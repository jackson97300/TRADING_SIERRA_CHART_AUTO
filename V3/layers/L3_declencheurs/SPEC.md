# SPEC L3 — les quatre déclencheurs du cycle, GELÉS

*Gelée le 08/09/2026 — bloqueur n° 4 de la revue Fable (`A_FAIRE_08_09.md` §1) :
« les déclencheurs vivent hors du miroir » n'est pas un état publiable. La
source de vérité EXÉCUTABLE reste `CORE/research/hypotheses.py` du dépôt privé
(`LES_QUATRE`, protégée par le tag `mission-phase2-v1` et le pré-enregistrement
cycle 2 du 06/09). Ce fichier RECOPIE les définitions mot pour mot pour que le
miroir les porte ; si les deux divergent, le code tagué a raison et ce fichier
se corrige par commit.*

**Rien ici ne se modifie pendant la campagne.** Une idée née en relisant cette
spec va dans `NEXT_CYCLE.md`, jamais dans le code.

---

## Unités et planchers — communs aux quatre

La source d'erreur n° 1 du dépôt (huit confusions d'échelle) :

- `atr_barre` est en **POINTS** (barre agrégée 15 min, calculée sur high/low).
- Les `dist_*` sont en **TICKS** (tick = 0,25 sur ES et NQ).
- La SEULE conversion admise : `seuil_ticks()` = `max(fraction × ATR/tick,
  plancher en ticks)`. Comparer une `dist_*` à `fraction × atr_barre` en points
  donnerait un seuil quatre fois trop grand, silencieusement.

| plancher | définition | usage |
|---|---|---|
| P05 | max(0,05 ATR, 1 tick) | borne fine |
| P10 | max(0,10 ATR, 2 ticks) | proximité |
| P15 | max(0,15 ATR, 3 ticks) | retest |
| P20 | max(0,20 ATR, 4 ticks) | absorption |

Une colonne absente rend NaN : une hypothèse **ne déclenche jamais sur une
donnée manquante**, et ne lève pas non plus — le rapport dit `N = 0`.

---

## H3-VPOC — rejet à l'extrême de la VA courante, cible VPOC

*La seule des quatre attendue TESTABLE.*

- **RÉGIME** : ROTATION.
- **LIEU** : `dist_cur_vah` dans ± P10 (short) / `dist_cur_val` (long).
- **RÉACTION** : la barre t sort de la VA (high > VAH) ET clôture < VAH ET
  `finish_delta_pct` < 0,4 ; miroir pour le long.
- **SIDE** : SHORT / LONG.
- **COLONNES** : `dist_cur_vah/val`, `inside_cur_va`, `finish_delta_pct`.
- **Convention de signe** : `dist_cur_vah = VAH − close`, en ticks — positive
  sous le VAH. « Sortir puis revenir » se lit `high > VAH` (la mèche dépasse)
  et `dist_cur_vah > 0` (la clôture est revenue dessous).
- **CIBLE** : lieu et réaction sont EXACTEMENT ceux de H3 du cycle 1 ; seule la
  cible change, et c'est le runner qui la porte — barrière par famille =
  **VPOC atteint** (la seule des quatre à l'utiliser).

## H2p — fade des bandes VWAP-SD2, régime RECALCULÉ

*ANNONCÉE NON TESTABLE avant de tourner.*

- Identique à H2 du cycle 1, sauf le régime : `ib_range_atr_r < 0,8`
  (points sur points) au lieu de la colonne livrée, qui divise des ticks par
  des points (facteur 4).
- **LIEU** : `dist_vwap_rth_sd2u_r` dans [−P15 ; +P10] (short) /
  `dist_vwap_rth_sd2d_r` dans [−P10 ; +P15] (long).
- **RÉACTION** : `delta_bar` < 0 ET `finish_delta_pct` < 0,4 (short) ; miroir.
- **SIDE** : SHORT / LONG.
- **Pourquoi non testable** : au cycle 1 la réaction ramenait 27 signaux à 3,
  et le régime corrigé ne coupe presque plus (141 sur 143).

## H6p — retest de l'IB après cassure acceptée, régime RECALCULÉ

*ANNONCÉE NON TESTABLE.*

- Identique à H6, régime `ib_range_atr_r < 0,4`.
- **LIEU** : `ib_broken_up` = 1 ET `dist_ib_high` dans [−P15 ; +P05] ;
  miroir bas.
- **RÉACTION** : clôture au-dessus de l'IB high ET `finish_delta_pct` > 0,6 ;
  miroir. `dist_ib_high = IB_high − close`, négative quand la clôture est
  AU-DESSUS : ce signe distingue le retest par le haut du retest par le bas.
- **SIDE** : LONG / SHORT.
- **Pourquoi non testable** : le régime corrigé couvre 56 % des barres au lieu
  de 0,13 %, mais le LIEU ne rend que 58 signaux ES / 65 NQ, ramenés à 37 / 35
  par le régime — sous le seuil de 40 avant même la réaction.

## H8p — absorption à un niveau, seuils recalibrés sur LEUR distribution

*ANNONCÉE NON TESTABLE — et pas seulement sous-dimensionnée.*

- **LIEU** : ≤ P20 d'un niveau de référence (VA veille ou courante, murs
  d'options, PDH/PDL, ONH/ONL — les dix colonnes `dist_*` de la liste
  `NIVEAUX_H8`).
- **RÉACTION** : `rvol_r` ≥ 1,8 ET `delta_pct` ≤ −0,18 (long) / ≥ +0,18
  (short) ET `finish_delta_pct` contraire au delta (> 0,6 long / < 0,4 short).
  Les seuils sont le p90 MESURÉ de chaque colonne (`|delta_pct|` : médiane
  0,069, p90 0,175) — 2,0 et 0,30 étaient hors distribution.
- **SIDE** : LONG / SHORT.
- **`rvol_r` et non `rvol`** : le C++ initialise `rvol = 1.0` (« normal par
  défaut ») quand son ring buffer n'est pas prêt, et 1,0 est une valeur valide
  — « normal mesuré » et « jamais calculé » y sont indistinguables
  (CONVENTIONS §3.1, incident du 06/09).
- **Pourquoi non testable** : même desserrée à 1,5 / 0,15 elle ne rend que 8
  signaux ES et 7 NQ. **Ce n'est pas un seuil à corriger, c'est une conjonction
  impossible** — un rvol élevé, un delta fort et un finish contraire ne
  coexistent presque jamais. Elle est lancée pour que ce soit écrit, pas parce
  qu'on l'espère.

---

## Ce que « annoncée non testable » veut dire

L'attendu est écrit AVANT de tourner : N sous le seuil de 40 pour H2p, H6p et
H8p. « Non testable » signifiera « trop rare pour ce lot », jamais « le setup
est mauvais » — et un N au-dessus du seuil serait une SURPRISE à documenter,
pas une validation. Le mode ombre est leur seule voie ce cycle.

L'entonnoir du rapport sépare toujours `lieu seul → + régime → + réaction` :
sans ces étages, « non testable » ne dit pas si c'est le lieu qui est rare, le
régime qui ne mord jamais, ou la réaction qui est stricte — c'est précisément
ce qui a manqué à la lecture du 06/09, où H6 rendait N = 0 sans qu'on voie que
son régime couvrait 0,13 % des barres.
