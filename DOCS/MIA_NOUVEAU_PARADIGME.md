# 🧠 MIA — NOUVEAU PARADIGME DE TRADING
## Market Profile au Centre, Intelligence sans Over-Engineering

**Date** : 01/03/2026
**Principe** : 142 features disponibles → on en utilise ~20 qui comptent vraiment.

---

## LE CHANGEMENT EN 1 PHRASE

**Avant** : "Je scanne le marché pour un signal BN, puis je valide avec 4 layers de 15 conditions."
**Après** : "Je sais quel type de journée c'est, j'attends le prix sur mes niveaux, je confirme avec l'order flow."

---

## POURQUOI C'EST DIFFÉRENT

L'ancien système pose la question : **"Est-ce qu'il y a un signal ?"**
→ Réponse : toujours oui quelque part, d'où les faux signaux.

Le nouveau système pose la question : **"Est-ce que le marché me donne un trade ?"**
→ Réponse : seulement quand le contexte + le niveau + la confirmation s'alignent.

La différence fondamentale : on ne CHERCHE plus de trades. On ATTEND que le marché vienne à nous.

---

## L'ARCHITECTURE — 3 NIVEAUX, PAS 4

```
┌─────────────────────────────────────────────────────────────┐
│  RÉGIME  —  Quel type de journée ? (calculé 1x à 10h30)    │
│  → 5 features seulement                                     │
│  → Détermine QUOI trader et COMMENT                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  ZONE  —  Où attendre le prix ? (continu)                   │
│  → 6-8 niveaux max par session                              │
│  → PV levels + MenthorQ en confluence                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  TRIGGER  —  Le marché confirme-t-il ? (temps réel)         │
│  → BN + CVD : ce qu'on a déjà et qui marche                │
│  → Adapté au régime (continuation vs reversal)              │
└─────────────────────────────────────────────────────────────┘
```

Pas de Layer 4. Pas de score A/B/C/D. Pas de combo filter.
3 niveaux, chacun avec un rôle clair et non-redondant.

---

## NIVEAU 1 — LE RÉGIME

### Quand : Calculé une fois, entre 10h00 et 10h30 ET (après formation de l'IB)
### But : Savoir QUEL TYPE de trades on cherche aujourd'hui

### Les 5 features utilisées (sur 142 disponibles)

| # | Feature | Source | Rôle |
|:-:|---------|--------|------|
| 1 | `open_zone` | DMP_OpenType.h | Où on a ouvert vs VA veille (7 zones) |
| 2 | `open_type` | DMP_OpenType.h | Comment le marché s'est comporté (12 types) |
| 3 | `ib_range_atr` | DMP_Transform.h | IB large ou étroite → type de journée |
| 4 | `profile_shape` | DMP_ProfileShape.h | D/P/b/B → confirmation du régime |
| 5 | `vix_regime` | Déjà dans le bot | Volatilité macro |

### La matrice de régime (5 régimes, pas 12)

On simplifie les 12 open_types en **5 régimes actionnables** :

```
RÉGIME 1 — TREND (suivre le mouvement)
  Conditions : open_type = OD_UP ou OD_DOWN
               OU ib_range_atr > 0.80
               OU (OAOR + prix reste hors VA)
  Profile   : P-shape (trend up) ou b-shape (trend down)
  
  → Trades : UNIQUEMENT dans le sens de la tendance
  → SL : sous le dernier swing low (trend up) / au-dessus swing high (trend down)
  → TP : PAS de TP fixe → trailing stop agressif
  → Sizing : maximum (conviction forte)
  → Ne jamais fader

RÉGIME 2 — ROTATION (fader les extrêmes)
  Conditions : open_type = OAIR
               ET ib_range_atr entre 0.40 et 0.80
               ET profile_shape = D (distribution normale)
  
  → Trades : les 2 sens, fader les extrêmes de la VA/IB
  → SL : au-delà de l'extrême de la VA session
  → TP : VPOC session ou PVPOC (aimant magnétique)
  → Sizing : normal
  → Ne jamais chercher de breakout

RÉGIME 3 — REVERSAL (retournement confirmé)
  Conditions : open_type = ORR_UP/DOWN ou ODF_UP/DOWN
               OU (OAOR qui échoue et revient dans VA → Règle 80%)
  
  → Trades : dans le sens du reversal UNIQUEMENT
  → SL : serré (le pivot est clair)
  → TP : VA complète si Règle 80% active, sinon PVPOC
  → Sizing : fort (haute conviction)
  → Setup rare mais très rentable

RÉGIME 4 — BREAKOUT (compression → explosion)
  Conditions : ib_range_atr < 0.40 (IB très étroite)
               OU profile_shape = B (double distribution)
  
  → Trades : attendre cassure IB High ou IB Low + pullback
  → SL : de l'autre côté de l'IB (invalide le breakout)
  → TP : extension 1.5× la taille de l'IB
  → Sizing : normal
  → Patience requise (peut prendre des heures)

RÉGIME 5 — INCERTAIN (ne pas trader ou être très sélectif)
  Conditions : open_type = UNKNOWN (avant 10h30)
               OU VIX > 30
               OU day_type = Neutral (extension des 2 côtés)
               OU rien ne matche clairement
  
  → Trades : seulement si confluence L1 ≥ 6 ET trigger L3 maximal
  → Sizing : minimum
  → Accepter de ne rien faire
```

### Règle d'or du Régime

**Le régime est calculé UNE FOIS à 10h30 et ne change pas.**
Exception unique : si un OD échoue (ODF détecté) → basculer en REVERSAL.
On ne réévalue pas 50 fois par jour. Le régime c'est le plan.

---

## NIVEAU 2 — LA ZONE

### Quand : Continu, mais les niveaux sont définis avant l'ouverture + mis à jour 1x après IB
### But : Savoir OÙ le prix doit aller pour qu'on s'intéresse

### Les niveaux — 6 à 8 max par session

On ne met pas 30 niveaux. On en garde **6-8 maximum** qui comptent.

**Sélection des niveaux selon le régime :**

```
RÉGIME TREND :
  1. PVPOC          — point de rechargement (pullback pour re-entry)
  2. PVAH ou PVAL   — selon direction (support si trend up, résistance si trend down)
  3. IB High ou Low — breakout level (déjà cassé en trend)
  4. Swing Low/High — SL structurel
  + MenthorQ en confluence si < 5 ticks d'un PV level

RÉGIME ROTATION :
  1. PVPOC          — magnet central (TP naturel)
  2. PVAH           — extrême haut pour SHORT
  3. PVAL           — extrême bas pour LONG
  4. Session VPOC   — deuxième magnet
  5. IB High        — extrême haut alternatif
  6. IB Low         — extrême bas alternatif
  + MenthorQ en confluence

RÉGIME REVERSAL :
  1. Pivot du reversal (prix exact du rejet ODF/ORR)
  2. PVPOC          — premier objectif
  3. VA opposée     — TP si Règle 80% (traverser toute la VA)
  + MenthorQ en confluence

RÉGIME BREAKOUT :
  1. IB High        — trigger cassure haussière
  2. IB Low         — trigger cassure baissière
  3. Extension 1.5×IB — TP naturel
  4. PVPOC          — support/résistance après cassure
  + MenthorQ en confluence
```

### Le scoring des niveaux (simplifié)

```
Score d'un niveau = Base + Confluence

BASE :
  PVPOC           = 4  (le plus important)
  PVAH / PVAL     = 3
  PVWAP            = 2
  Session VPOC    = 3
  IB High / Low   = 3
  Swing H/L       = 2

CONFLUENCE (bonus) :
  MenthorQ level < 5 ticks  = +2  (Gamma Wall, HVL, GEX 1-3)
  MenthorQ level < 10 ticks = +1  (GEX 4-10, PUT/CALL wall)
  HVN session < 3 ticks     = +1  (volume confirme le niveau)

MINIMUM pour activer une zone :
  Score ≥ 4 = zone active (on attend le prix)
  Score ≥ 6 = zone haute conviction (sizing augmenté)
```

**C'est tout.** Pas de score A/B/C/D. Pas de 15 conditions. Un nombre + un seuil.

---

## NIVEAU 3 — LE TRIGGER

### Quand : Le prix arrive dans une zone active (< 10 ticks)
### But : Confirmer que le marché RÉAGIT au niveau, pas juste qu'il passe

### Les features de trigger (ce qu'on a déjà)

Le BN et le CVD sont déjà bien implémentés dans le bot. On ne les change pas.
On les **adapte au régime**.

```
TRIGGER EN RÉGIME TREND (on cherche une CONTINUATION) :
  → CVD qui reprend dans le sens de la tendance après un pullback
  → BN : color zones alignées avec la tendance
  → BN : PAS d'absorption contra-tendance (sinon → pas d'entrée)
  → Delta positif (trend up) ou négatif (trend down)
  
  Seuil : bn_score > 0.05 dans le sens du trend + delta aligné
  C'est moins exigeant car le régime fait le gros du travail.

TRIGGER EN RÉGIME ROTATION (on cherche un REJET) :
  → Absorption visible (absorb_bid pour LONG en bas, absorb_ask pour SHORT en haut)
  → CVD divergence (prix descend mais CVD monte = acheteurs cachés)
  → BN edge zone dans le bon sens
  → Delta qui s'inverse sur le test du niveau
  
  Seuil : absorption OU cvd_divergence + bn_score aligné
  Plus exigeant car on trade contre le mouvement immédiat.

TRIGGER EN RÉGIME REVERSAL (on cherche un RETOURNEMENT FORT) :
  → Absorption massive (les deux côtés tentent de prendre le contrôle)
  → Delta flip (changement brutal de direction)
  → BN triple ask/bid ou edge zone + rotation combo
  → CVD : slope qui s'inverse fortement
  
  Seuil : signal BN fort (score > 0.15) + delta flip
  Le signal doit être VIOLENT pour confirmer le reversal.

TRIGGER EN RÉGIME BREAKOUT (on cherche un MOMENTUM post-cassure) :
  → Volume élevé sur la cassure IB (vol_per_sec élevé)
  → Delta fort dans le sens de la cassure
  → PAS d'absorption contra (sinon c'est un faux breakout)
  → Pullback vers IB line + rebond = entry idéale
  
  Seuil : delta fort + volume + pullback tient le niveau cassé
```

---

## SL / TP — ADAPTÉ AU RÉGIME

### SL (Stop Loss)

```
TREND   : Sous le dernier swing low (LONG) / au-dessus swing high (SHORT)
          → Large, on accepte le bruit. Min = config.sl_default × 1.2
          
ROTATION: Au-delà de la VA (PVAH + buffer pour SHORT, PVAL - buffer pour LONG)
          → Moyen. Si le prix sort de la VA, le setup est invalide.
          
REVERSAL: Serré, au-delà du pivot de reversal + buffer
          → Le pivot est clair, si il casse le reversal est faux.
          
BREAKOUT: De l'autre côté de l'IB
          → Si le prix revient dans l'IB après breakout = faux breakout.
```

### TP (Take Profit)

```
TREND   : PAS de TP fixe. Trailing stop uniquement.
          Trailing activation = +1× ATR. Distance = 0.5× ATR.
          Laisser courir les gagnants.
          
ROTATION: VPOC session ou PVPOC (le plus proche).
          Le prix est attiré vers le centre.
          Possibilité de TP partiel (50%) au premier VPOC, reste vers le second.
          
REVERSAL: Si Règle 80% → l'autre bout de la VA.
          Sinon → PVPOC comme premier objectif.
          
BREAKOUT: Extension 1.5× IB range dans le sens de la cassure.
          Ou prochain HVN comme obstacle.
```

---

## CE QU'ON NE FAIT PAS (anti over-engineering)

```
❌ On n'utilise PAS les 142 features du dumper
❌ On n'utilise PAS les composite profiles 100d/200d (trop loin)
❌ On ne calcule PAS 15 niveaux avec 10 confluences chacun
❌ On ne score PAS A/B/C/D avec des pondérations complexes
❌ On ne réévalue PAS le régime toutes les 5 minutes
❌ On ne cherche PAS à prédire — on RÉAGIT
❌ On n'ajoute PAS de Layer 4, 5, 6
❌ On ne fait PAS de ML prédictif en live (on collecte pour apprendre plus tard)
```

---

## LES ~20 FEATURES QUI COMPTENT (sur 142)

| # | Feature | Rôle | Source |
|:-:|---------|------|--------|
| 1 | `open_zone` | Biais direction session | DMP_OpenType |
| 2 | `open_type` | Type d'ouverture → régime | DMP_OpenType |
| 3 | `open_direction` | +1/-1/0 simplifié | DMP_OpenType |
| 4 | `day_type` | Type de journée progressif | DMP_OpenType |
| 5 | `rule_80pct` | Signal haute conviction | DMP_OpenType |
| 6 | `ib_range_atr` | IB large/étroite | DMP_Transform |
| 7 | `ib_broken_up/down` | Cassure IB | DMP_Transform |
| 8 | `profile_shape` | D/P/b/B | DMP_ProfileShape |
| 9 | `vix_regime` | Volatilité | Déjà dans bot |
| 10 | `dist_prev_vpoc` | Distance PVPOC | Déjà dans bot (ticks) |
| 11 | `dist_prev_vah` | Distance PVAH | Déjà dans bot |
| 12 | `dist_prev_val` | Distance PVAL | Déjà dans bot |
| 13 | `dist_ib_high` | Distance IB High | À ajouter |
| 14 | `dist_ib_low` | Distance IB Low | À ajouter |
| 15 | `dist_vwap_d` | Position vs VWAP jour | À ajouter |
| 16 | `swing_high/low` | Structure | Déjà dans bot |
| 17 | `bn_score` | Order flow composite | Déjà dans bot |
| 18 | `cvd_divergence` | Divergence volume | Déjà dans bot |
| 19 | `absorb_ask/bid` | Absorption | Déjà dans bot |
| 20 | `delta` / `deltaPct` | Direction order flow | Déjà dans bot |

**20 features. Pas 142. C'est suffisant pour couvrir 100% des décisions.**

---

## COMPARAISON AVANT / APRÈS

| Aspect | Ancien (4 Layers) | Nouveau (3 Niveaux) |
|--------|-------------------|---------------------|
| **Contexte journée** | Aucun | Régime calculé à 10h30 |
| **Niveaux** | ~15 MenthorQ + BN | 6-8 PV + MQ en confluence |
| **Conditions pour trader** | ~15 validations | ~5 conditions claires |
| **SL/TP** | Fixe (20t/24t ES) | Adapté au régime |
| **Trend Day** | Même règles que Range | Trailing sans TP, sens unique |
| **Range Day** | Même règles que Trend | Fade extrêmes, TP = VPOC |
| **Features utilisées** | ~51 brutes | ~20 intelligentes |
| **Over-engineering** | Score A/B/C/D + combo | Un régime + un seuil |
| **Lisibilité du log** | "L1:PASS L2:PASS L3:VETO" | "ROTATION + PVPOC + absorb_bid → LONG" |

---

## PROCHAINE ÉTAPE CONCRÈTE

### Option A — Data-Driven (recommandé)
1. Lancer le dumper G3 en RTH pendant 2-3 semaines
2. Collecter les JSONL avec open_type, profile_shape, IB, HVN/LVN
3. Analyser en Python : est-ce que les régimes tiennent la route ?
4. Backtester les règles sur données historiques
5. Intégrer dans le bot seulement ce qui est prouvé

### Option B — Trading Manuel avec le framework
1. Chaque matin, noter manuellement : open_zone, IB size, profile shape
2. Trader avec cette grille mentale pendant 2-3 semaines
3. Journal de trading pour valider les hypothèses
4. Puis coder une fois qu'on a l'intuition validée

### Option C — Intégration directe (risqué)
1. Porter les calculs DMP_OpenType dans le bot C++
2. Coder les 5 régimes
3. Tester en sim
→ Plus rapide mais sans validation data

---

*"La simplicité est la sophistication suprême." — Leonardo da Vinci*
*"Ce n'est pas le trader avec le plus d'indicateurs qui gagne,*
*c'est celui qui sait ce qu'il cherche avant d'ouvrir son chart."*
