"""Tests bot4_v2/execution/dtc_backend_sierra - wrapper IDTCBackend."""
from __future__ import annotations

from typing import Optional

import pytest

from bot4_v2.execution.dtc_backend_sierra import SierraDTCBackend


# ============================================================
# Mock DTCConnector matchant _DTCConnectorLike Protocol
# ============================================================


class MockDTCConnector:
    """Mock minimal matchant _DTCConnectorLike Protocol pour tests unitaires."""

    def __init__(self, *, connected: bool = False,
                  connect_returns: bool = True,
                  send_market_result: tuple = ("P_CID", "SL_CID", 20000.0),
                  send_close_result: str = "C_CID",
                  cancel_result: bool = True,
                  raise_on: Optional[str] = None):
        self.connected = connected
        self._connect_returns = connect_returns
        self._send_market_result = send_market_result
        self._send_close_result = send_close_result
        self._cancel_result = cancel_result
        self._raise_on = raise_on
        self.calls: list[tuple] = []  # (method, args, kwargs)

    def _check_raise(self, method_name):
        if self._raise_on == method_name:
            raise RuntimeError(f"simulated {method_name} fail")

    def connect(self) -> bool:
        self.calls.append(("connect", (), {}))
        self._check_raise("connect")
        self.connected = self._connect_returns
        return self._connect_returns

    def disconnect(self) -> None:
        self.calls.append(("disconnect", (), {}))
        self._check_raise("disconnect")
        self.connected = False

    def send_market_with_stop_only(self, *, symbol, side, quantity, sl_price,
                                    trade_account, signal_ref_price=0.0):
        self.calls.append(("send_market_with_stop_only", (), {
            "symbol": symbol, "side": side, "quantity": quantity,
            "sl_price": sl_price, "trade_account": trade_account,
            "signal_ref_price": signal_ref_price,
        }))
        self._check_raise("send_market_with_stop_only")
        return self._send_market_result

    def send_close_market(self, *, symbol, side, quantity, trade_account):
        self.calls.append(("send_close_market", (), {
            "symbol": symbol, "side": side, "quantity": quantity,
            "trade_account": trade_account,
        }))
        self._check_raise("send_close_market")
        return self._send_close_result

    def cancel_order(self, *, order_id, trade_account):
        self.calls.append(("cancel_order", (), {
            "order_id": order_id, "trade_account": trade_account,
        }))
        self._check_raise("cancel_order")
        return self._cancel_result


# ============================================================
# Init validation
# ============================================================


def test_init_requires_dtc_connector():
    with pytest.raises(ValueError, match="dtc_connector required"):
        SierraDTCBackend(None)  # type: ignore


def test_init_rejects_non_protocol_object():
    """Object qui n'implemente pas Protocol -> TypeError."""

    class BadConnector:
        pass

    with pytest.raises(TypeError, match="_DTCConnectorLike"):
        SierraDTCBackend(BadConnector())  # type: ignore


def test_init_accepts_protocol_compliant():
    backend = SierraDTCBackend(MockDTCConnector())
    assert backend is not None


# ============================================================
# Connected property delegation
# ============================================================


def test_connected_false_when_dtc_not_connected():
    mock = MockDTCConnector(connected=False)
    backend = SierraDTCBackend(mock)
    assert backend.connected is False


def test_connected_true_when_dtc_connected():
    mock = MockDTCConnector(connected=True)
    backend = SierraDTCBackend(mock)
    assert backend.connected is True


# ============================================================
# connect() delegation + fail-soft
# ============================================================


def test_connect_delegates_and_returns_true():
    mock = MockDTCConnector(connect_returns=True)
    backend = SierraDTCBackend(mock)
    assert backend.connect() is True
    assert ("connect", (), {}) in mock.calls
    assert backend.connected is True


def test_connect_returns_false_on_dtc_returns_false():
    mock = MockDTCConnector(connect_returns=False)
    backend = SierraDTCBackend(mock)
    assert backend.connect() is False


def test_connect_returns_false_on_exception():
    """Exception caught -> False + log critique."""
    mock = MockDTCConnector(raise_on="connect")
    backend = SierraDTCBackend(mock)
    assert backend.connect() is False


# ============================================================
# disconnect() delegation
# ============================================================


def test_disconnect_delegates():
    mock = MockDTCConnector(connected=True)
    backend = SierraDTCBackend(mock)
    backend.disconnect()
    assert ("disconnect", (), {}) in mock.calls
    assert mock.connected is False


def test_disconnect_swallows_exception():
    mock = MockDTCConnector(raise_on="disconnect")
    backend = SierraDTCBackend(mock)
    # Pas de raise propagated
    backend.disconnect()


# ============================================================
# send_market_with_stop_only delegation + garde-fou H6
# ============================================================


def test_send_market_requires_trade_account():
    """Trade_account vide -> ValueError anti H6."""
    mock = MockDTCConnector()
    backend = SierraDTCBackend(mock)
    with pytest.raises(ValueError, match="H6"):
        backend.send_market_with_stop_only(
            symbol="NQ", side=2, quantity=1,
            sl_price=20010.0, trade_account="",
        )


def test_send_market_delegates_args():
    mock = MockDTCConnector(send_market_result=("P_123", "SL_456", 20000.5))
    backend = SierraDTCBackend(mock)
    result = backend.send_market_with_stop_only(
        symbol="NQ", side=2, quantity=1,
        sl_price=20010.0, trade_account="Sim4",
        signal_ref_price=19998.0,
    )
    assert result == ("P_123", "SL_456", 20000.5)
    # Verify args propagated
    args = mock.calls[-1][2]
    assert args["symbol"] == "NQ"
    assert args["side"] == 2
    assert args["trade_account"] == "Sim4"
    assert args["signal_ref_price"] == 19998.0


def test_send_market_returns_empty_tuple_on_exception():
    mock = MockDTCConnector(raise_on="send_market_with_stop_only")
    backend = SierraDTCBackend(mock)
    result = backend.send_market_with_stop_only(
        symbol="NQ", side=2, quantity=1,
        sl_price=20010.0, trade_account="Sim4",
    )
    assert result == ("", "", 0.0)


def test_send_market_returns_empty_on_bad_result_type():
    """Si DTCConnector retourne autre chose qu'un tuple 3 elements -> fail-soft."""
    mock = MockDTCConnector(send_market_result=("only_one",))  # type: ignore
    backend = SierraDTCBackend(mock)
    result = backend.send_market_with_stop_only(
        symbol="NQ", side=2, quantity=1,
        sl_price=20010.0, trade_account="Sim4",
    )
    assert result == ("", "", 0.0)


# ============================================================
# send_close_market delegation + garde-fou
# ============================================================


def test_send_close_requires_trade_account():
    mock = MockDTCConnector()
    backend = SierraDTCBackend(mock)
    with pytest.raises(ValueError, match="H6"):
        backend.send_close_market(
            symbol="NQ", side=1, quantity=1, trade_account="",
        )


def test_send_close_delegates_and_returns_cid():
    mock = MockDTCConnector(send_close_result="CLOSE_CID_999")
    backend = SierraDTCBackend(mock)
    cid = backend.send_close_market(
        symbol="NQ", side=1, quantity=1, trade_account="Sim4",
    )
    assert cid == "CLOSE_CID_999"


def test_send_close_returns_empty_on_exception():
    mock = MockDTCConnector(raise_on="send_close_market")
    backend = SierraDTCBackend(mock)
    cid = backend.send_close_market(
        symbol="NQ", side=1, quantity=1, trade_account="Sim4",
    )
    assert cid == ""


def test_send_close_returns_empty_on_non_string():
    """Si DTCConnector retourne non-string -> ''."""
    mock = MockDTCConnector(send_close_result=None)  # type: ignore
    backend = SierraDTCBackend(mock)
    cid = backend.send_close_market(
        symbol="NQ", side=1, quantity=1, trade_account="Sim4",
    )
    assert cid == ""


# ============================================================
# cancel_order delegation + garde-fou H6
# ============================================================


def test_cancel_order_requires_trade_account():
    """trade_account None -> ValueError H6."""
    mock = MockDTCConnector()
    backend = SierraDTCBackend(mock)
    with pytest.raises(ValueError, match="H6"):
        backend.cancel_order(client_order_id="X", trade_account=None)


def test_cancel_order_requires_trade_account_non_empty():
    mock = MockDTCConnector()
    backend = SierraDTCBackend(mock)
    with pytest.raises(ValueError, match="H6"):
        backend.cancel_order(client_order_id="X", trade_account="")


def test_cancel_order_delegates_with_trade_account():
    mock = MockDTCConnector(cancel_result=True)
    backend = SierraDTCBackend(mock)
    ok = backend.cancel_order(
        client_order_id="CID_123", trade_account="Sim4",
    )
    assert ok is True
    args = mock.calls[-1][2]
    assert args["order_id"] == "CID_123"
    assert args["trade_account"] == "Sim4"


def test_cancel_order_returns_false_on_dtc_false():
    mock = MockDTCConnector(cancel_result=False)
    backend = SierraDTCBackend(mock)
    ok = backend.cancel_order(client_order_id="X", trade_account="Sim4")
    assert ok is False


def test_cancel_order_returns_false_on_exception():
    mock = MockDTCConnector(raise_on="cancel_order")
    backend = SierraDTCBackend(mock)
    ok = backend.cancel_order(client_order_id="X", trade_account="Sim4")
    assert ok is False


# ============================================================
# IDTCBackend Protocol compliance
# ============================================================


def test_implements_idtc_backend_protocol():
    from bot4_v2.execution.dtc_adapter import IDTCBackend
    mock = MockDTCConnector()
    backend = SierraDTCBackend(mock)
    assert isinstance(backend, IDTCBackend)


# ============================================================
# Logs catalog codes registered
# ============================================================


def test_log_codes_sierra_registered():
    from CORE.log_catalog import LOG_CODES
    expected = {
        "BOT4V2_SIERRA_CONNECT_OK",
        "BOT4V2_SIERRA_CONNECT_FAIL",
        "BOT4V2_SIERRA_DISCONNECT_OK",
        "BOT4V2_SIERRA_DISCONNECT_FAIL",
        "BOT4V2_SIERRA_SEND_MARKET_EXC",
        "BOT4V2_SIERRA_SEND_MARKET_BAD_RESULT",
        "BOT4V2_SIERRA_SEND_CLOSE_EXC",
        "BOT4V2_SIERRA_CANCEL_EXC",
        "BOT4V2_SIERRA_CANCEL_FAIL",
    }
    missing = expected - set(LOG_CODES.keys())
    assert missing == set(), f"Missing codes: {missing}"
