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
11. **Les quatre n'ont JAMAIS été testées avant 11h00 ET** (mesure 08/09,
    `rapports/trou_atr_les_quatre` : 0 signal sur 52 j × 2, 300/300 barres
    `atr_barre` NaN 9h30-11h00 — min_periods = 7). La sous-population
    « avant 11h00 » de la règle 1 est **VIDE PAR CONSTRUCTION**, pas par le
    marché : toute phrase du type « la stratégie ne marche pas le matin »
    est INTERDITE au jour 61 — elle n'y a pas été essayée. L'IB et la
    première heure sont un angle mort ASSUMÉ de la campagne gelée ; le
    cycle 2 lit `atr_ref` (ATR-veille en secours, la solution L1). ET LE
    TABLEAU DIT PLUS (revue 08/09, B7) : H3-VPOC fait 13/4/2 signaux ES et
    8/5/2 NQ sur les tranches 11h-13h / 13h-15h / 15h-16h — **les quatre
    gelées sont, EN PRATIQUE, un setup de 11h00-13h00**. Un H3 lu sur 60
    signaux dont les deux tiers en mi-journée ne se généralise PAS à la
    séance.
12. **L4 se lit PAR FAMILLE de déclencheur** (audit Fable 08/09) : ses vetos
    sont écrits pour une CONTINUATION (« personne n'achète » = danger) ;
    sur un FADE, « personne n'achète » au niveau est la raison même du
    trade. Indice mesuré (bruit, N = 23, mais le signe gêne) : H3-ES à
    k = 2, retenus −0,162 / vetoés +0,251 — L4 fermait les GAGNANTS. Un
    verdict L4 global qui mélange fades et continuations est interdit. Et
    **V5 n'a jamais été mesuré** (seuils null, 100 % trous) : le jour 61
    dit « quatre vetos mesurés, un non mesurable », jamais « cinq vetos ».
13. **C2_EOD porte DEUX verdicts pré-enregistrés, jamais un troisième**
    (arbitrage Fable 08/09) : EOD-pur — le papier Baltussen, side =
    `side_pur`, TOUS les jours, N ≈ 60 — et EOD-r_min — le filtre |rend_r|
    ≥ p25, N ≈ 45. Les deux colonnes sont dans chaque ligne du journal
    (`side_pur`, `rend_pts`, `rendement_r`) ; si un seul des deux survit,
    la conclusion porte sur le FILTRE, pas sur l'effet. `side_pur = 0`
    (jour exactement plat au tick) = pas de direction : compté NO-TRADE
    dans le N d'EOD-pur — deux lecteurs ne doivent pas compter deux N.
    Le PRIX de sortie = la clôture de la dernière barre cash du jour
    (`close_1545` est une règle DÉTERMINISTE label → prix, recalculée du
    fichier — jamais sur la ligne de signal, qui resterait sinon
    contaminée par le futur : l'anti-fuite du test l'interdit) ; le
    journal des barrières portera l'issue chiffrée (A_FAIRE pt 21).
14. **C2_80PCT se lit par `cote_reentree`** (revue 08/09, C) : le side
    « ouverture au-dessus → SHORT vers VAL » suppose une ré-entrée PAR LE
    HAUT. Une ouverture au-dessus, un tour SOUS la VA, puis une ré-entrée
    par le bas : l'ouverture n'est plus la référence — le cas `mixte` se
    lit À PART, jamais mélangé au cas Dalton.
15. **DIV_DELTA v2 se lit en séparant `atr_source`** (revue 08/09, C) :
    un lieu à 9h35 sur l'ATR de la VEILLE dans une journée à gap de 2 ATR
    est un lieu sur une échelle fausse pour CETTE journée. Les signaux
    `veille` et `barre` sont deux populations — la colonne est dans chaque
    ligne, la lecture ne les additionne pas sans les avoir vues séparées.
16. **Les journées fermées par le stop journalier SIM se lisent À PART**
    (revue 08/09, A2) : le stop n'est PAS « inerte par construction »
    (4,9 SL de 1 ATR sur NQ) — si une séance ferme dessus, ses signaux
    post-fermeture n'existent pas dans le journal officiel, et la comparer
    aux journées pleines fausserait les deux.
17. **La nuit du jour 1 n'a PAS de preuve live** (INCIDENT 08/09 : le
    coureur ne basculait pas de journée — le journal live du 08 commence
    vers 10:30 UTC, pas à 22:00 la veille). Elle se lit comme un TROU,
    jamais comme une nuit calme. Le rejeu de 21:01, lui, couvre la journée
    entière — c'est pour ça qu'il est LA mesure et que le live n'est que
    la preuve.

## Ce que le jour 61 NE fait pas

Pas de « correction » : ce qui a survécu bascule observée → appliquée, ce qui
n'a pas survécu reste observé ou sort. Pas de seuil retouché sur le tableau.
Pas de lecture d'un épisode isolé. Les idées vont dans `NEXT_CYCLE.md`.
