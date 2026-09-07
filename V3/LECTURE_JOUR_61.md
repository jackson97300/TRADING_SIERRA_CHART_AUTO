# LECTURE DU JOUR 61 — l'attendu, écrit le jour 0

*Pré-enregistré le 07/09/2026, veille du jour 1, sur l'audit Fable des quatre
déclencheurs. Ce fichier dit COMMENT le tableau sera lu avant que quiconque
l'ouvre — pour que le jour 61 ne puisse pas se raconter d'histoire. Il se
complète par commit AVANT le jour 61 ; il ne se modifie plus après.*

## Les règles de lecture, dans l'ordre

1. **H3-VPOC ne peut pas passer seule à N ≈ 60.** Par arithmétique, pas par
   principe : effet cycle 1 +0,02 ATR, coût MES 0,038 ATR — l'intervalle à
   N = 60 contient zéro pour un effet de cette taille. H3 se juge sur
   120 jours OU sur sa sous-population PRÉ-DÉCLARÉE : instrument, avant/après
   11h00 ET (l'âge de la VA), régime ROTATION confirmé. Rien d'autre.
2. **ES et NQ comptent pour 1,3 test, pas 2** (corrélation ~0,9) — déjà la
   règle du cycle 1, rappelée parce que N sera petit.
3. **Lecture SÉPARÉE ES/NQ, et H3-NQ jamais seule** — parce que la colonne
   `finish_delta_pct` a une formule inconnue et que son seuil est un filtre
   MOU : 0,4 garde 55 % des barres de lieu sur ES et 41 % sur NQ
   (`rapports/finish_lieu_h3`). PAS parce qu'elle serait binaire : la mesure
   du même jour l'a démenti au site de décision (61 valeurs distinctes sur
   61 barres NQ) — la binarité vivait sur le 1 min. Règle corrigée le 07/09,
   avant le jour 61, comme ce fichier l'autorise.
4. **H2p, H3 et H-EXT se lisent comme UN phénomène** — la réversion vers la
   valeur, testée trois fois sous trois noms. Bonferroni ne le sait pas ; la
   lecture le sait. Si H-EXT survit et H2p non, la conclusion est « la
   réaction coûte plus qu'elle ne filtre » — une lecture, pas deux.
5. **Le régime de H2p (141/143) n'est pas une condition** : le retirer de la
   description de ce qui a été testé.
6. **H6p se lit avec/sans son régime** « IB étroite < 0,4 » — possiblement
   INVERSÉ par rapport au lieu (les retests arrivent les jours d'IB large).
7. **Chaque déclencheur se lit AVEC et SANS B5** (l'ouverture hors VA veille).
   Le cycle 1 prenait le contre-sens 95-97 % des jours de tendance et B5 lisait
   le bon sens 15/15 — c'est probablement là que la première vraie information
   sortira, pas des seuils. H-B5TREND est pré-enregistrée ; ceci est sa
   lecture d'application.
8. **La cible VPOC est FIGÉE à l'entrée** (DECISIONS 07/09, vérifiée dans le
   code tagué) — la lecture n'a pas à en débattre.
9. **Les seize ED se lisent un par un à N = 40 sur NQ**, jamais avant, jamais
   en groupe (OMBRE_ED16 : une quatrième lecture combinée du passé produirait
   des gagnants par combinatoire).
10. **Sous-puissance assumée** : L3 produira ~30 signaux vivants par
    instrument sur 60 jours, et L1/L4/F23 se mesurent SUR ces signaux. Une
    lecture sous-puissante n'est pas une surprise, c'est la réalité de
    l'ombre — écrite ici pour n'être découverte par personne le jour 61.

## Ce que le jour 61 NE fait pas

Pas de « correction » : ce qui a survécu bascule observée → appliquée, ce qui
n'a pas survécu reste observé ou sort. Pas de seuil retouché sur le tableau.
Pas de lecture d'un épisode isolé. Les idées vont dans `NEXT_CYCLE.md`.
