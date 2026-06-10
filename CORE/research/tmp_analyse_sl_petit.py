"""Analyse forensique : d'ou viennent les SL fill < 15 ticks Bot 3 v3 NQ.

Question Jackson 02/06 : pourquoi voit-on des SL a 2/5 ticks sur dashboard
alors que sl_planned = entry - 15t (fallback) ou cap 30t ?

Hypothese : Sim1 fill au bar.close 1m au lieu du STOP price exact.

Methodologie :
- Charge BOT3_V3_FILL_SLIPPAGE_REPORT events (donne entry_planned, exit_planned,
  exit_filled, sl_slip_t pour chaque trade)
- Pour chaque SL avec slip_t > 5t (= slip favorable artificiel), retrouver :
  * Heure UTC + jour de la semaine
  * Bar 1m au moment du STOP touch
  * bar.low (= moment ou STOP price atteint pour LONG)
  * bar.close (= prix d'exit reel si hypothese bar.close fill correct)
  * Verifier : exit_filled == bar.close ? ou close +/- 1 ?
- Stats :
  * Distribution heure (Asia/London/RTH)
  * Distribution ATR de la bar (volatilite)
  * % exit_filled match bar.close (validation hypothese)
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

TICK_SIZE = 0.25
TICK_USD = 1.25
LOG_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/LOGS/execution")
BARS_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ")
DAYS = ["20260524", "20260525", "20260526", "20260527", "20260528",
        "20260529", "20260531", "20260601"]


def parse_iso(s: str) -> datetime:
    if "Z" in s:
        s = s.replace("Z", "+00:00")
    if "+" not in s and "T" in s:
        s += "+00:00"
    return datetime.fromisoformat(s)


def load_sl_slippage_reports() -> list[dict]:
    """Charge tous BOT3_V3_FILL_SLIPPAGE_REPORT avec kind=sl."""
    reports = []
    for day in DAYS:
        for fname in [f"execution_{day}_paper_v2.jsonl", f"execution_{day}_bot_legacy.jsonl"]:
            fp = LOG_DIR / fname
            if not fp.exists():
                continue
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if e.get("code") != "BOT3_V3_FILL_SLIPPAGE_REPORT":
                            continue
                        ctx = e.get("ctx", {})
                        if ctx.get("kind") != "sl":
                            continue
                        reports.append({
                            "day": day,
                            "ts": parse_iso(e.get("ts")),
                            "signal_id": e.get("signal_id"),
                            "direction": ctx.get("direction"),
                            "entry_planned": float(ctx.get("entry_planned", 0)),
                            "entry_filled": float(ctx.get("entry_filled", 0)),
                            "exit_planned": float(ctx.get("exit_planned", 0)),
                            "exit_filled": float(ctx.get("exit_filled", 0)),
                            "sl_slip_t": float(ctx.get("sl_slip_t", 0)),
                            "pnl_R_planned": float(ctx.get("pnl_R_planned", -1)),
                            "pnl_R_real": float(ctx.get("pnl_R_real", -1)),
                        })
                    except Exception:
                        pass
    return reports


def load_bars(day: str) -> list[dict]:
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
                    "open": float(b.get("open", 0)),
                    "high": float(b.get("high", 0)),
                    "low": float(b.get("low", 0)),
                    "close": float(b.get("close", 0)),
                })
            except Exception:
                pass
    bars.sort(key=lambda x: x["ts"])
    return bars


def find_touch_bar(report: dict, bars: list[dict]):
    """Trouve la bar 1m ou le STOP price a ete atteint."""
    entry_planned = report["entry_planned"]
    exit_planned = report["exit_planned"]  # = STOP price planifie
    direction = report["direction"]
    entry_ts = report["ts"]  # approximate - c'est le ts du CLOSE event

    # Cherche dans les bars entre (estimate_open_ts) et entry_ts
    # Pas d'info sur l'heure d'open, on prend les bars dans l'heure precedente
    from datetime import timedelta
    window_start = entry_ts - timedelta(minutes=60)
    candidates = [b for b in bars if window_start <= b["ts"] <= entry_ts]

    for bar in candidates:
        if direction == "LONG":
            # STOP SELL pour LONG = touche si bar.low <= STOP
            if bar["low"] <= exit_planned:
                return bar
        else:  # SHORT
            # STOP BUY pour SHORT = touche si bar.high >= STOP
            if bar["high"] >= exit_planned:
                return bar
    return None


def analyse():
    print("=" * 90)
    print("ANALYSE FORENSIQUE — SL fill < SL planifie sur 8 jours Bot 3 v3 NQ")
    print("=" * 90)

    reports = load_sl_slippage_reports()
    print(f"\nTotal SL fills analyses : {len(reports)}")

    # Cherche les SL avec slip favorable artificiel (slip_t > +5)
    # LONG : slip_t > 0 = exit_filled > STOP planifie = moins de perte
    # SHORT : slip_t > 0 = exit_filled < STOP planifie = moins de perte
    favorable = [r for r in reports if r["sl_slip_t"] > 5]
    print(f"SL avec slip favorable > 5t (suspect bug fill) : {len(favorable)} ({100*len(favorable)/max(len(reports),1):.0f}%)")

    propre = [r for r in reports if abs(r["sl_slip_t"]) <= 2]
    print(f"SL fill propre |slip_t| <= 2 (conforme STOP price) : {len(propre)} ({100*len(propre)/max(len(reports),1):.0f}%)")

    defavorable = [r for r in reports if r["sl_slip_t"] < -5]
    print(f"SL avec slip defavorable > 5t (gap rapide) : {len(defavorable)} ({100*len(defavorable)/max(len(reports),1):.0f}%)")

    # Distribution heure
    print(f"\n=== DISTRIBUTION HORAIRE des SL slip favorable > 5t ===")
    by_hour = defaultdict(int)
    for r in favorable:
        h = r["ts"].astimezone(timezone.utc).hour
        by_hour[h] += 1
    for h in sorted(by_hour.keys()):
        bar_str = "#" * by_hour[h]
        session = "Asia" if h < 6 else ("London" if h < 13 else ("RTH" if h < 20 else "Off"))
        print(f"  {h:02d}h UTC ({session:6s}) : {by_hour[h]:3d} {bar_str}")

    # Detail 10 worst cases (slip max favorable)
    print(f"\n=== TOP 10 SLIP FAVORABLE (= bug fill plus prononce) ===")
    favorable_sorted = sorted(favorable, key=lambda r: -r["sl_slip_t"])[:10]
    print(f"  {'signal_id':<28} {'side':<6} {'entry':>10} {'STOP planif':>12} {'exit filled':>12} {'slip_t':>7} {'pnl_R':>7}")
    for r in favorable_sorted:
        sig = r["signal_id"] or "?"
        print(f"  {sig:<28} {r['direction']:<6} {r['entry_planned']:>10.2f} {r['exit_planned']:>12.2f} {r['exit_filled']:>12.2f} {r['sl_slip_t']:>+6.1f}t {r['pnl_R_real']:>+6.2f}")

    # Hypothese fill au bar.close
    print(f"\n=== VALIDATION HYPOTHESE 'fill = bar.close de la bar du STOP touch' ===")
    bars_by_day = {day: load_bars(day) for day in DAYS}

    n_matched = 0  # exit_filled match bar.close (proche)
    n_unmatched = 0
    examples_match = []
    examples_unmatch = []

    for r in favorable[:30]:  # sample 30
        bars = bars_by_day.get(r["day"], [])
        if not bars:
            continue
        touch_bar = find_touch_bar(r, bars)
        if not touch_bar:
            continue
        diff_close = abs(r["exit_filled"] - touch_bar["close"]) / TICK_SIZE  # en ticks
        if diff_close < 2:
            n_matched += 1
            if len(examples_match) < 3:
                examples_match.append({
                    "signal_id": r["signal_id"],
                    "side": r["direction"],
                    "entry": r["entry_planned"],
                    "stop_planned": r["exit_planned"],
                    "exit_filled": r["exit_filled"],
                    "bar_close": touch_bar["close"],
                    "bar_low": touch_bar["low"],
                    "bar_high": touch_bar["high"],
                    "bar_ts": touch_bar["ts"].isoformat(),
                })
        else:
            n_unmatched += 1
            if len(examples_unmatch) < 3:
                examples_unmatch.append({
                    "signal_id": r["signal_id"],
                    "side": r["direction"],
                    "entry": r["entry_planned"],
                    "stop_planned": r["exit_planned"],
                    "exit_filled": r["exit_filled"],
                    "bar_close": touch_bar["close"],
                    "bar_low": touch_bar["low"],
                    "bar_high": touch_bar["high"],
                    "diff_t": round(diff_close, 1),
                })

    total = n_matched + n_unmatched
    print(f"  Sample {total} trades favorable :")
    print(f"  Matched 'exit ≈ bar.close' (<2t diff) : {n_matched}/{total} = {100*n_matched/max(total,1):.0f}%")
    print(f"  Unmatched (autre logique fill)         : {n_unmatched}/{total}")

    print(f"\n  EXEMPLES MATCH (hypothese bar.close validee) :")
    for ex in examples_match:
        print(f"    {ex['signal_id']} {ex['side']} entry={ex['entry']:.2f} STOP_planif={ex['stop_planned']:.2f} EXIT={ex['exit_filled']:.2f}")
        print(f"      bar : OHLC={ex.get('open','?')}/{ex['bar_high']:.2f}/{ex['bar_low']:.2f}/{ex['bar_close']:.2f} ts={ex['bar_ts']}")
        diff = abs(ex['exit_filled'] - ex['bar_close']) / TICK_SIZE
        print(f"      → exit ≈ bar.close ({diff:.1f}t diff) : Sim1 fill au bar.close de la bar du STOP touch")

    print(f"\n  EXEMPLES UNMATCH (autre mecanique) :")
    for ex in examples_unmatch:
        print(f"    {ex['signal_id']} {ex['side']} entry={ex['entry']:.2f} STOP_planif={ex['stop_planned']:.2f} EXIT={ex['exit_filled']:.2f}")
        print(f"      bar : H/L/C={ex['bar_high']:.2f}/{ex['bar_low']:.2f}/{ex['bar_close']:.2f}")
        print(f"      → exit vs bar.close = {ex['diff_t']:.1f}t (pas bar.close)")

    # PnL gonfle vs realiste
    pnl_real = sum(r["pnl_R_real"] for r in reports) * 15 * TICK_USD  # R * 15t * $1.25
    pnl_planned = sum(r["pnl_R_planned"] for r in reports) * 15 * TICK_USD
    print(f"\n=== IMPACT FINANCIER bug fill ===")
    print(f"  PnL realise (avec slip favorable) : {pnl_real:+.2f}$ (sur {len(reports)} SL)")
    print(f"  PnL si fills propres (= STOP exact) : {pnl_planned:+.2f}$ (= chaque SL = -1R = -15t)")
    print(f"  Difference (PnL gonfle artificiellement) : {pnl_real - pnl_planned:+.2f}$")


if __name__ == "__main__":
    analyse()
