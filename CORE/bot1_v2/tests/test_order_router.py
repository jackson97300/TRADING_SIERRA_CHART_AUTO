"""Tests OrderRouter Bot 1 v2 - signature legacy 3-tuple + 4-tuple + dict.

FIX 17/06 Jackson : send_market_order retourne tuple 3 elements
(parent_cid, tp_cid, sl_cid). Le code utilisait `len(result) >= 4` qui ne
matchait jamais → tombait dans else final → success=bool(tuple_non_vide)=True
meme en abort ("", "", "") + parent_cid generic conserve au lieu du vrai
CID DTC → paper_tracker desync sur fills TP/SL.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from CORE.bot1_v2.cluster import ClusterDecision
from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.execution.order_router import OrderRouter, OrderResult


def _make_decision(
    tradable: bool = True,
    symbol: str = "ES",
    direction: str = "SHORT",
    skip_reason: str = "",
) -> ClusterDecision:
    """Decision (frozen) minimale pour tester send_bracket."""
    return ClusterDecision(
        tradable=tradable,
        skip_reason=skip_reason,
        signal_id="test_signal",
        direction=direction,
        entry_price=7580.5,
        sl_price=7582.0,
        tp_price=7578.25,
        sl_ticks=6,
        tp_ticks=9,
        rr_ratio=1.5,
        sl_wall="CUR_VAH",
        n_micros=1,
        symbol=symbol,
        stars_count=6,
        stars_total=7,
    )


def test_send_bracket_dry_run():
    """Dry run : retourne CIDs generes + entry_price."""
    cfg = Bot1V2Config.from_env()
    router = OrderRouter(cfg=cfg, dry_run=True, dtc_connector=None)
    decision = _make_decision()
    result = router.send_bracket(decision)
    assert result.success is True
    assert result.dry_run is True
    assert result.parent_cid.startswith("BOT1V2_P_")
    assert result.tp_cid.startswith("BOT1V2_TP_")
    assert result.sl_cid.startswith("BOT1V2_SL_")
    assert result.fill_price == 7580.5


def test_send_bracket_dtc_null_returns_fail():
    """Prod mode avec dtc=None → fail explicite."""
    cfg = Bot1V2Config.from_env()
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=None)
    result = router.send_bracket(_make_decision())
    assert result.success is False
    assert "DTC_CONNECTOR_NULL_IN_PROD" in result.error_msg


def test_send_bracket_tuple_3_elements_success():
    """REGRESSION TEST FIX 17/06 : tuple 3 elements DTC reel utilise les vrais CIDs."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    # send_market_order retourne tuple 3 elements (signature reelle)
    mock_dtc.send_market_order.return_value = (
        "MIA_P_abc123", "MIA_TP_def456", "MIA_SL_ghi789",
    )
    mock_dtc.get_last_fill_price.return_value = 7580.25  # fill broker reel
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    assert result.success is True
    # CRITIQUE : doit utiliser les vrais CIDs DTC, pas les generic BOT1V2_*
    assert result.parent_cid == "MIA_P_abc123"
    assert result.tp_cid == "MIA_TP_def456"
    assert result.sl_cid == "MIA_SL_ghi789"
    # fill_price recupere via get_last_fill_price
    assert result.fill_price == 7580.25


def test_send_bracket_tuple_3_elements_abort_empty_strings():
    """Si send_market_order retourne ("", "", "") = abort timeout → success=False."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_market_order.return_value = ("", "", "")  # parent timeout abort
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    # CRITIQUE : success doit etre False (avant le fix : success=bool(tuple_non_vide)=True)
    assert result.success is False


def test_send_bracket_tuple_3_elements_no_get_last_fill():
    """Si dtc n'a pas get_last_fill_price, fallback decision.entry_price."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock(spec=["send_market_order"])  # pas de get_last_fill_price
    mock_dtc.send_market_order.return_value = (
        "MIA_P_xyz", "MIA_TP_xyz", "MIA_SL_xyz",
    )
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    assert result.success is True
    assert result.fill_price == 7580.5  # = decision.entry_price


def test_send_bracket_tuple_4_elements_legacy_backward_compat():
    """Backward compat : si DTC evolue et retourne 4 elements (incl. fill_price)."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_market_order.return_value = (
        "MIA_P_4el", "MIA_TP_4el", "MIA_SL_4el", 7581.0,
    )
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    assert result.success is True
    assert result.parent_cid == "MIA_P_4el"
    assert result.fill_price == 7581.0  # = element 4 du tuple


def test_send_bracket_dict_result_backward_compat():
    """Backward compat dict (jamais utilise mais code legacy le tolerait)."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_market_order.return_value = {
        "success": True, "fill_price": 7579.75,
    }
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    assert result.success is True
    assert result.fill_price == 7579.75


def test_send_bracket_get_last_fill_exception_fallback():
    """Si get_last_fill_price raise, fallback decision.entry_price."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_market_order.return_value = (
        "MIA_P_xyz", "MIA_TP_xyz", "MIA_SL_xyz",
    )
    mock_dtc.get_last_fill_price.side_effect = RuntimeError("DTC freeze")
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    assert result.success is True
    assert result.fill_price == 7580.5  # = decision.entry_price


def test_send_bracket_exception_in_send_market_order():
    """Exception dans send_market_order → success=False avec error_msg."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_market_order.side_effect = ConnectionError("DTC down")
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    result = router.send_bracket(_make_decision())
    assert result.success is False
    assert "DTC_EXCEPTION" in result.error_msg
    assert "ConnectionError" in result.error_msg


def test_send_bracket_not_tradable():
    """Decision non tradable → reject sans appeler dtc."""
    cfg = Bot1V2Config.from_env()
    mock_dtc = MagicMock()
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    decision = _make_decision(tradable=False, skip_reason="QUALITY_INSUFFICIENT")
    result = router.send_bracket(decision)
    assert result.success is False
    assert "DECISION_NOT_TRADABLE" in result.error_msg
    mock_dtc.send_market_order.assert_not_called()
