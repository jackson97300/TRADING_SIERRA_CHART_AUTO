"""Logs summary — moteur de resume des logs V2 pour slash command /verif-logs.

Usage CLI :
    python -X utf8 -m CORE.logs_summary
    python -X utf8 -m CORE.logs_summary --hours 24
    python -X utf8 -m CORE.logs_summary --signal_id abc123
    python -X utf8 -m CORE.logs_summary --process v2clean
    python -X utf8 -m CORE.logs_summary --category trading

Protocol .claude/rules/log-debug-protocol.md applique :
  1. errors/   — derniers MAJEUR+CRITIQUE (priorite)
  2. events/   — transitions systeme (boot/session/heartbeat/crash)
  3. decisions/ — chain of gates (GATE_*_BLOCK)
  4. Correlation signal_id cross-categories si specifie

Output : format texte resume QUOI/OU/POURQUOI pour Jackson non-dev.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

LOG_BASE_DIR = Path(__file__).parent.parent / "LOGS"


def _read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _iter_category(category: str, since_utc: datetime, process: Optional[str] = None) -> Iterator[dict]:
    """Yields events d'une categorie depuis since_utc, filtrees par process si specifie."""
    cat_dir = LOG_BASE_DIR / category
    if not cat_dir.exists():
        return
    today = datetime.now(timezone.utc).date()
    dates_to_check = [today, today - timedelta(days=1)]  # tampon cross-minuit
    for d in dates_to_check:
        date_str = d.strftime("%Y%m%d")
        for path in cat_dir.glob(f"{category}_{date_str}_*.jsonl"):
            if process and f"_{process}." not in path.name:
                continue
            for entry in _read_jsonl(path):
                ts_str = entry.get("ts", "")
                try:
                    entry_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if entry_ts >= since_utc:
                        yield entry
                except (ValueError, AttributeError):
                    continue


def summarize_errors(since_utc: datetime, process: Optional[str] = None, max_events: int = 10) -> list[dict]:
    """Top N events MAJEUR+CRITIQUE triees par ts desc."""
    events = list(_iter_category("errors", since_utc, process))
    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return events[:max_events]


def count_by_code(category: str, since_utc: datetime, process: Optional[str] = None) -> Counter:
    """Count events par code dans une categorie."""
    c = Counter()
    for entry in _iter_category(category, since_utc, process):
        code = entry.get("code", "UNKNOWN")
        c[code] += 1
    return c


def count_by_level(since_utc: datetime, process: Optional[str] = None) -> dict:
    """Count events par niveau toutes categories."""
    result = Counter()
    for category in ("trading", "execution", "risk", "ml", "data", "events", "decisions", "errors"):
        for entry in _iter_category(category, since_utc, process):
            level = entry.get("level", "UNKNOWN")
            result[level] += 1
    return dict(result)


def trace_signal_id(signal_id: str, since_utc: datetime) -> list[dict]:
    """Retourne tous events avec signal_id matching, tries par ts asc."""
    events = []
    for category in ("trading", "execution", "risk", "ml", "decisions", "errors"):
        for entry in _iter_category(category, since_utc):
            if entry.get("signal_id") == signal_id:
                events.append(entry)
    events.sort(key=lambda e: e.get("ts", ""))
    return events


def last_transitions(since_utc: datetime, process: Optional[str] = None, max_events: int = 10) -> list[dict]:
    """Derniers events events/ (boot, session, heartbeat, crash)."""
    events = list(_iter_category("events", since_utc, process))
    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return events[:max_events]


def gate_blocks(since_utc: datetime, process: Optional[str] = None) -> Counter:
    """Count GATE_*_BLOCK par code dans decisions."""
    c = Counter()
    for entry in _iter_category("decisions", since_utc, process):
        code = entry.get("code", "")
        if code.startswith("GATE_") and "BLOCK" in code:
            c[code] += 1
    return c


def format_summary(hours: int = 24, process: Optional[str] = None,
                   signal_id: Optional[str] = None, category: Optional[str] = None) -> str:
    """Genere rapport texte pour Jackson (format QUOI/OU/POURQUOI)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    lines = []
    lines.append(f"=== LOGS SUMMARY — {hours}h ===")
    lines.append(f"Fenetre : {since.isoformat()} -> now")
    if process:
        lines.append(f"Process filter : {process}")
    if signal_id:
        lines.append(f"Signal ID : {signal_id}")
    lines.append("")

    # Si signal_id specifique → trace complete
    if signal_id:
        events = trace_signal_id(signal_id, since)
        lines.append(f"--- TRACE signal_id={signal_id} ({len(events)} events) ---")
        for e in events:
            ts = e.get("ts", "")[:19]
            lines.append(f"  [{ts}] [{e.get('level','')}] [{e.get('cat','')}] {e.get('code','')} — {e.get('msg_fr','')}")
        if not events:
            lines.append("  (aucun event trouve)")
        return "\n".join(lines)

    # Si categorie specifique → count codes + exemples
    if category:
        counts = count_by_code(category, since, process)
        lines.append(f"--- CATEGORIE {category} ({sum(counts.values())} events) ---")
        for code, n in counts.most_common(20):
            lines.append(f"  {n:4d}  {code}")
        return "\n".join(lines)

    # Recap standard 4 etapes protocol debug

    # 1. ERRORS (priorite)
    errors = summarize_errors(since, process, max_events=10)
    lines.append(f"--- ERRORS ({len(errors)} MAJEUR+CRITIQUE derniers 10) ---")
    if errors:
        for e in errors:
            ts = e.get("ts", "")[:19]
            lines.append(f"  [{ts}] [{e.get('level','')}] {e.get('code','')} : {e.get('msg_fr','')}")
    else:
        lines.append("  (aucune erreur — systeme OK)")
    lines.append("")

    # 2. NIVEAUX count (toutes categories)
    levels = count_by_level(since, process)
    lines.append("--- NIVEAUX (count toutes categories) ---")
    for lv in ("CRITIQUE", "MAJEUR", "ALERTE", "INFO"):
        n = levels.get(lv, 0)
        lines.append(f"  {lv:10s} : {n}")
    lines.append("")

    # 3. TRANSITIONS systeme
    transitions = last_transitions(since, process, max_events=8)
    lines.append(f"--- EVENTS SYSTEME (dernieres 8) ---")
    for e in transitions:
        ts = e.get("ts", "")[:19]
        lines.append(f"  [{ts}] {e.get('code','')} : {e.get('msg_fr','')[:80]}")
    lines.append("")

    # 4. GATE BLOCKS (pour "pourquoi aucun trade ?")
    blocks = gate_blocks(since, process)
    if blocks:
        lines.append("--- GATES BLOCKS (decisions/) ---")
        for code, n in blocks.most_common():
            lines.append(f"  {n:4d}  {code}")
        lines.append("")

    # 5. Top codes par categorie trading/risk/execution
    for cat in ("trading", "risk", "execution", "ml"):
        counts = count_by_code(cat, since, process)
        if counts:
            lines.append(f"--- TOP {cat} (3 premiers) ---")
            for code, n in counts.most_common(3):
                lines.append(f"  {n:4d}  {code}")
    lines.append("")
    lines.append("=== FIN SUMMARY ===")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MIA logs summary")
    parser.add_argument("--hours", type=int, default=24, help="Fenetre heures (defaut 24)")
    parser.add_argument("--process", type=str, default=None, help="Filtrer par process (v2clean, bot_legacy, watchdog)")
    parser.add_argument("--signal_id", type=str, default=None, help="Tracer un signal_id cross-categories")
    parser.add_argument("--category", type=str, default=None, help="Focus sur une categorie (trading/risk/execution/ml/events/data/decisions/errors)")
    args = parser.parse_args()

    print(format_summary(
        hours=args.hours,
        process=args.process,
        signal_id=args.signal_id,
        category=args.category,
    ))


if __name__ == "__main__":
    main()
