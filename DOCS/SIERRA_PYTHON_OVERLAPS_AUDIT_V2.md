# Audit Overlaps Sierra DMP vs Python live_enriched — V2 ROBUST

**Date** : 2026-06-07
**Symbole** : NQ
**Jours audites** : 30 (20260406 -> 20260603)

## Note de gouvernance (post ml-trainer review 4/10)

**"Source de verite" -> "Source par defaut"** : suite verdict ml-trainer (5/5 controles FAIL strict, risque infrastructure-mining), la matrice est repositionnee comme **DEFAULT SENSIBLE** et NON comme autorite. Chaque decision SIERRA/PYTHON peut etre OVERRIDE feature-par-feature apres validation empirique (walk-forward 4-fold + feature_importance modeles ML).

La matrice est un point de depart pragmatique, pas une verite immuable. Les bugs identifies dans la chaine (CLAMP ATR, range_pos collision, finish_strength method) confirment que la "verite" est elle-meme contingente aux choix d'implementation.

**Source Python live_enriched** : **DATABENTO** (confirme `live_enricher_io.py:32` import live_cache)

## Corrections vs V1 (review code-reviewer)
- Median + p95 au lieu de max (eviter outliers session-edge)
- Filter artefacts denominator < 1e-3 (eviter inf%)
- Classification automatique cause (6 categories)
- Whitelist infrastructure (35 colonnes metadata/OHLCV)
- Multi-jour 30 jours stratifies
- Spearman cross-source (detecte CONVENTION-INVERSION)

## Stats globales

- Overlap features (apres filter infra) : **86**
- Sierra-only : **204**
- Python-only : **427**

## Distribution cause (classification automatique)

| Cause | Count |
|---|---|
| DIVERGENT-METHODE | 37 |
| MATCH | 23 |
| BUG-SIERRA-NULL | 6 |
| CONVENTION-INVERSION-DATABENTO | 5 |
| BUG-PYTHON-NULL | 4 |
| QUASI-MATCH | 3 |
| CONVENTION-INVERSION-UNKNOWN | 2 |
| ARTEFACT-NEAR-ZERO | 2 |
| UNITE-DIFF | 2 |

## Decision source de verite

| Decision | Count |
|---|---|
| INVESTIGATION-MANUELLE | 37 |
| SIERRA (Python redondant) | 23 |
| SIERRA | 9 |
| PYTHON | 6 |
| SIERRA (mineur) | 3 |
| INVESTIGATION-URGENTE | 2 |
| MATCH (denominator near-zero) | 2 |
| LES-DEUX-SELON-USAGE | 2 |

## Detail — DIVERGENT-METHODE

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `dist_vwap_m_atr` | 25 | 0.4 | 0.7 | 3841.2406 | 8049.9853 | nan | INVESTIGATION-MANUELLE |
| `dist_vwap_w_atr` | 25 | 0.4 | 0.7 | 1426.567 | 4062.7608 | 0.6975 | INVESTIGATION-MANUELLE |
| `dist_vwap_d_atr` | 25 | 0.4 | 0.0 | 964.7201 | 14571.1235 | 0.6979 | INVESTIGATION-MANUELLE |
| `dist_prev_vpoc_atr` | 7 | 0.0 | 3.3 | 868.3272 | 2560.6849 | 0.8127 | INVESTIGATION-MANUELLE |
| `finish_strength` | 26 | 0.0 | 0.0 | 498.8441 | 5020.094 | -0.4016 | INVESTIGATION-MANUELLE |
| `sess_range_atr` | 24 | 0.5 | 1.5 | 208.4559 | 1475.1732 | -0.1987 | INVESTIGATION-MANUELLE |
| `open_zone` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `open_type` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `rotation_dn` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `retest_low_delta_div` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `vix_above_hvl_0dte` | 20 | 0.0 | 6.7 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `bn_absorb_bid` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `bool_gex_flip_zone` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `momentum_5b` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `retest_high_delta_div` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `open_bias_conf` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `rvol_buy` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `inside_cur_va` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `rotation_up` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `rvol_sell` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `open_direction` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `rvol_absorb_buy` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `bn_absorb_ask` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `rvol_absorb_sell` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | INVESTIGATION-MANUELLE |
| `range_pos` | 25 | 0.4 | 0.6 | 99.3127 | 99.9697 | 0.0689 | INVESTIGATION-MANUELLE |
| `vwap_slope_10` | 26 | 0.0 | 0.8 | 95.4768 | 251.4161 | nan | INVESTIGATION-MANUELLE |
| `dist_vwap_d` | 25 | 0.4 | 0.0 | 91.3677 | 201.0699 | 0.7278 | INVESTIGATION-MANUELLE |
| `dist_cur_vah` | 7 | 0.0 | 0.0 | 88.0711 | 179.4118 | 0.7492 | INVESTIGATION-MANUELLE |
| `dist_cur_val` | 7 | 0.0 | 0.0 | 82.9891 | 159.5503 | 0.6859 | INVESTIGATION-MANUELLE |
| `dist_sess_low` | 25 | 0.4 | 0.0 | 80.9091 | 93.2006 | 0.4751 | INVESTIGATION-MANUELLE |
| `dist_sess_high` | 25 | 0.4 | 0.0 | 75.0 | 86.4426 | 0.8044 | INVESTIGATION-MANUELLE |
| `dist_cur_vpoc` | 7 | 0.0 | 0.0 | 75.0 | 319.5652 | 0.5402 | INVESTIGATION-MANUELLE |
| `va_position_pct` | 7 | 38.1 | 0.0 | 65.2324 | 239.8682 | 0.4496 | INVESTIGATION-MANUELLE |
| `poc_position` | 7 | 0.0 | 0.0 | 44.4252 | 126.0909 | -0.0241 | INVESTIGATION-MANUELLE |
| `dist_vix_put` | 19 | 0.6 | 7.0 | 43.9563 | 49.14 | 0.9999 | INVESTIGATION-MANUELLE |
| `dist_vix_hvl_0dte` | 12 | 0.0 | 5.8 | 38.4275 | 50.3807 | 1.0 | INVESTIGATION-MANUELLE |
| `dist_vix_hvl` | 19 | 0.6 | 7.0 | 19.3798 | 25.0 | 0.9999 | INVESTIGATION-MANUELLE |

## Detail — MATCH

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `rvol` | 26 | 0.0 | 0.0 | 0.0027 | 0.0102 | 1.0 | SIERRA (Python redondant) |
| `dist_1d_min_ticks` | 14 | 0.0 | 7.1 | 0.0015 | 0.0027 | 1.0 | SIERRA (Python redondant) |
| `dist_1d_max_ticks` | 14 | 0.0 | 7.1 | 0.0014 | 0.0032 | 1.0 | SIERRA (Python redondant) |
| `ib_complete` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `total_vol` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | SIERRA (Python redondant) |
| `vwap_d_side` | 26 | 0.0 | 0.0 | 0.0 | 200.0 | nan | SIERRA (Python redondant) |
| `vix_regime` | 20 | 0.0 | 6.7 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `vix_above_hvl` | 20 | 0.0 | 6.7 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `ib_broken_down` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `session` | 26 | 0.0 | 0.0 | 0.0 | 50.0 | nan | SIERRA (Python redondant) |
| `day_type` | 26 | 0.0 | 0.0 | 0.0 | 16.6667 | nan | SIERRA (Python redondant) |
| `ib_broken_up` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `bar_high` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | SIERRA (Python redondant) |
| `ts` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | SIERRA (Python redondant) |
| `vix_level` | 20 | 0.0 | 6.7 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `bar_low` | 26 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | SIERRA (Python redondant) |
| `dist_vix_call` | 19 | 0.6 | 7.0 | 0.0 | 0.0 | 0.9999 | SIERRA (Python redondant) |
| `next_wall_dist_ticks` | 17 | 0.0 | 3.7 | 0.0 | 95.7262 | 0.5135 | SIERRA (Python redondant) |
| `mq_pc_dex` | 2 | 0.0 | 0.0 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `mq_iv_30d` | 2 | 0.0 | 0.0 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `mq_pc_gex` | 2 | 0.0 | 0.0 | 0.0 | 0.0 | nan | SIERRA (Python redondant) |
| `dist_vix_gex_nearest_dn` | 1 | 0.0 | 0.0 | 0.0 | 2.3256 | 0.9812 | SIERRA (Python redondant) |
| `dist_vix_gex_nearest_up` | 1 | 0.0 | 0.0 | 0.0 | 1.7544 | 0.9829 | SIERRA (Python redondant) |

## Detail — BUG-SIERRA-NULL

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `ib_range_atr` | 22 | 67.4 | 53.5 | 970.1848 | 1456.3583 | nan | PYTHON |
| `bars_since_retest_low` | 25 | 77.7 | 0.0 | 100.0 | 2408.0 | nan | PYTHON |
| `bars_since_retest_high` | 25 | 72.3 | 0.0 | 100.0 | 100.0 | 0.0552 | PYTHON |
| `dist_ib_high` | 22 | 67.4 | 53.5 | 75.0 | 75.0 | 1.0 | PYTHON |
| `dist_ib_low` | 22 | 67.4 | 53.5 | 75.0 | 75.0 | 1.0 | PYTHON |
| `ib_position_pct` | 21 | 52.2 | 52.7 | 0.0188 | 2.787 | 1.0 | PYTHON |

## Detail — CONVENTION-INVERSION-DATABENTO

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `delta_pct` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | SIERRA |
| `delta_day_dir` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | SIERRA |
| `cvd_day` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | SIERRA |
| `delta_bar` | 26 | 0.0 | 0.0 | 100.0 | 100.0 | nan | SIERRA |
| `delta_day` | 25 | 0.0 | 1.4 | 100.0 | 100.0 | nan | SIERRA |

## Detail — BUG-PYTHON-NULL

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `profile_skew` | 1 | 0.0 | 97.8 | 2878.2295 | 11884.2795 | -0.9428 | SIERRA |
| `ovn_range_ticks` | 23 | 0.0 | 66.3 | 31.1671 | 329.2838 | nan | SIERRA |
| `ib_range_ticks` | 26 | 0.0 | 55.0 | 0.0 | 0.0 | nan | SIERRA |
| `profile_shape` | 1 | 0.0 | 97.8 | 0.0 | 0.0 | nan | SIERRA |

## Detail — QUASI-MATCH

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `dist_vwap_w` | 25 | 0.4 | 0.7 | 4.6027 | 15.4979 | 0.9999 | SIERRA (mineur) |
| `dist_vwap_m` | 25 | 0.4 | 0.7 | 3.7954 | 6.0818 | 0.9999 | SIERRA (mineur) |
| `rvol_zscore` | 26 | 0.0 | 0.0 | 2.5308 | 2.5645 | 1.0 | SIERRA (mineur) |

## Detail — CONVENTION-INVERSION-UNKNOWN

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `dist_swing_low` | 25 | 0.4 | 0.5 | 125.0 | 206.5 | -0.8021 | INVESTIGATION-URGENTE |
| `dist_swing_high` | 25 | 0.4 | 0.5 | 125.0 | 172.4371 | -0.8844 | INVESTIGATION-URGENTE |

## Detail — ARTEFACT-NEAR-ZERO

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `session_id` | 26 | 0.0 | 0.0 | nan | nan | nan | MATCH (denominator near-zero) |
| `mq_gamma_condition` | 1 | 0.0 | 0.0 | nan | nan | nan | MATCH (denominator near-zero) |

## Detail — UNITE-DIFF

| Feature | n_days | Sierra null % | Py null % | median rel % | p95 rel % | Spearman | Source verite |
|---|---|---|---|---|---|---|---|
| `atr` | 26 | 0.0 | 0.0 | 93.42 | 96.3067 | 0.4514 | LES-DEUX-SELON-USAGE |
| `atr_14m` | 12 | 0.0 | 1.3 | 74.3925 | 75.0024 | nan | LES-DEUX-SELON-USAGE |

## Sierra-only features uniques (filtre infra)

- `ask_bid_imbalance`
- `ask_pct`
- `avg_ask_size`
- `avg_bid_size`
- `avg_trade_size`
- `bar_color_dn`
- `bar_color_up`
- `bar_duration_sec`
- `bar_edge_buy`
- `bar_edge_sell`
- `bar_long_dn_bar`
- `bar_long_dn_up`
- `bar_long_up_bar`
- `bar_long_up_dn`
- `bar_pressure_ask`
- `bar_pressure_bid`
- `bars_in_va`
- `bid_pct`
- `big_ask_cluster_20t`
- `big_ask_cluster_20t_t1`
- `big_ask_cluster_20t_t2`
- `big_ask_cluster_20t_t3`
- `big_ask_cluster_20t_t4`
- `big_ask_cluster_50t`
- `big_bid_cluster_20t`
- `big_bid_cluster_20t_t1`
- `big_bid_cluster_20t_t2`
- `big_bid_cluster_20t_t3`
- `big_bid_cluster_20t_t4`
- `big_bid_cluster_50t`
- `bn_color_dn`
- `bn_color_dn_2`
- `bn_color_up`
- `bn_color_up_2`
- `bn_long_dn`
- `bn_long_up`
- `bn_pressure_ask`
- `bn_pressure_bid`
- `bn_score_bear`
- `bn_score_bull`
- `bn_score_raw`
- `bn_volume_dn`
- `bn_volume_up`
- `bool_above_cur_vpoc`
- `bool_above_mq_call`
- `bool_above_mq_hvl`
- `bool_above_prev_vpoc`
- `bool_above_vwap_d`
- `bool_above_vwap_m`
- `bool_above_vwap_w`
- `bool_ib_inside`
- `bool_near_level`
- `bool_session_early`
- `bool_va_confluence`
- `buy_sell_ratio`
- `buy_vol`
- `comp_vpoc_align_20_50`
- `comp_vpoc_align_day_20`
- `cvd_bar_delta`
- `cvd_day_dir`
- `cvd_ohlc_range`
- `delta_bar_vol_norm`
- `delta_day`
- `delta_divergence`
- `diag_imbalance`
- `diag_neg_delta`
- `diag_pos_delta`
- `dist_1d_max_ticks`
- `dist_1d_min_ticks`
- `dist_big_ask_nearest_dn`
- `dist_big_ask_nearest_up`
- `dist_big_bid_nearest_dn`
- `dist_big_bid_nearest_up`
- `dist_blind_nearest_dn`
- `dist_blind_nearest_up`
- `dist_cluster_nearest_dn`
- `dist_cluster_nearest_up`
- `dist_comp_20d_vah`
- `dist_comp_20d_val`
- `dist_comp_20d_vpoc`
- `dist_comp_20d_vpoc_atr`
- `dist_comp_20d_vwap`
- `dist_comp_50d_vah`
- `dist_comp_50d_val`
- `dist_comp_50d_vpoc`
- `dist_comp_50d_vpoc_atr`
- `dist_comp_50d_vwap`
- `dist_cur_vwap_vp`
- `dist_ext_color_dn`
- `dist_ext_color_up`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `dist_ext_long_dn`
- `dist_ext_long_up`
- `dist_gex_nearest_dn`
- `dist_gex_nearest_up`
- `dist_mq_call`
- `dist_mq_call_0dte`
- `dist_mq_hvl`
- `dist_mq_hvl_0dte`
- `dist_mq_put`
- `dist_mq_put_0dte`
- `dist_open_830`
- `dist_open_cash`
- `dist_ovn_high`
- `dist_ovn_low`
- `dist_prev_vah`
- `dist_prev_val`
- `dist_prev_vpoc`
- `dist_prev_vpoc_atr`
- `dist_prev_vwap`
- `dist_prev_vwap_sd1d`
- `dist_prev_vwap_sd1u`
- `dist_session_hvn_above`
- `dist_session_hvn_below`
- `dist_session_lvn_above`
- `dist_session_lvn_below`
- `dist_vix_call`
- `dist_vix_call_0dte`
- `dist_vix_gex_nearest_dn`
- `dist_vix_gex_nearest_up`
- `dist_vix_hvl`
- `dist_vix_hvl_0dte`
- `dist_vix_put`
- `dist_vix_put_0dte`
- `dist_vwap_d_sd1d`
- `dist_vwap_d_sd1u`
- `dist_vwap_d_sd2d`
- `dist_vwap_d_sd2u`
- `dist_vwap_d_sd3d`
- `dist_vwap_d_sd3u`
- `finish_delta_pct`
- `fp_edge_buy`
- `fp_edge_sell`
- `gex_cluster_count`
- `high_ask_vol_pct`
- `high_pullback_delta`
- `hvn_between`
- `ib_is_narrow`
- `ib_is_wide`
- `inside_comp_20d_va`
- `inside_comp_50d_va`
- `inside_prev_va`
- `is_double_dist`
- `large_trader_ratio`
- `low_bid_vol_pct`
- `low_pullback_delta`
- `lvn_between`
- `lvn_confluence_count`
- `ma_trend`
- `momentum_3b`
- `mq_net_gex_norm`
- `n_big_ask_t1`
- `n_big_ask_t2`
- `n_big_ask_t3`
- `n_big_ask_t4`
- `n_big_bid_t1`
- `n_big_bid_t2`
- `n_big_bid_t3`
- `n_big_bid_t4`
- `n_clusters_20t`
- `n_clusters_50t`
- `new_swing_high`
- `new_swing_low`
- `next_wall_is_call`
- `open_gap_ticks`
- `open_in_prev_va`
- `open_position`
- `poc_bar_dist`
- `poc_separation_ticks`
- `price`
- `price_vs_swing_mid`
- `profile_hvn_dominant`
- `profile_shape`
- `profile_skew`
- `range_size_ticks`
- `retest_high_count`
- `retest_low_count`
- `rotation_zz_osc`
- `rule_80pct`
- `sell_vol`
- `sess_range_atr`
- `sess_range_ticks`
- `session_hvn_count`
- `session_lvn_count`
- `single_print_count`
- `single_print_mid`
- `swing_range_ticks`
- `ticks_count`
- `trend_day_probability`
- `vah_touches_20b`
- `val_touches_20b`
- `vix_above_hvl`
- `vix_above_hvl_0dte`
- `vix_level`
- `vix_regime`
- `vol_per_sec`
- `volume_imbalance`
- `vwap_m_side`
- `vwap_ma_align`
- `vwap_slope_10_dir`
- `vwap_slope_30`
- `vwap_triple_align`
- `vwap_w_side`

**Total Sierra-only utiles** : 204

## Python-only features uniques (filtre infra)

- `above_after_open`
- `above_asia_open`
- `above_london_open`
- `above_ny_open`
- `above_open_830`
- `above_open_930`
- `after_high`
- `after_low`
- `after_open`
- `after_open_approximate`
- `aggressor_imbalance`
- `asia_high`
- `asia_low`
- `asia_open`
- `asia_open_approximate`
- `atr_14m`
- `atr_14m_pct`
- `atr_regime_zscore_60d`
- `bar_body_pct`
- `bar_body_ticks`
- `bar_lower_wick_pct`
- `bar_no_trade`
- `bar_upper_wick_pct`
- `bars_since_last_spike`
- `bars_since_last_swing_high`
- `bars_since_last_swing_low`
- `big_buy_dominance`
- `big_sell_dominance`
- `bn_absorb_ask_at_level`
- `bn_absorb_ask_raw`
- `bn_absorb_bid_at_level`
- `bn_absorb_bid_raw`
- `bn_stack_ask`
- `bn_stack_bid`
- `bn_trapped_buyers_at_resistance`
- `bn_trapped_buyers_raw`
- `bn_trapped_sellers_at_support`
- `bn_trapped_sellers_raw`
- `cash_high`
- `cash_low`
- `cluster_at_high`
- `cluster_at_low`
- `ctx_absorption_score_5`
- `ctx_absorption_streak_5`
- `ctx_bars_since_div`
- `ctx_climax_signal`
- `ctx_cvd_recovery_rate`
- `ctx_cvd_session`
- `ctx_day_type_intensity`
- `ctx_delta_exhaustion`
- `ctx_delta_slope_5`
- `ctx_delta_sum_10`
- `ctx_delta_sum_3`
- `ctx_dist_vwap_velocity`
- `ctx_div_at_swing`
- `ctx_div_density_20`
- `ctx_double_top_trap`
- `ctx_excess_high_bars`
- `ctx_excess_low_bars`
- `ctx_failed_auction`
- `ctx_finish_strength_mean_5`
- `ctx_ib_extension_ratio`
- `ctx_ib_position_velocity`
- `ctx_instant_absorption`
- `ctx_momentum_exhaustion`
- `ctx_mq_put_call_ratio`
- `ctx_poc_migration_10`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_price_delta_div_3`
- `ctx_price_slope_5`
- `ctx_range_vs_atr_10`
- `ctx_rotation_factor_20`
- `ctx_rvol_session`
- `ctx_session_phase`
- `ctx_side_flip_count_10`
- `ctx_trend_day_score`
- `ctx_va_developing_10`
- `ctx_va_position_velocity`
- `ctx_va_width`
- `ctx_vol_sell_buy_ratio_5`
- `ctx_vol_slope_5`
- `ctx_vol_z_5`
- `ctx_vwap_slope_accel`
- `cur_pdh`
- `cur_pdl`
- `cur_va_n_buckets`
- `cur_va_total_vol`
- `cur_vah`
- `cur_val`
- `cur_vpoc`
- `cvd_5d_rolling_ffd`
- `cvd_session`
- `days_since_roll`
- `delta_change`
- `delta_div_buy`
- `delta_div_buy_clean`
- `delta_div_sell`
- `delta_div_sell_clean`
- `delta_div_strength`
- `delta_divergence_clean`
- `diag_imbalance_ofi_proxy`
- `discount_zone`
- `dist_1d_max_ticks_pct`
- `dist_1d_min_ticks_pct`
- `dist_after_high_pct`
- `dist_after_low_pct`
- `dist_after_open_pct`
- `dist_asia_high_pct`
- `dist_asia_low_pct`
- `dist_asia_open_pct`
- `dist_big_ask_nearest_pct`
- `dist_big_bid_nearest_pct`
- `dist_cash_high_pct`
- `dist_cash_low_pct`
- `dist_cluster_nearest_dn_pct`
- `dist_cluster_nearest_up_pct`
- `dist_color_dn_nearest_pct`
- `dist_color_up_nearest_pct`
- `dist_cur_vah_atr`
- `dist_cur_vah_pct`
- `dist_cur_val_atr`
- `dist_cur_val_pct`
- `dist_cur_vpoc_atr`
- `dist_cur_vpoc_pct`
- `dist_delta_div_buy_nearest_pct`
- `dist_delta_div_sell_nearest_pct`
- `dist_edge_buy_nearest_pct`
- `dist_edge_sell_nearest_pct`
- `dist_gex_nearest_dn_pct`
- `dist_gex_nearest_up_pct`
- `dist_ib_high_atr`
- `dist_ib_high_pct`
- `dist_ib_low_atr`
- `dist_ib_low_pct`
- `dist_last_spike_origin_pct`
- `dist_last_swing_high_pct`
- `dist_last_swing_low_pct`
- `dist_london_high_pct`
- `dist_london_low_pct`
- `dist_london_open_pct`
- `dist_long_dn_nearest_pct`
- `dist_long_up_nearest_pct`
- `dist_mq_call_0dte_pct`
- `dist_mq_call_atr`
- `dist_mq_call_pct`
- `dist_mq_hvl_0dte_pct`
- `dist_mq_hvl_atr`
- `dist_mq_hvl_pct`
- `dist_mq_put_0dte_pct`
- `dist_mq_put_atr`
- `dist_mq_put_pct`
- `dist_naked_poc_nearest_pct`
- `dist_ny_open_pct`
- `dist_open_830_pct`
- `dist_open_930_pct`
- `dist_ovn_high_pct`
- `dist_ovn_low_pct`
- `dist_pdh_atr`
- `dist_pdh_pct`
- `dist_pdl_atr`
- `dist_pdl_pct`
- `dist_prev_vah_atr`
- `dist_prev_vah_pct`
- `dist_prev_val_atr`
- `dist_prev_val_pct`
- `dist_prev_vpoc_pct`
- `dist_pvwap_pct`
- `dist_pvwap_sd1d_pct`
- `dist_pvwap_sd1u_pct`
- `dist_sess_high_atr`
- `dist_sess_high_pct`
- `dist_sess_low_atr`
- `dist_sess_low_pct`
- `dist_trapped_buyers_nearest_pct`
- `dist_trapped_sellers_nearest_pct`
- `dist_us_high_pct`
- `dist_us_low_pct`
- `dist_vix_gamma_wall_0dte`
- `dist_vwap_d_pct`
- `dist_vwap_d_sd1d_pct`
- `dist_vwap_d_sd1u_pct`
- `dist_vwap_d_sd2d_pct`
- `dist_vwap_d_sd2u_pct`
- `dist_vwap_m_pct`
- `dist_vwap_m_sd1d_pct`
- `dist_vwap_m_sd1u_pct`
- `dist_vwap_m_sd2d_pct`
- `dist_vwap_m_sd2u_pct`
- `dist_vwap_w_pct`
- `dist_vwap_w_sd1d_pct`
- `dist_vwap_w_sd1u_pct`
- `dist_vwap_w_sd2d_pct`
- `dist_vwap_w_sd2u_pct`
- `div_at_key_level_ticks`
- `div_confluence_dmp`
- `div_confluence_with_regime`
- `div_regime_proxy_ok`
- `equal_highs_detected`
- `equal_lows_detected`
- `finish_pct_up`
- `finish_strong_dn`
- `finish_strong_up`
- `ib_broken_dn`
- `ib_high`
- `ib_low`
- `ib_range`
- `im_cross_delta_agreement_5`
- `im_cross_delta_weighted_5`
- `im_cross_open_signal`
- `im_delta_day_divergence`
- `im_ltr_slope_diff`
- `im_open_type_agreement`
- `im_price_ratio_slope_10`
- `im_rolling_correlation_10`
- `im_smt_divergence`
- `im_volume_lead`
- `inside_value_area`
- `is_cash_session`
- `is_ib_window`
- `is_in_asia`
- `is_in_london`
- `is_in_us_after`
- `is_in_us_cash`
- `is_new_cash_high`
- `is_new_cash_low`
- `is_new_sess_high`
- `is_new_sess_low`
- `is_news_715`
- `is_news_730`
- `is_news_830`
- `is_news_845`
- `is_news_900`
- `is_news_930`
- `is_roll_day`
- `itten_at_iso`
- `large_trader_max_size_proxy`
- `last_swing_high_session`
- `last_swing_low_session`
- `liquidity_sweep_high_lag5`
- `liquidity_sweep_low_lag5`
- `london_high`
- `london_low`
- `london_open`
- `london_open_approximate`
- `long_dn_bar`
- `long_dn_up_pattern`
- `long_up_bar`
- `long_up_dn_pattern`
- `max_big_ask_vol_in_bar`
- `max_big_bid_vol_in_bar`
- `max_cluster_size`
- `max_cluster_volume`
- `max_cluster_volume_v2`
- `max_delta_bar`
- `max_size_buy`
- `max_size_sell`
- `min_delta_bar`
- `mins_since_news`
- `mins_to_next_news`
- `mq_1d_max`
- `mq_1d_min`
- `mq_blind`
- `mq_call`
- `mq_call_0dte`
- `mq_gamma_condition`
- `mq_gamma_wall_0dte`
- `mq_gex`
- `mq_hvl`
- `mq_hvl_0dte`
- `mq_iv_30d`
- `mq_net_dex`
- `mq_net_gex`
- `mq_pc_dex`
- `mq_pc_gex`
- `mq_pc_oi`
- `mq_put`
- `mq_put_0dte`
- `mq_total_dex`
- `mq_total_gex`
- `n_big_ask_v2_t1`
- `n_big_ask_v2_t2`
- `n_big_ask_v2_t3`
- `n_big_ask_v2_t4`
- `n_big_bid_v2_t1`
- `n_big_bid_v2_t2`
- `n_big_bid_v2_t3`
- `n_big_bid_v2_t4`
- `n_big_buy_t1`
- `n_big_buy_t2`
- `n_big_buy_t3`
- `n_big_buy_t4`
- `n_big_sell_t1`
- `n_big_sell_t2`
- `n_big_sell_t3`
- `n_big_sell_t4`
- `n_big_t1`
- `n_big_t2`
- `n_big_t3`
- `n_big_t4`
- `n_cluster_groups`
- `n_clusters`
- `n_color_dn_cluster_within_0_2pct`
- `n_color_up_cluster_within_0_2pct`
- `n_delta_div_buy_cluster_within_0_2pct`
- `n_delta_div_buy_zones_active`
- `n_delta_div_sell_cluster_within_0_2pct`
- `n_delta_div_sell_zones_active`
- `n_edge_buy_active`
- `n_edge_sell_active`
- `n_long_dn_cluster_within_0_2pct`
- `n_long_dn_zones_active`
- `n_long_up_cluster_within_0_2pct`
- `n_long_up_zones_active`
- `n_spike_origins_active`
- `n_spike_origins_cluster_within_0_2pct`
- `n_ticks_bar`
- `n_trapped_buyers_cluster_within_0_2pct`
- `n_trapped_buyers_zones_active`
- `n_trapped_sellers_cluster_within_0_2pct`
- `n_trapped_sellers_zones_active`
- `near_resistance_level`
- `near_support_level`
- `ny_open`
- `ny_open_approximate`
- `open_830_et`
- `open_930_et`
- `open_cash`
- `ovn_broken_dn`
- `ovn_broken_up`
- `ovn_high`
- `ovn_low`
- `p99_trade_size`
- `pct_in_range`
- `pdh`
- `pdl`
- `poc_migration_dir`
- `position_in_range`
- `premium_zone`
- `prev_vah`
- `prev_val`
- `prev_vpoc`
- `price_1030`
- `pvwap`
- `pvwap_sd1d`
- `pvwap_sd1u`
- `range_h_minus_lprev_ticks`
- `range_hprev_minus_l_ticks`
- `range_size`
- `regime_actionable`
- `regime_confidence`
- `regime_favor`
- `regime_mode`
- `regime_range_votes`
- `regime_trend_votes`
- `regime_vol`
- `roll_phase`
- `rvol_buy_strong`
- `rvol_extreme`
- `rvol_regime`
- `rvol_sell_strong`
- `sess_high`
- `sess_low`
- `session_segment`
- `spike_detected_lag3`
- `swing_high_active_lag10`
- `swing_low_active_lag10`
- `us_high`
- `us_low`
- `vix_1d_max`
- `vix_1d_min`
- `vix_call`
- `vix_call_0dte`
- `vix_gamma_wall_0dte`
- `vix_gex`
- `vix_gex_0`
- `vix_gex_1`
- `vix_gex_2`
- `vix_gex_3`
- `vix_gex_4`
- `vix_gex_5`
- `vix_gex_6`
- `vix_gex_7`
- `vix_gex_8`
- `vix_gex_9`
- `vix_hvl`
- `vix_hvl_0dte`
- `vix_put`
- `vix_put_0dte`
- `vol_spike_dn`
- `vol_spike_up`
- `vol_zscore_20`
- `vwap_d`
- `vwap_d_cross_dn`
- `vwap_d_cross_up`
- `vwap_d_sd1_above`
- `vwap_d_sd1_below`
- `vwap_d_sd1d`
- `vwap_d_sd1u`
- `vwap_d_sd2_above`
- `vwap_d_sd2_below`
- `vwap_d_sd2d`
- `vwap_d_sd2u`
- `vwap_d_sd3d`
- `vwap_d_sd3u`
- `vwap_m`
- `vwap_m_sd1d`
- `vwap_m_sd1u`
- `vwap_m_sd2d`
- `vwap_m_sd2u`
- `vwap_m_sd3d`
- `vwap_m_sd3u`
- `vwap_slope_10_atr`
- `vwap_w`
- `vwap_w_sd1d`
- `vwap_w_sd1u`
- `vwap_w_sd2d`
- `vwap_w_sd2u`
- `vwap_w_sd3d`
- `vwap_w_sd3u`
- `within_news_715_5m`
- `within_news_730_5m`
- `within_news_830_5m`
- `within_news_845_5m`
- `within_news_900_5m`
- `within_news_930_5m`
- `wwrritten_at_iso`

**Total Python-only utiles** : 427