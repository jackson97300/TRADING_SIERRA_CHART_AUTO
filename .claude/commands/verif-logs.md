Verifie les logs MIA V2 — resume protocol debug (QUOI / OU / POURQUOI).

Protocol `.claude/rules/log-debug-protocol.md` applique automatiquement :
  1. errors/   — derniers MAJEUR+CRITIQUE (priorite)
  2. events/   — transitions systeme (boot/session/heartbeat/crash)
  3. decisions/ — GATE_*_BLOCK count (pourquoi aucun trade ?)
  4. Trace signal_id cross-categories si specifie

## Usage

Forme base :
  /verif-logs              — recap 24h standard
  /verif-logs 6h           — recap 6 dernieres heures
  /verif-logs process=v2clean   — filtrer par process
  /verif-logs process=bot_legacy
  /verif-logs process=watchdog
  /verif-logs signal_id=abc123ef  — trace complete d'un signal cross-cat
  /verif-logs cat=trading         — focus sur une categorie

## Etapes executees

1. Lancer `python -X utf8 -m CORE.logs_summary [--hours N] [--process X] [--signal_id Y] [--category Z]`
2. Parser le stdout du script (format texte structure)
3. Format reponse Jackson en 3 sections :
   - **QUOI cloche** (derniers errors + pattern)
   - **OU** (categories concernees + process + timing)
   - **POURQUOI** (cause racine via ctx + correlation signal_id si applicable)

## Comportement sans arguments

Defaut : `--hours 24` toutes categories + tous process.
Jackson voit immediatement :
- Top 10 errors (MAJEUR+CRITIQUE)
- Count par niveau (CRITIQUE/MAJEUR/ALERTE/INFO)
- Derniers events systeme (boot, session, crash)
- Gates blocks si applicable
- Top codes par categorie trading/risk/execution/ml

## Format reponse Jackson

Si erreurs trouvees :
```
## QUOI cloche
{code1} : {msg_fr1} (N occurrences)
{code2} : {msg_fr2} (M occurrences)

## OU
Categorie : {cat}
Process : {host_process}
Premier vu : {ts}

## POURQUOI
Cause racine : {analyse ctx + trace}
Pattern : {une fois / recurrent / cascade}
Fix recommande : {action precise}
```

Si aucune erreur :
```
Systeme OK derniere {N}h.
- X transitions normales
- Y trades executes
- Z signaux (tops codes)
```

## Anti-patterns interdits

- Ne PAS lire 30j de logs dans contexte Claude (overflow)
- Utiliser `code` stable pour diagnostic (pas prose fr)
- Toujours consulter errors/ EN PREMIER avant hypotheses
- Si Jackson dit "pourquoi X" sans plus de detail : lancer `/verif-logs 6h` + chercher pattern

## Extension future (reporte)

- Agent log-analyzer dedie pour diagnostics ouverts complexes
- Correlation automatique avec DISCORD webhooks history
- Export PDF hebdomadaire pour audit trail
