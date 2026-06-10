"""
Scan Spearman des features V4 vs PROXY range/trend construit empirique.

trend_day_probability etant NaN sur ce parquet, on construit un label proxy:
  label_range = 1 si bar_close 60 min plus tard reste dans [open-N*ATR, open+N*ATR]
  label_range = 0 si breakout franc

Methodo:
  - lookback 60 bars (1 heure 1min)
  - range_threshold = 1.5 * atr_14m (en points)
  - tendance = max(close[t:t+60]) - min(close[t:t+60]) >= range_threshold
              ET |close[t+60] - close[t]| >= 0.8 * range
  - sinon range
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PARQUET_PATH = ROOT / "DATA" / "PAPER_TRADES_V6_AUDIT" / "nq_mai_v4_fresh.parquet"

EXCLUDE_PREFIXES = (
    "ts_", "ts", "symbol", "year", "month", "day_id",
)
EXCLUDE_PRICE_COLS = {
    "open", "high", "low", "close", "bar_open", "bar_close", "bar_high", "bar_low",
    "avg_price", "vwap_d", "vwap_w", "vwap_m",
    "asia_high", "asia_low", "ovn_high", "ovn_low", "ib_high", "ib_low",
    "sess_high", "sess_low", "after_high", "after_low",
    "ny_open", "london_open", "open_930_et", "open_830_et",
    "_last_swing_high_price", "_last_swing_low_price",
    "ust_max", "ust_min", "ust_high", "ust_low",
}
EXCLUDE_EXACT = {
    "trend_day_probability", "label_range", "label_trend",
    "id", "bar_id", "session_id", "rth_session_id", "session_date",
    "open_type_code", "day_type_code", "profile_shape_code",
    "ret_fwd_60m", "range_fwd_60m", "trend_score_fwd",  # construits par nous
}


def is_numeric_feature(col: str, dtype) -> bool:
    if col in EXCLUDE_EXACT:
        return False
    if col in EXCLUDE_PRICE_COLS:
        return False
    if col.startswith(EXCLUDE_PREFIXES):
        return False
    if not pd.api.types.is_numeric_dtype(dtype):
        return False
    return True


def build_label_trend(df: pd.DataFrame, lookforward: int = 60) -> pd.Series:
    """
    trend_score in [0, 1]:
      - 1.0 = trend pur (directional move >= range)
      - 0.0 = range parfait (close oscille autour open)
    """
    # close column priority
    if "close" in df.columns:
        close = pd.to_numeric(df["close"], errors="coerce")
    elif "bar_close" in df.columns:
        close = pd.to_numeric(df["bar_close"], errors="coerce")
    else:
        close = pd.to_numeric(df["avg_price"], errors="coerce")
    # ATR en points (atr_14m_pct = en pct du prix; sinon fallback)
    if "atr_14m_pct" in df.columns:
        atr_pct = pd.to_numeric(df["atr_14m_pct"], errors="coerce")
        atr_pts = atr_pct / 100.0 * close
    elif "atr_14m" in df.columns:
        atr_pts = pd.to_numeric(df["atr_14m"], errors="coerce")
    else:
        # rough fallback: rolling std of close * 1.5
        atr_pts = close.diff().abs().rolling(14).mean()

    # max/min sur les 60 prochaines barres
    fwd_max = close.shift(-1).rolling(lookforward, min_periods=20).max().shift(-lookforward + 1)
    fwd_min = close.shift(-1).rolling(lookforward, min_periods=20).min().shift(-lookforward + 1)
    fwd_close = close.shift(-lookforward)

    rng_pts = (fwd_max - fwd_min).abs()
    move_pts = (fwd_close - close).abs()

    # directional ratio: si move/rng proche 1, trend; si 0, range
    directional = move_pts / rng_pts.replace(0, np.nan)
    # range absolu en ATR
    rng_atr = rng_pts / atr_pts.replace(0, np.nan)

    # trend_score: combine directional + range_atr (faible si pas de mouvement)
    # trend pur = directional high ET rng_atr >= 1.5
    # range pur = directional low OR rng_atr < 1.0
    trend_score = directional.clip(0, 1)
    # penaliser si pas assez de mouvement pour qualifier
    weak_move_mask = rng_atr < 1.0
    trend_score = trend_score.where(~weak_move_mask, trend_score * 0.5)

    return trend_score


def main() -> int:
    if not PARQUET_PATH.exists():
        print(f"FATAL: {PARQUET_PATH} introuvable")
        return 1

    print(f"[1/5] Chargement {PARQUET_PATH.name}...")
    df = pd.read_parquet(PARQUET_PATH)
    print(f"  shape = {df.shape}")

    print("[2/5] Construction label trend_score_fwd_60m (proxy)...")
    df = df.sort_values("ts_utc" if "ts_utc" in df.columns else df.columns[0]).reset_index(drop=True)
    df["trend_score_fwd_60m"] = build_label_trend(df, lookforward=60)
    target = df["trend_score_fwd_60m"]
    valid = target.notna() & np.isfinite(target)
    print(f"  valid = {valid.sum()}/{len(df)} ({valid.mean():.1%})")
    print(f"  distrib: q05={target.quantile(0.05):.3f} med={target.median():.3f} "
          f"q95={target.quantile(0.95):.3f}")

    print("[3/5] Scan features...")
    candidates = [c for c in df.columns if is_numeric_feature(c, df[c].dtype)]
    print(f"  candidates = {len(candidates)}")

    print("[4/5] Spearman corr...")
    results = []
    for col in candidates:
        ser = pd.to_numeric(df[col], errors="coerce")
        mask = valid & ser.notna() & np.isfinite(ser)
        if mask.sum() < 500:
            continue
        if ser[mask].std() < 1e-9:
            continue
        try:
            rho, pval = spearmanr(ser[mask], target[mask])
        except Exception:
            continue
        if not np.isfinite(rho):
            continue
        results.append((col, float(rho), float(pval), int(mask.sum())))

    res_df = pd.DataFrame(results, columns=["feature", "rho", "pval", "n"])
    res_df["abs_rho"] = res_df["rho"].abs()
    res_df = res_df.sort_values("rho")
    print(f"  scored = {len(res_df)}")

    print("\n[5/5] TOP 30 NEGATIVES (rho<0 = MONTENT en RANGE):")
    print("-" * 95)
    for _, row in res_df.head(30).iterrows():
        marker = "**" if row["abs_rho"] > 0.10 else "  "
        print(f"  {marker} {row['rho']:+.4f}  p={row['pval']:.1e}  n={row['n']:5d}  {row['feature']}")

    print("\nTOP 30 POSITIVES (rho>0 = MONTENT en TREND):")
    print("-" * 95)
    for _, row in res_df.tail(30).iloc[::-1].iterrows():
        marker = "**" if row["abs_rho"] > 0.10 else "  "
        print(f"  {marker} {row['rho']:+.4f}  p={row['pval']:.1e}  n={row['n']:5d}  {row['feature']}")

    out = ROOT / "DATA" / "research" / "range_scan_v4_NQ_mai.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    res_df.sort_values("abs_rho", ascending=False).to_csv(out, index=False)
    print(f"\nSauvegarde: {out}")

    # Diagnostic range features directes
    print("\n=== DIAGNOSTIC 14 RANGE FEATURES DIRECTES ===")
    range_feats = [
        "bar_range_pct", "ib_range_atr", "pct_in_range", "position_in_range",
        "ctx_va_width_atr", "ctx_va_developing_10_atr", "trend_score_fwd_60m",
    ]
    present = [f for f in range_feats if f in df.columns]
    sub = df[present].apply(pd.to_numeric, errors="coerce")
    print(sub.corr(method="spearman").round(3))

    return 0


if __name__ == "__main__":
    sys.exit(main())
