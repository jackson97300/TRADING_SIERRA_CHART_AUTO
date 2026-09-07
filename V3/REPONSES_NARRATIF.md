# F23 — RÉPONSES AUX HUIT QUESTIONS
*Fable, 08/09/2026, sur `RECAP_NARRATIF.md`. Déposé tel quel : le dépôt est la
mémoire. Contrainte respectée : mécanismes sur OHLCV + delta 1 min ; tout ce
qui exige carnet ou OI le dit.*

## 0. « Comment ça ne reste pas un gadget »

Un narratif devient un instrument de décision le jour où il rend **un nombre
par niveau et par barre, calculable hors ligne, avec un devenir mesurable** —
et le jour où une couche qui le lit fait *mieux* que la même couche sans lui,
hors bruit. Trois conditions : un **vecteur d'état par niveau** (cinq scalaires
au plus, chacun avec sa distribution datée : `n_tests`, `defense_tendance`,
`desequilibre_au_dela`, `age_barres`, `issue_courante`) ; une **mesure
d'information** avant toute mesure de rentabilité (l'état à t sépare-t-il les
devenirs à t+20, scalaire par scalaire, contre le hasard) ; un **avec/sans dans
la couche consommatrice** (B1n vs B1p ; H7 avec `piege_proche` vs sans). Le
récit qui refuse de publier est la *condition* de la valeur, pas la valeur.

## Q1 — Le net piégé sans open interest

`|delta|/volume` mesure l'agression nette au-delà, pas le net piégé. Trois
grandeurs séparées, jamais fusionnées :
- **A** = Σ delta des barres closes au-delà (signe = qui a poussé) ;
- **D** = |A| / Σ volume — seuil au **p75 des cassures des 57 jours, par
  instrument** (attendu 3–6 %) ;
- **R, le retour non financé** = part du delta de même signe que A pendant le
  chemin de retour : R ≈ 1, ils n'ont pas vendu, encore dedans ; R ≈ 0, sortis
  pendant le retour, carburant brûlé. Meilleure borne inférieure sans OI.
« Piégé » n'est jamais un fait — c'est H-PIÈGE, avec D et R.

## Q2 — La décroissance du carburant

Pas de modèle : deux horloges qui existent déjà. **V_depuis** = volume échangé
depuis la cassure en multiples du volume de la cassure (le volume est la seule
horloge qui traite 03:00 et 10:00 pareil) ; **n_revisites** de la zone (même
hystérésis que les tests). La courbe se LIT sur 57 jours (déciles), elle ne se
pose pas. Les stops retirés sans exécution restent invisibles par construction.

## Q3 — Les niveaux dynamiques

**Un niveau qui bouge n'est pas testé, il est suivi.** Figer `niveau_prix` au
test, tout calculer contre lui (lève la quarantaine) ; marquer
`derive_niveau` à `i_connu`, exclure des scalaires si |dérive| > p90 ; et les
`cur_*` avant ~90 min de profil cash ne sont pas des niveaux, ce sont des
**estimateurs** (seuil posé sur la stabilité mesurée par heure, pas décrété).

## Q4 — Valeur prédictive sans data mining

Trois garde-fous à ajouter aux nôtres : **états pré-enregistrés avec direction
attendue** (un état sans attendu est exploratoire, pas testable) ;
**Bonferroni sur les états** (ES/NQ corrélés 0,9 comptent 1,3, pas 2) ; **test
de permutation par niveau** (mélanger les étiquettes de niveau entre fiches
d'une même journée, 1 000 fois — si la séparation réelle ne dépasse pas p95 du
mélange, F23 parle de l'heure ou du régime, pas du niveau). Plus la mesure qui
tue proprement : si `n_tests` seul sépare autant que le vecteur complet, le
reste est décoration. Valeur prédictive lue au jour 61 seulement — interdit à
écrire dans `campagne.yaml`.

## Q5 — L'acceptation

Deux barres sont deux unités de temps ; l'acceptation est une **quantité de
volume** : acceptée quand le volume au-delà atteint `v_acc` = p50 du volume
d'une barre 15 min de la même heure (profil horaire déjà mesuré). La cassure
de 15h45 reste `indeterminee` — c'est une information, pas un défaut. Départage
des deux définitions par la mesure (part d'indéterminés par heure + devenir),
pas de troisième définition.

## Q6 — Le lexique

Un mot n'entre dans `recit.py` que s'il a une ligne dans `seuils.yaml` — le
« rien de caché » de L0, appliqué aux mots. « Défense » n'existe qu'après le
seuil (rvol ≥ p50 ET rejet ≥ p75) ; « s'use » exige n_tests ≥ 3 (à 2 c'est une
différence, pas une tendance) ; « carburant/stock/obligation » jamais dans une
fiche, seulement dans H-PIÈGE ; « rotation » = déséquilibre < seuil, une
absence mesurée ; un `cur_*` avant 11h s'appelle « estimateur ».

## Q7 — Le lecteur humain

Journaliser l'état au clic est nécessaire, pas suffisant : il manque le
**contrefactuel**. Alternance en aveugle **pré-tirée par blocs de semaines**
(jours avec carte / sans carte, l'état journalisé dans les deux cas),
annotation **fermée** au clic (la carte disait : tenu/cassé/regagné/rien ;
j'ai cliqué : avec/contre/sans lien), et la carte ne montre **jamais le
devenir de ses propres états** pendant la campagne — c'est un P&L déguisé.

## Q8 — Ce qui manque, ce qui est un mythe

Manque à la fiche (mesurable) : `duree_test_min` (time at price),
`vitesse_approche` (le ralentissement avant la touche = quelqu'un absorbe
avant), `dist_valeur` (un test de VAH à 2 ATR de la VWAP ≠ à 0,3), et
**l'heure comme état**. Probablement des mythes sur 1 min sans carnet : les
« gros prints » comme défense (p95 = 2×p50 ; un print à l'ask peut être un
vendeur qui sort — le delta de fenêtre dit la même chose sans l'ambiguïté),
l'absorption C++ (formule non reproduite), la « troisième fois » (pas
l'effectif — ce n'est pas une règle qu'on mesure, c'est une donnée qu'on n'a
pas). Ce que les desks ont et que nous n'aurons pas : carnet, OI, flux
d'options — chaque phrase qui les sous-entend doit le dire.

## L'ordre qui fait de F23 une brique

1. Cinq scalaires + `duree_test_min`, `vitesse_approche`, `dist_valeur` —
   distributions datées.
2. États pré-enregistrés avec attendu directionnel, Bonferroni.
3. Séparation par scalaire seul puis par état ; permutation par niveau.
4. `cur_*` figés au test, étiquetés par dérive — lève la quarantaine.
5. Avec/sans dans B1n et H7 ; verdict oriente / muette / à retirer.
6. Carte : alternance en aveugle pré-tirée, annotation fermée.
7. Jour 61 : H-PIÈGE (D, R), courbe de décroissance lue.

**Un narratif qui survit à ces sept étapes n'est plus un narratif : c'est une
feature. Un qui n'y survit pas aura quand même donné la carte des stocks —
utile, mesurée, et connue pour ce qu'elle est.**
