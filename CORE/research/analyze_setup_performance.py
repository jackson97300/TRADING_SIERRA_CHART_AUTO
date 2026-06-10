"""analyze_setup_performance.py — Analyse reussite par setup depuis JSONL.

Created : 2026-05-02 dimanche soir.
Source : LOGS/setups_observed/YYYYMMDD_setups_trades.jsonl

Genere DOCS/SETUP_PERFORMANCE_REPORT.md avec :
  - Stats globales (n_trades, WR, PF, PnL total)
  - Breakdown par setup (PF, WR, PnL avg, MFE/MAE)
  - Breakdown par setup x session (RTH/Asia/London/AfterHours)
  - Breakdown par setup x regime VIX
  - Top setups gagnants vs perdants
  - Distribution exit_reason par setup

Usage :
  python -X utf8 CORE/research/analyze_setup_performance.py
  python -X utf8 CORE/research/analyze_setup_performance.py --date 20260505
  python -X utf8 CORE/research/analyze_setup_performance.py --since 20260505
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = ROOT / "LOGS" / "setups_observed"
OUTPUT_DIR = ROOT / "DOCS"


def load_trades(date_filter: str = None, since: str = None) -> list[dict]:
    """Charge tous les EXIT events des JSONL.

    date_filter : YYYYMMDD specifique
    since : YYYYMMDD minimum
    """
    trades = []
    for fp in sorted(LOGS_DIR.glob("*_setups_trades.jsonl")):
        date_str = fp.name.split("_")[0]
        if date_filter and date_str != date_filter:
            continue
        if since and date_str < since:
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                if d.get("event") == "EXIT":
                    trades.append(d)
            except json.JSONDecodeError:
                continue
    return trades


def compute_pf(trades: list[dict]) -> float:
    """Profit Factor exact = sum(gains) / |sum(pertes)|."""
    gains = sum(t["pnl_dollars"] for t in trades if t["pnl_dollars"] > 0)
    losses = sum(t["pnl_dollars"] for t in trades if t["pnl_dollars"] < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return round(gains / abs(losses), 2)


def aggregate_by(trades: list[dict], key_fn) -> dict[str, dict]:
    """Agrege les trades par cle (ex: par setup, par session, par setup×session)."""
    groups = defaultdict(list)
    for t in trades:
        keys = key_fn(t)
        if isinstance(keys, str):
            keys = [keys]
        for k in keys:
            groups[k].append(t)

    out = {}
    for key, ts in groups.items():
        n = len(ts)
        n_wins = sum(1 for t in ts if t["pnl_dollars"] > 0)
        pnl = sum(t["pnl_dollars"] for t in ts)
        out[key] = {
            "n_trades": n,
            "n_wins": n_wins,
            "wr_pct": round(n_wins / n * 100, 1) if n > 0 else 0,
            "pf": compute_pf(ts),
            "pnl_total_usd": round(pnl, 2),
            "pnl_avg_usd": round(pnl / n, 2) if n > 0 else 0,
            "mfe_avg_ticks": round(sum(t.get("mfe_ticks", 0) for t in ts) / n, 1) if n > 0 else 0,
            "mae_avg_ticks": round(sum(t.get("mae_ticks", 0) for t in ts) / n, 1) if n > 0 else 0,
        }
    return out


def render_table(data: dict[str, dict], title: str, sort_key: str = "pnl_total_usd") -> str:
    """Render markdown table."""
    if not data:
        return f"## {title}\n\n_Aucune donnée._\n"
    sorted_items = sorted(data.items(), key=lambda x: x[1].get(sort_key, 0), reverse=True)
    lines = [f"## {title}", ""]
    lines.append("| Key | N | Wins | WR% | PF | PnL total $ | PnL avg $ | MFE avg t | MAE avg t |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for key, s in sorted_items:
        emoji = "⭐" if s["pf"] >= 1.3 and s["wr_pct"] >= 50 else ""
        lines.append(
            f"| {key} | {s['n_trades']} | {s['n_wins']} | "
            f"{s['wr_pct']}% | {s['pf']} | "
            f"{s['pnl_total_usd']} | {s['pnl_avg_usd']} | "
            f"{s['mfe_avg_ticks']} | {s['mae_avg_ticks']} | {emoji}"
        )
    return "\n".join(lines) + "\n\n"


def render_exit_reason_breakdown(trades: list[dict]) -> str:
    """Distribution exit_reason par setup."""
    by_setup_reason = defaultdict(lambda: defaultdict(int))
    for t in trades:
        for setup in t.get("all_setups", [t.get("setup_name", "?")]):
            by_setup_reason[setup][t.get("exit_reason", "?")] += 1

    lines = ["## Exit reasons par setup", ""]
    lines.append("| Setup | SL | TP_CAP | TRAILING | TIMEOUT | KILL | Total |")
    lines.append("|---|---|---|---|---|---|---|")
    for setup, reasons in sorted(by_setup_reason.items()):
        total = sum(reasons.values())
        lines.append(
            f"| {setup} | {reasons.get('SL', 0)} | {reasons.get('TP_CAP', 0)} | "
            f"{reasons.get('TRAILING', 0)} | {reasons.get('TIMEOUT', 0)} | "
            f"{reasons.get('KILL_SWITCH', 0)} | {total} |"
        )
    return "\n".join(lines) + "\n\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date specifique YYYYMMDD")
    parser.add_argument("--since", help="Depuis date YYYYMMDD")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "SETUP_PERFORMANCE_REPORT.md"))
    args = parser.parse_args()

    trades = load_trades(date_filter=args.date, since=args.since)
    if not trades:
        print(f"[WARN] Aucun trade trouve (date={args.date} since={args.since})")
        return

    period = args.date or args.since or "all"
    print(f"[load] {len(trades)} trades sur periode '{period}'")

    # Stats globales
    n_total = len(trades)
    n_wins = sum(1 for t in trades if t["pnl_dollars"] > 0)
    pnl_total = sum(t["pnl_dollars"] for t in trades)
    pf_global = compute_pf(trades)

    # Breakdowns
    by_setup_main = aggregate_by(trades, lambda t: t.get("setup_name", "?"))
    by_setup_individual = aggregate_by(
        trades, lambda t: t.get("all_setups", [t.get("setup_name", "?")])
    )
    by_session = aggregate_by(trades, lambda t: t.get("session_label_entry", t.get("session_label", "?")))
    by_regime = aggregate_by(trades, lambda t: t.get("regime_label", "?"))
    by_solo_conf = aggregate_by(
        trades,
        lambda t: t.get("setup_label_solo_or_confluence", "?")
    )
    by_setup_session = aggregate_by(
        trades,
        lambda t: [
            f"{setup}_x_{t.get('session_label_entry', t.get('session_label', '?'))}"
            for setup in t.get("all_setups", [t.get("setup_name", "?")])
        ]
    )
    by_setup_side = aggregate_by(
        trades,
        lambda t: [f"{setup}_{t.get('side', '?')}" for setup in t.get("all_setups", [t.get("setup_name", "?")])]
    )

    # Render report
    md = []
    md.append(f"# Setup Performance Report — Bot 2 V2 Phase 1\n")
    md.append(f"**Genere** : {datetime.now().isoformat()}")
    md.append(f"**Periode** : {period}")
    md.append(f"**Source** : `LOGS/setups_observed/*_setups_trades.jsonl`\n")

    md.append(f"## 0. Resume executif\n")
    md.append(f"- **Trades** : {n_total} ({n_wins} wins / {n_total - n_wins} losses)")
    md.append(f"- **WR** : {round(n_wins / n_total * 100, 1)}%")
    md.append(f"- **PF** : {pf_global}")
    md.append(f"- **PnL total** : ${round(pnl_total, 2)}")
    md.append(f"- **PnL avg/trade** : ${round(pnl_total / n_total, 2)}\n")

    md.append(render_table(by_setup_main, "1. Par setup (label principal — confluence concatenee)"))
    md.append(render_table(by_setup_individual, "2. Par setup individuel (chaque trigger compte separement)"))
    md.append(render_table(by_session, "3. Par session (entry)"))
    md.append(render_table(by_regime, "4. Par regime VIX"))
    md.append(render_table(by_solo_conf, "5. Solo vs Confluence"))
    md.append(render_table(by_setup_side, "6. Par setup x side"))
    md.append(render_table(by_setup_session, "7. Par setup x session (granulaire)"))
    md.append(render_exit_reason_breakdown(trades))

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(md), encoding="utf-8")
    print(f"[done] Rapport : {args.output}")


if __name__ == "__main__":
    main()
