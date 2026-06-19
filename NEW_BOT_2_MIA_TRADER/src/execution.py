"""M5 Execution Bot 4 — wrapper Pydantic autour BOT/dtc_connector.py legacy.

Strategie : Option C (verdict audit market-analyst 27/05) — GO-AVEC-REWRITE.

- **GARDE** : 1212 LOC legacy proven 6 mois (H6 TA par CID, slip+reprice,
  anti-orphelin V2 9 etapes, OCO manuel, drain disconnect, race fixes)
- **REECRIT** : surface Pydantic ExecutionEvent + DTCSettings + BracketResult
- **ADAPTE** : `on_order_update` callback brut → adapter Pydantic
- **ELIMINE** : `tuple` returns, `dataclass OrderFill`, magic numbers, hardcode TA

Architecture :
    M3 SLTP   : calcule sl_price + tp1_price (statique au signal)
    M4 Risk   : ALLOW/BLOCK + sizing decision
    M5 EXECUTION (this) : place bracket DTC + adapter Pydantic
    M3.5 Monitor : trailing TR40 + MFE-TP (poll polling state.sl/tp)

Convention Bot 4 (memory project_bot4_naming_convention_20260527) :
- ClientName="MIA_Bot_4", TradeAccount="Sim4", CID prefix="MIA4_"
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .contract import AntiOrphanStep
from .execution_config import DTCSettings, ExecutionConfig


# =============================================================================
# Lazy import du legacy BOT/dtc_connector.py
# =============================================================================

# Permet tests sans BOT/ installe (mock DTCConnector)
_LEGACY_AVAILABLE = False
_DTCConnector = None

try:
    # Path resolve : BOT/ est au meme niveau que NEW_BOT_2_MIA_TRADER/
    _PROJECT_ROOT = Path(__file__).parent.parent.parent
    if str(_PROJECT_ROOT / "BOT") not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT / "BOT"))
    from dtc_connector import (  # type: ignore
        DTCConnector as _DTCConnectorImpl,
        BUY, SELL, MARKET, LIMIT, STOP,
    )
    _DTCConnector = _DTCConnectorImpl
    _LEGACY_AVAILABLE = True
except ImportError:
    BUY, SELL, MARKET, LIMIT, STOP = 1, 2, 1, 2, 3


# =============================================================================
# Pydantic Result models
# =============================================================================


class BracketResult(BaseModel):
    """Resultat send_bracket() Pydantic (remplace tuple legacy)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool
    parent_id: str = Field(default="")
    tp_cid: str = Field(default="")
    sl_cid: str = Field(default="")
    fill_price: Optional[float] = Field(default=None, description="LastFillPrice parent reel")
    slip_ticks: Optional[float] = Field(default=None, description="abs(fill - signal_ref)/tick")
    reprice_done: bool = Field(default=False, description="Si slip > seuil → SL/TP recalcule")
    reject_reason: Optional[str] = None


class FlattenResult(BaseModel):
    """Resultat sequence anti-orphelin 9 etapes.

    Fix P1-1 review J9 : `steps` matche contract.AntiOrphanStep typed
    (step_id Literal strict + success + duration_ms + error).
    Fix P1-2 review J9 : `critical_steps_failed` separe (4,5,9) des cleanup tolerables (1,2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence_completed: bool
    final_qty_broker: int = Field(default=0)
    orphan_detected_post_cleanup: bool = Field(default=False)
    steps: List[AntiOrphanStep] = Field(
        default_factory=list,
        description="9 etapes typees Pydantic contract.AntiOrphanStep",
    )
    critical_steps_failed: List[str] = Field(
        default_factory=list,
        description="Etapes 4/5/9 failed (vrai orphan risque)",
    )
    cleanup_steps_failed: List[str] = Field(
        default_factory=list,
        description="Etapes 1/2/6.5/7/8 failed (cancel TP/SL deja remplis = OK)",
    )
    duration_total_ms: float = Field(default=0.0, ge=0)
    error: Optional[str] = None


# =============================================================================
# Adapter ORDER_UPDATE legacy dict → Pydantic event
# =============================================================================


@dataclass
class OrderUpdateRaw:
    """Snapshot Type 301 ORDER_UPDATE brut (callback on_order_update legacy)."""

    client_order_id: str
    server_order_id: str
    symbol: str
    order_status: int  # 2=Open, 4=Working, 7=Filled, 8=Cancelled
    filled_qty: int
    expected_qty: int
    fill_price: float
    trade_account: str
    raw_msg: Dict[str, Any]

    @property
    def is_filled(self) -> bool:
        return (
            self.order_status == 7
            or (self.filled_qty > 0 and self.filled_qty >= self.expected_qty
                and self.order_status not in (2,))
        )

    @property
    def is_partial(self) -> bool:
        return (
            self.filled_qty > 0
            and self.expected_qty > 0
            and self.filled_qty < self.expected_qty
            and not self.is_filled
        )

    @property
    def is_cancelled(self) -> bool:
        return self.order_status in (8, "Cancelled")

    @classmethod
    def from_msg(cls, msg: Dict[str, Any]) -> "OrderUpdateRaw":
        return cls(
            client_order_id=msg.get("ClientOrderID", ""),
            server_order_id=msg.get("ServerOrderID", ""),
            symbol=str(msg.get("Symbol", "")),
            order_status=int(msg.get("OrderStatus", 0) or 0),
            filled_qty=int(msg.get("FilledQuantity") or 0),
            expected_qty=int(msg.get("OrderQuantity") or 0),
            fill_price=float(
                msg.get("AverageFillPrice")
                or msg.get("LastFillPrice")
                or msg.get("Price1")
                or 0
            ),
            trade_account=msg.get("TradeAccount", ""),
            raw_msg=msg,
        )


# =============================================================================
# DTCExecutor — wrapper Pydantic
# =============================================================================


class DTCExecutor:
    """Wrapper Pydantic autour BOT/dtc_connector.py legacy.

    Usage :
        config = ExecutionConfig.sim4_default()
        executor = DTCExecutor(config=config, telemetry=tel)
        if executor.connect():
            result = executor.send_bracket(
                symbol="NQM26-CME",
                side="BUY",
                quantity=3,
                sl_price=21441.75,
                tp_price=21465.00,
                signal_ref_price=21450.00,
                sl_ticks=33,
                tp_ticks=60,
                tick_size=0.25,
            )
            if result.success:
                # ... attendre fill via callbacks
                pass
            else:
                logger.error(f"Bracket failed: {result.reject_reason}")

    Callbacks Pydantic :
        executor.on_order_update_callback = my_handler  # recoit OrderUpdateRaw
        executor.on_filled_callback = my_filled         # recoit OrderUpdateRaw is_filled=True
        executor.on_cancelled_callback = my_cancelled
    """

    def __init__(
        self,
        config: Optional[ExecutionConfig] = None,
        telemetry: Any = None,  # Telemetry singleton (eviter cycle import)
    ):
        self.config = config or ExecutionConfig.sim4_default()
        self.telemetry = telemetry  # injectee, peut etre None

        # Legacy DTCConnector instance (initialise dans connect())
        self._legacy: Any = None

        # Callbacks Pydantic-style
        self.on_order_update_callback: Optional[Callable[[OrderUpdateRaw], None]] = None
        self.on_filled_callback: Optional[Callable[[OrderUpdateRaw], None]] = None
        self.on_cancelled_callback: Optional[Callable[[OrderUpdateRaw], None]] = None

        # State propre Bot 4 (separer du legacy)
        self._connected = False
        self._lock = threading.Lock()

        # Fix 03/06 (audit broadcast pollution) : Bot 4 reçoit via DTC tous les
        # ORDER_UPDATE broadcast par Sierra Chart (incl. Bot 1 v3, Bot 3 v4 sur
        # autres Sim accounts). Le handler legacy hardcode prefix MIA_*, donc
        # impossible de distinguer Bot 4 d'autres bots par prefix CID.
        # Solution : maintenir set des CIDs émis par CE Bot 4 et filtrer.
        # 38 BOT4_EXEC_FILL_* loggés le 03/06 alors que Bot 4 n'avait rien tradé.
        self._my_cids: set[str] = set()

        # Fix 19/06 (INCIDENT #77 DTC reconnect) : 87 BRACKET_FAIL 18/06 +
        # 10 le 19/06 toutes "not_connected" car is_connected() = getter pur,
        # aucun reconnect tente. Solution : ensure_connected() avec anti-spam
        # 30s minimum entre tentatives (eviter flood reconnect en boucle).
        self._last_reconnect_attempt_ts: float = 0.0
        self._reconnect_attempts_count: int = 0

    # -------------------------------------------------------------------------
    # API publique
    # -------------------------------------------------------------------------

    def connect(self) -> bool:
        """Connecte DTC via legacy. Init callbacks adapter."""
        if self.config.dry_run:
            self._connected = True
            return True

        if not _LEGACY_AVAILABLE:
            raise RuntimeError(
                "BOT/dtc_connector.py legacy non disponible. "
                "Verifier que NEW_BOT_2_MIA_TRADER/ est au meme niveau que BOT/"
            )

        # Adapter DTCSettings Pydantic → legacy DTCConfig (compat dataclass)
        legacy_cfg = self._make_legacy_config()
        self._legacy = _DTCConnector(legacy_cfg)

        # Brancher le callback brut sur l'adapter Pydantic
        self._legacy.on_order_update = self._adapter_on_order_update

        if not self._legacy.connect():
            return False

        self._connected = True
        return True

    def disconnect(self) -> None:
        """Disconnect avec drain (legacy P1.2)."""
        if self._legacy and not self.config.dry_run:
            self._legacy.disconnect(drain_timeout=self.config.dtc.drain_timeout_sec)
        self._connected = False

    def is_connected(self) -> bool:
        if self.config.dry_run:
            return self._connected
        return self._legacy is not None and getattr(self._legacy, "connected", False)

    def ensure_connected(self, min_retry_interval_sec: float = 30.0) -> bool:
        """Verifie DTC connecte. Si non, tente reconnect avec anti-spam.

        Fix INCIDENT #77 (19/06/2026) : `is_connected()` est un getter pur.
        Quand DTC tombe (network blip, broker side, Sierra Chart restart),
        send_bracket() retourne immediatement `reject_reason="not_connected"`
        sans jamais tenter de se reconnecter. Resultat : 87 BRACKET_FAIL 18/06
        + 10 le 19/06 = Bot 4 hors-ligne ~48h, 0 trade.

        Strategy :
        - Si deja connecte : OK return True.
        - Si pas connecte : tenter `self.connect()` une fois.
        - Anti-spam : ne pas tenter si moins de `min_retry_interval_sec`
          depuis la derniere tentative (default 30s).
        - Log telemetry BOT4_DTC_RECONNECT_{ATTEMPT,OK,FAIL,SKIP_THROTTLE}.

        Fix Q3 code-reviewer (19/06) : throttle wrapped dans self._lock pour
        eviter race condition entre thread main + callbacks DTC.
        Fix R-NEW-1 code-reviewer : disconnect() avant reconnect pour eviter
        leak threads _recv_loop zombies (legacy _DTCConnector re-instancie).

        Args:
            min_retry_interval_sec : delai minimum entre 2 tentatives reconnect.

        Returns:
            True si connecte (ou re-connecte), False sinon.
        """
        if self.is_connected():
            return True

        # Fix Q3 : wrap throttle + state mutations dans lock pour eviter
        # race condition main thread vs callback DTC.
        with self._lock:
            now = time.time()
            elapsed = now - self._last_reconnect_attempt_ts
            if elapsed < min_retry_interval_sec:
                # Anti-spam : skip cette tentative
                self._emit_telemetry(
                    "BOT4_DTC_RECONNECT_SKIP_THROTTLE",
                    {"elapsed_sec": round(elapsed, 1),
                     "min_interval_sec": min_retry_interval_sec,
                     "attempts_so_far": self._reconnect_attempts_count},
                )
                return False

            self._last_reconnect_attempt_ts = now
            self._reconnect_attempts_count += 1
            attempt_n = self._reconnect_attempts_count

        self._emit_telemetry(
            "BOT4_DTC_RECONNECT_ATTEMPT",
            {"attempt_n": attempt_n},
        )
        # Fix R-NEW-1 : disconnect() pour cleanup legacy _recv_loop avant
        # re-instanciation, sinon thread daemon zombie accumule a chaque
        # reconnect. Safe meme si _legacy=None ou deja disconnect.
        try:
            if self._legacy is not None:
                try:
                    self.disconnect()
                except Exception:  # noqa: BLE001
                    # disconnect lui-meme peut echouer si legacy en mauvais
                    # etat : on continue avec reconnect (re-instancie clean).
                    pass
            ok = self.connect()
            if ok:
                self._emit_telemetry(
                    "BOT4_DTC_RECONNECT_OK",
                    {"attempt_n": attempt_n},
                )
                return True
            else:
                self._emit_telemetry(
                    "BOT4_DTC_RECONNECT_FAIL",
                    {"attempt_n": attempt_n,
                     "reason": "connect_returned_false"},
                )
                return False
        except Exception as e:  # noqa: BLE001
            self._emit_telemetry(
                "BOT4_DTC_RECONNECT_FAIL",
                {"attempt_n": attempt_n,
                 "reason": f"{type(e).__name__}: {str(e)[:100]}"},
            )
            return False

    def _emit_telemetry(self, code: str, ctx: dict) -> None:
        """Helper telemetry safe (no-op si telemetry absente).

        Fix Q1 code-reviewer (19/06) : Telemetry.emit(event: BaseEvent) attend
        un Pydantic event, PAS code+ctx. Solution conforme pattern Bot 4
        existant (main.py utilise emit_safe(self._log, code, **ctx)) :
        utiliser emit_safe directement via lazy import du logger Bot 4.

        Si bot4_logger indisponible (tests minimaux) ou logger non initialise :
        no-op silencieux (preserve l'usage Telemetry-based pour mock tests).
        """
        # Voie 1 : Telemetry singleton avec API emit/log_event (pour mock tests)
        if self.telemetry is not None:
            try:
                emit = getattr(self.telemetry, "emit", None)
                if callable(emit):
                    try:
                        emit(code, **ctx)
                        return
                    except TypeError:
                        # Telemetry attend Pydantic event, pas code+ctx :
                        # tomber sur voie 2 logger emit_safe.
                        pass
                log = getattr(self.telemetry, "log_event", None)
                if callable(log):
                    log(code, ctx)
                    return
            except Exception:  # noqa: BLE001
                pass

        # Voie 2 : emit_safe via logger Bot 4 (pattern main.py)
        try:
            from .bot4_logger import emit_safe, get_bot4_logger
            logger = get_bot4_logger("execution")
            emit_safe(logger, code, **ctx)
        except Exception:  # noqa: BLE001
            pass  # silent fail safe (production-resilient)

    # -------------------------------------------------------------------------
    # send_bracket : wrapper Pydantic
    # -------------------------------------------------------------------------

    def send_bracket(
        self,
        *,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: int,
        sl_price: float,
        tp_price: float,
        tick_size: float,  # Fix P1-4 review : OBLIGATOIRE (viole tick-size-policy.md si default)
        signal_ref_price: float = 0,
        sl_ticks: int = 0,
        tp_ticks: int = 0,
        trade_account: Optional[str] = None,
    ) -> BracketResult:
        """Envoie un bracket (parent MARKET + TP LIMIT + SL STOP) via legacy.

        Returns BracketResult Pydantic frozen (au lieu de tuple).

        Fix INCIDENT #77 (19/06) : ensure_connected() tente reconnect DTC si
        disconnecte (anti-spam 30s). Avant ce fix, is_connected() etait un
        getter pur -> 87 BRACKET_FAIL 18/06 + 10 le 19/06 toutes
        reject_reason="not_connected", Bot 4 hors-ligne ~48h sans tenter
        de se reconnecter.
        """
        if not self.ensure_connected():
            return BracketResult(success=False, reject_reason="not_connected")

        if self.config.dry_run:
            # Simulation : retourne CID fictifs
            return BracketResult(
                success=True,
                parent_id=f"{self.config.dtc.client_order_id_prefix}P_{uuid.uuid4().hex[:8]}",
                tp_cid=f"{self.config.dtc.client_order_id_prefix}TP_{uuid.uuid4().hex[:8]}",
                sl_cid=f"{self.config.dtc.client_order_id_prefix}SL_{uuid.uuid4().hex[:8]}",
                fill_price=signal_ref_price,
                slip_ticks=0.0,
                reprice_done=False,
            )

        # Mapper side str → int legacy
        legacy_side = BUY if side == "BUY" else SELL
        ta = trade_account or self.config.dtc.trade_account

        # Appel legacy
        parent_id, tp_cid, sl_cid = self._legacy.send_market_order(
            symbol=symbol,
            side=legacy_side,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
            trade_account=ta,
            signal_ref_price=signal_ref_price,
            sl_ticks=sl_ticks,
            tp_ticks=tp_ticks,
            tick_size=tick_size,
            auto_reprice_threshold_ticks=self.config.dtc.auto_reprice_threshold_ticks,
        )

        if not parent_id or not tp_cid or not sl_cid:
            return BracketResult(
                success=False,
                reject_reason="parent_fill_timeout_or_send_failure",
            )

        # Fix 03/06 (audit broadcast pollution) : enregistre les CIDs Bot 4 emis
        # pour filtrer les ORDER_UPDATE broadcast SC d'autres bots dans handler.
        with self._lock:
            self._my_cids.add(parent_id)
            self._my_cids.add(tp_cid)
            self._my_cids.add(sl_cid)

        # Recuperer fill_price reel + slip (12/05 fix get_last_fill_price)
        fill_price = None
        slip_ticks = None
        if hasattr(self._legacy, "get_last_fill_price"):
            fill_price = self._legacy.get_last_fill_price(parent_id)
            if fill_price and signal_ref_price > 0 and tick_size > 0:
                slip_ticks = abs(fill_price - signal_ref_price) / tick_size

        return BracketResult(
            success=True,
            parent_id=parent_id,
            tp_cid=tp_cid,
            sl_cid=sl_cid,
            fill_price=fill_price,
            slip_ticks=slip_ticks,
            reprice_done=(slip_ticks or 0) > self.config.dtc.auto_reprice_threshold_ticks,
        )

    # -------------------------------------------------------------------------
    # register_recovered_cids : re-injection apres restart Bot 4
    # -------------------------------------------------------------------------

    def register_recovered_cids(
        self,
        parent_cid: str,
        tp_cid: Optional[str],
        sl_cid: Optional[str],
    ) -> None:
        """Re-injecte les CIDs d'une position recoveree apres restart Bot 4.

        Fix 05/06 (incident SL fantome 04/06 23:13 UTC) : sans cette methode,
        _my_cids reste vide au boot apres restart (init RAM ligne 229), et tous
        les fills DTC du propre Bot 4 sont rejetes avec BOT4_FILL_UNKNOWN_CID
        par le filtre broadcast pollution 03/06 (lignes 405-413).

        Consequence cascade :
        - on_filled_callback jamais declenche -> trade pas suivi
        - current_price/mae/mfe/bars_held restent a leur valeur init
        - tracking aveugle : si SL ou TP touche, bot ne le voit pas
        - 207 BOT4_FILL_UNKNOWN_CID sur 7 jours (audit 05/06)

        A appeler depuis main.py apres _reload_open_positions_from_disk().
        """
        with self._lock:
            self._my_cids.add(parent_cid)
            if tp_cid:
                self._my_cids.add(tp_cid)
            if sl_cid:
                self._my_cids.add(sl_cid)

    # -------------------------------------------------------------------------
    # cancel_order : wrapper Pydantic
    # -------------------------------------------------------------------------

    def cancel_order(
        self,
        client_order_id: str,
        trade_account: Optional[str] = None,
    ) -> bool:
        """Cancel ordre via legacy. require_sid=True par defaut (NEW clean room)."""
        if self.config.dry_run:
            return True

        ta = trade_account or self.config.dtc.trade_account
        return self._legacy.cancel_order(
            order_id=client_order_id,
            trade_account=ta,
            require_sid=self.config.dtc.cancel_require_sid,
        )

    # -------------------------------------------------------------------------
    # Callback adapter : legacy dict → Pydantic
    # -------------------------------------------------------------------------

    def _adapter_on_order_update(self, msg: Dict[str, Any]) -> None:
        """Convertit msg dict legacy → OrderUpdateRaw Pydantic + dispatche callbacks.

        J11 instrumentation : emit codes log fills (parent/TP/SL) + invalides ghost.
        """
        try:
            raw = OrderUpdateRaw.from_msg(msg)
        except Exception as e:
            # Defensive : un msg malforme ne doit pas casser le _recv_loop legacy
            print(f"[EXECUTION] OrderUpdateRaw parse error: {e}", file=sys.stderr)
            return

        # J11 : emit code log fill detect via prefix CID
        # Fix 03/06 (audit broadcast pollution) : Sierra Chart broadcast TOUS les
        # ORDER_UPDATE a tous les clients DTC. Bot 4 recevait ainsi les fills de
        # Bot 1 v3 (Sim1), Bot 3 v4 (Sim3) — 38 BOT4_EXEC_FILL_* parasites le 03/06.
        # Solution : filtrer par self._my_cids (CIDs effectivement emis par Bot 4).
        try:
            from .bot4_logger import emit_safe, get_bot4_logger
            _log = get_bot4_logger("execution")
            if raw.is_filled:
                cid = raw.client_order_id

                # FILTRE BROADCAST : si CID pas dans _my_cids = fill d'un autre bot
                with self._lock:
                    is_my_cid = cid in self._my_cids
                if not is_my_cid:
                    emit_safe(_log, "BOT4_FILL_UNKNOWN_CID",
                              cid=cid, fill_price=raw.fill_price,
                              is_tp=cid.startswith("MIA_TP_"),
                              is_sl=cid.startswith("MIA_SL_"))
                    return  # Skip emit + dispatch (pas notre fill)

                if raw.fill_price <= 0 or raw.order_status != 7:
                    emit_safe(_log, "BOT4_EXEC_FILL_INVALID",
                              sym=raw.symbol, cid=cid,
                              order_status=raw.order_status,
                              fill_price=raw.fill_price,
                              filled_qty=raw.filled_qty)
                elif cid.startswith("MIA_P_"):
                    emit_safe(_log, "BOT4_EXEC_FILL_PARENT",
                              sym=raw.symbol, cid=cid,
                              fill_price=raw.fill_price,
                              signal_ref_price=0.0,  # legacy ne sait pas
                              slip_ticks=0.0)
                elif cid.startswith("MIA_TP_"):
                    emit_safe(_log, "BOT4_EXEC_FILL_TP",
                              sym=raw.symbol, cid=cid,
                              fill_price=raw.fill_price,
                              pnl_ticks=0.0)
                elif cid.startswith("MIA_SL_"):
                    emit_safe(_log, "BOT4_EXEC_FILL_SL",
                              sym=raw.symbol, cid=cid,
                              fill_price=raw.fill_price,
                              pnl_ticks=0.0)
        except Exception:
            pass  # log emit ne doit jamais casser le recv_loop

        # Dispatch
        if self.on_order_update_callback is not None:
            try:
                self.on_order_update_callback(raw)
            except Exception as e:
                print(f"[EXECUTION] on_order_update_callback error: {e}", file=sys.stderr)

        if raw.is_filled and self.on_filled_callback is not None:
            try:
                self.on_filled_callback(raw)
            except Exception as e:
                print(f"[EXECUTION] on_filled_callback error: {e}", file=sys.stderr)

        if raw.is_cancelled and self.on_cancelled_callback is not None:
            try:
                self.on_cancelled_callback(raw)
            except Exception as e:
                print(f"[EXECUTION] on_cancelled_callback error: {e}", file=sys.stderr)

    # -------------------------------------------------------------------------
    # Legacy config adapter
    # -------------------------------------------------------------------------

    def _make_legacy_config(self) -> Any:
        """Convertit DTCSettings Pydantic → bot_config.DTCConfig legacy dataclass."""
        try:
            from bot_config import DTCConfig  # type: ignore
        except ImportError:
            # Fallback : creer config minimal compatible
            @dataclass
            class DTCConfig:
                host: str
                port: int
                timeout_seconds: float
                heartbeat_interval_seconds: int
                reconnect_delay_seconds: float

        # Fix P0-3 review J9 : propager client_name (eviter Bot 4 logon MIA_Bot_V2)
        try:
            return DTCConfig(
                host=self.config.dtc.host,
                port=self.config.dtc.port,
                timeout_seconds=int(self.config.dtc.timeout_seconds),
                heartbeat_interval_seconds=self.config.dtc.heartbeat_interval_seconds,
                reconnect_delay_seconds=int(self.config.dtc.reconnect_delay_seconds),
                client_name=self.config.dtc.client_name,  # CRITIQUE Bot 4
            )
        except TypeError:
            # DTCConfig legacy pre-fix P0-3 (sans client_name) - fallback compat
            cfg = DTCConfig(
                host=self.config.dtc.host,
                port=self.config.dtc.port,
                timeout_seconds=int(self.config.dtc.timeout_seconds),
                heartbeat_interval_seconds=self.config.dtc.heartbeat_interval_seconds,
                reconnect_delay_seconds=int(self.config.dtc.reconnect_delay_seconds),
            )
            # Setattr post-creation (dataclass mutable)
            try:
                cfg.client_name = self.config.dtc.client_name
            except Exception:
                pass
            return cfg

    # -------------------------------------------------------------------------
    # OCO + flatten (sequence anti-orphelin) - delegues au legacy
    # -------------------------------------------------------------------------

    def register_oco_pair(self, tp_cid: str, sl_cid: str) -> None:
        """Enregistre paire OCO pour cancel automatique au fill."""
        if not self.config.dry_run and hasattr(self._legacy, "register_oco_pair"):
            self._legacy.register_oco_pair(tp_cid, sl_cid)

    def get_current_price(self, symbol: str) -> float:
        """Prix courant via market data legacy."""
        if self.config.dry_run:
            return 0.0
        return self._legacy.get_current_price(symbol) if self._legacy else 0.0

    def get_last_fill_price(self, parent_id: str) -> Optional[float]:
        """Fix race 12/05 : fill_price persistant."""
        if self.config.dry_run:
            return None
        if hasattr(self._legacy, "get_last_fill_price"):
            return self._legacy.get_last_fill_price(parent_id)
        return None

    # -------------------------------------------------------------------------
    # request_position_blocking — wrapper Pydantic (anti race condition)
    # -------------------------------------------------------------------------

    def get_position_qty(
        self,
        symbol_contract: str,
        timeout_sec: Optional[float] = None,
        trade_account: Optional[str] = None,
    ) -> Optional[int]:
        """Query Type 305 position broker bloquant. Returns qty signe ou None si timeout.

        qty > 0 = LONG, qty < 0 = SHORT, qty == 0 = flat.
        Utilise dans sequence anti-orphelin etape 4 (verify avant MARKET CLOSE).

        Fix P0-1 review J9 : legacy expose `timeout=` (PAS `timeout_sec=`).
        Fix P0-2 review J9 : `trade_account=` OBLIGATOIRE explicite (sinon legacy default
        Sim3 piege = VIOLE fix H6 orphan-prevention.md).
        Fix P0-4 review J9 : legacy retourne int signe directement (PAS dict).
        """
        if self.config.dry_run:
            return 0  # paper assume flat
        if not self._legacy or not hasattr(self._legacy, "request_position_blocking"):
            return None
        timeout = timeout_sec or self.config.request_position_timeout_sec
        ta = trade_account or self.config.dtc.trade_account  # fix P0-2 : pas default Sim3
        try:
            # Fix P0-1 : signature legacy = timeout (pas timeout_sec)
            # Fix P0-2 : trade_account explicite (anti H6 piege)
            result = self._legacy.request_position_blocking(
                symbol_contract,
                trade_account=ta,
                timeout=timeout,
            )
            # Fix P0-4 : legacy retourne signed int (qty) ou None, PAS dict
            if isinstance(result, (int, float)):
                return int(result)
            return None
        except Exception as e:
            print(f"[EXECUTION] get_position_qty error: {e}", file=sys.stderr)
            return None

    def get_open_orders(
        self,
        symbol_filter: Optional[str] = None,
        trade_account: Optional[str] = None,
        timeout_sec: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """Query Type 300 OPEN_ORDERS bloquant. Returns liste working orders.

        Utilise etape 6.5 (cancel-all-working) + etape 9 (verify post-cleanup).

        Fix P0-1 review J9 : verifier signature legacy reelle (timeout= probable).
        """
        if self.config.dry_run:
            return []
        if not self._legacy or not hasattr(self._legacy, "request_open_orders_blocking"):
            return []
        ta = trade_account or self.config.dtc.trade_account
        try:
            # Inspecter signature legacy : trade_account + symbol_filter + timeout
            return self._legacy.request_open_orders_blocking(
                trade_account=ta,
                symbol_filter=symbol_filter,
                timeout=timeout_sec,
            ) or []
        except Exception as e:
            print(f"[EXECUTION] get_open_orders error: {e}", file=sys.stderr)
            return []

    # -------------------------------------------------------------------------
    # flatten_position_safely : sequence anti-orphelin 9 etapes
    # -------------------------------------------------------------------------

    def flatten_position_safely(
        self,
        *,
        symbol_contract: str,
        direction: Literal["LONG", "SHORT"],
        tp_cid: Optional[str],
        sl_cid: Optional[str],
        n_contracts: int,
        trade_account: Optional[str] = None,
    ) -> FlattenResult:
        """Sequence anti-orphelin 9 etapes (orphan-prevention.md V2).

        Etapes (chronologiques) :
            1. Cancel TP (cid + TA explicite)
            2. Cancel SL
            3. Wait 1s propagation cancels
            4. Verify qty broker (get_position_qty)
            5. MARKET CLOSE Type 208 OpenCloseTrade=2 si qty residuel
            6. Wait 2s pour fill MARKET CLOSE
            6.5. CANCEL-ALL-WORKING (Type 300 + cancel chaque)
            7. Type 209 SUBMIT_FLATTEN_POSITION_ORDER (symbol)
            8. Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (bouclier)
            9. VERIFY POST-CLEANUP (re-query Type 300, emit orphan si > 0)

        Args:
            symbol_contract: ex "NQM26-CME"
            direction: LONG ou SHORT (pour MARKET CLOSE side inverse)
            tp_cid: ClientOrderID TP (None si recovery)
            sl_cid: ClientOrderID SL
            n_contracts: quantite a flatten
            trade_account: Sim4 default Bot 4

        Returns FlattenResult avec :
            - sequence_completed : True si 9 etapes OK
            - final_qty_broker : qty restante (0 = clean)
            - orphan_detected_post_cleanup : True si etape 9 detecte working orders
            - steps_executed / steps_failed : liste pour audit
        """
        t0 = time.perf_counter()
        ta = trade_account or self.config.dtc.trade_account
        steps: List[AntiOrphanStep] = []
        critical_failed: List[str] = []
        cleanup_failed: List[str] = []

        if self.config.dry_run:
            return FlattenResult(
                sequence_completed=True,
                final_qty_broker=0,
                duration_total_ms=0.0,
                steps=[],
            )

        # Fix P1-3 review J9 : lock pour eviter race condition flatten vs callbacks.
        # CALLBACKS NE doivent PAS appeler flatten_position_safely (deadlock).
        with self._lock:
            return self._flatten_locked(
                symbol_contract=symbol_contract,
                direction=direction,
                tp_cid=tp_cid,
                sl_cid=sl_cid,
                n_contracts=n_contracts,
                ta=ta,
                t0=t0,
                steps=steps,
                critical_failed=critical_failed,
                cleanup_failed=cleanup_failed,
            )

    def _flatten_locked(
        self,
        *,
        symbol_contract: str,
        direction: str,
        tp_cid: Optional[str],
        sl_cid: Optional[str],
        n_contracts: int,
        ta: str,
        t0: float,
        steps: List[AntiOrphanStep],
        critical_failed: List[str],
        cleanup_failed: List[str],
    ) -> FlattenResult:
        """Body de flatten_position_safely sous lock. Construit Pydantic AntiOrphanStep."""

        def _add_step(step_id: str, executed: bool, success: bool,
                      duration_ms: Optional[float] = None,
                      error: Optional[str] = None,
                      is_critical: bool = False) -> None:
            steps.append(AntiOrphanStep(
                step_id=step_id,
                executed=executed,
                success=success,
                duration_ms=duration_ms,
                error=error,
            ))
            if not success and executed:
                if is_critical:
                    critical_failed.append(step_id)
                else:
                    cleanup_failed.append(step_id)

        # === Etape 1 : Cancel TP (cleanup - tolerable si OCO deja fill) ===
        ts1 = time.perf_counter()
        if tp_cid:
            try:
                ok = self.cancel_order(tp_cid, trade_account=ta)
                _add_step("1_cancel_tp", True, ok,
                          duration_ms=(time.perf_counter() - ts1) * 1000)
            except Exception as e:
                _add_step("1_cancel_tp", True, False, error=str(e)[:200])
        else:
            _add_step("1_cancel_tp", False, True, error="no_cid_skip")

        # === Etape 2 : Cancel SL (cleanup) ===
        ts2 = time.perf_counter()
        if sl_cid:
            try:
                ok = self.cancel_order(sl_cid, trade_account=ta)
                _add_step("2_cancel_sl", True, ok,
                          duration_ms=(time.perf_counter() - ts2) * 1000)
            except Exception as e:
                _add_step("2_cancel_sl", True, False, error=str(e)[:200])
        else:
            _add_step("2_cancel_sl", False, True, error="no_cid_skip")

        # === Etape 3 : Wait propagation ===
        time.sleep(self.config.flatten_wait_1_after_cancels_sec)
        _add_step("3_wait_1s_propagation", True, True,
                  duration_ms=self.config.flatten_wait_1_after_cancels_sec * 1000)

        # === Etape 4 : Verify qty broker (CRITIQUE) ===
        ts4 = time.perf_counter()
        qty_broker = self.get_position_qty(
            symbol_contract,
            timeout_sec=self.config.request_position_timeout_sec,
            trade_account=ta,
        )
        if qty_broker is None:
            _add_step("4_verify_position_broker", True, False,
                      duration_ms=(time.perf_counter() - ts4) * 1000,
                      error="DTC freeze on get_position_qty", is_critical=True)
            return FlattenResult(
                sequence_completed=False,
                final_qty_broker=0,
                steps=steps,
                critical_steps_failed=critical_failed,
                cleanup_steps_failed=cleanup_failed,
                duration_total_ms=(time.perf_counter() - t0) * 1000,
                error="DTC freeze on get_position_qty",
            )
        _add_step("4_verify_position_broker", True, True,
                  duration_ms=(time.perf_counter() - ts4) * 1000)

        # === Etape 5 : MARKET CLOSE si residuel (CRITIQUE) ===
        ts5 = time.perf_counter()
        if qty_broker != 0:
            close_side = "SELL" if qty_broker > 0 else "BUY"
            close_qty = abs(qty_broker)
            close_cid = f"{self.config.dtc.client_order_id_prefix}CLOSE_{uuid.uuid4().hex[:8]}"
            try:
                self._send_market_close(
                    symbol=symbol_contract, side=close_side, quantity=close_qty,
                    client_order_id=close_cid, trade_account=ta,
                )
                _add_step("5_market_close_if_residual", True, True,
                          duration_ms=(time.perf_counter() - ts5) * 1000,
                          is_critical=True)
            except Exception as e:
                _add_step("5_market_close_if_residual", True, False,
                          duration_ms=(time.perf_counter() - ts5) * 1000,
                          error=str(e)[:200], is_critical=True)

            # === Etape 6 : Wait fill ===
            time.sleep(self.config.flatten_wait_2_after_market_close_sec)
            _add_step("6_wait_2s_fill", True, True,
                      duration_ms=self.config.flatten_wait_2_after_market_close_sec * 1000)
        else:
            _add_step("5_market_close_if_residual", False, True, error="already_flat")
            _add_step("6_wait_2s_fill", False, True, error="skip_no_close")

        # === Etape 6.5 : CANCEL-ALL-WORKING (cleanup tolerable) ===
        ts65 = time.perf_counter()
        try:
            working = self.get_open_orders(
                symbol_filter=symbol_contract, trade_account=ta, timeout_sec=3.0,
            )
            if working:
                for order in working:
                    cid = order.get("ClientOrderID", "")
                    if cid:
                        self.cancel_order(cid, trade_account=ta)
                _add_step("6.5_cancel_all_working_query", True, True,
                          duration_ms=(time.perf_counter() - ts65) * 1000,
                          error=f"cancelled_{len(working)}")
            else:
                _add_step("6.5_cancel_all_working_query", True, True,
                          duration_ms=(time.perf_counter() - ts65) * 1000)
        except Exception as e:
            _add_step("6.5_cancel_all_working_query", True, False,
                      error=str(e)[:200])

        # === Etape 7 : Type 209 SUBMIT_FLATTEN_POSITION (cleanup tolerable) ===
        ts7 = time.perf_counter()
        try:
            self._send_type_209_flatten_symbol(symbol_contract, ta)
            _add_step("7_type_209_flatten_symbol", True, True,
                      duration_ms=(time.perf_counter() - ts7) * 1000)
        except Exception as e:
            _add_step("7_type_209_flatten_symbol", True, False, error=str(e)[:200])

        # === Etape 8 : Type 210 FLATTEN_ACCOUNT (cleanup tolerable bouclier) ===
        ts8 = time.perf_counter()
        try:
            self._send_type_210_flatten_account(ta)
            _add_step("8_type_210_flatten_account", True, True,
                      duration_ms=(time.perf_counter() - ts8) * 1000)
        except Exception as e:
            _add_step("8_type_210_flatten_account", True, False, error=str(e)[:200])

        # === Etape 9 : VERIFY POST-CLEANUP (CRITIQUE) ===
        time.sleep(self.config.flatten_wait_3_after_type_209_sec)
        ts9 = time.perf_counter()
        orphan_detected = False
        try:
            survivors = self.get_open_orders(
                symbol_filter=symbol_contract, trade_account=ta, timeout_sec=3.0,
            )
            if survivors:
                orphan_detected = True
                for order in survivors:
                    cid = order.get("ClientOrderID", "")
                    if cid:
                        self.cancel_order(cid, trade_account=ta)
                _add_step("9_verify_post_cleanup", True, False,
                          duration_ms=(time.perf_counter() - ts9) * 1000,
                          error=f"orphan_detected_{len(survivors)}", is_critical=True)
            else:
                _add_step("9_verify_post_cleanup", True, True,
                          duration_ms=(time.perf_counter() - ts9) * 1000)
        except Exception as e:
            _add_step("9_verify_post_cleanup", True, False, error=str(e)[:200],
                      is_critical=True)

        # Verify final qty
        final_qty = self.get_position_qty(
            symbol_contract, timeout_sec=2.0, trade_account=ta,
        ) or 0

        # Fix P1-2 review J9 : separer critical (4,5,9) vs cleanup (1,2,6.5,7,8)
        # sequence_completed = NO critical fail + NO orphan + final qty=0
        sequence_completed = (
            not critical_failed
            and not orphan_detected
            and final_qty == 0
        )

        return FlattenResult(
            sequence_completed=sequence_completed,
            final_qty_broker=final_qty,
            orphan_detected_post_cleanup=orphan_detected,
            steps=steps,
            critical_steps_failed=critical_failed,
            cleanup_steps_failed=cleanup_failed,
            duration_total_ms=(time.perf_counter() - t0) * 1000,
        )

    # -------------------------------------------------------------------------
    # Internal : send MARKET CLOSE + Type 209/210 (ClientOrderID OBLIGATOIRE)
    # -------------------------------------------------------------------------

    def _send_market_close(
        self, symbol: str, side: str, quantity: int,
        client_order_id: str, trade_account: str,
    ) -> None:
        """Type 208 MARKET avec OpenCloseTrade=2 (close)."""
        if not self._legacy or not hasattr(self._legacy, "_send"):
            return
        legacy_side = BUY if side == "BUY" else SELL
        self._legacy._send({
            "Type": 208,  # MARKET_ORDER
            "Symbol": symbol,
            "ClientOrderID": client_order_id,
            "OrderType": MARKET,
            "BuySell": legacy_side,
            "Quantity": quantity,
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,  # CLOSE
            "TimeInForce": 0,
        })

    def _send_type_209_flatten_symbol(self, symbol: str, trade_account: str) -> None:
        """Type 209 SUBMIT_FLATTEN_POSITION_ORDER (ClientOrderID OBLIGATOIRE).

        Sans ClientOrderID, SC rejette silencieusement (decouvert 04/05).
        """
        if not self._legacy or not hasattr(self._legacy, "_send"):
            return
        flush_cid = (
            f"{self.config.dtc.client_order_id_prefix}FLUSH_"
            f"{symbol[:2]}_{int(time.time()) % 100000}"
        )
        self._legacy._send({
            "Type": 209,
            "ClientOrderID": flush_cid,
            "Symbol": symbol,
            "TradeAccount": trade_account,
            "Exchange": "CME",
            "IsAutomatedOrder": 1,
        })

    def _send_type_210_flatten_account(self, trade_account: str) -> None:
        """Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (ClientOrderID OBLIGATOIRE)."""
        if not self._legacy or not hasattr(self._legacy, "_send"):
            return
        acct_cid = (
            f"{self.config.dtc.client_order_id_prefix}FLUSH_ACCT_"
            f"{int(time.time()) % 100000}"
        )
        self._legacy._send({
            "Type": 210,
            "ClientOrderID": acct_cid,
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
        })
