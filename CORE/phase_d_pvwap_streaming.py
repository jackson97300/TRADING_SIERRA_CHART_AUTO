"""phase_d_pvwap_streaming.py — Port streaming `add_pvwap_d_features`.

Calcule pvwap, pvwap_sd1u, pvwap_sd1d (VWAP veille) + distances normalisees
pour la session en cours.

Port de `CORE/phase_d_dalton_levels.py:add_pvwap_d_features` (batch) vers une
version streaming stateful, integrable dans `enricher_chain.py` apres l'engine
`phase_b_plus_streaming` qui produit `vwap_d`, `vwap_d_sd1u`, `vwap_d_sd1d`.

Strategie :
  1. A chaque bar, lire `vwap_d`, `vwap_d_sd1u`, `vwap_d_sd1d` du payload (deja
     calcules par phase_b_plus_streaming)
  2. Detecter changement de session via `session_date_trading` (ou `date_et`
     fallback). Au changement :
     - Snapshot des valeurs EOD de la session precedente comme pvwap pour la
       nouvelle session
     - Reset l'EOD tracker
  3. Tracker en continu les valeurs EOD = dernieres valeurs vues
  4. Emit dist_pvwap_pct, dist_pvwap_sd1u_pct, dist_pvwap_sd1d_pct

Causalite :
  - La 1ere bar d'une nouvelle session a la valeur pvwap = EOD de la session
    PRECEDENTE (deja vue, donc passe).
  - Pas de lookahead.

Edge case : 1ere session vue depuis boot du service = pas de session
precedente -> pvwap = NaN. C'est normal (warmup 1 jour comme batch).

Features generees (6) :
  - pvwap, pvwap_sd1u, pvwap_sd1d (prix absolus, helpers)
  - dist_pvwap_pct, dist_pvwap_sd1u_pct, dist_pvwap_sd1d_pct (ML-usable)

Source unique de verite documentee :
  - `project_source_data_unique_jsonl_live_20260523.md` : JSONL live = source
    unique, doit avoir TOUS les niveaux institutionnels (Jackson 23/05).

Auteur : MIA Trading V2
  v1.0 (2026-05-23) : port initial requested by Jackson "ON DOIS AVOIR TOUT
                       LES NIVEAU"
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class PVWAPStreamState:
    """State streaming PVWAP. Pickle-safe : primitifs seulement."""
    # Date de la session courante (string YYYY-MM-DD ou similaire)
    current_session_date: Optional[str] = None
    # EOD tracker pour la session courante (mis a jour a chaque bar)
    current_eod_vwap_d: Optional[float] = None
    current_eod_vwap_d_sd1u: Optional[float] = None
    current_eod_vwap_d_sd1d: Optional[float] = None
    # Snapshot EOD de la session precedente (utilise pour pvwap session courante)
    prev_session_eod_vwap_d: Optional[float] = None
    prev_session_eod_vwap_d_sd1u: Optional[float] = None
    prev_session_eod_vwap_d_sd1d: Optional[float] = None
    # 24/05/2026 PM Jackson : flag pour eviter de re-tenter le seed bootstrap
    # apres premier essai (lazy load au 1er bar, 1 tentative max par run process).
    _seed_attempted: bool = False


# 24/05/2026 PM Jackson directive : seed file lu au cold start pour bootstrap
# prev_session_eod_vwap_d depuis le dernier vwap_d du JSONL de la session
# precedente. Genere par BOT/bootstrap_pvwap.ps1.
_PVWAP_SEED_FILE = Path(
    os.environ.get(
        "MIA_PVWAP_SEED_FILE",
        str(Path(__file__).resolve().parents[1] / "DATA" / "state" / "pvwap_seed.json"),
    )
)


def _try_seed_pvwap(state: "PVWAPStreamState", symbol: Optional[str]) -> bool:
    """Charge prev_session_eod_vwap_d depuis le seed file si applicable.

    Lazy load : appele au 1er bar quand state.prev_session_eod_vwap_d is None
    ET state.current_session_date is None (= cold start, jamais de session vue).
    Sans seed file ou erreur : no-op silencieux (laisse NaN).

    Returns True si seed applique, False sinon.
    """
    if state._seed_attempted or not symbol:
        return False
    state._seed_attempted = True  # 1 tentative max par process
    try:
        if not _PVWAP_SEED_FILE.exists():
            return False
        # utf-8-sig pour gerer le BOM ajoute par PowerShell Set-Content -Encoding UTF8
        with open(_PVWAP_SEED_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        # Normalise le symbol : Databento "NQ.c.0" -> "NQ", "ES.c.0" -> "ES".
        # Le seed est indexe par racine sans suffixe continuous.
        sym_root = symbol.split(".")[0] if "." in symbol else symbol
        sym_data = data.get(sym_root)
        if not isinstance(sym_data, dict):
            return False
        v = sym_data.get("vwap_d")
        if v is None:
            return False
        state.prev_session_eod_vwap_d = float(v)
        sd1u = sym_data.get("vwap_d_sd1u")
        if sd1u is not None:
            state.prev_session_eod_vwap_d_sd1u = float(sd1u)
        sd1d = sym_data.get("vwap_d_sd1d")
        if sd1d is not None:
            state.prev_session_eod_vwap_d_sd1d = float(sd1d)
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def make_pvwap_stream_state() -> PVWAPStreamState:
    """Factory : state initial vide. Seed lazy load au 1er bar via _try_seed_pvwap."""
    return PVWAPStreamState()


def _is_valid_float(v) -> bool:
    """True si v est un float fini (pas None, pas NaN)."""
    if v is None:
        return False
    try:
        f = float(v)
        if f != f:    # NaN check
            return False
        return True
    except (TypeError, ValueError):
        return False


def add_phase_d_pvwap_streaming(row: dict, state: PVWAPStreamState) -> dict:
    """Sub-engine streaming PVWAP (6 features).

    Args:
        row : dict avec close, session_date_trading (ou date_et fallback),
              vwap_d, vwap_d_sd1u, vwap_d_sd1d
        state : PVWAPStreamState mutable

    Returns:
        dict row + 6 features (pvwap*, dist_pvwap_*).
    """
    out = dict(row)

    # 1. Identifier session courante (priorite session_date_trading, fallback date_et)
    sess_date = row.get("session_date_trading")
    if sess_date is None or (isinstance(sess_date, float) and sess_date != sess_date):
        sess_date = row.get("date_et")

    # Si pas de session date du tout, on ne peut rien faire
    if sess_date is None:
        out["pvwap"] = np.nan
        out["pvwap_sd1u"] = np.nan
        out["pvwap_sd1d"] = np.nan
        out["dist_pvwap_pct"] = np.nan
        out["dist_pvwap_sd1u_pct"] = np.nan
        out["dist_pvwap_sd1d_pct"] = np.nan
        return out

    # FIX P0-A code-reviewer 23/05 : normalisation defensive du type.
    # `session_date_trading` peut etre datetime.date OU pd.Timestamp OU str.
    # str(datetime.date(2026,5,21)) = '2026-05-21'
    # str(pd.Timestamp('2026-05-21')) = '2026-05-21 00:00:00'
    # = collision DIFFERENTES strings pour MEME date -> roll session faux declenche.
    # Solution : ISO format si date-like, sinon str() fallback.
    if hasattr(sess_date, "isoformat"):
        sess_date_str = sess_date.isoformat()
        # date.isoformat() = '2026-05-21', datetime.isoformat() = '2026-05-21T00:00:00'
        # Normalisation : ne garder que la partie date YYYY-MM-DD
        if "T" in sess_date_str:
            sess_date_str = sess_date_str.split("T", 1)[0]
        elif " " in sess_date_str:
            sess_date_str = sess_date_str.split(" ", 1)[0]
    else:
        sess_date_str = str(sess_date)
        # Idem si pd.Timestamp converti via str() : prendre seulement partie date
        if " " in sess_date_str:
            sess_date_str = sess_date_str.split(" ", 1)[0]

    # 24/05/2026 PM Jackson directive : bootstrap seed PVWAP. Le state est
    # persiste via pickle (live_enricher_state.py), donc apres restart le state
    # garde current_session_date != None (= ancien run) mais peut avoir
    # prev_session_eod_vwap_d=None si le service avait demarre apres le weekend
    # gap (= cas dimanche 24/05). Tenter le seed des que prev_session_eod_vwap_d
    # est None, independamment de current_session_date.
    if state.prev_session_eod_vwap_d is None and not state._seed_attempted:
        _try_seed_pvwap(state, row.get("symbol"))

    # 2. Detection changement de session
    if state.current_session_date is None:
        # Premier bar vu : init session courante, pas de session precedente
        state.current_session_date = sess_date_str
    elif sess_date_str != state.current_session_date:
        # Roll session : snapshot EOD courant -> prev, reset courant
        # Garde uniquement si EOD courant valide (sinon le prev reste comme il etait)
        if _is_valid_float(state.current_eod_vwap_d):
            state.prev_session_eod_vwap_d = state.current_eod_vwap_d
            state.prev_session_eod_vwap_d_sd1u = state.current_eod_vwap_d_sd1u
            state.prev_session_eod_vwap_d_sd1d = state.current_eod_vwap_d_sd1d
        state.current_session_date = sess_date_str
        state.current_eod_vwap_d = None
        state.current_eod_vwap_d_sd1u = None
        state.current_eod_vwap_d_sd1d = None

    # 3. Update EOD tracker = dernieres valeurs vwap_d vues dans cette session
    vwap_d_cur = row.get("vwap_d")
    if _is_valid_float(vwap_d_cur):
        state.current_eod_vwap_d = float(vwap_d_cur)
    vwap_d_sd1u_cur = row.get("vwap_d_sd1u")
    if _is_valid_float(vwap_d_sd1u_cur):
        state.current_eod_vwap_d_sd1u = float(vwap_d_sd1u_cur)
    vwap_d_sd1d_cur = row.get("vwap_d_sd1d")
    if _is_valid_float(vwap_d_sd1d_cur):
        state.current_eod_vwap_d_sd1d = float(vwap_d_sd1d_cur)

    # 4. Emit pvwap (prix absolus) = EOD de la session precedente
    pvwap = state.prev_session_eod_vwap_d
    pvwap_sd1u = state.prev_session_eod_vwap_d_sd1u
    pvwap_sd1d = state.prev_session_eod_vwap_d_sd1d

    out["pvwap"] = float(pvwap) if pvwap is not None else np.nan
    out["pvwap_sd1u"] = float(pvwap_sd1u) if pvwap_sd1u is not None else np.nan
    out["pvwap_sd1d"] = float(pvwap_sd1d) if pvwap_sd1d is not None else np.nan

    # 5. Emit distances normalisees (en %)
    close = row.get("close")
    if not _is_valid_float(close) or float(close) <= 0:
        out["dist_pvwap_pct"] = np.nan
        out["dist_pvwap_sd1u_pct"] = np.nan
        out["dist_pvwap_sd1d_pct"] = np.nan
        return out

    close_f = float(close)

    # NOTE convention : (close - pvwap) / close * 100
    # = positif si close > pvwap (close au-dessus du niveau)
    # = negatif si close < pvwap (close en-dessous du niveau)
    # Coherent avec dist_vwap_d_pct convention compliant DMP C++
    if _is_valid_float(pvwap):
        out["dist_pvwap_pct"] = (close_f - float(pvwap)) / close_f * 100
    else:
        out["dist_pvwap_pct"] = np.nan

    if _is_valid_float(pvwap_sd1u):
        out["dist_pvwap_sd1u_pct"] = (close_f - float(pvwap_sd1u)) / close_f * 100
    else:
        out["dist_pvwap_sd1u_pct"] = np.nan

    if _is_valid_float(pvwap_sd1d):
        out["dist_pvwap_sd1d_pct"] = (close_f - float(pvwap_sd1d)) / close_f * 100
    else:
        out["dist_pvwap_sd1d_pct"] = np.nan

    return out
