# CLAUDE.md — MIA Trading System V2

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
| TP/SL | ATR-based : SL = ATR * 0.08, TP = SL * 2.0 (R:R fixe 2:1) |
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
