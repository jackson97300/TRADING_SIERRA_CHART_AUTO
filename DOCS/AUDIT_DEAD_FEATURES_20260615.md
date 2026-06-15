# AUDIT DEAD FEATURES sierra_enriched — 15/06/2026

**Auteur** : Claude orchestrateur + 4 agents specialises (general-purpose × 4)
**Date** : 2026-06-15
**Donnees** : `DATA/live_enriched/sierra/NQ/` 4 jours (10-15/06, 15169 bars) + `ES/` 5 jours (10-15/06, 11762 bars)
**Trigger** : Migration Bot 1 `mia_paper_trader.py` vers `sierra_enriched` (commit `a201b15`). Audit empirique pour identifier features DEAD reelles dans le nouveau dataset 613 fields (vs DMP brut 380 fields).

---

## 1. RESULTATS HEADLINE

| Sample | Bars | DEAD | ALIVE | % DEAD |
|---|---|---|---|---|
| **NQ 1 jour** (15/06) | 1256 | 248 | 365 | 40.5% |
| **NQ 4 jours** (10-15/06) | 15169 | **157** | **474** | **24.9%** |
| **ES 5 jours** (10-15/06) | 11762 | **160** | **471** | **25.4%** |

**Finding cle** : sur 1 jour seul, 40.5% paraissent DEAD. Sur 4-5 jours, seulement **~25%** sont reellement DEAD. **91 features ressuscitent** entre 1j et 4j (RTH-only, sessions tardives, events sporadiques).

---

## 2. CAUSES RACINES PAR BUCKET (NQ 4j, 157 features DEAD)

| Bucket | Count | Cause type |
|---|---|---|
| **STD_ZERO** (std<eps OU top_freq haut sans CONSTANT) | 58 | Flags binaires events sporadiques (rare events) |
| **CONSTANT** (top_freq=100%) | 38 | Bug code OU seuils impossibles OU marqueurs META |
| **NULL** (null_pct>95%) | 35 | Feature missing pipeline OU session-dependent |
| **TOP_FREQ_HIGH** (95-99%) | 26 | Rare events normaux |

---

## 3. VRAIS BUGS A FIXER (7 bugs prioritaires)

### Bug #1 — `cvd_day_dir` NQ biais bull permanent ⚠️ CRITIQUE

**Statut** : CONSTANT 1 (15169 bars NQ, top_freq=100%)
**Source** : `CPP/MIA_REFACTORED/DUMPER/DMP_Transform.h:1302-1303` `Sign(cvd_day)` — formule correcte
**Cause racine** : `cvd_day` NQ jamais negatif sur 4 jours (range 5434-22249) vs ES qui balance correctement (-16747 → +38519)
**Cause probable** : etude Sierra Chart Footprint chart 30 NQ avec mauvais "Reset on New Session" OU param different du chart 31 ES
**Consumer prod CRITIQUE** : `CORE/bias_calculator.py:357,378` (PTS_CVD scoring) → **pollue activement le bias Bot 1 NQ vers BULL**
**Pattern** : VALIDATION_MISS — feature non monitoree post-deploy malgre dependance bias scoring
**Fix recommande** :
1. Diagnostic SC live : verifier params etude FPBS chart 30 vs chart 31
2. Si reset session mal configure → corriger SC + reload
3. Si bug persistent → fallback Python recalculer CVD depuis `buy_vol - sell_vol` cumule par session
**Effort** : 5 min config OU 1h fallback Python
**Risk** : moyen — bias_calculator NQ pollue

### Bug #2 — `delta_div_*_clean` famille morte depuis 12/06 ⚠️ CRITIQUE

**Statut** : `delta_div_sell_clean` CONSTANT False, `delta_div_slope_*_clean` CONSTANT 0 (NULL 77%)
**Source** : `CORE/divergences_v2.py:162` `MIN_DELTA_SLOPE = 100.0`
**Cause racine** : slope rolling 10-bars max observe ~0.053, **seuil 100 jamais atteint**. Sur 5000+ bars, 0% fire rate `_clean` (vs 17-24% fire rate `raw`)
**Historique** : INCIDENT_LOG #52 marque RESOLU le 12/06 (commits `2eb7666`, `73f26ef`, `37aa59b` Phase 2.2/2.3/2.4) MAIS **pas verifie empiriquement**. Classique pattern VALIDATION_MISS.
**Fix recommande** :
1. Recalibrer `MIN_DELTA_SLOPE = 0.005` (~p85 distribution NQ)
2. Test pytest etendu avec fire rate empirique > 5% requirement
3. **Ouvrir INCIDENT_LOG #55** : "VALIDATION_MISS — RESOLUTION #52 prematuree"
**Effort** : 3 LOC code + 30 LOC test = 30 min
**Risk** : faible — recalibration isolee

### Bug #3 — `composite_poc_5d/20d` cross-day reset destructeur ⚠️ HAUTE

**Statut** : NULL 100% (cascade : `comp_vpoc_align_*` CONSTANT 0, `dist_comp_20d_vpoc_atr` CONSTANT -20)
**Source** : `CORE/sierra_pipeline.py:1304-1310` (commit `941edd2`)
**Cause racine A (principale)** :
```python
self._market_profile_advanced_state = MarketProfileAdvancedState()  # CASSE
```
Cette ligne reinstancie le state CHAQUE cross-day → `daily_vpocs_5d/20d` deque videe. La cross-day transition dans `market_profile_advanced.py:189-194` qui archive le VPOC J-1 ne s'execute jamais (state.current_day est None apres reset).
**Cause racine B (secondaire)** : pas de persistance disque → restart nssm efface l'historique
**Pattern** : **COMMENT_FALSE** ("on reset au cas ou pour safety" est faux : le reset CASSE la feature) + **VALIDATION_MISS** (action item J+1 13/06 jamais coche)
**Fix recommande** :
- **Fix A** (15 LOC, 20 min) : reset uniquement `sweep` + `judas`, **PRESERVER** `composite_poc`
- **Fix B** (30 LOC, 45 min, optionnel) : pickle disque `DATA/state/composite_poc_*.pkl` cross-restart
**Effort total** : ~90 min avec tests
**Risk** : faible — modif additive, sub-states preserves selectivement
**Files** :
- `CORE/sierra_pipeline.py:1304-1310`
- `CORE/market_profile_advanced.py:116-233, 189-194`
- `tests/sierra_port/test_market_profile_advanced.py` (test cross_day_preserves_history a ajouter)

### Bug #4 — `dist_blind_nearest_up/dn` re-injection requise ⚠️ HAUTE

**Statut** : NULL 100% (sierra_enriched ne les ecrit pas, contrairement a DMP brut)
**Cause racine** : drop volontaire valide Jackson 11/06 soir suite a valeurs aberrantes C++ (charts 30/31 SC perdus -> `dist_comp_20d_vpoc = +86556` impossible). Drop dans `BOT/run_sierra_enricher.py:176-192` `_SIERRA_C_DEAD_FIELDS`.
**Vœu pieux** : commentaire ligne 171-186 promet re-injection via `menthorq_backfill_injector` ou `load_mq_levels` **MAIS aucun de ces modules n'est importe dans le pipeline streaming**. La promesse n'a jamais ete codee.
**Consumers prod ACTIFS** :
1. `CORE/bn_v5_engine.py:267-302` — pivot_near_support/resistance, **silencieusement degrade** (1 col support manquant sur 5). PROD Sim2 BN V5.
2. `CORE/bot3_gold_level_definitions.py:30,36` — Tier 2 BLIND_SPOT_UP/DN, **2 niveaux morts sur 49 Gold** (potentiellement -4% setups Tier 2). PROD Bot 3 Gold MGC.
3. `CORE/confluence_battery_prevdaily_mq.py:283,299` — research only, pas prod.
**Fix recommande** : porter calcul Python streaming dans `CORE/enricher_chain.py`
- Formule existe deja dans `menthorq_backfill_injector.py:321-324`: `(nearest_up - price) / TICK_SIZE`
- Inputs : `payload["mq_blind"]` (array 10 prix) + `close` + tick
- Ajouter aussi `_pct` version (`(level - close) / close * 100`)
**Effort** : 2-3h code + test + code-reviewer obligatoire
**Risk** : faible — formule eprouvee, prod consumers actifs valides

### Bug #5 — `dist_color_*_pct` Extension Lines NQ partiellement inactives ✅ CONFIG

**Statut** : NULL 99% sur NQ (10-12/06 = 100%, 15/06 = 89% — re-activation partielle)
**Source code** : `CPP/MIA_REFACTORED/DUMPER/DMP_F3_DistNormalisees.h:221-222` + `DMP_Reader.h:1992-1995` (Famille A `LineUntilFutureIntersection`)
**Cause racine** : etudes Sierra Chart COLOR UP / COLOR DN chart NQ avec "Draw Extension Lines until End of Chart" = NO (ou bars to calc trop court)
**Coherent avec memory** : `fix_es_bar_long_signals.md` (meme symptome cote ES)
**Fix recommande** :
- Sierra Chart VPS → chart NQ → studies COLOR UP/COLOR DN → Settings :
  - "Draw Extension Lines until End of Chart = Yes"
  - "Number of Bars to Calculate >= 1000"
- Idem pour chart ES si applicable
**Effort** : **5 min config SC**, 0 LOC
**Risk** : nul

### Bug #6 — `bool_va_confluence` seuil 10 ticks impossible

**Statut** : CONSTANT 0 (15169 bars NQ + 11762 ES, top_freq=100%)
**Source** : `CPP/MIA_REFACTORED/DUMPER/DMP_Transform.h:1727-1728` — formule correcte
**Cause racine** : seuil `|cur_vpoc - prev_vpoc| <= 10 ticks` (= 2.5 points NQ) jamais atteint. Diff median observe NQ = 400+ ticks, ES = 446 ticks.
**Statut consumer** : deja drop par `CORE/dataset_builder.py:150` ("rule_80pct et bool_va_confluence retires post-regen quasi-constants")
**Fix recommande** : recalibrer 20-30 ticks OU normaliser ATR `va_vpoc_drift_atr = |cur_vpoc - prev_vpoc| / atr_d`
**Effort** : 1 ligne C++ + recompile = 15 min
**Risk** : nul (deja drop ML)

### Bug #7 — Cleanup 14 features DROP definitif + commentaire trompeur

**Features** : `dist_comp_20d/50d_vpoc/vah/val/wap`, `inside_comp_20d/50d_va`, `comp_vpoc_align_20_50/day_20`, `ovn_high_lvl/low_lvl`
**Statut** : aucun consumer prod actif identifie (grep cross-codebase)
**Action** :
1. Cleanup commentaire trompeur `run_sierra_enricher.py:171-186` qui promet re-injection inexistante
2. Documenter drop definitif dans `DOCS/INVENTAIRE_DUMPER_VS_BOT.md`
3. Memory note : charts 30/31 SC perdus = dette technique (re-creer ces charts ou definitivement abandonner)
**Effort** : 30 min
**Risk** : nul

---

## 4. CATEGORIES "FAUX DEAD" (~120 features) — RARE EVENTS NORMAUX

Le DEAD filter Phase 4.1 est **trop strict** sur les flags binaires d'events sporadiques. Liste exemples :

| Famille | Features rare events | Top_freq % | Action |
|---|---|---|---|
| 7_REVERSAL | `ctx_climax_signal`, `ctx_delta_exhaustion`, `ctx_poor_high/low`, `ctx_failed_auction`, `ctx_double_top_trap`, `ctx_momentum_exhaustion` | 73-96% | Marquer `is_event_based=True`, exempter |
| 6_SIERRA_BN | `bn_absorb_ask/bid`, `bn_color_up/dn_2`, `bn_color_*_fwd1` | 96-99% | Idem |
| 7_REVERSAL | `ctx_div_at_swing`, `ctx_div_density_20` | 99% | Idem |
| 3_IB_OVERNIGHT | `ib_broken_up/dn`, `ib_is_narrow` | 96-99% | Idem |
| 5_ORDER_FLOW | `fp_edge_buy` | 95% | Idem |
| 3_IB_OVERNIGHT | `after_high/low/open`, `dist_after_*_pct` | 96% NULL | Session-dependent, plus de data RTH-after necessaire |

**Action recommandee** : ameliorer `tools/dead_filter_phase4.py` avec flag `--exempt-event-based` qui detecte les binaires (n_unique <= 2) ou top_value=False/0 et applique seuil top_freq=99.5% au lieu de 95%.

---

## 5. PATTERNS IDENTIFIES (memorial)

### VALIDATION_MISS (4 occurrences confirmees aujourd'hui)
- Bug #1 cvd_day_dir : pas monitore post-deploy
- Bug #2 delta_div_clean : INCIDENT #52 RESOLU sans verif empirique
- Bug #3 composite_poc : J+1 action item commit 941edd2 jamais coche
- Bug #4 dist_blind : commentaire promesse re-injection inexistante

→ Renforce memory `feedback_validation_miss_pre_deploy.md` (souverain 12/06). 8+ occurrences depuis 27/04.

### COMMENT_FALSE (1 occurrence)
- Bug #3 composite_poc : commentaire "safety reset" = casse la feature

→ Pattern documente dans `.claude/rules/incident-protocol.md`.

### PATTERN_11 V1 evite
- Bug #2 delta_div : tests Phase 2.2 testaient coherence du dict, **pas la semantique du seuil**. Classic case.
- Bug #6 bool_va_confluence : composite naif (`diff <= seuil`) sans normalisation ATR.

---

## 6. ROADMAP FIX (priorite + effort cumule)

| Sprint | Bugs | Effort | Quand |
|---|---|---|---|
| S1 critique bias | #1 cvd_day_dir + #2 delta_div_clean | ~2h30 | mardi 16/06 matin |
| S2 features ML | #3 composite_poc + #5 Extension Lines | ~1h30 | mardi 16/06 PM |
| S3 re-injection | #4 dist_blind streaming Python | ~3h30 | mercredi 17/06 |
| S4 cleanup | #6 bool_va_confluence + #7 cleanup | ~1h | jeudi 18/06 |
| S5 validation finale | re-catalog + bilan avant/apres | ~2h | vendredi 19/06 |

**Total** : ~10h sur 4 jours

---

## 7. METRIQUES SUCCES (a verifier post-fix)

| Bug | Metrique avant | Metrique cible apres |
|---|---|---|
| #1 cvd_day_dir | NQ 100% top=+1 | Distribution +1/0/-1 = 50/15/35% (similaire ES) |
| #2 delta_div_clean | 0% fire rate | 5-40% fire rate (cf raw) |
| #3 composite_poc | 100% NULL | <5% NULL apres J+5 trading days |
| #4 dist_blind | 100% NULL | <20% NULL (rythme MQ_BLIND updates) |
| #5 dist_color_pct | 99% NULL | <60% NULL (event-based) |
| #6 bool_va_confluence | 100% top=0 | >10% top=1 (confluences detectees) |

---

## 8. GARDE-FOUS PERMANENTS

1. **Bot 1 paper Sim2** : NE PAS modifier la logique trading pendant les fix. Migration sierra_enriched ce matin DOIT prouver no-regression 5 jours avant tout refactor decision.
2. **Open_type validation** : valider commit `cd695b9` (`mins_int >= ib_close`) sur NQ live aujourd'hui a 10:30 ET. Action prioritaire.
3. **Code-reviewer obligatoire** : chaque fix critique passe par agent code-reviewer + secondaire (ml-trainer / market-analyst / quality-auditor selon Bug) avec verdict GO/RESERVES/NOGO.
4. **Preservation wins historiques** : tout fix qui touche moteur decision Bot 1/2/3/4 → backtest preservation requis avant deploy (regle souveraine CLAUDE.md).
5. **INCIDENT_LOG + CHANGELOG** : chaque fix → 1 entree INCIDENT_LOG (resolution) + 1 CHANGELOG entry (impact prod + revert plan).

---

## 9. ANNEXES — Donnees brutes

- Catalog : `DATA/_AUDIT/feature_catalog_v5.csv` (613 features × 12 metadata cols)
- DEAD filter NQ : `DATA/_AUDIT/dead_filter_phase4__NQ_multi_4j.csv` (157 DEAD)
- DEAD filter ES : `DATA/_AUDIT/dead_filter_phase4__ES_multi_5j.csv` (160 DEAD)
- JSONL concat : `DATA/_AUDIT/_NQ_multi_4j.jsonl`, `_ES_multi_5j.jsonl`
- Rapports agents : sauvegardes dans cette session Claude Code (logs)

**Note finale** : audit empirique, donnees collectees live sur 4-5 jours apres rollover U26. Resultats fiables pour identification bug racine mais **5+ jours additionnels souhaites** pour calibration finale seuils (Bug #2 MIN_DELTA_SLOPE notamment).
