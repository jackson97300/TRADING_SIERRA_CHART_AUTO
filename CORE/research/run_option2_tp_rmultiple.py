"""run_option2_tp_rmultiple.py — Phase A Option 2 : TP R-multiple + regime filter.

Jackson 24/05/2026 : apres 10 variantes NOGO Lopez, on teste alternative
moins ambitieuse :
  - TP R-multiple fixe (1.5R / 2R / 3R) au lieu de cible 1d_max
  - Regime filter : skip TREND (fade marche en RANGE/NORMAL)
  - NQ-only (ES universellement pire)
  - Garde les 5 baselines LONG-only (V1 + 4 BN V4 variants V5/V6/V7/V8)

Matrice : 5 baselines x 3 R-multiples x 2 (avec/sans regime filter) = 30 buckets.

Critere succes intermediaire :
  - Top bucket : n>=150 ET PF>=1.5 ET DSR>=0.30 sur 5 mois = GO Phase B (refonte)
  - Sinon : NOGO Option 2 → bascule Option 1 (continuation post-retest)

Output : LOGS/bot3_reform/option2/REPORT_OPTION2.md
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot3_reform_backtester import (
    LOG_DIR,
    PERIOD_END,
    PERIOD_START,
    assign_folds,
    compute_psr_dsr,
    compute_walk_forward,
    load_v4_enriched,
    run_variant,
    stats_of,
    verdict_from_metrics,
    write_trades_jsonl,
)
from CORE.research.bot3_reform_variants import (
    LEVELS_V1_LONG,
    VariantConfig,
    filter_bn_confluence,
    filter_bn_density,
    filter_bn_edge,
    filter_footprint_dow,
    filter_regime_no_trend,
)


# ════════════════════════════════════════════════════════════════════════
# 30 BUCKETS = 5 baselines x 3 R-multiples x 2 regime filter
# ════════════════════════════════════════════════════════════════════════

R_MULTIPLES = [1.5, 2.0, 3.0]

# 5 baselines : V1 pure + 4 BN V4 filters
BASELINES = [
    ("V1",       "Purge 9 niveaux DROP (LONG only)",           []),
    ("V5_BN",    "V1 + BN density gate",                       [filter_bn_density]),
    ("V6_BN",    "V1 + BN confluence gate",                    [filter_bn_confluence]),
    ("V7_BN",    "V1 + BN edge gate",                          [filter_bn_edge]),
    ("V8_BN",    "V1 + BN V4 complet (density+conf+edge+fp)",
                 [filter_bn_density, filter_bn_confluence, filter_bn_edge, filter_footprint_dow]),
]


def build_option2_variants() -> Dict[str, VariantConfig]:
    """Genere les 30 variantes Option 2."""
    variants: Dict[str, VariantConfig] = {}
    for base_name, base_desc, base_filters in BASELINES:
        for r in R_MULTIPLES:
            for regime_on in (False, True):
                regime_suffix = "_REG" if regime_on else ""
                full_filters = list(base_filters)
                if regime_on:
                    full_filters.append(filter_regime_no_trend)
                name = f"OPT2_{base_name}_R{r}{regime_suffix}".replace(".", "p")
                desc = (
                    f"{base_desc} | TP={r}R | "
                    f"{'regime!=TREND' if regime_on else 'no regime filter'}"
                )
                variants[name] = VariantConfig(
                    name=name,
                    description=desc,
                    levels=list(LEVELS_V1_LONG),
                    filters=full_filters,
                    target_R=r,
                    sl_ticks_nq=40,
                    sl_ticks_es=30,
                )
    return variants


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

def main():
    out_dir = LOG_DIR / "option2"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*80}")
    print(f"OPTION 2 — TP R-MULTIPLE + REGIME FILTER (NQ-only)")
    print(f"{'='*80}\n")

    print("[LOAD] NQ...", flush=True)
    t0 = time.time()
    df = load_v4_enriched("NQ")
    print(f"  {len(df)} bars / {df['date'].nunique()} jours ({time.time()-t0:.1f}s)\n",
          flush=True)

    variants = build_option2_variants()
    print(f"[INFO] {len(variants)} buckets a tester\n", flush=True)

    results: List[Dict] = []
    for variant_name, variant in variants.items():
        t0 = time.time()
        trades = run_variant(variant, "NQ", df)
        trades = assign_folds(trades)
        elapsed = time.time() - t0

        metrics = stats_of(trades)
        wf = compute_walk_forward(trades)
        dsr_dict = compute_psr_dsr(trades, n_trials=30)  # haircut N=30 (30 buckets)
        verdict = verdict_from_metrics(metrics, wf, dsr_dict)

        # Sauvegarde trades par bucket
        bucket_dir = out_dir / variant_name
        bucket_dir.mkdir(parents=True, exist_ok=True)
        with open(bucket_dir / "trades_NQ.jsonl", "w", encoding="utf-8") as f:
            for t in trades:
                f.write(json.dumps(asdict(t)) + "\n")

        row = {
            "bucket": variant_name,
            "description": variant.description,
            "verdict": verdict,
            **metrics,
            "dsr": dsr_dict["dsr"],
            "psr": dsr_dict["psr"],
            "sharpe": dsr_dict["sharpe"],
            "pf_min_fold": wf["pf_min_fold"],
            "pf_median_fold": wf["pf_median_fold"],
            "n_folds_pf_gt_1_3": wf["n_folds_pf_gt_1_3"],
            "wf_consistency": wf["wf_consistency"],
            "runtime_sec": round(elapsed, 1),
        }
        results.append(row)
        print(f"  {variant_name:32s} n={metrics['n']:4d} WR={metrics['wr_pct']:5.1f}% "
              f"PF={metrics['pf']:5.2f} DSR={dsr_dict['dsr']:.3f} {verdict}",
              flush=True)

    # Write CSV
    df_res = pd.DataFrame(results)
    csv_path = out_dir / "summary_option2.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n[CSV] {csv_path}", flush=True)

    # Write REPORT.md
    report = []
    report.append("# Option 2 Phase A — TP R-Multiple + Regime Filter (NQ-only)\n")
    report.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    report.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END}")
    report.append(f"Symbole : NQ uniquement")
    report.append(f"Matrice : 5 baselines x 3 R-multiples x 2 regime filter = 30 buckets")
    report.append(f"DSR haircut : N=30 (30 buckets testes)\n")

    report.append("## TOP 15 par DSR\n")
    df_sorted = df_res.sort_values("dsr", ascending=False)
    report.append("| Bucket | n | WR% | PF | DSR | PF_min_fold | n_folds_pf>1.3 | Description |")
    report.append("|---|---|---|---|---|---|---|---|")
    for _, r in df_sorted.head(15).iterrows():
        report.append(
            f"| **{r['bucket']}** | {r['n']} | {r['wr_pct']} | {r['pf']} | "
            f"{r['dsr']} | {r['pf_min_fold']} | {r['n_folds_pf_gt_1_3']}/12 | "
            f"{r['description']} |"
        )

    report.append("\n## Verdict intermediaire\n")
    # GO si bucket avec n>=150 ET PF>=1.5 ET DSR>=0.30
    candidates = df_res[
        (df_res["n"] >= 150) & (df_res["pf"] >= 1.5) & (df_res["dsr"] >= 0.30)
    ].sort_values("dsr", ascending=False)
    if len(candidates) > 0:
        report.append(f"**GO PHASE B** : {len(candidates)} bucket(s) eligible(s) :")
        for _, r in candidates.iterrows():
            report.append(
                f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}"
            )
    else:
        report.append("**NOGO OPTION 2** : aucun bucket n>=150 ET PF>=1.5 ET DSR>=0.30")
        report.append("\nBascule recommandee : **OPTION 1** (continuation post-retest, "
                      "state machine).")
        # Top 3 quand meme pour analyse
        top3 = df_sorted.head(3)
        report.append("\nTop 3 candidats (pour analyse) :")
        for _, r in top3.iterrows():
            report.append(
                f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}, "
                f"PF_min_fold={r['pf_min_fold']}"
            )

    report.append("\n## Methodologie\n")
    report.append("- Memes anti-triche que backtester principal (entry close N, fills N+1+, "
                  "SL pessimiste, slippage par session)")
    report.append("- TP = entry +/- target_R * sl_ticks * TICK_SIZE (LONG/SHORT)")
    report.append("- SL = 40 ticks fixe NQ")
    report.append("- News veto fail-closed")
    report.append("- DSR haircut N=30 (correct pour 30 buckets independents)")

    report_path = out_dir / "REPORT_OPTION2.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(f"[REPORT] {report_path}", flush=True)

    # Print synthese console
    print(f"\n{'='*80}")
    print(f"TOP 10 PAR DSR")
    print(f"{'='*80}")
    print(df_sorted[["bucket", "n", "wr_pct", "pf", "dsr", "pf_min_fold"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
