# Reduction de features — le noyau non redondant

Genere par `CORE/research/feature_reduction.py`.

**Ce que ce document repond** : quelles features apportent une information que les autres n'apportent pas deja.

**Ce qu'il ne dit PAS** : lesquelles sont rentables. Cette question demande une cible, un walk-forward et un DSR — elle est traitee ailleurs. La selection ci-dessous porte sur la *redondance*, jamais sur la performance : c'est ce qui la protege du data mining.

Methode : nettoyage (vides, constantes, prix absolus, horloges de session), distance `1 - |rho de Spearman|`, clustering hierarchique average coupe a **0.70**, un representant central par cluster. Validation par decoupage **temporel** 80/20 — les clusters sont appris sur les barres les plus anciennes et verifies sur les plus recentes, jamais regardees.

## ES

618 colonnes au depart, 384 apres nettoyage, **191 features retenues** (11310 barres, 9048 train / 2262 test).

### Balayage de seuils

| seuil de correlation | clusters | regroupements |
|---|---|---|
| 0.50 | 128 | 48 |
| 0.60 | 154 | 60 |
| 0.70 **(retenu)** | 186 | 69 |
| 0.80 | 219 | 74 |

### Ecartees au nettoyage

| motif | nombre | exemples |
|---|---|---|
| hors perimetre (C) | 114 | `va_position_pct` (niveau C), `range_size_ticks` (niveau C), `momentum_3b` (niveau C) |
| hors perimetre (N) | 70 | `price` (niveau N), `open` (niveau N), `single_print_mid` (niveau N) |
| suspectee horloge, PROFIL INSTABLE -> gardee brute | 46 | `dist_vwap_d` (x7.1, derive train->test 446 % : l'heure ne la determine pas), `dist_vwap_d_atr` (x7.1, derive train->test 678 % : l'heure ne la determine pas), `dist_vwap_d_sd1u` (x5.6, derive train->test 74 % : l'heure ne la determine pas) |
| NORMALISEE par l'heure (recuperee) | 33 | `atr_14m_hnorm` (atr_14m — ratio a la mediane par heure (x2.2 -> x1.1, derive 13 %)), `atr_14m_pct_hnorm` (atr_14m_pct — ratio a la mediane par heure (x2.2 -> x1.1, derive 14 %)), `buy_vol_hnorm` (buy_vol — ratio a la mediane par heure (x3.2 -> x1.1, derive 15 %)) |
| hors perimetre (R) | 23 | `vix_above_hvl` (niveau R), `ib_is_wide` (niveau R), `delta_divergence` (niveau R) |
| EVENEMENT RARE (a traiter a part, non jete) | 16 | `bn_color_up_2` (se declenche 0.28 % du temps), `bn_color_dn_2` (se declenche 0.37 % du temps), `bn_long_up` (se declenche 0.77 % du temps) |
| horloge assumee (l'heure est l'information) | 9 | `dist_ib_high` (x2.6), `dist_ib_low` (x2.7), `dist_open_cash` (x3.6) |
| constante | 7 | `is_in_us_cash` (1 valeur(s) distincte(s)), `is_in_asia` (1 valeur(s) distincte(s)), `is_in_london` (1 valeur(s) distincte(s)) |
| hors perimetre (?) | 3 | `_mq_gamma_source` (niveau inconnu), `_aggressor_source` (niveau inconnu), `_phase3_enriched` (niveau inconnu) |
| prix absolu | 1 | `cvd_ohlc_range` (mediane 8586.0 ~ prix 7676.8) |

### Noyau retenu, par famille


**MARKET PROFILE**

- `dist_cur_vah` — remplace 9 features (stabilite test 0.79) : `dist_sess_high`, `dist_sess_high_pct`, `dist_vwap_d_sd3u_hnorm`, `dist_vwap_d_sd3u_pct_hnorm`, `dist_vwap_d_sd2u_pct_hnorm`, `dist_vwap_d_sd2u_hnorm`, `dist_vwap_d_sd1u`, `dist_vwap_d_sd1u_pct`, `dist_cur_vah_pct`
- `ctx_day_type_intensity` — remplace 2 features (stabilite test 0.71) : `ib_broken_dn`, `ib_broken_down`
- `profile_shape` — remplace 2 features (stabilite test 0.91) : `poc_separation_ticks`, `is_double_dist`
- `profile_skew` — remplace 2 features (stabilite test 0.77) : `poc_position`, `volume_imbalance`
- `bars_in_va` — remplace 1 features (stabilite test 0.93) : `inside_cur_va`
- `open_above_prev_vah` — remplace 1 features (stabilite test 1.00) : `open_below_prev_val`
- `vah_touches_20b`
- `val_touches_20b`
- `inside_prev_va`
- `poc_bar_dist`
- `open_type`
- `day_type`
- `bool_va_confluence`
- `single_print_count_hnorm`
- `ctx_va_position_velocity`
- `ctx_va_width_hnorm`
- `ctx_va_developing_10_hnorm`
- `im_open_type_agreement`
- `profile_overlap_pct`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `single_print_density`

**VOLUME PROFILE**

- `session_hvn_count` — remplace 2 features (stabilite test 0.95) : `lvn_confluence_count`, `session_lvn_count`

**NIVEAUX VEILLE**

- `dist_pdl` — remplace 19 features (stabilite test 0.89) : `fvg_up_active`, `fvg_dn_active`, `dist_prev_vah_pct`, `vwap_slope_30`, `dist_open_830`, `dist_ovn_low`, `above_open_830`, `dist_pvwap_sd1u_pct`, `pct_in_range`, `dist_1d_min_ticks_pct`, `dist_1d_min_ticks`, `position_in_range`, `dist_prev_val_pct`, `dist_pvwap_pct`, `dist_pvwap_sd1d_pct`, `dist_asia_open_pct`, `dist_ovn_high`, `dist_pdl_atr`, `dist_pdl_pct`
- `dist_pdh` — remplace 2 features (stabilite test 1.00) : `dist_pdh_atr`, `dist_pdh_pct`
- `dist_prev_vwap_rth_r` — remplace 2 features (stabilite test 0.98) : `dist_pdh_rth_r`, `dist_pdl_rth_r`
- `range_h_minus_lprev_ticks_hnorm`
- `range_hprev_minus_l_ticks_hnorm`
- `open_within_prev_va`
- `open_in_prev_va`

**VWAP**

- `dist_vwap_d` — remplace 18 features (stabilite test 0.83) : `bool_above_cur_vpoc`, `dist_cur_val_pct_hnorm`, `premium_zone`, `discount_zone`, `dist_cur_val_hnorm`, `single_print_below`, `single_print_above`, `dist_cur_vpoc_pct`, `dist_cur_vpoc`, `dist_vwap_d_sd1d_pct`, `dist_vwap_d_sd1d`, `bool_above_vwap_d`, `vwap_d_side`, `range_pos_va`, `dist_single_print_atr`, `dist_vwap_d_atr`, `dist_vwap_d_pct`, `dist_cur_vwap_vp`
- `vwap_m_side` — remplace 12 features (stabilite test 0.70) : `vwap_triple_align`, `dist_composite_poc_5d_atr`, `bool_above_mq_hvl`, `dist_composite_poc_20d_atr`, `vwap_m_side`, `bool_above_vwap_m`, `dist_mq_hvl_pct`, `dist_mq_hvl`, `dist_vwap_m_sd1u_pct`, `dist_vwap_m_sd1d_pct`, `dist_vwap_m_atr`, `dist_vwap_m_pct`
- `dist_vwap_w` — remplace 11 features (stabilite test 0.84) : `bool_above_prev_vpoc`, `dist_prev_val`, `dist_prev_vpoc_atr`, `dist_prev_vpoc`, `vwap_w_side`, `bool_above_vwap_w`, `dist_prev_vah`, `dist_vwap_w_sd1d_pct`, `dist_vwap_w_sd1u_pct`, `dist_vwap_w_atr`, `dist_vwap_w_pct`
- `dist_vwap_d_sd2d_hnorm` — remplace 3 features (stabilite test 0.98) : `dist_vwap_d_sd3d_pct_hnorm`, `dist_vwap_d_sd3d_hnorm`, `dist_vwap_d_sd2d_pct_hnorm`
- `vwap_slope_10` — remplace 1 features (stabilite test 0.86) : `vwap_slope_10_dir`
- `vwap_ma_align`
- `ctx_vwap_slope_accel`

**INITIAL BALANCE**

- `ib_range_ticks` — remplace 2 features (stabilite test 0.99) : `ib_range_atr`, `ib_range`
- `is_ib_window` — remplace 2 features (stabilite test 1.00) : `bool_session_early`, `ctx_session_phase`
- `ctx_ib_extension_ratio` — remplace 1 features (stabilite test 0.86) : `bool_ib_inside`
- `ib_broken_up`

**OPTIONS / MENTHORQ**

- `dist_mq_call` — remplace 2 features (stabilite test 0.96) : `ctx_mq_put_call_ratio`, `dist_mq_call_pct`
- `bool_gex_flip_zone` — remplace 2 features (stabilite test 1.00) : `div_regime_proxy_ok`, `mq_gamma_condition`
- `next_wall_dist_ticks` — remplace 1 features (stabilite test 0.84) : `next_wall_dist_ticks`
- `dist_mq_put` — remplace 1 features (stabilite test 1.00) : `dist_mq_put_pct`
- `dist_mq_call_0dte` — remplace 1 features (stabilite test 1.00) : `dist_mq_call_0dte_pct`
- `dist_gex_nearest_up` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_up_pct`
- `dist_gex_nearest_dn` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_dn_pct`
- `dist_mq_put_0dte`
- `vix_regime`
- `dist_vix_hvl_0dte`
- `vix_above_hvl_0dte`
- `dist_vix_gex_nearest_up`
- `dist_vix_gex_nearest_dn`
- `bool_above_mq_call`
- `gamma_block_long`
- `vix_level`
- `dist_vix_hvl`
- `dist_vix_call`
- `dist_vix_put`
- `dist_vix_put_0dte`

**ORDER FLOW**

- `ask_pct` — remplace 9 features (stabilite test 0.95) : `large_trader_ratio`, `cvd_bar_delta`, `delta_bar`, `diag_imbalance`, `ask_bid_imbalance`, `delta_bar_vol_norm`, `delta_pct`, `bid_pct`, `buy_sell_ratio`
- `big_ask_cluster_20t` — remplace 7 features (stabilite test 0.80) : `big_bid_cluster_20t`, `big_bid_cluster_20t_t2`, `big_bid_cluster_50t`, `big_bid_cluster_20t_t1`, `big_ask_cluster_20t_t1`, `big_ask_cluster_20t_t2`, `big_ask_cluster_50t`
- `delta_div_buy` — remplace 5 features (stabilite test 0.81) : `delta_div_buy`, `delta_div_slope_buy`, `delta_div_buy_clean`, `delta_div_slope_buy_clean`, `delta_divergence_clean`
- `cvd_day` — remplace 3 features (stabilite test 0.89) : `ctx_cvd_session`, `delta_day_dir`, `cvd_day_dir`
- `n_big_ask_t1` — remplace 3 features : `n_big_bid_t1`, `n_big_bid_v2_t1`, `n_big_ask_v2_t1`
- `n_big_ask_t3` — remplace 3 features (stabilite test 0.94) : `n_big_bid_t3`, `n_big_bid_v2_t3`, `n_big_ask_v2_t3`
- `delta_div_sell` — remplace 3 features (stabilite test 0.89) : `delta_div_sell_clean`, `delta_div_slope_sell_clean`, `delta_div_slope_sell`
- `finish_delta_pct` — remplace 1 features (stabilite test 1.00) : `high_ask_vol_pct`
- `n_big_ask_t2` — remplace 1 features (stabilite test 1.00) : `n_big_ask_v2_t2`
- `n_big_bid_t2` — remplace 1 features (stabilite test 1.00) : `n_big_bid_v2_t2`
- `bar_edge_buy` — remplace 1 features (stabilite test 1.00) : `bar_edge_buy_fire`
- `bar_edge_sell` — remplace 1 features (stabilite test 1.00) : `bar_edge_sell_fire`
- `delta_div_strength` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_strength`
- `ctx_delta_sum_3` — remplace 1 features (stabilite test 0.79) : `ctx_vol_sell_buy_ratio_5`
- `ctx_delta_sum_10` — remplace 1 features (stabilite test 0.97) : `ctx_cvd_recovery_rate`
- `high_pullback_delta`
- `low_pullback_delta`
- `diag_pos_delta_hnorm`
- `diag_neg_delta_hnorm`
- `low_bid_vol_pct`
- `bn_absorb_ask`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
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

- `momentum_10b_r` — remplace 2 features (stabilite test 0.77) : `poc_migration_dir`, `ctx_poc_migration_10`
- `dist_swing_low` — remplace 1 features (stabilite test 0.76) : `price_vs_swing_mid`
- `momentum_3b_r` — remplace 1 features (stabilite test 0.75) : `ctx_dist_vwap_velocity`
- `dist_swing_high`
- `swing_range_ticks_hnorm`
- `retest_high_count`
- `retest_low_count`
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
- `momentum_5b_r`

**VOLATILITE / REGIME**

- `rvol` — remplace 4 features (stabilite test 0.83) : `ctx_vol_z_5`, `rvol_regime`, `ctx_vol_z_20`, `rvol_zscore`
- `atr_14m_hnorm` — remplace 2 features (stabilite test 0.95) : `ctx_range_vs_atr_10_hnorm`, `atr_14m_pct_hnorm`
- `atr` — remplace 1 features (stabilite test 1.00) : `gamma_threshold_ticks`
- `sess_range_atr_hnorm` — remplace 1 features (stabilite test 0.96) : `sess_range_ticks_hnorm`
- `ovn_range_ticks`
- `range_size_hnorm`
- `ctx_rvol_session`
- `range_extension_completed`

**BATTLE NAVALE**

- `bn_color_up` — remplace 2 features (stabilite test 0.80) : `long_up_bar`, `bn_color_up`
- `bn_color_dn` — remplace 1 features (stabilite test 0.88) : `long_dn_bar`
- `bn_score_bear` — remplace 1 features (stabilite test 0.79) : `bn_absorb_bid`
- `bar_color_up` — remplace 1 features (stabilite test 0.95) : `bar_long_up_bar`
- `bar_color_dn` — remplace 1 features (stabilite test 0.88) : `bar_long_dn_bar`
- `n_long_up_zones_active` — remplace 1 features (stabilite test 0.92) : `n_color_up_zones_active`
- `n_long_dn_zones_active` — remplace 1 features (stabilite test 0.88) : `n_color_dn_zones_active`
- `bn_score_raw`
- `bn_volume_up`
- `bn_volume_dn`

**INTERMARKET**

- `im_volume_lead` — remplace 1 features (stabilite test 0.89) : `ctx_vol_slope_5`
- `im_smt_divergence`
- `im_price_ratio_slope_10`
- `im_rolling_correlation_10`
- `im_ltr_slope_diff`

**CONTEXTE ROLLING**

- `ctx_absorption_streak_5` — remplace 1 features (stabilite test 1.00) : `ctx_instant_absorption`
- `ctx_excess_low_bars` — remplace 1 features (stabilite test 1.00) : `ctx_excess_high_bars`
- `ctx_div_density_20`
- `ctx_climax_signal`
- `ctx_failed_auction`
- `ctx_absorption_score_5`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_double_top_trap`
- `ctx_finish_strength_mean_5`
- `ctx_side_flip_count_10`
- `ctx_trend_day_score`
- `ctx_rotation_factor_20`

**SESSION / TEMPS**

- `dist_open_cash` — remplace 9 features (stabilite test 0.87) : `dist_vwap_rth_sd1d_r`, `dist_vwap_rth_sd1u_r`, `dist_ib_high`, `dist_vwap_rth_r`, `dist_ib_high_pct`, `dist_ib_low`, `dist_ib_low_pct`, `above_open_cash`, `dist_ny_open_pct`
- `open_position` — remplace 1 features (stabilite test 0.87) : `open_gap_ticks`
- `open_direction` — remplace 1 features (stabilite test 0.94) : `im_cross_open_signal`
- `is_session_blocked` — remplace 1 features (stabilite test 0.84) : `is_blocked_combined`
- `open_relation_type` — remplace 1 features (stabilite test 1.00) : `open_outside_prev_range`
- `open_zone`
- `open_bias_conf`
- `ovn_broken_up`
- `ovn_broken_dn`
- `is_news_60m`

**BARRE / OHLC**

- `dist_sess_low_hnorm` — remplace 1 features (stabilite test 0.85) : `dist_sess_low_hnorm`
- `bar_duration_sec`
- `bar_upper_wick_pct`
- `bar_lower_wick_pct`
- `equal_highs_detected`
- `equal_lows_detected`
- `is_new_sess_high`

**AUTRES**

- `avg_trade_size` — remplace 6 features (stabilite test 0.85) : `max_ask_vol_in_bar`, `max_big_ask_vol_in_bar`, `max_bid_vol_in_bar`, `max_big_bid_vol_in_bar`, `avg_bid_size`, `avg_ask_size`
- `volume_hnorm` — remplace 5 features (stabilite test 0.97) : `sell_vol_hnorm`, `buy_vol_hnorm`, `ticks_count_hnorm`, `vol_per_sec_hnorm`, `total_vol_hnorm`
- `delta_divergence_any` — remplace 2 features (stabilite test 0.82) : `delta_divergence_any`, `div_confluence_with_regime`
- `p99_trade_size_proxy` — remplace 1 features (stabilite test 0.95) : `large_trader_max_size`
- `next_wall_is_call`
- `finish_strength`
- `rotation_up`
- `rotation_dn`
- `rotation_zz_osc`
- `rule_80pct`
- `ma_trend`
- `bool_near_level`
- `trend_day_probability_hnorm`

## NQ

618 colonnes au depart, 386 apres nettoyage, **212 features retenues** (11310 barres, 9048 train / 2262 test).

### Balayage de seuils

| seuil de correlation | clusters | regroupements |
|---|---|---|
| 0.50 | 137 | 59 |
| 0.60 | 162 | 60 |
| 0.70 **(retenu)** | 195 | 64 |
| 0.80 | 230 | 65 |

### Ecartees au nettoyage

| motif | nombre | exemples |
|---|---|---|
| hors perimetre (C) | 114 | `va_position_pct` (niveau C), `range_size_ticks` (niveau C), `momentum_3b` (niveau C) |
| hors perimetre (N) | 70 | `price` (niveau N), `open` (niveau N), `single_print_mid` (niveau N) |
| suspectee horloge, PROFIL INSTABLE -> gardee brute | 51 | `dist_vwap_d` (x8.2, derive train->test 110 % : l'heure ne la determine pas), `dist_vwap_d_atr` (x8.6, derive train->test 115 % : l'heure ne la determine pas), `dist_vwap_d_sd1u` (x7.6, derive train->test 56 % : l'heure ne la determine pas) |
| NORMALISEE par l'heure (recuperee) | 37 | `atr_14m_hnorm` (atr_14m — ratio a la mediane par heure (x3.0 -> x1.0, derive 20 %)), `atr_14m_pct_hnorm` (atr_14m_pct — ratio a la mediane par heure (x3.0 -> x1.0, derive 20 %)), `bar_lower_wick_pct_hnorm` (bar_lower_wick_pct — ratio a la mediane par heure (x3.3 -> x1.1, derive 25 %)) |
| hors perimetre (R) | 23 | `vix_above_hvl` (niveau R), `ib_is_wide` (niveau R), `delta_divergence` (niveau R) |
| constante | 13 | `n_big_ask_t1` (1 valeur(s) distincte(s)), `n_big_bid_t1` (1 valeur(s) distincte(s)), `is_in_us_cash` (1 valeur(s) distincte(s)) |
| EVENEMENT RARE (a traiter a part, non jete) | 9 | `bn_absorb_ask` (se declenche 1.10 % du temps), `bn_absorb_bid` (se declenche 1.00 % du temps), `bool_va_confluence` (se declenche 0.63 % du temps) |
| horloge assumee (l'heure est l'information) | 7 | `dist_ib_low` (x2.7), `dist_open_cash` (x2.1), `dist_ny_open_pct` (x2.1) |
| hors perimetre (?) | 3 | `_mq_gamma_source` (niveau inconnu), `_aggressor_source` (niveau inconnu), `_phase3_enriched` (niveau inconnu) |

### Noyau retenu, par famille


**MARKET PROFILE**

- `ctx_day_type_intensity` — remplace 2 features (stabilite test 0.67) : `ib_broken_dn`, `ib_broken_down`
- `bars_in_va` — remplace 1 features (stabilite test 0.90) : `inside_cur_va`
- `profile_shape` — remplace 1 features (stabilite test 1.00) : `is_double_dist`
- `profile_skew` — remplace 1 features (stabilite test 0.97) : `volume_imbalance`
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
- `ctx_va_width_hnorm`
- `ctx_va_developing_10_hnorm`
- `im_open_type_agreement`
- `profile_overlap_pct`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `single_print_density`
- `open_above_prev_vah`
- `open_below_prev_val`

**VOLUME PROFILE**

- `session_hvn_count` — remplace 2 features (stabilite test 0.79) : `session_lvn_count`, `lvn_confluence_count`

**NIVEAUX VEILLE**

- `dist_prev_vwap_rth_r` — remplace 38 features (stabilite test 0.74) : `dist_composite_poc_20d_atr`, `bool_above_prev_vpoc`, `above_open_830`, `dist_composite_poc_5d_atr`, `vwap_w_side`, `bool_above_vwap_w`, `vwap_slope_30`, `dist_pdh_atr`, `dist_prev_val`, `dist_prev_vpoc_atr`, `dist_vwap_w_sd1u_pct`, `dist_pdh_pct`, `dist_prev_vpoc`, `dist_pdh`, `dist_pdl_rth_r`, `dist_pdh_rth_r`, `dist_prev_vwap_rth_r`, `dist_vwap_w_atr`, `dist_prev_vah`, `dist_vwap_w_pct`, `dist_vwap_w`, `dist_1d_min_ticks_pct`, `n_color_dn_zones_active`, `dist_1d_min_ticks`, `dist_vwap_w_sd1d_pct`, `dist_mq_call_0dte_pct`, `dist_mq_call_0dte`, `dist_ovn_high`, `n_long_dn_zones_active`, `position_in_range`, `dist_pvwap_sd1u_pct`, `dist_prev_vah_pct`, `dist_asia_open_pct`, `dist_pvwap_pct`, `dist_pvwap_sd1d_pct`, `dist_prev_val_pct`, `dist_pdl_atr`, `dist_pdl_pct`
- `range_h_minus_lprev_ticks_hnorm`
- `range_hprev_minus_l_ticks_hnorm`
- `open_within_prev_va`

**VWAP**

- `dist_vwap_d` — remplace 18 features (stabilite test 0.79) : `bool_above_cur_vpoc`, `dist_cur_val_pct_hnorm`, `dist_cur_val_hnorm`, `premium_zone`, `discount_zone`, `single_print_below`, `single_print_above`, `dist_cur_vpoc`, `dist_cur_vpoc_pct`, `dist_vwap_d_sd1d_pct`, `dist_vwap_d_sd1d`, `bool_above_vwap_d`, `vwap_d_side`, `range_pos_va`, `dist_single_print_atr`, `dist_vwap_d_atr`, `dist_vwap_d_pct`, `dist_cur_vwap_vp`
- `dist_cur_vah` — remplace 9 features (stabilite test 0.78) : `dist_cur_vah`, `dist_cur_vah_pct`, `dist_vwap_d_sd1u`, `dist_vwap_d_sd1u_pct`, `dist_sess_high`, `dist_sess_high_pct`, `dist_vwap_d_sd3u_pct`, `dist_vwap_d_sd3u`, `dist_vwap_d_sd2u_pct`
- `dist_sess_low_hnorm` — remplace 5 features (stabilite test 0.87) : `dist_sess_low_hnorm`, `dist_sess_low_pct_hnorm`, `dist_vwap_d_sd3d_pct_hnorm`, `dist_vwap_d_sd3d_hnorm`, `dist_vwap_d_sd2d_pct_hnorm`
- `vwap_m_side` — remplace 1 features (stabilite test 1.00) : `bool_above_vwap_m`
- `vwap_slope_10` — remplace 1 features (stabilite test 0.86) : `vwap_slope_10_dir`
- `vwap_ma_align`
- `vwap_triple_align`
- `ctx_vwap_slope_accel`
- `dist_vwap_m`
- `dist_vwap_m_atr`
- `dist_vwap_m_pct`
- `dist_vwap_m_sd1u_pct`
- `dist_vwap_m_sd1d_pct`

**INITIAL BALANCE**

- `dist_open_cash` — remplace 9 features (stabilite test 0.89) : `dist_vwap_rth_sd1d_r`, `dist_ib_low`, `above_open_cash`, `dist_ib_low_pct`, `dist_vwap_rth_r`, `dist_open_cash`, `dist_ny_open_pct`, `dist_vwap_rth_sd1u_r`, `dist_ib_high_pct`
- `ib_range_ticks` — remplace 2 features (stabilite test 0.93) : `ib_range_atr`, `ib_range`
- `is_ib_window` — remplace 2 features (stabilite test 1.00) : `bool_session_early`, `ctx_session_phase`
- `ctx_ib_extension_ratio` — remplace 1 features (stabilite test 0.82) : `bool_ib_inside`
- `ib_broken_up`

**OPTIONS / MENTHORQ**

- `dist_mq_put` — remplace 2 features (stabilite test 0.89) : `ctx_mq_put_call_ratio`, `dist_mq_put_pct`
- `dist_gex_nearest_up` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_up_pct`
- `dist_gex_nearest_dn` — remplace 1 features (stabilite test 1.00) : `dist_gex_nearest_dn_pct`
- `gex_cluster_count`
- `vix_regime`
- `dist_vix_hvl_0dte`
- `vix_above_hvl_0dte`
- `dist_vix_gex_nearest_up`
- `dist_vix_gex_nearest_dn`
- `bool_above_mq_call`
- `dist_mq_call`
- `vix_level`
- `dist_vix_hvl`
- `dist_vix_call`
- `dist_vix_put`
- `dist_vix_put_0dte`
- `dist_mq_call_pct`
- `dist_mq_hvl`
- `dist_mq_put_0dte`
- `bool_above_mq_hvl`
- `dist_mq_hvl_pct`
- `bool_gex_flip_zone`
- `mq_gamma_condition`

**ORDER FLOW**

- `ask_pct` — remplace 9 features (stabilite test 0.96) : `large_trader_ratio`, `cvd_bar_delta`, `delta_bar`, `diag_imbalance`, `delta_bar_vol_norm`, `ask_bid_imbalance`, `delta_pct`, `bid_pct`, `buy_sell_ratio`
- `cvd_day` — remplace 3 features (stabilite test 0.82) : `ctx_cvd_session`, `delta_day_dir`, `cvd_day_dir`
- `delta_div_slope_clean` — remplace 3 features (stabilite test 0.82) : `delta_div_buy_clean`, `delta_div_slope_buy_clean`, `delta_divergence_clean`
- `big_ask_cluster_20t` — remplace 2 features (stabilite test 0.77) : `big_ask_cluster_50t`, `big_ask_cluster_20t_t2`
- `big_bid_cluster_20t` — remplace 2 features (stabilite test 0.77) : `big_bid_cluster_20t_t2`, `big_bid_cluster_50t`
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
- `ctx_delta_sum_10` — remplace 1 features (stabilite test 0.95) : `ctx_cvd_recovery_rate`
- `n_edge_sell_active` — remplace 1 features (stabilite test 0.77) : `n_edge_sell_active`
- `cvd_ohlc_range`
- `high_pullback_delta`
- `low_pullback_delta`
- `diag_neg_delta_hnorm`
- `low_bid_vol_pct`
- `big_ask_cluster_20t_t1`
- `big_bid_cluster_20t_t1`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
- `n_clusters_20t`
- `n_clusters_50t`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `fp_edge_buy`
- `fp_edge_sell`
- `retest_high_delta_div`
- `retest_low_delta_div`
- `delta_divergence_any`
- `n_delta_div_buy_zones_active`
- `n_delta_div_sell_zones_active`
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

- `momentum_10b_r` — remplace 2 features (stabilite test 0.76) : `poc_migration_dir`, `ctx_poc_migration_10`
- `price_vs_swing_mid` — remplace 1 features (stabilite test 0.74) : `dist_swing_high_hnorm`
- `momentum_3b_r` — remplace 1 features (stabilite test 0.73) : `ctx_dist_vwap_velocity`
- `momentum_5b_r` — remplace 1 features (stabilite test 0.68) : `im_price_ratio_slope_10`
- `dist_swing_low`
- `swing_range_ticks_hnorm`
- `retest_high_count`
- `retest_low_count`
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

**VOLATILITE / REGIME**

- `rvol` — remplace 4 features (stabilite test 0.85) : `ctx_vol_z_5`, `rvol_regime`, `rvol_zscore`, `ctx_vol_z_20`
- `atr_14m_hnorm` — remplace 2 features (stabilite test 0.96) : `ctx_range_vs_atr_10_hnorm`, `atr_14m_pct_hnorm`
- `sess_range_atr_hnorm` — remplace 1 features (stabilite test 0.98) : `sess_range_ticks_hnorm`
- `atr`
- `ovn_range_ticks`
- `range_size_hnorm`
- `ctx_rvol_session`
- `range_extension_completed`
- `div_regime_proxy_ok`

**BATTLE NAVALE**

- `bn_volume_up` — remplace 4 features (stabilite test 0.86) : `bn_volume_up`, `bn_score_raw`, `long_up_bar`, `bn_long_up`
- `bn_volume_dn` — remplace 3 features (stabilite test 0.88) : `bn_volume_dn`, `long_dn_bar`, `bn_long_dn`
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

**INTERMARKET**

- `im_smt_divergence`
- `im_volume_lead`
- `im_rolling_correlation_10`
- `im_ltr_slope_diff`

**CONTEXTE ROLLING**

- `ctx_absorption_streak_5` — remplace 1 features (stabilite test 1.00) : `ctx_instant_absorption`
- `ctx_excess_low_bars` — remplace 1 features (stabilite test 1.00) : `ctx_excess_high_bars`
- `ctx_div_density_20`
- `ctx_climax_signal`
- `ctx_failed_auction`
- `ctx_absorption_score_5`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_double_top_trap`
- `ctx_vol_slope_5_hnorm`
- `ctx_finish_strength_mean_5`
- `ctx_side_flip_count_10`
- `ctx_trend_day_score`
- `ctx_rotation_factor_20`

**SESSION / TEMPS**

- `n_long_up_zones_active` — remplace 6 features (stabilite test 0.77) : `n_color_up_zones_active`, `fvg_up_active`, `n_long_up_zones_active`, `fvg_dn_active`, `pct_in_range`, `dist_open_830`
- `open_position` — remplace 1 features (stabilite test 0.91) : `open_gap_ticks`
- `open_direction` — remplace 1 features (stabilite test 0.96) : `im_cross_open_signal`
- `is_session_blocked` — remplace 1 features (stabilite test 0.84) : `is_blocked_combined`
- `open_relation_type` — remplace 1 features (stabilite test 0.96) : `open_outside_prev_range`
- `open_zone`
- `open_bias_conf`
- `ovn_broken_up`
- `ovn_broken_dn`
- `is_news_60m`

**BARRE / OHLC**

- `next_wall_dist_ticks`
- `bar_duration_sec`
- `bar_pressure_ask`
- `bar_pressure_bid`
- `bar_upper_wick_pct_hnorm`
- `bar_lower_wick_pct_hnorm`
- `is_new_sess_low`

**AUTRES**

- `diag_pos_delta_hnorm` — remplace 6 features (stabilite test 0.89) : `diag_pos_delta_hnorm`, `sell_vol_hnorm`, `buy_vol_hnorm`, `ticks_count_hnorm`, `vol_per_sec_hnorm`, `total_vol_hnorm`
- `avg_trade_size` — remplace 2 features (stabilite test 0.90) : `avg_bid_size`, `avg_ask_size`
- `open_in_prev_va` — remplace 1 features (stabilite test 1.00) : `open_in_prev_va`
- `p99_trade_size_proxy` — remplace 1 features (stabilite test 0.93) : `large_trader_max_size`
- `div_confluence_dmp` — remplace 1 features (stabilite test 0.94) : `div_confluence_with_regime`
- `next_wall_is_call`
- `finish_strength_hnorm`
- `rotation_up`
- `rotation_dn`
- `rotation_zz_osc`
- `rule_80pct`
- `ma_trend`
- `bool_near_level`

## Croisement ES / NQ

**166 features communes** aux deux instruments — le socle : elles decrivent le marche, pas l'instrument.

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
- `bars_in_va`
- `big_ask_cluster_20t`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
- `bn_color_dn`
- `bn_color_up`
- `bn_volume_dn`
- `bn_volume_up`
- `bool_above_mq_call`
- `bool_gex_flip_zone`
- `bool_near_level`
- `ctx_absorption_score_5`
- `ctx_absorption_streak_5`
- `ctx_climax_signal`
- `ctx_day_type_intensity`
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
- `ctx_ib_extension_ratio`
- `ctx_momentum_exhaustion`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_price_delta_div_3`
- `ctx_rotation_factor_20`
- `ctx_rvol_session`
- `ctx_side_flip_count_10`
- `ctx_trend_day_score`
- `ctx_va_developing_10_hnorm`
- `ctx_va_position_velocity`
- `ctx_va_width_hnorm`
- `ctx_vwap_slope_accel`
- `cvd_day`
- `day_type`
- `delta_div_buy`
- `delta_div_sell`
- `delta_div_strength`
- `delta_divergence_any`
- `diag_neg_delta_hnorm`
- `diag_pos_delta_hnorm`
- `dist_cur_vah`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `dist_gex_nearest_dn`
- `dist_gex_nearest_up`
- `dist_mq_call`
- `dist_mq_put`
- `dist_mq_put_0dte`
- `dist_open_cash`
- `dist_prev_vwap_rth_r`
- `dist_sess_low_hnorm`
- `dist_swing_low`
- `dist_vix_call`
- `dist_vix_gex_nearest_dn`
- `dist_vix_gex_nearest_up`
- `dist_vix_hvl`
- `dist_vix_hvl_0dte`
- `dist_vix_put`
- `dist_vix_put_0dte`
- `dist_vwap_d`
- `finish_delta_pct`
- `fp_edge_buy`
- `fp_edge_sell`
- `fvg_dn_created_this_bar`
- `fvg_up_created_this_bar`
- `high_pullback_delta`
- `ib_broken_up`
- `ib_range_ticks`
- `im_cross_delta_agreement_5`
- `im_cross_delta_weighted_5_hnorm`
- `im_delta_day_divergence`
- `im_ltr_slope_diff`
- `im_open_type_agreement`
- `im_rolling_correlation_10`
- `im_smt_divergence`
- `im_volume_lead`
- `inside_prev_va`
- `is_ib_window`
- `is_news_60m`
- `is_session_blocked`
- `liquidity_sweep_high_lag5`
- `liquidity_sweep_low_lag5`
- `low_bid_vol_pct`
- `low_pullback_delta`
- `ma_trend`
- `momentum_10b_r`
- `momentum_3b_r`
- `momentum_5b_r`
- `n_big_ask_t2`
- `n_big_ask_t3`
- `n_big_bid_t2`
- `n_clusters_20t`
- `n_clusters_50t`
- `n_color_dn_cluster_within_0_2pct`
- `n_color_up_cluster_within_0_2pct`
- `n_delta_div_buy_zones_active`
- `n_delta_div_sell_zones_active`
- `n_edge_sell_active`
- `n_long_up_cluster_within_0_2pct`
- `n_long_up_zones_active`
- `next_wall_dist_ticks`
- `next_wall_is_call`
- `open_above_prev_vah`
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
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `profile_overlap_pct`
- `profile_shape`
- `profile_skew`
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
- `vah_touches_20b`
- `val_touches_20b`
- `vix_above_hvl_0dte`
- `vix_level`
- `vix_regime`
- `vwap_m_side`
- `vwap_ma_align`
- `vwap_slope_10`
