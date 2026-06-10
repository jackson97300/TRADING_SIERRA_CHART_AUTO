"""
Walk-forward backtest Lopez-compliant pour 5 cluster strategies decouverts par audit cross-family.

Methodologie :
- 12 folds chronologiques (1 mois warmup / 1 mois test)
- Forward return : fwd5_ticks = (close.shift(-5) - close) / 0.25
- Metriques par fold : n_fires, winrate, mean_ticks, Sharpe
- DSR (Deflated Sharpe Ratio) avec haircut multiple testing ~600 strategies
- Costs : 2 ticks slippage round-trip
- Verdict GO/NOGO par cluster

Usage : python -X utf8 CORE/research/walk_forward_top5_clusters.py
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "DATA" / "DATASETS"

ES_PATH = DATA_DIR / "ES_dataset_v5e.parquet"
NQ_PATH = DATA_DIR / "NQ_dataset_v5e.parquet"

TICK_SIZE = 0.25
SLIPPAGE_TICKS_ROUND_TRIP = 2.0  # 1 tick entry + 1 tick exit
N_STRATEGIES_TESTED = 600  # haircut multiple testing audit cross-family
N_FOLDS = 12

# ============================================================================
# Definition des clusters candidats
# ============================================================================

CLUSTERS = [
    {
        "id": 1,
        "symbol": "NQ",
        "direction": "BUY",
        "name": "aggressor_strong_sell + n_big_sell_t1 + near_mq_hvl",
        "build": lambda df: (
            (df["aggressor_imbalance"] <= -0.3).astype(int)
            & (df["n_big_sell_t1"] >= 1).astype(int)
            & (df["dist_mq_hvl_pct"].abs() <= 0.3).astype(int)
        ),
    },
    {
        "id": 2,
        "symbol": "NQ",
        "direction": "BUY",
        "name": "n_trapped_sellers_cluster_within_0_2pct + near_gex_nearest_dn",
        "build": lambda df: (
            (df["n_trapped_sellers_cluster_within_0_2pct"] >= 1).astype(int)
            & (df["dist_gex_nearest_dn_pct"].abs() <= 0.3).astype(int)
        ),
    },
    {
        "id": 3,
        "symbol": "NQ",
        "direction": "BUY",
        "name": "bn_stack_ask + n_big_sell_t1 + n_big_t1",
        "build": lambda df: (
            (df["bn_stack_ask"] >= 1).astype(int)
            & (df["n_big_sell_t1"] >= 1).astype(int)
            & (df["n_big_t1"] >= 1).astype(int)
        ),
    },
    {
        "id": 4,
        "symbol": "ES",
        "direction": "SELL",
        "name": "aggressor_strong_buy + bn_absorb_ask_at_level + bn_absorb_ask_raw",
        "build": lambda df: (
            (df["aggressor_imbalance"] >= 0.3).astype(int)
            & (df["bn_absorb_ask_at_level"] >= 1).astype(int)
            & (df["bn_absorb_ask_raw"] >= 1).astype(int)
        ),
    },
    {
        "id": 5,
        "symbol": "ES",
        "direction": "BUY",
        "name": "bn_trapped_sellers_at_support + n_big_t1",
        "build": lambda df: (
            (df["bn_trapped_sellers_at_support"] >= 1).astype(int)
            & (df["n_big_t1"] >= 1).astype(int)
        ),
    },
]


# ============================================================================
# Metriques Lopez
# ============================================================================

def deflated_sharpe(sr_observed, n_obs, sr_distribution_skew=0.0,
                    sr_distribution_kurt=3.0, n_trials=600):
    """
    Deflated Sharpe Ratio (Lopez de Prado, AFML ch.14)

    SR_observed: Sharpe annualise observe
    n_obs: nombre d'observations (trades)
    n_trials: nombre de strategies testees pour multiple testing
    """
    if n_obs < 10 or sr_observed <= 0:
        return None, None

    # Expected max sharpe under null hypothesis (multiple testing)
    # Bailey & Lopez de Prado (2014) approx :
    # SR_0 = sqrt(V[SR]) * ((1-gamma)*Z(1-1/N) + gamma*Z(1-1/(N*e)))
    gamma = 0.5772156649  # Euler-Mascheroni
    e_factor = math.e
    if n_trials <= 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * e_factor))
        # Variance of estimated Sharpe under H0 ~ 1/n
        sr0 = (1 - gamma) * z1 + gamma * z2
        sr0 = sr0 / math.sqrt(max(n_obs - 1, 1))

    # PSR (probability that true SR > 0, given observed and nonnormal moments)
    # PSR = Z((SR - 0) * sqrt(n-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2))
    denom = 1 - sr_distribution_skew * sr_observed + (sr_distribution_kurt - 1) / 4.0 * (sr_observed ** 2)
    if denom <= 0:
        return None, None
    psr = stats.norm.cdf(sr_observed * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))

    # DSR = PSR with threshold sr0 instead of 0
    denom_dsr = 1 - sr_distribution_skew * sr_observed + (sr_distribution_kurt - 1) / 4.0 * (sr_observed ** 2)
    if denom_dsr <= 0:
        return psr, None
    dsr = stats.norm.cdf((sr_observed - sr0) * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom_dsr))
    return psr, dsr


def compute_max_drawdown_ticks(pnl_series_ticks):
    """Drawdown maximum sur cumul ticks."""
    if len(pnl_series_ticks) == 0:
        return 0.0
    cum = np.cumsum(pnl_series_ticks)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return float(dd.max())


# ============================================================================
# Walk-forward
# ============================================================================

def build_folds_monthly(df_with_ts, n_folds=12):
    """
    Construit des folds chronologiques 1 mois.
    Returns : list of (test_start, test_end) tuples
    """
    ts_min = df_with_ts["ts_event"].min()
    ts_max = df_with_ts["ts_event"].max()
    total_days = (ts_max - ts_min).total_seconds() / 86400
    fold_days = total_days / (n_folds + 1)  # 1 fold warmup + n_folds tests

    folds = []
    for i in range(n_folds):
        test_start = ts_min + pd.Timedelta(days=fold_days * (i + 1))
        test_end = ts_min + pd.Timedelta(days=fold_days * (i + 2))
        folds.append((test_start, test_end))
    return folds


def evaluate_fold(df_fold, signal_mask, direction, fwd_col="_fwd5_ticks_signed"):
    """
    Evalue un fold pour un signal donne.
    direction : 'BUY' ou 'SELL' (le fwd_col est deja signed selon direction)
    Returns : dict de metriques
    """
    fires = df_fold[signal_mask].copy()
    fires = fires.dropna(subset=[fwd_col])

    n_fires = len(fires)
    if n_fires == 0:
        return {
            "n_fires": 0, "winrate": np.nan, "mean_ticks_gross": np.nan,
            "mean_ticks_net": np.nan, "std_ticks": np.nan, "sharpe": np.nan,
            "max_dd": 0.0, "skew": np.nan, "kurt": np.nan,
        }

    pnl_gross = fires[fwd_col].values
    pnl_net = pnl_gross - SLIPPAGE_TICKS_ROUND_TRIP

    winrate = float((pnl_gross > 0).mean())
    mean_gross = float(pnl_gross.mean())
    mean_net = float(pnl_net.mean())
    std = float(pnl_gross.std())
    sharpe = mean_gross / std if std > 1e-9 else 0.0
    skew = float(stats.skew(pnl_gross)) if n_fires >= 4 else 0.0
    kurt = float(stats.kurtosis(pnl_gross, fisher=False)) if n_fires >= 4 else 3.0
    max_dd = compute_max_drawdown_ticks(pnl_net)

    return {
        "n_fires": n_fires,
        "winrate": winrate,
        "mean_ticks_gross": mean_gross,
        "mean_ticks_net": mean_net,
        "std_ticks": std,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "skew": skew,
        "kurt": kurt,
    }


def run_cluster_walkforward(df, cluster):
    """
    Walk-forward sur un cluster.
    Retourne : DataFrame fold-level + dict aggregate.
    """
    direction = cluster["direction"]
    sign = +1 if direction == "BUY" else -1

    df = df.sort_values("ts_event").reset_index(drop=True).copy()

    # Forward return signed selon direction
    fwd5_raw = (df["close"].shift(-5) - df["close"]) / TICK_SIZE
    df["_fwd5_ticks_signed"] = sign * fwd5_raw

    # Build signal
    sig = cluster["build"](df).fillna(0).astype(int)
    df["_signal"] = sig

    # Folds
    folds = build_folds_monthly(df, N_FOLDS)

    fold_results = []
    all_pnl_net = []
    months_with_fires = 0

    for i, (start, end) in enumerate(folds):
        mask = (df["ts_event"] >= start) & (df["ts_event"] < end)
        df_fold = df.loc[mask]
        fold_signal = (df_fold["_signal"] == 1)
        m = evaluate_fold(df_fold, fold_signal, direction)
        m["fold"] = i + 1
        m["start"] = start.strftime("%Y-%m-%d")
        m["end"] = end.strftime("%Y-%m-%d")
        fold_results.append(m)

        # Cumul pour DD et stats globales
        fires = df_fold[fold_signal].dropna(subset=["_fwd5_ticks_signed"])
        if len(fires) > 0:
            pnl = fires["_fwd5_ticks_signed"].values - SLIPPAGE_TICKS_ROUND_TRIP
            all_pnl_net.extend(pnl.tolist())
            months_with_fires += 1

    fold_df = pd.DataFrame(fold_results)

    # Aggregate cross-folds
    valid_folds = fold_df.dropna(subset=["winrate"])
    n_total_fires = int(fold_df["n_fires"].sum())

    if len(valid_folds) == 0 or n_total_fires == 0:
        agg = {
            "cluster_id": cluster["id"],
            "symbol": cluster["symbol"],
            "direction": direction,
            "n_total_fires": 0,
            "n_folds_with_fires": 0,
            "mean_winrate": np.nan,
            "std_winrate": np.nan,
            "mean_ticks_net": np.nan,
            "global_sharpe": np.nan,
            "psr": np.nan,
            "dsr": np.nan,
            "max_dd_global": 0.0,
            "regime_concentration": np.nan,
            "verdict": "NOGO_NO_FIRES",
        }
        return fold_df, agg

    pnl_arr = np.array(all_pnl_net)
    pnl_gross_arr = pnl_arr + SLIPPAGE_TICKS_ROUND_TRIP

    global_winrate = float((pnl_gross_arr > 0).mean())
    global_mean_net = float(pnl_arr.mean())
    global_std = float(pnl_gross_arr.std())
    global_sharpe = (pnl_gross_arr.mean() / global_std) if global_std > 1e-9 else 0.0

    if len(pnl_gross_arr) >= 4:
        sk = float(stats.skew(pnl_gross_arr))
        kt = float(stats.kurtosis(pnl_gross_arr, fisher=False))
    else:
        sk, kt = 0.0, 3.0

    psr, dsr = deflated_sharpe(global_sharpe, len(pnl_arr), sk, kt, N_STRATEGIES_TESTED)
    max_dd_global = compute_max_drawdown_ticks(pnl_arr)

    # Concentration regime : % du total dans les 2 mois les plus actifs
    sorted_fires = fold_df["n_fires"].sort_values(ascending=False)
    if n_total_fires > 0:
        top2_share = float(sorted_fires.head(2).sum() / n_total_fires)
    else:
        top2_share = 1.0

    # Verdict
    std_wr = float(valid_folds["winrate"].std())
    fires_per_active_fold = n_total_fires / max(months_with_fires, 1)

    crit_stable_wr = std_wr < 0.10  # < 10pp
    crit_dsr_pos = dsr is not None and dsr > 0.5  # PSR/DSR > 0.5 = > 50% chance true SR > sr0
    crit_dd_ok = max_dd_global < 30
    crit_n_per_fold = fires_per_active_fold >= 2

    crits = [crit_stable_wr, crit_dsr_pos, crit_dd_ok, crit_n_per_fold]
    n_pass = sum(crits)

    if n_pass == 4:
        verdict = "GO"
    elif n_pass >= 2:
        verdict = "GO_AVEC_RESERVES"
    else:
        verdict = "NOGO"

    # Extra : stationnarite. Si > 60% des fires dans top2 mois → noter
    if top2_share > 0.60:
        verdict += "_NONSTATIONARY"

    # Edge net minimal
    if global_mean_net < 0:
        verdict = "NOGO_NEG_NET"

    agg = {
        "cluster_id": cluster["id"],
        "symbol": cluster["symbol"],
        "direction": direction,
        "name": cluster["name"],
        "n_total_fires": n_total_fires,
        "n_folds_with_fires": months_with_fires,
        "mean_winrate": float(valid_folds["winrate"].mean()),
        "std_winrate": std_wr,
        "global_winrate": global_winrate,
        "mean_ticks_gross": float(pnl_gross_arr.mean()),
        "mean_ticks_net": global_mean_net,
        "global_sharpe": global_sharpe,
        "psr": psr,
        "dsr": dsr,
        "max_dd_global": max_dd_global,
        "regime_concentration_top2": top2_share,
        "fires_per_active_fold": fires_per_active_fold,
        "crit_stable_wr": crit_stable_wr,
        "crit_dsr_pos": crit_dsr_pos,
        "crit_dd_ok": crit_dd_ok,
        "crit_n_per_fold": crit_n_per_fold,
        "verdict": verdict,
    }
    return fold_df, agg


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 80)
    print("WALK-FORWARD BACKTEST — 5 CLUSTER STRATEGIES (Lopez-compliant)")
    print("=" * 80)

    print("\n[Load datasets]")
    es_df = pd.read_parquet(ES_PATH)
    nq_df = pd.read_parquet(NQ_PATH)
    print(f"  ES: {es_df.shape}  range={es_df['ts_event'].min()} → {es_df['ts_event'].max()}")
    print(f"  NQ: {nq_df.shape}  range={nq_df['ts_event'].min()} → {nq_df['ts_event'].max()}")

    all_aggs = []
    all_folds = {}

    for cluster in CLUSTERS:
        df = es_df if cluster["symbol"] == "ES" else nq_df
        print("\n" + "=" * 80)
        print(f"CLUSTER #{cluster['id']} — {cluster['symbol']} {cluster['direction']}")
        print(f"  {cluster['name']}")
        print("=" * 80)

        fold_df, agg = run_cluster_walkforward(df, cluster)

        # Print fold table
        print(f"\nFold-level results:")
        print(fold_df[["fold", "start", "n_fires", "winrate", "mean_ticks_gross",
                       "mean_ticks_net", "sharpe", "max_dd"]].to_string(index=False,
                       float_format=lambda x: f"{x:.3f}" if pd.notna(x) else "  nan"))

        # Aggregate
        print(f"\nAggregate cross-folds:")
        for k, v in agg.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")

        all_aggs.append(agg)
        all_folds[cluster["id"]] = fold_df

    # Final summary
    print("\n\n" + "=" * 100)
    print("FINAL SUMMARY")
    print("=" * 100)

    summary_df = pd.DataFrame(all_aggs)
    cols_show = ["cluster_id", "symbol", "direction", "n_total_fires",
                 "global_winrate", "std_winrate", "mean_ticks_net",
                 "global_sharpe", "psr", "dsr", "max_dd_global",
                 "regime_concentration_top2", "verdict"]
    print(summary_df[cols_show].to_string(index=False,
          float_format=lambda x: f"{x:.3f}" if pd.notna(x) else "   nan"))

    # Save
    out_csv = ROOT / "CORE" / "research" / "walk_forward_top5_clusters_results.csv"
    summary_df.to_csv(out_csv, index=False)
    print(f"\n[Saved] {out_csv}")

    out_folds = ROOT / "CORE" / "research" / "walk_forward_top5_clusters_folds.csv"
    full_fold_df = pd.concat(
        [df.assign(cluster_id=cid) for cid, df in all_folds.items()],
        ignore_index=True
    )
    full_fold_df.to_csv(out_folds, index=False)
    print(f"[Saved] {out_folds}")

    # Top GO / NOGO
    print("\n" + "=" * 80)
    print("VERDICT ANALYSIS")
    print("=" * 80)
    go = summary_df[summary_df["verdict"].str.startswith("GO_") | (summary_df["verdict"] == "GO")]
    nogo = summary_df[summary_df["verdict"].str.startswith("NOGO")]
    print(f"\nGO (any): {len(go)} / {len(summary_df)}")
    print(f"NOGO: {len(nogo)} / {len(summary_df)}")

    if len(go) > 0:
        # Top GO = best DSR
        best = go.sort_values("dsr", ascending=False).iloc[0]
        print(f"\n[BEST GO candidate] Cluster #{best['cluster_id']} "
              f"{best['symbol']} {best['direction']}")
        print(f"  DSR={best['dsr']:.3f} | global_winrate={best['global_winrate']:.3f} | "
              f"net_ticks={best['mean_ticks_net']:.2f} | DD={best['max_dd_global']:.1f}")

    if len(nogo) > 0:
        worst = nogo.sort_values("global_sharpe", ascending=True).iloc[0]
        print(f"\n[WORST NOGO] Cluster #{worst['cluster_id']} "
              f"{worst['symbol']} {worst['direction']}")
        print(f"  reason verdict={worst['verdict']} | sharpe={worst['global_sharpe']:.3f} | "
              f"net_ticks={worst['mean_ticks_net']:.2f}")


if __name__ == "__main__":
    main()
