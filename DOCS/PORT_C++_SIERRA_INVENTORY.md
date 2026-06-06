# Port C++ Sierra — Inventaire exhaustif features Python-only

**Date** : 2026-06-07
**Mode** : ULTRATHINK exhaustif
**Echantillon** : 5 jours recents NQ
**Total features Python** (apres filter infra) : 461
**Sierra features** : 265
**Python-only (a porter)** : 394

## Stats par famille

| Famille | N features | N utiles (<50% null) |
|---|---|---|
| F3_DistNormalisees | 68 | 58 |
| F1_SessionsFine | 41 | 29 |
| F4_VWAP_Bands | 31 | 31 |
| F14_BigV2 | 31 | 31 |
| F2_PrevLevels | 29 | 19 |
| F5a_CTX_Simples | 28 | 26 |
| F25_Unclassified | 18 | 13 |
| F21_AggressorEnrichi | 14 | 14 |
| F5b_CTX_Complexes | 14 | 14 |
| F7_Divergences | 14 | 13 |
| F8_News | 14 | 14 |
| F12_BarShape | 12 | 12 |
| F6_Intermarket_PYTHON | 10 | 7 |
| F10_Swings_Enrichi | 10 | 10 |
| F15_Trapped | 10 | 10 |
| F17_LongColorEdge | 8 | 8 |
| F23_VP_Absolus | 8 | 8 |
| F11_Regime_PYTHON | 7 | 7 |
| F16_BN_AbsorbStack | 6 | 6 |
| F18_SpikeOrigins | 4 | 4 |
| F13_RVOL_Avance | 4 | 4 |
| F24_Quality | 4 | 4 |
| F22_PositionRange | 3 | 3 |
| F20_DailyExtremes | 3 | 2 |
| F9_Roll | 3 | 1 |

## Stats par complexite C++

| Complexite | N |
|---|---|
| EASY | 127 |
| HARD | 52 |
| IMPOSSIBLE-RESTE-PYTHON | 17 |
| MEDIUM | 130 |
| TRIVIAL | 68 |

## F10_Swings_Enrichi (10 features, 10 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `bars_since_last_swing_high` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `bars_since_last_swing_low` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `equal_highs_detected` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `equal_lows_detected` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `last_swing_high_session` | 0.0% | ✅ | enricher_chain.py:1164 | MEDIUM |
| `last_swing_low_session` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `liquidity_sweep_high_lag5` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `liquidity_sweep_low_lag5` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `swing_high_active_lag10` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `swing_low_active_lag10` | 0.0% | ✅ | NOT_FOUND | MEDIUM |

## F11_Regime_PYTHON (7 features, 7 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `regime_actionable` | 0.0% | ✅ | enricher_chain.py:1479 | IMPOSSIBLE-RESTE-PYTHON |
| `regime_confidence` | 0.0% | ✅ | enricher_chain.py:1477 | IMPOSSIBLE-RESTE-PYTHON |
| `regime_favor` | 0.0% | ✅ | enricher_chain.py:1477 | IMPOSSIBLE-RESTE-PYTHON |
| `regime_mode` | 0.0% | ✅ | enricher_chain.py:1477 | IMPOSSIBLE-RESTE-PYTHON |
| `regime_range_votes` | 0.0% | ✅ | enricher_chain.py:1478 | IMPOSSIBLE-RESTE-PYTHON |
| `regime_trend_votes` | 0.0% | ✅ | enricher_chain.py:1478 | IMPOSSIBLE-RESTE-PYTHON |
| `regime_vol` | 0.0% | ✅ | enricher_chain.py:1479 | IMPOSSIBLE-RESTE-PYTHON |

## F12_BarShape (12 features, 12 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `bar_body_pct` | 0.0% | ✅ | enricher_chain.py:747 | EASY |
| `bar_body_ticks` | 0.0% | ✅ | enricher_chain.py:499 | EASY |
| `bar_lower_wick_pct` | 0.0% | ✅ | enricher_chain.py:1354 | EASY |
| `bar_no_trade` | 0.0% | ✅ | enricher_chain.py:1360 | EASY |
| `bar_upper_wick_pct` | 0.0% | ✅ | enricher_chain.py:1343 | EASY |
| `long_dn_bar` | 0.0% | ✅ | enricher_chain.py:499 | EASY |
| `long_dn_up_pattern` | 0.0% | ✅ | enricher_chain.py:505 | EASY |
| `long_up_bar` | 0.0% | ✅ | enricher_chain.py:499 | EASY |
| `long_up_dn_pattern` | 0.0% | ✅ | enricher_chain.py:505 | EASY |
| `range_h_minus_lprev_ticks` | 0.0% | ✅ | enricher_chain.py:500 | EASY |
| `range_hprev_minus_l_ticks` | 0.0% | ✅ | enricher_chain.py:500 | EASY |
| `range_size` | 0.0% | ✅ | phase_b_helpers.py:1275 | EASY |

## F13_RVOL_Avance (4 features, 4 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `rvol_buy_strong` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `rvol_extreme` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `rvol_regime` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `rvol_sell_strong` | 0.0% | ✅ | NOT_FOUND | MEDIUM |

## F14_BigV2 (31 features, 31 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `big_buy_dominance` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `big_sell_dominance` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `cluster_at_high` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `cluster_at_low` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `max_big_ask_vol_in_bar` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `max_big_bid_vol_in_bar` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `max_cluster_size` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `max_cluster_volume` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `max_cluster_volume_v2` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_ask_v2_t1` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_ask_v2_t2` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_ask_v2_t3` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_ask_v2_t4` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_bid_v2_t1` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_bid_v2_t2` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_bid_v2_t3` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_bid_v2_t4` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_buy_t1` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_buy_t2` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_buy_t3` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_buy_t4` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_sell_t1` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_sell_t2` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_sell_t3` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_sell_t4` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_t1` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_t2` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_t3` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_big_t4` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_cluster_groups` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_clusters` | 0.0% | ✅ | NOT_FOUND | MEDIUM |

## F15_Trapped (10 features, 10 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `bn_trapped_buyers_at_resistance` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_trapped_buyers_raw` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_trapped_sellers_at_support` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_trapped_sellers_raw` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_trapped_buyers_cluster_within_0_2pct` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_trapped_buyers_zones_active` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_trapped_sellers_cluster_within_0_2pct` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_trapped_sellers_zones_active` | 0.0% | ✅ | NOT_FOUND | HARD |
| `near_resistance_level` | 0.0% | ✅ | NOT_FOUND | HARD |
| `near_support_level` | 0.0% | ✅ | NOT_FOUND | HARD |

## F16_BN_AbsorbStack (6 features, 6 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `bn_absorb_ask_at_level` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_absorb_ask_raw` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_absorb_bid_at_level` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_absorb_bid_raw` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_stack_ask` | 0.0% | ✅ | NOT_FOUND | HARD |
| `bn_stack_bid` | 0.0% | ✅ | NOT_FOUND | HARD |

## F17_LongColorEdge (8 features, 8 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `n_color_dn_cluster_within_0_2pct` | 0.0% | ✅ | enricher_chain.py:1604 | HARD |
| `n_color_up_cluster_within_0_2pct` | 0.0% | ✅ | enricher_chain.py:1603 | HARD |
| `n_edge_buy_active` | 0.0% | ✅ | enricher_chain.py:1566 | HARD |
| `n_edge_sell_active` | 0.0% | ✅ | enricher_chain.py:1566 | HARD |
| `n_long_dn_cluster_within_0_2pct` | 0.0% | ✅ | enricher_chain.py:504 | HARD |
| `n_long_dn_zones_active` | 0.0% | ✅ | enricher_chain.py:501 | HARD |
| `n_long_up_cluster_within_0_2pct` | 0.0% | ✅ | enricher_chain.py:503 | HARD |
| `n_long_up_zones_active` | 0.0% | ✅ | enricher_chain.py:501 | HARD |

## F18_SpikeOrigins (4 features, 4 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `bars_since_last_spike` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_spike_origins_active` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_spike_origins_cluster_within_0_2pct` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `spike_detected_lag3` | 0.0% | ✅ | NOT_FOUND | MEDIUM |

## F1_SessionsFine (41 features, 29 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `above_after_open` | 0.0% | ✅ | NOT_FOUND | EASY |
| `above_asia_open` | 0.0% | ✅ | NOT_FOUND | EASY |
| `above_london_open` | 0.0% | ✅ | NOT_FOUND | EASY |
| `above_ny_open` | 0.0% | ✅ | NOT_FOUND | EASY |
| `after_high` | 96.7% | ❌ | SKIPPED | EASY |
| `after_low` | 96.7% | ❌ | SKIPPED | EASY |
| `after_open` | 96.7% | ❌ | SKIPPED | EASY |
| `after_open_approximate` | 0.0% | ✅ | NOT_FOUND | EASY |
| `asia_high` | 0.0% | ✅ | NOT_FOUND | EASY |
| `asia_low` | 0.0% | ✅ | NOT_FOUND | EASY |
| `asia_open` | 0.0% | ✅ | NOT_FOUND | EASY |
| `asia_open_approximate` | 0.0% | ✅ | NOT_FOUND | EASY |
| `dist_after_high_pct` | 96.7% | ❌ | SKIPPED | EASY |
| `dist_after_low_pct` | 96.7% | ❌ | SKIPPED | EASY |
| `dist_after_open_pct` | 96.7% | ❌ | SKIPPED | EASY |
| `dist_asia_high_pct` | 0.0% | ✅ | NOT_FOUND | EASY |
| `dist_asia_low_pct` | 0.0% | ✅ | NOT_FOUND | EASY |
| `dist_asia_open_pct` | 0.0% | ✅ | NOT_FOUND | EASY |
| `dist_london_high_pct` | 40.0% | ✅ | NOT_FOUND | EASY |
| `dist_london_low_pct` | 40.0% | ✅ | NOT_FOUND | EASY |
| `dist_london_open_pct` | 40.0% | ✅ | NOT_FOUND | EASY |
| `dist_ny_open_pct` | 71.9% | ❌ | SKIPPED | EASY |
| `dist_us_high_pct` | 71.9% | ❌ | SKIPPED | EASY |
| `dist_us_low_pct` | 71.9% | ❌ | SKIPPED | EASY |
| `is_cash_session` | 0.0% | ✅ | phase_b_helpers.py:120 | EASY |
| `is_ib_window` | 0.0% | ✅ | phase_b_helpers.py:122 | EASY |
| `is_in_asia` | 0.0% | ✅ | enricher_chain.py:713 | EASY |
| `is_in_london` | 0.0% | ✅ | enricher_chain.py:714 | EASY |
| `is_in_us_after` | 0.0% | ✅ | enricher_chain.py:716 | EASY |
| `is_in_us_cash` | 0.0% | ✅ | enricher_chain.py:715 | EASY |
| `london_high` | 40.0% | ✅ | NOT_FOUND | EASY |
| `london_low` | 40.0% | ✅ | NOT_FOUND | EASY |
| `london_open` | 40.0% | ✅ | NOT_FOUND | EASY |
| `london_open_approximate` | 0.0% | ✅ | NOT_FOUND | EASY |
| `mins_et` | 0.0% | ✅ | phase_b_helpers.py:112 | game_changers_streaming.py:102 | enricher_chain.py:1436 | EASY |
| `ny_open` | 71.9% | ❌ | SKIPPED | EASY |
| `pct_in_range` | 0.0% | ✅ | NOT_FOUND | EASY |
| `position_in_range` | 0.1% | ✅ | enricher_chain.py:1377 | EASY |
| `session_segment` | 0.0% | ✅ | enricher_chain.py:1441 | EASY |
| `us_high` | 71.9% | ❌ | SKIPPED | EASY |
| `us_low` | 71.9% | ❌ | SKIPPED | EASY |

## F20_DailyExtremes (3 features, 2 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `atr_regime_zscore_60d` | 100.0% | ❌ | SKIPPED | MEDIUM |
| `mq_1d_max` | 0.1% | ✅ | enricher_chain.py:1374 | MEDIUM |
| `mq_1d_min` | 0.1% | ✅ | enricher_chain.py:1373 | MEDIUM |

## F21_AggressorEnrichi (14 features, 14 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `aggressor_imbalance` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `cvd_5d_rolling_ffd` | 0.0% | ✅ | enricher_chain.py:1934 | MEDIUM |
| `delta_change` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `diag_imbalance_ofi_proxy` | 0.0% | ✅ | enricher_chain.py:440 | MEDIUM |
| `finish_pct_up` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `finish_strong_dn` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `finish_strong_up` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `large_trader_max_size_proxy` | 0.0% | ✅ | enricher_chain.py:445 | MEDIUM |
| `max_delta_bar` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `max_size_buy` | 0.0% | ✅ | enricher_chain.py:443 | MEDIUM |
| `max_size_sell` | 0.0% | ✅ | enricher_chain.py:444 | MEDIUM |
| `min_delta_bar` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `n_ticks_bar` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `p99_trade_size` | 0.0% | ✅ | NOT_FOUND | MEDIUM |

## F22_PositionRange (3 features, 3 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `discount_zone` | 0.0% | ✅ | NOT_FOUND | EASY |
| `inside_value_area` | 0.0% | ✅ | phase_b_helpers.py:1045 | EASY |
| `premium_zone` | 0.0% | ✅ | NOT_FOUND | EASY |

## F23_VP_Absolus (8 features, 8 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `cur_va_n_buckets` | 0.0% | ✅ | phase_b_helpers.py:1535 | enricher_chain.py:1951 | EASY |
| `cur_va_total_vol` | 0.0% | ✅ | phase_b_helpers.py:1535 | enricher_chain.py:1952 | EASY |
| `cur_vah` | 0.0% | ✅ | phase_b_helpers.py:1026 | enricher_chain.py:851 | EASY |
| `cur_val` | 0.0% | ✅ | phase_b_helpers.py:1027 | enricher_chain.py:852 | EASY |
| `cur_vpoc` | 0.0% | ✅ | phase_b_helpers.py:1025 | enricher_chain.py:850 | EASY |
| `prev_vah` | 0.0% | ✅ | phase_b_helpers.py:1031 | game_changers_streaming.py:129 | enricher_chain.py:854 | EASY |
| `prev_val` | 0.0% | ✅ | phase_b_helpers.py:1032 | game_changers_streaming.py:130 | enricher_chain.py:855 | EASY |
| `prev_vpoc` | 0.0% | ✅ | phase_b_helpers.py:1030 | game_changers_streaming.py:131 | enricher_chain.py:853 | EASY |

## F24_Quality (4 features, 4 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `atr_14m_pct` | 0.0% | ✅ | enricher_chain.py:783 | MEDIUM |
| `vol_spike_dn` | 0.0% | ✅ | phase_b_plus_streaming.py:171 | MEDIUM |
| `vol_spike_up` | 0.0% | ✅ | phase_b_plus_streaming.py:170 | MEDIUM |
| `vol_zscore_20` | 0.0% | ✅ | phase_b_plus_streaming.py:183 | MEDIUM |

## F25_Unclassified (18 features, 13 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `cvd_session` | 0.0% | ✅ | enricher_chain.py:1460 | MEDIUM |
| `ib_broken_dn` | 0.0% | ✅ | phase_b_helpers.py:262 | MEDIUM |
| `ib_high` | 52.4% | ❌ | SKIPPED | MEDIUM |
| `ib_low` | 52.4% | ❌ | SKIPPED | MEDIUM |
| `ib_range` | 52.4% | ❌ | SKIPPED | MEDIUM |
| `mq_blind` | 0.0% | ✅ | enricher_chain.py:201 | MEDIUM |
| `mq_call` | 0.1% | ✅ | enricher_chain.py:148 | MEDIUM |
| `mq_call_0dte` | 73.6% | ❌ | SKIPPED | MEDIUM |
| `mq_gex` | 0.0% | ✅ | enricher_chain.py:201 | MEDIUM |
| `mq_hvl` | 0.1% | ✅ | enricher_chain.py:152 | MEDIUM |
| `mq_hvl_0dte` | 20.4% | ✅ | enricher_chain.py:153 | MEDIUM |
| `mq_put` | 0.1% | ✅ | enricher_chain.py:150 | MEDIUM |
| `mq_put_0dte` | 15.3% | ✅ | enricher_chain.py:151 | MEDIUM |
| `ny_open_approximate` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `poc_migration_dir` | 0.0% | ✅ | phase_b_helpers.py:1055 | MEDIUM |
| `price_1030` | 60.7% | ❌ | SKIPPED | MEDIUM |
| `sess_high` | 0.0% | ✅ | phase_b_helpers.py:572 | game_changers_streaming.py:205 | enricher_chain.py:848 | MEDIUM |
| `sess_low` | 0.0% | ✅ | phase_b_helpers.py:573 | game_changers_streaming.py:206 | enricher_chain.py:849 | MEDIUM |

## F2_PrevLevels (29 features, 19 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `above_open_830` | 0.0% | ✅ | phase_b_plus_streaming.py:442 | EASY |
| `above_open_930` | 0.0% | ✅ | phase_b_plus_streaming.py:448 | EASY |
| `cash_high` | 75.2% | ❌ | SKIPPED | EASY |
| `cash_low` | 75.2% | ❌ | SKIPPED | EASY |
| `cur_pdh` | 0.0% | ✅ | phase_b_helpers.py:1028 | EASY |
| `cur_pdl` | 0.0% | ✅ | phase_b_helpers.py:1029 | EASY |
| `dist_cash_high_pct` | 75.2% | ❌ | SKIPPED | EASY |
| `dist_cash_low_pct` | 75.2% | ❌ | SKIPPED | EASY |
| `dist_open_830_pct` | 53.1% | ❌ | SKIPPED | EASY |
| `dist_open_930_pct` | 47.5% | ✅ | phase_b_plus_streaming.py:447 | EASY |
| `dist_ovn_high_pct` | 71.9% | ❌ | SKIPPED | EASY |
| `dist_ovn_low_pct` | 71.9% | ❌ | SKIPPED | EASY |
| `dist_pdh_atr` | 0.0% | ✅ | enricher_chain.py:856 | EASY |
| `dist_pdh_pct` | 0.0% | ✅ | phase_b_helpers.py:1077 | EASY |
| `dist_pdl_atr` | 0.0% | ✅ | enricher_chain.py:857 | EASY |
| `dist_pdl_pct` | 0.0% | ✅ | phase_b_helpers.py:1078 | EASY |
| `is_new_cash_high` | 0.0% | ✅ | phase_b_helpers.py:693 | EASY |
| `is_new_cash_low` | 0.0% | ✅ | phase_b_helpers.py:694 | EASY |
| `is_new_sess_high` | 0.0% | ✅ | phase_b_helpers.py:607 | EASY |
| `is_new_sess_low` | 0.0% | ✅ | phase_b_helpers.py:608 | EASY |
| `open_830_et` | 53.1% | ❌ | SKIPPED | EASY |
| `open_930_et` | 47.5% | ✅ | phase_b_plus_streaming.py:435 | EASY |
| `open_cash` | 47.5% | ✅ | phase_b_helpers.py:778 | game_changers_streaming.py:128 | EASY |
| `ovn_broken_dn` | 0.0% | ✅ | phase_b_plus_streaming.py:385 | EASY |
| `ovn_broken_up` | 0.0% | ✅ | phase_b_plus_streaming.py:384 | EASY |
| `ovn_high` | 71.9% | ❌ | SKIPPED | EASY |
| `ovn_low` | 71.9% | ❌ | SKIPPED | EASY |
| `pdh` | 0.0% | ✅ | phase_b_helpers.py:1033 | game_changers_streaming.py:132 | enricher_chain.py:856 | EASY |
| `pdl` | 0.0% | ✅ | phase_b_helpers.py:1034 | game_changers_streaming.py:133 | enricher_chain.py:857 | EASY |

## F3_DistNormalisees (68 features, 58 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `dist_1d_max_ticks_pct` | 0.1% | ✅ | enricher_chain.py:1388 | TRIVIAL |
| `dist_1d_min_ticks_pct` | 0.1% | ✅ | enricher_chain.py:1397 | TRIVIAL |
| `dist_big_ask_nearest_pct` | 83.2% | ❌ | SKIPPED | TRIVIAL |
| `dist_big_bid_nearest_pct` | 83.1% | ❌ | SKIPPED | TRIVIAL |
| `dist_cluster_nearest_dn_pct` | 69.2% | ❌ | SKIPPED | TRIVIAL |
| `dist_cluster_nearest_up_pct` | 69.9% | ❌ | SKIPPED | TRIVIAL |
| `dist_color_dn_nearest_pct` | 23.0% | ✅ | enricher_chain.py:1602 | TRIVIAL |
| `dist_color_up_nearest_pct` | 0.0% | ✅ | enricher_chain.py:1602 | TRIVIAL |
| `dist_cur_vah_atr` | 0.0% | ✅ | enricher_chain.py:851 | TRIVIAL |
| `dist_cur_vah_pct` | 0.0% | ✅ | phase_b_helpers.py:1072 | TRIVIAL |
| `dist_cur_val_atr` | 0.0% | ✅ | enricher_chain.py:852 | TRIVIAL |
| `dist_cur_val_pct` | 0.0% | ✅ | phase_b_helpers.py:1073 | TRIVIAL |
| `dist_cur_vpoc_atr` | 0.0% | ✅ | enricher_chain.py:850 | TRIVIAL |
| `dist_cur_vpoc_pct` | 0.0% | ✅ | phase_b_helpers.py:1071 | TRIVIAL |
| `dist_delta_div_buy_nearest_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_delta_div_sell_nearest_pct` | 2.9% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_edge_buy_nearest_pct` | 13.3% | ✅ | enricher_chain.py:1565 | TRIVIAL |
| `dist_edge_sell_nearest_pct` | 0.0% | ✅ | enricher_chain.py:1565 | TRIVIAL |
| `dist_gex_nearest_dn_pct` | 0.1% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_gex_nearest_up_pct` | 0.1% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_ib_high_atr` | 52.4% | ❌ | SKIPPED | TRIVIAL |
| `dist_ib_high_pct` | 52.4% | ❌ | SKIPPED | TRIVIAL |
| `dist_ib_low_atr` | 52.4% | ❌ | SKIPPED | TRIVIAL |
| `dist_ib_low_pct` | 52.4% | ❌ | SKIPPED | TRIVIAL |
| `dist_last_spike_origin_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_last_swing_high_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_last_swing_low_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_long_dn_nearest_pct` | 0.0% | ✅ | enricher_chain.py:502 | TRIVIAL |
| `dist_long_up_nearest_pct` | 0.0% | ✅ | enricher_chain.py:502 | TRIVIAL |
| `dist_mq_call_0dte_pct` | 25.9% | ✅ | enricher_chain.py:115 | TRIVIAL |
| `dist_mq_call_atr` | 0.1% | ✅ | enricher_chain.py:858 | TRIVIAL |
| `dist_mq_call_pct` | 0.1% | ✅ | rolling_features_streaming.py:551 | enricher_chain.py:114 | TRIVIAL |
| `dist_mq_hvl_0dte_pct` | 20.4% | ✅ | enricher_chain.py:153 | TRIVIAL |
| `dist_mq_hvl_atr` | 0.1% | ✅ | enricher_chain.py:860 | TRIVIAL |
| `dist_mq_hvl_pct` | 0.1% | ✅ | enricher_chain.py:116 | TRIVIAL |
| `dist_mq_put_0dte_pct` | 15.3% | ✅ | enricher_chain.py:116 | TRIVIAL |
| `dist_mq_put_atr` | 0.1% | ✅ | enricher_chain.py:859 | TRIVIAL |
| `dist_mq_put_pct` | 0.1% | ✅ | rolling_features_streaming.py:550 | enricher_chain.py:115 | TRIVIAL |
| `dist_naked_poc_nearest_pct` | 0.0% | ✅ | enricher_chain.py:1853 | TRIVIAL |
| `dist_prev_vah_atr` | 0.0% | ✅ | enricher_chain.py:854 | TRIVIAL |
| `dist_prev_vah_pct` | 0.0% | ✅ | phase_b_helpers.py:1075 | TRIVIAL |
| `dist_prev_val_atr` | 0.0% | ✅ | enricher_chain.py:855 | TRIVIAL |
| `dist_prev_val_pct` | 0.0% | ✅ | phase_b_helpers.py:1076 | TRIVIAL |
| `dist_prev_vpoc_pct` | 0.0% | ✅ | phase_b_helpers.py:1074 | TRIVIAL |
| `dist_pvwap_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_pvwap_sd1d_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_pvwap_sd1u_pct` | 0.0% | ✅ | NOT_FOUND | TRIVIAL |
| `dist_sess_high_atr` | 0.0% | ✅ | enricher_chain.py:848 | TRIVIAL |
| `dist_sess_high_pct` | 0.0% | ✅ | phase_b_helpers.py:579 | TRIVIAL |
| `dist_sess_low_atr` | 0.0% | ✅ | enricher_chain.py:849 | TRIVIAL |
| `dist_sess_low_pct` | 0.0% | ✅ | phase_b_helpers.py:582 | TRIVIAL |
| `dist_trapped_buyers_nearest_pct` | 99.3% | ❌ | SKIPPED | TRIVIAL |
| `dist_trapped_sellers_nearest_pct` | 91.3% | ❌ | SKIPPED | TRIVIAL |
| `dist_vwap_d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:242 | TRIVIAL |
| `dist_vwap_d_sd1d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:244 | TRIVIAL |
| `dist_vwap_d_sd1u_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:243 | TRIVIAL |
| `dist_vwap_d_sd2d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:246 | TRIVIAL |
| `dist_vwap_d_sd2u_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:245 | TRIVIAL |
| `dist_vwap_m_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:333 | TRIVIAL |
| `dist_vwap_m_sd1d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:335 | TRIVIAL |
| `dist_vwap_m_sd1u_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:334 | TRIVIAL |
| `dist_vwap_m_sd2d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:337 | TRIVIAL |
| `dist_vwap_m_sd2u_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:336 | TRIVIAL |
| `dist_vwap_w_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:298 | TRIVIAL |
| `dist_vwap_w_sd1d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:300 | TRIVIAL |
| `dist_vwap_w_sd1u_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:299 | TRIVIAL |
| `dist_vwap_w_sd2d_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:302 | TRIVIAL |
| `dist_vwap_w_sd2u_pct` | 0.0% | ✅ | phase_b_plus_streaming.py:301 | TRIVIAL |

## F4_VWAP_Bands (31 features, 31 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `pvwap` | 0.0% | ✅ | NOT_FOUND | EASY |
| `pvwap_sd1d` | 0.0% | ✅ | NOT_FOUND | EASY |
| `pvwap_sd1u` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_d` | 0.0% | ✅ | phase_b_plus_streaming.py:234 | EASY |
| `vwap_d_cross_dn` | 0.0% | ✅ | phase_b_plus_streaming.py:261 | EASY |
| `vwap_d_cross_up` | 0.0% | ✅ | phase_b_plus_streaming.py:260 | EASY |
| `vwap_d_sd1_above` | 0.0% | ✅ | phase_b_plus_streaming.py:268 | EASY |
| `vwap_d_sd1_below` | 0.0% | ✅ | phase_b_plus_streaming.py:269 | EASY |
| `vwap_d_sd1d` | 0.0% | ✅ | enricher_chain.py:1161 | phase_b_plus_streaming.py:244 | EASY |
| `vwap_d_sd1u` | 0.0% | ✅ | enricher_chain.py:1160 | phase_b_plus_streaming.py:243 | EASY |
| `vwap_d_sd2_above` | 0.0% | ✅ | phase_b_plus_streaming.py:270 | EASY |
| `vwap_d_sd2_below` | 0.0% | ✅ | phase_b_plus_streaming.py:271 | EASY |
| `vwap_d_sd2d` | 0.0% | ✅ | phase_b_plus_streaming.py:246 | EASY |
| `vwap_d_sd2u` | 0.0% | ✅ | phase_b_plus_streaming.py:245 | EASY |
| `vwap_d_sd3d` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_d_sd3u` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_m` | 0.0% | ✅ | enricher_chain.py:809 | phase_b_plus_streaming.py:327 | EASY |
| `vwap_m_sd1d` | 0.0% | ✅ | phase_b_plus_streaming.py:335 | EASY |
| `vwap_m_sd1u` | 0.0% | ✅ | phase_b_plus_streaming.py:334 | EASY |
| `vwap_m_sd2d` | 0.0% | ✅ | phase_b_plus_streaming.py:337 | EASY |
| `vwap_m_sd2u` | 0.0% | ✅ | phase_b_plus_streaming.py:336 | EASY |
| `vwap_m_sd3d` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_m_sd3u` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_slope_10_atr` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_w` | 0.0% | ✅ | enricher_chain.py:808 | phase_b_plus_streaming.py:292 | EASY |
| `vwap_w_sd1d` | 0.0% | ✅ | phase_b_plus_streaming.py:300 | EASY |
| `vwap_w_sd1u` | 0.0% | ✅ | phase_b_plus_streaming.py:299 | EASY |
| `vwap_w_sd2d` | 0.0% | ✅ | phase_b_plus_streaming.py:302 | EASY |
| `vwap_w_sd2u` | 0.0% | ✅ | phase_b_plus_streaming.py:301 | EASY |
| `vwap_w_sd3d` | 0.0% | ✅ | NOT_FOUND | EASY |
| `vwap_w_sd3u` | 0.0% | ✅ | NOT_FOUND | EASY |

## F5a_CTX_Simples (28 features, 26 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `ctx_absorption_score_5` | 0.0% | ✅ | rolling_features_streaming.py:352 | rolling_features.py:116 | MEDIUM |
| `ctx_absorption_streak_5` | 0.0% | ✅ | rolling_features_streaming.py:649 | rolling_features.py:231 | MEDIUM |
| `ctx_cvd_recovery_rate` | 0.0% | ✅ | rolling_features_streaming.py:403 | rolling_features.py:136 | MEDIUM |
| `ctx_cvd_session` | 0.0% | ✅ | rolling_features_streaming.py:1179 | rolling_features.py:583 | enricher_chain.py:1458 | MEDIUM |
| `ctx_day_type_intensity` | 0.0% | ✅ | rolling_features_streaming.py:732 | rolling_features.py:310 | MEDIUM |
| `ctx_delta_slope_5` | 0.0% | ✅ | rolling_features_streaming.py:418 | rolling_features.py:144 | MEDIUM |
| `ctx_delta_sum_10` | 0.0% | ✅ | rolling_features_streaming.py:573 | rolling_features.py:183 | MEDIUM |
| `ctx_delta_sum_3` | 0.0% | ✅ | rolling_features_streaming.py:424 | rolling_features.py:147 | MEDIUM |
| `ctx_dist_vwap_velocity` | 0.0% | ✅ | rolling_features_streaming.py:582 | rolling_features.py:187 | MEDIUM |
| `ctx_finish_strength_mean_5` | 0.0% | ✅ | rolling_features_streaming.py:456 | rolling_features.py:163 | MEDIUM |
| `ctx_ib_extension_ratio` | 52.4% | ❌ | SKIPPED | MEDIUM |
| `ctx_ib_position_velocity` | 52.8% | ❌ | SKIPPED | MEDIUM |
| `ctx_mq_put_call_ratio` | 0.2% | ✅ | rolling_features_streaming.py:742 | rolling_features.py:322 | MEDIUM |
| `ctx_poc_migration_10` | 0.0% | ✅ | rolling_features_streaming.py:801 | rolling_features.py:335 | MEDIUM |
| `ctx_price_slope_5` | 0.0% | ✅ | rolling_features_streaming.py:415 | rolling_features.py:141 | MEDIUM |
| `ctx_range_vs_atr_10` | 0.0% | ✅ | rolling_features_streaming.py:599 | rolling_features.py:197 | MEDIUM |
| `ctx_rotation_factor_20` | 0.0% | ✅ | rolling_features_streaming.py:861 | rolling_features.py:375 | MEDIUM |
| `ctx_rvol_session` | 0.0% | ✅ | rolling_features_streaming.py:1191 | rolling_features.py:598 | MEDIUM |
| `ctx_session_phase` | 0.0% | ✅ | rolling_features_streaming.py:1209 | rolling_features.py:625 | MEDIUM |
| `ctx_side_flip_count_10` | 0.0% | ✅ | rolling_features_streaming.py:476 | rolling_features.py:176 | MEDIUM |
| `ctx_trend_day_score` | 0.0% | ✅ | rolling_features_streaming.py:717 | rolling_features.py:299 | MEDIUM |
| `ctx_va_developing_10` | 0.0% | ✅ | rolling_features_streaming.py:816 | rolling_features.py:348 | MEDIUM |
| `ctx_va_position_velocity` | 0.0% | ✅ | rolling_features_streaming.py:465 | rolling_features.py:170 | MEDIUM |
| `ctx_va_width` | 0.0% | ✅ | rolling_features_streaming.py:808 | rolling_features.py:347 | MEDIUM |
| `ctx_vol_sell_buy_ratio_5` | 0.0% | ✅ | rolling_features_streaming.py:373 | rolling_features.py:122 | MEDIUM |
| `ctx_vol_slope_5` | 0.0% | ✅ | rolling_features_streaming.py:670 | rolling_features.py:253 | MEDIUM |
| `ctx_vol_z_5` | 0.0% | ✅ | rolling_features_streaming.py:438 | rolling_features.py:152 | MEDIUM |
| `ctx_vwap_slope_accel` | 0.0% | ✅ | rolling_features_streaming.py:384 | rolling_features.py:128 | MEDIUM |

## F5b_CTX_Complexes (14 features, 14 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `ctx_bars_since_div` | 0.0% | ✅ | rolling_features_streaming.py:1230 | rolling_features.py:517 | HARD |
| `ctx_climax_signal` | 0.0% | ✅ | rolling_features_streaming.py:657 | rolling_features.py:241 | HARD |
| `ctx_delta_exhaustion` | 0.0% | ✅ | rolling_features_streaming.py:678 | rolling_features.py:261 | HARD |
| `ctx_div_at_swing` | 0.0% | ✅ | rolling_features_streaming.py:1246 | rolling_features.py:531 | HARD |
| `ctx_div_density_20` | 0.0% | ✅ | rolling_features_streaming.py:1236 | rolling_features.py:522 | HARD |
| `ctx_double_top_trap` | 0.0% | ✅ | rolling_features_streaming.py:1153 | rolling_features.py:556 | HARD |
| `ctx_excess_high_bars` | 0.0% | ✅ | rolling_features_streaming.py:904 | rolling_features.py:417 | HARD |
| `ctx_excess_low_bars` | 0.0% | ✅ | rolling_features_streaming.py:919 | rolling_features.py:428 | HARD |
| `ctx_failed_auction` | 0.0% | ✅ | rolling_features_streaming.py:890 | rolling_features.py:396 | HARD |
| `ctx_instant_absorption` | 0.0% | ✅ | rolling_features_streaming.py:641 | rolling_features.py:220 | HARD |
| `ctx_momentum_exhaustion` | 0.0% | ✅ | rolling_features_streaming.py:1164 | rolling_features.py:568 | HARD |
| `ctx_poor_high` | 0.0% | ✅ | rolling_features_streaming.py:905 | rolling_features.py:420 | HARD |
| `ctx_poor_low` | 0.0% | ✅ | rolling_features_streaming.py:920 | rolling_features.py:431 | HARD |
| `ctx_price_delta_div_3` | 0.0% | ✅ | rolling_features_streaming.py:303 | rolling_features.py:110 | HARD |

## F6_Intermarket_PYTHON (10 features, 7 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `im_cross_delta_agreement_5` | 0.0% | ✅ | intermarket_features.py:158 | IMPOSSIBLE-RESTE-PYTHON |
| `im_cross_delta_weighted_5` | 0.0% | ✅ | intermarket_features.py:175 | IMPOSSIBLE-RESTE-PYTHON |
| `im_cross_open_signal` | 0.0% | ✅ | intermarket_features.py:58 | IMPOSSIBLE-RESTE-PYTHON |
| `im_delta_day_divergence` | 100.0% | ❌ | SKIPPED | IMPOSSIBLE-RESTE-PYTHON |
| `im_ltr_slope_diff` | 100.0% | ❌ | SKIPPED | IMPOSSIBLE-RESTE-PYTHON |
| `im_open_type_agreement` | 0.0% | ✅ | intermarket_features.py:290 | IMPOSSIBLE-RESTE-PYTHON |
| `im_price_ratio_slope_10` | 0.0% | ✅ | intermarket_features.py:224 | IMPOSSIBLE-RESTE-PYTHON |
| `im_rolling_correlation_10` | 0.0% | ✅ | intermarket_features.py:237 | IMPOSSIBLE-RESTE-PYTHON |
| `im_smt_divergence` | 0.0% | ✅ | intermarket_features.py:55 | IMPOSSIBLE-RESTE-PYTHON |
| `im_volume_lead` | 100.0% | ❌ | SKIPPED | IMPOSSIBLE-RESTE-PYTHON |

## F7_Divergences (14 features, 13 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `delta_div_buy` | 0.0% | ✅ | enricher_chain.py:931 | HARD |
| `delta_div_buy_clean` | 0.0% | ✅ | rolling_features_streaming.py:1012 | rolling_features.py:487 | HARD |
| `delta_div_sell` | 0.0% | ✅ | enricher_chain.py:930 | HARD |
| `delta_div_sell_clean` | 0.0% | ✅ | rolling_features_streaming.py:1013 | rolling_features.py:488 | HARD |
| `delta_div_strength` | 0.0% | ✅ | rolling_features_streaming.py:1015 | rolling_features.py:498 | HARD |
| `delta_divergence_clean` | 0.0% | ✅ | rolling_features_streaming.py:1014 | rolling_features.py:489 | HARD |
| `div_at_key_level_ticks` | 96.0% | ❌ | SKIPPED | HARD |
| `div_confluence_dmp` | 0.0% | ✅ | rolling_features_streaming.py:1295 | rolling_features.py:678 | HARD |
| `div_confluence_with_regime` | 0.0% | ✅ | rolling_features_streaming.py:1303 | rolling_features.py:709 | HARD |
| `div_regime_proxy_ok` | 0.0% | ✅ | rolling_features_streaming.py:1299 | rolling_features.py:703 | HARD |
| `n_delta_div_buy_cluster_within_0_2pct` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_delta_div_buy_zones_active` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_delta_div_sell_cluster_within_0_2pct` | 0.0% | ✅ | NOT_FOUND | HARD |
| `n_delta_div_sell_zones_active` | 0.0% | ✅ | NOT_FOUND | HARD |

## F8_News (14 features, 14 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `is_news_715` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `is_news_730` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `is_news_830` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `is_news_845` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `is_news_900` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `is_news_930` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `mins_since_news` | 0.0% | ✅ | phase_b_plus_streaming.py:464 | MEDIUM |
| `mins_to_next_news` | 0.0% | ✅ | phase_b_plus_streaming.py:468 | MEDIUM |
| `within_news_715_5m` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `within_news_730_5m` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `within_news_830_5m` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `within_news_845_5m` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `within_news_900_5m` | 0.0% | ✅ | NOT_FOUND | MEDIUM |
| `within_news_930_5m` | 0.0% | ✅ | NOT_FOUND | MEDIUM |

## F9_Roll (3 features, 1 utiles)

| Feature | Null % | Utile | Source Python | Complexite |
|---|---|---|---|---|
| `days_since_roll` | 100.0% | ❌ | SKIPPED | EASY |
| `is_roll_day` | 0.0% | ✅ | enricher_chain.py:1884 | EASY |
| `roll_phase` | 100.0% | ❌ | SKIPPED | EASY |
