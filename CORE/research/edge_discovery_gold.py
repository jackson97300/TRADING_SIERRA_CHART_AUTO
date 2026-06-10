"""
edge_discovery_gold.py — Edge discovery GOLD (MGC) selon PROMPT_CLAUDE_CODE_BOT3_GOLD.md

Adapté de edge_discovery_bot2.py pour MGC :
    - Source : MGC_dataset_v5e_mq_enriched.parquet (411 features, 4 mois jan-mai 2026)
    - Tick size 0.10 (vs 0.25 ES/NQ)
    - Tick value $1 (vs $0.50 NQ, $1.25 ES)
    - 38 niveaux (21 MP standard + 17 Gold-spécifiques London/Asia/MQ/Blind)
    - Feature groups étendus : GOLD_INTERMARKET, GOLD_SESSION
    - Setups Gold-spécifiques (Asia breakout, MQ Gold 0DTE, DXY decoupling)

Output : DOCS/EDGE_REPORT_GOLD_MGC.md + DOCS/EDGE_REPORT_GOLD_MGC_RTH.md

Usage :
    python -X utf8 CORE/research/edge_discovery_gold.py
    python -X utf8 CORE/research/edge_discovery_gold.py --rth-only --output DOCS/EDGE_REPORT_GOLD_MGC_RTH.md
"""

from __future__ import annotations
import glob
import argparse
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np


# ═══════════════════════════════════════════════════════════════════
# 1. CHARGEMENT DONNÉES PARQUET V4
# ═══════════════════════════════════════════════════════════════════

def load_v4_parquets(data_dir: str, symbol: str = "MGC") -> pd.DataFrame:
    """Charge le parquet MGC_dataset_v5e_mq_enriched.parquet (Gold monolithique).

    Pour MGC : utilise MGC_dataset_v5e_mq_enriched.parquet (4 mois jan-mai 2026,
    enrichi Phase D + MQ Gold via load_mq_levels + attach_mq_distances).
    Pour ES/NQ : utilise pipeline v4_enriched standard (Hive partitioned).
    """
    if symbol == "MGC":
        # Mode Gold : fichier monolithique
        mgc_path = Path("DATA/DATASETS/MGC_dataset_v5e_mq_enriched.parquet")
        if not mgc_path.exists():
            print(f"[ERREUR] {mgc_path} absent. Run build_mgc_mq_enriched.py d'abord.")
            return pd.DataFrame()
        print(f"[LOAD] {mgc_path}")
        df = pd.read_parquet(mgc_path)
    else:
        # Mode ES/NQ : Hive partitioned
        sym_full = f"{symbol}.c.0"
        patterns = [
            f"{data_dir}/symbol={sym_full}/**/data*.parquet",
            f"{data_dir}/symbol={sym_full}/**/*.parquet",
        ]
        files = []
        for p in patterns:
            files.extend(glob.glob(p, recursive=True))
        files = sorted(set(files))
        if not files:
            print(f"[ERREUR] Aucun parquet trouvé pour {symbol} dans {data_dir}")
            return pd.DataFrame()
        print(f"[LOAD] {len(files)} fichiers parquet pour {symbol}")
        parts = []
        for f in files:
            try:
                df = pd.read_parquet(f)
                parts.append(df)
            except Exception as e:
                print(f"  [WARN] Erreur lecture {f}: {e}")
        if not parts:
            return pd.DataFrame()
        df = pd.concat(parts, ignore_index=True)

    # Normalize timestamp (utc=True force coherent tz handling cross-files)
    if 'ts_event' in df.columns:
        df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True, errors='coerce')
        if df['ts_event'].dt.tz is not None:
            df['ts_event'] = df['ts_event'].dt.tz_convert(None)
        df = df.dropna(subset=['ts_event'])
    df = df.sort_values('ts_event').drop_duplicates('ts_event').reset_index(drop=True)

    # Session date
    if 'session_date' not in df.columns and 'session_date_trading' in df.columns:
        df['session_date'] = pd.to_datetime(df['session_date_trading']).dt.date
    elif 'session_date' not in df.columns:
        df['session_date'] = df['ts_event'].dt.date

    print(f"[LOAD] {len(df)} barres, {df['session_date'].nunique()} jours, {df.shape[1]} colonnes")
    print(f"  Période : {df['ts_event'].iloc[0]} → {df['ts_event'].iloc[-1]}")

    # Sessions
    if 'session_id' in df.columns:
        print(f"  Sessions : {df['session_id'].value_counts().to_dict()}")
    if 'is_in_us_cash' in df.columns:
        print(f"  US cash : {df['is_in_us_cash'].sum()} barres")

    return df


# ═══════════════════════════════════════════════════════════════════
# 2. FORWARD MOVES
# ═══════════════════════════════════════════════════════════════════

def add_forward_moves(df: pd.DataFrame,
                      horizons: list = None,
                      price_col: str = 'close',
                      tick_size: float = 0.10) -> pd.DataFrame:
    """Calcule moves forward en ticks, par session (pas cross-session)."""
    if horizons is None:
        horizons = [5, 15, 30, 60]

    out = df.copy()
    for h in horizons:
        out[f'fwd_{h}m_ticks'] = np.nan

    for date, group in out.groupby('session_date'):
        idx = group.index
        price = group[price_col].values
        for h in horizons:
            fwd = np.full(len(price), np.nan)
            for i in range(len(price) - h):
                fwd[i] = (price[i + h] - price[i]) / tick_size
            out.loc[idx, f'fwd_{h}m_ticks'] = fwd

    return out


# ═══════════════════════════════════════════════════════════════════
# 3. CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════

def classify_bars(df: pd.DataFrame,
                  horizon: int = 15,
                  threshold_big: int = 100,
                  threshold_neutral: int = 30) -> pd.DataFrame:
    """Classifie barres en SHORT_WIN, LONG_WIN, NEUTRAL, SMALL_MOVE."""
    col = f'fwd_{horizon}m_ticks'
    conditions = [
        df[col] < -threshold_big,
        df[col] > threshold_big,
        (df[col] >= -threshold_neutral) & (df[col] <= threshold_neutral),
    ]
    choices = ['SHORT_WIN', 'LONG_WIN', 'NEUTRAL']
    df['bar_class'] = np.select(conditions, choices, default='SMALL_MOVE')

    counts = df['bar_class'].value_counts()
    print(f"\n[CLASSIFY] Horizon {horizon}min, seuil >{threshold_big}t :")
    for cls in ['SHORT_WIN', 'LONG_WIN', 'NEUTRAL', 'SMALL_MOVE']:
        print(f"  {cls:<12}: {counts.get(cls, 0):>5} ({counts.get(cls, 0)/len(df)*100:.1f}%)")
    return df


# ═══════════════════════════════════════════════════════════════════
# 4. FEATURE GROUPS — adapté Bot 2 (v4 enriched)
# ═══════════════════════════════════════════════════════════════════

FEATURE_GROUPS = {
    "MARKET_PROFILE": [
        "va_position_pct", "inside_cur_va", "position_in_range",
        "dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
        "poc_position", "poc_migration_dir", "range_size_pct",
        "inside_value_area",
        "ctx_poc_migration_10", "ctx_va_width", "ctx_va_width_atr",
        "ctx_va_developing_10", "ctx_va_developing_10_atr",
        "ctx_ib_extension_ratio", "ctx_rotation_factor_20",
        "ctx_failed_auction",
        "profile_shape" if False else "poc_position",  # profile_shape pas dans v4
    ],
    "NIVEAUX_VEILLE": [
        "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
        "dist_pdh_pct", "dist_pdl_pct",
        "dist_sess_high_pct", "dist_sess_low_pct",
        "dist_cash_high_pct", "dist_cash_low_pct",
        "is_new_sess_high", "is_new_sess_low",
        "is_new_cash_high", "is_new_cash_low",
        "dist_open_830_pct", "dist_open_930_pct",
        "above_open_830", "above_open_930",
    ],
    "IB_STRUCTURE": [
        "ib_range_ticks", "ib_range_atr", "ib_position_pct",
        "ib_broken_up", "ib_broken_dn",
        "dist_ib_high_pct", "dist_ib_low_pct",
        "ib_complete",
    ],
    "OVERNIGHT": [
        "ovn_range_ticks", "dist_ovn_high_pct", "dist_ovn_low_pct",
        "ovn_broken_up", "ovn_broken_dn",
        "dist_asia_high_pct", "dist_asia_low_pct",
        "dist_london_high_pct", "dist_london_low_pct",
        "above_london_open", "above_ny_open",
    ],
    "VWAP": [
        "dist_vwap_d_pct", "dist_vwap_d_atr", "vwap_d_side",
        "dist_vwap_w_pct", "dist_vwap_m_pct",
        "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
        "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct",
        "vwap_offset_pct", "vwap_slope_10", "vwap_slope_10_atr",
        "vwap_d_cross_up", "vwap_d_cross_dn",
        "vwap_d_sd1_above", "vwap_d_sd1_below",
        "vwap_d_sd2_above", "vwap_d_sd2_below",
        "vwap_w_d_aligned",
        "dist_pvwap_pct",
    ],
    "OPTIONS_MQ": [
        "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
        "dist_mq_call_0dte_pct", "dist_mq_put_0dte_pct", "dist_mq_hvl_0dte_pct",
        "dist_gex_nearest_up_pct", "dist_gex_nearest_dn_pct",
        "gex_cluster_count_z", "bool_gex_flip_zone",
        "bool_above_mq_call", "bool_above_mq_hvl",
        "dist_mq_hvl_pct_z",
        "dist_blind_nearest_up_pct", "dist_blind_nearest_dn_pct",
        "dist_1d_min_ticks_pct", "dist_1d_max_ticks_pct",
        "next_wall_dist_ticks", "next_wall_is_call",
    ],
    "ORDERFLOW_DELTA": [
        "delta_bar", "delta_pct", "delta_day_dir",
        "cvd_day", "cvd_session", "cvd_5d_rolling_ffd",
        "aggressor_imbalance", "buy_sell_ratio",
        "finish_strength", "finish_pct_up",
        "finish_strong_up", "finish_strong_dn",
        "delta_change", "delta_div_buy", "delta_div_sell",
        "ctx_delta_sum_3", "ctx_delta_exhaustion",
        "ctx_instant_absorption", "ctx_absorption_streak_5",
    ],
    "ORDERFLOW_VOLUME": [
        "rvol", "rvol_zscore", "rvol_regime",
        "rvol_buy", "rvol_sell", "rvol_buy_strong", "rvol_sell_strong",
        "rvol_absorb_buy", "rvol_absorb_sell", "rvol_extreme",
        "volume_z", "n_trades_z", "vol_zscore_20",
        "max_trade_size_z", "avg_price",
        "vol_spike_up", "vol_spike_dn",
        "ctx_vol_z_5",
        "vol_imbalance_3bar_build",
    ],
    "BATTLE_NAVALE": [
        "n_big_ask_v2_t1", "n_big_bid_v2_t1",
        "n_big_ask_v2_t2", "n_big_bid_v2_t2",
        "n_big_ask_v2_t3", "n_big_bid_v2_t3",
        "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
        "n_cluster_groups", "max_cluster_size", "max_cluster_volume_v2",
        "cluster_at_high", "cluster_at_low",
        "big_buy_dominance", "big_sell_dominance",
        "bn_absorb_ask_raw", "bn_absorb_bid_raw",
        "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
        "bn_stack_ask", "bn_stack_bid",
    ],
    "TRAPPED_EDGE": [
        "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
        "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
        "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
        "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
        "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
        "bar_edge_buy_fire", "bar_edge_sell_fire",
        "n_edge_buy_active", "n_edge_sell_active",
        "bar_edge_buy_zone_size", "bar_edge_sell_zone_size",
        "dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
    ],
    "COLOR_ZONES": [
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
        "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
        "n_delta_div_buy_zones_active", "n_delta_div_sell_zones_active",
        "dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct",
    ],
    "STRUCTURE_SWING": [
        "dist_last_swing_high_pct", "dist_last_swing_low_pct",
        "bars_since_last_swing_high", "bars_since_last_swing_low",
        "swing_high_active_lag10", "swing_low_active_lag10",
        "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
        "equal_highs_detected", "equal_lows_detected",
        "pct_in_range", "premium_zone", "discount_zone",
        "momentum_5b", "bar_body_pct", "bar_range_pct", "bar_return",
        "long_up_bar", "long_dn_bar",
        "long_dn_up_pattern", "long_up_dn_pattern",
    ],
    "SPIKE_NAKED": [
        "spike_detected_lag3", "n_spike_origins_active",
        "dist_last_spike_origin_pct", "bars_since_last_spike",
        "n_spike_origins_cluster_within_0_2pct",
        "n_naked_poc_active", "dist_naked_poc_nearest_pct",
        "naked_poc_age_max_days", "n_naked_poc_within_0_5pct",
        "n_single_prints_pct", "has_single_print_above",
    ],
    "CROSS_INSTRUMENT": [
        "im_smt_divergence", "im_cross_open_signal",
        "im_open_type_agreement", "im_cross_delta_agreement_5",
        "im_cross_delta_weighted_5", "im_rolling_correlation_10",
        "im_price_ratio_slope_10", "im_volume_lead",
        "im_delta_day_divergence", "im_ltr_slope_diff",
    ],
    "SESSION_CONTEXT": [
        "open_type", "day_type", "open_zone",
        "open_bias_conf", "open_direction",
        "near_resistance_level", "near_support_level",
        "session_segment", "time_to_session_close_norm",
        "mins_since_news",
    ],
    # ════════════════════════════════════════════════════════════════════
    # GOLD-SPECIFIC GROUPS (Phase D Gold features)
    # ════════════════════════════════════════════════════════════════════
    "GOLD_INTERMARKET": [
        "im_dxy_corr_60d",                  # corrélation Gold/DXY (proxy 6E)
        "im_real_yields_proxy",             # momentum ZN+ZB (yields baisse = bull gold)
        "gold_silver_ratio",                # ratio Gold/Silver (mean ~80)
        "gold_silver_ratio_zscore_60d",     # z-score (>2 = silver under, mean rev short Gold)
        "copper_gold_ratio",                # Dr. Copper / Gold (risk-on/off)
        "copper_gold_ratio_momentum_30",    # momentum risk appetite
        "oil_gold_ratio_zscore_60d",        # Oil/Gold inflation proxy
    ],
    "GOLD_SESSION": [
        "mgc_asia_london_overlap_vol",      # volume ratio overlap 12:30-16:00 UTC
        "mgc_session_break_acceleration",   # accel post US-open 13:30 ET
        "london_fix_window_10_30",          # AM Fix +/- 5min
        "london_fix_window_15_00",          # PM Fix +/- 5min
        "asia_breakout_strength",           # range Asia / ATR
    ],
    "GOLD_MQ_LEVELS": [
        # MQ Gold en TICKS (pas pct, cf prompt)
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
        "dist_1d_min_ticks", "dist_1d_max_ticks",
        "dist_gex_nearest_up", "dist_gex_nearest_dn", "gex_cluster_count",
        "dist_blind_nearest_up", "dist_blind_nearest_dn",
        "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
    ],
}


# ═══════════════════════════════════════════════════════════════════
# 5. EDGE DETECTOR
# ═══════════════════════════════════════════════════════════════════

def compute_feature_edge(df: pd.DataFrame, min_samples: int = 20) -> pd.DataFrame:
    """Compare features entre SHORT_WIN, LONG_WIN et NEUTRAL."""
    shorts = df[df['bar_class'] == 'SHORT_WIN']
    longs = df[df['bar_class'] == 'LONG_WIN']
    neutrals = df[df['bar_class'] == 'NEUTRAL']

    results = []
    for group_name, features in FEATURE_GROUPS.items():
        for feat in features:
            if feat not in df.columns:
                continue

            s_val = shorts[feat].mean() if len(shorts) > 0 else np.nan
            l_val = longs[feat].mean() if len(longs) > 0 else np.nan
            n_val = neutrals[feat].mean() if len(neutrals) > 0 else np.nan

            edge_short, edge_long = 0, 0
            if not np.isnan(n_val) and abs(n_val) > 0.0001:
                if not np.isnan(s_val):
                    edge_short = abs(s_val - n_val) / abs(n_val)
                if not np.isnan(l_val):
                    edge_long = abs(l_val - n_val) / abs(n_val)

            # Direction de l'edge
            short_dir = ""
            long_dir = ""
            if not np.isnan(s_val) and not np.isnan(n_val):
                short_dir = "↑" if s_val > n_val else "↓"
            if not np.isnan(l_val) and not np.isnan(n_val):
                long_dir = "↑" if l_val > n_val else "↓"

            # T-stat simplifié
            try:
                s_std = shorts[feat].std()
                n_std = neutrals[feat].std()
                if s_std > 0 and n_std > 0 and len(shorts) > 1 and len(neutrals) > 1:
                    t_stat = abs(s_val - n_val) / np.sqrt(s_std**2/len(shorts) + n_std**2/len(neutrals))
                else:
                    t_stat = 0
            except:
                t_stat = 0

            results.append({
                'group': group_name,
                'feature': feat,
                'mean_short': s_val,
                'mean_long': l_val,
                'mean_neutral': n_val,
                'short_dir': short_dir,
                'long_dir': long_dir,
                'edge_short': edge_short,
                'edge_long': edge_long,
                'edge_score': max(edge_short, edge_long),
                't_stat': t_stat,
                'n_nan_pct': df[feat].isna().mean(),
            })

    return pd.DataFrame(results).sort_values('edge_score', ascending=False)


# ═══════════════════════════════════════════════════════════════════
# 6. SETUPS — adaptés Bot 2 features (pct au lieu de ticks)
# ═══════════════════════════════════════════════════════════════════

SETUPS = [
    # --- MARKET PROFILE ---
    {
        "name": "SELL_VPOC_FAR_ABOVE",
        "description": "Prix très loin au-dessus VPOC session → retour mean reversion",
        "side": "SHORT",
        "conditions": {
            "dist_cur_vpoc_pct": ("<", -0.15),
            "finish_strength": ("<", -10),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "BUY_VPOC_RECLAIM",
        "description": "Prix revient au VPOC + delta positif → acheteurs reviennent",
        "side": "LONG",
        "conditions": {
            "dist_cur_vpoc_pct": ("abs<", 0.05),
            "delta_bar": (">", 20),
            "rvol": (">", 0.6),
        },
    },
    {
        "name": "SELL_TOP_RANGE",
        "description": "Prix au haut du range (>90%) + finish faible → rejection",
        "side": "SHORT",
        "conditions": {
            "position_in_range": (">", 0.90),
            "finish_strength": ("<", -15),
        },
    },
    {
        "name": "BUY_BOTTOM_RANGE",
        "description": "Prix au bas du range (<10%) + RVOL spike → reversal",
        "side": "LONG",
        "conditions": {
            "position_in_range": ("<", 0.10),
            "rvol": (">", 1.2),
            "delta_bar": (">", 0),
        },
    },
    # --- NIVEAUX VEILLE ---
    {
        "name": "SELL_ABOVE_PREV_VAH",
        "description": "Prix au-dessus prev VAH (acceptance rejetée) → retour dans VA",
        "side": "SHORT",
        "conditions": {
            "dist_prev_vah_pct": ("<", -0.15),
            "finish_strength": ("<", 0),
        },
    },
    {
        "name": "BUY_AT_PREV_VAL",
        "description": "Prix proche prev VAL (support) + delta positif → rebond",
        "side": "LONG",
        "conditions": {
            "dist_prev_val_pct": ("abs<", 0.10),
            "delta_bar": (">", 10),
        },
    },
    # --- IB ---
    {
        "name": "SELL_IB_BREAK_DN",
        "description": "IB cassée par le bas + delta négatif → continuation bearish",
        "side": "SHORT",
        "conditions": {
            "ib_broken_dn": ("==", 1),
            "delta_bar": ("<", -10),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "BUY_IB_BREAK_UP",
        "description": "IB cassée par le haut + delta positif → continuation bullish",
        "side": "LONG",
        "conditions": {
            "ib_broken_up": ("==", 1),
            "delta_bar": (">", 10),
            "rvol": (">", 0.5),
        },
    },
    # --- VWAP ---
    {
        "name": "BUY_VWAP_RECLAIM",
        "description": "Prix traverse VWAP daily par le bas + slope positive → trend",
        "side": "LONG",
        "conditions": {
            "dist_vwap_d_pct": ("abs<", 0.05),
            "vwap_slope_10": (">", 1),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "SELL_VWAP_SD2_REJECT",
        "description": "Prix touche VWAP SD2 upper → suracheté, rejection",
        "side": "SHORT",
        "conditions": {
            "dist_vwap_d_sd2u_pct": ("abs<", 0.05),
            "delta_bar": ("<", 0),
        },
    },
    {
        "name": "BUY_VWAP_SD2_SUPPORT",
        "description": "Prix touche VWAP SD2 lower → survendu, rebond",
        "side": "LONG",
        "conditions": {
            "dist_vwap_d_sd2d_pct": ("abs<", 0.05),
            "delta_bar": (">", 0),
        },
    },
    # --- OPTIONS MQ ---
    {
        "name": "SELL_MQ_CALL_WALL",
        "description": "Prix au-dessus MQ Call (dist négatif) → résistance options",
        "side": "SHORT",
        "conditions": {
            "dist_mq_call_pct": ("<", -0.10),
            "finish_strength": ("<", 0),
        },
    },
    {
        "name": "BUY_MQ_PUT_SUPPORT",
        "description": "Prix proche MQ Put → support gamma squeeze",
        "side": "LONG",
        "conditions": {
            "dist_mq_put_pct": (">", -1.0),
            "delta_bar": (">", 0),
            "rvol": (">", 0.6),
        },
    },
    {
        "name": "SELL_GEX_REJECTION",
        "description": "Prix proche GEX down + delta négatif → rejet",
        "side": "SHORT",
        "conditions": {
            "dist_gex_nearest_dn_pct": ("abs<", 0.05),
            "delta_bar": ("<", -10),
        },
    },
    {
        "name": "BUY_GEX_SUPPORT",
        "description": "Prix rebondit sur GEX up + delta positif",
        "side": "LONG",
        "conditions": {
            "dist_gex_nearest_up_pct": ("<", 0.10),
            "delta_bar": (">", 10),
        },
    },
    {
        "name": "SELL_1D_MAX_REJECT",
        "description": "Prix proche du 1d max MQ → résistance intraday",
        "side": "SHORT",
        "conditions": {
            "dist_1d_max_ticks_pct": ("abs<", 0.05),
            "finish_strength": ("<", 0),
        },
    },
    # --- ORDERFLOW ---
    {
        "name": "SELL_CVD_DIVERGENCE",
        "description": "Prix haut + CVD négatif → divergence bearish, les acheteurs lâchent",
        "side": "SHORT",
        "conditions": {
            "delta_day_dir": ("==", -1),
            "position_in_range": (">", 0.70),
            "dist_vwap_d_pct": ("<", -0.05),
        },
    },
    {
        "name": "BUY_CVD_DIVERGENCE",
        "description": "Prix bas + CVD positif → divergence bullish, vendeurs épuisés",
        "side": "LONG",
        "conditions": {
            "delta_day_dir": ("==", 1),
            "position_in_range": ("<", 0.30),
            "dist_vwap_d_pct": (">", 0.05),
        },
    },
    {
        "name": "SELL_DELTA_EXHAUSTION",
        "description": "Delta exhaustion détecté → momentum s'essouffle",
        "side": "SHORT",
        "conditions": {
            "ctx_delta_exhaustion": (">", 0.5),
            "position_in_range": (">", 0.70),
        },
    },
    {
        "name": "BUY_ABSORPTION",
        "description": "Absorption acheteur détectée → support fort",
        "side": "LONG",
        "conditions": {
            "ctx_instant_absorption": ("==", 1),
            "delta_bar": (">", 0),
        },
    },
    # --- TRAPPED TRADERS ---
    {
        "name": "SELL_TRAPPED_BUYERS",
        "description": "Trapped buyers détectés à résistance → piège bull confirmé",
        "side": "SHORT",
        "conditions": {
            "bn_trapped_buyers_at_resistance": ("==", 1),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "BUY_TRAPPED_SELLERS",
        "description": "Trapped sellers détectés à support → piège bear confirmé",
        "side": "LONG",
        "conditions": {
            "bn_trapped_sellers_at_support": ("==", 1),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "SELL_EDGE_SELL_FIRE",
        "description": "Edge sell zone fire → signal de vente structurel",
        "side": "SHORT",
        "conditions": {
            "bar_edge_sell_fire": ("==", 1),
            "delta_bar": ("<", 0),
        },
    },
    {
        "name": "BUY_EDGE_BUY_FIRE",
        "description": "Edge buy zone fire → signal d'achat structurel",
        "side": "LONG",
        "conditions": {
            "bar_edge_buy_fire": ("==", 1),
            "delta_bar": (">", 0),
        },
    },
    # --- CROSS-INSTRUMENT ---
    {
        "name": "SELL_SMT_DIVERGENCE",
        "description": "SMT divergence ES/NQ → désaccord inter-marché, reversal",
        "side": "SHORT",
        "conditions": {
            "im_smt_divergence": ("==", 1),
            "position_in_range": (">", 0.70),
        },
    },
    {
        "name": "BUY_CROSS_DELTA_AGREE",
        "description": "Cross-instrument delta agreement > 0.7 + bas du range → confirmation",
        "side": "LONG",
        "conditions": {
            "im_cross_delta_agreement_5": (">", 0.7),
            "position_in_range": ("<", 0.30),
            "delta_bar": (">", 0),
        },
    },
    # --- COLOR ZONES ---
    {
        "name": "BUY_COLOR_UP_PROXIMITY",
        "description": "Prix proche d'une color up zone → support structurel",
        "side": "LONG",
        "conditions": {
            "dist_color_up_nearest_pct": ("abs<", 0.05),
            "n_color_up_cluster_within_0_2pct": (">", 1),
            "delta_bar": (">", 0),
        },
    },
    {
        "name": "SELL_COLOR_DN_PROXIMITY",
        "description": "Prix proche d'une color down zone → résistance structurelle",
        "side": "SHORT",
        "conditions": {
            "dist_color_dn_nearest_pct": ("abs<", 0.05),
            "n_color_dn_cluster_within_0_2pct": (">", 1),
            "delta_bar": ("<", 0),
        },
    },
    # --- SPIKE / NAKED POC ---
    {
        "name": "BUY_NAKED_POC_MAGNET",
        "description": "Naked POC actif proche → prix attiré vers le POC non retesté",
        "side": "LONG",
        "conditions": {
            "n_naked_poc_within_0_5pct": (">", 0),
            "position_in_range": ("<", 0.50),
            "delta_bar": (">", 0),
        },
    },
    # --- SESSION TIMING ---
    {
        "name": "SELL_LATE_SESSION_FADE",
        "description": "Fin de session (dernier quart) + prix haut → fade probable",
        "side": "SHORT",
        "conditions": {
            "time_to_session_close_norm": ("<", 0.25),
            "position_in_range": (">", 0.80),
            "finish_strength": ("<", 0),
        },
    },
    # ════════════════════════════════════════════════════════════════════
    # SETUPS GOLD-SPECIFIQUES (selon PROMPT_CLAUDE_CODE_BOT3_GOLD)
    # ════════════════════════════════════════════════════════════════════
    {
        "name": "GOLD_ASIA_BREAKOUT_CONTINUATION_LONDON",
        "description": "Asia breakout fort + LONDON poursuit → momentum handoff continuation",
        "side": "LONG",
        "conditions": {
            "asia_breakout_strength": (">", 2.0),
            "is_in_london": ("==", 1),
            "delta_bar": (">", 10),
        },
    },
    {
        "name": "GOLD_SELL_MQ_CALL_0DTE_REJECT",
        "description": "Prix touche MQ Call 0DTE en ticks → résistance gamma rejection",
        "side": "SHORT",
        "conditions": {
            "dist_mq_call_0dte": ("abs<", 50),    # < 50 ticks
            "delta_bar": ("<", 0),
            "rvol": (">", 0.7),
        },
    },
    {
        "name": "GOLD_BUY_MQ_PUT_0DTE_REBOUND",
        "description": "Prix touche MQ Put 0DTE → support gamma rebond",
        "side": "LONG",
        "conditions": {
            "dist_mq_put_0dte": ("abs<", 50),
            "delta_bar": (">", 0),
            "rvol": (">", 0.7),
        },
    },
    {
        "name": "GOLD_DXY_DECOUPLE_LONG",
        "description": "DXY corr s'éloigne fort de baseline -0.45 vers positif → setup mean rev LONG Gold",
        "side": "LONG",
        "conditions": {
            "im_dxy_corr_60d": (">", 0.10),     # découplé hausse
            "delta_bar": (">", 0),
        },
    },
    {
        "name": "GOLD_REAL_YIELDS_EXTREME_LONG",
        "description": "Real yields chutent fort (proxy ZN+ZB momentum > +1) → bullish gold",
        "side": "LONG",
        "conditions": {
            "im_real_yields_proxy": (">", 1.0),
            "delta_bar": (">", 0),
        },
    },
    {
        "name": "GOLD_SILVER_RATIO_EXTREME_SHORT",
        "description": "Gold/Silver ratio z-score > 2 → silver underperformance = Gold suracheté",
        "side": "SHORT",
        "conditions": {
            "gold_silver_ratio_zscore_60d": (">", 2.0),
            "finish_strength": ("<", 0),
        },
    },
    {
        "name": "GOLD_SILVER_RATIO_EXTREME_LONG",
        "description": "Gold/Silver ratio z-score < -2 → silver overperformance = mean rev Gold LONG",
        "side": "LONG",
        "conditions": {
            "gold_silver_ratio_zscore_60d": ("<", -2.0),
            "delta_bar": (">", 0),
        },
    },
    {
        "name": "GOLD_BLIND_SPOT_PROXIMITY_LONG",
        "description": "Prix proche Blind Spot up (zone gamma vide = accélération possible)",
        "side": "LONG",
        "conditions": {
            "dist_blind_nearest_up": ("abs<", 30),
            "delta_bar": (">", 10),
            "rvol": (">", 1.0),
        },
    },
    {
        "name": "GOLD_BLIND_SPOT_PROXIMITY_SHORT",
        "description": "Prix proche Blind Spot dn → accélération down possible",
        "side": "SHORT",
        "conditions": {
            "dist_blind_nearest_dn": ("abs<", 30),
            "delta_bar": ("<", -10),
            "rvol": (">", 1.0),
        },
    },
    {
        "name": "GOLD_LONDON_NY_OVERLAP_IB_BREAKOUT_UP",
        "description": "London/NY overlap + IB breakout UP + flow positif",
        "side": "LONG",
        "conditions": {
            "mgc_asia_london_overlap_vol": (">", 1.0),
            "ib_broken_up": ("==", 1),
            "delta_pct": (">", 0.15),
        },
    },
    {
        "name": "GOLD_LONDON_NY_OVERLAP_IB_BREAKOUT_DN",
        "description": "London/NY overlap + IB breakout DN + flow négatif",
        "side": "SHORT",
        "conditions": {
            "mgc_asia_london_overlap_vol": (">", 1.0),
            "ib_broken_dn": ("==", 1),
            "delta_pct": ("<", -0.15),
        },
    },
    {
        "name": "GOLD_HVL_0DTE_PIVOT_LONG",
        "description": "Prix touche HVL 0DTE depuis bas (support gamma pivot)",
        "side": "LONG",
        "conditions": {
            "dist_mq_hvl_0dte": ("abs<", 50),
            "bool_above_mq_hvl": ("==", 0),     # prix sous HVL
            "delta_bar": (">", 5),
        },
    },
    {
        "name": "GOLD_HVL_0DTE_PIVOT_SHORT",
        "description": "Prix touche HVL 0DTE depuis haut (résistance gamma pivot)",
        "side": "SHORT",
        "conditions": {
            "dist_mq_hvl_0dte": ("abs<", 50),
            "bool_above_mq_hvl": ("==", 1),
            "delta_bar": ("<", -5),
        },
    },
]


def apply_condition(series, op, value):
    if op == "==": return series == value
    elif op == ">": return series > value
    elif op == "<": return series < value
    elif op == ">=": return series >= value
    elif op == "<=": return series <= value
    elif op == "abs<": return series.abs() < value
    elif op == "abs>": return series.abs() > value
    return pd.Series(True, index=series.index)


def test_setup(df, setup, horizon=15, tick_value=0.50):
    """Teste un setup et retourne les métriques."""
    fwd_col = f'fwd_{horizon}m_ticks'
    if fwd_col not in df.columns:
        return {"name": setup["name"], "n_triggers": 0}

    mask = pd.Series(True, index=df.index)
    for feat, cond in setup.get("conditions", {}).items():
        if not isinstance(cond, (tuple, list)) or len(cond) != 2:
            continue
        op, value = cond
        if feat not in df.columns:
            mask &= False
            break
        mask &= apply_condition(df[feat], op, value)

    triggered = df[mask & df[fwd_col].notna()]
    if len(triggered) == 0:
        return {"name": setup["name"], "side": setup.get("side"), "n_triggers": 0, "n_days": 0}

    fwd = triggered[fwd_col].values
    side = setup.get("side", "LONG")
    pnl = -fwd if side == "SHORT" else fwd

    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    win_rate = len(winners) / len(pnl)
    pf = (winners.sum() / -losers.sum()) if len(losers) > 0 and losers.sum() != 0 else 999
    n_days = triggered['session_date'].nunique()

    return {
        "name": setup["name"],
        "description": setup.get("description", ""),
        "side": side,
        "n_triggers": len(triggered),
        "n_days": n_days,
        "triggers_per_day": round(len(triggered) / max(n_days, 1), 1),
        "win_rate": round(win_rate * 100, 1),
        "pf": round(pf, 2),
        "avg_move_ticks": round(pnl.mean(), 0),
        "avg_move_dollars": round(pnl.mean() * tick_value, 2),
        "best_ticks": round(pnl.max(), 0),
        "worst_ticks": round(pnl.min(), 0),
        "total_pnl_ticks": round(pnl.sum(), 0),
    }


# ═══════════════════════════════════════════════════════════════════
# 7. TIMING
# ═══════════════════════════════════════════════════════════════════

def analyze_timing(df, horizon=15):
    fwd_col = f'fwd_{horizon}m_ticks'
    if fwd_col not in df.columns:
        return pd.DataFrame()

    df_valid = df[df[fwd_col].notna()].copy()
    df_valid['hour_utc'] = df_valid['ts_event'].dt.hour
    df_valid['half_hour'] = df_valid['hour_utc'] * 2 + (df_valid['ts_event'].dt.minute >= 30).astype(int)

    results = []
    for hh, group in df_valid.groupby('half_hour'):
        h = hh // 2
        m = "00" if hh % 2 == 0 else "30"
        fwd = group[fwd_col]
        results.append({
            'time_utc': f"{h:02d}:{m}",
            'n_bars': len(group),
            'avg_move': round(fwd.mean(), 1),
            'big_short': int((fwd < -100).sum()),
            'big_long': int((fwd > 100).sum()),
            'win_long_pct': round((fwd > 0).mean() * 100, 1),
            'std': round(fwd.std(), 1),
        })
    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════════════
# 8. RAPPORT
# ═══════════════════════════════════════════════════════════════════

def generate_report(df, edge_df, setup_results, timing_df, symbol, output_path):
    lines = []
    lines.append(f"# EDGE DISCOVERY REPORT — {symbol} (Bot 2 Databento V4)")
    lines.append(f"")
    lines.append(f"**Généré** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    # Safe min/max sur session_date (peut contenir NaN hors RTH)
    sd_clean = df['session_date'].dropna()
    sd_min = sd_clean.min() if len(sd_clean) > 0 else "N/A"
    sd_max = sd_clean.max() if len(sd_clean) > 0 else "N/A"
    sd_n = sd_clean.nunique() if len(sd_clean) > 0 else 0
    lines.append(f"**Données** : {sd_min} → {sd_max}")
    lines.append(f"**Barres** : {len(df)} ({sd_n} jours)")
    lines.append(f"**Features analysées** : {sum(len(v) for v in FEATURE_GROUPS.values())}")
    lines.append(f"**Setups testés** : {len(SETUPS)}")
    lines.append(f"")

    # Top features
    lines.append(f"## 1. TOP 30 FEATURES AVEC EDGE")
    lines.append(f"")
    lines.append(f"| # | Groupe | Feature | Short Win | Long Win | Neutral | Edge% | Dir S/L | T-stat |")
    lines.append(f"|---|--------|---------|-----------|----------|---------|-------|---------|--------|")
    for i, (_, row) in enumerate(edge_df.head(30).iterrows()):
        stars = "⭐" * min(3, int(row['edge_score'] / 0.3))
        lines.append(
            f"| {i+1} | {row['group'][:14]} | {row['feature'][:30]} | "
            f"{row['mean_short']:.3f} | {row['mean_long']:.3f} | {row['mean_neutral']:.3f} | "
            f"{row['edge_score']:.0%} {stars} | {row['short_dir']}/{row['long_dir']} | {row['t_stat']:.1f} |"
        )

    # Setups
    lines.append(f"")
    lines.append(f"## 2. SETUPS TESTÉS ({len(SETUPS)} setups)")
    lines.append(f"")
    lines.append(f"| Setup | Side | Triggers | Jours | /j | WR% | PF | Avg t | Best | Worst | Total |")
    lines.append(f"|-------|------|----------|-------|-----|-----|-----|-------|------|-------|-------|")

    valid = [s for s in setup_results if s.get('n_triggers', 0) >= 3]
    valid.sort(key=lambda x: x.get('pf', 0), reverse=True)
    for s in valid:
        v = ""
        if s.get('pf', 0) >= 1.5 and s.get('win_rate', 0) >= 55: v = " ⭐⭐⭐"
        elif s.get('pf', 0) >= 1.3 and s.get('win_rate', 0) >= 50: v = " ⭐⭐"
        elif s.get('pf', 0) >= 1.1 and s.get('win_rate', 0) >= 45: v = " ⭐"
        lines.append(
            f"| {s['name'][:28]} | {s['side']} | {s['n_triggers']} | {s['n_days']} | "
            f"{s.get('triggers_per_day',0)} | {s.get('win_rate',0):.0f}% | {s.get('pf',0):.2f} | "
            f"{s.get('avg_move_ticks',0):+.0f} | {s.get('best_ticks',0):+.0f} | "
            f"{s.get('worst_ticks',0):+.0f} | {s.get('total_pnl_ticks',0):+.0f}{v} |"
        )

    # Timing
    if not timing_df.empty:
        lines.append(f"")
        lines.append(f"## 3. TIMING (demi-heure UTC)")
        lines.append(f"")
        lines.append(f"| Heure | Bars | Avg move | SHORT>100t | LONG>100t | Win L% |")
        lines.append(f"|-------|------|---------|-----------|----------|--------|")
        for _, row in timing_df.iterrows():
            b = " 🔴" if row['avg_move'] < -50 else (" 🟢" if row['avg_move'] > 50 else "")
            lines.append(f"| {row['time_utc']} | {row['n_bars']} | {row['avg_move']:+.0f}t{b} | "
                        f"{row['big_short']} | {row['big_long']} | {row['win_long_pct']:.0f}% |")

    # Recommandations
    lines.append(f"")
    lines.append(f"## 4. RECOMMANDATIONS")
    lines.append(f"")
    best = [s for s in valid if s.get('pf', 0) >= 1.3 and s.get('win_rate', 0) >= 50]
    if best:
        lines.append(f"### Setups validés (PF >= 1.3 + WR >= 50%) :")
        for s in best:
            lines.append(f"- **{s['name']}** ({s['side']}) : PF {s['pf']:.2f}, WR {s['win_rate']:.0f}%, "
                        f"{s['n_triggers']} triggers")
            lines.append(f"  {s.get('description', '')}")
    else:
        lines.append(f"Aucun setup validé. Plus de données nécessaires.")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"*edge_discovery_bot2.py — MIA IA System (Bot 2 Databento V4)*")

    report = "\n".join(lines)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(report)
    print(f"\n[REPORT] Sauvegardé : {output_path}")
    return report


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Edge Discovery GOLD (MGC) — selon PROMPT_CLAUDE_CODE_BOT3_GOLD")
    parser.add_argument("--data-dir", default="DATA/DATASETS/v4_enriched",
                        help="Répertoire parquets v4 enriched (ignoré pour MGC qui utilise monolithique)")
    parser.add_argument("--symbol", default="MGC", help="MGC (Gold) ou NQ/ES pour comparaison")
    parser.add_argument("--output", default="DOCS/EDGE_REPORT_GOLD_MGC.md")
    parser.add_argument("--horizon", type=int, default=15)
    parser.add_argument("--threshold", type=int, default=80,
                        help="Seuil gros move ticks (Gold 80t = 8pts, vs NQ 100t)")
    parser.add_argument("--rth-only", action="store_true", help="US cash session only")
    parser.add_argument("--tick-value", type=float, default=1.0,
                        help="MGC=1.0, NQ=0.50, ES=1.25")
    args = parser.parse_args()

    print("=" * 70)
    print(f"EDGE DISCOVERY GOLD — {args.symbol}")
    print("=" * 70)

    df = load_v4_parquets(args.data_dir, args.symbol)
    if df.empty:
        return

    # RTH filter
    if args.rth_only:
        n_before = len(df)
        if 'is_in_us_cash' in df.columns:
            df = df[df['is_in_us_cash'] == 1].reset_index(drop=True)
        elif 'session_id' in df.columns:
            df = df[df['session_id'] == 2].reset_index(drop=True)
        print(f"[RTH] US cash : {n_before} → {len(df)} barres")

    # Forward moves
    print(f"\n[FORWARD] Calcul moves {args.horizon}min...")
    df = add_forward_moves(df, horizons=[5, 15, 30, 60])

    # Classify
    df = classify_bars(df, horizon=args.horizon, threshold_big=args.threshold)

    # Feature edge
    n_features = sum(1 for g in FEATURE_GROUPS.values() for f in g if f in df.columns)
    print(f"\n[EDGE] Analyse {n_features} features (sur {sum(len(v) for v in FEATURE_GROUPS.values())} définies)...")
    edge_df = compute_feature_edge(df)

    print(f"\nTOP 15 features :")
    for i, (_, row) in enumerate(edge_df.head(15).iterrows()):
        stars = "⭐" * min(3, int(row['edge_score'] / 0.3))
        print(f"  {row['edge_score']:.0%} {stars} {row['group'][:12]:>12} / {row['feature']}")

    # Setups
    print(f"\n[SETUPS] Test {len(SETUPS)} setups...")
    setup_results = []
    for setup in SETUPS:
        result = test_setup(df, setup, horizon=args.horizon, tick_value=args.tick_value)
        setup_results.append(result)
        n = result.get('n_triggers', 0)
        if n > 0:
            pf = result.get('pf', 0)
            wr = result.get('win_rate', 0)
            avg = result.get('avg_move_ticks', 0)
            star = "⭐" if pf >= 1.3 and wr >= 50 else ""
            print(f"  {setup['name'][:35]:<35} {n:>4} trig | WR {wr:>5.1f}% | PF {pf:>5.2f} | Avg {avg:>+6.0f}t {star}")

    # Timing
    print(f"\n[TIMING] Analyse horaire...")
    timing_df = analyze_timing(df, horizon=args.horizon)

    # Report
    generate_report(df, edge_df, setup_results, timing_df, args.symbol, args.output)

    # Summary
    best = [s for s in setup_results if s.get('pf', 0) >= 1.3 and s.get('win_rate', 0) >= 50 and s.get('n_triggers', 0) >= 3]
    print(f"\n{'='*70}")
    print(f"RÉSUMÉ : {len(best)} setups validés")
    for s in best:
        print(f"  ⭐ {s['name']} : PF {s['pf']:.2f}, WR {s['win_rate']:.0f}%, {s['n_triggers']} triggers")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
