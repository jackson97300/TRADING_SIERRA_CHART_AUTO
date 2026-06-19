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
    from CORE.constants import get_tick_size, is_rth_bar
except ImportError:
    from constants import get_tick_size, is_rth_bar  # type: ignore

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
    sl_buffer_ticks = cfg.sl_buffer_ticks(symbol)

    # Trouve mur SL : pour SHORT = prix > entry, pour LONG = prix < entry
    sl_wall_name, wall_price, sl_tier = _find_sl_wall(bar, direction, entry_price)
    if wall_price <= 0:
        # Reason distinct si overnight ET des bandes vwap_d existaient (= gatees) :
        # c'est le gate qui a retire le seul mur -> tracable (J+1 grep volume bloque).
        # Si aucune bande vwap_d, c'est un vrai NO_SL_WALL_FOUND (pas le gate).
        reason = "NO_SL_WALL_FOUND"
        _vwap_d_keys = (
            "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d_sd2u",
            "vwap_d_sd2d", "vwap_d_sd3u", "vwap_d_sd3d",
        )
        if not is_rth_bar(bar) and any(bar.get(k) is not None for k in _vwap_d_keys):
            reason = "NO_SL_WALL_OVERNIGHT_VWAPD_GATED"
        return SLTPResult(
            accepted=False,
            reject_reason=reason,
            direction=direction,
        )

    # SL BUFFER anti stop-hunter : place SL DERRIERE le mur, pas AU mur exact
    # Jackson : "SL qui laisse respirer le prix pour eviter stop hunter"
    # Pour SHORT : SL au-dessus mur + buffer
    # Pour LONG : SL sous mur - buffer
    if direction == "SHORT":
        sl_price = wall_price + sl_buffer_ticks * tick
    else:
        sl_price = wall_price - sl_buffer_ticks * tick

    # Compute SL distance en ticks REELS (apres buffer)
    sl_distance_pts = abs(entry_price - sl_price)
    sl_ticks = int(round(sl_distance_pts / tick))

    # HARD CAP : si SL total (mur + buffer) trop loin -> REJECT
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

    # PLANCHER : si SL trop proche -> use min (anti-bruit micro)
    if sl_ticks < sl_min_ticks:
        sl_ticks = sl_min_ticks
        if direction == "SHORT":
            sl_price = entry_price + sl_min_ticks * tick
        else:
            sl_price = entry_price - sl_min_ticks * tick

    # TP : R:R 1.5 par defaut (empirique : 2.0 trop ambitieux, jamais atteint)
    # TP_ticks = SL_ticks * 1.5 -> plus de TP hits, edge positif possible
    rr_target = 1.5
    tp_ticks = int(round(sl_ticks * rr_target))
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
    """Trouve le mur SL le PLUS PROCHE valide parmi TOUS les tiers.

    Hierarchie informative (pas filtrant) :
      Tier 1 : VWAP SD bands, cur_vah/val, EXT_EDGE_*
      Tier 2 : prev_vah/val, ovn_high/low, ib_high/low, SD2/SD3
      Tier 3 : pdh/pdl, sess_high/low, mq levels

    Strategie : on collecte tous murs valides (>entry pour SHORT, <entry pour LONG)
    et on prend celui dont la distance est MINIMALE.

    Returns:
        (wall_name, price, tier) ou ("", 0.0, 0) si aucun.
    """
    if direction == "SHORT":
        valid = lambda v: isinstance(v, (int, float)) and v > entry_price
    else:
        valid = lambda v: isinstance(v, (int, float)) and v < entry_price

    # Collecte TOUS les murs candidats avec leurs tiers
    candidates_all = []

    # Tier 1
    t1_pairs = [
        ("VWAP_D_SD1U" if direction == "SHORT" else "VWAP_D_SD1D",
         bar.get("vwap_d_sd1u" if direction == "SHORT" else "vwap_d_sd1d"), 1),
        ("CUR_VAH" if direction == "SHORT" else "CUR_VAL",
         bar.get("cur_vah_lvl") or bar.get("cur_vah") if direction == "SHORT"
         else bar.get("cur_val_lvl") or bar.get("cur_val"), 1),
        ("EXT_EDGE",
         bar.get("ext_edge_sell_price" if direction == "SHORT" else "ext_edge_buy_price"), 1),
        ("EXT_COLOR",
         bar.get("ext_color_up_price" if direction == "SHORT" else "ext_color_dn_price"), 1),
        ("EXT_LONG",
         bar.get("ext_long_up_price" if direction == "SHORT" else "ext_long_dn_price"), 1),
    ]
    # Tier 2
    t2_pairs = [
        ("VWAP_D_SD2U" if direction == "SHORT" else "VWAP_D_SD2D",
         bar.get("vwap_d_sd2u" if direction == "SHORT" else "vwap_d_sd2d"), 2),
        ("PREV_VAH" if direction == "SHORT" else "PREV_VAL",
         bar.get("prev_vah") or bar.get("prev_vah_lvl") if direction == "SHORT"
         else bar.get("prev_val") or bar.get("prev_val_lvl"), 2),
        ("OVN_HIGH" if direction == "SHORT" else "OVN_LOW",
         bar.get("ovn_high") if direction == "SHORT" else bar.get("ovn_low"), 2),
        ("IB_HIGH" if direction == "SHORT" else "IB_LOW",
         bar.get("ib_high") if direction == "SHORT" else bar.get("ib_low"), 2),
        ("SWING_HIGH" if direction == "SHORT" else "SWING_LOW",
         bar.get("swing_high") if direction == "SHORT" else bar.get("swing_low"), 2),
    ]
    # Tier 3
    t3_pairs = [
        ("VWAP_D_SD3U" if direction == "SHORT" else "VWAP_D_SD3D",
         bar.get("vwap_d_sd3u" if direction == "SHORT" else "vwap_d_sd3d"), 3),
        ("PDH" if direction == "SHORT" else "PDL",
         bar.get("pdh") if direction == "SHORT" else bar.get("pdl"), 3),
        ("SESS_HIGH" if direction == "SHORT" else "SESS_LOW",
         bar.get("sess_high") if direction == "SHORT" else bar.get("sess_low"), 3),
    ]

    # GATE vwap_d overnight (fix 18/06) : vwap_d + bandes SD sont RTH-anchored
    # (Sierra natif) et ne resettent PAS a la frontiere CME 18:00 ET. Hors RTH
    # elles portent l'ancrage de la veille = murs SL perimes (48% des bars
    # overnight ont une bande SD a <=20t, min 0t = SL absurde). On les exclut
    # hors RTH. Les autres murs (sess/ovn/pdh/pdl/ib/prev) resettent correctement.
    is_rth = is_rth_bar(bar)

    for pairs in (t1_pairs, t2_pairs, t3_pairs):
        for name, price, tier in pairs:
            if price is None:
                continue
            if not is_rth and name.startswith("VWAP_D_SD"):
                continue  # vwap_d perime overnight -> ne pas l'utiliser comme mur SL
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if valid(price):
                distance = abs(price - entry_price)
                candidates_all.append((distance, name, price, tier))

    if not candidates_all:
        return "", 0.0, 0

    # Trouve le PLUS PROCHE
    candidates_all.sort()
    _, name, price, tier = candidates_all[0]
    return name, price, tier
