"""Bot 4 v2 dtc_backend_sierra — Wrapper IDTCBackend Protocol sur BOT/dtc_connector.

Module NEW Phase P5.4.A (26/06/2026) — Bridge bot4_v2 isolation et heritage
production-grade DTCConnector.

Heritage strict (`.claude/rules/orphan-prevention.md` + `bot.md`) :
- BOT/dtc_connector.DTCConnector = valide production Sim1+Sim2+Sim3 (30+ patches
  historiques : H6 TradeAccount par cid, ClientOrderID obligatoire, anti-orphan
  V2 sequence 9 etapes, OCO manuel Type 208, OrderStatus=7=Filled only)
- INTERDIT modifier BOT/dtc_connector.py (gele production)
- IDTCBackend Protocol P2 dtc_adapter -> signature exacte des methodes

Architecture (SRP minimal) :
    bot4_v2.execution.dtc_adapter.DTCAdapter  (pydantic isolated wrapper P2)
        |-> backend : IDTCBackend Protocol
        |       |-> SierraDTCBackend (CETTE CLASSE - delegation pure)
        |               |-> BOT.dtc_connector.DTCConnector (HERITAGE VALIDE)

EXCLU scope (backlog) :
- Auto-reconnect strategie custom (heritage DTCConnector deja gerent recv_loop)
- Persistance state cross-restart (cf project_4bots_persistance_chantier)
- Multi-broker abstraction (P7 live AMP cutover)

Garde-fous critiques :
- cancel_order REQUIRE trade_account (raise ValueError anti H6 hardcode Sim3)
- send_market_with_stop_only retourne tuple compatible IDTCBackend Protocol
- Tous logs via emit_safe (regle souveraine TRACABILITE)

ATTENTION : ce wrapper IMPORTE BOT/dtc_connector.py donc transitivement
BOT/bot_config.py qui charge .env et config DTC. Pour tests unitaires, injecter
un mock DTCConnector (cf test_dtc_backend_sierra.py).
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# DTC CONNECTOR PROTOCOL (anti import cycle + test injection)
# ============================================================


@runtime_checkable
class _DTCConnectorLike(Protocol):
    """Interface minimale attendue depuis BOT/dtc_connector.DTCConnector.

    Permet d'injecter un mock en test sans charger BOT/bot_config.py.
    """

    connected: bool

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def send_market_with_stop_only(
        self, symbol: str, side: int, quantity: int,
        sl_price: float, trade_account: str,
        signal_ref_price: float = 0.0,
    ) -> tuple: ...
    def send_close_market(
        self, symbol: str, side: int, quantity: int,
        trade_account: str,
    ) -> str: ...
    def cancel_order(
        self, order_id: str, trade_account: str,
    ) -> bool: ...


# ============================================================
# SIERRA DTC BACKEND (delegation pure)
# ============================================================


class SierraDTCBackend:
    """IDTCBackend Protocol implementation pour Sierra Chart via DTCConnector.

    Pattern : pure delegation sur `BOT.dtc_connector.DTCConnector` heritage.

    Usage paper Sim4 :
        from BOT.dtc_connector import DTCConnector
        from bot_config import DTCConfig
        dtc_conn = DTCConnector(DTCConfig(...))
        backend = SierraDTCBackend(dtc_conn)
        # Inject dans DTCAdapter(backend=backend, settings=DTCSettings(dry_run=False))

    Garde-fous :
    - cancel_order REQUIRE trade_account explicit (anti H6 hardcode Sim3)
    - send_market_with_stop_only delegation directe (heritage flux MARKET+SL fix #67)
    - connected/connect/disconnect delegation directe
    - Logs traceability via emit_safe (codes BOT4V2_SIERRA_*)
    """

    def __init__(self, dtc_connector: _DTCConnectorLike):
        """Init backend wrapper.

        Args:
            dtc_connector : instance BOT/dtc_connector.DTCConnector deja construite
                            ET connectee OU prete a connect(). Doit matcher
                            _DTCConnectorLike Protocol.

        Raises:
            ValueError : si dtc_connector None ou ne matche pas Protocol.
        """
        if dtc_connector is None:
            raise ValueError(
                "dtc_connector required - inject BOT.dtc_connector.DTCConnector"
            )
        # Verification Protocol runtime (defense en profondeur)
        if not isinstance(dtc_connector, _DTCConnectorLike):
            raise TypeError(
                f"dtc_connector must implement _DTCConnectorLike Protocol "
                f"(got {type(dtc_connector).__name__})"
            )
        self._dtc = dtc_connector

    @property
    def connected(self) -> bool:
        """Etat connexion DTC (delegate proxy)."""
        return bool(self._dtc.connected)

    def connect(self) -> bool:
        """Connect DTC server. Returns True si OK."""
        try:
            ok = bool(self._dtc.connect())
        except Exception as exc:  # noqa: BLE001
            emit_safe(
                _LOG, "BOT4V2_SIERRA_CONNECT_FAIL",
                exc_type=type(exc).__name__,
            )
            return False
        if ok:
            emit_safe(_LOG, "BOT4V2_SIERRA_CONNECT_OK")
        else:
            emit_safe(_LOG, "BOT4V2_SIERRA_CONNECT_FAIL", exc_type="returned_false")
        return ok

    def disconnect(self) -> None:
        """Disconnect DTC server proprement."""
        try:
            self._dtc.disconnect()
        except Exception as exc:  # noqa: BLE001
            emit_safe(
                _LOG, "BOT4V2_SIERRA_DISCONNECT_FAIL",
                exc_type=type(exc).__name__,
            )
            return
        emit_safe(_LOG, "BOT4V2_SIERRA_DISCONNECT_OK")

    def send_market_with_stop_only(
        self,
        symbol: str,
        side: int,
        quantity: int,
        sl_price: float,
        trade_account: str,
        signal_ref_price: float = 0.0,
    ) -> tuple:
        """Envoie MARKET parent + SL STOP (fix B1 INCIDENT_LOG #67).

        Delegation pure sur BOT/dtc_connector.send_market_with_stop_only.

        Args:
            symbol : futures contract (mappe via _to_contract dans connector)
            side : 1=BUY (long) / 2=SELL (short)
            quantity : nb contrats
            sl_price : prix SL initial (absolu)
            trade_account : OBLIGATOIRE compte cible (Sim4 pour bot4_v2)
            signal_ref_price : prix reference informatif

        Returns:
            (parent_id, sl_cid, fill_price) tuple :
            - succes complet : 3 non-vides
            - fill OK + SL fail (NAKED) : (parent_id, "", fill_price)
            - pas de fill : ("", "", 0.0)
        """
        if not trade_account:
            raise ValueError(
                "trade_account REQUIRED (anti H6 hardcode Sim3 piege - "
                "orphan-prevention.md)"
            )
        try:
            result = self._dtc.send_market_with_stop_only(
                symbol=symbol,
                side=side,
                quantity=quantity,
                sl_price=sl_price,
                trade_account=trade_account,
                signal_ref_price=signal_ref_price,
            )
        except Exception as exc:  # noqa: BLE001
            emit_safe(
                _LOG, "BOT4V2_SIERRA_SEND_MARKET_EXC",
                sym=symbol, exc_type=type(exc).__name__,
            )
            return ("", "", 0.0)
        # Validation defensive (defense en profondeur)
        if not isinstance(result, tuple) or len(result) != 3:
            emit_safe(
                _LOG, "BOT4V2_SIERRA_SEND_MARKET_BAD_RESULT",
                sym=symbol, result_type=type(result).__name__,
            )
            return ("", "", 0.0)
        return result

    def send_close_market(
        self,
        symbol: str,
        side: int,
        quantity: int,
        trade_account: str,
    ) -> str:
        """Envoie MARKET CLOSE (inverse position).

        Delegation pure. Returns close_cid string (vide si echec).
        """
        if not trade_account:
            raise ValueError(
                "trade_account REQUIRED (anti H6 hardcode)"
            )
        try:
            cid = self._dtc.send_close_market(
                symbol=symbol, side=side, quantity=quantity,
                trade_account=trade_account,
            )
        except Exception as exc:  # noqa: BLE001
            emit_safe(
                _LOG, "BOT4V2_SIERRA_SEND_CLOSE_EXC",
                sym=symbol, exc_type=type(exc).__name__,
            )
            return ""
        return cid if isinstance(cid, str) else ""

    def cancel_order(
        self,
        client_order_id: str,
        server_order_id: str = "",
        trade_account: Optional[str] = None,
    ) -> bool:
        """Cancel ordre via Type 203.

        Garde-fou H6 : trade_account REQUIRED. JAMAIS de default Sim3.

        Args:
            client_order_id : ClientOrderID a cancel
            server_order_id : ServerOrderID (heritage DTCConnector le requiert
                              via _order_server_ids dict interne, ignore ici)
            trade_account : OBLIGATOIRE compte cible

        Returns:
            True si cancel OK, False sinon.

        Raises:
            ValueError : si trade_account vide/None (anti H6).
        """
        if not trade_account:
            raise ValueError(
                "trade_account REQUIRED (anti H6 hardcode Sim3 piege - "
                "cf orphan-prevention.md cause racine 04/05/2026)"
            )
        try:
            ok = bool(self._dtc.cancel_order(
                order_id=client_order_id,
                trade_account=trade_account,
            ))
        except Exception as exc:  # noqa: BLE001
            emit_safe(
                _LOG, "BOT4V2_SIERRA_CANCEL_EXC",
                cid=client_order_id, exc_type=type(exc).__name__,
            )
            return False
        if not ok:
            emit_safe(
                _LOG, "BOT4V2_SIERRA_CANCEL_FAIL",
                cid=client_order_id, trade_account=trade_account,
            )
        return ok
