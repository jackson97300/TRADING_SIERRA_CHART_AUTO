# MISSION CYCLE 2 — pre-enregistrement du 06/09/2026

**Ecrit AVANT de lancer. Rien ici ne sera retouche apres avoir vu un resultat.**
Ce qui naitra de la lecture ira dans `NEXT_CYCLE.md`.

Cycle 1 : `mission-phase2-v1`, six hypotheses, **zero survivante**. Verdicts et
causes dans `NEXT_CYCLE.md`. Les 16 jours scelles (42-57) n'ont pas ete ouverts
et **ne le seront pas dans ce cycle non plus**.

---

## 0. Ce que ce cycle est, et ce qu'il n'est pas

**C'est un SECOND REGARD sur les memes 40 jours.** Il est declare comme tel.
Apres lui, plus de troisieme regard sur ce lot : seulement les jours qui
s'ajoutent. C'est la regle posee le 06/09 avant le cycle 1, et elle tient.

**Attendu pre-enregistre : 0 a 1 survivante.** Trois des quatre hypotheses
ci-dessous sont annoncees **non testables avant de tourner** — leur
dimensionnement est mesure plus bas. La seule qui peut conclure est H3-VPOC.

**Bonferroni 0,05 / 4.** On garde /4 bien que trois soient annoncees mortes :
compter moins parce qu'on prevoit un echec reviendrait a s'accorder un seuil
plus facile sur celle qui reste.

---

## 1. Les quatre hypotheses

### H3-VPOC — la barriere par famille *(la seule qui peut conclure)*

**Origine** : constat 0.1, ecrit **avant** le cycle 1 — *« si les retours a la
valeur meurent sur la barriere et gagnent sur leur sortie naturelle, c'est le
resultat le plus utile du cycle, et la barriere par famille devient l'hypothese
du cycle suivant »*. Elle n'est donc pas choisie apres coup.

**Mesure qui la motive** : H3 atteint le VPOC ou la VWAP **66,7 %** des fois
avant la barriere de continuation (N = 93), et meurt quand meme.

| | |
|---|---|
| LIEU et REACTION | **identiques a H3 du cycle 1**, sans un caractere de changement |
| TP | le **VPOC courant** est atteint (`dist_cur_vpoc` change de signe) |
| SL | **-1,0 ATR-5m**, inchange |
| expiration | **20 barres**, inchangee |

**Une seule chose change : la cible.** C'est ce qui rend la comparaison avec le
cycle 1 lisible — tout ecart s'impute a la barriere, a rien d'autre.

**Ce qu'il faut attendre, et ne pas se raconter** : une cible plus proche
encaisse moins par trade. Le taux de reussite montera mecaniquement ; l'esperance
peut ne pas suivre. Les frais, eux, ne bougent pas : 2,82 $ sur MNQ, 4,32 $ sur
MES, converti a chaque trade avec l'ATR de la barre.

### H2' — regime recalcule *(annoncee non testable)*

Identique a H2 du cycle 1, sauf le regime : `ib_range_atr_r < 0,8`
(`recalc.ib_range_atr_r`, points/points) au lieu de la colonne livree, qui
divise des ticks par des points.

Dimensionnement mesure : lieu 143 ES / 120 NQ, regime corrige 141 / 119 — le
regime ne coupe presque plus. Mais au cycle 1 la **reaction** ramenait 27 a 3.
Attendu : quelques dizaines de signaux au mieux, sous le seuil de 40.

### H6' — regime recalcule *(annoncee non testable)*

Identique a H6, regime `ib_range_atr_r < 0,4`.

Dimensionnement mesure : lieu 58 ES / 65 NQ, avec le regime corrige **37 / 35**.
Sous 40 **avant meme** d'appliquer la reaction. Le regime corrige fait passer la
couverture de 0,13 % a 56 % des barres, mais le lieu lui-meme est trop rare sur
40 jours.

### H8' — seuils recalibres sur leur distribution *(annoncee non testable)*

Identique a H8, avec `rvol_r >= 1,8` et `|delta_pct| >= 0,18` — le p90 mesure de
chaque colonne, au lieu de 2,0 et 0,30 qui etaient hors distribution
(`|delta_pct|` : mediane 0,069, p90 0,175).

Dimensionnement mesure, tous seuils confondus :

| seuils | ES | NQ |
|---|---|---|
| rvol >= 2,0 ; delta >= 0,30 (cycle 1) | 0 | 0 |
| rvol >= 1,8 ; delta >= 0,18 | 3 | 3 |
| rvol >= 1,5 ; delta >= 0,15 | 8 | 7 |

**Ce n'est pas un seuil a corriger, c'est une conjonction impossible** : un rvol
eleve, un delta fort et un finish contraire ne coexistent presque jamais. Elle
est lancee pour que ce soit ecrit noir sur blanc, pas parce qu'on espere.

---

## 2. Ce qui ne change pas

Fenetre RTH 9h30-16:00 ET. Barres 5 min. Entree a l'ouverture de t+1.
Un signal par franchissement, remise a zero a la frontiere de journee.
Planchers en ticks : proximite `max(0,10 ATR, 2 t)`, retest `max(0,15 ATR, 3 t)`.
Donnees collectees uniquement — ni proxy, ni scraper.
Recherche jours 1-40. **Scelles 42-57 : fermes.**

Criteres de survie : N >= 40 par instrument, esperance nette > 0, >= 5 jours
distincts, aucun jour portant > 60 % du gain, >= 4/5 blocs de 8 jours
calendaires positifs, bootstrap par jour p < 0,05/4, robustesse +/-30 %.

**Un seul assouplissement, motive et ecrit d'avance** : le critere
« esperance > 0 sur les DEUX instruments » devient « sur au moins un instrument
dont le cout mesure est inferieur a 10 % de son ATR-5m ». Seul **NQ** y
satisfait (7 % contre 30 % sur ES). La raison est arithmetique et mesuree
(`NEXT_CYCLE.md`, critere d'arret), pas opportuniste : sur MES un aller-retour
coute 30 % de l'ATR-5m, aucun setup ne peut survivre a cela.

---

## 3. Ce que ce cycle decide

**Si H3-VPOC passe** : premier edge mesure du projet. Il entre en mode ombre, pas
en execution.

**Si elle ne passe pas** : il n'y a pas d'edge directionnel intraday 5 min
exploitable dans ces 40 jours. On passe a l'horizon **15 minutes** — l'ATR croit
en racine du temps, le cout relatif tombe de 7 % a 4 % sur MNQ et de 30 % a 18 %
sur MES. C'est le dernier essai sur ce lot.

**Date limite : 20/09/2026.**
