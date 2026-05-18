# Bot 3 V2 — Project Structure Tracker

**Usage** : Vue arborescente + status tracker auto-update. À mettre à jour à CHAQUE création/modif module Bot 3 v2.

**Convention** : pas de modif fichier Bot 3 v2 sans update ce tracker. Non-négociable.

**Dernière mise à jour** : 2026-05-18 (Phase 0.5 finalisée — agent ULTRATHINK NOGO résolu, baseline 11j Bot 3 v1)

---

## Légende status

- `⬜ TODO` : à créer / pas démarré
- `🟡 WIP` : work in progress (code commencé, pas finalisé)
- `🔵 REVIEW` : code complet, en attente review agent
- `🟢 GO` : reviewed GO, déployé / actif
- `🔴 NOGO` : reviewed NOGO, à corriger
- `⚫ DEPRECATED` : remplacé / retiré

---

## Arborescence cible Bot 3 v2

```
D:\TRADING_SIERRA_CHART_AUTO\
│
├── CORE\
│   ├── bot3_narrative_state_machine.py       ⬜ TODO Phase 1 [~600 LOC]
│   ├── bot3_story_trackers.py                ⬜ TODO Phase 1 [~350 LOC]
│   ├── bot3_narrative_persistence.py         ⬜ TODO Phase 1 [~120 LOC]
│   ├── bot3_narrative_logging.py             ⬜ TODO Phase 1 [~80 LOC]
│   ├── bot3_plot_twist_detectors.py          ⬜ TODO Phase 2 [~300 LOC]
│   ├── bot3_scenario_validator.py            ⬜ TODO Phase 2 [~200 LOC]
│   ├── bot3_direction_resolver.py            ⬜ TODO Phase 3 [~400 LOC]
│   ├── bot3_shadow_mode.py                   ⬜ TODO Phase 3 [~150 LOC]
│   ├── audit_narrative_phase5.py             ⬜ TODO Phase 5 [~400 LOC]
│   │
│   ├── bot3_config.py                        🟢 GO (refactor Phase 1 : +30 flags)
│   ├── bot3_level_definitions.py             🟢 GO (refactor Phase 4 : +nature=)
│   ├── bot3_decision_engine.py               🟢 GO (refactor Phase 4 : +narrative_direction param)
│   ├── bot3_mp_engine.py                     🟢 GO (refactor Phase 1+4 : injection NSM)
│   ├── bot3_snapshot_recorder.py             🟢 GO (refactor Phase 4 : +narrative fields)
│   ├── bot3_context_analyzer.py              🟢 GO (no change, lu en input)
│   ├── bot3_breakout_retest.py               🟢 GO (no change, PATTERN MIRROR)
│   └── log_catalog.py                        🟢 GO (extend Phase 1 : +8 codes BOT3_NSM_*)
│
├── tests\bot3\
│   ├── test_narrative_state_machine.py       ⬜ TODO Phase 1 [~400 LOC]
│   ├── test_story_trackers.py                ⬜ TODO Phase 1 [~300 LOC]
│   ├── test_narrative_persistence.py         ⬜ TODO Phase 1 [~150 LOC]
│   ├── test_plot_twist_detectors.py          ⬜ TODO Phase 2 [~250 LOC]
│   ├── test_scenario_validator.py            ⬜ TODO Phase 2 [~200 LOC]
│   ├── test_direction_resolver.py            ⬜ TODO Phase 3 [~500 LOC]
│   └── test_narrative_integration.py         ⬜ TODO Phase 3 [~300 LOC]
│
├── tools\
│   ├── replay_narrative_state_machine.py     ⬜ TODO Phase 1 [~200 LOC]
│   ├── replay_direction_resolver.py          ⬜ TODO Phase 3 [~250 LOC]
│   └── audit_shadow_divergences.py           ⬜ TODO Phase 3 [~150 LOC]
│
├── DOCS\
│   ├── plans\2026-05-18-bot3-narrative-layer-spec.md   🟢 GO (master plan)
│   ├── BOT3V2_KNOWLEDGE_BASE.md                         🟢 GO (KB livres + modules + rules)
│   ├── BOT3V2_AGENT_BRIEF_TEMPLATE.md                   🟢 GO (4 templates briefs)
│   ├── BOT3V2_PROJECT_STRUCTURE.md                      🟢 GO (CE FICHIER)
│   ├── BOT3_NARRATIVE_PHASE5_AUDIT_REPORT.md            ⬜ TODO Phase 5
│   └── INCIDENT_LOG.md                                  🟢 GO (entry 2026-05-18 Pattern 11 inv)
│
├── LOGS\
│   ├── reviews\                                          🟢 GO (dir + README + .gitkeep)
│   │   ├── README.md
│   │   ├── REVIEW_BOT3V2_*.json                         ⬜ TODO (créés au fil reviews)
│   │   └── ASSEMBLY_VERDICT_BOT3V2_FINAL_*.json         ⬜ TODO Phase 5
│   │
│   └── bot3_v2\                                          🟢 GO (dir + .gitkeep)
│       ├── narrative_state_YYYYMMDD.jsonl                ⬜ TODO Phase 1+
│       ├── resolver_decisions_YYYYMMDD.jsonl             ⬜ TODO Phase 3+
│       ├── gate_pending_YYYYMMDD.jsonl                   ⬜ TODO Phase 3+
│       ├── shadow_divergences_YYYYMMDD.jsonl             ⬜ TODO Phase 3+
│       └── trade_journal_YYYYMMDD.jsonl                  ⬜ TODO Phase 4+
│
└── .claude\memory\
    ├── project_bot3_v2_narrative_chantier.md             🟢 GO (auto-charge)
    ├── feedback_bot3v2_{module}_{insight}.md             ⬜ TODO (créés après chaque review)
    └── MEMORY.md                                          🟢 GO (entry ajoutée)
```

---

## Status tracker par phase

### Phase 0.5 — Pro Standard Foundation ✅ GO (18/05)

| Fichier | Status | Date | Commit | Review |
|---------|--------|------|--------|--------|
| DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md (v2 conventions clarifiées) | 🟢 GO | 2026-05-18 | (next) | agent Plan ULTRATHINK |
| DOCS/BOT3V2_KNOWLEDGE_BASE.md (v2 Databento canonical) | 🟢 GO | 2026-05-18 | (next) | - |
| DOCS/ADR/0001-dsr-statistical-design.md | 🟢 GO | 2026-05-18 | (next) | ml-trainer pending Phase 5 |
| DOCS/ADR/0002-nsm-pattern-reference-live-enricher-state.md | 🟢 GO | 2026-05-18 | (next) | market-analyst pending Phase 1 |
| DOCS/BOT3_V1_BASELINE_11D_20260518.md | 🟢 GO | 2026-05-18 | (next) | baseline empirique |

**Findings clés Phase 0.5** :
- Convention "Databento" reformulée : payload V4 enriched canonical AUTORISÉ (inclut `bn_*` re-emits), lecture directe DMP raw INTERDITE
- NSM pattern reference = `LiveEnricherState` (NOT BRS) — différences shape clé + lifecycle documentées
- ConfirmationGate INTÉGRÉ DirectionResolver via `wait_for` field adaptive (pas module séparé) — économie 250 LOC
- DSR Phase 5 design : 5-7 scenarios canonical + 12 mois data + Bonferroni + sample weights Lopez Ch 4
- Baseline Bot 3 v1 réelle 11j : WR 44% (vs 13% sample biaisé 2j), LONG 80% (vs 93% biaisé), 46% timeouts
- Cibles Phase 5 GO révisées : WR v2 ≥54% (10pp gain), SHORT ratio ≥35%, timeouts ≤30%

### Phase 0 — Spec & Docs persistance ✅ GO

| Fichier | Status | Date | Commit | Review |
|---------|--------|------|--------|--------|
| DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md | 🟢 GO | 2026-05-18 | e733a6e | - |
| DOCS/BOT3V2_KNOWLEDGE_BASE.md | 🟢 GO | 2026-05-18 | e733a6e | - |
| DOCS/BOT3V2_AGENT_BRIEF_TEMPLATE.md | 🟢 GO | 2026-05-18 | e733a6e | - |
| DOCS/BOT3V2_PROJECT_STRUCTURE.md | 🟢 GO | 2026-05-18 | (next) | - |
| .claude/memory/project_bot3_v2_narrative_chantier.md | 🟢 GO | 2026-05-18 | (memory) | - |
| CLAUDE.md auto-load section 4 | 🟢 GO | 2026-05-18 | e733a6e | - |
| DOCS/INCIDENT_LOG.md entry Pattern 11 inv | 🟢 GO | 2026-05-18 | e733a6e | - |
| DOCS/IDEAS_BACKLOG.md entry chantier majeur | 🟢 GO | 2026-05-18 | e733a6e | - |
| LOGS/reviews/.gitkeep + README.md | 🟢 GO | 2026-05-18 | (next) | - |
| LOGS/bot3_v2/.gitkeep | 🟢 GO | 2026-05-18 | (next) | - |

### Phase 1.5 — Mini-detour features manquantes live 🟡 J+1 AM

Cf sanity check 18/05 : 3 features absentes du payload live, présentes batch parquet.

| Fichier | Status | Date | Commit | Review | Notes |
|---------|--------|------|--------|--------|-------|
| CORE/enricher_chain.py (port session_segment) | ⬜ TODO | - | - | - | Phase B option_c_plus extend |
| CORE/enricher_chain.py (port profile_shape) | ⬜ TODO | - | - | - | game_changers extend |
| CORE/enricher_chain.py (port cvd_session) | ⬜ TODO | - | - | - | cvd_features extend |

### Phase 1 — Foundations NSM + StoryTrackers 🟡 EN COURS (spec done, code J+2-3)

| Fichier | Status | Date | Commit | Review | Notes |
|---------|--------|------|--------|--------|-------|
| DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md | 🟢 GO | 2026-05-18 | (next) | market-analyst ULTRATHINK 4.20/5 | Spec NSM complete 17 etats 32 transitions |
| CORE/bot3_narrative_state_machine.py | 🟢 GO | 2026-05-18 | (next) | 62/62 pytest + replay 5j ES GO PHASE 2 (6/6 criteres reformules) + 4 reviews ULTRATHINK (market-analyst+code-reviewer+ml-trainer x2) | NSM ~900 LOC + 15 etats + 36 transitions (T1-T32 + T6bis/T7bis/T9bis OAOR/ORR + T30b/T31b) + FLICKER_THRESHOLD=12 calibre |
| tools/replay_narrative_state_machine.py | 🟢 GO | 2026-05-18 | (next) | replay ES 5j VERDICT GO PHASE 2 (37 transitions, 100% sessions actives, 38% short, 44% coverage, 20% sessions flicker) | StoryTrackers integrate + 6 criteres reformules post-NOGO ml-trainer |
| CORE/bot3_story_trackers.py | 🔵 REVIEW | 2026-05-18 | (next) | spec 4.30/5 + 13/13 pytest PASS + bench p50=287us | 13 trackers code livre (~340 LOC) |
| CORE/bot3_narrative_persistence.py | 🔵 REVIEW | 2026-05-18 | (next) | ADR 0003 + 3 tests inline PASS | Pickle commun + backup rotation 24h |
| CORE/bot3_narrative_logging.py | 🔵 REVIEW | 2026-05-18 | (next) | 11/11 codes resolve PASS | emit helpers + verify codes registered au load |
| CORE/log_catalog.py (extend) | 🟢 GO | 2026-05-18 | (next) | 11/11 resolve PASS | +11 codes BOT3_NSM/STORY |
| CORE/bot3_config.py (refactor) | ⬜ TODO | - | - | - | +flags kill switch |
| CORE/bot3_mp_engine.py (refactor) | ⬜ TODO | - | - | - | Injection NSM tracking only |
| CORE/log_catalog.py (extend) | ⬜ TODO | - | - | - | +8 codes BOT3_NSM_* |
| tests/bot3/test_narrative_state_machine.py | 🟢 GO | 2026-05-18 | (next) | 62/62 pytest PASS | T1-T32 + T6bis/T7bis/T9bis (OAOR/ORR) + T30b/T31b + flicker(=12)/session/pickle/concurrency + F1 race + F6 ordering + UNKNOWN guard + all_observed_open_types regression |
| tests/bot3/test_story_trackers.py | 🟢 GO | 2026-05-18 | (next) | 13/13 pytest PASS | trend/BOS/pickle/concurrency/reset/rejection/snap/ringbuf/slope/nan |
| tests/bot3/__init__.py + conftest.py | 🟢 GO | 2026-05-18 | (next) | - | Fixtures Stub Regime/Swing/Story |
| tests/bot3/test_story_trackers.py | ⬜ TODO | - | - | - | 20+ tests |
| tests/bot3/test_narrative_persistence.py | ⬜ TODO | - | - | - | 5+ tests kill -9 recovery |
| tools/replay_narrative_state_machine.py | ⬜ TODO | - | - | - | Replay sur parquet 30j |

**Critère passage Phase 2** : 100% tests verts, replay 5 jours OK, latency <10ms/bar, diff `LOGS/decisions` pre/post = 0 (tracking-only).

### Phase 2 — PlotTwist + ScenarioValidator 🟢 EN COURS (J+1)

| Fichier | Status | Date | Commit | Review | Notes |
|---------|--------|------|--------|--------|-------|
| CORE/bot3_plot_twist_detectors.py | 🟢 GO | 2026-05-18 | (next) | 17/17 pytest + 3 fixes Claude 4.7 (severity max BOS throttle 30 VOL_Z tighten 2.5/3.0) | 4 detectors STRUCTURE_BREAK/VOLUME_ANOMALY/DIVERGENCE/CAPITULATION + state ring buffer |
| CORE/bot3_scenario_validator.py | 🟢 GO | 2026-05-18 | (next) | 14/14 pytest + 3 fixes Claude 4.7 externe (strongest signal + bars negatifs defensif + RANGE doc decision) | Time decay 240 bars + 10 etats whitelist invalidating twists |
| CORE/log_catalog.py (extend) | 🟢 GO | 2026-05-18 | (next) | 17 codes load OK | +6 codes PLOT_TWIST_* + SCENARIO_* |
| CORE/bot3_narrative_logging.py (extend) | 🟢 GO | 2026-05-18 | (next) | _verify_codes_registered PASS | BOT3V2_NARRATIVE_CODES +6 Phase 2 |
| tests/bot3/test_plot_twist_detectors.py | 🟢 GO | 2026-05-18 | (next) | 17/17 pytest PASS | BOS/VOL/DIV/CAPIT + scan_all + pickle + nan |
| tests/bot3/test_scenario_validator.py | 🟢 GO | 2026-05-18 | (next) | 14/14 pytest PASS | time decay + invalidating twists + strongest + bars negative + 8 etats |
| tools/replay_narrative_state_machine.py (extend) | 🟢 GO | 2026-05-18 | (next) | replay 5j ES VERDICT GO PHASE 2 (7/7 criteres) | +PlotTwistDetectorsState + scan_all + validator pipeline |

### Phase 3 — DirectionResolver + Shadow mode ⬜ TODO

| Fichier | Status | Date | Commit | Review | Notes |
|---------|--------|------|--------|--------|-------|
| CORE/bot3_direction_resolver.py | ⬜ TODO | - | - | - | 10-15 scenarios table-driven |
| CORE/bot3_shadow_mode.py | ⬜ TODO | - | - | - | Logger parallèle JSONL |
| CORE/bot3_mp_engine.py (extend) | ⬜ TODO | - | - | - | Integration resolver |
| LOGS/bot3_v2/resolver_decisions_*.jsonl | ⬜ TODO | - | - | - | Auto-créé runtime |
| LOGS/bot3_v2/shadow_divergences_*.jsonl | ⬜ TODO | - | - | - | Auto-créé runtime |
| tests/bot3/test_direction_resolver.py | ⬜ TODO | - | - | - | 25+ tests par scenario_id |
| tests/bot3/test_narrative_integration.py | ⬜ TODO | - | - | - | 10+ tests end-to-end |
| tools/replay_direction_resolver.py | ⬜ TODO | - | - | - | Replay shadow |

### Phase 4 — Refactor levels + integration ⬜ TODO

| Fichier | Status | Date | Commit | Review | Notes |
|---------|--------|------|--------|--------|-------|
| CORE/bot3_level_definitions.py (refactor) | ⬜ TODO | - | - | - | +nature= parallèle |
| CORE/bot3_decision_engine.py (refactor) | ⬜ TODO | - | - | - | Signature étendue |
| CORE/bot3_mp_engine.py (extend) | ⬜ TODO | - | - | - | Passe narrative_direction |
| CORE/bot3_config.py (extend) | ⬜ TODO | - | - | - | BOT3_USE_NARRATIVE_DIRECTION=True après GO |
| CORE/bot3_snapshot_recorder.py (extend) | ⬜ TODO | - | - | - | +narrative fields |
| Symétrie SHORT levels (5 new mirror) | ⬜ TODO | - | - | - | MQ_CALL_0DTE, IB_HIGH, GEX_UP, VWAP_W_SD1U, PVAH |
| LOGS/bot3_v2/trade_journal_*.jsonl | ⬜ TODO | - | - | - | Auto-créé runtime |

### Phase 5 — Backtest DSR Lopez + GO/NOGO ⬜ TODO

| Fichier | Status | Date | Commit | Review | Notes |
|---------|--------|------|--------|--------|-------|
| CORE/audit_narrative_phase5.py | ⬜ TODO | - | - | - | Walk-forward 12 folds + DSR Lopez |
| DOCS/BOT3_NARRATIVE_PHASE5_AUDIT_REPORT.md | ⬜ TODO | - | - | - | Rapport final |
| LOGS/reviews/ASSEMBLY_VERDICT_BOT3V2_FINAL_*.json | ⬜ TODO | - | - | - | Verdict 3 agents finale |

### Phase 6 — Shadow live VPS ⬜ TODO

### Phase 7 — Switch live ⬜ TODO

---

## Workflow de mise à jour ce fichier (obligatoire)

À chaque création / modif module Bot 3 v2 :

1. **Mettre à jour le tableau de la phase concernée** :
   - Status : `⬜ TODO` → `🟡 WIP` → `🔵 REVIEW` → `🟢 GO`
   - Date : YYYY-MM-DD jour de modif
   - Commit : hash 7 char du commit Git
   - Review : `{agent}_{verdict}` ex `market-analyst_GO`
   - Notes : 1 ligne clarification

2. **Mettre à jour la légende arborescente** en haut

3. **Mettre à jour `Dernière mise à jour`** ligne 7

4. **Commit Git** ce fichier dans le même commit que le module

5. **Si phase passe à GO complet** : tag Git + push + entry INCIDENT_LOG si finding important

---

## Convention naming review verdicts

Format : `LOGS/reviews/REVIEW_BOT3V2_{module}_{agent}_{YYYYMMDD}.json`

Exemples :
- `REVIEW_BOT3V2_narrative_state_machine_market-analyst_20260525.json`
- `REVIEW_BOT3V2_narrative_state_machine_code-reviewer_20260526.json` (cross-check Tier 1)
- `REVIEW_BOT3V2_direction_resolver_market-analyst_20260601.json`

Si verdict change après iterations (ex GO-RES → GO après fix) :
- Garder ancien fichier (audit historique)
- Créer nouveau fichier avec timestamp ultérieur
- Ancien fichier devient automatiquement obsolete (latest = la plus récente)

---

## Cross-reference

- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md`
- Knowledge base : `DOCS/BOT3V2_KNOWLEDGE_BASE.md`
- Agent briefs : `DOCS/BOT3V2_AGENT_BRIEF_TEMPLATE.md`
- Memory chantier : `.claude/memory/project_bot3_v2_narrative_chantier.md`
- Logs reviews : `LOGS/reviews/`
- Logs bot3_v2 JSONL : `LOGS/bot3_v2/`
