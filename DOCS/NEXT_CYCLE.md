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

## Hypotheses nees en cours de route, NON testees

*(vide au 05/09 — tout ce qui apparait ici pendant l'analyse des resultats
attend le cycle suivant)*
