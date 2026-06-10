"""meta_label_nq_buy_validation.py — Test meta-labeling NQ_buy CAUTION → GO.

Approche Lopez AFML ch.3 :
  - Primary model : NQ_buy_model.pkl existant (PF 2.13 / WR 43.2% / DSR 1.0)
  - Meta model : LightGBM binaire qui filtre les signaux peu confiants du primary
  - Goal : faire passer WR de 43.2% → 45%+ (Lopez minimum) tout en gardant PF >= 2.0

Methodologie rigoureuse Lopez compliant :
  1. Walk-forward 70/30 chronologique + purge gap (horizon=60) anti-leak
  2. Train primary + meta sur train, evaluate sur test
  3. PnL OHLC-real (pas reconciliation labeler)
  4. DSR avec skewness/kurtosis empiriques
  5. Comparaison primary-only vs primary+meta sur OOS

Critere GO (Lopez) :
  - PF test >= 2.0 (vs baseline NQ_buy 2.13)
  - WR test >= 45% (vs baseline 43.2% — gap actuel)
  - DSR > 0.95
  - N_test trades >= 30
  - Improvement net vs primary-only

Usage : python -X utf8 CORE/research/meta_label_nq_buy_validation.py
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.meta_labeler import (
    MetaLabelConfig, MetaModel,
    build_meta_labels, build_meta_features,
    DEFAULT_META_CONTEXT_FEATURES,
)

K_SL = 1.5
K_TP_RATIO = 2.0
HORIZON = 60
TICK = 0.25
COST_TICKS = {"NQ": 0.5}
N_TESTS = 6  # Tests : primary-only + 5 meta thresholds (0.40/0.45/0.50/0.55/0.60)


# ==============================================================================
# PnL OHLC-real (BUY-only)
# ==============================================================================


@numba.njit(cache=True)
def _simulate_buy_only_pnl(highs, lows, closes, atrs, k_sl, k_tp_ratio,
                            horizon, tick_size, cost_ticks):
    n = len(closes)
    pnl = np.zeros(n, dtype=np.float64)
    for i in range(n - horizon - 1):
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_ticks = k_sl * atr_t
        tp_ticks = k_tp_ratio * sl_ticks
        entry = closes[i]
        sl_lvl = entry - sl_ticks * tick_size
        tp_lvl = entry + tp_ticks * tick_size
        outcome = 0.0
        hit = False
        for k in range(1, horizon + 1):
            j = i + k
            if j >= n:
                break
            if lows[j] <= sl_lvl:
                outcome = -sl_ticks - cost_ticks
                hit = True
                break
            if highs[j] >= tp_lvl:
                outcome = tp_ticks - cost_ticks
                hit = True
                break
        if not hit:
            j = i + horizon
            if j < n:
                outcome = (closes[j] - entry) / tick_size - cost_ticks
            else:
                outcome = -cost_ticks
        pnl[i] = outcome
    return pnl


def compute_metrics(pnl: np.ndarray) -> dict:
    """Compute PF, WR, EV, Sharpe, MaxDD."""
    if len(pnl) == 0 or np.all(pnl == 0):
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "sharpe": 0, "max_dd": 0, "total": 0}
    nonzero = pnl[pnl != 0]
    if len(nonzero) == 0:
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "sharpe": 0, "max_dd": 0, "total": 0}
    wins = nonzero[nonzero > 0]
    losses = nonzero[nonzero < 0]
    n = len(nonzero)
    pf = float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() < 0 else float("inf")
    wr = len(wins) / n if n > 0 else 0
    ev = float(nonzero.mean())
    sharpe = float(nonzero.mean() / nonzero.std() * np.sqrt(252)) if nonzero.std() > 0 else 0
    cum = np.cumsum(nonzero)
    max_dd = float(np.max(np.maximum.accumulate(cum) - cum))
    return {"n": n, "pf": pf, "wr": wr, "ev": ev, "sharpe": sharpe, "max_dd": max_dd,
            "total": float(nonzero.sum())}


def deflated_sharpe_ratio(sharpe: float, n_trials: int, n_obs: int,
                           skewness: float = 0, kurtosis: float = 3) -> float:
    """DSR Lopez AFML ch.14."""
    from scipy.stats import norm
    if n_trials <= 1 or n_obs < 30:
        return 1.0 if sharpe > 0 else 0.0
    emc = 0.5772156649
    e_max_sr = (1 - emc) * norm.ppf(1 - 1/n_trials) + emc * norm.ppf(1 - 1/(n_trials * np.e))
    var_sr = (1 - skewness * sharpe + (kurtosis - 1) / 4 * sharpe ** 2) / (n_obs - 1)
    if var_sr <= 0:
        return 0.5
    z = (sharpe - e_max_sr) / np.sqrt(var_sr)
    return float(norm.cdf(z))


def main():
    print("=" * 100)
    print("  META-LABELING NQ BUY — Validation Lopez ch.3 (CAUTION → GO)")
    print("=" * 100)
    print(f"  Goal : NQ_buy WR 43.2% → 45%+ via meta filter")
    print(f"  Methode : primary + meta separation + walk-forward 70/30 + purge gap")

    # Charge NQ_buy primary model v5d (NEW - cohherent dataset)
    # FIX 28/04 11:30 : utiliser primary v5d retrain (PF 1.59 sur 12 mois)
    # plutot que v3 25/04 (PF 2.13 mais lucky sur 70j).
    primary_path = ROOT / "DATA" / "MODELS" / "BASELINE_27042026" / "NQ_buy_v5d_model.pkl"
    config_path = ROOT / "DATA" / "MODELS" / "BASELINE_27042026" / "NQ_buy_v5d_pf159_no.json"
    print(f"\n[1/6] Loading primary model V5D from {primary_path.name}...")
    with open(primary_path, "rb") as f:
        primary_model = pickle.load(f)
    import json
    with open(config_path, "r") as f:
        config = json.load(f)
    primary_features = config.get("features", [])
    primary_threshold = config.get("threshold", 0.30)
    print(f"      Primary features = {len(primary_features)} (v5d cohherent)")
    print(f"      Primary threshold = {primary_threshold:.3f}")
    print(f"      Primary baseline metrics : PF={config['aggregate_metrics']['profit_factor']:.2f} "
          f"WR={config['aggregate_metrics']['win_rate']*100:.1f}%")

    # Charge dataset NQ v5d (cohherent avec primary v5d, 12 mois 351K bars)
    print(f"\n[2/6] Loading NQ_dataset_v5d.parquet (12 mois cohherent primary v5d)...")
    df = pd.read_parquet(ROOT / "DATA" / "datasets" / "NQ_dataset_v5d.parquet")
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    print(f"      RTH bars = {len(df):,}")

    # Filter columns to primary features only (some may be missing)
    primary_features_avail = [f for f in primary_features if f in df.columns]
    missing = set(primary_features) - set(primary_features_avail)
    if missing:
        print(f"      [WARN] Missing primary features in v5d : {len(missing)} (e.g. {list(missing)[:3]})")
        # Pour ces features manquantes, ajouter colonnes a 0
        for m in missing:
            df[m] = 0
        primary_features_avail = primary_features

    # PnL OHLC-real
    print(f"\n[3/6] Compute PnL OHLC-real BUY-only...")
    t0 = time.perf_counter()
    # Compat v3 : utilise 'price' au lieu de 'close' si dispo
    if "close" in df.columns:
        closes = df["close"].values.astype(np.float64)
    elif "price" in df.columns:
        closes = df["price"].values.astype(np.float64)
    else:
        raise KeyError("Ni 'close' ni 'price' dans le dataset")
    if "high" in df.columns:
        highs = df["high"].values.astype(np.float64)
    elif "bar_high" in df.columns:
        highs = df["bar_high"].values.astype(np.float64)
    else:
        # v3 : pas de high explicite, approximation = price (no SL/TP intra-bar)
        highs = closes.copy()
    if "low" in df.columns:
        lows = df["low"].values.astype(np.float64)
    elif "bar_low" in df.columns:
        lows = df["bar_low"].values.astype(np.float64)
    else:
        lows = closes.copy()
    atrs = df["atr"].values.astype(np.float64)
    pnl_all = _simulate_buy_only_pnl(highs, lows, closes, atrs,
                                       K_SL, K_TP_RATIO, HORIZON, TICK, COST_TICKS["NQ"])
    print(f"      Done in {time.perf_counter()-t0:.1f}s")

    # Walk-forward 70/30 + purge gap
    print(f"\n[4/6] Walk-forward 70/30 + purge gap Lopez ch.7...")
    n = len(df)
    split_idx = int(n * 0.7)
    purge_train_end = split_idx - HORIZON
    df_train = df.iloc[:purge_train_end].reset_index(drop=True)
    df_test = df.iloc[split_idx:].reset_index(drop=True)
    pnl_train = pnl_all[:purge_train_end]
    pnl_test = pnl_all[split_idx:]
    print(f"      Train: {pd.to_datetime(df_train['ts'], unit='ms').min()} → "
          f"{pd.to_datetime(df_train['ts'], unit='ms').max()} ({len(df_train):,} bars)")
    print(f"      Test : {pd.to_datetime(df_test['ts'], unit='ms').min()} → "
          f"{pd.to_datetime(df_test['ts'], unit='ms').max()} ({len(df_test):,} bars)")

    # Get primary predictions on train + test
    print(f"\n[5/6] Primary predict on train + test...")
    X_train = df_train[primary_features_avail].fillna(0)
    X_test = df_test[primary_features_avail].fillna(0)
    p_primary_train = primary_model.predict_proba(X_train)[:, 1]
    p_primary_test = primary_model.predict_proba(X_test)[:, 1]
    print(f"      Primary train : mean={p_primary_train.mean():.3f}, "
          f"%>thr={(p_primary_train > primary_threshold).mean()*100:.1f}%")
    print(f"      Primary test  : mean={p_primary_test.mean():.3f}, "
          f"%>thr={(p_primary_test > primary_threshold).mean()*100:.1f}%")

    # Build meta labels (train) + features (train + test)
    print(f"\n[6/6] Train meta model on TRAIN, evaluate on TEST...")
    label_train = df_train["label"].astype(np.int8)
    y_meta_train = build_meta_labels(label_train, p_primary_train,
                                      primary_threshold=primary_threshold,
                                      target_label=1)

    # Meta features : context + p_primary + edge combo bonus
    META_CONTEXT_BONUS = DEFAULT_META_CONTEXT_FEATURES + [
        "is_in_us_after",  # combo edge identifie
    ]
    # Filter only available
    avail_meta = [f for f in META_CONTEXT_BONUS if f in df.columns]
    print(f"      Meta context features avail : {len(avail_meta)}/{len(META_CONTEXT_BONUS)}")
    X_meta_train = build_meta_features(df_train, p_primary_train, avail_meta)
    X_meta_test = build_meta_features(df_test, p_primary_test, avail_meta)

    # Train meta model
    cfg = MetaLabelConfig(primary_threshold=primary_threshold,
                           context_features=avail_meta)
    sample_weight_train = df_train["sample_weight"].values if "sample_weight" in df_train.columns else None

    n_meta_train = (~y_meta_train.isna()).sum()
    print(f"      Meta train samples (primary actif) : {n_meta_train:,}")
    if n_meta_train < cfg.min_meta_samples:
        print(f"      [FAIL] Pas assez d'echantillons meta : {n_meta_train} < {cfg.min_meta_samples}")
        return

    meta = MetaModel(cfg)
    try:
        meta.fit(X_meta_train, y_meta_train, sample_weight=sample_weight_train)
    except ValueError as e:
        print(f"      [FAIL] {e}")
        return

    # Predict meta on test
    p_meta_test = meta.predict_proba(X_meta_test)
    print(f"      Meta test : mean={p_meta_test.mean():.3f}, "
          f"std={p_meta_test.std():.3f}")

    # ==========================================================================
    # COMPARAISON : primary-only vs primary+meta
    # ==========================================================================
    print(f"\n{'='*100}")
    print(f"  COMPARAISON : primary-only vs primary+meta sur TEST")
    print(f"{'='*100}")

    # Baseline primary-only
    primary_signal_test = p_primary_test > primary_threshold
    pnl_primary_only = pnl_test[primary_signal_test]
    m_primary = compute_metrics(pnl_primary_only)
    nonzero_p = pnl_primary_only[pnl_primary_only != 0]
    if len(nonzero_p) >= 30:
        from scipy.stats import skew, kurtosis as kurt_fn
        sk_p = float(skew(nonzero_p))
        ku_p = float(kurt_fn(nonzero_p, fisher=False))
    else:
        sk_p, ku_p = 0.0, 3.0
    dsr_p = deflated_sharpe_ratio(m_primary["sharpe"], n_trials=N_TESTS, n_obs=m_primary["n"],
                                    skewness=sk_p, kurtosis=ku_p)

    print(f"\n  PRIMARY-ONLY (NQ_buy seul, baseline) :")
    print(f"    N={m_primary['n']:,}  PF={m_primary['pf']:.2f}  WR={m_primary['wr']*100:.1f}%  "
          f"EV={m_primary['ev']:+.1f}t  Sharpe={m_primary['sharpe']:+.2f}  MaxDD={m_primary['max_dd']:.0f}t  "
          f"DSR={dsr_p:.2f}")

    # Test plusieurs meta thresholds
    print(f"\n  PRIMARY + META — variation seuil meta :")
    print(f"  {'meta_thr':>10s}  {'N':>6s}  {'WR%':>6s}  {'PF':>6s}  {'EV':>7s}  "
          f"{'Sharpe':>7s}  {'MaxDD':>6s}  {'DSR':>5s}  {'GO':>3s}")
    print(f"  " + "-"*86)

    results = []
    for meta_thr in [0.40, 0.45, 0.50, 0.55, 0.60]:
        combined_signal = primary_signal_test & (p_meta_test > meta_thr)
        pnl_combined = pnl_test[combined_signal]
        m = compute_metrics(pnl_combined)
        nonzero = pnl_combined[pnl_combined != 0]
        if len(nonzero) >= 30:
            from scipy.stats import skew as _sk, kurtosis as _ku
            sk = float(_sk(nonzero))
            ku = float(_ku(nonzero, fisher=False))
        else:
            sk, ku = 0.0, 3.0
        dsr = deflated_sharpe_ratio(m["sharpe"], n_trials=N_TESTS, n_obs=m["n"],
                                     skewness=sk, kurtosis=ku)
        is_go = (m["pf"] >= 2.0 and m["wr"] >= 0.45 and m["n"] >= 30 and dsr > 0.95)
        go_str = "GO" if is_go else "NO"
        print(f"  {meta_thr:>10.2f}  {m['n']:>6,d}  {m['wr']*100:>6.1f}  {m['pf']:>6.2f}  "
              f"{m['ev']:>+7.1f}  {m['sharpe']:>+7.2f}  {m['max_dd']:>6.0f}  {dsr:>5.2f}  {go_str:>3s}")
        results.append({"meta_thr": meta_thr, **m, "dsr": dsr, "is_go": is_go})

    # ==========================================================================
    # CONCLUSION
    # ==========================================================================
    n_go = sum(1 for r in results if r["is_go"])
    print(f"\n{'='*100}")
    print(f"  CONCLUSION : {n_go}/5 thresholds meta passent GO Lopez")
    print(f"{'='*100}")

    # Best non-degenerate combo
    valid_results = [r for r in results if r["n"] >= 30]
    if valid_results:
        best_pf = max(valid_results, key=lambda r: r["pf"])
        best_wr = max(valid_results, key=lambda r: r["wr"])
        print(f"\n  Best PF combined : meta_thr={best_pf['meta_thr']:.2f}  "
              f"PF={best_pf['pf']:.2f} WR={best_pf['wr']*100:.1f}% N={best_pf['n']}")
        print(f"  Best WR combined : meta_thr={best_wr['meta_thr']:.2f}  "
              f"PF={best_wr['pf']:.2f} WR={best_wr['wr']*100:.1f}% N={best_wr['n']}")

        # Comparison vs primary-only
        print(f"\n  IMPROVEMENT vs primary-only :")
        print(f"    Best WR : ΔWR = {(best_wr['wr'] - m_primary['wr'])*100:+.1f}pp, "
              f"ΔPF = {best_wr['pf'] - m_primary['pf']:+.2f}, "
              f"ΔN = {best_wr['n'] - m_primary['n']:+,d}")
        if best_wr["wr"] >= 0.45 and best_wr["pf"] >= 2.0 and best_wr["dsr"] > 0.95:
            print(f"\n  ✅ META-LABELING UTILE : NQ_buy CAUTION → GO Lopez plein possible")
            print(f"     Recommandation : meta_thr={best_wr['meta_thr']:.2f}")
        else:
            print(f"\n  ⚠️  META-LABELING marginal : pas de GO clair, WR ne passe pas seuil")


if __name__ == "__main__":
    main()
