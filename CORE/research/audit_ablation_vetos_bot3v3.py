# -*- coding: utf-8 -*-
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from CORE.bot3_v3_continuation_engine import (
    Bot3V3Engine, Bot3V3Params, build_default_level_defs,
)

from CORE.research.rebacktest_bot3v3_mode_a_vs_b import (
    load_data, classify_session, simulate_trade,
    TradeResult, compute_metrics, stratify,
    TICK_NQ, DOLLAR_PER_TICK_NQ, SLIPPAGE_TICKS, TIMEOUT_BARS,
)

OUT_ROOT = Path("LOGS/audit_ablation_vetos_bot3v3")
OUT_ROOT.mkdir(parents=True, exist_ok=True)


def build_params(config_name):
    p = Bot3V3Params()
    if config_name == "C0_BASELINE":
        pass
    elif config_name == "C1_NO_V1_TREND_ALIGN":
        p.trend_alignment_required = False
    elif config_name == "C2_NO_V2_MIN_SLOPE":
        p.min_vwap_slope_abs = 0.0
    elif config_name == "C3_NO_V3_SLOPE_DIV":
        p.slope_divergence_veto_enabled = False
    elif config_name == "C4_NO_V4_RR_1_5":
        p.tp_fixed_ticks_nq = 38
        p.target_R = 1.5
    elif config_name == "C5_ALL_OFF_RR15":
        p.trend_alignment_required = False
        p.min_vwap_slope_abs = 0.0
        p.slope_divergence_veto_enabled = False
        p.tp_fixed_ticks_nq = 38
        p.target_R = 1.5
    else:
        raise ValueError("Unknown config: " + config_name)
    return p


def run_engine_ablation(df, symbol, params):
    tick = TICK_NQ
    eng = Bot3V3Engine(symbol=symbol,
                       level_defs=build_default_level_defs(),
                       params=params)

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    ts_arr = df["ts_event"].astype(str).values
    ts_dt_arr = df["ts_event_dt"].values
    regime_arr = df["regime_mode"].fillna("UNKNOWN").values
    n_bars = len(df)

    entries = []
    t0 = time.time()
    for i in range(n_bars):
        row = df.iloc[i].to_dict()
        bar_ts_iso = str(row.get("ts_event"))
        bar_day = str(row.get("session_date"))
        decision = eng.process_bar(row, bar_ts_iso, bar_day)
        if decision is not None:
            entries.append((i, decision))
    elapsed = time.time() - t0
    print("    " + str(len(entries)) + " entries in " + ("%.1f" % elapsed) + "s")

    results = []
    for idx, dec in entries:
        sl_price = dec.sl_price
        tp_price = dec.tp_price
        sl_ticks = dec.sl_ticks
        if params.sl_tp_fixed_mode_nq:
            sl_mode = "moteur_fixed_nq"
        elif dec.swing_used:
            sl_mode = "moteur_swing"
        else:
            sl_mode = "moteur_fallback"

        exit_idx, cause, exit_price, pnl_ticks, mae, mfe, bars = simulate_trade(
            highs, lows, closes, idx, dec.side, dec.entry_close,
            sl_price, tp_price, sl_ticks, tick, n_bars,
        )

        pnl_ticks_net = pnl_ticks - SLIPPAGE_TICKS
        pnl_R = pnl_ticks_net / sl_ticks if sl_ticks > 0 else 0
        pnl_usd = pnl_ticks_net * DOLLAR_PER_TICK_NQ

        ts_dt = pd.Timestamp(ts_dt_arr[idx])
        session = classify_session(ts_dt)
        regime = str(regime_arr[idx])

        results.append(TradeResult(
            mode="A", symbol=symbol, side=dec.side,
            level_name=dec.level_name, session=session, regime_mode=regime,
            entry_bar_idx=idx, entry_ts=ts_arr[idx],
            entry_price=dec.entry_close, sl_price=sl_price, tp_price=tp_price,
            sl_ticks=sl_ticks, sl_mode=sl_mode,
            exit_bar_idx=exit_idx, exit_ts=ts_arr[exit_idx],
            exit_price=exit_price, exit_cause=cause,
            pnl_ticks=pnl_ticks, pnl_ticks_net=pnl_ticks_net,
            pnl_R=pnl_R, pnl_usd=pnl_usd,
            mae_ticks=mae, mfe_ticks=mfe, bars_held=bars,
        ))
    return results


CONFIGS_ABLATION = [
    "C0_BASELINE",
    "C1_NO_V1_TREND_ALIGN",
    "C2_NO_V2_MIN_SLOPE",
    "C3_NO_V3_SLOPE_DIV",
    "C4_NO_V4_RR_1_5",
    "C5_ALL_OFF_RR15",
]


def main():
    print("=" * 80)
    print("AUDIT ABLATION VETOS Bot 3 v3 - NQ Mode A 5 mois")
    print("=" * 80)

    print()
    print("=== Loading NQ (NQ.c.0) ===")
    df = load_data("NQ.c.0")
    n_days = df["session_date"].nunique()
    print("  Shape: " + str(df.shape) + ", days: " + str(n_days))

    all_trades = {}
    summary = {}

    for cfg in CONFIGS_ABLATION:
        print()
        print("--- " + cfg + " ---")
        params = build_params(cfg)
        print("  trend_align=" + str(params.trend_alignment_required)
              + " min_slope_abs=" + str(params.min_vwap_slope_abs)
              + " slope_div_veto=" + str(params.slope_divergence_veto_enabled)
              + " tp_fixed=" + str(params.tp_fixed_ticks_nq))
        trades = run_engine_ablation(df, "NQ", params)
        all_trades[cfg] = trades

        global_m = compute_metrics(trades)
        per_session = stratify(trades, "session")
        per_regime = stratify(trades, "regime_mode")
        per_side = stratify(trades, "side")

        summary[cfg] = {
            "global": global_m,
            "by_session": per_session,
            "by_regime": per_regime,
            "by_side": per_side,
        }
        print("  -> n=" + str(global_m["n"]) + ", WR=" + str(global_m["WR"])
              + "%, PF=" + str(global_m["PF"]) + ", EV_ticks="
              + str(global_m["EV_ticks"]) + ", sum_USD="
              + str(global_m["sum_pnl_usd"]))
        long_count = sum(1 for t in trades if t.side == "LONG")
        short_count = sum(1 for t in trades if t.side == "SHORT")
        print("  -> LONG=" + str(long_count) + ", SHORT=" + str(short_count))

    print()
    print("=" * 80)
    print("CONTRIBUTION MARGINALE PAR VETO (Ci vs C0 BASELINE)")
    print("=" * 80)
    baseline = summary["C0_BASELINE"]["global"]
    contrib_table = []
    for cfg in CONFIGS_ABLATION[1:]:
        s = summary[cfg]["global"]
        contrib = {
            "config": cfg,
            "n_delta": s["n"] - baseline["n"],
            "n_ratio": round((s["n"] / baseline["n"]), 3) if baseline["n"] > 0 else 0,
            "PF_delta": round(s["PF"] - baseline["PF"], 3),
            "EV_ticks_delta": round(s["EV_ticks"] - baseline["EV_ticks"], 3),
            "WR_delta": round(s["WR"] - baseline["WR"], 2),
            "sum_USD_delta": round(s["sum_pnl_usd"] - baseline["sum_pnl_usd"], 2),
            "MaxDD_delta": round(s["max_dd_usd"] - baseline["max_dd_usd"], 2),
        }
        if contrib["PF_delta"] > 0 and contrib["EV_ticks_delta"] > 0:
            contrib["verdict"] = "VIRER"
        elif contrib["PF_delta"] < 0 and contrib["EV_ticks_delta"] < 0:
            contrib["verdict"] = "GARDER"
        else:
            contrib["verdict"] = "NEUTRE"
        contrib_table.append(contrib)
        print()
        print(cfg + ":")
        print("  delta_n=" + str(contrib["n_delta"])
              + " delta_PF=" + str(contrib["PF_delta"])
              + " delta_EV=" + str(contrib["EV_ticks_delta"])
              + " delta_USD=" + str(contrib["sum_USD_delta"]))
        print("  -> " + contrib["verdict"])

    print()
    print("=== Saving outputs ===")
    all_trade_rows = []
    for cfg, trades in all_trades.items():
        for t in trades:
            d = asdict(t)
            d["config"] = cfg
            all_trade_rows.append(d)
    if all_trade_rows:
        df_all = pd.DataFrame(all_trade_rows)
        csv_path = OUT_ROOT / "trades_all.csv"
        df_all.to_csv(csv_path, index=False)
        print("  CSV: " + str(csv_path) + " (" + str(len(df_all)) + " rows)")

    def convert(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, dict):
            return {k: convert(v) for k, v in o.items()}
        if isinstance(o, list):
            return [convert(x) for x in o]
        return o

    out_obj = {
        "configs": CONFIGS_ABLATION,
        "summary": convert(summary),
        "contrib_marginale": contrib_table,
        "meta": {
            "symbol": "NQ",
            "months": "2026-01_2026-05",
            "n_days": int(n_days),
            "mode": "A_cluster_OR_long_bar",
            "ticks_slip": SLIPPAGE_TICKS,
            "timeout_bars": TIMEOUT_BARS,
        },
    }
    json_path = OUT_ROOT / "summary.json"
    with open(json_path, "w") as f:
        json.dump(out_obj, f, indent=2, default=str)
    print("  JSON: " + str(json_path))
    print()
    print("DONE.")
    return summary, contrib_table


if __name__ == "__main__":
    main()
