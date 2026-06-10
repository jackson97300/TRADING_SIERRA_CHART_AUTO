"""boost_marginal_combos.py — Test features additionnelles pour booster combos MARGINAL -> GO.

Combos MARGINAL identifies (verdict 09/05) :
  - LONG_UP_x_SWING_LOW    LONG  : EV ES +2.56 / NQ +1.78
  - PVAL_x_SWING_LOW       LONG  : EV ES +5.45 / NQ +5.12 (n petit)
  - COLOR_UP_x_PVAL        LONG  : EV ES +6.07 / NQ +2.67 (n petit)
  - PVAH_x_SWING_HIGH      SHORT : EV ES +2.61 / NQ +1.84

Pour chaque combo, on teste l'ajout d'une 3eme feature (filter/condition).
Si combo + feature_X ameliore EV, WF, PSR -> candidat boost.

Critere GO :
  - EV >= +3t apres costs
  - PF >= 1.4
  - WF folds positifs >= 10/12
  - PSR >= 0.95 (Sidak relax pour research)
  - n >= 30 trades

Methodologie stricte conservee : TP=24t, SL=12t, costs, path-dependent.
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
PROXIMITY_PCT = 0.02

# Combos MARGINAL a booster
MARGINAL_COMBOS = [
    {"name": "LONG_UP_x_SWING_LOW",  "side": "LONG",
     "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"]},
    {"name": "PVAL_x_SWING_LOW",     "side": "LONG",
     "cols": ["dist_prev_val_pct", "dist_last_swing_low_pct"]},
    {"name": "COLOR_UP_x_PVAL",      "side": "LONG",
     "cols": ["dist_color_up_nearest_pct", "dist_prev_val_pct"]},
    {"name": "PVAH_x_SWING_HIGH",    "side": "SHORT",
     "cols": ["dist_prev_vah_pct", "dist_last_swing_high_pct"]},
]

# Features additionnelles a tester (filter/condition)
# Format : (name, col, op, threshold, applies_to_side)
# applies_to_side = "BOTH" / "LONG" / "SHORT"
ADD_FEATURES = [
    # CVD regime / bias
    {"name": "cvd_bull",        "col": "cvd_5d_rolling_ffd",      "op": ">", "thr": 50,    "side": "LONG"},
    {"name": "cvd_bear",        "col": "cvd_5d_rolling_ffd",      "op": "<", "thr": -50,   "side": "SHORT"},
    # Aggressor imbalance
    {"name": "aggr_buy",        "col": "aggressor_imbalance",     "op": ">", "thr": 0.3,   "side": "LONG"},
    {"name": "aggr_sell",       "col": "aggressor_imbalance",     "op": "<", "thr": -0.3,  "side": "SHORT"},
    # Range position (LONG bas, SHORT haut)
    {"name": "range_low",       "col": "position_in_range",        "op": "<", "thr": 0.3,   "side": "LONG"},
    {"name": "range_high",      "col": "position_in_range",        "op": ">", "thr": 0.7,   "side": "SHORT"},
    # Trapped traders
    {"name": "trapped_sell",    "col": "bn_trapped_sellers_raw",  "op": ">=", "thr": 1,    "side": "LONG"},
    {"name": "trapped_buy",     "col": "bn_trapped_buyers_raw",   "op": ">=", "thr": 1,    "side": "SHORT"},
    # Color directionnel (sequence pre-bar)
    {"name": "color_up_active", "col": "n_color_up_zones_active", "op": ">=", "thr": 2,    "side": "LONG"},
    {"name": "color_dn_active", "col": "n_color_dn_zones_active", "op": ">=", "thr": 2,    "side": "SHORT"},
    # Long bar fire (impulsion BN)
    {"name": "long_up_recent",  "col": "long_up_bar",              "op": ">", "thr": 0,    "side": "LONG"},
    {"name": "long_dn_recent",  "col": "long_dn_bar",              "op": ">", "thr": 0,    "side": "SHORT"},
    # Edge buy/sell
    {"name": "edge_buy_active", "col": "bar_edge_buy_zone_size",  "op": ">=", "thr": 1,    "side": "LONG"},
    {"name": "edge_sell_active","col": "bar_edge_sell_zone_size", "op": ">=", "thr": 1,    "side": "SHORT"},
    # Volatility (ATR vs avg)
    {"name": "vol_high",        "col": "atr_normalized",          "op": ">", "thr": 1.0,   "side": "BOTH"},
    {"name": "vol_low",         "col": "atr_normalized",          "op": "<", "thr": 1.0,   "side": "BOTH"},
    # Sessions (RTH only filter via cash session bool)
    {"name": "rth_only",        "col": "is_cash_session",         "op": "==", "thr": 1,    "side": "BOTH"},
    # MQ gamma : pas de mur Call proche pour LONG (>0.10% safe)
    {"name": "no_mq_call_near", "col": "dist_mq_call_pct",        "op": ">", "thr": 0.10,  "side": "LONG"},
    {"name": "no_mq_put_near",  "col": "dist_mq_put_pct",         "op": "<", "thr": -0.10, "side": "SHORT"},
    # Delta div confirm
    {"name": "delta_div_buy",   "col": "delta_div_buy",           "op": ">", "thr": 0,    "side": "LONG"},
    {"name": "delta_div_sell",  "col": "delta_div_sell",          "op": ">", "thr": 0,    "side": "SHORT"},
    # PVPOC position (LONG : prix sous PVPOC = value zone bas)
    {"name": "below_pvpoc",     "col": "dist_prev_vpoc_pct",       "op": "<", "thr": -0.05, "side": "LONG"},
    {"name": "above_pvpoc",     "col": "dist_prev_vpoc_pct",       "op": ">", "thr": 0.05,  "side": "SHORT"},
    # 1d_min/max room
    {"name": "room_1dmin",      "col": "dist_1d_min_ticks_pct",   "op": "<", "thr": -0.30, "side": "SHORT"},
    {"name": "room_1dmax",      "col": "dist_1d_max_ticks_pct",   "op": ">", "thr": 0.30,  "side": "LONG"},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def apply_filter(df, feature):
    col = feature["col"]
    op = feature["op"]
    thr = feature["thr"]
    if col not in df.columns:
        return None
    s = df[col].astype(float)
    if op == ">":   return s > thr
    if op == "<":   return s < thr
    if op == ">=":  return s >= thr
    if op == "<=":  return s <= thr
    if op == "==":  return s == thr
    return None


def simulate_trade_at(df, i, direction, sym):
    n = len(df)
    if i + FWD_BARS >= n:
        return None
    tick = TICK_SIZE[sym]; cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    entry = closes[i]
    if direction == "LONG":
        tp = entry + TP_TICKS * tick; sl = entry - SL_TICKS * tick
    else:
        tp = entry - TP_TICKS * tick; sl = entry + SL_TICKS * tick
    for k in range(i + 1, min(i + FWD_BARS + 1, n)):
        bh = highs[k]; bl = lows[k]
        if direction == "LONG":
            sl_hit = bl <= sl; tp_hit = bh >= tp
        else:
            sl_hit = bh >= sl; tp_hit = bl <= tp
        if sl_hit and tp_hit: return -float(SL_TICKS) - cost
        if sl_hit:            return -float(SL_TICKS) - cost
        if tp_hit:            return float(TP_TICKS) - cost
    final = closes[min(i + FWD_BARS, n - 1)]
    return float(((final - entry) if direction == "LONG" else (entry - final)) / tick - cost)


def evaluate_with_filter(df, sym, combo, add_feature=None):
    """Evaluate combo seul OU combo + filter additionnel."""
    cols = combo["cols"]
    side = combo["side"]
    masks = []
    for c in cols:
        if c not in df.columns:
            return None
        masks.append(df[c].astype(float).abs() <= PROXIMITY_PCT)
    near = masks[0]
    for m in masks[1:]:
        near = near & m
    if add_feature:
        f_mask = apply_filter(df, add_feature)
        if f_mask is None:
            return None
        near = near & f_mask
    indices = np.where(near)[0]
    n = len(df)
    last = -COOLDOWN
    pnls = []
    for i in indices:
        if i - last < COOLDOWN:
            continue
        if i + FWD_BARS >= n:
            continue
        pnl = simulate_trade_at(df, i, side, sym)
        if pnl is None:
            continue
        pnls.append(pnl); last = i
    if len(pnls) < 30:
        return {"n": len(pnls), "ev": 0, "pf": 0, "wr": 0, "psr": 0, "pos_folds": 0}
    arr = np.array(pnls)
    n_t = len(arr)
    wr = (arr > 0).mean()
    sw = arr[arr > 0].sum(); sl = abs(arr[arr < 0].sum())
    pf = sw / sl if sl > 0 else float("inf")
    ev = arr.mean()
    if arr.std() > 0 and n_t > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(arr); kt = kurtosis(arr, fisher=False)
        sr = arr.mean() / arr.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n_t - 1) / denom))
    else:
        psr = 0.5
    cuts = np.linspace(0, n_t, 13, dtype=int)
    pos_folds = 0
    for k in range(12):
        sub = arr[cuts[k]:cuts[k + 1]]
        if len(sub) >= 1 and sub.sum() >= 0:
            pos_folds += 1
    return {"n": n_t, "ev": float(ev), "pf": float(pf), "wr": float(wr),
            "psr": float(psr), "pos_folds": pos_folds}


def is_go(m):
    return m and m["n"] >= 30 and m["ev"] >= 3.0 and m["pf"] >= 1.4 and \
           m["pos_folds"] >= 10 and m["psr"] >= 0.95


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    sym = args.symbol
    df = load_v4(sym, args.months)
    print(f"[{sym}] Loaded {len(df)} bars\n")

    # Audit features disponibles
    avail = []
    missing = []
    for f in ADD_FEATURES:
        if f["col"] in df.columns:
            avail.append(f["name"])
        else:
            missing.append(f["name"] + f" (col={f['col']})")
    print(f"  Features disponibles : {len(avail)}/{len(ADD_FEATURES)}")
    if missing:
        print(f"  Features absentes : {missing[:5]}{'...' if len(missing)>5 else ''}")

    print("\n" + "=" * 100)
    for combo in MARGINAL_COMBOS:
        print(f"\n=== {combo['name']} ({combo['side']}) — {sym} ===")
        # Baseline (combo seul)
        base = evaluate_with_filter(df, sym, combo)
        if base is None or base.get("n", 0) < 30:
            print(f"  BASELINE : sample insuffisant (n={base.get('n', 0) if base else 0})")
            continue
        base_ev = base["ev"]
        base_n = base["n"]
        print(f"  BASELINE seul : n={base_n}, EV={base_ev:+.2f}t, PF={base['pf']:.2f}, "
              f"WF={base['pos_folds']}/12, PSR={base['psr']:.3f} -> {'GO' if is_go(base) else 'MARG'}")

        # Test chaque feature additionnelle compatible
        results = []
        for feat in ADD_FEATURES:
            if feat["side"] not in ("BOTH", combo["side"]):
                continue
            if feat["col"] not in df.columns:
                continue
            m = evaluate_with_filter(df, sym, combo, feat)
            if m is None or m["n"] < 30:
                continue
            delta_ev = m["ev"] - base_ev
            results.append({"feat": feat["name"], **m, "delta_ev": delta_ev})

        # Trie par delta EV decroissant
        results.sort(key=lambda r: -r["delta_ev"])
        print(f"\n  {'Feature ajoutee':<22} {'n':>6} {'EV':>7} {'dEV':>7} {'PF':>5} {'WF+':>4} {'PSR':>5} {'Verdict':>10}")
        print(f"  {'-'*80}")
        for r in results[:10]:  # top 10
            verdict = "GO" if is_go(r) else ("BOOST" if r["delta_ev"] > 1.0 else "—")
            print(f"  {r['feat']:<22} {r['n']:>6} {r['ev']:>+6.2f} {r['delta_ev']:>+6.2f} "
                  f"{r['pf']:>5.2f} {r['pos_folds']:>3}/12 {r['psr']:>5.3f} {verdict:>10}")


if __name__ == "__main__":
    main()
