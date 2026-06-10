"""Backtest SL respirent — comparer scenarios SL=15/30/50/60 sur trades NQ Bot 3 v3.

Chantier 02/06/2026 : Jackson "SL ridicules ne laissent pas respirer le prix".

Methodologie :
- Charge TRADE_OPEN Bot 3 v3 sur 8 jours (24-29/05, 31/05, 01/06)
- Pour chaque trade : entry_price + side + entry_ts
- Charge bars 1m NQ live_enriched de l'entry au timeout 30 min
- Simule 4 scenarios SL fixe + TP fixe (R:R 1.5) :
    A : SL=15t / TP=22.5t (fallback baseline actuel)
    B : SL=30t / TP=45t   (cap max actuel)
    C : SL=50t / TP=75t   (respire modere)
    D : SL=60t / TP=90t   (respire large)
- Compare WR, PF, EV, distribution outcome

Tick NQ = 0.25 pt. 1 contrat NQ standard = $1.25/tick.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

TICK_SIZE = 0.25
TICK_USD = 1.25  # NQ E-mini standard 1 contrat
TIMEOUT_MIN = 30
TARGET_R = 1.5

LOG_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/LOGS/bot3_v3")
BARS_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ")
DAYS = ["20260524", "20260525", "20260526", "20260527", "20260528",
        "20260529", "20260531", "20260601"]

SCENARIOS = [
    ("A_fallback15", 15, 22.5),
    ("B_cap30",      30, 45.0),
    ("C_respire50",  50, 75.0),
    ("D_respire60",  60, 90.0),
]


def parse_iso(s: str) -> datetime:
    if "Z" in s:
        s = s.replace("Z", "+00:00")
    if "+" not in s and "T" in s:
        s += "+00:00"
    return datetime.fromisoformat(s)


def load_trades_open(day: str) -> list[dict]:
    fp = LOG_DIR / f"bot3_v3_v1_{day}.jsonl"
    if not fp.exists():
        return []
    trades = []
    with open(fp, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get("event") == "TRADE_OPEN":
                    trades.append(e)
            except Exception:
                pass
    return trades


def load_bars_minimal(day: str) -> list[dict]:
    """Load bars NQ jour : juste ts_event + high + low + close (skip 491 features)."""
    fp = BARS_DIR / f"{day}_NQ.jsonl"
    if not fp.exists():
        return []
    bars = []
    with open(fp, encoding="utf-8") as f:
        for line in f:
            try:
                b = json.loads(line)
                ts = b.get("ts_event")
                if ts is None:
                    continue
                bars.append({
                    "ts": parse_iso(ts),
                    "high": float(b.get("high", 0)),
                    "low": float(b.get("low", 0)),
                    "close": float(b.get("close", 0)),
                })
            except Exception:
                pass
    bars.sort(key=lambda x: x["ts"])
    return bars


def simulate(trade: dict, bars: list[dict], sl_ticks: float, tp_ticks: float
             ) -> tuple[str, float, float]:
    """Simule un trade avec SL/TP fixe.

    Returns: (outcome, exit_price, pnl_usd)
        outcome in {SL, TP, TIMEOUT, NO_FILL}
    """
    entry_price = float(trade["entry_price"])
    side = trade["side"]
    entry_ts = parse_iso(trade["ts"])
    timeout_ts = entry_ts + timedelta(minutes=TIMEOUT_MIN)

    if side == "LONG":
        sl_price = entry_price - sl_ticks * TICK_SIZE
        tp_price = entry_price + tp_ticks * TICK_SIZE
    else:
        sl_price = entry_price + sl_ticks * TICK_SIZE
        tp_price = entry_price - tp_ticks * TICK_SIZE

    for bar in bars:
        if bar["ts"] < entry_ts:
            continue
        if bar["ts"] > timeout_ts:
            # Timeout : exit au bar close
            exit_price = bar["close"]
            if side == "LONG":
                pnl_ticks = (exit_price - entry_price) / TICK_SIZE
            else:
                pnl_ticks = (entry_price - exit_price) / TICK_SIZE
            return "TIMEOUT", exit_price, pnl_ticks * TICK_USD

        # Check hit SL ou TP dans bar
        if side == "LONG":
            sl_hit = bar["low"] <= sl_price
            tp_hit = bar["high"] >= tp_price
        else:
            sl_hit = bar["high"] >= sl_price
            tp_hit = bar["low"] <= tp_price

        # Si les deux dans la meme bar : conservateur, on suppose SL d'abord (worst case)
        if sl_hit and tp_hit:
            return "SL", sl_price, -sl_ticks * TICK_USD
        if sl_hit:
            return "SL", sl_price, -sl_ticks * TICK_USD
        if tp_hit:
            return "TP", tp_price, tp_ticks * TICK_USD

    return "NO_FILL", entry_price, 0.0


def compute_stats(results: list[dict]) -> dict:
    wins = [r for r in results if r["pnl_usd"] > 0.01]
    losses = [r for r in results if r["pnl_usd"] < -0.01]
    bes = [r for r in results if abs(r["pnl_usd"]) <= 0.01]
    n = len(results)
    n_w = len(wins)
    n_l = len(losses)
    pnl_total = sum(r["pnl_usd"] for r in results)
    gross_win = sum(r["pnl_usd"] for r in wins)
    gross_loss = -sum(r["pnl_usd"] for r in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    wr = 100 * n_w / max(n - len(bes), 1)
    ev = pnl_total / max(n, 1)
    n_timeout = sum(1 for r in results if r["outcome"] == "TIMEOUT")
    n_sl = sum(1 for r in results if r["outcome"] == "SL")
    n_tp = sum(1 for r in results if r["outcome"] == "TP")
    n_nofill = sum(1 for r in results if r["outcome"] == "NO_FILL")
    return {
        "n": n, "W": n_w, "L": n_l, "BE": len(bes),
        "WR": wr, "PF": pf, "EV_USD": ev, "PnL": pnl_total,
        "SL": n_sl, "TP": n_tp, "TIMEOUT": n_timeout, "NO_FILL": n_nofill,
    }


def main():
    print("=" * 80)
    print("BACKTEST SL RESPIRENT — Bot 3 v3 NQ, 8 jours (24-29/05 + 31/05 + 01/06)")
    print("=" * 80)

    # Load all trades + bars
    all_trades = []
    bars_by_day = {}
    for day in DAYS:
        trades = load_trades_open(day)
        bars = load_bars_minimal(day)
        bars_by_day[day] = bars
        for t in trades:
            t["_day"] = day
        all_trades.extend(trades)
        print(f"  {day} : {len(trades)} trades, {len(bars)} bars")

    print(f"\nTotal trades historiques : {len(all_trades)}")
    if not all_trades:
        print("Aucun trade — abort")
        return

    # Run 4 scenarios
    print(f"\n{'Scenario':<15} {'N':>4} {'W':>4} {'L':>4} {'BE':>4} {'WR%':>6} {'PF':>6} {'EV$':>7} {'PnL$':>10} {'SL':>4} {'TP':>4} {'TIMEO':>6} {'NF':>4}")
    print("-" * 100)

    all_stats = {}
    for scen_name, sl_ticks, tp_ticks in SCENARIOS:
        results = []
        for t in all_trades:
            day = t["_day"]
            bars = bars_by_day.get(day, [])
            outcome, exit_price, pnl_usd = simulate(t, bars, sl_ticks, tp_ticks)
            results.append({
                "signal_id": t.get("signal_id"),
                "day": day,
                "side": t["side"],
                "entry_price": t["entry_price"],
                "exit_price": exit_price,
                "outcome": outcome,
                "pnl_usd": pnl_usd,
            })
        stats = compute_stats(results)
        all_stats[scen_name] = stats
        pf_str = f"{stats['PF']:.2f}" if stats['PF'] != float('inf') else "inf"
        print(f"{scen_name:<15} {stats['n']:>4} {stats['W']:>4} {stats['L']:>4} {stats['BE']:>4} "
              f"{stats['WR']:>5.1f}% {pf_str:>6} {stats['EV_USD']:>+6.2f} {stats['PnL']:>+9.2f} "
              f"{stats['SL']:>4} {stats['TP']:>4} {stats['TIMEOUT']:>6} {stats['NO_FILL']:>4}")

    # Delta vs baseline B
    base = all_stats["B_cap30"]
    print("\n" + "=" * 80)
    print(f"DELTAS vs B_cap30 (baseline actuelle Bot 3 v3 cap)")
    print("=" * 80)
    for scen_name, stats in all_stats.items():
        if scen_name == "B_cap30":
            continue
        dpnl = stats["PnL"] - base["PnL"]
        dwr = stats["WR"] - base["WR"]
        dev = stats["EV_USD"] - base["EV_USD"]
        print(f"  {scen_name:<15} : PnL {dpnl:+.2f} | WR {dwr:+.1f}pp | EV {dev:+.2f}$ | "
              f"SL hits {stats['SL']} vs {base['SL']} | TP hits {stats['TP']} vs {base['TP']}")

    # Per-day breakdown for scenario D_respire60
    print("\n" + "=" * 80)
    print(f"DETAIL PAR JOUR — Scenario D_respire60 vs B_cap30")
    print("=" * 80)
    for day in DAYS:
        day_trades = [t for t in all_trades if t["_day"] == day]
        if not day_trades:
            continue
        bars = bars_by_day.get(day, [])
        for scen_name, sl_t, tp_t in [("B_cap30", 30, 45), ("D_respire60", 60, 90)]:
            pnl_day = 0.0
            n_w = n_l = n_to = 0
            for t in day_trades:
                outcome, _, pnl = simulate(t, bars, sl_t, tp_t)
                pnl_day += pnl
                if pnl > 0.01: n_w += 1
                elif pnl < -0.01: n_l += 1
                if outcome == "TIMEOUT": n_to += 1
            tag = "BASE" if scen_name == "B_cap30" else "TEST"
            print(f"  {day} {tag} : {len(day_trades)} trades, {n_w}W/{n_l}L, {n_to} TIMEOUT, PnL {pnl_day:+.2f}$")
        print()


if __name__ == "__main__":
    main()
