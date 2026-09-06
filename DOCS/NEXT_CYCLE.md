# NEXT_CYCLE — ce qui attend le cycle suivant

Ouvert le 05/09/2026, avant le tag `mission-phase2-v1`.

**Regle** : toute idee nee en REGARDANT les resultats de la mission va ici, pas
dans `MISSION_PHASE2.md`. Le fichier de mission est fige au tag ; celui-ci ne
l'est pas. C'est la seule frontiere qui separe une recherche d'une peche.

---

## Chantiers identifies pendant la phase 1

### Recalculs manquants

**Les swings, pour le biais B2 complet.** `dist_swing_high`, `dist_swing_low`,
`swing_range_ticks` et `bars_since_last_swing_*` sont utilisables mais donnent
la distance aux DERNIERS swings, pas leur SEQUENCE. La structure HH/HL demande
deux niveaux consecutifs et leur ordre — c'est un compteur a construire (F23),
pas une colonne existante. En attendant, B2 s'ecrit en version simple : « prix
au-dessus du dernier swing high 4h ». Version complete au prochain cycle.

**`initial_balance` et `rvol` groupent par date UTC**, pas par cle de session.
En seance cash les deux coincident ; le jour ou le noyau passe en 24 h, il
faudra les passer sur `session_sess`. Sans quoi une IB de session asiatique
serait rattachee au mauvais jour.

### Donnees a recuperer

**Les VA historiques, exportees de Sierra.** VPOC, VAH et VAL ne se recalculent
pas depuis les barres 1 min : il y faut la distribution du volume par prix, que
nous ne collectons pas. Mesure : un VPOC approxime en repartissant le volume de
chaque barre sur sa plage `[low, high]` s'ecarte de 106 ticks en mediane sur NQ,
13 sur ES. Mais Sierra garde les ticks dans ses `.scid` et recalcule
l'historique : une passe unique d'export (Volume Profile en RTH, puis
`Write Bar and Study Data to File`) rendrait les VA justes sur les 51 jours.

**Le noyau 24 h.** La reduction ne tourne que sur la seance cash (~381 barres
par jour). `dist_asia_*` et `dist_london_*` ne sont pas recalculables dans ce
perimetre — leurs barres ne sont pas en memoire. Un run `--tout` donnera un
second noyau, avec d'autres redondances.

### Dette technique

**Le C++ suppose que `sc.BaseDateTimeIn` est en UTC**, ce qui n'est vrai que
parce que le fuseau global de Sierra l'est. Tant que cette hypothese tient, le
fuseau global ne peut pas etre change — et la dette DST doit etre payee a la
main deux fois par an dans les session times. Corriger le C++ pour convertir
depuis le fuseau du graphique lever ait cette contrainte. Chantier de
production : recompilation, validation de parite sur les horodatages, accord
explicite de Jackson.

**`bars_since_boot`** est la seule colonne A/B sans famille. Compteur technique,
sans famille metier : a exclure explicitement plutot qu'a ranger.

### Correctif C++ — defauts d'initialisation hors domaine (06/09/2026)

**A faire le jour ou le VPS est touche, avec le fix `direction()`** — recompilation Sierra requise,
donc a grouper.

`DMP_Transform.h:1355-1390` : remplacer par `DMP_INVALID` tout defaut qui appartient au domaine de
la variable. Neuf champs concernes ; le seul dont la panne est deja mesuree est `day_type`
(fige a 2.0 sur tout le RTH, 33 jours ES / 29 NQ sur 53), mais les huit autres sont a une panne de
module de faire la meme chose sans rien qui le signale :

```
f.open_zone       = 4.0f   ->  DMP_INVALID
f.day_type        = 2.0f   ->  DMP_INVALID
f.profile_shape   = 0.0f   ->  DMP_INVALID
f.profile_skew    = 0.0f   ->  DMP_INVALID
f.poc_position    = 0.5f   ->  DMP_INVALID
f.volume_imbalance= 1.0f   ->  DMP_INVALID
f.poc_separation_ticks = 0.0f -> DMP_INVALID
f.rvol            = 1.0f   ->  DMP_INVALID
f.rvol_zscore     = 0.0f   ->  DMP_INVALID
```

Modele deja present deux lignes plus bas : `f.profile_hvn_dominant = DMP_INVALID`.

**Prealable cote Python** : tout consommateur de ces colonnes doit gerer `DMP_INVALID` avant le
deploiement, sinon le correctif transforme un mensonge silencieux en `NaN` bruyant au milieu de la
prod. Grep des consommateurs a faire d'abord.

**Cause amont a traiter aussi** : le « FIX #2 day_type progressif intra-session », note TODO dans
`DATA_SOURCES_V5.md:237` le 19/05 et jamais livre. `DMP_INVALID` rendra la panne visible ; il ne la
reparera pas.

**Regle** : `CONVENTIONS.md` §3.1. **Incident** : `INCIDENT_LOG.md` 06/09 [VALIDATION_MISS].
**Surveillance en attendant** : controle L6 n7.


### Ce que la mission pourrait reveler

*(a remplir APRES le run, jamais avant)*

---

## CYCLE 2 ET HORIZON 15 MIN — resultats du 06/09

### Cycle 2 : zero survivante

  H3-VPOC   MEURT          50/47   -0,016 / +0,017   TP 66 % / 57 %
  H2p       NON TESTABLE   16/11
  H6p       NON TESTABLE   15/12
  H8p       NON TESTABLE    2/3

La barriere par famille fait ce qui etait ecrit d avance : le taux de reussite
monte a 66 %, l esperance ne suit pas. Le constat 0.1 avait raison sur le
diagnostic, tort sur le remede — ce n est pas la barriere qui tuait H3.

A ne pas retenir : H2p a +0,705 sur ES avec 73 % de TP. **N = 11.** Ecrit ici
pour que personne ne le redecouvre en croyant avoir trouve quelque chose.

### Horizon 15 min : le premier signe bilateral

                 5 min (couts corriges)      15 min       N
  H3    NQ +0,061 / ES -0,109        ->   +0,018 / +0,019   28/29
  H7    NQ +0,012 / ES -0,270        ->   -0,006 / -0,033   119
  sorties naturelles H3  66,7 %      ->   82,5 %

**H3 est positive sur les DEUX instruments pour la premiere fois du projet.**
Effet arithmetique predit : l ATR grandit, les frais ne bougent pas.

**Mais N tombe a 28/29, sous 40. NON TESTABLE.** Trois fois moins de barres,
trois fois moins de signaux. +0,018 ATR, c est 2 % d une barre, sans
significativite.

### Ce que cela dit, et la seule voie qui reste

**Il manque des JOURS, pas des idees.** En 15 min sur 40 jours, H3 rend 28
signaux ; il en faut 40. A raison de ~0,7 signal par jour et par instrument, il
manque **environ 17 jours de seance** — trois a quatre semaines.

Les 16 jours scelles ne servent pas a cela : ils sont la validation finale, et
les ouvrir maintenant detruirait la seule chose qui protege encore ce projet.

**Mode ombre H3 en 15 min, a partir de maintenant, jusqu a N = 40 par
instrument.** Aucune execution, aucun capital. La decision se prend quand N est
atteint, pas avant — vers la mi-octobre.

**C etait le troisieme et dernier regard sur ce lot.** Le passage en 15 min etait
pre-enregistre dans le critere d arret, donc legitime ; il n y en aura pas de
quatrieme. A partir d ici, seulement les jours qui s ajoutent.

## CRITERE D'ARRET — ecrit le 06/09, avant le cycle 2

Ecrit maintenant, pendant qu'il ne depend d'aucun resultat non encore lu. Sans
lui, chaque zero produit une raison de refaire un tour ; avec lui, un zero
devient une decision.

### Le fait qui a rendu ces reponses possibles

Cinquieme confusion points/ticks de la semaine, et elle etait dans la case 2 des
couts. « ATR-5m ~25 pts = 12,50 $ » pour MNQ : 25 POINTS de MNQ valent 50 $ ;
12,50 $, c'est 25 TICKS. Mesure sur l'ATR-5m median du 06/09 :

| | $/point | ATR-5m en $ | cout reel | ce qui etait applique |
|---|---|---|---|---|
| MNQ | 2,00 | 40,10 | **0,070 ATR** | 0,230 — surestime 3,3x |
| MES | 5,00 | 14,15 | **0,305 ATR** | 0,140 — sous-estime 2,2x |

**Sur MES, un aller-retour coute 30 % de l'ATR-5m** : 20 % du TP a +1,5 ATR,
30 % du SL. Sur MNQ, 7 %. Ce n'est pas une hypothese, c'est de l'arithmetique :
**le micro ES en intraday 5 min ne peut pas gagner.**

La lecture recalculee avec le cout converti a chaque barre le confirme sans
exception — les trois hypotheses qui produisent des trades sont **positives sur
NQ et negatives sur ES** :

| | NQ | ES | verdict |
|---|---|---|---|
| H3 | **+0,061** | -0,109 | MEURT (2/5 blocs sur NQ) |
| H7 | **+0,012** | -0,270 | MEURT (3/5 blocs) |
| H4 | **+0,003** | -0,446 | NON TESTABLE |

Zero survivante reste le verdict : H3 meurt sur son walk-forward autant que sur
ES. Mais l'ecart ES/NQ, de 0,17 a 0,45 ATR pour la meme strategie, est la
signature de la taxe, pas du marche.

**Correction du 06/09 (fin de journee).** Les couts annonces plus haut
(0,070 ATR sur MNQ, 0,305 sur MES) etaient **deux fois trop eleves** : l'ATR-5m
avait ete ESTIME par `atr_14m x racine(5)` au lieu d'etre MESURE sur les barres
agregees. Mesure directe :

| | ATR-5m median | en $ | cout par trade | % du TP a 1,5 ATR |
|---|---|---|---|---|
| MES 5 min | 6,29 pts | 31,43 $ | **0,1375 ATR** | 9,2 % |
| MES 15 min | 11,82 pts | 59,11 $ | 0,0731 ATR | 4,9 % |
| MNQ 5 min | 41,38 pts | 82,75 $ | **0,0341 ATR** | 2,3 % |
| MNQ 15 min | 79,96 pts | 159,93 $ | 0,0176 ATR | 1,2 % |

**Ce que cela invalide** : « le micro ES en 5 min ne peut pas gagner,
arithmetiquement » est trop fort. A 9,2 % du TP, le cout est significatif mais
non redhibitoire. Le constat EMPIRIQUE tient — les trois hypotheses qui ont
produit des trades sont negatives sur ES et positives sur NQ — mais son
explication par le seul cout etait deux fois trop severe.

**Ce que cela ne touche pas** : les resultats des cycles 1 et 2. `triple_barriere`
lit `df["atr5"]`, l'ATR-5m reel de chaque barre, et convertit le cout dessus. Les
P&L sont justes ; seule la communication etait fausse.

### Q1 — Le critere d'echec du cycle 2

> **Une hypothese passe si : esperance nette > 0, N >= 40, et >= 4/5 blocs
> positifs — sur au moins un instrument dont le cout mesure est inferieur a
> 10 % de son ATR-5m.**

Ce que ce critere change par rapport au cycle 1 : il n'exige plus les DEUX
instruments. Exiger ES et NQ etait juste tant qu'on les croyait comparables ; on
sait maintenant qu'ils ne le sont pas, et la raison est chiffree, pas
opportuniste. Sur ce lot, seul **NQ** satisfait la condition de cout (7 % contre
30 %).

Ce qu'il ne change pas : N >= 40, 4/5 blocs, bootstrap par jour, Bonferroni,
16 jours scelles intacts. Le walk-forward reste le juge le plus dur, et c'est
lui qui a tue H3 sur NQ malgre une esperance positive.

**Si aucune hypothese du cycle 2 ne passe ce critere : il n'y a pas d'edge
directionnel intraday 5 min exploitable dans ces 40 jours.** C'est une phrase a
accepter, pas a contourner.

### Q2 — Ce qu'on fait alors : l'horizon, pas la question

La premiere voie n'est ni « changer de question » ni « arreter ». C'est
**passer en barres de 15 minutes**.

L'ATR croit en racine du temps : x1,7 environ de 5 a 15 min. Le cout par trade,
lui, ne bouge pas. Le cout relatif tombe donc de **30 % a 18 % sur MES**, et de
**7 % a 4 % sur MNQ**. C'est le seul levier qui repose sur de l'arithmetique et
non sur un espoir, et il ne coute presque rien : memes donnees, meme noyau, meme
code — le runner agrege deja, `MINUTES_BARRE` passe de 5 a 15.

Les six hypotheses se rejouent telles quelles sur cet horizon. C'est **le
dernier essai sur ce lot** ; ensuite, seulement les jours qui s'ajoutent.

Voies suivantes, si le 15 min echoue aussi, par cout croissant :
1. changer de cible — cesser de predire la DIRECTION, predire l'atteinte d'un
   niveau ou la volatilite (memes donnees, meme infra) ;
2. changer d'instrument — abandonner ES en micro, ne garder que NQ ;
3. arreter le bot et ne garder que la collecte.

### Q3 — La limite en temps

**Cycle 2 clos le 20/09/2026.** Deux semaines. Puis, dans l'ordre et sans
reouvrir ce qui precede : horizon 15 min, puis decision.

### Ce que ce critere protege contre

Pas contre l'echec — contre le fait de **perfectionner l'instrument
indefiniment sans jamais accepter son verdict**. La semaine du 06/09 a compte 48
commits, presque tous pour reparer des mesures : c'etait necessaire, et ca ne
peut pas se repeter indefiniment. Si le cycle 2 rend zero et que la reponse est
« il faut d'abord corriger telle colonne », c'est la qu'on tourne en rond — pas
avant.


## Ce que la lecture du cycle 1 ouvre (06/09/2026)

**Resultat du cycle 1 : zero survivante**, conforme a l'attendu pre-enregistre
(0 a 2). Les 16 jours scelles n'ont pas ete ouverts. Le texte tague n'a pas
bouge. Ce qui suit est ce que la lecture a appris, et rien de tout cela ne
retouche le cycle 1.

| hyp | verdict | entonnoir ES (lieu > regime > reaction) | ce que ca dit |
|---|---|---|---|
| H2 | NON TESTABLE | 143 > 27 > 3 | regime hors unite, puis reaction |
| H3 | **MEURT** | 276 > 276 > 52 | testee pour de vrai |
| H4 | NON TESTABLE | 107 > 107 > 22 | trop rare, et negative |
| H6 | NON TESTABLE | **58 > 0 > 0** | le regime tue tout |
| H7 | **MEURT** | 685 > 685 > 551 | testee pour de vrai |
| H8 | NON TESTABLE | **496 > 496 > 0** | la reaction tue tout |

### 1. La regle qui manquait : une condition de regime a une unite

C'est la lecon principale, et elle depasse « mesurer la distribution d'un
seuil ». `ib_range_atr` divise des TICKS par des POINTS (`ib_range_ticks / atr`,
identique au livre a 100 % sur 12 580 barres). Facteur 4, le meme que sur les
`dist_*_atr` : quatrieme bug de la famille ATR, premier sur une condition de
regime.

**Une condition de regime se recalcule par `recalc.py` comme une distance.**
`recalc.ib_range_atr_r` est ecrit. Les seuils du paradigme etaient justes dans
leur unite d'origine — la mediane corrigee, 0,43, tombe exactement a la
frontiere « IB etroite / rotation » de mars. Ce n'est pas le seuil qu'il fallait
changer, c'est la colonne qu'il fallait recalculer.

**A faire avant le cycle 2** : passer toutes les conditions de regime au meme
crible d'unite, pas seulement `ib_range_atr`. Le crible est simple : reconstruire
la colonne par sa formule attendue en unites coherentes, et comparer au livre.
Une egalite a 100 % avec une formule *incoherente* identifie le bug ; c'est ce
qui a tranche ici.

### 2. Les trois hypotheses non testees, a reprendre — a une condition

H2', H6', H8' avec le regime recalcule sont **trois hypotheses nouvelles**, pas
une reprise. Elles se pre-enregistrent, avec **Bonferroni 0,05 / 3**, sur les
memes 40 jours de recherche.

C'est un **second regard sur les memes donnees**, et il n'est legitime qu'a
trois conditions, toutes non negociables :
1. **le declarer comme tel** dans le texte du cycle 2 ;
2. **ne rien toucher aux 16 jours scelles**, qui restent la validation finale de
   tout ce qui survivrait un jour ;
3. **pas de troisieme regard** sur ce lot. Apres celui-la, seulement les jours
   qui s'ajoutent.

Diagnostics a faire avant de les reecrire :
- **H6** : le lieu rend 58 signaux ES ; avec le regime corrige (52,9 % des barres
  au lieu de 0,13 %), il devrait survivre a l'etage regime. A verifier, pas a
  supposer.
- **H8** : le lieu rend 496 et la reaction rend 0. Ce n'est pas une question
  d'unite — il faut isoler laquelle des trois conditions
  (`rvol_r >= 2` / `|delta_pct| >= 0,30` / finish contraire) annule tout, et
  mesurer sa distribution avant de la reecrire.
- **H2** : 143 > 27 > 3. Le regime corrige en couvrirait 96,9 %, donc le lieu
  passerait a ~143 ; reste a savoir ce que la reaction en garde.

### 3. La barriere par famille — le resultat le plus exploitable du cycle

Sorties naturelles atteintes **avant** la barriere, mesurees :

| hyp | part | N |
|---|---|---|
| H3 | **66,7 %** | 93 |
| H4 | 65,9 % | 44 |
| H7 | 48,8 % | 660 |

**H3 touche le VPOC ou la VWAP deux fois sur trois, et meurt quand meme** sur une
barriere de continuation a +1,5 / -1,0 ATR. C'est le constat 0.1 mesure : un
setup de retour a la valeur juge sur une cible de tendance. La barriere par
famille — cible = VPOC ou VWAP, invalidation = acceptation au-dela du niveau —
devient **l'hypothese centrale du cycle 2**, et elle se pre-enregistre comme les
autres.

Attention a ne pas se raconter d'histoire : 66,7 % de touches ne fait pas un
edge. Il reste a mesurer l'esperance nette avec cette barriere-la, frais compris
(0,23 ATR sur MNQ, 0,14 sur MES), et une cible plus proche encaisse moins par
trade. C'est justement ce que le cycle 2 doit trancher.

### 4. H4 en mode ombre, sans illusion

22 signaux, esperance **-0,19 ATR sur NQ et -0,458 sur ES**. « NON TESTABLE »
dit « trop rare pour conclure » ; le signe, lui, est franc et concordant sur les
deux instruments. Ce n'est pas une survivante en attente : c'est une hypothese
negative a qui on laisse quarante jours de plus pour changer de signe. Entrer en
ombre sans l'oublier.

### 5. Ce que le cycle 1 ne dit pas

Il ne dit pas que les features manquent. Il dit que deux setups n'ont pas d'edge
net de frais (H3, H7) et que trois definitions de regime ou de reaction etaient
fausses ou trop strictes. Ce sont des problemes de **definition**, pas de
**representation** : aucun clustering ne les aurait vus. P4 (clustering sur les
barres 5 min) et P9 (scores de famille) servent le cycle 2 ; ils ne rattrapent
pas le cycle 1.


## Hypotheses nees en cours de route, NON testees

*(vide au 05/09 — tout ce qui apparait ici pendant l'analyse des resultats
attend le cycle suivant)*
