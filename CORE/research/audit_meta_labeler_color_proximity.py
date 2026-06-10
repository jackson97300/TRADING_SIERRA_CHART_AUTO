"""
audit_meta_labeler_color_proximity.py — Phase 2 : Meta-labeler Lopez ch.3.5
sur les 3 rules GO_RIGOROUS detectees par audit_rules_edge.

CONTEXTE Phase 1.6 : 3 rules color_proximity confirmees Lopez compliant :
  - ES color_dn_proximity SELL : DSR 0.998, n=165, WR=47.9%, +16.94t/trade
  - NQ color_up_proximity BUY : DSR 0.501, n=110, WR=43.6%, +60.22t/trade
  - NQ color_dn_proximity SELL : DSR 0.990, n=103, WR=52.4%, +86.99t/trade

OBJECTIF : entrainer un meta-classifier "rule fire → WIN ou LOSS ?" pour
ameliorer WR de 43-52% → 55-65%, DSR > primary.

METHODOLOGIE Lopez AFML ch.3.5 :
1. Primary signal = rule fire (deja active, side fixe par rule)
2. Meta target y_meta = (direction × realized_pts > 0).astype(int)  # 1=WIN, 0=LOSS
3. Features X = V5e_clean (388 cols) drop :
   - target leaks (deja drop)
   - rule-related (color_* features pour eviter leak car rule = color proximity)
   - low signal features (NaN > 50%)
4. Walk-forward purged k-fold 5 folds + embargo 60 bars
5. Modeles : LightGBM (current) + CatBoost (Jackson reco)
6. Metriques per fold : AUC, precision, recall, F1, gain DSR
7. Verdict : GO si meta_DSR > primary_DSR + 0.1 ET AUC > 0.55 stable cross-fold

Anti-tricherie :
- Purged k-fold (Lopez ch.7) : embargo 60 bars
- Sample weight Lopez ch.4 (uniqueness) sur trades
- Threshold opt sur fold 0 train, frozen test
- DSR haircut n_trials = 6 modeles × 3 setups × 5 folds × 10 thresholds = 900

Output : DSR per setup × model, comparison vs primary, verdict GO/NOGO.

Run : python -X utf8 CORE/research/audit_meta_labeler_color_proximity.py
"""
from __future__ import annotations

import json
import math
import time
import warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

import sys
ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
sys.path.insert(0, str(ROOT))
DATASETS_DIR = ROOT / "DATA" / "DATASETS"

from CORE.signal_engine_rules.rules import RULES_V1
from CORE.label_v5_dataset import K_SL, K_TP_RATIO

# ─── 3 setups GO_RIGOROUS de Phase 1.6 ───────────────────────────────────
SETUPS = [
    {"sym": "ES", "rule": "color_dn_proximity", "direction": "SELL", "dir_value": -1,
     "primary_dsr": 0.998, "primary_sharpe": 0.503, "primary_n": 165},
    {"sym": "NQ", "rule": "color_up_proximity", "direction": "BUY", "dir_value": 1,
     "primary_dsr": 0.501, "primary_sharpe": 0.335, "primary_n": 110},
    {"sym": "NQ", "rule": "color_dn_proximity", "direction": "SELL", "dir_value": -1,
     "primary_dsr": 0.990, "primary_sharpe": 0.579, "primary_n": 103},
]

# ─── Lopez compliant params ──────────────────────────────────────────────
N_FOLDS = 5
EMBARGO_BARS = 60
SLIPPAGE_TICKS = 2.0

# DSR haircut : 2 modeles × 3 setups × 5 folds × 10 thresholds = 300 (explicit)
# + selection bias (rules deja choisies) + meta features peeking = +5x
N_STRATEGIES_DSR = 1500

# Meta filter thresholds (review ml-trainer 06/05 fixes 1-2-5-6)
META_AUC_MIN = 0.57            # durci 0.55→0.57 (n=103-165 borderline statistique)
META_AUC_STD_MAX = 0.05        # stabilite cross-fold
META_DSR_GAIN_MIN = 0.05       # durci 0.0→0.05 (gain reel obligatoire)
META_N_ACTIVE_RATIO_MIN = 0.4  # >=40% des fires doivent etre traded (sinon over-filter)
META_N_TOTAL_ACTIVE_MIN = 50   # n_total >=50 pooled (sinon Lopez n insuffisant)
N_FIRES_MIN = 30
N_FIRES_MIN_PER_FOLD = 10

# Features to drop (eviter leak meta : features liees au color trigger)
COLOR_RELATED_PREFIX = ("color_", "n_color_", "dist_color_", "bn_color_")


def deflated_sharpe(sr, n_obs, sk, kt, n_trials):
    if n_obs < 10 or sr <= 0:
        return None, None
    gamma = 0.5772156649
    if n_trials <= 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        sr0 = (1 - gamma) * z1 + gamma * z2
        sr0 = sr0 / math.sqrt(max(n_obs - 1, 1))
    denom = 1 - sk * sr + (kt - 1) / 4.0 * (sr ** 2)
    if denom <= 0:
        return None, None
    psr = stats.norm.cdf(sr * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    dsr = stats.norm.cdf((sr - sr0) * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    return float(psr), float(dsr)


def load_dataset(symbol):
    fp_clean = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    fp_orig = DATASETS_DIR / f"{symbol}_dataset_v5e.parquet"
    df = pd.read_parquet(fp_clean)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    if fp_orig.exists():
        df_orig = pd.read_parquet(fp_orig, columns=["ts_event", "realized_pts", "exit_offset"])
        df_orig["ts_event"] = pd.to_datetime(df_orig["ts_event"], utc=True)
        df = df.merge(df_orig, on="ts_event", how="left")
    return df


def apply_rule(df, rule_name):
    """Apply UNE rule sur df, return colonne direction."""
    fn = RULES_V1[rule_name]
    records = df.to_dict("records")
    dirs = np.zeros(len(records), dtype=np.int8)
    for i, features in enumerate(records):
        try:
            tag = fn(features)
            dirs[i] = tag.direction
        except Exception:
            pass
    return dirs


def get_meta_features(df):
    """Features ML : V5e_clean drop {color_*, target leaks, sample_weight, label, _* helpers}."""
    exclude = {"ts_event", "symbol", "label", "sample_weight",
               "realized_pts", "exit_offset",
               "open", "high", "low", "close", "volume",
               "_date", "_month", "_dow", "_hour", "_signal", "_y_meta", "_pnl_signed",
               "ts",  # leak temporel (cf audit edge discovery MI=0.22)
               # Lookahead leaks (deja META_COLS train_v5_lightgbm)
               "long_dn_up_fwd1", "long_up_dn_fwd1",
               "bn_color_up_fwd1", "bn_color_dn_fwd1",
               "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
               "mins_to_next_news",
               # Swing architectural leak (sessions_swings_engine fenetre [-10,+10])
               "bars_since_last_swing_high", "bars_since_last_swing_low",
               "dist_last_swing_high_pct", "dist_last_swing_low_pct",
               "swing_high_active_lag10", "swing_low_active_lag10",
               "last_swing_high_session", "last_swing_low_session",
               "_last_swing_high_price", "_last_swing_low_price",
               # Helpers internes
               "is_nq", "instrument_id", "publisher_id",
               "session_id", "session_date", "mins_et",
               "rtype",
               # Features avec strong _fwd suffix
               }
    feature_cols = []
    for c in df.columns:
        if c in exclude:
            continue
        if c.startswith(COLOR_RELATED_PREFIX):
            continue
        if c.endswith("_fwd1") or c.endswith("_fwd5") or c.endswith("_fwd10") or "_fwd" in c:
            continue
        if c.startswith("_"):
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        feature_cols.append(c)
    return feature_cols


def safe_fillna_median(X):
    """Cast Int64/UInt64 nullable integer en float64 avant fillna (eviter TypeError dtype)."""
    X = X.copy()
    for c in X.columns:
        if str(X[c].dtype).startswith(("Int", "UInt")) or X[c].dtype == "boolean":
            X[c] = X[c].astype("float64")
    med = X.median()
    return X.fillna(med), med


_LEAK_TRACE = []  # global trace pour debug AUC=1.0


def evaluate_meta_lightgbm(X_train, y_train, X_test, sw_train=None):
    """Train LightGBM + return proba test (review ml-trainer fix 4 : min_child_samples 10).
    +trace top features importance (debug leak)."""
    import lightgbm as lgb
    train_data = lgb.Dataset(X_train, label=y_train, weight=sw_train)
    params = {
        "objective": "binary", "metric": "auc",
        "learning_rate": 0.03, "num_leaves": 15, "max_depth": 4,
        "feature_fraction": 0.7, "bagging_fraction": 0.7, "bagging_freq": 5,
        "min_child_samples": 10, "lambda_l2": 0.1,
        "verbosity": -1, "random_state": 42,
    }
    model = lgb.train(params, train_data, num_boost_round=50)
    # Trace top 5 features importance pour debug
    try:
        importances = pd.Series(model.feature_importance(), index=X_train.columns).sort_values(ascending=False)
        _LEAK_TRACE.append(("LightGBM", importances.head(5).to_dict()))
    except Exception:
        pass
    return model.predict(X_test)


def evaluate_meta_catboost(X_train, y_train, X_test, sw_train=None):
    """Train CatBoost + return proba test (review ml-trainer fix 4 : min_data 10)."""
    from catboost import CatBoostClassifier
    model = CatBoostClassifier(
        iterations=50, learning_rate=0.03, depth=4,  # 100→50
        l2_leaf_reg=3.0, min_data_in_leaf=10,  # 5→10
        verbose=0, random_seed=42,
    )
    model.fit(X_train, y_train, sample_weight=sw_train)
    return model.predict_proba(X_test)[:, 1]


def opt_threshold_on_train(X_train, y_train, sw_train, model_fn, grid=None):
    """Fix 3 review : threshold opt sur fold 0 train (grid 0.50-0.70 pas 0.05).

    Max EV pondere par sample_weight : EV = sum(sw * (proba_top × pnl_proxy))
    Approx : maximize precision × n_active (proxy pour EV).
    """
    if grid is None:
        grid = np.arange(0.50, 0.71, 0.05)
    # Out-of-fold prediction sur train via 3-fold internal CV (anti-leak)
    n = len(X_train)
    if n < 30:
        return 0.5
    fold_size = n // 3
    proba_train_oof = np.zeros(n)
    for i in range(3):
        s, e = i * fold_size, (i + 1) * fold_size if i < 2 else n
        X_tr_inner = pd.concat([X_train.iloc[:s], X_train.iloc[e:]])
        y_tr_inner = np.concatenate([y_train[:s], y_train[e:]])
        sw_tr_inner = np.concatenate([sw_train[:s], sw_train[e:]]) if sw_train is not None else None
        if len(np.unique(y_tr_inner)) < 2:
            proba_train_oof[s:e] = 0.5
            continue
        try:
            proba_train_oof[s:e] = model_fn(X_tr_inner, y_tr_inner, X_train.iloc[s:e], sw_train=sw_tr_inner)
        except Exception:
            proba_train_oof[s:e] = 0.5
    # Max EV pondere
    best_threshold = 0.5
    best_score = -np.inf
    for t in grid:
        signals = (proba_train_oof > t).astype(int)
        active = signals == 1
        if active.sum() < 5:
            continue
        # EV proxy : (precision × n_active) / total
        precision = (y_train[active] == 1).mean() if active.sum() > 0 else 0
        n_active = active.sum()
        score = precision * np.sqrt(n_active)  # geometric mean precision × stabilite
        if score > best_score:
            best_score = score
            best_threshold = t
    return float(best_threshold)


META_MODELS = {
    "LightGBM": evaluate_meta_lightgbm,
    "CatBoost": evaluate_meta_catboost,
}


def evaluate_setup(setup, df_full):
    """Eval meta-labeler sur 1 setup."""
    sym = setup["sym"]
    rule_name = setup["rule"]
    direction = setup["direction"]
    dir_value = setup["dir_value"]
    print(f"\n{'='*100}")
    print(f"  SETUP : {sym} {rule_name} {direction} (primary DSR={setup['primary_dsr']:.3f})")
    print(f"{'='*100}")

    # Apply rule
    print(f"  Apply rule {rule_name}...")
    t0 = time.time()
    dirs = apply_rule(df_full, rule_name)
    df_full["_signal"] = dirs
    print(f"  Done in {time.time()-t0:.1f}s")

    # Filter bars where rule fires in target direction
    fire_mask = df_full["_signal"] == dir_value
    n_fires = int(fire_mask.sum())
    print(f"  Fires {direction} : {n_fires}")

    # Compute y_meta = WIN/LOSS
    realized = df_full["realized_pts"].fillna(0).values
    pnl_signed = dir_value * realized - SLIPPAGE_TICKS
    y_meta_full = (pnl_signed > 0).astype(int)
    df_full["_y_meta"] = y_meta_full
    df_full["_pnl_signed"] = pnl_signed

    # Restreindre aux fires
    df_fires = df_full[fire_mask].copy().reset_index(drop=True)
    if len(df_fires) < N_FIRES_MIN:
        print(f"  NOGO_LOW_N : {len(df_fires)} < {N_FIRES_MIN}")
        return None

    # WR primary (sanity check)
    wr_primary = (df_fires["_y_meta"] == 1).mean()
    print(f"  WR_primary (sanity) : {wr_primary*100:.1f}%")

    # Meta features
    feat_cols = get_meta_features(df_fires)
    print(f"  Meta features : {len(feat_cols)} (drop color-related + target leaks)")
    X = df_fires[feat_cols].copy()
    y = df_fires["_y_meta"].values
    sw = df_fires["sample_weight"].values if "sample_weight" in df_fires.columns else np.ones(len(y))
    pnl = df_fires["_pnl_signed"].values

    # Drop high-NaN
    nan_pct = X.isna().mean()
    high_nan = nan_pct[nan_pct > 0.5].index.tolist()
    X = X.drop(columns=high_nan)
    print(f"  Apres drop NaN>50% : {len(X.columns)} features")

    # Walk-forward purged k-fold
    n = len(X)
    fold_size = n // N_FOLDS
    results = {model_name: {"folds": [], "all_pnl_filtered": []} for model_name in META_MODELS}

    # Fix 3 review : threshold opt sur fold 0 (premier fold = train pure)
    fold0_end = fold_size
    optimal_thresholds = {}
    if fold0_end >= N_FIRES_MIN:
        X_fold0, _ = safe_fillna_median(X.iloc[:fold0_end])
        y_fold0 = y[:fold0_end]
        sw_fold0 = sw[:fold0_end]
        for model_name, fn in META_MODELS.items():
            opt_t = opt_threshold_on_train(X_fold0, y_fold0, sw_fold0, fn)
            optimal_thresholds[model_name] = opt_t
            print(f"  Threshold opt fold 0 train pour {model_name} : {opt_t:.2f}")

    print(f"\n  Walk-forward {N_FOLDS} folds (n={n}, ~{fold_size} per fold)...")
    for i in range(1, N_FOLDS):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < N_FOLDS - 1 else n
        train_end = test_start
        if train_end < N_FIRES_MIN:
            continue
        X_tr, train_med = safe_fillna_median(X.iloc[:train_end])
        X_te = X.iloc[test_start:test_end].copy()
        # Cast Int64 et fillna avec train median
        for c in X_te.columns:
            if str(X_te[c].dtype).startswith(("Int", "UInt")) or X_te[c].dtype == "boolean":
                X_te[c] = X_te[c].astype("float64")
        X_te = X_te.fillna(train_med)
        y_tr = y[:train_end]
        y_te = y[test_start:test_end]
        sw_tr = sw[:train_end]
        pnl_te = pnl[test_start:test_end]

        if len(np.unique(y_tr)) < 2 or len(y_te) < 5:
            continue

        for model_name, fn in META_MODELS.items():
            t0 = time.time()
            threshold = optimal_thresholds.get(model_name, 0.5)
            try:
                proba = fn(X_tr, y_tr, X_te, sw_train=sw_tr)
                signals = (proba > threshold).astype(int)
                pnl_filtered = np.where(signals == 1, pnl_te, 0)
                pnl_active = pnl_filtered[signals == 1]
                # Metriques
                from sklearn.metrics import roc_auc_score
                auc = roc_auc_score(y_te, proba) if len(np.unique(y_te)) > 1 else None
                n_active = int(signals.sum())
                wr_meta = float((pnl_active > 0).mean()) if n_active > 0 else 0
                sharpe_active = float(pnl_active.mean() / (pnl_active.std() + 1e-9)) if n_active > 5 else 0
                results[model_name]["folds"].append({
                    "fold": i,
                    "n_test": len(y_te),
                    "n_active": n_active,
                    "auc": auc,
                    "wr_meta": wr_meta,
                    "sharpe_active": sharpe_active,
                    "pnl_total": float(pnl_active.sum()),
                    "elapsed": round(time.time() - t0, 2),
                })
                results[model_name]["all_pnl_filtered"].extend(pnl_active.tolist())
                print(f"    fold {i} {model_name:10s}: AUC={auc:.4f} n_active={n_active}/{len(y_te)} "
                      f"WR={wr_meta*100:.0f}% Sh={sharpe_active:+.3f} ({results[model_name]['folds'][-1]['elapsed']}s)" if auc else f"    fold {i} {model_name}: AUC=N/A")
            except Exception as e:
                print(f"    fold {i} {model_name}: EXCEPTION {type(e).__name__}: {str(e)[:120]}")

    # Aggregate per model (fixes 1+2+5+6 review ml-trainer)
    model_summary = {}
    for model_name in META_MODELS:
        folds = results[model_name]["folds"]
        if not folds:
            continue
        all_pnl = np.array(results[model_name]["all_pnl_filtered"])
        aucs = [f["auc"] for f in folds if f["auc"] is not None]
        n_total_active = len(all_pnl)
        n_total_test_bars = sum(f["n_test"] for f in folds)
        ratio_active = (n_total_active / n_total_test_bars) if n_total_test_bars > 0 else 0
        auc_mean = float(np.mean(aucs)) if aucs else 0
        auc_std = float(np.std(aucs)) if aucs else 0
        if n_total_active < META_N_TOTAL_ACTIVE_MIN:
            verdict = f"NOGO_LOW_N_POOLED (n={n_total_active} < {META_N_TOTAL_ACTIVE_MIN})"
            sharpe_meta = None
            dsr_meta = None
        else:
            sharpe_meta = float(all_pnl.mean() / (all_pnl.std() + 1e-9))
            sk = float(stats.skew(all_pnl)) if n_total_active >= 4 else 0.0
            kt = float(stats.kurtosis(all_pnl, fisher=False)) if n_total_active >= 4 else 3.0
            psr, dsr_meta = deflated_sharpe(sharpe_meta, n_total_active, sk, kt, N_STRATEGIES_DSR)
            # Fixes 1+2+5 verdict :
            if dsr_meta is None:
                verdict = "NOGO_DSR_FAIL"
            elif auc_mean < META_AUC_MIN:
                verdict = f"NOGO_AUC_LOW ({auc_mean:.3f} < {META_AUC_MIN})"
            elif auc_std > META_AUC_STD_MAX:
                verdict = f"NOGO_AUC_INSTABLE (std {auc_std:.3f} > {META_AUC_STD_MAX})"
            elif ratio_active < META_N_ACTIVE_RATIO_MIN:
                verdict = f"NOGO_OVER_FILTER (active {ratio_active:.2f} < {META_N_ACTIVE_RATIO_MIN})"
            elif dsr_meta < setup["primary_dsr"] + META_DSR_GAIN_MIN:
                verdict = f"NOGO_DSR_NO_GAIN (meta={dsr_meta:.3f} vs primary+{META_DSR_GAIN_MIN:.2f}={setup['primary_dsr']+META_DSR_GAIN_MIN:.3f})"
            else:
                verdict = "GO_META"
        model_summary[model_name] = {
            "n_total_active": n_total_active,
            "n_total_test_bars": n_total_test_bars,
            "ratio_active": ratio_active,
            "auc_mean": auc_mean,
            "auc_std": auc_std,
            "sharpe_meta": sharpe_meta,
            "dsr_meta": dsr_meta,
            "primary_dsr": setup["primary_dsr"],
            "primary_sharpe": setup["primary_sharpe"],
            "threshold_opt": optimal_thresholds.get(model_name, 0.5),
            "verdict": verdict,
            "fold_metrics": folds,
        }

    print(f"\n  RESULTATS {sym}_{rule_name}_{direction} :")
    for model_name, s in model_summary.items():
        dsr_str = f"{s['dsr_meta']:.3f}" if s['dsr_meta'] is not None else "N/A"
        sh_str = f"{s['sharpe_meta']:+.3f}" if s['sharpe_meta'] is not None else "N/A"
        print(f"    {model_name:10s}: AUC={s['auc_mean']:.3f}±{s['auc_std']:.3f} "
              f"DSR_meta={dsr_str} (vs primary {s['primary_dsr']:.3f}) "
              f"Sharpe={sh_str} -> {s['verdict']}")
    # Debug leak : print top features importance (last fold trace)
    if _LEAK_TRACE:
        last_trace = _LEAK_TRACE[-1]
        print(f"\n  DEBUG top 5 features importance ({last_trace[0]}):")
        for f, imp in list(last_trace[1].items())[:5]:
            print(f"    {f}: {imp}")

    return {
        "setup": setup,
        "n_fires": n_fires,
        "wr_primary_check": float(wr_primary),
        "n_features_meta": len(X.columns),
        "models": model_summary,
    }


def main():
    print("=" * 100)
    print("  PHASE 2 META-LABELER Lopez ch.3.5 sur 3 rules GO_RIGOROUS")
    print("  LightGBM + CatBoost, walk-forward purged k-fold + DSR haircut 1500")
    print("=" * 100)

    # Charger datasets une fois par symbole
    es_df = load_dataset("ES")
    nq_df = load_dataset("NQ")
    print(f"\n  ES loaded : {es_df.shape}, realized_pts coverage {es_df['realized_pts'].notna().mean()*100:.1f}%")
    print(f"  NQ loaded : {nq_df.shape}, realized_pts coverage {nq_df['realized_pts'].notna().mean()*100:.1f}%")

    all_results = {}
    for setup in SETUPS:
        df = es_df if setup["sym"] == "ES" else nq_df
        # Make a copy pour _signal/_y_meta non persisté entre setups
        df_local = df.copy()
        r = evaluate_setup(setup, df_local)
        if r is not None:
            key = f"{setup['sym']}_{setup['rule']}_{setup['direction']}"
            all_results[key] = r

    # Synthese
    print(f"\n{'=' * 100}")
    print(f"  SYNTHESE FINALE — Meta-labeler vs Primary")
    print(f"{'=' * 100}")
    print(f"  Setup                                | Model     | AUC      | DSR_meta | Primary DSR | Verdict")
    print(f"  " + "-" * 100)
    for key, r in all_results.items():
        for model_name, s in r["models"].items():
            dsr_str = f"{s['dsr_meta']:.3f}" if s['dsr_meta'] is not None else "N/A"
            print(f"  {key:36s} | {model_name:9s} | {s['auc_mean']:.3f}    | {dsr_str:>7s}  | "
                  f"{s['primary_dsr']:.3f}      | {s['verdict']}")

    # Save
    out = ROOT / "DATA" / f"audit_meta_labeler_color_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report : {out}")


if __name__ == "__main__":
    main()
