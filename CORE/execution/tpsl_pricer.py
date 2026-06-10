"""tpsl_pricer.py — Calcul centralise prix TP/SL bracket.

Plan agent 04/05 Etape 2 : centralise la logique de calcul TP/SL pour
qu'elle soit reutilisable et testable.

Avant : duplique dans
  - databento_paper_trader_v2.py:execute_trade (Bot 2)
  - databento_paper_trader_v2.py:_bot3_execute_trade (Bot 3)
  - mia_paper_trader.py (Bot 1)
Maintenant : import unique depuis ici.
"""
from __future__ import annotations

from typing import Tuple


def calc_bracket_prices(
    side: str,
    ref_price: float,
    sl_ticks: int,
    tp_ticks: int,
    tick_size: float = 0.25,
) -> Tuple[float, float]:
    """Calcule (sl_price, tp_price) absolus depuis un prix de reference.

    Args:
        side : "LONG" ou "SHORT" (case insensitive)
        ref_price : prix d'entree de reference (live, fill, ou parquet)
        sl_ticks : distance SL en ticks (toujours positif)
        tp_ticks : distance TP en ticks (toujours positif)
        tick_size : taille du tick (0.25 pour ES/NQ)

    Returns:
        (sl_price, tp_price) tuple

    Examples:
        >>> calc_bracket_prices("LONG", 7250.0, 80, 120, 0.25)
        (7230.0, 7280.0)
        >>> calc_bracket_prices("SHORT", 27800.0, 200, 300, 0.25)
        (27850.0, 27725.0)
    """
    side_u = side.upper() if isinstance(side, str) else "LONG"
    sl_pts = sl_ticks * tick_size
    tp_pts = tp_ticks * tick_size
    if side_u == "LONG":
        return (ref_price - sl_pts, ref_price + tp_pts)
    return (ref_price + sl_pts, ref_price - tp_pts)


def slip_ticks(fill_price: float, ref_price: float, tick_size: float = 0.25) -> float:
    """Calcule le slippage en ticks entre fill et reference.

    Returns:
        slip absolu en ticks (toujours positif)
    """
    if ref_price <= 0 or fill_price <= 0:
        return 0.0
    return abs(fill_price - ref_price) / tick_size
