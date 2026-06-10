import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *
import pandas as pd
import numpy as np

nq = load_trades("NQ")
nq = merge_with_confl(nq, load_confl("NQ"))

KEEP_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}

print("=" * 100)
print("DECONSTRUCTION : qu'est-ce qui drive l'edge?")
print("=" * 100)

# Test 1 : KEEP_NQ + confl=0 LONDON+US (sans confluence)
mask = nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] == 0) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("NQ KEEP confl==0 LONDON+US", nq, mask)
print("confl==0:", r)

# Test 2 : KEEP_NQ + confl>=1 + ALL_SESSIONS (sans filtrage session)
mask = nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1)
r = filter_test("NQ KEEP confl>=1 ALL_SESSIONS", nq, mask)
print("confl>=1 ALL:", r)

# Test 3 : tous niveaux + confl>=1 + LONDON+US (sans filtrage levels)
mask = (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("NQ ALL_LEVELS confl>=1 LONDON+US", nq, mask)
print("ALL_LEVELS confl>=1 L+US:", r)

# Test 4 : KEEP_NQ + ALL confl + LONDON+US (sans confluence filter)
mask = nq["level_name"].isin(KEEP_NQ) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
r = filter_test("NQ KEEP all confl LONDON+US", nq, mask)
print("KEEP all confl L+US:", r)

# Test 5 : NQ KEEP confl==0 ALL_SESSIONS
mask = nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] == 0)
r = filter_test("NQ KEEP confl==0 ALL_SESSIONS", nq, mask)
print("KEEP confl==0 ALL:", r)

# Decomposition par level individuel sur CAND2 mask
print()
print("=" * 100)
print("Decomposition par niveau (CAND2 = KEEP confl>=1 LONDON+US)")
print("=" * 100)
mask_base = nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])
g_base = nq[mask_base]
for lvl in KEEP_NQ:
    g = g_base[g_base["level_name"] == lvl]
    if len(g) >= 30:
        p = g["pnl_ticks_net"].values
        w = p[p > 0].sum(); l = -p[p < 0].sum()
        pf = w / l if l > 0 else 5.0
        print(f"  {lvl:15} | n={len(g):4d} | PF={pf:.2f} | WR={(p>0).mean()*100:.1f}% | avg={p.mean():.1f}t")

# Decomposition par session
print()
print("Decomposition par session (CAND2 mask)")
for sess in ["LONDON", "US_CASH"]:
    g = g_base[g_base["session_at_entry"] == sess]
    p = g["pnl_ticks_net"].values
    w = p[p > 0].sum(); l = -p[p < 0].sum()
    pf = w / l if l > 0 else 5.0
    print(f"  {sess:10} | n={len(g):4d} | PF={pf:.2f} | WR={(p>0).mean()*100:.1f}% | avg={p.mean():.1f}t")
