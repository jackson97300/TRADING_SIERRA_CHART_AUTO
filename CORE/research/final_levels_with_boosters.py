"""final_levels_with_boosters.py — Liste finale niveaux + boosters optimaux.

Pour chaque niveau GO (SWING_LOW, SWING_HIGH, COLOR_UP_zone, COLOR_DN_zone),
tester les boosters trader-driven compatibles avec la direction. Identifier
le top booster qui maximise EV sans sacrifier trop de sample.

Boosters (anti pattern 11 : limites a 4 trader-driven par direction) :
  LONG  : room_1dmax, aggr_buy, below_pvpoc, cvd_bull
  SHORT : room_1dmin, aggr_sell, above_pvpoc, cvd_bear

4 niveaux x 4 boosters x 2 syms = 32 tests.
Bonferroni alpha=0.05/32=0.00156 -> PSR seuil 0.998.

Output : liste finale (niveau, booster optimal, n, EV, dEV vs base).
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

# 4 niveaux GO Sidak validates
LEVELS = [
    {"name": "SWING_LOW",     "side": "LONG",  "col": "dist_last_swing_low_pct"},
    {"name": "SWING_HIGH",    "side": "SHORT", "col": "dist_last_swing_high_pct"},
    {"name": "COLOR_UP_zone", "side": "LONG",  "col": "dist_color_up_nearest_pct"},
    {"name": "COLOR_DN_zone", "side": "SHORT", "col": "dist_color_dn_nearest_pct"},
]

# Boosters trader-driven (4 par direction)
BOOSTERS_LONG = [
    {"name": "room_1dmax",   "col": "dist_1d_max_ticks_pct",  "op": ">",  "thr": 0.30,
     "rationale": "marge >100t vers high jour precedent = pas de plafond technique"},
    {"name": "aggr_buy",     "col": "aggressor_imbalance",    "op": ">",  "thr": 0.3,
     "rationale": "flux acheteur dominant a l'instant"},
    {"name": "below_pvpoc",  "col": "dist_prev_vpoc_pct",     "op": "<",  "thr": -0.05,
     "rationale": "prix sous PVPOC veille = value zone bas"},
    {"name": "cvd_bull",     "col": "cvd_5d_rolling_ffd",     "op": ">",  "thr": 50,
     "rationale": "regime bull confirme (CVD 5d FFD)"},
]
BOOSTERS_SHORT = [
    {"name": "room_1dmin",   "col": "dist_1d_min_ticks_pct",  "op": "<",  "thr": -0.30,
     "rationale": "marge >100t vers low jour precedent = pas de plancher"},
    {"name": "aggr_sell",    "col": "aggressor_imbalance",    "op": "<",  "thr": -0.3,
     "rationale": "flux vendeur dominant"},
    {"name": "above_pvpoc",  "col": "dist_prev_vpoc_pct",     "op": ">",  "thr": 0.05,
     "rationale": "prix au-dessus PVPOC veille = re-test resistance"},
    {"name": "cvd_bear",     "col": "cvd_5d_rolling_ffd",     "op": "<",  "thr": -50,
     "rationale": "regime bear confirme"},
]

N_TESTS = len(LEVELS) * 4 * 2  # 32
BONF_ALPHA = 0.05 / N_TESTS
PSR_TH = 1 - BONF_ALPHA  # ~0.998


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def simulate_trade(df, i, direction, sym):
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


def evaluate(df, sym, level_col, side, filter_col=None, op=None, thr=None):
    if level_col not in df.columns:
        return None
    near = df[level_col].astype(float).abs() <= PROXIMITY_PCT
    if filter_col:
        if filter_col not in df.columns:
            return None
        s = df[filter_col].astype(float)
        if op == ">":   f_mask = s > thr
        elif op == "<": f_mask = s < thr
        elif op == ">=":f_mask = s >= thr
        elif op == "<=":f_mask = s <= thr
        else: return None
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
        pnl = simulate_trade(df, i, side, sym)
        if pnl is None:
            continue
        pnls.append(pnl); last = i
    if len(pnls) < 30:
        return {"n": len(pnls), "ev": 0, "pf": 0, "wr": 0, "psr": 0, "pos_folds": 0, "total": 0}
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
            "psr": float(psr), "pos_folds": pos_folds, "total": float(arr.sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    print(f"\n=== LISTE FINALE NIVEAUX + BOOSTERS OPTIMAUX ===")
    print(f"=== {N_TESTS} tests, Bonferroni alpha={BONF_ALPHA:.4f}, PSR seuil={PSR_TH:.4f} ===\n")

    final_list = []
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, args.months)
        if df.empty: continue
        print(f"\n{'='*100}")
        print(f"=== {sym} ===")
        print(f"{'='*100}")

        for lvl in LEVELS:
            print(f"\n--- {lvl['name']} {lvl['side']} ---")
            base = evaluate(df, sym, lvl["col"], lvl["side"])
            if base is None or base["n"] < 30:
                print(f"  BASE : sample insuffisant"); continue
            print(f"  BASELINE seul : n={base['n']}, EV={base['ev']:+.2f}, PF={base['pf']:.2f}, "
                  f"WF={base['pos_folds']}/12, PSR={base['psr']:.4f}, total={base['total']:+.0f}t")

            boosters = BOOSTERS_LONG if lvl["side"] == "LONG" else BOOSTERS_SHORT
            results = []
            for b in boosters:
                m = evaluate(df, sym, lvl["col"], lvl["side"],
                              b["col"], b["op"], b["thr"])
                if m is None or m["n"] < 30:
                    continue
                delta_ev = m["ev"] - base["ev"]
                results.append({"booster": b["name"], **m, "delta_ev": delta_ev})
            results.sort(key=lambda r: -r["delta_ev"])
            print(f"\n  {'Booster':<18} {'n':>6} {'EV':>7} {'dEV':>7} {'PF':>5} {'WF+':>5} {'PSR':>7} {'total':>8}")
            for r in results:
                go_marker = " ⭐" if (r["psr"] >= PSR_TH and r["pos_folds"] >= 10
                                       and r["ev"] >= base["ev"] + 1.0) else ""
                print(f"  {r['booster']:<18} {r['n']:>6} {r['ev']:>+6.2f} {r['delta_ev']:>+6.2f} "
                      f"{r['pf']:>5.2f} {r['pos_folds']:>3}/12 {r['psr']:>7.4f} {r['total']:>+8.0f}t{go_marker}")

            # Best booster (max delta_ev qui passe Sidak strict)
            best = next((r for r in results if r["psr"] >= PSR_TH and r["pos_folds"] >= 10
                         and r["ev"] >= base["ev"] + 1.0), None)
            if best:
                print(f"\n  >>> BEST BOOSTER {sym} {lvl['name']}: + {best['booster']} "
                      f"(EV {base['ev']:+.2f} -> {best['ev']:+.2f}, n {base['n']} -> {best['n']})")
                final_list.append({"sym": sym, "level": lvl["name"], "side": lvl["side"],
                                    "base_ev": base["ev"], "base_n": base["n"],
                                    "booster": best["booster"], "boost_ev": best["ev"], "boost_n": best["n"]})
            else:
                final_list.append({"sym": sym, "level": lvl["name"], "side": lvl["side"],
                                    "base_ev": base["ev"], "base_n": base["n"],
                                    "booster": None, "boost_ev": base["ev"], "boost_n": base["n"]})

    # ─── LISTE FINALE SYNTHESE ───
    print(f"\n{'='*100}")
    print(f"=== LISTE FINALE COMPLETE ===")
    print(f"{'='*100}\n")
    print(f"  {'Sym':<4} {'Niveau':<18} {'Side':<6} {'Base n':>7} {'Base EV':>8} {'Booster':<18} {'Boost n':>8} {'Boost EV':>9} {'Verdict':>10}")
    for r in final_list:
        verdict = "BOOST" if r["booster"] else "BASE"
        booster = r["booster"] or "—"
        print(f"  {r['sym']:<4} {r['level']:<18} {r['side']:<6} "
              f"{r['base_n']:>7} {r['base_ev']:>+7.2f} {booster:<18} "
              f"{r['boost_n']:>8} {r['boost_ev']:>+8.2f} {verdict:>10}")


if __name__ == "__main__":
    main()
