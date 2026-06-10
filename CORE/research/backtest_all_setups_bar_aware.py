"""
Backtest unifie des 4 setups Jackson avec le simulator BAR-AWARE corrige.

Post-finding 21/04 23h40 : l'ancien simulator close-only sous-estimait
les TP (et certains SL). Le nouveau utilise bar_high/bar_low pour des
resultats realistes.

Compare OLD (close-only) vs NEW (bar-aware) sur les 4 setups.

Usage :
    python -X utf8 CORE/research/backtest_all_setups_bar_aware.py
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
from CORE.primary_models.bataille_navale import BatailleNavaleModel
from CORE.primary_models.v_reversal import VReversalModel
from CORE.primary_models.range_fade import RangeFadeModel

from CORE.research._simulator import simulate_exit_bar_aware


TICK_SIZE_NQ = 0.25
TICK_VALUE_NQ_MICRO = 0.50
JOURS = ["20260417", "20260419", "20260420", "20260421"]
LOOKBACK_BARS = 20


def load_bars(path):
    bars = []
    if not path.exists():
        return bars
    with open(path, "r") as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def simulate_exit_close_only(bars, entry_idx, direction, entry_price,
                             sl_ticks, tp_ticks, horizon=120):
    """ANCIEN simulator (close-only) pour comparaison."""
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


def run_setup(setup_name, model_factory, symbol, simulator_fn,
              needs_lookback_context=False, dedup_window=60):
    """Run un setup sur 4 jours avec le simulator donne."""
    all_trades = []
    for j in JOURS:
        path = Path(f"DATA/{symbol}/{j}_{symbol}.jsonl")
        bars = load_bars(path)
        if not bars:
            continue

        # Instance fraiche par jour (reset state pour stateful)
        model = model_factory()

        last_entry_idx = -dedup_window - 1
        price_buffer = deque(maxlen=LOOKBACK_BARS)

        for i, bar in enumerate(bars):
            if needs_lookback_context and len(price_buffer) >= LOOKBACK_BARS // 2:
                context = {
                    "lookback_max_price": max(price_buffer),
                    "lookback_min_price": min(price_buffer),
                }
            else:
                context = None

            sig = model.generate_signal(bar, context=context)

            price = bar.get("price")
            if price is not None and math.isfinite(float(price)):
                price_buffer.append(float(price))

            if sig.type.value == "HOLD":
                continue
            if i - last_entry_idx < dedup_window:
                continue
            if price is None:
                continue

            entry = float(price)
            result = simulator_fn(bars, i, sig.type.value, entry, sig.sl_ticks, sig.tp_ticks)
            if result is None:
                continue

            all_trades.append({
                "date": j, "symbol": symbol, "setup": setup_name,
                "entry_price": entry, "direction": sig.type.value,
                "sl_ticks": sig.sl_ticks, "tp_ticks": sig.tp_ticks,
                **result,
            })
            last_entry_idx = i

    return all_trades


def summarize(trades, label):
    if not trades:
        return {"label": label, "n": 0, "pf": 0, "wr": 0, "total": 0}
    wins = [t for t in trades if t["pnl_ticks"] > 0]
    losses = [t for t in trades if t["pnl_ticks"] < 0]
    wr = 100 * len(wins) / len(trades)
    total = sum(t["pnl_ticks"] for t in trades)
    gains = sum(t["pnl_ticks"] for t in wins)
    pertes = -sum(t["pnl_ticks"] for t in losses) if losses else 0
    pf = gains / pertes if pertes > 0 else (float("inf") if gains > 0 else 0)
    return {
        "label": label, "n": len(trades),
        "pf": pf, "wr": wr, "total": total,
        "wins": len(wins), "losses": len(losses),
    }


def main():
    # Factories : closures pour creer une instance fraiche par run
    setups = {
        "Setup1_PullbackConf": (
            lambda: PullbackConfluence0DTEModel(require_pullback=False, skip_sessions=(), tp_dyn_max_ticks=0),
            False,  # lookback pas requis en mode require_pullback=False
        ),
        "Setup3_BatailleNavale_V1": (
            lambda: BatailleNavaleModel(min_confirm_streak=3),
            False,
        ),
        "Setup3_BatailleNavale_V3_streak2": (
            lambda: BatailleNavaleModel(min_confirm_streak=2),
            False,
        ),
        "V_Reversal_V4_noFP": (
            lambda: VReversalModel(require_footprint_confirm=False),
            False,
        ),
        "RangeFade_V4_noFP": (
            lambda: RangeFadeModel(require_footprint_confirm=False),
            False,
        ),
    }

    print(f"{'#'*80}")
    print(f"# COMPARAISON OLD simulator (close-only) vs NEW simulator (bar-aware)")
    print(f"# 4 jours propres : {JOURS}")
    print(f"{'#'*80}")

    results = []
    for setup_name, (factory, needs_lb) in setups.items():
        for sym in ["NQ", "ES"]:
            trades_old = run_setup(setup_name, factory, sym, simulate_exit_close_only, needs_lb)
            trades_new = run_setup(setup_name, factory, sym, simulate_exit_bar_aware, needs_lb)
            r_old = summarize(trades_old, f"{setup_name}_{sym}_OLD")
            r_new = summarize(trades_new, f"{setup_name}_{sym}_NEW")
            results.append((setup_name, sym, r_old, r_new))

    print(f"\n{'Setup':<32} {'Sym':<4} {'N':<4} {'PF old':<8} {'PF new':<8} {'delta PF':<9} {'WR old':<7} {'WR new':<7} {'Ticks old':<10} {'Ticks new':<10}")
    print("-" * 115)
    for setup_name, sym, r_old, r_new in results:
        delta_pf = r_new["pf"] - r_old["pf"]
        delta_sign = "+" if delta_pf > 0 else ""
        print(f"{setup_name:<32} {sym:<4} {r_new['n']:<4} "
              f"{r_old['pf']:<8.2f} {r_new['pf']:<8.2f} {delta_sign}{delta_pf:<8.2f} "
              f"{r_old['wr']:<7.1f} {r_new['wr']:<7.1f} "
              f"{r_old['total']:+.0f}{'':>3} {r_new['total']:+.0f}")


if __name__ == "__main__":
    main()
