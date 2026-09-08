# Refonte dashboard — Proposition A : LE CONTRAT D'ABORD (strangler)

*Proposition d'agent architecte (08/09/2026). NON VALIDÉE — à arbitrer par
Jackson et Fable avant toute ligne de code. Deux propositions concurrentes :
[B moteur unique](2026-09-08-refonte-dashboard-B-moteur.md),
[C défaillances d'abord](2026-09-08-refonte-dashboard-C-defaillances.md).
Verdict croisé du juge : à venir dans 2026-09-08-refonte-dashboard-VERDICT.md.*

**Angle** : on ne corrige pas 14 cerveaux, on les rend inoffensifs. On définit
d'abord le **contrat de verdict** (schéma JSON versionné, émis par le serveur),
on fait migrer **tous les consommateurs** (écran, paper traders, tiers) vers ce
contrat, puis on remplace l'intérieur cerveau par cerveau, derrière une
interface qui ne bouge plus. Aucune phase ne change deux choses à la fois ;
chaque phase se revert par un `scp` + `nssm restart` (30 s) ; rien pendant la
séance US.

**Fait d'ancrage** (audit 08/09, 13:54 UTC) : le backend loggait
`VENTE PRUDENTE -> ATTENDRE` (porte de lieu) pendant que l'écran affichait
`VENTE`. La cause architecturale est visible dans `dashboard.js:2134` :
`var cgAction = cgBackend && cgBackend.action ? cgBackend.action : action;` —
un **fallback silencieux sur le calcul local** dès que `data.conseil_global[sym]`
manque ou est figé. Tant qu'un chemin de recalcul client existe, il finira par
s'exécuter. Le contrat existe pour qu'il n'y ait **rien à recalculer**.

---

## 1. Le contrat de verdict versionné

### 1.1 Emplacement

Pas de nouvel endpoint (continuité de service, un seul poll, un seul cache) :
un bloc `verdict` ajouté à la réponse `/api/dashboard`, à côté de
`conseil_global` qu'il double temporairement puis remplace (Phase 6). Produit
par un module unique nouveau : `DASHBOARD/api/verdict.py`.

### 1.2 Schéma exact (v1)

```json
"verdict": {
  "schema_version": 1,
  "es":  { /* VerdictInstrument */ },
  "nq":  { /* VerdictInstrument */ },
  "mgc": null
}
```

`VerdictInstrument` :

```json
{
  "instrument": "ES",
  "ts_bar": 1788882840000,
  "ts_calcul": "2026-09-08T13:54:05Z",

  "etat": "OK",
  "trous": [],

  "direction": "SHORT",
  "mode": "RANGE",
  "score": -0.42,
  "confiance": 0.33,
  "vol_regime": "NORMAL",

  "action": "ATTENDRE",
  "action_affichage": "ATTENDRE",
  "action_executable": "ATTENDRE",

  "portes": [
    {"nom": "ZONE", "verdict": "BLOQUE",
     "motif": "plus proche VAH 6482.25 a 17t (seuil 6t)",
     "details": {"niveau": "VAH", "dist_ticks": 17, "seuil_ticks": 6}}
  ],

  "zone": {"en_zone": false, "niveau": "VAH", "prix": 6482.25,
           "dist_ticks": 17, "seuil_ticks": 6},
  "fraicheur": {"etat": "PERSISTENT", "age_bars": 3, "signal_id": "ES_VP_1788882600"},
  "mtf": {"bulls": 1, "bears": 2, "verdict": "NEUTRE"},

  "motifs": ["Bias: BEARISH", "Delta: vendeurs", "Range: 84%", "..."],
  "log_ref": "VERDICT:ES:1788882840000"
}
```

### 1.3 Sémantique, champ par champ

| Champ | Sémantique | Source (unique) |
|---|---|---|
| `etat` | `OK` / `DEGRADE` / `PANNE`. **Fail-closed** : toute donnée d'entrée manquante ou périmée (price=0, barre > 120 s, `vix_level<=0`, niveaux tous absents) dégrade l'état. `PANNE` ⇒ toutes les actions valent `INDISPONIBLE` et le client affiche une panne, **jamais** un verdict. VIX 0 = trou listé dans `trous`, jamais « calme ». | `verdict.py` |
| `trous` | Liste des champs d'entrée manquants ayant causé la dégradation. Affichée telle quelle. | `verdict.py` |
| `direction` | `LONG` / `SHORT` / `NEUTRE`. **Une seule origine autorisée : `CORE/regime_engine.compute_regime().favor`.** Aucune porte, aucune vue, aucun client n'a le droit de la produire ni de l'inverser. | `compute_regime` |
| `mode`, `score`, `confiance`, `vol_regime` | Copies directes de `RegimeAnalysis` (mode, bias_score, confidence, vol_regime). | `compute_regime` |
| `action` | Enum fermée : `ACHAT`, `ACHAT PRUDENT`, `VENTE`, `VENTE PRUDENTE`, `ATTENDRE`, `CONFLIT`, `INDISPONIBLE` (littéraux identiques à l'existant — zéro renommage, les bots comparent ces chaînes). Dérivée de `direction` + **portes soustractives**. Une porte ne peut que dégrader (`→ ATTENDRE` ou `→ CONFLIT`), jamais créer ni inverser une direction. | `verdict.py` |
| `action_affichage` / `action_executable` | `action` après expiration fraîcheur 2 barres (UI) / 4 barres (bots) — reprend la state machine existante `_evaluate_signal_freshness` (déjà par barre, déjà testée `test_signal_freshness.py`). | `verdict.py` |
| `portes` | Liste **ordonnée** des portes évaluées avec verdict `PASSE`/`BLOQUE` : `DONNEES`, `SESSION`, `VOL`, `ZONE`, `GAMMA`, `MTF_VETO`. La première `BLOQUE` détermine l'action. Structuré, pas des strings à parser — rend enfin visibles à l'écran les motifs HORS ZONE / VETO MTF. | `verdict.py` (Phase 1 : recopie depuis `build_conseil_global`) |
| `zone` | Sortie de `zone_info` (stabilizers.py:210), inchangée. | `zone_info` |
| `fraicheur` | `NEW` / `PERSISTENT` / `EXPIRED` / `IDLE` + `age_bars` + `signal_id`. Cliquet **par barre** (`ts_bar` change = 1 tick d'horloge), jamais par poll — corrige le « 3 votes = 15 s » de `_stabilize_favor`. | `verdict.py` |
| `mtf` | Contexte affichable (bulls/bears/verdict). Le MTF n'est **jamais additif** dans le contrat : il n'existe que comme vue et comme porte `MTF_VETO` (4/4 opposé → `CONFLIT`). | `read_mtf_bias` |
| `motifs` | Les checks lisibles (équivalent `checks` actuel). Purement explicatif. | `verdict.py` |
| `log_ref` | Clé de corrélation avec la ligne JSONL émise. Tout changement d'`action`, de `direction` ou d'état de porte émet un code catalogué (`CORE/log_catalog.py`), avec vérification d'émission réelle J+1 (`test_log_emission.py` couvre les nouveaux codes). | `verdict.py` |

Nouveaux codes catalogue (définis AVANT tout commit, format imposé) :
`VERDICT_EMIS` (INFO, decisions), `VERDICT_INDISPONIBLE_DONNEES` (MAJEUR,
decisions), `VERDICT_VERSION_INCONNUE` (MAJEUR, decisions),
`AFFICHAGE_DIVERGENCE` (MAJEUR, events). Les codes `CONSEIL_ZONE_GATE_BLOCK`
et `CONSEIL_MTF_VETO_CONFLIT` existants sont conservés tels quels.

### 1.4 Versionnement et comportement en version inconnue

- `schema_version` : entier, au niveau du bloc. **Ajout de champ = pas
  d'incrément** (tolérance additive). Retrait ou changement de sémantique =
  incrément.
- **Noyau immuable garanti à travers toutes les versions futures** :
  `{schema_version, etat, action_affichage}` — règle écrite dans la docstring
  de `verdict.py`, toute v future doit les conserver à l'identique.
- **Client d'affichage** recevant une version > connue : rend le noyau
  immuable + bandeau « verdict vN — client vM, détails masqués ». Si le noyau
  est absent ou l'enum inconnue : carte PANNE. **En aucun cas un recalcul
  local** — le code de recalcul n'existera plus (Phase 4).
- **Paper traders** recevant une version inconnue : fail-closed strict →
  `ATTENDRE` + émission `VERDICT_VERSION_INCONNUE`.
- **Verdict absent de la réponse** (serveur ancien pendant un rollback) :
  écran = PANNE ; bots = fallback `conseil_global` jusqu'à Phase 6, puis
  `ATTENDRE`.

### 1.5 Tiers : filtrage AU contrat

`_filter_response_by_tier` filtre le bloc verdict lui-même — jamais de recalcul
par tier :
- **FREE** : `{schema_version, etat, action_affichage}` uniquement. (Corrige
  l'audit point 7 : FREE voit désormais une action *protégée par les portes*,
  identique à celle du PRO, juste sans les détails.)
- **STARTER** : + `direction, mode, score, confiance, zone, fraicheur`. (La
  fuite `order_flow_advanced` au tier STARTER se règle dans la même passe.)
- **PRO/OWNER** : tout.

---

## 2. Sort de chacun des 14 cerveaux

### Côté serveur (9)

| # | Cerveau (fichier:ligne) | Sort | Phase |
|---|---|---|---|
| 1 | `compute_regime` — CORE/regime_engine.py:229 | **GARDÉ — l'unique cerveau de direction.** Intouché par ce plan (audité 04/09, calibré par instrument via `regime_calibration`). | — |
| 2 | `_compute_bias_proxy` — CORE/regime_engine.py:118 | **GARDÉ** comme organe interne privé de `compute_regime` (jamais appelé ailleurs). Devient à terme le seul calcul de biais du dashboard. Les corrections mode-aware de l'audit point 1 (double comptage delta/cvd, seuil unique) se font *ici et seulement ici*, hors périmètre de ce plan de migration. | — |
| 3 | `compute_bias` — CORE/bias_calculator.py:265 | **DÉGRADÉ puis retiré du chemin dashboard.** La carte BIAS devient une vue de `verdict.score` + motifs du proxy. Le module reste dans CORE pour ses autres consommateurs, mais plus aucune influence sur une direction affichée ou tradée. | 4a puis 6 |
| 4 | `read_mtf_bias` — DASHBOARD/api/readers.py:998 | **DÉGRADÉ en vue + entrée de porte.** La grille MTF reste affichée ; le score MTF n'entre dans le verdict que via la porte `MTF_VETO` (soustractive). Le défaut structurel (composante V identique sur les 4 TF, normalisations non calibrées) le disqualifie comme signal additif tant qu'il n'est pas recalibré. | 5 |
| 5 | `_enrich_regime_with_mtf` — DASHBOARD/api/stabilizers.py:67 | **SUPPRIMÉ.** Le boost ±0.25 disparaît ; plus de mutation in-place du régime. Diff d'actions mesuré en rejeu et arbitré par Jackson AVANT déploiement. | 5 |
| 6 | `build_advisory` — DASHBOARD/api/builders.py:865 | **DÉGRADÉ en vue pure.** Les conseils texte sont générés depuis le verdict ; la mutation `regime["favor"]` (l.953, l.962 — un « cerveau » caché dans une vue) est supprimée. `qui_a_la_main` = vue de `verdict.score`. | 4a |
| 7 | `_stabilize_favor` — DASHBOARD/api/stabilizers.py:305 | **REMPLACÉ** par la fraîcheur du contrat : latch par barre avec expiration, un seul état par instrument, dans `verdict.py`. Supprime l'asymétrie ES/NQ (deux dicts régime distincts, app.py l.1326-1332) par construction. La carte FAVORISER = `verdict.direction` + `verdict.fraicheur`. | 4a |
| 8 | `build_conseil_global` — DASHBOARD/api/builders.py:1149 | **Étranglé en dernier** (le mieux protégé aujourd'hui : porte de lieu + véto MTF déployés 08/09, vérifiés en prod). Phase 1 : encapsulé tel quel — il produit `verdict.action`, seul ajout : un champ structuré `portes` (additif). Phase 6 : son comptage interne à 6 signaux est remplacé par `direction` `compute_regime` + confiance + portes. Le gamma gate, la porte de lieu, le véto MTF et la freshness **survivent intégralement** comme portes du verdict. | 1 puis 6 |
| 9 | `build_trade_suggestion` — DASHBOARD/api/builders.py:1436 | **DÉGRADÉ en checklist sans verdict propre.** `direction` = `verdict.direction`, `has_signal` exige `verdict.action_executable` directionnel (donc hérite session + zone + gamma + données). SL/TP : suspendus (`INDISPONIBLE`) tant que l'unité de la colonne `atr` n'est pas certifiée — un assert d'unité conditionne leur retour. | 4a |

Site d'assemblage associé : `build_regime_context` (builders.py:173) n'est pas
un 10e cerveau mais la colle qui en mélange trois (compute_bias +
compute_regime + son propre override cohérence l.259-266, dupliqué de celui de
`compute_regime` l.454-460). Phase 4a : il devient un lecteur de features pour
les cartes contexte (VIX, VWAP slopes, momentum) ; le double override disparaît.

### Côté navigateur (5) — le code à étrangler

| # | Site (dashboard.js) | Sort | Phase |
|---|---|---|---|
| 10 | **Réplique du conseil** — `renderGlobalAdvice` l.2009-2177 (comptage `bullPoints/bearPoints` l.2016-2106, fallback silencieux l.2134) | Phase 2 : le fallback local devient une carte PANNE (fail-closed) — c'est le correctif du 13:54. Phase 4b : **suppression totale du comptage** ; la checklist affichée = `verdict.motifs` + `verdict.portes`. | 2 puis 4b |
| 11 | **`reconcileFavorWithMtf`** — l.1825-1854 | **SUPPRIMÉ en premier.** Il INVERSE le sens côté client (`favor SHORT + mtfBulls 4 → affiche LONG`), survivance de l'override Python supprimé le 08/06. Aucun remplacement. | 2 |
| 12 | **Zones de confluence locales** — `renderConfluence` l.1901-2007 | **Migré côté Python** : vue `confluence` par instrument construite sur `_niveaux_cles` (stabilizers.py:175 — le calcul JS en est précisément une deuxième liste, avec ses propres seuils 8/24 ticks). Le JS ne fait plus que rendre. | 4a + 4b |
| 13 | **Feed divergence 70/30** — `updateSignalFeed` l.1447-1520 (l.1495 : seuils 70/30 vs 80/20 serveur, labels locaux) | **DÉGRADÉ en rendu d'événements serveur.** Les transitions viennent de `verdict.fraicheur == NEW` et des `level_breaks` ; seuils locaux 70/30 et labels ACHAT/VENTE au navigateur supprimés, dédup simplifiée. | 4b |
| 14 | **Override conseils / alertes locales** — carte alerts l.7500+ et override `favor-value` | **DÉGRADÉ.** Les seuils purement informatifs (VIX>30, RVOL>3) restent — ce sont des lectures, pas des décisions. Tout libellé *directionnel* provient du verdict. VIX absent/0 s'affiche « DONNÉES EN PANNE (VIX) », rouge, jamais « calme ». | 4b |

---

## 3. Plan de migration par phases

Règles transverses : déploiement hors séance US uniquement (avant 13:00 UTC ou
après 20:30 UTC, week-end de préférence) ; une phase = un déploiement = un
revert possible ; le critère GO d'une phase est mesuré sur des séances
*réelles* avant d'ouvrir la suivante ; `V3/` n'est jamais touchée.

### Phase 0 — Le test d'or : parité écran == API (préalable à tout)

**Contenu** : (a) un beacon JS minimal — 1 POST/minute vers
`/api/telemetrie_affichage` contenant `{action affichée, ts, version JS}` ;
(b) côté serveur, comparaison avec le dernier verdict émis, émission
`AFFICHAGE_DIVERGENCE` (MAJEUR → Discord) si écart ; (c) suppression de la
ligne `dashboard.min.js` dans `deploy.sh` (fichier d'avril encore copié —
`index.html` charge `dashboard.js?v=171`) et suppression du fichier sur le VPS.
**Justification** : la divergence écran/API est LE mode de défaillance prouvé
du 08/09, resté invisible 3 mois parce que les logs étaient morts. Ce test
tourne en continu en production, il aurait sonné à 13:54.
**Vérification** : provoquer une divergence en local (mock) → l'alerte part ;
grep J+1 confirme l'émission réelle.
**GO Phase 1** : beacon actif 2 séances, zéro faux positif, la divergence du
13:54 reproduite en local est détectée.

### Phase 1 — Le contrat émis (serveur seulement, zéro changement de logique)

**Contenu** : `DASHBOARD/api/verdict.py` assemble `VerdictInstrument` v1 par
pur re-packaging de l'existant : `action` = `build_conseil_global` inchangé
(+ champ structuré `portes`, additif), `direction/mode/score/confiance` = le
régime de la réponse (`response[sym]["regime"]`, le même dict que voit le
conseil — pas `regime_es`, pour ne pas hériter de l'asymétrie), `zone` =
`zone_info`, `fraicheur` = state machine existante. Filtrage tier du bloc
verdict. Codes log ajoutés au catalogue. `conseil_global` reste émis à
l'identique — duplication temporaire assumée.
**Vérification** : `test_verdict_contract.py` — parité stricte
`verdict.action == conseil_global[sym].action` en rejeu sur les 819 barres NQ
du 08/09 (outillage : `CORE/research/audit_conseil_global.py`) + cas
fail-closed + `test_log_emission.py` étendu.
**GO Phase 2** : parité 100 % en rejeu ES+NQ, `bench_dashboard.py` vert, une
séance réelle avec `VERDICT_EMIS` observés dans les JSONL.

### Phase 2 — L'écran consomme le contrat, les inverseurs meurent

**Contenu** : `renderGlobalAdvice` lit `verdict` uniquement, fallback local
remplacé par la carte PANNE ; `reconcileFavorWithMtf` supprimé ;
`verdict.portes` et `motifs` rendus (HORS ZONE / VETO MTF enfin visibles) ;
comportement version-inconnue implémenté ; bump `?v=`.
**Vérification** : le test d'or — beacon sans `AFFICHAGE_DIVERGENCE` sur séance
complète ; test manuel hors séance : couper le backend → l'écran doit montrer
PANNE, pas un dernier verdict figé ni un recalcul.
**GO Phase 3** : 2 séances de beacon propres.

### Phase 3 — Les paper traders consomment le contrat

**Contenu** : `mia_paper_trader.py` et `mia2_brain_v6_databento.py` lisent
`verdict[sym].action_executable` (aujourd'hui : `conseil_global[sym].executable_action`,
~2 lignes chacun), fallback `conseil_global` conservé + kill-switch env
`MIA_BOT_USE_VERDICT`. Version inconnue → `ATTENDRE` + log.
**Vérification** : `bench_dashboard.py` étendu ; une séance en double lecture
loggée (les deux valeurs comparées à chaque poll, code `VERDICT_BOT_MATCH`
temporaire).
**GO Phase 4** : 100 % de correspondance sur une séance réelle, zéro trade dont
la décision aurait différé.

### Phase 4 — Étrangler les vues (deux déploiements distincts)

**4a serveur** : `build_advisory` → vue du verdict (mutation favor supprimée) ;
`_stabilize_favor` → remplacé par le latch du contrat ; `build_trade_suggestion`
→ checklist sans verdict propre, SL/TP suspendus jusqu'à certification `atr` ;
`build_regime_context` → lecteur de features ; vue `confluence` serveur sur
`_niveaux_cles`.
**4b JS** : suppression du comptage local et de la checklist parallèle ;
clusters JS supprimés ; feed sans labels locaux ni seuils 70/30 ; alertes sans
direction locale ; VIX 0 = panne affichée.
**Vérification** : rejeu comparatif carte par carte (diff FAVORISER avant/après
documenté et arbitré par Jackson avant déploiement) ; beacon étendu à la carte
FAVORISER ; tests unitaires des vues.
**GO Phase 5** : 2 séances de beacon propres sur les deux cartes, diff
FAVORISER validé.

### Phase 5 — Étrangler le MTF additif

**Contenu** : suppression de `_enrich_regime_with_mtf` (le boost ±0.25 sur le
score disparaît ; le MTF ne subsiste que comme grille affichée et porte
`MTF_VETO`).
**Vérification** : rejeu 10 jours ES+NQ, distribution des actions avant/après
chiffrée et présentée à Jackson **avant** déploiement (changement de
comportement assumé, pas un refactor).
**GO Phase 6** : diff validé par Jackson, une séance réelle sans surprise.

### Phase 6 — Étrangler le cœur, nettoyer

**Contenu** : l'intérieur de `build_conseil_global` (comptage 6 signaux)
remplacé dans `verdict.py` par `direction` + `confiance` + portes ;
`conseil_global` retiré de la réponse (les bots lisent le verdict depuis la
Phase 3) ; `compute_bias` retiré du chemin dashboard ; suppression des fichiers
morts (`builders.py.backup_20260428_premerge`, `.bak_20260422`,
`.bak_bigorders`, `v4_reader.py.bak_bigorders`, `dashboard.min.js`).
**Vérification** : rejeu comparatif complet nouveau vs ancien sur 10 jours,
chaque écart classé (attendu/défaut) et arbitré avant déploiement ; puis 2
séances beacon + monitoring paper + grep J+1 des émissions.
**GO final** : fenêtre de 5 séances sans entrée INCIDENT_LOG liée au dashboard.

---

## 4. Effort, risques, rollback par phase

| Phase | Effort | Risque principal | Mitigation | Rollback |
|---|---|---|---|---|
| 0 | 4 h | Faux positifs du beacon (cache 5 s, latence poll) | Fenêtre de tolérance 2 polls avant émission | Retirer le POST JS (bump `?v=`) |
| 1 | 6 h | Divergence de re-packaging (verdict ≠ conseil) | Parité testée en rejeu AVANT prod ; aucun consommateur ne lit encore le bloc | 1 ligne dans app.py + restart nssm, 30 s |
| 2 | 5 h | Écran PANNE trop sensible → trader aveugle en séance | Seuil de staleness aligné sur l'existant ; déploiement un samedi | Re-scp ancien `dashboard.js` + bump `?v=` |
| 3 | 4 h | Un bot trade sur un verdict différent du legacy | Double lecture loggée avant bascule ; kill-switch env 30 s | `MIA_BOT_USE_VERDICT=0` + restart |
| 4 | 10 h (4a : 6, 4b : 4) | Changement d'affichage FAVORISER (latch par barre) perçu comme régression | Diff rejoué et validé par Jackson avant déploiement ; 4a et 4b des jours différents | Revert fichier par fichier |
| 5 | 3 h | Le retrait du boost MTF change des verdicts en séance | C'est le but ; validé sur rejeu chiffré d'abord | Revert `stabilizers.py` seul |
| 6 | 6 h | Le nouveau cœur diverge sur des cas non rejoués | Rejeu 10 jours arbitré ; beacon + bots surveillés | Revert `builders.py` + `verdict.py` + app.py |

**Total : ~38 h** étalées sur 6-8 semaines (une phase par semaine maximum, GO
mesuré entre chaque).

---

## 5. Budget simplicité (LOC production, hors tests)

| Poste | Ajouté | Supprimé |
|---|---|---|
| `verdict.py` (assemblage, portes structurées, latch, fraîcheur, tier) | 280 | |
| `builders.py` : champ `portes` structuré (Phase 1) | 15 | |
| `app.py` : attache verdict / retrait glue (P6) | 15 | 45 |
| `log_catalog.py` : 5 codes | 8 | |
| Beacon parité (JS + endpoint + comparateur) | 80 | |
| Vue `confluence` serveur | 60 | |
| `tier_filter.py` : filtre verdict (remplace `_simplify_conseil`) | 20 | 15 |
| JS : `reconcileFavorWithMtf` | | 30 |
| JS : comptage local + checklist parallèle | | 100 |
| JS : clusters de confluence | | 115 |
| JS : labels locaux du feed + seuils 70/30 | | 25 |
| `stabilizers.py` : `_enrich_regime_with_mtf` | | 95 |
| `stabilizers.py` : `_stabilize_favor` | | 135 |
| `builders.py` : mutation favor dans `build_advisory` | | 20 |
| `builders.py` : appel `compute_bias` + override dupliqué | | 50 |
| `builders.py` : cœur du comptage `build_conseil_global` (P6) | | 130 |
| `deploy.sh` : ligne min.js | | 1 |
| **Total** | **≈ 478** | **≈ 761** |

**Net : ≈ −280 LOC actives**, plus la suppression de ~4 fichiers `.bak`
(plusieurs milliers de lignes hors exécution) et du `dashboard.min.js` mort.
Tests ajoutés : ~350 LOC, comptées à part.

Abstractions nouvelles — il n'y en a que trois, chacune adossée à un défaut
constaté : le **contrat versionné** (le client recalcule et inverse, 13:54 ;
écran figé au restart), le **beacon de parité** (divergence écran/API invisible
3 mois, logs morts), la **porte DONNEES fail-closed** (VIX 0 rendu comme
calme). Refusé explicitement, car aucun défaut constaté ne les justifie :
nouvel endpoint dédié, Redis/SQLite pour l'état, framework front, renommage des
enums, refonte de `compute_regime`.

---

## Fichiers critiques

- `DASHBOARD/api/builders.py` (build_conseil_global l.1149, build_advisory l.865, build_trade_suggestion l.1436, build_regime_context l.173)
- `DASHBOARD/api/app.py` (route /api/dashboard l.1138-1350)
- `DASHBOARD/api/stabilizers.py` (_enrich_regime_with_mtf, zone_info, _stabilize_favor, _niveaux_cles)
- `DASHBOARD/static/js/dashboard.js` (renderGlobalAdvice l.2009, reconcileFavorWithMtf l.1825, renderConfluence l.1901, updateSignalFeed l.1447)
- `CORE/regime_engine.py` (compute_regime l.229 — l'unique cerveau conservé)
