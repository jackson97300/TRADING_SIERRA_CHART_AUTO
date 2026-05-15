# Deploy MIA-Live-Enricher (Phase 2 plan Pass 4)

**Date** : 2026-05-15
**Statut** : ATTENTE OK JACKSON pour deploy VPS

## Pre-requis

- live_enricher.py + dependances code-ready (sanity test --test 5/5 PASS)
- R2 seed warmup actif (commit b79d138) : lit V4 parquet mois courant au boot
- Code log_catalog : 4 nouveaux codes ENRICHER_* enregistres
- VPS Databento Live deja streaming (MIA-Databento-Live service nssm actif)
- Trades buffer Chantier 2 deja running (DATA/LIVE_CACHE/trades/{sym}/*.jsonl)
- Sierra MQ_Lite + VIX_Lite dump deja running

## Commandes deploy (a executer sur VPS apres OK Jackson)

### 1. Deployer code Live Enricher VPS

```bash
# 4 fichiers Live Enricher (depuis PC local)
scp CORE/live_enricher.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/live_enricher_io.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/live_enricher_state.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/live_enricher_writer.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"

# log_catalog update (codes ENRICHER_* 4 nouveaux)
scp CORE/log_catalog.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
```

### 2. Installer service nssm sur VPS

```powershell
# Connexion SSH puis :
ssh Administrator@212.28.179.199

# Installer service (executer en mode admin VPS)
nssm install MIA-Live-Enricher "C:\Program Files\Python311\python.exe" "-X utf8 C:\TRADING_SIERRA_CHART_AUTO\CORE\live_enricher.py"

# Configurer
nssm set MIA-Live-Enricher AppDirectory "C:\TRADING_SIERRA_CHART_AUTO"
nssm set MIA-Live-Enricher Start SERVICE_AUTO_START
nssm set MIA-Live-Enricher AppStdout "C:\TRADING_SIERRA_CHART_AUTO\LOGS\live_enricher_stdout.log"
nssm set MIA-Live-Enricher AppStderr "C:\TRADING_SIERRA_CHART_AUTO\LOGS\live_enricher_stderr.log"
nssm set MIA-Live-Enricher AppRotateFiles 1
nssm set MIA-Live-Enricher AppRotateBytes 10485760

# Demarrer
nssm start MIA-Live-Enricher

# Verifier
Get-Service MIA-Live-Enricher
```

### 3. Verifications post-deploy

```bash
# Heartbeat (apres 60s)
ssh Administrator@212.28.179.199 "type C:\TRADING_SIERRA_CHART_AUTO\DATA\LIVE_CACHE\enricher_state\heartbeat.json"

# JSONL en cours d'ecriture
ssh Administrator@212.28.179.199 "dir C:\TRADING_SIERRA_CHART_AUTO\DATA\live_enriched\ES_c_0\ /b"

# Logs stdout
ssh Administrator@212.28.179.199 "type C:\TRADING_SIERRA_CHART_AUTO\LOGS\live_enricher_stdout.log" | head -50

# Logs evenements MIA
ssh Administrator@212.28.179.199 "type C:\TRADING_SIERRA_CHART_AUTO\LOGS\events\events_$(date +%Y%m%d).jsonl" | grep -i ENRICHER
```

## Force cold start (declenche seed depuis V4 batch parquet)

**Cas d'usage** : apres modif code seed sessions / open_cash dans
live_enricher_state.py, le restart classique nssm garde le pickle state
existant (`state_loaded=True` dans logs ENRICHER_BOOT) -> SKIP du seed.

Pour FORCER cold start :

```bash
# 1. Stop service
ssh Administrator@212.28.179.199 "nssm stop MIA-Live-Enricher"

# 2. Delete pickle states (force cold start sur prochain boot)
ssh Administrator@212.28.179.199 "powershell -Command Remove-Item C:/TRADING_SIERRA_CHART_AUTO/DATA/LIVE_CACHE/enricher_state/*.pickle -Force"

# 3. Start
ssh Administrator@212.28.179.199 "nssm start MIA-Live-Enricher"

# 4. Verifier logs ENRICHER_SEED_OPEN_CASH_FROM_V4 + ENRICHER_SEED_SESSIONS_FROM_V4
ssh Administrator@212.28.179.199 "powershell -Command \"Select-String -Path C:/TRADING_SIERRA_CHART_AUTO/LOGS/live_enricher_stdout.log -Pattern 'ENRICHER_SEED' | Select-Object -Last 5\""
```

**Risque** : perte de l'historique state pickle (rolling buffer 60j bars + engine_states).
Le warmup_from_v4=True doit RE-CHARGER bars depuis V4 parquet → ~30s boot time.

## Pipeline d'inspection (apres 1-2h prod)

```bash
# Sync JSONL VPS -> PC
scp -r Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/ES_c_0/*.jsonl" DATA/live_enriched/ES_c_0/
scp -r Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ_c_0/*.jsonl" DATA/live_enriched/NQ_c_0/
scp Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DATA/LIVE_CACHE/enricher_state/heartbeat.json" DATA/LIVE_CACHE/enricher_state/

# Inspecter contenu local
python tools/snapshot_inspector.py --all --verbose

# Comparer vs V4 batch (drift detection)
python tools/snapshot_inspector.py --symbol ES.c.0 --compare-v4

# Validator PRO (a la dmp_validator.py) — 8 checks DMP-style
python tools/live_enricher_validator.py --date YYYYMMDD
python tools/live_enricher_validator.py --symbol NQ.c.0 --strict
# Verdict GREEN / YELLOW / RED + actions concretes

# Comparer apres 1 mois complet (V4 oracle test extension)
python tests/test_live_enricher_parity_v4.py
```

## Plan rollback

```powershell
# Stopper service (sans desinstaller)
ssh Administrator@212.28.179.199 "nssm stop MIA-Live-Enricher"

# Desinstaller (si bug bloquant)
ssh Administrator@212.28.179.199 "nssm remove MIA-Live-Enricher confirm"
```

## Criteres GO/NOGO production

**GO** :
- `heartbeat.json` updated < 60s
- 1 JSONL line par minute par symbol (3 lignes/min total ES+NQ+MGC)
- Schema version `live_enriched_1.0` present
- `ml_critical_features` 22/22 presents (verifie par snapshot_inspector)
- 0 emit `ENRICHER_WRITE_FAIL` dans `LOGS/events/`

**NOGO (rollback immediate)** :
- 3+ emit `ENRICHER_WRITE_FAIL` consecutifs
- Heartbeat stale > 5 min
- JSONL contient `schema_version != live_enriched_1.0`
- Conso CPU > 50% sustained
- RAM > 2 GB sustained (rolling buffer 60j *3 sym = ~1 GB attendu)

## Suivi J+1

- Grep `ENRICHER_SEED_OPEN_CASH_FROM_V4` dans `LOGS/events/{date}.jsonl` apres 1er boot
  - Si > 0 emit = R2 seed warmup actif (commit b79d138)
  - Si 0 emit = VALIDATION_MISS (instrumentation muette) → INCIDENT_LOG
- Comparer JSONL Sample 100 bars vs V4 batch ES → drift < 1e-6 sur GREEN features
- Inspecter `dead_features_count` dans snapshot_inspector → si > 50 = bug streaming

## References

- `CORE/live_enricher.py` (main loop + boot R2 seed warmup)
- `CORE/live_enricher_writer.py` (JSONL output schema 1.0)
- `tools/snapshot_inspector.py` (analyse post-deploy)
- `tests/test_live_enricher_parity_v4.py` (V4 oracle test R3)
- `DOCS/CHECKLIST_FEATURE_ADDED.md` (regles ajout feature)
- `.claude/rules/critical-tasks-review.md` (protocole agent review)
