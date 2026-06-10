"""backtest_levels_strict.py — Backtest 49 levels + 30 combos avec methodologie STRICTE.

Methodologie corrigee (anti DATA_MINING_TRAP) :
  - TP = 24t / SL = 12t path-dependent (pessimist si TP+SL meme bar)
  - Costs : ES 2t / NQ 3t round-trip
  - Walk-forward 12 folds chronologiques
  - PSR Bailey 2012 (Pearson kurtosis)
  - Sidak threshold pour 80 tests (49 simples + 30 combos + 2 syms = 158)
  - Cooldown 45b pour eviter chevauchement
  - Proximity stricte 0.02% (5t ES, 10t NQ) au lieu de 0.05%
  - Min n = 30 (Lopez n>=100 ideal mais on tolere 30 pour combos rares)

Verdict GO :
  - PSR >= Sidak threshold
  - WF 12 folds : >=8 folds avec PF >= 1.0
  - PF >= 1.3
  - EV/trade > 0 apres costs
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}
TP_TICKS = 24
SL_TICKS = 12
FWD_BARS = 30
COOLDOWN = 45
PROXIMITY_PCT = 0.02   # plus strict que 0.05% (anti bruit)
MIN_N = 30


CANDIDATES = [
    # LONG (bounce sur SUPPORT)
    {"name": "PDL",                "dist_col": "dist_pdl_pct",                  "side": "LONG"},
    {"name": "PVAL",               "dist_col": "dist_prev_val_pct",             "side": "LONG"},
    {"name": "PVPOC_below",        "dist_col": "dist_prev_vpoc_pct",            "side": "LONG"},
    {"name": "PVWAP_SD1D",         "dist_col": "dist_pvwap_sd1d_pct",           "side": "LONG"},
    {"name": "IB_LOW",             "dist_col": "dist_ib_low_pct",               "side": "LONG"},
    {"name": "SWING_LOW",          "dist_col": "dist_last_swing_low_pct",       "side": "LONG"},
    {"name": "CUR_VAL",            "dist_col": "dist_cur_val_pct",              "side": "LONG"},
    {"name": "ASIA_LOW",           "dist_col": "dist_asia_low_pct",             "side": "LONG"},
    {"name": "LONDON_LOW",         "dist_col": "dist_london_low_pct",           "side": "LONG"},
    {"name": "CASH_LOW",           "dist_col": "dist_cash_low_pct",             "side": "LONG"},
    {"name": "OVN_LOW",            "dist_col": "dist_ovn_low_pct",              "side": "LONG"},
    {"name": "MQ_PUT",             "dist_col": "dist_mq_put_pct",               "side": "LONG"},
    {"name": "MQ_PUT_0DTE",        "dist_col": "dist_mq_put_0dte_pct",          "side": "LONG"},
    {"name": "MQ_HVL",             "dist_col": "dist_mq_hvl_pct",               "side": "LONG"},
    {"name": "GEX_DN",             "dist_col": "dist_gex_nearest_dn_pct",       "side": "LONG"},
    {"name": "VWAP_W",             "dist_col": "dist_vwap_w_pct",               "side": "LONG"},
    {"name": "VWAP_W_SD1D",        "dist_col": "dist_vwap_w_sd1d_pct",          "side": "LONG"},
    {"name": "VWAP_W_SD2D",        "dist_col": "dist_vwap_w_sd2d_pct",          "side": "LONG"},
    {"name": "VWAP_D_SD1D",        "dist_col": "dist_vwap_d_sd1d_pct",          "side": "LONG"},
    {"name": "VWAP_D_SD2D",        "dist_col": "dist_vwap_d_sd2d_pct",          "side": "LONG"},
    {"name": "LONG_UP_zone",       "dist_col": "dist_long_up_nearest_pct",      "side": "LONG"},
    {"name": "COLOR_UP_zone",      "dist_col": "dist_color_up_nearest_pct",     "side": "LONG"},
    {"name": "EDGE_BUY",           "dist_col": "dist_edge_buy_nearest_pct",     "side": "LONG"},
    {"name": "DELTA_DIV_BUY",      "dist_col": "dist_delta_div_buy_nearest_pct","side": "LONG"},
    {"name": "OPEN_830",           "dist_col": "dist_open_830_pct",             "side": "LONG"},
    {"name": "OPEN_930",           "dist_col": "dist_open_930_pct",             "side": "LONG"},
    {"name": "NAKED_POC",          "dist_col": "dist_naked_poc_nearest_pct",    "side": "LONG"},
    {"name": "SINGLE_PRINT",       "dist_col": "dist_single_print_nearest_pct", "side": "LONG"},
    {"name": "TRAPPED_SELLERS",    "dist_col": "dist_trapped_sellers_nearest_pct","side": "LONG"},
    # SHORT (rejet sur RESISTANCE)
    {"name": "PDH",                "dist_col": "dist_pdh_pct",                  "side": "SHORT"},
    {"name": "PVAH",               "dist_col": "dist_prev_vah_pct",             "side": "SHORT"},
    {"name": "PVPOC_above",        "dist_col": "dist_prev_vpoc_pct",            "side": "SHORT"},
    {"name": "PVWAP_SD1U",         "dist_col": "dist_pvwap_sd1u_pct",           "side": "SHORT"},
    {"name": "IB_HIGH",            "dist_col": "dist_ib_high_pct",              "side": "SHORT"},
    {"name": "SWING_HIGH",         "dist_col": "dist_last_swing_high_pct",      "side": "SHORT"},
    {"name": "CUR_VAH",            "dist_col": "dist_cur_vah_pct",              "side": "SHORT"},
    {"name": "ASIA_HIGH",          "dist_col": "dist_asia_high_pct",            "side": "SHORT"},
    {"name": "LONDON_HIGH",        "dist_col": "dist_london_high_pct",          "side": "SHORT"},
    {"name": "CASH_HIGH",          "dist_col": "dist_cash_high_pct",            "side": "SHORT"},
    {"name": "OVN_HIGH",           "dist_col": "dist_ovn_high_pct",             "side": "SHORT"},
    {"name": "MQ_CALL",            "dist_col": "dist_mq_call_pct",              "side": "SHORT"},
    {"name": "MQ_CALL_0DTE",       "dist_col": "dist_mq_call_0dte_pct",         "side": "SHORT"},
    {"name": "MQ_HVL_short",       "dist_col": "dist_mq_hvl_pct",               "side": "SHORT"},
    {"name": "GEX_UP",             "dist_col": "dist_gex_nearest_up_pct",       "side": "SHORT"},
    {"name": "VWAP_W_SD1U",        "dist_col": "dist_vwap_w_sd1u_pct",          "side": "SHORT"},
    {"name": "VWAP_W_SD2U",        "dist_col": "dist_vwap_w_sd2u_pct",          "side": "SHORT"},
    {"name": "VWAP_D_SD1U",        "dist_col": "dist_vwap_d_sd1u_pct",          "side": "SHORT"},
    {"name": "VWAP_D_SD2U",        "dist_col": "dist_vwap_d_sd2u_pct",          "side": "SHORT"},
    {"name": "LONG_DN_zone",       "dist_col": "dist_long_dn_nearest_pct",      "side": "SHORT"},
    {"name": "COLOR_DN_zone",      "dist_col": "dist_color_dn_nearest_pct",     "side": "SHORT"},
    {"name": "EDGE_SELL",          "dist_col": "dist_edge_sell_nearest_pct",    "side": "SHORT"},
    {"name": "DELTA_DIV_SELL",     "dist_col": "dist_delta_div_sell_nearest_pct","side": "SHORT"},
    {"name": "TRAPPED_BUYERS",     "dist_col": "dist_trapped_buyers_nearest_pct","side": "SHORT"},
]

COMBOS = [
    {"name": "PDL_x_IB_LOW",        "side": "LONG", "cols": ["dist_pdl_pct", "dist_ib_low_pct"]},
    {"name": "PVAL_x_SWING_LOW",    "side": "LONG", "cols": ["dist_prev_val_pct", "dist_last_swing_low_pct"]},
    {"name": "PVPOC_x_IB_LOW",      "side": "LONG", "cols": ["dist_prev_vpoc_pct", "dist_ib_low_pct"]},
    {"name": "MQ_PUT_x_IB_LOW",     "side": "LONG", "cols": ["dist_mq_put_pct", "dist_ib_low_pct"]},
    {"name": "MQ_PUT_0DTE_x_IB_LOW","side": "LONG", "cols": ["dist_mq_put_0dte_pct", "dist_ib_low_pct"]},
    {"name": "MQ_HVL_x_LONDON_LOW", "side": "LONG", "cols": ["dist_mq_hvl_pct", "dist_london_low_pct"]},
    {"name": "MQ_HVL_x_SWING_LOW",  "side": "LONG", "cols": ["dist_mq_hvl_pct", "dist_last_swing_low_pct"]},
    {"name": "GEX_DN_x_IB_LOW",     "side": "LONG", "cols": ["dist_gex_nearest_dn_pct", "dist_ib_low_pct"]},
    {"name": "LONG_UP_x_COLOR_UP",  "side": "LONG", "cols": ["dist_long_up_nearest_pct", "dist_color_up_nearest_pct"]},
    {"name": "LONG_UP_x_SWING_LOW", "side": "LONG", "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"]},
    {"name": "COLOR_UP_x_PVAL",     "side": "LONG", "cols": ["dist_color_up_nearest_pct", "dist_prev_val_pct"]},
    {"name": "EDGE_BUY_x_DELTA_BUY","side": "LONG", "cols": ["dist_edge_buy_nearest_pct", "dist_delta_div_buy_nearest_pct"]},
    {"name": "SINGLE_x_IB_LOW",     "side": "LONG", "cols": ["dist_single_print_nearest_pct", "dist_ib_low_pct"]},
    {"name": "TRAPPED_S_x_IB_LOW",  "side": "LONG", "cols": ["dist_trapped_sellers_nearest_pct", "dist_ib_low_pct"]},
    {"name": "VWAP_W_SD1D_x_IB_LOW","side": "LONG", "cols": ["dist_vwap_w_sd1d_pct", "dist_ib_low_pct"]},
    {"name": "PDH_x_IB_HIGH",       "side": "SHORT", "cols": ["dist_pdh_pct", "dist_ib_high_pct"]},
    {"name": "PVAH_x_SWING_HIGH",   "side": "SHORT", "cols": ["dist_prev_vah_pct", "dist_last_swing_high_pct"]},
    {"name": "PVPOC_x_IB_HIGH",     "side": "SHORT", "cols": ["dist_prev_vpoc_pct", "dist_ib_high_pct"]},
    {"name": "MQ_CALL_x_IB_HIGH",   "side": "SHORT", "cols": ["dist_mq_call_pct", "dist_ib_high_pct"]},
    {"name": "MQ_CALL_0DTE_x_IB_H", "side": "SHORT", "cols": ["dist_mq_call_0dte_pct", "dist_ib_high_pct"]},
    {"name": "MQ_HVL_x_LONDON_H",   "side": "SHORT", "cols": ["dist_mq_hvl_pct", "dist_london_high_pct"]},
    {"name": "MQ_HVL_x_SWING_H",    "side": "SHORT", "cols": ["dist_mq_hvl_pct", "dist_last_swing_high_pct"]},
    {"name": "GEX_UP_x_IB_HIGH",    "side": "SHORT", "cols": ["dist_gex_nearest_up_pct", "dist_ib_high_pct"]},
    {"name": "LONG_DN_x_COLOR_DN",  "side": "SHORT", "cols": ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"]},
    {"name": "LONG_DN_x_SWING_H",   "side": "SHORT", "cols": ["dist_long_dn_nearest_pct", "dist_last_swing_high_pct"]},
    {"name": "COLOR_DN_x_PVAH",     "side": "SHORT", "cols": ["dist_color_dn_nearest_pct", "dist_prev_vah_pct"]},
    {"name": "EDGE_SELL_x_DELTA_S", "side": "SHORT", "cols": ["dist_edge_sell_nearest_pct", "dist_delta_div_sell_nearest_pct"]},
    {"name": "SINGLE_x_IB_HIGH",    "side": "SHORT", "cols": ["dist_single_print_nearest_pct", "dist_ib_high_pct"]},
    {"name": "TRAPPED_B_x_IB_H",    "side": "SHORT", "cols": ["dist_trapped_buyers_nearest_pct", "dist_ib_high_pct"]},
    {"name": "VWAP_W_SD1U_x_IB_H",  "side": "SHORT", "cols": ["dist_vwap_w_sd1u_pct", "dist_ib_high_pct"]},
]

N_TESTS_GLOBAL = (len(CANDIDATES) + len(COMBOS)) * 2  # x 2 syms


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def simulate_trades_at_indices(df, signal_indices, direction, sym):
    n = len(df)
    tick = TICK_SIZE[sym]
    cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    trades = []
    last = -COOLDOWN
    for i in signal_indices:
        if i - last < COOLDOWN:
            continue
        if i + FWD_BARS >= n:
            continue
        entry = closes[i]
        if direction == "LONG":
            tp = entry + TP_TICKS * tick
            sl = entry - SL_TICKS * tick
        else:
            tp = entry - TP_TICKS * tick
            sl = entry + SL_TICKS * tick
        exit_reason = "TIMEOUT"
        pnl = 0.0
        for k in range(i + 1, min(i + FWD_BARS + 1, n)):
            bh = highs[k]; bl = lows[k]
            if direction == "LONG":
                sl_hit = bl <= sl
                tp_hit = bh >= tp
            else:
                sl_hit = bh >= sl
                tp_hit = bl <= tp
            if sl_hit and tp_hit:
                exit_reason = "SL_PESS"; pnl = -float(SL_TICKS) - cost; break
            if sl_hit:
                exit_reason = "SL"; pnl = -float(SL_TICKS) - cost; break
            if tp_hit:
                exit_reason = "TP"; pnl = float(TP_TICKS) - cost; break
        else:
            final = closes[min(i + FWD_BARS, n - 1)]
            pnl = ((final - entry) if direction == "LONG" else (entry - final)) / tick - cost
        trades.append({"entry_idx": i, "exit": exit_reason, "pnl_ticks": float(pnl)})
        last = i
    return trades


def metrics_full(trades, sym):
    if not trades:
        return None
    pnls = np.array([t["pnl_ticks"] for t in trades])
    n = len(pnls)
    wr = (pnls > 0).mean()
    sw = pnls[pnls > 0].sum()
    sl_sum = abs(pnls[pnls < 0].sum())
    pf = sw / sl_sum if sl_sum > 0 else float("inf")
    ev = pnls.mean()
    if pnls.std() > 0 and n > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(pnls); kt = kurtosis(pnls, fisher=False)
        sr = pnls.mean() / pnls.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n - 1) / denom))
    else:
        psr = 0.5
    # Walk-forward 12 folds
    cuts = np.linspace(0, n, 13, dtype=int)
    pfs = []
    for k in range(12):
        sub = pnls[cuts[k]:cuts[k + 1]]
        if len(sub) < 2:
            pfs.append(0)
            continue
        sw_f = sub[sub > 0].sum()
        sl_f = abs(sub[sub < 0].sum())
        pfs.append(sw_f / sl_f if sl_f > 0 else 99.0)
    pf_min = float(min(pfs))
    pf_med = float(np.median(pfs))
    n_pos = sum(1 for p in pfs if p >= 1.0)
    return {"n": n, "wr": wr, "pf": pf, "ev": ev, "psr": psr,
            "pf_min": pf_min, "pf_med": pf_med, "n_pos_folds": n_pos}


def evaluate_simple(df, sym, candidate):
    name = candidate["name"]
    dist_col = candidate["dist_col"]
    side = candidate["side"]
    if dist_col not in df.columns:
        return {"name": name, "side": side, "error": f"col absent: {dist_col}"}
    near = df[dist_col].astype(float).abs() <= PROXIMITY_PCT
    indices = np.where(near)[0]
    if len(indices) < MIN_N:
        return {"name": name, "side": side, "n_signals": len(indices), "error": "n_signals<min"}
    trades = simulate_trades_at_indices(df, indices, side, sym)
    if len(trades) < MIN_N:
        return {"name": name, "side": side, "n_signals": len(indices),
                "n_trades": len(trades), "error": "n_trades<min after cooldown"}
    m = metrics_full(trades, sym)
    return {"name": name, "side": side, "n_signals": len(indices), **m}


def evaluate_combo(df, sym, combo):
    name = combo["name"]
    cols = combo["cols"]
    side = combo["side"]
    for c in cols:
        if c not in df.columns:
            return {"name": name, "side": side, "error": f"col absent: {c}"}
    masks = [df[c].astype(float).abs() <= PROXIMITY_PCT for c in cols]
    near = masks[0]
    for m in masks[1:]:
        near = near & m
    indices = np.where(near)[0]
    if len(indices) < MIN_N:
        return {"name": name, "side": side, "n_signals": len(indices), "error": "n_signals<min"}
    trades = simulate_trades_at_indices(df, indices, side, sym)
    if len(trades) < MIN_N:
        return {"name": name, "side": side, "n_signals": len(indices),
                "n_trades": len(trades), "error": "n_trades<min after cooldown"}
    m = metrics_full(trades, sym)
    return {"name": name, "side": side, "n_signals": len(indices), **m}


def report(results, label, sym, psr_threshold):
    print(f"\n=== {label} ({sym}) ===")
    valid = [r for r in results if "error" not in r]
    err = [r for r in results if "error" in r]
    valid.sort(key=lambda r: -(r.get("ev", -999)))
    print(f"\n{'Candidat':<23} {'Side':<6} {'nSig':>6} {'nTr':>5} {'WR':>6} {'PF':>6} {'EV':>7} {'PSR':>6} {'WFmin':>6} {'WFmed':>6} {'WF+':>4} {'Verdict':>8}")
    print("-" * 110)
    n_go = 0
    for r in valid:
        verdict = "NOGO"
        if (r["psr"] >= psr_threshold and r["n_pos_folds"] >= 8 and
            r["pf"] >= 1.3 and r["ev"] > 0):
            verdict = "GO"; n_go += 1
        elif r["pf"] >= 1.0 and r["ev"] > -0.5 and r["n_pos_folds"] >= 6:
            verdict = "MARGINAL"
        pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
        print(f"  {r['name']:<21} {r['side']:<6} {r['n_signals']:>6} {r['n']:>5} "
              f"{r['wr']*100:>5.1f}% {pf_str:>6} {r['ev']:>+6.2f} {r['psr']:>5.3f} "
              f"{r['pf_min']:>5.2f} {r['pf_med']:>5.2f} {r['n_pos_folds']:>3}/12 {verdict:>8}")
    print(f"\nN GO : {n_go}/{len(valid)} (Sidak threshold n={N_TESTS_GLOBAL} : PSR >= {psr_threshold:.4f})")
    if err:
        print(f"\nN errors : {len(err)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()

    sym = args.symbol
    psr_th = 1 - (1 - (1 - 0.05)**(1/N_TESTS_GLOBAL))
    print(f"\n=== BACKTEST LEVELS STRICT — {sym} ({args.months} mois) ===")
    print(f"=== TP={TP_TICKS}t SL={SL_TICKS}t fwd={FWD_BARS}b cooldown={COOLDOWN}b ===")
    print(f"=== Proximity {PROXIMITY_PCT}%, min n={MIN_N}, costs {COSTS_TICKS[sym]}t round-trip ===")
    print(f"=== Sidak threshold (n_tests={N_TESTS_GLOBAL}) : PSR >= {psr_th:.4f} ===")
    df = load_v4(sym, args.months)
    if df.empty:
        print("No data"); return
    print(f"  Loaded {len(df)} bars")

    res_simple = [evaluate_simple(df, sym, c) for c in CANDIDATES]
    report(res_simple, "NIVEAUX SIMPLES", sym, psr_th)

    res_combo = [evaluate_combo(df, sym, c) for c in COMBOS]
    report(res_combo, "COMBINAISONS", sym, psr_th)


if __name__ == "__main__":
    main()
