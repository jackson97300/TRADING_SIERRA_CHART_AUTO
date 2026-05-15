"""game_changers_streaming.py

API streaming-aware du module `build_dataset_v4_phase_b.py:apply_game_changers()`.
Reproduit 5 features Market Profile par jour : open_type, open_zone, day_type,
open_direction, open_bias_conf.

Architecture :
    Batch : groupby(date_et) -> trigger classification a la 1ere bar POST-IB
            (mins_et >= us_start + 60) -> broadcast sur toutes bars du jour.
    Stream : detect transition date_et + mins_et passage POST-IB -> classify
             une fois et garde en state -> output sur chaque bar du jour.

DIVERGENCE BATCH/STREAM DOCUMENTEE :
    day_type batch utilise sess_high/sess_low/close FINAUX du jour (.iloc[-1])
    = LOOKAHEAD FUTUR. En stream impossible.
    Decision : stream produit "running day_type" qui evolue intraday avec les
    sess_high/sess_low/close courants. A la DERNIERE bar = batch.
    Parite VRAIE uniquement sur last-bar-of-session (mirror volume_profile).

Convention pipeline :
    add_session_metadata_streaming -> add_ib_features_streaming ->
    add_session_high_low_streaming -> add_volume_profile_features_streaming ->
    add_ib_atr_streaming -> add_game_changers_streaming
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

import game_changers as gc

# FIX P0 audit code-reviewer : utiliser get_session_boundaries SOURCE UNIQUE
# de verite pour ib_close_min (mirror batch ligne 253-254).
# Anti-pattern hardcode : MGC=510 au lieu de 570 -> classifier 60min trop tot
# -> open_type UNKNOWN systematique sur MGC.
try:
    from CORE.constants import get_session_boundaries as _get_session_boundaries
except ImportError:
    from constants import get_session_boundaries as _get_session_boundaries


@dataclass
class GameChangersState:
    """State sub-engine game_changers.

    Pickle-safe : primitifs + Optional[Any] (date).
    """
    # Date tracking pour reset par jour
    current_date_et: Optional[Any] = None
    # Bounds session (us_start, ib_close_min)
    ib_close_min: int = 630   # ES/NQ default 09:30 + 60 = 10:30 ET (mins_et=630)
    # Frozen-at-IB stats (open_type, open_zone, open_direction, open_bias_conf)
    # Une fois calcules POST-IB, ne changent plus pour le reste du jour.
    classified_today: bool = False
    cached_open_type: int = 0           # UNKNOWN
    cached_open_zone: int = 0           # AT_POC default mais batch fallback=0 (UNKNOWN)
    cached_open_direction: int = 0
    cached_open_bias_conf: float = 0.0
    # day_type : RUNNING (recalcule chaque bar avec sess_high/low/close courants)
    # Divergence batch (qui voit fin de session) - flagge INCIDENT_LOG.
    cached_day_type: int = 2            # NORM_VAR default


def add_game_changers_streaming(
    row: dict,
    state: GameChangersState,
    symbol: str = "ES",
) -> dict:
    """Sub-engine streaming game_changers — 5 features Market Profile.

    Features :
      open_type        - OD/OTD/ORR/OAOR/OAIR + ODF (12 valeurs)
      open_zone        - 7 zones par rapport au PDH/PDL/VA precedente
      day_type         - NonTrend/Normal/NormVar/Neutral/Trend (RUNNING)
      open_direction   - +1/-1/0 (derive de open_type)
      open_bias_conf   - confidence [0, 1] (derive de open_type)

    Args:
        row : dict avec inputs phase_b helpers + open_cash + price_1030 +
              ib_high/low/atr + sess_high/low + close + prev_vah/val/vpoc + pdh/pdl
              + date_et + mins_et.
        state : GameChangersState mutable.
        symbol : pour set ib_close_min (ES/NQ=630 = 10:30 ET, MGC=570 = 09:30 ET).

    Returns:
        dict row + 5 features.
    """
    out = dict(row)

    # ─── Set ib_close_min per-symbole (FIX P0 audit code-reviewer) ─────────
    # Mirror EXACT batch ligne 253-254 : get_session_boundaries(symbol)["us_start"] + 60
    # MGC: us_start=510 (08:30 ET), ib_close=570 (09:30 ET)
    # ES/NQ: us_start=570 (09:30 ET), ib_close=630 (10:30 ET)
    bounds = _get_session_boundaries(symbol)
    ib_close_min = bounds["us_start"] + 60
    state.ib_close_min = ib_close_min

    date_et = out.get("date_et")
    mins_et = out.get("mins_et")

    # ─── Detection rotation date_et : reset state ──────────────────────────
    if date_et is not None and date_et != state.current_date_et:
        state.current_date_et = date_et
        state.classified_today = False
        state.cached_open_type = 0
        state.cached_open_zone = 0
        state.cached_open_direction = 0
        state.cached_open_bias_conf = 0.0
        state.cached_day_type = 2

    # ─── Trigger classification POST-IB (une fois par jour) ────────────────
    # Mirror batch : grp[grp["mins_et"] >= ib_close_min].iloc[0]
    # FIX P1.1 audit : classified_today=True INCONDITIONNEL apres 1ere tentative
    # POST-IB. Mirror batch qui prend `post_ib.iloc[0]` peu importe le resultat
    # (UNKNOWN si inputs incomplets -> broadcast UNKNOWN tout le jour).
    # Sans ce fix, stream retry bar suivante avec inputs potentiellement valides
    # -> divergence vs batch fige sur 1ere bar POST-IB.
    if (
        not state.classified_today
        and mins_et is not None
        and not pd.isna(mins_et)
        and mins_et >= ib_close_min
    ):
        # On a la 1ere bar POST-IB : classify (UNKNOWN fallback si inputs invalides)
        open_cash = out.get("open_cash")
        prev_vah = out.get("prev_vah")
        prev_val = out.get("prev_val")
        prev_vpoc = out.get("prev_vpoc")
        pdh = out.get("pdh")
        pdl = out.get("pdl")
        ib_high = out.get("ib_high")
        ib_low = out.get("ib_low")
        price_1030 = out.get("price_1030")

        # classify_open_type + classify_open_zone (stateless, deterministe).
        # Fix code-reviewer P1 R2 R3 : try/except etait CODE MORT car
        # classify_open_type retourne UNKNOWN (0) sur inputs None (cf
        # game_changers.py:179-181 `if not all(_valid(v)): return UNKNOWN`),
        # ne leve PAS TypeError/ValueError. Le try/except servait juste a
        # masquer le silent fallback Pattern V1.
        # Solution : detect explicit input invalide AVANT classify + emit log
        # MAJEUR si POST-IB avec inputs manquants (= pattern V1 reproduit).
        # Anti silent fallback (regle souveraine logs 01/05).
        critical_inputs_valid = all(
            v is not None and not (isinstance(v, float) and v != v)  # not None and not NaN
            for v in (open_cash, prev_vah, prev_val, ib_high, ib_low, price_1030)
        )
        if critical_inputs_valid:
            ot = gc.classify_open_type(
                open_cash, prev_vah, prev_val, ib_high, ib_low, price_1030
            )
            oz = gc.classify_open_zone(
                open_cash, prev_vah, prev_val, prev_vpoc, pdh, pdl
            )
            state.cached_open_type = int(ot)
            state.cached_open_zone = int(oz)
            state.cached_open_direction = int(gc.direction(ot))
            state.cached_open_bias_conf = float(gc.confidence(ot))
        else:
            # Inputs manquants -> garder cached UNKNOWN.
            # Fix code-reviewer Pass 4 Review #3 R3 (15/05) : emit log MAJEUR
            # pour audit J+1 (regle souveraine logs 01/05). Distinguer warmup
            # cold start (acceptable) de bug pipeline (silent fallback Pattern V1).
            # Caller doit grep `GAME_CHANGERS_OPEN_TYPE_UNKNOWN` en errors_*.jsonl
            # pour identifier frequence (rare = warmup OK, frequent = bug).
            try:
                import logging
                _gc_logger = logging.getLogger("game_changers_streaming")
                missing_inputs = [
                    n for n, v in zip(
                        ("open_cash", "prev_vah", "prev_val", "ib_high", "ib_low", "price_1030"),
                        (open_cash, prev_vah, prev_val, ib_high, ib_low, price_1030),
                    ) if v is None or (isinstance(v, float) and v != v)
                ]
                _gc_logger.warning(
                    f"[GAME_CHANGERS_OPEN_TYPE_UNKNOWN] symbol={symbol} "
                    f"date_et={date_et} mins_et={mins_et} missing_inputs={missing_inputs} "
                    "-> classify=UNKNOWN cached (warmup cold start OU bug pipeline upstream)"
                )
            except Exception:
                pass
        # FIX P1.1 : classified_today=True inconditionnel (mirror batch fige sur post_ib.iloc[0])
        state.classified_today = True

    # ─── day_type RUNNING (recalcule chaque bar apres POST-IB) ─────────────
    # Mirror batch mais avec sess_high/low/close COURANTS au lieu de finaux.
    # DIVERGENCE intentionnelle (INCIDENT_LOG documente).
    if state.classified_today:
        ib_high = out.get("ib_high")
        ib_low = out.get("ib_low")
        ib_atr_val = out.get("ib_atr")
        sess_high = out.get("sess_high")
        sess_low = out.get("sess_low")
        close = out.get("close")
        if (
            ib_high is not None and ib_low is not None
            and not pd.isna(ib_high) and not pd.isna(ib_low)
            and ib_high > ib_low
        ):
            ib_range = ib_high - ib_low
            if ib_atr_val is not None and not pd.isna(ib_atr_val) and ib_atr_val > 0:
                ib_atr_ratio = ib_range / ib_atr_val
            else:
                ib_atr_ratio = 0.0
            try:
                dt = gc.classify_day_type(
                    ib_atr_ratio, sess_high, sess_low, close, ib_high, ib_low
                )
                state.cached_day_type = int(dt)
            except (TypeError, ValueError):
                pass

    out["open_type"] = state.cached_open_type
    out["open_zone"] = state.cached_open_zone
    out["day_type"] = state.cached_day_type
    out["open_direction"] = state.cached_open_direction
    out["open_bias_conf"] = state.cached_open_bias_conf

    return out
