# 📊 Guide d'Intégration — MIA_CVD_Divergence.h

## 🎯 Objectif

Ajouter le module de détection avancée des divergences CVD **sans modifier** le comportement existant. Le module s'intègre en 4 points dans le code.

## 📁 Fichier à copier

```
MIA_CVD_Divergence.h → D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\MIA_CVD_Divergence.h
```

## 🔧 Modifications requises (4 fichiers)

---

### 1️⃣ MIA_Main.cpp — Ajouter l'include (ligne ~22)

```cpp
// APRÈS cette ligne:
#include "MIA_Layers.h"

// AJOUTER:
#include "MIA_CVD_Divergence.h"     // 🆕 11/02/2026: Détection avancée divergences CVD
```

---

### 2️⃣ MIA_Main.cpp — Appeler UpdateCVD_History + AnalyzeCVD_Divergence

Chercher la section où `CollectBN_Data()` et `CollectVolumeProfile_Data()` sont appelés (vers ligne ~850-900 dans MIA_Main.cpp refactoré).

**APRÈS** les appels `CollectBN_Data()` et **AVANT** les appels aux Layers, ajouter :

```cpp
    // 🆕 11/02/2026: CVD DIVERGENCE AVANCÉE
    // Mettre à jour le rolling buffer CVD (8 barres)
    CVD_AnalysisResult cvd_es, cvd_nq;
    memset(&cvd_es, 0, sizeof(cvd_es));
    memset(&cvd_nq, 0, sizeof(cvd_nq));
    
    // ES: prix OHLC du chart principal + CVD du footprint
    {
        int last_idx = sc.ArraySize - 1;
        float es_high = sc.High[last_idx];
        float es_low = sc.Low[last_idx];
        float es_close = sc.Close[last_idx];
        
        UpdateCVD_History(sc, bn_es, es_high, es_low, es_close, false);
        cvd_es = AnalyzeCVD_Divergence(sc, bn_es, es_close, false);
        
        // Log si signal détecté
        LogCVD_Analysis(sc, cvd_es, "ES");
    }
    
    // NQ: prix depuis le chart NQ référencé
    {
        SCFloatArray nq_high, nq_low, nq_close;
        int nq_chart = Input_NQ_Footprint_Chart.GetInt();
        sc.GetChartBaseData(nq_chart, SC_HIGH, nq_high);
        sc.GetChartBaseData(nq_chart, SC_LOW, nq_low);
        sc.GetChartBaseData(nq_chart, SC_LAST, nq_close);
        
        int nq_last = nq_close.GetArraySize() - 1;
        if (nq_last > 0) {
            UpdateCVD_History(sc, bn_nq, nq_high[nq_last], nq_low[nq_last], nq_close[nq_last], true);
            cvd_nq = AnalyzeCVD_Divergence(sc, bn_nq, nq_close[nq_last], true);
            
            LogCVD_Analysis(sc, cvd_nq, "NQ");
        }
    }
```

> ⚠️ **Note**: Les variables `cvd_es` et `cvd_nq` doivent être accessibles dans la suite du code où les Layers sont appelés. Déclarez-les au même scope que `bn_es`, `bn_nq`.

---

### 3️⃣ MIA_Layers.h — Intégration Layer 2 (VETO amélioré)

Dans `EvaluateLayer2()`, **REMPLACER** le bloc VETO CVD existant (lignes ~1258-1291) :

```cpp
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 CVD DIVERGENCE AVANCÉE - Remplace le VETO simple
    // Module: MIA_CVD_Divergence.h
    // Détecte: Divergences classiques multi-barres (8 bars lookback)
    // ═══════════════════════════════════════════════════════════════════════
    // OPTION A: Utiliser le nouveau module (RECOMMANDÉ)
    // Note: cvd_result doit être passé en paramètre à EvaluateLayer2()
    //       ou accessible via une variable globale/struct
    
    // Pour l'instant, on GARDE l'ancien code comme fallback
    // et on AJOUTE le nouveau par-dessus:
```

**Approche recommandée** — Ajouter un paramètre `cvd_result` à `EvaluateLayer2()`:

**AVANT** (signature actuelle, chercher dans MIA_Layers.h):
```cpp
inline Layer2Result EvaluateLayer2(SCStudyInterfaceRef sc, int direction,
                                    const BN_Data& bn_primary, const BN_Data& bn_secondary,
                                    ...)
```

**APRÈS** (ajouter le paramètre CVD):
```cpp
inline Layer2Result EvaluateLayer2(SCStudyInterfaceRef sc, int direction,
                                    const BN_Data& bn_primary, const BN_Data& bn_secondary,
                                    const CVD_AnalysisResult& cvd_result,  // 🆕 CVD avancé
                                    ...)
```

Puis **REMPLACER** le bloc VETO CVD (lignes ~1258-1291) par:

```cpp
    // ═══════════════════════════════════════════════════════════════════════
    // CVD DIVERGENCE VETO - Version avancée multi-barres
    // ═══════════════════════════════════════════════════════════════════════
    if (CheckCVD_Veto(cvd_result, direction)) {
        snprintf(result.reason, sizeof(result.reason),
                 "🛑 VETO CVD AVANCÉ: %s", cvd_result.veto_reason);
        return result;
    }
    
    // Fallback: Garder le VETO CVD simple si le module avancé n'a pas assez de données
    if (cvd_result.bars_in_buffer < CVD_MIN_BARS) {
        // === ANCIEN CODE CVD (fallback) ===
        if (bn_primary.cvd_divergence) {
            if (direction == 1) {
                snprintf(result.reason, sizeof(result.reason),
                         "🛑 VETO CVD: DIVERGENCE BEARISH! CVD chute (slope=%.0f) - BULL TRAP!",
                         bn_primary.cvd_slope);
                return result;
            } else {
                snprintf(result.reason, sizeof(result.reason),
                         "🛑 VETO CVD: DIVERGENCE BULLISH! CVD monte (slope=%.0f) - BEAR TRAP!",
                         bn_primary.cvd_slope);
                return result;
            }
        }
        
        const float CVD_STRONG_THRESHOLD = 500.0f;
        if (direction == 1 && bn_primary.cvd_slope < -CVD_STRONG_THRESHOLD) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO CVD: Flow VENDEUR fort (slope=%.0f < -500)",
                     bn_primary.cvd_slope);
            return result;
        }
        if (direction == -1 && bn_primary.cvd_slope > CVD_STRONG_THRESHOLD) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO CVD: Flow ACHETEUR fort (slope=%.0f > +500)",
                     bn_primary.cvd_slope);
            return result;
        }
    }
```

---

### 4️⃣ MIA_Layers.h — Intégration Layer 3 (Bonus/Malus amélioré)

Dans `EvaluateLayer3()`, **APRÈS** le bloc A7 CVD existant (ligne ~1626), **AJOUTER**:

```cpp
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 BLOC A7b: CVD DIVERGENCE AVANCÉE (multi-barres)
    // Module: MIA_CVD_Divergence.h
    // Ajoute: Hidden divergences, Absorption, CVD Flip
    // Note: cvd_result doit être passé en paramètre ou accessible
    // ═══════════════════════════════════════════════════════════════════════
    float cvd_advanced_adj = GetCVD_LayerAdjustment(cvd_result, direction);
    if (cvd_advanced_adj != 0.0f) {
        score += cvd_advanced_adj;
        // Log optionnel pour debug
        // sc.AddMessageToLog(cvd_result.signal_description, 0);
    }
```

De même, ajouter `const CVD_AnalysisResult& cvd_result` en paramètre de `EvaluateLayer3()`.

---

## 📊 Résumé des Persistent Variables utilisées

| Index | Type | Usage | Existant? |
|-------|------|-------|-----------|
| Float 100 | PersistentFloat | ES prev_cvd (ancien) | ✅ Existant |
| Float 101 | PersistentFloat | NQ prev_cvd (ancien) | ✅ Existant |
| Int 1 | PersistentInt | g_last_day | ✅ Existant |
| Int 2 | PersistentInt | pnl_baseline | ✅ Existant |
| **Float 200-239** | PersistentFloat | **ES CVD buffer (8×5)** | 🆕 Nouveau |
| **Float 240-279** | PersistentFloat | **NQ CVD buffer (8×5)** | 🆕 Nouveau |
| **Float 280** | PersistentFloat | **ES last bar fingerprint** | 🆕 Nouveau |
| **Float 281** | PersistentFloat | **NQ last bar fingerprint** | 🆕 Nouveau |
| **Int 10** | PersistentInt | **ES buffer write index** | 🆕 Nouveau |
| **Int 11** | PersistentInt | **NQ buffer write index** | 🆕 Nouveau |
| **Int 12** | PersistentInt | **ES bars accumulated** | 🆕 Nouveau |
| **Int 13** | PersistentInt | **NQ bars accumulated** | 🆕 Nouveau |

---

## 🧪 Plan de test

### Phase 1: Compilation
1. Copier `MIA_CVD_Divergence.h` dans le répertoire
2. Ajouter l'include dans `MIA_Main.cpp`
3. Compiler → vérifier 0 erreurs

### Phase 2: Observation (MODE_TEST)
1. Activer les logs CVD (décommenter `LogCVD_Analysis`)
2. Laisser tourner 1 session complète
3. Vérifier que le buffer se remplit correctement (logs "Buffer en remplissage X/4")
4. Vérifier que des divergences sont détectées aux bons moments

### Phase 3: Intégration Layers
1. Modifier les signatures Layer 2 et Layer 3
2. Passer `cvd_es` / `cvd_nq` en paramètres
3. Compiler et tester en MODE_TEST
4. Comparer le nombre de VETO avant/après

### Phase 4: Validation
1. Analyser les logs: les VETO CVD avancés capturent-ils des cas que l'ancien code manquait?
2. Vérifier que les divergences cachées (HIDDEN) boosten les bons trades
3. S'assurer que l'absorption est détectée aux niveaux MenthorQ
4. WinRate cible: amélioration de 2-5% sur les trades filtrés CVD

---

## ⚠️ Points d'attention

1. **Le module ne REMPLACE pas** le code CVD existant — il l'ENRICHIT
2. **L'ancien code reste en fallback** quand le buffer n'a pas assez de barres
3. **Les seuils sont conservateurs** — commencer par observer avant d'ajuster
4. **L'absorption est le signal le plus intéressant** — très efficace combiné avec Layer 1
5. **Le rolling buffer se vide** au redémarrage du study — normal, il se re-remplit en ~8 barres

## 🔧 Bugs corrigés pendant les tests (11/02/2026)

### BUG 1: Conflit classique/cachée (CRITIQUE)
**Problème** : Les divergences classiques (retournement) et cachées (continuation) pouvaient se déclencher simultanément dans des directions opposées, annulant le score.
**Fix** : Exclusion mutuelle — si classique bearish détecté, la cachée bullish est bloquée (et inversement).

### BUG 2: Conflit absorption/hidden
**Problème** : L'absorption (signal court terme sur 3 barres) était parasitée par des hidden divergences (signal structurel sur 8 barres) dans la direction opposée.
**Fix** : L'absorption prime sur la hidden divergence quand elles se contredisent. Le score de la hidden est neutralisé.

### BUG 3: Collision fingerprint
**Problème** : `close*1000 + cvd` créait des collisions (ex: close=6000,cvd=500 vs close=6000.5,cvd=0 = même empreinte). Des barres légitimes étaient ignorées.
**Fix** : Hash multi-valeurs `high*7 + low*13 + close*31 + cvd*0.1` avec tolérance float.

### WARNING: Données plates
Quand OHLC et CVD sont strictement identiques sur plusieurs barres consécutives, seule la première est enregistrée. C'est un comportement attendu (ce sont les mêmes données), pas un bug.
