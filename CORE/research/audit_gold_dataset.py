"""Audit fiabilite dataset MGC V5e clean (12 mois)."""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
df = pd.read_parquet(ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_clean.parquet")

print("=" * 70)
print("AUDIT FIABILITE - MGC_dataset_v5e_clean.parquet")
print("=" * 70)
print(f"\nShape: {df.shape}")

# ========== 1. Timestamps ==========
print("\n[1] TIMESTAMPS")
ts = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
print(f"  Range: {ts.min()} -> {ts.max()}")
print(f"  Span: {(ts.max()-ts.min()).days} jours")
print(f"  NaT count: {ts.isna().sum()}")
# Gaps detection
ts_sorted = ts.sort_values().reset_index(drop=True)
diffs = ts_sorted.diff().dt.total_seconds()
gaps = diffs[diffs > 120]  # > 2 min gaps
print(f"  Gaps > 2min: {len(gaps)}")
if len(gaps) > 0:
    print(f"    Max gap: {gaps.max()/60:.1f} min")
    print(f"    Mean gap: {gaps.mean()/60:.1f} min")
    print(f"    Top 5 gaps:")
    for idx, sec in gaps.nlargest(5).items():
        print(f"      idx={idx} ts={ts_sorted.iloc[idx]} gap={sec/60:.1f}min")

# ========== 2. Prix coherence ==========
print("\n[2] PRIX COHERENCE")
for col in ["open", "high", "low", "close"]:
    if col in df.columns:
        print(f"  {col}: min={df[col].min():.2f} max={df[col].max():.2f} mean={df[col].mean():.2f}")

# Vérifier prix OHLC coherent (high >= max(open,close), low <= min(open,close))
mask_bad_high = df["high"] < df[["open", "close"]].max(axis=1)
mask_bad_low = df["low"] > df[["open", "close"]].min(axis=1)
print(f"  Bars avec high < max(open,close): {mask_bad_high.sum()}")
print(f"  Bars avec low > min(open,close): {mask_bad_low.sum()}")

# Jumps anormaux (close to next close > 5% en 1 min = anomalie Gold)
ret_pct = df["close"].pct_change().abs() * 100
big_jumps = ret_pct[ret_pct > 5]
print(f"  Jumps > 5% intraday 1-min: {len(big_jumps)} (anormal Gold)")
if len(big_jumps) > 0:
    print(f"    Max jump: {big_jumps.max():.2f}%")
    print(f"    Top 5 jumps:")
    for idx, j in big_jumps.nlargest(5).items():
        print(f"      idx={idx} ts={df['ts_event'].iloc[idx]} jump={j:.2f}% close={df['close'].iloc[idx]:.2f}")

# ========== 3. Volume + ATR coherence ==========
print("\n[3] VOLUME + ATR")
if "volume" in df.columns:
    print(f"  volume: min={df['volume'].min()} max={df['volume'].max()} median={df['volume'].median():.0f}")
    print(f"  Bars vol=0: {(df['volume']==0).sum()} ({(df['volume']==0).sum()/len(df)*100:.1f}%)")
if "atr" in df.columns:
    print(f"  atr (per-bar ticks): median={df['atr'].median():.1f} p25={df['atr'].quantile(0.25):.1f} p99={df['atr'].quantile(0.99):.1f}")
    print(f"  atr NaN: {df['atr'].isna().sum()} ({df['atr'].isna().sum()/len(df)*100:.1f}%)")
if "rvol" in df.columns:
    print(f"  rvol: median={df['rvol'].median():.2f} p99={df['rvol'].quantile(0.99):.2f} max={df['rvol'].max():.2f}")

# ========== 4. NaN par feature critique ==========
print("\n[4] NaN PAR FEATURE CRITIQUE")
critical = [
    "open","high","low","close","volume","atr","rvol",
    "is_in_us_cash","is_in_us_after","is_in_london","is_in_asia",
    "dist_single_print_nearest_pct","dist_ib_low_pct","dist_cur_vpoc_pct",
    "dist_vwap_w_sd1d_pct","dist_open_830_pct","dist_open_930_pct",
    "dist_last_swing_high_pct","dist_last_swing_low_pct",
]
for c in critical:
    if c in df.columns:
        nan_pct = df[c].isna().sum()/len(df)*100
        marker = "OK" if nan_pct < 5 else "WARN" if nan_pct < 50 else "BAD"
        print(f"  [{marker:4s}] {c:50s} NaN={nan_pct:5.1f}%")
    else:
        print(f"  [ABS ] {c:50s} ABSENT")

# ========== 5. Phase D Gold features ==========
print("\n[5] PHASE D GOLD FEATURES (gold_phase_d_features.py)")
phase_d = ["im_dxy_corr_60d","im_real_yields_proxy","mgc_asia_london_overlap_vol","mgc_session_break_acceleration"]
for c in phase_d:
    if c in df.columns:
        nan_pct = df[c].isna().sum()/len(df)*100
        print(f"  [PRESENT] {c}: NaN={nan_pct:.1f}%")
    else:
        print(f"  [ABSENT ] {c}")

# ========== 6. MenthorQ Gold ==========
print("\n[6] MENTHORQ GOLD LEVELS")
mq_levels = [
    "dist_mq_call_pct","dist_mq_put_pct","dist_mq_hvl_pct",
    "dist_mq_call_0dte_pct","dist_mq_put_0dte_pct","dist_mq_hvl_0dte_pct",
    "dist_gex_nearest_up_pct","dist_gex_nearest_dn_pct",
]
for c in mq_levels:
    if c in df.columns:
        nan_pct = df[c].isna().sum()/len(df)*100
        print(f"  [PRESENT] {c}: NaN={nan_pct:.1f}%")
    else:
        print(f"  [ABSENT ] {c}")

# ========== 7. Distribution journalière (bars/jour) ==========
print("\n[7] DISTRIBUTION JOURNALIERE")
df["_date"] = ts.dt.date
bars_per_day = df.groupby("_date").size()
print(f"  Jours uniques: {len(bars_per_day)}")
print(f"  Bars/jour median: {bars_per_day.median():.0f}")
print(f"  Bars/jour min: {bars_per_day.min()} (jour: {bars_per_day.idxmin()})")
print(f"  Bars/jour max: {bars_per_day.max()} (jour: {bars_per_day.idxmax()})")
# Jours avec < 100 bars (potentiellement weekends, holidays, ou data gap)
low_days = bars_per_day[bars_per_day < 100]
print(f"  Jours avec < 100 bars: {len(low_days)} (probables weekends/holidays)")

# ========== 8. Sessions coverage ==========
print("\n[8] SESSIONS COVERAGE")
for c in ["is_in_us_cash","is_in_us_after","is_in_london","is_in_asia"]:
    if c in df.columns:
        pct = (df[c]==1).sum()/len(df)*100
        print(f"  {c}: {pct:.1f}%")

print("\n" + "=" * 70)
print("AUDIT TERMINE")
print("=" * 70)
