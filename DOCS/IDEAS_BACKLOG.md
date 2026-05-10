# IDEAS BACKLOG — Mode mentor proactif

**Usage** : Tracker les idées proactives proposées et patterns observés.

Format : `- [date] {idea_short} | {effort} | {impact} | {status}`
Status : `PROPOSED / IN_PROGRESS / DONE / REJECTED / WAITING_DATA`

## Idées en cours / proposées

- [2026-05-02 09:15] **PATCH R4 deploye Bot 2 Sim2** | DEPLOYED | HIGH | reviews 2 rounds code-reviewer ULTRATHINK GO + market-analyst PATCH SAFE pour trading lundi. Actions follow-up market-analyst :
  - [2026-05-02] Widget dashboard `slip_entry_ticks` mediane/p95/distribution rolling 20 trades | 30 min UI | MEDIUM | PROPOSED
  - [2026-05-02] Recalculer PF/Sharpe historiques avec slip_entry estime — quantifier gap paper/backtest | 1h script | HIGH | PROPOSED — peut expliquer sub-PF 7 semaines
  - [2026-05-02 J+7] Audit alerte automatique : si `mediane(slip)==0 AND N>=20` → INCIDENT_LOG VALIDATION_MISS instrumentation ratee | check lundi+vendredi | HIGH | PENDING
  - [2026-05-04 lundi 14:00 UTC] Grep `PARENT_FILL_RECORDED LOGS/execution/execution_20260504_*.jsonl | wc -l` ≥ nb_trades_jour, verifier distribution slip plausible (mediane 0.5-2.0t Sim2) | PENDING J+1
  - [2026-05-02] V5 train ML weekend : inclure cost_model slip_ticks_median=1.5 dans backtest pour calibrer expectations prod | HIGH | À AJOUTER GATE 17h methodology
- [2026-05-02 01:50] **BLOCKER V5 — Leak mq_* pre-2026 dataset_builder.py:516** | RESOLU MATIN | finding empirique = pas de leak en V4 actuel (NaN preserved 100%). Guard fail-loud + assertion samedi appliques. Cf DOCS/BLOCKER_MQ_LEAK_PRE2026.md.
- [2026-05-02 01:30] GATE 17h methodologie v2 post-review ml-trainer | doc fait | HIGH | DONE — 9 corrections patchees (DSR formule + n_trials 120/240 + hold-out 12 mois 4 trimestres + Patch R4 samedi matin + decision tree mix GO/NO-GO + apple-to-apple ES/NQ). 4 reserves restantes (dsr_calculator code + sensitivity table fat tails). Cf DOCS/GATE_17H_METHODOLOGY.md + DOCS/V5_GATE_17H_RESULTS.md.template.
- [2026-05-02 01:15] Smoke test MQ × 3 TF + CAT4 × 3 TF sur ES+NQ 2026-04-28 | 15 min | PASS partiel | dist_mq_*_pct_TF count=0 NaN propage (level_col absent), add_im_features_per_tf retourne 0 cols (import intermarket_features rate silent). À fix samedi 9h.
- [2026-05-02] **🏆 LE GRAAL — Live HTF Enrichment Pipeline** | 1-2j dev | TRES HIGH | DOCUMENTÉ — auto-update 1m/5m/15m/1h enrichis incrementalement depuis bars live, latence <60s, supprime hack LIVE override + Fix C v2. Cf DOCS/PLAN_LIVE_HTF_ENRICHMENT_GRAAL.md. Implementer post week-end ML.
- [2026-05-02] PATCH R4 parent fill tracking Bot 2 | 30min code + 1h tests + review | HIGH | DOCUMENTÉ — `_on_dtc_fill` ne traite que TP/SL/close, fill PARENT ignoré, pos["entry"]=signal_price (jamais fill_price reel). Cf DOCS/PATCH_R4_PARENT_FILL_TRACKING.md. Deploy samedi avec review agent.
- [2026-05-02] Conversion DBN→parquet 04-29/04-30 FAIT (gap V4 fix partiel) | 5min | resolved


- [2026-05-01] Multi-timeframe alignment (EMA 5m slope filter pour 1m signal) | 1-2h | HIGH | IN_PROGRESS — Jackson valide, peut résoudre problème pullback
- [2026-05-01] Volume surge climax detector (rvol>=3 → flag CLIMAX_REVERSAL) | 1h | MEDIUM | IN_PROGRESS — observe-only initial
- [2026-05-01] Auto-rebuild pipeline V4 sur gap detection | 2-3h | MEDIUM | PROPOSED — bug 04-29/04-30 silencieux
- [2026-05-01] Topstep risk dashboard widget (-$X / -$1000 limit + trail) | 1-2h | HIGH | PROPOSED — risque opérationnel
- [2026-05-01] Time-of-day analysis (WR par heure UTC) | 30min | MEDIUM | PROPOSED — quick win sur 81 trades
- [2026-05-01] Reversal indicator composite (bear/bull score) observe-only logger | 1h | MEDIUM | PROPOSED — N=38 insuffisant, capturer 100+ trades
- [2026-05-01] Pullback entry feature (P25 MAE NQ=5t) | 4-6h | LOW | REJECTED — backtest -$111 net (TP manqués > bonus)
- [2026-05-01] Refactor pipeline V4 incremental (vs retraitement mois entier) | 2-3h | MEDIUM | PROPOSED — pipeline_incremental memory

## Patterns observés (à investiguer)

- [2026-05-01] WR Bot 2 = 23% sur 7j (-$2041 PnL) | breakeven RR=1.31 nécessite WR=43% → besoin meilleur filtre entrée
- [2026-05-01] RR > 2 = 0% TP atteint (12/12 SL) → cap RR=2.0 deployé, observer impact
- [2026-05-01] SL>budget 107 rejets/jour SHORTs → SL_BUDGET 75→120 deployé
- [2026-05-01] LONG TP a bullish_score median 8 vs SL median 5 → bull>=9 = WR 60% sur N=5 (insuffisant)
- [2026-05-01] SHORT bearish_score élevé (≥7) = signal CONTRARIEN → veto SHORT possible (N=11 insuffisant)
- [2026-05-01] Data gap pipeline V4 04-29/04-30 silencieux → besoin gap detection auto
- [2026-05-01] Bug architectural _order_to_symbol race → entry_price = signal_price pas fill_price (Option 4/5 callback à coder)

## Risques opérationnels flaggés

- [2026-05-01] Topstep daily limit -$1000 : pas d'alerte bot quand approche → besoin widget dashboard urgent
- [2026-05-01] Snapshots ML pollués par signal_price (R5 race fix) → biais Lopez meta-labeling
- [2026-05-01] Recovery boot persiste signal_price (R6) → biais permanent au reboot
- [2026-05-01] Bot 1 21/27 SL "no data" parquet → bars Sierra Sim3 ≠ Databento → pas de backtest possible Bot 1

## Decisions / verdicts

- [2026-05-01] Cap RR=2.0 : DEPLOY (backtest +$210 Bot 2 7j)
- [2026-05-01] SL Budget 75→120 : DEPLOY (107 rejets observés, calcul Topstep OK)
- [2026-05-01] Pullback entry : REJECT pour deploy (backtest -$111 net, mais limites méthodologiques)
- [2026-05-01] Reversal indicator : OBSERVE-ONLY 100+ trades futurs avant deploy

## Dette technique MGC — Chantier 1 tick_size centralise (2026-05-10)

### Contexte
Chantier 1 a centralise `get_tick_size(symbol)` dans 11 modules pipeline V4
actifs (build_dataset_v4_*, phase_b_*, rolling_features, sessions_swings,
edge_zones, value_area_running, footprint_builder, game_changers,
market_profile_rolling, phase_d_dalton_levels). Pipeline ES+NQ valide
end-to-end (test 2026-04-01 : 1380 bars × 90 cols, pas de regression).

### Dette residuelle (47 fichiers hors scope MGC actuel)
Audit code-reviewer 2026-05-10 a identifie ~47 fichiers avec `TICK_SIZE = 0.25`
hardcode dans des modules **hors pipeline V4 actif** :

**A migrer SI Bot 1/2/3 etendus a MGC live** (Chantier 6) :
- `CORE/mia_paper_trader.py` (Bot 1)
- `CORE/databento_paper_trader.py`, `databento_paper_trader_v2.py` (Bot 2/3)
- `CORE/dataset_builder.py` (legacy v1/v2)

**A migrer SI utilises pour MGC backtests/research** :
- `CORE/research/*.py` (~30 scripts audit)
- `CORE/backtest_*.py` (3 scripts)
- `CORE/audit_*.py` (~10 scripts)

**Fichiers dette annexe** :
- `CORE/intermarket_features.py` : ES↔NQ pair fixe, refactor pour MGC en
  Chantier 5 (option A skip / B paire MGC↔DXY)
- `CORE/build_dataset_v4_phase_b.py:386-392` : `apply_intermarket_pair`
  utilise TICK_SIZE=0.25 OK pour ES/NQ pair, refactor MGC en Chantier 5
- 16 callers `RollingFeatures()` sans symbol (warn emis a chaque appel)
  - `bot_main.py:149` migre 10/05 a `RollingFeatures(symbol="ES")` (1 inst shared ES+NQ)
  - 15 autres (dataset_builder, mia_sim, mia_bench, test_all, pattern_discovery,
    backtest_strategies, backtest_chantiers, backtest_div) : warning OK car
    ces scripts traitent ES/NQ en mono-instrument hardcode

### Action
Aucune action immediate. Documente pour pas oublier au moment du Chantier 6
(paper traders MGC) et Chantier 5 (intermarket MGC).


## Plan migration long terme dette TICK_SIZE (10/05/2026)

### Solution preventive deployee
1. **Lint guard** : `tools/check_tick_hardcode.py` scan automatique
2. **Rule** : `.claude/rules/tick-size-policy.md` documente patterns interdits/acceptes
3. **Pre-commit hook** (optionnel) : `python tools/check_tick_hardcode.py --strict`

### Categorisation 107 violations residuelles

**Tier A - BOT LIVE (critique 5 modules)** — A migrer AVANT extension MGC live :
- `BOT/bot_config.py` (2 violations)
- `BOT/trade_journal.py` (1)
- `CORE/databento_bot.py` (1)
- `CORE/databento_paper_trader.py` (1)
- `CORE/mia_paper_trader.py` (1)

Effort estime : 2.5-4h (5 modules x 30-45 min refactor + tests). **Priorite haute** :
ces modules sont en prod active.

**DEADLINE : 31/05/2026** (3 semaines). Si non migre, documenter retard dans
`DOCS/INCIDENT_LOG.md` categorie SCOPE_CREEP avec raison.

A faire en Chantier 6 (Paper traders state dicts MGC).

**Tier B - PIPELINE LEGACY (8 modules)** — A migrer SI utilises pour dataset MGC :
- `CORE/dataset_builder.py` (2) - V1/V2 legacy
- `CORE/load_mq_levels.py`, `menthorq_backfill_injector.py`, `enrich_dataset_v5_htf.py`
- `CORE/databento_dumper.py`, `ib_recalc.py`, `mia_session_replay.py`, `mia_sim.py`

Effort : 4-6h. **Priorite moyenne** : utilises principalement pour ES/NQ.

**Tier C - RESEARCH/AUDIT (~50 modules)** — Migration optionnelle :
- `CORE/research/*.py` (~30 scripts audits ponctuels)
- `CORE/audit_*.py` (~10)
- `CORE/backtest_*.py`, `CORE/feature_rules_*.py`, `CORE/mia_double_top.py`...

Effort : 8-12h. **Priorite basse** : scripts one-shot, peuvent etre migres
au case-by-case quand reutilises pour MGC.

**Tier D - TESTS/SCRIPTS (~30 modules)** — A juger :
- `BOT/test_dtc_*.py` (test scripts)
- `BOT/audit_*.py`, `BOT/backtest_*.py`
- `CORE/test_*.py`, scripts research/

Souvent OK car testent ES/NQ uniquement. Migration uniquement si besoin MGC.

### Sequencement recommande

| Phase | Quand | Modules | Effort |
|---|---|---|---|
| 1 | Avant Chantier 6 | Tier A (5 bot live) | 2-3h |
| 2 | Quand MGC dataset = priorite | Tier B (8 legacy) | 4-6h |
| 3 | Au cas par cas | Tier C/D (~80) | n/a |

### Garde-fou
Le lint guard `tools/check_tick_hardcode.py` empeche tout NOUVEAU module de
violer. Donc la dette est PLAFONNEE — elle ne peut que diminuer dans le temps.


## Chantier 5bis3 — MGC features residuelles (10/05/2026)

Apres Chantier 5bis2 (fix I/O + seuils MGC empiriques), 2 categories de features
encore mortes pour MGC (causes structurelles, non-bloquant Phase 2 backtests) :

### 1. Edge Zones — 3 features const=0
- `bar_edge_buy_fire`, `bar_edge_sell_fire`
- `n_edge_buy_active`, `n_edge_sell_active`

**Cause** : algorithme `_detect_stacks_for_bar` (edge_zones_engine.py) cherche
cellules ADJACENTES dans le footprint. Sur MGC (tick=0.10), footprint
**sparse** (cells non-adjacentes au tick) → `cells.get(p_above) == None` →
aucun stack detecte → 0 fire.

**Options fix** :
- (A) Bucket prix MGC en "macro-tick" 0.50 (5x tick natif) pour densifier
- (B) Reduire min_group_size de 2 a 1 (single-cell imbalance)
- (C) Reformuler imbalance entre cellules NON-adjacentes (within 2-3 ticks)

Empiriquement, distribution imbalance MGC = p50=200%, p95=700%, p99=1000% donc
imbalances forts existent — c'est l'algo adjacence qui les rate.

### 2. Regime engine — 7 features const=0
- `regime_confidence`, `regime_trend_votes`, `regime_range_votes`
- `regime_actionable`, `regime_mode`, `regime_favor`, `regime_vol`

**Cause** : `compute_regime_dict` appele dans `build_dataset_v4_dmp_databento`
(Phase A, ligne 1019-1028) AVANT que `apply_game_changers` (Phase B) calcule
`open_type/day_type`. Phase A detect `missing_regime != []` → skip + const 0.

Pour ES/NQ, ces colonnes existent en Phase A car DMP les fournit (Sierra Chart
calcule). Pour MGC, DMP n'est pas configure → colonnes absentes Phase A → skip.

**Fix** : deplacer appel `compute_regime_dict` en fin de `build_dataset_v4_phase_b`
APRES `apply_game_changers`. Effort 30 min + test non-regression ES/NQ.

### Effort total Chantier 5bis3 : 1h30
Priorite : faible (non-bloquant Phase 2). A faire avant trading live MGC.

