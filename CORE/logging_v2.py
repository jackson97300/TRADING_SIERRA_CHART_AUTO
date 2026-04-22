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
