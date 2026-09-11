# PRÉ-ENREGISTREMENT DU CYCLE 2 — écrit le 12/09/2026, avant tout résultat

> **DÉCLARATION D'HONNÊTETÉ, à lire en premier.**
> Ce document est écrit le **12/09/2026**, au jour **4 sur 61** de la campagne
> en cours. La sélection des déclencheurs repose **uniquement sur leur
> fréquence de déclenchement** — un comptage de tirs. **Aucun devenir n'a été
> consulté** : ni `pnl_atr`, ni `issue`, ni un taux de réussite, ni le résultat
> d'un seul signal. Le verrou `V3/devenir.py` refuse cette lecture jusqu'au
> jour 61, et il a été posé le même jour que ce document.
>
> Un pré-enregistrement dont on ne peut pas prouver qu'il précède les résultats
> ne vaut rien. Celui-ci est gelé par un commit horodaté, publié sur le miroir,
> et son hash est la preuve de sa date.

---

## 1. Pourquoi ce document existe

Les quatre hypothèses de la campagne en cours ont été choisies sur une
intuition de qualité, **jamais sur leur taux de déclenchement**. C'est la cause
directe de la sous-puissance que le projet assume depuis le début : H6p a
besoin d'environ **160 jours** pour atteindre un échantillon de 40, et personne
ne le savait au moment de la choisir.

Quatre jours de campagne viennent de produire le chiffre qui manquait. Il ne
dit rien de la qualité des déclencheurs — il dit **quand on pourra les juger**.
C'est la différence entre « on espère avoir un échantillon » et « on sait quand
on l'aura ».

## 2. Ce qui a été mesuré, et ce qui ne l'a pas été

**Mesuré** : le nombre de signaux uniques par déclencheur sur les jours 1 à 4
(08 au 11/09/2026), lus dans `LOGS/barrieres/`, comptés par `snapshot_id`
distinct — un signal, pas trois lignes de barrières.

**Pas mesuré, et volontairement** : tout ce qui touche au devenir.

### Fréquence observée et projection à 60 jours

L'intervalle est un intervalle de Poisson exact à 95 %. Quatre jours sont une
base étroite pour estimer un taux, et l'intervalle le dit honnêtement.

| Déclencheur | n (4 j) | par jour | N sur 60 j (IC 95 %) | atteint N = 40 ? |
|---|---|---|---|---|
| `ED10_BUY_CVD_DIVERGENCE` | 7 | 1,75 | 42 à 216 | **oui, même au pire** |
| `C2_80PCT` | 4 | 1,00 | 16 à 154 | possible |
| `ED04_BUY_VPOC_RECLAIM` | 3 | 0,75 | 9 à 132 | possible |
| `C2_EOD` | 3 | 0,75 | 9 à 132 | possible |
| `ED05_SELL_GEX_REJECTION` | 2 | 0,50 | 4 à 108 | possible |
| `ED11_SELL_IB_BREAK_DOWN` | 2 | 0,50 | 4 à 108 | possible |
| `ED03`, `ED06`, `ED12` | 1 | 0,25 | 0 à 84 | possible |
| `H6p` (gelée, pour mémoire) | 1 | 0,25 | 0 à 84 | possible |

**Un seul déclencheur atteint N = 40 même à la borne basse de son intervalle.**
Tout le reste est « possible », ce qui veut dire « on ne sait pas ». C'est la
lecture honnête de quatre jours, et elle est beaucoup plus sobre que le tableau
des moyennes seul.

### Deux contrôles qui conditionnent la sélection

**Ils ne se recouvrent pas.** Sur 23 barres portant un signal, 2 seulement en
portent plusieurs. Les neuf déclencheurs sont neuf phénomènes distincts, pas un
seul sous neuf noms. C'est la règle 4 de `LECTURE_JOUR_61` vérifiée, et cette
fois négative : en retenir trois ne compterait pas trois fois la même chose.

**La structure est saine.** 25 signaux, 12 sur ES et 13 sur NQ, répartis de 9 h
à 15 h ET. Pas de concentration sur une heure ni sur un instrument, ce qui
aurait trahi un artefact plutôt qu'un déclencheur.

## 3. Les déclencheurs pré-enregistrés

### 3.1 Rang A — `ED10_BUY_CVD_DIVERGENCE`

- **Hypothèse** : ce déclencheur produit une espérance par signal différente de
  zéro, barrières B-ATR, sur le cycle 2.
- **Sens** : long uniquement (le déclencheur est mono-directionnel par
  construction).
- **N visé** : 40 signaux. Projection : atteint vers le **jour 23**, et vers le
  jour 57 à la borne basse de l'intervalle.
- **Règle d'arrêt** : lecture au **jour 61 du cycle 2**, jamais avant, quel que
  soit l'état de l'échantillon. Aucune lecture anticipée, aucun arrêt sur
  résultat favorable.
- **Si N < 40 au jour 61** : déclaré sous-puissant, lu **descriptivement**
  (nombre de signaux, heures, répartition par instrument), **aucune conclusion**
  sur l'espérance. Pas de prolongation décidée après avoir vu le résultat.

### 3.2 Rang B — `C2_80PCT`

Mêmes règles, avec deux différences assumées :

- **Sens** : les deux (le déclencheur tire long et short).
- **N visé** : 40. Projection 60 en moyenne, mais **16 à la borne basse** :
  l'échantillon n'est **pas garanti**, et c'est écrit ici avant de courir.

### 3.3 Rang C — `ED04_BUY_VPOC_RECLAIM`

Mêmes règles. Projection 45 en moyenne, **9 à la borne basse**. Retenu parce
que son coût est nul au-delà de la correction pour tests multiples, et parce
qu'un troisième déclencheur indépendant vaut mieux qu'un seul si l'un d'eux
s'avère muet.

### 3.4 Explicitement NON retenus

`ED05`, `ED11`, `ED03`, `ED06`, `ED12` et les quatre gelées. Non pas parce
qu'ils seraient mauvais — **on n'en sait rien, et on ne le saura pas** — mais
parce que leur fréquence ne permet pas d'espérer un échantillon lisible en un
cycle. Les écarter maintenant, sur la fréquence seule, est la seule façon de ne
pas les écarter plus tard sur un résultat.

## 4. Correction pour tests multiples

Neuf déclencheurs ont été **regardés**, trois sont **retenus**.

La sélection porte sur la fréquence, qui est indépendante du devenir : en toute
rigueur elle ne gonfle pas le taux de faux positifs. Le document adopte malgré
tout la correction la plus **conservatrice** : **Bonferroni sur 9**, soit un
seuil de **α = 0,05 / 9 ≈ 0,0056** par déclencheur.

Raison : la fréquence a été estimée sur les mêmes journées que celles qui ont
révélé l'existence de ces déclencheurs, et l'indépendance parfaite entre
fréquence et devenir est une hypothèse, pas une mesure. Être conservateur coûte
peu ici et rend l'argument inattaquable. Le 28 avril, un audit non corrigé a
annoncé 14 à 19 points de gain et reçu cinq NOGO sur cinq.

**Les quatre jours ayant servi à la sélection sont exclus du cycle 2.** Les
données qui choisissent une hypothèse ne peuvent pas la tester.

## 5. Ce que ce document interdit à son auteur

- Modifier un seuil, un sens ou un N après avoir vu le moindre résultat.
- Ajouter un déclencheur en cours de cycle 2.
- Lire un devenir avant le jour 61 — le verrou `V3/devenir.py` le refuse, et le
  contourner exige d'écrire `force=True` avec un motif, dans le code, relisible.
- Prolonger un cycle parce que l'échantillon manque **et** que le résultat
  partiel est encourageant. Si l'on prolonge, c'est décidé avant de regarder.

## 6. Ce qui reste ouvert, et qui doit être tranché avant le démarrage

- La date de démarrage du cycle 2, qui dépend de la fin du cycle 1 (jour 61,
  soit le 03/12/2026 au calendrier prévu).
- La définition exacte de l'espérance testée : par signal, en multiples d'ATR,
  barrières B-ATR — à confirmer, c'est la convention du cycle 1.
- Le ré-examen de la fréquence au jour 20 et au jour 40 du cycle 1 : si un
  déclencheur retenu s'effondre, il reste retenu, et le document le dira. On ne
  réécrit pas un pré-enregistrement, on l'annote.

---

*Écrit le 12/09/2026 au jour 4 sur 61. Aucun devenir consulté. La date fait foi
par le commit et par le hash du miroir.*
