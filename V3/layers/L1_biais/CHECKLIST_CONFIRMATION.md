# La checklist de confirmation — liste fermée, comptable, réfutable

**Unité de travail : 15 minutes** (décision Jackson 14/09). Sous 15 min on paie
le bruit, au-dessus on perd la réactivité, et toute la chaîne V3 est déjà
agrégée là.

**Ce document formalise la méthode de Jackson**, telle qu'il l'a décrite :

> *« J'ai déjà mon biais. Je sais que mon prochain trade sera un achat. J'attends
> ma zone. J'arrive dans ma zone, je vérifie que tout est aligné, et une fois
> que ça me le signale, je rentre. Mais pas n'importe où, pas au beau milieu de
> nulle part. »*

Zone → flux → confirmation → trade. Le bot actuel fait l'inverse : H7 tire
**10,9 fois par séance** sur ES alors que les niveaux ne sont touchés que **3
fois**. Il automatise l'impatience, pas la lecture.

Et le coût est chiffré : entrer au niveau **sans confirmation**, c'est un stop
touché dans **85 % des cas sur ES, 90 % sur NQ** (mesure du 14/09, 306 et 244
entrées hypothétiques). **L'écart entre ce plancher et quelque chose de
tradable est exactement ce que cette checklist doit produire.**

---

## 1. POURQUOI UNE CHECKLIST ET PAS UN SCORE

Un score composite a été essayé trois fois dans ce projet. Mesure : le composite
des bots corrèle **rho = +0,0009 (p = 0,69)** sur 217 491 barres, alors que les
features brutes qu'il agrège font **rho +0,0174**. **L'agrégation détruit
l'information.** Et le seul test DSR jamais mené le classe NOGO, battu par son
propre témoin sans biais (PF 1,627 contre 0,988).

Donc : **on ne somme pas, on n'en fait pas un score, et on ne pose AUCUN seuil
aujourd'hui.** On rend un **vecteur** et on le journalise. Les seuils, s'il doit
y en avoir, seront posés au jour 61 par la mesure — pas par la logique.

C'est la même discipline que le devenir : *« il doit être RECALCULABLE »*. Un
vecteur journalisé permet de tester ensuite n'importe quelle combinaison, y
compris « un seul item suffit », que les chiffres ci-dessus rendent plausible.

## 2. LE CONTRAT

Chaque item rend **trois états, jamais deux** :

| état | sens |
|---|---|
| `True` | j'ai regardé, la condition est remplie |
| `False` | j'ai regardé, elle ne l'est pas |
| `None` | **je n'ai pas pu regarder** — donnée absente |

`None` n'est pas `False`. C'est la doctrine fondatrice de V3, et c'est ce qui a
manqué à toutes les générations précédentes : `_get(bar, key, default=0.0)`
transformait une panne en valeur plausible, et c'est ainsi qu'un bug d'échelle a
produit **zéro signal VENTE sur 110 946 barres** pendant deux mois.

Sortie de la checklist :

```python
{"items": {"C1": True, "C2": None, ...},   # le VECTEUR, c'est lui qui compte
 "n_vrais": 4, "n_faux": 3, "n_muets": 3,  # somme toujours = N
 "cote_demande": "long"}                    # le côté que le déclencheur veut
```

**Aucun verdict.** Pas de « confirmé / non confirmé ». La checklist décrit, elle
ne décide pas — tant que la mesure n'a pas dit quel item sert à quoi.

## 3. LES ITEMS

Chaque item est mappé à une colonne qui doit figurer au **registre**
(`V3/conventions.yaml`) avant d'être lue — règle souveraine du 14/09.

| # | ce que Jackson regarde | colonne(s) | état |
|---|---|---|---|
| **C1** | gros intervenants | `big_ask_cluster_*`, `big_bid_cluster_*` | **à vérifier vivant** — 16 features mortes 26 jours, corrigées le 13/04 |
| **C2** | niveau tenu plusieurs fois, avec volume | F23 : `n_tests`, `n_tenues`, `dernier_tenu` | machinerie existante |
| **C3** | couleur up / dn | **`bn_color_up_2`** | GARDER, **rho +0,070 — n°4 du projet** |
| **C4** | swing low, double bottom / top | **`dist_swing_high`** | GARDER, **rho +0,080 — n°1 du projet** |
| **C5** | absorption | `bn_absorb_bid` / `bn_absorb_ask` | GARDER, rho −0,060 / −0,050 |
| **C6** | pression acheteuse / vendeuse | `bn_pressure_bid` | GARDER, rho −0,046 |
| **C7** | prix collé à une déviation VWAP | `dist_vwap_d_sd1u/d`, `sd2`, `sd3` | présentes |
| **C8** | extrême de range (fade) | `range_pos_va`, `dist_cur_vah` / `val` | présentes |
| **C9** | niveau options, GEX, gamma | `dist_mq_hvl`, `gamma_block_long`, `mq_*` | présentes |
| **C10** | contexte d'unité supérieure | 30 et 60 min, **décalées d'une barre** | voir §5 |

**Fait qui mérite d'être dit** : quatre des dix items de Jackson tombent sur les
features les mieux corrélées de tout le projet. `dist_swing_high` est le **n°1**,
`bn_color_up_2` le **n°4**. Sa lecture à l'œil est **mesurablement meilleure que
les composites que trois générations de bots ont construits par-dessus**.

**C11 — pullback** : listé par Jackson, non retenu pour l'instant. Il exige une
définition de « jambe », donc F23, et une jambe n'est connue qu'une fois finie —
risque de look-ahead. À construire avec la lecture par jambe, pas avant.

## 4. CE QUI EST REFUSÉ, ET POURQUOI

**Les figures V / W / M / inversées.** C'est BN V5, **tué le 10/06/2026** :
`5 contrôles Lopez sur 5 en échec`, `n=25` contre 100 exigés, `PF NQ 0,72`, et
surtout **deux trades séparés d'une seconde portaient 54 % des gains** — en les
retirant, le PF passe de **1,08 à 0,50**. Constat écrit : *« patterns V/W/M en
1 min sur futures : non validés par la littérature pro (Bulkowski, Brooks,
Raschke parlent de DAILY sur actions) »*. Ne pas remettre.

**`bn_long_up` / `bn_long_dn`** (« long up bar »). Liste **DROP** du projet.
Attention au piège de nommage : `bn_color_up` est DROP, **`bn_color_up_2` est
GARDER**. Le `_2` n'est pas cosmétique.

**`delta_divergence`.** Mesuré le 14/09 : non nul sur **0,4 % des barres** (ES et
NQ). Jackson la voit peut-être à l'œil ; **la colonne ne la porte pas**. Le
module la déclare lui-même « DORMANT », et `AUDIT_DEAD_FEATURES_RESOLUTION`
affirme le contraire — c'est l'audit qui a tort.

**`new_swing_high` / `new_swing_low`.** Non nuls sur **1,6 %** des barres. Ne pas
les confondre avec `dist_swing_high`, qui est continue et n°1 du projet.

## 5. LE MULTI-UNITÉS — contexte, jamais vote

**Mesuré le 14/09, avec garde anti-look-ahead (`shift(1)` sur chaque unité
supérieure, seules les clôtures déjà passées sont lues) :**

| | 3 unités alignées | 2 sur 3, sans opposition |
|---|---|---|
| ES k=2 | 51,7 % | **52,9 %** |
| ES k=4 | 51,3 % | **54,8 %** |
| NQ k=2 | **47,9 %** | **53,1 %** |
| NQ k=4 | **47,4 %** | **54,3 %** |

**L'alignement COMPLET est pire que l'alignement partiel, sur les quatre
cellules.** Sur NQ il passe sous 50 %. Mécanisme plausible : quand les trois
unités s'accordent, le mouvement est **déjà mûr** — on arrive en retard.

**CONFIRMÉ INDÉPENDAMMENT par le dépôt lui-même**, sur 8 mois et une autre
méthode : `ANALYSE_BOT1_LACUNES_20260520.md:39` mesure **MTF 4/4 → WR 25,4 %**
contre **3/4 → WR 28,5 %**, avec le diagnostic déjà écrit : *« piège
trend-chase late »*. Mesuré en mai, jamais retiré.

### Pourquoi le MTF existant ne doit PAS être réutilisé (audit du 14/09)

| défaut | mesure |
|---|---|
| 40 % du score est **le même nombre copié 4 fois** | `vwap_score` identique bit-à-bit sur 1m/5m/15m/1h — **1019/1019 instants**, ES et NQ. `r(5m,15m) = 0,96` |
| il lit la barre 60 min **non clôturée** | exclure le bucket en cours change le verdict sur **46,5 % ES / 50,1 % NQ** |
| l'hypothèse du code est fausse ×5 à ×50 | `builders.py:1222` dit « rare ~1-5 % » ; mesuré **24,5 % ES / 53,7 % NQ** — sur NQ, « 4/4 » est l'état MAJORITAIRE |
| le seul walk-forward qui l'isole | retirer le boost 4/4 change le PF de **0,01** ; DSR 0,00, **0 fold sur 12** |
| le fix du 08/06 | backtest « REPORTÉ », et son audit J+7 **impossible** — `_v2log.emit` levait une exception avalée, **zéro ligne pendant 3 mois** |
| le front annule le back | `stabilizers.py:107-110` retire l'override, `dashboard.js:1838-1852` le refait — et **le front gagne à l'écran** |

Les trois commentaires qui justifient ce fix citent une mémoire
`feedback_mtf_no_override.md` **qui n'existe pas**.

**Conséquence pour C10 : on ne réutilise rien de ce MTF.** On repart du frame
15 min de V3, on décale explicitement d'une barre, et on ne compte pas les
unités alignées.

Deux conséquences :

1. **C10 ne compte pas les unités alignées.** Il note *dans quelle structure
   d'unité supérieure on se trouve* — un niveau de 60 min est un objet différent
   d'un niveau de 15 min parce que plus de participants l'ont vu. C'est
   structurel, pas un vote.
2. **Le look-ahead est le risque n°1 du MTF.** À 10h07, la barre 60 min de 10h00
   n'est pas close ; la lire revient à voir 53 minutes de futur. Précédent du
   dépôt : corriger un alignement de ce type a fait passer un veto de
   `0W/19L, −1 820 $` à `4W/4L, +127 $` — **1 947 $ d'écart sur un seul
   décalage**. Tout item d'unité supérieure doit être décalé d'une barre.

## 6. LA JOURNALISATION

**Le vecteur entier est écrit sur CHAQUE décision, y compris celles qu'on ne
prend pas.** Sans ça, `PERSONNE` ne produit aucune mesure et les trades écartés
n'existent nulle part — on perd le contrefactuel, et au jour 61 la question
« bloquer était-il juste ? » devient sans réponse.

C'est aussi ce qui rend mesurable ce que Jackson a nommé lui-même comme son vrai
problème : **l'impatience**. Chaque fois que la zone n'est pas atteinte ou qu'un
item manque, c'est écrit. Au jour 61, le prix de chaque clic anticipé est un
chiffre, pas une impression.

## 7. CE QU'ON MESURERA AU JOUR 61

1. **Quel item discrimine, seul.** Les chiffres du dépôt disent que les features
   brutes battent les composites : il faut donc tester chaque item isolément
   avant toute combinaison.
2. **Le compte discrimine-t-il, et est-il MONOTONE ?** Trois escaliers testés le
   14/09 — les crans de B1p, les grades de BotBN, l'alignement MTF — sont
   **tous les trois non monotones**. Ne rien présumer.
3. **De combien la checklist fait-elle baisser le 85-90 % de stops touchés ?**
   C'est l'objectif chiffré du module.
4. **Ce que coûte l'impatience** : résultat des entrées où le vecteur était
   incomplet, contre celles où il était plein.

Unité d'analyse : **la session**, jamais le trade (leçon du 04/07 : PF 1,81 au
niveau trade, aucun t-stat > 2,0 au niveau session). Comparaison ES/NQ
**appariée par jour**.
