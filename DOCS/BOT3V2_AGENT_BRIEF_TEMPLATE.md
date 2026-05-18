# Bot 3 V2 — Templates Agent Brief ULTRATHINK

**Usage** : Copier le template approprié + remplir `{placeholders}` + invoquer agent. Garantit que chaque review est exhaustive et reproductible.

**Référence projet** :
- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md`
- Knowledge base : `DOCS/BOT3V2_KNOWLEDGE_BASE.md`

---

## Template 1 — `market-analyst` ULTRATHINK

```
AGENT : market-analyst (mode ULTRATHINK)

## Mission
Review {module_name} pour le chantier Bot 3 v2 Narrative Layer (refonte décision Bot 3 paper trader).

## Contexte critique (lire avant)
Jackson trade comme un pro discrétionnaire :
- Pre-écrit 2-3 scénarios avant l'open
- Construit narration par actes (Asia/London/NY)
- Multi-TF awareness (D1+1h+15m+5m)
- Attend confirmation pattern (1-3 bars) avant fire
- Flat si narrative invalidée

Bot 3 V1 (15-18/05) : 15 trades, WR 13%, 14 LONG / 1 SHORT par construction. Pattern 11 V1 inversé confirmé (108 ctx writes vs 4 reads).

## Knowledge base à charger (livres + chapitres précis)

LIRE EN PRIORITE :
- **Dalton "Mind over Markets"** :
  - Ch 4-5 Day Types (Trend, Double Distribution, Normal, Normal Variation, Non-Trend)
  - Ch 6-7 Open Types (D1 OD, D2 OTD, D3 ORR, D4 OA)
  - Ch 8 Initial Balance (1st hour structure)
  - Ch 9-10 Value Area + Acceptance vs Rejection
  - Ch 12 Profile Shape (P, b, balanced)
- **Steidlmayer Market Profile** : TPO, POC, VAH/VAL, Naked POC magnet
- **Wyckoff** :
  - 3 Lois (Supply-Demand, Cause-Effect, Effort-Result)
  - 5 Phases A-E (Spring, Upthrust, SOS, SOW)
  - VSA (Volume Spread Analysis)
  - Composite Operator
- **Mark Douglas "Trading in the Zone"** :
  - 5 fundamental truths
  - Probabilistic thinking (edge sur série, pas trade individuel)
  - No projection bias
- **ICT Smart Money Concepts** :
  - Break of Structure (BOS) : close > last_swing_high.price ET close[i-1] <= last_swing_high.price
  - Change of Character (CHoCH) : 1er BOS contre-tendance
  - Liquidity Sweeps (buy-side / sell-side)
  - Order Blocks, FVG, Premium/Discount, Inducement
- **Bookmap orderflow** : Iceberg, Absorption, Footprint reading

Pour chaque finding, **citer le chapitre exact** du livre pertinent.

## Modules MIA à grep + lire (pre-existants)

OBLIGATOIRE de lire avant de juger :
- CORE/regime_engine.py (compute_regime mode/favor/vol/actionable)
- CORE/game_changers.py + _streaming.py (open_type, day_type, profile_shape, open_zone)
- CORE/sessions_swings_lag_streaming.py (swing pivots lag-10)
- CORE/sessions_swings_simple_streaming.py (session high/low/opens)
- CORE/phase_d_dalton_levels.py (naked POC tracker)
- CORE/edge_zones_streaming.py + edge_zones_engine.py (Phase 3c-B deployée 18/05)
- CORE/phase_b_plus_color_streaming.py (Phase 3c-B deployée 18/05)
- CORE/value_area_running.py (VAH/VAL/POC running)
- CORE/phase_b_helpers.py (IB features, session_metadata)
- CORE/bias_calculator_v6.py (bias_score multi-features)
- CORE/bot3_breakout_retest.py (PATTERN ARCHITECTURAL à mirror)
- CORE/bot3_context_analyzer.py (12 dims ctx, INPUT du NSM)
- CORE/bot3_decision_engine.py (evaluate_decision + _resolve_neutral_side)
- CORE/bot3_level_definitions.py (TIER1/2/3 + SIDAK + COMBOS)
- CORE/bot3_mp_engine.py (orchestrateur)
- CORE/log_catalog.py (convention codes log)

## Règles projet à intégrer

LIRE :
- .claude/rules/critical-tasks-review.md (protocole agent + logs souverains A-F)
- .claude/rules/module-review-protocol.md (6 STEPS Tier 1)
- .claude/rules/data-quality.md
- .claude/rules/log-debug-protocol.md
- .claude/rules/core.md (walk-forward obligatoire)
- feedback_swing_proximity_veto.md (veto LONG près swing low)
- feedback_data_mining_trap.md (DSR Lopez n≥100 obligatoire)
- feedback_lightgbm_no_composite_indicators.md (anti composite hardcoded)
- feedback_pattern11_repetition_avoided.md (no refactor n<30)
- feedback_cross_instrument_bonus_not_gate.md
- feedback_proactive_mentor.md

## Code à auditer
{file_path} (~{loc_estimated} LOC)

## Tests empiriques OBLIGATOIRES (vraies données)

DATASETS DISPONIBLES :
- Parquet v3 propre : DATA/DATASETS/V4/2026-04-15_2026-05-15_{ES,NQ,MGC}_v4.parquet
- Live enriched 18/05 post-deploy Phase 3c : DATA/live_enriched/{ES,NQ,MGC}/20260518_*.jsonl
- Logs Bot 3 v1 baseline : LOGS/decisions/decisions_2026051{5,8}_paper_v2.jsonl + LOGS/trading/trading_20260515_paper_v2.jsonl

CAS TESTS OBLIGATOIRES (8 cas + stress) :
1. Trend day fort bearish (15/05 ES Asia/London, 12 trades v1)
2. Breakdown intra-session (18/05 ES Asia/London, 3 LONG MQ_PUT)
3. Range bound stable (semaine 1 mai parquet v3)
4. Roll day (`is_roll_day=1` parquet v3)
5. High vol news event (`within_news_*_5m=1`)
6. Low vol Asia stagnant (`vol_zscore_20<-1 ET rvol<0.5`)
7. Open Drive D1 (`open_type=0 ET range expansion bar1-5`)
8. Open Rotation D4 (`open_type=3 ET IB narrow`)

STRESS TESTS :
- Kill -9 + restart pendant 10 bars actives (recovery)
- Pickle corruption simulée
- Latency profiling (<5ms/bar pour NSM, <2ms resolver)

## Verdict requis (4 dimensions, score 0-5)

1. **Méthodologie** : Cohérence vs livres canon. Citer chapitres précis.
2. **Code Quality** : Lisibilité, fail-soft, anti-Pattern 11 V1, mirror BreakoutRetestSM pattern.
3. **Empirique** : 8 cas pass/fail + replay 15-18/05 cohérence + stress tests + latency.
4. **Trading Sense** : Si Bot 3 v2 avait utilisé ce module, aurait-il évité combien de pertes / pris combien de SHORT manqués vs baseline 15-18/05 (delta ticks chiffré) ?

Score global = (Méthodo×0.30 + CodeQ×0.20 + Empir×0.30 + Trading×0.20)
- GO : ≥4.0
- GO-AVEC-RESERVES : 3.5-4.0
- NOGO : <3.5

## Output

Rapport 1500-2500 mots structuré :
1. Verdict global + score 4 dim
2. Méthodologie (citations chapitres livres)
3. Code Quality findings
4. Tests empiriques résultats (table 8 cas + stress)
5. Trading Sense (replay 15-18/05 simulation v2 vs v1)
6. Findings critiques (BLOCKING / MAJEUR / MINEUR)
7. Recommendations actions concrètes (LOC fix précis)
8. Memory feedback à créer (nom + contenu suggéré)

Archive verdict JSON : LOGS/reviews/REVIEW_BOT3V2_{module}_{agent}_{date}.json
Memory feedback créée : .claude/memory/feedback_bot3v2_{module}_{insight}.md
```

---

## Template 2 — `code-reviewer` ULTRATHINK

```
AGENT : code-reviewer (mode ULTRATHINK)

## Mission
Review code quality + architecture {module_name} pour Bot 3 v2 Narrative Layer.

## Knowledge base
Lire DOCS/BOT3V2_KNOWLEDGE_BASE.md sections 2 (modules MIA) et 3 (rules).

## Focus principal
- Pattern mirror BreakoutRetestStateMachine (cf bot3_breakout_retest.py)
- Anti-Pattern 11 V1 : composite hardcoded sans backtest
- Anti silent fallback (cf tick-size-policy.md, data-quality.md)
- Fail-soft + try/except CORE imports
- Pickle hygiene atomic write
- Race condition multi-symbol
- Codes log catalog enregistrés
- Latence <5ms/bar (mesurer)

## Tests empiriques
Run unitaires pytest + integration sur replay 1 jour v4_enriched 18/05.

## Verdict 4 dim (cf KNOWLEDGE_BASE section 5)
Focus pondéré : Méthodo×0.20 + CodeQ×0.40 + Empir×0.25 + Trading×0.15

## Output
Rapport 800-1500 mots, citations file:line obligatoires.
Archive verdict JSON + memory feedback.
```

---

## Template 3 — `ml-trainer` ULTRATHINK

```
AGENT : ml-trainer (mode ULTRATHINK)

## Mission
Validation méthodologique statistique {module_name} pour Bot 3 v2.

## Knowledge base focus
- Lopez de Prado AFML Ch 3 (Meta-labeling), Ch 4 (Sample uniqueness), Ch 5 (FFD ADF), Ch 7 (Walk-forward), Ch 8 (Feature importance), Ch 11 (DSR/PSR/Bonferroni)
- Mark Douglas (probabilistic thinking, edge over series)

## Focus principal
- Stationnarité features (ADF test si applicable, ex cvd_5d_rolling_ffd)
- Feature importance MDA > MDI
- Walk-forward 12 folds chronologique (PAS random split)
- DSR Lopez par scenario_id (≥0.95 OR n≥200)
- PSR globale ≥0.95
- Bonferroni si multiple testing
- Anti data mining trap (cf feedback_data_mining_trap.md)
- Anti composite hardcoded (cf feedback_lightgbm_no_composite_indicators.md)

## Tests empiriques
- Walk-forward 6 mois v3 parquet
- DSR per scenario calculation
- Distribution analysis (no fat tail leak)

## Verdict 4 dim
Focus pondéré : Méthodo×0.35 + CodeQ×0.10 + Empir×0.40 + Trading×0.15
GO/NOGO statistique strict.

## Output
Rapport 1200-2000 mots avec metrics tableaux.
Archive verdict JSON + memory feedback.
```

---

## Template 4 — `Plan` (architect) ULTRATHINK

```
AGENT : Plan (architect mode ULTRATHINK)

## Mission
Critique architecturale + alternatives pour {module_name} Bot 3 v2.

## Knowledge base focus
- Tous livres canon (cohérence philosophique)
- Modules existants pattern mirror obligatoire

## Focus principal
- Architecture cohérente avec ecosystem MIA
- Pattern reuse vs new (anti over-engineering)
- Trade-offs identifiés
- Plan B alternatives
- Interfaces propres (signatures def + dataclasses)
- Decoupling testable

## Output
Spec architecturale + plan implementation phasé.
Pas de code, design uniquement.
```

---

## Invocation typique (orchestration Claude)

```python
# Pseudo-code orchestration
def dispatch_module_review(module_name, file_path, phase, tier):
    """Workflow standard pour review module Bot 3 v2."""

    # Charger knowledge base
    kb = read("DOCS/BOT3V2_KNOWLEDGE_BASE.md")
    plan = read("DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md")

    # Choisir template selon module
    if module_name in ["narrative_state_machine", "direction_resolver"]:
        primary_agent = "market-analyst"  # méthodologie trading
    elif module_name in ["narrative_persistence", "narrative_logging"]:
        primary_agent = "code-reviewer"   # qualité code
    elif module_name in ["audit_narrative_phase5"]:
        primary_agent = "ml-trainer"      # validation stats

    # Render template
    brief = render_template(
        template=primary_agent,
        module_name=module_name,
        file_path=file_path,
        loc_estimated=estimate_loc(file_path),
        knowledge_base_path="DOCS/BOT3V2_KNOWLEDGE_BASE.md",
        plan_path="DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md"
    )

    # Dispatch agent (background si Tier 1, foreground si Tier 2/3)
    agent_id = dispatch_agent(primary_agent, brief,
                              run_in_background=(tier == 1))

    # Si Tier 1 : cross-check 2e agent (angle différent)
    if tier == 1:
        secondary_agent = (
            "code-reviewer" if primary_agent == "market-analyst"
            else "market-analyst"
        )
        brief_2 = render_template(template=secondary_agent, ...)
        agent_2_id = dispatch_agent(secondary_agent, brief_2,
                                     run_in_background=True)

    # Await + croiser verdicts
    verdict_primary = await_agent(agent_id)
    if tier == 1:
        verdict_secondary = await_agent(agent_2_id)
        verdict_final = reconcile_verdicts(verdict_primary, verdict_secondary)
    else:
        verdict_final = verdict_primary

    # Archive
    write_json(
        f"LOGS/reviews/REVIEW_BOT3V2_{module_name}_{primary_agent}_{today()}.json",
        verdict_final
    )

    # Memory feedback auto-créée par l'agent dans son output
    return verdict_final
```

---

## Format auto-rappel Claude pour orchestration

À chaque session sur Bot 3 v2, Claude DOIT :
1. Lire `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md` (statut phases)
2. Lire `DOCS/BOT3V2_KNOWLEDGE_BASE.md` (livres + modules + rules + tests)
3. Lire memory `project_bot3_v2_narrative_chantier.md` (état courant)
4. Si dispatch agent : utiliser ces templates obligatoirement
5. Si review verdict reçu : archiver JSON + créer memory feedback + update master plan checkbox

Pas de raccourci. Pas d'invocation agent sans brief complet. C'est la condition pour ne RIEN perdre cross-sessions.
