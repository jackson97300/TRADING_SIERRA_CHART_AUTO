"""
strategy_battery_v5_full.py — Battery complète sur dataset v5.

V5 ajoute :
  1. Adaptation des 17 hypothèses (H1-H9 + SA-SH) aux noms de features v5
     (suffixes _pct, _raw, _at_level présents dans le parquet enrichi)
  2. Nouvelles stratégies demandées par Jackson 27/04 soir :
     - JC : cluster trades (n_clusters, max_cluster_size, dist_cluster_*)
     - JC2 : color zones (n_color_up_zones_active, dist_color_up_nearest_pct)
     - JL : long bars (long_up_bar, long_dn_bar)
     - JL2 : long reversal patterns (long_up_dn_pattern, long_dn_up_pattern)
     - JI : imbalance extreme (vol_imbalance_3bar_build, aggressor_imbalance)
     - JD : divergence (im_delta_day_divergence, n_delta_div_buy_cluster)
     - JE : edge zones (bar_edge_buy_fire, bar_edge_sell_fire)
     - JS : vol spike (vol_spike_up, vol_spike_dn, rvol_extreme)
     - JT : trapped traders (n_trapped_buyers_cluster, n_trapped_sellers_cluster)
     - JG : Game Changers dashboard composite (open_type + open_bias_conf + day_type)
     - JM : MenthorQ confluence (proximité 2+ niveaux MQ)

Triple Barrier ATR-dynamique cohérent v5 : K_SL=1.5 K_TP=2.0 H=60.

Auteur : MIA Trading System V2
Date   : 2026-04-27 20:00
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Dict, Callable, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Reutilise stats robustes
from strategy_battery_test import (
    mc_permutation_shuffle_order, bootstrap_pf_ci, benjamini_hochberg,
    h1_vwap_reversion, h2_open_drive, h3_failed_ib,
    h7_intermarket_divergence, h8_ofi_residualized,
)

# Constantes alignees v5
TICK_SIZE = 0.25
K_SL = 1.5
K_TP_RATIO = 2.0
HORIZON = 60
COOLDOWN_BARS = 3
MAX_TRADES_PER_DAY = 5
COST_TICKS = {"ES": 2.3, "NQ": 5.2}


def _g(df: pd.DataFrame, col: str, fill: float = 0.0) -> np.ndarray:
    """Get column safely, fillna."""
    if col not in df.columns:
        return np.full(len(df), np.nan)
    return pd.to_numeric(df[col], errors="coerce").fillna(fill).values


def _has(df: pd.DataFrame, *cols) -> bool:
    return all(c in df.columns for c in cols)


# ═══════════════════════════════════════════════════════════════════════════════
# H4-H9 + SA-SH adaptees aux noms v5 (suffixes _pct/_raw)
# ═══════════════════════════════════════════════════════════════════════════════

def h4_v5(df):
    """H4 1D Magnetism — utilise dist_1d_max/min_ticks_pct."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "dist_1d_max_ticks_pct", "dist_1d_min_ticks_pct"):
        return sig
    d_max = _g(df, "dist_1d_max_ticks_pct")
    d_min = _g(df, "dist_1d_min_ticks_pct")
    # Proche du 1d max → reversion bearish
    sig[(np.abs(d_max) < 0.001)] = -1  # < 0.1%
    sig[(np.abs(d_min) < 0.001)] = 1
    return sig


def h5_v5(df):
    """H5 Rejet VAH/VAL avec _pct + delta_day_dir comme fallback CVD."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "dist_cur_vah_pct", "dist_cur_val_pct"):
        return sig
    d_vah = _g(df, "dist_cur_vah_pct")
    d_val = _g(df, "dist_cur_val_pct")
    # cvd_day_dir absent → utilise delta_day_dir (présent)
    cvd = _g(df, "delta_day_dir") if "delta_day_dir" in df.columns else np.zeros(len(df))
    sig[(np.abs(d_vah) < 0.002) & (cvd == -1)] = -1  # rejet VAH bearish
    sig[(np.abs(d_val) < 0.002) & (cvd == 1)] = 1   # rebond VAL bullish
    return sig


def h6_v5(df):
    """H6 Divergence — utilise im_delta_day_divergence + dist_delta_div_buy/sell."""
    sig = np.zeros(len(df), dtype=int)
    if "im_delta_day_divergence" not in df.columns:
        return sig
    div = _g(df, "im_delta_day_divergence")
    # Quand divergence détectée + momentum opposé → revoir
    if "delta_day_dir" in df.columns:
        ddir = _g(df, "delta_day_dir")
        # div positif (price up but delta down) → SELL
        sig[(div > 0) & (ddir < 0)] = -1
        # div négatif (price down but delta up) → BUY
        sig[(div < 0) & (ddir > 0)] = 1
    return sig


def h9_v5(df):
    """H9 VPIN regime — utilise rvol_regime + buy_vol/sell_vol."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "buy_vol", "sell_vol"):
        return sig
    buy = _g(df, "buy_vol")
    sell = _g(df, "sell_vol")
    vpin = np.abs(buy - sell) / np.maximum(buy + sell, 1)
    vpin_smooth = pd.Series(vpin).rolling(20, min_periods=5).mean().fillna(0.5).values
    clean = vpin_smooth < 0.3
    if "delta_day_dir" in df.columns:
        ddir = _g(df, "delta_day_dir")
        sig[clean & (ddir > 0)] = 1
        sig[clean & (ddir < 0)] = -1
    return sig


def sa_v5(df):
    """SA GEX Wall Fade adapté _pct."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "dist_mq_put_0dte_pct", "dist_mq_call_0dte_pct", "dist_mq_hvl_pct"):
        return sig
    d_put = _g(df, "dist_mq_put_0dte_pct")
    d_call = _g(df, "dist_mq_call_0dte_pct")
    d_hvl = _g(df, "dist_mq_hvl_pct")
    absorb_bid = _g(df, "bn_absorb_bid_raw") if "bn_absorb_bid_raw" in df.columns else np.zeros(len(df))
    absorb_ask = _g(df, "bn_absorb_ask_raw") if "bn_absorb_ask_raw" in df.columns else np.zeros(len(df))
    # LONG : proche put wall (dist négatif petit) + gamma positif (HVL au-dessus, dist > 0)
    long_mask = (d_put > -0.01) & (d_put < -0.001) & (d_hvl > 0) & (absorb_bid == 1)
    sig[long_mask] = 1
    # SHORT : proche call wall + gamma positif
    short_mask = (d_call > 0.001) & (d_call < 0.01) & (d_hvl > 0) & (absorb_ask == 1)
    sig[short_mask] = -1
    return sig


def sb_v5(df):
    """SB GEX Flip Breakout adapté."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "dist_mq_hvl_pct", "delta_day_dir"):
        return sig
    d_hvl = _g(df, "dist_mq_hvl_pct")
    delta_dir = _g(df, "delta_day_dir")
    rvol = _g(df, "rvol", 1.0) if "rvol" in df.columns else np.ones(len(df))
    # SHORT : sous HVL forte (gamma negatif) + delta baissier + volume
    sig[(d_hvl < -0.005) & (delta_dir == -1) & (rvol > 1.0)] = -1
    sig[(d_hvl > 0.005) & (delta_dir == 1) & (rvol > 1.0)] = 1
    return sig


def sc_v5(df):
    """SC Delta div + GEX confluence."""
    sig = np.zeros(len(df), dtype=int)
    if "im_delta_day_divergence" not in df.columns:
        return sig
    div = _g(df, "im_delta_day_divergence")
    d_gex_up = _g(df, "dist_gex_nearest_up_pct", 1.0)
    d_gex_dn = _g(df, "dist_gex_nearest_dn_pct", -1.0)
    # SHORT : div positive (price up, delta down) + proche GEX up
    sig[(div > 0) & (d_gex_up < 0.002) & (d_gex_up > 0)] = -1
    # LONG : div negative + proche GEX dn
    sig[(div < 0) & (d_gex_dn > -0.002) & (d_gex_dn < 0)] = 1
    return sig


def sd_v5(df):
    """SD Absorption + GEX (utilise _raw + _at_level)."""
    sig = np.zeros(len(df), dtype=int)
    absorb_bid = _g(df, "bn_absorb_bid_at_level") if "bn_absorb_bid_at_level" in df.columns else _g(df, "bn_absorb_bid_raw")
    absorb_ask = _g(df, "bn_absorb_ask_at_level") if "bn_absorb_ask_at_level" in df.columns else _g(df, "bn_absorb_ask_raw")
    d_put_0 = _g(df, "dist_mq_put_0dte_pct", 1.0)
    d_call_0 = _g(df, "dist_mq_call_0dte_pct", 1.0)
    sig[(absorb_bid == 1) & (np.abs(d_put_0) < 0.005)] = 1
    sig[(absorb_ask == 1) & (np.abs(d_call_0) < 0.005)] = -1
    return sig


def se_v5(df):
    """SE VWAP + GEX regime."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "dist_mq_hvl_pct", "dist_vwap_d_atr"):
        return sig
    d_hvl = _g(df, "dist_mq_hvl_pct")
    x = _g(df, "dist_vwap_d_atr")
    gamma_pos = d_hvl > 0
    sig[gamma_pos & (x > 2.0)] = -1
    sig[gamma_pos & (x < -2.0)] = 1
    return sig


def sf_v5(df):
    """SF IB Breakout + GEX."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "ib_broken_up", "ib_broken_down"):
        return sig
    br_up = _g(df, "ib_broken_up")
    br_dn = _g(df, "ib_broken_down")
    d_hvl = _g(df, "dist_mq_hvl_pct") if "dist_mq_hvl_pct" in df.columns else np.zeros(len(df))
    delta_dir = _g(df, "delta_day_dir") if "delta_day_dir" in df.columns else np.zeros(len(df))
    sig[(br_dn == 1) & (d_hvl < 0) & (delta_dir == -1)] = -1
    sig[(br_up == 1) & (d_hvl > 0) & (delta_dir == 1)] = 1
    return sig


def sg_v5(df):
    """SG POC Defense (utilise dist_cur_vpoc_pct)."""
    sig = np.zeros(len(df), dtype=int)
    if "dist_cur_vpoc_pct" not in df.columns:
        return sig
    d_poc = _g(df, "dist_cur_vpoc_pct")
    tight = np.abs(d_poc) < 0.001  # 0.1%
    absorb_bid = _g(df, "bn_absorb_bid_raw") if "bn_absorb_bid_raw" in df.columns else np.zeros(len(df))
    absorb_ask = _g(df, "bn_absorb_ask_raw") if "bn_absorb_ask_raw" in df.columns else np.zeros(len(df))
    sig[tight & (absorb_bid == 1)] = 1
    sig[tight & (absorb_ask == 1)] = -1
    return sig


def sh_v5(df):
    """SH Composite Rotation (utilise vpoc absolu)."""
    sig = np.zeros(len(df), dtype=int)
    # Pas de dist_comp_20d_vpoc dans v5 — fallback sur dist_cur_vpoc_pct extreme
    if "dist_cur_vpoc_pct" not in df.columns:
        return sig
    d_poc = _g(df, "dist_cur_vpoc_pct")
    sig[d_poc > 0.01] = -1   # > 1% au-dessus VPOC → reversion
    sig[d_poc < -0.01] = 1   # < 1% sous VPOC → reversion
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# NOUVELLES STRATEGIES JACKSON 27/04
# ═══════════════════════════════════════════════════════════════════════════════

def jc_cluster_at_extreme(df):
    """JC — Cluster bid/ask sur high ou low (cluster_at_high/low actif)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "cluster_at_high", "cluster_at_low"):
        return sig
    high_cluster = _g(df, "cluster_at_high")
    low_cluster = _g(df, "cluster_at_low")
    # Cluster au low + delta dir up = rebond support
    delta_dir = _g(df, "delta_day_dir") if "delta_day_dir" in df.columns else np.zeros(len(df))
    sig[(low_cluster == 1) & (delta_dir >= 0)] = 1   # BUY rebond
    sig[(high_cluster == 1) & (delta_dir <= 0)] = -1 # SELL rejet
    return sig


def jc2_color_zone_break(df):
    """JC2 — Cassure zone color (price franchit zone color_up/dn)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct"):
        return sig
    d_up = _g(df, "dist_color_up_nearest_pct")
    d_dn = _g(df, "dist_color_dn_nearest_pct")
    # Très proche zone color_up (<0.05%) + cassure → BUY momentum
    near_up = (np.abs(d_up) < 0.0005)
    near_dn = (np.abs(d_dn) < 0.0005)
    delta_dir = _g(df, "delta_day_dir") if "delta_day_dir" in df.columns else np.zeros(len(df))
    sig[near_up & (delta_dir > 0)] = 1
    sig[near_dn & (delta_dir < 0)] = -1
    return sig


def jl_long_bar_continuation(df):
    """JL — Long up/dn bar continuation (Acosta long-bar pattern)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "long_up_bar", "long_dn_bar"):
        return sig
    long_up = _g(df, "long_up_bar")
    long_dn = _g(df, "long_dn_bar")
    # Long up bar + RTH = continuation BUY
    in_us = _g(df, "is_in_us_cash") if "is_in_us_cash" in df.columns else np.ones(len(df))
    sig[(long_up == 1) & (in_us == 1)] = 1
    sig[(long_dn == 1) & (in_us == 1)] = -1
    return sig


def jl2_long_reversal_pattern(df):
    """JL2 — Long up→dn reversal pattern (long up bar suivie inversion)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "long_up_dn_pattern", "long_dn_up_pattern"):
        return sig
    pat_ud = _g(df, "long_up_dn_pattern")  # long up suivi inversion baissière
    pat_du = _g(df, "long_dn_up_pattern")
    sig[pat_ud == 1] = -1  # SELL : long up bar puis reversal
    sig[pat_du == 1] = 1   # BUY : long dn bar puis reversal
    return sig


def ji_imbalance_extreme(df):
    """JI — Aggressor imbalance ou volume imbalance extreme."""
    sig = np.zeros(len(df), dtype=int)
    if "aggressor_imbalance" not in df.columns:
        return sig
    agg = _g(df, "aggressor_imbalance")
    # z-score-like, threshold 2 sigma
    sig[agg > 2.0] = 1
    sig[agg < -2.0] = -1
    return sig


def jd_div_cluster(df):
    """JD — Divergence cluster (n_delta_div_buy/sell_cluster_within_0_2pct > 0)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "n_delta_div_buy_cluster_within_0_2pct", "n_delta_div_sell_cluster_within_0_2pct"):
        return sig
    div_buy = _g(df, "n_delta_div_buy_cluster_within_0_2pct")
    div_sell = _g(df, "n_delta_div_sell_cluster_within_0_2pct")
    sig[div_buy >= 1] = 1   # cluster div buy proche → BUY
    sig[div_sell >= 1] = -1
    return sig


def je_edge_zone_fire(df):
    """JE — Edge zone fire (bar_edge_buy_fire / bar_edge_sell_fire)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "bar_edge_buy_fire", "bar_edge_sell_fire"):
        return sig
    fire_buy = _g(df, "bar_edge_buy_fire")
    fire_sell = _g(df, "bar_edge_sell_fire")
    sig[fire_buy == 1] = 1
    sig[fire_sell == 1] = -1
    return sig


def js_vol_spike(df):
    """JS — Volume spike + rvol extreme."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "vol_spike_up", "vol_spike_dn"):
        return sig
    spike_up = _g(df, "vol_spike_up")
    spike_dn = _g(df, "vol_spike_dn")
    sig[spike_up == 1] = 1
    sig[spike_dn == 1] = -1
    return sig


def jt_trapped_traders(df):
    """JT — Trapped buyers/sellers (n_trapped_*_cluster_within_0_2pct > 0)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct"):
        return sig
    trap_buy = _g(df, "n_trapped_buyers_cluster_within_0_2pct")
    trap_sell = _g(df, "n_trapped_sellers_cluster_within_0_2pct")
    # trapped buyers proches → SELL (ils vont sortir, vente)
    sig[trap_buy >= 1] = -1
    sig[trap_sell >= 1] = 1
    return sig


def jg_game_changers_dashboard(df):
    """JG — Composite Game Changers : open_type drive + open_bias_conf high + day_type trend."""
    sig = np.zeros(len(df), dtype=int)
    if not _has(df, "open_type", "open_bias_conf"):
        return sig
    conf = _g(df, "open_bias_conf")
    # open_type encoding
    open_t = df["open_type"]
    # day_type filter (si dispo)
    if "day_type" in df.columns:
        day_t = df["day_type"]
        if day_t.dtype == object:
            trend_day = day_t.str.contains("trend", case=False, na=False).values
        else:
            trend_day = (day_t > 0).values
    else:
        trend_day = np.ones(len(df), dtype=bool)

    if open_t.dtype == object:
        drive_up = open_t.str.contains("drive_up|odr_up", case=False, na=False).values
        drive_dn = open_t.str.contains("drive_dn|odr_dn", case=False, na=False).values
    else:
        drive_up = (open_t == 1).values
        drive_dn = (open_t == 2).values

    high_conf = conf > 0.6

    # Filtre first 90 minutes
    if "minutes_since_open" in df.columns:
        first_90 = (df["minutes_since_open"] >= 0).values & (df["minutes_since_open"] <= 90).values
    else:
        first_90 = np.ones(len(df), dtype=bool)

    sig[drive_up & high_conf & trend_day & first_90] = 1
    sig[drive_dn & high_conf & trend_day & first_90] = -1
    return sig


def jm_menthorq_confluence(df):
    """JM — Confluence MenthorQ : prix proche d'au moins 2 niveaux MQ."""
    sig = np.zeros(len(df), dtype=int)
    levels = ["dist_mq_put_0dte_pct", "dist_mq_call_0dte_pct", "dist_mq_hvl_pct",
              "dist_mq_put_pct", "dist_mq_call_pct"]
    available = [l for l in levels if l in df.columns]
    if len(available) < 3:
        return sig
    # Compter combien de niveaux à <0.3% du prix
    near_count = np.zeros(len(df), dtype=int)
    for lev in available:
        d = _g(df, lev)
        near = (np.abs(d) < 0.003).astype(int)
        near_count += near
    confluence = near_count >= 2
    delta_dir = _g(df, "delta_day_dir") if "delta_day_dir" in df.columns else np.zeros(len(df))
    sig[confluence & (delta_dir > 0)] = 1
    sig[confluence & (delta_dir < 0)] = -1
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRE COMPLET
# ═══════════════════════════════════════════════════════════════════════════════

HYPOTHESES_FULL = [
    # Originales (h1-h3 + h7-h8 marchent déjà sans modif)
    ("H1", "VWAP mean reversion (Dalton/Chan)", h1_vwap_reversion),
    ("H2", "Open Drive continuation (Dalton)", h2_open_drive),
    ("H3", "Failed IB Poor High (Crabel)", h3_failed_ib),
    # Adaptees v5
    ("H4", "1D Magnetism v5 (MenthorQ pinning)", h4_v5),
    ("H5", "Rejet VAH/VAL v5 (Dalton)", h5_v5),
    ("H6", "Divergence delta v5", h6_v5),
    ("H7", "Intermarket ES/NQ divergence", h7_intermarket_divergence),
    ("H8", "OFI residualise (Cont 2014)", h8_ofi_residualized),
    ("H9", "VPIN regime v5 (Easley-Lopez)", h9_v5),
    # SA-SH adaptées v5
    ("SA", "GEX Wall Fade v5 (SpotGamma)", sa_v5),
    ("SB", "GEX Flip Breakout v5", sb_v5),
    ("SC", "Delta Div + GEX v5 (Bookmap/Dale)", sc_v5),
    ("SD", "Absorption + GEX v5 (Acosta)", sd_v5),
    ("SE", "VWAP + GEX regime v5", se_v5),
    ("SF", "IB Breakout + GEX v5", sf_v5),
    ("SG", "POC Defense v5 (Acosta/Dalton)", sg_v5),
    ("SH", "Composite Rotation v5 (Dalton)", sh_v5),
    # Nouvelles Jackson 27/04
    ("JC", "Cluster at extreme (high/low)", jc_cluster_at_extreme),
    ("JC2", "Color zone break", jc2_color_zone_break),
    ("JL", "Long bar continuation", jl_long_bar_continuation),
    ("JL2", "Long reversal pattern", jl2_long_reversal_pattern),
    ("JI", "Imbalance extreme aggressor", ji_imbalance_extreme),
    ("JD", "Divergence cluster", jd_div_cluster),
    ("JE", "Edge zone fire", je_edge_zone_fire),
    ("JS", "Volume spike", js_vol_spike),
    ("JT", "Trapped traders cluster", jt_trapped_traders),
    ("JG", "Game Changers dashboard composite", jg_game_changers_dashboard),
    ("JM", "MenthorQ confluence 2+ niveaux", jm_menthorq_confluence),
]


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATOR + RUNNER (réutilise design strategy_battery_v5.py)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    direction: int
    entry_bar: int
    pnl_ticks: float
    won: bool
    date: Optional[str] = None
    hit_type: str = "unknown"


@dataclass
class SimResult:
    hypothesis: str
    trades: List[TradeResult] = field(default_factory=list)
    n_bars: int = 0
    n_days: int = 0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return sum(1 for t in self.trades if t.won) / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_ticks for t in self.trades)

    @property
    def gross_wins(self) -> float:
        return sum(t.pnl_ticks for t in self.trades if t.won)

    @property
    def gross_losses(self) -> float:
        return abs(sum(t.pnl_ticks for t in self.trades if not t.won))

    @property
    def profit_factor(self) -> float:
        if self.n_trades == 0:
            return float("nan")
        if self.gross_losses <= 0:
            return float("inf") if self.gross_wins > 0 else float("nan")
        return self.gross_wins / self.gross_losses

    @property
    def ev_per_trade(self) -> float:
        return self.total_pnl / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def trades_per_day(self) -> float:
        return self.n_trades / self.n_days if self.n_days > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        cumsum = np.cumsum([t.pnl_ticks for t in self.trades])
        peak = np.maximum.accumulate(cumsum)
        return float((peak - cumsum).max())

    @property
    def sharpe_daily(self) -> float:
        if self.n_trades < 5 or self.n_days < 5:
            return 0.0
        daily: Dict[str, float] = defaultdict(float)
        for t in self.trades:
            if t.date is not None:
                daily[t.date] += t.pnl_ticks
        arr = np.array(list(daily.values()), dtype=float)
        if len(arr) < 5 or arr.std() < 1e-6:
            return 0.0
        return float(arr.mean() / arr.std() * np.sqrt(252.0))


def simulate_forward(df, signal, hypothesis, symbol):
    closes = df["close"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date.values
    cost = COST_TICKS[symbol]
    trades = []
    last_bar = -COOLDOWN_BARS - 1
    daily_count = {}
    unique_days = set(dates.tolist())
    n = len(df)

    for i in range(n - HORIZON - 1):
        if signal[i] == 0:
            continue
        if i - last_bar < COOLDOWN_BARS:
            continue
        d = dates[i]
        if daily_count.get(d, 0) >= MAX_TRADES_PER_DAY:
            continue
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue

        sl_ticks = K_SL * atr_t
        tp_ticks = K_TP_RATIO * sl_ticks
        direction = int(signal[i])
        entry = closes[i]
        if not np.isfinite(entry):
            continue

        sl_pts = sl_ticks * TICK_SIZE
        tp_pts = tp_ticks * TICK_SIZE

        if direction == 1:
            tp_lvl = entry + tp_pts
            sl_lvl = entry - sl_pts
        else:
            tp_lvl = entry - tp_pts
            sl_lvl = entry + sl_pts

        exit_pnl = -cost
        hit_type = "time"
        for k in range(1, HORIZON + 1):
            j = i + k
            if j >= n:
                break
            h = highs[j]
            l = lows[j]
            if direction == 1:
                if l <= sl_lvl:
                    exit_pnl = -sl_ticks - cost
                    hit_type = "sl"
                    break
                if h >= tp_lvl:
                    exit_pnl = tp_ticks - cost
                    hit_type = "tp"
                    break
            else:
                if h >= sl_lvl:
                    exit_pnl = -sl_ticks - cost
                    hit_type = "sl"
                    break
                if l <= tp_lvl:
                    exit_pnl = tp_ticks - cost
                    hit_type = "tp"
                    break
        else:
            exit_close = closes[i + HORIZON] if (i + HORIZON) < n else entry
            exit_pnl = (exit_close - entry) / TICK_SIZE * direction - cost

        trades.append(TradeResult(
            direction=direction, entry_bar=i, pnl_ticks=float(exit_pnl),
            won=exit_pnl > 0, date=str(d) if d else None, hit_type=hit_type,
        ))
        last_bar = i
        daily_count[d] = daily_count.get(d, 0) + 1

    return SimResult(hypothesis=hypothesis, trades=trades, n_bars=n, n_days=len(unique_days))


def compute_verdict(sim, mc_p, pf_lo, bh_significant):
    if sim.n_trades < 30:
        return "NO-GO (n<30)"
    if not np.isfinite(sim.profit_factor) or sim.profit_factor < 1.3:
        return "NO-GO (PF<1.3)"
    if sim.win_rate < 0.35:
        return "NO-GO (WR<35%)"
    if sim.ev_per_trade < 1.0:
        return "NO-GO (EV<1t)"
    if np.isfinite(mc_p) and mc_p > 0.10:
        return "NO-GO (MC p>0.10)"
    if not bh_significant:
        return "CAUTION (not BH signif)"
    if np.isfinite(pf_lo) and pf_lo < 1.0:
        return "CAUTION (PF_lo<1)"
    if sim.profit_factor >= 1.5 and sim.win_rate >= 0.42 and np.isfinite(mc_p) and mc_p <= 0.05:
        return "GO"
    return "CAUTION"


def run_battery(symbol):
    print(f"\n{'='*70}")
    print(f"  BATTERY FULL — {symbol}")
    print(f"{'='*70}")
    df = pd.read_parquet(ROOT / f"DATA/datasets/{symbol}_dataset_v5.parquet")
    n_days = pd.to_datetime(df["ts"], unit="ms").dt.date.nunique()
    print(f"  {len(df):,} barres, {n_days} jours, {df.shape[1]} colonnes")
    print(f"  ATR median = {df['atr'].median():.2f}t  (SL ≈ {K_SL*df['atr'].median():.1f}t TP ≈ {K_SL*K_TP_RATIO*df['atr'].median():.1f}t)")

    results = []
    for code, name, func in HYPOTHESES_FULL:
        try:
            signal = func(df)
        except Exception as e:
            print(f"  [{code}] ERROR : {type(e).__name__}: {str(e)[:80]}")
            continue

        n_signals = int((signal != 0).sum())
        if n_signals < 10:
            print(f"  [{code}] {name[:40]:<40} — {n_signals} signaux (skip)")
            results.append({
                "code": code, "name": name, "symbol": symbol,
                "n_signals": n_signals, "n_trades": 0,
                "win_rate": 0, "profit_factor": float("nan"),
                "ev_per_trade": 0, "sharpe_daily": 0,
                "max_dd": 0, "trades_day": 0, "total_pnl": 0,
                "mc_p_value": float("nan"),
                "pf_ci_lo": float("nan"), "pf_ci_hi": float("nan"),
                "verdict": "NO-GO (features/signals)",
                "hit_tp": 0, "hit_sl": 0, "hit_time": 0,
            })
            continue

        sim = simulate_forward(df, signal, f"{code}: {name}", symbol)
        if sim.n_trades < 20:
            mc_p = float("nan")
            pf_lo, pf_hi = float("nan"), float("nan")
        else:
            mc_p = mc_permutation_shuffle_order(sim, n_iters=2000)
            pf_lo, pf_hi = bootstrap_pf_ci(sim, n_iters=1000)

        hit_tp = sum(1 for t in sim.trades if t.hit_type == "tp")
        hit_sl = sum(1 for t in sim.trades if t.hit_type == "sl")
        hit_time = sum(1 for t in sim.trades if t.hit_type == "time")

        results.append({
            "code": code, "name": name, "symbol": symbol,
            "n_signals": n_signals,
            "n_trades": sim.n_trades,
            "win_rate": sim.win_rate,
            "profit_factor": sim.profit_factor,
            "ev_per_trade": sim.ev_per_trade,
            "sharpe_daily": sim.sharpe_daily,
            "max_dd": sim.max_drawdown,
            "trades_day": sim.trades_per_day,
            "total_pnl": sim.total_pnl,
            "mc_p_value": mc_p,
            "pf_ci_lo": pf_lo, "pf_ci_hi": pf_hi,
            "hit_tp": hit_tp, "hit_sl": hit_sl, "hit_time": hit_time,
            "verdict": "TBD",
        })
        pf_str = f"{sim.profit_factor:.2f}" if np.isfinite(sim.profit_factor) else "inf"
        mc_str = f"{mc_p:.3f}" if np.isfinite(mc_p) else "n/a"
        print(f"  [{code:<3}] {name[:38]:<38} sig={n_signals:>6} trades={sim.n_trades:>5} "
              f"WR={sim.win_rate*100:>4.1f}% PF={pf_str:>5} EV={sim.ev_per_trade:+5.1f}t "
              f"Sharpe={sim.sharpe_daily:>5.2f} MC={mc_str}")

    # BH FDR
    pvals = [r["mc_p_value"] for r in results]
    bh_sig = benjamini_hochberg(pvals, alpha=0.05)
    for r, sig_bh in zip(results, bh_sig):
        if r["n_trades"] < 30:
            continue
        r["bh_significant"] = bool(sig_bh)
        fake_sim = type("FakeSim", (), {
            "n_trades": r["n_trades"],
            "profit_factor": r["profit_factor"],
            "win_rate": r["win_rate"],
            "ev_per_trade": r["ev_per_trade"],
        })()
        r["verdict"] = compute_verdict(fake_sim, r["mc_p_value"], r["pf_ci_lo"], sig_bh)

    return results


def main():
    print("=" * 70)
    print("STRATEGY BATTERY V5 FULL — 28 strategies (17 academiques + 11 Jackson)")
    print("=" * 70)
    print(f"  K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON}")
    print(f"  Baseline ML : ES BUY PF 1.11 / ES SELL PF 0.63")

    all_results = []
    for sym in ["ES", "NQ"]:
        try:
            all_results.extend(run_battery(sym))
        except Exception as e:
            print(f"\n[ERROR] {sym} : {type(e).__name__}: {e}")

    if not all_results:
        return

    # Save MD
    out_path = ROOT / "DOCS" / "STRATEGY_BATTERY_V5_FULL_REPORT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Strategy Battery V5 FULL — 28 strategies + ATR-dynamique\n\n")
        f.write(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Source** : ES/NQ_dataset_v5.parquet (24m, 351K bars)\n")
        f.write(f"**Triple Barrier** : K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON}\n")
        f.write(f"**Costs** : ES {COST_TICKS['ES']}t, NQ {COST_TICKS['NQ']}t\n\n")
        f.write("**Baseline ML v5** : ES BUY PF 1.11 / ES SELL PF 0.63\n\n")
        f.write("## Top par PF (n_trades >= 30, PF descendant)\n\n")
        f.write("| Rang | Code | Strategie | Sym | Trades | WR | PF | EV | Sharpe | MC_p | BH | Verdict |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
        sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
        for rank, r in enumerate(sortable, 1):
            pf = f"{r['profit_factor']:.2f}"
            mc = f"{r['mc_p_value']:.3f}" if np.isfinite(r["mc_p_value"]) else "n/a"
            bh = "✓" if r.get("bh_significant", False) else "✗"
            f.write(f"| {rank} | {r['code']} | {r['name']} | {r['symbol']} | "
                    f"{r['n_trades']} | {r['win_rate']*100:.1f}% | {pf} | "
                    f"{r['ev_per_trade']:+.1f}t | {r['sharpe_daily']:.2f} | "
                    f"{mc} | {bh} | {r['verdict']} |\n")
    print(f"\n[SAVED] {out_path}")

    # TOP 15 console
    print("\n" + "=" * 70)
    print("TOP 15 (PF descendant, n_trades >= 30)")
    print("=" * 70)
    sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
    sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
    for r in sortable[:15]:
        pf = f"{r['profit_factor']:.2f}"
        bh = "✓" if r.get("bh_significant", False) else "✗"
        print(f"  [{r['code']:<3}] {r['symbol']:<2} {r['name'][:42]:<42} | "
              f"trades={r['n_trades']:>5} WR={r['win_rate']*100:>4.1f}% PF={pf} "
              f"EV={r['ev_per_trade']:+5.1f}t Sharpe={r['sharpe_daily']:.2f} BH={bh} | {r['verdict']}")


if __name__ == "__main__":
    main()
