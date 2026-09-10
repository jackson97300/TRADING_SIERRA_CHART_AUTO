# SCÉNARIOS — LE MODULE QUI LIT LA SÉANCE EN CONTINU
*Fable, 10/09/2026. Récapitulation complète de la demande de Jackson, restructurée, augmentée de ce qui manquait. Pour Claude Code : c'est une spec de couche, au même rang que L0 ou F23 — pas un script du matin. Rien ici ne décide ; tout décrit, se journalise, se mesure au jour 61.*

*(Déposée telle quelle le 10/09 par Claude Code. L'ordre de travail est dans `scenarios/MISSION.md` ; les prérequis — `recalc.open_type_r`, `recalc.range_r`, la distribution des largeurs — précèdent la grammaire, que Fable relit avant qu'elle soit codée.)*

---

## 0. La demande, telle que Jackson l'a posée — et ce qu'elle corrige

Jackson a raison sur trois points contre la version précédente :

1. **A, B, C sont des positions d'ouverture, pas des scénarios.** Un scénario est *ce que le prix fait de sa position* : ouvrir sous la valeur, réintégrer, faire un pullback sur la VAL, et monter — c'est un scénario. Ouvrir sous la valeur et rester dessous en est un autre. La position d'ouverture est le **premier état** ; le scénario est une **séquence d'états**.
2. **Un niveau est une zone, pas un prix.** Un prix plus quelques ticks au-dessus et en dessous — la largeur dépend de l'instrument, de la volatilité du jour et de la nature du niveau (une VAL n'a pas la largeur d'un mur d'options). C'est exactement `seuil_ticks` P10 autour du niveau — mais exprimé en **prix**, avec ses deux bornes, jamais un point.
3. **Le module doit être vivant.** Pas une carte de 9h25 : un processus qui consomme les barres à mesure qu'elles arrivent et qui, à chaque barre, dit : les niveaux (zones), le scénario en cours, les réintégrations, ce qui vient de valider, ce qui vient d'invalider, et ce qui s'arme. Comme un desk qui parle toute la séance.

Ce document prend ces trois points et les pousse jusqu'au bout.

---

## 1. Ce qu'est un scénario — une séquence d'états, pas une position

Un scénario est une **grammaire** : une position d'ouverture, puis des transitions observables, chacune datée, chacune avec sa validation et son invalidation. Les briques de cette grammaire existent déjà dans V3 — le module ne les invente pas, il les *assemble* :

| brique | ce qu'elle dit | d'où elle vient |
|---|---|---|
| **position d'ouverture** | au-dessus / dans / sous la valeur de référence (VA de la dernière session complète) | B5, `prev_*` avec `veille_source` |
| **type d'ouverture** (Dalton) | drive / test-drive / rejet-renversement / enchère | `open_type_r` (à recalculer : les deux premières barres et le retour ou non sur l'ouverture) |
| **réintégration** | le prix rentre dans la VA (ou dans l'IB) : *tentée* (une clôture) ou *acceptée* (deux clôtures, ou volume — F23) | fiches F23 sur VAH/VAL, `issue` |
| **pullback** | après réintégration, retour sur le bord franchi qui **tient** (test + tenue F23) | F23 `n_tests`, `issue = tenu` |
| **continuation** | le prix s'éloigne du bord tenu dans le sens de la réintégration : nouveau plus haut/bas de session | `range_r`, plus hauts de session, VWAP en pente |
| **rejet** | test du bord opposé qui tient, ou cassure qui regagne (head-fake) | F23 `regagne`, `D`, `R` |
| **IB** | formée à 10h30, cassée, acceptée, retestée | `ib_*` + F23 sur IB high/low |
| **transition** | longue barre qui sort d'un range établi | `TRANSITION` (P3) |

**Les scénarios canoniques — les séquences qu'un desk nomme** (chacune avec sa validation et son invalidation, en prix) :

| code | séquence | validé quand | invalidé quand |
|---|---|---|---|
| `S_OUV_HAUT_TEND` | ouvre > VAH → pas de retour dans la VA avant 10h30 → IB au-dessus, cassée par le haut acceptée | acceptation > IB high | clôture acceptée dans la VA (devient `S_OUV_HAUT_REJET`) |
| `S_OUV_HAUT_REJET` | ouvre > VAH → réintègre la VA (acceptée) → rotation ou traversée | deux clôtures dans la VA | acceptation > VAH à nouveau (devient `S_OUV_HAUT_TEND` tardif — noté comme *reprise*) |
| `S_OUV_BAS_REINT_PULL` | ouvre < VAL → réintègre (acceptée) → **pullback sur la VAL qui tient** → monte | tenue F23 du pullback + plus haut de session après | cassure acceptée sous la VAL (retour à `S_OUV_BAS_TEND`) |
| `S_OUV_BAS_REINT_TRAV` | ouvre < VAL → réintègre → traverse vers le VAH sans pullback | 80 % franchi | rejet au VPOC accepté |
| `S_OUV_BAS_TEND` | ouvre < VAL → reste dessous → IB sous la VA cassée par le bas | acceptation < IB low | réintégration acceptée |
| `S_DANS_ROTATION` | ouvre dans la VA → IB dans la VA → range `ETABLI` | deux bords tenus ≥ 2 fois | cassure acceptée d'un bord (devient `S_DANS_CASSURE_*`) |
| `S_DANS_CASSURE_HAUT/BAS` | ouvre dans la VA → cassure acceptée d'un bord de VA ou d'IB → continuation ou head-fake | retest tenu du bord cassé | regain avec déséquilibre (head-fake → retour à `S_DANS_ROTATION`) |
| `S_TRANSITION` | n'importe quel état → `TRANSITION` (longue barre hors range) | acceptation au-delà | regain |

La grammaire est **ouverte** : les séquences non canoniques sont journalisées telles quelles (`S_AUTRE` avec la séquence d'états brute). Au jour 61, on saura si les huit couvrent 80 % des jours ou 40 % — et lesquelles manquent.

---

## 2. Les zones d'intervention — un niveau est une bande, en prix

Pour chaque niveau figé de la journée, le module tient une **zone** :

```
{ nom, source (sierra | derniere_complete | snapshot_mq | calcul_jour),
  prix, bas, haut,               # bas/haut = prix ∓ largeur ; largeur par NATURE de niveau et par instrument
  largeur_ticks, largeur_source, # P10 (seuil_ticks sur atr_ref) pour VA/VWAP/IB ; distribution propre pour murs (plus larges) et PDH/PDL
  fiche_f23: {n_tests, issue, D, R, age},   # la mémoire : testée, tenue, cassée, regagnée
  role_dans_scenario: cible | invalidation | pullback | neutre,  # ce que la zone est pour le scénario EN COURS
  setups_armes: [{setup, side, condition_restante}],           # ce qui tirerait ici, et ce qui manque encore
  etat: intacte | testee | cassee | regagnee | atteinte }
```

Trois choses que « un prix ± quelques ticks » ne dit pas et que le module doit dire :
- **La largeur dépend de la nature** : une VAL de la veille et un mur d'options n'ont pas la même largeur — la seconde vient de la distribution des réactions aux murs (à mesurer), pas de P10. Une zone trop étroite manque les réactions, trop large en invente.
- **La zone a un rôle qui change** : la VAL est une *cible* dans `S_OUV_HAUT_REJET`, un *pullback* dans `S_OUV_BAS_REINT_PULL`, une *invalidation* dans `S_DANS_ROTATION`. Le même prix, trois rôles selon le scénario en cours — c'est ce que le trader fait dans sa tête et que personne n'écrit.
- **La zone a une mémoire** (F23) : une VAL testée trois fois et tenue trois fois n'est pas une VAL intacte ; une VAL cassée-regagnée avec `D` élevé est une zone avec des piégés dedans. La fiche fait partie de la zone.

---

## 2 bis. Complément (Fable, 10/09) — les niveaux d'options dans les zones et la grammaire

- **Largeur des murs** : distribution des réactions aux murs (`mq_call` / `mq_put`, `gex_nearest`) sur les 57 jours, par instrument — distance de réaction, part des murs touchés qui réagissent → largeur propre dans `seuils.yaml` zones, `null` avant (prérequis 3 bis).
- **`cote_hvl` dans l'état** : depuis `dist_mq_hvl` (jamais `gamma_block_*`), il fait partie de l'état du scénario ; les zones `mq_*` changent de rôle avec lui — rejet au-dessus, cassure-continuation en dessous. **Le HVL n'est pas une zone**, c'est un côté.
- **Les murs comme zones** : `source: snapshot_mq` + `mq_snapshot_ts` ; un mur qui bouge à midi = événement `ZONE_DEPLACEE`, jamais une correction. Les 0DTE entrent après 14h00 ET seulement, rôle `pin`. Les murs remplissent `prochaine_zone_haut/bas` quand le scénario est hors VA.

---

## 3. Le module vivant — `scenarios.py` en continu

**Cadence** : à chaque barre 15 min close (la décision), avec une lecture 1 min pour les réintégrations tentées (la réaction). Trois instants privilégiés : 9h25 (avant), 10h30 (IB), 12h00 (mi-séance).

**Ce qu'il émet, à chaque barre, dans `LOGS/scenarios/scenarios_<jour>.jsonl` (un écrivain, append-only, `.tmp` + `os.replace`) :**
```
{ ts, sym, heure_et,
  position_ouverture, type_ouverture,
  scenario_en_cours, scenario_depuis (ts), sequence_etats: [...],
  validations: [{quoi, zone, ts}], invalidations: [{quoi, zone, ts}],
  reintegrations: [{zone, tentee_ts, acceptee_ts | null}],
  zones: [...],                       # §2, avec rôle et setups armés
  ce_qui_ne_se_trade_pas: [...],      # les setups hors scénario
  prochaine_zone_haut, prochaine_zone_bas,
  confiance: null }                   # JAMAIS un score — le champ existe pour interdire qu'on l'invente ailleurs
```
**Ce qu'il affiche** (la vitrine, le stream, la carte) : la même chose en une page, lecture seule — le scénario en cours en titre, les zones triées par distance, les validations/invalidations de la dernière heure, ce qui s'arme, ce qui ne se trade pas.

**Ce qu'il ne fait jamais** : décider, bloquer, pondérer, prédire. Il n'entre dans aucune porte. Il ne dit pas « va monter », il dit « `S_OUV_BAS_REINT_PULL` validé à 10h15 par la tenue de la VAL 7 647,00–7 649,25 ; continuation confirmée si nouveau plus haut de session ; invalidé si acceptation sous 7 647 ».

---

## 4. Ce qui manquait à la demande — quatre ajouts

1. **La transition de scénario est un événement, pas une correction.** Quand `S_OUV_HAUT_TEND` devient `S_OUV_HAUT_REJET` à 10h45, le module ne « corrige » pas : il journalise la *bascule* avec son heure et sa cause. Au jour 61, le nombre de bascules par jour et leur heure sont une mesure — la matinée des impatients, c'est là qu'elle se voit.
2. **La lecture rétrospective doit reproduire la lecture en direct.** Test obligatoire : le scénario final journalisé à 16h00 en direct = celui que le rejeu du soir calcule sur la journée complète. Sinon le module « sait » des choses après coup qu'il ne savait pas à 10h30 — la fuite d'avenir de F23, encore.
3. **Le scénario est le dénominateur de tout le reste.** Chaque signal de l'entonnoir, chaque fantôme, chaque ligne de marge porte `scenario_en_cours` au moment du signal. Règle 39 du jour 61 : *chaque déclencheur se lit par scénario.* H3 short au VAH dans `S_OUV_HAUT_REJET` et dans `S_DANS_ROTATION` sont deux populations.
4. **Le module se mesure lui-même.** Trois nombres, avant tout usage : la part des jours couverts par les huit scénarios canoniques ; la part des scénarios validés qui *tiennent* jusqu'à la clôture (validé à 10h30, encore vrai à 16h00) ; et — le contrôle négatif — un scénario tiré au sort par jour doit faire pire que la grammaire sur ces deux mesures. Un module de scénarios qui décrit aussi bien qu'un tirage au sort décrit le passé, pas la séance.

---

## 5. Ce qu'il consomme, et ce qui manque pour le construire

| entrée | état |
|---|---|
| `prev_*` dernière session complète, `veille_source` | fait (brique 1) |
| B5 recalculé, position d'ouverture | fait |
| F23 fiches (`n_tests`, `issue`, `D`, `R`), zones figées | `prev_*` fiables ; `cur_*` en quarantaine — le module n'utilise que les figées |
| `seuil_ticks` sur `atr_ref` → largeur en prix | fait (brique 1) |
| `exposer()` → setups armés et lieux en prix | fait (brique 2) |
| `open_type_r` (type d'ouverture Dalton) | **à recalculer** (deux premières barres, retour sur l'ouverture) |
| `range_r` (machine à états ETABLI/CASSE/RETEST) | **à écrire** (post-it §2) |
| largeur des zones par nature (murs, PDH/PDL) | **à mesurer** (distribution des réactions par type de niveau) |
| acceptation en volume (Q5 F23) | option ; deux clôtures d'abord |

Deux prérequis (`open_type_r`, `range_r`) et une mesure. Le reste est là.

---

## 6. Ordre — après le gel, avant EXEC ou en parallèle

1. `open_type_r` + `range_r` dans `recalc.py` (les deux manquent au post-it aussi).
2. La grammaire (§1) et les zones (§2) en code, journal §3 — d'abord en **rejeu** sur les 57 jours : les trois mesures du §4.4 avant tout affichage.
3. Le test « direct = rétrospectif ».
4. Le mode vivant, branché sur le coureur (lecture seule), puis la page.
5. Règle 39 ; `scenario_en_cours` sur toutes les lignes de journaux.

Deux à trois jours de Claude Code, aucun risque pour la campagne : le module lit, il n'écrit que son propre journal.

---

## 7. Ce que Jackson y gagne, sans trader
La séance racontée par une machine dans les mots d'un desk — ouverture, réintégration, pullback, validation, invalidation, zones avec leur mémoire — en continu, contre-lisible, et mesurée contre elle-même. C'est la carte du matin devenue un narrateur de séance. Et c'est le contenu du stream : pas un bot qui trade, un bot qui *lit* et qui dit ce qu'il attend pour agir. Personne ne montre ça, parce que personne ne l'a écrit.

---

## 8. L'auto-évaluation du soir — apprendre sans se dérégler

Jackson demande que le module, à la fin de la journée, regarde ce qu'il a fait de mal, ce qu'il aurait dû faire, et apprenne au fur et à mesure. Oui — à une condition qui sépare l'apprentissage de la dérive : **il note, il ne se règle pas.**

**Ce qu'il évalue chaque soir — sur la description, jamais sur un gain :**
| question | mesure | erreur nommée |
|---|---|---|
| Le scénario validé à 10h30 était-il encore vrai à 16h00 ? | `scenario_10h30 == scenario_final` | `VALIDATION_PRECOCE` (validé sur une réintégration *tentée*, pas acceptée) |
| Les bascules étaient-elles nécessaires ? | nombre de bascules ; bascule suivie d'un retour au scénario précédent en < N barres | `BASCULE_FANTOME` (a réagi à une mèche, pas à une acceptation) |
| Les zones ont-elles réagi ? | part des zones *touchées* qui ont produit une réaction F23 (tenue ou cassure acceptée) | `ZONE_TROP_LARGE` (touchée sans rien) / `ZONE_TROP_ETROITE` (réaction à 1–2 ticks hors bande) |
| Les rôles étaient-ils justes ? | la zone marquée *cible* a-t-elle été atteinte ; celle marquée *invalidation* a-t-elle été respectée | `ROLE_INVERSE` |
| Le « ne se trade pas » a-t-il tenu ? | un setup déclaré hors scénario a-t-il produit un lieu atteint avec réaction | `EXCLUSION_FAUSSE` |
| La lecture rétrospective diffère-t-elle ? | rejeu du soir vs journal en direct | `FUITE` — incident, pas erreur |

Chaque erreur est une ligne dans `LOGS/scenarios/erreurs_<jour>.jsonl` : type, heure, zone, scénario, **ce qui aurait été juste** (la valeur observable qui aurait évité l'erreur : « acceptée à 10h45, pas tentée à 10h30 »). C'est le « ce qu'il aurait dû faire » — sur des états, pas sur des trades.

**Ce qu'il apprend — et comment, sans toucher un paramètre en campagne :**
- Le module tient un **carnet** : par type d'erreur, le compte cumulé, les jours, et l'ajustement *candidat* (« largeur des murs : p75 des réactions au lieu de P10 » ; « validation = acceptation, jamais tentative »). Le carnet est lisible tous les soirs ; il est le contenu du stream le plus honnête qui soit.
- **Aucun ajustement ne s'applique en cours de campagne.** Un module qui se règle sur ses erreurs d'hier optimise sur l'échantillon qu'il va juger — c'est l'auto-tuning qui a tué le grid search (528 essais, 0 survivant). Les candidats du carnet se **pré-enregistrent** pour le cycle suivant, chacun avec son attendu, et se mesurent depuis zéro sur des jours neufs.
- **Le seul apprentissage immédiat autorisé** : les *règles de grammaire* qui ne sont pas des seuils — « une réintégration tentée ne valide pas », « un rôle se fige à la validation ». Ce sont des définitions, comme la sortie horaire ; elles se corrigent le jour même, avec la ligne DECISIONS, parce qu'elles ne découpent aucune distribution.
- **La mesure de l'apprentissage** : le taux d'erreurs par type, par bloc de deux semaines. S'il baisse sans qu'un paramètre ait bougé, la grammaire s'améliore ; s'il ne baisse qu'après un ajustement de cycle, c'est l'ajustement — et on le sait.

---

## 9. Les TP et SL du scénario — des sorties, pas des conseils

Un scénario porte naturellement ses sorties, et c'est L5 qui les connaît déjà :
- **TP du scénario** = la prochaine zone dans le sens du scénario, moins la marge (`B-NAT` / `B-NIV`, « devant l'obstacle, jamais derrière un mur ») — dans `S_OUV_BAS_REINT_PULL`, c'est le VPOC puis le VAH ; dans `S_OUV_HAUT_REJET`, la VAL.
- **SL du scénario** = derrière la zone d'*invalidation* du scénario, plus le buffer de balayage (`B-NIV`, `buffer_sweep_atr`) — le stop est là où le scénario meurt, pas à une distance fixe. C'est exactement la règle V1 de Jackson, avec le scénario comme raison du placement.
- **Le module les journalise comme une variante de barrière — `B-SCEN`** — sur chaque signal, à côté de B-ATR, B-NIV, B-NAT : hors ligne, mesurée au jour 61 avec `stats.py`, jamais appliquée en campagne. Attendu : moins de SL touchés que B-ATR (le stop est derrière une invalidation), TP plus courts, espérance inconnue.
- **Le mot.** Sur la vitrine et en stream, ce ne sont pas des « TP/SL conseillés » — ce sont **les sorties du scénario** : « ce scénario se termine ici, et meurt là ». La différence n'est pas cosmétique : un TP conseillé à un abonné est un conseil en investissement ; une sortie de scénario est une description de la structure. Le module décrit où le scénario finit ; il ne conseille personne.

Trois lignes de plus dans le journal de chaque signal, aucune logique nouvelle : L5 sait déjà placer, le scénario dit seulement *derrière quoi* et *devant quoi*.
