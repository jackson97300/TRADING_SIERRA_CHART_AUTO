# DMP Live Validation Report — 15/04/2026

**Genere le** : 2026-04-15 21:36
**Source ES** : `20260415_ES.jsonl` — 1233 barres
**Source NQ** : `20260415_NQ.jsonl` — 1294 barres

## Contexte

Apres la spirale de decouverte de bugs dumper (delta_divergence, big_orders,
MenthorQ, bn_absorb, fp_edge, bar_edge, arr[sz-1], Number of Bars to Calculate),
ce rapport constitue la **source de verite** definitive pour les features du
DMP live apres tous les fixes appliques (07/04, 13/04, 14/04, 15/04).

Objectif : zero decouverte accidentelle ulterieure. Toute feature non listee
comme PROPRE ou EVENT_BASED doit etre consideree comme connue et documentee ici.

## Vue d'ensemble

| Categorie | ES | NQ |
|---|---|---|
| **PROPRE** | 183 | 140 |
| **EVENT_BASED** | 15 | 11 |
| **QUASI_CONSTANTE** | 30 | 13 |
| **MORTE** | 20 | 19 |
| **OUTLIER** | 13 | 78 |

## ⚠️ Features avec comportement divergent ES vs NQ

| Feature | Categorie ES | Categorie NQ |
|---|---|---|
| `bar_color_dn` | QUASI_CONSTANTE | PROPRE |
| `bar_color_up` | QUASI_CONSTANTE | PROPRE |
| `bar_long_dn_bar` | QUASI_CONSTANTE | PROPRE |
| `bar_long_dn_up` | MORTE | QUASI_CONSTANTE |
| `bar_long_up_bar` | QUASI_CONSTANTE | EVENT_BASED |
| `bar_long_up_dn` | MORTE | QUASI_CONSTANTE |
| `bar_pressure_ask` | QUASI_CONSTANTE | PROPRE |
| `bar_pressure_bid` | QUASI_CONSTANTE | PROPRE |
| `big_ask_cluster_20t_t4` | EVENT_BASED | MORTE |
| `big_bid_cluster_20t_t3` | PROPRE | QUASI_CONSTANTE |
| `bn_color_dn` | QUASI_CONSTANTE | PROPRE |
| `bn_color_up` | QUASI_CONSTANTE | PROPRE |
| `bn_color_up_2` | QUASI_CONSTANTE | PROPRE |
| `bn_long_dn` | EVENT_BASED | PROPRE |
| `bn_long_up` | EVENT_BASED | PROPRE |
| `bn_volume_dn` | EVENT_BASED | PROPRE |
| `bn_volume_up` | EVENT_BASED | PROPRE |
| `bool_above_mq_call` | QUASI_CONSTANTE | PROPRE |
| `bool_above_mq_hvl` | QUASI_CONSTANTE | PROPRE |
| `bool_above_prev_vpoc` | QUASI_CONSTANTE | PROPRE |
| `bool_above_vwap_d` | QUASI_CONSTANTE | PROPRE |
| `bool_above_vwap_m` | QUASI_CONSTANTE | PROPRE |
| `bool_above_vwap_w` | QUASI_CONSTANTE | PROPRE |
| `bool_gex_flip_zone` | EVENT_BASED | PROPRE |
| `cvd_day_dir` | QUASI_CONSTANTE | MORTE |
| `delta_divergence` | QUASI_CONSTANTE | PROPRE |
| `dist_1d_max_ticks` | PROPRE | OUTLIER |
| `dist_1d_min_ticks` | PROPRE | OUTLIER |
| `dist_big_ask_nearest_dn` | OUTLIER | PROPRE |
| `dist_big_ask_nearest_up` | OUTLIER | PROPRE |
| `dist_big_bid_nearest_dn` | OUTLIER | PROPRE |
| `dist_big_bid_nearest_up` | OUTLIER | PROPRE |
| `dist_blind_nearest_dn` | PROPRE | OUTLIER |
| `dist_blind_nearest_up` | PROPRE | OUTLIER |
| `dist_comp_20d_vah` | PROPRE | OUTLIER |
| `dist_comp_20d_val` | PROPRE | OUTLIER |
| `dist_comp_20d_vpoc` | PROPRE | OUTLIER |
| `dist_comp_20d_vpoc_atr` | PROPRE | OUTLIER |
| `dist_comp_20d_vwap` | PROPRE | OUTLIER |
| `dist_comp_50d_vah` | PROPRE | OUTLIER |
| `dist_comp_50d_val` | PROPRE | OUTLIER |
| `dist_comp_50d_vpoc` | PROPRE | OUTLIER |
| `dist_comp_50d_vpoc_atr` | PROPRE | OUTLIER |
| `dist_comp_50d_vwap` | PROPRE | OUTLIER |
| `dist_cur_vah` | PROPRE | OUTLIER |
| `dist_cur_val` | PROPRE | OUTLIER |
| `dist_cur_vpoc` | PROPRE | OUTLIER |
| `dist_cur_vwap_vp` | PROPRE | OUTLIER |
| `dist_ext_color_dn` | PROPRE | OUTLIER |
| `dist_ext_color_up` | PROPRE | OUTLIER |
| `dist_ext_edge_buy` | PROPRE | OUTLIER |
| `dist_ext_edge_sell` | PROPRE | OUTLIER |
| `dist_ext_long_dn` | PROPRE | OUTLIER |
| `dist_ext_long_up` | PROPRE | OUTLIER |
| `dist_gex_nearest_dn` | PROPRE | OUTLIER |
| `dist_gex_nearest_up` | PROPRE | OUTLIER |
| `dist_mq_call` | PROPRE | OUTLIER |
| `dist_mq_call_0dte` | PROPRE | OUTLIER |
| `dist_mq_hvl` | PROPRE | OUTLIER |
| `dist_mq_put` | PROPRE | OUTLIER |
| `dist_mq_put_0dte` | PROPRE | OUTLIER |
| `dist_open_830` | PROPRE | OUTLIER |
| `dist_ovn_high` | PROPRE | OUTLIER |
| `dist_ovn_low` | PROPRE | OUTLIER |
| `dist_prev_vah` | PROPRE | OUTLIER |
| `dist_prev_val` | PROPRE | OUTLIER |
| `dist_prev_vpoc` | PROPRE | OUTLIER |
| `dist_prev_vpoc_atr` | PROPRE | OUTLIER |
| `dist_prev_vwap` | PROPRE | OUTLIER |
| `dist_prev_vwap_sd1d` | PROPRE | OUTLIER |
| `dist_prev_vwap_sd1u` | PROPRE | OUTLIER |
| `dist_sess_high` | PROPRE | OUTLIER |
| `dist_sess_low` | PROPRE | OUTLIER |
| `dist_session_lvn_above` | PROPRE | OUTLIER |
| `dist_swing_high` | PROPRE | OUTLIER |
| `dist_swing_low` | PROPRE | OUTLIER |
| `dist_vix_call` | PROPRE | OUTLIER |
| `dist_vix_call_0dte` | PROPRE | OUTLIER |
| `dist_vix_gex_nearest_dn` | PROPRE | OUTLIER |
| `dist_vix_gex_nearest_up` | PROPRE | OUTLIER |
| `dist_vix_hvl` | PROPRE | OUTLIER |
| `dist_vix_put` | PROPRE | OUTLIER |
| `dist_vwap_d` | PROPRE | OUTLIER |
| `dist_vwap_d_atr` | PROPRE | OUTLIER |
| `dist_vwap_d_sd1d` | PROPRE | OUTLIER |
| `dist_vwap_d_sd1u` | PROPRE | OUTLIER |
| `dist_vwap_d_sd2d` | PROPRE | OUTLIER |
| `dist_vwap_d_sd2u` | PROPRE | OUTLIER |
| `dist_vwap_d_sd3d` | PROPRE | OUTLIER |
| `dist_vwap_d_sd3u` | PROPRE | OUTLIER |
| `dist_vwap_m` | PROPRE | OUTLIER |
| `dist_vwap_m_atr` | PROPRE | OUTLIER |
| `dist_vwap_w` | PROPRE | OUTLIER |
| `dist_vwap_w_atr` | PROPRE | OUTLIER |
| `ib_is_wide` | PROPRE | QUASI_CONSTANTE |
| `is_double_dist` | MORTE | QUASI_CONSTANTE |
| `ma_trend` | QUASI_CONSTANTE | PROPRE |
| `n_big_ask_t4` | PROPRE | MORTE |
| `next_wall_dist_ticks` | PROPRE | OUTLIER |
| `open_gap_ticks` | PROPRE | OUTLIER |
| `open_in_prev_va` | PROPRE | EVENT_BASED |
| `open_zone` | PROPRE | QUASI_CONSTANTE |
| `poc_separation_ticks` | QUASI_CONSTANTE | PROPRE |
| `price_vs_swing_mid` | QUASI_CONSTANTE | PROPRE |
| `profile_hvn_dominant` | QUASI_CONSTANTE | PROPRE |
| `profile_shape` | MORTE | QUASI_CONSTANTE |
| `range_pos` | PROPRE | OUTLIER |
| `range_size_ticks` | PROPRE | OUTLIER |
| `retest_high_delta_div` | PROPRE | EVENT_BASED |
| `retest_low_delta_div` | EVENT_BASED | QUASI_CONSTANTE |
| `rotation_dn` | QUASI_CONSTANTE | PROPRE |
| `rotation_up` | QUASI_CONSTANTE | PROPRE |
| `rvol_absorb_buy` | EVENT_BASED | QUASI_CONSTANTE |
| `rvol_absorb_sell` | EVENT_BASED | QUASI_CONSTANTE |
| `sess_range_atr` | PROPRE | OUTLIER |
| `val_touches_20b` | PROPRE | EVENT_BASED |
| `vwap_d_side` | QUASI_CONSTANTE | PROPRE |
| `vwap_m_side` | QUASI_CONSTANTE | PROPRE |
| `vwap_ma_align` | PROPRE | EVENT_BASED |
| `vwap_slope_10_dir` | QUASI_CONSTANTE | PROPRE |
| `vwap_w_side` | QUASI_CONSTANTE | PROPRE |

## 🔴 Features MORTES

| Feature | Raison ES | Raison NQ |
|---|---|---|
| `bar_long_dn_up` | constant = 0.0 | - |
| `bar_long_up_dn` | constant = 0.0 | - |
| `big_ask_cluster_20t_t4` | - | constant = 0.0 |
| `big_bid_cluster_20t_t4` | constant = 0.0 | constant = 0.0 |
| `bool_va_confluence` | constant = 0.0 | constant = 0.0 |
| `comp_vpoc_align_day_20` | constant = 0.0 | constant = 0.0 |
| `cvd_day_dir` | - | constant = 1.0 |
| `dist_vix_hvl_0dte` | 100% NaN | 100% NaN |
| `dist_vix_put_0dte` | 100% NaN | 100% NaN |
| `hvn_between` | constant = 0.0 | constant = 0.0 |
| `ib_broken_down` | constant = 0.0 | constant = 0.0 |
| `inside_comp_20d_va` | constant = 0.0 | constant = 0.0 |
| `inside_comp_50d_va` | constant = 0.0 | constant = 0.0 |
| `inside_prev_va` | constant = 0.0 | constant = 0.0 |
| `is_double_dist` | constant = 1.0 | - |
| `lvn_between` | constant = 0.0 | constant = 0.0 |
| `n_big_ask_t4` | - | constant = 0.0 |
| `n_big_bid_t4` | constant = 0.0 | constant = 0.0 |
| `profile_shape` | constant = 3.0 | - |
| `rule_80pct` | constant = 0.0 | constant = 0.0 |
| `vix_above_hvl` | constant = 0.0 | constant = 0.0 |
| `vix_above_hvl_0dte` | constant = 0.0 | constant = 0.0 |
| `vix_regime` | constant = 1.0 | constant = 1.0 |

## ⚠️ Features QUASI-CONSTANTES

| Feature | Raison ES | Raison NQ |
|---|---|---|
| `bar_color_dn` | top_value 1.0 freq 99.9% | - |
| `bar_color_up` | top_value 1.0 freq 99.9% | - |
| `bar_long_dn_bar` | top_value 0.0 freq 99.1% | - |
| `bar_long_dn_up` | - | top_value 0.0 freq 99.1% |
| `bar_long_up_bar` | top_value 0.0 freq 99.4% | - |
| `bar_long_up_dn` | - | top_value 0.0 freq 99.7% |
| `bar_pressure_ask` | top_value 1.0 freq 99.9% | - |
| `bar_pressure_bid` | top_value 1.0 freq 99.9% | - |
| `big_bid_cluster_20t_t3` | - | uniq=4 top_freq=97% |
| `bn_color_dn` | top_value 1.0 freq 99.9% | - |
| `bn_color_up` | top_value 1.0 freq 99.9% | - |
| `bn_color_up_2` | top_value 1.0 freq 99.9% | - |
| `bool_above_mq_call` | fire 97.2% (quasi tout le temps actif) | - |
| `bool_above_mq_hvl` | top_value 1.0 freq 99.9% | - |
| `bool_above_prev_vpoc` | top_value 1.0 freq 99.9% | - |
| `bool_above_vwap_d` | fire 97.5% (quasi tout le temps actif) | - |
| `bool_above_vwap_m` | top_value 1.0 freq 99.9% | - |
| `bool_above_vwap_w` | top_value 1.0 freq 99.9% | - |
| `cvd_day_dir` | fire 100.0% (quasi tout le temps actif) | - |
| `day_type` | uniq=2 top_freq=99% | uniq=3 top_freq=98% |
| `delta_day_dir` | fire 100.0% (quasi tout le temps actif) | top_value 1.0 freq 99.2% |
| `delta_divergence` | top_value 1.0 freq 99.8% | - |
| `ib_is_wide` | - | top_value 0.0 freq 99.3% |
| `is_double_dist` | - | top_value 1.0 freq 99.3% |
| `ma_trend` | fire 99.9% (quasi tout le temps actif) | - |
| `open_zone` | - | uniq=3 top_freq=92% |
| `poc_separation_ticks` | uniq=5 top_freq=92% | - |
| `price_vs_swing_mid` | fire 97.6% (quasi tout le temps actif) | - |
| `profile_hvn_dominant` | uniq=4 top_freq=92% | - |
| `profile_shape` | - | top_value 3.0 freq 99.3% |
| `retest_low_delta_div` | - | top_value 0.0 freq 99.4% |
| `rotation_dn` | top_value 1.0 freq 99.9% | - |
| `rotation_up` | top_value 1.0 freq 99.9% | - |
| `rvol_absorb_buy` | - | top_value 0.0 freq 99.2% |
| `rvol_absorb_sell` | - | top_value 0.0 freq 99.1% |
| `vwap_d_side` | fire 99.9% (quasi tout le temps actif) | - |
| `vwap_m_side` | top_value 1.0 freq 99.9% | - |
| `vwap_slope_10_dir` | fire 99.9% (quasi tout le temps actif) | - |
| `vwap_triple_align` | fire 97.6% (quasi tout le temps actif) | fire 97.6% (quasi tout le temps actif) |
| `vwap_w_side` | top_value 1.0 freq 99.9% | - |

## 🚨 Features OUTLIERS

| Feature | Raison ES | Raison NQ |
|---|---|---|
| `bars_since_retest_high` | 26.6% NaN | 61.9% NaN |
| `bars_since_retest_low` | 38.8% NaN | 74.0% NaN |
| `dist_1d_max_ticks` | - | 10.3% NaN |
| `dist_1d_min_ticks` | - | 10.3% NaN |
| `dist_big_ask_nearest_dn` | 46.0% NaN | - |
| `dist_big_ask_nearest_up` | 49.5% NaN | - |
| `dist_big_bid_nearest_dn` | 43.7% NaN | - |
| `dist_big_bid_nearest_up` | 47.8% NaN | - |
| `dist_blind_nearest_dn` | - | 10.3% NaN |
| `dist_blind_nearest_up` | - | 10.3% NaN |
| `dist_cluster_nearest_dn` | 74.9% NaN | 30.7% NaN |
| `dist_cluster_nearest_up` | 72.6% NaN | 43.1% NaN |
| `dist_comp_20d_vah` | - | 10.3% NaN |
| `dist_comp_20d_val` | - | 10.3% NaN |
| `dist_comp_20d_vpoc` | - | 10.3% NaN |
| `dist_comp_20d_vpoc_atr` | - | 10.3% NaN |
| `dist_comp_20d_vwap` | - | 10.3% NaN |
| `dist_comp_50d_vah` | - | 10.3% NaN |
| `dist_comp_50d_val` | - | 10.3% NaN |
| `dist_comp_50d_vpoc` | - | 10.3% NaN |
| `dist_comp_50d_vpoc_atr` | - | 10.3% NaN |
| `dist_comp_50d_vwap` | - | 10.3% NaN |
| `dist_cur_vah` | - | 10.3% NaN |
| `dist_cur_val` | - | 10.3% NaN |
| `dist_cur_vpoc` | - | 10.3% NaN |
| `dist_cur_vwap_vp` | - | 10.3% NaN |
| `dist_ext_color_dn` | - | 10.3% NaN |
| `dist_ext_color_up` | - | 10.3% NaN |
| `dist_ext_edge_buy` | - | 12.2% NaN |
| `dist_ext_edge_sell` | - | 13.1% NaN |
| `dist_ext_long_dn` | - | 10.3% NaN |
| `dist_ext_long_up` | - | 10.3% NaN |
| `dist_gex_nearest_dn` | - | 10.3% NaN |
| `dist_gex_nearest_up` | - | 10.3% NaN |
| `dist_ib_high` | 75.3% NaN | 71.8% NaN |
| `dist_ib_low` | 75.3% NaN | 71.8% NaN |
| `dist_mq_call` | - | 10.3% NaN |
| `dist_mq_call_0dte` | - | 10.3% NaN |
| `dist_mq_hvl` | - | 10.3% NaN |
| `dist_mq_put` | - | 10.3% NaN |
| `dist_mq_put_0dte` | - | 10.3% NaN |
| `dist_open_830` | - | 10.3% NaN |
| `dist_ovn_high` | - | 10.3% NaN |
| `dist_ovn_low` | - | 10.3% NaN |
| `dist_prev_vah` | - | 10.3% NaN |
| `dist_prev_val` | - | 10.3% NaN |
| `dist_prev_vpoc` | - | 10.3% NaN |
| `dist_prev_vpoc_atr` | - | 10.3% NaN |
| `dist_prev_vwap` | - | 10.3% NaN |
| `dist_prev_vwap_sd1d` | - | 10.3% NaN |
| `dist_prev_vwap_sd1u` | - | 10.3% NaN |
| `dist_sess_high` | - | 10.3% NaN |
| `dist_sess_low` | - | 10.3% NaN |
| `dist_session_hvn_above` | 57.7% NaN | 59.6% NaN |
| `dist_session_hvn_below` | 13.9% NaN | 18.4% NaN |
| `dist_session_lvn_above` | - | 17.9% NaN |
| `dist_swing_high` | - | 10.4% NaN |
| `dist_swing_low` | - | 10.4% NaN |
| `dist_vix_call` | - | 10.3% NaN |
| `dist_vix_call_0dte` | - | 14.2% NaN |
| `dist_vix_gex_nearest_dn` | - | 10.3% NaN |
| `dist_vix_gex_nearest_up` | - | 10.3% NaN |
| `dist_vix_hvl` | - | 10.3% NaN |
| `dist_vix_put` | - | 10.3% NaN |
| `dist_vwap_d` | - | 10.3% NaN |
| `dist_vwap_d_atr` | - | 10.3% NaN |
| `dist_vwap_d_sd1d` | - | 10.3% NaN |
| `dist_vwap_d_sd1u` | - | 10.3% NaN |
| `dist_vwap_d_sd2d` | - | 10.3% NaN |
| `dist_vwap_d_sd2u` | - | 10.3% NaN |
| `dist_vwap_d_sd3d` | - | 10.3% NaN |
| `dist_vwap_d_sd3u` | - | 10.3% NaN |
| `dist_vwap_m` | - | 10.3% NaN |
| `dist_vwap_m_atr` | - | 10.3% NaN |
| `dist_vwap_w` | - | 10.3% NaN |
| `dist_vwap_w_atr` | - | 10.3% NaN |
| `ib_range_atr` | 75.3% NaN | 71.8% NaN |
| `next_wall_dist_ticks` | - | 10.3% NaN |
| `open_gap_ticks` | - | 10.3% NaN |
| `range_pos` | - | 10.3% NaN |
| `range_size_ticks` | - | 10.3% NaN |
| `sess_range_atr` | - | 10.3% NaN |

## ⚡ Features EVENT-BASED (rare, legitime)

| Feature | Raison ES | Raison NQ |
|---|---|---|
| `bar_long_up_bar` | - | fire 4.95% (rare, legitime) |
| `big_ask_cluster_20t_t4` | fire 1.70% (rare, legitime) | - |
| `bn_absorb_ask` | fire 1.78% (rare, legitime) | fire 2.09% (rare, legitime) |
| `bn_absorb_bid` | fire 1.87% (rare, legitime) | fire 1.31% (rare, legitime) |
| `bn_long_dn` | fire 2.76% (rare, legitime) | - |
| `bn_long_up` | fire 3.33% (rare, legitime) | - |
| `bn_volume_dn` | fire 4.46% (rare, legitime) | - |
| `bn_volume_up` | fire 3.97% (rare, legitime) | - |
| `bool_gex_flip_zone` | fire 2.68% (rare, legitime) | - |
| `new_swing_high` | fire 2.03% (rare, legitime) | fire 1.85% (rare, legitime) |
| `new_swing_low` | fire 1.54% (rare, legitime) | fire 1.08% (rare, legitime) |
| `open_in_prev_va` | - | fire 1.62% (rare, legitime) |
| `retest_high_delta_div` | - | fire 2.09% (rare, legitime) |
| `retest_low_delta_div` | fire 4.38% (rare, legitime) | - |
| `rvol_absorb_buy` | fire 1.87% (rare, legitime) | - |
| `rvol_absorb_sell` | fire 1.78% (rare, legitime) | - |
| `rvol_buy` | fire 2.76% (rare, legitime) | fire 3.17% (rare, legitime) |
| `rvol_sell` | fire 3.97% (rare, legitime) | fire 2.63% (rare, legitime) |
| `val_touches_20b` | - | fire 2.40% (rare, legitime) |
| `vwap_ma_align` | - | fire 2.40% (rare, legitime) |

## ✅ Features PROPRES (variation normale)

| Feature | Raison ES | Raison NQ |
|---|---|---|
| `ask_bid_imbalance` | std=0.2248 uniq=1025 | std=0.2540 uniq=989 |
| `ask_pct` | std=0.1124 uniq=967 | std=0.1270 uniq=957 |
| `atr` | std=28.0201 uniq=89 | std=85.9842 uniq=172 |
| `avg_ask_size` | std=59.5078 uniq=681 | std=4.5496 uniq=784 |
| `avg_bid_size` | std=59.4902 uniq=683 | std=4.2112 uniq=775 |
| `avg_trade_size` | std=109.1672 uniq=825 | std=8.3164 uniq=959 |
| `bar_color_dn` | - | binaire fire 89.7% |
| `bar_color_up` | - | binaire fire 89.7% |
| `bar_duration_sec` | std=3.6518 uniq=26 | std=2.8585 uniq=22 |
| `bar_edge_buy` | binaire fire 14.9% | binaire fire 62.7% |
| `bar_edge_sell` | binaire fire 12.8% | binaire fire 56.7% |
| `bar_high` | std=14.7284 uniq=200 | std=93.9278 uniq=558 |
| `bar_long_dn_bar` | - | binaire fire 8.3% |
| `bar_low` | std=14.4328 uniq=203 | std=92.4426 uniq=566 |
| `bar_pressure_ask` | - | binaire fire 89.7% |
| `bar_pressure_bid` | - | binaire fire 89.7% |
| `bars_in_va` | std=42.3309 uniq=194 | std=52.7333 uniq=205 |
| `bid_pct` | std=0.1124 uniq=967 | std=0.1270 uniq=957 |
| `big_ask_cluster_20t` | std=8.7504 uniq=37 | std=5.5726 uniq=25 |
| `big_ask_cluster_20t_t1` | std=3.6015 uniq=17 | std=3.5618 uniq=18 |
| `big_ask_cluster_20t_t2` | std=3.5523 uniq=18 | std=2.8135 uniq=16 |
| `big_ask_cluster_20t_t3` | std=2.1448 uniq=14 | binaire fire 5.4% |
| `big_ask_cluster_50t` | std=9.5445 uniq=44 | std=6.2193 uniq=30 |
| `big_bid_cluster_20t` | std=12.5871 uniq=48 | std=6.1595 uniq=31 |
| `big_bid_cluster_20t_t1` | std=5.5026 uniq=21 | std=4.1544 uniq=21 |
| `big_bid_cluster_20t_t2` | std=5.4984 uniq=21 | std=2.8051 uniq=16 |
| `big_bid_cluster_20t_t3` | std=2.1353 uniq=12 | - |
| `big_bid_cluster_50t` | std=14.3334 uniq=56 | std=7.7581 uniq=38 |
| `bn_color_dn` | - | binaire fire 89.7% |
| `bn_color_dn_2` | binaire fire 11.7% | binaire fire 89.7% |
| `bn_color_up` | - | binaire fire 89.7% |
| `bn_color_up_2` | - | binaire fire 89.7% |
| `bn_long_dn` | - | binaire fire 16.8% |
| `bn_long_up` | - | binaire fire 14.5% |
| `bn_pressure_ask` | binaire fire 50.9% | binaire fire 89.7% |
| `bn_pressure_bid` | binaire fire 57.7% | binaire fire 86.2% |
| `bn_score_bear` | std=0.1061 uniq=7 | std=0.2397 uniq=5 |
| `bn_score_bull` | std=0.1103 uniq=6 | std=0.2375 uniq=4 |
| `bn_score_raw` | std=0.1252 uniq=11 | std=0.1306 uniq=8 |
| `bn_volume_dn` | - | binaire fire 9.4% |
| `bn_volume_up` | - | binaire fire 5.2% |
| `bool_above_cur_vpoc` | binaire fire 78.9% | binaire fire 63.2% |
| `bool_above_mq_call` | - | binaire fire 59.5% |
| `bool_above_mq_hvl` | - | binaire fire 89.7% |
| `bool_above_prev_vpoc` | - | binaire fire 89.7% |
| `bool_above_vwap_d` | - | binaire fire 87.3% |
| `bool_above_vwap_m` | - | binaire fire 89.7% |
| `bool_above_vwap_w` | - | binaire fire 89.7% |
| `bool_gex_flip_zone` | - | binaire fire 30.2% |
| `bool_ib_inside` | binaire fire 11.0% | binaire fire 6.4% |
| `bool_near_level` | binaire fire 82.4% | binaire fire 31.0% |
| `bool_session_early` | binaire fire 80.9% | binaire fire 77.4% |
| `buy_sell_ratio` | std=0.1124 uniq=967 | std=0.1270 uniq=957 |
| `buy_vol` | std=682.1684 uniq=530 | std=258.8749 uniq=432 |
| `comp_vpoc_align_20_50` | binaire fire 92.1% | binaire fire 89.7% |
| `cvd_bar_delta` | std=204.4163 uniq=403 | std=83.9869 uniq=306 |
| `cvd_day` | std=7592.5974 uniq=982 | std=6767.8152 uniq=953 |
| `cvd_ohlc_range` | std=2580.4986 uniq=21 | std=1681.8422 uniq=48 |
| `delta_bar` | std=203.4847 uniq=402 | std=83.9271 uniq=305 |
| `delta_bar_vol_norm` | std=0.2248 uniq=1026 | std=0.2540 uniq=989 |
| `delta_day` | std=2190.5318 uniq=961 | std=1335.5112 uniq=914 |
| `delta_divergence` | - | binaire fire 89.6% |
| `delta_pct` | std=0.2248 uniq=1026 | std=0.2540 uniq=989 |
| `diag_imbalance` | std=0.6210 uniq=792 | std=0.4962 uniq=864 |
| `diag_neg_delta` | std=203.2109 uniq=348 | std=80.5842 uniq=235 |
| `diag_pos_delta` | std=193.5913 uniq=330 | std=93.8249 uniq=251 |
| `dist_1d_max_ticks` | std=144.1531 uniq=249 | - |
| `dist_1d_min_ticks` | std=147.0758 uniq=249 | - |
| `dist_big_ask_nearest_dn` | - | std=4.9847 uniq=33 |
| `dist_big_ask_nearest_up` | - | std=5.6177 uniq=35 |
| `dist_big_bid_nearest_dn` | - | std=5.8082 uniq=39 |
| `dist_big_bid_nearest_up` | - | std=4.8628 uniq=33 |
| `dist_blind_nearest_dn` | std=22.9205 uniq=228 | - |
| `dist_blind_nearest_up` | std=243.3443 uniq=188 | - |
| `dist_comp_20d_vah` | std=70.0801 uniq=215 | - |
| `dist_comp_20d_val` | std=113.9092 uniq=233 | - |
| `dist_comp_20d_vpoc` | std=79.2254 uniq=217 | - |
| `dist_comp_20d_vpoc_atr` | std=0.4300 uniq=383 | - |
| `dist_comp_20d_vwap` | std=61.3345 uniq=1199 | - |
| `dist_comp_50d_vah` | std=52.7145 uniq=194 | - |
| `dist_comp_50d_val` | std=81.2175 uniq=213 | - |
| `dist_comp_50d_vpoc` | std=72.8656 uniq=213 | - |
| `dist_comp_50d_vpoc_atr` | std=0.4293 uniq=383 | - |
| `dist_comp_50d_vwap` | std=61.6718 uniq=1185 | - |
| `dist_cur_vah` | std=21.5543 uniq=113 | - |
| `dist_cur_val` | std=41.6776 uniq=185 | - |
| `dist_cur_vpoc` | std=38.0966 uniq=168 | - |
| `dist_cur_vwap_vp` | std=25.6990 uniq=1194 | - |
| `dist_ext_color_dn` | std=66.4324 uniq=205 | - |
| `dist_ext_color_up` | std=64.7066 uniq=215 | - |
| `dist_ext_edge_buy` | std=67.3965 uniq=94 | - |
| `dist_ext_edge_sell` | std=81.4311 uniq=103 | - |
| `dist_ext_long_dn` | std=23.7712 uniq=114 | - |
| `dist_ext_long_up` | std=12.8591 uniq=77 | - |
| `dist_gex_nearest_dn` | std=45.9691 uniq=138 | - |
| `dist_gex_nearest_up` | std=26.9420 uniq=97 | - |
| `dist_mq_call` | std=58.2514 uniq=212 | - |
| `dist_mq_call_0dte` | std=69.4362 uniq=222 | - |
| `dist_mq_hvl` | std=144.7027 uniq=249 | - |
| `dist_mq_put` | std=82.5387 uniq=213 | - |
| `dist_mq_put_0dte` | std=219.3001 uniq=249 | - |
| `dist_open_830` | std=126.4384 uniq=259 | - |
| `dist_open_cash` | std=31.2372 uniq=160 | std=225.5890 uniq=530 |
| `dist_ovn_high` | std=36.2832 uniq=161 | - |
| `dist_ovn_low` | std=38.4251 uniq=173 | - |
| `dist_prev_vah` | std=37.3997 uniq=170 | - |
| `dist_prev_val` | std=61.9017 uniq=217 | - |
| `dist_prev_vpoc` | std=57.1460 uniq=217 | - |
| `dist_prev_vpoc_atr` | std=1.0667 uniq=374 | - |
| `dist_prev_vwap` | std=49.3447 uniq=217 | - |
| `dist_prev_vwap_sd1d` | std=66.8821 uniq=217 | - |
| `dist_prev_vwap_sd1u` | std=38.5482 uniq=217 | - |
| `dist_sess_high` | std=20.6419 uniq=89 | - |
| `dist_sess_low` | std=37.1957 uniq=166 | - |
| `dist_session_lvn_above` | std=13.5491 uniq=58 | - |
| `dist_session_lvn_below` | std=16.7965 uniq=69 | std=83.5026 uniq=250 |
| `dist_swing_high` | std=19.6265 uniq=112 | - |
| `dist_swing_low` | std=19.8302 uniq=111 | - |
| `dist_vix_call` | std=0.2963 uniq=99 | - |
| `dist_vix_call_0dte` | std=0.7989 uniq=99 | - |
| `dist_vix_gex_nearest_dn` | std=0.2186 uniq=91 | - |
| `dist_vix_gex_nearest_up` | std=0.2678 uniq=93 | - |
| `dist_vix_hvl` | std=0.2430 uniq=99 | - |
| `dist_vix_put` | std=0.2752 uniq=99 | - |
| `dist_vwap_d` | std=25.6990 uniq=1195 | - |
| `dist_vwap_d_atr` | std=1.0588 uniq=741 | - |
| `dist_vwap_d_sd1d` | std=33.1774 uniq=1177 | - |
| `dist_vwap_d_sd1u` | std=19.5694 uniq=1183 | - |
| `dist_vwap_d_sd2d` | std=41.2779 uniq=1158 | - |
| `dist_vwap_d_sd2u` | std=16.3801 uniq=1180 | - |
| `dist_vwap_d_sd3d` | std=49.6972 uniq=1172 | - |
| `dist_vwap_d_sd3u` | std=17.7898 uniq=1178 | - |
| `dist_vwap_m` | std=49.8539 uniq=1203 | - |
| `dist_vwap_m_atr` | std=0.6576 uniq=745 | - |
| `dist_vwap_w` | std=29.7661 uniq=1207 | - |
| `dist_vwap_w_atr` | std=1.0558 uniq=766 | - |
| `finish_delta_pct` | std=0.3741 uniq=235 | std=0.3266 uniq=25 |
| `finish_strength` | std=54.0106 uniq=238 | std=29.4809 uniq=161 |
| `fp_edge_buy` | binaire fire 6.8% | binaire fire 43.4% |
| `fp_edge_sell` | binaire fire 6.5% | binaire fire 39.1% |
| `gex_cluster_count` | std=0.6001 uniq=3 | binaire fire 13.6% |
| `high_ask_vol_pct` | std=0.2266 uniq=304 | std=0.2690 uniq=36 |
| `high_pullback_delta` | std=32.4202 uniq=142 | std=8.0389 uniq=49 |
| `ib_broken_up` | binaire fire 13.6% | binaire fire 21.8% |
| `ib_complete` | binaire fire 19.1% | binaire fire 22.6% |
| `ib_is_narrow` | binaire fire 17.8% | binaire fire 17.2% |
| `ib_is_wide` | binaire fire 6.7% | - |
| `ib_position_pct` | std=0.5554 uniq=82 | std=0.4508 uniq=70 |
| `ib_range_ticks` | std=46.1316 uniq=16 | std=265.7613 uniq=23 |
| `inside_cur_va` | binaire fire 52.5% | binaire fire 53.9% |
| `large_trader_ratio` | std=0.5995 uniq=1065 | std=0.4182 uniq=1113 |
| `low_bid_vol_pct` | std=0.2245 uniq=276 | std=0.2672 uniq=31 |
| `low_pullback_delta` | std=21.8280 uniq=120 | std=5.0244 uniq=33 |
| `lvn_confluence_count` | std=1.5615 uniq=6 | std=1.3612 uniq=6 |
| `ma_trend` | - | binaire fire 89.7% |
| `momentum_3b` | std=1.0396 uniq=40 | std=5.1163 uniq=126 |
| `momentum_5b` | std=1.4558 uniq=49 | std=7.1953 uniq=170 |
| `n_big_ask_t1` | std=8.3837 uniq=21 | std=3.2559 uniq=15 |
| `n_big_ask_t2` | std=8.3904 uniq=15 | std=8.1966 uniq=11 |
| `n_big_ask_t3` | std=6.0166 uniq=19 | std=1.5807 uniq=9 |
| `n_big_ask_t4` | binaire fire 5.4% | - |
| `n_big_bid_t1` | std=8.3018 uniq=21 | std=3.2068 uniq=19 |
| `n_big_bid_t2` | std=8.3881 uniq=17 | std=8.3673 uniq=13 |
| `n_big_bid_t3` | std=5.6217 uniq=19 | std=1.3623 uniq=7 |
| `n_clusters_20t` | std=7.6448 uniq=19 | std=6.4196 uniq=21 |
| `n_clusters_50t` | std=8.5707 uniq=9 | std=7.9415 uniq=21 |
| `next_wall_dist_ticks` | std=25.1135 uniq=85 | - |
| `next_wall_is_call` | binaire fire 78.5% | binaire fire 30.4% |
| `open_bias_conf` | std=0.2359 uniq=4 | std=0.3102 uniq=3 |
| `open_direction` | binaire fire 84.4% | binaire fire 84.0% |
| `open_gap_ticks` | std=75.6609 uniq=4 | - |
| `open_in_prev_va` | binaire fire 83.1% | - |
| `open_position` | std=0.7478 uniq=2 | std=0.6479 uniq=2 |
| `open_type` | std=2.1710 uniq=5 | std=1.7049 uniq=3 |
| `open_zone` | std=1.5495 uniq=3 | - |
| `ovn_range_ticks` | std=17.3372 uniq=30 | std=206.5792 uniq=20 |
| `poc_bar_dist` | std=2.3830 uniq=19 | std=10.2249 uniq=58 |
| `poc_position` | std=0.1317 uniq=30 | std=0.1409 uniq=56 |
| `poc_separation_ticks` | - | std=40.0660 uniq=9 |
| `price` | std=14.6141 uniq=212 | std=93.3563 uniq=554 |
| `price_vs_swing_mid` | - | binaire fire 89.4% |
| `profile_hvn_dominant` | - | std=66.1465 uniq=9 |
| `profile_skew` | std=0.0694 uniq=242 | std=0.0716 uniq=242 |
| `range_pos` | std=21.3945 uniq=200 | - |
| `range_size_ticks` | std=24.7095 uniq=122 | - |
| `retest_high_count` | std=29.0630 uniq=35 | std=5.2354 uniq=10 |
| `retest_high_delta_div` | binaire fire 7.3% | - |
| `retest_low_count` | std=45.8026 uniq=35 | std=8.2822 uniq=11 |
| `rotation_dn` | - | binaire fire 89.7% |
| `rotation_up` | - | binaire fire 89.7% |
| `rotation_zz_osc` | std=1.1599 uniq=40 | std=5.3282 uniq=129 |
| `rvol` | std=0.8764 uniq=1176 | std=0.8463 uniq=1225 |
| `rvol_zscore` | std=1.0515 uniq=1194 | std=1.0425 uniq=1256 |
| `sell_vol` | std=678.5208 uniq=545 | std=245.9282 uniq=428 |
| `sess_range_atr` | std=3.8511 uniq=110 | - |
| `sess_range_ticks` | std=31.6116 uniq=41 | std=305.5261 uniq=65 |
| `session_hvn_count` | std=2.8451 uniq=7 | std=2.9796 uniq=11 |
| `session_lvn_count` | std=3.8051 uniq=8 | std=3.0224 uniq=10 |
| `single_print_count` | std=7.3968 uniq=23 | std=27.6984 uniq=64 |
| `single_print_mid` | std=11.6565 uniq=31 | std=75.1214 uniq=56 |
| `swing_range_ticks` | std=18.8845 uniq=43 | std=109.1963 uniq=61 |
| `ticks_count` | std=985.8893 uniq=609 | std=457.4114 uniq=543 |
| `total_vol` | std=1345.3930 uniq=677 | std=497.9458 uniq=569 |
| `trend_day_probability` | std=0.2420 uniq=5 | std=0.2405 uniq=5 |
| `va_position_pct` | std=0.8907 uniq=201 | std=0.8620 uniq=583 |
| `vah_touches_20b` | binaire fire 84.3% | binaire fire 32.0% |
| `val_touches_20b` | binaire fire 9.8% | - |
| `vix_level` | std=0.5643 uniq=99 | std=5.5332 uniq=101 |
| `vol_per_sec` | std=22.4233 uniq=1025 | std=8.2885 uniq=952 |
| `volume_imbalance` | std=0.5236 uniq=252 | std=0.3795 uniq=257 |
| `vwap_d_side` | - | binaire fire 89.7% |
| `vwap_m_side` | - | binaire fire 89.7% |
| `vwap_ma_align` | binaire fire 8.4% | - |
| `vwap_slope_10` | std=0.4272 uniq=658 | std=2.0348 uniq=787 |
| `vwap_slope_10_dir` | - | binaire fire 89.6% |
| `vwap_slope_30` | std=0.7876 uniq=658 | std=2.4672 uniq=934 |
| `vwap_w_side` | - | binaire fire 89.7% |
