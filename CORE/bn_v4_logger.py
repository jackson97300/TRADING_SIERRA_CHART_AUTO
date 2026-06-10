"""bn_v4_logger.py — Logger JSONL dedie BN V4 paper trades.

Exige par regle souveraine `.claude/rules/critical-tasks-review.md` section C
"Logs structurel JSONL dedie" : si gate filtre > 30% des trades, logger JSONL
dedie obligatoire pour tracabilite J+1.

BN V4 filtre 99.9%+ des bars (66 setups TRADE sur 120K bars = 0.055%). Donc
logger dedie obligatoire.

Path output : `LOGS/bn_v4/bn_v4_v1_YYYYMMDD.jsonl` (append-only).

Cycle de vie d'un trade :
  1. log_bar_processed (chaque bar lue, sans setup)
  2. log_setup_detected (genere signal_id, mode=TRADE/OBSERVE)
  3. log_trade_open (linked au signal_id, executed=True)
  4. log_trail_update (chaque cancel-replace SL)
  5. log_trade_close (renseigne pnl_usd avec meme signal_id)

OU pour mode OBSERVE :
  1. log_bar_processed
  2. log_setup_detected (mode=OBSERVE, executed=False)
  3. log_observation_close (pnl_simul_R apres simulation virtuelle)

Schema JSONL :
{
  "ts": str ISO8601 UTC,
  "ts_event_ns": int epoch ns,
  "event": str ("BAR_PROCESSED" / "SETUP_DETECTED" / "TRADE_OPEN" / "TRAIL_UPDATE" / "TRADE_CLOSE" / "OBSERVATION_CLOSE"),
  "signal_id": str (unique BN_V4_{SYM}_{YYYYMMDD}_{NNN}),
  "symbol": str,
  "direction": str ("long" / "short") OR null,
  "mode": str ("TRADE" / "OBSERVE") OR null,
  "grade": str ("A++" / "A" / "B" / "C") OR null,
  "density": int OR null,
  "n_levels": int OR null,
  "score_breakdown": dict OR null,
  "entry_price": float OR null,
  "sl_initial": float OR null,
  "risk_ticks": float OR null,
  "exit_price": float OR null,
  "exit_cause": str OR null,
  "pnl_R": float OR null,
  "pnl_usd": float OR null,
  "duration_bars": int OR null,
  "ctx": dict (champs extra)
}

Auteur : MIA Trading V2
  v1.0 (2026-05-23) : version initiale conforme regle souveraine logs
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
LOG_BASE = ROOT / "LOGS" / "bn_v4"
SCHEMA_VERSION = "bn_v4_v1"


def _now_iso() -> str:
    """Timestamp UTC ISO8601."""
    return datetime.now(timezone.utc).isoformat()


def _json_default(obj):
    """Serializer pour numpy/pandas types non-natifs."""
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            v = float(obj)
            if v != v or v == float("inf") or v == float("-inf"):
                return None
            return round(v, 6)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    try:
        import pandas as pd
        if pd.isna(obj):
            return None
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except (ImportError, TypeError, ValueError):
        pass
    try:
        from datetime import date, datetime as _dt
        if isinstance(obj, _dt):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
    except ImportError:
        pass
    raise TypeError(
        f"Object of type {type(obj).__name__} not JSON serializable"
    )


class BNV4Logger:
    """Logger JSONL dedie BN V4. Thread-safe (lock interne).

    Usage :
        logger = BNV4Logger(symbol='NQ')
        sid = logger.log_setup_detected(setup_dict, score_breakdown)
        logger.log_trade_open(sid, entry_price, sl_initial, risk_ticks)
        logger.log_trail_update(sid, old_sl, new_sl, n_pivots)
        logger.log_trade_close(sid, exit_price, exit_cause, pnl_R, pnl_usd, duration_bars)
    """

    def __init__(self, symbol: str = "NQ", flush_each_write: bool = True):
        self.symbol = symbol
        self.flush_each_write = flush_each_write
        self._lock = threading.Lock()
        self._setup_counter = 0
        self._setup_counter_date: Optional[str] = None
        LOG_BASE.mkdir(parents=True, exist_ok=True)

    def _build_path(self, ts_event_ns: Optional[int] = None) -> Path:
        """Daily path UTC : `LOGS/bn_v4/bn_v4_v1_YYYYMMDD.jsonl`."""
        if ts_event_ns is not None:
            dt = datetime.fromtimestamp(ts_event_ns / 1e9, tz=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
        day_str = dt.strftime("%Y%m%d")
        return LOG_BASE / f"{SCHEMA_VERSION}_{day_str}.jsonl"

    def _next_signal_id(self, ts_event_ns: int) -> str:
        """Genere un signal_id unique : `BN_V4_{SYM}_{YYYYMMDD}_{NNN}`.

        Compteur reset par jour UTC (basee sur ts_event_ns).
        """
        dt = datetime.fromtimestamp(ts_event_ns / 1e9, tz=timezone.utc)
        day_str = dt.strftime("%Y%m%d")
        with self._lock:
            if self._setup_counter_date != day_str:
                self._setup_counter = 0
                self._setup_counter_date = day_str
            self._setup_counter += 1
            n = self._setup_counter
        return f"BN_V4_{self.symbol}_{day_str}_{n:03d}"

    def _write_line(self, record: dict, ts_event_ns: Optional[int] = None) -> bool:
        """Append-only write JSONL. Returns True si OK, False si fail."""
        path = self._build_path(ts_event_ns)
        try:
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    json.dump(record, f, default=_json_default, ensure_ascii=False)
                    f.write("\n")
                    if self.flush_each_write:
                        f.flush()
                        os.fsync(f.fileno())
            return True
        except (OSError, TypeError, ValueError) as e:
            # Fail-safe : log to stderr (le caller doit gerer dim erreur)
            print(f"[BN_V4_LOGGER_WRITE_FAIL] path={path} err={e}",
                   file=sys.stderr)
            return False

    # ──── Methodes publiques ───────────────────────────────────────────────

    def log_bar_processed(self, symbol: str, ts_event_ns: int,
                            close: float, ctx: Optional[dict] = None) -> bool:
        """1 ligne / bar lue. Volume potentiel : ~1440/jour."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(ts_event_ns),
            "event": "BAR_PROCESSED",
            "signal_id": None,
            "symbol": symbol,
            "close": close,
            "ctx": ctx or {},
        }
        return self._write_line(rec, ts_event_ns)

    def log_setup_detected(self, setup: dict,
                            score_breakdown: Optional[dict] = None,
                            ctx: Optional[dict] = None) -> str:
        """Setup BN V4 detecte. Genere signal_id, retourne pour link futur.

        Args:
            setup : dict produit par bn_v4_engine.check_setup() avec
                    bar_idx, entry_price, direction, grade, density,
                    n_levels, mode, ts_event, etc.
            score_breakdown : dict des sous-scores (trend, levels, density,
                              edge, footprint signals fired, etc.)
            ctx : champs additionnels libres

        Returns:
            signal_id genere (str), a propager vers log_trade_open + close.
        """
        ts_event = setup.get("ts_event")
        if hasattr(ts_event, "value"):
            ts_event_ns = int(ts_event.value)
        elif isinstance(ts_event, int):
            ts_event_ns = ts_event
        else:
            ts_event_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)

        signal_id = self._next_signal_id(ts_event_ns)
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns,
            "event": "SETUP_DETECTED",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "direction": setup.get("direction"),
            "mode": setup.get("mode", "TRADE"),
            "grade": setup.get("grade"),
            "density": setup.get("density"),
            "n_levels": setup.get("n_levels"),
            "entry_price": setup.get("entry_price"),
            "zone_bottom": setup.get("zone_bottom"),
            "zone_top": setup.get("zone_top"),
            "score_breakdown": score_breakdown or {},
            "ctx": ctx or {},
        }
        self._write_line(rec, ts_event_ns)
        return signal_id

    def log_trade_open(self, signal_id: str, ts_event_ns: int,
                        entry_price: float, sl_initial: float,
                        risk_ticks: float, qty: int = 1,
                        ctx: Optional[dict] = None) -> bool:
        """Trade DTC ouvert (mode TRADE). Linked au signal_id."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(ts_event_ns),
            "event": "TRADE_OPEN",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "entry_price": entry_price,
            "sl_initial": sl_initial,
            "risk_ticks": risk_ticks,
            "qty": qty,
            "executed": True,
            "ctx": ctx or {},
        }
        return self._write_line(rec, ts_event_ns)

    def log_trail_update(self, signal_id: str, ts_event_ns: int,
                           old_sl: float, new_sl: float,
                           n_pivots: int,
                           ctx: Optional[dict] = None) -> bool:
        """Update trailing SL (cancel-replace DTC)."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(ts_event_ns),
            "event": "TRAIL_UPDATE",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "old_sl": old_sl,
            "new_sl": new_sl,
            "n_pivots_confirmed": n_pivots,
            "ctx": ctx or {},
        }
        return self._write_line(rec, ts_event_ns)

    def log_trade_close(self, signal_id: str, ts_event_ns: int,
                          exit_price: float, exit_cause: str,
                          pnl_R: float, pnl_usd: float,
                          duration_bars: int,
                          ctx: Optional[dict] = None) -> bool:
        """Trade ferme (SL hit, timeout, manuel). Renseigne pnl avec signal_id."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(ts_event_ns),
            "event": "TRADE_CLOSE",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "exit_price": exit_price,
            "exit_cause": exit_cause,
            "pnl_R": pnl_R,
            "pnl_usd": pnl_usd,
            "duration_bars": duration_bars,
            "ctx": ctx or {},
        }
        return self._write_line(rec, ts_event_ns)

    def log_observation_close(self, signal_id: str, ts_event_ns: int,
                                exit_price: float, exit_cause: str,
                                pnl_simul_R: float,
                                duration_bars: int,
                                ctx: Optional[dict] = None) -> bool:
        """Observation grade A close (simul, pas d'ordre DTC)."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(ts_event_ns),
            "event": "OBSERVATION_CLOSE",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "exit_price": exit_price,
            "exit_cause": exit_cause,
            "pnl_simul_R": pnl_simul_R,
            "duration_bars": duration_bars,
            "executed": False,
            "ctx": ctx or {},
        }
        return self._write_line(rec, ts_event_ns)

    def log_kill_switch(self, reason: str, positions_flat: int,
                          orders_canceled: int,
                          ctx: Optional[dict] = None) -> bool:
        """Kill switch active."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(datetime.now(timezone.utc).timestamp() * 1e9),
            "event": "KILL_SWITCH",
            "signal_id": None,
            "symbol": self.symbol,
            "reason": reason,
            "positions_flat": positions_flat,
            "orders_canceled": orders_canceled,
            "ctx": ctx or {},
        }
        return self._write_line(rec)

    def log_error(self, signal_id: Optional[str], error_code: str,
                    error_msg: str, ctx: Optional[dict] = None) -> bool:
        """Erreur runtime BN V4 (linked au signal_id si applicable)."""
        rec = {
            "ts": _now_iso(),
            "ts_event_ns": int(datetime.now(timezone.utc).timestamp() * 1e9),
            "event": "ERROR",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "error_code": error_code,
            "error_msg": error_msg[:500],     # truncate longs
            "ctx": ctx or {},
        }
        return self._write_line(rec)
