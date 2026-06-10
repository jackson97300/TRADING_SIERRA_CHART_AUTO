"""Audit empirique Phase 1 : attribution source data (V4 enriched vs Fallback DMP)
sur les trades Bot 2 V6 du 11/05/2026.

Sortie : tableau trades avec source + WR par sous-groupe.

Usage :
    python -X utf8 CORE/research/audit_bot2v6_source_attribution.py --date 2026-05-11
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


ROOT = Path(__file__).resolve().parents[2]


def load_trades(date_str: str) -> tuple[list[dict], list[dict]]:
    """Returns (opens, closes) lists of trade events."""
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_paper_v6.jsonl"
    opens, closes = [], []
    if not fp.exists():
        print(f"[ERR] {fp} not found")
        return opens, closes
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            code = rec.get("code", "")
            if code == "TRADE_OPEN":
                opens.append(rec)
            elif code in ("TRADE_CLOSE", "TRADE_CLOSE_TP", "TRADE_CLOSE_SL", "TRADE_CLOSE_TRAIL"):
                closes.append(rec)
    return opens, closes


def load_stale_events(date_str: str) -> list[datetime]:
    """Returns list of V4_BAR_STALE event timestamps."""
    fp = ROOT / "LOGS" / "events" / f"events_{date_str.replace('-','')}_paper_v6.jsonl"
    stale_ts = []
    if not fp.exists():
        return stale_ts
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("code") == "V6_V4_BAR_STALE":
                try:
                    stale_ts.append(parse_ts(rec["ts"]))
                except Exception:
                    pass
    return stale_ts


def was_stale_at(entry_ts: datetime, stale_events: list[datetime], window_sec: int = 90) -> bool:
    """Returns True if any V4_BAR_STALE event occurred within window_sec before entry."""
    lo = entry_ts - timedelta(seconds=window_sec)
    hi = entry_ts + timedelta(seconds=5)  # +5s tolerance after
    for ts in stale_events:
        if lo <= ts <= hi:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-05-11")
    args = ap.parse_args()

    opens, closes = load_trades(args.date)
    stale_events = load_stale_events(args.date)

    print(f"=== Bot 2 V6 audit source attribution — {args.date} ===")
    print(f"Trades opened: {len(opens)}")
    print(f"Trades closed: {len(closes)}")
    print(f"V4_BAR_STALE events: {len(stale_events)}")
    print()

    # Match opens to closes by signal_id
    open_by_id = {r.get("signal_id"): r for r in opens if r.get("signal_id")}
    matched_trades = []
    for c in closes:
        sid = c.get("signal_id")
        if sid and sid in open_by_id:
            matched_trades.append((open_by_id[sid], c))
        else:
            # Try match by symbol + time proximity (close just after open)
            c_ctx = c.get("ctx", {})
            c_ts = parse_ts(c["ts"])
            c_sym = c_ctx.get("sym")
            for o in opens:
                o_ts = parse_ts(o["ts"])
                o_sym = o.get("ctx", {}).get("sym")
                if o_sym == c_sym and o_ts < c_ts and (c_ts - o_ts).total_seconds() < 7200:
                    matched_trades.append((o, c))
                    break

    if not matched_trades:
        print("[WARN] No matched open/close pairs")
        return

    # Stats par source
    rows = []
    for o, c in matched_trades:
        entry_ts = parse_ts(o["ts"])
        exit_ts = parse_ts(c["ts"])
        pnl_t = c.get("ctx", {}).get("pnl", 0)
        sym = o.get("ctx", {}).get("sym", "?")
        direction = o.get("ctx", {}).get("direction", "?")
        size = o.get("ctx", {}).get("size", 1)
        reason = c.get("ctx", {}).get("reason", "?")
        was_stale = was_stale_at(entry_ts, stale_events, window_sec=90)
        source = "FALLBACK_DMP" if was_stale else "V4_ENRICHED"
        dur_min = (exit_ts - entry_ts).total_seconds() / 60
        try:
            pnl_t = float(pnl_t)
        except Exception:
            pnl_t = 0
        rows.append({
            "entry": entry_ts.strftime("%H:%M:%S"),
            "exit": exit_ts.strftime("%H:%M:%S"),
            "sym": sym,
            "dir": direction,
            "size": size,
            "source": source,
            "reason": reason,
            "pnl_t": pnl_t,
            "dur_min": round(dur_min, 1),
        })

    print(f"{'Entry':<10}{'Exit':<10}{'Sym':<5}{'Dir':<6}{'Sz':<4}{'Source':<14}{'Reason':<10}{'Pnl_t':<8}{'Dur_min':<8}")
    print("-" * 80)
    for r in rows:
        print(f"{r['entry']:<10}{r['exit']:<10}{r['sym']:<5}{r['dir']:<6}{r['size']:<4}"
              f"{r['source']:<14}{r['reason']:<10}{r['pnl_t']:<8}{r['dur_min']:<8}")

    print()
    # Agrégats
    groups = defaultdict(list)
    for r in rows:
        groups[r["source"]].append(r)
    print("=== Stats par source ===")
    print(f"{'Source':<16}{'N':<5}{'Wins':<6}{'WR%':<7}{'Mean_pnl_t':<12}{'Sum_pnl_t':<10}")
    print("-" * 60)
    for src in ["V4_ENRICHED", "FALLBACK_DMP"]:
        g = groups.get(src, [])
        n = len(g)
        wins = sum(1 for r in g if r["pnl_t"] > 0)
        wr = round(100 * wins / max(n, 1), 1)
        mean_pnl = round(sum(r["pnl_t"] for r in g) / max(n, 1), 2)
        sum_pnl = round(sum(r["pnl_t"] for r in g), 2)
        print(f"{src:<16}{n:<5}{wins:<6}{wr:<7}{mean_pnl:<12}{sum_pnl:<10}")

    total_n = len(rows)
    total_wins = sum(1 for r in rows if r["pnl_t"] > 0)
    total_wr = round(100 * total_wins / max(total_n, 1), 1)
    total_sum = round(sum(r["pnl_t"] for r in rows), 2)
    print(f"{'TOTAL':<16}{total_n:<5}{total_wins:<6}{total_wr:<7}{'':<12}{total_sum:<10}")


if __name__ == "__main__":
    main()
