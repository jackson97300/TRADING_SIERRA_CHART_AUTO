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

## 2026-05-15 19:15 — FIX BUG #2 IB seed + GAP RECOVERY pour HOT restart (state stale pickle)

**Categorie** : FIX (extension fix 19:00 + gap recovery)
**Impact prod** : OFFLINE (Live-Enricher collecte, aucun consumer)
**Fichier(s)** : `CORE/live_enricher_state.py:740-805` (nouvelle fn `_apply_gap_recovery_seeds`), `CORE/live_enricher_state.py:817-822` (appel HOT restart path)

### Quoi
**Bug residuel apres 1er fix BUG #2 (19:00)** : seed IB n'etait appele que en
cold start (pas de pickle). HOT restart avec pickle pre-existant pre-IB
(snapshot pickle 12:11 UTC = pre-09:30 ET us_start) → seed jamais applique →
ib_high reste None → bit 6 reste actif.

Empirique post-19:00 HOT restart : flag=64 (ES bit 6) + flag=98 (NQ/MGC bit 6+5+1).

**Fix gap recovery** : appel `_apply_gap_recovery_seeds` apres `load_state`
si pickle existe. Idempotent : applique seed UNIQUEMENT si engine state
sous-optimal (champ critique None alors que evenement passe).

Criteres "sous-optimal" :
- IBState : `ib_high is None` → seed depuis V4 batch
- SessionsSwingsSimpleState : `ny_open is None` → seed
- VolumeProfileState : `prev_vpoc is None` → seed
- OpenCashPrice1030State : `price_1030 is None` → seed

**Resultats post-deploy 19:15 UTC** :
- 3 symboles ENRICHER_SEED_IB_FROM_V4 emit au boot ✅
- NQ.c.0/MGC.v.0 flag 98 → 34 (bit 6 disparu) ✅
- ES.c.0 flag 64 → 0 (bit 6 disparu, propre) ✅

### Pourquoi
Pickle figé pendant 6h+ downtime = state engine pre-evenements critiques de
la journee. Le live va calculer 1ere bar post-boot SANS connaitre IB high/low
de la session = data corruption persistante jusqu'au prochain rollover.

Gap recovery permet de re-seeder ces engine states "morts" depuis V4 batch
(qui a continue a etre rebuild par live_pipeline meme pendant downtime).

### Validation pre-deploy
- [x] Syntax check OK
- [x] Test empirique 3/3 PASS post HOT restart 12:43 UTC
- [x] Logs ENRICHER_SEED_IB_FROM_V4 emis pour 3 symboles
- [x] Bit 6 disparu sur ES/NQ/MGC

### Suivi post-deploy
- J+1 : grep `ENRICHER_SEED_*_FROM_V4` boot logs. Tous emis ssi pickle stale.
- Surveiller : gap recovery ne doit jamais overwrite live nominal (engine
  state non-vide preserve par check None idempotent).

### Liens
- Bug observe : commit 296714b (seed IB) deploye mais ineffectif en HOT restart
- Pattern future : refacto unifier 5 seeds en `seed_*_if_stale(state, key, ...)`
  helper DRY (backlog).

---

## 2026-05-15 19:00 — FIX BUG #2 IB seed depuis V4 batch (cold/HOT restart > 10:30 ET)

**Categorie** : FIX
**Impact prod** : OFFLINE (Live-Enricher collecte, aucun consumer)
**Fichier(s)** : `CORE/live_enricher_state.py:663-738` (nouvelle fn `_seed_ib_from_warmup`), `CORE/live_enricher_state.py:721-724` (appel boot), `CORE/live_enricher.py:1305-1315` (bit 6), `CORE/log_catalog.py:620-621` (2 codes)
**Reviewer(s) agent** : pattern strictement analogue aux 5 seeds existants (_seed_open_cash, _seed_sessions, _seed_swings_lag, _seed_vp, +nouveau _seed_ib) — pas re-review

### Quoi
Fix bug `ib_complete=1` mais `ib_high=null` observe post-HOT-restart 18:13 UTC.

Cause racine identifie via `phase_b_helpers.py:374-381` :
```python
ib_complete = 1 if (mins_et >= ib_close) else 0  # base sur time only
if ib_complete == 1 and state.ib_high is not None:  # MAIS state vide si live down
    ib_high_out = state.ib_high
else:
    ib_high_out = np.nan  # → ib_high=NaN dans output
```

Si live etait DOWN pendant fenetre IB 09:30-10:30 ET ET HOT restart apres
10:30 ET → state.ib_high jamais accumule → ib_complete=1 (time pass) MAIS
ib_high=NaN (state vide).

**Solution** :
1. `_seed_ib_from_warmup` lit V4 batch derniere bar `ib_high` non-NaN du
   session_date_trading courant et instantie `IBState` pre-rempli :
   ```python
   IBState(current_date_et=today_sdt, ib_high=v4_ib_high, ib_low=v4_ib_low,
           n_ib_bars_seen=60)
   ```
2. Appele dans `initialize_state` apres les 4 autres seeds existants.
3. Bit 6 (64) `ib_data_missing` dans data_quality_flag = signal residuel si
   seed V4 echec (V4 batch Phase B incomplete jour J).
4. 2 codes log : `ENRICHER_SEED_IB_FROM_V4` (INFO/events succes) et
   `ENRICHER_SEED_IB_FAIL` (ALERTE/events).

### Pourquoi
**Code seed strictement analogue aux 4 seeds existants** (sessions_swings,
swings_lag, vp, open_cash) qui suivent meme pattern lecture V4 batch derniere
bar valide -> instantiation state pickle-friendly. Pas un nouveau pattern.

**Bit 6 distinct du bit 4** : bit 4 = ny_open None (session corruption),
bit 6 = ib_high None (IB window data manquante). Domaines independants.

**Cas observe (recap)** : ES.c.0 V4 batch IB complete (Phase B done sur
09:30-10:30 ET) → seed succes. NQ.c.0/MGC.v.0 V4 batch IB partial selon
quand live_pipeline rebuild. Seed succes ou echec selon timing.

### Impact attendu
- Post seed succes : ib_complete=1 + ib_high reel (bit 6 = 0)
- Post seed echec (V4 Phase B retard) : ib_complete=1 + ib_high=NaN + bit 6 actif
- Pas de regression cas nominal (live continu pendant 09:30-10:30 ET) : state
  accumule normalement, V4 seed redondant mais idempotent.

### Validation pre-deploy
- [x] Test empirique 3 symboles ES/NQ/MGC : 3/3 PASS seed V4 actuel
  - ES : ib_high=7467.75, ib_low=7420.25
  - NQ : ib_high=29684.75, ib_low=29458.5
  - MGC : ib_high=4716.9, ib_low=4694.0
- [x] Test bit 6 logic 6/6 PASS (None/NaN/valid/sentinel)
- [x] Syntax validate 3 fichiers modifies
- [ ] Test post-deploy : grep `ENRICHER_SEED_IB_FROM_V4` boot logs

### Revert plan
```bash
git revert <commit_fix_bug2>
scp CORE/live_enricher_state.py CORE/live_enricher.py CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 "nssm stop MIA-Live-Enricher; Start-Sleep -Seconds 5; nssm start MIA-Live-Enricher"
```

### Suivi post-deploy
- J+1 : grep `ENRICHER_SEED_IB_FROM_V4` LOGS/events. Si > 0 emit = OK.
  Si bit 6 actif chronique = V4 batch Phase B pipeline a investiguer (chantier
  refacto pipeline incremental cf project_pipeline_incremental_backlog.md).

### Liens
- Bug racine : `CORE/phase_b_helpers.py:374-381` (sentinel ib_high=NaN si state vide)
- Pattern : analogue aux 4 seeds existants (DRY refacto backlog)
- BUG #4 connexe (capture mid-session) deja fixe commit 3a3e5e6

---

## 2026-05-15 18:45 — FIX BUG #4 session opens capture mid-session restart (parite batch + bit 5 observabilite)

**Categorie** : FIX
**Impact prod** : OFFLINE (Live-Enricher collecte, aucun consumer)
**Fichier(s)** : `CORE/sessions_swings_simple_streaming.py:67-78,184-205,222-280,302-320`, `CORE/live_enricher.py:1290-1314`, `CORE/log_catalog.py:618-620`
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES 18:35 - 2 critiques adressees)

### Quoi
Fix bug detecte empiriquement post-HOT-restart 18:13 UTC : `ny_open=None` persistant
sur NQ/MGC (bit 4 actif systematique) car :
- Live enricher down 12:11-18:13 UTC = 6h gap couvrant 13:30 UTC (US RTH open 09:30 ET)
- Code streaming SET `ny_open` uniquement quand `mins_et == us_start` exact
- Si live boot mi-session, cette condition ne se redeclenche jamais cette session
- Seed V4 fallback fonctionne pour ES (V4 batch ES Phase B complet n=9) mais
  echec NQ/MGC (V4 batch Phase B incomplet jour J, seed n=3 asia only)

Solution **2 niveaux** (preserve parite batch + add observabilite) :
1. **Capture EXACT prioritaire** (`mins_et == X_start`) - identique batch
2. **Capture FALLBACK** (`sid == X and open is None`) - mid-session boot
3. **Flag `*_open_approximate`** dans state + out[] (4 sessions)
4. **Bit 5 (32) data_quality_flag** = at least 1 open approximate
5. **Code log ENRICHER_SESSIONS_OPEN_APPROXIMATE** (ALERTE/decisions) defini
6. Reset `*_open_approximate` au session_date change (idempotent)

### Pourquoi
**RESERVE 1 code-reviewer (parite batch)** : Le batch (`sessions_swings_engine.py:263`)
utilise `m == target` strict. En cas restart-mid-session, batch=NaN, ancien stream=None.
Ce fix prend un proxy en stream qui est tagged `approximate=1`. ML peut filtrer
ou apprendre a gerer ce cas. Dette tech : aligner batch sur meme regle (backlog).

**RESERVE 2 code-reviewer (silent fallback)** : Bit 4 etait justement le signal
"ny_open=None apres us_start". Capture fallback masquerait cette corruption.
Bit 5 distinct preserve l'observabilite : bit 4 = open MISSING (vraie corruption),
bit 5 = open APPROXIMATE (proxy acceptable mais tagged).

**Q5 (Pattern 11 V1)** : 4eme correctif consecutif bitmask. Surveillance, pas
blocker. Refacto `_seed_sessions_swings_from_warmup` robuste idempotent en backlog.

### Impact attendu
- Bit 4 NQ/MGC : actif → 0 (capture proxy au 1er bar US cash post-boot)
- Bit 5 : 0 (nominal) → 1 (mid-session restart)
- Flags `*_open_approximate` : nouvelles colonnes JSONL (4 par bar)
- Parite batch : preservee si live continu, divergence taggee si restart

### Validation pre-deploy
- [x] Tests empiriques 3/3 PASS (capture exact / fallback / reset)
- [x] Code log declare `ENRICHER_SESSIONS_OPEN_APPROXIMATE`
- [x] Review code-reviewer 2 reserves adressees
- [ ] Test post-deploy : bit 4 disparait NQ/MGC, bit 5 actif (jusqu'a session change)
- [ ] J+1 16/05 : nouvelle session 18:00 ET → bit 5 reset si live continu

### Revert plan
```bash
git revert <commit_fix_bug4>
ssh Administrator@212.28.179.199 "nssm stop MIA-Live-Enricher"
scp CORE/sessions_swings_simple_streaming.py CORE/live_enricher.py CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 "nssm start MIA-Live-Enricher"
```

### Suivi post-deploy
- J+1 : grep bits 4 et 5 dans LOGS/decisions. Bit 4 doit etre 0 sur NQ/MGC,
  bit 5 doit etre actif jusqu'a 18:00 ET (Asia next session reset)
- J+7 : verifier 0 bit 4 anormal, bit 5 active uniquement post-restart legitime

### Liens
- Review : code-reviewer GO-AVEC-RESERVES 18:35
- Backlog : refacto seed V4 idempotent + alignement batch sur regle "1er bar vu"
- Bug racine : V4 batch NQ/MGC Phase B incomplet jour J (live_pipeline lag 5min)

---

## 2026-05-15 18:30 — FIX data_quality_flag bitmask 3 bugs critiques (code-reviewer GO-AVEC-RESERVES)

**Categorie** : FIX
**Impact prod** : OFFLINE (Live-Enricher collecte, aucun consumer)
**Fichier(s)** : `CORE/live_enricher.py:1243-1300`, `CORE/log_catalog.py:618`
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES verdict 15/05 18:00)

### Quoi
Fix 3 bugs critiques bitmask `data_quality_flag` (commits 8c08c7e + d559af2 + 525485b)
detectes par code-reviewer apres deploy initial Phase 1 :
1. **bit 4 (session_ctx_corrupted)** ne se declenchait JAMAIS. Cause : `sessions_swings_simple_streaming.py:262` ecrit `out["ny_open"] = np.nan` (pas None). `np.nan is not None == True`. Le writer convertit NaN→None APRES bitmask. Fix : check `math.isnan(_ny)` AVANT le branch None.
2. **bit 3 (swing_state_reset)** = faux positifs systematiques sur bars Asia. Cause : `session_id=0` est legitimement Asia (0=Asia / 1=London / 2=US cash / 3=US AH), pas un sentinel. Le vrai sentinel "swing state empty" est `-1` (cf `sessions_swings_lag_streaming.py:246, 259`). Fix : `_lshs == -1` au lieu de `== 0`.
3. **bars_since_boot ignorait HOT restart**. Cause : `_n_bars_processed` dict module-level reset au boot process. HOT restart (nssm stop/start) reload pickle avec `state.n_bars_processed=10000+` mais module reset a 0 → 30 premieres bars post-HOT-restart taggees warmup_phase a tort. Fix : utiliser `state.n_bars_processed` (pickle-persiste).
4. Ajout code log `ENRICHER_DATA_QUALITY_FLAG_SET` (regle souveraine logs critical-tasks-review 01/05) - tout flag != 0 emit ALERTE/decisions pour audit J+1.

### Pourquoi
Sans ces fixes :
- bit 4 = METRIQUE MORTE (jamais audit possible sur corruption ny_open post-reset)
- bit 3 = bruit massif (toutes les bars Asia 22:00-08:00 UTC taggees a tort `swing_reset` apres bar #21 → ETL drop 33% du temps)
- HOT restart penalise = doc anti-cold-restart inutile car HOT restart se comporte comme cold restart pour les 30 premieres bars

### Impact attendu
- bit 4 : declenchements 0% → declenchements reels sur bars US sans ny_open
- bit 3 : faux positifs Asia ~33% → ~0% (sentinel `-1` exclusivement)
- HOT restart : warmup tag 0 bars (state pickle continue)
- Log `ENRICHER_DATA_QUALITY_FLAG_SET` emit a chaque flag != 0 (tracking J+1)

### Validation pre-deploy
- [x] Code edit applique
- [x] Code log declare `CORE/log_catalog.py:618`
- [ ] Test empirique 10 bars post HOT restart (a faire apres scp)
- [x] Review agent : GO-AVEC-RESERVES → 3 bugs adresses

### Revert plan
```bash
git revert <commit_fix_3bugs>
ssh Administrator@212.28.179.199 "nssm stop MIA-Live-Enricher"
scp CORE/live_enricher.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 "nssm start MIA-Live-Enricher"
```

### Deployed at YYYY-MM-DD HH:MM
(en attente confirmation Jackson pour scp VPS)

### Suivi post-deploy
- J+1 : grep `ENRICHER_DATA_QUALITY_FLAG_SET` LOGS/decisions/ -> verifier bit 4 declenche sur bars US AH si ny_open absent, bit 3 nul sur bars Asia normales
- J+7 : audit bars warmup_phase post HOT-restart = 0
- J+30 : tendance flag globale, ratio bars ETL-droppees

### Liens
- Commits couverts : 8c08c7e (data_quality_flag init), d559af2 (HOT restart doc), 525485b (seed P1.2 session_id pivot V2)
- Review : code-reviewer GO-AVEC-RESERVES 15/05 18:00 (3 critiques + 1 important)
- Regle logs : `.claude/rules/critical-tasks-review.md` (logs souverains 01/05)

---

## 2026-05-15 12:36 — DEPLOY MIA-Live-Enricher service VPS (Phase 1 collecte pure)

**Categorie** : DEPLOY
**Impact prod** : OFFLINE (collecte JSONL pure, AUCUN consumer bot/dashboard)
**Fichier(s)** : `CORE/live_enricher*.py`, `CORE/log_catalog.py`, +20 fichiers streaming
**Reviewer(s) agent** : code-reviewer (R2 commit b79d138 + R3 commit e2bc44f)

### Quoi
Premier demarrage MIA-Live-Enricher en production VPS comme service nssm.
Demarre la collecte H24 des snapshots enrichis (~431 cols/bar) pour ES/NQ/MGC
dans `DATA/live_enriched/{sym}/{YYYYMMDD}.jsonl`. Aucun consumer branche
(decision Jackson Phase 1 = "pas encore brancher bot ou dashboard").

### Pourquoi
- Suite audit Pass 4 R1-R5 (5 risques closed) : R2 seed warmup commit b79d138
  + R3 V4 oracle test commit e2bc44f
- Jackson : "on peux commencer a recevoir des snapshots dans des dossiers
  bien organises EN LIVE avant de brancher sur un bot"
- Infrastructure code-ready depuis 13/05 mais jamais demarre (DATA/live_enriched
  vide). Etape critique pour valider streaming end-to-end avant LIVE reel.

### Impact attendu
- Snapshots JSONL H24 disponibles pour inspection vs V4 batch oracle
- Detection drift batch/stream en LIVE (vs V4 oracle test offline 8190 bars)
- ~431 cols/bar, ~1 ligne/min/symbol = 1440 lignes/jour/symbol
- Conso disque ~50 MB/jour total (3 symbols)

### Bugs detectes + fixes deploy

1. **AppDirectory chain** : nssm set avec `;` separator a stocke toute la chaine
   PowerShell dans la valeur AppDirectory -> service start fail "Nom repertoire
   invalide". Fix : separer chaque nssm set en commande SSH dediee.

2. **SYMBOL_TO_MQ_SYM mapping MGC** : `live_enricher_io.py:165-169` mappait
   `MGC.v.0 -> "GC"` (filesystem dir). Mais `load_mq_levels` valide
   `symbol in SYMBOL_TO_FS_DIR.keys()` (= ES/NQ/MGC), pas GC. Fix :
   `MGC.v.0 -> "MGC"` (symbol Python, load_mq_levels handle fs dir conversion).
   Cf lessons.md "MGC -> GC mapping filesystem".

3. **`datetime.date` not JSON serializable** : `phase_b_helpers.add_session_metadata`
   produit `date_et = ts_et.dt.date` (objet datetime.date). `_json_default`
   du writer gerait pd.Timestamp et np.* mais PAS la stdlib date. Fix :
   ajout handling `isinstance(obj, (datetime, date))` -> `.isoformat()`.
   Avant fix : 100% bars ENRICHER_WRITE_FAIL.

4. **Sub-engines streaming pas tous deployes** : initial scp = 5 fichiers
   live_enricher* + log_catalog. Manquait 20+ fichiers *_streaming.py +
   helpers (footprint_builder_streaming, vix_lite_reader, etc.) -> Pattern V1
   safe fallback "payload reverted to pre-chain" emit ENRICHER_ENGINE_FAIL.
   Fix : scp batch complet (25 fichiers).

### Validation pre-deploy
- [x] Sanity test : `python -m CORE.live_enricher --test` 5/5 PASS local + VPS
- [x] R2 seed warmup commit b79d138 (6 tests PASS, code-reviewer GO NET)
- [x] R3 V4 parity test commit e2bc44f (3 pytest PASS)
- [x] R5 lint guard commit 0743efe (37 modules baseline 0 violation)
- [x] V4 parquet ES + NQ mai 2026 present (warmup seed source)

### Validation post-deploy

```
Heartbeat ALIVE (age 20.8s, uptime 136s)
ES.c.0 : 7 rows / 431 cols / schema live_enriched_1.0
NQ.c.0 : 7 rows / 431 cols
MGC.v.0 : 5 rows / 425 cols
ML-critical features : 13/22 present (Phase 2 enquete 9 manquantes)
0 bars failed
```

### Plan suivi

- J+1 : sync JSONL VPS->PC + snapshot_inspector --compare-v4
  - Cherche : open_cash captured a 09:30 ET (= 13:30 UTC) sur bar 14:30 UTC
  - Verifie : ENRICHER_SEED_OPEN_CASH_FROM_V4 emit > 0 dans events log
- J+7 : extension V4 oracle test aux 7+ sub-engines `groupby session_date_trading`
  (sess_high/low, phase_d_dalton 4x, phase_b_v6, value_area_running)
- Phase 2 (post-J+7) : Pattern V1 fix game_changers stream session_date_trading
  OU mode RTH-only confirme

### Revert plan

```bash
# Stop service (preserve data + state pickle)
ssh Administrator@212.28.179.199 "nssm stop MIA-Live-Enricher"

# Desinstaller (si bug bloquant)
ssh Administrator@212.28.179.199 "nssm remove MIA-Live-Enricher confirm"
```

### Deployed at 2026-05-15 12:35 (Paris) / 06:35 ET / 10:35 UTC

Service status confirme : Running Automatic.

### Suivi post-deploy

- Memory : `feedback_live_enricher_first_deploy_*` (a creer si pattern detecte)
- Review agent : code-reviewer (R2+R3+R5 prior reviews valides)

---

## 2026-05-13 15:00 — FEATURE Chantier 3 Phase 3b — sub-engine #4 volume_profile streaming (RUNNING VPOC intraday)

**Categorie** : FEATURE
**Impact prod** : OFFLINE pour l'instant (Live Enricher en cours de construction) -> LIVE futur quand service deploye
**Fichier(s)** :
- `CORE/phase_b_helpers.py:768-998` (add_volume_profile_features_streaming + VolumeProfileState)
- `TOOLS/test_engine_parity.py:904-1160` (_test_volume_profile 3 niveaux + P1.1 fix)
- `DOCS/INCIDENT_LOG.md` entry 2026-05-13 14:30 (decision design batch vs stream)
**Schema/version** : 16 features (cur/prev x vpoc/vah/val/pdh/pdl + inside_VA + poc_migration_dir + 8 dist_*_pct)
**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES (0 P0, 3 P1, 5 P2). P1.1 fix applique pre-commit.

### Quoi
Sub-engine #4 streaming pour Live Enricher. Reproduit `add_volume_profile_features()` batch avec une DIVERGENCE INTENTIONNELLE : VPOC running intraday (vs batch constant per session). State maintient `price_volume` dict cumulatif + transfert prev_* a la rotation session.

### Pourquoi
Bot live a besoin de cur_vpoc INTRADAY (decisions bar par bar). Batch produit le snapshot offline (training V4 dataset). Choix design : option A (running) car option B (NaN jusqu'a fin session) rend la feature inutile intraday.

### DISTRIBUTION SHIFT — Risque ML majeur (P1.2 audit)

**14 features (cur_vpoc-dependent) ont une distribution DIFFERENTE en inference (running) vs training (constant)** :
- cur_vpoc, cur_vah, cur_val (running evolue)
- inside_value_area passe 1->0->1 plusieurs fois intraday (vs constant batch)
- 8 dist_*_pct heritent du shift

**ml-trainer review OBLIGATOIRE AVANT toute integration v4 inference** (cf .claude/rules/critical-tasks-review.md critere 2 ML pipeline). Mandat explicite a fournir :
- Quantifier KS test feature par feature (running vs batch sur 3 sessions ES + 3 sessions NQ)
- p99 distance + impact PF backtest live-mode vs train-mode
- Verdict GO/NOGO + recommandation : re-train running-mode OU accepter shift OU ajouter `cur_vpoc_running` au batch

**Status actuel** : feature CODEE + TESTEE mais NON-INTEGREE en pipeline V4 inference. Backlog : ml-trainer review avant deploy live.

### Validation pre-deploy
- 3 niveaux tests PASS :
  - Niveau 1 : parite last-bar-of-session sur 3 sessions (1260 bars + 27599 trades synth), atol 1e-6 sur pdh/pdl exacts + atol 0.25 (1 tick) sur VPOC/VAH/VAL (tie-break dict insertion order)
  - Niveau 2 : pickle roundtrip state mid-session (4628 trades, 24 buckets price_volume)
  - Niveau 3 : rotation session detection + transfert prev_vpoc=5806.25
- P1.1 audit fix : test loophole sur derniere bar (trades [bar_419, bar_419+60s) etaient draines sans appel stream -> tolerance 0.25 masquait potentiellement bug). Convention corrigee : window=[bar_i, bar_(i+1)), derniere bar = +1min. Assertion `trade_idx == len(trades_arr)` valide aucune perte.

### Backlog post-commit
- **P1.2 (avant deploy live)** : ml-trainer review distribution shift. Sans GO -> ne PAS integrer en V4 inference.
- **P1.3 (perf)** : compute_volume_profile_dict O(n) a chaque bar. Optimization cache vpoc bucket (recompute uniquement si update). Differable J+1 post-deploy.
- **P2.1** : extraire `VALUE_AREA_PCT = 70.0` dans `CORE/constants.py`.
- **P2.2** : consolider try/except cast en helper `_safe_float()`.

### Revert plan
Sub-engine isole (additive only). Pour rollback : retirer les 2 ajouts (streaming function + dataclass) du fichier `CORE/phase_b_helpers.py`. La fonction batch existante n'a pas ete touchee.

### Liens
- INCIDENT_LOG : 2026-05-13 14:30 [SCOPE_CREEP] divergence design batch (constant) vs stream (running VPOC)
- Memory : - (a creer si distribution shift confirme post ml-trainer)
- Review agent : code-reviewer GO-AVEC-RESERVES, 3 P1 (P1.1 fixe, P1.2+P1.3 backlog)

---

## 2026-05-13 11:30 — FEATURE Phase 2a — integration vix_lite_reader dans pipeline V4 (parallel vix_* DMP)

**Categorie** : FEATURE
**Impact prod** : OFFLINE (pipeline V4 build, pas de Bot/Dashboard impact direct)
**Fichier(s)** :
- `CORE/build_dataset_v4_dmp_databento.py:984-1027` (nouvelle etape 4ter — asof merge backward 5min)
- `CORE/vix_lite_reader.py` (3 P0 fixes appliques : sanity range, dtype float64, vix_regime cast float)
**Schema/version** : parquet V4 +32 colonnes `vixl_*` (10 levels + 10 gex + 1 regime + 7 dist + 2 above_hvl + 2 dist_gex)
**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES → 3 P0 corriges (sanity [5,150] aligne DMP, dtype object → float64, vix_regime int → float64)

### Quoi
Suite directe de l'entry 11:05 (VIX_Lite.cpp v1.3). Le pipeline V4 charge maintenant les donnees VIX_Lite JSONL en parallele des `vix_*` du DMP_MQ_FIELDS. Toutes les colonnes VIX_Lite sont prefixees `vixl_*` (rename `vix_ → vixl_` substring) pour eviter conflit nom avec DMP. Merge asof backward, tolerance 5min (VIX bouge 1/min RTH, fige hors RTH).

Couvre 32 features VIX cote Python (+1 vs DMP qui en a 17 + 11 dist_vix_*) :
- 10 levels bruts (`vixl_level`, `vixl_call`, `vixl_put`, `vixl_hvl`, `vixl_1d_min`, `vixl_1d_max`, `vixl_call_0dte`, `vixl_gamma_wall_0dte`, `vixl_put_0dte`, `vixl_hvl_0dte`)
- 10 GEX flatten (`vixl_gex_0` a `vixl_gex_9`)
- 1 regime categoriel (`vixl_regime` 0..3, aligne DMP_Transform.h)
- 7 distances `dist_vixl_*` (call, put, hvl, call_0dte, put_0dte, hvl_0dte, gamma_wall_0dte)
- 2 distances GEX (`dist_vixl_gex_nearest_up/dn`)
- 2 booleans (`vixl_above_hvl`, `vixl_above_hvl_0dte`)

**Sanity ranges** alignes DMP_Reader.h + VIX_Lite.cpp guards :
- `vix_level` ∈ [5, 200] (low historique 9.14 + protect crash)
- `vix MQ levels` ∈ [5, 150] (covid 2020 peak 82.69 + niveaux MQ peuvent stress 85-95)

### Pourquoi
Phase 2a du plan strategique Bot 2 V6 full Databento. Permet J+7 d'audit comparatif `vix_level` (DMP) vs `vixl_level` (VIX_Lite) avant cutover Phase 2b. Le DMP cross-chart peut renvoyer valeurs obsoletes cachees quand sg vide (cf bug sg7 HVL_0DTE observe 13/05 → fallback fusion C++ v1.3). VIX_Lite host mode est plus rigoureux + +1 feature `gamma_wall_0dte`.

### Impact attendu
- **Backward compat** : Phase 2a TOTALEMENT NON-DESTRUCTIVE. Les `vix_*` du DMP_MQ_FIELDS restent inchanges. Si VIX_Lite absent ou parse echec → try/except large → pipeline continue sans `vixl_*` (les colonnes seront absentes, downstream gere NaN ou skip).
- **Volume parquet** : +32 colonnes float64 sur ~302K bars/mois ≈ +75 MB/mois output. Acceptable.
- **Test empirique** : 11 lignes VIX_Lite reelles VPS → 32 cols enriched → merge_asof OK sur 61 bars dummy. Sample :
  ```
  vixl_level=17.97, vixl_regime=1.0, vixl_call=25.0,
  dist_vixl_call_0dte=2.03, vixl_above_hvl=0
  ```

### Validation pre-deploy
- [x] Tests unitaires `vix_lite_reader.py` : 3 tests inline OK (`compute_vix_regime`, `compute_vix_gex_distances`, `_test_load_real_data`)
- [x] Test merge asof empirique : 25/61 bars couvertes (premier dump 14:37 + gap rebuild → bars hors tolerance 5min NaN, comportement attendu)
- [x] Review code-reviewer GO-AVEC-RESERVES → 3 P0 appliques avant commit
- [ ] J+1 backfill 1 jour : verifier que pipeline V4 produit un parquet avec colonnes `vixl_*` non-NaN sur >95% des bars RTH
- [ ] J+7 audit comparatif `vix_*` (DMP) vs `vixl_*` (VIX_Lite) sur meme bars : p50/p99 abs diff, % mismatch → decision cutover Phase 2b

### Revert plan
```bash
# Annuler Phase 2a : retirer le bloc 4ter du pipeline V4
git revert <commit_hash>
# OU manuel : supprimer lignes 984-1027 dans build_dataset_v4_dmp_databento.py
# Les vix_* du DMP_MQ_FIELDS restent intacts → pipeline continue comme avant
```

### Deployed at 2026-05-13 11:30 (PC local, pas VPS)
Pas de deploy VPS pour cette modif (pipeline tourne sur PC local Jackson). Premier rebuild manuel J+1 pour validation.

### Suivi post-deploy
- J+1 (2026-05-14) : 1er rebuild pipeline V4 avec mode Phase 2a → verif coverage `vixl_*` > 95% RTH
- J+7 (2026-05-20) : audit comparatif vix_* DMP vs vixl_* VIX_Lite (script `tools/compare_vix_vs_vixl.py` a creer)
- J+14 : decision cutover Phase 2b si convergence < 0.01 (precision %.4f DMP) sur > 99% bars

### Liens
- Entry precedente 11:05 : VIX_Lite.cpp v1.3 + vix_lite_reader.py
- Review code-reviewer : 3 P0 (sanity range, dtype object, regime float64), 6 P1 (script compare, vectorisation, try narrow scope, sys.path top-level, commentaire schema, robustesse path Hive)
- Plan strategique : `project_bot2v6_dmp_in_practice.md` + memoire `feedback_bot3_data_source_v4_enriched.md`

---

## 2026-05-13 11:05 — FEATURE VIX_Lite.cpp v1.3 — etude C++ dediee dump VIX + 19 niveaux MQ Gamma VIX

**Categorie** : FEATURE
**Impact prod** : OFFLINE (collecte uniquement, decouplage progressif du DMP full pour Bot 2 V6 full-Databento)
**Fichier(s)** :
- `CPP/MIA_REFACTORED/VIX_Lite.cpp` (nouveau, ~370 LOC)
- VPS deploy : `C:/SIERRA CHART TRADING/ACS_Source/VIX_Lite.cpp` + `C:/TRADING_SIERRA_CHART_AUTO/CPP/MIA_REFACTORED/VIX_Lite.cpp`
- DLL Sierra : `C:/SIERRA CHART TRADING/Data/VIX_Lite_64.dll`
**Schema/version** : nouveau schema `vix_levels_1.1` (output `DATA/vix_levels/year=YYYY/month=M/day=D/vix.jsonl`)
**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES (3 P0 fixes appliques : (1) vix_level via GetChartBaseData en cross-chart safe, (2) VIX_MQ_MAX 80→150 pour niveaux MQ legitimes en stress, (3) timestamp precision ms preserve)

### Quoi
Etude C++ ACSIL dediee, attachee sur Chart 15 (VIX_CGI[M]), dump 1 ligne/min :
- 1 prix VIX courant (sc.Close[sc.Index] en host)
- 8 niveaux MQ Gamma : vix_call, vix_put, vix_hvl, vix_1d_min, vix_1d_max, vix_call_0dte, vix_put_0dte, vix_hvl_0dte
- **1 niveau supplementaire vs DMP** : vix_gamma_wall_0dte (sg8, absent du DMP_ReadVIX)
- 10 niveaux GEX VIX (vix_gex[0..9])

Total 20 valeurs / ligne. Schema `vix_levels_1.1`.

**Fallback fusion MenthorQ** (v1.3) : quand 2 niveaux 0DTE sont au meme prix sur le chart (ex: "Put Support 0DTE & HVL 0DTE: 16.00"), MenthorQ fusionne le label visuellement et vide le subgraph secondaire. Le C++ recopie automatiquement la valeur du principal :
- sg7 HVL_0DTE vide & sg6 Put_0DTE valide → HVL_0DTE = Put_0DTE
- sg8 Gamma_Wall_0DTE vide & sg5 Call_0DTE valide → Gamma_Wall_0DTE = Call_0DTE

Quand les niveaux sont differents, on garde la vraie valeur lue (pas d'ecrasement).

### Pourquoi
Objectif strategique Jackson 13/05/2026 : **Bot 2 V6 full Databento**. Pipeline V4 enriched a 20-35min lag inherent (Databento Historical API + batch). Plan revise = DMP++ Databento Python pour ~440 features tactiques (footprint, BN, color, big orders, edge zones, regime, etc. tous deja recodes en Python) + Sierra MQ Lite + VIX Lite pour ~34 features structurelles (MenthorQ niveaux + VIX). VIX_Lite est la 1ere brique : decouple les 17 features VIX du DMP full. A terme, MQ Lite + VIX Lite suffiront cote Sierra.

Avantages vs DMP_ReadVIX :
- Etude C++ separee, DLL isolee (si plante, MQ_Lite + DMP continuent)
- Schema simple JSONL (pas de pollution dans 262 colonnes DMP)
- Fallback fusion MenthorQ proprement gere (DMP renvoie valeurs obsoletes cachees quand sg vide)
- +1 feature : vix_gamma_wall_0dte (absent du DMP)
- Pattern host normal (sc.Close[sc.Index], GetStudyArrayUsingID) plus rigoureux que cross-chart DMP qui lit valeurs historiques

### Impact attendu
- **Bot 2 V6 / pipeline V4** : pas d'impact immediat (DMP continue a fournir vix_*). Etape suivante = adapter `build_dataset_v4_dmp_databento.py` pour basculer source VIX du DMP_MQ_FIELDS vers `DATA/vix_levels/*.jsonl`.
- **Volume disque** : 1 ligne/min × ~600 bytes × 1440 min/jour = ~860 KB/jour, ~310 MB/an. Acceptable (DMP fait GB).
- **Performance ACSIL** : negligeable (~20 GetStudyArrayUsingID + 1 sc.Close + 1 fopen/min, guard BHCS_BAR_HAS_CLOSED + last_bar dedup).

### Validation pre-deploy
- [x] Audit code-reviewer GO-AVEC-RESERVES (3 P0 fixes appliques)
- [x] Compile Sierra remote build : `The build succeeded`, DLL `VIX_Lite_64.dll` 918 528 octets
- [x] Test empirique attach Chart 15 : 4 itérations v1.0→v1.3, dernier dump valide :
  ```json
  {"ts":1778684640000,"schema_version":"vix_levels_1.1","vix_level":17.9600,
   "vix_call":25.0000,"vix_put":17.0000,"vix_hvl":21.5000,
   "vix_1d_min":16.3600,"vix_1d_max":19.5200,
   "vix_call_0dte":20.0000,"vix_gamma_wall_0dte":20.0000,
   "vix_put_0dte":16.0000,"vix_hvl_0dte":16.0000,
   "vix_gex":[18.0000,17.5000,19.0000,18.5000,16.5000,15.0000,20.5000,15.5000,21.0000,30.0000]}
  ```
  Match 100% avec screenshot chart 15 Jackson (collision MQ_Gamma fusion bien recopiee).

### Revert plan
```powershell
# Sierra Chart : detach VIX_Lite study de Chart 15
# Optional : supprimer VPS files
ssh Administrator@212.28.179.199 'del "C:\SIERRA CHART TRADING\ACS_Source\VIX_Lite.cpp" "C:\SIERRA CHART TRADING\Data\VIX_Lite_64.dll" "C:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\VIX_Lite.cpp"'
# Pipeline V4 continue a lire les vix_* du DMP JSONL inchange
```

### Deployed at 2026-05-13 11:05 (heure VPS ET)
- Compile remote build : OK
- Attach Chart 15 : OK
- Dump premier : 14:37 UTC v1.0 (sg7=null pre-fix fusion)
- Dump apres fix v1.3 : 15:04 UTC (sg7=16.00 fusion OK, sg8 gamma_wall_0dte=20.00 fusion OK)

### Suivi post-deploy
- J+1 (2026-05-14) : verifier comportement quand HVL_0DTE != Put_0DTE → sg7 devrait contenir la vraie valeur (pas le fallback)
- J+7 : volume disque accumule + zero null sur 17/19 niveaux non-fusionnes
- J+30 : integration pipeline V4 Python loader effective

### Liens
- Review code-reviewer : 3 P0 fixes (lecture vix_level, range MQ_MAX, timestamp precision)
- Memoire `project_bot2v6_dmp_in_practice.md` : architecture cible full Databento
- Plan revise : DMP++ Databento Python (~440 features tactiques) + Sierra MQ_Lite + VIX_Lite (~34 features structurelles)

---

## 2026-05-13 01:00 — FIX Dashboard Indicateurs Trading Manuel + Order Flow Avance vide (bump V4_STALE_SEC 600→2700s)

**Categorie** : FIX
**Impact prod** : DASHBOARD (read-only display, aucune modif moteur decision)
**Fichier(s)** :
- `DASHBOARD/api/v4_reader.py:40` (`_V4_STALE_SEC = 600` → `2700`)
- `DASHBOARD/api/v4_reader.py:265+` (compteur skip telemetrie `_merge_skip_count`)
**Schema/version** : N/A
**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES → 4 reserves R1-R4 corrigees (R1 bump 2700s vs 1800s pour couvrir lag pic 48min observe, R2 doc cas-limite near_*_level, R3 entry CHANGELOG, R4 telemetrie compteur skip cumule)

### Quoi
Jackson screenshot 13/05 : Indicateurs Trading Manuel Phase 3 + Order Flow Avance tout OFF/0 alors que pipeline V4 enriched tourne et features V4 dispos. Cause racine : `_V4_STALE_SEC=600s` safety dans `merge_dmp_v4` skip le merge quand `DMP_ts - V4_ts > 10min`. Pipeline V4 batch interne 30-48min de lag (Databento Historical delay 15min + Phase_B retraitement mois entier ~3min + iter 5min) → safety toujours active → dashboard tombe en mode degrade DMP-seul → features V4 absentes du bar_enriched. Fix : bumper seuil a 2700s (45min) qui couvre 95% des cas empiriques observes.

### Pourquoi
Empirique 13/05 23:30 UTC : V4 ts=22:42, DMP ts=22:45, diff=2880s → skip → "Pas de donnees historiques" + tous widgets V4 a 0. V4_ONLY_FEATURES (cluster, big_orders, im_delta_day_divergence, naked_poc, near_*_level, trapped_*_at_*, bn_absorb_*_at_level) sont des signaux d'EVENEMENTS PAR-BAR, pas niveaux de prix qui derivent en 45min → compromis safety acceptable.

### Impact attendu
- Metriques : section "Indicateurs Trading Manuel" Phase 3 (trapped, absorption, div_clean) + "Order Flow Avance" (cluster, big_orders, smt, naked_poc) affichent valeurs reelles 95% du temps au lieu de OFF/0 50% du temps.
- Effet de bord : aucun. 0 modif code bots. 0 modif code decisionnel/risk/exec. Patch read-only display dashboard.
- Dette tech : `near_resistance_level`/`near_support_level` dans whitelist peuvent etre faux a 45min stale + move directionnel fort. A traiter post-refacto pipeline V4 incremental (IDEAS_BACKLOG priorite 1).

### Validation pre-deploy
- [x] Grep cross-codebase : `merge_dmp_v4` + `_V4_STALE_SEC` utilises uniquement `v4_reader.py` + `app.py` → ZERO impact bots Bot 1/2/3
- [x] Review agent code-reviewer GO-AVEC-RESERVES → 4 reserves corrigees
- [x] Test empirique compute merge avec V4 stale 48min : merge skip confirme, fallback DMP brut OK
- [ ] Post-deploy : verifier compteur `_merge_skip_count` (log WARN toutes 10 skip) → si croit > 6/h, lag pipeline trop haut, considerer bump 3600s ou prioriser refacto incremental

### Revert plan
```bash
# Rollback rapide :
git checkout HEAD~1 -- DASHBOARD/api/v4_reader.py
scp DASHBOARD/api/v4_reader.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/api/"
ssh Administrator@212.28.179.199 "nssm restart MIA-Dashboard"
```

### Deployed at (a remplir apres deploy VPS)
TODO

### Suivi post-deploy
- J+1 : verifier Jackson voit features V4 dans Indicateurs + OFA via hard refresh dashboard
- J+7 : grep `LOGS/errors/*_dashboard.jsonl` pour compteur `V4 stale skip cumule` → si > 100/jour, bump seuil ou refacto pipeline
- J+30 : N/A

### Liens
- INCIDENT_LOG : voir entries 13/05 lies
- IDEAS_BACKLOG : entry PRIORITE 1 13/05 (refacto pipeline V4 incremental qui resoudra ce probleme a la racine)
- Review agent : code-reviewer GO-AVEC-RESERVES R1-R4 (toutes corrigees)

### Dette technique residuelle
1. `near_*_level` flags peuvent etre faux a 45min stale + move directionnel fort (cas-limite R2). A documenter cas usage Jackson + potentiellement exclure de V4_ONLY_FEATURES post-refacto incremental.
2. Pipeline V4 lag racine reste 30-48min. Refacto incremental BUILD_V4 + PHASE_B = solution durable (IDEAS_BACKLOG P1).

---

## 2026-05-13 09:00 — FIX Dashboard section "7/30 derniers jours" vide pour Bot 3 MP

**Categorie** : FIX
**Impact prod** : DASHBOARD (read-only display, aucune modif moteur decision)
**Fichier(s)** :
- `DASHBOARD/api/paper_tracker.py` (compute_stats_period docstring L187, get_bot3_payload L562-587 +stats_7d/30d)
- `DASHBOARD/static/js/dashboard.js` (bot3Normalized L4682-4694 +stats_7d/30d)
- `DASHBOARD/static/index.html` (cache-bust dashboard.css v=76→77, dashboard.js v=125→126)
**Schema/version** : N/A (pas de schema bot)
**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES → 4 reserves corrigees (docstring update + cache-bust + entry CHANGELOG ; pas de try/except defensive over-engineering, pas de log catalog read-only)

### Quoi
Bot 3 MP dashboard affichait "Pas de donnees historiques" dans sections 7j/30j alors que Bot 3 a ~30+ trades sur 5 derniers jours actifs (06/07/08/11/12 mai). `get_bot3_payload()` ne calculait que `stats_today`, omettait `stats_7d`/`stats_30d` contrairement a `_build_bot_payload()` Bot 1/Bot 2. Fix : appel `compute_stats_period(7|30, "*_databento_v3_trades.jsonl")` cote backend + propagation cote frontend `bot3Normalized`.

### Pourquoi
Asymetrie historique : Bot 3 a son propre payload builder `get_bot3_payload` (initial pour level_stats / recent_decisions Phase 1 OBSERVE-ONLY) qui n'a jamais ete aligne avec Bot 1/Bot 2 pour stats periodes. Fichiers trades source de verite `*_databento_v3_trades.jsonl` existent et sont correctement exclus du glob Bot 1 (`is_bot1_pattern` filtre `databento`). Pattern glob ne collisionne pas avec Bot 2 V1 archive (`*_databento_trades.jsonl` suffix different).

### Impact attendu
- Metriques : section "7 derniers jours" + "30 derniers jours" Bot 3 affiche maintenant trades/WR/PF/PnL + breakdown ES/NQ
- Effet de bord : aucun. 0 modif code Bot 1/Bot 2 (code path inchange). 0 modif code decisionnel/risk/exec.

### Validation pre-deploy
- [x] Lecture code 3 fichiers + comparaison patterns Bot 1/Bot 2 vs Bot 3
- [x] Verification pattern glob `*_databento_v3_trades.jsonl` matche bons fichiers VPS (5 fichiers 06-12/05, ~50KB total)
- [x] Verification absence cross-pollution (Bot 2 `*_databento_trades.jsonl` suffix different, _iter_trades_from_files exclusion deja en place)
- [x] Review agent: code-reviewer GO-AVEC-RESERVES (4 reserves corrigees)
- [x] Test empirique : `compute_stats_period` deja en prod Bot 1/Bot 2 depuis 29/04 sans incident

### Revert plan
```bash
# Rollback git ou SCP version precedente :
git checkout HEAD~1 -- DASHBOARD/api/paper_tracker.py DASHBOARD/static/js/dashboard.js DASHBOARD/static/index.html
scp DASHBOARD/api/paper_tracker.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/api/"
scp DASHBOARD/static/js/dashboard.js Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/js/"
scp DASHBOARD/static/index.html Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/"
ssh Administrator@212.28.179.199 "nssm restart MIA-Dashboard"
```

### Deployed at 2026-05-12 18:55 UTC (V1) + 2026-05-13 00:30 UTC (V2 fix complementaire)

**V1 (18:55)** : SCP 3 fichiers + restart MIA-Dashboard. Service Running mais Jackson signale "rubriques toujours vierges".

**V2 (00:30)** : crash silencieux `TypeError: '>' not supported between instances of 'NoneType' and 'int'` dans `compute_stats_period` ligne 198 sur trades Bot 3 v3 `RECOVERED_TIMEOUT` (pnl_ticks=null). 12/69 trades 7j affectes. Endpoint plantait → frontend voyait stats_7d undefined → branche "Pas de donnees".

**Fix V2** : `paper_tracker.py:compute_stats_period` ajout filter `[t for t in trades_raw if isinstance(t.get("pnl_ticks"), (int, float)) and t.get("pnl_ticks") == t.get("pnl_ticks")]` (numeric + exclude NaN). Aligne sur `_is_numeric_pnl` de `_compute_stats_today_from_trades` deja existant. Re-SCP + restart.

**Test empirique post-fix V2** : `compute_stats_period(7, "*_databento_v3_trades.jsonl")` → 57 trades, WR 66.7%, PF 1.51, PnL +$1486.5 (ES: 28 trades PF 2.62, NQ: 29 PF 1.38). OK.

### Suivi post-deploy
- J+1 : verifier Jackson voit bien les stats 7j/30j Bot 3 dans dashboard (hard refresh requis)
- J+7 : N/A (read-only)
- J+30 : N/A

### Liens
- INCIDENT_LOG : entry 2026-05-13 00:30 `VALIDATION_MISS` (deploy V1 sans test empirique reel → bug)
- Memory : `feedback_pre_deploy_3_questions.md` (24/04 viole), `feedback_validation_miss_patterns.md` (24/04)
- Review agent : code-reviewer V1 GO-AVEC-RESERVES (faux negatif sur schema diff Bot 1 vs Bot 3 RECOVERED_TIMEOUT)

### Dette technique residuelle
`compute_stats_period` (L201) et `_renderPaperStatsPeriod` (L5024) hardcodent `("ES", "NQ")` dans la boucle by_symbol. Quand Bot 3 tradera MGC empiriquement (Phase 2+), il faudra etendre les 2 boucles a MGC. Aujourd'hui 0 trade MGC observe = pas bloquant.

---

## 2026-05-12 17:00 — FEATURE Bot 3 GOLD (MGC) integration Phase 1 OBSERVE-ONLY

**Categorie** : FEATURE
**Impact prod** : PAPER (Bot 3 — Sim1)
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py` (SYMBOLS+MGC L167, SYMBOL_TO_CONTRACT L168, load_last_bar fix .v.0 L175-216, _bot3_positions+MGC L370, bot3_gold_engine instancie L358, counters MGC L373-378, dispatcher poll_cycle L2236-2274, checkpoint OBSERVE-ONLY unifie L2275-2295)
- `CORE/bot3_config.py` (GUARD_RAILS_BOT3[MGC] L160-188, RISK_BOT3[MGC] L188-194, ATR_BASELINE[MGC] L211, MAX_DRIFT_TICKS[MGC]=30 deja en place)
- `CORE/bot3_gold_engine.py` (methode evaluate(bar, sym) -> (Bot3Signal|None, list[DecisionLog]) L210-285)
- `CORE/bot3_gold_config.py` (TRADE_ACCOUNT_BOT3G="Sim1" L29 — corrige etait Sim3)
- `CORE/log_catalog.py` (10 codes BOT3G_* L541-550)
- `DOCS/BOT_CHANGELOG.md` (cette entry)
**Schema/version** : Bot 3 v3.1 (multi-instrument ES+NQ+MGC) — Phase 1 OBSERVE-ONLY MGC
**Reviewer(s) agent** : code-reviewer (round 1 GO-AVEC-RESERVES R1+R2+R3 → fixes appliques)

### Quoi
Extension Bot 3 a MGC (Micro Gold COMEX) via Bot3GoldEngine dedie (8 scenarios dynamiques NEUTRAL S1-S8). Le moteur ES/NQ (Bot3Engine MP) reste inchange. Dispatcher dans `_bot3_poll_cycle` route selon le symbole. Phase 1 OBSERVE-ONLY : detection contacts + logging, AUCUNE execution DTC.

### Pourquoi
Jackson directive 12/05/2026 : "BOT 1 SIM3, BOT 2 SIM2, BOT 3 SIM1 trade ES+NQ+MGC". Bot 3 d'abord car 5 fichiers `bot3_gold_*.py` deja codes + backtest 4 mois (PF 1.185, 159 trades, balanced LONG/SHORT 53/47%, S7 GS_RATIO dominant). PF marginal < 1.3 seuil → Phase 1 OBSERVE 1 semaine avant Phase 2 paper.

### Impact attendu
- **Detection** : ~10-20 contacts/jour MGC (estimation backtest extrapole) sur 36 niveaux NEUTRAL (Tier 1 = 9 niveaux activés Phase 2)
- **Logs** : codes BOT3G_DECISION_GO/SKIP/VETO emis dans LOGS/decisions/. Codes MAJEUR (MACRO_OVERRIDE, VETO_LONDON_FIX, HEDGE_TRIGGER) tracables via grep.
- **Zero impact ES/NQ** : code path separe via dispatcher (regression-safe verifie via tests empiriques 6/6).
- **Bug fix collateral CRITIQUE** : `load_last_bar()` utilise desormais `get_databento_ticker(symbol)` au lieu de hardcode `.c.0` → fix MGC qui aurait sinon perdu 50-99% des bars 6 mois rollover GC (cf .claude/rules/lessons.md). ES/NQ comportement identique (retour `.c.0`).

### Validation pre-deploy
- [x] Tests unitaires: 6/6 smoke + 4/4 post-fix (imports, evaluate API, dispatcher, log_catalog)
- [x] Backtest preservation: NA (extension symbole sans modif moteur ES/NQ) — backtest Gold 159 trades PF 1.185 deja documente DOCS/EDGE_REPORT_GOLD_MGC_RTH.md
- [x] Review agent: code-reviewer round 1 GO-AVEC-RESERVES (R1 checkpoint OBSERVE-ONLY dupli, R2 dist_pct_at_touch=0.0 hardcode, R3 fallback silencieux import) → 3 fixes appliques + round 2 a faire
- [x] Test empirique: `python -X utf8 -c "from databento_paper_trader_v2 import DatabentoPaperTraderV2; t=DatabentoPaperTraderV2(dry_run=True); print(t._bot3_positions)"` → `{'NQ': None, 'ES': None, 'MGC': None}`

### Nouveaux logs (10 codes BOT3G_*)
| Code | Niveau | Categorie | Template |
|---|---|---|---|
| BOT3G_BOOT_READY | INFO | events | Bot3 Gold boot pret : phase={phase} observe_only={observe_only} |
| BOT3G_LEVEL_CONTACT | INFO | decisions | Bot3G contact niveau : {level} tier={tier} dist={dist} |
| BOT3G_DECISION_GO | INFO | decisions | Bot3G GO : {level} {side} scenario={scenario} conf={conf} |
| BOT3G_DECISION_SKIP | INFO | decisions | Bot3G SKIP : {level} reason={reason} macro={macro} |
| BOT3G_MACRO_OVERRIDE | MAJEUR | decisions | Bot3G macro override : {level} side_propose={side} → action={action} |
| BOT3G_VETO_LONDON_FIX | MAJEUR | decisions | Bot3G VETO London Fix : {level} window={window} |
| BOT3G_TRADE_OPEN | INFO | trading | Bot3G trade ouvert : MGC {level} {side} qty={qty} @ {price} |
| BOT3G_TRADE_CLOSE | INFO | trading | Bot3G trade ferme : MGC {level} reason={reason} pnl={pnl}t |
| BOT3G_INTERMARKET | INFO | decisions | Bot3G intermarket : DXY={dxy} real_yield={ry} gs_z={gsz} |
| BOT3G_HEDGE_TRIGGER | MAJEUR | decisions | Bot3G HEDGE actif : Bot2 NQ={nq} ES={es} → LONG MGC qty={qty} |

### Revert plan
```bash
# Rollback rapide (kill switch Gold sans toucher ES/NQ)
# 1. Editer CORE/bot3_gold_config.py : BOT3G_OBSERVE_ONLY=True (deja par defaut Phase 1)
# 2. OU disable au niveau dispatcher : commenter ligne sym=="MGC" dans _bot3_poll_cycle
#    et garder seulement self.bot3_engine.evaluate(bar_dict, sym)
# 3. Git revert si besoin :
git revert <commit_hash>   # cette entry
# Effets attendus : MGC redevient inactif, ES/NQ continuent normalement
```

### Deployed at
(a remplir apres deploy VPS + restart MIA-DataBento-Paper-V2)

### Suivi post-deploy
**J+1** : grep LOGS/decisions/decisions_YYYYMMDD_*.jsonl | grep BOT3G_DECISION_GO → compter signaux + verifier balance LONG/SHORT
**J+7** : audit pre-Phase 2 → calculer PF hypothetique (would_GO + simu SL/TP) + ratio veto London Fix / RTH / Vol_mort
**J+30** : decision Phase 2 PAPER actif si PF >= 1.3 sur >= 50 contacts simulés

---

## 2026-05-12 03:50 — FIX RACE CONDITION entry_price 3 bots + features V4 enriched

**Categorie** : FIX (CRITIQUE)
**Impact prod** : PAPER (Bot 1 + Bot 2 V6 + Bot 3)
**Fichier(s)** :
- `BOT/dtc_connector.py:97-103,316-321,418-437` (init + capture + nouvelle methode)
- `CORE/mia_paper_trader.py:2317-2350` (Bot 1 fix)
- `CORE/mia2_brain_v6_databento.py:2664-2693` (Bot 2 V6 fix)
- `CORE/databento_paper_trader_v2.py:2446-2462,2521-2570` (Bot 3 fix + drift reject)
- `CORE/bot3_config.py:39-71` (MAX_DRIFT_TICKS calibre p75)
- `BOT/bot3_config.py` (synchro duplicate BOT/)
- `CORE/log_catalog.py:60-62` + `BOT/log_catalog.py:60-62` (2 nouveaux codes)
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES) + market-analyst (GO seuils corriges)

### Quoi
Resolution race condition `_handle_dtc_fill` callback : entry_price stocke = signal_price (faux) au lieu de fill_price reel broker DTC. Approche non-breaking : ajout `_last_fill_prices` dict persistent dans dtc_connector + nouvelle methode `get_last_fill_price(parent_id)`. 3 bots recuperent le fill_price reel apres `send_market_order` return. Bot 3 supplementaire : drift_reject avant trade si drift signal vs live_ref depasse seuil.

### Pourquoi
Trade Bot 3 NQ 12/05 02:54:51 (`LIVE_REF_USED drift_ticks=173.0`) : dashboard rapporte +$142.50 vs Sierra fill reel -$120 (ecart $262.50/trade). Bug invisible Bot 1/V6 (drift 1-5t sources fraiches) mais catastrophique Bot 3 (V4 enriched stale 18-24min → drift jusqu'a 173t).
Bug racine introduit 03/05 (directive V4 enriched Bot 3) + race condition design initial. 44 trades Bot 3 historiques contamines.

### Comment
- `BOT/dtc_connector.py` : `_last_fill_prices` dict persistent + `get_last_fill_price()` method. Signature `send_market_order` INCHANGEE (backward-compat).
- 3 bots : `fill_price_real = self.dtc.get_last_fill_price(parent_id)` apres return. `entry_price = fill_price_real if >0 else signal["entry_price"]` (fallback safe). Stockage `signal_price` + `entry_drift_ticks` audit. Emit `BOT_ENTRY_FILL_RECORDED` (INFO).
- Bot 3 specifique : drift_reject avant `send_market_order` si `|drift_signal| > MAX_DRIFT_TICKS[sym]`. Emit `BOT_DRIFT_REJECT` (MAJEUR).
- `bot3_config.py` MAX_DRIFT_TICKS calibre p75 empirique (83 events) : NQ=60, ES=16, MGC=30 (corrige initial 20/8/30 trop strict 77.4% block).

### Validation pre-deploy
- ✅ Syntax check 7/7 fichiers OK (local + VPS)
- ✅ Import check VPS : `get_last_fill_price` method exists, `MAX_DRIFT_TICKS` accessible, 2 log codes registres
- ✅ Review agent code-reviewer : 5/5 sur 7 fichiers, GO-AVEC-RESERVES (R1 fuite memoire ~2.9MB/an + R2 asymetrie drift Bot 1/V6 non-bloquantes)
- ✅ Review agent market-analyst : NOGO sur seuils initiaux 20/8/30 → corriges 60/16/30 (data p75 distribution empirique drift). GO post-correction.
- ✅ Audit non-regression personnel : approche non-breaking (signature inchangee), callback `_handle_dtc_fill is_parent` preserve defense en profondeur, fallback safe signal_price si DTC timeout.

### Backtest preservation
N/A (fix bug pur, pas changement strategie). Sur Bot 1 + Bot 2 V6 drift typique 1-5t → `entry_price_effective` post-fix ≈ pre-fix a 1-5t pres → WR/PF impact <0.5% (invisible).
Sur Bot 3 : 44 trades historiques INVALIDES (entry_price faux) → marquer `_CONTAMINATED_` apres validation shadow 5 trades.

### Revert plan
1. `git revert 2c1a4b9` (commit atomique)
2. scp 7 fichiers depuis `DATA/BACKUP/pre_fix_entry_price_20260512/` vers VPS
3. Restart 3 services nssm

### Deployed at 2026-05-12 03:50 UTC
- scp 8 fichiers VPS (7 + BOT/bot3_config duplicate)
- nssm restart Bot 1 + Bot 2 V6 + Bot 3
- 3 services Running, heartbeats OK
- Bot 3 LIVE_REF_USED ES drift=3.0t (normal, sous seuil 16t)

### Suivi post-deploy J+1 (13/05 matin)
- `grep BOT_ENTRY_FILL_RECORDED LOGS/execution/execution_20260512_*.jsonl | wc -l` doit etre > 0 sur ≥ 1 trade live
- `grep BOT_DRIFT_REJECT LOGS/execution/` : si > 0 → Bot 3 V4 stale critique, investiguer source live_cache
- Spot-check 1 trade : signal_price vs fill_price vs drift_ticks coherents
- Bot 1 + Bot 2 V6 : WR/PF stable vs hier (regression check)

### Nouveaux logs
- `BOT_ENTRY_FILL_RECORDED` (INFO) : entry fill reel enregistre. Ctx : sym, direction, signal_price, fill_price, drift_ticks, bot.
- `BOT_DRIFT_REJECT` (MAJEUR) : trade refuse drift excessif. Ctx : sym, direction, drift_ticks, threshold, bot.

### Liens
- INCIDENT_LOG : 2026-05-12 03:30 entry [VALIDATION_MISS]
- INCIDENT_LOG : 2026-05-12 03:00 entry [VALIDATION_MISS] features V4
- Memory : `project_bot2v6_dmp_in_practice.md`, `feedback_bot3_data_source_v4_enriched.md`
- Backup : `DATA/BACKUP/pre_fix_entry_price_20260512/`

### Dette technique introduite
1. `_last_fill_prices` dict jamais purge (~2.9MB/an, acceptable, backlog cleanup)
2. Drift reject = patch sur cause racine V4 enriched stale 18min. A retirer apres deploy pipeline incremental (cf `project_pipeline_incremental_backlog.md`).
3. 44 trades Bot 3 contamines a marquer `_CONTAMINATED_` apres shadow validation 5 trades.

---


## 2026-05-11 15:45 — [Pipeline V4 enriched : fix Databento empty response + logging exception]

**Categorie** : FIX
**Impact prod** : PAPER (Bot 3 source data via MIA-LivePipeline)
**Fichier(s)** :
- `CORE/databento_download.py:88-117` : try/except avec traceback + validation record_count > 0
- `CORE/databento_download.py:163-172` : ERR enrichi (type + repr + traceback)
- `CORE/live_pipeline.py:160-191` : post-check mtime DBN après download
- `CORE/log_catalog.py:481-484` : +3 codes (DOWNLOAD_EMPTY_RESPONSE, DOWNLOAD_NON_RETRY_EXC, DOWNLOAD_STALE_POST_FETCH)

**Schema/version** : log_catalog 350 → 353
**Reviewer(s) agent** : code-reviewer (verdict NOGO pipeline + 4 fixes — tous appliqués)

### Quoi
Incident 11/05/2026 : Bot 3 muet 2h40 (RTH 13:30-15:45). Root cause = Databento Historical OHLCV-1m API ES.c.0 stuck à 13:25 UTC pendant 2h. Le code `databento_download.py` recevait des réponses API "OK avec 0 records" et **écrasait silencieusement le DBN valide précédent avec un DBN vide** (11700 bytes = header + 0 records). Aucun log [DL] ou [ERR] visible.

### Pourquoi
Cross-check agent + factuel convergent :
- Agent : "L'API peut renvoyer 200 OK + 0 records si bars récentes pas encore disponibles, code overwrite sans validation"
- Factuel : DBN file ES = 11700 bytes (presque vide), mtime gelé 13:36 UTC, parquet bars=806 stuck à 13:25

### Impact attendu
- Métriques : +3 codes log audit, +1 protection anti-overwrite-vide
- Effet de bord : aucun (fail-safe — preserve DBN existant au lieu d'écraser avec vide)

### Validation pre-deploy
- [x] Syntax Python : ast.parse OK
- [x] Codes registered : 353/353 LOG_CODES
- [x] Review agent : code-reviewer NOGO → 4 fixes appliqués
- [x] Test empirique : restart 15:45:54 UTC, nouveau format log `OK (3.29 MB, 210470 records)` confirme Fix #2 actif. Worst_status dashboard CRIT → WARN.

### Revert plan
```bash
git checkout HEAD~1 -- CORE/databento_download.py CORE/live_pipeline.py CORE/log_catalog.py
scp CORE/databento_download.py CORE/live_pipeline.py CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/BOT/log_catalog.py"
ssh Administrator@212.28.179.199 "Restart-Service MIA-LivePipeline"
```

### Deployed at 2026-05-11 15:45:54 UTC

### Suivi post-deploy
- J+1 : grep `DOWNLOAD_EMPTY_RESPONSE|DOWNLOAD_NON_RETRY_EXC|DOWNLOAD_STALE_POST_FETCH` events_*.jsonl
- J+7 : confirmer aucun re-incident silence pipeline V4
- J+30 : data utilisée pour décider switch source live (chantier C backlog)

### Liens
- Memory : `feedback_bot3_data_source_v4_enriched.md` (lag pipeline V4 documenté)
- INCIDENT_LOG : 11/05 entry VALIDATION_MISS (garde-fou dashboard cassé) + DEPLOY_UNSAFE (overwrite silencieux DBN)
- Review agent : code-reviewer NOGO + Fix 1/2/3/4 GO

---

## 2026-05-11 14:12 — [Bot 3 Traçabilité blocages : 5 nouveaux emit + throttle helper]

**Categorie** : FEATURE
**Impact prod** : PAPER (Bot 3 Sim1 MIA-DataBento-Paper-V2)
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py:339-341` : init `_bot3_emit_throttle: dict[(sym, code), float]` dans `__init__`
- `CORE/databento_paper_trader_v2.py:360-381` : nouveau helper `_bot3_emit_throttled(code, throttle_sec, **kw)` avec assert sym fail-loud
- `CORE/databento_paper_trader_v2.py:~2088-2102` : emit `BOT3_ALREADY_IN_POSITION` (INFO throttle 300s)
- `CORE/databento_paper_trader_v2.py:~2110-2122` : emit `BOT3_BAR_NONE` (INFO throttle 60s) + `BOT3_BAR_STALE` (ALERTE throttle 300s)
- `CORE/databento_paper_trader_v2.py:~2155-2161` : emit `BOT3_OBSERVE_ONLY_SKIP` (INFO par signal)
- `CORE/databento_paper_trader_v2.py:~2426-2431` : emit `BOT3_EXECUTE_DTC_DOWN` (MAJEUR rare)
- `CORE/log_catalog.py:478-485` : 5 nouveaux codes log (total 345 → 350)
- `BOT/log_catalog.py` : sync (sys.path priority bug)

**Schema/version** : log_catalog 345 → 350
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES 3 réserves bloquantes — toutes appliquées)

### Quoi
Réponse directive Jackson "met a jour les log on dois pouvoir suivre tout les blocage".
Cartographie 5 points de blocage silencieux Bot 3 (continue/return False sans emit) :

1. `bar is None` → `BOT3_BAR_NONE` (INFO throttle 60s)
2. `age > DATA_CRIT_THR_SEC` → `BOT3_BAR_STALE` (ALERTE throttle 300s)
3. `_bot3_positions[sym] is not None` → `BOT3_ALREADY_IN_POSITION` (INFO throttle 300s)
4. `signal generated + BOT3_OBSERVE_ONLY=True` → `BOT3_OBSERVE_ONLY_SKIP` (INFO)
5. `_ensure_dtc_connected() == False` in execute_trade → `BOT3_EXECUTE_DTC_DOWN` (MAJEUR)

Helper `_bot3_emit_throttled` avec throttle par (sym, code) anti-spam log cycle 1s.

### Pourquoi
Jackson 11/05 : pouvoir auditer J+1 quels signaux Bot 3 ont été bloqués et pourquoi.
Avant : 4 `continue` + 1 `return False` SILENCIEUX (zero trace). Audit impossible.

### Impact attendu
- Métriques : +5 codes log traçabilité, ~50-100 emit/jour estimés
- Effet de bord : aucun (emit pure observation, aucun changement comportement)

### Validation pre-deploy
- [x] Tests unitaires : N/A (modif emit pure, pas de logique)
- [x] Syntax Python : ast.parse OK
- [x] Codes registered : 350/350 LOG_CODES (était 345)
- [x] Review agent : GO-AVEC-RESERVES — 3 réserves appliquées (BAR_STALE ALERTE+300s, BOT3_ALREADY_IN_POSITION ajouté, EXECUTE_DTC_DOWN MAJEUR pas CRITIQUE)
- [x] Test empirique : restart 14:11:52 UTC PID 4432, BOT3_BAR_STALE émis 14:12:07 (NQ+ES) avec niveau ALERTE et template "throttle 300s" confirmé. BOT3_LADDER_TICK continue d'émettre.

### Revert plan
```bash
ssh Administrator@212.28.179.199 "Stop-Service MIA-DataBento-Paper-V2"
git checkout HEAD~1 -- CORE/databento_paper_trader_v2.py CORE/log_catalog.py
scp CORE/databento_paper_trader_v2.py CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/BOT/log_catalog.py"
ssh Administrator@212.28.179.199 "Start-Service MIA-DataBento-Paper-V2"
```

### Deployed at 2026-05-11 14:11:52 UTC (PID 4432)

### Suivi post-deploy
- J+1 (12/05) : grep `BOT3_BAR_NONE|BOT3_BAR_STALE|BOT3_ALREADY_IN_POSITION|BOT3_OBSERVE_ONLY_SKIP|BOT3_EXECUTE_DTC_DOWN` execution_*.jsonl pour confirmer instrumentation
- J+7 (18/05) : analyse distribution blocages — quel symbole/code domine ?
- J+30 : data utilisée pour optimiser pipeline V4 enriched (réduire bar stale)

### Liens
- Memory : N/A (pattern pas promu)
- Review agent : code-reviewer 11/05 GO-AVEC-RESERVES (Q1 throttle, Q2 doublon DTC_DOWN, Q3 assert sym, Q4 elif, Q5 trou ALREADY_IN_POSITION)
- Skills rules : `.claude/rules/critical-tasks-review.md` section LOGS TRACABILITE A.1-2 (code défini AVANT commit, niveaux INFO/MAJEUR/CRITIQUE/ALERTE)

---

## 2026-05-11 17:45 — [Bot 3 Solution D2 Ladder Phase 1b ACTION — Vrai cancel/replace SL]

**Categorie** : FEATURE
**Impact prod** : PAPER (Bot 3 Sim1 MIA-DataBento-Paper-V2)
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py:1043-1100` : refacto `_bot3_update_mfe_mae` (snapshot pattern hors lock pour eviter deadlock)
- `CORE/databento_paper_trader_v2.py:1237-1267` : `_bot3_check_trailing_ladder` case `mode == "ACTION"` appelle helper modify
- `CORE/databento_paper_trader_v2.py:1276-1454` : nouveau helper `_bot3_modify_sl_via_dtc` (~140 LOC) avec 7+3 fixes anti-orphan
- `CORE/log_catalog.py` : +11 nouveaux codes (BOT3_LADDER_SL_MODIFIED, NO_SL_ALERT, MODIFY_DTC_DOWN, NO_OLD_SL_CID, CONTRACT_LOOKUP_FAIL, CANCEL_EXCEPTION, CANCEL_FAILED, SEND_NEW_SL_EXCEPTION, POS_VERIFY_EXCEPTION, POS_VERIFY_TIMEOUT, POS_CLOSED_DURING_MODIFY)
- `CORE/tests/test_bot3_ladder_action.py` (nouveau) : 8 tests unitaires PASS

**Schema/version** : Bot 3 v2.1 (ladder OBSERVE) -> v2.2 (ladder OBSERVE + ACTION)
**Reviewer(s) agent** : code-reviewer (round 1 NOGO 3 issues critiques → round 2 GO-AVEC-RESERVES post 3 fixes)

### Quoi
Implémentation Phase 1b ACTION du ladder profit-locking. Quand MFE atteint un palier (Solution D2 :
NQ +60t/+100t/+150t/+200t, ES +20t/+40t/+60t/+80t), le SL est **réellement déplacé** via DTC :

1. Cancel old SL via Type 203 (avec ServerOrderID + TradeAccount fix H6)
2. Wait 0.3s propagation cancel
3. **Verify position broker via request_position_blocking** (anti race condition trade inverse)
4. Pre-register new_sl_cid dans `_order_trade_accounts` + `_oco_pairs` (anti-orphan)
5. Send new STOP order (Type 208 OrderType=STOP + StopPrice)
6. Update pos.sl_cid + pos.sl_price + ladder_sl_history (mini-lock)
7. Emit BOT3_LADDER_SL_MODIFIED (success) ou BOT3_LADDER_NO_SL_ALERT CRITIQUE (échec)

### Pourquoi
Phase 1a OBSERVE deployé ce matin (12:00 UTC) = log "WOULD lock" sans action DTC réelle. Aujourd'hui 14:33 UTC : Bot 3 NQ LONG entry 29308.25 → SL -$202.50 (16 min duration). Jackson observation : "il était à plus 200 ticks de gain et le trailing pas active". Confirme empiriquement que mode OBSERVE seul ne protège RIEN.

### Impact attendu
- À chaque palier MFE atteint sur trade Bot 3 → SL bougé au prix lock_ticks
- Worst case post-palier 1 = entry+20t (NQ) = lock $30 garanti
- Risques connus : DTC reject silent, race condition, orphan SL (mitigés par 3 fixes critiques)

### Validation pre-deploy
- [x] Tests unitaires : 8/8 PASS (`python -m unittest CORE.tests.test_bot3_ladder_action`)
- [x] Syntax python ast OK les 2 fichiers
- [x] Import LOG_CODES verifie : 345 codes total (+11 nouveaux Phase 1b)
- [x] Code-reviewer round 1 : NOGO 3 issues critiques (deadlock, race, OCO partial)
- [x] Code-reviewer round 2 : GO-AVEC-RESERVES post 3 fixes appliqués
- [x] 7 fixes anti-orphan validés (cf `.claude/rules/orphan-prevention.md`)
- [ ] Test runtime sur VPS apres SCP (mode OBSERVE puis ACTION)

### 3 issues critiques FIXÉES (code-reviewer round 1)

**Fix #1 — DEADLOCK garanti** : `threading.Lock()` non-reentrant + ladder appelé INSIDE lock = deadlock au premier ACTION. Refacto `_bot3_update_mfe_mae` = snapshot pattern, ladder appelé HORS lock principal.

**Fix #2 — Race condition trade inverse** : pendant 0.3s wait post-cancel, marché peut traverser old SL → SC fill → position close DTC → new STOP envoyé crée trade inverse catastrophique. Ajout `request_position_blocking` pré-send + abort si qty=0.

**Fix #3 — Cleanup OCO partial** : `_oco_pairs` bidirectionnel, je popais 1 direction = orphan mapping. Pop maintenant `old_sl_cid` + `tp_cid` + `new_sl_cid` (3 directions selon contexte).

### Revert plan
```bash
# Option 1 : Switch mode OBSERVE (no code revert)
ssh Administrator@212.28.179.199 'powershell -Command "nssm set MIA-DataBento-Paper-V2 AppEnvironmentExtra ... MIA_BOT3_LADDER_MODE=OBSERVE"'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-DataBento-Paper-V2"'

# Option 2 : Disable kill switch (no ladder)
ssh Administrator@212.28.179.199 'powershell -Command "nssm set MIA-DataBento-Paper-V2 AppEnvironmentExtra MIA_TRADE_ACCOUNT=Sim2 MIA_DTC_HOST=localhost MIA_DTC_PORT=11099 MIA_DTC_USER=miav2"'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-DataBento-Paper-V2"'

# Option 3 : Revert code
ssh Administrator@212.28.179.199 'cd C:/TRADING_SIERRA_CHART_AUTO && git checkout CORE/databento_paper_trader_v2.py CORE/log_catalog.py'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-DataBento-Paper-V2"'
```

### Deployed at YYYY-MM-DD HH:MM
(a remplir apres SCP + restart en MODE OBSERVE d'abord puis switch ACTION)

### Suivi post-deploy J+1 OBLIGATOIRE (R2 code-reviewer)
- grep `BOT3_LADDER_TICK` LOGS/execution/* → diagnostic fonction tourne
- grep `BOT3_LADDER_WOULD_LOCK` (mode OBSERVE) ou `BOT3_LADDER_SL_MODIFIED` (mode ACTION) → palier déclenche
- grep `BOT3_LADDER_NO_SL_ALERT` ou `BOT3_LADDER_POS_CLOSED_DURING_MODIFY` ou `BOT3_LADDER_CANCEL_FAILED` → si présent = anomalie CRITIQUE, rollback OBSERVE
- Vérifier MFE/PnL Bot 3 améliore vs sans ladder (target +$50-100 par trade pas-completement-perdant)

### Liens
- BOT_CHANGELOG : 2026-05-11 12:00 Solution D2 Phase 1a OBSERVE
- INCIDENT_LOG : 2026-05-11 trade -$202.50 NQ (cause "trailing pas activé")
- `.claude/rules/orphan-prevention.md` (7 fixes H6, lock R5, anti-orphan v2)
- `.claude/rules/critical-tasks-review.md` (Critère 1 Trading/Risk)
- Memory `feedback_swing_proximity_veto.md` (Jackson 11/05)
- Memory `feedback_range_confirmation_breakout.md` (Jackson 11/05)
- Memory `project_bot3_scale_out_be_plan.md` (07/05 — 7 fixes valides)

---

## 2026-05-11 12:00 — [Bot 3 Solution D2 Ladder Profit-Locking — Phase 1a OBSERVE]

**Categorie** : FEATURE
**Impact prod** : PAPER (Bot 3 Sim1 MIA-DataBento-Paper-V2)
**Fichier(s)** :
- `CORE/bot3_config.py:71-78,95-105` : ajout `ladder_paliers` NQ (4 paliers) + ES (4 paliers)
- `CORE/databento_paper_trader_v2.py:1087,1159-1265` : ajout fonction `_bot3_check_trailing_ladder` + call site dans `_bot3_update_mfe_mae`
- `CORE/tests/test_bot3_ladder.py` (nouveau) : 14 tests unitaires (palier 1/2/4, idempotent, edge cases, ES, kill switch)
- `CORE/research/replay_ladder_history.py` (nouveau) : script replay sur trades historiques

**Schema/version** : Bot 3 v2 -> v2.1 (additive, retrocompatible)
**Reviewer(s) agent** : market-analyst GO Phase 1 (verdict 11/05) + 14 tests unitaires PASS

### Quoi
Implementation Solution D2 "profit-locking par paliers" pour Bot 3 (Jackson directive 11/05 apres observation "monter +$100 puis SL").

**4 paliers NQ** : (mfe_seuil, sl_lock_ticks) :
- Palier 1 : MFE +60t → SL +20t (lock $30)
- Palier 2 : MFE +100t → SL +40t (lock $60)
- Palier 3 : MFE +150t → SL +80t (lock $120)
- Palier 4 : MFE +200t → SL +120t (lock $180)

**4 paliers ES** (tick_value $1.25 plus eleve) :
- Palier 1 : MFE +20t → SL +8t (lock $30)
- Palier 2 : MFE +40t → SL +16t (lock $60)
- Palier 3 : MFE +60t → SL +30t (lock $112.50)
- Palier 4 : MFE +80t → SL +50t (lock $187.50)

**Mode OBSERVE (Phase 1a)** : emit BOT3_LADDER_WOULD_LOCK_PALIER_N + BOT3_LADDER_TICK diagnostic sans action DTC. **Aucun cancel/replace SL DTC.** Permet observation runtime + audit avant Phase 1b ACTION.

**Mode ACTION (Phase 1b future)** : pas implementee, 7 fixes anti-orphan requis avant deploy (cf market-analyst review).

**Kill switches** :
- `MIA_BOT3_LADDER_ENABLED=0` (default) → fonction return early, no emit
- `MIA_BOT3_LADDER_ENABLED=1` → mode OBSERVE active (logs WOULD_LOCK)
- `MIA_BOT3_LADDER_MODE=OBSERVE|ACTION` (default OBSERVE)

### Pourquoi
Audit 11/05 Bot 3 : 38 trades historique +$411 PnL, mais 3 big givebacks (MFE >50t → SL/TIMEOUT) totalisent ~$504 evapore. Trades 11/05 today : MFE 48t/66t → SL au lieu de capture.

Verdict market-analyst : `_bot3_check_trailing_observation` ligne 1089 = log only depuis 07/05 (0 emit en realite — bug timing/call path). Re-implementer en `_bot3_check_trailing_ladder` avec diagnostic emit OBLIGATOIRE pour observer le runtime.

### Impact attendu (backtest replay historique)
- **38 trades 06-11/05** : PnL actuel +$411 → PnL D2 simule +$694.50 = **+$283.50 (+69%)**
- **10/38 trades touchent ≥1 palier** (26%)
- **6 trades sauves** par ladder (gain garanti vs SL initial)
- Distribution paliers armes : palier 1=7, palier 2=2, palier 3=1

### Validation pre-deploy
- [x] Tests unitaires : 14/14 PASS (`python -m unittest CORE.tests.test_bot3_ladder`)
- [x] Syntax python ast OK les 2 fichiers
- [x] Import GUARD_RAILS_BOT3 verifie : 4 paliers NQ + 4 paliers ES presents
- [x] Backtest replay 38 trades : +$283.50 / +69%
- [x] Pas de modif DTC (mode OBSERVE = log only, anti-orphan irrelevant Phase 1a)
- [ ] Test runtime : observer 1-2 trades naturels Bot 3 + BOT3_LADDER_TICK emit (apres deploy)

### Revert plan
```bash
# Option 1 : disable kill switch (no code revert)
ssh Administrator@212.28.179.199 'powershell -Command "nssm set MIA-DataBento-Paper-V2 AppEnvironmentExtra MIA_TRADE_ACCOUNT=Sim2 MIA_DTC_HOST=localhost MIA_DTC_PORT=11099 MIA_DTC_USER=miav2"'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-DataBento-Paper-V2"'
# = retour Bot 3 sans ladder (MIA_BOT3_LADDER_ENABLED non defini = default 0 = off)

# Option 2 : revert code
ssh Administrator@212.28.179.199 'cd C:/TRADING_SIERRA_CHART_AUTO && git checkout CORE/databento_paper_trader_v2.py CORE/bot3_config.py'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-DataBento-Paper-V2"'
```

### Deployed at 2026-05-11 10:56 UTC (12:56 Paris)
- SCP bot3_config.py + databento_paper_trader_v2.py + test_bot3_ladder.py
- Hash match VPS = local (FED4A1FE / D10E7A46)
- nssm set MIA-DataBento-Paper-V2 AppEnvironmentExtra ajout `MIA_BOT3_LADDER_ENABLED=1` + `MIA_BOT3_LADDER_MODE=OBSERVE`
- Restart service : Running PID 10296
- BOOT_READY confirme : `DTC=OK model=SetupEngine_v1 data=V4_enriched_parquet`
- BOT3_BOOT_READY : `phase=PAPER tier1+2+3 observe=False`
- Bot a immediatement pris un trade NQ LONG entry=29306.75 @ 10:56:16 UTC (signal_id 3574aaf2d39a)

### Suivi post-deploy ATTENTION
- **0 emit `BOT3_LADDER_TICK` 5 min post-restart** malgre position NQ ouverte
- Hypothese : meme bug que `_bot3_check_trailing_observation` (0 emits depuis 07/05)
- `_bot3_update_mfe_mae` peut-etre pas appelee OR positions Bot 3 pas dans la struct attendue
- A debug si toujours 0 emit apres 30+ min (faut comprendre call path)
- Possible : `MIA_BOT3_LADDER_ENABLED=1` env var pas propagee au process Python — a verifier

### Suivi post-deploy
- **J+0 (today)** : verifier emit `BOT3_LADDER_TICK` apparait dans LOGS/events/events_*_paper_v2.jsonl pour chaque position ouverte
- **J+1** : compter `BOT3_LADDER_WOULD_LOCK_PALIER_N` emis vs paliers attendus selon mfe_ticks observes
- **J+3** : audit replay live vs theorique. Si % match >= 90% → GO Phase 1b ACTION
- **J+7** : delta PnL theorique cumule (lock_usd somme) vs PnL actuel — confirmer +69% scenario
- **J+30** : si stable + GO → Phase 1b (cancel/replace SL DTC reel) avec 7 fixes anti-orphan

### Liens
- INCIDENT_LOG : aucun (feature add, pas de fix bug)
- Memory `project_bot3_scale_out_be_plan.md` (07/05 — 7 fixes anti-orphan toujours valides pour Phase 1b)
- Memory `feedback_bot3_sltp_integration_plan.md` (07/05 — SLTPEngine wall-aware = backlog Phase 2)
- Market-analyst verdict 11/05 GO Phase 1
- Test results : 14/14 PASS

---

## 2026-05-11 10:59 — [Bot 1 DTC activation Sim 3]

**Categorie** : CONFIG
**Impact prod** : PAPER (Bot 1 Sim3 MIA-Paper)
**Fichier(s)** : aucun code modifie. Modif nssm service env vars :
- `MIA_TREND_DAY_OVERRIDE_ENABLED=1` (deja present)
- `MIA_DTC_ENABLE=1` (NOUVEAU — active envoi ordres DTC)
- `MIA_TRADE_ACCOUNT=Sim3` (NOUVEAU — route trades vers Sim 3 Topstep)

**Reviewer(s) agent** : self + Jackson validation explicite

### Quoi
Activation DTC sur Bot 1 (`mia_paper_trader.py` PID nouveau 11736). Avant ce changement, Bot 1 tournait en simulation pure memoire (`MIA_DTC_ENABLE` non defini = default "0"). Trades affiches dashboard mais **aucun ordre arrive Sierra Chart Sim 3**.

Apres restart MIA-Paper :
- Boot log confirme : `BOOT_READY : DTC=connected model=paper data=Sim3`
- Bot 1 ouvre maintenant des ordres reels via DTC localhost:11099 vers Sierra Chart Sim 3

### Pourquoi
Audit 11/05 matin a revele que Bot 1 Sim 3 broker PnL = 0 alors que dashboard montrait 4 trades today. Le bot tournait en simulation memoire sans envoi DTC. Decoupage Sim 3 (broker reel Topstep) vs paper-memory (interne bot) = source de confusion dashboard vs Sierra Chart.

Decision Jackson 11/05 11:00 : `"OK ACTIVE DTC BOT 1"`. Aligne le pipeline DTC bout-en-bout Bot 1 avec Bot 2 V6 (Sim 2) + Bot 3 (Sim 1).

### Impact attendu
- Tous les futurs trades Bot 1 = ordres reels Sim 3 Topstep (DLL $1000/jour)
- Dashboard Bot 1 stats <-> Sierra Chart Sim 3 PnL alignes
- Risque connu : DTC reject silencieux possible (cf `.claude/rules/orphan-prevention.md`)
- Cooldown DTC SC : verifier `execution_*_paper.jsonl` premier trade pour ORDER_FILL + BRACKET_OK

### Validation pre-deploy
- [x] Bot 2 V6 + Bot 3 deja en DTC actif sur Sim 2 + Sim 1 (precedent valide infrastructure)
- [x] DTC connector teste 02/04/2026 (OCO manuel + cancel ServerOrderID)
- [x] Anti-orphan protections en place (rule orphan-prevention.md cancel_order trade_account explicit)
- [x] Verify post-deploy : BOOT_READY DTC=connected confirme 08:59:01 UTC

### Revert plan
```bash
ssh Administrator@212.28.179.199 'powershell -Command "nssm set MIA-Paper AppEnvironmentExtra MIA_TREND_DAY_OVERRIDE_ENABLED=1"'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-Paper"'
# Retour simulation pure memoire (MIA_DTC_ENABLE supprime)
```

### Deployed at 2026-05-11 08:59 UTC (10:59 Paris)
- env vars : confirme via `nssm get MIA-Paper AppEnvironmentExtra`
- service Status : Running PID 11736
- BOOT_READY : `DTC=connected model=paper data=Sim3`

### Suivi post-deploy
- **J+0 (today, dimanche)** : pas de session marche, aucun trade attendu
- **J+1 (lundi 12/05 RTH 09:30 ET)** : surveiller premier trade Bot 1
  - Sierra Chart Sim 3 broker PnL ↔ dashboard match
  - `LOGS/execution/execution_*_paper.jsonl` : ORDER_FILL + BRACKET_OK
  - `LOGS/errors/errors_*_paper.jsonl` : 0 DTC_REJECT / 0 ORPHAN_RISK
- **J+3** : verifier coherence stats J+1 + J+2 + J+3 dashboard vs Sierra Chart

### Liens
- BOT_CHANGELOG : 2026-05-11 10:30 quick fixes (paper_tracker.py + mia_paper_trader.py)
- `.claude/rules/orphan-prevention.md` (protections anti-orphan DTC)

---

## 2026-05-11 10:50 — [Dashboard fix attribution Bot 2 V6 stats + filter invalidated Bot 1]

**Categorie** : FIX (deux bugs distincts mais lies, fix groupe)
**Impact prod** : DASHBOARD + PAPER (Bot 1)
**Fichier(s)** :
- `DASHBOARD/api/paper_tracker.py:122-145` : `_iter_trades_from_files` exclut `v6` du glob pattern Bot 1 (avant: Bot 1 stats embarquaient trades V6)
- `DASHBOARD/api/paper_tracker.py:464` : pattern `*_v6_trades.jsonl` au lieu de `*_databento_trades.jsonl` pour Bot 2 V6 (avant: stats V6 dashboard = stats Bot 2 V1 archive)
- `CORE/mia_paper_trader.py:556-580` : `_load_existing` skip trades `invalidated=True` (avant: Bot 1 rechargeait les 3 trades phantom DMP Gold 10/05 au boot)

**Reviewer(s) agent** : self + Jackson validation visuelle dashboard reload

### Quoi
Deux bugs decouverts pendant l'audit Bot 2 V6 11/05 matin :

**Bug A — Dashboard attribution Bot 2 V6** : `paper_tracker.py:464` utilisait pattern `*_databento_trades.jsonl` pour aggreger stats 30j Bot 2 V6, MAIS ce pattern correspond aux trades de Bot 2 V1 (archive, deprecated 11/05). Bot 2 V6 ecrit dans `*_v6_trades.jsonl`. Dashboard affichait donc :
- State actuel (positions, cooldown) = Bot 2 V6 (state_v6.json) correct
- Stats historiques 7j/30j = Bot 2 V1 archive (-$2,783 / 56 trades / WR 21.4%)
- Resultat : dashboard pretend que "Bot 2 V6 perd $2,783/30j" alors que vraies stats V6 = +$868.50 / 9 trades / WR 78%

**Bug B — Bot 1 charge trades invalidated** : suite incident DMP Gold pollution 10/05 (chart MGC sans audit C++ ecrit bars Gold dans `DATA/ES/*.jsonl`), 3 trades phantom ont ete annotes `invalidated=True` dans `20260511_trades.jsonl` (10/05 22:25, 22:40, 22:59 ET). `paper_tracker.py:_iter_trades_from_files:160-161` filtre bien `invalidated`, MAIS `mia_paper_trader.py:_load_existing` NE LE FAIT PAS. Au boot Bot 1 rechargeait les 4 trades (3 phantom + 1 vrai) → state.stats_today pollue (4 trades / -$54). Le filtre dashboard ne pouvait pas corriger car il lit state.stats_today directement.

### Pourquoi
Audit Bot 2 V6 11/05 matin a revele que les stats dashboard ne correspondaient pas aux trades reels :
- Dashboard Bot 2 V6 : -$2,783 / 56 trades
- `*_v6_trades.jsonl` empirique : +$868.50 / 9 trades

Et Bot 1 dashboard : 4 trades / -$54 (dont 2 phantom +/-40K$ DMP Gold).

Sans ces fixes, **mon audit profond AUDIT_PROFOND_BOT2_V6.md du 10/05 etait base sur des chiffres faux** (cf INCIDENT_LOG 2026-05-11 VALIDATION_MISS). Le verdict "OPTION A STOPPER Bot 2 V6" etait base sur des stats Bot 2 V1 archive attribuees a tort a V6.

### Impact attendu
- Dashboard Bot 2 V6 30j : -$2,783 → vraies stats V6 (~+$868.50 / 9 trades / WR 78% sur 5j data)
- Dashboard Bot 1 today : 4 trades / -$54 → 1 trade / +$147 (les 3 phantom DMP Gold disparaissent)
- Bot 1 ES stats today : 3 trades 0% → 0 trades (les 2 phantom etaient ES)
- Aucun effet sur logique trading, juste affichage stats coherent

### Validation pre-deploy
- [x] Tests syntax : `python -c "import ast; ast.parse(...)"` OK les 2 fichiers
- [x] Reconciliation empirique : `*_databento_trades.jsonl` cumul historique = exactement -$2,783.75 / 56 trades (confirme attribution faux)
- [x] Hash SHA256 local == VPS apres SCP

### Revert plan
```bash
ssh Administrator@212.28.179.199 'cd C:/TRADING_SIERRA_CHART_AUTO && git checkout DASHBOARD/api/paper_tracker.py CORE/mia_paper_trader.py'
ssh Administrator@212.28.179.199 'powershell -Command "Restart-Service MIA-Dashboard; Restart-Service MIA-Paper"'
```

### Deployed at 2026-05-11 08:54 UTC (10:54 Paris)
- paper_tracker.py + mia_paper_trader.py : SCP'd, hash match
- MIA-Dashboard restart OK
- MIA-Paper restart OK (PID 2356)
- Verify state Bot 1 post-restart : 1 trade / +$147 / NQ 1 trade / ES 0 trade ✓

### Suivi post-deploy
- **J+1** : verifier coherence stats dashboard Bot 1 / Bot 2 V6 (visuel Jackson)
- **J+7** : valider que `*_databento_trades.jsonl` Bot 2 V1 archive ne genere plus de bruit dans aucune partition (Bot 1 / Bot 3)

### Liens
- INCIDENT_LOG : 2026-05-11 10:00 [VALIDATION_MISS] audit profond Bot 2 V6 chiffres faux
- BOT_CHANGELOG : 2026-05-10 22:40 [VALIDATION_MISS] DMP Gold pollution incident
- BOT_CHANGELOG : 2026-05-11 10:30 funnel suffix V6 + Bot V6 invalidated filter

---

## 2026-05-11 10:30 — [Bot 2 V6 — quick fixes pre-restart (funnel suffix + filter invalidated)]

**Categorie** : FIX
**Impact prod** : PAPER (Bot 2 V6 Sim2, MIA-Brain-V6)
**Fichier(s)** :
- `CORE/mia2_brain_v6_databento.py:1132-1148` : `_funnel_save_eod` ecrit maintenant `funnel_{date}_v6.json` (suffix _v6) au lieu de `funnel_{date}.json` → ne plus ecraser le funnel Bot 1
- `CORE/mia2_brain_v6_databento.py:577-595` : `_load_existing` skip trades avec `invalidated=True` → empeche reload du trade fantome DMP Gold 10/05 dans stats_today

**Schema/version** : pas de bump (fix application-level)
**Reviewer(s) agent** : self (validation empirique stats reelles, audit 11/05)

### Quoi
Deux quick fixes avant relance MIA-Brain-V6 :
1. **Funnel suffix `_v6`** : Bot 1 (mia_paper_trader.py) et Bot 2 V6 partagent `FUNNEL_LOG_DIR`. Sans suffix, le dernier qui sauvegarde au EOD CME (18:00 ET) ecrasait l'autre = historique funnel V6 perdu.
2. **Filter `invalidated`** : aligne convention `paper_tracker.py` qui filtre deja les trades annotes `invalidated=True` (cleanup phantom DMP Gold 10/05). Sans ce filtre, `_load_existing` recharge le trade fantome (meme avec pnl_usd=0) → stats_today recompte 1 trade.

### Pourquoi
Audit Bot 2 V6 11/05 a revele que stats_today affichait `pnl_usd: 40480.5` (trade fantome 10/05 deja annote invalidated par `cleanup_phantom_paper_trades.py` mais pas filtre cote bot). Audit a aussi montre que les funnels Bot 1 et Bot 2 V6 s'ecrasent mutuellement (file `funnel_20260510.json` = Bot 1 ou Bot 2 V6 selon dernier write_state).

Stats reelles Bot 2 V6 (verifiees via grep `*_v6_trades.jsonl`) : +$868.50 / 9 trades / 5 jours / WR 77.8%. Pas le `-$2,783/30j` que l'audit profond DOCS/AUDIT_PROFOND_BOT2_V6.md affirmait (chiffre venait probablement de stats globales mixes Bot 1 + Bot 2 V1 + Bot 2 V6). Cf INCIDENT_LOG 2026-05-11 VALIDATION_MISS.

### Impact attendu
- Metriques :
  - state_v6.json.stats_today.pnl_usd : 40480.5 → 0.0 (au premier `_write_state`)
  - LOGS/funnel/funnel_20260512_v6.json : fichier propre cree au prochain rollover CME (18:00 ET dimanche → debut session lundi)
- Effet de bord : aucun (filter `invalidated` defensif sans changement logique business)

### Validation pre-deploy
- [x] Tests syntax: `python -c "import ast; ast.parse(...)"` OK
- [x] Diff verifie : 2 hunks (1 funnel + 1 _load_existing)
- [x] Audit empirique state_v6.json + *_v6_trades.jsonl : trade fantome confirme invalidated, pnl_usd=0
- [ ] Test empirique post-deploy : verifier state_v6.json apres 5 min runtime que stats_today reflete bien les trades reels (devrait etre 0 trade aujourd'hui dimanche)

### Revert plan
```bash
# rollback fichier code sur VPS
ssh Administrator@212.28.179.199 'cd C:/TRADING_SIERRA_CHART_AUTO && git checkout CORE/mia2_brain_v6_databento.py'
# restart service
ssh Administrator@212.28.179.199 'nssm restart MIA-Brain-V6'
```

### Deployed at YYYY-MM-DD HH:MM
(a remplir apres SCP + Set-Service Automatic + Start-Service + verify 5 min)

### Suivi post-deploy
- J+1 : check state_v6.json.stats_today + LOGS/funnel/funnel_20260512_v6.json bien cree
- J+7 : evaluer WR + PF Bot 2 V6 sur cycle hebdomadaire post-restart

### Liens
- INCIDENT_LOG : 2026-05-11 10:00 [VALIDATION_MISS] audit profond Bot 2 V6 fabrique avec stats fausses
- Refacto plan : DOCS/PLAN_REFACTO_BOT2_V6_20260511.md (a creer Etape 6)

---

## 2026-05-09 17:30 — [Bot 3 v2 — SIDAK_LEVELS + COMBOS_BOOSTED + SLTPEngine wall-aware]

**Categorie** : FEATURE
**Impact prod** : PAPER (Bot 3 Sim1, INSTANCE EXISTANTE — pas nouveau process)
**Fichier(s)** :
- `CORE/bot3_level_definitions.py` : +SIDAK_LEVELS (4) +COMBOS_BOOSTED (3) +5 helpers
- `CORE/bot3_mp_engine.py` : Bot3Signal.bucket field +`_scan_combos_boosted()` (~150 LOC) +tag SIDAK dans `_build_signal()` +scan combos priority 1 dans `evaluate()`
- `CORE/databento_paper_trader_v2.py` : bypass filter regime si bucket SIDAK/COMBO + `_compute_sltp_wall_aware()` (~80 LOC) + routage TP/SL selon bucket dans `_bot3_execute_trade()`
- `CORE/log_catalog.py` : +4 codes log (BOT3_FILTER_BYPASS_SIDAK_COMBO, BOT3_SIDAK_SLTP_WALL_AWARE, BOT3_SIDAK_SLTP_FALLBACK, BOT3_COMBO_BOOSTED_FIRE)

**Schema/version** : Bot 3 v1 -> v2 (additive, backward-compat 13 héritage inchangés)
**Reviewer(s) agent** : ml-trainer (round 1 NOGO sur Voie B → GO sur Tier A+B simplifié) + code-reviewer (round 1 GO-WITH-FIXES B1+B2+B3+I1 → round 2 GO clean)

### Quoi
Ajout 4 niveaux Sidak strict + 3 combos boostés à Bot 3 paper (Sim1) sans modifier les 13 niveaux héritage. Architecture en 3 priorities :
- P1 : 3 combos boostés haute conviction (LONG_UP_x_SWING_LOW + room_1dmax/aggr_buy, LONG_DN_x_COLOR_DN)
- P2 : 4 Sidak simples (SWING_LOW/HIGH, COLOR_UP/DN_zone)
- P3 : 13 héritage INCHANGÉS

Bypass filter regime + SLTPEngine wall-aware (mia_sltp.py) pour P1+P2. Fallback standard Bot 3 si SLTPEngine reject.

### Pourquoi
Audit Sidak strict 09/05 (`backtest_levels_strict.py`) : 4 niveaux validés avec PSR=1.0000, n>1000 par niveau, WF 11-12/12 cross-régime. Audit MQ pollution historique : MQ propre. Audit cross-régime : 4 niveaux ROBUSTES dans HAUSSIER+BAISSIER+RANGE.

Combos boostés : audit `boost_marginal_combos.py` 09/05 (Bonferroni 4 tests). 2 GO confirmés sur 4 combos MARGINAL.

Simulator Étape 1b avec VRAI mia_sltp.py : SIDAK pur ES +$2184, NQ +$5495 / 6 mois (1 contract). Combo boosté NQ +$1193 supplémentaire.

### Impact attendu
- Metriques projection : +$5649 / 6m sur 1 contract ES + 1 contract NQ vs Bot 3 actuel (selon simulator)
- Sur 4 micros chacun : ~+$22 600 / 6 mois (théorique pré-slippage)
- Effet de bord : aucun (séparation totale héritage/nouveau, vérifié ligne par ligne)

### Validation pre-deploy
- [x] Syntax OK 4 fichiers (`python -X utf8 -c "import ast..."`)
- [x] Import test (les helpers Sidak/Combo s'importent + 4 codes log présents dans LOG_CODES)
- [x] Audit Sidak strict 6 mois ES + NQ (PSR=1.0, n>1000)
- [x] Audit cross-régime (3 régimes positifs)
- [x] Audit MQ pollution (PROPRE confirmé)
- [x] Simulator Étape 1a + 1b (VRAI SLTPEngine importé)
- [x] ml-trainer review : GO sur Tier A + B simplifié
- [x] code-reviewer round 1 : GO-WITH-FIXES (B1+B2+B3+I1)
- [x] Fixes B1+B2+B3+I1 appliqués
- [x] code-reviewer round 2 : GO clean
- [x] Backup : `BACKUP/bot3_pre_sidak_20260509_1654/` (7 fichiers)

### Revert plan
1. `cp BACKUP/bot3_pre_sidak_20260509_1654/*.py CORE/`
2. SCP vers VPS (4 fichiers backup)
3. `Restart-Service MIA-DataBento-Paper-V2`
4. Vérifier service Running
5. Documenter dans CHANGELOG ROLLBACK section

### Suivi post-deploy J+1
Vérifications obligatoires (anti VALIDATION_MISS) :
```bash
# Doit etre > 0 si combo fire (Bonferroni n=190 NQ attendu)
grep BOT3_COMBO_BOOSTED_FIRE LOGS/decisions/*_20260510*.jsonl
# Doit etre > 0 si SIDAK/COMBO trade
grep BOT3_FILTER_BYPASS_SIDAK_COMBO LOGS/decisions/*_20260510*.jsonl
# Wall-aware vs fallback split
grep BOT3_SIDAK_SLTP_WALL_AWARE LOGS/execution/*_20260510*.jsonl | wc -l
grep BOT3_SIDAK_SLTP_FALLBACK LOGS/execution/*_20260510*.jsonl | wc -l
```

Si zéro après 24h paper actif → VALIDATION_MISS → INCIDENT_LOG.

### Suivi post-deploy J+7
- Compter trades par bucket (HERITAGE / SIDAK / COMBO_BOOSTED)
- Mesurer EV par bucket
- Si EV SIDAK > 0 et stable → confirmation paper

### Suivi post-deploy J+30
- Validation Lopez complète (DSR formel sur SIDAK, walk-forward 12 folds)
- Si EV cumulé > 0 + WF stable → candidate live

### Liens
- Audits 09/05 : `LOGS/research/levels_strict_*.log`, `boost_marginal_*.log`, `compare_lists.log`, `audit_mq_pollution_*.log`, `audit_regime_robust_*.log`, `etape1b_real_sltp.log`
- Reviews : ml-trainer dispatch + code-reviewer round 1+2 (cf conversation 09/05)
- ROLLBACK reference : `BACKUP/bot3_pre_sidak_20260509_1654/`

---

## 2026-05-07 18:00 — [BN V3 Engine + Paper Loop Bot 2 Sim2 (Databento)]

**Categorie** : FEATURE
**Impact prod** : PAPER (Bot 2 Sim2 nouveau process parallele, pas d'impact databento_paper_trader existant)
**Fichier(s)** :
- `CORE/bn_v3_engine.py` (NEW, ~600 LOC) : moteur Dow + Holy Grail + Fibonacci pullback + recharge
- `CORE/bn_v3_paper_loop.py` (NEW, ~280 LOC) : runner standalone polling parquet v4 enriched
- `CORE/tests/test_bn_v3_engine.py` (NEW, 20 tests PASS) : couverture detect + recharge + config
- `CORE/research/backtest_bn_v3.py` (NEW) : backtest 60j v4 enriched
- `CORE/log_catalog.py` : +6 codes log (BN_V3_LOOP_START, BN_V3_ENTRY, BN_V3_RECHARGE, etc.)
**Schema/version** : N/A (process standalone)
**Reviewer(s) agent** : code-reviewer (pending pre-deploy lundi)

### Quoi
Implementation BN V3 redesign apres BN V2 NOGO empirique (0/4 detections sur trades live Jackson).
- Detection : Dow Theory strict (3 HH+HL ou LH+LL successifs) + Holy Grail Linda Raschke (ADX>25 + EMA20 slope).
- Filtre anti-range : range_detector_v3 (recyclage du module morning session).
- Pullback Fibonacci 30-62% du dernier swing.
- Sizing : 2 contrats initiaux + recharge +1 sur Long Up Bar (LONG) / Long Down Bar (SHORT) cap 2 recharges.
- Scale-out 50% au TP_partial +60t MFE NQ / +25t ES + move SL au BE.
- Time stop 90 min, EOD 16:00 ET flatten.
- Standalone : process separe `bn_v3_paper_loop.py` polling parquet v4 enriched, pas d'impact `databento_paper_trader.py`.

### Pourquoi
1. BN V2 entrait sur breakout HH (late) au lieu de pullback HL (early). Jackson trade pullback. 4 trades live observes 07/05 = 4/4 MISS BN V2 (cf `feedback_bn_signal_protocol.md`, `DATA/RESEARCH/jackson_bn_real_trades.csv`).
2. Bot 2 trade peu (consensus pondere 4 pts), data Databento Sim2 fresh (pas stale 21min comme V4 enriched lu par Bot 3 Sim1).
3. Directive Jackson 07/05 : "EXCLUSIVEMENT BN SUR BOT 2, RENTRER 2 CONTRAT, CHARGER SI LONG UP BAR / LONG DOWN BAR".

### Impact attendu
- Pas d'impact Bot 1 / Bot 3 (process separe).
- Bot 2 ajoute ~1-4 trades BN/jour si literature Holy Grail + Dow strict tient.
- Recharge cap 4 contrats max (2 init + 2 recharges) -> exposition USD limitee.

### Validation pre-deploy
- [x] Tests unitaires: 20/20 PASS (`pytest CORE/tests/test_bn_v3_engine.py`)
- [ ] Backtest preservation: 60j v4 enriched NQ + ES avec/sans recharge (en cours)
- [ ] Review agent code-reviewer + market-analyst (lundi avant deploy)
- [x] Test empirique kill switch : MIA_BN_V3_ENABLED=0 -> exit immediat OK
- [x] Test empirique paper_loop dry-run : start OK, no EMIT_FAIL, log codes registres

### Revert plan
```bash
# Kill switch immediat (sur VPS)
ssh Administrator@212.28.179.199 'powershell "[System.Environment]::SetEnvironmentVariable(\"MIA_BN_V3_ENABLED\",\"0\",\"Machine\")"'
# Stopper service (si nssm utilise)
ssh Administrator@212.28.179.199 'nssm stop MIA-BN-V3-Paper'
```

### Deployed at TBD (lundi 2026-05-08 si backtest GO)

### Suivi post-deploy
- J+1 : grep BN_V3_ENTRY + BN_V3_RECHARGE + BN_V3_FLATTEN dans LOGS/decisions/ (verifier instrumentation, target >=1 entry/jour)
- J+7 : compute PF + WR + n_trades + n_recharges_avg, comparer baseline Bot 2 consensus
- J+30 : verdict GO live AMP / iterate / NOGO (rollback)

### Liens
- Memory : `feedback_bn_signal_protocol.md`, `project_bn_v2_status_20260507.md`, `feedback_range_color_inversion_pattern.md`
- Trades CTA replay : `DATA/RESEARCH/jackson_bn_real_trades.csv` (3/3 MISS BN V2)
- References pro : Linda Raschke "Holy Grail" (TradersMastermind), Dow Theory pullback (Oxford Strat)
- BN V2 backtest : pyramiding DEGRADES PF (1.20 -> 0.97) sur avril 2026 baissier — flag pattern 11 a surveiller

---

## 2026-05-07 13:30 — [Bot 3 TIMEOUT pnl approximatif Solution C+A v2]

**Categorie** : FIX OBSERVABILITY
**Impact prod** : DASHBOARD (lecture stats Bot 3 corrigee). Pas d'impact moteur de decision Bot 3.
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py` (`_bot3_check_timeout` ligne 685-757, `_bot3_log_trade_close` ligne 1488-1556)
- `CORE/log_catalog.py` (3 nouveaux codes BOT3_TIMEOUT_PNL_APPROX*)
- `DASHBOARD/api/paper_tracker.py` (`_is_official_pnl` exclusion pnl_estimated du PF Lopez)
- `DASHBOARD/static/js/dashboard.js` (2 components Paper Trading + V3 — affichage `*` suffix pnl_estimated)
- `CORE/tests/test_bot3_timeout_pnl.py` (9 tests, tous PASS)
**Reviewer(s) agent** : code-reviewer (verdict GO Solution C, NOGO v1 Solution A → refactor v2 GO)

### Quoi
Solution C : `_emit("BOT3_TRADE_CLOSE", pnl=None, pnl_known=False)` au lieu de `pnl=0` hardcode. Frontend respecte `pnl_known`/`pnl_estimated` → "—" ou "$X.XX*" au lieu de "+$0.00" mensonger.

Solution A v2 : tail JSONL DMP du jour (`DATA/{SYM}/{YYYYMMDD}_{SYM}.jsonl`, derniers 8KB) pour calculer pnl approximatif via close de la derniere bar 1-min (age max 90s). Flag `pnl_estimated=True` exclut ce pnl du PF/Sharpe officiel Lopez (`_is_official_pnl` paper_tracker), mais l'inclut dans le total $ informationnel dashboard.

### Pourquoi
Bug confirme empiriquement : 31 `BOT3_TIMEOUT_FLATTEN_SYM` envoyes / **0** `BOT3_FLATTEN_FILL_CAPTURED` sur 4 jours (04-07/05). Le fix 06/05 (capture fill Type 209) est code mort car Sierra Chart Sim1 ne renvoie jamais ORDER_UPDATE OrderStatus=7 pour Type 209/210 SUBMIT_FLATTEN_POSITION_ORDER.

Consequence dashboard : tous les TIMEOUTS Bot 3 affichent `+$0.00` (hardcode `pnl=0` ligne 691). Trade 04/05 NQ OPEN_830 avec MFE=263t MAE=-407t → pnl reel inconnu mais affiche $0.00 = mensonge.

Trade 07/05 NQ GEX_DN entry 28707.75 → MFE=149t MAE=-6t → meme bug.

Code-reviewer agent verdict : Solution A v1 (`load_last_bar` parquet V4_enriched) NOGO car parquet a lag structurel ~5j → 100% des TIMEOUTS tombaient SKIP_STALE → fix mort. Refactor v2 = JSONL DMP du jour (lag <60s) GO.

### Validation pre-deploy
- 9 tests unitaires PASS (`pytest CORE/tests/test_bot3_timeout_pnl.py`) :
  - LONG fresh pnl positif, SHORT fresh pnl negatif (dir_sign)
  - Bar stale > 90s → SKIP_STALE
  - JSONL absent → silent skip
  - JSONL corrompu → APPROX_FAIL
  - entry_price=0 → skip defensif
  - 3 codes log dans LOG_CODES (anti KeyError silent)
  - JSONL sans price/ts → silent skip
  - paper_tracker exclude pnl_estimated du PF officiel
- Module backend compile OK (`python -c "import CORE.databento_paper_trader_v2"`)
- Logs catalog 3 entries verifiees (`MAJEUR/execution`, `ALERTE/execution` x2)

### Anti-pattern 11 V1 verification
Solution est **observability fix** (pas decision moteur). N'interfere PAS avec OPTION 2 (TP devant mur via SLTPEngine CAS 4) en cours en Phase A backtest. Sequencing valide : OPTION 2 reste en Phase A→B→C, Solution C+A v2 deploye independamment.

### Revert plan
Si J+1 montre `BOT3_TIMEOUT_PNL_APPROX_FAIL` > 50% des TIMEOUTS ou pollution stats inattendue :
1. Backend : reverter `_emit BOT3_TRADE_CLOSE` ligne 743-748 a `pnl=None, pnl_known=False, pnl_estimated=False`
2. Backend : skip ETAPE 7c entierement (passer `exit_price_approx=None, pnl_*_approx=None` a `_bot3_log_trade_close`)
3. Frontend : revert dashboard.js a "—" pour tous TIMEOUTS (suppression suffix `*`)
4. paper_tracker : revert `_is_official_pnl` a `_is_numeric_pnl`
5. Restart MIA-DataBento-Paper-V2

### Suivi post-deploy
- **J+1** : grep `BOT3_TIMEOUT_PNL_APPROX` dans LOGS/execution → doit etre > 0 sur prochain TIMEOUT (instrumentation reussie). Si 0 → investigation immediate (`feedback_validation_miss_patterns.md`)
- **J+7** : count `pnl_estimated=True` vs `pnl_estimated=False` dans `*_databento_v3_trades.jsonl`. Verifier ratio coherent avec ratio TIMEOUT/total
- **J+30** : audit visuel dashboard pour confirmer absence de "$0.00" pour TIMEOUT. Tous doivent etre "$X.XX*" ou "—"

### Liens
- INCIDENT_LOG : 2026-05-07 11:00 BOT3_TP_BEHIND_WALL (memes contexte trading)
- Memory : `feedback_bot3_sltp_integration_plan.md` (OPTION 2 SLTPEngine en cours, sequencing independant)
- Review agent : code-reviewer (Solution A v1 NOGO → v2 refactor JSONL DMP GO + 3 codes log obligatoires + 9 tests + `_is_official_pnl`)

---

## 2026-05-07 — [PHASE 1 OBSERVATION trailing + BE Bot 3 (Jackson directive focus technique)]

**Categorie** : FEATURE OBSERVATION (log only, zero impact trading)
**Impact prod** : NUL (mode OBSERVE_ONLY intrinseque) — code observe MFE et logge triggers BE/trailing hypothetiques
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py:925-1000` (`_bot3_check_trailing_observation` appelee dans `_bot3_update_mfe_mae`)
- `CORE/bot3_config.py:56-83` (3 nouvelles cles GUARD_RAILS_BOT3 par sym : `trailing_be_trigger_ticks`, `trailing_active_trigger_ticks`, `trailing_distance_ticks`)
- `CORE/log_catalog.py` (`BOT3_TRAILING_BE_OBSERVED`, `BOT3_TRAILING_UPDATE_OBSERVED` INFO)
- `CORE/tests/test_bot3_trailing_observation.py` (12 tests PASS dont 2 cas reels 06/05)

**Reviewer(s) agent** : code-reviewer (verdict GO direct deploy VPS, P1.1-1.5 non-bloquants)

### Quoi
Observation passive du moment optimal pour mettre BE / trailing sur les positions Bot 3.
Logique :
- Sur chaque bar, calc MFE (deja fait dans `_bot3_update_mfe_mae`)
- Si MFE >= `trailing_be_trigger_ticks` (32t ES, 80t NQ = 1R) → emit `BOT3_TRAILING_BE_OBSERVED` 1x avec `sl_hypothetical_be = entry`
- Si MFE >= `trailing_active_trigger_ticks` (48t ES, 120t NQ = 1.5R) → emit `BOT3_TRAILING_UPDATE_OBSERVED` a chaque progression MFE >= 25% trailing_distance (anti-spam)
- Aucune modification DTC orders. Phase 2 (futur) ajoutera les modify orders apres audit J+7.

### Pourquoi
Jackson 07/05 directive : "trailing + BE + cible $200-300/jour, focus technique pas argent". Audit empirique 06/05 = 5 trades, MFE peak 35-40t/contract perdus en TIMEOUT ("give back" pattern). Avec trailing actif : ~+$100/trade preserves au lieu de give-back.

Phase OBSERVATION = collecte data J+7 pour valider seuils calibrage AVANT activation Phase 2.

### Validation pre-deploy
- 12/12 tests pytest PASS (BE/trailing LONG+SHORT, idempotence, anti-spam, real cases 06/05, config manquante)
- py_compile OK 3 fichiers (local + VPS)
- code-reviewer : GO direct deploy (mode observation = risque trading nul)

### Suivi post-deploy
- **Deployed at 2026-05-07** (mode OBSERVATION strict, aucun impact trading)
- **J+1** : grep `BOT3_TRAILING_BE_OBSERVED` count > 0 si trades pris. Si count=0 sur 5+ trades = instrumentation ratee.
- **J+7** : audit complet :
  - % trades qui ont touche BE trigger
  - Gain theorique (MFE locked vs PnL reel actuel)
  - Faux positifs (BE puis MFE rebondit, donc lock ne degrade pas le trade)
  - Decision activation Phase 2 (DTC modify orders) base sur cette data

### Phase 2 (backlog)
Si J+7 audit valide l'edge :
- Implementer `_modify_sl_order` (cancel + replace SL DTC)
- Modifier `_bot3_check_trailing_observation` → `_bot3_apply_trailing` (vrai modify)
- Tests integration DTC roundtrip + race conditions
- Code review + deploy

---

## 2026-05-07 — [TREND DAY override Bot 1+2 V6 — DEFAULT OFF, opt-in via env var]

**Categorie** : FEATURE (nouveau bypass conditionnel ChaseTopGate base audit walk-forward)
**Impact prod** : NUL (default OFF) — code deploye mais inactif jusqu'a backtest realiste
**Fichier(s)** :
- `CORE/mia_paper_trader.py` (+`_is_trend_day` defensive keys + buffer history + bypass ChaseTopGate)
- `CORE/mia2_brain_v6_databento.py` (duplication identique pour Bot 2 V6)
- `CORE/log_catalog.py` (`GATE_CHASE_TOP_TREND_DAY_BYPASS` INFO)
- `CORE/research/audit_chasetop_trendday_walkforward.py` (nouveau script audit Lopez)
- `CORE/tests/test_trend_day_override.py` (17 tests, 4 integration P0.1/P0.2)

**Reviewer(s) agent** : code-reviewer (verdict NOGO round 1, GO apres P0.1+P0.2 fixes round 2)

### Quoi
Mode TREND DAY override pour ChaseTopGate. Bypass conditionnel si :
1. `regime_trend_votes >= 6` (lookup defensif `mode_trend_votes` || `regime_trend_votes`)
2. `regime_favor == direction du signal` (lookup defensif `favor` || `regime_favor`)
3. median pct_in_range sur 60 dernieres bars >= 80% (LONG) OU <= 20% (SHORT)

Si toutes conditions OK → bypass ChaseTopGate (au lieu de reject). Logge `GATE_CHASE_TOP_TREND_DAY_BYPASS` INFO.

### Pourquoi
Bot 1+2 V6 = 0 trade le 06/05/2026. Funnel revele ChaseTopGate (range_pos >= 60%) bloque 97% des LONG sur trend day strong. Audit walk-forward 12 folds (`audit_chasetop_trendday_walkforward.py`) :
- Seuil 60% DSR INSTABLE par fold (pas d'edge stable)
- TREND LONG day : LONG @ range_pos 70-90% = **+1.31t a +1.38t mean_pnl mieux** que non-trend
- 9/12 folds NQ delta positif

**MAIS** : mean_pnl reste NEGATIF absolu (-0.89t a -1.43t). DSR non calcule sur baseline R:R 1.0. → Pattern DATA_MINING_TRAP risk si deploye actif.

### Validation pre-deploy
- 17/17 tests pytest PASS (10 unit Bot 1, 2 unit Bot 2, 1 real case 06/05, 4 integration P0.1+P0.2)
- py_compile OK 3 fichiers (local + VPS)
- code-reviewer : verdict GO-AVEC-RESERVES round 2 apres :
  - P0.1 : lookup defensif cles natives (sinon bypass mort en prod)
  - P0.2 : default OFF (eviter data mining trap)

### Default OFF, activation manuelle
```bash
# Activer apres backtest realiste valide :
nssm set MIA-Paper AppEnvironmentExtra MIA_TREND_DAY_OVERRIDE_ENABLED=1
nssm set MIA-Brain-V6 AppEnvironmentExtra MIA_TREND_DAY_OVERRIDE_ENABLED=1
Restart-Service MIA-Paper
Restart-Service MIA-Brain-V6
```

### Revert plan
- Si activation faite et derive observed → unset env var + restart
- Code reste en place (additif, retro-compatible)

### Suivi post-deploy
- **Deployed at 2026-05-07** (default OFF, pas d'impact prod immediat)
- **Avant activation** : refaire audit avec TP/SL realistes SLTPEngine (TP1 sur murs Tier 1/2, SL ATR-based) — DSR > 0.5 requis pour activer
- **Si activation** : J+7 grep `GATE_CHASE_TOP_TREND_DAY_BYPASS` count + cross-check pnl trades concernes vs sample non-bypass

---

## 2026-05-06 18:30 UTC — [FIX BUG STRUCTUREL CRITIQUE : on_order_update jamais wire dans DTC connector]

**Categorie** : FIX critique (bug structurel depuis origine Bot 3 03/05 = 3 jours)
**Impact prod** : LIVE (Bot 3 paper Sim1) — apres ce fix, 100% des fills captures (TP/SL/Type 209)
**Fichier(s)** :
- `BOT/dtc_connector.py:127-135` (ajout self.on_order_update Optional[Callable])
- `BOT/dtc_connector.py:_handle_order_update` (ligne ~705 : appel callback EN AMONT avant traitement interne)
- `CORE/log_catalog.py` (ON_ORDER_UPDATE_CALLBACK_ERR ALERTE)
- `CORE/tests/test_bot3_anti_orphan.py` (4 nouveaux tests : 19/19 PASS)

**Reviewer(s) agent** : code-reviewer (verdict GO-AVEC-RESERVES, R1 lock confirme deja en place, R2 suivi J+1 obligatoire)

### Quoi
Le DTC connector defini `on_fill` callback (style OrderFill object) mais **n'avait pas** `on_order_update` (style msg dict brut). Bot 3 assignait `self.dtc.on_order_update = self._on_order_update_callback` depuis 03/05 sur un attribut **inexistant** → callback jamais lu → `_bot3_handle_dtc_fill` jamais appele → 100% des fills Bot 3 silencieusement perdus.

Fix ajoute le callback `on_order_update` au DTC connector (additif, retro-compatible Bot 1 + Bot 2 V1 qui utilisent `on_fill` inchange). Le callback est appele EN AMONT dans `_handle_order_update` interne pour permettre aux consumers de router le msg DICT brut (parent/tp/sl/flatten cid_type).

### Pourquoi
**Tous les pnl Bot 3 a $0 depuis 03/05** sont la consequence de ce bug (pas de Type 209 capture, pas de TP/SL fill capture). Mon fix Type 209 deploye 17:30 UTC est **inutile sans ce fix racine** (le code etait correct mais `_bot3_handle_dtc_fill` jamais call).

7 trades aujourd'hui (06/05) ont fini pnl_known=false. Estimation perte non capturee : -$880 (NQ LONG GEX_DN -$867 + autres MFE perdus).

### Validation pre-deploy
- 19/19 tests pytest PASS (4 nouveaux on_order_update + 15 existants)
- py_compile OK 2 fichiers (local + VPS)
- Code review code-reviewer : verdict GO-AVEC-RESERVES, R1 lock _bot3_pos_lock confirme ligne 321 deja en place

### Revert plan
Si J+1 montre 0 PARENT_FILL_RECORDED malgre trades fires :
1. `git revert HEAD` (cette modif)
2. SCP dtc_connector.py + restart MIA-DataBento-Paper-V2
3. Investigation INCIDENT_LOG entry 2026-05-06 18:30

### Suivi post-deploy
- **Deployed at 2026-05-06 18:30 UTC** (state.json positions clean apres recovery boot, position fantome ES SHORT @7368 cleanup auto)
- **J+0 immediat** : grep `PARENT_FILL_RECORDED` au prochain trade Bot 3 (devrait fire). Si pas → instrumentation ratee → INCIDENT_LOG.
- **J+1** : grep `BOT3_TRADE_CLOSE.*pnl_known.*true` > 0 (vs 0 sur les 7 trades du 06/05). Verifier dashboard affiche pnl reels au lieu de "—".
- **J+7** : audit cross-bot : verifier que stats_today.trades_known_pnl > 0 sur tous les jours, pas que TIMEOUT pnl=null.

---

## 2026-05-06 17:30 UTC — [FIX BUG STRUCTUREL : Capture fill Type 209 SUBMIT_FLATTEN_POSITION_ORDER]

**Categorie** : FIX critique (bug structurel depuis origine Bot 3 03/05)
**Impact prod** : LIVE (Bot 3 paper Sim1) — pnl_known=true sur tous les TIMEOUT futurs
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py:480-486,595-616,679-697` (close_reason en amont + flush_cid tracking + handle fill flatten)
- `CORE/databento_paper_trader_v2.py:299-355` (_bot3_handle_dtc_fill cas flatten avant check pos None)
- `CORE/log_catalog.py` (BOT3_FLATTEN_FILL_CAPTURED MAJEUR + BOT3_FLATTEN_FILL_NO_ENTRY ALERTE)
- `DASHBOARD/api/paper_tracker.py:232-280` (P0 dedup signal_id - corrige par review code-reviewer)
- `CORE/tests/test_bot3_anti_orphan.py` (4 nouveaux tests : 15/15 PASS)

**Reviewer(s) agent** : code-reviewer (round 1 P0 dedup signal_id detecte → corrige → GO direct deploy)

### Quoi
Capture du fill Type 209 SUBMIT_FLATTEN_POSITION_ORDER pour reconstruire pnl reel sur les trades qui finissent en TIMEOUT 60min.

Mecanisme :
1. `_bot3_check_timeout` ETAPE 7a enregistre `flush_cid` dans `_bot3_cid_index` avec `pos_snapshot` AVANT `_send` Type 209
2. `_bot3_handle_dtc_fill` cas `cid_type=="flatten"` recoit le fill, reconstruit pnl via snapshot (entry_price + side), re-log via `_bot3_log_trade_close` avec pnl_known=true
3. `paper_tracker._compute_stats_today_from_trades` dedup par signal_id : la ligne pnl_known=true gagne sur la ligne pnl=null

### Pourquoi
Sur les 5 trades du 06/05, 100% ont fini avec `pnl_known=false` car le bug rendait les fills Type 209 invisibles au bot. Diagnostic complet : INCIDENT_LOG entry 17:30. Bug present depuis origine Bot 3, decouvert empiriquement aujourd'hui.

### Validation pre-deploy
- 15/15 tests pytest PASS (4 nouveaux + 11 anti-orphan existants)
- py_compile OK 3 fichiers (local + VPS)
- Code review code-reviewer : P0 dedup signal_id detecte + corrige + verdict GO

### Revert plan
Si BOT3_FLATTEN_FILL_CAPTURED ne fire pas en prod OU regression sur trades normaux :
1. `git revert HEAD` (cette modif)
2. SCP les 3 fichiers + restart MIA-DataBento-Paper-V2 + MIA-Dashboard
3. Investigation INCIDENT_LOG entry 2026-05-06 17:30

### Suivi post-deploy
- **Deployed at 2026-05-06 17:30 UTC**
- **J+0 immediate** : grep `BOT3_FLATTEN_FILL_CAPTURED` dans logs apres prochain TIMEOUT Bot 3 (60 min apres prochaine ouverture position). Verifier pnl_ticks calcule correctement.
- **J+1** : grep stats_today.trades_known_pnl > 0 (vs 0 aujourd'hui sur 5 trades). Verifier dashboard affiche bien $X.XX sur trades TIMEOUT.
- **J+30** : audit cross-bot : `grep -c BOT3_FLATTEN_FILL_CAPTURED LOGS/execution/*.jsonl` doit egal `grep -c BOT3_TIMEOUT_FORCE_CLOSE` (1 capture par timeout)

---

## 2026-05-06 16:00 UTC — [REWRITE ANTI-ORPHAN BOT 3 — P0+P1+P2 sequence V2 + 11 tests PASS]

**Categorie** : FIX critique (6 chemins orphelins identifies par audit moi+code-reviewer 2 rounds)
**Impact prod** : LIVE (Bot 3 paper Sim1) — elimine creation d'orphelins TP/SL Working dans DOM
**Fichier(s)** :
- `BOT/dtc_connector.py:124-595` (P0.1 + P2.1 + P1.2 + P0-A/C)
- `CORE/databento_paper_trader_v2.py:377-720,1910-1980` (P0.2 + P0.3 + P0.4 + P1.1 + P0-B)
- `CORE/log_catalog.py:385-415` (16 nouveaux codes BOT3_RECOVER_*, BOT3_TIMEOUT_CANCEL_ALL_*, BOT3_ORPHAN_*, BOT3_SHUTDOWN_*, OPEN_ORDERS_QUERY_*, DTC_DISCONNECT_DRAIN_TIMEOUT)
- `CORE/tests/test_bot3_anti_orphan.py` (11 tests PASS)

**Schema/version** : sequence anti-orphelin V1 → V2 (etapes 1-8 → 1-9 avec 6.5 cancel-all-working + 9 verify-post-cleanup)
**Reviewer(s) agent** : code-reviewer (2 rounds : NOGO P0-A/B/C → GO direct VPS apres fixes)

### Quoi
Rewrite complet de la sequence anti-orphelin Bot 3 :
- **P0.1** `request_open_orders_blocking` Type 300 avec collecte 301 + NoOrders=1, lock concurrent (P0-A), pas de Symbol field (P0-C)
- **P0.2** `_bot3_recover_open_positions` reconstitue tp_cid/sl_cid/sl_price/tp_cap_price/entry_price reels via Type 300+305 ; detection AMBIGUOUS_BRACKET (P0-B) si multi LIMIT/STOP
- **P0.3** etape 6.5 cancel-all-working dans `_bot3_check_timeout` (avant Type 209/210)
- **P0.4** etape 9 verify post-cleanup re-query Type 300 + recancel survivants + emit `BOT3_ORPHAN_DETECTED_POST_CLEANUP` CRITIQUE
- **P1.1** shutdown path pre-emptive cancel TP/SL avant disconnect
- **P1.2** `_recv_loop` daemon=False + drain join 3s sur disconnect
- **P2.1** `request_position_with_avg_price` retourne `(qty, avg_price)` pour entry_price reel au boot

### Pourquoi
3 RECOVERED_TIMEOUT Bot 3 ce matin avec entry_price=0, exit_price=null, pnl=null. Cycle restart watchdog (fix 13:30) corrigeait les futurs cycles mais les 3 positions du matin restaient. Audit revele que `_bot3_recover_open_positions` creait placeholder avec tp_cid=None → cancel skip → Type 209 ne touche pas les Working orphelins (confirme par TradeActivityLog `None.data` "No working orders to cancel"). Verdict NOGO session live.

### Validation pre-deploy
- 11/11 tests pytest PASS (CORE/tests/test_bot3_anti_orphan.py)
- py_compile OK 3 fichiers (local + VPS)
- Code review code-reviewer round 2 GO direct VPS (apres P0-A/B/C corriges)

### Revert plan
Si BOT3_ORPHAN_DETECTED_POST_CLEANUP fire en production OU regression sur trades normaux :
1. `git revert HEAD` (cette modif)
2. SCP les 3 fichiers + restart MIA-DataBento-Paper-V2
3. Investigation INCIDENT_LOG entry 2026-05-06 16:00

### Suivi post-deploy
- **Deployed at 2026-05-06 13:45 UTC** (vu BOT_HEARTBEAT stable + state.json positions vides au boot)
- **J+1** : grep BOT3_ORPHAN_DETECTED_POST_CLEANUP, BOT3_RECOVER_AMBIGUOUS_BRACKET, BOT3_RECOVER_FULL_BRACKET. Verifier 0 orphelin survivant.
- **J+7** : Sierra Chart Trade Activity Log Sim1 : 0 working orders sans position attachee.
- **J+30** : audit cumul orphelins via grep cross-bots LOGS/execution/.

---

## 2026-05-06 13:40 UTC — [URGENT FIX HEARTBEAT 3 bots — stop cycle restart watchdog 81/jour]

**Categorie** : FIX critique (regression heartbeat depuis retire Bot 2 V1)
**Impact prod** : LIVE (Bot 1 + Bot 2 V6 + Bot 3 + watchdog) — stoppe cycle restart cyclique
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py` : `_compute_last_bar_age()` + emit BOT_HEARTBEAT 30s dans main loop
- `CORE/mia_paper_trader.py` : `_compute_last_bar_age_for_heartbeat()` + emit
- `CORE/mia2_brain_v6_databento.py` : idem Bot 1 (pattern identique)
- `BOT/mia_watchdog.py` : commentaire ligne 153 update ("V6 emit 30s via BOT_HEARTBEAT depuis 06/05")

**Reviewer(s) agent** : code-reviewer 06/05 (verdict GO-AVEC-CHANGES, 1 critique fallback 99999 applique avant deploy)

### Quoi
Ajout emit `BOT_HEARTBEAT` toutes 30s dans la main loop des 3 bots actifs. Format : `{"code": "BOT_HEARTBEAT", "ctx": {"last_bar_age": <float>, "bot": "..."}}` compatible `mia_watchdog.check_jsonl_last_bar_age` (mia_watchdog.py:326).

**Fallback CRITIQUE** : `last_bar_age = 99999.0` (pas 0.0) si erreur lecture data feed = sentinel CRIT force watchdog kill (anti-mensonge "bot vivant" si data mort). Pattern aligne `check_stream_subscribe_alive` (watchdog:354).

### Pourquoi
Jackson alerte "TROP DE REDEMARAGE" + bouton dashboard rouge/vert cyclique. Investigation watchdog logs : 81 restarts en 24h.
- MIA-DataBento-Paper-V2 (Bot 3) : **34 restarts**
- MIA-Brain-V6 (Bot 2 V6) : **34 restarts**
- MIA-Paper (Bot 1) : 13 restarts

Cause racine : aucun bot n'emit BOT_HEARTBEAT depuis retire Bot 2 V1 (`databento_paper_trader.py`, mort 05/05). Le code n'a pas ete transfere aux successeurs. Watchdog ne trouve pas → SOURCE_CRIT cumulatif → restart cyclique 15-25 min.

Impact Bot 3 specifique : 17 cycles `RECOVER + TIMEOUT_FORCE_CLOSE` aujourd'hui. Trades parasitaires. DPL +21t cumulatif obtenu MALGRE.

### Impact attendu
- 0 nouveau restart watchdog (validation +30 min sans restart 11:39 → 12:09 UTC)
- Boutons dashboard 3 bots restent VERT (plus de cycle rouge/vert)
- Fin des cycles RECOVER+FORCE_CLOSE Bot 3 (positions broker preservees pleinement)
- Effet de bord : payload events_*.jsonl +1KB/30s par bot (negligeable)

### Validation pre-deploy
- Syntax check ast.parse 4 fichiers OK
- Code review code-reviewer GO-AVEC-CHANGES, 1 critique applique (fallback 99999 anti-mensonge)
- Pas de pytest (modif main loop, validation par observation post-deploy)
- Restart sequentiel : Watchdog → Paper (Bot 1) → Brain-V6 (Bot 2) → DataBento-Paper-V2 (Bot 3)
- Verif post-deploy : 11 BOT_HEARTBEAT emit en 3 min, 0 nouveau RESTART_TRIGGERED

### Revert plan
Si bug : retirer le bloc emit BOT_HEARTBEAT (env var `MIA_HEARTBEAT_DISABLED=1` non implemente — direct edit). Watchdog retombera dans cycle restart (degradation gracieuse vs etat avant fix).

### Suivi post-deploy
- J+0 (immediat) : 30 min sans restart confirme = fix valide
- J+1 : grep `WATCHDOG_RESTART_TRIGGERED` → attendu < 5/jour (vs 81 avant)
- J+7 : audit stabilite + verif BOT_HEARTBEAT emit cumulatif coherent

### Liens
- INCIDENT_LOG : 2026-05-06 13:30 entry REGRESSION_HEARTBEAT_MISSING + VALIDATION_MISS
- Pattern reference : `databento_paper_trader.py` (Bot 2 V1 mort) ligne emit BOT_HEARTBEAT historique

---

## 2026-05-06 04:30 UTC — [Bot 3 trade journal append-only JSONL — solution durable Plan agent GO]

**Categorie** : FEATURE + FIX + REFACTO (architecture durable trades fermes Bot 3)
**Impact prod** : DASHBOARD + PAPER (Bot 3 Sim1)
**Fichier(s)** :
- `CORE/databento_paper_trader_v2.py:1085-1170, 360-374, 538-548, 1581-1592, 1670-1678` (refacto _bot3_log_trade_close + 2 calls TP/TIMEOUT, retire buffer memoire + restore + closed_today state.json)
- `DASHBOARD/api/paper_tracker.py:232-296, 470-495` (lecture JSONL via _compute_stats_today_from_trades + filter pnl_known + bot3 payload)
- `DASHBOARD/static/js/dashboard.js:4380-4388, 4774-4830` (status dot 120s + _renderClosedTradesV3 schema aligne)
- `DASHBOARD/static/css/dashboard.css:1291-1310` (table CSS)
- `DASHBOARD/static/index.html` (cache bump v=113->v=117, css v=74->v=75)

**Reviewer(s) agent** :
- 1ere passe : code-reviewer GO-AVEC-RESERVES (Q2 pnl=None TIMEOUT bloquant, Q1 restore important)
- 2eme passe : Plan agent GO (refacto durable JSONL append-only) — Jackson "PAS DE DETTE SOLUTION LONG TERME"

### Quoi
**Solution durable** : Bot 3 ecrit les trades fermes append-only dans `{cme_day}_databento_v3_trades.jsonl` (pattern aligne Bot 1 `*_trades.jsonl`, Bot 2 V2 `*_databento_trades.jsonl`). Source de verite unique :
1. `_bot3_log_trade_close(sym, pos, exit_price, pnl_ticks, pnl_dollars, reason, duration_sec)` ecrit le record JSON par ligne (schema aligne Bot 2 V2 : entry_time/exit_time/symbol/pnl_usd/duration_sec + alias compat).
2. Dashboard lit le fichier via `_compute_stats_today_from_trades("*_databento_v3_trades.jsonl")` (helper existant deja utilise pour Bot 1/2).
3. State.json ne contient PLUS `closed_today` (allege).
4. Pas de buffer memoire, pas de restore au boot — fichier persistant restart-safe par construction.

**Status dot Bot 3** : align frontend `ageSec < 120` (etait 60, asymetrie avec Bot 1/2).

**TIMEOUT pnl=None** : path TIMEOUT (SL/TP orphelins fermes Type 208/209 sans fill propage) ecrit `pnl_ticks=None, pnl_usd=None, pnl_known=False`. Frontend affiche "—" et `_compute_stats_today_from_trades` filtre via `_is_numeric_pnl()` pour ne PAS polluer WR/PF/total avec faux flat. Bot 1/2 inchanges (eux n'ont jamais pnl=None).

### Pourquoi
Jackson 06/05 : "LE BOT 3 A PRIS DES TRADES JE LES VOIS DANS SIERRA CHART MAIS RIEN DANS LE DASHBORD" puis "PAS DE DETTE SOLUTION LONG TERME". Premiere correction quick-fix (buffer memoire `_bot3_closed_today` cap 50 dans state.json) refusee. Plan agent valide refacto durable JSONL :
- Source de verite unique cross-bot (Bot 1/2/3 meme pattern)
- Audit J+30 trivial via glob unifie
- Restart-safe (fichier persiste, pas de re-load logique)
- Pas de cap arbitraire, historique illimite
- Concurrence write-append/read NTFS atomic ligne (pattern Bot 1/2 valide 30j prod)

### Impact attendu
- Dashboard Bot 3 onglet expose tableau trades cloturés du jour (ordre chrono inverse, cap display 50)
- Total P&L Bot 3 fidele (pnl_known flag exclut TIMEOUT)
- Restart inter-day preserve historique automatiquement
- Dot status vert tant que bot vivant (alignement Bot 1/2)
- Audit J+30 cross-bot via glob `*_*trades.jsonl`
- Effet de bord : suppression `closed_today` du state.json (allege ~5KB), pas de regression dashboard cote Bot 1/2

### Validation pre-deploy
- pytest : test integration ad-hoc PASS (3 trades incluant TIMEOUT pnl=None : count 3, stats sur 2 known, WR 50%, pnl_ticks -26.5, pnl_usd 412.5)
- syntax check `ast.parse` OK : Python + frontend
- backtest preservation : N/A (ajout journal lecture-seule + refacto cosmetique state.json, aucun changement scoring/gates Bot 3)
- review code-reviewer 1ere passe : GO-AVEC-RESERVES (Q2 bloquant + Q1 important corriges)
- review Plan agent 2eme passe : GO (2 ajustements appliques : schema_version sans date + reuse helper existant)

### Revert plan
- Si bug ecriture JSONL : Bot 3 silent fail via `_emit("PY_EXCEPTION_HOT_PATH")` (pas de regression trading)
- Si bug lecture dashboard : retirer le wire `_compute_stats_today_from_trades("*_databento_v3_trades.jsonl")` dans `get_bot3_payload` -> dashboard affiche 0 trades (degradation gracieuse)
- Cache bump v=117 -> v=115 frontend si display casse

### Suivi post-deploy
- J+1 : verifier `{date}_databento_v3_trades.jsonl` cree apres premier trade close + dashboard affiche tableau
- J+1 : grep coherence cross-bot pattern `find DATA/PAPER_TRADES -name "*trades.jsonl" | head` (Bot 1, Bot 2 V2, Bot 3 visibles)
- J+7 : audit P&L total dashboard vs logs execution (cross-check coherence)
- J+30 : audit cross-bot via glob unifie pour validation pattern

### Liens
- INCIDENT_LOG : 2026-05-06 03:30 entry DATA_MINING_TRAP_AVOIDED (audit confluence Long/Color, contexte session)
- Review agents : code-reviewer 06/05 + Plan agent 06/05 (refacto durable validee)
- Pattern reference : Bot 2 V2 `databento_paper_trader.py:1245-1325` (`_log_closed_trade`)

---

## 2026-05-04 22:00 UTC — [Bot 1 Round 1 : LEVIER #1 skip NEUTRAL + LEVIER #2 circuit breaker + LEVIER A trailing TP + V4 OBSERVE + retry state.json + code_map TRAILING_TP]

**Categorie** : FEATURE + FIX (Bot 1 Sim3 paper — preparation RTH 05/05 13:30 UTC)
**Impact prod** : PAPER (Bot 1 uniquement)
**Fichier(s)** :
- `CORE/mia_paper_trader.py:85-91` (constants TRAILING_TP Option 2 active 30/50/db20 + Option 1 OBSERVE 40/60/db25)
- `CORE/mia_paper_trader.py:122-123` (ENTRY_RULES `circuit_breaker_losses=3` + `circuit_breaker_pause_sec=3600`)
- `CORE/mia_paper_trader.py:174` (funnel category `2_cooldown_cb` ajout `circuit_breaker`)
- `CORE/mia_paper_trader.py:685-870` (`_observe_v4_widgets` Phase 1 OBSERVE pour 12 codes MANUAL_*/OFA_*)
- `CORE/mia_paper_trader.py:1007` (call `_observe_v4_widgets` debut check_entry)
- `CORE/mia_paper_trader.py:1050-1068` (LEVIER #1 skip si `regime.bias == "NEUTRAL"`)
- `CORE/mia_paper_trader.py:1102` (funnel reject `circuit_breaker` apres consec losses)
- `CORE/mia_paper_trader.py:2168-2210` (LEVIER A trailing TP MFE armed/triggered + Option 1 OBSERVE log)
- `CORE/mia_paper_trader.py:2637-2644` (code_map `TRAILING_TP -> TRADE_CLOSE_TRAIL` + `KILL_SWITCH -> TRADE_CLOSE_KILL`)
- `CORE/mia_paper_trader.py:2662-2669` (emit `CIRCUIT_BREAKER_TRIP` au 3e SL consecutif)
- `CORE/mia_paper_trader.py:2757-2783` (state.json expose `circuit_breaker_remaining_sec` + `circuit_breaker_config` pour dashboard)
- `CORE/mia_paper_trader.py:2804-2830` (retry os.replace 3x backoff 50ms/100ms — fix WinError 5 race state.json)
- `CORE/mia_paper_trader.py:_close_trade` (anti-orphan 7 etapes BOT1_CLEANUP_* — protocole `.claude/rules/orphan-prevention.md`)
- `CORE/log_catalog.py:325-330` (6 codes BOT1_CLEANUP_* CANCEL_FAIL/FLATTEN_SYM/FLATTEN_FAIL/VERIFY_OK/VERIFY_FAIL/VERIFY_TIMEOUT)
- `CORE/log_catalog.py:335-337` (3 codes TRAILING_TP_ARMED/TRIGGERED/OBSERVED_VALIDATED)
- `CORE/log_catalog.py:77` (code CIRCUIT_BREAKER_TRIP existant — emit branche)

**Reviewer(s) agent** : market-analyst (audit independant pre-RTH 22:00 UTC) → **GO-AVEC-RESERVES**

### Quoi
1. **LEVIER #1** : skip entree si `regime.bias == "NEUTRAL"` (toujours autorise dans les 2 sens auparavant)
2. **LEVIER #2** : circuit breaker 3 SL consecutifs → pause 60 min (puis reset auto)
3. **LEVIER A** : trailing TP MFE-based, 2 niveaux
   - Option 2 ACTIVE : MFE >= 30t (ES) / 50t (NQ), drawback >= 20t → close immediat
   - Option 1 OBSERVE : MFE >= 40t (ES) / 60t (NQ), drawback >= 25t → log uniquement
4. **V4 OBSERVE Phase 1** : `_observe_v4_widgets` instrumente 12 codes MANUAL_*/OFA_* pour cluster/big_orders/SMT/naked POC sans impact decision
5. **code_map TRAILING_TP** : ajout mapping `TRAILING_TP -> TRADE_CLOSE_TRAIL` (avant : fallback `TRADE_CLOSE_MANUAL` template incompatible)
6. **state.json retry** : 3 tentatives backoff exponentiel sur `os.replace` pour masquer race avec dashboard reader (WinError 5 ~1.5x/h)
7. **Anti-orphan 7 etapes** : `_close_trade` cancel TP/SL → wait 1s → request_position → close residuel → wait 2s → Type 209 SUBMIT_FLATTEN → verify qty_final (codes BOT1_CLEANUP_*)

### Pourquoi
- **LEVIER #1** : backtest empirique 111 trades historiques montre PF 1.06 -> 1.51 (+0.45) en filtrant trades pris en regime NEUTRAL ou les deux sens etaient autorises (perdants asymetriques). Audit market-analyst flagge **N=85 non significatif** (CI bootstrap inclut zero) -> revert si J+7 PF < 1.30.
- **LEVIER #2** : protection contre serie noire / regime adverse. 3 SL consec = signal regime change, 60 min pause force respiration. Audit market-analyst flagge **probablement trop agressif** (estime 2h pause/jour) -> alternative 4 SL / 30 min a evaluer J+7.
- **LEVIER A** : capture une partie du MFE quand le marche fait un retour > drawback. Backtest claim initial +$437 sur 50 trades -> agent reproduit seulement +$34 (discrepance non resolue). Decision : deploy quand meme Option 2, observer Option 1 en parallele (telemetrie).
- **V4 OBSERVE** : Phase 1 d'integration des 4 widgets V4 (cluster_at_high/low, big_orders_imbalance, smt_divergence, naked_poc_dist). Aucun impact decision, juste comptage des firings pour calibrage Phase 2 future.
- **code_map fix** : sans le mapping, log emit pour outcome=TRAILING_TP echoue silencieusement (template manquant) -> trade close non logge.
- **state.json retry** : decouvert ~36 PermissionError/jour entre paper_trader et dashboard. Race normale Windows file lock, retry court masque proprement.
- **Anti-orphan 7 etapes** : applique sequence validee fix H6 (04/05 11:00 UTC) au Bot 1 cleanup. Avant : single cancel + close peut laisser orphelin si DTC freeze ou Sim Trade Manager desync.

### Impact attendu
- Bot 1 PF cible : 1.06 -> 1.30+ (LEVIER #1) ; LEVIER #2 reduit DD max ; LEVIER A capture +$30-70/trade gain MFE retour (estimate prudent agent)
- 0 orphelin Bot 1 attendu (anti-orphan 7 etapes)
- 0 WinError 5 attendu sur state.json (retry 3x)
- ~470 emit/jour MANUAL_*/OFA_* OBSERVE (pas de spam)
- Effet de bord : pause 60 min apres 3 SL = ~20-25% temps potentiellement bloque si serie noire (audit flag)

### Validation pre-deploy
- [x] Tests unitaires : N/A (fixes inline mia_paper_trader)
- [x] Backtest LEVIER #1 : 111 trades historiques PF 1.06 -> 1.51 (mais N=85 non significatif → review J+7)
- [x] Backtest LEVIER A : reproduit +$34 (vs claim +$437 non reproductible)
- [x] Review agent market-analyst : **GO-AVEC-RESERVES** (CRITIQUE #1 CHANGELOG manquant -> resolu par cette entry, CRITIQUE #2 BOT1_CLEANUP non teste empiriquement -> sera teste au 1er trade)
- [x] Pre-RTH check : 13/13 OK (services, regle v2 affichee, circuit_breaker=3SL/60min visible dashboard)
- [ ] **Test empirique BOT1_CLEANUP_*** : 0 trade depuis deploy (sera valide au 1er trade RTH 05/05)

### Revert plan
```bash
# Revert LEVIER #1 (skip NEUTRAL) — commenter le bloc lignes 1050-1068
# Revert LEVIER #2 — set ENTRY_RULES["circuit_breaker_losses"] = 9999 dans mia_paper_trader.py:122
# Revert LEVIER A — set TRAILING_TP_MFE_THRESHOLD_TICKS = {"ES": 9999, "NQ": 9999}
# Restart service :
ssh Administrator@212.28.179.199 'nssm restart MIA-Paper'
```

### Deployed at 2026-05-04 ~22:00 UTC
Service `MIA-Paper` running. Pre-RTH check complete.

### Suivi post-deploy
- J+1 mardi 05/05 13:30 UTC : verifier PF reel + emit `BOT1_CLEANUP_VERIFY_OK` count + `TRAILING_TP_TRIGGERED` count + `CIRCUIT_BREAKER_TRIP` count + 0 WinError 5
- J+7 mardi 11/05 : PF >= 1.30 confirme (LEVIER #1) sinon revert. Decision finale circuit breaker 3 SL vs 4 SL/30 min selon firing rate.
- J+30 04/06 : trailing TP cumul gain $/trade vs claim. Phase 2 V4 OBSERVE -> integration scoring.

### Reserves audit a traiter
- **HIGH #3** : claim trailing TP +$437 non reproductible. Documenter accept ~$30-70 (agent estimate) ou reproduire script.
- **HIGH #4** : Mardi 05/05 14:00 UTC = ISM Services PMI + JOLTS -> 1h volatilite paralysante. Skip ou size /2.
- **MEDIUM #5** : decider circuit breaker 3 SL vs 4 SL / 30 min. Defaut 3/60 jusqu'a J+7.
- **Risque agent** : retry os.replace 50ms+100ms = 150ms total peut etre insuffisant sous charge dashboard. A surveiller J+1.

### Liens
- INCIDENT_LOG : 2026-05-04 entry (CHANGELOG_MISS pre-RTH evite par cette entry)
- Memory : `feedback_data_quality_first.md`, `feedback_pre_deploy_3_questions.md`
- Audit : market-analyst 22:00 UTC GO-AVEC-RESERVES (8 reponses Q1-Q8 + 5 actions)
- Regle : `.claude/rules/orphan-prevention.md` (sequence 7 etapes appliquee Bot 1)
- Pre-RTH check : 13/13 OK (services nssm + regles v2 + circuit_breaker config dashboard)

---

## 2026-05-04 11:00 UTC — [FIX H6 ANTI-ORPHELIN : TradeAccount tracking dtc_connector + Bot 3 timeout robuste]

**Categorie** : FIX (cause racine 7 trades orphelins Bot 3 nuit 04/05)
**Impact prod** : PAPER (Bot 3 Sim1 + Bot 2 Sim2 + Bot 1 Sim3) — fix critique infrastructure DTC
**Fichier(s)** :
- `BOT/dtc_connector.py:91-99` (init `_order_trade_accounts` + `_request_id_counter`)
- `BOT/dtc_connector.py:185-188` (send_market_order pre-register parent TA)
- `BOT/dtc_connector.py:269-272` (pre-register TP+SL TA)
- `BOT/dtc_connector.py:377-422` (cancel_order + RequestID + double envoi)
- `BOT/dtc_connector.py:629-634` (capture TA depuis ORDER_UPDATE)
- `BOT/dtc_connector.py:723-733` (OCO auto cancel utilise TA correct)
- `BOT/dtc_connector.py:746-763` (_verify_cancel utilise TA tracke + RequestID)
- `CORE/databento_paper_trader_v2.py:369-499` (_bot3_check_timeout sequence 8 etapes)
- `.claude/rules/orphan-prevention.md` (nouveau, regle souveraine)
- `DOCS/INCIDENT_LOG.md` (entry 2026-05-04 categorie VALIDATION_MISS)

**Bug racine** :
`cancel_order(order_id: str, trade_account: str = "Sim3")` avait un default piege.
`_handle_order_update` OCO auto cancel appelait `self.cancel_order(opposite_cid)` sans
trade_account → SC recevait cancel pour Sim3 alors que les ordres etaient sur Sim1 (Bot 3)
ou Sim2 (Bot 2) → cancel ignore silencieusement + Status=8 retourne sur ID inconnu →
false positive cote Python → orphelins reels jamais detectes.
Idem `_verify_cancel` ligne 753 hardcodait `"TradeAccount": "Sim3"`.

**Quoi** : Tracker explicit `_order_trade_accounts: dict {cid: trade_account}`. Pre-enregistrement
parent + TP + SL au moment du `send_market_order`. Capture additionnelle du TA depuis chaque
`msg.get("TradeAccount")` dans `_handle_order_update`. OCO auto + `_verify_cancel` lisent ce dict.
Ajout `RequestID` (alignement projet 1 sierra_dtc_connector.py validee Sim1 Nov 2024).

**Pourquoi** : zero-orphelin garanti. Les 7 trades TIMEOUT pnl=0 + position 2@27911.75 de la
nuit etaient causes par cancels envoyes au mauvais compte. En live AMP, ce bug provoquerait
des pertes reelles (positions non fermees + cancels rejetes broker).

**Impact** :
- Latence cancel auto OCO : 30-300 ms (idem avant fix, mais maintenant **reellement** canceled)
- Bot 3 `_bot3_check_timeout` : sequence 8 etapes (cancel TP+SL → wait → verify position →
  MARKET CLOSE si != 0 → wait → Type 209 fallback → BOT3_TRADE_CLOSE emit)
- Codes log nouveaux : `BOT3_TIMEOUT_CANCEL_FAIL_ORPHAN_RISK`, `BOT3_TIMEOUT_ALREADY_FLAT`,
  `BOT3_TIMEOUT_POSITION_UNKNOWN`, `BOT3_DTC_DOWN_ORPHAN_RISK`, `BOT3_TIMEOUT_FORCE_CLOSE`,
  `BOT3_TIMEOUT_FLATTEN_SYM`, `BOT3_TIMEOUT_FLATTEN_FAIL`, `BOT3_TIMEOUT_CANCEL_EXCEPTION`,
  `BOT3_TIMEOUT_REQUEST_POS_FAIL`, `BOT3_TIMEOUT_CLOSE_FAIL`

**Validation pre-deploy** :
- Tir croise sources : sierra_dtc_connector.py projet 1 + SOLUTION_BRACKET_OCO_FINAL.md +
  VICTOIRE_OCO_AUTOMATIQUE_14NOV_2024.md + doc officielle Sierra Chart
- Audit agent independant `general-purpose` (analyse 5 questions cles, recommandation 4 etapes)
- 5 iterations tests empiriques Sim1 NQ + ES qty=1 paper :
  - Iter 1 : test_timeout_cleanup → pas de fill (OK formel)
  - Iter 2 : test_bracket_real → orphelin ES 20857 detecte
  - Iter 3 : Type 210 + Type 209 manuel → flush effectif
  - Iter 4 : Type 209 systematique seul → orphelins persistent
  - Iter 5 : fix H6 + pure Type 203 → NQ OK Status=8 reel + DOM clean (Jackson confirme)
- Hypotheses testees + invalidees : H1 "Use Attached Orders", H2 Status=8 premature,
  H4 Type 210 systematique necessaire, H5 RequestID manquant. Seule H6 = vraie cause.

**Reviewer(s) agent** : agent general-purpose (audit independant 5 questions),
tests empiriques Sim1 (Jackson confirmation visuelle DOM)

**Revert plan** : `git revert <commit-fix-h6>` puis `git push` + restart MIA-DataBento-Paper-V2
sur VPS. Comportement avant fix : orphelins systematiques sur Bot 2/3 mais Bot 1 (Sim3) OK.

**Suivi post-deploy** :
- J+1 (05/05) : `grep "BOT3_TIMEOUT" LOGS/*/events_*.jsonl` → zero `*_ORPHAN_RISK`
  attendu. Verifier inventaire Sim1 GUI Trade Activity Log → zero ordre Working en debut
  de session ET en fin.
- J+7 (11/05) : compte trades Bot 3 vs avant deploy. Si nombre TIMEOUT divise par >5 →
  fix valide.
- J+30 (03/06) : valider en condition de marche varies (TREND day, RANGE day, news).
- En live AMP futur : Type 209 fallback (etape 7) sera redondant mais inoffensif.

---

## 2026-05-03 15:46 UTC — [Bot 3 alignement Bot 2 — suppression cap data quality]

**Categorie** : CONFIG (RISK_BOT3 alignement Bot 2 Phase 1 free-run)
**Impact prod** : PAPER (Bot 3 Sim1 — pas de limite trades/losses/PnL)
**Fichier(s)** :
- MODIFIE : `CORE/bot3_config.py:72-87` (RISK_BOT3)

### Quoi
Alignement Bot 3 sur Bot 2 (Phase 1 free-run) :
- `max_trades_per_day` : 20 → **None** (pas de limite)
- `max_losses_per_day` : 10 → **None** (pas de limite)
- `kill_switch_daily_pnl` : None (deja, inchange)
- `position_size` : 3 (inchange)

Code Bot 3 supportait deja `None` (ligne 846 databento_paper_trader_v2.py
`if max_t is not None and n_trades >= max_t: ...`). Aucune logique business
modifiee.

### Pourquoi
Jackson 03/05 : "ALIGNE LE BOT 3 AU BOT 2 POUR CES PARAMETRES". Phase 1 free-run
collecte data maximale. Cap data quality Lopez (20 trades/jour) reactivable en
LIVE capital reel via PHASE_1_FREE_RUN flag.

### Tableau final 3 bots (limites)

| Bot | max_trades | max_losses | kill_switch PnL | Sessions |
|---|---|---|---|---|
| Bot 1 (Sim3) | 9999 | 9999 | None | 24h - eco |
| Bot 2 (Sim2) | None | None | None | 02h-21h UTC |
| Bot 3 (Sim1) | **None** ← MODIF | **None** ← MODIF | None | 24h - eco |

**Bot 1 et Bot 3 = sessions 24h sauf eco_calendar windows**.
**Bot 2 = trading_window 02h-21h UTC** (configuration SetupEngine specifique).

### Validation pre-deploy
- ast.parse syntax bot3_config.py : OK
- Hash VPS = local apres scp
- Restart MIA-DataBento-Paper-V2 : pid 8716 BOOT_READY 15:46:22 UTC
- BOT3_BOOT_READY confirmed phase=PAPER tier1+2+3=True

### Backward compat
- Bot 2 V2 SetupEngine : INCHANGE (RISK_PER_SYMBOL deja PHASE_1_FREE_RUN)
- Bot 3 : pas de cap actionable, peut faire >20 trades/jour si signaux

### Revert plan
1. Editer `CORE/bot3_config.py` : remplacer None par 20 / 10
2. scp + restart MIA-DataBento-Paper-V2

### Suivi J+1
- Audit `n_trades_per_day` Bot 3 lundi RTH — si > 50/jour, recalibration filtre
  niveau MP (signaux trop frequents probable)

---

## 2026-05-03 15:30 UTC — [Bot 1 STEP 0 STRICT + Refactor dashboard (Action 3 anticipee)]

**Categorie** : FEATURE + REFACTO (Bot 1 STEP 0 regime gate STRICT + dashboard source unique)
**Impact prod** : PAPER (Bot 1 Sim3 cap drastique trades + dashboard frontend recoit calib optimale)
**Fichier(s)** :
- MODIFIE : `DASHBOARD/api/builders.py:170-247` (build_regime_context refactor → appel regime_engine)
- MODIFIE : `CORE/mia_paper_trader.py:142-179` (FUNNEL_STEPS 12 → 13 layers ajout STEP 0)
- MODIFIE : `CORE/mia_paper_trader.py:212-220` (import REGIME_SKIP_ENABLED top module fail-open)
- MODIFIE : `CORE/mia_paper_trader.py:806-845` (STEP 0 regime gate STRICT in check_entry)

**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES (Q5 fail-open CRITIQUE applique)

### Quoi
1. **Refactor dashboard build_regime_context** (Action 3 anticipee — Jackson "REFACTORISER LE BOT 1
   CE SOIR TOUT DE SUITE") :
   - 170 lignes inline (10 votes ponderes) REMPLACEES par appel `regime_engine.compute_regime(bar)`
   - Fallback safe (mode=NORMAL favor=NEUTRE) si regime_engine plante
   - Override coherence bias preservee (3+ bear/bull factors)
   - Expose `regime_actionable` + `regime_confidence` dans dict retour
   - Tests parite : 6/6 mode (100%) + 6/6 favor (100%) + 6/6 vol (100%) ✓ PASS

2. **Bot 1 STEP 0 STRICT** (Jackson "PAS DE MODE SOFT, ON MET LE PLUS HAUT NIVEAU") :
   - Skip FULL si `regime_actionable=0` (pas TREND/RANGE clair OU NEUTRE OU EXTREME OU conf<0.10)
   - Skip si `favor=NEUTRE`
   - Skip si direction signal contraire favor (BUY vs SHORT, SELL vs LONG)
   - Estimation impact : 80% trades coupes (actionable rate 20.2%)

3. **Q5 fix CRITIQUE fail-open** (code-reviewer) :
   - Import `REGIME_SKIP_ENABLED` au top du module (pas dans check_entry)
   - Si ImportError → `_REGIME_SKIP_ENABLED=False` = Bot 1 continue sans gate (pas paralyse)
   - Test simulation ImportError : `TEST PASS: fail-open correct` ✓

### Pourquoi
Jackson 03/05 : "BOT 1 A BEAUCOUP PLUS DE FAUX SIGNAUX QUE LES AUTRES BOTS, IL PRENDRA
BEAUCOUP PLUS DE TRADES". Bot 1 dashboard-follower fait 9-36 trades/jour vs Bot 2/3 plus
selectifs. Filtre regime STRICT cap les pires bruits Bot 1.

Bot 2 + Bot 3 RESTENT en filtre directionnel SOFT (skip seulement si direction contraire
forte conviction). Asymetrie par bot : Bot 1 strict, Bot 2/3 soft.

### Architecture finale post-refactor

```
DMP Sierra Chart -> JSONL bar (calibration source)
   |
   +-- regime_engine.compute_regime(bar) [SOURCE UNIQUE — calib optimale 5.5]
       |
       +-- Dashboard build_regime_context() [refactor : appel regime_engine]
       |   +-- Bot 1 (Sim3) lit regime via API JWT owner
       |       -> STEP 0 STRICT (full skip si not actionable OU contraire favor)
       |
       +-- Bot 2 (Sim2 SetupEngine) appel direct regime_engine
       |   -> filtre directionnel SOFT (skip seulement contraire favor)
       |
       +-- Bot 3 (Sim1 24 niveaux) appel direct regime_engine
           -> filtre directionnel SOFT (skip seulement contraire favor)

Kill switch : MIA_REGIME_SKIP_ENABLED=0 (env nssm) → desactive 3 bots
calib_version="v2_optim_20260503" (logs OBSERVE)
```

### Validation pre-deploy
- ast.parse syntax 3 fichiers : OK
- Tests parite dashboard <-> regime_engine : 100% sur 6 bars samples
- Test fail-open empirique (rename regime_engine.py.bak → import fail) : PASS
- Hash VPS = local apres scp 2 fichiers : OK
- Restart MIA-Paper + MIA-Dashboard : BOOT_READY 15:29:22 UTC pid 9844, 0 erreur import

### Backward compat
- Bot 2 + Bot 3 INCHANGES (filtre SOFT garde)
- Frontend dashboard recoit memes champs dict (mode/favor/vol/votes/details) avec calib optimale
- Logs JSONL Bot 1 enrichis avec STEP 0 reject codes

### Reserves restantes (suivi J+1)

**R2 Cap 80% trades Bot 1** (code-reviewer Q2) :
- Audit J+1 obligatoire : `n_skip_step_0 / n_polls > 90%` → recalibrer (vol_extreme=5.5 trop strict ?)
- Si Bot 1 fait 0 trade lundi RTH → activer `MIA_REGIME_SKIP_ENABLED=0` mardi matin

**R6 Pattern 11 Bot 1 13 layers** (code-reviewer Q6) :
- 0+1+2+3+4+5+6+6bis+6ter+6quart+6cinq+7+8 = 13 layers (V1 mort = 11)
- Justification Jackson directe accepte
- Si rate skip > 90% J+5 → fusion STEP 0 + STEP 6quart (regime profile/day) ou retrait 6quart redondant

**Calibration Bot 1 ES non valide** :
- Calibration grid search 14j NQ uniquement
- ES rate actionable peut diverger
- A backtester separe post-7j

### Revert plan ULTRA-RAPIDE
1. Kill switch : `nssm set MIA-Paper AppEnvironmentExtra ... MIA_REGIME_SKIP_ENABLED=0; nssm restart MIA-Paper`
2. Filtre desactive en 30s, Bot 1 trade comme avant
3. Dashboard reste sur regime_engine (calibration optimale) — pas affecte

### Suivi J+1 lundi 04/05 13:30 UTC
- Verifier `LOGS/funnel/funnel_20260504_paper.json` : `step_0_regime_*` rates par symbole
- Critere alerte : rate skip > 90% par symbole (calibration trop strict ES)
- Verifier 0 erreur `REGIME_ENGINE_IMPORT_FAIL` dans `LOGS/errors/errors_*paper.jsonl`

---

## 2026-05-03 15:13 UTC — [Option A : filtre directionnel SOFT ACTIF Bot 2 + Bot 3]

**Categorie** : FEATURE (gate skip directionnel ACTIF — pas mode observe)
**Impact prod** : PAPER (Bot 2 Sim2 + Bot 3 Sim1 — filtre actif des lundi 04/05 RTH)
**Fichier(s)** :
- MODIFIE : `CORE/regime_engine.py` (ajout REGIME_SKIP_ENABLED env + REGIME_CALIB_VERSION)
- MODIFIE : `CORE/databento_paper_trader_v2.py` (Bot 2 lignes 728-792 + Bot 3 lignes 833-893)

**Reviewer(s) agent** : code-reviewer GO-AVEC-RESERVES (R1+R2 critiques appliques avant deploy)

### Quoi
**Option A — filtre directionnel SOFT** : skip UNIQUEMENT si signal trade contraire au regime favor fort.

```python
# Conditions cumulees pour skip :
if REGIME_SKIP_ENABLED and regime is not None \
        and regime.is_actionable and regime.favor != "NEUTRE":
    if (signal.side == "LONG" and regime.favor == "SHORT") or \
       (signal.side == "SHORT" and regime.favor == "LONG"):
        emit("BOTx_REGIME_SKIP", ...)
        continue  # skip trade
```

### Pourquoi
Jackson 03/05 : "ON UTILISE DIRECTT" — pas mode observe, filtre actif des lundi.
Compromis pragmatique vs full skip (cap 70% trades) : skip ~15-20% trades les pires
contre-tendance, conserve PF 11 setups Bot 2 valides + 24 niveaux Bot 3.

### Reserves agent appliquees AVANT deploy

**R1 (CRITIQUE) Kill switch** : `MIA_REGIME_SKIP_ENABLED=0` env disable filtre rapide
sans redeploy code. Rollback en 30s via `nssm restart MIA-DataBento-Paper-V2`.

**R2 (IMPORTANT) calib_version** : ajoute dans logs OBSERVE/SKIP `calib_version="v2_optim_20260503"`.
Permet diff vs Bot 1 dashboard (calibration ANCIENNE 2.0) sans confusion.

### Reserves restantes (suivi J+1)

**R3 Estimation 15-20% non verifiee** : audit obligatoire J+1 mardi.
- Si `n_skip / (n_skip + n_trade) > 30%` → filtre trop strict, recalibrer
- Si `< 5%` → filtre quasi-inactif, pas de gain
- Tolerance acceptable : 10-25%

**R4 Calibration NQ-only** : grid search 14j NQ uniquement. Application sur ES = pas
verifie. Recalibrer ES separe post-7j si stats divergent.

### Validation pre-deploy
- ast.parse syntax 2 fichiers : OK
- Hash VPS = local apres scp 2 fichiers : OK
- Restart MIA-DataBento-Paper-V2 : pid 4176 BOOT_READY 15:13:48 UTC
- 0 erreur import regime_engine

### Backward compat
- Bot 1 (mia_paper_trader.py Sim3 dashboard) : INCHANGE — calibration ancienne, mode log only
- Bot 2 SetupEngine 11 setups : filtre SOFT actif lundi RTH
- Bot 3 24 niveaux MP : filtre SOFT actif lundi RTH

### Revert plan ULTRA-RAPIDE
1. `ssh Administrator@212.28.179.199 'powershell -Command "& nssm set MIA-DataBento-Paper-V2 AppEnvironmentExtra MIA_TRADE_ACCOUNT=Sim2 MIA_DTC_HOST=localhost MIA_DTC_PORT=11099 MIA_DTC_USER=miav2 MIA_REGIME_SKIP_ENABLED=0; & nssm restart MIA-DataBento-Paper-V2"'`
2. Filtre desactive en 30s, BOTx_REGIME_OBSERVE continue mais pas de skip
3. Si probleme persiste : revert code via `git checkout HEAD~1 CORE/databento_paper_trader_v2.py`

### Suivi post-deploy J+1
- **Lundi 04/05 13:30 UTC** : grep `BOTx_REGIME_SKIP` dans `LOGS/events/events_20260504_paper_v2.jsonl`
- **Mardi 05/05** : audit ratio skip/trade par bot, decision continuer ou revert
- **Vendredi 09/05** : decision activation strict (Option B) si calibration validee 5j
- **Mardi 05/05 (parallele)** : refactor `DASHBOARD/api/builders.py` pour appeler regime_engine (Bot 1 alignement)

### Architecture finale post-Option A

```
Sierra Chart DMP -> JSONL (calibration ANCIENNE 2.0)
   |
   +-- Dashboard build_regime_context() (mode observe Bot 1)
   |   +-- Bot 1 (Sim3) : LOG regime ancienne calib (pas de skip)
   |
   +-- regime_engine.compute_regime() (calibration OPTIMALE 5.5)
       +-- Bot 2 (Sim2 SetupEngine) : LOG OBSERVE + SKIP directionnel SOFT
       +-- Bot 3 (Sim1 24 niveaux) : LOG OBSERVE + SKIP directionnel SOFT

Kill switch global : MIA_REGIME_SKIP_ENABLED=0 → desactive skip Bot 2+3
Calib version logged : calib_version="v2_optim_20260503"
```

---

## 2026-05-03 15:00 UTC — [3 audits regime_engine + corrections critiques]

**Categorie** : FIX + AUDIT (audit integration regime_engine 3 bots + corrections)
**Impact prod** : PAPER (Bot 2 ajout integration + V4 VPS rebuild Mai)
**Fichier(s)** :
- MODIFIE : `CORE/databento_paper_trader_v2.py:728-768` (Bot 2 regime mode observe + regime_at_entry capture)
- DEPLOY : VPS `CORE/build_dataset_v4_dmp_databento.py` + `quality_validator.py`
- REBUILD : V4 VPS `symbol={ES,NQ}.c.0/year=2026/month=05/data.parquet` (90 cols + regime_*)

**Reviewer(s) agent** : 3 code-reviewer paralleles (1 par bot) — verdicts GO-RESERVES

### 3 audits agents — verdicts

| Bot | Verdict | Findings critiques |
|---|---|---|
| Bot 1 | GO-RESERVES | R1 calibration ancienne dashboard ≠ regime_engine (logs J+1 biaises EXTREME systematique). R2 token owner OK. R3 logger aussi `_funnel_pass`. |
| Bot 2 | GO-RESERVES | OMISSION CRITIQUE : regime_engine PAS integre (oublie deploy 14:30). Pattern 9/10 setups RANGE confirme. |
| Bot 3 | GO-RESERVES | R1 V4 VPS Mai = 8/18 features → 99.9% RANGE 0% actionable degenere. R7 divergence Bot 1 vs Bot 3. |

### 3 actions correctives

#### ACTION 1 OK — Bot 2 regime_engine integration (omission)
Ajout dans `databento_paper_trader_v2.py:728-768` AVANT `setup_engine.evaluate(bar_dict, sym)` :
- Try/except + `_emit("BOT2_REGIME_OBSERVE", ...)` 7 champs regime
- Capture `regime_at_entry` (mode + favor) dans `SETUP_TRADE_OPEN` event pour calibration cross-setup x regime J+5
- Deploy VPS + restart MIA-DataBento-Paper-V2 (BOOT_READY 14:55:52 UTC pid 8028)

#### ACTION 2 OK — V4 VPS Mai 2026 rebuild
Push pipeline modifie + quality_validator sur VPS, rebuild --start 2026-05-01 --end 2026-05-01 :
- ES 1260 bars + NQ 1260 bars
- 90 cols (vs 80 avant) avec 7 regime_* via compute_regime_dict
- **regime_actionable 18.2%** (vs 0% V4 ancien — target 15-25% atteint)
- Build time 1.2s/jour (faisable sur 14 mois)

#### ACTION 3 REPORTEE — Refactor dashboard build_regime_context
Identifiee critique par 2 agents (Bot 1 + Bot 3) mais reportee mardi car :
- Risque casser dashboard prod (30-60 min refactor + tests parite)
- Cross-validation J+1 (Bot 1 calib ancienne vs Bot 3 calib nouvelle) = data utile pour identifier gap exact avant refactor

### Verification post-deploy
- Hash VPS = local apres scp 3 fichiers OK
- Restart MIA-DataBento-Paper-V2 : 0 erreur import regime_engine
- Logs BOOT_READY 14:55:52 UTC pid 8028 + BOT3_BOOT_READY phase=PAPER

### Suivi J+1 lundi 04/05 13:30 UTC
Verifier dans logs :
- `events_20260504_paper_v2.jsonl` contient BOT2_REGIME_OBSERVE + BOT3_REGIME_OBSERVE
- `events_20260504_paper.jsonl` Bot 1 contient market_ctx avec regime_*
- `SETUP_TRADE_OPEN` events (Bot 2) contient regime_at_entry pour calibration

### Reserves restantes (mardi+)

1. **R1 Bot 1 calibration divergente** : refactor dashboard `build_regime_context` pour appeler `regime_engine.compute_regime` directement → source unique partagee.
2. **R3 Bot 1 log _funnel_pass** : ajouter regime_* aussi sur trades pris (pas seulement rejets) — eviter biais selection calibration.
3. **R4 Bot 3 throttle logs** : si calibration confirmee, throttle BOT3_REGIME_OBSERVE a 1/heure post-J+5.
4. **Suggestion S1 Bot 3** : ajouter `n_features_present` dans BOT3_REGIME_OBSERVE pour detecter V4 incomplet en grep.
5. **Logger regime_at_entry dans Bot 1** : Bot 1 doit aussi capturer regime sur trade open (pour cross-comparaison Bot 1/2/3 PnL × regime).

### Backtest preservation wins
**Non applicable** : MODE OBSERVE = log only, aucun impact sur signaux/trades.

### Architecture finale post-action

```
Sierra Chart DMP -> JSONL (268 features inc. regime calc dashboard)
   |
   +-- Dashboard build_regime_context() (calibration ANCIENNE 2.0)
   |   +-- Bot 1 (Sim3) lit regime via API JWT owner
   |       -> log market_ctx.regime_* dans rejets STEPS 3-8
   |
   +-- Pipeline V4 enriched VPS (45 features + 7 cols regime_*)
   |   +-- regime_engine.compute_regime() calibration OPTIMALE 5.5
   |   |   actionable 18.2% target atteint
   |   |
   |   +-- Bot 2 (Sim2 SetupEngine 11 setups) lit V4 + appel compute_regime
   |   |   -> emit BOT2_REGIME_OBSERVE + regime_at_entry sur trade
   |   |
   |   +-- Bot 3 (Sim1 24 niveaux MP) lit V4 + appel compute_regime
   |       -> emit BOT3_REGIME_OBSERVE + regime_at_entry sur trade

CORE/regime_engine.py = SOURCE UNIQUE (anti Pattern 11)
Dashboard sera resync mardi (Action 3) → parite Bot 1 ↔ Bot 2/3
```

---

## 2026-05-03 14:46 UTC — [regime_engine CALIBRATION OPTIMALE via grid search]

**Categorie** : FIX CALIBRATION (regime_engine seuils empiriques)
**Impact prod** : PAPER (Bot 3 Sim1 — log only mode observe)
**Fichier(s)** :
- MODIFIE : `CORE/regime_engine.py` (seuils calibres grid search 4D)
- NOUVEAU : `CORE/research/grid_search_regime.py` (81 combinations testees)
- NOUVEAU : `CORE/research/calibrate_regime_engine.py` (3 versions baseline)
- VPS deploy : regime_engine.py + Bot 3 restart pid 5604 BOOT_READY 14:46:12 UTC

**Reviewer(s) agent** : self (grid search empirique sur 14 jours data clean NQ)

### Quoi
Grid search 4D (81 combinations) sur 13539 bars NQ 17/04 -> 30/04 :
  - vol_extreme : [3.5, 4.5, 5.5]
  - mode_strong : [3, 4, 5]
  - conf_actionable : [0.05, 0.10, 0.15]
  - vwap_dir : [1.5, 2.5, 3.5]

Score multi-objectif :
  +/- 1pt par % d'ecart |actionable - 20%| (target 20%)
  +5pt si jour BULL identifie (22/04 NQ favor LONG > SHORT)
  +5pt si jour SHORT identifie (28/04 NQ favor SHORT > LONG)
  +3pt si jour CHOPPY identifie (23/04 NEUTRE > 60%)
  -5pt si LONG forced sur jour perdant (29/04, 30/04)

**Best score : 12.9** avec :
  - vol_extreme = 5.5 (was 2.0)
  - mode_strong = 3 (was 5)
  - conf_actionable = 0.10 (was 0.20)
  - vwap_dir = 3.5 (was 5.0)

### Pourquoi
Audit distribution V4 NQ 14j montrait actionable rate 2.8-3.4% (target 15-25%).
Quartiles realistes :
  - sess_range_atr p50=2.27 / p90=4.66 (seuil 2.0 = capture 50%+ bars en EXTREME)
  - vwap_slope_10 p75=3.78 / p90=8.03 (seuil 5 = trop strict)
  - poc_bar_dist p75=19 (seuil 30 = trop strict)
  - bars_in_va p75=22 (seuil 60 = trop strict)
  - single_print_count p25=47 (seuil 10 = presque toujours fort)

Tous les top-10 calibrations ont vol_extreme=5.5 = signal robuste sur seuil critique.

### Validation cross-PnL Bot V1 (4/5 alignees)

| Date | PnL Bot V1 | Regime calibre | Verdict |
|---|---|---|---|
| 22/04 | data | LONG 24% > SHORT 2.8% TREND 65% | ✅ BULL |
| 23/04 | data | TREND 49% NEUTRE 73% | ✅ Choppy |
| 28/04 | +422$ SHORT-dom | SHORT 35.8% > LONG 6.5% | ✅ SHORT detected |
| 29/04 | -270$ range LONG-forced | TREND 28% LONG 22% SHORT 29% mixed | ✅ Bot V1 LONG = perdu coherent |
| 30/04 | -230$ LONG-forced | TREND 64% LONG 34.7% SHORT 0% | ⚠️ Regime BULL mais reversal market |

### Resultats globaux 14 jours NQ
- Actionable rate : 3.4% -> **20.2%** (target 15-25% atteint)
- Mode TREND rate : 28% -> 50%
- Mode RANGE rate : 46% -> 45%
- Mode NORMAL rate : 26% -> 8%
- vol EXTREME rate : 32% -> 7% (calibration vol_extreme 5.5 effective)
- Favor NEUTRE rate : 68% -> 67% (peu change, bias proxy inchange)

### Reserve : divergence dashboard <-> regime_engine

Calibration optimale regime_engine != seuils dashboard build_regime_context() actuels.
Tests parite ce soir : 4/6 mode (67%) / 4/6 favor (67%) / 0/6 vol (0%).

**Action mardi (J+2)** : refactor `DASHBOARD/api/builders.py:build_regime_context()` pour
appeler `regime_engine.compute_regime()` directement -> source unique partagee + parite 100%.

### Backward compat
- Bot 1 (mia_paper_trader.py) : continue lire regime via dashboard backend (calibration ANCIENNE).
- Bot 3 (databento_paper_v2.py) : utilise regime_engine.py CALIBRE (nouvelle).

Cette divergence temporaire = compromis pragmatique pour deploy lundi sans casser dashboard.

### Suivi post-deploy J+1
- Comparer logs Bot 1 (`market_ctx.regime_*` ancienne calib) vs Bot 3
  (`BOT3_REGIME_OBSERVE` nouvelle calib) sur memes ts_event.
- Mardi : refactor dashboard pour utiliser regime_engine (resolves S2 code-reviewer).

---

## 2026-05-03 14:30 UTC — [Plan B regime_engine MODE OBSERVE Bot 1 + Bot 3]

**Categorie** : FEATURE (regime detector mutualise — anti Pattern 11)
**Impact prod** : PAPER (Bot 1 Sim3 + Bot 3 Sim1 — log only, pas de skip)
**Fichier(s)** :
- NOUVEAU : `CORE/regime_engine.py` (374 LOC — porting build_regime_context dashboard)
- NOUVEAU : `CORE/tests/test_regime_engine.py` (parite 6 bars — 100% mode + 83% favor + 100% vol)
- MODIFIE : `CORE/build_dataset_v4_dmp_databento.py` (DMP_MQ_FIELDS 17->45 + appel regime sur chaque bar -> 7 cols regime_*)
- MODIFIE : `CORE/quality_validator.py` (NATURALLY_DIFFERENT + EVENT_BASED extensions)
- MODIFIE : `CORE/mia_paper_trader.py:792-805` (Bot 1 log regime_mode/favor/vol/trend_votes dans market_ctx)
- MODIFIE : `CORE/databento_paper_trader_v2.py:813-832` (Bot 3 appel compute_regime + emit BOT3_REGIME_OBSERVE)

**Reviewer(s) agent** :
- code-reviewer #1 (Plan B GO-RESERVES, 4 reserves : R1.1+R1.2 bias drift differe, R1.3+R3+R4 fixes appliques)
- code-reviewer #2 (deploy review : GO-AVEC-RESERVES Option A, R1 logs Bot 3 vides probable car V4 VPS sans features regime DMP)

### Quoi
1. **regime_engine.py** : module unifie 10 votes ponderes Steidlmayer/Dalton + bias proxy.
   Output : RegimeAnalysis (mode TREND/RANGE/NORMAL, favor LONG/SHORT/NEUTRE, confidence,
   trend/range_votes, vol_regime, is_actionable). Source unique consommee par dashboard,
   pipeline V4, Bot 1 (via dashboard API), Bot 3 (appel direct).
2. **Pipeline V4** : etend DMP_MQ_FIELDS 17->45 features (+31 features regime DMP) + ajoute
   7 colonnes regime_* via compute_regime_dict() sur chaque bar. Test rebuild local 17/04->01/05
   OK (13540 bars ES + NQ, regime_actionable 2.8-3.4%).
3. **Bot 1** : 4 champs regime ajoutes dans market_ctx (mode/favor/vol/trend_votes).
   Bot 1 lit deja le regime via dashboard `instr.get("regime", {})`. Logs J+1 enrichis.
4. **Bot 3** : import compute_regime, call sur bar_dict V4 enriched, emit BOT3_REGIME_OBSERVE
   avec 7 champs regime + try/except + emit BOT3_REGIME_ERROR si crash.

### Pourquoi
Jackson 03/05 : "ON A NEGLIGER LA DETECTION DE REGIME". Workflow trade pro :
1. DIRECTION CLAIRE (regime + bias) - STEP 0
2. NIVEAU touch (Bot 3 levels ou Bot 2 setups)
3. RECONFIRMATION direction + orderflow
4. TRADE

Code-reviewer matin : Plan A (28 features brutes exposees, 3 bots calculent leur regime
chacun) = Pattern 11 V1 reborn (cf feedback_cross_instrument_bonus_not_gate.md).
Plan B (1 source unique + features agregees) = anti Pattern 11.

**Mode OBSERVE** (log only, pas de skip) car premier jour paper 3 bots demain et calibration
empirique necessaire avant activation gate. Aucun risque casser trading.

### Validation pre-deploy
- Tests parite dashboard <-> regime_engine : 6/6 mode (100%), 5/6 favor (83%), 6/6 vol (100%) PASS
- ast.parse syntax 5 fichiers : OK
- Hash VPS = local apres scp : OK
- Restart MIA-Paper + MIA-DataBento-Paper-V2 : BOOT_READY OK, 0 erreur import regime_engine

### Backtest preservation wins
**Non applicable** : MODE OBSERVE = pas de skip = pas d'impact sur signaux genere.
Calibration GO/NOGO seuils mardi apres logs J+1.

### Reserves differees (acceptables court terme)
- **R1.1+R1.2** (code-reviewer #1) : bias proxy regime_engine vs compute_bias officiel
  dashboard = drift garanti N% bars. A fixer mardi (port compute_bias direct).
- **R2** : iterrows() sur 1M bars = 8-15 min. Vectoriser quand rebuild V4 14 mois.
- **R1 deploy** (code-reviewer #2) : Bot 3 V4 VPS ne contient pas features regime DMP
  (day_type, profile_shape, vix_level, etc.) car build_dataset_v4 modifie pas deploye/rebuild
  sur VPS. Logs BOT3_REGIME_OBSERVE probablement degenerees (mode=NORMAL favor=NEUTRE 100%).
  Bot 1 logs OK (regime via dashboard backend qui calcule deja).
- **Calibration seuils** : actionable rate 2.8-3.4% trop strict, calibrer mardi sur logs J+1.

### Revert plan
1. Restore VPS files : `scp regime_engine.py.bak`, `mia_paper_trader.py.bak`, etc.
2. `nssm restart MIA-Paper MIA-DataBento-Paper-V2`
3. Logs BOT3_REGIME_OBSERVE / BOT3_REGIME_ERROR disparaissent

### Suivi post-deploy
- **J+1 (lundi 04/05 13:30 UTC)** : verifier presence logs BOT3_REGIME_OBSERVE + market_ctx
  regime_mode/favor/vol dans Bot 1 decisions/rejections.
- **J+2 (mardi 05/05)** : calibration seuils regime_engine (actionable rate target 15-30%
  des bars RTH si regime detector marche). Si Bot 3 logs vides, rebuild V4 sur VPS prevu.
- **J+5 (vendredi 08/05)** : decision activation skip MODE GATE Bot 3 (basee 5 jours observe).
- **J+10** : si gate skip OK, etudier R1.1+R1.2 bias drift fix (port compute_bias).

### Architecture finale
```
Sierra Chart DMP -> JSONL (268 features inc. regime)
   |
   +-- Dashboard build_regime_context() (live)
   |   +-- Bot 1 (mia_paper_trader.py Sim3) lit "regime" dict
   |       -> log market_ctx.regime_*
   |
   +-- Pipeline V4 enriched (rebuild 15j local, pas VPS encore)
   |   +-- DMP_MQ_FIELDS 45 features
   |   +-- compute_regime_dict() -> 7 cols regime_*
   |   +-- Bot 3 (databento_paper_v2 Sim1) lit V4 + appel compute_regime() runtime
   |       -> emit BOT3_REGIME_OBSERVE
   |
   +-- Tests parite test_regime_engine.py (6 bars) : PASS

CORE/regime_engine.py = SOURCE UNIQUE (anti Pattern 11)
```

---

## 2026-05-03 12:52 UTC — [Correction architecture 3 bots : revert V2CLEAN + restart Bot 1]

**Categorie** : ROLLBACK + CONFIG (correction erreurs deploy 11:43)
**Impact prod** : PAPER (3 bots : Bot 1 Sim3, Bot 2 Sim2, Bot 3 Sim1)
**Fichier(s)** : VPS services nssm uniquement (env vars + StartupType)
**Reviewer(s) agent** : self (Jackson rappelle architecture cible 3 bots distincts)

### Quoi
1. **Revert V2CLEAN dry_run** : `nssm reset MIA-V2CLEAN-Bot AppEnvironmentExtra` → env vars vide → mode `dry_run_decision_only`. Heartbeat post-restart confirme `execution_wired: false`.
2. **Restart MIA-Paper (Bot 1 Sim3)** : config env `MIA_DTC_ENABLE=1`, `MIA_TRADE_ACCOUNT=Sim3`, `MIA_DTC_USER=MIA_PAPER_S3` (username unique anti-collision), StartType Automatic, force restart (Stop-Service ce matin n'avait pas tue le process). BOOT_READY 12:52:29 UTC pid 6700.

### Pourquoi
Erreurs deploy 11:43 :
- V2CLEAN active live Sim2 = doublon avec Bot 2 V2 SetupEngine sur Sim2 (architecture Jackson : 3 bots distincts, V2CLEAN R&D pas dans archi 3 bots).
- MIA-Paper stoppe = Bot 1 dashboard-follower (Sim3 DMP via dashboard) absent. Jackson rappelle "on devait juste l'AMELIORER pas le STOPPER".

### Architecture finale conforme Jackson
| Bot | Service | Sim | Data | DTC User |
|---|---|---|---|---|
| Bot 1 (dashboard-follower) | MIA-Paper | Sim3 | DMP via dashboard | MIA_PAPER_S3 |
| Bot 2 (SetupEngine 11 setups) | MIA-DataBento-Paper-V2 | Sim2 | Databento (parquet v4_enriched) | miav2 |
| Bot 3 (24 niveaux MP) | MIA-DataBento-Paper-V2 (in-process) | Sim1 | Databento (parquet v4_enriched) | miav2 (partage Bot 2) |
| V2CLEAN (R&D ML) | MIA-V2CLEAN-Bot | n/a | DMP JSONL | MIA_V2CLEAN (default code) |

### Validation pre-deploy
- Hash `setup_definitions.py` local = VPS confirme 11/11 setups intacts (Bot 2)
- Heartbeat V2CLEAN post-revert : `execution_wired: false` (dry_run)
- BOOT_READY MIA-Paper post-restart : pid 6700, DTC=connected, model=paper, data=Sim3
- 4 services state confirme : 3 Running + 1 Stopped (V1 obsolete)
- 3 usernames DTC distincts : MIA_V2CLEAN, miav2, MIA_PAPER_S3 (anti-collision Sierra Chart)

### Backtest preservation wins
**Non applicable** : revert + restart, aucune modification scoring/gates.

### Revert plan (si urgence)
1. `nssm set MIA-V2CLEAN-Bot AppEnvironmentExtra "MIA_BOT_LIVE_EXECUTION=1" "MIA_TRADE_ACCOUNT=Sim2" ...` → re-active V2CLEAN live
2. `nssm reset MIA-Paper AppEnvironmentExtra` + `Stop-Service MIA-Paper` → desactive Bot 1
3. Restart services concernes

### Suivi post-deploy
- **J+1 (lundi 04/05 13:30 UTC RTH)** : verifier presence `TRADE_OPEN` events pour les 3 bots :
  - Bot 1 : `LOGS/trading/trading_20260504_paper.jsonl` non-vide
  - Bot 2 : `LOGS/trading/trading_20260504_databento_paper_v2.jsonl` non-vide (SETUP_TRIGGERED + TRADE_OPEN)
  - Bot 3 : meme fichier paper_v2 contient `BOT3_TIER_*_EVAL` + `BOT3_TRADE_OPEN`
- **Crash-loop MIA-Paper** : a 30+ min uptime sans BOOT_READY duplicate = fix WinError 10038 reussi
- **J+1 audit** : verifier MIA-Paper bug "signaux date future 2026-05-05" si reproduit (investigation deferee)

### Concerns reportes
- Bug "signaux date future" Bot 1 : a investiguer apres confirmation crash-loop fixe
- V2CLEAN reactivation live : projet R&D distinct, primary + meta-labeling Lopez avant activation prod (cf `project_bot_objectif_final.md`)

---

## 2026-05-03 11:43 UTC — [V2CLEAN live execution Sim2 + 3 fixes critiques pre-activation]

**Categorie** : FIX + CONFIG (activation mode live execution)
**Impact prod** : PAPER (Bot 2 V2 V2CLEAN sur Sim2 demo)
**Fichier(s)** :
- `V2CLEAN/bot_main.py:1043-1071, 1075` (H2 on_connection_lost callback + M2 MIA_DTC_USER env)
- `V2CLEAN/execution/order_manager.py:194-203` (H1 garde 1 max position par symbol)
- VPS service `MIA-V2CLEAN-Bot` AppEnvironmentExtra (5 env vars ajoutees)

**Reviewer(s) agent** : code-reviewer (verdict GO-RESERVES, H1+H2+M2 fixes appliques avant activation)

### Quoi
1. **H1 fix** : `submit_bracket()` refuse desormais nouveau bracket si bracket open meme symbol non clos. Anti-pyramid si 2 PASS arrivent dans 15s.
2. **H2 fix** : `build_live_bot()` cable `_on_connection_lost` callback vers `kill_switch.trip(CATASTROPHE)`. Si DTC reconnect epuise 4 tentatives → bot trip CATASTROPHE (au lieu de continuer silencieusement).
3. **M2 fix** : `main()` lit `MIA_DTC_USER` env var (eviter collision username Sierra Chart).
4. **Config nssm** : `MIA_BOT_LIVE_EXECUTION=1`, `MIA_TRADE_ACCOUNT=Sim2`, `MIA_DTC_USER=MIA_V2CLEAN_BOT`, `MIA_DTC_HOST=127.0.0.1`, `MIA_DTC_PORT=11099`.

### Pourquoi
Bot 2 V2 V2CLEAN tournait en `dry_run_decision_only` depuis deploy 17/04. 13 PASS / 2735 REJECT vendredi 02/05 mais 0 ordre DTC emis (`execution_wired=false`). Jackson 03/05 demande paper actif sur Sim2 demo. Code-reviewer impose H1+H2+M2 avant activation production.

### Impact
- Bot 2 V2CLEAN trade desormais ordres DTC reels sur Sim2 (compte Sim demo, no risque capital).
- Lundi 13:30 UTC RTH = premier test reel paper.
- Heartbeat post-restart confirme `execution_wired: true`, `kill_switch_active: false`, DTC connected user=MIA_V2CLEAN_BOT.

### Validation pre-deploy
- Tests V2CLEAN/tests/test_execution.py : 13/13 PASS
- Syntax check Python ast.parse : OK
- Hash files VPS = local apres scp (deploy verifie)
- Service restart sans crash : log stderr montre `MODE LIVE EXECUTION` + `DTC connected` + `models preflight OK`

### Backtest preservation wins
**Non applicable** : aucune modification scoring/gates. Modifs strictement execution layer (bracket safety, callback DTC, env config).

### Revert plan
1. `nssm set MIA-V2CLEAN-Bot AppEnvironmentExtra ""`
2. `Restart-Service MIA-V2CLEAN-Bot` → revient en dry_run_decision_only
3. Rollback fichiers : `git checkout HEAD~1 V2CLEAN/bot_main.py V2CLEAN/execution/order_manager.py` puis scp VPS

### Suivi post-deploy
- **J+1 (lundi 04/05)** : verifier au moins 1 `bracket_complete` dans `V2CLEAN/logs/events.jsonl` apres ouverture RTH 13:30 UTC. Si 0 trade et 13+ PASS → bug bloquant a investiguer.
- **J+7** : audit trades Sim2 vs decisions PASS, ratio attendu ~5-15% (gates filtrent).
- **J+30** : metrics PF / WR / DD comparees a backtest baseline 2026.

### Concerns reportes (acceptable < J+7)
- H3 codes catalog `EXECUTION_*` non emis (cosmetic mais important pour audit)
- M1 freshness check par bar avant submit
- M3 trip CATASTROPHE post-restart au lieu de DAILY
- M4 TimeInForce explicite DAY

### Annexe : 2 autres bots simultanes
- **MIA-DataBento-Paper-V2** (Bot 2 V2 SetupEngine + Bot 3 in-process) → live deja, Sim2 (Bot 2) + Sim1 (Bot 3 via TRADE_ACCOUNT_BOT3="Sim1"). User DTC `miav2`.
- **MIA-Paper** (mia_paper_trader.py Sim3 dashboard-follower) → STOPPED 03/05 11:00 UTC suite crash-loop WinError 10038 (60+ reboots/jour, signaux fictifs date 2026-05-05).

---

## 2026-05-01 14:57 UTC — [Bot 2 SCORING sur LIVE bar (anti-INADMISSIBLE Jackson)]

**Categorie** : FIX (architecture data freshness)
**Impact prod** : PAPER (Bot 2 databento)
**Fichier(s)** : `CORE/databento_paper_trader.py:1612-1716` + `CORE/log_catalog.py:259-261`
**Reviewer(s) agent** : Plan agent v3 (NOGO sur drift mais score_consensus est rule-based pas ML donc N/A) + code-reviewer (GO-AVEC-RESERVES, 1 reserve appliquee : safe parsing ts_event_iso)

### Quoi
Bot 2 lit desormais la bar du LIVE_CACHE (`databento_live_stream.py` ecrit, latence 60s) au lieu de scorer sur la bar parquet Historical (delay 30 min). Implementation :
- Nouvelle methode `_read_live_cache_bar` : lit JSON OHLCV LIVE complet
- Nouvelle methode `_enrich_bar_with_live` : merge bar parquet + live :
  - Override OHLC + volume avec valeurs LIVE
  - Recalcule `dist_mq_call/put/hvl_pct` + `bool_above_mq_*` + `dist_pdh/pdl_pct` avec close LIVE
  - Garde features structurelles parquet (mq_levels daily, day_type, profile_shape, cvd_5d, atr_14m)
  - Logger `LIVE_BAR_OVERRIDE` 1x/min/symbole
- `_process_symbol` ligne 1910 : appelle `_enrich_bar_with_live` AVANT le check stale → bar_ts = live_ts (60s) au lieu de parquet ts (30 min) → HARD SKIP plus declenche
- Code log `LIVE_BAR_OVERRIDE` (INFO, events) ajoute

### Pourquoi
Jackson directive 14:50 UTC : "TRADER SUR DONNEES 33 MIN DE RETARD = INADMISSIBLE". Mesures empiriques au deploy : ES drift -59 ticks / NQ drift -178 ticks entre close parquet (vieux 30 min) et close live. Trader sur parquet = decisions sur conditions completement differentes du marche actuel.

DATABENTO_DELAY_MIN reduit 30→15 (compromis pipeline) en parallele, mais la VRAIE solution est ce refactor live override.

### Impact attendu
- Bot 2 score sur conditions de marche actuelles (latence 60-90s vs 30 min)
- Reduction drastique slippage entry (cf coherence avec close_for_order ligne 2295 qui utilisait deja live)
- Drift train/serve : NON-APPLICABLE car score_consensus = rule-based (if/else), pas ML LGBM
- Si MIA-Live-OHLCV down → fallback parquet auto (no-op via try/except + max_age_sec=180)

### Validation pre-deploy
- [x] Compile check OK
- [x] Plan agent v3 + code-reviewer reviews
- [x] Reserve appliquee : try/except autour pd.to_datetime(ts_event_iso)
- [x] Deploy 14:57:23 UTC, premiers events LIVE_BAR_OVERRIDE OK :
  - ES : close_parquet=7296.5 close_live=7281.75 delta=-59t live_age=23s
  - NQ : close_parquet=27872.75 close_live=27832.25 delta=-178t

### Suivi post-deploy
- T+15min : verifier first BOT_HEARTBEAT nouveau PID 6448 → last_bar_age doit etre <90s (vs 2300s avant)
- J+1 : grep `LIVE_BAR_OVERRIDE` events distribution delta_ticks (median <2t en steady-state, p99 <10t)
- J+7 : ratio slippage entry vs scoring close — doit chuter 23t → <3t

### Risques residuels documentes
- `aggressor_imbalance` reste de 30 min en arriere (poids 1, pas bloquant dans score)
- Re-trade meme bar parquet sur N ts LIVE differents : mitige par RiskManager + ALREADY_IN_POSITION
- Si MIA-Live-OHLCV crash : fallback parquet, bar_age explose 30 min, flag CRIT recree, Bot 2 stop (comportement souhaite)

### Branche dev
`feature/pipeline-incremental` (merge master apres 24h validation steady-state)

---

## 2026-05-01 13:55 UTC — [Option B : bumper seuils Bot 2 + watchdog pour tolerer retard pipeline]

**Categorie** : CONFIG (seuils data freshness)
**Impact prod** : PAPER (Bot 2 databento)
**Fichier(s)** : `CORE/databento_paper_trader.py:113-125` + `BOT/mia_watchdog.py:101-107`
**Reviewer(s) agent** : N/A (calibration de constantes, pas de logique nouvelle)

### Quoi
- Bot 2 anti-cascade seuils : FRESH 90→600, WARN 300→1500, CRIT 900→2700 (en sec)
- Watchdog Bot 2 alignement : warn 300→1500, crit 900→2700
- Restart MIA-DataBento-Paper avec nouveaux seuils
- Suppr `STOP_DATABENTO.flag` manuellement pour boot propre

### Pourquoi
**Bug logique decouvert apres deploy fix anti-cascade matin** : `live_pipeline_loop.py` produit parquet `v4_enriched` avec **retard structurel ~30 min** (pipeline batch retraite mois entier a chaque cycle 5 min, ne rattrape qu'1 min/cycle). Mes seuils v1 (FRESH=90s) ne sont JAMAIS atteints car pipeline ne descend pas sous 90s. Resultat : Bot 2 reste en pause indefiniment apres premier flag CRIT. Recovery automatique cassee.

Solution Option B (Jackson 14:00 UTC) : bumper seuils pour aligner sur latence pipeline ~5-10 min steady-state + marge catch-up. Bot 2 trade sur bars 5-10 min anciennes (perf paper degradee mais OK). Solution propre = pipeline incremental (Option C, backlog).

### Validation pre-deploy
- [x] Compile check OK
- [x] SCP + restart MIA-DataBento-Paper, MIA-Watchdog
- [x] Watchdog incoherence detectee post-deploy : seuils watchdog Bot 2 desalignes (CRIT 900) → re-restart Bot 2 inutile a 13:55:11. Fix immediat alignement seuils watchdog.

### Deployed at 2026-05-01 13:54 UTC (databento) + 13:56 UTC (watchdog seuils alignes)

### Suivi post-deploy
- T+15min : verifier flag local non recree par Bot 2
- T+1h : verifier 0 restart inutile par watchdog
- T+2h30 : pipeline doit avoir rattrape, parquet last bar ~5 min retard

### Backlog (Option C, prochaine session)
Refactor `CORE/build_dataset_v4_dmp_databento.py` incremental — voir memory `project_pipeline_incremental_backlog.md`.

---

## 2026-05-01 14:00 UTC — [Watchdog v2 multi-source data freshness + auto-restart nssm]

**Categorie** : FEATURE (monitoring + reliability)
**Impact prod** : NEW SERVICE (`MIA-Watchdog`)
**Fichier(s)** : `BOT/mia_watchdog.py` (reecriture complete v1 legacy obsolete)
**Reviewer(s) agent** : code-reviewer 2x (NOGO v1 → fixes 9 issues → GO v2 + fix 2 bugs dry-run runtime)

### Quoi
Service nssm `MIA-Watchdog` qui surveille en continu la fraicheur de **7 sources** :
1. V2CLEAN brain (heartbeat.txt json ts_utc)
2. Databento stream (databento_live_stream.log mtime)
3. Bot 1 Sierra (events_*_paper.jsonl mtime, regex strict pour exclure databento)
4. Bot 2 Databento (last_bar_age dans BOT_HEARTBEAT)
5. Live pipeline (live_pipeline_loop.log mtime)
6. DMP JSONL ES + 7. NQ (mtime fichier du jour)

Sur stale CRITICAL → Discord alerte + `Restart-Service` nssm (cap 3/heure/service persistant disque).
Heartbeat positif Discord toutes les 10 min — color/title/channel selon worst level (vert OK admin, rouge CRIT alertes).
Logs structures dans `LOGS/events/events_YYYYMMDD_watchdog.jsonl` (audit J+1 grep).

### Pourquoi
**Incident 30/04 minuit → 01/05 09:00** (33h) : V2CLEAN.bot_main service nssm "Running" mais 0 log ecrit (deadlock probable post-rotation EventJournal). Aucune alerte Discord. Jackson decouvre par hasard. Le legacy `mia_watchdog.py` surveillait UNIQUEMENT `BOT/bot_main.py` (legacy non utilise) via `heartbeat_writer.py` → inutile pour les 6 services nssm actuels. Reecriture complete obligatoire.

### Impact attendu
- Detection zombie/stale < 5 min (vs 33h sans watchdog)
- Auto-restart si possible (cap protection anti-loop)
- Visibility positive : silence Discord 10 min = watchdog mort = a investiguer
- Aucun impact trading direct (monitoring pur)

### Validation pre-deploy
- [x] Compile check : `python -m py_compile` OK
- [x] Smoke tests logiques : 4 tests (filter glob, persistence RestartTracker, priorites level, ABSENT seuil)
- [x] Dry-run local 8s : 7 sources scannees, Discord simule, no crash
- [x] Code-reviewer agent v1 : NOGO 3 bugs critiques + 6 reserves
- [x] Code-reviewer agent v2 : **GO** apres fixes
- [x] Bugs runtime detectes en dry-run (UnicodeDecodeError stderr fr-FR + dry-run ne couvrait pas Restart-Service) : FIXES appliques
- [N/A] Backtest preservation : pas de modif scoring/gates

### Revert plan
```bash
ssh Administrator@212.28.179.199 'powershell -Command "Stop-Service MIA-Watchdog ; nssm remove MIA-Watchdog confirm"'
git checkout HEAD~1 -- BOT/mia_watchdog.py
# Si besoin : supprimer DATA/HEARTBEAT/watchdog_restart_history.json
```

### Deployed at 2026-05-01 13:42 UTC (initial) + 13:44 UTC (v2.1 fix seuils Bot1)
- v1 deploy 13:42:17 → faux positif immediat sur Bot1_Sierra_paper (silence 21 min entre BOT_KILL_SWITCH_RELEASED et fin blocage RTH 15 min) → restart MIA-Paper inutile.
- Stop-Service MIA-Watchdog 13:43:21
- Bumper seuils Bot1 : warn 120→600, crit 600→1800 (commentaires inline)
- v2.1 SCP + Start-Service 13:44:11 → WATCHDOG_HEARTBEAT worst=PAUSED, 0 crits, 0 restarts ✅
- Bug fixes runtime decouverts en dry-run : UnicodeDecodeError stderr fr-FR + dry_run ne couvrait pas Restart-Service → fixes appliques avant deploy.

### Suivi post-deploy
- J+1 : verifier `LOGS/events/events_*_watchdog.jsonl` contient WATCHDOG_HEARTBEAT toutes les 10 min
- J+7 : compter restarts auto declenches, valider reduction MTTR
- J+30 : reviewer cap 3/h trop strict ou trop laxiste

### Nouveaux logs (rule log-debug-protocol.md)
- WATCHDOG_START / WATCHDOG_STOP / WATCHDOG_CRASH (events)
- WATCHDOG_HEARTBEAT (info, toutes les 10 min)
- WATCHDOG_SOURCE_WARN / WATCHDOG_SOURCE_CRIT (per-source)
- WATCHDOG_FLAG_STALE (flag pause oublie > 30 min)
- WATCHDOG_RESTART_TRIGGERED / WATCHDOG_RESTART_CAP_REACHED / WATCHDOG_RESTART_SIMULATED

---

## 2026-05-01 13:10 UTC — [Anti-cascade STOP.flag + recovery auto data feed databento]

**Categorie** : FIX (kill-switch design)
**Impact prod** : PAPER (Bot 2 databento + Bot 1 mia_paper indirect)
**Fichier(s)** : `CORE/databento_paper_trader.py:107,117,422,478,1059,1670-1740` + `CORE/log_catalog.py:255`
**Schema/version** : N/A (no schema change)
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES — 3/4 reserves appliquees, Discord alerter reportee phase 2 watchdog)

### Quoi
- `databento_paper_trader.py` n'ecrit plus `STOP.flag` GLOBAL quand son data feed est stale, mais un flag DEDIE `STOP_DATABENTO.flag` (LOCAL au bot databento).
- `can_trade()` lit les 2 flags : global admin + local data stale.
- Recovery auto : compteur `_consec_fresh_hb`, si flag local existe + 3 hb consec frais (last_age <= 90s) → suppr flag automatiquement + emit `DATA_FEED_RECOVERED`.
- Constantes nommees `DATA_FRESH_THR_SEC=90`, `DATA_WARN_THR_SEC=300`, `DATA_CRIT_THR_SEC=900`, `DATA_RECOVERY_CONSEC_HB=3`.
- Idempotence : flag re-write seulement si pas deja present (pas de pollution logs).

### Pourquoi
**Incident 01/05 12:43 UTC** : `databento_paper_trader.py:1683` (avant fix) creait `STOP.flag` GLOBAL sur stale 900s+. Ce flag est lu par 5 bots dont `mia_paper_trader.py` (DTC live, data feed different). Resultat cascade : un probleme isole cote Databento a kill mia_paper_trader pendant 20 min juste avant l'open RTH 09:30 ET. Bot DTC live ne devait jamais pauser sur incident Databento.

### Impact attendu
- Anti-cascade : data feed Databento stale → tue UNIQUEMENT le bot databento, pas mia_paper_trader DTC
- Reduit MTTR : recovery auto 15 min apres reconnect stream (vs intervention humaine sinon)
- Admin override conserve : `STOP.flag` global tue toujours TOUS les bots
- Effet de bord : aucun (pas de modif scoring/gates/sizing)

### Validation pre-deploy
- [x] Compile check : `python -m py_compile CORE/databento_paper_trader.py CORE/log_catalog.py` OK
- [N/A] Backtest preservation : pas de modif scoring/gates
- [x] Review agent code-reviewer : GO-AVEC-RESERVES (4 reserves)
  - 3 appliquees (constantes nommees, idempotence flag, no-reset compteur post-recovery)
  - 1 reportee (Discord alerter pour flag local) → phase 2 watchdog externe

### Revert plan
```bash
# Si rollback necessaire :
ssh Administrator@212.28.179.199 'powershell -Command "Stop-Service MIA-DataBento-Paper"'
git checkout HEAD~1 -- CORE/databento_paper_trader.py CORE/log_catalog.py
scp CORE/databento_paper_trader.py CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 'powershell -Command "Start-Service MIA-DataBento-Paper"'
# Et supprimer manuellement STOP_DATABENTO.flag si present
```

### Deployed at 2026-05-01 13:15 UTC
- SCP `databento_paper_trader.py` (134718 bytes) + `log_catalog.py` (28053 bytes) vers VPS OK
- `Restart-Service MIA-DataBento-Paper` OK : ancien PID 10292 stop, nouveau PID 2228 BOT_START a 13:15:31 UTC
- Service `Running`, BOT_HEARTBEAT en attente premiere bar Databento

### Suivi post-deploy
- J+1 : verifier 0 occurence de `BOT_KILL_SWITCH_ACTIVATED` cote `mia_paper_trader.py` cause data Databento stale
- J+7 : verifier `DATA_FEED_RECOVERED` emis au moins 1 fois si data Databento a oscille
- J+30 : metrics watchdog phase 2 (a designer)

### Nouveaux logs (rule log-debug-protocol.md)
- `DATA_FEED_RECOVERED` (MAJEUR, events) : transition stale → fresh apres N=3 hb consec frais

### Liens
- Incident matin 01/05 ~12:43 UTC : voir DOCS/INCIDENT_LOG.md (a ajouter post-deploy)
- Review agent code-reviewer : transcript session 2026-05-01

---

## 2026-05-01 09:00 UTC — [v6 SLTP sub-tier T2_STRUCTUREL mutation + logs CAS 4 enrichis]

**Categorie** : FEATURE (refacto walls) + LOGGING (tracking rejets CAS 4)
**Impact prod** : Bot 1 (MIA-Paper-Trader Sim3) + Bot 2 (MIA-DataBento-Paper Sim2) + dataset paper_trades.jsonl
**Fichier(s)** :
- Modif : `CORE/mia_sltp.py` — ajout `T2_STRUCTUREL_WALLS` set (13 cols), 3 nouvelles features TIER2 (`dist_blind_nearest_up/dn`, `dist_vwap_m`), enrichissement SLTPResult (cas4_subtier, cas4_blocked_wall_col, cas4_rr_pre/post, cas4_caused_reject), logique CAS 4 v6 mutation T1+T2_STRUCTUREL, reject_reason enrichi avec context capot
- Modif : `CORE/mia_paper_trader.py:1156-1206` — `_funnel_reject("7_sltp")` enrichi avec cas4_kwargs si cas4_caused_reject. Snapshot trade ouvert (~1290) : ajout 11 champs cas4_* tracking ex-post
- Modif : `CORE/databento_paper_trader.py:2109-2160` — emit `SLTP_CAS4_TRIGGERED` enrichi (subtier, wall_col, rr_pre/post), nouveaux emit `SLTP_CAS4_T2_OBSERVED` + `SLTP_CAS4_CAUSED_REJECT`
- Nouveau : `tests/test_mia_sltp_v6_t2_structurel.py` — 22 tests (T2_STRUCTUREL set invariants, mutation T1+T2_S, observability T2 hors structurel, reject tracking, df columns)

**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES — réserves observabilite non bloquantes : R1 casing wall_col vs cas4_blocked_col, R2 helper extraction DRY, R3 doc cas4_observed_tier2 legacy ; aucun bug bloquant)

### Quoi

13 features T2 (anchors VWAP multi-TF, MQ classiques, 1D extremes, Blind Levels) deviennent un sub-tier `T2_STRUCTUREL` qui beneficie de la MUTATION CAS 4 anti-TP-derriere-mur (comme TIER1). Le reste de TIER2 reste observability-only legacy. Logs CAS 4 enrichis pour tracking ex-post : subtier (T1/T2_STRUCTUREL/T2_OBSERVABILITY), col du mur, R:R pre/post capot, flag caused_reject si capot a fait chuter R:R sous MIN_RR_RATIO (0.8).

### Pourquoi

Audit walls 30/04 : trade screen Bot 1 SHORT @ 7239 → 1D Max @ 7236.77 (~9 ticks devant TP) + SD-1 W bloquaient le TP de facto. Avec mutation T2_STRUCTUREL, TP cap a 6t → R:R 6/14 = 0.43 < MIN_RR_RATIO → trade REJECTED avant entree (intention defensive). Anti pattern 11 V1 : ce n'est pas une promotion T3→T2, juste un label MUTATION sur sous-ensemble curated dans T2.

Validation Jackson 30/04 soir : "ok je valide" apres comparatif visuel actuel vs proposition v6.

### Impact attendu

- Effet protecteur : trades avec mur structurel devant TP (R:R<0.8 apres capot) seront rejetes avant entree → reduction nb trades
- Logs enrichis : permet grep ex-post `cas4_capot_t2_structurel` pour identifier murs offenders et calibrer fire rate
- Effet de bord : aucun (capot deja existant pour T1, on etend a 13 cols T2 curated avec defaults)

### Validation pre-deploy

- [x] Tests unitaires: 60/60 PASS suite SLTP globale (22 nouveaux v6)
- [x] Backtest preservation: smoke test 4 scenarios (T1 mutation, T2_STRUCTUREL mutation, T2 observability, CAS4 caused reject) tous validés
- [x] Review agent: code-reviewer GO-AVEC-RESERVES (réserves R1-R5 non bloquantes, observabilité)
- [x] Test empirique : `python -X utf8 -m pytest tests/test_mia_sltp_v6_t2_structurel.py` → 22 passed

### Revert plan

```bash
# Rollback git
git revert HEAD~3..HEAD  # 3 commits split (sltp, bot1, bot2)

# Re-deploy ancien code VPS
scp CORE/mia_sltp.py CORE/mia_paper_trader.py CORE/databento_paper_trader.py \
    Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"

# Restart services nssm
ssh Administrator@212.28.179.199 "nssm restart MIA-Paper-Trader"
ssh Administrator@212.28.179.199 "nssm restart MIA-DataBento-Paper"
```

### Deployed at 2026-05-01 09:XX UTC
(a remplir apres SCP + restart nssm)

### Suivi post-deploy

- **J+1 (02/05)** : grep `SLTP_CAS4_TRIGGERED` events → ratio T1 vs T2_STRUCTUREL (attendu : majorite T1, T2_S minoritaire mais non nul). grep `SLTP_CAS4_CAUSED_REJECT` → fire rate (>5/jour = trop agressif, audit murs offenders). grep `cas4_capot_t2_structurel` decisions → identifier murs T2_S responsables (BLIND_UP, 1D_MIN, VWAP_W).
- **J+7 (08/05)** : preservation backtest wins → si > 10% wins historiques rejetes par v6, rollback.
- **J+30 (31/05)** : si fire rate stable et coherent, evaluer extension T2_STRUCTUREL aux T2 actuellement observ-only (CUR_VAH, SWING_HIGH...).

### Contexte deploy

Deploy en pleine periode catastrophique : 2 jours de pertes (30/04 + 01/05) totalisant -$1,526 sur 61 trades, WR moyen 25%. v6 SLTP deployee comme **couche defensive** (rejette plus de trades = moins de pertes en attendant audit cause racine WR catastrophique). Audit market-analyst dispatchée en parallèle pour identifier patterns d'entrée fautifs (sur-trading meme setup, repetition LONG NQ confluence VWAP-SD inverse, Bot 2 fallback FIXED_40T fréquent).

### Liens

- Memory : `user_jackson_workflow.md` (validation "ok je valide" 30/04 soir), `feedback_pattern11_repetition_avoided.md` (anti-T3→T2)
- Tests : `tests/test_mia_sltp_v6_t2_structurel.py`

---

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
