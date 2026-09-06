# Synthese croisee — Claude Code x Fable, 06/09/2026

Pour Jackson et pour Fable. Objet : mettre cote a cote ce que chacun a mesure,
signaler les convergences, ce que chacun apporte a l'autre, et **deux corrections
a la proposition de cycle 2 de Fable** que la mesure impose.

---

## 1. Ce que j'ai mesure aujourd'hui — verifiable, chiffre par chiffre

Tout ce qui suit est reproductible sur `DATA/live_enriched/sierra/`, 57 jours,
barres dedoublonnees par minute (`recalc.dedoublonner_par_minute`).

### Six confusions points/ticks, toutes de facteur 4

| # | ou | effet mesure |
|---|---|---|
| 1 | `sess_range_atr` | mauvaise unite d'ATR, TODO du 19/05 jamais livre |
| 2 | `dist_*_atr` livres | rapport livre/vrai = **4,000 exactement** |
| 3 | `atr` lu au lieu de `atr_14m` | ATR « median 125 » sur ES, absurde et pourtant plausible |
| 4 | seuil `0,10 ATR-5m` | vaut **1,13 tick sur ES**, plus fin que la grille |
| 5 | **`ib_range_atr`** | = `ib_range_ticks / atr` : TICKS / POINTS. Identique au livre a **100 %** sur 12 580 barres. Seuil « < 0,40 » couvrait **0,13 %** des barres au lieu de 53 % — **facteur 400**, H6 n'a jamais pu declencher |
| 6 | cout par trade | « 25 pts MNQ = 12,50 $ » — c'est 25 TICKS. Cout surestime **3,3x** sur NQ, sous-estime **2,2x** sur ES |

**Le crible qui tranche en deux minutes** : reconstruire la colonne par une formule
en unites *incoherentes* et comparer au livre. Une egalite a 100 % avec une
formule incoherente identifie le diviseur sans ambiguite.

### Le cout reel, et la consequence structurelle

| | $/point | ATR-5m en $ | cout par trade |
|---|---|---|---|
| MNQ | 2,00 | 40,10 | **0,070 ATR** |
| MES | 5,00 | 14,15 | **0,305 ATR** |

**Sur MES, un aller-retour coute 30 % de l'ATR-5m** — 20 % du TP, 30 % du SL.
Le micro ES en intraday 5 min ne peut pas gagner : arithmetique, pas hypothese.
Verifie sans exception sur les trois hypotheses qui ont produit des trades, toutes
positives sur NQ et negatives sur ES.

### Les trois lectures, toutes pre-enregistrees, toutes a zero

| | resultat |
|---|---|
| Cycle 1 (six hypotheses, tag `mission-phase2-v1`) | zero survivante |
| Cycle 2 (barriere par famille sur H3) | zero — le taux de reussite monte a 66 %, l'esperance ne suit pas |
| Horizon 15 min | H3 **positive sur les deux instruments** (+0,018 / +0,019) mais **N = 28/29 < 40** |

### Le HVL comme regime — la correction de Fable, verifiee et calibree

| | ES | NQ |
|---|---|---|
| `dist_mq_hvl` renseigne | **99,7 %** | 96,3 % |
| prix au-dessus du HVL | 66,8 % | 57,6 % |
| bascules **sans** zone morte | 10,2 / jour | 8,2 / jour |
| bascules **avec** zone morte 1,0 ATR-5m | **1,8 / jour** | **1,5 / jour** |
| barres couvertes avec zone morte | 93 % | 90 % |

**Un regime qui change dix fois par jour n'est pas un regime.** La zone morte de
1,0 ATR-5m est necessaire, et elle ne coute que 7 a 10 % de couverture.

### Les gates de Bot 1 v2, mesures pour la premiere fois

```
ES : 603 signaux bruts -> 271 passent (55 % bloques)
NQ : 701 -> 288 (59 %)
L0_MAX_TRADES_JOUR  739 blocages | L0_EOD_LOCKOUT 6 | tous vetos L5 : 0
```

**La limite de cinq trades par jour ferme 57 % des signaux a elle seule.** Aucun
veto L5 ne mord jamais. Reserve ecrite dans le code : `L0_STOP_JOURNALIER` n'a pas
pu etre teste (le P&L d'un trade n'est connu qu'apres sa cloture).

### Les seize setups d'`edge_discovery`, portes

Meme maladie, en pire : `dist_prev_vah < -500` = 18,5 ATR ES, declenche sur 0,8 %
des barres ES et 13,7 % des barres NQ — **facteur 17**. Et « proche du VPOC »
(`abs< 100`) est vrai **78 % du temps sur ES**. Portes en ATR, quatre atteignent
40 signaux, **mode ombre a partir du 08/09**, Bonferroni /16.

---

## 2. Ce que j'apporte que Fable n'a pas

**arXiv:2605.04004 — Mesfin, « Structural Limits of OHLCV-Based Intraday Signals
in MNQ Futures: A Systematic Falsification Study », mai 2026.**

| | |
|---|---|
| instrument | **MNQ** |
| periode | **947 jours**, 2021-2025 |
| signaux | **14 familles** OHLCV |
| criteres | walk-forward, t >= 2,0, N >= 30, net de **2 points de friction**, coherence inter-annuelle |
| resultat | **aucune ne passe** ; brut maximal 0,07 a 1,50 point, **sous la friction** |

C'est la source la plus proche de notre situation exacte, et elle manque a la
liste de Fable. Elle dit deux choses :

1. **Nos deux zeros ne sont pas un echec de methode** — ils reproduisent sur
   40 jours ce qu'une etude independante trouve sur 947.
2. **Les signaux OHLCV intraday sont epuises.** Notre H3 a +0,018 ATR sur NQ vaut
   ~0,72 $ net : exactement l'ordre de grandeur de leur « brut maximal sous la
   friction ».

Et une piste que le papier ouvre en creux : l'**order flow** montre un IC de
+0,0044 (+0,0022 hors echantillon) et un R² ajuste **superieur a l'OHLCV seul**.
Nous avons `delta_bar`, `cvd_day`, `ask/bid_pct`, les clusters VAP, le footprint —
que le papier MNQ n'avait pas. **Sur six hypotheses du cycle 1, une seule en
dependait vraiment (H8), et elle est morte sur une conjonction impossible, pas sur
une absence d'edge.**

---

## 3. Ce que Fable apporte que je n'avais pas

**Les sources peer-reviewed.** Mes recherches n'ont rendu que des blogs et des
vendeurs de donnees sur le gamma. Fable rend Baltussen-Da-Lammers-Martens (JFE 142,
2021), Barbon-Buraschi (Gamma Fragility), Gao-Han-Li-Zhou (JFE 129, 2018), Cboe
Research sur les 0DTE. C'est ce qui manquait a mon audit, et je le dis sans
detour : **sur ce point sa recherche est meilleure que la mienne.**

**Et surtout : le momentum de fin de journee.** Effet documente sur 60 marches et
46 ans, Sharpe 0,87-1,73, R² predictif 1,6 % sur SPY — et **absent de toutes nos
listes**, des dix hypotheses initiales aux seize d'`edge_discovery`. Il se definit
en une ligne, il est testable en OHLCV seul, et il est le seul candidat dont
l'effet soit etabli ailleurs qu'en pratique praticienne.

C'est le meilleur apport de la journee, et il ne vient pas de moi.

---

## 4. Deux corrections a la proposition de cycle 2 de Fable

### C2-3 : le seuil `ib_range_atr_r > 1,2` ne peut pas se declencher

Mesure sur 22 161 barres ES et 22 129 NQ, avec la formule corrigee :

| | p50 | p90 | p99 | **max** |
|---|---|---|---|---|
| ES | 0,387 | 0,651 | 0,930 | **0,946** |
| NQ | 0,414 | 0,709 | 0,919 | **0,919** |

`> 1,2` : **0,00 % des barres, sur les deux instruments.** Le maximum jamais
observe est 0,946. C'est exactement l'erreur de H6 au cycle 1 — un seuil ecrit
sans mesurer sa distribution, et une hypothese non testable par construction.

### C2-3 : largeur d'IB et extension d'IB ne sont pas la meme chose

La proposition utilise `ib_range_atr_r` eleve comme regime de **tendance**. Or
Dalton dit l'inverse : **IB etroite -> jour de tendance probable ; IB large ->
jour de range**. Un `ib_range_atr_r` eleve est un jour de RANGE, pas de tendance.

Ce que la proposition vise est vraisemblablement l'**extension** d'IB — le prix
qui sort de l'IB et l'etend — qui se mesure par `ctx_ib_extension_ratio`, une
colonne differente. Deux corrections possibles, a trancher :

- regime tendance = `ib_range_atr_r < 0,4` (IB etroite, 47 a 53 % des barres) ;
- ou regime tendance = `ctx_ib_extension_ratio` au-dela d'un seuil **dont la
  distribution reste a mesurer avant de l'ecrire**.

---

## 5. Ce que la mesure valide dans la proposition de Fable

- **C2-1 momentum de fin de journee** : a garder en tete de liste. Seule hypothese
  a effet documente sur longue periode, testable en niveau A, et jamais essayee.
- **C2-2 fade SD2 avec rejet** : le regime `prix > HVL` est mesure et utilisable
  (avec zone morte). Le seuil `ib_range_atr_r < 0,8` couvre 96 % des barres —
  il ne filtre donc presque rien, a savoir avant de compter dessus.
- **C2-4 retest d'IB** : `ib_range_atr_r < 0,4` couvre 47 a 53 % des barres.
  C'est calibre. Reste que le LIEU de H6 ne rendait que 58 signaux ES sur 40 jours
  — c'est lui le facteur limitant, pas le regime.

---

## 6. Les points ou nous convergeons sans nous etre concertes

1. Le HVL est un **separateur de regime**, pas un lieu.
2. `ib_range_atr` est dans la mauvaise unite et rend H6/H2 non testables.
3. Le filtre de regime n'est pas optionnel : une strategie testee sans regime
   melange deux populations.
4. Les frais sur micro sont le mur, et ils pesent trois fois plus que sur mini.
5. La sortie appartient au setup, pas au protocole.
6. Mesurer le devenir des rejetes — l'entonnoir est en place et branche.

---

## 7. Ce qui reste ouvert, et que ni l'un ni l'autre n'a tranche

- **Aucune source ne mesure l'effet gamma sur NQ** ; tout est SPX/ES. La
  replication ES/NQ reste la seule preuve.
- **La magnitude de l'effet gamma intraday n'est etablie nulle part** en
  peer-reviewed avec un chiffre. Mecanisme solide, ampleur inconnue.
- **`mq_hvl` contre `mq_hvl_0dte`** : a mesurer, pas a choisir a priori.
- **Le momentum de fin de journee s'affaiblit avec le temps** selon au moins une
  replication — prior a tester, pas edge acquis.
- **57 jours contre 947.** Ce que la litterature mesure sur des decennies ne se
  transpose pas mecaniquement a notre lot. C'est ce que notre mission teste, pas
  ce que la litterature garantit.
