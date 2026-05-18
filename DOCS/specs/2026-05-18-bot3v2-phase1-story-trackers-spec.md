# Spec Phase 1 — `CORE/bot3_story_trackers.py` (StoryTrackers)

**Date** : 2026-05-18
**Phase** : Bot 3 v2 Narrative Layer Phase 1 (Foundations TRACKING ONLY)
**Spec author** : Agent market-analyst ULTRATHINK (mode mentor adversarial)
**Reviewers cibles** : market-analyst + code-reviewer Tier 2 (input critique NSM)
**Verdict spec auto-eval** : **4.30/5 GO-AVEC-RESERVES** (1 réserve LOC `acceptance_zones`)

---

## TL;DR

- **11 trackers obligatoires + 2 bonus** (13 total)
- **~340 LOC code + ~310 LOC tests** (20+ tests, coverage 90%)
- Mirror `LiveEnricherState` pattern (ADR 0002)
- Ring buffer `deque(maxlen=60)` (anti-pattern P0-2 DataFrame croissant)
- **Pickle commun NSM + Story** (Option A, ADR 0003)
- 3 codes log enregistrés
- TRACKING ONLY Phase 1 = ZERO impact prod Bot 3 v1
- Latence cible <3ms/bar médiane

## 11 Trackers (citations canon)

| # | Tracker | Type | Canon | Stateful ? |
|---|---------|------|-------|-----------|
| 1 | `hh_count_60` | int | ICT BOS HH structural | NON (pure recompute) |
| 2 | `ll_count_60` | int | ICT LL (mirror) | NON |
| 3 | `swing_progression_score` | float [-1, +1] | Dow Theory + Wyckoff Tape Reading | NON (dérivé) |
| 4 | `slope_close_30` | float | Lopez AFML Ch 5 (OLS, pas EMA) | NON |
| 5 | `slope_close_60` | float | Idem | NON |
| 6 | `bars_since_last_BOS` | int | ICT Smart Money formula canonical | OUI |
| 7 | `last_BOS_dir` | int {-1, 0, +1} | ICT BOS direction | OUI |
| 8 | `bars_since_session_high` | int | Dalton Ch 8 Initial Balance | OUI |
| 9 | `bars_since_session_low` | int | Mirror | OUI |
| 10 | `acceptance_zones_session` | list[dict] | Dalton Ch 9-10 HVN intra-session | OUI |
| 11 | `rejection_count_at_level` | dict | Dalton p.102 + Anti re-fire MQ_PUT | OUI |
| 12 (bonus) | `hh_count_5` | int | Anti-BOS contradictoire | NON |
| 13 (bonus) | `bars_since_open` | int | NSM T6/T7 OPEN_DRIVE requires bar_idx_session>30 | OUI |

## Décisions retenues

### Décision A — `acceptance_zones_session` FULL (vs MVP stub)
Cohérent directive Jackson "no shortcut". LOC budget OK (340→360). +20 LOC code + 2 tests. ROI massif anti dette technique.

### Décision B — Pickle commun NSM + Story (Option A)
ADR 0003 créé : `bot3_narrative_persistence.py` sauvegarde NarrativePersistedState (NSM + Story atomiquement). Évite desync au recovery.

### Décision C — Pas de cross-check 2e agent sur spec
story_trackers = Tier 2 par master plan. Cross-check Tier 1 = sur le code livré, pas la spec. Spec a passé market-analyst ULTRATHINK 4.30/5.

## 3 réserves auto-adversariales (à mitiger pendant code)

1. **`acceptance_zones` LOC budget** → résolu par décision A (full)
2. **Profiling latence non mesuré** → microbenchmark obligatoire avant commit (1000 iter data V4 réelle)
3. **`rejection_count_at_level` hook-only** → vérification J+2 : grep `increment_rejection_at_level` dans `bot3_mp_engine.py`

## 3 Codes log

```
BOT3_STORY_BOS_DETECTED       (MAJEUR, events)    - nouveau BOS
BOT3_STORY_TREND_CONFIRMED    (MAJEUR, decisions) - hh_count_60>=3 + slope_60>0.15 (throttle 30 bars)
BOT3_STORY_REVERSAL_CANDIDATE (ALERTE, events)    - slope flip + HH/LL contradictoire (throttle 10 bars)
```

## Sequencing strict

```
story_trackers (code + tests) AVANT NSM (code + tests)
                ↓
       NSM consume story_trackers.snapshot()
```

Justification : NSM transitions T10/T11/T20-T29 dépendent de `hh_count_60`, `bars_since_BOS`, `slope_close_60`. Sans story_trackers, NSM tests retournent `None` → Pattern 11 V1 silent fallback.

## Critère passage Phase 2 (mesurable)

1. Latence `update_story_trackers` < 3ms/bar médiane (cProfile p50/p95/p99)
2. Coverage tests ≥ 90%
3. `hh_count_60` médiane 4-10 sur 11j baseline
4. `BOT3_STORY_BOS_DETECTED` events ≥ 2/jour/sym moyenne
5. Pickle recovery PASS (kill -9 test)
6. 0 KeyError sur log_catalog
7. 0 race condition multi-thread (test concurrency ES+NQ)

## Cross-references

- Spec NSM consumer : `DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md`
- ADR 0002 pattern : `DOCS/ADR/0002-nsm-pattern-reference-live-enricher-state.md`
- ADR 0003 pickle commun : `DOCS/ADR/0003-narrative-persistence-atomic-common.md`
- Pattern ref code : `CORE/live_enricher_state.py:51-200`
- Input swing_state : `CORE/sessions_swings_lag_streaming.py:106-110`
- Baseline 11j : `DOCS/BOT3_V1_BASELINE_11D_20260518.md`
- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md`

## Status

- [x] Spec rédigée (market-analyst ULTRATHINK 4.30/5)
- [x] Décision A : acceptance_zones FULL
- [x] Décision B : ADR 0003 pickle commun
- [x] Décision C : no cross-check spec (Tier 2)
- [ ] Microbenchmark latence préparé (J+1 AM)
- [ ] Code `bot3_story_trackers.py` (J+1)
- [ ] Tests 20+ pytest (J+1 PM)
- [ ] Integration NSM (J+2)
- [ ] Review Tier 2 (J+3)

---

**Spec output complet agent market-analyst** : 14 sections détaillées disponibles dans le contexte conversation 18/05 13h. Reproduction full ici inutile (cf agent task ID a8171df123310096a).
