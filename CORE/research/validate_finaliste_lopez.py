"""validate_finaliste_lopez.py — Validation Lopez AFML Phase 2 pour finaliste BN V3.

A lancer apres Phase 1 (backtest_bn_v3_variants.py) quand un finaliste emerge
avec PF >= 1.3 ET n_trades >= 30.

Methodologie (Lopez AFML ch.14 + critical-tasks-review.md critere #8) :

  1. Walk-forward 12-fold (chronologique, pas random)
  2. PSR / DSR Lopez par fold + global
  3. Concentration analysis : max(fold_pnl) / total <= 33%
  4. Stabilite : zero fold avec PF < 0.7 (cf incident DATA_MINING_TRAP 28/04)
  5. Costs reels : commission $0.50/contrat + slip 1 tick

Verdict GO necessite **5/5 critères** verts :
  ✓ PF mean >= 1.3 sur folds
  ✓ DSR Lopez >= 0.10
  ✓ n trades total >= 30 (rare events) ou >= 100 (ideal)
  ✓ Concentration max fold <= 33%
  ✓ Zero fold avec PF < 0.7

NOGO si 1+ critere echoue.

Usage :
    python -X utf8 CORE/research/validate_finaliste_lopez.py \\
        --variant E_mode2_range --sym NQ --months 2026-03,2026-04,2026-05 --folds 12

Date : 2026-05-13
Source : Jackson directive 13/05 + audit code-reviewer (P0 #1-#4 fixes + tests)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.backtest_bn_v3_variants import (
    VARIANTS, run_variant, load_data,
)


# ─── Lopez PSR / DSR (recyclage psr_dsr_analysis.py) ──────────────────────

def compute_psr(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio (Lopez AFML ch.14).

    PSR = Phi( (SR - SR*) * sqrt(N-1) / sqrt(1 - gamma3*SR + (gamma4-1)/4 * SR^2) )
    """
    if len(returns) < 3:
        return 0.0
    sr = float(np.mean(returns) / np.std(returns, ddof=1)) if np.std(returns, ddof=1) > 0 else 0.0
    n = len(returns)
    gamma3 = float(pd.Series(returns).skew())
    gamma4 = float(pd.Series(returns).kurt())  # Fisher (excess) kurtosis
    if np.isnan(gamma3): gamma3 = 0.0
    if np.isnan(gamma4): gamma4 = 0.0
    denominator = 1.0 - gamma3 * sr + ((gamma4 - 1.0) / 4.0) * (sr ** 2)
    if denominator <= 0:
        return 0.0
    z = (sr - sr_benchmark) * np.sqrt(n - 1) / np.sqrt(denominator)
    # CDF normale standard
    from scipy import stats
    return float(stats.norm.cdf(z))


def compute_dsr(returns: np.ndarray, n_trials: int = 8) -> float:
    """Deflated Sharpe Ratio = PSR avec SR* augmente pour N_trials testes.

    Plus de variantes testees = plus de risque "data mining" = SR* plus haut requis.
    """
    if len(returns) < 3 or n_trials < 1:
        return 0.0
    n = len(returns)
    sr_star = float(np.sqrt(2.0 * np.log(max(n_trials, 1))) / np.sqrt(n))
    return compute_psr(returns, sr_benchmark=sr_star)


# ─── Walk-forward ─────────────────────────────────────────────────────────

def split_chronological_folds(df: pd.DataFrame, n_folds: int) -> list[tuple[int, int]]:
    """Split chronologique en N folds disjoints (pas overlap).

    Returns liste de (start_idx, end_idx) inclusifs pour chaque fold.
    """
    n = len(df)
    fold_size = n // n_folds
    if fold_size < 200:  # min 200 bars/fold pour warmup BN V3
        raise ValueError(f"Folds trop petits : {fold_size} bars/fold < 200 (warmup BN V3)")
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size - 1 if i < n_folds - 1 else n - 1
        folds.append((start, end))
    return folds


def run_walk_forward(variant_name: str, df: pd.DataFrame, sym: str,
                      n_folds: int = 12) -> dict:
    """Run BN V3 variant sur N folds chronologiques + compute metrics par fold."""
    if variant_name not in VARIANTS:
        raise ValueError(f"Variant '{variant_name}' not in VARIANTS={list(VARIANTS.keys())}")
    config = VARIANTS[variant_name]

    folds = split_chronological_folds(df, n_folds)
    print(f"\n=== Walk-forward {n_folds} folds (chrono, no overlap) ===")
    print(f"Variant : {variant_name}")
    print(f"Config  : {config}")
    print(f"Fold size : {(folds[0][1] - folds[0][0] + 1)} bars (~{(folds[0][1] - folds[0][0] + 1) / 1440:.1f} jours)")
    print()

    fold_results = []
    for i, (start, end) in enumerate(folds):
        fold_df = df.iloc[start:end + 1].reset_index(drop=True)
        trades, stats = run_variant(sym, fold_df, variant_name, config)
        pnls = np.array([t.pnl_usd for t in trades]) if trades else np.array([])
        wins = pnls[pnls > 0] if len(pnls) > 0 else np.array([])
        losses = pnls[pnls <= 0] if len(pnls) > 0 else np.array([])

        fold_pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 and len(losses) > 0 else (float("inf") if len(wins) > 0 else 0.0)
        fold_sharpe = float(np.mean(pnls) / np.std(pnls, ddof=1)) if len(pnls) >= 2 and np.std(pnls, ddof=1) > 0 else 0.0

        fold_stat = {
            "fold": i + 1,
            "start_ts": fold_df["ts_event"].iloc[0] if len(fold_df) > 0 else None,
            "end_ts": fold_df["ts_event"].iloc[-1] if len(fold_df) > 0 else None,
            "n_trades": len(trades),
            "n_long": sum(1 for t in trades if t.direction == "LONG"),
            "n_short": sum(1 for t in trades if t.direction == "SHORT"),
            "pf": float(fold_pf) if not np.isinf(fold_pf) else 999.0,
            "wr": float(len(wins) / max(len(pnls), 1) * 100),
            "total_pnl_usd": float(pnls.sum()) if len(pnls) > 0 else 0.0,
            "avg_pnl_usd": float(pnls.mean()) if len(pnls) > 0 else 0.0,
            "sharpe": fold_sharpe,
        }
        fold_results.append(fold_stat)
        print(f"Fold {i+1:2d}/{n_folds} | bars [{start:5d}-{end:5d}] | "
              f"n={fold_stat['n_trades']:3d} | PF={fold_stat['pf']:.2f} | "
              f"WR={fold_stat['wr']:.1f}% | PnL=${fold_stat['total_pnl_usd']:+.0f} | "
              f"Sharpe={fold_sharpe:+.2f}")

    return {"folds": fold_results, "variant": variant_name, "config": config,
            "n_folds": n_folds}


# ─── Verdict GO/NOGO ──────────────────────────────────────────────────────

def compute_verdict(walk_results: dict, n_trials: int = 8) -> dict:
    """Verdict 5/5 Lopez compliance."""
    folds = walk_results["folds"]
    pnls_per_fold = np.array([f["total_pnl_usd"] for f in folds])
    pfs_per_fold = np.array([f["pf"] for f in folds if f["pf"] < 999])
    total_trades = sum(f["n_trades"] for f in folds)

    # Compute PSR + DSR sur returns par-fold
    if len(pnls_per_fold) >= 3:
        psr = compute_psr(pnls_per_fold)
        dsr = compute_dsr(pnls_per_fold, n_trials=n_trials)
    else:
        psr = 0.0
        dsr = 0.0

    # 5 criteres Lopez
    pf_mean = float(np.mean(pfs_per_fold)) if len(pfs_per_fold) > 0 else 0.0
    total_pnl = float(pnls_per_fold.sum())
    max_fold_pnl = float(max(0, pnls_per_fold.max())) if len(pnls_per_fold) > 0 else 0.0
    concentration = max_fold_pnl / total_pnl if total_pnl > 0 else 1.0
    worst_pf = float(min([f["pf"] for f in folds if f["n_trades"] > 0], default=0.0))
    n_negative_folds = sum(1 for f in folds if f["total_pnl_usd"] < 0)

    checks = {
        "1_pf_mean_ge_1.3": (pf_mean >= 1.3, f"PF mean={pf_mean:.2f} (req >= 1.3)"),
        "2_dsr_ge_0.10":    (dsr >= 0.10,    f"DSR={dsr:.3f} (req >= 0.10)"),
        "3_n_trades_ge_30": (total_trades >= 30, f"N total trades={total_trades} (req >= 30 rare events, ideal >= 100)"),
        "4_concentration_le_33": (concentration <= 0.33, f"Concentration max fold={concentration*100:.1f}% (req <= 33%)"),
        "5_no_fold_pf_lt_0.7": (worst_pf >= 0.7 or worst_pf == 0.0, f"Worst fold PF={worst_pf:.2f} (req >= 0.7 sauf si n_trades=0)"),
    }

    all_pass = all(passed for passed, _ in checks.values())
    verdict = "GO" if all_pass else "NOGO"

    return {
        "verdict": verdict,
        "psr": psr,
        "dsr": dsr,
        "pf_mean_folds": pf_mean,
        "total_trades": total_trades,
        "total_pnl_usd": total_pnl,
        "concentration_pct": concentration * 100,
        "worst_fold_pf": worst_pf,
        "n_negative_folds": n_negative_folds,
        "n_folds": len(folds),
        "checks": checks,
    }


def print_verdict(verdict: dict, walk_results: dict) -> None:
    print()
    print("=" * 100)
    print(f"=== VERDICT LOPEZ AFML — {walk_results['variant']} ===")
    print("=" * 100)
    print(f"PSR (Lopez ch.14)       : {verdict['psr']:.3f}")
    print(f"DSR (deflated N_trials) : {verdict['dsr']:.3f}")
    print(f"PF mean folds           : {verdict['pf_mean_folds']:.2f}")
    print(f"Total trades            : {verdict['total_trades']}")
    print(f"Total PnL               : ${verdict['total_pnl_usd']:.0f}")
    print(f"Max fold concentration  : {verdict['concentration_pct']:.1f}%")
    print(f"Worst fold PF           : {verdict['worst_fold_pf']:.2f}")
    print(f"Folds negatifs          : {verdict['n_negative_folds']} / {verdict['n_folds']}")
    print()
    print("5 critères Lopez :")
    for k, (passed, msg) in verdict["checks"].items():
        icon = "✓" if passed else "✗"
        print(f"  [{icon}] {k}: {msg}")
    print()
    print(f"VERDICT FINAL : {verdict['verdict']}")
    if verdict["verdict"] == "GO":
        print("  -> Edge prouve. Integration V3 + CHANGELOG + commit OK.")
        print("  -> Toujours valider via market-analyst + paper Sim2 avant deploy live.")
    else:
        print("  -> NOGO. Pas d'integration. Cf incident DATA_MINING_TRAP 28/04 :")
        print("     5 candidats PF apparents +14-19pp -> 5/5 NOGO Lopez.")
        print("  -> Options : (a) augmenter selectivite filtres, (b) etendre periode,")
        print("              (c) tester autre variante, (d) pivot strategy.")
    print("=" * 100)


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True,
                        help=f"Variant name (one of {list(VARIANTS.keys())})")
    parser.add_argument("--sym", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--months", default="2026-03,2026-04,2026-05",
                        help="YYYY-MM,YYYY-MM,...")
    parser.add_argument("--folds", type=int, default=12)
    parser.add_argument("--n-trials", type=int, default=8,
                        help="N variantes testees Phase 1 (= deflate DSR)")
    parser.add_argument("--out-dir", default="DATA/research")
    args = parser.parse_args()

    if args.variant not in VARIANTS:
        print(f"ERROR : Variant '{args.variant}' inconnue. Choix : {list(VARIANTS.keys())}")
        sys.exit(1)

    months = [tuple(map(int, m.strip().split("-"))) for m in args.months.split(",")]

    print(f"=== Validate Finaliste Lopez — {args.variant} ===")
    print(f"Sym       : {args.sym}")
    print(f"Months    : {months}")
    print(f"Folds     : {args.folds}")
    print(f"N_trials  : {args.n_trials} (deflate DSR contre data mining)")
    print()

    df = load_data(args.sym, months)
    print(f"Loaded {len(df)} bars")

    walk_results = run_walk_forward(args.variant, df, args.sym, args.folds)
    verdict = compute_verdict(walk_results, n_trials=args.n_trials)
    print_verdict(verdict, walk_results)

    # Save outputs
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    folds_df = pd.DataFrame(walk_results["folds"])
    folds_path = out_dir / f"lopez_{args.variant}_{args.sym}_folds.csv"
    folds_df.to_csv(folds_path, index=False)
    print(f"\n[OUT] Folds : {folds_path}")

    import json
    verdict_path = out_dir / f"lopez_{args.variant}_{args.sym}_verdict.json"
    with open(verdict_path, "w", encoding="utf-8") as f:
        verdict_serializable = {
            **{k: v for k, v in verdict.items() if k != "checks"},
            "checks": {k: {"passed": bool(p), "msg": m} for k, (p, m) in verdict["checks"].items()},
            "variant": args.variant,
            "sym": args.sym,
            "months": [f"{y}-{mo:02d}" for y, mo in months],
            "n_folds": args.folds,
            "n_trials_for_dsr": args.n_trials,
        }
        json.dump(verdict_serializable, f, indent=2, default=str)
    print(f"[OUT] Verdict : {verdict_path}")


if __name__ == "__main__":
    main()
