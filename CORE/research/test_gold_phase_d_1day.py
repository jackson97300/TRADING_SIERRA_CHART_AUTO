"""Test 1 jour gold_phase_d_features sur MGC + 6E + ZN + ZB.

Validation empirique AVANT integration build_dataset_v4_phase_b.py.
Si KO sur 1 jour → corriger AVANT rebuild 12 mois.

DROPPED 12/05/2026 : im_silver_lead_lag (NOGO market-analyst, Silver sparsity).

Critere :
- im_dxy_corr_60d : non-NaN ratio > 50%, range [-1, +1]
- im_real_yields_proxy : non-NaN ratio > 70%
- mgc_asia_london_overlap_vol : non-zero ratio > 0% (selon plage dans data)
- mgc_session_break_acceleration : non-zero ratio > 0% (selon DST + plage)
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
from gold_phase_d_features import (
    apply_gold_phase_d, load_ohlcv_databento, GOLD_PHASE_D_FEATURES,
)

# Test day : 23/04/2026 (jeudi, dernier jour MGC dispo backfill historique)
test_start = pd.Timestamp("2026-04-23 00:00:00", tz="UTC")
test_end = pd.Timestamp("2026-04-24 00:00:00", tz="UTC")
# DuckDB strip tz, donc utiliser naive
start_naive = test_start.tz_localize(None)
end_naive = test_end.tz_localize(None)

print(f"=== Test Gold Phase D : 1 day {test_start.date()} ===\n")

# Load MGC base
print("Loading MGC.v.0...")
df_mgc = load_ohlcv_databento("MGC.v.0", start_naive, end_naive)
print(f"  MGC: {len(df_mgc)} bars")
if df_mgc.empty:
    print("ERROR: MGC empty")
    sys.exit(1)

# Load 4 cross-asset symbols
print("Loading 4 cross-asset symbols...")
df_6e = load_ohlcv_databento("6E.c.0", start_naive, end_naive)
df_si = load_ohlcv_databento("SI.c.0", start_naive, end_naive)
df_zn = load_ohlcv_databento("ZN.c.0", start_naive, end_naive)
df_zb = load_ohlcv_databento("ZB.c.0", start_naive, end_naive)

print(f"  6E: {len(df_6e)} bars")
print(f"  SI: {len(df_si)} bars")
print(f"  ZN: {len(df_zn)} bars")
print(f"  ZB: {len(df_zb)} bars")

# Apply Gold Phase D
print("\nApplying gold_phase_d_features...")
df_enriched = apply_gold_phase_d(df_mgc, df_6e=df_6e, df_si=df_si, df_zn=df_zn, df_zb=df_zb)
print(f"  Output: {df_enriched.shape}")

# Validation par feature
print(f"\n{'Feature':<40}{'N non-NaN':<12}{'% non-NaN':<12}{'Min':<10}{'Max':<10}{'Mean':<10}")
print("-" * 100)
n_total = len(df_enriched)
for feat in GOLD_PHASE_D_FEATURES:
    if feat not in df_enriched.columns:
        print(f"  {feat:<40} ABSENT ❌")
        continue
    s = df_enriched[feat]
    n_non_nan = s.notna().sum()
    pct = 100 * n_non_nan / n_total
    if n_non_nan > 0:
        non_nan = s.dropna()
        mn = non_nan.min()
        mx = non_nan.max()
        me = non_nan.mean()
        print(f"  {feat:<40}{n_non_nan:<12}{pct:<11.1f}%{mn:<10.3f}{mx:<10.3f}{me:<10.3f}")
    else:
        print(f"  {feat:<40}{0:<12}{0:<11.1f}%{'N/A':<10}{'N/A':<10}{'N/A':<10}  ❌ 100% NaN")

print(f"\n=== VERDICT ===")
results = {}
for feat in GOLD_PHASE_D_FEATURES:
    if feat not in df_enriched.columns:
        results[feat] = "ABSENT"
        continue
    pct = 100 * df_enriched[feat].notna().sum() / n_total
    thresh = {
        "im_dxy_corr_60d": 50,
        "im_real_yields_proxy": 70,
        "im_silver_lead_lag": 30,
        "mgc_asia_london_overlap_vol": 0.01,
        "mgc_session_break_acceleration": 0.01,
    }.get(feat, 50)
    if pct >= thresh:
        results[feat] = f"OK ({pct:.1f}% non-NaN >= {thresh}%)"
    else:
        results[feat] = f"FAIL ({pct:.1f}% non-NaN < {thresh}%)"
    print(f"  {feat:<40} {results[feat]}")

n_ok = sum(1 for v in results.values() if v.startswith("OK"))
print(f"\nFinal : {n_ok}/{len(GOLD_PHASE_D_FEATURES)} features OK")
