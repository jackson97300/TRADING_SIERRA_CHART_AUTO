# 🏗️ PLAN DE RECONSTRUCTION MIA — ÉTAPE PAR ÉTAPE

**Date** : 01/03/2026
**Principe** : Python d'abord (valider), C++ ensuite (exécuter)

---

## POURQUOI PYTHON D'ABORD

Le C++ Sierra Chart est lent à itérer : modifier → compiler → relancer SC → attendre les données.
Python est instantané : modifier → exécuter → voir les résultats.

**On construit TOUT le cerveau en Python d'abord :**
- Tester les régimes sur données existantes
- Valider les seuils
- Simuler des trades
- Quand c'est prouvé → on porte en C++ (traduction mécanique)

---

## LES 6 ÉTAPES

### ÉTAPE 1 — Le Moteur de Régime (Python)
**Livrable** : `mia_regime.py`
**Durée** : Aujourd'hui

Lit une séquence de snapshots JSON et détermine :
- `open_zone` : où le prix ouvre vs VA veille (7 zones)
- `open_type` : OD/OTD/ORR/OAIR/OAOR/ODF (besoin de 30 min de données)
- `ib_range_atr` : taille IB / ATR
- `regime` : TREND / ROTATION / REVERSAL / BREAKOUT / INCERTAIN

Input  : liste de snapshots JSON (tes données existantes)
Output : régime classifié + confiance + direction

Tester sur : données historiques du bot Python.
Valider : est-ce que les jours qu'on sait être des Trend Days sont bien classés TREND ?

---

### ÉTAPE 2 — Le Moteur de Zones (Python)
**Livrable** : `mia_zones.py`
**Durée** : 1 session

Pour chaque snapshot, identifie les 6-8 niveaux actifs :
- Charge les PV levels (PVPOC, PVAH, PVAL, PVWAP + SD bands)
- Charge IB High/Low
- Charge MenthorQ (GEX, HVL, Gamma)
- Calcule la confluence (MQ level < 5 ticks d'un PV level = bonus)
- Trie par distance, garde les 6-8 plus pertinents avec score

Input  : 1 snapshot + régime du jour
Output : liste de zones triées [{nom, prix, score, direction}]

---

### ÉTAPE 3 — Le Moteur de Trigger (Python)
**Livrable** : `mia_trigger.py`
**Durée** : 1 session

Quand le prix est dans une zone active (< seuil ticks), évalue :
- BN score dans le bon sens (adapté au régime)
- CVD / delta direction
- Absorption visible
- DOM imbalance

Input  : 1 snapshot + zone active + régime
Output : TRIGGER_YES/NO + confiance + raison

---

### ÉTAPE 4 — Le Simulateur de Trades (Python)
**Livrable** : `mia_simulator.py`
**Durée** : 1-2 sessions

Lit une journée complète de snapshots et simule :
1. À 10h30 → calcule le régime
2. Identifie les zones actives
3. Pour chaque snapshot → vérifie si le prix est dans une zone + trigger
4. Si oui → ouvre un trade simulé avec SL/TP selon le régime
5. Suit le trade jusqu'à SL, TP, ou trailing stop
6. Log le résultat

Output : journal de trades simulés avec PnL, win rate, etc.

---

### ÉTAPE 5 — Validation sur Données Historiques
**Livrable** : rapport d'analyse
**Durée** : 1-2 sessions

Faire tourner le simulateur sur TOUTES les données Python collectées.
Répondre aux questions :
- Win rate par régime ?
- Win rate par zone (PVPOC vs PVAL vs IB) ?
- Est-ce que les OD ont vraiment > 80% continuation ?
- Meilleur seuil de trigger par régime ?
- PnL cumulé vs l'ancien système ?

SI les résultats sont bons → passer au C++.
SI non → ajuster les règles et re-tester.

---

### ÉTAPE 6 — Port en C++ (bot Sierra Chart)
**Livrable** : MIA_Main.cpp refactoré avec nouveau paradigme
**Durée** : 2-3 sessions

Traduction mécanique du Python validé :
1. Ajouter structures dans MIA_Config.h (Regime, Zone, etc.)
2. Créer MIA_Regime.h (calcul régime)
3. Modifier MIA_Layers.h (nouvelle logique 3 niveaux)
4. Adapter MIA_SLTP_Calc.h (SL/TP par régime)
5. Test MODE_TEST sur Sierra Chart

---

## CE QU'ON FAIT MAINTENANT — ÉTAPE 1

On commence par `mia_regime.py` car c'est le changement de paradigme fondamental.
C'est lui qui dicte tout le reste.
