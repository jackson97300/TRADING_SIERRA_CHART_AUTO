"""Backtest variantes feature trend_orderflow_alignment_20b sur 133 jours NQ.

Objectif :
- Tester plusieurs definitions de la feature
- Mesurer predictivite vs direction marche forward (J+1, J+5)
- Identifier la formule la plus pertinente pour anti-pattern "BUY sur mur PVAL en trend up"

Variantes :
- Direction tendance : T1 (price), T2 (vwap_slope), T3 (combo)
- Orderflow : O1 (delta_bar flat), O2 (delta_bar EMA), O3 (big_orders only)
- Threshold : TH1 0.5, TH2 1.0, TH3 2.0

Output : DOCS/TREND_ORDERFLOW_BACKTEST.md
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
OUT = ROOT / "DOCS" / "TREND_ORDERFLOW_BACKTEST.md"


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
    return df


def compute_alignment_variants(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule plusieurs variantes de trend_orderflow_alignment_20b."""
    # Numeric cast
    for col in ("close", "delta_bar", "atr", "vwap_slope_10",
                "n_big_ask_t1", "n_big_bid_t1"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- DIRECTIONS TENDANCE ---
    # T1 : price slope normalise par ATR daily
    if "close" in df.columns and "atr" in df.columns:
        df["T1_trend"] = (df["close"] - df["close"].shift(20)) / df["atr"]
    else:
        df["T1_trend"] = np.nan

    # T2 : vwap_slope_10 Sierra (slope 1h30) si dispo
    if "vwap_slope_10" in df.columns:
        df["T2_trend"] = df["vwap_slope_10"]
    else:
        df["T2_trend"] = np.nan

    # T3 : combo T1 + T2 (mean, only when both available)
    df["T3_trend"] = (df["T1_trend"] + df["T2_trend"]) / 2

    # --- ORDERFLOW CUMUL 20B ---
    # O1 : mean delta_bar flat 20b
    if "delta_bar" in df.columns:
        df["O1_of"] = df["delta_bar"].rolling(20, min_periods=10).mean()

    # O2 : EMA delta_bar span 20
    if "delta_bar" in df.columns:
        df["O2_of"] = df["delta_bar"].ewm(span=20, min_periods=10).mean()

    # O3 : big orders only (n_big_ask - n_big_bid) cumul 20b
    if "n_big_ask_t1" in df.columns and "n_big_bid_t1" in df.columns:
        df["O3_of"] = ((df["n_big_ask_t1"] - df["n_big_bid_t1"])
                       .rolling(20, min_periods=10).mean())

    # --- ALIGNMENT SCORES ---
    # Pour chaque T x O combinaison, calculer alignment continu
    # alignment = sign(T) * sign(O) * min(|T|, |O|) — score [-N..+N]
    for t_name in ("T1", "T2", "T3"):
        for o_name in ("O1", "O2", "O3"):
            t_col = f"{t_name}_trend"
            o_col = f"{o_name}_of"
            if t_col in df.columns and o_col in df.columns:
                t = df[t_col]
                o = df[o_col]
                # Sign alignment
                sign_align = np.sign(t) * np.sign(o)
                # Magnitude min
                mag = np.minimum(t.abs(), o.abs().fillna(0))
                df[f"align_{t_name}_{o_name}"] = sign_align * mag

    return df


def per_day_predictivity(df: pd.DataFrame) -> dict:
    """Mesure predictivite : alignment vs forward direction marche."""
    if df.empty or "close" not in df.columns:
        return None

    # Filtre RTH (9:30-16:00 ET = 570-960 mins)
    if "mins_et" in df.columns:
        rth = df[(df.mins_et >= 570) & (df.mins_et < 960)].copy()
    else:
        rth = df.copy()
    if len(rth) < 60:
        return None

    # Label : direction prochaines 5 minutes (forward 5 bars)
    rth["forward_5b"] = rth.close.shift(-5) - rth.close
    rth = rth.dropna(subset=["forward_5b"])

    out = {"n_bars": len(rth)}

    # Pour chaque variante alignment, Spearman vs forward
    for col in rth.columns:
        if not col.startswith("align_"): continue
        s = rth[col].dropna()
        if len(s) < 30: continue
        common = rth.dropna(subset=[col, "forward_5b"])
        if len(common) < 30: continue
        rho = common[col].rank().corr(common["forward_5b"].rank())
        out[f"rho_{col}"] = round(float(rho), 4)

    return out


def main():
    files = sorted(DATA_DIR.glob("*_NQ.jsonl"))[-100:]   # 100 derniers jours
    print(f"=== Backtest variantes trend_orderflow_alignment sur {len(files)} jours NQ ===\n")

    daily = []
    for i, fp in enumerate(files):
        try:
            df = load_day(fp)
            if df.empty: continue
            df = compute_alignment_variants(df)
            stats = per_day_predictivity(df)
            if stats:
                stats["day"] = fp.stem.split("_")[0]
                daily.append(stats)
        except Exception as e:
            pass
        if (i+1) % 20 == 0:
            print(f"  {i+1}/{len(files)} jours...")

    d = pd.DataFrame(daily)
    print(f"\nJours exploitables : {len(d)}")
    print(f"Bars RTH median : {d.n_bars.median():.0f}")

    # Aggregation : moyenne Spearman par variante
    rho_cols = [c for c in d.columns if c.startswith("rho_align_")]
    summary = []
    for c in rho_cols:
        s = d[c].dropna()
        if len(s) < 10: continue
        variant = c.replace("rho_align_", "")
        summary.append({
            "variant": variant,
            "n_days": len(s),
            "rho_mean": round(float(s.mean()), 4),
            "rho_median": round(float(s.median()), 4),
            "rho_p25": round(float(s.quantile(0.25)), 4),
            "rho_p75": round(float(s.quantile(0.75)), 4),
            "rho_min": round(float(s.min()), 4),
            "rho_max": round(float(s.max()), 4),
            "pct_positive": round(100 * (s > 0).sum() / len(s), 1),
            "pct_significant": round(100 * (s.abs() > 0.1).sum() / len(s), 1),
        })

    summary_df = pd.DataFrame(summary)
    summary_df = summary_df.sort_values("rho_mean", ascending=False)

    print("\n=== TOP 9 variantes par rho_mean ===")
    print(summary_df.to_string(index=False))

    # Rapport markdown
    md = []
    md.append("# Backtest variantes trend_orderflow_alignment_20b")
    md.append("")
    md.append(f"**Date** : 2026-06-07")
    md.append(f"**Symbole** : NQ")
    md.append(f"**Jours testes** : {len(d)} (live_enriched)")
    md.append(f"**Bars RTH median** : {d.n_bars.median():.0f}")
    md.append(f"**Label** : direction forward 5 bars (close[t+5] - close[t])")
    md.append("")
    md.append("## Variantes testees")
    md.append("")
    md.append("**Direction tendance** :")
    md.append("- T1 : `(close - close[-20]) / atr_daily` — pur prix normalise ATR")
    md.append("- T2 : `vwap_slope_10` Sierra (slope 1h30)")
    md.append("- T3 : `(T1 + T2) / 2` — combo")
    md.append("")
    md.append("**Orderflow cumul 20b** :")
    md.append("- O1 : `mean(delta_bar[-20:])` flat")
    md.append("- O2 : `EMA(delta_bar, span=20)` exponentiel")
    md.append("- O3 : `(n_big_ask_t1 - n_big_bid_t1).rolling(20).mean()` BIG only")
    md.append("")
    md.append("**Alignment score continu** :")
    md.append("- `align_TX_OY = sign(T) * sign(O) * min(|T|, |O|)`")
    md.append("")
    md.append("## Resultats — Spearman vs forward 5b (sorte par rho_mean desc)")
    md.append("")
    md.append("| Variant | n_days | rho_mean | rho_median | rho_p25 | rho_p75 | % positif | % significatif |")
    md.append("|---|---|---|---|---|---|---|---|")
    for _, r in summary_df.iterrows():
        md.append(f"| `align_{r.variant}` | {r.n_days} | {r.rho_mean} | {r.rho_median} | {r.rho_p25} | {r.rho_p75} | {r.pct_positive}% | {r.pct_significant}% |")
    md.append("")

    # Recommendation
    md.append("## Recommandation feature `trend_orderflow_alignment_20b`")
    md.append("")
    best = summary_df.iloc[0]
    md.append(f"**Variante GAGNANTE** : `align_{best.variant}` (rho_mean = {best.rho_mean})")
    md.append("")
    md.append(f"- Stabilite : {best.pct_significant}% des jours ont |rho| > 0.1")
    md.append(f"- Robustesse : {best.pct_positive}% des jours ont signe correct")
    md.append("")
    md.append("Formule recommandee :")
    md.append("```python")
    t, o = best.variant.split("_")
    if t == "T1":
        md.append("trend = (close[t] - close[t-20]) / atr_daily")
    elif t == "T2":
        md.append("trend = vwap_slope_10   # Sierra natif (slope 1h30)")
    elif t == "T3":
        md.append("trend = (price_slope_20 + vwap_slope_10) / 2")
    if o == "O1":
        md.append("orderflow = mean(delta_bar[-20:])")
    elif o == "O2":
        md.append("orderflow = EMA(delta_bar, span=20)")
    elif o == "O3":
        md.append("orderflow = mean(n_big_ask_t1[-20:] - n_big_bid_t1[-20:])")
    md.append("alignment = sign(trend) * sign(orderflow) * min(|trend|, |orderflow|)")
    md.append("```")
    md.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport ecrit : {OUT} ===")


if __name__ == "__main__":
    main()
