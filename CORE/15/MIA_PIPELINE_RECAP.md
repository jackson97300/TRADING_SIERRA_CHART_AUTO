# MIA Trading System — Documentation Pipeline Python
## Analyse & Features pour NQ/ES Futures

**Date** : 05/03/2026
**Version** : v4
**Données validées** : Session US 05/03/2026 (NQ + ES, 239 barres chacun)

---

## Table des matières

1. Vue d'ensemble du pipeline
2. Les 5 modules
3. Résultats : ranking global des 41 features
4. Résultats : validation croisée NQ/ES
5. Guide d'utilisation rapide
6. Détail par module
7. Leçons du 05/03/2026
8. Problèmes connus et limitations
9. Prochaines étapes

---

## 1. Vue d'ensemble du pipeline

Le pipeline MIA Python transforme les données brutes du DMP C++ (Sierra Chart) en features exploitables pour le trading algorithmique NQ/ES futures.

```
Sierra Chart (1-min bars)
       │
       ▼
DMP C++ (DMP_Main.cpp)
       │  Produit: JSONL 214 colonnes par barre
       │  Inclut: prix, delta, volume, VWAP, GEX, profil, game changers
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  PIPELINE PYTHON (3 couches)                            │
│                                                         │
│  1. dmp_reader.py        → Charge le JSONL (216 cols)   │
│  2. rolling_features.py  → +25 features ctx_*           │
│  3. intermarket_features.py → +10 features im_*         │
│                                                         │
│  + game_changers.py      → Classifieurs Market Profile  │
│    (déjà dans le JSONL, utilisable en standalone)       │
│                                                         │
│  TOTAL: 251 colonnes par barre                          │
└─────────────────────────────────────────────────────────┘
       │
       ▼
  Moteur de décision ML (à venir)
```

**Performance** : 89ms pour 239+239 barres (0.37ms/barre). Budget live 1-min largement respecté.

---

## 2. Les 5 modules

### 2.1 `dmp_reader.py` — Lecture des données

**Rôle** : Charger les fichiers JSONL produits par le DMP C++ et retourner des DataFrames pandas prêts pour l'analyse.

**Fonctionnalités** :
- `load(symbol, date)` : charger un jour
- `load_range(symbol, start, end)` : charger une plage de dates
- `load_file(filepath)` : charger directement un fichier
- `us_only(df)` : filtrer session US
- `rth_only(df)` : filtrer RTH (9h30-16h00 ET)
- `drop_constants(df)` : supprimer les colonnes constantes (inutiles pour ML) — supprime ~69 colonnes sur une session unique
- `summary(df)` : résumé rapide (barres, sessions, prix, nulls)

**Conversions automatiques** : timestamp ms → datetime UTC + Eastern Time, index trié chronologiquement.

**Structure attendue des fichiers** : `{base}/{SYM}/YYYYMMDD_{SYM}.jsonl`

---

### 2.2 `rolling_features.py` — Le "cinéaste" (25 features ctx_*)

**Rôle** : Transformer les snapshots DMP (1 barre isolée) en film (dynamique sur fenêtres glissantes). Capte ce qui CHANGE entre les barres.

**Fenêtres** : short=3 barres (~3 min), mid=5 barres (~5 min), long=10 barres (~10 min).

#### Les 25 features par catégorie :

**CRITICAL (5)** — Signal fort, haute priorité :

| # | Feature | Description | Usage |
|---|---------|-------------|-------|
| 1 | `ctx_price_delta_div_3` | Divergence prix/delta sur 3 barres | +1=bull div, -1=bear div |
| 2 | `ctx_absorption_score_5` | Score d'absorption (delta pousse, prix ne suit pas) | 0-1, >0.3 = absorption active |
| 3 | `ctx_vol_sell_buy_ratio_5` | Ratio volume sell/buy bars | >1.0 = vendeurs dominent |
| 4 | `ctx_vwap_slope_accel` | Accélération du VWAP slope 10 | Positif = VWAP accélère vers le haut |
| 5 | `ctx_cvd_recovery_rate` | Vitesse de recovery du CVD normalisée | Positif = acheteurs reviennent |

**HIGH (8)** — Bon signal, fiable :

| # | Feature | Description |
|---|---------|-------------|
| 6 | `ctx_price_slope_5` | Pente prix 5 barres (direction court terme) |
| 7 | `ctx_delta_slope_5` | Pente delta 5 barres (accélère ou s'essouffle) |
| 8 | `ctx_delta_sum_3` | Somme delta 3 barres (impulsion court terme) |
| 9 | `ctx_vol_z_5` | Z-score volume 5 barres (détecte climax) |
| 10 | `ctx_diag_imbalance_mean_5` | Moyenne diag_imbalance 5 barres (footprint lissé) |
| 11 | `ctx_finish_strength_mean_5` | Qui finit les barres (tendance acheteurs/vendeurs) |
| 12 | `ctx_va_position_velocity` | Vitesse de déplacement dans la Value Area |
| 13 | `ctx_side_flip_count_10` | Compteur de flips VWAP (chop detection) |

**MEDIUM (4)** :

| # | Feature | Description |
|---|---------|-------------|
| 14 | `ctx_delta_sum_10` | Somme delta 10 barres (moyen terme) |
| 15 | `ctx_dist_vwap_velocity` | Vitesse d'éloignement du VWAP |
| 16 | `ctx_range_vs_atr_10` | Range 10 barres / ATR (expansion vs contraction) |
| 17 | `ctx_ib_position_velocity` | Vitesse dans l'Initial Balance |

**AUDIT FIX (3)** — Corrigent des faiblesses identifiées lors des tests :

| # | Feature | Description | Pourquoi ajoutée |
|---|---------|-------------|------------------|
| 18 | `ctx_instant_absorption` | Absorption bar-by-bar signée (-1/0/+1) | La div_3 ratait les absorptions post-climax |
| 19 | `ctx_absorption_streak_5` | Somme des absorptions instantanées sur 5 barres | Persistance du signal d'absorption |
| 20 | `ctx_climax_signal` | Vol Z-score > 1.5 + direction delta | Combine détection climax + direction |

**TIER 1 (3)** — Haute valeur, validées sur données :

| # | Feature | Description | Pourquoi ajoutée |
|---|---------|-------------|------------------|
| 21 | `ctx_vol_slope_5` | Pente du volume 5 barres | Le volume chutait de 3526→1186 post-climax (signal d'épuisement) |
| 22 | `ctx_delta_exhaustion` | Ratio |delta| vs max récent | Pattern "3 pushes" : chaque push plus faible |
| 23 | `ctx_large_trader_slope_5` | Pente du large_trader_ratio | Transition 1.15→0.86 = gros qui fuient |

**DYNAMIC SCORES (2)** — Remplacent des constantes C++ mortes :

| # | Feature | Remplace | Gain |
|---|---------|----------|------|
| 24 | `ctx_trend_day_score` | `trend_day_probability` (r=0.000) | De mort (0.15 constant) à score dynamique 0→0.80 |
| 25 | `ctx_day_type_intensity` | `day_type` (r=+0.012) | De 1 transition/session à score continu [-1,+1] (r=-0.156) |

---

### 2.3 `intermarket_features.py` — Vision cross-asset (10 features im_*)

**Rôle** : Capter ce qu'un seul instrument ne montre pas en croisant ES et NQ. Divergences de conviction, lead-lag, consensus institutionnel.

**Mécanisme** : Merge inner sur timestamp (les deux JSONL sont synchronisés barre par barre).

**Bug fixes intégrés** :
- Dedup ts après merge (évite pollution des fenêtres)
- Colonnes manquantes → NaN (pas de faux calculs silencieux)
- Nettoyage im_* du target avant merge (idempotent)
- Colonnes NaN par défaut si merge échoue

#### Les 10 features :

**CRITICAL (3)** :

| # | Feature | r(3) NQ | Description |
|---|---------|---------|-------------|
| 1 | `im_cross_delta_agreement_5` | **+0.271** | NQ et ES poussent du même côté ? < 0.4 = confusion = DANGER |
| 2 | `im_cross_delta_weighted_5` | **-0.242** | Agreement pondéré par magnitude — signal CONTRARIAN : consensus fort = exhaustion |
| 3 | `im_smt_divergence` | +0.098 | NQ fait un new high mais ES refuse (Smart Money Trap) |

**HIGH (4)** :

| # | Feature | r(3) NQ | Description |
|---|---------|---------|-------------|
| 4 | `im_delta_day_divergence` | -0.179 | Delta day d'un symbole flippe de signe mais pas l'autre |
| 5 | `im_price_ratio_slope_10` | -0.143 | Pente du ratio NQ/ES — qui surperforme |
| 6 | `im_volume_lead` | +0.113 | Qui a le volume qui accélère en premier |
| 7 | `im_cross_open_signal` | **-0.091** | Game changers ES injecté dans NQ quand NQ est neutre |

**MEDIUM (3)** :

| # | Feature | r(3) NQ | Description |
|---|---------|---------|-------------|
| 8 | `im_rolling_correlation_10` | +0.093 | Corrélation glissante prix — drop < 0.80 = découplage |
| 9 | `im_ltr_slope_diff` | -0.062 | Différentiel pente LTR — gros migrent d'un symbole à l'autre |
| 10 | `im_open_type_agreement` | 0.0* | Les deux symboles d'accord sur la direction d'ouverture |

*im_open_type_agreement est constant à 0 le 05/03 (NQ neutre → toujours 0). Signal pour les jours où les deux ont un open_type directionnel.

---

### 2.4 `game_changers.py` — Market Profile (parité C++)

**Rôle** : Réplique exacte en Python des algorithmes Market Profile du C++ (DMP_OpenType.h, DMP_ProfileShape.h). Validé 105/105 tests de parité.

**Note** : Les game changers sont DÉJÀ calculés par le C++ et présents dans le JSONL. Ce module sert pour :
1. Utilisation standalone (sans le C++)
2. Validation de parité
3. Référence des algorithmes

#### Classifieurs :

| Fonction | Description | Valeurs |
|----------|-------------|---------|
| `classify_open_type()` | Type d'ouverture (priorité OD > ORR > OAOR > OTD > OAIR) | 0-11 (12 types) |
| `classify_open_zone()` | Zone d'ouverture vs VA veille | 1-7 (7 zones) |
| `classify_day_type()` | Type de journée | 0-4 (NonTrend/Normal/NormVar/Neutral/Trend) |
| `classify_profile_shape()` | Forme du profil volume | 0-3 (D/P/b/B) |
| `direction()` | Direction du open_type | +1/-1/0 |
| `confidence()` | Confiance du open_type | 0.00-0.90 |
| `bias_boost()` | Ajustement du signal selon open_type | -0.30 à +0.20 |
| `check_odf()` | Surveillance Open Drive Failure post-10h30 | Upgrade OD → ODF |
| `Rule80Pct` | Machine 4 états pour la règle des 80% | IDLE→PRIMED→IN_VA→CONFIRMED |

#### Confiances :

| Open Type | Confiance | Signal |
|-----------|-----------|--------|
| ODF (Open Drive Failure) | 0.90 | Le plus fiable — reversal confirmé |
| OD (Open Drive) | 0.85 | Fort momentum directionnel |
| OTD (Open Test Drive) | 0.70 | Mouvement significatif dans VA |
| OAOR (Open Auction Outside Range) | 0.65 | Gap qui tient |
| ORR (Open Rejection Reverse) | 0.60 | Reversal depuis hors VA |
| OAIR (Open Auction In Range) | 0.30 | Range — pas de direction |
| UNKNOWN | 0.00 | Données insuffisantes |

#### bias_boost (signal × open_type) :

| Signal | OD (strong) | OTD/ORR/OAOR | OD opposé | OTD/ORR/OAOR opposé |
|--------|-------------|---------------|-----------|---------------------|
| Long | +0.20 | +0.10 | **-0.30** (JAMAIS fader) | -0.15 |
| Short | +0.20 | +0.10 | **-0.30** (JAMAIS fader) | -0.15 |

---

### 2.5 `ERRATA_AUDIT_MARKET_PROFILE.md` — Corrections

**Rôle** : Document de corrections vérifiées ligne par ligne contre le code C++ source. Identifie 7 erreurs/nuances dans l'analyse initiale.

**Points clés validés** :
- Les 12 open_types et 7 confiances sont exacts
- L'algorithme open_type (OD > ORR > OAOR > OTD > OAIR) est fidèle
- bias_boost() est une réplique parfaite
- La Rule 80% machine 4 états est correcte

**Erreurs corrigées** :
- Nombre de colonnes DMP : le meta.json hardcode 158 mais le C++ sérialise ~214
- trend_day_probability est dans DMP_Transform.h, pas DMP_OpenType.h
- La condition Trend Day exige EXCLUSIVEMENT un seul côté (même 1 tick de l'autre côté bloque)
- profile_shape via VPOC J-1 ne fonctionne pas (il faut le developing VPOC intra-day)

---

## 3. Résultats : ranking global des 41 features

Corrélation avec le rendement futur 3 barres (r(3)) sur les 239 barres US du 05/03/2026 :

| Rang | Feature | r(3) | r(5) | Type | Catégorie |
|------|---------|------|------|------|-----------|
| 1 | `im_cross_delta_agreement_5` | **+0.271** | +0.346 | IM | Cross-delta direction |
| 2 | `im_cross_delta_weighted_5` | **-0.242** | -0.237 | IM | Cross-delta magnitude (contrarian) |
| 3 | `profile_skew` | -0.228 | -0.317 | GC | Profil asymétrique |
| 4 | `ctx_side_flip_count_10` | -0.225 | -0.294 | CTX | Chop detection |
| 5 | `im_delta_day_divergence` | -0.179 | -0.264 | IM | Delta day cross-asset |
| 6 | **`ctx_day_type_intensity`** | **-0.156** | -0.202 | CTX ★ | Score dynamique day type |
| 7 | `ctx_range_vs_atr_10` | -0.153 | -0.270 | CTX | Expansion range |
| 8 | `ctx_vwap_slope_accel` | +0.125 | +0.145 | CTX | Accélération VWAP |
| 9 | `poc_position` | -0.114 | -0.101 | GC | Position POC dans profil |
| 10 | `im_volume_lead` | +0.113 | +0.075 | IM | Qui mène en volume |
| 11 | `volume_imbalance` | -0.112 | -0.260 | GC | Déséquilibre volume |
| 12 | `im_smt_divergence` | +0.098 | +0.043 | IM | SMT (Smart Money Trap) |
| 13 | `ctx_vol_slope_5` | -0.095 | -0.140 | CTX | Pente volume |
| 14 | `im_rolling_correlation_10` | +0.093 | +0.047 | IM | Corrélation NQ/ES |
| 15 | **`im_cross_open_signal`** | **-0.091** | -0.073 | IM ★ | ES game changers → NQ |
| 16 | `open_bias_conf` | +0.091 | +0.073 | GC | Confiance open type |
| 17 | **`ctx_trend_day_score`** | **+0.086** | +0.132 | CTX ★ | Score trend dynamique |
| 18 | `ctx_finish_strength_mean_5` | -0.082 | -0.176 | CTX | Qui finit les barres |
| ... | ... | ... | ... | ... | ... |
| 40 | `day_type` | +0.012 | +0.054 | GC | Enum figé (1 transition) |
| 41 | `trend_day_probability` | **+0.000** | -0.000 | GC | Constante 0.15 (mort) |

**Répartition du top 10** : 4 IM, 3 CTX, 3 GC — les trois couches contribuent.

---

## 4. Résultats : validation croisée NQ/ES

Features testées sur les deux cibles (NQ target + ES target). "Stable" = même signe de corrélation des deux côtés.

| Feature | NQ r(3) | ES r(3) | Stable |
|---------|---------|---------|--------|
| `im_cross_delta_agreement_5` | +0.271 | +0.260 | ✅ |
| `im_cross_delta_weighted_5` | -0.242 | -0.189 | ✅ |
| `im_rolling_correlation_10` | +0.093 | +0.106 | ✅ |
| `ctx_vwap_slope_accel` | +0.125 | +0.040 | ✅ |
| `ctx_vol_slope_5` | -0.095 | -0.134 | ✅ |
| `ctx_day_type_intensity` | -0.156 | -0.101 | ✅ ★ |
| `im_cross_open_signal` | -0.091 | -0.072 | ✅ ★ |

**7 features stables cross-asset** = candidats fiables pour un modèle multi-instrument.

Les features directionnelles (volume_lead, delta_day_divergence, price_ratio_slope) flippent entre NQ et ES target — c'est normal (le signal est le même, vu de l'autre côté).

---

## 5. Guide d'utilisation rapide

### Installation

```bash
pip install pandas numpy
```

Aucune autre dépendance.

### Usage minimal

```python
from dmp_reader import DmpReader
from rolling_features import RollingFeatures
from intermarket_features import IntermarketFeatures

# 1. Charger les données
reader = DmpReader("D:/TRADING_SIERRA_CHART_AUTO/DATA")
df_nq = reader.load("NQ", "2026-03-05")
df_es = reader.load("ES", "2026-03-05")

# 2. Rolling features (25 ctx_*)
rf = RollingFeatures()
nq_ctx = rf.compute(df_nq)
es_ctx = rf.compute(df_es)

# 3. Intermarket features (10 im_*)
im = IntermarketFeatures()
nq_full = im.compute(nq_ctx, es_ctx, target="NQ")

# 4. Résultat : 251 colonnes par barre
print(f"{len(nq_full.columns)} colonnes, {len(nq_full)} barres")

# 5. Résumé
rf.summary(nq_full)
im.summary(nq_full)
```

### Charger directement un fichier

```python
df = reader.load_file("20260305_NQ.jsonl")
```

### Nettoyer pour le ML

```python
# Supprimer les colonnes constantes (69 cols en moins sur 1 session)
df_clean = reader.drop_constants(nq_full, verbose=True)
```

### Game changers standalone

```python
from game_changers import *

# Vérifier la parité C++
run_parity_tests()  # 105/105

# Utiliser les classifieurs
ot = classify_open_type(open_cash=5000, prev_vah=5050, prev_val=4950,
                        ib_high=5025, ib_low=5000, price_at_1030=5020)
print(open_type_name(ot))       # "OD_UP"
print(confidence(ot))            # 0.85
print(bias_boost(+1, ot))       # +0.20 (long aligné avec OD_UP)
print(bias_boost(-1, ot))       # -0.30 (short CONTRE OD_UP → interdit)
```

### Filtres de session

```python
us_only = reader.us_only(df)        # Session US uniquement
rth_only = reader.rth_only(df)      # RTH 9:30-16:00 ET
```

---

## 6. Historique des itérations

| Version | Features | Détection événements | Changements |
|---------|----------|---------------------|-------------|
| v1 | 17 ctx | 30% (3/10) | Première version |
| v2 | 20 ctx | 90% (9/10) | +instant_absorption, +streak, +climax_signal |
| v3 | 23 ctx | 100% (10/10) | +vol_slope, +delta_exhaustion, +ltr_slope |
| v4 | 25 ctx + 10 im | 100% + cross-asset | +trend_day_score, +day_type_intensity, +cross_open_signal, +open_type_agreement, +weighted_agreement, +ltr_slope_diff |

---

## 7. Leçons du 05/03/2026

### Le fait marquant : ES savait avant NQ

| | NQ | ES |
|---|---|---|
| open_type | OAIR (neutre, conf 0.30) | **OAOR_DOWN (bearish, conf 0.65)** |
| bias_boost(short) | 0.00 | **+0.10** |
| bias_boost(long) | 0.00 | **-0.15** |
| Prix sur la session | -84 pts | -12 pts |
| Delta day début | -3 075 (déjà vendu) | +268 (encore acheteur) |
| Delta day fin | -1 465 (recovery) | -2 176 (effondrement) |

ES avait le biais bearish correct dès 10:30 ET. NQ ne donnait rien. C'est la raison d'être de `im_cross_open_signal` : quand NQ est neutre, prendre le signal ES.

### Le pattern "3 pushes" détecté

Trois vagues d'achat successives, chacune plus faible :
1. B00-B01 : delta +211/+204 → prix ne monte pas (absorption)
2. B19 : delta +500, vol 2524 → **buy climax** → rejet immédiat
3. B50 : delta +410, vol 3450 → **bounce raté** → continuation baissière

`ctx_delta_exhaustion` capte ce pattern : chaque push est un ratio plus faible du max précédent.

### Le sell climax et l'exhaustion

B42 : delta -812, vol 3526 (le plus gros de la session). Puis le volume chute : 3526 → 2657 → 1707 → 1244 → 1250 → 1186. `ctx_vol_slope_5` passe de +603 à -97, signalant la fin du flush.

### La confusion cross-delta précède le crash

`im_cross_delta_agreement_5` tombe à **0.20** à B41 — le plus bas de la session. 3 barres plus tard : B42 = le sell climax (-83 pts). La confusion NQ/ES PRÉCÈDE systématiquement les moves violents.

---

## 8. Problèmes connus et limitations

### Données : 1 seul jour

Toutes les corrélations sont calculées sur 239 barres d'une seule session. C'est suffisant pour valider la mécanique mais insuffisant pour confirmer les edges statistiques. Ne PAS optimiser de seuils sur ce dataset.

### Features mortes dans le DMP C++

| Feature C++ | Problème | Remplacement Python |
|-------------|----------|---------------------|
| `trend_day_probability` | Constante 0.15 toute la session | `ctx_trend_day_score` (dynamique) |
| `day_type` | 1 seule transition sur 239 barres | `ctx_day_type_intensity` (continu) |
| `retest_high/low_count` | Toujours 0 (BUG C++ #5, pas implémenté) | Aucun (attendre fix C++) |

### SMT Divergence : 2 triggers / 99 barres

Le seuil de 20 ticks est correct mais la SMT est un événement rare par nature. Le 05/03, NQ et ES font leur high ensemble → pas de divergence au sommet. Besoin de plus de jours pour valider.

### im_open_type_agreement : constant à 0

Le 05/03, NQ est neutre (OAIR) → agreement toujours 0. Ce signal n'apparaît que quand les deux symboles ont un open_type directionnel — rare mais potentiellement très informatif.

### Seuils hardcodés

- `ctx_instant_absorption` : seuil delta > 30 (vs 10 pour `ctx_absorption_score_5`). Deux seuils différents pour des concepts similaires. À harmoniser après backtesting sur plus de données.
- `im_smt_divergence` : seuil 20 ticks = 4.3% ATR NQ mais 20.2% ATR ES. Asymétrique en volatilité relative.

---

## 9. Prochaines étapes

### Priorité 1 — Validation multi-jours

Backtester les 41 features sur 20+ jours de données pour confirmer :
- Quelles features gardent leur rang
- Quels seuils sont stables
- Quelles features sont overfittées sur le 05/03

### Priorité 2 — Intégration moteur de décision

Le pipeline produit 251 colonnes. Le moteur ML (MenthorQ 50%, OrderFlow 30%, Context 20%) doit consommer ces features pour produire des signaux de trading.

### Priorité 3 — Calendrier macro

Ajouter un filtre binaire CPI/FOMC/NFP : ne pas trader dans les 5 minutes avant/après. C'est un filtre de protection, pas une feature ML.

### Priorité 4 — Régime detector

Combiner VIX, ATR, IB range, composite range pour déterminer le régime de marché (trending/mean-reverting/volatile/comprimé) et pondérer les features en conséquence.

### Priorité 5 — Post-trade logger

Dès le premier trade live, logger chaque décision avec les 251 features au moment de l'entrée et le résultat. C'est le feedback loop qui permet d'ajuster les poids.

---

## Annexe : structure des fichiers

```
D:\TRADING_SIERRA_CHART_AUTO\
├── CORE\
│   ├── dmp_reader.py              (lecteur JSONL → DataFrame)
│   ├── rolling_features.py        (25 features ctx_*)
│   ├── intermarket_features.py    (10 features im_*)
│   └── game_changers.py           (classifieurs Market Profile)
│
├── DATA\
│   ├── NQ\
│   │   └── 20260305_NQ.jsonl      (239 barres, 214 cols)
│   └── ES\
│       └── 20260305_ES.jsonl      (239 barres, 214 cols)
│
└── DOCS\
    ├── MIA_PIPELINE_RECAP.md      (ce document)
    └── ERRATA_AUDIT_MARKET_PROFILE.md
```
