"""
Backtest — Range Fade (Setup #2 Jackson) sur 4 jours propres.
"""

import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.primary_models.range_fade import RangeFadeModel


TICK_SIZE_NQ = 0.25
TICK_VALUE_NQ_MICRO = 0.50
JOURS = ["20260417", "20260419", "20260420", "20260421"]


def load_bars(path):
    bars = []
    if not path.exists():
        return bars
    with open(path, "r") as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def simulate_exit(bars, entry_idx, direction, entry_price, sl_ticks, tp_ticks, horizon=90):
    if direction == "BUY":
        sl_price = entry_price - sl_ticks * TICK_SIZE_NQ
        tp_price = entry_price + tp_ticks * TICK_SIZE_NQ
    else:
        sl_price = entry_price + sl_ticks * TICK_SIZE_NQ
        tp_price = entry_price - tp_ticks * TICK_SIZE_NQ

    end = min(entry_idx + 1 + horizon, len(bars))
    for i in range(entry_idx + 1, end):
        price = bars[i].get("price")
        if price is None or not math.isfinite(float(price)):
            continue
        price = float(price)
        if direction == "BUY":
            if price <= sl_price:
                return {"exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if price >= tp_price:
                return {"exit_reason": "TP", "pnl_ticks": tp_ticks}
        else:
            if price >= sl_price:
                return {"exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if price <= tp_price:
                return {"exit_reason": "TP", "pnl_ticks": tp_ticks}

    if end - 1 > entry_idx:
        final = float(bars[end - 1].get("price", entry_price))
        pnl = ((final - entry_price) if direction == "BUY" else (entry_price - final)) / TICK_SIZE_NQ
        return {"exit_reason": "TIME", "pnl_ticks": pnl}
    return None


def run(symbol, params):
    trades = []
    total_bars = 0
    for j in JOURS:
        path = Path(f"DATA/{symbol}/{j}_{symbol}.jsonl")
        bars = load_bars(path)
        total_bars += len(bars)
        model = RangeFadeModel(**params)
        for i, bar in enumerate(bars):
            sig = model.generate_signal(bar)
            if sig.type.value == "HOLD":
                continue
            entry = bar.get("price")
            if entry is None:
                continue
            result = simulate_exit(bars, i, sig.type.value, float(entry),
                                   sig.sl_ticks, sig.tp_ticks)
            if result is None:
                continue
            trades.append({
                "date": j, "entry_ts": bar["ts"], "entry_price": float(entry),
                "direction": sig.type.value, "sl_ticks": sig.sl_ticks, "tp_ticks": sig.tp_ticks,
                "pattern": sig.meta.get("pattern"),
                "width": sig.meta.get("width_ticks"),
                "tp_mode": sig.meta.get("tp_mode"),
                **result,
            })
    return trades, total_bars


def report(trades, bars, sym, label):
    print(f"\n{'='*72}\n{label} — {sym}\n{'='*72}")
    print(f"  Bars: {bars}  Trades: {len(trades)}")
    if not trades:
        return None
    wins = [t for t in trades if t["pnl_ticks"] > 0]
    losses = [t for t in trades if t["pnl_ticks"] < 0]
    wr = 100 * len(wins) / len(trades)
    total = sum(t["pnl_ticks"] for t in trades)
    gains = sum(t["pnl_ticks"] for t in wins)
    pertes = -sum(t["pnl_ticks"] for t in losses) if losses else 0
    pf = gains / pertes if pertes > 0 else float("inf") if gains > 0 else 0
    print(f"  W/L {len(wins)}/{len(losses)}  WR {wr:.1f}%  PF {pf:.2f}  Total {total:+.0f}t")
    longs = [t for t in trades if t["direction"] == "BUY"]
    shorts = [t for t in trades if t["direction"] == "SELL"]
    if longs:
        wr_l = 100*sum(1 for t in longs if t["pnl_ticks"]>0)/len(longs)
        print(f"  LONG  : {len(longs)}  WR {wr_l:.0f}%  {sum(t['pnl_ticks'] for t in longs):+.0f}t")
    if shorts:
        wr_s = 100*sum(1 for t in shorts if t["pnl_ticks"]>0)/len(shorts)
        print(f"  SHORT : {len(shorts)}  WR {wr_s:.0f}%  {sum(t['pnl_ticks'] for t in shorts):+.0f}t")
    import datetime as dt
    for t in trades[:8]:
        ts = dt.datetime.fromtimestamp(t["entry_ts"]/1000, tz=dt.timezone.utc) + dt.timedelta(hours=2)
        print(f"    {t['date']} {ts.strftime('%H:%M')}P {t['pattern']:<18} "
              f"@ {t['entry_price']:>9.2f} w={t['width']:.0f}t sl={t['sl_ticks']:>2}t tp={t['tp_ticks']:>2}t "
              f"-> {t['exit_reason']} {t['pnl_ticks']:+.0f}t")
    return {"pf": pf, "wr": wr, "total": total, "n": len(trades)}


def main():
    variants = {
        "V1_middle":        dict(tp_mode="middle"),
        "V2_three_quarter": dict(tp_mode="three_quarter"),
        "V3_range_wider":   dict(min_range_ticks=30),  # Ranges plus grands
        "V4_no_footprint":  dict(require_footprint_confirm=False),
    }
    results = {}
    for sym in ["NQ", "ES"]:
        print(f"\n{'#'*72}\n# {sym}\n{'#'*72}")
        for name, p in variants.items():
            t, b = run(sym, p)
            r = report(t, b, sym, name)
            if r:
                results[(sym, name)] = r
    print(f"\n{'='*80}\nSYNTHESE RANGE FADE\n{'='*80}")
    print(f"{'Variant':<18} {'Sym':<4} {'N':<4} {'PF':<7} {'WR%':<6} {'Ticks':<8}")
    for (sym, name), r in sorted(results.items()):
        print(f"{name:<18} {sym:<4} {r['n']:<4} {r['pf']:<7.2f} {r['wr']:<6.1f} {r['total']:+.0f}")


if __name__ == "__main__":
    main()
