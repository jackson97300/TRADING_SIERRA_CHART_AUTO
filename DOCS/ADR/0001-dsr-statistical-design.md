# ADR 0001 — DSR Lopez Phase 5 Statistical Design

**Date** : 2026-05-18
**Phase** : Bot 3 v2 Narrative Layer Phase 0.5
**Status** : Accepted
**Auteur** : Jackson + Claude + agent Plan ULTRATHINK + (futur) ml-trainer ULTRATHINK Phase 5
**Reviewers** : ml-trainer (sign-off final Phase 5)

## Contexte

Le plan original Bot 3 v2 (master plan ligne 162) demandait :
> "DSR ≥0.95 sur 8+ scenarios, walk-forward 12 folds 6 mois"

L'agent ULTRATHINK Plan a démontré que ce critère est **mathématiquement inatteignable** :
- 6 mois data trading ≈ 130 jours
- 12 folds = ~10.8 jours par fold (avec purge + embargo Lopez Ch 7 = ~9 jours utiles)
- Bot 3 v1 produit ~5 trades/jour, Bot 3 v2 vise même volume
- Si 15 scenarios à tester : 5/15 = 0.33 trades/jour/scenario
- Par fold : **9 × 0.33 = ~3 trades/scenario/fold**

**DSR Lopez Ch 11** (Bailey & Lopez de Prado 2014) est **inutilisable sous n=30 par direction**. A fortiori sous n=3.

Bonferroni correction explicit absent du plan original :
- Tester 15 scenarios = `p_threshold = 0.05 / 15 = 0.003`
- DSR threshold standard 0.95 correspond à un test unique
- Pour 15 tests simultanés : `DSR_threshold = 1 - (1 - 0.95)/k = 0.997` (Bonferroni-corrected)

Sample weight uniqueness Lopez Ch 4 également absent : sur multi-sym ES + NQ + MGC en parallèle, trades concurrents same bar → biais double-counting si pas pondéré `sample_weight = 1 / concurrent_trades`.

## Décision

3 leviers combinés pour rendre DSR Phase 5 statistiquement défendable :

### Levier 1 — Réduire scenarios pre-Phase 5 à 5-7 canonical

Au lieu de 10-15 scenarios :
- 5-7 scenarios "core canonical" testés en Phase 5 (couvrent 80% des contextes typiques)
- Les 8-10 autres scenarios = **DEFERRED Phase 6 shadow live** (data empirique additionnelle pendant 15+ jours shadow)
- Décision GO/NOGO sur scenarios canonical d'abord, extension après data confirmation

Scenarios canonical proposés (à valider ml-trainer Phase 5 design review) :
1. `TREND_DOWN_ACCELERATION + support_options → SHORT_AT_BREAK`
2. `TREND_DOWN_EXHAUSTION + support_options → LONG_REJECTION` (Wyckoff Spring)
3. `RANGE_FLOOR_REBOUND + support_options → LONG_REJECTION`
4. `BREAKDOWN_CONTINUATION + support_options → SHORT_RETEST`
5. `TREND_UP_ACCELERATION + resistance_options → LONG_AT_BREAK`
6. `RANGE_TOP_REJECTION + resistance_options → SHORT_REJECTION`
7. `NY_EXHAUSTION + any → REVERSAL`

### Levier 2 — Étendre data backtest à 12 mois (au lieu de 6 mois)

- 6 mois → 12 mois = 260 jours trading
- 12 folds = ~20 jours/fold (avec purge embargo Lopez = ~17 jours utiles)
- 5 trades/jour × 17 jours = 85 trades/fold (tous scenarios confondus)
- 85 / 7 scenarios = **~12 trades/scenario/fold**
- Sur 12 folds : 144 trades/scenario total = **proche n=200 cible**

Data source : étendre `DATA/DATASETS/V4/*.parquet` à 12 mois (avec live_enricher backfill historique si nécessaire).

### Levier 3 — Bonferroni explicit + sample weights Lopez Ch 4

**Bonferroni correction documentée** :
- 7 scenarios canonical → `p_threshold = 0.05 / 7 = 0.00714`
- DSR threshold ajusté : `DSR_threshold = 1 - (1 - 0.95) / 7 = 0.993`
- Documenté dans `audit_narrative_phase5.py` + commenté

**Sample uniqueness Lopez Ch 4** :
- Pour chaque trade `t_i`, `weight_i = 1 / number_concurrent_trades_at_time(t_i)`
- Implémentation : `audit_narrative_phase5.compute_sample_weights(trades_df)` retourne `pd.Series` weights
- Pondère le calcul Sharpe / DSR

**Sequential bootstrap** (alternative pour CV walk-forward) : utiliser `mlfinlab` library si disponible OR custom impl. Lopez Ch 4.2 algorithm 1.

## Conséquences

### Positives
- DSR Phase 5 statistiquement défendable (n~144 par scenario vs ~36 dans plan original)
- Bonferroni explicit = anti faux positifs académique correct
- Sample weights = pas de biais multi-sym
- Phases 1-4 peuvent démarrer **sans bloquer** sur ce design (s'applique Phase 5)

### Négatives
- 12 mois data = retro-backfill à organiser pre-Phase 5
- 5-7 scenarios initiaux = couverture réduite (8-10 scenarios additionnels deferred Phase 6)
- Sequential bootstrap = complexité implementation Phase 5

### Risques
- Si 12 mois data v3 historique a des trous (pre-fix C++ schema 3.7.x) : utilisable seulement 6-8 mois propres
  - **Mitigation** : audit data quality avant Phase 5 démarre. Si trous : retour Levier 1 (5 scenarios seulement) + n cible 100 (vs 200)
- Si certains scenarios canonical n'atteignent pas DSR 0.993 : à arbitrer Phase 5 (drop ou recalibrer)
  - **Mitigation** : ABRtion possible (toggle on/off scenarios) + memory feedback documenté

## Validation

Avant Phase 5 démarre, **ml-trainer ULTRATHINK** doit :
1. Valider la liste finale 5-7 scenarios canonical (vs proposition ADR)
2. Confirmer disponibilité 12 mois data v3 propre (audit quality)
3. Designer `audit_narrative_phase5.py` skeleton (DSR + Bonferroni + sample weights)
4. Verdict GO design avant code Phase 5

Trace review : `LOGS/reviews/REVIEW_BOT3V2_audit_narrative_phase5_ml-trainer_<date>.json`

## Cross-references

- Lopez de Prado "Advances in Financial ML" :
  - Ch 4 Sample uniqueness + sequential bootstrap
  - Ch 7 Cross-Validation Walk-Forward (purge + embargo)
  - Ch 11 The dangers of backtesting (DSR, PSR, Bonferroni)
- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md` (section Phase 5)
- Knowledge Base : `DOCS/BOT3V2_KNOWLEDGE_BASE.md` section 1.5 Lopez
- Memory `feedback_data_mining_trap.md` (DSR Lopez n>=100 par direction obligatoire)
- Critical tasks review : `.claude/rules/critical-tasks-review.md` critère #8 Backtest

## Status courant

- [x] ADR accepté (Phase 0.5 J+0)
- [ ] ml-trainer review design Phase 5 (avant Phase 5 démarre, attendu mi-juin)
- [ ] Implementation `audit_narrative_phase5.py` (Phase 5)
- [ ] Audit data quality 12 mois (Phase 5 prerequis)
