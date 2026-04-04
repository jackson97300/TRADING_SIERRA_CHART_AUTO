# 🚀 GUIDE COMPILATION - MIA AutoTrader C++

**Version**: v2.0  
**Date**: 2026-02-06  
**Fichiers**: 19 modules

---

## 📋 PRÉREQUIS

### Tous les fichiers dans `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\`

```
MIA_REFACTORED/
├── MIA_Main.cpp              ← FICHIER À COMPILER
├── study_mapping.json        ← 🆕 CONFIGURATION STUDY IDs
│
├── MIA_Config.h              (1063 lignes)
├── MIA_Globals.h             (33 lignes)
├── MIA_StateManager.h        (283 lignes)
├── MIA_StudyConfig.h         (277 lignes)
├── MIA_ExtensionTracker.h    (280 lignes)
├── MIA_SLTP.h                (138 lignes)
├── MIA_SLTP_Calc.h           (807 lignes)
├── MIA_Utils.h               (276 lignes)
├── MIA_DataReader.h          (1824 lignes)
├── MIA_DataDumper.h          (498 lignes)
├── MIA_Indicators.h          (649 lignes)
├── MIA_Interfaces.h          (288 lignes)
├── MIA_Layers.h              (1909 lignes)
├── MIA_Execution.h           (1070 lignes)
├── MIA_Logging.h             (1953 lignes)
├── MIA_Tests.h               (494 lignes)
├── MIA_MockImpl.h            (553 lignes)
└── MIA_SierraImpl.h          (517 lignes)
```

---

## 🔧 ÉTAPES DE COMPILATION

### 1️⃣ Ouvrir Sierra Chart
Menu: **Analysis → Build Custom Studies DLL**

### 2️⃣ Configurer

**Source File Path**:
```
D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\MIA_Main.cpp
```

### 3️⃣ Compiler
1. Cliquer **"Build"**
2. Attendre 30-60 secondes
3. Vérifier: **"Build successful"**

### 4️⃣ Recharger
Menu: **Analysis → Reload and Recalculate All**

---

## 🎯 CONFIGURATION DE L'ÉTUDE

### Ajouter l'étude
1. **Analysis → Studies → Add Custom Study**
2. Chercher: **"MIA AutoTrader Bataille Navale v1"**

### Inputs par défaut

| # | Input | Valeur |
|---|-------|--------|
| 0 | Bot Enabled | Oui |
| 1 | Trade ES | Oui |
| 2 | Trade NQ | Oui |
| 5 | ES Footprint Chart | **1** |
| 6 | ES Barres Chart | **25** |
| 7 | NQ Footprint Chart | **2** |
| 8 | NQ Barres Chart | **23** |
| 9 | ES Main Chart | **25** |
| 10 | NQ Main Chart | **23** |
| 11 | VIX Chart | **15** |
| 12 | ES Daily Chart | **16** |
| 13 | NQ Daily Chart | **17** |
| 14 | Mode | **1** (TEST) |
| 15 | Trade Rectangles | Oui |
| 16 | Data Dump | Oui |
| 17 | ES Volume Profile | **26** |
| 18 | NQ Volume Profile | **27** |
| 19 | ES Swing Structure | **28** |
| 20 | NQ Swing Structure | **29** |
| 21 | ES Composite Profile | **31** |
| 22 | NQ Composite Profile | **30** |

---

## ⚠️ ERREURS COURANTES

### ❌ "Cannot open include file: MIA_Config.h"
**Solution**: Vérifier que TOUS les `.h` sont dans `MIA_REFACTORED\`

### ❌ "multiple definition of 'g_es_state'"
**Solution**: Ajouter `inline` devant les variables globales:
```cpp
inline BotState g_es_state;  // ✅ CORRECT
```

### ❌ "multiple definition of 'CollectBN_Data'"
**Solution**: Ajouter `inline` devant les fonctions:
```cpp
inline void CollectBN_Data(...) { }  // ✅ CORRECT
```

### ❌ Dashboard affiche "MQ=NON, RECT=NON"
**Cause**: `study_mapping.json` manquant ou Study IDs incorrects

**Solution**:
1. Vérifier que `study_mapping.json` est dans `MIA_REFACTORED\`
2. Chemin dans `MIA_StudyConfig.h`:
```cpp
LoadFromFile("D:\\TRADING_SIERRA_CHART_AUTO\\CPP\\MIA_REFACTORED\\study_mapping.json");
```

---

## ✅ VALIDATION

### Dashboard correct
```
[MIA BOT] 🚀 RUNNING [TEST MODE]
Session: London | VIX: XX.XX
ES: SCANNING | T:0 W:0 L:0 | $0
-> L1: MQ=OUI, RECT=OUI (ColorUp=X ColorDn=X)
```

### Logs
```
D:\LOGS\MIA\mia_autotrader_YYYYMMDD.log
```

---

## 📊 STUDY IDs À VÉRIFIER

### Chart 1 (ES Footprint)
| Étude | ID |
|-------|----|
| EDGE_BUY | 32 |
| EDGE_SELL | 35 |
| COLOR_UP | 56 |
| COLOR_DOWN | 57 |
| FPBS | 31 |

### Chart 2 (NQ Footprint)
| Étude | ID |
|-------|----|
| EDGE_BUY | 55 |
| EDGE_SELL | 56 |
| COLOR_UP | 53 |
| COLOR_DOWN | 54 |
| FPBS | 33 |

### Chart 25 (ES Barres)
| Étude | ID |
|-------|----|
| MQ_GAMMA | 2 |
| MQ_BLIND | 22 |
| LONG_UP_BAR | 18 |

### Chart 23 (NQ Barres)
| Étude | ID |
|-------|----|
| MQ_GAMMA | 25 |
| MQ_BLIND | 26 |

---

## 📞 CHECKLIST FINALE

- [ ] Tous les fichiers `.h` présents
- [ ] `study_mapping.json` présent
- [ ] Chemin JSON correct dans `MIA_StudyConfig.h`
- [ ] Compilation réussie (0 erreur)
- [ ] Dashboard affiche `MQ=OUI, RECT=OUI`
- [ ] Test en MODE_TEST validé
- [ ] Prêt pour PRODUCTION (Input 14 = 0)

---

*Guide mis à jour le 2026-02-06*
