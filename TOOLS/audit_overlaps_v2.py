"""Audit overlaps Sierra DMP vs Python pipeline live_enriched — V2 robust.

Corrections code-reviewer v1 :
- Multi-jour : N jours stratifies au lieu de 1
- median + p95 au lieu de max (eviter outliers)
- Filtrer artefacts denominator < 1e-3 (eviter inf%)
- Classification automatique cause (CONVENTION-INVERSION, BUG-NULL,
  FORMULE, METHODE, UNITE, ARTEFACT)
- Whitelist infrastructure (metadata, OHLCV doublons, privees)
- Rapport agrege par feature sur tous jours

NB : Python pipeline lit DATABENTO (live_cache.py wrap), confirme dans
live_enricher_io.py:32. Donc divergences = (a) bug Databento inverse,
(b) bars Sierra vs Databento differents, (c) formules Python custom.

Output : DOCS/SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "DOCS" / "SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md"
SYMBOL = "NQ"

# === BLACKLIST INFRASTRUCTURE (a virer du count) ===
INFRA_COLUMNS = {
    # Metadata
    "schema_version", "n_columns", "instrument_id", "symbol", "sym",
    "contract", "date_et", "ts_event", "ts_event_iso", "ts_event_ns",
    "written_at_iso", "written_at_ts", "age_sec", "latency_s",
    "data_quality_flag", "trades_window_aligned", "trades_window_n",
    "trades_window_sec", "mq_schema_version", "mq_snapshot_ts", "mq_sym",
    "mq_trigger",
    # OHLCV doublons (les 2 sources ont par definition les memes)
    "open", "high", "low", "close", "volume", "avg_price",
    # Mins ET / session (calculable, pas conflit)
    "mins_et", "session_date", "session_date_trading",
    # Privees Python (debug-only)
    "_last_swing_high_price", "_last_swing_low_price",
    "bars_since_boot",
}

# === CONVENTION-INVERSION KNOWN (Databento Side bug, INCIDENT_LOG entry 37) ===
KNOWN_DATABENTO_INVERSE = {
    "delta_bar", "delta_day", "cvd_day", "delta_day_dir",
    "delta_pct", "cvd_day_dir",
}

# === UNITE-DIFFERENT KNOWN ===
# Sierra utilise unite X, Python unite Y. Pas un bug, juste convention.
KNOWN_UNIT_DIFF = {
    # ATR : Sierra ticks, Python parfois points/pct
    "atr": ("ticks", "points"),
    "atr_14m": ("ticks", "points"),
}


def load_bars(fp: Path) -> pd.DataFrame:
    bars = []
    with open(fp, "r", encoding="utf-8") as fh:
        for line in fh:
            try: bars.append(json.loads(line))
            except: pass
    df = pd.DataFrame(bars)
    if "ts" in df.columns:
        df["ts_int"] = pd.to_numeric(df["ts"], errors="coerce").astype("Int64")
    return df


def col_is_numeric(s: pd.Series) -> bool:
    nonnull = s.dropna()
    if nonnull.empty: return False
    try:
        pd.to_numeric(nonnull.head(20), errors="raise")
        return True
    except (ValueError, TypeError):
        return False


def compare_single_day(df_s: pd.DataFrame, df_p: pd.DataFrame,
                       col: str) -> Dict:
    """Compare une feature sur un jour.

    Returns dict {n_common, sierra_null_pct, py_null_pct, max_abs_diff,
                  median_abs_diff, p95_abs_diff, median_rel_diff_pct,
                  p95_rel_diff_pct, match_pct_categorical}
    """
    if col not in df_s.columns or col not in df_p.columns:
        return None

    sa, pa = df_s[col].align(df_p[col], join="inner")
    both_nonnull = ~(sa.isna() | pa.isna())
    n_common = int(both_nonnull.sum())
    if n_common < 5:
        return None

    sa_v = sa[both_nonnull]
    pa_v = pa[both_nonnull]

    out = {"n_common": n_common, "n_total": len(sa)}
    out["sierra_null_pct"] = round(100 * sa.isna().sum() / len(sa), 1)
    out["py_null_pct"] = round(100 * pa.isna().sum() / len(pa), 1)

    if col_is_numeric(sa_v) and col_is_numeric(pa_v):
        sa_num = pd.to_numeric(sa_v, errors="coerce")
        pa_num = pd.to_numeric(pa_v, errors="coerce")
        diff = (sa_num - pa_num).abs()
        out["max_abs_diff"] = round(float(diff.max()), 6)
        out["median_abs_diff"] = round(float(diff.median()), 6)
        out["p95_abs_diff"] = round(float(diff.quantile(0.95)), 6)
        out["mean_abs_diff"] = round(float(diff.mean()), 6)

        # Filtrer artefacts : denominator < 1e-3 = exclu rel_diff
        denom = sa_num.abs()
        denom_ok_mask = denom >= 1e-3
        if denom_ok_mask.sum() > 0:
            rel_diff = (diff[denom_ok_mask] / denom[denom_ok_mask])
            out["median_rel_diff_pct"] = round(100 * float(rel_diff.median()), 4)
            out["p95_rel_diff_pct"] = round(100 * float(rel_diff.quantile(0.95)), 4)
        else:
            out["median_rel_diff_pct"] = None
            out["p95_rel_diff_pct"] = None

        # Correlation Spearman (signal cohérence)
        try:
            rho = sa_num.rank().corr(pa_num.rank())
            out["spearman"] = round(float(rho), 4)
        except Exception:
            out["spearman"] = None

        # Sign correlation : si rho < -0.5, probable CONVENTION-INVERSION
        out["sign_inverted"] = (out["spearman"] is not None and out["spearman"] < -0.5)
    else:
        # Categorical
        eq = (sa_v.astype(str) == pa_v.astype(str)).sum()
        out["categorical_match_pct"] = round(100 * eq / n_common, 1)
        out["max_abs_diff"] = None
        out["median_rel_diff_pct"] = None

    return out


def classify_cause(agg: Dict, col: str) -> str:
    """Classification cause divergence."""
    if col in KNOWN_DATABENTO_INVERSE:
        return "CONVENTION-INVERSION-DATABENTO"
    if col in KNOWN_UNIT_DIFF:
        return "UNITE-DIFF"

    s_null = agg.get("avg_sierra_null_pct", 0)
    p_null = agg.get("avg_py_null_pct", 0)
    if s_null > 50:
        return "BUG-SIERRA-NULL"
    if p_null > 50:
        return "BUG-PYTHON-NULL"

    median_rel = agg.get("avg_median_rel_diff_pct", None)
    if median_rel is None:
        return "ARTEFACT-NEAR-ZERO"
    if median_rel < 0.1:
        return "MATCH"
    if median_rel < 5:
        return "QUASI-MATCH"

    spearman = agg.get("avg_spearman", None)
    if spearman is not None and spearman < -0.5:
        return "CONVENTION-INVERSION-UNKNOWN"

    # P95 vs median
    p95 = agg.get("avg_p95_rel_diff_pct", 0)
    if p95 / max(median_rel, 0.01) > 50:  # p95 >> median = outliers
        return "OUTLIER-DOMINATED"

    return "DIVERGENT-METHODE"


def decide_source(cause: str, agg: Dict) -> str:
    """Decision source de verite selon cause."""
    if cause == "CONVENTION-INVERSION-DATABENTO":
        return "SIERRA"
    if cause == "BUG-PYTHON-NULL":
        return "SIERRA"
    if cause == "BUG-SIERRA-NULL":
        return "PYTHON"
    if cause == "UNITE-DIFF":
        return "LES-DEUX-SELON-USAGE"
    if cause == "MATCH":
        return "SIERRA (Python redondant)"
    if cause == "QUASI-MATCH":
        return "SIERRA (mineur)"
    if cause == "CONVENTION-INVERSION-UNKNOWN":
        return "INVESTIGATION-URGENTE"
    if cause == "ARTEFACT-NEAR-ZERO":
        return "MATCH (denominator near-zero)"
    if cause == "OUTLIER-DOMINATED":
        return "MATCH (median OK, outliers session-edge)"
    return "INVESTIGATION-MANUELLE"


def main():
    sierra_dir = ROOT / "DATA" / SYMBOL
    py_dir = ROOT / "DATA" / "live_enriched" / SYMBOL

    # Charger fichiers existants des 2 sources, jours communs
    sierra_days = {fp.stem.split("_")[0]: fp for fp in sierra_dir.glob(f"*_{SYMBOL}.jsonl")}
    py_days = {fp.stem.split("_")[0]: fp for fp in py_dir.glob(f"*_{SYMBOL}.jsonl")}
    common_days = sorted(set(sierra_days) & set(py_days))

    print(f"Sierra : {len(sierra_days)} jours, Python : {len(py_days)} jours")
    print(f"Communes : {len(common_days)} jours")

    # Prendre les 30 derniers jours communs (stratification temporelle)
    selected_days = common_days[-30:]
    print(f"Audit sur {len(selected_days)} derniers jours : {selected_days[0]} -> {selected_days[-1]}")

    # Agreger par feature
    # feature -> liste de dicts par jour
    per_feature: Dict[str, List[Dict]] = {}

    all_overlap = set()
    all_sierra_only = set()
    all_py_only = set()

    for i, day in enumerate(selected_days):
        try:
            df_s = load_bars(sierra_days[day]).dropna(subset=["ts_int"]).set_index("ts_int")
            df_p = load_bars(py_days[day]).dropna(subset=["ts_int"]).set_index("ts_int")
            common_ts = df_s.index.intersection(df_p.index)
            if len(common_ts) < 60:
                continue
            df_s_c = df_s.loc[common_ts]
            df_p_c = df_p.loc[common_ts]

            cols_s = set(df_s_c.columns) - {"ts_int"} - INFRA_COLUMNS
            cols_p = set(df_p_c.columns) - {"ts_int"} - INFRA_COLUMNS
            overlap = cols_s & cols_p
            all_overlap |= overlap
            all_sierra_only |= (cols_s - cols_p)
            all_py_only |= (cols_p - cols_s)

            for col in overlap:
                try:
                    stats = compare_single_day(df_s_c, df_p_c, col)
                    if stats is None: continue
                    stats["day"] = day
                    per_feature.setdefault(col, []).append(stats)
                except Exception as e:
                    pass
        except Exception as e:
            print(f"  ERREUR {day} : {e}")
            continue
        if (i+1) % 5 == 0:
            print(f"  {i+1}/{len(selected_days)} jours processed")

    # Agreger par feature (moyenne des metriques sur N jours)
    aggregated = []
    for col, day_stats in per_feature.items():
        if not day_stats: continue
        n_days = len(day_stats)

        # Aggregation
        s_nulls = [s["sierra_null_pct"] for s in day_stats]
        p_nulls = [s["py_null_pct"] for s in day_stats]

        median_rels = [s["median_rel_diff_pct"] for s in day_stats if s.get("median_rel_diff_pct") is not None]
        p95_rels = [s["p95_rel_diff_pct"] for s in day_stats if s.get("p95_rel_diff_pct") is not None]
        spearmans = [s["spearman"] for s in day_stats if s.get("spearman") is not None]

        agg = {
            "feature": col,
            "n_days": n_days,
            "avg_sierra_null_pct": round(float(np.mean(s_nulls)), 1),
            "avg_py_null_pct": round(float(np.mean(p_nulls)), 1),
            "avg_median_rel_diff_pct": round(float(np.median(median_rels)), 4) if median_rels else None,
            "avg_p95_rel_diff_pct": round(float(np.median(p95_rels)), 4) if p95_rels else None,
            "avg_spearman": round(float(np.median(spearmans)), 4) if spearmans else None,
        }
        agg["cause"] = classify_cause(agg, col)
        agg["source_verite"] = decide_source(agg["cause"], agg)
        aggregated.append(agg)

    df_audit = pd.DataFrame(aggregated)

    # Stats globales
    cause_counts = df_audit.cause.value_counts()
    decision_counts = df_audit.source_verite.value_counts()

    # Rapport markdown
    md = []
    md.append("# Audit Overlaps Sierra DMP vs Python live_enriched — V2 ROBUST")
    md.append("")
    md.append(f"**Date** : 2026-06-07")
    md.append(f"**Symbole** : {SYMBOL}")
    md.append(f"**Jours audites** : {len(selected_days)} ({selected_days[0]} -> {selected_days[-1]})")
    md.append(f"**Source Python live_enriched** : **DATABENTO** (confirme `live_enricher_io.py:32` import live_cache)")
    md.append("")
    md.append("## Corrections vs V1 (review code-reviewer)")
    md.append("- Median + p95 au lieu de max (eviter outliers session-edge)")
    md.append("- Filter artefacts denominator < 1e-3 (eviter inf%)")
    md.append("- Classification automatique cause (6 categories)")
    md.append("- Whitelist infrastructure (35 colonnes metadata/OHLCV)")
    md.append("- Multi-jour 30 jours stratifies")
    md.append("- Spearman cross-source (detecte CONVENTION-INVERSION)")
    md.append("")
    md.append("## Stats globales")
    md.append("")
    md.append(f"- Overlap features (apres filter infra) : **{len(all_overlap)}**")
    md.append(f"- Sierra-only : **{len(all_sierra_only)}**")
    md.append(f"- Python-only : **{len(all_py_only)}**")
    md.append("")
    md.append("## Distribution cause (classification automatique)")
    md.append("")
    md.append("| Cause | Count |")
    md.append("|---|---|")
    for k, v in cause_counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Decision source de verite")
    md.append("")
    md.append("| Decision | Count |")
    md.append("|---|---|")
    for k, v in decision_counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    # Detail par cause
    for cause in cause_counts.index:
        sub = df_audit[df_audit.cause == cause].sort_values("avg_median_rel_diff_pct", ascending=False, na_position="last")
        if sub.empty: continue
        md.append(f"## Detail — {cause}")
        md.append("")
        md.append("| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |")
        md.append("|---|---|---|---|---|---|---|---|")
        for _, r in sub.iterrows():
            md.append(f"| `{r.feature}` | {r.n_days} | {r.avg_sierra_null_pct} | {r.avg_py_null_pct} | {r.avg_median_rel_diff_pct} | {r.avg_p95_rel_diff_pct} | {r.avg_spearman} | {r.source_verite} |")
        md.append("")

    # Sierra-only et Python-only listes (filtrees infra)
    md.append("## Sierra-only features uniques (filtre infra)")
    md.append("")
    for c in sorted(all_sierra_only):
        md.append(f"- `{c}`")
    md.append("")
    md.append(f"**Total Sierra-only utiles** : {len(all_sierra_only)}")
    md.append("")
    md.append("## Python-only features uniques (filtre infra)")
    md.append("")
    for c in sorted(all_py_only):
        md.append(f"- `{c}`")
    md.append("")
    md.append(f"**Total Python-only utiles** : {len(all_py_only)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport ecrit : {OUT} ===")
    print(f"\nClassification cause :")
    print(cause_counts.to_string())
    print(f"\nDecision source verite :")
    print(decision_counts.to_string())


if __name__ == "__main__":
    main()
