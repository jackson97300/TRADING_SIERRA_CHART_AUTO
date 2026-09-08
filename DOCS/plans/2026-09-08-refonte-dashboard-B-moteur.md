# Refonte dashboard — Proposition B : LE MOTEUR UNIQUE (coupe franche)

*Proposition d'agent architecte (08/09/2026). NON VALIDÉE — à arbitrer par
Jackson et Fable avant toute ligne de code. Deux propositions concurrentes :
[A contrat d'abord](2026-09-08-refonte-dashboard-A-contrat.md),
[C défaillances d'abord](2026-09-08-refonte-dashboard-C-defaillances.md).*

**Angle assumé** : l'état d'arrivée le plus petit possible. Un seul module
serveur décide, tout le reste affiche. Les cerveaux redondants sont
physiquement supprimés à la fin du plan, pas gardés en réserve. La migration
est plus abrupte que les alternatives, mais chaque étape est hors séance,
revertable, et la coupe finale n'a lieu qu'après un double-run mesuré.

---

## 1. LE MOTEUR UNIQUE : `CORE/verdict.py`

### 1.1 Principe

Un module nouveau d'environ 260 lignes, construit AUTOUR de
`CORE/regime_engine.compute_regime` (l.229-520), qui reste le seul calcul de
direction du système. `verdict.py` ne calcule AUCUNE direction lui-même : il
appelle `compute_regime` une fois, puis applique des **portes soustractives**
dans un ordre fixe. Une porte ne peut que dégrader le verdict (direction →
ATTENDRE/CONFLIT/PANNE), jamais l'inverser ni le renforcer. C'est la
généralisation du principe déjà déployé le 08/09 (porte de lieu + véto MTF) —
sauf qu'au lieu d'être un filet aval collé sur un système de points, les
portes deviennent LE mécanisme, et le système de points bull/bear disparaît.

Signature unique :

```
compute_verdict(bar_enriched, symbol, options, mtf) -> dict  # verdict.v1
```

Appelée exactement une fois par instrument par poll, depuis `/api/dashboard`
(app.py l.1285-1288 aujourd'hui). Personne d'autre ne décide.

### 1.2 Schéma du verdict (verdict.v1)

```json
{
  "schema": "verdict.v1",
  "sym": "ES",
  "bar_ts": 1757343300000,
  "mode": "TREND | RANGE | NORMAL",
  "direction": "LONG | SHORT | NEUTRE",
  "action": "ACHAT | VENTE | ATTENDRE | CONFLIT | PANNE",
  "prudence": true,
  "score": -0.42,
  "confiance": 0.33,
  "vol_regime": "LOW | NORMAL | HIGH | EXTREME | INCONNU",
  "en_zone": false,
  "zone": {"niveau": "VAL", "prix": 6512.25, "dist_ticks": 14, "seuil_ticks": 6},
  "portes": [
    {"nom": "DONNEES", "etat": "OK"},
    {"nom": "SESSION", "etat": "OK"},
    {"nom": "VOL", "etat": "OK"},
    {"nom": "ZONE", "etat": "BLOQUE", "motif": "plus proche VAL a 14t (seuil 6t)"},
    {"nom": "GAMMA", "etat": "OK"},
    {"nom": "MTF", "etat": "OK"}
  ],
  "fraicheur": {"etat": "NEW | PERSISTENT | EXPIRED | IDLE", "age_barres": 1, "signal_id": "ab12cd34"},
  "sante": {"vix": "OK | TROU", "donnees": "OK | STALE | TROU"},
  "details": ["IB cassee UP", "Day Type: Trend", "..."]
}
```

Points structurants :

- **`direction` et `action` sont séparés.** `direction` = la sortie brute de
  `compute_regime` (toujours visible — un trader doit pouvoir voir « le moteur
  voit SHORT mais la porte de zone bloque »). `action` = ce qui est tradable
  ICI et MAINTENANT, après portes. Exactement la distinction que l'incident du
  13:54 UTC a rendue vitale.
- **`ACHAT PRUDENT` / `VENTE PRUDENTE` disparaissent comme actions
  distinctes.** Artefact du système de points. Cible : `action=ACHAT` +
  `prudence=true` quand `confiance` sous seuil calibré. Le JS affiche « ACHAT
  PRUDENT » comme concaténation d'affichage — zéro logique.
- **`PANNE` est une action de premier rang** : données stale/absentes ou VIX à
  0 produisent un verdict PANNE affiché comme tel. Fail-closed contractuel.
- La projection `conseil_global` **conserve les clés existantes** (`action`,
  `executable_action`, `reason`, `checks`, `freshness`, `freshness_exec`,
  `age_bars`, `signal_id`) pour ne pas toucher les paper traders
  (`CORE/mia2_brain_v6_databento.py` l.1411-1413, `CORE/mia_paper_trader.py`
  l.1721 lisent `executable_action` avec fallback `action`). ~30 lignes de
  projection dans `verdict.py`.

### 1.3 Les portes soustractives (ordre fixe)

| # | Porte | Règle | Sortie si bloquée | Log catalogué |
|---|-------|-------|-------------------|---------------|
| 1 | DONNEES | bar absente, `ts` > 90 s, ou `vix_level <= 0` | `PANNE` (VIX TROU : `vol_regime=INCONNU`, directionnel interdit) | `VERDICT_GATE_DATA` |
| 2 | SESSION | hors session US | `ATTENDRE` motif session | `VERDICT_GATE_SESSION` |
| 3 | VOL | `vol_regime == EXTREME` | `ATTENDRE` | `VERDICT_GATE_VOL` |
| 4 | ZONE | `zone_info` (déplacé ici depuis stabilizers.py l.210-232, avec `_niveaux_cles` l.175-200) : hors zone P10 | `ATTENDRE` | `CONSEIL_ZONE_GATE_BLOCK` (existant, conservé) |
| 5 | GAMMA | appel du SSoT `CORE/gamma_veto_engine` (déjà unique depuis l'incident #74) : mur du côté de la direction | `ATTENDRE` | `VERDICT_GATE_GAMMA` |
| 6 | MTF | direction contre un alignement 4/4 opposé (MTF assaini, cf. 1.4.2) | `CONFLIT` | `CONSEIL_MTF_VETO_CONFLIT` (existant, conservé) |
| 7 | FRAICHEUR | hystérésis et expiration PAR BARRE (cf. 1.4.3) | `ATTENDRE` (EXPIRED) | `VERDICT_LATCH` |

Chaque évaluation de porte figure dans `verdict["portes"]` même quand elle
passe — les motifs HORS ZONE / VETO MTF invisibles à l'écran aujourd'hui
deviennent visibles par construction. Chaque CHANGEMENT d'action émet
`VERDICT_CHANGE` via `CORE/logging_v2.get_logger` (pattern réparé le 08/09,
couvert par `test_log_emission.py`).

### 1.4 Résolution des 4 défauts de fond — par SUPPRESSION, pas par ajout

**1.4.1 Double comptage delta/cvd (identiques 600/600 barres).** Dans
`_compute_bias_proxy` (regime_engine.py l.160-176), la branche cvd disparaît
entièrement : `cvd_day_dir` est une colonne condamnée par V3, mesurée identique
à `delta_day_dir` — la « modulation ±0.05 » et la calibration adaptative
0.20/0.25 modulent du bruit dupliqué. Reste UN vote orderflow `delta_day_dir` à
poids 0.25. Suppression de ~20 lignes ; aucun code nouveau. Le double comptage
aval (delta compté une 2e fois dans `build_conseil_global` l.1182-1187)
disparaît avec `build_conseil_global` lui-même.

**1.4.2 Composante V du MTF auto-corrélée.** Le défaut mesuré :
`read_mtf_bias` (readers.py l.1081-1087) calcule V = prix vs VWAP **jour**
pour les 4 timeframes — la même valeur à 40 % de poids quatre fois, donc
« 4/4 » ≈ 1 vote. Coupe franche : **la composante V est supprimée**, le score
par TF devient 50 % delta agrégé du TF + 50 % momentum du TF (les deux seules
grandeurs réellement par-TF du calcul actuel), étiquetés au seuil unique
(cf. 1.4.4). Le MTF assaini a droit à exactement UN rôle décisionnel : la
porte de cohérence n° 6 (on ne trade pas CONTRE un 4/4 unanime — mécanisme
prouvé en prod le 08/09, 7 CONFLIT rejoués corrects). Le boost de score
`_enrich_regime_with_mtf` (+0.25) est supprimé sans remplacement : le MTF ne
pousse plus jamais un verdict, il ne peut que l'interdire. La grille MTF à
l'écran reste servie par `/api/mtf/{symbol}`, recalibrée par le même
changement.

**1.4.3 FAVORISER : cliquet en polls, latch sans expiration, asymétrie
ES/NQ.** `_stabilize_favor` (stabilizers.py l.305-438) est supprimé
intégralement. Remplacé par le bloc FRAICHEUR du moteur (~30 lignes) :
(a) l'hystérésis compte des **changements de `bar_ts`**, pas des polls — une
confirmation = 2 barres, plus jamais « 3 votes = 15 s » ; (b) le latch
**expire** : après N barres sans reconfirmation, retour IDLE (le mécanisme
freshness DISPLAY/EXECUTION 2/4 barres de `_evaluate_signal_freshness` est
absorbé tel quel — le seul morceau de `build_conseil_global` qui survit) ;
(c) la symétrie ES/NQ est structurelle : un seul chemin de code, état par
`sym` — l'asymétrie actuelle (ES stabilise un dict, NQ un autre, app.py
l.1326-1332) ne peut plus exister car il n'y a plus qu'un dict, le verdict.

**1.4.4 Seuils d'étiquette incohérents (±0.30 vs ±0.25).** Une constante
unique `SEUIL_ETIQUETTE` par instrument dans `CORE/regime_calibration.py` (le
fichier qui porte déjà la règle « jamais de seuil en dur, jamais recopié d'un
instrument à l'autre »). Consommée par `_compute_bias_proxy` (aujourd'hui 0.30
en dur l.216-218) et par l'étiquetage MTF (aujourd'hui 0.25, readers.py
l.1107-1112 et l.1140-1141). Tous les autres étiqueteurs (bias_calculator
±0.30, _enrich ±0.25, JS ±0.25 implicite) meurent avec leurs modules.

---

## 2. SORT DE CHACUN DES 14 CERVEAUX

### Côté serveur (9)

| # | Cerveau | Lieu | Sort | Étape |
|---|---------|------|------|-------|
| 1 | `compute_bias` | CORE/bias_calculator.py (588 l.), appelé par builders.py l.204 | **SUPPRIMÉ du chemin dashboard.** La carte BIAS affiche `verdict.score` / `verdict.direction`. Le fichier reste temporairement pour `CORE/cross_instrument.py` (hors périmètre), avec bannière de dépréciation. | 3 |
| 2 | `_compute_bias_proxy` | regime_engine.py l.118-222 | **ABSORBÉ : devient LE biais du système.** Nettoyé du cvd (1.4.1) et branché sur le seuil unique (1.4.4). | 2 |
| 3 | `compute_regime` | regime_engine.py l.229-520 | **CONSERVÉ — le cœur.** Aucun changement de logique de vote. Le garde-fou de cohérence 3-facteurs conservé À L'INTÉRIEUR — la réplique de l'override dans builders.py l.261-266 est supprimée, c'était un double. | — |
| 4 | `read_mtf_bias` | readers.py l.998-1164 | **DÉGRADÉ EN VUE** : composante V supprimée, renormalisation delta/momentum, seuil unique. Sert la grille `/api/mtf` et fournit bulls/bears à la seule porte n° 6. Plus jamais un boost. | 2-3 |
| 5 | `_enrich_regime_with_mtf` | stabilizers.py l.67-162 | **SUPPRIMÉ** sans remplacement (le boost +0.25 était la moitié du double comptage MTF ; le log `BIAS_NEUTRAL_ZONE_FALLBACK` meurt avec). | 5 (mort étape 3) |
| 6 | `build_advisory` | builders.py l.865-1019 | **DÉGRADÉ EN VUE** (~60 l.) : formate des conseils texte depuis `verdict` + session. Son override divergence qui RÉÉCRIT `regime["favor"]` (l.951-967) — un cerveau caché dans un formateur — est supprimé. `qui_a_la_main` devient une projection de `verdict.score`. | 3-4 |
| 7 | `_stabilize_favor` | stabilizers.py l.305-438 | **SUPPRIMÉ**, remplacé par le bloc FRAICHEUR du moteur. `_stabilize_qui` (l.449-472) supprimé avec. | 5 (mort étape 3) |
| 8 | `build_conseil_global` | builders.py l.1082-1428 | **SUPPRIMÉ.** Le système de points bull/bear entier (votes fade sans condition de mode, double comptage delta, gamma-cap à 4) disparaît. Survivent, absorbés dans `verdict.py` : la state machine de fraîcheur (l.1105-1146), les deux portes du 08/09 (zone l.1299-1324, véto MTF l.1334-1349) et leurs codes de log. La clé API `conseil_global` reste, produite par projection du verdict (compat paper traders + tier FREE via `_simplify_conseil` inchangé). | 5 (mort étape 3) |
| 9 | `build_trade_suggestion` | builders.py l.1436-1554 | **SUPPRIMÉ.** La carte « suggestion » devient une vue de `verdict.portes`. Les SL/TP affichés sont RETIRÉS tant que l'unité de la colonne `atr` n'est pas certifiée — fail-closed. Réintroduction éventuelle = une vue, jamais un cerveau. | 4 |

### Côté navigateur (5) — dashboard.js devient un afficheur pur

| # | Site | Lieu | Sort | Étape |
|---|------|------|------|-------|
| 10 | Réplique du conseil (calcul local bullPoints/bearPoints) | dashboard.js l.2016-2108 + réconciliation l.2134-2150 | **SUPPRIMÉ.** Remplacé par le rendu direct de `verdict.action`, `verdict.portes`, `verdict.details`, `verdict.fraicheur`. Plus une seule ligne JS capable de produire une action. | 4 |
| 11 | `reconcileFavorWithMtf` | dashboard.js l.1825-1854 | **SUPPRIMÉ IMMÉDIATEMENT** (étape 1). Survivant côté navigateur de l'override MTF supprimé côté Python le 08/06, INVERSE le sens affiché. 30 lignes, danger pur, zéro dépendance. | 1 |
| 12 | Override des conseils par MTF | dashboard.js l.1710-1726 | **SUPPRIMÉ** (réécrit « FAVORISER ACHAT » en « CONFLIT » localement). Même famille que #11. | 1 |
| 13 | Zones de confluence locales | dashboard.js l.1901-2007 | **MIGRÉ EN VUE SERVEUR** : ~45 lignes Python réutilisant `_niveaux_cles` (jamais deux listes qui divergent). Le JS ne garde que le rendu. Les clusters restent informatifs (jamais un point de score). | 4 |
| 14 | Feed de signaux + seuils 70/30 + VIX « calme » | dashboard.js l.1440-1519 (l.1495 : `range_pos >= 70 → "Favorise VENTE"`), l.1628 (« Marché calme ») | **DÉGRADÉ EN AFFICHAGE** : le feed rend les transitions du verdict et les `level_breaks` serveur ; les seuils locaux 70/30 (troisième jeu de seuils !) supprimés. `verdict.sante.vix == "TROU"` s'affiche « DONNÉES VIX INDISPONIBLES », jamais « calme ». Ajout justifié par l'écran figé du 13:26 : chien de garde d'affichage (~15 l.) qui grise la carte CONSEIL si le dernier fetch réussi date de plus de 30 s (« FLUX INTERROMPU »). | 1 (70/30, VIX) et 4 (feed) |

**Cerveau n° 15, hors inventaire mais à signaler** :
`CORE/bot1_v2/dashboard_mirror.py` (967 l.) réplique `build_conseil_global` en
local. Après la bascule il sera mesurablement faux. Hors périmètre de ce plan
(bots), mais la recommandation de sortie est : consommer `conseil_global` de
l'API comme les autres bots, supprimer le miroir. La campagne V3 (V3/) n'est
touchée par rien de ce qui précède — `verdict.py` vit dans CORE/, ne modifie ni
les features ni les datasets, et `compute_regime`/`compute_regime_dict` gardent
leurs signatures pour le pipeline V4.

---

## 3. PLAN DE BASCULE

Fenêtres de déploiement : hors séance US (avant 13:00Z ou après 21:30Z, ou
week-end), via deploy.sh + `nssm restart MIA-Dashboard`. Le restart avec
`--workers 1` remet à zéro les états mémoire : acceptable hors séance, et
l'hystérésis par barre du moteur est fail-safe au reset (elle RETIENT la
publication 2 barres, elle n'invente rien).

**Étape 0 — Outillage et nettoyage deploy (avant tout code moteur).**
- Corriger deploy.sh : supprimer la copie de `dashboard.min.js` (l.64 —
  fichier d'avril, non référencé par index.html qui charge `dashboard.js?v=171`)
  et supprimer le fichier du repo.
- Test d'or de parité écran==API : étendre `CORE/bench_dashboard.py` pour
  affirmer (a) `conseil_global.{es,nq}.action` présent et ∈ vocabulaire fermé,
  (b) après l'étape 4, un contrôle statique en CI : `grep` de dashboard.js
  interdisant toute construction locale d'action (`bullPoints`, `bearPoints`,
  littéraux `"ACHAT"`/`"VENTE"` hors table de couleurs/rendu). L'écran ne PEUT
  plus diverger de l'API quand il n'a plus de quoi fabriquer un verdict — la
  parité devient structurelle, le test la verrouille.

**Étape 1 — Couper les inverseurs client (indépendant du moteur, gain
immédiat).** Suppression de #11, #12, seuils 70/30 et VIX « calme » de #14,
ajout du chien de garde d'affichage. Bump `?v=`. Aucun changement serveur.
C'est la partie du risque prouvé la plus dangereuse (inversion de sens à
l'écran) et la moins coûteuse.

**Étape 2 — Naissance du moteur en double-run muet (shadow).**
`CORE/verdict.py` écrit, appelé dans `/api/dashboard` À CÔTÉ du chemin legacy,
sous flag ENV `MIA_VERDICT_ENGINE=shadow` (même pattern que
`MIA_REGIME_SKIP_ENABLED`, rollback nssm 30 s). Le verdict shadow n'est PAS
exposé dans la réponse : chaque désaccord `shadow.action != legacy.action`
émet `VERDICT_SHADOW_DIFF` (log catalogué, avec les deux verdicts et les
portes). Inclut les correctifs 1.4.1/1.4.2/1.4.4 (le shadow tourne avec le
moteur DÉJÀ corrigé — on compare la cible réelle, pas une copie du legacy).
Durée : minimum 5 séances US complètes.

**Étape 3 — Bascule serveur par flag, hors séance.** `MIA_VERDICT_ENGINE=on` :
`response["conseil_global"]` devient la projection du verdict ; les appels à
`_enrich_regime_with_mtf`, `_stabilize_favor`, `_stabilize_qui`,
`build_conseil_global`, `compute_bias` sont contournés (le code reste en
place, mort, pour rollback instantané par flag) ; les champs de la carte régime
sont servis depuis le verdict. Les paper traders ne voient qu'un changement de
distribution des valeurs, pas de schéma. **Rollback = flag off + restart
(30 s), sans redéploiement.**

**Étape 4 — JS afficheur pur.** #10 remplacé par le rendu du verdict (les
motifs HORS ZONE / VETO MTF deviennent enfin visibles), #13 migré en vue
serveur, carte suggestion → vue des portes. Bump `?v=`. Activation du grep CI
de l'étape 0. Rollback = re-servir la version JS précédente.

**Étape 5 — Suppression physique (la coupe).** Après 5 séances stables
post-étape 4 : suppression des corps morts (`build_conseil_global` + state
machine locale, `build_trade_suggestion`, `build_advisory` décisionnel,
`_enrich_regime_with_mtf`, `_stabilize_favor`, `_stabilize_qui`, appel/import
`compute_bias` dans builders, composante V du MTF, branche cvd du proxy,
backups `builders.py.bak*`), suppression du flag, purge des tests devenus sans
objet (`test_bug4_mtf_double_counting.py`) remplacés par `test_verdict.py`.
Rollback = git revert du commit unique de suppression.

**Critères de GO :**
- GO étape 2→3 : chaque `VERDICT_SHADOW_DIFF` de la période est rattaché à un
  défaut corrigé DOCUMENTÉ (double comptage delta, V auto-corrélée, seuils,
  cliquet) — zéro désaccord inexpliqué ; zéro PANNE non justifiée par un vrai
  trou de données ; latence `/api/dashboard` inchangée.
- GO étape 4→5 : 5 séances sans incident, bench de parité vert chaque jour,
  taux d'ATTENDRE/CONFLIT cohérent avec les mesures pré-deploy des portes
  (36,7 % ES / 30,0 % NQ bloqués attendus — si on observe 90 %, une porte est
  cassée, pas de GO).

---

## 4. EFFORT, RISQUES, ROLLBACK

| Étape | Effort dev | Attente | Risque principal | Rollback |
|---|---|---|---|---|
| 0 | 3 h | — | Aucun (suppressions + test) | git revert |
| 1 | 2 h | 1 séance d'observation | Un trader habitué à l'override MTF perd un affichage (qui était FAUX) — à annoncer | re-servir JS précédent |
| 2 | 8 h | ≥ 5 séances shadow | Diffs shadow jamais expliqués à 100 % → prolongation, pas de GO (risque planning, jamais trading) | flag=off |
| 3 | 4 h | 2-3 séances | Changement de distribution des actions pour les paper traders (moins de PRUDENT, plus d'ATTENDRE motivé) → casse les séries stats : dater le changement de régime dans les bilans | flag=off, 30 s |
| 4 | 6 h | 5 séances | Régression d'affichage (carte vide si clé absente) → le schéma verdict.v1 garantit toutes les clés, y compris en PANNE | JS précédent + bump |
| 5 | 4 h | — | Un import oublié vers un module supprimé → CI + grep pré-commit des symboles supprimés | git revert du commit de coupe |

Total : ~27 h de dev, ~3 semaines calendaires. Risque transverse :
`dashboard_mirror.py` (bot1_v2) diverge après l'étape 3 — à signaler dès
l'étape 2.

---

## 5. BUDGET SIMPLICITÉ

**Supprimé (runtime, estimé sur les lignes lues) :**

| Bloc | LOC |
|---|---|
| builders.py : build_conseil_global + state machine + gamma wrapper (l.1055-1428) | ~330 |
| builders.py : build_trade_suggestion | ~119 |
| builders.py : build_advisory décisionnel (155 → vue 60) | ~95 net |
| builders.py : appel compute_bias + extraction + override dupliqué (l.196-266) | ~55 |
| stabilizers.py : _enrich_regime_with_mtf, _stabilize_favor, _stabilize_qui | ~260 |
| readers.py : composante V + verdicts MTF simplifiés | ~30 net |
| regime_engine.py : branche cvd | ~20 |
| app.py : câblage stabilisation/zone dupliqué | ~25 |
| dashboard.js : #10 + #11 + #12 + #13 clustering + #14 seuils | ~250 |
| dashboard.min.js (mort) + backups builders.py.bak* | 3 fichiers entiers |
| **Total supprimé** | **~1 180 LOC + 3 fichiers** |

**Ajouté (runtime) :**

| Bloc | LOC |
|---|---|
| CORE/verdict.py (portes + fraîcheur + schéma + projection + logs) | ~260 |
| Vue confluence serveur (sur `_niveaux_cles` existant) | ~45 |
| Codes log_catalog (VERDICT_*) | ~10 |
| JS : rendu verdict/portes + chien de garde d'affichage | ~40 |
| Constante SEUIL_ETIQUETTE (regime_calibration) | ~5 |
| **Total ajouté** | **~360 LOC** (+ ~150 de tests, hors budget runtime) |

**Net : environ −820 lignes de runtime**, plus trois fichiers morts. Quatorze
lieux de décision deviennent deux fichiers : `regime_engine.py` (la direction)
et `verdict.py` (les portes). Trois abstractions nouvelles seulement, chacune
adossée à une défaillance constatée : le schéma verdict.v1 (écran VENTE vs API
ATTENDRE, 13:54Z), le double-run shadow (précédent des émissions mortes 3 mois
— on ne bascule que sur du mesuré), l'hystérésis par barre (cliquet 3 votes =
15 s mesuré). Pas de bus d'événements, pas de plugins de portes, pas de YAML :
aucun mode de défaillance observé ne les justifie.

---

## Fichiers critiques

- `CORE/regime_engine.py` (le cœur conservé ; nettoyage cvd + seuil unique)
- `DASHBOARD/api/builders.py` (build_conseil_global/advisory/trade_suggestion à supprimer ; source des portes absorbées)
- `DASHBOARD/api/stabilizers.py` (zone_info/_niveaux_cles à déplacer ; _stabilize_favor/_enrich_regime_with_mtf à supprimer)
- `DASHBOARD/api/app.py` (point d'appel unique du moteur, flag shadow/on, projection conseil_global)
- `DASHBOARD/static/js/dashboard.js` (les 5 sites de décision client)
