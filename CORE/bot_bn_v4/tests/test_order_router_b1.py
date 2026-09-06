"""Tests B1 (INCIDENT_LOG #67/#68) : order_router consomme le flow dedie
send_market_with_stop_only (MARKET + SL, PAS de TP). Garantit qu'une position
n'est jamais ouverte sans SL pose sans etre flaggee naked.
"""
from __future__ import annotations

from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.execution.order_router import OrderRouter


class _FakeDTC:
    """Mock minimal du connector : retourne le tuple (parent, sl, fill) voulu."""

    def __init__(self, result):
        self._result = result
        self.calls = []
        self.close_calls = []

    def send_market_with_stop_only(self, **kwargs):
        self.calls.append(kwargs)
        return self._result

    def send_close_market(self, **kwargs):
        self.close_calls.append(kwargs)
        return "MIA_CLOSE_fake"

    def get_last_fill_price(self, parent_id):
        return 0.0


def _router(dtc):
    return OrderRouter(cfg=BotBNV4Config(), dry_run=False, dtc_connector=dtc)


def test_fill_and_sl_ok():
    dtc = _FakeDTC(("MIA_P_abc", "MIA_TRAIL_SL_xyz", 21000.0))
    r = _router(dtc).send_entry("NQ", "long", 21000.0, 20990.0, 1)
    assert r.success is True
    assert r.parent_cid == "MIA_P_abc"
    assert r.sl_cid == "MIA_TRAIL_SL_xyz"
    assert r.fill_price == 21000.0
    assert r.naked is False


def test_naked_triggers_flatten_and_not_tracked():
    # Fill OK mais SL non pose -> R1 : flatten MARKET inverse + success=False
    # (la position n'est PAS trackee comme active).
    dtc = _FakeDTC(("MIA_P_abc", "", 21000.0))
    r = _router(dtc).send_entry("NQ", "long", 21000.0, 20990.0, 1)
    assert r.success is False
    assert r.naked is True
    assert r.sl_cid == ""
    assert r.error_msg == "DTC_NAKED_FLATTENED"
    # flatten appele avec side oppose (long=BUY 1 -> close SELL 2)
    assert len(dtc.close_calls) == 1
    assert dtc.close_calls[0]["side"] == 2
    assert dtc.close_calls[0]["trade_account"] == "Sim3"


def test_no_fill_abort():
    # Pas de fill -> aucune position, success=False (anti fantome).
    dtc = _FakeDTC(("", "", 0.0))
    r = _router(dtc).send_entry("NQ", "long", 21000.0, 20990.0, 1)
    assert r.success is False
    assert r.naked is False
    assert "NO_FILL" in r.error_msg


def test_uses_stop_only_method_not_legacy():
    # Garde-fou anti-regression B1 : on appelle bien le flow SL-only,
    # JAMAIS l'ancien send_market_order(tp_price=0) qui sautait le SL.
    dtc = _FakeDTC(("MIA_P_abc", "MIA_SL_x", 21000.0))
    _router(dtc).send_entry("NQ", "long", 21000.0, 20990.0, 1)
    assert len(dtc.calls) == 1
    call = dtc.calls[0]
    assert "sl_price" in call
    assert "tp_price" not in call  # pas de TP dans le flow SL-only
    assert call["trade_account"] == "Sim3"


def test_dry_run_still_simulates_fill():
    # Le mode dry-run reste inchange (fill simule au prix d'entree).
    r = OrderRouter(cfg=BotBNV4Config(), dry_run=True).send_entry(
        "NQ", "long", 21000.0, 20990.0, 1,
    )
    assert r.success is True
    assert r.dry_run is True
    assert r.fill_price == 21000.0
    assert r.sl_cid  # un sl_cid synthetique est genere


class _DisconnectedDTC:
    """Mock DTC connecte=False (cas SC restart silencieux 23/06 23:16)."""

    connected = False

    def send_market_with_stop_only(self, **kwargs):
        raise AssertionError(
            "send_fn doit NE PAS etre appele si .connected=False (pre-check P0b)"
        )

    def cancel_order(self, *args, **kwargs):
        raise AssertionError(
            "cancel_fn doit NE PAS etre appele si .connected=False (pre-check P0b)"
        )

    def send_stop_order(self, **kwargs):
        raise AssertionError("send_stop_order ne doit pas etre appele")


def test_dtc_not_connected_pre_send_fail_loud():
    """FIX P0b 24/06 (R1+R5 code-reviewer) : pre-check connected detecte SC
    restart silencieux + emit code log dedie via err_msg. Incident 23/06 NQ A++
    perdu : pas d'emit visible, juste DTC_NO_FILL_CONFIRMED generique. Avec ce
    fix, err_msg explicite + caller emit BOTBN_DTC_NOT_CONNECTED_PRE_SEND.
    """
    dtc = _DisconnectedDTC()
    r = _router(dtc).send_entry("NQ", "long", 21000.0, 20990.0, 1)
    assert r.success is False
    assert r.error_msg == "DTC_NOT_CONNECTED_PRE_SEND"
    assert r.naked is False  # pas de fill, donc pas naked


def test_replace_sl_dtc_disconnected_returns_empty_no_orphan():
    """FIX P0b 24/06 R1 BLOQUANT code-reviewer : replace_sl protege identique
    a send_entry. Trailing en cours quand DTC perd la connexion -> cancel sur
    socket dead aurait leve exception -> "" -> position nue cote broker. Le
    pre-check retourne "" proprement -> caller emit BOTBN_TRAILING_SL_REPLACE_FAIL.
    """
    dtc = _DisconnectedDTC()
    router = _router(dtc)
    new_cid = router.replace_sl(
        symbol="NQ",
        sl_cid="MIA_TRAIL_SL_old",
        new_sl_price=20990.0,
        direction="long",
        n_micros=1,
    )
    assert new_cid == ""  # caller doit emit alerte trailing fail
