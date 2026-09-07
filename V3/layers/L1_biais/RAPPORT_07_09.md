# L1 — rapport de mesure du 07/09

*Ce qui a été construit, ce qui a été mesuré, et les quatre questions ouvertes.
Aucun chiffre de ce document n'est un verdict : ils sont là pour être
contestés.*

---

## 1. Ce qui existe maintenant

| fichier | rôle |
|---|---|
| `composantes.py` | B1p, B1n, B4, B5, B5b — registre `@composante`, `None` possible |
| `biais.py` | la **série** : B1 candidat → B4 annule → B5 qualifie |
| `seuils.yaml` | tous les nombres, avec les `null` non encore mesurés |
| `test_biais.py` | 18 cas de composante + 6 de série + grep anti-score + test du `null` |
| `mesure_57j.py` | couverture, séparation (IC par jour), coût de l'obéissance |

**La série, pas un score.** B1 seul donne le côté. B4 ne peut qu'annuler, B5
que qualifier `fort`/`faible`. Le cas de test qui le prouve : *B5 contre le
candidat rend LONG faible, jamais SHORT.*

Ma première version faisait `sum(b1, b5, b5b) >= seuil`, avec dans sa
docstring « pas de pondération, chaque règle vaut 1 » — la règle citée sur la
ligne qui la violait. Le danger n'est pas la pondération, c'est **l'addition** :
deux composantes à +1 franchissent un seuil de 2, donc deux presque-riens font
un avis. Le `grep` anti-score existe pour que ça ne revienne pas.

---

## 2. Les quatre mesures, dans l'ordre où elles ont été faites

### 2.1 Le reset hebdomadaire de la VWAP semaine — VALIDÉ

Le point qui pouvait invalider B1 en silence. Si la référence ne se
réinitialise pas, `dist_vwap_w` dérive, le signe se fige, et B1 rend le même
côté pendant des semaines.

| jour | \|dist_vwap_w\| médian (ticks, ES) |
|---|---|
| lundi | **64,5** |
| mardi | 92,7 |
| mercredi | 91,5 |
| jeudi | 141,2 |
| vendredi | **142,4** |

La référence repart près du prix et s'en éloigne. Sept semaines sur huit ont
leur minimum en début de semaine. **B1 lit une vraie VWAP hebdomadaire.**

### 2.2 La zone morte `z1` — deux surprises

`|dist_vwap_w|` en ATR-15m, 60 jours : ES p10 0,49 · médiane **2,13** · p90 5,63.
NQ médiane 2,75.

| `z1` | jours avec avis (ES) | barres | bascules/jour |
|---|---|---|---|
| 0,0 | **60/60** | 100 % | 0,65 |
| 0,5 | **60/60** | 89,5 % | 0,33 |
| 1,0 | **60/60** | 76,1 % | 0,10 |
| 2,0 | 52/60 | 51,6 % | 0,00 |

**Première surprise : la zone morte ne sert pas à ce pour quoi je l'avais
introduite.** Je l'avais mise pour empêcher le ballottement du côté — le
raisonnement du régime gamma, qui basculait 10,2 fois par jour. Ici : **0,65
bascule par jour à `z1 = 0`**. Le problème n'existe pas.

**Seconde surprise : B1-photo a un avis tous les jours.** Il faut monter à
`z1 = 2,0` — la médiane — pour obtenir de l'abstention, au prix de la moitié
des observations.

`z1 = 1,0` est retenu pour la stabilité, **pas** pour l'abstention.

### 2.3 La couverture — HORS PLAGE PAR NATURE

La spec exige moins de 95 % des jours. B1-photo en fait **100 %**.

Ce n'est pas un seuil mal posé : **la composante ne sait pas dire « je ne sais
pas »**. Le prix est toujours d'un côté d'une référence ; le constater n'est
pas orienter.

C'est le premier argument mesuré en faveur de **B1n** : un narratif *peut*
s'abstenir — quand la référence a été cassée sans regain, il rend 0.

### 2.4 La séparation — NÉGATIVE sur ES

| | ES | NQ |
|---|---|---|
| couverture (jours avec avis) | 70 % | 83 % |
| devenir **avec** le biais | **−0,091** (n=165, 29 j) | +0,108 (n=257, 40 j) |
| devenir **contre** | **+0,689** (n=117, 19 j) | +0,368 (n=89, 26 j) |
| **séparation** | **−0,780 ± 0,771** | −0,260 ± 0,543 |
| séparation par hasard | −0,305 | — |

Sur ES, les signaux qui vont **contre** B1 font sept fois mieux que ceux qui le
suivent. **Suivre le biais coûterait.** Sur NQ, zéro est dans l'intervalle.

*(Couverture 70 % ici contre 100 % en §2.2 : la §2.2 compte les jours où une
barre a un avis, la §2.4 le jour où le biais est lu — une fois, tôt. Le premier
jour du lot n'a pas d'ATR de veille, et quelques journées n'ont pas de
`dist_prev_*`.)*

---

## 3. Les défauts trouvés — dont trois qui sont les miens

### 3.1 Mon verdict affichait « ORIENTE » pour une séparation négative

Il testait `abs(separation) - ic > 0` **sans regarder le signe**. Un contrôle
qui valide l'amplitude et oublie la direction.

**C'est la troisième fois en deux jours que je produis la même forme de bug** :
rendre `False` là où il fallait `None` (`L0_VIX_REGIME`), valider une magnitude
sans sa direction (ici). À chaque fois le code tourne, la sortie a l'air
normale, et elle dit l'inverse de la vérité.

Corrigé : une séparation négative rend **ORIENTE À L'ENVERS**.

### 3.2 La couverture était à 0 % — et la correction évidente était une fuite

`atr_barre` est NaN avant la 7ᵉ barre (`min_periods=7`). Le biais se lit à
9h30 ; l'ATR agrégé n'existe qu'à 11h15. B1 rendait `None` partout.

La correction évidente — lire le biais à `i = 7` — **est une fuite** : on
normaliserait l'ouverture par la volatilité de la matinée qui la suit.

Retenu : **l'ATR de la veille**, ce qu'un desk utilise à l'ouverture.

### 3.3 Deux ATR commodes auraient donné un facteur 10,7

`atr` et `atr_14m` sont remplis dès la première barre. Médianes sur une journée
ES :

| | valeur | rapport à `atr_barre` |
|---|---|---|
| `atr` | 65,29 | **6,03** |
| `atr_14m` | 7,07 | **0,62** |
| `atr_barre` | 10,86 pts | 1 — formule connue |

Ni 4 (conversion ticks/points), ni 1. **Trois ATR coexistent et je ne connais
la formule que d'un seul.** Normaliser par `atr_14m` donnait **10,7×** d'écart.

### 3.4 Trois colonnes ne survivaient pas à l'agrégation

`data_quality_flag`, `dist_vwap_w`, `vix_regime` — plus quatre niveaux
(`dist_cur_vpoc`, `dist_prev_*`).

Conséquences : `L0_DATA_INSTABLE` aurait **fermé la séance entière** en live ;
`L0_VIX_REGIME` rendait `False` en ne lisant rien ; et **`biais()` rendait 0 en
permanence — B1 n'existait pas.**

`lecture.verifier_colonnes` déclare maintenant les dépendances de chaque
couche. À son premier lancement il a trouvé la troisième.

---

## 4. Les quatre questions pour Fable

### Q1 — La mesure porte sur un seul déclencheur

| | ES avec/contre/sans | part « avec » |
|---|---|---|
| H3 | 10 / 12 / 13 | 28,6 % |
| **H6** | **0 / 0 / 0** | — |
| **H7** | **155 / 105 / 80** | 45,6 % |
| **H8** | **0 / 0 / 0** | — |

**H6 et H8 ne produisent aucun signal. H7 en produit 91 %.** On mesure sweep +
reclaim, pas les quatre hypothèses. Faut-il réparer H6/H8 avant de conclure quoi
que ce soit sur L1 ?

### Q2 — La séparation négative : signal ou artefact ?

La tentation est d'inverser B1. C'est exactement la forme d'un faux positif :
un signe qui s'inverse, sur 60 jours qui ont déjà servi, un seul instrument, et
une histoire qui se raconte bien après coup (« un fade contre la tendance de
fond est le setup normal »).

Mais l'écart est grand (−0,78 contre un hasard à −0,305) et cohérent avec la
nature des déclencheurs. **Comment le tester sans data mining ?**

### Q3 — La couverture de B1p est-elle rédhibitoire ?

Une composante qui a un avis 100 % du temps peut-elle entrer en chaîne comme
*candidat*, si la série la corrige ensuite ? Ou faut-il l'écarter d'emblée et
n'écrire que B1n ?

Ma lecture : l'écarter serait prématuré — elle reste la **référence** contre
laquelle le narratif se mesure. Mais elle ne peut pas être `b1_actif`.

### Q4 — Deux couvertures différentes dans le même rapport

70 % (biais lu une fois par jour) contre 100 % (barres avec avis). Laquelle est
« la couverture » au sens de la spec ? La première me paraît juste — un biais
est une décision quotidienne — mais la spec dit « part des jours avec
`cote ≠ AUCUN` », ce qui ne tranche pas entre les deux.

---

## 5. Ce qui reste avant que L1 puisse être scellée

1. **F23 dans `recalc.py`** + test au tick sur deux journées — prérequis de
   B1n, donc du duel.
2. **`lecture.py` bloc L1** — pour l'instant `mesure_57j.py` construit le dict
   à la main.
3. **B4 réel** — elle demande les deux instruments alignés sur la même barre ;
   le chargement est par instrument. *Manque de plomberie, pas de donnée.*
4. **B5 à 10h30 ET** — lue à chaque barre aujourd'hui.
5. **Le duel B1p / B1n**, tranché par la séparation.
6. **Les seuils encore `null`** : `defense_forte`, `piege_volume_min`.

---

## 6. Ce qui est acquis et ne se rejoue pas

- Le reset hebdo est validé : B1 lit une vraie référence.
- `z_touche = 0` et `z_reset = 0,5 ATR` sont mesurés (F23).
- L'ATR de référence du biais est celui de la veille, et le raisonnement est
  écrit dans le code.
- La série remplace le score, avec un test qui l'interdit.
- **B1-photo ne peut pas être `b1_actif`** : sa couverture est hors plage par
  nature, et sa séparation est négative ou nulle sur les deux instruments.

*Rien dans L1 ne touche le bot : elle n'a aucun accès à `chaine.appliquer`, par
construction.*
