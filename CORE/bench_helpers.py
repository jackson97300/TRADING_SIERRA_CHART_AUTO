# -*- coding: utf-8 -*-
"""
bench_helpers.py — Helpers communs aux benchs MIA.

Mutualise les fonctions utilisees par mia_bench_v4.py, bench_dashboard.py,
bench_bots.py pour eviter duplication (~80 LOC).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def append_print(out: list, msg: str) -> None:
    """Print + append a une liste de sortie (pour rapport texte)."""
    print(msg)
    out.append(msg)


def file_age_seconds(path: Path) -> float | None:
    """Retourne age en secondes du fichier ou None si absent."""
    if not path.exists():
        return None
    mt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mt).total_seconds()


def get_service_status(name: str, timeout: int = 5) -> str:
    """Retourne 'Running' / 'Stopped' / 'NotFound' / 'ERROR'."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Service {name} -ErrorAction SilentlyContinue | Select -ExpandProperty Status"],
            capture_output=True, text=True, timeout=timeout
        )
        return (r.stdout or "").strip() or "NotFound"
    except subprocess.TimeoutExpired:
        return "ERROR_TIMEOUT"
    except Exception as e:
        return f"ERROR_{type(e).__name__}"


def find_python_process(needle: str, timeout: int = 5) -> str | None:
    """Trouve le PID Python dont la CommandLine contient `needle`.

    Note securite : `needle` doit etre hardcoded dans le code appelant
    (jamais user input) car interpole dans une commande PowerShell.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
             f"Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=timeout
        )
        out = (r.stdout or "").strip()
        if not out:
            return None
        return out.split()[0].strip()  # premier PID, nettoye CRLF Windows
    except Exception:
        return None


def count_recent_in_log(log_path: Path, code_pattern: str,
                         max_age_sec: int = 3600) -> int:
    """Count occurrences d'un pattern dans les N derniers secondes du log JSONL."""
    if not log_path.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_sec
    n = 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if code_pattern not in line:
                    continue
                try:
                    j = json.loads(line)
                    ts = datetime.fromisoformat(j["ts"].replace("Z", "+00:00")).timestamp()
                    if ts > cutoff:
                        n += 1
                except (KeyError, ValueError, json.JSONDecodeError):
                    pass
    except OSError:
        pass
    return n


def read_json_safe(path: Path) -> dict | None:
    """Lit un JSON encoding-safe (utf-8 explicite, fallback None si fail)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def fmt_age(secs: float | None) -> str:
    """Format human-friendly age."""
    if secs is None:
        return "MISSING"
    if secs < 60:
        return f"{secs:.0f}s"
    if secs < 3600:
        return f"{secs/60:.1f}min"
    return f"{secs/3600:.1f}h"
