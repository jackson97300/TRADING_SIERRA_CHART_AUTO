# F23 — le narratif : ce que le prix a fait de ses références

*Écrit le 06/09, avant le code. Quatre mots, quatre formules.*

---

## Le trou que ça comble

Chaque barre est aujourd'hui jugée **isolément**. Le système ne sait pas qu'un
niveau a été défendu quatre fois. La donnée est pourtant chargée en mémoire au
moment de la décision : `vah_touches_20b`, `retest_high_count` sont dans
l'agrégation — **et aucune couche ne les lit**.

> *« Des fois on trade un niveau qui a été défendu plusieurs fois et on ne le
> sait pas. »*

C'est l'intuition du dashboard. Elle n'a jamais été un chiffre.

---

## Pourquoi on recalcule au lieu de lire les colonnes C++

`vah_touches_20b` compte sur **20 barres de 1 minute** — vingt minutes de
mémoire, pas la journée. Et sa définition de « touche » est dans le C++, pas
écrite. Un biais narratif a besoin de compteurs **depuis l'ouverture de
session**, avec une définition qu'on peut lire et contester.

Lire la colonne C++ à la place serait un **proxy à fenêtre inconnue** — la règle
qui a fait retirer `mq_gamma_condition`.

C'est la même famille dont L3 aura besoin pour distinguer le premier test du
troisième. **On la construit une fois, elle sert aux deux couches.**

---

## Les quatre définitions

Sur barres **15 min**, clé de **session**, niveaux en provenance **A**
(`dist_cur_vah`, `dist_cur_val`, `dist_cur_vpoc`, `dist_prev_vah`,
`dist_prev_val`, `dist_prev_vpoc`) — vérifiés par identité, pas seulement
plausibles.

| mot | formule |
|---|---|
| **touche** | l'écart entre la barre et le niveau ≤ `z_touche` ATR-15m, où l'écart vaut `\|dist\| × tick − (high − low) / 2` |
| **tenue** | la barre **suivante** clôture du côté d'où le prix venait |
| **cassure** | **deux** clôtures 15 min consécutives de l'autre côté |
| **regain** | une cassure, puis un retour avec tenue |

La cassure à deux clôtures est l'**acceptation** de Dalton — la même règle que
S-4. Une seule clôture de l'autre côté est un dépassement, pas une acceptation.

**`z_touche` se pose sur la distribution mesurée**, jamais décrété. C'est écrit
dans `seuils.yaml` avec sa distribution à côté : quatre seuils hors distribution
ont déjà rendu des hypothèses non testables cette semaine.

---

## Ce que la lecture expose

Par niveau, et rien de plus — quatre mots, pas quinze états :

- `n_tests_niveau` — combien de fois testé depuis l'ouverture
- `etat_niveau` ∈ {`tenu`, `casse`, `regagne`, `intact`}
- `barres_depuis_test` — l'âge du dernier test
- `signal_meme_lieu_recent` — un déclencheur a-t-il échoué à ≤ 0,2 ATR de ce
  lieu depuis l'ouverture ?

Plus **la migration du POC** (`poc_migration_dir`, `ctx_poc_migration_10`, niveau
B) : où la valeur se déplace est une part du récit, pas seulement où le prix est.

---

## L'entonnoir ne change pas

Il reste **append-only et sans état** — c'est ce qui le rend fiable. On ne relie
pas les décisions entre elles dans le journal.

**La mémoire vit dans la lecture.** `signal_meme_lieu_recent` se lit dans
l'entonnoir du jour **sans y écrire**. Chaque ligne porte alors ces champs comme
snapshot : la mémoire est **dans** la décision, pas **entre** les décisions.

---

## Comment on saura si ça sert

Séparation de **B1-photo** contre séparation de **B1-narratif**, sur les mêmes
57 jours, les mêmes signaux, avec le contrôle négatif comme étalon (biais tiré
au sort par jour).

- **N'améliore pas hors bruit** → B1 reste une photo, les compteurs restent
  journalisés en observation. Ils serviront à L3 de toute façon.
- **Améliore** → L1 change de nature, et c'est une mesure qui le dit, pas une
  intuition.

---

## L'ordre, et pourquoi il ne se négocie pas

1. les définitions dans `seuils.yaml`, avec leur distribution ;
2. F23 dans `recalc.py`, avec **test au tick sur deux jours** ;
3. `lecture.py` ;
4. la mesure **avec / sans** ;
5. **seulement ensuite**, B1.

Le narratif **avant** B1, mesuré avec et sans — pas après. Un biais écrit
d'abord et enrichi ensuite ne se compare plus à rien : on ne saurait pas si
l'amélioration vient du récit ou du réglage qui l'accompagne.
