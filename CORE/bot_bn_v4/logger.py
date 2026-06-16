"""Logger Bot BN V4 - wrapper logging_v2 + JSONL decisions dedie.

Respecte regle souveraine LOGS TRACABILITE (01/05/2026) :
  - Codes catalog BOTBN_* via CORE.logging_v2
  - JSONL DEDIE decisions : LOGS/bot_bn_v4_decisions/{YYYYMMDD}.jsonl
    (regle C : gate filtre >30% -> dedie pour audit fin)

Usage :
    from CORE.bot_bn_v4.logger import bot_log, log_decision_jsonl

    bot_log.emit("BOTBN_BOOT", dry_run=True, symbols="NQ",
                 trade_account="Sim3", grade_min="A++")
    log_decision_jsonl(bar_ts, "NQ", setup_dict, executed=True)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from CORE.logging_v2 import get_logger
except ImportError:
    from logging_v2 import get_logger  # type: ignore


# Logger unique pour tous les modules Bot BN V4 (process=botbn = fichiers JSONL separes)
bot_log = get_logger("bot_bn_v4", process="botbn")


# === JSONL DECISIONS DEDIE ===

_DECISIONS_DIR = Path(os.environ.get("MIA_LOG_DIR", "LOGS")) / "bot_bn_v4_decisions"


def _decisions_path() -> Path:
    """Chemin du JSONL decisions du jour (UTC)."""
    _DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _DECISIONS_DIR / f"bot_bn_v4_decisions_{day}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_decision_jsonl(
    *,
    bar_ts: Optional[int],
    symbol: str,
    direction: Optional[str],
    setup: Optional[dict],
    tradable: bool,
    executed: bool = False,
    skip_reason: str = "",
    fill_price: Optional[float] = None,
    sl_price: Optional[float] = None,
    sl_ticks: Optional[int] = None,
    order_error: Optional[str] = None,
    session_phase: Optional[str] = None,
    hypothetical: bool = False,
) -> None:
    """Append une ligne JSONL pour chaque evaluation (skip OU tradable OU hypo).

    Permet audit empirique offline :
      - Distribution grades (A++/A/B/C) par jour
      - Quels gates BN V4 firent le plus ?
      - A/B grades hypothetiques : auraient-ils ete profitables ?
      - London hypothetique : vaut-il la peine d'ouvrir une nouvelle session ?
    """
    try:
        entry: dict[str, Any] = {
            "ts": _now_iso(),
            "bar_ts": bar_ts,
            "symbol": symbol,
            "direction": direction,
            "tradable": tradable,
            "executed": executed,
            "hypothetical": hypothetical,
            "skip_reason": skip_reason,
            "session_phase": session_phase,
            "fill_price": fill_price,
            "sl_price": sl_price,
            "sl_ticks": sl_ticks,
            "order_error": order_error,
        }
        if setup:
            entry["setup"] = {
                "grade": setup.get("grade"),
                "density": setup.get("density"),
                "n_levels": setup.get("n_levels"),
                "mode": setup.get("mode"),
                "entry_price": setup.get("entry_price"),
                "zone_bottom": setup.get("zone_bottom"),
                "zone_top": setup.get("zone_top"),
                "slope_mean_60": setup.get("slope_mean_60"),
                "outside_window": setup.get("outside_window", False),
            }
        line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
        with _decisions_path().open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        # Anti-bloque le bot : si JSONL write fail (disque plein, perm),
        # emit catalogue mais ne raise pas dans la loop principale.
        try:
            bot_log.emit("BOTBN_LOOP_EXCEPTION", err=f"decisions_jsonl_fail: {exc!r}")
        except Exception:
            pass
