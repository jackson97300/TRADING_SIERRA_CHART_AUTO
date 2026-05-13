"""mia_amd_streaming.py

API streaming-aware du module CORE/mia_amd.py (AmdEngine — ICT Power of 3).
Reproduit les 18 features amd_* (Accumulation/Manipulation/Distribution)
calculees a partir des sessions Asia/London/US.

Architecture :
    Le module batch utilise plusieurs passes sur le DataFrame entier
    (_asia_range, _detect_sweeps, _detect_judas, _propagate_dir,
    _score_manip, _score_dist, _score_po3). Le streaming reproduit ces
    passes en mode incremental dans un seul state AmdEngineState.

Convention pipeline :
    add_amd_streaming(row, state) — chaine apres rvol_engine + rolling_features
    (depend de rvol, delta_pct, finish_strength, momentum_5b, ib_broken_*, etc.)

Module batch CORE/mia_amd.py INTOUCHE (additive-only).

Auteur : Phase 3b semaine 3 (2026-05-13)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from mia_amd import (
    ACCUM_MAX_ATR_RATIO,
    ACCUM_MIN_TICKS,
    SWEEP_MIN_TICKS,
    MANIP_RVOL_SPIKE,
    MANIP_DELTA_THR,
    JUDAS_REENTRY_TICKS,
    DIST_RVOL_MIN,
    DIST_DELTA_MIN,
    DIST_MOMENTUM_MIN,
    PO3_W_ACCUM,
    PO3_W_MANIP,
    PO3_W_DIST,
)

# FIX P1 audit code-reviewer : tick-size policy (.claude/rules/tick-size-policy.md)
# Anti-pattern : tick=0.25 hardcoded -> MGC sous-estime 2.5x.
# Helper get_tick_size(symbol) = source unique verite.
try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


def _safe_float_or(x, default=0.0):
    """Cast safe : retourne float ou default si NaN/exception."""
    if x is None:
        return default
    try:
        f = float(x)
        if np.isnan(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _get_session(row: dict) -> str:
    """Mirror AmdEngine._get_sessions : session_id (str) prioritaire sinon session (int 0/1/2)."""
    sid = row.get("session_id")
    if sid is not None:
        return str(sid)
    s = _safe_float_or(row.get("session"), 2.0)
    if s == 0:
        return "Asia"
    elif s == 1:
        return "London"
    else:
        return "US"


def make_amd_state(symbol: str = "NQ") -> "AmdEngineState":
    """Factory AmdEngineState avec config per-symbole (FIX P1 audit tick-policy).

    Mirror AmdEngine.__init__() : derive tick/sweep_min/accum_min/judas_re
    depuis `symbol`. Pour MGC, tick=0.10 (vs 0.25 ES/NQ) -> les conversions
    ticks SONT correctes.
    """
    symbol_up = symbol.upper()
    return AmdEngineState(
        symbol=symbol_up,
        tick=_get_tick_size(symbol_up),
        sweep_min=SWEEP_MIN_TICKS.get(symbol_up, 15),
        accum_min=ACCUM_MIN_TICKS.get(symbol_up, 50),
        judas_re=JUDAS_REENTRY_TICKS.get(symbol_up, 10),
    )


@dataclass
class AmdEngineState:
    """State streaming AmdEngine (ICT Power of 3).

    Pickle-safe : tous primitifs (str, float, int, bool, Optional[float]).

    IMPORTANT : utiliser make_amd_state(symbol) pour instancier (per-symbole
    correct tick + thresholds). Default ES/NQ pour compat retro.
    """
    symbol: str = "NQ"
    tick: float = 0.25   # ES/NQ default - utiliser make_amd_state(symbol) pour MGC
    sweep_min: int = 15  # NQ default - SWEEP_MIN_TICKS["ES"]=4 / MGC variable
    accum_min: int = 50  # NQ default - ACCUM_MIN_TICKS["ES"]=12
    judas_re: int = 10   # NQ default - JUDAS_REENTRY_TICKS["ES"]=3

    # ─── Asia range tracking ──────────────────────────────────────────────
    current_asia_high: Optional[float] = None  # running pendant Asia
    current_asia_low: Optional[float] = None
    frozen_asia_high: Optional[float] = None   # frozen apres transition Asia -> London/US
    frozen_asia_low: Optional[float] = None
    frozen_a_valid: bool = False               # range Asia valide (>= accum_min + <= 0.6 ATR)

    # ─── Sweep tracking (one-shot par session London ou US) ───────────────
    done_u: bool = False    # sweep up done
    done_d: bool = False    # sweep down done
    mx_u: float = 0.0       # max depth up (running max apres sweep done)
    mx_d: float = 0.0       # max depth down (idem)

    # ─── Judas tracking (one-shot par session) ────────────────────────────
    had_u: bool = False     # sweep up vu
    had_d: bool = False     # sweep down vu
    j_done_u: bool = False  # Bear Judas (sweep up + reversal down) done
    j_done_d: bool = False  # Bull Judas (sweep dn + reversal up) done

    # ─── Propagated direction (forward fill par session) ──────────────────
    prop_dir: int = 0       # mirror _propagate_dir : ffill m_dir, reset Asia=0

    # ─── PO3 state (one-shot session) ─────────────────────────────────────
    had_j_session: bool = False  # Judas detecte cette session ?
    last_ms: float = 0.0          # manip_score du bar Judas
    last_md: int = 0              # manip_dir du bar Judas

    # ─── Session transition tracking ──────────────────────────────────────
    prev_session: str = ""


def add_amd_streaming(
    row: dict,
    state: AmdEngineState,
) -> dict:
    """API streaming AmdEngine — 18 features ICT Power of 3.

    Features (18) :
      amd_phase, amd_asia_high, amd_asia_low, amd_asia_range_ticks,
      amd_sweep_up, amd_sweep_dn, amd_sweep_depth_ticks,
      amd_judas_swing, amd_manip_dir, amd_manip_score,
      amd_dist_score, amd_dist_dir, amd_dist_confirmed,
      amd_po3_bullish, amd_po3_bearish, amd_po3_score, amd_reversal_prob,
      amd_session_bias

    Args:
        row : dict avec price, session (ou session_id), atr, et inputs ML
              (rvol, delta_pct, finish_strength, momentum_5b, ib_broken_*,
              retest_high/low_delta_div, rvol_absorb_*, profile_shape, cvd_day_dir).
        state : AmdEngineState mutable.

    Returns:
        dict row + 18 features amd_*.
    """
    out = dict(row)

    # ─── Inputs ────────────────────────────────────────────────────────────
    session = _get_session(out)
    price = _safe_float_or(out.get("price"), np.nan)
    atr = _safe_float_or(out.get("atr"), 100.0)
    if atr <= 0:
        atr = 100.0

    # ML inputs (utilises pour scoring)
    rvol = _safe_float_or(out.get("rvol"), 1.0)
    dpct = _safe_float_or(out.get("delta_pct"), 0.0)
    fin = _safe_float_or(out.get("finish_strength"), 0.0)
    rt_h = _safe_float_or(out.get("retest_high_delta_div"), 0.0)
    rt_l = _safe_float_or(out.get("retest_low_delta_div"), 0.0)
    ab_b = _safe_float_or(out.get("rvol_absorb_buy"), 0.0)
    ab_s = _safe_float_or(out.get("rvol_absorb_sell"), 0.0)
    prof = _safe_float_or(out.get("profile_shape"), 0.0)
    mom5 = _safe_float_or(out.get("momentum_5b"), 0.0)
    ib_u = _safe_float_or(out.get("ib_broken_up"), 0.0)
    ib_d = _safe_float_or(out.get("ib_broken_down"), 0.0)
    cvd = _safe_float_or(out.get("cvd_day_dir"), 0.0)

    session_changed = (session != state.prev_session)

    # ─── 1. ASIA RANGE (running + frozen apres transition) ─────────────────
    if session == "Asia":
        if state.prev_session != "Asia":
            # Premier bar Asia : reset cur_h/l
            state.current_asia_high = price if not np.isnan(price) else None
            state.current_asia_low = price if not np.isnan(price) else None
            # FIX P1.2 audit code-reviewer : reset frozen_a_valid au demarrage
            # d'une nouvelle session Asia, sinon valeur stale persiste indefiniment.
            # Le frozen_a_valid sera re-set au prochain Asia -> London/US.
            state.frozen_a_valid = False
        else:
            if not np.isnan(price):
                if state.current_asia_high is None or price > state.current_asia_high:
                    state.current_asia_high = price
                if state.current_asia_low is None or price < state.current_asia_low:
                    state.current_asia_low = price
        a_h = state.current_asia_high
        a_l = state.current_asia_low
    elif session in ("London", "US"):
        # Transition Asia -> London : freeze + valid check
        if state.prev_session == "Asia" and state.current_asia_high is not None:
            state.frozen_asia_high = state.current_asia_high
            state.frozen_asia_low = state.current_asia_low
            rng_ticks = (
                (state.frozen_asia_high - state.frozen_asia_low) / state.tick
            )
            rng_pts = state.frozen_asia_high - state.frozen_asia_low
            state.frozen_a_valid = (
                rng_ticks >= state.accum_min
                and rng_pts / atr <= ACCUM_MAX_ATR_RATIO
            )
        a_h = state.frozen_asia_high
        a_l = state.frozen_asia_low
    else:
        a_h = None
        a_l = None

    out["amd_asia_high"] = a_h if a_h is not None else np.nan
    out["amd_asia_low"] = a_l if a_l is not None else np.nan
    if a_h is not None and a_l is not None:
        out["amd_asia_range_ticks"] = (a_h - a_l) / state.tick
    else:
        out["amd_asia_range_ticks"] = np.nan

    # ─── 2. PHASE ──────────────────────────────────────────────────────────
    if session == "Asia":
        out["amd_phase"] = 0.0
    elif session == "London":
        out["amd_phase"] = 1.0
    elif session == "US":
        out["amd_phase"] = 2.0
    else:
        out["amd_phase"] = -1.0

    # ─── 3. SWEEPS reset au changement de session London/US ────────────────
    if session_changed and session in ("London", "US"):
        state.done_u = False
        state.done_d = False
        state.mx_u = 0.0
        state.mx_d = 0.0
        state.had_u = False
        state.had_d = False
        state.j_done_u = False
        state.j_done_d = False
        state.had_j_session = False
        state.last_ms = 0.0
        state.last_md = 0

    # FIX P1 audit Plan agent : reset PO3 accumulators a CHAQUE bar Asia
    # (mirror batch _score_po3 ligne 298-299 qui fait `if sess[i]=='Asia':
    # had_j=False; last_ms=0.0; last_md=0` dans la boucle for, pas seulement
    # a la transition). Protege contre pickle-replay : si state deserialise
    # avec had_j_session=True heritage US precedent, fuite empechee.
    if session == "Asia":
        state.had_j_session = False
        state.last_ms = 0.0
        state.last_md = 0
        state.prop_dir = 0

    sw_u = 0
    sw_d = 0
    if (
        session in ("London", "US")
        and a_h is not None and a_l is not None
        and not np.isnan(price)
    ):
        # Detection initiale sweep
        if price > a_h and not state.done_u:
            d_up = (price - a_h) / state.tick
            if d_up >= state.sweep_min:
                sw_u = 1
                state.mx_u = d_up
                state.done_u = True
        if price < a_l and not state.done_d:
            d_dn = (a_l - price) / state.tick
            if d_dn >= state.sweep_min:
                sw_d = 1
                state.mx_d = d_dn
                state.done_d = True
        # Maj running max depth apres detection
        if state.done_u and price > a_h:
            state.mx_u = max(state.mx_u, (price - a_h) / state.tick)
        if state.done_d and price < a_l:
            state.mx_d = max(state.mx_d, (a_l - price) / state.tick)

    sw_dep = (
        max(state.mx_u, state.mx_d) if session in ("London", "US") else 0.0
    )
    out["amd_sweep_up"] = float(sw_u)
    out["amd_sweep_dn"] = float(sw_d)
    out["amd_sweep_depth_ticks"] = sw_dep

    # ─── 4. JUDAS SWING (sweep + reversal) ─────────────────────────────────
    if sw_u:
        state.had_u = True
    if sw_d:
        state.had_d = True

    judas = 0
    m_dir = 0
    if (
        session in ("London", "US")
        and a_h is not None and a_l is not None
        and not np.isnan(price)
    ):
        # Bear Judas : sweep UP puis price retombe sous asia_high
        if state.had_u and not state.j_done_u:
            re_dn = (a_h - price) / state.tick
            if re_dn >= state.judas_re:
                judas = 1
                m_dir = 1  # bear Judas -> manip_dir = 1 (mirror batch)
                state.j_done_u = True
        # Bull Judas : sweep DN puis price remonte au-dessus asia_low
        if state.had_d and not state.j_done_d:
            re_up = (price - a_l) / state.tick
            if re_up >= state.judas_re:
                judas = 1
                m_dir = -1  # bull Judas -> manip_dir = -1
                state.j_done_d = True

    out["amd_judas_swing"] = float(judas)
    out["amd_manip_dir"] = float(m_dir)

    # ─── 5. PROPAGATE DIR (ffill m_dir, reset Asia=0) ──────────────────────
    if m_dir != 0:
        state.prop_dir = m_dir
    prop_dir = state.prop_dir

    # ─── 6. MANIP SCORE ────────────────────────────────────────────────────
    manip_score = 0.0
    a_valid_flag = 1.0 if state.frozen_a_valid else 0.0
    if prop_dir != 0:
        s = 0.0
        if sw_dep >= state.sweep_min * 2:
            s += 0.20
        elif sw_dep >= state.sweep_min:
            s += 0.10
        if rvol >= MANIP_RVOL_SPIKE:
            s += 0.20
        if prop_dir == 1 and dpct > MANIP_DELTA_THR and fin < 0:
            s += 0.20
        elif prop_dir == -1 and dpct < -MANIP_DELTA_THR and fin > 0:
            s += 0.20
        if prop_dir == 1 and rt_h > 0:
            s += 0.15
        elif prop_dir == -1 and rt_l > 0:
            s += 0.15
        if prop_dir == -1 and ab_b > 0:
            s += 0.10
        elif prop_dir == 1 and ab_s > 0:
            s += 0.10
        if a_valid_flag > 0:
            s += 0.10
        if prof == 3:
            s += 0.05
        manip_score = min(s, 1.0)
    out["amd_manip_score"] = manip_score

    # ─── 7. DIST SCORE ─────────────────────────────────────────────────────
    dist_score = 0.0
    d_dir = 0.0
    conf = 0
    if prop_dir != 0 and session != "Asia":
        exp = -prop_dir  # distribution = opposee manipulation
        d_dir = float(exp)
        s = 0.0
        if rvol >= DIST_RVOL_MIN:
            s += 0.25
        if exp > 0 and dpct > DIST_DELTA_MIN:
            s += 0.25
        elif exp < 0 and dpct < -DIST_DELTA_MIN:
            s += 0.25
        if exp > 0 and mom5 > DIST_MOMENTUM_MIN:
            s += 0.20
        elif exp < 0 and mom5 < -DIST_MOMENTUM_MIN:
            s += 0.20
        if exp > 0 and ib_u > 0:
            s += 0.15
        elif exp < 0 and ib_d > 0:
            s += 0.15
        if exp > 0 and cvd > 0:
            s += 0.15
        elif exp < 0 and cvd < 0:
            s += 0.15
        dist_score = min(s, 1.0)
        if dist_score >= 0.50:
            conf = 1
    out["amd_dist_score"] = dist_score
    out["amd_dist_dir"] = d_dir
    out["amd_dist_confirmed"] = float(conf)

    # ─── 8. PO3 SCORE ──────────────────────────────────────────────────────
    if judas == 1:
        state.had_j_session = True
        if m_dir != 0:
            state.last_md = m_dir
        state.last_ms = manip_score

    po3b = 0
    po3br = 0
    po3s = 0.0
    rev = 0.0
    if state.had_j_session and session != "Asia":
        a_s = 0.33 if a_valid_flag > 0 else 0.0
        m_s = max(state.last_ms, manip_score)
        po3s = min(
            a_s * PO3_W_ACCUM + m_s * PO3_W_MANIP + dist_score * PO3_W_DIST,
            1.0,
        )
        if state.last_md == -1 and conf == 1:
            po3b = 1
        elif state.last_md == 1 and conf == 1:
            po3br = 1
        # Mirror batch ligne 313-314 :
        #   had_j & dc==0 -> rev = min(m_s*1.2, 1.0)
        #   had_j & dc==1 -> rev = min(m_s*0.8 + ds*0.2, 1.0)
        if conf == 0:
            rev = min(m_s * 1.2, 1.0)
        else:  # conf == 1
            rev = min(m_s * 0.8 + dist_score * 0.2, 1.0)
    out["amd_po3_bullish"] = float(po3b)
    out["amd_po3_bearish"] = float(po3br)
    out["amd_po3_score"] = po3s
    out["amd_reversal_prob"] = rev

    # ─── 9. SESSION BIAS ───────────────────────────────────────────────────
    # Mirror batch ligne 122 : np.where(dc==1, dd, np.where(judas==1, -m_dir, 0))
    if conf == 1:
        bias = d_dir
    elif judas == 1:
        bias = float(-m_dir)
    else:
        bias = 0.0
    out["amd_session_bias"] = bias

    # ─── Update prev_session ───────────────────────────────────────────────
    state.prev_session = session

    return out
