"""Audit comparatif trailing Bot 1 vs Bot 2 V6 sur trades partagés (meme signal_id).

Strategie : matcher par signal_id (les 2 bots partagent les signaux source).
Pour chaque signal partage, comparer pnl_t Bot 1 vs Bot 2 V6 + reason close.

Usage :
    python -X utf8 CORE/research/audit_trailing_bot1_vs_bot2v6.py --days 8 --end 2026-05-12
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


def load_trades(date_str: str, suffix: str) -> dict[str, dict]:
    """Returns dict {signal_id: {entry_ts, exit_ts, sym, dir, pnl_t, reason}}"""
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_{suffix}.jsonl"
    trades = defaultdict(dict)
    if not fp.exists():
        return {}
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sid = rec.get("signal_id")
            if not sid:
                continue
            code = rec.get("code", "")
            ctx = rec.get("ctx", {})
            if code == "TRADE_OPEN":
                trades[sid].update({
                    "entry_ts": parse_ts(rec["ts"]),
                    "sym": ctx.get("sym"),
                    "dir": ctx.get("direction"),
                    "entry_price": ctx.get("price"),
                    "size": ctx.get("size"),
                })
            elif code in ("TRADE_CLOSE", "TRADE_CLOSE_TP", "TRADE_CLOSE_SL", "TRADE_CLOSE_TRAIL", "TRADE_CLOSE_TRAILING_TP"):
                trades[sid].update({
                    "exit_ts": parse_ts(rec["ts"]),
                    "pnl_t": float(ctx.get("pnl", 0)),
                    "reason": code.replace("TRADE_CLOSE_", ""),
                })
    return dict(trades)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    end_date = datetime.fromisoformat(args.end).date() if args.end else datetime.now(timezone.utc).date()
    dates = [(end_date - timedelta(days=i)).isoformat() for i in range(args.days)]

    bot1_by_sid = {}
    bot2_by_sid = {}
    for d in dates:
        b1 = load_trades(d, "paper")
        b2 = load_trades(d, "paper_v6")
        bot1_by_sid.update(b1)
        bot2_by_sid.update(b2)

    # Filtre : seulement les trades fermes des 2 cotes
    shared = []
    for sid in bot1_by_sid:
        if sid in bot2_by_sid:
            t1 = bot1_by_sid[sid]
            t2 = bot2_by_sid[sid]
            if "pnl_t" in t1 and "pnl_t" in t2:
                shared.append((sid, t1, t2))

    print(f"=== Trades partages Bot 1 + Bot 2 V6 (meme signal_id) — {args.days}j ===")
    print(f"N trades partages : {len(shared)}")
    print()

    if not shared:
        print("[WARN] Aucun trade partage")
        return

    print(f"{'Date':<12}{'Sym':<5}{'Dir':<6}{'B1_pnl':<9}{'B2_pnl':<9}{'Delta':<8}"
          f"{'B1_reason':<13}{'B2_reason':<13}{'B1_dur':<8}{'B2_dur':<8}")
    print("-" * 100)
    deltas = []
    for sid, t1, t2 in sorted(shared, key=lambda x: x[1].get("entry_ts") or datetime.min.replace(tzinfo=timezone.utc)):
        d = t1["pnl_t"] - t2["pnl_t"]
        deltas.append(d)
        b1_dur = (t1["exit_ts"] - t1["entry_ts"]).total_seconds() / 60 if "entry_ts" in t1 and "exit_ts" in t1 else 0
        b2_dur = (t2["exit_ts"] - t2["entry_ts"]).total_seconds() / 60 if "entry_ts" in t2 and "exit_ts" in t2 else 0
        date_str = t1["entry_ts"].strftime("%Y-%m-%d %H:%M") if "entry_ts" in t1 else "?"
        print(f"{date_str:<18}"
              f"{t1.get('sym','?'):<5}{t1.get('dir','?'):<6}"
              f"{t1['pnl_t']:<9}{t2['pnl_t']:<9}{d:<+8.1f}"
              f"{t1['reason'][:12]:<13}{t2['reason'][:12]:<13}"
              f"{b1_dur:<8.1f}{b2_dur:<8.1f}")

    # Agregats
    print()
    print("=== Statistiques delta (Bot 1 - Bot 2 V6) ===")
    n = len(deltas)
    sum_delta = sum(deltas)
    mean_delta = sum_delta / n
    pos_delta = sum(1 for d in deltas if d > 0)
    neg_delta = sum(1 for d in deltas if d < 0)
    zero_delta = sum(1 for d in deltas if d == 0)
    print(f"N trades partages : {n}")
    print(f"Bot 1 mieux       : {pos_delta} trades ({round(100*pos_delta/n,1)}%)")
    print(f"Bot 2 V6 mieux    : {neg_delta} trades ({round(100*neg_delta/n,1)}%)")
    print(f"Equivalent        : {zero_delta} trades ({round(100*zero_delta/n,1)}%)")
    print(f"Delta total       : {sum_delta:+.1f}t (Bot 1 - Bot 2 V6)")
    print(f"Delta moyen       : {mean_delta:+.2f}t par trade")
    if n > 0:
        # Conversion $ (3 micros NQ = $1.50/tick total, ES = $3.75)
        # Approximation : majorite NQ
        sum_d_usd = sum_delta * 1.50
        print(f"Delta total ($)   : ${sum_d_usd:+.1f} (estim NQ 3 micros)")

    # Breakdown par reason combo
    print()
    print("=== Breakdown par close reason (B1_reason / B2_reason) ===")
    combos = defaultdict(list)
    for sid, t1, t2 in shared:
        key = f"{t1['reason'][:8]} / {t2['reason'][:8]}"
        combos[key].append(t1["pnl_t"] - t2["pnl_t"])
    for k, ds in sorted(combos.items(), key=lambda x: -len(x[1])):
        sumd = sum(ds)
        meand = sumd / len(ds)
        print(f"  {k:<25} N={len(ds):<3} delta_sum={sumd:+.1f}t mean={meand:+.2f}t")


if __name__ == "__main__":
    main()
