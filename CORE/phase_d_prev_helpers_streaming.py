"""phase_d_prev_helpers_streaming.py — Port streaming prev_* session helpers.

Calcule 10 features Previous Session helpers + distances pct ML-usable :
  - prev_vah, prev_val, prev_vpoc (EOD broadcast Volume Area session J-1)
  - pdh, pdl (Previous Day High/Low 24h, incluant overnight)
  - dist_prev_vah_pct, dist_prev_val_pct, dist_prev_vpoc_pct (ML)
  - dist_pdh_pct, dist_pdl_pct (ML)

# Contexte INCIDENT #76 (19/06/2026)

Audit empirique 5j ES + 4j NQ confirme : tous les helpers `prev_*` Sierra
emis par DMP C++ varient INTRA-SESSION (2-4 distinct values par session)
alors qu'ils devraient etre CONSTANTS = EOD broadcast J-1 fige.

Pattern racine : aliases DMP C++ `prev_*` pointent vers etude COURANTE
au lieu de figer EOD snapshot. Meme bug que pvwap (INCIDENT #75).

Consumers prod degrades (4 bots paper actifs) :
  - Bot 2 BN V4 (`bn_v4_engine.py:89-90, 102-103`) : 4 features ML
  - Bot 2 BN V4 sierra_compat
  - Bot 3 v3 continuation (Tier 3 PREV_VAL, PREV_VAH)
  - Bot 3 v3 sierra_reader (reconstruction Python fallback)
  - Bot 3 level_definitions (Tier 2-3)
  - Bot 3 Gold (Tier 2 : PREV_VAH, PREV_VAL, PDH, PDL — 4 features)

# Strategie

Pattern identique a `phase_d_pvwap_streaming.py` (INCIDENT #75) :
  1. Tracker EOD courant via cur_vah/val/vpoc + bar_high/bar_low (24h)
  2. Detection cross-day via session_date_trading
  3. Au boundary : snapshot EOD courant -> prev_session_*, reset trackers
  4. Emit 5 helpers absolus + 5 distances pct (convention DMP signed)

# Sources

| Feature | Source | Note |
|---------|--------|------|
| prev_vah | cur_vah | EOD final |
| prev_val | cur_val | EOD final |
| prev_vpoc | cur_vpoc | EOD final |
| pdh | max(bar_high) 24h | NOT cash_high (RTH-only). Verifie empirique 15/06 ES : max(bar_high) 24h=7560 == pdh broadcast 7560, cash_high RTH=7498. |
| pdl | min(bar_low) 24h | symetrique pdh |

# Convention de signe DMP (cf phase_d_pvwap_streaming INCIDENT #75 fix)

`DMP_F3_DistNormalisees.h:101` : DMP_CalcDistPct(close, level) = (level - close) / close * 100
POSITIF si level > close (niveau AU-DESSUS du prix)
NEGATIF si level < close (niveau EN-DESSOUS du prix)

Coherent avec Bot 3 v3 fallback `bot3_v3_sierra_reader.py:747`,
Bot 2 BN V4 sierra_compat:85-97, et 5 consumers prod.

# Feature flags (Q5 Plan agent)

- MIA_PREV_VA_WIRE_ENABLED (default "1") : prev_vah/val/vpoc (low risk)
- MIA_PREV_DAY_HL_WIRE_ENABLED (default "1") : pdh/pdl (Q2 source = bar_high)

Separes car sources differentes : si pdh/pdl produit valeurs erronees en
prod (Q2 racine), rollback pdh sans affecter prev_vah/val/vpoc.

Date : 2026-06-19
Reviewed : Plan agent (GO-AVEC-RESERVES, Q1-Q5 traitees) + code-reviewer (a venir)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


# ════════════════════════════════════════════════════════════════════════════
# STATE
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class PrevHelpersState:
    """State streaming PrevHelpers. Pickle-safe : primitifs seulement.

    5 trackers EOD courants + 5 snapshots prev session + session metadata.

    Vocation EOD broadcast : NE PAS reinstancier au cross-day reset
    (pattern composite_poc INCIDENT #58 + pvwap INCIDENT #75).
    """
    # Date session courante (ISO YYYY-MM-DD)
    current_session_date: Optional[str] = None

    # ── Trackers EOD courants (alimentes a chaque bar valide) ──
    # Sources cur_vah/val/vpoc : Volume Area session courante
    current_eod_vah: Optional[float] = None
    current_eod_val: Optional[float] = None
    current_eod_vpoc: Optional[float] = None
    # Sources bar_high/bar_low : extremes session 24h (incluant overnight)
    # Q2 Plan agent : pdh != cash_high (RTH only), pdh = max(bar_high) 24h.
    current_eod_session_high: Optional[float] = None  # cumul max bar_high
    current_eod_session_low: Optional[float] = None   # cumul min bar_low

    # ── Snapshots prev session (broadcast sur session courante) ──
    prev_session_vah: Optional[float] = None
    prev_session_val: Optional[float] = None
    prev_session_vpoc: Optional[float] = None
    prev_session_pdh: Optional[float] = None
    prev_session_pdl: Optional[float] = None

    # Seed bootstrap flag (1 tentative max par run)
    _seed_attempted: bool = False


# 19/06 Plan agent Q5 : 2 feature flags separes (sources differentes)
_FLAG_VA = "MIA_PREV_VA_WIRE_ENABLED"   # prev_vah/val/vpoc
_FLAG_HL = "MIA_PREV_DAY_HL_WIRE_ENABLED"  # pdh/pdl


# Seed file pattern (similaire pvwap_seed.json)
_PREV_HELPERS_SEED_FILE = Path(
    os.environ.get(
        "MIA_PREV_HELPERS_SEED_FILE",
        str(Path(__file__).resolve().parents[1] / "DATA" / "state"
            / "prev_helpers_seed.json"),
    )
)


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _is_valid_float(v) -> bool:
    """True si v est un float fini (pas None, pas NaN, pas Inf)."""
    if v is None:
        return False
    try:
        f = float(v)
        if f != f:  # NaN check
            return False
        if f == float("inf") or f == float("-inf"):
            return False
        return True
    except (TypeError, ValueError):
        return False


def _try_seed_prev_helpers(
    state: PrevHelpersState, symbol: Optional[str]
) -> bool:
    """Bootstrap prev_session_* depuis seed file si disponible.

    Lazy load au 1er bar quand state.prev_session_pdh is None ET
    state.current_session_date is None (cold start).

    Returns True si seed applique, False sinon.
    """
    if state._seed_attempted or not symbol:
        return False
    state._seed_attempted = True
    try:
        if not _PREV_HELPERS_SEED_FILE.exists():
            return False
        with open(_PREV_HELPERS_SEED_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        sym_root = symbol.split(".")[0] if "." in symbol else symbol
        sym_data = data.get(sym_root)
        if not isinstance(sym_data, dict):
            return False
        for src, attr in [
            ("vah", "prev_session_vah"),
            ("val", "prev_session_val"),
            ("vpoc", "prev_session_vpoc"),
            ("pdh", "prev_session_pdh"),
            ("pdl", "prev_session_pdl"),
        ]:
            v = sym_data.get(src)
            if v is not None:
                try:
                    setattr(state, attr, float(v))
                except (TypeError, ValueError):
                    pass
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def make_prev_helpers_state() -> PrevHelpersState:
    """Factory : state initial vide. Seed lazy au 1er bar via _try_seed."""
    return PrevHelpersState()


def _normalize_session_date(sess_date) -> Optional[str]:
    """Normalise session_date_trading vers ISO YYYY-MM-DD.

    Cf phase_d_pvwap_streaming.py:166-184 FIX P0-A code-reviewer 23/05 :
    pd.Timestamp vs datetime.date vs str = collisions silencieuses.
    Forcer ISO YYYY-MM-DD partout.
    """
    if sess_date is None:
        return None
    if isinstance(sess_date, float) and sess_date != sess_date:
        return None
    if hasattr(sess_date, "isoformat"):
        s = sess_date.isoformat()
        if "T" in s:
            s = s.split("T", 1)[0]
        elif " " in s:
            s = s.split(" ", 1)[0]
        return s
    s = str(sess_date)
    if " " in s:
        s = s.split(" ", 1)[0]
    return s


# ════════════════════════════════════════════════════════════════════════════
# CORE
# ════════════════════════════════════════════════════════════════════════════

def add_phase_d_prev_helpers_streaming(
    row: dict, state: PrevHelpersState
) -> dict:
    """Sub-engine streaming PrevHelpers (10 features).

    Args:
        row : dict avec close, session_date_trading (ou date_et fallback),
              cur_vah, cur_val, cur_vpoc, bar_high, bar_low.
              Optionnel : symbol (pour seed bootstrap).
        state : PrevHelpersState mutable persistent across bars.

    Returns:
        dict row + 10 features (5 helpers + 5 dist_*_pct).
        Cold-start (warmup) : NaN partout, pas de fallback silencieux.

    Convention de signe DMP (verifie DMP_F3_DistNormalisees.h:101) :
        dist_X_pct = (level - close) / close * 100
        POSITIF si level > close (niveau au-dessus)
        NEGATIF si level < close (niveau en-dessous)
    """
    out = dict(row)
    flag_va = os.environ.get(_FLAG_VA, "1") == "1"
    flag_hl = os.environ.get(_FLAG_HL, "1") == "1"

    # ── 1. Detection session courante ──
    sess_date_raw = row.get("session_date_trading")
    if sess_date_raw is None:
        sess_date_raw = row.get("date_et")
    sess_date_str = _normalize_session_date(sess_date_raw)

    if sess_date_str is None:
        # Pas de session connue : impossible de calculer. NaN partout.
        for k in ("prev_vah", "prev_val", "prev_vpoc", "pdh", "pdl",
                  "dist_prev_vah_pct", "dist_prev_val_pct",
                  "dist_prev_vpoc_pct", "dist_pdh_pct", "dist_pdl_pct"):
            out[k] = np.nan
        return out

    # ── 2. Bootstrap seed si dispo (cold-start post-restart) ──
    # Plan agent Q1 : non-atomique, pattern PVWAP. Seed tente UNE fois
    # si tous les snapshots prev sont None.
    all_prev_none = all(
        getattr(state, attr) is None
        for attr in ("prev_session_vah", "prev_session_val",
                     "prev_session_vpoc", "prev_session_pdh",
                     "prev_session_pdl")
    )
    if all_prev_none and not state._seed_attempted:
        _try_seed_prev_helpers(state, row.get("symbol"))

    # ── 3. Detection changement session + snapshot EOD prev ──
    if state.current_session_date is None:
        state.current_session_date = sess_date_str
    elif sess_date_str != state.current_session_date:
        # Roll session : EOD courant -> prev. Garde l'ancien si EOD invalide
        # (semantique non-atomique pattern PVWAP, Q1 Plan agent).
        if _is_valid_float(state.current_eod_vah):
            state.prev_session_vah = state.current_eod_vah
        if _is_valid_float(state.current_eod_val):
            state.prev_session_val = state.current_eod_val
        if _is_valid_float(state.current_eod_vpoc):
            state.prev_session_vpoc = state.current_eod_vpoc
        if _is_valid_float(state.current_eod_session_high):
            state.prev_session_pdh = state.current_eod_session_high
        if _is_valid_float(state.current_eod_session_low):
            state.prev_session_pdl = state.current_eod_session_low
        # Reset trackers session courante
        state.current_session_date = sess_date_str
        state.current_eod_vah = None
        state.current_eod_val = None
        state.current_eod_vpoc = None
        state.current_eod_session_high = None
        state.current_eod_session_low = None

    # ── 4. Update trackers EOD courants ──
    # cur_vah/val/vpoc = derniere valeur vue (EOD broadcast)
    for src, attr in [
        ("cur_vah", "current_eod_vah"),
        ("cur_val", "current_eod_val"),
        ("cur_vpoc", "current_eod_vpoc"),
    ]:
        v = row.get(src)
        if _is_valid_float(v):
            setattr(state, attr, float(v))

    # bar_high / bar_low = MAX cumul session J (incluant overnight, Q2 fix)
    bh = row.get("bar_high")
    if bh is None:
        bh = row.get("high")
    if _is_valid_float(bh):
        bh_f = float(bh)
        cur_h = state.current_eod_session_high
        if cur_h is None or bh_f > cur_h:
            state.current_eod_session_high = bh_f

    bl = row.get("bar_low")
    if bl is None:
        bl = row.get("low")
    if _is_valid_float(bl):
        bl_f = float(bl)
        cur_l = state.current_eod_session_low
        if cur_l is None or bl_f < cur_l:
            state.current_eod_session_low = bl_f

    # ── 5. Emit helpers absolus prev_* (NaN si cold-start) ──
    # Helpers VA : controle par flag_va
    if flag_va:
        out["prev_vah"] = (
            float(state.prev_session_vah)
            if _is_valid_float(state.prev_session_vah)
            else np.nan
        )
        out["prev_val"] = (
            float(state.prev_session_val)
            if _is_valid_float(state.prev_session_val)
            else np.nan
        )
        out["prev_vpoc"] = (
            float(state.prev_session_vpoc)
            if _is_valid_float(state.prev_session_vpoc)
            else np.nan
        )
    # Helpers Day H/L : controle par flag_hl
    if flag_hl:
        out["pdh"] = (
            float(state.prev_session_pdh)
            if _is_valid_float(state.prev_session_pdh)
            else np.nan
        )
        out["pdl"] = (
            float(state.prev_session_pdl)
            if _is_valid_float(state.prev_session_pdl)
            else np.nan
        )

    # ── 6. Emit distances pct (convention DMP signed) ──
    close = row.get("close")
    if not _is_valid_float(close) or float(close) <= 0:
        if flag_va:
            out["dist_prev_vah_pct"] = np.nan
            out["dist_prev_val_pct"] = np.nan
            out["dist_prev_vpoc_pct"] = np.nan
        if flag_hl:
            out["dist_pdh_pct"] = np.nan
            out["dist_pdl_pct"] = np.nan
        return out

    close_f = float(close)

    def _dist_pct(level: Optional[float]) -> float:
        """(level - close) / close * 100. NaN si level invalide."""
        if not _is_valid_float(level):
            return np.nan
        return (float(level) - close_f) / close_f * 100

    if flag_va:
        out["dist_prev_vah_pct"] = _dist_pct(state.prev_session_vah)
        out["dist_prev_val_pct"] = _dist_pct(state.prev_session_val)
        out["dist_prev_vpoc_pct"] = _dist_pct(state.prev_session_vpoc)
    if flag_hl:
        out["dist_pdh_pct"] = _dist_pct(state.prev_session_pdh)
        out["dist_pdl_pct"] = _dist_pct(state.prev_session_pdl)

    return out
