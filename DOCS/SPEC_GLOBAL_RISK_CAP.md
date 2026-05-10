# SPEC — GlobalRiskCap (anti-Topstep DLL breach)

**Date** : 2026-05-11
**Phase** : 0.3.e (PRE-REQUIS Phase 1)
**Auteur** : Claude (orchestrateur)
**Source** : verdict code-reviewer Phase 0.2 (issue : 3 bots = 3 cap individuels $500 -> $1500 max loss possible vs Topstep DLL $1000)

---

## Problème

**Actuel** :
- Bot 1 (mia_paper_trader.py) : RiskManager cap $500/jour, process A
- Bot 2 (databento_paper_trader_v2.py) : cap $500/jour, process B
- Bot 3 (databento_paper_trader_v2.py partie Bot 3) : cap $500/jour, process B (partagé Bot 2)

**Risque** : Bot 1 perd -$500 + Bot 2 perd -$500 + Bot 3 perd -$500 = **-$1500 total**, mais Topstep DLL = **$1000**. Breach garanti.

**Note** : c'est un risque DEJA présent avec ES+NQ. L'arrivée de MGC l'accentue (3 sym actifs × 3 bots = exposure plus grande) mais ne le cree pas.

---

## Contraintes architecturales

1. **Process boundaries** : Bot 1 et Bot 2/3 sont des PROCESS SEPARES (mia_paper_trader.py vs databento_paper_trader_v2.py). Singleton Python en mémoire ne traverse pas.
2. **TradeAccount séparés** :
   - Bot 1 = Sim3 (paper Topstep)
   - Bot 2 = Sim2 (paper Topstep)
   - Bot 3 = Sim1 (paper Topstep)
3. **Topstep DLL** : trailing daily depending on funded vs combine. Pour simplicité : assumer $1000 hard cap journalier (worst case).
4. **Fail-safe** : si GlobalRiskCap fails (file lock timeout, broker query fail), bot doit s'arrêter (fail-closed, pas fail-open).

---

## 3 options évaluées

### Option A — Shared File JSON avec lock OS

**Architecture** :
- Fichier : `DATA/RISK/global_risk_state.json`
- Format :
  ```json
  {
    "session_date": "2026-05-11",
    "daily_pnl_by_bot": {"bot1": -250.0, "bot2": -180.0, "bot3": +50.0},
    "daily_pnl_global": -380.0,
    "kill_switch_triggered": false,
    "kill_switch_reason": null,
    "last_update": "2026-05-11T14:32:15Z"
  }
  ```
- Lock : `portalocker` (cross-platform Python) ou `msvcrt.locking` (Windows-only) ou flock (Linux-only)
- Chaque bot : `acquire_lock → read state → update its bot pnl → recompute global → write → release_lock` à chaque trade close
- Kill switch : si `daily_pnl_global < -$800` (marge sous Topstep DLL $1000) → set `kill_switch_triggered=true` → tous les bots arrêtent leurs nouvelles entrées

**Pros** :
- Simple à implémenter (~50 LOC)
- File-based = visible humainement, debug facile
- Pas de dépendance réseau / broker
- Traverse process boundaries via OS filesystem

**Cons** :
- Latence file I/O (~5-50ms par read/write)
- File corruption possible si lock fail (mais rare avec portalocker)
- Source de vérité = PnL SIMULE par bot, pas broker réel

### Option B — Query DTC P&L Broker

**Architecture** :
- Chaque bot, à chaque cycle (~30s) : query Sierra Chart DTC `OPEN_POSITIONS_REQUEST` pour son TradeAccount
- Aggrégat les 3 réponses : sum |pnl_realized| trades du jour
- Kill switch si cumul > $800

**Pros** :
- Source de vérité = broker réel (pas simulé)
- Pas de file lock à gérer
- Reflète Topstep DLL "réelle"

**Cons** :
- DTC query toutes les 30s × 3 bots = surcharge SC (mais Type 300 supportable)
- Latence broker query (~100-500ms)
- Si DTC down → comment fail-safe ?
- Complexité (parsing P&L response)
- Bot 1 / Bot 2 / Bot 3 doivent CHACUN query (ou un service tiers)

### Option C — Service tiers GlobalRiskMonitor

**Architecture** :
- Nouveau service nssm `MIA-GlobalRiskMonitor`
- Poll DTC toutes 30s pour tous TradeAccounts (Sim1, Sim2, Sim3)
- Écrit `DATA/RISK/global_risk_state.json` (read-only pour les bots)
- Bots lisent le fichier (pas de lock car read-only)
- Si kill switch déclenché → fichier marker `DATA/BOT_CONTROL/STOP_ALL.flag` créé → bots stop

**Pros** :
- Séparation des responsabilités (Risk service vs bots)
- Bots simplifiés (juste read JSON)
- Source de vérité broker
- Pas de file lock (un seul écrivain)

**Cons** :
- Nouvelle infra (service + nssm registration + monitoring)
- 4ème process à gérer (Bot 1, 2, 3, Risk)
- Latence entre detection breach et propagation kill (poll 30s)
- Complexité dev (~3-4h)

---

## Recommandation

**Option A — Shared File JSON** pour Phase 1.5

**Pourquoi** :
1. **Simplicité** : 50 LOC, déployable en 2h, debug aisé
2. **Process boundaries** : résout le problème principal (Bot 1 vs Bot 2/3)
3. **Pas de nouvelle infra** : pas de service tiers à monitor
4. **PnL simulé acceptable** : les bots SAVENT déjà leur PnL simulé (tracking interne), pas besoin de query broker
5. **Topstep margin** : $800 cap interne avec DLL $1000 broker = 20% marge pour latence/edge cases
6. **Réversible** : si Option A insuffisante, on évolue vers Option C plus tard sans casser l'API

**Risque résiduel** :
- PnL simulé != PnL broker exactement (slippage non capturé, mais on est en paper Sim donc slippage = 0 généralement)
- File lock contention si 3 bots écrivent en même temps : utiliser `portalocker` avec timeout 5s → fail-closed si timeout

---

## API proposée

```python
# CORE/global_risk_cap.py

import json
import time
from pathlib import Path
import portalocker  # pip install portalocker

STATE_FILE = Path("DATA/RISK/global_risk_state.json")
KILL_FLAG = Path("DATA/BOT_CONTROL/STOP_ALL.flag")
DLL_CAP_USD = 800.0  # marge 20% sous Topstep DLL $1000
LOCK_TIMEOUT_SEC = 5.0


def update_bot_pnl(bot_id: str, daily_pnl: float, *, fail_closed: bool = True) -> dict:
    """Update le PnL d'un bot dans le state global. Retourne le state apres update.

    Args:
        bot_id : 'bot1' | 'bot2' | 'bot3'
        daily_pnl : PnL journalier du bot (USD)
        fail_closed : si True, raise ValueError en cas de lock timeout (default: True)

    Returns:
        dict du state global apres update.

    Raises:
        TimeoutError : si lock timeout ET fail_closed=True
        RuntimeError : si kill switch deja triggered (bot doit pause)
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({
            "session_date": time.strftime("%Y-%m-%d"),
            "daily_pnl_by_bot": {"bot1": 0.0, "bot2": 0.0, "bot3": 0.0},
            "daily_pnl_global": 0.0,
            "kill_switch_triggered": False,
            "kill_switch_reason": None,
            "last_update": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }))

    try:
        with portalocker.Lock(str(STATE_FILE), mode="r+", timeout=LOCK_TIMEOUT_SEC) as fh:
            state = json.load(fh)

            # Daily rollover
            today = time.strftime("%Y-%m-%d")
            if state.get("session_date") != today:
                state = {
                    "session_date": today,
                    "daily_pnl_by_bot": {"bot1": 0.0, "bot2": 0.0, "bot3": 0.0},
                    "daily_pnl_global": 0.0,
                    "kill_switch_triggered": False,
                    "kill_switch_reason": None,
                }

            state["daily_pnl_by_bot"][bot_id] = daily_pnl
            state["daily_pnl_global"] = sum(state["daily_pnl_by_bot"].values())
            state["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Kill switch check
            if state["daily_pnl_global"] < -DLL_CAP_USD and not state["kill_switch_triggered"]:
                state["kill_switch_triggered"] = True
                state["kill_switch_reason"] = (
                    f"Global DLL cap ${DLL_CAP_USD} breached: "
                    f"${state['daily_pnl_global']:.2f}"
                )
                KILL_FLAG.parent.mkdir(parents=True, exist_ok=True)
                KILL_FLAG.write_text(state["kill_switch_reason"])

            fh.seek(0)
            fh.truncate()
            json.dump(state, fh, indent=2)

        if state["kill_switch_triggered"]:
            raise RuntimeError(state["kill_switch_reason"])

        return state

    except portalocker.LockException:
        if fail_closed:
            raise TimeoutError(f"GlobalRiskCap lock timeout ({LOCK_TIMEOUT_SEC}s)")
        return {}


def is_kill_switch_active() -> tuple[bool, str]:
    """Read-only check sans lock. Retourne (active, reason)."""
    if KILL_FLAG.exists():
        return True, KILL_FLAG.read_text()
    return False, ""


def reset_session():
    """Reset le state pour nouvelle session (appele par cron 00:00 ET ou bot start)."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    if KILL_FLAG.exists():
        KILL_FLAG.unlink()
```

---

## Integration dans les 3 bots

### Bot 1 (mia_paper_trader.py)

```python
from CORE.global_risk_cap import update_bot_pnl, is_kill_switch_active

# Au début de chaque cycle poll (avant check entry signals)
kill_active, reason = is_kill_switch_active()
if kill_active:
    _emit("BOT1_GLOBAL_KILL_SWITCH_ACTIVE", reason=reason)
    return  # Skip entry processing

# Apres chaque trade close
try:
    state = update_bot_pnl("bot1", self.daily_pnl_usd)
    if state["kill_switch_triggered"]:
        _emit("BOT1_TRIGGER_GLOBAL_KILL", reason=state["kill_switch_reason"])
except RuntimeError as e:
    # Kill switch deja active par un autre bot
    _emit("BOT1_BLOCKED_BY_KILL", reason=str(e))
```

### Bot 2 + Bot 3 (databento_paper_trader_v2.py)

Idem mais avec `bot_id="bot2"` ou `bot_id="bot3"`.

---

## Tests

### Test 1 : 3 bots independants, pnl cumule
```python
update_bot_pnl("bot1", -300.0)
update_bot_pnl("bot2", -300.0)
state = update_bot_pnl("bot3", -300.0)
# Expected : kill_switch_triggered=True (total -900 < -800)
```

### Test 2 : lock contention
Simuler 3 bots qui ecrivent en parallele -> verifier qu'aucun update n'est perdu.

### Test 3 : daily rollover
Set session_date='2026-05-10', update -> verify reset to today.

### Test 4 : fail-closed timeout
Holder lock 10s -> update_bot_pnl -> verify TimeoutError raised.

---

## Decisions ouvertes Jackson

1. **Cap DLL** : $800 OK (20% marge) ou autre valeur ?
2. **bot_id naming** : bot1/bot2/bot3 ou plus explicite (mia_paper / databento_v2_bot2 / databento_v2_bot3) ?
3. **Reset session** : cron 00:00 ET automatic OU au boot de chaque bot (premier update apres date change) ?
4. **Kill flag** : faut-il aussi tuer les positions ouvertes (flatten) ou juste bloquer les nouvelles entrees ?
   - Reco : juste bloquer nouvelles entrees, laisser positions actuelles courir vers TP/SL (eviter cascade flatten)
5. **Activation** : avant ou apres activation MGC (Phase 1.8) ?
   - Reco : AVANT MGC. Le cap est utile dès aujourd'hui ES+NQ (risque existant).

---

## Plan d'execution

**Phase 1.5.a — Implementation core** (~2h)
1. Ecrire `CORE/global_risk_cap.py`
2. Tests pytest 4 scenarios
3. Review code-reviewer
4. Commit

**Phase 1.5.b — Integration Bot 2/3** (~1h)
1. Hook dans databento_paper_trader_v2.py (Bot 2 + Bot 3)
2. Tests intégration
3. Deploy VPS (sans restart car bots tournent — restart fin de session US)

**Phase 1.5.c — Integration Bot 1** (~1h)
1. Hook dans mia_paper_trader.py
2. Tests intégration
3. Deploy VPS + restart Bot 1 (en fin de session US)

**Phase 1.5.d — Validation production** (~24h observation)
1. Cron 00:00 ET reset state (ou check au boot)
2. J+1 grep logs pour confirmer events `*_GLOBAL_KILL_SWITCH_*` n'apparaissent pas en faux positif
3. Stress test : forcer breach simulé pour valider kill flag propagation
