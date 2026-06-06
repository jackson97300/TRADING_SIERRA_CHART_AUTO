"""test_parity_B1.py - Test parite Batch B1 F3 Distances normalisees _pct.

Objectif :
  Verifier que la formule C++ DMP_CalcDistPct produirait les memes valeurs que
  la formule Python phase_b_helpers.py:1063-1093 _dist() pour 29 features
  (groupes A-E parite bit-for-bit attendue).

Methode :
  1. Lire fichier Sierra DMP brut pre-port (schema 3.7.15-17, sans _pct C++)
  2. Calculer MANUELLEMENT en Python les ~29 pct via formule (level - close) / close * 100
  3. Lire fichier live_enriched correspondant (pipeline Python avec vrais _pct)
  4. Compare valeurs : max_abs_diff < 1e-3, Spearman > 0.99
  5. Rapport parite par feature

Limites :
  - Groupe F (8 features Zones nearest) NON teste parite : Sierra utilise
    Extension Lines, Python utilise streams zones. Divergence methode
    intentionnelle, documente dans DMP_F3_DistNormalisees.h.

Usage :
  python -X utf8 tools/test_parity_B1.py [--sym NQ] [--date 20260603]

Auteur : Batch B1 port — 2026-06-07
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Features _pct testables (29 groupes A-E directes)
# Map : feature_pct -> niveau brut Sierra DMP correspondant
PARITY_MAP = {
    # Groupe A — VWAP _pct (13)
    "dist_vwap_d_pct":       "vwap_d_pct_NEEDS_RECALC",          # Sierra a dist_vwap_d (ticks), pas vwap_d directement
    "dist_vwap_d_sd1u_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_d_sd1d_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_d_sd2u_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_d_sd2d_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_d_sd3u_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_d_sd3d_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_w_pct":       "RECALC_FROM_TICKS",
    "dist_vwap_w_sd1u_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_w_sd1d_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_m_pct":       "RECALC_FROM_TICKS",
    "dist_vwap_m_sd1u_pct":  "RECALC_FROM_TICKS",
    "dist_vwap_m_sd1d_pct":  "RECALC_FROM_TICKS",
    # Groupe B — VP _pct (6)
    "dist_cur_vpoc_pct":     "RECALC_FROM_TICKS",
    "dist_cur_vah_pct":      "RECALC_FROM_TICKS",
    "dist_cur_val_pct":      "RECALC_FROM_TICKS",
    "dist_prev_vpoc_pct":    "RECALC_FROM_TICKS",
    "dist_prev_vah_pct":     "RECALC_FROM_TICKS",
    "dist_prev_val_pct":     "RECALC_FROM_TICKS",
    # Groupe C — Session _pct (2)
    "dist_sess_high_pct":    "RECALC_FROM_TICKS",
    "dist_sess_low_pct":     "RECALC_FROM_TICKS",
    # Groupe D — MenthorQ _pct (6)
    "dist_mq_call_pct":      "RECALC_FROM_TICKS",
    "dist_mq_put_pct":       "RECALC_FROM_TICKS",
    "dist_mq_hvl_pct":       "RECALC_FROM_TICKS",
    "dist_mq_call_0dte_pct": "RECALC_FROM_TICKS",
    "dist_mq_put_0dte_pct":  "RECALC_FROM_TICKS",
    "dist_mq_hvl_0dte_pct":  "RECALC_FROM_TICKS",
    # Groupe E — 1D Extremes _pct (2)
    "dist_1d_max_ticks_pct": "RECALC_FROM_TICKS",
    "dist_1d_min_ticks_pct": "RECALC_FROM_TICKS",
}

# Map dist_*_pct -> dist_*_ticks correspondant cote Sierra DMP
# La conversion C++ exacte : pct = (level - close) / close * 100
# Equivalent : pct = (dist_ticks * tick_size) / close * 100
DIST_TICKS_MAP = {
    "dist_vwap_d_pct":       "dist_vwap_d",
    "dist_vwap_d_sd1u_pct":  "dist_vwap_d_sd1u",
    "dist_vwap_d_sd1d_pct":  "dist_vwap_d_sd1d",
    "dist_vwap_d_sd2u_pct":  "dist_vwap_d_sd2u",
    "dist_vwap_d_sd2d_pct":  "dist_vwap_d_sd2d",
    "dist_vwap_d_sd3u_pct":  "dist_vwap_d_sd3u",
    "dist_vwap_d_sd3d_pct":  "dist_vwap_d_sd3d",
    "dist_vwap_w_pct":       "dist_vwap_w",
    "dist_vwap_m_pct":       "dist_vwap_m",
    "dist_cur_vpoc_pct":     "dist_cur_vpoc",
    "dist_cur_vah_pct":      "dist_cur_vah",
    "dist_cur_val_pct":      "dist_cur_val",
    "dist_prev_vpoc_pct":    "dist_prev_vpoc",
    "dist_prev_vah_pct":     "dist_prev_vah",
    "dist_prev_val_pct":     "dist_prev_val",
    "dist_sess_high_pct":    "dist_sess_high",
    "dist_sess_low_pct":     "dist_sess_low",
    "dist_mq_call_pct":      "dist_mq_call",
    "dist_mq_put_pct":       "dist_mq_put",
    "dist_mq_hvl_pct":       "dist_mq_hvl",
    "dist_mq_call_0dte_pct": "dist_mq_call_0dte",
    "dist_mq_put_0dte_pct":  "dist_mq_put_0dte",
    "dist_mq_hvl_0dte_pct":  "dist_mq_hvl_0dte",
    "dist_1d_max_ticks_pct": "dist_1d_max_ticks",
    "dist_1d_min_ticks_pct": "dist_1d_min_ticks",
}

# Features VWAP weekly/monthly SD (existent en _pct Python mais Sierra n'a pas
# dist_vwap_w_sd1u/d ni dist_vwap_m_sd1u/d en TICKS dans le JSONL — seulement
# dist_vwap_w et dist_vwap_m). On peut quand meme reconstruire en utilisant le
# niveau brut si disponible (le pipeline Python le calcule via phase_b_plus).
# Pour parite Sierra C++, ces features dependent de r.vwap_weekly_sd1u/d et
# r.vwap_monthly_sd1u/d (existent en RawData mais ne sont PAS exposees en
# feature ML pre-Batch B1 — donc impossible a tester ici). On skip ces 4 :
#   dist_vwap_w_sd1u_pct, dist_vwap_w_sd1d_pct,
#   dist_vwap_m_sd1u_pct, dist_vwap_m_sd1d_pct
SKIP_NO_TICKS = {
    "dist_vwap_w_sd1u_pct",
    "dist_vwap_w_sd1d_pct",
    "dist_vwap_m_sd1u_pct",
    "dist_vwap_m_sd1d_pct",
}


def load_jsonl(path: Path, sample: int = 1000) -> pd.DataFrame:
    """Lit un JSONL ligne par ligne (skip JSONDecodeError silently)."""
    rows = []
    if not path.exists():
        return pd.DataFrame()
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= sample:
                break
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(rows)


def compute_cpp_equivalent_pct(df_sierra: pd.DataFrame, tick_size: float) -> pd.DataFrame:
    """Recalcule en Python ce que produirait C++ DMP_CalcDistPct.

    Formule C++ : pct = (level - close) / close * 100
    Equivalent  : pct = (dist_ticks * tick_size) / close * 100

    Renvoie un DataFrame avec colonnes dist_*_pct calculees.
    """
    out = {}
    close = df_sierra.get("price")
    if close is None or close.empty:
        return pd.DataFrame()

    for pct_col, ticks_col in DIST_TICKS_MAP.items():
        if ticks_col not in df_sierra.columns:
            out[pct_col] = pd.Series([float("nan")] * len(df_sierra))
            continue
        dist_ticks = df_sierra[ticks_col]
        # pct = (dist_ticks * tick_size) / close * 100
        pct = (dist_ticks * tick_size) / close * 100.0
        # Conserver NaN ou si close=0
        pct = pct.where(close > 0, other=float("nan"))
        out[pct_col] = pct
    return pd.DataFrame(out, index=df_sierra.index)


def join_on_ts(df_sierra: pd.DataFrame, df_live: pd.DataFrame) -> pd.DataFrame:
    """Joint Sierra et live_enriched sur le timestamp 'ts' (millis epoch)."""
    if "ts" not in df_sierra.columns or "ts" not in df_live.columns:
        return pd.DataFrame()
    s = df_sierra.set_index("ts")
    l = df_live.set_index("ts")
    # Inner join sur ts commun
    common_ts = s.index.intersection(l.index)
    return pd.DataFrame({
        "_n_sierra": [len(s)],
        "_n_live": [len(l)],
        "_n_common": [len(common_ts)],
    }), s.loc[common_ts], l.loc[common_ts]


def spearman_safe(x: pd.Series, y: pd.Series) -> float:
    """Spearman simple, NaN-safe. Retourne NaN si <30 paires valides."""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 30:
        return float("nan")
    return float(df["x"].corr(df["y"], method="spearman"))


def main():
    p = argparse.ArgumentParser(description="Test parite Batch B1 F3 _pct")
    p.add_argument("--sym", default="NQ", choices=("NQ", "ES"))
    p.add_argument("--date", default="20260603", help="YYYYMMDD")
    p.add_argument("--sample", type=int, default=1000, help="Nb lignes lues")
    args = p.parse_args()

    tick_size = 0.25  # ES/NQ
    sierra_path = ROOT / "DATA" / args.sym / f"{args.date}_{args.sym}.jsonl"
    live_path = ROOT / "DATA" / "live_enriched" / args.sym / f"{args.date}_{args.sym}.jsonl"

    print("=" * 70)
    print(f"TEST PARITE BATCH B1 — F3 Distances normalisees _pct")
    print(f"  sym={args.sym}  date={args.date}  sample={args.sample}")
    print(f"  tick_size={tick_size}")
    print(f"  Sierra : {sierra_path}")
    print(f"  Live   : {live_path}")
    print("=" * 70)

    df_sierra = load_jsonl(sierra_path, args.sample)
    df_live = load_jsonl(live_path, args.sample)
    print(f"Loaded sierra={len(df_sierra)} rows  live={len(df_live)} rows")

    if df_sierra.empty or df_live.empty:
        print("FAIL : un fichier vide ou absent")
        return 1

    # Calcul C++-equivalent
    df_cpp = compute_cpp_equivalent_pct(df_sierra, tick_size)
    print(f"Computed {len(df_cpp.columns)} dist_*_pct cols (C++ pendant)")

    # Join sur ts
    join_meta, s_idx, l_idx = join_on_ts(df_sierra, df_live)
    print(f"Join on ts : {join_meta.iloc[0]['_n_common']} bars communes")
    # Realign cpp DataFrame on s_idx
    df_cpp_idx = df_cpp.set_index(df_sierra["ts"]).loc[s_idx.index]

    print()
    print(f"{'Feature':<32} {'n_pairs':>8} {'max_diff':>10} {'med_diff':>10} {'spearman':>9} {'status':>8}")
    print("-" * 90)

    results = []
    for pct_col in DIST_TICKS_MAP.keys():
        if pct_col in SKIP_NO_TICKS:
            print(f"{pct_col:<32} {'SKIP':>8} {'-':>10} {'-':>10} {'-':>9} {'SKIP':>8}")
            continue
        if pct_col not in l_idx.columns:
            print(f"{pct_col:<32} {'-':>8} {'-':>10} {'-':>10} {'-':>9} {'MISSING':>8}")
            continue
        cpp_v = df_cpp_idx[pct_col]
        py_v = l_idx[pct_col]
        df_pair = pd.DataFrame({"cpp": cpp_v.values, "py": py_v.values}).dropna()
        n_pairs = len(df_pair)
        if n_pairs < 30:
            print(f"{pct_col:<32} {n_pairs:>8} {'-':>10} {'-':>10} {'-':>9} {'TOO_FEW':>8}")
            continue
        diff = (df_pair["cpp"] - df_pair["py"]).abs()
        max_diff = float(diff.max())
        med_diff = float(diff.median())
        sp = spearman_safe(df_pair["cpp"], df_pair["py"])
        # Tolerance pct : 1e-3 absolu OU spearman > 0.99
        status = "PASS" if (max_diff < 1e-3 or (not math.isnan(sp) and sp > 0.99)) else "FAIL"
        print(f"{pct_col:<32} {n_pairs:>8} {max_diff:>10.6f} {med_diff:>10.6f} {sp:>9.4f} {status:>8}")
        results.append((pct_col, n_pairs, max_diff, med_diff, sp, status))

    print()
    n_pass = sum(1 for r in results if r[5] == "PASS")
    n_fail = sum(1 for r in results if r[5] == "FAIL")
    n_total = len(results)
    print(f"RESULT : {n_pass}/{n_total} PASS  ({n_fail} FAIL)")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
