# STATUS — V3, l'etat des briques

*Le fichier a lire en premier. Une ligne par brique, trois etats possibles.*

| etat | ce que ca veut dire |
|---|---|
| **ecrite** | le code existe, rien n'est mesure |
| **mesuree** | on sait ce qu'elle rejette et ce que ses rejetes deviennent |
| **passee** | elle remplit son critere de scellement — elle entre dans la chaine |

**L0 est SCELLEE le 06/09.** Elle ne se rouvre plus : ce qui naitra ensuite ira
dans `NEXT_CYCLE.md`. Son critere est au paragraphe 7 de
`layers/L0_interrupteur/BRIEF.md` — reecrit le jour meme, l'ancien etant
arithmetiquement contradictoire a 25 portes.

**Regle du chantier** : une brique qui ne rejette rien, ou qui rejette tout, ne
passe pas a la suivante. C'est le garde-fou que V1 n'a jamais eu — il embarquait
27 modules dont personne ne savait ce que chacun filtrait.

---

## Briques

| # | brique | etat | rejet mesure | plage attendue | note |
|---|---|---|---|---|---|
| L0 | interrupteur — 25 portes + 5 declarees absentes | **PASSEE** | **une ligne par porte** : `layers/L0_interrupteur/rapports/portes_57j.csv` | 15-30 % **par porte** | l'agregat a ete retire : domine par `POSITION_OUVERTE`, il se lisait comme un echec alors que la plage est par porte |
| REG | regime (gamma HVL zone morte 1,0 ATR + largeur IB corrigee) | **mesuree** | — | 4 cases >= 5 jours | 99,7 % de couverture ES, 1,8 bascule/jour |
| L1 | biais — B1p mesuree, B1n en attente de F23 | **mesuree** | — | a etablir sur la mesure | ne se juge PAS sur un taux de rejet : couverture, separation, cout de l'obeissance. Cf `layers/L1_biais/BRIEF.md` |
| L3 | declencheurs 15 min | **ecrite + ombre C2 courue** | rapports lieu_div_delta, lieu_poor (08/09) | N >= 40 par etage | 4 pre-enregistres + 16 ED en ombre + **3 setups C2 ACTIFS** (80PCT, EOD, DIV_DELTA — seuils mesures, 8 cas chacun). C2_POOR pre-cable PAS actif (v1 morte par construction, redesign J+2). #3/#4 attendent le diagnostic F23 nuit ; #9-#11, #7, #12 : cycle 2 |
| F23 | memoire de session — fiches par test, partagee L1/L3 | **ecrite** | 9 fiches sur 2 jours, test au tick vert | — | debloque B1n et trois declencheurs de L3 |
| L4 | confirmation order flow 1 min | **J2 FAIT 07/09 — mesuree, OBSERVEE** | mesure_l4_20260907 : 512 signaux, separation dans le bruit aux trois k, gain net +-epsilon | 30-50 % (mesure : 18-27 %) | k=2 ecrit dans DECISIONS ; **QUATRE vetos mesures, UN non mesurable** (V5, seuils null — jamais « cinq vetos »). Lecture PAR FAMILLE au jour 61 (audit 08/09 : les vetos sont ecrits pour une continuation — sur un fade, « personne n'achete » est la raison du trade ; indice H3-ES k=2 : retenus -0,162 / vetoes +0,251, bruit mais le signe gene). L4 se rejuge au jour 61. **AUDIT 09/09 : AUCUNE TRACE en campagne** — la chaine n'importe que L0/L5, aucune couche L4 n'ecrit dans l'entonnoir. « Observee » decrit la mesure du 07/09, PAS un journal quotidien : au jour 61 il n'y aura pas une ligne L4 a rejuger sans cablage (cycle 2) |
| L5 | risque — 3 vetos (gamma, rvol, frais/TP) | **mesuree** | meme rapport, lignes `L5_*` | 10-25 % | PAS inerte : c'etait la mesure qui l'etait. Le veto SL mort remplace par la part des frais dans la distance au TP |
| L6 | surveillance donnees | **passee, SANS PRODUCTEUR QUOTIDIEN (audit 09/09)** | — | — | 7 controles ecrits, mais `surveillance_l6.py` (CORE/research) n'est dans AUCUNE tache planifiee — dernier fichier produit le 04/09. `L0_DATA_L6_ALERTE` (appliquee) a bloque 84 battements du jour 1 sur un verdict vieux de 4 jours, puis passera en TROU permanent (fail-closed en strict). Brancher en etape 0 du rythme du soir = arbitrage bloc C |
| L0-live | le branchement live de L0 : `strict=True` + etat du connecteur | **mesuree, BRANCHEE 07/09** | 14 scenarios de faux live + coureur reel (`execution/coureur_live.py`) : battements journalises en seance ferie, age_s ~90 s via --sync, FERIE_CME + trous DTC conformes a l'attendu pre-enregistre | — | reste avant scellement : un jour OUVRE complet + le pont DTC (dtc_connecte est un trou voulu) |

## Comment lire le rapport des portes

Trois classes, trois lectures — les confondre donne le verdict inverse :

| classe | ce que ca veut dire | comment la juger |
|---|---|---|
| **appliquee** | elle bloque | sa part de rejet, dans sa plage |
| **observee** | elle journalise « j'aurais bloque » sans agir | le devenir de ce qu'elle aurait ferme |
| **trou** | elle n'a pas pu repondre — la donnee n'existe pas ici | **jamais** sur la plage de rejet |

**Sept portes sont muettes hors ligne** (`ROLLOVER`, `CONTRAT_INACTIF`,
`DTC_DECONNECTE`, et quatre de la famille A). Elles ne sont pas inertes : leur
terrain est le live, ou elles ont une vraie valeur a comparer — et ou un trou
BLOQUE (`chaine.appliquer(strict=True)`). Les juger sur les plages de rejet
donnait « dans la plage » a une porte qui ne repond jamais.

## Ou est quoi

Un dossier par couche, tout ce qui la concerne dedans : spec, seuils, code,
tests, mesure, rapports. Carte complete dans `LISEZ_MOI.md`.

## Calendrier immediat

**MARDI 08/09/2026 — JOUR 1 DE LA CAMPAGNE D'OMBRE.** Le coureur live tourne
(`coureur_live.py --sync`, lance le 07/09 au soir) ; le rejeu officiel de
21:01 UTC est celui de CE soir — quatre gelees + seize ED + TROIS setups C2
actifs (80PCT, EOD, DIV_DELTA v2). JEUDI 10/09 : rollover U26→Z26,
`L0_CONTRAT_INACTIF` doit le dire — a REGARDER, pas a corriger.
VENDREDI 12/09 : GEL — apres, on n'ajoute plus, on regarde tourner.

## Prochain pas

1. **B-BOUEE + branchement `barrieres_du_jour` au 21:01** (mesure MAE des
   gagnants d'abord) et **A2 + PF_PERTE_JOUR observee** — demain, revue
   Fable 08/09 §E2.
2. **`test_dmp`** (reproduction des colonnes B du post-it) puis la chaine
   POSTIT (recalc range → cinq mesures → setups PJ_*).
3. **Diagnostic F23 nuit (A_FAIRE pt 11)** → debloque #3 VWAP/SD1,
   #4 SWEEP_ON et POOR v2 (fiche F23, design arbitre pt 20).
4. **Pont DTC / EXEC SIM** : ordres de TEST hors chaine, avant vendredi.

**L1 (biais 1 h / 4 h) attend F23** — B1-photo est ecartee par la mesure
(DECISIONS 07/09) ; rien a construire sur L1 avant le diagnostic.
Regle de coherence (revue 08/09, A3) : `PROMPT_REPRISE` cite CE fichier,
jamais l'inverse — une seule verite pour « ou en est-on ».
