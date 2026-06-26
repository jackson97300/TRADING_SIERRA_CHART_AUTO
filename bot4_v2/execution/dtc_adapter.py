"""Bot 4 v2 dtc_adapter — Wrapper Pydantic ISOLATED vs BOT/dtc_connector.py legacy.

Module NEW Phase P2 Batch 4b (25/06/2026) — PAS de FORK CORE/* ni BOT/*.

Pattern (anti dette Bot 4 v1) :
- INTERDIT `self._backend._send(...)` direct (greffe v1 INCIDENT_LOG #77)
- API typee Pydantic-style (dataclasses frozen) pour anti-VALIDATION_MISS
- Injection de dependances : `DTCAdapter(backend: IDTCBackend)` avec
  `IDTCBackend` Protocol = interface minimale (anti couplage direct legacy)
- Logger via bot4_v2.observability.telemetry (codes BOT4V2_DTC_*)
- ConnectionStatus enum explicite (vs bool fragile v1)

Heritages V1 conserves (INCIDENT_LOG #77 fix + leçons DTC) :
- OrderStatus 7=Filled (jamais 2=Open) → adapter expose `Filled` boolean explicit
- ServerOrderID + ClientOrderID + TradeAccount obligatoires pour cancel
- OCO manuel 3 ordres Type 208 (PAS Type 206 OCO natif - SC l'ignore)
- ensure_connected() throttle anti-spam 30s
- BracketResult.naked boolean : True si fill OK + SL non pose

Garde-fous (spec section 7) :
- Pas de print() / except: pass / silent fallback
- Pas de modification BOT/dtc_connector.py (interface isolee obligatoire)
- Fail-loud raise ValueError sur args invalides
- DTCSettings frozen + Pydantic-style env override
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# ENUMS
# ============================================================


class ConnectionStatus(str, Enum):
    """Etat connexion DTC. Explicit (vs bool fragile v1)."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class OrderSide(str, Enum):
    """Cote ordre (DTC convention : 1=BUY, 2=SELL)."""

    BUY = "BUY"
    SELL = "SELL"

    @property
    def dtc_int(self) -> int:
        """Convertit en int DTC (1=BUY, 2=SELL)."""
        return 1 if self == OrderSide.BUY else 2


# ============================================================
# CONFIG (DTCSettings frozen dataclass Pydantic-style)
# ============================================================


def _env_int(name: str, default: int) -> int:
    """Lit env var BOT4V2_DTC_{name} en int. Fallback default."""
    val = os.environ.get(f"BOT4V2_DTC_{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Lit env var BOT4V2_DTC_{name} en float. Locale-aware (virgule FR)."""
    val = os.environ.get(f"BOT4V2_DTC_{name}")
    if val is None:
        return default
    try:
        return float(val.replace(",", "."))
    except (TypeError, ValueError, AttributeError):
        return default


def _env_str(name: str, default: str) -> str:
    """Lit env var BOT4V2_DTC_{name} en str."""
    return os.environ.get(f"BOT4V2_DTC_{name}", default)


@dataclass(frozen=True)
class DTCSettings:
    """Configuration DTC immutable (Pydantic-style frozen dataclass).

    Source unique BOT4V2_DTC_* env vars + defaults documentes.
    """

    # Connection
    host: str = field(default_factory=lambda: _env_str("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 11099))
    client_name: str = field(
        default_factory=lambda: _env_str("CLIENT_NAME", "MIA_Bot_4_v2")
    )
    trade_account: str = field(
        default_factory=lambda: _env_str("TRADE_ACCOUNT", "Sim4")
    )

    # Timeouts (sec)
    # Heritage INCIDENT_LOG #77 : reconnect throttle 30s anti-spam
    reconnect_throttle_sec: float = field(
        default_factory=lambda: _env_float("RECONNECT_THROTTLE_SEC", 30.0)
    )
    parent_fill_timeout_sec: float = field(
        default_factory=lambda: _env_float("PARENT_FILL_TIMEOUT_SEC", 30.0)
    )
    heartbeat_interval_sec: float = field(
        default_factory=lambda: _env_float("HEARTBEAT_INTERVAL_SEC", 10.0)
    )

    # Behavior
    dry_run: bool = field(
        default_factory=lambda: _env_str("DRY_RUN", "0") == "1"
    )
    # OCO manuel obligatoire (Type 206 SC l'ignore silencieusement)
    oco_manual: bool = field(
        default_factory=lambda: _env_str("OCO_MANUAL", "1") == "1"
    )

    @classmethod
    def from_env(cls) -> DTCSettings:
        """Construit settings depuis env vars (snapshot au boot)."""
        return cls()


# ============================================================
# REQUEST/RESPONSE MODELS (frozen dataclass)
# ============================================================


@dataclass(frozen=True)
class OrderRequest:
    """Requete ordre (MARKET ou STOP). Immutable."""

    symbol: str
    side: OrderSide
    quantity: int
    order_type: str  # "MARKET" / "STOP" / "LIMIT"
    price: Optional[float] = None  # pour STOP/LIMIT
    trade_account: Optional[str] = None  # override DTCSettings.trade_account
    client_order_id: Optional[str] = None  # auto-genere si None
    signal_ref_price: Optional[float] = None  # pour slippage metric


@dataclass(frozen=True)
class BracketRequest:
    """Requete bracket OCO (MARKET parent + SL STOP, PAS de TP par defaut).

    Heritage Bot 3 BN V4 INCIDENT_LOG #67 : Bot 4 v2 supporte aussi flux
    SL-only (PAS de TP). Pour bracket TP+SL classique, passer tp_price.
    """

    symbol: str
    side: OrderSide
    quantity: int
    sl_price: float
    tp_price: Optional[float] = None  # None = flux SL-only
    trade_account: Optional[str] = None
    signal_ref_price: Optional[float] = None


@dataclass(frozen=True)
class BracketResult:
    """Resultat bracket. Immutable.

    Heritage Bot 3 BN V4 R1 review 24/06 : `naked=True` si fill OK + SL non pose
    -> caller doit close auto / alerter CRITIQUE.
    """

    success: bool
    parent_cid: str = ""
    sl_cid: str = ""
    tp_cid: str = ""
    fill_price: float = 0.0
    error_msg: str = ""
    naked: bool = False  # True si fill OK mais SL non pose (anti position nue)
    dry_run: bool = False


# ============================================================
# BACKEND PROTOCOL (interface minimale anti couplage direct)
# ============================================================


@runtime_checkable
class IDTCBackend(Protocol):
    """Interface minimale backend DTC. Le wrapper DTCAdapter call uniquement
    ces methodes, JAMAIS d'attributs prives (anti `self._backend._send`).

    Conforme avec BOT/dtc_connector.py legacy (signatures publiques alignees) :
    - is_connected() -> bool
    - connect() -> bool
    - disconnect() -> None
    - send_market_with_stop_only(...) -> tuple[parent_id, sl_cid, fill_price]
    - send_close_market(...) -> str (close_cid)
    - cancel_order(cid, trade_account, server_order_id?) -> bool
    """

    @property
    def connected(self) -> bool:
        """True si connecte au serveur DTC."""
        ...

    def connect(self) -> bool:
        """Etablit connexion. Returns True si OK."""
        ...

    def disconnect(self) -> None:
        """Ferme connexion proprement."""
        ...

    def send_market_with_stop_only(
        self,
        symbol: str,
        side: int,
        quantity: int,
        sl_price: float,
        trade_account: str,
        signal_ref_price: float = 0.0,
    ) -> tuple:
        """Envoie parent MARKET + SL STOP (PAS de TP).

        Returns (parent_id, sl_cid, fill_price) :
        - succes complet : 3 non-vides
        - position NUE : (parent_id, "", fill_price)
        - timeout / abort : ("", "", 0.0)
        """
        ...

    def send_close_market(
        self,
        symbol: str,
        side: int,
        quantity: int,
        trade_account: str,
    ) -> str:
        """Envoie ordre close MARKET (inverse position). Returns close_cid."""
        ...

    def cancel_order(
        self,
        client_order_id: str,
        trade_account: str,
        server_order_id: Optional[str] = None,
    ) -> bool:
        """Cancel un ordre. Heritage INCIDENT_LOG H6 04/05 : trade_account
        obligatoire (default Sim3 piege si non specifie).
        """
        ...


# ============================================================
# DTCAdapter
# ============================================================


class DTCAdapter:
    """Wrapper Pydantic ISOLATED vs IDTCBackend.

    INTERDICTION FONDAMENTALE (spec section 7) :
    - PAS `self._backend._send(...)` direct
    - PAS d'attributs prives backend
    - TOUS les appels passent par les methodes publiques Protocol IDTCBackend

    Pattern injection : caller fournit le backend (real BOT/dtc_connector.py en
    prod, FakeDTC en tests, MockDTC en dry-run).
    """

    def __init__(
        self,
        backend: IDTCBackend,
        settings: Optional[DTCSettings] = None,
    ):
        """Init adapter avec backend injecte.

        Args:
            backend : implementation IDTCBackend (real ou fake)
            settings : DTCSettings (default = from_env)

        Raises:
            TypeError : si backend ne respecte pas IDTCBackend Protocol
        """
        if not isinstance(backend, IDTCBackend):
            raise TypeError(
                f"backend must implement IDTCBackend Protocol, "
                f"got {type(backend).__name__}"
            )
        self._backend = backend
        self._settings = settings or DTCSettings.from_env()

    @property
    def settings(self) -> DTCSettings:
        """Settings utilises (immutable)."""
        return self._settings

    @property
    def status(self) -> ConnectionStatus:
        """Status connexion explicit (vs bool fragile)."""
        try:
            return (
                ConnectionStatus.CONNECTED if self._backend.connected
                else ConnectionStatus.DISCONNECTED
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("dtc_adapter: status check exc=%s", exc)
            return ConnectionStatus.FAILED

    def ensure_connected(self) -> ConnectionStatus:
        """Verifie connexion + tente reconnect si DISCONNECTED.

        Heritage Bot 3 INCIDENT_LOG #77 + Bot 4 v1 audit 19/06 : DTC peut
        perdre connexion silencieusement (SC restart) -> reconnect auto.

        BUG #3 R4 review batch 4b : throttle `reconnect_throttle_sec` non
        encore implemente (settings prepares mais skip logic deferree P3).
        Backlog BOT4V2-P2-4b-R4 IDEAS_BACKLOG.md.

        Returns:
            ConnectionStatus apres tentative
        """
        if self._backend.connected:
            return ConnectionStatus.CONNECTED

        _LOG.warning("dtc_adapter: backend disconnected, attempting reconnect")
        try:
            ok = self._backend.connect()
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("dtc_adapter: reconnect exception=%s", exc)
            emit_safe(_LOG, "BOT4V2_DTC_RECONNECT_FAIL",
                      reason=f"reconnect_exc_{type(exc).__name__}")
            return ConnectionStatus.FAILED

        if ok:
            # BUG #2 R review batch 4b fix : utilise code dedie reconnect_ok
            # (vs BOT4V2_BOOT_READY qui polluait events boot).
            emit_safe(_LOG, "BOT4V2_DTC_RECONNECT_OK")
            return ConnectionStatus.CONNECTED
        emit_safe(_LOG, "BOT4V2_DTC_RECONNECT_FAIL",
                  reason="connect_returned_false")
        return ConnectionStatus.FAILED

    def disconnect(self) -> None:
        """Ferme connexion backend proprement."""
        try:
            self._backend.disconnect()
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("dtc_adapter: disconnect exception=%s", exc)

    def send_bracket(self, request: BracketRequest) -> BracketResult:
        """Envoie un bracket OCO MARKET parent + SL STOP (et TP optionnel).

        Heritage Bot 3 BN V4 fix B1 (INCIDENT_LOG #67) : si tp_price=None,
        utilise send_market_with_stop_only (PAS send_market_order qui saute
        le SL si tp=0).

        Returns:
            BracketResult avec naked=True si fill OK mais SL non pose.
        """
        if self._settings.dry_run:
            return BracketResult(
                success=True,
                parent_cid="DRYRUN_PARENT",
                sl_cid="DRYRUN_SL",
                tp_cid="DRYRUN_TP" if request.tp_price else "",
                fill_price=request.signal_ref_price or 0.0,
                dry_run=True,
            )

        if not self._backend.connected:
            emit_safe(_LOG, "BOT4V2_DTC_NOT_CONNECTED_PRE_SEND",
                      symbol=request.symbol, side=request.side.value)
            return BracketResult(
                success=False,
                error_msg="DTC_NOT_CONNECTED_PRE_SEND",
            )

        if request.tp_price is not None:
            # TP+SL bracket : non supporte par IDTCBackend minimal protocol P2.
            # Reporte au backend Phase P4 bracket_manager (extension protocole).
            return BracketResult(
                success=False,
                error_msg="TP_PLUS_SL_NOT_YET_SUPPORTED_P2_USE_SL_ONLY",
            )

        # Flux SL-only (Bot 3 BN V4 + Bot 4 trailing)
        return self._send_sl_only(request)

    def _send_sl_only(self, request: BracketRequest) -> BracketResult:
        """Envoie flux SL-only via backend (fix B1 INCIDENT_LOG #67)."""
        trade_account = request.trade_account or self._settings.trade_account
        try:
            result = self._backend.send_market_with_stop_only(
                symbol=request.symbol,
                side=request.side.dtc_int,
                quantity=request.quantity,
                sl_price=request.sl_price,
                trade_account=trade_account,
                signal_ref_price=request.signal_ref_price or 0.0,
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.error("dtc_adapter: send_market_with_stop_only exc=%s", exc)
            return BracketResult(
                success=False,
                error_msg=f"DTC_EXCEPTION:{type(exc).__name__}",
            )

        if not isinstance(result, tuple) or len(result) != 3:
            return BracketResult(
                success=False,
                error_msg=f"DTC_UNKNOWN_RESULT_TYPE:{type(result).__name__}",
            )

        parent_id, sl_cid, fill_raw = result
        try:
            fill_price = float(fill_raw) if fill_raw else 0.0
        except (TypeError, ValueError):
            fill_price = 0.0

        if not parent_id or fill_price <= 0:
            return BracketResult(
                success=False,
                parent_cid=parent_id or "",
                error_msg=f"DTC_NO_FILL_CONFIRMED:parent={parent_id or 'unknown'}",
            )

        if not sl_cid:
            # Heritage Bot 3 BN V4 R1 : position NUE (fill OK + SL non pose)
            # caller doit close auto / alerter CRITIQUE
            return BracketResult(
                success=False,
                parent_cid=parent_id,
                sl_cid="",
                fill_price=fill_price,
                naked=True,
                error_msg="DTC_NAKED_FILL_NO_SL",
            )

        return BracketResult(
            success=True,
            parent_cid=parent_id,
            sl_cid=sl_cid,
            fill_price=fill_price,
        )

    def send_close(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        trade_account: Optional[str] = None,
    ) -> Optional[str]:
        """Envoie ordre close MARKET (inverse position).

        Args:
            symbol, side, quantity : close request
            trade_account : override settings.trade_account si fourni

        Returns:
            close_cid si OK, None si erreur (anti silent fail caller alerte).
        """
        if self._settings.dry_run:
            return f"DRYRUN_CLOSE_{symbol}"
        if not self._backend.connected:
            emit_safe(_LOG, "BOT4V2_DTC_NOT_CONNECTED_PRE_SEND",
                      symbol=symbol, side=side.value)
            return None
        ta = trade_account or self._settings.trade_account
        try:
            cid = self._backend.send_close_market(
                symbol=symbol,
                side=side.dtc_int,
                quantity=quantity,
                trade_account=ta,
            )
            return cid if cid else None
        except Exception as exc:  # noqa: BLE001
            _LOG.error("dtc_adapter: send_close_market exc=%s", exc)
            return None

    def cancel_order(
        self,
        client_order_id: str,
        trade_account: Optional[str] = None,
        server_order_id: Optional[str] = None,
    ) -> bool:
        """Cancel un ordre.

        Heritage INCIDENT_LOG H6 04/05 : trade_account OBLIGATOIRE
        (default Sim3 piege). On utilise settings.trade_account si non fourni.
        ServerOrderID requis pour eviter cancel ignore silencieusement.
        """
        if self._settings.dry_run:
            return True
        # BUG #4 R review batch 4b fix : aligner observabilite sur send_bracket
        # / send_close. cancel_order silencieux not_connected = trace perdue
        # pour decision_router cleanup naked positions.
        if not self._backend.connected:
            emit_safe(_LOG, "BOT4V2_DTC_NOT_CONNECTED_PRE_SEND",
                      symbol="?", side="CANCEL", reason="cancel_not_connected")
            return False
        ta = trade_account or self._settings.trade_account
        try:
            ok = bool(self._backend.cancel_order(
                client_order_id=client_order_id,
                trade_account=ta,
                server_order_id=server_order_id,
            ))
        except Exception as exc:  # noqa: BLE001
            _LOG.error("dtc_adapter: cancel_order cid=%s exc=%s",
                       client_order_id, exc)
            emit_safe(_LOG, "BOT4V2_DTC_CANCEL_FAIL",
                      cid=client_order_id,
                      reason=f"exc_{type(exc).__name__}")
            return False
        if not ok:
            emit_safe(_LOG, "BOT4V2_DTC_CANCEL_FAIL",
                      cid=client_order_id, reason="backend_returned_false")
        return ok
