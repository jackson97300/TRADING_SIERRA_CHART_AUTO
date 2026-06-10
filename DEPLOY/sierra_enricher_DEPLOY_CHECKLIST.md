# Phase 4.2.2 — Deploy Sierra Enricher VPS — Checklist

**Date** : 10/06/2026
**Phase** : 4.2.2 Sierra Full Migration
**Statut** : ⏳ ATTENTE confirmation Jackson explicite avant SCP

⚠️ **REGLE CLAUDE.md** : "JAMAIS envoyer de fichier sur le VPS sans confirmation explicite"

---

## Pre-flight checks (LOCAL, avant SCP)

- [x] Phase 4.1 `CORE/sierra_pipeline.py` 13/13 tests PASS
- [x] Phase 4.2.1 `BOT/run_sierra_enricher.py` 12/12 tests PASS
- [x] E2E validation : 1125 bars NQ 08/06 enrichies, 0 erreur, 485 cols/bar
- [x] Review code-reviewer GO franc post-polish (commit `e4e3bff`)
- [x] Scripts deploy crees localement (`DEPLOY/sierra_enricher_*.ps1`)
- [ ] **Jackson confirme explicitement deploy VPS**

---

## Files a deployer via SCP (apres confirmation)

### CORE modules Phase 3 (9 fichiers)
```bash
scp CORE/poc_migration.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/roll_calendar.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/eco_news_features.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/swings_v2.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/prev_levels.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/sessions_fine.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/session_utils.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/divergences_v2.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
scp CORE/ctx_rolling.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
```

### CORE dependances obligatoires (fix C1 review 10/06)
```bash
# sierra_live_io.py est importe par sierra_pipeline + wrapper.
# Verifier d'abord version VPS avant overwrite (peut etre deja deploye).
scp CORE/sierra_live_io.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
```

### CORE orchestrateur Phase 4.1
```bash
scp CORE/sierra_pipeline.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
```

### BOT wrapper Phase 4.2.1
```bash
scp BOT/run_sierra_enricher.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/BOT/"
```

### DEPLOY scripts PowerShell
```bash
scp DEPLOY/sierra_enricher_nssm_install.ps1 Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DEPLOY/"
scp DEPLOY/sierra_enricher_nssm_uninstall.ps1 Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DEPLOY/"
scp DEPLOY/sierra_enricher_DEPLOY_CHECKLIST.md Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/DEPLOY/"
```

---

## Install VPS (apres SCP)

```powershell
# Connexion VPS
ssh Administrator@212.28.179.199

# Verifier presence fichiers
cd C:/TRADING_SIERRA_CHART_AUTO
ls CORE/sierra_pipeline.py BOT/run_sierra_enricher.py DEPLOY/sierra_enricher_*.ps1

# Creer dir temp Windows (fix C2 review : /tmp/ Unix incompatible)
New-Item -ItemType Directory -Path C:/Temp -Force | Out-Null

# Test wrapper local sur fichier reel (dry-run, sans ecrire)
$today = Get-Date -Format yyyyMMdd
python -X utf8 BOT/run_sierra_enricher.py --symbol NQ `
    --batch DATA/NQ/${today}_NQ.jsonl `
    --output C:/Temp/test_sierra_${today}.jsonl --dry-run

# Si dry-run OK : install service nssm
.\DEPLOY\sierra_enricher_nssm_install.ps1 -Symbol NQ

# Verifier install
Get-Service MIA-Sierra-Enricher-NQ
# Expected: Status=Stopped, StartType=Manual (DEMAND_START)
```

---

## Start service (Jackson confirme une 2eme fois pour 1er start)

```powershell
# 1er start manuel
Start-Service MIA-Sierra-Enricher-NQ

# Check status apres 30s
Start-Sleep -Seconds 30
Get-Service MIA-Sierra-Enricher-NQ
# Expected: Status=Running

# Check logs stdout (premiers events)
Get-Content -Tail 20 C:/TRADING_SIERRA_CHART_AUTO/LOGS/sierra_enricher/sierra_enricher_NQ_stdout.log

# Check logs stderr (devrait etre vide ou minimal)
Get-Content -Tail 20 C:/TRADING_SIERRA_CHART_AUTO/LOGS/sierra_enricher/sierra_enricher_NQ_stderr.log

# Check output JSONL apres 60s (au moins 1 bar)
Start-Sleep -Seconds 60
Get-ChildItem C:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/sierra/NQ/*.jsonl
# Expected: fichier yyyyMMdd_NQ_sierra_enriched.jsonl avec au moins 1 ligne
```

---

## Monitoring J+1 (24h apres start)

- [ ] Service Running stable (pas de crash)
- [ ] Output JSONL contient ~1380 bars/jour (RTH + extended)
- [ ] Pas de JSONDecodeError dans logs (lignes tronquees R1 review)
- [ ] Pipeline stats coherentes : bars_processed > 0, errors faibles
- [ ] Cross-day reset 18:00 ET detecte (cross_day_resets >= 1)
- [ ] Comparaison parite vs Databento enricher (Phase 4.3)

---

## Rollback strategy

Si problemes (crash repete, output corrompu, perf degradee) :

```powershell
# Stop + uninstall
.\DEPLOY\sierra_enricher_nssm_uninstall.ps1 -Symbol NQ

# Fichiers JSONL preserves dans DATA/live_enriched/sierra/NQ/
# Logs preserves dans LOGS/sierra_enricher/
# Investigation post-mortem avant re-install
```

---

## Decision Phase 4.3 (apres 5 jours dual-run)

Apres 5 jours de dual-run :
- Comparer features Sierra vs Databento bar par bar
- Convergence >= 95% par feature SIGNED -> GO Phase 5 (backfill + cutover)
- Convergence < 95% sur > 5 features -> investigation + fix avant Phase 5

---

**Sources references** :
- `CORE/sierra_pipeline.py` (Phase 4.1 orchestrateur)
- `BOT/run_sierra_enricher.py` (Phase 4.2.1 wrapper)
- `DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md` (master design)
- `.claude/rules/critical-tasks-review.md` (deploy = irreversible critere 7)
- Memory `reference_vps_process_persistence` (nssm pattern existant)
