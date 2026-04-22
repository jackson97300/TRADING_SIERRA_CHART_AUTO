# Regle — Protocole debug via logs MIA V2

**Date** : 2026-04-22
**Source** : Jackson directive "systeme logs pro et pertinent, savoir ou chercher"

## Regle souveraine

**Quand Jackson dit "verifie les logs" / "pourquoi ca cloche" / "qu'est-ce qui se passe"**, appliquer le protocole ordonne ci-dessous AVANT toute hypothese.

## Ordre de consultation (4 etapes)

### Etape 1 — Errors file (30 sec)

```bash
ls -la LOGS/errors/errors_{YYYYMMDD}_*.jsonl
cat LOGS/errors/errors_{YYYYMMDD}_*.jsonl | jq -s 'sort_by(.ts) | reverse | .[:10]'
```

Lit les 10 derniers events niveau MAJEUR+CRITIQUE tous processes confondus.
Si vide → pas d'erreur fatale aujourd'hui, passer Etape 2.
Si plein → analyser les `code` + `msg_fr` → formuler diagnostic.

### Etape 2 — Events file (transitions systeme)

```bash
tail -50 LOGS/events/events_{YYYYMMDD}_*.jsonl
```

Regarder :
- `BOOT_START`, `BOOT_READY`, `BOOT_FAIL_PREFLIGHT`
- `SESSION_OPEN`, `SESSION_CLOSE`, `SESSION_FLATTEN_WINDOW`
- `HEARTBEAT_V2CLEAN_*` (stale/down/zombie)
- `BOT_SHUTDOWN`, `BOT_CRASH`
- `DLL_RELOAD`, `DTC_DISCONNECT*`

Si pattern de `HEARTBEAT_V2CLEAN_DOWN` → V2CLEAN process mort, bot en attente.
Si pattern de `BOT_CRASH` → stacktrace dans `ctx.trace`.

### Etape 3 — Decisions file (chain of gates)

```bash
tail -100 LOGS/decisions/decisions_{YYYYMMDD}_*.jsonl | jq 'select(.code|startswith("GATE_"))'
```

Compter les blocks par gate :
- `GATE_HEALTH_BLOCK` : V2CLEAN zombie → corriger cote Python cerveau
- `GATE_SESSION_BLOCK` : hors session (Asia/London skip valide ou pre-RTH)
- `GATE_RISK_BLOCK` : kill-switch OR ATR OR cooldown OR exposure

Si Jackson demande "pourquoi aucun trade aujourd'hui" → compter les GATE_*_BLOCK par categorie.

### Etape 4 — Suivre un signal_id (diagnostic trade specifique)

```bash
grep "signal_id.*abc123" LOGS/**/*_{YYYYMMDD}_*.jsonl
```

Affiche TOUT le cycle de vie du signal cross-categories (trading → decisions → execution → trading TRADE_CLOSE).

Si pas de `TRADE_OPEN` apres `SIGNAL_RECEIVED` → regarder `decisions/` pour voir quel gate a bloque.
Si `ORDER_REJECT` broker → `execution/` pour cause exacte.

## Commandes de diagnostic communes

### "Pourquoi aucun trade aujourd'hui ?"
```bash
# Count signals recus
grep -c "SIGNAL_RECEIVED" LOGS/trading/trading_{YYYYMMDD}_*.jsonl

# Count gates blocks par type
grep "GATE_.*_BLOCK" LOGS/decisions/decisions_{YYYYMMDD}_*.jsonl | jq .code | sort | uniq -c

# Count kills
grep -c "KILL_" LOGS/risk/risk_{YYYYMMDD}_*.jsonl
```

### "Slippage eleve ce matin ?"
```bash
grep "ORDER_FILL" LOGS/execution/execution_{YYYYMMDD}_*.jsonl | jq '.ctx.slip' | sort -n | tail -20
```

### "Bot plante ?"
```bash
grep -E "BOT_CRASH|BOT_SHUTDOWN" LOGS/events/events_{YYYYMMDD}_*.jsonl | tail -5
```

### "Meta : qu'est-ce qui s'est passe hier 14h-15h ?"
```bash
cat LOGS/errors/errors_{YYYYMMDD}_*.jsonl | jq 'select(.ts >= "2026-04-22T14:00:00Z" and .ts <= "2026-04-22T15:00:00Z")'
```

## Interpretation par niveau

| Niveau | Signification Jackson | Action Claude |
|---|---|---|
| CRITIQUE | Truc grave, arrete tout | Lire ctx complet, stack trace, proposer fix immediat |
| MAJEUR | Probleme persistant a traiter | Analyser pattern, compter occurrences, recommander |
| ALERTE | Anomalie tracable, pas urgente | Noter dans summary, tracker si recurrent |
| INFO | Normal, bot fonctionne | Ignorer sauf si demande explicite |

## Anti-patterns interdits

- ❌ Lire 30j de logs dans le contexte Claude (overflow garanti)
- ❌ Chercher sans categorie + date precise
- ❌ Ignorer `.code` stable, se baser sur prose fr variable
- ❌ Diagnostiquer sans consulter `errors/` en premier
- ❌ Proposer fix sans avoir lu le `msg_fr` + `ctx`

## Format reponse a Jackson

Apres diagnostic, repondre en 3 sections :

```
## QUOI cloche
{code} : {msg_fr} (N occurrences aujourd'hui)

## OU
Categorie : {cat}
Process : {host_process}
Premier vu : {ts}

## POURQUOI
Cause racine : {analyse du ctx + trace si applicable}
Pattern : {une fois / recurrent / cascade}
Fix recommande : {action precise}
```

## Fichiers-cles pour cette regle

- `CORE/log_catalog.py` : catalogue codes (mettre a jour au fur et a mesure)
- `CORE/logging_v2.py` : module central
- `LOGS/README.md` : structure + convention nommage
- Memory `feedback_log_debug_protocol.md` : pattern anti-oubli

## Enforcement

Si Jackson dit "INCIDENT_LOG !" et qu'on a neglige les logs lors d'un diagnostic :
1. Documenter incident categorie `CONTEXT_MISS`
2. Categorie va incrementer le compteur
3. A 3+ occurrences, promouvoir memoire dediee
