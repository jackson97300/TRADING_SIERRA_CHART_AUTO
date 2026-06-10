"""backtest_bn_v3_variants.py — Compare 4 variantes BN V3 sur NQ.

Variantes (Jackson directive 13/05/2026 chart NQ 13/05 replies 2->3, 4->5, 6->7) :

  A_baseline  : V3 actuel (swing=3, dow=3, recharge long_up_bar/long_dn_bar)
  B_reactif   : swing=2, dow=2 (plus de pivots detectes, entry plus tot)
  C_hybride   : A + trail dynamique check_lowest_green_trail (exit sur rouge
                qui ferme sous verte plus basse, en plus des autres regles)
  D_edge_zon  : A + recharge sur bar_edge_buy_fire (LONG) ou bar_edge_sell_fire
                (SHORT) — en plus de long_up_bar/long_dn_bar

Output : tableau comparatif PF/WR/n_trades/avg_pnl/max_DD/avg_recharges
         + CSV par trade par variante pour drill-down.

Anti data_mining_trap : ce backtest est Phase 1 (eliminatoire). Le finaliste
doit passer Phase 2 (walk-forward 12-fold + DSR Lopez via agent ml-trainer)
avant tout deploy.

Usage :
    python -X utf8 CORE/research/backtest_bn_v3_variants.py
    python -X utf8 CORE/research/backtest_bn_v3_variants.py --months 2026-04,2026-05

Date : 2026-05-13
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v3_engine import (
    BNV3Engine, BNV3State, BNV3Result,
    N_CONTRACTS_INITIAL, MAX_PYRAMID_LOADS, SCALE_OUT_TRIGGER_TICKS,
    TICK_SIZE,
)
from CORE.research.backtest_bn_v3 import (
    TradeResult, TICK_VALUE_USD, MAX_TRADE_DURATION_MIN,
    COMMISSION_USD_PER_CONTRACT,
)


# ─── Variantes config ─────────────────────────────────────────────────────

VARIANTS = {
    "A_baseline":      dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=False, recharge_edge_zones=False,
                            enable_mode2=False),
    "B_reactif":       dict(swing_min_bars=2, dow_min_swings=2,
                            use_trail_dyn=False, recharge_edge_zones=False,
                            enable_mode2=False),
    "C_hybride":       dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=True,  recharge_edge_zones=False,
                            enable_mode2=False),
    "D_edge_zon":      dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=False, recharge_edge_zones=True,
                            enable_mode2=False),
    # Variante E : A_baseline + Mode 2 amorce range break (Jackson 13/05 directive)
    "E_mode2_range":   dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=False, recharge_edge_zones=False,
                            enable_mode2=True, enable_mode3=False),
    # Variante G : A + Mode 2 + recharge edge zones
    "G_mode2_edge":    dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=False, recharge_edge_zones=True,
                            enable_mode2=True, enable_mode3=False),
    # Variante F : A + Mode 3 V-reversal (Jackson 13/05 - capitulation + depart en V)
    "F_mode3_vrev":    dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=False, recharge_edge_zones=False,
                            enable_mode2=False, enable_mode3=True),
    # Variante H : A + Mode 2 + Mode 3 (les 3 portes d'amorce BN actives)
    "H_all_modes":     dict(swing_min_bars=3, dow_min_swings=3,
                            use_trail_dyn=False, recharge_edge_zones=False,
                            enable_mode2=True, enable_mode3=True),
}


# ─── Simulator etendu (gere variantes C et D) ─────────────────────────────

def simulate_trade_v(df: pd.DataFrame, entry_idx: int,
                     engine: BNV3Engine, state: BNV3State, sym: str,
                     use_trail_dyn: bool = False,
                     recharge_edge_zones: bool = False) -> TradeResult:
    """Simule 1 trade BN V3 avec extensions variantes C (trail dyn) + D (edge zones).

    Difference vs simulate_trade original :
      - use_trail_dyn=True  : check check_lowest_green_trail chaque bar.
                              Si trend_broken=True -> exit immediat (TRAIL_BROKEN).
      - recharge_edge_zones=True : recharge si bar_edge_buy_fire=1 (LONG) ou
                              bar_edge_sell_fire=1 (SHORT) en plus de long_up/dn_bar.
    """
    tick_size = TICK_SIZE[sym]
    direction = state.direction
    entry_price = state.entry_price
    sl_price = state.sl_price
    tp_partial_price = state.tp_partial_price

    contracts_open = N_CONTRACTS_INITIAL
    recharge_entries: list[tuple[int, float, str]] = []
    scaled_out = False
    scaled_out_price = None

    if direction == "LONG":
        sl_hit_fn = lambda bar_low: bar_low <= sl_price
        tp_hit_fn = lambda bar_high: bar_high >= tp_partial_price
    else:
        sl_hit_fn = lambda bar_high: bar_high >= sl_price
        tp_hit_fn = lambda bar_low: bar_low <= tp_partial_price

    edge_buy_col = "bar_edge_buy_fire"
    edge_sell_col = "bar_edge_sell_fire"
    has_edge_cols = edge_buy_col in df.columns and edge_sell_col in df.columns

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
        if ts_et.hour >= 16:
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

        # --- TP scale out ---
        if not scaled_out and tp_hit_fn(bar["high" if direction == "LONG" else "low"]):
            scaled_out = True
            scaled_out_price = tp_partial_price
            sl_price = entry_price  # move SL to BE
            if direction == "LONG":
                sl_hit_fn = lambda bar_low: bar_low <= sl_price
            else:
                sl_hit_fn = lambda bar_high: bar_high >= sl_price

        # --- VARIANTE C : trail dynamique ---
        if use_trail_dyn:
            window = df.iloc[:i + 1]
            trail = engine.check_lowest_green_trail(window, state)
            if trail["trend_broken"]:
                exit_idx = i
                exit_price = float(bar["close"])
                exit_reason = "TRAIL_BROKEN_GREEN"
                break

        # --- Recharge long_up_bar / long_dn_bar (standard V3) ---
        if contracts_open < N_CONTRACTS_INITIAL + MAX_PYRAMID_LOADS:
            window = df.iloc[:i + 1]
            try:
                rec_result = engine.detect_recharge(window, state)
                if rec_result.signal in ("RECHARGE_LONG", "RECHARGE_SHORT"):
                    contracts_open += 1
                    recharge_entries.append((i, float(bar["close"]), "long_bar"))
                    continue
            except Exception:
                pass

            # --- VARIANTE D : recharge sur edge zones ---
            if recharge_edge_zones and has_edge_cols:
                edge_fire = False
                if direction == "LONG" and bar[edge_buy_col] == 1:
                    edge_fire = True
                if direction == "SHORT" and bar[edge_sell_col] == 1:
                    edge_fire = True
                if edge_fire:
                    # En profit only (regle BN : on charge dans le sens du profit)
                    in_profit = ((direction == "LONG" and bar["close"] > entry_price) or
                                 (direction == "SHORT" and bar["close"] < entry_price))
                    if in_profit:
                        contracts_open += 1
                        recharge_entries.append((i, float(bar["close"]), "edge_zone"))

    if exit_idx is None:
        exit_idx = n - 1
        exit_price = float(df.iloc[exit_idx]["close"])
        exit_reason = "END_OF_DATA"

    # --- PnL ---
    sign = 1.0 if direction == "LONG" else -1.0
    pnl_ticks_per_contract_avg = 0.0
    total_contract_units = 0

    if scaled_out:
        pnl_scaled = sign * (scaled_out_price - entry_price) / tick_size
        pnl_runner = sign * (exit_price - entry_price) / tick_size
        pnl_ticks_per_contract_avg += pnl_scaled + pnl_runner
        total_contract_units += 2
    else:
        pnl_init = sign * (exit_price - entry_price) / tick_size
        pnl_ticks_per_contract_avg += pnl_init * 2
        total_contract_units += 2

    for (rec_idx, rec_price, _src) in recharge_entries:
        pnl_rec = sign * (exit_price - rec_price) / tick_size
        pnl_ticks_per_contract_avg += pnl_rec
        total_contract_units += 1

    pnl_usd = pnl_ticks_per_contract_avg * TICK_VALUE_USD[sym]
    pnl_usd -= total_contract_units * COMMISSION_USD_PER_CONTRACT
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


def run_variant(sym: str, df: pd.DataFrame, variant_name: str,
                config: dict) -> tuple[list[TradeResult], dict]:
    """Run 1 variante sur dataframe deja charge."""
    engine = BNV3Engine(
        sym=sym, use_range_filter=False,
        swing_min_bars=config["swing_min_bars"],
        dow_min_swings=config["dow_min_swings"],
        adx_min=20.0,
        enable_mode2_range_break=config.get("enable_mode2", False),
        enable_mode3_v_reversal=config.get("enable_mode3", False),
    )
    # Mode 2 requires range_detector_v3 a etre instancie pour scanner consolidations
    if config.get("enable_mode2", False):
        try:
            from CORE.range_detector_v3 import RangeDetectorV3
            engine._range_detector = RangeDetectorV3(sym=sym)
        except ImportError:
            print(f"[WARN] range_detector_v3 indispo, Mode 2 va skip")
    state = BNV3State()
    trades: list[TradeResult] = []
    n = len(df)
    next_search_idx = 100

    while next_search_idx < n - MAX_TRADE_DURATION_MIN:
        window = df.iloc[:next_search_idx + 1]
        try:
            result = engine.detect(window, state)
        except Exception as e:
            next_search_idx += 1
            continue

        if result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
            trade = simulate_trade_v(
                df, next_search_idx, engine, state, sym,
                use_trail_dyn=config["use_trail_dyn"],
                recharge_edge_zones=config["recharge_edge_zones"],
            )
            trades.append(trade)
            next_search_idx += trade.bars_in_trade + 10
            state = BNV3State()
            state.last_setup_idx = next_search_idx - 11
        else:
            next_search_idx += 1

    if not trades:
        return trades, {"n_trades": 0, "pf": 0.0, "wr": 0.0,
                        "avg_pnl_usd": 0.0, "total_pnl_usd": 0.0,
                        "max_dd_usd": 0.0, "avg_recharges": 0.0}

    pnls = np.array([t.pnl_usd for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    wr = len(wins) / len(pnls) * 100

    # Max drawdown (equity curve)
    cum = pnls.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min())

    stats = {
        "n_trades": len(trades),
        "n_long": sum(1 for t in trades if t.direction == "LONG"),
        "n_short": sum(1 for t in trades if t.direction == "SHORT"),
        "pf": float(pf),
        "wr": float(wr),
        "avg_pnl_usd": float(pnls.mean()),
        "total_pnl_usd": float(pnls.sum()),
        "max_dd_usd": max_dd,
        "avg_recharges": float(np.mean([t.n_recharges for t in trades])),
        "avg_bars_in_trade": float(np.mean([t.bars_in_trade for t in trades])),
        "exit_reasons": {r: sum(1 for t in trades if t.exit_reason == r)
                         for r in set(t.exit_reason for t in trades)},
    }
    return trades, stats


def load_data(sym: str, months: list[tuple[int, int]]) -> pd.DataFrame:
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0"
    dfs = []
    for (year, month) in months:
        f = base / f"year={year}" / f"month={month:02d}" / "data.parquet"
        if not f.exists():
            print(f"[WARN] missing {f}")
            continue
        d = pd.read_parquet(f)
        # Normalize tz : force UTC partout (certains mois tz-naive, d'autres tz-aware)
        d["ts_event"] = pd.to_datetime(d["ts_event"], utc=True)
        dfs.append(d)
    if not dfs:
        raise RuntimeError(f"No data {sym} {months}")
    df = pd.concat(dfs, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sym", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--months", default="2026-03,2026-04,2026-05",
                        help="YYYY-MM,YYYY-MM,...")
    parser.add_argument("--out-dir", default="DATA/research")
    parser.add_argument("--only", default=None,
                        help="Comma-separated variant names to run (default: all). "
                             "Ex: --only F_mode3_vrev,H_all_modes")
    args = parser.parse_args()

    months = [tuple(map(int, m.strip().split("-"))) for m in args.months.split(",")]
    print(f"=== BN V3 VARIANTS BACKTEST {args.sym} ===")
    print(f"Months: {months}")

    # Filtrer les variantes si --only
    selected_variants = VARIANTS
    if args.only:
        only_set = set(args.only.split(","))
        selected_variants = {k: v for k, v in VARIANTS.items() if k in only_set}
        unknown = only_set - set(VARIANTS.keys())
        if unknown:
            print(f"[WARN] Unknown variants ignored: {unknown}")
        print(f"Filtered variants: {list(selected_variants.keys())}")

    df = load_data(args.sym, months)
    print(f"Loaded {len(df)} bars, range [{df['ts_event'].min()} -> {df['ts_event'].max()}]")
    print()

    all_results = {}
    all_trades = {}
    for variant_name, config in selected_variants.items():
        print(f"--- Running variant {variant_name} ---")
        print(f"    config: {config}")
        trades, stats = run_variant(args.sym, df, variant_name, config)
        all_results[variant_name] = stats
        all_trades[variant_name] = trades
        print(f"    -> n_trades={stats['n_trades']}, PF={stats['pf']:.2f}, "
              f"WR={stats['wr']:.1f}%, total_pnl=${stats['total_pnl_usd']:.0f}, "
              f"max_DD=${stats['max_dd_usd']:.0f}")
        print()

    # Tableau comparatif
    print("=" * 100)
    print(f"=== COMPARATIF {args.sym} | Periode: {months[0]} -> {months[-1]} ===")
    print("=" * 100)
    header = f"{'Variant':<14} {'N':<5} {'L/S':<10} {'PF':<7} {'WR%':<7} {'AvgPnL$':<10} {'TotPnL$':<10} {'MaxDD$':<10} {'Recharges':<10}"
    print(header)
    print("-" * 100)
    for name in VARIANTS:
        s = all_results[name]
        ls = f"{s['n_long']}/{s['n_short']}" if s['n_trades'] > 0 else "0/0"
        print(f"{name:<14} {s['n_trades']:<5} {ls:<10} "
              f"{s['pf']:<7.2f} {s['wr']:<7.1f} "
              f"${s['avg_pnl_usd']:<9.1f} ${s['total_pnl_usd']:<9.0f} "
              f"${s['max_dd_usd']:<9.0f} {s['avg_recharges']:<10.2f}")
    print("=" * 100)

    # Verdict eliminatoire Phase 1
    print()
    print("=== VERDICT ELIMINATOIRE PHASE 1 ===")
    print("Criteres : PF >= 1.3 ET n_trades >= 30 -> finaliste Phase 2 (Lopez)")
    print("Criteres : PF < 1.0 OU n_trades < 30 -> NOGO immediat")
    print("-" * 100)
    finalists = []
    for name in VARIANTS:
        s = all_results[name]
        if s["n_trades"] < 30:
            verdict = f"NOGO (n_trades={s['n_trades']} < 30)"
        elif s["pf"] < 1.0:
            verdict = f"NOGO (PF={s['pf']:.2f} < 1.0)"
        elif s["pf"] >= 1.3:
            verdict = f"FINALISTE Phase 2 (PF={s['pf']:.2f} >= 1.3)"
            finalists.append(name)
        else:
            verdict = f"BORDERLINE (1.0 <= PF={s['pf']:.2f} < 1.3)"
        print(f"  {name:<14} : {verdict}")
    print()
    if finalists:
        print(f"[NEXT] Phase 2 ml-trainer walk-forward Lopez sur : {finalists}")
    else:
        print("[NEXT] Aucun finaliste -> garder V3 actuel + pivot strategy")
    print()

    # Sauvegarde tableaux + trades CSV
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df = pd.DataFrame.from_dict(all_results, orient="index")
    summary_path = out_dir / f"bn_v3_variants_{args.sym}_summary.csv"
    summary_df.to_csv(summary_path)
    print(f"[OUT] {summary_path}")
    for name, trades in all_trades.items():
        if trades:
            trades_df = pd.DataFrame([t.__dict__ for t in trades])
            p = out_dir / f"bn_v3_variants_{args.sym}_{name}_trades.csv"
            trades_df.to_csv(p, index=False)
            print(f"[OUT] {p}")


if __name__ == "__main__":
    main()
