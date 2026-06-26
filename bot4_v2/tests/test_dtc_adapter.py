"""Tests bot4_v2/execution/dtc_adapter."""
from __future__ import annotations

import os
from typing import Optional

import pytest

from bot4_v2.execution.dtc_adapter import (
    BracketRequest,
    BracketResult,
    ConnectionStatus,
    DTCAdapter,
    DTCSettings,
    IDTCBackend,
    OrderRequest,
    OrderSide,
)


# ============================================================
# FAKE BACKEND (test fixture)
# ============================================================


class FakeDTCBackend:
    """Fake DTC backend pour tests (implemente IDTCBackend Protocol)."""

    def __init__(
        self,
        connected: bool = True,
        market_result: tuple = ("MIA_P_abc", "MIA_SL_xyz", 20000.0),
        close_cid: str = "MIA_CLOSE_def",
        cancel_ok: bool = True,
        raise_on_send: bool = False,
        raise_on_connect: bool = False,
    ):
        self._connected = connected
        self._market_result = market_result
        self._close_cid = close_cid
        self._cancel_ok = cancel_ok
        self._raise_on_send = raise_on_send
        self._raise_on_connect = raise_on_connect
        # Tracking calls pour assertions
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.send_calls = []
        self.close_calls = []
        self.cancel_calls = []

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self.connect_calls += 1
        if self._raise_on_connect:
            raise RuntimeError("simulated connect failure")
        self._connected = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    def send_market_with_stop_only(
        self,
        symbol: str,
        side: int,
        quantity: int,
        sl_price: float,
        trade_account: str,
        signal_ref_price: float = 0.0,
    ) -> tuple:
        self.send_calls.append({
            "symbol": symbol, "side": side, "quantity": quantity,
            "sl_price": sl_price, "trade_account": trade_account,
            "signal_ref_price": signal_ref_price,
        })
        if self._raise_on_send:
            raise RuntimeError("simulated send failure")
        return self._market_result

    def send_close_market(
        self,
        symbol: str,
        side: int,
        quantity: int,
        trade_account: str,
    ) -> str:
        self.close_calls.append({
            "symbol": symbol, "side": side, "quantity": quantity,
            "trade_account": trade_account,
        })
        return self._close_cid

    def cancel_order(
        self,
        client_order_id: str,
        trade_account: str,
        server_order_id: Optional[str] = None,
    ) -> bool:
        self.cancel_calls.append({
            "client_order_id": client_order_id,
            "trade_account": trade_account,
            "server_order_id": server_order_id,
        })
        return self._cancel_ok


@pytest.fixture(autouse=True)
def _clear_env_bot4v2_dtc(monkeypatch):
    """Clear BOT4V2_DTC_* env vars avant chaque test."""
    for key in list(os.environ.keys()):
        if key.startswith("BOT4V2_DTC_"):
            monkeypatch.delenv(key, raising=False)
    yield


# ============================================================
# Enums
# ============================================================


def test_connection_status_values():
    assert ConnectionStatus.DISCONNECTED.value == "DISCONNECTED"
    assert ConnectionStatus.CONNECTED.value == "CONNECTED"


def test_order_side_dtc_int():
    """BUY=1, SELL=2 (DTC convention)."""
    assert OrderSide.BUY.dtc_int == 1
    assert OrderSide.SELL.dtc_int == 2


# ============================================================
# DTCSettings
# ============================================================


def test_dtc_settings_defaults():
    cfg = DTCSettings.from_env()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 11099
    assert cfg.client_name == "MIA_Bot_4_v2"
    assert cfg.trade_account == "Sim4"
    assert cfg.reconnect_throttle_sec == 30.0
    assert cfg.parent_fill_timeout_sec == 30.0
    assert cfg.dry_run is False
    assert cfg.oco_manual is True


def test_dtc_settings_env_override_int(monkeypatch):
    monkeypatch.setenv("BOT4V2_DTC_PORT", "12345")
    cfg = DTCSettings.from_env()
    assert cfg.port == 12345


def test_dtc_settings_env_override_float_locale_fr(monkeypatch):
    monkeypatch.setenv("BOT4V2_DTC_PARENT_FILL_TIMEOUT_SEC", "45,5")
    cfg = DTCSettings.from_env()
    assert cfg.parent_fill_timeout_sec == 45.5


def test_dtc_settings_env_override_str(monkeypatch):
    monkeypatch.setenv("BOT4V2_DTC_TRADE_ACCOUNT", "Sim6")
    cfg = DTCSettings.from_env()
    assert cfg.trade_account == "Sim6"


def test_dtc_settings_dry_run_enabled(monkeypatch):
    monkeypatch.setenv("BOT4V2_DTC_DRY_RUN", "1")
    cfg = DTCSettings.from_env()
    assert cfg.dry_run is True


def test_dtc_settings_invalid_int_fallback(monkeypatch):
    monkeypatch.setenv("BOT4V2_DTC_PORT", "not_a_port")
    cfg = DTCSettings.from_env()
    assert cfg.port == 11099  # default


def test_dtc_settings_frozen():
    from dataclasses import FrozenInstanceError
    cfg = DTCSettings.from_env()
    with pytest.raises(FrozenInstanceError):
        cfg.host = "evil_host"  # type: ignore


# ============================================================
# DTCAdapter init & Protocol enforcement
# ============================================================


def test_adapter_init_with_valid_backend():
    backend = FakeDTCBackend()
    adapter = DTCAdapter(backend=backend)
    assert adapter.settings.trade_account == "Sim4"


def test_adapter_init_rejects_non_protocol_backend():
    """Backend qui n'implemente pas IDTCBackend -> TypeError."""

    class BadBackend:
        """Pas de methodes IDTCBackend."""
        pass

    with pytest.raises(TypeError, match="IDTCBackend"):
        DTCAdapter(backend=BadBackend())  # type: ignore


def test_adapter_init_with_custom_settings():
    backend = FakeDTCBackend()
    settings = DTCSettings(trade_account="Sim99")
    adapter = DTCAdapter(backend=backend, settings=settings)
    assert adapter.settings.trade_account == "Sim99"


# ============================================================
# DTCAdapter status
# ============================================================


def test_adapter_status_connected():
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    assert adapter.status == ConnectionStatus.CONNECTED


def test_adapter_status_disconnected():
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend)
    assert adapter.status == ConnectionStatus.DISCONNECTED


# ============================================================
# DTCAdapter ensure_connected
# ============================================================


def test_ensure_connected_already_connected_noop():
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    result = adapter.ensure_connected()
    assert result == ConnectionStatus.CONNECTED
    assert backend.connect_calls == 0  # no reconnect needed


def test_ensure_connected_triggers_reconnect():
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend)
    result = adapter.ensure_connected()
    assert result == ConnectionStatus.CONNECTED
    assert backend.connect_calls == 1


def test_ensure_connected_exception_returns_failed():
    backend = FakeDTCBackend(connected=False, raise_on_connect=True)
    adapter = DTCAdapter(backend=backend)
    result = adapter.ensure_connected()
    assert result == ConnectionStatus.FAILED


# ============================================================
# DTCAdapter disconnect
# ============================================================


def test_disconnect_calls_backend():
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    adapter.disconnect()
    assert backend.disconnect_calls == 1


# ============================================================
# send_bracket (SL-only flow)
# ============================================================


def test_send_bracket_dry_run():
    settings = DTCSettings(dry_run=True)
    backend = FakeDTCBackend(connected=False)  # connected=False ignored in dry_run
    adapter = DTCAdapter(backend=backend, settings=settings)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
        signal_ref_price=20000.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is True
    assert result.dry_run is True
    assert result.parent_cid == "DRYRUN_PARENT"
    assert backend.send_calls == []  # backend pas appele


def test_send_bracket_not_connected_returns_error():
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is False
    assert result.error_msg == "DTC_NOT_CONNECTED_PRE_SEND"


def test_send_bracket_sl_only_success():
    backend = FakeDTCBackend(
        connected=True,
        market_result=("MIA_P_abc", "MIA_SL_xyz", 20005.0),
    )
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=2, sl_price=19990.0,
        signal_ref_price=20000.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is True
    assert result.parent_cid == "MIA_P_abc"
    assert result.sl_cid == "MIA_SL_xyz"
    assert result.fill_price == 20005.0
    assert result.naked is False
    # Check backend called correctly
    assert len(backend.send_calls) == 1
    call = backend.send_calls[0]
    assert call["symbol"] == "NQ"
    assert call["side"] == 1  # BUY = 1
    assert call["quantity"] == 2
    assert call["sl_price"] == 19990.0
    assert call["trade_account"] == "Sim4"  # default
    assert call["signal_ref_price"] == 20000.0


def test_send_bracket_naked_position_detected():
    """Fill OK mais SL non pose -> naked=True (anti position nue)."""
    backend = FakeDTCBackend(
        connected=True,
        market_result=("MIA_P_abc", "", 20005.0),  # sl_cid vide
    )
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is False
    assert result.naked is True
    assert result.fill_price == 20005.0
    assert result.parent_cid == "MIA_P_abc"
    assert result.error_msg == "DTC_NAKED_FILL_NO_SL"


def test_send_bracket_no_fill_confirmed():
    """Tuple ('', '', 0) -> DTC_NO_FILL_CONFIRMED."""
    backend = FakeDTCBackend(
        connected=True,
        market_result=("", "", 0.0),
    )
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is False
    assert "NO_FILL" in result.error_msg


def test_send_bracket_with_tp_returns_not_supported():
    """TP+SL bracket = non supporte par protocol P2 minimum."""
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1,
        sl_price=19990.0, tp_price=20020.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is False
    assert "TP_PLUS_SL_NOT_YET_SUPPORTED" in result.error_msg


def test_send_bracket_backend_exception():
    backend = FakeDTCBackend(connected=True, raise_on_send=True)
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is False
    assert "DTC_EXCEPTION" in result.error_msg


def test_send_bracket_invalid_backend_result_tuple():
    """Backend retourne mauvais tuple (2 elements au lieu de 3)."""
    backend = FakeDTCBackend(
        connected=True,
        market_result=("only_two", "elements"),  # type: ignore
    )
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is False
    assert "DTC_UNKNOWN_RESULT_TYPE" in result.error_msg


def test_send_bracket_short_side():
    backend = FakeDTCBackend(
        connected=True,
        market_result=("MIA_P_short", "MIA_SL_short", 19995.0),
    )
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.SELL, quantity=1, sl_price=20010.0,
    )
    result = adapter.send_bracket(request)
    assert result.success is True
    # Side SELL -> dtc_int 2
    assert backend.send_calls[0]["side"] == 2


def test_send_bracket_custom_trade_account():
    """Override settings.trade_account via BracketRequest."""
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    request = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1,
        sl_price=19990.0,
        trade_account="Sim_override",
    )
    adapter.send_bracket(request)
    assert backend.send_calls[0]["trade_account"] == "Sim_override"


# ============================================================
# send_close
# ============================================================


def test_send_close_success():
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    cid = adapter.send_close(
        symbol="NQ", side=OrderSide.SELL, quantity=1,
    )
    assert cid == "MIA_CLOSE_def"
    assert backend.close_calls[0]["side"] == 2


def test_send_close_dry_run():
    settings = DTCSettings(dry_run=True)
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend, settings=settings)
    cid = adapter.send_close(symbol="NQ", side=OrderSide.SELL, quantity=1)
    assert cid is not None
    assert "DRYRUN" in cid


def test_send_close_not_connected_returns_none():
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend)
    cid = adapter.send_close(symbol="NQ", side=OrderSide.SELL, quantity=1)
    assert cid is None


def test_send_close_empty_cid_returns_none():
    """Backend retourne "" -> close cid = None (anti silent success)."""
    backend = FakeDTCBackend(connected=True, close_cid="")
    adapter = DTCAdapter(backend=backend)
    cid = adapter.send_close(symbol="NQ", side=OrderSide.SELL, quantity=1)
    assert cid is None


def test_send_close_custom_trade_account():
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    adapter.send_close(
        symbol="NQ", side=OrderSide.SELL, quantity=1,
        trade_account="SimX",
    )
    assert backend.close_calls[0]["trade_account"] == "SimX"


# ============================================================
# cancel_order
# ============================================================


def test_cancel_order_success():
    backend = FakeDTCBackend(connected=True, cancel_ok=True)
    adapter = DTCAdapter(backend=backend)
    ok = adapter.cancel_order(
        client_order_id="MIA_SL_xyz",
        server_order_id="SERVER_123",
    )
    assert ok is True
    call = backend.cancel_calls[0]
    assert call["client_order_id"] == "MIA_SL_xyz"
    assert call["trade_account"] == "Sim4"  # default
    assert call["server_order_id"] == "SERVER_123"


def test_cancel_order_dry_run():
    settings = DTCSettings(dry_run=True)
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend, settings=settings)
    ok = adapter.cancel_order(client_order_id="any_cid")
    assert ok is True
    assert backend.cancel_calls == []


def test_cancel_order_not_connected_returns_false():
    backend = FakeDTCBackend(connected=False)
    adapter = DTCAdapter(backend=backend)
    ok = adapter.cancel_order(client_order_id="cid", server_order_id="sid")
    assert ok is False


def test_cancel_order_custom_trade_account():
    """Heritage INCIDENT_LOG H6 04/05 : trade_account obligatoire."""
    backend = FakeDTCBackend(connected=True)
    adapter = DTCAdapter(backend=backend)
    adapter.cancel_order(
        client_order_id="cid",
        trade_account="SimY",
    )
    assert backend.cancel_calls[0]["trade_account"] == "SimY"


def test_cancel_order_backend_returns_false():
    backend = FakeDTCBackend(connected=True, cancel_ok=False)
    adapter = DTCAdapter(backend=backend)
    ok = adapter.cancel_order(client_order_id="cid")
    assert ok is False


def test_cancel_order_backend_exception():
    class RaisingCancel:
        @property
        def connected(self):
            return True

        def connect(self):
            return True

        def disconnect(self):
            pass

        def send_market_with_stop_only(self, **kw):
            return ("", "", 0)

        def send_close_market(self, **kw):
            return ""

        def cancel_order(self, **kw):
            raise RuntimeError("simulated cancel exception")

    backend = RaisingCancel()
    adapter = DTCAdapter(backend=backend)  # type: ignore
    ok = adapter.cancel_order(client_order_id="cid")
    assert ok is False


# ============================================================
# OrderRequest / BracketRequest frozen
# ============================================================


def test_order_request_frozen():
    from dataclasses import FrozenInstanceError
    req = OrderRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, order_type="MARKET",
    )
    with pytest.raises(FrozenInstanceError):
        req.symbol = "ES"  # type: ignore


def test_bracket_request_frozen():
    from dataclasses import FrozenInstanceError
    req = BracketRequest(
        symbol="NQ", side=OrderSide.BUY, quantity=1, sl_price=19990.0,
    )
    with pytest.raises(FrozenInstanceError):
        req.sl_price = 0.0  # type: ignore


def test_bracket_result_frozen():
    from dataclasses import FrozenInstanceError
    r = BracketResult(success=True)
    with pytest.raises(FrozenInstanceError):
        r.success = False  # type: ignore


# ============================================================
# Garde-fou : pas d'acces aux attributs prives backend
# ============================================================


def test_adapter_does_not_call_private_send_on_backend():
    """Anti dette Bot 4 v1 : DTCAdapter ne doit JAMAIS appeler backend._send.

    Parse l'AST pour detecter `self._backend.<attr>` ou attr commence par _
    (acces attribut prive). Anti-self-match : on ignore docstring/comments.
    """
    import ast
    import inspect
    import bot4_v2.execution.dtc_adapter as adapter_module

    tree = ast.parse(inspect.getsource(adapter_module))
    violations = []
    for node in ast.walk(tree):
        # Cherche Attribute access chains : self._backend._something
        if not isinstance(node, ast.Attribute):
            continue
        if not node.attr.startswith("_"):
            continue
        # node.value doit etre une autre Attribute access (chain)
        inner = node.value
        if not isinstance(inner, ast.Attribute):
            continue
        if inner.attr != "_backend":
            continue
        # inner.value doit etre Name("self")
        deepest = inner.value
        if isinstance(deepest, ast.Name) and deepest.id == "self":
            violations.append(node.attr)

    assert not violations, (
        f"VIOLATION SPEC : self._backend.<private> detecte : {violations}"
    )


# ============================================================
# IDTCBackend Protocol runtime check
# ============================================================


def test_fake_backend_implements_protocol():
    """FakeDTCBackend doit implementer IDTCBackend (runtime_checkable)."""
    backend = FakeDTCBackend()
    assert isinstance(backend, IDTCBackend)


def test_bad_backend_does_not_implement_protocol():
    class IncompleteBackend:
        @property
        def connected(self):
            return True
        # missing other methods

    backend = IncompleteBackend()
    assert not isinstance(backend, IDTCBackend)
