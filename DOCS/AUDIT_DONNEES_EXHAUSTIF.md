# Audit exhaustif des donnees `live_enriched`
Genere par `CORE/research/audit_donnees_exhaustif.py`.
Verdicts : MORTE (constante) · ZERO · SATUREE (>95%) · RARE (<1%) · QUASI-MORTE (<=3 valeurs) · VIDE (>50% trous) · VIVANTE

## ES — 11896 barres (10 jours), 626 colonnes
| Famille | total | VIVANTE | SATUREE | MORTE/ZERO | RARE | VIDE |
|---|---|---|---|---|---|---|
| MARKET PROFILE | 58 | 56 | 0 | 2 | 0 | 0 |
| VOLUME PROFILE | 9 | 7 | 0 | 2 | 0 | 0 |
| NIVEAUX VEILLE | 25 | 23 | 0 | 0 | 0 | 0 |
| VWAP | 60 | 55 | 1 | 4 | 0 | 0 |
| INITIAL BALANCE | 24 | 12 | 0 | 1 | 0 | 11 |
| OPTIONS / MENTHORQ | 34 | 31 | 0 | 0 | 0 | 0 |
| ORDER FLOW | 118 | 109 | 0 | 5 | 1 | 2 |
| SWINGS / STRUCTURE | 29 | 22 | 0 | 3 | 0 | 4 |
| SESSION / TEMPS | 43 | 28 | 0 | 5 | 0 | 4 |
| VOLATILITE / REGIME | 31 | 25 | 0 | 3 | 1 | 2 |
| BATTLE NAVALE | 39 | 27 | 0 | 4 | 8 | 0 |
| INTERMARKET | 5 | 4 | 0 | 1 | 0 | 0 |
| CONTEXTE ROLLING | 22 | 22 | 0 | 0 | 0 | 0 |
| PRIX / OHLC | 57 | 39 | 0 | 1 | 3 | 14 |
| AUTRES | 72 | 48 | 0 | 9 | 9 | 1 |

### ES — features problematiques

**MARKET PROFILE**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `has_single_prints` | MORTE | 100% | 100.0% | 1 | 1 | 1 |
| `poc_migration_dir` | QUASI-MORTE | 99% | 95.3% | 3 | -1 | 1 |

**VOLUME PROFILE**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `hvn_between` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `lvn_between` | MORTE | 100% | 0.0% | 1 | 0 | 0 |

**VWAP**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `vwap_d_side` | QUASI-MORTE | 100% | 100.0% | 3 | -1 | 1 |
| `vwap_slope_10_dir` | QUASI-MORTE | 100% | 99.7% | 3 | -1 | 1 |
| `vwap_triple_align` | QUASI-MORTE | 100% | 49.0% | 3 | -1 | 1 |
| `vwap_w_side` | QUASI-MORTE | 100% | 100.0% | 3 | -1 | 1 |
| `vwap_m_side` | SATUREE | 100% | 100.0% | 2 | -1 | 1 |

**INITIAL BALANCE**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `ctx_ib_extension_ratio` | VIDE | 27% | 100.0% | 934 | 1 | 5.038 |
| `ctx_ib_position_velocity` | VIDE | 13% | 96.8% | 455 | -0.3603 | 0.4423 |
| `dist_ib_high` | VIDE | 27% | 99.4% | 341 | -158 | 191 |
| `dist_ib_high_pct` | VIDE | 26% | 99.5% | 884 | -0.5086 | 0.6265 |
| `dist_ib_low` | VIDE | 27% | 99.7% | 314 | -262 | 68 |
| `dist_ib_low_pct` | VIDE | 26% | 99.8% | 886 | -0.8434 | 0.223 |
| `ib_high` | VIDE | 26% | 100.0% | 8 | 7670 | 7760 |
| `ib_low` | VIDE | 26% | 100.0% | 8 | 7639 | 7726 |
| `ib_position_pct` | VIDE | 14% | 99.6% | 469 | 0 | 1 |
| `ib_range` | VIDE | 26% | 100.0% | 8 | 23.75 | 39.5 |
| `ib_range_atr` | VIDE | 27% | 100.0% | 226 | 0.3133 | 2.7 |
| `ib_is_narrow` | ZERO | 100% | 0.0% | 2 | 0 | 1 |

**ORDER FLOW**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `ctx_price_delta_div_3` | QUASI-MORTE | 100% | 22.8% | 3 | -1 | 1 |
| `cvd_day_dir` | QUASI-MORTE | 100% | 99.9% | 3 | -1 | 1 |
| `delta_day_dir` | QUASI-MORTE | 100% | 99.9% | 3 | -1 | 1 |
| `delta_div_slope_clean` | QUASI-MORTE | 100% | 13.5% | 3 | -1 | 1 |
| `delta_divergence_clean` | QUASI-MORTE | 100% | 13.5% | 3 | -1 | 1 |
| `dist_cluster_nearest_dn` | VIDE | 43% | 100.0% | 57 | -70 | -1 |
| `dist_cluster_nearest_up` | VIDE | 44% | 32.4% | 67 | 0 | 71 |

**SWINGS / STRUCTURE**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `ctx_div_at_swing` | QUASI-MORTE | 100% | 5.6% | 3 | -1 | 1 |
| `judas_swing_direction` | QUASI-MORTE | 100% | 2.5% | 3 | -1 | 1 |
| `price_vs_swing_mid` | QUASI-MORTE | 100% | 98.5% | 3 | -1 | 1 |
| `bars_since_last_sweep_high` | VIDE | 38% | 100.0% | 20 | 1 | 20 |
| `bars_since_last_sweep_low` | VIDE | 38% | 100.0% | 20 | 1 | 20 |
| `dist_fvg_dn_nearest_atr` | VIDE | 5% | 0.0% | 1 | 0 | 0 |
| `dist_fvg_up_nearest_atr` | VIDE | 5% | 0.0% | 1 | 0 | 0 |

**SESSION / TEMPS**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `day_type` | QUASI-MORTE | 100% | 100.0% | 3 | 1 | 3 |
| `im_open_type_agreement` | QUASI-MORTE | 100% | 15.6% | 3 | -1 | 1 |
| `open_direction` | QUASI-MORTE | 100% | 19.9% | 3 | -1 | 1 |
| `open_relation_type` | QUASI-MORTE | 100% | 100.0% | 3 | 1 | 3 |
| `session` | QUASI-MORTE | 100% | 60.2% | 3 | 0 | 2 |
| `dist_after_open_pct` | VIDE | 4% | 95.3% | 181 | -0.1259 | 0.4679 |
| `dist_ny_open_pct` | VIDE | 31% | 99.1% | 1074 | -0.4453 | 0.7263 |
| `london_first_hour_direction` | VIDE | 25% | 77.8% | 3 | -1 | 1 |
| `mins_to_next_news` | VIDE | 43% | 100.0% | 318 | 1 | 434 |

**VOLATILITE / REGIME**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `rvol_buy_strong` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `rvol_sell_strong` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `vix_above_hvl` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `dist_cash_high_atr` | VIDE | 31% | 99.6% | 1480 | -1.185 | 0.4503 |
| `dist_cash_low_atr` | VIDE | 31% | 99.8% | 1541 | 0 | 1.098 |

**BATTLE NAVALE**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `bn_color_dn_2` | ZERO | 100% | 0.1% | 2 | 0 | 1 |
| `bn_color_dn_2_fwd1` | ZERO | 100% | 0.1% | 2 | 0 | 1 |
| `bn_color_up_2` | ZERO | 100% | 0.1% | 2 | 0 | 1 |
| `bn_color_up_2_fwd1` | ZERO | 100% | 0.1% | 2 | 0 | 1 |

**INTERMARKET**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `im_smt_divergence` | QUASI-MORTE | 100% | 1.6% | 3 | -1 | 1 |

**PRIX / OHLC**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `bar_no_trade` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `after_high` | VIDE | 4% | 100.0% | 33 | 7647 | 7757 |
| `after_low` | VIDE | 4% | 100.0% | 37 | 7641 | 7751 |
| `after_open` | VIDE | 4% | 100.0% | 9 | 7642 | 7751 |
| `bars_since_london_open` | VIDE | 29% | 99.7% | 389 | 0 | 388 |
| `dist_after_high_pct` | VIDE | 4% | 98.8% | 202 | -0.1914 | 0 |
| `dist_after_low_pct` | VIDE | 4% | 99.0% | 199 | 0 | 0.5104 |
| `dist_cash_high_pct` | VIDE | 27% | 99.5% | 1370 | 0 | 0.9011 |
| `dist_cash_low_pct` | VIDE | 27% | 99.8% | 1269 | -0.8499 | 0 |
| `dist_us_high_pct` | VIDE | 31% | 99.6% | 1439 | -0.893 | 0.3115 |
| `dist_us_low_pct` | VIDE | 31% | 99.8% | 1328 | 0 | 0.8571 |
| `london_open` | VIDE | 30% | 100.0% | 9 | 7642 | 7756 |
| `ny_open` | VIDE | 31% | 100.0% | 9 | 7641 | 7748 |
| `us_high` | VIDE | 31% | 100.0% | 161 | 7648 | 7782 |
| `us_low` | VIDE | 31% | 100.0% | 79 | 7622 | 7744 |

**AUTRES**

| feature | verdict | rempli | non-nul | uniques | min | max |
|---|---|---|---|---|---|---|
| `_phase3_enriched` | MORTE | 100% | 100.0% | 1 | 1 | 1 |
| `is_news_730` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `is_news_900` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `is_roll_day` | MORTE | 100% | 0.0% | 1 | 0 | 0 |
| `ma_trend` | MORTE | 100% | 100.0% | 1 | 1 | 1 |
| `roll_phase` | MORTE | 100% | 100.0% | 1 | 1 | 1 |
| `div_at_key_level_ticks` | VIDE | 13% | 93.3% | 37 | 0 | 40 |
| `is_news_715` | ZERO | 100% | 0.1% | 2 | 0 | 1 |
| `is_news_845` | ZERO | 100% | 0.1% | 2 | 0 | 1 |
| `is_news_930` | ZERO | 100% | 0.1% | 2 | 0 | 1 |
