"""compare_lists_aggregated.py — Comparatif Liste 1 vs Liste 2 en bot virtuel.

Liste 1 : 4 niveaux Sidak + 1 combo NQ (LONG_DN_x_COLOR_DN)
Liste 2 : Liste 1 + 2 combos boostes (LONG_UP_x_SWING_LOW + room_1dmax ES,
                                       LONG_UP_x_SWING_LOW + aggr_buy NQ)

Bot virtuel agrege :
  - Pour chaque bar, scan tous les signaux
  - Premier signal qui fire (priority : niveaux d'abord, combos apres) -> trade
  - Cooldown 45b global (pas de chevauchement)
  - Methodologie stricte : TP=24t, SL=12t, costs, WF 12 folds, PSR
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


# Definition signaux : (name, kind, side, applies_to, masks_func, priority)
def make_signal(name, side, base_cols, filter_col=None, filter_op=None, filter_thr=None,
                applies_to="BOTH", priority=1):
    return {
        "name": name, "side": side, "base_cols": base_cols,
        "filter_col": filter_col, "filter_op": filter_op, "filter_thr": filter_thr,
        "applies_to": applies_to, "priority": priority,
    }


# ─── LISTE 1 : 4 niveaux Sidak + 1 combo NQ ───
LIST_1 = [
    make_signal("SWING_LOW",        "LONG",  ["dist_last_swing_low_pct"],  priority=1),
    make_signal("SWING_HIGH",       "SHORT", ["dist_last_swing_high_pct"], priority=1),
    make_signal("COLOR_UP_zone",    "LONG",  ["dist_color_up_nearest_pct"],priority=1),
    make_signal("COLOR_DN_zone",    "SHORT", ["dist_color_dn_nearest_pct"],priority=1),
    make_signal("LONG_DN_x_COLOR_DN", "SHORT",
                 ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"],
                 applies_to="NQ", priority=2),
]

# ─── LISTE 2 : Liste 1 + 2 combos boostes ───
LIST_2 = LIST_1 + [
    make_signal("LONG_UP_x_SWING_LOW + room_1dmax", "LONG",
                 ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"],
                 filter_col="dist_1d_max_ticks_pct", filter_op=">", filter_thr=0.30,
                 applies_to="ES", priority=2),
    make_signal("LONG_UP_x_SWING_LOW + aggr_buy", "LONG",
                 ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"],
                 filter_col="aggressor_imbalance", filter_op=">", filter_thr=0.3,
                 applies_to="NQ", priority=2),
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def precompute_signal_masks(df, sym, signals):
    """Pour chaque signal applicable, calcule un boolean array."""
    out = []
    for sig in signals:
        if sig["applies_to"] not in ("BOTH", sym):
            continue
        # Cols presence check
        if any(c not in df.columns for c in sig["base_cols"]):
            continue
        masks = [df[c].astype(float).abs() <= PROXIMITY_PCT for c in sig["base_cols"]]
        near = masks[0]
        for m in masks[1:]:
            near = near & m
        if sig["filter_col"]:
            if sig["filter_col"] not in df.columns:
                continue
            s = df[sig["filter_col"]].astype(float)
            op = sig["filter_op"]; thr = sig["filter_thr"]
            if op == ">":   f_mask = s > thr
            elif op == "<": f_mask = s < thr
            elif op == ">=":f_mask = s >= thr
            elif op == "<=":f_mask = s <= thr
            else:           f_mask = pd.Series(True, index=df.index)
            near = near & f_mask
        out.append({"name": sig["name"], "side": sig["side"],
                    "mask": near.to_numpy(), "priority": sig["priority"]})
    # Trie par priority (1 d'abord)
    out.sort(key=lambda x: x["priority"])
    return out


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


def run_bot(df, sym, signals_compiled):
    """Simule un bot qui trade sur signals_compiled. Return list of trades."""
    n = len(df)
    last = -COOLDOWN
    trades = []
    for i in range(20, n - FWD_BARS):
        if i - last < COOLDOWN:
            continue
        # Scan signaux dans l'ordre priority
        fired = None
        for sig in signals_compiled:
            if sig["mask"][i]:
                fired = sig
                break
        if fired is None:
            continue
        pnl = simulate_trade(df, i, fired["side"], sym)
        if pnl is None:
            continue
        trades.append({"entry_idx": i, "signal": fired["name"],
                       "side": fired["side"], "pnl": pnl})
        last = i
    return trades


def metrics(trades):
    if not trades:
        return None
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    wr = (pnls > 0).mean()
    sw = pnls[pnls > 0].sum(); sl = abs(pnls[pnls < 0].sum())
    pf = sw / sl if sl > 0 else float("inf")
    ev = pnls.mean()
    total = pnls.sum()
    if pnls.std() > 0 and n > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(pnls); kt = kurtosis(pnls, fisher=False)
        sr = pnls.mean() / pnls.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n - 1) / denom))
    else:
        psr = 0.5
    cuts = np.linspace(0, n, 13, dtype=int)
    pos_folds = 0
    fold_evs = []
    for k in range(12):
        sub = pnls[cuts[k]:cuts[k + 1]]
        if len(sub) >= 1:
            fold_evs.append(float(sub.mean()))
            if sub.sum() >= 0:
                pos_folds += 1
    # Max drawdown sur cumsum
    cum = pnls.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max()) if len(dd) > 0 else 0
    return {"n": n, "wr": wr, "pf": pf, "ev": ev, "total": total,
            "psr": psr, "pos_folds": pos_folds, "max_dd": max_dd,
            "fold_ev_min": min(fold_evs) if fold_evs else 0,
            "fold_ev_max": max(fold_evs) if fold_evs else 0}


def report(label, sym, trades):
    m = metrics(trades)
    if m is None:
        print(f"  {label} {sym} : aucun trade"); return
    pnl_dollars = m["total"] * 1.25 if sym == "ES" else m["total"] * 0.50  # ES tick $1.25, NQ tick $0.50
    print(f"\n  {label} {sym} :")
    print(f"    N trades : {m['n']}")
    print(f"    WR : {m['wr']*100:.1f}%, PF : {m['pf']:.2f}, EV/trade : {m['ev']:+.2f}t")
    print(f"    Total ticks : {m['total']:+.0f}t (= ${pnl_dollars:+.0f} sur 1 contract)")
    print(f"    PSR : {m['psr']:.4f}")
    print(f"    WF 12 folds : {m['pos_folds']}/12 positifs (range EV [{m['fold_ev_min']:+.2f}, {m['fold_ev_max']:+.2f}])")
    print(f"    Max DD : {m['max_dd']:.0f}t")
    # Breakdown par signal
    by_sig = {}
    for t in trades:
        by_sig.setdefault(t["signal"], []).append(t["pnl"])
    print(f"    Breakdown par signal :")
    for name, pnls in sorted(by_sig.items(), key=lambda x: -np.mean(x[1])):
        arr = np.array(pnls)
        print(f"      {name:<35s} n={len(arr):>4} EV={arr.mean():+.2f}t total={arr.sum():+.0f}t")


def compare(sym, df):
    print(f"\n{'='*100}")
    print(f"=== COMPARATIF {sym} — Liste 1 vs Liste 2 ===")
    print(f"{'='*100}")
    sigs1 = precompute_signal_masks(df, sym, LIST_1)
    sigs2 = precompute_signal_masks(df, sym, LIST_2)
    print(f"\n  Liste 1 ({sym}) : {len(sigs1)} signaux applicables ({[s['name'] for s in sigs1]})")
    print(f"  Liste 2 ({sym}) : {len(sigs2)} signaux applicables ({[s['name'] for s in sigs2]})")
    trades_1 = run_bot(df, sym, sigs1)
    trades_2 = run_bot(df, sym, sigs2)
    report("LISTE 1", sym, trades_1)
    report("LISTE 2", sym, trades_2)
    # Delta
    m1 = metrics(trades_1); m2 = metrics(trades_2)
    if m1 and m2:
        print(f"\n  DELTA L2 vs L1 {sym} :")
        print(f"    N trades : {m2['n']} vs {m1['n']} ({m2['n']-m1['n']:+d})")
        print(f"    EV/trade : {m2['ev']:+.2f}t vs {m1['ev']:+.2f}t ({m2['ev']-m1['ev']:+.2f}t)")
        print(f"    Total ticks : {m2['total']:+.0f}t vs {m1['total']:+.0f}t ({m2['total']-m1['total']:+.0f}t)")
        if sym == "ES":
            print(f"    Total $ : ${m2['total']*1.25:+.0f} vs ${m1['total']*1.25:+.0f} ({(m2['total']-m1['total'])*1.25:+.0f}$)")
        else:
            print(f"    Total $ : ${m2['total']*0.50:+.0f} vs ${m1['total']*0.50:+.0f} ({(m2['total']-m1['total'])*0.50:+.0f}$)")
        print(f"    PSR : {m2['psr']:.4f} vs {m1['psr']:.4f}")
        print(f"    WF + : {m2['pos_folds']}/12 vs {m1['pos_folds']}/12")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, args.months)
        if df.empty:
            continue
        print(f"\n[{sym}] Loaded {len(df)} bars")
        compare(sym, df)


if __name__ == "__main__":
    main()
