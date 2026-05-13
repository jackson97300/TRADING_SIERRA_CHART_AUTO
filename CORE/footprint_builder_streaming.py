"""footprint_builder_streaming.py

API streaming-aware footprint_builder.py.
HELPER (PAS sub-engine ML) : construit le dict cells pour la bar courante
depuis trades_in_window. Le dict est consomme par :
  - edge_zones_streaming (deja livre commit 6c7de8f)
  - phase_b_plus_plus_streaming (a venir)
  - Toute autre future feature qui depend du footprint cellule

Stateless : pure function par bar. Le caller (Live Enricher service)
maintient le trades buffer et fournit la fenetre [bar_t-1, bar_t).

Aucune feature ML sortie. Le retour est un dict :
  cells[price_bucket] -> {ask_vol, bid_vol, total_vol, n_trades}

Mirror batch build_footprint_per_bar() : meme convention Databento side
('A'=aggressor BUY -> ask_vol, 'B'=aggressor SELL -> bid_vol, 'N'=ignore).

Fix FP precision MGC tick=0.10 (commit 11/05 J3) : .round(4) sur bucket.
"""
from __future__ import annotations

from typing import Dict, List, Optional

TICK_SIZE = 0.25  # default ES/NQ


def build_footprint_cells_streaming(
    trades_in_window: Optional[List[dict]],
    tick: float = TICK_SIZE,
) -> Dict[float, Dict[str, float]]:
    """Construit le dict cells footprint pour UNE bar depuis les trades.

    Mirror batch build_footprint_per_bar() pour une seule bar.

    Args:
        trades_in_window : list[dict] avec keys 'price', 'size', 'side'.
                            None ou [] = aucun trade -> dict vide.
        tick : tick size (0.25 ES/NQ, 0.10 MGC).

    Returns:
        dict[price_bucket -> {'ask_vol', 'bid_vol', 'total_vol', 'n_trades'}]
        Trades side='N' (auctions/halts) ignores. Bucket arrondi au tick.
    """
    cells: Dict[float, Dict[str, float]] = {}
    if not trades_in_window:
        return cells

    for trade in trades_in_window:
        price = trade.get("price")
        size = trade.get("size")
        side = trade.get("side")
        if price is None or size is None or side not in ("A", "B"):
            continue
        try:
            pf = float(price)
            sf = float(size)
            if pf <= 0 or sf <= 0:
                continue
        except (TypeError, ValueError):
            continue

        # Bucket au tick + round(4) pour FP precision MGC tick=0.10
        bucket = round((pf / tick), 0) * tick
        bucket = round(bucket, 4)

        if bucket not in cells:
            cells[bucket] = {
                "ask_vol": 0.0,
                "bid_vol": 0.0,
                "total_vol": 0.0,
                "n_trades": 0,
            }
        if side == "A":
            cells[bucket]["ask_vol"] += sf
        else:  # side == "B"
            cells[bucket]["bid_vol"] += sf
        cells[bucket]["total_vol"] += sf
        cells[bucket]["n_trades"] += 1

    return cells
