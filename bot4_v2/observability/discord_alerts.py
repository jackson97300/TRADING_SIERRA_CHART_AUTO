"""Bot 4 v2 discord_alerts - alertes CRITIQUE/MAJEUR via Discord webhook.

Module NEW Phase P5.4.C (26/06/2026) — Alerts paper Sim4 24h supervision.

Responsabilites strictes (SRP) :
- DiscordAlerter class : send_alert(code, msg, ctx) fire-and-forget
- DiscordAlertHandler : logging.Handler hook qui dispatche events CRITICAL+
  vers Discord automatiquement (anti spam via throttle 60s par code)
- Fail-soft TOTAL : Discord down / network glitch / 4xx / 5xx -> log warning
  local + continue, JAMAIS crash bot

Pattern usage minimal :
    from bot4_v2.observability.discord_alerts import (
        DiscordAlerter, DiscordAlertHandler, install_handler,
    )
    alerter = DiscordAlerter(webhook_url=os.getenv("DISCORD_WEBHOOK"))
    install_handler(alerter, min_level=logging.CRITICAL)
    # Apres : tous les _LOG.critical(...) cross-modules -> Discord auto

EXCLU scope (backlog) :
- Rich embeds Discord (markdown table P&L, etc.)
- Mention @everyone configurable (defaut @here pour CRITIQUE)
- Multi-channel routing (CRITIQUE -> #alerts, INFO -> #logs)

Garde-fous :
- Throttle 60s par code (anti spam si KILL_SWITCH loop)
- Timeout 5s par request (anti freeze main loop)
- Fail-soft urllib.request (pas dependence requests)
- Logs cross-traceability via emit_safe (codes BOT4V2_DISCORD_*)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# SETTINGS frozen
# ============================================================


@dataclass(frozen=True)
class DiscordAlertSettings:
    """Settings DiscordAlerter. Frozen anti-mutation runtime."""

    throttle_sec: float = 60.0          # 1 alerte/code max chaque N sec
    timeout_sec: float = 5.0            # HTTP timeout (anti freeze loop)
    max_message_chars: int = 1900       # Discord limit 2000, marge securite
    mention_at_here: bool = True        # @here sur CRITIQUE
    enabled: bool = True                # Master switch (env var override)

    def __post_init__(self) -> None:
        if self.throttle_sec < 0:
            raise ValueError("throttle_sec must be >= 0")
        if self.timeout_sec <= 0:
            raise ValueError("timeout_sec must be > 0")
        if self.max_message_chars <= 0:
            raise ValueError("max_message_chars must be > 0")


# ============================================================
# DISCORD ALERTER (standalone, injectable)
# ============================================================


class DiscordAlerter:
    """Sender Discord webhook fire-and-forget + throttle anti-spam.

    Pattern usage :
        alerter = DiscordAlerter(
            webhook_url=os.getenv("BOT4V2_DISCORD_WEBHOOK"),
            settings=DiscordAlertSettings(throttle_sec=60),
        )
        # Appel manuel :
        alerter.send_alert(
            code="BOT4V2_ROUTER_BRACKET_NAKED",
            msg="Router NQ bracket NAKED parent=P_123 fill=20000.0",
            ctx={"sym": "NQ", "parent_cid": "P_123"},
        )
        # OU via logging handler (cf install_handler ci-dessous)
    """

    def __init__(
        self,
        webhook_url: Optional[str],
        settings: Optional[DiscordAlertSettings] = None,
        url_opener: Optional[object] = None,  # injection tests
    ):
        """Init alerter.

        Args:
            webhook_url : URL webhook Discord (None ou vide = disabled silencieux)
            settings : DiscordAlertSettings (defaut throttle 60s)
            url_opener : injection tests (defaut urllib.request.urlopen)
        """
        self._webhook = (webhook_url or "").strip()
        self._settings = settings or DiscordAlertSettings()
        self._opener = url_opener or urllib.request.urlopen
        self._last_alert_ts: dict[str, float] = {}  # code -> epoch_sec
        self._n_sent = 0
        self._n_throttled = 0
        self._n_failed = 0

    @property
    def enabled(self) -> bool:
        return self._settings.enabled and bool(self._webhook)

    @property
    def stats(self) -> dict:
        return {
            "n_sent": self._n_sent,
            "n_throttled": self._n_throttled,
            "n_failed": self._n_failed,
            "n_tracked_codes": len(self._last_alert_ts),
        }

    def send_alert(
        self,
        code: str,
        msg: str,
        ctx: Optional[dict] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Envoie alerte Discord. Fire-and-forget + throttle.

        Args:
            code : code log catalog (ex "BOT4V2_ROUTER_BRACKET_NAKED")
            msg : message formate prêt à afficher
            ctx : metadata optionnel (sera serialise JSON dans message)
            now : epoch time (defaut time.time()), injection tests

        Returns:
            True si effectivement envoye, False si throttled / disabled / fail.
        """
        if not self.enabled:
            return False

        ts = now if now is not None else time.time()

        # Throttle par code (anti spam KILL_SWITCH loop)
        last_ts = self._last_alert_ts.get(code, 0.0)
        if (ts - last_ts) < self._settings.throttle_sec:
            self._n_throttled += 1
            return False

        # Build payload Discord
        body = self._build_message(code, msg, ctx)
        payload = {"content": body}
        try:
            data = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError) as exc:
            emit_safe(
                _LOG, "BOT4V2_DISCORD_PAYLOAD_FAIL",
                alert_code=code, exc_type=type(exc).__name__,
            )
            self._n_failed += 1
            return False

        # HTTP POST fire-and-forget avec timeout
        req = urllib.request.Request(
            self._webhook, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(req, timeout=self._settings.timeout_sec) as resp:
                status = getattr(resp, "status", None)
                if status is None:
                    # urlopen response.getcode() pour compat older Python
                    status = resp.getcode() if hasattr(resp, "getcode") else 200
                if 200 <= int(status) < 300:
                    self._n_sent += 1
                    self._last_alert_ts[code] = ts
                    return True
                emit_safe(
                    _LOG, "BOT4V2_DISCORD_HTTP_FAIL",
                    alert_code=code, http_status=int(status),
                )
                self._n_failed += 1
                return False
        except urllib.error.HTTPError as exc:
            emit_safe(
                _LOG, "BOT4V2_DISCORD_HTTP_FAIL",
                alert_code=code, http_status=exc.code,
            )
            self._n_failed += 1
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            emit_safe(
                _LOG, "BOT4V2_DISCORD_NETWORK_FAIL",
                alert_code=code, exc_type=type(exc).__name__,
            )
            self._n_failed += 1
            return False
        except Exception as exc:  # noqa: BLE001
            # Defense en profondeur (jamais crash bot sur Discord)
            emit_safe(
                _LOG, "BOT4V2_DISCORD_UNEXPECTED_FAIL",
                alert_code=code, exc_type=type(exc).__name__,
            )
            self._n_failed += 1
            return False

    def _build_message(
        self, code: str, msg: str, ctx: Optional[dict],
    ) -> str:
        """Format message Discord avec mention conditionnelle + truncation."""
        parts = []
        if self._settings.mention_at_here:
            parts.append("@here")
        parts.append(f"**[{code}]**")
        parts.append(msg or "(no message)")
        if ctx:
            try:
                ctx_str = json.dumps(ctx, default=str)
            except (TypeError, ValueError):
                ctx_str = str(ctx)
            parts.append(f"```{ctx_str}```")
        body = " ".join(parts)
        # Truncate si trop long (Discord 2000 char limit)
        if len(body) > self._settings.max_message_chars:
            body = body[:self._settings.max_message_chars - 20] + "...(truncated)"
        return body


# ============================================================
# LOGGING HANDLER (auto-dispatch CRITICAL+)
# ============================================================


class DiscordAlertHandler(logging.Handler):
    """Logging handler qui dispatch records >= CRITICAL vers DiscordAlerter.

    Pattern install :
        alerter = DiscordAlerter(webhook_url=...)
        handler = DiscordAlertHandler(alerter, min_level=logging.CRITICAL)
        logging.getLogger().addHandler(handler)
        # Apres : tous _LOG.critical(...) cross-modules -> Discord auto

    Garde-fous :
    - Filtre level (defaut CRITICAL+ pour anti spam INFO)
    - Extract code depuis record.args ou record.msg si format catalogue
    - Fail-soft : exception dans emit() = log warning + continue
    """

    def __init__(
        self,
        alerter: DiscordAlerter,
        min_level: int = logging.CRITICAL,
    ):
        super().__init__(level=min_level)
        self._alerter = alerter

    def emit(self, record: logging.LogRecord) -> None:
        """Override : dispatch record vers alerter si level OK."""
        try:
            if record.levelno < self.level:
                return
            # Extract code + msg du record
            code, msg = self._extract_code_and_msg(record)
            # Extract ctx (record.args si dict, sinon empty)
            ctx = {}
            if isinstance(record.args, dict):
                ctx = dict(record.args)
            self._alerter.send_alert(code=code, msg=msg, ctx=ctx)
        except Exception:  # noqa: BLE001
            # Fail-soft : NEVER crash bot sur handler exception
            try:
                self.handleError(record)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _extract_code_and_msg(record: logging.LogRecord) -> tuple[str, str]:
        """Extract code + msg depuis record (format emit_safe ou stdlib)."""
        # emit_safe formate "[CODE] message ctx=..."
        msg = record.getMessage()
        if msg.startswith("[") and "]" in msg:
            end = msg.index("]")
            code = msg[1:end]
            rest = msg[end + 1:].lstrip()
            return code, rest
        # Stdlib record sans code structure
        return record.name, msg


# ============================================================
# INSTALL HELPER
# ============================================================


def install_handler(
    alerter: DiscordAlerter,
    min_level: int = logging.CRITICAL,
    logger_name: Optional[str] = None,
) -> DiscordAlertHandler:
    """Helper : install handler sur logger root (ou named).

    Args:
        alerter : DiscordAlerter pre-construit
        min_level : seuil declenchement (defaut CRITICAL = log.critical only)
        logger_name : logger cible (None = root logger = capture tout)

    Returns:
        DiscordAlertHandler installe (utile pour uninstall manuel).
    """
    handler = DiscordAlertHandler(alerter, min_level=min_level)
    target_logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    target_logger.addHandler(handler)
    return handler


def uninstall_handler(
    handler: DiscordAlertHandler,
    logger_name: Optional[str] = None,
) -> None:
    """Helper : remove handler du logger cible."""
    target_logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    target_logger.removeHandler(handler)
