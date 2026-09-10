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
