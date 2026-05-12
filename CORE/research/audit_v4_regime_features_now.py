"""Audit features regime DANS le parquet V4 enriched ACTUEL (post-fix 02:30).

Verifie pour NQ + ES : 19 features regime requises par compute_regime sont-elles
presentes ET non-NaN dans la derniere barre du parquet ?
"""
import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Features regime requises par compute_regime (agent code-reviewer 12/05)
FEATURES_REGIME = [
    "ib_broken_up", "ib_broken_down", "ib_formed_bool", "ib_range_ticks",
    "day_type", "open_type", "single_print_count",
    "vwap_slope_10", "sess_range_atr", "profile_shape",
    "poc_bar_dist", "bars_in_va", "trend_day_probability",
    "range_pos", "delta_day_dir", "cvd_day_dir",
    "delta_divergence", "atr_regime_zscore_60d",
    "regime_actionable", "regime_favor", "regime_mode",
]

for sym in ["NQ", "ES"]:
    print(f"\n{'='*78}")
    print(f"  V4 ENRICHED — {sym}.c.0 mai 2026")
    print(f"{'='*78}")
    fp = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0" / "year=2026" / "month=05" / "data.parquet"
    if not fp.exists():
        print(f"  NOT FOUND: {fp}")
        continue
    df = pq.read_table(fp).to_pandas()
    print(f"  N bars: {len(df)}")
    print(f"  TS range: {df['ts_event'].min()} → {df['ts_event'].max()}")
    print(f"  Cols total: {len(df.columns)}")
    print()

    # Sample : derniere barre
    last_row = df.iloc[-1]
    print(f"  Derniere barre @ {last_row['ts_event']}:")
    print(f"  {'Feature':<35}{'Status':<10}{'Value'}")
    print(f"  {'-'*78}")
    for feat in FEATURES_REGIME:
        if feat not in df.columns:
            print(f"  {feat:<35}{'MISSING':<10}{'(colonne absente)'}")
        else:
            v = last_row[feat]
            if pd.isna(v):
                # Stats sur toute la colonne
                n_total = len(df)
                n_nan = df[feat].isna().sum()
                pct_nan = round(100 * n_nan / n_total, 1)
                print(f"  {feat:<35}{'NaN':<10}value=None  ({pct_nan}% NaN total)")
            else:
                # Stats si features partiel
                n_total = len(df)
                n_nan = df[feat].isna().sum()
                pct_nan = round(100 * n_nan / n_total, 1)
                if pct_nan > 0:
                    status = f"{pct_nan}% NaN"
                else:
                    status = "OK"
                if isinstance(v, float):
                    v_str = f"{v:.3f}"
                else:
                    v_str = str(v)
                print(f"  {feat:<35}{status:<10}value={v_str}")

    # Stats sur les 100 dernieres barres (rolling actuel)
    print(f"\n  === Stats 100 dernieres barres (live actuel) ===")
    last100 = df.tail(100)
    for feat in ["regime_actionable", "regime_favor", "regime_mode"]:
        if feat in df.columns:
            if feat == "regime_actionable":
                n_act = (last100[feat] == 1).sum() if feat in last100.columns else 0
                print(f"  {feat:<25} actionable=1 : {n_act}/100 = {n_act}%")
            else:
                vals = last100[feat].value_counts()
                print(f"  {feat:<25} distribution : {dict(vals)}")
