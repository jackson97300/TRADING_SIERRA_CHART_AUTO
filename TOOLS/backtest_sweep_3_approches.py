"""Backtest sweep 3 approches feature anti-pattern 'BUY mur en trend up'.

Approches testees :
A1 — Trend + OrderFlow + Big Spawn (etendu fenetres 20/30/50/100)
A2 — Wyckoff + Volume Profile + VWAP (Dalton-inspired)
A3 — Multi-temporal momentum + Confluence niveaux (cross-feature)

Pour chaque : Spearman vs forward return 5/15/30/60 bars.
Output : DOCS/BACKTEST_3_APPROCHES.md + scoreboard "l'elue".

PAS DE ML - regles deterministes pures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "DATA" / "live_enriched" / "NQ"
OUT = ROOT / "DOCS" / "BACKTEST_3_APPROCHES.md"

# Fenetres rolling a tester
WINDOWS = [20, 30, 50, 100]
# Labels forward (en bars 1-min)
FORWARDS = [5, 15, 30, 60]


def load_day(fp: Path) -> pd.DataFrame:
    bars = []
    with open(fp, "r", encoding="utf-8") as fh:
        for line in fh:
            try: bars.append(json.loads(line))
            except: pass
    df = pd.DataFrame(bars)
    if df.empty: return df
    if "ts" in df.columns:
        df["ts_event"] = pd.to_datetime(df["ts"], utc=True, unit="ms")
        df["ts_et"] = df["ts_event"].dt.tz_convert("America/New_York")
        df["mins_et"] = df["ts_et"].dt.hour * 60 + df["ts_et"].dt.minute
    # Cast numeric critical
    for col in ("close", "delta_bar", "atr", "atr_14m", "vwap_slope_10",
                "n_big_ask_t1", "n_big_bid_t1", "cvd_day", "cvd_day_dir",
                "range_pos", "dist_vwap_d_atr", "dist_cur_vpoc",
                "single_print_count", "vwap_d_side", "total_vol",
                "dist_pdh_pct", "dist_pdl_pct", "delta_day"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ===========================================
# APPROCHE 1 : Trend + OrderFlow + Big Spawn
# ===========================================

def compute_a1_features(df: pd.DataFrame) -> pd.DataFrame:
    """A1: trend(N) * orderflow(N) * big_spawn(N) — N varie 20-100."""
    out = pd.DataFrame(index=df.index)
    for N in WINDOWS:
        # Trend = price slope normalise ATR
        if "close" in df.columns and "atr" in df.columns:
            trend = (df["close"] - df["close"].shift(N)) / df["atr"]
            # OrderFlow = delta_bar EMA
            of_ema = df["delta_bar"].ewm(span=N, min_periods=N//2).mean() if "delta_bar" in df.columns else pd.Series(0, index=df.index)
            # Big spawn = % bars avec big_ask_t1 > 0 sur N derniers
            if "n_big_ask_t1" in df.columns:
                bs = (df["n_big_ask_t1"] > 0).rolling(N, min_periods=N//2).mean()
            else:
                bs = pd.Series(0.5, index=df.index)
            # Score = trend * orderflow * (big_spawn - 0.5) * 2  (centrer big_spawn)
            score = trend * np.sign(of_ema) * np.abs(of_ema).clip(upper=100) * (bs - 0.5) * 2
            out[f"A1_N{N}"] = score
    return out


# ===========================================
# APPROCHE 2 : Wyckoff + VP + VWAP
# ===========================================

def compute_a2_features(df: pd.DataFrame) -> pd.DataFrame:
    """A2: Position VP * VWAP slope * CVD direction * single prints."""
    out = pd.DataFrame(index=df.index)
    if "range_pos" not in df.columns or "vwap_slope_10" not in df.columns:
        return out

    # range_pos est en [0, 1] selon Sierra (position dans VA session)
    # Centrer autour 0.5 et amplifier
    pos_centered = (df["range_pos"].fillna(0.5) - 0.5) * 2  # [-1, +1]

    # VWAP slope direction et magnitude
    vs = df["vwap_slope_10"].fillna(0)
    vs_norm = vs / df["atr"].clip(lower=1)  # normalise par ATR

    # CVD direction (Sierra sain)
    cvd_dir = df.get("cvd_day_dir", pd.Series(0, index=df.index)).fillna(0)

    # Single print count (trend day proxy)
    sp = df.get("single_print_count", pd.Series(0, index=df.index)).fillna(0)
    sp_high = (sp > 100).astype(float)  # >100 = trend day

    # Vol increasing (range expansion proxy)
    if "atr_14m" in df.columns:
        vol_exp = df["atr_14m"] / df["atr_14m"].rolling(60, min_periods=20).mean() - 1
    else:
        vol_exp = pd.Series(0, index=df.index)

    for N in WINDOWS:
        # Rolling Z-scores
        pos_z = (pos_centered - pos_centered.rolling(N, min_periods=N//2).mean()) / pos_centered.rolling(N, min_periods=N//2).std().clip(lower=0.01)
        vs_z = vs_norm.rolling(N, min_periods=N//2).mean()

        # Score composite : alignment direction
        score = (
            pos_z * 0.3 +
            np.sign(vs_z) * np.abs(vs_z).clip(upper=3) * 0.3 +
            cvd_dir * 0.2 +
            sp_high * np.sign(vs_z) * 0.1 +
            vol_exp.fillna(0).clip(-1, 1) * 0.1
        )
        out[f"A2_N{N}"] = score
    return out


# ===========================================
# APPROCHE 3 : Multi-temporal momentum + Confluence
# ===========================================

def compute_a3_features(df: pd.DataFrame) -> pd.DataFrame:
    """A3: Momentum 3 timeframes + confluence niveaux + range expansion."""
    out = pd.DataFrame(index=df.index)
    if "close" not in df.columns or "atr" not in df.columns:
        return out

    # Momentums sur differentes fenetres
    mom_5 = (df["close"] - df["close"].shift(5)) / df["atr"]
    mom_20 = (df["close"] - df["close"].shift(20)) / df["atr"]
    mom_60 = (df["close"] - df["close"].shift(60)) / df["atr"]

    # VWAP slope direction (deja dispo)
    vs = df.get("vwap_slope_10", pd.Series(0, index=df.index)).fillna(0)
    vs_sign = np.sign(vs)

    # Range expansion : atr_14m vs sa moyenne longue
    if "atr_14m" in df.columns:
        atr_long = df["atr_14m"].rolling(120, min_periods=30).mean()
        range_exp = (df["atr_14m"] / atr_long.clip(lower=0.1) - 1).clip(-1, 2)
    else:
        range_exp = pd.Series(0, index=df.index)

    # Confluence niveau (proche PDH ou PDL)
    near_pdh = (df.get("dist_pdh_pct", pd.Series(99, index=df.index)).fillna(99).abs() < 0.2).astype(float)
    near_pdl = (df.get("dist_pdl_pct", pd.Series(99, index=df.index)).fillna(99).abs() < 0.2).astype(float)
    near_key = (near_pdh + near_pdl).clip(0, 1)

    for N in WINDOWS:
        # Coherence multi-temporel
        coh = np.sign(mom_5) * np.sign(mom_20) * np.sign(mom_60)  # +1 si 3 alignes, -1 si discordants

        # Score : coherence * magnitude * vwap dir * range_exp
        mag = (mom_5.abs() + mom_20.abs() + mom_60.abs()) / 3
        score = (
            coh * mag * 0.4 +
            vs_sign * mag.clip(upper=2) * 0.3 +
            range_exp.fillna(0) * np.sign(mom_20) * 0.2 +
            (1 - near_key) * np.sign(mom_20) * 0.1  # bonus si LOIN d'un mur
        )
        out[f"A3_N{N}"] = score
    return out


# ===========================================
# EVALUATION : Spearman vs forward returns
# ===========================================

def evaluate_day(df: pd.DataFrame) -> Dict[str, float]:
    """Spearman des features vs forward returns 5/15/30/60 bars."""
    if df.empty or "close" not in df.columns:
        return {}

    # Compute features
    a1 = compute_a1_features(df)
    a2 = compute_a2_features(df)
    a3 = compute_a3_features(df)
    feats = pd.concat([a1, a2, a3], axis=1)

    # Filter RTH
    if "mins_et" in df.columns:
        mask_rth = (df.mins_et >= 570) & (df.mins_et < 960)
    else:
        mask_rth = pd.Series(True, index=df.index)

    out = {}
    for fwd in FORWARDS:
        label = df["close"].shift(-fwd) - df["close"]
        for col in feats.columns:
            common = feats[mask_rth].join(label.rename("y"), how="inner").dropna(subset=[col, "y"])
            if len(common) < 30: continue
            try:
                rho = common[col].rank().corr(common["y"].rank())
                out[f"{col}_fwd{fwd}"] = float(rho)
            except Exception:
                pass
    return out


def main():
    files = sorted(DATA_DIR.glob("*_NQ.jsonl"))[-100:]
    print(f"=== Backtest 3 approches sur {len(files)} jours NQ ===\n")

    daily = []
    for i, fp in enumerate(files):
        try:
            df = load_day(fp)
            if df.empty: continue
            stats = evaluate_day(df)
            if stats:
                stats["day"] = fp.stem.split("_")[0]
                daily.append(stats)
        except Exception as e:
            pass
        if (i+1) % 20 == 0:
            print(f"  {i+1}/{len(files)} jours...")

    d = pd.DataFrame(daily)
    print(f"\nJours exploitables : {len(d)}")

    # Aggregation
    rho_cols = [c for c in d.columns if c != "day"]
    summary = []
    for c in rho_cols:
        s = d[c].dropna()
        if len(s) < 10: continue
        summary.append({
            "feature": c,
            "n_days": len(s),
            "rho_mean": round(float(s.mean()), 4),
            "rho_median": round(float(s.median()), 4),
            "rho_abs_mean": round(float(s.abs().mean()), 4),
            "pct_significant": round(100 * (s.abs() > 0.1).sum() / len(s), 1),
            "pct_strong": round(100 * (s.abs() > 0.2).sum() / len(s), 1),
        })

    summary_df = pd.DataFrame(summary)
    summary_df = summary_df.sort_values("rho_abs_mean", ascending=False)

    print("\n=== TOP 20 features par |rho_mean| ===")
    print(summary_df.head(20).to_string(index=False))

    # Top par approche
    top_by_approche = {}
    for approche in ["A1", "A2", "A3"]:
        subset = summary_df[summary_df.feature.str.startswith(approche + "_")]
        if len(subset) > 0:
            top_by_approche[approche] = subset.iloc[0]

    # Rapport markdown
    md = []
    md.append("# Backtest 3 approches feature alignment trend / orderflow")
    md.append("")
    md.append(f"**Date** : 2026-06-07")
    md.append(f"**Jours testes** : {len(d)} (NQ live_enriched)")
    md.append(f"**Mode** : FULL REGLES (pas de ML)")
    md.append(f"**Approches** : A1 (Trend+OF+BigSpawn) / A2 (Wyckoff+VP+VWAP) / A3 (MultiTemp+Confluence)")
    md.append(f"**Fenetres** : {WINDOWS}")
    md.append(f"**Forwards** : {FORWARDS} bars (label)")
    md.append("")
    md.append("## Resultats TOP 20 (par |rho_mean| descending)")
    md.append("")
    md.append("| Feature | n_days | rho_mean | rho_median | |rho|_mean | % significant (|rho|>0.1) | % strong (|rho|>0.2) |")
    md.append("|---|---|---|---|---|---|---|")
    for _, r in summary_df.head(20).iterrows():
        md.append(f"| `{r.feature}` | {r.n_days} | {r.rho_mean} | {r.rho_median} | {r.rho_abs_mean} | {r.pct_significant}% | {r.pct_strong}% |")
    md.append("")
    md.append("## Best par approche")
    md.append("")
    md.append("| Approche | Best feature | rho_mean | % significant |")
    md.append("|---|---|---|---|")
    for app, r in top_by_approche.items():
        md.append(f"| {app} | `{r.feature}` | {r.rho_mean} | {r.pct_significant}% |")
    md.append("")
    md.append("## Verdict")
    md.append("")
    if not summary_df.empty:
        best = summary_df.iloc[0]
        if best.rho_abs_mean > 0.15:
            md.append(f"**L'ELUE** : `{best.feature}` (|rho| = {best.rho_abs_mean}, {best.pct_significant}% significant)")
            md.append("")
            md.append("→ SOLIDE pour deployer en gate Bot 2/3")
        elif best.rho_abs_mean > 0.1:
            md.append(f"**CANDIDATE** : `{best.feature}` (|rho| = {best.rho_abs_mean})")
            md.append("")
            md.append("→ MARGINAL, raffiner avec mix multi-features ou tester nouvelle approche")
        else:
            md.append(f"**FAIBLE** : meilleur = `{best.feature}` (|rho| = {best.rho_abs_mean})")
            md.append("")
            md.append("→ NOGO, design d'approche fondamentalement different requis")
    md.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport ecrit : {OUT} ===")


if __name__ == "__main__":
    main()
