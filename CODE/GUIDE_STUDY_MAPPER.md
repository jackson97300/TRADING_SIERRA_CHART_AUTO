# 📋 MIA Study Mapper — Workflow Complet

## 🎯 Objectif

Créer un inventaire exhaustif de TOUTES les études Sierra Chart pour résoudre
définitivement les problèmes de lecture de données du bot.

## 🔴 Bug corrigé

Les versions précédentes (TEST_Scan_All, MIA_Study_Scanner_Complete) avaient
un **bug critique** :

```cpp
// ❌ AVANT (BUG) — studyIdx = position dans la liste (1, 2, 3...)
sc.GetStudyArrayFromChartUsingID(chartNum, studyIdx, sg, arr);

// ✅ APRÈS (CORRIGÉ) — studyID = identifiant unique (ex: 34, 102, 251...)
int studyID = sc.GetStudyIDByIndex(chartNum, studyIdx);  // Obtenir l'ID réel
sc.GetStudyArrayFromChartUsingID(chartNum, studyID, sg, arr);  // Utiliser l'ID
```

L'index ≠ l'ID. L'index c'est la position (1ère étude, 2ème étude...).
L'ID c'est l'identifiant unique que Sierra Chart attribue. Sans l'ID correct,
on lit les données d'études complètement différentes !

## 📝 Étapes

### Étape 1 : Compiler

1. Copier `MIA_Study_Mapper.cpp` dans le dossier des sources Sierra Chart
2. Le compiler via Sierra Chart → Build Custom Study DLL (Analysis → Build...)
3. Vérifier que la DLL est bien compilée

### Étape 2 : Scanner chaque chart

Pour CHAQUE chart de ton workspace Sierra Chart :

1. Clic droit sur le chart → Studies → Add Custom Study
2. Ajouter **"MIA - Study Mapper (Inventaire)"**
3. Laisser les paramètres par défaut (200 études max, 100 subgraphs max)
4. Le scan se fait **automatiquement** en 1-2 secondes
5. Vérifier dans le log Sierra Chart : `✅ MAPPER DONE Chart XX: ...`

Fichier créé : `D:\TRADING_SIERRA_CHART_AUTO\STUDIES\chart_XX.json`

**Charts à scanner (minimum)** :
- Tous les charts ES (barres, footprint, BN, MenthorQ, composite...)
- Tous les charts NQ (idem)
- Chart VIX
- Chart ES daily, NQ daily

**Astuce** : Pour rescanner un chart, mettre "Force Rescan" de 0 → 1.

### Étape 3 : Vérifier les fichiers

```
D:\TRADING_SIERRA_CHART_AUTO\STUDIES\
├── chart_1.json      ← Chart 1
├── chart_2.json      ← Chart 2
├── chart_26.json     ← Chart 26
├── chart_27.json     ← Chart 27
├── ...               ← etc pour chaque chart
```

### Étape 4 : Fusionner en recueil unique

```bash
cd D:\MIA_IA_system
python mia_study_merger.py
```

Résultat :
```
D:\TRADING_SIERRA_CHART_AUTO\STUDIES\
├── chart_1.json
├── chart_2.json
├── ...
├── RECUEIL_COMPLET.json        ← Tout fusionné, sans doublons
├── RECUEIL_COMPLET.txt         ← Version lisible
└── study_mapping_generated.json ← Prêt pour le code C++
```

### Étape 5 : Utiliser le recueil

Le `study_mapping_generated.json` contient pour chaque chart :

```json
{
  "chart_26": {
    "BatailleNavale": {
      "study_id": 34,
      "study_index": 2,
      "subgraphs": {
        "Edge Buy": { "index": 0, "example_value": 5.0 },
        "Edge Sell": { "index": 1, "example_value": 2.0 },
        "Color Up": { "index": 2, "example_value": 12.0 }
      }
    }
  }
}
```

→ On peut maintenant mettre à jour `MIA_StudyConfig.h` et `study_mapping.json`
   avec les **vrais** Study IDs et subgraph indexes pour chaque chart.

## 📊 Fichiers livrés

| Fichier | Rôle |
|---------|------|
| `MIA_Study_Mapper.cpp` | C++ à compiler et ajouter sur chaque chart |
| `mia_study_merger.py` | Python pour fusionner les JSON en recueil unique |
| Ce guide | Workflow étape par étape |

## ⚠️ Notes

- **Ne PAS supprimer** l'étude du chart après le scan — elle ne consomme rien
- Le scan ne tourne qu'**une fois** (sauf si Force Rescan)
- Les fichiers chart_XX.json sont **écrasés** à chaque rescan (pas d'accumulation)
- Le merger détecte les doublons par **nom d'étude** (clé de dédoublication)
