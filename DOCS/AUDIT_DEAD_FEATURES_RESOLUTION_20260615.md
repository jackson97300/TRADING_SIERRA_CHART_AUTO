# AUDIT DEAD FEATURES — RESOLUTION 15/06/2026

**Auteur** : Claude orchestrateur + agents specialises
**Date** : 2026-06-15 (afternoon session)
**Trigger** : audit DEAD features sierra_enriched 613 fields post-migration Bot 1
**Reference baseline** : `DOCS/AUDIT_DEAD_FEATURES_20260615.md` + `DATA/_AUDIT/BASELINE_20260615/`

---

## 1. RESULTATS HEADLINE

| Sample | Baseline | Post-fix | Delta DEAD |
|---|---|---|---|
| **NQ 4j** (15169 bars baseline / 16746 post) | DEAD=157 ALIVE=474 | DEAD=143 ALIVE=488 | **-14** ✅ |
| **ES 5j** (11762 bars baseline / 13338 post) | DEAD=160 ALIVE=471 | DEAD=149 ALIVE=482 | **-11** ✅ |

25 features ressuscitees cross-instrument apres 3 fixes deployes.

---

## 2. SPRINTS EXECUTES (3 bugs deployes prod)

### Bug #1 — cvd_day_dir bias bull permanent NQ (INCIDENT #59)

| Etape | Resultat |
|---|---|
| Diagnostic | sg18 FPBS = "Cumulative Sum - ALL" pas reset session |
| Fix | `CORE/cvd_session_override.py` (Python override + hook enricher_chain) |
| Tests | 15/15 pytest (incl. DST winter zoneinfo) |
| Replay 4j NQ | 100% +1 → 92.1% +1 / 7.9% -1 |
| Replay 5j ES | 94% +1 → 85% +1 / 15% -1 |
| Reviews | code-reviewer GO + ml-trainer GO (V4 MDA=0) |
| Commit | `905bbd9` |
| Deploy VPS | 12:16 ET, MIA-Sierra-Enricher-ES restart |
| Live confirme | ES `cvd_day_dir=-1` (vs +1 constant avant) ✅ |

### Bug #2 — delta_div_*_clean MIN_DELTA_SLOPE 100->8 (INCIDENT #57)

| Etape | Resultat |
|---|---|
| Diagnostic | Phase 2.2 migre CUMMAX → SLOPE, seuil 100 legacy = impossible |
| Distribution slope | p99 = 54.2 NQ / 86 ES (vs seuil 100) |
| Calibration | Seuil 8.0 → fire rate clean/raw 18.1% NQ / 29.9% ES (target 5-40%) |
| Fix | `CORE/divergences_v2.py:162` + 2 tests pytest (sentinel + guaranteed div) |
| Replay 4j NQ | clean buy 0.04% → 3.40% (+85×) ; sell 0.00% → 4.05% |
| Replay 5j ES | clean buy 0.12% → 5.76% (+48×) ; sell 0.14% → 6.97% |
| Reviews | code-reviewer GO-AVEC-RESERVES (R1 fixe) + ml-trainer GO (V4 pas affecte MDA=0) |
| Commit | `a049f36` |
| Deploy VPS | 12:36 ET, MIA-Sierra-Enricher-ES restart |
| Live confirme | Pipeline cohérent, distribution attendue sur fenetre 7-13% |
| Post-fix DEAD filter | `delta_div_buy_clean` DEAD → ALIVE NQ + ES ✅ |

### Bug #3 — composite_poc cross-day reset destructeur (INCIDENT #58)

| Etape | Resultat |
|---|---|
| Diagnostic | `sierra_pipeline.py:1310` reinstanciait `MarketProfileAdvancedState()` complet → ecrasait daily_vpocs_5d/20d rolling |
| Fix A | Reset selectif sweep+judas, PRESERVE composite_poc |
| Fix B (pickle persistance) | BACKLOG accepte par code-reviewer (scope creep) |
| Tests | 18/18 pytest (+2 preserves + destructive_reset doc + 1 E2E pipeline) |
| Replay 4 jours seq NQ | daily_vpocs_5d accumule [29196.5, 29907.0] vs vide bug |
| Reviews | code-reviewer GO-AVEC-RESERVES (R1+R2 fixes appliques → GO sec) |
| Commit | `0c4acd6` |
| Deploy VPS | 12:51 ET, MIA-Sierra-Enricher-ES restart |
| Live confirme | composite_poc_5d/20d NULL au J+0 (normal — attente J+1 cross-day archive) |

### Bug #7 — Cleanup commentaire trompeur (INCIDENT #60)

| Etape | Resultat |
|---|---|
| Diagnostic | `run_sierra_enricher.py:171-186` promet re-injection inexistante |
| Cleanup | Commentaire reecrit : DROP DEFINITIF (14 features) vs BACKLOG (2 features dist_blind_*) |
| Documentation | `INVENTAIRE_DUMPER_VS_BOT.md` annexe + `IDEAS_BACKLOG.md` 3 entries |
| Commit | `46792e3` |
| Deploy | Pas requis (documentation only) |

---

## 3. BUGS REPORTES EN BACKLOG (sprint dedie ulterieur)

| Bug | Effort | Statut | Raison |
|---|---|---|---|
| **#4 dist_blind_*** | 1-2h dev | PROPOSED IDEAS_BACKLOG | Sprint dedie (1-2h + review). Consumers prod actifs (BN V5 + Bot 3 Gold) mais pas live trading critique |
| **#5 dist_color_*_pct** | 5 min config GUI | WAITING_JACKSON | Action manuelle Sierra Chart, post-session uniquement |
| **#6 bool_va_confluence** | 1 ligne C++ | BACKLOG_MINOR | Impact prod NUL (deja drop ML), fix decoratif |

---

## 4. VRAIS BUGS RESOLUS — Cascade impact

### Bot 1 paper Sim2 (PROD ACTIVE)

**AVANT fixes** :
- bias_calculator score_bull NQ recevait +PTS_CVD=0.25 a 100% des bars (cvd_dir=+1 constant)
- flag delta_cvd_divergence detectait toujours quand delta_day_dir=-1 (bruit constant)
- compute_bias() biaise bull NQ permanent → recommendations LONG saturees (cf commentaire incident "NQ LONG drift -$2010 sur 7 trades 100% LONG")

**APRES fixes** :
- cvd_day_dir distribution NQ 92/8 (haussier marche + naturel) au lieu de 100/0 (bug)
- delta_cvd_divergence detecte vraie divergence intra-bar vs cumul session
- compute_bias() peut maintenant produire score_bear NQ sur 8% des bars
- delta_div_*_clean reflechi en composite delta_divergence_clean cleaner

### Modeles V4 (LightGBM)

**Impact** : NUL (verification ml-trainer agent — importance.csv montre MDA=0 sur features delta_div_*_clean dans 4 modeles `v4_pure_20260524/`). Pas de retraining requis.

### Bots Bot 2/3/4 paper

**Impact** : neutre (consumers cvd_day_dir et delta_div_*_clean limites a research/audits)

---

## 5. PATTERNS IDENTIFIES — INCIDENT_LOG entries

| INCIDENT | Pattern | Statut |
|---|---|---|
| **#57** delta_div_*_clean | VALIDATION_MISS (RESOLUTION #52 prematuree) | RESOLU + deploye |
| **#58** composite_poc | COMMENT_FALSE + VALIDATION_MISS | RESOLU + deploye |
| **#59** cvd_day_dir | VALIDATION_MISS (feature non monitoree) | RESOLU + deploye |
| **#60** dist_blind re-injection | VALIDATION_MISS (commentaire vœu pieux) | RESOLU (cleanup commentaire) + BACKLOG fix code |

**4 occurrences VALIDATION_MISS cette session = renforce memory `feedback_validation_miss_pre_deploy.md`** (deja 8+ occurrences cumulees depuis 27/04).

---

## 6. SUIVI POST-DEPLOY (J+1, J+5, J+30)

| Date | Verification |
|---|---|
| **J+0 (15/06)** | ✅ Live confirme : ES cvd_day_dir=-1, pas de crash enricher, dist_blind cleanup OK |
| **J+1 (16/06)** | Distribution cvd_day_dir NQ apres 24h post-fix (target : > 5% bars -1) + composite_poc_5d non-NULL (1ere archive cross-day) + delta_div_*_clean fire rate 7-13% confirme |
| **J+5 (20/06)** | composite_poc.daily_vpocs_5d count = 4-5 (rolling 5d filled) |
| **J+30 (15/07)** | Audit complete : run feature_catalog_v5 + dead_filter sur nouveau sample 30j, comparer baseline → re-evaluer Bug #4 fix priorite (si BN V5 paper degrade visible) |

---

## 7. METRIQUES SUCCESS — verification J+1

| Bug | Metrique cible J+1 | Action si fail |
|---|---|---|
| #1 cvd_day_dir | NQ distribution +1/-1 ≥ 80/15% sur 16:00 ET → 16:00 ET du jour suivant | Investiguer override pipeline non execute |
| #2 delta_div_*_clean | NQ fire rate clean / raw ≥ 5% sur 24h post-fix | Recalibrer MIN_DELTA_SLOPE |
| #3 composite_poc | composite_poc_5d non-NULL ≥ 50% bars apres 17:00 ET 16/06 (cross-day J+1 effectue) | Investiguer logique cross-day |

---

## 8. PROGRESSION (avant / apres)

```
AVANT session (16:00 ET) :
  613 features sierra_enriched -> 25% DEAD (157 NQ, 160 ES)
  4 bugs critiques pollutent moteur decision Bot 1 (cvd, delta_div, composite_poc)
  Bug 1 commentaires trompeurs commit obfuscation
  
APRES session (17:00 ET) :
  613 features sierra_enriched -> 22.5% DEAD (143 NQ, 149 ES) — 25 features ressuscitees
  3 bugs critiques deployes (cvd, delta_div, composite_poc J+1)
  3 bugs reportes proprement IDEAS_BACKLOG (dist_blind, dist_color, bool_va_confluence)
  4 INCIDENT_LOG entries documentees
  5 commits sur branche feat/sierra-full-migration
  Pattern VALIDATION_MISS x4 renforce mémoires
```

---

## 9. COMMITS DEPLOYES

```
46792e3 docs(cleanup): commentaire trompeur run_sierra_enricher + backlog Bug #4/#5/#6
0c4acd6 fix(pipeline): composite_poc cross-day reset destructeur (INCIDENT #58)
a049f36 fix(divergences): recalibrer MIN_DELTA_SLOPE 100 -> 8 (INCIDENT #57)
905bbd9 fix(enricher): cvd_day_dir bias bull permanent NQ (INCIDENT #59)
eaad888 fix(dashboard): rollover ES/NQ M26->U26 + None-guard banner stabilize
a201b15 feat(bot1): migrate _read_last_jsonl_bar to sierra_enriched (Databento fallback)
cd695b9 fix(pipeline): phase_b_helpers `==` strict mins_int -> `>=` (BUG RACINE open_type=0)
```

---

## 10. FILES GENERES CETTE SESSION

| Fichier | Type |
|---|---|
| `DOCS/AUDIT_DEAD_FEATURES_20260615.md` | Rapport baseline |
| `DOCS/AUDIT_DEAD_FEATURES_RESOLUTION_20260615.md` | Ce rapport (bilan resolution) |
| `DATA/_AUDIT/BASELINE_20260615/` | 4 fichiers reference baseline |
| `DATA/_AUDIT/POST_FIXES_20260615/` | 2 fichiers comparaison post-fix |
| `CORE/cvd_session_override.py` | Module fix #1 |
| `CORE/divergences_v2.py` (modif) | Fix #2 recalibration |
| `CORE/sierra_pipeline.py` (modif) | Fix #3 cross-day preserve |
| `CORE/log_catalog.py` (modif) | Entry CVD_OVERRIDE_FAIL |
| `CORE/enricher_chain.py` (modif) | Hook override |
| `BOT/run_sierra_enricher.py` (modif) | Cleanup commentaire |
| `tests/sierra_port/test_cvd_session_override.py` | 15 tests |
| `tests/sierra_port/test_sierra_pipeline_cross_day_reset.py` | 4 tests (1 skip importorskip) |
| `tests/sierra_port/test_market_profile_advanced.py` (modif) | +2 tests preserves |
| `tests/test_divergences_v2.py` (modif) | +2 tests sentinel + guaranteed |
| `DOCS/INCIDENT_LOG.md` (modif) | 4 nouveaux incidents #57-#60 |
| `DOCS/BOT_CHANGELOG.md` (modif) | 3 entries fixes |
| `DOCS/INVENTAIRE_DUMPER_VS_BOT.md` (modif) | Annexe 15/06 |
| `DOCS/IDEAS_BACKLOG.md` (modif) | 3 entries Bug #4/#5/#6 |
