# Reduction de features — le noyau non redondant

Genere par `CORE/research/feature_reduction.py`.

**Ce que ce document repond** : quelles features apportent une information que les autres n'apportent pas deja.

**Ce qu'il ne dit PAS** : lesquelles sont rentables. Cette question demande une cible, un walk-forward et un DSR — elle est traitee ailleurs. La selection ci-dessous porte sur la *redondance*, jamais sur la performance : c'est ce qui la protege du data mining.

Methode : nettoyage (vides, constantes, prix absolus, horloges de session), distance `1 - |rho de Spearman|`, clustering hierarchique average coupe a **0.70**, un representant central par cluster. Validation par decoupage **temporel** 80/20 — les clusters sont appris sur les barres les plus anciennes et verifies sur les plus recentes, jamais regardees.

## ES

609 colonnes au depart, 241 apres nettoyage, **136 features retenues** (11310 barres, 9048 train / 2262 test).

### Balayage de seuils

| seuil de correlation | clusters | regroupements |
|---|---|---|
| 0.50 | 101 | 35 |
| 0.60 | 115 | 36 |
| 0.70 **(retenu)** | 134 | 39 |
| 0.80 | 155 | 38 |

### Ecartees au nettoyage

| motif | nombre | exemples |
|---|---|---|
| hors perimetre (C) | 248 | `atr_14m` (niveau C), `dist_vwap_d_sd2d` (niveau C), `dist_vwap_d_sd3u` (niveau C) |
| hors perimetre (N) | 70 | `price` (niveau N), `open` (niveau N), `single_print_mid` (niveau N) |
| hors perimetre (R) | 23 | `vix_above_hvl` (niveau R), `delta_divergence` (niveau R), `new_swing_high` (niveau R) |
| suspectee horloge, PROFIL INSTABLE -> gardee brute | 22 | `dist_vwap_d` (x7.1, derive train->test 446 % : l'heure ne la determine pas), `dist_vwap_d_atr` (x7.1, derive train->test 678 % : l'heure ne la determine pas), `dist_vwap_d_sd1u` (x5.6, derive train->test 74 % : l'heure ne la determine pas) |
| EVENEMENT RARE (a traiter a part, non jete) | 16 | `bn_color_up_2` (se declenche 0.28 % du temps), `bn_color_dn_2` (se declenche 0.37 % du temps), `bn_long_up` (se declenche 0.77 % du temps) |
| NORMALISEE par l'heure (recuperee) | 8 | `atr_14m_pct_hnorm` (atr_14m_pct — ratio a la mediane par heure (x2.2 -> x1.1, derive 14 %)), `dist_cur_val_hnorm` (dist_cur_val — z-score robuste par heure (x9.9 -> x1.3, derive 29 %)), `dist_vwap_d_sd2u_hnorm` (dist_vwap_d_sd2u — z-score robuste par heure (x5.5 -> x1.1, derive 20 %)) |
| constante | 7 | `is_in_us_cash` (1 valeur(s) distincte(s)), `is_in_asia` (1 valeur(s) distincte(s)), `is_in_london` (1 valeur(s) distincte(s)) |
| horloge assumee (l'heure est l'information) | 3 | `dist_ib_high` (x2.6), `dist_ib_low` (x2.7), `dist_open_cash` (x3.6) |
| hors perimetre (?) | 3 | `_mq_gamma_source` (niveau inconnu), `_aggressor_source` (niveau inconnu), `_phase3_enriched` (niveau inconnu) |
| prix absolu | 1 | `cvd_ohlc_range` (mediane 8586.0 ~ prix 7676.8) |

### Noyau retenu, par famille


**MARKET PROFILE**

- `ctx_day_type_intensity` — remplace 2 features (stabilite test 0.71) : `ib_broken_dn`, `ib_broken_down`
- `profile_shape` — remplace 1 features (stabilite test 0.94) : `is_double_dist`
- `open_above_prev_vah` — remplace 1 features (stabilite test 1.00) : `open_below_prev_val`
- `inside_cur_va`
- `inside_prev_va`
- `open_type`
- `day_type`
- `bool_va_confluence`
- `profile_skew`
- `poc_migration_dir`
- `im_open_type_agreement`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`

**VOLUME PROFILE**

- `session_hvn_count` — remplace 2 features (stabilite test 0.95) : `lvn_confluence_count`, `session_lvn_count`

**NIVEAUX VEILLE**

- `dist_pdl` — remplace 13 features (stabilite test 0.89) : `fvg_up_active`, `fvg_dn_active`, `dist_open_830`, `dist_ovn_low`, `above_open_830`, `dist_pvwap_sd1u_pct`, `pct_in_range`, `dist_pvwap_pct`, `dist_pvwap_sd1d_pct`, `dist_asia_open_pct`, `dist_ovn_high`, `dist_pdl_atr`, `dist_pdl_pct`
- `dist_pdh` — remplace 2 features (stabilite test 1.00) : `dist_pdh_atr`, `dist_pdh_pct`
- `open_within_prev_va`
- `open_in_prev_va`

**VWAP**

- `dist_vwap_d` — remplace 18 features (stabilite test 0.83) : `bool_above_cur_vpoc`, `dist_vwap_d_sd2u_hnorm`, `premium_zone`, `discount_zone`, `dist_cur_val_hnorm`, `single_print_below`, `single_print_above`, `dist_cur_vah`, `dist_cur_vpoc`, `dist_vwap_d_sd1d`, `bool_above_vwap_d`, `vwap_d_side`, `dist_vwap_d_sd1u`, `range_pos_va`, `dist_single_print_atr`, `dist_vwap_d_atr`, `dist_vwap_d_pct`, `dist_cur_vwap_vp`
- `dist_vwap_w` — remplace 9 features (stabilite test 0.83) : `bool_above_prev_vpoc`, `dist_prev_val`, `dist_prev_vpoc_atr`, `dist_prev_vpoc`, `vwap_w_side`, `bool_above_vwap_w`, `dist_prev_vah`, `dist_vwap_w_atr`, `dist_vwap_w_pct`
- `dist_vwap_m` — remplace 5 features (stabilite test 0.79) : `dist_vix_put_0dte`, `vwap_m_side`, `bool_above_vwap_m`, `dist_vwap_m_atr`, `dist_vwap_m_pct`
- `vwap_ma_align`
- `vwap_slope_10_dir`
- `ctx_vwap_slope_accel`
- `vwap_triple_align`

**INITIAL BALANCE**

- `ib_complete` — remplace 3 features (stabilite test 1.00) : `bool_session_early`, `is_ib_window`, `ctx_session_phase`
- `ib_range_ticks` — remplace 1 features (stabilite test 1.00) : `ib_range`
- `ib_is_wide`
- `ib_broken_up`
- `bool_ib_inside`
- `range_extension_above_ib_atr`
- `range_extension_below_ib_atr`

**OPTIONS / MENTHORQ**

- `bool_gex_flip_zone` — remplace 2 features (stabilite test 1.00) : `div_regime_proxy_ok`, `mq_gamma_condition`
- `gex_cluster_count`
- `vix_regime`
- `vix_above_hvl_0dte`
- `dist_vix_gex_nearest_up`
- `bool_above_mq_call`
- `gamma_block_long`
- `bool_above_mq_hvl`

**ORDER FLOW**

- `ask_pct` — remplace 7 features (stabilite test 0.98) : `cvd_bar_delta`, `delta_bar`, `ask_bid_imbalance`, `delta_bar_vol_norm`, `delta_pct`, `bid_pct`, `buy_sell_ratio`
- `delta_div_buy` — remplace 5 features (stabilite test 0.81) : `delta_div_buy`, `delta_div_slope_buy`, `delta_div_buy_clean`, `delta_div_slope_buy_clean`, `delta_divergence_clean`
- `n_big_ask_t1` — remplace 3 features : `n_big_bid_t1`, `n_big_bid_v2_t1`, `n_big_ask_v2_t1`
- `n_big_ask_t3` — remplace 3 features (stabilite test 0.94) : `n_big_bid_t3`, `n_big_bid_v2_t3`, `n_big_ask_v2_t3`
- `delta_div_sell` — remplace 3 features (stabilite test 0.89) : `delta_div_sell_clean`, `delta_div_slope_sell_clean`, `delta_div_slope_sell`
- `cvd_day_dir` — remplace 1 features (stabilite test 1.00) : `delta_day_dir`
- `finish_delta_pct` — remplace 1 features (stabilite test 1.00) : `high_ask_vol_pct`
- `big_ask_cluster_20t_t2` — remplace 1 features (stabilite test 0.85) : `big_bid_cluster_20t_t2`
- `bar_edge_buy` — remplace 1 features (stabilite test 1.00) : `bar_edge_buy_fire`
- `bar_edge_sell` — remplace 1 features (stabilite test 1.00) : `bar_edge_sell_fire`
- `ctx_delta_sum_3` — remplace 1 features (stabilite test 0.79) : `ctx_vol_sell_buy_ratio_5`
- `high_pullback_delta`
- `bn_absorb_ask`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
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
- `n_long_up_cluster_within_0_2pct`
- `n_long_dn_cluster_within_0_2pct`
- `n_color_up_cluster_within_0_2pct`
- `n_color_dn_cluster_within_0_2pct`
- `ctx_price_delta_div_3`
- `n_edge_sell_active`
- `im_cross_delta_agreement_5`
- `im_delta_day_divergence`

**SWINGS / STRUCTURE**

- `price_vs_swing_mid`
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

- `atr` — remplace 1 features (stabilite test 1.00) : `gamma_threshold_ticks`
- `ovn_range_ticks`
- `range_size_hnorm`
- `atr_14m_pct_hnorm`
- `rvol_regime`
- `range_extension_completed`

**BATTLE NAVALE**

- `bn_color_up` — remplace 2 features (stabilite test 0.80) : `long_up_bar`, `bn_color_up`
- `bn_color_dn` — remplace 1 features (stabilite test 0.88) : `long_dn_bar`
- `bn_score_bear` — remplace 1 features (stabilite test 0.79) : `bn_absorb_bid`
- `bar_color_up` — remplace 1 features (stabilite test 0.95) : `bar_long_up_bar`
- `bar_color_dn` — remplace 1 features (stabilite test 0.88) : `bar_long_dn_bar`
- `bn_score_raw`
- `bn_volume_up`
- `bn_volume_dn`

**INTERMARKET**

- `im_smt_divergence`

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
- `ctx_vol_slope_5`
- `ctx_side_flip_count_10`
- `ctx_rotation_factor_20`

**SESSION / TEMPS**

- `dist_open_cash` — remplace 3 features (stabilite test 0.83) : `dist_ib_high`, `dist_ib_low`, `above_open_cash`
- `open_direction` — remplace 1 features (stabilite test 0.94) : `im_cross_open_signal`
- `is_session_blocked` — remplace 1 features (stabilite test 0.84) : `is_blocked_combined`
- `open_relation_type` — remplace 1 features (stabilite test 1.00) : `open_outside_prev_range`
- `open_position`
- `open_zone`
- `open_bias_conf`
- `ovn_broken_up`
- `ovn_broken_dn`

**BARRE / OHLC**

- `bar_duration_sec`
- `equal_highs_detected`
- `equal_lows_detected`
- `is_new_sess_high`

**AUTRES**

- `volume_hnorm` — remplace 2 features (stabilite test 1.00) : `vol_per_sec_hnorm`, `total_vol_hnorm`
- `delta_divergence_any` — remplace 2 features (stabilite test 0.82) : `delta_divergence_any`, `div_confluence_with_regime`
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

609 colonnes au depart, 243 apres nettoyage, **146 features retenues** (11310 barres, 9048 train / 2262 test).

### Balayage de seuils

| seuil de correlation | clusters | regroupements |
|---|---|---|
| 0.50 | 111 | 42 |
| 0.60 | 124 | 38 |
| 0.70 **(retenu)** | 142 | 35 |
| 0.80 | 163 | 39 |

### Ecartees au nettoyage

| motif | nombre | exemples |
|---|---|---|
| hors perimetre (C) | 248 | `atr_14m` (niveau C), `dist_vwap_d_sd2d` (niveau C), `dist_vwap_d_sd3u` (niveau C) |
| hors perimetre (N) | 70 | `price` (niveau N), `open` (niveau N), `single_print_mid` (niveau N) |
| suspectee horloge, PROFIL INSTABLE -> gardee brute | 25 | `dist_vwap_d` (x8.2, derive train->test 110 % : l'heure ne la determine pas), `dist_vwap_d_atr` (x8.6, derive train->test 115 % : l'heure ne la determine pas), `dist_vwap_d_sd1u` (x7.6, derive train->test 56 % : l'heure ne la determine pas) |
| hors perimetre (R) | 23 | `vix_above_hvl` (niveau R), `delta_divergence` (niveau R), `new_swing_high` (niveau R) |
| constante | 13 | `n_big_ask_t1` (1 valeur(s) distincte(s)), `n_big_bid_t1` (1 valeur(s) distincte(s)), `is_in_us_cash` (1 valeur(s) distincte(s)) |
| EVENEMENT RARE (a traiter a part, non jete) | 9 | `bn_absorb_ask` (se declenche 1.10 % du temps), `bn_absorb_bid` (se declenche 1.00 % du temps), `bool_va_confluence` (se declenche 0.63 % du temps) |
| NORMALISEE par l'heure (recuperee) | 9 | `atr_14m_pct_hnorm` (atr_14m_pct — ratio a la mediane par heure (x3.0 -> x1.0, derive 20 %)), `ctx_vol_slope_5_hnorm` (ctx_vol_slope_5 — z-score robuste par heure (x3.5 -> x1.1, derive 19 %)), `dist_cur_val_hnorm` (dist_cur_val — z-score robuste par heure (x11.1 -> x1.2, derive 24 %)) |
| hors perimetre (?) | 3 | `_mq_gamma_source` (niveau inconnu), `_aggressor_source` (niveau inconnu), `_phase3_enriched` (niveau inconnu) |
| horloge assumee (l'heure est l'information) | 2 | `dist_ib_low` (x2.7), `dist_open_cash` (x2.1) |

### Noyau retenu, par famille


**MARKET PROFILE**

- `dist_cur_vah` — remplace 2 features (stabilite test 0.88) : `dist_vwap_d_sd2u`, `dist_vwap_d_sd1u`
- `ctx_day_type_intensity` — remplace 2 features (stabilite test 0.67) : `ib_broken_dn`, `ib_broken_down`
- `profile_shape` — remplace 1 features (stabilite test 1.00) : `is_double_dist`
- `inside_cur_va`
- `inside_prev_va`
- `open_type`
- `day_type`
- `profile_skew`
- `poc_migration_dir`
- `im_open_type_agreement`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `open_above_prev_vah`
- `open_below_prev_val`

**VOLUME PROFILE**

- `session_hvn_count` — remplace 2 features (stabilite test 0.79) : `session_lvn_count`, `lvn_confluence_count`

**NIVEAUX VEILLE**

- `dist_pdh` — remplace 21 features (stabilite test 0.76) : `bool_above_prev_vpoc`, `above_open_830`, `vwap_w_side`, `bool_above_vwap_w`, `dist_pdh_atr`, `dist_prev_val`, `dist_prev_vpoc_atr`, `dist_pdh_pct`, `dist_prev_vpoc`, `dist_pdh`, `dist_vwap_w_atr`, `dist_prev_vah`, `dist_vwap_w_pct`, `dist_vwap_w`, `dist_ovn_high`, `dist_pvwap_sd1u_pct`, `dist_asia_open_pct`, `dist_pvwap_pct`, `dist_pvwap_sd1d_pct`, `dist_pdl_atr`, `dist_pdl_pct`
- `open_within_prev_va`

**VWAP**

- `dist_vwap_d` — remplace 15 features (stabilite test 0.81) : `bool_above_cur_vpoc`, `dist_cur_val_hnorm`, `premium_zone`, `discount_zone`, `single_print_below`, `single_print_above`, `dist_cur_vpoc`, `dist_vwap_d_sd1d`, `bool_above_vwap_d`, `vwap_d_side`, `range_pos_va`, `dist_single_print_atr`, `dist_vwap_d_atr`, `dist_vwap_d_pct`, `dist_cur_vwap_vp`
- `dist_vwap_m` — remplace 5 features (stabilite test 0.79) : `vwap_m_side`, `bool_above_vwap_m`, `dist_vix_put_0dte`, `dist_vwap_m_atr`, `dist_vwap_m_pct`
- `vwap_ma_align`
- `vwap_slope_10_dir`
- `vwap_triple_align`
- `ctx_vwap_slope_accel`

**INITIAL BALANCE**

- `ib_complete` — remplace 3 features (stabilite test 1.00) : `bool_session_early`, `is_ib_window`, `ctx_session_phase`
- `ib_range_ticks` — remplace 1 features (stabilite test 1.00) : `ib_range`
- `ib_is_wide`
- `ib_broken_up`
- `bool_ib_inside`
- `range_extension_above_ib_atr`
- `range_extension_below_ib_atr`

**OPTIONS / MENTHORQ**

- `gex_cluster_count`
- `vix_regime`
- `vix_above_hvl_0dte`
- `dist_vix_gex_nearest_up`
- `bool_above_mq_hvl`
- `bool_above_mq_call`
- `bool_gex_flip_zone`
- `mq_gamma_condition`

**ORDER FLOW**

- `ask_pct` — remplace 7 features (stabilite test 0.98) : `cvd_bar_delta`, `delta_bar`, `delta_bar_vol_norm`, `ask_bid_imbalance`, `delta_pct`, `bid_pct`, `buy_sell_ratio`
- `delta_div_slope_clean` — remplace 3 features (stabilite test 0.82) : `delta_div_buy_clean`, `delta_div_slope_buy_clean`, `delta_divergence_clean`
- `im_delta_day_divergence` — remplace 2 features (stabilite test 0.90) : `im_delta_day_divergence`, `delta_day_dir`
- `finish_delta_pct` — remplace 1 features (stabilite test 1.00) : `high_ask_vol_pct`
- `n_big_ask_t3` — remplace 1 features (stabilite test 1.00) : `n_big_ask_v2_t3`
- `n_big_bid_t3` — remplace 1 features (stabilite test 1.00) : `n_big_bid_v2_t3`
- `bar_edge_buy` — remplace 1 features (stabilite test 1.00) : `bar_edge_buy_fire`
- `bar_edge_sell` — remplace 1 features (stabilite test 1.00) : `bar_edge_sell_fire`
- `delta_div_buy` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_buy`
- `delta_div_sell` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_sell`
- `delta_div_sell_clean` — remplace 1 features (stabilite test 1.00) : `delta_div_slope_sell_clean`
- `ctx_delta_sum_3` — remplace 1 features (stabilite test 0.73) : `ctx_vol_sell_buy_ratio_5`
- `cvd_ohlc_range`
- `high_pullback_delta`
- `big_ask_cluster_20t_t2`
- `big_bid_cluster_20t_t2`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
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
- `n_long_up_cluster_within_0_2pct`
- `n_long_dn_cluster_within_0_2pct_hnorm`
- `n_color_up_cluster_within_0_2pct`
- `n_color_dn_cluster_within_0_2pct`
- `ctx_price_delta_div_3`
- `n_edge_sell_active`
- `im_cross_delta_agreement_5`

**SWINGS / STRUCTURE**

- `price_vs_swing_mid`
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

- `atr`
- `ovn_range_ticks`
- `rvol_regime`
- `range_extension_completed`
- `div_regime_proxy_ok`
- `range_size_hnorm`
- `atr_14m_pct_hnorm`

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
- `ctx_side_flip_count_10`
- `ctx_rotation_factor_20`

**SESSION / TEMPS**

- `dist_open_cash` — remplace 8 features (stabilite test 0.75) : `above_open_cash`, `dist_ib_low`, `dist_ib_high`, `fvg_up_active`, `dist_open_cash`, `fvg_dn_active`, `pct_in_range`, `dist_open_830`
- `open_direction` — remplace 1 features (stabilite test 0.96) : `im_cross_open_signal`
- `is_session_blocked` — remplace 1 features (stabilite test 0.84) : `is_blocked_combined`
- `open_relation_type` — remplace 1 features (stabilite test 0.96) : `open_outside_prev_range`
- `open_position`
- `open_zone`
- `open_bias_conf`
- `ovn_broken_up`
- `ovn_broken_dn`

**BARRE / OHLC**

- `bar_duration_sec`
- `bar_pressure_ask`
- `bar_pressure_bid`
- `is_new_sess_low`

**AUTRES**

- `volume_hnorm` — remplace 2 features (stabilite test 1.00) : `vol_per_sec_hnorm`, `total_vol_hnorm`
- `open_in_prev_va` — remplace 1 features (stabilite test 1.00) : `open_in_prev_va`
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

**120 features communes** aux deux instruments — le socle : elles decrivent le marche, pas l'instrument.

- `ask_pct`
- `atr`
- `atr_14m_pct_hnorm`
- `bar_color_dn`
- `bar_color_up`
- `bar_duration_sec`
- `bar_edge_buy`
- `bar_edge_sell`
- `big_ask_cluster_20t_t2`
- `big_ask_cluster_20t_t3`
- `big_bid_cluster_20t_t3`
- `bn_color_dn`
- `bn_color_up`
- `bn_volume_dn`
- `bn_volume_up`
- `bool_above_mq_call`
- `bool_above_mq_hvl`
- `bool_gex_flip_zone`
- `bool_ib_inside`
- `bool_near_level`
- `ctx_absorption_score_5`
- `ctx_absorption_streak_5`
- `ctx_climax_signal`
- `ctx_day_type_intensity`
- `ctx_delta_exhaustion`
- `ctx_delta_slope_5`
- `ctx_delta_sum_3`
- `ctx_div_at_swing`
- `ctx_div_density_20`
- `ctx_double_top_trap`
- `ctx_excess_low_bars`
- `ctx_failed_auction`
- `ctx_momentum_exhaustion`
- `ctx_poor_high`
- `ctx_poor_low`
- `ctx_price_delta_div_3`
- `ctx_rotation_factor_20`
- `ctx_side_flip_count_10`
- `ctx_vwap_slope_accel`
- `day_type`
- `delta_div_buy`
- `delta_div_sell`
- `delta_divergence_any`
- `dist_ext_edge_buy`
- `dist_ext_edge_sell`
- `dist_open_cash`
- `dist_pdh`
- `dist_vix_gex_nearest_up`
- `dist_vwap_d`
- `dist_vwap_m`
- `finish_delta_pct`
- `fp_edge_buy`
- `fp_edge_sell`
- `fvg_dn_created_this_bar`
- `fvg_up_created_this_bar`
- `gex_cluster_count`
- `high_pullback_delta`
- `ib_broken_up`
- `ib_complete`
- `ib_is_wide`
- `ib_range_ticks`
- `im_cross_delta_agreement_5`
- `im_delta_day_divergence`
- `im_open_type_agreement`
- `im_smt_divergence`
- `inside_cur_va`
- `inside_prev_va`
- `is_session_blocked`
- `liquidity_sweep_high_lag5`
- `liquidity_sweep_low_lag5`
- `ma_trend`
- `n_big_ask_t3`
- `n_color_dn_cluster_within_0_2pct`
- `n_color_up_cluster_within_0_2pct`
- `n_delta_div_buy_zones_active`
- `n_delta_div_sell_zones_active`
- `n_edge_sell_active`
- `n_long_up_cluster_within_0_2pct`
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
- `poc_migration_dir`
- `price_vs_swing_mid`
- `profile_overlap_above_pdh`
- `profile_overlap_below_pdl`
- `profile_shape`
- `profile_skew`
- `range_extension_above_ib_atr`
- `range_extension_below_ib_atr`
- `range_extension_completed`
- `range_size_hnorm`
- `retest_high_delta_div`
- `retest_low_count`
- `retest_low_delta_div`
- `rotation_dn`
- `rotation_up`
- `rotation_zz_osc`
- `rule_80pct`
- `rvol_regime`
- `session_hvn_count`
- `sweep_high_active`
- `sweep_high_this_bar`
- `sweep_low_active`
- `sweep_low_this_bar`
- `vix_above_hvl_0dte`
- `vix_regime`
- `volume_hnorm`
- `vwap_ma_align`
- `vwap_slope_10_dir`
- `vwap_triple_align`
