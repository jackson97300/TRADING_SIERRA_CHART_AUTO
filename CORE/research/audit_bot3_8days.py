"""Audit Bot 3 MP (Databento Sim1) sur 8 jours.

Mesure :
- Performance par jour
- WR / mean_pnl / sum_pnl globaux
- Distribution close reason (TP/SL/TIMEOUT/TRAIL)
- Distribution par symbole et niveau Tier 1/2/3
- Overlap vs Bot 1 et Bot 2 V6 (diversification source de donnees reelle)

Usage :
    python -X utf8 CORE/research/audit_bot3_8days.py --days 8 --end 2026-05-12
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


def load_bot3_trades(date_str: str) -> tuple[list[dict], list[dict]]:
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_paper_v2.jsonl"
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
            if code == "BOT3_TRADE_OPEN":
                opens.append(rec)
            elif code == "BOT3_TRADE_CLOSE":
                closes.append(rec)
    return opens, closes


def load_bot1_trades(date_str: str) -> tuple[list[dict], list[dict]]:
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_paper.jsonl"
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


def load_bot2v6_trades(date_str: str) -> tuple[list[dict], list[dict]]:
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_paper_v6.jsonl"
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
    open_by_id = {r.get("signal_id"): r for r in opens if r.get("signal_id")}
    used = set()
    matched = []
    for c in closes:
        sid = c.get("signal_id")
        if sid and sid in open_by_id and sid not in used:
            matched.append((open_by_id[sid], c))
            used.add(sid)
        else:
            # match by sym + level + proximity (Bot 3 specifique : level)
            c_ts = parse_ts(c["ts"])
            c_sym = c.get("ctx", {}).get("sym")
            c_level = c.get("ctx", {}).get("level")
            best_o, best_dt = None, 99999
            for o in opens:
                osid = o.get("signal_id")
                if osid in used:
                    continue
                o_ts = parse_ts(o["ts"])
                o_sym = o.get("ctx", {}).get("sym")
                o_level = o.get("ctx", {}).get("level")
                if o_sym == c_sym and o_level == c_level and o_ts < c_ts:
                    dt = (c_ts - o_ts).total_seconds()
                    if dt < best_dt and dt < 14400:
                        best_dt = dt
                        best_o = o
            if best_o:
                matched.append((best_o, c))
                if best_o.get("signal_id"):
                    used.add(best_o.get("signal_id"))
    return matched


def bot3_row(o: dict, c: dict) -> dict:
    return {
        "entry_ts": parse_ts(o["ts"]),
        "exit_ts": parse_ts(c["ts"]),
        "sym": o.get("ctx", {}).get("sym", "?"),
        "level": o.get("ctx", {}).get("level", "?"),
        "tier": o.get("ctx", {}).get("tier", "?"),
        "direction": o.get("ctx", {}).get("direction", "?"),
        "pnl_t": float(c.get("ctx", {}).get("pnl", 0)),
        "reason": c.get("ctx", {}).get("reason", "?"),
        "mfe": c.get("ctx", {}).get("mfe", 0),
        "mae": c.get("ctx", {}).get("mae", 0),
        "dur_s": c.get("ctx", {}).get("dur", 0),
    }


def bot12_row(o: dict, c: dict, bot: str) -> dict:
    return {
        "bot": bot,
        "entry_ts": parse_ts(o["ts"]),
        "exit_ts": parse_ts(c["ts"]),
        "sym": o.get("ctx", {}).get("sym", "?"),
        "dir": o.get("ctx", {}).get("direction", "?"),
        "pnl_t": float(c.get("ctx", {}).get("pnl", 0)),
    }


def find_overlap(target: dict, others: list[dict], window_min: int = 5) -> dict | None:
    lo = target["entry_ts"] - timedelta(minutes=window_min)
    hi = target["entry_ts"] + timedelta(minutes=window_min)
    for o in others:
        if o["sym"] != target["sym"]:
            continue
        if lo <= o["entry_ts"] <= hi:
            return o
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    end_date = datetime.fromisoformat(args.end).date() if args.end else datetime.now(timezone.utc).date()
    dates = [(end_date - timedelta(days=i)).isoformat() for i in range(args.days)]

    bot3_trades = []
    bot1_trades = []
    bot2_trades = []
    daily_bot3 = defaultdict(list)

    for d in dates:
        o3, c3 = load_bot3_trades(d)
        for op, cl in match_trades(o3, c3):
            r = bot3_row(op, cl)
            bot3_trades.append(r)
            daily_bot3[d].append(r)
        o1, c1 = load_bot1_trades(d)
        for op, cl in match_trades(o1, c1):
            bot1_trades.append(bot12_row(op, cl, "BOT1"))
        o2, c2 = load_bot2v6_trades(d)
        for op, cl in match_trades(o2, c2):
            bot2_trades.append(bot12_row(op, cl, "BOT2V6"))

    print(f"=== AUDIT Bot 3 MP — {args.days}j ({dates[-1]} → {dates[0]}) ===")
    print(f"Bot 3 trades closed : {len(bot3_trades)}")
    print(f"Bot 1 trades closed : {len(bot1_trades)} (pour overlap)")
    print(f"Bot 2 V6 trades closed : {len(bot2_trades)} (pour overlap)")
    print()

    # Daily breakdown
    print("=== Daily breakdown Bot 3 ===")
    print(f"{'Date':<12}{'N':<5}{'Wins':<6}{'WR%':<7}{'Sum_pnl_t':<10}{'Sum_$':<10}")
    print("-" * 60)
    for d in sorted(daily_bot3.keys()):
        trades = daily_bot3[d]
        n = len(trades)
        wins = sum(1 for t in trades if t["pnl_t"] > 0)
        wr = round(100 * wins / max(n, 1), 1)
        s_t = round(sum(t["pnl_t"] for t in trades), 1)
        # Bot 3 = Sim1, 1 micro per trade, NQ tick $0.50, ES tick $1.25
        s_d = sum(t["pnl_t"] * (1.25 if t["sym"] == "ES" else 0.50) for t in trades)
        print(f"{d:<12}{n:<5}{wins:<6}{wr:<7}{s_t:<10}${round(s_d, 1):<8}")
    print()

    # Global stats Bot 3
    print("=== Bot 3 stats globales ===")
    n = len(bot3_trades)
    if n == 0:
        print("No bot 3 trades")
        return
    wins = sum(1 for t in bot3_trades if t["pnl_t"] > 0)
    wr = round(100 * wins / n, 1)
    mean = round(sum(t["pnl_t"] for t in bot3_trades) / n, 2)
    s_t = round(sum(t["pnl_t"] for t in bot3_trades), 1)
    s_d = sum(t["pnl_t"] * (1.25 if t["sym"] == "ES" else 0.50) for t in bot3_trades)
    print(f"N={n} Wins={wins} WR={wr}% Mean={mean}t Sum={s_t}t (≈ ${round(s_d, 1)})")
    print()

    # Distribution reason
    print("=== Distribution close reason ===")
    reasons = defaultdict(list)
    for t in bot3_trades:
        reasons[t["reason"]].append(t)
    for r, ts in sorted(reasons.items(), key=lambda x: -len(x[1])):
        rn = len(ts)
        rwins = sum(1 for t in ts if t["pnl_t"] > 0)
        rwr = round(100 * rwins / max(rn, 1), 1)
        rsum = round(sum(t["pnl_t"] for t in ts), 1)
        print(f"  {r:<15} N={rn:<4} WR={rwr}% Sum={rsum}t")
    print()

    # Distribution symbol + tier
    print("=== Distribution symbol + tier ===")
    syms = defaultdict(list)
    for t in bot3_trades:
        key = f"{t['sym']}/{t['tier']}"
        syms[key].append(t)
    for k, ts in sorted(syms.items(), key=lambda x: -len(x[1])):
        rn = len(ts)
        rwins = sum(1 for t in ts if t["pnl_t"] > 0)
        rwr = round(100 * rwins / max(rn, 1), 1)
        rsum = round(sum(t["pnl_t"] for t in ts), 1)
        print(f"  {k:<15} N={rn:<4} WR={rwr}% Sum={rsum}t")
    print()

    # Diversification source de donnees REELLE : Bot 3 overlap vs Bot 1 / Bot 2 V6
    print("=== Diversification SOURCE Bot 3 (Databento) vs Bot 1/Bot 2 V6 (DMP) ===")
    bot3_overlap_bot1 = 0
    bot3_overlap_bot2 = 0
    bot3_exclusive = 0
    for t3 in bot3_trades:
        ovl_b1 = find_overlap(t3, bot1_trades, window_min=5)
        ovl_b2 = find_overlap(t3, bot2_trades, window_min=5)
        if ovl_b1:
            bot3_overlap_bot1 += 1
        if ovl_b2:
            bot3_overlap_bot2 += 1
        if not ovl_b1 and not ovl_b2:
            bot3_exclusive += 1
    print(f"Bot 3 trades = {len(bot3_trades)}")
    print(f"  overlap +-5min Bot 1   : {bot3_overlap_bot1} ({round(100*bot3_overlap_bot1/max(len(bot3_trades),1),1)}%)")
    print(f"  overlap +-5min Bot 2 V6 : {bot3_overlap_bot2} ({round(100*bot3_overlap_bot2/max(len(bot3_trades),1),1)}%)")
    print(f"  EXCLUSIFS Bot 3 (Databento pur) : {bot3_exclusive} ({round(100*bot3_exclusive/max(len(bot3_trades),1),1)}%)")

    # Trades exclusifs Bot 3
    excl = []
    for t in bot3_trades:
        if not find_overlap(t, bot1_trades, 5) and not find_overlap(t, bot2_trades, 5):
            excl.append(t)
    if excl:
        n = len(excl)
        wins = sum(1 for t in excl if t["pnl_t"] > 0)
        wr = round(100 * wins / n, 1)
        s_t = round(sum(t["pnl_t"] for t in excl), 1)
        print(f"  → Performance trades exclusifs : N={n} WR={wr}% Sum={s_t}t")
    print()

    # Detail chronologique
    print("=== Detail Bot 3 trades (last 25) ===")
    bot3_sorted = sorted(bot3_trades, key=lambda t: t["entry_ts"])
    last25 = bot3_sorted[-25:]
    print(f"{'Date':<12}{'Entry':<10}{'Sym':<5}{'Tier':<7}{'Lvl':<20}{'Reason':<12}{'Pnl_t':<8}{'MFE':<6}{'MAE':<6}")
    for t in last25:
        print(f"{t['entry_ts'].strftime('%Y-%m-%d'):<12}"
              f"{t['entry_ts'].strftime('%H:%M:%S'):<10}"
              f"{t['sym']:<5}{str(t['tier'])[:6]:<7}{str(t['level'])[:18]:<20}"
              f"{str(t['reason'])[:10]:<12}{t['pnl_t']:<8}{t['mfe']:<6}{t['mae']:<6}")


if __name__ == "__main__":
    main()
