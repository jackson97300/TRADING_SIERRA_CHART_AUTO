# RAPPORT DIAGNOSTIC - VWAP SLOPE = 0

**Date:** 27/01/2026 02:48  
**Problème:** VWAP slope retourne 0.0000 → bloque tous les trades

---

## 📊 CHARTS ANALYSÉS

| Chart | Type | Role | VWAP Study | Données? |
|-------|------|------|------------|----------|
| 1 | ES Footprint | Bataille Navale | ? | ❌ AUCUNE |
| 2 | NQ Footprint | Bataille Navale | Study 57 / 13 | ⚠️ Footprint uniquement |
| 23 | NQ Barres 1min | VWAP Slope | Study 1 | ❌ VIDE |
| 25 | ES Barres 1min | VWAP Slope | Study 1 | ❌ VIDE |

---

## 🐛 PROBLÈME IDENTIFIÉ

Le code C++ utilise:
```cpp
// Ligne 2549-2550
g_market_live.vwap_slope_es = CalculateVWAPSlope(sc, es_barres_chart, 1, 20);
g_market_live.vwap_slope_nq = CalculateVWAPSlope(sc, nq_barres_chart, 1, 20);
```

**Study ID = 1** existe sur charts 23 et 25, MAIS:
- `GetStudyArrayFromChartUsingID(chart, 1, 0, vwap_array)` retourne un array VIDE
- `vwap_array.GetArraySize() = 0` → fonction retourne 0

---

## 🔍 SCANS DÉTAILLÉS

### Chart 23 (NQ Barres):
- Study Inspector: 43 studies détectés
- **Study 1 = "VWAP"** (sg0="V", sg1="+1", sg2="-1")
- TEST Scan All: **1 seule valeur** trouvée (Study 3, pas VWAP)

### Chart 25 (ES Barres):
- Study Inspector: 44 studies détectés
- **Study 1 = "VWAP"** (sg0="V", sg1="+1", sg2="-1")
- TEST Scan All: **1 seule valeur** trouvée (Study 3, pas VWAP)

### Chart 2 (NQ Footprint):
- **Study 57 = "VWAP"**
- **Study 13 = "VWAP"** (sg0="VWAP", sg1="SD+1")
- TEST Scan All: **Study 58** (NEWS 07.15) retourne des données, pas les VWAP

---

## 💡 SOLUTIONS POSSIBLES

### Option 1: DÉSACTIVER le FLAT VETO (TEMPORAIRE)
Commenter les lignes 6243-6262 dans `MIA_AutoTrader_BN_v1.cpp`:
```cpp
// float vwap_slope_es = g_market_live.vwap_slope_es;
// bool is_flat_es = (fabs(vwap_slope_es) < 0.01f);
// 
// if (is_flat_es) {
//     ... FLAT VETO CODE ...
// }
```

### Option 2: UTILISER le VWAP de MenthorQ (RECOMMANDÉ)
Le VWAP existe dans `mq_es.vwap` et `mq_nq.vwap` (déjà collecté).

Modifier `CalculateVWAPSlope`:
```cpp
// Calculer slope depuis prix historiques vs VWAP actuel
// Au lieu de chercher study VWAP sur chart barres
```

### Option 3: AJOUTER un INPUT pour VWAP Study ID
Permettre à l'utilisateur de spécifier le bon Study ID:
```cpp
Input_ES_VWAP_Study_ID.SetInt(1);  // Valeur par défaut, ajustable
```

### Option 4: UTILISER le chart FOOTPRINT au lieu des BARRES
Changer les inputs:
```cpp
Input_ES_Barres_Chart = 1 (Footprint au lieu de 25)
Input_NQ_Barres_Chart = 2 (Footprint au lieu de 23)
```

---

## ⚡ RECOMMANDATION IMMÉDIATE

**Désactiver le FLAT VETO** pour ne pas bloquer les trades pendant qu'on corrige le calcul VWAP slope.

Le marché bouge clairement (visible sur les charts) mais le filtre bloque à cause d'un problème technique, pas d'un vrai marché plat.

---

## 📝 DIAGNOSTIC LOG AJOUTÉ

J'ai modifié `CalculateVWAPSlope()` pour écrire des diagnostics dans:
- `D:\TRADING_SIERRA_CHART_AUTO\debug_vwap_slope.txt`
- `D:\MIA_IA_system\debug_vwap_slope.txt`

Format:
```
HH:MM:SS|SYMBOL|Chart:X|StudyID:Y|ArraySize:Z|VWAP:price|Slope:value
```

Cela permettra de confirmer que l'array est vide.
