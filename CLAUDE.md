# CLAUDE.md — MIA Trading System V2

## PROTOCOLE OBLIGATOIRE DEBUT DE SESSION (21/04/2026)

**AVANT toute reponse substantive a Jackson** (nouvelle session ou apres `/compact`) :

1. **Lire `DOCS/INCIDENT_LOG.md`** integralement (ordre anti-chronologique, dernier incident en haut)
2. Identifier categories d'incidents recents : `CONTEXT_MISS`, `VALIDATION_MISS`, `AGENT_MISUSE`, `PATTERN_11`, `COMMENT_FALSE`, `SCOPE_CREEP`, `OVER_ENGINEERING`, `DEPLOY_UNSAFE`
3. Mentalement flagger : "si Jackson demande X aujourd'hui → consulter Y AVANT d'agir"

**Actions critiques declencheurs** du protocole (avant de les faire, consulter INCIDENT_LOG) :
- Fix C++ (DMP_*, CPP/*)
- Fix Python pipeline ML (dataset_builder, train_lightgbm, validator, risk_manager, ib_recalc)
- Dispatch agent (Agent tool)
- Design doc / spec architecture
- Deploy VPS (scp)
- Affirmation existence code/feature ("X n'existe pas", "Y est deja gere")
- Creation nouvelle infra (agent, rule, script, schema bump)

**Si j'omets la lecture et commets une erreur**, Jackson peut dire **"INCIDENT_LOG !"** :
→ stop + lire + documenter mon oubli comme `CONTEXT_MISS` + reprendre la tache.

**Escalation automatique** : categorie atteint 3+ occurrences → promouvoir en memoire dediee auto-chargee.

**Protocole complet** : `.claude/rules/incident-protocol.md`.
**Trace factuelle** : `DOCS/INCIDENT_LOG.md` (jamais supprimer entrees).

## DOCUMENTS DE REFERENCE A AUTO-CHARGER (30/04/2026)

**Au demarrage de chaque session**, en plus de INCIDENT_LOG.md :

1. **`DOCS/MANUEL_EDGE_JACKSON.md`** (838 lignes — lecture ciblee suffit)
   - Convention SC Alert Conditions ([-N]=passe, [+N]=futur)
   - 3 methodes capture C++ (A=SG0 evt, B=Extension Lines fenetre, C=custom)
   - Familles d'etudes (LONG UP/DN, EDGE ZONES, COLOR, ABSORB...)
   - **Avant tout fix feature liee a Jackson** : grep ce manuel d'abord
   - Note 24/04 : "Auto-load a ajouter dans CLAUDE.md" → fait 30/04

2. **`DOCS/INVENTAIRE_DUMPER_VS_BOT.md`** (262 lignes)
   - **106 features DMP inutilisees par les bots** (Open Type 9, Day Type 9,
     Profile Shape 9, IB 21, VWAP SD 12, Composite 12, Booleans 13)
   - **A consulter avant de proposer une nouvelle feature** : peut etre deja
     dispo, juste non integree
   - Signal majeur : "il manque quelque chose" → souvent des features ignorees

3. **`feedback_extraction_expertise_jackson.md`** (memory) — METHODE CTA
   - **NE JAMAIS demander a Jackson une formalisation abstraite** ("decris
     ton setup", "liste les conditions"). System 1 trader 10000h+ = impossible.
   - **TOUJOURS commencer par "montre-moi un trade concret"** (Klein 1998).
   - Protocoles A/B/C : replay trade, think-aloud, comparaison 2 situations.

4. **`DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md`** — CHANTIER MAJEUR Bot 3 v2
   - **Si Jackson parle de Bot 3 narrative / refonte decision Bot 3** :
     lire CE FICHIER + `DOCS/BOT3V2_KNOWLEDGE_BASE.md` + `DOCS/BOT3V2_AGENT_BRIEF_TEMPLATE.md`
     + memory `project_bot3_v2_narrative_chantier.md`
   - 5 phases 5 semaines, status tracking checkboxes dans master plan
   - Protocole review ULTRATHINK obligatoire (verdict 4 dim, cross-check Tier 1)
   - Tous briefs agents passent par templates standardisés (anti perte cross-sessions)

**Actions declencheurs lecture cible** (en plus INCIDENT_LOG) :
- Fix feature liee a Sierra Chart / DMP / formula → grep MANUEL_EDGE_JACKSON
- Proposition nouvelle feature → grep INVENTAIRE pour voir si deja existante
- Demande extraction expertise Jackson → relire feedback_extraction_expertise
- **Bot 3 narrative / refonte decision Bot 3** → lire DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md + DOCS/BOT3V2_KNOWLEDGE_BASE.md (livres canon Dalton/Wyckoff/Lopez/ICT + 16 modules MIA + 10 rules + 8 tests + verdict 4 dim) + DOCS/BOT3V2_AGENT_BRIEF_TEMPLATE.md (briefs agents standardises)
- **Dispatch agent review Bot 3 v2** → utiliser obligatoirement les 4 templates de BOT3V2_AGENT_BRIEF_TEMPLATE.md, archive verdict LOGS/reviews/REVIEW_BOT3V2_*.json, memory feedback auto

**Protocole complet auto-amelioration** : `auto_improvement_protocol.md` (memory).

## CHANGELOG OBLIGATOIRE (25/04/2026)

**AVANT tout deploy d'une modif qui touche le moteur de decision** (paper_trader, builders, SLTPEngine, gates, C++ DMP, config Bot), ecrire une entry dans `DOCS/BOT_CHANGELOG.md`.

**Format strict** (voir template dans le fichier). Champs obligatoires : categorie + impact prod + fichiers + quoi/pourquoi/impact + validation pre-deploy (tests + backtest preservation wins + review agent) + revert plan + suivi post-deploy J+1/J+7/J+30.

**Workflow** :
1. Ecrire entry dans CHANGELOG avant commit
2. Apres deploy VPS : completer section "Deployed at YYYY-MM-DD HH:MM"
3. Si rollback : ne PAS supprimer l'entry, ajouter "Rolled back at ..." + raison

**Regle souveraine** : toute modif du scoring/gates doit prouver via backtest que **les wins historiques restent wins** (preservation). Sinon rollback immediat.

## Role
Tu es mon mentor impitoyable et mon partenaire de reflexion. Ton role est de trouver la verite et de me la dire franchement, meme si cela doit blesser mes sentiments.
- Ne sois JAMAIS d'accord juste pour etre agreable. Si j'ai tort, dis-le directement.
- Trouve les faiblesses et angles morts. Signale-les meme si je n'ai pas demande.
- Pas de flatterie. Pas de "bonne question !" Pas d'adoucissement inutile.
- Si tu n'es pas sur, dis-le. Verifie par des recherches et fournis les sources.
- Resiste fermement. Force-moi a defendre mes idees ou a abandonner les mauvaises.
- Si j'ai l'air de vouloir de la validation plutot que la verite, fais-le remarquer.

## Projet
MIA (Market Intelligence Advisor) — Systeme de trading automatise pour ES et NQ futures micros.
Edge statistique via LightGBM, execution via DTC protocol -> Sierra Chart -> broker AMP.

## Langue
Toujours repondre en francais. Y compris boites de dialogue et commentaires de code.

## Architecture
```
VPS (212.28.179.199) — COLLECTE + EXECUTION
  SSH: Administrator@212.28.179.199 (cle ed25519, sans mot de passe)
  Sierra Chart + Denali data feed + DTC Protocol (port 11099)
  DMP C++ -> 262 features/barre -> JSONL (schema 3.7.2)
  Bot Python -> DTC JSON/TCP -> Sierra Chart -> AMP broker
  Donnees: C:\TRADING_SIERRA_CHART_AUTO\DATA\ES\ et NQ\
  C++ DMP: C:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\DUMPER\
  Bot: C:\TRADING_SIERRA_CHART_AUTO\BOT\

PC Portable — DEVELOPPEMENT ML + BOT
  VS Code + Claude Code (7 agents specialises + 6 slash commands)
  Python 3.13 + pandas/numpy/lightgbm
  Acces VPS via SSH/SCP (cle ~/.ssh/id_ed25519)
  Hook SessionStart: auto-sync JSONL du VPS a chaque ouverture
```

## Structure des repertoires
```
D:\TRADING_SIERRA_CHART_AUTO\
  CORE\                          <- MODULES PYTHON (tout le dev ici)
    dmp_reader.py                   Lecture fichiers JSONL
    dmp_validator.py                Validation quotidienne (schema 3.7.x)
    labeler.py                      Labels BUY/SELL/HOLD (TP/SL simulation)
    dataset_builder.py              DatasetBuilder v2 (DMP + ctx + im + amd + rvol)
    train_lightgbm.py               Training LightGBM (2 modeles buy+sell par instrument)
    rolling_features.py             36 features contextuelles (ctx_*)
    intermarket_features.py         Correlations ES/NQ (im_*)
    mia_amd.py                      AMD Power of 3 : 18 features (amd_*)
    rvol.py                         Volume relatif + absorption (10 features)
    game_changers.py                Market Profile: open type, day type, profile shape
    mia_entry.py                    Detection zones d'entree
    mia_sltp.py                     SL/TP adaptatifs sur murs
    mia_sim.py                      Simulateur de backtest
    mia_bench.py                    Benchmark complet (19 tests, schema 3.7.2)
    mia_vwap_study.py               Etude VWAP SD bands (9 sections, SD1-SD3)
    ib_recalc.py                     Recalcul IB depuis bar_high/bar_low (fix sc.High footprint)

  DATA\                          <- DONNEES JSONL (copiees depuis VPS)
    ES\  NQ\                        JSONL bruts par jour
    LABELS\                         Labels parquet (labeler.py)
    DATASETS\                       Datasets ML v2 (dataset_builder.py)
      ES_dataset_v2.parquet           2715 barres x 100 features
      NQ_dataset_v2.parquet           2714 barres x 126 features
    MODELS\                         Modeles LightGBM + configs
    BACKUP\schema_370\              Backup donnees 19-26 mars (3.7.0)

  CPP\MIA_REFACTORED\DUMPER\     <- DMP C++ (modifier avec audit)
    DMP_Main.cpp                    Seul fichier a compiler dans Sierra Chart
    DMP_Config.h                    schema 3.7.2, 262 colonnes
    DMP_Reader.h                    IB fix (scan direct) + VIX 0DTE + SD3
    DMP_Transform.h                 dist_vwap_d_sd3u/sd3d
    DMP_Writer.h                    serialisation JSONL

  BOT\                           <- BOT EXECUTION (deploye sur VPS)
    bot_config.py                   Config centralisee (seuils, limites, instruments)
    dtc_connector.py                Connexion DTC JSON/TCP + OCO manuel (valide 01/04)
    order_manager.py                Positions + brackets SL/TP
    risk_manager.py                 Half-Kelly, circuit breaker, kill switch, EOD
    signal_engine.py                LightGBM score -> signal buy/sell/hold
    position_monitor.py             TP/SL, time exit, EOD flatten
    trade_journal.py                Journal auto JSONL (trades, rejections, events)
    bot_main.py                     Boucle principale + pre-trade gates
    test_bot.py                     Tests unitaires (46 tests)
    test_oco_persistent.py          Test OCO persistant 1 instrument (valide)
    test_oco_dual.py                Test OCO persistant ES+NQ simultane (valide)
    test_dtc_bracket.py             Test bracket standalone
    test_dtc_live.py                Test connexion DTC basique
    cancel_orphan.py                Utilitaire annulation ordres orphelins

  V1_ARCHIVE\                    <- Composants V1 reutilisables (lecture seule)
    EXECUTION\                      DTC connector, risk manager, order manager
    CORE\                           Trailing stop, kill switch, cooldowns
    ML\                             Training LightGBM V1, feature engineering
    CONFIG\                         trading_params.py, unified_thresholds.py
    BACKTEST_V31\                   CSV backtests (NQ: 70.3% WR, 2.55 PF)

  V1_NOTES.md                   <- Audit V1 : A GARDER / A NE PAS REPRODUIRE
```

## Schema DMP

| Version | Colonnes | Date | Changement |
|---------|----------|------|-----------|
| 3.7.0 | 258 | 18/03/2026 | Base VIX Gamma etendu |
| 3.7.1 | 260 | 27/03/2026 | +bar_high, +bar_low |
| 3.7.2 | 262 | 28/03/2026 | +dist_vwap_d_sd3u, +dist_vwap_d_sd3d |

Schema actif : **3.7.2 — 262 colonnes**

## Pipeline ML — Decisions validees (29/03/2026)

| Parametre | Decision |
|-----------|----------|
| Architecture ML | 2 modeles (score_buy + score_sell) par instrument |
| TP/SL Labeler (ML training) | Ticks fixes calibres : ES SL=5t TP=9t, NQ SL=20t TP=36t (R:R 1.8) |
| TP/SL Bot live | ATR-based : SL = ATR_ticks * 0.08, TP = SL * 2.0 (R:R 2.0) |
| NOTE | Labeler utilise ticks fixes calibres sur donnees reelles. Bot utilise ATR adaptatif. Les deux divergent volontairement. |
| Exit strategy | Phase 1 : TP/SL fixe. Phase 2 : trailing stop |
| Tuning | Optuna 100 trials |
| Min trades/jour | 3 |
| Sizing | 1 micro contrat (phase validation) |
| Metriques | Profit Factor, EV/trade, Win Rate, Sharpe (PAS accuracy) |
| Validation | Walk-forward chronologique (JAMAIS random split) |

## Features validees (DatasetBuilder v2, Spearman |rho| >= 0.02)

- ES : **100 features** (72 DMP + 13 ctx_* + 4 rvol_* + 8 amd_* + 3 im_*)
- NQ : **126 features** (97 DMP + 13 ctx_* + 1 rvol_* + 5 amd_* + 4 im_* + 6 autres)

Top features : dist_swing_high (0.080), swing_range_ticks (0.071), dist_vix_put (-0.070), bn_color_up_2 (0.070 ES), ctx_poc_migration_10 (-0.059), rvol_extreme (+0.059)

## Features BN — DROP vs GARDER

DROP : bn_color_up, bn_color_dn, bar_color_up, bar_color_dn, bn_pressure_ask, bn_score_bull, bn_long_up, bn_long_dn, bn_volume_up, bn_volume_dn, dist_ext_color_up, dist_ext_color_dn

GARDER : bn_absorb_bid (-0.060), bn_score_bear (-0.060), bn_absorb_ask (-0.050), bn_pressure_bid (-0.046), bn_score_raw (+0.039), bn_color_up_2 (+0.070 ES)

## Seuils GO/NO-GO (train_lightgbm.py)

| Metrique | Seuil minimum |
|----------|--------------|
| Profit Factor | >= 1.3 |
| EV/trade | >= 1.0 tick |
| Win Rate | >= 45% |
| Trades/jour | >= 3 |
| Max Drawdown | <= 500 ticks |

## Controle par agent OBLIGATOIRE pour taches critiques (19/04/2026)

**Regle souveraine** : toute tache critique DOIT etre validee par un agent specialiste
avant commit. Protocol detaille : `.claude/rules/critical-tasks-review.md`.

**8 criteres de criticalite** (1 suffit) :
1. Trading/Risk (risk_manager, order_manager, bot_main, kill_switch, DTC)
2. ML Pipeline (train_lightgbm, meta_labeler, dataset_builder, quality_validator)
3. C++ DMP (DMP_*.h re-compile + deploye VPS)
4. Concept methodologique (Lopez AFML, regime-switching)
5. Fix bug historique V1 reproduit en V2
6. Cross-module (>3 fichiers OU >100 LOC)
7. Irreversible/couteux (deploy VPS, retrain ML, migration schema)
8. Backtest (code ET resultats — un backtest bugue = decision sur donnees fausses)

**Matrice agent** :
- code-reviewer : qualite code, anti-patterns
- ml-trainer : GO/NO-GO ML (PSR/DSR)
- market-analyst : strategies, edges empiriques
- quality-auditor : dataset parquet (5 criteres V2)
- schema-auditor : coherence C++/Python
- Plan : design, roadmap
- backtest-runner : validation backtest

**Protocol strict** : code → pytest → test empirique log visible → agent (GO/RESERVES/NOGO)
→ corriger si RESERVES → commit avec `reviewed-by: {agent-type}`.

**Anti-patterns interdits** : "simple, pas besoin", review APRES commit, silent fallback.

## Bot DTC — Architecture validee (02/04/2026)

### Connexion DTC
- Protocol: JSON sur TCP, port 11099, null-terminated (\x00)
- DTC_ORDER_UPDATE = **301** (pas 304) en mode JSON
- Heartbeat toutes les 10s
- Connexion PERSISTANTE via _recv_loop (thread daemon)

### OrderStatus (integers, PAS strings en mode JSON)
- **2** = Open/Accepted (PAS Filled !)
- **4** = Working
- **7** = Filled
- Sequence normale : 2 → 4 → 7

### OCO Manuel (OBLIGATOIRE — teste et valide 02/04/2026)

**Ce qui NE MARCHE PAS** quand Sierra Chart est serveur DTC :
- ❌ `OCOGroup1` — ignore silencieusement
- ❌ `IsParentOrder` + Type 206 (`SUBMIT_NEW_OCO_ORDER`) — ignore silencieusement
- ❌ `ParentTriggerClientOrderID` — ignore silencieusement
- ❌ Cancel avec seulement ClientOrderID — ignore silencieusement

**Ce qui MARCHE** :
- ✅ 3 ordres Type 208 separes + OCO manuel
- ✅ Cancel avec **ClientOrderID + ServerOrderID + TradeAccount**
- ✅ Double envoi cancel par securite
- ✅ `_verify_cancel` 1s apres (Timer) pour re-cancel si echec

Le bot gere l'OCO manuellement :
1. `register_oco_pair(tp_cid, sl_cid)` — enregistre la paire
2. `_recv_loop` detecte fill (OrderStatus=**7**) via ORDER_UPDATE type 301
3. `_handle_order_update` annule l'oppose via cancel_order
4. `cancel_order` envoie **2 fois** avec ClientOrderID + **ServerOrderID** + TradeAccount
5. `_verify_cancel` re-cancel 1s apres par securite (Timer)
6. `_oco_processed` set empeche les doubles annulations

### Flow Bracket (3 ordres separes)
```
1. Parent MARKET (OpenCloseTrade=1) → poll fill (status=7, recv timeout=1s)
2. TP LIMIT (OpenCloseTrade=2) → immediat apres fill (~0ms)
3. SL STOP  (OpenCloseTrade=2) → 0.1s apres TP
4. register_oco_pair(tp_cid, sl_cid)
5. _recv_loop surveille → cancel oppose au fill (double envoi + verify)
6. Verif ordres ouverts → re-cancel si orphelin
```

### Timings mesures (Sim3, 02/04/2026)
- BUY → Fill : ~1-3s
- Fill → TP envoye : <1ms
- TP → SL envoye : ~100ms
- Bracket complet (BUY → SL) : ~1.2-3.2s
- Fill TP/SL → Cancel oppose : ~300ms

### Tests valides sur VPS (02/04/2026)
- test_dtc_nq_bracket.py : NQ, 4/4 tests (2x TP, 2x SL), cancel OK, 0 orphelin
- test_dtc_live.py --buy-test : ES, bracket complet, fill OK
- test_dtc_live.py --sell-test : ES, fermeture position OK
- Type 206 / IsParentOrder : teste et REJETE (SC serveur DTC ne supporte pas)

## Regles CRITIQUES

### NE PAS FAIRE
- NE PAS utiliser l'ancien projet (D:\MIA_IA_system) — architecture cassee (148K LOC)
- NE PAS entrainer LightGBM avant 15 jours de donnees propres
- NE PAS modifier le C++ sans audit — 4 fichiers a synchroniser
- NE PAS utiliser les features BN binaires mortes pour le ML
- NE PAS faire de split aleatoire — toujours walk-forward
- NE PAS over-engineer — V2 cible < 3000 LOC Python total
- NE PAS ajouter de trailing stop / rechargement avant que TP/SL fixe soit profitable
- NE PAS compter sur OCOGroup1 de Sierra Chart — TOUJOURS gerer OCO manuellement
- NE PAS utiliser Type 206, IsParentOrder, ParentTriggerClientOrderID — SC serveur DTC les ignore
- NE PAS cancel un ordre sans ServerOrderID — sera ignore silencieusement
- NE PAS fermer la connexion DTC tant que des ordres bracket sont actifs
- NE PAS traiter OrderStatus=2 comme Filled — 2=Open, 7=Filled

### TOUJOURS FAIRE
- Valider avec dmp_validator.py apres chaque collecte
- Lancer mia_bench.py apres modifications Python
- Lancer /test apres chaque modification de code (48+ tests)
- Mettre a jour PROJECT_STRUCTURE.md a chaque nouveau fichier cree
- Separer par regime dans toute analyse (trend vs range)
- Verifier schema version (3.7.2 = 262 cols)
- 1 position max par instrument, session US only, max 5 trades/jour

## Procedure modification C++ (DMP)
```
1. DMP_Reader.h    -> struct + lecture
2. DMP_Transform.h -> struct + calcul + CSV header
3. DMP_Writer.h    -> serialisation JSONL + meta
4. DMP_Config.h    -> version + nb colonnes
5. Incrementer DMP_SCHEMA_VERSION
6. Python: dmp_validator.py + mia_bench.py + dataset_builder.py
7. Deployer sur VPS (TOUJOURS les 2 dossiers):
   scp fichier.h Administrator@212.28.179.199:"C:/SIERRA CHART TRADING/ACS_Source/"
   scp fichier.h Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CPP/MIA_REFACTORED/DUMPER/"
8. Recompiler dans Sierra Chart (Analysis -> Build Custom Studies DLL)
9. Reload Data Charts 30/31 (eviter bug OVN croissant)
```

## Acces VPS
```bash
# Connexion SSH directe (cle ed25519, sans mot de passe)
ssh Administrator@212.28.179.199

# Copier un fichier VERS le VPS
scp fichier.h Administrator@212.28.179.199:"C:/SIERRA CHART TRADING/ACS_Source/"

# Copier un fichier DEPUIS le VPS
scp Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/ES/20260330_ES.jsonl" D:/TRADING_SIERRA_CHART_AUTO/DATA/ES/

# Lister les fichiers sur le VPS
ssh Administrator@212.28.179.199 "dir C:\TRADING_SIERRA_CHART_AUTO\DATA\ES\ /b"
```

## Agents specialises (.claude/agents/)

| Agent | Modele | Role |
|-------|--------|------|
| data-sync | Haiku | VPS -> Local -> Validation schema |
| schema-auditor | Sonnet | Coherence C++ <-> Python (7 fichiers) |
| feature-engineer | Opus | Features derivees + screening Spearman |
| ml-trainer | Opus | LightGBM walk-forward + verdict GO/NO-GO |
| market-analyst | Opus | VWAP, regimes, benchmark, patterns |
| backtest-runner | Opus | Simulation trades + metriques P&L |
| deploy-manager | Haiku | SCP vers VPS (ACS_Source + DUMPER) |

Claude orchestre automatiquement — tu parles normalement, le bon agent est dispatch.

## Slash Commands (.claude/commands/)
```
/sync         Recupere les JSONL du VPS, valide automatiquement
/validate     Valide les derniers fichiers (schema, colonnes, coherence)
/test         Suite de tests automatiques (48+ tests, pipeline complet)
/bench        Lance mia_bench.py (benchmark complet)
/train        Pipeline complet DatasetBuilder v2 + LightGBM
/vwap         Etude VWAP SD1-SD3 complete
/audit-cpp    Verifie coherence schema C++ <-> Python
```

## Hooks automatiques (settings.json)

| Hook | Declencheur | Action |
|------|-------------|--------|
| SessionStart | Ouverture Claude Code | Auto-sync JSONL du VPS via SCP |

## Commandes quotidiennes
```bash
# Option 1 : Slash commands (recommande)
/sync          # Recupere les donnees du VPS + valide
/train         # Quand 15+ jours de donnees

# Option 2 : Manuel
scp Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/ES/*.jsonl" D:/TRADING_SIERRA_CHART_AUTO/DATA/ES/
scp Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/NQ/*.jsonl" D:/TRADING_SIERRA_CHART_AUTO/DATA/NQ/
python CORE/dmp_validator.py DATA/ES/YYYYMMDD_ES.jsonl DATA/NQ/YYYYMMDD_NQ.jsonl
python -X utf8 CORE/labeler.py
python CORE/dataset_builder.py
python CORE/train_lightgbm.py
```

## Procedure MenthorQ — Quand Jackson envoie les donnees CTA/Options

Quand Jackson colle un JSON avec des donnees CTA/MenthorQ dans le chat :
1. Creer `DATA/MENTHORQ/YYYYMMDD_cta.json` (CTA seul)
2. Creer `DATA/MENTHORQ/YYYYMMDD_menthorq_complete.json` (CTA + key_levels + vol_model)
3. Copier les 2 fichiers sur le VPS via SCP :
   ```bash
   scp DATA/MENTHORQ/YYYYMMDD_cta.json Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/MENTHORQ/"
   scp DATA/MENTHORQ/YYYYMMDD_menthorq_complete.json Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/MENTHORQ/"
   ```
4. Verifier que `/api/cta` retourne la bonne date

**Format des fichiers** :
- `_cta.json` : `{ date, source, CTA: { ES, NQ, GOLD, TREASURY_10Y, TREASURY_2Y, BRENT, EUR_USD, CHF_USD, GSCI_COMMODITY, US_TREASURY_BOND } }`
- `_menthorq_complete.json` : meme chose + `key_levels: { ES, NQ }` + `vol_model: { ES, NQ }` (avec top_gex_strikes, bl_levels, gamma_wall_0dte)
- Chaque instrument CTA : `{ position_today, position_yesterday, position_1m_ago, percentile_1m, percentile_3m, percentile_1y, zscore_3m }`
- key_levels : call_resistance, put_support, hvl, 0dte, 1d_max, 1d_min, iv_30d, gamma_condition, pc_oi, total_gex, net_gex, pc_gex, total_dex, net_dex, pc_dex
- vol_model : iv_30d, GEX/DEX, top_gex_strikes (10 strikes), bl_levels (10 Break Levels), gamma_wall_0dte

**NE PAS demander confirmation** — faire les 4 etapes automatiquement.

## Infos techniques

| Parametre | Valeur |
|-----------|--------|
| VPS IP | 212.28.179.199 |
| Broker | AMP via Teton CME Routing |
| Data Feed | Denali (SC Data) |
| Instruments | ESM26-CME, NQM26-CME |
| Tick Size | 0.25 (ES et NQ) |
| Tick Value | ES micro $1.25, NQ micro $0.50 |
| Timeframe | 1 minute |
| Sessions | US 09:30-16:00 ET (trading), Asia/London (collecte only) |

## Deploiement C++ sur le VPS
```
Dossiers VPS (TOUJOURS les 2):
  1. C:\SIERRA CHART TRADING\ACS_Source\      <- Sierra Chart compile ICI
  2. C:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\DUMPER\  <- Backup

Workflow:
  Claude modifie sur PC -> /audit-cpp -> deploy-manager envoie via SCP
  -> Jackson compile dans Sierra Chart (5 sec) -> Reload Charts 30/31
```

## Site Web & Dashboard — Architecture CRITIQUE (ne pas oublier !)

### 2 produits distincts et COMPLEMENTAIRES

| Produit | URL | Repo | Heberge sur | Type |
|---------|-----|------|-------------|------|
| **Site marketing** | https://mia-ia-system.com | `jackson97300/mia-website` (PUBLIC) | Vercel | Build statique Next.js (export) |
| **Dashboard app** | https://dashboard.mia-ia-system.com | `jackson97300/TRADING_SIERRA_CHART_AUTO` (PRIVE) | VPS Windows via Cloudflare Tunnel | FastAPI/Uvicorn port 8503 |

### Site marketing mia-ia-system.com

**Repo local** : `D:\mia-website\` (git remote = jackson97300/mia-website)
**Push via** : GitHub Desktop → Vercel auto-deploy sur push main
**Framework Vercel** : "Other" (Build Command vide, Output Directory ".")
**IMPORTANT** : Vercel **ne build PAS** — il sert les fichiers statiques tels quels

**Contenu du repo `D:\mia-website\`** :
- Seulement le **BUILD statique** (dossier `_next/`, pas de `package.json`, pas de `src/`)
- Pages : `/`, `/register`, `/login`, `/calendar`, `/education`, `/legal`, `/privacy`, `/terms`, `/forgot-password`, `/risk`, `/coming-soon`
- `mia-fixes.js` : **patch JavaScript critique** qui modifie le site apres chargement React (hide Google OAuth button, redirect submit, add footer links, etc.)
- `mia-fixes.css` : fixes CSS (header opaque, body padding, ticker)
- `ticker.js` : ticker SPY/QQQ/IWM + Mag 7
- `vercel.json` : framework "Other"
- `robots.txt`, `sitemap.xml`

**Le SOURCE Next.js est PERDU ou INTROUVABLE** (verifie 09/04/2026).
Les dossiers `D:\MIA_IA_system\website-nextjs\` et `website_nextjs\` contiennent un source **incomplet** (layout.tsx + page.tsx seulement, pas de register/login).
Un source complet existe peut-etre dans `D:\$RECYCLE.BIN\S-1-5-21-...\$RJQSX6F\` (corbeille Windows).

**Ce que fait `mia-fixes.js` (patches a froid sur le build)** :
```js
// Variables globales
var DASHBOARD_URL = 'https://dashboard.mia-ia-system.com';

// 1. Hide Google OAuth button (qui etait un placeholder "A implementer")
function hideGoogleOAuth() { ... }

// 2. Intercept form submit sur /register et /login → redirect vers dashboard
function fixLoginRegister() {
  if (path.indexOf('/register') !== -1 && loginForm) {
    loginForm.addEventListener('submit', function(e) {
      e.preventDefault();
      window.location.href = DASHBOARD_URL + '/register';
    });
  }
}

// 3. Add footer links Dashboard + Discord
function fixFooterDashboard() { ... }

// 4. Redirect buttons pointing to localhost → DASHBOARD_URL
// 5. Header opaque force (backdrop shield div)
// 6. Pricing 3 tiers (hide+insert anti-React)
// 7. Ticker retry 1s/3s/5s (anti React hydration)
// 8. Section Resultats Verifies ($19,880 payouts, 3 prop firms)
// 9. SEO meta descriptions
```

**Flow actuel signup (casse, a reparer)** :
```
User → mia-ia-system.com/register
     → Next.js affiche form UI (mockup, pas de fetch natif)
     → mia-fixes.js intercept submit event
     → window.location = dashboard.mia-ia-system.com/register
     → Dashboard n'a PAS de page /register dediee
     → Dashboard home affiche le formulaire sidebar trial
     → User doit RE-REMPLIR le form (mauvaise UX)
```

**Flow cible (a coder)** :
```
User → mia-ia-system.com/register
     → Next.js affiche form (patche par mia-fixes.js)
     → mia-fixes.js intercept submit + fait fetch cross-origin vers
       https://dashboard.mia-ia-system.com/api/auth/trial
     → Backend cree user, retourne JWT
     → mia-fixes.js stocke token dans localStorage cross-domain (via iframe ou cookie .mia-ia-system.com)
     → Redirect vers dashboard.mia-ia-system.com deja loggue
```

**CORS** : dashboard.mia-ia-system.com doit autoriser l'origine `https://mia-ia-system.com` dans les headers.

### Dashboard dashboard.mia-ia-system.com

**Repo** : `D:\TRADING_SIERRA_CHART_AUTO\` (sous-dossier `DASHBOARD/`)
**Stack** : FastAPI + Uvicorn + HTML/JS/CSS statique (lightweight-charts, pas de framework)
**Port VPS** : 8503 (Uvicorn --workers 1)
**Tunnel** : Cloudflare Tunnel "tableau de bord Mia" → dashboard.mia-ia-system.com
**users.json** : `DASHBOARD/users.json` (hors git — contient owner + trial users)
**JWT secret** : `.jwt_secret` (hors git, persistant)

**Endpoints auth** (DASHBOARD/api/auth.py) :
- `POST /api/auth/register` — signup classique
- `POST /api/auth/login` — login avec downgrade auto trial expire + tracking last_login
- `POST /api/auth/trial` — signup trial 7j + capture IP/pays/langue/UA/UTM/RGPD + notif Discord
- `GET /api/auth/verify?token=...` — confirme email (trial classique)
- `POST /api/auth/resend-verification` — renvoie email verification (rate limit 60s)
- `POST /api/auth/google` — OAuth Google (verifie ID token server-side + cree/login user)
- `POST /api/auth/promo` — code promo

**Endpoints admin (owner only)** :
- `/api/bot/stop`, `/api/bot/start`, `/api/bot/status` — kill switch
- `/api/admin/users/stats` — stats users par tier
- `/api/admin/bot/health` — heartbeat bot
- `/api/admin/bot/recent_trades`, `/api/admin/bot/rejections`
- `/api/admin/discord/test`
- `/api/admin/logs/tail`

**Tiers users** :
```
TIER_LEVELS = {"free": 0, "starter": 1, "trial": 2, "pro": 2, "admin": 3, "owner": 3}
```
- **FREE** : chart OHLC sans niveaux, banner prix, pas de 4-big-boxes, pas de jauges, pas de MTF, pas de pages dediees
- **STARTER (19$/mois)** : Overview complet + Niveaux & VWAP + Alertes (pas de pages PRO)
- **PRO (49$/mois)** : tout accessible
- **TRIAL** : acces PRO 7 jours
- **OWNER (jackson)** : PRO + Admin Tools

**Pattern UI tier gating (Pattern D - TradingView style)** :
- Floutage leger 3px + badge coin discret "🔒 STARTER" / "🔒 PRO"
- CTA global en bas d'Overview (FREE only)
- Modal au click sur page PRO bloquee (pas d'overlay permanent)
- Bandeau dore en haut (FREE only)
- Navigation grise + badge PRO pour pages bloquees

### Stack auth cible (en cours 09/04/2026)

| Composant | Provider | Statut |
|-----------|----------|--------|
| Signup/Login classique | FastAPI + PBKDF2 + JWT | ✅ Fonctionnel |
| Google OAuth | Google Identity Services | Backend ✅ / Frontend ⏳ / Client ID ⏳ |
| Email verification | Brevo SMTP API (300/jour gratuit) | Module ✅ / API key ⏳ |
| Captcha anti-bot | Cloudflare Turnstile | Non implemente ⏳ |
| 2FA TOTP | - | BACKLOG (Jackson : "plus tard") |

**Fichiers de secrets (tous dans .gitignore)** :
- `.jwt_secret` : secret HMAC pour JWT
- `.brevo_secret` : API key Brevo (format xkeysib-...)
- `.google_oauth_secret` : Client ID Google OAuth
- `.turnstile_secret` : site key + secret key Cloudflare Turnstile
- `BOT/alert_config.json` : 12 webhooks Discord V1

### Deploiement dashboard sur VPS

```bash
# Fichiers backend
scp DASHBOARD/api/*.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/api/"

# Fichiers frontend (statiques servis par FastAPI)
scp DASHBOARD/static/index.html Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/"
scp DASHBOARD/static/js/dashboard.js Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/js/"
scp DASHBOARD/static/css/dashboard.css Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/css/"

# Bump version dans index.html (dashboard.js?v=XX + dashboard.css?v=XX) pour casser le cache
# Restart uvicorn uniquement si app.py ou auth.py modifie :
ssh Administrator@212.28.179.199 'powershell -Command "Get-CimInstance Win32_Process -Filter \"Name like '\''python%'\''\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"'
ssh Administrator@212.28.179.199 'cd C:/TRADING_SIERRA_CHART_AUTO && "C:/Program Files/Python311/python.exe" -m uvicorn DASHBOARD.api.app:app --host 0.0.0.0 --port 8503 --workers 1' &
```

**Le dashboard uvicorn n'est PAS persistant** — meurt quand la session SSH ferme. A rendre persistant avec nssm ou Task Scheduler (backlog).

### Workflow modification site marketing

```
1. Si modification simple (patch CSS/JS) :
   - Modifier D:\mia-website\mia-fixes.js ou mia-fixes.css
   - GitHub Desktop : commit + push
   - Vercel auto-deploy en 30-60s

2. Si modification profonde (nouvelle page, formulaire) :
   - PROBLEME : source Next.js perdu/introuvable
   - Solution temporaire : patch via mia-fixes.js
   - Solution propre : reconstruire source Next.js OU migrer vers du HTML statique simple

3. NE JAMAIS push d'infos sensibles dans ce repo (il est PUBLIC)
```

## Feuille de route

| Phase | Description | Statut |
|-------|-------------|--------|
| 1 | Collecte DMP propre (schema 3.7.2) | En cours (depuis 28/03) |
| 2 | labeler.py + dataset_builder.py | Cree |
| 3 | train_lightgbm.py (2 modeles buy+sell) | Cree |
| 4 | Bot V2 (DTC + Risk + Orders + OCO) | VALIDE (01/04) |
| 5 | Collecte 15+ jours -> training reel | Attente mi-avril |
| 6 | Paper trading (bot + modeles) | Attente |
| 7 | Bot live VPS (DTC -> Sierra -> AMP) | Attente |

## Principes
- Data quality is the foundation — ne jamais avancer sur des donnees sales
- Signal quality over quantity — moins de signaux, meilleurs signaux
- Anti-overfitting — 20+ jours minimum avant ML
- Edge simple — le ML combine, pas de regles en cascade
- Le C++ est un collecteur muet — Python est le cerveau
- Commencer simple (TP/SL fixe), complexifier apres validation (trailing)
- Les agents specialises font le travail, Claude orchestre

## Bugs connus

| Bug | Symptome | Statut |
|-----|----------|--------|
| IB High null | dist_ib_high = INVALID sur charts footprint (sc.High renvoie le high du footprint, pas de la barre 1min) | CORRIGE — ib_recalc.py Python post-processing recalcule IB depuis bar_high/bar_low |
| OCO orphelin | OCOGroup1 de Sierra Chart ne cancel pas l'oppose quand TP/SL touche → ordre orphelin dangereux | CORRIGE — OCO manuel avec ServerOrderID + double cancel + verify_cancel (02/04) |
| ORDER_UPDATE type | DTC_ORDER_UPDATE=304 ne matchait rien en JSON mode | CORRIGE — type=301 (valide V1) |
| OrderStatus=2 | is_filled traitait status=2 (Open) comme Filled → faux positifs | CORRIGE — seul status=7 = Filled (02/04) |
| Cancel sans ServerOrderID | cancel_order n'envoyait que ClientOrderID → ignore par SC | CORRIGE — ServerOrderID obligatoire + double envoi (02/04) |
| DTC natif bracket | Type 206, IsParentOrder, ParentTriggerClientOrderID | NON SUPPORTE — SC serveur DTC ignore silencieusement (teste 02/04) |

## Communication
- Langue : Francais
- Style : Technique, direct, pas de compliments inutiles
- Role de Claude : Superviseur adversarial + orchestrateur d'agents
- Livraison : Fichiers finis prets a deployer
- JAMAIS envoyer de fichier sur le VPS sans confirmation explicite
