import sys
sys.path.insert(0, "CORE/research")
from _edge_search_lib import *
import pandas as pd
import numpy as np
from scipy import stats as scstats

nq = load_trades("NQ")
nq = merge_with_confl(nq, load_confl("NQ"))

print("=" * 100)
print("VALIDATION RIGOUREUSE : top 3 candidats stables")
print("=" * 100)

KEEP_NQ = {"IB_LOW", "MQ_PUT_0DTE", "MQ_HVL", "GEX_DN", "VWAP_W_SD1D"}

candidates = [
    ("CAND1: NQ KEEP confl>=1 LONDON+US LONG",
     nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"]) & (nq["side"] == "LONG")),
    ("CAND2: NQ KEEP confl>=1 LONDON+US (LONG+SHORT)",
     nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 1) & nq["session_at_entry"].isin(["LONDON", "US_CASH"])),
    ("CAND3: NQ KEEP confl>=2 ALL_SESSIONS LONG",
     nq["level_name"].isin(KEEP_NQ) & (nq["confl_count"] >= 2) & (nq["side"] == "LONG")),
]

def deflated_sharpe(returns, n_trials=100):
    """DSR Bailey-Lopez 2014 simplified: penalize for multiple testing."""
    if len(returns) < 30:
        return None
    sr = returns.mean() / returns.std() * np.sqrt(252)  # daily annualized approx
    # Skew/kurt adjustment (Lopez 2014 eq 4)
    skew = scstats.skew(returns)
    kurt = scstats.kurtosis(returns)
    n = len(returns)
    # Std error of SR
    se = np.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1))
    # Expected max SR under null with n_trials
    e_max_sr = (1 - 0.5772) * scstats.norm.ppf(1 - 1.0 / n_trials) + 0.5772 * scstats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    dsr = scstats.norm.cdf((sr - e_max_sr * se) / se) if se > 0 else 0
    return dict(sr=round(sr, 3), dsr=round(dsr, 3), n=n, skew=round(skew, 2), kurt=round(kurt, 2))

for label, mask in candidates:
    g = nq[mask].copy().sort_values("entry_dt").reset_index(drop=True)
    n = len(g)
    pnl = g["pnl_ticks_net"].values
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    pf = (wins / losses) if losses > 0 else float("inf")
    wr = (pnl > 0).mean() * 100
    n_days = g["date"].nunique()
    tpd = n / n_days
    
    # Concentration top winners
    top3 = sorted(pnl[pnl > 0].tolist(), reverse=True)[:3]
    conc3 = sum(top3) / wins if wins > 0 else 0
    pf_no_top3 = ((wins - sum(top3)) / losses) if losses > 0 else None
    
    # PF par mois (regime stability)
    g["month"] = g["entry_dt"].dt.to_period("M")
    monthly = []
    for m, gm in g.groupby("month"):
        if len(gm) < 5:
            continue
        p = gm["pnl_ticks_net"].values
        w = p[p > 0].sum()
        l = -p[p < 0].sum()
        pfm = (w / l) if l > 0 else (5.0 if w > 0 else 0)
        monthly.append((str(m), len(gm), round(min(pfm, 5.0), 2), round((p > 0).mean() * 100, 1)))
    
    # PF par session
    sessions_pf = {}
    for sess, gs in g.groupby("session_at_entry"):
        if len(gs) < 30:
            continue
        p = gs["pnl_ticks_net"].values
        w = p[p > 0].sum()
        l = -p[p < 0].sum()
        sessions_pf[sess] = dict(n=len(gs), pf=round((w / l) if l > 0 else 5.0, 2), wr=round((p > 0).mean() * 100, 1))
    
    # PF par level
    levels_pf = {}
    for lvl, gl in g.groupby("level_name"):
        if len(gl) < 30:
            continue
        p = gl["pnl_ticks_net"].values
        w = p[p > 0].sum()
        l = -p[p < 0].sum()
        levels_pf[lvl] = dict(n=len(gl), pf=round((w / l) if l > 0 else 5.0, 2), wr=round((p > 0).mean() * 100, 1))
    
    # DSR sur returns par jour (PnL daily)
    daily_pnl = g.groupby("date")["pnl_ticks_net"].sum().values
    dsr_info = deflated_sharpe(daily_pnl, n_trials=50)  # 50 trials = nombre approx tests faits
    
    # Costs deja inclus dans pnl_ticks_net (regle anti-cheat)
    avg_ticks_net = pnl.mean()
    
    # MFE / MAE moyens
    mfe_avg = g["mfe_ticks"].mean()
    mae_avg = g["mae_ticks"].mean()
    
    print()
    print("###", label)
    print(f"  n={n} | tpd={tpd:.2f} | n_days={n_days} | WR={wr:.1f}% | PF={pf:.2f} | avg_net={avg_ticks_net:.1f}t")
    print(f"  Concentration top3 / wins: {conc3:.3f} (Lopez seuil <0.33: {'PASS' if conc3 < 0.33 else 'FAIL'})")
    print(f"  PF without top3 winners: {pf_no_top3}")
    print(f"  MFE_avg: {mfe_avg:.1f}t, MAE_avg: {mae_avg:.1f}t")
    print(f"  DSR Bailey: {dsr_info}")
    print(f"  Sessions: {sessions_pf}")
    print(f"  Levels: {levels_pf}")
    print(f"  Monthly stability: {len(monthly)} months tracked")
    months_ok = sum(1 for m, n_, pfm, wrm in monthly if pfm >= 1.3)
    months_under_1 = sum(1 for m, n_, pfm, wrm in monthly if pfm < 1.0)
    print(f"    Months PF>=1.3: {months_ok} / {len(monthly)} ({100*months_ok/len(monthly):.0f}%)")
    print(f"    Months PF<1.0:  {months_under_1} / {len(monthly)} ({100*months_under_1/len(monthly):.0f}%)")
    for m_ in monthly:
        print(f"    {m_}")
