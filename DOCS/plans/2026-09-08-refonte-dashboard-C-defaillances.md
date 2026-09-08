# Refonte dashboard — Proposition C : LES DÉFAILLANCES D'ABORD (robustesse)

*Proposition d'agent architecte (08/09/2026). NON VALIDÉE — à arbitrer par
Jackson et Fable avant toute ligne de code. Deux propositions concurrentes :
[A contrat d'abord](2026-09-08-refonte-dashboard-A-contrat.md),
[B moteur unique](2026-09-08-refonte-dashboard-B-moteur.md).*

**Principe directeur** : chaque mode de défaillance constaté vient d'une
**duplication d'état** (deux calculs, deux dicts, deux sources, deux versions
de code) ou d'un **défaut silencieux** (valeur par défaut, except avalé, écran
figé). L'architecture cible supprime les duplications par construction et
transforme chaque défaut restant en état PANNE visible. Chaque mécanisme
ci-dessous est adossé à un incident daté — aucun ne répond à une menace
imaginaire.

## 1. Table des 8 modes de défaillance → mécanisme → test continu

| # | Mode constaté | Mécanisme qui le rend impossible ou bruyant | Test qui le prouve en continu |
|---|---|---|---|
| 1 | Écran figé sur échec de fetch (08/09 13:26) | **Fraîcheur obligatoire dans le rendu** : la carte verdict n'est rendue que par UNE fonction `rendreVerdict(payload, ageMs)` ; un watchdog JS (timer indépendant du poll) passe la carte en état `PÉRIMÉ` (gris + « dernière donnée HH:MM:SS ») dès que `ageMs > 2×POLL_INTERVAL`. Le pattern existe déjà pour les bots V2 (`STATE FROZEN`, dashboard.js l.5619). Impossible structurellement : le DOM du verdict n'est plus écrit ailleurs que par cette fonction. | Test golden headless (Playwright) : charger la page sur fixture, couper le réseau, avancer l'horloge, asserter que le texte devient `PÉRIMÉ` et plus jamais `VENTE`. En CI à chaque commit JS. |
| 2 | Réplique de décision côté client (13:54 : backend ATTENDRE, écran VENTE) | **Zéro décision côté client** : suppression du calcul local bull/bear (dashboard.js l.1990-2110) — le JS rend `conseil_global.checks[]` verbatim. Garde structurelle : **lint « no-decision-in-JS »** — un test CI greppe dashboard.js pour les tokens interdits (`bullPoints`, `bearPoints`, affectation calculée de `"ACHAT"/"VENTE"`). | **Test d'or de parité écran==API** : en CI, servir la page sur un payload enregistré et asserter `texte(#global-action) === payload.conseil_global.es.action` sur un corpus de fixtures (directionnel, hors zone, CONFLIT, PANNE). LE test de non-régression du système. |
| 3 | reconcileFavorWithMtf inverse le sens (survivant 3 mois du fix Python 08/06) | Même mécanisme que #2 (suppression + lint). La cause racine était la **double implémentation** : un override supprimé d'un côté survit de l'autre. Cible : il n'existe plus de « l'autre côté ». | Le lint no-decision-in-JS échoue si une fonction de réconciliation réapparaît ; le test de parité #2 échoue si le favor affiché diffère du payload. |
| 4 | Émissions de logs mortes 3 mois (AttributeError avalée) | (a) **Canari de boot** : au démarrage, émettre `DASHBOARD_BOOT` via le vrai logger et vérifier que la ligne existe sur disque ; échec → `/api/health` dégradé. (b) **Wrapper unique `emit_sur`** remplaçant les 6 blocs `try/except pass` disséminés : compte les échecs et expose `log_emit_failures` dans `/api/health`. (c) Généraliser `DASHBOARD/tests/test_log_emission.py` : paramétrer sur TOUS les modules qui déclarent `_v2log` et chaque code du catalogue utilisé. | Test d'émission généralisé en CI (import de chaque module + émission réelle vérifiée sur disque) + check J+1 automatisable via `/api/health.log_last_emit_age`. |
| 5 | VIX 0.0 affiché « calme » vert | **Fail-closed au contrat, pas au rendu** : les grandeurs physiques affichées ne portent JAMAIS de défaut numérique. Règle : `get_field(default=0)` interdit pour les champs affichés ; le reader renvoie `null` (VIX ≤ 0 → `null`), le contrat type le champ nullable, le JS rend `null` → « — PANNE feed » gris. La jauge verte devient impossible : il n'y a pas de valeur à colorier. | Test unitaire serveur : bar avec `vix_level=0` → payload `vix=null` + `sante.vix_ok=false`. Test golden UI : fixture `vix=null` → jauge grise « PANNE ». Liste blanche des champs physiques vérifiée par un test qui échoue si un nouveau champ affiché utilise un défaut numérique. |
| 6 | deploy.sh sert un dashboard.min.js d'avril | **Deploy vérifié par empreinte** : (a) suppression de `dashboard.min.js` (repo, VPS, ligne 64 de deploy.sh — index.html charge `dashboard.js?v=171`) ; (b) le script calcule le SHA-256 local de chaque fichier déployé, puis après `nssm restart` télécharge l'asset servi et compare — mismatch → échec bruyant ; (c) `/api/version` expose `{git_sha, js_sha, contract_version}` ; le JS embarque son stamp et compare au boot — mismatch → bandeau « version périmée, rechargez ». | Étape de vérification post-deploy intégrée au script (bloquante) + check quotidien : hash du JS servi en prod == hash du JS du dépôt. |
| 7 | Deux sources MTF selon la carte ; composante V auto-corrélée sur les 4 TF | **Une seule lecture MTF par cycle** : le snapshot MTF calculé pour `/api/dashboard` (déjà caché 10 s, app.py l.1167) devient LA source ; `/api/mtf/{sym}` sert le même snapshot caché (même `snapshot_ts`) ou disparaît, le JS lisant le payload principal (supprime le fetch séparé l.1814). Pour l'auto-corrélation V : le MTF est **dégradé en affichage** — plus de boost (le +0.25 de `_enrich_regime_with_mtf` viole « portes soustractives uniquement ») ; seul survit le **véto 4/4 opposé** (soustractif, validé 08/09), avec un flag `mtf.degrade=true` tant que la recalibration (autre chantier) n'est pas faite. | Test CI : pour un même instant, `GET /api/dashboard.mtf_es.snapshot_ts == GET /api/mtf/ES.snapshot_ts` (ou test d'absence de la route). Test unitaire : le score du verdict est identique avec MTF 4/4 et MTF 0/4 aligné (plus aucun chemin additif), et bascule en CONFLIT uniquement sur 4/4 opposé. |
| 8 | Cliquet FAVORISER en polls (3 votes = 15 s), latch sans expiration, asymétrie ES/NQ (dict stabilisé ≠ dict de la réponse) | **Hystérésis indexée sur la barre, opérant sur LE dict de la réponse** : la stabilisation vit dans le pipeline verdict (un seul appel par instrument), avance ses votes uniquement quand `bar_ts` change, latch avec `expire_bar_ts`. L'asymétrie 08/09 venait de deux dicts régime (`regime_es` local l.1162 vs `response["es"]["regime"]` l.1274, rustine l.1329-1332) : la cible construit l'état d'un instrument UNE fois et la réponse référence cet objet — la seconde copie n'existe plus. | Test unitaire : deux appels même `bar_ts` → zéro vote ajouté ; latch expiré → retour NEUTRE motivé. Test paramétré ES/NQ sur le MÊME chemin de code. Test de non-fuite : `response[sym].regime.favor == favor stabilisé` (jamais le brut). |

## 2. Architecture cible

### 2.1 Flux

```
readers (fail-closed : absent → null, jamais 0)
   └→ SNAPSHOT par cycle : {bar, mtf, options, zone, ts}   ← une lecture, un ts
        └→ DASHBOARD/api/verdict.py : construire_verdict(snapshot, etat[sym])
             1. CORE/regime_engine.compute_regime      ← LE cerveau (direction, mode, score)
             2. portes SOUSTRACTIVES (ne peuvent que dégrader, jamais inverser ni booster) :
                porte de confirmation (delta/range_pos/DIV — ex-points du conseil, voir 2.2)
                porte de lieu (zone_info, P10 par instrument)      [existante 08/09]
                véto MTF 4/4 opposé → CONFLIT                       [existant 08/09]
                gamma gate (mur MQ proche)                          [existant]
                porte de session + porte de données (sante.*_ok)
             3. hystérésis par barre (votes/latch indexés bar_ts) + fraîcheur
        └→ VerdictV1 (contrat unique) publié dans le payload
             ├→ carte JS (rendu verbatim, zéro calcul)
             ├→ paper traders (executable_action du MÊME objet)
             └→ tier_filter (ne peut que RETIRER des champs, jamais altérer)
```

### 2.2 Contrat de verdict (VerdictV1)

```
{
  contract_version: "verdict.v1",
  sym, bar_ts, server_ts, snapshot_ts,
  mode, direction: ACHAT|VENTE|ATTENDRE|CONFLIT (+ nuance prudent),
  executable: idem avec fraîcheur exécution (remplace action/executable_action),
  score, confiance, en_zone, zone: {niveau, prix, dist_ticks, seuil_ticks},
  portes: [{code, declenchee, motif}],          ← les checks, structurés, rendus tels quels
  fraicheur: {etat, age_bars, signal_id},
  sante: {vix_ok, niveaux_ok, mtf_ok, donnees_ok}   ← fail-closed visible
}
```

Règles du contrat : le client vérifie `contract_version` et refuse de rendre un
verdict qu'il ne comprend pas (état PANNE, jamais un rendu approximatif). Tout
champ physique est nullable. `portes[]` remplace les strings `checks[]` — le
trader voit ENFIN pourquoi c'est ATTENDRE.

Conformité « un seul cerveau » : les 6 signaux à points de
`build_conseil_global` (bias 2 pts, delta 1, range_pos 1, MTF 1, DIV 2)
constituent aujourd'hui un second cerveau capable de produire une direction
propre. Dans la cible, la direction vient exclusivement de `compute_regime` ;
delta/range_pos/DIV deviennent une **porte de confirmation** soustractive : une
direction non confirmée par k signaux indépendants passe ATTENDRE. Par
construction, cette porte ne peut jamais produire le sens opposé de
compute_regime — la classe de bug du 13:54 disparaît.

### 2.3 Sort des 14 cerveaux

| Cerveau | Sort |
|---|---|
| `CORE/regime_engine.compute_regime` | **GARDÉ** — seul cerveau de direction (audité 04/09, calibré par instrument). |
| `_compute_bias_proxy` | Absorbé : composant interne de compute_regime, plus jamais appelé/exposé seul. |
| `CORE/bias_calculator.compute_bias` | Retiré du chemin dashboard (le bias affiché = celui du régime). Son sort global (rétroport skip range_pos, double comptage delta/cvd) relève du chantier calibration, hors périmètre ici. |
| `read_mtf_bias` | **Dégradé en fournisseur de données** : scores par TF affichés, flag `degrade=true`, aucun poids dans le score. Source unique (snapshot partagé). |
| `_enrich_regime_with_mtf` | **SUPPRIMÉ** (le boost additif viole « soustractif uniquement » ; le véto 4/4 migre dans verdict.py). |
| `build_advisory` | Vue pure sur le verdict (textes, conseils) — plus aucun favor/direction propre. |
| `_stabilize_favor` | **REMPLACÉ** par l'hystérésis par barre dans verdict.py (un état, un dict, expiration). |
| `build_conseil_global` | **REFONDU** en portes de confirmation dans verdict.py ; le champ `conseil_global` du payload devient un alias de VerdictV1 (compat une release). |
| `build_trade_suggestion` | Vue : ne rend SL/TP que si `verdict.direction` directionnelle ET `en_zone` ET unité `atr` certifiée (assert) ; ne calcule plus de direction. |
| JS réplique du conseil | **SUPPRIMÉ** — rendu verbatim de `verdict.portes`. |
| JS `reconcileFavorWithMtf` | **SUPPRIMÉ** (l.1825-1854). |
| JS override conseils | **SUPPRIMÉ** — les conseils viennent du serveur. |
| JS zones de confluence locales | **MIGRÉES** côté Python dans `_niveaux_cles`/zone_info (la carte des niveaux unique existe déjà, stabilizers.py l.175) ; le JS rend les clusters servis. |
| JS feed divergence 70/30 | **SUPPRIMÉ** — le feed rend les événements serveur (`level_breaks`, `signals_journal`, transitions de verdict), déjà tous côté serveur. |

### 2.4 Santé de bout en bout

`/api/health` enrichi (pas un nouveau service) : `{last_bar_age,
log_last_emit_age, log_emit_failures, git_sha, js_sha, contract_version,
workers_ok}`. Au démarrage, l'app **refuse de démarrer** si elle détecte plus
d'un worker (aujourd'hui c'est un commentaire dans stabilizers.py, demain une
assertion). Un état vert signifie : données fraîches, logs qui s'écrivent,
code servi == code du dépôt.

## 3. Plan de migration par phases (revertables, hors séance US)

**Phase 0 — Les filets (aucun changement de comportement).**
Contenu : deploy.sh par empreinte + suppression min.js ; `/api/version` ;
canari de boot + `emit_sur` + health enrichi ; CI : test d'émission généralisé,
squelette du harnais de parité (fixtures enregistrées depuis la prod).
Vérification : hash servi == hash dépôt en prod ; `DASHBOARD_BOOT` présent ;
tests existants verts. GO : filets verts 24 h. Rollback : ancien deploy.sh.

**Phase 1 — L'écran honnête (JS seul, serveur intact).**
Contenu : watchdog fraîcheur + états PÉRIMÉ/PANNE ; check `contract_version` ;
suppression de reconcileFavorWithMtf, du calcul local du conseil, de l'override
conseils ; rendu des `checks` backend ; VIX null → gris ; suppression du double
fetch MTF. Vérification : test d'or de parité + test coupure réseau + capture
manuelle en pré-marché. GO : parité verte sur tout le corpus. Rollback :
revert d'un seul fichier (dashboard.js) + bump `?v=`.

**Phase 2 — Le contrat en mode ombre (serveur, sans bascule).**
Contenu : `verdict.py` (compute_regime + portes existantes migrées + hystérésis
par barre) publié dans le payload EN PLUS de `conseil_global` legacy ; émission
`VERDICT_DIVERGENCE_LEGACY` à chaque désaccord ; readers fail-closed (VIX,
niveaux). Vérification : rejeu des JSONL des 10 derniers jours ; compteur de
divergences expliqué à 100 % (chaque écart = un bug legacy connu, sinon on
s'arrête). GO : 3-5 séances d'ombre sans divergence inexpliquée. Rollback :
flag env — le champ verdict disparaît du payload.

**Phase 3 — La bascule des consommateurs.**
Contenu : la carte JS et les paper traders lisent `verdict` (`executable`
remplace `executable_action`, mêmes sémantiques de fraîcheur 2/4 barres) ;
`conseil_global` devient alias du verdict ; suppression de
`_enrich_regime_with_mtf` et de l'ancien `_stabilize_favor` ; source MTF unique
effective. Vérification : parité verte ; une séance paper complète avec
comparaison décision-par-décision bot vs écran (les deux lisent le même objet
— le test devient trivial). GO : zéro divergence bot/écran sur une séance.
Rollback : les consommateurs relisent le champ legacy (conservé une release
exprès).

**Phase 4 — La purge.**
Contenu : suppression des champs legacy, des cerveaux morts (advisory
direction, réplique JS résiduelle, confluence locale → clusters serveur, feed
70/30), audit tier_filter (FREE ne voit plus action/bias sans les portes ; le
filtre ne peut que retirer). Vérification : suite complète + lint
no-decision-in-JS + `wc -l` du budget simplicité. GO : tout vert. Rollback :
git revert du commit de purge.

La campagne V3 (`V3/`) n'est touchée à aucune phase. Chaque phase = commits
déployables et revertables indépendamment, exécutés hors 15:30-22:00 Paris.

## 4. Estimation d'effort

| Phase | Contenu | Heures |
|---|---|---|
| 0 | Deploy empreinte, /api/version, canari logs, CI émission + harnais parité | 6 h |
| 1 | JS honnête (watchdog, PANNE, suppressions, rendu checks) | 8 h |
| 2 | verdict.py + mode ombre + rejeu 10 jours | 12 h |
| 3 | Bascule consommateurs + suppressions serveur | 10 h |
| 4 | Purge + tier_filter + bilan budget | 6 h |
| **Total** | (+ 3-5 séances d'observation ombre, ~15 min/jour) | **42 h** |

## 5. Budget simplicité chiffré

| Mouvement | LOC |
|---|---|
| Supprimé JS : réplique conseil (~120), reconcileFavorWithMtf (~30), confluence locale (~150), feed divergence (~40), override conseils (~30), double fetch MTF (~15) | **−385** |
| Supprimé Python : `_enrich_regime_with_mtf` (−97), ancien `_stabilize_favor` net (−90), scoring conseil → portes net (−150), advisory direction (−40), plomberie double-dict app.py (−30) | **−407** |
| Supprimé artefact : dashboard.min.js (138 Ko servi périmé) | −1 fichier |
| Ajouté : verdict.py + contrat (~220), clusters serveur migrés (~70), watchdog/PANNE/version JS (~90), /api/version + health (~35), deploy empreinte (~35) | **+450** |
| **Net production** | **≈ −342 LOC** |

Tests ajoutés (parité golden, émission généralisée, fail-closed, hystérésis,
vérif deploy) : ~+350 LOC — additifs par nature, ce sont eux qui rendent les 8
modes bruyants en continu. Net global ≈ stable, net décision fortement
négatif : moins de code qui décide, plus de code qui prouve.

---

## Fichiers critiques

- `DASHBOARD/api/app.py` (route /api/dashboard l.1138-1350 — assemblage, double-dict à supprimer, health/version)
- `DASHBOARD/api/builders.py` (build_conseil_global l.1149-1428 — portes à migrer vers verdict.py)
- `DASHBOARD/api/stabilizers.py` (_enrich_regime_with_mtf à supprimer, _stabilize_favor à remplacer, zone_info/_niveaux_cles à étendre)
- `DASHBOARD/static/js/dashboard.js` (l.1215-1282 fetch/backoff, l.1825-1854 reconcile, l.1990-2180 réplique conseil)
- `DASHBOARD/deploy.sh` (empreinte + purge min.js) et `DASHBOARD/tests/test_log_emission.py` (le modèle à généraliser)
