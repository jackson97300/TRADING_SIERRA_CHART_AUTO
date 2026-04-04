# MIA PIPELINE PYTHON — README

**Date** : 2026-03-07
**Emplacement** : `D:\TRADING_SIERRA_CHART_AUTO\CORE\`

---

## QU'EST-CE QUE C'EST

Pipeline Python pour le trading algorithmique NQ/ES futures. Transforme les données brutes Sierra Chart (JSONL 214 colonnes, barres 1-min) en signaux de trading exploitables.

Deux bots coexistent :
- **Bot C++** (MIA_Main.cpp) : exécution temps réel, tick-by-tick, layers L1→L4 avec order flow live. Dans `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\`.
- **Bot Python** (ce pipeline) : expérimentation, backtesting, scoring contextuel sur barres 1-min. Plus lent mais plus flexible.

Les deux partagent les mêmes données DMP (C++ collecte, Python analyse).

---

## LES 6 FICHIERS

```
D:\TRADING_SIERRA_CHART_AUTO\CORE\
│
├── dmp_reader.py              215 lignes  Lecture JSONL → DataFrame
├── rolling_features.py        424 lignes  26 features ctx_* (VERROUILLÉ)
├── intermarket_features.py    369 lignes  10 features im_* (VERROUILLÉ)
├── game_changers.py           945 lignes  Market Profile parité C++ (105/105 tests)
├── mia_entry.py               432 lignes  Couche 3 : scoring + zones d'entrée
├── mia_bench.py               912 lignes  Benchmark automatique (10 tests)
│
├── 20260305_NQ.jsonl          ┐
├── 20260305_ES.jsonl          │  Données (drop les nouveaux ici)
├── 20260306_NQ.jsonl          │
├── 20260306_ES.jsonl          ┘
│
└── MIA_BENCH_REPORT.txt       Généré automatiquement par mia_bench.py
```

**Dépendances** : `pandas`, `numpy` uniquement. Pas de sklearn, pas de tensorflow.

---

## LE PIPELINE (COMMENT ÇA S'ENCHAÎNE)

```
JSONL DMP (214 cols, 1-min bars, produit par DMP C++ Sierra Chart)
    │
    ▼
dmp_reader.py                → Charge, filtre (US/RTH), ajoute datetime
    │  216 colonnes
    ▼
rolling_features.py          → +26 features ctx_* (dynamique intra-bar)
    │  242 colonnes
    ▼
intermarket_features.py      → +10 features im_* (cross NQ×ES)
    │  252 colonnes
    ▼
mia_entry.py                 → Score contextuel (7 CORE) + zones d'entrée
    │  Signaux LONG/SHORT/NEUTRE
    ▼
mia_bench.py                 → Tests automatiques + rapport
```

---

## CE QUI EST VERROUILLÉ (NE PAS TOUCHER)

### rolling_features.py — 26 features ctx_*

Feature set figé. Ajouté la dernière feature (`ctx_mq_put_call_ratio`) après audit de couverture complet (214 colonnes DMP scannées, 9 candidats testés sur 4 datasets). Aucun autre domaine ne justifie un ajout.

Les 26 features par catégorie :
- **CRITICAL (5)** : price_delta_div_3, absorption_score_5, vol_sell_buy_ratio_5, vwap_slope_accel, cvd_recovery_rate
- **HIGH (8)** : price_slope_5, delta_slope_5, delta_sum_3, vol_z_5, diag_imbalance_mean_5, finish_strength_mean_5, va_position_velocity, side_flip_count_10
- **MEDIUM (4)** : delta_sum_10, dist_vwap_velocity, range_vs_atr_10, ib_position_velocity
- **AUDIT FIX (3)** : instant_absorption, absorption_streak_5, climax_signal
- **TIER 1 (3)** : vol_slope_5, delta_exhaustion, large_trader_slope_5
- **DYNAMIC (2)** : trend_day_score (remplace trend_day_probability C++ mort), day_type_intensity (remplace day_type enum)
- **MENTHORQ (1)** : mq_put_call_ratio (seul trou comblé après audit)

### intermarket_features.py — 10 features im_*

- **CRITICAL (3)** : cross_delta_agreement_5, cross_delta_weighted_5, smt_divergence
- **HIGH (4)** : delta_day_divergence, price_ratio_slope_10, volume_lead, cross_open_signal
- **MEDIUM (3)** : rolling_correlation_10, ltr_slope_diff, open_type_agreement

### game_changers.py — Parité C++ 105/105

Réplique exacte de DMP_OpenType.h et DMP_ProfileShape.h. Classifieurs : open_type (12 valeurs), open_zone (7), day_type (5), profile_shape (4), Rule 80% (machine 4 états), bias_boost(), direction(), confidence().

**NE PAS modifier ces 3 fichiers.** Le feature set est le résultat d'un audit exhaustif (252 colonnes → 15 signaux → 10 propres → 7 noyau dur). Chaque feature a été testée sur 4 datasets (NQ+ES × 2 jours), vérifiée pour la redondance (corrélation croisée), les proxy-prix, la stabilité cross-asset et la stabilité inter-jour.

---

## LE NOYAU DUR — 7 FEATURES QUI COMPTENT

Sur 252 colonnes, 7 features captent **95% du signal prédictif**. Elles sont dans `mia_entry.py` sous `CORE_FEATURES` :

| # | Feature | Poids | Domaine | Ce qu'elle mesure |
|---|---------|-------|---------|-------------------|
| 1 | `profile_skew` | -0.200 | PROFIL | Asymétrie du profil volume (structure) |
| 2 | `single_print_count` | +0.205 | PROFIL | Nb de LVN = zones de faible résistance |
| 3 | `im_cross_delta_weighted_5` | -0.170 | INTERMAR | Consensus delta NQ×ES = signal contrarian |
| 4 | `ctx_mq_put_call_ratio` | -0.136 | GAMMA | Ratio dist PUT/CALL = gamma positioning |
| 5 | `dist_gex_nearest_up` | +0.159 | GAMMA | Place avant le mur GEX haut |
| 6 | `dist_ovn_high` | -0.125 | STRUCTURE | Distance au high overnight |
| 7 | `ctx_cvd_recovery_rate` | +0.072 | MOMENTUM | CVD qui reprend → prix suit |

**5 domaines indépendants**, zéro redondance.

**Pondération contextuelle** (les poids changent selon le contexte) :
- **PROFIL** (features 1-2) : × 2.0 quand prix `inside_prev_va`, × 0.5 dehors. Raison : `profile_skew` est 5× plus prédictif dans la VA veille.
- **INTERMAR** (feature 3) : × 1.5 en session US, × 0.3 en Asia/London. Raison : volume cross-asset insuffisant hors US.
- **GAMMA, STRUCTURE, MOMENTUM** : poids constant (pas assez de données pour prouver un boost contextuel).

---

## mia_entry.py — COMMENT IL DÉCIDE

4 couches de décision :

**Couche 1 — Filtre** : peut-on trader ? (session, IB formé, pas de macro event)

**Couche 2 — Biais** : quelle direction ? Score contextuel des 7 CORE_FEATURES pondéré par domaine. Score > +0.08 = LONG, < -0.08 = SHORT, entre = NEUTRE.

**Couche 3 — Zone** : où entrer ? Scanne 20 niveaux DMP (HVL, GEX, PREV VA, CUR VA, IB, VWAP...) classés par importance (Score 3/2/1 — parité C++ MIA_Layers.h). Trade seulement quand le biais ET un niveau sont alignés.

**Couche 4 — SL/TP** : quand sortir ? (à construire)

**Résultats mesurés** (2 jours, 636 barres) :
- LONG sur niveaux : **67% WR**, +8.2 pts/trade
- SHORT (score fort) : **62% WR**, -10.0 pts/trade le 05/03

---

## mia_bench.py — L'OUTIL DE TEST

**Usage** : `python mia_bench.py` (depuis le dossier CORE)

Détecte automatiquement tous les `YYYYMMDD_SYM.jsonl`, construit le pipeline complet, produit un rapport avec 10 tests :

| Test | Ce qu'il fait |
|------|---------------|
| 1. Fonctionnel | Parité C++ 105/105, direction/confidence/profile_shape vs JSONL, NaN, sync |
| 2. Inventaire | Barres, sessions, prix, open_type par fichier |
| 3. Ranking bootstrap | CI 95% sur 2000 tirages + stabilité jour/jour → BÉTON/PROBABLE/FRAGILE |
| 4. Cross-asset | Même feature NQ vs ES → stable ou flip |
| 5. Par régime | Corrélation par session (US, Asia, London) |
| 6. Seuils | Sensibilité des seuils hardcodés |
| 7. Game changers | Open type, day type, bias_boost par session |
| 8. Verdict | Résumé BÉTON/PROBABLE/FRAGILE |
| 9. Signal vs Bruit | **Tri automatique 252 colonnes** → SIGNAL/MAYBE/BRUIT |
| 10. Noyau dur | **Backtest des 7 CORE** par jour, WR SHORT/LONG, comparaison 7 vs 41 |

Le rapport est sauvegardé dans `MIA_BENCH_REPORT.txt`.

---

## WORKFLOW QUOTIDIEN

```
1. Le DMP C++ produit les JSONL de la session (automatique via Sierra Chart)
2. Copier les fichiers dans D:\TRADING_SIERRA_CHART_AUTO\CORE\
   Format: 20260307_NQ.jsonl, 20260307_ES.jsonl
3. Lancer: python mia_bench.py
4. Lire le rapport MIA_BENCH_REPORT.txt
5. Observer: les SIGNAL montent, les BRUIT tombent, les MAYBE se décident
```

**Pas besoin de toucher le code.** Le tri se fait tout seul avec plus de données.

---

## ÉTAT DES DONNÉES (au 07/03/2026)

- **2 jours** : 20260305 (US), 20260306 (Asia+London)
- **636 barres NQ**, 1349 barres totales (NQ+ES)
- **4 BÉTON**, 4 PROBABLE, 31 FRAGILE (sur les 39 features ctx+im)
- **14 SIGNAL**, 26 MAYBE, 51 BRUIT (sur les 238 colonnes numériques)

Le minimum recommandé pour des résultats fiables est **20 jours (~6000 barres)**. À ce stade :
- Les MAYBE se trient en SIGNAL ou BRUIT
- Les features conditionnelles au régime sont séparables
- Les seuils du régime detector peuvent être calibrés
- Le WR des signaux est statistiquement significatif

---

## RÉSULTATS CLÉS DÉCOUVERTS

### 1. profile_skew est le signal #1

Négatif sur les 2 jours, les 3 régimes (US trend, Asia bull, London bear), les 2 symboles. Indépendant du prix (r_prix = +0.36). C'est une propriété **structurelle** du profil volume.

### 2. profile_skew est 5× plus prédictif dans la VA veille

| | Inside prev VA | Outside prev VA |
|---|---|---|
| r(3) 05/03 | **-0.251** | -0.048 |
| r(3) 06/03 | **-0.390** | -0.086 |

→ Raison de la pondération contextuelle PROFIL dans `mia_entry.py`.

### 3. ES est le signal avancé pour NQ

Le 05/03, ES open_type = OAOR_DOWN (bearish, conf 0.65). NQ = OAIR (neutre). Le marché a baissé. `im_cross_open_signal` capte cette info.

### 4. Le consensus cross-delta est CONTRARIAN

`im_cross_delta_weighted_5` négatif = quand NQ et ES poussent ensemble fort, c'est l'**exhaustion**, pas la continuation. Le prix reverse ensuite. r = -0.170.

### 5. Les features IM perdent leur pouvoir en Asia/London

`im_cross_delta_agreement_5` : r = +0.271 en US, r = -0.001 le 06/03. Volume cross-asset insuffisant hors RTH US.

### 6. Les niveaux ne prédisent pas la direction, ils créent des zones

dist_prev_vpoc, prev_vah, MQ_HVL comme S/R → instable. MAIS `inside_prev_va` comme **filtre** sur les features → stable et puissant.

---

## BUGS C++ CONNUS (BLOQUENT DES FEATURES)

| Bug | Impact | Fichier C++ |
|-----|--------|-------------|
| BN Color/Absorb/Pressure = 0 | 11/13 colonnes BN mortes | DMP_Reader.h: lit subgraph 0 au lieu de 2 |
| Retest high/low = 0 | 4/4 colonnes retest mortes | DMP_Main.cpp: pas implémenté |
| finish_delta_pct > 1.0 | Valeurs invalides | CalcOrderFlow(): manque clamp(0,1) |

Ces bugs empêchent d'exploiter les données BN et Retest dans le pipeline Python. Les fixer dans le C++ débloquera potentiellement de nouvelles features SIGNAL.

---

## CE QUI RESTE À CONSTRUIRE

### Priorité 1 — Accumuler des données
Drop les JSONL chaque jour, lance `mia_bench.py`. Le système se calibre tout seul.

### Priorité 2 — Couche 4 : SL/TP
Module de money management dans `mia_entry.py`. SL/TP basé sur ATR, trailing, exit si score flippe.

### Priorité 3 — Régime detector (mia_context.py)
Quand on aura 20 jours, séparer les features par régime (TREND/ROTATION). Certaines features qui flippent entre jours (ctx_vwap_slope_accel: +0.12 en US trend, -0.26 en London bear) deviendront exploitables avec le bon filtre de régime. Utiliser VIX + ATR + IB range pour classifier.

### Priorité 4 — Macro calendar
Filtre binaire CPI/FOMC/NFP → ne pas trader ±5 min. Fichier statique, pas un module ML.

### Priorité 5 — Fixer les bugs C++ DMP
BN subgraph (4 lignes), finish_delta_pct clamp, retest implémentation.

---

## PRINCIPES DE DÉVELOPPEMENT

1. **Data-first** : collecter et tester avant d'intégrer. Aucune feature ne rentre sans preuve statistique (CI 95% + stable jour/jour).
2. **Pas d'optimisation de seuils sur < 20 jours**. Le risque d'overfit est trop grand.
3. **NE PAS simplifier le code sans demander**. Les features "fragiles" ne sont pas mortes, elles sont non-prouvées.
4. **Les features verrouillées (rolling + intermarket) ne changent pas**. Le scoring (mia_entry.py) et le bench (mia_bench.py) évoluent.
5. **7 features noyau dur captent 95% du signal**. Les 33 autres sont du bruit qui dilue. Le scoring utilise les 7, pas les 41.
6. **Tout test en MODE_TEST avant production**.
7. **Répondre toujours en français**.
8. **Communication directe et technique** — code-level, pas high-level.

---

## USAGE RAPIDE (COPIER-COLLER)

```python
from dmp_reader import DmpReader
from rolling_features import RollingFeatures
from intermarket_features import IntermarketFeatures
from mia_entry import EntryEngine

reader = DmpReader(".")
rf = RollingFeatures()
im = IntermarketFeatures()
entry = EntryEngine()

# Pipeline complet
nq = rf.compute(reader.load_file("20260305_NQ.jsonl"))
es = rf.compute(reader.load_file("20260305_ES.jsonl"))
nq_full = im.compute(nq, es, target="NQ")

# Signaux d'entrée
nq_signals = entry.compute(nq_full)
entry.summary(nq_signals)

# Benchmark automatique (depuis le terminal)
# python mia_bench.py
```
