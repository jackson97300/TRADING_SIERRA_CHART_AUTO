import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *

nq = load_trades("NQ")
es = load_trades("ES")
nq = merge_with_confl(nq, load_confl("NQ"))
es = merge_with_confl(es, load_confl("ES"))

print("PHASE 2 - Exploration plus large : confl>=1, agregations multi-instrument, regime")
print()

results = []

# === Test relachement confluence : confl>=1 sur niveaux gardes
print("=" * 100)
print("Phase 2A : confl>=1 (relax)")
print("=" * 100)
KEEP_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}

tests = [
    ("NQ KEEP confl>=1", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1)),
    ("NQ KEEP confl>=1 LONDON+US", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("NQ KEEP confl>=1 LONDON+US LONG", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")),
    ("NQ IB+MQ+VWAP confl>=1 LONDON+US", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "VWAP_W_SD1D"}) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("NQ IB+MQ+VWAP confl>=1 LONDON+US LONG", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "VWAP_W_SD1D"}) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")),
    ("NQ IB+MQ+VWAP+GEX confl>=1 LONDON+US LONG", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "VWAP_W_SD1D", "GEX_DN"}) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")),
    ("NQ KEEP confl>=2 ASIA LONG", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2) & (nq["session_at_entry"] == "ASIA") & (nq["side"] == "LONG")),
    ("NQ ALL confl>=2 LONDON LONG", (nq["confl_count"] >= 2) & (nq["session_at_entry"] == "LONDON") & (nq["side"] == "LONG")),
    ("NQ ALL confl>=2 US_CASH LONG", (nq["confl_count"] >= 2) & (nq["session_at_entry"] == "US_CASH") & (nq["side"] == "LONG")),
    ("NQ KEEP confl>=2 ALL_SESSIONS LONG", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2) & (nq["side"] == "LONG")),
]
for label, mask in tests:
    r = filter_test(label, nq, mask)
    if r:
        results.append(r)
        print(label.ljust(50), "| n=", str(r["n"]).rjust(5), "| tpd=", str(r["tpd"]).rjust(5), "| wr=", str(r["wr"]).rjust(5), "| PF=", str(r["pf"]).rjust(5), "| wfmed=", r["wf_pf_med"], "| wfmin=", r["wf_pf_min"], "| stab=", r["wf_stable"])

# === Combinaison NQ + ES : additionner tpd
print()
print("=" * 100)
print("Phase 2B : Combinaisons NQ + ES (additionner tpd avec configs propres)")
print("=" * 100)

import pandas as pd

# Best config NQ : IB+MQ+VWAP confl>=2 LONDON+US LONG
mask_nq = nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "VWAP_W_SD1D"}) & (nq["confl_count"] >= 2) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")
g_nq = nq[mask_nq].copy()
g_nq["instr"] = "NQ"
g_nq["tick_value_usd"] = 0.50  # MNQ micro

# Tester ES IB_LOW seul (PF marginal) pour ajouter du volume
mask_es = (es["level_name"] == "IB_LOW") & (es["confl_count"] >= 2) & (es["session_at_entry"] == "US_CASH") & (es["side"] == "LONG")
g_es = es[mask_es].copy()
g_es["instr"] = "ES"
g_es["tick_value_usd"] = 1.25  # MES micro

print()
print("NQ subset metrics:")
m_nq = metrics(g_nq); print("  ", m_nq)
print("ES subset metrics:")
m_es = metrics(g_es); print("  ", m_es)
print()

# Combinaison : sum trades, recompute pf in dollars
combined = pd.concat([g_nq, g_es], ignore_index=True)
combined["pnl_usd"] = combined["pnl_ticks_net"] * combined["tick_value_usd"]
n = len(combined)
wins = combined.loc[combined["pnl_usd"] > 0, "pnl_usd"].sum()
losses = -combined.loc[combined["pnl_usd"] < 0, "pnl_usd"].sum()
pf = (wins / losses) if losses > 0 else float("inf")
wr = (combined["pnl_usd"] > 0).mean() * 100
n_unique_days = combined["date"].nunique()
tpd = n / n_unique_days
print(f"COMBINED NQ+ES: n={n}, n_days={n_unique_days}, tpd={tpd:.2f}, wr={wr:.1f}%, PF_usd={pf:.2f}")

# Walk-forward sur combined
combined = combined.sort_values("entry_dt").reset_index(drop=True)
n_folds = 12
fold_size = len(combined) // n_folds
pfs = []
for i in range(n_folds):
    start = i * fold_size
    end = start + fold_size if i < n_folds - 1 else len(combined)
    chunk = combined.iloc[start:end]
    w = chunk.loc[chunk["pnl_usd"] > 0, "pnl_usd"].sum()
    l = -chunk.loc[chunk["pnl_usd"] < 0, "pnl_usd"].sum()
    pfs.append((w / l) if l > 0 else (5.0 if w > 0 else 0))
pfs = np.array([min(p, 5.0) for p in pfs])
print(f"  WF: med={np.median(pfs):.2f}, min={pfs.min():.2f}, max={pfs.max():.2f}, std={pfs.std():.2f}")
print(f"  WF stability: {pfs.std()/np.median(pfs):.2f}")

# === Phase 2C : essayer ES IB_LOW + NQ ALL KEEP
print()
print("=" * 100)
print("Phase 2C : NQ KEEP confl>=2 + ES IB_LOW confl>=2")
print("=" * 100)

mask_nq2 = nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2)
g_nq2 = nq[mask_nq2].copy(); g_nq2["instr"] = "NQ"; g_nq2["tick_value_usd"] = 0.50

mask_es2 = (es["level_name"] == "IB_LOW") & (es["confl_count"] >= 2)
g_es2 = es[mask_es2].copy(); g_es2["instr"] = "ES"; g_es2["tick_value_usd"] = 1.25

combined2 = pd.concat([g_nq2, g_es2], ignore_index=True)
combined2["pnl_usd"] = combined2["pnl_ticks_net"] * combined2["tick_value_usd"]
n = len(combined2)
wins = combined2.loc[combined2["pnl_usd"] > 0, "pnl_usd"].sum()
losses = -combined2.loc[combined2["pnl_usd"] < 0, "pnl_usd"].sum()
pf = (wins / losses) if losses > 0 else float("inf")
wr = (combined2["pnl_usd"] > 0).mean() * 100
n_unique_days = combined2["date"].nunique()
tpd = n / n_unique_days
print(f"COMBINED2 NQ_KEEP+ES_IB_LOW confl>=2: n={n}, n_days={n_unique_days}, tpd={tpd:.2f}, wr={wr:.1f}%, PF_usd={pf:.2f}")

combined2 = combined2.sort_values("entry_dt").reset_index(drop=True)
fold_size = len(combined2) // 12
pfs = []
for i in range(12):
    start = i * fold_size
    end = start + fold_size if i < 11 else len(combined2)
    chunk = combined2.iloc[start:end]
    w = chunk.loc[chunk["pnl_usd"] > 0, "pnl_usd"].sum()
    l = -chunk.loc[chunk["pnl_usd"] < 0, "pnl_usd"].sum()
    pfs.append((w / l) if l > 0 else (5.0 if w > 0 else 0))
pfs = np.array([min(p, 5.0) for p in pfs])
print(f"  WF: med={np.median(pfs):.2f}, min={pfs.min():.2f}, max={pfs.max():.2f}, std={pfs.std():.2f}")
print(f"  WF stability ratio: {pfs.std()/np.median(pfs):.2f}")
print(f"  Folds: {[round(p, 2) for p in pfs]}")
