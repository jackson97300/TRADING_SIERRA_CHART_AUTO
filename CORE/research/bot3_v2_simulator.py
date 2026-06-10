"""bot3_v2_simulator.py — Comparatif Bot 3 actuel vs Bot 3 v2 (SIDAK + SLTPEngine).

Etape 1 du plan integration : valider empiriquement avant push live.

3 configs simulees sur 6 mois v4 enriched :
  A. ACTUEL : 13 niveaux heritage + filter regime ON + TP/SL simple
  B. +4 sans SLTP : 13 + 4 Sidak (bypass filter) + TP/SL simple
  C. +4 avec SLTP : 13 + 4 Sidak (bypass filter) + SLTPEngine wrapper

Wrapper SLTPEngine simplifie (calque sur mia_sltp.py) :
  - SHORT : SL au-dessus prochain mur Call/HVL/0DTE + 3t buffer
            TP avant prochain mur Put/HVL/0DTE - 2t buffer
  - LONG : miroir
  - Cap RR max (ES 2.5, NQ 2.0) + cap absolu (ES 80t, NQ 160t)
  - Fallback : sl_base * ATR multiplier, tp = sl * tp_rr_ratio si pas de mur exploitable

Methodologie stricte conservee : path-dependent SL, costs, WF 12 folds, PSR Bailey.
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

# Config Bot 3 (depuis bot3_config.py)
SL_BASE = {"ES": 32, "NQ": 80}
TP_RR_RATIO = 1.2
TP_CAP_TICKS = {"ES": 80, "NQ": 160}
MAX_RR = {"ES": 2.5, "NQ": 2.0}
WALL_BUFFER_SL = {"ES": 3, "NQ": 8}   # buffer derriere mur
WALL_BUFFER_TP = {"ES": 2, "NQ": 4}   # buffer avant mur
MAX_TP_WALL_DIST_PCT = 0.20            # 0.20% = ~50t ES, ~80t NQ (mur trop loin → fallback)


# ─── 4 NIVEAUX SIDAK ───
SIDAK_LEVELS = [
    {"name": "SWING_LOW",     "side": "LONG",  "col": "dist_last_swing_low_pct"},
    {"name": "SWING_HIGH",    "side": "SHORT", "col": "dist_last_swing_high_pct"},
    {"name": "COLOR_UP_zone", "side": "LONG",  "col": "dist_color_up_nearest_pct"},
    {"name": "COLOR_DN_zone", "side": "SHORT", "col": "dist_color_dn_nearest_pct"},
]

# ─── 13 NIVEAUX HERITAGE BOT 3 (mock simplifie) ───
# Note : pour la simulation A on simule juste un sous-ensemble de niveaux
# heritage (TIER1 cles) avec filter regime ON et TP/SL simple. Pas exact a 100%
# du Bot 3 prod, mais sufficient pour calibrer la baseline.
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
    """Mock filter directionnel (calque regime_engine simplifie).

    Utilise cvd_5d_rolling_ffd : > 50 -> LONG, < -50 -> SHORT, sinon NEUTRE.
    Approximation suffisante pour audit (le vrai regime_engine est plus riche).
    """
    cvd = bar.get("cvd_5d_rolling_ffd")
    if cvd is None or pd.isna(cvd):
        return "NEUTRE"
    cvd = float(cvd)
    if cvd > 50:
        return "LONG"
    if cvd < -50:
        return "SHORT"
    return "NEUTRE"


def compute_sltp_simple(sym, side, atr_normalized=1.0):
    """TP/SL Bot 3 actuel : sl_base * ATR mult, tp = sl * rr_ratio capped."""
    sl = int(round(SL_BASE[sym] * max(0.5, min(2.0, atr_normalized))))
    tp = int(round(sl * TP_RR_RATIO))
    tp = min(tp, TP_CAP_TICKS[sym])
    return sl, tp, "SIMPLE"


def compute_sltp_walls(sym, side, bar, atr_normalized=1.0):
    """SLTPEngine wrapper : SL derriere mur, TP avant mur. Fallback si pas de mur."""
    tick = TICK_SIZE[sym]
    close = float(bar.get("close", 0))
    if close <= 0:
        return compute_sltp_simple(sym, side, atr_normalized)

    # Murs above (resistances) : MQ_call, MQ_call_0DTE, MQ_HVL si dist > 0
    walls_above = []
    walls_below = []
    for col in ["dist_mq_call_pct", "dist_mq_call_0dte_pct", "dist_mq_hvl_pct"]:
        d = bar.get(col)
        if d is not None and not pd.isna(d):
            d = float(d)
            if d > 0:  # mur au-dessus du prix
                walls_above.append((d, col))
            elif d < 0:  # mur en-dessous
                walls_below.append((abs(d), col))
    for col in ["dist_mq_put_pct", "dist_mq_put_0dte_pct"]:
        d = bar.get(col)
        if d is not None and not pd.isna(d):
            d = float(d)
            if d < 0:
                walls_below.append((abs(d), col))
            elif d > 0:
                walls_above.append((d, col))

    walls_above.sort(key=lambda x: x[0])  # plus proche d'abord
    walls_below.sort(key=lambda x: x[0])

    sl_buf = WALL_BUFFER_SL[sym]
    tp_buf = WALL_BUFFER_TP[sym]
    sl_simple, tp_simple, _ = compute_sltp_simple(sym, side, atr_normalized)

    if side == "SHORT":
        # SL au-dessus du mur above le plus proche
        sl_wall = walls_above[0] if walls_above else None
        # TP avant mur below le plus proche
        tp_wall = walls_below[0] if walls_below else None
    else:  # LONG
        sl_wall = walls_below[0] if walls_below else None
        tp_wall = walls_above[0] if walls_above else None

    sl_reason = "SIMPLE"
    tp_reason = "SIMPLE"

    # SL placement
    if sl_wall is not None:
        sl_dist_pts = sl_wall[0] / 100 * close
        sl_ticks_wall = int(round(sl_dist_pts / tick)) + sl_buf
        if 8 <= sl_ticks_wall <= 2 * SL_BASE[sym]:  # plage acceptable
            sl_ticks = sl_ticks_wall
            sl_reason = f"WALL_{sl_wall[1]}"
        else:
            sl_ticks = sl_simple
    else:
        sl_ticks = sl_simple

    # TP placement
    if tp_wall is not None and tp_wall[0] <= MAX_TP_WALL_DIST_PCT:
        tp_dist_pts = tp_wall[0] / 100 * close
        tp_ticks_wall = max(8, int(round(tp_dist_pts / tick)) - tp_buf)
        # Cap RR max
        rr = tp_ticks_wall / sl_ticks
        if rr > MAX_RR[sym]:
            tp_ticks_wall = int(sl_ticks * MAX_RR[sym])
            tp_reason = f"WALL_{tp_wall[1]}_RR_CAPPED"
        else:
            tp_reason = f"WALL_{tp_wall[1]}"
        # Cap absolu
        if tp_ticks_wall > TP_CAP_TICKS[sym]:
            tp_ticks_wall = TP_CAP_TICKS[sym]
            tp_reason += "_ABS_CAPPED"
        tp_ticks = tp_ticks_wall
    else:
        tp_ticks = tp_simple

    return sl_ticks, tp_ticks, f"SL={sl_reason}|TP={tp_reason}"


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


def run_config(df, sym, config: str):
    """config = 'A' | 'B' | 'C'."""
    n = len(df)
    closes = df["close"].to_numpy()
    last = -COOLDOWN
    trades = []

    for i in range(50, n - FWD_BARS):
        if i - last < COOLDOWN:
            continue
        bar = df.iloc[i]

        # ─── Scan SIDAK levels (configs B et C) ───
        if config in ("B", "C"):
            for lvl in SIDAK_LEVELS:
                if lvl["col"] not in df.columns:
                    continue
                d = bar.get(lvl["col"])
                if d is None or pd.isna(d):
                    continue
                if abs(float(d)) > PROXIMITY_PCT_SIDAK:
                    continue
                # BYPASS filter regime pour Sidak
                # SLTPEngine pour config C, simple pour B
                if config == "C":
                    sl, tp, reason = compute_sltp_walls(sym, lvl["side"], bar)
                else:
                    sl, tp, reason = compute_sltp_simple(sym, lvl["side"])
                tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
                if tr is None:
                    continue
                tr.update({"signal": lvl["name"], "side": lvl["side"], "bucket": "SIDAK",
                           "sl": sl, "tp": tp, "reason": reason})
                trades.append(tr)
                last = i
                break

        # ─── Scan HERITAGE levels (configs A, B, C) ───
        if last == i:
            continue  # SIDAK a fire deja sur cette bar
        favor = regime_favor(bar)
        for lvl in HERITAGE_LEVELS:
            if lvl["col"] not in df.columns:
                continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d):
                continue
            if abs(float(d)) > lvl["proximity"]:
                continue
            # Filter regime ON pour heritage
            if favor != "NEUTRE":
                if (lvl["side"] == "LONG" and favor == "SHORT") or \
                   (lvl["side"] == "SHORT" and favor == "LONG"):
                    continue
            sl, tp, reason = compute_sltp_simple(sym, lvl["side"])
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None:
                continue
            tr.update({"signal": lvl["name"], "side": lvl["side"], "bucket": "HERITAGE",
                       "sl": sl, "tp": tp, "reason": reason})
            trades.append(tr)
            last = i
            break

    return trades


def metrics(trades, sym):
    if not trades:
        return None
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
    pos_folds = 0
    for k in range(12):
        sub = pnls[cuts[k]:cuts[k + 1]]
        if len(sub) >= 1 and sub.sum() >= 0:
            pos_folds += 1
    cum = pnls.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max()) if len(dd) > 0 else 0
    return {"n": n, "wr": wr, "pf": pf, "ev": ev, "total": total, "psr": psr,
            "pos_folds": pos_folds, "max_dd": max_dd, "$": pnl_dollars}


def report(label, sym, trades):
    m = metrics(trades, sym)
    if m is None:
        print(f"  {label} {sym} : aucun trade"); return None
    print(f"\n  {label} {sym} :")
    n_sidak = sum(1 for t in trades if t.get("bucket") == "SIDAK")
    n_her = sum(1 for t in trades if t.get("bucket") == "HERITAGE")
    print(f"    N total = {m['n']} (SIDAK={n_sidak}, HERITAGE={n_her})")
    print(f"    WR={m['wr']*100:.1f}%, PF={m['pf']:.2f}, EV={m['ev']:+.2f}t")
    print(f"    Total = {m['total']:+.0f}t = ${m['$']:+.0f} (1 contract)")
    print(f"    PSR={m['psr']:.4f}, WF+={m['pos_folds']}/12, MaxDD={m['max_dd']:.0f}t")
    if n_sidak > 0:
        sidak_trades = [t for t in trades if t["bucket"] == "SIDAK"]
        sidak_pnls = np.array([t["pnl"] for t in sidak_trades])
        print(f"    >>> SIDAK seul : n={len(sidak_pnls)}, EV={sidak_pnls.mean():+.2f}t, "
              f"total={sidak_pnls.sum():+.0f}t")
    if n_her > 0:
        her_trades = [t for t in trades if t["bucket"] == "HERITAGE"]
        her_pnls = np.array([t["pnl"] for t in her_trades])
        print(f"    >>> HERITAGE seul : n={len(her_pnls)}, EV={her_pnls.mean():+.2f}t, "
              f"total={her_pnls.sum():+.0f}t")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()

    all_results = {}
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, args.months)
        if df.empty:
            continue
        print(f"\n{'='*100}")
        print(f"=== BOT 3 V2 SIMULATOR — {sym} ({args.months} mois) ===")
        print(f"{'='*100}")
        print(f"  Loaded {len(df)} bars, {df['ts_event'].min()} -> {df['ts_event'].max()}")

        trades_A = run_config(df, sym, "A")
        m_A = report("CONFIG A (Bot 3 actuel)", sym, trades_A)

        trades_B = run_config(df, sym, "B")
        m_B = report("CONFIG B (+4 Sidak SANS SLTP)", sym, trades_B)

        trades_C = run_config(df, sym, "C")
        m_C = report("CONFIG C (+4 Sidak AVEC SLTP)", sym, trades_C)

        # Delta synthese
        if m_A and m_B and m_C:
            print(f"\n  DELTA {sym} :")
            print(f"    B vs A : N {m_B['n']-m_A['n']:+d}, EV {m_B['ev']-m_A['ev']:+.2f}t, "
                  f"$ {m_B['$']-m_A['$']:+.0f}")
            print(f"    C vs A : N {m_C['n']-m_A['n']:+d}, EV {m_C['ev']-m_A['ev']:+.2f}t, "
                  f"$ {m_C['$']-m_A['$']:+.0f}")
            print(f"    C vs B (effet SLTP pur) : N {m_C['n']-m_B['n']:+d}, "
                  f"EV {m_C['ev']-m_B['ev']:+.2f}t, $ {m_C['$']-m_B['$']:+.0f}")
        all_results[sym] = {"A": m_A, "B": m_B, "C": m_C}

    print(f"\n\n{'='*100}")
    print(f"=== SYNTHESE FINALE ===")
    print(f"{'='*100}\n")
    print(f"  {'Sym':<5} {'Config':<8} {'N':>6} {'EV':>7} {'PF':>5} {'Total $':>10} {'PSR':>6} {'WF+':>5} {'MaxDD':>7}")
    for sym in ["ES", "NQ"]:
        if sym not in all_results: continue
        r = all_results[sym]
        for cfg in ["A", "B", "C"]:
            m = r[cfg]
            if m:
                print(f"  {sym:<5} {cfg:<8} {m['n']:>6} {m['ev']:>+6.2f} {m['pf']:>5.2f} "
                      f"${m['$']:>+8.0f} {m['psr']:>5.3f} {m['pos_folds']:>3}/12 {m['max_dd']:>6.0f}t")


if __name__ == "__main__":
    main()
