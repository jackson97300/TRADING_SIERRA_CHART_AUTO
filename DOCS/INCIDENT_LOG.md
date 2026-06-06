# INCIDENT LOG — MIA Trading System

**USAGE** : ce fichier est lu par Claude au DEBUT de chaque session (nouvelle ou continuation apres `/compact`). Chaque incident documente ici doit guider Claude pour eviter sa repetition.

## Protocole de consultation

**AVANT toute action critique** (fix C++, dispatch agent, affirmation existence code/feature, design, deploy) :
1. Grep ce fichier pour la categorie concernee
2. Si match trouve, relire l'entree et appliquer la prevention
3. Si incident nouveau detecte : ajout immediat en haut du fichier (ordre anti-chronologique)

**Categories autorisees** :
- `CONTEXT_MISS` — non-consultation d'info disponible (memoire, rule, code existant)
- `PATTERN_11` — logique hardcoded au lieu de laisser ML apprendre (V1 reborn)
- `AGENT_MISUSE` — mauvais agent pour la tache OU agent non consulte quand requis
- `OVER_ENGINEERING` — solution trop complexe pour le probleme
- `VALIDATION_MISS` — affirmer sans preuve empirique
- `COMMENT_FALSE` — commentaire/doc dit X alors que realite = Y
- `SCOPE_CREEP` — depassement perimetre demande
- `DEPLOY_UNSAFE` — deploy sans confirmation/validation
- `LAZY_DELEGATION` — saute STEP 1-3 d'analyse manuelle, delegue tout aux agents (cf `.claude/rules/module-review-protocol.md`)
- `DATA_MINING_TRAP` — audit one-shot qui produit "edges" sans walk-forward + DSR Lopez = noise habille en signal (haircut multiple testing manquant)

## Regles de maintenance

1. **JAMAIS supprimer** une entree (meme ancienne/resolue)
2. **Ordre anti-chronologique** : dernier incident en haut
3. **Une entree = 10 lignes max** (sinon linker vers fichier dedie)
4. **Escalation** : si une categorie atteint 3+ occurrences, promouvoir en memoire dediee auto-chargee
5. **Cross-reference** avec `.claude/rules/lessons.md` + memoires `feedback_*`

---

### 2026-06-06 23:30 (37) - [PATTERN_11 + VALIDATION_MISS] - Convention Side Databento INVERSEE dans 8 modules CORE/ — bug delta_bar pollue Bot 1/2/3 depuis demarrage pipeline

**Categorie** : PATTERN_11 (mapping convention hardcoded contre la realite) + VALIDATION_MISS (jamais teste empiriquement avant deploy)
**Sub-categorie** : ORDERFLOW_CONVENTION_INVERTED

**Contexte** : Sa 06/06 nuit, Jackson observe Bot 1 NQ qui ACHETE pendant chute -1407 pts (05/06 baissier massif). Investigation revele bug critique.

**Bug** : Notre Python interprete `Side.ASK ('A')` comme BUYER aggressor (`delta_bar += size`). Verite officielle (NautilusTrader Rust decoder canonical) :
```rust
'A' => AggressorSide::Seller,   // Side.ASK = SELLER aggressor
'B' => AggressorSide::Buyer,    // Side.BID = BUYER aggressor
```

Convention SAINE (Sierra Chart) : `delta_bar = AskVolume - BidVolume` (ask vol = aggressive BUY).
Convention OPPOSEE (Databento expose Side dans le sens BOOK SIDE aggressee).

**Empirique 5 jours baissiers NQ** (20260519, 27, 0603, 0604, 0605) :
- Sierra `delta_bar` sum : NEGATIF (coherent marche baissier)
- Databento `delta_bar` sum : POSITIF (inverse)
- Ranges miroirs ([-799..641] vs [-641..799])

**Impact** :
- Bot 1 V3 NQ + Bot 2 BN V5 + Bot 3 V4 = decisions LIVE inversees depuis demarrage pipeline (plusieurs mois)
- Bot 2 BN V5 +$887/jour recent = gain pur du bug ou strategy reelle ? Strategy-inversion test obligatoire Phase 5.4
- Tous datasets parquet v4 (`build_dataset_v4_dmp_databento.py:619-627`) = `buy_vol`/`sell_vol`/`delta_bar` INVERSES → modeles LightGBM polluees
- Tous backtests bot 1/2/3 = thresholds calibres sur features inversees

**Sites du bug (8 modules)** :
- `databento_dumper.py:115,118`
- `enricher_chain.py:321,323`
- `footprint_builder.py:127,129`
- `footprint_builder_streaming.py:74,76`
- `phase_b_plus_plus_trades_streaming.py:219`
- `live_enricher_v_pre_refactor.py:494,496`
- `build_dataset_v4_dmp_databento.py:619-627` (SQL)
- `research/calibrate_mgc_thresholds_batch.py:48,50`

**Cause racine** : commentaire faux dans `databento_dumper.py:76` ("side='A' (ASK) → buy") replique par copier-coller dans 7 autres modules sans verification empirique de la convention Databento officielle.

**Lecon** :
1. **Toute convention orderflow doit etre verifiee EMPIRIQUEMENT sur N jours directionnels** (5 jours baissiers + 5 haussiers, convergence > 60%) AVANT deploy
2. **Cross-check avec source canonique** (NautilusTrader decoder, docs vendor officielles) PAS un commentaire "evident"
3. **Sanity check signe sur jours connus** : marche baissier ⇒ delta_day attendu negatif. Sinon = bug mapping
4. **PATTERN_11 detecte** : 8 modules avec meme bug par copier-coller du commentaire faux source

**Trigger prevention** :
- AVANT tout deploy d'une convention orderflow (delta, imbalance, aggressor) : lancer `tools/check_feature_sign.py` (Phase 5 design migration Sierra)
- AVANT commit d'un module qui consume `side`, `aggressor`, `orderflow_direction` : grep tous les sites + test empirique 5 jours directionnels
- AVANT confiance dans un dataset ML : sanity check delta_day sign sur 5 jours baissiers connus

**Resolution** : migration full Sierra Chart (eliminer pipeline Databento entierement). Sierra = convention saine (AskVolume = aggressive BUY natif). Code Databento devient mort et est archive Phase 7.2. Design doc complet `DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md`. Plan agent verdict RESERVES MAJEURES 5/10, corrections appliquees dans todo (85 items).

**Reviewed** : Plan agent (RESERVES MAJEURES), code-reviewer (pending Phase 1.5), schema-auditor (pending Phase 0.7bis)

---

### 2026-06-04 09:30 (36) - [CONTEXT_MISS] - ENV BN V5 propage seulement sur paper_v2 — Dashboard service oublie cause Bot 2 BN V4 affiche en boucle

**Categorie** : CONTEXT_MISS (deuxieme cas deprecation BN V4->V5 en 24h)
**Sub-categorie** : DEPLOY_INCOMPLETE_MULTI_SERVICE

**Contexte** : Hier 03/06 22:00 deploy dashboard Bot 2 BN V5 :
- `DASHBOARD/api/paper_tracker.py` : ajout `get_bn_v5_payload()` + routage `MIA_BN_V5_ENABLED=1`
- `DASHBOARD/static/js/dashboard.js` : detection bot_label "Bot 2 BN V5"
- `DASHBOARD/static/index.html` : cache bust v153
- SCP + restart MIA-Dashboard fait
- Test local fonction OK

Mais ENV `MIA_BN_V5_ENABLED=1` propagee SEULEMENT sur service `MIA-DataBento-Paper-V2`. **Service `MIA-Dashboard` NSSM AppEnvironmentExtra avait encore `MIA_BN_V4_ENABLED=1` (ancien) ET PAS `MIA_BN_V5_ENABLED`**.

Resultat 04/06 09:24 UTC Jackson voit le dashboard :
- "Bot 2 BN V4 — Bataille Navale (Sim2)" (au lieu de BN V5)
- "STATE FROZEN age=?min (paper_trader freeze)"
- "Aucun setup BN V4 collecte"

Branche code `elif MIA_BN_V4_ENABLED=1 → get_bn_v4_payload()` activee → lit `LOGS/bn_v4/` (vide depuis 02/06) → available=False, alive=False → frozen.

**Cause racine** : pas de checklist explicite "deprecation bot X→Y exige propagation ENV sur N services" dans CLAUDE.md ou critical-tasks-review.md. C'est la 2e occurrence en 24h du meme pattern (cf incident #35 BN V4 watchdog non purge → 66 reboots/jour).

**Lecon** : la deprecation d'un bot X via ENV `MIA_<X>_ENABLED=0` doit etre EXHAUSTIVE :
1. Service principal (paper_v2 / paper trader)
2. Service Dashboard (separe, propre ENV)
3. Service Watchdog (separe, code check obsolete)
4. Tous les autres services qui referent X (grep cross-codebase)

**Trigger prevention** : ajouter dans `.claude/rules/critical-tasks-review.md` section deploy :
```bash
# Avant deploy fix deprecation ENV :
ssh VPS "Get-Service MIA-* | ForEach-Object { Write-Host $_.Name; nssm get $_.Name AppEnvironmentExtra }" \
  | grep -E "MIA_<X>_ENABLED|MIA_<Y>_ENABLED"
# Verifier que TOUS les services concernes ont le bon ENV.
```

**Fix applique** (04/06 09:30 UTC) : `nssm set MIA-Dashboard AppEnvironmentExtra ... MIA_BN_V4_ENABLED=0 MIA_BN_V5_ENABLED=1 ...` + `Restart-Service MIA-Dashboard`. PID neuf, ENV correcte. Apres refresh hard browser (Ctrl+Shift+R) Jackson devrait voir Bot 2 BN V5.

**Reviewed** : agent investigation 04/06 (rendu), self.

---

### 2026-06-03 15:23 (35) - [CONTEXT_MISS] - Watchdog Bot2_BN_V4 check obsolete cause 66 reboots/jour paper_v2 + 4 orphelins Bot 3

**Categorie** : CONTEXT_MISS (deprecation BN V4 -> BN V5 23/05 sans purge watchdog)
**Sub-categorie** : INFRA_MONITORING_DRIFT

**Contexte** : BN V4 (`bn_v4_paper`) remplace par BN V5 (`bn_v5_engine`) le 23/05/2026 dans paper_v2 (cf memory `project_bn_v5_engine_20260507`). ENV `MIA_BN_V4_ENABLED=0` mis sur paper_v2 hier soir 02/06 fin RTH. Le fichier de log `LOGS/bn_v4/bn_v4_v1_*.jsonl` n'est plus ecrit depuis 02/06 16:00 UTC.

`BOT/mia_watchdog.py:142-154` contenait un check `Bot2_BN_V4` avec :
- `path_glob: LOGS/bn_v4/bn_v4_v1_*.jsonl`
- `crit_age_s: 1800` (30 min)
- `service: MIA-DataBento-Paper-V2`

Ce check n'a JAMAIS ete mis a jour pour pointer vers BN V5 (ni renomme ni supprime). Resultat 03/06 :
- Age constate `WATCHDOG_SOURCE_CRIT Bot2_BN_V4` = 64-68k secondes
- Watchdog declanche `Restart-Service MIA-DataBento-Paper-V2` toutes les 15-16 min (cap 3/h)
- 66 BOOT_STARTS paper_v2 dans la journee
- 4 positions Bot 3 v4 orphelines (Jackson flatten manuel 11:38:49)
- Process instable cascade BN V5 + Bot 3 V3 + Bot 3 v4

**Cause racine** : checklist post-deprecation manquante. Quand un bot X est remplace par bot Y (23/05 BN V4 -> BN V5), il faut grep tous les composants infra qui referent X :
- `mia_watchdog.py` (check + CME_DATA_DEPENDENT_SOURCES)
- `dashboard` references
- `log_catalog.py` codes log X-specific
- `BOT_CHANGELOG.md` annotations

**Lecon** : la deprecation d'un module ne se limite PAS au code metier. **Le monitoring qui suit le module mort PROVOQUE le bug**, car il restart un service pour ressusciter un fantome.

**Trigger prevention** :
- A chaque deprecation bot (ENV X=0, code remplace), executer mandatoirement :
  ```bash
  grep -rn "<old_bot_name>" BOT/mia_watchdog.py DASHBOARD/ CORE/log_catalog.py
  ```
- Ajouter cette regle dans `.claude/rules/critical-tasks-review.md` section "DEPLOY criteres" : "deprecation = purge infra + monitoring obligatoire"
- Outil futur : `tools/watchdog_dryrun.py` qui valide chaque path_glob produit au moins 1 fichier mtime < crit_age_s quand service tourne. Sinon erreur de config.

**Fix applique** : `BOT/mia_watchdog.py` ligne 141-154 (bloc Bot2_BN_V4 supprime + commentaire 12 lignes explicatif) + ligne 246 ("Bot2_BN_V4" retire de `CME_DATA_DEPENDENT_SOURCES`). Deploy + restart MIA-Watchdog 15:23 UTC. 24 min observation : 0 CRIT / 0 RESTART.

**Reviewed** : agent 3 (diagnostic 128 reboots), code-reviewer (en attente verdict), self (smoke test inline OK).

---

### 2026-06-03 12:45 (34) - [PATTERN_11] - BN V5 cascade F5+F6 ajoutee 02/06 SOIR sans rebacktest (3eme occurrence cycle BN V4->V5)

**Categorie** : PATTERN_11 (3eme occurrence cycle Battle Navale V4->V5)
**Sub-categorie** : DECISION_OVERRIDE (Jackson override 2 reviewers GO-AVEC-RESERVES)

**Contexte** : BN V5 deploy 23/05/2026 paper Sim2. Validation visuelle Jackson + memory `project_bn_v5_engine_20260507` annonce "20/20 tests PASS pre-deploy" mais ces tests etaient unitaires sur fonctions individuelles, pas backtest end-to-end. Le 02/06 SOIR, Jackson ajoute 2 bonus dans `BNV5Params` :
- `require_aggressor_confirm: True` (aggressor_imbalance >= 0.30)
- `require_long_bar_confirm: True` (long_up_bar = 1)
Sans rebacktest 30j post-modification. Resultat empirique 03/06 : 0 trade en 13 jours consecutifs.

**Cause racine** : Pattern 11 V1 reproduit pour la 3eme fois sur cycle BN V4->V5 :
- Empilage filtres cascade (4 hard filters + 2 bonus)
- F5 aggressor >= 0.30 sur bar d'entry V/W = exiger conviction AVANT que retournement se materialise
- F6 long_up_bar = 1 sur bar reversal = idem contradictoire
- Wyckoff Spring se confirme N+1, pas N (cf memory `feedback_range_confirmation_breakout.md`)

Audit cascade empirique (95975 candidats 03/06) :
- F5 aggressor : NQ 125 -> 0 (100% rejection), ES 60 -> 2 (96.67%)
- F6 long_up_bar : idem
- Combine F5+F6 : ZERO setup peut passer mathematiquement

**Impact prod** :
- 0 trade BN V5 en 13 jours consecutifs (20/05 -> 03/06)
- 99K events GATE_*_BLOCK / jour pollution logs MAJEUR
- Vs BN V4 (predecesseur) : 8 trades 26/05-02/06 (~1 trade/jour)
- Coute opportunite : ~13 trades manques sur fenetre exploitable

**Lecon** :
1. Toute modification params cascade DOIT etre testee empiriquement (backtest 30j minimum) AVANT deploy. Memory `feedback_pattern11_repetition_avoided.md` deja escalee 3 occurrences.
2. Ajout bonus en cascade = high-risk Pattern 11. Preferer scoring composite (cf `feedback_lightgbm_no_composite_indicators.md`).
3. Le "20/20 tests PASS pre-deploy" non documente = NON suffisant. Tests unitaires != validation end-to-end.

**Trigger prevention** : avant toute modification `BNV5Params` ou cascade filtres :
1. Backtest 30j live_enriched sur params actuels (baseline)
2. Backtest 30j avec params propose
3. Comparer N trades + PF + WR
4. Si N=0 ou PF degrade > 30% : NOGO automatique
5. ml-trainer 5 controles obligatoire si PATTERN_11 risk (cf `.claude/rules/critical-tasks-review.md` critere 9)

**Fix 03/06 12:45** :
- `bn_v5_engine.py:83` : range_drift_min_pct 0.20 -> 0.10 (compromis NQ P75 + ES P85)
- `bn_v5_engine.py:95,99` : require_aggressor_confirm + require_long_bar_confirm True -> False
- `log_catalog.py:576-577` : BN_V5_GATE_*_BLOCK MAJEUR -> INFO
- SCP + restart paper_v2 OK

**Decision_override** : Jackson override 2 reviewers GO-AVEC-RESERVES qui exigeaient SHADOW MODE 7j avant ACTION live. Justification souveraine : "ON DEPLOY TRADING PAPER DIRECT PAS DE SHADOW" (Sim2 = paper donc pas capital reel, status quo 0 trade = bot mort).

**Risques documentes** :
1. Data mining (1 fenetre 13j seulement, DSR Lopez non calculable)
2. Regime adverse (juin VIX 14 vs mai 22, M_SHORT pourrait chuter)
3. Range filter conceptuellement faux pour V/W (Wyckoff)
4. 0 tests pytest BN V5 = regression future indetectable

**Plan monitoring strict** : J+1 / J+7 / J+30 quantitatif + kill switch DD > 200t NQ / 80t ES.

**Reviewed** : code-reviewer GO-AVEC-RESERVES + market-analyst GO-AVEC-RESERVES (Jackson override)

---

### 2026-06-03 10:10 (33) - [VALIDATION_MISS] - Mapping Bot ID dashboard vs flatten_bot.py refacto archi 28/05 incomplet

**Contexte** : Refacto architecture bots 28/05 reordonne Sim accounts (Bot 1=Sim1, Bot 2=Sim2, Bot 3=Sim3, Bot 4=Sim4 nouveau) MAIS :
- `CORE/flatten_bot.py:30-34` BOT_TO_ACCOUNT garde l'ancien mapping (1->Sim3, 3->Sim1)
- `CORE/databento_paper_trader_v2.py:187-188` consume mechanism lit FLATTEN_2 (Bot 2 V2 SetupEngine legacy) + FLATTEN_3 (Bot 1 MP ancien Sim1). Pas FLATTEN_1 ni FLATTEN_4.
- `CORE/mia_paper_trader.py:83` (Bot 4 process) consume FLATTEN_1_*.flag (legacy "Bot 1 DMP" pre-refacto = Sim3 ancien).
- `DASHBOARD/static/js/dashboard.js:6792` `_currentBotIdForApi` ne supporte que "bot1/2/3" (pas "bot4").
- `DASHBOARD/api/admin_routes.py:921,996` `_VALID_BOT_IDS` + `bots_to_flag` ALL omettent "4".

**Cause racine** : refacto cross-module mal propage. Frontend dashboard updated avec nouveau naming mais backend (flatten_bot.py + consume mechanism + Bot 4 process + admin_routes) restes sur ancien naming. Aucun audit integration pre-merge refacto 28/05.

**Impact prod** : Bouton FLATTEN dashboard cosmetique depuis 28/05 (5 jours). 5 admin_log "bot_flatten OK" le 03/06 = 5 fois flat mauvais Sim. Plus dangereux : si Jackson clique FLATTEN sur card Bot 4 dashboard, `_currentBotIdForApi("bot4")` retourne "1" par defaut -> ferme Bot 1 Sim1 au lieu de Bot 4 Sim4.

**Lecon** : tout refacto cross-module DOIT auditer TOUS les callers du mapping modifie en checklist :
1. Frontend dashboard.js (`_currentBotIdForApi`, `currentPaperBot`)
2. Backend admin_routes.py (`_VALID_BOT_IDS`, route params, bots_to_flag)
3. Subprocess flatten_bot.py (`BOT_TO_ACCOUNT`, argparse choices)
4. Consume mechanism databento_paper_v2.py (`BOT{N}_FLATTEN_FLAG_PATTERN`)
5. Process separes (mia_paper_trader.py si applicable)
TOUS DOIVENT etre coherents AVANT merge refacto, sinon bouton dashboard ment pendant 5 jours sans alerter.

**Trigger prevention** : refonte architecture multi-bots avec changement Sim/ID = audit complet OBLIGATOIRE :
- Grep `BOT_TO_ACCOUNT` + `currentPaperBot` + `FLATTEN_` + `_VALID_BOT_IDS` cross-codebase
- Si dashboard bot1/2/3/4 = Sim1/2/3/4 -> verifier que TOUS les consumers respectent cette convention
- Tests integration E2E : click FLATTEN bot1 dashboard -> verifier Sim1 broker flat (pas autre)

**Fix 03/06 10:10** : 8 fixes total appliques sur 3 rounds code-reviewer.

**Round 1 — code-reviewer NOGO 6 bugs critiques** :
1. CRITIQUE Race FLATTEN_1_*.flag : Bot 4 process (mia_paper_trader.py:3673) consumait DEJA FLATTEN_1_*.flag pre-existant -> double-consume avec mon nouveau handler paper_v2 pour Bot 1
2. CRITIQUE flatten_bot.py argparse "4" pas dans choices -> `python flatten_bot.py --bot 4` exit 2 ; `--bot all` n'incluait pas Sim4
3. CRITIQUE Race FLATTEN_3 stale heritage : pas de TTL check sur nouveaux handlers BOT1/BOT3_v4 (pattern Bot 2 lignes 3917-3937 absent)
4. MINEUR silent fallback : `except Exception: pass` ligne 3987 (anti-pattern `.claude/rules/data-quality.md`)
5. MINEUR _VALID_BOT_IDS admin_routes : "4" manquant -> 400 sur FLATTEN Bot 4 dashboard
6. MINEUR doc admin_routes.py:917-919 ancien mapping (Bot 1 DMP -> Sim3 etc.)
+ bonus : code log `BOT3_V3_FLATTEN_MANUAL_EXECUTED` jamais emis (asymetrie EXCEPTION/EXECUTED -> audit J+1 impossible)

**Round 2 — code-reviewer 2 nouveaux bugs CRITIQUES** :
1. admin_routes.py:996 `bots_to_flag = ["1","2","3"]` oubliait "4" -> Flatten ALL ne creait jamais FLATTEN_4_*.flag
2. dashboard.js `_currentBotIdForApi` n'avait pas "bot4" -> retour "1" par defaut -> ferme Bot 1 Sim1 au lieu de Bot 4 Sim4

**Round 3 — GO franc** : fixes appliques + test empirique subprocess flatten_bot.py --bot 4 Sim4 OK_FLAT + consume FLATTEN_1_NQ.flag detecte stale TTL.

**Fix files** :
1. flatten_bot.py BOT_TO_ACCOUNT aligne {1:Sim1, 2:Sim2, 3:Sim3, 4:Sim4}
2. flatten_bot.py argparse choices + "all" ajout "4"
3. databento_paper_v2.py constants BOT1+BOT3 + handler refonte TTL pattern Bot 2
4. mia_paper_trader.py Bot 4 process rename BOT1_FLATTEN -> BOT4_FLATTEN (anti-race)
5. log_catalog.py 8 nouveaux codes
6. admin_routes.py _VALID_BOT_IDS + bots_to_flag ALL ajout "4" + doc mapping
7. dashboard.js _currentBotIdForApi ajout "bot4"->"4"
8. Test empirique subprocess Sim4 + consume FLATTEN_1_NQ.flag = OK

**Reviewed** : code-reviewer 3 rounds + tests empiriques VPS

---

### 2026-06-03 09:13 (32) - [VALIDATION_MISS] - Guard DTC FILL_INVALID trop large (status != 7 = CRITIQUE faux positif)

**Contexte** : `bot3_v3_continuation_paper.py:545` et `bot3_v4_data_driven_paper.py:546` handler `handle_dtc_fill` emettait `FILL_PRICE_INVALID` niveau CRITIQUE sur TOUT `OrderStatus != 7`. Or DTC sequence normale d'un SL STOP en attente = status=2 (Open ACK) -> status=4 (Working en attente trigger) -> status=7 (Filled quand trigger). Le bot considerait status=2/4 comme fill INVALID.

**Cause racine** : commentaire ligne 549 disait "Tout autre status routed ici = bug routing (cid registered mais status non-fill)". Faux : le routing par cid voit TOUS les ORDER_UPDATE du cid, pas seulement les fills. CLAUDE.md regle souveraine "OrderStatus=2 n'est PAS Filled. JAMAIS traiter 2 comme Filled. Sequence normale : 2 -> 4 -> 7" non respectee dans le handler initial.

**Impact prod** : 28 faux CRITIQUE en 6h sur 03/06 matin (07:00-09:00). Cascade 10 crashes process paper_v2 (PIDs 9888 -> 10176 -> 5272 -> 8660 -> 7040 -> 3652 -> 5304 -> 7652 -> 6960 -> 7396 -> 8828). A chaque crash, RECOVERED_TIMEOUT invente PnL fictif sur positions ouvertes (incident 03/06 -$175 fictifs : NQ -$150 a 07:27 + ES -$25 a 09:01).

**Lecon** : guard CRITIQUE doit etre AUDITE empiriquement avant deploy. Le commentaire ligne 549 "bug routing" etait un assumption non verifie : le routing voit normalement tous les ORDER_UPDATE du cid (parent + tp + sl). Filtrer par status=7 + fill_price > 0 = vrai ghost trade SEULEMENT.

**Trigger prevention** : tout guard niveau CRITIQUE doit avoir :
1. Test pytest qui simule chaque status DTC (2, 4, 6, 7+invalid, 7+valid, 8) et verifie le comportement
2. Audit grep historique : si un guard CRITIQUE > 100 events/24h sans incident reel -> investigation faux positif obligatoire
3. Commentaire qui explique le comportement attendu + reference CLAUDE.md regle DTC

**Fix 03/06 09:13** : handler modifie pour return True sur status non-7 (ACK/Working = update legitime). Status 6 (Rejected) / 8 (Cancelled) -> ORDER_TERMINAL INFO niveau. GUARD #2 (fill_price<=0 sur status=7 = vrai ghost) preserve. Validation empirique : 0 FILL_PRICE_INVALID apres 09:13 (vs 28 avant). PID paper_v2 stable.

**Reserve ouverte** : SL Rejected handler manquant (status=6 -> ORDER_TERMINAL INFO mais pas de force flat). Position reste tracked SANS protection si SL rejete. Critique pour LIVE AMP (P3 backlog : `_force_flat_no_sl()`).

**Reviewed** : code-reviewer (GO-AVEC-RESERVES sur SL Rejected handler)

---

### 2026-06-03 06:50 (31) - [VALIDATION_MISS] - Migration MNQM26 sans verif Sierra Chart pre-config

**Cross-ref** : entry (30) tick value NQ specs CME (05:30) -> apres fix tick_value E-mini, migration MNQM26 testee 06:50 = bug deploiement different (symbole non config SC) ≠ bug specs. Timeline complet : 05:30 fix tick value -> 06:30 migration MNQM26 -> 06:50 detection Trade Activity Log vide -> 07:10 rollback E-mini.

**Contexte** : Jackson directive "cross-chart Sierra etudes sur NQM26 visuel + execution sur MNQM26 Micro". Migration code 24 fichiers (NQ tick 5.00 -> 0.50 + symbol NQM26 -> MNQM26 + n_contracts 1 -> 5 puis 3). SCP + restart paper_v2. **Aucune verification empirique pre-migration que Sierra Chart Sim accepte MNQM26-CME**.

**Cause racine** : assumption non testee que MNQM26 est dispo par default dans Sierra Chart data feed. Trade Activity Log post-deploy vide -> ordres MNQM26 pas routes au broker. Dashboard affiche trades fantomes (bot pense ouvert, broker n'a rien). Cascade crashes (signal_id reuse, RECOVERED_TIMEOUT fictifs).

**Impact prod** : 4 trades NQ MNQM26 emis (06:41-06:50) avec FILL_PRICE_INVALID immediat car SC ne route pas. Crashes paper_v2 + Bot 4. Decision Jackson 07:10 = rollback complet vers E-mini "Option A pure sans triche" + futur migration apres Sierra Chart config.

**Lecon** : tout changement de symbol broker DOIT etre teste empiriquement AVANT migration code :
1. SSH VPS + lancer `flatten_bot.py --bot X --json` ou similar sur nouveau symbol pour verifier accept broker
2. Verifier Trade Activity Log Sierra Chart accepte le symbol (status non-Rejected)
3. Test 1 ordre minimal avant migrer 24 fichiers

**Trigger prevention** : checklist obligatoire avant tout changement symbol :
1. Symbol existe dans data feed Sierra Chart (File -> Find Symbol)
2. Symbol accepte par broker (Trade Activity Log apres test order)
3. Tick size + multiplier + permissions broker pour ce symbol verifies
4. Tests pytest sur SYMBOL_TO_CONTRACT mapping si applicable

**Fix 03/06 07:10** : Rollback 16 fichiers vers E-mini partout. STOP.flag pre-existant supprime. Restart services. Trade Activity Log normalise. Migration MNQ reportee a post-config Sierra Chart cross-chart MNQM26 (eval prop firm).

**Reviewed** : self (decision rollback Jackson directe)

---

### 2026-06-03 05:30 (30) - [VALIDATION_MISS] - Tick value NQ $1.25 au lieu de $5.00 (E-mini specs)

**Contexte** : Jackson observe que dashboard affiche PnL en "MICRO" pas "MINI". Audit code : `CORE/constants.py:72` declare `"NQ": 1.25` avec commentaire `"E-mini NQM26 standard : $1.25/tick ($5/pt)"`. Mathematiquement faux : E-mini NQ = $20/pt -> $5/tick (PAS $5/pt). $1.25/tick correspond a Micro ES (MES = $5/pt × 0.25 tick), pas a NQ.

**Cause racine** : fix MICRO->MINI 02/06 (entry 27) a corrige NQ $0.50 (Micro) -> $1.25 par confusion avec valeur de MES Micro (qui = $1.25). E-mini NQ vrai = $5.00. Bug pre-existant sur Bot 4 deja documente entry 27 disait "Bot 4 envoyait E-mini standard ($1.25 NQ) mais calculait pnl_usd en MICRO ($0.50)" — la "valeur cible" $1.25 etait elle-meme fausse. Aucun agent (market-analyst NOGO 02/06, code-reviewer) ne l'a attrape : tous ont valide le passage $0.50 -> $1.25 sans verifier multiplicateur CME NQ. Erreur basique specs trading non audite.

**Impact prod** : PnL NQ affiche × **4 trop bas** sur Bot 1 v3, Bot 2 BN V5, Bot 3 v4 (+ Bot 4 deja ÷ 10 NQ et ÷ 10 ES). Tous trades NQ historiques sous-evalues. Ex : trade NQ 4 ticks → dashboard +$5 → broker reel +$20.

**Lecon** : verifier specs CME contract (multiplicateur $/pt × tick_size) AVANT tout fix tick_value. Cross-check formule : tick_value = multiplier × tick_size. Pour NQ : $20 × 0.25 = $5. PAS $5/pt × 0.25 = $1.25. Distinction multiplier vs tick value est basique trading et doit etre integree avant tout commit touchant tick_value.

**Trigger prevention** : avant tout fix tick_value dans code prod :
1. Grep specs CME (ou WebSearch "E-mini NQ contract specs") pour multiplier reel
2. Formule : tick_value = multiplier × tick_size (NQ : $20 × 0.25 = $5.00 / ES : $50 × 0.25 = $12.50 / MNQ : $2 × 0.25 = $0.50 / MES : $5 × 0.25 = $1.25)
3. Cross-check log execution : pnl_ticks × tick_value = pnl_usd cumulant le bon montant
4. INTERDIT : copier-coller tick_value d'un autre instrument sans verification specs

**Fix 03/06 05:30 (round 1)** : NQ 1.25 -> 5.00 dans CORE/constants.py:72, bot3_paper_common.py:61, bn_v5_engine.py:45, bn_v4_paper.py:88, bot3_config.py:138, mia_paper_trader.py:121, BOT/bot_config.py:38. ES 1.25 -> 12.50 dans mia_paper_trader.py + BOT/bot_config.py:31 (Bot 4 specifiquement). SCP + restart MIA-DataBento-Paper-V2 + MIA-Bot-4-Paper.

**Code-reviewer NOGO 03/06 05:45 (round 2)** : fix incomplet, 5 critiques :
- C1 `CORE/mia_sltp.py:62,63,67` : tick_value 0.50/1.25/1.00 + n_micros 3 importes par databento_paper_trader_v2 (Bot 3) + mia_paper_trader (Bot 4). Budget USD sous-estime 3.33x.
- C2 `BOT/order_manager.py:249,274` + `BOT/trade_journal.py:93` : hardcode `1.25 if ES else 0.50` → PnL log faux × 10 sur fills bracket.
- C3 `databento_paper_trader_v2.py:1596` ladder default fallback 0.50 (inerte si ladder OBSERVE, dette latente).
- C4 side-effect ladder_paliers (lock USD × 4 maintenant E-mini mais cap ticks pur, OK).
- C5 `BOT/test_bot.py:48` : test `NQ.tick_value == 0.50` fail apres fix.

**Fix 03/06 06:00 (round 2)** :
- `mia_sltp.py:62-67` : NQ tick 5.00 + n_micros 1 + max_usd 400 (preserve max_ticks 80). ES tick 12.50 + n_micros 1 + max_usd 500 (preserve max_ticks 40). MGC n_micros 3->1 + max_usd 120->40 (preserve max_ticks 40).
- `order_manager.py:249,274` : hardcode `12.50 if ES else 5.00`.
- `trade_journal.py:93` : idem.
- `test_bot.py:48` : `NQ.tick_value == 5.00`.
- SCP + restart MIA-DataBento-Paper-V2 + MIA-Bot-4-Paper (round 2).

**Dette tech restante** : remplacer hardcode order_manager/trade_journal par `INSTRUMENTS[sym].tick_value` (refacto). Verifier ladder_paliers calibration USD (lock × 4 maintenant, peut etre trop generous).

**Reviewed** : code-reviewer NOGO -> corrige round 2 ; agent audit trades du jour en cours pour validation PnL recalcule.

---

### 2026-06-02 22:30 (29) - [CONTEXT_MISS] - Dashboard Bot 1 affiche pas positions ES/MGC actives

**Contexte** : Jackson rapporte trade ES SHORT 7593.75 Sim1 visible sur Sierra Chart mais ABSENT du dashboard onglet "Bot 1 NQ + ES".

**Cause racine** (agent investigation 02/06 22:25) : `get_bot3_v3_payload()` `DASHBOARD/api/paper_tracker.py:1996` retournait `today.get("positions_active", {})` qui ne contient QUE les positions NQ Wyckoff (depuis `LOGS/bot3_v3/`). Les positions ES/MGC ouvertes via `_bot3_execute_trade` (databento_paper_v2) sont persistees dans `databento_paper_v3_state.json["positions"]` mais JAMAIS dans `LOGS/bot3_v3/`. Le merge avait ete fait pour `closed_today` (lignes 1903-1934) mais OUBLIE pour `positions_with_countdown`.

**Lecon** : refonte architecture 28/05 ("4 bots", Bot 1 = NQ Wyckoff + ES/MGC MP fusion) appliquee partiellement cote dashboard. Merge closed_today fait, merge positions_active oublie. Pattern omission feature partiellement implementee.

**Trigger prevention** : refonte architecture multi-source DOIT auditer tous les payloads dashboard (closed + active + stats + signals) en check-list. Pas seulement closed.

**Fix 02/06 22:30** : ajout merge positions ES/MGC depuis `STATE_FILE_BOT3` dans `get_bot3_v3_payload()` avec normalisation schema bot3_v3 + defense en profondeur `if sym in positions_active_merged: continue`.

**Reviewed** : agent general-purpose 02/06 22:25 -> diff precis applique.

---

### 2026-06-02 22:00 (28) - [PATTERN_PLAN_C_REPRO] - Confusion ticks vs USD sur cap TP ES (150t au lieu de $150)

**Contexte** : 02/06 matin Jackson directive "caper TP ES a 150 USD", interpretee a tort comme "tp_cap_ticks = 150" (=$1875). Le bot a place TP @7568.21 sur trade ES SHORT 7593.75 = 102 ticks = $1275 cible, alors que Jackson voulait $150 (=12 ticks ES standard $12.50/tick).

**Cause racine** : confusion unite ticks vs USD (= pattern Plan C 27/05, `.claude/rules/critical-tasks-review.md` SIZING DEPLOY Check 1). J'ai lu "150" sans confirmer l'unite avec Jackson. Backtest aurait du etre fait avec TP=12t (pas 150t), invalidant le scenario C "PF 2.75" qui justifiait le changement.

**Lecon** : tout chiffre lie a SL/TP/risk DOIT inclure son unite explicite (USD, ticks, points, R) dans la directive Jackson. Si ambigu : confirmer AVANT de coder. Ne pas extrapoler "150 = 150 ticks" parce que c'est le format du code.

**Trigger prevention** : avant tout changement SL/TP en config, repeter en clair "X USD = Y ticks pour 1 contrat Z" et faire valider Jackson. Idem si Jackson change d'avis : confirmer unite.

**Fix 02/06 22:00** : `CORE/bot3_config.py` ES guard_rails :
- `tp_cap_ticks` : 150 -> 12 ($150 USD pour 1 ES standard)
- `tp_rr_ratio` : 4.69 -> 1.5 (TP target sera capped a 12t)
- `timeout_minutes` : 60 -> 30 (revert baseline pre-02/06 matin)
- `sl_ticks_base` inchange 32t (= $400 risk)
- RR effectif = 12/32 = 0.375 (defavorable statistiquement, reserve doc dans config)

**Reviewed** : Jackson directive "ON AVAIS DIT CAPER LES TP ES A 150 USD" + auto-detection erreur unite.

---

### 2026-06-02 20:00 (27) - [VALIDATION_MISS] - Bug latent PnL Bot 4 x2.5 sous-estime (constants.py MICRO vs broker E-mini)

**Contexte** : audit market-analyst lors du rollback sizing "TOUT EN MINI" 02/06 soir a revele que `CORE/constants.py:TICK_VALUE` etait en MICRO (NQ=0.50, ES=1.25) DEPUIS l'origine, alors que les bots envoyaient des contrats E-mini STANDARD (NQM26-CME = $1.25/tick, ESM26-CME = $12.50/tick).

**Bug latent** : Bot 4 (NEW_BOT_2_MIA_TRADER, service MIA-Bot-4-Paper RUNNING) appelle `get_tick_value(symbol)` lignes 780, 856 de `main.py` pour calculer `pnl_usd = pnl_ticks * tick_value * n_micros`. Avec mapping NQM26-CME (E-mini standard) mais tick_value=0.50 (micro), PnL Bot 4 sous-estime systematiquement 2.5x (NQ) et 10x (ES).

**Detection** : impossible sans probe live AMP ou audit dedie. Pas detecte par tests pytest (les tests utilisent les memes valeurs faussees). Pattern silent fallback (cf `lessons.md` "gamma hardcode 0.0").

**Cause racine** : `CORE/constants.py` historiquement scoped "micros". Pas mis a jour lors des migrations broker (Bot 4 Phase 7.1 SAFE COLLECT 27/05 utilise E-mini standard sur Sim4).

**Lecon** : toute source de verite tick_value doit etre auditee a chaque migration broker (MICRO <-> STANDARD). 2 sources alignees minimum : (1) SYMBOL_TO_CONTRACT mapping (2) TICK_VALUE_USD. Probe live recommandee a chaque migration.

**Trigger prevention futur** :
- Audit market-analyst doit grep `TICK_VALUE.*0\.50|tick_value.*0\.50` partout pour detecter incoherences MICRO/MINI silencieuses
- Dette latente identique a corriger si reactivation : `CORE/mia_paper_trader.py:121`, `BOT/bot_config.py:31,38`, `CORE/databento_bot.py:100`, `CORE/databento_paper_trader.py:151`, `CORE/mia2_brain_v6_databento.py:148` (tous DISABLED).

**Fix 02/06 soir** :
- `CORE/constants.py:65-69` TICK_VALUE migre MICRO -> MINI standard (NQ=1.25, ES=12.50, MGC=1.00)
- `CORE/constants.py:368` fallback get_tick_value 1.25 -> 12.50 (coherent E-mini)
- Tests 7/7 smoke PASS apres fix.

**Reviewed** : market-analyst 02/06 19:55 -> NOGO initial, fix applique avant deploy.

---

### 2026-06-02 14:30 (26) - [VALIDATION_MISS] - Tests engines pre-existants casses (19/78 FAIL) non lies sizing 02/06

**Contexte** : audit pre-deploy sizing per-bot 02/06 a revele que tests engines drift defaults vs tests (`tests/test_bot3_v3_engine.py` + `test_bot3_v4_engine.py` + `test_bot2_edges_engine.py` = 19 FAIL / 78 total) sont PRE-EXISTANTS. Regle `.claude/rules/critical-tasks-review.md` SIZING DEPLOY Check 3 exige pytest engines PASS = NOGO automatique.

**Cause racine** : drift entre defaults engines et tests sans documentation. Probable accumulation depuis 28/05 (fix MES->ES) ou plus tot. Aucun INCIDENT_LOG entry historique.

**Lecon** : tests engines pytest doivent etre maintenus en CI continuous, pas seulement valides ad-hoc. Drift silencieux = piege pre-deploy si un changement majeur (sizing) survient.

**Trigger prevention futur** :
- Tests engines doivent etre RUN apres chaque modif critique trading
- Si fail pre-existant : documenter dans INCIDENT_LOG la 1ere fois
- Bloquer deploy si fails non documentes

**Decision 02/06** : deploy sizing per-bot quand meme avec cette RESERVE documentee. Tests engines drift = dette technique a corriger separement (pas bloquant sur paper Sim1).

**Reviewed** : agent code-reviewer 02/06 14:00 -> GO-AVEC-RESERVES condition documentation pre-existante

---

### 2026-06-02 14:00 (25) - [VALIDATION_MISS] - PnL dashboard Bot 1 NQ sous-estime x2.5 vs broker reel depuis 28/05 (incoherence MICRO calcul / STANDARD exec)

**Contexte** : 28/05 fix MES->ES standard ($1.25->12.50 tick_value) dans GUARD_RAILS_BOT3["ES"]. Mais NQ a ete LAISSE en STANDARD broker (NQM26-CME mapping) avec MICRO calcul code (bot3_paper_common TICK_VALUE_USD["NQ"]=0.50). Resultat : 78 trades Bot 1 NQ 28/05-01/06 affichaient PnL ÷ 2.5 vs realite broker Sim1.

**Cause racine** : audit incomplet 28/05 fix MES->ES. Reviewer + Jackson ont aligne ES mais oublie de verifier NQ. Pattern "fix partial" qui laisse divergence cachee.

**Lecon** : tout changement sizing/tick_value sur 1 symbole DOIT inclure audit cross-symbol. Specifiquement : verifier que MICRO calcul code matche MICRO broker mapping pour CHAQUE symbole, pas juste celui qu'on fixe.

**Trigger prevention futur** : check liste sanity pre-deploy sizing :
- SYMBOL_TO_CONTRACT[sym] match contract reel SC (MNQ micro vs NQ standard)
- tick_value config match $/tick contract reel
- n_contracts coherent broker
- Audit cross-symbol post-fix : refaire calcul empirique sur 5 trades historiques

**Fix applique 02/06** :
- Audit forensique R3 documente $+240 ecart sur 78 trades
- Architecture per-bot sizing (chaque bot config independante)
- 7 fichiers patches + 4 hardcodes qty=1 corriges + defaults n_contracts=3 fail-loud
- CHANGELOG entry 02/06 14:00

**Reviewed** : agent code-reviewer 02/06 13:00 NOGO 5 bloquants -> corrections appliquees -> re-review pending

---

### 2026-06-01 09:30 (24) - [VALIDATION_MISS] - Payload DTC SL STOP envoye avec Price1=StopPrice depuis le debut V2 (60 jours non audite vs specs DTC)

**Contexte** : 60 trades NQ Bot 1 v3 Sim1 27-29/05 audites — SL slip mean +10.5t favorable artificiel, 83% trades |slip|>5t, max +109t. PnL paper gonfle ~50%.

**Ce qui a mal tourne** : code `BOT/dtc_connector.py:434` (et 3 sites equivalents ladder/trailing/BN V4) envoyaient les SL STOP avec `Price1=sl_price` ET `StopPrice=sl_price`. Specs DTC officielles `s_SubmitNewSingleOrder` disent que `OrderType=3 (STOP)` utilise UNIQUEMENT `StopPrice`. SC interpretait comme `OrderType=4 (STOP_LIMIT)` avec LIMIT=STOP, qui fillait au LIMIT favorable au touch.

**Cause racine** : payload DTC jamais audite ligne par ligne vs specs officielles. Bug present depuis 02/04/2026 (debut V2 OCO manuel valide), 60 jours en prod sans detection. Couches d'audit DTC du 02/04 + fix H6 du 04/05 + tests Bot 1 03/05 sont passes a cote du champ Price1 sur STOP (focus sur cancel/anti-orphan, pas envoi).

**Lecon** : tout nouveau OrderType DTC (STOP, STOP_LIMIT, MARKET_IF_TOUCHED) doit avoir un audit payload vs specs officielles `s_SubmitNewSingleOrder` AVANT premier envoi prod. Les tests pytest "ca marche" ne suffisent pas — il faut prouver que les champs envoyes correspondent EXACTEMENT a la spec du OrderType.

**Trigger prevention futur** :
- Avant tout nouveau `OrderType=X` dans DTC payload : grep specs officielles + verifier que seuls les champs autorises pour ce type sont envoyes
- Audit pytest payload (test_dtc_*_payload_specs.py) doit verifier chaque champ AVANT deploy
- Si bug similaire suspecte (slip favorable systematique > spread bid/ask) : grep `Price1` + `StopPrice` envoi DTC

**Fix applique 2026-06-01** :
- Patch 4 sites (`dtc_connector.py:436-462`, `paper_v2.py:2104+2447`, `bn_v4_paper.py:1061`)
- Code log `SL_STOP_PATCHED_V1` (INFO, execution) emit a chaque SL — verification empirique J+1 patch actif
- Tests pytest mock DTC 5/5 PASS + BOT/test_bot.py 46/46 PASS (non-regression)
- Phase 0 audit RISK anti-orphan : SAFE (ServerOrderID independant OrderType)
- CHANGELOG entry 2026-06-01 09:30
- Setting SC `Allow Simulated Resting Limit Order to Fill at Better Price=No` deja applique 30/05 (reduction partielle +4.7t)

**Reviewed** : agent code-reviewer 01/06 09:18 → NOGO initial (3 sites manquants + CHANGELOG/INCIDENT_LOG/log fail-loud) → P0 corrections appliquees → re-review pending avant deploy

---

### 2026-05-28 03:30 (23) - [DECISION_OVERRIDE] - Bot 4 L3 BN v2 rehab deploye contributif SANS DSR Lopez (exception souveraine Jackson)

**Contexte** : Bot 4 audit 28/05 = 0 trade aujourd'hui (1038 decisions ATTENDRE sur 94 bars uniques). Sweep threshold 1.5-3.5 sur 26-27/05 prouve les 4 layers actifs (L1/L2/L4/L5) ne generent PAS d'edge (tous PF<0.7, WR~33%). Layer L3 BN v2 prevu spec d'origine mais REPORTE 26/05.

**Decision Jackson 28/05 03:15** : reactiver L3 (spec OR-fusion 4 patterns + boost cluster) **directement contributif** (pas shadow mode), bypass INCIDENT_LOG #22 (28/05 01:45) qui exige DSR>=0.5 + n_folds_pf>1.3>=50% + PF_min_fold>=0.7 AVANT deploy contributif.

**Pourquoi bypass** :
- Bot 4 = paper Sim4 1 micro NQ Phase 7.1 SAFE COLLECT (cf memory `project_bot4_live_phase71_20260527.md`)
- Precedent souverain memory `project_bn_v4_paper_decision_20260523.md` : Jackson autorise paper sans DSR si "rien a perdre"
- Reactivation L3 est urgente pour debloquer Bot 4 0 trade (alternative = laisser dormant)

**Risques acceptes** :
- Pas de backtest preservation wins (spec OR-fusion non backtestee)
- Pas de DSR Lopez
- MAX_POSSIBLE_SCORE 8->10 -> impact sizing (-50% theorique sur risk.py)
- Pollution data calibration si L3 faux positif

**Mitigations en place** :
1. **Kill switch env var** `MIA_BOT4_L3_DISABLED=1` -> rollback 5s sans redeploy (test valide 28/05)
2. **4 codes log_catalog** dedies : `BOT4_L3_TRIGGERED_LONG/SHORT/REGIME_NEUTRE_SKIP/KILL_SWITCH_ENABLED`
3. **Suivi serre** J+1/J+3/J+7 avec gates de retour shadow si faux positifs (cf CHANGELOG)

**Lecon** : exception au protocole est ACCEPTABLE en paper micro avec mitigations explicites + traceabilite kill switch + suivi serre + documentation INCIDENT_LOG. NE PAS reproduire en live AMP ou en gros sizing.

**Trigger prevention futur** :
- Avant tout futur bypass INCIDENT_LOG : verifier presence (a) kill switch runtime, (b) codes log_catalog dedies, (c) plan suivi J+1/J+7 avec criteres mesurable, (d) entry INCIDENT_LOG documentant le bypass.
- Si l'un manque : NOGO l'exception, revenir au protocole standard.

**Fix applique 28/05 03:15** :
- L3 reactive (`l3_bn_v2.py` NEW + integration `decide.py`)
- 4 codes log_catalog ajoutes (`CORE/log_catalog.py:210-214`)
- CHANGELOG entry 28/05 03:15 documentant l'exception

**Reviewed** : agent code-reviewer 28/05 03:00 -> NOGO direct shadow 7j obligatoire. Override Jackson + mitigations -> GO conditionnel monitoring serre.

---

### 2026-05-28 01:45 (22) - [VALIDATION_MISS] - Bot 3 v4 deploye 24/05 sans seuil DSR minimum, KILL 28/05

**Contexte** : Bot 3 v4 paper Sim3 NQ deploye 24/05 avec baseline backtest n=1110 PF=1.033 WR=30% **DSR=0.13** (marginal Lopez). Audit Lopez 28/05 (agent ml-trainer) sur n=41 live = CI 95% PF [0.08, 0.64] EXCLUT 1.0, **P(true PF >= 1.0) = 0.08%** (1 chance sur 1250).

**Ce qui a mal tourne** : SWING family (53% des trades v4) s'effondre PF 2.33 (backtest 414 trades) -> 0.11 (live 24 trades) = **x20 effondrement**. SWING_HIGH live PF 0.07 (1 win sur 13). V4 a abandonne les niveaux institutionnels gagnants de V3 (CUR_VPOC, MQ_1D_MAX, GEX_DN, PREV_VAH PF >1.5) pour surcharger SWING. Cumul 4j live = -$375.50.

**Cause racine** : protocole deploy paper actuel n'a PAS de seuil DSR minimum. Baseline DSR 0.13 (marginal) + n_folds_pf>1.3 = 2/12 (16.7%) = signal fragile from the start. **N'aurait jamais du etre deploye sans seuil minimum**.

**Lecon** : tout deploy paper d'un bot ML/strategie doit passer 3 gates :
1. DSR Lopez >= 0.50 (ideal 1.0+) sur n>=100 trades backtest
2. n_folds_pf>1.3 >= 50% (stabilite cross-folds)
3. PF_min_fold >= 0.7 (eviter PF moyen masquant un fold catastrophique)

Sinon = **deploye en mode CONFIDENCE INSUFFISANTE** = bot va probablement perdre live.

**Trigger prevention** :
- Avant tout deploy paper bot ML : grep DSR/n_folds dans backtest report. Si DSR<0.5 OR n_folds_pf>1.3<50% → REFUSER deploy paper, demander recalibration.
- Nouvelle regle 10 `.claude/rules/critical-tasks-review.md` a creer pour formaliser ces gates.

**Fix applique 28/05** :
- Bot 3 v4 KILL via env var (`MIA_BOT3_V4_ENABLED=0`) — en attente GO Jackson
- Audit complet `DOCS/AUDITS/2026-05-28_audit_bot3v4_lopez.md`

**Reviewed** : agent ml-trainer Lopez bootstrap PF + PSR z-stat -3.075 (99.89% confiance edge negatif).

---

### 2026-05-27 15:35 (21) - [VALIDATION_MISS] - Bot 4 ne peut JAMAIS trader : schema MenthorQ obsolete dans reader

**Contexte** : Apres deploy Bot 4 LIVE 27/05, monitor 5h30 montre 2259 decisions emises mais ZERO trade. Audit decisions revele score_total max observe = 2.36 vs threshold 3.5 = `Bot 4 ne peut techniquement JAMAIS atteindre threshold` malgre pipeline fonctionnel.

**Ce qui a mal tourne** : `MenthorQReader.load_levels` (NEW_BOT_2_MIA_TRADER/src/reader.py:267) lit `payload.key_levels.NQ` / `payload.vol_model.NQ` / `payload.CTA.NQ` mais le scraper actuel produit le schema `payload.NQ.structured.{key_levels, netgex, bl_levels, matrix_v1, future_curve}` + `payload.CTA.raw_ajax`. Toutes les cles retournent None -> `menthorq_present = False` -> `menthorq_fresh = False` -> `L4_gamma inactive 100% (0/2480 bars)` -> score max plafonne ~2.4 (juste L1) < threshold 3.5.

**Cause racine** : Schema JSON MenthorQ a evolue (probablement V2 scraper deployment) mais le reader Bot 4 a ete code avec un schema obsolete reference de plan J3-J5. Aucun test ne couvrait le schema reel du scraper VPS (`test_7_menthorq_reader` utilise fixture obsolete).

**Lecon** : Quand un module consomme des fichiers JSON externes (data pipeline cross-system), le schema DOIT etre verifie empiriquement avec un sample REEL du producteur, pas un fichier mock. Le test inline avec fixture obsolete = false positive (test PASS mais code casse en prod).

**Trigger prevention** : 
- Tout nouveau reader/parser de fichier externe : ajouter test contre 1 fichier REEL VPS sample dans fixtures + assert structure attendue
- Audit J+1 : grep `menthorq_data_present` / `L4_gamma.active` dans logs Bot 4 -> seuil minimum 50% activation L4 (sinon investigation)

**Fix applique** : `MenthorQReader.load_levels` lignes 263+ adapte au schema reel : `payload.{SYM}.structured.{key_levels, netgex, bl_levels, matrix_v1, future_curve}` + `payload.{SYM}_swing.raw_ajax` + `payload.{SYM}_intraday.raw_ajax` + `payload.CTA` top-level.

**Verification post-deploy** : Bot 4 redemarre 15:35 UTC. L4_gamma active=True (au lieu de False). Sur bar test : walls_far (normal car LongTreand sans wall proche), sign=0 normal. Bot peut maintenant atteindre threshold quand conditions marche alignees.

**Reviewed** : Jackson + Claude self-audit (lecture VPS schema reel via `Get-Content | ConvertFrom-Json | PSObject.Properties.Name`)

---

### 2026-05-27 14:14 (20) - [DEPLOY_UNSAFE] - Bot 4 DTC reconnect boucle infinie + lock file orphelin apres Stop-Service

**Contexte** : Bot 4 J12 deploye 27/05 08:24 UTC Phase 7.1 SAFE COLLECT. Tournait 5h30. Audit logs 14:00 UTC revele : 334 HEARTBEAT + 0 trade + stderr inonde "Connexion perdue — tentative de reconnexion" en boucle.

**Ce qui a mal tourne** :
1. Bug DTC : Fix P0-3 J9 propage `client_name="MIA_Bot_4"` dans `connect()` initial mais PAS dans `_recv_loop` reconnect (hardcode "MIA_Bot_V2" residuel ligne 921 dtc_connector.py). Au 1er disconnect, reconnect avec ClientName V2 → collision avec wrapper Bot 1/2/3 → Sierra Chart kick.
2. Bug keepalive : DTC connector ne emit PAS Type 3 HEARTBEAT proactif (juste reactif aux HB recus). Bot 4 sur Sim4 sans market data subscribe ni trades = socket silencieuse → SC ferme apres timeout ~30-60s.
3. Bug lock file : `Stop-Service` brutal nssm tue process sans declencher `atexit` → `bot4.lock` reste orphelin → reboot Bot 4 crash `Bot4LockError` exit 2 → nssm restart loop chaque 30s sans jamais boot.

**Cause racine** : 3 bugs en chaine. Fix P0-3 J9 partiel = anti-pattern "fix grep incomplet". Keepalive proactif manquant = latent depuis V2 avril 2026 (Bot 1/2/3 maintenu socket via market data, masque le bug).

**Lecon** : 
1. Tout fix `client_name`/`ClientName` doit grep EXHAUSTIVEMENT le fichier (5 occurrences trouvees apres patch). Outil `tools/check_clientname_hardcode.py` recommande.
2. `Stop-Service` Windows brutal != SIGTERM Unix : atexit pas garanti. Lock file doit avoir auto-recovery (parse PID + check vivant) — voir IDEAS_BACKLOG P2-1 deja flag, maintenant CONFIRME en prod.
3. Sierra Chart kick silencieusement client DTC duplicate ClientName ou socket idle. Spec DTC : heartbeat proactif des 2 cotes obligatoire.

**Trigger prevention** : 
- Tout patch DTC connector partage Bot 1/2/3/4 → grep cross-fichier obligatoire AVANT deploy
- Restart Bot 4 service → checker `LOGS/bot4.lock` avant Start-Service, supprimer si orphelin
- Logs `bot4_stderr.log` monitorer ligne "Connexion perdue" → seuil 5+ = alerte
- **TOUT nouveau bot : VERIFIER `timeout_seconds > heartbeat_interval_seconds` (marge >= 2x)**

**Reviewed** : Jackson + 3 agents code-reviewer (specialiste DTC + comparaison Bot 1/2/3 vs Bot 4) 27/05 14:00-15:00 UTC

**RESOLUTION FINALE 27/05 14:34 UTC** (cycle 3 investigation) : agent comparaison Bot 1/2/3 vs Bot 4 tranche : **vrai cause racine** = `timeout_seconds=10` (Bot 4 surcharge `execution_config.py:30`) vs `heartbeat_interval=10` (negocie au logon). Race fatale : si HB SC arrive a t=10.05s, `recv()` timeout AVANT le HB → `_recv()` return None (avant patch sentinel) → `_recv_loop` interprete EOF → reconnect. Bot 1/2/3 utilisent `timeout=30s` (default DTCConfig) = marge 20s > HB = JAMAIS de timeout = zero reconnect. **Fix V3 = aligner Bot 4 sur 30s** (`execution_config.py:30`). Monitor 5 min post-fix : ZERO "Connexion perdue" (vs +12/5min avant). 4 patches deployes au final : V1a clientname reconnect + V1b keepalive proactif + V2 sentinel `_RECV_TIMEOUT` + **V3 vrai fix timeout=30s**. Patches V1b et V2 sont defensifs et peuvent etre retires post-validation Phase 7.1 SAFE COLLECT.

---

### 2026-05-27 09:30 (19) - [VALIDATION_MISS] - Plan C SL hybride deploye avec mauvaise unite atr

**Contexte** : Audit stop-hunter ce matin Bot 1 v3 + Bot 3 v4 (79-86% SL recovery TP). Agent backtest-runner valide Plan C SL hybride ATR-based sur 14j NQ : Bot 1 var C floor=0.5/cap=2.0 → +$2200, Bot 3 v4 var B 0.4/1.5 → +$1229. Deploy a 07:20 UTC.

**Ce qui a mal tourne** : code-reviewer cross-check apres deploy detecte BUG D'UNITES CRITIQUE :
- Backtest `CORE/research/backtest_sl_hybrid.py:47-65` calcule `atr14_15min` en **POINTS** (rolling TR sans `/tick`), median NQ 40 pts
- Code prod `bot3_v3_continuation_engine.py:729` lit `row["atr"]` qui est en **TICKS** (cf `enricher_chain.py:819-820`), ~38 ticks ATR_14_1min
- Double erreur : (1) unite ticks vs points = facteur 4x, (2) timeframe 1min vs 15min = facteur 3x
- Resultat : SL calcule ~12x trop petit que voulu par le backtest

**Cause racine** : deploy sans verifier que les fields utilises par backtest existent en live AVEC LA MEME UNITE. Le field `atr` est ambigu (pas de suffixe `_ticks` / `_points`) → meprise silencieuse.

**Lecon** : tout deploy sizing/SL/TP DOIT verifier alignement unite/timeframe entre fields backtest et prod sur la MEME bar historique. Si ecart > 5% → STOP.

**Trigger prevention** : ajout regle souveraine "Check 1/2/3 obligatoires" dans `.claude/rules/critical-tasks-review.md` section SIZING/SL/TP DEPLOY. Pre-deploy checklist OBLIGATOIRE : (1) field source backtest identifie, (2) probe live verifie ecart < 5%, (3) pytest engines passent.

**Reviewed** : Jackson + code-reviewer / Action immediate : rollback Plan C `sl_hybrid_atr_enabled_nq=False` deploye, paper_v2 restart. Re-backtest avec bonne unite en attente.

---

### 2026-05-26 03:00 (18) - [CONTEXT_MISS] - MASTER_PLAN NEW Bot 2 ecrit avec noms DMP au lieu de live_enriched VPS

**Contexte** : design NEW Bot 2, MASTER_PLAN.md ecrit avec VETO Tier 1 sur signaux `bar_long_dn_bar`, `bar_color_dn`, `bn_color_dn_2`.

**Ce qui a mal tourne** : ces colonnes sont les noms DMP JSONL (262 cols) mais NE SONT PAS dans `live_enriched` (que NEW Bot 2 doit consommer). Le live_enricher (refacto weekend 24-25/05) :
- Renomme : `bar_long_dn_bar` → `long_dn_bar`, `bar_long_up_dn` → `long_up_dn_pattern`
- Agrege : pas de binaire `bar_color_*`/`bn_color_*`, remplace par `n_color_*_cluster_within_0_2pct` + `dist_color_*_nearest_pct`
- Si NEW Bot 2 code `bar.get("bar_color_dn")` → None silencieux → VETO mort

**Cause racine** : verifie le local `DATA/live_enriched/NQ/20260521_NQ.jsonl` (468 cols, OBSOLETE pre-refacto) au lieu du VPS `20260525_NQ.jsonl` (492 cols, post-refacto). Local non sync depuis 21/05.

**Detection** : agent reviewer externe (consulte par Jackson) a flagge l'incoherence en cross-checking schema VPS.

**Lecon** : avant d'ecrire un MASTER_PLAN qui specifie des noms de colonnes, **dump SOURCE DE VERITE VPS en local** (SCP + grep exhaustif) au lieu de se fier au schema local potentiellement obsolete. Refacto pipeline weekend = schema potentiel evolutif.

**Trigger prevention** : Phase 1 NEW Bot 2 livrable `feature_coverage_matrix.md` doit cross-checker chaque colonne consommee contre `vps_schema_492cols.txt` (sauve `NEW_BOT_2_MIA_TRADER/specs/`). Aucun nom de colonne dans code NEW Bot 2 sans verification grep prealable sur schema VPS reel.

**Reviewed** : reviewer externe Jackson + self (CONTEXT_MISS reconnu, 18eme incident categorie atteinte 4+ occurrences → memoire dediee a creer)

---

### 2026-05-24 (17) - [CONTEXT_MISS] - Backtest Bot 3 reform sur dataset v4_enriched tronque (avril manquant)

**Contexte** : Session reform Bot 3, 10 variantes V1-V10 + 30 buckets Option 2 backtestees sur "5.3 mois propres MenthorQ" (15/12/2025 → 21/05/2026). Verdict "20/20 NOGO Lopez, V8 best PF 1.21 NQ".

**Ce qui a mal tourne** : `v4_enriched` avril 2026 tronque a 3 jours (28-30) au lieu de 25 (bug pipeline documente memory `project_pipeline_incremental_backlog`). 22 jours bear avril MANQUANTS = pire periode Bot 3 prod (-$1546 sur 4j actifs avril). Resultats biaises : Bot 3 paraissait "moins mauvais qu'il ne l'est".

Re-run sur `v4_pure` complet (194 jours oct 2025 → mai 2026) :
- V1 NQ PF 0.93 → 0.75 (pire)
- V8 NQ PF 1.21 → 0.90 (top candidat effondre)
- WR universel chute (V1 29% → 17%)

**Cause racine** : J'ai accepte le dataset sans verifier son completeness. `v4_pure` (raw) disponible avec 8 mois mais j'ai utilise `v4_enriched` (tronque) sans grep "ls -la" avant lancement.

**Lecon** : avant tout backtest, AUDIT empirique du dataset = (1) liste fichiers, (2) range dates, (3) count bars par jour, (4) verifier features critiques presentes. C'est 30 secondes qui aurait evite 4h de backtests invalides.

**Trigger prevention** : avant `load_v4_enriched()` (ou equivalent), faire AUDIT explicite : grep nb jours par mois, range total, sample size minimum 150 jours. Si <150 jours OU mois absent → FAIL FAST + investiguer alternative (v4_pure, backfill).

**Reviewed** : Jackson directive 2026-05-24 "VERIFIE LA MATURE DU TESTE QUE TU A EFFECTEUR LES DONNERR UTILISER ET LE CODE" + "DU COUP TOUT NOS DERNIER BACTESTE SON BIAISER" → confirme.

---

### 2026-05-23 23h (16) - [LAZY_DELEGATION + VALIDATION_MISS] - Cycle 4 reviews iter1→iter4 BN V4 integration

**Contexte** : Session 8h dev BN V4 paper deploy. Jackson exige "review agent apres chaque etape, non negociable". 4 iter reviews agents (~280K tokens total) ont attrape 8 P0 + ~13 P1.

**Cause racine** : Mes "fix" iter1→iter3 etaient des demi-fix (silent fallback + faux fix).
- iter1 : 4 P0 detectees, fix appliques
- iter2 : 2 P0 BIS detectees, mon fix #1 P0#1 etait COSMETIQUE (patche `format_message` qui etait CODE MORT, les vrais callers utilisent `Logger.emit` directement). Mon fix bonus VALIDATION_MISS log_fn injection a CREE un nouveau VALIDATION_MISS plus grave (28 codes BN_V4_* orphelins). Verdict iter2 = NOGO.
- iter3 : Reviewer a flagge 7 codes restants orphelins + bug audit `cause` lit `pos.get('n_pivots_confirmed')` always 0 (vit dans `_trail_state`).
- iter4 : Re-fix iter3 + retrait 5 codes inutilises -> GO-AVEC-RESERVES 8.5/10.

**Echec** : J'ai applique "demi-fix" plusieurs fois (pattern recurrent) :
1. iter1 fix P0#5 GATE_TOP_LEVEL_BLOCK : ajoute au catalog SANS EMIT dans le code = orphelin garanti
2. iter2 fix P0#1 format_message ValueError : patche code mort, le vrai chemin Logger.emit pas touche
3. iter2 fix bonus VALIDATION_MISS : "retire constantes des templates gates" sans s'assurer que CONFIG_LOADED est emit en prod = constantes perdues
4. iter3 fix P0#1 audit cause : code lit pos.get au lieu de self._trail_state[sym] = always 0

**Lecon** : avant deploy lundi, tous les "fix" doivent etre grep-verified post-application. Pattern LAZY_DELEGATION + VALIDATION_MISS = couple toxique.

**Trigger prevention** :
1. Apres TOUT fix log_catalog : grep cross-codebase `_emit("CODE", ...)` pour confirmer caller existe. Si 0 caller = orphelin = pattern interdit.
2. Apres TOUT fix logique : verifier que le state utilise est bien LE state, pas un dict pos qui en lit copie.
3. Lecture iter3 reviewer "C'est PILE le pattern VALIDATION_MISS" : signal d'alarme rouge -> stop tout dev + grep complet.
4. `LAZY_DELEGATION + VALIDATION_MISS` = pattern couple. Documenter dans memoire dediee si recurrence > 3 sessions.

**Reviewed** : 4 reviews agents en serie (iter1-4 au total ~280K tokens). Verdict final 8.5/10 GO deploy lundi 25/05 sous 4 conditions (test parite, dashboard update, vérif J+1 HEARTBEAT > 100, rollback si fail).

### 2026-05-22 (15) - [VALIDATION_MISS] - Audit 3 bots lance sur logs appauvris au lieu du journal riche

**Contexte** : Jackson demande un audit forensique des 3 bots sur les trades pris. Claude audite `LOGS/trading/*.jsonl` et `LOGS/execution/`.

**Cause racine** : `LOGS/trading/` = logs structures appauvris (`ctx` = sym+pnl seulement). Le vrai journal de trades = `DATA/PAPER_TRADES/*_trades.jsonl` (mae, mfe, walls, sl_ticks, regime, grade, 250 features `dmp_bar_at_exit`). Claude a affirme "Bot 1 et Bot 2 n'ont pas de mfe/mae" sans avoir cherche TOUS les fichiers de trades.

**Echec** : conclusions inversees — Bot 1 annonce −$2803 (reel +$474), Bot 3 annonce +$2325 (reel −$152). Jackson a rattrape en citant un trade NQ contenant `mae:-91 mfe:39 bars_held:8` issu de `20260520_trades.jsonl`.

**Lecon** : avant tout audit de trades, inventorier TOUS les fichiers `*trades*.jsonl` (`find`) et identifier le journal le plus riche. Ne jamais affirmer "champ absent" sans avoir cherche toutes les sources.

**Trigger prevention** :
1. Tout audit trades = `find "*trades*.jsonl"` en ETAPE 0, comparer la richesse des schemas
2. `VALIDATION_MISS` atteint 5 occurrences (#11, #13, #14, #15) -> escalation memoire dediee OBLIGATOIRE

**Reviewed** : Jackson (mentor) - rattrapage direct

### 2026-05-20 22:00 (14) - [VALIDATION_MISS] - Backtests Bot 2 sur v4_enriched alors que le live tourne sur live_enriched : 2 pipelines divergents + parquet corrompu

**Contexte** : Backtests SetupEngine Bot 2 (tri 11 setups + filtre MTF) lances sur `DATA/datasets/v4_enriched`. Doute Jackson sur la data -> comparaison v4_enriched vs live_enriched (ES 20/05, 1066 barres communes).

**Cause racine** : 2 moteurs de features distincts. `v4_enriched` produit par `build_dataset_v4_dmp_databento.py` (vieux), `live_enriched` par `enricher_chain.py` (moteur du live). Comparaison : `delta_bar` diverge 22% (signe oppose), `delta_day_dir` signe oppose, `vwap_slope_10` jamais identique. Seules les features MenthorQ-derivees identiques. + parquet `v4_enriched/NQ.c.0/mai` CORROMPU (ecriture non atomique, footer absent depuis 04:45).

**Echec** : Backtester sur une data que le bot ne verra jamais en live. Tout setup calibre sur v4 = non transposable, PF v4 sans valeur pour le live.

**Lecon** : Backtest et live DOIVENT partager le meme moteur de features. Source unique = `replay_enricher_batch.py` (rejoue `enricher_chain`). Abandonner v4_enriched pour Bot 2.

**Trigger prevention** :
1. Avant tout backtest qui informe un deploy : verifier data backtest == data live (meme pipeline)
2. Ecriture parquet batch DOIT etre atomique (tmp + rename) — backlog fix
3. `VALIDATION_MISS` atteint 3+ (#11, #13, #14) -> escalation memoire dediee due

### 2026-05-20 11:30 (13) - [VALIDATION_MISS] - Feature selection a ignore la blacklist PROHIBITED : 6 features LEAK dans le "subset 9 winners"

**Contexte** : Apres l'incident #12 (dimensionalite), pivot vers feature selection Lopez Ch.8 -> "subset 9 winners" annonce avec NQ PF 1.96 DSR=1.0. Puis search space 113 features, injection 15 features, forward selection incrementale (subset confirme PF 2.59), enfin re-backtest execution realiste backtest-runner -> **PF 6.26**.

**Cause racine** : Le backtest-runner a fait un test d'ablation : retirer les 4 features swing -> PF s'effondre 6.26 -> 0.92. Investigation : 6 des 9 "winners" sont des features LOOKAHEAD LEAK **deja blacklistees** dans `CORE/build_dataset_v4_dmp_databento.py:444-461` (PROHIBITED list, audit quality-auditor 27/04/2026) :
- `liquidity_sweep_high/low_lag5` : consultent `close[i+5]` explicitement
- `bars_since_last_swing_high/low` : derivees contaminees (fenetre centree)
- `dist_swing_high/low` : test ablation confirme contamination
Le `feature_selection_lopez_ch8.py` + le search space `features_finale_v1.txt` ont ete construits SANS croiser avec la blacklist PROHIBITED du pipeline. Les features bannies le 27/04 ont ete re-introduites comme "winners". 4 agents (feature-selection, forward-selection, injection, backtest) ont travaille dessus ; seul le dernier (backtest-runner, qui fait des ablations) l'a detecte.

**Echec** : Le leak-check aurait du etre l'ETAPE 0 de tout feature selection. DSR Lopez protege contre l'overfitting du backtest, PAS contre le look-ahead leak — deux problemes distincts. Le PF 1.96/2.59/6.26 = artefact, le modele voyait le futur.

**Lecon** : Tout pipeline de feature selection / search space DOIT en etape 0 :
1. Charger la blacklist `PROHIBITED` depuis `build_dataset_v4_dmp_databento.py`
2. Exclure toute feature blacklistee du search space AVANT tout calcul MDA/PFI/DSR
3. Test de controle : ablation des top features — si retirer K features effondre le PF de >50%, suspecter un leak (un edge propre est distribue, pas concentre)

**Trigger prevention** :
1. **Leak-check etape 0 OBLIGATOIRE** : tout search space croise avec PROHIBITED list AVANT feature selection
2. **Test ablation systematique** : retirer les top-3 features -> si PF s'effondre >50% = red flag leak
3. **label-shuffle test** : PF doit tomber a ~1.0 sur labels melanges (valide le moteur, pas les features)
4. **Categorie `VALIDATION_MISS`** : escalation si 3+ -> deja proche (incidents #11, #13)

**Fix applique 20/05** :
1. Backtest-runner a stoppe avant le code Bot 4 (leak attrape a temps)
2. Re-lancer feature selection avec blacklist PROHIBITED appliquee en etape 0
3. Search space `features_finale_v1.txt` a nettoyer : retirer Pilier 7 swing/sweep leak
4. Moteur `tools/backtest_bot4_realistic.py` valide sain (label-shuffle PF 1.06) — reutilisable

**Reviewed** : backtest-runner (detection ablation) + Claude (verification code source `build_dataset_v4_dmp_databento.py:444-461`)

---

### 2026-05-21 00:10 (12) - [OVER_ENGINEERING] - 3 semaines NOGO causes par dimensionalite non-flaggee par Claude

**Contexte** : Du 28/04 au 20/05, 5-6 backtests consecutifs ont produit NOGO sur dataset V4 (467-478 cols) malgre data Databento propre 8 mois :
- 28/04 audit cross-family : 5/5 NOGO (DSR<0.1, memory `feedback_data_mining_trap.md`)
- 07/05 BN V2 : NQ PF 0.97, ES marginal PF 1.12
- 18/05 Bot 3 V2 narrative (2700 LOC, 5 phases) : 1/8 EDGE_CONFIRMED Phase 5
- 19/05 Bot 3 V3 Confluence Score : 0/1798 DSR>=0.95 (ml-trainer agent)
- 19/05 Advisory V_BASE 8 mois v4_pure : 0/16 variants GO, DSR=0.000, -$14943 sur 5887 trades
- 17/05 Bot 1 full 17 gates v4_enriched : ES PF 0.81 / NQ PF 0.59

**Cause racine identifiee par Jackson 20/05 23:30** : 478 features pour ~5887 trades V_BASE = ratio 12.3 trades/feature. Lopez AFML Ch.7.6 exige N >= 10*p (minimum absolu) a 100*p (recommande). On etait juste au-dessus du minimum (5887 > 4780) mais a **12% du recommande** (47800). Pire en walk-forward 12-fold : 500 trades/fold / 478 features = 1.05 trades/feature = SOUS le minimum absolu. **DSR Bonferroni mathematiquement inatteignable** sur 478 features x 12 folds = nb_trials gonfle.

**Echec mentor (Claude)** : Claude a accompagne les 3 semaines de tests sans JAMAIS poser la question fondamentale "478 features x 5K trades est-il statistiquement viable ?". Dispatch ml-trainer + market-analyst sans flag amont sur la dimensionalite. **Industry standard quant pro (Two Sigma, AQR, RenTech publics) = 20-50 features pour modeles production** — Claude le sait mais n'a pas tire la sonnette d'alarme.

**Lecon** : Tout backtest ou audit edge candidate DOIT etre precede d'un **gut check dimensionalite** :
- Calculer ratio `n_trades / n_features` avant de lancer
- Si < 10 : NOGO methodologique, refuser l'audit, demander feature selection prealable
- Si < 100 : flag rouge, recommander feature selection (MDA, PFI, cluster Spearman) avant LightGBM/scoring composite

**Trigger prevention** :
1. **Pre-flight dimensionalite OBLIGATOIRE** avant dispatch ml-trainer / backtest scoring : compter features actives + estimer n_trades attendus -> ratio
2. **Refuser de coder un scoring composite** (Bot 3 V3, narrative, advisory) sur >50 features sans feature selection rigoureuse Lopez Ch.8 prealable
3. **Industry standard rappel auto-charge** : modeles quant prod = 20-50 features selectionnees, JAMAIS 478 brutes
4. **Categorisation `OVER_ENGINEERING`** : si 3+ occurrences -> memory dediee `feedback_dimensionality_check_first.md`
5. **Cross-check avec rule `awesome-performance.md`** : "Measure before optimizing" -> ici "validate dimensionality before testing edge"

**Fix applique 21/05 00:00** :
1. Kill task bf1rrdrzg (Bot 1 backtest sur 478 features) — verdict statistiquement vide attendu
2. Dispatch ml-trainer mandat STRICT feature selection rigoureuse Lopez Ch.8 sur v4_pure 8 mois (MDA + PFI + IC + cluster Spearman)
3. Cible : top 20-30 features stables walk-forward 12-fold
4. INTERDICTION absolue de tester un nouvel edge sur >50 features non-selectionnees rigoureusement

**Reviewed** : Jackson (mentor) - escalation directe "tu aurais du tirer la sonnette d'alarme"

---

### 2026-05-19 23:00 (11) - [VALIDATION_MISS] Bug FLATTEN_MANUAL Bot 2 V6 - Brain-V6 ne lisait pas le flag

**Contexte** : Suite fix 19/05 PM (bouton FLATTEN dashboard cable via flag files `DATA/BOT_CONTROL/FLATTEN_{bot}_{sym}.flag`), Jackson constate empirique 19/05 nuit que FLATTEN ne marche QUE sur Bot 1. Bot 2 V6 ES SHORT entry 7375.25 ouvert 22:16 UTC reste en tracking interne 3h+ apres click FLATTEN (state_v6.json bars_held=183, aucun TRADE_CLOSE log signal_id f7eeef8e). Broker Sim2 effectivement flat (verifie Sierra Chart GUI Jackson + flatten_bot.py Type 208/209/210 a fonctionne).

**Cause racine** : Le fix 19/05 PM avait code la lecture FLATTEN_2_*.flag UNIQUEMENT dans `CORE/databento_paper_trader_v2.py` (service MIA-DataBento-Paper-V2 = Bot 2 V2 SetupEngine + Bot 3 MP). Bot 2 V6 (service MIA-Brain-V6 distinct, code `CORE/mia2_brain_v6_databento.py`) ne lisait JAMAIS ce flag. Plus grave : paper_v2 supprimait le flag defensif `if self.positions[sym] is None` (ligne 3640-3645), avalant le flag avant que Brain-V6 puisse le voir (paper_v2 poll 30s vs Brain-V6 poll 10s = paper_v2 plus souvent en tete de course).

**Lecon** : Avant tout fix dashboard touchant `/api/admin/bot/{id}/...`, identifier TOUS les services Python qui ont un tracking interne pour ce bot_id. Bot 2 a DEUX implementations (V2 SetupEngine + V6 brain enrichi) dans 2 services distincts. Le fix 19/05 PM avait audite paper_v2 + paper_v3 mais oublie Brain-V6.

**Trigger prevention** :
- Avant patch dashboard FLATTEN/KILL/STOP : `Get-Service MIA-* | Where-Object Status -eq Running` pour lister TOUS les services bot actifs, puis grep dans chaque code source le pattern `FLATTEN_{bot_id}` / `STOP_FLAG` correspondant
- Regle de partage flag entre 2 process : NE JAMAIS unlink si self.positions[sym] is None sans coordination explicite (TTL ou owner explicite)
- Codes log distincts par origine process : BOT2_* (paper_v2) vs BOT2V6_* (Brain-V6)

**Fix applique 19/05 nuit** :
1. Ajout lecture FLATTEN_2_*.flag dans `mia2_brain_v6_databento.py` boucle run() avec convention partagee (process avec position traite + delete, sinon LAISSE)
2. Modif `databento_paper_trader_v2.py:3640-3673` : NE PAS unlink defensif si `self.positions[sym] is None` (regression corrigee)
3. TTL flag 60s ajoute dans LES DEUX (review code-reviewer BLOQUANT) pour eviter flag orphelin sur "Flatten all"
4. 4 nouveaux codes log catalog (BOT2V6_FLATTEN_MANUAL_EXECUTED/EXCEPTION + BOT2/BOT2V6_FLATTEN_MANUAL_FLAG_STALE)

**Action immediate 19/05 23:05** (avant fix) :
- Stop-Service MIA-Brain-V6 → backup state_v6.json → Python clear `open_by_symbol={}` → Start-Service MIA-Brain-V6
- Verifie 23:05:03 UTC : open_by_symbol vide, updated_iso normal = service ecrit nominal
- Trade fantome debloque sans perte $$ (broker etait deja flat)

**Reviewed** : Jackson (constat empirique) + code-reviewer (verdict GO-AVEC-RESERVES, 3 reserves : BLOQUANT TTL traite, RECOMMANDE banner stale + pytest non traites)

**Categorie incrementee** : VALIDATION_MISS (5+ occurrences cumulees, deja en memoire dediee `feedback_validation_miss_patterns.md`)

---

### 2026-05-19 13:20 (10) - [DEPLOY_UNSAFE + VALIDATION_MISS] Bug ladder Bot 3 SL fantome + kill_switch incomplet sur _bot3_positions

**Contexte** : Bot 3 Phase 1b ladder ACTION deploye sur paper_v2. Quand un trade NQ atteignait MFE >= 100t (palier 1), le bot ENVOYAIT cancel ancien SL + send nouveau SL palier (lock +60t), MAIS Sierra Chart ignorait silencieusement les 2 messages DTC. Resultat : SL "affiche" sur dashboard = 28910 (virtuel), SL reel broker = 28792 (initial 108t). Quand le marche redescendait sous 28910 sans toucher 28792, le trade timeout-fermait a perte au lieu du lock attendu.

**Trades affectes (19/05) confirmes empiriquement** :
- 09:10 NQ BUY entry=29008, MFE peak=127t, ladder palier 1 attendu lock +$60, reel = TIMEOUT -$93
- 12:12 NQ BUY entry=28900, MFE peak=116t, ladder palier 1 attendu lock +$60, reel = TIMEOUT -$84
- **Perte cumulee jour : -$177 + opportunite manquee +$120 = deficit -$297**
- Sur 30j stats actuelles +$652, le vrai PnL ladder-correct pourrait etre +$1500-2500 (estimation prudente +$500 gain manque)

**5 bugs imbriques (convergence audit Jackson + agent code-reviewer)** :

1. **`cancel_order` faux positif** (`BOT/dtc_connector.py:676-729`) : retourne True meme sans ServerOrderID dans tracking → Sierra ignore silencieusement le Type 203. Viole `orphan-prevention.md` regle "Cancel sans ServerOrderID = IGNORE silencieusement".

2. **MFE retroactif sur bar contenant entry** (`databento_paper_trader_v2.py:_bot3_update_mfe_mae`) : 08:39:53 (1 sec apres fill) log mfe=127t — bar age_sec=1013s = bar vieille de 17 min, donc high pre-fill compte dans MFE → palier 1 declenche faussement.

3. **Pas de tracking `new_sl_cid` dans `_bot3_cid_index`** : apres send STEP C du modify SL, code n'enregistre pas le nouveau ClientOrderID → `_bot3_handle_dtc_fill` ne sait pas router le fill SL si jamais Sierra l'avait accepte.

4. **Pas de verify Type 300 OPEN_ORDERS post-modify** : code suppose `send` TCP OK = SL actif broker. Faux pour STOP orders rejetes (violation regle R9 orphan-prevention.md).

5. **Race condition T+1s bracket init / palier 1** : palier 1 declenche en 1 sec (8:39:53 → 8:39:54) alors que bracket SL initial vient d'etre envoye. `BOT3_LADDER_SL_MODIFIED` emis avant que ServerOrderID ancien SL soit propage de `_recv_loop`.

**BUG BONUS DECOUVERT pendant revert** (categorie VALIDATION_MISS) :

6. **`kill_switch` flatte `self.positions` mais PAS `self._bot3_positions`** (`paper_trader_v2.py:3110-3119`) : la boucle iter `for sym in SYMBOLS: if self.positions[sym]:` couvre **Bot 2 V6 tracking** mais ignore le tracking dedie Bot 3. Quand `STOP.flag` global est cree, kill_switch retourne `BOT_KILL_SWITCH_ACTIVATED n_closed=0` + `BOT_SHUTDOWN` sans flatten les positions Bot 3 → orphelins potentiels si Bot 3 avait des positions ouvertes au broker Sim1.

**Verifie 19/05/2026 13:20 UTC** : STOP.flag cree, kill_switch active 2x (n_closed=0 chaque), positions Sim1 verifiees via `flatten_bot.py --bot 3` = etaient deja flat par coincidence (positions naturellement closed avant le STOP). MAIS architecture buguée = bombe a retardement pour incidents futurs.

**Cause racine consolidee** :
- DEPLOY_UNSAFE : Phase 1b ACTION ladder deploye sans test verify post-modify (regle R9 orphan-prevention.md ignoree)
- VALIDATION_MISS : kill_switch jamais audite sur Bot 3 path (tracking dedie ignore dans la boucle flatten)
- Convergence avec ancien incident 04/05 H6 (TradeAccount=Sim3 hardcode) : meme pattern "send DTC OK = effet broker garanti" sans verify

**Action immediate prise (19/05)** :
1. STOP.flag global cree → kill_switch shutdown bot
2. `flatten_bot.py --bot 3` execute sur Sim1 = verify positions flat (etaient deja)
3. `nssm set MIA_BOT3_LADDER_MODE=OBSERVE` (vs ACTION) → ladder log-only, ne touche plus au SL broker
4. STOP.flag removed + Start-Service paper_v2 → bot tourne nominal en mode safe
5. Bouton FLATTEN dashboard ajoute (per-trade, owner-only) `POST /api/admin/bot/{bot_id}/flatten/{symbol}` → Jackson peut flatten 1 trade ou tout un bot d'un clic, sans depencer du kill_switch buggué

**Lecons** :
1. **Toute action DTC critique (cancel/modify/send) DOIT avoir verify Type 300 post-action** avant de mettre a jour le state interne (cf regle R9 orphan-prevention.md, deja documentee mais ignoree en Phase 1b)
2. **`cancel_order` DOIT retourner False** si pas de ServerOrderID dans tracking (caller doit pouvoir detecter echec)
3. **MFE init = -inf** au boot/recovery, jamais recompute retroactif depuis bar pre-fill
4. **Race condition palier <T+10s** mitigee par `ladder_min_age_seconds=10` config minimum
5. **Kill_switch DOIT iterer sur TOUS les trackings de positions** (self.positions + self._bot3_positions + futurs trackers)
6. **Backup defense** : bouton FLATTEN dashboard granulaire (per-trade) = filet de secours quand le kill_switch ne suffit pas

**Trigger prevention** :
- Avant tout deploy ladder/scale-out/BE ACTION : sequence test obligatoire = (a) shadow OBSERVE J+7 logs comparison, (b) backtest 30j "ce qui se passerait sans bug", (c) verify Type 300 systematique
- Toute modif `_check_stop_flags`/`kill_switch` : grep tous les `self.*positions` du fichier + iterer chacun
- Bouton FLATTEN dashboard owner-only doit etre testable pre-incident (sandbox Sim1 vide)

**Fix applique aujourd'hui** :
- Revert ladder mode OBSERVE (immediate, deploye 13:25 UTC)
- Bouton FLATTEN per-trade dashboard (immediate, deploye 16:30 UTC, v=137)
- INCIDENT_LOG entry (cette entree)
- CHANGELOG entry deja ecrite (DOCS/BOT_CHANGELOG.md 19/05 IB_NARROW THRESHOLD entry)

**Fix a livrer (Phase C)** :
- `paper_trader_v2.py:3110-3119` : ajouter boucle `for sym in SYMBOLS: if self._bot3_positions[sym] is not None: self._bot3_close_position(...)` (CRITIQUE, prevent orphelin futur)
- `dtc_connector.py:cancel_order` : retourne False si pas de SID
- `databento_paper_trader_v2.py:_bot3_modify_sl_via_dtc` : verify Type 300 post-send, restore ancien SL si fail
- `_bot3_cid_index` : register new_sl_cid post-modify
- `bot3_config.py` : `ladder_min_age_seconds = 10` (defense race)
- `_bot3_update_mfe_mae` : skip bar contenant entry_ts

**Reviewed** : Jackson directive "STOP LES 3 BOT PUIS REVERT MAINTENANT" 19/05 13:20 + audit code-reviewer (separe) + self-diagnostic logs paper_v2.

**Liens** :
- CHANGELOG : entry 19/05 IB_NARROW (separate)
- Memory : `feedback_log_debug_protocol.md` (4 etapes diagnostic logs)
- Regle : `.claude/rules/orphan-prevention.md` (sequence anti-orphelin V2 R9)
- Bouton FLATTEN code : `CORE/flatten_bot.py` + `DASHBOARD/api/admin_routes.py:/api/admin/bot/{id}/flatten/{sym}`

---

### 2026-05-19 16:00 (9) - [VALIDATION_MISS] Seuil `IB_NARROW_THRESHOLD = 0.40` copie de C++ sans verifier convention Python

**Contexte** : Implementation `phase_b_v6_extras.py` (port Python feature `trend_day_probability`) reproduisait la formule C++ DMP_Transform.h:1316-1325 incluant `if (ib_range_atr < 0.40)`. Constante recopiee telle quelle dans Python sans verifier convention.

**Ce qui a mal tourne** : Convention C++ = `ib_range_points / atr_session_points` (ratio fractionnaire, range typique 0.3-0.8). Convention Python `phase_b_rolling_inputs.py:141` = `ib_range_ticks / atr_1min_ticks` (ratio multiple, range observe ES mean=21.7 / NQ mean=30.8). Seuil 0.40 jamais atteint -> critere `ib_narrow` (+0.30) inactif -> `trend_day_probability` plafonne 0.5 (au lieu max 0.65) sur 100% bars.

**Impact** : Feature critique input `regime_engine` (consommee par Bot 2 V6 -> regime_actionable) defaut 0.5 unique sur 100% bars. Vote TREND vs RANGE incomplet. Bug present depuis creation du module (audit code-reviewer 19/05 ante meridien).

**Cause racine** :
1. Recopie cross-langage de constante numerique sans verifier l'unite/convention du denominateur
2. Test inline `_test_trend_day_probability` utilisait des valeurs synthetiques `[0.30, 0.50, 0.30]` < 0.40 -> tests PASS mais ne testaient PAS la realite des donnees empiriques
3. Pas de sanity check post-build `trend_day_probability.nunique() >= 5` sur regen pilote

**Lecon** :
1. Toute constante copiee d'un autre langage doit etre validee empiriquement contre la distribution observee de l'input
2. Tests unitaires synthetiques ne remplacent PAS une verif distribution post-build (asserts sur unique values / mean / max)
3. Documentation explicite des differences de convention quand meme nom est partage entre 2 langages (`IB_NARROW_THRESHOLD` C++ != `IB_NARROW_THRESHOLDS` Python)

**Trigger prevention** :
- Toute formule portee C++ -> Python : grep tous les denominateurs (atr, range, vwap) + verifier l'unite (ticks/points/pct)
- Toute fonction utilisant un seuil "absolu" : ajouter sanity check post-build (nunique, mean dans bornes, % bars activation)
- Si meme nom partage C++/Python pour un seuil de meme intention semantique mais convention differente : suffixer `_PYTHON_CONVENTION` ou commentaire bug history explicite

**Fix applique** (`CORE/phase_b_v6_extras.py:50-69, 144-148`) :
- `IB_NARROW_THRESHOLD = 0.40` -> `IB_NARROW_THRESHOLDS = {"ES": 15.0, "NQ": 22.0, "MGC": 15.0}` calibre p25 empirique
- `add_trend_day_probability` lookup `IB_NARROW_THRESHOLDS.get(symbol, IB_NARROW_THRESHOLD_DEFAULT)`
- Test TDD nouveau `test_per_symbol_threshold_es_vs_nq` isole le critere narrow ES vs NQ
- Validation regen 10j 21-30/04 : 7 valeurs distinctes (0.0 -> 0.65), max 0.65 atteint 7.4% ES / 10.1% NQ, ib_narrow activation 27.3% ES / 29.7% NQ

**Consommateurs legacy clarifies** (3 modules avec convention different non-touches) :
- `CORE/rolling_features.py:281` `ib_range_atr < 0.40` -> column `ctx_trend_day_score` ABSENTE du V4 pure (confirmation grep) -> DEAD CODE Option C, garde pour V3 legacy
- `CORE/dalton_features.py:421` `ib_range_atr < 0.3` -> meme statut, DEAD CODE V4 pure
- `CORE/ib_recalc.py:24` `IB_NARROW_RATIO = 0.35` -> import seulement par `mia_bench.py`, `mia_sim.py`, `dataset_builder.py`, `test_all.py` (pipeline V3 DMP JSONL), DEAD CODE V4 pure

**Reviewed** : code-reviewer (GO-AVEC-RESERVES post-fix) + market-analyst (GO-AVEC-RESERVES post-fix, reco phase observation 1 mois) + self (grep cross-langage convention).

**Liens** :
- CHANGELOG entry du jour pour ce fix (DOCS/BOT_CHANGELOG.md)
- Memory `feedback_context_miss.md` (pattern : verifier convention avant porter formule cross-langage)
- C++ reference : `CPP/MIA_REFACTORED/DUMPER/DMP_Transform.h:1316-1325`

---

### 2026-05-19 03:30 (8) - [VALIDATION_MISS] Zombie trade RECOVERED_TIMEOUT fausse stats dashboard

**Contexte** : Apres deploy Phase 4d shadow mode (15:16 UTC), restart MIA-DataBento-Paper-V2. Service ancien (PID 122476) killed alors qu'une position NQ SHORT etait ouverte cote broker Sim1 (entry 29294.25). Nouveau service (PID 32844) detecte la position via `_bot3_recover_open_positions` mais SANS tracking interne (level/scenario/entry_ts perdus).

**Ce qui a mal tourne** : trade marque `level="_RECOVERED_BOOT_"` + `action="RECOVERED"` + `mfe=0/mae=0`. Bot ne peut PAS gerer (pas de trailing, pas de SL move). Attend juste timeout 60min. A 19:16:24 UTC, fermeture mark-to-market a 28966.25 = **+$1968 par chance** (marche a bouge favorable). PnL aurait pu etre -$1968 ou pire.

**Impact** : Dashboard affichait stats today PnL +$1364 (incluant +$1968 fake). 30j PnL +$4378 gonfle. **Stats edge analysis biaisees** (chance non-reproductible compte comme edge).

**Cause racine** : 
1. Protocole restart sans check positions ouvertes prealable
2. `_bot3_recover_open_positions` cree trade zombie sans flatten immediat
3. Filtre dashboard `_iter_trades_from_files` n'excluait pas les RECOVERED_TIMEOUT (precedent fix 13/05 ne filtrait que pnl_ticks=None, mais aujourd'hui pnl_ticks=2022 passe au travers)

**Lecon** : 
1. Tout trade marque `_RECOVERED_BOOT_` / `RECOVERED_TIMEOUT` / `action=RECOVERED` = NON-EDGE = exclu des stats
2. Pre-restart paper_v2 : verifier 0 positions ouvertes via `list_open_orders_bot3.py` ou DTC query
3. `_bot3_recover_open_positions` doit flatten immediatement (P0 fix Phase 4d2)

**Trigger prevention** :
- Avant restart paper_v2 (ou tout service avec positions) : `ssh ... "list_open_positions"` + attendre EOD si positions ouvertes
- Tout fix recovery : flatten immediat zombie au lieu de timeout
- Dashboard data_reader exclut les 4 markers (level/outcome/action/exit_reason)

**Fix applique** (commits a suivre) :
- `DASHBOARD/api/paper_tracker.py:_iter_trades_from_files` : skip si `level=="_RECOVERED_BOOT_"` OR `outcome=="RECOVERED_TIMEOUT"` OR `action=="RECOVERED"` OR `exit_reason=="RECOVERED_TIMEOUT"`. Filtre applique a TOUS les consumers (stats_today, stats_7d, stats_30d).
- SCP `paper_tracker.py` vers VPS + restart MIA-Dashboard. Effet immediat sur stats live.

**A FAIRE Phase 4d2 (P0)** :
- `CORE/databento_paper_trader_v2.py:_bot3_recover_open_positions` : ajouter flatten immediat zombie + emit BOT3_RECOVERED_ZOMBIE_FLATTENED CRITIQUE
- Creer `.claude/rules/deploy-protocol.md` : check positions ouvertes avant restart

**Reviewed** : Jackson (directive "SUPPRIME LES DES DONNER ON VEUX DES STATE REEL") + self-diagnostic confirme via grep VPS logs.

---

### 2026-05-18 23:30 (7) - [CONTEXT_MISS] NSM T17 RANGE_RESPECTED formule semantiquement fausse

**Contexte** : Apres fix (6) atr_intraday, T17 reste a 0 occurrences sur 14919 bars ES Mai (S07/S08 RANGE_* scenarios = 0). Audit market-analyst pointe la formule actuelle `ib_range / atr_daily < 1.2` qui mesure "IB etroit en absolu", PAS canon Dalton MOM Ch.9 "Day Type Recognition" qui dit Range Day = prix oscille DANS l'IB toute la session.

**Ce qui a mal tourne** : `bot3_narrative_state_machine.py:603-610` testait `ib_range/atr<IB_RANGE_ATR_MAX(1.2)` :
- Empirique ES batch : ratio mean=5.24, seuil <1.2 capture 0.31% des bars
- + state guard OPEN_ROTATION (71 cas observed) + ib_complete (53.5%) + inside_va (64.4%)
- Intersection complete = 0 cas en 11 jours -> RANGE_RESPECTED never fires

**Cause racine** : confusion entre 2 metriques semantiquement opposees :
- "IB etroit en absolu" (formule actuelle): mesure si l'IB est petite vs ATR daily. Rare et indirectement lie au Range Day.
- "Prix oscille DANS l'IB" (canon Dalton): mesure si le price stays inside IB without breakout. C'est la vraie definition Range Day.

**Lecon** : avant calibrer un seuil quantitatif, valider que la **formule reflete le canon**. Sinon le seuil sera tune-to-fit (Pattern 11 V1).

**Fix applique** (commits a suivre) :
- T17 nouvelle formule : `not ib_broken_up AND not ib_broken_dn AND bars_since_BOS > 90`
- State guard elargi : {OPEN_ROTATION, TREND_UP, TREND_DOWN}. Garde-fou anti-cycle TREND<->RANGE = bars_since_BOS > 90 (canon Dalton "range confirme apres consolidation prolongee", evite flip immediat).
- IB_RANGE_ATR_MAX deprecated (kept pour back-compat imports).
- Test calibration : seuil 30 cannibalise EXHAUSTION (S10 257->2 = perdu), seuil 90 preserve tout (S10 257->251, S07=81, S08=97).
- 3 nouveaux tests : `test_T17_blocked_if_ib_broken_up`, `test_T17_blocked_if_bars_since_BOS_too_recent`, `test_T17_from_trend_up_to_range_respected_after_long_consolidation`.

**Verification post-fix (replay ES Mai 11j)** :
- RANGE_RESPECTED state : 0 -> **137**
- S07 RANGE_support_long : 0 -> **81**
- S08 RANGE_resistance_short : 0 -> **97**
- S09 EXHAUSTION_TOP_short : 75 -> 52 (preserve)
- S10 EXHAUSTION_BOTTOM_long : 257 -> **251** (preserve, anti-cannibalisation BOS>90 valide)
- Tests : 67/67 PASS
- NQ Mai 11j : RANGE_RESPECTED=137, S07=80, S08=75 (cross-symbole OK)

**Phase 5 walk-forward maintenant possible sur** :
- S07 (PF 3.10 LEVEL_PROB) ES=81, NQ=80
- S08 (PF 7.96 LEVEL_PROB) ES=97, NQ=75
- S09 (PF 11.26 LEVEL_PROB) ES=52, NQ=26
- S10 (PF 4.93 LEVEL_PROB n=393) ES=251, NQ=4

**Trigger prevention** :
- Avant tout seuil quantitatif sur condition narrative, **mapper a une source canon** (Dalton/Wyckoff/Pruden). Si la formule ne reflete pas le canon = formule fausse meme avec seuil "calibrre".
- Cross-check empirique : compter les bars qui passent les sub-conds individuellement, puis intersection. Si intersection = 0 sur dataset reel = formule cassee.
- Anti-cycle multi-state : utiliser bars_since_BOS (proxy duree consolidation) comme garde-fou si on permet transitions cross-state.

**Reviewed** : Jackson (priorite absolue post-replay) + self-diagnostic + market-analyst review.

---

### 2026-05-18 22:00 (6) - [CONTEXT_MISS] NSM Bot 3 v2 utilise atr daily pour conditions par-bar 1-min

**Contexte** : STEP 1 (diagnostic distribution NarrativeState replay ES Mai 2026) revele que les states EXHAUSTION_TOP/EXHAUSTION_BOTTOM = **0 sur 11 jours** (14919 bars), bloquant Phase 5 walk-forward DSR sur S09/S10 (les 2 setups les plus solides empiriquement, PF 4.93 n=393 et PF 11.26 n=74 dans LEVEL_PROB_V4).

**Ce qui a mal tourne** : `bot3_narrative_state_machine.py:332` lit `atr = bar.get("atr")` et l'utilise pour T28/T29/T30/T31 (conditions par-bar 1-min). Or :
- Live ES `atr` = 17.5 pts (DAILY, ATR Wilder 14 jours)
- Live ES `atr_14m` = 4.375 pts (INTRADAY, ATR Wilder 14 bars 1-min)
- T28 demande `bar_range > 2 * atr` → seuil 35 pts ES sur barre 1-min = bar_range p99 batch = 7 pts = **inatteignable** (2/14919 cas)

**Cause racine** : melange d'echelles temporelles dans une seule variable `atr`. Le canon Pruden Ch.7 "buying climax = barre exceptionnelle du timeframe d'analyse" demande l'ATR du timeframe (1-min ici), pas l'ATR daily.

**Aggravant : semantique divergente live vs batch** :
- Live enricher : `atr` = daily Wilder + `atr_14m` separe
- Batch v4 enriched : `atr` mean=6.92 ES (echelle hybride), `atr_14m` ABSENT, `atr_14m_pct` present

**Lecon** :
1. Toute condition par-bar (T28/T29/T30/T31, T22-T27 Wyckoff recovery) DOIT utiliser un ATR d'echelle bar (atr_intraday/atr_14m).
2. Toute condition session-scale (T6/T7 OD vs open_cash, T14/T15 OTD, T17 ib_range/atr) DOIT utiliser un ATR daily.
3. Quand 2 echelles temporelles coexistent dans le code, ELLES DOIVENT ETRE NOMMEES DIFFEREMMENT (atr_daily, atr_intraday).

**Fix applique** (commits a suivre) :
- `bot3_narrative_state_machine.py` : ajout `atr_intraday` parsing (fallback atr_14m / atr_14m_pct*close / atr) au-dessus des transitions. T22-T27 + T28/T29 + T30/T31 utilisent maintenant atr_intraday. T6/T7/T14/T15/T17 gardent atr (daily) - leur scale est session.
- `replay_narrative_state_machine.py` : `_row_to_bar` passe atr_intraday calcule depuis atr_14m_pct * close.
- Docstring transition() documente la convention.

**Verification post-fix** (replay ES Mai 2026 11j) :
- EXHAUSTION_TOP : 0 -> **85** (+85)
- EXHAUSTION_BOTTOM : 0 -> **386** (+386)
- S09 EXHAUSTION_TOP_short scenarios : 0 -> **75** (+75)
- S10 EXHAUSTION_BOTTOM_long scenarios : 0 -> **257** (+257)
- WYCKOFF_UPTHRUST baisse 661 -> 30 (normalisation saine, T28 prend la place legitime)
- Trades V2 actionable : LONG=64 + SHORT=27 = 91 sur 11j = 8.3/jour (vs 5/jour V1).

**Trigger prevention** :
- Pour toute future modif d'un module qui melange echelles temporelles (1-min vs session vs daily), CREER DES VARIABLES SEPAREES NOMMEES PAR ECHELLE.
- Avant deploy une condition `X > N * atr`, verifier empiriquement quelle echelle d'atr est passee et p99 du ratio sur data reelle.
- T17 (RANGE_RESPECTED ib_range/atr) reste a fixer separement : utilise atr_intraday ?atr_session ? Investiguer dans STEP 2bis.

**Reviewed** : Jackson (priorite ABSOLUE post-replay 18/05) + self-diagnostic confirmant par bar live NQ/ES VPS.

---

### 2026-05-18 PM (5) - [PATTERN_11] Bot 3 v2 Phase 4abc MIRROR_SHORT DATA_MINING_TRAP self-inflicted

**Contexte** : Phase 4abc Bot 3 v2 livree avec 5 mirror SHORT levels TIER 1 (MQ_CALL_0DTE, IB_HIGH_SHORT, GEX_UP, VWAP_W_SD1U, PVAH_SHORT) pour symetrie LONG/SHORT objectif master plan sect 281. 176/176 pytest PASS, replay GO 9/9, commit bfa88d2 tag bot3v2-phase4abc-levels-symmetry.

**Ce qui a mal tourne** : reviews ULTRATHINK Tier 1 (market-analyst + code-reviewer) verdict **NOGO Phase 4d unanime**. 12 auto-findings perso confirmes (4 critiques + 4 importants + 4 mineurs) + 7 nouveaux agents.

**4 bugs CRITIQUES verifies empiriquement** :
1. **MIRROR_SHORT_TIER1 ZERO baseline empirique** : 5 levels tier=1 sans rej_/pf_/n_ (grep code confirme). Signature `DATA_MINING_TRAP` (incident 28/04 cf `feedback_data_mining_trap.md`).
2. **dist_col doublons** : IB_HIGH_SHORT et PVAH_SHORT ont SAME dist_col que IB_HIGH/PVAH TIER2_NEUTRAL existants. Risque double-fire mp_engine si Phase 4d itere les 2 dicts.
3. **tier=1 promotion abusive** : MQ_CALL_0DTE + IB_HIGH_SHORT marques tier=1 SANS N>=5000 (critere TIER 1 documente ligne 17-18 du module). Violation header.
4. **level_supports_symbol() asymetrie API** : ne lookup pas MIRROR_SHORT_TIER1 (lignes 587-590 hardcoded `(TIER1, TIER2, TIER3)`). Test empirique : `level_supports_symbol('MQ_CALL_0DTE', 'ES') = False` alors que MIRROR declare `symbols=[NQ, ES]`. Silent filter out signals.

**Killer fact non vu par auto-audit** : ligne 282 module **MQ_CALL baseline_rej_nq=33%** vs **MQ_PUT_0DTE rej_nq=57.5%** = asymetrie EMPIRIQUE 24 points documentee. J'ai cree MQ_CALL_0DTE tier=1 sur PRESUMPTION symetrie 57%. Refute par les propres donnees du module. Pruden Ch.7 : "Asymmetric supply/demand zones reflect long-term institutional positioning, not symmetric mean reversion".

**Cause racine** :
- Viole `feedback_backtest_before_gate.md` 17/04 : "Toujours backtest empirique (50 LOC) avant de coder un nouveau gate"
- Reproduit pattern incident 03/05 06:30 meta-labeler (infrastructure build pour edge inexistant, espoir validation Phase N+1)
- Tests PASS prouvent que le code compile, PAS la validite canon des decisions de design
- Bot 3 v1 a 80% LONG biais → solution "ajouter 5 mirror SHORT" est mecanique, pas canon (asymetrie marche US 1950-2026 documentee)

**Fixes appliques session 18/05 PM** :
- Suppression IB_HIGH_SHORT + PVAH_SHORT (doublons dist_col)
- Suppression MQ_CALL_0DTE (asymetrie 33%/57% empirique refute)
- Demote GEX_UP + VWAP_W_SD1U → tier=3 OBSERVE-ONLY (2 mirrors finaux au lieu de 5)
- `required_context: {phase_5_dsr_validated: True}` gate explicit
- Flag separe `BOT3_ENABLE_MIRROR_SHORT_OBSERVE=False` (default False jusqu'a Phase 5)
- Renomme dict `MIRROR_SHORT_TIER1` → `MIRROR_SHORT_OBSERVE`
- Refactor `_ALL_LEVEL_DICTS` central (fix Bug 12 + Bug 6 cache)
- `derive_nature_from_side('NEUTRAL') = None` (au lieu de structural, fix Bug 10 castrate 8 levels)
- `LevelNature = typing.Literal` (Enum strict, fix Bug 7 regression Phase 3 R5)
- INCIDENT_LOG entry (cet entry)
- IDEAS_BACKLOG MIRROR_SHORT Phase 5 dette tech documentee

**Lecons** :
1. Backtest empirique 50 LOC OBLIGATOIRE avant tout ajout level / scenario / gate (rule .claude/rules/critical-tasks-review.md critere 9)
2. Symetrie LONG/SHORT mecanique sans verifier asymetrie marche structurelle = data mining
3. Tier=1 doit etre verifie cumulativement (rej>58% + n>5000), pas mecaniquement attribue
4. API helpers level_supports_symbol et get_level_nature doivent itere mem set de dicts (`_ALL_LEVEL_DICTS` central DRY)
5. NEUTRAL ≠ structural : NEUTRAL = orderflow decide (7 scenarios legacy), structural = bilateral magnet sans bias
6. Le test "passe le pytest" ne suffit PAS - canon doit etre verifie par market-analyst Tier 1 review AVANT commit

**Trigger prevention** :
- Avant tout commit ajout level/scenario/gate : backtest empirique 50 LOC (vs spec)
- `tier=1` requires `n>=5000` AND `rej>58%` verifies dans la dict entry (assertion au load)
- `level_supports_symbol` + `get_level_nature` doivent partager `_ALL_LEVEL_DICTS` (DRY)
- `LevelNature` toujours Enum strict (Literal ou Enum class), jamais str alias

**Reviewed** :
- market-analyst (1.5/5 Dalton-Wyckoff-Steidlmayer-Lopez) verdict NOGO Phase 4d
- code-reviewer (2.75/5 code+threading+state+tests) verdict NOGO Phase 4d
- Auto-audit perso STEP 1-3 module-review-protocol.md (12 findings)

**Cross-ref** :
- `LOGS/reviews/REVIEW_BOT3V2_phase4abc_market_analyst_20260518.json`
- `LOGS/reviews/REVIEW_BOT3V2_phase4abc_code_reviewer_20260518.json`
- `feedback_data_mining_trap.md` (memory pattern reference 28/04)
- `feedback_backtest_before_gate.md` (memory rule 17/04)
- `feedback_pattern11_repetition_avoided.md` (memory 30/04)
- INCIDENT_LOG entry 2026-05-03 06:30 (meta-labeler DATA_MINING_TRAP precedent)
- `DOCS/IDEAS_BACKLOG.md` MIRROR_SHORT_OBSERVE Phase 5 dette tech

---

### 2026-05-18 PM (4) - [PATTERN_11] PlotTwistDetectors Phase 2 - 5 bugs critiques calibration symbol-blind

**Contexte** : Phase 2 PlotTwistDetectors + ScenarioValidator livre verdict GO PHASE 2 sur 7/7 criteres replay (114/114 pytest PASS). Reviews ULTRATHINK Tier 1 dispatch (market-analyst + code-reviewer parallele).

**Verdict convergent 2 agents** : GO-AVEC-RESERVES Phase 2 TRACKING + NOGO PHASE 3 sans fix R1-R3.

**5 bugs detectes** :

1. **R1 acceptance BOS instant** (market-analyst) : `detect_structure_break` fire sur close > swing + 2*tick SUR LA BARRE MEME. Dalton MOM Ch.7 exige 2-3 bars maintenus (acceptance TPOs Steidlmayer). ICT canonique require displacement candle + follow-through. Resultat : detecte sweep candidates = false BOS pile au sommet.

2. **R2 VOLUME_ANOMALY direction INVERSEE Wyckoff** (market-analyst + code-reviewer convergent) : code `close > open → direction = +1`. Pruden Ch.5 "Three Skills" definit explicitement buying climax = `close > open` (close encore plus haut) MAIS signal = BEARISH (vendeurs absorbants livrent → reversal imminent). Mon detecteur inverse la semantique exact. Phase 3 DirectionResolver consume direction → decisions a l'envers garanties.

3. **R3 severity non normalisee cross-symbol** (code-reviewer empirique avec script Python) : formules `/swing*0.001` + `/10000.0` + `/5.0` + `/3.0` toutes arbitraires et ES-only.
   - STRUCTURE_BREAK : ES swing=5000 → 0.600, NQ swing=22000 → 0.364, MGC swing=2200 → 0.909 (meme magnitude relative en ticks). Asymetrie 2.5x.
   - DIVERGENCE `/10000` : ES CVD 50-500K vs MGC 5-50K → severity MGC toujours <0.05 (jamais au seuil 0.3).
   Resultat : MGC sur-invalide systematiquement, NQ sous-invalide.

4. **R3bis tick_size=0.25 default viole `.claude/rules/tick-size-policy.md`** (code-reviewer) : `detect_structure_break(... tick_size: float = 0.25, ...)` + `scan_all(... tick_size: float = 0.25, ...)`. MGC tick=0.10 silent fallback. Acceptance 5x trop laxiste sur MGC.

5. **R8 last_BOS_dir couplage bullish/bearish** (code-reviewer) : 1 variable partagee → switch direction rapide en chop fire en alternance (BOS+ idx=10 → BOS- idx=15 → BOS+ idx=20). NSM oscille INVALIDATED <-> TREND_UP. Replay pollue.

**Cause racine commune Pattern 11 V1 inverse** :
- Calibrages avec constantes arbitraires sans citation canon (`/10000`, `/5.0`)
- Aucune normalisation par symbole (ticks, ATR, CVD baseline)
- Silent fallback tick_size = MGC oublie
- Tests passent car ils utilisent les memes valeurs hardcodees (pattern auto-referentiel deja documente PATTERN_11 NSM open_type 18/05 PM)

**Lecons** :
1. Severity formula doit etre cross-symbol invariante (ticks, ATR-mult, z-scores). JAMAIS de constante absolue arbitraire (`/10000`).
2. `tick_size` JAMAIS hardcoded en default, TOUJOURS pris du caller via `get_tick_size(symbol)` (rule `.claude/rules/tick-size-policy.md`).
3. Pour features cross-symbol critiques, tests pytest doivent inclure cas ES + NQ + MGC explicitement (pas tests unitaires ES-only).
4. Reviews ULTRATHINK avec script Python empirique > review code-only (code-reviewer a calcule les severities asymetriques explicitement = bug visible).

**Trigger prevention** :
- Avant tout commit feature severity/threshold : verifier formula invariante par symbole (run mental ES + NQ + MGC)
- Lint guard `tools/check_tick_hardcode.py` doit catch les defaults 0.25 hardcodes
- Tests pytest doivent inclure regression cross-symbol (ES + NQ + MGC) pour features sensibles tick/CVD

**Reviewed** : market-analyst (3.0 Dalton / 3.5 Wyckoff / 2.5 ICT / 2.0 Lopez) + code-reviewer (3 code / 3 threading / 4 state / 4 tests) verdict GO-AVEC-RESERVES Phase 2 TRACKING + NOGO PHASE 3 sans fix R1-R3 18/05 PM.

**Cross-ref** :
- `LOGS/reviews/REVIEW_BOT3V2_phase2_market_analyst_20260518.json`
- `LOGS/reviews/REVIEW_BOT3V2_phase2_code_reviewer_20260518.json`
- `DOCS/IDEAS_BACKLOG.md` (8 reserves trackees)
- Memory feedback a creer post-fix : `.claude/memory/feedback_bot3v2_severity_normalization_cross_symbol.md`

---

### 2026-05-18 PM (3) - [VALIDATION_MISS] NSM Bot 3 v2 trou couverture OAOR/ORR open_types non testes par replay

**Contexte** : Replay tracking-only NSM ES 5 jours (11-15/05/2026) post-fix Tier 1 reviews. Verdict initial GO (56/56 pytest PASS + bench p99=28us). Replay donne 15 transitions reelles sur 6817 bars, dont 9 sur 11/05 et **ZERO sur 14-15/05**.

**Ce qui a mal tourne** : market-analyst dispatch verdict NOGO sur 73% des jours non couverts : OpenType.OAOR_UP=8, OAOR_DOWN=9, ORR_UP=5, ORR_DOWN=6, UNKNOWN=0 → **aucune transition T6-T9 ne matche**. NSM coince en PRE_OPEN_NEUTRAL toute la session NY pour ces setups. Dalton MOM Ch.8 (Mind Over Markets) : OAOR = "highest confidence directional setup" — ignore par NSM.

ml-trainer cross-check confirme : coverage transitions ~20% (5-7 trigger codes sur 32). Tests pytest 56/56 PASS car ils testent UNIQUEMENT les transitions definies (selection biais). Aucun test sur OAOR/ORR.

**Cause racine** :
- Spec NSM (DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md) covers OpenType.OD_UP/OD_DOWN/OTD_UP/OTD_DOWN/OAIR mais OMET OAOR/ORR. C'est un OVERSIGHT de la spec, pas du code.
- Tests TDD ont valide ce que la spec demande, pas ce que la realite demande.
- Validation = self-referential : test code matches spec, mais spec incomplete vs marche reel.

**Lecon** : avant tests TDD sur un FSM narrative, faire :
1. Histogramme empirique des INPUTS sur 30 jours data live (open_type distribution)
2. Verifier que CHAQUE valeur observee a au moins 1 transition matchant
3. Si gap : completer spec AVANT d'ecrire les tests

**Trigger prevention** :
- Pour tout FSM consommant une feature categorical (enum) : audit empirique distribution AVANT lock spec
- "Couverture spec >= 90% des valeurs observees" comme critere bloquant avant pytest

**Reviewed** : market-analyst (NOGO empirique) + ml-trainer (NOGO methodo) 18/05 PM

**Cross-ref** :
- `LOGS/reviews/REVIEW_BOT3V2_narrative_state_machine_*_replay_20260518.json`
- `CORE/bot3_narrative_state_machine.py` T6-T9 (coverage gap OAOR/ORR)
- `CORE/game_changers.py:38-51` OpenType IntEnum
- Distribution observee 11 sessions mai : 9/11 sessions ont 2 valeurs open_type unique (bug pipeline V4 broadcast partial — cf entry suivante)

---

### 2026-05-18 PM (2) - [PATTERN_11] Pipeline V4 broadcast open_type partial sur session_date_trading

**Contexte** : Audit `DATA/V4_TEMP/ES_mai_v4_freshest.parquet` (mtime 17/05) revele 9/11 sessions ont >1 valeur unique d'open_type. Pipeline V4 cense broadcast une seule valeur par session (cf `CORE/build_dataset_v4_phase_b.py:325` `out_open_type.extend([int(ot)] * n_bars)`).

**Ce qui a mal tourne** : Frontiere de changement systematique a **04:00 UTC = 00:00 ET (minuit ET)** :
- Bars 22:00 UTC veille → 04:00 UTC jour D : open_type = 0 (UNKNOWN, valeur initiale)
- Bars 04:00 UTC → 21:00 UTC jour D : open_type = valeur classifiee
A 04:00 UTC : ib_high=NaN, ib_low=NaN, mais open_type devient non-zero. Implique que `classify_open_type` a recu inputs invalides ou que le broadcast n'est pas atomique.

**Cause racine probable** :
- Parquet buildé avec une vieille version du code (avant fix 14/05 v2 de `apply_game_changers`) qui groupait par `date_et` au lieu de `session_date_trading` complete
- OU build incremental qui a ecrase partiellement les bars

**Lecon** : pour features de niveau session (1 valeur/session via broadcast), AUDIT empirique de l'unicite par session apres CHAQUE build :
```python
assert df.groupby('session_date_trading')['open_type'].nunique().eq(1).all()
```

**Trigger prevention** :
- Ajouter validation `df.groupby(sdt).nunique() == 1` pour features broadcastees dans `quality_validator.py`
- Documenter que tout build V4 doit etre REGENERE quand fix de `apply_game_changers` change

**Impact sur NSM** : LIMITE — pendant session NY (13:30-20:00 UTC), open_type est correctement broadcaste (toujours >04:00 UTC). Donc T6-T9 voient la bonne valeur. Le bug affecte seulement les bars overnight (Asia/London partial).

**Action** : rebuild parquet ES/NQ mai 2026 avec fix 14/05 v2 du `apply_game_changers` LORS DE LA PROCHAINE Phase pipeline V4.

**Cross-ref** :
- `CORE/build_dataset_v4_phase_b.py:243-336` `apply_game_changers` (fix 14/05 v2 documente lignes 282-286)
- `DATA/V4_TEMP/ES_mai_v4_freshest.parquet` (a regenerer)

---

### 2026-05-18 PM - [PATTERN_11] NSM Bot 3 v2 open_type mapping hardcoded numerique vs IntEnum officielle

**Contexte** : Phase 1 NSM Bot 3 v2 (`CORE/bot3_narrative_state_machine.py`) avait pour but EXPLICITE d'eliminer Pattern 11 V1 (composite hardcoded). Tag bot3v2-phase1-nsm-foundation-20260518, 26/26 pytest PASS, bench p50=13.4us, presente comme GO interne.

**Ce qui a mal tourne** : Review market-analyst ULTRATHINK Tier 1 (verdict NOGO 3.25/5) a detecte que les transitions T6/T7 (OPEN_DRIVE_UP/DOWN), T8 (OTD), T9 (ROTATION) utilisent valeurs numerique hardcodees `open_type==0`, `==1`, `==3` alors que `CORE/game_changers.py:38-51` definit l'enum officielle `OpenType` :
- UNKNOWN=0, OD_UP=1, OD_DOWN=2, OTD_UP=3, OTD_DOWN=4, OAIR=7 (ce que spec appelle "Open Rotation")
- Code NSM matche les MAUVAISES valeurs. T6/T7 firent sur UNKNOWN, T8 sur OD_UP (inverse semantique), T9 sur OTD_UP (inverse).

**Comment ca a echappe aux 26 tests pytest PASS** : les tests `_make_ctx(open_type=0)` reutilisaient les memes valeurs hardcodees fausses. Tests valident le code MAIS PAS le contrat avec game_changers.py source de verite. Pattern auto-referentiel = bug invisible jusqu'a integration mp_engine.

**Cause racine** :
- **Pattern 11 V1 INVERSE applique au NSM lui-meme** : feature definie ET utilisee, mais mapping numerique faux non grep'd source code
- Test cree feature, code utilise feature, validation ne cross-check pas vs source officielle de la feature
- Spec NSM section "open_type values" listait 0/1/2/3 sans citation `game_changers.py:38` ni import enum
- Manuel de Jackson (MANUEL_EDGE_JACKSON.md) auto-load mais pas consulte avant ecriture transitions Dalton

**Lecon** : Avant tout mapping numerique d'une feature → logique decision :
1. Grep le code source de la feature (`grep -rn "OpenType\b" CORE/`)
2. Si IntEnum/Enum existe → IMPORTER l'enum, JAMAIS hardcoder l'int
3. Si pas d'enum → creer l'enum AVANT d'utiliser le numerique
4. Test doit utiliser l'enum aussi (pas la valeur int hardcoded) sinon validation auto-referentielle

**Trigger prevention** :
- AVANT toute transition basee sur feature numerique : `grep -rn "<FeatureName>" CORE/` pour trouver source
- Si feature numerique sans enum source → STOP, creer l'enum d'abord
- Test pytest doit importer et utiliser l'enum, pas la valeur int directement

**Reviewed** : market-analyst (NOGO 3.25/5) + Jackson directive 18/05 "PAS DE DETTE TOUJOUR CHOISIR LA SOLUTION LA LUS ROBUSTE ET STANDAR PRO"

**Cross-ref** :
- `LOGS/reviews/REVIEW_BOT3V2_narrative_state_machine_market_analyst_20260518.json`
- `LOGS/reviews/REVIEW_BOT3V2_narrative_state_machine_code_reviewer_20260518.json`
- `CORE/game_changers.py:38-51` (source de verite)
- `CORE/bot3_narrative_state_machine.py:~458, 468, 478, 485` (bugs B1)
- Memory `feedback_ia_traps_detection.md` (pattern 11 V1 origine)
- Memory `feedback_pattern11_repetition_avoided.md`

---

### 2026-05-18 12:30 - [VALIDATION_MISS] Hook V1 check_bot3v2_structure.py commit sans validation logique reelle

**Contexte** : Phase 1.0 quality stack Bot 3 v2 a livre 2 custom hooks pre-commit (check_bot3v2_structure.py + check_bot3v2_headers.py). Commit (current session) sans test de la LOGIQUE reelle des hooks, juste self-test surface "EXIT 0 / EXIT 1".

**Ce qui a mal tourne** : Jackson 18/05 12:25 a fait code review adversarial impitoyable du hook V1 et identifie 5 faiblesses serieuses :
1. **Substring match faible** : `if module_name not in structure_content` passe meme si module mentionne en "DEPRECATED" 2024 → faux GO permanent.
2. **Pattern docstring vs code incoherent** : docstring `bot3_(narrative|story|...)*.py` vs code `bot3_(narrative_|story_|...).*\.py$` → faux negatif silencieux sur `bot3_narrative.py` (sans suffixe).
3. Variable `missing` capturee pour rien.
4. Pas de fallback git si argv vide.
5. Pattern dupliquee pre-commit/script (pas grave mais doc).

**Ironie cruelle** : le hook etait CENSE empecher Pattern 11 V1 (silent fallback / convention non tenue). Il REPRODUIT le Pattern 11 V1 lui-meme = check faible avec docstring qui promet plus que le code ne livre.

**Cause racine** :
- Self-test SURFACE uniquement (EXIT codes), pas LOGIQUE (cas negatif vs positif vs edge)
- Pas teste les 3 cas obligatoires : module pas dans tracker, entry stale, status invalide
- Pas relu docstring vs code apres ecriture (cross-check inconsistance manquant)
- Commit precipite (4 fichiers groupes : __init__.py + conftest.py + 2 hooks) sans review separe par fichier

**Lecon** : pour CHAQUE nouveau script Phase 1+ Bot 3 v2 :
1. AVANT commit, tests OBLIGATOIRES :
   - cas negatif (input devrait fail) → verifier EXIT non-zero + message stderr utile
   - cas positif (input devrait pass) → verifier EXIT 0
   - edge case (input ambigu) → verifier comportement defini
2. Auto-review docstring vs code en relecture (5 sec scan) : promesses doc tient-elles ?
3. Si hook : tester avec fichier hypothetique qui DEVRAIT bloquer

**Trigger prevention** : si Claude commit un script `tools/check_*.py` ou `tools/validate_*.py` ou `tools/*lint*.py` :
- Faire au minimum 3 tests : NEGATIVE (fail attendu) + POSITIVE (pass attendu) + EDGE (case ambigu)
- Verifier coherence docstring/code (regex pattern, claims fonctionnelles)
- Cf cette entry comme exemple anti-pattern

**Reviewed** : Jackson (mode mentor adversarial) → V2 reecrite avec P1+P2+P3 fix immediatement, validation tests obligatoire avant commit V2.

**Cross-reference** : pattern identique a `feedback_validation_miss_patterns.md` (code defini sans emit reel grep cross-codebase).

---

### 2026-05-18 11:00 - [PATTERN_11_INVERSE] Bot 3 v1 catastrophique weekend 15-18/05 - features extraites mais pas utilisees decision

**Contexte** : Bot 3 paper trader v1 = 15 trades sur weekend 15-18/05, WR 13% (2 TP / 10 SL / 3 TIMEOUT). 14/15 LONG / 1 SHORT. Jackson critique : "ce n'est pas trader, le bot prend ses decisions sur 1 bar isolee comme s'il arrivait au milieu du film et speculait au doigt mouille".

**Ce qui a mal tourne** (3 agents converges : code-reviewer + market-analyst + Plan) :
1. **108 ctx writes** dans `bot3_context_analyzer.py` (50+ features extraites) vs **4 ctx reads** dans `bot3_decision_engine.py` hors safe defaults = Pattern 11 V1 inverse confirme empiriquement.
2. **13 niveaux LONG / 4 SHORT / 8 NEUTRAL** dans `bot3_level_definitions.py` = bias structurel 3:1 LONG mathematique par construction du dict, pas algorithmique.
3. **91.7% trades fires avec `regime.is_actionable=0`** (11/12 vendredi) = regime engine extrait, logue `BOT3_REGIME_OBSERVE` 600x/jour, mais IGNORE en decision (gate post-hoc avec bypass SIDAK/COMBO).
4. **Cooldown level = 5 bars** depuis TOUCH initial, pas depuis FAIL → MQ_PUT_0DTE re-fire 3x en 4h apres 2 echecs.
5. **Score = somme arithmetique sans ponderation direction** : `cross_delta_agree=0.8` en bear (ES+NQ vendent ensemble) BOOST le LONG +10 car le code regarde l'intensite, pas le signe.
6. **Tier 1 fixe (MQ_PUT_0DTE)** = aucun check orderflow positif requis avant LONG. Tier 2/3 NEUTRAL ont check `delta_pct > +0.20 + finish > +10 + n_big_bid > 0`. Asymetrie inverse : Tier 1 fragiles MOINS filtres que Tier 2.
7. **`cvd_5d_rolling` ghost feature** `bot3_context_analyzer.py:97` lit ancien nom, vrai nom Phase 3c-C = `cvd_5d_rolling_ffd` → fallback 0.0 silencieux depuis creation.

**Cause racine** : decision_engine = detecteur microstructure intra-bar habille en moteur decision. Cecite macro structurelle, asymetrie LONG mathematique. WR 13% = expression statistique attendue.

**Lecon** : Refonte fondamentale via **Narrative Layer** : StoryTrackers + NarrativeStateMachine + PlotTwistDetectors + ScenarioValidator + DirectionResolver. Levels deviennent NEUTRAL avec clef `nature=` parallele. Direction decidee par contexte. Kill switch `BOT3_USE_NARRATIVE_DIRECTION=False` rollback safety.

**Trigger prevention** :
- Avant deploy gate Bot 3, **verifier que TOUTES les features extraites dans context_analyzer sont utilisees dans decision_engine** (grep cross-codebase `ctx.get(feature_name)` count).
- Avant ajout niveau Tier 1, **valider DSR Lopez OR n>=200 par direction** (cf `feedback_data_mining_trap.md`).
- Avant fire LONG sur support en marche baissier, **verifier symetrie LONG/SHORT dans dict niveaux** (ratio LONG/SHORT cible 40-60%).

**Reviewed** : code-reviewer + market-analyst + Plan (3 agents converges)
**Chantier** : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md` (5 phases 5 semaines)

---

### 2026-05-18 04:30 - [VALIDATION_MISS] Roll detection streaming divergence batch (is_roll_day from-roll-onwards only)

**Contexte** : Phase 3c-C live_enricher porte `is_roll_day` batch -> streaming (CORE/build_dataset_v4_dmp_databento.py:749 -> CORE/enricher_chain.py:1697). Code-reviewer 18/05 03:00 a flagge divergence.

**Ce qui a mal tourne** (DOCUMENTE pre-deploy) : Le batch retro-flagge `is_roll_day=1` pour TOUTES les bars du jour ou un roll s'est produit (incluant les bars AVANT le roll dans la session, via `groupby(date).transform("max")`). Le streaming ne peut pas savoir en avance qu'un roll va arriver dans la session, donc `is_roll_day=1` n'est emis qu'a partir de la bar du roll jusqu'a fin session.

**Cause racine** : conversion algorithme "EOD broadcast" -> "running streaming" impossible sans lookahead.

**Lecon** : Pour roll detection, si Bot 2 V6 ou Bot 3 utilise `is_roll_day` en gate, il aura une vue partielle des bars roll-day du matin. Faible impact car features = rare events (rolls quarterly ES/NQ, mensuel GC).

**Trigger prevention** : Quand on porte batch -> streaming, identifier le pattern "EOD broadcast" (transform/groupby) et documenter divergence acceptee dans CHANGELOG + code comment. Cf code commentaire CORE/enricher_chain.py:1675-1679.

**Reviewed** : code-reviewer (18/05 review Phase 3c-C verdict GO-AVEC-RESERVES finding #4 "VRAI mais ACCEPTABLE")

---

### 2026-05-17 19:00 - [VALIDATION_MISS] Ghost feature names brain_v6 + entry_quality_gate (2 gates morts depuis creation)

**Contexte** : Audit Etape 3 Bot 2 V7 (mapping rules -> features V4 enriched). Cross-check empirique parquet mai 2026 + grep code brain_v6/entry_quality_gate.

**Ce qui a mal tourne** : Bot 2 V6 lit dans son code des features sous des noms qui **N'EXISTENT PAS** dans le parquet V4 enriched depuis sa creation :
1. `mia2_brain_v6_databento.py:1582-1583` lit `dist_big_ask_nearest_up` / `dist_big_bid_nearest_dn` → vraies cles V4 = `dist_big_ask_nearest_pct` / `dist_big_bid_nearest_pct` (sans suffix `_up/_dn`)
2. `entry_quality_gate.py:128` lit `cvd_bar_delta` → vraie cle V4 = `delta_bar`

**Effet** : Gate BIG_ORDER_OPPOSITE 100% MORT (jamais tire, .get() retourne None systematiquement). Gate ENTRY_QUALITY degrade (momentum_5b seul, cvd contra ignore).

**Preuves empiriques** :
- Funnel V6 EOD 5 jours (11-15/05) : 0 emit `v6_big_ask_at_price` / `v6_big_bid_at_price` (gate jamais bloque un trade)
- Backtest historique "+$155 / +0.078 PF" annonce CHANGELOG 05/05 = artefact d'autres filtres coincidents
- Backtest "104 trades 32.7% bloques PnL -1803$" entry_quality = artefact momentum_5b seul

**Cause racine** : noms inventes au code time sans cross-verification du schema parquet V4. Pas d'AssertionError car `.get()` silent fallback None. **Pattern COMMENT_FALSE** : commentaire ligne 1578 dit "Source : bar_row_dict.dist_big_ask_nearest_up" → mensonge operationnel depuis ~10 jours.

**Lecon** : `.get("ghost_name")` retourne None silencieusement. Pour features critiques, utiliser pattern `bar[key]` (KeyError loud) ou assertion debug-mode au boot.

**Trigger prevention** :
1. **Fix applique** : 2 LOC change (commit + SCP + restart MIA-Brain-V6 done 17/05 19:00)
2. **Pattern detection** : grep `\.get\(.dist_big_|cvd_bar_delta` dans tout CORE/ pour confirmer plus de ghost
3. **Tool** : `tools/audit_feature_names_in_code.py` (BACKLOG) qui scanne tous les `.get("string")` et verifie presence dans schema v4 enriched
4. **Tests** : ajouter test boot brain_v6 qui charge 1 bar v4 + verifie que toutes les features lues par les 3 gates V6 sont presentes (assertion non-None)
5. **Regle CLAUDE.md** : a chaque ajout gate utilisant feature V4, CONFIRMER nom via grep parquet schema AVANT commit (pas seulement copy/paste depuis spec C++)

**Cross-reference** : `feedback_validation_miss_patterns.md` (4+ occurrences, escalation memoire dediee), `feedback_ia_traps_detection.md` (pattern 11 cousin = "feature qui semble exister mais morte").

---

### 2026-05-17 09:30 - [DEPLOY_UNSAFE] sys.path BOT/ shadow CORE/ : ImportError BLOCKED_COMBOS_BOT3

**Contexte** : deploy VPS Phase 1.7b + 1.7d Bot 3 v2. SCP 6 fichiers CORE/ + nssm restart MIA-DataBento-Paper-V2. Service en SERVICE_PAUSED apres restart (crash loop).

**Ce qui a mal tourne** : `databento_paper_trader_v2.py:50-51` :
```python
sys.path.insert(0, str(ROOT / "CORE"))   # CORE inserted en 0...
sys.path.insert(0, str(ROOT / "BOT"))    # ...puis BOT inserted en 0 = BOT prioritaire !
```
Python charge `BOT/bot3_config.py` (12/05 vieux, sans BLOCKED_COMBOS_BOT3) au lieu de `CORE/bot3_config.py` (17/05 a jour). ImportError → service crash + nssm restart loop. 1h debug avant detection via log stderr.

**Cause racine** : doublon code source non documente. `BOT/bot3_config.py` + `BOT/log_catalog.py` existent depuis ancien deploy (avant refactor `CORE/`). Tant que les 2 versions etaient identiques, le bug etait LATENT. Premier ajout `BLOCKED_COMBOS_BOT3` dans CORE/ uniquement → drift → import echoue.

**Lecon** : `sys.path.insert(0, ...)` x2 = la derniere insertion devient priorite. Pour multi-dirs source, utiliser `insert(0)` UNE seule fois (priorite) + `append` pour fallbacks. Et JAMAIS de doublons code source sans process de sync.

**Trigger prevention** :
1. **Fix permanent applique** : `databento_paper_trader_v2.py:50-51` -> CORE `insert(0)` + BOT `append` (fallback dtc_connector legitime).
2. **Linter** `tools/check_duplicate_modules.py` : detecte tout .py duplique CORE/ vs BOT/ avec comparaison hash. Run en CI/CD.
3. **Regle CLAUDE.md** : Bot 3 modules = CORE/ source unique. BOT/ deprecated pour Bot 3 (reste pour dtc_connector + autres bots).
4. **Process deploy** : verifier `dir CORE/X.py BOT/X.py` (alignement timestamps) avant restart service.

**Reviewed** : code-reviewer (audit avant + apres fix), Jackson directive "Option A + audit complet".

---

### 2026-05-17 06:30 - [VALIDATION_MISS] Phase 1.7d boost JAMAIS declenche en prod malgre tests 17/17 PASS

**Contexte** : implementation Phase 1.7d Bot 3 v2 (SWING_COLOR_BOOSTED, 11 combos confluence COLOR validees DSR Lopez 1.0). Code ecrit, 17 tests unitaires PASS + commit 1.7b deja fait (f7caf40).

**Ce qui a mal tourne** : code-reviewer dispatch post-code a flag le bug avant commit. Empiriquement confirme par backtest : confidence avg NQ Phase 1.7d = **56.5 IDENTIQUE a Phase 1.7b 56.5** sur 9785 trades -> les boosts +10 a +20 ne se sont JAMAIS declenches sur ~6000 trades cibles cibles attendus.

**Cause racine** : `bot3_decision_engine._compute_swing_color_consensus(side, ctx)` lit `ctx["dist_color_up_nearest_pct"]`, `ctx["dist_color_dn_nearest_pct"]`, `ctx["aggressor_imbalance"]`. MAIS `bot3_context_analyzer.analyze_context(bar)` ne populait AUCUNE de ces 3 features dans le `ctx`. En prod, `ctx.get(...)` retournait `None` -> classification toujours "NEUTRE" -> aucune cle dans `SWING_COLOR_BOOSTED` -> 0 boost emis. Pattern classique : tests unitaires injectent ctx synthetique avec features deja la, masquent la deconnexion bar->ctx.

**Lecon** : pour chaque feature derivee dans `decision_engine`, AJOUTER UN TEST INTEGRATION END-TO-END qui passe par `bar -> analyze_context -> evaluate_decision` (pas ctx inject). Verifier empiriquement aussi via backtest que la statistique de sortie change (ex: confidence avg) — sinon = code mort.

**Trigger prevention** :
1. Apres tout ajout de feature dans `evaluate_decision` qui lit `ctx[...]`, **GREP `analyze_context` pour verifier que cette cle y est populated**.
2. Apres backtest validation, comparer une metrique GLOBALE (confidence avg, n trades boost, etc.) entre baseline et nouveau code. Si identique -> investigation OBLIGATOIRE.
3. Defaut `_safe_float(..., 999.0)` pour distances (pas 0.0) sinon |0| < 0.05 = faux positif CONFLUENCE.

**Reviewed** : code-reviewer (dispatch post-code) + Jackson directive "missionne un agent pour review croise vos resultats".

---

### 2026-05-16 13:00 - [VALIDATION_MISS] Declaration success sur forme sans verifier fond

**Contexte** : refactor Option B etape 7 `replay_enricher_batch.py`. Smoke test 1 jour ES a produit 117 bars × 438 cols. J'ai declare "Architecture validee empiriquement" en regardant uniquement le SHAPE (nb bars, nb cols).

**Ce qui a mal tourne** : le code-reviewer a detecte un bug us/ns CRITIQUE : `df["ts_event"].astype("int64")` retournait des MICROSECONDES (dtype Databento `datetime64[us, UTC]`) traites comme nanosecondes -> trades window filtree sur 16h40 au lieu de 60s, VIX jamais joint (ts_event_ms = us//1M = epoch 1970), cascade pollution `delta_bar`, footprint, big_clusters, VIX features.

**Cause racine** : j'ai verifie la FORME (nb cols, format JSONL OK) mais pas le FOND (delta_bar/volume coherent, vix non-NaN sur RTH, mq_gex shape correcte). Le bug etait INVISIBLE dans le shape.

**Lecon** : "PASS sur shape != PASS sur fond". Pour tout module pipeline critique, valider EMPIRIQUEMENT le contenu via tests d'integrite (ratios cross-features, ranges plausibles, non-NaN sur features attendues).

**Trigger prevention** :
- Avant declarer "validation OK" sur tout output, **executer un script anti-triche** avec checks fail-loud
- Pour pipeline ML : verifier minimum (a) features clees non-NaN sur fenetre attendue, (b) ratios cross-features (trades/volume), (c) timestamps monotones, (d) ranges plausibles
- Voir `tools/verify_replay_batch_output.py` comme exemple template (10 checks fail-loud)
- Cf directive Jackson 2026-05-16 13:30 : "TOUJOURS VERIFIER LE FOND, TESTE SUR DONNEES REELLES, ANTI TRICHE ET BUG"

**Reviewed** : Jackson + code-reviewer (a flag NOGO + reco verif anti-triche)

## Format d'entree

```
### YYYY-MM-DD HH:MM — [CATEGORIE] — Titre court

**Contexte** : 2 phrases max (tache + etat projet)
**Ce qui a mal tourne** : description factuelle
**Cause racine** : source manquee (memoire/rule/fichier non lu)
**Lecon** : regle imperative generalisee
**Trigger prevention** : signal concret pour detection future
**Reviewed** : Jackson / agent-name / self
```

---

## Incidents (anti-chronologique)

### 2026-05-15 11:50 — [PATTERN_11] — game_changers streaming reset date_et vs batch groupby session_date_trading

**Contexte** : R3 Pass 4 test parite V4 oracle ES avril 2026. Premiere comparaison streaming vs V4 sur donnees reelles (vs synthetic tests TOOLS/test_engine_parity).

**Ce qui a mal tourne** : 43.8% drift open_type / 39.2% open_zone / 33.9% open_direction sur bars Asia evening (date_et=J-1, session_date_trading=J). Test synthetique passait 4/4, masquait le drift.

**Cause racine** : apply_game_changers (build_dataset_v4_phase_b.py:276) groupby session_date_trading + broadcast cash classification a TOUS bars de la session. add_game_changers_streaming (game_changers_streaming.py:105) reset state sur date_et change. Pattern V1 cousin V2 = batch utilise scope SESSION, stream utilise scope DATE_ET.

**Lecon** : tests parite synthetiques peuvent passer alors que V4 oracle detecte du drift. Tout sub-engine streaming dont la version batch utilise `groupby("session_date_trading")` DOIT aussi reset sur changement session_date_trading, pas date_et.

**Trigger prevention** : grep `groupby.*session_date_trading` batch_fn -> verifier que streaming reset cle correspond. Test V4 oracle obligatoire avant deploy LIVE reel (tests/test_live_enricher_parity_v4.py).

**Reviewed** : self + agent feature-engineer R3 verdict initial. Fix streaming = scope session dediee (IDEAS_BACKLOG section streaming-batch-alignment).

### 2026-05-15 11:30 — [PATTERN_11] — initialize_state warmup_from_v4 silent fallback (AttributeError @property)

**Contexte** : R2 Pass 4 fix seed warmup. Suite a FIX P0-2 (bars_df = @property read-only depuis deque), l'ancien code `state.bars_df = df` levait AttributeError silencieusement avale par `except: pass`.

**Ce qui a mal tourne** : branche warmup_from_v4=True morte depuis FIX P0-2 (13/05). Aucun warmup ne s'executait. Cold start scenario c (boot apres 10:30 ET) -> open_cash/price_1030 vides = UNKNOWN constant jusqu'a J+1 09:30.

**Cause racine** : refactor deque (FIX P0-2) a casse l'API setter de bars_df sans casser de test (tests existants utilisent append_bar, pas l'assignment direct). Pattern V1 silent cousin.

**Lecon** : tout refactor d'une API mutation doit etre accompagne d'un test couvrant le path qui dependait de l'ancienne API. Pas de `except: pass` sans `_emit_log`.

**Trigger prevention** : grep `except Exception:\s*pass$` partout (initialize/boot/warmup). Tout silent fallback doit avoir un log emit.

**Reviewed** : code-reviewer GO NET apres correction Pass 4 commit b79d138 + 6 tests TOOLS/test_r2_seed_warmup.py

### 2026-05-14 01:30 — [VALIDATION_MISS] — Distribution shift delta_div_buy streaming LOT 1 fire 60% vs batch < 15%

**Contexte** : Smoke test phase_b_plus_plus_trades_streaming sur vraies donnees ES 09/04/2026 (1380 bars, 482K trades). 0 crash mais delta_div_buy fire rate = 59.71% (824/1380). delta_div_sell = 25.00% (345/1380).
**Ce qui a mal tourne** : Stream LOT 1 detecte une "divergence delta" beaucoup trop souvent (60% des bars). En batch les divergences sont typiquement < 15% (rare event). Le pattern fired n'est pas exploitable comme signal binaire ML en l'etat.
**Cause racine** : Convention streaming LOT 1 calcule delta_div sur cumdelta intra-bar (oscillations frequentes avec ~350 trades/bar), batch utilise un contexte cross-bar plus stable. Divergence semantique INHERENTE, pas un bug.
**Lecon** : Tout sub-engine streaming avec features cross-state (delta_div, color, long_updown, sweep) doit etre flagge `distribution_shift` + ml-trainer review OBLIGATOIRE avant deploy live. PSR/DSR re-calcul sur features stream est non-optionnel.
**Trigger prevention** : Avant trade live, run train_lightgbm sur dataset streaming-built + check feature_importance pour `delta_div_*` features. Si SHAP rank diverge > 5 places vs batch, alarme + investiguer.
**Reviewed** : self + code-reviewer (verdict 9 sub-engines GO/GO-AVEC-RESERVES 14/05 00:30)

### 2026-05-14 01:00 — [PATTERN_11] — LOT 5 trapped_traders silent dependency on LOT 4 absorb (fixed)

**Contexte** : Code-reviewer audit Phase 3c semaine 4 sur 8 commits (LOT 1-6 phase_b_plus_plus + gold_phase_d + intermarket). P0 bloquant detecte sur LOT 5.
**Ce qui a mal tourne** : Si caller appelle `add_trapped_traders_streaming` SANS avoir appele `add_stack_absorb_streaming` avant, `near_resistance_level`/`near_support_level` absents du row -> silent fallback 0 -> `at_resistance`/`at_support` toujours 0 (Pattern 11 V1 silent silent fail).
**Cause racine** : Convention dict-passing entre sub-engines sans schema/contract explicite. Le code originel utilisait `out.get("near_resistance_level", 0)` sans verifier presence.
**Lecon** : Tout sub-engine streaming consommant la sortie d'un autre DOIT raise ValueError fail-loud au debut si dependance absente. Le silent fallback Pattern 11 = bug differe garanti en prod.
**Trigger prevention** : Tout nouveau sub-engine cross-state ajoute apres LOT 4 doit avoir `if "<key>" not in row: raise ValueError` au debut. Lint check possible.
**Reviewed** : code-reviewer (P0 #7) + fix self 14/05 01:00 + retest data reelle PASS

### 2026-05-14 23:00 — [SCOPE_CREEP] — Sessions_swings_lag liquidity_sweep divergence batch (lookahead swing_h) vs stream (lag-10 swing_h)

**Contexte** : Chantier 3 Phase 3b semaine 3, commit sessions_swings_lag_streaming.py (ebea05b). Code-reviewer audit identifie P0 sur convention sweep timing.

**Ce qui diverge** :
- Batch `liquidity_sweep_high_lag5` utilise `swing_h_price[i]` = ffilled depuis pivot detecte avec LOOKAHEAD (window centered [k-10, k+10] vu integralement)
- Stream utilise `state.last_swing_high.price` = dernier pivot CONFIRME a bar i (= avec lag-10, j+10 <= i requis)
- Stream a un swing_h_price PLUS ANCIEN -> break (high > sh) plus facile -> 4x plus de sweep fires (synth 11 batch vs 44 stream).

**Cause racine** : convention LAG-N inherente. Le batch peut savoir le futur. Le stream live ne peut pas. Donc impossible d'obtenir parite stricte sur les features qui CONSOMMENT swing_h/l_price.

**Lecon** : tout sub-engine streaming dont les features derivees consomment un swing/pivot price detecte avec lookahead AURA une divergence semantique avec batch. C'est la BONNE semantique pour live (= utiliser dernier pivot confirme). Mais il faut documenter le distribution shift ML.

**Trigger prevention** : avant deploy live sub-engines stream, identifier toutes les features qui consomment des prix de pivots/swings detectes avec lookahead. Lister explicitement dans la docstring du module + INCIDENT_LOG. Mandate ml-trainer review pour quantifier impact distribution shift (KS test feature par feature, comparaison batch vs stream sur dataset reel).

**Sub-engines concernes** (a date) :
- volume_profile (commit 0a6cf7b) : cur_vpoc batch constant vs stream running
- sessions_swings_lag (commit ebea05b) : sweep + dist_last_swing_*_pct + bars_since_*

**Reviewed** : code-reviewer (P0 detecte) + self (documentation + INCIDENT_LOG)

---

### 2026-05-13 14:30 — [SCOPE_CREEP] — Sub-engine #4 volume_profile divergence design batch (constant intraday) vs stream (running VPOC)

**Contexte** : Chantier 3 Phase 3b Mardi, implementation `add_volume_profile_features_streaming` apres sub-engines #1/#2/#3 termines avec parite atol=1e-9.

**Ce qui ne match pas** :
- Batch `add_volume_profile_features(df, trades_df)` : groupby session_date_trading sur trades_df ENTIER -> calcule VPOC UNE fois fin de session -> broadcast cur_vpoc CONSTANT sur 480 bars du jour.
- Stream live equivalent : VPOC doit etre disponible INTRADAY (bot utilise cur_vpoc comme reference contextuelle bar par bar). Donc running VPOC qui evolue a chaque nouveau trade.
- Consequence : parite row-by-row batch/stream IMPOSSIBLE sur features cur_vpoc/vah/val/pdh/pdl/inside_value_area/poc_migration_dir/8x dist_*_pct (= 14 features sur 16 du sub-engine #4 divergent intraday).
- Parite VRAIE uniquement sur LAST BAR de chaque session (running VPOC = final session VPOC).

**Cause racine** : design batch fait pour OFFLINE training (broadcast post-session). Design stream fait pour LIVE inference (running intraday).

**Lecon** : tout sub-engine qui DEPEND DE TRADES (pas seulement OHLCV par barre) a ce probleme. Decision design :
  A. Stream = running VPOC intraday + parite test "last bar of session" uniquement
  B. Stream = NaN jusqu'a fin session + frozen = feature inutile intraday
  C. Stream = running + batch refait en running mode (additive-only constraint = NO)

**Choix retenu** : option A. Stream produit running VPOC, test parite sur last-bar-of-session uniquement.

**Implication ML** : v4 dataset training utilise batch (cur_vpoc constant intraday). Live utilise running. **Distribution shift potentiel** sur features cur_vpoc-dependent. A mitiger par :
  - Option future : ajouter feature `cur_vpoc_running` (live-style) au batch (calcule en rolling cumulative sur trades_df) pour matcher inference.
  - Court terme : flag a Jackson, decision si re-train avec running ou continuer constant. ML-trainer review obligatoire avant deploy live.

**Trigger prevention** : tout sub-engine streaming qui depend de trades/cumulatif intraday declenche un audit "running vs frozen" + flag distribution shift. Ne JAMAIS deployer en live sans ml-trainer review du delta features intraday.

**Reviewed** : self (decision design en cours, validation ml-trainer obligatoire avant deploy production sub-engine #4)

---

### 2026-05-13 00:30 — [VALIDATION_MISS] — Fix dashboard Bot 3 stats 7j/30j deploye sans test empirique reel → crash TypeError

**Contexte** : Jackson screenshot section 7/30j vide Bot 3 → diagnostic → fix code-reviewer GO-AVEC-RESERVES → deploy VPS → restart → Jackson signale "ON VOIS TOUJOURS PAS DONNER DES TRADE LES REBRIQUE SON VIERGE".

**Ce qui a mal tourne** :
- `compute_stats_period(7, "*_databento_v3_trades.jsonl")` levait `TypeError: '>' not supported between instances of 'NoneType' and 'int'` ligne 198 : `t.get("pnl_ticks", 0) > 0`.
- Cause : Bot 3 v3 logge des trades `RECOVERED_TIMEOUT` (anti-zombie 2-stage boot) avec `pnl_ticks=null` + `pnl_usd=null`. Le `.get("pnl_ticks", 0)` retourne `None` (cle existe avec valeur null), PAS le default 0. Soustraction None > 0 → TypeError.
- Verification empirique post-fix : 69 trades total 7j, **12 avec pnl_ticks=null** (signal_id `RECOVERED_*`, `outcome: RECOVERED_TIMEOUT`), 57 numeriques.
- Endpoint `/api/paper_v3_state` levait 500 silencieusement → frontend `paperData.stats_7d` undefined → branche "Pas de donnees historiques" persistante apres "deploy reussi".

**Cause racine** :
1. **STEP 1-3 module-review-protocol saute** : j'ai lu le code (`compute_stats_period`) mais n'ai PAS execute le walk-through 3 scenarios + n'ai PAS fait test empirique sur les vrais fichiers `*_databento_v3_trades.jsonl` VPS AVANT deploy.
2. **Code-reviewer brief incomplet** : j'ai briefe l'agent sur la logique theorique (pattern glob, exclusion Bot 1/2, cache-bust) mais pas demande "y a-t-il des differences de schema entre `*_trades.jsonl` Bot 1 et `*_databento_v3_trades.jsonl` Bot 3 ?". Agent a valide la logique sans verifier schema concret. Faux negative du review.
3. **Feedback_pre_deploy_3_questions.md (24/04 soir) viole point 3** : "testé empiriquement sur data reelle ?" → NON.
4. **feedback_validation_miss_patterns.md (24/04)** : pattern recurrent, "verifier empiriquement que code/methode defini est REELLEMENT appele en prod". Pareil ici : j'aurais du run `compute_stats_period` localement avec data VPS clone AVANT SCP.

**Lecon** :
- **AVANT toute modif dashboard backend qui appelle une fonction existante sur un nouveau pattern de donnees**, exiger : test Python direct sur VPS via SSH `python -c "from ... import f; print(f(args))"` AVANT SCP + restart.
- **Brief code-reviewer doit inclure schemas concrets** : "Bot 1 trades.jsonl schema = X, Bot 2 schema = Y, Bot 3 schema = Z, diffs ?". Sinon review = validation logique deconnectee.
- **JAMAIS faire confiance a "deja en prod sur Bot 1/2 donc OK pour Bot 3"** sans verifier que les datasets de Bot 3 sont structurellement equivalents.

**Trigger prevention** :
- Tout deploy backend dashboard qui reuse une fonction sur nouveau pattern de fichiers → smoke test Python remote OBLIGATOIRE avant SCP.
- Si l'API plante apres restart : check `LOGS/errors/errors_*_dashboard.jsonl` derniers 10 lignes pour TypeError/KeyError → indication immediate schema mismatch.

**Reviewed** : self (mea culpa explicite). Fix supplementaire applique + re-deploy + test empirique cette fois OK (57 trades, WR 66.7%, PF 1.51, PnL +$1486.5).

### 2026-05-12 16:15 — [VALIDATION_MISS] — Bot 3 MGC integration : regression duplication bot3_config + dicts rollover MGC

**Contexte** : Integration Bot 3 Gold (MGC) deploy VPS aujourd'hui. 5 fix successifs apres reviews (R1+R2+R3) + 8 fichiers SCP + restart service. Service stable pid=10920 mais 0 events MGC observes.

**Ce qui a mal tourne** :
- Apres deploy initial, **7 restarts service consecutifs** (pid 3804, 5256, 8972, etc.) tous crashes avec `KeyError: 'MGC'` ligne 2193 `databento_paper_trader_v2.py` : `RB[sym].get("max_trades_per_day")`.
- Cause racine du crash : `RISK_BOT3` dict ne contenait pas la cle "MGC". Fix applique a `CORE/bot3_config.py` mais le service Python charge `BOT/bot3_config.py` (sys.path BOT en premier) qui n'avait PAS le fix → silent divergence 2 sources.
- Pattern miroir incident 11/05 deja documente (`feedback_bot3_data_source_v4_enriched.md` + memory `bot3_config duplication`).
- Apres sync forcee `BOT/` + `CORE/` (~25KB chaque, identiques hash), KeyError disparu mais **0 events MGC quand meme** : 0 BOT3_REGIME_OBSERVE, 0 BOT3_BAR_STALE (parquet stale 22h+), 0 BOT3G_DECISION_*. Code path skip MGC en silence AVANT `load_last_bar` ou apres sans emit.

**Cause racine** :
1. **Duplication non-protegee** : 2 sources de verite `bot3_config.py` (CORE/ + BOT/) sans symlink ni `__init__.py` partage. Sync manuelle SCP requise = drift garanti tot ou tard.
2. **Audit pre-deploy incomplet** : 5 cap dicts (RISK_BOT3, ATR_BASELINE, SYMBOL_CONFIG, MAX_DRIFT_TICKS, RiskManager.counters) ajoutes MGC en 2 rounds successifs (round 1 manque RISK_BOT3 + cap counters → KeyError, round 2 ajoute mais d'autres dicts pas verifies empiriquement).
3. **Manque test pre-deploy local** : Bot 3 lance localement avec SYMBOLS_BOT3=["MGC"] aurait detecte KeyError instantanement avant SCP.

**Lecon** :
- **Une seule source de verite** pour les configs partagees Bot. Soit `from CORE.bot3_config import *` partout (depreciate BOT/bot3_config.py), soit symlink dur. Sync 2-locations = pattern 11.
- **Grep cross-dicts** avant deploy : `grep -n '\\[sym\\]' BOT/*.py CORE/*.py | grep -v "def "` → enumerer TOUS les acces dict-par-symbole, verifier MGC present partout.
- **Smoke test local minimal** : `python -c "from BOT.databento_paper_trader_v2 import _bot3_poll_cycle; ..."` avec MGC en SYMBOLS_BOT3 → DOIT pas raise KeyError.
- **Run pid uptime gate post-deploy** : verifier J+10min PID stable + 0 PY_EXCEPTION_HOT_PATH avant declarer OK. Si exception → rollback immediat, pas patch successif.

**Trigger prevention** : avant tout deploy nouveau symbole sur bot existant :
1. Grep `dict.*sym` + `dict\[symbol\]` dans le bot file pour enumerer TOUS dicts par-symbol
2. Verifier les 2 locations (CORE/ + BOT/) ont les memes clefs (`diff CORE/bot3_config.py BOT/bot3_config.py`)
3. Test local smoke avec le nouveau symbole en SYMBOLS_BOT3 actif
4. Post-deploy : grep PY_EXCEPTION_HOT_PATH dans events 10min apres restart → 0 obligatoire

**Note ouverte** : pid 10920 0 events MGC depuis fix → cause secondaire a investiguer (probable `load_last_bar` retourne None sans emit OU MGC parquet path mismatch `.v.0` vs `.c.0` masque le bar stale).

**Reviewed** : self + Jackson (vérification empirique logs VPS post-restart) + code-reviewer R1+R2+R3 rounds pre-deploy.

### 2026-05-12 10:00 — [INVESTIGATION] — Cat A features cross-check 3 agents : verdict + plan

**Contexte** : Apres rebuild V4 enriched mai 2026 (Cat B 88.5%->36.3% NaN -52pp), Cat A features residuelles 100% NaN persistent. Dispatch 3 agents code-reviewer en parallele pour audit.

**Findings consolides (cross-check 3 agents + audit empirique VPS)** :

**1. atr_regime_zscore_60d** : Cause = `min_periods=13800 bars` rolling 60j × 1380 bars CME 24h, mais Phase B charge `load_v4_partition(month)` mois isole → jamais atteint. Mars/Avril ont 53.4% non-NaN (rolling devient valide a mi-mois), Mai 1109 bars vu en local par agent (faux : VPS 9977 bars post-rebuild). Verite : 9977 < 13800 quand mois isole. Fix : Option B reduire `min_periods` 4140 (3j) OU Option A cross-month load (architecture pipeline incremental). ETA 1h-4h.

**2. Roll features (`roll_phase`, `days_since_roll`, `bars_since_roll`)** : `detect_roll` cherche discontinuite `instrument_id` mais NQM26 actif depuis mi-mars → group_id=0 partout sur avril+mai → NaN. **Deja dans ML_EXCLUDE** (lignes 77, 322, 418 build_dataset_v4_dmp_databento.py). Pas impact bots, juste audit cosmetique. Fix Option A calendrier CME hardcode H/M/U/Z. ETA 2h BACKLOG basse priorite.

**3. MQ Lite RAW features** (`dist_mq_call/put/hvl`, `dist_gex_*`, `dist_blind_*`, `dist_1d_min/max`) : **MISSION INITIALE INCORRECTE**. Ces features sont **ABSENTES par DESIGN** (drop intentionnel post-normalisation en `_pct`). Les versions `_pct` sont les vraies features ML : **0% NaN sur la plupart, 22% sur `_call_0dte`/`_hvl_0dte` due a source MenthorQ null**. Seul vrai bug : `dist_mq_call_0dte` et `dist_mq_hvl_0dte` survivent au drop quand 100% NaN raw. Pollution colonnaire mineure. Fix : add a `MQ_COLS_TO_DROP` ligne 942 OU filter dans `add_pct_normalized_distances`. ETA 5 min.

**4. Long bars features (6 cols)** : Engine `phase_b_plus_engine.py` existe, `apply_phase_b_plus` orchestre correctement. **Vu empirique VPS post-rebuild** : `long_up_bar` (2628/9992 non-zero NQ) + `long_dn_bar` (2535) **OK**. MAIS `n_long_up_zones_active`, `dist_long_up_nearest_pct`, `n_long_up_cluster_*` **100% NaN** → `add_long_extension_lines` ne tourne pas OU ses colonnes ne sont pas mergees dans final parquet (write_partitioned bug). **Investigation engine fine necessaire**. Edge Jackson primaire impactee. ETA 1-2h investigation + fix.

**5. `im_ltr_slope_diff`** : **NON IMPLEMENTABLE pipeline V4 Databento**. `large_trader_ratio` est feature DMP Sierra (CFTC COT-like), pas Databento. Deja dans PROHIBITED_FEATURES ligne 321 avec commentaire explicite "100% NaN (large_trader_ratio non dispo Databento)". **Accept NaN definitif**. 0 effort.

**Critique mentor (Agent 1)** : Agent fait notion utile que les Cat A features `atr_zscore`, `roll_*` sont deja dans ML_EXCLUDE → impact ML/bots = NUL. Cosmetique audit seulement. Reformulation priorites :
- HAUTE : `n_long_*_zones_active` + `dist_long_*_nearest_pct` (Edge Jackson)
- MOYENNE : `atr_regime_zscore_60d` (utile filter regime mais marginal)
- BASSE : Roll features, MQ_0dte residuel (already ML_EXCLUDE / cosmetique)
- NULLE : `im_ltr_slope_diff` (accept NaN)

**Plan recommande** (par priorite) :
1. Investigation `add_long_extension_lines` engine — pourquoi 100% NaN apres apply_phase_b_plus ?
2. Quick fix Option B `atr_regime_zscore_60d min_periods=4140`
3. Backlog reste Cat A (roll, MQ_0dte residuel, IM)

**Validation J+1** : test 14:00 UTC `regime_actionable` pendant RTH. Si ressuscite >10% → Cat B fix suffit. Si toujours 0% → Cat A bloquants prioritaires.

**Reviewed** : self + 3 agents code-reviewer parallele (cross-check confirme cause racine 3 groupes Cat A) + empirique audit_long_bars_post_rebuild.py.

### 2026-05-12 09:20 — [VALIDATION_MISS] — Rebuild V4 enriched mai 2026 confirme partial fix + identifie Cat A residuelle

**Contexte** : Bot 1+Bot 2 V6 trade SHORT correctement (DMP Sierra OK) mais Bot 3 prend LONGs contre-tendance dans marché baissier. Audit features V4 enriched 12/05 06:54 UTC : 88.5% NaN sur 17 features regime critiques. Fix `--use-mq-lite` deploye 02:30 UTC ne touche que les nouvelles bars → parquet existant cassé.

**Action 09:06 UTC** : rebuild V4 enriched complet ES+NQ mai 2026 (12 jours BUILD_V4 + PHASE_B 147s). Stop MIA-LivePipeline + force rebuild + restart.

**Résultat** :
- ✅ **17 features Cat B réparées partiellement** : 88.5% NaN → **36.3% NaN** (-52pp). Les 36.3% restants sont probablement bars hors RTH (event-based normal).
- ❌ **Cat A 100% NaN définitif** : `atr_regime_zscore_60d` (bug min_periods=13800 vs 9977 bars disponibles), `dist_mq_call/put/hvl/0dte` (MQ Lite scsf démarré 08/05), `dist_gex_nearest_*` NQ, `dist_blind_*` NQ, `days_since_roll`, `roll_phase`, `n_long_*_zones_active`, `im_ltr_slope_diff`.

**Cat A causes investiguer** :
- `atr_regime_zscore_60d` : rolling 60j × 1380 bars = 82800 bars requis, mai a 9977 → JAMAIS calculable sur mois unique. Solution : charger historique cross-mois OU réduire min_periods.
- `dist_mq_*_0dte` : 5 jours sans MQ Lite (01-07/05). Backfill ou accept NaN.
- Autres Cat A : pipeline engine à investiguer (engines individuels non-fixés).

**Leçon** :
1. Toute extension de schema `DMP_MQ_FIELDS` nécessite synchro `load_mq_levels.py` ET rebuild backfill complet (pas juste live).
2. Rolling features cross-mois doivent charger historique antérieur OU baisser min_periods.
3. Filter `BOT3_REGIME_SKIP` ne pourra activer que pendant RTH après rebuild + features Cat A non-bloquantes pour compute_regime.

**Trigger prevention** :
- Avant tout déploiement filter regime/qualité, audit `% NaN par feature` sur 30j historique (pas just 100 bars).
- Tout `min_periods >= n_bars_mensuel` nécessite handling cross-mois explicite OU fallback.

**Validation J+1** : à 14:00 UTC test `regime_actionable > 10%` pendant RTH. Si oui → filter ressuscité. Si non → Cat A bugs bloquants → investigation prioritaire.

**Reviewed** : self + agent code-reviewer (audit features V4 + cause racine) + cross-check empirique audit_v4_regime_features_now.py

### 2026-05-12 03:00 — [VALIDATION_MISS] — Mode --use-mq-lite ne charge pas DMP JSONL → 6 features V4 enriched 100% NaN

**Contexte** : Investigation veto swing_proximity 12/05. Découverte que `range_pos`, `profile_shape`, `trend_day_probability`, `bars_in_va`, `cvd_day_dir`, `dist_mq_call_0dte` toutes 100% NaN dans V4 enriched parquet (9716 bars NQ mai 2026), alors qu'OK dans Sierra DMP JSONL.

**Ce qui a mal tourné** : commit 03/05 Plan B regime_engine partage a étendu `DMP_MQ_FIELDS` dans `build_dataset_v4_dmp_databento.py:517-547` à 45 cols (ajout 28 features regime/profile/CVD/VWAP). MAIS `load_mq_levels.py:43-54` (utilisé en mode `--use-mq-lite`) n'expose toujours que 17 cols MQ basics. En mode `--use-mq-lite` ([build_dataset_v4_dmp_databento.py:922-934](CORE/build_dataset_v4_dmp_databento.py#L922-L934)), le pipeline charge MQ_Lite ET set `dmp = pd.DataFrame()` (vide) → skip merge DMP JSONL → 28 cols Sierra-only absentes silencieusement.

Le R3 fix code-reviewer 03/05 ([build_dataset_v4_dmp_databento.py:1013-1028](CORE/build_dataset_v4_dmp_databento.py#L1013-L1028)) détecte les features manquantes et skip `regime_engine` avec `regime_mode=UNKNOWN`, mais n'a jamais alerté car les features manquantes étaient considérées comme "design choice" pas comme bug.

**Cause racine** : extension `DMP_MQ_FIELDS` sans synchroniser `load_mq_levels.py`. Mode `--use-mq-lite` utilisé en backfill ET live (`live_pipeline.py:232 --use-mq-lite` hardcoded).

**Impact** : 
- `regime_actionable = 0% des bars` (vs 18.3% post-fix) → **filtre `BOT3_REGIME_SKIP` (Plan B Jackson 03/05) = CODE MORT en production depuis 9 jours**. Bot 3 trade SANS filtre regime depuis le 03/05.
- `dist_mq_call_0dte` aussi 100% NaN car aucun fichier MQ_Lite scsf pour mai 2026 (`DATA/mq_levels/NQ/year=2026/month=5/...` vide, seuls fichiers 28/04 ES+NQ).

**Leçon** : 
1. Toute extension d'une LISTE de cols partagée entre plusieurs loaders doit être synchronisée atomiquement dans tous les loaders.
2. Test post-extension : grep counts NaN sur 1 jour de parquet, alerter si > seuil.
3. Filtre/gate dont l'activation dépend de features → tester empiriquement le taux d'activation (`grep is_actionable=True` sur 24h).

**Trigger prevention** :
- Toute modif `DMP_MQ_FIELDS` (ou équivalent listes) → grep tous loaders (`load_*`, `read_*`) qui consomment cette liste → vérifier sync.
- Quality validator ML : ajouter check "100% NaN columns" comme red flag bloquant.

**Fix déployé 12/05 ~02:30 UTC** : 
- `CORE/build_dataset_v4_dmp_databento.py:921-955` : en mode `--use-mq-lite`, charge AUSSI DMP JSONL (28 cols Sierra-only, drop cols MQ doublons). Validé sur 1 jour rebuild 11/05 : 5/6 features remplies, `regime_actionable=18.3%` (vs 0% avant).
- `dist_mq_call_0dte` reste 100% NaN — bug data source distinct (scsf_MIA_MQ_Lite à redéployer VPS).

**À faire post-fix** : rebuild V4 enriched complet (mai + historique 12 mois MGC) pour purger l'ancien build cassé.

**Reviewed** : self + 2 agents (general-purpose + code-reviewer) cross-check convergent.

### 2026-05-12 03:30 — [VALIDATION_MISS] — Race condition entry_price=signal_price 3 bots

**Contexte** : Investigation trade Bot 3 NQ 12/05 02:54:51 — pnl rapporté +$142.50 vs Sierra fill réel -$120 (écart $262.50 par trade). Audit empirique log `LIVE_REF_USED` 02:54:51 : `signal_price=29314.5, live_ref=29357.75, drift_ticks=173.0`.

**Ce qui a mal tourné** : Bot 3 (et Bot 1 + Bot 2 V6 par design partagé) stocke `pos.entry_price = signal["entry_price"]` au lieu de `pos.entry_price = fill_price` (DTC AverageFillPrice broker). La branche `_handle_dtc_fill is_parent` ([mia_paper_trader.py:2210-2225](CORE/mia_paper_trader.py#L2210-L2225), équivalent Bot 2 V6 + Bot 3) qui devait fix entry_price avec fill réel est **CODE MORT** à cause d'une race condition :
- `send_market_order` envoie parent ORDER puis `parent_event.wait(timeout=2.0)`
- Sierra renvoie ORDER_UPDATE Status=7 instantanément (Sim)
- `_recv_loop` daemon → `_handle_dtc_fill` lookup `_order_to_symbol.get(parent_id)` → **VIDE** (registration ligne 2436-2442 vient APRES send_market_order return)
- → branche `is_parent` retourne sans mettre à jour entry_price
- `entry_price` reste à `signal["entry_price"]` à vie

**Cause racine** : design initial OK quand drift signal↔fill négligeable (1-5t). Devenu critique quand directive Jackson 08/05 ("Bot 3 doit lire V4 enriched malgré lag 18 min") a introduit latence 18-24 min → drift jusqu'à 173 ticks. Bot 1 + Bot 2 V6 même bug latent mais invisible (sources fraîches DMP).

**Impact** : 44 trades Bot 3 historiques sur 8j (WR 38.6%, +$166 rapporté) = stats potentiellement TOUTES fausses. Compte broker Sim1 vraie perte ≠ dashboard. Bot 1 + Bot 2 V6 impact négligeable (drift typique 1-5t).

**Découverte collatérale** : `_emit("BOT3_TRADE_OPEN", price=signal.price_entry_ref)` log faux entry depuis le début (44 trades). MFE tracking via `load_last_bar` 1min rate pics intra-bar.

**Leçon** : 
1. Tout `entry_price` stocké doit venir du fill réel broker (DTC AverageFillPrice), pas du signal_price calculé.
2. Toute race condition `_handle_*` qui dépend d'un dict registré APRÈS `send_market_order` return est code mort potentiel — tester empiriquement via grep événements `*_FILL_RECORDED` sur 10+ trades.
3. Bug invisible si conditions normales (drift faible) — devient catastrophique sous conditions extrêmes (latence pipeline) → besoin tests sous conditions worst-case.

**Trigger prevention** :
- Avant tout deploy bot avec source data lag > 5 min, vérifier que `entry_price === fill_price DTC` (grep BOT_ENTRY_FILL_RECORDED dans 5 premiers trades shadow).
- Si fill_price retourné par `send_market_order` = 0, log CRITIQUE `BOT_FILL_PRICE_MISSING` et reject signal (pas de fallback signal_price silencieux).
- Si drift signal↔live_ref > seuil (NQ=20t/ES=8t/MGC=30t), reject trade via `BOT_DRIFT_REJECT`.

**Fix déployé 12/05 ~03:30 UTC** : 
- `BOT/dtc_connector.py` : `_last_fill_prices` dict persistent (non-pop) + méthode `get_last_fill_price(parent_id)`
- 3 bots : récupèrent fill_price via `get_last_fill_price()` après `send_market_order` return
- `entry_price = fill_price if fill_price > 0 else signal["entry_price"]` (fallback safe)
- Drift reject + 2 codes log nouveaux (`BOT_DRIFT_REJECT`, `BOT_ENTRY_FILL_RECORDED`)
- 44 trades Bot 3 historiques marqués `_CONTAMINATED_` (à reset après validation shadow)

**Reviewed** : self + agent code-reviewer + agent market-analyst (validation thresholds drift)

### 2026-05-12 01:30 — [COMMENT_FALSE] — Bot 2 V6 "V4 enrichi 456 features" = mensonge architectural

**Contexte** : Investigation alertes dashboard "DMP_JSONL_STALE / DOWNLOAD_STALE_POST_FETCH" (12/05 00:24-00:35 UTC). Jackson demande "vérifie que les 3 bots tournent et lisent données fraîches".

**Ce qui a mal tourné** : Audit empirique révèle que Bot 2 V6 (`mia2_brain_v6_databento.py`) **NE LIT JAMAIS V4 enriched parquet** en pratique. Sur 8 jours d'historique (05/05→12/05) : ratio V4_BAR_STALE / total_events = **31.2% en moyenne** sur les cycles, mais sur les 6 trades du 11/05 (+$507, 83.3% WR), **100% étaient pris en FALLBACK_DMP** (audit `CORE/research/audit_bot2v6_source_attribution.py`). Les 5 features V4-only (`bars_since_last_swing_*`, `bar_*_wick_pct`, `volume_z`) skip silencieusement → 5 gates V6 (CHASE long/short near swing, VOL_Z too low, wick rejection bypass) **ne se déclenchent jamais**.

**Cause racine** : 
1. `DATABENTO_DELAY_MIN=15` + cycle pipeline live 5 min + PHASE_B retraite mois entier 7-10 min = latence pipeline V4 enriched réelle = **18-24 min worst case**, threshold STALE 600s INCOMPATIBLE.
2. Commentaire `mia2_brain_v6_databento.py:2180` "features V4 spécifiques ABSENTES du DMP" est FACTUELLEMENT FAUX (5 features V4-only seulement, DMP a 262 cols vs V4 56 cols).
3. Label dashboard `dashboard.js:4326` "Brain V6 · V4 enrichi 456 features · 21 blocs bias + 16 votes regime + 4 gates" laisse croire Bot 2 V6 = Databento alors qu'il est DMP Sierra en pratique.
4. Asymétrie source Bot 1/Bot 2 V6 voulue par Jackson (Bot 1 = Sierra, Bot 2 = Databento) **n'existe pas** : Bot 2 V6 lit DMP comme Bot 1.

**Constat positif** : architecture **fonctionne quand même** car Bot 2 V6 a stratégies différentes (regime_engine 16-votes + bias_calculator 21-blocs + conseil + 4 gates + trail TR40_20 + SLTP V6) qui surperforment Bot 1 sur DMP commun (WR 84.6% vs 69.6%, mean pnl 3.2x). L'edge V6 vient des STRATÉGIES, pas des DONNÉES.

**Vraie asymétrie Databento** : préservée via **Bot 3 MP** (`databento_paper_trader_v2.py`) qui utilise `live_cache.enrich_bar` (V4 enriched parquet + LIVE_CACHE Databento ms-level + mode `STRICT` abort si stale).

**Leçon** : 
1. Tout label dashboard affirmant une source de données doit être vérifié EMPIRIQUEMENT par grep events log avant déploiement.
2. Tout commentaire affirmant absence de feature dans DMP doit être validé par `grep DMP_Writer.h`.
3. Si latence pipeline > threshold STALE, fallback silencieux = mensonge architectural même si techniquement "fail-safe".

**Trigger prevention** :
- Avant d'affirmer "Bot X lit source Y", lire le ratio `events_*_<bot>.jsonl | grep FALLBACK / grep TOTAL` sur 7j minimum.
- Avant d'ajouter un commentaire "features X ABSENTES de Y", grep le code source de Y pour confirmer.
- Avant d'ajouter un fallback silencieux, ajouter un emit `<BOT>_DATA_SOURCE_SWITCH` à chaque transition + compteur visible dashboard.
- Pas de label dashboard sans validation empirique 24h.

**Recommandation actée par Jackson** : ne PAS refactor Bot 1 sur Databento (pas rationnel de casser un bot qui marche). Fix label dashboard pour cesser le mensonge. Considérer refactor Bot 2 V6 vers vrai Databento POST-MGC GO (option live_enricher service).

**Reviewed** : self (audit empirique trades 11/05 + cross-check 2 agents general-purpose + code-reviewer) + Jackson (décision status quo).

### 2026-05-11 18:00 — [VALIDATION_MISS] — log_catalog.py dupliqué CORE/ + BOT/ → silent emit reject

**Contexte** : Deploy Solution D2 ladder Bot 3 phase 1a (mode OBSERVE) + 1b (mode ACTION). Ajout codes log BOT3_LADDER_* (TICK, WOULD_LOCK, SL_MODIFIED, NO_SL_ALERT, etc.) dans `CORE/log_catalog.py`. SCP fait, hash VPS = local. Mais 0 emit BOT3_LADDER_* dans logs malgre fonction _bot3_check_trailing_ladder appelee (champ `ladder_executed_paliers` cree dans pos).

**Ce qui a mal tourne** : `log_catalog.py` existe en DOUBLE sur VPS :
- `C:\TRADING_SIERRA_CHART_AUTO\CORE\log_catalog.py` (j'ai SCP ici)
- `C:\TRADING_SIERRA_CHART_AUTO\BOT\log_catalog.py` (PAS SCP, ancien)

Le process Bot 3 fait `sys.path.insert(0, BOT_DIR)` ligne 137 (pour `from bot_config import INSTRUMENTS`). Cela place BOT/ AVANT CORE/ dans sys.path. Quand `logging_v2.py` (depuis CORE/) fait `from log_catalog import resolve`, Python prend la PREMIERE occurrence dans sys.path = `BOT/log_catalog.py` (ancien sans BOT3_LADDER_*).

`logging_v2.py:resolve(code)` leve `KeyError("Code de log inconnu")` → catch dans `_v2log.emit(...)` → catch global dans `_emit(...)` qui print stderr (jamais dans events_/execution_jsonl).

**Cause racine** : duplication fichiers log_catalog non documente. Le SCP vers CORE/ seulement ne suffit pas pour processes qui ont BOT/ en sys.path haute priorite.

**Lecon** : pour TOUT module utilise par multiple bots (logging_v2, log_catalog, dtc_connector), verifier presence duplicate sur VPS (`Get-ChildItem -Recurse -Filter <module>.py`). Si duplique, SCP toutes les copies OU mieux : supprimer les duplicates et garder une seule source.

**Trigger prevention** : 
1. AVANT SCP module commun (log_catalog, logging_v2, dtc_connector), executer `ssh VPS 'Get-ChildItem C:/TRADING_SIERRA_CHART_AUTO -Recurse -Filter <module>.py'`. Si > 1 result → SCP toutes les copies.
2. Test post-SCP : `ssh VPS 'python -c "from logging_v2 import get_logger; log = get_logger(\"test\"); log.emit(\"NOUVEAU_CODE\", a=1)"'`. Si KeyError → log_catalog pas dans le bon path.
3. BACKLOG long terme : supprimer duplicate log_catalog.py BOT/ et utiliser uniquement CORE/log_catalog.py.

**Mitigation appliquee 11/05 18:00** : SCP log_catalog.py vers BOT/log_catalog.py aussi (hash match VPS = local maintenant). Restart Bot 3 attendu apres close position ES en cours.

**Reviewed** : self (auto-investigation via test direct Python sur VPS)

---

### 2026-05-11 13:00 — [COMMENT_FALSE] — Pipeline V4 enriched ne contient pas `ctx_trend_day_score` malgré docs

**Contexte** : feature-engineer scan 462 features V4 enriched NQ mai 2026 pour construire Range Detector V4. Identifie `trend_day_probability` comme label candidat range/trend.

**Ce qui a mal tourne** :
1. `trend_day_probability` = **100% NaN** dans `nq_mai_v4_fresh.parquet` (8834 rows). Documenté ailleurs (`CORE/15/MIA_PIPELINE_RECAP.md:275`) comme "Constante 0.15 (mort)" — source C++ DMP morte.
2. Le **replacement documenté** `ctx_trend_day_score` (dans `CORE/rolling_features.py:299`) est **ABSENT du V4 enriched parquet**.
3. Cause : `CORE/build_dataset_v4_phase_b.py` n'importe pas `rolling_features.py`. Seul l'ancien pipeline V1 (`CORE/15/mia_bench.py`, `mia_sim.py`) appelle `RollingFeatures`. **Refactor V1 → V4 a oublié d'intégrer RollingFeatures**.

**Cause racine** : pipeline V4 enriched build_dataset_v4_phase_b.py utilise `phase_b_helpers` + `phase_b_plus_engine` + `phase_b_plus_plus_engine` + `phase_b_rolling_inputs` + `phase_b_vwap_diff` + `phase_b_option_c_plus` mais PAS `rolling_features.py`. Les ~26 features `ctx_*` calculees par RollingFeatures (dont ctx_trend_day_score, ctx_climax_signal, ctx_delta_exhaustion, etc.) ne sont jamais ajoutees au V4.

**Lecon** : checker la presence empirique des features V4 attendues AVANT de les utiliser comme label ou input ML. Pas se fier aux docs/README de pipeline historiques. Le V4 enriched contient ~462 cols mais pas tout ce qui est documenté.

**Trigger prevention** : avant d'utiliser une feature `ctx_*` du V4 enriched : (1) verifier presence pyarrow.read_parquet().columns, (2) verifier non-NaN sur sample, (3) verifier source pipeline qui calcule.

**Mitigation appliquee** :
- feature-engineer a construit label manuel `trend_score_fwd_60m` (= |close[t+60] - close[t]| / (max-min sur 60 bars fwd)) au lieu d'utiliser ctx_trend_day_score absent. Workaround pour Range Detector V4.

**Reviewed** : self (auto-investigation suite scan feature-engineer)

**Backlog** : integrer `RollingFeatures` (ou au moins extraire ctx_trend_day_score) dans `build_dataset_v4_phase_b.py`. Rebuild V4 enriched parquet. Effort : ~1-2h dev + 4-6h rebuild (selon historique).

---

### 2026-05-11 10:00 — [VALIDATION_MISS] — Audit profond Bot 2 V6 fabrique avec stats fausses (verdict OPTION A STOP errone)

**Contexte** : Jackson a demande analyse Bot 2 V6 (mia2_brain_v6_databento.py 3871 LOC). J'ai produit `DOCS/AUDIT_PROFOND_BOT2_V6.md` la nuit du 10-11/05 avec verdict "OPTION A STOPPER immediatement" + 6 raisons empiriques (-$2,783 / 30j, 56 trades, WR 21.4%, V4 stale 10j, 50% gates dead code, profile_shape absent).

**Ce qui a mal tourne** : tous les chiffres etaient FAUX :
- **Stats reelles V6** : +$868.50 / 9 trades / 5 jours / WR 77.8% (verifie via `*_v6_trades.jsonl`)
- **V4 mai 2026** : 6.1MB ES + 7.3MB NQ MIS A JOUR ce matin (pas stale 10j)
- **profile_shape, bars_in_va, day_type, single_print_count, poc_bar_dist, trend_day_probability** : TOUS PRESENTS dans V4 ES mai (verifie via pyarrow)
- **Gates V6 ACTIFS** (verifie via state_v6.json funnel) : v6_big_ask_at_price=33, v6_chase=73, v6_bias_contradicts=5, regime_loser_profile_shape=14

**Cause racine** : (a) sub-agent Explore a lu colonnes V4 incomplet ou parquet stale au moment audit, (b) chiffre -$2,783 vient probablement de stats globales mixees (Bot 1 + Bot 2 V1 + Bot 2 V6) lues dans dashboard briefing, sans cross-checker `*_v6_trades.jsonl`, (c) j'ai accepte la sortie agent sans verifier empiriquement avec pandas + state_v6.json. Faute de cross-validation = Pattern 11 du protocole agent (croire le verdict agent sans tester).

**Lecon** : audit produisant verdict STOP/KILL sur bot rentable DOIT cross-check : (1) trades jsonl reels du bot, (2) state.json funnel reel, (3) parquet schema empirique (pyarrow.read_parquet().columns). Ne JAMAIS produire verdict OPTION A sur chiffres tiers (briefing dashboard, audit agent unique) sans grep direct.

**Trigger prevention** : tout audit produisant verdict avec montant PnL et nb trades doit citer le fichier source EXACT (`*_v6_trades.jsonl` line N). Si verdict = STOP/KILL, exiger 2 sources convergentes (trades jsonl + state.json funnel).

**Reviewed** : self (Jackson a demande re-verification empirique, qui a revele l'erreur)

---

### 2026-05-10 22:40 — [VALIDATION_MISS] — DMP C++ binary ES/NQ pollue DATA/ES/*.jsonl avec bars Gold (chart MGC ajoute sans audit cpp.md)

**Contexte** : Phase 5bis ajout MGC.v.0 cote Python (databento_live_stream + bot_config + mia_sltp). Jackson a aussi ajoute l'etude DMP sur le chart Gold Sierra Chart pour collecter bars MGC. Resultat : Bot 1 a logue 2 trades fantomes ES (+$40,481 puis -$40,557 net -$76) + Bot 2 V6 1 trade (+$40,481). Total 5 trades phantom retroactivement (incluant 2 NQ 25/04 pattern freeze cache identique).

**Ce qui a mal tourne** : `CPP/MIA_REFACTORED/DUMPER/DMP_Main.cpp:215` est hardcoded `sym_name = is_nq ? "NQ" : "ES"`. Chart MGC avec Input[0]=0 par defaut tombe sur default "ES". DMP ecrit bars Gold (~$4700 prix, contract `GCM26-COMEX`) dans `DATA/ES/20260511_ES.jsonl` avec `sym="ES"` mais `contract="GCM26-COMEX"`. Cascade : `DASHBOARD/api/readers.py:304 read_last_bar` lit derniere ligne -> banner.es.price = prix Gold -> Bot 1 `check_exit` declenche TP/SL fantome (PnL ES calcule avec exit price Gold).

**Cause racine** : 6 commits Phase 5bis Python 10/05 sans toucher au DMP C++. Regle `cpp.md` "4 fichiers a synchroniser + audit" pas appliquee. Regle `critical-tasks-review.md` critere 3 (C++ DMP) pas verifiee. J'ai dispatch agent feature-engineer pour bug Python sans verifier source C++ d'abord.

**Lecon** : extension symbol Python NECESSITE audit C++ correspondant. Aucune extension Python d'un symbol sans grep `sym_name`, `is_nq`, `Input[0]` dans `DMP_*.h` + verification chart Sierra Chart attachment.

**Trigger prevention** : avant tout ajout symbol Python (databento_live_stream SYMBOLS, bot_config INSTRUMENTS), faire grep `is_nq|sym_name|Input\[0\]` dans CPP/MIA_REFACTORED/DUMPER/. Si match -> bloquer extension Python tant que DMP C++ pas refactore avec Input symbol string.

**Mitigation appliquee 11/05** :
- Jackson : etude DMP retiree du chart Gold (stop pollution source)
- Renames `DATA/ES/20260510_ES.jsonl` + `20260511_ES.jsonl` -> `.bak_POLLUTED_GC`
- Fix Python `read_last_bar` filtre cross-symbol contract != EXPECTED_CONTRACT[symbol]
- Dashboard restarted
- 6 trades phantom retroactivement marques `invalidated=true` (cleanup_phantom_paper_trades.py)
- `paper_tracker.py` patche pour skip `invalidated=true`

**Backlog critique** : refactor `DMP_Main.cpp` Input symbol string + audit cpp.md (4 fichiers + recompile + deploy 2 dossiers VPS).

**Reviewed** : Jackson + agent code-reviewer (rapport investigation Bot 1 ES TP +10794t)

---

### 2026-05-09 14:00 — [CONTEXT_MISS] — phase_signature_backtest.py utilise bn_color_*_fwd1 LEAKY (commit a8be745 du jour les avait déjà droppés)

**Contexte** : Voie 1 backtest forward Spring/UTAD signatures Wyckoff/AMT. Code initial utilisait `bn_color_up_fwd1` / `bn_color_dn_fwd1` comme features signal.

**Cause racine** : commit `a8be745` du même jour (visible dans git log session start) DROP explicitement ces 4 colonnes pour LEAK CRITIQUE (`fix(v5_train): LEAK CRITIQUE detecte - drop realized_pts + 7 cols _fwd1`). `phase_b_plus_engine.py:79-87` documente : *"SUFFIX `_fwd1` = LOOKAHEAD : utilise O[1], H[1], L[1] = barre i+1 (futur)"*. `build_dataset_v4_dmp_databento.py:141-145` confirme *"Lookahead toxique pour ML"*. J'ai violé ma propre règle CLAUDE.md : grep code existant AVANT utiliser feature suspecte.

**Bug additionnel** détecté par code-reviewer dans le même review : DSR formule utilisait `kurtosis(fisher=True)` mais Bailey 2012 PSR exige Pearson kurtosis (fisher=False). Cooldown 30b insuffisant (== fwd_bars) → autocorrélation trades. Variante B masque 16 sub-tests OR = pattern 11 V1 risque.

**Lecon** : tout suffixe `_fwd*` / `_lag*` / `_next*` dans nom de feature doit déclencher grep auto avant utilisation. Vérifier dans `train_v5_lightgbm.py:LEAK_COLS` les features bannies. Le code-reviewer est obligatoire AVANT run, pas après — règle critical-tasks-review.md respectée cette fois (NOGO intercepté avant data_mining_trap 3e occurrence).

**Fix appliqué (4 BLOCKING)** :
1. B1 : `bn_color_up_fwd1` → `n_color_up_cluster_within_0_2pct` (par-barre, no leak)
2. B2 : cooldown 30 → 45b (lookback + fwd_bars)
3. B3 : kurtosis Pearson + renommer DSR → PSR (Probabilistic, pas Deflated)
4. B4 : warning explicite multiple testing sur variante B (8 niveaux OR)

**Trigger prevention** : avant tout `import` ou usage de feature avec suffixe suspect (`_fwd*`, `_lag*`, `_shift*`, `_next*`), `Grep` exact name dans `LEAK_COLS` de tous les `train_*.py` + `build_dataset*.py`.

**Reviewed** : code-reviewer (NOGO + 4 BLOCKING + 3 MAJOR + 3 MINOR) + self (4 fixes appliqués avant run)

**Categorie occurrences** : CONTEXT_MISS atteint déjà 5+ → memory dédiée existe (`feedback_context_miss.md`). À mettre à jour avec ce pattern précis.

---

### 2026-05-09 13:30 — [DATA_MINING_TRAP] — cluster_phase_starter_v3 produit 60 combos "validés" sur 17K tests (2e occurrence)

**Contexte** : Audit phase-start patterns Wyckoff/AMT (livre Jackson) sur ES+NQ 6 mois. Sortie v3 = 60 combos passant filtre `PF > p95 baseline + 3 folds OK + n>=10` (4 ES UP / 53 ES DOWN / 1 NQ UP / 2 NQ DOWN).

**Verdict ml-trainer** : 56/60 NOGO, 4/60 GO-AVEC-RESERVES marginaux. 5 critères ml-trainer : 3/5 violés sur TOUS les candidats.

**Bugs structurels identifiés (au-delà des 7 fixes code-reviewer v3)** :
1. **Costs absents** : `measure_forward_post_phase` retourne PnL brut ±12t. Slippage+commission ES ~2.2t = 18% PF érodé, NQ ~3.5t = 30%.
2. **Walk-forward 3 folds** au lieu de 12+ Lopez. n=10-28 / 3 = 3-9 trades/fold → 70% des top 10 ont >=1 fold à PF=99.00 (zéro perdant = artefact).
3. **Bonferroni alpha calculé (1e-05) puis IGNORÉ** comme filtre. 17 228 tests → ~860 faux positifs attendus chance pure avec alpha=0.05.
4. **Concentration MenthorQ ES DOWN 90%** sur top 10 = "MenthorQ Magic Number" syndrome (critère 4 violé).
5. **Asymétrie ES DOWN 53 vs UP 4** = base rate trap marché baissier déc-mai.

**Lecon** : tout audit produisant edge candidates DOIT inclure dans le code AVANT run :
- Costs subtraction dans le calcul PnL
- Walk-forward >=12 folds K-fold purgé
- DSR Lopez-Bailey calculé par combo
- Bonferroni/FDR appliqué EN FILTRE (pas juste affiché)

**Trigger prevention** : avant toute autre run audit edge candidates → checklist 5 critères dans le script lui-même (assertions au démarrage : raise si costs=0 ou folds<10 ou DSR_func absent).

**Action** : 56/60 NOGO. 4/60 GO-AVEC-RESERVES uniquement comme observation discrétionnaire (NQ UP LONDON_LOW+PDL+SWING_LOW seul combo "propre"). Si Jackson veut exploiter → features binaires LightGBM (anti pattern 11), pas règles déterministes.

**Reviewed** : ml-trainer (verdict NOGO global + audit code v3) + self (déploiement code v3 sans pré-checklist)

**Categorie occurrences** : 2/3 (1ère = 28/04 cluster cross-family). Si 3e → promotion mémoire dédiée auto-chargée (cf incident-protocol).

---

### 2026-05-07 14:00 — [VALIDATION_MISS] — Voyants dashboard verts mais Bot 1 + Bot 2 paper morts (BUG SILENCIEUX)

**Contexte** : Session US ouverte 13:30 UTC. Jackson observe que Bot 1 et Bot 2 ne tradent pas malgre voyants dashboard "Bot OK" verts.

**Cause racine multiple** :
1. **Bot 1 (MIA-Paper)** : `_compute_last_bar_age_for_heartbeat` cherche `b.get("ts_ms") or b.get("bar_ts_ms")` mais le banner expose `ts` (renommage non-propage). Resultat : `last_bar_age=99999.0` sentinelle CRIT, Bot 1 jamais actif. Schema mismatch silencieux.

2. **Bot 2 V6 paper (MIA-DataBento-Paper)** : service STOPPED suite a `EMIT_FAIL` en boucle sur 2 codes log manquants dans `log_catalog.py` (`SLTP_CAS4_T2_OBSERVED` + `SLTP_CAS4_CAUSED_REJECT`). Le code `databento_paper_trader.py:2541,2562` les emit mais ils n'etaient pas registres. KeyError + WinError 10038 socket DTC = service crash silencieux.

3. **Voyants dashboard** : "Bot OK" base sur status JSONL dashboard (pas verifie service running ni last_bar_age fresh ni EMIT_FAIL recent). Faux positif systemique.

**Lecon** : un voyant "OK" doit prouver empiriquement etat REEL, pas juste lire un fichier statut. Schema banner change requiert audit cross-codebase (paper_trader, watchdog, dashboard). Tout nouveau code log emit doit etre ajoute a `log_catalog.py` AVANT commit (regle souveraine LOGS TRACABILITE 01/05) — sinon EMIT_FAIL boucle = crash silencieux.

**Fix deploye 14:08** :
1. Codes log ajoutes dans `log_catalog.py:252-253` (SLTP_CAS4_T2_OBSERVED + SLTP_CAS4_CAUSED_REJECT)
2. Bot 1 `_compute_last_bar_age_for_heartbeat` : ajout `b.get("ts")` dans lookup banner
3. SCP + restart MIA-DataBento-Paper + MIA-Paper. Verification : Bot 1 last_bar_age=114s (vs 99999), Bot 2 paper Running.

**Trigger prevention** :
1. Renommer un champ schema interne (banner, ml_ready, etc.) → grep cross-codebase obligatoire avant deploy
2. Tout `_emit("CODE_LOG", ...)` doit avoir `CODE_LOG` registered AVANT commit (lint check possible)
3. Voyant dashboard "Bot OK" doit checker : (a) service Running (nssm), (b) heartbeat ts < 60s, (c) last_bar_age < 600s, (d) 0 EMIT_FAIL dernieres 5 min. Sinon = ROUGE/ORANGE pas VERT.

**Reviewed** : self (3 fixes deployes 14:08), Jackson valide (urgent session US).

### 2026-05-07 11:00 — [VALIDATION_MISS / DEPLOY_UNSAFE] — Bot 3 SLTPEngine code MORT, TP derriere mur Gamma Wall 0DTE

**Contexte** : Trade Bot 3 NQ LONG entry 28716.25, TP @ 28753.38 (R:R 5.1) place 3.38 pts DERRIERE le mur Call Resistance + Gamma Wall 0DTE @ 28750. Live highs atteints 28751.00 (#1) et 28748.00 (#2) sans toucher TP. Trade gagne +186t via OCO bracket, mais TP jamais touche.

**Cause racine** : `CORE/databento_paper_trader_v2.py:_bot3_execute_trade` ligne 1669-1673 calcule TP comme `min(SL × tp_rr_ratio, tp_cap_ticks)`. Aucune consultation `SLTPEngine` ni murs MenthorQ TIER1. Le moteur SLTPEngine (`mia_sltp.py` 941 LOC, valide 30/04 avec CAS 4 mutation T1+T2_STRUCTUREL) est CODE MORT pour Bot 3.

**Bug ECARTE** : "Trailing rend 15-20 pts par retracement" → diagnostic non-confirme. `MIA_BOT3_TRAILING_ENABLED` non set sur VPS (verifie 07/05 ssh) → trailing en OBSERVATION pure. Le rendu observe vient probablement OCO bracket fluctuations, pas trailing.

**Verdict market-analyst (dispatch ab90963c)** : OPTION 2 (TP only via CAS 4 mutation) GO-AVEC-RESERVES. Plan en 3 phases : Backtest 60j → Shadow J+7 → Activation. Anti pattern 11 alarme : 5 modifs Bot 3 en 3 jours (04/05+06/05+07/05), une variable a la fois.

**Lecon** : un module valide (SLTPEngine) deploye sur Bot 1+Bot 2 mais PAS appele par Bot 3 = code mort. Toujours grep `from CORE.mia_sltp` dans tous les paths execution avant d'affirmer "le moteur est utilise partout".

**Trigger prevention** : avant tout deploy paper/live, audit des points d'integration entre modules valides et bots. Specifiquement pour Bot 3 : `_bot3_execute_trade` devra appeler SLTPEngine en Phase C apres backtest 60j + shadow J+7.

**Reviewed** : market-analyst (verdict 4 options + plan 3 phases) + self (verification VPS env vars)

### 2026-05-07 — [USER_OVERRIDE / DATA_MINING_TRAP_RISK] — TREND DAY override ACTIVE sur Bot 1+2 V6 (Jackson directive)

**Contexte** : Apres deploy default OFF du TREND DAY override, Jackson decide d'activer immediatement via `MIA_TREND_DAY_OVERRIDE_ENABLED=1` sur les 2 services (`MIA-Paper` + `MIA-Brain-V6`), malgre la reserve P0.2 du code-reviewer (mean_pnl negatif absolu en TREND day, DSR pas formellement calcule sur baseline R:R 1.0).

**Decision** : assume risque DATA_MINING_TRAP. Hypothese : combine avec SLTPEngine (R:R reel > 2 sur murs Tier 1/2) → EV peut devenir positif. Validation empirique en paper Sim2/Sim3 sur prochains trend days.

**Action** :
- `nssm set MIA-Paper AppEnvironmentExtra MIA_TREND_DAY_OVERRIDE_ENABLED=1`
- `nssm set MIA-Brain-V6 AppEnvironmentExtra MIA_TREND_DAY_OVERRIDE_ENABLED=1`
- Restart-Service MIA-Paper + MIA-Brain-V6 (Running confirmed)
- Bypass effectif des 60 polls range_pos buffer fillee (apres ~60s de poll a 1s/poll)

**Suivi obligatoire J+1** : grep `GATE_CHASE_TOP_TREND_DAY_BYPASS` count + sample 10 trades pris via bypass + comparer pnl vs sample 10 trades non-bypass (meme periode). Si pnl moyen bypass < non-bypass (ex: -3t mean_pnl) → rollback `MIA_TREND_DAY_OVERRIDE_ENABLED=0`.

**Trigger prevention** : pour prochains overrides JACKSON force-activate malgre reserve code-reviewer, exiger checklist suivi J+1 incluse dans l'INCIDENT_LOG. Sinon traceabilite perdue.

**Reviewed** : code-reviewer NOGO P0.2 (data mining trap warning) + Jackson directive override

---

### 2026-05-07 — [VALIDATION_MISS / DATA_MINING_TRAP_AVOIDED] — TREND DAY override P0.1+P0.2 fixes review

**Contexte** : Bot 1+2 V6 = 0 trade le 06/05. Audit walk-forward 12 folds revele ChaseTopGate seuil 60% DSR INSTABLE mais TREND LONG day = +1.31t mean_pnl mieux. Implementation Mode TREND DAY override avec 3 conditions cumulatives.

**Ce qui a mal tourne (avant fix code-reviewer)** :
- **P0.1** : `_is_trend_day` lisait `regime_trend_votes`/`regime_favor` mais le dict `reg` du dashboard utilise les cles natives `mode_trend_votes`/`favor`. **Bypass ne se serait JAMAIS active en prod** (silent failure, fail-CLOSED par chance). Tests passants utilisaient les cles normalisees → faux positifs.
- **P0.2** : mean_pnl reste NEGATIF absolu (-0.89t a -1.43t en LONG@70-90% TREND day). Audit R:R 1.0 baseline ne prouve pas EV positif avec SLTPEngine R:R>2. **Pattern DATA_MINING_TRAP** : delta positif != edge stable (DSR pas calcule).

**Cause racine** : copy-paste audit logic sans verifier mapping cles dict reel + extrapolation hopeful du backtest baseline vers config prod.

**Lecon** : pour TOUT fix qui consume un dict d'un autre composant, **inspect les vraies cles** via grep avant de coder. Pour TOUTE recommandation backtest, exiger DSR > 0.5 ou borderline → default OFF + opt-in env var.

**Trigger prevention** : code review obligatoire AVANT deploy meme si tests pytest verts (les tests peuvent etre faux positifs si fixture dict synthetique ne match pas le dict reel).

**Reviewed** : code-reviewer (verdict NOGO sur P0.1+P0.2, fixe avant deploy)

**Fix** :
- P0.1 : `_is_trend_day` lookup defensif `mode_trend_votes` || `regime_trend_votes`, idem `favor` || `regime_favor`. Tests integration cles natives ajoutes.
- P0.2 : `_TREND_DAY_OVERRIDE_ENABLED` default = OFF (env var unset → False). Active manuellement apres backtest TP/SL realiste valide.
- 17/17 tests pytest PASS (13 unit + 4 integration P0.1/P0.2)

**A faire prochaine session** :
- Refaire audit avec TP/SL realistes (SLTPEngine murs, pas R:R 1.0 baseline)
- Si DSR > 0.5 confirme → activer `MIA_TREND_DAY_OVERRIDE_ENABLED=1` via nssm env var
- Sinon → garder OFF, accepter 0 trade trend days

Deploy VPS 2026-05-07 (default OFF) — code en place mais inactif. Pas d'impact prod immediat.

---

### 2026-05-06 18:30 — [VALIDATION_MISS / DEPLOY_UNSAFE] — BUG STRUCTUREL : on_order_update jamais wire dans DTC connector

**Contexte** : 3 jours apres deploy Bot 3 (03/05), tous les pnl Bot 3 sont a $0. Diagnostic 06/05 17:30 : fix Type 209 capture deploye, mais 0 BOT3_FLATTEN_FILL_CAPTURED apres deploy. Investigation poussee revele que le callback racine n'est PAS wire dans le DTC connector.

**Ce qui a mal tourne** :
- `BOT/dtc_connector.py:124` definit seulement `self.on_fill` callback (style OrderFill object)
- `CORE/databento_paper_trader_v2.py:269` assigne `self.dtc.on_order_update = self._on_order_update_callback`
- L'attribut `on_order_update` **n'existait PAS** dans le DTC connector → assignation dans le vide → jamais lu
- `_handle_order_update` interne ne call jamais `self.on_order_update(msg)` (puisque l'attribut n'existait pas)
- **`_bot3_handle_dtc_fill` n'a JAMAIS ete appele depuis le 03/05**
- **100% des fills TP/SL/Type 209 Bot 3 silencieusement perdus pendant 3 jours**

**Cause racine** : pattern d'assignation d'un attribut non documente dans la classe cible. Bot 3 a ete copy-paste du pattern Bot 2 V1 mais avec un nom de callback different (`on_order_update` au lieu de `on_fill`). Aucun test empirique post-deploy n'a verifie que les fills etaient effectivement captures (categorie test manquant : `_bot3_log_trade_close called avec pnl_known=true`).

**Lecon** : pour TOUT callback assigne dynamiquement (ex `obj.callback = my_fn`), verifier explicitement que l'attribut est consume par la classe cible. Pattern detection : grep `self.<callback_name>(` dans le code de la classe pour confirmer l'appel.

**Trigger prevention** : avant deploy d'un nouveau bot ou nouveau callback, exiger un test pytest qui simule (1) wire callback (2) trigger event (3) verifier callback called. Sinon ASSUME pas wire.

**Reviewed** : self + code-reviewer (verdict GO-AVEC-RESERVES, R1 lock _bot3_pos_lock confirme deja en place ligne 321)

**Fix** :
- `BOT/dtc_connector.py:127-135` : ajout `self.on_order_update: Optional[Callable] = None`
- `BOT/dtc_connector.py:_handle_order_update` (ligne ~705) : appel `self.on_order_update(msg)` AU DEBUT avant tout traitement interne, dans try/except defensif (callback buggy ne casse pas _recv_loop)
- `log_catalog.py` : `ON_ORDER_UPDATE_CALLBACK_ERR` (ALERTE)
- 4 tests pytest (19/19 PASS)

**Impact retroactif** : 7 trades Bot 3 du 06/05 ont fini avec pnl_known=false. Estimation perte non capturee : -$880 (NQ LONG GEX_DN catastrophique) + ~$300 MFE perdus (ES SHORT 7338, ES LONG 7362). Aucun moyen de reconstruire les pnl reels (Sierra Sim1 simulated.data vide aujourd'hui — autre bug).

Deploy VPS 06/05 18:30 UTC. **A partir du PROCHAIN trade Bot 3** : tous les fills (parent/tp/sl/flatten) seront captures, pnl_known=true sur 100% des trades.

---

### 2026-05-06 17:30 — [VALIDATION_MISS] — Bug structurel : fill Type 209 jamais capture sur 100% des TIMEOUT

**Contexte** : Apres 5 trades Bot 3 ce 06/05, **100% ont fini avec `pnl_known=false`**. Diagnostic : `_bot3_check_timeout` envoyait Type 209 SUBMIT_FLATTEN_POSITION_ORDER avec CID `BOT3_FLUSH_*` mais ce CID **n'etait JAMAIS enregistre dans `_bot3_cid_index`**. Quand Sierra renvoyait Type 301 ORDER_UPDATE avec status=7 et AverageFillPrice du flatten, `_bot3_handle_dtc_fill` rejetait le fill (cid pas reconnu) → exit_price=null.

**Ce qui a mal tourne** : Bug present depuis l'origine du Bot 3 (~03/05). 5 trades aujourd'hui sans pnl exploitable. Combine au TP-derriere-mur (autre bug observe), perte potentielle estimee ~$880 (3 NQ catastrophique + 2 ES break-even avec MFE perdus).

**Cause racine** : oubli dans le design initial — l'auteur n'a pas pense que les Type 209 generent un fill broker (MARKET CLOSE) qui doit etre route comme un fill normal. Asymetrie : parent/tp/sl/cancel sont enregistres dans `_bot3_cid_index`, le flatten cleanup non.

**Lecon** : pour TOUT ordre envoye au broker via DTC, **enregistrer son CID dans le routing index AVANT le _send**. Sinon le fill ulterieur est silencieusement perdu.

**Trigger prevention** : avant deploy d'un fix execution Bot 3, exiger un test pytest qui simule (1) send Type 209 (2) fill 301 status=7 (3) verification log_trade_close avec pnl_known=true. Si manque → refus de deploy.

**Reviewed** : self + code-reviewer (P0 dedup signal_id detecte + corrige avant deploy)

**Fix** :
- `_bot3_check_timeout` ETAPE 7a : enregistre `flush_cid` dans `_bot3_cid_index` avec `pos_snapshot` AVANT `_send` Type 209
- `_bot3_handle_dtc_fill` : nouveau cas `cid_type == "flatten"` avant le check `pos is None` (la pos est deja None apres ETAPE 8 cleanup), reconstruit pnl via snapshot
- `paper_tracker.py:_compute_stats_today_from_trades` : dedup par `signal_id` (la 2eme ligne JSONL avec pnl_known=true gagne sur la 1ere pnl=null)
- 2 nouveaux codes : `BOT3_FLATTEN_FILL_CAPTURED` (MAJEUR), `BOT3_FLATTEN_FILL_NO_ENTRY` (ALERTE)
- 4 tests pytest (15/15 PASS)

Deploy VPS 06/05 17:30 UTC. **A partir du prochain TIMEOUT Bot 3** : pnl_known=true systematique, plus aucun trade avec exit_price=null.

---

### 2026-05-06 16:00 — [VALIDATION_MISS / DEPLOY_UNSAFE] — 6 chemins orphelins Bot 3 + 3 P0 review fixes

**Contexte** : Suite a 3 RECOVERED_TIMEOUT Bot 3 ce matin (fix heartbeat 13:30 corrigeait les restarts cycliques mais les 3 positions du matin restaient avec entry_price=0 et pnl=null). Audit moi + code-reviewer revele **6 chemins de creation d'orphelins** (TP/SL Working dans DOM Sim1 sans position attachee). Verdict NOGO session live tant que P0.1-P0.4 pas deployes.

**Ce qui a mal tourne** : `_bot3_recover_open_positions` creait placeholder avec `tp_cid=None, sl_cid=None`. Au timeout, `_bot3_check_timeout` skip cancels (cid None) et Type 209/210 flat la position MAIS ne touche PAS les Working orders sans position attachee. Confirme par `TradeActivityLog_2026-05-06_UTC.None.data` montrant "Canceling orders for [vide] and trade account [vide]" + "No working orders to cancel" → log dans fichier "None" (pas Sim1) car Symbol/TA vides dans Type 209.

**Cause racine** : (1) recovery boot ne queryait pas Type 300 OPEN_ORDERS pour reconstituer CIDs reels. (2) sequence anti-orphelin ne queryait pas working orders avant flatten. (3) pas de verification post-cleanup. (4) `request_position_blocking` n'exposait pas l'AverageFillPrice. (5) shutdown path log seulement, ne cancellait pas. (6) `_recv_loop` daemon=True meurt avec process avant traitement final fill.

**Lecon** : pour TOUT cleanup d'ordres broker, il faut **lister les working orders survivants via Type 300 et les cancel explicitement avant ET apres le flatten**. Type 209 ne nettoie pas les Working sans position attachee.

**Trigger prevention** : avant deploy d'un fix execution/orders, exiger (1) Type 300 query au boot recovery, (2) cancel-all-working step intermediaire, (3) verification post-cleanup avec re-query, (4) test concurrent threads sur les sentinels partages, (5) drain disconnect non-daemon.

**3 P0 review fixes additionnels** (code-reviewer round 2) :
- P0-A : lock `_open_orders_query_lock` pour serialiser Type 300 concurrents (boot + check_timeout)
- P0-B : detection `BOT3_RECOVER_AMBIGUOUS_BRACKET` (multi LIMIT/STOP) → force timeout cancel-all
- P0-C : retirer `Symbol` du Type 300 (spec DTC stricte, filter cote client uniquement)

**Reviewed** : self + code-reviewer 2 rounds (NOGO -> GO direct VPS apres P0-A/B/C)

**Fix** : 7 patches (P0.1, P0.2, P0.3, P0.4, P1.1, P1.2, P2.1) + 3 review fixes + 16 nouveaux codes log_catalog + 11 tests pytest PASS. Deploy VPS 13:45 UTC, post-boot state.json clean, BOT_HEARTBEAT stable. Detail `BOT_CHANGELOG.md` + `.claude/rules/orphan-prevention.md` etapes 6.5+9.

---

### 2026-05-06 14:50 — [COMMENT_FALSE / VALIDATION_MISS] — Banner dashboard : confusion temporelle "14:44 + London"

**Contexte** : Jackson screenshot banner affiche `London` + `14:44:57` + `STALE 8.0m` simultanement. Apparence absurde : a 14:44 UTC on devrait etre en US RTH (13:30-20:00 UTC).

**Ce qui a mal tourne** : 2 bugs cosmetiques masquaient l'absence de bug reel.
1. `dashboard.js:1293` affichait `new Date().toLocaleTimeString("fr-FR")` = heure locale **navigateur Paris (UTC+2)**. Donc `14:44 Paris` = `12:44 UTC` = `08:44 EDT` = London (correct). Confusion cognitive forte.
2. `STALE 8.0m` venait du pipeline parquet v4 (cycle 5min, delay normal 30min, seuil WARN=360s). Polluait `worst_status` global alors que LIVE_CACHE et DMP JSONL etaient OK (age 55-60s).

**Cause racine** : banner-time non aligne sur referentiel session_id (qui raisonne en ET). Pipeline historique inclus dans calcul `worst_status` live.

**Lecon** : tout indicateur temporel/staleness sur dashboard trading doit utiliser le **referentiel marche** (UTC ou ET), pas le local browser. Sources historiques doivent etre flaggees `is_historical=True` pour exclusion du voyant live.

**Trigger prevention** : avant d'affirmer "bug session detection" ou "data feed mort", verifier empiriquement (1) heure UTC reelle vs affichee, (2) mtime fichier source, (3) si STALE/WARN vient pipeline historique vs live feed.

**Reviewed** : self (verif empirique mtime ES JSONL=12:50:01 UTC vs now_utc=12:50:57 UTC = age 55s OK)

**Fix** : `dashboard.js:1293` affiche `HH:MM ET / HH:MM UTC`. `app.py:319` ajoute flag `is_historical=True` sur pipeline parquet v4. `worst_status` calcule sur sources live uniquement. Cache bump v=119→v=120.

---

### 2026-05-06 13:30 — [REGRESSION_HEARTBEAT_MISSING / VALIDATION_MISS] — 3 bots tues 13-34× par jour, BOT_HEARTBEAT non emit depuis retire Bot 2 V1

**Contexte** : Jackson alerte "TROP DE REDEMARAGE" + bouton dashboard rouge/vert cyclique. Investigation logs watchdog : 3 services restartes en boucle :
- MIA-DataBento-Paper-V2 (Bot 3) : **34 restarts** today
- MIA-Brain-V6 (Bot 2 V6) : **34 restarts** today
- MIA-Paper (Bot 1) : 13 restarts today

Total = 81 restarts / 24h. Cycle observe : Bot tradait → watchdog kill 15min → broker garde position orpheline → reboot recovery → force close 60min plus tard → cycle.

**Cause racine** : `mia_watchdog.py:303 check_jsonl_last_bar_age` cherche l'event `BOT_HEARTBEAT` dans `events_*_paper*.jsonl`. **AUCUN des 3 bots actuels n'emit cet event**. Seul Bot 2 V1 (`databento_paper_trader.py`, mort depuis 05/05) l'emettait. Lors du retire Bot 2 V1, l'emit BOT_HEARTBEAT n'a pas ete transfere a Bot 2 V6 / Bot 3 / Bot 1.

**Impact production** :
- Bot 3 : 17 cycles `RECOVER + TIMEOUT_FORCE_CLOSE` aujourd'hui = trades parasitaires (DPL +21t cumulatif obtenu MALGRE)
- Bot 1 + Bot 2 V6 : 0 trades (pre-RTH) mais leur etat memoire perdu chaque restart

**Fix** : ajout emit `BOT_HEARTBEAT` toutes 30s dans la main loop des 3 bots :
- `databento_paper_trader_v2.py` : helper `_compute_last_bar_age()` via `load_last_bar()` (Databento source)
- `mia_paper_trader.py` : helper `_compute_last_bar_age_for_heartbeat(data)` via dashboard banner.ts_ms
- `mia2_brain_v6_databento.py` : meme pattern Bot 1
- **Fallback 99999.0** (pas 0.0) si erreur lecture = sentinel CRIT force watchdog kill (pas de mensonge "bot vivant" si data feed mort). Pattern aligne `check_stream_subscribe_alive`.

**Lecons** :
1. **Apres tout retire/migration de bot, grep tous les codes log emis par l'ancien dans le nouveau**. Dans cet incident, `grep "BOT_HEARTBEAT"` cross-codebase aurait revele le manque.
2. **Heartbeat doit etre PROACTIF** (le bot dit "je suis vivant + age data") pas REACTIF (watchdog deduit). Sentinel 99999 = "honnete" plutot que silence.

**Trigger prevention** : prochaine fois qu'un bot est retire OU migre, **grep cross-codebase** tous les codes log emis (`grep -E "_emit\(.|emit\(.\[\"']" CORE/<old_bot>.py | grep -oE "BOT_[A-Z_]+|[A-Z_]{8,}"`) pour verifier que les successeurs les emettent aussi.

**Reviewed** : code-reviewer 06/05 (verdict GO-AVEC-CHANGES, 1 critique fallback 99999 applique avant deploy).

---

### 2026-05-06 11:50 — [VALIDATION_MISS] — `realized_pts` (TARGET Triple Barrier) etait dans V5e_clean dataset utilise pour audits exploratoires

**Contexte** : Apres demande Jackson "ON CHERCHAIT PAS LE BON LABEL" + "FONDATION 100% FIABLE", audit foundation 7-phase comprehensive sur `V5e_clean_long.parquet` (351K bars × 405 cols, 12 mois mai 2025-avril 2026).

**Decouverte majeure** : Phase 3 leak detection a flagge `realized_pts` avec **rho_label=+0.98** (LEAK MASSIF). C'est le PnL realise du Triple Barrier = TARGET deguise en feature (cf `build_dataset_v4_dmp_databento.py:427` "realized_pts = PnL Triple Barrier (= TARGET, pas feature)").

**Ce qui a mal tourne** : Mon script `build_v5e_clean_with_long_ext.py` initial droppait les price/vol leaks (55 features) mais **pas les target leaks** (`realized_pts`, `exit_offset`, `t1`, `barrier_type`). N'importe quel modele LightGBM/XGBoost/etc entraine sur ce V5e clean aurait eu AUC artificiel ~1.0 (information du futur). Tous les audits exploratoires recents (audit confluence Long/Color, audit ChaseTopGate threshold 70 vs 60) etaient utilises avec V5e qui CONTENAIT realized_pts.

**Cause racine** : `build_v5e_clean_with_long_ext.py` ne synchronisait pas avec `train_v5_lightgbm.py:META_COLS` qui exclut deja realized_pts comme leak (audit ml-trainer 02/05). Donc mes scripts exploratoires utilisaient un dataset different de celui du training, contenant le leak.

**Lecon** : avant de creer un dataset "clean", **toujours synchroniser avec META_COLS / liste leaks du module training officiel** (`train_v5_lightgbm.py`). Tout dataset ML doit pass quality_validator + check vs liste leaks documentee.

**Sauve par chance** : `train_v5_lightgbm.py` (le code officiel) excluait deja realized_pts depuis 02/05. Aucun modele deploye n'a ete corrompu. **Mais** mes audits exploratoires (audit confluence Long/Color, etc.) auraient pu donner des verdicts faux positifs si executes avec le dataset pollue.

**Trigger prevention** : avant de creer un dataset cleane pour exploration ML, grep les META_COLS / leak lists des modules training existants (`grep META_COLS CORE/train_*.py`). Si feature dans META_COLS = drop obligatoire dans dataset exploration aussi.

**Action immediate** : drop 14 features supplementaires dans `build_v5e_clean_with_long_ext.py` (target leaks + lookhead leaks + swing architectural leak). Dataset final V5e_clean_long.parquet : 388 cols (vs 405 initial), audit foundation verdict SUSPECT_1 (drift informatif uniquement, 0 blocker).

**Reviewed** : self (audit foundation 7-phase) + ml-trainer 02/05 historique (qui avait deja detecte ce leak dans train_v5_lightgbm).

---

### 2026-05-06 03:30 — [DATA_MINING_TRAP_AVOIDED] — Audit confluence Long/Color Extension Lines : 3 GO_STRONG identifies, validation regime decomposition refute integration immediate

**Contexte** : Apres avoir code `add_long_extension_lines()` dans phase_b_plus_engine.py (6 features Extension Lines pour LONG UP/DN bars, equivalent au fix delta_div 07/04), audit walk-forward Lopez 5-fold sur 4 mois (jan-avril 2026) ES+NQ via `audit_confluence_long_color_levels.py` (200 combos {niveau veille / VWAP / MQ} x {LONG/COLOR zones}).

**Resultats audit** : 3 candidats GO_STRONG_NONSTAT (DSR>=0.95 + n>=100 + WR>=50% + folds_active>=6) :
- NQ LONG MQ_put_0dte + long_up_zones (n=1251 WR 57% mean +22.5t DSR 0.998)
- NQ LONG MQ_put_0dte + color_up_zones (redondant)
- ES SHORT pVWAP + color_dn_cluster (n=644 WR 54% mean +2.3t DSR 0.984)

**Validation finale** : 2 reviews ml-trainer (1ere NOGO 8 corrections, 2eme GO-AVEC-RESERVES R1+R2 appliquees) puis regime decomposition (`regime_decomposition_3_candidates.py`) → **3/3 ACCIDENT_REGIME** (concentration top2 mar+avr = 90% sur NQ, jan+fev = 67% sur ES).

**NUANCE methodologique** : sur NQ MQ_put_0dte, **4/4 mois positifs avec WR stable 53-59%** = edge **opportunistic event-based** (rare quand prix loin strike PUT 0DTE, frequent quand proche), pas accident regime au sens classique. Heure 13:00 UTC (open RTH) WR 66% mean +47t = pattern intra-session puissant.

**Lecon** : `concentration_top2 > 60% != accident regime automatique`. Si tous mois positifs + magnitude stable → edge **frequence event-driven**. Different de "1 mois explose, 3 perdent" (vrai accident).

**Trigger prevention** : avant verdict NOGO_NONSTATIONARY, **toujours decomposer mois par mois** (n_fires + WR + mean_net) ET creneaux horaires. Si `consistent_months >= 75% positifs` ET `WR std cross-mois < 10%` → reclasser en `EDGE_OPPORTUNISTIC` plutot que `NOGO`.

**Action** :
- Candidat 1 (NQ LONG MQ_put_0dte + long_up_zones) : **GO_PAPER_OBSERVE 30j** sizing 0
- Candidat 2 : DROP redondant
- Candidat 3 (ES pVWAP SHORT) : DROP magnitude faible (+1-3t apres slippage)
- Re-audit J+60 (juillet) sur 6 mois pour famille pVWAP SHORT avec filtre horaire 14-18 UTC
- Methodologie regime decomposition codee dans `CORE/research/regime_decomposition_3_candidates.py` (reutilisable)

**Reviewed** : ml-trainer (2 passes) + self (regime decomposition + verdict EDGE_OPPORTUNISTIC vs NOGO).

---

### 2026-05-05 18:30 — [PATTERN_11_AVOIDED] — Pattern false-stop entry au top fixé via ChaseTopGate (range_pos<60 LONG)

**Contexte** : Bot 1 a fait 3 trades NQ LONG aujourd'hui, **3 SL consécutifs**. Direction correcte (prix monte +244-300t après chaque SL) mais entry TOUJOURS au top du range RTH (rangepos=100% sur les 3). Le user a tradé après le bot et a eu TP, prouvant que c'est un problème de **timing entry**, pas de direction.

**Investigation** :
1. Mon walk-forward Lopez 5-fold sur SL widening (audit market-analyst recommandait SL=92t NQ) → **DSR=-0.45 NEGATIF** (3 folds catastrophiques -3897t/-3337t). NOGO SL widening.
2. Mon audit conditions d'entry TP vs SL sur 90 trades historiques :
   - `near_vwap` : delta -8% (CONTRE-PRODUCTIF, SL plus souvent près VWAP que TP)
   - `range_pos<60` : delta +25% (DISCRIMINANT FORT)
   - `n_consec_up<=1` : delta -27% (CONTRE-PRODUCTIF)
3. Filter OR (les 3) cumulé : **delta -4%** (les SL passent plus que les TP)
4. Filter B seul (range_pos<60 LONG-only) walk-forward Lopez 5-fold :
   - **DSR=0.72** > seuil Lopez 0.5 ✅
   - 3/5 folds positifs ✅
   - Total delta **+$1264** ✅
   - 33 SL évités, 6 TP perdus = ratio **5.5x** bénéfique
   - ES delta +$431 (6 SL évités, 0 TP perdu)
   - NQ delta +$832 (27 SL évités, 6 TP perdus)
   - SHORT laissé intact (filter symétrique aurait perdu 10 TP pour 16 SL = ratio 1.6x non-significatif)

**Pattern 11 V1 avoided** : on aurait pu coder filter OR avec 3 conditions inspirées des techniques pros (VWAP pullback, wick rejection, no-chase-trend). **L'audit empirique a montré que 2 sur 3 sont contre-productives**. Pattern 11 V1 = cascade de règles "qui semblent intuitives" mais que l'audit invalide.

**Cause racine du problème original** : Bot 1 lit `display_action` (ATTENDRE forcé après 2 bars freshness, fixé Option B 16:30 même jour), puis entre au prix courant sans filter d'entry quality. Sur jour ECO post-news, marché poussé au top du range = chase top systématique = SL hits avant continuation trend.

**Fix appliqué** :
- `CORE/mia_paper_trader.py` + `CORE/mia2_brain_v6_databento.py` : nouvelle étape funnel `6six_chase_top` après EntryQualityGate, bloque LONG si `range_pos >= 60`. Asymétrique : SHORT non filtré.
- `CORE/log_catalog.py` : `GATE_CHASE_TOP_LONG_BLOCK` (log block) + `GATE_CHASE_TOP_LONG_RESCUED` (audit J+7 false-block rate).
- `CORE/audit_chase_top_rescued.py` : script offline qui mesure MFE 30min post-block. Si MFE >= TP_target, le filter a raté un TP. Critère GO J+7 : false-block rate < 30%.
- Env vars `MIA_CHASE_TOP_GATE_ENABLED=1` (kill-switch) + `MIA_CHASE_TOP_THRESHOLD=60` (calibration).
- `CORE/tests/test_chase_top_gate.py` : 9 tests pytest, tous PASS.

**Lecon** :
1. **Audit empirique avant code** : sur 3 conditions "pratiques pro" (VWAP pullback, wick, no-chase), 2 étaient contre-productives sur ce dataset. Ne JAMAIS coder un filter sans mesurer.
2. **Walk-forward Lopez OBLIGATOIRE** sur tout fix de gate trading. Sans le walk-forward, j'aurais déployé filter OR -4% (perte) au lieu de filter B +$1264 (gain).
3. **Asymétrie LONG/SHORT** légitime quand audit montre comportement différent. Ne pas forcer la symétrie par esthétique.
4. **Tracking RESCUED indispensable** post-deploy. Sans `audit_chase_top_rescued.py` J+7, on ne saura pas si le filter rate des TP réels en out-of-sample.

**Trigger prevention** : avant de coder un nouveau gate trading :
- Audit empirique TP_pass% vs SL_pass% sur historique
- Walk-forward Lopez 5-fold MINIMUM (DSR > 0.5)
- Sample size n >= 100 (idealement >= 120)
- Tracking false-block rate post-deploy (script offline J+7)
- Kill-switch env var pour rollback sans redeploy

**Reviewed** : market-analyst (audit profond, recommandait SL widening rejeté empiriquement) + code-reviewer (GO-AVEC-RESERVES R1+R2+R3 traités) + walk-forward Lopez 5-fold local DSR=0.72.

**Suivi J+7 obligatoire (12/05/2026)** :
- Re-run walk-forward avec n>=120 trades. Si DSR chute < 0.5 → rollback `MIA_CHASE_TOP_GATE_ENABLED=0`.
- Run `python -X utf8 CORE/audit_chase_top_rescued.py --days 7`. Si false-block rate >= 30% → investigation rollback.

### 2026-05-05 16:30 — [OVER_ENGINEERING] — `_MAX_SIGNAL_AGE_BARS=2` étouffait 95% des signaux ACHAT PRUDENT actifs

**Contexte** : Bot 1 paper a fait 0 trade en RTH 13:30-16:00 UTC malgré 940 polls. Top reject `conseil_attendre: 366 (39%)`. User a demandé d'analyser le module.

**Ce qui a mal tourne** :
1. Fix 22/04 (`_MAX_SIGNAL_AGE_BARS=2`) destiné à corriger un **bug d'affichage UI** (signal ACHAT visible 15min sans pullback → FOMO trader humain) mais appliqué aussi au **gate de tradabilité bot** sans dissocier les usages.
2. Bot 1 lit `display_action` qui force ATTENDRE après 2 bars → signal ACHAT PRUDENT raw stable depuis 5+ min = ATTENDRE forcé même si conditions toujours valides.
3. Audit empirique 05/05 NQ : sur 197 GATE_CONSEIL_ATTENDRE, **188 (95.4%) avaient raw_action = ACHAT/ACHAT PRUDENT** actif (bull≥4 bear≤2). Top séquence 36 minutes consécutives où raw=ACHAT PRUDENT mais bot dit ATTENDRE.

**Cause racine** : 
- Confusion conceptuelle entre 2 préoccupations différentes : anti-FOMO display (UI) ≠ anti-chase execution (gate). Mêmes seuil = mauvais compromis.
- Pas de tests pytest sur la state machine `_evaluate_signal_freshness` → impossible de détecter le side-effect sur le gate paper.
- Pas de monitoring `expired_blocked_with_raw_active` → bug invisible pendant 13 jours.

**Lecon** : 
1. Quand un fix touche une state machine partagée par plusieurs consommateurs (UI + gates), **dissocier les seuils par usage** dès le design.
2. Tout fix sur logique de tradabilité doit s'accompagner de **logs traçabilité** (compteurs RESCUED/BLOCKED) pour audit J+1.
3. **Audit empirique** (combien de polls bloqués ?) avant ET après modif, pas juste tests unitaires.

**Trigger prevention** : avant tout fix qui force `action = ATTENDRE/IDLE` au runtime, vérifier :
- Le filter touche-t-il à la fois UI et gate paper ? Si oui → dissocier.
- Y a-t-il un compteur dédié dans le funnel pour mesurer l'impact ?
- Tests pytest couvrant les transitions état (NEW→PERSISTENT→EXPIRED) avec assertions sur les 2 sorties (display vs exec) ?

**Fix appliqué (Option B)** :
- `DASHBOARD/api/builders.py` : split `_MAX_SIGNAL_AGE_BARS_DISPLAY=2` (UI) + `_MAX_SIGNAL_AGE_BARS_EXECUTION=4` (gate paper). `build_conseil_global` retourne `action` (display, ATTENDRE après 2) ET `executable_action` (gate, ATTENDRE après 4).
- `CORE/mia_paper_trader.py` + `CORE/mia2_brain_v6_databento.py` : lit `executable_action` au lieu de `action` (avec fallback backward-compat).
- `CORE/log_catalog.py` : ajout code `GATE_CONSEIL_EXEC_RESCUED` pour mesurer empiriquement l'impact (signaux débloqués par seuil 4 bars vs ancien 2 bars).
- Fail-loud guard sur `sym=UNKNOWN` (R2 code-reviewer) pour éviter corruption cross-symbol du `_SIGNAL_STATE`.
- `DASHBOARD/tests/test_signal_freshness.py` : 10 tests pytest (PASS) couvrant les transitions et l'intégration.

**Résultat post-deploy 16:38 UTC** : Bot 1 a immédiatement pris un nouveau trade NQ LONG (3ème de la journée). Pattern jour défavorable persiste mais mécanique débloquée.

**Reviewed** : market-analyst (audit conceptuel) + code-reviewer (GO-AVEC-RESERVES, 4 réserves traitées : R1 workers=1 confirmé, R2 fail-loud UNKNOWN, R3 pytest 10/10, R4 log RESCUED).

### 2026-05-05 14:30 — [VALIDATION_MISS] — 7 features V4 quasi-mortes pendant des mois, fix +/-1 tick footprint

**Contexte** : User a demandé pourquoi V6 brain dépendait à 66% de features V4. Backtest-runner a flagué 7 features fire <2% nonzero sur 30k bars avril+mai 2026.

**Ce qui a mal tourne** :
1. `bn_absorb_*_at_level`, `bn_trapped_*_at_*`, etc. : fire 0.00-0.35% au lieu de baseline ~0.5-2% attendu
2. Cause racine : `add_absorption_features` et `add_trapped_traders_features` cherchaient `cells.get(h_price)` au prix EXACT du high. Sur Databento, le bar_high est souvent atteint par 1 seul trade → cellule unique avec faible volume → condition `ask > 10` jamais vraie
3. Sierra Chart formule officielle `AVAP(H,0)` capture la cellule TOP visuelle, équivalent au max sur 2 ticks au top du footprint
4. Pendant des mois : V6 brain comptait sur ces features pour scorer mais elles étaient effectivement neutralisées

**Cause racine** : 
- Pas de monitoring fire rate des features rare events
- Pas de capture SC reference pour valider la formule visuelle vs implémentation
- `bn_absorb_ask_raw : pure SC formula (rare ~0.07% ES)` → commentaire pris pour acquis sans vérification

**Lecon** : Pour toute nouvelle feature "rare event" dans le pipeline V4 :
1. **Validation empirique** post-build : mesurer fire rate sur 1 mois (RTH only).
2. **Comparison reference** : dessiner 5-10 events sur capture SC réelle vs implémentation. Si 50:10, formule cassée.
3. **Threshold attendu documenté** dans le code AVANT déploiement.

**Trigger prevention** : avant d'utiliser une feature "rare event" dans le brain V6 (ou tout brain), grep son fire rate sur le V4 actuel. Si <0.5% nonzero, ne pas la consommer dans le scoring.

**Fix appliqué (agent feature-engineer)** : 2 edits dans `CORE/phase_b_plus_plus_engine.py` :
- `add_absorption_features` lignes ~786-826 : scan zone [H, H-tick] (et [L, L+tick]) au lieu du prix exact
- `add_trapped_traders_features` lignes ~554-583 : idem

**Résultats post-fix (V4 avril 2026 RTH)** :
- ES `bn_trapped_buyers_at_resistance` : 0.22% → 5.33% (24×)
- ES `bn_trapped_sellers_at_support` : 0.09% → 6.87% (76×)
- ES `bn_trapped_*_raw` : ~1% → 17-18%
- ES `bn_absorb_*_raw` : 0-0.07% → 0.13-0.20% (2-3×)
- NQ : amélioration mineure (probablement threshold ABSORPTION_BID=20 trop strict pour NQ moins liquide → action future)

**Reviewed** : agent feature-engineer + Jackson. Fix déployé sur VPS, V4 avril+mai rebuild, MIA-LivePipeline restart.

### 2026-05-04 10:30 — [VALIDATION_MISS] — TradeAccount=Sim3 hardcode = cause des 7 trades orphelins Bot 3 nuit

**Contexte** : Bot 3 lundi matin → 7 trades TIMEOUT pnl=0 mfe=0 mae=0 sur Sim1 + position NQ 2@27911.75 + multiples TP/SL ouverts visibles dashboard 09:30. DPL: -456T.

**Ce qui a mal tourne** : 
1. `BOT/dtc_connector.py:cancel_order` declarait `trade_account: str = "Sim3"` en default param.
2. `_handle_order_update` OCO auto cancel ligne 724 appelait `self.cancel_order(opposite_cid)` SANS passer le trade_account → utilisait default "Sim3".
3. `_verify_cancel` ligne 753 hardcodait `"TradeAccount": "Sim3"`.
4. Bot 3 = Sim1, Bot 2 = Sim2, Bot 1 = Sim3. Tous les cancels OCO Bot 2/Bot 3 envoyes vers Sim3 → SC ne trouvait pas l'ordre → cancel ignore silencieusement.
5. Cote Python : Status=8 retourne par SC pour ID inconnu → tests croyaient "OK" → orphelins reels jamais detectes.
6. 4h de tests ce matin avec H1 (Use Attached Orders), H2 (Status=8 premature), H3 (Trade Simulation Mode bug), H4 (Type 210 systematique), H5 (RequestID manquant) avant de trouver H6.

**Cause racine** : code prod de production avec default param trompeur jamais audite. Le default Sim3 servait Bot 1 historiquement, mais quand l'OCO auto a ete partage entre les 3 bots, personne n'a verifie que le default convenait pour Sim1/Sim2.

**Lecon** :
- **Anti-pattern critique** : default param sur trade_account/symbol/account/instrument dans une fonction partagee multi-contexte.
- L'agent code-reviewer aurait du flagger ca lors du review initial OCO multi-bot.
- Le bug etait masque par les Status=8 retournes par SC sur ID inconnu (false positive).
- Tir croise sources projet 1 (Jackson) montrait `TradeAccount` toujours present, jamais default → indice manque.

**Trigger prevention** :
- AVANT tout deploy de fonction qui prend trade_account/account/symbol en param : verifier qu'il n'y a PAS de default value piege.
- Quand on a un Status=8 (Canceled) qui dit OK mais la realite est "ordre encore Open" : verifier le **TradeAccount du cancel** vs TradeAccount de l'ordre original.
- Tout cleanup d'ordre doit faire `request_position_blocking` apres pour valider le state reel, pas faire confiance au Status=8.

**Reviewed** : Jackson + agent general-purpose (audit independant) + tests empiriques Sim1 NQ 4 iterations.

**Fix deploye** : 04/05 11:00 — `BOT/dtc_connector.py` :
- Ajout `self._order_trade_accounts: dict` tracker
- `_handle_order_update` capture `msg.get("TradeAccount")`
- OCO auto cancel + `_verify_cancel` utilisent le TA correct
- `send_market_order` pre-register parent + TP + SL
- `cancel_order` ajout `RequestID` (alignement projet 1)
- `CORE/databento_paper_trader_v2.py:_bot3_check_timeout` : sequence anti-orphelin 8 etapes (R1+R2+R3+R5 + Type 209 fallback)
- Doc `.claude/rules/orphan-prevention.md` creee

**Validation post-fix** : NQ Sim1 pure Type 203 (sans Type 209/210 fallback) → Status=8 reel + qty_final=0 + DOM clean (Jackson confirme).

---

### 2026-05-03 15:00 — [VALIDATION_MISS] — Audit 3 bots revele Bot 2 omission deploy + V4 VPS degenere

**Contexte** : Apres deploy regime_engine 14:30 (Bot 1 + Bot 3 mode observe) + calibration 14:46 (grid search optimal), Jackson demande audit integration regime sur les 3 bots avec 1 agent par bot.

**Ce qui a mal tourne** : 3 audits agents ont revele :
1. **Bot 2 OMISSION CRITIQUE** : regime_engine PAS integre dans poll_cycle Bot 2 (oublie deploy 14:30). Bot 2 SetupEngine 11 setups = 9/10 RANGE-play, vulnerable aux jours TREND. Pattern de risque non detecte sans regime tagging.
2. **Bot 3 V4 VPS degenere** : V4 enriched Mai 2026 contenait seulement 8/18 features regime (pipeline non rebuild apres modif). compute_regime avec defaults retournait 99.9% RANGE / 0% actionable = logs degenere.
3. **Bot 1 calibration divergente** : Bot 1 lit dashboard build_regime_context (ancienne calibration vol_extreme=2.0) alors que Bot 3 utilise regime_engine OPTIMALE (vol_extreme=5.5). Logs J+1 inexploitables pour calibration mardi tant que dashboard non resynchronise.

**Cause racine** : auto-validation post-deploy 14:30 absente. Aurait du grep "BOT2_REGIME" dans le code apres deploy pour confirmer integration sur les 3 bots, pas seulement Bot 1 + Bot 3.

**Actions correctives appliquees** :
1. Bot 2 regime_engine ajoute (lignes 728-768 databento_paper_trader_v2.py + capture regime_at_entry sur trade)
2. V4 VPS rebuild Mai 2026 → regime_actionable 0% → 18.2% (target 15-25% atteint)
3. Refactor dashboard build_regime_context REPORTE mardi (cross-validation J+1 d'abord)

**Verifications post-actions** :
- Hash VPS 3 fichiers = local apres scp
- MIA-DataBento-Paper-V2 restart pid 8028 BOOT_READY 14:55:52
- 0 erreur import regime_engine

**Lecon meta** : meme avec 2 reviews code-reviewer (deploy + calibration), il a fallu un 3eme round (3 agents 1 par bot) pour detecter omission Bot 2. Pattern audit cross-bot apres deploy multi-bot OBLIGATOIRE = nouvelle regle.

**Trigger prevention** :
- Apres tout deploy multi-bot, lancer audit `grep <new_module>` dans chacun des bots
- Si bot N+1 omis, INCIDENT_LOG immediat + correction
- Si V4/V5 schema change, `head -1 vps:V4_*.parquet` pour confirmer features attendues

**Reviewed** : 3 agents code-reviewer paralleles (Bot 1 + Bot 2 + Bot 3) + self-correction

**CHANGELOG** : `DOCS/BOT_CHANGELOG.md` 2026-05-03 15:00 UTC

---

### 2026-05-03 14:30 — [Plan B regime_engine deploy MODE OBSERVE — anti Pattern 11]

**Contexte** : Jackson 03/05 "ON A NEGLIGER LA DETECTION DE REGIME". Workflow trade pro :
DIRECTION CLAIRE -> NIVEAU touch -> RECONFIRMATION -> TRADE. Code-reviewer matin a flagge
Plan A (28 features brutes pour 3 bots = Pattern 11). Plan B = 1 source unique regime_engine.

**Actions** :
1. CORE/regime_engine.py cree (374 LOC porting build_regime_context dashboard)
2. Pipeline build_dataset_v4 etendu (DMP_MQ_FIELDS 17->45 + 7 cols regime_*)
3. quality_validator etendu (NATURALLY_DIFFERENT + EVENT_BASED)
4. Bot 1 + Bot 3 integres MODE OBSERVE (log only, pas skip)
5. Tests parite dashboard 100% mode + 83% favor + 100% vol PASS
6. Code-reviewer 2 reviews (1ere : 4 reserves dont 3 fixes appliques R1.3/R3/R4 ;
   2eme : GO-AVEC-RESERVES Option A deploy minimal)
7. Deploy VPS scp + restart MIA-Paper + MIA-DataBento-Paper-V2
8. BOOT_READY OK, 0 erreur import

**Patterns evites** :
- Pattern 11 V1 (cascade rules duplicates) -> source unique regime_engine
- DATA_MINING_TRAP -> mode OBSERVE 5 jours avant activation skip
- AGENT_MISUSE -> 2 code-reviewer reviews avant deploy

**Reserves differees** (acceptables court terme) :
- R1.1+R1.2 bias drift (regime_engine bias proxy != compute_bias officiel)
- Bot 3 logs probablement vides J+1 (V4 VPS sans features regime DMP, calibration mardi)
- Calibration seuils (actionable 3% trop strict)

**Lecon meta** : Plan B (verdict agrege calcule once) > Plan A (features brutes exposees)
pour cohérence cross-bot et anti-Pattern 11. Mode OBSERVE = filet de securite avant skip.

**CHANGELOG** : `DOCS/BOT_CHANGELOG.md` 2026-05-03 14:30 UTC

**Reviewed** : code-reviewer x2 + Jackson validation Plan B

---

### 2026-05-03 12:52 — [CONTEXT_MISS] — Mauvaise lecture archi 3 bots Jackson : V2CLEAN ≠ Bot 2 + Bot 1 dashboard-follower

**Contexte** : suite audit paper bots 11:00, j'ai active V2CLEAN live Sim2 + stoppe MIA-Paper Sim3, sans verifier l'architecture cible Jackson "Bot 1 Sim3 DMP / Bot 2 Sim2 Databento / Bot 3 Sim1 Databento".

**Ce qui a mal tourne** :
1. V2CLEAN active sur Sim2 = doublon Bot 2 SetupEngine 11 setups (potentiel conflit lundi RTH).
2. MIA-Paper (Bot 1 dashboard-follower) stoppe au lieu de fix le crash-loop WinError 10038 par standardisation username DTC.
3. Bug "signaux date future 2026-05-05" Bot 1 non investigue avant decision arret.

**Cause racine** : non-consultation memory `project_bot_objectif_final.md` qui clarifie V2CLEAN = bot principal V2 R&D (primary + meta Lopez), distinct des 3 bots paper actifs. Aussi : non-consultation memory `feedback_extraction_expertise_jackson.md` (commencer par "montre-moi un trade concret" plutot que decisions architecturales unilaterales).

**Lecon** : si memory mentionne explicitement architecture (`project_bot_objectif_final.md`, `reference_vps_process_persistence.md`), VERIFIER avant toute decision deploy/stop service. La phrase "MIA-Paper crash-loop" ne signifie pas "stopper MIA-Paper" mais "investiguer la cause du crash et fixer".

**Trigger prevention** :
- Avant tout deploy/stop service VPS : grep `D:\TRADING_SIERRA_CHART_AUTO\.claude\projects\d--TRADING-SIERRA-CHART-AUTO\memory\` pour project_*.md mentionant le bot/service.
- Si crash-loop : investiguer cause racine (logs stderr, INCIDENT_LOG patterns) avant de stopper.
- Si bot "redondant" suspecte : confirmer avec Jackson l'architecture cible avant action irreversible.

**Resolution 12:52** :
- V2CLEAN reverted to dry_run (`nssm reset MIA-V2CLEAN-Bot AppEnvironmentExtra` + restart)
- MIA-Paper restart avec username DTC unique `MIA_PAPER_S3` + force restart (Stop-Service ce matin n'avait pas tue le process)
- Architecture finale conforme : 3 bots actifs (Sim1, Sim2, Sim3) + V2CLEAN dry_run R&D
- Bug "signaux date future" Bot 1 = investigation deferree (a faire apres confirmation crash-loop fix lundi)

**CHANGELOG** : `DOCS/BOT_CHANGELOG.md` 2026-05-03 12:52 UTC

**Reviewed** : Jackson (rappel archi via questions "petit controle")

---

### 2026-05-03 12:30 — [VALIDATION_MISS] — Pipeline v4_enriched dette : 100% NaN day_type/session/dist_ib pour 28-30/04

**Contexte** : Jackson demande replay Bot 3 sur jeudi 30/04 + vendredi 01/05 pour evaluer comportement reel hypothetique. Backtest 14m v3 a 0 trades 29/04 + 30/04 (mais 39 trades 01/05). Re-run replay specifique avril 2026 confirme 0 trades 29-30/04.

**Ce qui a mal tourne** : pipeline v4_enriched a bars 29-30/04 (1347 bars/jour NQ + ES) mais avec **100% NaN** sur features critiques (`day_type`, `session`, `dist_ib_high_pct`, `dist_ib_low_pct`). ES 28/04 aussi 100% NaN. NQ 01/05 = 78% NaN sur dist_ib_high_pct mais 20 trades quand meme generes.

**Cause racine** : pipeline `build_dataset_v4_dmp_databento.py` incremental (cf project_pipeline_incremental_backlog.md 01/05) traite le mois entier avec retard 30 min. Si batch echoue ou rate dernieres bars, features context restent NaN. La memory mentionne "Patch Option B en place (seuils Bot 2 tolerent)" = workaround actuel mais ne corrige pas le NaN.

**Lecon** : avant tout replay backtest, verifier qualite dataset pour la periode cible :
```
SELECT date, COUNT(*) as n, SUM(CASE WHEN day_type IS NULL THEN 1 ELSE 0 END) as n_null
FROM read_parquet('v4_enriched/symbol=X/...') GROUP BY date
```
Si n_null > 50% → impossible replay sur cette periode.

**Trigger prevention** :
- Quality_validator V4 doit detecter NaN systemique sur features critiques par jour
- Avant replay : run quality_validator.py sur dataset segment cible
- Pipeline v4 doit **fail-loud** si 100% NaN sur day_type/session (au lieu de produire silencieusement)
- INCIDENT_LOG entry refer to project_pipeline_incremental_backlog.md (refactor planifie hors trading)

**Implication Bot 3** :
- 30/04 + 29/04 : aucun replay possible
- 01/05 : replay partiel valide (39 trades sur features partiellement disponibles)
- En **prod live**, Bot 3 lit DMP JSONL direct (pas v4_enriched) → comportement different. Live aurait probablement trade ces 2 jours si DMP valide.

**Reviewed** : self (data quality check empirique)

**Lien** : `project_pipeline_incremental_backlog.md`, `project_dette_v3_purge_may2026.md`

---

### 2026-05-03 11:43 — [RESOLUTION VALIDATION_MISS 11:00] — V2CLEAN active live Sim2 + MIA-Paper stoppe

**Contexte** : suite incident 11:00 (3 paper bots non fonctionnels), Jackson exige paper actif end-to-end. Mode auto + agent reviews systematiques.

**Actions appliquees** :
1. **MIA-Paper service stoppe** (StartType=Manual) : crash-loop WinError 10038, polluait Sim3 avec ordres fictifs date future 2026-05-05.
2. **V2CLEAN code-reviewer** : verdict GO-RESERVES, 3 concerns HIGH (H1 1 max position/symbol, H2 on_connection_lost callback, M2 MIA_DTC_USER env).
3. **3 fixes appliques** :
   - `V2CLEAN/execution/order_manager.py:194-203` : garde 1 max position par symbol
   - `V2CLEAN/bot_main.py:1043-1071` : on_connection_lost callback → kill_switch CATASTROPHE
   - `V2CLEAN/bot_main.py:1075` : lit MIA_DTC_USER env
4. **Tests** : 13/13 V2CLEAN/tests/test_execution.py PASS + ast.parse OK + hash VPS=local apres scp.
5. **Config nssm V2CLEAN** : `MIA_BOT_LIVE_EXECUTION=1`, `MIA_TRADE_ACCOUNT=Sim2`, `MIA_DTC_USER=MIA_V2CLEAN_BOT`, `MIA_DTC_HOST=127.0.0.1`, `MIA_DTC_PORT=11099`.
6. **Restart service** : heartbeat post-restart confirme `execution_wired=true`, log stderr `MODE LIVE EXECUTION` + `DTC connected` + `models preflight OK` + `risk_state restored`.

**Etat final paper bots** :
- MIA-V2CLEAN-Bot (Bot 2 V2 ML LightGBM) → LIVE Sim2 ✓ (active 03/05 11:43)
- MIA-DataBento-Paper-V2 (Bot 2 V2 SetupEngine + Bot 3 in-process) → LIVE Sim1+Sim2 ✓ (deja live, confirme via BOOT_READY dtc=OK pas DRY_RUN)
- MIA-Paper Sim3 → STOPPED ✓

**Verification J+1 prevue** : lundi 04/05 RTH 13:30 UTC, verifier `V2CLEAN/logs/events.jsonl` contient au moins 1 `bracket_complete` apres premier signal PASS. Si 0 trade malgre 10+ PASS → bug bloquant a investiguer.

**Lecon meta** : protocole agent-review obligatoire (`.claude/rules/critical-tasks-review.md`) a empeche activation prod sans fix critiques. Sans code-reviewer, V2CLEAN aurait potentiellement ouvert 2 brackets simultanes sur meme symbol (H1) ou continue silencieusement avec DTC mort (H2).

**Reviewed** : code-reviewer (3 fixes high appliques) + self (deploy + verification heartbeat)

**CHANGELOG** : `DOCS/BOT_CHANGELOG.md` 2026-05-03 11:43 UTC

---

### 2026-05-03 11:00 — [VALIDATION_MISS] — Audit paper bots VPS revele 3 bots non-fonctionnels

**Contexte** : Jackson demande audit complet avant Asia 03/05 22:00 UTC. Etat suppose : Bot 2 + Bot 3 trade en paper. Etat reel : 0 trade vendredi 02/05 RTH sur les 3 paper bots.

**Ce qui a mal tourne** : 3 bots actifs mais aucun ne trade reellement :
1. **MIA-V2CLEAN-Bot** (Bot 2 V2 ML) : mode `dry_run_decision_only`, env `MIA_BOT_LIVE_EXECUTION` non defini → `execution_wired=false` → log decisions sans soumission DTC. 13 PASS / 2735 REJECT vendredi mais 0 ordre.
2. **MIA-DataBento-Paper-V2** (Bot 2 V2 SetupEngine + Bot 3 in-process) : 3 reboots 02/05 (deploys), DMP weekend stale (`last_bar_age 97000-137000s`), 0 SETUP_TRIGGERED ni BOT3_TIER_EVAL en logs `*_paper_v2.jsonl`. Trading file `trading_20260502_paper_v2.jsonl` n'existe meme pas.
3. **MIA-Paper** (Sim3) : crash-loop silent, WinError 10038 socket DTC mort, redemarre toutes les 30 min depuis 09:01 UTC. Genere signaux avec `bar_ts = 2026-05-05` (date future) = signaux fictifs polluants.

**Cause racine** : aucun monitoring effectif sur "trades effectivement emis" cross-bot. Heartbeat says alive mais ne dit pas "trades=N". Jackson croyait paper actif mais V2CLEAN dry-run by design + DataBento V2 attendant DMP + MIA-Paper crash-loop = 0 trades.

**Lecon** : un service nssm "Running" + heartbeat OK ne garantit PAS que le bot trade. Verifier obligatoirement :
- Existence fichier `trading_YYYYMMDD_*.jsonl` non-vide
- Au moins 1 `TRADE_OPEN` event par jour RTH ouvert
- Heartbeat doit exposer `trades_today` (pas seulement bars_processed)
- WinError 10038 = signal silent crash-loop (pas detecte par nssm car restart immediat)

**Trigger prevention** :
- Cron quotidien check : `(Get-ChildItem trading_$(Get-Date -Format 'yyyyMMdd')*.jsonl).Length > 0` sinon alerte Discord
- Standardiser `MIA_DTC_USER` distinct par bot (eviter collision username Sierra Chart)
- Heartbeat V2CLEAN : exposer `live_execution_active` clairement

**Actions correctives** :
- CRITIQUE : Stop MIA-Paper service (crash-loop + signaux fictifs)
- MAJEUR : Confirmer Bot 2 V2 + Bot 3 emettront signaux lundi 13:30 UTC RTH
- MOYEN : V2CLEAN live execution = projet separe (review + tests requis)

**Reviewed** : self-audit + general-purpose subagent cross-validate

**Rapport** : ce fichier + reponse session 03/05 11:00 UTC

---

### 2026-05-03 06:30 — [DATA_MINING_TRAP self-inflicted] — Bot 3 meta-labeler invalid methodologically

**Contexte** : Apres NOGO Phase 2 backtest brut Bot 3, Jackson demande approche meta-labeling Lopez ch.3 (au lieu de data mining). Script `CORE/research/bot3_meta_labeler.py` cree, walk-forward 12-fold, claim "NQ PF 1.47 / DSR 0.952".

**Ce qui a mal tourne** : claim invalide methodologiquement :
1. Train contient des donnees post-test (folds intermediaires) → leak structure modele meme avec val pre-test
2. DSR proxy = sharpe_pf / std_pf (faux : Bailey deflate des SR de returns, pas des PF)
3. n_trials=21 sous-estime massivement (reel = ~1680 essais)
4. Embargo en bars 1m (1440) sur evenements trades = mauvais
5. PF_net post-haircut 0.75x = 1.10 (< 1.4 seuil Lopez)
6. PF min fold 0.97 disqualifiant
7. 8/12 folds = bias selection (4 skipped car train_pre_test < 100)

**Cause racine** : meta-labeling utilise pour rattraper un edge sous-jacent inexistant (PF brut 1.02 = bruit pur). Pattern identique 28/04 mais cette fois cree par moi.

**Lecon** : un meta-labeler ne sauve pas un edge negatif. Si PF brut < 1.2 stable, le meta amplifie le bruit pas le signal. Pour valider meta-labeler, exiger :
- Train STRICT pre-test only (pas post-test, meme purged)
- DSR Bailey 2014 formule complete (pas proxy maison)
- n_trials reel = nb thresholds × nb folds × nb features
- Negative control test (permuter labels, pf_meta doit ≈ pf_brut)
- Walk-forward 12/12 complets, pas 8/12

**Trigger prevention** :
- Si PF brut median fold < 1.2 → meta-labeling = perte de temps
- Verifier strictement train_idx[< test_start] only
- DSR proxy interdit, utiliser mlfinlab ou implementer formule complete
- Negative control empirique obligatoire avant claim "valide"

**Reviewed** : code-reviewer (6 high concerns) + ml-trainer (NOGO 1/8 PASS) + self-incident reconnu

**Rapport** : `DOCS/BOT3_META_LABELER_REPORT.md`

---

### 2026-05-03 04:50 — [DATA_MINING_TRAP avoided] — Bot 3 backtest 14 mois NOGO Phase 2 universel

**Contexte** : Backtest Bot 3 round 5 sur 14 mois Databento (NQ+ES, 10116 trades). 2 niveaux NQ apparent GO (MQ_PUT_0DTE PF 2.10, IB_LOW PF 1.67). Pression psychologique potentielle "PF>2 sur 295 trades = GO Phase 2".

**Ce qui aurait mal tourne sans protocole** : promotion Phase 2 sur PF agrege seul → faux GO.

**Cause racine evitee** : application stricte 5/5 criteres BOT3_PHASE2_GATE.md + walk-forward 12-fold Pardo.

**Lecon** : walk-forward 0/18 stable invalide totalement les "GO apparents". PF agrege masque PF_min fold catastrophique (NQ MQ_PUT_0DTE PF_min 0.82, NQ IB_LOW PF_min 0.63). Haircut 0.75x Sim1->Live confirme : NQ IB_LOW tombe a 1.25 (FAIL).

**Trigger prevention** :
- Toujours walk-forward AVANT promotion, pas apres
- Critere "stable_pass" = PF median >= 1.4 AND PF min >= 1.0 AND std/median <= 0.4 (3 conditions cumulees)
- Si 0/N stable et PF apparents > 2.0 : signal regime-dependance, pas edge structurel

**Reviewed** : ml-trainer (NOGO Phase 2) + market-analyst (doctrinal Steidlmayer/Dalton confirme regime-dependance)

**Rapport** : `DOCS/BOT3_BACKTEST_REPORT.md`

---

### 2026-05-03 04:50 — [PATTERN_11 avoided] — ES Bot 3 DROP universel = bar size mismatch (pas TP/SL)

**Contexte** : 9 niveaux ES Bot 3 PF<1.4, TIMEOUT 80%+ sur tous. Tentation : recalibrer TP/SL ES (cherry-pick post-hoc).

**Ce qui aurait mal tourne** : recalibration TP/SL ES = cherry-pick interdit (manifesto anti-triche regle 11) + pattern 11 V1 (ajout layer hardcoded au lieu de comprendre cause structurelle).

**Cause racine reelle (market-analyst doctrinal)** : Lopez AFML ch.5 *"Trading bar size must match the volatility regime of the instrument"*. ES ATR ~30-60 ticks (vs NQ 150-200) sur timeframe 1min = bar size mismatch structurel. Pas reparable par recalibration parametres, refonte timeframe necessaire (5min minimum).

**Lecon** : avant de recalibrer parametres d'un setup qui echoue universellement sur un instrument, verifier d'abord adequation **bar size vs volatilite tick-normalisee** de l'instrument. Si mismatch structurel, drop instrument plutot que tuner.

**Trigger prevention** :
- Si TIMEOUT > 60% sur 5+ niveaux meme instrument : suspecter bar size mismatch
- Calculer ratio (ATR_ticks_NQ / ATR_ticks_ES) — si > 3x sur meme timeframe = mismatch probable
- Lopez ch.5 doit etre relu avant toute recalibration parametres

**Reviewed** : market-analyst (Steidlmayer/Dalton/Lopez ch.5 cite explicitement)

---

### 2026-05-02 00:30 — [VALIDATION_MISS] — Databento ne fournit PAS ohlcv-5m ni ohlcv-15m natifs

**Contexte** : Plan V3 SANS DETTE ML HTF supposait bars 5m / 15m / 1h natives Databento via `databento_backfill_batch.py --schemas ohlcv-5m ohlcv-15m ohlcv-1h`. Test sample 1 semaine lance pour valider format avant download 15 ans.

**Ce qui a mal tourne** : Databento SDK rejette `ohlcv-5m` et `ohlcv-15m` :
> "The `schema` was not a valid value of Schema. Use any of ['mbo','mbp-1','mbp-10','tbbo','trades','ohlcv-1s','ohlcv-1m','ohlcv-1h','ohlcv-1d','definition','statistics','status','imbalance','ohlcv-eod','cmbp-1','cbbo-1s','cbbo-1m','tcbbo','bbo-1s','bbo-1m']"

Schemas OHLCV dispos = **1s, 1m, 1h, 1d, eod uniquement**. Pas de 5m ni 15m.

**Cause racine** : suppose schemas natifs sans verifier API doc ni SDK avant planification. Pattern VALIDATION_MISS classique.

**Lecon** : avant tout plan reposant sur API externe, **valider schemas/endpoints disponibles via test mini-call** (pas via supposition / reading marketing material).

**Trigger prevention** :
- Avant tout plan utilisant API externe : test mini-call (1 sample minimum) AVANT de planifier
- Documenter explicitement les schemas API dispo dans le plan (preflight check)
- Le test sample lean methodologique (Jackson) a EVITE 45 min de download foire

**Fix** : resample 1m → 5m / 15m via DuckDB avec anti-lookahead strict (bars HTF fermes strictement AVANT bar 1m T). Code-reviewer ULTRATHINK avait deja flagge ce risque (Q3) mais on l'avait ecarte avec hypothese "natifs Databento". Hypothese fausse.

**Impact plan V3 SANS DETTE** :
- Plan revise : 1m natif + 1h natif + 1d natif Databento ; 5m + 15m via resample DuckDB anti-lookahead
- 728 features finales inchangees (juste source 5m/15m differente)
- Effort week-end +1h (anti-lookahead tests rigoureux)

**Reviewed** : self (test sample empirique a revele bug avant production)

---

### 2026-05-01 22:00 — [VALIDATION_MISS / SCOPE_CREEP] — LIVE override Bot 2 casse SLTPEngine (faille C, x10.8 SLTP fails)

**Contexte** : Refactor Bot 2 LIVE override deploy 14:57 UTC pour resoudre lag 30 min Databento Historical. `_enrich_bar_with_live` recalcule close + dist_mq_*_pct + dist_pdh/pdl_pct avec close LIVE mais **PAS** les distances aux walls T1+T2 utilisees par SLTPEngine. Validation refactor disait "score_consensus est rule-based, NON-APPLICABLE drift train/serve" → faux raisonnement, n'incluait pas SLTPEngine.

**Ce qui a mal tourne** :
- `dist_*` au parquet = distance signee en TICKS depuis `close_parquet` (verifie mia_sltp._check_wall_behind:815)
- LIVE override change `close` de la bar → `dist_*` reste relatif au vieux close
- Drift NQ -178 ticks observe au deploy → wall a `+20t` parquet en realite a `+198t` du close LIVE
- `_find_sl_wall` rejette walls hors `max_sl_ticks` → fallback FIXED → room_ratio 1.31 → VETO_SHORT bloque
- **Mesure empirique 01/05** : SLTP_NO_VALID_WALL **3.8% pre 14:57 UTC → 41.2% post (×10.8)**, VETO_SHORT_NO_WALL 197 occurrences (26% des bars), **1 SEUL trade pris sur 760 bars**

**Cause racine** : Refactor LIVE override n'a pas inventorie tous les consommateurs de `close` aval. L'audit s'est limite a score_consensus (vu comme "le decideur") mais SLTPEngine consomme indirectement via `dist_*` derivees du close. Pattern `VALIDATION_MISS` cumule au `SCOPE_CREEP` (refactor introduit nouvelles incoherences silencieuses).

**Lecon** : Tout refactor qui modifie `close` (ou n'importe quelle valeur de prix) DOIT inventorier toutes les features derivees (dist_*, ratios, *_pct) ET tous les consommateurs aval (gates, SLTPEngine, QG). Audit "drift train/serve" trop etroit si limite au modele decisionnel.

**Trigger prevention** :
- Avant deploy refactor LIVE override : grep `dist_` + `pct` + `ratio` dans la codebase pour identifier features derivees
- Inventaire consommateurs aval : grep imports + utilisations de la fonction modifiee
- Test empirique pre-deploy : drift +50t / -50t / -200t et verifier que SLTPEngine retrouve toujours des walls valides
- Au moindre doute sur audit refactor : code-reviewer + Plan agent (cross-check oblige) avant deploy
- Si refactor en cours touche au close : LIRE en plus mia_sltp.py + tous les fichiers dist_* dans CORE/

**Fix v1 (NOGO code-reviewer)** : Recalcul `dist_*` aux walls T1+T2 dans `_enrich_bar_with_live`. **REJETE** par code-reviewer apres verification empirique sur parquet V4 reel : seules 5/40 colonnes existent en BRUT (le reste en `_pct` ou manquantes). Fix v1 = no-op sur 35/40 walls (87.5%). Tests passaient grace a fixture synthetique injectant manuellement les cols → pattern `VALIDATION_MISS` cumule.

**Fix v2 (final)** : Stocker `_close_parquet_orig` dans `_enrich_bar_with_live` puis adapter `_inject_dist_ticks_from_pct` pour reconstruire ticks au moment du parquet PUIS ajuster `-delta_ticks` vers LIVE. Couvre les 28 walls `_pct` + 5 walls bruts. Math validee : `ticks_at_live = pct * close_parquet / (TICK*100) - delta_ticks`. 9/9 tests unitaires sur **parquet V4 reel** (eviter piege fixture synthetique). Cf `tests/test_live_bar_dist_recalc.py`.

**Reviewed** : code-reviewer NOGO sur v1 → redesign v2 → re-review pending

---

### 2026-05-01 14:30 — [DEPLOY_UNSAFE / OVERRIDE_AGENT] — Retrait STOP.flag override Plan agent (Jackson decision souveraine)

**Contexte** : Apres session crise 01/05 (-$1,526 paper / WR 25%), tous fixes appliques :
- QualityGate v3 deploye Bot 2 (45/45 tests + 2 reviews GO)
- Fix close_trade Bot 1 v2 deploye (5/5 tests + re-review GO-AVEC-RESERVES, scenario A race fill broker NON teste live)
- Dashboard v98 (UI message contradictoire fix)
- log_catalog 169 codes
- TRAILING_TR40_NQ_ENABLED=False (anti-naked)

**Plan agent recommande** : ATTENDRE DEMAIN PRE-RTH 14:00 Paris pour validation supervisée fixes en condition eveillee. Argument decisif : "Souverainete Jackson 22/04 mode 24h est sur DOCTRINE, pas micro-decision operationnelle post-bug. Skip 1 nuit ≠ rollback 24h."

**Decision Jackson 14:30 Paris** : RETIRER STOP.flag MAINTENANT (override conscient).
- Bots reprennent Asia + London + RTH avec QualityGate v3 + close_trade v2 actifs
- Validation scenario A race close_trade en conditions reelles (pas testee live)
- Risque accepte : data nocturne potentiellement biaisee si bug close_trade race se manifeste

**Garde-fous prepares** :
- Git tag snapshot : `crise-20260501-eod` (rollback code 1 commande)
- Script urgence : `/tmp/kill-bots-instant.sh` (re-creer STOP.flag)
- Dashboard v98 : bouton STOP visible kill_switch
- Criteres rollback automatique J+1 (5 ERROR/h, CLOSE_TRADE race detectee, 3 QUALITY_GATE_ERROR/h, -$500 cumule)

**Lecon** : La souverainete Jackson sur micro-decisions operationnelles l'emporte sur la recommandation agent. Documenter override dans INCIDENT_LOG = transparence.

**Trigger prevention** :
- Pour deploy futur post-bug critique : preparer garde-fous AVANT de toucher au flag
- Tester scenario non valide live = mode supervised observation J+1 obligatoire
- Si pattern "override agent + bug J+1" repete → escalation memory dediee (current count : 1)

**Reviewed** : Jackson (decision souveraine) + Plan agent (recommandation override)

---

### 2026-05-01 13:00 — [COMMENT_FALSE / VALIDATION_MISS / DEPLOY_UNSAFE] — Crise multi-bugs : trailing virtuel, close_trade naked, faux PnL dashboard, ZoneManager absent

**Contexte** : 30/04+01/05 PnL paper -$1,526 sur 61 trades, WR 25%. Jackson observe trade NQ SHORT avec state.json sl=27540.50 (mathematiquement impossible pour SHORT, doit etre AU-DESSUS) vs broker SL=27570.25 → desync. Puis trade ES SHORT @ 7253 avec TP/SL DISPARUS sur Sierra Chart = position naked. Jackson stop bots en mode crise + ULTRATHINK demande.

**Ce qui a mal tourne** :
1. **B1 P0** Trailing TR40_20 NQ Bot 1 : update virtual `pos["sl_price"]` SEULEMENT en memoire. **Le bracket SL broker reste a l'ancien prix**. Commentaire ligne 1792 explicite : *"NOTE paper Sim3 : on update pos[sl_price] (simu only). TODO LIVE : ajouter cancel + replace SL bracket via DTC"*. **TODO en prod 4+ semaines**. Backtest valide PF 0.99->1.32 = mensonge statistique (calcule sur simu, pas fills broker reels).
2. **B2 P0** `_close_trade(from_dtc_callback=False)` outcome="TP"/"SL" simu-triggered : cancel TP+SL brackets cote broker MAIS PAS de close_market sauf TIMEOUT. Commentaire incoherent *"trust broker fill via on_fill"* alors que les brackets viennent d'etre cancel. **Position naked possible**.
3. **B5 P2** `_verify_cancel` Timer 1s emit inconditionnellement `CANCEL_FAILED_RETRY` + `OCO_ORPHAN_DETECTED` meme quand cancel reussi. 10 faux positifs/jour pollue logs.
4. **Architecture** : pas de ZoneManager, pas de filtre BUY swing LOW / SELL swing HIGH, pas de hierarchie qualite (PREMIUM/STRONG/WEAK). Bot prend tout signal qui passe ENTRY_RULES. Regression vs V1 (30 strategies + zones + hierarchie).

**Cause racine** : *"Absence d'un contrat unique de cycle de vie d'un ordre, partage entre Bot 1, Bot 2, dtc_connector, state.json, et Sierra Chart"* (Plan agent verdict).

**Lecon** :
1. **TODO en prod = INTERDIT** sur fichiers Trading/Risk critical. Hook pre-commit `no-todo-in-core.sh` obligatoire.
2. **Backtest = CONTRAT broker reel** (Sim2 fills reels), pas simu virtuelle. Si simu ferme avant broker → backtest faux. Tests contract obligatoires CI.
3. **State.json != broker** : doit y avoir reconciler 60s qui detecte desync.
4. **Trader sans zones** = bruit. Pas pro. ZoneManager + 9 verifications pro requis (zone, flow, pieges, color, swing, divergences, imbalances, clusters, big orders).

**Trigger prevention** :
- AVANT toute modif `mia_paper_trader.py` ou `databento_paper_trader.py` : grep TODO LIVE/FIXME en CORE/BOT, bloquer commit
- AVANT deploy : tests contract broker Sim2 PASS obligatoire
- Heartbeat reconciler 60s state.json vs broker (Type 305 query)
- Tout filtre d'entree NEW : verifier d'abord audit empirique data-driven sur N>=20 trades

**Reviewed** : Jackson (mode crise) + code-reviewer agent + Plan agent (2 agents convergent Chemin B refacto OrderLifecycle FSM)

**Snapshot** : `BACKUPS/CRISE_20260501/` (states bot1+2, active_positions, jsonl trades+snapshots 01/05)

---

### 2026-04-29 18:00 — [VALIDATION_MISS / COMMENT_FALSE] — Bot 1 perte -$1156 NQ pendant FOMC sans gate eco / page calendrier decorative

**Contexte** : FOMC Federal Funds Rate 14:00 ET (= 20:00 Paris). Bot 1 NQ Sim3 tradait normalement.

**Ce qui a mal tourne** : Bot 1 a pris des trades pendant la chute verticale post-annonce FOMC. DPL daily NQ = -771 ticks = **-$1156** sur la seule session. La page `/calendar` du dashboard existait avec marketing "MIA bloque automatiquement le trading 15 min avant et 30 min apres ces evenements" mais **AUCUN code ne realisait ce blocage** : iframe TradingView decoratif, zero integration bot.

**Cause racine** :
1. **VALIDATION_MISS** : la promesse marketing du calendrier n'a jamais ete validee empiriquement. Personne n'a teste "le bot bloque-t-il vraiment pendant FOMC ?" avant qu'un FOMC arrive.
2. **COMMENT_FALSE** : page HTML disait "MIA bloque" alors que le code ne bloquait rien. Marketing menteur sur le statut reel du systeme.
3. Pas de monitoring "did the bot trade during high impact event ?" qui aurait flagge le mismatch.

**Lecon** : toute promesse fonctionnelle dans une UI doit etre couplee a un test empirique qui valide que le code FAIT vraiment ce qui est ecrit. "MIA bloque -15min/+30min" sans gate code = mensonge. Idem pour les pages "protection capital", "kill switch", "auto-flatten" — chacune doit avoir un test empirique qui declenche la condition et verifie l'action.

**Trigger prevention** : avant d'ecrire un texte UI qui annonce une protection automatique, repondre "OU est le code qui realise cette protection ?". Si pas de pointeur file:line, la protection n'existe pas et le texte est un mensonge marketing.

**Action corrective** : module `CORE/eco_calendar.py` cree (475 lignes) + endpoint API + gate Bot 1 + Bot 2 + 17 tests unitaires + frontend dynamique. Validate live : block FOMC actuel valide a 18:21 UTC apres deploy.

**Reviewed** : market-analyst (verdict Q1-Q5) + code-reviewer (P0+P1) + Jackson confirmation Option A

---

### 2026-04-29 12:00 — [VALIDATION_MISS] — Silent crash _recv_loop DTC : `dict.get(key, default)` retourne None si valeur null → 24h+ de fills perdus → position fantome Sim2

**Contexte** : Bot 2 (databento_paper_trader Sim2) presente desync state.json vs Sierra Chart broker pour la 2eme fois en 24h. Hier soir flatten manuel + cleanup state. Aujourd'hui 11:00 UTC, position fantome NQ -6 contrats P/L -729T sur Sim2 alors que state.json Bot 2 dit `active_positions: 0`.

**Ce qui a mal tourne** : audit forensique des err.log Bot 2 revele `DTC order update error: '>' not supported between instances of 'NoneType' and 'int'` repete des centaines de fois depuis 24h+. Origine : `BOT/dtc_connector.py:514` :
```python
filled_qty = msg.get("FilledQuantity", 0)  # null → None, pas 0
expected_qty = msg.get("OrderQuantity", 0)
if (filled_qty > 0 and ...):  # None > 0 = TypeError
```
Sierra Chart envoie ORDER_UPDATE intermediaires (status Open/Working) avec `"FilledQuantity": null`. Le default param de `dict.get()` ne s'applique PAS si la cle existe avec valeur null. Resultat : exception leve dans `_handle_order_update` → propage dans `_recv_loop` → fills finaux (status=7) PERDUS → state `active_positions` jamais mis a jour → position fantome.

**Cause racine** : misuse du pattern `dict.get(key, default)`. Le default ne s'applique QUE si la cle est absente. Si SC envoie explicitement `null`, le code recoit `None`. Pour avoir le default sur null, il faut `dict.get(key) or default`.

**Lecon** : pour tout JSON externe (DTC, API), utiliser le pattern `dict.get(key) or default` pour les valeurs numeriques, JAMAIS `dict.get(key, default)` qui ne protege pas contre les valeurs null. C'est subtle car ca marche en developpement (mock data sans null) mais casse en prod sur certains messages reels.

**Trigger prevention** : pour tout message DTC / API externe :
1. Quand on attend un nombre, utiliser `or 0` ou `or 0.0`
2. Tests unitaires obligatoires avec mock `{"key": null}` pour valider robustness
3. err.log monitor : si `TypeError.*NoneType` apparait → investigation immediate

**Fix execute** :
- `BOT/dtc_connector.py:497` : `fill_price = msg.get(...) or msg.get(...) or 0` (chain or)
- `BOT/dtc_connector.py:510-511` : `filled_qty = msg.get("FilledQuantity") or 0`
- `BOT/dtc_connector.py:527` : `is_filled = ... or ((msg.get("FilledQuantity") or 0) > 0 ...)`
- `BOT/dtc_connector.py:550` : `quantity = (msg.get("FilledQuantity") or msg.get("OrderQuantity") or 0)`
- Deploy VPS partage Bot 1 + Bot 2
- Restart les 2 bots
- Surveillance err.log : 30s sans nouvelle erreur post-fix ✓

**Impact** : 2 positions fantomes en 24h, total perte mesuree -$835 sur Sim2 paper (heureusement pas de live). Sur compte prop firm 50K eval = compte mort en 1 trade.

**Reviewed** : code-reviewer (GO-AVEC-RESERVES → reserves traitees inline) + Jackson recadrage initial Bot 2

**Pattern observed** : ce bug a `_recv_loop` silencieux exception est **identique** au pattern documenté dans `feedback_validation_miss_patterns.md` — code defini (le filtre fill partiel) mais qui plante en production sans alerte. Les fills perdus sont la conséquence visible d'un bug invisible (TypeError silencieusement avalee dans une exception generique du recv loop).

**Documentation associee** : entry `BOT_CHANGELOG.md` 2026-04-29 (mandatory CLAUDE.md fix moteur execution).

### 2026-04-28 21:00 — [DATA_MINING_TRAP] — Audits cluster cross-family + deep patterns produisent "edges" qui sont du noise (5/5 NOGO walk-forward Lopez)

**Contexte** : Jackson demande recherche patterns invisibles a l'oeil nu sur features BN+microstructure+contexte (parquet v5e 313j × 454 cols). 2 audits successifs (cross-family + deep ULTRATHINK) sortent ~600 combinaisons testees, 5 candidats top avec edge annonce +14-19pp.

**Ce qui a mal tourne** : ml-trainer walk-forward 12 folds + DSR Lopez = **5 NOGO sur 5**. DSR maximum = 0.09 (Lopez exige >0.5). Causes :
- Multiple testing : 600 hypotheses sans Bonferroni → bonnes hypotheses noyees dans bruit
- Concentration regime catastrophique : cluster #2 = 30 fires sur 30 dans 1 SEUL mois (mars 2026), artefact de la disponibilite MenthorQ pas un edge
- Drawdowns ingerables : cluster #3 = 745 ticks (= -$1490 sur 1 NQ micro)
- Sample size sous-dimensionne : 30-38 fires/an = 2.5/mois, Lopez exige 100+
- Costs dominants : cluster #4 ES SELL = +1.2 ticks brut - 2 ticks costs = **-0.76 tick net**

**Cause racine** : audit one-shot type "filter par |edge|>=5pp + n>=30 + Sharpe>=0.15" SANS walk-forward DSR = data mining classique. Le DSR Lopez avec haircut multiple testing transforme +17pp annonce en 0.09 reel = noise pur.

**Lecon** : tout audit qui produit des candidats "edges" DOIT obligatoirement etre suivi de :
1. Walk-forward fold-by-fold (12 folds chronologique min)
2. DSR (Deflated Sharpe Ratio) avec n_strategies_tested correctement renseigne
3. Sample size 100+ fires par strategy
4. Verification stationnarite (concentration temporelle <33% sur 1 mois)
5. Costs inclus (slippage 1-2 ticks par trade)

Sans ces 5 controles : audit = data mining noise, pas signal.

**Trigger prevention** :
- AVANT toute affirmation "j'ai trouve un edge X% sur cluster Y", check : walk-forward 12-fold OK ? DSR > 0.5 ? n >= 100 ? concentration < 33% ? costs inclus ?
- AVANT integration cluster en strategy/score : ml-trainer mandate avec verdict GO/NOGO + DSR + walk-forward
- AVANT enthousiasme sur "+17pp edge" : rappeler la formule "audit_one_shot_winrate × DSR_haircut = realite ≈ 0"

**Fix execute** :
1. Memoire dediee creee `feedback_data_mining_trap.md` (escalation 1ere occurrence promue immediate vu severite)
2. Nouvelle categorie `DATA_MINING_TRAP` ajoutee aux categories autorisees INCIDENT_LOG
3. Reference ajoutee a `.claude/rules/critical-tasks-review.md` (critere 8 backtest etendu)
4. Snapshot v3 full features capture toutes les data → permet ML LightGBM training (approche correcte vs hardcode clusters)
5. Drop des `_fwd1` lookahead confirme (audit precedent)

**Reviewed** : ml-trainer (verdict 5 NOGO + DSR detail) + Jackson (validation OUI capitalise lecon)

**Pattern 11 V1 reproduit** : exactement le meme piege que V1 ("11 layers gate cascading sur backtest"). 1 an plus tard, je reproduis le meme piege au niveau audit (chercher cluster qui matche backtest sans validation OOS). Categorie `DATA_MINING_TRAP` est cousine de `PATTERN_11`.

### 2026-04-28 18:50 — [VALIDATION_MISS+CASCADE] — Sim2 incident orphan/double-entry + pipeline fige

**Contexte** : 17:17 UTC, Jackson observe sur Sierra Chart Sim2 :
1. ES double entree BUY 6 contracts au lieu de 3 (avg position decalee, TP visuellement loin)
2. NQ ordre orphelin SHORT 3 contrats au lieu d'etre flat apres TP fillé
3. Bot a tradé sur bar 16:10 alors qu'il etait 17:17 UTC (bar agee de 1h+)

**Ce qui a mal tourne — 4 niveaux de root cause en cascade** :
1. **Pipeline VPS** : ce matin j'ai deploye `live_pipeline_loop.py --phase-b-every 1` SANS deployer la chaine Phase B (14 fichiers Python manquants : `build_dataset_v4_phase_b.py`, `phase_b_helpers.py`, `phase_b_*.py`, `edge_zones_engine.py`, `extension_lines_manager.py`, `footprint_builder.py`, `market_profile_rolling.py`, `phase_d_dalton_levels.py`, `sessions_swings_engine.py`, `value_area_running.py`). Phase B fail rc=2 a chaque iter → parquet enrichi fige sur 16:10.
2. **Pipeline `--force` manquant** : `databento_download.py:64` SKIP si `data.dbn.zst` existe. Pipeline relance toutes les 5min mais le download SKIP → JAMAIS de mise a jour intra-day. La 1re iter du jour telecharge jusqu'a `now-30min` puis plus rien.
3. **Bot callback fill JAMAIS attache** : `databento_paper_trader.py:438-439` faisait `if hasattr(self.dtc, "register_fill_callback"):` mais cette methode n'existe PAS sur DTCConnector (le pattern correct est `self.dtc.on_fill = ...`). `_on_dtc_fill` JAMAIS appele → orphelins systematiques + state.json jamais nettoye.
4. **Bot `cancel_order` sans ServerOrderID** : meme apres avoir state.json avec les `tp_cid/sl_cid`, le cancel echoue car `_server_order_ids` est in-memory only. Au boot le dict est vide → cancel envoye sans ServerOrderID → SC ignore silencieusement (cf `fix_oco_orphan.md` 02/04).

**Cause racine** : pattern `VALIDATION_MISS` repete (4 fois en cascade dans la meme deploy ce matin). Modifier le caller (live_pipeline_loop) sans verifier que les targets (Phase B chain) existent en prod. Et inventer une API cote bot databento (`register_fill_callback`) sans tester si elle existe vraiment dans DTCConnector.

**Lecon** : pour TOUTE deploy d'un caller, verifier empiriquement que les dependances sont presentes ET que les API utilisees existent reellement. `hasattr()` qui retourne False peut masquer un bug majeur silencieusement.

**Trigger prevention** :
- Avant deploy d'un caller : `grep -r "from <target> import"` + verifier path VPS
- Pour callbacks : verifier signature reelle dans le module reference (pas `hasattr` defensif aveugle)
- Toujours tester empiriquement le **flow complet** (pas juste l'init) — ouvrir une position en dry-run, kill le process, relancer, observer le state file et les logs

**Fix deploye** : 14 fichiers SCP + 8 fixes bot + 3 fixes pipeline + 6 codes catalog + threshold 600s → 2400s + atomic write tmp+replace + `_rotate_day_if_needed` + storm detection BAR_KEY_PARSE_FAIL. Cf `BOT_CHANGELOG.md` 2026-04-28 18:50.

**Pattern** : 4 audits code-reviewer successifs (NOGO → 3x GO-AVEC-RESERVES). **Sans ces audits, j'aurais redeploye 2 fois du code casse en prod**. Le reviewer m'a sauvé empiriquement.

**Reviewed** : code-reviewer (4 audits) + Jackson directe (validation strategique "zero dette")

**Verification post-deploy** :
- `BAR_STALE_SKIP age=8472s` (bar 16:10) ✅
- Pipeline iter 1 OK : 1092 bars × mq=26.9% × derniere bar 18:11 (au lieu de 0% × 16:10) ✅
- `[NQ] 18:11:00 close=27130 bull=4 → BUY → OPEN parent=MIA_P_be1c4e` ✅

### 2026-04-28 12:00 — [DATA_LEAK_CRITIQUE] — sess_high/close_eod backfill pollue pipeline ML (decouverte ULTRATHINK)

**Contexte** : pendant ULTRATHINK review meta-labeling NQ_buy v5d, ml-trainer a detecte data leak severe.
**Ce qui a mal tourne** : `CORE/build_dataset_v4_phase_b.py:186-188` utilise `sess_high = grp["sess_high"].iloc[-1]` et `close_eod = grp["close"].iloc[-1]` pour calculer `day_type` et features Game Changers. **Ces valeurs sont en FIN DE JOURNEE** broadcast sur tout le jour (391 bars). Lookahead pur. Verifie : `day_type` nunique=1 par jour pour les 391 bars d'une journee.
**Cause racine** : version backfill du Game Changers a leak temporel, version live (game_changers.py:568-570) est OK.
**Lecon** : feature broadcast-by-day = lookahead garanti si calcule depuis valeur fin-de-jour. Toujours verifier dans backfill que features dependantes de la session sont calculees `up to bar i` only.
**Trigger prevention** : avant tout meta-labeling ou retrain, audit features `day_type`, `open_type`, `profile_shape`, `trend_day_probability` pour s'assurer qu'elles ne reGardent pas le futur.
**Fix requis (urgent)** : 
  - `build_dataset_v4_phase_b.py:186` : remplacer `grp["sess_high"].iloc[-1]` par expanding max
  - `build_dataset_v4_phase_b.py:188` : meme fix sur close_eod
  - Re-build v4_enriched → re-label v5 → re-train primaries
  - **Impact attendu** : effondrement potentiel des PF v5d primary (1.59 NQ_buy peut tomber a 1.0)
**Pattern** : 4eme lucky bug en 13h (apres PD_LEVELS, analyse causale, baselines lucky 25/04). Mais **LIVE PROOF 24/04 montre que pipeline actuel marche** (PF 2.64 paper) DESPITE le leak. Hypothese : leak existait deja dans v3 25/04 → primary appris a "matcher day_type final" mais en live, day_type est calcule from session-so-far → similar enough.
**Reviewed** : ml-trainer ULTRATHINK
**Decision Jackson** : keep paper trading current pipeline, fix leak en parallele (apres validation 5j paper)

### 2026-04-28 11:55 — [LIVE_PROOF_OK] — Paper trading 24/04 NQ : PF 2.64 / WR 61.5% / +$468 sur 3 micros

**Contexte** : apres serie de NO-GO methodologiques (PD_LEVELS, analyse causale, lucky models), Jackson rappelle que le bot a tradé en live mode paper le 24/04 (vendredi).
**Resultat** : analyse logs `LOGS/trading/trading_20260424_paper.jsonl` (13 trades NQ LONG) :
- **WR 8/13 = 61.5%** (6 TP + 2 timeout positifs + 5 SL)
- **Total PnL +312 ticks/contract**, +$468 sur 3 micros NQ
- **PF estime 2.64** (388 wins / 147 losses)
- 193 signaux generes, 13 acceptes (6.7% acceptation rate via filtres MTF + confidence)
- 9 rejets `sltp_no_wall` = Smart SL Wall (codé, 12 tests) sauverait 5% trades supplementaires
**Cause racine** : malgre les "lucky models" suspect en backtest, le **systeme entier (primary 25/04 + filtres MTF/confidence + paper trader)** produit un PF 2.64 reel en live. Le primary seul en walk-forward = PF 2.39 (matches). L'edge n'est pas dans le primary seul mais dans le **systeme assemble**.
**Lecon** : la performance walk-forward (avec simulateur simplifie) est **borne inferieure** de la performance live (avec gates MTF + confidence + risk manager). Ne PAS rejeter un model parce qu'il a regression sur dataset different — tester en paper trading reel est la verite.
**Trigger prevention** : avant rejection d'un baseline, verifier s'il a un track record live paper. Si oui, le track record live PRIME sur backtest theoriques.
**Fix** : bot autonome paper trading reste actif, backups PRODUCTION_BASELINES preserves, plan recadre vers Smart SL Wall integration + 5 jours paper validation avant live.
**Reviewed** : Jackson (recadrage explicite "ON A TRADER VENDREDI PASSE")

### 2026-04-28 11:25 — [LUCKY_MODELS] — NQ baselines 25/04 sont LUCKY sur fenetre 70j v3, regression sur 12 mois v5d

**Contexte** : pour faire meta-labeling sur NQ_buy CAUTION → GO, j'ai re-train NQ sur v5d (12 mois) en pensant trouver une perf comparable a PRODUCTION_BASELINES (NQ_sell PF 2.39 GO, NQ_buy PF 2.13 CAUTION) qui sont en realite v3 25/04.
**Ce qui a mal tourne** : sur v5d 12 mois (5x plus de data), MEME pipeline donne :
- NQ_buy : PF 1.59 (vs 2.13 v3) — regression -25%, NO-GO
- NQ_sell : PF **0.83** (vs 2.39 v3) — **DESASTRE -65%, NO-GO catastrophique**
**Cause racine** : v3 = backfill 70j etroit avec 264 features. v5d = 12 mois Lopez-compliant 165 features. Sur fenetre etroite avec beaucoup de features, **overfit dispar fait des "GO" Lopez visuellement** (DSR 1.0 sur 32K bars = 8 folds courts). Sur 12 mois (351K bars / 43 folds), **edge structurellement absent**.
**Lecon** : "GO Lopez" sur petit dataset (70j) = risque LUCKY MODEL. Toujours valider sur dataset le plus long disponible (12 mois minimum). Lopez ch.16 = plafond empirique 1m bars edges, coherent avec l'absence d'edge 12 mois.
**Trigger prevention** : si modele a "GO Lopez" sur dataset < 90 jours, **suspect par defaut**. Re-train sur dataset >= 6 mois avant de croire le verdict.
**Fix** : nouveaux configs v5d sauves dans BASELINE_27042026 (NO-GO honnetes 12 mois). Configs v3 25/04 restent dans PRODUCTION_BASELINES (lucky possible). Decision Jackson en attente : (a) accepter le risque et deploy paper avec 25/04 ou (b) accepter qu'on n'a pas d'edge ML solide et pivot.
**Pattern detecte** : 3eme lucky bug en 12h apres PD_LEVELS (nuit) + analyse causale (matin). L'approche rigoureuse Lopez detecte systematiquement ces pieges.
**Reviewed** : self diagnosis empirique

### 2026-04-28 11:00 — [VALIDATION_MISS] — Analyse causale v1 ES BUY/SELL/NQ BUY/SELL : 4 lucky bugs confirmes Lopez

**Contexte** : suite NO-GO PD_LEVELS de la nuit, Jackson demande de chercher meilleurs parametres ES BUY via analyse causale. v1 du script `analyze_all_models_winning_patterns.py` annonce PF 4.08 ES BUY / 3.31 NQ SELL / 2.87 NQ BUY / 2.71 ES SELL.
**Ce qui a mal tourne** : ml-trainer review v1 NO-GO (PnL proxy faux + cherry picking 560 tests + zero OOS + pattern 11). v2 Lopez-compliant apres ULTRATHINK review (purge gap + skewness empirique + DSR + walk-forward 70/30) → **0/5 combos GO sur ES BUY, ES SELL, NQ SELL. 1/5 GO sur NQ BUY** (is_in_us_after=1 AND day_type<=2, PF test 1.93 mais multiple testing residuel = 1 false positive attendu sur 20 tests).
**Cause racine** : meme structure que lucky bug PD_LEVELS la nuit. PnL proxy v1 utilisait `realized_pts` du labeler reconcilie BUY/SELL → biais directionnel systemique. Baseline "PF 1.99 ES BUY" v1 etait artefact du proxy ; baseline reelle = **PF 0.93** (perd avec K_SL=1.5/K_TP=3 + cost).
**Lecon** : avant tout test causal sur features, valider le proxy de PnL avec **simulation OHLC-real BUY-only / SELL-only** (sans reconciliation label). Toujours appliquer 4 actions Lopez : (1) PnL OHLC-real, (2) walk-forward 70/30 + purge gap horizon, (3) bootstrap CI 95%, (4) DSR avec skew/kurt empiriques.
**Trigger prevention** : si analyse causale donne baseline > 1.5 sur "BUY systematique chaque bar" sans filter = **suspect** (peu probable que rentrer aveugle gagne avec couts). Verifier le proxy AVANT de croire les TOP combos.
**Fix** : `CORE/research/analyze_all_models_v2_lopez_compliant.py` corrige les 4 actions + 3 corrections ULTRATHINK. Resultat = 1/20 GO seulement, ce qui est **exactement** ce qu'on attend statistiquement par hasard a α=0.05.
**Reviewed** : ml-trainer v1 NO-GO + ml-trainer v2 ULTRATHINK GO-AVEC-RESERVES (3 corrections appliquees)

### 2026-04-28 01:25 — [VALIDATION_MISS+COMMENT_FALSE+CONTEXT_MISS] — Lucky bug PD_LEVELS convention echangee : PF 8.19 NQ FAUX

**Contexte** : Voie 2 Plan B Rules PD attentiste implementee (170 LOC + 16 tests TDD + 254j backtest). Resultats apparents : ES GO PF 35t, NQ GO PF 8.19. Annonces a Jackson comme GO PAPER TRADING.
**Ce qui a mal tourne** : code-reviewer dispatch a posteriori a detecte 3 bugs critiques :
1. Convention DMP : `CalcDistTicks` retourne `(level - price) / tick_size` en TICKS. Mon code Python faisait `level = price + dist` sans `* 0.25` → erreur 4x ET signe.
2. Parquet v5d utilise convention DIFFERENTE (`dist = close - level` en POINTS, signe inverse).
3. Tests fixtures synthetiques utilisaient la meme convention que le code → tautologie, ne testaient rien.
Resultat empirique : PVAH < PVAL dans tous les fichiers genere, PSD+1 = PSD-1 = PDC. Backtest sur niveaux ECHANGES = lucky bug.
**Cause racine** : 
- (a) **VALIDATION_MISS** : pas verifie empiriquement la convention sur 1 vrai fichier. Affirmation "convention uniforme" non etayee.
- (b) **COMMENT_FALSE** : comment dans pd_levels_extractor "verifie empiriquement sur 27/04 NQ" etait faux.
- (c) **CONTEXT_MISS** : aurais du grep `CalcDistTicks` source DMP avant d'ecrire la formule.
**Lecon** : avant de coder une formule de feature derivee, TOUJOURS verifier empiriquement avec 2-3 valeurs absolues connues (e.g. JSONL bar reelle + chart visuel). Les tests fixtures synthetiques NE remplacent JAMAIS les tests sur donnees reelles.
**Trigger prevention** : si un test "passe" 22/22 mais le resultat backtest est trop beau (PF > 5 sans precedent), suspecter un lucky bug et faire AUDIT a posteriori AVANT d'annoncer GO.
**Fix** : reecrit `backfill_pd_levels_from_parquet.py` pour utiliser colonnes ABSOLUES (`cur_vah`, `cur_val`, `vwap_d`, `vwap_d_sd1u/d`). Niveaux maintenant coherents (PVAH > PVAL). Resultat reel backtest : ES NO-GO PF 0.51, NQ NO-GO PF 0.005 = rules attentistes NE FONCTIONNENT PAS sur la data 254j.
**Reviewed** : code-reviewer (NO-GO impitoyable, 3 categories incident simultanees)

### 2026-04-27 23:30 — [AGENT_MISUSE] — Patch fillna v5d deploye sans review agent prealable

**Contexte** : Suite bug NQ Preflight FATAL (97% NaN trapped), j'ai code `CORE/patch_v5d_fillna_nearest.py`, applique sur 2.6M valeurs ES+NQ, et relance Optuna v4 — TOUT sans dispatcher quality-auditor / code-reviewer / ml-trainer.
**Ce qui a mal tourne** : Modification pipeline ML critique (datasets v5d in-place, 13 features impactees) sans validation agent. Critere 2 + 7 de `.claude/rules/critical-tasks-review.md` satisfaits (ML Pipeline + Irreversible — datasets ecrases). Si fillna(100.0) cree une distribution toxique LightGBM, je le verrai seulement APRES 30 min de training perdu.
**Cause racine** : Auto-mode + sense d'urgence "Optuna doit relancer ce soir" → court-circuite protocole. Jackson m'a fait remarquer.
**Lecon** : Auto-mode ne dispense PAS du protocole agent review. Pipeline ML = critique = review OBLIGATOIRE meme en mode autonome. Si Optuna en attente, lancer review en parallele plutot que skipper.
**Trigger prevention** : avant tout patch dataset v5d/v5b/v5c (in-place ou nouveau), dispatch quality-auditor (5 criteres V2) ET ml-trainer (impact sur signal ML) en parallele AVANT relance training.
**Fix** : review a posteriori dispatch maintenant + integrer dans next session protocol "Auto-mode + critical task = double-check protocol obligatoire".
**Reviewed** : Jackson (m'a recadre)

### 2026-04-27 23:25 — [VALIDATION_MISS] — NQ Preflight FATAL silencieux 4 runs Optuna : trapped_*_nearest_pct 97% NaN

**Contexte** : Optuna v3 (4 fixes ml-trainer appliques) tourne sur v5d apres re-inclusion 16 BN features (Jackson Option B). 4 modeles attendus. ES BUY/SELL OK, NQ FATAL.
**Ce qui a mal tourne** : `[FATAL] Preflight NQ : 2 erreurs bloquantes — dist_trapped_buyers_nearest_pct 97.1% NaN, dist_trapped_sellers_nearest_pct 96.2% NaN`. Le bug etait deja present sur v2/v3 mais j'ai laisse 3 runs Optuna se terminer sans investiguer NQ.
**Cause racine** : zones trapped traders sont rare-event sur NQ (97% absence). NaN = "pas de zone proche" = info SEMANTIQUEMENT VALIDE mais Preflight strict 90% NaN bloque. J'ai accepte le FATAL comme normal pendant 3 runs sans creuser.
**Lecon** : si un FATAL Preflight survient sur un symbole pendant que l'autre passe, INVESTIGUER IMMEDIATEMENT (cause asymetrie ES/NQ = info). Ne jamais ignorer un FATAL en pensant "ES suffira" — Jackson trade ES ET NQ.
**Trigger prevention** : `[FATAL] Preflight {symbol}` dans log = STOP, investiguer, fixer, relancer. Jamais "on continuera plus tard".
**Fix** : `CORE/patch_v5d_fillna_nearest.py` fillna(100.0) sentinelle "tres loin" sur 13 dist_*_nearest_pct (preserve l'info "absence" comme signal, gere par LightGBM splits binaires).
**Reviewed** : self (autonomous mode)

### 2026-04-27 21:30 — [LEAK_RESOLU] — Fix anti-leak v5b validé empiriquement : SHAP top 10 propre + edge ML 1.09 confirmé

**Contexte** : Suite incident 20:30 (leak ovn_high/ib_high/open_830/930), 3 fixes appliqués + dataset v5b (masks NaN sur 68% OVN active + 52% pré-IB + 42% pré-09:30).
**Résultats validés empiriquement** :
- **ML v5b PF 1.09** vs v5 PF 1.11 (quasi pareil) MAIS trades -52% (1340→638) = ML s'appuyait sur leak comme proxy timing RTH/hors-RTH, pas comme prédiction directe. MaxDD -51% (1424→693t) = trades hors-RTH étaient ceux qui creusaient le DD.
- **SHAP v5b top 10 PROPRE** : dist_ovn_high_pct tombé #1→#21 (0.254→0.015), dist_ib_high_pct hors top 30, above_open_830/930 hors top 30.
- **Top features v5b légitimes** : poc_migration_dir (#1), dist_prev_vpoc_pct (#2), dist_color_dn/up_nearest_pct (#3-4), open_zone (#5), ctx_poc_migration_10, ib_range_atr, atr_14m_pct = features trader que Jackson utilise live (Game Changers, color zones, VPOC).
**Lecon** : (1) Test B ml-trainer (audit code source) = méthode la plus efficace pour détecter leak SHAP-based. (2) Lopez Test D (drop & retrain) confirmé : si feature leaky enlevée, PF reste similaire car ML utilise la feature comme PROXY, pas comme edge primaire. (3) Plafond empirique vrai edge ES BUY 1m H=60 = PF 1.09 (Sharpe 0.70, EV +0.6t). Cohérent avec Plan agent prédiction "PF 1.1-1.3 max".
**Trigger prevention** : pour toute feature broadcast par session aggregée (groupby + agg max/min), ajouter mask NaN obligatoire pendant la session active. Audit systématique avant chaque dataset rebuild.
**Reviewed** : self (empirique) + Phase 2 SHAP re-run sur v5b confirme

### 2026-04-27 20:30 — [VALIDATION_MISS + LEAK STRUCTUREL] — Feature `dist_ovn_high_pct` leaky (broadcast OVN max sur bars OVN actives)

**Contexte** : Phase 2 SHAP analysis sur ML v5 ES BUY (PF 1.11 post-fix anti-triche). SHAP révèle `dist_ovn_high_pct` domine 4× la feature #2 → ml-trainer flag suspicion leak (Test B AFML ch.8).
**Ce qui a mal tourne** : Audit `phase_b_plus_engine.py` ligne 540-547 → bug structurel `add_ovn_features` :
```python
ovn_agg = ovn_only.groupby("ovn_session_date").agg(ovn_high=("high", "max"))
df = df.merge(ovn_agg, ...)  # broadcast sur CHAQUE bar du jour, INCLUS pendant OVN active
```
Pour bar à 20:00 ET (en pleine session OVN), `ovn_high` contient le MAX de TOUTE la session OVN — incluant les bars 21:00 → 09:30 lendemain matin = **lookahead massif**.
Confirmation empirique : bar 04:00 ET 2025-08-19, running_max(high) jusqu'à cette bar = 6460.25, mais `ovn_high` broadcast = 6477.50 → 17.25 points DANS LE FUTUR.
Impact : ~70% du dataset (bars OVN) contient cette feature leaky. ML l'a exploitée à 4× le poids des autres features. PF 1.11 en partie artificiel.
**Cause racine** : (a) `groupby + max` agrégation futur-incluse sans considérer le timing intra-session, (b) absence de validation lookahead sur features broadcast OVN, (c) feature ajoutée Phase B+ sans audit empirique vs running max.
**Lecon** : **Toute feature aggrégée par session (high/low/range/open/close) DOIT être figée au CLOSE de cette session avant d'être broadcastée**. Pour OVN, la valeur ne doit apparaître qu'à partir de 09:30 ET (RTH open). Pour cash high/low intraday, valeur figée seulement à la fin de la période d'agrégation.
**Trigger prevention** : (1) avant chaque feature `dist_X` où X est aggrégé, vérifier que X est computed BEFORE la bar courante, pas avec son futur. (2) Test empirique systématique : pour bar i, dist_X[i] doit utiliser X computed sur bars [start, i] uniquement, pas [start, end_session]. (3) Si feature broadcast par session, ajouter `mask = (mins_et_loc >= session_close_min)` avant merge.
**Reviewed** : ml-trainer (Test B SHAP domination 4×) + self (lecture code phase_b_plus_engine.py + confirmation empirique 1 bar)

### 2026-04-27 18:30 — [VALIDATION_MISS + OVER_ENGINEERING] — Cascade 3 bugs Phase ML pipeline (anti-triche train_lightgbm)

**Contexte** : Smoke test ML --no-tune --skip-mda v4 (351K bars ES). Apres 13 bugs deja fixes dans la matinee (oracle, lookahead swings/sweeps, etc.), ml-trainer a valide GO Lopez (PF 1.53-2.16, PSR/DSR 1.0). Jackson exige protocole anti-triche : code-reviewer audit AVANT Optuna 50 trials.
**Ce qui a mal tourne** : 3 bugs cascade detectes apres ml-trainer GO :
  (1) **VALIDATION_MISS** : code-reviewer detecte 2 bugs critiques DOUBLE DIPPING (`optimize_threshold(y_te,...)` ligne 729 + Optuna objective sur folds[0] test) + 2 importants (`fit_params=` deprecie sklearn 1.7+, `cv=5` default StratifiedKFold non chronologique). ml-trainer GO etait artificiel (+0.5-1.0 PF estimes par leak).
  (2) **OVER_ENGINEERING** : fix v1 = `optimize_threshold(y_tr, p_train_OOS, ...)` via cross-fit KFold-3. Resultat : 0 trades sur 86 folds (mismatch calibration OOS-train vs in-fit-test : KFold-3 voit 2/3 data, final_model voit 100%). Le fix anti-cheat lui-meme casse tout.
  (3) **VALIDATION_MISS v2** : fix v1bis = `threshold=0.5` fixe. Resultat : 1 fold sur 43 fait des trades (fold 39 seul, 25 BUY + 35 SELL). PF=3.42 = mirage statistique. Cause : `is_unbalance=True` decale probas LightGBM hors de 0.5.
**Cause racine** : (a) protocole anti-triche **ASYMETRIQUE** — code-reviewer dispatche APRES ml-trainer au lieu d'AVANT. ml-trainer GO sur metriques double-dippees etait inevitable. (b) chaque fix applique sans smoke-test minimal pre-validation : "fix → run 25min → constate echec → re-fix → re-run 25min". 3 cycles de 25 min perdus.
**Lecon** : (1) **Protocole anti-triche : code-reviewer AVANT ml-trainer**, jamais l'inverse. ml-trainer ne peut pas detecter double-dipping methodologique, code-reviewer si. (2) **Avant fix dataset/pipeline ML qui modifie threshold/calibration : test rapide local sur 1 fold (~2 min) avant relancer pipeline complet (~25 min)**. (3) Ne jamais utiliser threshold fixe avec `is_unbalance=True` — probas decalees hors 0.5. Threshold = mean(y_train) ou calibration Platt obligatoire.
**Trigger prevention** : si je touche train_lightgbm.py (Optuna objective, optimize_threshold, cross_val_predict) → DISPATCH code-reviewer AVANT smoke test. Si je modifie threshold/calibration → test local 1 fold avant pipeline complet. Si je vois 0 trades ou trades concentres sur 1 fold → STOP, c'est un mismatch calibration, pas un edge insuffisant.
**Reviewed** : Jackson + code-reviewer (detecte les 4 bugs anti-triche) + self (cascade fixes constatee empiriquement)

### 2026-04-25 23:30 — [VALIDATION_MISS + COMMENT_FALSE] — Dataset v4 enrichi : 8 bugs detectes par audit 3 agents

**Contexte** : Soiree migration data DMP -> Databento (paye $179/mo). Build dataset v4 enrichi (700k bars × 48 cols, 30 MB) pour ML training Lopez compliant. Audit professionnel demande par Jackson en fin de soiree.
**Ce qui a mal tourne** : 3 agents (code-reviewer, quality-auditor, Plan agent) consensus : NON-PRET pour ML training. 8 bugs critiques :
  (1) `bars_since_roll` accumule cross-mois (sample 9660 -> 34034) = ML apprendrait proxy temps absolu
  (2) CVD reset 22:00 UTC FAUX en hiver (DST) — CME globex = 17:00 CT = 23:00 UTC hiver
  (3) "MQ filled 57%" cite par moi = MENSONGE involontaire, vrai = 12% global (57% sur avril seul, 0% avant dec 2025)
  (4) `dist_mq_put_atr` 98.9% clip a -10 = feature MORTE (clip ±10 ATR detruit info)
  (5) Fuite instrument 13 features (atr_14m + dist_* en ticks bruts, NQ 3.7x ES = ML apprend l'instrument)
  (6) `dist_mq_hvl_0dte` 99.6% null = morte
  (7) Non-idempotence sub-period (ATR/CVD warm-up perdu si re-run partiel)
  (8) Documentation MANQUEE : INCIDENT_LOG, BOT_CHANGELOG, CLAUDE.md non updates malgre 10h travail
**Cause racine** : (a) verif empirique skipped sur stat MQ% citee depuis 1 mois recent (b) clip ATR pas teste sur features macro (call wall a 370 ticks vs ATR 1min ~2 pts), (c) protocole obligatoire CLAUDE.md doc skipped en flux travail intense
**Lecon** : avant chaque stat citee a Jackson : verif empirique sur full periode. Avant clip params : test distribution post-clip. Doc obligatoire = BLOQUANTE meme en flux. Audit agent obligatoire APRES code complet (pas juste avant).
**Trigger prevention** : si je cite un % couverture/qualite -> grep verif empirique global. Si je clip une feature -> check %_clipped_a_borne. A fin chaque session technique majeure -> dispatch audit agent OBLIGATOIRE.
**Reviewed** : Jackson + code-reviewer + quality-auditor + Plan agent

### 2026-04-25 21:00 — [PATTERN_11 + RESOLU] — Migration data : DMP custom Sierra Chart bugs caches confirmes empiriquement -> Databento adopt

**Contexte** : Investigation pourquoi backtest 13/04/2026 montrait des chiffres bizarres. Dataset DMP existant. Hypothese : DMP fiable car tourne depuis mois.
**Ce qui a mal tourne** : DMP 13/04 vol diff 53% vs Databento (source officielle CME). Investigation : DMP a perdu **7 heures de data** (09h-15h UTC = London open + cash open NY) puis triple-compte 16h-20h UTC (180 bars/heure au lieu de 60). DMP plante en silence sans alerter, et triple-compte au redemarrage = data historique POLLUEE sans qu'on le sache.
**Cause racine** : confiance aveugle dans DMP custom (boite noire SC subgraphs) sans verification systematique vs source officielle CME. Pas de monitoring data quality continu.
**Lecon** : (a) JAMAIS confiance aveugle dans data source proprietaire boite noire — toujours cross-check periodique vs source officielle (b) Migration vers Databento = source pro reproductible avec audit logs = base ML serieuse
**Trigger prevention** : avant ML training majeur -> 1 jour de cross-check obligatoire vs source independante. Pour data critique : 2 sources independantes en parallele (DMP + Databento) avec alerte divergence > 1%.
**Reviewed** : Jackson + market-analyst + Plan agent

### 2026-04-25 00:30 — [VALIDATION_MISS + RESOLU] — Kill-switch paper_trader bug dormant (bouton STOP_BOT sans effet)

**Contexte** : Jackson demande ajout bouton "Relancer" au dashboard admin (il voulait pouvoir arreter/relancer le bot a distance en cas de news imminente). Audit preliminaire revele que le bouton "STOP BOT" existant ne fait RIEN depuis le depart : `STOP.flag` n'est lu que par `BOT/bot_main.py` (V1 legacy inactif) — pas par `CORE/mia_paper_trader.py` (bot paper actif).

**Ce qui a mal tourne** : infrastructure admin (endpoints `/api/bot/{stop,start}`, bouton UI dashboard, auto-show/hide selon `stop_flag_active`) deployee depuis session 09/04 SANS aucun test empirique bout-en-bout. Personne n'a jamais verifie qu'appuyer STOP_BOT → arrete effectivement le bot. Bouton REDEMARRER pareil (supprime un flag que personne ne lisait). Pattern `VALIDATION_MISS` identique aux V2-BIS risk.on_bar, reset_session, OCO_ORPHAN_DETECTED (code catalog sans emit).

**Cause racine** : confusion bot V1 (`BOT/bot_main.py` 275) vs bot V2 paper (`CORE/mia_paper_trader.py`). Le contrat "STOP.flag = kill-switch" etait documente pour V1, jamais porte a V2 apres migration paper. Les tests unitaires ne couvraient PAS le parcours complet `/api/bot/stop → flag → bot lit → flatten`.

**Lecon** : apres toute migration/refactor, **grep cross-codebase** pour verifier que les points d'integration (flag files, config, env vars) sont bien lus cote consumer actif en prod. Un fichier cree par producteur sans consumer = bug dormant.

**Fix 24/04 20:00-22:30** :
  1. `CORE/mia_paper_trader.py` : constante `STOP_FLAG_FILE`, `self._stop_flag_active` + `_stop_flag_activated_at`, bloc kill-switch dans `run()` avec retry flatten a chaque tick pause + alerte MAJEUR si pending > 30s (reserve #1 code-reviewer), expose `kill_switch` dans `_write_state()` (reserve #2).
  2. `CORE/log_catalog.py` : +`BOT_KILL_SWITCH_ACTIVATED` (MAJEUR) + `BOT_KILL_SWITCH_RELEASED` (INFO).
  3. `DASHBOARD/static/js/dashboard.js` ligne 5136 : `init()` passe `fetch()` brut → `fetchWithAuth()` pour auto-refresh JWT (fix bug dormant deco toutes 15min : aucun `POST /api/auth/refresh` dans logs historique).
  4. `DASHBOARD/static/sounds/*.wav` + UI sidebar sons (trade_open/tp/sl) avec mute + volume localStorage.

**Review code-reviewer** : GO-AVEC-RESERVES → 2 corrections appliquees (retry flatten + expose kill_switch state).

**Test empirique live VPS 14:25 UTC** :
  - STOP.flag cree → bot detecte en 12s → `[KILL_SWITCH] STOP.flag detecte -> flatten + pause` + `state.json kill_switch.active=true` ✓
  - STOP.flag supprime → bot detecte en 9s → `[KILL_SWITCH] STOP.flag supprime -> reprise trading` + `kill_switch.active=false` ✓

**Trigger prevention** : avant de commit une infra "fire-and-forget" (file flag, cache invalidation, env var), exiger un **test empirique bout-en-bout** documente dans le commit message. Le code-reviewer doit check : "le consumer de ce signal existe-t-il dans le code actif prod ?".

**Reviewed** : Jackson + code-reviewer

---

### 2026-04-24 23:45 — [CONTEXT_MISS + RESOLU] — Plan correction 3 findings audit market-analyst

**Contexte** : Audit impitoyable market-analyst apres 5 fixes en 3h (SLTP P1, SELL+Freshness, Bias gate, SL bornes, atr_14m). Revele 5 findings dont 3 actionnables cette nuit, 2 restants backlog.

**Finding #1 [CONTEXT_MISS] atr_14m non branche paper_trader** :
  Le fix schema 3.7.14 pour `atr_14m` + `VolatilitySpikeGate` est **inutile pour paper_trader actif**. VolatilitySpikeGate uniquement importe dans `BOT/bot_main.py` (legacy/futur). `mia_paper_trader.py` ne l'importe JAMAIS. **Cause** : biais "code correct = utile en prod" — je n'ai pas verifie la chaine d'usage end-to-end.
  **Decision** : Option (B) accepter que le fix sert uniquement pour futur bot live. Pas de branchement en paper_trader (scope creep). Le fix C++ reste valide techniquement pour consumers futurs.
  **Trigger prevention** : cf memory `feedback_pre_deploy_3_questions.md` — avant deploy fix, verifier qui consomme en boucle prod ACTIVE (pas qui importe le code).

**Finding #2 [RESOLU] Redondance bias STEP 6bis quasi-tautologique** :
  `conseil_global` lit `regime.bias` = `compute_bias(bar)` (builders.py:151). STEP 6bis rappelle `compute_bias(bar_row_dict)` sur meme input. Meme fonction, meme bar (dashboard/JSONL source), meme output 99%+ du temps. **Fix** : STEP 6bis gate supprime. Conserve uniquement :
    - Prereq `bar_dmp_missing` (bar DMP presente)
    - Soft-flag V2 log `bias_weak` pour observabilite
  Update FUNNEL_STEPS : `["bar_dmp_missing"]` (retire `bias_opposite_direction`, `bias_unclear`).
  Scoring conseil_global integre toujours bias comme 1/6 facteurs (poids 2/8) — non touche.

**Finding #4 [RESOLU] Kill-switch SELL asymetrique par instrument** :
  Avant : seuil DD hardcode 60t pour ES+NQ combined. NQ max_sl=80t → 1 SL plein peut declencher (trop agressif). ES max_sl=40t → 60t = 1.5 trades (jamais frein).
  Apres : compteurs DD/trades/disabled par SYMBOLE. Seuil = `max_sl_ticks[sym] * 1.5` :
    - NQ : DD > 120t (1.5 trades pleins max_sl 80)
    - ES : DD > 60t (1.5 trades pleins max_sl 40)
  Reset EOD par symbole dans `_rotate_day_if_needed`.

**Finding #3 [BACKLOG] P-hacking Lopez** : 5 fixes en 3h sans backtest empirique. A traiter demain avec simulation sur 1210 barres live 23/04 pour mesurer interaction reelle (SL bornes + T2 seul + freshness + SELL en combinaison).

**Finding #5 [BACKLOG] Payoff gate trivial + scoring ES=NQ** : dette architecturale pre-LightGBM. Post-30j data, scoring par instrument + meta-labeler ML.

**Review agent POST-plan** : GO-AVEC-RESERVES → 1 STEP 0 pre-code (grep compute_bias consumers + FUNNEL_REASONS + reset EOD kill-switch) effectue. 4 verifications OK.

**Tests** : 96/96 pytest passent post-fix.

**Fichiers modifies** : `CORE/mia_paper_trader.py` (FUNNEL_STEPS, STEP 6bis bloc, init + check + close_position SELL, _rotate_day_if_needed).

---

### 2026-04-24 22:00 — [RESOLU] — Fix ATR naming ambigu + VolatilitySpikeGate re-armee (schema 3.7.14)

**Contexte** : Audit ATR suite analyse 23/04. Feature `atr` dans JSONL = en fait `atr_daily` (lu chart DAILY, NQ ~437 ticks). Nom ambigu.
**Impact critique detecte** : `VolatilitySpikeGate` (BOT/bot_main.py:117) calcule `bar_range_ticks / atr_ticks`. Avec atr_daily ~437t, ratio toujours < 0.1 → gate spike JAMAIS declenchee → safety net cassee quand bot ira live.
**Fix** :
  - Nouveau champ C++ `atr_14m` (ATR 14-barres 1-min, True Range SMA, en ticks) calcule depuis chart BARRES (23/25) via `sc.GetChartArray(chart, SC_HIGH/LOW/LAST)`.
  - Schema 3.7.13 → **3.7.14**, 267 → 268 colonnes.
  - 5 fichiers C++ modifies (Reader/Transform/Writer/Config).
  - `CORE/volatility_gate.py` : priorite atr_14m, fallback atr_daily avec log WARN one-shot.
  - `CORE/dmp_validator.py` : EXPECTED_COLS_3714=268 + condition exclude mise a jour.
**Review code-reviewer initial** : NOGO (2 bugs) → fixes :
  1. `sc.GetChartArray(-chart_barres, ...)` avait signe negatif illegal ACSIL → retire.
  2. `dmp_validator.py` condition exclude n'incluait pas 268 → ajoute.
  3. Log WARN fallback atr_daily ajoute (pattern log-debug-protocol).
**Tests** : 96/96 pytest passent.
**Note** : pattern `arr[sz-1]` utilise (risque backfill v4) — blacklist v4 a noter.
**Trigger prevention** : avant tout nouveau champ ACSIL, verifier signature `sc.GetChartArray(ChartNumber, ...)` avec ChartNumber POSITIF. Le `-chart` n'est pas une convention SC valide.

---

### 2026-04-24 21:00 — [SCOPE_CREEP] — Re-activation SELL paper + freshness quick win

**Contexte** : Analyse 23/04 revele 0 trade pris (4026 polls → 3884 conseil_attendre 97%). Cause principale = patch 22/04 SELL DISABLED (builders.py:1329) qui forcait toutes les VENTE/VENTE PRUDENTE en ATTENDRE. Raison historique : audit market-analyst 22/04 PF SELL=0.00 ES (0/6 wins) + Jackson bust Topstep LIVE sur SELL news imprevue. Sur 23/04 NQ baisse 400pt + ES baisse 60pt → 50-70% des opportunites etaient SELL, toutes etouffees.

**Ce qui a change** :
  1. `builders.py:1329-1356` : retrait du forcage VENTE→ATTENDRE. SELL re-active paper uniquement.
  2. `mia_paper_trader.py:75-97 + check_entry` : freshness accepte `("NEW", "PERSISTENT")` au lieu de `"NEW"` seul. Deblocage 46 rejets freshness_not_new/jour.
  3. Kill-switch auto SELL ajoute (pas de boucle manuelle) : si DD_intraday_sell > 60 ticks OU (N>=20 trades ET WR < 25%) → `self._sell_disabled = True` → re-bloque VENTE automatiquement (reject code `sell_auto_disabled`).

**Justification vs pattern 11 V1** :
  - Base statistique 6 trades SELL (audit 22/04) = IC95% Jeffreys WR [0%, 46%] = decision inexploitable
  - Retirer un gate hardcode sur 6 obs = INVERSE du pattern 11 (pattern 11 = ajouter gates cascade apres loss)
  - Safety nets : Paper DTC Sim3 + gates bias/SLTP/payoff aval + kill-switch auto
  - TODO V2CLEAN : flag `ENABLE_SELL_PAPER=True` / `ENABLE_SELL_LIVE=False` dans config centrale

**Review code-reviewer** : GO-AVEC-RESERVES → 3 conditions traitees :
  - #1 entry_px = close courant (banner dashboard) ✅ verifie empiriquement
  - #2 kill-switch auto SELL ajoute ✅
  - #3 cette entree INCIDENT_LOG ✅

**Tests** : 93/93 pytest passent (dont 12 SLTP + 37 bias + 18 cross).

**Monitoring** : chaque fin de journee, review WR_sell_rolling + DD_intraday_sell. Review vendredi 25/04 sur N>=20 trades.

**Trigger prevention** : avant tout patch "DISABLE feature based on N<30 trades", exiger Bayesian IC95% dans la justification. Base stat < 30 = decision inexploitable.

---

### 2026-04-24 18:00 — [RESOLU] — Fix BUG#B+C DMP_ReadNearestExtensionLine max_dist filtre (schema 3.7.10)

**Contexte** : Audit diagnostique Jackson 24/04 afternoon identifie 11 bugs/ameliorations sur les 8 familles d'etudes SC lues par le DMP. Premier fix = BUG#B (NQ COLOR EL median -4531 ticks = -1133 points) + BUG#C (NQ EDGE EL outliers p99=1285t) — meme cause racine.
**Cause racine** : Doc officielle SC (ThreadID=57101) confirme "each recalculation duplicates the lineuntilfuture". Le reader `DMP_ReadNearestExtensionLine` scannait sans filtre de distance max → retournait lignes historiques stale (jamais intersectees apres Full Recalc). Pattern identique au fix delta_divergence 07/04 (meme famille Extension Lines).
**Fix applique 24/04 17:30-18:00** :
  - `DMP_Config.h` : +constante `DMP_MAX_EXT_LINE_DIST_TICKS = 500.0f` (= 125 points ES/NQ)
  - `DMP_Reader.h::DMP_ReadNearestExtensionLine` : filtre `if (d > max_dist_px) continue;` + signature tick_size obligatoire (pas de default pour eviter silent fallback)
  - 6 call sites passent `d.tick_size` explicite (pattern identique aux autres readers)
  - Schema 3.7.9 → 3.7.10 (comportemental, 267 cols inchanges)
**Review code-reviewer** : GO-AVEC-RESERVES → 2 corrections appliquees :
  1. MAX_DIST centralise dans Config.h (pas magic number Reader.h)
  2. Default tick_size retire (anti-pattern silent fallback)
  3+4 : backlog observabilite (counter filter declenche) + surveillance borne scan 50
**Validation empirique** (simulation post-fix sur 1034 barres NQ+ES existantes) :
  - NQ COLOR UP/DN : 100% filtered (-4531t aberrant eliminé) ✅
  - NQ EDGE BUY : p99 1285t → 70t (7.3% outliers filtres) ✅
  - NQ EDGE SELL : p99 1470t → 46t (10.9% outliers filtres) ✅
  - NQ LONG UP/DN : 0% filtered (p99 403-419t legitimes preserves) ✅
  - ES LONG + EDGE : 0% filtered (valeurs deja propres) ✅
**Deploy** : en attente confirmation Jackson (SCP ACS_Source + DUMPER + recompile SC).
**Trigger prevention** : Avant tout reader Extension Lines, toujours ajouter filtre max_dist centralise Config.h. Gotcha SC officiel — pas de bug a chercher dans le reader.

---

### 2026-04-24 10:53 — [CONTEXT_MISS] — Start-ScheduledTask MIA_PaperTrader cree doublon process avec service nssm MIA-Paper

**Contexte** : deploy regime GEX sur paper_trader VPS. Apres kill PID 3260, j'ai fait `Start-ScheduledTask -TaskName MIA_PaperTrader` pensant que la scheduled task etait le mecanisme de persistance.
**Ce qui a mal tourne** : 2 python.exe ont demarre en parallele = race condition sur state.json + 2 connexions DTC Sim3 potentielles. PID 7068 (cmd `-u -X utf8`) lance par le SERVICE nssm `MIA-Paper` (auto-restart apres kill 3260) + PID 11844 lance par ma scheduled task via .bat. Detecte 2 min plus tard au loop suivant.
**Cause racine** : j'ai checke `Get-ScheduledTask` mais pas `Get-Service` avant de restart. Memory `reference_nssm_dashboard.md` mentionnait nssm pour Dashboard — j'aurais du presumer qu'il existait peut-etre aussi un service nssm pour paper_trader.
**Lecon** : avant tout restart d'un process persistant VPS (dashboard, paper_trader, V2CLEAN), v�rifier **LES DEUX** mecanismes : `Get-Service | Where Name -like '*MIA*'` ET `Get-ScheduledTask | Where TaskName -like '*MIA*'`. Si 2 mecanismes existent, ne lancer QU'UN seul.
**Trigger prevention** : avant `Start-ScheduledTask` ou equivalent, run `Get-Service MIA-*` pour detecter les services nssm qui auto-restart deja.
**Reviewed** : self (detecte au loop suivant via ps double). A documenter avec Jackson : probable doublon historique (scheduled task + service) a desactiver un des deux.

---

### 2026-04-24 14:10 — [RESOLU] — Fix dist_mq_hvl_0dte deploye + valide empiriquement

**Contexte** : Bug decouvert matin 24/04 (cf entree precedente) — le HVL 0DTE visible chart Jackson etait AVEUGLE au bot car DMP_Transform n'exposait pas `dist_mq_hvl_0dte` comme feature JSONL (seulement comme fallback pour Call/Put 0DTE superposes). Cas niveaux distincts observe empiriquement 23/04.
**Fix applique 24/04 13:50-14:10** :
  - Schema 3.7.8 → **3.7.9** (266 → **267 colonnes**)
  - +1 feature `dist_mq_hvl_0dte` exposee explicitement
  - +check dans CalcDataQuality (bool_near_level inclut desormais les 3 niveaux 0DTE)
  - +patch dmp_validator.py (EXPECTED_COLS_379=267 + branche detection)
**Audit pre-deploy** : code-reviewer HOLD → 2 correctifs (dmp_validator + CalcDataQuality check) → GO.
**Deploy** : SCP ACS_Source + DUMPER backup (coherent 2 dossiers). Jackson recompile SC 14:05 UTC.
**Validation empirique 14:10 UTC** : barre post-recompile (prix 27064.50, UTC 12:08) :
  - `dist_mq_hvl_0dte = -558t` → niveau absolu 27064.50 - 139.50 = **26925.00**
  - Match EXACT avec HVL 0DTE visuel chart Jackson (label "HVL ODTE" a 26925)
  - Call 0DTE +342t → 27150 ✅, Put 0DTE -1458t → 26700 ✅ (cas distinct confirme)
**Lecon** : le protocol critical-tasks-review fonctionne. Audit agent pre-deploy a rattrape 2 bugs (validator bloquant + check oublie). Temps total bug → fix valide : **4h** (decouverte 10:30 → validation 14:10). Plus court que l'estimation Option 2 (1 jour) grace a scope ultra-minimal (3 lignes C++ + 7 lignes support).
**Trigger prevention** : Toujours verifier quand une feature LIVE dans le code (ici `r.mq_hvl_0dte` lu depuis 31/03) sans etre exposee dans le JSONL. Grep `f.X = ` pour toute variable `r.X` lue → si absent = feature silencieusement abandonnee cote consommateurs.
**Reviewed** : code-reviewer agent (pre-deploy) + Jackson (validation empirique visuelle).

---

### 2026-04-24 13:40 — [CONTEXT_MISS] — 4 affirmations erronees consecutives sur screenshots / niveaux MenthorQ

**Contexte** : Session matinale Q&R edge Jackson. J'ai affirme consecutivement plusieurs choses non verifiees :
1. "Le chart SC affiche en UTC" alors que j'avais 3 hypotheses possibles — verifie apres (valide)
2. "Les niveaux MenthorQ sont stale (Levels Timestamp 22/04)" alors que le screenshot affichait 2026-04-23 et je lisais mal la zone floue
3. "`dist_mq_*` aberrants" alors que distinction `_0dte` (sg5-7) vs generique (sg0-2) n'avait pas ete comprise
4. "BUG LONG UP=DOWN identiques" alors que Jackson avait copy-paste rate
**Ce qui a mal tourne** : 4 CONTEXT_MISS dans la meme session. Chaque fois j'ai affirme un fait (potentiellement un bug) sans verifier empiriquement AVANT. Jackson a du me corriger explicitement chaque fois.
**Cause racine** : Mode "analyse rapide" active sur des screenshots pas clairs → lecture approximative → affirmation premature. Regle `feedback_context_miss.md` existait deja depuis 20/04 mais pas respectee.
**Lecon** : Sur un **screenshot peu clair** (zoom pixelise, superposition legend), **demander zoom ou confirmation** au lieu d'affirmer. Sur une **valeur numerique aberrante** (ex dist_mq_hvl -3070t), **verifier la convention code AVANT** d'affirmer qu'elle est bugguee. Sur une **entree utilisateur incoherente avec empirique**, demander re-dump.
**Trigger prevention** : Si je vais affirmer un fait base sur un screenshot → prendre 5s pour auto-question "ai-je zoom-lu le screenshot proprement ? ai-je une hypothese alternative ?". Si non, demander. **Categorie CONTEXT_MISS atteint largement 3+ aujourd'hui (24/04) : promouvoir memoire dediee.**
**Fix applique** : Memoire `reference_timezone_convention.md` creee avec convention MQ_GAMMA subgraphs + warning mea culpa. MEMORY.md pointeur ajoute.
**Reviewed** : Jackson (corrections explicites). Pattern 11 evite de justesse sur les 4 occurrences (pas de code ecrit/deploye avant correction).

---

### 2026-04-24 10:30 — [VALIDATION_MISS] — Affirmé BUG LONG UP=DOWN sans verifier copy-paste Jackson

**Contexte** : Q&R Phase 0 sur formules Alert Conditions LONG BAR. Jackson m'a dumpe formules, j'ai constate que UP ES/NQ et DOWN ES/NQ avaient la meme Alert Condition (`=AND(O>C[-1], H>L[-1]+TICKSIZE*N)`).
**Ce qui a mal tourne** : J'ai affirme un "BUG 1 MAJEUR" en rouge dans le MANUEL et la reponse Jackson, supposant que les 2 etudes fonctionnaient sur le meme Alert Condition + differenciation via Inputs. En realite, Jackson avait fait un copy-paste raté dans son dump (meme formule UP pour les 4 lignes UP/DOWN ES/NQ).
**Cause racine** : Quand Jackson a redumpe correctement, la vraie formule NQ LONG DOWN BAR etait `=AND(O<C[-1], H[-1]>L+TICKSIZE*40)` — miroir bearish exact. Les fire rates differents (UP 0.5% ES vs DOWN 1.4% ES, UP 9.9% NQ vs DOWN 11.6% NQ) **auraient du me mettre la puce a l'oreille** : si les formules etaient identiques, les fire rates devraient etre egaux. J'ai pris l'incoherence pour un mystere ("inputs direction ?") au lieu de demander confirmation a Jackson.
**Lecon** : **Quand une entree utilisateur est incoherente avec un fait empirique observe**, demander confirmation AVANT d'affirmer un bug. Regle : si fire_rate_UP != fire_rate_DOWN mais formules semblent identiques, hypothese n°1 = "copy-paste rate utilisateur", hypothese n°2 = "differenciation via Inputs". Demander re-dump avant de creer un flag rouge dans la doc.
**Trigger prevention** : Lors de dump de formules / configs par utilisateur, si 2 entites conceptuellement differentes (UP/DOWN, BUY/SELL, LONG/SHORT) ont une config LITERALEMENT identique, c'est un signal d'alerte copy-paste. **Demander explicitement** "tu es sur que X et Y ont exactement la meme formule ?" avant de propager dans la doc.
**Fix applique** : MANUEL_EDGE_JACKSON.md §4.1 corrige avec vraies formules miroir. BUG 1 retire. Note historique ajoutee.
**Reviewed** : self-detection quand Jackson a re-dumpe correctement apres ma reponse. Aucun dommage dans le code (rien de deploye sur ce finding, uniquement doc).

---

### 2026-04-24 02:40 — [CONTEXT_MISS] — Fix C++ NQ_FP EDGE swap inoperant (2 traces manquees)

**Contexte** : Saturation `bar_edge_buy/sell` NQ 74% persiste malgre fix chart 14 matin 23/04 (entree 22:55 ci-dessous). J'ai propose un swap IDs dans `DMP_Reader.h::NQ_FP` : `EDGE_BUY=55↔4` et `EDGE_SELL=56↔2` pour pointer vers natives chart 2 avec `Percentage=1000` (fix Jackson). Deploye sur VPS (SCP) avant recompile DLL.
**Ce qui a mal tourne** : Review agent POST-DEPLOY a identifie 2 problemes bloquants :
  1. `DMP_Transform.h:1257` fait `fp_edge_buy = OR(fp_edge_buy, fp_edge_buy_2)` — l'overlay sature en `EDGE_BUY_2=55` va contaminer le OR → fix neutralise pour `fp_edge_*`.
  2. `bar_edge_buy/sell` NE LIT PAS `NQ_FP` mais `NQ_BARRES` (chart 23 ID 40/16). Mon swap sur `NQ_FP` (chart 2) n'affecte pas les features saturees observees.
Resultat : recompile aurait donne **ZERO changement observable** sur les 4 features cibles. Code mort + piege prochaine session.
**Cause racine** : J'ai propose le fix sans tracer end-to-end la feature `bar_edge_buy` dans le pipeline. Grep `DMP_Studies::NQ_FP::EDGE_BUY` fait, mais grep `bar_edge_buy\s*=` (source de la feature saturee observee) non fait. Confiance excessive sur le grep fp_edge_* qui renvoyait NQ_FP, ignorant que bar_edge_* passe par un autre namespace.
**Lecon** : **Avant tout swap d'ID C++, tracer la feature JSONL observee (celle qui a un comportement anormal) bout-en-bout**. Etapes minimales : (1) grep le nom exact de la feature dans le JSONL (ex: `bar_edge_buy`) dans tout le code C++ pour trouver l'assignation `d.X =`, (2) identifier le namespace/chart utilise, (3) vérifier toute cascade OR/AND dans Transform qui pourrait contaminer, (4) SEULEMENT APRÈS proposer le fix.
**Trigger prevention** : Si je propose un fix C++ sur une feature observee anormale, je dois lister dans ma proposition : (a) nom exact de la feature, (b) file:line de l'assignation directe, (c) file:line de toute cascade Transform qui la derive. Si je ne peux pas le faire de memoire, je grep avant de proposer.
**Fix applique** : Rollback complet du swap (IDs 55/56/4/2 restored a l'original) sur local + VPS. Aucune recompile DLL effectuee. Collecte continue avec saturation NQ jusqu'au vrai fix demain.
**Reviewed** : code-reviewer agent (2 reviews cross-check) + self-detection sur re-verification `bar_edge_buy\s*=`. Vraie source : `NQ_BARRES::EDGE_BUY=40` chart 23, Percentage Threshold inconnu (chart 23 non dumpe, le dump JSON ne contient pas les Input Parameters).

---

### 2026-04-23 22:55 — [VALIDATION_MISS] — Saturation bar_edge_buy/sell NQ 75% non detectee avant audit

**Contexte** : Audit empirique ML-readiness des features footprint a revele que `bar_edge_buy/sell` NQ fire 75% vs 15% ES (cassure symetrie ES/NQ). Features prohibitees training ML depuis avril mais pas questionnees.
**Ce qui a mal tourne** : Config Sierra Chart heritage V1 faisait pointer NQ_FOOTPRINT.EDGE_BUY=55 (chart 2) et NQ_BARRES.EDGE_BUY=32 (chart 23) vers des overlays copiant l'etude source chart 14 ID:1 `EDGE ZONES IMBALANCE BUY 0DIAG` avec `Percentage Threshold=1000` (permissif). Cote ES, configuration pointait vers des etudes avec Threshold=600 (strict). Resultat : saturation NQ 75% fire + BOTH simultane 64% = feature non-discriminante, training ML aveugle.
**Cause racine** : Legacy "A/B tests tick reversal" (Jackson V1 perso) avec plusieurs versions d'etudes EDGE ZONES (rev1 800%, rev2 800%, rev3 800%, 600%DIAG, rev8 0DIAG, 0DIAG) laisse dans le chartbook. Le DMP C++ lit via `study_mapping.json` hardcoded aligned sur IDs non-optimaux. Jamais audite empiriquement avant 23/04.
**Lecon** : **Features binaires avec fire_rate > 60% ET BOTH_simultane > 30% sont cassees par definition**. Planifier audit empirique periodique de la symetrie des features binaires entre symbols (ES vs NQ ES devraient avoir fire_rate comparables pour meme feature). Memory `feedback_es_nq_mirror.md` application empirique stricte.
**Trigger prevention** : Script `CORE/research/audit_footprint_efficiency_*.py` + `CORE/research/quick_check_bar_edge_post_fix.py` integres dans pipeline nightly. Alerte si abs(fire_ES - fire_NQ) > 30% sur une feature binaire.
**Fix applique** : Jackson a modifie chart 14 Rev 8t ID:1 et ID:2 : Percentage Threshold 1000→600 (BUY) / -1000→-600 (SELL). Les overlays chart 2 ID:55/56 et chart 23 ID:32/33 heritent automatiquement via `Study to Overlay = #14.ID1/ID2` + `Data Copy Mode = Use Latest Value from Chart`. Validation empirique sur 9 barres post-fix NQ : BOTH tombe de 52% → 22%, XOR de 15% → 44%. Sur 4 dernieres barres consecutives : 0 BOTH, 2 XOR, 2 NEITHER — convergence complete vers comportement ES.
**Reviewed** : Jackson (decouverte + fix SC) + empirique (46 barres NQ 23/04 analysees). Commit associé non necessaire (config SC uniquement, aucun code touche).

### 2026-04-22 21:15 — [CONTEXT_MISS] — Propose RTH-only a Jackson malgre decision 21/04 = 24h

**Contexte** : Jackson demande "rassure-moi le bot trade toutes les sessions". Je propose 3 options dont Option A = "ajouter gate US RTH". Jackson me reprend "IL DOIS TRADER TOUT LES SESSION".
**Ce qui a mal tourne** : J'ai cite memory `project_v2clean_multi_session` version 19/04 ("US RTH only pour demarrage") sans voir que le meme fichier ETAIT deja update 21/04 avec "Jackson tranche = 24h, NE PAS re-suggerer RTH-only sans signal empirique contrariant". Le fichier avait un tableau historique explicite + une section "Anti-pattern a eviter : NE PAS re-suggerer RTH-only".
**Cause racine** : j'ai read les 2 premieres lignes de memory (description type 2-3 phrases) puis ai synthetise sans lire la section "Anti-pattern" en fin. Memory auto-chargee dans MEMORY.md indexe la description, pas le corps detaille.
**Lecon** : **Quand memory cite une DECISION Jackson (avec date + "tranche" / "confirme"), lire le fichier ENTIER avant de proposer action contradictoire.** Les sections "Anti-pattern a eviter" et "Historique decisions" existent precisement pour ca.
**Trigger prevention** : avant de proposer une reco technique sur V2CLEAN/paper_trader/V2-bis, grep memory pour "NE PAS" + "tranche" + "Jackson confirme" sur le sujet.
**Reviewed** : Jackson (correction directe "IL DOIS TRADER TOUT LES SESSION ON ES PAPER"). Fix applique : memory updated 22/04 re-confirmation paper=24h (argument : collecte donnees). Pas de code change necessaire (bot deja sans filtre session).

### 2026-04-22 XX:XX — [VALIDATION_MISS] — Migration order_manager.py missed OCO_ORPHAN_DETECTED emit

**Contexte** : migration BOT/order_manager.py vers systeme logs V2 (5 emits ajoutes). Review code-reviewer post-commit a detecte gap critique.
**Ce qui a mal tourne** : le log `OCO_ORPHAN_DETECTED` n'etait PAS emis. Pourtant ce scenario est EXACTEMENT le bug DNA V1 (02/04) qui a motive tout l'OCO manuel. Sans ce log, un orphan en prod serait invisible — position ghost avec SL actif = risque perte non-trackee.
**Cause racine** : j'ai migre les emits "happy path" (submit/fill/cancel) mais pas les "failure modes" (orphan = cancel echoue). Pattern inverse du VALIDATION_MISS 22/04 precedent (`risk.on_bar` methode definie mais pas cablee dans dispatcher) — cette fois code defini dans catalog mais pas emis dans code reel.
**Lecon** : **Apres migration logging, verifier que TOUS les codes catalog pertinents au fichier sont effectivement emis**. Grep cross-reference : `codes definis pour categorie X` vs `codes emis dans fichiers de categorie X`.
**Trigger prevention** : script check `catalog_coverage.py` qui grep LOG_CODES["X_CATEGORY_*"] vs "emit(\"X_" dans codebase, flag missing.
**Reviewed** : code-reviewer BOT/order_manager (22/04) — 3 actions correctives identifiees. Fix applique : emit ajoute dans `_verify_cancel` (dtc_connector.py L566). Note : detection orphan REEL (via Open Orders Request Type 300) reportee P3 — actuellement emit ALERTE indicatif.

### 2026-04-22 XX:XX — [COMMENT_FALSE] — V2_StatePersistence header cite code Python inexistant

**Contexte** : review STEP 4 Tier 2 V2_StatePersistence.h par agent code-reviewer. Le header L6-7 disait "Port Python : risk_manager.py:545-564 (_write_snapshot_atomic, 20 LOC) + logique restore + backup".
**Ce qui a mal tourne** : l'agent a grep `BOT/risk_manager.py` pour verifier → **0 match pour `_write_snapshot_atomic`**. La reference etait inventee ou periumee. C'est exactement le pattern COMMENT_FALSE du 20/04 (chiffres LOC non-verifies empiriquement, section 4.6 cite ligne qui n'existe pas dans file Python).
**Cause racine** : au moment ou j'ai ecrit le stub V2_StatePersistence.h (session precedente), j'ai probablement copie une reference d'un autre stub ou l'ai inventee sans grep. **Pattern 2eme occurrence memoire COMMENT_FALSE depuis 20/04**.
**Lecon** : **AUCUNE reference file:line citee dans un header ou doc DOIT passer sans grep de verification empirique.** Meme pour les references "port de Python".
**Trigger prevention** : quand header C++ mentionne "port Python <file>:<lines>" → grep exact `grep -n "symbol" <file>` AVANT commit. Si 0 match = reference fausse, corriger ou retirer.
**Reviewed** : code-reviewer Tier 2 V2_StatePersistence (22/04) detecte. Correction appliquee : header reformule "ref exacte a confirmer P1".

### 2026-04-22 XX:XX — [VALIDATION_MISS] — `risk.on_bar()` defini mais jamais appele dispatcher

**Contexte** : session V2-BIS 22/04 review 4 modules Tier 1 (V2_Main, V2_OrderExec, V2_RiskManager, V2_HealthCheck, V2_SessionGuard). 8 agents reviews individuels ont approuve chaque module.
**Ce qui a mal tourne** : V2_RiskManager.h ligne 64-72 definit `on_bar(double mtm_pnl_usd)` avec commentaire "CRITIQUE : update peak + check_intraday_dd (sinon INTRADAY_DD trop tard)". MAIS `V2_Main.cpp on_bar_close_dispatcher` ne l'appelait JAMAIS. Methode = **dead code de bonne intention**. Classic : methode definie + test reference (peak_drop_intraday_dd) + impl P1 existera, mais cablage dispatcher manque → INTRADAY_DD ne peut PAS trigger pendant trade ouvert.
**Cause racine** : les 8 agents reviews individuels valident CHAQUE module en silo, sans tracer le flow cross-module. La review SYNTHESE GLOBALE (validateur tiers, 9eme agent) a detecte via grep multi-fichiers "qui appelle risk.on_bar ?" → vide.
**Lecon** : **Apres batch de reviews individuels modules, OBLIGATION dispatcher 1 agent SYNTHESE** qui valide :
  1. Chaque methode publique definie est appelee quelque part
  2. Chaque interface ajoutee est implementee ET injectee
  3. Chaque test cible a son cablage dispatcher
**Trigger prevention** : module-review-protocol.md STEP 5 Tier 1 → ajouter STEP 5b "synthesis review global" apres tous modules batches. Validator agent au lieu de 2 cross-checks individuels.
**Reviewed** : code-reviewer synthesis (22/04) detecte C1+C2, fix applique immediatement V2_Main.cpp.

### 2026-04-22 XX:XX — [CONTEXT_MISS] — Proposition doublon EventType::ORDER_ERROR

**Contexte** : application reco Plan V2_HealthCheck STEP 5 Q4 failure modes. Ajout 4 nouveaux EventType dans V2_Types.h enum (V2CLEAN_HEARTBEAT_MISSING, V2CLEAN_CLOCK_SKEW, HEARTBEAT_IO_ERROR, ORDER_ERROR).
**Ce qui a mal tourne** : `ORDER_ERROR` existait deja ligne 182 de V2_Types.h. J'ai ajoute un doublon ligne 193. Grep immediat apres ajout a detecte. Suppression dans la foulee.
**Cause racine** : j'ai lu la fin de l'enum (L167-170) pour positionner mes ajouts, mais pas grep exhaustivement avant. Le trigger prevention ajoute le 22/04 XX:XX (incident precedent KILL_SWITCH_TRIGGERED) etait precisement cette regle — mais applique au moment ADD, pas a l'ADD suivant quelques minutes plus tard.
**Lecon** : **Quand bundle plusieurs ajouts a un enum dans une meme edition, grep CHAQUE nouveau nom individuellement**, pas seulement le premier.
**Trigger prevention** : batch add enum = boucle `for each new_val: grep -n "new_val\b" file`.
**Reviewed** : self (detecte par grep immediat post-edit).

### 2026-04-22 XX:XX — [CONTEXT_MISS] — Proposition doublon EventType::KILL_SWITCH_TRIGGERED

**Contexte** : review V2_Main.cpp STEP 1 walk-through Gap #5 (spam journal kill-switch). Je propose d'ajouter `EventType::KILL_SWITCH_TRIGGERED` comme nouvelle entree enum.
**Ce qui a mal tourne** : `EventType::KILL_SWITCH_TRIGGER` (au singulier, sans D final) existe deja `V2_Types.h:154`. Mon design aurait cree doublon evitable. Code-reviewer a detecte l'angle mort lors STEP 4.
**Cause racine** : j'ai suivi STEP 1 (walk-through) et STEP 2 (grep design doc) MAIS pas STEP complementaire critique : grep EXHAUSTIF de l'enum EventType pour savoir ce qui existe deja. Mon grep STEP 2 a cible "V2_Main / dispatcher / chain.of.gates" sans verifier `V2_Types.h`.
**Lecon** : **Avant proposer AJOUT a un enum/struct C++, grep le type dans V2_Types.h (ou equivalent header types) pour lister les entrees existantes**. Specialement quand le design parle de "journal event X" ou "new enum value".
**Trigger prevention** : quand design proposition contient "ajouter EventType::X" ou "ajouter enum value", faire grep `grep -n "X\|equivalent\|similar" V2_Types.h` AVANT de valider le design.
**Reviewed** : code-reviewer (agent market-analyst agent_a2a08927c03d2bfd6 section "Angle mort detecte").

### 2026-04-21 16:XX — [LAZY_DELEGATION] — V2_JSONLBridge review sans STEP 1-3 manuel

**Contexte** : walkthrough stubs V2-bis module par module. Module 2/13 V2_JSONLBridge.h.
**Ce qui a mal tourne** : j'ai directement dispatche code-reviewer sans walk-through scenarios reels ni grep design doc. Code-reviewer a rendu 10 recommandations dont R2 (ajouter `is_v2clean_zombie()` a ISignalSource) qui viole SRP. Si applique directement, j'aurais pollue l'interface.
**Cause racine** : paresse methodologique - deleguer tout aux agents au lieu de faire STEP 1-3 manuel d'abord.
**Lecon** : **Avant dispatch agent sur module, appliquer STEP 1-3 du `module-review-protocol.md`** (walk-through scenarios + grep doc + 2 tests stubs). ~60% des issues sont detectables manuellement.
**Trigger prevention** : avant `Agent` tool sur module V2-bis, grep `.claude/rules/module-review-protocol.md` + appliquer STEPS.
**Reviewed** : Plan agent (cross-check) a detecte R2 faux positif + R11 trou additionnel.

### 2026-04-21 14:XX — [CONTEXT_MISS] — Ajout feature absolue violant data-quality.md

**Contexte** : Jackson demande derivation `mq_gamma_condition` dans `menthorq_backfill_injector.py`.
**Ce qui a mal tourne** : ajout initial de 6 features dont `mq_net_gex` (113M ES) + `mq_total_gex` (485M ES). Valeurs absolues non-normalisees, incomparables ES/NQ (ratio 25x+). Violation directe `data-quality.md` regle souveraine "NE JAMAIS stocker d'absolus de prix/volume".
**Cause racine** : n'ai pas consulte `.claude/rules/data-quality.md` AVANT d'ecrire code. Memoire `feedback_data_quality_first.md` est auto-chargee mais j'ai ajoute quand meme feature absolue.
**Lecon** : **Avant d'ajouter feature numerique ML, verifier mentalement : ES vs NQ comparable ? Si non (dollars/volumes absolus), normaliser par ratio ou drop**.
**Trigger prevention** : si je m'apprete a ecrire `result["mq_<quelque_chose>"] = _parse_suffix_number(...)` ou valeur $M/$B → **stop**, normaliser d'abord.
**Reviewed** : code-reviewer (attrape via protocol critical-tasks-review). Correction : DROP `mq_net_gex`/`mq_total_gex`, ADD `mq_net_gex_norm = net/total` (ratio). Temps perdu : 10 min.

### 2026-04-20 21:XX — [AGENT_MISUSE] — 3 agents dispatch mal adaptes pour JSONL multi-barres

**Contexte** : Jackson demande audit exhaustif 266 features multi-barres. J'ai dispatche quality-auditor + schema-auditor + code-reviewer + market-analyst.
**Ce qui a mal tourne** : quality-auditor est specialise **parquet V2** (5 criteres fuite/vol/outlier/constant), pas JSONL temporel multi-barres. code-reviewer generique pas arme pour VIX/open_type specifiques.
**Cause racine** : dispatche sans verifier `.claude/agents/*.md` definitions vs exigences de la tache. Plan agent l'a detecte au round suivant.
**Lecon** : **VERIFIER la definition de chaque agent AVANT dispatch** quand la tache differe du use-case standard.
**Trigger prevention** : si tache = nouvelle modalite (JSONL vs parquet, multi-barres vs snapshot), grep `.claude/agents/*.md` avant Agent dispatch.
**Reviewed** : Plan agent

### 2026-04-20 20:XX — [SCOPE_CREEP] — Proposition 2 agents a creer inutile

**Contexte** : Plan agent suggere `feature-distribution-auditor` + `audit-coordinator` comme solution ideale. J'ai presente a Jackson comme necessaire.
**Ce qui a mal tourne** : creer 2 agents = 2 fichiers .md + 2 prompts + maintenance pour UN audit ponctuel.
**Cause racine** : acceptation aveugle recommandation Plan agent sans pragmatic filter. Jackson a dit "on peut utiliser existants".
**Lecon** : **Avant de creer un nouvel agent, epuiser les possibilites de re-brief des agents existants**.
**Trigger prevention** : si ma solution necessite creer infra (agent/rule/script), d'abord demander "peut-on y arriver avec l'existant + prompt plus precis ?".
**Reviewed** : self (Jackson pragmatique l'a implicitement valide)

### 2026-04-20 19:XX — [VALIDATION_MISS] — Fix C++ deploy sans verifier ib_recalc.py Python

**Contexte** : Fix C++ DMP_Transform.h:848 pour bug IB position_pct. Deploy propose apres 1 round code-reviewer GO.
**Ce qui a mal tourne** : code-reviewer 2e round (audit complet) a trouve que `CORE/ib_recalc.py:195-201` **recalcule** `ib_position_pct` sans guard `ib_complete`. Le fix C++ serait annule cote pipeline ML. 17083/17083 barres polluees confirmees empiriquement.
**Cause racine** : n'ai pas mappe toutes les surfaces d'ecriture de la feature avant de fixer. C++ seul = insuffisant.
**Lecon** : **Avant tout fix feature, grep TOUT le pipeline** (C++ ET Python) pour tous les points d'ecriture/recalcul de cette feature.
**Trigger prevention** : fix C++ sur feature F → grep `F` sur CORE/*.py + BOT/*.py + V2CLEAN/*.py avant deploy.
**Reviewed** : code-reviewer (RESERVE #1 CRITIQUE)

### 2026-04-20 18:XX — [VALIDATION_MISS] — V2-bis design v1.4 : 10 reserves declare appliquees, 5 residus

**Contexte** : 4e review Plan agent sur design V2-bis. J'annonce 10 corrections appliquees → bump v1.4.
**Ce qui a mal tourne** : Plan agent re-audit v1.4 detecte 5 residus (78 tests vs 79 dans 4 endroits, "717 LOC" vs 716, refs cross brisees, timeline 7.5-8.5 vs 6 sem, v1.3 vs v1.4 tags).
**Cause racine** : correction faite dans une section mais pas propagee aux autres sections qui citent la meme valeur. Discipline editoriale de propagation faiblarde.
**Lecon** : **Apres chaque correction numerique/textuelle, grep le chiffre/texte AVANT et APRES correction dans tout le fichier**.
**Trigger prevention** : si Edit change "X" en "Y" → grep "X" dans meme fichier → fix toutes autres occurrences.
**Reviewed** : Plan agent

### 2026-04-20 16:XX — [CONTEXT_MISS] — Audit single_print_mid flagge comme bug alors que deja PROHIBITED

**Contexte** : Audit multi-barres 266 features. market-analyst flagge `single_print_mid` + `profile_hvn_dominant` = prix absolus → violation data-quality.md.
**Ce qui a mal tourne** : ces 2 features sont **deja dans `dataset_builder.py:185 PROHIBITED_FEATURES`** depuis longtemps. Drop auto au niveau parquet. Pas un "bug actif".
**Cause racine** : brief agent sans lui donner le contenu PROHIBITED_FEATURES. Agent a flagge ce qui etait deja gere.
**Lecon** : **Avant audit features, briefer l'agent avec la liste des features deja droppees/exemptees** pour eviter faux positifs.
**Trigger prevention** : audit qualite features → include `PROHIBITED_FEATURES` + `EXEMPT_FEATURES` dans brief.
**Reviewed** : self (investigation empirique post-audit)

### 2026-04-20 16:XX — [CONTEXT_MISS] — Collinearite 4 features signalee, deja documentee

**Contexte** : Audit detecte `ask_bid_imbalance = delta_pct = buy_sell_ratio = ask_pct` collineaires corr=1.0.
**Ce qui a mal tourne** : `dataset_builder.py:412` documente deja ces 3 redondances avec commentaire explicite `# ask_pct == buy_sell_ratio, delta_pct == ask_bid_imbalance` et drop auto.
**Cause racine** : pas lu dataset_builder.py avant de dispatcher audit. Aurait evite faux positif.
**Lecon** : **Quand audit ML features, lire d'abord dataset_builder.py PROHIBITED + commentaires explicatifs**.
**Trigger prevention** : tache = "audit features X" → Read `CORE/dataset_builder.py` PROHIBITED_FEATURES section AVANT tout.
**Reviewed** : self

### 2026-04-20 15:XX — [CONTEXT_MISS] — Convention DMP dist mal codee dans Phase 0

**Contexte** : Script audit_phase0.py, check derivation `bool_above_X == (dist_X > 0)`.
**Ce qui a mal tourne** : 7 faux positifs sur ES + 7 sur NQ (99-100% barres). La convention reelle = `bool_above_X == (dist_X < 0)` (DMP_Transform.h:531 `PosInRange`).
**Cause racine** : ecrit le check sans lire la formule C++ source. Intuition naturelle "dist > 0 = above" inversee dans DMP.
**Lecon** : **Pour coder un check sur feature DMP, TOUJOURS lire la formule C++ source avant d'affirmer la semantique**.
**Trigger prevention** : avant ecrire `check(feature_X)` → Read `CPP/.../DMP_Transform.h` section qui calcule X.
**Reviewed** : self (empirique : `price=26684, dist_cur_vpoc=-3, bool_above=1` a revele la convention)

### 2026-04-20 13:XX — [COMMENT_FALSE] — "60 LOC critiques lignes 545-564" reel = 20 LOC

**Contexte** : Design V2-bis P0 section V2_StatePersistence, justifie port Python.
**Ce qui a mal tourne** : j'ai ecrit "20 LOC critiques" puis Plan agent a corrige, j'ai revise en "60 LOC" ... faux aussi. Realite = `_write_snapshot_atomic` est 20 lignes exactes (545-564).
**Cause racine** : repete chiffre de Plan agent review sans verifier empiriquement. Plan agent lui-meme avait donne chiffre faux.
**Lecon** : **Tout chiffre cite (LOC, %, count) DOIT etre verifie empiriquement par Read/Grep avant ecriture dans doc**.
**Trigger prevention** : si je m'apprete a ecrire "N LOC", "X%", "K tests" → verifier avec Bash/Read avant.
**Reviewed** : code-reviewer

---

## Statistiques par categorie (auto-update si manuel)

| Categorie | Occurrences | Promoted en memoire ? |
|---|---|---|
| CONTEXT_MISS | **6** | **OUI** `feedback_context_miss.md` (deja promu, renforce 22/04 avec trigger "grep enum existant" + "batch add = grep chaque nouveau nom") |
| VALIDATION_MISS | **9** | **OUI** (9 occurrences post +3 entries 31/32/33 le 03/06) — promu `feedback_validation_miss_patterns.md` : **27/04 leak structurel session features + 03/06 trigger renforce : "tout changement broker symbol + tout guard CRITIQUE empirique audit > 100/24h"** |
| AGENT_MISUSE | 1 | **OUI preventivement** `feedback_agent_brief_verify.md` |
| SCOPE_CREEP | 1 | Pas encore |
| COMMENT_FALSE | **2** | Pas encore (seuil 3+) — trigger nouveau 22/04 : "grep empirique toute reference file:line header" |
| **LAZY_DELEGATION** | **1** | **OUI preventivement** `.claude/rules/module-review-protocol.md` (6 STEPS) |
| **PATTERN_11** | **3** | **OUI** (3 occurrences cycle BN V4->V5 le 03/06) — promu `feedback_pattern11_repetition_avoided.md` : **escalation : avant toute modif cascade BN V*, backtest 30j AVANT deploy + ml-trainer 5 controles si rate-of-fire chute > 30%** |
| **OVER_ENGINEERING** | **1** | Pas encore (seuil 3+) — trigger 27/04 : "test local 1 fold avant pipeline complet" si modif threshold/calibration ML |

**Escalation auto** : quand categorie = 3+ → creer memoire dediee auto-chargee.

### 2026-05-10 22:30 — [VALIDATION_MISS] Régression ES game_changers open_type/day_type const=1 depuis Chantier 1
**Contexte** : Audit Chantier 5bis2 (revival features MGC) a découvert que `apply_game_changers`
dans `build_dataset_v4_phase_b.py` utilisait `grp.iloc[0]` (1ère barre du jour = 18:00 ET J-1
= avant IB) où `ib_high/low` sont masked NaN (anti-leak fix).

**Ce qui a mal tourné** : `classify_open_type` retournait UNKNOWN (0) systématiquement
car ses inputs étaient NaN. Idem `classify_day_type` retournait NORM_VAR (2).

**Conséquence** :
- Sur MGC (testé) : `open_type/day_type/open_direction/open_bias_conf` const sur 30k bars
- **Sur ES (régression silencieuse)** : `open_type` const=1 dans `v4_enriched/symbol=ES.c.0/`
  depuis Chantier 1 (probablement 12+ mois). Personne n'a remarqué car ces 4 features sont
  dans `ML_EXCLUDE_FEATURES` (drift instrument), donc invisibles au quality-auditor ML.
- 4 features mortes silencieuses dans tous les datasets ES v4_enriched.
- NB : `ES_dataset_v5e_clean_long.parquet` (pipeline research différente) avait `open_type`
  nuniq=10 — ce qui confirme que le bug est isolé au refactor v4_phase_b.

**Cause racine** : `apply_game_changers` ligne 192-194 :
```python
for date, grp in df.groupby("date_et", sort=False):
    first = grp.iloc[0]  # Bug : 1ere barre du jour = avant IB = NaN
```

**Leçon** : Toute feature classée par `classify_open_type` doit lire les inputs APRÈS
fin IB window (mins_et >= us_start + 60). Pour ES/NQ ib_close=10:30, MGC=09:30.

**Trigger prevention** : avant ML training, exécuter cardinalite check sur features
ML_EXCLUDE_FEATURES aussi (pas seulement features actives). Une feature const=1
silencieuse cache un bug de calcul, même si elle n'entre pas au modèle.

**Fix appliqué** : commit `05ce5b6` (Chantier 5bis2) — `apply_game_changers` utilise
maintenant `post_ib = grp[grp["mins_et"] >= ib_close_min]; first = post_ib.iloc[0]`.
Le fix sauve aussi ES rétroactivement (rebuild ES v4_enriched requis).

**Action** :
1. Rebuild `v4_enriched/symbol=ES.c.0/` pour tous mois 2025-2026 → +4 features revived
2. Re-construire `ES_dataset_v5e_clean.parquet` si utilisé
3. Si Bot 1/2/3 utilisent ces 4 features → revalider backtests

**Reviewed** : code-reviewer ULTRATHINK 10/05/2026 22:00 (découverte croisée audit MGC)

