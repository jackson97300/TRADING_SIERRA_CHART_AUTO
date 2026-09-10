# SCÉNARIOS — l'ordre de travail (Fable, 10/09/2026)

*Ce fichier est l'ordre, pas la spec : la spec est `V3/SCENARIOS_SPEC.md`, à
lire en entier d'abord. Le module se construit APRÈS le gel du 11/09, en
parallèle d'EXEC. Il ne décide rien, n'entre dans aucune porte, n'écrit que
ses propres journaux.*

## Règles dures, non négociables
- Aucun seuil dans le code ; `scenarios/seuils.yaml`, `null` tant que la
  distribution n'existe pas.
- Un scénario est une séquence d'états datés ; la grammaire des huit
  canoniques (spec §1) est **ouverte** : tout ce qui n'entre pas est `S_AUTRE`
  avec sa séquence brute.
- Une zone est `{prix, bas, haut}` — jamais un point ; largeur par nature de
  niveau (P10 sur `atr_ref` pour VA/VWAP/IB ; distribution propre pour murs et
  PDH/PDL, `null` tant que non mesurée).
- Niveaux **figés** seulement (`prev_*` dernière session complète, ON,
  PDH/PDL, IB après 10h30, murs au snapshot) — les `cur_*` restent en
  quarantaine.
- `confiance` existe et vaut `null`. Aucun score, aucune direction attendue,
  aucun mot conclusif (« va », « devrait ») dans les sorties texte — un test
  `grep` l'interdit.
- L'auto-évaluation **note, ne règle pas** : le carnet d'erreurs (§8)
  propose des candidats pré-enregistrés pour le cycle suivant ; aucun
  paramètre ne bouge en campagne. Seules les règles de grammaire
  (définitions, pas seuils) se corrigent le jour même avec ligne DECISIONS.
- Les sorties de scénario s'appellent **sorties**, jamais « conseil » ;
  `B-SCEN` est une variante de barrière hors ligne, comme B-NIV.

## Prérequis, dans cet ordre (deux manquent)
1. `recalc.open_type_r` — le type d'ouverture Dalton depuis les deux
   premières barres 15 min et le retour ou non sur `open_cash_lvl`.
   Distribution des quatre types sur 57 jours avant usage.
2. `recalc.range_r` — la machine à quatre états du post-it
   (`FORMATION/ETABLI/CASSE/RETEST`) sur deux fiches F23 face à face,
   `compression` incluse ; test au tick sur deux journées.
3. Distribution de la largeur des réactions par nature de niveau →
   `seuils.yaml` zones.

**Point de relecture Fable : après 1-3, AVANT la grammaire** — « c'est la
grammaire qui décide de tout ce que le module pourra dire, et c'est le
moment où une paire d'yeux coûte le moins ».

## Construction — d'abord en rejeu, jamais en direct avant les trois mesures
4. `grammaire.py` (états, transitions, validations/invalidations en prix),
   `zones.py` (§2), `scenarios.py` (le journal §3, `.tmp` + `os.replace`, un
   écrivain), `erreurs.py` (§8), `sorties.py` (`B-SCEN` dans `barrieres.py`,
   §9).
5. **Rejeu sur les 57 jours**, puis les trois mesures de la spec §4.4,
   écrites dans `rapports/scenarios_57j.md` **avant** tout affichage : part
   des jours couverts par les huit ; part des scénarios validés à 10h30
   encore vrais à 16h00 ; contrôle négatif — un scénario tiré au sort par
   jour, mille tirages, doit faire pire sur les deux.
6. **Test « direct = rétrospectif »** : le scénario final journalisé barre à
   barre = celui du rejeu sur la journée complète ; tout écart est une fuite
   d'avenir → incident.
7. Le mode vivant branché sur le coureur (lecture seule) ; la page texte ;
   la tâche.
8. `scenario_en_cours` sur chaque ligne de l'entonnoir, des fantômes, des
   marges ; règle 39 dans `LECTURE_JOUR_61` : *chaque déclencheur se lit par
   scénario.*

## Tests, minimum
Un par état de la grammaire (validé / invalidé / bascule), LONG et SHORT en
miroir ; zone = bande (un prix au bord bas est dedans, un tick en dessous
est dehors) ; rôle qui change avec le scénario (la même VAL cible /
pullback / invalidation) ; `S_AUTRE` produit sur une séquence inconnue ;
aucun mot conclusif ; l'auto-évaluation nomme chaque type d'erreur sur un
cas synthétique ; `B-SCEN` en parité avec `barrieres.py` sur SL derrière
l'invalidation + buffer.

## Livrable
`scenarios/` (< 300 l. par fichier), tests, `rapports/scenarios_57j.md`,
`seuils.yaml`, lignes DECISIONS (module pré-enregistré, attendu des trois
mesures écrit avant), règle 39. Review interne, 14 contrôles, hash après le
`-> master`.

## Complément Fable (10/09) — les niveaux d'options
*À intégrer à l'étape 3 et à la grammaire ; ne change rien aux étapes 1-2.*
- **Prérequis 3 bis** : distribution des réactions aux murs (`mq_call` /
  `mq_put`, `gex_nearest`) sur les 57 jours, par instrument — distance de
  réaction, part des murs touchés qui réagissent → largeur propre dans
  `seuils.yaml` zones, `null` avant.
- **Grammaire** : l'attribut `cote_hvl` (depuis `dist_mq_hvl`, jamais
  `gamma_block_*`) fait partie de l'état du scénario ; les zones `mq_*`
  changent de rôle avec lui — rejet au-dessus, cassure-continuation en
  dessous. **Le HVL n'est pas une zone.**
- **Zones** : les murs entrent avec `source: snapshot_mq` et `mq_snapshot_ts` ;
  un mur qui bouge à midi = événement `ZONE_DEPLACEE`, jamais une correction.
  Les 0DTE entrent après 14h00 ET seulement, rôle `pin`. Les murs remplissent
  `prochaine_zone_haut/bas` quand le scénario est hors VA.

## Les dix décisions de Fable (10/09, après les prérequis 1-2) — s'appliquent à la grammaire
1. **Tenue causale, jamais l'`issue` F23.** La grammaire ne consomme que
   `tenu_a` (la clôture suivante) et les acceptations à deux clôtures ;
   `issue` reste pour F23 et le jour 61. Test : la grammaire rejouée barre à
   barre ne lit aucune colonne dont le calcul dépend de i+2 ou au-delà
   (direct = rétrospectif sous une autre forme).
2. **v0 : un range par journée, l'IB.** Après une `CASSE` acceptée, le
   scénario est `S_DANS_CASSURE_*` jusqu'à un regain ou la clôture ; les
   journées à deux ranges tombent en `S_AUTRE` et se comptent — premier
   candidat du cycle 2 si `S_AUTRE` en est plein.
3. **ETABLI reste strict** (deux tenues par bord) ; l'état de séquence
   `POSE` (« bords posés, aucune acceptation dehors ») décrit sans valider —
   `range_r` journalise `barres_depuis_pose`. Si la mesure dit peu d'ETABLI,
   c'est une information, pas une raison de baisser à une tenue.
4. **Zones asymétriques** : `dehors` = p80 des dépassements sur les tests
   TENUS, `dedans` = P10 `seuil_ticks` ; `quantile_contenance: 0.80` (p90
   contient les balayages qui sont des cassures tentées).
5. **`ZONE_DEPLACEE` par les données** (saut > 1 tick du niveau reconstruit
   entre deux barres), journalisé avec l'heure ; le brut n'a pas de
   `mq_snapshot_ts` — à demander au DMP (NEXT_CYCLE).
6. **Compression sur l'EXTRÊME** de la barre du test, pas sa clôture.
7. **Le tag : demain matin**, hash de la tête à 9h00 Paris, relecture, tag
   avant l'ouverture — les deux recalculs seront dedans.
8. **Règle 39 décrit, elle ne découpe pas** : le scénario est une colonne de
   contexte au jour 61, jamais une partition du verdict (N ≥ 40 par case
   pour partitionner — cycle 2 ou au-delà).
9. **Les trois attendus du rejeu, signés relectrice** : couverture 60 %
   (< 45 % trop courte, > 80 % trop large) ; validés à 10h30 encore vrais à
   16h00 : 55 % (< 40 % trop précoce) ; contrôle négatif battu d'au moins
   15 points sur les deux. Dans `seuils.yaml` et DECISIONS avant le rejeu.
10. **0DTE `dormant` avant 14h00 ET** dans le journal, absents des zones
    affichées et des rôles ; `cote_hvl` : `dist_mq_hvl < 0` = prix au-dessus
    du HVL = gamma positif — prouvé sur barres réelles (`tests/test_cote_hvl.py`).

## Relecture Fable à `e26236a` (10/09) — les écarts tranchés, les valeurs fixées
*« C'est la bonne façon d'arriver à des seuils : les nombres sont là, `null` en
attendant, et c'est à moi de fixer. »* Les valeurs sont dans `seuils.yaml`
(v2026-09-10b) ; ici, les décisions.
- **Écart 1 — DRIVE n'existe pas à ce grain, on ne le force pas.** Trois
  types en v0 : `TEST_DRIVE`, `REJET_RENVERSEMENT`, `ENCHERE` ; DRIVE
  fusionné dans TEST_DRIVE avec `retour_open` journalisé (false = jamais
  revenu sur l'ouverture, ce qu'il reste du drive) ; la traversée sur les
  premières minutes 1 min = candidat cycle 2, pré-enregistré.
- **Écart 2 — l'IB est plus large que le post-it, et c'est normal** : les
  0,8-2,5 décrivaient un range de milieu de séance. `w_min / w_max` = p10 /
  p90 par instrument ; hors de ça, `S_AUTRE(IB_hors_norme)`.
- **Écart 3 — les mèches s'allongent avant la cassure : on ne renverse pas
  l'hypothèse après coup.** Même définition, colonne renommée `pression`
  (> 1 = le marché s'appuie sur le bord), journalisée, pas un état, aucun
  seuil en v0 ; **H-PRESSION** pré-enregistrée cycle 2 (NEXT_CYCLE §5 nonies).
- **Écart 4 — aucune nature contenue par P10** : `dedans` reste P10 (la
  proximité qui déclenche), `dehors` = p80 mesuré (la bande qui contient).
  VA_veille provisoire (w0), re-mesure au jour 20 de w1 ; murs NQ = pas une
  zone ; VWAP et GEX_nearest = null définitifs.
- **ETABLI 0 / 57 et 1 / 57 = attendu, et un fait exige une neuvième
  séquence maintenant** : 53 % des premières cassures échouent →
  `S_DANS_HEADFAKE` (cassure acceptée → regain à deux clôtures → retour dans
  l'IB) ; `S_DANS_POSE` (IB posée, aucune acceptation dehors jusqu'à la
  clôture, 25 % des jours) canonique v0 ; `S_DANS_ROTATION` gardé pour
  l'ETABLI rare. **Grammaire v0 = huit canoniques autrement composées** :
  `S_OUV_*` ×5 + `S_DANS_POSE` + `S_DANS_CASSURE_*` + `S_DANS_HEADFAKE`.
- Les deux faits de données acceptés et déclarés ; `mq_snapshot_ts` au DMP
  dans NEXT_CYCLE. Attendus du rejeu inchangés (60 % / 55 % / 15 points).
- **« La grammaire peut se coder maintenant sur ces valeurs. »** Tag demain
  9h00 Paris sur la tête, relecture du périmètre gelé, tag avant l'ouverture.

## Relecture Fable à `c6c12dd` (10/09 soir) — trois arbitrages, trois demandes
- **La couverture, c'est la 1 bis** : les scénarios VALIDÉS à la clôture
  (58 % / 53 %, dans l'intervalle). Le 93 % « en cours » est une *position*
  déguisée en scénario — exactement ce que Jackson reprochait à A/B/C. La
  définition pré-enregistrée était mal posée par la relectrice, elle le note ;
  l'« en cours » reste journalisé comme part de journées avec une hypothèse
  ouverte. Le titre affiche l'état : `(en cours, non validé)` en gris,
  `(validé 10h45)` en clair ; un scénario non validé ne fait rien s'armer.
- **La tenue à 10h30 sur N = 5 / 4 : vrai et trop petit, pas de verdict** ; se
  lit au jour 20 de w1 ; la 2 bis (67 % / 64 % sur 54) est le proxy déclaré.
- **Les deux définitions validées, avec une correction de nom** :
  `S_OUV_HAUT_REINT` (famille) avec `precision ∈ {PULL, TRAV, null}`, miroir
  exact de `S_OUV_BAS_REINT` ; `S_OUV_HAUT_REJET` disparaît. Une famille avec
  `precision: null` est un canonique. Rejet au VPOC 1 / 57 : compté, jour 20.
- Demandes avant le mode vivant, **faites** : (a) le renommage — et pour que le
  miroir soit exact, la famille REINT est validée par l'ACCEPTATION des deux
  côtés, PULL / TRAV sont des précisions datées (choix dit tel quel) ; (b)
  `etat_scenario ∈ {en_cours, valide, invalide}` + `titre` + `arme` sur chaque
  ligne ; (c) la réserve w0 en gras en tête du rapport — les vrais nombres
  commencent le 10/09 au soir, 23h01, en w1.

## La vitrine et les alertes — plan arrêté avec Fable (10/09 soir), APRÈS le tag du 11/09
Trois choses séparées, jamais fondues : **l'écrivain** (un processus, là où
sont les données, sans écran — `scenarios.py --direct` en boucle à chaque
clôture de 15 min), **la vitrine** (une page HTML sans état qui lit le journal :
titre avec son état, zones triées par distance, validations / invalidations
de la dernière heure, ce qui s'arme, ce qui ne se trade pas, les sorties du
scénario — jamais le mot « conseil »), **les alertes** (un lecteur du journal
qui sonne sur cinq ÉVÉNEMENTS — bascule, validation, invalidation, zone
cassée, `ZONE_DEPLACEE` — jamais sur un état en cours ; un muet ; silence les
cinq premières minutes).
- Ordre : local d'abord (PC, `localhost`, zéro fichier sur le VPS) ; le VPS
  (service nssm à côté des données) et la page du dashboard après le jour 20
  de w1 et une relecture — même HTML, déploiement sur confirmation explicite.
- Pas de logiciel de bureau (Tkinter, PyQt : cul-de-sac), mais **une fenêtre**
  : `pywebview`, native, always-on-top, qui affiche LE MÊME HTML que la
  vitrine — un onglet de navigateur disparaît derrière Sierra. Une seule page,
  deux façons de l'ouvrir.
- Ensuite seulement : la voix (`pyttsx3`) quand les événements auront prouvé
  qu'ils valent d'être entendus ; le study Sierra en dernier.
- La règle qui protège tout : **la page lit, elle n'écrit que dans le journal
  manuel, jamais ailleurs**. Et dater le moment où Jackson regarde :
  `scenarios_visibles : oui/non` dans `journal_manuel/<jour>.md`, comme
  `carte_visible` — les clics cessent d'être indépendants de la machine, la
  ligne « trader vs machine » du jour 61 se lit en deux populations.

## Liste fusionnée (Fable, 10/09 soir) — phase A CODÉE le 10/09, sur ordre de Jackson
Seize fichiers, trois phases (le document de Fable fait foi). Phase A, faite :
`SPEC_VITRINE.md` (A0) ; `boucle.py` + `execution/scenarios.bat` +
`execution/garde_scenarios.py/.bat` (A1 — le garde est en Python comme celui du
coureur, pas en `.ps1` : même code, même leçon du 07/09 ; `direct_<jour>.jsonl`
DISTINCT de `scenarios_<jour>.jsonl` du rejeu, `grammaire_version` +
`seuils_version` sur chaque ligne) ; `vitrine.py` + `vitrine.html` (A2, la seule
source HTML, `/etat.json`, NOTER, MUET) ; `alertes.py` (A4, cinq événements,
gabarits dans le yaml) ; `tests/test_vitrine_alertes.py` (A5) ; `fenetre.py`
(A3, pywebview installé sur le PC) ; `scenarios_visibles` dans le journal
manuel lu par `pourquoi_plus` (A6) ; `noter.py` (A6 bis). Rien n'est lancé en
tâche avant le tag ; les `.bat` portent la commande `schtasks`. Phase B et C :
après relecture, puis jour 20 de w1.

## État de la construction (10/09 soir) — à relire par Fable AVANT `scenario_en_cours` sur l'entonnoir
- Étape 4 **faite** : `grammaire.py` (huit canoniques v0 + `S_DANS_ROTATION` +
  `S_AUTRE(raison)` ; `S_OUV_BAS_REINT` = famille sans précision ; codes
  asymétriques par nom, logique en miroir — NEXT_CYCLE §5 nonies), `zones.py`
  (bande asymétrique dedans P10 / dehors p80, mémoire F23 CAUSALE, cassée /
  regagnée à deux clôtures, `ZONE_DEPLACEE` avec la barre, 0DTE dormant avant
  14h00 ET), `scenarios.py` (rejeu et direct par la MÊME fonction `derouler`,
  journal `.tmp` + `os.replace`, un écrivain), `erreurs.py` (sept erreurs
  nommées, chacune avec « ce qui aurait été juste », carnet cumulé, candidats
  pré-enregistrés — aucun paramètre ne bouge), `sorties.py` (`B-SCEN` : TP
  devant la zone cible − marge B-NIV, SL derrière la zone d'invalidation +
  buffer B-NIV, `None` + motif sans zone).
- Tests **faits** : `test_grammaire` 24/24 (un état par scénario validé /
  invalidé / bascule, miroir, bande au tick, rôles, S_AUTRE, mots conclusifs,
  ZONE_DEPLACEE, DIRECT = RÉTROSPECTIF sur quatre journées synthétiques),
  `test_scenarios_soir` 18/18 (chaque erreur nommée sur un cas synthétique,
  B-SCEN en parité de formule avec `barrieres.b_niv`, miroir, sans conseil).
- Étape 5 **faite** : `mesure_scenarios.py` → `rapports/scenarios_57j.md`
  contre l'attendu de la relectrice (lire le rapport, pas ce résumé).
- Étape 6 : direct = rétrospectif prouvé sur synthétique ([8]) et sur ES/NQ
  09/09 pour `range_r` ; sur une VRAIE journée en direct, c'est `erreurs.py`
  qui le vérifie chaque soir (`FUITE` = incident) — première journée : 10/09.
- Étape 7 **faite** en lecture seule : `scenarios.py --direct` (barres
  complètes), appelé par `direct.py` ; rythme du soir étape 5b/5 =
  `erreurs.py`. La page texte / la vitrine : pas encore.
- Étape 8 **pas faite, volontairement** : `scenario_en_cours` sur les lignes
  de l'entonnoir, des fantômes et des marges touche `chaine.py` — après la
  relecture de Fable, jamais avant le tag. Règle 39 déjà écrite.
