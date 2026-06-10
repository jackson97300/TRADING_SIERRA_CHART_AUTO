"""
train_v4_pure_lightgbm.py — Voie A 2026-05-24
==============================================

Pipeline ML LightGBM sur V4_pure 8 mois, 4 modeles (ES_BUY, ES_SELL, NQ_BUY, NQ_SELL).

ETAPES :
  1. Charge dataset v4_pure partitionne (ES.c.0 + NQ.c.0, oct 2025 - mai 2026)
  2. Applique Triple Barrier labels (TP/SL fixes calibres CLAUDE.md)
  3. Calcule sample_weight Lopez ch.4 (uniqueness)
  4. Pre-selection features (top-N par LightGBM importance fast pass) pour respecter
     Lopez Ch.7.6 (ratio n_trades/n_features >= 100 recommande, >= 10 minimum absolu)
  5. Pipeline complet train_lightgbm.py (preflight, walk-forward 12-fold, Optuna,
     meta-labeling, regime GEX, DSR/PSR/MC tests, baseline comparison)
  6. Verdict GO/NOGO par modele, rapport markdown ecrit dans DOCS/

Anti-patterns evites :
  - Pas de v4_enriched (incident #17 : pipeline incremental tronque avril)
  - Pas de random split (CLAUDE.md souverain)
  - Pre-selection sur fold #1 train UNIQUEMENT (pas de leakage sur folds futurs)
  - Respect ML_EXCLUDE_FEATURES (audit 27/04 ULTRATHINK Option C+)
  - DSR Phi correction avec n_trials reel (4 modeles testes)

Usage :
    python -X utf8 CORE/train_v4_pure_lightgbm.py
    python -X utf8 CORE/train_v4_pure_lightgbm.py --symbol ES
    python -X utf8 CORE/train_v4_pure_lightgbm.py --topn 50 --n-trials 50
    python -X utf8 CORE/train_v4_pure_lightgbm.py --skip-shap --skip-meta
"""
from __future__ import annotations

import sys
import time
import glob
import json
import pickle
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

import numpy as np
import pandas as pd
import numba

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
sys.path.insert(0, str(ROOT / "CORE"))

# Re-export du pipeline existant
import train_lightgbm as t_lgb
from train_lightgbm import (
    TrainConfig, ModelTrainer, walk_forward_splits,
    preflight_check, importance_guard, generate_report,
    PreflightError, ImportanceLeakError,
    _normalize_sample_weight, simulate_trades,
)

import lightgbm as lgb

# =============================================================================
# CONSTANTES (alignees CLAUDE.md + label_v4_dataset.py)
# =============================================================================

TICK_SIZE_BY_SYMBOL = {"ES": 0.25, "NQ": 0.25}
TP_TICKS = {"ES": 9, "NQ": 36}    # R:R 1.8 (Jackson 29/03)
SL_TICKS = {"ES": 5, "NQ": 20}
FORWARD_BARS = 20                  # 20 min horizon Triple Barrier

OUTPUT_DIR = ROOT / "DATA" / "MODELS" / "v4_pure_20260524"
LOGS_DIR = ROOT / "LOGS" / "ml_training"
REPORT_PATH = ROOT / "DOCS" / "EDGE_REPORT_LIGHTGBM_V4_PURE_20260524.md"


# =============================================================================
# 1. CHARGEMENT V4_PURE
# =============================================================================

def load_v4_pure(symbol: str) -> pd.DataFrame:
    """Charge ts partitions v4_pure pour un symbol, concat trie chronologique."""
    paths = sorted(glob.glob(str(
        ROOT / f"DATA/DATASETS/v4_pure/symbol={symbol}.c.0/year=*/month=*/data.parquet"
    )))
    if not paths:
        raise FileNotFoundError(f"Aucune partition v4_pure pour {symbol}")
    print(f"  [LOAD] {symbol}: {len(paths)} partitions")
    df_list = [pd.read_parquet(p) for p in paths]
    df = pd.concat(df_list, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"  [LOAD] {symbol}: {len(df):,} bars, range {df['ts_event'].min()} -> {df['ts_event'].max()}")
    return df


# =============================================================================
# 2. TRIPLE BARRIER LABELING (recopie de label_v4_dataset.py)
# =============================================================================

@numba.njit(cache=True)
def _simulate_tpsl_numba(highs, lows, closes, tp_pts, sl_pts, n_bars):
    """Triple Barrier propre (cf label_v4_dataset.py)."""
    n = len(closes)
    labels = np.zeros(n, dtype=np.int8)
    exit_offsets = np.full(n, n_bars, dtype=np.int32)
    realized = np.zeros(n, dtype=np.float32)

    for i in range(n - n_bars):
        entry = closes[i]
        tp_long = entry + tp_pts
        sl_long = entry - sl_pts
        tp_short = entry - tp_pts
        sl_short = entry + sl_pts

        buy_win = False
        buy_offset = n_bars
        for k in range(1, n_bars + 1):
            if i + k >= n:
                break
            h = highs[i + k]
            l = lows[i + k]
            if l <= sl_long:
                buy_offset = k
                break
            if h >= tp_long:
                buy_win = True
                buy_offset = k
                break

        sell_win = False
        sell_offset = n_bars
        for k in range(1, n_bars + 1):
            if i + k >= n:
                break
            h = highs[i + k]
            l = lows[i + k]
            if h >= sl_short:
                sell_offset = k
                break
            if l <= tp_short:
                sell_win = True
                sell_offset = k
                break

        if buy_win and sell_win:
            if buy_offset < sell_offset:
                labels[i] = 1
                exit_offsets[i] = buy_offset
                realized[i] = tp_pts
            elif sell_offset < buy_offset:
                labels[i] = -1
                exit_offsets[i] = sell_offset
                realized[i] = -tp_pts
            else:
                labels[i] = 0
                exit_offsets[i] = buy_offset
        elif buy_win:
            labels[i] = 1
            exit_offsets[i] = buy_offset
            realized[i] = tp_pts
        elif sell_win:
            labels[i] = -1
            exit_offsets[i] = sell_offset
            realized[i] = -tp_pts
        else:
            labels[i] = 0
            exit_offsets[i] = min(buy_offset, sell_offset)

    return labels, exit_offsets, realized


def compute_sample_weight_uniqueness(labels, exit_offsets):
    """Lopez AFML ch.4 sample_weight uniqueness."""
    n = len(labels)
    coverage = np.zeros(n, dtype=np.int32)
    for i in range(n):
        end = min(i + int(exit_offsets[i]), n)
        coverage[i:end] += 1

    weights = np.ones(n, dtype=np.float64)
    for i in range(n):
        end = min(i + int(exit_offsets[i]), n)
        if end > i:
            mean_cov = coverage[i:end].mean()
            weights[i] = 1.0 / max(1.0, mean_cov)
    return weights


def add_labels(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Ajoute label + sample_weight + ts (ms epoch) au df."""
    tick = TICK_SIZE_BY_SYMBOL[symbol]
    tp_pts = TP_TICKS[symbol] * tick
    sl_pts = SL_TICKS[symbol] * tick

    print(f"  [LABEL] {symbol}: TP={TP_TICKS[symbol]}t, SL={SL_TICKS[symbol]}t, H={FORWARD_BARS}bars")
    t0 = time.perf_counter()
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    labels, exit_offsets, realized = _simulate_tpsl_numba(
        highs, lows, closes, tp_pts, sl_pts, FORWARD_BARS
    )
    print(f"  [LABEL] {symbol}: {time.perf_counter()-t0:.1f}s")

    t0 = time.perf_counter()
    sw = compute_sample_weight_uniqueness(labels, exit_offsets)
    print(f"  [SW]    {symbol}: mean={sw.mean():.3f} ({time.perf_counter()-t0:.1f}s)")

    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_hold = int((labels == 0).sum())
    print(f"  [STATS] {symbol}: BUY={n_buy} ({n_buy/len(df)*100:.1f}%), "
          f"SELL={n_sell} ({n_sell/len(df)*100:.1f}%), HOLD={n_hold} ({n_hold/len(df)*100:.1f}%)")

    df = df.copy()
    df["label"] = labels.astype(np.int8)
    df["exit_offset"] = exit_offsets
    df["realized_pts"] = realized
    df["sample_weight"] = sw

    # ts en ms epoch (compat walk_forward_splits)
    df["ts"] = (df["ts_event"].astype("int64") // 1_000_000).astype("int64")

    # partial_session : derniers FORWARD_BARS pas labelisables proprement
    df["partial_session"] = False
    df.loc[df.index[-FORWARD_BARS:], "partial_session"] = True

    # sym pour cost detection dans simulate_trades
    df["sym"] = symbol

    return df


# =============================================================================
# 3. PRE-SELECTION FEATURES (anti incident #12 dimensionnalite)
# =============================================================================

# Local extension of ML_EXCLUDE_FEATURES (incident #13 du 20/05 + audit 24/05).
# Features ajoutees en mai 2026 (commit "parite batch/stream") qui sont
# mathematiquement LEAK look-ahead car derivees de _last_swing_*_price calcule
# via fenetre CENTREE [i-10:i+11] dans sessions_swings_engine.py:318-374.
# Voir CORE/sessions_swings_engine.py:373-374.
LOCAL_LEAKAGE_BLACKLIST = {
    "dist_swing_high",        # leak (sessions_swings_engine v2 fenetre centree)
    "dist_swing_low",         # leak (sessions_swings_engine v2 fenetre centree)
    "_last_swing_high_price", # helper interne lookahead
    "_last_swing_low_price",  # helper interne lookahead
}


def get_features_v4_pure(df: pd.DataFrame, max_nan_pct: float = 0.90) -> List[str]:
    """Liste features candidates (apres ML_EXCLUDE_FEATURES + filtres techniques).

    Filtres v4_pure :
    - ML_EXCLUDE_FEATURES (build_dataset_v4_dmp_databento.py:68 + LOCAL_LEAKAGE)
    - NaN ratio > max_nan_pct (defaut 90%)
    - Features constantes (nunique <= 1)
    """
    base = t_lgb.get_features(df)
    # Drop local leakage (incident #13 20/05)
    base = [c for c in base if c not in LOCAL_LEAKAGE_BLACKLIST]

    valid = []
    dropped_nan = []
    dropped_const = []
    for c in base:
        if c not in df.columns:
            continue
        nan_ratio = df[c].isna().mean()
        if nan_ratio > max_nan_pct:
            dropped_nan.append(c)
            continue
        if df[c].nunique(dropna=True) <= 1:
            dropped_const.append(c)
            continue
        valid.append(c)
    if dropped_nan:
        print(f"  [FEATS] Drop {len(dropped_nan)} features (NaN > {max_nan_pct:.0%}) "
              f"ex: {dropped_nan[:5]}")
    if dropped_const:
        print(f"  [FEATS] Drop {len(dropped_const)} features constantes "
              f"ex: {dropped_const[:5]}")
    print(f"  [FEATS] LOCAL_LEAKAGE_BLACKLIST applied: {sorted(LOCAL_LEAKAGE_BLACKLIST)}")
    return valid


def preselect_features_lightgbm(
    df: pd.DataFrame,
    candidates: List[str],
    symbol: str,
    side: str,
    top_n: int = 60,
    min_train_days: int = 30,
) -> List[str]:
    """Pre-selection : entraine 1 LightGBM rapide sur les premiers ~30 jours,
    garde les top_N features par importance MDI.

    Pourquoi : respecter Lopez Ch.7.6 ratio n_trades/n_features.
    Sur v4_pure 218k bars ES, n labels positifs ~50k, en walk-forward 12 folds
    ~4k trades/fold. Avec 229 features brutes, ratio = 17 (sous le 100 recommande).
    Reduire a 60 features = ratio 67 (mieux, proche recommande).

    Pas de leakage : on prend uniquement le premier fold train (chronologique),
    le test des folds 1-12 reste vierge.
    """
    target = 1 if side == "buy" else -1

    # Premier fold train (chronologique)
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date
    unique_days = sorted(dates.unique())
    if len(unique_days) < min_train_days + 7:
        print(f"  [PRESEL] {symbol} {side}: pas assez de jours, retourne candidates entiers ({len(candidates)})")
        return candidates

    train_days = set(unique_days[:min_train_days])
    train_mask = dates.isin(train_days)
    train_df = df[train_mask].reset_index(drop=True)

    X = train_df[candidates]
    y = (train_df["label"] == target).astype(int).values
    sw = _normalize_sample_weight(train_df["sample_weight"].values) if "sample_weight" in train_df.columns else None

    if y.sum() < 50:
        print(f"  [PRESEL] {symbol} {side}: <50 positifs sur fold pre-sel, retourne candidates entiers")
        return candidates

    # Fit rapide (params defaut, no Optuna)
    params = t_lgb._default_params()
    model = lgb.LGBMClassifier(**params)
    if sw is not None:
        model.fit(X, y, sample_weight=sw)
    else:
        model.fit(X, y)

    imp = pd.DataFrame({
        "feature": candidates,
        "mdi": model.feature_importances_,
    }).sort_values("mdi", ascending=False)

    selected = imp.head(top_n)["feature"].tolist()
    print(f"  [PRESEL] {symbol} {side}: {len(candidates)} -> {len(selected)} features (top-{top_n} MDI sur {min_train_days}j)")
    print(f"  [PRESEL] {symbol} {side}: top10 = {selected[:10]}")
    return selected


# =============================================================================
# 4. PIPELINE PRINCIPAL PAR SYMBOL
# =============================================================================

def train_one_symbol(
    symbol: str,
    config: TrainConfig,
    tune: bool = True,
    top_n_preselect: int = 60,
) -> List[Dict]:
    """Pipeline complet pour 1 symbol : load + label + preselect + train BUY/SELL."""
    print(f"\n{'#'*70}\n# {symbol} V4_PURE\n{'#'*70}")

    # 1. Load + label
    df = load_v4_pure(symbol)
    df = add_labels(df, symbol)
    candidates = get_features_v4_pure(df)
    print(f"  [FEATS] {symbol}: {len(candidates)} candidates apres ML_EXCLUDE")

    # 2. Preflight (skip quality_validator car v4)
    try:
        preflight_check(symbol, df, candidates, config)
    except PreflightError as e:
        print(f"[FATAL] Preflight {symbol}: {e}")
        return []

    # 3. Train BUY + SELL
    trainer = ModelTrainer(config)
    results = []

    for side in ["buy", "sell"]:
        # Pre-selection features (anti dimensionnalite incident #12)
        if top_n_preselect > 0 and top_n_preselect < len(candidates):
            try:
                features = preselect_features_lightgbm(
                    df, candidates, symbol, side, top_n=top_n_preselect,
                    min_train_days=config.min_train_days,
                )
            except Exception as e:
                print(f"  [PRESEL] {symbol} {side}: echec ({e}), garde candidates entiers")
                features = candidates
        else:
            features = candidates

        # Train
        result = trainer.train_model(symbol, side, df, features, tune=tune)

        # Importance guard (post-train)
        if result.get("model") is not None:
            try:
                importance_guard(
                    model=result["model"],
                    features=features,
                    symbol=symbol,
                    side=side,
                )
                result["leak_detected"] = None
            except ImportanceLeakError as e:
                print(f"[LEAK] {symbol} {side}: {e}")
                result["leak_detected"] = str(e)

        # SHAP top features (skip si flag)
        if "--skip-shap" not in sys.argv and result.get("model") is not None:
            try:
                result["shap_top"] = compute_shap_top(result["model"], df[features], features, top=20)
            except Exception as e:
                print(f"  [SHAP] {symbol} {side}: echec ({e})")
                result["shap_top"] = []
        else:
            result["shap_top"] = []

        # Save model
        try:
            save_v4_pure_model(result, symbol, side)
        except Exception as e:
            print(f"  [SAVE] {symbol} {side}: echec ({e})")

        results.append(result)

    return results


# =============================================================================
# 5. SHAP TOP FEATURES
# =============================================================================

def compute_shap_top(model, X: pd.DataFrame, features: List[str], top: int = 20) -> List[Dict]:
    """SHAP mean(|value|) top-N features (sample 5000 pour vitesse)."""
    import shap
    n_sample = min(5000, len(X))
    X_sample = X.sample(n=n_sample, random_state=42) if len(X) > n_sample else X
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)
    # LightGBM binary : shap_values est array (n_samples, n_features)
    if isinstance(shap_values, list):
        shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]
    mean_abs = np.abs(shap_values).mean(axis=0)
    df_shap = pd.DataFrame({
        "feature": features,
        "shap_mean_abs": mean_abs,
    }).sort_values("shap_mean_abs", ascending=False).head(top)
    return df_shap.to_dict(orient="records")


# =============================================================================
# 6. SAVE
# =============================================================================

def save_v4_pure_model(result: Dict, symbol: str, side: str):
    """Sauvegarde modele + config + folds + importance dans v4_pure_20260524/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{symbol}_{side.upper()}"

    # Model pickle
    model_path = OUTPUT_DIR / f"{prefix}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": result.get("model"),
            "meta_model": result.get("meta_model"),
            "threshold": result.get("threshold"),
            "features": result.get("features"),
            "meta_features": result.get("meta_features", []),
            "verdict": result.get("verdict"),
            "leak_detected": result.get("leak_detected"),
            "shap_top": result.get("shap_top", []),
            "aggregate": result.get("aggregate", {}),
        }, f)

    # Config JSON
    config_data = {
        "symbol": symbol,
        "side": side,
        "threshold": result.get("threshold"),
        "n_features": len(result.get("features", [])),
        "verdict": result.get("verdict"),
        "leak_detected": result.get("leak_detected"),
        "aggregate": {k: (v if not isinstance(v, float) or np.isfinite(v) else None)
                      for k, v in result.get("aggregate", {}).items()},
        "trained_at": datetime.utcnow().isoformat() + "Z",
    }
    cfg_path = OUTPUT_DIR / f"{prefix}_config.json"
    with open(cfg_path, "w") as f:
        json.dump(config_data, f, indent=2, default=str)

    # Folds
    folds_path = OUTPUT_DIR / f"{prefix}_folds.json"
    with open(folds_path, "w") as f:
        json.dump(result.get("fold_metrics", []), f, indent=2, default=str)

    # Importance (MDI + MDA si dispo)
    imp = result.get("importance")
    if imp is not None and not imp.empty:
        imp_path = OUTPUT_DIR / f"{prefix}_importance.csv"
        imp.to_csv(imp_path, index=False)

    # SHAP top
    if result.get("shap_top"):
        shap_path = OUTPUT_DIR / f"{prefix}_shap_top.csv"
        pd.DataFrame(result["shap_top"]).to_csv(shap_path, index=False)

    print(f"  [SAVE] {prefix}: {model_path.name}, {cfg_path.name}, folds, importance")


# =============================================================================
# 7. RAPPORT MARKDOWN
# =============================================================================

def _fmt(x, fmt=".2f", na="n/a"):
    try:
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return na
        return format(x, fmt)
    except Exception:
        return na


def generate_markdown_report(all_results: List[Dict], config: TrainConfig):
    """Rapport executif markdown structure pour Jackson."""
    lines = []
    lines.append(f"# EDGE REPORT — LightGBM V4_PURE (4 modeles ES/NQ x BUY/SELL)")
    lines.append("")
    lines.append(f"**Date** : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Mandat** : Voie A — Valider empiriquement edge ML LightGBM sur features V4_pure "
                 f"apres 16 NOGO advisory rule-based (rapport 20/05).")
    lines.append("")
    lines.append(f"**Periode** : oct 2025 -> mai 2026 (8 mois, ~218k bars ES + ~217k bars NQ)")
    lines.append(f"**Labels** : Triple Barrier fixes — ES SL=5t TP=9t, NQ SL=20t TP=36t (R:R 1.8), H={FORWARD_BARS}bars")
    lines.append(f"**Validation** : Walk-forward 12 folds chronologiques, purge/embargo Lopez ch.7")
    lines.append(f"**Tuning** : Optuna {config.n_trials} trials, split 80/20 inner train")
    lines.append(f"**Couts** : ES {config.cost_ticks_es}t/trade, NQ {config.cost_ticks_nq}t/trade")
    lines.append(f"**Seuils GO** : PF>=1.3, EV>=1.0t, WR>=45%, Trades/jour>=3, MaxDD<=500t, DSR>=0.95, PSR>=0.95")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== VERDICT EXECUTIF =====
    lines.append("## VERDICT EXECUTIF")
    lines.append("")
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        verd = r.get("verdict", "n/a")
        agg = r.get("aggregate", {})
        pf = _fmt(agg.get("profit_factor"), ".2f")
        dsr = _fmt(agg.get("dsr"), ".2f")
        n = agg.get("total_trades", 0)
        leak = r.get("leak_detected")
        leak_tag = " **[LEAK DETECTE]**" if leak else ""
        lines.append(f"- **{sym} {side}** : `{verd}` "
                     f"(PF={pf}, DSR={dsr}, n={n}){leak_tag}")
    lines.append("")

    # ===== TABLEAU GLOBAL =====
    lines.append("## TABLEAU GLOBAL — Aggregate cross-folds")
    lines.append("")
    lines.append("| Modele | n trades | n folds | WR% | PF | PF med | EV/t | Max DD | Sharpe | DSR | PSR | MC p | HHI | Verdict |")
    lines.append("|--------|---------:|--------:|----:|---:|-------:|-----:|-------:|-------:|----:|----:|-----:|----:|--------|")
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        agg = r.get("aggregate", {})
        verd = r.get("verdict", "?")
        # Verdict court
        verd_short = verd.split("(")[0].strip()[:18]
        lines.append(f"| {sym} {side} | "
                     f"{agg.get('total_trades', 0)} | "
                     f"{agg.get('n_valid_folds', 0)} | "
                     f"{_fmt(agg.get('win_rate', 0)*100, '.1f')} | "
                     f"{_fmt(agg.get('profit_factor'), '.2f')} | "
                     f"{_fmt(agg.get('pf_median'), '.2f')} | "
                     f"{_fmt(agg.get('ev_per_trade'), '+.2f')} | "
                     f"{_fmt(agg.get('max_drawdown'), '.0f')} | "
                     f"{_fmt(agg.get('sharpe'), '.2f')} | "
                     f"{_fmt(agg.get('dsr'), '.3f')} | "
                     f"{_fmt(agg.get('psr'), '.3f')} | "
                     f"{_fmt(agg.get('mc_p_value'), '.3f')} | "
                     f"{_fmt(agg.get('return_hhi'), '.3f')} | "
                     f"{verd_short} |")
    lines.append("")

    # ===== PER-FOLD DETAILS =====
    lines.append("## PER-FOLD DETAILS")
    lines.append("")
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        folds = r.get("fold_metrics", [])
        if not folds:
            continue
        lines.append(f"### {sym} {side}")
        lines.append("")
        lines.append("| Fold | Dates | Trades | WR% | PF | EV/t | PnL t | MaxDD | Trades/j |")
        lines.append("|-----:|-------|-------:|----:|---:|-----:|------:|------:|---------:|")
        for fm in folds:
            pf_val = fm.get("profit_factor", float("nan"))
            lines.append(f"| {fm.get('fold')} | "
                         f"{fm.get('dates', '')} | "
                         f"{fm.get('trades', 0)} | "
                         f"{_fmt(fm.get('win_rate', 0)*100, '.0f')} | "
                         f"{_fmt(pf_val, '.2f')} | "
                         f"{_fmt(fm.get('ev_trade'), '+.2f')} | "
                         f"{_fmt(fm.get('pnl_ticks'), '+.0f')} | "
                         f"{_fmt(fm.get('max_dd'), '.0f')} | "
                         f"{_fmt(fm.get('trades_day'), '.1f')} |")
        lines.append("")

    # ===== SHAP TOP 20 =====
    lines.append("## TOP 20 FEATURES SHAP (mean |value|)")
    lines.append("")
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        shap_top = r.get("shap_top", [])
        if not shap_top:
            lines.append(f"### {sym} {side}")
            lines.append("(SHAP non calcule ou skipped)")
            lines.append("")
            continue
        lines.append(f"### {sym} {side}")
        lines.append("")
        lines.append("| Rank | Feature | SHAP mean |val| |")
        lines.append("|-----:|---------|----------------:|")
        for i, row in enumerate(shap_top[:20], 1):
            lines.append(f"| {i} | `{row['feature']}` | {row['shap_mean_abs']:.6f} |")
        lines.append("")

    # ===== DIAGNOSTIC ANTI-LEAK =====
    lines.append("## DIAGNOSTIC ANTI-LEAK")
    lines.append("")
    lines.append("**Preflight** : verifie labels presents, BUY+SELL>0, sample_weight valide, "
                 "NaN <= 90% (v4), pas de feature constante, tri chronologique sur `ts`.")
    lines.append("**Importance guard** : aucune feature ne doit depasser 40% importance, top5 cumul <70%, "
                 ">=30 features actives (>1%).")
    lines.append("")
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        leak = r.get("leak_detected")
        if leak:
            lines.append(f"- **{sym} {side}** : LEAK DETECTE — {leak}")
        else:
            lines.append(f"- {sym} {side} : OK (preflight + importance guard passes)")
    lines.append("")

    # ===== COMPARAISON ADVISORY =====
    lines.append("## COMPARAISON vs ADVISORY (rapport 20/05)")
    lines.append("")
    lines.append("Advisory V_BASE 16 variants : tous PF < 0.78, tous WR < 32%, tous DSR ~ 0.0.")
    lines.append("Ratio comparatif :")
    lines.append("")
    lines.append("| Modele | Advisory PF | ML PF | Advisory WR | ML WR | Delta PF | Delta WR |")
    lines.append("|--------|-----------:|------:|------------:|------:|---------:|---------:|")
    # Advisory baselines (de EDGE_REPORT_ADVISORY_V4_PURE.md)
    ADV_PF = {("ES", "BUY"): 0.65, ("ES", "SELL"): 0.65, ("NQ", "BUY"): 0.31, ("NQ", "SELL"): 0.31}
    ADV_WR = {("ES", "BUY"): 0.32, ("ES", "SELL"): 0.32, ("NQ", "BUY"): 0.173, ("NQ", "SELL"): 0.173}
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        agg = r.get("aggregate", {})
        adv_pf = ADV_PF.get((sym, side), float("nan"))
        adv_wr = ADV_WR.get((sym, side), float("nan"))
        ml_pf = agg.get("profit_factor", float("nan"))
        ml_wr = agg.get("win_rate", float("nan"))
        d_pf = ml_pf - adv_pf if (np.isfinite(ml_pf) and np.isfinite(adv_pf)) else float("nan")
        d_wr = (ml_wr - adv_wr) if (np.isfinite(ml_wr) and np.isfinite(adv_wr)) else float("nan")
        lines.append(f"| {sym} {side} | {_fmt(adv_pf, '.2f')} | {_fmt(ml_pf, '.2f')} | "
                     f"{_fmt(adv_wr*100, '.1f')} | {_fmt(ml_wr*100, '.1f')} | "
                     f"{_fmt(d_pf, '+.2f')} | {_fmt(d_wr*100, '+.1f')}pp |")
    lines.append("")

    # ===== RECOMMANDATION =====
    lines.append("## RECOMMANDATION HONNETE")
    lines.append("")
    n_go = sum(1 for r in all_results if r.get("verdict") == "GO")
    n_caution = sum(1 for r in all_results if "CAUTION" in str(r.get("verdict", "")))
    n_nogo = sum(1 for r in all_results if "NO-GO" in str(r.get("verdict", "")))
    lines.append(f"- {n_go}/4 modeles GO, {n_caution}/4 CAUTION, {n_nogo}/4 NO-GO")
    lines.append("")

    if n_go >= 1:
        lines.append("**Decision** : envisager paper Sim2 sur les modeles GO uniquement, sizing 1 micro.")
        lines.append("Verifier d'abord : (1) absence de leak (importance guard pass), "
                     "(2) stabilite cross-folds (PF std < 50% du mean), "
                     "(3) DSR >= 0.95 sur 8+/12 folds.")
    elif n_caution >= 1:
        lines.append("**Decision** : ne PAS deployer en paper. Modeles CAUTION = edge marginal, "
                     "risque d'overfit eleve. Recommandation : relabeler avec triple-barrier ATR-dynamique "
                     "(comme label_v5) avant de conclure. Si encore CAUTION : abandonner LightGBM v4_pure.")
    else:
        lines.append("**Decision** : NOGO total comme advisory. **L'edge ML LightGBM n'existe pas sur ce dataset "
                     "avec ces labels TP/SL fixes.**")
        lines.append("")
        lines.append("Hypotheses pour expliquer le NOGO :")
        lines.append("1. **Labels TP/SL fixes inadaptes** : 5/9t ES ou 20/36t NQ pas alignes avec volatilite "
                     "intraday variable. Tester label_v5 (ATR-dynamique K_SL=1.5).")
        lines.append("2. **Drift directionnel** : ES +11% / NQ +18% sur la periode = biais haussier "
                     "favorise BUY mecaniquement. Labels Triple Barrier symetriques masquent ce biais.")
        lines.append("3. **Features V4_pure trop bruyantes** : 229 candidates, signaux noyes. "
                     "Tester feature selection Lopez Ch.8 (MDA + cluster Spearman) avant LightGBM.")
        lines.append("4. **Edge ML inexistant a horizon 20 min** : peut-etre que l'edge est a horizon plus court "
                     "(5-10 bars) ou plus long (60+ bars). Tester variations FORWARD_BARS.")
        lines.append("5. **Meta-labeling pourrait sauver** : primary tres permissif + meta filtre faux positifs. "
                     "Code deja en place (`enable_meta_wf`), evaluer son apport reel.")
        lines.append("")
        lines.append("**Voie B (forensique trades gagnants Bot 1 ES SHORT + Bot 2 V6 NQ SHORT) reste prioritaire.**")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**Outputs** :")
    lines.append(f"- Modeles : `DATA/MODELS/v4_pure_20260524/{{ES,NQ}}_{{BUY,SELL}}.pkl`")
    lines.append(f"- Configs : `DATA/MODELS/v4_pure_20260524/*_config.json`")
    lines.append(f"- Folds   : `DATA/MODELS/v4_pure_20260524/*_folds.json`")
    lines.append(f"- Importance : `DATA/MODELS/v4_pure_20260524/*_importance.csv`")
    lines.append(f"- SHAP top : `DATA/MODELS/v4_pure_20260524/*_shap_top.csv`")
    lines.append(f"- Logs : `LOGS/ml_training/lightgbm_v4_pure_20260524_*.log`")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[REPORT] Markdown ecrit dans {REPORT_PATH}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Config
    config = TrainConfig()
    setattr(config, "dataset_version", "v4")  # active branche NaN <=90%
    setattr(config, "n_trials_dsr", 4)         # 4 modeles testes = N_trials DSR

    # CLI overrides
    if "--n-trials" in sys.argv:
        idx = sys.argv.index("--n-trials")
        if idx + 1 < len(sys.argv):
            config.n_trials = int(sys.argv[idx + 1])

    top_n = 60
    if "--topn" in sys.argv:
        idx = sys.argv.index("--topn")
        if idx + 1 < len(sys.argv):
            top_n = int(sys.argv[idx + 1])

    # Disable meta-WF par defaut pour vitesse (peut etre lourd) sauf --enable-meta-wf
    if "--enable-meta-wf" in sys.argv:
        setattr(config, "enable_meta_wf", True)
    else:
        setattr(config, "enable_meta_wf", False)

    symbols = ["ES", "NQ"]
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbols = [sys.argv[idx + 1].upper()]

    tune = "--no-tune" not in sys.argv

    print(f"\n{'='*70}")
    print(f"TRAIN V4_PURE LIGHTGBM — Voie A 2026-05-24")
    print(f"{'='*70}")
    print(f"  Symbols       : {symbols}")
    print(f"  Tune          : {tune} ({config.n_trials} trials)")
    print(f"  Top-N presel  : {top_n}")
    print(f"  Meta WF       : {config.enable_meta_wf}")
    print(f"  Output dir    : {OUTPUT_DIR}")
    print(f"  Report path   : {REPORT_PATH}")
    print(f"{'='*70}")

    # Log file
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"lightgbm_v4_pure_20260524_{int(time.time())}.log"

    all_results = []
    t_start = time.time()
    for sym in symbols:
        results = train_one_symbol(sym, config, tune=tune, top_n_preselect=top_n)
        all_results.extend(results)

    elapsed = time.time() - t_start
    print(f"\n[TIME] Total {elapsed:.0f}s ({elapsed/60:.1f}min)")

    if all_results:
        generate_markdown_report(all_results, config)

    # Verdict global
    print(f"\n{'='*70}")
    print(f"  VERDICT GLOBAL V4_PURE LIGHTGBM")
    print(f"{'='*70}")
    for r in all_results:
        sym = r.get("symbol", "?")
        side = r.get("side", "?").upper()
        verd = r.get("verdict", "n/a")
        agg = r.get("aggregate", {})
        pf = agg.get("profit_factor", float("nan"))
        dsr = agg.get("dsr", float("nan"))
        n = agg.get("total_trades", 0)
        print(f"  {sym} {side}: {verd}  | PF={_fmt(pf, '.2f')} DSR={_fmt(dsr, '.3f')} n={n}")
    print(f"{'='*70}")
