# TODO — 10/09 : la passe lecture (R3 + A1 + B3), avant le gel

*Brief Fable 10/09. Zéro touche à ce que la chaîne décide ; trois portes
cessent de mentir ou de se taire. Les cases se cochent au fur et à mesure,
la dernière porte le hash du miroir.*

## Ce matin (Jackson + Claude)
- [x] L6 : F15 en INFO (`motif=derive_feature`) — `etat_l6(20260910) = False`,
      le live du 10/09 s'ouvre (commit `41412e7`)
- [x] Rollover : commande lancée à **10h01 Paris** — ES 480 / NQ 481 lignes,
      100 % U26, calendrier Z26 → **ligne B** (DECISIONS, YAML observée, fiche).
      Restent : redémarrage coureur 15h15 (ancien YAML en mémoire) ; ce soir
      heure de bascule + `max(atr_barre)` ; 11/09 matin remise appliquée si le
      fichier ouvre en Z26.
- [ ] `journal_manuel/20260909.md` : la ligne de 11h15 (Jackson)

## La passe lecture
- [x] **0. Découper `lecture.py`** (299/300) → `lecture.py` (216 au découpage,
      235 après R3/A1/B3 ; `lire()` + le contrat + bloc L4) + `lecture_colonnes.py` (108 : REQUISES,
      `SOURCES_DECLAREES`, `val/vrai/_texte`, `verifier_colonnes`), ré-exportés.
      Huit tests verts avant et après ; identité ligne à ligne vérifiée au
      re-rejeu de l'étape 4 (les « avant » sont fabriqués avec ce code).
      *(Miroir des arbitrages Fable : `54a438e`.)*
- [x] **1. R3** — `lec` expose `atr_ref` et `atr_source` (sans recalculs :
      `atr_ref = atr_barre`, `atr_source = absent`, visible) ; `vetos._frais`
      et `_dist_hvl_atr` sur `atr_ref`. Test réel (03/09 barre 4, 10h30) :
      FRAIS et REGIME répondent, `atr_source = veille` sur chaque ligne.
- [x] **2. A1 minimal** — `lire(side)`, `chaine` le passe ; `_gamma` → `None`
      pour un SHORT et un sens inconnu ; LONG inchangé. Test miroir 4 cas.
      Garde YAML réécrite : « en strict, le trou bloquerait TOUS les shorts —
      ne pas promouvoir avant la passe complète ». LECTURE règle 36.
- [x] **3. B3** — `rang_du_jour = (minutes_et − 570) // 15` ; fail-loud sur
      une barre hors grille (le `ts`). *Écart au brief, motivé* : pas d'assert
      « le cash commence à 9h30 » dans `lire()` — le battement live passe
      `full_agg` (la nuit) et un coureur lancé en retard est légitime ; avec
      le rang lu sur l'heure, un cash qui commence à 9h45 rend 1, plus 0 —
      le défaut que l'assert visait n'existe plus. Test : 9h15 → −1/0/1,
      9h45 → 1, hors grille → lève, PREMIERE_BARRE inchangée (2 bloque, 5 passe).
      `test_passe_lecture` 15/15.
- [x] **4. Attendu écrit AVANT, puis mesuré** — 14 jours (les 10 du lot avec un
      signal des quatre le matin + 01/04/07/08/09), « avant » fabriqués avec le
      code d'avant la passe et conservés `_avant_lecture`. Comparateur :
      **0 inattendu / 159 lignes**. (a) 22 trous du matin → réponses (les 22
      prévus) ; (b) 1 veto gamma short retiré (prévu) **+ 12 `TROU_L5_VETO_GAMMA`
      sur les autres shorts** (non prévu, consigné : « non mesuré » par short) ;
      7 `PREMIERE_BARRE` inchangées ; ombres identiques ; jours 1-2 : 0/0. Le
      jour 3 (10/09) se rejoue à 23h01 avec le code neuf.
- [x] **5. Review interne** (code-reviewer : GO-AVEC-RÉSERVES, R1/R3-R8
      exécutées — mesure 13 vs attendu 1 consignée, battements de nuit
      documentés + testés, test « L5_VETO_GAMMA reste observée », lint,
      chiffres), 14 contrôles, publié — commit `bd5dbd2`, **miroir `e333fe5`**.
      **R2 reste à Jackson : redémarrer le coureur live (ancien `lecture.py`
      en mémoire) à 15h15 Paris, `ts` dans DECISIONS + règle 36.**

## Pas dans cette passe
`gamma_block_short` dans l'agrégation (CORE) · le lieu dans `PASSE` (passe
suivante) · pas 2b.

## Après, dans l'ordre de Fable
- [x] **le lieu dans `PASSE`** — `V3/lieux.py` + `test_lieux` 16/16, chaîne
      3 lignes (journal seulement), règle 37, DECISIONS ×3 ; review
      GO-AVEC-RÉSERVES exécutées (R1 : signe de `dist_cur_val` mesuré contre
      `cur_val_lvl`, ma table avait tort — VALIDATION_MISS ; R2 `bande_ticks` ;
      R3 `close` ; R4 tests) ; NEXT_CYCLE §5 septies (le long de `h3` gelé
      lit la VAL avec le signe inverse — rien ne bouge au tag) ; commit
      `1b6d4b7`, **miroir `8fe25d3`**.
- [ ] lecture marges/2 par Fable (schéma validé Q5, version b)
- [ ] **gel demain matin + tag** (après relecture Fable — pas avant)
- [x] **brique 4** — L6 dénominateurs : `volumetrie_cash` (ferme), `vix_cash_zero`
      (ferme > 5 min, mesuré 101-210), `derive_feature` (INFO, définition v1 à
      valider par Fable), Globex ne ferme plus ; `test_l6_denominateurs` 12/12 ;
      réel 09/09 : NQ F15 ×3,71 = la feature, ES ×2,50 = un régime, 0 ALERTE.
- [x] **brique 5** — `pourquoi_plus.py` (lieux sans réaction des quatre + trader
      vs machine, `--ecrire`), `recit.py` (AU-DELÀ / D / R, H-PIÈGE si regagné),
      journal manuel 7 champs.
- [x] **brique 3** — `carte_matin.py` (niveau + bande en PRIX sur `atr_veille`,
      les dix de H8p, les repères `_lvl`), tirage en aveugle SEED 20260910 /
      blocs d'une semaine / 8 tirés d'un coup, carte toujours générée et
      stockée, `carte_visible` dans le journal, `--forcer` n'écrit pas ;
      `test_carte_matin` 14/14 (nuit seule, tardive, forcée) ;
      `execution/carte_matin.bat`. **À Jackson : la tâche planifiée 15h25
      Paris, jours de semaine seulement** (`schtasks /create /tn "V3 carte
      matin" /tr "<racine du dépôt>\V3\execution\carte_matin.bat" /sc weekly
      /d MON,TUE,WED,THU,FRI /st 15:25` — même piège DST que le rythme du
      soir : à revoir le 25/10 et le 1er/11 ; la garde TARDIVE protège la
      donnée, pas l'horloge).
- [x] review 3-4-5 (GO-AVEC-RÉSERVES, 12 réserves exécutées — dont la carte
      VIDE à 9h25 et `derive_feature` contre sa propre médiane) → commit
      `77e186a` → **miroir `7c9e47d`**.

## Ce qui reste, et à qui (10/09 midi)
- **Jackson, 15h15 Paris** : `taskkill /PID 26360 /F` (le coureur live a
  l'ancien `lecture.py` ET l'ancien YAML en mémoire ; le garde le relance en
  < 3 min) — l'heure va dans DECISIONS + règle 36.
- **Jackson** : la tâche planifiée « V3 carte matin » (commande ci-dessus).
- **Jackson** : la ligne de 11h15 du 09/09 dans `journal_manuel/20260909.md`.
- **Ce soir 22h** : heure de bascule U26→Z26 dans le fichier (si elle a lieu)
  et `max(atr_barre)` du 10/09 ; `volumetrie_cash` ES/NQ 10/09 avant le gel.
- **11/09 matin** : si le fichier ouvre en Z26 → `L0_CONTRAT_INACTIF` remise
  `appliquee` + une ligne DECISIONS ; relecture Fable (marges/2, lieu,
  §5 septies, `derive_feature` v1) ; **le gel + son tag**.

## SCENARIOS — prérequis avant la grammaire (10/09 après-midi, ordre de Fable)
- [x] règle 38 (H3 deux jambes) + mesure sans devenir (15 longs / 30 shorts sur 73) ->
      commit `9c2cd96` -> **miroir `d470feb`** (spec + mission scénarios dedans).
- [x] prérequis 1 `recalc.open_type_r` + `test_open_type` 15/15 + distribution
      (`scenarios/rapports/open_type_57j.md`) : DRIVE quasi absent à 30 min (ES 1 / NQ 0),
      TEST_DRIVE 43 / 57 %, REJET 21 / 20 %, ENCHERE 34 / 23 % -> NEXT_CYCLE §5 nonies.
- [x] prérequis 2 `recalc.range_r` (deux fiches F23 face à face, tenue CAUSALE,
      compression sur l'extrême) + `test_range` 27/27 dont direct = rétrospectif ;
      distribution IB (`rapports/range_ib_57j.md`).
- [x] prérequis 3 + 3 bis `mesure_reactions` (dépassement sur tests tenus, sauts par
      heure) -> `rapports/reactions_niveaux_57j.md` ; `scenarios/seuils.yaml` (null +
      décisions Fable : dedans P10 / dehors p80 tenus, POSE, un range v0, 0DTE dormant).
- [x] dix décisions Fable appliquées (MISSION.md), règle 39, NEXT_CYCLE §5 octies/nonies,
      `test_cote_hvl` 5/5, CONVENTIONS §11, DECISIONS (attendu avant / mesuré après /
      attendus du rejeu signés relectrice).
- [x] commit B `66bfc6a` -> **miroir `e26236a`** (vérifié) -> hash à Fable avec les distributions
      (relecture AVANT la grammaire).
- [ ] **11/09 9h00 Paris** : hash de la tête à Fable ; relecture ; **tag avant l'ouverture**
      (les deux recalculs seront dedans — Fable, réponse 7).
- [x] relecture Fable à `e26236a` (10/09 15h) : les quatre écarts tranchés, les valeurs fixées
      (`seuils.yaml` v2026-09-10b : dehors par nature, w_min/w_max p10/p90, `pression`, trois types
      d'ouverture, S_DANS_POSE + S_DANS_HEADFAKE, attendus 60 / 55 / 15) -> appliqué, tests verts.
- [x] `grammaire.py` (huit canoniques v0 + S_DANS_ROTATION + S_AUTRE(raison)), `zones.py` (bande
      asymétrique, mémoire F23 causale, ZONE_DEPLACEE, 0DTE dormant), `scenarios.py` (rejeu et direct
      par la MÊME fonction, journal `.tmp` + `os.replace`), `sorties.py` (B-SCEN en parité B-NIV),
      `erreurs.py` (sept erreurs nommées + carnet) — chacun < 300 l. ; `test_grammaire` 24/24
      (validé / invalidé / bascule, miroir, bande, rôles, S_AUTRE, mots conclusifs, ZONE_DEPLACEE,
      DIRECT = RÉTROSPECTIF), `test_scenarios_soir` 18/18.
- [x] mode vivant : `scenarios.py --direct` (barres complètes), appelé par `direct.py` ; rythme du
      soir étape 5b/5 = `erreurs.py` (rejeu + auto-évaluation + FUITE si le direct diffère).
- [x] rejeu 57 j : `rapports/scenarios_57j.md` — couverture en cours 93 % (trop large : mécanique TEND),
      validée 58 / 53 % (dans l'attendu), tenue 60 / 75 % sur N = 5 / 4, tirage battu de +68 / +67 ->
      ligne DECISIONS 16h15.
- [x] commit D `3f288e8` -> **miroir `c6c12dd`** (vérifié) -> hash à Fable (relecture de la grammaire).
- [ ] après relecture Fable : `scenario_en_cours` sur l'entonnoir / fantômes / marges (touche `chaine.py`,
      jamais avant le tag) ; la vitrine texte ; sa réponse « laquelle est la couverture ».
- [ ] ce soir 23h01 : le rythme du soir passe par 5b/5 (`erreurs.py`) — première vraie journée en direct
      (10/09) : `FUITE` = incident si le journal direct diffère du rejeu.
- [x] phase A de la liste fusionnée CODÉE le 10/09 (ordre de Jackson) : SPEC_VITRINE, boucle + garde,
      vitrine + html, alertes, noter, fenêtre, test A5, scenarios_visibles — rien lancé en tâche avant le tag.
- [x] phase A RELUE par Fable à `2670789` : elle passe (DECISIONS 18h00) ; deux remarques, pas des corrections.
- [x] B1 `setups_armes` (lu dans `marges_quatre.exposer`, H3/H2p hors zones, C2 absent) et B5 `carnet.py`
      codés le 10/09 soir (GO Jackson) ; le module lit le MÊME frame que la chaîne (`scenarios.charger` +
      `injecter_recalculs`) ; tests 30/30, 25/25, 24/24.
- [ ] **11/09 9h00, AVANT la tête** : lire `LOGS/scenarios/erreurs_20260910.jsonl` — la première comparaison
      direct / rejeu d'une vraie journée (5b/5 de 23h01) ; `FUITE` = incident à consigner avant le tag.
- [x] COPILOTE LANCÉ le 10/09 à 22h50 sur « lance tout » + GO de Jackson : `scenarios.bat` (écrivain, dort hors
      cash), tâche « V3 garde scenarios » toutes les 5 min (via PowerShell), `vitrine.py` (8765), `fenetre.py`
      avec Jackson devant. Rythme du soir du 10/09 fait à la main : L6 reset_vwap faux positif corrigé (sinon
      live du 11/09 fermé), verdict rejoué sans ALERTE ; 5b/5 sans FUITE.
- [ ] **11/09 matin** : vérifier que la fenêtre s'est ouverte (WebView2) ; `pip` pyttsx3 plus tard. Ancien plan (pour mémoire) : (1) l'écrivain en boucle
      (`scenarios.py --direct` à chaque clôture de 15 min, un processus) ; (2) la vitrine HTML servie
      sur localhost ; (3) la fenêtre `pywebview` always-on-top sur le même HTML ; (4) `winsound` sur les
      cinq événements, muet, silence des cinq premières minutes ; (5) `scenarios_visibles : oui/non`
      dans le journal manuel. Puis la voix, puis le study Sierra. Rien sur le VPS avant le jour 20 de w1.
