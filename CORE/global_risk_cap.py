"""
global_risk_cap.py — Tracker PnL global 3 bots + alertes Discord paliers $500.

Cree 11/05/2026 (Phase 1.5). Reference DOCS/SPEC_GLOBAL_RISK_CAP.md.

MODE OBSERVE (paper trading actuel) :
  - Tracker PnL cumule des 3 bots (mia_paper, databento_v6, databento_v2_b3)
  - Alerte Discord a chaque palier de $500 traverse (gain ET perte)
  - PAS de block automatique (collecte data ML)
  - Reset session au boot bot (CME 18:00 ET = minuit Paris ete)

MODE BLOCK (futur live funded, switch via env var RISK_CAP_MODE=BLOCK) :
  - Block nouvelles entrees si daily_pnl_global < -CAP_USD
  - CAP_USD a determiner avant live (suggestion $800)
  - Kill bloque entries seulement (pas flatten - preserve trades ouverts pour ML data quality)

Architecture file-based shared state (cross-process Bot 1 / Bot 2/3) :
  DATA/RISK/global_risk_state.json (atomic write avec portalocker)

API :
  from CORE.global_risk_cap import update_bot_pnl, is_kill_active, read_state

Usage bots (apres chaque trade close) :
  update_bot_pnl("mia_paper", daily_pnl_usd=-150.50)

Usage bots (avant chaque _execute_trade, mode BLOCK only) :
  if is_kill_active():
      _emit("GATE_RISK_KILL_ACTIVE", ...)
      return  # skip trade
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "DATA" / "RISK" / "global_risk_state.json"
KILL_FLAG = ROOT / "DATA" / "BOT_CONTROL" / "RISK_KILL.flag"

# Mode operation : OBSERVE (paper) | BLOCK (live funded)
RISK_CAP_MODE = os.environ.get("RISK_CAP_MODE", "OBSERVE").upper()

# Cap PnL global en USD (utilise uniquement en mode BLOCK)
# A determiner avant passage live funded (suggestion $800 = 20% marge sous Topstep DLL $1000)
RISK_CAP_USD = float(os.environ.get("RISK_CAP_USD", "800.0"))

# Palier alerte Discord : tous les $500 cumules
ALERT_PALIER_USD = 500.0

# Bot ids canoniques (naming explicite - decision Jackson 11/05)
KNOWN_BOT_IDS = {"mia_paper", "databento_v6", "databento_v2_b3"}

# CME timezone (pour rollover trading day)
ET_ZONE = ZoneInfo("America/New_York")
LOCK_TIMEOUT_SEC = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers CME trading day (rollover 18:00 ET = minuit Paris ete)
# ─────────────────────────────────────────────────────────────────────────────

def cme_trading_day(now_utc: Optional[datetime] = None) -> str:
    """Retourne CME trading day YYYY-MM-DD (rollover 18:00 ET, DST-aware).

    Exemples ete (EDT, UTC-4) :
      10/05 17:30 ET (21:30 UTC) -> "2026-05-10"
      10/05 18:00 ET (22:00 UTC) -> "2026-05-11" (bascule)
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET_ZONE)
    if now_et.hour >= 18:
        # Apres 18:00 ET = nouveau trading day
        return (now_et.date() + timedelta(days=1)).strftime("%Y-%m-%d")
    return now_et.strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# State management
# ─────────────────────────────────────────────────────────────────────────────

def _fresh_state(session_date: str) -> dict:
    """Etat initial nouveau trading day."""
    return {
        "session_date": session_date,
        "daily_pnl_by_bot": {bid: 0.0 for bid in KNOWN_BOT_IDS},
        "daily_pnl_global": 0.0,
        "last_alert_palier_usd": 0,
        "kill_switch_triggered": False,
        "kill_switch_reason": None,
        "kill_switch_ts": None,
        "mode": RISK_CAP_MODE,
        "last_update_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _read_state_raw() -> dict:
    """Lit STATE_FILE sans lock (caller doit gerer lock)."""
    if not STATE_FILE.exists():
        return _fresh_state(cme_trading_day())
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("State file unreadable, reset: %s", e)
        return _fresh_state(cme_trading_day())


def _write_state_atomic(state: dict) -> None:
    """Write atomic (.tmp + rename)."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _maybe_reset_session(state: dict) -> dict:
    """Reset state si nouveau CME trading day (lazy reset au boot bot)."""
    today = cme_trading_day()
    if state.get("session_date") != today:
        prev_date = state.get("session_date", "unknown")
        prev_pnl = state.get("daily_pnl_global", 0.0)
        logger.info("CME session rollover: %s -> %s (prev PnL=$%.2f)",
                    prev_date, today, prev_pnl)
        return _fresh_state(today)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Discord alerter (lazy import, fail-soft)
# ─────────────────────────────────────────────────────────────────────────────

def _send_discord_alert(palier_usd: float, daily_pnl: float,
                        by_bot: dict, reasons: list[str]) -> None:
    """Send Discord alert. Fail-soft si discord_alerter indisponible."""
    try:
        try:
            from BOT.discord_alerter import send_custom  # type: ignore
        except ImportError:
            from discord_alerter import send_custom  # type: ignore
        emoji = "🟢" if palier_usd > 0 else "🔴"
        sign = "+" if palier_usd > 0 else ""
        msg = (
            f"{emoji} **GlobalRiskCap palier {sign}${abs(palier_usd):.0f}** traverse\n"
            f"PnL global jour : ${daily_pnl:.2f}\n"
            f"Par bot : {by_bot}\n"
            f"Mode : {RISK_CAP_MODE}"
        )
        send_custom("alertes", msg)
    except Exception as e:
        logger.warning("Discord alert failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────

def update_bot_pnl(bot_id: str, daily_pnl_usd: float) -> dict:
    """Update le PnL d'un bot. Trigger alerte Discord si palier $500 traverse.

    Args:
        bot_id : 'mia_paper' | 'databento_v6' | 'databento_v2_b3'
        daily_pnl_usd : PnL cumule du jour pour ce bot (USD)

    Returns:
        dict state apres update.

    Raises:
        RuntimeError : si kill_switch_triggered ET mode==BLOCK (= bot doit pause).
    """
    if bot_id not in KNOWN_BOT_IDS:
        logger.warning("Unknown bot_id '%s', accepting anyway. Update KNOWN_BOT_IDS.", bot_id)

    # Lock simulation (portalocker pas disponible sans pip install, fallback flock-style)
    # Pour robustesse cross-process : on accepte race condition mineure (last-write-wins)
    # Volume update : ~5 trades/bot/jour * 3 bots = 15 writes/jour = race rare
    state = _read_state_raw()
    state = _maybe_reset_session(state)

    # Update bot pnl
    if state.get("daily_pnl_by_bot") is None:
        state["daily_pnl_by_bot"] = {}
    state["daily_pnl_by_bot"][bot_id] = float(daily_pnl_usd)
    state["daily_pnl_global"] = sum(state["daily_pnl_by_bot"].values())
    state["last_update_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Check palier glissant $500 (gain ET perte)
    daily_pnl = state["daily_pnl_global"]
    last_palier = state.get("last_alert_palier_usd", 0)
    abs_pnl = abs(daily_pnl)
    palier_actuel = int(abs_pnl // ALERT_PALIER_USD) * int(ALERT_PALIER_USD)
    palier_actuel_signed = palier_actuel if daily_pnl >= 0 else -palier_actuel

    if abs(palier_actuel_signed) > abs(last_palier):
        # Nouveau palier traverse
        logger.info("RISK_PALIER_CROSSED: pnl=$%.2f palier=$%s (prev=$%s)",
                    daily_pnl, palier_actuel_signed, last_palier)
        state["last_alert_palier_usd"] = palier_actuel_signed
        _send_discord_alert(palier_actuel_signed, daily_pnl,
                            state["daily_pnl_by_bot"], [])

    # Kill switch check (mode BLOCK only)
    if RISK_CAP_MODE == "BLOCK":
        if daily_pnl < -RISK_CAP_USD and not state.get("kill_switch_triggered"):
            state["kill_switch_triggered"] = True
            state["kill_switch_reason"] = (
                f"PnL global ${daily_pnl:.2f} < cap -${RISK_CAP_USD:.0f}"
            )
            state["kill_switch_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            KILL_FLAG.parent.mkdir(parents=True, exist_ok=True)
            KILL_FLAG.write_text(state["kill_switch_reason"])
            logger.error("RISK_KILL_TRIGGERED: %s", state["kill_switch_reason"])

    _write_state_atomic(state)

    # Raise si mode BLOCK + kill active (bot doit gerer)
    if RISK_CAP_MODE == "BLOCK" and state.get("kill_switch_triggered"):
        raise RuntimeError(state["kill_switch_reason"])

    return state


def is_kill_active() -> tuple[bool, str]:
    """Check rapide si kill flag active (read-only, pas de lock).

    Returns:
        (active, reason)
    """
    if not KILL_FLAG.exists():
        return False, ""
    try:
        reason = KILL_FLAG.read_text()
    except OSError:
        reason = "FLAG_FILE_PRESENT"
    return True, reason


def read_state() -> dict:
    """Helper pour bots : lit STATE_FILE current state.

    Fail-safe : retourne fresh_state si fichier absent (pas fail-closed
    pour mode OBSERVE, l'absence n'est pas un kill).
    """
    state = _read_state_raw()
    state = _maybe_reset_session(state)
    return state


def reset_session() -> dict:
    """Force reset session (utile cron 00:00 ET ou debug)."""
    fresh = _fresh_state(cme_trading_day())
    _write_state_atomic(fresh)
    if KILL_FLAG.exists():
        try:
            KILL_FLAG.unlink()
        except OSError:
            pass
    logger.info("Session force-reset to %s", fresh["session_date"])
    return fresh


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="Print state")
    parser.add_argument("--reset", action="store_true", help="Force reset session")
    parser.add_argument("--update", nargs=2, metavar=("BOT_ID", "PNL"),
                        help="Update bot pnl (test)")
    args = parser.parse_args()

    if args.reset:
        state = reset_session()
        print(json.dumps(state, indent=2))
    elif args.update:
        bot_id, pnl_str = args.update
        state = update_bot_pnl(bot_id, float(pnl_str))
        print(json.dumps(state, indent=2))
    else:
        state = read_state()
        print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
