"""market_profile_advanced.py - Phase A.3 MEDIUM features Market Profile + ICT.

Sortie audit ULTRATHINK 12/06 PM cross-check 2 agents.

Phase A.3 MEDIUM features (4) :
  1. Single Prints - exploit single_print_count/mid Sierra DMP natif + nouveau
                     dist/position relative au close
  2. Composite POC 5d/20d - state persistant + history rolling daily VPOC
  3. Liquidity Sweep detector - multi-bar pattern sweep high/low + reversal
  4. Judas Swing detector - London session : direction initiale vs vraie direction

State machines stateful (par symbole) :
  - SinglePrintState : juste calcul instantane (pas state)
  - CompositePOCState : rolling 5/20 daily VPOC values + reset cross-day
  - LiquiditySweepState : prev_session_high/low + sweep tracking buffer
  - JudasSwingState : London open tracking + first hour direction

Auteur : MIA Trading V5 Phase A.3
Date   : 2026-06-12
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# 1. SINGLE PRINTS — exploit Sierra DMP natif + position relative
# ════════════════════════════════════════════════════════════════════════════

def detect_single_prints(payload: dict) -> dict:
    """Detecte single prints via Sierra DMP natif (single_print_count, single_print_mid).

    Concept Dalton : Single Print = zone du profile avec un seul TPO (letter).
    Indique zones de prix non acceptees, zones magnet/reversal.

    Sierra DMP emit DEJA :
      - single_print_count : nombre de single prints session
      - single_print_mid   : prix moyen des single prints

    On enrichit avec position relative au close + distance.

    Returns dict :
      has_single_prints     : bool, count > 0
      dist_single_print_atr : float ou None, distance close -> single_print_mid (signed)
      single_print_above    : bool, single_print_mid > close
      single_print_below    : bool, single_print_mid < close
      single_print_density  : float, count / range_size_ticks (normalise par range)
    """
    sp_count = payload.get("single_print_count", 0)
    sp_mid = payload.get("single_print_mid")
    close = payload.get("close")
    atr = payload.get("atr")
    range_size = payload.get("range_size_ticks")

    has_sp = (sp_count is not None and sp_count > 0)

    defaults = {
        "has_single_prints": has_sp,
        "dist_single_print_atr": None,
        "single_print_above": False,
        "single_print_below": False,
        "single_print_density": 0.0,
    }

    if not has_sp or sp_mid is None or close is None:
        return defaults

    try:
        spm = float(sp_mid)
        c = float(close)
    except (TypeError, ValueError):
        return defaults

    # Position relative
    above = spm > c
    below = spm < c

    # Distance en ATR
    dist_atr = None
    if atr is not None:
        try:
            a = float(atr)
            if a > 0:
                dist_atr = round((spm - c) / a, 4)
        except (TypeError, ValueError):
            pass

    # Densite
    density = 0.0
    if range_size is not None:
        try:
            r = float(range_size)
            if r > 0:
                density = round(float(sp_count) / r, 4)
        except (TypeError, ValueError):
            pass

    return {
        "has_single_prints": has_sp,
        "dist_single_print_atr": dist_atr,
        "single_print_above": above,
        "single_print_below": below,
        "single_print_density": density,
    }


# ════════════════════════════════════════════════════════════════════════════
# 2. COMPOSITE POC 5d / 20d (state persistant rolling daily VPOC)
# ════════════════════════════════════════════════════════════════════════════
# Approche pragmatique sans full volume profile granulaire :
# Composite POC = MEDIAN des cur_vpoc daily finaux sur 5/20 jours
# (= centre de gravite du marche sur la fenetre rolling).

class CompositePOCState:
    """State rolling 5/20 daily VPOC values."""

    def __init__(self):
        self.daily_vpocs_5d: deque = deque(maxlen=5)
        self.daily_vpocs_20d: deque = deque(maxlen=20)
        self.current_day: Optional[str] = None
        self.last_vpoc_today: Optional[float] = None


def _ts_to_trading_day(ts_ms: int) -> Optional[str]:
    """Convertit ts ms -> trading day CME format YYYY-MM-DD.

    Convention CME : 18:00 ET J-1 -> 18:00 ET J = trading day J.
    """
    try:
        dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        # Convention CME : si hour UTC >= 22 (= 18:00 ET en hiver / 17:00 ET en ete avec DST)
        # le trading day est le jour suivant. Approximation simple : si hour >= 22, shift +1 jour.
        if dt_utc.hour >= 22:
            from datetime import timedelta
            dt_utc = dt_utc + timedelta(days=1)
        return dt_utc.date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def compute_composite_poc(payload: dict, state: CompositePOCState) -> dict:
    """Calcule composite POC 5d et 20d en suivant les daily VPOC finaux.

    Logique :
      - Track le dernier cur_vpoc vu chaque trading day
      - Quand un nouveau day commence, fige le VPOC du day precedent
        dans rolling 5d et 20d windows
      - Composite POC = MEDIAN des daily VPOCs

    Args:
        payload : bar courante avec ts + cur_vpoc
        state   : CompositePOCState mutable persistent

    Returns dict :
      composite_poc_5d  : float ou None
      composite_poc_20d : float ou None
      dist_composite_poc_5d_atr  : float ou None
      dist_composite_poc_20d_atr : float ou None
    """
    ts = payload.get("ts")
    cur_vpoc = payload.get("cur_vpoc")
    close = payload.get("close")
    atr = payload.get("atr")

    defaults = {
        "composite_poc_5d": None,
        "composite_poc_20d": None,
        "dist_composite_poc_5d_atr": None,
        "dist_composite_poc_20d_atr": None,
    }
    if ts is None or cur_vpoc is None:
        return defaults

    try:
        ts_int = int(ts)
        vpoc = float(cur_vpoc)
    except (TypeError, ValueError):
        return defaults

    trading_day = _ts_to_trading_day(ts_int)
    if trading_day is None:
        return defaults

    # Detection nouveau jour : fige VPOC final du jour precedent
    if state.current_day is None:
        state.current_day = trading_day
    elif trading_day != state.current_day:
        # Nouveau jour : fige le VPOC du jour precedent dans rolling windows
        if state.last_vpoc_today is not None:
            state.daily_vpocs_5d.append(state.last_vpoc_today)
            state.daily_vpocs_20d.append(state.last_vpoc_today)
        state.current_day = trading_day

    # Update last_vpoc_today (sera fige a la transition next-day)
    state.last_vpoc_today = vpoc

    # Compute composite POCs (median des daily VPOCs accumules)
    def _median(values: list) -> Optional[float]:
        if not values:
            return None
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
        return sorted_vals[mid]

    comp_5d = _median(list(state.daily_vpocs_5d))
    comp_20d = _median(list(state.daily_vpocs_20d))

    # Distances en ATR
    dist_5d = None
    dist_20d = None
    if close is not None and atr is not None:
        try:
            c = float(close)
            a = float(atr)
            if a > 0:
                if comp_5d is not None:
                    dist_5d = round((comp_5d - c) / a, 4)
                if comp_20d is not None:
                    dist_20d = round((comp_20d - c) / a, 4)
        except (TypeError, ValueError):
            pass

    return {
        "composite_poc_5d": round(comp_5d, 2) if comp_5d is not None else None,
        "composite_poc_20d": round(comp_20d, 2) if comp_20d is not None else None,
        "dist_composite_poc_5d_atr": dist_5d,
        "dist_composite_poc_20d_atr": dist_20d,
    }


# ════════════════════════════════════════════════════════════════════════════
# 3. LIQUIDITY SWEEP DETECTOR (multi-bar pattern ICT/Smart Money)
# ════════════════════════════════════════════════════════════════════════════

class LiquiditySweepState:
    """State pour detection sweep highs/lows multi-bars."""

    def __init__(self, sweep_window_bars: int = 5):
        self.sweep_window_bars = sweep_window_bars
        # Rolling buffer des N dernieres bars (high, low, close)
        self.bars_buffer: deque = deque(maxlen=sweep_window_bars * 2)
        # Sweeps actifs (non encore filled)
        self.active_sweeps_high: list = []  # list of (sweep_price, bars_since)
        self.active_sweeps_low: list = []


def detect_liquidity_sweep(payload: dict, state: LiquiditySweepState) -> dict:
    """Detecte liquidity sweeps recents (price perce niveau puis reverse).

    Pattern ICT/Smart Money :
      Sweep HIGH = high de la bar > MAX high des N bars precedentes,
                   PUIS close revient en-dessous de ce MAX = sweep & reverse.
      Sweep LOW  = low < MIN low des N bars precedentes,
                   PUIS close revient au-dessus de ce MIN.

    Returns dict :
      sweep_high_active     : int, count sweeps high actifs
      sweep_low_active      : int, count sweeps low actifs
      sweep_high_this_bar   : bool, nouveau sweep high cette bar
      sweep_low_this_bar    : bool, nouveau sweep low cette bar
      bars_since_last_sweep_high : int ou None
      bars_since_last_sweep_low  : int ou None
    """
    bar_high = payload.get("bar_high") or payload.get("high")
    bar_low = payload.get("bar_low") or payload.get("low")
    close = payload.get("close")

    defaults = {
        "sweep_high_active": 0,
        "sweep_low_active": 0,
        "sweep_high_this_bar": False,
        "sweep_low_this_bar": False,
        "bars_since_last_sweep_high": None,
        "bars_since_last_sweep_low": None,
    }
    if any(v is None for v in (bar_high, bar_low, close)):
        return defaults

    try:
        bh = float(bar_high)
        bl = float(bar_low)
        c = float(close)
    except (TypeError, ValueError):
        return defaults

    # Detection sweep : compare avec les N bars precedentes (avant la courante)
    sweep_high_now = False
    sweep_low_now = False
    if len(state.bars_buffer) >= state.sweep_window_bars:
        recent = list(state.bars_buffer)[-state.sweep_window_bars:]
        max_high = max(b[0] for b in recent)
        min_low = min(b[1] for b in recent)
        # Sweep HIGH : new high MAIS close revient sous max_high
        if bh > max_high and c < max_high:
            state.active_sweeps_high.append((max_high, 0))
            sweep_high_now = True
        # Sweep LOW
        if bl < min_low and c > min_low:
            state.active_sweeps_low.append((min_low, 0))
            sweep_low_now = True

    # Update buffer apres detection (la bar courante peut creer un sweep
    # baseees sur l'historique, mais elle-meme entre dans le buffer pour next)
    state.bars_buffer.append((bh, bl, c))

    # Increment bars_since pour sweeps actifs
    state.active_sweeps_high = [
        (price, bs + 1) for (price, bs) in state.active_sweeps_high
    ]
    state.active_sweeps_low = [
        (price, bs + 1) for (price, bs) in state.active_sweeps_low
    ]

    # Cleanup : retire sweeps "filled" (close re-traverse le niveau)
    state.active_sweeps_high = [
        (price, bs) for (price, bs) in state.active_sweeps_high
        if c < price  # sweep haut reste actif tant que close < price perce
    ]
    state.active_sweeps_low = [
        (price, bs) for (price, bs) in state.active_sweeps_low
        if c > price
    ]

    # Cap age sweeps a 20 bars (au-dela = obsolete)
    state.active_sweeps_high = [(p, bs) for (p, bs) in state.active_sweeps_high if bs <= 20]
    state.active_sweeps_low = [(p, bs) for (p, bs) in state.active_sweeps_low if bs <= 20]

    bars_since_high = (
        min(bs for (_, bs) in state.active_sweeps_high)
        if state.active_sweeps_high else None
    )
    bars_since_low = (
        min(bs for (_, bs) in state.active_sweeps_low)
        if state.active_sweeps_low else None
    )

    return {
        "sweep_high_active": len(state.active_sweeps_high),
        "sweep_low_active": len(state.active_sweeps_low),
        "sweep_high_this_bar": sweep_high_now,
        "sweep_low_this_bar": sweep_low_now,
        "bars_since_last_sweep_high": bars_since_high,
        "bars_since_last_sweep_low": bars_since_low,
    }


# ════════════════════════════════════════════════════════════════════════════
# 4. JUDAS SWING DETECTOR (ICT London session pattern)
# ════════════════════════════════════════════════════════════════════════════
# Concept ICT :
#   London Judas = London open part dans une direction (ex: bas) pour SWEEP
#   liquidite, PUIS reverse pour aller dans la VRAIE direction (haut).
#
# Detection :
#   1. Track London session entree
#   2. Capture London open + direction premiere heure
#   3. Quand current direction != direction premiere heure -> Judas swing
#
# Session = 1 (London) dans le data Sierra.

class JudasSwingState:
    """State pour detection Judas Swing London."""

    def __init__(self):
        self.in_london = False
        self.london_open: Optional[float] = None
        self.london_open_ts: Optional[int] = None
        self.london_first_hour_max: Optional[float] = None
        self.london_first_hour_min: Optional[float] = None
        self.first_hour_direction: Optional[int] = None  # +1 / -1 / 0
        self.first_hour_complete: bool = False


def detect_judas_swing(payload: dict, state: JudasSwingState) -> dict:
    """Detecte pattern Judas Swing London session.

    Logique :
      1. Quand session = 1 (London) commence : reset state, capture london_open
      2. Pendant 1ere heure London (60 bars 1-min) : track max/min + direction
      3. Apres 1ere heure : direction figee
      4. Si current close diverge de cette direction = Judas Swing detected

    Returns dict :
      judas_swing_active        : bool, current direction opposite to first hour
      judas_swing_direction     : int +1/-1/0 = vraie direction probable
      london_open               : float ou None
      london_first_hour_direction : int ou None
      bars_since_london_open    : int ou None
    """
    session = payload.get("session")
    session_segment = payload.get("session_segment")
    close = payload.get("close")
    bar_high = payload.get("bar_high") or payload.get("high")
    bar_low = payload.get("bar_low") or payload.get("low")
    ts = payload.get("ts")

    defaults = {
        "judas_swing_active": False,
        "judas_swing_direction": 0,
        "london_open": state.london_open,
        "london_first_hour_direction": state.first_hour_direction,
        "bars_since_london_open": None,
    }
    if any(v is None for v in (close, bar_high, bar_low, ts)):
        return defaults

    # Detection London session (session=1 OU session_segment=='london')
    is_london = (session == 1) or (session_segment == "london")

    # Detection entree London
    if is_london and not state.in_london:
        state.in_london = True
        state.london_open = float(close)
        state.london_open_ts = int(ts)
        state.london_first_hour_max = float(bar_high)
        state.london_first_hour_min = float(bar_low)
        state.first_hour_direction = None
        state.first_hour_complete = False

    # Sortie London : reset
    if not is_london and state.in_london:
        state.in_london = False
        state.london_open = None
        state.first_hour_direction = None
        state.first_hour_complete = False

    if not state.in_london or state.london_open is None or state.london_open_ts is None:
        return defaults

    # Pendant 1ere heure (60 bars 1-min = 3600 sec)
    try:
        elapsed_sec = (int(ts) - state.london_open_ts) / 1000
    except (TypeError, ValueError):
        return defaults

    bars_since = int(elapsed_sec / 60) if elapsed_sec > 0 else 0

    if not state.first_hour_complete:
        # Update max/min
        try:
            bh = float(bar_high)
            bl = float(bar_low)
            if state.london_first_hour_max is not None and bh > state.london_first_hour_max:
                state.london_first_hour_max = bh
            if state.london_first_hour_min is not None and bl < state.london_first_hour_min:
                state.london_first_hour_min = bl
        except (TypeError, ValueError):
            pass

        # Fige direction apres 60 bars
        if elapsed_sec >= 3600:
            try:
                first_close = state.london_open
                last_close = float(close)
                if last_close > first_close * 1.0005:  # 0.05% UP threshold
                    state.first_hour_direction = +1
                elif last_close < first_close * 0.9995:  # 0.05% DOWN threshold
                    state.first_hour_direction = -1
                else:
                    state.first_hour_direction = 0
                state.first_hour_complete = True
            except (TypeError, ValueError):
                pass

    # Detection Judas Swing (apres 1ere heure complete)
    judas_active = False
    judas_dir = 0
    if state.first_hour_complete and state.first_hour_direction is not None and state.london_open is not None:
        try:
            c = float(close)
            current_dir = 0
            if c > state.london_open * 1.001:  # 0.1% UP
                current_dir = +1
            elif c < state.london_open * 0.999:
                current_dir = -1
            # Judas si direction current OPPOSEE a first hour
            if current_dir != 0 and state.first_hour_direction != 0 and current_dir != state.first_hour_direction:
                judas_active = True
                judas_dir = current_dir  # La vraie direction
        except (TypeError, ValueError):
            pass

    return {
        "judas_swing_active": judas_active,
        "judas_swing_direction": judas_dir,
        "london_open": state.london_open,
        "london_first_hour_direction": state.first_hour_direction,
        "bars_since_london_open": bars_since,
    }


# ════════════════════════════════════════════════════════════════════════════
# API publique : compute_market_profile_advanced_features
# ════════════════════════════════════════════════════════════════════════════

class MarketProfileAdvancedState:
    """Container pour les 3 states stateful (single prints = stateless)."""

    def __init__(self, sweep_window_bars: int = 5):
        self.composite_poc = CompositePOCState()
        self.sweep = LiquiditySweepState(sweep_window_bars=sweep_window_bars)
        self.judas = JudasSwingState()


def compute_market_profile_advanced_features(
    payload: dict,
    state: MarketProfileAdvancedState,
) -> dict:
    """Calcule les 4 MEDIUM features Phase A.3 sur un bar.

    Args:
        payload : bar courante (dict)
        state   : MarketProfileAdvancedState persistent across bars

    Returns dict avec 15+ features ajoutees.
    """
    out = {}
    out.update(detect_single_prints(payload))
    out.update(compute_composite_poc(payload, state.composite_poc))
    out.update(detect_liquidity_sweep(payload, state.sweep))
    out.update(detect_judas_swing(payload, state.judas))
    return out
