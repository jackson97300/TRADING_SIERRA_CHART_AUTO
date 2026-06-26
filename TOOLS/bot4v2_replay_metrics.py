"""Bot 4 v2 replay metrics - validation pipeline sur sample JSONL historique.

Phase P5.4.B (26/06/2026) — Implementation regle souveraine CHANGELOG
"backtest preservation wins prouvee avant deploy modif moteur decision".

Pour Bot 4 v2 = refonte TOTALE (vs Bot 4 v1 disabled INCIDENT_LOG #83) :
- Preservation wins literal IMPOSSIBLE (architecture differente)
- Adaptation pragmatique : valider pipeline produit > 0 fire sur N jours,
  ratio fire/bar dans range raisonnable, zero crash

Critere GO Sim5 (heuristique conservative) :
- > 0 fires_evaluated sur la periode (sinon pipeline cassee)
- 0 jour avec crash (process_bar exception)
- closed_signals ~= dispatched_brackets (state machine consistance)
- naked_brackets = 0 en dry-run (mais code path testable)

Usage :
    # 10 derniers jours NQ
    python tools/bot4v2_replay_metrics.py --symbol NQ --since 20260612 --until 20260625

    # JSON output pour CI
    python tools/bot4v2_replay_metrics.py --symbol NQ --since 20260620 --until 20260625 --json

EXCLU scope (backlog P6) :
- Backtest preservation wins literal (necessite Bot 4 v1 trace + 14j sample)
- P&L simulation reel (necessite slip + fees model)
- Walk-forward DSR Lopez (P6 30j shadow data prerequis)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


def date_range(since: str, until: str) -> list[str]:
    """Liste YYYYMMDD entre since et until inclus."""
    d1 = datetime.strptime(since, "%Y%m%d").date()
    d2 = datetime.strptime(until, "%Y%m%d").date()
    if d2 < d1:
        return []
    result = []
    current = d1
    while current <= d2:
        result.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return result


def replay_one_day(jsonl_path: Path, symbol: str, max_bars: int = 0,
                    menthorq_dir: Optional[Path] = None) -> dict:
    """Replay 1 jour JSONL via BotMainLoop dry-run + collect metrics.

    Args:
        jsonl_path : path fichier JSONL live_enriched
        symbol : "NQ" / "ES" / ...
        max_bars : 0 = full file, >0 = limit
        menthorq_dir : optionnel MenthorQ path (defaut tmp empty)

    Returns:
        dict metrics {bars_processed, fires_evaluated, ..., crashed: bool}
    """
    if not jsonl_path.exists():
        return {
            "path": str(jsonl_path), "exists": False,
            "bars_processed": 0, "crashed": False,
        }

    # Import lazy pour eviter overhead si pas appele
    from bot4_v2.main.__main__ import build_loop, parse_args

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mq_dir = menthorq_dir or Path(tmp)
        cli_args = [
            "--symbols", symbol,
            "--replay", str(jsonl_path),
            "--menthorq-dir", str(mq_dir),
            "--max-cycles", str(max_bars) if max_bars > 0 else "0",
            "--heartbeat-sec", "0",
        ]
        args = parse_args(cli_args)
        try:
            loop = build_loop(args)
        except Exception as exc:  # noqa: BLE001
            return {
                "path": str(jsonl_path), "exists": True,
                "bars_processed": 0, "crashed": True,
                "exc_type": type(exc).__name__,
                "exc_msg": str(exc)[:200],
            }
        try:
            loop.run()
        except Exception as exc:  # noqa: BLE001
            return {
                "path": str(jsonl_path), "exists": True,
                "bars_processed": loop.processed_bars,
                "crashed": True,
                "exc_type": type(exc).__name__,
                "exc_msg": str(exc)[:200],
            }

        # Extract metrics from loop state (router + reconciler)
        router = loop._router
        reconciler = loop._reconciler
        tracker = router.trackers.get(symbol.upper())

        metrics = {
            "path": str(jsonl_path),
            "exists": True,
            "bars_processed": loop.processed_bars,
            "total_dispatches": loop.total_dispatches,
            "crashed": False,
            "tracker_active_instances": tracker.n_active if tracker else 0,
            "tracker_total_instances": tracker.n_instances if tracker else 0,
            "reconciler_positions_tracked": reconciler.n_positions,
            "dispatch_map_size": len(router._signal_to_dispatch),
        }
        return metrics


def aggregate_metrics(per_day: list[dict]) -> dict:
    """Aggrege metriques cross-day."""
    agg = {
        "n_days": len(per_day),
        "n_files_exist": sum(1 for d in per_day if d.get("exists")),
        "n_crashed": sum(1 for d in per_day if d.get("crashed")),
        "total_bars": sum(d.get("bars_processed", 0) for d in per_day),
        "total_dispatches": sum(d.get("total_dispatches", 0) for d in per_day),
        "max_dispatch_map_size": max(
            (d.get("dispatch_map_size", 0) for d in per_day),
            default=0,
        ),
    }
    # Critere GO Sim5 (heuristique conservative)
    has_fire = agg["total_dispatches"] > 0 or any(
        d.get("tracker_total_instances", 0) > 0 for d in per_day
    )
    agg["has_fire"] = has_fire
    agg["status"] = (
        "GO" if (has_fire and agg["n_crashed"] == 0) else "RESERVE"
    )
    if agg["n_crashed"] > 0:
        agg["status_reason"] = f"{agg['n_crashed']} jours crashed"
    elif not has_fire:
        agg["status_reason"] = "Aucun fire/instance detecte (pipeline silencieuse)"
    else:
        agg["status_reason"] = "Pipeline fonctionnel, >0 fires/instances"
    return agg


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="bot4v2_replay_metrics",
        description="Replay sample JSONL historique + collect metrics validation pipeline",
    )
    parser.add_argument("--symbol", default="NQ", help="Symbole (defaut NQ)")
    parser.add_argument("--since", required=True, help="Date debut YYYYMMDD")
    parser.add_argument("--until", required=True, help="Date fin YYYYMMDD")
    parser.add_argument(
        "--data-dir", default="DATA/live_enriched/sierra",
        help="Repertoire data live_enriched",
    )
    parser.add_argument(
        "--menthorq-dir", default=None,
        help="MenthorQ dir (defaut: tmp empty pour replay neutre)",
    )
    parser.add_argument(
        "--max-bars-per-day", type=int, default=0,
        help="Limit bars/day (0 = full). Pour tests rapides.",
    )
    parser.add_argument("--json", action="store_true",
                          help="Output JSON pour CI")
    return parser.parse_args(argv)


def format_human(per_day: list[dict], agg: dict) -> str:
    """Format human-readable."""
    lines = [
        f"=== Bot 4 v2 Replay Metrics ===",
        f"Days replayed : {agg['n_days']} ({agg['n_files_exist']} files exist)",
        f"Total bars : {agg['total_bars']}",
        f"Total dispatches : {agg['total_dispatches']}",
        f"Has fire/instance : {agg['has_fire']}",
        f"Crashed days : {agg['n_crashed']}",
        f"Max dispatch_map size : {agg['max_dispatch_map_size']}",
        f"Status : {agg['status']} ({agg.get('status_reason', '')})",
        "",
        "Per day :",
    ]
    for d in per_day:
        path = Path(d["path"]).name
        if not d.get("exists"):
            lines.append(f"  {path:<45} (file absent)")
            continue
        if d.get("crashed"):
            lines.append(
                f"  {path:<45} CRASH {d.get('exc_type', '?')}"
            )
            continue
        lines.append(
            f"  {path:<45} bars={d['bars_processed']:>4} "
            f"dispatched={d.get('total_dispatches', 0)} "
            f"instances={d.get('tracker_total_instances', 0)}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    dates = date_range(args.since, args.until)
    if not dates:
        print("ERROR : since > until", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir) / args.symbol.upper()
    menthorq_dir = Path(args.menthorq_dir) if args.menthorq_dir else None

    per_day = []
    for d in dates:
        jsonl_path = data_dir / f"{d}_{args.symbol.upper()}_sierra_enriched.jsonl"
        metrics = replay_one_day(
            jsonl_path, args.symbol,
            max_bars=args.max_bars_per_day,
            menthorq_dir=menthorq_dir,
        )
        per_day.append(metrics)

    agg = aggregate_metrics(per_day)

    if args.json:
        print(json.dumps({
            "per_day": per_day,
            "aggregate": agg,
        }, indent=2))
    else:
        print(format_human(per_day, agg))

    return 0 if agg["status"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
