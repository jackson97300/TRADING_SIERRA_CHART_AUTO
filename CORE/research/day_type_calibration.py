"""Calibration seuils day_type NQ Sierra DMP."""
import json, os
from glob import glob
from datetime import datetime, timezone
import numpy as np
import pandas as pd

DATA_DIR = r"D:/TRADING_SIERRA_CHART_AUTO/DATA/NQ"
TICK_NQ = 0.25
DALTON = np.array([0.08, 0.30, 0.42, 0.10, 0.10])
RTH_START = 9 * 60 + 30
RTH_END = 16 * 60
IB_END = 10 * 60 + 30
# Grid combinant le grid initial du brief + extension realiste pour NQ moderne
GRID_NT = [0.30, 0.40, 0.50, 0.60, 0.70, 1.20, 1.40, 1.50, 1.60, 1.70, 1.80]
GRID_NM = [1.0, 1.25, 1.5, 1.75, 2.0, 2.10, 2.20, 2.40]
GRID_TM = [0.30, 0.40, 0.50, 0.60, 0.75, 0.85, 1.0, 1.25, 1.50]
LBL = ["NonTrend", "Normal", "NormVar", "Neutral", "Trend"]
NEU_C = 0.35

def is_dst(dt):
    mo, dy = dt.month, dt.day
    tw = (dt.weekday() + 1) % 7
    if 4 <= mo <= 10: return True
    if mo == 3 and (dy - tw) >= 8: return True
    if mo == 11 and (dy - tw) < 1: return True
    return False

def ts_to_min_et(ts_ms):
    d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    off = 4 if is_dst(d) else 5
    h = (d.hour - off + 24) % 24
    return h * 60 + d.minute

def load_day(p):
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for ln in f:
            try: rows.append(json.loads(ln))
            except Exception: continue
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["min_et"] = df["ts"].apply(ts_to_min_et)
    return df

def load_all(start="20260508"):
    out = {}
    for fp in sorted(glob(os.path.join(DATA_DIR, "*_NQ.jsonl"))):
        fn = os.path.basename(fp)
        ds = fn[:8]
        if fn.replace(".jsonl", "") != ds + "_NQ": continue
        if ds < start: continue
        df = load_day(fp)
        if not df.empty: out[ds] = df
    return out

def extract(df):
    rth = df[(df["min_et"] >= RTH_START) & (df["min_et"] < RTH_END)].copy()
    if rth.empty: return None
    atr = rth["atr"].dropna().median()
    if not np.isfinite(atr) or atr <= 0: return None
    ibw = rth[rth["min_et"] < IB_END]
    if ibw.empty: return None
    has_bar = "bar_high" in ibw.columns and "bar_low" in ibw.columns
    if has_bar:
        ibh = ibw["bar_high"].max(); ibl = ibw["bar_low"].min()
        sh = rth["bar_high"].max(); sl = rth["bar_low"].min()
    else:
        ibh = ibw["price"].max(); ibl = ibw["price"].min()
        sh = rth["price"].max(); sl = rth["price"].min()
    if not (np.isfinite(ibh) and np.isfinite(ibl) and ibh > ibl): return None
    ibr = ibh - ibl
    ib_atr = (ibr / TICK_NQ) / atr
    cl = rth.iloc[-1]["price"]
    cdt = rth.iloc[-1].get("day_type")
    cdi = int(cdt) if cdt is not None and 0 <= cdt <= 4 else 2
    return dict(ib_high=ibh, ib_low=ibl, ib_range=ibr, ib_atr=ib_atr,
                sess_high=sh, sess_low=sl, close=cl, atr_ticks=atr,
                ext_up=max(0, sh - ibh), ext_dn=max(0, ibl - sl),
                current_dt=cdi)

def classify(m, nt, nm, tm):
    ia, ir = m["ib_atr"], m["ib_range"]
    eu, ed = m["ext_up"], m["ext_dn"]
    sh, sl, cl = m["sess_high"], m["sess_low"], m["close"]
    if ia < nt: return 0
    su = eu > ir * tm; sd = ed > ir * tm
    ea = eu > 0; eb = ed > 0
    if (su and not eb) or (sd and not ea): return 4
    if ea and eb:
        rg = sh - sl
        if rg > 0:
            ps = (cl - sl) / rg
            if (0.5 - NEU_C) <= ps <= (0.5 + NEU_C): return 3
    if ia >= nm:
        if max(eu, ed) < ir * 0.20: return 1
    return 2

def dist_for(metrics, nt, nm, tm):
    if not metrics: return np.zeros(5)
    c = np.zeros(5, dtype=int)
    for m in metrics: c[classify(m, nt, nm, tm)] += 1
    return c / c.sum()

def l2(d): return float(np.linalg.norm(d - DALTON))
def degen(d, t=0.045): return bool(np.any(d < t))

def sweep(metrics):
    rs = []
    for nt in GRID_NT:
        for nm in GRID_NM:
            for tm in GRID_TM:
                d = dist_for(metrics, nt, nm, tm)
                rs.append(dict(nontrend=nt, normal=nm, trend_mult=tm,
                               p_nontrend=d[0], p_normal=d[1], p_normvar=d[2],
                               p_neutral=d[3], p_trend=d[4],
                               l2_dalton=l2(d), degenerate=degen(d)))
    return pd.DataFrame(rs).sort_values("l2_dalton").reset_index(drop=True)

def main():
    print("=" * 80)
    print("CALIBRATION SEUILS day_type NQ Sierra DMP")
    print("=" * 80)
    days = load_all("20260508")
    print(f"\nJours charges : {len(days)} ({min(days)} -> {max(days)})")
    metrics = []
    for ds, df in days.items():
        m = extract(df)
        if m is None:
            print(f"  SKIP {ds}"); continue
        m["date"] = ds
        metrics.append(m)
    print(f"Jours retenus : {len(metrics)}")
    if len(metrics) < 10:
        print(f"FLAG : {len(metrics)} jours statistiquement fragile")

    db = dist_for(metrics, 0.15, 0.80, 2.0)
    print("\n-- DISTRIBUTION BASELINE (seuils actuels 0.15/0.80/2.0) --")
    for i, l in enumerate(LBL):
        print(f"  {l:9s}: {db[i]*100:5.1f}%  (Dalton {DALTON[i]*100:.0f}%)")
    print(f"  L2 distance : {l2(db):.4f}")

    ac = np.zeros(5, dtype=int)
    for m in metrics: ac[m["current_dt"]] += 1
    ad = ac / max(1, ac.sum())
    print("\n-- DISTRIBUTION day_type ACTUEL JSONL (C++ live, EOD) --")
    for i, l in enumerate(LBL):
        print(f"  {l:9s}: {ad[i]*100:5.1f}%")

    ibas = np.array([m["ib_atr"] for m in metrics])
    print(f"\n-- STATS ib_atr (RTH IB) --")
    print(f"  median {np.median(ibas):.3f}  mean {np.mean(ibas):.3f}  min {ibas.min():.3f}  max {ibas.max():.3f}")

    res = sweep(metrics)
    t5c = res[~res["degenerate"]].head(5)
    print("\n-- TOP 5 (no degenerate <4.5%) --")
    if len(t5c) == 0:
        print("AUCUNE combinaison sans bucket < 3% sur ce grid !")
        show = res.head(5)
    else:
        show = t5c
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(show.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print("\n-- TOP 5 ALL (degenerate inclus) --")
    print(res.head(5).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out = r"D:/TRADING_SIERRA_CHART_AUTO/DOCS/day_type_sweep_full.csv"
    res.to_csv(out, index=False)
    print(f"\nCSV ecrit : {out}")

    best = show.iloc[0] if len(show) else res.iloc[0]
    print(f"\n-- BEST : NT={best['nontrend']} NM={best['normal']} TM={best['trend_mult']} --")
    print(f"  NT={best['p_nontrend']*100:.1f}% NM={best['p_normal']*100:.1f}% NV={best['p_normvar']*100:.1f}% "
          f"Neu={best['p_neutral']*100:.1f}% Tr={best['p_trend']*100:.1f}%  L2={best['l2_dalton']:.4f}")

    print("\n-- BREAKDOWN PAR JOUR --")
    print(f"{'date':10s} {'ib_atr':>7s} {'ib_rg_p':>8s} {'ext_up':>7s} {'ext_dn':>7s} {'baseline':>10s} {'best':>10s}")
    for m in metrics:
        db_ = classify(m, 0.15, 0.80, 2.0)
        bs_ = classify(m, best["nontrend"], best["normal"], best["trend_mult"])
        print(f"{m['date']:10s} {m['ib_atr']:7.3f} {m['ib_range']:8.2f} "
              f"{m['ext_up']:7.2f} {m['ext_dn']:7.2f} {LBL[db_]:>10s} {LBL[bs_]:>10s}")
    return res, metrics, best

if __name__ == "__main__":
    main()
