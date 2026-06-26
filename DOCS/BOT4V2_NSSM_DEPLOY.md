# Bot 4 v2 — Deploy paper Sim4 via nssm (procédure manuelle Jackson)

**Date** : 2026-06-26
**Source** : Phase P5.4.C bot4_v2 chantier (refonte propre INCIDENT_LOG #83)
**Pré-requis** : INCIDENT_LOG #91 (Sim4 = compte Bot 4 v1 STOPPED, réutilisé Bot 4 v2)

## ✋ Pré-requis manuel Jackson

**AVANT lancer le service**, sur VPS Sierra Chart GUI :
1. Trade Activity Log → Sim4 → **Close All Positions** (flatten Bot 4 v1 historique)
2. Vérifier balance Sim4 = 0 positions
3. Confirmer compte Sim4 propre

## Commandes nssm install (à exécuter une seule fois)

```powershell
# 1. Stop ancien service Bot 4 v1 (si encore actif)
nssm stop MIA-Bot-4-Paper
nssm set MIA-Bot-4-Paper Start SERVICE_DISABLED

# 2. Install nouveau service Bot 4 v2
$ServiceName = "MIA-Bot4V2-Sim4-Paper"
$Python = "C:\Program Files\Python311\python.exe"
$AppDir = "C:\TRADING_SIERRA_CHART_AUTO"
$Args = "-X utf8 -m bot4_v2.main --symbols NQ --no-dry-run --trade-account Sim4"

nssm install $ServiceName $Python $Args
nssm set $ServiceName AppDirectory $AppDir
nssm set $ServiceName AppStdout "C:\TRADING_SIERRA_CHART_AUTO\LOGS\bot4v2_stdout.log"
nssm set $ServiceName AppStderr "C:\TRADING_SIERRA_CHART_AUTO\LOGS\bot4v2_stderr.log"

# Auto-restart : 30s delay + max 5 restarts/h
nssm set $ServiceName AppExit Default Restart
nssm set $ServiceName AppRestartDelay 30000

# Rotation logs (R-backlog Bot 3 BN V4 #87 leçon)
nssm set $ServiceName AppRotateBytes 10485760
nssm set $ServiceName AppRotateFiles 1

# Env vars (PYTHONPATH + Discord webhook si configuré)
nssm set $ServiceName AppEnvironmentExtra "PYTHONPATH=C:\TRADING_SIERRA_CHART_AUTO" "BOT4V2_DISCORD_WEBHOOK=https://discord.com/api/webhooks/XXX/YYY"

# 3. Start service
nssm start $ServiceName

# 4. Verify
sc query $ServiceName
Get-Process | Where-Object {$_.ProcessName -like "python*"} | Where-Object {$_.StartTime -gt (Get-Date).AddMinutes(-5)}
```

## Sentinels J+1 (verification logs cross-day)

```powershell
# Run manuel J+1 matin (verifie emission codes BOT4V2_*)
cd C:\TRADING_SIERRA_CHART_AUTO
$today = (Get-Date).ToString("yyyyMMdd")
python -X utf8 tools/bot4v2_sentinel.py --date $today --logs-root LOGS

# Mode strict pour cron (exit 1 si VALIDATION_MISS)
python -X utf8 tools/bot4v2_sentinel.py --date $today --strict --json
```

## Backtest replay metrics post-deploy

```powershell
# Verifier pipeline produit fires sur derniers jours apres deploy
cd C:\TRADING_SIERRA_CHART_AUTO
$PYTHONPATH="."
python -X utf8 tools/bot4v2_replay_metrics.py --symbol NQ --since 20260620 --until 20260626
```

## Désinstallation (rollback)

```powershell
nssm stop MIA-Bot4V2-Sim4-Paper
nssm remove MIA-Bot4V2-Sim4-Paper confirm
```

## Discord webhook setup (optionnel mais recommandé)

1. Discord serveur → créer channel `#bot4v2-sim4-alerts`
2. Channel Settings → Integrations → Webhooks → New Webhook
3. Copier URL webhook
4. Inject via env var `BOT4V2_DISCORD_WEBHOOK` (cf nssm setup ci-dessus)
5. Alertes auto sur codes CRITIQUE :
   - `BOT4V2_ROUTER_BRACKET_NAKED` (capital exposé)
   - `BOT4V2_MAIN_KILL_SWITCH` (consecutive exceptions threshold)
   - `BOT4V2_SIERRA_CONNECT_FAIL` (DTC down)
   - `BOT4V2_RECONCILER_NAKED_FORCE_CLOSE` (force-close auto)

Throttle 60s par code (anti spam loop).

## Vérifications post-deploy J+1

| Item | Commande | Attendu |
|---|---|---|
| Service Running | `sc query MIA-Bot4V2-Sim4-Paper` | STATE = 4 RUNNING |
| Logs cross-cat | `Get-ChildItem LOGS\*\*_20260627_bot4v2.jsonl` | Files exist + size > 0 |
| Sentinel | `python tools/bot4v2_sentinel.py --date 20260627` | Status OK |
| Discord webhook | Test manuel POST | Channel reçoit ping |
| Trade Activity Log Sim4 | Sierra Chart GUI | Trades cohérents bot logs |

## Risques connus + mitigations

| Risque | Mitigation |
|---|---|
| Crash daily rollover 00:00 UTC (cf Bot 3 BN V4 #87) | nssm AppRotateBytes + auto-restart |
| GHOST positions (tracker TRIGGERED sans broker) | Backlog P6 (need IDTCBackend.get_open_positions extension) |
| Sim4 positions héritées Bot 4 v1 | **Pré-requis manuel flatten avant deploy** |
| Multi-instances même symbol | Anti-pyramiding RouterSettings.max_concurrent_trades=1 par symbol |

## Conditions GO / NO-GO Sim4

**GO** si :
- [ ] Flatten Sim4 manuel fait
- [ ] Service nssm installé + Started + RUNNING
- [ ] Sentinel J+1 status OK (pas VALIDATION_MISS)
- [ ] Discord webhook test ping reçu
- [ ] Bot logs `BOT4V2_MAIN_BOOT` émis cross-day

**NO-GO** si :
- [ ] Sim4 a positions résiduelles Bot 4 v1
- [ ] Service ne start pas (Python exception)
- [ ] Sentinel détecte VALIDATION_MISS (codes critiques manquants)
- [ ] `BOT4V2_ROUTER_BRACKET_NAKED` émit > 0 dans 24h (audit immédiat)

## Cross-references

- [INCIDENT_LOG #83](INCIDENT_LOG.md) : Refonte Bot 4 v2 décision souveraine
- [INCIDENT_LOG #87](INCIDENT_LOG.md) : Bot 3 BN V4 crashes daily rollover (leçon rotation logs)
- [INCIDENT_LOG #91](INCIDENT_LOG.md) : Sim5 → Sim4 CONTEXT_MISS
- `.claude/rules/orphan-prevention.md` : règles DTC strictes héritage
- `.claude/rules/critical-tasks-review.md` : règle souveraine TRACABILITE logs
