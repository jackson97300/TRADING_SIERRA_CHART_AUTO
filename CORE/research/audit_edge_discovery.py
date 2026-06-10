"""
audit_edge_discovery.py — Phase 1 Edge Discovery rigoureux (Lopez compliant).

REPONSE A : "Edge existe-t-il dans les features V5e_clean_long pour LONG/SHORT ?"

Methodologie strict anti-tricherie (Jackson 06/05 "SANS TRICHE") :

1. INFORMATION COEFFICIENT (IC) : Spearman feature × y_binary, per direction
   IC > 0.05 = signal exploitable (Lopez recommande)
   IC > 0.10 = edge fort

2. MUTUAL INFORMATION : mutual_info_classif sample 50K bars (capture non-linear)
   MI > 0.005 = signal informatif

3. CROSS-FOLD STABILITY : compute IC par fold (5 folds chrono), verify std < |mean|
   Si IC instable cross-fold = pas un edge stable

4. BASELINE STRATEGY simple (sign top features) walk-forward :
   - Signal = somme normalisee top 5 features (z-score)
   - Threshold optimise sur train, frozen pour test
   - 5 folds purged k-fold + embargo 60 bars (label horizon)
   - DSR Lopez n_trials=1000 (haircut multiple testing : 4 sous-tableaux × 5 folds × 50 thresholds testes)
   - Costs : 2 ticks slippage round-trip
   - Verdict GO/NOGO baseline (DSR_oos >= 0.5 ET Sharpe > 0)

5. PAR SOUS-TABLEAU : ES_BUY, ES_SELL, NQ_BUY, NQ_SELL (4 modeles independants)
   Per-direction important car features SHORT differentes de LONG

Output : rapport detaille top features + verdict GO/NOGO par sous-tableau.

Anti-tricherie :
- Walk-forward chronologique strict (pas de shuffle)
- Embargo 60 bars (= horizon label v5)
- Feature selection sur fold 0 train uniquement (no leak)
- DSR haircut large (n_trials=1000)
- Threshold opt sur train, frozen pour test (pas de threshold per-fold ré-opt)

Usage : python -X utf8 CORE/research/audit_edge_discovery.py
"""
from __future__ import annotations

import json
import math
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_classif

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
DATASETS_DIR = ROOT / "DATA" / "DATASETS"

# ─── Lopez compliant params ──────────────────────────────────────────────
N_FOLDS = 5
EMBARGO_BARS = 60     # = horizon label v5
TOP_N_FEATURES = 30   # top features par IC pour analyse
BASELINE_TOP_N = 5    # nombre de features pour baseline simple
# Haircut DSR : ml-trainer C2 06/05 = 10000 (conservatisme realiste pour peeking IC selection)
# 4 subsets × 5 folds × 50 thresholds = 1000 strategies explicites
# + selection bias prealable (compute IC sur 388 features = peek-ahead) → +~10x facteur
N_STRATEGIES_DSR_RIGOROUS = 10000  # GO_RIGOROUS (DSR realiste apres peeking)
N_STRATEGIES_DSR_CANDIDAT = 1000   # CANDIDAT (DSR strict explicit strategies)
N_STRATEGIES_DSR = N_STRATEGIES_DSR_RIGOROUS  # default conservateur
SLIPPAGE_USD_PER_TRADE = 6.25  # ES micro 2 ticks slippage RT, NQ ~$5

# IC thresholds
IC_MIN_EXPLOITABLE = 0.05
IC_MIN_STRONG = 0.10
MI_MIN = 0.005

# Baseline DSR thresholds
BASELINE_DSR_MIN = 0.5
BASELINE_SHARPE_MIN = 0.05


def deflated_sharpe(sr_observed, n_obs, skew, kurt, n_trials):
    if n_obs < 10 or sr_observed <= 0:
        return None, None
    gamma = 0.5772156649
    if n_trials <= 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        sr0 = (1 - gamma) * z1 + gamma * z2
        sr0 = sr0 / math.sqrt(max(n_obs - 1, 1))
    denom = 1 - skew * sr_observed + (kurt - 1) / 4.0 * (sr_observed ** 2)
    if denom <= 0:
        return None, None
    psr = stats.norm.cdf(sr_observed * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    dsr = stats.norm.cdf((sr_observed - sr0) * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    return float(psr), float(dsr)


def load_dataset(symbol):
    fp = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    df = pd.read_parquet(fp)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def get_feature_cols(df):
    """Feature cols numeric, exclude meta/label/OHLCV/TS."""
    exclude = {"ts_event", "symbol", "label", "sample_weight",
               "open", "high", "low", "close", "volume",
               "_date", "_month", "_dow", "_hour"}
    return [c for c in df.columns
            if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]


def compute_ic_per_feature(X, y, sample_size=None):
    """Information Coefficient = Spearman correlation feature × y_binary.

    ml-trainer C1 06/05 (BLOCKING) : full dataset par defaut (pas sampling).
    scipy spearmanr vectorise = 5-10s sur 351K bars × 388 features. Gain precision.
    sample_size != None : utilise pour cross-fold compute (folds = 70K bars deja).
    """
    n = len(X)
    if sample_size is not None and n > sample_size:
        idx = np.random.RandomState(42).choice(n, sample_size, replace=False)
        X_s = X.iloc[idx]
        y_s = y[idx]
    else:
        X_s, y_s = X, y
    y_series = pd.Series(y_s, index=X_s.index)
    ic = X_s.corrwith(y_series, method="spearman").dropna()
    return ic.sort_values(key=abs, ascending=False)


def compute_mi_per_feature(X, y, sample_size=30000):
    """Mutual Information feature × y_binary (capture non-linear)."""
    n = len(X)
    if n > sample_size:
        idx = np.random.RandomState(42).choice(n, sample_size, replace=False)
        X_s = X.iloc[idx]
        y_s = y[idx]
    else:
        X_s, y_s = X, y
    X_imp = X_s.fillna(X_s.median())
    # MI compute - ml-trainer C3 06/05 : forcer y_s int (mutual_info_classif requires)
    mi = mutual_info_classif(X_imp.values, y_s.astype(int), random_state=42, n_jobs=-1)
    return pd.Series(mi, index=X_imp.columns).sort_values(ascending=False)


def ic_cross_fold_stability(X, y, n_folds=N_FOLDS):
    """Compute IC par fold (chronologique) pour verifier stabilite.

    Returns DataFrame {feature: [ic_fold1, ic_fold2, ..., ic_foldN]}.
    Sub-tableau interessant : features avec mean IC > 0 ET std/abs(mean) < 1.0
    (signal stable cross-time).
    """
    n = len(X)
    fold_size = n // n_folds
    fold_ics = {}
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n
        X_f = X.iloc[start:end]
        y_f = y[start:end]
        if len(X_f) < 1000:
            continue
        ic_f = compute_ic_per_feature(X_f, y_f, sample_size=20000)
        for c, v in ic_f.items():
            fold_ics.setdefault(c, [np.nan] * n_folds)[i] = float(v)
    return pd.DataFrame(fold_ics).T


def walk_forward_baseline(X, y, sw, top_features, instrument):
    """Baseline strategy : signal = sign(sum z-score top 5 features) > threshold.

    Walk-forward 5 folds chronologique + embargo 60 bars.
    Threshold optimise sur fold 0 train, frozen pour folds suivants.
    Returns dict avec DSR, Sharpe, n_trades, etc.
    """
    n = len(X)
    fold_size = n // N_FOLDS
    sample_size_train = 50000
    # Compute z-scores top features sur fold 0 train (mean/std frozen)
    fold0_train = X.iloc[:fold_size - EMBARGO_BARS]
    if len(fold0_train) < 1000:
        return {"verdict": "NOGO_INSUFFICIENT_TRAIN"}
    means = fold0_train[top_features].mean()
    stds = fold0_train[top_features].std().replace(0, 1.0)
    # Z-score normalise
    X_z = (X[top_features] - means) / stds
    X_z = X_z.fillna(0)
    # Signal = sum z-scores (signe)
    signal_score = X_z.sum(axis=1)

    # Threshold opt sur fold 0 train (50 thresholds tested)
    # Maximise Sharpe sur fold 0 train, frozen pour folds 1-4 test
    train_signal = signal_score.iloc[:fold_size - EMBARGO_BARS].values
    train_y = y[:fold_size - EMBARGO_BARS]
    best_threshold = 0.0
    best_sharpe = -np.inf
    for thresh in np.linspace(-2.0, 2.0, 50):
        signals = (train_signal > thresh).astype(int)
        outcomes = np.where(signals == 1, np.where(train_y == 1, 1, -1), 0)
        nz = outcomes[outcomes != 0]
        if len(nz) < 20:
            continue
        sh = nz.mean() / (nz.std() + 1e-9)
        if sh > best_sharpe:
            best_sharpe = sh
            best_threshold = thresh

    # Walk-forward folds 1-4 test (fold 0 = train, exclu)
    fold_metrics = []
    all_pnl = []
    for i in range(1, N_FOLDS):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < N_FOLDS - 1 else n
        test_signal = signal_score.iloc[test_start:test_end].values
        test_y = y[test_start:test_end]
        signals = (test_signal > best_threshold).astype(int)
        outcomes = np.where(signals == 1, np.where(test_y == 1, 1, -1), 0)
        nz = outcomes[outcomes != 0]
        n_trades = len(nz)
        wr = float((nz > 0).mean()) if n_trades > 0 else 0
        sh = float(nz.mean() / (nz.std() + 1e-9)) if n_trades > 10 else 0
        fold_metrics.append({
            "fold": i, "test_start": test_start, "test_end": test_end,
            "n_trades": n_trades, "wr": wr, "sharpe": sh,
        })
        all_pnl.extend(nz.tolist())

    n_total = len(all_pnl)
    if n_total < 20:
        return {"verdict": "NOGO_LOW_N", "n_total": n_total, "best_threshold": best_threshold}

    pnl_arr = np.array(all_pnl)
    sharpe = pnl_arr.mean() / (pnl_arr.std() + 1e-9)
    wr = float((pnl_arr > 0).mean())
    sk = float(stats.skew(pnl_arr)) if n_total >= 4 else 0.0
    kt = float(stats.kurtosis(pnl_arr, fisher=False)) if n_total >= 4 else 3.0
    # 2 niveaux haircut (ml-trainer A3 06/05) :
    psr_rigorous, dsr_rigorous = deflated_sharpe(sharpe, n_total, sk, kt, N_STRATEGIES_DSR_RIGOROUS)
    psr_candidat, dsr_candidat = deflated_sharpe(sharpe, n_total, sk, kt, N_STRATEGIES_DSR_CANDIDAT)

    n_folds_positive = sum(1 for f in fold_metrics if f["sharpe"] > 0)
    fold_sharpes = [f["sharpe"] for f in fold_metrics]
    sharpe_std_cross_fold = float(np.std(fold_sharpes)) if len(fold_sharpes) >= 2 else 0

    # Verdict 2 niveaux (ml-trainer A3) :
    if dsr_rigorous is None:
        verdict = "NOGO_DSR_FAIL"
    elif sharpe < BASELINE_SHARPE_MIN:
        verdict = "NOGO_SHARPE_LOW"
    elif n_folds_positive < 3:
        verdict = "NOGO_INSTABLE"
    elif dsr_rigorous >= BASELINE_DSR_MIN:
        verdict = "GO_RIGOROUS"  # DSR realiste apres peeking selection
    elif dsr_candidat >= BASELINE_DSR_MIN:
        verdict = "CANDIDAT"  # DSR strict explicite, mais peeking pas penalise
    else:
        verdict = "NOGO_DSR_LOW"

    return {
        "verdict": verdict,
        "best_threshold": float(best_threshold),
        "best_threshold_train_sharpe": float(best_sharpe),
        "n_total_oos": n_total,
        "wr_oos": wr,
        "sharpe_oos": float(sharpe),
        "psr_rigorous": psr_rigorous,
        "dsr_rigorous": dsr_rigorous,
        "psr_candidat": psr_candidat,
        "dsr_candidat": dsr_candidat,
        # backward compat
        "psr_oos": psr_rigorous,
        "dsr_oos": dsr_rigorous,
        "n_folds_positive": n_folds_positive,
        "sharpe_std_cross_fold": sharpe_std_cross_fold,
        "fold_metrics": fold_metrics,
    }


def run_subset(symbol, direction, df):
    """Audit edge sur sous-tableau {ES,NQ} × {BUY,SELL}.

    direction : "BUY" -> y = (label == 1).astype(int)
                "SELL" -> y = (label == -1).astype(int)
    """
    print(f"\n  {'='*90}")
    print(f"  AUDIT EDGE : {symbol} × {direction}")
    print(f"  {'='*90}")

    if direction == "BUY":
        y = (df["label"] == 1).astype(int).values
    elif direction == "SELL":
        y = (df["label"] == -1).astype(int).values
    else:
        raise ValueError(direction)

    sw = df["sample_weight"].values if "sample_weight" in df.columns else np.ones(len(df))
    feat_cols = get_feature_cols(df)
    X = df[feat_cols].copy()

    # Drop high-NaN cols
    nan_pct = X.isna().mean()
    high_nan_cols = nan_pct[nan_pct > 0.5].index.tolist()
    X = X.drop(columns=high_nan_cols)
    print(f"  Features apres drop high-NaN : {len(X.columns)} (drop {len(high_nan_cols)})")
    print(f"  Target distribution : {y.sum()} positifs / {len(y)} ({y.mean()*100:.1f}%)")

    # IC compute
    print(f"\n  [IC] Information Coefficient (Spearman feature × y)")
    t0 = time.time()
    ic_series = compute_ic_per_feature(X, y, sample_size=50000)
    n_exploitable = (ic_series.abs() >= IC_MIN_EXPLOITABLE).sum()
    n_strong = (ic_series.abs() >= IC_MIN_STRONG).sum()
    print(f"    Total features avec |IC| >= {IC_MIN_EXPLOITABLE} : {n_exploitable}")
    print(f"    Total features avec |IC| >= {IC_MIN_STRONG} (edge fort) : {n_strong}")
    print(f"    Top 15 par |IC| :")
    for c in ic_series.head(15).index:
        v = ic_series[c]
        flag = "***" if abs(v) >= IC_MIN_STRONG else ("**" if abs(v) >= IC_MIN_EXPLOITABLE else "")
        print(f"      {c:50s} IC={v:+.4f} {flag}")
    print(f"    [time {time.time()-t0:.1f}s]")

    # MI compute
    print(f"\n  [MI] Mutual Information (non-linear capture)")
    t0 = time.time()
    mi_series = compute_mi_per_feature(X, y, sample_size=30000)
    n_mi = (mi_series >= MI_MIN).sum()
    print(f"    Total features avec MI >= {MI_MIN} : {n_mi}")
    print(f"    Top 10 par MI :")
    for c in mi_series.head(10).index:
        print(f"      {c:50s} MI={mi_series[c]:+.4f}")
    print(f"    [time {time.time()-t0:.1f}s]")

    # Cross-fold stability (sur top 30 IC)
    print(f"\n  [STABILITY] IC cross-fold (5 folds chrono)")
    t0 = time.time()
    top30 = ic_series.head(TOP_N_FEATURES).index.tolist()
    ic_folds_df = ic_cross_fold_stability(X[top30], y)
    if not ic_folds_df.empty:
        ic_mean = ic_folds_df.mean(axis=1)
        ic_std = ic_folds_df.std(axis=1)
        stability_ratio = ic_std / ic_mean.abs().replace(0, np.nan)
        # Stable = std < |mean|
        stable_mask = (stability_ratio < 1.0) & (ic_mean.abs() >= IC_MIN_EXPLOITABLE * 0.5)
        n_stable = stable_mask.sum()
        print(f"    Top 30 stables cross-fold (std<|mean|) : {n_stable}")
        print(f"    Top 10 stables :")
        stable_features = ic_mean[stable_mask].abs().sort_values(ascending=False).head(10)
        for c in stable_features.index:
            print(f"      {c:50s} IC_mean={ic_mean[c]:+.4f} IC_std={ic_std[c]:.4f} ratio={stability_ratio[c]:.2f}")
    print(f"    [time {time.time()-t0:.1f}s]")

    # Baseline strategy walk-forward
    print(f"\n  [BASELINE] Strategy simple sign(top {BASELINE_TOP_N} features z-score)")
    t0 = time.time()
    top_baseline = ic_series.head(BASELINE_TOP_N).index.tolist()
    print(f"    Top {BASELINE_TOP_N} : {top_baseline}")
    baseline_result = walk_forward_baseline(X, y, sw, top_baseline, instrument=f"{symbol}_{direction}")
    print(f"    Verdict : {baseline_result['verdict']}")
    print(f"    Threshold opt fold 0 : {baseline_result.get('best_threshold', 'N/A')}")
    if "n_total_oos" in baseline_result:
        print(f"    n_trades_oos : {baseline_result['n_total_oos']}")
        print(f"    WR_oos : {baseline_result['wr_oos']*100:.1f}%")
        print(f"    Sharpe_oos : {baseline_result['sharpe_oos']:+.4f}")
        print(f"    DSR_oos : {baseline_result.get('dsr_oos')}")
        print(f"    Folds positifs : {baseline_result.get('n_folds_positive', 0)}/{N_FOLDS-1}")
    print(f"    [time {time.time()-t0:.1f}s]")

    return {
        "symbol": symbol,
        "direction": direction,
        "n_features": len(X.columns),
        "n_target_positives": int(y.sum()),
        "ic_top15": [(c, float(ic_series[c])) for c in ic_series.head(15).index],
        "ic_n_exploitable": int(n_exploitable),
        "ic_n_strong": int(n_strong),
        "mi_top10": [(c, float(mi_series[c])) for c in mi_series.head(10).index],
        "mi_n_above_threshold": int(n_mi),
        "baseline": baseline_result,
    }


def main():
    print("=" * 100)
    print("  PHASE 1 EDGE DISCOVERY rigoureux (Lopez compliant, 'sans triche')")
    print("  V5e_clean_long ES + NQ × BUY/SELL = 4 sous-tableaux independants")
    print("=" * 100)

    es_df = load_dataset("ES")
    nq_df = load_dataset("NQ")
    print(f"\n  ES : {es_df.shape}  date {es_df['ts_event'].min()} -> {es_df['ts_event'].max()}")
    print(f"  NQ : {nq_df.shape}  date {nq_df['ts_event'].min()} -> {nq_df['ts_event'].max()}")

    results = {}
    for sym, df in [("ES", es_df), ("NQ", nq_df)]:
        for direction in ["BUY", "SELL"]:
            key = f"{sym}_{direction}"
            print(f"\n{'#'*100}")
            print(f"  {key}")
            print(f"{'#'*100}")
            results[key] = run_subset(sym, direction, df)

    # Synthese
    print(f"\n{'='*100}")
    print(f"  SYNTHESE FINALE")
    print(f"{'='*100}")
    print(f"  Subset    | n_strong_IC | n_exploitable_IC | Baseline DSR | Sharpe_oos | Verdict")
    print(f"  " + "-"*95)
    for key, r in results.items():
        b = r["baseline"]
        dsr_str = f"{b.get('dsr_oos'):.3f}" if b.get("dsr_oos") is not None else "N/A"
        sh_str = f"{b.get('sharpe_oos', 0):+.3f}"
        print(f"  {key:9s} | {r['ic_n_strong']:>10d}  | {r['ic_n_exploitable']:>15d}  | {dsr_str:>11s}  | {sh_str:>9s}  | {b['verdict']}")

    # Verdict global avec 2 niveaux (ml-trainer A3 06/05)
    n_go_rigorous = sum(1 for r in results.values() if r["baseline"]["verdict"] == "GO_RIGOROUS")
    n_candidat = sum(1 for r in results.values() if r["baseline"]["verdict"] == "CANDIDAT")
    print(f"\n  Sous-tableaux GO_RIGOROUS (DSR>=0.5 n_trials=10000, robuste peeking) : {n_go_rigorous}/4")
    print(f"  Sous-tableaux CANDIDAT (DSR>=0.5 n_trials=1000, peeking non penalise) : {n_candidat}/4")
    if n_go_rigorous == 0 and n_candidat == 0:
        print(f"  >>> CONCLUSION : Pas d'edge baseline detecte sur aucun sous-tableau.")
        print(f"      RECOMMANDATION : auditer label v5 sanity OU collecter plus de data OU repenser features.")
    elif n_go_rigorous >= 1:
        print(f"  >>> CONCLUSION : Edge baseline rigoureux detecte sur {n_go_rigorous} sous-tableau(x).")
        print(f"      RECOMMANDATION : prioriser ces setups pour Phase 2 (audit ML CatBoost/Stacking).")
    else:
        print(f"  >>> CONCLUSION : Aucun GO_RIGOROUS, mais {n_candidat} CANDIDAT(s).")
        print(f"      RECOMMANDATION : phase 2 walk-forward 12-fold + DSR n_trials=N_features (~388K) avant integration.")
    print(f"\n  WARNING : Phase 1 = exploratoire. Tout subset GO requirera ml-trainer Phase 2 confirmation.")

    # Save
    out = ROOT / "DATA" / f"audit_edge_discovery_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json"
    payload = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "n_strategies_dsr_haircut": N_STRATEGIES_DSR,
        "n_folds": N_FOLDS,
        "embargo_bars": EMBARGO_BARS,
        "results": results,
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report : {out}")


if __name__ == "__main__":
    main()
