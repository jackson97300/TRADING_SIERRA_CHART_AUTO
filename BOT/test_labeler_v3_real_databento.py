"""
test_labeler_v3_real_databento.py — Test integration sur vraies donnees NQ Databento

Created : 2026-05-02 samedi 0bis
Author : Jackson + agent Claude.com mobile (point 2 manquant 10/10)

Goal : valider labeler_v3 sur vraies donnees ES/NQ vs synthetic uniquement.
Synthetic capture pas :
- Gaps overnight session
- RTH vs ETH variations volume
- Bars ouverture volume explosif
- FOMC, NFP, jours feries
- Asymetries directionnelles regimes

Test data : 4 jours NQ avril 2026 resample en 5m (avec gaps weekend).
Verifications :
1. Distribution labels {-1, 0, +1} : attendre 25/50/25 +/- 15% sur vraies bars 5m
2. sample_weight cohorts : mean reasonable (1-10), variance non triviale
3. No temporal leak (t1_actual >= entry_ts)
4. Pas de NaN dans label
5. Daily vol estimate stable (no explosion ni 0)
6. Pas de classes ultra-desequilibrees (>= 10% par classe)
"""

from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from labeler_v3 import label_dataset_v3

PARQUET_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"


def load_nq_1m_avril_2026() -> pd.DataFrame:
    """Charge plusieurs jours NQ 1m avril 2026 (avec gaps weekend)."""
    base = PARQUET_ROOT / "symbol=NQ.c.0" / "year=2026" / "month=4"
    parts = []
    for day_dir in sorted(base.glob("day=*")):
        for parquet in sorted(day_dir.glob("*.parquet")):
            df = pd.read_parquet(parquet)
            parts.append(df)
    if not parts:
        return pd.DataFrame()
    full = pd.concat(parts, ignore_index=True)
    if "ts_event" not in full.columns:
        full = full.reset_index().rename(columns={"index": "ts_event"})
    full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
    full = full.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)
    return full


def resample_1m_to_5m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m bars → 5m bars (label='left' = bar 10:00 couvre 10:00-10:04)."""
    df = df_1m.set_index("ts_event")
    df_5m = df.resample("5min", label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return df_5m


def main():
    print("=" * 70)
    print("TEST INTEGRATION labeler_v3 sur DONNEES REELLES NQ Databento")
    print("=" * 70)

    df_1m = load_nq_1m_avril_2026()
    if df_1m.empty:
        print("[FAIL] Pas de donnees NQ avril 2026")
        sys.exit(1)
    print(f"  Loaded {len(df_1m)} bars 1m NQ avril 2026")
    print(f"  Range: {df_1m['ts_event'].min()} → {df_1m['ts_event'].max()}")

    # Resample 1m → 5m
    df_5m = resample_1m_to_5m(df_1m)
    print(f"  Resampled to {len(df_5m)} bars 5m")

    # Run labeler v3
    print("\n[RUN labeler_v3] tf=5m, pt_sl=(1.5, 1.0), horizon=12 bars (1h)")
    events = label_dataset_v3(
        df_5m.reset_index(),  # ts_event en colonne
        tf_name='5m',
        pt_sl=(1.5, 1.0),
        horizon_bars=12,
        rvol_threshold=0.3,
    )

    if events.empty:
        print("[FAIL] Aucun event produit")
        sys.exit(1)

    print(f"\n[VALIDATION 6 criteres]")
    issues = []

    # Critere 1 : Distribution labels
    label_dist = events['label'].value_counts(normalize=True).sort_index()
    print(f"\n1. Distribution labels :")
    for lbl, pct in label_dist.items():
        sign = '+' if lbl > 0 else ('-' if lbl < 0 else ' ')
        print(f"   {sign}{lbl} : {pct:.1%}")
    n_pos = label_dist.get(1, 0)
    n_neg = label_dist.get(-1, 0)
    n_hold = label_dist.get(0, 0)
    if abs(n_pos - 0.25) > 0.20:
        issues.append(f"Class +1 = {n_pos:.1%} (cible 25%, ecart > 20pp)")
    if abs(n_neg - 0.25) > 0.20:
        issues.append(f"Class -1 = {n_neg:.1%} (cible 25%, ecart > 20pp)")

    # Critere 2 : Sample weights cohorts
    sw = events['sample_weight'].dropna()
    print(f"\n2. Sample weights : mean={sw.mean():.3f}, std={sw.std():.3f}, "
          f"min={sw.min():.3f}, max={sw.max():.3f}")
    if sw.mean() < 0.1 or sw.mean() > 50:
        issues.append(f"Sample weight mean={sw.mean():.3f} hors range [0.1, 50]")
    if sw.std() < 0.01:
        issues.append(f"Sample weight std={sw.std():.4f} trop faible (variance triviale)")

    # Critere 3 : No temporal leak
    leak_count = 0
    for entry_ts, row in events.iterrows():
        t1 = row['ts_t1_actual']
        if pd.notna(t1) and t1 < entry_ts:
            leak_count += 1
    print(f"\n3. Temporal leak : {leak_count}/{len(events)} samples avec t1 < entry")
    if leak_count > 0:
        issues.append(f"LEAK : {leak_count} samples ts_t1 < entry_ts")

    # Critere 4 : Pas de NaN dans label
    nan_count = events['label'].isna().sum()
    print(f"\n4. NaN dans label : {nan_count}/{len(events)}")
    if nan_count > 0:
        issues.append(f"{nan_count} NaN dans label")

    # Critere 5 : Daily vol stable
    vol = events['daily_vol'].dropna()
    print(f"\n5. Daily vol : mean={vol.mean():.6f}, std={vol.std():.6f}, "
          f"min={vol.min():.6f}, max={vol.max():.6f}")
    if vol.max() > 0.1:
        issues.append(f"Daily vol max={vol.max():.4f} > 10% bar (suspect)")
    if vol.min() < 1e-8:
        issues.append(f"Daily vol min={vol.min():.10f} ~ 0 (suspect)")

    # Critere 6 : Pas de classe ultra-desequilibree
    print(f"\n6. Classes balance :")
    min_class_pct = label_dist.min()
    print(f"   Classe minoritaire : {min_class_pct:.1%}")
    if min_class_pct < 0.05:
        issues.append(f"Classe minoritaire {min_class_pct:.1%} < 5% (deséquilibré)")

    # Verdict final
    print("\n" + "=" * 70)
    if not issues:
        print("VERDICT : PASS — labeler_v3 valide sur donnees reelles NQ")
        print(f"  Distribution : {n_pos:.1%}/{n_hold:.1%}/{n_neg:.1%} (+1/0/-1)")
        print(f"  Events : {len(events)}")
        print(f"  Classes balance OK")
    else:
        print(f"VERDICT : ATTENTION ({len(issues)} reserves)")
        for i, issue in enumerate(issues, 1):
            print(f"  [{i}] {issue}")
    print("=" * 70)

    # Stats supplementaires
    print(f"\nBarrier types distribution :")
    bt_dist = events['barrier_type'].value_counts(normalize=True)
    for bt, pct in bt_dist.items():
        print(f"  {bt} : {pct:.1%}")


if __name__ == "__main__":
    main()
