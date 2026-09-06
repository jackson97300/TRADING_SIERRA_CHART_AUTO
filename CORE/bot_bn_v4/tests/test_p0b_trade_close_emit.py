"""Tests P0.B 28/06 — BOTBN_TRADE_CLOSE + BOTBN_SL_SENT emit verification.

Audit weekend 28/06 a constate :
- execution_*_botbn.jsonl semaine 22-26/06 = 4 BOTBN_ORDER_SENT MAIS 0 TRADE_CLOSE
- Logs close emitent sous namespace bot1_v2 (BOT1V2_DTC_FILL_*) car listener
  partage. Bot 2/3 BN V4 audit impossible (PnL/WR sans trace).

Fix : emit BOTBN_TRADE_CLOSE dans _on_fill_close + BOTBN_SL_SENT post send_entry.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))


def test_botbn_trade_close_emit_signature():
    """_on_fill_close accepte 3 args (sym, pnl_usd, exit_reason) + default UNKNOWN."""
    import CORE.bot_bn_v4.main as m
    import inspect
    sig = inspect.signature(m.BotBNV4._on_fill_close)
    params = list(sig.parameters.keys())
    assert "exit_reason" in params, f"exit_reason absent: {params}"
    assert sig.parameters["exit_reason"].default == "UNKNOWN"


def test_botbn_trade_close_emit_via_bot_log():
    """Simule un callback _on_fill_close + verifie que bot_log.emit est appele."""
    emitted = []
    fake_bot_log = MagicMock()
    fake_bot_log.emit = lambda code, **ctx: emitted.append((code, ctx))

    # Mock daily_gate.apply_pnl pour eviter dependances
    fake_self = MagicMock()
    fake_self.daily_gate = MagicMock()
    fake_self.daily_gate.apply_pnl = MagicMock(return_value=None)
    fake_self._save_daily_state = MagicMock(return_value=None)
    fake_self.log = MagicMock()

    with patch("CORE.bot_bn_v4.main.bot_log", fake_bot_log):
        import CORE.bot_bn_v4.main as m
        # Appel direct comme une bound method
        m.BotBNV4._on_fill_close(fake_self, "NQ", -125.50, "SL")

    # Assertions emit
    codes = [c for c, _ in emitted]
    assert "BOTBN_TRADE_CLOSE" in codes, f"emit codes: {codes}"

    # Verifier les kwargs
    close_ctx = [ctx for c, ctx in emitted if c == "BOTBN_TRADE_CLOSE"][0]
    assert close_ctx["sym"] == "NQ"
    assert close_ctx["pnl_usd"] == -125.50
    assert close_ctx["exit_reason"] == "SL"


def test_botbn_trade_close_emit_avant_apply_pnl():
    """L'emit doit etre fait AVANT apply_pnl (perte log si exception PnL)."""
    call_order = []
    fake_bot_log = MagicMock()
    fake_bot_log.emit = lambda code, **ctx: call_order.append(f"emit:{code}")

    fake_self = MagicMock()
    fake_self.daily_gate = MagicMock()
    def fake_apply_pnl(*args, **kwargs):
        call_order.append("apply_pnl")
    fake_self.daily_gate.apply_pnl = fake_apply_pnl
    fake_self._save_daily_state = lambda: call_order.append("save_state")
    fake_self.log = MagicMock()

    with patch("CORE.bot_bn_v4.main.bot_log", fake_bot_log):
        import CORE.bot_bn_v4.main as m
        m.BotBNV4._on_fill_close(fake_self, "ES", 50.0, "TP")

    # emit doit etre premier
    emit_idx = next(i for i, x in enumerate(call_order) if x.startswith("emit:"))
    apply_idx = next(i for i, x in enumerate(call_order) if x == "apply_pnl")
    assert emit_idx < apply_idx, f"emit pas avant apply: {call_order}"


def test_botbn_trade_close_robuste_exception_emit():
    """Si bot_log.emit raise, apply_pnl est quand meme appele."""
    fake_bot_log = MagicMock()
    fake_bot_log.emit = MagicMock(side_effect=RuntimeError("log down"))

    fake_self = MagicMock()
    fake_self.daily_gate = MagicMock()
    fake_self.daily_gate.apply_pnl = MagicMock(return_value=None)
    fake_self._save_daily_state = MagicMock(return_value=None)
    fake_self.log = MagicMock()

    with patch("CORE.bot_bn_v4.main.bot_log", fake_bot_log):
        import CORE.bot_bn_v4.main as m
        # Ne doit PAS raise
        m.BotBNV4._on_fill_close(fake_self, "NQ", 100.0, "TIMEOUT")

    # apply_pnl appele malgre emit fail
    fake_self.daily_gate.apply_pnl.assert_called_once_with(100.0)


def test_botbn_sl_sent_code_dans_main_py():
    """Verifie que main.py emet BOTBN_SL_SENT apres BOTBN_ORDER_SENT."""
    src = (ROOT / "CORE/bot_bn_v4/main.py").read_text(encoding="utf-8")
    assert '"BOTBN_SL_SENT"' in src, "BOTBN_SL_SENT absent main.py"
    # Verifier que c'est apres ORDER_SENT (ordre source)
    idx_sent = src.index('"BOTBN_ORDER_SENT"')
    idx_sl = src.index('"BOTBN_SL_SENT"')
    assert idx_sl > idx_sent, "BOTBN_SL_SENT doit etre apres BOTBN_ORDER_SENT"


def test_log_catalog_codes_enregistres():
    """Les 3 nouveaux codes P0 sont dans LOG_CODES."""
    from CORE.log_catalog import LOG_CODES, LogLevel
    for code in ("BOTBN_TRADE_CLOSE", "BOTBN_SL_SENT",
                  "SIERRA_ATR_REGIME_BOOT_WARMUP"):
        assert code in LOG_CODES, f"{code} absent du catalog"
        lvl, cat, _ = LOG_CODES[code]
        assert lvl == LogLevel.MAJEUR, f"{code} doit etre MAJEUR (audit-critical)"

    # BOTBN_TRADE_CLOSE doit etre dans execution
    lvl, cat, _ = LOG_CODES["BOTBN_TRADE_CLOSE"]
    assert cat == "execution"
