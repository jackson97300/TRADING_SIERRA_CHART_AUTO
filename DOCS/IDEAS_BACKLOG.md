# IDEAS BACKLOG — Mode mentor proactif

**Usage** : Tracker les idées proactives proposées et patterns observés.

Format : `- [date] {idea_short} | {effort} | {impact} | {status}`
Status : `PROPOSED / IN_PROGRESS / DONE / REJECTED / WAITING_DATA`

## Idées en cours / proposées

- **[DETTE 2026-05-15]** **Hardcode OVN/Opens 18:00/09:30 ET dans `phase_b_plus_streaming.py` casse MGC** | 1h | LOW | PROPOSED (MGC pas Bot 2/3 actuel)
  - **Source** : Code-reviewer Pass 4c-prereq audit (commit c1475b0) ligne 343-352, 346 - hardcode `mins_et >= 1080 OR < 570` correct ES/NQ mais FAUX MGC (devrait `>= 1140 OR < 510` per `SESSION_BOUNDARIES_BY_SYMBOL["MGC"]`).
  - **Impact** : features `ovn_high/low MGC` polluees si on integre MGC live.
  - **Fix** : utiliser `bounds["asia_start"]` per-symbole comme dans `add_session_metadata_streaming`. Refactor session boundaries au lieu de hardcode.
  - **Deadline** : AVANT Bot 3 MGC live (cf `project_bot1_bot2_mgc_plan_blockers`).

- **[DETTE 2026-05-15]** **Redondance schema payload Pass 3a + Pass 4c-prereq (3 paires duplicate)** | 0.5h | LOW | PROPOSED (bloat sans bug)
  - **Source** : Code-reviewer Pass 4c-prereq concern #2 - paires duplicate dans payload : `mins_et` (Pass 3a + Pass 4c), `session_date` vs `session_date_trading`, `is_in_us_cash` vs `is_cash_session`.
  - **Impact** : bloat schema ~3 cles + risque drift si convention diverge future.
  - **Fix** : soit (a) consolider Pass 4c-prereq pour ne PAS produire les cles deja produites par Pass 3a, soit (b) renommer Pass 4c outputs avec prefix unique. Documenter convention.

- **[DETTE 2026-05-14]** **Test empirique cross-session boundary CME 22:00 UTC (Pass 3b)** | 1-2h | LOW | PROPOSED (couverture test incomplete)
  - **Source** : Code-reviewer Pass 3b R2 B4 - test actuel `test_live_enricher_integration.py` valide 30 bars d'1 plage horaire continue. Manque la validation du reset `trading_date` + `daily_high_running` au cross-CME boundary (18:00 ET = 22:00 UTC).
  - **Impact** : si bug `same_session` (ligne 1010 `rolling_features_streaming.py`), divergences delta_div seraient calculees a tort cross-day. Non detecte par test actuel.
  - **Fix** : ajouter test 2 jours consecutifs avec bar 21:59 UTC + 22:00 UTC. Verifier `trading_date` change + reset state.

- **[DETTE 2026-05-14]** **Audit complet inputs payload vs attentes engines streaming** | 3-4h | HIGH | PROPOSED (Pattern 11 V1 prevent)
  - **Source** : Code-reviewer Pass 3b R2 B5 - revele 20+ inputs amont manquants pour rolling_features (vwap_slope_10, cvd_day, va_position_pct, ib_position_pct, dist_vwap_d, atr, vwap_d_side, vix_regime, bn_absorb_*, retest_*, dist_swing_*, dist_blind_*, dist_cur_va*, dist_ib_*, large_trader_ratio, dist_mq_*, next_wall_dist_ticks).
  - **Impact** : nombreuses features ML potentiellement biaisees/mortes silencieusement. Pattern V1 26 jours features mortes.
  - **Fix** : audit systematique de chaque engine streaming dans `live_enricher.py` :
    - Pour chaque sub-engine, lister inputs attendus (grep `out.get`)
    - Verifier presence dans payload AVANT appel
    - Si absent : injecter (Databento source) OU documenter (phase_b_plus non integre) OU fail-loud (anti silent fallback)
  - **Engines a integrer en amont** : `phase_b_plus_streaming` (74 VWAP) + `phase_b_helpers.add_session_high_low_streaming` + `add_volume_profile_features_streaming`. Sans, ~30% des ctx_* features = NaN/biais.
  - **Deadline** : AVANT training reel mid-juin 2026.

- **[DETTE 2026-05-14]** **Bug data quality : trades Databento manquants 04-27 + 04-30 ES** | INVESTIGATE | MEDIUM | PROPOSED (impact 2/23 sessions ES April UNKNOWN)
  - **Source** : Audit V4 Round 2 code-reviewer (commit Fix v2 game_changers) - revele apres Fix v2 propage proprement les defauts data.
  - **Impact** : 2 sessions ES April 2026 (04-27 lundi, 04-30 jeudi) ont `prev_vah/val/vpoc = NaN` car `daily_profiles` ne contient pas ces dates -> trades manquants dans le buffer Databento.
  - **Verification** : `ls DATA/DATABENTO/GLBX.MDP3/trades/symbol=ES.c.0/year=2026/month=4/day=27/` + idem day=30. Si absent -> retelecharger Databento.
  - **Note** : 04-03 (Good Friday NYSE ferme) + 05-01 (cross-month partial) sont UNKNOWN LEGITIMES. Total UNKNOWN April ES = 4/23 (17%), dont 2 legitimes + 2 data quality.
  - **Deadline** : AVANT training reel mid-juin 2026 (15-17% UNKNOWN biaiserait le modele).

- **[DETTE 2026-05-14]** **Root fix `add_open_cash_price1030` merge par session_date_trading** | 1-2h | LOW | PROPOSED (Fix v2 contourne en aval)
  - **Source** : Audit V4 Round 2 - Fix #1 v2 corrige le bug J-1 shift au point de CONSOMMATION (filter `date_et == session_date_trading`), MAIS la SOURCE du bug (`phase_b_helpers.py:761`) merge toujours `open_cash` / `price_1030` par `date_et`.
  - **Impact** : si un autre consommateur downstream (dashboard, autre engine) lit `open_cash` directement, il aura encore le shift J-1.
  - **Verification** : `grep -rn "open_cash\|price_1030" CORE/ DASHBOARD/` pour identifier consommateurs.
  - **Fix** : refactor `add_open_cash_price1030` pour merger par `session_date_trading` au lieu de `date_et`. Tester non-regression toutes consumers.
  - **Mitigation actuelle** : test regression `TOOLS/test_phase_b_open_type_no_j1_shift.py` detecte la reintroduction du bug.

- **[DETTE 2026-05-14]** **Cross-asset MGC live : tracker 6E/ZN/ZB dans SYMBOLS Live Enricher** | 3-4h | MEDIUM | PROPOSED (gold_phase_d features = NaN sans cross-asset live)
  - **Source** : Live Enricher Pass 2 commit d964762 - `gold_phase_d_streaming` necessite close 6E/ZN/ZB pour `im_dxy_corr_60d` et `im_real_yields_proxy`. Actuellement passe None -> features NaN en live MGC.
  - **Impact** : 2 features Gold (sur 4) = NaN systematique en LIVE pour MGC. Backfill V4 ok (parquets Databento dispo). Mais ML training avec NaN systematique = info perdue pour le modele.
  - **Fix** : ajouter "6E.c.0", "ZN.c.0", "ZB.c.0" a `SYMBOLS` (CORE/live_enricher.py:66) + lecture cache live (databento_live_stream.py supporte ces symbols). Cycle MGC : `cross_asset_closes = {"6E": _states["6E.c.0"].last_bar()["close"], ...}` + pass to add_gold_phase_d_streaming.
  - **Cost** : 3 streams Databento supplementaires (deja inclus subscription Databento).
  - **Deadline** : AVANT training reel MGC mid-juin 2026.

- **[DETTE 2026-05-14]** **Consumer downstream pour marker `phase_b_plus_plus_partial`** | 1-2h | MEDIUM | PROPOSED (bloquant Pass 2 Live Enricher integration)
  - **Source** : code-reviewer round 3 Live Enricher (commit af17446) - marker `phase_b_plus_plus_partial = True` ajoute au payload en cas de crash mid-chain LOT 1-6, mais **aucun consommateur downstream ne le filtre**.
  - **Impact** : bars partielles passent au dataset V4 comme bars completes (features phase_b_plus_plus = defaults/NaN). NaN handling LightGBM gere mais biais si frequence elevee.
  - **Fix** : ajouter filtre dans `build_dataset_v4_phase_b.py` (ou equivalent) : `df = df[df.get("phase_b_plus_plus_partial", False) != True]`. Logger count filtre pour monitoring.
  - **Alternative** : ne PAS supprimer mais flag dans col booleene pour LightGBM (sample_weight = 0.5 si partial).
  - **Deadline** : AVANT training reel mid-juin 2026.

- **[PRIORITE 2 — Jackson 2026-05-13]** **Feature `bn_state` machine d'etat (Battle Navale haussiere/baissiere/neutre)** | 4-6h dev + agent review | HIGH | PROPOSED (concept valide Jackson "OK")
  - **Concept** : detection automatique etat BN base sur theorie Dow + paliers franchis. Reference screenshot ancien Jackson 10 niveaux escalier ascendant.
  - **6 etats** : `BN_HAUSSIER_ACTIF` / `BN_HAUSSIER_PAUSE` / `BN_BAISSIER_ACTIF` / `BN_BAISSIER_PAUSE` / `NEUTRE` / `BN_INVALIDATION`
  - **4 nouvelles cols V4** : `bn_state`, `bn_paliers_count`, `bn_recharge_zone`, `bn_last_pivot_ts`, `bn_distance_from_start_ticks`
  - **Logique** : detection pivots (3 swing highs/lows alignes) -> START -> tracking sequence HH/HL + franchissements niveaux structurels (Wall_0DTE, BL_5, GEX_3) + Long_Up/Dn_Bar validation + invalidation si close < previous_swing_low.
  - **Implementation** : nouveau module `CORE/bn_state_engine.py` + integration `build_dataset_v4_phase_b.py` + widget dashboard "BN State" dans Indicateurs Trading Manuel.
  - **Sequencing** : APRES Phase 1 pipeline V4 incremental + Phase 2 OFA enrichissement (priorite 1).

- **[REJECTED EMPIRIQUE 2026-05-13]** **Pipeline V4 incremental window-based** | tente 4h | TRES HIGH | REJECTED
  - **Probleme initial** : pipeline V4 lag 30-48min -> dashboard OFA tombe en mode degrade DMP-seul -> features V4 absentes.
  - **Tentative 1 (window 3j seul, 25x speedup)** : 188 cols cumulatives divergent vs full mode (atr_regime_zscore_60d, asia_*, swings, day_type, ctx_*_rolling). Window 3j INSUFFISANT car certaines features lookback 60j+. **NOGO ZERO regression.**
  - **Tentative 2 (window 3j + context 60j)** : ZERO regression theorique MAIS pipeline 1074s vs 309s full = **3.5x PLUS LENT**. Cause : Phase B+++ (bottleneck) traite 21M trades sur 63j vs 10M sur 30j. **NOGO performance.**
  - **Conclusion empirique** : refacto window-based mathematiquement impossible a concilier avec ZERO regression sans degrader perf. Le pipeline V4 a un cout fixe trades-based qu'on ne peut pas reduire sans casser features rolling longues.
  - **Mitigation deja deployee (Phase 1c)** : `_V4_STALE_SEC = 600 -> 2700` accepte lag 45min -> dashboard ES OFA marche. Lag Databento Historical 15-30min reste structurel inherent.
  - **Code conserve** : commit 1d92eb9 `apply_all_engines` extraction (code cleaner, ZERO regression idempotence prouvee 1 mois bit-for-bit). Helpers `load_trades_for_window` + `compute_window_cutoff` + `process_partition_incremental` restent dans le code mais NON ACTIVES en prod.
  - **A archiver** : DOCS/plans/2026-05-13-phase-1b-pipeline-v4-incremental.md (plan ecrit, rejet documente ici).

- **[BACKLOG futur]** **Enrichissement Order Flow Avancé dashboard** | 2h | HIGH | PROPOSED
  - Independent du pipeline V4 lag. Ajouter widgets : clusters volumique, bid/ask imbalance par bar, absorption velocity, big_orders momentum sliding 5 bars.
  - Tous deja calcules V4 enriched, juste exposer dans `build_order_flow_advanced` + frontend.
  - Activable une fois pipeline V4 stable (Phase 1c deja deployee = OK pour ES).

- [2026-05-12 02:30 UTC investigation V4 enriched] **6 features V4 enriched cassées 100% NaN** | 4-6h fix + audit Bot 3 | HIGH | PROPOSED — Découverte lors investigation veto swing_proximity (Jackson "investigue 100% NaN"). Colonnes EXISTENT dans schema parquet mais 100% NaN sur 9716 barres NQ mai 2026 :
  - `range_pos` — REDONDANT (alternative OK : `pct_in_range` 0% NaN, `position_in_range` 0.7% NaN). Drop col residuelle du schema.
  - `profile_shape` — calculé par `apply_game_changers` PHASE_B → ne tourne pas / sauvegarde rate
  - `trend_day_probability` — idem `apply_game_changers`
  - `bars_in_va` — calculé par `market_profile_engine` PHASE_B → idem
  - `cvd_day_dir` — calculé par `delta_engine` ou cumulative → idem
  - `dist_mq_call_0dte` — MenthorQ levels lookup → levels pas attachés correctement
  
  **Cause probable** : commit `de1d843` (10/05) "Chantier 5bis3 P1 Regime engine call order Phase A->B" + fix `apply_game_changers iloc[0]->post_ib row` = régression silencieuse sur engines PHASE_B (jamais détectée car Bot 1/Bot 2 V6 lisent Sierra DMP qui calcule ces features OK).
  
  **Impact actuel** :
  - Bot 1 + Bot 2 V6 : AUCUN (utilisent Sierra DMP, features OK)
  - Bot 3 (Databento V4 enriched) : POTENTIEL gates silencieusement neutralisés. Si `setup_engine.py` lit `profile_shape`, `trend_day_probability`, `bars_in_va`, `cvd_day_dir`, `dist_mq_call_0dte` → gates skip avec None.
  
  **Action** : (1) Grep `CORE/setup_engine.py` pour identifier quelles features cassées Bot 3 essaye d'utiliser (silent skip). (2) Reproduire localement le PHASE_B et debug pourquoi `apply_game_changers` ne calcule pas. (3) Refixer + tests parité bit-for-bit + rebuild V4 enriched 8j (May 2026).

- [2026-05-12 02:00 UTC veto audit] **Veto SHORT bottom range_pos NOGO empirique** | DONE | REJECTED — Audit 35 SHORT trades 8j (05/05→12/05). Veto range_pos<=30 OR dist_swing_low proche aurait fait perdre **-$2499/8j** (88.6% trades bloqués = 25 TP/TRAIL ratés -$2517 vs 6 SL évités +$306 économisés). Bot 1 + Bot 2 V6 tradent SHORT au "bottom" en mode **continuation de trend baissier** (RANGE_POS=0 souvent artefact OVN/early-session, pas vrai bottom). Tracker `SHORT_AT_BOTTOM_OBSERVED` confirmé observe-only justifié. Règle 11/05 Jackson swing_proximity = conceptuellement valide en mean-rev mais NOGO en trend day. **Décision** : NE PAS activer veto. Pattern 11 V1 rechute évitée.

- [2026-05-12 00:38 UTC midnight transient] **Pipeline graceful start day** | 30 min | MEDIUM | PROPOSED — Chaque transition jour UTC (00:00 UTC), Databento Historical API n'a pas encore les bars day=N → CONVERT_TRADES FAIL 5+ iter consécutifs → 28+ DMP_JSONL_STALE alertes transient pendant ~25 min. Solution : `live_pipeline.py` mode "graceful midnight" qui retry avec `partial_end = max(00:30, now-10min)` pendant les 30 premières min UTC, ou suppress emit DMP_JSONL_STALE si current_time < 00:30 UTC (= grâce pour transition). Observé 12/05 00:14-00:34 UTC.

- [2026-05-12 R1 incident] **Rebuild MGC backfill — pas de concurrence pipeline live** | 1h fix scheduler | HIGH | PROPOSED — Mon `.bat` rebuild MGC 14 mois lancé 20:33 UTC le 11/05 a tourné en parallèle du `MIA-LivePipeline` → conflit DuckDB I/O probable (race conditions parquet read/write). Tué à 00:35 UTC. À refaire pendant fenêtre nuit calme : (a) Stop MIA-LivePipeline avant rebuild, (b) Run rebuild MGC, (c) Restart MIA-LivePipeline. OR scheduler dans `live_pipeline_loop.py` qui détecte rebuild MGC en cours et passe en idle mode.

- [2026-05-11 J3 Phase B+R3+market-analyst Gold] **Calibration EDGE_THRESHOLD_PCT MGC + 5 features Gold critiques** | total 6-8h | TRES HIGH J4-pré | PROPOSED
  1. **`im_dxy_corr_60d`** — rolling correlation 60 bars Gold/DXY futures (DX). Litt. pro : -0.45 normal, swing à 0 en stress. **OBLIGATOIRE avant J4 training** : citation market-analyst "modèle ML Gold sans DXY = aveugle à 60% variance directionnelle". DXY pas dans pipeline actuel (`constants.py:233` commentaire "Futur : SI Silver ou DXY ?"). Effort : ajouter DX au databento_download + intermarket_features Gold pair.
  2. **`im_real_yields_proxy`** — ZN/ZB momentum proxy TIPS (Gold inverse-corrélé real yields).
  3. **`im_silver_lead_lag`** — SI/MGC ratio (Silver leads Gold 10-30 min breakouts précieux).
  4. **`mgc_asia_london_overlap_vol`** — 70% volume Gold sur overlap London-NY (14:00-16:00 UTC).
  5. **`mgc_session_break_acceleration`** — 13:30 ET US open Gold re-pricing dollar+yields.
  - Aussi : EDGE_THRESHOLD_PCT["MGC"]=1500 calibré sur avril 2026 stress VIX>30 = fragile cross-regime. Extend R3 script `validate_mgc_edge_threshold.py` pour bucketize par VIX (<15, 15-25, >25). Alerte mensuel hors [0.5%, 5%].

- [2026-05-11 J3 R5 incident] **Recovery `_recover_open_positions()` Bot 1 + Bot 2 V6** | 2h dev + agent review | CRITIQUE | PROPOSED — Bot 1 (`mia_paper_trader.py:399`) + Bot 2 V6 init `self.positions = {}` HARDCODE vide au boot. Aucun reload state.json. Chaque restart en plein trade = orphan position broker garanti. Pattern Bot 3 (`_bot3_recover_open_positions`) à copier. Incident confirmé 11/05 : trade ES Bot 1 17:43:07 perdu post-restart 20:10 (Sim3 broker-side = orphan).

- [2026-05-11 J3 R2] **Backtest dédié Bot 2 V6 timeout (R2b)** | 1h backtest-runner | MEDIUM | PROPOSED — Suite R2 verdict Bot 1 NOGO timeout=30 (-$386 sur 114 trades). Bot 2 V6 = archetype V6 brain enrichi nouveau, à backtester séparément. Si NOGO → revert défense 120 confirmé. Bot 2 V6 actuellement reverted à 120 par défense.

- [2026-05-11 J3] **Anti-bug `tick=tick` pour futurs symboles** | 1.5h | HIGH | PROPOSED
  - Lint guard `tools/check_tick_hardcode.py` étendre : bloquer commit si nouveau symbole sans entries `SYMBOL_TO_TICK_SIZE` + `EDGE_THRESHOLD_PCT` + `BIG_ORDER_TIERS`.
  - Test régression cross-instrument : run dataset_builder sur 1j nouveau symbole + dumper distribution `dist_swing_high_ticks` median + p99. Comparer ratio vs ES (doit être ~tick_ratio_inverse). Si ratio hors [0.5x, 2x] → tick mal propagé. Run avant ajout MNG (tick 0.001) / MCL (tick 0.01) futurs.

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


## Chantier 5bis3 Partie 2 — EdgeZones algorithm refactor (deferred 11/05/2026)

### Cause racine
`edge_zones_engine._detect_stacks_for_bar` cherche cells **adjacentes au tick natif**
(p+tick pour buy, p-tick pour sell). Sur MGC tick=0.10, footprint est SPARSE :
peu de cells consecutives, donc `cells.get(p_above)` retourne None majoritairement
→ `is_imb=False` partout → 0 stacks detectes.

Verification empirique mars 2026 (28k bars MGC) :
- 5903 cellules totales
- Imbalance distribution (quand bid>0 ET ask>=bid) : p50=200%, p95=700%, p99=1000%
- Donc les imbalances EXISTENT, c'est l'algo cells-adjacent qui ne match pas.

### Solution proposee (refactor)
Bucket le footprint MGC en macro-tick (5 ticks = 0.50) AVANT detection adjacence :
- Aggregate ask_vol/bid_vol par bucket macro-tick
- Detect imbalance sur ces buckets densifies
- Tick natif preserve pour autres features qui consomment footprint

Effort : 2-3h (refactor `_detect_stacks_for_bar` + tests + recalibrate seuils MGC).

Variables :
- `EDGE_DETECTION_TICK = {"ES": None, "NQ": None, "MGC": 0.50}` (None = tick natif)
- Modifier `apply_edge_zones` pour passer le macro-tick a `_detect_stacks_for_bar`
- `_detect_stacks_for_bar` fait rebucket interne si macro-tick != tick natif

### Priorite : BASSE
3 features (`bar_edge_buy_fire`, `bar_edge_sell_fire`, `n_edge_*_active`) sont
non-critiques pour BN V2/V3, Bot 3 levels, RuleEngine. Phase 2 backtests
fonctionnent sans.

A faire dans une session dediee aux features Gold edge (avec tests pre/post
recalibrage seuils 600 -> X% adaptatif).


## Phase 2 Backtests MGC — Plan execution (10/05/2026)

### Datasets prets
- ES : `DATA/DATASETS/ES_dataset_v5e_clean.parquet` (357k bars × 469 cols, post-Chantier 5bis3 P1)
- MGC : `DATA/DATASETS/MGC_dataset_v5e_clean.parquet` (rebuild en cours VPS, 336k bars x 405 cols attendu post-Regime fix)

### Strategies a backtester sur MGC

| # | Strategie | Module | Methode |
|---|---|---|---|
| 1 | BN V2 multi-tier signaux | `CORE/bn_engine.py:BNEngine` | Replay sur bars + signaux + simu OCO |
| 2 | BN V3 Dow + Holy Grail | `CORE/bn_v3_engine.py:BNV3Engine` | Idem |
| 3 | RuleEngine 16 regles | `CORE/rule_engine.py:RuleEngine` | Score >threshold = signal |
| 4 | Bot 3 levels Sidak | `CORE/bot3_*` | 13 niveaux heritage + 4 Sidak + 3 COMBOS_BOOSTED |

### Garde-fous methodologiques OBLIGATOIRES (cf incident 28/04 DATA_MINING_TRAP)

1. **Walk-forward 12 folds** Lopez-compliant (1 mois test / 11 mois train rolling)
2. **DSR** via `CORE/dsr_calculator.py` (Bailey-Lopez 2012, Pearson kurtosis)
3. **n_trades ≥ 100** par strategie par fold
4. **Concentration ≤ 33%** : pas plus d'un tiers du PnL sur un seul setup/level
5. **Costs MGC inclus** : slippage entry ~1 tick ($0.10) + commission Topstep ~$0.85 RT
6. **Pre-RTH filter** : option ON (RTH gold 08:30-13:30 ET only) vs option OFF (24h trading)
7. **Verdict ml-trainer agent** : GO/RESERVES/NOGO avant tout deploiement

### Sequencement

**Etape 1** : verifier MGC dataset post-rebuild (regime_* revived)
**Etape 2** : backtest BN V2 sur ES + MGC (comparaison cross-instrument)
**Etape 3** : backtest BN V3 idem
**Etape 4** : backtest RuleEngine idem
**Etape 5** : backtest Bot 3 levels
**Etape 6** : verdict ml-trainer + recommandation strategie optimale MGC
**Etape 7** : recalibration seuils MGC empirique (Chantier 2+3)
**Etape 8** : paper trading MGC (Chantier 6)

### Effort estime
- Etapes 1-5 : ~10-15h compute + dev (12 folds × 4 strategies × 2 instruments)
- Etape 6 ml-trainer review : 30 min
- Etapes 7-8 : variable selon resultats

