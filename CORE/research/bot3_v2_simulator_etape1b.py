"""bot3_v2_simulator_etape1b.py — Etape 1b : VRAI SLTPEngine importe.

Etape 1a (simulator simplifie) avait montre delta favorable.
Etape 1b utilise le VRAI mia_sltp.py 941 LOC pour validation rigoureuse
avant push live.

Wrapper :
  - convert_v4_bar_to_sltp_input() : v4_enriched (dist_*_pct en %) -> SLTPEngine (dist_* en ticks)
  - engine.evaluate_single(bar, direction) -> SLTPResult
  - Si valid : sl/tp wall-aware (SLTPEngine logique complete)
  - Si reject : fallback STANDARD Bot 3 (sl_base × ATR, tp = sl × 1.2)

Configs simulees :
  A. Bot 3 actuel (mock heritage seul)
  C. Bot 3 v2 Voie A (Sidak P1 + heritage P2 + SLTPEngine)
  D. Bot 3 v2 Voie B (combos boostes P1 + Sidak P2 + heritage P3 + SLTPEngine)

Bot 3 ACTUEL n'est PAS modifie (research only).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

# Import VRAI SLTPEngine
from mia_sltp import SLTPEngine  # noqa: E402

TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}
FWD_BARS = 30
COOLDOWN = 45
PROXIMITY_PCT_SIDAK = 0.02

# Standard Bot 3 fallback (si SLTPEngine reject)
SL_BASE = {"ES": 32, "NQ": 80}
TP_RR_RATIO = 1.2
TP_CAP_TICKS = {"ES": 80, "NQ": 160}
ATR_MULTIPLIER_CLAMP = (0.7, 1.5)

# Combos boostés (priority 1) — Voie B
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

SIDAK_LEVELS = [
    {"name": "SWING_LOW",     "side": "LONG",  "col": "dist_last_swing_low_pct"},
    {"name": "SWING_HIGH",    "side": "SHORT", "col": "dist_last_swing_high_pct"},
    {"name": "COLOR_UP_zone", "side": "LONG",  "col": "dist_color_up_nearest_pct"},
    {"name": "COLOR_DN_zone", "side": "SHORT", "col": "dist_color_dn_nearest_pct"},
]

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


def convert_v4_bar_to_sltp_input(bar, sym):
    """Convert v4_enriched bar to SLTPEngine input format.

    SLTPEngine attend des dist_* en TICKS signees (positive = au-dessus, negative = en-dessous).
    v4_enriched a des dist_*_pct en POURCENTAGE.

    Conversion : dist_ticks = dist_pct / 100 * close / tick_size
    """
    tick = TICK_SIZE[sym]
    close = bar.get("close")
    if close is None or pd.isna(close) or close <= 0:
        return None
    close = float(close)
    out = {"close": close, "high": float(bar.get("high", close)),
           "low": float(bar.get("low", close)), "open": float(bar.get("open", close))}
    # Convert all dist_*_pct -> dist_* (ticks)
    for col in bar.index:
        if isinstance(col, str) and col.startswith("dist_") and col.endswith("_pct"):
            col_ticks = col[:-4]  # strip "_pct"
            v = bar[col]
            if v is None or pd.isna(v):
                out[col_ticks] = np.nan
                continue
            try:
                d_pts = float(v) / 100.0 * close
                d_ticks = d_pts / tick
                out[col_ticks] = d_ticks
            except (ValueError, TypeError):
                out[col_ticks] = np.nan
    # Other features that might be needed
    for k in ["atr", "rvol", "cvd_5d_rolling_ffd", "aggressor_imbalance"]:
        v = bar.get(k)
        if v is not None and not pd.isna(v):
            out[k] = float(v)
    return pd.Series(out)


def compute_sltp_with_engine(engine, bar, side, sym):
    """Appel VRAI SLTPEngine. Return (sl_ticks, tp_ticks, mode, reject_reason)."""
    direction = 1 if side == "LONG" else -1
    sltp_input = convert_v4_bar_to_sltp_input(bar, sym)
    if sltp_input is None:
        return None
    try:
        result = engine.evaluate_single(sltp_input, direction)
    except Exception as e:
        return {"sl_ticks": 0, "tp_ticks": 0, "mode": "ERROR", "reject": str(e)[:100]}
    if result.valid:
        return {
            "sl_ticks": int(round(result.sl_ticks)),
            "tp_ticks": int(round(result.tp1_ticks)),
            "mode": "WALL_AWARE",
            "sl_wall": result.sl_wall,
            "tp_wall": result.tp1_wall,
            "rr": result.rr_ratio,
            "reject": "",
        }
    else:
        return {
            "sl_ticks": 0, "tp_ticks": 0, "mode": "REJECT",
            "reject": result.reject_reason,
        }


def compute_sltp_standard(sym, atr_normalized=1.0):
    """Fallback standard Bot 3 si SLTPEngine reject."""
    atr_mult = max(ATR_MULTIPLIER_CLAMP[0], min(ATR_MULTIPLIER_CLAMP[1], atr_normalized))
    sl = int(round(SL_BASE[sym] * atr_mult))
    tp = int(round(sl * TP_RR_RATIO))
    tp = min(tp, TP_CAP_TICKS[sym])
    return sl, tp


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


def check_combo(df, i, combo):
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


def run_voie_B_real_engine(df, sym, engine):
    """Voie B avec VRAI SLTPEngine."""
    n = len(df)
    last = -COOLDOWN
    trades = []
    combos_for_sym = [c for c in COMBOS_BOOSTED if c["applies_to"] in (sym, "BOTH")]
    n_engine_used = 0
    n_engine_reject = 0
    n_fallback = 0

    for i in range(50, n - FWD_BARS):
        if i - last < COOLDOWN:
            continue
        bar = df.iloc[i]
        fired = False

        # PRIORITY 1 : combos boostes
        for combo in combos_for_sym:
            if check_combo(df, i, combo):
                # SLTPEngine
                sltp = compute_sltp_with_engine(engine, bar, combo["side"], sym)
                if sltp is None: continue
                if sltp["mode"] == "WALL_AWARE":
                    sl, tp = sltp["sl_ticks"], sltp["tp_ticks"]
                    n_engine_used += 1
                else:
                    sl, tp = compute_sltp_standard(sym)
                    n_fallback += 1
                    if sltp["mode"] == "REJECT":
                        n_engine_reject += 1
                tr = simulate_trade(df, i, combo["side"], sl, tp, sym)
                if tr is None: continue
                tr.update({"signal": combo["name"], "side": combo["side"],
                           "bucket": "COMBO_BOOSTED", "sltp_mode": sltp["mode"]})
                trades.append(tr); last = i; fired = True; break
        if fired: continue

        # PRIORITY 2 : Sidak simples
        for lvl in SIDAK_LEVELS:
            if lvl["col"] not in df.columns: continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d) or abs(float(d)) > PROXIMITY_PCT_SIDAK: continue
            sltp = compute_sltp_with_engine(engine, bar, lvl["side"], sym)
            if sltp is None: continue
            if sltp["mode"] == "WALL_AWARE":
                sl, tp = sltp["sl_ticks"], sltp["tp_ticks"]
                n_engine_used += 1
            else:
                sl, tp = compute_sltp_standard(sym)
                n_fallback += 1
                if sltp["mode"] == "REJECT":
                    n_engine_reject += 1
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None: continue
            tr.update({"signal": lvl["name"], "side": lvl["side"],
                       "bucket": "SIDAK", "sltp_mode": sltp["mode"]})
            trades.append(tr); last = i; fired = True; break
        if fired: continue

        # PRIORITY 3 : heritage (filter regime ON, TP/SL standard)
        favor = regime_favor(bar)
        for lvl in HERITAGE_LEVELS:
            if lvl["col"] not in df.columns: continue
            d = bar.get(lvl["col"])
            if d is None or pd.isna(d) or abs(float(d)) > lvl["proximity"]: continue
            if favor != "NEUTRE":
                if (lvl["side"] == "LONG" and favor == "SHORT") or \
                   (lvl["side"] == "SHORT" and favor == "LONG"):
                    continue
            sl, tp = compute_sltp_standard(sym)
            tr = simulate_trade(df, i, lvl["side"], sl, tp, sym)
            if tr is None: continue
            tr.update({"signal": lvl["name"], "side": lvl["side"],
                       "bucket": "HERITAGE", "sltp_mode": "STANDARD"})
            trades.append(tr); last = i; break

    return trades, {"engine_used": n_engine_used, "engine_reject": n_engine_reject,
                     "fallback": n_fallback}


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


def report(label, sym, trades, stats=None):
    m = metrics(trades, sym)
    if m is None: return None
    n_combo = sum(1 for t in trades if t.get("bucket") == "COMBO_BOOSTED")
    n_sidak = sum(1 for t in trades if t.get("bucket") == "SIDAK")
    n_her = sum(1 for t in trades if t.get("bucket") == "HERITAGE")
    print(f"\n  {label} {sym} :")
    print(f"    N total = {m['n']} (COMBO_BOOST={n_combo}, SIDAK={n_sidak}, HERITAGE={n_her})")
    print(f"    WR={m['wr']*100:.1f}% PF={m['pf']:.2f} EV={m['ev']:+.2f}t total={m['total']:+.0f}t = ${m['$']:+.0f}")
    print(f"    PSR={m['psr']:.4f} WF+={m['pos_folds']}/12 MaxDD={m['max_dd']:.0f}t")
    if stats:
        n_total_sltp = stats['engine_used'] + stats['fallback']
        if n_total_sltp > 0:
            wall_rate = stats['engine_used'] / n_total_sltp * 100
            print(f"    SLTPEngine usage : {stats['engine_used']}/{n_total_sltp} "
                  f"({wall_rate:.1f}% wall-aware), {stats['engine_reject']} rejects, "
                  f"{stats['fallback']} fallback standard")
    if n_combo > 0:
        cb = [t for t in trades if t["bucket"] == "COMBO_BOOSTED"]
        cb_pnl = np.array([t["pnl"] for t in cb])
        n_wall = sum(1 for t in cb if t.get("sltp_mode") == "WALL_AWARE")
        print(f"    >>> COMBO_BOOST : n={len(cb_pnl)}, EV={cb_pnl.mean():+.2f}t, "
              f"total={cb_pnl.sum():+.0f}t, wall-aware={n_wall}/{len(cb_pnl)}")
    if n_sidak > 0:
        sk = [t for t in trades if t["bucket"] == "SIDAK"]
        sk_pnl = np.array([t["pnl"] for t in sk])
        n_wall = sum(1 for t in sk if t.get("sltp_mode") == "WALL_AWARE")
        print(f"    >>> SIDAK : n={len(sk_pnl)}, EV={sk_pnl.mean():+.2f}t, "
              f"total={sk_pnl.sum():+.0f}t, wall-aware={n_wall}/{len(sk_pnl)}")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    print(f"\n{'='*100}")
    print(f"=== ETAPE 1B — VRAI SLTPEngine importe (mia_sltp.py 941 LOC) ===")
    print(f"{'='*100}\n")

    for sym in ["ES", "NQ"]:
        df = load_v4(sym, args.months)
        if df.empty: continue
        print(f"\n{'='*100}")
        print(f"=== {sym} ({len(df)} bars) ===")
        print(f"{'='*100}")
        engine = SLTPEngine(symbol=sym)
        print(f"  SLTPEngine instancie : symbol={sym}, max_sl_ticks={engine.max_sl_ticks}, "
              f"max_sl_usd=${engine.max_sl_usd}, n_micros={engine.n_micros}")
        trades, stats = run_voie_B_real_engine(df, sym, engine)
        report("VOIE B (combos boostes P1 + Sidak P2 + heritage P3) — VRAI SLTPEngine", sym, trades, stats)


if __name__ == "__main__":
    main()
