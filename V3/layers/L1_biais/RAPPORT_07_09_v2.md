# L1 — rapport v2, après l'audit du 07/09

*La v1 est archivée en `rapports/biais_57j_v1_PERIMEE.csv`. Elle était fausse
sur un point : bootstrap par jour, contrôle négatif à un tirage, IC supposant
l'indépendance de deux groupes qui partagent les jours.*

---

## 1. L'attendu, écrit avant la relance

| attendu | résultat |
|---|---|
| l'IC contient zéro sur les deux instruments | **CONFIRMÉ** |
| le test sans déclencheur est nul | **DÉMENTI** |
| l'effet ES vit dans le tercile « loin » | **DÉMENTI** |

---

## 2. Ce que les corrections ont changé

| | v1 | v2 |
|---|---|---|
| unité du bootstrap | jour (60) | **bloc semaine (13)** |
| IC de la différence | `hypot`, groupes supposés indépendants | **apparié** |
| contrôle négatif | 1 tirage | **1 000, côté par semaine** |
| séparation ES | −0,780 ± 0,771 | **−0,414 ± 0,626** |
| verdict | « ORIENTE » | **n'informe pas** |

**La séparation de −0,78 était un artefact.** Avec la bonne unité statistique,
elle tombe à −0,414 et son intervalle contient zéro. L'audit avait raison sur
les trois défauts, et sur leur conséquence : un intervalle trop étroit fait
sortir du bruit ce qui n'en sort pas.

---

## 3. Le résultat, et il n'était pas attendu

**Le test sans déclencheur n'est pas nul.**

| | séparation | IC | semaines |
|---|---|---|---|
| ES | **−0,707** | ± 0,560 | 12 |
| NQ | **−0,516** | ± 0,476 | 13 |

Rappel de ce que mesure ce test : devenir d'un **long hypothétique sur toutes
les barres cash**, les jours où B1 dit LONG, moins les jours où il dit SHORT.
Aucun déclencheur n'intervient.

Si B1 informait, le chiffre serait **positif** : les jours LONG, un long
gagnerait. Il est négatif sur les deux instruments, et son intervalle exclut
zéro dans les deux cas.

### Ce que ça veut dire, et ce que ça ne veut pas dire

**Ça ne veut pas dire « B1 est à l'envers, il faut l'inverser ».**

La lecture la plus économique est celle que l'audit proposait, mais un cran
plus profond : ce n'est pas le déclencheur qui crée l'effet — il survit quand
on les retire tous — c'est **la réversion vers la VWAP semaine elle-même**. Une
VWAP est une moyenne pondérée par le volume ; quand le prix s'en éloigne, il y
revient. À cinq heures d'horizon (20 barres de 15 min), cette réversion domine.

Autrement dit : **`dist_vwap_w` n'est pas un biais directionnel, c'est une
mesure d'extension**, et l'extension est *mean-reverting*. C'est cohérent avec
le tercile « loin » de NQ (−0,832), même si ES ne réplique pas.

### Trois réserves

1. **Douze à treize blocs.** L'IC est large, et il l'est honnêtement.
2. **Quinze comparaisons affichées.** À 5 %, une sort par hasard. Ici deux
   sortent, dans le même sens — plus convaincant qu'une seule, mais **ES et NQ
   sont corrélés à ~90 %** : ce ne sont pas deux tests indépendants.
3. **C'est le lot qui a déjà servi.** Tout ce qui s'y découvre est une
   hypothèse, jamais un résultat.

---

## 4. Ce qui est décidé, et ce qui ne l'est pas

**Décidé :**

- **B1-photo ne peut pas être `b1_actif`.** Sa séparation n'informe pas, et
  quand un effet apparaît il est du mauvais côté.
- **Rien n'est inversé.** Inverser B1 sur les 60 jours qui l'ont produit, c'est
  `optimal_config.json`. La règle tient même — surtout — quand le résultat
  arrange.

**Pré-enregistré pour l'ombre, en observation, écrit avant mardi :**

> **H-EXT** — la distance à la VWAP semaine prédit une réversion à 20 barres.
> Mesure : devenir d'un long hypothétique, jours `dist_vwap_w < 0` contre jours
> `> 0`, sur les jours 61 et suivants. Attendu si l'effet est réel : séparation
> négative, IC excluant zéro, sur les deux instruments.

Elle sera lue au jour 61, sur des jours que personne n'a vus. C'est la seule
façon de savoir si ce qu'on vient de voir existe.

**Non tranché :**

- H6 et H8 ne produisent **aucun signal** — seuils hors distribution ou
  colonnes absentes, même diagnostic qu'au cycle 1.
- B1n n'existe pas encore : F23 est à construire.
- B4 demande les deux instruments alignés sur la même barre.

---

## 5. Les corrections de méthode qui restent acquises

`V3/stats.py` porte les trois, et elles serviront à toutes les couches :

- **bootstrap par bloc**, l'unité étant celle de la grandeur mesurée — la
  semaine pour un biais hebdomadaire ;
- **bootstrap apparié**, parce que `avec` et `contre` partagent les jours en
  sens opposés ;
- **contrôle négatif comme distribution**, 1 000 tirages, avec la même
  persistance que la vraie grandeur.

Et un test de forme dans `test_biais.py` : **« même magnitude, signe opposé »
doit changer le verdict.** Ajouté après la troisième occurrence de la même
faute — un contrôle qui valide l'amplitude et oublie la direction.
