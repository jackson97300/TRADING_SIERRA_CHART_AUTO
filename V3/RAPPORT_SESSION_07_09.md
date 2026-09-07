# RAPPORT DE SESSION — lundi 07/09/2026 (Labor Day)

*Écrit pour le suivi par les autres agents (Fable en tête) : ce qui a été
fait, avec quelle preuve, et ce qui attend qui. Une session = un fichier daté ;
le détail fin est dans les messages de commit.*

**Précision de calendrier** : les documents de la veille datent « 08/09 » ;
l'horloge dit lundi 07/09, Labor Day, séance écourtée. La campagne d'ombre
démarre donc DEMAIN mardi 08/09 — jour 1 instrumenté des deux côtés (coureur
live + rejeu 21:01).

---

## Fait aujourd'hui, dans l'ordre

### 1. Constat du §5 : trois NON, avec preuves
Aucun run `strict=True` (pas de journal) ; fichier du jour copié à 11:36 UTC,
avant le cash ; aucun entonnoir de nuit avec `TROU_VIX`. → La tâche était le
coureur live, conformément au prompt.

### 2. Le coureur LIVE — commit `25857a9`
`execution/coureur_live.py` + `sync_vps.py` + `etat_live.py`. Boucle sur le
fichier vivant (scp `--sync`, hôte/chemin dans `comptes.local.yaml`, jamais
dans le code) ; battement de chaque barre 15 min complète — nuit comprise —
dans `chaine.appliquer(strict=True, live={...})` ; signaux L3 = les fonctions
mêmes du rejeu ; journal append-only `LOGS/entonnoir/live_<jour>.jsonl`,
SÉPARÉ de l'entonnoir officiel. Attendu pré-enregistré AVANT le premier run,
puis testé EN RÉEL pendant la séance : `L0_FERIE_CME` bloque, trous
DTC/colonnes_mortes bloquent en strict, `age_s` ~90 s, zéro re-journalisation
à la relance. Review Tier 1 : GO après 3 réserves (découpage 300 lignes,
timeout scp, diagnostics du rejeu portés). Le coureur TOURNE depuis ~16:30
UTC ; à 22:00 UTC il bascule seul sur la journée 08/09 et doit montrer
`SESSION_BLOQUEE` + `TROU_L0_VIX_REGIME` la nuit (question 3 du constat).

### 3. Prérequis L4 « proxys » — commit `3229c0e`, review GO
`lecture.SOURCES_DECLAREES` : toute colonne gouvernée par une `_source`
contenant « proxy » se lit None (`_mq_gamma_source` → 6 colonnes gamma ;
`_aggressor_source` → `aggressor_imbalance`). Les champs `_source` survivent
désormais à l'agrégation — sans quoi le refus était aveugle là où les portes
lisent. `test_proxys.py` (5 contrôles, dont le chemin réel agrégé) devient le
7e contrôle de `publier.sh`.

**Conséquence assumée, PAS maquillée** : `L5_VETO_GAMMA` ne peut plus
répondre (entrée 100 % proxy, scraper mort le 27/05). En appliquée + strict,
son trou fermait tout le live. La porte passe **observée** ; rejeu 20260904 :
signaux identiques, seul ajout `TROU_L5_VETO_GAMMA`.
→ **ARBITRAGE JACKSON avant le gel du 12/09** (A_FAIRE point 16) : exemption
explicite du proxy pour ce veto (le -0,48 ATR a été mesuré SUR le proxy), ou
observation pendant la campagne. Revert = un commit.

### 4. Prérequis L4 « B4 » — commit `9c65fde`
Une colonne SMT, toujours la même : `colonne_smt: im_smt_divergence`,
`instrument_smt: ES` (seuils L1) — les deux instruments divergent (ES −1,
NQ 0 au même ts). Et la mesure 57 j ne fabrique plus d'accord : elle
comparait l'instrument à lui-même (`d_vwap_w_autre = dv`) avec
`smt_div = False` en dur — deux trous honnêtes désormais, B4 rend None.

### 5. Corrections du matin (avant le coureur)
- `campagne.py` courait {h3, h6, h7, h8} du cycle 1 au lieu de `LES_QUATRE`
  pré-enregistrées, sans colonnes `_r` (H2p/H8p structurellement muettes) et
  en comptant par barre vraie au lieu du franchissement — corrigé, review GO,
  commit `eb6b8bd`, incident `VALIDATION_MISS` documenté au dépôt principal.
- Les 10 niveaux de H8p survivent à l'agrégation (6 manquaient).
- Journal vide = preuve d'un jour couru muet ; absent = incident.
  `pourquoi.py` distingue les deux.

## Ce qui attend qui

| quoi | qui | quand |
|---|---|---|
| Arbitrage veto gamma (A_FAIRE pt 16) | Jackson | avant le gel du 12/09 |
| Clic MANUEL + 21:01 (`campagne.py` puis `pourquoi.py`) | Jackson | ce soir |
| Webhooks Discord (3e jour) | Jackson | dix minutes |
| Reproduction `ctx_*` (mismatch = 0 sur 2 jours) | prochaine session | avant L4 J2 |
| `rvol_r` / `cvd_sess_r` dans l'agrégation | prochaine session | avant L4 J2 |
| L4 J2 (5 vetos en série, glissement, k) | prochaine session | ~2 jours |
| Racine + commit pour relecture Fable | à l'issue de L4 J2 | — |

## Les commits du jour (dépôt privé → miroir)

`80f1f4b` bloqueurs du tag + prompt corrigé → tag `campagne-ombre-1` posé
· `eb6b8bd` coureur du rejeu conforme au pré-enregistrement · `25857a9`
coureur LIVE · `3229c0e` refus des proxys + veto gamma observée · `9c65fde`
B4 une colonne SMT · `f1c150d` (miroir) prompt à jour. Sept contrôles verts
à chaque publication.
