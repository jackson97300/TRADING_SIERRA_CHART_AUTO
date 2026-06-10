"""Backtest Bot 3 Gold Full Rules (8 scenarios dynamiques) sur 4 mois MGC enrichi.

Selon PROMPT_CLAUDE_CODE_BOT3_GOLD.md :
  - 36 niveaux NEUTRAUX (7 Gold-specific + 29 MP)
  - 8 scenarios dynamiques
  - Vetos absolus (news, fix, RTH-only, etc.)
  - SL 200t base, trailing 80/50, timeout 60min, R:R 2.0

Output : DOCS/EDGE_REPORT_BOT3_GOLD_8SCENARIOS.md + stats par scenario
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from collections import Counter
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np

from bot3_gold_level_definitions import (
    get_all_gold_levels, is_ticks_level, get_proximity,
)
from bot3_gold_decision_engine import (
    build_gold_context, evaluate_decision_gold,
)

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_mq_enriched.parquet"
OUT_DIR = ROOT / "DATA" / "BACKTEST" / "GOLD"

TICK_SIZE = 0.10
TICK_VALUE = 1.0
N_CONTRACTS = 3
COMMISSION_PER_RT = 0.74

SLIP = {"entry": 1.5, "sl": 1.5, "tp": 0.5, "trail": 2.0}

TRAIL_ACTIVATION = 80   # +8 pts Gold
TRAIL_DISTANCE = 50     # trail à 5 pts
TIMEOUT_MIN = 60        # 60 min Gold timeout
TP_CAP_TICKS = 400      # 40 pts Gold max cap


def detect_touch(bar: dict, level_def: dict) -> tuple[bool, float]:
    col = level_def["col"]
    val = bar.get(col)
    if val is None or pd.isna(val):
        return False, 0.0
    try:
        d = float(val)
    except (TypeError, ValueError):
        return False, 0.0
    if d != d:
        return False, 0.0

    prox, ticks_based = get_proximity(level_def)
    if ticks_based:
        return abs(d) <= prox, d
    return abs(d) <= prox, d


def simulate_trade(df, entry_idx, side, sl_ticks, tp_ticks):
    """Simule trade avec SL/TP/trailing/timeout."""
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    direction = 1 if side == "LONG" else -1
    entry_with_slip = entry_price + direction * SLIP["entry"] * TICK_SIZE
    sl_price = entry_with_slip - direction * sl_ticks * TICK_SIZE
    tp_price = entry_with_slip + direction * tp_ticks * TICK_SIZE

    best = entry_with_slip
    trailing_active = False

    for j in range(1, TIMEOUT_MIN + 1):
        idx = entry_idx + j
        if idx >= len(df):
            break
        bar = df.iloc[idx]
        h = float(bar["high"])
        l = float(bar["low"])
        sl_at_start = sl_price
        trailing_was = trailing_active

        sl_hit = (direction == 1 and l <= sl_at_start) or (direction == -1 and h >= sl_at_start)
        tp_hit = (direction == 1 and h >= tp_price) or (direction == -1 and l <= tp_price)

        if sl_hit and tp_hit:
            slip_pts = SLIP["trail" if trailing_was else "sl"] * TICK_SIZE
            exit_p = sl_at_start - direction * slip_pts
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL_AMB"
        if sl_hit:
            slip_pts = SLIP["trail" if trailing_was else "sl"] * TICK_SIZE
            exit_p = sl_at_start - direction * slip_pts
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "TRAIL" if trailing_was else "SL"
        if tp_hit:
            exit_p = tp_price - direction * SLIP["tp"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "TP"

        # Update trailing
        if direction == 1 and h > best:
            best = h
        elif direction == -1 and l < best:
            best = l
        fav = (best - entry_with_slip) / TICK_SIZE * direction
        if not trailing_active and fav >= TRAIL_ACTIVATION:
            trailing_active = True
        if trailing_active:
            new_sl = best - direction * TRAIL_DISTANCE * TICK_SIZE
            if direction == 1 and new_sl > sl_price:
                sl_price = new_sl
            elif direction == -1 and new_sl < sl_price:
                sl_price = new_sl

    # Timeout
    last_idx = min(entry_idx + TIMEOUT_MIN, len(df) - 1)
    exit_p = float(df.iloc[last_idx]["close"]) - direction * SLIP["sl"] * TICK_SIZE * 0.5
    pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
    pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
    return pnl_d, last_idx - entry_idx, "TIMEOUT"


def main():
    print(f"=== BACKTEST BOT 3 GOLD — 8 SCENARIOS DYNAMIQUES ===\n")
    print(f"  Source : {INPUT}")
    df = pd.read_parquet(INPUT)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"  Shape : {df.shape}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    levels = get_all_gold_levels()
    print(f"  Niveaux : {len(levels)} (tous NEUTRAL)")

    pnls = []
    trades_log = []
    open_until = -1
    exit_counts = Counter()
    side_counts = Counter()
    scenario_counts = Counter()
    skip_counts = Counter()
    macro_bias_counts = Counter()
    n_touches = 0
    n_evaluations = 0

    for i in range(len(df)):
        if i <= open_until:
            continue
        bar = df.iloc[i].to_dict()

        # Detect touches
        touched = []
        for name, lvl in levels.items():
            is_touch, dist = detect_touch(bar, lvl)
            if is_touch:
                touched.append((name, lvl, dist))
        if not touched:
            continue
        n_touches += len(touched)

        # Tie-break : Tier 1 le plus proche
        touched.sort(key=lambda x: (x[1].get("tier", 99), abs(x[2])))
        name, lvl, dist = touched[0]
        n_evaluations += 1

        # Build context
        ctx = build_gold_context(bar)
        macro_bias_counts[ctx["macro_bias"]] += 1

        # Decision
        trade, reason, params = evaluate_decision_gold(name, lvl, ctx, dist)
        if not trade:
            # Categorize skip
            cat = reason.split("_")[0] if "_" in reason else reason
            skip_counts[cat] += 1
            continue

        side = params["side"]
        scenario_counts[params["scenario"]] += 1
        sl_ticks = min(params["sl_ticks"], 300)  # cap absolu 30pts
        tp_ticks = min(sl_ticks * 2, TP_CAP_TICKS)  # R:R 2 cap 40pts

        result = simulate_trade(df, i, side, sl_ticks, tp_ticks)
        if result is None:
            continue
        pnl, dur, exit_reason = result
        pnls.append(pnl)
        open_until = i + dur
        exit_counts[exit_reason] += 1
        side_counts[side] += 1
        trades_log.append({
            "level": name, "side": side, "scenario": params["scenario"],
            "pnl": pnl, "exit": exit_reason, "macro": ctx["macro_bias"],
            "confidence": params["confidence"],
        })

    # Stats
    if not pnls:
        print("  AUCUN TRADE")
        return

    pnls_arr = np.array(pnls)
    wins = pnls_arr[pnls_arr > 0].sum()
    losses = abs(pnls_arr[pnls_arr < 0].sum())
    pf = wins / losses if losses > 0 else 999.0
    wr = (pnls_arr > 0).sum() / len(pnls_arr) * 100
    ev = pnls_arr.mean()
    total = pnls_arr.sum()

    print(f"\n=== RESULTATS ===")
    print(f"  Touches : {n_touches:,}")
    print(f"  Évaluations (tie-break) : {n_evaluations:,}")
    print(f"  Trades exécutés : {len(pnls):,}")
    print(f"  PF : {pf:.3f}")
    print(f"  WR : {wr:.1f}%")
    print(f"  EV : ${ev:.2f}")
    print(f"  Total PnL : ${total:,.2f}")
    print(f"\n  Distribution side : {dict(side_counts)}")
    print(f"  Exit reasons : {dict(exit_counts)}")
    print(f"\n  Macro bias distribution : {dict(macro_bias_counts)}")
    print(f"\n  Scenarios déclenchés :")
    for s, n in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        scenario_pnls = [t["pnl"] for t in trades_log if t["scenario"] == s]
        s_pf = (sum(p for p in scenario_pnls if p > 0)
                / max(abs(sum(p for p in scenario_pnls if p < 0)), 0.01))
        s_wr = sum(1 for p in scenario_pnls if p > 0) / len(scenario_pnls) * 100 if scenario_pnls else 0
        print(f"    {s:35s} n={n:4d}  PF={s_pf:.2f}  WR={s_wr:.1f}%")
    print(f"\n  Top skips :")
    for r, n in skip_counts.most_common(8):
        print(f"    {r:30s} {n:6d}")

    # Verdict
    print(f"\n=== VERDICT ===")
    if len(pnls) < 50:
        verdict = "INSUFFICIENT_N"
    elif pf >= 1.5 and wr >= 50:
        verdict = "GO STRONG — approche dynamique valide"
    elif pf >= 1.3 and wr >= 45:
        verdict = "GO MARGINAL"
    elif pf >= 1.0:
        verdict = "NEUTRAL"
    else:
        verdict = "NOGO"
    print(f"  {verdict}")

    # Save
    summary = {
        "n_touches": n_touches, "n_evaluations": n_evaluations,
        "n_trades": len(pnls), "pf": round(pf, 3), "wr": round(wr, 1),
        "ev": round(ev, 2), "total_pnl": round(total, 2),
        "side_counts": dict(side_counts), "exit_counts": dict(exit_counts),
        "macro_bias": dict(macro_bias_counts),
        "scenarios": dict(scenario_counts),
        "verdict": verdict,
    }
    out = OUT_DIR / "bot3_gold_8scenarios_results.json"
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved : {out}")


if __name__ == "__main__":
    main()
