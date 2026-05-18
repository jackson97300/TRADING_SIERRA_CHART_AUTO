# Bot 3 V2 Narrative Layer — Knowledge Base centralisée

**Date** : 2026-05-18
**Usage** : Reference unique pour BRIEF AGENT REVIEW ultrathink + AUTO-LOAD Claude début de session sur Bot 3 v2.

Si tu (Claude ou agent) attaques un module Bot 3 v2, lire ce fichier EN ENTIER avant de coder ou reviewer.

## CONVENTIONS PROJET SOUVERAINES (Jackson 18/05)

### Data source : payload V4 enriched canonical Databento (clarification 18/05)

Bot 3 v2 consomme **exclusivement le payload `live_enriched` canonical** (~465 cols/bar) produit par le service `live_enricher` (nssm 24/7).

**Distinction explicite** :

| Source | Status | Exemple |
|--------|--------|---------|
| Payload V4 enriched canonical (`databento_paper_trader_v2` → `ctx`) | ✅ AUTORISÉ | `bn_*` re-emits, `dist_edge_*`, `n_color_*`, `regime_*`, etc. (465 cols) |
| Lecture directe `DATA/{sym}/{date}_{sym}.jsonl` (DMP SC raw bypass) | ❌ INTERDIT | Bypass live_enricher = risk drift |
| Engines Python streaming (`edge_zones_streaming.py`, etc.) | ✅ AUTORISÉ | Calculs derived in-pipeline |
| Sierra Chart Studies API directe (ACSIL) | ❌ INTERDIT | C'est le job du DMP SC |

`live_enricher` est la **seule porte d'entrée** pour Bot 3 v2. Les features `bn_*` (Wyckoff VSA, ex absorption) sont autorisées car re-emits dans le payload canonical.

Cf master plan section "Data source unique" pour justification complète.

### Commits Git réguliers + structure auto-update
- Commit séparé par étape logique
- Message structuré (cf master plan section "Commits Git réguliers")
- Tag Git par phase complétée
- Update `DOCS/BOT3V2_PROJECT_STRUCTURE.md` à CHAQUE modif (non-négociable)
- Update checkbox master plan + memory chantier

### Headers fichiers Python (NEW modules obligatoire)
- Docstring début : module name + role + data source + dates + phase + review trace
- Section HISTORY commentée mise à jour à chaque modif >20 LOC
- Cf master plan section "Headers fichiers Python"

---

## 1. Knowledge base livres — 7 ouvrages canon

### 1.1 Dalton — "Mind over Markets" (Steidlmayer Market Profile)
**Chapitres pertinents pour Bot 3 v2** :
- **Ch 4-5 Day Types** : Trend Day, Double Distribution, Normal Day, Normal Variation, Non-Trend Day. Bot 3 v2 doit détecter le day type via `game_changers.day_type` et adapter la stratégie.
- **Ch 6-7 Open Types** : Open Drive (D1 OD_UP/OD_DOWN), Open Test Drive (D2 OTD_UP/OTD_DOWN), Open Rejection Reverse (D3 ORR), Open Auction (D4 OA). Utilisés par NSM pour transitions `PRE_OPEN_* → OPEN_DRIVE_*`.
- **Ch 8 Initial Balance** : 1st hour high/low = structure foundationnelle. IB cassé tôt + vol expansion = trend day signal.
- **Ch 9-10 Value Area** : 70% volume zone = consensus institutionnel. Acceptance vs Rejection patterns.
- **Ch 12 Profile Shape** : P-shape (sellers exhausted), b-shape (buyers exhausted), balanced (range).

**Concepts MIA** : `open_type`, `day_type`, `profile_shape`, `open_zone`, `open_direction`, `open_bias_conf` (déjà dans `game_changers.py`).

### 1.2 Steidlmayer (Market Profile père fondateur)
**Concepts canon pour Bot 3 v2** :
- **TPO (Time Price Opportunity)** : letter-based profile representation par 30-min brackets.
- **POC (Point of Control)** : prix avec le plus de TPO = consensus court terme.
- **VAH/VAL (Value Area High/Low)** : bornes 70% volume.
- **Acceptance vs Rejection** : si prix reste 2+ TPOs dans une zone = acceptance, sinon rejection.
- **Naked POC** : POC de session précédente non retesté = magnet pour session suivante.

**Concepts MIA** : `cur_vpoc/vah/val` (volume_profile_running), `prev_vpoc/vah/val`, `dist_naked_poc_nearest_pct` (Phase 3c-C deployée 18/05), `inside_value_area`.

### 1.3 Wyckoff — "Studies in Tape Reading" + Pruden "3 Skills of Top Trading"
**Lois et phases pour Bot 3 v2** :
- **3 Lois Wyckoff** : Supply-Demand, Cause-Effect, Effort-Result. Effort-Result = volume vs price = base VSA.
- **5 Phases accumulation/distribution** :
  - Phase A : Preliminary Support (PS) + Selling Climax (SC) + Automatic Rally (AR) + Secondary Test (ST)
  - Phase B : Building cause (range)
  - Phase C : Spring (false breakdown) ou Upthrust (false breakout)
  - Phase D : Sign of Strength (SOS) ou Sign of Weakness (SOW)
  - Phase E : Markup ou Markdown
- **Composite Operator** : "le marché est manipulé par un opérateur composite qui accumule au bas et distribue en haut"
- **VSA (Volume Spread Analysis)** : volume sans suivi de prix = absorption / capitulation imminente

**Concepts MIA** : `bn_absorb_ask/bid`, `bn_absorb_bid_at_level`, `bn_absorb_ask_at_level`, `vol_spike_up/dn`, `vol_zscore_20`, `bars_since_climax`.

### 1.4 Mark Douglas — "Trading in the Zone"
**Principes mentaux pour Bot 3 v2** :
- **5 fundamental truths** :
  1. Anything can happen
  2. You don't need to know what will happen next to make money
  3. There is a random distribution between wins/losses for any set of variables that define an edge
  4. An edge is nothing more than an indication of a higher probability of one thing happening over another
  5. Every moment in the market is unique
- **Probabilistic thinking** : penser en séries de trades, pas en trades individuels. Edge stat sur 100+ trades.
- **No projection** : "le marché te dit ce qu'il fait, écoute-le". Pas de bias projeté.
- **Disciplined trader mindset** : neutralité émotionnelle, suivre l'edge.

**Application MIA** : `DirectionResolver` ne doit avoir AUCUN bias structurel LONG/SHORT. Contexte décide. Le bot ne "croit" pas, il "lit".

### 1.5 Lopez de Prado — "Advances in Financial Machine Learning"
**Chapitres pertinents pour Bot 3 v2** :
- **Ch 3 Meta-labeling** : primary model decide direction, meta model decide size (filter false positives). Pattern pour Bot 3 v2 : DirectionResolver = primary, ConfirmationGate = meta.
- **Ch 4 Sample Uniqueness** : sample weight = 1/concurrent_trades. Sequential bootstrap pour CV. Bot 3 v2 backtest doit utiliser sample weights.
- **Ch 5 Fractional Differentiation** : ADF test pour stationnarité. d* minimal qui passe ADF. `cvd_5d_rolling_ffd` Phase 3c-C utilise d=0.4 mais ADF non validé (TODO).
- **Ch 7 Cross-Validation Walk-Forward** : JAMAIS random split. Toujours chronologique avec purge + embargo. Bot 3 v2 Phase 5 = 12 folds walk-forward.
- **Ch 8 Feature Importance** : MDA (Mean Decrease Accuracy) > MDI. Bot 3 v2 narrative features doivent passer MDA.
- **Ch 11 Backtest Dangers** : DSR (Deflated Sharpe Ratio), PSR (Probabilistic Sharpe Ratio), Sharpe haircut multiple testing. Bot 3 v2 Phase 5 doit calculer DSR par scenario_id.
- **Bonferroni correction** : si on teste N scenarios, le p-value seuil = 0.05/N pour rester à 5% confidence globale.

**Application MIA** : `cvd_5d_rolling_ffd` (Phase 3c-C), DSR ≥0.95 par scenario_id Phase 5, walk-forward 12 folds.

### 1.6 ICT (Inner Circle Trader) — Smart Money Concepts
**Concepts canon pour Bot 3 v2** :
- **Break of Structure (BOS)** : `close[i] > last_swing_high.price ET close[i-1] <= last_swing_high.price` → BOS bullish. Mirror SHORT.
- **Change of Character (CHoCH)** : 1er BOS contre-tendance après une série de HH ou LL. Signal reversal.
- **Liquidity Sweeps** : prix dépasse swing high/low rapidement puis revient = stop hunt. Buy-side liquidity sweep (above high) ou Sell-side (below low).
- **Order Blocks** : dernière bar consolidation avant move impulsif = institution placement. Mitigation = retest.
- **Fair Value Gaps (FVG)** : gap entre high bar N et low bar N+2 (3-bar imbalance). Magnet futur.
- **Mitigation Blocks** : retour vers order block opposite = liquidity provided.
- **Premium / Discount Zones** : 50% du range = équilibre. Above = premium (sell zone), below = discount (buy zone).
- **Inducement** : faux setup pour piéger retail avant vrai move.
- **Imbalance** : zones où le prix passe rapidement = magnets de rebalance.

**Concepts MIA** : `liquidity_sweep_high/low_lag5`, `equal_highs_detected`, `equal_lows_detected`, `dist_last_swing_high/low`, `premium_zone`, `discount_zone`, BOS detector à coder.

### 1.7 Bookmap orderflow (Trader Dale + autres)
**Concepts orderflow pour Bot 3 v2** :
- **Iceberg orders** : grosse limite cachée, ne montre qu'une fraction. Détection : ask/bid vol persistent à un prix sans dépletion.
- **Spoofing** : grosses limites placées puis annulées (illégal mais existe). Détection : volume size disparait après touch.
- **Footprint absorption** : ask vol >> bid vol mais prix monte = buyers absorbent les sellers à un niveau. Signal défense.
- **Heatmap interpretation** : zones de liquidité concentrée = magnets.
- **Delta divergence** : prix fait LL mais delta cumul fait HL = capitulation sellers, reversal probable.

**Concepts MIA** : `footprint_builder_streaming.py`, `edge_zones_streaming.py` (Phase 3c-B), `phase_b_plus_color_streaming.py`, `bn_absorb_ask/bid_at_level`.

---

## 2. Modules MIA pre-existants — 16 modules à connaître

| # | Module | Rôle | Réutiliser pour Bot 3 v2 |
|---|--------|------|--------------------------|
| 1 | `CORE/bot3_breakout_retest.py` | State machine TOUCH → ACCEPTANCE → RETEST → ENTRY | **PATTERN ARCHITECTURAL** pour `NarrativeStateMachine` (mirror class structure) |
| 2 | `CORE/bot3_context_analyzer.py` | Extract 12 dims ctx | **INPUT** du NSM update |
| 3 | `CORE/bot3_decision_engine.py` | `evaluate_decision` + `_resolve_neutral_side` | **REFACTOR** signature étendue + `_resolve_neutral_side` devient fallback |
| 4 | `CORE/bot3_level_definitions.py` | TIER1/2/3 + SIDAK + COMBOS | **REFACTOR** ajout `nature=` parallèle |
| 5 | `CORE/bot3_mp_engine.py` | Orchestrateur touch detect + ctx + decision | **REFACTOR** injection NSM AVANT boucle niveaux |
| 6 | `CORE/regime_engine.py` | `compute_regime` mode/favor/vol/actionable | **CONSOMME DIRECT** input NSM + DirectionResolver |
| 7 | `CORE/game_changers.py` + `_streaming.py` | open_type, day_type, profile_shape, open_zone | **CONSOMME** par NSM (transitions OPEN_DRIVE) |
| 8 | `CORE/sessions_swings_lag_streaming.py` | Swing pivots lag-10 + liquidity sweeps | **CONSOMME** par StoryTrackers + PlotTwist |
| 9 | `CORE/sessions_swings_simple_streaming.py` | Session high/low + opens running | **CONSOMME** par NSM |
| 10 | `CORE/phase_d_dalton_levels.py` | pVWAP/SD, naked POC tracker, single prints | **CONSOMME** par StoryTrackers (acceptance zones) |
| 11 | `CORE/edge_zones_streaming.py` + `edge_zones_engine.py` | Stacks imbalance ask/bid via ExtensionLineBuffer | **CONSOMME** (Phase 3c-B deployée 18/05) |
| 12 | `CORE/phase_b_plus_color_streaming.py` | Color clusters BN + dist_color_*_pct | **CONSOMME** (Phase 3c-B deployée 18/05) |
| 13 | `CORE/value_area_running.py` | VAH/VAL/POC developing per session | **CONSOMME** par StoryTrackers |
| 14 | `CORE/phase_b_helpers.py` | IB features, session_metadata, volume_profile streaming | **CONSOMME** par NSM (IB cassé) |
| 15 | `CORE/bias_calculator_v6.py` | bias_score multi-features | **CONSOMME** optionnel tie-breaker |
| 16 | `CORE/log_catalog.py` | Catalog codes log centralisé | **EXTEND** avec 8 codes BOT3_NSM_* |

---

## 3. Règles projet + memories — 10 références obligatoires

Lire AVANT review/code Bot 3 v2 :

1. `.claude/rules/critical-tasks-review.md` — Protocol agent review + 8 critères critiques + section logs souverains A-F
2. `.claude/rules/module-review-protocol.md` — 6 STEPS Tier 1 modules critiques
3. `.claude/rules/data-quality.md` — Qualité features V2 (5 critères, anti silent fallback)
4. `.claude/rules/log-debug-protocol.md` — Convention logging 4 niveaux + codes catalog
5. `.claude/rules/tick-size-policy.md` — Anti silent fallback TICK_SIZE
6. `.claude/rules/core.md` — Pipeline Python rules (walk-forward obligatoire)
7. Memory `feedback_swing_proximity_veto.md` — Veto LONG près swing low (Jackson 11/05)
8. Memory `feedback_data_mining_trap.md` — DSR Lopez n>=100 par direction obligatoire (28/04)
9. Memory `feedback_lightgbm_no_composite_indicators.md` — Anti composite hardcoded (18/04)
10. Memory `feedback_pattern11_repetition_avoided.md` — No refactor si n<30 + rollback récent (30/04)
11. Memory `feedback_es_nq_mirror.md` — Hiérarchie : qualité > symétrie > screening (13/04)
12. Memory `feedback_cross_instrument_bonus_not_gate.md` — Cross-instrument = bonus, pas gate (24/04)
13. Memory `feedback_proactive_mentor.md` — Mode mentor proactif obligatoire (01/05)
14. Memory `project_bot3_v2_narrative_chantier.md` — État courant chantier (auto-charge)

---

## 4. Tests empiriques — 8 cas obligatoires sur vraies données

### Datasets disponibles

```
TEST DATA PATHS :

├── Parquet v3 propre (30j ES/NQ/MGC) :
│   ├── DATA/DATASETS/V4/2026-04-15_2026-05-15_ES_v4.parquet
│   ├── DATA/DATASETS/V4/2026-04-15_2026-05-15_NQ_v4.parquet
│   └── DATA/DATASETS/V4/2026-04-15_2026-05-15_MGC_v4.parquet
│
├── Live enriched (post-Phase 3c 18/05 03:30 ET) :
│   ├── DATA/live_enriched/ES/20260518_ES.jsonl (465 cols/bar)
│   ├── DATA/live_enriched/NQ/20260518_NQ.jsonl
│   └── DATA/live_enriched/MGC/20260518_MGC.jsonl
│
├── Trades / footprint (pour edge_zones / footprint validation) :
│   └── DATA/trades/{sym}/{date}_{sym}_trades.parquet
│
├── MenthorQ levels (options-driven niveaux) :
│   └── DATA/MENTHORQ/20260518_menthorq_complete.json
│
└── Logs Bot 3 v1 (référence baseline) :
    ├── LOGS/decisions/decisions_20260515_paper_v2.jsonl (vendredi)
    ├── LOGS/decisions/decisions_20260518_paper_v2.jsonl (today)
    └── LOGS/trading/trading_20260515_paper_v2.jsonl
```

### Cas test obligatoires par module

| # | Cas | Date / Contexte | Critère validation |
|---|-----|----------------|-------------------|
| 1 | Trend day fort bearish | 15/05 ES Asia/London (12 trades v1, 9 SL + 2 TP) | NSM doit détecter TREND_DOWN, DirectionResolver doit SHORT MQ_PUT_0DTE en break |
| 2 | Breakdown intra-session | 18/05 ES Asia/London (3 LONG MQ_PUT, 0 wins) | NSM détecte BREAKDOWN_CONTINUATION, NO_TRADE OR SHORT (vs LONG v1) |
| 3 | Range bound stable | trouver session calm semaine 1 mai parquet v3 | NSM état RANGE_RESPECTED, LONG OK seulement si rejection confirmée |
| 4 | Roll day | rechercher `is_roll_day=1` dans parquet v3 | NSM = INVALIDATED, no trade |
| 5 | High vol news event | `within_news_*_5m=1` payload | NSM flat 5min avant + 5min après |
| 6 | Low vol Asia stagnant | `vol_zscore_20<-1 ET rvol<0.5` | NSM état ASIA_RANGE, refuse trade tier 1 si confidence resolver <0.6 |
| 7 | Open Drive D1 | `open_type=0 ET range expansion bar1-5` | NSM transition PRE_OPEN → OPEN_DRIVE_DOWN/UP |
| 8 | Open Rotation D4 | `open_type=3 ET IB narrow` | NSM état OPEN_ROTATION, no trade premier IB |

### Stress tests obligatoires phase 4

- **Kill -9 + restart pendant 10 bars actives** : 100% recovery sans replay manuel (pickle hygiene)
- **Pickle corruption simulated** : fresh state automatique + log `BOT3_NSM_PERSIST_RECOVERED`
- **Gap weekend** : state à l'open dimanche soir vs Friday close (cohérence ou reset)
- **Halt / Limit move** : NSM = INVALIDATED automatique
- **Latency profiling** : NSM update <5ms/bar, direction resolver <2ms, total pipeline <40ms/bar (Phase 1) puis <50ms (Phase 4)

---

## 5. Verdict 4 dimensions — Format standard

Chaque review agent doit rendre verdict sur 4 axes (score 0-5 par dim) :

| Dimension | Critère | Référence à citer |
|-----------|---------|-------------------|
| **Méthodologie** | Cohérence vs livres canon (Dalton/Wyckoff/Lopez/ICT) | Citer chapitres précis |
| **Code Quality** | Lisibilité, fail-soft, anti-Pattern 11 V1, mirror patterns existants | `.claude/rules/critical-tasks-review.md` |
| **Empirique** | Tests vraies données (8 cas obligatoires), edge cases, stress tests | Pass/Fail par cas, latency measured |
| **Trading Sense** | Si Bot 3 v2 avait utilisé ce module, aurait-il évité combien de pertes / pris combien de SHORT manqués vs baseline 15-18/05 | Delta ticks vs Bot 3 v1 |

**Score global** = (Méthodo×0.30 + CodeQ×0.20 + Empir×0.30 + Trading×0.20). 
- GO : moyenne ≥4.0
- GO-AVEC-RESERVES : 3.5-4.0
- NOGO : <3.5

---

## 6. Cross-check Tier 1 modules

Modules **Tier 1** (= verdict 2 agents indépendants obligatoire) :
- `bot3_narrative_state_machine.py`
- `bot3_direction_resolver.py`
- `bot3_decision_engine_v2.py` (refactor)
- `bot3_level_definitions_v2.py` (refactor)

Modules **Tier 2** (= verdict 1 agent suffit) :
- `bot3_story_trackers.py`
- `bot3_plot_twist_detectors.py`
- `bot3_scenario_validator.py`
- `bot3_confirmation_gate.py`
- `bot3_shadow_mode.py`
- `bot3_narrative_persistence.py`
- `bot3_narrative_logging.py`

Modules **Tier 3** (= code-reviewer standard suffit) :
- `audit_narrative_phase5.py`
- Tests pytest

### Si verdicts cross-check divergent (Tier 1)
- Si 1er agent GO et 2e NOGO → 3e agent arbitre
- Si 1er agent GO-RES et 2e GO → GO global (consensus haut)
- Si 1er agent GO-RES et 2e NOGO → NOGO global (downgrade)

---

## 7. Tracking review archivé

Format `LOGS/reviews/REVIEW_BOT3V2_{module}_{agent}_{date}.json` :

```json
{
  "trace_id": "REVIEW_BOT3V2_narrative_state_machine_market-analyst_20260520",
  "module": "narrative_state_machine",
  "agent": "market-analyst",
  "agent_mode": "ultrathink",
  "phase": "Phase 1",
  "books_loaded": [
    "Dalton Mind over Markets Ch 4-8",
    "Wyckoff Phases A-E",
    "ICT Smart Money Concepts BOS/CHoCH"
  ],
  "modules_referenced": [
    "CORE/regime_engine.py",
    "CORE/game_changers.py",
    "CORE/sessions_swings_lag_streaming.py",
    "CORE/bot3_breakout_retest.py (pattern mirror)"
  ],
  "rules_consulted": [
    ".claude/rules/critical-tasks-review.md",
    ".claude/rules/module-review-protocol.md",
    "feedback_pattern11_repetition_avoided.md"
  ],
  "empirical_tests": {
    "parquet_30j_ES": {"pass": 7, "fail": 1, "details": "..."},
    "replay_15_05": {"states_detected": [...], "coherence_pct": 85},
    "stress_kill9_recovery": "PASS",
    "latency_ms_per_bar": 4.2
  },
  "verdict": {
    "scores": {"methodologie": 4.5, "code_quality": 4.0, "empirique": 3.5, "trading_sense": 4.5},
    "global": 4.13,
    "decision": "GO-AVEC-RESERVES"
  },
  "findings": [
    "BOS detection missing edge case for gap opens",
    "State PRE_OPEN_NEUTRAL transition rules need 2nd check"
  ],
  "memory_feedback_created": "feedback_bot3v2_nsm_dalton_alignment.md",
  "next_actions": [
    "Fix BOS gap opens edge case",
    "Add unit test for PRE_OPEN_NEUTRAL"
  ]
}
```

---

## 8. Memory feedback auto-créé après review

Format `.claude/memory/feedback_bot3v2_{module}_{insight}.md` :

```yaml
---
name: feedback-bot3v2-{module}-{insight}
description: {one-line insight from review}
metadata:
  type: feedback
---

{Insight content with body structure :
- Lead with the rule/learning
- **Why:** {reason from review}
- **How to apply:** {when/where this guidance kicks in}}

Cross-reference :
- Review verdict : LOGS/reviews/REVIEW_BOT3V2_{module}_*.json
- Module : CORE/{module_path}
- Phase : {phase_name}
```

---

## 9. État de Phase 3c live (deployée 18/05 03:30 ET)

Phase 3c-A/B/C deployée et active. Bot 3 a maintenant accès aux 32 features Phase 3c via payload live_enriched (465 cols vs 431 avant) :
- Phase 3c-A (17) : bar wicks, bar_no_trade, position_in_range, dist_1d_max/min_ticks, sess_range_atr, delta_day, 7 keys regime
- Phase 3c-B (8) : 4 edge_zones (Bot 2 V6), 4 color_clusters (Bot 3)
- Phase 3c-C (8) : atr_regime_zscore_60d, dist_naked_poc_nearest_pct, is_roll_day, days_since_roll, roll_phase, cvd_5d_rolling_ffd, cur_va_n_buckets, cur_va_total_vol

**CRITIQUE** : `bot3_context_analyzer.py:97` lit ANCIEN nom `cvd_5d_rolling` au lieu de `cvd_5d_rolling_ffd` (ghost feature à fix Phase 1).

---

## Référence rapide invocation agent

Quand Claude dispatch un agent review module :
1. Charger ce KB en contexte agent
2. Pointer vers livres+chapitres pertinents (section 1)
3. Pointer vers modules MIA à grep (section 2)
4. Charger rules + memories (section 3)
5. Définir tests empiriques (section 4)
6. Demander verdict 4 dim (section 5)
7. Si Tier 1 : cross-check 2e agent (section 6)
8. Archiver verdict JSON (section 7)
9. Créer memory feedback (section 8)
