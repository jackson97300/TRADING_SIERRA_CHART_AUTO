# Refonte dashboard — VERDICT du juge adversarial (08/09/2026)

*Jugement croisé des trois propositions
([A contrat](2026-09-08-refonte-dashboard-A-contrat.md),
[B moteur](2026-09-08-refonte-dashboard-B-moteur.md),
[C défaillances](2026-09-08-refonte-dashboard-C-defaillances.md)).
Chaque claim factuel vérifié contre le code. STATUT : recommandation —
l'arbitrage final appartient à Jackson et Fable. Aucune ligne de code avant.*

## 1. Vérification factuelle

18 claims vérifiés — **aucun FAUX**. Les trois agents ont lu le code
correctement ; le désaccord est architectural, pas factuel. Sélection :

| Claim | Verdict | Preuve |
|---|---|---|
| dashboard.js:2134 fallback `cgBackend && cgBackend.action ? ... : action` | VRAI | mot pour mot |
| reconcileFavorWithMtf inverse le sens | VRAI | l.1838-1840 : `favor === "SHORT" && mtfBulls >= 3 → overrideFavor = "LONG"` |
| dashboard_mirror.py = 15e cerveau (B seul l'a vu) | VRAI | 967 lignes exactement ; docstring l.6 « reproduit build_conseil_global » |
| Composante V MTF identique 4 TF | VRAI | readers.py l.1081-1087 (VWAP jour + close courant, `/60` en dur) |
| Branche cvd supprimable ~20 l. | VRAI | regime_engine.py l.160-176 |
| deploy.sh l.64 copie min.js ; index.html charge dashboard.js?v=171 | VRAI | min.js = 138 315 octets, daté 11/04 |
| Override cohérence dupliqué builders l.259-266 vs regime_engine l.454-460 | VRAI | ligne pour ligne |
| Rustine deux-dicts ES app.py l.1326-1332 | VRAI | carte JS lit `response["es"]["regime"]` = le BRUT ; NQ lit le stabilisé |
| Fuite order_flow_advanced au tier STARTER | VRAI | tier_filter.py l.40-47 retire `order_flow` mais pas `order_flow_advanced` |
| B compte l.1082-1146 en « supprimé » alors qu'il les déclare absorbées | PARTIEL | son −820 net recalculé honnêtement ≈ −740 |

## 2. Verdict par proposition

**A — contrat d'abord.** Force : le seul séquencement épistémologiquement
propre (parité 100 % prouvée AVANT tout changement de comportement — la règle
« mesurer avant d'annoncer » du dépôt). Faiblesses : le beacon télémétrique
met tout le plan derrière son composant le plus fragile ; le « noyau immuable
versionné » est du cérémonial inter-équipes pour un repo unique ; état final
plus gros que B sans gain de sûreté. **Over-engineering : beacon + endpoint
télémétrie ; versionnement complet.**

**B — moteur unique.** Forces : le meilleur état d'arrivée (deux fichiers qui
décident), le seul à avoir vu dashboard_mirror.py, le seul à citer le
précédent gamma_veto_engine/incident #74 (LA jurisprudence du dépôt pour ce
problème exact), le meilleur premier geste (tuer les inverseurs JS — 30
lignes, danger pur). Faiblesses : shadow avec fixes intégrés = expérience
confondue (bug de restructuration indistinguable d'un fix voulu) ; réécriture
du score MTF 50/50 = recalibration à poids inventés, violation de
`feedback_calibration_par_instrument`, ET elle changerait le comportement du
véto 4/4 — la seule chose MESURÉE (08/09) ; suppression de PRUDENT casse
silencieusement les bots (§4.3) ; 27 h sous-budgété.

**C — défaillances d'abord.** Forces : la meilleure Phase 0 (canari de logs,
readers fail-closed — vérifié : `readers.py:121` fait bien `get_field(...,
0.0)` sur le VIX ; le SEUL à avoir vu le double fetch MTF : route
`/api/mtf/{symbol}` app.py:917 + fetch JS l.1814 alors que le payload porte
déjà `mtf_es`) ; description de l'asymétrie ES la plus précise. Faiblesses :
la « porte de confirmation » k-signaux recompte des entrées déjà votées par
`_compute_bias_proxy` (delta, range_pos, DIV) — le second cerveau sous un nom
neuf, exactement le montage des « trois horloges » ; Playwright disproportionné ;
triptyque version/hash/empreinte = trois mécanismes pour un défaut.

## 3. Les 7 désaccords tranchés

1. **Emplacement moteur → `CORE/verdict.py` (B).** Précédent gamma_veto_engine
   (incident #74) : extrait de builders vers CORE comme SSoT dashboard +
   sierra_pipeline + Bot 1 v2. dashboard_mirror réplique le conseil PARCE QUE
   la logique est enfermée dans DASHBOARD/. Sens de dépendance du repo :
   DASHBOARD → CORE, jamais l'inverse. Condition : zone_info + _niveaux_cles
   migrent avec.
2. **Vocabulaire → A pendant la migration, nettoyage B en toute fin, couplé
   aux bots.** `"PRUDENT" in action` dérive `min_confidence_required = 0.40`
   dans LES DEUX bots (mia_paper_trader l.1764/2877, mia2_brain l.1453/2812) :
   supprimer le littéral change un seuil d'entrée en silence. La projection
   émet les 7 littéraux + bull_points/bear_points à l'identique.
3. **Beacon → REJETÉ.** Watchdog (écran figé) + empreinte deploy (min.js) +
   suppression du code de recalcul + lint no-decision-in-JS (divergence) : le
   défaut devient structurellement impossible ; le test de parité sur fixtures
   dans la CI EXISTANTE (.github/workflows/) couvre le rendu. Le beacon =
   surface permanente pour un défaut déjà rendu impossible.
4. **Comptage 6-signaux → suppression pure (B).** La porte de confirmation de
   C confirme une direction par les entrées qui l'ont produite — pas des
   signaux indépendants. Le changement de distribution se mesure au shadow.
5. **MTF → A et C.** Pas de réécriture du score (scope creep + poids non
   mesurés + change le comportement du véto validé). Cible : supprimer le
   boost `_enrich_regime_with_mtf` (convergence des trois, diff rejoué
   d'abord), véto conservé tel que mesuré, flag `degrade=true`, recalibration
   = chantier séparé.
6. **Séquencement → A pour la discipline, outillage shadow de B, en DEUX
   temps.** (1) Shadow ISO-comportement, parité 100 % exigée (tout diff = bug
   de restructuration). (2) Corrections UNE PAR UNE, chacune avec rejeu
   chiffré ES+NQ présenté à Jackson avant activation. Chaque diff a UNE cause.
7. **LOC → chiffres honnêtes mais périmètres différents.** B recalculé ≈ −740
   (recomptait la state machine absorbée). A exact pour son périmètre (garde
   plus de choses en vie + 80 l. de beacon). L'état final de B est réellement
   ~450 lignes plus petit — il gagne sur le critère du dépôt.

## 4. Ce que les trois ont raté (trouvailles du juge)

1. **`.github/workflows/deploy-dashboard.yml` — le deuxième chemin de deploy,
   LE POINT LE PLUS DANGEREUX.** Tout push master touchant `DASHBOARD/**`
   copie le dossier ENTIER sur le VPS (`overwrite: true`, min.js compris) et
   redémarre via `taskkill` + `pythonw start_dashboard.py` — en contradiction
   avec la règle nssm (« ne plus lancer python directement »). Il contournerait
   l'empreinte de C et les fenêtres hors séance des trois plans (un merge à
   15h Paris déploie en pleine séance). Dormant AUJOURD'HUI (master n'est pas
   poussé — webhooks), mais mine armée le jour où les push reprennent. À
   neutraliser/aligner en Phase 0.
2. **`CORE/databento_paper_trader.py` — un 16e cerveau** (docstring :
   « REPRODUIRE rules dashboard (build_conseil_global) »). Statut actif/dormant
   à vérifier sur le VPS avant purge (`feedback_dormant_module_verify_active_path`).
3. **bull_points/bear_points consommés au-delà de l'affichage** (bots : log
   GATE_CONSEIL_EXEC_RESCUED ; JS l.2135-2136) — omis de la projection de B.
4. **Suppression de `_stabilize_qui` sans remplaçant → carte « QUI A LA
   MAIN » scintillante** (3 lignes de spec d'hystérésis à écrire).
5. **Tier FREE expose aussi `regime.bias`** (tier_filter.py:74-80) — le fix
   « FREE = action protégée » doit rebrancher ce teaser aussi.
6. **`DASHBOARD/BACKUP/`** : deux répertoires de copies complètes d'avril, en
   plus des 4 `.bak` — même classe de dette que min.js.
7. Vérifiés sains : ticker-widget.js, briefing.py, V3/.

## 5. RECOMMANDATION D'ASSEMBLAGE

**Colonne vertébrale B** (état final : deux fichiers qui décident,
`regime_engine.py` + `CORE/verdict.py`) — **disciplinée par le séquencement
de A** (identité prouvée avant tout changement de comportement) — **équipée
des filets de C** (watchdog écran, readers null-jamais-0, canari de logs, UN
contrôle d'empreinte via `js_sha` dans /api/health, source MTF unique,
assertion workers=1).

**Rejeté définitivement** : beacon + endpoint télémétrie (A) ; noyau immuable
versionné (A — `"schema": "verdict.v1"` + PANNE si inconnu suffit) ; porte de
confirmation k-signaux (C) ; réécriture du score MTF (B) ; Playwright (C) ;
délais GO indexés sur le beacon (A).

**Séquencement final** :

| Phase | Contenu | Effort |
|---|---|---|
| 0 | Hygiène deploy : min.js hors deploy.sh ET du repo ; **neutraliser/aligner deploy-dashboard.yml sur nssm** ; purge 4 .bak + BACKUP/ ; canari de logs ; harnais fixtures de parité en CI. Zéro changement de comportement. | ~5 h |
| 1 | Étape 1 de B : suppression reconcileFavorWithMtf + override conseils l.1710-1726 + seuils 70/30 + VIX « calme » ; watchdog écran. Retrait de FAUX, annoncé. | ~3 h |
| 2 | `CORE/verdict.py` en re-packaging PUR (zone_info/_niveaux_cles migrés), shadow par flag env, **parité 100 %** exigée. | ~10 h + 3 séances |
| 3 | Corrections UNE PAR UNE dans le shadow (cvd ; boost _enrich ; _stabilize_favor → hystérésis par barre ; comptage), chacune : rejeu chiffré ES+NQ arbitré AVANT activation. | ~8 h + 2 séances/correctif |
| 4 | Bascule flag on ; JS afficheur pur + lint no-decision-in-JS ; bots sur projection inchangée ; tier au contrat (bias FREE compris). | ~6 h |
| 5 | Coupe physique après 5 séances stables (littéraux PRUDENT couplés à la mise à jour des bots) ; sort de dashboard_mirror + databento_paper_trader v1. | ~4 h |

**Effort honnête : ~36-40 h de dev sur 5-7 semaines calendaires.** État
final : ~−700 LOC de runtime, deux fichiers qui décident, un écran qui ne
peut plus mentir que par panne — et qui le dit.
