"""test_bot3_risk_manager.py — Tests Bot3RiskManager cooldown + circuit breaker.

Couverture (08/05/2026 directive Jackson "ANALYSE COOLDOWN BOT 1+2 APPLIQUE BOT 3") :
  - can_trade OK initial state
  - cooldown 15 min post-close bloque
  - cooldown expire OK
  - circuit breaker 3 SL consec → 60 min bloque
  - reset consec_sl sur win
  - cross_sym independence (NQ cooldown ne bloque pas ES)
  - pnl_ticks=None (timeout) update last_close_time mais pas consec_sl
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.databento_paper_trader_v2 import Bot3RiskManager


class TestBot3RiskManagerBasic:
    def test_initial_state_can_trade(self):
        rm = Bot3RiskManager()
        allow, reason = rm.can_trade("NQ")
        assert allow is True
        assert reason == "OK"

    def test_constants_match_bot1_bot2(self):
        rm = Bot3RiskManager()
        # Aligne Bot 1 (mia_paper_trader.py:121-123) + Bot 2 (databento_paper_trader.py:134-141)
        assert rm.cooldown_min == 15
        assert rm.max_consec_sl == 3
        assert rm.pause_breaker_min == 60


class TestBot3RiskManagerCooldown:
    def test_cooldown_blocks_within_15min(self):
        rm = Bot3RiskManager()
        rm.on_trade_close("NQ", pnl_ticks=-50.0)
        # Immediat apres close → cooldown
        allow, reason = rm.can_trade("NQ")
        assert allow is False
        assert "COOLDOWN" in reason

    def test_cooldown_expires_after_15min(self):
        rm = Bot3RiskManager()
        # Force last_close_time a 16 min dans le passe
        rm.last_close_time["NQ"] = datetime.now(timezone.utc) - timedelta(minutes=16)
        allow, reason = rm.can_trade("NQ")
        assert allow is True

    def test_cooldown_independent_per_symbol(self):
        rm = Bot3RiskManager()
        rm.on_trade_close("NQ", pnl_ticks=-50.0)
        # NQ bloque mais ES OK
        allow_nq, _ = rm.can_trade("NQ")
        allow_es, reason_es = rm.can_trade("ES")
        assert allow_nq is False
        assert allow_es is True
        assert reason_es == "OK"


class TestBot3RiskManagerCircuitBreaker:
    def test_3_sl_consec_triggers_breaker(self):
        rm = Bot3RiskManager()
        # 1er SL : consec=1, no breaker
        r1 = rm.on_trade_close("NQ", pnl_ticks=-50.0)
        assert r1["consecutive_sl"] == 1
        assert r1["breaker_triggered"] is False
        # 2eme SL : consec=2, no breaker
        r2 = rm.on_trade_close("NQ", pnl_ticks=-30.0)
        assert r2["consecutive_sl"] == 2
        assert r2["breaker_triggered"] is False
        # 3eme SL : consec=3 → breaker triggered
        r3 = rm.on_trade_close("NQ", pnl_ticks=-100.0)
        assert r3["consecutive_sl"] == 3
        assert r3["breaker_triggered"] is True
        # can_trade bloque par CIRCUIT_BREAKER (et aussi COOLDOWN car post-close immediat)
        allow, reason = rm.can_trade("NQ")
        assert allow is False
        # COOLDOWN ou CIRCUIT_BREAKER (les 2 sont actifs, COOLDOWN check en 1er)
        assert "COOLDOWN" in reason or "CIRCUIT_BREAKER" in reason

    def test_breaker_blocks_after_cooldown_expires(self):
        rm = Bot3RiskManager()
        # Trigger breaker
        rm.on_trade_close("NQ", pnl_ticks=-50.0)
        rm.on_trade_close("NQ", pnl_ticks=-30.0)
        rm.on_trade_close("NQ", pnl_ticks=-100.0)
        # Force cooldown expire mais pas breaker (16 min < 60 min pause)
        rm.last_close_time["NQ"] = datetime.now(timezone.utc) - timedelta(minutes=16)
        allow, reason = rm.can_trade("NQ")
        assert allow is False
        assert "CIRCUIT_BREAKER" in reason

    def test_win_resets_consec_sl_and_breaker(self):
        rm = Bot3RiskManager()
        # 2 SL consec
        rm.on_trade_close("NQ", pnl_ticks=-50.0)
        rm.on_trade_close("NQ", pnl_ticks=-30.0)
        assert rm.consecutive_sl["NQ"] == 2
        # Win → reset
        r = rm.on_trade_close("NQ", pnl_ticks=+80.0)
        assert r["consecutive_sl"] == 0
        assert rm.consecutive_sl["NQ"] == 0
        assert rm.breaker_until.get("NQ") is None

    def test_breaker_independent_per_symbol(self):
        rm = Bot3RiskManager()
        # 3 SL NQ → breaker NQ
        rm.on_trade_close("NQ", pnl_ticks=-50.0)
        rm.on_trade_close("NQ", pnl_ticks=-30.0)
        rm.on_trade_close("NQ", pnl_ticks=-100.0)
        # ES toujours libre (pas de close)
        allow_es, reason_es = rm.can_trade("ES")
        assert allow_es is True


class TestBot3RiskManagerEdgeCases:
    def test_pnl_none_updates_cooldown_only(self):
        """TIMEOUT/RECOVERED : pnl=None → update cooldown mais PAS consec_sl."""
        rm = Bot3RiskManager()
        r = rm.on_trade_close("NQ", pnl_ticks=None)
        assert r["consecutive_sl"] == 0  # pas incremente
        assert r["pnl_ticks"] is None
        # Cooldown actif
        allow, reason = rm.can_trade("NQ")
        assert allow is False
        assert "COOLDOWN" in reason

    def test_pnl_zero_treated_as_breakeven_no_increment(self):
        """pnl_ticks = 0.0 → pas un SL → ne devrait pas incrementer consec_sl."""
        rm = Bot3RiskManager()
        r = rm.on_trade_close("NQ", pnl_ticks=0.0)
        # pnl=0 n'est pas < 0 → reset consec_sl
        assert r["consecutive_sl"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
