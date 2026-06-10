"""
Simulator bar-aware commun pour tous les backtests.

CORRECTION FINDING 21/04/2026 23h40 :
L'ancien simulator utilisait `price` (close) uniquement -> sous-estimait
les TP (et certains SL) touches intra-bar.

Nouveau simulator utilise bar_high / bar_low pour detecter les touches.

Convention Lopez (pessimiste) : si SL et TP touches dans meme barre, SL gagne.
"""

import math


TICK_SIZE_NQ = 0.25
TICK_SIZE_ES = 0.25


def simulate_exit_bar_aware(bars, entry_idx, direction, entry_price,
                            sl_ticks, tp_ticks, horizon_bars=120,
                            tick_size=TICK_SIZE_NQ):
    """
    Simulate exit using bar_high / bar_low (realistic TP LIMIT + SL STOP fills).

    Args:
        bars: list of JSONL bar dicts (doivent avoir 'bar_high', 'bar_low', 'price')
        entry_idx: index of entry bar
        direction: 'BUY' or 'SELL'
        entry_price: float
        sl_ticks, tp_ticks: int
        horizon_bars: max bars to hold
        tick_size: 0.25 par defaut NQ/ES

    Returns:
        dict {exit_idx, exit_price, exit_reason, pnl_ticks} ou None
    """
    if direction == "BUY":
        sl_price = entry_price - sl_ticks * tick_size
        tp_price = entry_price + tp_ticks * tick_size
    else:  # SELL
        sl_price = entry_price + sl_ticks * tick_size
        tp_price = entry_price - tp_ticks * tick_size

    end_idx = min(entry_idx + 1 + horizon_bars, len(bars))

    for i in range(entry_idx + 1, end_idx):
        bar = bars[i]
        close = bar.get("price")
        if close is None or not math.isfinite(float(close)):
            continue
        close = float(close)

        bar_high = bar.get("bar_high")
        bar_low = bar.get("bar_low")
        if bar_high is None or not math.isfinite(float(bar_high)):
            bar_high = close
        else:
            bar_high = float(bar_high)
        if bar_low is None or not math.isfinite(float(bar_low)):
            bar_low = close
        else:
            bar_low = float(bar_low)

        if direction == "BUY":
            sl_touched = bar_low <= sl_price
            tp_touched = bar_high >= tp_price
            # Convention pessimiste : SL prioritaire si les 2 touches meme barre
            if sl_touched and tp_touched:
                return {"exit_idx": i, "exit_price": sl_price,
                        "exit_reason": "SL_TP_SAME_BAR", "pnl_ticks": -sl_ticks}
            if sl_touched:
                return {"exit_idx": i, "exit_price": sl_price,
                        "exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if tp_touched:
                return {"exit_idx": i, "exit_price": tp_price,
                        "exit_reason": "TP", "pnl_ticks": tp_ticks}
        else:  # SELL
            sl_touched = bar_high >= sl_price
            tp_touched = bar_low <= tp_price
            if sl_touched and tp_touched:
                return {"exit_idx": i, "exit_price": sl_price,
                        "exit_reason": "SL_TP_SAME_BAR", "pnl_ticks": -sl_ticks}
            if sl_touched:
                return {"exit_idx": i, "exit_price": sl_price,
                        "exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if tp_touched:
                return {"exit_idx": i, "exit_price": tp_price,
                        "exit_reason": "TP", "pnl_ticks": tp_ticks}

    # Time stop
    if end_idx - 1 > entry_idx:
        final_bar = bars[end_idx - 1]
        final_price = final_bar.get("price", entry_price)
        if final_price is None or not math.isfinite(float(final_price)):
            final_price = entry_price
        final_price = float(final_price)
        if direction == "BUY":
            pnl = (final_price - entry_price) / tick_size
        else:
            pnl = (entry_price - final_price) / tick_size
        return {"exit_idx": end_idx - 1, "exit_price": final_price,
                "exit_reason": "TIME", "pnl_ticks": pnl}

    return None
