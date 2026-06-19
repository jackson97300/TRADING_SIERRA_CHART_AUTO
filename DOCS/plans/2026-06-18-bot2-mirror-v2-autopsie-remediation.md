# Bot 2 "Mirror v2" (Sim2) — Autopsie + plan de remédiation

**Date** : 2026-06-18
**Module** : `CORE/bot1_v2/` (affiché "Bot 2 Mirror v2" dashboard, compte Sim2, service VPS `MIA-Paper-Bot1V2`)
**Statut** : DIAGNOSTIC FAIT — remédiation en phases, non démarrée
**Méthode** : autopsie empirique Claude (logs VPS 15→18/06, 9544 évaluations) croisée avec 3 agents
spécialisés (code-reviewer, trading-strategy-analyst, market-analyst). Convergence totale.

---

## 0bis. DIRECTIVE Jackson 18/06 — phase COLLECTE (pas de limites de fréquence)

**Objectif actuel = collecter un maximum de trades paper exploitables**, pas optimiser la consistance.
- `MAX_TRADES_PER_DAY` → off (9999)
- `DAILY_STOP_LOSS_USD` → **-2000** / `DAILY_STOP_WIN_USD` → **+2000** (garde-fou catastrophe seulement, quasi-off)
- Override ASSUMÉ de la mémoire SOUVERAINE `feedback_douglas_consistency_principles` (stop -200/+150,
  max 5) : Douglas = discipline LIVE/consistance ; ici = collecte PAPER. À ré-armer si passage live.

**RÉSERVE DURE** : "pas de limite de fréquence" n'autorise PAS à relâcher les gates QUALITÉ/DIRECTION.
Ouvrir les vannes AVANT de fixer D-2 (near_level S/R) = collecter des trades "short dans le trou" =
dataset empoisonné. L'ordre des phases (sécuriser D-2/D-1 PUIS ouvrir) reste impératif.
Conséquence : la cible "2-5 trades/j" de la Phase 5 est REMPLACÉE par "max trades, mais dirigés correctement".

## 1. Symptôme

**2 trades réels en 4 jours** (15→18/06). Les 2 = ES SHORT, 7/7 étoiles, RR 1.5, mur CUR_VAH.

Funnel empirique (logs `LOGS/decisions/decisions_*_bot1v2.jsonl`, n=9544) :

| Étape | n | % |
|---|---|---|
| Évaluations totales | 9544 | 100% |
| Bloquées session (Asia 2014 + London 1227 + EOD/pre-RTH) | 3437 | 36% |
| Verdict = ATTENDRE (jamais 4/0 directionnel propre) | 5473 | 57% |
| Direction obtenue → tuées par cascade 7★ | 523 | 5,5% |
| Vetos (climax 37 / rvol 16) | 43 | 0,5% |
| 7★/7 atteint | 12 | 0,13% |
| **Trades envoyés** | **2** | **0,02%** |

Étoiles tueuses (parmi 523) : `NOT_AT_LEVEL` 429×, `RVOL_LOW` 425×, `MTF_CONFLICT` 192×,
`BAR_NOT_CONFIRMED` 95×, `MOMENTUM_WEAK` 57× (se cumulent).

---

## 2. Cause racine — 4 problèmes empilés

### P-A : Pattern 11 V1 (cascade ET) — sous-trading
Chaîne ET de 13 conditions : verdict-mère (4/0) × 4 vetos × 7 étoiles **toutes obligatoires**
(`dashboard_mirror.py:785` `ready = no_veto AND stars_count == stars_total`).
91,6% des directions tuées par la cascade. Probabilité jointe < 0,1%.
Double comptage : bias (verdict-mère + étoile) et MTF (verdict-mère + étoile).

### P-B : Verdict-mère 4/0 inatteignable
`_compute_dashboard_action` exige `bull_pts==4 AND bear_pts==0`. Or `cvd_day_dir`, `delta_day_dir`,
`vwap_d_side` se contredisent ~47% du temps (ES : (-1,1,1)=765, (1,1,-1)=674). De plus
`DASHBOARD_VERDICTS_ACCEPTED=("ACHAT","VENTE")` exclut les "PRUDENT" → 81 verdicts directionnels jetés.

### P-C : Le "Mirror" ne miroir RIEN (ghost features)
Les barres `sierra_enriched` ne contiennent PAS `conseil_action`, `bull_pts`, `mtf_bulls`,
`bias_score`, `gamma_block_long/short` (vérifié sur barre réelle). Le bot tourne à 100% sur ses
calculs DÉRIVÉS — réimplémentation parallèle et divergente de `DASHBOARD/api/builders.py:build_conseil_global`.
**Conséquence sécurité** : les 2 vetos gamma (présentés comme root-cause du -$967) sont MORTS
(`_as_bool(None)=False` → jamais armés). Faux sentiment de protection.

### P-D : Seuils non alignés sur les distributions réelles
Mesures empiriques (ES 3083 + NQ 4667 barres RTH) :
- `RVOL_MIN=1.3` → passe 18-19% (médiane rvol 0,89). À 1.1 → ~30%.
- `NEAR_LEVEL_MAX_TICKS` ES=4t → 35% ; NQ=8t → **13%** (médiane nearest NQ = 38t ; 8t ≈ 2t-ES).
- `BIAS_SCORE_MIN_ABS=0.5` tue tous les 2/3-alignés (bias ∈ {±0.33, ±1.0}).
- `MOMENTUM_5B_MIN_ABS=2.0` : échelle ES (médiane 2,5) ≠ NQ (médiane 19) → trivial sur NQ (94,5%).

---

## 3. Découvertes DANGEREUSES (priorité avant tout relâchage)

### D-1 : `cvd_day_dir` figé à `1` sur NQ — ❌ FAUX POSITIF (autopsie sur données périmées)
**RÉSOLU / NON-BUG (vérifié 18/06).** Le market-analyst a conclu "NQ figé +1, ne peut jamais
shorter" en analysant les fichiers locaux 10-15/06 = **PRÉ-FIX**. L'override `CORE/cvd_session_override.py`
(déployé 15/06, INCIDENT_LOG #59) recalcule cvd_day depuis delta_bar cumulé par session.
Vérification VPS post-fix : NQ `cvd_day_dir` = [1] le 15, **[-1,1] le 16, [-1,0,1] le 17, [-1] le 18**.
La feature fonctionne. Aucun code Phase 1b nécessaire. Leçon : vérifier fraîcheur data vs date de
deploy AVANT de diagnostiquer un bug pipeline (INCIDENT_LOG #66).
Résidu mineur (non bloquant) : léger carryover de baseline aux frontières de session (jour N+1 first
≈ jour N last) — à vérifier un jour, n'empêche pas cvd_day_dir de flipper.

### D-2 : `_check_quality_near_level` géométrique sans support/résistance
Valide un SHORT à **3t du plus bas de session** (`dist_sess_low=3t`) ou un SHORT à 565t de la VAH
qui passe via `dist_ib_low=1t` (shorter sur le support). Relâcher near_level SANS fixer ça =
multiplier les trades "dans le trou". Opposé de la souveraineté "zones où intervenir".

---

## 4. Bugs de fiabilité / traçabilité (code-reviewer)

| ID | Type | Détail | Fichier |
|---|---|---|---|
| F-1 | VALIDATION_MISS | `direction="?"` sur 88% des logs NOT_TRADABLE (direction connue dans mirror) | `main.py:274`, `cluster.py:108` |
| F-2 | VALIDATION_MISS | JSONL dédié `LOGS/bot1_v2_decisions/` absent sur VPS → tuning aveugle | `logger.py:42`, `main.py` |
| F-3 | COMMENT_FALSE | cooldown `register_close()` jamais appelé ; commentaire `main.py:119` faux ; protection anti-revenge inerte | `main.py:149`, `cluster.py:171` |
| F-4 | DEAD_CODE | anti-clustering spatial (`set_last_entry_price`...) écrit mais jamais branché | `state/position_store.py:137` |
| F-5 | RÉSOLU | divergence sessions Asia/London (déjà fixée commit 77e7649, 17/06) | `gates/session.py:100` |
| F-6 | MINOR | `strength_ok` dead code ; `RR=1.5` sans backtest ; `stars_total` 5 vs 7 incohérent | `dashboard_mirror.py` |

---

## 4bis. Angles morts du plan — control review (18/06, 2e passe)

Trouvés en re-contrôlant le plan (mon 1er jet ne les avait PAS relevés) :

| ID | Gravité | Problème | Preuve |
|---|---|---|---|
| G-1 | **HAUTE (safety)** | Compteurs daily (`n_trades_today`, `cumul_pnl_usd`) NON persistés. Restart → reset 0 → DAILY_STOP_LOSS/WIN/MAX_TRADES sautent. | `position_store.py` ne sérialise pas daily_gate ; `daily_limits.py:39` init à 0. Cf `project_4bots_persistance_chantier` (~$1700 perdu) |
| G-2 | **HAUTE (strategie)** | ZÉRO backtest de l'edge "mirror". Deployé paper sans validation qu'une combinaison a un edge (contrairement à BN V4 avec PF). La recalibration peut produire 2-5 trades/j… perdants. | aucun backtest cité ; RR 1.5 "empirique" non chiffré |
| G-3 | MOYENNE | Paradoxe preservation : Phase 5 "préserver les 2 wins" MAIS market-analyst montre que 4/8 setups ready_to_arm = mauvais (short dans le trou). Préserver = figer la logique near_level défaillante. | analyse market-analyst des 8 ready_to_arm |
| G-4 | MOYENNE | Phase 3 Option A (injecter dashboard dans enricher) impacte TOUS les bots (Bot 1/3/4 consomment sierra_enriched), pas juste Bot 2. | cross-cutting ; review schema-auditor + régression multi-bots requise |
| G-5 | BASSE | SL walls partiellement morts : `swing_high/low`, `ext_edge_sell_price` ABSENTS des barres → Tier1 EXT_EDGE + Tier2 SWING inertes (fallback sur cur_vah/vwap_sd/pdh/sess OK). | probe barre réelle 15/06 |
| G-6 | BASSE | EOD/RTH lockout calcule en UTC-4 toute l'année (`session.py:36`) → faux d'1h en hiver (EST UTC-5). | commentaire code admet la simplification |

**Conséquence sur l'ordre** : G-1 (persistance daily) rejoint la Phase 1 (sécurité). G-2 (backtest edge)
devient une **Phase 4bis bloquante** avant tout passage live. G-3 corrige le critère de preservation Phase 5.

## 5. Plan de remédiation — PHASES (l'ordre est volontaire)

**Principe** : sécuriser et rendre traçable AVANT de relâcher. Relâcher d'abord = amplifier D-2.
Toute phase touchant le moteur de décision = tâche critique (`critical-tasks-review.md` critère 1) :
review agent + test empirique + preservation des 2 wins existants AVANT deploy.

### Phase 1 — Sécuriser le dangereux
- [ ] D-2 : ajouter logique support/résistance dans `_check_quality_near_level` (LONG → niveau au-dessus
  = résistance interdite proche / support proche OK ; SHORT symétrique). Définir la sémantique exacte
  par direction.
- [ ] D-1 : investiguer `cvd_day_dir` NQ figé (enricher_chain / pipeline). Tant que non corrigé,
  NQ pilote à moitié aveugle.

### Phase 2 — Traçabilité (prérequis du tuning data-driven)
- [ ] F-1 : propager `mirror.direction` dans tous les logs de rejet.
- [ ] F-2 : vérifier version `main.py` déployée VPS + `MIA_LOG_DIR` du service ; emit `BOT1V2_DECISIONS_PATH`
  au boot ; confirmer écriture réelle J+1. Documenter en INCIDENT_LOG (fait, voir §6).

### Phase 3 — Décider du "Mirror"
- [ ] P-C Option A (propre) : injecter les vrais champs dashboard dans `sierra_enriched`
  (appeler `build_conseil_global` côté producteur) → vrai mirror + réactive gamma vetos. Review `schema-auditor`.
- [ ] OU Option B (minimal) : assumer le mode dérivé, renommer la doc (≠ "mirror"), rebrancher gamma
  sur `mq_gamma_condition`/`next_wall_dist_ticks` ou retirer honnêtement les vetos morts.

### Phase 4 — Recalibration (SEULEMENT après 1-3)
- [ ] P-A : cascade 7★ → score pondéré. Proposition : **2 CORE obligatoires (near_level + bias cohérent)
  + 5 bonus**, armement si `2 core OK AND somme_bonus >= seuil`. Tunable via env var `BOT1V2_MIN_STARS`.
- [ ] P-B : verdict-mère = score directionnel (`dir_score = bull_pts - bear_pts >= 2 AND bear_pts <= 1`),
  accepter les PRUDENT pondérés.
- [ ] Résoudre tension momentum/pullback : `max(score_continuation, score_reversion)` (substituables, pas cumulatifs).
- [ ] P-D : seuils de départ chiffrés ci-dessous.
- [ ] F-3/F-4/F-6 : armer cooldown, brancher ou retirer anti-clustering, nettoyer dead code.

#### Seuils de départ proposés (à valider par re-replay)

| Paramètre | Actuel | Proposé | Source |
|---|---|---|---|
| `RVOL_MIN` | 1.3 | **1.1** | médiane 0,89 ; 1.1 → ~30% |
| `NEAR_LEVEL_MAX_TICKS_ES` | 4 | **8** | médiane nearest 7,9t |
| `NEAR_LEVEL_MAX_TICKS_NQ` | 8 | **16** | médiane nearest 38t |
| `BIAS_SCORE_MIN_ABS` | 0.5 | **0.33** | bias ∈ {±0.33, ±1.0} |
| `MOMENTUM_5B_MIN_ABS` ES | 2.0 | 2.0 | ok |
| `MOMENTUM_5B_MIN_ABS` NQ | 2.0 | **~12 ou ATR-norm** | médiane \|m5\| NQ = 19 |
| étoiles | 7/7 ET | **score 2 core + bonus** | Pattern 11 |
| `DASHBOARD_VERDICTS_ACCEPTED` | ACHAT,VENTE | +PRUDENT pondéré | 81 verdicts jetés |

### Phase 5 — Validation avant deploy (obligatoire)
- [ ] Re-rejouer les 4j logs + enriched avec nouvelle config → viser **2-5 trades/jour de qualité**
  (ni paralysie, ni trade-à-tout-va).
- [ ] Preservation : les 2 trades ES SHORT 7/7 restent valides.
- [ ] backtest-runner/ml-trainer : N>=100 simulés + costs avant tout passage live (DSR non calculable si N<100).
- [ ] pytest `CORE/bot1_v2/tests/` verts.
- [ ] entry BOT_CHANGELOG complétée + review agent par phase.

---

## 6. Garde-fous & souveraineté Jackson

- "On doit avoir des zones où intervenir, on ne doit pas trader à tout-va" → near_level + bias cohérent
  restent des **gates durs** (CORE). On déplace seulement les confirmations secondaires en score.
- "Des trades de qualité doivent passer" → le score N/7 débloque les signaux qui ratent 1-2 confirmations.
- **NE PAS** commencer par les seuils (amplifie D-2). **NE PAS** passer live tant que N<100 simulés.

## 7. Liens
- INCIDENT_LOG : entrées 2026-06-18 (VALIDATION_MISS F-1/F-2, COMMENT_FALSE F-3)
- BOT_CHANGELOG : entry 2026-06-18 Bot 2 remédiation (PLANNED)
- Logs autopsie : `TMP_BOT2_AUTOPSY/decisions_*_bot1v2.jsonl` (à purger du repo après intégration)
- Mémoires : `feedback_ia_traps_detection` (pattern 11), `feedback_data_mining_trap`,
  `feedback_cross_instrument_bonus_not_gate`, `project_bots_architecture_20260529`
- Reviews agents : code-reviewer (a3c3e2d412bb6603f), trading-strategy-analyst (aeb406341782ab530),
  market-analyst (a33a1135cd0ad96a1)

---

## 8. PHASE 4 — Plan détaillé (cascade 7★ → score pondéré) [étape 1 validée 18/06]

**Principe** : verdict directionnel souple → 4 vetos hard (inchangés) → 2 CORE obligatoires
+ 5 bonus pondérés. Supprime les double-comptages bias×2 et MTF×2.
**Fichiers** : `CORE/bot1_v2/dashboard_mirror.py` (compute_verdict) + `config.py`. Bot 2 only.
**Prérequis acquis** : near_level S/R + vwap_d gate (déployés), cvd_day/delta_day corrects (fix #73)
→ inputs bias fiables.

### 4b — Verdict-mère = score directionnel
- `dir_score = bull_pts − bear_pts` ; LONG si `dir_score>=+2 ET bear_pts<=1` ;
  SHORT si `dir_score<=−2 ET bull_pts<=1` ; sinon ATTENDRE.
- Retire MTF≥3 + bias du verdict (→ deviennent CORE/bonus, fin double-comptage).
  Retire le filtre ACHAT/VENTE-only.

### 4a — Étoiles → score
- CORE 1 near_level (S/R + RTH, ES 8t/NQ 16t) : hard requis.
- CORE 2 bias cohérent : `|bias_score|>=0.33 ET sign(bias)==direction` : hard requis.
- BONUS (total 6.0) : rvol≥1.1 (+1.5) · momentum (+1.0) · MTF≥2/max1opp (+1.5) ·
  pullback (+1.0) · bar_confirmation (+1.0).
- Armement : `2 CORE OK ET somme_bonus >= MIN_BONUS_SCORE` (défaut 4.0/6.0, env tunable).

### 4c — momentum/pullback non-bloquants
Subsumé par le score 4a (N bonus, pas tous) → lève la contradiction momentum vs pullback.
Pas de code dédié.

### 4d — Seuils (config)
RVOL_MIN 1.3→1.1 · BIAS_SCORE_MIN_ABS 0.5→0.33 · MOMENTUM_5B_MIN_ABS symbol-aware
(ES 2.0/NQ ~12) · near_level ES 8/NQ 16.

### 4e — Garde-fous + collecte
Armer cooldown register_close (main.py _on_fill_close, mort COMMENT_FALSE #65) ·
brancher/retirer anti-clustering · MAX_TRADES_PER_DAY=9999 · stops ±$2000.

### 4bis — Backtest edge (BLOQUANT avant trust)
Re-replay enriched : compter trades (cible 2-5/j qualité) + PROUVER edge (pas juste +trades)
+ préservation 2 trades réels. Pas live tant que N<100 simulés (DSR).

### Garde-fous souverains
Préservation 2 trades · re-replay avant deploy · review agent (Trading/Risk).

---

## 9. PHASE 4 — Plan v4 FINAL (GO FRANC collecte paper, 19/06)

Décision Jackson : Bot 2 = "Mirror" du BIAIS journalier → trade AVEC le régime (with-trend),
day-features dans dir_score = VOULU (pas un bug).

**4b Verdict** : `_compute_pts` momentum SYMBOL-AWARE (point si momentum_5b > 1.0 ES / 10.0 NQ).
`dir_score = bull_pts−bear_pts`. LONG si >=3 & bear<=1 ; SHORT si <=−3 & bull<=1 ; sinon ATTENDRE.
Retire MTF + bias du verdict.
**4a CORE+bonus** : CORE hard = near_level (S/R + RTH + ES 8t / NQ 16t). BONUS = COMPTE de 3 dims
INDÉPENDANTES {rvol≥1.1, pullback, bar_confirmation}, armement si near_level OK ET count >= MIN_BONUS_COUNT
(défaut 2/3, env BOT1V2_MIN_BONUS_COUNT). "conviction |dir_score|>=4" RETIRÉ (= dir_score, non indépendant).
**Vetos** : 4 hard. CAVEAT : gamma_block_* ABSENT sur ES → veto gamma INACTIF sur ES, protection -$967
NON garantie sur ES (accepté collecte paper ; branchement mq_* = backlog).
**Seuils** : RVOL_MIN 1.1, BIAS_SCORE_MIN_ABS 0.33 (bias plus dans gating mais garder cohérent),
near ES8/NQ16, momentum symbol-aware.
**GO** : trades/jour post-cooldown 2-6 (régulé MAX_TRADES=5). Préservation 2 trades ✅. Framing collecte
observatoire (pas de claim edge ; backtest PF avant live).

Validation : trading-strategy-analyst GO FRANC conditionnel (3 rounds). Reste : code (ce module ≠ plan),
review code-reviewer + codes log avant commit, dédup par ts dans tout backtest.
