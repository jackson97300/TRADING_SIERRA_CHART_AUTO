"""Audit comparatif Bot 1 DMP vs Bot 2 V6 sur 7 jours.

Questions :
1. Performance : WR, sum_pnl, mean_pnl, sharpe-like par bot
2. Diversification : trades pris au meme moment (overlap) vs trades exclusifs
3. Direction : meme direction sur meme symbole, ou divergents
4. Verdict edge : Bot 2 V6 apporte-t-il de la valeur vs Bot 1 ?

Usage :
    python -X utf8 CORE/research/audit_bot1_vs_bot2v6_compare.py --days 7
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def load_trades_for_bot(date_str: str, bot_suffix: str) -> tuple[list[dict], list[dict]]:
    """bot_suffix = 'paper' (Bot 1) ou 'paper_v6' (Bot 2 V6)."""
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_{bot_suffix}.jsonl"
    opens, closes = [], []
    if not fp.exists():
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


def match_trades(opens: list[dict], closes: list[dict]) -> list[tuple[dict, dict]]:
    """Match opens to closes via signal_id ou proximity."""
    open_by_id = {r.get("signal_id"): r for r in opens if r.get("signal_id")}
    matched = []
    used_opens = set()
    for c in closes:
        sid = c.get("signal_id")
        if sid and sid in open_by_id and sid not in used_opens:
            matched.append((open_by_id[sid], c))
            used_opens.add(sid)
        else:
            c_ts = parse_ts(c["ts"])
            c_sym = c.get("ctx", {}).get("sym")
            best_o = None
            best_dt = 99999
            for o in opens:
                o_sid = o.get("signal_id")
                if o_sid in used_opens:
                    continue
                o_ts = parse_ts(o["ts"])
                o_sym = o.get("ctx", {}).get("sym")
                if o_sym == c_sym and o_ts < c_ts:
                    dt = (c_ts - o_ts).total_seconds()
                    if dt < best_dt and dt < 14400:  # 4h max
                        best_dt = dt
                        best_o = o
            if best_o:
                matched.append((best_o, c))
                if best_o.get("signal_id"):
                    used_opens.add(best_o.get("signal_id"))
    return matched


def trade_to_row(o: dict, c: dict, bot: str) -> dict:
    return {
        "bot": bot,
        "entry_ts": parse_ts(o["ts"]),
        "exit_ts": parse_ts(c["ts"]),
        "sym": o.get("ctx", {}).get("sym", "?"),
        "dir": o.get("ctx", {}).get("direction", "?"),
        "size": o.get("ctx", {}).get("size", 1),
        "pnl_t": float(c.get("ctx", {}).get("pnl", 0)),
        "reason": c.get("ctx", {}).get("reason", c.get("code", "?")),
    }


def find_overlap(t1: dict, others: list[dict], window_min: int = 5) -> dict | None:
    """Cherche trade dans others ayant entry_ts dans [t1.entry-W, t1.entry+W] et meme sym/dir."""
    lo = t1["entry_ts"] - timedelta(minutes=window_min)
    hi = t1["entry_ts"] + timedelta(minutes=window_min)
    for o in others:
        if o["sym"] != t1["sym"]:
            continue
        if lo <= o["entry_ts"] <= hi:
            return o
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default = today UTC)")
    args = ap.parse_args()

    end_date = datetime.fromisoformat(args.end).date() if args.end else datetime.now(timezone.utc).date()
    dates = [(end_date - timedelta(days=i)).isoformat() for i in range(args.days)]

    bot1_trades = []
    bot2_trades = []
    for d in dates:
        o1, c1 = load_trades_for_bot(d, "paper")
        for op, cl in match_trades(o1, c1):
            bot1_trades.append(trade_to_row(op, cl, "BOT1"))
        o2, c2 = load_trades_for_bot(d, "paper_v6")
        for op, cl in match_trades(o2, c2):
            bot2_trades.append(trade_to_row(op, cl, "BOT2V6"))

    print(f"=== Comparaison Bot 1 DMP vs Bot 2 V6 — {args.days}j (depuis {dates[-1]}) ===")
    print(f"Bot 1 trades closed : {len(bot1_trades)}")
    print(f"Bot 2 V6 trades closed : {len(bot2_trades)}")
    print()

    # Stats par bot
    print(f"{'Bot':<10}{'N':<5}{'Wins':<6}{'WR%':<7}{'Mean_pnl_t':<12}{'Sum_pnl_t':<10}")
    print("-" * 60)
    for label, trades in [("BOT1_DMP", bot1_trades), ("BOT2_V6", bot2_trades)]:
        n = len(trades)
        if n == 0:
            print(f"{label:<10}{n:<5}{0:<6}{0:<7}{0:<12}{0:<10}")
            continue
        wins = sum(1 for t in trades if t["pnl_t"] > 0)
        wr = round(100 * wins / n, 1)
        mean = round(sum(t["pnl_t"] for t in trades) / n, 2)
        s = round(sum(t["pnl_t"] for t in trades), 1)
        print(f"{label:<10}{n:<5}{wins:<6}{wr:<7}{mean:<12}{s:<10}")

    # Overlap : Bot 2 V6 a-t-il pris les memes trades que Bot 1 ?
    print()
    print("=== Diversification (overlap +-5min sur meme symbole) ===")
    bot2_overlap = 0
    bot2_exclusive = 0
    bot2_same_dir = 0
    bot2_opposite_dir = 0
    for t2 in bot2_trades:
        match_in_bot1 = find_overlap(t2, bot1_trades, window_min=5)
        if match_in_bot1:
            bot2_overlap += 1
            if match_in_bot1["dir"] == t2["dir"]:
                bot2_same_dir += 1
            else:
                bot2_opposite_dir += 1
        else:
            bot2_exclusive += 1
    print(f"Bot 2 V6 trades ayant equivalent Bot 1 +-5min : {bot2_overlap} / {len(bot2_trades)}")
    print(f"  same direction (correle, doublon)   : {bot2_same_dir}")
    print(f"  opposite direction (signal contraire) : {bot2_opposite_dir}")
    print(f"Bot 2 V6 trades EXCLUSIFS (Bot 1 absent) : {bot2_exclusive}")

    # Reverse : Bot 1 trades sans equivalent Bot 2 V6
    bot1_overlap = 0
    bot1_exclusive = 0
    for t1 in bot1_trades:
        match_in_bot2 = find_overlap(t1, bot2_trades, window_min=5)
        if match_in_bot2:
            bot1_overlap += 1
        else:
            bot1_exclusive += 1
    print(f"Bot 1 trades EXCLUSIFS (Bot 2 V6 absent) : {bot1_exclusive}")

    # Stats trades EXCLUSIFS Bot 2 V6 (= la vraie valeur ajoutee)
    print()
    print("=== Performance trades EXCLUSIFS Bot 2 V6 (la vraie valeur ajoutee) ===")
    excl = []
    for t2 in bot2_trades:
        if find_overlap(t2, bot1_trades, window_min=5) is None:
            excl.append(t2)
    if excl:
        n = len(excl)
        wins = sum(1 for t in excl if t["pnl_t"] > 0)
        wr = round(100 * wins / n, 1)
        mean = round(sum(t["pnl_t"] for t in excl) / n, 2)
        s = round(sum(t["pnl_t"] for t in excl), 1)
        print(f"  N={n} Wins={wins} WR={wr}% Mean={mean}t Sum={s}t")
        if s > 0:
            print(f"  → Bot 2 V6 a CRÉÉ de la valeur exclusive : +{s}t en {n} trades")
        else:
            print(f"  → Bot 2 V6 a PERDU sur ses trades exclusifs : {s}t en {n} trades")
    else:
        print("  Aucun trade exclusif Bot 2 V6 = c'est strictement un sous-ensemble Bot 1")

    # Detail trade-by-trade
    print()
    print("=== Detail Bot 2 V6 trades (chronologique) ===")
    bot2_trades_sorted = sorted(bot2_trades, key=lambda t: t["entry_ts"])
    print(f"{'Date':<12}{'Entry':<10}{'Sym':<5}{'Dir':<6}{'Pnl_t':<8}{'Overlap_Bot1':<15}")
    for t in bot2_trades_sorted:
        ovl = find_overlap(t, bot1_trades, window_min=5)
        ovl_str = f"YES({ovl['dir']})" if ovl else "NO"
        print(f"{t['entry_ts'].strftime('%Y-%m-%d'):<12}"
              f"{t['entry_ts'].strftime('%H:%M:%S'):<10}"
              f"{t['sym']:<5}{t['dir']:<6}{t['pnl_t']:<8}{ovl_str:<15}")


if __name__ == "__main__":
    main()
