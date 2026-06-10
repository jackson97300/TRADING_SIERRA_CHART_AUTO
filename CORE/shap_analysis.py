"""
SHAP Analysis pour MIA V2 Meta-Labeling (17/04/2026)
=======================================================

Revele les COMBINAISONS de features qui filtrent les VRAIS winners du meta model.

Repond a la question de Jackson :
    "Faire l'inverse : laisser les donnees parler au lieu de coder des strategies
     a priori - trouver les meilleures combinaisons que le test nous revele"

Methodologie :
    1. Charge meta_model pickle (LightGBM binaire entraine sur winners/losers primary)
    2. Charge dataset v3 + features meta
    3. SHAP values : importance individuelle de chaque feature
    4. SHAP interaction values : importance des PAIRES de features (revele combinaisons)
    5. Rank top 15 interactions + top 15 features seules
    6. Sauvegarde rapport markdown + CSV + PNG dependence plots

USAGE :
    python -X utf8 CORE/shap_analysis.py                     # ES buy + sell
    python -X utf8 CORE/shap_analysis.py --symbol ES --side buy
    python -X utf8 CORE/shap_analysis.py --n-interactions 20

Output :
    DATA/SHAP_ANALYSIS/{SYMBOL}_{SIDE}_report.md
    DATA/SHAP_ANALYSIS/{SYMBOL}_{SIDE}_shap_values.csv
    DATA/SHAP_ANALYSIS/{SYMBOL}_{SIDE}_interactions.csv
    DATA/SHAP_ANALYSIS/{SYMBOL}_{SIDE}_top_interactions.png (optional)
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler import build_meta_features  # noqa: E402

MODELS_DIR = Path("DATA/MODELS")
DATASETS_DIR = Path("DATA/DATASETS")
OUTPUT_DIR = Path("DATA/SHAP_ANALYSIS")


# ─────────────────────────────────────────────────────────────────────────────
# CHARGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def load_meta_and_primary(symbol: str, side: str):
    """Charge le meta model + primary model + config."""
    prefix = f"{symbol}_{side}"

    primary_path = MODELS_DIR / f"{prefix}_model.pkl"
    meta_path = MODELS_DIR / f"{prefix}_meta_model.pkl"
    config_path = MODELS_DIR / f"{prefix}_config.json"

    if not primary_path.exists():
        raise FileNotFoundError(f"Primary model absent: {primary_path}")
    if not meta_path.exists():
        raise FileNotFoundError(f"Meta model absent: {meta_path}")
    if not config_path.exists():
        raise FileNotFoundError(f"Config absent: {config_path}")

    with open(primary_path, "rb") as f:
        primary = pickle.load(f)
    with open(meta_path, "rb") as f:
        meta = pickle.load(f)
    with open(config_path, "r") as f:
        config = json.load(f)

    return primary, meta, config


def load_dataset(symbol: str) -> pd.DataFrame:
    """Charge le dataset v3 (post-backfill 7 mois)."""
    # Essayer v3 d'abord, puis v2 fallback
    for version in ["v3", "v2"]:
        path = DATASETS_DIR / f"{symbol}_dataset_{version}.parquet"
        if path.exists():
            print(f"  [load] {path.name}")
            return pd.read_parquet(path)
    raise FileNotFoundError(f"Aucun dataset {symbol} trouve dans {DATASETS_DIR}")


# ─────────────────────────────────────────────────────────────────────────────
# SHAP ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def compute_shap_values(meta_model, X_meta: pd.DataFrame) -> np.ndarray:
    """Calcule les SHAP values (importance individuelle par feature).

    Pour un modele binaire LightGBM, shap_values est de shape (N, F).
    """
    explainer = shap.TreeExplainer(meta_model)
    shap_values = explainer.shap_values(X_meta)
    # Pour binary LightGBM, shap_values peut etre shape (N, F) ou (2, N, F) selon version
    if isinstance(shap_values, list):
        shap_values = shap_values[1]  # classe positive
    elif shap_values.ndim == 3:
        shap_values = shap_values[:, :, 1]  # classe positive
    return shap_values


def compute_shap_interactions(meta_model, X_meta: pd.DataFrame,
                               max_samples: int = 2000) -> np.ndarray:
    """Calcule les SHAP interaction values (matrice (N, F, F)).

    ATTENTION : coût O(N * F^2 * trees). Sur 10k trades x 10 features x 200 trees,
    ça peut prendre quelques minutes. On echantillonne max_samples pour rester
    sous 1-2 min.
    """
    # Subsample si trop de data (garde distribution representative)
    if len(X_meta) > max_samples:
        sample_idx = np.random.RandomState(42).choice(
            len(X_meta), max_samples, replace=False)
        X_sample = X_meta.iloc[sample_idx].copy()
    else:
        X_sample = X_meta

    print(f"  [shap] computing interactions on {len(X_sample)} samples...")
    explainer = shap.TreeExplainer(meta_model)
    interactions = explainer.shap_interaction_values(X_sample)
    # Pour binary : peut etre list de 2 arrays
    if isinstance(interactions, list):
        interactions = interactions[1]
    elif interactions.ndim == 4:
        interactions = interactions[:, :, :, 1]
    return interactions


def rank_features(shap_values: np.ndarray, feature_names: list[str]) -> pd.DataFrame:
    """Rank features par magnitude SHAP moyenne."""
    mean_abs_shap = np.abs(shap_values).mean(axis=0)
    df = pd.DataFrame({
        "feature": feature_names,
        "mean_abs_shap": mean_abs_shap,
    })
    return df.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)


def rank_interactions(interactions: np.ndarray,
                      feature_names: list[str]) -> pd.DataFrame:
    """Rank les PAIRES de features par magnitude d'interaction moyenne.

    interactions shape = (N, F, F). On prend la magnitude moyenne (off-diagonale).
    """
    int_matrix = np.abs(interactions).mean(axis=0)  # (F, F)
    # Zero la diagonale (= SHAP values individuels, deja captures)
    np.fill_diagonal(int_matrix, 0)

    pairs = []
    F = len(feature_names)
    for i in range(F):
        for j in range(i + 1, F):
            # Interactions sont symétriques, on prend la somme |i,j| + |j,i|
            strength = int_matrix[i, j] + int_matrix[j, i]
            pairs.append({
                "feature_a": feature_names[i],
                "feature_b": feature_names[j],
                "interaction_strength": strength,
            })
    return pd.DataFrame(pairs).sort_values(
        "interaction_strength", ascending=False).reset_index(drop=True)


def analyze_top_interactions(shap_values: np.ndarray,
                              X_meta: pd.DataFrame,
                              top_pairs: pd.DataFrame,
                              y_meta: np.ndarray,
                              n_top: int = 10) -> pd.DataFrame:
    """Pour chaque top interaction, calcule les stats :
        - Quand feature_A et feature_B sont 'hautes' (p75+), winrate observe
        - Comparer au winrate baseline global
    """
    feature_names = list(X_meta.columns)
    base_winrate = float(y_meta.mean())

    results = []
    for _, row in top_pairs.head(n_top).iterrows():
        fa, fb = row["feature_a"], row["feature_b"]
        if fa not in feature_names or fb not in feature_names:
            continue

        va = X_meta[fa].values
        vb = X_meta[fb].values

        # Seuils : p75 pour hautes, p25 pour basses
        va_hi = np.quantile(va, 0.75)
        va_lo = np.quantile(va, 0.25)
        vb_hi = np.quantile(vb, 0.75)
        vb_lo = np.quantile(vb, 0.25)

        # 4 quadrants
        mask_hh = (va >= va_hi) & (vb >= vb_hi)  # A haut AND B haut
        mask_hl = (va >= va_hi) & (vb <= vb_lo)  # A haut AND B bas
        mask_lh = (va <= va_lo) & (vb >= vb_hi)  # A bas AND B haut
        mask_ll = (va <= va_lo) & (vb <= vb_lo)  # A bas AND B bas

        row_out = {
            "feature_a": fa, "feature_b": fb,
            "interaction": row["interaction_strength"],
            "base_wr": base_winrate,
        }
        for label, mask in [("hh", mask_hh), ("hl", mask_hl),
                             ("lh", mask_lh), ("ll", mask_ll)]:
            n = int(mask.sum())
            if n >= 20:
                wr = float(y_meta[mask].mean())
                lift = wr / base_winrate if base_winrate > 0 else np.nan
                row_out[f"{label}_n"] = n
                row_out[f"{label}_wr"] = wr
                row_out[f"{label}_lift"] = lift
            else:
                row_out[f"{label}_n"] = n
                row_out[f"{label}_wr"] = np.nan
                row_out[f"{label}_lift"] = np.nan
        results.append(row_out)
    return pd.DataFrame(results)


# ─────────────────────────────────────────────────────────────────────────────
# REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def write_report(symbol: str, side: str,
                  feat_rank: pd.DataFrame,
                  pair_rank: pd.DataFrame,
                  quadrants: pd.DataFrame,
                  n_samples: int,
                  base_winrate: float,
                  config: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"{symbol}_{side}_report.md"

    lines = []
    lines.append(f"# SHAP Analysis {symbol} {side.upper()} Meta Model")
    lines.append(f"")
    lines.append(f"**Date** : 2026-04-17")
    lines.append(f"**Dataset** : {n_samples} signaux primary (meta training set)")
    lines.append(f"**Baseline winrate** : {base_winrate:.1%}")
    lines.append(f"**Meta threshold primary** : "
                  f"{config.get('train_config', {}).get('primary_threshold', 'N/A')}")
    lines.append(f"")
    lines.append(f"## Philosophie")
    lines.append(f"")
    lines.append(f"Le meta model a appris a distinguer les VRAIS winners du primary model "
                  f"(quand primary fire ET c'est profitable) des faux positifs (primary fire "
                  f"mais SL touche). SHAP revele les features et combinaisons qui portent "
                  f"cette distinction.")
    lines.append(f"")
    lines.append(f"## Top 15 features individuelles (SHAP magnitude)")
    lines.append(f"")
    lines.append(f"| Rank | Feature | Mean |SHAP| |")
    lines.append(f"|------|---------|-----------|")
    for i, row in feat_rank.head(15).iterrows():
        lines.append(f"| {i+1} | `{row['feature']}` | {row['mean_abs_shap']:.4f} |")
    lines.append(f"")
    lines.append(f"## Top 15 interactions (paires de features qui se renforcent)")
    lines.append(f"")
    lines.append(f"| Rank | Feature A | Feature B | Strength |")
    lines.append(f"|------|-----------|-----------|----------|")
    for i, row in pair_rank.head(15).iterrows():
        lines.append(f"| {i+1} | `{row['feature_a']}` | `{row['feature_b']}` | "
                      f"{row['interaction_strength']:.4f} |")
    lines.append(f"")
    lines.append(f"## Analyse quadrants top 10 interactions (A_haut/A_bas x B_haut/B_bas)")
    lines.append(f"")
    lines.append(f"**Lecture** : pour chaque paire, on regarde les winrate quand les 2 features "
                  f"sont hautes (p75+) vs quand elles sont basses (p25-). Lift > 1 = combinaison "
                  f"gagnante. Lift < 1 = combinaison perdante.")
    lines.append(f"")
    lines.append(f"| A | B | hh_n | hh_wr | hh_lift | hl_wr | lh_wr | ll_wr |")
    lines.append(f"|---|---|------|-------|---------|-------|-------|-------|")
    for _, row in quadrants.iterrows():
        fa, fb = row["feature_a"], row["feature_b"]
        hh_n = int(row.get("hh_n") or 0)
        hh_wr = row.get("hh_wr")
        hh_lift = row.get("hh_lift")
        hl_wr = row.get("hl_wr")
        lh_wr = row.get("lh_wr")
        ll_wr = row.get("ll_wr")
        def fmt(x, pct=True):
            if pd.isna(x):
                return "-"
            return f"{x:.1%}" if pct else f"{x:.2f}"
        lines.append(
            f"| {fa} | {fb} | {hh_n} | {fmt(hh_wr)} | "
            f"{fmt(hh_lift, pct=False)} | {fmt(hl_wr)} | {fmt(lh_wr)} | {fmt(ll_wr)} |"
        )
    lines.append(f"")
    lines.append(f"## Recommandations")
    lines.append(f"")
    top_lift = quadrants.loc[quadrants["hh_lift"].idxmax()] if len(quadrants) > 0 else None
    if top_lift is not None and not pd.isna(top_lift.get("hh_lift", np.nan)):
        lines.append(f"**Meilleure combinaison 'hautes'** : `{top_lift['feature_a']}` + "
                      f"`{top_lift['feature_b']}` → winrate {top_lift['hh_wr']:.1%} "
                      f"(lift {top_lift['hh_lift']:.2f}x baseline)")
        lines.append(f"")
    lines.append(f"**Utilisation suggeree** :")
    lines.append(f"1. Coder une strategie qui declenche quand les 2 features du top interaction "
                  f"sont hautes (p75+)")
    lines.append(f"2. Backtester cette strategie avec framework V2 (100 seeds, RTH, slippage, "
                  f"p-value)")
    lines.append(f"3. Si p-value < 0.05 ET PF > 1.3 → GO paper trading")
    lines.append(f"")
    lines.append(f"## Fichiers produits")
    lines.append(f"- `{symbol}_{side}_shap_values.csv` (feature importance)")
    lines.append(f"- `{symbol}_{side}_interactions.csv` (pairs ranking)")
    lines.append(f"- `{symbol}_{side}_quadrants.csv` (analyse quadrants)")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def maybe_plot_top_interactions(symbol: str, side: str,
                                 interactions: np.ndarray,
                                 X_sample: pd.DataFrame,
                                 feature_names: list[str],
                                 pair_rank: pd.DataFrame,
                                 n_plots: int = 3):
    """Plots dependence des top N interactions."""
    if not HAS_MPL:
        return None
    out_path = OUTPUT_DIR / f"{symbol}_{side}_top_interactions.png"
    fig, axes = plt.subplots(n_plots, 1, figsize=(10, 4 * n_plots))
    if n_plots == 1:
        axes = [axes]

    for k in range(min(n_plots, len(pair_rank))):
        fa = pair_rank.iloc[k]["feature_a"]
        fb = pair_rank.iloc[k]["feature_b"]
        try:
            idx_a = feature_names.index(fa)
            idx_b = feature_names.index(fb)
        except ValueError:
            continue

        ax = axes[k]
        # Scatter plot des interaction values sur les 2 features
        x_vals = X_sample[fa].values
        y_vals = interactions[:, idx_a, idx_b]
        color_vals = X_sample[fb].values

        scatter = ax.scatter(x_vals, y_vals, c=color_vals, cmap="RdYlBu_r",
                             alpha=0.6, s=20)
        ax.set_xlabel(fa)
        ax.set_ylabel(f"SHAP interaction {fa} × {fb}")
        ax.set_title(f"#{k+1} {fa} × {fb} (strength={pair_rank.iloc[k]['interaction_strength']:.3f})")
        plt.colorbar(scatter, ax=ax, label=fb)
        ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close()
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def analyze(symbol: str, side: str, n_interactions: int = 15,
            max_samples: int = 2000) -> dict:
    print(f"\n{'='*80}")
    print(f"  SHAP ANALYSIS — {symbol} {side.upper()}")
    print(f"{'='*80}")

    # 1. Load models + dataset
    print(f"[1] Loading models + dataset...")
    primary, meta, config = load_meta_and_primary(symbol, side)
    df = load_dataset(symbol)
    print(f"    Dataset: {len(df)} rows")

    # 2. Compute primary predictions + meta features
    print(f"[2] Computing primary predictions + meta features...")
    features_primary = config.get("features", [])
    missing_features = [f for f in features_primary if f not in df.columns]
    if missing_features:
        print(f"    [WARN] {len(missing_features)} primary features missing, using available")
        features_primary = [f for f in features_primary if f in df.columns]
    X_primary = df[features_primary]
    p_primary = primary.predict_proba(X_primary)[:, 1]

    X_meta_full = build_meta_features(df, p_primary)
    # Filter to features the meta model was trained on
    meta_feature_names = meta.feature_names if hasattr(meta, "feature_names") else list(X_meta_full.columns)
    missing_meta = [f for f in meta_feature_names if f not in X_meta_full.columns]
    if missing_meta:
        raise ValueError(f"Features meta manquantes: {missing_meta}")
    X_meta_full = X_meta_full[meta_feature_names]

    # Apply primary threshold filter (meta only trained on primary-active samples)
    primary_threshold = config.get("train_config", {}).get(
        "primary_threshold",
        meta.config.primary_threshold if hasattr(meta, "config") else 0.30,
    )
    active_mask = p_primary > primary_threshold
    X_meta = X_meta_full[active_mask].copy()

    # Build y_meta for winrate analysis (label reel vs target)
    target_label = 1 if side == "buy" else -1
    y_meta = (df.loc[active_mask, "label"].values == target_label).astype(int)
    print(f"    Meta samples (primary active): {len(X_meta)}")
    print(f"    Base winrate (meta training signal): {y_meta.mean():.1%}")

    if len(X_meta) < 50:
        print(f"    [ERR] Pas assez de samples meta ({len(X_meta)} < 50). Abort.")
        return {"status": "abort_low_samples"}

    # 3. SHAP values (feature importance)
    print(f"[3] Computing SHAP values (feature importance)...")
    shap_values = compute_shap_values(meta.model, X_meta)
    feat_rank = rank_features(shap_values, meta_feature_names)
    print(f"\n    Top 5 features:")
    for _, row in feat_rank.head(5).iterrows():
        print(f"      {row['feature']:30s}  |SHAP|={row['mean_abs_shap']:.4f}")

    # 4. SHAP interactions (pairs)
    print(f"[4] Computing SHAP interaction values...")
    # Subsample for interactions (coûteux)
    if len(X_meta) > max_samples:
        sample_idx = np.random.RandomState(42).choice(
            len(X_meta), max_samples, replace=False)
        X_sample = X_meta.iloc[sample_idx].copy()
        y_sample = y_meta[sample_idx]
    else:
        X_sample = X_meta
        y_sample = y_meta

    interactions = compute_shap_interactions(meta.model, X_sample,
                                               max_samples=max_samples)
    pair_rank = rank_interactions(interactions, meta_feature_names)
    print(f"\n    Top 5 interactions:")
    for _, row in pair_rank.head(5).iterrows():
        print(f"      {row['feature_a']:25s} × {row['feature_b']:25s}  "
              f"strength={row['interaction_strength']:.4f}")

    # 5. Analyse quadrants top interactions
    print(f"[5] Analysing top {n_interactions} interactions quadrants...")
    quadrants = analyze_top_interactions(
        shap_values[:len(X_sample)] if len(X_meta) > max_samples else shap_values,
        X_sample,
        pair_rank,
        y_sample,
        n_top=n_interactions,
    )

    # 6. Save CSV + report
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    feat_rank.to_csv(OUTPUT_DIR / f"{symbol}_{side}_shap_values.csv", index=False)
    pair_rank.to_csv(OUTPUT_DIR / f"{symbol}_{side}_interactions.csv", index=False)
    quadrants.to_csv(OUTPUT_DIR / f"{symbol}_{side}_quadrants.csv", index=False)

    report_path = write_report(
        symbol, side, feat_rank, pair_rank, quadrants,
        n_samples=len(X_meta), base_winrate=float(y_meta.mean()),
        config=config,
    )
    print(f"\n[6] Report saved: {report_path}")

    # 7. Optional plots
    plot_path = maybe_plot_top_interactions(
        symbol, side, interactions, X_sample, meta_feature_names, pair_rank,
        n_plots=3,
    )
    if plot_path:
        print(f"    Plot saved: {plot_path}")

    return {
        "status": "ok",
        "symbol": symbol,
        "side": side,
        "n_meta_samples": len(X_meta),
        "base_winrate": float(y_meta.mean()),
        "top_features": feat_rank.head(10).to_dict("records"),
        "top_interactions": pair_rank.head(10).to_dict("records"),
        "report_path": str(report_path),
    }


def main():
    if not HAS_SHAP:
        print("ERREUR : shap non installe. pip install shap")
        sys.exit(1)

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", choices=["ES", "NQ"], default=None,
                    help="Symbol a analyser (default : ES et NQ)")
    ap.add_argument("--side", choices=["buy", "sell"], default=None,
                    help="Side a analyser (default : buy et sell)")
    ap.add_argument("--n-interactions", type=int, default=15,
                    help="Nombre de top interactions a analyser")
    ap.add_argument("--max-samples", type=int, default=2000,
                    help="Max samples pour SHAP interactions (cout O(N*F^2))")
    args = ap.parse_args()

    symbols = [args.symbol] if args.symbol else ["ES", "NQ"]
    sides = [args.side] if args.side else ["buy", "sell"]

    results = []
    for symbol in symbols:
        for side in sides:
            try:
                r = analyze(symbol, side,
                            n_interactions=args.n_interactions,
                            max_samples=args.max_samples)
                results.append(r)
            except FileNotFoundError as e:
                print(f"\n[SKIP] {symbol} {side}: {e}")
            except Exception as e:
                print(f"\n[ERR] {symbol} {side}: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n\n{'='*80}")
    print(f"  SUMMARY — {len(results)} analyses completed")
    print(f"{'='*80}")
    for r in results:
        if r.get("status") == "ok":
            print(f"  {r['symbol']} {r['side']}: n={r['n_meta_samples']}, "
                  f"base_wr={r['base_winrate']:.1%}")
            print(f"    Top feat : {r['top_features'][0]['feature']}")
            top_pair = r['top_interactions'][0]
            print(f"    Top pair : {top_pair['feature_a']} × {top_pair['feature_b']}")


if __name__ == "__main__":
    main()
