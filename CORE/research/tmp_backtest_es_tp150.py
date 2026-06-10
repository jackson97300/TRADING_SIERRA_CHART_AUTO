"""Backtest TP=150 sur ES Bot 3 MP — Jackson directive 02/06.

Question : sur 23 trades ES historiques (83% TIMEOUT actuellement),
elargir TP de 38t a 150t change-t-il la donne ?

Scenarios :
  A_baseline : SL=32t / TP=38t  / timeout=30min  (actuel)
  B_tp150    : SL=32t / TP=150t / timeout=30min  (juste TP, voir si change)
  C_tp150_t60: SL=32t / TP=150t / timeout=60min  (TP + timeout 60min)
  D_tp150_t120: SL=32t/ TP=150t / timeout=120min (TP + timeout 2h)
  E_sl64_tp150: SL=64t/ TP=150t / timeout=60min  (SL plus large aussi)

Tick ES = 0.25 pt. 1 contrat ES standard = $12.50/tick.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

TICK_SIZE = 0.25
TICK_USD = 12.50  # ES E-mini standard 1 contrat
LOG_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/LOGS/trading")
BARS_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/ES")
DAYS = ["20260524", "20260525", "20260526", "20260527", "20260528",
        "20260529", "20260531", "20260601", "20260602"]

SCENARIOS = [
    ("A_baseline_38_30",   32, 38,  30),
    ("B_tp150_t30",        32, 150, 30),
    ("C_tp150_t60",        32, 150, 60),
    ("D_tp150_t120",       32, 150, 120),
    ("E_sl64_tp150_t60",   64, 150, 60),
]


def parse_iso(s: str) -> datetime:
    if "Z" in s:
        s = s.replace("Z", "+00:00")
    if "+" not in s and "T" in s:
        s += "+00:00"
    return datetime.fromisoformat(s)


def load_trades_es() -> list[dict]:
    """Parse BOT3_TRADE_OPEN events pour ES."""
    import re
    trades = []
    for day in DAYS:
        fp = LOG_DIR / f"trading_{day}_paper_v2.jsonl"
        if not fp.exists():
            continue
        with open(fp, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("code") != "BOT3_TRADE_OPEN":
                        continue
                    msg = e.get("msg_fr", "")
                    if " ES " not in msg:
                        continue
                    # parse "Bot3 trade ouvert : ES GEX_DN LONG REJECTION qty=1 @ 7614.5 sl=22t conf=50"
                    m = re.search(r"ES (\w+) (LONG|SHORT) .* @ ([\d.]+) sl=(\d+)t", msg)
                    if not m:
                        continue
                    level, side, entry, sl_ticks_actual = m.group(1), m.group(2), float(m.group(3)), int(m.group(4))
                    trades.append({
                        "ts": parse_iso(e.get("ts")),
                        "day": day,
                        "level": level,
                        "side": side,
                        "entry_price": entry,
                        "sl_ticks_actual": sl_ticks_actual,
                        "signal_id": e.get("signal_id"),
                    })
                except Exception:
                    pass
    return trades


def load_bars_minimal(day: str) -> list[dict]:
    fp = BARS_DIR / f"{day}_ES.jsonl"
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


def simulate(trade: dict, bars: list[dict], sl_ticks: int, tp_ticks: int, timeout_min: int):
    entry = trade["entry_price"]
    side = trade["side"]
    entry_ts = trade["ts"]
    timeout_ts = entry_ts + timedelta(minutes=timeout_min)

    if side == "LONG":
        sl_price = entry - sl_ticks * TICK_SIZE
        tp_price = entry + tp_ticks * TICK_SIZE
    else:
        sl_price = entry + sl_ticks * TICK_SIZE
        tp_price = entry - tp_ticks * TICK_SIZE

    for bar in bars:
        if bar["ts"] < entry_ts:
            continue
        if bar["ts"] > timeout_ts:
            exit_price = bar["close"]
            pnl_ticks = ((exit_price - entry) if side == "LONG" else (entry - exit_price)) / TICK_SIZE
            return "TIMEOUT", exit_price, pnl_ticks * TICK_USD

        if side == "LONG":
            sl_hit = bar["low"] <= sl_price
            tp_hit = bar["high"] >= tp_price
        else:
            sl_hit = bar["high"] >= sl_price
            tp_hit = bar["low"] <= tp_price

        if sl_hit and tp_hit:
            return "SL", sl_price, -sl_ticks * TICK_USD
        if sl_hit:
            return "SL", sl_price, -sl_ticks * TICK_USD
        if tp_hit:
            return "TP", tp_price, tp_ticks * TICK_USD

    return "NO_FILL", entry, 0.0


def main():
    print("=" * 100)
    print("BACKTEST ES TP=150 + timeout etendus — Bot 3 MP, 9 jours (24/05 - 02/06)")
    print("=" * 100)

    trades = load_trades_es()
    print(f"Trades ES charges : {len(trades)}")
    bars_by_day = {}
    for day in DAYS:
        bars_by_day[day] = load_bars_minimal(day)
        if bars_by_day[day]:
            print(f"  {day} : {len(bars_by_day[day])} bars")

    print(f"\n{'Scenario':<22} {'N':>4} {'TP':>3} {'SL':>3} {'TO':>3} {'TO_W':>5} {'TO_L':>5} {'PnL$':>10} {'EV$':>8} {'WR%':>6} {'PF':>6}")
    print("-" * 100)

    for name, sl_t, tp_t, to_min in SCENARIOS:
        results = []
        for t in trades:
            bars = bars_by_day.get(t["day"], [])
            outcome, exit_p, pnl_usd = simulate(t, bars, sl_t, tp_t, to_min)
            results.append({"outcome": outcome, "pnl_usd": pnl_usd})

        n_tp = sum(1 for r in results if r["outcome"] == "TP")
        n_sl = sum(1 for r in results if r["outcome"] == "SL")
        n_to = sum(1 for r in results if r["outcome"] == "TIMEOUT")
        to_w = sum(1 for r in results if r["outcome"] == "TIMEOUT" and r["pnl_usd"] > 0.01)
        to_l = sum(1 for r in results if r["outcome"] == "TIMEOUT" and r["pnl_usd"] < -0.01)
        total_pnl = sum(r["pnl_usd"] for r in results)
        n_w = sum(1 for r in results if r["pnl_usd"] > 0.01)
        n_l = sum(1 for r in results if r["pnl_usd"] < -0.01)
        gross_win = sum(r["pnl_usd"] for r in results if r["pnl_usd"] > 0)
        gross_loss = -sum(r["pnl_usd"] for r in results if r["pnl_usd"] < 0)
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        wr = 100 * n_w / max(n_w + n_l, 1)
        ev = total_pnl / max(len(results), 1)
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
        print(f"{name:<22} {len(results):>4} {n_tp:>3} {n_sl:>3} {n_to:>3} {to_w:>5} {to_l:>5} {total_pnl:>+9.2f} {ev:>+7.2f} {wr:>5.1f}% {pf_str:>6}")


if __name__ == "__main__":
    main()
