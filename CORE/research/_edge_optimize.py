import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *

nq = load_trades("NQ")
nq = merge_with_confl(nq, load_confl("NQ"))

print("OPTIMISATION : retirer les niveaux marginaux (GEX_DN, VWAP_W_SD1D)")
print("=" * 100)

# Niveaux 'core' = IB_LOW + MQ_PUT_0DTE + MQ_HVL (les 3 PF>2 dans CAND2 mask)
CORE_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL"}

mask = nq["level_name"].isin(CORE_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("NQ CORE confl>=1 LONDON+US", nq, mask)
print("CORE confl>=1 L+US:", r)

# tpd ratio
print(f"  -> tpd = {r['tpd']:.2f} (cible >= 4)")

# Ajout de GEX_DN ou VWAP au CORE pour booster volume
mask = nq["level_name"].isin(CORE_NQ | {"GEX_DN"}) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("CORE+GEX_DN confl>=1 L+US", nq, mask)
print("CORE+GEX_DN:", r)

mask = nq["level_name"].isin(CORE_NQ | {"VWAP_W_SD1D"}) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("CORE+VWAP confl>=1 L+US", nq, mask)
print("CORE+VWAP:", r)

# Toutes confluences sur CORE only
mask = nq["level_name"].isin(CORE_NQ) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("CORE all confl L+US", nq, mask)
print("CORE all confl L+US (sans confluence filter):", r)

# Test retirer SHORT (peu nombreux dans CAND2)
mask = nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")
r = filter_test("CAND1 LONG only confl>=1 L+US", nq, mask)
print("CAND1 LONG only:", r)

# Decomposer par fold pour CAND2 vs CORE
print()
print("=" * 100)
print("CAND2 vs CORE : detail walk-forward 12-fold pour comparaison")
print("=" * 100)
KEEP_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}
import pandas as pd
import numpy as np

for label, mask in [
    ("CAND2 (5 levels)", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("CORE (3 levels)", nq["level_name"].isin(CORE_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
]:
    g = nq[mask].sort_values("entry_dt").reset_index(drop=True)
    n_folds = 12
    fold_size = len(g) // n_folds
    pfs = []
    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else len(g)
        chunk = g.iloc[start:end]
        p = chunk["pnl_ticks_net"].values
        w = p[p > 0].sum(); l = -p[p < 0].sum()
        pf = w / l if l > 0 else (5.0 if w > 0 else 0)
        pfs.append(round(min(pf, 10.0), 2))
    print(f"  {label}: folds = {pfs}")
    print(f"  -> PF med={np.median(pfs):.2f} min={min(pfs):.2f} max={max(pfs):.2f} std={np.std(pfs):.2f}")
