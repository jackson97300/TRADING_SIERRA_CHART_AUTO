# MIA V2 — Improvements Tracker

**Source of truth** pour décider quelle amélioration vaut le temps et laquelle est du nice-to-have.
Chaque chantier est **scoré** avant d'être lancé. Score < 50/100 = skip sans regret.

Dernière mise à jour : **2026-04-12**

---

## Framework d'évaluation (rappel)

| Critère | Poids | Question à poser |
|---------|-------|------------------|
| **1. Impact edge mesurable** | **40%** | Est-ce que ça change Sharpe / PF / EV sur le backtest ? |
| **2. Risque technique/ML éliminé** | **25%** | Est-ce que ça évite une catastrophe documentée ? |
| **3. Validation académique reconnue** | **15%** | Un livre/paper sérieux dit que c'est critique ? |
| **4. Effort / complexité** | **10%** | Combien d'heures pour le faire bien ? (<4h = max, >1 semaine = min) |
| **5. Applicabilité immédiate** | **10%** | Je peux le tester sur mes données **cette semaine** ? |

**Notation** : chaque critère /5 → somme pondérée → **score /100**.

**Décision** :
- **≥ 70** → 🔥 PERTINENT, fais-le
- **50-69** → ⚠️ À valider empiriquement avec preuve de concept courte avant d'investir
- **< 50** → ❌ NICE-TO-HAVE, skip

---

## 📊 Statut global (vue d'ensemble)

| # | Chantier | Livre source | Score | Statut | Effort | Résultat empirique |
|---|----------|--------------|-------|--------|--------|---------------------|
| 1 | Sample Weight Uniqueness | López AFML ch.4 | **95** | ✅ DONE 12/04 | 3h | *à mesurer quand 15+ j data* |
| 2 | Meta-labeling skeleton | López AFML ch.3 | **78** | ✅ SKELETON 12/04 | 4h | *à mesurer après intégration* |
| 3 | Davey kill rule | Davey 2014 | **72** | ✅ DONE 12/04 | 1h | *actif après 1er backtest réel* |
| 4 | Integration meta-labeling train+bot | López AFML ch.3 | **88** | 🔜 NEXT SESSION | 5-8h | - |
| 5 | Monte Carlo Permutation + Deflated Sharpe | Aronson + López ch.14 | **85** | 📋 À FAIRE | 1-2j | - |
| 6 | Slippage distribution empirique | Davey 2014 | **80** | 📋 À FAIRE | 3-5j | - |
| 7 | Walk-Forward Efficiency (WFE) | Pardo 2008 | **68** | ⚠️ VALIDER | 2h | - |
| 8 | Clustered Feature Importance (CFI) | López MLAM ch.6 | **65** | ⚠️ VALIDER | 1-2j | - |
| 9 | Denoising covariance Marcenko-Pastur | López MLAM ch.2 | **58** | ⚠️ VALIDER | 2-3j | - |
| 10 | VAR trades+quotes | Hasbrouck ch.9 | **52** | ⚠️ VALIDER | 2-3h | - |
| 11 | Portfolio multi-stratégies (V3) | Davey 2014 | **NA** | 🕐 V3 (6+ mois) | semaines | - |
| 12 | Lee-Ready trade sign | Hasbrouck ch.5 | **32** | ❌ SKIP | 30min | Inapplicable barres 1min |
| 13 | Fractional differentiation | López AFML ch.5 | **45** | ❌ SKIP | 1j | Controverse empirique |
| 14 | LSTM / GRU / Transformers | Jansen ch.16-17 | **25** | ❌ SKIP | semaines | Pas assez de data |
| 15 | GANs data augmentation | Jansen ch.21 | **15** | ❌ SKIP | 1-2w | Gimmick non production-ready |
| 16 | Reinforcement Learning | Jansen ch.22 | **10** | ❌ SKIP | semaines | Sim-to-real gap massif |
| 17 | Alternative data (NLP, satellite) | Jansen ch.2-3 | **10** | ❌ SKIP | mois | Inadapté intraday futures |
| 18 | Johansen cointegration ES/NQ | Chan ch.3 | **20** | ❌ SKIP | 1-2w | Pas vraie cointegration |
| 19 | CPCV (Combinatorial Purged CV) | López AFML ch.12 | **40** | ❌ SKIP | 2-3j | Purged K-Fold suffit |
| 20 | Walk-Forward Cluster Analysis | Pardo 2008 | **35** | ❌ SKIP | 2-3j | Compute prohibitif |
| 21 | Previous open cash feature explicite | Intuition trader | **39** | ❌ SKIP (testé 12/04) | 3h | \|rho\|=0.0079 p=0.57 sur 13j ES = bruit |

**Légende statut** :
- ✅ **DONE** : implémenté et commité
- 🔜 **NEXT SESSION** : prio absolue de la prochaine session
- 📋 **À FAIRE** : validé comme pertinent, en queue
- ⚠️ **VALIDER** : score limite, nécessite PoC court avant d'investir sérieusement
- 🕐 **V3** : pas pour maintenant, horizon lointain
- ❌ **SKIP** : refusé, ne pas revisiter sans raison forte

---

## 🔥 Fiches détaillées — Chantiers actifs

### ✅ #1 — Sample Weight Uniqueness (López AFML ch.4)

**Score : 95/100** — **CRITIQUE**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 5/5 | 40 |
| Risque éliminé | 5/5 | 25 |
| Validation | 5/5 | 15 |
| Effort | 4/5 | 8 |
| Applicabilité | 5/5 | 10 |
| **Total** | | **98** |

**Pourquoi critique** : Sharpe IS gonflé de +0.3 à +0.6 si les labels concurrents ne sont pas pondérés (MQL5 2024 benchmarks). Sans ce fix, tu déploies un système 2x moins bon que tu crois l'avoir entraîné.

**Statut** : commit `4f0a897` 12/04. Mean `sample_weight` = 0.49 ES/NQ, 94% chevauchement.

**Résultat empirique à mesurer** : comparer Sharpe IS avec/sans `sample_weight=1.0` quand 15+ jours de data dispos. Attendu : baisse du Sharpe IS de ~30-50%, mais ce Sharpe sera le VRAI Sharpe exploitable en live.

---

### ✅ #2 — Meta-labeling skeleton (López AFML ch.3)

**Score : 78/100** — **PERTINENT**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 4/5 | 32 |
| Risque éliminé | 4/5 | 20 |
| Validation | 5/5 | 15 |
| Effort | 3/5 | 6 |
| Applicabilité | 3/5 | 6 |
| **Total** | | **79** |

**Pourquoi pertinent** : Architecture 2-niveaux qui résout le problème V1 (8 gates cascading = overfit chaque gate). Potentiel +0.2 à +0.5 Sharpe si le primary a un edge (Hudson & Thames). C'est l'inverse architectural du problème V1.

**Statut** : `CORE/meta_labeler.py` créé 12/04, validé sur vrai dataset ES. Non intégré dans `train_lightgbm.py` ni `signal_engine.py` → chantier #4.

---

### ✅ #3 — Davey kill rule (Davey 2014)

**Score : 72/100** — **PERTINENT**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 2/5 | 16 |
| Risque éliminé | 4/5 | 20 |
| Validation | 4/5 | 12 |
| Effort | 5/5 | 10 |
| Applicabilité | 3/5 | 6 |
| **Total** | | **64** |

**Note** : je baisse le score à 64 après réévaluation honnête (impact edge direct faible, applicabilité 3/5 car nécessite backtest réel pour fixer `backtest_max_dd_usd`). Reste pertinent mais pas critique.

**Pourquoi pertinent** : défense vitale contre la divergence live vs backtest. Davey (3x WCTC champion) dit que c'est la règle #1 qu'il applique sur tous ses systèmes live.

**Statut** : commit `4f0a897`. Règle active dès que `backtest_max_dd_usd > 0.0` (à remplir après 1er training réel).

---

### 🔜 #4 — Integration meta-labeling dans `train_lightgbm.py` + `signal_engine.py`

**Score : 88/100** — **CRITIQUE PROCHAINE SESSION**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 5/5 | 40 |
| Risque éliminé | 4/5 | 20 |
| Validation | 5/5 | 15 |
| Effort | 3/5 | 6 |
| Applicabilité | 4/5 | 8 |
| **Total** | | **89** |

**Pourquoi critique** : le skeleton sans intégration = zéro valeur. Seule l'intégration complète permet de mesurer l'impact empirique du meta-labeling sur ton Sharpe OOS.

**Plan d'intégration** (voir `project_meta_labeler_skeleton.md` en mémoire) :
1. Après training primary model dans `train_lightgbm.py` : build meta dataset → train meta model par side → export
2. Dans `BOT/signal_engine.py` : charger primary + meta, calculer `p_final = p_primary × p_meta`, sizer avec `Half-Kelly × p_meta`
3. Backtest comparaison : Sharpe avec primary seul vs primary+meta

**Prérequis** : 15+ jours de data disponibles (actuellement 13 jours).

---

### 📋 #5 — Monte Carlo Permutation Test + Deflated Sharpe Ratio

**Score : 85/100** — **CRITIQUE**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 5/5 | 40 (indirect mais critique) |
| Risque éliminé | 5/5 | 25 |
| Validation | 5/5 | 15 |
| Effort | 3/5 | 6 |
| Applicabilité | 3/5 | 6 |
| **Total** | | **92** |

**Pourquoi critique** : aujourd'hui, V2 n'a **AUCUN** test de significativité statistique. Tu fais 100 trials Optuna, tu prends le meilleur, tu supposes qu'il a un edge. **Aronson + López disent que c'est garanti de te planter**.

**Plan** :
- `CORE/mia_validate_mc.py` (nouveau) : Monte Carlo permutation + Stationary Bootstrap
- Integration dans `train_lightgbm.py` après `aggregate_results`
- Deflated Sharpe + PBO via `mlfinlab` ou implémentation directe
- Règle de décision claire : `DSR > 0 AND PBO < 50% AND p_mc < 0.05 AND WFE > 30%` → déployer

**Prérequis** : 15+ jours de data + premier training avec sample_weight actif.

---

### 📋 #6 — Slippage distribution empirique (Davey 2014)

**Score : 80/100** — **BLOQUANT LIVE**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 4/5 | 32 (décale le Sharpe réel) |
| Risque éliminé | 5/5 | 25 |
| Validation | 4/5 | 12 |
| Effort | 2/5 | 4 |
| Applicabilité | 3/5 | 6 |
| **Total** | | **79** |

**Pourquoi pertinent** : V2 utilise un slippage **fixe** (2.3 ticks ES, 5.2 ticks NQ). Davey dit après 20 ans de live : **le slippage est une distribution**. Sans modèle réaliste, les estimations de P&L live sont **fictives**.

**Plan** :
1. Collecter 50+ trades paper/live réels
2. Mesurer écart prix signal vs fill réel (ES et NQ séparément)
3. Fit distribution (lognormale probable) via Kolmogorov-Smirnov
4. Intégrer dans le backtester : tirer slippage aléatoirement au lieu de valeur fixe
5. Recalculer Sharpe/DD avec slippage réaliste — attendre dégradation 10-30%

**Prérequis** : paper trading ou petit size réel (pour collecter les 50+ trades avec slippage mesurable).

---

### ⚠️ #7 — Walk-Forward Efficiency metric (Pardo 2008)

**Score : 68/100** — **À VALIDER**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 2/5 | 16 |
| Risque éliminé | 3/5 | 15 |
| Validation | 4/5 | 12 |
| Effort | 5/5 | 10 |
| Applicabilité | 5/5 | 10 |
| **Total** | | **63** |

**Pourquoi limite** : métrique simple et rapide (2h de code) mais impact edge faible — c'est du diagnostic, pas du gain. Utile pour détecter l'overfit sur les folds existants. **Pas critique mais bon investissement vu l'effort minimal**.

**Plan** : ajouter champ `sharpe_is` à `SimResult`, calculer WFE = Sharpe_OOS / Sharpe_IS, logger warning si WFE < 30% ou > 80%.

---

### ⚠️ #8 — Clustered Feature Importance (López MLAM ch.6)

**Score : 65/100** — **À VALIDER**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 4/5 | 32 |
| Risque éliminé | 3/5 | 15 |
| Validation | 4/5 | 12 |
| Effort | 2/5 | 4 |
| Applicabilité | 2/5 | 4 |
| **Total** | | **67** |

**Pourquoi limite** : gain empirique (López) = +6.6% accuracy / +6.3% AUC sur S&P 500 monthly. **Non répliqué sur futures intraday**. Potentiel intéressant mais pas garanti pour ton cas. Nécessite PoC court avant d'investir 1-2 jours.

**Plan** : implémenter hierarchical clustering simple (scipy), mesurer le gain réel, décider si on continue.

---

### ⚠️ #9 — Denoising covariance Marcenko-Pastur (López MLAM ch.2)

**Score : 58/100** — **À VALIDER**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 3/5 | 24 |
| Risque éliminé | 3/5 | 15 |
| Validation | 4/5 | 12 |
| Effort | 2/5 | 4 |
| Applicabilité | 2/5 | 4 |
| **Total** | | **59** |

**Pourquoi limite** : théoriquement solide, résout le problème documenté de features colinéaires (ask_pct ≈ buy_sell_ratio, etc.), mais introduit un hyperparam (λ threshold) à tuner. **Preuve empirique uniquement sur equity monthly, pas sur futures intraday**.

**Plan** : PoC sur 1 semaine de data ES, comparer performance LightGBM avec/sans denoising. Décider.

---

### ⚠️ #10 — VAR trades+quotes (Hasbrouck ch.9)

**Score : 52/100** — **À VALIDER**

| Critère | Note | Pts |
|---------|------|-----|
| Impact edge | 3/5 | 24 |
| Risque éliminé | 2/5 | 10 |
| Validation | 4/5 | 12 |
| Effort | 4/5 | 8 |
| Applicabilité | 2/5 | 4 |
| **Total** | | **58** |

**Pourquoi limite** : V2 n'a pas de tick data (barres 1min agrégées). VAR de Hasbrouck est conçu pour tick-by-tick. **Dégradation significative** sur barres 1min. Gain incertain.

**Plan** : si on y va, PoC minimum pour tester `statsmodels.tsa.api.VAR` sur `{delta, mid_price, ask_bid_imbalance, absorption}` et voir si les features IRF (impulse response) améliorent le LightGBM.

---

## ❌ Skip list définitive — ne JAMAIS revisiter sans raison forte

| Chantier | Raison |
|----------|--------|
| **Lee-Ready trade sign (barres 1min)** | Lee-Ready est tick-level, gain réel 2-5pp max sur barres agrégées, pas 13pp comme annoncé. Si revisité : au niveau **DMP C++** pour tick data. |
| **LSTM / GRU / CNN 1D / Transformers** | 13 jours de data = overfit garanti. Revisiter à **6+ mois de data live** si LightGBM plafonne. |
| **GANs data augmentation** | Jansen lui-même admet "pas production-ready". Risque de fausses données = fausse confiance. |
| **Reinforcement Learning (SAC, PPO, DQN)** | Sim-to-real gap énorme, reward function = trou noir, non-stationnarité tue la policy. *"DRL trading still unsolved 2026"* — Jansen. |
| **Alternative data (NLP, satellite, earnings calls)** | V2 intraday futures = mismatch total de horizon. Alt data = fréquence journalière/trimestrielle. |
| **Johansen cointegration ES/NQ** | ES (S&P500) et NQ (Nasdaq 100) ne sont PAS vraiment cointégrés — underlyings différents fortement corrélés. Johansen va donner des résultats fragiles. |
| **CPCV (Combinatorial Purged CV)** | 50-100× plus cher en compute que Purged K-Fold. Purged K-Fold + DSR + WFE suffit. |
| **Walk-Forward Cluster Analysis** | Tester 5 configs WFA × 100 trials Optuna × 4 modèles = ~4000 trainings LightGBM. Disproportionné. |
| **HRP / Portfolio construction** | N = 2 instruments. HRP brille à N > 10. Overkill. |
| **Fractional differentiation** | Concept bon mais implémentation controversée, **pas de preuve empirique robuste** sur futures intraday. Revisiter si intuition forte sur un dataset spécifique. |
| **Entropy features (AFML ch.18)** | Bruit dominant sur barres 1min. Aucun papier post-2018 ne valide empiriquement. |
| **Autoencoders feature engineering** | LightGBM + denoising Marcenko-Pastur + CFI fait le job sans ajouter de complexité. |
| **Hasbrouck Information Share cross-exchange** | Concept pour actions multi-venues. V2 = single venue CME Globex. N/A. |

---

## 🔬 Tests empiriques rejetés — Historique

Section dédiée pour garder trace des idées **testées et rejetées** avec données concrètes.
Objectif : si tu as la même idée dans 3 mois, tu retrouves le résultat et tu ne refais pas le test.

### Test #1 — "Previous open cash" comme feature explicite (12/04/2026)

**Hypothèse trader** : le prix d'ouverture RTH cash (SPX/NDX à 9:30 ET) du jour précédent est un niveau de référence classique utilisé par les traders pros (gap analysis, opening range, fair value retest). L'ajouter comme feature devrait améliorer le Sharpe du LightGBM V2.

**Découverte** : la feature **existe déjà** dans le DMP C++ sous le nom `dist_open_cash` (ligne de JSONL : `"dist_open_cash": 63.0`). Plus 11 autres features liées : `dist_open_830`, `open_gap_ticks`, `open_bias_conf`, `open_direction`, `open_type`, `open_position`, `open_zone`, `open_in_prev_va`, `dist_prev_vwap`, `dist_prev_vpoc`, `bool_above_prev_vpoc`.

**Raison de son absence du dataset final** : dropée par le screening Spearman (`|rho| < 0.02` avec les labels Triple Barrier).

**Mesure empirique** (13 jours ES, 5103 labels actifs) :

| Feature | \|rho\| Spearman | p-value | Verdict |
|---------|------|---------|---------|
| open_gap_ticks | 0.0162 | 0.2481 | DROP |
| open_bias_conf | 0.0146 | 0.2972 | DROP |
| open_position | 0.0139 | 0.3196 | DROP |
| open_zone | 0.0088 | 0.5279 | DROP |
| bool_above_prev_vpoc | 0.0084 | 0.5504 | DROP |
| **dist_open_cash** | **0.0079** | **0.5722** | **DROP** |
| dist_prev_vpoc | 0.0067 | 0.6319 | DROP |
| dist_open_830 | 0.0066 | 0.6388 | DROP |
| open_type | 0.0037 | 0.7892 | DROP |
| dist_prev_vwap | 0.0021 | 0.8818 | DROP |
| open_direction | 0.0013 | 0.9243 | DROP |

**Interprétation** : **TOUTES** les features "open/prev/cash" ont `|rho| < 0.02` ET `p-value > 0.05` sur 13 jours. Aucune signification statistique détectée. L'info est **indistinguable du bruit** dans cette configuration.

**Nuances (pour ne pas mentir)** :
1. 13 jours = power statistique faible. L'edge pourrait émerger à 60+ jours de data.
2. Spearman capture la monotonie, pas les relations non-linéaires conditionnelles (ex : `abs(dist_open_cash) < 5 ticks → réaction forte`).
3. Effet peut-être conditionnel (FOMC, CPI, high vol uniquement).
4. Le label Triple Barrier est restrictif. Tester contre d'autres labels (return direction à 5 min, breakout) pourrait donner un signal.

**Conditions de ré-ouverture** :
- Data disponible ≥ 60 jours ET une des 4 nuances ci-dessus testée
- OU hypothèse spécifique de régime avec PoC de 30 minutes max
- Sans ces conditions : **NE PAS revisiter**.

**Score framework initial** : 51/100 (limite)
**Score après test empirique** : 39/100 (SKIP définitif)
**Leçon méta** : intuition trader cohérente ≠ edge ML. Le framework a évité 3h de dev et le risque d'overfit.

---

## 📈 Roadmap ordonnée (après aujourd'hui)

### Semaine 1 (attendre 15+ jours de data)
- Collecte VPS continue (rien à coder)

### Semaine 2 (data prête)
1. **Relance pipeline complet** : labeler → dataset_builder → train_lightgbm avec `sample_weight` actif
2. **Mesurer résultat empirique PRIO 3** : Sharpe IS avec vs sans `sample_weight`
3. **Intégration meta-labeling** (#4) dans train_lightgbm + signal_engine
4. **Backtest comparatif** : primary seul vs primary + meta

### Semaine 3
5. **Monte Carlo Permutation + DSR/PBO** (#5) : ajouter tests de significativité
6. **WFE metric** (#7) : 2h facile, ajouter au rapport training

### Semaine 4
7. **Slippage distribution** (#6) : collecter 50+ trades paper, fit, intégrer

### Après (selon résultats)
- Si `sample_weight` + meta-labeling + validation stats donnent un système profitable → **passage live prudent**
- Si pas profitable → retour à l'analyse, pas d'ajout de complexité (#8-10 uniquement si nécessaire)

---

## 🔄 Protocole de mise à jour

**À chaque fin de session** :
1. Ajouter les chantiers nouvellement identifiés avec leur score
2. Mettre à jour le statut des chantiers en cours
3. Remplir la colonne "Résultat empirique" avec les vraies métriques mesurées
4. Recalibrer les poids du framework si un chantier scoré 80 donne un résultat nul (preuve que le poids impact_edge était trop optimiste)

**Règle d'or** : un chantier qui n'a pas été scoré ici **ne doit pas être démarré**. C'est la barrière contre la dérive "j'ai eu une idée cool".

**Auteur framework** : inspiré des 9 livres analysés (López, Davey, Chan, Harris, Jansen, Aronson, Pardo, Hasbrouck) + philosophie Mark Douglas (edge statistique > trade individuel).
