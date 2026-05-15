"""
phase_b_helpers.py — Pre-compute helpers pour Phase B (port modules V1 sur v4)

Calcule les colonnes derivees necessaires aux modules V1 (game_changers, rvol,
intermarket) a partir du dataset v4_enriched (OHLCV Databento + MQ DMP merges).

Inputs : DataFrame v4_enriched + Trades parquet (pour Volume Profile reel).
Outputs : DataFrame enrichi avec :
  - delta_pct, finish_strength, range_size  (rvol)
  - ib_high, ib_low, ib_range, ib_complete, ib_atr  (game_changers + sessions)
  - sess_high, sess_low, dist_sess_high, dist_sess_low  (sessions)
  - open_cash, price_1030  (game_changers open_type)
  - prev_vah, prev_val, prev_vpoc, pdh, pdl  (game_changers open_zone)
  - cur_vah, cur_val, cur_vpoc  (rolling features)
  - cvd_day  (existant cvd_session, alias pour code V1)
  - ts (alias ts_event en ms epoch)

Convention :
  - Tous les timestamps en UTC (Databento natif)
  - Sessions ET via zoneinfo("America/New_York")
  - Ne MODIFIE PAS les colonnes existantes du v4_enriched

Auteur : Phase B Session 1 (2026-04-26)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller doit passer tick explicitement
                  # via tick=get_tick_size(symbol). Voir CORE/constants.py.


# ═══════════════════════════════════════════════════════════════════════════════
# DEFAULT BOUNDS (per-symbol session windows, en minutes ET depuis minuit)
# ═══════════════════════════════════════════════════════════════════════════════
# Aligne sur les defaults documentes dans add_session_metadata + add_ib_features.
# Si caller ne passe pas bounds, on utilise ES/NQ defaults.
DEFAULT_BOUNDS_ES_NQ = {
    "asia_start": 1080,      # 18:00 ET (= overnight start, session +1 day)
    "us_start": 570,         # 09:30 ET (RTH start ES/NQ)
    "us_after_start": 960,   # 16:00 ET (RTH end / after-hours start)
}

# Cles obligatoires pour bounds (utilise par _resolve_bounds anti-fallback silencieux)
_BOUNDS_REQUIRED_KEYS = ("asia_start", "us_start", "us_after_start")


def _resolve_bounds(bounds: dict | None) -> dict:
    """FIX P0-1 audit code-reviewer (13/05 nuit) : harmonise batch + stream.

    Source UNIQUE de verite pour bounds. Evite silent fallback Pattern 11 :
      - Si bounds is None : retourne copie DEFAULT_BOUNDS_ES_NQ
      - Si bounds est dict partiel (cle manquante) : RAISE KeyError explicite
        (fail-loud cohesion lessons.md anti silent default)
      - Si bounds dict complet : retourne tel quel

    Cf incident `.claude/rules/lessons.md` Gamma hardcode 0.0 fallback +
    `tick-size-policy.md` anti-pattern #3 (silent fallback = bug garanti).

    Args:
        bounds : None ou dict (potentiellement partiel).

    Returns:
        dict complet avec toutes les cles requises.

    Raises:
        KeyError : si bounds dict partiel (cle requise manquante).
    """
    if bounds is None:
        return dict(DEFAULT_BOUNDS_ES_NQ)
    if not isinstance(bounds, dict):
        raise TypeError(
            f"bounds must be dict or None (got {type(bounds).__name__})"
        )
    missing = [k for k in _BOUNDS_REQUIRED_KEYS if k not in bounds]
    if missing:
        raise KeyError(
            f"bounds dict missing required keys: {missing}. "
            f"Required: {list(_BOUNDS_REQUIRED_KEYS)}. "
            f"Use DEFAULT_BOUNDS_ES_NQ as template ou passer None pour defaults."
        )
    return bounds


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SESSION HELPERS (ET timezone)
# ═══════════════════════════════════════════════════════════════════════════════

def add_session_metadata(df: pd.DataFrame, bounds: dict | None = None) -> pd.DataFrame:
    """
    Ajoute date_et, mins_et, session_date_trading, is_cash_session, is_ib_window.

    FIX 4 (review code-reviewer 26/04) : ajout `session_date_trading` qui aligne
    avec convention CME (session lundi = dim 18:00 ET -> lun 17:00 ET).
    Calcul : si mins_et >= 1080 (18:00) ET, session = date_et + 1 jour.
    Permet sess_high/low de couvrir la session entiere (overnight inclus).
    """
    df = df.copy()
    # FIX P0-1 audit 13/05 nuit : _resolve_bounds harmonise batch + stream,
    # raise KeyError explicite si bounds partiel (anti silent fallback Pattern 11).
    b = _resolve_bounds(bounds)
    ts_et = df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET) if df["ts_event"].dt.tz is None else df["ts_event"].dt.tz_convert(ET)
    df["date_et"] = ts_et.dt.date
    df["mins_et"] = ts_et.dt.hour * 60 + ts_et.dt.minute
    # Session trading date = date+1 si on est apres asia_start
    df["session_date_trading"] = np.where(
        df["mins_et"] >= b["asia_start"],
        (ts_et + pd.Timedelta(days=1)).dt.date,
        df["date_et"],
    )
    # Cash session = us_start -> us_after_start (defaults ES 09:30-16:00, MGC 08:30-13:30)
    df["is_cash_session"] = ((df["mins_et"] >= b["us_start"]) & (df["mins_et"] < b["us_after_start"])).astype("int8")
    # IB window = us_start -> us_start+60 (1ere heure de RTH : 09:30-10:30 ES, 08:30-09:30 MGC)
    df["is_ib_window"] = ((df["mins_et"] >= b["us_start"]) & (df["mins_et"] < b["us_start"] + 60)).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# API STREAMING sub-engine #1 (Chantier 3 Phase 3b Lundi)
# ═══════════════════════════════════════════════════════════════════════════════
# Pattern uniforme Plan agent Option D : engine streaming-aware avec @dataclass
# State + apply_*_streaming(row, state) -> dict. DRY garanti via tests parite.
#
# add_session_metadata est STATELESS : transformations row-level pures
# (timezone UTC->ET, hour/minute extraction, comparaison seuils bounds).
# AUCUN state rolling. SessionMetadataState reserve evolution future.
# (dataclass/field deja importes top-of-module)


@dataclass
class SessionMetadataState:
    """State sub-engine #1 phase_b_helpers — STATELESS (factory uniforme).

    Aucun state rolling. Convention uniforme avec engines stateful Phase 3b+.
    """
    pass


def add_session_metadata_streaming(
    row: dict,
    state: SessionMetadataState,
    bounds: dict | None = None,
) -> dict:
    """API streaming sub-engine #1 (Chantier 3 Phase 3b Lundi).

    Reproduit fidelement add_session_metadata() en mode row-by-row :
      ts_event UTC -> ET timezone conversion
      mins_et = hour * 60 + minute
      date_et = ts_et.date()
      session_date_trading = date_et + 1 jour si mins_et >= asia_start, sinon date_et
      is_cash_session = 1 si us_start <= mins_et < us_after_start
      is_ib_window = 1 si us_start <= mins_et < us_start + 60

    Args:
        row : dict avec 'ts_event' (pandas.Timestamp ou datetime).
        state : SessionMetadataState (factory uniforme, non utilise).
        bounds : dict overrides asia_start/us_start/us_after_start (default ES/NQ).

    Returns:
        dict row + {date_et, mins_et, session_date_trading, is_cash_session,
        is_ib_window}.
    """
    out = dict(row)
    # FIX P0-1 audit 13/05 nuit : utilise _resolve_bounds (idem batch), raise
    # KeyError explicite si dict partiel au lieu de silent fallback default.
    b = _resolve_bounds(bounds)

    ts = out.get("ts_event")
    if ts is None:
        out["date_et"] = None
        out["mins_et"] = None
        out["session_date_trading"] = None
        out["is_cash_session"] = 0
        out["is_ib_window"] = 0
        return out

    # Convertir UTC -> ET
    if isinstance(ts, pd.Timestamp):
        if ts.tz is None:
            ts_et = ts.tz_localize("UTC").tz_convert(ET)
        else:
            ts_et = ts.tz_convert(ET)
    else:
        # datetime non-pandas : convertir via pd.Timestamp
        ts_pd = pd.Timestamp(ts)
        if ts_pd.tz is None:
            ts_et = ts_pd.tz_localize("UTC").tz_convert(ET)
        else:
            ts_et = ts_pd.tz_convert(ET)

    mins_et = ts_et.hour * 60 + ts_et.minute
    date_et = ts_et.date()

    # session_date_trading : date+1 si mins_et >= asia_start
    if mins_et >= b["asia_start"]:
        session_date_trading = (ts_et + pd.Timedelta(days=1)).date()
    else:
        session_date_trading = date_et

    out["date_et"] = date_et
    out["mins_et"] = mins_et
    out["session_date_trading"] = session_date_trading
    out["is_cash_session"] = 1 if (b["us_start"] <= mins_et < b["us_after_start"]) else 0
    out["is_ib_window"] = 1 if (b["us_start"] <= mins_et < b["us_start"] + 60) else 0
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INITIAL BALANCE (IB)
# ═══════════════════════════════════════════════════════════════════════════════

def add_ib_features(df: pd.DataFrame, tick: float = TICK_SIZE,
                     bounds: dict | None = None) -> pd.DataFrame:
    """ib_high/low/range/complete/atr/broken + position_pct.

    FIX 27/04 (anti-leak) : ib_high/low broadcast a tout le jour creait un leak
    pour les bars avant 10:30 ET (fin IB). Bars 09:30-10:30 voyaient le futur de
    la fenetre IB. Solution : masker ib_high/low/range a NaN si ib_complete=0
    (avant 10:30 ET). Distances et derives suivent automatiquement le mask.

    Detection bug : SHAP analysis 27/04 -> dist_ib_high_pct #5 SHAP, dist_ib_low_pct #8.
    Voir DOCS/INCIDENT_LOG.md 2026-04-27 20:30 (cascade leak features broadcast).
    """
    df = df.copy()
    # FIX P0-1 audit sub-engine #2 : utilise _resolve_bounds (fail-loud, aligne
    # avec sub-engine #1 + add_session_metadata). Anti regression Pattern 11
    # silent fallback `(bounds or {...})["us_start"]`.
    b = _resolve_bounds(bounds)
    if "date_et" not in df.columns:
        df = add_session_metadata(df, bounds=b)

    # IB stats par jour : max(high)/min(low) sur fenetre 1h apres us_start
    # ES/NQ : 09:30-10:30 ET, MGC : 08:30-09:30 ET (RTH gold COMEX)
    us_start = b["us_start"]
    ib_close = us_start + 60
    ib_rows = df[df["is_ib_window"] == 1]
    ib_agg = ib_rows.groupby("date_et").agg(
        ib_high=("high", "max"),
        ib_low=("low", "min"),
    ).reset_index()
    df = df.merge(ib_agg, on="date_et", how="left")

    # ib_complete : 1 si bar apres us_start+60 (fin IB window per-symbole)
    df["ib_complete"] = (df["mins_et"] >= ib_close).astype("int8")

    # FIX ANTI-LEAK : masker ib_high/low avant 10:30 ET (IB pas encore termine)
    is_pre_ib_close = df["ib_complete"] == 0
    df.loc[is_pre_ib_close, "ib_high"] = np.nan
    df.loc[is_pre_ib_close, "ib_low"] = np.nan

    df["ib_range_ticks"] = ((df["ib_high"] - df["ib_low"]) / tick).round().astype("float64")
    df["ib_range"] = df["ib_high"] - df["ib_low"]
    df["ib_broken_up"] = ((df["ib_complete"] == 1) & (df["high"] > df["ib_high"])).astype("int8")
    df["ib_broken_dn"] = ((df["ib_complete"] == 1) & (df["low"] < df["ib_low"])).astype("int8")
    # Distances IB en pct (NOUVEAU - normalised, ML-usable). NaN avant 10:30 ET (anti-leak).
    df["dist_ib_high_pct"] = ((df["ib_high"] - df["close"]) / df["close"] * 100).astype("float64")
    df["dist_ib_low_pct"] = ((df["close"] - df["ib_low"]) / df["close"] * 100).astype("float64")

    # ib_position_pct (uniquement si ib_complete)
    ib_rng = df["ib_range"].replace(0, np.nan)
    pos = (df["close"] - df["ib_low"]) / ib_rng
    df["ib_position_pct"] = pos.where(df["ib_complete"] == 1)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# API STREAMING sub-engine #2 (Chantier 3 Phase 3b Lundi)
# ═══════════════════════════════════════════════════════════════════════════════
# add_ib_features STATEFUL : maintient ib_high/low cumulative pendant IB window
# (09:30-10:30 ET ES/NQ, 08:30-09:30 MGC), reset par session date_et.
#
# Anti-leak : ib_high/low masqué à NaN avant ib_complete=1 (= mins_et >= us_start+60).
# Pendant IB window : state mis à jour bar par bar MAIS output reste NaN.
# Après IB window : state figé, broadcast à toutes bars du jour jusqu'à reset session.
#
# Edge case (Pattern 11 risk) : cold start mid-IB (boot service 09:45 ET) =
# state ib_high/low partiel (manque bars 09:30-09:44) -> divergence vs batch
# qui voit toute la fenêtre. Mitigation : warmup_from_v4 obligatoire au boot.


@dataclass
class IBState:
    """State sub-engine #2 add_ib_features — daily IB high/low cumulative.

    Reset automatique à chaque nouvelle session (date_et change).
    Pickle-safe : tous attributs serialisables.
    """
    current_date_et: Optional[Any] = None  # date | None
    ib_high: Optional[float] = None
    ib_low: Optional[float] = None
    n_ib_bars_seen: int = 0  # diagnostic warmup partial


def add_ib_features_streaming(
    row: dict,
    state: IBState,
    tick: float = TICK_SIZE,
    bounds: dict | None = None,
) -> dict:
    """API streaming sub-engine #2 add_ib_features (Chantier 3 Phase 3b).

    Reproduit fidèlement add_ib_features() batch :
      ib_high/low : max/min sur IB window (09:30-10:30 ES/NQ, 08:30-09:30 MGC)
      ib_complete : 1 si mins_et >= us_start + 60
      Anti-leak : ib_high/low = NaN si ib_complete=0 (output, state préservé)
      ib_range, ib_range_ticks, ib_broken_up/dn, dist_ib_high/low_pct,
      ib_position_pct dérivés.

    Args:
        row : dict avec ts_event + date_et + mins_et + is_ib_window + high/low/close.
              Doit avoir été enrichi par add_session_metadata_streaming au préalable.
        state : IBState mutable (current_date_et, ib_high, ib_low).
        tick : tick size (0.25 ES/NQ, 0.10 MGC).
        bounds : config bounds (idem add_session_metadata).

    Returns:
        dict row + {ib_high, ib_low, ib_range, ib_range_ticks, ib_complete,
        ib_broken_up, ib_broken_dn, dist_ib_high_pct, dist_ib_low_pct, ib_position_pct}.
    """
    out = dict(row)
    b = _resolve_bounds(bounds)
    us_start = b["us_start"]
    ib_close = us_start + 60

    # 1. Détecter nouvelle session via date_et
    # FIX P1.2 audit sub-engine #2 : raise explicite si date_et absent (anti
    # silent miscompute Pattern 11 - state pollue cross-session si row sans
    # session_metadata appele avant). Convention : ordre engines impose
    # add_session_metadata_streaming AVANT add_ib_features_streaming.
    date_et = out.get("date_et")
    if date_et is None:
        raise ValueError(
            "add_ib_features_streaming requires 'date_et' in row. "
            "Call add_session_metadata_streaming BEFORE add_ib_features_streaming "
            "(ordre engines : session_metadata -> ib_features)."
        )
    if date_et != state.current_date_et:
        # Reset state (nouvelle session)
        state.current_date_et = date_et
        state.ib_high = None
        state.ib_low = None
        state.n_ib_bars_seen = 0

    # 2. Update state pendant IB window
    is_ib_window = out.get("is_ib_window", 0)
    high = out.get("high")
    low = out.get("low")
    if is_ib_window == 1 and high is not None and low is not None:
        try:
            if not (pd.isna(high) or pd.isna(low)):
                hf, lf = float(high), float(low)
                if state.ib_high is None or hf > state.ib_high:
                    state.ib_high = hf
                if state.ib_low is None or lf < state.ib_low:
                    state.ib_low = lf
                state.n_ib_bars_seen += 1
        except (TypeError, ValueError):
            pass

    # 3. ib_complete
    mins_et = out.get("mins_et")
    ib_complete = 1 if (mins_et is not None and mins_et >= ib_close) else 0
    out["ib_complete"] = ib_complete

    # 4. Output ib_high/low (anti-leak : NaN si ib_complete=0)
    if ib_complete == 1 and state.ib_high is not None and state.ib_low is not None:
        ib_high_out = state.ib_high
        ib_low_out = state.ib_low
    else:
        ib_high_out = np.nan
        ib_low_out = np.nan
    out["ib_high"] = ib_high_out
    out["ib_low"] = ib_low_out

    # 5. ib_range, ib_range_ticks (suivent le mask)
    if not (pd.isna(ib_high_out) or pd.isna(ib_low_out)):
        ib_range = ib_high_out - ib_low_out
        ib_range_ticks = round(ib_range / tick)
    else:
        ib_range = np.nan
        ib_range_ticks = np.nan
    out["ib_range"] = ib_range
    out["ib_range_ticks"] = float(ib_range_ticks) if not pd.isna(ib_range_ticks) else np.nan

    # 6. ib_broken_up/dn (uniquement si ib_complete=1)
    if ib_complete == 1 and not pd.isna(ib_high_out) and high is not None:
        try:
            out["ib_broken_up"] = 1 if float(high) > ib_high_out else 0
        except (TypeError, ValueError):
            out["ib_broken_up"] = 0
    else:
        out["ib_broken_up"] = 0
    if ib_complete == 1 and not pd.isna(ib_low_out) and low is not None:
        try:
            out["ib_broken_dn"] = 1 if float(low) < ib_low_out else 0
        except (TypeError, ValueError):
            out["ib_broken_dn"] = 0
    else:
        out["ib_broken_dn"] = 0

    # 7. dist_ib_high_pct, dist_ib_low_pct (suivent mask, NaN si pre-IB)
    close = out.get("close")
    if close is not None and not pd.isna(close) and float(close) != 0.0:
        cf = float(close)
        if not pd.isna(ib_high_out):
            out["dist_ib_high_pct"] = (ib_high_out - cf) / cf * 100
        else:
            out["dist_ib_high_pct"] = np.nan
        if not pd.isna(ib_low_out):
            out["dist_ib_low_pct"] = (cf - ib_low_out) / cf * 100
        else:
            out["dist_ib_low_pct"] = np.nan
    else:
        out["dist_ib_high_pct"] = np.nan
        out["dist_ib_low_pct"] = np.nan

    # 8. ib_position_pct (uniquement si ib_complete=1 ET ib_range > 0)
    if (ib_complete == 1 and not pd.isna(ib_range) and ib_range > 0
            and close is not None and not pd.isna(close)):
        out["ib_position_pct"] = (float(close) - ib_low_out) / ib_range
    else:
        out["ib_position_pct"] = np.nan

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# API STREAMING sub-engine #3 (Chantier 3 Phase 3b Mardi)
# ═══════════════════════════════════════════════════════════════════════════════
# add_session_high_low STATEFUL : 2 axes de cumulatif parallele
#   - sess_high/low : groupby session_date_trading (CME futures dim 18h -> ven 17h)
#   - cash_high/low : groupby date_et AND is_cash_session=1 (RTH 09:30-16:00 ET)
#
# Anti-leak / parite batch :
#   - cash_high/low = NaN si is_cash_session=0 (mirror df.where(cash_mask))
#   - is_new_*_high/low = 0 sur first bar de session (mirror prev.shift(1).isna())
#   - is_new_cash_high/low = 0 si gap cash (prev row NOT cash, mirror NaN shift)
#
# Edge case GAP cash (halt mid-session) :
#   En batch : df.where(cash_mask)["cash_high"].shift(1) -> NaN si prev bar
#   etait hors cash, donc is_new_cash_high = 0 meme si high > prev_state.
#   En stream : track state.prev_output_cash_high (NaN si prev row pas cash).


@dataclass
class SessionHighLowState:
    """State sub-engine #3 add_session_high_low — 2 axes parallele.

    Reset automatique :
      - sess_*  : nouvelle session_date_trading (CME futures)
      - cash_*  : nouvelle date_et (RTH cash)

    Track prev_output_cash_high pour matcher exactement le comportement
    batch shift(1) sur output masque (anti edge case halt cash).
    """
    # CME futures session (dim 18h ET -> ven 17h ET, contigu)
    current_session_date_trading: Optional[Any] = None
    sess_high: Optional[float] = None
    sess_low: Optional[float] = None
    sess_n_bars: int = 0

    # Cash session RTH (09:30-16:00 ET, peut avoir gap halt)
    current_date_et: Optional[Any] = None
    cash_high: Optional[float] = None
    cash_low: Optional[float] = None
    cash_n_bars: int = 0
    # FIX edge case parite : prev row output cash_high/low (NaN si pas cash)
    # mirror batch df.groupby("date_et")["cash_high"].shift(1) qui propage NaN
    prev_output_cash_high: Optional[float] = None
    prev_output_cash_low: Optional[float] = None


def add_session_high_low_streaming(
    row: dict,
    state: SessionHighLowState,
    tick: float = TICK_SIZE,
) -> dict:
    """API streaming sub-engine #3 add_session_high_low (Chantier 3 Phase 3b).

    Reproduit fidelement add_session_high_low() batch sur 12 features :
      sess_high, sess_low, dist_sess_high_pct, dist_sess_low_pct,
      is_new_sess_high, is_new_sess_low,
      cash_high, cash_low, dist_cash_high_pct, dist_cash_low_pct,
      is_new_cash_high, is_new_cash_low.

    Args:
        row : dict avec session_date_trading + date_et + is_cash_session
              + high/low/close. Requiert add_session_metadata_streaming AVANT.
        state : SessionHighLowState mutable.
        tick : tick size (unused mais conserve pour signature symetrique).

    Returns:
        dict row + 12 features.

    Raises:
        ValueError si session_date_trading ou date_et absent (ordre engines).
    """
    out = dict(row)

    # Fail-loud ordre engines (anti silent miscompute Pattern 11)
    session_date_trading = out.get("session_date_trading")
    if session_date_trading is None:
        raise ValueError(
            "add_session_high_low_streaming requires 'session_date_trading' in row. "
            "Call add_session_metadata_streaming BEFORE."
        )
    date_et = out.get("date_et")
    if date_et is None:
        raise ValueError(
            "add_session_high_low_streaming requires 'date_et' in row. "
            "Call add_session_metadata_streaming BEFORE."
        )

    high = out.get("high")
    low = out.get("low")
    close = out.get("close")
    # FIX P1-B audit code-reviewer : coercion explicite int pour gerer bool/float
    # (is_cash_session peut etre np.True_, np.int8, 1.0, etc. selon pipeline).
    # `or 0` protege contre None implicite.
    try:
        _ics_raw = out.get("is_cash_session", 0)
        is_cash_session = int(_ics_raw) if _ics_raw is not None else 0
    except (TypeError, ValueError):
        is_cash_session = 0

    # NOTE P1-A audit : divergence theorique close==0 (batch produit inf,
    # stream produit NaN). Probabilite zero sur futures ES/NQ/MGC (prix
    # toujours > 0). Garde defensive maintenue pour eviter ZeroDivisionError
    # Python (numpy le tolere mais Python natif raise). Test atol 1e-9
    # ignorerait NaN-vs-NaN ; pas de fix prod tant que close=0 impossible.

    # ─── PARTIE 1 : SESSION HIGH/LOW (CME futures session) ──────────────────
    # Reset state si nouvelle session_date_trading
    if session_date_trading != state.current_session_date_trading:
        state.current_session_date_trading = session_date_trading
        state.sess_high = None
        state.sess_low = None
        state.sess_n_bars = 0

    # Snapshot prev AVANT update (pour is_new_sess_high/low)
    prev_sess_high = state.sess_high
    prev_sess_low = state.sess_low

    # Update state si high/low valides
    if high is not None and low is not None:
        try:
            if not (pd.isna(high) or pd.isna(low)):
                hf, lf = float(high), float(low)
                if state.sess_high is None or hf > state.sess_high:
                    state.sess_high = hf
                if state.sess_low is None or lf < state.sess_low:
                    state.sess_low = lf
                state.sess_n_bars += 1
        except (TypeError, ValueError):
            pass

    sess_high_out = state.sess_high if state.sess_high is not None else np.nan
    sess_low_out = state.sess_low if state.sess_low is not None else np.nan
    out["sess_high"] = sess_high_out
    out["sess_low"] = sess_low_out

    # dist_sess_*_pct
    if close is not None and not pd.isna(close) and float(close) != 0.0:
        cf = float(close)
        out["dist_sess_high_pct"] = (
            (sess_high_out - cf) / cf * 100 if not pd.isna(sess_high_out) else np.nan
        )
        out["dist_sess_low_pct"] = (
            (cf - sess_low_out) / cf * 100 if not pd.isna(sess_low_out) else np.nan
        )
    else:
        out["dist_sess_high_pct"] = np.nan
        out["dist_sess_low_pct"] = np.nan

    # is_new_sess_high/low (event detection)
    # Batch : prev = shift(1) dans session_date_trading group.
    # First bar de session -> prev None -> force 0.
    # Subsequent bars : new si high > prev OU low < prev.
    is_new_sh = 0
    is_new_sl = 0
    if prev_sess_high is not None and high is not None and not pd.isna(high):
        try:
            if float(high) > prev_sess_high:
                is_new_sh = 1
        except (TypeError, ValueError):
            pass
    if prev_sess_low is not None and low is not None and not pd.isna(low):
        try:
            if float(low) < prev_sess_low:
                is_new_sl = 1
        except (TypeError, ValueError):
            pass
    out["is_new_sess_high"] = is_new_sh
    out["is_new_sess_low"] = is_new_sl

    # ─── PARTIE 2 : CASH HIGH/LOW (RTH 09:30-16:00 ET) ──────────────────────
    # Reset state si nouvelle date_et (cash est ANCRE sur date_et calendar,
    # contrairement a session_date_trading qui couvre dim->ven)
    if date_et != state.current_date_et:
        state.current_date_et = date_et
        state.cash_high = None
        state.cash_low = None
        state.cash_n_bars = 0
        state.prev_output_cash_high = None
        state.prev_output_cash_low = None

    # Update state UNIQUEMENT pendant cash session
    if (
        is_cash_session == 1
        and high is not None
        and low is not None
    ):
        try:
            if not (pd.isna(high) or pd.isna(low)):
                hf, lf = float(high), float(low)
                if state.cash_high is None or hf > state.cash_high:
                    state.cash_high = hf
                if state.cash_low is None or lf < state.cash_low:
                    state.cash_low = lf
                state.cash_n_bars += 1
        except (TypeError, ValueError):
            pass

    # Output cash_high/low : NaN si is_cash_session=0 (mirror df.where(cash_mask))
    if is_cash_session == 1 and state.cash_high is not None:
        cash_high_out = state.cash_high
        cash_low_out = state.cash_low
    else:
        cash_high_out = np.nan
        cash_low_out = np.nan
    out["cash_high"] = cash_high_out
    out["cash_low"] = cash_low_out

    # dist_cash_*_pct
    if close is not None and not pd.isna(close) and float(close) != 0.0:
        cf = float(close)
        out["dist_cash_high_pct"] = (
            (cash_high_out - cf) / cf * 100 if not pd.isna(cash_high_out) else np.nan
        )
        out["dist_cash_low_pct"] = (
            (cf - cash_low_out) / cf * 100 if not pd.isna(cash_low_out) else np.nan
        )
    else:
        out["dist_cash_high_pct"] = np.nan
        out["dist_cash_low_pct"] = np.nan

    # is_new_cash_high/low : mirror batch shift(1) sur OUTPUT cash_high
    # Si prev_output_cash_high == NaN (= prev row pas en cash ou first bar)
    # -> force 0 meme si high > state.cash_high (edge case gap halt).
    is_new_ch = 0
    is_new_cl = 0
    prev_out_ch = state.prev_output_cash_high
    prev_out_cl = state.prev_output_cash_low
    if (
        is_cash_session == 1
        and prev_out_ch is not None
        and not pd.isna(prev_out_ch)
        and high is not None
        and not pd.isna(high)
    ):
        try:
            if float(high) > prev_out_ch:
                is_new_ch = 1
        except (TypeError, ValueError):
            pass
    if (
        is_cash_session == 1
        and prev_out_cl is not None
        and not pd.isna(prev_out_cl)
        and low is not None
        and not pd.isna(low)
    ):
        try:
            if float(low) < prev_out_cl:
                is_new_cl = 1
        except (TypeError, ValueError):
            pass
    out["is_new_cash_high"] = is_new_ch
    out["is_new_cash_low"] = is_new_cl

    # Update prev_output_* pour next row (apres avoir produit is_new_*)
    state.prev_output_cash_high = (
        cash_high_out if not pd.isna(cash_high_out) else None
    )
    state.prev_output_cash_low = (
        cash_low_out if not pd.isna(cash_low_out) else None
    )

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SESSION HIGH/LOW (cumulative)
# ═══════════════════════════════════════════════════════════════════════════════

def add_session_high_low(df: pd.DataFrame, tick: float = TICK_SIZE,
                          bounds: dict | None = None) -> pd.DataFrame:
    """
    sess_high/low cumulatif par session trading (CME : dim 18:00 ET -> ven 17:00 ET).
    + cash_high/low (cash session 09:30-16:00 ET seulement)
    + is_new_sess_high/low + is_new_cash_high/low (event detection)
    """
    df = df.copy()
    if "session_date_trading" not in df.columns:
        df = add_session_metadata(df, bounds=bounds)

    # Full trading session HH/LL
    df["sess_high"] = df.groupby("session_date_trading")["high"].cummax()
    df["sess_low"] = df.groupby("session_date_trading")["low"].cummin()
    df["dist_sess_high_pct"] = ((df["sess_high"] - df["close"]) / df["close"] * 100).astype("float64")
    df["dist_sess_low_pct"] = ((df["close"] - df["sess_low"]) / df["close"] * 100).astype("float64")
    # is_new event : high de cette barre > sess_high de la barre precedente
    prev_sess_high = df.groupby("session_date_trading")["sess_high"].shift(1)
    prev_sess_low = df.groupby("session_date_trading")["sess_low"].shift(1)
    df["is_new_sess_high"] = (df["high"] > prev_sess_high.fillna(-np.inf)).astype("int8")
    df["is_new_sess_low"] = (df["low"] < prev_sess_low.fillna(np.inf)).astype("int8")
    # First bar of session : pas un new high/low
    df.loc[prev_sess_high.isna(), "is_new_sess_high"] = 0
    df.loc[prev_sess_low.isna(), "is_new_sess_low"] = 0

    # Cash session HH/LL (09:30-16:00 ET only)
    cash_mask = df["is_cash_session"] == 1
    df["cash_high"] = df.where(cash_mask).groupby("date_et")["high"].cummax()
    df["cash_low"] = df.where(cash_mask).groupby("date_et")["low"].cummin()
    df["dist_cash_high_pct"] = ((df["cash_high"] - df["close"]) / df["close"] * 100).astype("float64")
    df["dist_cash_low_pct"] = ((df["close"] - df["cash_low"]) / df["close"] * 100).astype("float64")
    prev_cash_high = df.groupby("date_et")["cash_high"].shift(1)
    prev_cash_low = df.groupby("date_et")["cash_low"].shift(1)
    df["is_new_cash_high"] = ((df["high"] > prev_cash_high.fillna(-np.inf)) & cash_mask).astype("int8")
    df["is_new_cash_low"] = ((df["low"] < prev_cash_low.fillna(np.inf)) & cash_mask).astype("int8")
    df.loc[prev_cash_high.isna() | ~cash_mask, "is_new_cash_high"] = 0
    df.loc[prev_cash_low.isna() | ~cash_mask, "is_new_cash_low"] = 0
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 4. OPEN CASH + PRICE 10:30
# ═══════════════════════════════════════════════════════════════════════════════

def add_open_cash_price1030(df: pd.DataFrame, bounds: dict | None = None) -> pd.DataFrame:
    """open_cash (close de barre us_start) + price_1030 (close de barre us_start+60).

    Per-symbole (Chantier 4 10/05/2026) :
      - ES/NQ : open_cash = 09:30 ET, price_1030 = 10:30 ET
      - MGC   : open_cash = 08:30 ET, price_1030 = 09:30 ET (RTH gold +1h IB)
    """
    df = df.copy()
    if "date_et" not in df.columns:
        df = add_session_metadata(df, bounds=bounds)
    # Fix code-reviewer P1 R2 R1 : harmoniser avec streaming via _resolve_bounds
    # (raise KeyError explicite vs silent fallback `(bounds or {...})` Pattern 11).
    b = _resolve_bounds(bounds)
    us_start = b["us_start"]
    ib_close = us_start + 60  # fin IB = 1h apres us_start
    # Open cash = close de la barre us_start
    open_cash = df[df["mins_et"] == us_start].groupby("date_et")["close"].first().rename("open_cash")
    # Price 10:30 (ou 09:30 MGC) = close de la barre us_start+60, premiere apres IB complete
    price_1030 = df[df["mins_et"] == ib_close].groupby("date_et")["close"].first().rename("price_1030")
    df = df.merge(open_cash, on="date_et", how="left")
    df = df.merge(price_1030, on="date_et", how="left")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# add_open_cash_price1030 STREAMING (Pass P1 fix B1 - 15/05/2026)
# ═══════════════════════════════════════════════════════════════════════════════
# Code-reviewer P1 NOGO : `add_open_cash_price1030` batch-only n'etait jamais
# appele dans `_process_bar_cycle` -> open_cash/price_1030 = None -> game_changers
# retournait UNKNOWN constant (Pattern V1 reproduit).
# Cette version streaming capture close a us_start ET us_start+60, puis broadcast
# sur les bars suivantes du meme date_et (per-symbole bounds).

@dataclass
class OpenCashPrice1030State:
    """State streaming add_open_cash_price1030 - capture+broadcast per date_et.

    Pickle-safe : primitifs + Optional[Any] (date).
    """
    current_date_et: Optional[Any] = None
    cached_open_cash: Optional[float] = None
    cached_price_1030: Optional[float] = None


def add_open_cash_price1030_streaming(
    row: dict,
    state: OpenCashPrice1030State,
    bounds: dict | None = None,
) -> dict:
    """Sub-engine streaming open_cash + price_1030.

    Reproduit batch add_open_cash_price1030 :
      - open_cash = close de la bar mins_et == us_start (1ere bar cash)
      - price_1030 = close de la bar mins_et == us_start + 60 (1ere post-IB)
      - Broadcast cached values sur toutes bars du meme date_et

    Args:
        row : dict avec date_et + mins_et (Pass 4c-prereq session_metadata) + close.
        state : OpenCashPrice1030State mutable.
        bounds : per-symbole us_start (ES/NQ=570, MGC=510).

    Returns:
        dict row + {open_cash, price_1030}.
    """
    out = dict(row)
    b = _resolve_bounds(bounds)
    us_start = b["us_start"]
    ib_close = us_start + 60

    date_et = out.get("date_et")
    mins_et = out.get("mins_et")
    close = out.get("close")

    # Reset cache si nouveau jour
    if date_et != state.current_date_et:
        state.current_date_et = date_et
        state.cached_open_cash = None
        state.cached_price_1030 = None

    # Capture close si on est SUR la bar us_start ou us_start+60
    if mins_et is not None and close is not None:
        try:
            mins_int = int(mins_et)
            close_f = float(close)
            if mins_int == us_start and state.cached_open_cash is None:
                state.cached_open_cash = close_f
            elif mins_int == ib_close and state.cached_price_1030 is None:
                state.cached_price_1030 = close_f
        except (TypeError, ValueError):
            pass

    # Broadcast valeurs cached (None si pas encore capture)
    out["open_cash"] = state.cached_open_cash if state.cached_open_cash is not None else np.nan
    out["price_1030"] = state.cached_price_1030 if state.cached_price_1030 is not None else np.nan
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# API STREAMING sub-engine #4 (Chantier 3 Phase 3b Mardi soir)
# ═══════════════════════════════════════════════════════════════════════════════
# add_volume_profile_features STATEFUL : 16 features VPOC/VAH/VAL/PDH/PDL
# Plus complexe que sub-engines #1-3 :
#   1. Depend de TRADES (pas seulement OHLCV) : trades_in_window list
#   2. State maintient running price_volume dict cumulatif intraday
#   3. Reset session_date_trading : transfert cur_* -> prev_* (frozen)
#
# DIVERGENCE BATCH/STREAM DOCUMENTEE (INCIDENT_LOG 2026-05-13 14:30) :
#   - Batch : cur_vpoc CONSTANT per session (calcule fin de session sur ALL trades)
#   - Stream : cur_vpoc EVOLUE intraday (running VPOC sur trades accumules)
#   - Parite VRAIE uniquement sur LAST BAR de chaque session
#   - Feature distribution shift potentiel intraday : ml-trainer review obligatoire
#     avant deploy production.
#
# Edge cases :
#   - Premiere bar de session : price_volume vide -> cur_vpoc = NaN
#   - Session sans trades : cur_vpoc/vah/val = NaN (gere par compute_volume_profile_dict)
#   - prev_* = NaN pour la PREMIERE session vue (pas de session precedente)


@dataclass
class VolumeProfileState:
    """State sub-engine #4 add_volume_profile_features.

    Maintient :
      - current_session_date_trading : pour detecter rotation
      - price_volume : dict cumulatif {price_bucket -> size} pour session courante
      - pdh/pdl_running : max/min des trades de la session courante
      - prev_* : stats session precedente (frozen apres rotation)
      - cur_* cache (recompute on demand depuis price_volume)

    Pickle-safe : dict primitif, floats, Any pour date.
    """
    current_session_date_trading: Optional[Any] = None
    # Running cumulative pour session courante
    price_volume: Dict[float, float] = field(default_factory=dict)
    pdh_running: Optional[float] = None
    pdl_running: Optional[float] = None
    # Previous session FROZEN stats (transferred at session boundary)
    prev_vpoc: Optional[float] = None
    prev_vah: Optional[float] = None
    prev_val: Optional[float] = None
    prev_pdh: Optional[float] = None
    prev_pdl: Optional[float] = None
    # Diagnostic
    n_trades_session: int = 0


def add_volume_profile_features_streaming(
    row: dict,
    state: VolumeProfileState,
    trades_in_window: Optional[list] = None,
    tick: float = TICK_SIZE,
    value_area_pct: float = 70.0,
) -> dict:
    """API streaming sub-engine #4 add_volume_profile_features.

    Reproduit add_volume_profile_features() batch sur 16 features avec
    RUNNING VPOC intraday (vs batch constant intraday — voir INCIDENT_LOG).

    Args:
        row : dict avec session_date_trading + close. Requiert add_session_metadata
              AVANT (ordre engines).
        state : VolumeProfileState mutable.
        trades_in_window : list[dict] {price, size} - trades depuis la barre
              precedente. None ou [] = pas de nouveaux trades (cur_* preserve).
        tick : tick size (0.25 ES/NQ, 0.10 MGC).
        value_area_pct : % volume cible Value Area (70% default Steidlmayer).

    Returns:
        dict row + 16 features :
          cur_vpoc, cur_vah, cur_val, cur_pdh, cur_pdl,
          prev_vpoc, prev_vah, prev_val, pdh, pdl,
          inside_value_area, poc_migration_dir,
          dist_cur_vpoc_pct, dist_cur_vah_pct, dist_cur_val_pct,
          dist_prev_vpoc_pct, dist_prev_vah_pct, dist_prev_val_pct,
          dist_pdh_pct, dist_pdl_pct

    Raises:
        ValueError si session_date_trading absent.
    """
    out = dict(row)

    session_date_trading = out.get("session_date_trading")
    if session_date_trading is None:
        raise ValueError(
            "add_volume_profile_features_streaming requires 'session_date_trading' "
            "in row. Call add_session_metadata_streaming BEFORE."
        )

    # 1. Detection rotation session -> transfert cur_* vers prev_*
    if session_date_trading != state.current_session_date_trading:
        # Finaliser la session precedente (si existante) : compute final VPOC depuis
        # price_volume et transferer dans prev_* (frozen).
        if state.current_session_date_trading is not None and state.price_volume:
            final_vp = compute_volume_profile_dict(state.price_volume, value_area_pct)
            state.prev_vpoc = (
                final_vp["vpoc"] if not pd.isna(final_vp["vpoc"]) else None
            )
            state.prev_vah = (
                final_vp["vah"] if not pd.isna(final_vp["vah"]) else None
            )
            state.prev_val = (
                final_vp["val"] if not pd.isna(final_vp["val"]) else None
            )
            state.prev_pdh = state.pdh_running
            state.prev_pdl = state.pdl_running
        # Reset running pour nouvelle session
        state.current_session_date_trading = session_date_trading
        state.price_volume = {}
        state.pdh_running = None
        state.pdl_running = None
        state.n_trades_session = 0

    # 2. Accumuler trades_in_window dans price_volume
    if trades_in_window:
        for trade in trades_in_window:
            price = trade.get("price")
            size = trade.get("size")
            if price is None or size is None:
                continue
            try:
                pf = float(price)
                sf = float(size)
                if pd.isna(pf) or pd.isna(sf) or sf <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            # Bucket par tick
            bucket = round(pf / tick) * tick
            state.price_volume[bucket] = state.price_volume.get(bucket, 0.0) + sf
            # Update pdh/pdl running (sur prix de trade, pas bar high/low)
            if state.pdh_running is None or pf > state.pdh_running:
                state.pdh_running = pf
            if state.pdl_running is None or pf < state.pdl_running:
                state.pdl_running = pf
            state.n_trades_session += 1

    # 3. Compute running VPOC depuis state.price_volume
    if state.price_volume:
        cur_vp = compute_volume_profile_dict(state.price_volume, value_area_pct)
        cur_vpoc = cur_vp["vpoc"]
        cur_vah = cur_vp["vah"]
        cur_val = cur_vp["val"]
    else:
        cur_vpoc = np.nan
        cur_vah = np.nan
        cur_val = np.nan

    cur_pdh = state.pdh_running if state.pdh_running is not None else np.nan
    cur_pdl = state.pdl_running if state.pdl_running is not None else np.nan
    prev_vpoc = state.prev_vpoc if state.prev_vpoc is not None else np.nan
    prev_vah = state.prev_vah if state.prev_vah is not None else np.nan
    prev_val = state.prev_val if state.prev_val is not None else np.nan
    prev_pdh = state.prev_pdh if state.prev_pdh is not None else np.nan
    prev_pdl = state.prev_pdl if state.prev_pdl is not None else np.nan

    # 4. Output features de base
    out["cur_vpoc"] = cur_vpoc
    out["cur_vah"] = cur_vah
    out["cur_val"] = cur_val
    out["cur_pdh"] = cur_pdh
    out["cur_pdl"] = cur_pdl
    out["prev_vpoc"] = prev_vpoc
    out["prev_vah"] = prev_vah
    out["prev_val"] = prev_val
    out["pdh"] = prev_pdh  # nom batch : pdh = previous day high
    out["pdl"] = prev_pdl

    # 5. Derivees ML-usable (mirror batch ligne 879-892)
    close = out.get("close")
    # inside_value_area : close entre VAL et VAH
    if (
        close is not None and not pd.isna(close)
        and not pd.isna(cur_val) and not pd.isna(cur_vah)
    ):
        try:
            cf = float(close)
            out["inside_value_area"] = 1 if (cf >= cur_val and cf <= cur_vah) else 0
        except (TypeError, ValueError):
            out["inside_value_area"] = 0
    else:
        out["inside_value_area"] = 0

    # poc_migration_dir : sign(cur_vpoc - prev_vpoc)
    if not pd.isna(cur_vpoc) and not pd.isna(prev_vpoc):
        diff = cur_vpoc - prev_vpoc
        if diff > 0:
            out["poc_migration_dir"] = 1
        elif diff < 0:
            out["poc_migration_dir"] = -1
        else:
            out["poc_migration_dir"] = 0
    else:
        out["poc_migration_dir"] = 0

    # Distances pct (8 features) : (close - level) / close * 100
    if close is not None and not pd.isna(close):
        try:
            cf = float(close)
            if cf != 0.0:
                def _dist(level):
                    return (cf - level) / cf * 100 if not pd.isna(level) else np.nan
                out["dist_cur_vpoc_pct"] = _dist(cur_vpoc)
                out["dist_cur_vah_pct"] = _dist(cur_vah)
                out["dist_cur_val_pct"] = _dist(cur_val)
                out["dist_prev_vpoc_pct"] = _dist(prev_vpoc)
                out["dist_prev_vah_pct"] = _dist(prev_vah)
                out["dist_prev_val_pct"] = _dist(prev_val)
                out["dist_pdh_pct"] = _dist(prev_pdh)
                out["dist_pdl_pct"] = _dist(prev_pdl)
            else:
                for k in ("dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
                          "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
                          "dist_pdh_pct", "dist_pdl_pct"):
                    out[k] = np.nan
        except (TypeError, ValueError):
            for k in ("dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
                      "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
                      "dist_pdh_pct", "dist_pdl_pct"):
                out[k] = np.nan
    else:
        for k in ("dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
                  "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
                  "dist_pdh_pct", "dist_pdl_pct"):
            out[k] = np.nan

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 5. VOLUME PROFILE (Trades-based)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_volume_profile_dict(volume_by_price: dict, value_area_pct: float = 70.0) -> dict:
    """
    Algo Steidlmayer standard : VPOC + extension VA jusqu'a 70% volume.

    Args:
        volume_by_price: dict[price -> total_volume]
        value_area_pct: % volume cible (70% default)
    Returns:
        dict{vpoc, vah, val, total_vol}
    """
    if not volume_by_price:
        return {"vpoc": np.nan, "vah": np.nan, "val": np.nan, "total_vol": 0}
    total_vol = sum(volume_by_price.values())
    if total_vol <= 0:
        return {"vpoc": np.nan, "vah": np.nan, "val": np.nan, "total_vol": 0}
    target_vol = total_vol * value_area_pct / 100

    prices_sorted = sorted(volume_by_price.keys())
    vpoc = max(volume_by_price, key=volume_by_price.get)
    poc_idx = prices_sorted.index(vpoc)
    cum_vol = volume_by_price[vpoc]
    low_idx = high_idx = poc_idx

    while cum_vol < target_vol and (low_idx > 0 or high_idx < len(prices_sorted) - 1):
        vol_up = volume_by_price[prices_sorted[high_idx + 1]] if high_idx < len(prices_sorted) - 1 else -1
        vol_dn = volume_by_price[prices_sorted[low_idx - 1]] if low_idx > 0 else -1
        if vol_up >= vol_dn:
            high_idx += 1
            cum_vol += vol_up
        else:
            low_idx -= 1
            cum_vol += vol_dn

    return {
        "vpoc": vpoc,
        "vah": prices_sorted[high_idx],
        "val": prices_sorted[low_idx],
        "total_vol": total_vol,
    }


def add_volume_profile_features(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    tick: float = TICK_SIZE,
    bounds: dict | None = None,
) -> pd.DataFrame:
    """
    Ajoute cur_vpoc/vah/val (current day) + prev_vpoc/vah/val (yesterday) + pdh/pdl.

    Si trades_df fourni, utilise vrai volume au tick.
    Sinon, fallback : approximation depuis OHLC bar (volume distribue uniformement
    entre low et high de chaque bar).
    """
    df = df.copy()
    if "date_et" not in df.columns:
        df = add_session_metadata(df, bounds=bounds)

    daily_profiles = {}
    daily_hl = {}

    # FIX 28/04 (Jackson) : grouper par session_date_trading (CME 18:00 ET cutoff)
    # au lieu de date_et (calendar UTC). Sinon les niveaux veille (prev_vpoc, pdh,
    # etc.) CHANGENT pendant 1 session CME (qui chevauche 2 calendar days).
    # Ces niveaux DOIVENT etre constants intraday = lignes horizontales SC,
    # comme les niveaux MenthorQ.
    if trades_df is None or trades_df.empty:
        print("  [WARN] No trades_df : cur/prev VPOC/VAH/VAL = NaN, pdh/pdl from OHLC")
        # pdh/pdl par session_date_trading (sinon split entre 2 calendar days)
        for sess_date, grp in df.groupby("session_date_trading"):
            daily_profiles[sess_date] = {"vpoc": np.nan, "vah": np.nan, "val": np.nan, "total_vol": 0}
            daily_hl[sess_date] = {"pdh": grp["high"].max(), "pdl": grp["low"].min()}
    else:
        # Vraie VAP depuis Trades, groupe par session_date_trading
        trades_df = trades_df.copy()
        trades_df["price_bucket"] = (trades_df["price"] / tick).round() * tick
        # Calculer session_date_trading sur trades (CME 18:00 ET cutoff)
        ts_et = trades_df["ts_event"].dt.tz_convert(ET)
        mins_et = ts_et.dt.hour * 60 + ts_et.dt.minute
        trades_df["session_date_trading"] = np.where(
            mins_et >= 1080,
            (ts_et + pd.Timedelta(days=1)).dt.date,
            ts_et.dt.date,
        )
        for sess_date, grp in trades_df.groupby("session_date_trading"):
            vbp = grp.groupby("price_bucket")["size"].sum().to_dict()
            daily_profiles[sess_date] = compute_volume_profile_dict(vbp)
            daily_hl[sess_date] = {"pdh": grp["price"].max(), "pdl": grp["price"].min()}

    # Map current session stats (utilisation session_date_trading -> constants intraday)
    df["cur_vpoc"] = df["session_date_trading"].map(lambda d: daily_profiles.get(d, {}).get("vpoc", np.nan))
    df["cur_vah"] = df["session_date_trading"].map(lambda d: daily_profiles.get(d, {}).get("vah", np.nan))
    df["cur_val"] = df["session_date_trading"].map(lambda d: daily_profiles.get(d, {}).get("val", np.nan))
    df["cur_pdh"] = df["session_date_trading"].map(lambda d: daily_hl.get(d, {}).get("pdh", np.nan))
    df["cur_pdl"] = df["session_date_trading"].map(lambda d: daily_hl.get(d, {}).get("pdl", np.nan))

    # Previous session stats (shift 1 trading session, pas calendar day)
    sorted_dates = sorted(daily_profiles.keys())
    prev_map = {d: sorted_dates[i - 1] for i, d in enumerate(sorted_dates) if i > 0}
    df["prev_vpoc"] = df["session_date_trading"].map(lambda d: daily_profiles.get(prev_map.get(d), {}).get("vpoc", np.nan))
    df["prev_vah"] = df["session_date_trading"].map(lambda d: daily_profiles.get(prev_map.get(d), {}).get("vah", np.nan))
    df["prev_val"] = df["session_date_trading"].map(lambda d: daily_profiles.get(prev_map.get(d), {}).get("val", np.nan))
    df["pdh"] = df["session_date_trading"].map(lambda d: daily_hl.get(prev_map.get(d), {}).get("pdh", np.nan))
    df["pdl"] = df["session_date_trading"].map(lambda d: daily_hl.get(prev_map.get(d), {}).get("pdl", np.nan))

    # Derivees ML-usable (NOUVEAU - E.1 inside_value_area + poc_migration_dir)
    # inside_value_area : close entre VAL et VAH (current day VP)
    df["inside_value_area"] = (
        (df["close"] >= df["cur_val"]) & (df["close"] <= df["cur_vah"])
    ).astype("int8")
    # poc_migration_dir : signe(cur_vpoc - prev_vpoc) -> +1 vpoc up, -1 vpoc down, 0 unchanged
    df["poc_migration_dir"] = np.sign(df["cur_vpoc"] - df["prev_vpoc"]).fillna(0).astype("int8")
    # Distances en pct (ML-usable)
    df["dist_cur_vpoc_pct"] = ((df["close"] - df["cur_vpoc"]) / df["close"] * 100).astype("float32")
    df["dist_cur_vah_pct"] = ((df["close"] - df["cur_vah"]) / df["close"] * 100).astype("float32")
    df["dist_cur_val_pct"] = ((df["close"] - df["cur_val"]) / df["close"] * 100).astype("float32")
    df["dist_prev_vpoc_pct"] = ((df["close"] - df["prev_vpoc"]) / df["close"] * 100).astype("float32")
    df["dist_prev_vah_pct"] = ((df["close"] - df["prev_vah"]) / df["close"] * 100).astype("float32")
    df["dist_prev_val_pct"] = ((df["close"] - df["prev_val"]) / df["close"] * 100).astype("float32")
    df["dist_pdh_pct"] = ((df["close"] - df["pdh"]) / df["close"] * 100).astype("float32")
    df["dist_pdl_pct"] = ((df["close"] - df["pdl"]) / df["close"] * 100).astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# API STREAMING sub-engine #5a (Chantier 3 Phase 3b Mercredi) — add_rvol_inputs
# ═══════════════════════════════════════════════════════════════════════════════
# add_rvol_inputs est STATELESS : transformations row-level pures (range_size,
# finish_strength, delta_pct, total_vol, ts). RvolInputsState reserve pour
# evolution future (factory uniforme avec sub-engines #1-4).


@dataclass
class RvolInputsState:
    """State sub-engine #5a — STATELESS (factory uniforme)."""
    pass


def add_rvol_inputs_streaming(
    row: dict,
    state: RvolInputsState,
    tick: float = TICK_SIZE,
) -> dict:
    """API streaming sub-engine #5a add_rvol_inputs.

    Reproduit add_rvol_inputs() batch sur 5 features :
      range_size, finish_strength, delta_pct, total_vol, ts (ms epoch UTC).

    Stateless : pas de dependence inter-row.

    Args:
        row : dict avec high, low, open, close, volume, delta_bar, ts_event.
        state : RvolInputsState (stateless, conserve symetrie API).
        tick : tick size (unused mais conserve signature symetrique).

    Returns:
        dict row + 5 features.
    """
    out = dict(row)

    # 1. range_size = high - low
    high = out.get("high")
    low = out.get("low")
    op = out.get("open")
    close = out.get("close")
    try:
        if high is not None and low is not None and not (pd.isna(high) or pd.isna(low)):
            range_size = float(high) - float(low)
        else:
            range_size = np.nan
    except (TypeError, ValueError):
        range_size = np.nan
    out["range_size"] = range_size

    # 2. finish_strength = (close - open) / range_size * 100, fillna(0)
    # Batch convention : range_size==0 -> NaN puis fillna(0)
    try:
        if (op is not None and close is not None and range_size is not None
                and not pd.isna(range_size) and range_size != 0.0):
            opf = float(op)
            cf = float(close)
            if pd.isna(opf) or pd.isna(cf):
                fs = 0.0
            else:
                fs = (cf - opf) / range_size * 100.0
                if pd.isna(fs):
                    fs = 0.0
        else:
            fs = 0.0
    except (TypeError, ValueError):
        fs = 0.0
    out["finish_strength"] = fs

    # 3. delta_pct = delta_bar / volume, fillna(0)
    volume = out.get("volume")
    delta_bar = out.get("delta_bar")
    try:
        if (volume is not None and delta_bar is not None
                and not pd.isna(volume) and not pd.isna(delta_bar)
                and float(volume) != 0.0):
            dp = float(delta_bar) / float(volume)
            if pd.isna(dp):
                dp = 0.0
        else:
            dp = 0.0
    except (TypeError, ValueError):
        dp = 0.0
    out["delta_pct"] = dp

    # 4. total_vol = float(volume)
    try:
        if volume is not None and not pd.isna(volume):
            out["total_vol"] = float(volume)
        else:
            out["total_vol"] = np.nan
    except (TypeError, ValueError):
        out["total_vol"] = np.nan

    # 5. ts = ts_event ms epoch (UTC). Batch convention :
    #    si tz-naive -> tz_localize("UTC") puis int64 // 1e6
    #    si tz-aware -> int64 // 1e6 direct
    ts_event = out.get("ts_event")
    if isinstance(ts_event, pd.Timestamp):
        if ts_event.tz is None:
            ts_ms = int(ts_event.tz_localize("UTC").value // 1_000_000)
        else:
            ts_ms = int(ts_event.value // 1_000_000)
        out["ts"] = ts_ms
    elif ts_event is not None:
        try:
            ts = pd.Timestamp(ts_event)
            if ts.tz is None:
                ts_ms = int(ts.tz_localize("UTC").value // 1_000_000)
            else:
                ts_ms = int(ts.value // 1_000_000)
            out["ts"] = ts_ms
        except (TypeError, ValueError):
            out["ts"] = None
    else:
        out["ts"] = None

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 6. RVOL PRE-COMPUTE (delta_pct, finish_strength, range_size)
# ═══════════════════════════════════════════════════════════════════════════════

def add_rvol_inputs(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Calcule les inputs requis par RvolEngine :
      - delta_pct = delta_bar / volume (entre -1 et 1)
      - finish_strength = (close - open) / range_size * 100 (signed, en %)
      - range_size = high - low (en points)
      - total_vol = alias pour volume (compat code V1)
      - ts = ts_event en ms epoch (compat code V1)
    """
    df = df.copy()
    df["range_size"] = df["high"] - df["low"]
    rng_safe = df["range_size"].replace(0, np.nan)
    df["finish_strength"] = ((df["close"] - df["open"]) / rng_safe * 100).fillna(0)
    vol_safe = df["volume"].replace(0, np.nan)
    df["delta_pct"] = (df["delta_bar"] / vol_safe).fillna(0)
    df["total_vol"] = df["volume"].astype(float)
    # ts en ms epoch (UTC) pour compat code V1 (rvol filter close)
    if df["ts_event"].dt.tz is None:
        df["ts"] = (df["ts_event"].dt.tz_localize("UTC").astype("int64") // 1_000_000).astype("int64")
    else:
        df["ts"] = (df["ts_event"].astype("int64") // 1_000_000).astype("int64")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# API STREAMING sub-engine #5b (Chantier 3 Phase 3b Mercredi) — add_ib_atr
# ═══════════════════════════════════════════════════════════════════════════════
# add_ib_atr STATEFUL : rolling mean(ib_range) sur lookback_days jours precedents.
# Convention shift(1) BATCH : le jour COURANT n'est PAS inclus dans le rolling.
# Donc le state contient UNIQUEMENT les sessions PASSEES (closes), pas la session
# courante. La capture de ib_range de la session courante se fait lors de la
# rotation (detection nouveau date_et).
#
# Dependence ordre engines : sub-engine #2 (ib_features) AVANT sub-engine #5b
# (ib_atr) — sinon ib_range absent du row. Convention pipeline.
#
# Edge case : si ib_range = NaN sur une session (pas d'IB complet), on n'ajoute
# PAS au deque (skip session, mirror batch groupby first skipna).


@dataclass
class IbAtrState:
    """State sub-engine #5b add_ib_atr — rolling ib_range jours passes.

    Maintient :
      - daily_ib_ranges : liste (date, ib_range) max lookback_days entries, FIFO
      - current_date : date_et de la session en cours (pas encore close)
      - current_session_ib_range : ib_range capture pour session courante
        (transfert vers daily_ib_ranges a la rotation)

    Pickle-safe : liste de tuples (date, float), date, Optional[float].
    """
    daily_ib_ranges: list = field(default_factory=list)  # list[(date, ib_range)]
    current_date: Optional[Any] = None
    current_session_ib_range: Optional[float] = None
    lookback_days: int = 14


def add_ib_atr_streaming(
    row: dict,
    state: IbAtrState,
    lookback_days: int = 14,
) -> dict:
    """API streaming sub-engine #5b add_ib_atr.

    Reproduit add_ib_atr() batch : ib_atr = mean(ib_range) sur les
    lookback_days jours PRECEDENTS (shift(1) batch). min_periods=3.

    Args:
        row : dict avec date_et + ib_range. Requiert add_session_metadata +
              add_ib_features AVANT (ordre engines).
        state : IbAtrState mutable.
        lookback_days : nombre de jours pour le rolling (default 14).

    Returns:
        dict row + {ib_atr}.

    Raises:
        ValueError si date_et absent (ordre engines).
    """
    out = dict(row)
    date_et = out.get("date_et")
    if date_et is None:
        raise ValueError(
            "add_ib_atr_streaming requires 'date_et' in row. "
            "Call add_session_metadata_streaming BEFORE."
        )

    # Sync lookback (au cas ou caller change le parametre entre appels)
    if state.lookback_days != lookback_days:
        state.lookback_days = lookback_days
        # Trim deque si reduction
        if len(state.daily_ib_ranges) > lookback_days:
            state.daily_ib_ranges = state.daily_ib_ranges[-lookback_days:]

    # 1. Detection rotation date_et -> transfert current_session_ib_range
    # vers daily_ib_ranges (= jour CLOS)
    if date_et != state.current_date:
        if (state.current_date is not None
                and state.current_session_ib_range is not None
                and not pd.isna(state.current_session_ib_range)):
            state.daily_ib_ranges.append(
                (state.current_date, float(state.current_session_ib_range))
            )
            # FIFO : trim a lookback_days
            if len(state.daily_ib_ranges) > lookback_days:
                state.daily_ib_ranges = state.daily_ib_ranges[-lookback_days:]
        state.current_date = date_et
        state.current_session_ib_range = None

    # 2. Capture ib_range pour la session courante (UNE seule fois par session)
    # Mirror batch groupby("date_et")["ib_range"].first() avec skipna=True default
    if state.current_session_ib_range is None:
        ib_range = out.get("ib_range")
        if ib_range is not None and not pd.isna(ib_range):
            try:
                state.current_session_ib_range = float(ib_range)
            except (TypeError, ValueError):
                pass

    # 3. Output ib_atr = mean(daily_ib_ranges values) si len >= 3 sinon NaN
    # NB : on n'inclut PAS current_session_ib_range (= shift(1) batch)
    if len(state.daily_ib_ranges) >= 3:
        values = [v for (_, v) in state.daily_ib_ranges]
        out["ib_atr"] = sum(values) / len(values)
    else:
        out["ib_atr"] = np.nan

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ATR (Average True Range) sur fenetre IB pour day_type
# ═══════════════════════════════════════════════════════════════════════════════

def add_ib_atr(df: pd.DataFrame, lookback_days: int = 14) -> pd.DataFrame:
    """
    ib_atr = moyenne(ib_range) sur lookback_days jours precedents.
    Utilise par classify_day_type pour normaliser ib_range.

    FIX 14/05/2026 (audit profond bug day_type=2 constants) :
    groupby("date_et") cascade le bug session fragmentation. Switch a
    groupby("session_date_trading") pour aligner sur les vraies sessions
    CME (18:00 ET cutoff). Sinon ib_atr peut etre NaN si mois single-day.
    """
    df = df.copy()
    if "ib_range" not in df.columns:
        raise ValueError("add_ib_features() doit etre appele avant add_ib_atr()")

    # Une valeur ib_range par session CME (constante intraday)
    group_key = "session_date_trading" if "session_date_trading" in df.columns else "date_et"
    daily_ib = df.groupby(group_key)["ib_range"].first().sort_index()
    ib_atr_series = daily_ib.shift(1).rolling(lookback_days, min_periods=3).mean()
    df["ib_atr"] = df[group_key].map(ib_atr_series)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ALL-IN-ONE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

PHASE_B_HELPER_COLS = {
    # Session
    "date_et", "mins_et", "session_date_trading", "is_cash_session", "is_ib_window",
    # IB
    "ib_high", "ib_low", "ib_range", "ib_range_ticks", "ib_complete",
    "ib_broken_up", "ib_broken_dn", "ib_position_pct", "ib_atr",
    "dist_ib_high_pct", "dist_ib_low_pct",
    # Session HL trading + cash + new event
    "sess_high", "sess_low", "dist_sess_high", "dist_sess_low",
    "dist_sess_high_pct", "dist_sess_low_pct",
    "is_new_sess_high", "is_new_sess_low",
    "cash_high", "cash_low", "dist_cash_high_pct", "dist_cash_low_pct",
    "is_new_cash_high", "is_new_cash_low",
    # Open cash + 10:30
    "open_cash", "price_1030",
    # Volume Profile
    "cur_vpoc", "cur_vah", "cur_val", "cur_pdh", "cur_pdl",
    "prev_vpoc", "prev_vah", "prev_val", "pdh", "pdl",
    "inside_value_area", "poc_migration_dir",
    "dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
    "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_pdh_pct", "dist_pdl_pct",
    # Phase C running (ecrasent cur_* EOD)
    "cur_va_n_buckets", "cur_va_total_vol",
    # RVOL inputs
    "delta_pct", "finish_strength", "range_size", "total_vol", "ts",
}


def add_all_phase_b_helpers(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    tick: float = TICK_SIZE,
    enable_phase_c_running: bool = True,
    bounds: dict | None = None,
) -> pd.DataFrame:
    """Pipeline complet Phase B helpers : sessions + IB + VP + sess HL + RVOL inputs + ATR.

    IDEMPOTENT : drop les helpers existants avant recalcul (utile si re-run sur
    un dataset deja partiellement enrichi).

    Phase C (NOUVEAU 2026-04-27) : si enable_phase_c_running=True (default) ET
    trades_df fourni, ecrase cur_vpoc/vah/val EOD broadcast par leur version
    RUNNING (cumulatif depuis debut session), eliminant le lookahead intraday
    documente dans ML_EXCLUDE_FEATURES.

    Chantier 4 (10/05/2026) : bounds per-symbole via get_session_boundaries(sym).
    Defaults ES/NQ (09:30 NYSE RTH). Pour MGC, passer bounds=get_session_boundaries("MGC")
    pour obtenir IB 08:30-09:30, cash 08:30-13:30 (COMEX RTH gold).
    """
    df = df.copy()
    drop_existing = [c for c in PHASE_B_HELPER_COLS if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)
    df = add_session_metadata(df, bounds=bounds)
    df = add_ib_features(df, tick=tick, bounds=bounds)
    df = add_session_high_low(df, tick=tick, bounds=bounds)
    df = add_open_cash_price1030(df, bounds=bounds)
    df = add_volume_profile_features(df, trades_df=trades_df, tick=tick, bounds=bounds)
    # Phase C : VPOC/VA running cumsum (ecrase cur_vpoc/vah/val EOD)
    if enable_phase_c_running and trades_df is not None and not trades_df.empty:
        from value_area_running import apply_value_area_running
        df = apply_value_area_running(df, trades_df=trades_df, tick=tick)
    df = add_rvol_inputs(df, tick=tick)
    df = add_ib_atr(df, lookback_days=14)
    return df
