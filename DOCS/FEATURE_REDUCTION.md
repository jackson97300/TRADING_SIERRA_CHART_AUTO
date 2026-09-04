# Reduction de features — le noyau non redondant

Genere par `CORE/research/feature_reduction.py`.

**Ce que ce document repond** : quelles features apportent une information que les autres n'apportent pas deja.

**Ce qu'il ne dit PAS** : lesquelles sont rentables. Cette question demande une cible, un walk-forward et un DSR — elle est traitee ailleurs. La selection ci-dessous porte sur la *redondance*, jamais sur la performance : c'est ce qui la protege du data mining.

Methode : nettoyage (vides, constantes, prix absolus, horloges de session), distance `1 - |rho de Spearman|`, clustering hierarchique average coupe a **0.70**, un representant central par cluster. Validation par decoupage **temporel** 80/20 — les clusters sont appris sur les barres les plus anciennes et verifies sur les plus recentes, jamais regardees.

## ES

609 colonnes au depart, 452 apres nettoyage, **224 features retenues** (15649 barres, 12519 train / 3130 test).

### Balayage de seuils

| seuil de correlation | clusters | regroupements |
|---|---|---|
| 0.50 | 147 | 55 |
| 0.60 | 180 | 72 |
| 0.70 **(retenu)** | 221 | 76 |
| 0.80 | 254 | 81 |

### Ecartees au nettoyage

| motif | nombre | exemples |
|---|---|---|
| prix absolu | 72 | `price` (mediane 7679.5 ~ prix 7679.5), `open` (mediane 7679.5 ~ prix 7679.5), `cvd_ohlc_range` (mediane 9245.0 ~ prix 7679.5) |
| suspectee horloge, PROFIL INSTABLE -> gardee brute | 48 | `dist_vwap_d` (x8.0, derive train->test 98 % : l'heure ne la determine pas), `dist_vwap_d_atr` (x7.9, derive train->test 132 % : l'heure ne la determine pas), `dist_vwap_d_sd1u` (x6.8, derive train->test 37 % : l'heure ne la determine pas) |
| NORMALISEE par l'heure (recuperee) | 45 | `atr_14m_hnorm` (atr_14m — ratio a la mediane par heure (x2.2 -> x1.1, derive 21 %)), `atr_14m_pct_hnorm` (atr_14m_pct — ratio a la mediane par heure (x2.2 -> x1.1, derive 21 %)), `bar_lower_wick_pct_hnorm` (bar_lower_wick_pct — ratio a la mediane par heure (x2.0 -> x1.0, derive 4 %)) |
| EVENEMENT RARE (a traiter a part, non jete) | 30 | `vix_above_hvl` (se declenche 1.47 % du temps), `ib_is_narrow` (se declenche 0.31 % du temps), `delta_divergence` (se declenche 0.52 % du temps) |
| vide | 23 | `ib_position_pct` (55 % de trous), `after_high` (100 % de trous), `after_low` (100 % de trous) |
| constante | 23 | `lvn_between` (1 valeur(s) distincte(s)), `hvn_between` (1 valeur(s) distincte(s)), `bar_no_trade` (1 valeur(s) distincte(s)) |
| horloge assumee (l'heure est l'information) | 11 | `dist_ib_high` (x3.0), `dist_ib_low` (x2.9), `dist_open_cash` (x3.7) |
| FUITE ecartee avant calcul | 8 | `mins_to_next_news` (regarde le futur), `_mq_gamma_source` (metadonnee de pipeline), `_aggressor_source` (metadonnee de pipeline) |
| binaire quasi-toujours vraie | 1 | `has_single_prints` (se declenche 99.7 % du temps) |

### Noyau retenu, par famille


**MARKET PROFILE**

- `dist_composite_poc_5d_atr` — remplace 2 features (stabilite test 0.85) : `dist_pdh_atr`, `dist_composite_poc_20d_atr`
- `bars_in_va` — remplace 1 features (stabilite test 0.92) : `inside_cur_va`
- `ctx_va_width_hnorm` — remplace 1 features (stabilite test 0.76) : `range_size_ticks_hnorm`
- `profile_skew` — remplace 1 features (stabilite test 0.95) : `volume_imbalance`
- `poc_migration_dir` — remplace 1 features (stabilite test 0.82) : `ctx_poc_migration_10`
- `vah_touches_20b`
- `val_touches_20b`
- `inside_prev_va`
- `poc_bar_dist`
- `open_type`
- `day_type`
- `bool_va_confluence`
- `poc_position`
- `single_print_count_hnorm`
- `ctx_va_position_velocity`
- `ctx_va_developing_10`
- `im_open_type_agreement`
- `open_above_prev_vah`
- `open_below_prev_val`
- `profile_overlap_pct`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `single_print_density`

**VOLUME PROFILE**

- `session_hvn_count` — remplace 2 features (stabilite test 0.94) : `lvn_confluence_count`, `session_lvn_count`
- `dist_session_hvn_above`
- `dist_session_hvn_below`
- `dist_session_lvn_above`
- `dist_session_lvn_below`

**NIVEAUX VEILLE**

- `dist_pvwap_pct` — remplace 2 features (stabilite test 1.00) : `dist_pvwap_sd1u_pct`, `dist_pvwap_sd1d_pct`
- `open_in_prev_va`
- `range_h_minus_lprev_ticks_hnorm`
- `range_hprev_minus_l_ticks_hnorm`
- `open_within_prev_va`
- `dist_pdl_atr`

**VWAP**

- `dist_vwap_d` — remplace 24 features (stabilite test 0.82) : `bool_above_cur_vpoc`, `premium_zone`, `discount_zone`, `va_position_pct`, `dist_cur_val_pct_hnorm`, `single_print_above`, `single_print_below`, `dist_cur_val_hnorm`, `dist_cur_vah_pct`, `dist_cur_vah`, `bool_above_vwap_d`, `vwap_d_side`, `dist_vwap_d_sd1d_pct_hnorm`, `dist_vwap_d_sd1d_hnorm`, `range_pos`, `dist_cur_vpoc_pct`, `dist_cur_vpoc`, `range_pos_va`, `dist_vwap_d_sd1u_pct`, `dist_vwap_d_sd1u`, `dist_single_print_atr`, `dist_vwap_d_atr`, `dist_vwap_d_pct`, `dist_cur_vwap_vp`
- `dist_vwap_w` — remplace 22 features (stabilite test 0.80) : `bool_above_prev_vpoc`, `dist_prev_vah_pct`, `dist_prev_val`, `dist_mq_hvl_0dte`, `dist_mq_hvl_0dte_pct`, `dist_prev_vwap_sd1d`, `dist_prev_vpoc`, `dist_prev_vpoc_atr`, `vwap_triple_align`, `dist_mq_call_0dte`, `dist_mq_call_0dte_pct`, `dist_pdh`, `dist_pdh_pct`, `dist_prev_vah`, `dist_prev_vwap`, `dist_prev_vwap_sd1u`, `vwap_w_side`, `bool_above_vwap_w`, `dist_vwap_w_sd1u_pct`, `dist_vwap_w_sd1d_pct`, `dist_vwap_w_atr`, `dist_vwap_w_pct`
- `dist_vwap_m` — remplace 13 features (stabilite test 0.70) : `bool_above_mq_hvl`, `bool_above_vwap_m`, `vwap_m_side`, `dist_ext_color_up`, `dist_color_up_nearest_pct`, `dist_ext_color_dn`, `dist_color_dn_nearest_pct`, `dist_mq_hvl_pct`, `dist_mq_hvl`, `dist_vwap_m_sd1u_pct`, `dist_vwap_m_sd1d_pct`, `dist_vwap_m_atr`, `dist_vwap_m_pct`
- `dist_vwap_d_sd2u_hnorm` — remplace 5 features (stabilite test 0.82) : `dist_sess_high_pct_hnorm`, `dist_sess_high_hnorm`, `dist_vwap_d_sd3u_pct_hnorm`, `dist_vwap_d_sd3u_hnorm`, `dist_vwap_d_sd2u_pct_hnorm`
- `dist_vwap_d_sd2d_hnorm` — remplace 5 features (stabilite test 0.91) : `dist_sess_low_pct_hnorm`, `dist_sess_low_hnorm`, `dist_vwap_d_sd3d_pct_hnorm`, `dist_vwap_d_sd3d_hnorm`, `dist_vwap_d_sd2d_pct_hnorm`
- `vwap_slope_10` — remplace 1 features (stabilite test 0.85) : `vwap_slope_10_dir`
- `vwap_ma_align`
- `ctx_vwap_slope_accel`

**INITIAL BALANCE**

- `dist_ib_high` — remplace 18 features (stabilite test 0.80) : `dist_asia_low_pct`, `fvg_dn_active`, `above_open_cash`, `dist_ovn_high`, `dist_ib_low`, `dist_ovn_low`, `dist_london_open_pct`, `dist_london_high_pct`, `dist_open_830`, `dist_ib_low_pct`, `pct_in_range`, `dist_london_low_pct`, `dist_open_cash`, `dist_ny_open_pct`, `dist_cash_high_atr_hnorm`, `dist_cash_high_pct_hnorm`, `dist_us_high_pct_hnorm`, `dist_ib_high_pct`
- `ib_complete` — remplace 4 features (stabilite test 1.00) : `bool_session_early`, `is_ib_window`, `ib_formed_bool`, `ctx_session_phase`
- `ib_range_ticks` — remplace 2 features (stabilite test 0.97) : `ib_range_atr`, `ib_range`
- `ib_broken_up` — remplace 1 features (stabilite test 0.88) : `ctx_day_type_intensity`
- `ib_broken_dn` — remplace 1 features (stabilite test 0.94) : `ib_broken_down`
- `bool_ib_inside` — remplace 1 features (stabilite test 0.81) : `ctx_ib_extension_ratio`
- `ib_is_wide`
- `range_extension_above_ib_atr`
- `range_extension_below_ib_atr`

**OPTIONS / MENTHORQ**

- `vix_level` — remplace 4 features (stabilite test 0.60) : `dist_vix_put_0dte`, `dist_vix_put`, `dist_vix_hvl`, `dist_vix_call`
- `dist_mq_put` — remplace 2 features (stabilite test 0.92) : `ctx_mq_put_call_ratio`, `dist_mq_put_pct`
- `bool_gex_flip_zone` — remplace 2 features (stabilite test 1.00) : `div_regime_proxy_ok`, `mq_gamma_condition`
- `next_wall_dist_ticks` — remplace 1 features (stabilite test 0.84) : `next_wall_dist_ticks`
- `dist_mq_call` — remplace 1 features (stabilite test 1.00) : `dist_mq_call_pct`
- `dist_mq_put_0dte` — remplace 1 features (stabilite test 1.00) : `dist_mq_put_0dte_pct`
- `dist_gex_nearest_up` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_up_pct`
- `dist_gex_nearest_dn` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_dn_pct`
- `vix_regime`
- `dist_vix_call_0dte`
- `dist_vix_hvl_0dte`
- `vix_above_hvl_0dte`
- `dist_vix_gex_nearest_up`
- `dist_vix_gex_nearest_dn`
- `bool_above_mq_call`
- `gamma_block_long`

**ORDER FLOW**

- `ask_pct` — remplace 9 features (stabilite test 0.95) : `large_trader_ratio`, `cvd_bar_delta`, `delta_bar`, `diag_imbalance`, `ask_bid_imbalance`, `delta_bar_vol_norm`, `delta_pct`, `bid_pct`, `buy_sell_ratio`
- `big_ask_cluster_20t` — remplace 7 features (stabilite test 0.82) : `big_bid_cluster_20t`, `big_bid_cluster_50t`, `big_bid_cluster_20t_t2`, `big_bid_cluster_20t_t1`, `big_ask_cluster_20t_t1`, `big_ask_cluster_20t_t2`, `big_ask_cluster_50t`
- `cvd_day` — remplace 5 features (stabilite test 0.88) : `delta_day_dir`, `cvd_day_dir`, `ctx_cvd_session`, `delta_day`, `cvd_session`
- `delta_div_buy` — remplace 5 features (stabilite test 0.80) : `delta_divergence_clean`, `delta_div_slope_clean`, `delta_div_buy`, `delta_div_slope_buy`, `delta_div_slope_buy_clean`
- `n_big_ask_t1` — remplace 3 features (stabilite test 0.91) : `n_big_bid_t1`, `n_big_bid_v2_t1`, `n_big_ask_v2_t1`
- `n_big_ask_t2` — remplace 3 features (stabilite test 0.75) : `n_big_bid_t2`, `n_big_bid_v2_t2`, `n_big_ask_v2_t2`
- `n_big_ask_t3` — remplace 3 features (stabilite test 0.93) : `n_big_bid_t3`, `n_big_bid_v2_t3`, `n_big_ask_v2_t3`
- `delta_div_sell` — remplace 3 features (stabilite test 0.89) : `delta_div_sell_clean`, `delta_div_slope_sell_clean`, `delta_div_slope_sell`
- `finish_delta_pct` — remplace 1 features (stabilite test 1.00) : `high_ask_vol_pct`
- `n_big_ask_t4` — remplace 1 features (stabilite test 1.00) : `n_big_ask_v2_t4`
- `n_big_bid_t4` — remplace 1 features (stabilite test 1.00) : `n_big_bid_v2_t4`
- `bar_edge_buy` — remplace 1 features (stabilite test 1.00) : `bar_edge_buy_fire`
- `bar_edge_sell` — remplace 1 features (stabilite test 1.00) : `bar_edge_sell_fire`
- `dist_edge_sell_nearest_pct` — remplace 1 features (stabilite test 0.98) : `dist_edge_buy_nearest_pct`
- `delta_div_strength` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_strength`
- `ctx_delta_sum_3` — remplace 1 features (stabilite test 0.78) : `ctx_vol_sell_buy_ratio_5`
- `ctx_delta_sum_10` — remplace 1 features (stabilite test 0.96) : `ctx_cvd_recovery_rate`
- `high_pullback_delta`
- `low_pullback_delta`
- `diag_pos_delta_hnorm`
- `diag_neg_delta_hnorm`
- `low_bid_vol_pct`
- `bn_absorb_ask`
- `bn_absorb_bid`
- `dist_big_ask_nearest_up`
- `dist_big_ask_nearest_dn`
- `dist_big_bid_nearest_up`
- `dist_big_bid_nearest_dn`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
- `big_ask_cluster_20t_t4`
- `big_bid_cluster_20t_t4`
- `dist_cluster_nearest_up`
- `dist_cluster_nearest_dn`
- `n_clusters_20t`
- `n_clusters_50t`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `fp_edge_buy`
- `fp_edge_sell`
- `retest_high_delta_div`
- `retest_low_delta_div`
- `n_delta_div_buy_zones_active`
- `n_delta_div_sell_zones_active`
- `dist_delta_div_buy_nearest_atr`
- `dist_delta_div_sell_nearest_atr`
- `ctx_delta_exhaustion`
- `ctx_delta_slope_5`
- `aggressor_imbalance`
- `n_long_up_cluster_within_0_2pct`
- `n_long_dn_cluster_within_0_2pct`
- `n_color_up_cluster_within_0_2pct`
- `n_color_dn_cluster_within_0_2pct`
- `ctx_price_delta_div_3`
- `n_edge_buy_active`
- `n_edge_sell_active`
- `im_cross_delta_agreement_5`
- `im_cross_delta_weighted_5_hnorm`
- `im_delta_day_divergence`

**SWINGS / STRUCTURE**

- `momentum_3b` — remplace 2 features (stabilite test 0.97) : `bar_body_pct`, `bar_body_ticks`
- `momentum_5b` — remplace 1 features (stabilite test 0.98) : `ctx_dist_vwap_velocity`
- `price_vs_swing_mid` — remplace 1 features (stabilite test 0.74) : `dist_swing_low`
- `dist_swing_high`
- `swing_range_ticks_hnorm`
- `retest_high_count`
- `retest_low_count`
- `bars_since_retest_high`
- `bars_since_retest_low`
- `bars_since_last_swing_high`
- `bars_since_last_swing_low`
- `liquidity_sweep_high_lag5`
- `liquidity_sweep_low_lag5`
- `ctx_momentum_exhaustion`
- `ctx_div_at_swing`
- `fvg_up_active`
- `fvg_up_created_this_bar`
- `fvg_dn_created_this_bar`
- `sweep_high_active`
- `sweep_low_active`
- `sweep_high_this_bar`
- `sweep_low_this_bar`
- `bars_since_last_sweep_high`
- `bars_since_last_sweep_low`

**VOLATILITE / REGIME**

- `rvol` — remplace 4 features (stabilite test 0.83) : `ctx_vol_z_5`, `rvol_regime`, `rvol_zscore`, `ctx_vol_z_20`
- `atr_14m_hnorm` — remplace 2 features (stabilite test 0.95) : `ctx_range_vs_atr_10_hnorm`, `atr_14m_pct_hnorm`
- `atr` — remplace 1 features (stabilite test 1.00) : `gamma_threshold_ticks`
- `sess_range_atr_hnorm` — remplace 1 features (stabilite test 0.98) : `sess_range_atr_hnorm`
- `ovn_range_ticks`
- `range_size_hnorm`
- `ctx_rvol_session`
- `range_extension_completed`

**BATTLE NAVALE**

- `bn_color_up` — remplace 2 features (stabilite test 0.79) : `bn_score_bull`, `long_up_bar`
- `bn_color_dn` — remplace 2 features (stabilite test 0.66) : `bn_score_raw`, `bn_color_dn`
- `bar_color_up` — remplace 1 features (stabilite test 0.94) : `bar_long_up_bar`
- `bar_color_dn` — remplace 1 features (stabilite test 0.89) : `bar_long_dn_bar`
- `dist_ext_long_up` — remplace 1 features (stabilite test 0.99) : `dist_long_up_nearest_pct`
- `dist_ext_long_dn` — remplace 1 features (stabilite test 0.97) : `dist_long_dn_nearest_pct_hnorm`
- `n_long_up_zones_active` — remplace 1 features (stabilite test 0.86) : `n_color_up_zones_active`
- `n_long_dn_zones_active` — remplace 1 features (stabilite test 0.88) : `n_color_dn_zones_active`
- `bn_volume_up`
- `bn_volume_dn`
- `long_dn_bar`

**INTERMARKET**

- `im_smt_divergence`
- `im_price_ratio_slope_10`
- `im_rolling_correlation_10`
- `im_ltr_slope_diff`

**CONTEXTE ROLLING**

- `ctx_absorption_streak_5` — remplace 1 features (stabilite test 1.00) : `ctx_absorption_streak_5`
- `ctx_excess_low_bars` — remplace 1 features (stabilite test 1.00) : `ctx_excess_high_bars`
- `ctx_vol_slope_5` — remplace 1 features (stabilite test 0.88) : `im_volume_lead`
- `ctx_div_density_20`
- `ctx_climax_signal`
- `ctx_failed_auction`
- `ctx_absorption_score_5`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_double_top_trap`
- `ctx_finish_strength_mean_5`
- `ctx_side_flip_count_10`
- `ctx_price_slope_5`
- `ctx_trend_day_score`
- `ctx_rotation_factor_20`

**SESSION / TEMPS**

- `above_open_830` — remplace 12 features (stabilite test 0.92) : `vwap_slope_30`, `above_open_830`, `dist_pdl_pct`, `dist_pdl`, `dist_1d_min_ticks_pct`, `dist_1d_min_ticks`, `position_in_range`, `dist_prev_vpoc_pct`, `dist_1d_max_ticks`, `dist_1d_max_ticks_pct`, `dist_prev_val_pct`, `dist_asia_high_pct`
- `dist_us_low_pct_hnorm` — remplace 2 features (stabilite test 0.95) : `dist_cash_low_atr`, `dist_cash_low_pct_hnorm`
- `open_position` — remplace 1 features (stabilite test 0.85) : `open_gap_ticks`
- `open_direction` — remplace 1 features (stabilite test 0.96) : `im_cross_open_signal`
- `is_new_cash_high` — remplace 1 features (stabilite test 0.75) : `is_new_sess_high`
- `is_session_blocked` — remplace 1 features (stabilite test 0.88) : `is_blocked_combined`
- `open_relation_type` — remplace 1 features (stabilite test 1.00) : `open_outside_prev_range`
- `open_zone`
- `open_bias_conf`
- `mins_since_news`
- `ovn_broken_up`
- `ovn_broken_dn`
- `news_seconds_until`
- `news_minutes_until`
- `is_new_cash_low`

**BARRE / OHLC**

- `bar_duration_sec`
- `bar_upper_wick_pct`
- `bar_lower_wick_pct_hnorm`
- `equal_highs_detected`
- `equal_lows_detected`
- `is_new_sess_low`

**AUTRES**

- `avg_trade_size` — remplace 6 features (stabilite test 0.85) : `max_ask_vol_in_bar`, `max_big_ask_vol_in_bar`, `max_bid_vol_in_bar`, `max_big_bid_vol_in_bar`, `avg_bid_size`, `avg_ask_size`
- `volume_hnorm` — remplace 5 features (stabilite test 0.98) : `sell_vol_hnorm`, `buy_vol_hnorm`, `ticks_count_hnorm`, `vol_per_sec_hnorm`, `total_vol_hnorm`
- `delta_divergence_any` — remplace 3 features (stabilite test 0.78) : `delta_divergence_any`, `ctx_bars_since_div`, `div_confluence_with_regime`
- `is_double_dist` — remplace 2 features (stabilite test 0.91) : `poc_separation_ticks`, `profile_shape`
- `p99_trade_size_proxy` — remplace 1 features (stabilite test 0.95) : `large_trader_max_size`
- `next_wall_is_call`
- `finish_strength`
- `rotation_up`
- `rotation_dn`
- `rotation_zz_osc`
- `rule_80pct`
- `trend_day_probability_hnorm`
- `ma_trend`
- `bool_near_level`
- `is_eco_blocked`

## NQ

609 colonnes au depart, 436 apres nettoyage, **229 features retenues** (15651 barres, 12520 train / 3131 test).

### Balayage de seuils

| seuil de correlation | clusters | regroupements |
|---|---|---|
| 0.50 | 156 | 64 |
| 0.60 | 188 | 67 |
| 0.70 **(retenu)** | 224 | 68 |
| 0.80 | 260 | 70 |

### Ecartees au nettoyage

| motif | nombre | exemples |
|---|---|---|
| prix absolu | 71 | `price` (mediane 29405.0 ~ prix 29405.0), `open` (mediane 29404.8 ~ prix 29405.0), `single_print_mid` (mediane 29409.9 ~ prix 29405.0) |
| suspectee horloge, PROFIL INSTABLE -> gardee brute | 61 | `dist_vwap_d` (x9.2, derive train->test 169 % : l'heure ne la determine pas), `dist_vwap_d_atr` (x9.0, derive train->test 203 % : l'heure ne la determine pas), `dist_vwap_d_sd1u` (x7.8, derive train->test 55 % : l'heure ne la determine pas) |
| NORMALISEE par l'heure (recuperee) | 44 | `atr_14m_hnorm` (atr_14m — ratio a la mediane par heure (x2.9 -> x1.1, derive 25 %)), `atr_14m_pct_hnorm` (atr_14m_pct — ratio a la mediane par heure (x2.9 -> x1.1, derive 24 %)), `bar_lower_wick_pct_hnorm` (bar_lower_wick_pct — ratio a la mediane par heure (x3.4 -> x1.1, derive 28 %)) |
| constante | 35 | `n_big_ask_t1` (1 valeur(s) distincte(s)), `n_big_bid_t1` (1 valeur(s) distincte(s)), `n_big_ask_t4` (1 valeur(s) distincte(s)) |
| vide | 34 | `dist_ext_color_up` (80 % de trous), `dist_ext_color_dn` (81 % de trous), `dist_ext_long_up` (53 % de trous) |
| EVENEMENT RARE (a traiter a part, non jete) | 24 | `vix_above_hvl` (se declenche 1.46 % du temps), `ib_is_narrow` (se declenche 0.27 % du temps), `delta_divergence` (se declenche 0.63 % du temps) |
| horloge assumee (l'heure est l'information) | 11 | `dist_ib_high` (x2.6), `dist_ib_low` (x2.8), `dist_open_cash` (x2.4) |
| FUITE ecartee avant calcul | 8 | `mins_to_next_news` (regarde le futur), `_mq_gamma_source` (metadonnee de pipeline), `_aggressor_source` (metadonnee de pipeline) |
| binaire quasi-toujours vraie | 1 | `has_single_prints` (se declenche 99.9 % du temps) |

### Noyau retenu, par famille


**MARKET PROFILE**

- `dist_mq_put_0dte` — remplace 39 features (stabilite test 0.67) : `vwap_triple_align`, `bool_above_mq_hvl`, `vwap_w_side`, `bool_above_vwap_w`, `vwap_slope_30`, `dist_mq_put_0dte`, `dist_mq_put_0dte_pct`, `dist_vwap_w_sd1d_pct`, `bool_above_prev_vpoc`, `dist_pdl`, `dist_pdl_pct`, `dist_mq_call_0dte_pct`, `dist_mq_call_0dte`, `dist_1d_max_ticks_pct`, `dist_1d_max_ticks`, `dist_mq_hvl`, `dist_mq_hvl_pct`, `dist_1d_min_ticks_pct`, `dist_vwap_w_sd1u_pct`, `dist_mq_hvl_0dte`, `dist_mq_hvl_0dte_pct`, `dist_1d_min_ticks`, `dist_vwap_w_atr`, `dist_prev_val_hnorm`, `position_in_range`, `dist_asia_open_pct`, `dist_asia_high_pct`, `dist_pdh_pct`, `dist_vwap_w`, `dist_pdh`, `dist_vwap_w_pct`, `dist_prev_vwap_sd1d_hnorm`, `dist_prev_val_pct`, `dist_prev_vah_pct`, `dist_prev_vpoc_pct`, `dist_prev_vpoc_atr`, `dist_prev_vpoc`, `dist_prev_vwap`, `dist_prev_vwap_sd1u`
- `ctx_va_width` — remplace 2 features (stabilite test 0.88) : `sess_range_ticks`, `range_size_ticks`
- `dist_composite_poc_5d_atr` — remplace 2 features (stabilite test 0.85) : `dist_pdh_atr`, `dist_composite_poc_20d_atr`
- `bars_in_va` — remplace 1 features (stabilite test 0.88) : `inside_cur_va`
- `is_double_dist` — remplace 1 features (stabilite test 0.99) : `is_double_dist`
- `profile_skew` — remplace 1 features (stabilite test 0.96) : `volume_imbalance`
- `poc_migration_dir` — remplace 1 features (stabilite test 0.81) : `ctx_poc_migration_10`
- `vah_touches_20b`
- `val_touches_20b`
- `inside_prev_va`
- `poc_bar_dist_hnorm`
- `open_type`
- `day_type`
- `poc_position`
- `poc_separation_ticks_hnorm`
- `single_print_count_hnorm`
- `ctx_va_position_velocity`
- `ctx_va_developing_10`
- `im_open_type_agreement`
- `open_above_prev_vah`
- `open_below_prev_val`
- `profile_overlap_pct`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `single_print_density`

**VOLUME PROFILE**

- `session_hvn_count` — remplace 2 features (stabilite test 0.79) : `lvn_confluence_count`, `session_lvn_count`
- `dist_session_hvn_above`
- `dist_session_hvn_below`
- `dist_session_lvn_above`
- `dist_session_lvn_below`

**NIVEAUX VEILLE**

- `dist_pvwap_pct` — remplace 2 features (stabilite test 1.00) : `dist_pvwap_sd1u_pct`, `dist_pvwap_sd1d_pct`
- `open_in_prev_va`
- `dist_pdl_atr`
- `range_h_minus_lprev_ticks_hnorm`
- `range_hprev_minus_l_ticks_hnorm`
- `open_within_prev_va`

**VWAP**

- `dist_vwap_d` — remplace 24 features (stabilite test 0.76) : `bool_above_cur_vpoc`, `dist_cur_val_pct`, `dist_cur_val`, `discount_zone`, `premium_zone`, `va_position_pct`, `single_print_below`, `single_print_above`, `dist_cur_vah_pct`, `dist_cur_vah`, `dist_cur_vpoc_pct`, `dist_cur_vpoc`, `dist_vwap_d_sd1d_pct`, `dist_vwap_d_sd1d`, `bool_above_vwap_d`, `vwap_d_side`, `range_pos`, `range_pos_va`, `dist_vwap_d_sd1u_pct`, `dist_vwap_d_sd1u`, `dist_single_print_atr`, `dist_vwap_d_atr`, `dist_vwap_d_pct`, `dist_cur_vwap_vp`
- `dist_mq_call` — remplace 9 features (stabilite test 0.76) : `dist_mq_call`, `dist_mq_call_pct`, `dist_vix_put_0dte`, `vwap_m_side`, `bool_above_vwap_m`, `dist_vwap_m_sd1d_pct`, `dist_vwap_m_sd1u_pct`, `dist_vwap_m_atr`, `dist_vwap_m_pct`
- `dist_vwap_d_sd2u` — remplace 5 features (stabilite test 0.83) : `dist_sess_high`, `dist_sess_high_pct`, `dist_vwap_d_sd3u_pct`, `dist_vwap_d_sd3u`, `dist_vwap_d_sd2u_pct`
- `dist_vwap_d_sd2d_hnorm` — remplace 5 features (stabilite test 0.88) : `dist_sess_low_hnorm`, `dist_sess_low_pct_hnorm`, `dist_vwap_d_sd3d_pct_hnorm`, `dist_vwap_d_sd3d_hnorm`, `dist_vwap_d_sd2d_pct_hnorm`
- `vwap_slope_10` — remplace 1 features (stabilite test 0.84) : `vwap_slope_10_dir`
- `vwap_ma_align`
- `ctx_vwap_slope_accel`

**INITIAL BALANCE**

- `dist_ib_high` — remplace 15 features (stabilite test 0.74) : `dist_asia_low_pct`, `dist_ovn_high`, `above_open_cash`, `dist_london_open_pct`, `dist_ovn_low`, `pct_in_range`, `dist_open_830`, `dist_london_low_pct`, `dist_london_high_pct`, `dist_open_cash`, `dist_ny_open_pct`, `dist_cash_high_atr_hnorm`, `dist_us_high_pct`, `dist_cash_high_pct`, `dist_ib_high_pct`
- `dist_us_low_pct_hnorm` — remplace 5 features (stabilite test 0.91) : `ib_position_pct`, `dist_cash_low_atr_hnorm`, `dist_cash_low_pct_hnorm`, `dist_us_low_pct_hnorm`, `dist_ib_low_pct`
- `ib_complete` — remplace 4 features (stabilite test 1.00) : `bool_session_early`, `is_ib_window`, `ib_formed_bool`, `ctx_session_phase`
- `ib_range_ticks` — remplace 2 features (stabilite test 0.96) : `ib_range_atr`, `ib_range`
- `ib_broken_dn` — remplace 2 features (stabilite test 0.65) : `ctx_day_type_intensity`, `ib_broken_down`
- `bool_ib_inside` — remplace 1 features (stabilite test 0.76) : `ctx_ib_extension_ratio`
- `ib_is_wide`
- `ib_broken_up`
- `range_extension_above_ib_atr`

**OPTIONS / MENTHORQ**

- `dist_vix_call_0dte` — remplace 4 features (stabilite test 0.69) : `dist_vix_call_0dte`, `dist_vix_put`, `dist_vix_hvl`, `dist_vix_call`
- `dist_mq_put` — remplace 2 features (stabilite test 0.96) : `ctx_mq_put_call_ratio`, `dist_mq_put_pct`
- `dist_gex_nearest_up` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_up_pct`
- `dist_gex_nearest_dn` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_dn_pct`
- `gex_cluster_count`
- `vix_regime`
- `dist_vix_hvl_0dte`
- `vix_above_hvl_0dte`
- `dist_vix_gex_nearest_up`
- `dist_vix_gex_nearest_dn`
- `bool_above_mq_call`
- `bool_gex_flip_zone`
- `mq_gamma_condition`

**ORDER FLOW**

- `ask_pct` — remplace 9 features (stabilite test 0.96) : `large_trader_ratio`, `cvd_bar_delta`, `delta_bar`, `diag_imbalance`, `delta_bar_vol_norm`, `delta_pct`, `ask_bid_imbalance`, `bid_pct`, `buy_sell_ratio`
- `cvd_day` — remplace 5 features (stabilite test 0.81) : `delta_day_dir`, `cvd_day_dir`, `ctx_cvd_session`, `delta_day`, `cvd_session`
- `delta_div_buy_clean` — remplace 3 features (stabilite test 0.82) : `delta_divergence_clean`, `delta_div_slope_clean`, `delta_div_slope_buy_clean`
- `big_ask_cluster_20t` — remplace 2 features (stabilite test 0.78) : `big_ask_cluster_50t`, `big_ask_cluster_20t_t2`
- `big_bid_cluster_20t` — remplace 2 features (stabilite test 0.75) : `big_bid_cluster_20t_t2`, `big_bid_cluster_50t`
- `finish_delta_pct` — remplace 1 features (stabilite test 1.00) : `high_ask_vol_pct`
- `max_ask_vol_in_bar` — remplace 1 features (stabilite test 1.00) : `max_big_ask_vol_in_bar`
- `max_bid_vol_in_bar` — remplace 1 features (stabilite test 1.00) : `max_big_bid_vol_in_bar`
- `n_big_ask_t2` — remplace 1 features (stabilite test 1.00) : `n_big_ask_v2_t2`
- `n_big_bid_t2` — remplace 1 features (stabilite test 1.00) : `n_big_bid_v2_t2`
- `n_big_ask_t3` — remplace 1 features (stabilite test 1.00) : `n_big_ask_v2_t3`
- `n_big_bid_t3` — remplace 1 features (stabilite test 1.00) : `n_big_bid_v2_t3`
- `bar_edge_buy` — remplace 1 features (stabilite test 1.00) : `bar_edge_buy_fire`
- `bar_edge_sell` — remplace 1 features (stabilite test 1.00) : `bar_edge_sell_fire`
- `delta_div_buy` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_buy`
- `delta_div_sell` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_sell`
- `delta_div_strength` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_strength`
- `delta_div_sell_clean` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_sell_clean`
- `ctx_delta_sum_3` — remplace 1 features (stabilite test 0.73) : `ctx_vol_sell_buy_ratio_5`
- `ctx_delta_sum_10` — remplace 1 features (stabilite test 0.94) : `ctx_cvd_recovery_rate`
- `n_edge_sell_active` — remplace 1 features (stabilite test 0.80) : `n_edge_sell_active`
- `cvd_ohlc_range_hnorm`
- `high_pullback_delta`
- `low_pullback_delta`
- `diag_neg_delta_hnorm`
- `low_bid_vol_pct`
- `dist_big_ask_nearest_up`
- `dist_big_ask_nearest_dn`
- `dist_big_bid_nearest_up`
- `dist_big_bid_nearest_dn`
- `big_ask_cluster_20t_t1`
- `big_bid_cluster_20t_t1`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
- `dist_cluster_nearest_up`
- `dist_cluster_nearest_dn`
- `n_clusters_20t`
- `n_clusters_50t`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `fp_edge_buy`
- `fp_edge_sell`
- `retest_high_delta_div`
- `retest_low_delta_div`
- `delta_divergence_any`
- `n_delta_div_buy_zones_active_hnorm`
- `n_delta_div_sell_zones_active_hnorm`
- `dist_delta_div_buy_nearest_atr`
- `dist_delta_div_sell_nearest_atr`
- `ctx_delta_exhaustion`
- `ctx_delta_slope_5`
- `aggressor_imbalance`
- `n_long_up_cluster_within_0_2pct`
- `n_long_dn_cluster_within_0_2pct_hnorm`
- `n_color_up_cluster_within_0_2pct`
- `n_color_dn_cluster_within_0_2pct`
- `ctx_price_delta_div_3`
- `im_cross_delta_agreement_5`
- `im_cross_delta_weighted_5_hnorm`
- `im_delta_day_divergence`

**SWINGS / STRUCTURE**

- `momentum_3b` — remplace 2 features (stabilite test 0.97) : `bar_body_pct`, `bar_body_ticks`
- `price_vs_swing_mid` — remplace 2 features (stabilite test 0.71) : `dist_swing_high_hnorm`, `dist_swing_low_hnorm`
- `momentum_5b` — remplace 1 features (stabilite test 0.98) : `ctx_dist_vwap_velocity`
- `swing_range_ticks_hnorm`
- `retest_high_count`
- `retest_low_count`
- `bars_since_last_swing_high`
- `bars_since_last_swing_low`
- `liquidity_sweep_high_lag5`
- `liquidity_sweep_low_lag5`
- `ctx_momentum_exhaustion`
- `ctx_div_at_swing`
- `fvg_up_created_this_bar`
- `fvg_dn_created_this_bar`
- `sweep_high_active`
- `sweep_low_active`
- `sweep_high_this_bar`
- `sweep_low_this_bar`
- `bars_since_last_sweep_high`
- `bars_since_last_sweep_low`
- `fvg_up_active_hnorm`

**VOLATILITE / REGIME**

- `rvol` — remplace 4 features (stabilite test 0.85) : `ctx_vol_z_5`, `rvol_regime`, `rvol_zscore`, `ctx_vol_z_20`
- `atr_14m_hnorm` — remplace 2 features (stabilite test 0.96) : `ctx_range_vs_atr_10_hnorm`, `atr_14m_pct_hnorm`
- `range_extension_completed` — remplace 1 features (stabilite test 0.70) : `range_extension_below_ib_atr`
- `atr`
- `sess_range_atr_hnorm`
- `ovn_range_ticks`
- `range_size_hnorm`
- `ctx_rvol_session`
- `div_regime_proxy_ok`

**BATTLE NAVALE**

- `long_dn_bar` — remplace 4 features (stabilite test 0.85) : `bn_volume_dn`, `bn_score_raw`, `long_dn_bar`, `bn_score_bear`
- `bn_volume_up` — remplace 3 features (stabilite test 0.87) : `bn_volume_up`, `long_up_bar`, `bn_score_bull`
- `n_long_dn_zones_active` — remplace 2 features (stabilite test 0.84) : `fvg_dn_active`, `n_color_dn_zones_active`
- `bn_color_up`
- `bn_color_dn`
- `bn_color_up_2`
- `bn_color_dn_2`
- `bn_pressure_ask`
- `bn_pressure_bid`
- `bar_color_up`
- `bar_color_dn`
- `bar_long_up_bar`
- `bar_long_dn_bar`
- `bar_long_dn_up`
- `bar_long_up_dn`
- `long_dn_up_pattern`
- `long_up_dn_pattern`
- `n_long_up_zones_active`
- `n_color_up_zones_active_hnorm`

**INTERMARKET**

- `im_smt_divergence`
- `im_price_ratio_slope_10`
- `im_volume_lead`
- `im_rolling_correlation_10`
- `im_ltr_slope_diff`

**CONTEXTE ROLLING**

- `ctx_excess_low_bars` — remplace 1 features (stabilite test 1.00) : `ctx_excess_high_bars`
- `ctx_div_density_20`
- `ctx_bars_since_div_hnorm`
- `ctx_climax_signal`
- `ctx_failed_auction`
- `ctx_absorption_score_5`
- `ctx_absorption_streak_5`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_double_top_trap`
- `ctx_vol_slope_5`
- `ctx_finish_strength_mean_5`
- `ctx_side_flip_count_10`
- `ctx_price_slope_5`
- `ctx_trend_day_score`
- `ctx_rotation_factor_20`

**SESSION / TEMPS**

- `open_position` — remplace 1 features (stabilite test 0.89) : `open_gap_ticks`
- `open_direction` — remplace 1 features (stabilite test 0.94) : `im_cross_open_signal`
- `is_new_cash_high` — remplace 1 features (stabilite test 0.65) : `is_new_sess_high`
- `news_minutes_until` — remplace 1 features (stabilite test 1.00) : `news_minutes_until`
- `is_session_blocked` — remplace 1 features (stabilite test 0.88) : `is_blocked_combined`
- `open_relation_type` — remplace 1 features (stabilite test 0.90) : `open_outside_prev_range`
- `open_zone`
- `open_bias_conf`
- `mins_since_news`
- `above_open_830`
- `ovn_broken_up`
- `ovn_broken_dn`
- `is_new_cash_low`

**BARRE / OHLC**

- `next_wall_dist_ticks`
- `bar_duration_sec`
- `bar_pressure_ask`
- `bar_pressure_bid`
- `bar_upper_wick_pct_hnorm`
- `bar_lower_wick_pct_hnorm`
- `is_new_sess_low`

**AUTRES**

- `diag_pos_delta_hnorm` — remplace 6 features (stabilite test 0.88) : `diag_pos_delta_hnorm`, `sell_vol_hnorm`, `buy_vol_hnorm`, `ticks_count_hnorm`, `vol_per_sec_hnorm`, `total_vol_hnorm`
- `avg_trade_size` — remplace 2 features (stabilite test 0.90) : `avg_bid_size`, `avg_ask_size`
- `p99_trade_size_proxy` — remplace 1 features (stabilite test 0.93) : `large_trader_max_size`
- `div_confluence_dmp` — remplace 1 features (stabilite test 0.95) : `div_confluence_with_regime`
- `next_wall_is_call`
- `finish_strength`
- `rotation_up`
- `rotation_dn`
- `rotation_zz_osc`
- `rule_80pct`
- `trend_day_probability_hnorm`
- `ma_trend`
- `bool_near_level`
- `is_eco_blocked`

## Croisement ES / NQ

**191 features communes** aux deux instruments — le socle : elles decrivent le marche, pas l'instrument.

- `above_open_830`
- `aggressor_imbalance`
- `ask_pct`
- `atr`
- `atr_14m_hnorm`
- `avg_trade_size`
- `bar_color_dn`
- `bar_color_up`
- `bar_duration_sec`
- `bar_edge_buy`
- `bar_edge_sell`
- `bar_lower_wick_pct_hnorm`
- `bars_in_va`
- `bars_since_last_sweep_high`
- `bars_since_last_sweep_low`
- `bars_since_last_swing_high`
- `bars_since_last_swing_low`
- `big_ask_cluster_20t`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
- `bn_color_dn`
- `bn_color_up`
- `bn_volume_up`
- `bool_above_mq_call`
- `bool_gex_flip_zone`
- `bool_ib_inside`
- `bool_near_level`
- `ctx_absorption_score_5`
- `ctx_absorption_streak_5`
- `ctx_climax_signal`
- `ctx_delta_exhaustion`
- `ctx_delta_slope_5`
- `ctx_delta_sum_10`
- `ctx_delta_sum_3`
- `ctx_div_at_swing`
- `ctx_div_density_20`
- `ctx_double_top_trap`
- `ctx_excess_low_bars`
- `ctx_failed_auction`
- `ctx_finish_strength_mean_5`
- `ctx_momentum_exhaustion`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_price_delta_div_3`
- `ctx_price_slope_5`
- `ctx_rotation_factor_20`
- `ctx_rvol_session`
- `ctx_side_flip_count_10`
- `ctx_trend_day_score`
- `ctx_va_developing_10`
- `ctx_va_position_velocity`
- `ctx_vol_slope_5`
- `ctx_vwap_slope_accel`
- `cvd_day`
- `day_type`
- `delta_div_buy`
- `delta_div_sell`
- `delta_div_strength`
- `delta_divergence_any`
- `diag_neg_delta_hnorm`
- `diag_pos_delta_hnorm`
- `dist_big_ask_nearest_dn`
- `dist_big_ask_nearest_up`
- `dist_big_bid_nearest_dn`
- `dist_big_bid_nearest_up`
- `dist_cluster_nearest_dn`
- `dist_cluster_nearest_up`
- `dist_composite_poc_5d_atr`
- `dist_delta_div_buy_nearest_atr`
- `dist_delta_div_sell_nearest_atr`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `dist_gex_nearest_dn`
- `dist_gex_nearest_up`
- `dist_ib_high`
- `dist_mq_call`
- `dist_mq_put`
- `dist_mq_put_0dte`
- `dist_pdl_atr`
- `dist_pvwap_pct`
- `dist_session_hvn_above`
- `dist_session_hvn_below`
- `dist_session_lvn_above`
- `dist_session_lvn_below`
- `dist_us_low_pct_hnorm`
- `dist_vix_call_0dte`
- `dist_vix_gex_nearest_dn`
- `dist_vix_gex_nearest_up`
- `dist_vix_hvl_0dte`
- `dist_vwap_d`
- `dist_vwap_d_sd2d_hnorm`
- `finish_delta_pct`
- `finish_strength`
- `fp_edge_buy`
- `fp_edge_sell`
- `fvg_dn_created_this_bar`
- `fvg_up_created_this_bar`
- `high_pullback_delta`
- `ib_broken_dn`
- `ib_broken_up`
- `ib_complete`
- `ib_is_wide`
- `ib_range_ticks`
- `im_cross_delta_agreement_5`
- `im_cross_delta_weighted_5_hnorm`
- `im_delta_day_divergence`
- `im_ltr_slope_diff`
- `im_open_type_agreement`
- `im_price_ratio_slope_10`
- `im_rolling_correlation_10`
- `im_smt_divergence`
- `inside_prev_va`
- `is_double_dist`
- `is_eco_blocked`
- `is_new_cash_high`
- `is_new_cash_low`
- `is_new_sess_low`
- `is_session_blocked`
- `liquidity_sweep_high_lag5`
- `liquidity_sweep_low_lag5`
- `long_dn_bar`
- `low_bid_vol_pct`
- `low_pullback_delta`
- `ma_trend`
- `mins_since_news`
- `momentum_3b`
- `momentum_5b`
- `n_big_ask_t2`
- `n_big_ask_t3`
- `n_clusters_20t`
- `n_clusters_50t`
- `n_color_dn_cluster_within_0_2pct`
- `n_color_up_cluster_within_0_2pct`
- `n_edge_sell_active`
- `n_long_dn_zones_active`
- `n_long_up_cluster_within_0_2pct`
- `n_long_up_zones_active`
- `news_minutes_until`
- `next_wall_dist_ticks`
- `next_wall_is_call`
- `open_above_prev_vah`
- `open_below_prev_val`
- `open_bias_conf`
- `open_direction`
- `open_in_prev_va`
- `open_position`
- `open_relation_type`
- `open_type`
- `open_within_prev_va`
- `open_zone`
- `ovn_broken_dn`
- `ovn_broken_up`
- `ovn_range_ticks`
- `p99_trade_size_proxy`
- `poc_migration_dir`
- `poc_position`
- `price_vs_swing_mid`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `profile_overlap_pct`
- `profile_skew`
- `range_extension_above_ib_atr`
- `range_extension_completed`
- `range_h_minus_lprev_ticks_hnorm`
- `range_hprev_minus_l_ticks_hnorm`
- `range_size_hnorm`
- `retest_high_count`
- `retest_high_delta_div`
- `retest_low_count`
- `retest_low_delta_div`
- `rotation_dn`
- `rotation_up`
- `rotation_zz_osc`
- `rule_80pct`
- `rvol`
- `sess_range_atr_hnorm`
- `session_hvn_count`
- `single_print_count_hnorm`
- `single_print_density`
- `sweep_high_active`
- `sweep_high_this_bar`
- `sweep_low_active`
- `sweep_low_this_bar`
- `swing_range_ticks_hnorm`
- `trend_day_probability_hnorm`
- `vah_touches_20b`
- `val_touches_20b`
- `vix_above_hvl_0dte`
- `vix_regime`
- `vwap_ma_align`
- `vwap_slope_10`
