import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *
import pandas as pd
import numpy as np
from scipy import stats as scstats

nq = load_trades("NQ")
nq = merge_with_confl(nq, load_confl("NQ"))

print("=" * 100)
print("VALIDATION FINALE : CORE+VWAP NQ confl>=1 LONDON+US")
print("Levels: IB_LOW + MQ_PUT_0DTE + MQ_HVL + VWAP_W_SD1D")
print("=" * 100)

CORE_PLUS_VWAP = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "VWAP_W_SD1D"}
mask = nq["level_name"].isin(CORE_PLUS_VWAP) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
g = nq[mask].sort_values("entry_dt").reset_index(drop=True)

print(f"n trades: {len(g)}")
print(f"date range: {g['entry_dt'].min()} -> {g['entry_dt'].max()}")
print(f"unique trading days: {g['date'].nunique()}")
print(f"trades/day: {len(g) / g['date'].nunique():.2f}")

p = g["pnl_ticks_net"].values
wins = p[p > 0].sum(); losses = -p[p < 0].sum()
pf = wins / losses if losses > 0 else float("inf")
wr = (p > 0).mean() * 100
print(f"WR: {wr:.1f}%")
print(f"PF: {pf:.2f}")
print(f"avg ticks net: {p.mean():.2f}")
print(f"median ticks net: {np.median(p):.2f}")

# DSR Bailey 2014
def deflated_sharpe(returns, n_trials):
    sr = returns.mean() / returns.std() * np.sqrt(252)
    skew = scstats.skew(returns); kurt = scstats.kurtosis(returns)
    n = len(returns)
    se = np.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1))
    e_max_sr = (1 - 0.5772) * scstats.norm.ppf(1 - 1.0 / n_trials) + 0.5772 * scstats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    dsr = scstats.norm.cdf((sr - e_max_sr * se) / se) if se > 0 else 0
    return dict(sr=round(sr, 3), dsr=round(dsr, 3), n=n)

daily_pnl = g.groupby("date")["pnl_ticks_net"].sum().values
print()
print(f"DSR Bailey 2014 (n_trials=50): {deflated_sharpe(daily_pnl, 50)}")
print(f"DSR Bailey 2014 (n_trials=100): {deflated_sharpe(daily_pnl, 100)}")
print(f"DSR Bailey 2014 (n_trials=200): {deflated_sharpe(daily_pnl, 200)}")

# Conc top 3, top 5 winners
top_wins = sorted(p[p > 0].tolist(), reverse=True)
print()
print(f"Top 3 winners: {top_wins[:3]} (sum={sum(top_wins[:3]):.0f}t)")
print(f"Top 5 winners: {top_wins[:5]} (sum={sum(top_wins[:5]):.0f}t)")
print(f"Total wins: {wins:.0f}t")
print(f"Conc top3/wins: {sum(top_wins[:3])/wins:.3f} (Lopez seuil <0.33)")
print(f"PF without top3: {(wins - sum(top_wins[:3]))/losses:.2f}")
print(f"PF without top5: {(wins - sum(top_wins[:5]))/losses:.2f}")

# Walk-forward 12 fold detail
print()
print("WALK-FORWARD 12-FOLD detail:")
n_folds = 12
fold_size = len(g) // n_folds
folds = []
for i in range(n_folds):
    start = i * fold_size
    end = start + fold_size if i < n_folds - 1 else len(g)
    chunk = g.iloc[start:end]
    p_ = chunk["pnl_ticks_net"].values
    w_ = p_[p_ > 0].sum(); l_ = -p_[p_ < 0].sum()
    pf_ = w_ / l_ if l_ > 0 else 5.0
    folds.append({
        "fold": i+1,
        "start": chunk["entry_dt"].iloc[0].strftime("%Y-%m-%d"),
        "end": chunk["entry_dt"].iloc[-1].strftime("%Y-%m-%d"),
        "n": len(chunk), "pf": round(pf_, 2),
        "wr": round((p_ > 0).mean() * 100, 1),
    })
for f in folds:
    print(f"  {f}")

pfs = [f["pf"] for f in folds]
print(f"  PF stats: med={np.median(pfs):.2f}, min={min(pfs):.2f}, max={max(pfs):.2f}, std={np.std(pfs):.2f}")
print(f"  Folds PF>=1.0: {sum(1 for p_ in pfs if p_ >= 1.0)}/{len(pfs)}")
print(f"  Folds PF>=1.3: {sum(1 for p_ in pfs if p_ >= 1.3)}/{len(pfs)}")
print(f"  Folds PF>=1.5: {sum(1 for p_ in pfs if p_ >= 1.5)}/{len(pfs)}")

# Stress costs +1.5t
print()
print("Stress test : +1.5 ticks slippage additionnels")
g["pnl_stress"] = g["pnl_ticks_net"] - 1.5
ps = g["pnl_stress"].values
ws = ps[ps > 0].sum(); ls = -ps[ps < 0].sum()
print(f"  PF apres +1.5t cost: {ws/ls:.2f} (baseline {pf:.2f})")
print(f"  WR apres stress: {(ps > 0).mean() * 100:.1f}%")

# Stress costs +3t (paranoid)
g["pnl_paranoid"] = g["pnl_ticks_net"] - 3.0
pp = g["pnl_paranoid"].values
wp = pp[pp > 0].sum(); lp = -pp[pp < 0].sum()
print(f"  PF apres +3.0t cost: {wp/lp:.2f}")

# Monthly stability
print()
print("Stabilite mensuelle:")
g["month"] = g["entry_dt"].dt.to_period("M")
months_ok = 0; months_neg = 0; total = 0
for m, gm in g.groupby("month"):
    if len(gm) < 5: continue
    p_ = gm["pnl_ticks_net"].values
    w_ = p_[p_ > 0].sum(); l_ = -p_[p_ < 0].sum()
    pf_ = w_ / l_ if l_ > 0 else 5.0
    total += 1
    if pf_ >= 1.3: months_ok += 1
    if pf_ < 1.0: months_neg += 1
    print(f"  {m}: n={len(gm):3d}, PF={pf_:.2f}, WR={(p_ > 0).mean()*100:.1f}%")
print(f"  Months PF>=1.3: {months_ok}/{total}, Months PF<1.0: {months_neg}/{total}")

# Decomposition par level pour verif robustesse
print()
print("Decomposition par level (CORE+VWAP):")
for lvl in CORE_PLUS_VWAP:
    gl = g[g["level_name"] == lvl]
    if len(gl) >= 30:
        p_ = gl["pnl_ticks_net"].values
        w_ = p_[p_ > 0].sum(); l_ = -p_[p_ < 0].sum()
        pf_ = w_ / l_ if l_ > 0 else 5.0
        print(f"  {lvl:15} | n={len(gl):4d} | PF={pf_:.2f} | WR={(p_ > 0).mean()*100:.1f}% | avg={p_.mean():.1f}t")

# Decomposition par session
print()
print("Decomposition par session (CORE+VWAP):")
for sess in ["LONDON", "US_CASH"]:
    gs = g[g["session_at_entry"] == sess]
    p_ = gs["pnl_ticks_net"].values
    w_ = p_[p_ > 0].sum(); l_ = -p_[p_ < 0].sum()
    pf_ = w_ / l_ if l_ > 0 else 5.0
    print(f"  {sess:10} | n={len(gs):4d} | PF={pf_:.2f} | WR={(p_ > 0).mean()*100:.1f}% | avg={p_.mean():.1f}t")

# Side
print()
print("Decomposition par side (CORE+VWAP):")
for side in ["LONG", "SHORT"]:
    gs = g[g["side"] == side]
    if len(gs) >= 30:
        p_ = gs["pnl_ticks_net"].values
        w_ = p_[p_ > 0].sum(); l_ = -p_[p_ < 0].sum()
        pf_ = w_ / l_ if l_ > 0 else 5.0
        print(f"  {side:10} | n={len(gs):4d} | PF={pf_:.2f} | WR={(p_ > 0).mean()*100:.1f}%")
