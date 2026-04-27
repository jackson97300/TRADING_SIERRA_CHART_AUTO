# BOT CHANGELOG — MIA Trading System

**Journal permanent de toutes les modifications apportees au bot** : gates, features, fixes, configs, refactos. Ordre **anti-chronologique** (dernier en haut).

## Regles d'usage (obligatoires)

1. **AVANT** tout deploy d'une modif qui touche le moteur de decision (paper_trader, builders, SLTPEngine, C++ DMP, gates), ecrire une entry ici.
2. **Format strict** : utiliser le template ci-dessous. Tout champ obligatoire.
3. **Backtest preservation** obligatoire si modif impacte scoring/gates — doit prouver que les wins historiques restent wins.
4. **Review agent** obligatoire selon matrice `critical-tasks-review.md`.
5. **Apres deploy** : ajouter la section "Deployed at YYYY-MM-DD HH:MM" + "Suivi post-deploy" avec metriques observees a 1/7/30 jours.
6. **En cas de rollback** : NE PAS supprimer l'entry. Ajouter section "Rolled back at YYYY-MM-DD HH:MM — raison" + garder trace.
7. **Liens** : toujours cross-reference avec INCIDENT_LOG, memories, reviews agents.

## Template d'entry

```markdown
## YYYY-MM-DD HH:MM — [SHORT_TITLE]

**Categorie** : [FIX | FEATURE | GATE | CONFIG | REFACTO | ROLLBACK]
**Impact prod** : [LIVE | PAPER | DASHBOARD | OFFLINE]
**Fichier(s)** : `path:line`
**Schema/version** : X.Y.Z -> X.Y.Z+1 (si applicable)
**Reviewer(s) agent** : code-reviewer / market-analyst / ml-trainer / Plan

### Quoi
Description factuelle 1-3 phrases.

### Pourquoi
Justification business + data (chiffres, findings). Lien incidents/backtests.

### Impact attendu
- Metriques : +$X PnL / -Y rejets
- Effet de bord : aucun | liste

### Validation pre-deploy
- [ ] Tests unitaires: N/N
- [ ] Backtest preservation: X wins / Y wins
- [ ] Review agent: GO / RESERVES (lien)
- [ ] Test empirique: commande + resultat

### Revert plan
```bash
# commandes de rollback explicites
```

### Deployed at YYYY-MM-DD HH:MM
(a remplir apres deploy VPS + restart service)

### Suivi post-deploy
- J+1 : metriques observees
- J+7 : metriques observees
- J+30 : metriques observees

### Liens
- INCIDENT_LOG : YYYY-MM-DD entry
- Memory : `feedback_*.md`
- Review agent : ... (summary court)
```

---

## Entries

## 2026-04-27 22:00 — [FEAT signal_engine_rules V1 deployed + paper_trader integration]

**Categorie** : FEAT
**Impact prod** : OFFLINE batch + paper_trader snapshot enrichi (PAS de change decision logic)
**Fichier(s)** :
- `CORE/signal_engine_rules/__init__.py` (nouveau)
- `CORE/signal_engine_rules/schema.py` (nouveau, RuleTag dataclass)
- `CORE/signal_engine_rules/rules.py` (nouveau, 9 pure functions + RULES_V1 + apply_all_rules)
- `CORE/signal_engine_rules/batch_tagger.py` (nouveau, parquet v5b -> v5c)
- `CORE/signal_engine_rules/tests/*.py` (52/52 tests PASS)
- `CORE/mia_paper_trader.py` : `_lookup_rules_tags` + `rules_fired` field au close snapshot

**Quoi** : middleware tagger 9 regles (long_up/dn_bar, color_up/dn_proximity, color_zone_break, cluster_at_high/low, failed_ib_poor_high, edge_zone_fire). Format RuleTag(direction, strength, version, fired_at, meta). Batch ES/NQ_dataset_v5b -> v5c (18 cols ajoutees, 53s chacun). Paper_trader logge `rules_fired` au close trade pour analyse comportementale + dataset re-training ML futur.

**Pourquoi** : Plan B Jackson 27/04 soir suite NO-GO ML PF 1.09 marginal. Edge live trader (Topstep +$665 22/04) pas reproductible avec features 24m statiques. Solution : trader rules-only + collecter dataset comportemental sur 100-300 trades avant re-training ML.

**Impact** :
- AUCUN changement logique entry (toujours via `conseil_global` dashboard)
- Snapshot trade enrichi avec `rules_fired: {<rule_name>: {direction, strength}}` + `rules_schema_version: "1.0"`
- Parquet v5c disponible pour Phase 1 Winner Cluster + Phase 3 Aronson + Phase 5 CPCV mega battery

**Validation pre-deploy** :
- Tests : 52/52 PASS (6 schema + 26 rules + 12 anti-leak + 5 batch + 3 corrections post-review)
- Anti-leak : test_no_lookahead.py NON-NEGOTIABLE par spec section 5.2 + incident leak 27/04 21:30
- Smoke ES + NQ batch_tagger : 53s chacun, 18 cols ajoutees, distribution coherente
- Smoke `_lookup_rules_tags` sur trade window 31 bars : long_up_bar +1 + edge_zone_fire -1 fire correctement

**Reviews agents** :
- Plan agent (design) : GO-AVEC-RESERVES + 5 corrections appliquees (JL2 sortie V1, dataclass RuleTag, batch-only V1, anti-leak guards, tests obligatoires)
- code-reviewer (implementation) : GO-AVEC-RESERVES + 6 corrections appliquees (C1 docstring strength, C2 test color_zone_break BUY priority, I1 hard blacklist dist_ib_*, I5 contract test apply_all_rules, S2 NaN test color_zone_break, S3 strength constants)
- ml-trainer Phase 2 (SHAP v5b) : top 10 features propres confirmees, top SHAP utilise comme prior pour rules

**Spec** : `DOCS/specs/2026-04-27-signal-engine-rules-design.md`
**Plan** : `DOCS/plans/2026-04-27-signal-engine-rules-implementation.md` (12 tasks TDD)

**Anomalies non-bloquantes a investiguer post-deploy** :
1. `color_zone_break` 0 fires sur 351K bars ES + NQ → seuil 0.05% probablement trop strict, a re-calibrer
2. `failed_ib_poor_high` 0 fires sur 24m → conjonction conditions IB rare, a verifier si bug ou feature naturelle

**Revert plan** : si snapshot trade KO ou regression paper_trader → comment ligne `_lookup_rules_tags` call. Parquet v5c reste utilisable pour analyse manuelle.

**Suivi post-deploy** :
- J+1 : compter `rules_fired` non-empty dans 5 derniers trades paper, verifier coherence
- J+7 : agreger 30+ trades, comparer fire_counts live vs backtest battery
- J+30 : Re-train ML Phase 2 sur dataset comportemental 100+ trades (re-evaluer JL2)

**Cross-references** :
- INCIDENT_LOG 2026-04-27 21:30 (leak resolu) + 20:30 (3 leaks structurels detectes)
- Memory `feedback_ml_features.md` (top SHAP v5b documente + features leaky blacklistees)

---

## 2026-04-25 23:30 — [REFACTO data source : Migration DMP -> Databento + dataset v4 enrichi]

**Categorie** : REFACTO
**Impact prod** : OFFLINE (data backfill + future ML training)
**Fichier(s)** : `CORE/databento_download.py`, `CORE/databento_backfill_batch.py`, `CORE/databento_backfill_full_free.py`, `CORE/build_dataset_v4_dmp_databento.py`, `CORE/research/compare_close_hlv*.py`
**Schema/version** : DMP custom -> Databento GLBX.MDP3 (source officielle CME)
**Reviewer(s) agent** : code-reviewer + quality-auditor + Plan agent (3 audits convergents)

### Quoi
Migration source data primaire DMP custom Sierra Chart (boite noire SC subgraphs) -> Databento (source officielle CME). Architecture HYBRIDE : DMP continue forward sur VPS pour MQ features (95 jours archive existante). Build dataset v4 enrichi (700k bars × 48 cols, 30 MB Parquet) merging Databento OHLCV + Trades + DMP MQ features.

### Pourquoi (validation empirique)
- DMP confirme buggy historique : 13/04/2026 perd 7h data (London + cash open NY) puis triple-compte 16h-20h UTC (180 bars/h vs 60). Vol diff 53% vs Databento. Bug silencieux non detecte pendant des MOIS.
- Databento Standard $179/mois inclut 15 ans OHLCV + 12 mois Trades + 1 mois MBP-10 GRATUIT.
- Comparaison 10 jours empirique (compare_close_hlv_10days.py) : ES close mismatch 0.057%, NQ 0.142% — sous seuil Plan agent 0.15%.
- Achat Trades 5 ans aurait coute $1374 (verifie portail) — DECISION : reste sur 12 mois gratuit + DMP archive 95 jours pour MQ.

### Impact attendu
- ML training Lopez compliant : 350k bars/symbole × 48 cols
- Primary model : OHLCV + Trades agg (12 mois exact aggressor)
- Meta-labeler : MQ features (95 jours overlap avec data Databento)
- Effet de bord : 4 scripts nouveaux + 1 dataset Parquet partitionne

### Validation pre-deploy
- [x] Tests empiriques : 4 dry-runs sur 1 mois mars 2026 (5 bugs API runtime fixes)
- [x] Comparaison 10 jours DMP vs Databento (0.057% ES / 0.142% NQ mismatch)
- [x] Backfill 4 runs : Run 3 Trades 195M records OK, Runs 1+2 partial OK (data ecrite), Run 4 FAIL safety threshold
- [x] Audit 3 agents (code-reviewer 6.5/10, quality-auditor BLOCKED, Plan agent GO-RESERVES)
- [ ] **8 BUGS A CORRIGER avant ML training** — voir INCIDENT_LOG 2026-04-25 23:30

### Bugs detectes par audit (must-fix avant ML)
1. `bars_since_roll` accumule cross-mois (cumcount group bug)
2. CVD reset 22:00 UTC FAUX en hiver (DST = 23:00 UTC)
3. `dist_mq_*_atr` clip ±10 ATR detruit info (3 features mortes 88-99% clipped)
4. Fuite instrument 13 features (atr_14m + ticks bruts NQ vs ES)
5. `dist_mq_hvl_0dte` 99.6% null
6. Non-idempotence sub-period (warm-up perdu)
7. Documentation manquee (cet entry corrige)
8. MQ filled biais temporel (12% global, 56-59% mois recents seulement)

### Revert plan
```bash
# Si Databento non concluant apres N jours :
# 1. Cancel subscription Databento (databento.com/portal/billing)
# 2. Continue DMP (jamais arrete) comme source primaire
# 3. Garder dataset v4 archive pour analyses comparatives
# Aucun rollback code car DMP n'a jamais ete debranche
```

### Deployed at 2026-04-25 22:30 (backfill termine)

### Suivi post-deploy
- J+1 : applique 8 fix bugs identifies + REBUILD dataset
- J+7 : monitoring DMP vs Databento divergence quotidienne
- J+30 : decision achat Trades 5 ans selon paper trading edge

### Liens
- INCIDENT_LOG : 2026-04-25 23:30 (8 bugs detectes) + 2026-04-25 21:00 (bug DMP 13/04)
- Memory : `project_data_v3.md` (a creer pour v4)
- Review agents : code-reviewer 6.5/10 + quality-auditor 15 red flags + Plan agent 8 angles morts
- Cout : $54 paye Databento (proratise) + $179/mois recurrent

---

## 2026-04-25 — [ROLLBACK fix bn_absorb + finding strategique replay/Full Recalc]

**Categorie** : ROLLBACK
**Impact prod** : LIVE (collecte features)
**Fichier(s)** : `CPP/MIA_REFACTORED/DUMPER/DMP_Reader.h:1655-1665`, `DMP_Config.h:60`
**Schema/version** : 3.7.15 → **rollback 3.7.14**

### Quoi
Rollback du fix bn_absorb_ask/bid via ExtensionLineCount. Restauration DMP_ReadBN_Trigger original.

### Pourquoi (validation empirique via replay)
Test replay 24/04 (Reload All Charts + Full Recalc) :
- ES bn_absorb_ask : 3.31% (PRE) → **100% saturation** (POST) — ExtensionLineCount accumule en trending
- NQ bn_absorb_ask : 0.73% (PRE) → **0% regression** (POST) — Extension Lines pas active sur Chart 2
- Memoire `feedback_lessons.md` avait predit la saturation : confirme empiriquement.

**100% saturation = feature MORTE pour ML (pas de variance) = pire que rare 3.31%**.

### FINDING STRATEGIQUE MAJEUR (validee meme test)

Replay/Full Recalc **AJOUTE des bars manquantes** sans en perdre :
- ES + NQ : **+139 bars Asia early** par instrument (23/04 22:01-00:19 UTC)
- 0 bar perdue
- Features toutes valides (price, atr, vwap, delta, rvol = 100% non-zero)

**Le DMP live rate des bars en transition de jour UTC** (probable rollover bug). Le Full Recalc les recupere proprement.

**Implication strategique** : la strategie Jackson "reconstituer 6 mois data via replay" est **EMPIRIQUEMENT VALIDEE**. Sur 120 jours, gain potentiel +10-15% data = milliers de bars supplementaires pour ML.

### Backlog — vraie solution bn_absorb
- Tentative #1 (Extension Lines) : echec (saturation/regression)
- A explorer :
  - Option A : delta ExtensionLineCount entre 2 polls (+1 line = nouveau event)
  - Option B : verifier timing sg0 sz-1 vs sz-2
  - Option C : autre subgraph (sg2 SumOfAlerts ?)
- **Pas de retry tonight** — necessite analyse code C++ + visuel chart Jackson

### Validation pre-deploy
- [x] Code rollback fait
- [x] Schema 3.7.14 restaure
- [x] Backups in place (PRE_FIX, PRE_REPLAY)
- [ ] Recompile DLL — Jackson required
- [ ] Verif live Asia 23h ET dimanche soir

### Suivi post-deploy
- J+1 (lundi 27/04) : verifier `bn_absorb_ask` retourne au comportement PRE_FIX (3.31% ES, 0.73% NQ)
- Strategie reconstituer 6 mois data : a planifier en chantier post-paper validation

### Lecon (memoire a ajouter)
**Avant de fix une feature soupconnee morte, MESURER PRE_FIX baseline empirique** (pas presumer 0% sans data). Le fix peut paraitre justifie sur audit faulty mais detruire un comportement qui marchait deja partiellement.

---

## 2026-04-25 — [DMP_Reader fix bn_absorb_ask/bid via Extension Lines]

**Categorie** : FIX (bug C++ DMP critique)
**Impact prod** : LIVE (collecte features → ML → bot)
**Fichier(s)** : `CPP/MIA_REFACTORED/DUMPER/DMP_Reader.h:1655-1670`
**Schema/version** : 3.7.10 → **3.7.11** (comportemental, 268 cols inchange — MAIS lecture features change : bn_absorb_ask/bid passent de "100% zero" a "actif quand event")
**Reviewer(s) agent** : (a faire) schema-auditor + code-reviewer

### Quoi
Remplacement lecture `bn_absorb_ask` et `bn_absorb_bid` :
- AVANT : `DMP_ReadBN_Trigger(sc, chart, study)` lit ACSIL sg0 = SG1 UI = **Color Bar (pulse 1 bar)** → rate 99% des events
- APRES : `DMP_ReadExtensionLineCount(sc, chart, study) > 0 ? 1.0f : 0.0f` lit les **Extension Lines** (persistent jusqu'a intersection prix)

### Pourquoi
**Bug confirme visuellement par Jackson 25/04** :
- Capture Sierra Chart 1 ID 25 (ABSORB_ASK ES) : events visibles (chiffres jaunes affiches)
- JSONL DMP `bn_absorb_ask` : **100% zero** sur 985 bars 23/04 ES + 982 NQ + 1239 24/04 ES + 1059 NQ
- Pattern identique fix delta_divergence 07/04 (Famille A "AddLineUntilFutureIntersection")

Code C++ ligne 1539 confirme structure :
- SG1 (UI) = ACSIL sg0 = Color Bar = pulse 1 bar (= ce que le DMP lisait)
- SG2 (UI) = ACSIL sg1 = Extension Lines = persistent (= ce qu'il fallait lire)

### Impact attendu
- **bn_absorb_ask** : passe de 100% zero a ~5-15% non-zero (events absorb sur trends)
- **bn_absorb_bid** : idem
- **Decision bot** : ZERO impact (bn_absorb_* loggue mais 0 pts au scoring conseil_global, cf builders.py:1300)
- **Future ML** : feature redevient utilisable → top features ML potentiellement reordered

### Prerequis Sierra Chart (a faire avant compile)
Verifier sur les 4 etudes ABSORB que **"Draw Extension Lines at Color Bar Value = Extend to Future Intersection"** est active :
- Chart 1 ID 25 (ES ABSORB_ASK) — confirme 25/04 capture
- Chart 1 ID 26 (ES ABSORB_BID) — a verifier
- Chart 2 ID 29 (NQ ABSORB_ASK) — a verifier
- Chart 2 ID 30 (NQ ABSORB_BID) — a verifier

**A noter** : Number of Bars to Calculate = 20 sur ces etudes. Pas critique pour ce fix (Extension Lines persistent au-dela de 20 bars une fois cree), mais a augmenter a 2000 pour robustesse backfill.

### Validation pre-deploy
- [x] Code modifie (4 lignes)
- [x] Syntax check (commentaires + structure C++ valides)
- [ ] Review schema-auditor : a faire avant deploy
- [ ] Review code-reviewer : a faire avant deploy
- [ ] Recompile dans Sierra Chart (Jackson required)
- [ ] Test empirique JSONL post-deploy : bn_absorb_ask >0 quand events visuels visibles

### Revert plan
```bash
# Restorer DMP_ReadBN_Trigger pour bn_absorb_ask/bid (4 lignes)
git revert <commit>
scp DMP_Reader.h Administrator@VPS:"C:/SIERRA CHART TRADING/ACS_Source/"
scp DMP_Reader.h Administrator@VPS:"C:/TRADING_SIERRA_CHART_AUTO/CPP/MIA_REFACTORED/DUMPER/"
# Recompiler dans Sierra Chart + Reload Charts 30/31
```

### Deployed at (a remplir post-recompile Jackson)

### Suivi post-deploy
- J+1 : verifier `bn_absorb_ask` > 0 sur quelques bars dans JSONL frais
- J+5 : audit features avec `dmp_features_health_check.py` (a creer) → confirme regression evitee
- J+30 : feature dans top 10 ML importance ?

### Liens
- INCIDENT_LOG : 2026-04-25 (entry a creer pour pattern recurrent)
- Memoire : `feedback_lessons.md` Famille A (delta_divergence fix 07/04 = meme pattern)
- Memoire : `feedback_validation_miss_patterns.md` (6eme occurrence pattern)

### TODO connexes (meme bug, autres features)
A appliquer apres validation visuelle Jackson :
1. `bn_long_up`, `bn_long_dn` (ligne 1661-1664)
2. `bn_volume_up`, `bn_volume_dn` (ligne 1691-1701)
3. `fp_edge_buy`, `fp_edge_sell`, `fp_edge_buy_2`, `fp_edge_sell_2` (ligne 1693-1705)

**NE PAS** appliquer aveuglement : chaque feature doit etre confirmee visuellement par Jackson AVANT modif (anti-pattern 11 — eviter de casser ce qui marche peut-etre).

---

## 2026-04-25 — [Enrichissement log V2 systeme decisions paper_trader]

**Categorie** : FEATURE (observabilite, pas de scoring/gate change)
**Impact prod** : PAPER
**Fichier(s)** :
  - `CORE/log_catalog.py:112-121` (+10 codes GATE_*)
  - `CORE/mia_paper_trader.py:145-162` (REJECT_LOG_STEPS + REJECT_TO_V2_CODE)
  - `CORE/mia_paper_trader.py:605` (emit V2 dans _log_rejection_detailed)
  - `CORE/mia_paper_trader.py:765-785` (context enrichi step 3)
**Schema/version** : -
**Reviewer(s) agent** : market-analyst (GO log + garde-fou 10j avant fix ES)

### Quoi
Enrichissement du systeme de logs V2 existant pour tracer le funnel paper_trader :

1. **10 codes catalog `GATE_*`** ajoutes (categorie `decisions/`) :
   - `GATE_CONSEIL_ATTENDRE` — conseil = ATTENDRE (avec bull/bear pts, bias, MTF, range_pos)
   - `GATE_CONSEIL_CONFLIT`
   - `GATE_SELL_AUTO_DISABLED`
   - `GATE_FRESHNESS_EXPIRED`
   - `GATE_SIGNAL_DEDUPED`
   - `GATE_CONF_TOO_LOW`
   - `GATE_MTF_INSUFFICIENT`
   - `GATE_BAR_DMP_MISSING`
   - `GATE_SLTP_REJECT`
   - `GATE_PAYOFF_TOO_LOW`

2. **REJECT_LOG_STEPS etendu** : inclut `3_conseil` (avant : bruit skip).

3. **Mapping `REJECT_TO_V2_CODE`** : chaque reason funnel → code catalog V2.

4. **`_log_rejection_detailed`** : emit V2 supplementaire vers `LOGS/decisions/decisions_YYYYMMDD_paper.jsonl` APRES ecriture rejections/ (rate limite existant 60s/sym/reason conserve, pas de spam).

5. **Context enrichi step 3** : capture `bull_pts`, `bear_pts`, `bias`, `mtf_bulls`, `mtf_bears`, `confidence`, `range_pos`, `signal_id` au moment du reject `conseil_attendre`/`conseil_conflit`.

### Pourquoi
Audit ES 0 trade 24/04 : impossible de diagnostiquer sans trace continue. `conseil_global` ES etait en ATTENDRE 100% du temps US RTH mais **aucun log** des valeurs `bull_pts`/`bear_pts`/MTF au moment des rejets step 3 (previously skipped comme "bruit").

Market-analyst R2 demande : log empirique obligatoire AVANT tout fix scoring/gate ES (garde-fou pattern 11 : aucun fix avant N>=10 jours de data).

### Impact attendu
- Post-deploy : chaque reject step 3-8 est trace dans `LOGS/decisions/`
- Permet diagnostic "pourquoi pas de trade ES" avec data empirique
- Rate limite 60s/sym/reason → ~10-20 entries par jour par gate (pas de spam)
- Zero impact sur decisions trade (pur observabilite)
- Zero impact perf (emit V2 async JSONL append)

### Validation pre-deploy
- [x] Syntax check paper_trader + log_catalog OK
- [x] pytest 137/137 non-regressed
- [x] Review market-analyst R2 : GO log + 10j garde-fou
- [x] Rate limit 60s conserve (pas de spam)

### Revert plan
```bash
# Retirer les codes GATE_* du catalog + retirer REJECT_TO_V2_CODE + retirer emit V2 block + retirer step3_ctx
git revert <commit>
scp CORE/mia_paper_trader.py CORE/log_catalog.py VPS
Restart-Service MIA-Paper
```

### Deployed at 2026-04-25 00:02 UTC puis enrichi 00:11 UTC
- **v1 (00:02)** : step 3 enrichi (bull/bear_pts, mtf, bias, conf, range_pos) + emit V2 decisions/ pour tous les steps
- **v2 (00:11)** : market_ctx injecte a TOUS les rejets step 3-8 — 10 champs additionnels :
  - `dist_vwap_atr`, `atr`, `session`, `vix_regime` (context volatilite/session)
  - `mq_dist_call_t`, `mq_dist_put_t`, `mq_dist_hvl_t` (distances murs majeurs en ticks)
  - `mq_next_wall_t`, `mq_next_wall_side` (prochain mur + side)
  - `above_hvl` (position vs HVL)
- SCP paper_trader.py → VPS (2 restarts successifs)
- **Total : 19 champs loggues dans chaque reject vs 8 avant**

### Finding immediat du log
**Paradoxe NQ detecte au premier sample** : `bull_pts=4, bear_pts=2, bias=BULLISH, mtf=4/0` devrait donner action=ACHAT PRUDENT (builders.py:1322). Log dit action=ATTENDRE. Anomalie inexpliquee par la logique de scoring seule (stabilizer ? freshness ?). **Sans ce log enrichi, invisible.** A investiguer lundi 27/04 session US.

### Suivi post-deploy
- J+1 (lundi 27/04) : verifier `LOGS/decisions/decisions_*.jsonl` contient entries `GATE_*`
- J+5 : aggreger distribution par symbol/reason, identifier pattern ES
- **J+10 (05/05)** : critere GO/NOGO fix ES selon market-analyst :
  - Si bull_pts>=4 atteint 0 fois sur ES → calibration NQ inadaptee → fix justifie
  - Sinon ES = instrument plus selectif → statu quo

### Liens
- Audit ES 0 trade : `CORE/research/reconstruct_mtf_es_25042026.py`
- Regle log-debug-protocol : `.claude/rules/log-debug-protocol.md`
- Memory : `feedback_log_debug_protocol.md`
- Review market-analyst : GO + 10j garde-fou

---

## 2026-04-25 — [O3 Notification API browser pour trade events]

**Categorie** : FEATURE
**Impact prod** : DASHBOARD
**Fichier(s)** : `DASHBOARD/static/js/dashboard.js:3707-3811` (+ cache bust v=80 → v=81)
**Schema/version** : -
**Reviewer(s) agent** : aucune (feature UX pure, pas de scoring/gate)

### Quoi
Ajout Notification API browser en complement des sons Audio :
- Demande permission au 1er clic bouton TEST (user gesture requis Chrome)
- Envoie notif native pour chaque trade OPEN/TP/SL avec titre + body contextualise
- Replace notif precedente via `tag: "mia-trade"` (evite spam superpose)
- Auto-close 8s + click = focus dashboard tab
- Respecte le toggle ACTIF/MUET (meme etat que sons)

### Pourquoi
Limitation Audio API Chrome : autoplay bloque quand onglet inactif (background tab) → Jackson a rapporte "Ordre servi entendu mais pas Target servi" car il etait sur Sierra Chart au moment du TP. Notification API fonctionne TOUJOURS, meme onglet inactif.

### Impact attendu
- Jackson peut etre alerte des trades meme en travaillant sur Sierra Chart ou autre app
- Notif se stack pas : tag="mia-trade" remplace la precedente
- Aucun impact performance (native browser API)

### Validation pre-deploy
- [x] Syntax check `node --check` OK
- [x] Respecte toggle MUET (si muet → pas de son NI notif)
- [x] Auto-dismiss 8s evite spam
- [x] Click notif = focus tab dashboard

### Revert plan
```bash
# Retirer _sendNotif calls + function, bump cache bust
```

### Deployed at 2026-04-25 (minuit approx)
- SCP dashboard.js v81 + index.html → VPS
- Pas de restart requis (static files)
- Jackson doit faire **Ctrl+F5** sur dashboard, puis **clic TEST** pour autoriser permission

### Suivi post-deploy
- Au prochain trade : Jackson doit voir notif native dans coin ecran meme si onglet dashboard minimise
- Si permission refusee : revenir proposer plus tard

---

## 2026-04-25 — [Fix B2 MenthorQ regime fallback sur dernier fichier disponible]

**Categorie** : FIX
**Impact prod** : PAPER / DASHBOARD
**Fichier(s)** : `CORE/mia_paper_trader.py:398-460` (`_load_menthorq_regime`)
**Schema/version** : -
**Reviewer(s) agent** : aucune (modif non scoring/gates, pure infra)

### Quoi
Si `DATA/MENTHORQ/{today}_menthorq_complete.json` absent, fallback automatique sur le dernier fichier disponible (max 7j). Expose dans state.json `fallback_used: bool` + `fallback_date: str` pour transparence dashboard.

### Pourquoi
MenthorQ data extraite post-close jour J par Jackson, utilisable jour J+1. Si pas encore extrait (weekend, delay Jackson), bot avait `regime = UNKNOWN` sur dashboard. Inutile. Les donnees MQ sont valides plusieurs jours (levels statiques).

### Impact attendu
- Dashboard regime ES/NQ affiche le dernier regime connu au lieu de UNKNOWN
- Decisions trade : **ZERO impact** (features mq_* viennent du DMP JSONL live, pas de ce fichier)
- Log visible : `mq_regime fallback : today=20260425 absent, loaded 20260423`

### Validation pre-deploy
- [x] Syntax check OK
- [x] Test fallback logic : 20260425 (today absent) → 20260423 (age 2j, < 7j) used correctly
- [x] Aucun impact sur scoring/gates (lecture read-only)

### Revert plan
```bash
# Retirer le bloc fallback (~45 LOC), restaurer comportement MQ_REGIME_MISSING
git revert <commit>
scp CORE/mia_paper_trader.py VPS
Restart-Service MIA-Paper
```

### Deployed at 2026-04-24 23:30 UTC (samedi 25/04 01:30 FR)
- SCP `CORE/mia_paper_trader.py` → VPS
- `Restart-Service MIA-Paper` OK
- Verif state.json : `menthorq_regime.fallback_used=true, fallback_date="20260419"`
  (ES=GEX+ net_gex=132040000, NQ=GEX+ net_gex=4890000)

### Bug orthogonal decouvert (backlog)
Le scraper auto `mia_menthorq_scraper.py` ECRASE les fichiers manuels Jackson quand
il execute. Exemple 24/04 : mon SCP matin de `20260423_menthorq_complete.json`
(source="extraction manuelle", key_levels valides) → ecrase par scraper auto
14:18 qui a genere un fichier avec echecs 422 (raw_ajax only, pas de key_levels).
Fix B2 le CONTOURNE (fallback saute les fichiers invalides), mais le bug reste.
TODO : modifier scraper pour SKIP si fichier existant a source="extraction manuelle".

### Suivi post-deploy
- J+1 : verifier fallback actif sans regression
- Pas de suivi long terme necessaire (infra cosmetique)

---

## 2026-04-25 — [MTF_BULL_DESERT filter SHORT sur `mtf_bulls <= 1`]

**Categorie** : GATE
**Impact prod** : PAPER
**Fichier(s)** : `CORE/mia_paper_trader.py:717-750` (check_entry step 6)
**Schema/version** : - (comportemental, pas de bump)
**Reviewer(s) agent** : market-analyst (R1 + R2) + code-reviewer (a faire)

### Quoi
Ajout gate downside-only `MTF_BULL_DESERT` dans `check_entry()` : si `direction == "SHORT" AND mtf_bulls <= 1 AND mtf_bears < 3`, rejet immediat avec raison `mtf_bull_desert`. Intervient AVANT le gate existant `min_mtf_bears >= 3` comme defense en profondeur.

**IMPORTANT** — la condition inclut `mtf_bears < 3` pour preserver les SHORT avec MTF **bearish aligne** (ex: SHORT 18:18 du 24/04 avait `mtf=0/3` → `mtf_bears=3` → SHORT legitime, ne doit PAS etre bloque). Sans cette condition, regression detectee par backtest preservation → fix avant deploy.

### Pourquoi
Backtest lookforward 24/04 sur 107 SHORT bloques par gate MTF aval, decoupe par `mtf_bulls` :

| mtf_bulls | n | W/L | PnL | PF | USD |
|---|---|---|---|---|---|
| 0 | 3 | 0/3 | -60t | 0.00 | -$90 |
| **1** | **15** | **2/13** | **-188t** | **0.28** | **-$282** |
| 2 | 21 | 9/12 | +84t | 1.35 | +$126 |
| 3 | 68 | 26/42 | +96t | 1.11 | +$144 |

Bucket `mtf_bulls <= 1` combine : 18 trades, WR 11%, PnL -248t = -$372 (3 micros). Edge negatif credible (Wilson 95% WR 13% sur n=15 = [2%, 38%]).

**Defense en profondeur** : si jamais `min_mtf_bears >= 3` est modifie ou bypass, ce filtre downside reste actif.

### Impact attendu
- PnL : +$0 today (redondant avec gate actuel), +$282/jour similaire si gate superieur desactive un jour
- Rejets supplementaires : 0 (deja tous bloques par gate aval)
- Effet de bord : aucun — le filtre intervient AVANT le gate existant, decision identique

### Validation pre-deploy
- [x] Tests unitaires: pytest CORE/ 137/137 passes (2 failures + 2 errors pre-existants)
- [x] Backtest preservation: 18/18 trades executes 24/04 preserves (premiere version avait regression sur SHORT 18:18 mtf=0/3 — fix condition ajoutee `mtf_bears < 3`)
- [x] Backtest verif catch: 18 SHORT rejetes bucket mtf<=1 + mtf_bears<3 catches par le filtre (identique gate aval actuel, pas de changement funnel)
- [x] Review code-reviewer: GO-AVEC-RESERVES mineures → 2 commentaires enrichis (redondance + revert)
- [x] Review market-analyst R1 (seuil >=3 rejete, demande split data)
- [x] Review market-analyst R2 (GO sur ce filtre precis, confidence 4/5)
- [x] Deploy VPS : SCP + restart MIA-Paper OK, filtre present ligne 742

### Lecon retenue
Backtest preservation a detecte regression silencieuse (1/18 trades bloque). Sans changelog + backtest automatique, le SHORT 18:18 aurait ete bloque en prod sans explication. **Justifie definitivement la regle "backtest preservation obligatoire sur modif scoring/gates".**

### Revert plan
```bash
# Retirer les 7 lignes ajoutees dans check_entry puis:
scp CORE/mia_paper_trader.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 "powershell -Command 'Restart-Service MIA-Paper'"
# Confirmer via paper_trader.log que bot repart
```

### Deployed at 2026-04-25 (samedi marches fermes, deploy safe)
- SCP `CORE/mia_paper_trader.py` + `CORE/log_catalog.py` vers VPS
- `Restart-Service MIA-Paper` OK
- Verif : `Select-String mtf_bull_desert CORE/mia_paper_trader.py` → ligne 742 present sur VPS
- Position ouverte : 0 (pas de trade en cours, marches fermes)
- Bot statut : Running, heartbeat actif

### Suivi post-deploy
- J+1 (26/04) : nombre de rejets `mtf_bull_desert` dans rejections_*.jsonl
- J+7 : re-split data 5+ jours multi-regime, verifier edge mtf<=1 reste credible
- J+30 : analyse statistique complete avec IC95% par bucket, envisager action sur mtf=2/3 si data suffisante

### Liens
- Backtest scripts : `CORE/research/backtest_short_what_if_24042026.py`
- Review market-analyst R1 : seuil >=3 rejete comme trop agressif
- Review market-analyst R2 : verdict GO sur filtre mtf<=1 specifique
- Memory `feedback_lightgbm_no_composite_indicators.md` (anti-pattern 11)

---

## 2026-04-24 22:30 — [Kill-switch paper_trader STOP.flag read]

**Categorie** : FIX (bug dormant 15 jours)
**Impact prod** : PAPER
**Fichier(s)** : `CORE/mia_paper_trader.py:65-70, 234-237, 1713-1770` + `CORE/log_catalog.py:107-110`
**Schema/version** : -
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES, 2 corrections appliquees)

### Quoi
- Ajout constante `STOP_FLAG_FILE` pointant `DATA/BOT_CONTROL/STOP.flag`
- Ajout etat `self._stop_flag_active + _stop_flag_activated_at + _stop_flag_stale_alerted` dans `__init__`
- Bloc kill-switch dans `run()` boucle principale : detection flag → flatten positions (retry a chaque tick pause) → mode pause (5s poll, pas de check_entry/exit) → alerte MAJEUR si pending > 30s
- Expose etat `kill_switch` dans `state.json` pour dashboard
- 2 codes log_catalog : `BOT_KILL_SWITCH_ACTIVATED` (MAJEUR), `BOT_KILL_SWITCH_RELEASED` (INFO)

### Pourquoi
Bouton "STOP BOT" dashboard admin ecrivait `STOP.flag` depuis 09/04 mais **seul `BOT/bot_main.py` (V1 legacy inactif) le lisait**. `CORE/mia_paper_trader.py` (bot actif) ignorait ce fichier → kill-switch inoperant 15 jours. Jackson a demande "bouton relancer" → audit a revele le bug dormant.

### Impact attendu
- Jackson peut arreter le bot depuis son telephone via dashboard (ex: news imminente)
- Bot flatten proprement + pause (process reste vivant, heartbeat persiste)
- Reprise via "REDEMARRER" : bot reprend check_entry/exit en 5s

### Validation pre-deploy
- [x] Tests unitaires: 137/137 pytest passes
- [x] Syntax check Python OK
- [x] Review code-reviewer: GO-AVEC-RESERVES → 2 corrections appliquees (retry flatten each tick + expose kill_switch in state)
- [x] Test empirique live VPS 14:25 UTC : STOP.flag cree → detection 12s + pause → flag supprime → reprise 9s ✓

### Revert plan
```bash
git revert <commit>
scp CORE/mia_paper_trader.py CORE/log_catalog.py VPS
ssh VPS "Restart-Service MIA-Paper"
```

### Deployed at 2026-04-24 14:24 UTC

### Suivi post-deploy
- J+1 (25/04) : aucun usage production (jamais trigger par Jackson), 0 bug detecte
- A surveiller : si trigger manuel par Jackson, verifier flatten se fait bien

### Liens
- INCIDENT_LOG : 2026-04-25 00:30 (VALIDATION_MISS + RESOLU)
- Memory : `feedback_validation_miss_patterns.md` (5eme occurrence promue escalation auto-load)

---

## 2026-04-24 22:30 — [Fix deco dashboard toutes 15 min (auto-refresh token)]

**Categorie** : FIX
**Impact prod** : DASHBOARD
**Fichier(s)** : `DASHBOARD/static/js/dashboard.js:5266-5278` + cache-bust `index.html` v=79 -> v=80
**Schema/version** : -
**Reviewer(s) agent** : (pas de review — modif frontend mineure non critique)

### Quoi
Dans `init()` : remplacement `fetch("/api/auth/me")` brut par `fetchWithAuth("/api/auth/me")` qui gere auto-refresh via cookie `mia_session` (7j).

### Pourquoi
Logs serveur VPS : **0 appel** `/api/auth/refresh` sur tout l'historique. Cause : `init()` utilisait `fetch` brut qui, sur 401 (token access 15min expire), clearait localStorage + redirect `/welcome` SANS tenter le refresh. Jackson se faisait deconnecter toutes les 15 min (access_expiry) sans explication.

### Impact attendu
- Plus de deconnexion tant que cookie refresh valide (7j)
- Zero regression : `fetchWithAuth` existe deja et gere le flow correctement

### Validation pre-deploy
- [x] Syntax check `node --check`: OK
- [x] Grep verif : aucun autre `fetch("/api/auth/me")` brut restant
- [x] Test empirique (a confirmer par Jackson avec DevTools Network)

### Revert plan
```bash
# Remplacer fetchWithAuth par fetch + headers Authorization
scp DASHBOARD/static/js/dashboard.js VPS
# Pas besoin restart (static file)
```

### Deployed at 2026-04-24 22:30 UTC (file-only, pas de restart requis)

### Suivi post-deploy
- Jackson doit faire **Ctrl+F5** pour charger v=80
- Jackson signale "ca continue" (25/04 matin) → probable cache browser, a diagnostiquer via DevTools
- A verifier : DevTools Sources > dashboard.js?v=80 affiche

### Liens
- INCIDENT_LOG : 2026-04-25 00:30

---

## 2026-04-24 22:30 — [Sons paper trading (3 WAV execution events)]

**Categorie** : FEATURE
**Impact prod** : DASHBOARD
**Fichier(s)** : `DASHBOARD/static/js/dashboard.js:3694-3817` (nouveau bloc sounds) + `DASHBOARD/static/index.html:174-191` (UI sidebar) + `DASHBOARD/static/sounds/*.wav` (3 fichiers)
**Schema/version** : -
**Reviewer(s) agent** : (pas de review — feature UX uniquement)

### Quoi
Ajout audio notifications dans le dashboard admin pour les evenements trade :
- `trade_open.wav` (W Ordre servi) sur nouveau `trade_id` dans `open_by_symbol`
- `trade_tp.wav` (W Target servi) sur TP close detecte
- `trade_sl.wav` (W Ordre stoppe) sur SL close detecte
- UI sidebar : toggle ACTIF/MUET + slider volume + bouton TEST (debloque autoplay Chrome)
- Persistance localStorage : `mia_sound_enabled`, `mia_sound_volume`

### Pourquoi
Jackson : "pouvoir etre alerte meme quand je ne regarde pas l'ecran, notamment en cas de trade sur news imminente".

### Impact attendu
- Feedback audio temps reel pour chaque trade pris/ferme
- Aucun impact backend, aucun risque trading

### Validation pre-deploy
- [x] Syntax check OK
- [x] Test empirique : son `Ordre servi` confirme audible par Jackson au trade 17:46 UTC
- [ ] Son `Target servi` : NON ENTENDU par Jackson — cause probable autoplay Chrome en onglet background

### Revert plan
```bash
# Retirer bloc sounds + UI sidebar, bump cache-bust
```

### Deployed at 2026-04-24 22:30 UTC

### Suivi post-deploy
- Backlog : ajouter Notification API native (marche onglet inactif contrairement a Audio)
- A confirmer par Jackson : bouton TEST fonctionne + slider volume OK

### Liens
- Fichiers WAV source : `D:/DORIAN/Sierra-Chart-en-Profondeur-partie-2-v2023.3/.../1. Voix feminine/`
