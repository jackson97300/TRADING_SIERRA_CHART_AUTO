"""
build_v5e_clean_with_long_ext.py — Phase 0 (Jackson 06/05 "PAS DE TRICHE").

Construit un dataset propre pour exploration label/edge :
1. Charge V5e (12 mois mai 2025-avril 2026, label v5 deja calcule, sample_weight Lopez)
2. Drop features polluees identifiees par quality_validator :
   - price leak (asia_high, ib_high, ovn_high, pdh, pdl, pvwap, etc. = ratio NQ/ES 3.7×)
   - volatility leak (dist_cur_vah, dist_cur_vpoc, dist_ib_high, dist_vwap_d = std ratio 4.8-5.4×)
3. Augmente avec LONG Extension Lines (n_long_up/dn_zones_active, dist_*, cluster) depuis
   V4 enrichi jan-avril 2026 (4 mois propres regenerated 06/05)
4. Subset chronologique : garde uniquement les bars couverts par V4 enrichi recent

Output : DATA/DATASETS/{ES,NQ}_dataset_v5e_clean_long.parquet

Usage : python -X utf8 CORE/research/build_v5e_clean_with_long_ext.py
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
DATASETS_DIR = ROOT / "DATA" / "DATASETS"
V4_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"

# Features polluees identifiees par quality_validator (drop pour ML-clean)
PRICE_LEAK_FEATURES = [
    "after_open", "asia_high", "asia_low", "asia_open",
    "cash_high", "cash_low",
    "ib_high", "ib_low",
    "london_high", "london_low", "london_open",
    "ny_open",
    "ovn_high", "ovn_low",
    "sess_high", "sess_low",
    "us_high", "us_low",
    "pdh", "pdl",
    "pvwap", "pvpoc", "pvah", "pval",
    "cur_vpoc", "cur_vah", "cur_val",
    "vwap_d", "vwap_w", "vwap_m",
    # SD bands non normalisees
    "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d_sd2u", "vwap_d_sd2d", "vwap_d_sd3u", "vwap_d_sd3d",
    "vwap_w_sd1u", "vwap_w_sd1d", "vwap_w_sd2u", "vwap_w_sd2d", "vwap_w_sd3u", "vwap_w_sd3d",
    "vwap_m_sd1u", "vwap_m_sd1d", "vwap_m_sd2u", "vwap_m_sd2d", "vwap_m_sd3u", "vwap_m_sd3d",
    "pvwap_sd1u", "pvwap_sd1d",
]

VOL_LEAK_FEATURES = [
    # std NQ/ES > 2.5× → utiliser variants _pct ou _atr
    "dist_cur_vah", "dist_cur_vpoc", "dist_cur_val",
    "dist_ib_high", "dist_ib_low",
    "dist_vwap_d", "dist_vwap_w", "dist_vwap_m",
    "dist_pdh", "dist_pdl",
    "dist_pvwap", "dist_pvpoc", "dist_pvah", "dist_pval",
    "dist_ovn_high", "dist_ovn_low",
    "dist_sess_high", "dist_sess_low",
    "dist_open_830", "dist_open_930",
    "dist_swing_high", "dist_swing_low",
]

TARGET_LEAK_FEATURES = [
    # CRITICAL : realized_pts + exit_offset sont les sorties Triple Barrier (TARGET)
    # cf build_dataset_v4_dmp_databento.py:427 "realized_pts = PnL Triple Barrier (TARGET)"
    # leak rho=+0.98 avec label confirme par audit foundation 06/05
    "realized_pts", "exit_offset",
    # Lopez triple barrier outputs additionnels
    "t1", "barrier_type", "daily_vol_at_entry",
    # === LEAKS detectes par audit ml-trainer 02/05 (cf train_v5_lightgbm.py:48-61) ===
    # _fwd1 = forward 1 bar = info futur structurelle
    "long_dn_up_fwd1", "long_up_dn_fwd1",
    "bn_color_up_fwd1", "bn_color_dn_fwd1",
    "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
    # lookahead news event
    "mins_to_next_news",
    # swing-based architectural leak (sessions_swings_engine.py:274-286 fenetre [i-10, i+10])
    "bars_since_last_swing_high", "bars_since_last_swing_low",
    "dist_last_swing_high_pct", "dist_last_swing_low_pct",
    "swing_high_active_lag10", "swing_low_active_lag10",
    "last_swing_high_session", "last_swing_low_session",
]

DROP_FEATURES = set(PRICE_LEAK_FEATURES + VOL_LEAK_FEATURES + TARGET_LEAK_FEATURES)

LONG_EXT_FEATURES = [
    "n_long_up_zones_active", "n_long_dn_zones_active",
    "dist_long_up_nearest_pct", "dist_long_dn_nearest_pct",
    "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
]


def load_v5e(symbol):
    fp = DATASETS_DIR / f"{symbol}_dataset_v5e.parquet"
    df = pd.read_parquet(fp)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    return df


def load_v4_long_ext(symbol):
    """Charge LONG Extension Lines depuis V4 enrichi jan-avril 2026 (4 mois propres)."""
    sym_root = V4_ROOT / f"symbol={symbol}.c.0" / "year=2026"
    months = sorted(p for p in sym_root.glob("month=0[1-4]") if p.is_dir())
    dfs = []
    for m in months:
        f = m / "data.parquet"
        if not f.exists():
            continue
        df_m = pd.read_parquet(f)
        # Garde uniquement ts_event + LONG Extension Lines
        cols_keep = ["ts_event"] + [c for c in LONG_EXT_FEATURES if c in df_m.columns]
        if len(cols_keep) <= 1:
            print(f"  WARNING : {m} pas de LONG Extension Lines")
            continue
        dfs.append(df_m[cols_keep].copy())
    if not dfs:
        return pd.DataFrame()
    out = pd.concat(dfs, ignore_index=True)
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True)
    return out


def build_clean_dataset(symbol):
    print(f"\n=== {symbol} ===")
    v5e = load_v5e(symbol)
    print(f"  V5e loaded : {v5e.shape}")

    # Drop features polluees
    drop_present = [c for c in DROP_FEATURES if c in v5e.columns]
    print(f"  Drop pollues : {len(drop_present)} features")
    v5e_clean = v5e.drop(columns=drop_present)
    print(f"  V5e clean : {v5e_clean.shape}")

    # Merge LONG Extension Lines depuis V4 jan-avril 2026
    v4_long = load_v4_long_ext(symbol)
    if v4_long.empty:
        print(f"  WARNING : aucune LONG Extension Lines trouvee dans V4 enrichi")
        out = v5e_clean
    else:
        print(f"  V4 LONG features : {v4_long.shape}")
        # Merge sur ts_event (left join sur V5e)
        out = v5e_clean.merge(v4_long, on="ts_event", how="left")
        # Verif coverage
        long_coverage = out[LONG_EXT_FEATURES[0]].notna().mean() * 100 if LONG_EXT_FEATURES[0] in out.columns else 0
        print(f"  LONG coverage post-merge : {long_coverage:.1f}%")

    # Output
    fp_out = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    out.to_parquet(fp_out, compression="snappy")
    print(f"  Saved : {fp_out} (shape={out.shape})")
    return out


def main():
    print("Phase 0 build : V5e clean + LONG Extension Lines")
    for sym in ["ES", "NQ"]:
        build_clean_dataset(sym)
    print("\nDone")


if __name__ == "__main__":
    main()
