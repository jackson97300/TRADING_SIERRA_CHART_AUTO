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
