"""Audit : combien de $ aurait fait gagner/perdre le veto SHORT au bottom sur 7 jours.

Critere veto Jackson 11/05 (memory feedback_swing_proximity_veto.md) :
  - SHORT ET range_pos <= 30 (ChaseBottomGate symetrique)
  - OU SHORT ET dist_swing_low > -30t NQ / -12t ES (trop proche swing low)

Pour chaque trade SHORT Bot 1 + Bot 2 V6 :
  1. Lire la barre DMP JSONL au timestamp d'entry
  2. Verifier range_pos + dist_swing_low
  3. Tag WOULD_BLOCK si critere
  4. Sommer pnl economise (SL evite) - pnl perdu (TP manque)

Usage :
    python -X utf8 CORE/research/audit_short_at_bottom_veto.py --days 8 --end 2026-05-12
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_trades(date_str: str, suffix: str) -> dict[str, dict]:
    fp = ROOT / "LOGS" / "trading" / f"trading_{date_str.replace('-','')}_{suffix}.jsonl"
    trades = {}
    if not fp.exists():
        return trades
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
                trades.setdefault(sid, {}).update({
                    "entry_ts": parse_ts(rec["ts"]),
                    "sym": ctx.get("sym"),
                    "dir": ctx.get("direction"),
                    "entry_price": ctx.get("price"),
                    "size": ctx.get("size", 3),
                })
            elif code in ("TRADE_CLOSE_TP", "TRADE_CLOSE_SL", "TRADE_CLOSE_TRAIL", "TRADE_CLOSE_TRAILING_TP"):
                trades.setdefault(sid, {}).update({
                    "exit_ts": parse_ts(rec["ts"]),
                    "pnl_t": float(ctx.get("pnl", 0)),
                    "reason": code.replace("TRADE_CLOSE_", ""),
                })
    return trades


def load_dmp_bar_at(sym: str, target_ts: datetime) -> dict | None:
    """Lit la barre DMP la plus proche AVANT target_ts (within 90s)."""
    date_str = target_ts.strftime("%Y%m%d")
    fp = ROOT / "DATA" / sym / f"{date_str}_{sym}.jsonl"
    if not fp.exists():
        return None
    best_bar = None
    best_dt = 99999
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            try:
                bar_ts = datetime.fromtimestamp(int(j.get("ts", 0)) / 1000, tz=timezone.utc)
            except Exception:
                continue
            if bar_ts <= target_ts:
                dt = (target_ts - bar_ts).total_seconds()
                if dt < best_dt and dt < 120:  # within 120s
                    best_dt = dt
                    best_bar = j
    return best_bar


SWING_PROXIMITY_THRESHOLDS_T = {"NQ": 30, "ES": 12, "MGC": 30}
RANGE_POS_BOTTOM_THRESHOLD = 30


def would_block_short(trade: dict, bar: dict | None) -> tuple[bool, str]:
    """Returns (would_block, reason). Veto Jackson 11/05."""
    if trade.get("dir") != "SHORT":
        return False, "not_short"
    if not bar:
        return False, "no_bar"
    sym = trade.get("sym", "NQ")

    rp = bar.get("range_pos")
    try:
        rp = float(rp) if rp is not None else None
    except (ValueError, TypeError):
        rp = None

    d_swL = bar.get("dist_swing_low")
    try:
        d_swL = float(d_swL) if d_swL is not None else None
    except (ValueError, TypeError):
        d_swL = None

    block_reasons = []
    # Critere 1 : range_pos <= 30
    if rp is not None and rp <= RANGE_POS_BOTTOM_THRESHOLD:
        block_reasons.append(f"range_pos={rp:.1f}<=30")
    # Critere 2 : dist_swing_low proche (dist negative entre -threshold et 0)
    thr = SWING_PROXIMITY_THRESHOLDS_T.get(sym, 30)
    if d_swL is not None and -thr <= d_swL <= 0:
        block_reasons.append(f"d_swL={d_swL:.0f}t > -{thr}t")

    if block_reasons:
        return True, " | ".join(block_reasons)
    return False, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--end", default="2026-05-12")
    args = ap.parse_args()

    end_date = datetime.fromisoformat(args.end).date()
    dates = [(end_date - timedelta(days=i)).isoformat() for i in range(args.days)]

    all_trades = []
    for d in dates:
        for suffix, bot_name in [("paper", "BOT1"), ("paper_v6", "BOT2V6")]:
            ts = load_trades(d, suffix)
            for sid, t in ts.items():
                if "pnl_t" in t and t.get("dir") == "SHORT":
                    t["bot"] = bot_name
                    t["signal_id"] = sid
                    all_trades.append(t)

    print(f"=== Audit veto SHORT bottom — {args.days}j ({dates[-1]} -> {dates[0]}) ===")
    print(f"Total SHORT trades : {len(all_trades)}")
    print()

    # Detail trade par trade
    rows = []
    for t in all_trades:
        bar = load_dmp_bar_at(t["sym"], t["entry_ts"])
        would_block, reason = would_block_short(t, bar)
        rp = bar.get("range_pos") if bar else None
        d_swL = bar.get("dist_swing_low") if bar else None
        rows.append({
            **t,
            "bar_range_pos": rp,
            "bar_dist_swing_low": d_swL,
            "would_block": would_block,
            "veto_reason": reason,
        })

    # Tableau detail
    print(f"{'Date':<11}{'Time':<10}{'Bot':<8}{'Sym':<5}{'Reason':<8}{'Pnl_t':<8}"
          f"{'rp':<7}{'d_swL':<9}{'WOULD_BLOCK':<13}{'Veto_reason'}")
    print("-" * 120)
    for r in sorted(rows, key=lambda x: x["entry_ts"]):
        rp_str = f"{float(r['bar_range_pos']):.1f}" if r['bar_range_pos'] is not None else "?"
        dsl_str = f"{float(r['bar_dist_swing_low']):.0f}" if r['bar_dist_swing_low'] is not None else "?"
        flag = "BLOCK" if r["would_block"] else "ok"
        date_s = r["entry_ts"].strftime("%Y-%m-%d")
        time_s = r["entry_ts"].strftime("%H:%M:%S")
        print(f"{date_s:<11}{time_s:<10}{r['bot']:<8}{r['sym']:<5}"
              f"{r['reason'][:7]:<8}{r['pnl_t']:<8}{rp_str:<7}{dsl_str:<9}"
              f"{flag:<13}{r['veto_reason'][:40]}")

    # Stats avec/sans veto
    print()
    print("=== Stats globales 7j ===")
    blocked = [r for r in rows if r["would_block"]]
    allowed = [r for r in rows if not r["would_block"]]
    n_b = len(blocked)
    n_a = len(allowed)
    sum_blocked = sum(r["pnl_t"] for r in blocked)
    sum_allowed = sum(r["pnl_t"] for r in allowed)
    sum_total = sum(r["pnl_t"] for r in rows)

    print(f"Total trades SHORT : {len(rows)}")
    print(f"  WOULD_BLOCK : {n_b} trades, pnl_t total = {sum_blocked:+.1f}t")
    print(f"  ALLOWED     : {n_a} trades, pnl_t total = {sum_allowed:+.1f}t")
    print(f"  TOTAL (sans veto, ACTUEL) = {sum_total:+.1f}t")
    print(f"  TOTAL (AVEC veto, simule) = {sum_allowed:+.1f}t")
    print(f"  Delta veto                = {sum_allowed - sum_total:+.1f}t")
    print()

    # Pour les bloques : combien etaient SL vs TP
    if blocked:
        b_sl = [r for r in blocked if r["pnl_t"] <= 0]
        b_tp = [r for r in blocked if r["pnl_t"] > 0]
        print(f"Trades qui auraient ete bloques :")
        print(f"  Perdants (SL evites) : {len(b_sl)} trades, pnl_t = {sum(r['pnl_t'] for r in b_sl):+.1f}t (economie potentielle)")
        print(f"  Gagnants (TP rates)  : {len(b_tp)} trades, pnl_t = {sum(r['pnl_t'] for r in b_tp):+.1f}t (manque a gagner)")
        delta_block = sum(r['pnl_t'] for r in b_sl) + sum(r['pnl_t'] for r in b_tp)
        print(f"  Net delta veto       : {-delta_block:+.1f}t (positif = veto gagnant)")

    # $ approximatif (3 micros NQ = $1.50/tick, ES = $3.75/tick)
    def tick_to_usd(r):
        tv = 1.25 if r["sym"] == "ES" else 0.50
        n = r.get("size", 3)
        return r["pnl_t"] * tv * n

    sum_blocked_usd = sum(tick_to_usd(r) for r in blocked)
    sum_allowed_usd = sum(tick_to_usd(r) for r in allowed)
    sum_total_usd = sum_blocked_usd + sum_allowed_usd
    print()
    print(f"=== Impact $ (3 micros) ===")
    print(f"Sans veto (actuel)   : ${sum_total_usd:+.2f}")
    print(f"Avec veto (simule)   : ${sum_allowed_usd:+.2f}")
    print(f"Delta veto           : ${sum_allowed_usd - sum_total_usd:+.2f}")
    if sum_allowed_usd - sum_total_usd > 0:
        print(f"  → Veto AURAIT FAIT GAGNER ${sum_allowed_usd - sum_total_usd:.2f} sur {args.days}j")
    else:
        print(f"  → Veto AURAIT FAIT PERDRE ${abs(sum_allowed_usd - sum_total_usd):.2f} sur {args.days}j")


if __name__ == "__main__":
    main()
