"""
Mini-backtest — PullbackConfluence0DTE sur JSONL propres post-17/04/2026
=========================================================================

v2 (21/04 soir) : support context rolling (pullback detection) +
                  affichage source TP + session.

LIMITATIONS (c'est un PROOF OF CONCEPT, pas Lopez rigoureux) :
  - Seulement 4 jours propres (17, 19, 20, 21/04) = N faible
  - Pas de Monte Carlo permutation
  - Pas de walk-forward
  - Pas de meta-labeling
  - Slippage et fees non modelises

Usage :
    python -X utf8 CORE/research/backtest_pullback_confluence.py
"""

import json
import math
import sys
from collections import deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.primary_models.pullback_confluence_0dte import PullbackConfluence0DTEModel


TICK_SIZE_NQ = 0.25
TICK_VALUE_NQ_MICRO = 0.50  # $/tick micro NQ
TICK_SIZE_ES = 0.25
TICK_VALUE_ES_MICRO = 1.25  # $/tick micro ES

JOURS_PROPRES = ["20260417", "20260419", "20260420", "20260421"]
LOOKBACK_BARS = 20


def load_bars_jsonl(path: Path):
    bars = []
    if not path.exists():
        return bars
    with open(path, "r") as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def simulate_exit(bars, entry_idx, direction, entry_price, sl_ticks, tp_ticks,
                  horizon_bars=60):
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


def run_backtest(symbol: str, model, dedup_window_bars=60):
    """Run backtest avec context rolling lookback."""
    all_trades = []
    total_bars = 0
    hold_reasons = {}

    for jour in JOURS_PROPRES:
        path = Path(f"DATA/{symbol}/{jour}_{symbol}.jsonl")
        bars = load_bars_jsonl(path)
        total_bars += len(bars)

        last_entry_idx = -dedup_window_bars - 1
        price_buffer = deque(maxlen=LOOKBACK_BARS)

        for i, bar in enumerate(bars):
            # Construire context avec lookback rolling
            context = None
            if len(price_buffer) >= LOOKBACK_BARS // 2:
                prices = list(price_buffer)
                context = {
                    "lookback_max_price": max(prices),
                    "lookback_min_price": min(prices),
                    "lookback_bars": len(prices),
                }

            signal = model.generate_signal(bar, context=context)

            # Add current price to buffer pour prochaines barres
            current_price = bar.get("price")
            if current_price is not None and math.isfinite(float(current_price)):
                price_buffer.append(float(current_price))

            if signal.type.value == "HOLD":
                # Comptage raisons pour debug
                reason_key = signal.reason.split(":")[0] if signal.reason else "no_trigger"
                hold_reasons[reason_key] = hold_reasons.get(reason_key, 0) + 1
                continue

            if i - last_entry_idx < dedup_window_bars:
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
                "tp_source": signal.meta.get("tp_source", "fixed"),
                "session": signal.meta.get("session", "?"),
                "reason": signal.reason,
                **result,
            }
            all_trades.append(trade)
            last_entry_idx = i

    return all_trades, total_bars, hold_reasons


def report(trades, total_bars, hold_reasons, symbol, version_label):
    tick_value = TICK_VALUE_NQ_MICRO if symbol == "NQ" else TICK_VALUE_ES_MICRO
    print(f"\n{'='*72}")
    print(f"{version_label} — {symbol} — 4 jours propres")
    print(f"{'='*72}")
    print(f"  Total bars       : {total_bars}")
    print(f"  Total trades     : {len(trades)}")

    if not trades:
        print("  AUCUN TRADE.")
        # Top 5 raisons HOLD
        top_reasons = sorted(hold_reasons.items(), key=lambda x: -x[1])[:5]
        print("  Top 5 raisons HOLD :")
        for r, c in top_reasons:
            print(f"    {r}: {c}")
        return None

    wins = [t for t in trades if t["pnl_ticks"] > 0]
    losses = [t for t in trades if t["pnl_ticks"] < 0]
    wr = 100 * len(wins) / len(trades)
    total_pnl_ticks = sum(t["pnl_ticks"] for t in trades)
    avg_pnl = total_pnl_ticks / len(trades)
    gains = sum(t["pnl_ticks"] for t in wins)
    pertes = -sum(t["pnl_ticks"] for t in losses) if losses else 0
    pf = gains / pertes if pertes > 0 else float("inf") if gains > 0 else 0

    print(f"  W/L              : {len(wins)}/{len(losses)}   WR {wr:.1f}%")
    print(f"  Profit Factor    : {pf:.2f}")
    print(f"  EV/trade         : {avg_pnl:+.1f} ticks ({avg_pnl * tick_value:+.2f}$ micro)")
    print(f"  Total PnL        : {total_pnl_ticks:+.0f} ticks ({total_pnl_ticks * tick_value:+.2f}$ micro)")

    # Par direction
    buys = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    if buys:
        wr_b = 100 * sum(1 for t in buys if t['pnl_ticks']>0) / len(buys)
        print(f"  BUY  : {len(buys)} WR {wr_b:.0f}% PnL {sum(t['pnl_ticks'] for t in buys):+.0f}t")
    if sells:
        wr_s = 100 * sum(1 for t in sells if t['pnl_ticks']>0) / len(sells)
        print(f"  SELL : {len(sells)} WR {wr_s:.0f}% PnL {sum(t['pnl_ticks'] for t in sells):+.0f}t")

    # Par session
    sess_stats = {}
    for t in trades:
        s = t.get("session", "?")
        sess_stats.setdefault(s, []).append(t)
    print(f"  Par session      :")
    for s in sorted(sess_stats):
        ts = sess_stats[s]
        pnl = sum(t['pnl_ticks'] for t in ts)
        wr_s = 100 * sum(1 for t in ts if t['pnl_ticks']>0) / len(ts) if ts else 0
        print(f"    {s:10} : {len(ts):>2} trades  WR {wr_s:>3.0f}%  PnL {pnl:+.0f}t")

    # TP dynamique vs fixe
    tp_dyn = [t for t in trades if "gex_dyn" in t.get("tp_source", "")]
    tp_fixed = [t for t in trades if t.get("tp_source") == "fixed"]
    if tp_dyn:
        pnl_dyn = sum(t['pnl_ticks'] for t in tp_dyn)
        print(f"  TP dynamique GEX : {len(tp_dyn)} trades  PnL {pnl_dyn:+.0f}t  (tp ticks avg={sum(t['tp_ticks'] for t in tp_dyn)/len(tp_dyn):.0f})")
    if tp_fixed:
        pnl_fix = sum(t['pnl_ticks'] for t in tp_fixed)
        print(f"  TP fixe 36t      : {len(tp_fixed)} trades  PnL {pnl_fix:+.0f}t")

    # Echantillon
    print(f"  Sample trades    :")
    for t in trades[:6]:
        import datetime as dt
        ts = dt.datetime.fromtimestamp(t["entry_ts"]/1000, tz=dt.timezone.utc) + dt.timedelta(hours=2)
        print(f"    {t['date']} {ts.strftime('%H:%M')}P {t['direction']:4s} @ {t['entry_price']:>9.2f} "
              f"tp={t['tp_ticks']:>2}t({t['tp_source']:>10s}) sess={t['session']:>6} "
              f"-> {t['exit_reason']} {t['pnl_ticks']:+.0f}t")

    return {"pf": pf, "wr": wr, "total_ticks": total_pnl_ticks, "n": len(trades)}


def compare_runs():
    """Compare plusieurs variantes pour isoler quel ajustement aide/nuit."""

    variants = {
        "V1_baseline":         dict(require_pullback=False, skip_sessions=(),
                                    tp_dyn_max_ticks=0),
        "V2a_skip_asia_only":  dict(require_pullback=False, skip_sessions=("Asia",),
                                    tp_dyn_max_ticks=0),
        "V2b_tp_dyn_only":     dict(require_pullback=False, skip_sessions=(),
                                    tp_dyn_min_ticks=20, tp_dyn_max_ticks=80),
        "V2c_skip_asia+tp_dyn": dict(require_pullback=False, skip_sessions=("Asia",),
                                    tp_dyn_min_ticks=20, tp_dyn_max_ticks=80),
        "V2d_full_pull15":     dict(require_pullback=True, skip_sessions=("Asia",),
                                    tp_dyn_min_ticks=20, tp_dyn_max_ticks=80,
                                    pullback_min_ticks=15),
        "V2e_full_pull5":      dict(require_pullback=True, skip_sessions=("Asia",),
                                    tp_dyn_min_ticks=20, tp_dyn_max_ticks=80,
                                    pullback_min_ticks=5),
    }

    results = {}
    for symbol in ["NQ", "ES"]:
        print(f"\n{'#'*72}\n# {symbol}\n{'#'*72}")
        for name, params in variants.items():
            model = PullbackConfluence0DTEModel(**params)
            trades, bars, holds = run_backtest(symbol, model)
            r = report(trades, bars, holds, symbol, f"{name}") if trades else None
            if r:
                results[(symbol, name)] = r

    # Synthese comparative
    print(f"\n\n{'='*80}\nSYNTHESE COMPARATIVE (6 variantes x 2 symboles)\n{'='*80}")
    print(f"{'Variante':<22} {'Sym':<4} {'N':<4} {'PF':<7} {'WR%':<6} {'Ticks':<8}")
    for (sym, name), r in sorted(results.items()):
        print(f"{name:<22} {sym:<4} {r['n']:<4} {r['pf']:<7.2f} {r['wr']:<6.1f} {r['total_ticks']:+.0f}")


if __name__ == "__main__":
    compare_runs()
