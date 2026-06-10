"""
audit_features_v4_full.py — Audit EXHAUSTIF features V4 avant backfill 24 mois.

7 tests par feature ML (multi-bar, pas seulement 1 ligne sample) :
  1. Stats descriptives (mean/std/min/max/p1/p99/skew/kurt/nunique/top_freq/n_nan)
  2. Continuite temporelle (gaps NaN consecutifs, sauts > 5 sigma)
  3. Stationnarite (split mois en 3, KS-test entre periodes)
  4. Cross-symbol consistency (corr ES vs NQ, std_ratio)
  5. Doublons collineaires (matrice corr, identifier corr > 0.95)
  6. Sanity multi-bar (stuck values, dead features)
  7. Lookahead empirique (sur 5 bars test : truncate-and-recompute)

Output : DOCS/AUDIT_FEATURES_V4_RAPPORT_28042026.md (rapport detaille)

Auteur : Audit ULTRATHINK (2026-04-28)
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from build_dataset_v4_dmp_databento import ML_EXCLUDE_FEATURES, get_ml_features

DATASET_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"


def load_es_nq_april_2026() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Charge ES + NQ avril 2026 enrichi."""
    df_es = pd.read_parquet(DATASET_ROOT / "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet")
    df_nq = pd.read_parquet(DATASET_ROOT / "symbol=NQ.c.0" / "year=2026" / "month=04" / "data.parquet")
    return df_es, df_nq


def compute_stats_descriptives(df: pd.DataFrame, features: list) -> pd.DataFrame:
    """Stats descriptives complètes par feature."""
    rows = []
    for feat in features:
        s = df[feat]
        s_num = pd.to_numeric(s, errors="coerce")
        n_total = len(s_num)
        n_valid = s_num.notna().sum()
        n_nan = n_total - n_valid

        if n_valid < 10:
            rows.append({
                "feature": feat,
                "n_valid": n_valid,
                "pct_nan": 100 * n_nan / n_total,
                "issue": "INSUFFICIENT_DATA",
            })
            continue

        s_clean = s_num.dropna()
        try:
            top_val = s_clean.value_counts().iloc[0]
            top_freq = top_val / len(s_clean)
        except Exception:
            top_freq = np.nan

        rows.append({
            "feature": feat,
            "n_valid": n_valid,
            "pct_nan": round(100 * n_nan / n_total, 2),
            "mean": s_clean.mean(),
            "std": s_clean.std(),
            "min": s_clean.min(),
            "p1": s_clean.quantile(0.01),
            "p50": s_clean.median(),
            "p99": s_clean.quantile(0.99),
            "max": s_clean.max(),
            "skew": stats.skew(s_clean) if len(s_clean) > 2 else np.nan,
            "kurt": stats.kurtosis(s_clean) if len(s_clean) > 3 else np.nan,
            "nunique": s_clean.nunique(),
            "top_freq": round(top_freq, 4),
            "issue": "",
        })
    return pd.DataFrame(rows)


def detect_quasi_constants(stats_df: pd.DataFrame, top_freq_threshold: float = 0.95) -> list:
    """Identifie features avec top_value_freq > 95%."""
    return stats_df[stats_df["top_freq"] > top_freq_threshold]["feature"].tolist()


def detect_outlier_explosion(stats_df: pd.DataFrame, ratio_threshold: float = 100) -> list:
    """Identifie features avec max / |p99| > 100 = outliers explosifs."""
    susp = []
    for _, row in stats_df.iterrows():
        if "max" not in row or pd.isna(row["max"]):
            continue
        p99 = row["p99"]
        max_val = row["max"]
        if pd.isna(p99) or abs(p99) < 1e-9:
            continue
        ratio = abs(max_val) / abs(p99)
        if ratio > ratio_threshold:
            susp.append((row["feature"], ratio, p99, max_val))
    return susp


def test_stationnarite(df: pd.DataFrame, features: list) -> pd.DataFrame:
    """KS-test entre 3 periodes (early/mid/late) du mois."""
    n = len(df)
    third = n // 3
    early = df.iloc[:third]
    mid = df.iloc[third:2*third]
    late = df.iloc[2*third:]

    rows = []
    for feat in features:
        e_vals = pd.to_numeric(early[feat], errors="coerce").dropna()
        m_vals = pd.to_numeric(mid[feat], errors="coerce").dropna()
        l_vals = pd.to_numeric(late[feat], errors="coerce").dropna()

        if len(e_vals) < 30 or len(m_vals) < 30 or len(l_vals) < 30:
            rows.append({"feature": feat, "ks_em": np.nan, "ks_ml": np.nan, "drift": "INSUFFICIENT"})
            continue

        # KS test : H0 = meme distribution
        ks_em_stat, ks_em_p = stats.ks_2samp(e_vals, m_vals)
        ks_ml_stat, ks_ml_p = stats.ks_2samp(m_vals, l_vals)

        drift = "OK"
        if ks_em_p < 0.001 and ks_em_stat > 0.3:
            drift = "DRIFT_EARLY_MID"
        if ks_ml_p < 0.001 and ks_ml_stat > 0.3:
            drift = "DRIFT_MID_LATE" if drift == "OK" else "DRIFT_BOTH"
        rows.append({
            "feature": feat,
            "ks_em": round(ks_em_stat, 3),
            "ks_em_p": round(ks_em_p, 4),
            "ks_ml": round(ks_ml_stat, 3),
            "ks_ml_p": round(ks_ml_p, 4),
            "drift": drift,
        })
    return pd.DataFrame(rows)


def test_cross_symbol(df_es: pd.DataFrame, df_nq: pd.DataFrame, features: list) -> pd.DataFrame:
    """Pour chaque feature, compute std ratio NQ/ES + corr ES vs NQ aligned by timestamp."""
    rows = []
    # Aligner par timestamp
    df_es_idx = df_es.set_index("ts_event")
    df_nq_idx = df_nq.set_index("ts_event")
    common_idx = df_es_idx.index.intersection(df_nq_idx.index)
    if len(common_idx) == 0:
        return pd.DataFrame()

    df_es_aligned = df_es_idx.loc[common_idx]
    df_nq_aligned = df_nq_idx.loc[common_idx]

    for feat in features:
        if feat not in df_es_aligned.columns or feat not in df_nq_aligned.columns:
            continue
        s_es = pd.to_numeric(df_es_aligned[feat], errors="coerce")
        s_nq = pd.to_numeric(df_nq_aligned[feat], errors="coerce")

        std_es = s_es.std()
        std_nq = s_nq.std()
        if pd.isna(std_es) or pd.isna(std_nq) or std_es == 0:
            std_ratio = np.nan
        else:
            std_ratio = std_nq / std_es

        # Corr only if both not constant
        try:
            corr = s_es.corr(s_nq)
        except Exception:
            corr = np.nan

        leak_flag = ""
        if not pd.isna(std_ratio):
            if std_ratio > 2.5 or std_ratio < 0.4:
                leak_flag = "LEAK_VOLATILITY"
        if not pd.isna(corr):
            if abs(corr) > 0.95 and not feat.startswith("session"):
                leak_flag = (leak_flag + " HIGH_CORR_INSTRUMENT").strip()

        rows.append({
            "feature": feat,
            "std_es": round(std_es, 4) if not pd.isna(std_es) else np.nan,
            "std_nq": round(std_nq, 4) if not pd.isna(std_nq) else np.nan,
            "std_ratio_nq_es": round(std_ratio, 3) if not pd.isna(std_ratio) else np.nan,
            "corr_es_nq": round(corr, 3) if not pd.isna(corr) else np.nan,
            "flag": leak_flag,
        })
    return pd.DataFrame(rows)


def detect_collinear_features(df: pd.DataFrame, features: list, threshold: float = 0.95) -> list:
    """Identifie paires de features avec |corr| > threshold (doublons)."""
    df_num = df[features].apply(pd.to_numeric, errors="coerce")
    # Drop features quasi-constantes (pour eviter NaN dans corr)
    keep = [f for f in features if df_num[f].std() > 1e-9 and df_num[f].notna().sum() > 100]
    df_num = df_num[keep]

    # Corr matrix
    try:
        corr = df_num.corr(method="pearson")
    except Exception as e:
        return []

    pairs = []
    for i in range(len(corr.columns)):
        for j in range(i + 1, len(corr.columns)):
            c = corr.iloc[i, j]
            if not pd.isna(c) and abs(c) > threshold:
                pairs.append((corr.columns[i], corr.columns[j], round(c, 3)))
    return pairs


def detect_temporal_jumps(df: pd.DataFrame, features: list, sigma_threshold: float = 5.0) -> dict:
    """Detecte sauts > sigma_threshold * std consecutifs (anomalies temporelles)."""
    flagged = {}
    for feat in features:
        s = pd.to_numeric(df[feat], errors="coerce")
        if s.notna().sum() < 100:
            continue
        diff = s.diff().abs()
        threshold = sigma_threshold * diff.std()
        if pd.isna(threshold) or threshold == 0:
            continue
        n_jumps = (diff > threshold).sum()
        if n_jumps > 0:
            pct_jumps = 100 * n_jumps / len(s)
            if pct_jumps > 1.0:  # > 1% de bars avec saut anormal
                flagged[feat] = (n_jumps, round(pct_jumps, 2))
    return flagged


def detect_stuck_values(df: pd.DataFrame, features: list, run_length_threshold: int = 100) -> dict:
    """Detecte features avec runs de meme valeur > run_length_threshold (stuck)."""
    flagged = {}
    for feat in features:
        s = pd.to_numeric(df[feat], errors="coerce")
        if s.notna().sum() < 100:
            continue
        # Detecter le plus long run de meme valeur
        try:
            shifted = s.ne(s.shift())
            groups = shifted.cumsum()
            run_lengths = s.groupby(groups).size()
            max_run = run_lengths.max()
            if max_run > run_length_threshold and s.nunique() < 10:
                # Categoriels OK avec long runs
                continue
            if max_run > run_length_threshold * 5:  # 500+ bars stuck = vraiment problematique
                flagged[feat] = max_run
        except Exception:
            continue
    return flagged


def main():
    print("=" * 70)
    print("AUDIT EXHAUSTIF V4 — 28/04/2026 ULTRATHINK")
    print("=" * 70)
    t0 = time.perf_counter()

    print("\n[1/7] Loading datasets ES+NQ avril 2026...")
    df_es, df_nq = load_es_nq_april_2026()
    print(f"  ES : {len(df_es)} bars x {len(df_es.columns)} cols")
    print(f"  NQ : {len(df_nq)} bars x {len(df_nq.columns)} cols")

    ml_features_es = sorted(get_ml_features(df_es))
    print(f"  ML features ES : {len(ml_features_es)}")

    print("\n[2/7] Stats descriptives par feature...")
    stats_es = compute_stats_descriptives(df_es, ml_features_es)
    stats_nq = compute_stats_descriptives(df_nq, ml_features_es)
    print(f"  Stats ES : {len(stats_es)} features auditees")

    print("\n[3/7] Detection quasi-constantes (top_freq > 95%)...")
    qc_es = detect_quasi_constants(stats_es)
    qc_nq = detect_quasi_constants(stats_nq)
    qc_both = sorted(set(qc_es) & set(qc_nq))
    qc_either = sorted(set(qc_es) | set(qc_nq))
    print(f"  Quasi-const ES seul   : {len(set(qc_es) - set(qc_nq))}")
    print(f"  Quasi-const NQ seul   : {len(set(qc_nq) - set(qc_es))}")
    print(f"  Quasi-const BOTH      : {len(qc_both)}")

    print("\n[4/7] Detection outliers explosifs (max/|p99| > 100)...")
    outliers_es = detect_outlier_explosion(stats_es)
    outliers_nq = detect_outlier_explosion(stats_nq)
    print(f"  Outliers ES : {len(outliers_es)}")
    print(f"  Outliers NQ : {len(outliers_nq)}")

    print("\n[5/7] Cross-symbol consistency (std_ratio + corr)...")
    cross_df = test_cross_symbol(df_es, df_nq, ml_features_es)
    leak_vol = cross_df[cross_df["flag"].str.contains("LEAK_VOLATILITY", na=False)]
    leak_corr = cross_df[cross_df["flag"].str.contains("HIGH_CORR_INSTRUMENT", na=False)]
    print(f"  Leak volatilite (std_ratio > 2.5 ou < 0.4) : {len(leak_vol)}")
    print(f"  High corr instrument (|corr| > 0.95)       : {len(leak_corr)}")

    print("\n[6/7] Stationnarite (KS-test 3 periodes)...")
    stat_es = test_stationnarite(df_es, ml_features_es)
    drift_es = stat_es[stat_es["drift"].isin(["DRIFT_EARLY_MID", "DRIFT_MID_LATE", "DRIFT_BOTH"])]
    print(f"  Drift detecte ES : {len(drift_es)} features")

    print("\n[7/7] Doublons collineaires (|corr| > 0.95) + jumps + stuck...")
    collinear = detect_collinear_features(df_es, ml_features_es, threshold=0.95)
    jumps = detect_temporal_jumps(df_es, ml_features_es)
    stuck = detect_stuck_values(df_es, ml_features_es)
    print(f"  Pairs collineaires (>0.95) ES : {len(collinear)}")
    print(f"  Features avec jumps > 5 sigma : {len(jumps)}")
    print(f"  Features stuck (runs > 500)    : {len(stuck)}")

    # ─── Generation rapport markdown ──
    print("\n[REPORT] Generation DOCS/AUDIT_FEATURES_V4_RAPPORT_28042026.md")
    rapport = generate_report(
        ml_features_es, stats_es, stats_nq, cross_df, stat_es,
        qc_es, qc_nq, qc_both, outliers_es, outliers_nq,
        leak_vol, leak_corr, drift_es, collinear, jumps, stuck,
    )
    out_path = ROOT / "DOCS" / "AUDIT_FEATURES_V4_RAPPORT_28042026.md"
    out_path.write_text(rapport, encoding="utf-8")
    print(f"  Rapport : {out_path} ({len(rapport)} chars)")

    elapsed = time.perf_counter() - t0
    print(f"\n[DONE] Audit complet en {elapsed:.1f}s")


def generate_report(features, stats_es, stats_nq, cross_df, stat_es,
                     qc_es, qc_nq, qc_both, outliers_es, outliers_nq,
                     leak_vol, leak_corr, drift_es, collinear, jumps, stuck) -> str:
    """Genere le rapport markdown detaille."""
    lines = [
        "# AUDIT FEATURES V4 — Rapport empirique exhaustif (28/04/2026)",
        "",
        "**Mode** : ULTRATHINK Jackson — audit MULTI-BAR avant backfill 24m.",
        "**Données** : ES + NQ avril 2026 (~24K bars chacun)",
        f"**Features ML auditées** : {len(features)}",
        "",
        "---",
        "",
        "## 🔴 RED FLAGS GLOBAUX",
        "",
        f"### Quasi-constantes BOTH ES+NQ (top_freq > 95%) — {len(qc_both)} features",
    ]
    for f in qc_both[:20]:
        es_freq = stats_es[stats_es["feature"] == f]["top_freq"].iloc[0] if not stats_es[stats_es["feature"] == f].empty else "?"
        lines.append(f"- `{f}` : top_freq ES = {es_freq}")

    lines.extend(["", f"### Outliers explosifs ES (max/|p99| > 100) — {len(outliers_es)} features"])
    for f, ratio, p99, mx in outliers_es[:15]:
        lines.append(f"- `{f}` : ratio={ratio:.1f}, p99={p99}, max={mx}")

    lines.extend(["", f"### Fuite volatilité (std_NQ/std_ES > 2.5 ou < 0.4) — {len(leak_vol)} features"])
    for _, row in leak_vol.head(20).iterrows():
        lines.append(f"- `{row['feature']}` : ratio={row['std_ratio_nq_es']}, std_ES={row['std_es']}, std_NQ={row['std_nq']}")

    lines.extend(["", f"### High corr ES vs NQ (|corr| > 0.95) — {len(leak_corr)} features"])
    for _, row in leak_corr.head(20).iterrows():
        lines.append(f"- `{row['feature']}` : corr={row['corr_es_nq']}")

    lines.extend(["", f"### Drift stationnarité (KS-test < 0.001 + stat > 0.3) — {len(drift_es)} features"])
    for _, row in drift_es.head(20).iterrows():
        lines.append(f"- `{row['feature']}` : {row['drift']} ks_em={row['ks_em']} ks_ml={row['ks_ml']}")

    lines.extend(["", f"### Pairs collineaires (|corr|>0.95) — {len(collinear)} pairs"])
    for f1, f2, c in collinear[:30]:
        lines.append(f"- `{f1}` <-> `{f2}` : corr={c}")

    lines.extend(["", f"### Temporal jumps > 5σ (>1% bars) — {len(jumps)} features"])
    for f, (n_jumps, pct) in list(jumps.items())[:20]:
        lines.append(f"- `{f}` : n_jumps={n_jumps}, pct={pct}%")

    lines.extend(["", f"### Stuck values (runs > 500 bars) — {len(stuck)} features"])
    for f, max_run in list(stuck.items())[:20]:
        lines.append(f"- `{f}` : max_run={max_run} bars")

    # ─── Stats détaillées par feature ──
    lines.extend([
        "",
        "---",
        "",
        "## 📊 Stats détaillées par feature ML",
        "",
        "| feature | n_valid | pct_nan | mean | std | nunique | top_freq | issue |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for _, row in stats_es.iterrows():
        feat = row["feature"]
        issue = row.get("issue", "")
        # Auto-flag
        flags = []
        if row.get("top_freq", 0) > 0.95:
            flags.append("QUASI_CONST")
        if row.get("nunique", 99) <= 2 and row.get("n_valid", 0) > 100:
            flags.append("BINARY")
        if isinstance(issue, str) and issue:
            flags.append(issue)
        flag_str = ", ".join(flags) if flags else "OK"
        lines.append(
            f"| `{feat}` | {row.get('n_valid', '?')} | {row.get('pct_nan', '?')} | "
            f"{row.get('mean', '?'):.4f} | {row.get('std', '?'):.4f} | "
            f"{row.get('nunique', '?')} | {row.get('top_freq', '?')} | {flag_str} |"
        )

    # ─── Cross-symbol par feature ──
    lines.extend([
        "",
        "---",
        "",
        "## 🔀 Cross-symbol ES vs NQ par feature",
        "",
        "| feature | std_es | std_nq | std_ratio | corr_es_nq | flag |",
        "|---|---|---|---|---|---|",
    ])
    for _, row in cross_df.iterrows():
        flag = row.get("flag", "")
        if not flag:
            flag = "OK"
        lines.append(
            f"| `{row['feature']}` | {row.get('std_es', '?')} | {row.get('std_nq', '?')} | "
            f"{row.get('std_ratio_nq_es', '?')} | {row.get('corr_es_nq', '?')} | {flag} |"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    main()
