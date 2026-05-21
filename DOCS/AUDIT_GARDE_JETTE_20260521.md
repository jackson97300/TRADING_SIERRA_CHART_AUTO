# Audit GARDE / JETTE — feuille de route reconstruction MIA

**Date** : 2026-05-21
**Contexte** : après une session de diagnostic intensive (nuit 20-21/05), constat acté
par Jackson : **l'automatisation autonome ne fonctionne pas**. Ce document trie ce qui
est solide (à garder) de ce qui n'a jamais produit d'edge (à jeter), pour repartir
propre. Jackson prend une phase de recul : étude des livres + de ce qui marche
réellement en trading algo, puis reconstruction sur les fondations saines.

---

## 1. LE CONSTAT DE FOND — pourquoi ça a échoué

L'edge de Jackson est **réel** : il est rentable en prop firm. Mais cet edge est
**discrétionnaire** — il vit dans sa sélection en temps réel (« ce double bottom-là
oui, celui-là non »), un jugement System 1 de 10 000 heures.

**Tout ce qui a été testé pour mécaniser cette sélection a échoué** (preuves §3).
Un edge discrétionnaire ne rentre pas dans un bot autonome.

**La contradiction centrale** : l'edge exige la *présence* de Jackson ; son désir
(la liberté, ne plus être collé à l'écran) exige son *absence*. Les deux ne peuvent
pas coexister à 100%. 2,5 ans ont buté sur cette contradiction non vue.

---

## 2. CE QU'ON GARDE — fondations saines

| Bloc | Pourquoi on garde |
|---|---|
| **Flux de données Databento** | Backfill trades réparé (21/05). Source propre, fiable. |
| **DMP Sierra Chart** | Collecte temps réel validée, schema stable. |
| **Moteur `enricher_chain`** | UN moteur de features unique, partagé live + replay. Sain. |
| **Exécution DTC** | Connecteur validé, brackets OCO, anti-orphelin H6. Marche. |
| **Dashboard** | Outil réel — a fait gagner de l'argent en live (+665 $ Topstep). |
| **Infra VPS** | Services nssm, monitoring, logging V2, watchdog. Opérationnel. |
| **INCIDENT_LOG + leçons** | Mémoire des erreurs — évite de les répéter. |

---

## 3. CE QU'ON JETTE / MET DE CÔTÉ — avec les preuves

| Bloc | Verdict | Preuve |
|---|---|---|
| **ML + ~500 features** | JETER | Overfitting industriel (incident #12). Feature selection a pris des features LEAK (incident #13). Data mining trap. |
| **11 setups SetupEngine** | JETER | 8/11 NOGO sur données propres. Seuils calés sur v4, non transposables au live. |
| **Moteur advisory** (`build_conseil_global`) | JETER | PF 0.51 backtest. Aucun edge sur barres 1-min. |
| **Bot 2 V6** | JETER | Miroir exact de Bot 1 — `signal_id` identiques. Décoratif. |
| **Aiguilleur de régime auto** | METTRE DE CÔTÉ | 10 méthodes testées (regime_mode, Dow, vwap_slope, CI/ER, ADX, Hurst...). Aucune fiable en temps réel — le lag tue les transitions. |
| **Pipeline `v4_enriched`** | JETER | Redondant avec `enricher_chain` et il en diverge (delta, vwap_slope). Garder UN seul moteur. |
| **Double bottom mécanique** | METTRE DE CÔTÉ | PF 0.90 brut, 0.97 filtré — pas d'edge même avec contexte. |

---

## 4. DETTE / BUGS PIPELINE À CORRIGER

Identifiés cette nuit — à traiter avant toute reconstruction :

1. **Parquet `v4_enriched` corrompu** — écriture non atomique du pipeline batch.
2. **`replay_enricher_batch` sans fail-loud** — produit un dataset vide en silence
   si les trades manquent (a coûté un replay de 6h45).
3. **Bug OVERWRITE `databento_backfill_batch`** — chaque backfill efface le dossier
   symbole entier → détruit les backfills précédents.
4. **Bug `mia_bench`** — `abs()` sur `None` dans `rolling_features.py:528`.
5. **`regime_engine` cassé** — `regime_mode` retourne TREND en permanence.

---

## 5. PISTES POUR LA RECONSTRUCTION (à valider par l'étude de Jackson)

- **Bot d'exécution / bot-alerte** : le bot scanne et alerte ; Jackson valide en
  30 s depuis son téléphone ; le bot exécute sans émotion. Répond au désir de
  liberté *partielle*. Cohérent avec les faits (détection OK, exécution OK, seule
  la sélection reste humaine).
- **Bot version étude Sierra Chart (ACSIL)** : piste évoquée par Jackson — un bot
  intégré au graphe, dans son environnement de lecture.
- À trancher après la phase d'étude (livres + recherche « ce qui marche en algo »).

---

## 6. PRINCIPE DIRECTEUR POUR RECONSTRUIRE

1. **Simplicité** — un seul pipeline de features, peu de features (10-40, pas 500).
2. **Un seul moteur** — `enricher_chain`, partagé live + backtest.
3. **Validation systématique** — walk-forward + DSR Lopez avant tout déploiement.
   Pas de métrique optimiste (AUC sur segments triés ≠ test séquentiel réel).
4. **Pas de ML** tant que les fondations data ne sont pas saines et profondes.
5. **Tester avant de coder** — un test de 2 min évite 2295 lignes sur du sable.
6. **L'edge de Jackson reste à Jackson** — le bot exécute / assiste / alerte ;
   il ne sélectionne pas à sa place.
