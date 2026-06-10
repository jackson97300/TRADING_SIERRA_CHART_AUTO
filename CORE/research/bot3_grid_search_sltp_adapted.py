"""Bot 3 Grid Search SL/TP adapte (logique mia_sltp portee).

OBJECTIF (Jackson 04/05/2026) : trouver les meilleurs seuils SL/TP avec la
logique "SL protege derriere niveau touche + TP devant premier mur + cap RR".

METHODE :
1. PHASE 1 : extraire UNE FOIS tous les signals Bot 3 + snapshot dist_*_pct
2. PHASE 2 : grid search en memoire (135 configs/symbole) en simulant les exits
3. PHASE 3 : ranking par PF + WR + n>=100 + DSR Lopez

ANTI-TRICHE (heritage bot3_backtester.py) :
- Entry T close, slippage par session (RTH 1.5t / Asia 4t)
- News veto (rvol>3 ou range>2*ATR)
- SL+TP meme bar = SL pessimiste
- 1 position max (skip si trade actif)
- Tie-break Tier 1>2>3>NEUTRAL

LOGIQUE SLTP NOUVELLE (porte de mia_sltp.py) :
- SL = max(level_dist + buffer, sl_min_respiration), capot sl_max_budget
- TP : scan murs T1/T2 devant, prendre 1er R:R >= MIN_RR_SELECTION
- Fallback TP_STANDARD = SL × 2.0 si aucun mur exploitable
- CAS 4 : si T1 ou T2_STRUCTUREL plus proche que TP, capot devant
- Cap final : tp_ticks = min(tp_ticks, sl_ticks * max_rr_cap)
- Plancher : reject si tp_ticks/sl_ticks < MIN_RR_RATIO (0.8)

Usage :
    python -X utf8 CORE/research/bot3_grid_search_sltp_adapted.py --symbol NQ --month 2026-04
    python -X utf8 CORE/research/bot3_grid_search_sltp_adapted.py --all
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.bot3_decision_engine import evaluate_decision  # noqa: E402
from CORE.bot3_level_definitions import get_active_levels  # noqa: E402
from CORE.bot3_context_analyzer import analyze_context  # noqa: E402
from CORE.bot3_config import (  # noqa: E402
    BOT3_ENABLE_TIER2,
    BOT3_ENABLE_TIER2_NEUTRAL,
    BOT3_ENABLE_TIER3,
    GUARD_RAILS_BOT3,
    ATR_BASELINE,
)


# ======================================================================
# CONFIG ANTI-TRICHE
# ======================================================================
TICK_SIZE = 0.25
COMMISSION_PER_RT = 0.74
SLIPPAGE_RTH_ENTRY = 1.5
SLIPPAGE_RTH_SL = 1.5
SLIPPAGE_RTH_TRAIL = 2.0
SLIPPAGE_RTH_TP = 0.5
SLIPPAGE_ASIA_ENTRY = 4.0
SLIPPAGE_ASIA_SL = 3.0
SLIPPAGE_ASIA_TRAIL = 3.0
SLIPPAGE_ASIA_TP = 1.0
NEWS_RVOL_THRESHOLD = 3.0
NEWS_RANGE_ATR_MULT = 2.0
TIER_PRIORITY = {1: 1, 2: 2, 3: 3, 99: 99}


# ======================================================================
# WALLS DEFINITION (porte de mia_sltp.py, adapte features v4)
# ======================================================================
# Format : (col_pct, name, role)
T1_WALLS_V4 = [
    ("dist_gex_nearest_up_pct", "GEX_UP", "resist"),
    ("dist_gex_nearest_dn_pct", "GEX_DN", "support"),
    ("dist_mq_call_0dte_pct", "MQ_CALL_0DTE", "both"),
    ("dist_mq_put_0dte_pct", "MQ_PUT_0DTE", "both"),
    ("dist_mq_hvl_0dte_pct", "MQ_HVL_0DTE", "both"),
    ("dist_sess_high_pct", "SESS_HIGH", "resist"),
    ("dist_sess_low_pct", "SESS_LOW", "support"),
]

T2_WALLS_V4 = [
    ("dist_cur_vah_pct", "CUR_VAH", "resist"),
    ("dist_cur_val_pct", "CUR_VAL", "support"),
    ("dist_cur_vpoc_pct", "CUR_VPOC", "both"),
    ("dist_prev_vah_pct", "PREV_VAH", "resist"),
    ("dist_prev_val_pct", "PREV_VAL", "support"),
    ("dist_vwap_d_sd1u_pct", "VWAP+1SD", "resist"),
    ("dist_vwap_d_sd1d_pct", "VWAP-1SD", "support"),
    ("dist_vwap_d_sd2u_pct", "VWAP+2SD", "resist"),
    ("dist_vwap_d_sd2d_pct", "VWAP-2SD", "support"),
    ("dist_ovn_high_pct", "OVN_HIGH", "resist"),
    ("dist_ovn_low_pct", "OVN_LOW", "support"),
    ("dist_last_swing_high_pct", "SWING_HIGH", "resist"),
    ("dist_last_swing_low_pct", "SWING_LOW", "support"),
    ("dist_1d_max_ticks_pct", "1D_MAX", "resist"),
    ("dist_1d_min_ticks_pct", "1D_MIN", "support"),
    ("dist_pvwap_sd1u_pct", "PVWAP+1SD", "resist"),
    ("dist_pvwap_sd1d_pct", "PVWAP-1SD", "support"),
    ("dist_mq_call_pct", "MQ_CALL", "both"),
    ("dist_mq_put_pct", "MQ_PUT", "both"),
    ("dist_mq_hvl_pct", "MQ_HVL", "both"),
    ("dist_vwap_w_pct", "VWAP_W", "both"),
    ("dist_open_830_pct", "OPEN_830", "both"),
    ("dist_blind_nearest_up_pct", "BLIND_UP", "resist"),
    ("dist_blind_nearest_dn_pct", "BLIND_DN", "support"),
    ("dist_vwap_m_pct", "VWAP_M", "both"),
]

T2_STRUCTUREL_V4 = frozenset({
    "VWAP+1SD", "VWAP-1SD", "VWAP+2SD", "VWAP-2SD",
    "VWAP_W", "VWAP_M",
    "1D_MAX", "1D_MIN",
    "MQ_CALL", "MQ_PUT", "MQ_HVL",
    "BLIND_UP", "BLIND_DN",
})

# Tous les walls flat (T1+T2) avec leur tier
ALL_WALLS_V4 = [(c, n, r, 1) for c, n, r in T1_WALLS_V4] + \
               [(c, n, r, 2) for c, n, r in T2_WALLS_V4]

# Snapshot columns (a stocker pour chaque signal pour grid search rapide)
SNAPSHOT_COLS = list({c for c, _, _, _ in ALL_WALLS_V4}) + [
    "close", "high", "low", "ts_event", "rvol",
    "atr", "is_in_us_cash", "is_in_us_after",
    "is_in_london", "is_in_asia", "vix_level",
    "within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
    "within_news_845_5m", "within_news_900_5m", "within_news_930_5m",
]


# ======================================================================
# SLTP PARAMS (constantes mia_sltp portees)
# ======================================================================
SL_BUFFER_TICKS = {"NQ": 8, "ES": 4}
TP_BUFFER_TICKS = {"NQ": 4, "ES": 2}
MIN_RR_RATIO = 0.8         # plancher absolu
MIN_RR_SELECTION = 1.5     # selection mur TP


# ======================================================================
# HELPERS
# ======================================================================

def _is_news_bar(bar: dict) -> bool:
    """Veto news bar : rvol > 3 OR range > 2*ATR_per_bar OR within_news_*."""
    rvol = float(bar.get("rvol", 1.0) or 1.0)
    if rvol > NEWS_RVOL_THRESHOLD:
        return True
    high = float(bar.get("high", 0) or 0)
    low = float(bar.get("low", 0) or 0)
    atr_14_ticks = float(bar.get("atr", 20.0) or 20.0)
    atr_per_bar_pts = atr_14_ticks * TICK_SIZE
    if atr_per_bar_pts > 0 and (high - low) > NEWS_RANGE_ATR_MULT * atr_per_bar_pts:
        return True
    for k in ("within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
              "within_news_845_5m", "within_news_900_5m", "within_news_930_5m"):
        v = bar.get(k, 0)
        try:
            fv = float(v) if v is not None else 0.0
            if fv != fv:
                continue
            if int(fv) == 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _slippage_for_session(session: str, kind: str) -> float:
    is_rth = (session in ("US_CASH", "US_AFTER"))
    table = {
        "entry": (SLIPPAGE_RTH_ENTRY, SLIPPAGE_ASIA_ENTRY),
        "sl": (SLIPPAGE_RTH_SL, SLIPPAGE_ASIA_SL),
        "trail": (SLIPPAGE_RTH_TRAIL, SLIPPAGE_ASIA_TRAIL),
        "tp": (SLIPPAGE_RTH_TP, SLIPPAGE_ASIA_TP),
    }
    rth, asia = table.get(kind, (1.0, 1.0))
    return rth if is_rth else asia


def _safe_int(v) -> int:
    """Convert val to int, treating NaN/None/invalid as 0."""
    if v is None:
        return 0
    try:
        f = float(v)
        if f != f:  # NaN
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _detect_session(bar: dict) -> str:
    if _safe_int(bar.get("is_in_us_cash", 0)) == 1:
        return "US_CASH"
    if _safe_int(bar.get("is_in_us_after", 0)) == 1:
        return "US_AFTER"
    if _safe_int(bar.get("is_in_london", 0)) == 1:
        return "LONDON"
    if _safe_int(bar.get("is_in_asia", 0)) == 1:
        return "ASIA"
    return "OTHER"


def _pct_to_ticks(dist_pct: float, close: float) -> float:
    """Convert dist_pct (signed) to ticks."""
    if close <= 0:
        return 0.0
    return dist_pct * close / TICK_SIZE


def _scan_walls_ahead(snapshot: dict, direction: int) -> list:
    """Scanne walls T1/T2 DEVANT le prix.

    Returns list of (name, role, tier, abs_dist_ticks, col_pct).
    """
    close = float(snapshot.get("close", 0))
    if close <= 0:
        return []
    walls = []
    for col_pct, name, role, tier in ALL_WALLS_V4:
        v = snapshot.get(col_pct)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN
            continue
        dist_ticks = _pct_to_ticks(v, close)
        abs_d = abs(dist_ticks)
        if abs_d < 3 or abs_d > 250:
            continue
        # Filter direction (LONG -> walls above, SHORT -> walls below)
        if direction == 1:  # LONG
            if role == "support":
                continue
            if dist_ticks < 0:
                continue
        else:  # SHORT
            if role == "resist":
                continue
            if dist_ticks > 0:
                continue
        walls.append((name, role, tier, abs_d, col_pct))
    walls.sort(key=lambda w: w[3])
    return walls


def compute_sltp_adapted(
    snapshot: dict,
    side: str,
    level_dist_ticks: float,
    symbol: str,
    config: dict,
) -> Optional[dict]:
    """Calcule SL/TP avec logique adaptee Bot 3.

    config = {
        'sl_min_respiration': int,     # plancher SL respiration ATR-based
        'sl_max_budget': int,          # cap SL budget (cohorte 80t NQ / 28t ES)
        'max_rr_cap': float,           # cap final RR (1.5/2.0/2.5)
    }

    Returns dict ou None si reject.
    """
    direction = 1 if side == "LONG" else -1
    sl_buffer = SL_BUFFER_TICKS.get(symbol, 5)
    tp_buffer = TP_BUFFER_TICKS.get(symbol, 4)

    # ----- 1. SL = max(level_dist+buffer, min_respiration), capot max_budget -----
    sl_naturel = abs(level_dist_ticks) + sl_buffer
    sl_min = config["sl_min_respiration"]
    sl_max = config["sl_max_budget"]
    sl_ticks = max(sl_naturel, sl_min)
    if sl_ticks > sl_max:
        return None  # SL hors budget

    # ----- 2. Scan murs devant pour TP -----
    walls = _scan_walls_ahead(snapshot, direction)

    # ----- 3. Find TP : 1er mur avec R:R >= MIN_RR_SELECTION -----
    tp_ticks = 0.0
    tp_wall = ""
    for name, role, tier, dist, col in walls:
        tp_cand = dist - tp_buffer
        if tp_cand <= 0:
            continue
        rr = tp_cand / sl_ticks if sl_ticks > 0 else 0
        if rr >= MIN_RR_SELECTION:
            tp_ticks = tp_cand
            tp_wall = f"WALL_{name}"
            break

    # Fallback : TP standard 2R si aucun mur acceptable
    if tp_ticks == 0:
        tp_ticks = sl_ticks * 2.0
        tp_wall = "TP_STANDARD"

    # ----- 4. CAS 4 : T1 ou T2_STRUCTUREL plus proche -> capot -----
    for name, role, tier, dist, col in walls:
        is_struct = (tier == 2 and name in T2_STRUCTUREL_V4)
        if (tier == 1 or is_struct) and dist < tp_ticks:
            tp_devant = math.floor(dist - tp_buffer)
            if tp_devant > 0:
                tp_ticks = float(tp_devant)
                tp_wall = f"DEVANT_{name}"
            break  # premier mur seulement

    # ----- 5. Cap RR final -----
    max_rr = config["max_rr_cap"]
    if tp_ticks > sl_ticks * max_rr:
        tp_ticks = sl_ticks * max_rr
        tp_wall = f"CAPPED_RR{max_rr}"

    # ----- 6. Plancher RR -----
    rr_final = tp_ticks / sl_ticks if sl_ticks > 0 else 0
    if rr_final < MIN_RR_RATIO:
        return None  # reject

    return {
        "sl_ticks": float(sl_ticks),
        "tp_ticks": float(tp_ticks),
        "tp_wall": tp_wall,
        "rr": float(rr_final),
    }


# ======================================================================
# PHASE 1 : Extraction signals
# ======================================================================

@dataclass
class Signal:
    """Snapshot d'un signal Bot 3 detecte."""
    entry_idx: int
    symbol: str
    level_name: str
    level_tier: int
    level_dist_ticks: float       # signed, level dist en ticks (converted from pct)
    side: str                      # LONG / SHORT
    action: str
    confidence: int
    entry_price: float
    entry_ts: str
    session: str
    snapshot: dict = field(default_factory=dict)  # cols pour scan walls TP


def extract_signals(symbol: str, df: pd.DataFrame) -> list[Signal]:
    """PHASE 1 : detect signals + snapshot features dist_*_pct.

    Re-utilise la logique de bot3_backtester.py (anti-triche identique).
    """
    print(f"\n=== Extract signals {symbol} : {len(df):,} bars ===", flush=True)

    active_levels = get_active_levels(
        enable_tier2=BOT3_ENABLE_TIER2,
        enable_tier3=BOT3_ENABLE_TIER3,
        symbol=symbol,
        enable_tier2_neutral=BOT3_ENABLE_TIER2_NEUTRAL,
    )
    print(f"  Niveaux actifs : {len(active_levels)}", flush=True)

    signals = []
    n_news_skip = 0

    for idx in range(len(df)):
        row = df.iloc[idx]
        bar = row.to_dict()
        bar["ts_event"] = str(bar["ts_event"])

        if _is_news_bar(bar):
            n_news_skip += 1
            continue

        ctx = analyze_context(bar)

        candidates = {}
        for level_name, level_def in active_levels.items():
            dist_col = level_def.get("dist_col")
            dist_val = bar.get(dist_col)
            if dist_val is None:
                continue
            try:
                dist_signed = float(dist_val)
            except (TypeError, ValueError):
                continue
            if dist_signed != dist_signed:
                continue
            if abs(dist_signed) > level_def.get("proximity_pct", 0.05):
                continue
            trade_ok, reason, params = evaluate_decision(
                level_name=level_name, level_def=level_def,
                ctx=ctx, symbol=symbol, dist_signed=dist_signed,
            )
            if trade_ok:
                candidates[level_name] = (level_def, dist_signed, ctx, params)

        if not candidates:
            continue

        # Tie-break Tier asc, confidence desc, |dist| asc
        sorted_cands = sorted(
            candidates.items(),
            key=lambda kv: (
                TIER_PRIORITY.get(kv[1][0].get("tier", 99), 99),
                -int(kv[1][3].get("confidence", 0)),
                abs(kv[1][1]),
            )
        )
        level_name, (level_def, dist_signed, ctx, params) = sorted_cands[0]

        # Convert dist_pct -> ticks
        close = float(bar.get("close", 0) or 0)
        level_dist_ticks = _pct_to_ticks(dist_signed, close)

        # Build snapshot
        snapshot = {c: bar.get(c) for c in SNAPSHOT_COLS}

        sig = Signal(
            entry_idx=idx,
            symbol=symbol,
            level_name=level_name,
            level_tier=level_def.get("tier", 99),
            level_dist_ticks=level_dist_ticks,
            side=params["side"],
            action=params.get("action", "REJECTION"),
            confidence=int(params.get("confidence", 50)),
            entry_price=close,
            entry_ts=str(bar["ts_event"]),
            session=ctx.get("session", _detect_session(bar)),
            snapshot=snapshot,
        )
        signals.append(sig)

        if len(signals) % 200 == 0:
            print(f"  ... {len(signals)} signals (idx {idx}/{len(df)})", flush=True)

    print(f"  Total signals : {len(signals)} (news skip {n_news_skip})", flush=True)
    return signals


# ======================================================================
# PHASE 2 : Simulation exit
# ======================================================================

@dataclass
class TradeResult:
    pnl_ticks_net: float = 0.0
    pnl_dollars_net: float = 0.0
    exit_reason: str = ""
    duration_bars: int = 0
    rr_realized: float = 0.0


def simulate_exit(
    df: pd.DataFrame, signal: Signal, sltp: dict,
    timeout_min: int, trail_act: int, trail_dist: int,
    n_contracts: int, tick_value: float,
) -> TradeResult:
    """Simule exit avec SL/TP nouvelle logique + anti-triche."""
    direction = 1 if signal.side == "LONG" else -1
    entry_idx = signal.entry_idx
    if entry_idx >= len(df):
        return TradeResult(exit_reason="NO_DATA")

    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    slip_entry = _slippage_for_session(signal.session, "entry")
    entry_with_slip = entry_price + direction * slip_entry * TICK_SIZE
    sl_price = entry_with_slip - direction * sltp["sl_ticks"] * TICK_SIZE
    tp_price = entry_with_slip + direction * sltp["tp_ticks"] * TICK_SIZE

    trailing_active = False
    best_price = entry_with_slip

    for j in range(1, timeout_min + 1):
        bar_idx = entry_idx + j
        if bar_idx >= len(df):
            break
        bar = df.iloc[bar_idx]
        h = float(bar["high"])
        l = float(bar["low"])
        sl_at_start = sl_price
        trailing_was_active = trailing_active

        sl_hit = (direction == 1 and l <= sl_at_start) or (direction == -1 and h >= sl_at_start)
        tp_hit = (direction == 1 and h >= tp_price) or (direction == -1 and l <= tp_price)

        if sl_hit and tp_hit:
            slip_kind = "trail" if trailing_was_active else "sl"
            slip_pts = _slippage_for_session(signal.session, slip_kind) * TICK_SIZE
            exit_p = sl_at_start - direction * slip_pts
            pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_ticks * tick_value * n_contracts - COMMISSION_PER_RT * n_contracts
            return TradeResult(
                pnl_ticks_net=pnl_d / (tick_value * n_contracts),
                pnl_dollars_net=pnl_d,
                exit_reason="SL_AMBIGUOUS" if not trailing_was_active else "TRAIL_AMBIGUOUS",
                duration_bars=j,
                rr_realized=pnl_ticks / sltp["sl_ticks"] if sltp["sl_ticks"] > 0 else 0,
            )

        if sl_hit:
            slip_kind = "trail" if trailing_was_active else "sl"
            slip_pts = _slippage_for_session(signal.session, slip_kind) * TICK_SIZE
            exit_p = sl_at_start - direction * slip_pts
            pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_ticks * tick_value * n_contracts - COMMISSION_PER_RT * n_contracts
            return TradeResult(
                pnl_ticks_net=pnl_d / (tick_value * n_contracts),
                pnl_dollars_net=pnl_d,
                exit_reason="TRAIL" if trailing_was_active else "SL",
                duration_bars=j,
                rr_realized=pnl_ticks / sltp["sl_ticks"] if sltp["sl_ticks"] > 0 else 0,
            )

        if tp_hit:
            slip_pts = _slippage_for_session(signal.session, "tp") * TICK_SIZE
            exit_p = tp_price - direction * slip_pts
            pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_ticks * tick_value * n_contracts - COMMISSION_PER_RT * n_contracts
            return TradeResult(
                pnl_ticks_net=pnl_d / (tick_value * n_contracts),
                pnl_dollars_net=pnl_d,
                exit_reason="TP",
                duration_bars=j,
                rr_realized=pnl_ticks / sltp["sl_ticks"] if sltp["sl_ticks"] > 0 else 0,
            )

        # Trailing update (defere a T+1, pas activable bar de touch)
        if direction == 1 and h > best_price:
            best_price = h
        elif direction == -1 and l < best_price:
            best_price = l
        favorable = (best_price - entry_with_slip) / TICK_SIZE * direction
        if not trailing_active and favorable >= trail_act:
            trailing_active = True
        if trailing_active:
            new_sl = best_price - direction * trail_dist * TICK_SIZE
            if direction == 1 and new_sl > sl_price:
                sl_price = new_sl
            elif direction == -1 and new_sl < sl_price:
                sl_price = new_sl

    # Timeout
    last_idx = min(entry_idx + timeout_min, len(df) - 1)
    last_bar = df.iloc[last_idx]
    final_price = float(last_bar["close"])
    slip_pts = _slippage_for_session(signal.session, "trail") * TICK_SIZE * 0.5
    exit_p = final_price - direction * slip_pts
    pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
    pnl_d = pnl_ticks * tick_value * n_contracts - COMMISSION_PER_RT * n_contracts
    return TradeResult(
        pnl_ticks_net=pnl_d / (tick_value * n_contracts),
        pnl_dollars_net=pnl_d,
        exit_reason="TIMEOUT",
        duration_bars=last_idx - entry_idx,
        rr_realized=pnl_ticks / sltp["sl_ticks"] if sltp["sl_ticks"] > 0 else 0,
    )


# ======================================================================
# PHASE 2.5 : Grid search (boucle configs)
# ======================================================================

def run_config(symbol: str, df: pd.DataFrame, signals: list[Signal],
               config: dict) -> dict:
    """Run 1 config = parcours signals + simulate exits."""
    cfg_guard = GUARD_RAILS_BOT3[symbol]
    n_contracts = cfg_guard["n_contracts"]
    tick_value = cfg_guard["tick_value"]
    trail_act = config["trailing_activation"]
    trail_dist = config["trailing_distance"]
    timeout_min = config["timeout_minutes"]

    pnls = []
    n_reject = 0
    n_pos_blocked = 0
    open_until_idx = -1
    sl_hits = 0
    tp_hits = 0
    timeouts = 0
    trail_exits = 0

    for sig in signals:
        if sig.entry_idx <= open_until_idx:
            n_pos_blocked += 1
            continue
        sltp = compute_sltp_adapted(
            sig.snapshot, sig.side, sig.level_dist_ticks, symbol, config
        )
        if sltp is None:
            n_reject += 1
            continue
        result = simulate_exit(
            df, sig, sltp, timeout_min, trail_act, trail_dist,
            n_contracts, tick_value,
        )
        pnls.append(result.pnl_dollars_net)
        open_until_idx = sig.entry_idx + result.duration_bars
        if result.exit_reason in ("SL", "SL_AMBIGUOUS"):
            sl_hits += 1
        elif result.exit_reason == "TP":
            tp_hits += 1
        elif result.exit_reason == "TIMEOUT":
            timeouts += 1
        elif result.exit_reason in ("TRAIL", "TRAIL_AMBIGUOUS"):
            trail_exits += 1

    if not pnls:
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "reject_pct": 100,
                "sl_pct": 0, "tp_pct": 0, "timeout_pct": 0, "trail_pct": 0,
                "total_pnl": 0}

    pnls_arr = np.array(pnls)
    wins = pnls_arr[pnls_arr > 0].sum()
    losses = abs(pnls_arr[pnls_arr < 0].sum())
    pf = wins / losses if losses > 0 else float("inf")
    wr = (pnls_arr > 0).sum() / len(pnls_arr) * 100
    ev = pnls_arr.mean()
    reject_pct = n_reject / (len(signals) - n_pos_blocked) * 100 if (len(signals) - n_pos_blocked) > 0 else 0

    return {
        "n": len(pnls),
        "pf": round(pf, 3) if pf != float("inf") else 999.0,
        "wr": round(wr, 1),
        "ev_dollars": round(ev, 2),
        "total_pnl": round(pnls_arr.sum(), 2),
        "reject_pct": round(reject_pct, 1),
        "sl_pct": round(sl_hits / len(pnls) * 100, 1),
        "tp_pct": round(tp_hits / len(pnls) * 100, 1),
        "timeout_pct": round(timeouts / len(pnls) * 100, 1),
        "trail_pct": round(trail_exits / len(pnls) * 100, 1),
        "n_reject": n_reject,
        "n_pos_blocked": n_pos_blocked,
    }


# ======================================================================
# GRID SEARCH SPACE
# ======================================================================

GRID_SPACE = {
    # Restreint NQ apres test 5K bars : top 5 etaient sl_min 60-70, sl_max 80-100,
    # rr_cap 2.0-2.5, timeout 15m, trail_act 30, trail_dist 12. Garde marge.
    "NQ": {
        "sl_min_respiration": [50, 60, 70, 80],
        "sl_max_budget": [80, 100, 120],
        "max_rr_cap": [2.0, 2.5],
        "timeout_minutes": [15, 20, 30],
        "trailing_activation": [25, 30],
        "trailing_distance": [10, 12, 14],
    },
    "ES": {
        "sl_min_respiration": [10, 12, 14, 16, 18],
        "sl_max_budget": [20, 28, 36],
        "max_rr_cap": [1.5, 2.0, 2.5],
        "timeout_minutes": [15, 20, 30],
        "trailing_activation": [8, 12],
        "trailing_distance": [5, 8],
    },
}


def iter_configs(symbol: str):
    """Genere tous les configs du grid space."""
    space = GRID_SPACE[symbol]
    for sl_min in space["sl_min_respiration"]:
        for sl_max in space["sl_max_budget"]:
            if sl_min >= sl_max:  # eviter sl_min > sl_max
                continue
            for max_rr in space["max_rr_cap"]:
                for timeout in space["timeout_minutes"]:
                    for trail_act in space["trailing_activation"]:
                        for trail_dist in space["trailing_distance"]:
                            yield {
                                "sl_min_respiration": sl_min,
                                "sl_max_budget": sl_max,
                                "max_rr_cap": max_rr,
                                "timeout_minutes": timeout,
                                "trailing_activation": trail_act,
                                "trailing_distance": trail_dist,
                            }


def run_grid_search(symbol: str, df: pd.DataFrame, signals: list[Signal],
                    out_dir: Path, run_id: str) -> list[dict]:
    """PHASE 2 : grid search sur tous les configs."""
    print(f"\n=== Grid Search {symbol} ===", flush=True)
    configs = list(iter_configs(symbol))
    print(f"  Total configs : {len(configs)}", flush=True)

    results = []
    for i, cfg in enumerate(configs, 1):
        stats = run_config(symbol, df, signals, cfg)
        cfg_full = {**cfg, **stats}
        results.append(cfg_full)
        if i % 20 == 0 or i == len(configs):
            print(f"  ... {i}/{len(configs)} configs (n={stats['n']} pf={stats['pf']} wr={stats['wr']})", flush=True)

    # Sort by PF (with WR>=50, n>=100 priority)
    def sort_key(r):
        if r["n"] < 100:
            return -1  # last
        if r["wr"] < 50:
            return 0
        return r["pf"]

    results.sort(key=sort_key, reverse=True)

    # Save full results
    out_csv = out_dir / f"grid_{symbol}_{run_id}.csv"
    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"  Results saved : {out_csv}", flush=True)

    # Print top 10
    print(f"\n  TOP 10 {symbol} (PF, WR>=50, n>=100) :", flush=True)
    for r in results[:10]:
        print(f"    sl_min={r['sl_min_respiration']}t sl_max={r['sl_max_budget']}t "
              f"rr_cap={r['max_rr_cap']} timeout={r['timeout_minutes']}m "
              f"trailA={r['trailing_activation']}/D={r['trailing_distance']} "
              f"-> n={r['n']} PF={r['pf']} WR={r['wr']}% "
              f"EV=${r['ev_dollars']} totPnL=${r['total_pnl']} "
              f"SL%={r['sl_pct']} TP%={r['tp_pct']} TO%={r['timeout_pct']} "
              f"reject%={r['reject_pct']}", flush=True)

    return results


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=["NQ", "ES", "ALL"], default="ALL")
    parser.add_argument("--month", default=None,
                        help="YYYY-MM (default tous les mois)")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit-bars", type=int, default=None,
                        help="limit N premieres bars (debug)")
    parser.add_argument("--force-reextract", action="store_true",
                        help="force re-extract signals (ignore cache pickle)")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "DATA" / "BACKTEST" / "BOT3_GRID_SLTP"
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["NQ", "ES"] if args.symbol == "ALL" else [args.symbol]
    all_summaries = {}

    for sym in symbols:
        print(f"\n{'='*70}\n  GRID SEARCH SLTP {sym} - run_id={run_id}\n{'='*70}", flush=True)
        sym_dir = ROOT / "DATA" / "DATASETS" / "v4_enriched" / f"symbol={sym}.c.0"
        if args.month:
            year, month = args.month.split("-")
            files = list(sym_dir.glob(f"year={year}/month={month}/data.parquet"))
        else:
            files = sorted(sym_dir.glob("year=*/month=*/data.parquet"))
        if not files:
            print(f"  ERREUR : aucun parquet pour {sym}", flush=True)
            continue
        print(f"  Loading {len(files)} parquet files...", flush=True)
        dfs = []
        for f in files:
            df = pd.read_parquet(f)
            if "ts_event" in df.columns:
                ts = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
                df["ts_event"] = ts.dt.tz_localize(None)
            dfs.append(df)
        df = pd.concat(dfs, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
        if args.limit_bars:
            df = df.head(args.limit_bars).copy()
        print(f"  Total bars : {len(df):,}", flush=True)

        # Phase 1 : extract signals (avec cache pickle)
        cache_signals = out_dir / f"signals_{sym}_{run_id}.pkl"
        if cache_signals.exists() and not args.force_reextract:
            print(f"  Loading signals cache : {cache_signals}", flush=True)
            with cache_signals.open("rb") as f:
                signals = pickle.load(f)
            print(f"  Loaded {len(signals)} signals from cache", flush=True)
        else:
            signals = extract_signals(sym, df)
            with cache_signals.open("wb") as f:
                pickle.dump(signals, f)
            print(f"  Cached {len(signals)} signals to {cache_signals}", flush=True)
        if not signals:
            print(f"  Aucun signal {sym}, skip", flush=True)
            continue

        # Phase 2 : grid search
        results = run_grid_search(sym, df, signals, out_dir, run_id)
        all_summaries[sym] = {
            "n_signals": len(signals),
            "n_configs": len(results),
            "top1": results[0] if results else {},
        }

    summary_path = out_dir / f"summary_{run_id}.json"
    summary_path.write_text(
        json.dumps({"run_id": run_id, "symbols": all_summaries}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n  Summary final : {summary_path}", flush=True)


if __name__ == "__main__":
    main()
