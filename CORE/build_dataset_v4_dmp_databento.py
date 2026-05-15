"""
build_dataset_v4_dmp_databento.py — dataset ML enrichi (Databento + DMP JSONL)

Sources:
  - OHLCV-1m : DATA/databento/GLBX.MDP3/ohlcv-1m/symbol={ES,NQ}.c.0/year=*/month=*/day=*/data_0.parquet
  - Trades   : DATA/databento/GLBX.MDP3/trades/symbol={ES,NQ}.c.0/year=*/month=*/day=*/data_0.parquet
               -> aggrege en 1-min via DuckDB (delta, CVD)
  - DMP MQ   : DATA/{ES,NQ}/YYYYMMDD_{ES,NQ}.jsonl
               -> 18 features mq_*, dist_mq_*, gex_*, blind_* (per-bar = pas de lag)

Output:
  DATA/datasets/v4_enriched/symbol={ES,NQ}.c.0/year=YYYY/month=MM/data.parquet

Plan agent corrections appliquees:
  1. LEFT JOIN OHLCV + Trades + DMP (pas inner) — keep all bars
  2. Trades aggressor: side='A' = buyer aggressive, side='B' = seller
  3. DMP MQ features: per-bar source = pas de lag 1j (vs JSON web)
  4. Roll detection par discontinuite instrument_id
  5. DuckDB streaming pour Trades aggregation (pas pandas)
  + CVD reset session CME (22:00 UTC)
  + mq_dist_*_atr clip ±10*ATR
  + Sort par ts_event avant write
  + Atomic write (.tmp -> rename)

Usage:
  python -X utf8 CORE/build_dataset_v4_dmp_databento.py --test-day 2026-04-01
  python -X utf8 CORE/build_dataset_v4_dmp_databento.py --start 2025-04-25 --end 2026-04-25
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo  # Python 3.9+ — DST-aware CVD reset

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DBN_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3"
DMP_ROOTS = {
    "ES": ROOT / "DATA" / "ES",
    "NQ": ROOT / "DATA" / "NQ",
    "MGC": ROOT / "DATA" / "MGC",  # 10/05/2026 : ajout Gold (DMP optionnel, peut etre vide)
}
OUT_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"

# 10/05/2026 — TICK_SIZE n'est PLUS une constante module (incompatible MGC=0.10).
# Utiliser get_tick_size(symbol) depuis CORE.constants. Avant : TICK_SIZE=0.25 hardcoded
# faussait toutes les distances *_pct sur MGC d'un facteur 2.5x.
# try/except : 2 conventions sys.path (ROOT/ via -m, vs CORE/ direct CLI)
try:
    from CORE.constants import get_tick_size, get_tick_value, get_databento_ticker  # noqa: E402
except ImportError:
    from constants import get_tick_size, get_tick_value, get_databento_ticker  # noqa: E402

# ============================================================
# ML training exclusions (audit ml-trainer 2026-04-25)
# ============================================================
# Ces colonnes sont presentes dans le Parquet pour reference/debug
# mais doivent etre EXCLUES du training LightGBM (sinon leakage)
ML_EXCLUDE_FEATURES = {
    # OHLCV bruts: prix absolus -> proxy temporel (prix monte = 2026, bas = 2025)
    "open", "high", "low", "close", "volume",
    "avg_price",  # = mean(price), proxy prix absolu
    # Metadata non-feature
    "ts_event", "year", "month", "day",
    "instrument_id",
    # bars_since_roll: valeur absolue >> 30000 = capture date implicite
    # (garder seulement days_since_roll = bars/1380 = plus interpretable)
    "bars_since_roll",
    # Quasi-NaN: 90% null meme en mars 2026 = inutilisable
    "dist_gex_nearest_dn_pct",
    # Collineaire avec dist_1d_min_ticks_pct (corr 0.875)
    "dist_1d_max_ticks_pct",
    # max_trade_size: stats bruite, peu d'edge
    "max_trade_size",
    # n_trades: collineaire avec volume (corr ~0.95 typique)
    "n_trades",
    # === Audit-6 fixes (2026-04-25) ===
    # vwap_offset_ticks: ratio fuite 4.47 (units differentes ES/NQ) - remplace par vwap_offset_pct
    "vwap_offset_ticks",
    # is_roll_day: quasi-constante 98.8% top_freq (4199/351K bars) - aucun signal
    "is_roll_day",
    # bar_no_trade: quasi-constante 100% top_freq (120/351K bars) - aucun signal
    "bar_no_trade",
    # range_size_pct: ratio fuite 1.07 (NQ vol > ES structurellement) + 88% NaN
    # collineaire avec position_in_range qui passe le critere
    "range_size_pct",
    # buy_vol / sell_vol: volumes absolus differents ES vs NQ
    # info preservee via delta_bar (=buy-sell) + cvd_session (cumul) + volume_z
    "buy_vol", "sell_vol",
    # dist_mq_hvl_pct: ratio fuite 0.501 (juste sur seuil) - bias regime ES/NQ structurel
    # info preservee via dist_mq_hvl_pct_z (z-score par symbole)
    "dist_mq_hvl_pct",

    # === Phase B audit (2026-04-26) - 31 features RED par quality-auditor ===
    # PRIX ABSOLUS (ratio NQ/ES = 3.7-4.7) : helpers internes pour game_changers/intermarket
    # mais pas pour ML (proxy instrument). Garder les NORMALISES (_pct, _atr, _z).
    "ib_high", "ib_low", "ib_range",
    "sess_high", "sess_low",
    "open_cash", "price_1030",
    "cur_vpoc", "cur_vah", "cur_val", "cur_pdh", "cur_pdl",
    "prev_vpoc", "prev_vah", "prev_val", "pdh", "pdl",
    # Ranges/distances en TICKS bruts (NQ x4 ES) : utiliser version _pct ou _atr
    "ib_range_ticks", "ib_atr",
    "dist_sess_high", "dist_sess_low",  # legacy ticks (remplace par _pct apres FIX 8)
    "range_size",  # points bruts
    # Bool features avec biais regime instrument-specifique
    "bool_above_mq_call", "bool_gex_flip_zone",
    # === Features DMP-C++ non-reproductibles Databento (15/05/2026) ===
    # Audit feature-engineer Review #4 : drift batch/stream si reactivees.
    # Stream produit proxies renames (diag_imbalance_ofi_proxy,
    # large_trader_max_size_proxy) disponibles gates uniquement.
    # ML_EXCLUDE explicite anti reintroduction accidentelle.
    "diag_imbalance", "large_trader_ratio",
    "ctx_diag_imbalance_mean_5", "ctx_large_trader_slope_5",
    # RVOL binaires mortes (>97% top_value_freq sur Databento, seuils SC mal calibres)
    # Rester : rvol, rvol_zscore, rvol_regime (vivants)
    "rvol_buy", "rvol_sell", "rvol_buy_strong", "rvol_sell_strong",
    "rvol_absorb_buy", "rvol_absorb_sell", "rvol_extreme",

    # === Phase B helpers session/dates (NON-features ML) ===
    "date_et", "mins_et", "session_date_trading",
    "is_cash_session", "is_ib_window",
    "ts",  # alias ts_event en epoch ms

    # === Phase B+ helpers (NON-features ML) ===
    # VWAP prix absolus + bandes (utiliser distance _pct uniquement)
    "vwap_d", "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d_sd2u", "vwap_d_sd2d", "vwap_d_sd3u", "vwap_d_sd3d",
    "vwap_w", "vwap_w_sd1u", "vwap_w_sd1d", "vwap_w_sd2u", "vwap_w_sd2d", "vwap_w_sd3u", "vwap_w_sd3d",
    "vwap_m", "vwap_m_sd1u", "vwap_m_sd1d", "vwap_m_sd2u", "vwap_m_sd2d", "vwap_m_sd3u", "vwap_m_sd3d",
    # Cash session HH/LL prix absolus (utiliser dist_cash_high/low_pct ML-usable)
    "cash_high", "cash_low",
    # OVN prix absolus + ticks bruts
    "ovn_high", "ovn_low", "ovn_range_ticks",
    # Opens prix absolus
    "open_830_et", "open_930_et",
    # bar_body_ticks (ticks bruts, NQ x4 ES)
    "bar_body_ticks",

    # === Phase B audit-2 (2026-04-26) - fuites volume absolu B+++ ===
    "max_size_buy", "max_size_sell",  # volume absolu bruts
    "max_cluster_volume", "p99_trade_size",  # idem
    "n_clusters",  # NQ x4 ES (seuil 250/20 different mais distribution differente)

    # === Phase B+ news flags binaires quasi-mortes (>99.9% zero) ===
    # On garde mins_since_news + mins_to_next_news (continus, signal exploitable)
    "is_news_715", "is_news_730", "is_news_830", "is_news_845", "is_news_900", "is_news_930",
    "within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
    "within_news_845_5m", "within_news_900_5m", "within_news_930_5m",

    # === Phase B+ Color/Long _fwd1 lookahead + tres rares (>99% zero) ===
    # Lookahead toxique pour ML + signal tres rare. Garder long_up_bar/long_dn_bar (>>5% fire).
    "bn_color_up_fwd1", "bn_color_dn_fwd1",
    "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
    "long_up_dn_fwd1", "long_dn_up_fwd1",

    # === Phase B+ long_up/dn_bar : seuil 9 ticks identique mais NQ x6 fire rate ES ===
    # A recalibrer per-symbole en Phase B+ v2 ou utiliser bar_body_pct (deja la, normalise).
    "long_up_bar", "long_dn_bar",

    # === Phase B audit-3 (2026-04-26) - 11 drops additionnels apres 2e tour quality-auditor ===
    # im_* avec seuils mal calibres (ticks bruts vs pct sess range)
    "im_price_ratio_slope_10",   # ratio vol NQ/ES = 13.75 + p99=0 outlier infini
    "im_smt_divergence",          # seuil ticks bruts non calibre + quasi-const ES 99.9% (31 fires/24K)
    # big_*_dominance : default 0.5 quand zero big orders -> 96.5% top_freq ES
    "big_buy_dominance", "big_sell_dominance",
    # n_big_*_t2..t4 : tier 2-4 ES quasi-mort (p99=0 -> outlier explosion + quasi-const)
    # On garde t1 (signal exploitable apres clip p99.5 dans train_lightgbm)
    "n_big_buy_t2",
    "n_big_buy_t3", "n_big_sell_t3", "n_big_t3",
    "n_big_buy_t4", "n_big_sell_t4", "n_big_t4",

    # === Phase B Bloc1+2 audit-4 (2026-04-26) - 2 agents specialistes review ===
    # Code-reviewer + quality-auditor 3eme tour : 19 features RED additionnelles
    # 1. ✅ LOOKAHEAD INTRA-JOUR RESOLU PHASE C (2026-04-27)
    #    Anciennement cur_vpoc/vah/val constants intraday (= EOD lookahead).
    #    Phase C value_area_running.py recalcule running cumsum par bar.
    #    LOOKAHEAD RESOLU. Mais cur_vpoc/vah/val EUX-MEMES restent EXCLUS car
    #    PRIX ABSOLUS (ES 6906 / NQ 25607 = leak instrument ratio 17, audit 27/04).
    #    Les versions normalisees dist_cur_*_pct sont ML-usables (GREEN).
    "cur_vpoc", "cur_vah", "cur_val", "cur_pdh", "cur_pdl",
    # NOTE : prev_vpoc/vah/val/pdh/pdl + dist_prev_*_pct restent OK (J-1, pas lookahead)
    # 2. FUITE INSTRUMENT (volume features absolus) (4)
    "n_ticks_bar",            # NQ x4 ES (8.5 vs 33.6) + ratio std 4.05
    "min_delta_bar",          # ES range [-5910, 159] / NQ similaire mais sera bug sans fix int64
    # max_delta_bar : ratio instrument 0.47 < 0.5, GARDE
    # 3. QUASI-CONSTANTES (8)
    "is_new_sess_high", "is_new_sess_low",  # 97-99% top_freq
    "is_new_cash_high", "is_new_cash_low",  # 98-99% top_freq
    "vwap_d_cross_up", "vwap_d_cross_dn",   # 97.9% top_freq (event rare bar exact cross)
    "vwap_d_sd2_below",                       # 96.9% top_freq
    "rotation_up", "rotation_dn",             # 95-96% top_freq
    # 4. NaN dominant + biais instrument
    "dist_big_ask_nearest_pct",   # 93% NaN ES + ratio instrument 0.54
    "dist_big_bid_nearest_pct",   # 92% NaN ES + ratio instrument 0.51
    # NOTE : dist_cluster_nearest_up/dn_pct GARDES (pas de fuite, NaN OK pour LightGBM)
    # NOTE : delta_change OK (std ratio 0.40, pas de fuite)
    # NOTE : max_delta_bar OK (instr 0.47, sous seuil)
    # NOTE : finish_pct_up + finish_strong_up/dn OK (ratio normalise [0,100])
    # NOTE : delta_div_buy/sell OK (signal rare valide, ~7-30% fire rate)
    # NOTE : vwap_d_sd1_above/below + sd2_above OK (top_freq 63-86%)

    # === Bloc 3 #1 Edge Zones audit-2 agents (2026-04-26) ===
    # Code-reviewer + quality-auditor : sur 8 features Edge Zones, 4 a DROP, 2 GREEN
    # 3 RED leak fuite instrument/volatilite structurelle :
    "dist_edge_buy_nearest_pct",   # INST 0.73 + VOL 3.22 (NQ tick%/ES tick% = 1/3.6 mecanique)
    "dist_edge_sell_nearest_pct",  # VOL 4.06 (NQ x4 ES)
    "n_edge_buy_active",           # INST 0.51 juste sur seuil + asymmetrie seuils per-symbole
    # 2 REDONDANCES (corr 0.94+ avec zone_size = fire + intensite combine) :
    "bar_edge_buy_fire",           # corr 0.94 avec bar_edge_buy_zone_size sur ES, 0.97 NQ
    "bar_edge_sell_fire",          # corr 0.95 avec bar_edge_sell_zone_size sur ES, 0.97 NQ
    # NOTE GARDES (3 GREEN ML-usable) :
    #   bar_edge_buy_zone_size, bar_edge_sell_zone_size : encode fire + intensite stack
    #   n_edge_sell_active : signal valide (asymmetrie buy/sell exempte naturellement)
    # TODO Phase C : z-score par symbol des dist_edge_* OU normalisation par ATR pour preserver signal

    # === Transforms TODO dans train_lightgbm.py (pas dans parquet) ===
    # df['n_big_buy_t1']  = df['n_big_buy_t1'].clip(upper=df['n_big_buy_t1'].quantile(0.995))
    # df['n_big_sell_t1'] = df['n_big_sell_t1'].clip(upper=df['n_big_sell_t1'].quantile(0.995))
    # df['n_big_t1']      = df['n_big_t1'].clip(upper=df['n_big_t1'].quantile(0.995))
    # df['n_big_sell_t2'] = df['n_big_sell_t2'].clip(upper=df['n_big_sell_t2'].quantile(0.99))
    # df['n_big_t2']      = df['n_big_t2'].clip(upper=df['n_big_t2'].quantile(0.99))
    # === EXEMPT (NATURALLY_DIFFERENT) ===
    # im_delta_day_divergence : anti-symetrie mathematique volontaire ES vs NQ

    # === Bloc 3 #6-12 + #8-10 audit (2026-04-27) - features added ===
    # BN #6 Absorption helpers internes
    # (raw + at_level + near_resistance/support sont GREEN, on les garde)
    # BN #7 Stack PUR : booleans GREEN (rare events)
    # BN #8 Big Orders v2 : gardes par tier (sauf max_*_vol_in_bar = volume absolu)
    "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",  # volume absolu = fuite instrument
    "n_big_ask_v2_t4", "n_big_bid_v2_t4",  # NQ toujours = 0 (tier 4 ES uniquement)
    # BN #9 Cluster Volume : max_cluster_volume_v2 = volume absolu
    "max_cluster_volume_v2",
    # BN #12 Delta Div Extension Lines : booleans + dist GREEN

    # === Bloc 3 #8-10 Sessions + Swings (2026-04-27) ===
    # PRIX ABSOLUS (ratio NQ/ES = 3.7-4.7) -> EXCLUDE ML, garder distances _pct
    "asia_high", "asia_low", "london_high", "london_low",
    "us_high", "us_low", "after_high", "after_low",
    "asia_open", "london_open", "ny_open", "after_open",
    # Helpers internes session metadata (non-features ML)
    "session_id", "session_date", "mins_et",
    # Swing helpers internes (PRIX absolus)
    "_last_swing_high_price", "_last_swing_low_price",
    # NOTE GARDES (ML-usable) :
    #   - is_in_asia/london/us_cash/us_after (booleans)
    #   - dist_*_high_pct, dist_*_low_pct (8 distances normalisees)
    #   - dist_*_open_pct, above_*_open (4+4 distances + booleans)
    #   - swing_high/low_active_lag10, dist_last_swing_*_pct, bars_since_last_swing_*
    #   - last_swing_high/low_session
    #   - liquidity_sweep_high/low_lag5, equal_highs/lows_detected
    #   - pct_in_range, premium_zone, discount_zone

    # === BN bonus Trapped Traders + Spike Origin (2026-04-27) ===
    # Toutes ML-usables a priori (booleans, counts, _pct normalises)
    # 10 Trapped : bn_trapped_buyers/sellers_raw, bn_trapped_*_at_resistance/support,
    #              n_trapped_*_zones_active, dist_trapped_*_nearest_pct,
    #              n_trapped_*_cluster_within_0_2pct
    # 5 Spike : spike_detected_lag3, n_spike_origins_active,
    #           dist_last_spike_origin_pct, bars_since_last_spike,
    #           n_spike_origins_cluster_within_0_2pct
    # En attente audit empirique post-backfill 24 mois (quasi-const + ratio instrument).

    # === Phase 1 rolling inputs V4-natif (2026-04-27) ===
    # HELPERS internes (POINTS, ticks bruts -> fuite instrument NQ x4 ES).
    # Utilises uniquement par market_profile_rolling.py pour calculer ctx_*.
    # PAS exposes au modele (les versions _pct ou _atr sont conservees comme features).
    "dist_vwap_d", "dist_ib_high", "dist_ib_low",
    "dist_sess_high", "dist_sess_low",
    "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val",
    "bar_high", "bar_low",  # aliases V1 de high/low
    "cvd_day",  # alias cvd_session
    "inside_cur_va",  # alias inside_value_area
    "va_position_pct",  # alias poc_position
    # FIX 27/04 (quality-auditor) : raw POINTS/bar -> fuite vol NQ 4x ES
    "vwap_slope_10",  # garder vwap_slope_10_atr ML
    # ctx_va_width / ctx_va_developing_10 raw POINTS aussi (fuite vol)
    "ctx_va_width", "ctx_va_developing_10",  # garder _atr ML
    # NOTE GARDES (ML-usable, normalises) :
    #   - atr (ticks, mais utilise via /atr ratios -> OK)
    #   - vwap_slope_10 (slope = direction normalisee)
    #   - vwap_d_side (binaire -1/0/+1)
    #   - dist_vwap_d_atr (normalise ATR)
    #   - ib_range_atr (normalise)
    #   - delta_day_dir (binaire)
    #   - momentum_5b (delta sum, OK)
    #   - poc_position (normalise [0,1])
    #   - ib_broken_down (binaire alias)
    #   - session (entier 0-3 categorial)

    # === Phase C VPOC running diagnostics (2026-04-27) ===
    # Helpers internes (count buckets + total volume cumule par session).
    "cur_va_n_buckets", "cur_va_total_vol",

    # === Phase D Dalton levels (2026-04-28) ===
    # HELPERS prix absolus (pVWAP veille) -> drop ML, garder dist_*_pct
    "pvwap", "pvwap_sd1u", "pvwap_sd1d",
    # HELPER ticks bruts (fuite instrument NQ x4 ES) -> drop ML, garder _atr
    "max_single_print_zone_width_ticks",

    # ═══════════════════════════════════════════════════════════════════════
    # === AUDIT ULTRATHINK 27/04/2026 — Option C+ DROP irrecuperables ===
    # 5 agents audit (code-reviewer + market-analyst + quality-auditor +
    # feature-engineer + ml-trainer) + Plan + 2 agents rescue.
    # Verdict consolide : DROP 39 features irrecuperables.
    # ═══════════════════════════════════════════════════════════════════════

    # 1. DOUBLONS PARFAITS / ALIAS (8 features)
    "bar_return",                # corr=1.0 avec bar_body_pct (meme calcul)
    "dist_us_high_pct",          # corr=-1.0 avec dist_cash_high_pct (signe inverse)
    "dist_us_low_pct",           # corr=1.0 avec dist_cash_low_pct
    "dist_open_930_pct",         # corr=1.0 avec dist_ny_open_pct
    "ib_broken_down",            # alias V1 redondant ib_broken_dn
    "dist_ovn_low_pct",          # corr=0.956 avec dist_asia_low_pct
    "dist_open_830_pct",         # corr=0.973 avec dist_open_930_pct (pre-market)
    "atr",                       # raw helper, ratio std NQ/ES=4.42 (oubli initial)

    # 2. NaN STRUCTUREL / DATA MANQUANTE (3 features)
    "im_ltr_slope_diff",         # 100% NaN (large_trader_ratio non dispo Databento)
    "days_since_roll",           # info temporelle linéaire, corr ES/NQ=1.0
    "im_smt_divergence",         # ES 99.93% zeros (seuils 10pts hardcodes)

    # 3. QUASI-CONSTANTES MORTES (2 features)
    "vwap_d_cross_up",           # top_freq 97.9% (event rare bar exact cross)
    "vwap_d_cross_dn",           # idem

    # 4. PHASE B+++ FORMULE SC OFFICIELLE — RE-INCLUS Sprint 1 Optuna 28/04 (Jackson decision)
    # Re-codage Databento 25-26/04 (phase_b_plus_plus_engine.py = Trades agreges).
    # Decision Jackson 28/04 00:35 : "ces feaute on les a recreees ce matin avec
    # Databento — re-include pour Optuna nuit". 18 features BN/Trapped/Absorb
    # exploitables re-introduites dans le ML pool. ATTENTION : les 4 _fwd1 RESTENT
    # exclus car LOOKAHEAD LEAK (regardent bar future = oracle).
    # ANCIENNE EXCLUSION (audit code-reviewer 27/04) commentee ci-dessous :
    #   "AVAP au prix EXACT du high donne 0 ASK volume 84% du temps NQ"
    # → vrai pour bn_absorb_*_raw rares (18-237 fires / 351K). Mais features
    # continues n_trapped_zones_active (60% bars) ont signal exploitable.
    # SHAP demain matin tranchera.
    # ---
    # "bn_absorb_ask_raw", "bn_absorb_ask_at_level",     # RE-INCLUS Sprint 1
    # "bn_absorb_bid_raw", "bn_absorb_bid_at_level",     # RE-INCLUS Sprint 1
    # "bn_stack_ask", "bn_stack_bid",                    # RE-INCLUS Sprint 1
    # "bn_trapped_buyers_raw", "bn_trapped_sellers_raw", # RE-INCLUS Sprint 1
    # "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",  # RE-INCLUS Sprint 1
    # FUITE INSTRUMENT post-fillna(100.0) 27/04 23:35 (audit quality-auditor) :
    # NQ trapped 97.1% / 96.2% v100 = LightGBM split "100.0 = NQ" pure instrument id.
    # Signal trapped preserve via n_trapped_*_zones_active + bn_trapped_*_raw.
    "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
    # "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",  # RE-INCLUS Sprint 1
    # "n_trapped_buyers_cluster_within_0_2pct",  # RE-INCLUS Sprint 1
    # "n_trapped_sellers_cluster_within_0_2pct", # RE-INCLUS Sprint 1
    # "rvol_absorb_buy", "rvol_absorb_sell",     # RE-INCLUS Sprint 1
    "near_resistance_level", "near_support_level",  # helpers internes Phase B+++ (rester exclus)

    # 5. BIG ORDERS TIER 3 (2 features) — events trop rares meme cote ES
    "n_big_ask_v2_t3", "n_big_bid_v2_t3",

    # 6. DELTA DIV STUCK + FUITE INSTRUMENT (4 features)
    "n_delta_div_buy_cluster_within_0_2pct",   # stuck 8578 bars (bug zones)
    "n_delta_div_sell_cluster_within_0_2pct",  # idem
    "dist_delta_div_buy_nearest_pct",          # drift ks=0.796 + corr ES/NQ=0.994
    "dist_delta_div_sell_nearest_pct",         # idem leak

    # 7. CLUSTER DRIFT NON-CORRIGEABLES (2 features)
    "dist_cluster_nearest_dn_pct",             # drift KS=0.679
    "dist_cluster_nearest_up_pct",             # drift KS=0.695

    # 8. NEWS TEMPORELS LINEAIRES (2 features)
    # feature-engineer : LightGBM tree-based scale-invariant -> log-transform
    # INUTILE. Garder mins_since_news raw uniquement si exemption explicite.
    # Decision Option C+ : DROP (peu de signal).
    "mins_since_news", "mins_to_next_news",

    # 9. CVD_5D_ROLLING ORIGINAL (sera remplace par cvd_5d_rolling_ffd)
    "cvd_5d_rolling",

    # 10. VWAP WEEKLY/MONTHLY RAW (10 features) — REPLACE par 5 differentiels
    # feature-engineer : sur 1 mois data, w==d quasi-redondant, sur 24m diverge.
    # Encoder DIVERGENCE comme feature interaction (vwap_w_minus_d_pct).
    "dist_vwap_w_pct", "dist_vwap_w_sd1u_pct", "dist_vwap_w_sd1d_pct",
    "dist_vwap_w_sd2u_pct", "dist_vwap_w_sd2d_pct",
    "dist_vwap_m_pct", "dist_vwap_m_sd1u_pct", "dist_vwap_m_sd1d_pct",
    "dist_vwap_m_sd2u_pct", "dist_vwap_m_sd2d_pct",

    # ═══════════════════════════════════════════════════════════════════════
    # === FINAL AUDIT quality-auditor 27/04 (Option C+ post fix) ===
    # 14 DROP additionnels apres validation finale
    # ═══════════════════════════════════════════════════════════════════════

    # 11. RANGE TICKS BRUTS (fuite vol NQ x4 ES, ratio 4.38-4.45)
    "range_h_minus_lprev_ticks", "range_hprev_minus_l_ticks",

    # 12. AFTER-HOURS RAW NaN 95.8% (couverts par _filled deja en ML)
    "dist_after_high_pct", "dist_after_low_pct", "dist_after_open_pct",

    # 13. PREMIUM_ZONE = 1 - DISCOUNT_ZONE (corr -0.989, doublon)
    "premium_zone",

    # 14. ATR_REGIME_ZSCORE_60D (corr 0.999 avec atr_14m_pct = doublon parfait)
    # Note : feature creee par feature-engineer rescue, mais quality-auditor a
    # detecte qu'elle est deja "captee" par atr_14m_pct.
    "atr_regime_zscore_60d",

    # 15. QUASI-CONSTANTES MORTES (top_freq > 95%)
    # quality-auditor verdict (overrides code-reviewer "event-based exemption") :
    # 9 features quasi-mortes a DROP (zero signal meme sur 24m).
    "cluster_at_high",                # NQ top_freq=100%
    "cluster_at_low",                 # NQ top_freq=100%
    "equal_highs_detected",           # 99% (override exemption)
    "equal_lows_detected",            # 99% (override exemption)
    "long_dn_up_pattern",             # 97%
    "long_up_dn_pattern",             # 97%
    "above_after_open",               # 98%

    # 16. FIX 3 ml-trainer (27/04) : roll_phase = info temporelle linéaire pure
    # Pas predictif, drift par construction, remplace par session_segment
    "roll_phase",

    # 17. FIX 27/04 (audit post-backfill 24m) : total_vol est un alias de volume
    # (deja en ML_EXCLUDE). Drop par intermarket sur certains mois cree
    # incoherence schema. Ajout en ML_EXCLUDE pour coherence cross-mois.
    "total_vol",

    # 18. CLUSTERING SPEARMAN 24m (27/04) - 8 doublons confirmes |corr|>0.95
    # Threshold 0.95 conservateur (sur 24m, vs 0.85 1mois trop agressif).
    # Pour chaque cluster, garder le representant avec plus de signal.
    "dist_prev_vah_pct",            # cluster avec dist_pvwap_sd1u_pct (=keep)
    "dist_prev_val_pct",            # cluster avec dist_pvwap_sd1d_pct (=keep)
    "dist_vwap_d_pct",              # cluster avec dist_vwap_d_atr (=keep, normalise)
    "is_in_us_cash",                # cluster avec session_segment (=keep)
    "n_cluster_groups",             # cluster avec max_cluster_size (=keep)
    "time_to_session_close_norm",   # cluster avec session_segment (=keep)
    "vol_zscore_20",                # cluster avec rvol_zscore (=keep)
    "volume_z",                     # cluster avec n_trades_z (=keep)

    # 19. LEAKAGE TARGET DETECTE 27/04 : sorties Triple Barrier dans labeler V4
    # realized_pts = PnL realise simulation Triple Barrier (= TARGET, pas feature)
    # exit_offset = nb bars avant TP/SL touche (= TARGET, pas feature)
    # Inclus comme metadata mais NE DOIVENT PAS arriver dans X_train.
    # IMPORTANCE GUARD a detecte : Top1 realized_pts 13.9%, WR=100%, PF=inf.
    "realized_pts", "exit_offset",

    # 20. LOOKAHEAD SWINGS/SWEEP (quality-auditor 27/04) - fenetre CENTRES = futur
    # swing_high_active_lag10 : high[i-10:i+11] -> 10 bars futures
    #   Empirique : fire 1.78% des bars, mais label=-1 a 78.5% quand fire
    #   = predictor trivial du label, leak total
    # liquidity_sweep_*_lag5 : close[i+5] consulte explicitement
    "swing_high_active_lag10", "swing_low_active_lag10",
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
    # Derivees contaminees (utilisent _last_swing_*_price update via lookahead)
    "dist_last_swing_high_pct", "dist_last_swing_low_pct",
    "bars_since_last_swing_high", "bars_since_last_swing_low",
    "last_swing_high_session", "last_swing_low_session",

    # === 2026-04-28 ml-trainer audit pre-Optuna (Group 21) ===
    # Rules tags V1+V2 quasi-constantes (top_freq 99.7-100% car fires rares 0.03-2%)
    # Risque memorisation rare events si min_child_samples=10.
    # Decision Sprint 1 : DROP du ML training, garder dans paper_trader snapshot
    # pour analyse comportementale + meta-labeling Sprint 2 (post-validation primary).
    # Cf ml-trainer agent verdict NOGO/3-fixes 28/04/2026 00:30.
    # 9 V1 rules (rule_*_dir + rule_*_strength = 18 cols)
    "rule_long_up_bar_dir", "rule_long_up_bar_strength",
    "rule_long_dn_bar_dir", "rule_long_dn_bar_strength",
    "rule_color_up_proximity_dir", "rule_color_up_proximity_strength",
    "rule_color_dn_proximity_dir", "rule_color_dn_proximity_strength",
    "rule_color_zone_break_dir", "rule_color_zone_break_strength",
    "rule_cluster_at_high_dir", "rule_cluster_at_high_strength",
    "rule_cluster_at_low_dir", "rule_cluster_at_low_strength",
    "rule_failed_ib_poor_high_dir", "rule_failed_ib_poor_high_strength",
    "rule_edge_zone_fire_dir", "rule_edge_zone_fire_strength",
    # 3 V2 rules pullback (rule_*_dir + rule_*_strength = 6 cols)
    "rule_pullback_continuation_buy_dir", "rule_pullback_continuation_buy_strength",
    "rule_pullback_continuation_sell_dir", "rule_pullback_continuation_sell_strength",
    "rule_pullback_mq_hvl_buy_dir", "rule_pullback_mq_hvl_buy_strength",

    # === 2026-04-28 Audit NaN temporal drift (Group 22) ===
    # 14 features MenthorQ/GEX/Blind avec NaN drift > 20% avant/apres date_median.
    # Cause : MQ data scrapee tardivement (100% NaN avant 2025-10-23).
    # Risque : LightGBM cree split is_nan(MQ) = proxy date "post 2025-10" = leak temporel.
    # Mandate ml-trainer audit pre-Optuna 28/04/2026 00:30 (NOGO sans ce fix).
    # Re-evaluation v6 attendue post-purge MQ complet (juin 2026 selon memoire
    # feedback_ml_features.md). Voir DOCS/AUDIT_NAN_TEMPORAL_DRIFT.md.
    "bool_above_mq_hvl",
    "dist_1d_min_ticks_pct",
    "dist_blind_nearest_dn_pct",
    "dist_blind_nearest_up_pct",
    "dist_gex_nearest_up_pct",
    "dist_mq_call_0dte_pct",
    "dist_mq_call_pct",
    "dist_mq_hvl_pct_z",
    "dist_mq_put_0dte_pct",
    "dist_mq_put_pct",
    "dist_vix_gex_nearest_dn",
    "dist_vix_gex_nearest_up",
    "gex_cluster_count_z",
    "position_in_range",

    # === 2026-05-13 nuit : LEAK DMP MOMENTUM CONFIRME ===
    # Decouvert via meta-audit tools/meta_audit_leak_features.py 13/05/2026 :
    # rho(momentum_3b, futur close_t+1) = 0.444 (n=29635 bars ES avril 2026)
    # Une feature qui correle 0.44 avec le retour de la barre SUIVANTE EST
    # MATHEMATIQUEMENT un look-ahead leak (aucune formule causale honnete ne
    # peut atteindre rho_fut1 > 0.05). Test empirique sur 11 variantes Python
    # causales : max |rho| = 0.02 (cf tools/backtest_momentum_variants.py).
    # CAUSE PROBABLE : timing capture r.price_close Sierra (event-driven) peut
    # inclure 1-tick forward vs Databento OHLCV close strict per-minute boundary.
    # Localisation code DMP : CPP/MIA_REFACTORED/DUMPER/DMP_Pipeline.h:266-286
    # (NOT DMP_Main.cpp:436 comme initialement diagnostique).
    # ACTION downstream : CORE/primary_models/blind_level_fade.py utilise
    # momentum_3b. A remplacer par close.diff(N) Python honnete quand pipeline
    # V4 sera entierement Databento (Chantier 3 Live Enricher).
    "momentum_3b",
}


def get_ml_features(df: pd.DataFrame) -> list:
    """Retourne la liste des colonnes utilisables en ML (apres exclusion leakage)."""
    return [c for c in df.columns if c not in ML_EXCLUDE_FEATURES]

# Fields utiles a extraire du DMP JSONL (per-bar source MenthorQ + regime).
#
# 03/05/2026 (Jackson — Plan B regime_engine partage) : extension de 17 -> 45
# features pour permettre detection regime cote pipeline V4. Code-reviewer GO-RESERVES :
#   - DROP : delta_day, sess_range_ticks, ib_range_ticks (vol leak instrument)
#   - REMPLACES : delta_day_dir (binaire), sess_range_atr (deja inclus),
#                 ib_formed_bool (derivee dans add_ohlc_derived_features)
#   - 22 features ajoutees passent quality_validator V2 (cf CORE/quality_validator.py
#     extension NATURALLY_DIFFERENT + EVENT_BASED 03/05).
#
# Source unique de verdict regime : CORE/regime_engine.py compute_regime_dict()
# applique sur chaque bar -> ajoute 7 colonnes regime_* au output V4.
DMP_MQ_FIELDS = [
    "ts",
    # === MenthorQ Options (existant - 17 features) ===
    "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
    "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
    "dist_1d_min_ticks", "dist_1d_max_ticks",
    "dist_gex_nearest_up", "dist_gex_nearest_dn",
    "dist_blind_nearest_up", "dist_blind_nearest_dn",
    "gex_cluster_count",
    "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
    "dist_vix_gex_nearest_up", "dist_vix_gex_nearest_dn",
    # === Regime Market Profile (10) — Steidlmayer/Dalton categoriels ===
    "day_type", "open_type", "open_direction", "open_bias_conf",
    "profile_shape", "trend_day_probability",
    "single_print_count", "poc_bar_dist", "bars_in_va", "range_pos",
    # === IB / Session (4 features safe — DROP ib_range_ticks vol leak) ===
    "ib_broken_up", "ib_broken_down",
    "ib_range_ticks",  # garde TEMPORAIREMENT pour calculer ib_formed_bool, drop apres regime calc
    "sess_range_atr",  # ratio deja normalise (vs sess_range_ticks DROP)
    # === VWAP MTF (5 features — DROP vwap_m_side quasi-const) ===
    "vwap_slope_10", "vwap_slope_30",
    "vwap_d_side", "vwap_w_side",
    "vwap_triple_align", "vwap_ma_align",
    # === Momentum (3) ===
    "momentum_3b", "momentum_5b", "ma_trend",
    # === VIX (2) ===
    "vix_level", "vix_regime",
    # === OrderFlow CVD (3 features — DROP delta_day vol leak) ===
    "delta_day_dir",  # binaire (vs delta_day cumul = vol leak)
    "cvd_day_dir", "delta_divergence",
]


# ============================================================
# Loaders
# ============================================================
def load_ohlcv(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Load OHLCV-1m Databento via DuckDB.

    FIX BUG TIMEZONE 26/04/2026 : SET TimeZone='UTC' OBLIGATOIRE.
    Sans ca, sur Windows TZ Paris, DuckDB strip tz et decale les bars de +2h
    (DST ete) ou +1h (DST hiver). Tout le dataset etait corrompu.
    """
    # Chantier 5bis (10/05/2026) : utilise get_databento_ticker pour MGC.v.0
    # (evite bug MGC.c.0 rollover qui tronquait 50% des bars).
    db_ticker = get_databento_ticker(symbol)
    pattern = (DBN_ROOT / "ohlcv-1m" / f"symbol={db_ticker}" / "**" / "*.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC';")  # CRITIQUE : preserve UTC
        df = con.execute(f"""
            SELECT
                ts_event::TIMESTAMP AS ts_event,
                open, high, low, close, volume,
                instrument_id
            FROM read_parquet('{pattern}', hive_partitioning=true)
            WHERE ts_event >= TIMESTAMP '{start.isoformat()}'
              AND ts_event <  TIMESTAMP '{(end + timedelta(days=1)).isoformat()}'
            ORDER BY ts_event
        """).fetchdf()
    except Exception as e:
        print(f"  [WARN] OHLCV load failed for {symbol}: {e}")
        return pd.DataFrame()
    finally:
        con.close()
    return df


def aggregate_trades_1min(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Aggregate Trades to 1-min via DuckDB streaming.

    FIX BUG TIMEZONE 26/04/2026 : idem, SET TimeZone='UTC'.
    """
    # Chantier 5bis (10/05/2026) : ticker per-symbole (MGC.v.0 vs ES.c.0/NQ.c.0)
    db_ticker = get_databento_ticker(symbol)
    pattern = (DBN_ROOT / "trades" / f"symbol={db_ticker}" / "**" / "*.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC';")  # CRITIQUE : preserve UTC
        # Convention Databento: side='A' = aggressor BUYER lifted offer
        #                      side='B' = aggressor SELLER hit bid
        df = con.execute(f"""
            SELECT
                date_trunc('minute', ts_event::TIMESTAMP) AS ts_event,
                SUM(CASE WHEN side='A' THEN size ELSE 0 END)::BIGINT AS buy_vol,
                SUM(CASE WHEN side='B' THEN size ELSE 0 END)::BIGINT AS sell_vol,
                (SUM(CASE WHEN side='A' THEN size ELSE 0 END)
                 - SUM(CASE WHEN side='B' THEN size ELSE 0 END))::BIGINT AS delta_bar,
                COUNT(*)::BIGINT AS n_trades,
                AVG(price)::DOUBLE AS avg_price,
                MAX(size)::BIGINT AS max_trade_size
            FROM read_parquet('{pattern}', hive_partitioning=true)
            WHERE ts_event >= TIMESTAMP '{start.isoformat()}'
              AND ts_event <  TIMESTAMP '{(end + timedelta(days=1)).isoformat()}'
              AND size > 0
            GROUP BY 1
            ORDER BY 1
        """).fetchdf()
    except Exception as e:
        print(f"  [WARN] Trades aggregation failed for {symbol}: {e}")
        return pd.DataFrame()
    finally:
        con.close()
    return df


def load_dmp_jsonl(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Load mq_* features from DMP JSONL files (per-bar = pas de lag)."""
    dmp_dir = DMP_ROOTS[symbol]
    rows = []
    cur = start
    while cur <= end:
        ymd = cur.strftime("%Y%m%d")
        fpath = dmp_dir / f"{ymd}_{symbol}.jsonl"
        if fpath.exists() and fpath.stat().st_size > 1000:  # skip empty files
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        try:
                            d = json.loads(line)
                            row = {k: d.get(k) for k in DMP_MQ_FIELDS}
                            rows.append(row)
                        except Exception:
                            continue
            except Exception as e:
                print(f"  [WARN] DMP read {fpath.name}: {e}")
        cur += timedelta(days=1)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None).dt.floor("min")
    df = df.drop(columns=["ts"])
    # De-dup if duplicates par minute (DMP peut ecrire 2 lignes)
    df = df.groupby("ts_event").last().reset_index()
    return df


# ============================================================
# Features derivees
# ============================================================
def add_session_cvd(df: pd.DataFrame) -> pd.DataFrame:
    """
    CVD reset par session CME globex (17:00 CT = 22:00 UTC ete, 23:00 UTC hiver).
    FIX BUG #2 (audit 2026-04-25): convention DST-aware via zoneinfo America/Chicago,
    sinon decalage 1h pendant 6 mois/an (hiver) = sessions cassees.
    """
    if df.empty or "delta_bar" not in df.columns:
        return df

    # Convertir ts UTC -> America/Chicago (gere DST automatiquement)
    ts_utc = pd.to_datetime(df["ts_event"], utc=True)
    ts_chi = ts_utc.dt.tz_convert(ZoneInfo("America/Chicago"))
    # Session = jour qui commence a 17:00 CT (open globex Chicago time)
    # Soustraire 17h pour aligner sur "session day" puis prendre la date
    session_day = (ts_chi - pd.Timedelta(hours=17)).dt.date
    df = df.assign(session_id=session_day.astype(str))
    df["cvd_session"] = df.groupby("session_id")["delta_bar"].cumsum()

    # FIX 27/04 (audit ULTRATHINK + feature-engineer rescue) :
    # Remplacer cvd_5d_rolling brut (drift KS=0.806 + bug min_periods=1 ramp-up
    # artificiel) par Fractional Differentiation Lopez AFML ch.5 sur cvd_session.
    # FFD preserve memoire stationnaire sans warm-up agressif.
    # d=0.4 : compromis preservation memoire (0.5 max) vs stationnarite (0.0 min).
    df["cvd_5d_rolling_ffd"] = _fractional_diff(df["cvd_session"], d=0.4, threshold=1e-4).astype("float32")

    df = df.drop(columns=["session_id"])
    return df


def _fractional_diff(series: pd.Series, d: float = 0.4, threshold: float = 1e-4) -> pd.Series:
    """
    Fractional Differentiation Lopez AFML ch.5 (fixed-width window).

    Calcule la serie diff fractionnaire d entre 0 et 1 : preserve la memoire
    de la serie originale tout en la rendant stationnaire (passe ADF test).

    Args:
        series : pd.Series (cumul ou prix)
        d      : ordre fractionnaire (0.0 = identite, 1.0 = diff classique)
        threshold : poids min |w_k| (truncate window)

    Returns:
        pd.Series FFD'ed (NaN sur warm-up = len(weights))
    """
    # Compute weights iteratively : w_k = -w_{k-1} * (d - k + 1) / k
    weights = [1.0]
    k = 1
    while True:
        w_k = -weights[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        weights.append(w_k)
        k += 1
    weights = np.array(weights[::-1])  # convolve order : reverse
    width = len(weights)

    n = len(series)
    out = np.full(n, np.nan)
    values = series.values
    for i in range(width - 1, n):
        window = values[i - width + 1: i + 1]
        if np.isnan(window).any():
            continue
        out[i] = np.dot(weights, window)
    return pd.Series(out, index=series.index)


def detect_roll(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag is_roll_day par discontinuite instrument_id (Plan agent recommandation).
    FIX BUG #1 (audit 2026-04-25): bars_since_roll = NaN avant le 1er roll observe
    (pas de reference roll = valeur n'a pas de sens). Ajout days_since_roll
    pour interpretabilite ML (vs bars brutes).
    """
    if df.empty or "instrument_id" not in df.columns:
        df["is_roll_day"] = 0
        df["bars_since_roll"] = pd.NA
        df["days_since_roll"] = pd.NA
        return df
    df = df.copy()
    df["is_roll"] = (df["instrument_id"] != df["instrument_id"].shift(1)).astype(int)
    df.loc[df.index[0], "is_roll"] = 0  # premier bar pas un roll
    # Day-level flag (max par jour)
    df["is_roll_day"] = df.groupby(
        pd.to_datetime(df["ts_event"], utc=True).dt.date
    )["is_roll"].transform("max")
    # Bars since last roll : group by cumsum (chaque groupe = bars entre 2 rolls)
    group_id = df["is_roll"].cumsum()
    # FIX POST-AUDIT-2: forcer dtype Int64 nullable pour eviter coercion object
    df["bars_since_roll"] = df.groupby(group_id).cumcount().astype("Int64")
    # Avant le 1er roll observe : NaN (pas de reference)
    mask_no_roll_yet = (group_id == 0)
    df.loc[mask_no_roll_yet, "bars_since_roll"] = pd.NA
    # days_since_roll = bars / 1380 (1380 bars/jour TRADING, weekends arretent compteur)
    # Renomme implicite : c'est trading_days_since_roll pas calendar_days
    df["days_since_roll"] = (df["bars_since_roll"].astype("Float64") / 1380).round(2)
    df = df.drop(columns=["is_roll"])
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ATR-14 sur bars 1-min."""
    if df.empty:
        return df
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_pclose = (df["high"] - df["close"].shift(1)).abs()
    low_pclose = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_pclose, low_pclose], axis=1).max(axis=1)
    df["atr_14m"] = tr.rolling(window=period, min_periods=1).mean()
    return df


def add_ohlc_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sauve les colonnes OHLC + avg_price + 1d_max via transformations relatives.
    FIX audit ml-trainer 2026-04-25: au lieu de DROP, on PRESERVE l'info
    via features derivees non-leakage.
    """
    if df.empty:
        return df

    # 1. Bar shape features (OHLC -> ratios relatifs au close)
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        df["bar_return"] = (df["close"] / df["open"] - 1).clip(-0.05, 0.05)
        df["bar_range_pct"] = ((df["high"] - df["low"]) / df["close"] * 100).clip(0, 5)
        df["bar_body_pct"] = ((df["close"] - df["open"]) / df["close"] * 100).clip(-3, 3)
        df["bar_upper_wick_pct"] = ((df["high"] - df[["open", "close"]].max(axis=1)) / df["close"] * 100).clip(0, 3)
        df["bar_lower_wick_pct"] = ((df[["open", "close"]].min(axis=1) - df["low"]) / df["close"] * 100).clip(0, 3)

    # 2. avg_price (VWAP du bar) -> offset en POURCENTAGE du close (audit-6 fix)
    # Avant: _ticks bruts (ratio fuite 4.47 car NQ ticks/bar 4x plus gros que ES)
    # Apres: _pct comparable entre instruments (ratio < 0.01)
    if "avg_price" in df.columns and "close" in df.columns:
        df["vwap_offset_pct"] = ((df["avg_price"] - df["close"]) / df["close"] * 100).clip(-0.5, 0.5)

    # 3. bars_since_roll -> roll_phase categoriel (anti-fuite valeur absolue)
    if "days_since_roll" in df.columns:
        # 0=early (0-15j), 1=mid (15-45j), 2=late (45+j), NaN si pas de roll observe
        df["roll_phase"] = pd.cut(
            df["days_since_roll"],
            bins=[-0.01, 15, 45, 999],
            labels=[0, 1, 2],
        ).astype("Float64")  # Float64 pour preserver NaN

    # 4. position_in_range (combine 1d_min + 1d_max sans collinearite)
    if all(c in df.columns for c in ["dist_1d_min_ticks_pct", "dist_1d_max_ticks_pct"]):
        # close - 1d_min en pct = -dist_1d_min (car dist_min est negatif)
        # 1d_max - close en pct = dist_1d_max
        # range = dist_1d_max - dist_1d_min (= taille range jour)
        # position = (-dist_1d_min) / range = ou se trouve close dans le range journalier (0=bas, 1=haut)
        range_size = df["dist_1d_max_ticks_pct"] - df["dist_1d_min_ticks_pct"]
        df["range_size_pct"] = range_size.clip(0, 10)  # range journalier en %
        # position 0-1 (close vs range)
        df["position_in_range"] = ((-df["dist_1d_min_ticks_pct"]) / range_size).clip(0, 1)

    # 4bis. dist_mq_hvl_pct: z-score par symbole pour eliminer borderline 0.501
    # ES tend a etre plus pres du HVL que NQ (bias regime structurel)
    # Z-score normalise sur la distribution propre a chaque symbole
    if "dist_mq_hvl_pct" in df.columns:
        hvl_vals = df["dist_mq_hvl_pct"].dropna()
        if len(hvl_vals) > 100 and hvl_vals.std() > 0:
            df["dist_mq_hvl_pct_z"] = ((df["dist_mq_hvl_pct"] - hvl_vals.mean()) / hvl_vals.std()).clip(-5, 5)

    # 5. n_trades / volume normalises (z-score par symbole pour eliminer fuite instrument)
    if "n_trades" in df.columns:
        n_vals = df["n_trades"].dropna()
        if len(n_vals) > 100 and n_vals.std() > 0:
            df["n_trades_z"] = ((df["n_trades"] - n_vals.mean()) / n_vals.std()).clip(-5, 5)
    if "volume" in df.columns:
        v_vals = df["volume"].dropna()
        if len(v_vals) > 100 and v_vals.std() > 0:
            df["volume_z"] = ((df["volume"] - v_vals.mean()) / v_vals.std()).clip(-5, 5)
    if "max_trade_size" in df.columns:
        m_vals = df["max_trade_size"].dropna()
        if len(m_vals) > 100 and m_vals.std() > 0:
            df["max_trade_size_z"] = ((df["max_trade_size"] - m_vals.mean()) / m_vals.std()).clip(-5, 5)

    return df


def add_pct_normalized_distances(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """
    Features distances en POURCENTAGE du prix (vs ATR-norm).
    FIX BUG #4-5-6 (audit 2026-04-25):
      - ATR 1min trop petit pour normaliser distances macro (call wall = 370 ticks
        / ATR 2pts = 185x = clip a 10 dans 99% des cas = feature MORTE).
      - Ratio prix (ticks * tick_size / close * 100) = % du prix = comparable
        entre ES (~6500) et NQ (~25000) => elimine fuite instrument.
      - Pas de clip car distances en % naturellement bornees (~5% max).
    FIX POST-AUDIT-2: DROP les colonnes brutes ticks apres calcul _pct
      (sinon ML voit les deux versions et apprend la fuite via brut).
    FIX MGC (10/05/2026) : tick_size lookup par symbole (0.10 pour MGC vs 0.25 ES/NQ).
      Sans ce fix, MGC dist_*_pct etait sous-estime d'un facteur 2.5x.

    Args:
        df: DataFrame avec colonnes dist_*_ticks et close.
        symbol: ES, NQ, MGC, ... pour lookup tick_size correct.
    """
    if df.empty or "close" not in df.columns:
        return df
    tick_size = get_tick_size(symbol)
    # Distances en ticks brutes ES/NQ a normaliser en pct du prix
    # NOTE: dist_vix_gex_* sont en POINTS VIX (pas ticks ES) -> exclues, gardees brutes
    # NOTE: dist_mq_hvl_0dte ajoute schema 3.7.9 (24/04/2026), historique vide mais forward OK
    fields_to_normalize = [
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
        "dist_1d_min_ticks", "dist_1d_max_ticks",
        "dist_gex_nearest_up", "dist_gex_nearest_dn",
        "dist_blind_nearest_up", "dist_blind_nearest_dn",
        # dist_vix_gex_*: EXCLUES (en points VIX, pas ticks ES) -> gardees brutes
    ]
    cols_to_drop_after = []
    for field in fields_to_normalize:
        if field in df.columns and df[field].notna().any():
            # ticks * tick_size = points; / close * 100 = pourcentage du prix
            df[f"{field}_pct"] = (df[field] * tick_size / df["close"]) * 100
            cols_to_drop_after.append(field)
    # ATR aussi en pourcentage (vs valeur absolue qui differe ES/NQ)
    if "atr_14m" in df.columns:
        df["atr_14m_pct"] = (df["atr_14m"] / df["close"]) * 100
        cols_to_drop_after.append("atr_14m")  # drop apres calcul du _pct
    # DROP les versions brutes (anti-fuite instrument confirmed audit-2)
    df = df.drop(columns=cols_to_drop_after, errors="ignore")

    # Clip outliers physiquement absurdes (artefacts roll gap)
    # FIX BUG #A audit-4: utilise .mask() qui PRESERVE NaN (vs .where() qui transformait NaN -> 0)
    # dist_*_put_*_pct ne peut PAS etre positive (put_support est sous le prix)
    for col in ["dist_mq_put_pct", "dist_mq_put_0dte_pct"]:
        if col in df.columns:
            df[col] = df[col].mask(df[col] > 0, 0)
    # dist_*_call_*_pct ne peut PAS etre negative (call_resistance est au-dessus)
    for col in ["dist_mq_call_pct", "dist_mq_call_0dte_pct"]:
        if col in df.columns:
            df[col] = df[col].mask(df[col] < 0, 0)
    return df


# ============================================================
# Build orchestrator
# ============================================================
def build_for_symbol(symbol: str, start: date, end: date,
                      use_mq_lite: bool = False) -> pd.DataFrame:
    print(f"\n{'='*70}")
    print(f"  {symbol} — {start} -> {end}  {'(MQ_Lite source)' if use_mq_lite else '(DMP JSONL source)'}")
    print(f"{'='*70}")
    t0 = time.time()

    # 1. OHLCV
    print("  [1/6] Load OHLCV Databento...")
    ohlcv = load_ohlcv(symbol, start, end)
    print(f"        {len(ohlcv)} bars")
    if ohlcv.empty:
        print(f"  [SKIP] No OHLCV for {symbol}")
        return pd.DataFrame()

    # 2. Trades aggregated 1-min
    print("  [2/6] Aggregate Trades 1-min...")
    trades = aggregate_trades_1min(symbol, start, end)
    print(f"        {len(trades)} 1-min bars trades")

    # 3. MQ features : MQ_Lite levels (nouveau) ou DMP JSONL (legacy)
    # FIX 12/05/2026 (cross-check 2 agents) : en mode mq_lite, le pipeline ne
    # chargeait QUE les niveaux MQ (17 cols) et SAUTAIT le DMP JSONL. Resultat
    # 28 cols Sierra-only (regime/profile/CVD/VWAP/momentum) absentes
    # silencieusement → regime_engine guard skip → regime_actionable=0 100%
    # → filtre BOT3_REGIME_SKIP code mort en production. Fix : toujours charger
    # le DMP JSONL pour features Sierra non-MQ, MQ_Lite reste source unique
    # pour les NIVEAUX (dist_mq_*, dist_gex_*, etc.).
    if use_mq_lite:
        sys.path.insert(0, str(ROOT / "CORE"))
        from load_mq_levels import load_mq_levels  # lazy import
        print("  [3/6] Load MQ_Lite levels (Hive partitioned)...")
        mq_levels = load_mq_levels(symbol, start, end)
        print(f"        {len(mq_levels)} levels rows")
        # FIX 12/05 : charge aussi DMP JSONL pour les 28 features Sierra-only
        # (regime/profile/CVD/VWAP/momentum/IB). Drop les cols MQ qui sont
        # remises ensuite via attach_mq_distances (4bis) pour eviter doublon.
        #
        # FIX MENTHORQ COVERAGE 16/05/2026 : conditionner le drop dist_mq_*.
        #   Si MQ_Lite Hive VIDE pour la periode (mois pre-28/04/2026 deploy),
        #   on GARDE dist_mq_*_ticks du DMP pour fallback (calcul _pct = ticks*tick/close*100
        #   dans bloc 4bis-fallback). Sans ce fix, coverage MQ = 0% sur Dec-Mar.
        print("  [3bis/6] Load DMP JSONL pour features Sierra non-MQ...")
        dmp_full = load_dmp_jsonl(symbol, start, end)
        if not dmp_full.empty:
            # FIX MENTHORQ COVERAGE 16/05/2026 v2 : NE JAMAIS dropper dist_mq_*
            # du DMP. On les garde TOUJOURS comme TICKS source pour fallback _pct.
            # MQ_Lite asof merge ecrit `dist_mq_*_pct` en colonnes separees (PCT)
            # quand disponible → pas de conflit nom. Le fallback (4bis-fallback)
            # calcule `_pct` = ticks*tick/close*100 pour les bars NaN apres MQ_Lite.
            #
            # Resultat attendu :
            #   - Mois pre-MQ_Lite (Dec-Mar) : `_pct` calcule via fallback DMP (~100%)
            #   - Mois post-deploy (Avr-Mai) : `_pct` via MQ_Lite asof (autoritaire)
            #                                  + fallback DMP comble les trous
            dmp = dmp_full  # plus de drop, tout est preserve
            print(f"        {len(dmp)} bars DMP ({len(dmp.columns)-1} cols, incl. dist_mq_* TICKS pour fallback)")
        else:
            dmp = pd.DataFrame()
            print(f"        [WARN] DMP JSONL vide (Sierra inactif?) → 28 features regime/profile manquantes")
    else:
        print("  [3/6] Load DMP JSONL MQ features...")
        mq_levels = pd.DataFrame()
        dmp = load_dmp_jsonl(symbol, start, end)
        print(f"        {len(dmp)} bars DMP")

    # 4. Merge LEFT JOIN
    print("  [4/6] Merge OHLCV + Trades + MQ (LEFT JOIN)...")
    # Normaliser ts_event en pandas Timestamp UTC sans tz pour merge
    # FIX POST-AUDIT-2: bonne detection via isinstance(DatetimeTZDtype) au lieu de hasattr
    ohlcv["ts_event"] = pd.to_datetime(ohlcv["ts_event"])
    if isinstance(ohlcv["ts_event"].dtype, pd.DatetimeTZDtype):
        ohlcv["ts_event"] = ohlcv["ts_event"].dt.tz_localize(None)
    if not trades.empty:
        trades["ts_event"] = pd.to_datetime(trades["ts_event"])
    if not dmp.empty:
        dmp["ts_event"] = pd.to_datetime(dmp["ts_event"])

    df = ohlcv.merge(trades, on="ts_event", how="left") if not trades.empty else ohlcv
    df = df.merge(dmp, on="ts_event", how="left") if not dmp.empty else df

    # 4bis-pre. Snapshot dist_mq_*_ticks du DMP AVANT attach_mq_distances
    # (qui pre-allocate NaN et ecrase les valeurs DMP). On restore via fillna apres.
    # FIX MENTHORQ COVERAGE 16/05/2026 v3.
    _dmp_mq_snapshot = {}
    _snapshot_cols = ["dist_mq_call", "dist_mq_put", "dist_mq_hvl",
                       "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte"]
    for col in _snapshot_cols:
        if col in df.columns and df[col].notna().any():
            _dmp_mq_snapshot[col] = df[col].copy()

    # 4bis. Si MQ_Lite mode : asof merge + calcul distances (close depuis OHLCV)
    if use_mq_lite and not mq_levels.empty:
        from load_mq_levels import attach_mq_distances
        print("  [4bis/6] Asof merge MQ_Lite levels + compute distances...")
        df = attach_mq_distances(df, mq_levels, tick_size=get_tick_size(symbol))

    # 4bis-restore. Restore DMP dist_mq_*_ticks pour les bars NaN apres MQ_Lite.
    # MQ_Lite valeurs (bars matched asof) sont AUTORITAIRES, fallback DMP comble trous.
    if _dmp_mq_snapshot:
        n_restored = 0
        for col, dmp_vals in _dmp_mq_snapshot.items():
            if col in df.columns:
                mask_nan = df[col].isna() & dmp_vals.notna()
                if mask_nan.any():
                    df.loc[mask_nan, col] = dmp_vals[mask_nan]
                    n_restored += int(mask_nan.sum())
            else:
                df[col] = dmp_vals
                n_restored += int(dmp_vals.notna().sum())
        if n_restored > 0:
            print(f"  [4bis-restore] DMP dist_mq_*_ticks restaures (post-attach NaN) : {n_restored} valeurs")

    # 4bis-fallback. FIX BUG MenthorQ COVERAGE 16/05/2026 :
    # Pour les mois pre-MQ_Lite deploy (28/04/2026), MQ_Lite Hive est vide
    # mais le DMP JSONL contient `dist_mq_*` en TICKS (post menthorq_backfill_injector).
    # On calcule `dist_mq_*_pct` en fallback = dist_mq_*_ticks * tick / close * 100.
    # Convention NEW (level - close) preservee : signe DMP C++ deja NEW.
    # Resultat attendu : coverage MQ Dec-Mar passe de 0% a ~95% sur ES/NQ.
    _tick = get_tick_size(symbol)
    _fallback_mq_map = [
        ("dist_mq_call", "dist_mq_call_pct"),
        ("dist_mq_put", "dist_mq_put_pct"),
        ("dist_mq_hvl", "dist_mq_hvl_pct"),
        ("dist_mq_call_0dte", "dist_mq_call_0dte_pct"),
        ("dist_mq_put_0dte", "dist_mq_put_0dte_pct"),
        ("dist_mq_hvl_0dte", "dist_mq_hvl_0dte_pct"),
    ]
    n_filled_fallback = 0
    for ticks_col, pct_col in _fallback_mq_map:
        if ticks_col in df.columns:
            # Mask : pct vide (NaN) ET ticks dispo ET close valide
            need_fill = (
                (pct_col not in df.columns or df[pct_col].isna())
                & df[ticks_col].notna()
                & df["close"].notna()
                & (df["close"] != 0)
            )
            if need_fill.any():
                # dist_pct = (level - close) / close * 100
                #         = (dist_ticks * tick) / close * 100  [convention DMP NEW]
                pct_values = (df.loc[need_fill, ticks_col] * _tick / df.loc[need_fill, "close"]) * 100
                if pct_col not in df.columns:
                    df[pct_col] = pd.NA
                df.loc[need_fill, pct_col] = pct_values
                n_filled_fallback += int(need_fill.sum())
    if n_filled_fallback > 0:
        # Marquer is_mq_filled=1 pour ces bars (fallback considere MQ valide)
        if "is_mq_filled" in df.columns:
            mask_filled = df["dist_mq_call_pct"].notna() | df["dist_mq_put_pct"].notna()
            df.loc[mask_filled & df["is_mq_filled"].isna(), "is_mq_filled"] = 1
        print(f"  [4bis-fallback] DMP dist_mq_*_ticks -> _pct : {n_filled_fallback} valeurs remplies")

    # 4ter. VIX_Lite (Phase 2a — decouplage progressif des vix_* du DMP full).
    # But strategique 13/05/2026 : Bot 2 V6 full Databento. VIX_Lite est une etude
    # C++ dediee (CPP/MIA_REFACTORED/VIX_Lite.cpp v1.3) qui dump VIX + 19 niveaux
    # MQ Gamma VIX dans DATA/vix_levels/year=*/month=*/day=*/vix.jsonl.
    # Auto-detect : si fichiers VIX_Lite presents pour la periode → merge en
    # PARALLELE avec prefixe vixl_* (pas de conflit avec vix_* DMP). Phase 2b
    # ulterieure = retirer les vix_* du DMP_MQ_FIELDS apres audit comparatif J+7.
    try:
        sys.path.insert(0, str(ROOT / "CORE"))
        from vix_lite_reader import load_vix_lite_jsonl, enrich_vix_lite
        print("  [4ter/6] Load VIX_Lite (Phase 2a parallel vix_* DMP)...")
        vix_lite_df = load_vix_lite_jsonl(start, end)
        if not vix_lite_df.empty:
            vix_lite_df = enrich_vix_lite(vix_lite_df)
            # Rename : vix_X → vixl_X et dist_vix_X → dist_vixl_X (prefix unique)
            # Garde ts_event tel quel pour merge_asof.
            rename_map = {
                c: c.replace("vix_", "vixl_", 1)
                for c in vix_lite_df.columns
                if "vix_" in c and c != "ts_event"
            }
            vix_lite_df = (
                vix_lite_df.drop(columns=["schema_version"], errors="ignore")
                            .rename(columns=rename_map)
            )
            # Asof merge backward, tolerance 5min (VIX bouge 1/min RTH, fige hors RTH)
            df = pd.merge_asof(
                df.sort_values("ts_event").reset_index(drop=True),
                vix_lite_df.sort_values("ts_event").reset_index(drop=True),
                on="ts_event",
                direction="backward",
                tolerance=pd.Timedelta(minutes=5),
            )
            print(f"        {len(vix_lite_df)} VIX_Lite rows merged (+{len(rename_map)} vixl_* cols)")
        else:
            print(f"        [INFO] aucun fichier VIX_Lite pour {start}..{end} (skip)")
    except ImportError as e:
        print(f"        [WARN] vix_lite_reader import failed: {e}")
    except Exception as e:
        print(f"        [WARN] VIX_Lite merge failed: {e}")

    # 5. Fill no-trade bars + flag
    print("  [5/6] Compute derived features...")
    if "delta_bar" in df.columns:
        df["bar_no_trade"] = df["delta_bar"].isna().astype(int)
        for c in ["buy_vol", "sell_vol", "delta_bar", "n_trades", "max_trade_size"]:
            if c in df.columns:
                df[c] = df[c].fillna(0)

        # CVD session-reset
        df = add_session_cvd(df)

    # ATR + roll + PCT-normalized distances (vs ATR-norm qui detruisait info)
    df = compute_atr(df, period=14)
    df = detect_roll(df)
    df = add_pct_normalized_distances(df, symbol=symbol)
    # Sauve OHLC/avg_price/etc via features derivees (pas drop)
    df = add_ohlc_derived_features(df)

    # FIX BUG #B audit-4: is_mq_filled utilise dist_mq_call_pct (apres drop brut)
    # Avant: utilisait dist_mq_call brut deja DROPPED -> always 0 (bug)
    # Maintenant: utilise version _pct qui existe apres add_pct_normalized_distances
    if "dist_mq_call_pct" in df.columns:
        df["is_mq_filled"] = df["dist_mq_call_pct"].notna().astype(int)
    elif "dist_mq_put_pct" in df.columns:
        df["is_mq_filled"] = df["dist_mq_put_pct"].notna().astype(int)
    else:
        df["is_mq_filled"] = 0

    # FIX POST-AUDIT-3: gex_cluster_count -> z-score par symbole (preserve info structurelle)
    # FIX BUG #C audit-4: DROP version brute apres calcul z (sinon doublon RED ratio 0.502)
    if "gex_cluster_count" in df.columns:
        gex_vals = df["gex_cluster_count"].dropna()
        if len(gex_vals) > 10:
            mean_sym = gex_vals.mean()
            std_sym = gex_vals.std()
            if std_sym > 0:
                df["gex_cluster_count_z"] = ((df["gex_cluster_count"] - mean_sym) / std_sym).clip(-5, 5)
            else:
                df["gex_cluster_count_z"] = 0.0
        # DROP version brute (z-score preserve l'info)
        df = df.drop(columns=["gex_cluster_count"], errors="ignore")

    # FIX BUG #D audit-4: dist_mq_hvl_0dte_pct = 99.97% null (feature schema 3.7.9 trop neuve)
    # Forward elle se peuplera, en attendant DROP pour eviter pollution dataset
    if "dist_mq_hvl_0dte_pct" in df.columns:
        fill_pct = df["dist_mq_hvl_0dte_pct"].notna().mean() * 100
        if fill_pct < 5.0:  # < 5% rempli = inutilisable
            df = df.drop(columns=["dist_mq_hvl_0dte_pct"], errors="ignore")

    # ===========================================================================
    # 5bis. REGIME ENGINE (Plan B Jackson 03/05/2026 — anti-Pattern 11)
    # ===========================================================================
    # Calcule UNE FOIS par bar le verdict regime (10 votes ponderes Steidlmayer/
    # Dalton + bias proxy) et expose comme 7 colonnes regime_*. Source unique
    # de logique regime, consommee par dashboard, Bot 1 paper, Bot 3 backtester.
    print("  [5bis/6] Compute regime_engine (10 votes -> 7 features regime_*)...")

    # R3 fix code-reviewer (03/05) : guard mode use_mq_lite ou DMP non charge.
    # Si features regime DMP absentes, regime_engine retournerait NORMAL/NEUTRE
    # everywhere -> regime_actionable=0 100% -> consumer Bot 1/3 rejet 100%.
    # Detect en amont et skip avec colonnes "UNKNOWN" explicites.
    REQUIRED_REGIME_COLS = ["day_type", "open_type", "vwap_slope_10",
                             "profile_shape", "trend_day_probability"]
    missing_regime = [c for c in REQUIRED_REGIME_COLS if c not in df.columns]
    if missing_regime:
        print(f"        [WARN] Skip regime_engine : features manquantes {missing_regime}")
        df["regime_mode"] = "UNKNOWN"
        df["regime_favor"] = "UNKNOWN"
        df["regime_confidence"] = 0.0
        df["regime_trend_votes"] = 0
        df["regime_range_votes"] = 0
        df["regime_vol"] = "UNKNOWN"
        df["regime_actionable"] = 0
    else:
        # R1.3 fix : derive ib_formed_bool depuis ib_range_ticks AVANT drop final
        if "ib_range_ticks" in df.columns:
            df["ib_formed_bool"] = (df["ib_range_ticks"] > 0).astype(int)

        try:
            from regime_engine import compute_regime_dict
        except ImportError:
            sys.path.insert(0, str(ROOT / "CORE"))
            from regime_engine import compute_regime_dict

        regime_records = []
        for _, row in df.iterrows():
            bar = row.to_dict()
            regime_records.append(compute_regime_dict(bar))
        df_regime = pd.DataFrame(regime_records, index=df.index)
        df = pd.concat([df, df_regime], axis=1)
        actionable_pct = df["regime_actionable"].mean() * 100 if "regime_actionable" in df.columns else 0
        print(f"        regime_actionable rate: {actionable_pct:.1f}% des bars")

        # DROP ib_range_ticks (vol leak instrument) APRES utilisation regime_engine
        # (R1.3 code-reviewer : ib_range_ticks std_NQ/std_ES=7.67 = vol leak)
        if "ib_range_ticks" in df.columns:
            df = df.drop(columns=["ib_range_ticks"], errors="ignore")

    # Sort + dedup safety
    df = df.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)

    # Year/month/day pour partitioning
    ts = pd.to_datetime(df["ts_event"])
    df["year"] = ts.dt.year
    df["month"] = ts.dt.month
    df["day"] = ts.dt.day

    elapsed = time.time() - t0
    print(f"  [6/6] Final: {len(df)} bars × {len(df.columns)} cols ({elapsed:.1f}s)")
    return df


def write_partitioned(df: pd.DataFrame, symbol: str, merge_existing: bool = True):
    """Write Parquet partitioned by year/month.

    merge_existing : si True (default), merge avec partition existante en
    remplacant les jours presents dans le nouveau df et conservant les autres.
    Permet runs partiels (ex: --test-day 28) sans perdre l'historique du mois.

    Si False, ecrase la partition complete (ancien comportement).
    """
    if df.empty:
        return
    out_base = OUT_ROOT / f"symbol={symbol}.c.0"
    out_base.mkdir(parents=True, exist_ok=True)

    n_files = 0
    n_merged = 0
    for (year, month), group in df.groupby(["year", "month"], sort=True):
        sub_dir = out_base / f"year={year}" / f"month={month:02d}"
        sub_dir.mkdir(parents=True, exist_ok=True)
        out_path = sub_dir / "data.parquet"
        tmp_path = sub_dir / "data.parquet.tmp"

        # Drop partition cols from new group (deja dans le path)
        group_clean = group.drop(columns=["year", "month", "day"], errors="ignore")

        # Merge avec existant : drop les jours presents dans group_clean
        # puis concat. Garantit pas de doublons par ts_event.
        if merge_existing and out_path.exists():
            existing = pd.read_parquet(out_path)
            # Harmonise tz : strip si l'un est aware (sinon TypeError au sort/compare)
            ex_ts = pd.to_datetime(existing["ts_event"])
            if isinstance(ex_ts.dtype, pd.DatetimeTZDtype):
                existing["ts_event"] = ex_ts.dt.tz_localize(None)
                ex_ts = existing["ts_event"]
            new_ts = pd.to_datetime(group_clean["ts_event"])
            if isinstance(new_ts.dtype, pd.DatetimeTZDtype):
                group_clean["ts_event"] = new_ts.dt.tz_localize(None)
                new_ts = group_clean["ts_event"]
            new_days = set(new_ts.dt.date.unique())
            kept = existing[~ex_ts.dt.date.isin(new_days)]
            # Aligne colonnes : prend l'union, NaN pour cols manquantes
            all_cols = list(set(kept.columns) | set(group_clean.columns))
            kept = kept.reindex(columns=all_cols)
            group_clean = group_clean.reindex(columns=all_cols)
            merged = pd.concat([kept, group_clean], ignore_index=True)
            merged = merged.sort_values("ts_event").reset_index(drop=True)
            n_merged += 1
            group_clean = merged

        table = pa.Table.from_pandas(group_clean, preserve_index=False)
        pq.write_table(table, tmp_path, compression="zstd")
        tmp_path.replace(out_path)
        n_files += 1
    print(f"  Wrote {n_files} partition files to {out_base} (merged {n_merged})")


# ============================================================
# Helpers summary
# ============================================================
def _mq_filled_pct(df: pd.DataFrame) -> float:
    """Retourne le % de bars avec MQ levels rempli.

    `add_pct_normalized_distances` DROP la version brute `dist_mq_call` au
    profit de `dist_mq_call_pct`. Cette fonction cherche d'abord la version
    _pct (apres drop), puis fallback brut, puis 0 (audit pipeline 29/04).
    """
    for col in ("dist_mq_call_pct", "dist_mq_call"):
        if col in df.columns:
            return round(100 * df[col].notna().mean(), 2)
    return 0


# ============================================================
# Main
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    ap.add_argument("--start", help="YYYY-MM-DD (default 2025-04-25)")
    ap.add_argument("--end", help="YYYY-MM-DD (default 2026-04-25)")
    ap.add_argument("--test-day", help="YYYY-MM-DD pour test 1 jour seulement")
    ap.add_argument("--use-mq-lite", action="store_true",
                    help="Source MQ : MQ_Lite Hive (DATA/mq_levels/) au lieu de DMP JSONL flat. "
                         "Recommande pour donnees post 2026-04-28 (deploy MQ_Lite).")
    args = ap.parse_args()

    if args.test_day:
        d = date.fromisoformat(args.test_day)
        start_d, end_d = d, d
    else:
        start_d = date.fromisoformat(args.start) if args.start else date(2025, 4, 25)
        end_d = date.fromisoformat(args.end) if args.end else date(2026, 4, 25)

    print(f"\nConfig: symbols={args.symbols} {start_d} -> {end_d}")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    summary = []
    for sym in args.symbols:
        df = build_for_symbol(sym, start_d, end_d, use_mq_lite=args.use_mq_lite)
        if not df.empty:
            write_partitioned(df, sym)
            summary.append({
                "symbol": sym,
                "bars": len(df),
                "cols": len(df.columns),
                "ts_min": str(df["ts_event"].min()),
                "ts_max": str(df["ts_event"].max()),
                "mq_filled_pct": _mq_filled_pct(df),
                "trades_filled_pct": round(100 * (df.get("delta_bar", pd.Series([0])) != 0).mean(), 2) if "delta_bar" in df.columns else 0,
            })

    print("\n" + "=" * 70)
    print(" SUMMARY")
    print("=" * 70)
    for s in summary:
        print(f"  {s['symbol']:6s} bars={s['bars']:>7d} cols={s['cols']:>3d} "
              f"mq={s['mq_filled_pct']:>5.1f}% trades={s['trades_filled_pct']:>5.1f}%  "
              f"{s['ts_min']} -> {s['ts_max']}")


if __name__ == "__main__":
    main()
