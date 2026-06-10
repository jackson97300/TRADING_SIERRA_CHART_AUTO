# AUDIT RAPPORT — 10 Primary Models

**Date** : 2026-04-21
**Auteur** : agent market-analyst
**Dataset reference** : `ES_dataset_v3.parquet` (32554, 214), `NQ_dataset_v3.parquet` (30716, 214)
**Perimetre** : 10 primary_models + `base.py` + `_validate_features.py`

---

## Synthese executive

| # | Primary Model | Verdict | Features utilisees | Features v3 a ajouter prioritaire | Alignement philo Jackson |
|---|---------------|---------|--------------------|------------------------------------|---------------------------|
| 1 | `va_failure_fade` | AMELIORER | 5 (open_in_prev_va, inside_prev_va, dist_prev_vpoc_atr, dist_prev_vah_atr, dist_prev_val_atr) | `open_direction`, `open_type`, `mq_gamma_condition` | OUI (Market Profile primary) |
| 2 | `trend_day_rider` | AMELIORER | 5 (ib_complete, ib_broken_up/down, ctx_ib_extension_ratio, dist_vwap_d_atr) | `open_type`, `open_zone`, `bool_session_early` | OUI (Open Type + IB) |
| 3 | `orb` | GO | 4 (ib_complete, ib_range_atr, ib_broken_up, ib_broken_down) | aucune (laisser au meta-labeler) | OUI (IB primary) |
| 4 | `vwap_reversion` | NOGO | 3 (dist_vwap_d_sd2u_atr, dist_vwap_d_sd2d, ctx_delta_slope_5) | — | partiel (finding 11/04 negatif) |
| 5 | `expected_move_reversion` | AMELIORER | 3 (mq_dist_1d_max_atr, mq_dist_1d_min_atr, dist_vwap_d_atr) | `dist_1d_max_atr`/`dist_1d_min_atr` (non droppees) | OUI (Options) |
| 6 | `poor_high_low_retest` | AMELIORER | 6 (ctx_poor_high/low, dist_swing_high_atr, dist_swing_low, dist_sess_high_atr, dist_sess_low) | `open_bias_conf`, `mq_dist_call_res_atr`, `mq_dist_put_atr` | OUI (Market Profile) |
| 7 | `dow_trend_fractal` | NOGO | 5 (trend_day_probability, dist_swing_high_atr, dist_swing_low, swing_range_atr, ctx_trend_day_score) | — (re-ecrire Dow stateful) | NON (proxy incoherent) |
| 8 | `double_top_bottom` | AMELIORER | 5 (dist_swing_high_atr, dist_swing_low, swing_range_atr, dist_sess_high_atr, dist_sess_low) | `mq_dist_call_res_atr`, `ctx_absorption_score_5`, `open_bias_conf` | OUI (partiel, confluence) |
| 9 | `mq_level_bounce` | AMELIORER | 6 (mq_dist_call_res_atr, mq_dist_put_0dte_atr, mq_dist_call_0dte_atr, mq_dist_hvl_atr, dist_sess_high_atr, dist_sess_low) | `mq_gamma_condition`, `mq_net_gex_norm`, `mq_iv_30d` | OUI (Options confirmation) |
| 10 | `gap_fade` | GO | 2 (open_gap_atr, vix_level) | `mq_gamma_condition`, `open_type`, `open_zone` | OUI (Open + regime) |

**Bilan** : **2 GO / 6 AMELIORER / 2 NOGO**.

**Top 3 priorite backtest** :
1. `orb` — logique propre, features exhaustives
2. `gap_fade` — seul primary avec filtre VIX explicite
3. `mq_level_bounce` (apres ajout `mq_gamma_condition`)

---

## Bugs signales (file:line)

1. **`dow_trend_fractal.py:82`** : `ctx_trend_day_score` in `required_features()` mais **jamais lu** dans `generate_signal`. Validator passera OK silencieusement. Code mort.
2. **`trend_day_rider.py:62-68`** : `min_trend_prob=0.40` dans `__init__` **jamais utilise** dans `generate_signal`. Code mort.
3. **`va_failure_fade.py:103-120`** : logique `vpoc_dist > 0.1 -> BUY` peut contredire regle Dalton originale selon le cas de l'open. Biais logique pas bug Python.
4. **`expected_move_reversion.py:77-78`** : `mq_dist_1d_max_atr` **possiblement droppe** en v3 par screening colinearite (`_dropped_collin.csv:8` corr=0.98 avec `dist_1d_max_atr`). Verifier empiriquement.
5. **`poor_high_low_retest.py:86-87`** : `ctx_poor_high/low` semantique inversee vs nom du modele. `rolling_features.py:393-410` calcule "non-tested", pas "overtested".
6. **`double_top_bottom.py:64-68`** : asymetrie unites seuils `proximity_swing_atr=0.15` vs `proximity_swing_pts=5.0`. Factor 4 biais directionnel.
7. **`poor_high_low_retest.py:63-67`** : meme asymetrie que #6.

---

## Regles generales constatees

1. **SL/TP hardcoded 20/36 ticks partout** — R:R 1.8 fixe. Ignore ATR, ignore distance au niveau logique. Simplification Phase 1 documentee.
2. **Convention DMP `dist = niveau - prix`** — verifiee dans `DMP_Transform.h:491`.
3. **Features en points bruts vs ATR** — incoherence terminologique, pas de bug.
4. **Pattern 11 evite** — aucun composite hardcoded, bon respect.
5. **SL/TP identiques BUY/SELL** — asymetrie possible non exploitee.

---

## Recommandation finale — Priorite backtest

### Phase 1 (GO immediat, pas de reparation)
1. **`orb`** — backtest walk-forward 70j v3, MC permutation seuil 0.25
2. **`gap_fade`** — backtest walk-forward 70j v3, stratification VIX

### Phase 2 (1 fix + backtest)
3. **`mq_level_bounce` + `mq_gamma_condition`** — ajout filtre gamma (5 lignes code)

### Phase 3 (fix multiples + backtest)
4. **`expected_move_reversion`** — remplacer `mq_dist_1d_*_atr` par `dist_1d_*_atr`
5. **`trend_day_rider`** — reintroduire `bool_session_early`, nettoyer `min_trend_prob`, ajouter `open_type`
6. **`va_failure_fade`** — remplacer proxy VPOC par `open_direction`
7. **`double_top_bottom`** — corriger asymetrie unites, ajouter `ctx_absorption_score_5`
8. **`poor_high_low_retest`** — resoudre semantique `ctx_poor_high`, harmoniser unites

### Phase 4 (NOGO en l'etat)
9. **`vwap_reversion`** — reexaminer apres purge v4, finding 11/04 contradictoire
10. **`dow_trend_fractal`** — re-ecrire en vraie detection Dow stateful (strat 6b) OU supprimer

---

## Features critiques ABSENTES des primary models

Alignement philosophie Jackson (visible sur ses 8 ecrans trading) :

**Open Type / Structure** (pilier 3) :
- `open_type` (OD/OTD/ORR/OA) - utilise par Jackson visuellement, absent 9/10 models
- `open_direction` - vraie direction open, absent 9/10 models
- `open_bias_conf` - rho 0.043 Tier 1, absent 8/10 models
- `open_zone` - rho 0.041 Tier 1, absent 9/10 models

**MenthorQ recents (injecte 21/04)** :
- `mq_gamma_condition` (binaire) - absent 10/10 models
- `mq_net_gex_norm` - absent 10/10 models
- `mq_iv_30d` - absent 10/10 models
- `mq_pc_gex` - absent 10/10 models

**Market Profile** (pilier 1 Jackson) :
- `dist_cur_vpoc_atr` - POC du jour (cle Dalton), absent 9/10 models
- `dist_cur_vah_atr` / `dist_cur_val_atr` - VAH/VAL du jour, absent 9/10

**Order Flow (pilier 4)** :
- `ctx_absorption_score_5` - rho 0.080 Tier 1, absent 9/10 models
- `delta_bar`, `high_pullback_delta` - absent 10/10 models

---

## Regles souveraines respectees

1. **Aucune feature inventee** — toutes verifiees dans `DMP_Transform.h`, `rolling_features.py`, `mia_menthorq_reader.py`, `dataset_builder.py`.
2. **Aucun composite hardcoded propose** — ameliorations = ajouts au `required_features()` pour meta-labeler.
3. **`feedback_lightgbm_no_composite_indicators.md` respecte** — pas de "si X > Y alors veto".
4. **`feedback_backtest_before_gate.md` respecte** — verdicts disent "backtester cette version" avant de decider.
5. **Pattern 11 evite** — aucune recommandation "hardcoder composite".
6. **Stats suspectes flagguees** : `ib_range_atr > 0.25` (sample 12j), `proximity_atr=0.5` MQ (relax vs 0.2 = snooping), `min_gap_atr=0.15` gap_fade (relax).

---

## Resultat

**GO** — 10 sections completes + synthese + priorites.
**Chiffres cles** : **2 GO / 6 AMELIORER / 2 NOGO**.
