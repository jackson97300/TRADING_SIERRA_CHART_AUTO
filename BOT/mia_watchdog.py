#!/usr/bin/env python3
"""
MIA V2 - Watchdog Standalone
Script separe (lance en parallele du bot) qui surveille :
  1. Le processus bot (PID vivant ?)
  2. Le heartbeat.json (fresh ?)
  3. La connectivite DTC (champ dtc_connected dans heartbeat)

Si le bot crash ou freeze :
  - Alerte Discord immediate (< 30s)
  - Optionnel: auto-restart du bot (--auto-restart)

Repris et simplifie du V1 D:/MIA_IA_system/LAUNCH/mia_watchdog.py (481 lignes -> ~280 lignes).
Modifications V2 :
  - Utilise BOT/discord_alerter.py (12 webhooks)
  - Heartbeat dans DATA/HEARTBEAT/
  - Pas d'heures de trading hardcodees (24/7 par defaut)
  - Restart optionnel (pas le mode par defaut en sim3 — on veut savoir avant de relancer)

Usage:
    python BOT/mia_watchdog.py                     # monitor uniquement (pas de restart)
    python BOT/mia_watchdog.py --auto-restart      # monitor + auto-restart
    python BOT/mia_watchdog.py --interval 15       # check toutes les 15s
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Ajoute la racine projet au path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from BOT.discord_alerter import DiscordAlerter  # noqa: E402
from BOT.heartbeat_writer import (  # noqa: E402
    HEARTBEAT_FILE,
    PID_FILE,
    heartbeat_age_seconds,
    read_heartbeat,
    read_pid,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

BOT_SCRIPT = os.path.join(_ROOT, "BOT", "bot_main.py")
LOG_FILE = os.path.join(_ROOT, "DATA", "HEARTBEAT", "watchdog.log")

# Timeouts
HEARTBEAT_STALE_SECONDS = 120       # > 120s sans heartbeat = frozen
CHECK_INTERVAL_SECONDS = 30         # verif toutes les 30s
STARTUP_GRACE_SECONDS = 60          # 60s grace au demarrage

# Restart policy
MAX_RESTARTS_PER_HOUR = 3           # plus prudent que V1 (5) pour un bot de trading
RESTART_DELAY_BASE = 15
RESTART_DELAY_MAX = 300
RESTART_DELAY_MULT = 2


# ============================================================================
# LOGGER
# ============================================================================

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Systeme logs V2 (22/04/2026) : process="watchdog" dedie (review agent)
# pour grep temporel propre si bot_legacy silencieux pendant incident.
try:
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parent.parent))
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("mia_watchdog", process="watchdog")
except Exception:
    _v2log = None


# ============================================================================
# PROCESS MANAGEMENT
# ============================================================================

def is_process_running(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False


def kill_process(pid: int):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            if is_process_running(pid):
                os.kill(pid, signal.SIGKILL)
        logger.info(f"Kill PID {pid}")
        # V2 log : bot tue par watchdog (distinct BOT_SHUTDOWN qui est arret propre)
        if _v2log:
            _v2log.emit("BOT_KILLED_BY_WATCHDOG", pid=pid)
    except Exception as e:
        logger.error(f"Erreur kill: {e}")


def start_bot() -> Optional[subprocess.Popen]:
    try:
        logger.info(f"Demarrage bot: {BOT_SCRIPT}")
        proc = subprocess.Popen(
            [sys.executable, BOT_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=_ROOT,
        )
        logger.info(f"Bot demarre PID={proc.pid}")
        # V2 log : bot lance par watchdog
        if _v2log:
            _v2log.emit("BOOT_START", component="bot_legacy_via_watchdog",
                        version="V2", pid=proc.pid)
        return proc
    except Exception as e:
        logger.error(f"Erreur start_bot: {e}")
        if _v2log:
            _v2log.emit("BOT_CRASH", exc_type=e.__class__.__name__,
                        exc_msg=str(e)[:200], exc=e)
        return None


# ============================================================================
# WATCHDOG
# ============================================================================

class Watchdog:
    def __init__(self, auto_restart: bool = False, interval: int = CHECK_INTERVAL_SECONDS):
        self.auto_restart = auto_restart
        self.interval = interval
        self.alerter = DiscordAlerter()
        self.bot_process: Optional[subprocess.Popen] = None
        self.restart_count = 0
        self.restart_times: list = []
        self.current_delay = RESTART_DELAY_BASE
        self.last_startup: Optional[datetime] = None
        self.running = True
        self._last_alert_reason: Optional[str] = None

    def can_restart(self) -> bool:
        one_hour_ago = datetime.now() - timedelta(hours=1)
        self.restart_times = [t for t in self.restart_times if t > one_hour_ago]
        if len(self.restart_times) >= MAX_RESTARTS_PER_HOUR:
            logger.error(f"Limite restarts atteinte ({MAX_RESTARTS_PER_HOUR}/h)")
            # V2 log : CRITIQUE = Discord @here auto via LEVEL_ACTIONS
            # (remplace alerter.send_custom redondant — review agent R2)
            if _v2log:
                _v2log.emit("WATCHDOG_MAX_RESTARTS", limit=MAX_RESTARTS_PER_HOUR)
            return False
        return True

    def calculate_restart_delay(self) -> int:
        delay = min(self.current_delay, RESTART_DELAY_MAX)
        self.current_delay = min(self.current_delay * RESTART_DELAY_MULT, RESTART_DELAY_MAX)
        return delay

    def reset_restart_delay(self):
        self.current_delay = RESTART_DELAY_BASE

    def restart_bot(self, reason: str) -> bool:
        if not self.can_restart():
            return False
        if not self.auto_restart:
            logger.warning(f"Auto-restart desactive — pas de restart (reason={reason})")
            return False

        delay = self.calculate_restart_delay()
        self.restart_count += 1
        self.restart_times.append(datetime.now())
        logger.warning(f"Restart dans {delay}s — reason={reason}")
        # V2 log : MAJEUR (review agent : ALERTE trop bas — Discord auto obligatoire)
        if _v2log:
            _v2log.emit("WATCHDOG_RESTART", delay=delay, reason=reason)

        self.alerter.send_watchdog_restart(reason, self.restart_count)

        pid = read_pid()
        if pid and is_process_running(pid):
            kill_process(pid)
            time.sleep(2)

        time.sleep(delay)
        self.bot_process = start_bot()
        self.last_startup = datetime.now()
        return self.bot_process is not None

    def check_health(self) -> Tuple[bool, str]:
        pid = read_pid()
        if not pid:
            return False, "Aucun PID file"

        if not is_process_running(pid):
            # V2 log : CRITIQUE externe (bot n'a pas pu se declarer mort, cause inconnue)
            if _v2log:
                _v2log.emit("BOT_PROCESS_DEAD", pid=pid)
            return False, f"Processus {pid} mort"

        # Grace period au demarrage
        if self.last_startup:
            age = (datetime.now() - self.last_startup).total_seconds()
            if age < STARTUP_GRACE_SECONDS:
                return True, f"Grace period ({age:.0f}s)"

        age_s = heartbeat_age_seconds()
        if age_s is None:
            # V2 log : distinct de stale — fichier jamais ecrit
            if _v2log:
                _v2log.emit("BOT_HEARTBEAT_MISSING")
            return False, "Heartbeat absent"
        if age_s > HEARTBEAT_STALE_SECONDS:
            # V2 log : heartbeat stale avec pid + age pour correlation
            if _v2log:
                _v2log.emit("BOT_HEARTBEAT_STALE", pid=pid,
                            age=int(age_s), limit=HEARTBEAT_STALE_SECONDS)
            return False, f"Heartbeat stale ({age_s:.0f}s)"

        # Check DTC via heartbeat
        hb = read_heartbeat()
        if hb and hb.get("dtc_connected") is False:
            # V2 log : DTC deconnecte detecte via heartbeat bot
            if _v2log:
                _v2log.emit("DTC_DISCONNECT",
                            reason="detected_via_bot_heartbeat")
            return False, "DTC deconnecte (d'apres heartbeat)"

        return True, "OK"

    def run(self):
        logger.info("=" * 60)
        logger.info(f"MIA V2 WATCHDOG — auto_restart={self.auto_restart} interval={self.interval}s")
        logger.info("=" * 60)
        # V2 log : watchdog demarre
        if _v2log:
            _v2log.emit("WATCHDOG_START",
                        auto_restart=self.auto_restart, interval=self.interval)
        # Tracker debut incident pour calcul duration dans WATCHDOG_RECOVERED
        self._unhealthy_since: Optional[datetime] = None

        self.alerter.send_custom(
            "admin",
            "🐕 MIA V2 Watchdog demarre",
            f"Surveillance active. Heartbeat stale > {HEARTBEAT_STALE_SECONDS}s — check toutes les {self.interval}s",
            color=0x00C853,
        )

        # Si auto-restart ET pas de bot deja lance, on demarre
        if self.auto_restart and (read_pid() is None or not is_process_running(read_pid() or 0)):
            logger.info("Auto-restart: demarrage initial du bot")
            self.bot_process = start_bot()
            self.last_startup = datetime.now()

        stable_time = 0
        while self.running:
            try:
                time.sleep(self.interval)
                healthy, reason = self.check_health()

                if healthy:
                    stable_time += self.interval
                    if stable_time > 600 and self.current_delay != RESTART_DELAY_BASE:
                        self.reset_restart_delay()
                        stable_time = 0
                    if self._last_alert_reason is not None:
                        logger.info("Bot revenu en bonne sante — reset etat alerte")
                        # V2 log : recovery apres incident (duree calculee)
                        if _v2log:
                            duration = 0
                            if self._unhealthy_since:
                                duration = int((datetime.now() - self._unhealthy_since).total_seconds())
                            _v2log.emit("WATCHDOG_RECOVERED", duration=duration)
                            self._unhealthy_since = None
                        self._last_alert_reason = None
                    logger.debug(f"Healthy: {reason}")
                else:
                    stable_time = 0
                    logger.warning(f"Unhealthy: {reason}")
                    # Tracker debut incident pour duration recovery
                    if self._unhealthy_since is None:
                        self._unhealthy_since = datetime.now()

                    # Alerte Discord (une fois par raison, pas de spam)
                    if reason != self._last_alert_reason:
                        self.alerter.send_custom(
                            "alertes",
                            "⚠️ MIA V2 — Bot UNHEALTHY",
                            f"**Raison**: {reason}\n**Heure**: {datetime.now().strftime('%H:%M:%S')}",
                            color=0xD50000,
                        )
                        self._last_alert_reason = reason

                    if self.auto_restart:
                        self.restart_bot(reason)

            except KeyboardInterrupt:
                logger.info("Watchdog arrete par Ctrl+C")
                self.running = False
            except Exception as e:
                logger.error(f"Erreur watchdog: {e}", exc_info=True)
                # V2 log : exception watchdog non geree (crash watchdog != bot)
                if _v2log:
                    _v2log.emit("BOT_CRASH", exc_type=e.__class__.__name__,
                                exc_msg=f"WATCHDOG_LOOP: {str(e)[:180]}", exc=e)
                time.sleep(10)

        logger.info("Watchdog arret")
        # V2 log : arret propre watchdog (INFO distinct du kill bot)
        if _v2log:
            _v2log.emit("BOT_SHUTDOWN", reason="watchdog_loop_ended")
        self.alerter.send_custom(
            "admin",
            "🛑 MIA V2 Watchdog arrete",
            "Surveillance stoppee.",
            color=0x616161,
        )


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="MIA V2 Watchdog")
    parser.add_argument(
        "--auto-restart",
        action="store_true",
        help="Redemarre automatiquement le bot s'il crash/freeze",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CHECK_INTERVAL_SECONDS,
        help=f"Intervalle de check en secondes (defaut: {CHECK_INTERVAL_SECONDS})",
    )
    args = parser.parse_args()

    wd = Watchdog(auto_restart=args.auto_restart, interval=args.interval)
    wd.run()


if __name__ == "__main__":
    main()
