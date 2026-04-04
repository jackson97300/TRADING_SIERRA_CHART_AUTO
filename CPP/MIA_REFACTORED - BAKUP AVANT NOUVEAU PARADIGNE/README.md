# 🎯 MIA AutoTrader BN v1 - Bot C++ Sierra Chart

**Version**: v2.0-REFACTORED  
**Mise à jour**: 2026-02-06  
**Total**: 14 942 lignes (19 fichiers)

---

## 📋 DESCRIPTION

MIA (Market Intelligence Advisor) est un bot de trading automatisé pour les **contrats micro futures** ES (MES) et NQ (MNQ) intégré à Sierra Chart via l'API ACSIL.

### Systèmes intégrés
- **Bataille Navale (BN)**: OrderFlow footprint (delta, absorptions, rotations)
- **MenthorQ**: Niveaux options (Gamma Walls, HVL, GEX, PUT/CALL)
- **Volume Profile**: LVN/HVN pour SL/TP dynamique (5 périodes: 1j→200j)
- **VWAP**: Contexte directionnel + bandes de déviation

---

## 📁 STRUCTURE DES FICHIERS

### Emplacement
```
D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\
```

### Fichiers (19 total)

| Fichier | Lignes | Rôle |
|---------|--------|------|
| **MIA_Main.cpp** | 2030 | ⭐ Fichier à compiler |
| **study_mapping.json** | 120 | 🆕 Configuration Study IDs |
| MIA_Config.h | 1063 | Structures, SymbolConfig |
| MIA_Globals.h | 33 | Variables globales |
| MIA_StateManager.h | 283 | Gestion état thread-safe |
| MIA_StudyConfig.h | 277 | Chargement Study IDs JSON |
| MIA_DataReader.h | 1824 | Collecte BN + MenthorQ |
| MIA_Indicators.h | 649 | VIX, ATR, VWAP, Confluence |
| MIA_DataDumper.h | 498 | Export JSONL backtesting |
| MIA_Layers.h | 1909 | Layers 1-4 validation |
| MIA_SLTP.h | 138 | Définitions SL/TP |
| MIA_SLTP_Calc.h | 807 | Calcul SL/TP dynamique |
| MIA_Execution.h | 1070 | Envoi ordres + Trailing |
| MIA_Utils.h | 276 | Helpers |
| MIA_ExtensionTracker.h | 280 | Tracking extensions |
| MIA_Logging.h | 1953 | Logs et Dashboard |
| MIA_Interfaces.h | 288 | Interfaces abstraites |
| MIA_Tests.h | 494 | Tests unitaires |
| MIA_MockImpl.h | 553 | Implémentation mock |
| MIA_SierraImpl.h | 517 | Implémentation Sierra |

---

## ⚙️ CONFIGURATION DES CHARTS

### Inputs Sierra Chart (valeurs par défaut)

| Input # | Nom | ES | NQ |
|---------|-----|----|----|
| 0 | Bot Enabled | ✅ | ✅ |
| 1 | Trade ES | ✅ | - |
| 2 | Trade NQ | - | ✅ |
| 5 | Footprint Chart | **1** | - |
| 6 | Barres Chart | **25** | - |
| 7 | NQ Footprint Chart | - | **2** |
| 8 | NQ Barres Chart | - | **23** |
| 9 | Main Chart | **25** | - |
| 10 | NQ Main Chart | - | **23** |
| 11 | VIX Chart | **15** | **15** |
| 12 | ES Daily Chart | **16** | - |
| 13 | NQ Daily Chart | - | **17** |
| 14 | Mode | 0=PROD / 1=TEST | |
| 15 | Trade Rectangles | ✅ | ✅ |
| 16 | Data Dump | ✅ | ✅ |
| 17 | ES Volume Profile | **26** | - |
| 18 | NQ Volume Profile | - | **27** |
| 19 | ES Swing Structure | **28** | - |
| 20 | NQ Swing Structure | - | **29** |
| 21 | ES Composite Profile | **31** | - |
| 22 | NQ Composite Profile | - | **30** |

---

## 📊 STUDY IDs (study_mapping.json)

> ⚠️ **Source de vérité**: `study_mapping.json` (01/03/2026). Ces tables sont un résumé — toujours consulter le JSON en cas de doute.

### ES Footprint (Chart 1)
| Étude | ID | Étude | ID |
|-------|----|-------|----|
| EDGE_BUY | 32 | EDGE_SELL | 35 |
| COLOR_UP | 56 | COLOR_DOWN | 57 |
| ABSORB_ASK | 25 | ABSORB_BID | 26 |
| ROTATION_UP | 19 | ROTATION_DOWN | 20 |
| FPBS | 31 | CLUSTER_VOL | 10 |

### NQ Footprint (Chart 2)
| Étude | ID | Étude | ID |
|-------|----|-------|----|
| EDGE_BUY | 55 | EDGE_SELL | 56 |
| COLOR_UP | 53 | COLOR_DOWN | 54 |
| ROTATION_UP | 21 | ROTATION_DOWN | 22 |
| FPBS | 33 | TRIPLE_ASK | 28 |
| LONG_UP_BAR | 23 | LONG_DOWN_BAR | 24 |

### ES Barres (Chart 25)
| Étude | ID | Étude | ID |
|-------|----|-------|----|
| MQ_GAMMA | 2 | MQ_BLIND | 22 |
| VWAP | 1 | LONG_UP_BAR | 18 |
| LONG_DOWN_BAR | 17 | COLOR_UP | 24 |

### NQ Barres (Chart 23)
| Étude | ID | Étude | ID |
|-------|----|-------|----|
| MQ_GAMMA | 25 | MQ_BLIND | 26 |
| VWAP | 1 | LONG_UP_BAR | 18 |

---

## 💰 CONFIGURATION TRADING

### ES - Micro MES
| Paramètre | Valeur | $ |
|-----------|--------|---|
| Tick Size | 0.25 | |
| Tick Value | $1.25 | Micro |
| **SL Default** | 20 ticks | $25 (5 pts) |
| **TP Default** | 24 ticks | $30 (6 pts) |
| RR Ratio | 1.20 | |
| Trailing Activation | +15 ticks | |
| Trailing Distance | 8 ticks | |
| Break-Even | +10 ticks | |

### NQ - Micro MNQ
| Paramètre | Valeur | $ |
|-----------|--------|---|
| Tick Size | 0.25 | |
| Tick Value | $0.50 | Micro |
| **SL Default** | 28 ticks | $14 (7 pts) |
| **TP Default** | 35 ticks | $17.50 (8.75 pts) |
| RR Ratio | 1.25 | |
| Trailing Activation | +35 ticks | |
| Trailing Distance | 12 ticks | |
| Break-Even | +15 ticks | |

---

## 🎯 LOGIQUE DES LAYERS

### Layer 1 - Proximité MenthorQ
Vérifie la proximité avec les niveaux options:
- **Score 3 (MAJEUR)**: HVL, GAMMA, GEX 1-3
- **Score 2 (IMPORTANT)**: PUT/CALL, 1D MIN/MAX, VAH/VAL
- **Score 1 (MINEUR)**: VWAP, SD±1, BLIND
- Distance max: 15 ticks

### Layer 2 - Confirmation OrderFlow
- **LONG**: (color_up OR edge_buy) AND delta>0 AND (rotation_up OR absorb_ask)
- **SHORT**: (color_down OR edge_sell) AND delta<0 AND (rotation_down OR absorb_bid)

### Layer 3 - Contexte Directionnel
- **NQ**: `vwap_slope > 0 AND smart_money > 0` (LONG)
- **ES**: `vwap_slope > 0 AND delta_pct > 0` (LONG)

### Layer 4 - Score Qualité (0-100)
| Composant | Points |
|-----------|--------|
| Importance L1 | 0-25 |
| Confluence BN | 0-25 |
| Tendance alignée | 0-20 |
| Confiance moyenne | 0-20 |
| VIX optimal | 0-10 |

**Grades**: A (80+) = TP+30%, B (70-79) = TP+15%, C (55-69) = Standard, D (<55) = REJETÉ

---

## 🔧 INSTALLATION

### 1. Copier les fichiers
```
D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\
├── MIA_Main.cpp          ← À compiler
├── study_mapping.json    ← Configuration Study IDs
└── MIA_*.h               ← Tous les headers
```

### 2. Compiler
1. Sierra Chart → **Analysis → Build Custom Studies DLL**
2. Source: `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\MIA_Main.cpp`
3. Cliquer **Build**

### 3. Ajouter l'étude
1. **Analysis → Studies → Add Custom Study**
2. Chercher: **"MIA AutoTrader Bataille Navale v1"**

---

## ⚠️ RÈGLES CRITIQUES

1. **`#pragma once`** en haut de chaque `.h`
2. **`inline`** devant chaque fonction dans les headers
3. **Ordre des includes** dans `MIA_Main.cpp` est IMPORTANT
4. **MODE_TEST (Input 14 = 1)** avant production
5. **Ne jamais modifier** les TP/SL sans backtest

---

## 📁 CHEMINS IMPORTANTS

| Type | Chemin |
|------|--------|
| Bot C++ | `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\` |
| study_mapping.json | `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\study_mapping.json` |
| Logs | `D:\LOGS\MIA\` |
| Dashboard | `D:\LOGS\MIA\dashboard_realtime.json` |
| Snapshots | `D:\MIA_IA_system\TRADING_SIERRA_CHART_AUTO\SNAPSHOTS\` |
| Data Dump | `D:\MIA_IA_system\TRADING_SIERRA_CHART_AUTO\DUMP\` |

---

## 📅 HISTORIQUE

| Date | Version | Changements |
|------|---------|-------------|
| 31/01/2026 | v1.0 | Refactoring initial (12 modules) |
| 01/02/2026 | v1.1 | Composite Profiles LVN/HVN |
| 02/02/2026 | v1.2 | Session/Swing data, SL/TP dynamique |
| 05/02/2026 | v1.3 | Software Stop-Loss |
| 06/02/2026 | v2.0 | study_mapping.json, chemins corrigés |

---

*Documentation générée le 2026-02-06*
