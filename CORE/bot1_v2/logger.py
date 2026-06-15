"""Logger Bot 1 v2 - wrapper logging_v2 + JSONL decisions dedie.

Respecte regle souveraine LOGS TRACABILITE (01/05/2026) :
  - Chaque event critique a un code catalog (BOT1V2_*) defini AVANT le commit
  - JSONL structure via CORE.logging_v2 (catalog -> categorie -> Discord auto)
  - JSONL DEDIE decisions : LOGS/bot1_v2_decisions/{YYYYMMDD}.jsonl append-only
    (regle C : gate filtre >30% -> dedie pour audit fin)

Usage :
    from CORE.bot1_v2.logger import bot_log, log_decision_jsonl

    bot_log.emit("BOT1V2_BOOT", dry_run=False, symbols=["ES","NQ"], trade_account="Sim2")
    log_decision_jsonl(bar_ts, "ES", mirror_verdict, sltp_result, decision_result, executed=True)
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


# Logger unique partage par tous les modules Bot 1 v2 (process=bot1v2 separe les fichiers JSONL)
bot_log = get_logger("bot1_v2", process="bot1v2")


# === JSONL DECISIONS DEDIE ===

_DECISIONS_DIR = Path(os.environ.get("MIA_LOG_DIR", "LOGS")) / "bot1_v2_decisions"


def _decisions_path() -> Path:
    """Chemin du JSONL decisions du jour (UTC)."""
    _DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _DECISIONS_DIR / f"bot1_v2_decisions_{day}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_decision_jsonl(
    *,
    bar_ts: Optional[int],
    symbol: str,
    mirror,  # MirrorVerdict | None
    sltp,    # SLTPResult | None
    decision,  # ClusterDecision
    executed: bool = False,
    fill_price: Optional[float] = None,
    order_error: Optional[str] = None,
    session_phase: Optional[str] = None,
    hypothetical: bool = False,
) -> None:
    """Append une ligne JSONL pour CHAQUE evaluation (skip OU tradable).

    Permet audit empirique offline :
      - Pourquoi 0 trade ? grep skip_reason
      - Quelle distribution stars ? jq stats
      - Quels vetos firent le plus ? bucket par name
      - Tuning futur seuils sans toucher code

    Format colonne-friendly pour jq / pandas read_json(lines=True).
    """
    try:
        verdict_dict: dict[str, Any] = {}
        if mirror is not None:
            verdict_dict = {
                "action": getattr(mirror, "action", None),
                "direction": getattr(mirror, "direction", None),
                "ready_to_arm": getattr(mirror, "ready_to_arm", False),
                "bull_pts": getattr(mirror, "bull_pts", 0),
                "bear_pts": getattr(mirror, "bear_pts", 0),
                "bias_score": getattr(mirror, "bias_score", 0.0),
                "bias_label": getattr(mirror, "bias_label", ""),
                "mtf_bulls": getattr(mirror, "mtf_bulls", 0),
                "mtf_bears": getattr(mirror, "mtf_bears", 0),
                "mtf_neutres": getattr(mirror, "mtf_neutres", 0),
                "stars_count": getattr(mirror, "stars_count", 0),
                "stars_total": getattr(mirror, "stars_total", 7),
                "vetos": [
                    {"name": v.name, "reason": v.reason, "value": str(v.value)}
                    for v in getattr(mirror, "vetos", ()) or ()
                ],
                "quality_misses": [
                    {"name": q.name, "reason": q.reason, "value": str(q.value)}
                    for q in getattr(mirror, "quality_misses", ()) or ()
                ],
                "vix_level": getattr(mirror, "vix_level", 0.0),
                "rvol_zscore": getattr(mirror, "rvol_zscore", 0.0),
                "ctx_climax_signal": getattr(mirror, "ctx_climax_signal", False),
                "gamma_block_long": getattr(mirror, "gamma_block_long", False),
                "gamma_block_short": getattr(mirror, "gamma_block_short", False),
            }

        sltp_dict: dict[str, Any] = {}
        if sltp is not None:
            sltp_dict = {
                "accepted": getattr(sltp, "accepted", False),
                "reject_reason": getattr(sltp, "reject_reason", ""),
                "sl_price": getattr(sltp, "sl_price", 0.0),
                "tp_price": getattr(sltp, "tp_price", 0.0),
                "sl_ticks": getattr(sltp, "sl_ticks", 0),
                "tp_ticks": getattr(sltp, "tp_ticks", 0),
                "rr_ratio": getattr(sltp, "rr_ratio", 0.0),
                "sl_wall": getattr(sltp, "sl_wall", ""),
                "sl_tier": getattr(sltp, "sl_tier", 0),
            }

        entry = {
            "ts": _now_iso(),
            "bar_ts": bar_ts,
            "symbol": symbol,
            "signal_id": getattr(decision, "signal_id", ""),
            "tradable": getattr(decision, "tradable", False),
            "skip_reason": getattr(decision, "skip_reason", ""),
            "direction": getattr(decision, "direction", None),
            "entry_price": getattr(decision, "entry_price", 0.0),
            "n_micros": getattr(decision, "n_micros", 0),
            "verdict": verdict_dict,
            "sltp": sltp_dict,
            "executed": executed,
            "fill_price": fill_price,
            "order_error": order_error,
            # Dry-evaluate Asia/London audit (Jackson 16/06) :
            #   session_phase = US_RTH / ASIA / LONDON / EOD / NEWS / ...
            #   hypothetical  = True ssi cluster evalue mais session non-RTH
            #                   (decision pas executee, juste loggee)
            "session_phase": session_phase,
            "hypothetical": hypothetical,
        }
        line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
        with _decisions_path().open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        # Anti-bloque le bot : si JSONL write fail (disque plein, perm),
        # emit un log catalogue mais ne raise pas dans la loop principale.
        try:
            bot_log.emit("BOT1V2_LOOP_EXCEPTION", err=f"decisions_jsonl_fail: {exc!r}")
        except Exception:
            pass
