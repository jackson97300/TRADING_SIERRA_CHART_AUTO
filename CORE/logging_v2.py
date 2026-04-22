"""Module central logging V2 MIA Trading.

API unique projet-wide. Chaque log reference un code du catalog (pas de prose libre).
Route vers fichiers JSONL par categorie + process + date, sans mutex cross-process.

Usage type :
    from core.logging_v2 import get_logger
    log = get_logger("bot_main", process="v2clean")
    log.emit("SIGNAL_RECEIVED", sym="ES", direction="BUY", score=0.85)
    log.emit("KILL_DD_DAILY", pnl=-870, limit=-500)

Format ligne JSONL :
    {ts, level, cat, code, msg_fr, host_process, signal_id, ctx}
"""

from __future__ import annotations

import json
import os
import socket
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from CORE.log_catalog import CATEGORIES, LOG_CODES, LogLevel, get_action, resolve
except ImportError:
    from log_catalog import CATEGORIES, LOG_CODES, LogLevel, get_action, resolve  # type: ignore


LOG_BASE_DIR = Path(os.environ.get("MIA_LOG_DIR", "LOGS"))


def _ensure_directories() -> None:
    LOG_BASE_DIR.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        (LOG_BASE_DIR / cat).mkdir(parents=True, exist_ok=True)
    (LOG_BASE_DIR / "snapshots").mkdir(parents=True, exist_ok=True)
    (LOG_BASE_DIR / "preflight").mkdir(parents=True, exist_ok=True)


_ensure_directories()

_HOST = socket.gethostname()
_PID = os.getpid()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_path(category: str, process: str) -> Path:
    return LOG_BASE_DIR / category / f"{category}_{_today_utc()}_{process}.jsonl"


def _build_error_path(process: str) -> Path:
    return LOG_BASE_DIR / "errors" / f"errors_{_today_utc()}_{process}.jsonl"


class Logger:
    """Logger pointing vers une categorie + process fixes via process kwarg."""

    def __init__(self, module: str, process: str = "v2clean"):
        self._module = module
        self._process = process
        self._host_process = f"{_HOST}/{process}_pid{_PID}"

    def emit(
        self,
        code: str,
        *,
        signal_id: Optional[str] = None,
        exc: Optional[BaseException] = None,
        **ctx: Any,
    ) -> None:
        level, category, template = resolve(code)

        try:
            msg_fr = template.format(**ctx)
        except KeyError as err:
            msg_fr = f"{template} [MISSING_CTX: {err}]"

        entry: dict[str, Any] = {
            "ts": _now_iso(),
            "level": level.value,
            "cat": category,
            "code": code,
            "msg_fr": msg_fr,
            "host_process": self._host_process,
            "module": self._module,
            "signal_id": signal_id,
            "ctx": ctx,
        }

        if exc is not None:
            entry["trace"] = {
                "type": exc.__class__.__name__,
                "msg": str(exc),
                "frames": [str(frame) for frame in traceback.extract_tb(exc.__traceback__)[-3:]],
            }

        self._write(category, entry)

        actions = get_action(level)
        if actions["error_file"]:
            self._write_error(entry)
        if actions["discord"]:
            self._dispatch_discord(entry, mention=actions["discord_mention"])

    def _write(self, category: str, entry: dict) -> None:
        path = _build_path(category, self._process)
        line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def _write_error(self, entry: dict) -> None:
        path = _build_error_path(self._process)
        line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def _dispatch_discord(self, entry: dict, *, mention: bool) -> None:
        try:
            from BOT.discord_alerter import send as discord_send  # type: ignore
        except Exception:
            return
        prefix = "@here " if mention else ""
        text = f"{prefix}[{entry['level']}] [{entry['cat']}] {entry['code']} — {entry['msg_fr']}"
        try:
            discord_send(text)
        except Exception:
            pass


_LOGGERS: dict[tuple[str, str], Logger] = {}


def get_logger(module: str, *, process: str = "v2clean") -> Logger:
    """Retourne un logger cache par (module, process)."""
    key = (module, process)
    if key not in _LOGGERS:
        _LOGGERS[key] = Logger(module, process=process)
    return _LOGGERS[key]


class CompatLogger:
    """Bridge stdlib logging API → logging_v2 codes generiques.

    Permet migration progressive : remplacer `logger = logging.getLogger()` par
    `logger = get_compat_logger(...)` sans changer les appels .info/.warning/.error.
    Messages routes via codes GENERIC_* (categorie events).
    """

    def __init__(self, module: str, process: str):
        self._log = get_logger(module, process=process)

    def info(self, msg: str, *args, **kwargs) -> None:
        if args:
            msg = msg % args
        self._log.emit("GENERIC_INFO", msg=str(msg))

    def warning(self, msg: str, *args, **kwargs) -> None:
        if args:
            msg = msg % args
        self._log.emit("GENERIC_ALERTE", msg=str(msg))

    def error(self, msg: str, *args, exc_info: bool = False, **kwargs) -> None:
        if args:
            msg = msg % args
        exc = sys.exc_info()[1] if exc_info else None
        self._log.emit("GENERIC_MAJEUR", msg=str(msg), exc=exc)

    def critical(self, msg: str, *args, exc_info: bool = False, **kwargs) -> None:
        if args:
            msg = msg % args
        exc = sys.exc_info()[1] if exc_info else None
        self._log.emit("GENERIC_CRITIQUE", msg=str(msg), exc=exc)

    def debug(self, msg: str, *args, **kwargs) -> None:
        if args:
            msg = msg % args
        self._log.emit("GENERIC_DEBUG", msg=str(msg))

    def emit(self, code: str, **ctx) -> None:
        """Pass-through vers logger.emit() pour les migrations avec codes stables."""
        self._log.emit(code, **ctx)


_COMPAT_LOGGERS: dict[tuple[str, str], CompatLogger] = {}


def get_compat_logger(module: str, *, process: str = "v2clean") -> CompatLogger:
    """Retourne un CompatLogger cache par (module, process).

    Utile pour migration bot_main.py / dtc_connector.py etc. qui utilisent
    stdlib logging API. Preserve les appels .info/.warning/.error existants
    tout en routant vers le systeme V2.
    """
    key = (module, process)
    if key not in _COMPAT_LOGGERS:
        _COMPAT_LOGGERS[key] = CompatLogger(module, process=process)
    return _COMPAT_LOGGERS[key]


def write_snapshot(name: str, data: dict) -> None:
    """Ecrit snapshot permanent (PAS rotation) dans LOGS/snapshots/."""
    path = LOG_BASE_DIR / "snapshots" / f"{name}_{_today_utc()}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, default=str, ensure_ascii=False) + "\n")


def write_preflight(report: dict) -> Path:
    """Ecrit rapport preflight au boot dans LOGS/preflight/."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = LOG_BASE_DIR / "preflight" / f"preflight_{ts}.json"
    path.write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def catalog_count() -> int:
    return len(LOG_CODES)


if __name__ == "__main__":
    log = get_logger("self_test", process="dev")
    log.emit("SIGNAL_RECEIVED", sym="ES", direction="BUY", score=0.85, signal_id="test-uuid")
    log.emit("KILL_DD_DAILY", pnl=-870.5, limit=-500.0)
    log.emit("ORDER_REJECT", sym="NQ", err_code=221, err_msg="broker_busy")
    print(f"OK : {catalog_count()} codes catalogues, logs ecrits dans {LOG_BASE_DIR.resolve()}")
