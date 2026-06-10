"""
Backtest — V-Reversal setup Jackson sur 4 jours propres.
"""

import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.primary_models.v_reversal import VReversalModel


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


def simulate_exit(bars, entry_idx, direction, entry_price, sl_ticks, tp_ticks, horizon=120):
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
                return {"exit_idx": i, "exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if price >= tp_price:
                return {"exit_idx": i, "exit_reason": "TP", "pnl_ticks": tp_ticks}
        else:
            if price >= sl_price:
                return {"exit_idx": i, "exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if price <= tp_price:
                return {"exit_idx": i, "exit_reason": "TP", "pnl_ticks": tp_ticks}

    if end - 1 > entry_idx:
        final = float(bars[end - 1].get("price", entry_price))
        pnl = ((final - entry_price) if direction == "BUY" else (entry_price - final)) / TICK_SIZE_NQ
        return {"exit_idx": end - 1, "exit_reason": "TIME", "pnl_ticks": pnl}

    return None


def run(symbol, params):
    all_trades = []
    total_bars = 0
    for j in JOURS:
        path = Path(f"DATA/{symbol}/{j}_{symbol}.jsonl")
        bars = load_bars(path)
        total_bars += len(bars)
        model = VReversalModel(**params)  # reset par jour
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
            all_trades.append({
                "date": j, "entry_ts": bar["ts"], "entry_price": float(entry),
                "direction": sig.type.value, "sl_ticks": sig.sl_ticks,
                "tp_ticks": sig.tp_ticks, "reason": sig.reason,
                "pattern": sig.meta.get("pattern"),
                "vol_ratio": sig.meta.get("vol_ratio"),
                **result,
            })
    return all_trades, total_bars


def report(trades, bars, symbol, label):
    print(f"\n{'='*72}\n{label} — {symbol}\n{'='*72}")
    print(f"  Bars: {bars}  Trades: {len(trades)}")
    if not trades:
        return None
    wins = [t for t in trades if t["pnl_ticks"] > 0]
    losses = [t for t in trades if t["pnl_ticks"] < 0]
    wr = 100 * len(wins) / len(trades)
    total = sum(t["pnl_ticks"] for t in trades)
    gains = sum(t["pnl_ticks"] for t in wins)
    pertes = -sum(t["pnl_ticks"] for t in losses) if losses else 0
    pf = gains / pertes if pertes > 0 else (float("inf") if gains > 0 else 0)
    print(f"  W/L {len(wins)}/{len(losses)}  WR {wr:.1f}%  PF {pf:.2f}  Total {total:+.0f}t")
    # Par pattern
    vb = [t for t in trades if t["pattern"] == "V_BOTTOM"]
    lt = [t for t in trades if t["pattern"] == "LAMBDA_TOP"]
    if vb:
        pf_v = sum(t["pnl_ticks"] for t in vb)
        print(f"  V_BOTTOM   : {len(vb)}  PnL {pf_v:+.0f}t  "
              f"WR {100*sum(1 for t in vb if t['pnl_ticks']>0)/len(vb):.0f}%")
    if lt:
        pf_l = sum(t["pnl_ticks"] for t in lt)
        print(f"  LAMBDA_TOP : {len(lt)}  PnL {pf_l:+.0f}t  "
              f"WR {100*sum(1 for t in lt if t['pnl_ticks']>0)/len(lt):.0f}%")
    # Sample
    import datetime as dt
    for t in trades[:8]:
        ts = dt.datetime.fromtimestamp(t["entry_ts"]/1000, tz=dt.timezone.utc) + dt.timedelta(hours=2)
        vr = t.get("vol_ratio", 0) or 0
        print(f"    {t['date']} {ts.strftime('%H:%M')}P {t['pattern']:<10} "
              f"@ {t['entry_price']:>9.2f} sl={t['sl_ticks']:>2}t tp={t['tp_ticks']:>3}t "
              f"vol={vr:.1f}x -> {t['exit_reason']} {t['pnl_ticks']:+.0f}t")
    return {"pf": pf, "wr": wr, "total": total, "n": len(trades)}


def main():
    variants = {
        "V1_default":        dict(),
        "V2_drop10":         dict(capitulation_drop_pts=10.0),
        "V3_vol2x":          dict(vol_spike_ratio=2.0),
        "V4_no_footprint":   dict(require_footprint_confirm=False),
    }
    results = {}
    for sym in ["NQ", "ES"]:
        print(f"\n{'#'*72}\n# {sym}\n{'#'*72}")
        for name, p in variants.items():
            t, b = run(sym, p)
            r = report(t, b, sym, name)
            if r:
                results[(sym, name)] = r

    print(f"\n{'='*80}\nSYNTHESE V-REVERSAL\n{'='*80}")
    print(f"{'Variant':<20} {'Sym':<4} {'N':<4} {'PF':<7} {'WR%':<6} {'Ticks':<8}")
    for (sym, name), r in sorted(results.items()):
        print(f"{name:<20} {sym:<4} {r['n']:<4} {r['pf']:<7.2f} {r['wr']:<6.1f} {r['total']:+.0f}")


if __name__ == "__main__":
    main()
