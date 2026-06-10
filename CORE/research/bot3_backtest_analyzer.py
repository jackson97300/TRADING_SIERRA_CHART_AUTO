"""Bot 3 Backtest Analyzer — DSR + walk-forward + concentration + bucket GO/HOLD/DROP.

Conformement a DOCS/BOT3_PHASE2_GATE.md (5 criteres Lopez stricts) +
DOCS/BOT3_BACKTEST_METHODOLOGY.md (manifesto PAS DE TRICHE Jackson 03/05).

Usage :
    python -X utf8 CORE/research/bot3_backtest_analyzer.py --run-id full_14m

Output :
    DATA/BACKTEST/BOT3/stats_per_level_<run_id>.csv
    DATA/BACKTEST/BOT3/walkforward_<run_id>.csv
    DOCS/BOT3_BACKTEST_REPORT.md (rapport final)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = ROOT / "DATA" / "BACKTEST" / "BOT3"
DOCS_DIR = ROOT / "DOCS"


def load_trades(run_id: str) -> pd.DataFrame:
    """Charge tous les trades JSONL du run."""
    files = list(BACKTEST_DIR.glob(f"trades_*_{run_id}.jsonl"))
    if not files:
        raise FileNotFoundError(f"Aucun trade JSONL pour run_id={run_id}")
    rows = []
    for f in files:
        with f.open(encoding="utf-8") as fp:
            for line in fp:
                rows.append(json.loads(line.strip()))
    df = pd.DataFrame(rows)
    print(f"Loaded {len(df)} trades from {len(files)} files")
    return df


def compute_pf(pnl_series: pd.Series) -> float:
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def compute_sharpe(pnl_series: pd.Series, periods_per_year: int = 252) -> float:
    if len(pnl_series) < 2:
        return 0.0
    mean = pnl_series.mean()
    std = pnl_series.std()
    if std == 0:
        return 0.0
    return mean / std * math.sqrt(periods_per_year)


def compute_dsr(sharpe_observed: float, n_trials: int, n_obs: int,
                skew: float = 0.0, kurt: float = 3.0) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    Approximation : DSR = Phi(SR_obs - E[max_SR]) / SE(SR_obs)
    Pour rules-based avec N_trials=21 et n=100, formule simplifiee.
    """
    if n_obs < 10:
        return 0.0
    # E[max_SR over N trials] ≈ E_emc * sqrt(n_obs) — Bailey 2014 eq.7 simplified
    gamma = 0.5772    # Euler-Mascheroni
    e_max_sr = math.sqrt((1 - gamma) * math.sqrt(2 * math.log(max(n_trials, 2)))
                         + gamma * math.sqrt(2 * math.log(max(n_trials, 2)) - 1))
    # Variance estimator with skew/kurt correction
    var_sr = (1 - skew * sharpe_observed + (kurt - 1) / 4 * sharpe_observed**2) / max(n_obs - 1, 1)
    if var_sr <= 0:
        return 0.0
    z = (sharpe_observed - e_max_sr) / math.sqrt(var_sr)
    # CDF Phi normal standard
    dsr = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return dsr


def compute_concentration(pnl_series: pd.Series, top_n: int = 3) -> tuple[float, float]:
    """Returns (concentration_top_n_pct, pf_without_top_n)."""
    wins_only = pnl_series[pnl_series > 0].sort_values(ascending=False)
    if len(wins_only) < top_n:
        return (1.0, 0.0)
    top_wins = wins_only.head(top_n).sum()
    gross = wins_only.sum()
    conc = top_wins / gross if gross > 0 else 1.0
    # PF without top N
    others = pnl_series[~pnl_series.isin(wins_only.head(top_n))]
    pf_no_top = compute_pf(others)
    return (conc, pf_no_top)


def compute_max_dd(pnl_series: pd.Series) -> float:
    """Max drawdown peak-trough sur cumul PnL."""
    cum = pnl_series.cumsum()
    if len(cum) == 0:
        return 0.0
    peak = cum.expanding().max()
    dd = peak - cum
    return float(dd.max())


def stats_per_level(df: pd.DataFrame, n_trials: int = 21) -> pd.DataFrame:
    """Stats agregees par (symbol, level_name)."""
    grouped = df.groupby(["symbol", "level_name", "level_tier"])
    rows = []
    for (sym, level, tier), g in grouped:
        n = len(g)
        pnl_gross = g["pnl_ticks_gross"]
        pnl_net = g["pnl_ticks_net"]
        wr = (pnl_net > 0).mean() * 100
        pf_gross = compute_pf(pnl_gross)
        pf_net = compute_pf(pnl_net)
        sharpe_net = compute_sharpe(pnl_net)
        skew = pnl_net.skew() if n >= 3 else 0.0
        kurt = pnl_net.kurt() if n >= 4 else 3.0
        dsr = compute_dsr(sharpe_net, n_trials, n, skew, kurt)
        conc, pf_no_top = compute_concentration(pnl_net, top_n=3)
        max_dd = compute_max_dd(pnl_net)
        avg_pnl = pnl_net.mean()
        median_dur = g["duration_bars"].median() if "duration_bars" in g.columns else 0
        mfe_avg = g["mfe_ticks"].mean() if "mfe_ticks" in g.columns else 0
        mae_avg = g["mae_ticks"].mean() if "mae_ticks" in g.columns else 0
        # Exit reasons distribution
        exit_reasons = g["exit_reason"].value_counts().to_dict() if "exit_reason" in g.columns else {}

        rows.append({
            "symbol": sym, "level_name": level, "level_tier": tier,
            "n_trades": n,
            "win_rate_pct": round(wr, 1),
            "pf_gross": round(pf_gross, 2),
            "pf_net": round(pf_net, 2),
            "sharpe_net": round(sharpe_net, 2),
            "dsr": round(dsr, 3),
            "concentration_top3": round(conc, 3),
            "pf_without_top3": round(pf_no_top, 2),
            "max_dd_ticks": round(max_dd, 1),
            "avg_pnl_ticks_net": round(avg_pnl, 2),
            "median_duration_bars": int(median_dur),
            "mfe_avg_ticks": round(mfe_avg, 1),
            "mae_avg_ticks": round(mae_avg, 1),
            "exit_TP_pct": round(exit_reasons.get("TP_CAP", 0) / n * 100, 1) if n else 0,
            "exit_SL_pct": round(exit_reasons.get("SL", 0) / n * 100, 1) if n else 0,
            "exit_TRAIL_pct": round(exit_reasons.get("TRAILING", 0) / n * 100, 1) if n else 0,
            "exit_TIMEOUT_pct": round(exit_reasons.get("TIMEOUT", 0) / n * 100, 1) if n else 0,
        })
    return pd.DataFrame(rows).sort_values(["symbol", "level_tier", "pf_net"], ascending=[True, True, False])


def bucket_decision(row: pd.Series) -> str:
    """Bucket 3-tier (review market-analyst) : GO / HOLD / DROP."""
    n = row["n_trades"]
    if n < 100:
        return "HOLD"   # n insuffisant, pas faux NOGO
    # n >= 100, evaluer 5 criteres
    criteria_pass = 0
    if row["dsr"] >= 0.95: criteria_pass += 1
    # n>=100 deja verifie
    criteria_pass += 1
    # walk-forward stability calcule separement
    if row["concentration_top3"] < 0.30 and row["pf_without_top3"] >= 1.2: criteria_pass += 1
    if row["pf_net"] >= 1.4: criteria_pass += 1
    if criteria_pass >= 4:
        return "GO"
    return "DROP"


def walk_forward_12_fold(df: pd.DataFrame) -> pd.DataFrame:
    """12-fold time-series stability (Pardo 1992).

    Split chrono trades par level → 12 folds. PF par fold + stability.
    """
    if "entry_bar_ts" not in df.columns:
        return pd.DataFrame()
    df_sorted = df.sort_values("entry_bar_ts").reset_index(drop=True)
    rows = []
    for (sym, level), g in df_sorted.groupby(["symbol", "level_name"]):
        n = len(g)
        if n < 24:    # min 2 trades par fold
            continue
        fold_size = n // 12
        if fold_size < 2:
            continue
        pf_folds = []
        for fold_idx in range(12):
            start = fold_idx * fold_size
            end = (fold_idx + 1) * fold_size if fold_idx < 11 else n
            fold_pnl = g.iloc[start:end]["pnl_ticks_net"]
            pf = compute_pf(fold_pnl)
            pf_folds.append(pf if math.isfinite(pf) else 0.0)
        pf_arr = np.array([p for p in pf_folds if math.isfinite(p) and p < 100])
        if len(pf_arr) < 8:
            continue
        rows.append({
            "symbol": sym, "level_name": level,
            "n_total": n,
            "pf_median": round(float(np.median(pf_arr)), 2),
            "pf_min": round(float(pf_arr.min()), 2),
            "pf_max": round(float(pf_arr.max()), 2),
            "pf_std": round(float(pf_arr.std()), 2),
            "stability_ratio": round(float(pf_arr.std() / max(np.median(pf_arr), 0.01)), 3),
            "stable_pass": (np.median(pf_arr) >= 1.4 and pf_arr.min() >= 1.0
                            and (pf_arr.std() / max(np.median(pf_arr), 0.01)) <= 0.4),
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    df_trades = load_trades(args.run_id)
    if df_trades.empty:
        print("Aucun trade trouve, abort")
        return

    print(f"\n=== Stats par niveau (run {args.run_id}) ===")
    stats = stats_per_level(df_trades)
    stats["bucket"] = stats.apply(bucket_decision, axis=1)
    out_stats = BACKTEST_DIR / f"stats_per_level_{args.run_id}.csv"
    stats.to_csv(out_stats, index=False)
    print(f"Stats : {out_stats}")
    print(stats.to_string(index=False, max_colwidth=20))

    print(f"\n=== Walk-forward 12-fold ===")
    wf = walk_forward_12_fold(df_trades)
    out_wf = BACKTEST_DIR / f"walkforward_{args.run_id}.csv"
    wf.to_csv(out_wf, index=False)
    print(f"Walk-forward : {out_wf}")
    if not wf.empty:
        print(wf.to_string(index=False, max_colwidth=15))

    # Summary global
    print(f"\n=== Bucket decisions ===")
    print(stats["bucket"].value_counts().to_string())

    # Per-tier summary
    print(f"\n=== Per-tier summary ===")
    for tier in [1, 2, 3, 99]:
        tier_stats = stats[stats["level_tier"] == tier]
        if not tier_stats.empty:
            print(f"  Tier {tier}: {len(tier_stats)} levels, avg PF_net = {tier_stats['pf_net'].mean():.2f}")


if __name__ == "__main__":
    main()
