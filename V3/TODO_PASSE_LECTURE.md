# TODO — 10/09 : la passe lecture (R3 + A1 + B3), avant le gel

*Brief Fable 10/09. Zéro touche à ce que la chaîne décide ; trois portes
cessent de mentir ou de se taire. Les cases se cochent au fur et à mesure,
la dernière porte le hash du miroir.*

## Ce matin (Jackson + Claude)
- [x] L6 : F15 en INFO (`motif=derive_feature`) — `etat_l6(20260910) = False`,
      le live du 10/09 s'ouvre (commit `41412e7`)
- [ ] Rollover à l'ouverture : la commande de `ROLLOVER_10_09.md`, ligne A ou B
      dans DECISIONS, l'heure ; le soir : heure de bascule + `max(atr_barre)`
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
- [ ] **5. Review interne** (code-reviewer), 14 contrôles, publier, **hash
      après `-> master`** : `……`

## Pas dans cette passe
`gamma_block_short` dans l'agrégation (CORE) · le lieu dans `PASSE` (passe
suivante) · pas 2b.

## Après, dans l'ordre de Fable
le lieu dans `PASSE` → lecture marges/2 → **gel demain matin + tag** →
briques 4-5 dans la semaine → carte du matin (protocole pré-enregistré).
