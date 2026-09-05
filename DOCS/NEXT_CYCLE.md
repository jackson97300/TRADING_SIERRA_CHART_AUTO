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
