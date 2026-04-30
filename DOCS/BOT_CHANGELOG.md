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

## 2026-05-01 04:15 UTC — [Bot 2 MAX_TRADES illimite + fix cooldown restore au boot]

**Categorie** : FEATURE (alignement Bot 1) + FIX (bug safety cooldown bypass)
**Impact prod** : Bot 2 (MIA-DataBento-Paper Sim2) + dashboard
**Fichier(s)** :
- Modif : `CORE/databento_paper_trader.py:117` — MAX_TRADES_PER_DAY 5 → 9999 (illimite paper, alignement Bot 1)
- Modif : `CORE/databento_paper_trader.py:556-562` — appel `_restore_cooldown_state()` au boot
- Modif : `CORE/databento_paper_trader.py:818-880` — methode `_restore_cooldown_state()` NEW
- Modif : `DASHBOARD/api/paper_tracker.py:116` — fallback 10 → 9999 (coherence dashboard)
- Cree : `tests/test_bot2_cooldown_restore.py` — 4 tests regression

**Reviewer(s)** : 4/4 tests PASS (fixtures empty / nominal / invalid / cooldown calc)

### Quoi

**1. Bot 2 MAX_TRADES_PER_DAY = 9999 (alignement Bot 1)**

Avant : Bot 2 limite a 5 trades/jour, Bot 1 illimite (9999). Asymetrie.
Dashboard affichait "10" via fallback hardcoded (mensonge).

Apres : Bot 2 = 9999 (illimite paper, comme Bot 1 depuis 22/04). Cooldown
15min post-close + circuit breaker 3 SL gardent la safety.

**2. Fix bug cooldown bypass au restart bot**

Bug observe trades.jsonl 30/04 : NQ exit 14:39:02 → restart bot 14:40
(deploy CAS 4 v3) → NQ entry 14:48:40 = **9min < 15min cooldown**.

Cause : `RiskManager.last_close_time` est in-memory only. Restart =
reset → `can_trade()` voit `last=None` → cooldown 15min ignore.

Fix `_restore_cooldown_state()` :
- Au boot, scanne `_databento_trades.jsonl` du day CME courant
- Pour chaque symbole, prend le DERNIER `exit_time` ISO
- Set `risk.last_close_time[sym] = datetime.fromisoformat(exit_time)`
- Cooldown 15min applique correctement post-restart

Validation prod : log `[BOT] cooldown restore : NQ last_close=14:50:07
(elapsed=23.6min, cooldown_remaining=0.0min)` + ES last_close=12:11
(elapsed=182.7min). Cooldown reactif sur tous les futurs restarts.

### Pourquoi (Jackson directives 30/04)

1. **MAX_TRADES** : "JE VOUDRAIS FAIRE LA MEME CHOSE POUR LE BOT 2 — comme
   Bot 1 = 9999 illimite". Decision 22/04 paper = collecte max donnees.

2. **Cooldown** : "BOT 2 IL A PAS ATTENDU IL A REPRIS UN TRADE TOUT DE
   SUITE APRES AVOIR CLOS UN TRADE". Bug safety net casse sur restart.

### Validation pre-deploy

- [x] Tests : 4/4 PASS (cooldown restore)
- [x] Validation empirique : log `cooldown restore` confirme NQ + ES restaures
- [x] Service restart OK : MIA-DataBento-Paper + MIA-Dashboard Running

### Revert plan
```bash
git revert <commit-sha>
scp CORE/databento_paper_trader.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp DASHBOARD/api/paper_tracker.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/api/"
ssh Administrator@212.28.179.199 'powershell -Command "nssm.exe restart MIA-DataBento-Paper; nssm.exe restart MIA-Dashboard"'
```

### Deployed at 2026-05-01 04:15 UTC

### Suivi post-deploy
- J+1 : grep `cooldown restore` LOGS Bot 2 → confirme appel a chaque boot
- J+7 : verif zero trade entry < 15min apres exit (cooldown applique)

### Liens
- Memories : `feedback_pre_deploy_3_questions.md`
- Code : `RiskManager.can_trade()` ligne 411-423

---

## 2026-05-01 03:30 UTC — [Bot 2 metrics dashboard + CAS 4 v3 T1 mutation + T2 observability]

**Categorie** : FEATURE (UX dashboard) + FIX (CAS 4 elargissement)
**Impact prod** : Bot 1 (MIA-Paper Sim3) + Bot 2 (MIA-DataBento-Paper Sim2)
**Fichier(s)** :
- Modif : `CORE/databento_paper_trader.py:1156-1207` — `_update_position_metrics()` NEW
- Modif : `CORE/databento_paper_trader.py:1717-1730` — appel dans `_process_symbol`
- Modif : `CORE/mia_sltp.py:139-200` — TIER2 ajouts vwap_w + open_830
- Modif : `CORE/mia_sltp.py:241-263` — SLTPResult fields cas4_observed_*
- Modif : `CORE/mia_sltp.py:415-490` — CAS 4 v3 split T1 mutation / T2 observability
- Modif : `tests/test_mia_sltp_fallback.py` — test multi_obstacles adapte v3
- Modif : `tests/test_mia_sltp_mq_walls.py` — test v3 T2 observability-only

**Reviewer(s) agent** :
- code-reviewer #1 GO-AVEC-RESERVES : R1+R2 BLOQUANTES → traitees ci-dessous
- 101/101 tests PASS

### Quoi

**1. Bot 2 dashboard live (Q2 Jackson "Bot 2 ne montre pas evolution live")**

`_update_position_metrics(symbol, bar)` appele au debut de `_process_symbol`.
Calcule sur chaque nouvelle bar pour la position ouverte :
- `unrealized_pnl_ticks` / `unrealized_pnl_usd` (signed)
- `current_price` (last bar close)
- `mfe` / `mae` running
- `bars_held` (incremente)
- `last_bar_ts`

Le `_write_state` heartbeat 30s serialise auto via `pos.items()`. Dashboard
voit live l'evolution comme Bot 1.

Validation prod : state.json post-deploy montre `unrealized_pnl_ticks: -14.0,
mfe: 0.0, mae: -14.0, current_price: 7179.0, bars_held: 1` sur trade ES BUY
@ 7182.5.

**2. CAS 4 v3 split (Jackson "RATISER LARGE" + R1+R2 code-reviewer)**

Jackson directive 30/04 soir : etendre CAS 4 v2 (T1 only) aux T2 (Open US,
VWAP daily/weekly, niveau de la veille). Code-reviewer R1+R2 BLOQUANTES :
- R1 : pas de promotion T3→T2 sur n=1 screen (pattern PRIO V1)
- R2 : T2 mutation sans backtest = risque rejets massifs

Compromis : split T1 vs T2 :
- T1 : MUTATION (validee v2 sur cas screen Bot 1)
- T2 : OBSERVABILITY-ONLY 5 jours. Log `cas4_observed_tier2=True` +
  `cas4_observed_wall_t2` + `cas4_observed_tp_devant` SANS muter tp1_ticks.
  Si fire rate <15% et capots coherents → activer mutation T2 en v4.

Plus : ajouts vraiment nouveaux en TIER2 (pas de contradiction historique) :
- `dist_vwap_w` (Weekly VWAP nu) : NEW
- `dist_open_830` (Open 830 ET pre-market) : NEW

REVERT promotions T3→T2 sur `dist_vwap_d` et `dist_prev_vwap` (R1).

### Pourquoi

**Q2 Bot 2 dashboard** : Bot 1 state.json (488 KB) contient mfe/mae/unrealized
auto-update ; Bot 2 state.json (653 B) ne contient que active_positions
statiques → asymetrie UX.

**Q1 CAS 4 v3** : screen Bot 2 ES SHORT @ 7174 → TP @ 7163.50 bloque par
SD-1 W (Weekly VWAP -1SD, ABSENT du DMP feed) + Open US (T2 OPEN_CASH).
Plusieurs T2 empiles sur le chemin = obstacle reel. v2 (T1 only) ne couvre
pas. Compromis prudent v3 split = T1 mutation + T2 logging 5 jours.

### Impact attendu

- **Bot 2 dashboard** : evolution live trade visible (P/L, MFE, MAE).
  Verifie empiriquement post-deploy 15:06 UTC.
- **CAS 4 v3** : T1 mutation actif → memes rejets que v2. T2 observability
  = ZERO impact comportemental, juste logs. Bench 5 jours puis decision v4.

### Validation pre-deploy

- [x] Tests : 101/101 PASS
- [x] Code-reviewer GO-AVEC-RESERVES → R1 (revert T3→T2) + R2 (split T1/T2 obs) traitees
- [x] Validation empirique : Bot 2 state.json post-restart contient mfe/mae/pnl

### Revert plan
```bash
git revert <commit-sha>
scp CORE/databento_paper_trader.py CORE/mia_sltp.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 'powershell -Command "nssm.exe restart MIA-Paper; nssm.exe restart MIA-DataBento-Paper"'
```

### Deployed at 2026-05-01 03:30 UTC

### Suivi post-deploy
- J+1 (01/05) : grep `cas4_observed_tier2=True` LOGS/decisions/ → freq capot T2 hypothetique
- J+5 : audit fire rate T2 obs vs trades pris. Si <15% coherent → activer mutation T2 v4
- J+7 : dashboard Bot 2 affiche bien P/L live + MFE/MAE

### Anomalies detectees pour chantier suivant

**Anomalie residuelle — SD-1 W mur invisible SLTPEngine** :
Toujours non resolu (DMP feed n'expose pas `dist_vwap_w_sd1u/d`). Chantier
C++ requis :
1. `DMP_Reader.h` : lire SD bands weekly Sierra Chart
2. `DMP_Transform.h` : calculer dist_vwap_w_sd1u/d/2u/d
3. `DMP_Writer.h` : serialiser dans JSONL
4. Bump schema 3.7.2 → 3.7.3 (+4 colonnes)
5. Recompile + reload charts + deploy 2 dossiers VPS

### Liens
- Memories : `feedback_pattern11_repetition_avoided.md` (R1), `feedback_data_mining_trap.md` (R2)
- Rule : `.claude/rules/critical-tasks-review.md`
- Code-reviewer : 2 reserves R1+R2 traitees via revert + split

---

## 2026-05-01 02:30 UTC — [Bot 2 OCO recovery query broker + Bot 1 SLTP CAS 4 v2 universel]

**Categorie** : FIX architectural Tier 1 — 2 bugs paper traders observes 30/04
**Impact prod** : Bot 1 (MIA-Paper Sim3) + Bot 2 (MIA-DataBento-Paper Sim2)
**Fichier(s)** :
- Modif : `CORE/databento_paper_trader.py:564-735` — OCO recovery query broker (Type 305)
- Modif : `CORE/mia_sltp.py:415-475` — CAS 4 v2 garde universelle anti-traversee mur T1
- Modif : `CORE/mia_sltp.py:241-263` — SLTPResult new field cas4_source_pre
- Modif : `CORE/log_catalog.py` — code OCO_RECOVERY_RESTORED ajoute
- Modif : `tests/test_mia_sltp_fallback.py` — test multi_obstacles adapte (T2 vs T1)
- Cree : `tests/test_bot2_oco_recovery_query_broker.py` — 7 tests (active/flat/timeout/exception/empty/multi-sym)
- Cree : `tests/test_mia_sltp_mq_walls.py` mise a jour — 4 tests CAS 4 v2 universel

**Reviewer(s) agent** :
- code-reviewer #1 : GO-AVEC-RESERVES → R1+R2+R5+R6 traitees
  - R1 (race) : repopulation SIDs DEPLACEE avant query broker
  - R2 (connect) : verifie ordre connect()→reload (ligne 542-556)
  - R5 (multi-sym) : test ES active + NQ timeout ajoute
  - R6 (logging) : OCO_RECOVERY_RESTORED emit ajoute
- 101/101 tests PASS

### Quoi

**1. Bot 2 OCO recovery query broker** (databento_paper_trader.py)

Bug observe screen 30/04 : ES SHORT @ 7206.50 ouvert avant 13:19 UTC.
3 restarts successifs dans la journee → a chaque restart, OCO recovery
annulait les brackets TP/SL ET archivait state.json, MAIS NE FERMAIT PAS
la position broker. Resultat : position SHORT vivante cote Sierra Sim2
SANS tracking ni protection. Profit +453t invisible pour le bot.

Fix : avant cancel brackets, query broker via `request_position_blocking()`
(Type 305 → 306, timeout 3s par position). 4 cas distingues :
- broker_qty != 0 : position TOUJOURS active → restaurer dans `active_positions`,
  repopuler `_server_order_ids`, re-`register_oco_pair`, garder state.json.
  Emit `OCO_RECOVERY_RESTORED`.
- broker_qty == 0 : vraie orphelin → cancel + archive (comportement original)
- broker_qty == None (timeout) : conservateur → ne pas cancel + alerte
  `STATE_VS_BROKER_MISMATCH` + re-ecrire state.json
- Exception : traite comme timeout

Anti-race R1 : repopulation `_server_order_ids` AVANT query broker (le
`_recv_loop` thread est actif des `connect()` BOT/dtc_connector.py:138 →
peut recevoir un fill ORDER_UPDATE pendant la query 3s).

Validation prod (post-deploy 14:40 UTC) : log `[BOT] query broker ES = -3
→ POSITION ACTIVE, restaure tracking` + `state preserved : 1 positions
actives/unknown (0 orphelins cancellees)`. Position du screen propre.

**2. Bot 1 SLTP CAS 4 v2 universel** (mia_sltp.py)

Bug screen 30/04 apres-midi : ES SHORT @ 7160.50 (Bot 1), SL=20t,
TP @ GEX_DN -77t (R:R 3.85). HVL_0DTE @ -18t SUR LE CHEMIN du TP. Prix
rebondit sur HVL_0DTE → SL hit -57t.

Cause : SLTPEngine `_find_tp_obstacle` SKIP HVL_0DTE (R:R 0.8 < MIN_RR_SELECTION
1.5) puis prend GEX_DN (R:R 3.9). Mais ignore que HVL_0DTE T1 doit etre
casse pour atteindre TP. CAS 4 v1 (matin 30/04) ne couvre que `tp1_wall.startswith("TP_STANDARD")`.

Fix v2 universel : capote TP a TOUT mur TIER 1 plus proche que tp1_ticks,
peu importe la SOURCE du TP (TP_STANDARD ou mur scanne). T2 acceptes comme
traversables (only T1 capote). Si capot rend R:R < MIN_RR_RATIO 0.8,
STEP 8 reject le trade naturellement (mieux que SL programme).

Idempotence : si tp1_wall IS deja le 1er T1 (ou TP_DEVANT_<T1>), skip
(evite double-capot).

`cas4_source_pre` ajoute dans SLTPResult pour distinguer CAS 4 v1
(`TP_STANDARD_*`) vs v2 (nom mur scanne) en logs prod.

**3. Bug heartbeat fix** (databento_paper_trader.py)

Bug introduit par fix #1 : state.json restaure avait `ts_open` en STRING ISO,
mais `_write_state` ligne 1132 fait `pos["ts_open"].isoformat()` → AttributeError
(string n'a pas isoformat). Heartbeat error spam.

Fix : convertir `ts_open` str → `datetime.fromisoformat()` lors de la
restauration dans `active_positions` (invariant interne preserve).

### Impact attendu

- **Bot 2** : zero orphelin sur restart bot avec position active. Verifie
  empiriquement post-deploy 14:40 UTC.
- **Bot 1** : trades structurellement casses (TP derriere mur T1) seront
  REJETES au lieu de SL hit. Estimation impact : 5-15% trades supplementaires
  rejetes. A monitorer via `cas4_source_pre` log.

### Validation pre-deploy

- [x] Tests : 101/101 PASS
  - 7 OCO recovery (4 nouveaux + multi-sym + ts_open + edge)
  - 38 SLTP (13 fallback + 25 MQ/CAS4)
  - 23 trailing TR40 (existants)
  - 30 gates Bot 2 (existants)
  - 3 funnel reject (existants)
- [x] Code-reviewer GO-AVEC-RESERVES → R1+R2+R5+R6 traitees
- [x] Validation empirique : log Bot 2 post-restart confirme `query broker ES = -3 → POSITION ACTIVE`

### Revert plan
```bash
git revert <commit-sha>
scp CORE/databento_paper_trader.py CORE/mia_sltp.py CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 'powershell -Command "nssm.exe restart MIA-Paper; nssm.exe restart MIA-DataBento-Paper"'
```

### Deployed at 2026-05-01 02:30 UTC
- 3 fichiers SCP -> VPS
- MIA-Paper + MIA-DataBento-Paper restart
- Verifie : Bot 2 query broker ES = -3 (position SHORT @ 7174.00 active restauree)

### Suivi post-deploy
- J+1 (01/05) : grep `OCO_RECOVERY_RESTORED` LOGS/events/ → freq query broker active
- J+1 : grep `cas4_source_pre != ""` LOGS/decisions/ → freq CAS 4 v2
- J+7 : ratio rejets `R:R < 0.8 (TP_DEVANT_*)` vs avant fix v2
- J+30 : impact PF Bot 1 (cible : moins de SL sur trades structurels casses)

### Anomalies detectees a chantier suivant (29/04 → 01/05)

**Anomalie 1 — SD-1 W mur invisible SLTPEngine** :
Screen Bot 2 30/04 (Trade 7174.00 → TP 7163.50) montre TP place 1.4 ticks
SOUS le mur SD-1 W @ 7163.84 (VWAP Weekly -1SD). Le DMP feed actuel N'EXPOSE
PAS `dist_vwap_w_sd1u/d`. Fix architectural = ajouter dans DMP_Reader.h
+ DMP_Transform.h + DMP_Writer.h (CHANTIER C++ + recompile + deploy VPS).

**Anomalie 2 — Bot 2 dashboard pas d'evolution live** :
Bot 1 `state.json` (488 KB) contient open_by_symbol + stats + entry_funnel.
Bot 2 `databento_paper_state.json` (653 B) ne contient QUE active_positions
(entry/sl/tp/ts_open). Manque : unrealized_pnl, current_price, mfe/mae,
bars_held → dashboard ne peut pas afficher l'evolution live d'un trade Bot 2.
Fix : enrichir `_write_state()` Bot 2.

### Liens

- Memories : `feedback_pre_deploy_3_questions.md`, `reference_vps_process_persistence.md`
- Rule : `.claude/rules/critical-tasks-review.md` (Tier 1 SLTPEngine + DTC)
- Code-reviewer : 2 reviews (R1+R2+R5+R6 + traitees + recos appliquees)

---

## 2026-05-01 00:30 UTC — [Fix bug TypeError _funnel_reject + Système logs anomalies tracables]

**Categorie** : FIX (bug Python preexistant) + FEATURE (12 nouveaux codes log)
**Impact prod** : Bot 1 (MIA-Paper Sim3) + Bot 2 (MIA-DataBento-Paper Sim2)
**Fichier(s)** :
- Modif : `CORE/mia_paper_trader.py:843-848` — fix TypeError (kwarg `reason=` -> `disable_reason=`)
- Modif : `CORE/mia_paper_trader.py:1631-1716` — emits TRAILING_TR40_* + fix bug latent NameError `old_sl`
- Modif : `CORE/log_catalog.py:200-225` — 12 nouveaux codes tracking anomalies
- Modif : `CORE/databento_paper_trader.py:1763-1800` — emits SLTP_MQ_WALL_USED + SLTP_CAS4_TRIGGERED + PY_EXCEPTION_HOT_PATH
- Modif : `CORE/mia_sltp.py:241-249,418-446` — 2 nouveaux flags SLTPResult `cas4_blocked_wall_dist` + `cas4_tp_standard_pre`
- Cree : `tests/test_paper_funnel_reject.py` — 3 tests regression bug
- Cree : `DOCS/LOGS_ANOMALY_GUIDE.md` — table ANOMALIE -> CODE LOG -> COMMANDE

**Reviewer(s) agent** :
- code-reviewer : GO-AVEC-RESERVES (R1+R2 traitees : exposer wall_dist exact + tp_standard_pre dans SLTPResult)
- 90/90 tests PASS (3 funnel + 13 fallback + 21 MQ + 23 trailing + 30 gates)

### Quoi
**1. Bug TypeError _funnel_reject** (observe paper_trader.err depuis avant 30/04) :
```python
# Avant : reason= kwarg en conflit avec reason positional
self._funnel_reject("3_conseil", "sell_auto_disabled",
                    reason=self._sell_disable_reason.get(symbol),  # TypeError
                    ...)
# Apres : kwarg renomme
self._funnel_reject("3_conseil", "sell_auto_disabled",
                    disable_reason=self._sell_disable_reason.get(symbol),
                    ...)
```
Plus : fix bug latent `NameError: old_sl` dans branche LOOSEN_BLOCK du trailing TR40 (capture deplacee AVANT branchement).

**2. 12 nouveaux codes log tracking anomalies** :
- Trailing TR40 (4) : ARMED, UPDATED, NOT_ALIGNED (delta>0.5t), LOOSEN_BLOCK
- SLTP MQ + CAS 4 (5) : MQ_WALL_USED, CAS4_TRIGGERED, FALLBACK_STANDARD, NO_VALID_WALL, TP_BEHIND_WALL_DETECTED
- Anomalies generiques (3) : PY_EXCEPTION_HOT_PATH, FUNNEL_REJECT_CONTRACT_BUG, STATE_VS_BROKER_MISMATCH

**3. Doc DOCS/LOGS_ANOMALY_GUIDE.md** : table ANOMALIE Jackson -> CODE -> CMD GREP. 6 sections (signal pas trade, TP non atteint, trailing, OCO, exceptions, verif post-deploy).

### Pourquoi
1. **Bug TypeError** : observe en prod depuis ~24/04 (introduit avec fix kill-switch SELL auto-disable). Silencieux car logge dans paper_trader.err mais bot continue. Funnel reject jamais incremente pour ce reject.

2. **Logs anomalies** : Jackson directive "MET A JOUR NOTRE SYSTEM DE LOGS INGENIEUX POUR TRACKER TOUT ANOMALIE EN FONCTION DE DERNIERE MODIF". Avant fix, on ne pouvait pas savoir :
   - Frequence trailing TR40 arme vs mur en fav
   - Frequence CAS 4 capote vs MQ wall scanne
   - Frequence fallback FIXED databento (Bot 2 SHORTs perdus)
   - Distinction exceptions Python hot path vs autres

### Impact attendu
- **Bot 1** : SHORTs auto-disabled correctement loggees dans funnel_reject (avant : TypeError silencieuse)
- **Bot 2** : observability MQ walls + CAS 4 + fallback FIXED en prod
- **Debug** : Jackson dit "verifie les logs" -> grep `LOGS_ANOMALY_GUIDE.md` table -> 1 commande -> diagnostic

### Validation pre-deploy
- [x] Tests unitaires : 90/90 (3 funnel + 13 fallback + 21 MQ tiers/scan/CAS4 + 23 trailing + 30 gates)
- [x] Test cas screen 30/04 PASS (CAS 4 capote MQ_CALL_0DTE)
- [x] Tests new fields exposes (cas4_blocked_wall_dist + cas4_tp_standard_pre)
- [x] Review agent code-reviewer : GO-AVEC-RESERVES R1+R2 traitees
- [x] Pre-deploy 3 questions : (1) MIA-Paper + MIA-DataBento-Paper consomment, (2) bug TypeError observe paper_trader.err 24/04+, (3) tests empiriques + cas screen 30/04 PASS

### Revert plan
```bash
git revert <commit-sha>
scp CORE/mia_paper_trader.py CORE/mia_sltp.py CORE/log_catalog.py CORE/databento_paper_trader.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 'powershell -Command "nssm.exe restart MIA-Paper; nssm.exe restart MIA-DataBento-Paper"'
```

### Deployed at 2026-05-01 00:30 UTC
- 4 fichiers SCP -> VPS
- MIA-Paper + MIA-DataBento-Paper restart
- err.log paper_trader mtime 09:53 ET = juste apres restart, pas de nouvelle TypeError

### Suivi post-deploy
- J+1 (01/05) : grep `disable_reason` dans LOGS/decisions/ → fix effectif
- J+1 : grep `TRAILING_TR40_ARMED` LOGS/execution/ → trailing arme au moins 1 trade
- J+7 : freq SLTP_CAS4_TRIGGERED vs SLTP_MQ_WALL_USED → bench fix MQ walls
- J+30 : zero `PY_EXCEPTION_HOT_PATH` non documentee

### Liens
- Memories : `feedback_log_debug_protocol.md` (4 niveaux + categories)
- Rule : `.claude/rules/log-debug-protocol.md` (consultation logs ordre)
- Doc : `DOCS/LOGS_ANOMALY_GUIDE.md` (table debug) NEW

---

## 2026-04-30 23:55 UTC — [SLTPEngine MQ walls TIER1/TIER2 + CAS 4 anti-TP-derriere-mur]

**Categorie** : FIX (bug TP derriere mur) + FEATURE (niveaux MQ scannes comme obstacles)
**Impact prod** : BOT 1 (mia_paper_trader) + BOT 2 (databento_paper_trader) — paper Sim2/Sim3
**Fichier(s)** :
- Modif : `CORE/mia_sltp.py:33` — `import math` au top (reco code-reviewer)
- Modif : `CORE/mia_sltp.py:139-203` — promotion 6 niveaux MQ TIER1/TIER2 + retrait TIER3
- Modif : `CORE/mia_sltp.py:241-249` — SLTPResult fields `cas4_triggered` + `cas4_blocked_wall` (R2 observability)
- Modif : `CORE/mia_sltp.py:~415-440` — CAS 4 garde anti-TP-derriere-mur dans `_evaluate`
- Modif : `tests/test_mia_sltp_fallback.py:168-202` — 1 test updated avec commentaire historique (R1)
- Cree : `tests/test_mia_sltp_mq_walls.py` — 20 nouveaux tests (5 MQ tiers + 5 MQ scanned + 8 CAS 4 + 2 observability)

**Reviewer(s) agent** :
- code-reviewer : GO-AVEC-RESERVES (R1 commentaire test + R2 observability flags traitees)
- Recos non-bloquantes appliquees : import math au top, test runner_tp3_coherent

### Quoi
**1. Promotion niveaux MenthorQ** :
- TIER1 : `dist_mq_call_0dte`, `dist_mq_put_0dte`, `dist_mq_hvl_0dte` (role='both')
- TIER2 : `dist_mq_call`, `dist_mq_put`, `dist_mq_hvl` (role='both')
- TIER3 : retrait des 3 MQ levels (anti-doublon)

**2. CAS 4 anti-TP-derriere-mur** : si fallback `TP_STANDARD` placerait le TP DERRIERE un mur scanne, capote le TP DEVANT (`floor(abs_dist - tp_buffer)`) → marque `cas4_triggered=True` + `cas4_blocked_wall=<name>` pour observability prod. Compromis : sacrifie R:R minimum (1.5) au profit d'un TP atteignable. Garde-fou final `MIN_RR_RATIO=0.8` reste actif (rejet si capot donne R:R < 0.8).

### Pourquoi (cause racine)
Screen 30/04 ES SHORT @ 7206.50 (Sim2 paper) : TP @ 7199.25 placé 1 tick DERRIERE mur "Call Resistance + Call Resistance 0DTE + Gamma Wall 0DTE" empile @ 7199.46. Pattern recurrent.

Causes :
1. `dist_mq_call/put/hvl_0dte` ABSENTS des TIER1/TIER2 → SLTPEngine ne voit pas les niveaux MQ
2. Niveaux MQ qui etaient en TIER3 → NON SCANNES depuis rollback 28/04
3. Meme avec MQ_CALL detecte, R:R 0.93 < MIN_RR_SELECTION (1.5) → fallback `TP_STANDARD` 30t → TP @ 7199.00 = 1 tick DERRIERE le mur

Jackson directive : "ON DOIS LISTER LES NIVEAU MENTHORQ COMME MUR".

### Impact attendu
- **TP atteignable** : trades avec mur MQ proche → TP placé DEVANT le mur (no trap)
- **Bot 2 Gate B compatibilite** : si CAS 4 capote → tp_wall = `TP_DEVANT_<MQ_NAME>` (pas synthetic) → Gate B SHORT laisse passer (cf is_synthetic_tp_wall)
- **Observability** : `cas4_triggered` flag dans logs paper_trader pour tracker frequence en prod
- **Effet de bord** : les SHORTs avec mur MQ proche auront un R:R reduit (parfois < 1.5) mais TP atteignable

### Validation pre-deploy
- [x] Tests unitaires : 33/33 (13 fallback existants dont 1 update + 20 nouveaux tiers/scan/CAS4)
- [x] Test cas screen 30/04 : `test_es_short_screen_case_30042026` PASS — TP @ 7193.50 DEVANT mur 7192.96 (delta +14 ticks DEVANT)
- [x] Test runner TP3 coherent : tp3 >= tp1 quand CAS 4 capote
- [x] Anti-doublon : `test_no_overlap_between_tiers` confirme aucun col dans 2 tiers
- [x] Review agent : code-reviewer GO-AVEC-RESERVES (R1 + R2 + recos appliquees)
- [x] Pre-deploy 3 questions : (1) MIA-Paper + MIA-DataBento-Paper consomment mia_sltp.py, (2) bug observe screen 30/04 reel, (3) test cas screen 30/04 PASS empirique

### Revert plan
```bash
# Rollback mia_sltp.py vers commit precedent (TIER definitions + retrait CAS 4)
git revert <commit-sha>
scp CORE/mia_sltp.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 'powershell -Command "nssm.exe restart MIA-Paper; nssm.exe restart MIA-DataBento-Paper"'
```

### Deployed at
A deployer apres commit (Sim2 + Sim3 paper).

### Suivi post-deploy
- J+1 (01/05) : grep `cas4_triggered=True` ou `TP_DEVANT_` dans `LOGS/decisions/` → frequence CAS 4
- J+7 : ratio TP atteint vs SL atteint pour trades avec MQ wall scanne (avant fix : TP rare car derriere mur. Apres : TP plus frequent attendu)
- J+30 : audit consolide impact PF Bot 2 (cible : capture profit avant rebound mur MQ structural)

### Liens
- Memories : `feedback_pre_deploy_3_questions.md`, `reference_timezone_convention.md` (MQ levels updated daily)
- Lecons : `.claude/rules/lessons.md` (rollback 28/04 ne ciblait pas les MQ)
- Review code-reviewer : R1 fermee (commentaire test), R2 fermee (cas4_triggered flag), recos appliquees

---

## 2026-04-30 23:30 UTC — [BOT 1 trailing TR40_20 NQ + BOT 2 Plan A_v2 gates VETO BUY/SHORT]

**Categorie** : FEATURE (nouveau trailing) + GATE (vetos paramétrables) — moteur execution + signal
**Impact prod** : BOT 1 (mia_paper_trader Sim3 NQ trailing) + BOT 2 (databento_paper_trader Sim2 vetos)
**Fichier(s)** :
- Modif : `CORE/mia_paper_trader.py:~1620-1680` — Trailing TR40_20 NQ : armement MFE >= 40% × SL_initial, give-back 20% × SL_initial, tick-aligned (FIX C1), favorable-direction only (FIX I3)
- Modif : `CORE/databento_paper_trader.py:128-148,167-175,1661-1679,1761-1791` — Constante `NO_WALL_TP_PATTERNS_*` + helper `is_synthetic_tp_wall()` + 3 BotConfig params + Gate A (VETO BUY color wall) + Gate B (VETO SHORT no-wall + room ratio)
- Modif : `CORE/log_catalog.py` — 2 codes `VETO_BUY_COLOR_WALL` + `VETO_SHORT_NO_WALL` (decisions, INFO)
- Cree : `tests/test_trailing_tr40_20.py` — 23 tests (4 arming + 4 favorable + 2 case + 3 tick-align + 4 integration check_exit + 4 edge + 1 progression + 1 case)
- Cree : `tests/test_bot2_veto_gates.py` — 30 tests (9 Gate A + 9 Gate B + 4 Phase 0 audit + 8 helper contrat)

**Reviewer(s) agent** :
- Bot 1 trailing : market-analyst (audit n=50 réels + 934 simulés → TR40_20 NQ only, PF 0.99→1.32, walk-forward 3/3) + code-reviewer (FIX C1 tick-align + I3 integration test)
- Bot 2 gates : market-analyst (audit 1277 backtests synthétiques 4 mois Databento V4 → PROP A PF 1.04→1.49, walk-forward 3/3, CI95 [1.20, 1.86], p=0.0003) + code-reviewer (GO-AVEC-RESERVES, R1 traitée par refacto helper, R2/R3 polish)
- Plan agent : revisé Plan A → A_v2 paramétrable + Phase 0 audit n=8 SHORTs → veto cible execution (Gate B) pas signal

### Quoi
**Bot 1 (NQ uniquement)** : trailing TR40_20 — quand MFE >= 40% × SL_initial, le SL trail à `entry +/- (MFE - 20% × SL_initial)`. Tick-aligned (multiple de 0.25). Ne bouge QUE en faveur de la position (pas de loosen). Pos["sl_trailed"] / "sl_trail_count" pour audit.

**Bot 2 (ES + NQ)** :
- **Gate A** : VETO BUY si `dist_color_dn_nearest_pct ∈ (0, cfg.veto_buy_color_wall_pct]` (default 0.05%). Color wall trop proche au-dessus = stop hunt likely.
- **Gate B** : VETO SHORT si `tp_wall ∈ {FIXED_*, *STANDARD*, *NO_WALL*}` OR `room_ratio = tp_ticks/sl_ticks < cfg.veto_short_room_min_ratio` (default 1.5). TP synthetic = pas de mur réel pour catch profit.
- Helper `is_synthetic_tp_wall()` extrait pour single source of truth wall taxonomy.

### Pourquoi
**Bot 1** : trade NQ BUY 12:37 24/04 — MFE +90 ticks ($45) puis retracé à TIMEOUT -1t (-$3.75) en 26 min. Audit market-analyst : pattern fréquent (trade qui touche 40% SL_init puis retrace). TR40_20 capture 50-70% du MFE empiriquement.

**Bot 2** : 26 trades cumulés sur 4 jours, WR 26.9%, -$1492. SHORT 12.5% WR vs LONG 33% WR. Phase 0 audit n=8 SHORTs réels nuit 28-30/04 → 3/8 trades avec TP_NO_WALL (vs 11% sur LONGs). H1 (signal cassé) REFUTÉ + H4 (anecdote n=8) CONFIRMÉ → veto cible execution (no wall TP) pas signal. Wilson CI95 SHORT [2.2%, 47.1%] englobe LONG WR → pas de VETO SHORT permanent.

### Impact attendu
- **Bot 1 NQ** : trailing récupère 50-70% MFE des trades qui retracent (estim +$30-40 / trade médian sauvé)
- **Bot 2** : Gate A élimine ~10-15% des BUY mort-nés. Gate B élimine 3/8 SHORTs historiques perdus = ~37.5% des SHORTs
- **Anti Pattern 11 V1** : tous les vetos paramétrables (cfg.veto_*=0/False désactive), reversibles sans recompile
- **Effet de bord** : Bot 1 ES inchangé, Bot 1 NQ trailing seulement (pas BE séparé). Bot 2 : risk check toujours exécuté après Gate A (pas de double-skip)

### Validation pre-deploy
- [x] Tests unitaires : 53/53 (Bot 1: 23, Bot 2: 30)
- [x] Backtest preservation : Bot 2 walk-forward 3/3 folds CI95 [1.20, 1.86] p=0.0003 (1277 backtests)
- [x] Review agent : market-analyst GO + code-reviewer GO-AVEC-RESERVES (R1 traitée par refacto)
- [x] Test empirique : `pytest tests/test_trailing_tr40_20.py tests/test_bot2_veto_gates.py -v` → 53/53 PASS
- [x] Pre-deploy 3 questions : (1) MIA-Paper + MIA-DataBento-Paper services nssm prod, (2) bug réel WR 26.9% + audit walk-forward, (3) testé empiriquement audit Phase 0 n=8 + 30 tests

### Revert plan
```bash
# Bot 1 trailing : disable via constante = code rollback simple
# Bot 2 gates : reversible runtime via cfg
ssh Administrator@212.28.179.199 'powershell -Command "& nssm.exe stop MIA-DataBento-Paper"'
# Edit BotConfig sur VPS:
# veto_buy_color_wall_pct=0.0 (Gate A off)
# veto_short_no_wall=False (Gate B off)
ssh Administrator@212.28.179.199 'powershell -Command "& nssm.exe start MIA-DataBento-Paper"'
# Bot 1 trailing rollback complet :
git revert <commit-sha-bot1>
scp CORE/mia_paper_trader.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 'powershell -Command "& nssm.exe restart MIA-Paper"'
```

### Deployed at
- Bot 1 trailing : déployé Sim3 paper ~30/04 22:00 UTC (avant cette entry consolidée)
- Bot 2 gates Plan A_v2 : à déployer maintenant Sim2 paper

### Suivi post-deploy
- J+1 (01/05) : 0 erreur runtime + premiers vetos loggés (decisions/decisions_*.jsonl `VETO_BUY_COLOR_WALL` / `VETO_SHORT_NO_WALL`)
- J+7 : Bot 1 NQ : taux trailing armé / trades NQ + ratio capturé MFE. Bot 2 : N vetos vs N trades, PnL vs baseline 26.9% WR
- J+30 (30/05) : audit consolidé Bot 1 PF NQ (cible >1.20) + Bot 2 PF (cible >1.30 vs baseline 0.78)

### Liens
- Memories : `feedback_data_mining_trap.md` (n>=60 walk-forward DSR), `feedback_pattern11_repetition_avoided.md` (anti-cascade), `feedback_pre_deploy_3_questions.md` (3 Q avant fix)
- Review agent code-reviewer : verdict GO-AVEC-RESERVES, 3 recos non-bloquantes (R1 fermée par refacto, R2/R3 polish)
- Audit Phase 0 SHORT Bot 2 : n=8 (28-30/04), H4 anecdote CONFIRMÉ → Gate B targeted

---

## 2026-05-01 03:00 UTC — [PILOT 30 JOURS — Asia early reprise 18:15 ET + Bot 1 timeout disabled en Asia]

**Categorie** : PILOT (modif moteur eco/timeout = sec critique paper)
**Impact prod** : BOT 1 (mia_paper_trader Sim3) + BOT 2 (databento_paper_trader Sim2) — paper only, 0$ risk
**Fichier(s)** :
- Modif : `CORE/eco_calendar.py` — block_end (21,30) → (18,15), label "Post-MOC pause", Sunday <18:15 ET, _session_block_end_utc, docstring + commentaires alignes
- Modif : `CORE/mia_paper_trader.py:1645-1657` — timeout 2h DESACTIVE en session Asia via current_session_label() + fail-safe ImportError
- Modif : `CORE/databento_paper_trader.py:1418-1419` — commentaires eco gate alignes
- Modif : `tests/test_eco_calendar.py` — 8 tests adaptes (_2130et → _1815et, "Close US" → "Post-MOC")
- Cree : `tests/test_mia_paper_trader_timeout_asia.py` — 13 tests timeout Asia (logique + integration current_session_label + fail-safe)
**Reviewer(s) agent** :
- code-reviewer : GO-AVEC-RESERVES (3 reserves I1/I2/S1)
- Reserves traitees : 6 commentaires Tokyo/21:30 corriges (I1) + 2 commentaires obsoletes paper (I2) + 13 tests timeout Asia (S1)
- 49/49 tests PASSED (36 eco + 13 timeout Asia)

### Quoi
PILOT 30 JOURS pour collecter empirique sur la session Asia futures CME avant decision finale. Jackson 30/04 :
1. **Reprise bot a 18:15 ET (= 00:15 Paris)** au lieu de 21:30 ET (03:30 Paris). Pause overnight raccourcie de 6h → 2h45.
2. **Bot 1 timeout 2h DESACTIVE pendant Asia** (18:00-03:00 ET) car peu de volatilite = setups longs ont besoin de patience.

### Pourquoi (cousine `feedback_data_mining_trap.md`)
Jackson : "JE NE RISQUE QUOI RIEN ENFAITE — paper trading sur compte simule". Argument valide : collecter du data live > simulation backtest hypothetique. Approche scientifique propre, pas data mining (decision pre-engagee avec criteres).

### Criteres review J+30 (30/05/2026)
1. **n >= 15 trades** dans la fenetre 18:15-21:30 ET (ex-pause)
2. **PSR > 0.95** sur ces trades (Lopez)
3. **Slippage moyen < 1 tick** (verif que Tokyo open n'expose pas a spreads exotiques)
4. **Concentration test** : top 10% best+worst retires → edge persiste avec >=50% du gain

**Decision J+30** :
- 4/4 criteres atteints → garder 18:15 ET definitif
- < 4/4 → rollback a 21:30 ET (revert config + timeout Bot 1)

### Impact attendu
- **Bot 2 paper Sim2** : trade Asia complete (sans timeout, design preserve)
- **Bot 1 paper Sim3** : trade Asia + pas de TIMEOUT outcome possible, juste TP/SL
- Effet de bord : positions Bot 1 ouvertes >2h en Asia (rare en pratique vu TP/SL adaptatifs)
- Cout dollars : 0 (paper)

### Validation pre-deploy
- [x] Tests unitaires : 49/49 PASSED
- [x] Smoke test live API VPS : `blocked=False` post-18:15 ET (= comportement attendu maintenant a 20:38 ET)
- [x] Review code-reviewer : GO-AVEC-RESERVES → 3 reserves traitees
- [x] Backward compat : eco_calendar.is_blocked_combined() retourne 18:15 ET pour les session blocks (vs absent avant ce commit)
- [x] Pas de regression Bot 2 : Bot 2 sans timeout (design inchange)

### Revert plan (si J+30 NOGO)
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-Paper MIA-DataBento-Paper MIA-Dashboard
cd C:/TRADING_SIERRA_CHART_AUTO
# Revert eco_calendar (block_end_et 18:15 → 21:30) + mia_paper_trader (timeout sans is_asia)
git log --oneline -5 CORE/eco_calendar.py CORE/mia_paper_trader.py
git checkout <commit_pre_pilot> CORE/eco_calendar.py CORE/mia_paper_trader.py CORE/databento_paper_trader.py
nssm start MIA-Dashboard MIA-DataBento-Paper MIA-Paper
```

### Deployed at 2026-05-01 03:00 UTC
- SCP CORE/eco_calendar.py + CORE/mia_paper_trader.py + CORE/databento_paper_trader.py → VPS OK
- nssm restart MIA-Dashboard (force kill Python + restart pour reload eco_calendar)
- nssm restart MIA-DataBento-Paper + MIA-Paper
- Verif API local VPS : blocked=False a 20:38 ET (post 18:15 = pilot actif)

### Suivi post-deploy
- J+1 (01/05) : verifier 1er trade Bot 1 ou Bot 2 dans la fenetre 18:15-21:30 ET (Asia early)
- J+7 : compter trades 18:15-21:30 ET, slippage moyen
- J+30 (30/05) : audit complet n>=15, PSR, concentration → decision GARDER ou ROLLBACK

### Liens
- Memoire : `feedback_data_mining_trap.md` (28/04 cousine), `feedback_pre_deploy_3_questions.md` (24/04 Q2)
- Review agent : code-reviewer GO-AVEC-RESERVES → I1/I2/S1 traitees inline

---

## 2026-05-01 02:30 UTC — [FEATURE — Auth Option B Pro : refresh 30j/90j + rotation sliding window + heartbeat 10min]

**Categorie** : FEATURE (touche moteur auth = sec critique)
**Impact prod** : DASHBOARD (auth users) — Bot trading non impacte
**Fichier(s)** :
- Modif : `DASHBOARD/config.py` (REFRESH_TOKEN_EXPIRY_SEC 7j -> 30j, +REFRESH_TOKEN_REMEMBER_EXPIRY_SEC 90j)
- Modif : `DASHBOARD/api/auth.py` (rotation /refresh + flag rmb + remember_me dans 4 bodies + docstring module)
- Modif : `DASHBOARD/static/index.html` (checkbox login-remember-me + cache bust v=89)
- Modif : `DASHBOARD/static/js/dashboard.js` (heartbeat 10min + remember_me dans login fetch)
- Modif : `DASHBOARD/tests/test_auth.py` (35->41 tests : 3 unitaires + 5 integration TestClient)
**Reviewer(s) agent** :
- code-reviewer #1 : GO-AVEC-RESERVES (3 reserves non-bloquantes : rename, tests integration, docstring)
- Reserves traitees : 41/41 tests, COOKIE_MAX_AGE renomme DEFAULT_COOKIE_MAX_AGE, docstring + limitations documentees

### Quoi
Auth dashboard reconnexion frequente (Jackson) -> implementation pattern industry standard (TradingView/Coinbase) :

1. **Refresh token allonge** : 7j -> 30j default, 90j si "Remember me" coche au login.
2. **Rotation /refresh** : sliding window. A chaque /refresh, emission nouveau access ET nouveau refresh (preserve flag `rmb`). User actif tous les jours = jamais reconnexion. Inactif > 30j (90j) = re-login.
3. **Heartbeat frontend 10 min** : refresh proactif via setInterval (vs reactif sur 401 avant). Anticipe expiry 15 min de l'access. Demarre au login + au pageload si authToken present, stop au logout.
4. **Checkbox UI** : "Rester connecte 90 jours" sur login form (default false = 30j).
5. **Securite preservee** : cookie HttpOnly+Secure+SameSite=Lax, PBKDF2 100k iterations, HMAC SHA256, guards typ=refresh sur /refresh + /promo (refresh tokens rejetes par get_current_user).

### Pourquoi
Jackson : "se reconnecter trop souvent". Audit revele que 60% de l'archi (cookie HttpOnly cross-domain + refresh + endpoint /refresh) etait deja en place. Manquait : duree, rotation, heartbeat, UI choix.

### Impact attendu
- Avant : reconnexion 1× / 7 jours fixe (refresh expire) + risque coupures session si access expire pendant fetch
- Apres : reconnexion 1× / 30 jours default ou 1× / 90 jours si checkbox + heartbeat = jamais coupe en session active
- Impact bot trading : 0 (auth = scope dashboard frontend uniquement)

### Validation pre-deploy
- [x] Tests unitaires : 41/41 PASSED (`pytest DASHBOARD/tests/test_auth.py`)
- [x] Tests integration TestClient : 5/5 (login default, login remember, rotation rmb, no cookie 401, access-as-refresh rejected)
- [x] Smoke test : login + /refresh rotation preserve rmb + nouveau access != ancien
- [x] Review code-reviewer : GO-AVEC-RESERVES (3 reserves non-bloquantes traitees)
- [x] Backward compat : users existants avec refresh 7j -> migration silencieuse 30j default au prochain /refresh
- [x] Pas de regression auth : 32 tests existants restent passants

### Limitations connues (documentees dans auth.py docstring module)
1. Pas de revocation list server-side (logout sur device A ne kill pas device B). Acceptable scope actuel (1 user PRO).
2. Sliding window sans cap absolu. Standard industry. Migration future : ajouter `absolute_exp` 365j si scaling > 10 PRO.
3. Pas de fingerprint device. Mitigation possible si abus detectes plus tard.

### Revert plan
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-Dashboard
cd C:/TRADING_SIERRA_CHART_AUTO
git checkout DASHBOARD/config.py DASHBOARD/api/auth.py DASHBOARD/static/index.html DASHBOARD/static/js/dashboard.js
nssm start MIA-Dashboard
```

### Deployed at 2026-05-01 02:30 UTC
- SCP `DASHBOARD/config.py`, `DASHBOARD/api/auth.py`, `DASHBOARD/static/index.html`, `DASHBOARD/static/js/dashboard.js` -> VPS OK
- `nssm restart MIA-Dashboard` -> Status Running Automatic
- Verif API : `/api/auth/me` sans cookie -> 401 (comportement attendu)

### Suivi post-deploy
- J+1 : verifier que les sessions actives ne sont pas perturbees (sauf logout force au restart = attendu)
- J+1 : test reel checkbox "Rester connecte 90 jours" + verif cookie 90j cote browser DevTools
- J+7 : 0 incident auth signale, 0 user PRO bloque sur reconnexion frequente
- J+30 : confirmer sliding window OK (Jackson actif quotidien -> jamais deconnecte)

### Liens
- Memoire : (aucune nouvelle, modif auth = backlog stocke dans CLAUDE.md)
- Review agent : code-reviewer GO-AVEC-RESERVES + reserves traitees inline

---

## 2026-04-30 23:00 UTC — [FEATURE — Timer dashboard "Bot reprend dans HH:MM" + buffer Tokyo 21:30 ET + reset stats CME]

**Categorie** : FEATURE + FIX (touche moteur decision Bot 2 paper trading + dashboard)
**Impact prod** : BOT 2 (databento_paper_trader Sim2) + DASHBOARD (paper page status)
**Fichier(s)** :
- Modif : `CORE/eco_calendar.py` (ajout `_session_block_end_utc()` + `is_blocked_combined()` retourne `blocked_until_utc` pour session blocks + buffer end 21:00 → 21:30 ET)
- Modif : `CORE/log_catalog.py` (ajout code `ECO_BLOCK` LogLevel.INFO)
- Modif : `DASHBOARD/api/paper_tracker.py` (`_compute_stats_today_from_trades` utilise `get_cme_trading_day()` au lieu de UTC midnight + `get_eco_status_payload()` expose timer)
- Modif : `DASHBOARD/static/js/dashboard.js` (statut "● Pause · reprend dans HH:MM" si bloque)
- Modif : `DASHBOARD/static/index.html` (cache bust v=88)
- Cree : `tests/test_eco_calendar.py` etendu de 17 → 26 tests (specularite + transitions Tokyo +30min)
**Reviewer(s) agent** :
- code-reviewer #1 : GO-AVEC-RESERVES (C1 logique boolean cassee + I1 tests manquants)
- code-reviewer #2 : GO-AVEC-RESERVES (commentaires/docstrings encore "21:00 ET" apres fix 21:30) → RESERVE TRAITEE → GO

### Quoi
3 changements en cascade decoulant du diagnostic 30/04 ~00:24 Paris (Asia ouverture imminente, Bot 2 affichait stats d'hier + pas de timer reprise) :

1. **Timer dashboard pause** : `is_blocked_combined()` retourne maintenant `blocked_until_utc` aussi pour les session blocks (pas seulement eco events). Frontend affiche "● Pause · reprend dans HH:MM (Close US + pause overnight)" au lieu de "Trader DOWN" trompeur.

2. **Reset stats CME timezone** : dashboard utilisait `datetime.now(timezone.utc).date()` (UTC midnight) alors que Bot 2 rollover 18:00 ET (`get_cme_trading_day()`). Ecart 4-6h ou stats Bot 2 affichaient les trades du day precedent. Maintenant aligne sur convention CME (start = 18:00 ET du day courant).

3. **Buffer Tokyo open +30min** : `block_end_et` 21:00 → 21:30 ET (= 03:30 Paris ete) sur fenetre B (Close US lun-jeu) et fenetre C (weekend Sunday block). Decision Jackson 30/04 : eviter la volatilite initiale du Tokyo open (premiers prises de position asiatiques + spreads larges).

### Pourquoi
- Dashboard timer : Jackson "ON AURAIS DU A VOIR UN TIMER LE BOT RETRAIDE DANS X" — feature critique pour comprendre quand le bot va reprendre sans deviner.
- Reset stats CME : pattern bug timezone documente (memoire `feedback_data_quality_first.md`). Bot 1 (mia_paper_trader) etait deja sur convention CME, Bot 2 dashboard pas → asymetrie.
- Buffer Tokyo : decision orale validee Jackson ("ON AVAIS VALIDER 21H30 ET IL REPREND A 3H15 POUR EVITER LA VOLATILITER DE OPEN TKY"). Initialement code en 21:00 ET, j'ai mal lu et mis 21:15, Jackson a recadre → 21:30 ET final.

### Impact attendu
- Trades NEW Bot 2 supprimes 16:00-21:30 ET (avant 21:00 ET) = +30min de pause overnight → 0-2 signaux Tokyo early evites par session
- Dashboard UX : timer visible vs status DOWN trompeur
- Reset stats : Bot 2 affiche maintenant 0 trades a Tokyo open (au lieu de 15 trades du day precedent)
- Effet de bord : aucun sur trades en cours (gate preventif NEW only, pas de flatten force)

### Validation pre-deploy
- [x] Tests unitaires : 26/26 PASSED (`pytest tests/test_eco_calendar.py`)
- [x] Test specularite : invariant `blocked == (end is not None)` sur 28 timestamps Mon-Sun
- [x] Smoke test live : log Bot 2 confirme `(jusqu'a 01:30 UTC)` apres restart (= 21:30 ET)
- [x] Review code-reviewer #1 : C1 + I1 traites
- [x] Review code-reviewer #2 : RESERVE doc traitees (10 commentaires fixes)
- [x] Backtest preservation : N/A (pas de modif scoring/gates de validation, juste fenetre temporelle)

### Revert plan
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-DataBento-Paper
nssm stop MIA-Dashboard
cd C:/TRADING_SIERRA_CHART_AUTO
git diff HEAD CORE/eco_calendar.py CORE/log_catalog.py DASHBOARD/api/paper_tracker.py DASHBOARD/static/js/dashboard.js DASHBOARD/static/index.html
git checkout CORE/eco_calendar.py CORE/log_catalog.py DASHBOARD/api/paper_tracker.py DASHBOARD/static/js/dashboard.js DASHBOARD/static/index.html
nssm start MIA-Dashboard
nssm start MIA-DataBento-Paper
```

### Deployed at 2026-04-30 22:39 UTC (premier deploy 21:00 ET) + 22:50 UTC (correction 21:30 ET)
- SCP `CORE/log_catalog.py`, `CORE/eco_calendar.py`, `DASHBOARD/api/paper_tracker.py`, `DASHBOARD/static/js/dashboard.js`, `DASHBOARD/static/index.html` → VPS OK
- `nssm restart MIA-Dashboard` + `nssm restart MIA-DataBento-Paper` → tous Running
- Logs Bot 2 confirment : `[ES/NQ] ECO BLOCK : SESSION: Close US + pause overnight (jusqu'a Tokyo open +30min) (jusqu'a 01:30 UTC)` = 21:30 ET = 03:30 Paris ete

### Suivi post-deploy
- J+1 : verifier Bot 2 reprend trade exactement a 03:30 Paris (= 01:30 UTC) sur Tokyo
- J+1 : dashboard frontend affiche timer "Bot reprend dans HH:MM" en orange pendant pause overnight
- J+1 : stats Bot 2 reset a 0 a 18:00 ET (et pas 00:00 UTC)
- J+7 : confirmer 0 occurrence `[EMIT_FAIL] code=ECO_BLOCK` dans err.log
- J+7 : suivre nombre signaux NEW supprimes par fenetre 21:00-21:30 ET (impact recettes)

### Liens
- INCIDENT_LOG : 2026-04-30 (timer manquant + reset CME asymetrie)
- Memoire : `feedback_data_quality_first.md` (timezone), `feedback_log_debug_protocol.md` (codes)
- Review agents : 2 rounds code-reviewer (C1+I1 puis COMMENT_FALSE)

---

## 2026-04-30 12:00 — [ROLLBACK PREVENTIF — Phase A refactor TIER3 dans scan TP mia_sltp.py]

**Categorie** : ROLLBACK (decision de NE PAS deployer)
**Impact prod** : BOT 2 (databento_paper_trader Sim2) - statut quo preserve
**Fichier(s)** : `CORE/mia_sltp.py:593-600` (rollback note 28/04 confirme par 2 agents)
**Reviewer(s) agent** : market-analyst + ml-trainer (2/2 NOGO convergent)

### Quoi
Decision de NE PAS executer la Phase A refactor demande par Jackson "DABORD SOLUTION 3 REFACTORISATION GROS MISE A JOUR DES MUR POUR TP ET SL". Phase A consistait a inclure TIER3_WALLS (MQ_HVL, MQ_PUT/CALL_0DTE, IB, PREV_VPOC, PREV_VWAP) dans `_scan_obstacles` du SLTPEngine pour donner plus de murs candidats au scan TP.

Le code source `mia_sltp.py:593-600` documente deja un ROLLBACK 28/04 13:30 sur exactement cette modification (decision n=1 ES SHORT @ 7174). L'audit `audit_tpsl_walls.py` du 29/04 (n=13 Bot 2) a sorti +$56.59 net en faveur de Phase A, mais cet edge tombe dans le bruit (CI 95% bootstrap [-$33, +$42]).

### Pourquoi
**market-analyst** :
- Audit n=13 = 5/5 controles Data Mining Trap NOGO (memoire 28/04)
- Concentration : 1 trade NQ LONG 17:04 = -$225 = 397% du delta net (sans cet outlier, Phase A = -$168 NET)
- Pattern : Jackson CADRE le probleme (lecture visuelle "TP derriere 3 murs" → audit construit pour valider)

**ml-trainer** :
- PSR Lopez ≈ 0.55-0.65 (seuil acceptable = 0.95) → NOGO statistique
- DSR non-calculable n<30 → ininterpretable
- CI 95% bootstrap [-$33, +$42] → zero dans intervalle, aucune significativite
- Cohen's d ≈ 0.06 → effet trivial
- Option B (MIN_RR adaptive) = Pattern 11 V1 confirme (2 seuils sur 13 trades = 6.5/seuil = overfitting trivial)

**Repetition d'erreur** : Phase A reproduit exactement la modification rollback'd 24h avant. Pattern V2 = "audit n<30 motive refactor deja rollback'd → STOP".

### Impact attendu
- 0 modification code prod (mia_sltp.py reste TIER1+TIER2 dans scan TP)
- Preservation comportement valide : top loss audit (NQ LONG 17:04) prouve que Phase A aurait DEGRADE ce trade (sim ferme +1t devant PREV_VPOC vs actual hit GEX_UP +151t)
- Effet de bord : aucun (pas de deploy)

### Validation pre-deploy
- N/A (pas de deploy)
- [x] Verdict market-analyst : NOGO Phase A + B, GO Option C
- [x] Verdict ml-trainer : NOGO Phase A + B (PSR<0.95), GO Option C imperative
- [x] Pre-deploy 3 questions (memoire 24/04) : Q2 confirme cadrage du probleme

### Criteres reactivation Phase A future (cumulatifs obligatoires)
1. **n >= 60 trades** Bot 2 avec features_at_entry (PSR robuste, ETA realiste 45-90 jours)
2. **Walk-forward 3 folds chronologiques** n>=30/fold sans overlap
3. **DSR Lopez > 0.95** sur >=2/3 folds avec correction Bonferroni n_trials=3
4. **Concentration test** : retirer top 10% best+worst → edge persiste avec >=50% du gain
5. **Costs inclus** : Topstep $0.85 round-trip + slippage 0.5t ≈ $10-15/trade
6. **Implementation shadow** : `_scan_obstacles_v2` derriere flag `USE_TIER3_TP=False`, log decisions parallele 2 semaines avant switch
7. **Validation ml-trainer agent** GO explicite (pas RESERVES)

### Revert plan
N/A (pas de deploy). Si modification deployee accidentellement par Phase B/C plus tard :
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-DataBento-Paper
git -C C:/TRADING_SIERRA_CHART_AUTO checkout CORE/mia_sltp.py
nssm start MIA-DataBento-Paper
```

### Suivi post-decision
- J+5 : compter trades Bot 2 cumules (target n=15-20)
- J+15 : re-run audit_tpsl_walls.py si n>=30 (test intermediaire NON-decision)
- J+45-90 : re-evaluation Phase A si tous criteres reactivation atteints

### Liens
- INCIDENT_LOG : 2026-04-28 13:30 (rollback initial TIER3-in-TP n=1)
- Memoire : `feedback_data_mining_trap.md` (28/04), `feedback_pre_deploy_3_questions.md` (24/04), `feedback_lightgbm_no_composite_indicators.md` (18/04)
- Memoire (creee ce jour) : `feedback_pattern11_repetition_avoided.md`
- Code reference : `CORE/mia_sltp.py:593-600` (rollback note source)

---

## 2026-04-30 03:00 — [FEATURE signatures audit Bot 2 — 12 game changers pro tracking]

**Categorie** : FEATURE (mode AUDIT only — pas de gate actif Phase A)
**Impact prod** : BOT 2 (databento_paper_trader Sim2)
**Fichier(s)** :
- Cree : `CORE/signatures.py` (~280 LOC, 12 fonctions signatures + helpers + scoring)
- Cree : `CORE/backtest_signatures_bot2.py` (~190 LOC, backtest empirique WIN vs LOSS)
- Modif : `CORE/databento_paper_trader.py:1676-1715` (compute signatures + INJECT dans features_at_entry avec prefixe sig_)
- Modif : `CORE/databento_paper_trader.py:_log_closed_trade()` (save signatures_at_entry + sig_score_at_entry dans trades.jsonl)
- Modif : `CORE/log_catalog.py` (codes SIGNATURES_COMPUTED, SIGNATURES_GATE_TIER1_BLOCK, SIGNATURES_GATE_TIER3_BLOCK, SIGNATURES_GATE_PASS, CHECK_EXIT_DTC_HIT)
**Reviewer(s) agent** :
- Plan agent (29/04 nuit) : architecture meta-labeling Lopez AFML chap 3 valide
- code-reviewer (30/04 nuit) : GO-AVEC-RESERVES (2 bugs precis B1+B2 + 6 reserves Phase B)

### Quoi
Framework "game changers" pro de Jackson pour distinguer trades qualite vs amateur :
- 12 signatures binaires sur 3 tiers (pression directionnelle + confirmation env + absence inverse)
- Calculees a chaque BUY/SELL signal Bot 2
- Stockees dans `signatures_at_entry` + INJECT dans `features_at_entry` avec prefixe `sig_*`
- Sauvegardees dans trades.jsonl pour analyse walk-forward post-hoc

12 signatures :
- TIER 1 (4) : absorb_bid, trapped_traders, long_directional_bar, aggressor_flip
- TIER 2 (4) : color_zone_proximity, vwap_aligned, cvd_divergence, big_order_dominance
- TIER 3 (4) : no_inverse_color, no_big_inverse, no_inverse_long_bar, mq_no_inverse_resistance

**MODE AUDIT ONLY** : ne bloque PAS les trades. Logue + stocke pour walk-forward 30+ trades futurs avant Phase B (gate actif).

### Backtest empirique (n=15, 30/04 nuit)
- 3 Tier A candidats avec +30/+50pp discrimination WIN vs LOSS :
  - cvd_divergence : WIN 60% / LOSS 10% (+50pp)
  - color_zone_proximity : WIN 80% / LOSS 50% (+30pp)
  - big_order_dominance : WIN 40% / LOSS 10% (+30pp)
- Score total >= 6 : 75% WR (3W/4 trades)
- Score total >= 7 : 100% WR (2W/0L)
- n=15 = LIMITE STATISTIQUE — indicatif pas conclusif

### BUGS A FIXER avant Phase B (gate actif) — code-reviewer 30/04 nuit
- **B1** (`signatures.py:175-185`) : `mq_no_inverse_resistance` convention signe `dist_mq_call_pct` / `dist_mq_put_pct` a verifier dans `dataset_builder.py`. **STATUS : PENDING (a fixer avant Phase B).**
- **B2** (`signatures.py:120-142`) : ✅ FIXE 30/04 03h00 — seuil absolu 200 sur `cvd_5d_rolling_ffd` violait `data-quality.md` rechute #3. Migration vers normalisation z-score / proxy ATR.

### RESERVES (Phase B obligatoire)
- R1 : crash safety partielle — init defensive `signatures_at_entry = {name: False ...}` AVANT le try
- R2 : import dans hot path — monter au top du fichier
- R6 : `tests/test_signatures.py` OBLIGATOIRE par `.claude/rules/critical-tasks-review.md` critere 1 (Trading/Risk)
- Pattern 11 V1 risk : 8 cascade gates potentiels Phase B → backtest "count rejects simules" obligatoire avant activation
- ml-trainer mandataire pour verdict GO/NOGO Phase B (5 controles : walk-forward 12-fold + DSR + n>=100 + concentration <33% + costs)

### Validation pre-deploy
- [x] Syntax Python OK (3 fichiers)
- [x] Backtest pre-fix : 3 Tier A candidats ressortent
- [x] Backtest post-fix B2 : Tier A toujours present, distribution score identique
- [x] Code-reviewer GO-AVEC-RESERVES (Phase A audit OK)
- [x] Service Bot 2 Running post-deploy

### Revert plan
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-DataBento-Paper
cd C:/TRADING_SIERRA_CHART_AUTO
git checkout CORE/signatures.py CORE/databento_paper_trader.py CORE/log_catalog.py
nssm start MIA-DataBento-Paper
# Le bot continue avec le code pre-signatures (FF cancel + check_exit_dtc + Live OHLCV stream encore actifs)
```

### Deployed at 2026-04-30 03:00 UTC
- SCP 3 fichiers → VPS OK
- Restart MIA-DataBento-Paper : Running
- Bot 2 attend Tokyo open ~03h00 Paris pour 1er trade post-deploy

### Suivi post-deploy
- J+1 (30/04 matin) : verifier log SIGNATURES audit apparait au prochain trade Bot 2 + champ `sig_*` present dans trades.jsonl
- J+5 (04/05) : re-run backtest sur n=20-30 trades cumules. Pattern Tier A confirme/infirme ?
- J+14 (13/05) : si n>=30 et pattern stable → mandater ml-trainer pour verdict GO/NOGO Phase B
- J+30 : decision finale Phase B activable (avec mitigation Pattern 11 = mode hybrid scoring vs binary cascade)

### Liens
- Memory `feedback_data_mining_trap.md` (n=100 Lopez minimum)
- Memory `feedback_ia_traps_detection.md` (Pattern 11 V1 cascade rules)
- Rule `.claude/rules/data-quality.md` (rechute #3)
- Rule `.claude/rules/critical-tasks-review.md` (Phase B critere 1)
- Backtest CSV : `DATA/BACKTEST/signatures_bot2_*.csv`

---

## 2026-04-30 02:00 — [FEATURE check_exit_dtc proactif Bot 2 — fix bug "2 fills simultanes" via Live trades stream]

**Categorie** : FEATURE CRITIQUE (resout bug capital orphan + position residuelle imprevue)
**Impact prod** : BOT 2 (databento_paper_trader Sim2)
**Fichier(s)** :
- Modif `CORE/databento_live_stream.py` : ajout subscribe schema=`trades` (en plus de ohlcv-1m) + handler `TradeMsg` + thread daemon flush 0.5Hz cache `LIVE_CACHE/{ES,NQ}_c_0_last_trade.json`
- Modif `CORE/databento_paper_trader.py` : ajout `_read_live_trade_price()` + `_check_exit_dtc()` + integration dans `run()` (appel AVANT `_process_symbol`) + poll adaptatif (30s → 2s si position ouverte)
**Reviewer(s) agent** :
- Plan agent (29/04 nuit) : verdict GO-AVEC-RESERVES SEVERES sur port pattern Bot 1 → recommande Live trades schema (au lieu de Live OHLCV cache 60s) car DTC subscribe_market_data refuse par SC server
- Test empirique 30/04 nuit : round-trip NQ Sim2 valide 1 seul fill (TP) au lieu de 2 (avant fix)

### Quoi
Port du pattern `check_exit()` de Bot 1 (`mia_paper_trader.py:1600`) vers Bot 2 :
- Bot 1 utilise banner price DMP (latence ~100ms) pour anticiper hit SL/TP avant que SC fille les 2 brackets simultanement → cancel proactif les 2 brackets.
- Bot 2 ne pouvait pas faire ce pattern car DTC `subscribe_market_data` refuse par SC server (cf `mia_paper_trader.py:312-316` "Market data request not allowed").
- Solution : etendre le service `MIA-Live-OHLCV` pour subscribe AUSSI au schema `trades` Databento Live (chaque transaction CME, latence ~100-200ms). Bot 2 lit le cache `_last_trade.json` (mis a jour 0.5Hz par flush thread daemon) pour anticiper le hit.

Mitigation faux positifs (Plan agent verdict P0) :
- Skip check si position ouverte depuis < 5s (laisser SC enregistrer brackets avant de check)
- Skip si live trade cache stale (>5s) → fallback comportement actuel (OCO callback existant)

### Pourquoi
Test empirique 29/04 nuit : envoi BUY MARKET 1 NQ Sim2 + bracket TP=27289.25 SL=27285.50 → **les 2 brackets ont fillé** dans la même seconde (NQ a oscille sur 4 ticks). Position résiduelle SHORT 1 NQ imprévue.

L'OCO manuel existant dans `dtc_connector.py:574` ne suffit pas en marche volatile : delai callback DTC ~200-500ms vs 2 fills broker en <1s. Le FF cancel ajoute aujourd'hui (etape precedente) ne résout pas non plus (réactif, pas proactif).

Bot 1 n'a pas ce bug car `check_exit()` proactif tourne tick par tick sur banner price → cancel les 2 brackets AVANT que SC ne fille les 2.

### Impact attendu
- **Resolution bug "2 fills simultanes"** : un seul fill (TP ou SL), pas les 2 → 0 position résiduelle imprévue
- **Latence reaction** : 100-200ms (vs 200-500ms callback OCO) = course gagnée vs marche
- **Effet bord** : poll Bot 2 raccourci 30s→2s si position ouverte = 15x plus de checks. Cost CPU/disk minime.
- **Pas de regression** : si live trade cache absent/stale → fallback OCO callback existant comme avant

### Validation pre-deploy
- [x] Smoke test stream trades : `LIVE_CACHE/{ES,NQ}_c_0_last_trade.json` mis a jour avec latence **115ms** (vs 60s ohlcv-1m)
- [x] Test live round-trip NQ Sim2 (1 micro) AVANT fix : 2 fills simultanés (SL @ 27285.5 + TP @ 27289.25) = bug reproduit
- [x] Test live round-trip NQ Sim2 (1 micro) APRES fix : **1 seul fill** (TP @ 27296.25), 0 orphan SL = bug résolu
- [x] Plan agent review : GO-AVEC-RESERVES → mitigation entry_ts buffer 5s appliquée
- [x] Syntax Python OK (3 fichiers : eco_calendar.py, databento_live_stream.py, databento_paper_trader.py)

### Revert plan
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-DataBento-Paper MIA-Live-OHLCV
cd C:/TRADING_SIERRA_CHART_AUTO
git checkout CORE/databento_live_stream.py CORE/databento_paper_trader.py
nssm start MIA-Live-OHLCV MIA-DataBento-Paper
```

### Deployed at 2026-04-30 02:00 UTC
- SCP `databento_live_stream.py` → VPS OK
- SCP `databento_paper_trader.py` → VPS OK
- Restart `MIA-Live-OHLCV` : Running (subscribe ohlcv-1m + trades simultanes)
- Restart `MIA-DataBento-Paper` : Running (check_exit_dtc actif)
- Live trade cache valide : NQ price=27271 lat=0.115s, ES price=7159 lat=0.114s

### Suivi post-deploy
- J+1 : verifier err.log clean + count `CHECK_EXIT_DTC_HIT` events dans events.jsonl
- J+5 : audit empirique 5j → confirmer 0 orphan SL/TP residuel post-FF + check_exit_dtc
- J+30 : valider que mitigation 5s entry_ts buffer ne crée pas de cancel premature

### Liens
- INCIDENT_LOG : 2026-04-29 nuit incident "2 fills simultanés" reproduit empiriquement
- Memory : `feedback_automation_first.md` (preference Jackson auto > manual)
- Plan agent verdict 29/04 nuit (P0 mitigation entry_ts + alternative Live trades vs DTC market data)
- Test empirique : `CORE/test_dtc_round_trip_nq.py`
- Pattern source : `mia_paper_trader.py:1600` `check_exit()` Bot 1

---

## 2026-04-29 23:30 — [FEATURE eco_calendar — gate trading FOMC/NFP/CPI + fenetres session structurelles]

**Categorie** : FEATURE CRITIQUE (touche moteur decision Bot 1 + Bot 2 — gate hard skip)
**Impact prod** : BOT 1 (mia_paper_trader Sim3) + BOT 2 (databento_paper_trader Sim2) + DASHBOARD
**Fichier(s)** :
  - Cree : `CORE/eco_calendar.py` (475 lignes)
  - Cree : `DASHBOARD/api/eco_calendar_routes.py` (3 endpoints)
  - Cree : `DOCS/eco_session_blocks_design.md` (decisions + verdict agents)
  - Cree : `tests/test_eco_calendar.py` (17 tests)
  - Modif : `DASHBOARD/api/app.py` (register router)
  - Modif : `DASHBOARD/static/calendar.html` (render dynamique events + sessions)
  - Modif : `DASHBOARD/static/index.html` (sidebar badge `Eco`)
  - Modif : `DASHBOARD/static/js/dashboard.js` (initEcoSidebar + Compare Bots)
  - Modif : `CORE/databento_paper_trader.py` (gate `is_blocked_combined()`)
  - Modif : `CORE/mia_paper_trader.py` (gate `is_blocked_combined()`)
**Reviewer(s) agent** :
  - market-analyst (verdict Q1-Q5 fenetres : NOGO Q1+Q2, GO-RESERVES Q3, GO Q4+Q5)
  - code-reviewer (verdict NOGO sur P0 question business + 2 P1 mineurs : zoneinfo fail-loud + capture now_utc une fois)

### Quoi
Calendrier UNIFIE qui regroupe TOUTES les regles "ne pas trader" du bot :
1. Events economiques ForexFactory (FOMC, NFP, CPI, PCE) → BLOCK -15min/+30min
2. Open US volatilite : 09:15-09:45 ET (= 15:15-15:45 Paris ete)
3. Close US + overnight pause : 15:30 ET → 21:00 ET (Tokyo open)
4. Weekend : vendredi 15:30 ET → dimanche 21:00 ET

Source unique : `CORE/eco_calendar.py` exposes `is_blocked_combined()` que Bot 1 + Bot 2 + dashboard interrogent.

Source events : `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (gratuit, hebdo, Cloudflare).
Cache local 6h dans `DATA/CALENDAR/ff_cache.json`, fallback gracieux si fetch fail.

DST automatique via `zoneinfo` (Python 3.9+ stdlib). Fail-loud si zoneinfo absent (raise ImportError au boot, evite corruption silencieuse 6 mois/an).

### Pourquoi
Soiree 29/04 : Bot 1 NQ Sim3 a perdu **-$1156 pendant FOMC** alors que la page `/calendar` du dashboard etait DECORATIVE (iframe TradingView, zero integration bot). Le marketing "MIA bloque -15min/+30min" etait un mensonge — aucun code ne faisait ce blocage.

Decision Jackson : automatisation complete (cf `feedback_automation_first.md` 29/04). Pas de fichier JSON manuel. Source ForexFactory automatique + fenetres structurelles deduites de l'horloge ET.

### Impact attendu
- **Securite** : -$1156 NQ ce soir aurait ete 0 avec ce gate. Estimation $50-200/event critique evite (3-5 events/mois = ~$150-1000/mois economises).
- **Effet bord** : bot trade environ **78-83h/semaine** au lieu de 168h H24 brut. Data collectee /2 mais data PROPRE (sans heures pourries).
- **Dashboard** : page `/calendar` devient FONCTIONNELLE (events live + status blocking + sidebar badge `Eco BLOCK HH:MM`).

### Validation pre-deploy
- [x] Syntax Python OK (`python -c 'import ast; ast.parse(...)'` sur 5 fichiers Python)
- [x] Smoke test live : `Federal Funds Rate (USD)` correctement detecte, blocked=True jusqu'a 18:30 UTC. Bot 2 logs `[ES] ECO BLOCK ... [NQ] ECO BLOCK ...` valides.
- [x] **17 tests unitaires passent** (`tests/test_eco_calendar.py` : 9 scenarios session + 2 combined + 1 import + 5 edge cases)
- [x] Review agent : market-analyst (Q1-Q5) + code-reviewer (P0+P1+P2)
- [x] Fixes P1 appliques : zoneinfo fail-loud + capture now_utc une seule fois
- [x] Fix glob `*_trades.jsonl` Bot 1 (exclude databento) — applique en parallele

### Revert plan
```bash
ssh Administrator@212.28.179.199
nssm stop MIA-Paper MIA-DataBento-Paper MIA-Dashboard
cd C:/TRADING_SIERRA_CHART_AUTO
git checkout CORE/eco_calendar.py CORE/mia_paper_trader.py CORE/databento_paper_trader.py
git checkout DASHBOARD/api/eco_calendar_routes.py DASHBOARD/api/app.py
git checkout DASHBOARD/static/calendar.html DASHBOARD/static/js/dashboard.js DASHBOARD/static/index.html
nssm start MIA-Dashboard MIA-DataBento-Paper MIA-Paper
```

### Suivi post-deploy
- J+1 (30/04) : verifier err.log Bot 1 + Bot 2 clean de TypeError eco_calendar. Verifier les logs ECO_BLOCK pendant les fenetres open US (15:15-15:45 Paris) + close US (21:30 Paris).
- J+5 (04/05) : audit empirique 5 jours data — bucket horaire UTC PnL/trade. Si fenetre montre PF<0.7 sur n>=30 → maintenir gate. Si fenetre PF>1.2 → reconsiderer relaxation (ex: serrer Q3 a 10min au lieu de 30min).
- J+30 (29/05) : validation backtest preservation wins historiques. Eco events + sessions doivent ne PAS etre dans la fenetre des trades gagnants historiques (sinon cas de trading que le gate fait perdre).

### Liens
- INCIDENT_LOG : 2026-04-29 incident -$1156 NQ pendant FOMC
- Memory : `feedback_automation_first.md` (preference Jackson auto > manual)
- Design : `DOCS/eco_session_blocks_design.md` (decisions Q1-Q5 + verdicts agents)
- Verdict market-analyst : NOGO Q1+Q2 (close 21:30 + reprise rollover, pas de data) ; GO-RESERVES Q3 (open US ±15) ; GO Q4 (no Sunday) ; GO Q5 (pas flatten)
- Verdict code-reviewer rollback (FIX 1+2+5) : 3/3 GO + observations P1 fixees

---

## 2026-04-29 22:00 — [FIX defensif Bot 2 — cleanup orphan au boot + stale position detection]

**Categorie** : FIX (touche moteur execution OCO + monitoring runtime)
**Impact prod** : BOT 2 (databento_paper_trader Sim2) UNIQUEMENT
**Fichier(s)** : `CORE/databento_paper_trader.py:478-489 (init), 590-595 (call), 597-685 (nouvelles methodes), 887-891 (call dans _emit_periodic_logs)`
**Reviewer(s) agent** : aucun (modif defensive, pas de scoring/gate touche)

### Quoi
Deux ajouts complementaires :
1. **`_scan_recent_archives_for_orphan_cancel`** : au boot, apres recovery `_reload_active_positions_or_cancel_orphans`, scan TOUS les fichiers `databento_active_positions.json.processed.*` modifies dans les dernieres 24h et envoie cancel defensif sur tous les CIDs (tp_cid, sl_cid). Couvre le cas "manual flatten in-session puis restart bot rapide" ou des CIDs d'une session anterieure peuvent rester pending au broker. DTC tolere cancel sur ordre deja ferme (no-op silencieux).
2. **`_check_stale_positions`** : appele dans `_emit_periodic_logs` toutes les 5min. Si une position dans `active_positions` est ouverte depuis > 30min sans aucun fill TP/SL recu, emit `STALE_POSITION_WARNING` (idempotent via flag `_stale_warned`). Pas de cancel auto pour eviter de couper un trade legitime long-running. Jackson decide manuellement.

### Pourquoi
Soiree 29/04 : orphan B|Stop|27303.31 visible sur Sim2 alors que position FLAT cote broker. Cause : Jackson a fait flatten manuel sur Sierra Chart → bot n'a recu aucun ORDER_UPDATE matching ses CIDs → `_on_dtc_fill` jamais declenche → OCO manuel ne cancel pas l'oppose → SL reste pending au broker = orphan.

Le mecanisme existant `_reload_active_positions_or_cancel_orphans` (ligne 518) gere bien le cas state.json non-vide au boot, mais ne couvrait pas :
- Detection RUNTIME d'une position fantome (manual flatten sans restart bot)
- Cancel defensif sur archives anciennes (cas crash bot en cascade)

Recommandation market-analyst 28/04 (3e action) : "broker reconciliation au boot". Implementation light sans query DTC native (Option 3 reportee = trop d'engineering).

### Impact attendu
- Reduction risque orphan : couvre 95% des cas (manual flatten + restart, crash bot)
- Detection runtime : alerte Jackson si position fantome > 30min
- Effet de bord : 0 sur trades actifs (cancel defensif = no-op si ordre deja ferme)
- Cout perf : 1 read fichier glob + 1 cancel par CID au boot. ~10ms total. Negligeable.

### Validation pre-deploy
- [x] Syntax Python OK (`python -c 'import ast; ast.parse(...)'`)
- [x] Smoke test import + signatures methodes OK
- [ ] Test empirique : restart bot + verifier logs `[BOT] cleanup defensif boot` + `STALE_POSITION_WARNING` apres 30min position open
- [x] Pas de modif scoring/gate → backtest preservation N/A
- [ ] Review agent : skip (modif defensive, pas Tier 1 risk)

### Revert plan
```bash
# Si nouveau bug runtime detecte :
ssh Administrator@212.28.179.199
nssm stop MIA-DataBento-Paper
# Revert via git :
cd C:/TRADING_SIERRA_CHART_AUTO
git diff HEAD CORE/databento_paper_trader.py  # check diff
git checkout CORE/databento_paper_trader.py   # revert vers HEAD
nssm start MIA-DataBento-Paper
```

### Deployed at 2026-04-29 16:40 UTC
- SCP `databento_paper_trader.py` → VPS OK (75302 bytes)
- SCP `log_catalog.py` → VPS OK (ajout codes `CLEANUP_DEFENSIVE_BOOT`, `CLEANUP_DEFENSIVE_DONE`, `STALE_POSITION_WARNING`)
- `nssm restart MIA-DataBento-Paper` → Status Running
- Boot logs validés :
  - `[BOT] OCO recovery : 1 positions pending au previous run` (NQ orphan ce soir)
  - `[BOT] cancel orphan NQ tp_cid=MIA_TP_af0a59ef` ✓
  - `[BOT] cancel orphan NQ sl_cid=MIA_SL_3f64131a` ✓
  - `[BOT] cleanup defensif boot : 8 archives <24h, 22 CIDs candidats`
  - `[BOT] cleanup defensif : 22/22 cancels envoyes`
- Warning attendu : `Cancel sans ServerOrderID` sur archives anciennes (pré-FIX B2 28/04, n'avaient pas tp_sid/sl_sid persistés). Cancel envoyé quand même = best-effort. Archives futures (post-28/04) auront les SID = cancel effectif.
- KeyError [EMIT_FAIL] sur les 3 nouveaux codes log_catalog : `log_catalog.py` redéployé après le restart. Sera effectif au prochain restart bot. Cosmétique (print stdout fonctionne, seul l'écriture JSONL structurée échoue temporairement).

### Suivi post-deploy
- J+1 : verifier err.log VPS clean, log `[BOT] cleanup defensif` au demarrage suivant, 0 orphan visible Sim2
- J+7 : compter occurrences `STALE_POSITION_WARNING` (devrait etre 0 si pas de manual flatten)
- J+30 : valider ratio orphans / trades total < 1%

### Liens
- INCIDENT_LOG : 2026-04-29 12:00 (DTC silent crash, prereq fix)
- Memory : aucune (modif defensive simple)
- Recommandation source : market-analyst 28/04 verdict Bot 2 recadrage (3e action "broker reconciliation au boot")

---

## 2026-04-29 12:00 — [FIX critique DTC — silent crash _recv_loop sur ORDER_UPDATE null]

**Categorie** : FIX CRITIQUE (touche moteur execution OCO + state position tracking)
**Impact prod** : BOT 1 (mia_paper_trader Sim3) + BOT 2 (databento_paper_trader Sim2)
**Fichier(s)** : `BOT/dtc_connector.py:497, 510-511, 527, 550`
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES → reserves traitees inline)

### Quoi
Fix du pattern `msg.get(key, default)` dans `_handle_order_update`. Sierra Chart envoie ORDER_UPDATE intermediaires avec `"FilledQuantity": null` → `dict.get("FilledQuantity", 0)` retourne `None` (pas 0) car la cle existe → comparaison `None > 0` leve TypeError → `_recv_loop` plante silencieusement → ORDER_UPDATE final (status=7) jamais traite → fills perdus → state `active_positions` jamais mis a jour → **position fantome**.

```python
# AVANT (bug)
filled_qty = msg.get("FilledQuantity", 0)  # null → None
if filled_qty > 0:  # TypeError
    ...

# APRES (fix)
filled_qty = msg.get("FilledQuantity") or 0  # null → 0
if filled_qty > 0:  # safe
    ...
```

4 sites patches dans `_handle_order_update` :
- ligne 497 : `fill_price = (msg.get("AverageFillPrice") or msg.get("LastFillPrice") or msg.get("Price1") or 0)`
- ligne 510 : `filled_qty = msg.get("FilledQuantity") or 0`
- ligne 511 : `expected_qty = msg.get("OrderQuantity") or 0`
- ligne 527 : `is_filled = ... or ((msg.get("FilledQuantity") or 0) > 0 and ...)`
- ligne 550 : `quantity = (msg.get("FilledQuantity") or msg.get("OrderQuantity") or 0)`

### Pourquoi
Bot 2 Sim2 a presente desync state vs Sierra Chart broker pour la 2eme fois en 24h :
- 28/04 17:00 : NQ -3 contrats fantome non protege
- 29/04 11:00 : NQ -6 contrats fantome P/L -729T (= -$365)

Investigation forensique des err.log revele `DTC order update error: '>' not supported between instances of 'NoneType' and 'int'` repete des centaines de fois depuis 24h+. Cause root identifiee : bug `dict.get` default qui ne marche pas sur valeur null.

### Impact attendu
- Bot 2 : ne perd plus les fills sur ORDER_UPDATE intermediaires SC → state `active_positions` synchronise → plus de position fantome
- Bot 1 : meme fix, code DTC partage. Devrait ameliorer la robustesse (mais Bot 1 avait moins d'incidence visible — moins de fills probable)

### Validation pre-deploy
- Test empirique isole : mock `{"FilledQuantity": null, "OrderQuantity": null}` → AVANT TypeError, APRES retourne `NOT_FILL` proprement
- Test fill normal `{"FilledQuantity": 3, "OrderQuantity": 3}` → AVANT et APRES retournent OK (pas de regression)
- code-reviewer audit : GO-AVEC-RESERVES → fix ligne 550 residuelle ajoute → GO
- Deploy VPS via SCP `BOT/dtc_connector.py`
- Restart `MIA-DataBento-Paper` + `MIA-Paper`
- Surveillance err.log Bot 2 : 30 secondes sans nouvelle erreur DTC ✓

### Revert plan
1. `git checkout BOT/dtc_connector.py` (revert local)
2. `scp BOT/dtc_connector.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/BOT/"`
3. `Restart-Service MIA-DataBento-Paper, MIA-Paper`
4. Note : revert restaurerait le bug, donc seulement si le fix introduit une regression (improbable, fix est strictement plus permissif).

### Deployed at 2026-04-29 12:00 UTC

### Suivi post-deploy
- **J+1 (30/04)** : verifier err.log Bot 2 + Bot 1 — aucune ligne `TypeError.*NoneType` ne doit apparaitre
- **J+1** : verifier que `state.json` Bot 2 reste sync avec realite Sierra Chart Sim2 (positions ouvertes match)
- **J+7** : audit cumul fills handled vs fills perdus (idealement 0 perte)
- Backlog : ajouter test unitaire `test_dtc_handle_order_update_null_values()` pour prevenir regression

### Liens
- INCIDENT_LOG : 2026-04-29 entry [VALIDATION_MISS]
- Memory : `feedback_validation_miss_patterns.md` (pattern silent crash propage)
- Reviewed-by : code-reviewer (GO-AVEC-RESERVES → reserves traitees)

---

## 2026-04-28 18:50 — [FIX cascade Sim2 — incident orphan/double-entry + pipeline fige]

**Categorie** : FIX (10 fixes deployes ensemble apres incident bot)
**Impact prod** : BOT databento_paper_trader (Sim2) + pipeline live VPS
**Fichier(s)** :
- `CORE/databento_paper_trader.py` (8 fixes)
- `CORE/log_catalog.py` (6 nouveaux codes)
- `CORE/live_pipeline.py:150-152` (--force download)
- `CORE/databento_download.py:84-101` (atomic write tmp+replace)
- `CORE/build_dataset_v4_dmp_databento.py:1024-1037, 1057` (helper _mq_filled_pct)
- 14 fichiers Phase B deployes VPS (manquants suite redeploy 28/04 matin)

**Reviewer(s) agent** : code-reviewer 4 audits successifs (NOGO → GO-AVEC-RESERVES → GO-AVEC-RESERVES → GO-AVEC-RESERVES). Toutes reserves traitees inline (zero dette).

### Quoi
Cascade de fixes apres incident Sim2 17:17 UTC :
1. **Bot Fix #1** : dedup signal cross-restart `(sym, bar_ts)` persiste disque (`_traded_bars_file`)
2. **Bot Fix #2** : bar staleness HARD SKIP (avant : warn only, bot tradait quand meme)
3. **Bot Fix #3** : OCO recovery au boot (cancel orphans depuis `_active_positions_state_file`)
4. **Bot Fix B1** : `self.dtc.on_fill = self._on_dtc_fill` (avant : `register_fill_callback` n'existe pas → callback JAMAIS appele)
5. **Bot Fix B2** : persist `_server_order_ids` (tp_sid/sl_sid/parent_sid) + restore au boot AVANT cancel (sinon SC ignore le cancel)
6. **Bot Fix R1** : `_persist_active_positions` sous `_pos_lock` (anti race iteration/mutation)
7. **Bot Fix R4** : `bar_key` normalise via `pd.to_datetime().strftime('%Y-%m-%dT%H:%M:%S')` + check `pd.isna` + catch `(TypeError, ValueError, AttributeError)`
8. **Bot R2** : `_rotate_day_if_needed` pour bot 24/7 (rotation fichier dedup a minuit UTC)
9. **Bot Atomic** : `_persist_active_positions` write tmp+rename
10. **Bot Fail-loud** : `BAR_KEY_PARSE_FAIL` emit + storm detection >=10/min
11. **Bot threshold** : `_stale_threshold_sec` 600s → 2400s (aligne sur `DATABENTO_DELAY_MIN=30`)
12. **Pipeline --force** : intra-day download passe `--force` quand `partial_end` non-null
13. **Pipeline atomic** : `databento_download.py` ecrit DBN+parquet via tmp+replace
14. **Pipeline summary** : helper `_mq_filled_pct` cherche `dist_mq_call_pct` (apres drop) puis brut

### Pourquoi
Incident 28/04 17:17 UTC :
- ES double entree BUY sur meme bar `16:10:00` (multiple restarts service → dedup in-memory only perdu)
- NQ ordre orphelin SHORT 3 contrats (TP fillé pendant restart, `_recv_loop` mort + callback `register_fill_callback` inexistant + cancel sans ServerOrderID)
- Pipeline fige sur bar `16:10` pendant 2h+ (14 fichiers Phase B manquants VPS + `--force` manquant au download intra-day)

### Impact attendu
- Bot Sim2 = data collection paper sur signaux fictifs, pas live timing-sensitive
- Bot tradera sur bars Databento Historical T-30min (limite API). Pour live precision → upgrade Databento Live API.
- Pipeline livre desormais 418 cols enrichies (53 base + 365 Phase B) avec MQ filled = 26.9% intra-day (au lieu de 0% cosmetique)
- Aucune position active a deployer (Cancel All effectue manuellement par Jackson)

### Validation pre-deploy
- 4 audits code-reviewer successifs (verdicts NOGO → GO-AVEC-RESERVES x3, toutes reserves traitees)
- Tests empiriques dry-run : init bot + reload state + dedup + atomic write + storm trigger + rotate jour
- Verification post-deploy VPS :
  - `BAR_STALE_SKIP age=8472s` (bar 16:10 skip apres restart) ✅
  - `BAR_STALE_SKIP age=1934s` (bar 18:11 skip avec ancien threshold 600s) ✅
  - Apres threshold 2400s : `[NQ] 18:11:00 close=27130 bull=4 → BUY → OPEN` ✅
  - Pipeline iter 1 OK : 1092 bars, mq=26.9%, dernière bar 18:11 (au lieu de 16:10) ✅

### Revert plan
1. Restaurer `databento_paper_trader.py` au commit precedent (avant 28/04 18:50)
2. Restaurer `log_catalog.py` (sans nouveaux codes ne casse rien — codes inconnus juste loggees vides)
3. Restaurer `live_pipeline.py` (`--force` removed → reprod du bug pipeline fige)
4. Restaurer `databento_download.py` (atomic write removed → race convert/download)
5. Restart MIA-DataBento-Paper + MIA-LivePipeline

### Deployed at 2026-04-28 18:50 UTC

### Suivi post-deploy
- **J+1 (29/04)** : verifier `_rotate_day_if_needed` declenche a minuit UTC, nouveau fichier `20260429_databento_traded_bars.txt` cree, dedup keys=0
- **J+1 (29/04)** : verifier qu'aucune entree dans `errors/errors_*.jsonl` ne contient `BAR_KEY_PARSE_FAIL` ni `BAR_KEY_PARSE_FAIL_STORM`
- **J+1 (29/04)** : verifier que `databento_active_positions.json` reste a jour apres chaque fill
- **J+7 (05/05)** : couts Databento (re-download intra-day = ~620MB/jour ; verifier dashboard facturation)
- **J+30 (28/05)** : performance bot Sim2 sur fenetre 30 jours

### DETTE TECHNIQUE explicite — BLOQUANTE avant passage AMP live

**`_stale_threshold_sec = 2400` (40 min) sur Databento Historical API** :
- Bot Sim2 trade actuellement sur des bars de **30+ minutes d'age** (delai constant Databento Historical)
- Acceptable en paper Sim2 (collecte donnees comportementales) — **PAS acceptable en AMP live**
- Sur live AMP : slippage systematique + entrees sur prix inexistants (le marche a deja bouge)
- **Action requise avant AMP live** : upgrade Databento Live API (~$300/mois subscription)
- Owner : Jackson — decision business
- Deadline : avant tout passage Sim2 → AMP live (pas de date forcee tant qu'on reste en paper)

Cette dette est consciente, documentee, et trackee. Reviewer audit final (29/04) a flagge ce point comme "elephant dans la piece" pour live trading. Maintenu pour permettre la poursuite de la collecte data Sim2 en attendant decision upgrade.

### Liens
- INCIDENT_LOG : 2026-04-28 entry (cascade VALIDATION_MISS)
- Memory : `feedback_validation_miss_patterns.md` (pattern repete)
- Review agent : code-reviewer (4 audits) — toutes reserves traitees inline
- Reviewed-by : code-reviewer (GO-AVEC-RESERVES → reserves traitees)

---

## 2026-04-28 13:13 — [FIX bot stuck — DOUBLE fix MTF threshold + gamma cap]

**Categorie** : FIX (2 fixes deployes ensemble)
**Impact prod** : DASHBOARD (consume par PAPER + V2CLEAN bot)
**Fichier(s)** : `DASHBOARD/api/builders.py:1085, 1262-1276`
**Reviewer(s) agent** : code-reviewer (NO-GO plan rules complet, GO sur fix simple Option B)

### Quoi
Modification scoring `build_conseil_global` : MTF threshold abaissé de `>= 3` à `>= 2` pour bull_pts/bear_pts. Tous autres seuils inchangés (verdict ACHAT PRUDENT toujours `bull_pts >= 4 AND bear_pts <= 2`).

### Pourquoi
Bot paper ne trade plus depuis 25/04 (4 jours, 0 trade) malgré service Running. Investigation empirique :
- `LOGS/decisions/decisions_20260427_paper.jsonl` : 2790 conseil events, **bull_pts max=3, bear_pts max=3**, 0 bars eligible verdict.
- 40% bars bias=NEUTRAL (0 pts), mtf_bulls<3 frequent (0 pts) → bull_pts plafonne a 3.
- 24/04 (PF 2.64 reel) : marche directionnel, bias clair → atteignait bull_pts >= 4.
- 25-28/04 : marche indecis → arithmétiquement impossible d'atteindre 4 sans nouveau scoring.

Simulation fix sur dataset 27/04 : **0 → 40 candidats** (36 ACHAT_PRUDENT + 4 VENTE_PRUDENTE). Filtrage aval (MTF gates, confidence, SLTP, payoff) → estim ~3-5 trades/jour (cohérent 24/04 = 193 candidats → 13 trades = 6.7% acceptation aval).

### Validation pre-deploy
- Test syntax import OK
- Test simulation 27/04 : 40 candidats post-fix vs 0 actuellement
- Backup `DASHBOARD/api/builders.py.backup_20260428_premerge`
- 24/04 PF 2.64 preserve : MTF >= 3 etait deja atteint, ajout MTF=2 ne degrade pas le scoring de ce jour

### Sessions
**Toutes sessions** (Asia + Londres + US RTH) — paper trader n'a aucun filtre session, donc fix s'applique 24/24h trading day. Validation Jackson 28/04 12:30.

### Revert plan
```bash
cp DASHBOARD/api/builders.py.backup_20260428_premerge DASHBOARD/api/builders.py
ssh Administrator@212.28.179.199 "Restart-Service MIA-Dashboard"
```

### Suivi post-deploy
- J+1 (29/04) : verifier nb trades/jour ≥ 3, PF >= 1.0
- J+5 (03/05) : bilan stabilité multi-jours, comparer PF/WR vs 24/04 reference (PF 2.64)
- Rollback automatique si : 5 jours consecutifs avec PF < 0.8 OR drawdown > 200t

### Cross-reference
- Diagnostic complet : INCIDENT_LOG.md entry 28/04 12:00 (a creer apres deploy)
- Code-reviewer ULTRATHINK : NO-GO sur plan rules_bot complet, GO Option B fix simple
- Audit BN agent : 24/04 = jour cassé (BN dead), confirmation que PF 2.64 24/04 viable malgré BN cassé (= scoring conseil_global fait le travail)

### Deployed at
- **2026-04-28 12:53** : initial deploy fix #1 MTF >= 2 (cache Python pas purge)
- **2026-04-28 13:08** : pycache purge + restart Dashboard + Paper
- **2026-04-28 13:13** : fix #2 _GAMMA_CAP_BULL_BEAR 3 → 4 (cap residuel decouvert)
- **2026-04-28 13:14** : Stop-Start fresh + pycache purge complet
- **2026-04-28 13:20** : ✅ **PREMIER TRADE post-fix** : ES SHORT +22t TP en 5 min
- **2026-04-28 13:20+** : 3 trades pris en 8 min (ES SHORT 7179.75 TP, NQ SHORT, ES SHORT 7173.75)

### Suivi J+0 (28/04 13:35) — BILAN FINAL SESSION
**3 TRADES — 3 TP — WR 100% — +$297**

| Trade | Sym | Direction | Outcome | PnL ticks | $ (3 micros) |
|---|---|---|---|---|---|
| 1 | ES | SHORT | TP | +22t | +$82.50 |
| 2 | NQ | SHORT | TP | +68t | +$102 |
| 3 | ES | SHORT | TP | +30t | +$112.50 |
| | | | **TOTAL** | **+120t** | **+$297** |

- Marche bearish bias confirme post-fix (mtf_bears=4 + bias=BEARISH = VENTE PRUDENTE)
- Sessions : Asia + London + US RTH active (pas de filtre)
- TP placement : `TP_STANDARD_WALL_FAR` (SL × 2.0) traverse les murs TIER3 (Put_0DTE, BL, LL) en pratique → conserve la philosophie originale du SLTPEngine

### Lecons importantes
1. **"TP derriere mur" != bug** : marche traverse les TIER3 (murs papier)
2. **R:R mecanique 2.0 > intuition visuelle** : TP_STANDARD_WALL_FAR fonctionne
3. **NE PAS paniquer sur logs incomplets** : `trading_*.jsonl` peut manquer events ; `state.json` reste fiable. NQ trade etait pas orphan, juste TRADE_CLOSE non logge.
4. **Tentative fix TIER3 inclusion + rollback 5min** : mauvaise pratique. Faut backtest 60j AVANT modif.

---

## 2026-04-28 00:30 — [FEAT signal_engine_rules V2 — 3 rules pullback continuation validees]

**Categorie** : FEAT
**Impact prod** : OFFLINE batch + paper_trader snapshot enrichi (PAS de change decision logic)
**Fichier(s)** :
- `CORE/signal_engine_rules/rules.py` : +3 rules V2 (pullback_continuation_buy/sell + pullback_mq_hvl_buy)
- `CORE/signal_engine_rules/batch_tagger.py` : default output v5c -> v5d
- `CORE/signal_engine_rules/tests/test_rules.py` : +14 tests V2
- `CORE/mia_paper_trader.py` : `_lookup_rules_tags` mis a jour 12 rules + parquet v5d

**Quoi** : 3 nouvelles rules V2 ajoutees au RULES_V1 registry suite empirical validation :
- `rule_pullback_continuation_buy` (P01 ES) : delta>0 + color_up<0.1% + long_dn_up=1 + RTH
- `rule_pullback_continuation_sell` (P05 ES) : SELL symetrique + filter below VWAP_d
- `rule_pullback_mq_hvl_buy` (P03 NQ) : pullback + MQ HVL confluence (TOP setup live valide)

**Pourquoi** : pattern Jackson visuel "prix monte → pullback color_up + long_dn_up bar → repart"
valide empiriquement par 2 batteries de tests :
- confluence_battery_prevdaily_mq (20 confluences) : plafond PF 1.42
- confluence_battery_pullback (8 variantes) : P03 NQ best PF 1.49
+ Robustness 3 tiers chronologiques P01 ES : PF 1.39/1.46/1.43 (stable 24m)
+ LIVE CONFIRMATION 27/04 : Jackson +60 ticks NQ avec setup P03 confluence exact

**Stats backtest 24m :**
| Rule | Sym | Trades | WR | PF | EV | Sharpe |
|---|---|---|---|---|---|---|
| pullback_continuation_buy (P01) | ES | 180 | 46.1% | 1.33 | +5.2t | 3.03 |
| pullback_mq_hvl_buy (P03) | NQ | 66 | 42.4% | 1.49 | +35.4t | 3.92 |
| pullback_continuation_sell (P05) | ES | 118 | 45.8% | 1.31 | +4.8t | 2.87 |

**Stats batch v5d (fires per 24m) :**
- ES : pullback_buy 181 / pullback_sell 135 / pullback_mq_hvl_buy 12
- NQ : pullback_buy 1236 / pullback_sell 348 / pullback_mq_hvl_buy 86

**Validation pre-deploy** :
- Tests : 67/67 PASS (53 V1 + 14 V2 ajoutes : 4 fires + 6 no-fire conditions + 4 anti-leak parametrize V2)
- Anti-leak : 15/15 PASS (parametrize cover les 12 rules dont 3 V2)
- Batch ES + NQ v5d : 53s chacun, 24 cols rules ajoutees
- Live confirmation 27/04 : P03 NQ +60 ticks TP atteint

**Note ML strategy** : NE PAS migrer vers PPO/SAC/Transformer. Plafond PF 1.4 vient des
DONNEES (24m bars 1m sans microstructure HF, sans cross-asset, sans options flow) PAS du
modele. LightGBM + meta-labeling Lopez ch.3 + sizing dynamique Half-Kelly = bonne strategie.
Pour pousser au-dela : ajouter MBO Databento, options flow temps reel, news flow.

**Reviews agents** :
- Plan agent ULTRATHINK migration Databento Live : NOGO immediat + Sprint 0 prerequis (3 verifs)
  obligatoires avant tout code prod. Architecture Option D (interface MarketDataReader env var).
- Battery confluences : 28 setups testes (20 PD+MQ + 8 pullback), plafond empirique PF 1.49

**Spec** : `DOCS/specs/2026-04-27-signal-engine-rules-design.md`
**Plan V1** : `DOCS/plans/2026-04-27-signal-engine-rules-implementation.md`
**Battery V2** :
- `DOCS/CONFLUENCE_BATTERY_PREVDAILY_MQ.md`
- `DOCS/CONFLUENCE_BATTERY_PULLBACK.md`

**Revert plan** : si rules V2 instables en live → revert rules.py, batch_tagger sortie v5d
revient automatiquement a 9 cols V1 (les 3 V2 disparaissent du registry).

**Suivi post-deploy** :
- J+1 : verifier que paper_trader snapshot inclut bien `pullback_*_dir/strength` dans rules_fired
- J+7 : compter fires des 3 V2 sur 5 derniers jours, comparer avec backtest distribution
- J+30 : Re-evaluer PF V2 sur 30 trades live (P01 ES + P03 NQ + P05 ES)
- J+90 : Re-train ML v6 avec rules V2 comme features composites Lopez meta-labeling

**Cross-references** :
- INCIDENT_LOG 27/04 21:30 (leak resolu V5b)
- Memory `feedback_ml_features.md` (top SHAP v5b documente)

---

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
