"""Logger Bot Mean Revert - wrapper logging_v2 + JSONL decisions dedie.

Respecte regle souveraine LOGS TRACABILITE (01/05/2026) :
  - Chaque event critique a un code catalog (BOTMR_*) defini AVANT le commit
  - JSONL structure via CORE.logging_v2 (catalog -> categorie -> Discord auto)
  - JSONL DEDIE decisions : LOGS/bot_mr_decisions/{YYYYMMDD}.jsonl append-only
    pour audit fin (sweep -> verifier que prod reproduit edge offline)

Usage :
    from CORE.bot_mean_revert.logger import bot_log, log_decision_jsonl

    bot_log.emit("BOTMR_BOOT", dry_run=False, symbols="ES,NQ", trade_account="Sim1")
    log_decision_jsonl(bar_ts, "ES", signal, executed=True)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from CORE.logging_v2 import get_logger
except ImportError:  # pragma: no cover
    from logging_v2 import get_logger  # type: ignore


# Logger unique partage par tous les modules Bot MR (process=bot_mr separe les fichiers JSONL)
bot_log = get_logger("bot_mean_revert", process="bot_mr")


# === JSONL DECISIONS DEDIE ===

_DECISIONS_DIR = Path(os.environ.get("MIA_LOG_DIR", "LOGS")) / "bot_mr_decisions"


def _decisions_path() -> Path:
    """Chemin du JSONL decisions du jour (UTC)."""
    _DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _DECISIONS_DIR / f"bot_mr_decisions_{day}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_decision_jsonl(
    *,
    bar_ts: Optional[int],
    symbol: str,
    signal,  # SignalResult
    executed: bool = False,
    fill_price: Optional[float] = None,
    order_error: Optional[str] = None,
    session_phase: Optional[str] = None,
    hypothetical: bool = False,
) -> None:
    """Append une ligne JSONL pour CHAQUE evaluation (skip OU tradable).

    Permet audit empirique offline :
      - Pourquoi 0 trade ? grep skip_reason
      - Quelle distribution direction ? jq stats
      - Edge sweep tient-il en live ? compare PF offline vs prod
      - Tuning futur seuils sans toucher code
    """
    try:
        signal_dict: dict[str, Any] = {
            "tradable": getattr(signal, "tradable", False),
            "direction": getattr(signal, "direction", None),
            "skip_reason": getattr(signal, "skip_reason", ""),
            "entry_price": getattr(signal, "entry_price", 0.0),
            "sl_price": getattr(signal, "sl_price", 0.0),
            "tp_price": getattr(signal, "tp_price", 0.0),
            "sl_ticks": getattr(signal, "sl_ticks", 0),
            "tp_ticks": getattr(signal, "tp_ticks", 0),
            "rr_ratio": getattr(signal, "rr_ratio", 0.0),
            "sd_level": getattr(signal, "sd_level", ""),
            "vwap_slope_30": getattr(signal, "vwap_slope_30", 0.0),
            "vix_level": getattr(signal, "vix_level", 0.0),
            "rvol_zscore": getattr(signal, "rvol_zscore", 0.0),
            "ctx_trend_day_score": getattr(signal, "ctx_trend_day_score", 0.0),
        }
        entry = {
            "ts": _now_iso(),
            "bar_ts": bar_ts,
            "symbol": symbol,
            "signal_id": getattr(signal, "signal_id", ""),
            "signal": signal_dict,
            "executed": executed,
            "fill_price": fill_price,
            "order_error": order_error,
            "session_phase": session_phase,
            "hypothetical": hypothetical,
        }
        line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
        with _decisions_path().open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:  # noqa: BLE001 - anti-bloque le bot
        try:
            bot_log.emit("BOTMR_LOOP_EXCEPTION", err=f"decisions_jsonl_fail: {exc!r}")
        except Exception:
            pass
