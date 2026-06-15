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
    """ES SHORT : mur Tier1 @ entry + 28 ticks (= 7 points) -> REJECT (cap 12)."""
    bar = {
        # Mur EXT_EDGE_SELL trop loin (28 ticks au-dessus)
        "ext_edge_sell_price": 7633.75 + 7.0,  # +28 ticks ES = +7 points
        "cur_vah_lvl": 7633.75 + 8.0,
        "vwap_d_sd1u": 7633.75 + 10.0,
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is False
    assert "SL_HARD_CAP_EXCEEDED" in result.reject_reason
    assert result.sl_ticks > 12  # confirme cap depasse


def test_sl_hard_cap_es_accepts_close_wall():
    """ES SHORT : mur Tier1 @ entry + 10 ticks (= 2.5 points) -> ACCEPT."""
    bar = {
        "ext_edge_sell_price": 7633.75 + 2.5,  # +10 ticks ES
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True, f"Reject reason: {result.reject_reason}"
    assert result.sl_ticks == 10
    assert result.sl_wall == "EXT_EDGE"


def test_sl_hard_cap_nq_rejects_far_wall():
    """NQ SHORT : mur Tier1 @ entry + 30 ticks (cap 20) -> REJECT."""
    bar = {
        "ext_edge_sell_price": 21500.0 + 7.5,  # +30 ticks NQ = +7.5 points
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=21500.0, symbol="NQ",
    )
    assert result.accepted is False
    assert "SL_HARD_CAP_EXCEEDED" in result.reject_reason


def test_sl_min_floor_anti_bruit():
    """ES LONG : mur Tier1 @ entry - 1 tick -> use min 4 ticks (anti-bruit)."""
    bar = {
        "ext_edge_buy_price": 7633.75 - 0.25,  # 1 tick (too close)
    }
    result = compute_sl_tp(
        bar, direction="LONG", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True
    assert result.sl_ticks == 4  # plancher applique


def test_no_wall_returns_reject():
    """Aucun mur valide -> REJECT."""
    bar = {}  # vide
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is False
    assert result.reject_reason == "NO_SL_WALL_FOUND"


def test_long_finds_wall_below():
    """LONG cherche mur SOUS entry (pas au-dessus)."""
    bar = {
        # Mur ext_edge_buy SOUS entry = valide pour LONG
        "ext_edge_buy_price": 7633.75 - 1.5,  # -6 ticks
    }
    result = compute_sl_tp(
        bar, direction="LONG", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True
    assert result.sl_price < 7633.75
    assert result.sl_ticks == 6


def test_short_finds_wall_above():
    """SHORT cherche mur AU-DESSUS entry."""
    bar = {
        "ext_edge_sell_price": 7633.75 + 2.0,  # +8 ticks
    }
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.accepted is True
    assert result.sl_price > 7633.75


def test_rr_ratio_2():
    """R:R par defaut = 2:1."""
    bar = {"ext_edge_sell_price": 7633.75 + 2.5}  # 10 ticks
    result = compute_sl_tp(
        bar, direction="SHORT", entry_price=7633.75, symbol="ES",
    )
    assert result.rr_ratio == 2.0
    assert result.tp_ticks == 20  # 2 * 10
