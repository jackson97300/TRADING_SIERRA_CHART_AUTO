# BRIEF — Couche L1, le biais

*Cadrage écrit le 06/09, après le scellement de L0. À traiter en parallèle par
Claude Code et Fable, puis à comparer.*

---

## 1. Pourquoi le critère de L0 ne se transpose pas

**Un biais ne rejette pas, il oriente.** Il dit « ce côté est favorisé » ou
« pas d'avis ». Le mesurer par un taux de rejet n'a pas de sens : une couche
qui n'a d'avis que 5 % du temps ne rejette pas 95 % des signaux, elle
s'abstient.

C'est la deuxième fois en une journée qu'un critère se transpose mal. La
première a failli sceller L0 sur une plage arithmétiquement impossible. On
écrit donc le critère de L1 **avant** le code, et on le mesure sur sa propre
grandeur.

---

## 2. Les trois grandeurs à mesurer

### La couverture — quelle part des barres a un biais

Un biais **présent 100 % du temps ne dit rien** : il n'est qu'un habillage du
sens du marché. Un biais **présent 5 % du temps ne sert à rien** : il ne sera
presque jamais consulté. La plage reste à établir **sur la mesure**, pas
d'avance — c'est la leçon de L0, où la plage avait été écrite avant de compter
les portes.

À produire : la distribution de la couverture par jour et par régime, pour les
deux instruments.

### La séparation — le seul chiffre qui dit si le biais a une information

> devenir des signaux **dans** le sens du biais — devenir des signaux **contre**

Avec son intervalle à 95 %, et comparé au **contrôle négatif** (ES −0,057
[−0,210 ; +0,096] ; NQ −0,000 [−0,134 ; +0,134]).

Si la séparation ne sort pas de cet intervalle, **le biais n'informe pas** —
quelle que soit son élégance conceptuelle. C'est la mesure qui décide s'il entre
dans la chaîne, exactement comme le devenir des rejetés a décidé pour les portes
de L0.

Piège à éviter, déjà rencontré : le devenir doit être **signé dans le sens du
trade**, jamais dans celui du marché. Un devenir signé marché est
ininterprétable sur un lot majoritairement short.

### Le coût de l'obéissance — les signaux qu'on aurait fermés

Tout signal **contre le biais** qu'on refuserait est simulé en **trade fantôme
complet** — triple barrière, coûts déduits — comme pour `L0_POSITION_OUVERTE`.
Le mécanisme existe déjà dans `V3/chaine.py`.

C'est la seule façon de savoir si obéir au biais coûte de l'argent. Une couche
qui oriente sans qu'on sache ce qu'elle écarte est une couche qu'on ne pourra
jamais juger — c'est ce qui a tué les trois bots précédents.

---

## 3. Une seule hypothèse d'abord

**B1 seul.** Un biais mesuré vaut mieux que quatre écrits. B4, B5 et B5b
attendent que B1 ait sa couverture, sa séparation et son coût.

Raison : quatre biais écrits ensemble, c'est quatre fois plus d'essais sur le
même lot — et le grid search du 06/09 a montré ce que ça produit
(528 essais → 43 « candidats » → **zéro** après retrait des règles dégénérées).

---

## 4. Ce qui s'applique sans discussion

Repris de L0, et non négociable :

- **Aucun seuil sans sa distribution mesurée**, datée, dans `rapports/`.
- **Données collectées ou dérivées uniquement.** Aucun proxy.
- **Toute décision journalisée** dans l'entonnoir avec son motif.
- **Le contrôle négatif** comme étalon de toute lecture.
- **Un cas nominal obligatoire** dans les tests — « rien ne doit bloquer quand
  tout va bien ». C'est lui qui a trouvé le défaut de `L0_DATA_INSTABLE`.

---

## 5. Ce qu'on refuse de trancher d'avance

La plage de couverture, le seuil de séparation, et le nombre de barres sur
lequel le biais se lit. Les trois s'établissent **sur la mesure**. Les écrire
maintenant reviendrait à refaire l'erreur du critère de L0 — une valeur posée
avant de savoir ce qu'elle gouverne.
