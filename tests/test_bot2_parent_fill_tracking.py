"""Tests Bot 2 PATCH R4 — Parent fill tracking entry_price reel.

Bug observe long terme (audit 02/05) :
- `_on_dtc_fill` ne traitait que TP/SL/close → fill PARENT ignore silencieusement
- pos["entry"] = signal_price (jamais update avec fill_price reel broker)
- Consequences :
  * pnl_ticks calcule sur signal_price (biais slippage entry sur tous trades)
  * Snapshots ML features_at_entry pollues (entry_price biaise)
  * Slip entry non mesure (impossible auditer execution quality)

Fix R4 (15 LOC + 5 reserve agent) :
1. Reconnaitre fill PARENT (order_id == pos["parent_id"]) → update pos["entry"]
2. Calculer slip_entry_ticks = (fill_price - signal_price) / TICK_SIZE * dir_sign
3. Emit PARENT_FILL_RECORDED avec contexte
4. Fallback parent_id dans lookup symbol (race _order_to_symbol pas populate)
5. Edge case : fill TP arrive AVANT fill PARENT → fallback signal_price OK
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _build_mock_trader_with_position(symbol="ES", side="BUY", signal_price=7200.0,
                                       parent_id="MIA_P_test",
                                       tp_cid="MIA_TP_test",
                                       sl_cid="MIA_SL_test"):
    """Mock minimal d'un BotTrader avec 1 position ouverte (post send_market_order)."""
    from CORE.databento_paper_trader import DatabentoPaperTrader as BotTrader

    trader = BotTrader.__new__(BotTrader)
    trader.cfg = MagicMock()
    trader.cfg.trade_account = "Sim2"
    trader.cfg.quantity = 3

    trader.active_positions = {
        symbol: {
            "parent_id": parent_id,
            "tp_cid": tp_cid,
            "sl_cid": sl_cid,
            "close_cid": None,
            "side": side,
            "entry": signal_price,  # signal_price avant fill PARENT
            "ts_open": "2026-05-02T13:00:00+00:00",
        }
    }
    trader._order_to_symbol = {
        parent_id: symbol,
        tp_cid: symbol,
        sl_cid: symbol,
    }
    import threading
    trader._pos_lock = threading.Lock()

    trader.dtc = MagicMock()
    trader.dtc._server_order_ids = {}
    trader.dtc._send = MagicMock()

    # Mocks for full TP/SL flow (post-PATCH-R4 close path)
    trader._log_closed_trade = MagicMock()
    trader.risk = MagicMock()
    trader.risk.on_trade_close = MagicMock()
    trader.alerter = MagicMock()
    trader.alerter.send = MagicMock()
    trader._persist_active_positions = MagicMock()

    return trader


def _make_fill(order_id, fill_price):
    """Mock objet fill avec attributs DTC."""
    fill = MagicMock()
    fill.order_id = order_id
    fill.fill_price = fill_price
    fill.symbol = "ESM26-CME"
    return fill


# ─────────────────────────────────────────────────────────────────────
# Test 1 : fill PARENT → update entry + slip
# ─────────────────────────────────────────────────────────────────────

class TestParentFillUpdatesEntry:
    """Test 1 — fill PARENT met a jour pos["entry"] avec fill_price reel."""

    def test_parent_fill_buy_slippage_positive(self, monkeypatch):
        """BUY signal @ 7200, fill @ 7200.50 → slip +2.0 ticks (defavorable)."""
        from CORE import databento_paper_trader as dpt
        emitted = []
        monkeypatch.setattr(dpt, "_emit", lambda code, **kw: emitted.append((code, kw)))

        trader = _build_mock_trader_with_position(side="BUY", signal_price=7200.0)
        fill = _make_fill("MIA_P_test", 7200.50)

        trader._on_dtc_fill(fill)

        # Position toujours active (pas close)
        assert "ES" in trader.active_positions
        # Entry update avec fill_price reel
        assert trader.active_positions["ES"]["entry"] == 7200.50
        # Slip calcule (BUY, fill > signal = defavorable +2 ticks)
        assert trader.active_positions["ES"]["slip_entry_ticks"] == 2.0
        # Event emit
        codes = [c for c, _ in emitted]
        assert "PARENT_FILL_RECORDED" in codes

    def test_parent_fill_sell_slippage_negative(self, monkeypatch):
        """SELL signal @ 7200, fill @ 7200.25 → slip +1.0 ticks (defavorable SELL)."""
        from CORE import databento_paper_trader as dpt
        monkeypatch.setattr(dpt, "_emit", lambda code, **kw: None)

        trader = _build_mock_trader_with_position(side="SELL", signal_price=7200.0)
        fill = _make_fill("MIA_P_test", 7200.25)

        trader._on_dtc_fill(fill)

        # SELL fill > signal = defavorable (sell more cheap)
        assert trader.active_positions["ES"]["entry"] == 7200.25
        # dir_sign = -1 pour SELL → (7200.25 - 7200.0) / 0.25 * -1 = -1.0
        # slippage defavorable SELL = signe negatif (entree pire)
        assert trader.active_positions["ES"]["slip_entry_ticks"] == -1.0


# ─────────────────────────────────────────────────────────────────────
# Test 2 : fill TP apres PARENT → pnl calcule sur fill_price reel (pas signal)
# ─────────────────────────────────────────────────────────────────────

class TestTpFillAfterParentUsesRealEntry:
    """Test 2 — fill TP apres fill PARENT → pnl calcule depuis fill_price."""

    def test_tp_after_parent_fill_uses_real_entry(self, monkeypatch):
        from CORE import databento_paper_trader as dpt
        emitted = []
        monkeypatch.setattr(dpt, "_emit", lambda code, **kw: emitted.append((code, kw)))

        trader = _build_mock_trader_with_position(side="BUY", signal_price=7200.0)

        # Etape 1 : fill PARENT @ 7200.50 (slip +2t)
        trader._on_dtc_fill(_make_fill("MIA_P_test", 7200.50))
        assert trader.active_positions["ES"]["entry"] == 7200.50

        # Etape 2 : fill TP @ 7210.0
        trader._on_dtc_fill(_make_fill("MIA_TP_test", 7210.0))

        # Position fermee
        assert "ES" not in trader.active_positions
        # pnl_ticks calcule sur fill_price (7210 - 7200.50) / 0.25 = 38 ticks
        # vs si calcule sur signal_price : (7210 - 7200) / 0.25 = 40 ticks
        # → 2 ticks de difference (= le slippage entry)
        tp_event = next((kw for c, kw in emitted if c == "TRADE_CLOSE_TP"), None)
        assert tp_event is not None
        assert tp_event["pnl"] == pytest.approx(38.0, abs=0.1), \
            f"pnl_ticks devrait etre 38 (fill_price-based), got {tp_event['pnl']}"


# ─────────────────────────────────────────────────────────────────────
# Test 3 : edge case — fill TP arrive AVANT fill PARENT (race) → fallback signal_price
# ─────────────────────────────────────────────────────────────────────

class TestTpFillBeforeParentFallback:
    """Test 3 — race condition : fill TP arrive AVANT fill PARENT.

    Scenario rare mais possible si :
    - Marche tres rapide, parent fill et TP fill arrivent dans le meme tick
    - DTC reorder les messages (UDP-like ?)
    - Bot recoit TP avant PARENT

    Fallback : pnl calcule sur signal_price (entry initial), puis position fermee.
    Pas de crash. Slip_entry_ticks reste non set (pas mesure).
    """

    def test_tp_before_parent_fallback_signal_price(self, monkeypatch):
        from CORE import databento_paper_trader as dpt
        emitted = []
        monkeypatch.setattr(dpt, "_emit", lambda code, **kw: emitted.append((code, kw)))

        trader = _build_mock_trader_with_position(side="BUY", signal_price=7200.0)

        # Fill TP arrive AVANT fill PARENT
        trader._on_dtc_fill(_make_fill("MIA_TP_test", 7210.0))

        # Position fermee (pas de crash)
        assert "ES" not in trader.active_positions
        # pnl calcule sur signal_price (entry n'a pas ete update)
        tp_event = next((kw for c, kw in emitted if c == "TRADE_CLOSE_TP"), None)
        assert tp_event is not None
        # (7210 - 7200) / 0.25 = 40 ticks
        assert tp_event["pnl"] == pytest.approx(40.0, abs=0.1)
        # Pas d'event PARENT_FILL_RECORDED emit
        assert "PARENT_FILL_RECORDED" not in [c for c, _ in emitted]


# ─────────────────────────────────────────────────────────────────────
# Test 4 : fallback parent_id si _order_to_symbol pas populate (race callback)
# ─────────────────────────────────────────────────────────────────────

class TestParentFillFallbackOrderToSymbol:
    """Test 4 — _order_to_symbol vide → fallback iter active_positions par parent_id."""

    def test_parent_fill_fallback_when_order_to_symbol_empty(self, monkeypatch):
        """Si _order_to_symbol pas populate (race entre fill et register), parent_id
        match dans active_positions.parent_id."""
        from CORE import databento_paper_trader as dpt
        monkeypatch.setattr(dpt, "_emit", lambda code, **kw: None)

        trader = _build_mock_trader_with_position(side="BUY", signal_price=7200.0)
        # Simuler race : _order_to_symbol pas populate
        trader._order_to_symbol = {}

        fill = _make_fill("MIA_P_test", 7200.50)
        trader._on_dtc_fill(fill)

        # Symbol resolu via fallback parent_id → entry update OK
        assert trader.active_positions["ES"]["entry"] == 7200.50
        assert trader.active_positions["ES"]["slip_entry_ticks"] == 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
