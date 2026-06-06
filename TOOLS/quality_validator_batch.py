"""Quality validator pour chaque batch port C++ Sierra.

Compare valeurs C++ Sierra (post-deploy) vs Python live_enriched sur N jours.
Mesure divergence par feature, identifie regressions.

Usage : python quality_validator_batch.py BX --features "feat1,feat2,..."

Output : DOCS/QUALITY_VALIDATION_BX.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIERRA_DIR = ROOT / "DATA" / "NQ"
PY_DIR = ROOT / "DATA" / "live_enriched" / "NQ"


def load_bars(fp: Path) -> pd.DataFrame:
    bars = []
    with open(fp, "r", encoding="utf-8") as fh:
        for line in fh:
            try: bars.append(json.loads(line))
            except: pass
    df = pd.DataFrame(bars)
    if df.empty: return df
    if "ts" in df.columns:
        df["ts_int"] = pd.to_numeric(df["ts"], errors="coerce").astype("Int64")
    return df


def validate_feature(s_sierra: pd.Series, s_py: pd.Series) -> Dict:
    """Compare une feature entre Sierra et Python."""
    sa, pa = s_sierra.align(s_py, join="inner")
    both_nonnull = ~(sa.isna() | pa.isna())
    n_common = int(both_nonnull.sum())
    if n_common < 30:
        return {"verdict": "INSUFFICIENT_DATA", "n": n_common}

    sa_v = sa[both_nonnull]
    pa_v = pa[both_nonnull]
    sa_num = pd.to_numeric(sa_v, errors="coerce")
    pa_num = pd.to_numeric(pa_v, errors="coerce")
    diff = (sa_num - pa_num).abs()

    out = {
        "n_common": n_common,
        "sierra_null_pct": round(100 * sa.isna().sum() / len(sa), 1),
        "py_null_pct": round(100 * pa.isna().sum() / len(pa), 1),
        "max_abs_diff": round(float(diff.max()), 6),
        "median_abs_diff": round(float(diff.median()), 6),
        "p95_abs_diff": round(float(diff.quantile(0.95)), 6),
        "mean_abs_diff": round(float(diff.mean()), 6),
    }

    # Rel diff (filter near-zero denominators)
    denom = sa_num.abs()
    denom_ok = denom >= 1e-3
    if denom_ok.sum() > 0:
        rel = (diff[denom_ok] / denom[denom_ok])
        out["median_rel_diff_pct"] = round(100 * float(rel.median()), 4)
        out["p95_rel_diff_pct"] = round(100 * float(rel.quantile(0.95)), 4)
    else:
        out["median_rel_diff_pct"] = None
        out["p95_rel_diff_pct"] = None

    # Spearman correlation
    try:
        rho = sa_num.rank().corr(pa_num.rank())
        out["spearman"] = round(float(rho), 4)
    except Exception:
        out["spearman"] = None

    # Verdict
    if out["max_abs_diff"] < 1e-6:
        out["verdict"] = "MATCH-EXACT"
    elif out.get("median_rel_diff_pct") is not None and out["median_rel_diff_pct"] < 0.1:
        out["verdict"] = "MATCH-QUASI"
    elif out.get("spearman", 0) is not None and out["spearman"] > 0.99:
        out["verdict"] = "HIGH-CORR (formules quasi-identiques)"
    elif out.get("median_rel_diff_pct") is not None and out["median_rel_diff_pct"] < 5:
        out["verdict"] = "MINOR-DIVERGENCE"
    else:
        out["verdict"] = "DIVERGENT"
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_name", help="ex: B1, B2, ...")
    parser.add_argument("--features", required=True, help="comma-separated feature names")
    parser.add_argument("--n-days", type=int, default=10)
    args = parser.parse_args()

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    print(f"=== Quality Validator {args.batch_name} ===")
    print(f"Features a valider : {len(features)}")
    print(f"Jours : {args.n_days}")

    # Recuperer jours communs Sierra ET Python
    sierra_days = {fp.stem.split("_")[0]: fp for fp in SIERRA_DIR.glob("*_NQ.jsonl")}
    py_days = {fp.stem.split("_")[0]: fp for fp in PY_DIR.glob("*_NQ.jsonl")}
    common_days = sorted(set(sierra_days) & set(py_days))[-args.n_days:]
    print(f"Jours communs (derniers {args.n_days}) : {len(common_days)}")

    # Agreger par feature sur N jours
    per_feat_stats: Dict[str, List[Dict]] = {f: [] for f in features}

    for day in common_days:
        try:
            df_s = load_bars(sierra_days[day]).dropna(subset=["ts_int"]).set_index("ts_int")
            df_p = load_bars(py_days[day]).dropna(subset=["ts_int"]).set_index("ts_int")
            common_ts = df_s.index.intersection(df_p.index)
            if len(common_ts) < 60: continue
            df_s_c = df_s.loc[common_ts]
            df_p_c = df_p.loc[common_ts]

            for feat in features:
                if feat not in df_s_c.columns:
                    per_feat_stats[feat].append({"day": day, "verdict": "ABSENT-SIERRA"})
                    continue
                if feat not in df_p_c.columns:
                    per_feat_stats[feat].append({"day": day, "verdict": "ABSENT-PYTHON"})
                    continue
                stats = validate_feature(df_s_c[feat], df_p_c[feat])
                stats["day"] = day
                per_feat_stats[feat].append(stats)
        except Exception as e:
            print(f"  ERREUR {day} : {e}")

    # Agreger
    summary = []
    for feat, day_stats in per_feat_stats.items():
        valid_days = [s for s in day_stats if "verdict" in s and s["verdict"] != "INSUFFICIENT_DATA"]
        if not valid_days:
            summary.append({"feature": feat, "n_days": 0, "verdict_global": "NO-DATA"})
            continue

        # Verdicts comptés
        verdicts = [s["verdict"] for s in valid_days]
        verdict_counts = {v: verdicts.count(v) for v in set(verdicts)}

        # Stats sur jours match
        match_days = [s for s in valid_days if s["verdict"] in ("MATCH-EXACT", "MATCH-QUASI", "HIGH-CORR (formules quasi-identiques)")]
        n_match = len(match_days)

        # Verdict global
        if n_match == len(valid_days):
            verdict_global = "GO"
        elif n_match >= len(valid_days) * 0.8:
            verdict_global = "GO-AVEC-RESERVES"
        elif n_match >= len(valid_days) * 0.5:
            verdict_global = "RESERVES"
        else:
            verdict_global = "NOGO"

        # Median stats des jours valides numerique
        median_rels = [s.get("median_rel_diff_pct") for s in valid_days if s.get("median_rel_diff_pct") is not None]
        spearmans = [s.get("spearman") for s in valid_days if s.get("spearman") is not None]

        summary.append({
            "feature": feat,
            "n_days": len(valid_days),
            "verdict_global": verdict_global,
            "n_match": n_match,
            "verdicts_breakdown": str(verdict_counts),
            "median_rel_diff_pct_agg": round(np.median(median_rels), 4) if median_rels else None,
            "spearman_agg": round(np.median(spearmans), 4) if spearmans else None,
        })

    df_summary = pd.DataFrame(summary)
    df_summary = df_summary.sort_values("verdict_global")

    # Rapport
    out_fp = ROOT / "DOCS" / f"QUALITY_VALIDATION_{args.batch_name}.md"
    md = []
    md.append(f"# Quality Validation Batch {args.batch_name}")
    md.append("")
    md.append(f"**Date** : 2026-06-07")
    md.append(f"**Features validees** : {len(features)}")
    md.append(f"**Jours** : {len(common_days)}")
    md.append("")
    md.append("## Resume verdict")
    md.append("")
    md.append("| Verdict | N features |")
    md.append("|---|---|")
    verdict_glob_counts = df_summary.verdict_global.value_counts()
    for k, v in verdict_glob_counts.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Detail par feature")
    md.append("")
    md.append("| Feature | Verdict | n_days | n_match | median_rel_% | spearman | breakdown |")
    md.append("|---|---|---|---|---|---|---|")
    for _, r in df_summary.iterrows():
        md.append(f"| `{r.feature}` | {r.verdict_global} | {r.n_days} | {r.n_match} | {r.median_rel_diff_pct_agg} | {r.spearman_agg} | {r.verdicts_breakdown} |")
    md.append("")

    # Verdict global batch
    n_go = (df_summary.verdict_global == "GO").sum()
    n_go_reserves = (df_summary.verdict_global == "GO-AVEC-RESERVES").sum()
    n_nogo = (df_summary.verdict_global == "NOGO").sum()
    md.append("## Verdict global batch")
    md.append("")
    if n_nogo == 0 and n_go >= len(features) * 0.9:
        md.append(f"✅ **BATCH {args.batch_name} GO** : {n_go}/{len(features)} GO + {n_go_reserves} GO-AVEC-RESERVES")
    elif n_nogo == 0:
        md.append(f"⚠️ **BATCH {args.batch_name} GO-AVEC-RESERVES** : {n_go}/{len(features)} GO, {n_go_reserves} avec reserves")
    elif n_nogo < len(features) * 0.1:
        md.append(f"⚠️ **BATCH {args.batch_name} RESERVES** : {n_nogo} NOGO a investiguer")
    else:
        md.append(f"❌ **BATCH {args.batch_name} NOGO** : {n_nogo} NOGO / {len(features)} → re-port requis")

    out_fp.parent.mkdir(parents=True, exist_ok=True)
    out_fp.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport : {out_fp} ===")


if __name__ == "__main__":
    main()
