"""Test empirique features ctx_trend_day_score + ctx_day_type_intensity sur 133 jours.

Critere GO :
- Spearman direction marche j vs mean(ctx_*) > 0.20 absolu
- Stabilite sur 4 sous-periodes
- Distribution non-degeneree (pas de bucket > 80%)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "DATA" / "live_enriched" / "NQ"


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


def per_day_stats(df: pd.DataFrame) -> dict:
    """Stats journalieres : mean ctx features RTH + direction marche du jour."""
    if df.empty: return None
    rth = df[(df.mins_et >= 570) & (df.mins_et < 960)] if "mins_et" in df.columns else df
    if len(rth) < 60: return None

    for col in ("ctx_trend_day_score", "ctx_day_type_intensity", "close", "atr"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if col in rth.columns:
            rth[col] = pd.to_numeric(rth[col], errors="coerce")

    out = {}
    out["n_bars_rth"] = len(rth)
    out["close_open"] = rth.close.iloc[-1] - rth.close.iloc[0] if "close" in rth.columns else np.nan
    out["atr"] = rth.atr.iloc[-1] if "atr" in rth.columns else np.nan
    out["direction_atr"] = out["close_open"] / out["atr"] if out["atr"] else np.nan

    # ctx_trend_day_score : mean + max + last RTH
    if "ctx_trend_day_score" in rth.columns:
        s = rth.ctx_trend_day_score.dropna()
        out["tds_mean"] = s.mean()
        out["tds_max"] = s.max()
        out["tds_last"] = s.iloc[-1] if len(s) else np.nan
    # ctx_day_type_intensity : mean + abs mean + last
    if "ctx_day_type_intensity" in rth.columns:
        s = rth.ctx_day_type_intensity.dropna()
        out["dti_mean"] = s.mean()
        out["dti_abs_mean"] = s.abs().mean()
        out["dti_last"] = s.iloc[-1] if len(s) else np.nan
    return out


def main():
    files = sorted(DATA_DIR.glob("*_NQ.jsonl"))[-133:]
    print(f"=== Test empirique ctx_* sur {len(files)} jours NQ ===\n")

    daily = []
    for fp in files:
        try:
            df = load_day(fp)
            stats = per_day_stats(df)
            if stats:
                stats["day"] = fp.stem.split("_")[0]
                daily.append(stats)
        except Exception as e:
            pass

    d = pd.DataFrame(daily)
    print(f"Jours exploitables : {len(d)}")
    print(f"Bars RTH median : {d.n_bars_rth.median():.0f}")
    print()

    # Distributions
    print("=== DISTRIBUTIONS ===")
    for col in ("tds_mean", "tds_max", "tds_last", "dti_mean", "dti_abs_mean", "dti_last"):
        if col in d.columns:
            s = d[col].dropna()
            print(f"  {col:18}: n={len(s):3d} min={s.min():+.3f} p25={s.quantile(.25):+.3f} med={s.median():+.3f} p75={s.quantile(.75):+.3f} max={s.max():+.3f}")
    print()

    # Predictivite : Spearman vs direction
    print("=== PREDICTIVITE Spearman (vs direction_atr) ===")
    direction = d.direction_atr.dropna()
    print(f"  direction_atr range = [{direction.min():.2f}, {direction.max():.2f}], med={direction.median():.2f}")
    print()
    for col in ("tds_mean", "tds_max", "tds_last", "dti_mean", "dti_abs_mean", "dti_last"):
        if col in d.columns:
            common = d.dropna(subset=[col, "direction_atr"])
            if len(common) > 10:
                rho = common[col].rank().corr(common.direction_atr.rank())
                interp = "PREDICTIF" if abs(rho) > 0.20 else ("MARGINAL" if abs(rho) > 0.10 else "FAIBLE")
                print(f"  {col:18} : rho={rho:+.4f}  [{interp}]")
    print()

    # Stabilite sur 4 sous-periodes
    print("=== STABILITE sur 4 sous-periodes ===")
    d_sorted = d.sort_values("day").reset_index(drop=True)
    n = len(d_sorted)
    quarter = n // 4
    print(f"  Q1 (n={quarter}, {d_sorted.day.iloc[0]} -> {d_sorted.day.iloc[quarter-1]})")
    print(f"  Q2 (n={quarter}, {d_sorted.day.iloc[quarter]} -> {d_sorted.day.iloc[2*quarter-1]})")
    print(f"  Q3 (n={quarter}, {d_sorted.day.iloc[2*quarter]} -> {d_sorted.day.iloc[3*quarter-1]})")
    print(f"  Q4 (n={n - 3*quarter}, {d_sorted.day.iloc[3*quarter]} -> {d_sorted.day.iloc[-1]})")
    print()
    for col in ("tds_mean", "dti_mean", "dti_abs_mean"):
        if col not in d_sorted.columns: continue
        print(f"  {col:18}:", end=" ")
        for q in range(4):
            lo = q * quarter
            hi = (q+1) * quarter if q < 3 else n
            sub = d_sorted.iloc[lo:hi].dropna(subset=[col, "direction_atr"])
            if len(sub) > 5:
                rho = sub[col].rank().corr(sub.direction_atr.rank())
                print(f"Q{q+1} rho={rho:+.3f} (n={len(sub)})", end="  ")
        print()

    # Verdict
    print()
    print("=== VERDICT GLOBAL ===")
    common = d.dropna(subset=["dti_mean", "direction_atr"])
    rho_dti = common.dti_mean.rank().corr(common.direction_atr.rank()) if len(common) > 10 else 0
    common = d.dropna(subset=["tds_mean", "direction_atr"])
    rho_tds = common.tds_mean.rank().corr(common.direction_atr.rank()) if len(common) > 10 else 0
    print(f"  ctx_day_type_intensity (mean RTH) Spearman = {rho_dti:+.3f}")
    print(f"  ctx_trend_day_score    (mean RTH) Spearman = {rho_tds:+.3f}")
    print()
    if abs(rho_dti) > 0.20 or abs(rho_tds) > 0.20:
        print("  GO : feature predictive significative -> remplacer day_type Dalton")
    elif abs(rho_dti) > 0.10 or abs(rho_tds) > 0.10:
        print("  MARGINAL : signal faible mais reel. Garder + amelioration possible")
    else:
        print("  FAIBLE : signal proche du bruit. Re-design necessaire (cf Plan agent V2)")


if __name__ == "__main__":
    main()
