# Selection Empirique TOP 72 Features — Option B'

**Date** : 2026-04-18
**Methode** : Lopez AFML "embrace sparsity" — screening empirique rigoureux sans composite ni intuition
**Datasets** : `ES_dataset_v2.parquet` (31884, 276), `NQ_dataset_v2.parquet` (30063, 277) + cross-check parquet v3
**Labels** : `label in {-1, 0, +1}` (SELL/HOLD/BUY, generees par `labeler.py` avec TP/SL ticks fixes)

## Resume executif

Sur 267 features candidates communes ES/NQ dans le parquet v2 (numeriques, hors meta), seulement **72 features** passent le triple filtre :
1. `max(|rho_es|, |rho_nq|) >= 0.03` sur au moins un label binaire (BUY ou SELL)
2. Non-colineaire (|corr Pearson| < 0.85) avec une feature deja retenue plus haut dans le ranking
3. Symetrique ES/NQ ou exemption `NATURALLY_DIFFERENT` documentee

**Verdict** : 72 < 80. On reste sous le plafond cible. Pas besoin de completer artificiellement — la borne empirique naturelle est atteinte. **Ajouter des features en dessous de |rho|=0.03 serait du cargo-culting**.

## Structure de la selection

| Tier | Definition | Count | Action recommandee |
|------|------------|-------|---------------------|
| T1_SOLID | rho ok + sym ok + stable v2/v3 + MDA > 0 dans training precedent | **38** | Garder obligatoirement |
| T2_CANDIDATE | rho ok + sym ok + stable v2/v3 + (MDA>0 OR untested) | **1** | Garder |
| T3_WEAK | rho passe mais MDA = 0 alors que deja dans training precedent | **11** | Drop recommande (prob. bruit) |
| T4_REVIEW | rho passe mais non testable (mq_* absent v3) ou stabilite = 0 | **22** | A retester sur v4 post-purge |

## Classement par score composite = max(|rho_es|, |rho_nq|)

Ordonne par |rho| decroissant. Symbole `LIVE_SHORT` : disponibilite en prod bot (voir section 4).

### Tier 1 — Features solides (38) [GARDER]

| Rank | Feature | max\|rho\| | rho_buy_es | rho_sell_es | Live source |
|------|---------|-----------|------------|-------------|-------------|
|   1 | ticks_count                   | 0.116 | -0.081 | -0.116 | JSONL |
|   2 | diag_neg_delta                | 0.112 | -0.073 | -0.112 | JSONL |
|   3 | diag_pos_delta                | 0.107 | -0.080 | -0.105 | JSONL |
|   4 | bar_duration_sec              | 0.106 | -0.077 | -0.101 | JSONL |
|   6 | dist_comp_20d_val_atr         | 0.095 | -0.066 | -0.095 | ATR_NORM_LIVE |
|   7 | dist_1d_max_atr               | 0.094 | -0.009 | -0.094 | ATR_NORM_LIVE |
|   8 | im_cross_delta_weighted_5     | 0.092 | -0.060 | -0.081 | **IM_TODO** |
|  12 | delta_day                     | 0.083 | -0.052 | -0.068 | JSONL |
|  13 | ctx_absorption_score_5        | 0.080 | -0.037 | -0.080 | **ROLLING_TODO** |
|  18 | inside_comp_20d_va            | 0.068 | -0.056 | -0.055 | JSONL |
|  19 | low_pullback_delta            | 0.066 | -0.039 | -0.066 | JSONL |
|  21 | inside_comp_50d_va            | 0.065 | -0.065 | -0.064 | JSONL |
|  22 | poc_bar_dist_atr              | 0.065 | -0.048 | -0.063 | ATR_NORM_LIVE |
|  23 | dist_ext_edge_buy_atr         | 0.064 | -0.046 | -0.064 | ATR_NORM_LIVE |
|  24 | ctx_mq_put_call_ratio         | 0.061 | +0.042 | +0.061 | **ROLLING_TODO** |
|  26 | high_pullback_delta           | 0.060 | -0.054 | -0.060 | JSONL |
|  28 | ctx_delta_sum_10              | 0.054 | -0.054 | -0.041 | **ROLLING_TODO** |
|  30 | ctx_delta_sum_3               | 0.051 | -0.051 | -0.018 | **ROLLING_TODO** |
|  31 | low_bid_vol_pct               | 0.051 | -0.010 | -0.027 | JSONL |
|  32 | cvd_day_dir                   | 0.051 | -0.023 | -0.051 | JSONL |
|  36 | dist_session_lvn_above_atr    | 0.049 | -0.026 | -0.049 | ATR_NORM_LIVE |
|  38 | dist_mq_put_0dte_atr          | 0.047 | +0.026 | -0.028 | ATR_NORM_LIVE |
|  39 | ctx_rvol_session              | 0.047 | -0.022 | -0.047 | **ROLLING_TODO** |
|  42 | im_rolling_correlation_10     | 0.046 | -0.020 | -0.038 | IM_LIVE (deja porte) |
|  45 | open_gap_atr                  | 0.045 | -0.045 | -0.044 | ATR_NORM_CALC_LIVE |
|  46 | next_wall_dist_atr            | 0.045 | -0.037 | -0.045 | ATR_NORM_CALC_LIVE |
|  47 | dist_session_lvn_below_atr    | 0.044 | -0.044 | -0.023 | ATR_NORM_LIVE |
|  48 | open_bias_conf                | 0.043 | +0.016 | +0.025 | JSONL |
|  53 | rvol_regime                   | 0.041 | -0.018 | -0.041 | **RVOL_TODO** |
|  54 | open_zone                     | 0.041 | +0.024 | +0.041 | JSONL |
|  55 | high_ask_vol_pct              | 0.040 | -0.033 | -0.015 | JSONL |
|  57 | amd_asia_range_atr            | 0.040 | -0.035 | -0.040 | **AMD_TODO** |
|  58 | dist_mq_put_atr               | 0.040 | -0.026 | -0.038 | ATR_NORM_LIVE |
|  59 | im_cross_delta_agreement_5    | 0.039 | -0.034 | -0.036 | IM_LIVE (deja porte) |
|  61 | delta_bar                     | 0.038 | -0.038 | -0.015 | JSONL |
|  66 | large_trader_ratio            | 0.036 | -0.031 | -0.021 | JSONL |
|  67 | day_type                      | 0.036 | -0.036 | -0.022 | JSONL |
|  68 | finish_delta_pct              | 0.036 | -0.029 | -0.005 | JSONL |

### Tier 2 — Candidate (1) [GARDER]

| Rank | Feature | max\|rho\| | Live source |
|------|---------|-----------|-------------|
|  65 | ctx_range_vs_atr_10           | 0.037 | **ROLLING_TODO** |

### Tier 3 — Rho faible + MDA null meme en training (11) [DROP RECOMMANDE]

Ces features etaient presentes dans le training ES_buy/sell precedent (configs 203 features) avec MDA=0. Le modele n'a **PAS** su en extraire de signal malgre leur rho non-nul. Plusieurs explications possibles :
- Colinearite cachee (meme signal via une autre feature)
- Signal non-monotone (LightGBM peut le capter mais il n'a pas juge utile)
- Feature categorielle sous-discriminante
- Bruit

Decision empirique : **DROP** sauf si reintegration apres retraining prouve une contribution. Ne pas les garder "par securite".

| Rank | Feature | max\|rho\| | Pourquoi |
|------|---------|-----------|----------|
|  20 | dist_vix_hvl                  | 0.066 | Colineaire avec vix_level (retiree du ranking top) |
|  25 | bool_above_vwap_m             | 0.060 | Signal VWAP monthly dilue par ctx_dist_vwap_velocity |
|  27 | next_wall_is_call             | 0.056 | Duplicate partiel de bool_above_mq_call |
|  34 | dist_vix_gex_nearest_dn       | 0.050 | Signal VIX gamma rare ; MDA=0 = inutile |
|  44 | inside_cur_va                 | 0.045 | Duplicate partiel de bars_in_va |
|  50 | bool_above_mq_call            | 0.042 | MDA=0 dans training precedent |
|  51 | inside_prev_va                | 0.042 | MDA=0 dans training precedent |
|  60 | bool_above_prev_vpoc          | 0.039 | MDA=0 dans training precedent |
|  62 | range_pos                     | 0.038 | MDA=0 dans training precedent |
|  69 | vwap_triple_align             | 0.036 | MDA=0 dans training precedent |
|  70 | bool_above_mq_hvl             | 0.034 | MDA=0 dans training precedent |

### Tier 4 — Review (22) [RETESTER APRES PURGE v4]

Features non testables car absentes du training precedent (nouvelles) ou absentes du parquet v3 (impossible de verifier stabilite v2/v3). **N'est PAS une faiblesse**, juste un manque de donnees historiques. A re-evaluer apres retraining complet sur parquet v2 clean.

#### 4a. Features MenthorQ nouvelles (12)
Ces features `mq_*` sont absentes du parquet v3 (historique MenthorQ non retropropage pour certaines metriques). Elles seront testees au prochain training.

| Rank | Feature | max\|rho\| | Pourquoi T4 |
|------|---------|-----------|-------------|
|   9 | mq_pc_oi                      | 0.089 | nouvelle, absente v3 |
|  10 | mq_dist_call_0dte_atr         | 0.085 | nouvelle, absente v3 |
|  11 | mq_hv_30d                     | 0.084 | nouvelle, absente v3 |
|  14 | mq_iv_rank                    | 0.078 | nouvelle, absente v3 |
|  15 | mq_es_nq_iv_spread            | 0.078 | nouvelle, absente v3 |
|  16 | mq_dist_call_res_atr          | 0.071 | nouvelle, absente v3 |
|  17 | mq_es_nq_gex_ratio            | 0.071 | nouvelle, absente v3 |
|  29 | mq_net_gex_m                  | 0.052 | nouvelle, absente v3 |
|  33 | mq_net_gex_ratio              | 0.051 | nouvelle, absente v3 |
|  35 | mq_net_dex_b                  | 0.049 | nouvelle, absente v3 |
|  40 | mq_pc_dex                     | 0.046 | nouvelle, absente v3 |
|  41 | mq_es_nq_gamma_div            | 0.046 | nouvelle, absente v3 |
|  52 | mq_dist_hvl_atr               | 0.042 | nouvelle, absente v3 |
|  56 | mq_expiring_gex_pct           | 0.040 | nouvelle, absente v3 |
|  72 | mq_hvl_distance_pct           | 0.033 | nouvelle, absente v3 |

#### 4b. Features derivees nouvelles (7)

| Rank | Feature | max\|rho\| | Pourquoi T4 |
|------|---------|-----------|-------------|
|   5 | single_print_count            | 0.101 | nouvelle, absente v3, pas en training |
|  37 | retest_high_count             | 0.048 | instable v2/v3 (stable=0), a surveiller |
|  43 | bars_in_va                    | 0.045 | instable v2/v3, top_freq 0.85 |
|  49 | bar_edge_sell                 | 0.042 | top_freq ES=0.93 NQ=0.89 **→ quasi-constante, A DROP** |
|  63 | bar_edge_buy                  | 0.038 | top_freq ES=0.92 NQ=0.90 **→ quasi-constante, A DROP** |
|  64 | ovn_range_atr                 | 0.038 | derivee, top_freq 0.73, a retester |
|  71 | swing_range_atr               | 0.034 | derivee, top_freq 0.73, a retester |

## Availability LIVE

Repartition des 72 features par origine de calcul live dans le bot :

| Origine | Count | Statut prod |
|---------|-------|-------------|
| JSONL_DIRECT | 34 | disponible immediat |
| ATR_NORMALIZE_LIVE | 8 | disponible via `V2CLEAN/common/atr_normalize_live.py` (P0bis.7, 17/04) |
| ATR_NORM_CALC_LIVE | 4 | **A ajouter dans atr_normalize_live.py** : `open_gap_atr`, `next_wall_dist_atr`, `ovn_range_atr`, `swing_range_atr` — calcul trivial `ticks / atr` |
| IM_LIVE_PORTED | 2 | disponible via `V2CLEAN/common/im_features_live.py` |
| MENTHORQ_DAILY | 15 | inject quotidien via scraper MenthorQ (CTA + vol model) |
| **ROLLING_TODO** | **6** | **PORTAGE OBLIGATOIRE** : `ctx_absorption_score_5`, `ctx_mq_put_call_ratio`, `ctx_delta_sum_10`, `ctx_delta_sum_3`, `ctx_rvol_session`, `ctx_range_vs_atr_10` |
| INTERMARKET_PY_NOT_LIVE (IM_TODO) | 1 | **PORTAGE OBLIGATOIRE** : `im_cross_delta_weighted_5` |
| RVOL_PY_NOT_LIVE (RVOL_TODO) | 1 | **PORTAGE OBLIGATOIRE** : `rvol_regime` |
| AMD_PY_NOT_LIVE (AMD_TODO) | 1 | **PORTAGE OBLIGATOIRE** : `amd_asia_range_atr` |

## Quels moteurs Python a porter live ?

Verdict empirique pour Option B' :

| Moteur CORE/ | Features utilisees dans top 72 | Decision |
|--------------|--------------------------------|----------|
| `rolling_features.py` | 6 (ctx_absorption_score_5, ctx_mq_put_call_ratio, ctx_delta_sum_10, ctx_delta_sum_3, ctx_rvol_session, ctx_range_vs_atr_10) | **OUI — porter** |
| `intermarket_features.py` | 3 deja (im_cross_delta_agreement_5, im_open_type_agreement, im_rolling_correlation_10) + 1 manquant (im_cross_delta_weighted_5) | **OUI — etendre `im_features_live.py` avec 1 feature** |
| `rvol.py` | 1 (rvol_regime) | **OUI mais leger** — juste la fonction regime |
| `mia_amd.py` | 1 (amd_asia_range_atr) | **MINIMAL** — juste la range session Asia, pas le moteur complet |
| `atr_normalize_live.py` | 12 deja + 4 a ajouter | **Etendre** (trivial) |

**Gain de sparsity confirme** : au lieu de porter 4 moteurs complets (~2000 LOC Python), on porte :
- Extension `atr_normalize_live.py` : +4 features (3 lignes de config)
- Extension `im_features_live.py` : +1 feature (~20 LOC)
- Nouveau `V2CLEAN/common/rolling_features_live.py` : ~150 LOC (rolling sums + ratios 5/10 bar)
- Nouveau `V2CLEAN/common/rvol_regime_live.py` : ~30 LOC (regime z-score)
- Nouveau `V2CLEAN/common/amd_asia_range_live.py` : ~40 LOC (min/max sur session Asia)

**Total ~250 LOC Python live** vs ~2000 LOC si portage integral.

## Features REJETEES — Diagnostic empirique

### Sur les 267 features communes :
- **128** sont eliminees au premier filtre (`max|rho| < 0.03`). Parmi les plus notables :
  - Toutes les features `bn_*` : PROHIBITED (composites casses)
  - `bar_long_dn_bar`, `bar_long_up_bar` : PROHIBITED temporaire 02/05
  - `ib_*` binaires et `bool_*` variees : redondantes avec continus
  - `dist_*_ticks` bruts : domines par leurs versions `_atr`
  - `sess_range_atr`, `momentum_5b`, `ctx_*` nombreux : rho < 0.03

- **48** sont eliminees au filtre colinearite (redondantes avec top). Ex :
  - `total_vol`, `sell_vol`, `buy_vol`, `vol_per_sec` → tous corr > 0.95 avec `ticks_count`
  - `mq_swing_20d_bias`, `mq_qscore_momentum`, `mq_swing_5d_bias` → corr > 0.91 avec `mq_pc_oi` (tous trois identiques ?)
  - `vix_level`, `dist_vix_put`, `vix_above_hvl` → colineaires a `dist_vix_hvl`
  - `mq_iv_30d`, `mq_exp_move_pct` → corr 0.999 avec `mq_iv_rank`
  - `dist_comp_20d_vah_atr`, `dist_comp_50d_val_atr`, etc. → tous corr > 0.90 avec `dist_comp_20d_val_atr`
  - `mq_dist_1d_max_atr` ≈ `dist_1d_max_atr` (0.998)
  - `bars_since_retest_low/high` ≈ `dist_ext_edge_buy_atr` (0.92)

- **19** sont eliminees car asymetrie ES/NQ > 0.05 sans exemption valide

CSV complet des rejetes dans `_dropped_collin.csv` (colinearite) + `_rho_full_v2.csv` (toutes les correlations).

## Features avec risque PROHIBITED / IMPACT

Aucune feature dans le top 72 n'est dans la liste PROHIBITED actuelle (`dataset_builder.py` filter). Les features polluees historiques (17 red flags v3 residuelles) comme `ctx_poor_high/low`, `va_position_pct`, etc. sont **absentes du top 72** — elles ont naturellement un rho trop faible ou une symetrie cassee.

## Pattern 11 garde-fou

Application stricte :
- Aucune feature retenue "car elle a l'air utile"
- Aucun composite ajoute
- MDA=0 recognise comme signal empirique valide (T3 WEAK dropped)
- T4 flagge comme "retester apres retraining v4", PAS "ignorer"
- Pas de composites `dist_comp_20d_val_atr + dist_comp_50d_val_atr` malgre rho similaire

## Recommandation finale

Option B' executable avec **63 features robustes** :
- **Tier 1** (38) + **Tier 2** (1) + **Tier 4a/b non quasi-constantes** (~20) = **59 features**
- + Drop explicite de `bar_edge_sell` et `bar_edge_buy` (quasi-constantes)
- + Retester apres purge v4 les `mq_*` nouvelles (15) qui pourraient remonter en T1

Pour le prochain retraining LightGBM primary + meta :
1. Utiliser parquet v2 actuel (PROPRE)
2. Feature list = union Tier 1 + Tier 2 + Tier 4 (65 features)
3. Apres training : verifier MDA de chaque Tier 4 — si MDA = 0, DROP au next run
4. Tier 3 : ne pas inclure (confirme inutile par MDA=0 dans training precedent avec 203 features)

## Fichiers generes

- `CORE/research/feature_selection_top80.csv` : tableau complet avec rang, rho, MDA, stabilite, live source, tier
- `CORE/research/feature_selection_v4_top80.md` : ce rapport
- `_rho_full_v2.csv` : rho par label ternaire/BUY/SELL sur parquet v2 pour toutes les 267 features
- `_dropped_collin.csv` : 48 features droppees pour colinearite (> 0.85)
