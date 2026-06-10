import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"D:/TRADING_SIERRA_CHART_AUTO")

def load_trades(symbol):
    rows = []
    path = ROOT / "DATA/BACKTEST/BOT3" / f"trades_{symbol}_full_14m_v3.jsonl"
    with open(path) as f:
        for line in f:
            rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["entry_bar_ts"]).dt.date
    df["entry_dt"] = pd.to_datetime(df["entry_bar_ts"])
    return df

def load_confl(symbol):
    return pd.read_csv(ROOT / "DATA/BACKTEST/BOT3" / f"confluence_test_{symbol}.csv")

def merge_with_confl(trades, confl):
    out = trades.copy()
    out["confl_count"] = confl["confl_count"].values
    if "n_types" in confl.columns:
        out["n_types"] = confl["n_types"].values
    return out

def metrics(g):
    n = len(g)
    if n == 0: return None
    pnl = g["pnl_ticks_net"].values
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    pf = (wins / losses) if losses > 0 else float("inf")
    wr = (pnl > 0).mean() * 100
    n_days = g["date"].nunique()
    tpd = n / max(n_days, 1)
    top3 = sorted(pnl[pnl > 0].tolist(), reverse=True)[:3]
    conc = sum(top3) / wins if wins > 0 else 0
    return dict(n=n, wr=round(wr, 1), pf=round(pf, 2), n_days=n_days, tpd=round(tpd, 2), conc_top3=round(conc, 3))

def walkforward_pf(g, n_folds=12):
    g = g.sort_values("entry_dt").reset_index(drop=True)
    n = len(g)
    if n < n_folds * 8:
        return dict(folds=0, pf_med=None, pf_min=None, stable=False)
    fold_size = n // n_folds
    pfs = []
    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else n
        chunk = g.iloc[start:end]
        pnl = chunk["pnl_ticks_net"].values
        wins = pnl[pnl > 0].sum()
        losses = -pnl[pnl < 0].sum()
        pf = (wins / losses) if losses > 0 else (5.0 if wins > 0 else 0)
        pfs.append(min(pf, 5.0))
    pfs = np.array(pfs)
    pf_med = float(np.median(pfs))
    pf_min = float(pfs.min())
    pf_std = float(pfs.std())
    stab = pf_std / pf_med if pf_med > 0 else 999
    stable = (pf_med >= 1.3) and (pf_min >= 1.0) and (stab <= 0.5)
    return dict(folds=n_folds, pf_med=round(pf_med, 2), pf_min=round(pf_min, 2),
                pf_std=round(pf_std, 2), stab_ratio=round(stab, 2), stable=stable)

def filter_test(label, df, mask):
    g = df[mask]
    if len(g) < 50: return None
    m = metrics(g)
    if m is None: return None
    wf = walkforward_pf(g, n_folds=12)
    out = dict(label=label, **m)
    out.update({f'wf_{k}': v for k, v in wf.items()})
    return out
