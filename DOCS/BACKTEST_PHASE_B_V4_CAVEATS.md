# Backtest Phase B v4 — CAVEATS & limitations

**Date** : 2026-06-12
**Scope** : replay 7 mois parquet v4_enriched (ES + NQ + MGC) avec scenarios Phase B v4
**Verdict global** : robust subset valide empirique, scenarios INERTES en attente Phase C live

## Source de verite & version data

| Source | Statut | Periode | Notes |
|---|---|---|---|
| **Parquet v4_enriched** | Utilise backtest | ES dec25-mai26, NQ dec25-mai26, MGC mai25-mai26 | Build via `build_dataset_v4_dmp_databento.py` + `build_dataset_v4_phase_b.py` |
| **JSONL live_enriched** | Non utilise backtest | Quelques jours (11-12/06) | Source de verite SOUVERAINE (memoire 23/05) - utilise pour Phase C live |
| **Schema heterogene** | OUI documente | 3.7.4 → 3.7.22 (10+ versions sur 7 mois) | Pas de re-build complet, mix de versions |

## Bugs connus dans le parquet historique

### Bug arr[sz-1] systemique (memoire 15/04)

Le DMP_Reader.h pattern `arr[sz-1]` (correct en LIVE) **POLLUE le BACKFILL Full Recalc** :
toutes les barres historiques portent la **derniere valeur actuelle** au lieu de la valeur de la bar.

**Features affectees historiquement** :
- delta_divergence, big_orders, color_up/dn, long_up/dn → blacklist V2
- Le parquet v4 actuel a deja droppe ces features pollutees
- Fix architectural `sc.GetContainingIndexForSCDateTime` reporte

### Bug Open Type cross-session leak (fix 12/06 - INCIDENT #54)

Le DMP_OpenType.h utilisait `sc.IsNewTradingDay()` qui ne triggere pas a 18:00 ET
sur NQ continuous chart 24/5. Resultat : `cached_ot` du jour J-1 **leakee pendant
Asia/London/pre-RTH J** sur 6/7 jours.

**Impact backtest** :
- `open_type` non fiable sur bars 18:00 ET J → 10:30 ET J+1 (pre-RTH next session)
- Affecte scenario A2 Open Drive Dalton (utilise open_type derived = 1 ou 2)
- Acceptable car le scenario A2 a aussi un time filter `mins_et 570-600` qui evite le pire

Fix C++ deploye 12/06 PM, valide J+1 (13/06 grep JSONL).

### Phase A.2a + A.3 features NON propagees au parquet historique

Audit empirique sur parquet mai 2026 NQ (14919 bars, 467 colonnes) :

**25 features Phase A.2a + A.3 ABSENTES** :

| Famille | Features absentes |
|---|---|
| **BN extended** | bn_color_up/dn, bn_long_up/dn, bn_pressure_ask/bid, bn_score_raw |
| **Sweep / Wyckoff** | sweep_high_active, sweep_low_active, sweep_high_this_bar |
| **Judas Swing** | judas_swing_active |
| **FVG / ICT** | fvg_up_active, fvg_dn_active, dist_fvg_up_nearest_atr |
| **Single Print** | has_single_prints, single_print_density |
| **Composite POC** | composite_poc_5d, composite_poc_20d |
| **Other A.2a** | open_relation_type, profile_overlap_pct, range_extension_completed, ib_is_narrow, range_pos_va, delta_div_slope_strength, delta_day |

**Consequence** : ces features sont calculees par `sierra_pipeline.py:1200`
(compute_market_profile_v5/advanced_features) mais **n'ont jamais ete propagees
en batch dans le parquet** v4_enriched.

**Solution** : extension du `enricher_chain.py` ou ajout d'un post-processing
`tools/backfill_phase_a_features.py` qui re-run le scoring sur les parquets
historiques. Effort 2-3j. **Backlog**.

## Scenarios IMPACT - Robust subset vs Inerte

### Robust subset (6-8 scenarios backtestables)

| Scenario | Features utilisees | Status |
|---|---|---|
| Bullish continuation | cvd_day, profile_shape, open_relation (proxy), judas (absent → fallback) | OK |
| Bearish rejection | confluence cluster, cvd_session, sweep (absent → bonus rate 0) | OK partiel |
| Range bound LONG/SHORT fade | day_type, trend_day_probability | OK |
| Open Drive Dalton LONG/SHORT | open_type=1/2 derived, mins_et, is_in_us_cash | OK (avec caveat open_type pre-fix C++) |
| IB Break Continuation Dalton | ib_complete, ib_broken_up/down, ib_range_atr | OK |
| VWAP SD2/SD3 Touch Reversal | vwap_d_sd2u/d, sd3u/d, delta_divergence | OK |
| Holy Grail Raschke | trend_day_probability, vwap_d | OK |

### INERTES (7 scenarios skipped backtest)

| Scenario | Feature manquante critique | Validation Phase C |
|---|---|---|
| **BN Fired Confluence** (SOUVERAIN Jackson) | bn_color/long/pressure/score | Live JSONL ~12/07 (30j) |
| Failed Breakout (Spring/UTAD) | sweep_*_this_bar | Live JSONL ~12/07 |
| FVG Magnet UP/DOWN | fvg_*_active | Live JSONL ~12/07 |
| Judas Swing reversal | judas_swing_active | Live JSONL ~12/07 |
| Single Print Magnet | has_single_prints | Live JSONL ~12/07 |

## Interpretation des resultats

### A prendre avec des pincettes

- **Hit rates calcules sur 6-8 scenarios uniquement** = ~50% du repertoire Phase B v4
- **BN Fired Confluence absent du backtest** alors qu'il est le scenario souverain
  Jackson (cap 85, confluence + BN signals) → trade Jackson 12/06 13:33 ET sim4
  LONG 29319 → TP 29388 = +$2760 EXACT pattern BN Fired NON validable historique
- Open Type cross-session bug (fix 12/06) affecte rétroactivement les outcomes
  Open Drive Dalton sur les 7 mois → hit_rate pre-RTH probablement degrade
- Schema parquet heterogene (10+ versions) → certaines features ont des definitions
  qui ont evolue sur la fenetre 7 mois (silent breaking changes)

### Resultats valides confiance haute

- VWAP SD2/SD3 Touch Reversal : features 100% stables sur les 7 mois → calibration fiable
- IB Break Continuation : ib_* features stables, hit_rate exploitable
- Range bound LONG/SHORT : day_type stable, calibration fiable
- Holy Grail Raschke : trend_day_probability + vwap_d stables

## Plan validation Phase C originale (live JSONL)

**Pour valider les 7 scenarios INERTES** :

1. **Accumulation live** depuis 12/06 PM (schema 3.7.22+) avec ScenarioTracker actif
2. **Cible** : ~30j de paper trading + observation = ~750-1000 trades par scenario actif
3. **Date cible** : ~12/07/2026 pour Platt scaling Lopez complete
4. **Pre-requis** : integration sierra_pipeline.py (instantiate ScenarioTracker per-symbol)

## Recommandations actionnables

### Court terme (backtest robust subset)
- Calibrer 6-8 scenarios robust subset sur les 7 mois historique
- Recalibrer caps `heuristic_score` si hit_rate empirique >> ou << cap actuel
- Documenter `DSR Lopez` par scenario (~ DSR > 0.95 = signal solide)

### Moyen terme (apres 30j live)
- Re-tester Phase B v4 sur JSONL live propre 30j+ → tous les 13 scenarios
- Valider BN Fired Confluence (souverain Jackson)
- Calibration Platt finale toutes scenarios

### Long terme (architectural)
- Backfill features Phase A.2a + A.3 dans parquet historique (2-3j)
- Permet re-backtest 7 mois COMPLETE avec tous les scenarios
- Fix architectural `sc.GetContainingIndexForSCDateTime` C++ (memoire 15/04)
- Versionner schema parquet (eviter heterogeneite future)

## Reference

- Plan agent design Phase B.5 : 12/06
- Audit empirique features : `tools/backtest_phase_b_v4.py` smoke output
- Memoire 23/05 source unique JSONL : `project_source_data_unique_jsonl_live_20260523.md`
- Memoire 15/04 bug arr[sz-1] : `feedback_bug_arr_sz_1_systemique.md`
- Fix C++ DMP_OpenType : commit d0ad7b9 (INCIDENT #54)
- Lopez AFML ch.13 (Platt scaling) : reference calibration empirique
