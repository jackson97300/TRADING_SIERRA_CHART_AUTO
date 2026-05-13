"""backtest_v6_groupa_predictivity.py — backtest predictivite v6_complete GROUPE A.

Phase 1b du plan migration Bot 2 V6 full Databento (13/05/2026 soir).
Objectif : valider que les 6 features Python (v0.2 v6_complete) ont un edge
predictif AU MOINS EQUIVALENT aux features DMP equivalentes.

Methode :
  1. Load V4 enriched parquet (avril 2026, ~29635 bars ES)
  2. Apply apply_v6_complete -> ajout 6 features Python (suffixe _py)
  3. Garde les colonnes DMP equivalentes (suffixe _dmp)
  4. Genere labels TBM (Triple Barrier Method Lopez AFML ch.3) :
       pour chaque bar : TP touche avant SL dans horizon ? +1 BUY win, -1 BUY loss
       Symetric pour SELL. On utilise long-only target par defaut.
  5. Spearman corr (feature × label) pour chaque feature Py et DMP
  6. Decision :
       Python Spearman >= DMP Spearman - 0.01 -> feature RETENUE (equivalence)
       Python Spearman > DMP Spearman          -> BONUS (meilleure)
       Python Spearman < DMP Spearman - 0.03   -> A REFORMULER

Critere global : >= 4/6 features RETENUE -> GO commit + cabler dans build_v4
              <= 3/6 features RETENUE   -> NOGO, reformuler ou hybride
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
from phase_b_v6_complete import apply_v6_complete  # noqa: E402


# Tick size ES (1 tick = 0.25 points)
TICK_ES = 0.25


def generate_tbm_labels(
    df: pd.DataFrame,
    tp_ticks: int = 10,
    sl_ticks: int = 5,
    horizon: int = 30,
    side: str = "long",
    tick: float = TICK_ES,
) -> pd.Series:
    """Triple Barrier Method labeling pour chaque bar.

    Pour chaque bar i, regarde les bars [i+1, i+horizon] :
      - Si HIGH atteint close[i] + tp_ticks*tick avant LOW atteint close[i] - sl_ticks*tick : +1 (TP)
      - Sinon si LOW atteint close[i] - sl_ticks*tick : -1 (SL)
      - Sinon : 0 (vertical timeout)

    Pour SHORT : symetric (inverser HIGH/LOW + signe).

    Returns pd.Series int8 sign label aligne sur df.index.
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    labels = np.zeros(n, dtype=np.int8)

    tp_pts = tp_ticks * tick
    sl_pts = sl_ticks * tick

    for i in range(n - horizon):
        entry = close[i]
        if side == "long":
            tp_level = entry + tp_pts
            sl_level = entry - sl_pts
            # Scan forward
            for j in range(1, horizon + 1):
                if high[i + j] >= tp_level:
                    labels[i] = 1
                    break
                if low[i + j] <= sl_level:
                    labels[i] = -1
                    break
        else:  # short
            tp_level = entry - tp_pts
            sl_level = entry + sl_pts
            for j in range(1, horizon + 1):
                if low[i + j] <= tp_level:
                    labels[i] = 1
                    break
                if high[i + j] >= sl_level:
                    labels[i] = -1
                    break

    return pd.Series(labels, index=df.index, name=f"label_tbm_{side}")


def spearman_safe(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    """Spearman correlation sur les valeurs valides. Retourne (rho, n_valid)."""
    mask = x.notna() & y.notna()
    if mask.sum() < 100:
        return (np.nan, int(mask.sum()))
    rho, _ = spearmanr(x[mask], y[mask])
    return (float(rho), int(mask.sum()))


def run_backtest():
    print("=" * 80)
    print("Backtest predictivite v6_complete GROUPE A — Phase 1b")
    print("=" * 80)

    # 1. Load V4 parquet ES avril 2026
    fpath = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet"
    print(f"Loading {fpath.name}...")
    df = pd.read_parquet(fpath)
    print(f"  {len(df)} bars, {len(df.columns)} cols")

    # 2. Garder colonnes DMP equivalentes (renommer _dmp)
    dmp_targets = ["range_pos", "momentum_3b", "sess_range_atr",
                   "vwap_w_side", "vwap_triple_align", "cvd_day_dir"]
    dmp_vals = df[dmp_targets].copy()
    dmp_vals.columns = [f"{c}_dmp" for c in dmp_targets]

    # 3. Drop ces colonnes du df_input, applique v6_complete (Python)
    df_input = df.drop(columns=dmp_targets)
    df_calc = apply_v6_complete(df_input)
    # Renommer en _py
    for c in dmp_targets:
        df_calc.rename(columns={c: f"{c}_py"}, inplace=True)

    # 4. Reconcat
    df_all = pd.concat([df_calc, dmp_vals], axis=1)

    # 5. Generer labels TBM long-only et short-only
    print("Generating TBM labels (TP=10t, SL=5t, horizon=30 bars)...")
    df_all["label_long"] = generate_tbm_labels(df_all, tp_ticks=10, sl_ticks=5, horizon=30, side="long")
    df_all["label_short"] = generate_tbm_labels(df_all, tp_ticks=10, sl_ticks=5, horizon=30, side="short")

    # Distribution labels
    for side in ("long", "short"):
        vc = df_all[f"label_{side}"].value_counts(normalize=True).sort_index()
        dist = ", ".join([f"{int(k)}:{100*v:.1f}%" for k, v in vc.items()])
        print(f"  label_{side} dist: {dist}")

    # 6. Spearman corr pour chaque feature × label
    print()
    print("RESULTS — Spearman corr feature × target label:")
    print("=" * 80)
    print(f"{'Feature':<22}{'Py vs LONG':>15}{'DMP vs LONG':>15}{'Py vs SHORT':>15}{'DMP vs SHORT':>15}")
    print("-" * 80)

    results = []
    for col in dmp_targets:
        py = df_all[f"{col}_py"]
        dmp = df_all[f"{col}_dmp"]

        rho_py_long, n_py_long = spearman_safe(py, df_all["label_long"])
        rho_dmp_long, n_dmp_long = spearman_safe(dmp, df_all["label_long"])
        rho_py_short, _ = spearman_safe(py, df_all["label_short"])
        rho_dmp_short, _ = spearman_safe(dmp, df_all["label_short"])

        print(f"{col:<22}{rho_py_long:>15.4f}{rho_dmp_long:>15.4f}{rho_py_short:>15.4f}{rho_dmp_short:>15.4f}")
        results.append({
            "feature": col,
            "py_long": rho_py_long, "dmp_long": rho_dmp_long,
            "py_short": rho_py_short, "dmp_short": rho_dmp_short,
            "n_py_long": n_py_long, "n_dmp_long": n_dmp_long,
        })

    # 7. Decision : Python >= DMP - 0.01 ?
    print()
    print("DECISION (cible : Py_rho >= DMP_rho - 0.01, sur LONG ou SHORT) :")
    print("-" * 80)
    retenu_count = 0
    for r in results:
        # Best abs rho cote DMP (long ou short)
        dmp_best = max(abs(r["dmp_long"]), abs(r["dmp_short"]))
        py_best = max(abs(r["py_long"]), abs(r["py_short"]))
        # Si Python s'aligne (ecart < 0.01) ou est meilleur
        delta = py_best - dmp_best
        if delta >= -0.01:
            status = "RETENUE" if delta < 0.01 else "BONUS  "
            retenu_count += 1
        elif delta >= -0.03:
            status = "MEDIUM "
        else:
            status = "REJET  "
        print(f"  {r['feature']:<22}: |rho_py|={py_best:.4f} |rho_dmp|={dmp_best:.4f} delta={delta:+.4f} [{status}]")

    print()
    print("=" * 80)
    print(f"VERDICT GLOBAL : {retenu_count}/6 features RETENUE ou BONUS")
    if retenu_count >= 4:
        print("  => GO CABLER apply_v6_complete dans build_v4 (apres shadow run 5j)")
    else:
        print("  => NOGO : reformuler features ou strategie hybride DMP partiel")
    print("=" * 80)

    return results


if __name__ == "__main__":
    run_backtest()
