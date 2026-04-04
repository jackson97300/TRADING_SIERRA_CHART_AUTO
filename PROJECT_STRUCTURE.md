# 📁 STRUCTURE DU PROJET MIA V2 — Trading System
## Version 2.0 — 01 Avril 2026

---

## 🎯 VUE D'ENSEMBLE

```
MIA V2 = C++ DMP (collecte) + Python ML (cerveau) + Bot (exécution)

  VPS (212.28.179.199)              PC Local (développement)
  ┌─────────────────────┐           ┌─────────────────────────┐
  │ Sierra Chart + DMP  │  ← SSH →  │ VS Code + Claude Code   │
  │ MenthorQ Scraper    │  ← SCP →  │ Python ML Pipeline      │
  │ Data Collection 24/7│           │ LightGBM Training       │
  │ OpenClaw (standby)  │           │ Tests + Bench           │
  └─────────────────────┘           └─────────────────────────┘
```

---

## 📂 PC LOCAL — D:\TRADING_SIERRA_CHART_AUTO\

```
D:\TRADING_SIERRA_CHART_AUTO\
│
├── 🧠 CORE\                          ← MODULES PYTHON ACTIFS (tout le dev ici)
│   ├── dmp_reader.py                    Lecture fichiers JSONL
│   ├── dmp_validator.py                 Validation quotidienne (schema 3.7.2)
│   ├── ib_recalc.py                     Recalcul IB depuis bar_high/bar_low
│   ├── labeler.py                       Labels BUY/SELL/HOLD (TP/SL simulation)
│   ├── dataset_builder.py               DatasetBuilder v2 (DMP+ctx+im+amd+rvol+mq)
│   ├── train_lightgbm.py               Training LightGBM (2 modeles buy+sell)
│   ├── rolling_features.py             36 features contextuelles (ctx_*)
│   ├── intermarket_features.py          Correlations ES/NQ (im_*)
│   ├── mia_amd.py                       AMD Power of 3 : 18 features (amd_*)
│   ├── rvol.py                          Volume relatif + absorption (10 features)
│   ├── game_changers.py                 Market Profile: open type, day type
│   ├── mia_entry.py                     Detection zones d'entree
│   ├── mia_sltp.py                      SL/TP adaptatifs
│   ├── mia_sim.py                       Simulateur de backtest
│   ├── mia_bench.py                     Benchmark complet (19 tests)
│   ├── mia_double_top.py               Double Top / Bottom detector
│   ├── mia_vwap_study.py               Etude VWAP SD bands
│   ├── mia_session_planner.py          Session Planner
│   ├── mia_menthorq_reader.py          📊 Lecteur MenthorQ → 37 features mq_*
│   ├── mia_menthorq_scraper.py         📊 Scraper MenthorQ (déployé VPS)
│   ├── test_all.py                      ✅ Suite de tests (48+ tests)
│   ├── test_menthorq_reader.py         ✅ Tests MenthorQ (45 tests)
│   └── .env.menthorq                    🔒 Credentials MenthorQ (pas versionné)
│
├── ⚙️ CPP\MIA_REFACTORED\
│   ├── DUMPER\                          ← DMP C++ (collecteur Sierra Chart)
│   │   ├── DMP_Main.cpp                   Seul fichier à compiler
│   │   ├── DMP_Config.h                   Schema 3.7.2, 262 colonnes
│   │   ├── DMP_Reader.h                   Lecture SC + VAP direct + IB progressif
│   │   ├── DMP_Transform.h                Features ML + MQ 0DTE fallback
│   │   ├── DMP_Writer.h                   Serialisation JSONL
│   │   ├── DMP_OpenType.h                 Open Type / Day Type / Rule 80%
│   │   ├── DMP_HVN_LVN.h                 HVN/LVN session
│   │   └── DMP_ProfileShape.h             Volume Profile shape
│   │
│   ├── MIA_Main.cpp                     Bot AutoTrader (Phase 6 — futur)
│   └── MIA_AutoTrader_BN_v1.cpp         Bot V1 (référence)
│
├── 📊 DATA\
│   ├── ES\                              JSONL bruts par jour (ES)
│   │   └── YYYYMMDD_ES.jsonl
│   ├── NQ\                              JSONL bruts par jour (NQ)
│   │   └── YYYYMMDD_NQ.jsonl
│   ├── MENTHORQ\                        📊 Données MenthorQ (scraper)
│   │   ├── YYYYMMDD_menthorq_complete.json
│   │   └── MENTHORQ_CATALOGUE_COMPLET.md
│   ├── LABELS\                          Labels parquet (labeler.py)
│   ├── DATASETS\                        Datasets ML v2 (parquet)
│   ├── MODELS\                          Modeles LightGBM + configs
│   └── BACKUP\                          Backup données anciennes
│
├── 🏗️ BOT\                             ← BOT V2 (deploye sur VPS, valide 01/04)
│   ├── bot_config.py                    Parametres centralises (seuils, limites)
│   ├── dtc_connector.py                 Connexion DTC JSON/TCP + OCO manuel
│   ├── order_manager.py                 Positions + brackets SL/TP
│   ├── risk_manager.py                  Half-Kelly, circuit breaker, kill switch
│   ├── signal_engine.py                 LightGBM score → signal buy/sell
│   ├── position_monitor.py             TP/SL, time exit, EOD flatten
│   ├── trade_journal.py                 Journal auto JSONL
│   ├── bot_main.py                      Boucle principale + pre-trade gates
│   ├── test_bot.py                      Tests unitaires (46 tests)
│   ├── test_oco_persistent.py          Test OCO persistant 1 instrument (valide)
│   ├── test_oco_dual.py                Test OCO dual ES+NQ simultane (valide)
│   ├── test_dtc_bracket.py             Test bracket standalone
│   ├── test_dtc_live.py                Test connexion DTC basique
│   └── cancel_orphan.py                Utilitaire annulation ordres orphelins
│
├── 📚 V1_ARCHIVE\                       ← V1 (lecture seule, référence)
│   ├── EXECUTION\                       DTC connector, risk manager (réutilisable)
│   ├── CORE\                            Trailing stop, kill switch, cooldowns
│   ├── ML\                              Training LightGBM V1
│   └── CONFIG\                          trading_params.py, unified_thresholds.py
│
├── 🔧 .claude\
│   ├── commands\                        Slash commands
│   │   ├── sync.md                      /sync — Récupère données VPS
│   │   ├── validate.md                  /validate — Validation DMP
│   │   ├── test.md                      /test — Suite de tests (48+)
│   │   ├── bench.md                     /bench — Benchmark complet
│   │   ├── train.md                     /train — Pipeline ML
│   │   ├── vwap.md                      /vwap — Étude VWAP
│   │   └── audit-cpp.md                /audit-cpp — Cohérence C++/Python
│   ├── agents\                          7 agents spécialisés
│   └── settings.json                    Hooks (SessionStart, PostToolUse)
│
├── 📋 CLAUDE.md                         Instructions projet (source of truth)
├── 📋 PROJECT_STRUCTURE.md              CE DOCUMENT
├── 📋 V1_NOTES.md                       Audit V1 : leçons pour V2
└── 📋 README.md                         README du projet
```

---

## 🖥️ VPS — 212.28.179.199 (Windows Server)

```
C:\TRADING_SIERRA_CHART_AUTO\
│
├── CORE\                                Scripts Python (déployés depuis PC)
│   ├── mia_menthorq_scraper.py          📊 Scraper MenthorQ (cron 2x/jour)
│   ├── .env.menthorq                    🔒 Credentials
│   └── [autres .py déployés]
│
├── CPP\MIA_REFACTORED\DUMPER\           Backup C++ (identique à PC)
│   ├── DMP_Main.cpp
│   ├── DMP_Reader.h
│   └── [autres .h]
│
├── DATA\
│   ├── ES\                              JSONL collectés en temps réel
│   ├── NQ\                              JSONL collectés en temps réel
│   └── MENTHORQ\                        JSON scraper MenthorQ
│
├── STUDIES\                             Scans Sierra Chart (chart_*.json)
└── PYTHON\                              Scripts utilitaires

C:\TRADING_SIERRA_CHART_AUTO\BOT\        ← Bot Python (deploye depuis PC)
├── dtc_connector.py                     Connexion DTC + OCO manuel
├── order_manager.py                     Bracket orders
├── bot_main.py                          Boucle principale
├── test_oco_dual.py                     Test valide ES+NQ
└── [autres modules]

C:\SIERRA CHART TRADING\
├── ACS_Source\                          ← C++ compilé ICI
│   ├── DMP_Main.cpp                     Source DMP (scp depuis PC)
│   ├── DMP_Reader.h
│   ├── DMP_Transform.h
│   └── [autres .h]
├── Data\
│   └── DMP_Main_64.dll                 DLL compilée
└── SierraChart.exe                      Sierra Chart
```

---

## 🔄 PIPELINE DE DONNÉES

```
                    VPS (24/7)                          PC (analyse)
              ┌─────────────────┐                ┌──────────────────┐
Denali Feed → │ Sierra Chart    │                │                  │
              │   ↓             │                │                  │
              │ DMP C++ (262    │   SCP/sync     │ IBRecalc         │
              │ cols/barre)     │ ──────────────→│   ↓              │
              │   ↓             │                │ RollingFeatures  │
              │ JSONL files     │                │   ↓              │
              │                 │                │ IntermarketFeat  │
              │ MenthorQ Scraper│   SCP/sync     │   ↓              │
              │ (cron 2x/jour)  │ ──────────────→│ MenthorQReader   │
              │   ↓             │                │   ↓              │
              │ JSON files      │                │ AMD + RVOL       │
              └─────────────────┘                │   ↓              │
                                                 │ Labeler          │
                                                 │   ↓              │
                                                 │ DatasetBuilder   │
                                                 │   ↓              │
                                                 │ LightGBM Train   │
                                                 │   ↓              │
                                                 │ GO/NO-GO         │
                                                 └──────────────────┘

## 🤖 PIPELINE EXECUTION (BOT → DTC → SIERRA CHART → AMP)

```
                        VPS (Bot Python)
  ┌──────────────────────────────────────────────────────┐
  │ SignalEngine (LightGBM)                              │
  │   ↓ score_buy / score_sell                           │
  │ RiskManager (gates, circuit breaker, Half-Kelly)     │
  │   ↓ can_trade?                                       │
  │ OrderManager                                         │
  │   ↓ send_market_order(bracket)                       │
  │ DTCConnector (JSON/TCP port 11099)                   │
  │   ├── Parent MARKET → fill (status=7)                │
  │   ├── TP LIMIT + SL STOP (OCOGroup)                  │
  │   └── _recv_loop: OCO manuel (cancel oppose au fill) │
  └──────────────────┬───────────────────────────────────┘
                     │ DTC Protocol
                     ▼
  ┌──────────────────────────────────────────────────────┐
  │ Sierra Chart → Teton CME Routing → AMP Broker → CME  │
  └──────────────────────────────────────────────────────┘
```
```

---

## 📊 SCHEMA DMP

| Version | Colonnes | Date | Changement |
|---------|----------|------|-----------|
| 3.7.0 | 258 | 18/03/2026 | Base VIX Gamma étendu |
| 3.7.1 | 260 | 27/03/2026 | +bar_high, +bar_low |
| 3.7.2 | 262 | 28/03/2026 | +dist_vwap_d_sd3u, +dist_vwap_d_sd3d |

Schema actif : **3.7.2 — 262 colonnes DMP + 37 colonnes MenthorQ = 299 features**

---

## 🔧 TÂCHES PLANIFIÉES VPS

| Tâche | Heure (FR) | Heure (ET) | Action |
|-------|-----------|-----------|--------|
| **MIA_MenthorQ_PreMarket** | 14:15 | 08:15 | Scrape MenthorQ ES+NQ (pré-US) |
| **MIA_MenthorQ_MidDay** | 17:15 | 11:15 | Scrape MenthorQ (Swing/Blind refresh) |
| **DMP collecte** | 24/7 | 24/7 | Sierra Chart DMP (continu) |

---

## 🛡️ HOOKS AUTOMATIQUES

| Hook | Déclencheur | Action |
|------|-------------|--------|
| SessionStart | Ouverture Claude Code | Auto-sync JSONL + MenthorQ du VPS |
| PostToolUse | scp vers ACS_Source | Lance tests quick (48 tests) |

---

## ✅ TESTS AUTOMATIQUES

| Suite | Tests | Temps | Commande |
|-------|-------|-------|----------|
| test_all.py --quick | 48 | ~3s | `/test --quick` |
| test_all.py | 54 | ~10s | `/test` |
| test_menthorq_reader.py | 45 | ~2s | Module seul |

---

## 📈 FEATURES ML PAR SOURCE

| Source | Prefix | Features | Statut |
|--------|--------|----------|--------|
| DMP C++ brut | (aucun) | 262 colonnes | ✅ Collecte 24/7 |
| Rolling Features | ctx_* | 36 | ✅ |
| Intermarket | im_* | 10 | ✅ |
| AMD Power of 3 | amd_* | 18 | ✅ |
| RVOL | rvol_* | 10 | ✅ |
| MenthorQ | mq_* | 37 (29 valides) | ✅ Scraper + Reader |
| **TOTAL** | | **~373 features** | |

Après Spearman screening (|rho| >= 0.02) : **~100-130 features retenues** pour LightGBM.

---

## 🚀 FEUILLE DE ROUTE

| Phase | Description | Statut |
|-------|-------------|--------|
| 1 | Collecte DMP propre (schema 3.7.2) | ✅ En cours depuis 28/03 |
| 2 | labeler.py + dataset_builder.py | ✅ Créé |
| 3 | train_lightgbm.py (2 modeles buy+sell) | ✅ Créé |
| 4 | **Bot V2 (DTC + Risk + OCO manuel)** | ✅ Validé 01/04 |
| 5 | Collecte 15+ jours → training réel | ⏳ Attente mi-avril |
| 6 | Paper trading (bot + modèles) | ⏳ Attente |
| 7 | Bot live VPS (DTC → Sierra → AMP) | ⏳ Attente |

---

## 📋 ACCÈS & CONNEXIONS

| Ressource | Accès |
|-----------|-------|
| VPS SSH | `ssh Administrator@212.28.179.199` (clé ed25519) |
| VPS RDP | `mstsc /v:212.28.179.199` (Administrator) |
| Broker | AMP via Teton CME Routing |
| Data Feed | Denali (SC Data) |
| MenthorQ | API AJAX WordPress (scraper Python) |
| Instruments | ESM26-CME (micro), NQM26-CME (micro) |

---

*Derniere mise a jour : 01 Avril 2026*
*Version : 2.1 — Bot DTC valide*
*LOC Python actif : ~5,000 (CORE/) + ~1,500 (BOT/) — vs 148K LOC V1*
*LOC C++ actif : ~3,500 (DUMPER/) + ~7,000 (AutoTrader ref)*
*Tests : 46 (BOT) + 48 (CORE) = 94 tests automatiques*
