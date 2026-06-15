"""SL/TP risk management Bot 1 v2.

Reutilise SLTPEngine existant (CORE/mia_sltp.py) + AJOUTE HARD CAP absolu.

Root cause trade -$967 du 15/06 :
  - SLTPEngine a place SL @ mur Tier1 EXT_EDGE_SELL = 7 points = 28 ticks
  - Aucun cap absolu : tracking sl_ticks=18 mais reel=28
  - Marche n'a JAMAIS atteint SL = squeeze 60 min = -$967

Bot 1 v2 :
  - Si mur Tier1 > SL_HARD_CAP_TICKS (12 ES / 20 NQ) -> REJECT trade
  - Si mur Tier1 < SL_MIN_TICKS (4 ES / 8 NQ) -> use min (anti-bruit micro)
  - Pas de modification SLTPEngine, juste wrapper
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from CORE.constants import get_tick_size
except ImportError:
    from constants import get_tick_size  # type: ignore

from CORE.bot1_v2.config import Bot1V2Config


@dataclass(frozen=True)
class SLTPResult:
    """Result du calcul SL/TP.

    accepted=False = trade reject (cap exceeded ou pas de mur valide).
    accepted=True = trade acceptable avec sl_price/tp_price.
    """
    accepted: bool
    sl_price: float = 0.0
    tp_price: float = 0.0
    sl_ticks: int = 0  # REEL en ticks (pas le legacy bugge)
    tp_ticks: int = 0
    sl_wall: str = ""  # source mur (EXT_EDGE_SELL, VWAP_D_SD1, etc.)
    sl_tier: int = 0   # 1/2/3
    reject_reason: str = ""
    direction: str = ""  # LONG / SHORT
    rr_ratio: float = 0.0


def compute_sl_tp(
    bar: dict,
    direction: str,
    entry_price: float,
    symbol: str,
    cfg: Optional[Bot1V2Config] = None,
) -> SLTPResult:
    """Calcule SL/TP avec HARD CAP absolu.

    Args:
        bar : dict sierra_enriched + dashboard data
        direction : "LONG" / "SHORT"
        entry_price : prix d'entree theorique
        symbol : "ES" / "NQ" / "MGC"
        cfg : config

    Returns:
        SLTPResult avec accepted=False si cap exceeded.
    """
    if cfg is None:
        cfg = Bot1V2Config.from_env()

    if direction not in ("LONG", "SHORT"):
        return SLTPResult(
            accepted=False,
            reject_reason=f"DIRECTION_INVALID:{direction}",
            direction=direction,
        )

    tick = get_tick_size(symbol)
    sl_cap_ticks = cfg.sl_hard_cap_ticks(symbol)
    sl_min_ticks = cfg.sl_min_ticks(symbol)

    # Trouve mur SL : pour SHORT = prix > entry, pour LONG = prix < entry
    # On utilise les niveaux disponibles dans le bar sierra_enriched
    sl_wall_name, sl_price, sl_tier = _find_sl_wall(bar, direction, entry_price)
    if sl_price <= 0:
        return SLTPResult(
            accepted=False,
            reject_reason="NO_SL_WALL_FOUND",
            direction=direction,
        )

    # Compute SL distance en ticks REELS
    sl_distance_pts = abs(entry_price - sl_price)
    sl_ticks = int(round(sl_distance_pts / tick))

    # HARD CAP : si mur trop loin -> REJECT
    if sl_ticks > sl_cap_ticks:
        return SLTPResult(
            accepted=False,
            sl_price=sl_price,
            sl_ticks=sl_ticks,
            sl_wall=sl_wall_name,
            sl_tier=sl_tier,
            reject_reason=f"SL_HARD_CAP_EXCEEDED:{sl_ticks}t>{sl_cap_ticks}t",
            direction=direction,
        )

    # PLANCHER : si mur trop proche -> use min (anti-bruit micro)
    if sl_ticks < sl_min_ticks:
        sl_ticks = sl_min_ticks
        if direction == "SHORT":
            sl_price = entry_price + sl_min_ticks * tick
        else:
            sl_price = entry_price - sl_min_ticks * tick

    # TP : R:R 2.0 par defaut (peut etre override par TP de mur si meilleur)
    tp_ticks = sl_ticks * 2
    if direction == "LONG":
        tp_price = entry_price + tp_ticks * tick
    else:
        tp_price = entry_price - tp_ticks * tick
    rr = tp_ticks / sl_ticks if sl_ticks > 0 else 0.0

    return SLTPResult(
        accepted=True,
        sl_price=sl_price,
        tp_price=tp_price,
        sl_ticks=sl_ticks,
        tp_ticks=tp_ticks,
        sl_wall=sl_wall_name,
        sl_tier=sl_tier,
        direction=direction,
        rr_ratio=rr,
    )


def _find_sl_wall(
    bar: dict, direction: str, entry_price: float,
) -> tuple[str, float, int]:
    """Trouve le mur SL le plus proche valide.

    Hierarchie Tier 1/2/3 simplifiee :
      Tier 1 : niveau immediat (VWAP SD1, cur_vah/val, EXT_EDGE_*)
      Tier 2 : niveau swing (prev_vah/val, ovn_high/low, ib_high/low)
      Tier 3 : niveau journalier (pdh/pdl, mq levels)

    Pour SHORT : cherche prix > entry
    Pour LONG : cherche prix < entry

    Returns:
        (wall_name, price, tier) ou ("", 0.0, 0) si aucun.
    """
    if direction == "SHORT":
        op = lambda v: isinstance(v, (int, float)) and v > entry_price
    else:
        op = lambda v: isinstance(v, (int, float)) and v < entry_price

    # Tier 1 : VWAP SD bands + cur_vah/val
    candidates_t1 = [
        ("VWAP_D_SD1U" if direction == "SHORT" else "VWAP_D_SD1D",
         bar.get("vwap_d_sd1u" if direction == "SHORT" else "vwap_d_sd1d")),
        ("CUR_VAH" if direction == "SHORT" else "CUR_VAL",
         bar.get("cur_vah_lvl") or bar.get("cur_vah")),
        ("CUR_VAH" if direction == "SHORT" else "CUR_VAL",
         bar.get("cur_val_lvl") if direction == "LONG" else bar.get("cur_vah_lvl")),
        ("EXT_EDGE",
         bar.get("ext_edge_sell_price" if direction == "SHORT" else "ext_edge_buy_price")),
    ]
    for name, price in candidates_t1:
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if op(price):
            return name, price, 1

    # Tier 2 : prev_vah/val + ovn + ib
    candidates_t2 = [
        ("PREV_VAH" if direction == "SHORT" else "PREV_VAL",
         bar.get("prev_vah") or bar.get("prev_vah_lvl")),
        ("OVN_HIGH" if direction == "SHORT" else "OVN_LOW",
         bar.get("ovn_high") if direction == "SHORT" else bar.get("ovn_low")),
        ("IB_HIGH" if direction == "SHORT" else "IB_LOW",
         bar.get("ib_high") if direction == "SHORT" else bar.get("ib_low")),
    ]
    for name, price in candidates_t2:
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if op(price):
            return name, price, 2

    # Tier 3 : pdh/pdl + sess_high/low
    candidates_t3 = [
        ("PDH" if direction == "SHORT" else "PDL",
         bar.get("pdh") if direction == "SHORT" else bar.get("pdl")),
        ("SESS_HIGH" if direction == "SHORT" else "SESS_LOW",
         bar.get("sess_high") if direction == "SHORT" else bar.get("sess_low")),
    ]
    for name, price in candidates_t3:
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if op(price):
            return name, price, 3

    return "", 0.0, 0
