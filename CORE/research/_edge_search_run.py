import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *

nq = load_trades("NQ")
es = load_trades("ES")
nq = merge_with_confl(nq, load_confl("NQ"))
es = merge_with_confl(es, load_confl("ES"))

n_days_nq = nq["date"].nunique()
n_days_es = es["date"].nunique()
print("NQ", len(nq), "trades /", n_days_nq, "jours =", round(len(nq)/n_days_nq,1), "/jour")
print("ES", len(es), "trades /", n_days_es, "jours =", round(len(es)/n_days_es,1), "/jour")
print()

results = []
KEEP_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}
KEEP_ES = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}

print("=" * 100)
print("NQ EXPLORATION")
print("=" * 100)

tests_nq = [
    ("NQ KEEP all", nq["level_name"].isin(KEEP_NQ)),
    ("NQ KEEP confl>=2", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2)),
    ("NQ KEEP confl>=3", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 3)),
    ("NQ KEEP confl>=2 LONDON+US", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("NQ KEEP confl>=2 LONDON+US LONG", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")),
    ("NQ KEEP confl>=2 LONDON+US rvol>=1", nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["rvol_at_entry"] >= 1.0)),
    ("NQ IB_LOW only confl>=2", (nq["level_name"] == "IB_LOW") & (nq["confl_count"] >= 2)),
    ("NQ IB_LOW+MQ_PUT confl>=2", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE"}) & (nq["confl_count"] >= 2)),
    ("NQ IB_LOW+MQ_PUT+GEX_DN confl>=2", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "GEX_DN"}) & (nq["confl_count"] >= 2)),
    ("NQ IB+MQ+VWAP confl>=2 LONDON+US", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "VWAP_W_SD1D"}) & (nq["confl_count"] >= 2) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("NQ IB+MQ+VWAP+GEX confl>=2 LONDON+US", nq["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE", "VWAP_W_SD1D", "GEX_DN"}) & (nq["confl_count"] >= 2) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("NQ ALL confl>=2 LONG", (nq["confl_count"] >= 2) & (nq["side"] == "LONG")),
    ("NQ ALL confl>=3 LONG", (nq["confl_count"] >= 3) & (nq["side"] == "LONG")),
    ("NQ ALL confl>=2 SHORT", (nq["confl_count"] >= 2) & (nq["side"] == "SHORT")),
    ("NQ ALL confl>=2 US_CASH", (nq["confl_count"] >= 2) & (nq["session_at_entry"] == "US_CASH")),
    ("NQ ALL confl>=2 LONDON", (nq["confl_count"] >= 2) & (nq["session_at_entry"] == "LONDON")),
    ("NQ ALL confl>=2 ASIA", (nq["confl_count"] >= 2) & (nq["session_at_entry"] == "ASIA")),
    ("NQ ALL confl>=2 LONG L+US", (nq["confl_count"] >= 2) & (nq["side"] == "LONG") & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("NQ ALL confl>=2 LONG L+US rvol>=1.0", (nq["confl_count"] >= 2) & (nq["side"] == "LONG") & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["rvol_at_entry"] >= 1.0)),
    ("NQ ALL confl>=2 LONG L+US rvol>=1.2", (nq["confl_count"] >= 2) & (nq["side"] == "LONG") & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["rvol_at_entry"] >= 1.2)),
    ("NQ ALL confl>=2 LONG L+US rvol>=1.5", (nq["confl_count"] >= 2) & (nq["side"] == "LONG") & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["rvol_at_entry"] >= 1.5)),
]

for label, mask in tests_nq:
    r = filter_test(label, nq, mask)
    if r:
        results.append(r)
        print(label.ljust(45), "| n=", str(r["n"]).rjust(5), "| tpd=", str(r["tpd"]).rjust(5), "| wr=", str(r["wr"]).rjust(5), "| PF=", str(r["pf"]).rjust(5), "| wfmed=", r["wf_pf_med"], "| wfmin=", r["wf_pf_min"], "| stab=", r["wf_stable"])

print()
print("=" * 100)
print("ES EXPLORATION")
print("=" * 100)

tests_es = [
    ("ES KEEP all", es["level_name"].isin(KEEP_ES)),
    ("ES KEEP confl>=2", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 2)),
    ("ES KEEP confl>=3", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 3)),
    ("ES IB+MQ confl>=2", es["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE"}) & (es["confl_count"] >= 2)),
    ("ES IB+MQ confl>=3", es["level_name"].isin({"IB_LOW", "MQ_PUT_0DTE"}) & (es["confl_count"] >= 3)),
    ("ES KEEP confl>=2 US_CASH", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 2) & (es["session_at_entry"] == "US_CASH")),
    ("ES KEEP confl>=2 LONG", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 2) & (es["side"] == "LONG")),
    ("ES KEEP confl>=2 LONG US_CASH", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 2) & (es["side"] == "LONG") & (es["session_at_entry"] == "US_CASH")),
    ("ES KEEP confl>=3 LONG US_CASH", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 3) & (es["side"] == "LONG") & (es["session_at_entry"] == "US_CASH")),
    ("ES KEEP confl>=2 LONG L+US", es["level_name"].isin(KEEP_ES) & (es["confl_count"] >= 2) & (es["side"] == "LONG") & es["session_at_entry"].isin(["LONDON", "US_CASH"])),
]
for label, mask in tests_es:
    r = filter_test(label, es, mask)
    if r:
        results.append(r)
        print(label.ljust(45), "| n=", str(r["n"]).rjust(5), "| tpd=", str(r["tpd"]).rjust(5), "| wr=", str(r["wr"]).rjust(5), "| PF=", str(r["pf"]).rjust(5), "| wfmed=", r["wf_pf_med"], "| wfmin=", r["wf_pf_min"], "| stab=", r["wf_stable"])

out_df = pd.DataFrame(results)
out_path = ROOT / "DATA/BACKTEST/BOT3/edge_search_results.csv"
out_df.to_csv(out_path, index=False)
print()
print("[OK] Saved", len(out_df), "configs to", out_path)

print()
print("=" * 100)
print("CONFIGURATIONS SATISFAISANT tpd>=4 ET pf>=1.3 ET wf_stable")
print("=" * 100)
qual = out_df[(out_df["tpd"] >= 4.0) & (out_df["pf"] >= 1.3) & (out_df["wf_stable"] == True)]
if len(qual):
    print(qual[["label", "n", "tpd", "wr", "pf", "wf_pf_med", "wf_pf_min", "wf_stable"]].to_string())
else:
    print("AUCUNE CONFIG STABLE.")

print()
print("Top 10 par PF avec tpd>=2:")
top = out_df[out_df["tpd"] >= 2.0].nlargest(10, "pf")
print(top[["label", "n", "tpd", "wr", "pf", "wf_pf_med", "wf_pf_min", "wf_stable"]].to_string())
print()
print("Top 10 par tpd avec PF>=1.2:")
top2 = out_df[(out_df["tpd"] >= 2.0) & (out_df["pf"] >= 1.2)].nlargest(10, "tpd")
print(top2[["label", "n", "tpd", "wr", "pf", "wf_pf_med", "wf_pf_min", "wf_stable"]].to_string())
