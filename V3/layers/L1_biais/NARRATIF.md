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

### Ce que la mesure a corrigé, avant le code

Première définition : « la barre est à moins de `z_touche` ATR du niveau ».
Mesurée : **38 à 53 % des barres**, soit **quatorze touches par jour** sur la VAH
seule. Normal — la value area contient 70 % du volume : le prix y séjourne, il
ne la teste pas. Une touche une barre sur deux décrit un endroit, pas un
événement.

**Correction par hystérésis** : il faut s'éloigner de `z_reset` ATR pour revenir
tester. Même principe que la zone morte du HVL, qui a fait tomber les bascules
de régime de 10,2 à 1,8 par jour.

| `z_reset` | 0 test | 1 test | ≥ 2 tests | lecture |
|---|---|---|---|---|
| **0,5 ATR** | 30,2 % | 24,6 % | **45,2 %** | **le compteur distingue** |
| 1,0 ATR | 30,2 % | 46,8 % | 23,0 % | se tasse sur 1 |
| 1,5 ATR | 30,2 % | 59,5 % | 10,3 % | booléen déguisé |

**`z_touche` = 0 ATR** (la barre englobe le niveau), **`z_reset` = 0,5 ATR.**
Le critère n'est pas le nombre de touches mais la **discrimination** : un
`n_tests` qui vaut toujours 0 ou 1 ne dira jamais « ce niveau a été défendu
quatre fois ». À 0,5, deux, trois et quatre tests existent dans 45 % des cas.

Effet : de 14 touches par jour à **1,2–1,6** par niveau. ES et NQ donnent 7,6 et
7,4 au total — la normalisation par l'ATR tient, ce qui n'allait pas de soi.

---

## Une FICHE par test, pas un compteur

Compter dit « le niveau a tenu deux fois ». Ça ne dit pas **comment** — et c'est
le comment qui prédit le troisième test. Un trader ne lit pas « VAH tenue 2× »,
il lit : *première défense sur deux fois le volume normal, delta vendeur net,
mèche de 60 % ; seconde sur volume famélique, delta plat — ça faiblit, le
troisième passe.* Wyckoff : **effort et résultat**, à chaque test.

Chaque test produit donc une fiche. Les six dimensions, toutes vérifiées
présentes le 06/09 :

| dimension | colonnes | ce qu'elle dit |
|---|---|---|
| effort | `total_vol`, `rvol_r` | combien il a fallu se battre |
| qui pousse | `delta_pct`, `ask_pct` / `bid_pct` | agression contre le niveau ou dans son sens |
| contexte cumulé | `cvd_sess_r`, `cvd_day` | le delta du jour défend-il ou attaque-t-il |
| forme | `bar_upper/lower_wick_pct`, `finish_delta_pct` | rejet franc ou clôture molle |
| gros ordres | `dist_big_ask/bid_nearest_up/dn`, `max_big_*_vol_in_bar` | défense passive visible dans les prints |
| **résultat** | excursion max dans le sens du rejet, k barres, en ATR | ce que la défense a **produit** |

*Effort sans résultat = faiblesse. C'est la ligne qui compte, et la seule qui ne
soit pas une colonne : elle se calcule.*

**Deux échelles, nommées.** L'effort se lit sur la barre 15 min du test (flux
sommés) ; la mèche et le finish se lisent mieux sur la barre **1 min** qui a
touché — c'est le pont vers L4. La fiche garde les deux.

### Ce qu'il a fallu réparer pour que la fiche existe

Cinq colonnes se perdaient à l'agrégation, dont `ask_pct` et `bid_pct` en
provenance **A**. Et deux ne s'agrègent pas du tout : `ask_pct` et les mèches
sont des **rapports** — prendre la valeur de la dernière minute pour
caractériser quinze minutes est faux. Elles se **reconstruisent exactement** :

```
ask = (total_vol + delta_bar) / 2     identité vérifiée à 5e-05 près
                                       sur 1 378 barres
```

## Ce que la lecture expose — quatre scalaires

Une porte ou une composante ne peut pas lire une liste. La fiche complète va
dans le **snapshot de l'entonnoir** ; `lecture.py` n'expose que :

- `n_tests` — le compte ;
- `defense_derniere` — effort × résultat du dernier test, seuils sur
  distribution ;
- `defense_tendance` — réaction du dernier test rapportée au premier
  (**< 1 = la défense s'use**) ;
- `cvd_cote_defense` — le delta cumulé du jour est-il du côté de la défense.

Plus **la migration du POC** (`poc_migration_dir`, niveau B) : où la valeur se
déplace est une part du récit, pas seulement où le prix est.

## Ce que ça rend mesurable, et qui ne l'était pas

Au lieu de « le 3ᵉ test vaut-il moins que le 1ᵉʳ », on peut demander :

> **le 3ᵉ test après deux défenses qui s'usent finit-il en cassure plus souvent
> que le 3ᵉ après deux défenses franches ?**

C'est une hypothèse de **L3** (rejet au niveau) *et* de **L1** (biais narratif :
au-dessus de la VWAP semaine, testée trois fois par le dessous avec des défenses
qui s'affermissent → long fort). **Les deux couches lisent la même fiche.**

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
