"""
mia_vwap_reversion_test.py — Test mean reversion VWAP SD bands
===============================================================
Teste l'hypothese : quand le prix touche VWAP +2SD, revient-il
vers VWAP ou vers -2SD ? Et dans quelles conditions ?

Resultats attendus (audit market analyst 11/04/2026) :
- Hypothese "+2SD revient a -2SD" : FAUSSE (3% occurrence)
- Hypothese "+2SD revient au VWAP" : FAIBLE (6-9%)
- SEUL edge potentiel : sell +2SD en session London (66% WR)

Usage :
    python -X utf8 CORE/mia_vwap_reversion_test.py DATA/ES DATA/NQ
"""
import json
import glob
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

try:
    from CORE.constants import TICK_SIZE
except ImportError:
    TICK_SIZE = 0.25


# ─── Config ───
HORIZONS = [5, 10, 30, 60, 120]  # barres forward
SESSION_LABELS = {0: "Asia", 1: "London", 2: "US"}


def load_data(base_dir: str) -> pd.DataFrame:
    """Charge tous les JSONL d'un dossier, exclut weekends (<50 barres)."""
    rows = []
    for f in sorted(glob.glob(os.path.join(base_dir, "*.jsonl"))):
        file_rows = []
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    file_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if len(file_rows) < 50:
            continue
        rows.extend(file_rows)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ["dist_vwap_d", "dist_vwap_d_sd1u", "dist_vwap_d_sd1d",
                 "dist_vwap_d_sd2u", "dist_vwap_d_sd2d",
                 "dist_vwap_d_sd3u", "dist_vwap_d_sd3d",
                 "price", "session", "vwap_slope_30", "rvol", "atr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def classify_zone(row) -> str:
    """Classifie la position du prix par rapport aux bandes VWAP SD."""
    dv = row.get("dist_vwap_d", np.nan)
    if pd.isna(dv):
        return "?"

    # Convention DMP : dist positif = niveau AU-DESSUS du prix
    # dist_vwap_d > 0 = VWAP au-dessus du prix = prix SOUS le VWAP
    # dist_vwap_d < 0 = VWAP en-dessous du prix = prix AU-DESSUS du VWAP
    sd1u = row.get("dist_vwap_d_sd1u", np.nan)
    sd1d = row.get("dist_vwap_d_sd1d", np.nan)
    sd2u = row.get("dist_vwap_d_sd2u", np.nan)
    sd2d = row.get("dist_vwap_d_sd2d", np.nan)
    sd3u = row.get("dist_vwap_d_sd3u", np.nan)
    sd3d = row.get("dist_vwap_d_sd3d", np.nan)

    # Prix au-dessus de +3SD (sd3u negatif = prix au-dessus)
    if not pd.isna(sd3u) and sd3u < -2:
        return "> +3SD"
    if not pd.isna(sd2u) and sd2u < -2:
        return "+2SD>+3SD"
    if not pd.isna(sd1u) and sd1u < -2:
        return "+1SD>+2SD"
    if dv < -2:
        return "VWAP>+1SD"
    if dv > 2:
        return "-1SD>VWAP"
    if not pd.isna(sd1d) and sd1d > 2:
        return "-2SD>-1SD"
    if not pd.isna(sd2d) and sd2d > 2:
        return "-3SD>-2SD"
    if not pd.isna(sd3d) and sd3d > 2:
        return "< -3SD"
    return "VWAP zone"


def compute_forward_returns(df: pd.DataFrame, horizons: list) -> pd.DataFrame:
    """Calcule les rendements forward en ticks pour chaque horizon."""
    close = df["price"].values
    for h in horizons:
        fwd = np.full(len(close), np.nan)
        for i in range(len(close) - h):
            if close[i] > 0 and close[i + h] > 0:
                fwd[i] = (close[i + h] - close[i]) / TICK_SIZE
        df[f"fwd_{h}"] = fwd
    return df


def test_mean_reversion(df: pd.DataFrame, sym: str) -> list:
    """Test principal : mean reversion depuis +2SD et -2SD."""
    R = []
    R.append(f"\n{'='*75}")
    R.append(f"  {sym} — VWAP SD MEAN REVERSION TEST")
    R.append(f"  {len(df)} barres")
    R.append(f"{'='*75}")

    # Classifier les zones
    df["vwap_zone"] = df.apply(classify_zone, axis=1)

    # Distribution des zones
    R.append(f"\n  ── 1. Distribution des zones VWAP ──")
    zone_counts = df["vwap_zone"].value_counts()
    total = len(df)
    for zone in ["< -3SD", "-3SD>-2SD", "-2SD>-1SD", "-1SD>VWAP",
                  "VWAP zone", "VWAP>+1SD", "+1SD>+2SD", "+2SD>+3SD", "> +3SD"]:
        n = zone_counts.get(zone, 0)
        R.append(f"    {zone:15s}: {n:6d} ({n/total*100:5.1f}%)")

    # Calcul forward returns
    df = compute_forward_returns(df, HORIZONS)

    # ── 2. Mean reversion depuis +2SD (SELL) ──
    R.append(f"\n  ── 2. Mean reversion depuis +2SD → SELL ──")
    above_2sd = df[df["vwap_zone"].isin(["+2SD>+3SD", "> +3SD"])]
    R.append(f"    Total barres au-dessus +2SD: {len(above_2sd)}")

    if len(above_2sd) > 10:
        R.append(f"\n    {'Horizon':>10s} {'N':>6s} {'WR sell':>8s} {'Avg ticks':>10s}")
        R.append(f"    {'-'*36}")
        for h in HORIZONS:
            col = f"fwd_{h}"
            valid = above_2sd[col].dropna()
            if len(valid) < 5:
                continue
            wr_sell = (valid < 0).sum() / len(valid) * 100
            avg = valid.mean()
            R.append(f"    {f'+{h}b':>10s} {len(valid):>6d} {wr_sell:>7.1f}% {avg:>+9.2f}t")

        # Par session
        R.append(f"\n    Par session:")
        for sess_id, sess_name in SESSION_LABELS.items():
            sess_data = above_2sd[above_2sd["session"] == sess_id]
            if len(sess_data) < 10:
                continue
            for h in [30, 60]:
                col = f"fwd_{h}"
                valid = sess_data[col].dropna()
                if len(valid) < 5:
                    continue
                wr_sell = (valid < 0).sum() / len(valid) * 100
                avg = valid.mean()
                flag = " ★" if wr_sell > 60 else ""
                R.append(f"      {sess_name:8s} +{h}b: N={len(valid):>4d}  WR sell={wr_sell:5.1f}%  avg={avg:+7.2f}t{flag}")

    # ── 3. Mean reversion depuis -2SD (BUY) ──
    R.append(f"\n  ── 3. Mean reversion depuis -2SD → BUY ──")
    below_2sd = df[df["vwap_zone"].isin(["-3SD>-2SD", "< -3SD"])]
    R.append(f"    Total barres en-dessous -2SD: {len(below_2sd)}")

    if len(below_2sd) > 10:
        R.append(f"\n    {'Horizon':>10s} {'N':>6s} {'WR buy':>8s} {'Avg ticks':>10s}")
        R.append(f"    {'-'*36}")
        for h in HORIZONS:
            col = f"fwd_{h}"
            valid = below_2sd[col].dropna()
            if len(valid) < 5:
                continue
            wr_buy = (valid > 0).sum() / len(valid) * 100
            avg = valid.mean()
            R.append(f"    {f'+{h}b':>10s} {len(valid):>6d} {wr_buy:>7.1f}% {avg:>+9.2f}t")

        # Par session
        R.append(f"\n    Par session:")
        for sess_id, sess_name in SESSION_LABELS.items():
            sess_data = below_2sd[below_2sd["session"] == sess_id]
            if len(sess_data) < 10:
                continue
            for h in [30, 60]:
                col = f"fwd_{h}"
                valid = sess_data[col].dropna()
                if len(valid) < 5:
                    continue
                wr_buy = (valid > 0).sum() / len(valid) * 100
                avg = valid.mean()
                flag = " ★" if wr_buy > 60 else ""
                R.append(f"      {sess_name:8s} +{h}b: N={len(valid):>4d}  WR buy={wr_buy:5.1f}%  avg={avg:+7.2f}t{flag}")

    # ── 4. Test mimetisme : +2SD revient-il a VWAP ou -2SD ? ──
    R.append(f"\n  ── 4. Test mimetisme : +2SD revient-il a VWAP ou -2SD ? ──")
    if len(above_2sd) > 10:
        reached_vwap = 0
        reached_minus_2sd = 0
        for idx in above_2sd.index:
            pos = df.index.get_loc(idx)
            future_120 = df.iloc[pos+1:pos+121] if pos+1 < len(df) else pd.DataFrame()
            if len(future_120) == 0:
                continue
            future_zones = future_120["vwap_zone"].values
            if any(z in ["VWAP zone", "-1SD>VWAP", "VWAP>+1SD"] for z in future_zones):
                reached_vwap += 1
            if any(z in ["-2SD>-1SD", "-3SD>-2SD", "< -3SD"] for z in future_zones):
                reached_minus_2sd += 1
        n = len(above_2sd)
        R.append(f"    Depuis +2SD (N={n}):")
        R.append(f"      Revient au VWAP (120b) : {reached_vwap:>5d} ({reached_vwap/n*100:.1f}%)")
        R.append(f"      Revient a -2SD (120b)  : {reached_minus_2sd:>5d} ({reached_minus_2sd/n*100:.1f}%)")

    # ── 5. Verdict ──
    R.append(f"\n  ── 5. VERDICT {sym} ──")
    R.append(f"    Hypothese '+2SD revient a -2SD' : a verifier ci-dessus")
    R.append(f"    Edge potentiel : sell +2SD London (verifier WR > 60%)")
    R.append(f"    ATTENTION : resultats sur {len(df)} barres, regime unique")
    R.append(f"    Minimum 2-3 mois de donnees pour conclure")

    return R


def main():
    if len(sys.argv) < 2:
        print("Usage: python -X utf8 CORE/mia_vwap_reversion_test.py DATA/ES [DATA/NQ]")
        sys.exit(1)

    report = []
    report.append("=" * 75)
    report.append("  MIA VWAP SD MEAN REVERSION TEST")
    report.append(f"  Date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    report.append("=" * 75)

    for base_dir in sys.argv[1:]:
        sym = os.path.basename(base_dir)
        df = load_data(base_dir)
        if df.empty:
            report.append(f"\n  {sym}: aucune donnee")
            continue
        report.extend(test_mean_reversion(df, sym))

    output = "\n".join(report)
    print(output)

    out_path = os.path.join(sys.argv[1], "MIA_VWAP_REVERSION_REPORT.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n  Rapport sauvegarde: {out_path}")


if __name__ == "__main__":
    main()
