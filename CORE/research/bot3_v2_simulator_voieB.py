"""bot3_v2_simulator_voieB.py — Comparatif Voie A vs Voie B (combos boostés priority 1).

Etape supplementaire pour valider l'inversion de priorite.

Configs :
  A. ACTUEL : 13 heritage + filter ON + TP/SL simple
  C. VOIE A : 13 heritage + 4 Sidak simples (bypass filter) + SLTPEngine wrapper
  D. VOIE B : 13 heritage + 3 COMBOS BOOSTES priority 1 + 4 Sidak simples priority 2
              + SLTPEngine wrapper

Combos boostés (validés audit boost_marginal_combos.py 09/05) :
  1. LONG_UP_x_SWING_LOW + room_1dmax (LONG ES, EV +4.53t)
  2. LONG_UP_x_SWING_LOW + aggr_buy (LONG NQ, EV +3.08t)
  3. LONG_DN_x_COLOR_DN (SHORT NQ uniquement, EV +2.68t)
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}
FWD_BARS = 30
COOLDOWN = 45
PROXIMITY_PCT_SIDAK = 0.02
SL_BASE = {"ES": 32, "NQ": 80}
TP_RR_RATIO = 1.2
TP_CAP_TICKS = {"ES": 80, "NQ": 160}
MAX_RR = {"ES": 2.5, "NQ": 2.0}
WALL_BUFFER_SL = {"ES": 3, "NQ": 8}
WALL_BUFFER_TP = {"ES": 2, "NQ": 4}
MAX_TP_WALL_DIST_PCT = 0.20

# Combos boostés (priority 1) — applies_to: ES / NQ / BOTH
COMBOS_BOOSTED = [
    {"name": "LONG_UP_x_SWING_LOW + room_1dmax",
     "side": "LONG", "applies_to": "ES",
     "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"],
     "filter": ("dist_1d_max_ticks_pct", ">", 0.30)},
    {"name": "LONG_UP_x_SWING_LOW + aggr_buy",
     "side": "LONG", "applies_to": "NQ",
     "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"],
     "filter": ("aggressor_imbalance", ">", 0.3)},
    {"name": "LONG_DN_x_COLOR_DN",
     "side": "SHORT", "applies_to": "NQ",
     "cols": ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"],
     "filter": None},
]

# Sidak simples (priority 2)
SIDAK_LEVELS = [
    {"name": "SWING_LOW",     "side": "LONG",  "col": "dist_last_swing_low_pct"},
    {"name": "SWING_HIGH",    "side": "SHORT", "col": "dist_last_swing_high_pct"},
    {"name": "COLOR_UP_zone", "side": "LONG",  "col": "dist_color_up_nearest_pct"},
    {"name": "COLOR_DN_zone", "side": "SHORT", "col": "dist_color_dn_nearest_pct"},
]

# Héritage mock (priority 3)
HERITAGE_LEVELS = [
    {"name": "IB_LOW",       "side": "LONG",  "col": "dist_ib_low_pct",         "proximity": 0.05},
    {"name": "IB_HIGH",      "side": "SHORT", "col": "dist_ib_high_pct",        "proximity": 0.05},
    {"name": "MQ_PUT_0DTE",  "side": "LONG",  "col": "dist_mq_put_0dte_pct",    "proximity": 0.05},
    {"name": "MQ_CALL_0DTE", "side": "SHORT", "col": "dist_mq_call_0dte_pct",   "proximity": 0.05},
    {"name": "OPEN_830",     "side": "LONG",  "col": "dist_open_830_pct",       "proximity": 0.05},
    {"name": "OPEN_930",     "side": "LONG",  "col": "dist_open_930_pct",       "proximity": 0.05},
    {"name": "MQ_HVL",       "side": "LONG",  "col": "dist_mq_hvl_pct",         "proximity": 0.05},
    {"name": "GEX_DN",       "side": "LONG",  "col": "dist_gex_nearest_dn_pct", "proximity": 0.05},
    {"name": "PVAL",         "side": "LONG",  "col": "dist_prev_val_pct",       "proximity": 0.10},
    {"name": "PVAH",         "side": "SHORT", "col": "dist_prev_vah_pct",       "proximity": 0.10},
    {"name": "PDH",          "side": "SHORT", "col": "dist_pdh_pct",            "proximity": 0.10},
    {"name": "MQ_CALL",      "side": "SHORT", "col": "dist_mq_call_pct",        "proximity": 0.05},
    {"name": "VWAP_W_SD1D",  "side": "LONG",  "col": "dist_vwap_w_sd1d_pct",    "proximity": 0.10},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def regime_favor(bar):
    cvd = bar.get("cvd_5d_rolling_ffd")
    if cvd is None or pd.isna(cvd):
        return "NEUTRE"
    cvd = float(cvd)
    if cvd > 50:  return "LONG"
    if cvd < -50: return "SHORT"
    return "NEUTRE"


def compute_sltp_simple(sym, atr_normalized=1.0):
    sl = int(round(SL_BASE[sym] * max(0.5, min(2.0, atr_normalized))))
    tp = int(round(sl * TP_RR_RATIO))
    tp = min(tp, TP_CAP_TICKS[sym])
    return sl, tp


def compute_sltp_walls(sym, side, bar):
    """SLTPEngine wrapper simplifié."""
    tick = TICK_SIZE[sym]
    close = float(bar.get("close", 0))
    if close <= 0:
        return compute_sltp_simple(sym)
    walls_above, walls_below = [], []
    for col in ["dist_mq_call_pct", "dist_mq_call_0dte_pct", "dist_mq_hvl_pct"]:
        d = bar.get(col)
        if d is not None and not pd.isna(d):
            d = float(d)
            if d > 0: walls_above.append((d, col))
            elif d < 0: walls_below.append((abs(d), col))
    for col in ["dist_mq_put_pct", "dist_mq_put_0dte_pct"]:
        d = bar.get(col)
        if d is not None and not pd.isna(d):
            d = float(d)
            if d < 0: walls_below.append((abs(d), col))
            elif d > 0: walls_above.append((d, col))
    walls_above.sort(key=lambda x: x[0])
    walls_below.sort(key=lambda x: x[0])
    sl_buf = WALL_BUFFER_SL[sym]; tp_buf = WALL_BUFFER_TP[sym]
    sl_simple, tp_simple = compute_sltp_simple(sym)
    if side == "SHORT":
        sl_wall = walls_above[0] if walls_above else None
        tp_wall = walls_below[0] if walls_below else None
    else:
        sl_wall = walls_below[0] if walls_below else None
        tp_wall = walls_above[0] if walls_above else None
    if sl_wall is not None:
        sl_dist_pts = sl_wall[0] / 100 * close
        sl_ticks_wall = int(round(sl_dist_pts / tick)) + sl_buf
        if 8 <= sl_ticks_wall <= 2 * SL_BASE[sym]:
            sl_ticks = sl_ticks_wall
        else:
            sl_ticks = sl_simple
    else:
        sl_ticks = sl_simple
    if tp_wall is not None and tp_wall[0] <= MAX_TP_WALL_DIST_PCT:
        tp_dist_pts = tp_wall[0] / 100 * close
        tp_ticks_wall = max(8, int(round(tp_dist_pts / tick)) - tp_buf)
        rr = tp_ticks_wall / sl_ticks
        if rr > MAX_RR[sym]:
            tp_ticks_wall = int(sl_ticks * MAX_RR[sym])
        if tp_ticks_wall > TP_CAP_TICKS[sym]:
            tp_ticks_wall = TP_CAP_TICKS[sym]
        tp_ticks = tp_ticks_wall
    else:
        tp_ticks = tp_simple
    return sl_ticks, tp_ticks


def simulate_trade(df, i, side, sl_ticks, tp_ticks, sym):
    n = len(df)
    if i + FWD_BARS >= n:
        return None
    tick = TICK_SIZE[sym]; cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    entry = closes[i]
    if side == "LONG":
        tp = entry + tp_ticks * tick; sl = entry - sl_ticks * tick
    else:
        tp = entry - tp_ticks * tick; sl = entry + sl_ticks * tick
    for k in range(i + 1, min(i + FWD_BARS + 1, n)):
        bh = highs[k]; bl = lows[k]
        if side == "LONG":
            sl_hit = bl <= sl; tp_hit = bh >= tp
        else:
            sl_hit = bh >= sl; tp_hit = bl <= tp
        if sl_hit and tp_hit: return {"pnl": -float(sl_ticks) - cost, "exit": "SL_PESS"}
        if sl_hit:            return {"pnl": -float(sl_ticks) - cost, "exit": "SL"}
        if tp_hit:            return {"pnl": float(tp_ticks) - cost,  "exit": "TP"}
    final = closes[min(i + FWD_BARS, n - 1)]
    pnl = float(((final - entry) if side == "LONG" else (entry - final)) / tick - cost)
    return {"pnl": pnl, "exit": "TIMEOUT"}


def check_combo_at_bar(df, i, combo):
    """Check si combo fire à la bar i (toutes conditions remplies)."""
    bar = df.iloc[i]
    for col in combo["cols"]:
        d = bar.get(col)
        if d is None or pd.isna(d) or abs(float(d)) > PROXIMITY_PCT_SIDAK:
            return False
    if combo["filter"]:
        col, op, thr = combo["filter"]
        v = bar.get(col)
        if v is None or pd.isna(v): return False
        v = float(v)
        if op == ">"  and not (v > thr):  return False
        if op == "<"  and not (v < thr):  return False
    return True


def run_voie_B(df, sym):
    """Config D : combos boostés P1 + Sidak P2 + héritage P3."""
    n = len(df)
    last = -COOLDOWN
    trades = []
    combos_for_sym = [c for c in COMBOS_BOOSTED if c["applies_to"] in (sym, "BOTH")]

    for i in range(50, n - FWD_BARS):
        if i - last < COOLDOWN:
            continue
        bar = df.iloc[i]
        fired = False

        # PRIORITY 1 : combos boostés
        for combo in combos_for_sym:
            if check_combo_at_bar(df, i, combo):
                sl, tp = compute_sltp_walls(sym, combo["side"], bar)
                tr = simulate_trade(df, i, combo["side"], sl, tp, sym)
                if tr is None: continue
                tr.update({"signal": combo["name"], "side": combo["side"], "bucket": "COMBO_BOOSTED"})
                trades.append(tr); last = i; fired = True; break
        if fired: continue

        # PRIORITY 2 : Sidak simples (bypass filter)
        for lvl in SIDAK_LEVELS:
            if lvl["col"] not in df.columns: continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d): continue
            if abs(float(d)) > PROXIMITY_PCT_SIDAK: continue
            sl, tp = compute_sltp_walls(sym, lvl["side"], bar)
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None: continue
            tr.update({"signal": lvl["name"], "side": lvl["side"], "bucket": "SIDAK"})
            trades.append(tr); last = i; fired = True; break
        if fired: continue

        # PRIORITY 3 : héritage (filter regime ON)
        favor = regime_favor(bar)
        for lvl in HERITAGE_LEVELS:
            if lvl["col"] not in df.columns: continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d): continue
            if abs(float(d)) > lvl["proximity"]: continue
            if favor != "NEUTRE":
                if (lvl["side"] == "LONG" and favor == "SHORT") or \
                   (lvl["side"] == "SHORT" and favor == "LONG"):
                    continue
            sl, tp = compute_sltp_simple(sym)
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None: continue
            tr.update({"signal": lvl["name"], "side": lvl["side"], "bucket": "HERITAGE"})
            trades.append(tr); last = i; break

    return trades


def run_voie_A(df, sym):
    """Config C : Sidak simples P1 + héritage P2 (pas de combos boostés)."""
    n = len(df)
    last = -COOLDOWN
    trades = []
    for i in range(50, n - FWD_BARS):
        if i - last < COOLDOWN: continue
        bar = df.iloc[i]
        fired = False
        for lvl in SIDAK_LEVELS:
            if lvl["col"] not in df.columns: continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d) or abs(float(d)) > PROXIMITY_PCT_SIDAK: continue
            sl, tp = compute_sltp_walls(sym, lvl["side"], bar)
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None: continue
            tr.update({"signal": lvl["name"], "side": lvl["side"], "bucket": "SIDAK"})
            trades.append(tr); last = i; fired = True; break
        if fired: continue
        favor = regime_favor(bar)
        for lvl in HERITAGE_LEVELS:
            if lvl["col"] not in df.columns: continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d) or abs(float(d)) > lvl["proximity"]: continue
            if favor != "NEUTRE":
                if (lvl["side"] == "LONG" and favor == "SHORT") or \
                   (lvl["side"] == "SHORT" and favor == "LONG"): continue
            sl, tp = compute_sltp_simple(sym)
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None: continue
            tr.update({"signal": lvl["name"], "side": lvl["side"], "bucket": "HERITAGE"})
            trades.append(tr); last = i; break
    return trades


def metrics(trades, sym):
    if not trades: return None
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    wr = (pnls > 0).mean()
    sw = pnls[pnls > 0].sum(); sl = abs(pnls[pnls < 0].sum())
    pf = sw / sl if sl > 0 else float("inf")
    ev = pnls.mean()
    total = pnls.sum()
    pnl_dollars = total * (1.25 if sym == "ES" else 0.50)
    if pnls.std() > 0 and n > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(pnls); kt = kurtosis(pnls, fisher=False)
        sr = pnls.mean() / pnls.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n - 1) / denom))
    else:
        psr = 0.5
    cuts = np.linspace(0, n, 13, dtype=int)
    pos_folds = sum(1 for k in range(12) if pnls[cuts[k]:cuts[k+1]].sum() >= 0)
    cum = pnls.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max()) if len(dd) > 0 else 0
    return {"n": n, "wr": wr, "pf": pf, "ev": ev, "total": total, "psr": psr,
            "pos_folds": pos_folds, "max_dd": max_dd, "$": pnl_dollars}


def report(label, sym, trades):
    m = metrics(trades, sym)
    if m is None: return None
    n_combo = sum(1 for t in trades if t.get("bucket") == "COMBO_BOOSTED")
    n_sidak = sum(1 for t in trades if t.get("bucket") == "SIDAK")
    n_her = sum(1 for t in trades if t.get("bucket") == "HERITAGE")
    print(f"\n  {label} {sym} :")
    print(f"    N total = {m['n']} (COMBO_BOOST={n_combo}, SIDAK={n_sidak}, HERITAGE={n_her})")
    print(f"    WR={m['wr']*100:.1f}% PF={m['pf']:.2f} EV={m['ev']:+.2f}t total={m['total']:+.0f}t = ${m['$']:+.0f}")
    print(f"    PSR={m['psr']:.4f} WF+={m['pos_folds']}/12 MaxDD={m['max_dd']:.0f}t")
    if n_combo > 0:
        cb = [t for t in trades if t["bucket"] == "COMBO_BOOSTED"]
        cb_pnl = np.array([t["pnl"] for t in cb])
        print(f"    >>> COMBO_BOOST seul : n={len(cb_pnl)}, EV={cb_pnl.mean():+.2f}t, total={cb_pnl.sum():+.0f}t")
    if n_sidak > 0:
        sk = [t for t in trades if t["bucket"] == "SIDAK"]
        sk_pnl = np.array([t["pnl"] for t in sk])
        print(f"    >>> SIDAK seul : n={len(sk_pnl)}, EV={sk_pnl.mean():+.2f}t, total={sk_pnl.sum():+.0f}t")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()

    all_results = {}
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, args.months)
        if df.empty: continue
        print(f"\n{'='*100}")
        print(f"=== BOT 3 V2 SIMULATOR VOIE B — {sym} ({args.months} mois) ===")
        print(f"{'='*100}")
        print(f"  Loaded {len(df)} bars")
        # Voie A (référence)
        trades_A = run_voie_A(df, sym)
        m_A = report("VOIE A (Sidak P1 + heritage P2)", sym, trades_A)
        # Voie B (combos boostés P1)
        trades_B = run_voie_B(df, sym)
        m_B = report("VOIE B (combos boostes P1 + Sidak P2 + heritage P3)", sym, trades_B)
        if m_A and m_B:
            print(f"\n  DELTA B vs A {sym} :")
            print(f"    N : {m_B['n']-m_A['n']:+d} ({m_B['n']} vs {m_A['n']})")
            print(f"    EV/trade : {m_B['ev']-m_A['ev']:+.2f}t ({m_B['ev']:+.2f} vs {m_A['ev']:+.2f})")
            print(f"    Total $ : {(m_B['total']-m_A['total'])*(1.25 if sym=='ES' else 0.50):+.0f}$ "
                  f"(${m_B['$']:+.0f} vs ${m_A['$']:+.0f})")
            print(f"    PSR : {m_B['psr']:.4f} vs {m_A['psr']:.4f}")
            print(f"    WF+ : {m_B['pos_folds']}/12 vs {m_A['pos_folds']}/12")
            print(f"    MaxDD : {m_B['max_dd']:.0f}t vs {m_A['max_dd']:.0f}t")
        all_results[sym] = {"A": m_A, "B": m_B}

    print(f"\n\n{'='*100}")
    print(f"=== SYNTHESE FINALE A vs B ===")
    print(f"{'='*100}\n")
    print(f"  {'Sym':<5} {'Voie':<6} {'N':>6} {'EV':>7} {'PF':>5} {'Total $':>10} {'PSR':>6} {'WF+':>5} {'MaxDD':>7}")
    for sym in ["ES", "NQ"]:
        if sym not in all_results: continue
        for v in ["A", "B"]:
            m = all_results[sym][v]
            if m:
                print(f"  {sym:<5} {v:<6} {m['n']:>6} {m['ev']:>+6.2f} {m['pf']:>5.2f} "
                      f"${m['$']:>+8.0f} {m['psr']:>5.3f} {m['pos_folds']:>3}/12 {m['max_dd']:>6.0f}t")


if __name__ == "__main__":
    main()
