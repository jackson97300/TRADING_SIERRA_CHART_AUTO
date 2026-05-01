#!/usr/bin/env python3
"""
MIA V2 — Watchdog data freshness multi-source (01/05/2026, v2 post-review)

Surveille en continu la fraicheur des donnees produites par les composants
critiques de l'ecosysteme MIA. Sur stale CRITICAL : Discord + Restart-Service.

Sources surveillees :
  1. V2CLEAN bot (cerveau Python)         via V2CLEAN/logs/heartbeat.txt (json ts_utc)
  2. Databento stream (live OHLCV)        via DATA/LOGS/databento_live_stream.log (mtime)
  3. Bot 1 Sierra (mia_paper_trader)      via LOGS/events/events_*_paper.jsonl (mtime, regex strict)
  4. Bot 2 Databento (databento_paper)    via last_bar_age dans BOT_HEARTBEAT events
  5. DMP C++ JSONL ES + NQ                via DATA/{ES,NQ}/YYYYMMDD_*.jsonl (mtime)
  6. Live pipeline                        via LOGS/live_pipeline_loop.log (mtime)

Actions par niveau :
  - WARN  : Discord webhook (dedup 15 min)
  - CRIT  : Discord webhook + Restart-Service <nom_service> (cap 3/heure/service persistant)

Heartbeat sortant Discord toutes les 10 min :
  - Color VERT si tout OK, ORANGE si WARN, ROUGE si CRIT/ABSENT
  - Channel "admin" si OK, "alertes" sinon
  - Silence Discord = watchdog mort = a investiguer

Reecriture 01/05/2026 (cause incident V2CLEAN zombie 33h sans alerte).
v2 : 3 bugs critiques + 6 reserves code-reviewer corriges.

Usage:
    python BOT/mia_watchdog.py                      # mode normal (auto-restart actif)
    python BOT/mia_watchdog.py --no-restart         # alerte seule (debug)
    python BOT/mia_watchdog.py --interval 30        # check toutes les 30s
    python BOT/mia_watchdog.py --dry-run            # parse mais n'envoie pas Discord

Service nssm :
    nssm install MIA-Watchdog "C:\\Program Files\\Python311\\python.exe" "BOT\\mia_watchdog.py"
    nssm set MIA-Watchdog AppDirectory "C:\\TRADING_SIERRA_CHART_AUTO"
    Start-Service MIA-Watchdog
"""

import argparse
import glob
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Ajoute racine projet au path
_THIS_DIR = Path(__file__).resolve().parent
ROOT = _THIS_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from BOT.discord_alerter import DiscordAlerter  # noqa: E402

# ============================================================================
# CONFIGURATION
# ============================================================================

LOOP_INTERVAL_SEC = 60                  # check loop period
HEARTBEAT_INTERVAL_MIN = 10             # Discord heartbeat positif
DEDUP_ALERT_MIN = 15                    # ne pas re-alerter meme reason avant
DEDUP_FLAG_STALE_MIN = 60               # alerte FLAG_STALE redonnee toutes les 60 min max
MAX_RESTART_PER_HOUR = 3                # par service (anti-loop)
ABSENT_TO_CRIT_STREAK = 5               # apres N checks ABSENT consec → CRIT
PAUSE_FLAG_STALE_MIN = 30               # flag actif > 30 min = alerte FLAG_STALE
RESTART_SERVICE_TIMEOUT_SEC = 120       # bump 60→120 (V2CLEAN met ~30s a stopper)

LOG_FILE = ROOT / "DATA" / "HEARTBEAT" / "watchdog_v2.log"
RESTART_HISTORY_FILE = ROOT / "DATA" / "HEARTBEAT" / "watchdog_restart_history.json"
EVENTS_LOG_DIR = ROOT / "LOGS" / "events"  # JSONL structure compatible bots

# Sources surveillees (declarative pour facilite test/extension)
SOURCES = [
    {
        "name": "V2CLEAN_brain",
        "type": "json_ts_utc",
        "path": str(ROOT / "V2CLEAN" / "logs" / "heartbeat.txt"),
        "ts_field": "ts_utc",
        "warn_age_s": 180,      # 3 min
        "crit_age_s": 600,      # 10 min
        "service": "MIA-V2CLEAN-Bot",
        # Pause optionnelle (Jackson peut creer ce flag pour debug sans alerte)
        "pause_grace_path": str(ROOT / "DATA" / "BOT_CONTROL" / "V2CLEAN_PAUSE.flag"),
    },
    {
        "name": "Databento_stream",
        "type": "file_mtime",
        "path": str(ROOT / "DATA" / "LOGS" / "databento_live_stream.log"),
        "warn_age_s": 120,      # 2 min
        "crit_age_s": 300,      # 5 min
        "service": "MIA-Live-OHLCV",
    },
    {
        "name": "Bot1_Sierra_paper",
        # Glob + filtre regex strict pour exclure databento_paper (fix bug #2)
        "type": "glob_mtime_filtered",
        "path_glob": str(ROOT / "LOGS" / "events" / "events_*_paper.jsonl"),
        "filename_regex_exclude": r"databento_paper",
        # Seuils calibres pour absorber les silences legitimes :
        # - Blocage 15 premieres min RTH (13:30-13:45 UTC) : Bot1 ne logue PAS d'events
        # - Hors RTH/sessions creuses : peu d'events naturels
        # Apprentissage 01/05 14:42 : seuil 10 min trop strict → faux positif restart
        # apres BOT_KILL_SWITCH_RELEASED 13:21 → silence 21 min jusqu'a fin blocage RTH.
        # Bumper : 30 min CRIT permet de tolerer ces silences sans rater un vrai zombie
        # (V2CLEAN zombie 33h matin = facilement detecte avec 30 min seuil).
        "warn_age_s": 600,      # 10 min (avant : 2 min — trop bavard)
        "crit_age_s": 1800,     # 30 min (avant : 10 min — faux positif blocage RTH)
        "service": "MIA-Paper",
        "pause_grace_path": str(ROOT / "DATA" / "BOT_CONTROL" / "STOP.flag"),
    },
    {
        "name": "Bot2_Databento_paper",
        "type": "jsonl_last_bar_age",
        "path_glob": str(ROOT / "LOGS" / "events" / "events_*_databento_paper.jsonl"),
        # Aligne sur seuils internes databento_paper_trader.py (Option B 01/05) :
        # FRESH=600 / WARN=1500 / CRIT=2700. Pipeline live a retard structurel
        # ~30 min pendant catch-up apres incident — il faut tolerer sinon le
        # watchdog re-restart Bot 2 indefiniment (boucle de bug observee 13:55:11).
        "warn_age_s": 1500,     # 25 min (avant : 5 min)
        "crit_age_s": 2700,     # 45 min (avant : 15 min)
        "service": "MIA-DataBento-Paper",
        # Honore les 2 flags : global admin + local data stale
        "pause_grace_paths": [
            str(ROOT / "DATA" / "BOT_CONTROL" / "STOP.flag"),
            str(ROOT / "DATA" / "BOT_CONTROL" / "STOP_DATABENTO.flag"),
        ],
    },
    {
        "name": "Live_Pipeline",
        "type": "file_mtime",
        "path": str(ROOT / "LOGS" / "live_pipeline_loop.log"),
        "warn_age_s": 360,      # 6 min (pipeline interval=300s)
        "crit_age_s": 900,      # 15 min
        "service": "MIA-LivePipeline",
    },
    {
        "name": "DMP_JSONL_ES",
        "type": "glob_mtime",
        "path_glob": str(ROOT / "DATA" / "ES" / "*_ES.jsonl"),
        "warn_age_s": 90,       # bar 1m + marge
        "crit_age_s": 300,      # 5 min sans nouvelle bar = SC ou DMP plante
        "service": None,        # pas de restart auto (Sierra Chart manuel)
        "pause_grace_path": str(ROOT / "DATA" / "BOT_CONTROL" / "SIERRA_MAINTENANCE.flag"),
    },
    {
        "name": "DMP_JSONL_NQ",
        "type": "glob_mtime",
        "path_glob": str(ROOT / "DATA" / "NQ" / "*_NQ.jsonl"),
        "warn_age_s": 90,
        "crit_age_s": 300,
        "service": None,
        "pause_grace_path": str(ROOT / "DATA" / "BOT_CONTROL" / "SIERRA_MAINTENANCE.flag"),
    },
]


# ============================================================================
# LOGGER
# ============================================================================

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
EVENTS_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("mia_watchdog")

# Identifiant du process pour les logs structures (fix #9)
HOST_PROCESS = f"{socket.gethostname()}/watchdog_pid{os.getpid()}"


def emit_event(level: str, code: str, msg_fr: str, **ctx):
    """Ecrit un event structure dans LOGS/events/events_YYYYMMDD_watchdog.jsonl
    (format compatible avec les autres bots, audit J+1 grep par code)."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = EVENTS_LOG_DIR / f"events_{today}_watchdog.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "level": level,
        "cat": "events",
        "code": code,
        "msg_fr": msg_fr,
        "host_process": HOST_PROCESS,
        "module": "mia_watchdog",
        "signal_id": None,
        "ctx": ctx,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning(f"emit_event fail: {e}")


# ============================================================================
# CHECK FUNCTIONS — une par type de source
# ============================================================================

def check_file_mtime(path: str) -> Optional[float]:
    """Age en secondes du mtime d'un fichier. None si absent."""
    try:
        st = os.stat(path)
        return time.time() - st.st_mtime
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning(f"check_file_mtime({path}) OSError: {e}")
        return None


def check_glob_mtime(pattern: str) -> Optional[float]:
    """Age du fichier le plus recent matchant le glob. None si aucun match."""
    matches = glob.glob(pattern)
    if not matches:
        return None
    try:
        latest = max(matches, key=lambda p: os.stat(p).st_mtime)
        return time.time() - os.stat(latest).st_mtime
    except OSError as e:
        logger.warning(f"check_glob_mtime({pattern}) OSError: {e}")
        return None


def check_glob_mtime_filtered(pattern: str, filename_regex_exclude: str) -> Optional[float]:
    """Comme check_glob_mtime mais exclut les fichiers dont le nom matche la regex.
    Fix bug #2 : `events_*_paper.jsonl` matche aussi `events_*_databento_paper.jsonl`.
    On exclut ceux contenant `databento_paper` pour ne garder que Bot 1 Sierra."""
    matches = glob.glob(pattern)
    if not matches:
        return None
    rx = re.compile(filename_regex_exclude)
    filtered = [p for p in matches if not rx.search(os.path.basename(p))]
    if not filtered:
        return None
    try:
        latest = max(filtered, key=lambda p: os.stat(p).st_mtime)
        return time.time() - os.stat(latest).st_mtime
    except OSError as e:
        logger.warning(f"check_glob_mtime_filtered({pattern}) OSError: {e}")
        return None


def check_json_ts_utc(path: str, ts_field: str) -> Optional[float]:
    """Age en secondes du champ ts_utc dans un JSON. None si absent ou parse fail."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"check_json_ts_utc({path}) fail: {e}")
        return None
    ts_str = data.get(ts_field)
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except (ValueError, TypeError) as e:
        logger.warning(f"check_json_ts_utc({path}) parse {ts_field}={ts_str!r}: {e}")
        return None


def check_jsonl_last_bar_age(pattern: str) -> Optional[float]:
    """Lit le dernier BOT_HEARTBEAT du JSONL le plus recent et retourne last_bar_age."""
    matches = glob.glob(pattern)
    if not matches:
        return None
    latest = max(matches, key=lambda p: os.stat(p).st_mtime)
    try:
        with open(latest, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block_size = min(8192, size)
            f.seek(-block_size, os.SEEK_END)
            tail_bytes = f.read()
    except OSError as e:
        logger.warning(f"check_jsonl_last_bar_age({latest}) OSError: {e}")
        return None
    lines = tail_bytes.decode("utf-8", errors="replace").strip().split("\n")
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("code") == "BOT_HEARTBEAT":
            ctx = ev.get("ctx") or {}
            age = ctx.get("last_bar_age")
            if isinstance(age, (int, float)) and age >= 0:
                return float(age)
    return None  # pas de BOT_HEARTBEAT trouve dans le tail


# Dispatcher type → fonction
CHECKERS = {
    "file_mtime":           lambda src: check_file_mtime(src["path"]),
    "glob_mtime":           lambda src: check_glob_mtime(src["path_glob"]),
    "glob_mtime_filtered":  lambda src: check_glob_mtime_filtered(
        src["path_glob"], src["filename_regex_exclude"]),
    "json_ts_utc":          lambda src: check_json_ts_utc(src["path"], src["ts_field"]),
    "jsonl_last_bar_age":   lambda src: check_jsonl_last_bar_age(src["path_glob"]),
}


# ============================================================================
# RESTART POLICY (PERSISTANT — fix reserve #4)
# ============================================================================

class RestartTracker:
    """Empeche les boucles de restart : max N restart par service par heure.
    Persiste l'historique sur disque pour survivre aux restart du watchdog lui-meme.
    Sinon nssm restart watchdog → cap reset → spam restart cible."""

    def __init__(self, max_per_hour: int = MAX_RESTART_PER_HOUR,
                 path: Path = RESTART_HISTORY_FILE):
        self.max_per_hour = max_per_hour
        self.path = path
        self._history: dict[str, list[datetime]] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for service, ts_list in data.items():
                self._history[service] = [
                    datetime.fromisoformat(ts.replace("Z", "+00:00")) for ts in ts_list
                ]
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(f"RestartTracker._load fail: {e}")

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                service: [t.isoformat().replace("+00:00", "Z") for t in ts_list]
                for service, ts_list in self._history.items()
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.error(f"RestartTracker._save fail: {e}")

    def can_restart(self, service: str) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=1)
        history = [t for t in self._history.get(service, []) if t > cutoff]
        self._history[service] = history
        return len(history) < self.max_per_hour

    def record(self, service: str):
        self._history.setdefault(service, []).append(datetime.now(timezone.utc))
        self._save()


def restart_service_nssm(service: str) -> tuple[bool, str]:
    """Restart-Service via PowerShell. Retourne (success, message).

    Fix dry-run bug 01/05/2026 : subprocess.run avec text=True + encoding par
    defaut Windows fr-FR cp1252 plante sur stderr contenant chars non-UTF8.
    Force encoding="utf-8" + errors="replace" + fallback `or ""` sur stderr."""
    try:
        result = subprocess.run(
            ["powershell", "-Command", f"Restart-Service {service} -ErrorAction Stop"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RESTART_SERVICE_TIMEOUT_SEC,
        )
        if result.returncode == 0:
            return True, f"Restart-Service {service} OK"
        stderr = (result.stderr or "").strip() or "(no stderr)"
        return False, f"Restart-Service {service} fail: {stderr}"
    except subprocess.TimeoutExpired:
        return False, f"Restart-Service {service} TIMEOUT (>{RESTART_SERVICE_TIMEOUT_SEC}s)"
    except OSError as e:
        return False, f"Restart-Service {service} OSError: {e}"


# ============================================================================
# WATCHDOG
# ============================================================================

# Mapping niveau → priorite pour calcul du worst level
LEVEL_PRIORITY = {"OK": 0, "PAUSED": 1, "ABSENT": 2, "WARN": 3, "CRIT": 4}
LEVEL_EMOJI = {"OK": "✅", "WARN": "⚠️", "CRIT": "🚨", "ABSENT": "❌", "PAUSED": "⏸️"}


class Watchdog:
    def __init__(self, auto_restart: bool = True, interval: int = LOOP_INTERVAL_SEC,
                 dry_run: bool = False):
        self.auto_restart = auto_restart
        self.interval = interval
        self.dry_run = dry_run
        self.alerter = DiscordAlerter() if not dry_run else None
        self.restart_tracker = RestartTracker()

        # Dedup alertes : (source_name, level) → datetime de derniere alerte
        self._last_alert: dict[tuple[str, str], datetime] = {}
        # ABSENT → CRIT escalation (fix bug #1)
        self._absent_streak: dict[str, int] = {}
        # Heartbeat positif Discord
        self._last_heartbeat_discord: Optional[datetime] = None
        # Stats run
        self._stats = {"checks": 0, "warns": 0, "crits": 0, "restarts": 0, "absents_escalated": 0}

    def _check_pause_flags(self, source: dict) -> tuple[bool, Optional[str], Optional[float]]:
        """Retourne (is_paused, flag_path_active, flag_age_s).
        Honore pause_grace_path (str) ET pause_grace_paths (list)."""
        paths = []
        if "pause_grace_path" in source:
            paths.append(source["pause_grace_path"])
        if "pause_grace_paths" in source:
            paths.extend(source["pause_grace_paths"])
        for p in paths:
            if p and os.path.exists(p):
                try:
                    age = time.time() - os.stat(p).st_mtime
                except OSError:
                    age = None
                return True, p, age
        return False, None, None

    def _alert_dedup_ok(self, source_name: str, level: str,
                        custom_minutes: Optional[int] = None) -> bool:
        """Retourne True si on peut envoyer une nouvelle alerte (dedup OK).
        custom_minutes permet d'avoir un dedup plus long (ex: FLAG_STALE 60 min)."""
        key = (source_name, level)
        last = self._last_alert.get(key)
        if last is None:
            return True
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        threshold = (custom_minutes or DEDUP_ALERT_MIN) * 60
        return elapsed > threshold

    def _record_alert(self, source_name: str, level: str):
        self._last_alert[(source_name, level)] = datetime.now(timezone.utc)

    def _send_discord(self, channel: str, title: str, msg: str, color: int):
        if self.dry_run or self.alerter is None:
            logger.info(f"[DRY_RUN] Discord {channel}: {title} — {msg[:80]}")
            return
        try:
            self.alerter.send_custom(channel, title, msg, color=color)
        except Exception as e:
            logger.error(f"Discord send fail: {e}")

    def _evaluate_source(self, source: dict) -> tuple[str, Optional[float], str]:
        """Retourne (level, age_s, msg). level in {OK, ABSENT, WARN, CRIT, PAUSED}."""
        # Pause legitime (kill-switch admin ou local data stale)
        is_paused, flag_path, flag_age = self._check_pause_flags(source)
        if is_paused:
            # Reset streak ABSENT pendant pause (sinon flag long → faux CRIT au release)
            self._absent_streak[source["name"]] = 0
            return "PAUSED", flag_age, f"{source['name']} pause via {os.path.basename(flag_path)} (age={flag_age:.0f}s)" if flag_age else f"{source['name']} pause via {os.path.basename(flag_path)}"

        checker = CHECKERS.get(source["type"])
        if not checker:
            return "ABSENT", None, f"type inconnu: {source['type']}"

        try:
            age = checker(source)
        except Exception as e:
            # Ne pas planter le watchdog sur un bug checker isole
            logger.error(f"checker {source['name']} crash: {e}", exc_info=True)
            return "ABSENT", None, f"{source['name']}: checker exception {type(e).__name__}: {e}"

        if age is None:
            # Streak ABSENT (fix bug #1)
            streak = self._absent_streak.get(source["name"], 0) + 1
            self._absent_streak[source["name"]] = streak
            if streak >= ABSENT_TO_CRIT_STREAK:
                self._stats["absents_escalated"] += 1
                return "CRIT", None, (
                    f"{source['name']}: ABSENT depuis {streak} checks consec "
                    f"(>={ABSENT_TO_CRIT_STREAK}) — source jamais vue/disparue : "
                    f"{source.get('path') or source.get('path_glob')}"
                )
            return "ABSENT", None, (
                f"{source['name']}: source absente (streak={streak}/{ABSENT_TO_CRIT_STREAK}) "
                f"{source.get('path') or source.get('path_glob')}"
            )

        # Reset streak ABSENT des qu'on a une mesure
        self._absent_streak[source["name"]] = 0

        if age > source["crit_age_s"]:
            return "CRIT", age, f"{source['name']}: STALE CRITICAL age={age:.0f}s > {source['crit_age_s']}s"
        if age > source["warn_age_s"]:
            return "WARN", age, f"{source['name']}: STALE WARN age={age:.0f}s > {source['warn_age_s']}s"
        return "OK", age, f"{source['name']}: fresh age={age:.0f}s"

    def _handle_paused_source(self, source: dict, age_s: Optional[float]):
        """Si le flag de pause est trop ancien, alerte FLAG_STALE (fix reserve #5)."""
        if age_s is None or age_s < PAUSE_FLAG_STALE_MIN * 60:
            return
        if not self._alert_dedup_ok(source["name"], "FLAG_STALE", DEDUP_FLAG_STALE_MIN):
            return
        self._record_alert(source["name"], "FLAG_STALE")
        msg = f"{source['name']} en pause depuis {age_s/60:.0f} min — verifier oubli ou panne reelle"
        self._send_discord(
            "alertes",
            f"⚠️ MIA Watchdog — FLAG_STALE: {source['name']}",
            msg + f"\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            color=0xFF8C00,
        )
        emit_event("MAJEUR", "WATCHDOG_FLAG_STALE", msg,
                   source=source["name"], flag_age_min=int(age_s / 60))
        logger.warning(msg)

    def _handle_crit(self, source: dict, msg: str):
        self._stats["crits"] += 1
        # Emit log structure systematiquement (audit J+1)
        emit_event("CRITIQUE", "WATCHDOG_SOURCE_CRIT", msg, source=source["name"])

        if not self._alert_dedup_ok(source["name"], "CRIT"):
            return
        self._record_alert(source["name"], "CRIT")
        title = f"🚨 MIA Watchdog — CRITICAL: {source['name']}"
        action = "Restart-Service en cours..." if (self.auto_restart and source.get("service")) else "Pas de restart auto."
        body = f"**{msg}**\n\n{action}\n\nHeure : {datetime.now().strftime('%H:%M:%S')}"
        self._send_discord("alertes", title, body, color=0xD50000)
        logger.error(msg)

        # Restart auto si configure
        service = source.get("service")
        if self.auto_restart and service:
            if not self.restart_tracker.can_restart(service):
                # Dedup sur CAP_REACHED (fix reserve #6) sinon spam toutes les 60s
                if self._alert_dedup_ok(source["name"], "CAP_REACHED", custom_minutes=60):
                    self._record_alert(source["name"], "CAP_REACHED")
                    self._send_discord(
                        "alertes",
                        f"⛔ MIA Watchdog — RESTART CAP: {service}",
                        f"Limite {MAX_RESTART_PER_HOUR} restart/heure atteinte. Intervention humaine requise.",
                        color=0xFF8C00,
                    )
                    emit_event("CRITIQUE", "WATCHDOG_RESTART_CAP_REACHED",
                               f"{service} cap {MAX_RESTART_PER_HOUR}/h", service=service)
                logger.critical(f"Restart cap reached for {service}")
                return

            # Fix 01/05 : dry-run doit aussi bloquer le restart REEL
            # (sinon test local peut redemarrer un service prod par erreur)
            if self.dry_run:
                logger.info(f"[DRY_RUN] Restart-Service {service} simule (skip exec)")
                emit_event("INFO", "WATCHDOG_RESTART_SIMULATED",
                           f"DRY_RUN: skip Restart-Service {service}",
                           service=service, reason=msg)
                return

            ok, info = restart_service_nssm(service)
            self.restart_tracker.record(service)
            self._stats["restarts"] += 1
            level_color = 0x00C853 if ok else 0xD50000
            self._send_discord(
                "alertes",
                f"🔄 MIA Watchdog — Restart {service}",
                f"{info}\nReason: {msg}",
                color=level_color,
            )
            emit_event("MAJEUR", "WATCHDOG_RESTART_TRIGGERED", info,
                       service=service, success=ok, reason=msg)
            logger.warning(f"Restart triggered for {service}: {info}")

    def _handle_warn(self, source: dict, msg: str):
        self._stats["warns"] += 1
        emit_event("MAJEUR", "WATCHDOG_SOURCE_WARN", msg, source=source["name"])
        if not self._alert_dedup_ok(source["name"], "WARN"):
            return
        self._record_alert(source["name"], "WARN")
        self._send_discord(
            "alertes",
            f"⚠️ MIA Watchdog — WARN: {source['name']}",
            f"**{msg}**\n\nMonitoring, no action.\n\nHeure : {datetime.now().strftime('%H:%M:%S')}",
            color=0xFF8C00,
        )
        logger.warning(msg)

    def _send_heartbeat_if_due(self, summary: list[dict]):
        """Heartbeat positif Discord. Color/title/channel selon worst level (fix bug #3)."""
        now = datetime.now(timezone.utc)
        if self._last_heartbeat_discord is not None:
            elapsed = (now - self._last_heartbeat_discord).total_seconds()
            if elapsed < HEARTBEAT_INTERVAL_MIN * 60:
                return

        # Calcul worst level dans summary
        worst_level = "OK"
        worst_priority = 0
        for entry in summary:
            level = entry["result"][0]
            p = LEVEL_PRIORITY.get(level, 0)
            if p > worst_priority:
                worst_priority = p
                worst_level = level

        # Adapter title/color/channel selon worst (fix bug #3)
        if worst_level == "CRIT":
            title = "🚨 MIA Watchdog — DEGRADED (CRITICAL)"
            color = 0xD50000
            channel = "alertes"
        elif worst_level == "ABSENT":
            title = "❌ MIA Watchdog — DEGRADED (ABSENT)"
            color = 0xD50000
            channel = "alertes"
        elif worst_level == "WARN":
            title = "⚠️ MIA Watchdog — DEGRADED (WARN)"
            color = 0xFF8C00
            channel = "alertes"
        elif worst_level == "PAUSED":
            title = "⏸️ MIA Watchdog — PAUSE active"
            color = 0x2962FF
            channel = "admin"
        else:
            title = "💓 MIA Watchdog — Heartbeat OK"
            color = 0x00C853
            channel = "admin"

        # Resume etat des sources
        lines = []
        for entry in summary:
            level, age, _ = entry["result"]
            mark = LEVEL_EMOJI.get(level, "?")
            age_str = f"{age:.0f}s" if age is not None else "n/a"
            lines.append(f"{mark} {entry['source']['name']}: {age_str}")
        body = "\n".join(lines)
        body += f"\n\nStats: {self._stats['checks']} checks, "
        body += f"{self._stats['warns']} warns, {self._stats['crits']} crits, "
        body += f"{self._stats['restarts']} restarts, "
        body += f"{self._stats['absents_escalated']} ABSENT→CRIT"

        self._send_discord(channel, title, body, color=color)
        self._last_heartbeat_discord = now
        emit_event("INFO", "WATCHDOG_HEARTBEAT",
                   f"Heartbeat: worst={worst_level}",
                   worst_level=worst_level, **self._stats)
        logger.info(f"Heartbeat Discord sent (worst={worst_level})")

    def run(self):
        logger.info("=" * 60)
        logger.info(f"MIA V2 Watchdog START — auto_restart={self.auto_restart} "
                    f"interval={self.interval}s dry_run={self.dry_run}")
        logger.info(f"Sources: {[s['name'] for s in SOURCES]}")
        logger.info("=" * 60)

        emit_event("MAJEUR", "WATCHDOG_START",
                   f"Watchdog demarre auto_restart={self.auto_restart}",
                   auto_restart=self.auto_restart, interval=self.interval,
                   sources=[s["name"] for s in SOURCES])

        self._send_discord(
            "admin",
            "🐕 MIA V2 Watchdog demarre",
            f"Surveillance active — {len(SOURCES)} sources, check toutes les {self.interval}s.\n"
            f"Auto-restart : {self.auto_restart}",
            color=0x00C853,
        )

        try:
            while True:
                self._stats["checks"] += 1
                summary = []
                for source in SOURCES:
                    level, age, msg = self._evaluate_source(source)
                    summary.append({"source": source, "result": (level, age, msg)})
                    if level == "CRIT":
                        self._handle_crit(source, msg)
                    elif level == "WARN":
                        self._handle_warn(source, msg)
                    elif level == "PAUSED":
                        # Detecte flag stale (oublie > 30 min)
                        self._handle_paused_source(source, age)
                    elif level == "ABSENT":
                        # Pas escalade encore (streak < seuil) — log debug seulement
                        logger.debug(msg)

                self._send_heartbeat_if_due(summary)
                time.sleep(self.interval)

        except KeyboardInterrupt:
            logger.info("Watchdog arrete par Ctrl+C")
            emit_event("MAJEUR", "WATCHDOG_STOP", "Arret manuel via Ctrl+C")
        except Exception as e:
            logger.error(f"Watchdog crash inattendu: {e}", exc_info=True)
            emit_event("CRITIQUE", "WATCHDOG_CRASH",
                       f"Watchdog crash: {type(e).__name__}: {e}",
                       exc_type=type(e).__name__, exc_msg=str(e)[:200])
            self._send_discord(
                "alertes",
                "🚨 MIA Watchdog CRASH",
                f"Watchdog lui-meme a plante : {e}\nIntervention humaine requise.",
                color=0xD50000,
            )
            raise
        finally:
            self._send_discord(
                "admin",
                "🛑 MIA V2 Watchdog arrete",
                f"Stats finales : {self._stats}",
                color=0x616161,
            )


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="MIA V2 Watchdog data freshness multi-source")
    parser.add_argument("--no-restart", action="store_true",
                        help="Desactive auto-restart (alerte seule)")
    parser.add_argument("--interval", type=int, default=LOOP_INTERVAL_SEC,
                        help=f"Intervalle check en secondes (defaut: {LOOP_INTERVAL_SEC})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse sources mais n'envoie pas Discord (test local)")
    args = parser.parse_args()

    wd = Watchdog(
        auto_restart=not args.no_restart,
        interval=args.interval,
        dry_run=args.dry_run,
    )
    wd.run()


if __name__ == "__main__":
    main()
