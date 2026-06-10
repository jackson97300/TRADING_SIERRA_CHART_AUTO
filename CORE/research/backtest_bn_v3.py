"""backtest_bn_v3.py — Backtest BN V3 sur data v4 enriched (Bot 2 Sim2 source).

Pipeline simulation :
  1. Load 2 mois data v4 enriched (mars + avril 2026 = derniers complets)
  2. Pour chaque bar : run BNV3Engine.detect() puis detect_recharge() si actif
  3. Simulate trades : entry 2 contrats, recharge +1 sur long_up_bar/long_dn_bar,
     SL hit / TP scale-out 50% +60t MFE / time stop 90 min / EOD flatten 16:00 ET
  4. Output : PF, WR, n_trades, avg_pnl, n_recharges_avg

Usage :
    python -X utf8 CORE/research/backtest_bn_v3.py --sym NQ
    python -X utf8 CORE/research/backtest_bn_v3.py --sym ES --no-recharge

Auteur : MIA Trading System
Date   : 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v3_engine import (
    BNV3Engine, BNV3State,
    N_CONTRACTS_INITIAL, MAX_PYRAMID_LOADS, SCALE_OUT_TRIGGER_TICKS, SCALE_OUT_PCT,
    TICK_SIZE,
)


# ─── Config simulation ────────────────────────────────────────────────────

TICK_VALUE_USD = {"NQ": 0.50, "ES": 1.25}  # micros
MAX_TRADE_DURATION_MIN = 90                # time stop 90 min
SL_TICKS_FALLBACK = 60                     # safety fallback si SL > 60t (mauvais setup)
COMMISSION_USD_PER_CONTRACT = 0.50         # AMP CME micros aller-retour


@dataclass
class TradeResult:
    ts_entry: pd.Timestamp
    ts_exit: pd.Timestamp
    direction: str
    entry_price: float
    exit_price: float
    sl_price: float
    n_contracts_total: int
    n_recharges: int
    pnl_ticks_unweighted: float                      # ticks par contrat moyen
    pnl_usd: float
    exit_reason: str
    bars_in_trade: int


def simulate_trade(df: pd.DataFrame, entry_idx: int, engine: BNV3Engine,
                   state: BNV3State, sym: str,
                   recharge_enabled: bool = True) -> TradeResult:
    """Simule 1 trade BN V3 depuis entry_idx jusqu'a sortie (SL/TP/time/EOD).

    Logique :
      - Initial : 2 contrats @ entry_price
      - Pendant trade : si long_up_bar/long_dn_bar fire ET trend OK ET in profit
        -> +1 contrat (max +2 recharges -> 4 contrats max)
      - SL hit -> close all
      - MFE +60t (NQ) / +25t (ES) -> scale out 50% au prix TP_partial
      - Apres scale out : SL passe a BE (entry price)
      - Time stop 90 min ou EOD 16:00 ET -> close all market
    """
    tick_size = TICK_SIZE[sym]
    direction = state.direction
    entry_price = state.entry_price
    sl_price = state.sl_price
    tp_partial_price = state.tp_partial_price

    # Pyramid tracking
    contracts_open = N_CONTRACTS_INITIAL
    recharge_entries = []  # list of (idx, price)
    scaled_out = False
    scaled_out_price = None
    scaled_out_idx = None

    # SL / TP
    if direction == "LONG":
        sl_hit_fn = lambda bar_low: bar_low <= sl_price
        tp_hit_fn = lambda bar_high: bar_high >= tp_partial_price
    else:
        sl_hit_fn = lambda bar_high: bar_high >= sl_price
        tp_hit_fn = lambda bar_low: bar_low <= tp_partial_price

    n = len(df)
    exit_idx = None
    exit_price = None
    exit_reason = ""

    for i in range(entry_idx + 1, min(entry_idx + MAX_TRADE_DURATION_MIN + 1, n)):
        bar = df.iloc[i]

        # --- Time stop / EOD ---
        ts = bar["ts_event"]
        if hasattr(ts, "tz_convert"):
            ts_et = ts.tz_convert("US/Eastern") if ts.tz else ts.tz_localize("UTC").tz_convert("US/Eastern")
        else:
            ts_et = pd.Timestamp(ts).tz_localize("UTC").tz_convert("US/Eastern")
        if ts_et.hour >= 16:  # EOD 16:00 ET
            exit_idx = i
            exit_price = float(bar["close"])
            exit_reason = "EOD_FLATTEN"
            break

        bars_in_trade = i - entry_idx
        if bars_in_trade >= MAX_TRADE_DURATION_MIN:
            exit_idx = i
            exit_price = float(bar["close"])
            exit_reason = "TIME_STOP_90M"
            break

        # --- SL hit ---
        if direction == "LONG" and sl_hit_fn(bar["low"]):
            exit_idx = i
            exit_price = sl_price
            exit_reason = "SL_HIT" if not scaled_out else "BE_HIT"
            break
        if direction == "SHORT" and sl_hit_fn(bar["high"]):
            exit_idx = i
            exit_price = sl_price
            exit_reason = "SL_HIT" if not scaled_out else "BE_HIT"
            break

        # --- TP scale out (50%) ---
        if not scaled_out and tp_hit_fn(bar["high" if direction == "LONG" else "low"]):
            scaled_out = True
            scaled_out_price = tp_partial_price
            scaled_out_idx = i
            # Move SL to BE on remaining
            sl_price = entry_price
            if direction == "LONG":
                sl_hit_fn = lambda bar_low: bar_low <= sl_price
            else:
                sl_hit_fn = lambda bar_high: bar_high >= sl_price

        # --- Recharge si long_up_bar/long_dn_bar fire ---
        if recharge_enabled and contracts_open < N_CONTRACTS_INITIAL + MAX_PYRAMID_LOADS:
            window = df.iloc[:i + 1]
            try:
                rec_result = engine.detect_recharge(window, state)
                if rec_result.signal in ("RECHARGE_LONG", "RECHARGE_SHORT"):
                    contracts_open += 1
                    recharge_entries.append((i, float(bar["close"])))
            except Exception:
                pass

    # Force exit at end of data si toujours ouvert
    if exit_idx is None:
        exit_idx = n - 1
        exit_price = float(df.iloc[exit_idx]["close"])
        exit_reason = "END_OF_DATA"

    # --- Compute PnL ---
    # Initial 2 contrats : pnl from entry_price -> exit (avec eventual scale_out)
    # Recharge contrats : pnl from recharge_entries[i].price -> exit
    sign = 1.0 if direction == "LONG" else -1.0
    pnl_ticks_per_contract_avg = 0.0
    total_contract_units = 0  # somme de contrats * 1 unite

    # Initial 2 contrats
    if scaled_out:
        # 1 contrat sort au TP (50%), 1 reste jusqu'a exit
        pnl_scaled = sign * (scaled_out_price - entry_price) / tick_size
        pnl_runner = sign * (exit_price - entry_price) / tick_size
        # Bot 2 sizing : 1+1 sur initial 2 contrats
        pnl_ticks_per_contract_avg += pnl_scaled + pnl_runner
        total_contract_units += 2
    else:
        # Tous les 2 contrats sortent au meme prix
        pnl_init = sign * (exit_price - entry_price) / tick_size
        pnl_ticks_per_contract_avg += pnl_init * 2
        total_contract_units += 2

    # Recharges contrats : tous sortent au exit_price
    for (rec_idx, rec_price) in recharge_entries:
        pnl_rec = sign * (exit_price - rec_price) / tick_size
        pnl_ticks_per_contract_avg += pnl_rec
        total_contract_units += 1

    # Convert ticks -> USD (micros)
    pnl_usd = pnl_ticks_per_contract_avg * TICK_VALUE_USD[sym]
    pnl_usd -= total_contract_units * COMMISSION_USD_PER_CONTRACT

    # Avg ticks per contract for diagnostics
    pnl_ticks_avg = pnl_ticks_per_contract_avg / total_contract_units if total_contract_units > 0 else 0

    return TradeResult(
        ts_entry=df.iloc[entry_idx]["ts_event"],
        ts_exit=df.iloc[exit_idx]["ts_event"],
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        sl_price=state.sl_price,
        n_contracts_total=total_contract_units,
        n_recharges=len(recharge_entries),
        pnl_ticks_unweighted=pnl_ticks_avg,
        pnl_usd=pnl_usd,
        exit_reason=exit_reason,
        bars_in_trade=exit_idx - entry_idx,
    )


def run_backtest(sym: str, months: list[tuple[int, int]],
                 recharge_enabled: bool = True,
                 dow_min_swings: int = 2,
                 adx_min: float = 20.0) -> tuple[list[TradeResult], dict]:
    """Charge data + run BN V3 sur chaque bar + simule trades."""
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0"
    dfs = []
    for (year, month) in months:
        f = base / f"year={year}" / f"month={month:02d}" / "data.parquet"
        if not f.exists():
            print(f"[WARN] missing {f}")
            continue
        df = pd.read_parquet(f)
        dfs.append(df)
    if not dfs:
        raise RuntimeError(f"No data for {sym} in {months}")
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"[{sym}] Loaded {len(df)} bars from {df.ts_event.min()} -> {df.ts_event.max()}")

    # Run engine on each bar (sliding window)
    engine = BNV3Engine(
        sym=sym, use_range_filter=False,  # Skip range_detector for backtest speed
        dow_min_swings=dow_min_swings,
        adx_min=adx_min,
    )
    state = BNV3State()
    trades: list[TradeResult] = []

    n = len(df)
    print(f"[{sym}] Running BN V3 detection (recharge={'ON' if recharge_enabled else 'OFF'})...", flush=True)
    next_search_idx = 100  # warmup
    last_progress = 0

    while next_search_idx < n - MAX_TRADE_DURATION_MIN:
        # Progress
        pct = int(next_search_idx / n * 100)
        if pct >= last_progress + 5:
            print(f"[{sym}] Progress {pct}% (idx={next_search_idx}/{n}, trades={len(trades)})", flush=True)
            last_progress = pct
        window = df.iloc[:next_search_idx + 1]
        result = engine.detect(window, state)
        if result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
            # Simulate trade
            trade = simulate_trade(df, next_search_idx, engine, state, sym,
                                   recharge_enabled=recharge_enabled)
            trades.append(trade)
            # Skip ahead past trade exit + cooldown 10 bars
            next_search_idx = (next_search_idx + trade.bars_in_trade + 10)
            # Reset state pour permettre nouveau setup
            state = BNV3State()
            state.last_setup_idx = next_search_idx - 11
        else:
            next_search_idx += 1

    # Stats
    if not trades:
        return trades, {"n_trades": 0, "pf": 0.0, "wr": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0}

    pnls = np.array([t.pnl_usd for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    wr = len(wins) / len(pnls) * 100
    stats = {
        "n_trades": len(trades),
        "pf": float(pf),
        "wr": float(wr),
        "avg_pnl_usd": float(pnls.mean()),
        "total_pnl_usd": float(pnls.sum()),
        "n_long": sum(1 for t in trades if t.direction == "LONG"),
        "n_short": sum(1 for t in trades if t.direction == "SHORT"),
        "avg_recharges": float(np.mean([t.n_recharges for t in trades])),
        "max_recharges": max(t.n_recharges for t in trades),
        "avg_bars_in_trade": float(np.mean([t.bars_in_trade for t in trades])),
        "exit_reasons": {r: sum(1 for t in trades if t.exit_reason == r)
                         for r in set(t.exit_reason for t in trades)},
    }
    return trades, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sym", choices=["NQ", "ES"], default="NQ")
    parser.add_argument("--months", default="2026-03,2026-04",
                        help="Format YYYY-MM,YYYY-MM (defaut : mars+avril 2026)")
    parser.add_argument("--no-recharge", action="store_true",
                        help="Desactive recharge pour A/B test")
    parser.add_argument("--dow-min-swings", type=int, default=2)
    parser.add_argument("--adx-min", type=float, default=20.0)
    parser.add_argument("--output", help="CSV output path (optional)")
    args = parser.parse_args()

    months = []
    for m in args.months.split(","):
        y, mo = m.strip().split("-")
        months.append((int(y), int(mo)))

    print(f"=== BN V3 Backtest {args.sym} ===")
    print(f"Months: {months}")
    print(f"Recharge enabled: {not args.no_recharge}")
    print(f"Dow min swings: {args.dow_min_swings}")
    print(f"ADX min: {args.adx_min}")
    print()

    trades, stats = run_backtest(
        sym=args.sym, months=months,
        recharge_enabled=not args.no_recharge,
        dow_min_swings=args.dow_min_swings,
        adx_min=args.adx_min,
    )

    print()
    print(f"=== STATS {args.sym} ===")
    for k, v in stats.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        elif isinstance(v, float):
            print(f"  {k}: {v:.3f}")
        else:
            print(f"  {k}: {v}")

    if args.output and trades:
        df_out = pd.DataFrame([t.__dict__ for t in trades])
        df_out.to_csv(args.output, index=False)
        print(f"\nTrades CSV saved: {args.output}")


if __name__ == "__main__":
    main()
