"""Logger Bot 5 VWAP-SD : wrapper bot_log V2 + decisions JSONL.

Codes log catalogues dans CORE/log_catalog.py (prefix BOTVWAPSD_).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class _BotLogProxy:
    """Wrapper bot_log V2 si dispo, fallback logging standard sinon."""

    def __init__(self):
        self._fallback = logging.getLogger("bot_vwap_sd")
        # FIX review #4 IMPORTANT 20/06 : except ImportError specifique pour
        # tracer cause root (avant: bare Exception masquait typo / dependency).
        try:
            from CORE.logging_v2 import bot_log as _v2_log
            self._impl = _v2_log
        except ImportError as e:
            self._impl = None
            self._fallback.warning(
                f"CORE.logging_v2 indisponible (ImportError: {e}), "
                f"fallback stdlib logging"
            )

    def emit(self, code: str, **ctx) -> None:
        try:
            if self._impl is not None:
                self._impl.emit(code, **ctx)
            else:
                self._fallback.info(f"{code} {ctx}")
        except Exception as e:  # noqa: BLE001
            # Garde bare Exception ici car emit() peut tomber sur tout
            # (network log_v2 distant, JSON serialization, etc.)
            self._fallback.warning(f"bot_log emit fail {code}: {e}")


bot_log = _BotLogProxy()


def log_decision_jsonl(
    bar_ts: Optional[str],
    symbol: str,
    direction: Optional[str],
    setup_id: Optional[str],
    tradable: bool,
    skip_reason: str,
    session_phase: str,
    shadow: bool,
    snapshot: Optional[dict],
    log_dir: str = "LOGS/decisions",
) -> None:
    """Ecrit 1 ligne JSONL par decision (audit + dashboard)."""
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    file = path / f"botvwapsd_decisions_{today}.jsonl"

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bar_ts": bar_ts,
        "sym": symbol,
        "direction": direction,
        "setup_id": setup_id,
        "tradable": tradable,
        "skip_reason": skip_reason,
        "session_phase": session_phase,
        "shadow": shadow,
        "snapshot": snapshot,
    }
    try:
        with file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:  # noqa: BLE001
        logging.getLogger("bot_vwap_sd").warning(f"log_decision_jsonl fail: {e}")
