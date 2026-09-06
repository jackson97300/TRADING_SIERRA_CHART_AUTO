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
| L1 | biais 1h/4h — B1 d'abord | **cadree** | — | a etablir sur la mesure | ne se juge PAS sur un taux de rejet : couverture, separation, cout de l'obeissance. Cf `layers/L1_biais/BRIEF.md` |
| L3 | declencheurs 15 min | **ecrite** | — | N >= 40 par etage | 4 pre-enregistres + 16 en ombre |
| L4 | confirmation order flow 1 min | **absente** | — | 30-50 % | la seule couche a construire |
| L5 | risque — 3 vetos (gamma, rvol, frais/TP) | **mesuree** | meme rapport, lignes `L5_*` | 10-25 % | PAS inerte : c'etait la mesure qui l'etait. Le veto SL mort remplace par la part des frais dans la distance au TP |
| L6 | surveillance donnees | **passee** | — | — | 7 controles quotidiens en place |
| L0-live | le branchement live de L0 : `strict=True` + etat du connecteur | **PASSEE** | 14 scenarios de faux live passent | — | brique SEPAREE : sceller une couche dont la moitie n'a jamais tourne n'aurait rien scelle |

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

**LUNDI 07/09/2026 — LABOR DAY.** 1er lundi de septembre, verifie. Le marche est
OUVERT mais ferme a 13:00 ET au lieu de 16:00 : seance raccourcie, aucun trade.

Deux consequences :
- la campagne d'ombre demarre le **mardi 08/09**, elle n'est pas touchee ;
- la surveillance L6 etait prevue lundi 21:01 UTC sur la premiere journee `w1`.
  **Une demi-seance est une mauvaise reference** — volumetrie, reset VWAP et
  fenetre seront tous atypiques. A decaler au mardi, ou a lire en sachant que
  les ecarts sont attendus.

## Prochain pas

**L1 — le biais 1 h / 4 h.** Meme methode : ecrire, mesurer le taux de rejet et
le devenir des rejetes, confronter les deux versions, sceller. Le critere de L0
sert de modele, pas de copie : une couche de BIAIS ne se juge pas comme un
interrupteur, et sa plage reste a etablir sur sa propre mesure.

**Avant mardi 9h30** : brancher le bot sur `chaine.appliquer(strict=True,
live={...})`. Le faux live prouve que le chemin fonctionne ; le bot ne l'emprunte
pas encore.
