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
    est INTERDITE au jour 61 — elle n'y a pas été essayée. **Corrigé le
    09/09 (brique 1 Fable, DECISIONS)** : depuis le jour 1 REJOUÉ, les
    quatre et les seize lisent `atr_ref` (ATR de la dernière session
    complète en secours) — la sous-population du matin EXISTE, elle porte
    `atr_source = veille` et se lit À PART (règle 15 étendue) ; les jours
    L6 `echelle_douteuse` (gap ≥ 2 ATR-veille) à part encore. ET LE
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
15. **DIV_DELTA v2 — et depuis le 09/09 LES QUATRE et LES SEIZE (brique 1) —
    se lisent en séparant `atr_source`** (revue 08/09, C ; les lignes
    antérieures à la brique — intentions du 04/09, journaux ≤ 08/09 non
    rejoués — n'ont pas le champ : absent = `barre`, un PASSE n'existait que
    sur `atr_barre` fini ; les jours L6 `motif = echelle_douteuse` ou
    `rollover` se lisent à part encore) :
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
18. **Jour 1 (08/09) : le journal live est un RODAGE — il ne fait pas foi**
    (verdict Fable 08/09). `ts` empoisonné (méga-secondes, pandas 3 VPS),
    motifs faux (`L0_FERIE_CME` fantôme du 1er janvier 1970,
    `L0_DATA_PERIMEE` d'un âge de 56 ans) jusqu'au fix de ~16:30 UTC. Seul
    le rejeu 21:01 fait foi ce jour-là. Le live fait foi à partir du
    premier jour où le battement porte `env` (versions python/pandas/numpy)
    ET où `test_agreger_ts.py` est vert SUR le VPS. Le fichier empoisonné
    est conservé renommé `_rodage` — pièce d'incident, jamais supprimé.

18b. **`POSITION_OUVERTE` : le journal LIVE ne fait pas foi dessus, jusqu'au pas
    2b** (audit Fable 09/09, A4 ; défaut `PLAN_ENTREE_EXEC` §0). En live,
    `triple_barriere` ne voit pas la sortie future → `libre_a = −1` → la porte
    ne ferme rien → DEUX `PASSE` simultanés possibles sur un instrument. Le
    REJEU 21:01 a le futur : `libre_a` juste, un seul PASSE. Sur CETTE porte, la
    mesure = le rejeu, jamais le live, tant que le câblage sur l'état réel (pas
    2b, après le gel) n'est pas fait.

## Les réactions aux niveaux (`reactions.py`) — règles écrites AVANT la donnée

*Ajoutées le 08/09 au soir, avant la première ligne du journal. Un journal
sans sa règle de lecture est un jeu de données à miner (incident 28/04).*

19. **Unité statistique** : le TEST pour les lignes `type=test`, le
    JOUR-INSTRUMENT pour `niveau_jour`. Jamais mélangées dans une phrase.
20. **Lecture par CLASSE** : primaires d'abord, secondaires à part avec leur
    `derive_niveau_atr`, et `vwap_d` en TÉMOIN. **Un niveau primaire qui ne se
    distingue pas du témoin n'est pas un niveau : c'est une heure.**
21. **Test de permutation obligatoire** : mélanger les étiquettes `niveau`
    entre fiches d'une même journée, 1 000 fois. Si la séparation réelle est
    sous le p95 du mélange, F23 décrit l'heure ou le régime, pas le niveau.
22. **`issue` se lit en composition à quatre voies**, jamais en taux de
    réussite : « 55 tenu sur 80 » n'est pas 69 % de réussite.
23. **Symétrie obligatoire** : `exc_rejet_atr_4` et `exc_poursuite_atr_4` se
    lisent CÔTE À CÔTE, jamais l'un sans l'autre. `reaction_atr` (hérité de
    f23) est ASYMÉTRIQUE — il ne se lit jamais seul.
24. Les fiches à `barres_restantes < 8` sont **censurées à droite** : lues à
    part ou exclues, décidé avant de regarder.
25. Une ligne à `motif_zero != null` ne compte **JAMAIS** comme « ce niveau
    n'a pas marché » — la colonne était absente, vide, ou le prix n'est
    jamais venu.
26. Jours `ferie` et demi-séances **à part** (07/09 = Labor Day est déjà dans
    le lot).
27. ES et NQ comptent **1,3**, pas 2 (règle 2). Aucun épisode isolé (règle 3).
28. **Aucune phrase de devenir.** Ce journal ne porte ni gain, ni R, ni
    entrée, ni sortie, ni stop. « Ce niveau a marché » est un contresens
    d'usage : le fichier dit ce que le marché a FAIT, jamais ce qu'il aurait
    fallu faire.

## Le devenir (`triple_barriere`) — CORE confronté à la référence (09/09)

*Rangées dans la plage jour-61 (29-34) ; 29-32 réservées à la lecture des
devenirs par famille. Écrites après la confrontation `research/parite_barriere`.*

33. **Une `EXPIRATION` de CORE sur la dernière barre cash (945 = 15h45) est un
    EOD** — un trade coupé par la clôture, pas un trade qui a duré 20 barres. La
    confrontation 09/09 (`research/rapports/parite_barriere.txt`) le chiffre :
    sur 70 signaux des quatre, **22 `EXPIRATION → EOD`** (MÊME prix, étiquette
    CORE fausse), répartis 11h-15h — **un tiers dès 11h** : la barrière 20 barres
    (5h) dépasse la clôture pour tout signal après ~11h, l'EOD est le vrai plafond.
    **Zéro écart de `pnl_atr`** entre CORE et la référence sur les 66 résolus :
    CORE n'a pas tort sur le PRIX, seulement sur le NOM. Les devenirs se lisent
    en SÉPARANT `EOD` des vraies `EXPIRATION`.
34. **Trois jours ont une donnée cash TRONQUÉE** (dernière barre < 945) : `09/07`
    (Labor Day, demi-séance — attendu), `09/09` (collecte en cours — attendu),
    `08/05` (**inexpliqué, à investiguer**). CORE y fabrique une `EXPIRATION` sur
    une barre trop précoce ; la référence dit `INDETERMINE`. À lire comme un TROU
    de données, jamais un devenir. La correction de CORE (étiquette `EOD` +
    20 barres détenues) attend le CYCLE 2 : la campagne est gelée sur CORE,
    changer le moteur des devenirs en cours ferait deux populations de mesures.

35. **Le silence des quatre se lit en `lieu_min_ticks`** (brique 2 Fable,
    09/09 — `marges_quatre_<jour>.jsonl`, une ligne par hypothèse × instrument,
    MÊME les jours muets, parité barre à barre avec les fonctions gelées
    prouvée par `test_marges_quatre`). « Bande trop serrée de X ticks sur N
    jours », « lieu atteint, réaction manquante = finish sur M jours » sont
    des CALIBRATIONS pour le cycle 2 — JAMAIS une permission d'élargir une
    bande ou de desserrer une réaction pendant la campagne. QUASI n'est pas un
    signal manqué : c'est une distance. La seule phrase autorisée a la forme
    « à seuil × k, N passerait de A à B », et elle se prononce au jour 61.

36. **`L5_VETO_GAMMA` se lit sur les LONGS seulement** (A1, forme minimale,
    passe lecture 10/09) : CHAQUE short depuis le 10/09 porte une ligne
    `TROU_L5_VETO_GAMMA` — mur ou pas — parce que `gamma_block_short` n'est
    pas dans l'agrégation ; ce n'est pas « aucun mur sous le prix », c'est
    « non mesuré » (mesuré au re-rejeu : 13 shorts sur 14 jours, 13 lignes ;
    avant, un short sans mur n'écrivait rien). Les lignes antérieures au
    10/09 (non rejouées, et le journal LIVE du 10/09 avant le redémarrage du
    coureur — `ts` dans DECISIONS) lisaient le mur du DESSUS pour les
    shorts : un `BLOQUE:L5_VETO_GAMMA` sur un `:S` y est un veto inversé,
    pas une mesure. Et depuis la même passe, `L5_FRAIS_TROP_LOURDS` et
    `L0_REGIME_INDETERMINE` RÉPONDENT avant 11h00 (sur `atr_ref`) : leurs
    `TROU_` du matin antérieurs sont des trous de MÈTRE, pas de marché.

37. **Le LIEU est sur la ligne depuis le 10/09** (`lieux`, `seuil_ticks`,
    `bande_ticks`, `close`, `lieux_motif` — `V3/lieux.py`) : nom du niveau,
    prix reconstruit `close + dist × tick` (TOUTES les `dist_*` sont
    « niveau − close », `dist_cur_val` comprise — mesuré à 100 % contre
    `cur_val_lvl` ; review du 10/09), distance en ticks, la BANDE du lieu
    (bas, haut — H6p `[−P15 ; +P05]`, H2p asymétrique : `seuil_ticks` est la
    borne de proximité de la famille, PAS la bande). Les lignes antérieures
    (non rejouées) n'ont pas le champ : leur lieu se reconstruit par rejeu,
    pas par lecture. Un `lieux: None` porte son motif ; un signal hors des
    quatre (battement, ombre) en a un par construction. Le lieu DÉCRIT ;
    « le niveau X marche mieux que Y » est une lecture du jour 61 par
    famille, jamais une raison de retoucher un lieu en campagne. **Et une
    lecture pour NEXT_CYCLE, pas pour le tag** : `h3` gelé reconstruit la VAL
    avec le signe inverse (`close − dl × tick` = 2·close − VAL) — son LONG
    tire quand la clôture est juste SOUS la VAL (`dl > 0`) avec une mèche
    basse plus longue que la distance à la VAL, pas « sortie sous la VAL
    puis clôture dedans » comme sa docstring le dit. Le journal porte la
    vraie VAL ; le déclencheur reste tel qu'il a été tagué et mesuré.

38. **H3-VPOC se lit en DEUX JAMBES** (Fable, 10/09, relecture du lieu —
    mesure : `close + dist_cur_val × tick = cur_val_lvl` à 100 % sur 4 × 390
    barres, `h3` gelé reconstruit la VAL au signe inverse). La jambe SHORT
    (rejet au VAH) est l'hypothèse pré-enregistrée. La jambe LONG tire quand
    la clôture est juste SOUS la VAL avec une mèche basse — ce n'est pas
    « sorti sous la VAL puis revenu dedans », c'est autre chose : **une
    hypothèse ACCIDENTELLE, sans attendu écrit, que personne n'a
    pré-enregistrée**. Elle se lit À PART et NE PEUT PAS « passer » : un
    résultat sur elle est une DÉCOUVERTE à pré-enregistrer au cycle 2
    (NEXT_CYCLE §5 septies), jamais un verdict. Rien ne bouge au tag. Sa
    taille est mesurée dans DECISIONS (10/09 soir : longs / shorts H3 sur le
    lot) — c'est la jambe qu'on isole.

39. **Le scénario est sur chaque ligne ; il DÉCRIT, il ne DÉCOUPE pas**
    (Fable, 10/09, module SCÉNARIOS — pré-enregistrée avant que le module
    existe). `scenario_en_cours` sera sur chaque ligne de l'entonnoir, des
    fantômes et des marges : au jour 61 il se lit comme une **colonne de
    contexte**, jamais comme une partition du verdict. Sur le lot, 73 signaux
    des quatre en 54 jours : découpés par scénario, aucune case n'a de
    puissance. Une partition par scénario exige N ≥ 40 par case — le cycle 2
    ou au-delà. La règle 9 (jamais en groupe) s'applique dans les deux sens :
    ni fusionner, ni découper en dessous de la puissance. Le module n'entre
    dans aucune porte, ne décide rien, n'écrit que ses propres journaux.

## Ce que le jour 61 NE fait pas

Pas de « correction » : ce qui a survécu bascule observée → appliquée, ce qui
n'a pas survécu reste observé ou sort. Pas de seuil retouché sur le tableau.
Pas de lecture d'un épisode isolé. Les idées vont dans `NEXT_CYCLE.md`.
