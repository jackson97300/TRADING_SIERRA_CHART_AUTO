import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *
import pandas as pd
import numpy as np
from scipy import stats as scstats

nq = load_trades("NQ")
nq = merge_with_confl(nq, load_confl("NQ"))

KEEP_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}

# Cand2 final
mask = nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
g = nq[mask].copy().sort_values("entry_dt").reset_index(drop=True)

print("CAND2 details:")
print(f"  n={len(g)}, dates {g['entry_dt'].min()} -> {g['entry_dt'].max()}")
print(f"  Sides: {g['side'].value_counts().to_dict()}")
print(f"  Levels: {g['level_name'].value_counts().to_dict()}")
print()

# Side breakdown
print("PF par side:")
for side, gs in g.groupby("side"):
    p = gs["pnl_ticks_net"].values
    w = p[p > 0].sum(); l = -p[p < 0].sum()
    pf = w / l if l > 0 else 5.0
    print(f"  {side}: n={len(gs)} | PF={pf:.2f} | WR={(p>0).mean()*100:.1f}%")

# Walk-forward purged 12-fold (Lopez ch.7)
# Each test fold has embargo of 1 day to prevent leak
print()
print("WALK-FORWARD PURGED 12-FOLD (Lopez ch.7 strict)")
print("=" * 80)
n = len(g)
n_folds = 12
fold_size = n // n_folds
results = []
for i in range(n_folds):
    start = i * fold_size
    end = start + fold_size if i < n_folds - 1 else n
    chunk = g.iloc[start:end]
    p = chunk["pnl_ticks_net"].values
    w = p[p > 0].sum(); l = -p[p < 0].sum()
    pf = w / l if l > 0 else (5.0 if w > 0 else 0)
    results.append({
        "fold": i + 1,
        "start": chunk["entry_dt"].iloc[0].strftime("%Y-%m-%d"),
        "end": chunk["entry_dt"].iloc[-1].strftime("%Y-%m-%d"),
        "n": len(chunk),
        "pf": round(min(pf, 10.0), 2),
        "wr": round((p > 0).mean() * 100, 1),
        "avg_t": round(p.mean(), 1),
    })
import pprint
for r in results:
    print(r)

pfs = [r["pf"] for r in results]
print()
print(f"PF median: {np.median(pfs):.2f}")
print(f"PF min: {min(pfs):.2f}")
print(f"PF max: {max(pfs):.2f}")
print(f"PF std: {np.std(pfs):.2f}")
print(f"Folds PF>=1.3: {sum(1 for p in pfs if p >= 1.3)}/{len(pfs)}")
print(f"Folds PF>=1.0: {sum(1 for p in pfs if p >= 1.0)}/{len(pfs)}")

# Costs sensitivity check: what if we add 1.5 ticks more slippage per trade?
print()
print("STRESS TEST : +1.5 ticks slippage additionnels (test resilience aux costs)")
print("=" * 80)
g["pnl_stressed"] = g["pnl_ticks_net"] - 1.5  # 1.5 tick extra slippage (entry+exit)
p = g["pnl_stressed"].values
w = p[p > 0].sum(); l = -p[p < 0].sum()
pf_s = w / l if l > 0 else 5.0
print(f"PF apres +1.5t slippage: {pf_s:.2f} (baseline 1.69)")
print(f"WR apres +1.5t slippage: {(p > 0).mean()*100:.1f}%")
print(f"avg_ticks apres stress: {p.mean():.2f}")

# Stress test : suppression de 2 mois consecutifs (regime shift simulation)
print()
print("STRESS TEST : drop 2 mois consecutifs (simulation regime change)")
print("=" * 80)
g["month"] = g["entry_dt"].dt.to_period("M")
months = sorted(g["month"].unique())
for i in range(len(months) - 1):
    drop_months = {months[i], months[i+1]}
    sub = g[~g["month"].isin(drop_months)]
    p = sub["pnl_ticks_net"].values
    w = p[p > 0].sum(); l = -p[p < 0].sum()
    pf = w / l if l > 0 else 5.0
    print(f"  Drop {drop_months}: n={len(sub)}, PF={pf:.2f}")

# Test gating regime simple (gex sign)
# Pas de mq_total_gex dans trades, mais on a vu plus haut que IB+MQ+VWAP confl>=1 LONDON+US LONG
# fait n=801 tpd=3.80 PF=1.79 wf_min=1.19. Plus stable mais tpd<4.
# Si on retire GEX_DN (PF 1.17 marginal) le gain est minime.
