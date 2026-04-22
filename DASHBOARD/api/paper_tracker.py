"""Paper tracker bridge — lecture state.json + agregation stats historiques.

Source de verite : `DATA/PAPER_TRADES/state.json` ecrit par `CORE/mia_paper_trader.py`.
Ce module LIT SEULEMENT (aucune logique de trading). Expose endpoint API pour frontend.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).parent.parent.parent
PAPER_DIR = _ROOT / "DATA" / "PAPER_TRADES"
STATE_FILE = PAPER_DIR / "state.json"


def _safe_read_state() -> dict:
    """Lit state.json (atomic read, fallback dict vide si absent)."""
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _empty_state()


def _empty_state() -> dict:
    return {
        "updated_ts": 0,
        "updated_iso": None,
        "date": None,
        "open_by_symbol": {},
        "closed_today": [],
        "stats_today": {"trades": 0, "wins": 0, "losses": 0, "wr": 0, "pf": None, "pnl_usd": 0, "pnl_ticks": 0},
        "stats_by_symbol": {"ES": {}, "NQ": {}},
        "cooldown_status": {},
        "trade_count_today": 0,
        "max_trades_per_day": 10,
    }


def _iter_trades_from_files(since_utc: datetime):
    """Yields trades from *_trades.jsonl files since a datetime."""
    if not PAPER_DIR.exists():
        return
    for path in sorted(glob(str(PAPER_DIR / "*_trades.jsonl"))):
        # Filter by filename date
        fname = os.path.basename(path)
        try:
            date_str = fname.split("_")[0]
            file_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            if file_date.date() < (since_utc - timedelta(days=1)).date():
                continue
        except (ValueError, IndexError):
            pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        exit_time_str = trade.get("exit_time", "")
                        try:
                            trade_ts = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                            if trade_ts >= since_utc:
                                yield trade
                        except (ValueError, AttributeError):
                            continue
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def compute_stats_period(days: int) -> dict:
    """Calcule stats sur N jours passes (WR, PF, PnL total, count par symbol)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trades = list(_iter_trades_from_files(since))
    if not trades:
        return {"trades": 0, "wr": 0, "pf": None, "pnl_usd": 0, "pnl_ticks": 0, "by_symbol": {}}

    wins = [t for t in trades if t.get("pnl_ticks", 0) > 0]
    losses = [t for t in trades if t.get("pnl_ticks", 0) <= 0]
    win_ticks = sum(t.get("pnl_ticks", 0) for t in wins) if wins else 0
    loss_ticks = sum(abs(t.get("pnl_ticks", 0)) for t in losses) if losses else 0
    total_usd = sum(t.get("pnl_usd", 0) for t in trades)

    by_sym = {}
    for sym in ("ES", "NQ"):
        subset = [t for t in trades if t.get("symbol") == sym]
        if not subset:
            by_sym[sym] = {"trades": 0, "wr": 0, "pnl_usd": 0, "pf": None}
            continue
        sw = [t for t in subset if t.get("pnl_ticks", 0) > 0]
        sl = [t for t in subset if t.get("pnl_ticks", 0) <= 0]
        sw_t = sum(t.get("pnl_ticks", 0) for t in sw) if sw else 0
        sl_t = sum(abs(t.get("pnl_ticks", 0)) for t in sl) if sl else 0
        by_sym[sym] = {
            "trades": len(subset),
            "wr": round(len(sw) / len(subset) * 100, 1),
            "pf": round(sw_t / sl_t, 2) if sl_t > 0 else None,
            "pnl_usd": round(sum(t.get("pnl_usd", 0) for t in subset), 2),
        }

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(len(wins) / len(trades) * 100, 1),
        "pf": round(win_ticks / loss_ticks, 2) if loss_ticks > 0 else None,
        "pnl_usd": round(total_usd, 2),
        "pnl_ticks": round(sum(t.get("pnl_ticks", 0) for t in trades), 1),
        "by_symbol": by_sym,
    }


def get_paper_trades_payload() -> dict:
    """Retourne payload complet pour endpoint /api/paper_trades.

    Structure :
      - state : snapshot live (open positions + today trades + today stats)
      - stats_7d : agreges 7 jours
      - stats_30d : agreges 30 jours
      - has_paper_active : bool (positions ouvertes OU cooldown/breaker actif)
    """
    state = _safe_read_state()
    stats_7d = compute_stats_period(7)
    stats_30d = compute_stats_period(30)

    has_open = bool(state.get("open_by_symbol"))
    has_cooldown = any(
        (cs.get("cooldown_remaining_sec", 0) > 0 or cs.get("circuit_breaker_remaining_sec", 0) > 0)
        for cs in (state.get("cooldown_status") or {}).values()
    )

    # Age du state (si > 60s, paper trader probablement down)
    age_sec = None
    if state.get("updated_ts"):
        age_sec = max(0, datetime.now(timezone.utc).timestamp() - state["updated_ts"])

    return {
        "state": state,
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "has_paper_active": has_open or has_cooldown,
        "state_age_sec": age_sec,
        "paper_trader_alive": age_sec is not None and age_sec < 60,
    }
