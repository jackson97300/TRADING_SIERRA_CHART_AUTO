"""
Mini-backtest — Bataille Navale (Setup #3 Jackson)
===================================================

Backtest stateful sur JSONL 4 jours propres.

LIMITATIONS :
  - 4 jours propres seulement (sample faible)
  - Pas de Monte Carlo
  - Pas de walk-forward
  - Reset state entre jours (evite leakage inter-session)

Usage :
    python -X utf8 CORE/research/backtest_bataille_navale.py
"""

import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.primary_models.bataille_navale import BatailleNavaleModel


TICK_SIZE_NQ = 0.25
TICK_VALUE_NQ_MICRO = 0.50

JOURS_PROPRES = ["20260417", "20260419", "20260420", "20260421"]


def load_bars_jsonl(path: Path):
    bars = []
    if not path.exists():
        return bars
    with open(path, "r") as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def simulate_exit(bars, entry_idx, direction, entry_price, sl_ticks, tp_ticks,
                  horizon_bars=120):
    if direction == "BUY":
        sl_price = entry_price - sl_ticks * TICK_SIZE_NQ
        tp_price = entry_price + tp_ticks * TICK_SIZE_NQ
    else:
        sl_price = entry_price + sl_ticks * TICK_SIZE_NQ
        tp_price = entry_price - tp_ticks * TICK_SIZE_NQ

    end_idx = min(entry_idx + 1 + horizon_bars, len(bars))
    for i in range(entry_idx + 1, end_idx):
        bar = bars[i]
        price = bar.get("price")
        if price is None or not math.isfinite(float(price)):
            continue
        price = float(price)
        if direction == "BUY":
            if price <= sl_price:
                return {"exit_idx": i, "exit_price": price, "exit_reason": "SL",
                        "pnl_ticks": -sl_ticks}
            if price >= tp_price:
                return {"exit_idx": i, "exit_price": price, "exit_reason": "TP",
                        "pnl_ticks": tp_ticks}
        else:
            if price >= sl_price:
                return {"exit_idx": i, "exit_price": price, "exit_reason": "SL",
                        "pnl_ticks": -sl_ticks}
            if price <= tp_price:
                return {"exit_idx": i, "exit_price": price, "exit_reason": "TP",
                        "pnl_ticks": tp_ticks}

    if end_idx - 1 > entry_idx:
        final_price = float(bars[end_idx - 1].get("price", entry_price))
        if direction == "BUY":
            pnl = (final_price - entry_price) / TICK_SIZE_NQ
        else:
            pnl = (entry_price - final_price) / TICK_SIZE_NQ
        return {"exit_idx": end_idx - 1, "exit_price": final_price,
                "exit_reason": "TIME", "pnl_ticks": pnl}

    return None


def run_backtest(symbol: str, model_params: dict):
    all_trades = []
    total_bars = 0
    hold_counts = {}

    for jour in JOURS_PROPRES:
        path = Path(f"DATA/{symbol}/{jour}_{symbol}.jsonl")
        bars = load_bars_jsonl(path)
        total_bars += len(bars)

        # Instance fraiche par jour (reset state, pas de leakage inter-session)
        model = BatailleNavaleModel(**model_params)

        for i, bar in enumerate(bars):
            signal = model.generate_signal(bar)
            if signal.type.value == "HOLD":
                key = (signal.reason.split(":")[0] if signal.reason else "no_reason")
                hold_counts[key] = hold_counts.get(key, 0) + 1
                continue

            entry_price = bar.get("price")
            if entry_price is None:
                continue
            entry_price = float(entry_price)

            result = simulate_exit(bars, i, signal.type.value, entry_price,
                                  signal.sl_ticks, signal.tp_ticks)
            if result is None:
                continue

            trade = {
                "date": jour,
                "entry_idx": i,
                "entry_ts": bar.get("ts"),
                "entry_price": entry_price,
                "direction": signal.type.value,
                "sl_ticks": signal.sl_ticks,
                "tp_ticks": signal.tp_ticks,
                "tp_source": signal.meta.get("tp_source", "?"),
                "streak": signal.meta.get("streak", 0),
                "maturity": signal.meta.get("maturity", "?"),
                "pullback_ticks": signal.meta.get("pullback_ticks", 0),
                "reason": signal.reason,
                **result,
            }
            all_trades.append(trade)

    return all_trades, total_bars, hold_counts


def report(trades, bars, holds, symbol, label):
    print(f"\n{'='*72}")
    print(f"{label} — {symbol} — 4 jours propres")
    print(f"{'='*72}")
    print(f"  Total bars    : {bars}")
    print(f"  Total trades  : {len(trades)}")

    if not trades:
        print("  AUCUN TRADE. Top 5 raisons HOLD :")
        for r, c in sorted(holds.items(), key=lambda x: -x[1])[:5]:
            print(f"    {r}: {c}")
        return None

    wins = [t for t in trades if t["pnl_ticks"] > 0]
    losses = [t for t in trades if t["pnl_ticks"] < 0]
    wr = 100 * len(wins) / len(trades)
    total = sum(t["pnl_ticks"] for t in trades)
    avg = total / len(trades)
    gains = sum(t["pnl_ticks"] for t in wins)
    pertes = -sum(t["pnl_ticks"] for t in losses) if losses else 0
    pf = gains / pertes if pertes > 0 else (float("inf") if gains > 0 else 0)

    print(f"  W/L           : {len(wins)}/{len(losses)}  WR {wr:.1f}%")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  EV/trade      : {avg:+.1f} ticks ({avg * TICK_VALUE_NQ_MICRO:+.2f}$ micro)")
    print(f"  Total PnL     : {total:+.0f} ticks ({total * TICK_VALUE_NQ_MICRO:+.2f}$ micro)")

    # Maturity breakdown
    mat_stats = {}
    for t in trades:
        m = t["maturity"]
        mat_stats.setdefault(m, []).append(t)
    if mat_stats:
        print(f"  Par maturity  :")
        for m, ts in sorted(mat_stats.items()):
            pnl = sum(t['pnl_ticks'] for t in ts)
            wr_m = 100 * sum(1 for t in ts if t['pnl_ticks']>0) / len(ts)
            print(f"    {m:<8} : {len(ts):>2} trades  WR {wr_m:>3.0f}%  PnL {pnl:+.0f}t")

    # Top 5 raisons HOLD
    print(f"  Top 5 HOLD reasons : ", end="")
    top5 = sorted(holds.items(), key=lambda x: -x[1])[:5]
    print("  ".join(f"{r}={c}" for r, c in top5))

    # Sample
    print(f"  Sample trades :")
    for t in trades[:10]:
        import datetime as dt
        ts = dt.datetime.fromtimestamp(t["entry_ts"]/1000, tz=dt.timezone.utc) + dt.timedelta(hours=2)
        print(f"    {t['date']} {ts.strftime('%H:%M')}P streak={t['streak']} {t['maturity']:<8} "
              f"@ {t['entry_price']:>9.2f} sl={t['sl_ticks']:>2}t tp={t['tp_ticks']:>2}t "
              f"-> {t['exit_reason']} {t['pnl_ticks']:+.0f}t")

    return {"pf": pf, "wr": wr, "total_ticks": total, "n": len(trades)}


def compare_runs():
    variants = {
        "V1_default":       dict(),
        "V2_streak4":       dict(min_confirm_streak=4),  # plus strict
        "V3_streak2":       dict(min_confirm_streak=2),  # plus permissif
        "V4_no_footprint":  dict(require_footprint_confirm=False),
    }

    results = {}
    for symbol in ["NQ", "ES"]:
        print(f"\n{'#'*72}\n# {symbol}\n{'#'*72}")
        for name, params in variants.items():
            trades, bars, holds = run_backtest(symbol, params)
            r = report(trades, bars, holds, symbol, name)
            if r and r["n"] > 0:
                results[(symbol, name)] = r

    # Synthese
    print(f"\n\n{'='*80}\nSYNTHESE COMPARATIVE\n{'='*80}")
    print(f"{'Variant':<20} {'Sym':<4} {'N':<4} {'PF':<7} {'WR%':<6} {'Ticks':<8}")
    for (sym, name), r in sorted(results.items()):
        print(f"{name:<20} {sym:<4} {r['n']:<4} {r['pf']:<7.2f} {r['wr']:<6.1f} {r['total_ticks']:+.0f}")


if __name__ == "__main__":
    compare_runs()
