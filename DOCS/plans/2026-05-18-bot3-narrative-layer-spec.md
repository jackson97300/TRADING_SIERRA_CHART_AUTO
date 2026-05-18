# Bot 3 V2 — Narrative Layer Spec (Master Plan)

**Date** : 2026-05-18
**Auteur** : Jackson + Claude + agents (market-analyst + code-reviewer + Plan)
**Statut** : Phase 0 — Spec finalisée, implementation à démarrer
**Methodologie persistance** : Ce document est la **source de vérité unique**. Si `/compact` ou nouvelle session, lire ce fichier en premier puis `BOT3V2_KNOWLEDGE_BASE.md` puis `BOT3V2_AGENT_BRIEF_TEMPLATE.md` pour reprendre le chantier sans perte.

---

## Vision philosophique (règle souveraine Jackson 18/05)

> **"On ne doit pas être biaisé sur une direction, on doit être bidirectionnel et le contexte décide si c'est LONG ou SHORT."**

> **"Le marché raconte une histoire continue. Le job du trader = être à l'écoute, pas projeter sa propre histoire dessus."** (Mark Douglas)

> **"Bot 3 actuel arrive au milieu du film et spécule au doigt mouillé."** (Jackson)

→ Refonte fondamentale Bot 3 : capable de **lire le narratif** multi-TF + structure + state machine, et **décider direction depuis le contexte** plutôt qu'appliquer une direction fixe au niveau touché.

## Diagnostic empirique Bot 3 V1 (15-18/05)

- **15 trades sur 2 jours, WR 13%** (2 TP / 10 SL / 3 TIMEOUT)
- **14/15 LONG / 1 SHORT** = biais structurel par construction dict niveaux
- **108 ctx writes** dans `analyzer` vs **4 ctx reads** dans `decision_engine` hors safe defaults
- **13 niveaux LONG / 4 SHORT / 8 NEUTRAL** dans `bot3_level_definitions.py` = bias 3:1 LONG mathématique
- **91.7% trades fired avec `regime.is_actionable=0`** (11/12 vendredi) = régime ignoré
- **Pattern 11 V1 inversé** : features extraites mais pas utilisées en décision
- **Niveau MQ_PUT_0DTE re-fire 3x en 4h après 2 échecs** = cooldown trop court, pas de blacklist

## Architecture cible

```
SOURCES (V4 enriched ~465 cols/bar 1m) + buffer 60 bars history
       │
       ▼
   PRE-NARRATIVE EXTRACT (existant, réutilisé)
   • analyze_context() 12 dims (bot3_context_analyzer.py)
   • compute_regime() (regime_engine.py)
   • sessions_swings_lag_streaming.py
   • phase_d_dalton_levels.py (naked_poc)
   • edge_zones_streaming.py + phase_b_plus_color_streaming.py (Phase 3c-B live)
       │
       ▼
   NARRATIVE LAYER (NEW — 4 sous-modules)
   1. StoryTrackers.update(bar, history)
      → hh_count_60, ll_count_60, bars_since_BOS, slope_close_30/60,
        acceptance_zones, rejection_count
   2. NarrativeStateMachine.transition(bar, ctx, regime, story, swings)
      → state + scenarios actifs [mirror BreakoutRetestStateMachine pattern]
   3. PlotTwistDetectors.scan(bar, ctx, history, story)
      → BOS, volume_anomaly, divergence, capitulation
   4. ScenarioValidator.check(state, new_bar, twists)
      → INVALIDATED si trigger
       │
       ▼
   DIRECTION RESOLVER
   resolve(state, level_touched, ctx, regime, story, twists)
   → {side, confidence, rationale, scenario_id}
   [10-15 scenarios pré-écrits, table-driven]
       │
       ▼
   DECISION ENGINE V2 (refactor decision_engine + mp_engine)
   evaluate_decision(..., narrative_direction=resolved)
   IF BOT3_USE_NARRATIVE_DIRECTION=True ET narrative_direction != NO_TRADE:
      use narrative_direction.side
   ELSE: fallback level_def["side"] heritage  ← KILL SWITCH
```

## 9 modules NEW à construire

| # | Module | LOC | Rôle |
|---|--------|-----|------|
| 1 | `CORE/bot3_narrative_state_machine.py` | ~600 | NSM stateful, mirror `BreakoutRetestStateMachine` pattern. 17 états (PRE_OPEN, OPEN_DRIVE, CONTINUATION/REVERSAL/RANGE/EXHAUSTION par session, INVALIDATED). Transitions déterministes. Events consommables (state_transition, scenario_invalidated, plot_twist) |
| 2 | `CORE/bot3_story_trackers.py` | ~350 | Story trackers : hh_count_60, ll_count_60, bars_since_BOS, slope_close_30/60, acceptance_zones, rejection_count_at_level, swing_progression_score |
| 3 | `CORE/bot3_plot_twist_detectors.py` | ~300 | 4 detectors : STRUCTURE_BREAK (BOS/CHoCH ICT), VOLUME_ANOMALY (z>2 vs prev 5), DIVERGENCE (price/CVD), CAPITULATION (3+climax pattern) |
| 4 | `CORE/bot3_scenario_validator.py` | ~200 | `is_narrative_still_valid()` : evalue triggers d'invalidation + time decay 4h |
| 5 | `CORE/bot3_direction_resolver.py` | ~400 | 10-15 scenarios pre-écrits table-driven `(state, level_nature) → {side, confidence, rationale}`. Fallback heritage si NEUTRAL + no scenario match |
| 6 | `CORE/bot3_shadow_mode.py` | ~150 | Logger parallèle Phase 3 (legacy vs narrative comparison) |
| 7 | `CORE/bot3_narrative_persistence.py` | ~120 | Pickle atomic write + recovery (fix dette `BreakoutRetestStateMachine` perd son état au restart) |
| 8 | `CORE/bot3_narrative_logging.py` | ~80 | 8 codes log + extend `_REASON_TO_LOG_CODE` (mp_engine:97-118) |
| 9 | `CORE/audit_narrative_phase5.py` | ~400 | Backtest comparatif legacy vs narrative + DSR Lopez par scenario_id walk-forward 12 folds |

**Total NEW** : ~2600 LOC code + ~1200 LOC tests

## 5 modules REFACTOR existants (chirurgical, kill switch obligatoire)

| Module | Changement | LOC delta |
|--------|-----------|-----------|
| `CORE/bot3_level_definitions.py` | Ajout clé `nature=` (support/resistance/structural) **EN PARALLELE** de `side=`. NE PAS supprimer `side`. | +30 |
| `CORE/bot3_decision_engine.py` | Signature `evaluate_decision(..., narrative_direction: Optional[ResolvedDirection]=None)` | +100 |
| `CORE/bot3_mp_engine.py` | Injection NSM update AVANT boucle niveaux. Passe `narrative_direction` à `evaluate_decision` | +80 |
| `CORE/bot3_config.py` | Flags `BOT3_USE_NARRATIVE_DIRECTION=False` (kill switch), `BOT3_NARRATIVE_TRACKING_ONLY=True`, buffer sizes | +30 |
| `CORE/bot3_snapshot_recorder.py` | Ajoute `narrative_state`, `scenario_id`, `direction_rationale` aux snapshots | +30 |

## Plan 5 phases avec checkboxes (tracking persistance)

### Phase 1 — Foundations : NSM + StoryTrackers (TRACKING ONLY)
**Durée** : ~1 semaine
**Statut** : `[ ]` Not started

- [ ] **Spec Phase 1** approuvée par Jackson
- [ ] `CORE/bot3_narrative_state_machine.py` créé (skeleton + 5 états core ASIA/LONDON/NY/INVALIDATED + persistence pickle)
- [ ] `CORE/bot3_story_trackers.py` créé (10 story trackers)
- [ ] `CORE/bot3_narrative_persistence.py` créé (atomic write + recovery)
- [ ] `CORE/bot3_narrative_logging.py` créé (codes log)
- [ ] `CORE/bot3_config.py` flags ajoutés
- [ ] `CORE/bot3_mp_engine.py` injection NSM update (tracking only)
- [ ] Tests unit (50+ tests) : `tests/bot3/test_narrative_state_machine.py`, `test_story_trackers.py`, `test_narrative_persistence.py` → 100% verts
- [ ] **Critère passage Phase 2** : Replay 5 jours (13-17/05) — diff `LOGS/decisions/*.jsonl` Phase 1 pre/post = 0, latence ajoutée <10ms/bar, ≥4 transitions NSM par jour par symbole
- [ ] Review agent ULTRATHINK code-reviewer (verdict 4 dim ≥4)
- [ ] Memory feedback créé `feedback_bot3v2_phase1_*.md`
- [ ] Archive `LOGS/reviews/REVIEW_BOT3V2_phase1_*.json`

### Phase 2 — Plot Twist + Scenario Validator (TRACKING ONLY)
**Durée** : ~1 semaine
**Statut** : `[ ]` Not started

- [ ] `CORE/bot3_plot_twist_detectors.py` créé (4 twist types)
- [ ] `CORE/bot3_scenario_validator.py` créé (invalidation triggers + time decay)
- [ ] NSM extension : transition `* → INVALIDATED` via validator
- [ ] Tests unit (40+ tests) → 100% verts
- [ ] **Critère passage Phase 3** : Histogramme twists 2-10/jour/sym, replay 15-18/05 confirme ≥1 invalidation par jour de perte (4/4 jours), 0 regression Phase 1
- [ ] Review agent ULTRATHINK market-analyst (Wyckoff/ICT canon)
- [ ] Memory feedback + archive review

### Phase 3 — Direction Resolver + Shadow mode
**Durée** : ~1 semaine
**Statut** : `[ ]` Not started

- [ ] `CORE/bot3_direction_resolver.py` créé (10-15 scenarios table-driven)
- [ ] `CORE/bot3_shadow_mode.py` créé (log parallèle JSONL)
- [ ] `CORE/bot3_mp_engine.py` integration `resolve_direction_from_narrative` AVANT `evaluate_decision` (exécution = legacy seulement)
- [ ] JSONL `LOGS/bot3_v2/resolver_decisions_*.jsonl` + `shadow_divergences_*.jsonl` actifs
- [ ] Tests unit (25+ tests par scenario_id) + integration (10+ end-to-end)
- [ ] **Critère passage Phase 4** : Bidirectional ratio shadow ≥35% SHORT (vs 6.7% legacy), n_divergences 30-60 sur 5 jours, audit manuel 30 cases ≥50% défendable canon Steidlmayer/Dalton/Wyckoff
- [ ] Review agent ULTRATHINK market-analyst + ml-trainer (cross-check)
- [ ] Memory feedback + archive review

### Phase 4 — Refactor levels + integration decision_engine
**Durée** : ~1 semaine
**Statut** : `[ ]` Not started

- [ ] `CORE/bot3_level_definitions.py` ajout `nature=` parallèle
- [ ] `CORE/bot3_decision_engine.py` signature étendue
- [ ] `CORE/bot3_mp_engine.py` passe `narrative_direction`
- [ ] `CORE/bot3_config.py` `BOT3_USE_NARRATIVE_DIRECTION=True` (après GO)
- [ ] `CORE/bot3_snapshot_recorder.py` ajout fields
- [ ] Symétrie LONG/SHORT : ajouter MQ_CALL_0DTE SHORT mirror, IB_HIGH SHORT, GEX_UP SHORT, VWAP_W_SD1U SHORT, PVAH SHORT
- [ ] Tests A/B Sim1 narrative vs Sim2 legacy paper trader
- [ ] **Critère passage Phase 5** : 0 regression backtest 6 mois (PF ±10%), WR paper narrative-aware ≥ WR paper legacy, bidirectional ratio paper ≥30% SHORT sur 50+ trades
- [ ] Review agent ULTRATHINK code-reviewer + market-analyst (cross-check Tier 1)
- [ ] Memory feedback + archive review

### Phase 5 — Backtest empirique DSR Lopez + GO/NOGO live
**Durée** : ~1 semaine
**Statut** : `[ ]` Not started

- [ ] `CORE/audit_narrative_phase5.py` créé
- [ ] Walk-forward 12 folds 6 mois v3 (PAS de random split — `.claude/rules/core.md`)
- [ ] DSR Lopez par `scenario_id` (10-15 scenarios) — chaque ≥0.95 OR n≥200 pour passer
- [ ] PSR globale ≥0.95 vs benchmark legacy
- [ ] **Critère GO live** : DSR ≥0.95 sur 8+ scenarios, WR walk-forward ≥40%, bidirectional 40-60%, regime alignment 0% misfire, drawdown max <1.5x legacy
- [ ] **Critère NOGO** : DSR <0.90 sur >30% scenarios → retour Phase 3, OU WR <30% → retour Phase 2
- [ ] Review agent ULTRATHINK ml-trainer (final sign-off) + market-analyst + code-reviewer
- [ ] Memory feedback final + archive review final
- [ ] `DOCS/BOT3_NARRATIVE_PHASE5_AUDIT_REPORT.md` généré

### Phase 6 — Shadow live VPS (après GO Phase 5)
- [ ] Deploy Bot 3 v2 en shadow live VPS (parallèle Bot 3 actuel, no real fire)
- [ ] Run 5 jours shadow comparison
- [ ] Final review

### Phase 7 — Switch live (après validation Phase 6)
- [ ] Bot 3 v1 désactivé
- [ ] Bot 3 v2 live
- [ ] Monitoring J+1 / J+7 / J+30
- [ ] Rollback plan documenté + flag `BOT3_USE_NARRATIVE_DIRECTION` kill switch testé

## Logging total — 8 codes + 5 JSONL dédiés

Codes log dans `CORE/log_catalog.py` (préfixe BOT3_) :

| Code | Niveau | Cat | Usage |
|------|--------|-----|-------|
| `BOT3_NSM_STATE_TRANSITION` | MAJEUR | decisions | NSM change d'état |
| `BOT3_NSM_INVALIDATED` | CRITIQUE | events | Narrative cassée, flat + reset |
| `BOT3_PLOT_TWIST_DETECTED` | MAJEUR | events | BOS / divergence / capitulation |
| `BOT3_DIRECTION_RESOLVED` | INFO | decisions | Resolver retourne direction |
| `BOT3_NARRATIVE_NO_TRADE` | INFO | decisions | Resolver NO_TRADE ambigu |
| `BOT3_SHADOW_DIVERGENCE` | MAJEUR | decisions | Phase 3 : v1 ≠ v2 |
| `BOT3_NSM_PERSIST_OK` | INFO | events | Pickle save success |
| `BOT3_NSM_PERSIST_RECOVERED` | ALERTE | events | Recovery fresh state après corruption |

JSONL dédiés `LOGS/bot3_v2/` :
- `narrative_state_YYYYMMDD.jsonl` (~1 ligne/bar = 4320 lignes/jour 3 syms)
- `resolver_decisions_YYYYMMDD.jsonl` (chaque LEVEL_CONTACT)
- `gate_pending_YYYYMMDD.jsonl` (suivi confirmation gate)
- `shadow_divergences_YYYYMMDD.jsonl` (Phase 3 v1 vs v2)
- `trade_journal_YYYYMMDD.jsonl` (cycle vie complet par trade)

Volumétrie estimée ~5 MB/jour, rotation 90j = 450 MB.

## Mesures succès chiffrées

| Metric | Avant 15-18/05 | Cible Phase 5 GO |
|--------|----------------|------------------|
| WR | 13% (2/15) | ≥40% walk-forward |
| LONG ratio | 93% (14/15) | 40-60% |
| Trades avec `regime.actionable=0` | 92% (11/12) | 0% |
| Régime alignment | 0% (0/15) | 100% |
| Confirmation wait | 0 bar (touch=fire) | 1-3 bars |
| R:R minimum vérifié | non | 1:2 strict |
| DSR Lopez par scenario | non calculé | ≥0.95 sur 8+ scenarios |

## Risques + mitigations

| Risque | Sévérité | Mitigation |
|--------|----------|-----------|
| Pattern 11 V1 (composite hardcoded sans backtest) | HAUTE | DirectionResolver = table déterministe par scenario_id, pas score numérique. DSR walk-forward Phase 5 obligatoire. |
| Data mining trap | HAUTE | DSR ≥0.95 OR n≥200 par scenario. Sinon désactivé. |
| Régression edge actuel (SIDAK PF≥1.35) | HAUTE | Kill switch `BOT3_USE_NARRATIVE_DIRECTION=False`. SIDAK levels gardent side=heritage en fallback prioritaire. |
| Over-engineering (Douglas KISS) | MOYENNE | 17 states max, 4 twists, 10-15 scenarios. Aucun ajout post-Phase 5 sans DSR ≥0.95. |
| Pickle corruption restart | MOYENNE | Module dédié `bot3_narrative_persistence.py` atomic write + fresh fallback. Tests kill -9. |
| Latence ajoutée >10ms/bar | MOYENNE | Budget <40ms Phase 1, <50ms Phase 4. Profiling obligatoire. |
| Race condition multi-symbol | MOYENNE | Pattern `_states: dict[symbol, ...]` isolé (mirror BreakoutRetestSM). |
| Time decay false positive | BASSE | INVALIDATED → auto-recompute PRE_OPEN_NEUTRAL next bar. Pas de dead-lock. |
| Confluence breakout_retest | MOYENNE | NSM NE BLOQUE PAS breakout_retest signals (state machine indépendante). |
| Codes log_catalog manquants (KeyError) | BASSE | Tests vérifient resolve() sans KeyError. Codes registered avant commit. |

## Protocole review ULTRATHINK obligatoire

Pour CHAQUE module, le brief agent doit inclure :
- **Knowledge base** : 7 livres + chapitres précis (cf `DOCS/BOT3V2_KNOWLEDGE_BASE.md`)
- **Modules MIA** : 16 modules pre-existants à lire (cf knowledge_base)
- **Règles projet** : 10 rules + memories pertinentes (cf knowledge_base)
- **Tests empiriques** : 8 cas obligatoires sur vraies données
- **Verdict 4 dimensions** : Méthodologie / Code Quality / Empirique / Trading Sense (score 0-5, GO si moyenne ≥4)
- **Cross-check 2e agent** pour modules Tier 1 (NSM, DirectionResolver, decision_engine_v2, level_definitions_v2)
- **Tracking** : verdict archivé `LOGS/reviews/REVIEW_BOT3V2_*.json`
- **Memory feedback** auto-créé après review

Template brief : `DOCS/BOT3V2_AGENT_BRIEF_TEMPLATE.md`.

## État d'avancement (à jour à chaque session)

**Dernière mise à jour** : 2026-05-18 (session initiale)

- **Phase 0** : ✅ Spec finalisée + docs persistantes créées
- **Phase 1** : ⬜ À démarrer
- **Phase 2-7** : ⬜ Pending

## Liens

- `DOCS/BOT3V2_KNOWLEDGE_BASE.md` — Knowledge base livres + modules + rules + tests
- `DOCS/BOT3V2_AGENT_BRIEF_TEMPLATE.md` — Templates briefs agents par type
- Memory : `project_bot3_v2_narrative_chantier.md` (auto-charge début session)
- `DOCS/INCIDENT_LOG.md` 2026-05-18 entry — Pattern 11 V1 inversé Bot 3 documenté
- `DOCS/IDEAS_BACKLOG.md` entry — "Bot 3 v2 Narrative Layer" chantier majeur 5 semaines
- `LOGS/reviews/` — archives reviews verdicts
