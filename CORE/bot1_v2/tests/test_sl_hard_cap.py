"""Tests SL Hard Cap - root cause trade -$967.

Le trade -$967 : SLTPEngine a place SL @ mur Tier1 EXT_EDGE_SELL = 28 ticks
au-dessus entry. Marche n'a JAMAIS atteint SL = squeeze 60min = -$967.

Bot 1 v2 : si mur Tier1 > 12 ticks ES / 20 ticks NQ -> REJECT trade.
"""
from __future__ import annotations

import pytest

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.risk.sl_tp import compute_sl_tp


def test_sl_hard_cap_es_rejects_far_wall():
    """ES SHORT : mur Tier1 @ entry + 28 ticks (= 7 points) + buffer 3t = 31t -> REJECT (cap 20)."""
    bar = {
        # Mur trop loin (28 ticks au-dessus)
        "ext_edge_sell_price": 7633.75 + 7.0,  # +28 ticks ES = +7 points
        "cur_vah_lvl": 7633.75 + 8.0,
        "vwap_d_sd1u": 7633.75 + 10.0,
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is False
    assert "SL_HARD_CAP_EXCEEDED" in result.reject_reason
    assert result.sl_ticks > 20  # confirme cap depasse


def test_sl_hard_cap_es_accepts_close_wall():
    """ES SHORT : mur @ entry + 10 ticks + buffer 3t = SL 13t -> ACCEPT (cap 20)."""
    bar = {
        "ext_edge_sell_price": 7633.75 + 2.5,  # +10 ticks ES
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True, f"Reject reason: {result.reject_reason}"
    # Mur 10t + buffer 3t = SL 13t reel
    assert result.sl_ticks == 13, f"Expected 13t (10 + 3 buffer), got {result.sl_ticks}"
    assert result.sl_wall == "EXT_EDGE"


def test_sl_hard_cap_nq_rejects_far_wall():
    """NQ SHORT : mur Tier1 @ entry + 32 ticks + buffer 5t = 37t -> REJECT (cap 30)."""
    bar = {
        "ext_edge_sell_price": 21500.0 + 8.0,  # +32 ticks NQ
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=21500.0, symbol="NQ",
    )
    assert result.accepted is False
    assert "SL_HARD_CAP_EXCEEDED" in result.reject_reason


def test_sl_min_floor_anti_bruit():
    """ES LONG : mur Tier1 @ entry - 1 tick + buffer 3t = 4t < min 6t -> use min 6t."""
    bar = {
        "ext_edge_buy_price": 7633.75 - 0.25,  # 1 tick (too close)
    }
    result = compute_sl_tp(
        bar, direction="LONG", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True
    assert result.sl_ticks == 6  # plancher applique (min ES = 6)


def test_no_wall_returns_reject():
    """Aucun mur valide -> REJECT."""
    bar = {}  # vide
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is False
    assert result.reject_reason == "NO_SL_WALL_FOUND"


def test_long_finds_wall_below():
    """LONG cherche mur SOUS entry (pas au-dessus) + buffer."""
    bar = {
        # Mur ext_edge_buy SOUS entry = valide pour LONG
        "ext_edge_buy_price": 7633.75 - 1.5,  # -6 ticks
    }
    result = compute_sl_tp(
        bar, direction="LONG", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True
    assert result.sl_price < 7633.75
    # Mur 6t + buffer 3t = SL 9t
    assert result.sl_ticks == 9


def test_short_finds_wall_above():
    """SHORT cherche mur AU-DESSUS entry + buffer."""
    bar = {
        "ext_edge_sell_price": 7633.75 + 2.0,  # +8 ticks
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True
    assert result.sl_price > 7633.75


def test_rr_ratio_15():
    """R:R par defaut = 1.5:1 (empirique : 2.0 jamais atteint).

    Mur 10t + buffer 3t = SL 13t. TP = 13 * 1.5 = 19.5 -> arrondi 20t.
    """
    bar = {"ext_edge_sell_price": 7633.75 + 2.5}  # 10 ticks
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert abs(result.rr_ratio - 1.5) < 0.1, f"RR={result.rr_ratio}"
    # 13 * 1.5 = 19.5 -> round to 20
    assert result.tp_ticks == 20, f"Expected 20 (13*1.5 rounded), got {result.tp_ticks}"


def test_sl_buffer_anti_hunter():
    """Verifie que SL est DERRIERE le mur, pas AU mur exact (anti stop-hunter).

    Jackson : "SL qui laisse respirer le prix pour eviter stop hunter"
    """
    bar = {"ext_edge_sell_price": 7640.00}  # mur exact a +25 ticks
    entry = 7633.75
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=entry, symbol="ES",
    )
    if result.accepted:
        # SL doit etre AU-DESSUS du mur 7640.00 (= mur + 3 ticks buffer = 7640.75)
        assert result.sl_price > 7640.00, (
            f"SL doit etre derriere le mur (anti-hunter). "
            f"SL={result.sl_price} mur={7640.00}"
        )
    else:
        # Si rejete par cap (25+3=28t > 20), c'est ok
        assert "SL_HARD_CAP_EXCEEDED" in result.reject_reason
