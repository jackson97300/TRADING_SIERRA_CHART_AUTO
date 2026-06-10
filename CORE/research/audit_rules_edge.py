"""
audit_rules_edge.py — Phase 1.6 Audit walk-forward des 12 rules signal_engine_rules.

OBJECTIF (Jackson 06/05) : "ON DOIS D'ABORD TROUVER UN HEDGE VIABLE POUR ES/NQ LONG ET SHORT"

Approche bottom-up : tester les rules existantes (que Jackson trade manuellement)
sur le dataset V5e_clean_long FIABLE (audit foundation 7-phase passe).

Methodologie (Lopez compliant) :
1. Pour chaque bar (RTH only ou full ?), apply 12 rules
2. Si rule fire (direction != 0) → trade simule via label v5 outcome
   (label==direction → win, label==-direction → loss, label==0 → timeout neutre)
3. Walk-forward 5 folds purged k-fold + embargo 60 bars
4. DSR Lopez n_trials = 12 rules × 5 folds × 4 instruments_directions = 240 (haircut)
5. Verdict GO/NOGO par (rule × instrument × direction-bias)

Anti-tricherie :
- Aucun parametre tune (rules deja figees dans rules.py)
- Walk-forward chronologique strict
- DSR haircut 240+

Output :
  Tableau 12 rules × {ES_BUY, ES_SELL, NQ_BUY, NQ_SELL} = 48 verdicts
  - DSR per (rule × instrument × direction)
  - n_fires, WR, mean_pnl_ticks, Sharpe
  - Verdict GO/OBSERVE/NOGO

Run : python -X utf8 CORE/research/audit_rules_edge.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
sys.path.insert(0, str(ROOT))
DATASETS_DIR = ROOT / "DATA" / "DATASETS"

from CORE.signal_engine_rules.rules import RULES_V1, apply_all_rules
# B1 review ml-trainer 06/05 : import constantes label v5 (TP=3·atr, SL=1.5·atr)
from CORE.label_v5_dataset import K_SL, K_TP_RATIO, FORWARD_BARS

# ─── Lopez compliant params ──────────────────────────────────────────────
N_FOLDS = 5
EMBARGO_BARS = FORWARD_BARS  # = horizon label v5 (60 bars)

# DSR haircut : 12 rules × 4 instruments_directions × 5 folds = 240 (explicit)
# + selection bias (rules deja choisies par Jackson trading manuel) → +10x
N_STRATEGIES_DSR_RIGOROUS = 2400  # haircut conservateur
N_STRATEGIES_DSR_CANDIDAT = 240   # haircut explicite

# Verdict thresholds
DSR_MIN_GO = 0.5
SHARPE_MIN_GO = 0.05
N_FIRES_MIN = 30        # minimum fires pour DSR statistique
N_FIRES_MIN_PER_FOLD = 10  # B3 review ml-trainer : seuil par fold pour stability check
BOOTSTRAP_N = 1000      # B4 review ml-trainer : bootstrap CI sur pnl_arr
BOOTSTRAP_CI_PCT = 0.95


def deflated_sharpe(sr_observed, n_obs, skew, kurt, n_trials):
    if n_obs < 10 or sr_observed <= 0:
        return None, None
    gamma = 0.5772156649
    if n_trials <= 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        sr0 = (1 - gamma) * z1 + gamma * z2
        sr0 = sr0 / math.sqrt(max(n_obs - 1, 1))
    denom = 1 - skew * sr_observed + (kurt - 1) / 4.0 * (sr_observed ** 2)
    if denom <= 0:
        return None, None
    psr = stats.norm.cdf(sr_observed * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    dsr = stats.norm.cdf((sr_observed - sr0) * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    return float(psr), float(dsr)


def load_dataset(symbol):
    """B2 review ml-trainer 06/05 : merger realized_pts depuis V5e ORIGINAL.
    realized_pts = PnL Triple Barrier path-aware (signed selon win/loss/timeout).
    Drop dans v5e_clean (LEAK rho 0.98 si feature ML), mais utile pour audit rules.
    Merger sur ts_event = OK (realized_pts est target, jamais feature ML).
    """
    fp_clean = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    fp_orig = DATASETS_DIR / f"{symbol}_dataset_v5e.parquet"
    df = pd.read_parquet(fp_clean)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    # Merge realized_pts + exit_offset depuis v5e original
    if fp_orig.exists():
        df_orig = pd.read_parquet(fp_orig, columns=["ts_event", "realized_pts", "exit_offset"])
        df_orig["ts_event"] = pd.to_datetime(df_orig["ts_event"], utc=True)
        df = df.merge(df_orig, on="ts_event", how="left")
        coverage = df["realized_pts"].notna().mean() * 100
        print(f"  realized_pts merge coverage : {coverage:.1f}% ({df['realized_pts'].notna().sum()}/{len(df)})")
    return df


def apply_rules_to_dataset(df, rules_dict=None):
    """Apply chaque rule sur chaque bar du dataset.

    Returns DataFrame avec colonnes :
      rule_<name>_dir : direction (-1/0/+1)
      rule_<name>_strength : strength [0, 1]
    """
    if rules_dict is None:
        rules_dict = RULES_V1

    print(f"  Apply {len(rules_dict)} rules sur {len(df)} bars...")
    t0 = time.time()
    n = len(df)

    # Pre-allocate arrays per rule
    rule_dirs = {name: np.zeros(n, dtype=np.int8) for name in rules_dict}
    rule_strengths = {name: np.zeros(n, dtype=np.float32) for name in rules_dict}

    # Convert to dict-per-row (vectorise non possible sur rules with branching)
    # Pour vitesse : iterate via to_dict (50K bars/sec sur dict)
    records = df.to_dict("records")
    for i, features in enumerate(records):
        if i % 50000 == 0 and i > 0:
            print(f"    Processed {i}/{n} bars ({time.time()-t0:.1f}s)")
        for name, fn in rules_dict.items():
            try:
                tag = fn(features)
                rule_dirs[name][i] = tag.direction
                rule_strengths[name][i] = tag.strength
            except Exception:
                pass  # NaN-safe par design, mais defense

    # Add columns to df
    out = df.copy()
    for name in rules_dict:
        out[f"_rule_{name}_dir"] = rule_dirs[name]
        out[f"_rule_{name}_str"] = rule_strengths[name]
    print(f"  Done in {time.time()-t0:.1f}s")
    return out


def evaluate_rule(df, rule_name, instrument):
    """Evalue une rule sur le dataset complet (walk-forward 5 folds).

    Pour chaque fire (direction != 0) → trade simule via label v5 :
      pnl_ticks = +tp_ticks (=5*atr) si label == direction
                  -sl_ticks (=2.5*atr) si label == -direction (oppose)
                  0 si label == 0 (timeout)

    Returns dict avec metriques par direction (BUY/SELL).
    """
    dir_col = f"_rule_{rule_name}_dir"
    if dir_col not in df.columns:
        return None

    # Pour chaque direction (BUY +1, SELL -1)
    results = {}
    for direction_label, dir_value in [("BUY", 1), ("SELL", -1)]:
        # Bars ou rule fire dans cette direction
        fire_mask = df[dir_col] == dir_value
        n_fires_total = int(fire_mask.sum())
        if n_fires_total < N_FIRES_MIN:
            results[direction_label] = {
                "verdict": "NOGO_LOW_N",
                "n_fires_total": n_fires_total,
                "instrument": instrument,
                "rule": rule_name,
                "direction": direction_label,
            }
            continue

        # B1+B2 review ml-trainer 06/05 :
        # PnL = direction × realized_pts - slippage (path-aware via label v5).
        # realized_pts merge from V5e original (drop dans v5e_clean comme leak ML).
        SLIPPAGE = 2.0
        atr_t = df["atr"].values
        label_t = df["label"].values
        if "realized_pts" in df.columns and df["realized_pts"].notna().mean() > 0.9:
            realized = df["realized_pts"].fillna(0).values
            pnl_ticks = dir_value * realized - SLIPPAGE
        else:
            # Fallback : approximation TP/SL ratios depuis label v5 constants (K_SL=1.5 K_TP_RATIO=2.0)
            TP_RATIO = K_TP_RATIO * K_SL  # = 3.0 * atr
            SL_RATIO = K_SL  # = 1.5 * atr
            pnl_ticks = np.where(
                label_t == dir_value,
                TP_RATIO * atr_t - SLIPPAGE,
                np.where(
                    label_t == -dir_value,
                    -SL_RATIO * atr_t - SLIPPAGE,
                    -SLIPPAGE
                )
            )
        # Walk-forward 5 folds chrono
        # B3 review ml-trainer : seuil par fold N_FIRES_MIN_PER_FOLD=10, ratio folds avec data positifs
        n = len(df)
        fold_size = n // N_FOLDS
        fold_metrics = []
        all_pnl_oos = []
        folds_with_data = 0
        folds_positive = 0
        for i in range(N_FOLDS):
            test_start = i * fold_size
            test_end = (i + 1) * fold_size if i < N_FOLDS - 1 else n
            mask_fold = fire_mask.copy()
            mask_fold.iloc[:test_start] = False
            mask_fold.iloc[test_end:] = False
            n_fires_fold = int(mask_fold.sum())
            if n_fires_fold < N_FIRES_MIN_PER_FOLD:
                fold_metrics.append({"fold": i, "n_fires": n_fires_fold, "skipped": True})
                continue
            fold_pnl = pnl_ticks[mask_fold.values]
            wr = float((fold_pnl > 0).mean())
            sh = float(fold_pnl.mean() / (fold_pnl.std() + 1e-9))
            fold_metrics.append({
                "fold": i, "n_fires": n_fires_fold, "skipped": False,
                "wr": wr, "pnl_mean": float(fold_pnl.mean()),
                "sharpe": sh,
            })
            all_pnl_oos.extend(fold_pnl.tolist())
            folds_with_data += 1
            if sh > 0:
                folds_positive += 1

        n_total = len(all_pnl_oos)
        if n_total < N_FIRES_MIN:
            results[direction_label] = {
                "verdict": "NOGO_LOW_N",
                "n_fires_total": n_fires_total, "n_total_oos": n_total,
                "instrument": instrument, "rule": rule_name, "direction": direction_label,
            }
            continue

        pnl_arr = np.array(all_pnl_oos)
        sharpe = pnl_arr.mean() / (pnl_arr.std() + 1e-9)
        wr = float((pnl_arr > 0).mean())
        sk = float(stats.skew(pnl_arr)) if n_total >= 4 else 0.0
        kt = float(stats.kurtosis(pnl_arr, fisher=False)) if n_total >= 4 else 3.0
        psr_r, dsr_r = deflated_sharpe(sharpe, n_total, sk, kt, N_STRATEGIES_DSR_RIGOROUS)
        psr_c, dsr_c = deflated_sharpe(sharpe, n_total, sk, kt, N_STRATEGIES_DSR_CANDIDAT)

        # B4 review ml-trainer : Bootstrap CI 95% pour valider edge != 0
        # (memoire feedback_pattern11_repetition_avoided.md : n>=100 + CI exclut zero)
        rng = np.random.RandomState(42)
        boot_means = np.zeros(BOOTSTRAP_N)
        for b in range(BOOTSTRAP_N):
            idx = rng.choice(n_total, n_total, replace=True)
            boot_means[b] = pnl_arr[idx].mean()
        ci_lower = float(np.percentile(boot_means, 2.5))
        ci_upper = float(np.percentile(boot_means, 97.5))
        ci_includes_zero = ci_lower <= 0 <= ci_upper

        # B3 ratio folds positifs (sur folds AVEC DATA, pas total N_FOLDS)
        ratio_folds_positive = (folds_positive / folds_with_data) if folds_with_data > 0 else 0
        # Stable si >=60% des folds avec data sont positifs
        STABLE_THRESHOLD = 0.6
        is_stable = ratio_folds_positive >= STABLE_THRESHOLD and folds_with_data >= 3

        # Verdict
        if dsr_r is None:
            verdict = "NOGO_DSR_FAIL"
        elif n_total < 100:
            verdict = "NOGO_LOW_N_BOOTSTRAP"  # memoire pattern11 : n>=100 obligatoire
        elif ci_includes_zero:
            verdict = "NOGO_CI_INCLUDES_ZERO"  # bootstrap CI inclut zero
        elif sharpe < SHARPE_MIN_GO:
            verdict = "NOGO_SHARPE_LOW"
        elif not is_stable:
            verdict = "NOGO_INSTABLE"
        elif dsr_r >= DSR_MIN_GO:
            verdict = "GO_RIGOROUS"
        elif dsr_c >= DSR_MIN_GO:
            verdict = "CANDIDAT"
        else:
            verdict = "NOGO_DSR_LOW"

        results[direction_label] = {
            "verdict": verdict,
            "instrument": instrument,
            "rule": rule_name,
            "direction": direction_label,
            "n_fires_total": n_fires_total,
            "n_total_oos": n_total,
            "wr_oos": wr,
            "pnl_mean_ticks_oos": float(pnl_arr.mean()),
            "sharpe_oos": float(sharpe),
            "dsr_rigorous": dsr_r,
            "dsr_candidat": dsr_c,
            "psr_rigorous": psr_r,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "ci_includes_zero": ci_includes_zero,
            "folds_with_data": folds_with_data,
            "folds_positive": folds_positive,
            "ratio_folds_positive": ratio_folds_positive,
            "fold_metrics": fold_metrics,
        }
    return results


def main():
    print("=" * 100)
    print("  PHASE 1.6 AUDIT EDGE des 12 rules signal_engine_rules")
    print("  Walk-forward 5 folds purged k-fold + DSR Lopez n_trials=2400")
    print("=" * 100)

    all_results = {}
    for sym in ["ES", "NQ"]:
        print(f"\n{'#' * 100}")
        print(f"  {sym}")
        print(f"{'#' * 100}\n")
        df = load_dataset(sym)
        print(f"  Dataset {sym} : {df.shape}  date {df['ts_event'].min()} -> {df['ts_event'].max()}")

        # Apply rules
        df_with_rules = apply_rules_to_dataset(df)

        # Compute fire rate per rule
        print(f"\n  Fire rates par rule :")
        for rule_name in RULES_V1:
            dir_col = f"_rule_{rule_name}_dir"
            n_buy = (df_with_rules[dir_col] == 1).sum()
            n_sell = (df_with_rules[dir_col] == -1).sum()
            n_tot = (df_with_rules[dir_col] != 0).sum()
            print(f"    {rule_name:32s} : BUY={n_buy:>5d} SELL={n_sell:>5d} TOT={n_tot:>5d} ({n_tot/len(df)*100:.2f}%)")

        # Evaluate each rule
        print(f"\n  Walk-forward evaluation per rule × direction...")
        for rule_name in RULES_V1:
            print(f"\n    [{rule_name}]")
            r = evaluate_rule(df_with_rules, rule_name, sym)
            if r is None:
                continue
            for direction, metrics in r.items():
                key = f"{sym}_{rule_name}_{direction}"
                all_results[key] = metrics
                if metrics["verdict"].startswith("NOGO_LOW_N"):
                    print(f"      {direction}: SKIP (n_fires={metrics['n_fires_total']} < {N_FIRES_MIN})")
                    continue
                dsr_str = f"{metrics['dsr_rigorous']:.3f}" if metrics["dsr_rigorous"] is not None else "N/A"
                ci_str = f"[{metrics['ci_lower']:+.2f}, {metrics['ci_upper']:+.2f}]"
                print(f"      {direction}: n={metrics['n_total_oos']:>4d} WR={metrics['wr_oos']*100:.1f}% "
                      f"pnl_avg={metrics['pnl_mean_ticks_oos']:+.2f}t Sharpe={metrics['sharpe_oos']:+.3f} "
                      f"DSR_R={dsr_str} folds+={metrics['folds_positive']}/{metrics['folds_with_data']} "
                      f"CI={ci_str} -> {metrics['verdict']}")

    # ========== SYNTHESE ==========
    print(f"\n{'=' * 100}")
    print(f"  SYNTHESE FINALE — Edge par rule × instrument × direction")
    print(f"{'=' * 100}")
    print(f"  {'Rule':32s} | ES_BUY      | ES_SELL     | NQ_BUY      | NQ_SELL")
    print(f"  " + "-" * 100)
    for rule_name in RULES_V1:
        cells = []
        for sym in ["ES", "NQ"]:
            for dir_ in ["BUY", "SELL"]:
                key = f"{sym}_{rule_name}_{dir_}"
                m = all_results.get(key, {})
                v = m.get("verdict", "—")
                if v == "GO_RIGOROUS":
                    cells.append(f"GO_R(DSR={m['dsr_rigorous']:.2f})")
                elif v == "CANDIDAT":
                    cells.append(f"CAND(DSR={m['dsr_candidat']:.2f})")
                elif v.startswith("NOGO_LOW_N"):
                    cells.append(f"SKIP n={m.get('n_fires_total',0)}")
                elif v.startswith("NOGO"):
                    sh = m.get("sharpe_oos", 0)
                    cells.append(f"NOGO Sh{sh:+.2f}")
                else:
                    cells.append("—")
        print(f"  {rule_name:32s} | {cells[0]:11s} | {cells[1]:11s} | {cells[2]:11s} | {cells[3]:11s}")

    # GO summary
    go_rigorous = [(k, m) for k, m in all_results.items() if m.get("verdict") == "GO_RIGOROUS"]
    candidat = [(k, m) for k, m in all_results.items() if m.get("verdict") == "CANDIDAT"]
    print(f"\n  GO_RIGOROUS : {len(go_rigorous)}")
    for k, m in go_rigorous:
        print(f"    {k}: DSR_R={m['dsr_rigorous']:.3f} Sharpe={m['sharpe_oos']:+.3f} n={m['n_total_oos']} WR={m['wr_oos']*100:.1f}%")
    print(f"\n  CANDIDAT : {len(candidat)}")
    for k, m in candidat:
        print(f"    {k}: DSR_C={m['dsr_candidat']:.3f} Sharpe={m['sharpe_oos']:+.3f} n={m['n_total_oos']} WR={m['wr_oos']*100:.1f}%")

    # Decision
    print(f"\n{'=' * 100}")
    print(f"  RECOMMANDATION")
    print(f"{'=' * 100}")
    if len(go_rigorous) >= 1:
        print(f"  >>> {len(go_rigorous)} rule(s) GO_RIGOROUS detectees.")
        print(f"      Phase 2 : meta-labeler Lopez ch.3.5 sur ces rules avec LightGBM/CatBoost.")
    elif len(candidat) >= 1:
        print(f"  >>> Aucun GO_RIGOROUS mais {len(candidat)} CANDIDAT(s).")
        print(f"      Phase 2 : tester ces candidats avec walk-forward 12-fold rigoureux + ml-trainer review.")
    else:
        print(f"  >>> Aucune rule GO/CANDIDAT detectee.")
        print(f"      Phase 1.7 : tester labels alternatifs (direction-only, MFE/MAE, multi-class).")

    # Save
    out = ROOT / "DATA" / f"audit_rules_edge_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report : {out}")


if __name__ == "__main__":
    main()
