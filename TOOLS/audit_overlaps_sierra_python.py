"""Audit overlaps Sierra DMP C++ vs Python pipeline live_enriched.

Pour chaque feature commune aux 2 sources :
1. Verifier si valeurs identiques sur bars communes
2. Si divergence : flag conflit + identifier source de verite

Output : DOCS/SIERRA_PYTHON_OVERLAPS_AUDIT.md (rapport markdown structure)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "DOCS" / "SIERRA_PYTHON_OVERLAPS_AUDIT.md"

# Jour de reference : data complete + connu (NQ baissier -19 pts, RTH normal)
DAY = "20260603"
SYMBOL = "NQ"


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


def compare_columns(s_sierra: pd.Series, s_py: pd.Series) -> dict:
    """Compare 2 series : count, NaN rate, divergence rate, max abs diff."""
    n = len(s_sierra)
    sn = s_sierra.dropna()
    pn = s_py.dropna()

    out = {
        "n": n,
        "sierra_null_pct": round(100 * (n - len(sn)) / n, 1) if n else 0,
        "py_null_pct": round(100 * (n - len(pn)) / n, 1) if n else 0,
    }

    # Aligner par index pour comparaison
    sa, pa = s_sierra.align(s_py, join="inner")
    both_nonnull = ~(sa.isna() | pa.isna())
    sa_v = sa[both_nonnull]
    pa_v = pa[both_nonnull]
    n_common = len(sa_v)
    out["n_both_nonnull"] = n_common

    if n_common == 0:
        out["divergence"] = "N/A"
        return out

    if col_is_numeric(sa_v) and col_is_numeric(pa_v):
        sa_num = pd.to_numeric(sa_v, errors="coerce")
        pa_num = pd.to_numeric(pa_v, errors="coerce")
        diff = (sa_num - pa_num).abs()
        out["max_abs_diff"] = round(float(diff.max()), 6)
        out["mean_abs_diff"] = round(float(diff.mean()), 6)
        # divergence relative (eviter division par zero)
        denom = sa_num.abs().clip(lower=1e-9)
        rel_diff = (diff / denom)
        out["max_rel_diff_pct"] = round(100 * float(rel_diff.max()), 2)
        # Match si max abs diff < 1e-6 OR rel diff < 0.1%
        if out["max_abs_diff"] < 1e-6:
            out["divergence"] = "MATCH"
        elif out["max_rel_diff_pct"] < 0.1:
            out["divergence"] = "QUASI-MATCH"
        elif out["max_rel_diff_pct"] < 5:
            out["divergence"] = "MINOR (< 5%)"
        else:
            out["divergence"] = "DIVERGENT"
    else:
        # Categorical compare
        eq = (sa_v.astype(str) == pa_v.astype(str)).sum()
        out["categorical_match_pct"] = round(100 * eq / n_common, 1)
        out["divergence"] = "MATCH" if eq == n_common else f"DIVERGENT {round(100*eq/n_common, 0)}%"
    return out


def classify_decision(stats: dict, sierra_null: float, py_null: float) -> str:
    """Recommandation source unique."""
    div = stats.get("divergence", "")
    if div == "MATCH":
        return "SIERRA (Python redondant, skip)"
    if div == "QUASI-MATCH" or "MINOR" in str(div):
        if sierra_null < py_null:
            return "SIERRA (moins de null)"
        else:
            return "PYTHON (moins de null)"
    if div == "DIVERGENT":
        return "CONFLIT - audit manuel requis"
    return "N/A"


def main():
    sierra_fp = ROOT / "DATA" / SYMBOL / f"{DAY}_{SYMBOL}.jsonl"
    py_fp = ROOT / "DATA" / "live_enriched" / SYMBOL / f"{DAY}_{SYMBOL}.jsonl"

    print(f"Loading Sierra : {sierra_fp.name}")
    df_s = load_bars(sierra_fp)
    print(f"Loading Python : {py_fp.name}")
    df_p = load_bars(py_fp)
    print(f"Sierra : {len(df_s)} bars, {len(df_s.columns)} columns")
    print(f"Python : {len(df_p)} bars, {len(df_p.columns)} columns")

    # Index par ts
    df_s = df_s.dropna(subset=["ts_int"]).set_index("ts_int")
    df_p = df_p.dropna(subset=["ts_int"]).set_index("ts_int")
    common_ts = df_s.index.intersection(df_p.index)
    print(f"Bars communes (par ts) : {len(common_ts)}")

    df_s_c = df_s.loc[common_ts]
    df_p_c = df_p.loc[common_ts]

    # Identifier overlap columns
    cols_sierra = set(df_s.columns) - {"ts_int"}
    cols_py = set(df_p.columns) - {"ts_int"}
    overlap = sorted(cols_sierra & cols_py)
    sierra_only = sorted(cols_sierra - cols_py)
    py_only = sorted(cols_py - cols_sierra)
    print(f"\nOverlap features : {len(overlap)}")
    print(f"Sierra-only       : {len(sierra_only)}")
    print(f"Python-only       : {len(py_only)}")

    # Comparer chaque overlap
    print(f"\nComparaison {len(overlap)} overlaps...")
    rows = []
    for col in overlap:
        try:
            stats = compare_columns(df_s_c[col], df_p_c[col])
            decision = classify_decision(stats, stats["sierra_null_pct"], stats["py_null_pct"])
            rows.append({
                "feature": col,
                "divergence": stats.get("divergence", "?"),
                "max_abs_diff": stats.get("max_abs_diff", ""),
                "max_rel_diff_pct": stats.get("max_rel_diff_pct", ""),
                "sierra_null_%": stats["sierra_null_pct"],
                "py_null_%": stats["py_null_pct"],
                "decision": decision,
            })
        except Exception as e:
            rows.append({"feature": col, "divergence": f"ERROR: {e}", "decision": "MANUAL"})

    df_audit = pd.DataFrame(rows)

    # Grouper par decision
    decision_counts = df_audit.decision.value_counts()
    div_counts = df_audit.divergence.value_counts()

    # Markdown report
    md = []
    md.append("# Audit Overlaps Sierra DMP vs Python Pipeline live_enriched")
    md.append(f"\n**Date** : 2026-06-07")
    md.append(f"**Jour de reference** : {DAY} NQ")
    md.append(f"**Sierra bars** : {len(df_s)} | **Python bars** : {len(df_p)} | **Communes** : {len(common_ts)}")
    md.append("")
    md.append("## Stats globales")
    md.append("")
    md.append(f"- **Overlap features** : {len(overlap)}")
    md.append(f"- **Sierra-only** : {len(sierra_only)}")
    md.append(f"- **Python-only** : {len(py_only)}")
    md.append("")
    md.append("## Distribution divergence")
    md.append("")
    md.append("| Divergence | Count |")
    md.append("|---|---|")
    for k, v in div_counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Decision recommandee")
    md.append("")
    md.append("| Decision | Count |")
    md.append("|---|---|")
    for k, v in decision_counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    # Tables par categorie de divergence
    md.append("## Detail par feature — DIVERGENT (conflits a auditer)")
    md.append("")
    md.append("| Feature | Divergence | Max abs diff | Max rel % | Sierra null % | Py null % | Decision |")
    md.append("|---|---|---|---|---|---|---|")
    div_rows = df_audit[df_audit.divergence == "DIVERGENT"].sort_values("max_rel_diff_pct", ascending=False, na_position="last")
    for _, r in div_rows.iterrows():
        md.append(f"| `{r.feature}` | {r.divergence} | {r.max_abs_diff} | {r.max_rel_diff_pct} | {r['sierra_null_%']} | {r['py_null_%']} | {r.decision} |")
    md.append("")

    md.append("## Detail par feature — MATCH (skipper Python)")
    md.append("")
    md.append("| Feature | Divergence | Sierra null % | Py null % |")
    md.append("|---|---|---|---|")
    match_rows = df_audit[df_audit.divergence == "MATCH"]
    for _, r in match_rows.iterrows():
        md.append(f"| `{r.feature}` | {r.divergence} | {r['sierra_null_%']} | {r['py_null_%']} |")
    md.append("")

    md.append("## Detail par feature — QUASI-MATCH ou MINOR (Sierra ok)")
    md.append("")
    md.append("| Feature | Divergence | Max rel % | Sierra null % | Py null % | Decision |")
    md.append("|---|---|---|---|---|---|")
    quasi_rows = df_audit[df_audit.divergence.isin(["QUASI-MATCH"]) | df_audit.divergence.str.startswith("MINOR", na=False)]
    for _, r in quasi_rows.iterrows():
        md.append(f"| `{r.feature}` | {r.divergence} | {r.max_rel_diff_pct} | {r['sierra_null_%']} | {r['py_null_%']} | {r.decision} |")
    md.append("")

    md.append("## Sierra-only (uniques C++)")
    md.append("")
    for c in sierra_only:
        md.append(f"- `{c}`")
    md.append("")

    md.append("## Python-only (uniques Python)")
    md.append("")
    for c in py_only:
        md.append(f"- `{c}`")
    md.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport ecrit : {OUT} ===")
    print(f"\nDistribution divergence :")
    print(div_counts.to_string())
    print(f"\nDecisions :")
    print(decision_counts.to_string())


if __name__ == "__main__":
    main()
