"""bot3_v3v4_logger.py — Logger JSONL dedie Bot 3 v3 + v4 paper trades.

Exige par regle souveraine `.claude/rules/critical-tasks-review.md` section C
"Logs structurel JSONL dedie" : si gate filtre > 30% des trades, logger JSONL
dedie obligatoire pour tracabilite J+1.

Bot 3 v3 (continuation) filtre via state machine 4 etats (5+ ARMED → BREAKOUT
→ RETEST → CONFIRMATION). Conversion rate touch → entry ~15-20% empirique.
→ Logger dedie obligatoire.

Bot 3 v4 (data-driven) filtre via cooldown 30b + max 2/level/jour.
Conversion rate touch → entry ~30-40% empirique.
→ Logger dedie obligatoire.

Architecture : 1 instance Logger par bot (Bot3V3Logger, Bot3V4Logger).
Path output :
  - `LOGS/bot3_v3/bot3_v3_v1_YYYYMMDD.jsonl` (append-only)
  - `LOGS/bot3_v4/bot3_v4_v1_YYYYMMDD.jsonl` (append-only)

Cycle de vie d'un trade (Bot 3 v3) :
  1. log_bar_processed (chaque bar lue)
  2. log_state_transition (chaque transition state machine)
  3. log_entry_signal (CONFIRMATION_OK genere signal_id)
  4. log_trade_open (executed=True si non dry_run)
  5. log_trade_close (renseigne pnl_R + pnl_usd meme signal_id)

Cycle de vie d'un trade (Bot 3 v4) :
  1. log_bar_processed
  2. log_touch_detected (TOUCH first-time avec asym_prob)
  3. log_entry_signal (apres filters)
  4. log_trade_open
  5. log_trade_close

Schema JSONL commun :
{
  "ts": str ISO8601 UTC,
  "ts_event_ns": int epoch ns,
  "bot": str ("v3" / "v4"),
  "event": str ("BAR_PROCESSED" / "STATE_TRANSITION" / "TOUCH" / "ENTRY_SIGNAL"
                / "TRADE_OPEN" / "TRADE_CLOSE"),
  "signal_id": str (unique BOT3_V{3|4}_{SYM}_{YYYYMMDD}_{NNN}),
  "symbol": str,
  "side": str ("LONG" / "SHORT") OR null,
  "level": str (level name) OR null,
  "state_from": str OR null,    # v3 state machine
  "state_to": str OR null,
  "entry_price": float OR null,
  "sl_price": float OR null,
  "tp_price": float OR null,
  "sl_ticks": int OR null,
  "tp_mode": str ("VPOC" / "R15") OR null,    # v4
  "exit_price": float OR null,
  "exit_cause": str OR null,    # TP/SL/TIMEOUT/EOD/MANUAL
  "pnl_R": float OR null,
  "pnl_usd": float OR null,
  "duration_bars": int OR null,
  "executed": bool,             # False si dry_run
  "ctx": dict (champs extra)
}

Auteur : MIA Trading V2
  v1.0 (2026-05-24) : version initiale conforme regle souveraine logs
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
LOG_BASE_V3 = ROOT / "LOGS" / "bot3_v3"
LOG_BASE_V4 = ROOT / "LOGS" / "bot3_v4"
SCHEMA_VERSION = "bot3_v1"

# States valides pour log_state_transition (fail-loud assert, fix review iter1)
VALID_STATES = {
    "WAITING_TOUCH", "ARMED", "BREAKOUT", "WAITING_RETEST",
    "CONFIRMATION", "ENTRY", "RESET",
}


def _now_iso() -> str:
    """Timestamp UTC ISO8601."""
    return datetime.now(timezone.utc).isoformat()


def _now_ns() -> int:
    """Epoch nanoseconds UTC (precision ns via time.time_ns())."""
    return time.time_ns()


def _json_default(obj):
    """Serializer pour numpy/pandas types non-natifs.

    Pattern reutilise de bn_v4_logger.py (v1.0 valide).
    """
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
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if pd.isna(obj):
            return None
    except (ImportError, TypeError):
        pass
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def _safe_float(v) -> Optional[float]:
    """Cast float defensif (NaN/Inf -> None)."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f or f == float("inf") or f == float("-inf"):
            return None
        return round(f, 6)
    except (TypeError, ValueError):
        return None


class Bot3Logger:
    """Logger JSONL append-only thread-safe pour Bot 3 v3 ou v4.

    Usage :
        logger = Bot3Logger(bot_version="v3", symbol="NQ")
        logger.log_bar_processed(ts_event_ns=1234567890123456789, close=15000.0, ...)
        logger.log_entry_signal(signal_id="BOT3_V3_NQ_20260525_001", side="LONG", ...)
        logger.log_trade_open(signal_id=..., entry_price=15000.0, sl_price=14988.0, ...)
        ...
        logger.log_trade_close(signal_id=..., exit_price=15012.0, exit_cause="TP", pnl_R=1.0)

    Thread-safe : threading.Lock() autour de l'ecriture fichier.
    Failure mode : best-effort (catch exception, print stderr). NE pas crasher le bot.
    Auto-rotation daily : ouvre nouveau fichier au changement de date UTC.
    """

    def __init__(self, bot_version: str, symbol: str, persistance: Optional[Any] = None):
        """Args:
            persistance: optional PositionPersistance pour persist _signal_counter
                cross-restart via meta namespace (etape 2.A sprint stabilite Bot 3 v3
                09/06). Si None : comportement legacy (counter reset au restart).
        """
        assert bot_version in ("v3", "v4"), f"bot_version must be 'v3' or 'v4', got {bot_version}"
        self.bot_version = bot_version
        self.symbol = symbol
        self._lock = threading.Lock()
        self._current_date: Optional[str] = None
        self._current_path: Optional[Path] = None
        # Signal_id counter daily (defense-in-depth vs caller bugs, fix review iter1)
        self._signal_counter: int = 0
        self._counter_date: Optional[str] = None
        # Persistance cross-restart (etape 2.A 09/06 sprint stabilite Bot 3 v3)
        self._persistance: Optional[Any] = persistance

        log_base = LOG_BASE_V3 if bot_version == "v3" else LOG_BASE_V4
        log_base.mkdir(parents=True, exist_ok=True)
        self._log_base = log_base

    # ────────────────────────────────────────────────────────────────────────
    # PERSISTANCE COUNTER (etape 2.A 09/06)
    # ────────────────────────────────────────────────────────────────────────

    def set_persistance(self, persistance: Any) -> None:
        """Inject PositionPersistance apres __init__ (use case Bot 3 v3 wiring)."""
        self._persistance = persistance

    def restore_counter(self) -> bool:
        """Restaure _signal_counter depuis persistance.get_meta (best-effort).

        Format meta key : signal_counter_{symbol} = {"counter": int, "date": "YYYYMMDD"}

        Return True si counter restored, False si NEW (file absent, date diff, etc.)
        Best-effort : exception swallowed (log stderr).
        """
        if self._persistance is None:
            return False
        try:
            data = self._persistance.get_meta(f"signal_counter_{self.symbol}", {})
            if not isinstance(data, dict):
                return False
            stored_date = data.get("date")
            stored_counter = data.get("counter")
            if not stored_date or stored_counter is None:
                return False
            today_utc = datetime.now(timezone.utc).strftime("%Y%m%d")
            if stored_date != today_utc:
                return False  # date diff -> reset normal
            with self._lock:
                self._signal_counter = int(stored_counter)
                self._counter_date = today_utc
            return True
        except Exception as e:
            import sys as _sys
            print(f"[Bot3Logger.restore_counter] best-effort fail: {e}",
                  file=_sys.stderr)
            return False

    def _persist_counter(self) -> None:
        """Persiste counter courant via persistance.set_meta. Best-effort."""
        if self._persistance is None:
            return
        try:
            with self._lock:
                payload = {
                    "counter": self._signal_counter,
                    "date": self._counter_date,
                }
            self._persistance.set_meta(f"signal_counter_{self.symbol}", payload)
        except Exception as e:
            import sys as _sys
            print(f"[Bot3Logger._persist_counter] best-effort fail: {e}",
                  file=_sys.stderr)

    def _get_path(self) -> Path:
        """Auto-rotation daily : path = LOGS/bot3_v{N}/bot3_v{N}_v1_YYYYMMDD.jsonl."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        if date_str != self._current_date:
            self._current_date = date_str
            self._current_path = self._log_base / f"bot3_{self.bot_version}_v1_{date_str}.jsonl"
        return self._current_path

    def next_signal_id(self) -> str:
        """Genere un signal_id unique daily (defense-in-depth caller bugs).

        Format : BOT3_V{3|4}_{SYMBOL}_{YYYYMMDD}_{NNN}
        Reset counter au changement de date UTC.
        Thread-safe via self._lock.

        NB : le caller peut aussi generer son propre signal_id si besoin
        (ex: tracking ts_event_ns precis). Cette methode est un helper.
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        with self._lock:
            if date_str != self._counter_date:
                self._counter_date = date_str
                self._signal_counter = 0
            self._signal_counter += 1
            counter = self._signal_counter
        signal_id = f"BOT3_{self.bot_version.upper()}_{self.symbol}_{date_str}_{counter:04d}"
        # Etape 2.A 09/06 : persiste counter cross-restart (best-effort)
        self._persist_counter()
        return signal_id

    def _write(self, payload: dict) -> None:
        """Append payload JSON to current daily file. Thread-safe + fsync.

        Pattern BN V4 valide (cf bn_v4_logger.py:161-162) : flush + fsync
        garantit que les lignes JSONL sont persistees disque MEME en cas de
        crash brutal VPS. Audit J+1 fiable.
        """
        path = self._get_path()
        try:
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, default=_json_default) + "\n")
                    # Crash-protection : flush user buffer + fsync OS buffer
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        # Best-effort : fsync non supporte sur certains FS (ex: NFS)
                        # ou file descriptor closed. Pas un blocker en paper.
                        pass
        except Exception as e:
            # Failure mode : log stderr mais ne crash pas le bot
            try:
                sys.stderr.write(f"[BOT3_{self.bot_version.upper()}_LOGGER_FAIL] "
                                 f"path={path} err={e}\n")
            except Exception:
                pass  # last-resort silent fail

    # ─────────────────────────────────────────────────────────────────────
    # Logging API
    # ─────────────────────────────────────────────────────────────────────

    def log_bar_processed(
        self,
        ts_event_ns: Optional[int] = None,
        close: Optional[float] = None,
        regime_mode: Optional[str] = None,
        **ctx,
    ) -> None:
        """Log chaque bar lue par le bot (pour audit conversion rate)."""
        payload = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns if ts_event_ns is not None else _now_ns(),
            "bot": self.bot_version,
            "event": "BAR_PROCESSED",
            "symbol": self.symbol,
            "close": _safe_float(close),
            "regime_mode": regime_mode,
            "ctx": ctx or {},
        }
        self._write(payload)

    def log_state_transition(
        self,
        signal_id: str,
        state_from: str,
        state_to: str,
        level: Optional[str] = None,
        side: Optional[str] = None,
        ts_event_ns: Optional[int] = None,
        **ctx,
    ) -> None:
        """Log transition state machine (Bot 3 v3 uniquement, mais accept aussi v4 si besoin).

        Fail-loud : raise AssertionError si state_from ou state_to invalides
        (fix review iter1). Set ferme dans VALID_STATES.
        """
        assert state_from in VALID_STATES, \
            f"state_from invalid : {state_from} not in {VALID_STATES}"
        assert state_to in VALID_STATES, \
            f"state_to invalid : {state_to} not in {VALID_STATES}"
        payload = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns if ts_event_ns is not None else _now_ns(),
            "bot": self.bot_version,
            "event": "STATE_TRANSITION",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "side": side,
            "level": level,
            "state_from": state_from,
            "state_to": state_to,
            "ctx": ctx or {},
        }
        self._write(payload)

    def log_touch(
        self,
        signal_id: str,
        level: str,
        side: str,
        dist_pct: Optional[float] = None,
        asym_prob: Optional[float] = None,
        ts_event_ns: Optional[int] = None,
        **ctx,
    ) -> None:
        """Log TOUCH detected (Bot 3 v4 surtout, mais utilise par v3 aussi)."""
        payload = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns if ts_event_ns is not None else _now_ns(),
            "bot": self.bot_version,
            "event": "TOUCH",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "side": side,
            "level": level,
            "dist_pct": _safe_float(dist_pct),
            "asym_prob": _safe_float(asym_prob),
            "ctx": ctx or {},
        }
        self._write(payload)

    def log_entry_signal(
        self,
        signal_id: str,
        level: str,
        side: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        sl_ticks: int,
        tp_mode: Optional[str] = None,
        executed: bool = False,
        veto_reason: Optional[str] = None,
        ts_event_ns: Optional[int] = None,
        **ctx,
    ) -> None:
        """Log entry signal (apres state machine confirme OU touch v4 valide).

        ATTENTION (note review iter1) : si `executed=False` (veto OU dry_run),
        AUCUN `log_trade_open` ni `log_trade_close` ne sera emis pour ce
        signal_id. Le signal_id est "orphelin" cote lifecycle JSONL : c'est
        intentionnel et documente. L'audit J+1 doit grouper par signal_id et
        distinguer les `executed=True` (qui auront close) des `executed=False`
        (veto seulement).
        """
        payload = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns if ts_event_ns is not None else _now_ns(),
            "bot": self.bot_version,
            "event": "ENTRY_SIGNAL",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "side": side,
            "level": level,
            "entry_price": _safe_float(entry_price),
            "sl_price": _safe_float(sl_price),
            "tp_price": _safe_float(tp_price),
            "sl_ticks": int(sl_ticks),
            "tp_mode": tp_mode,
            "executed": bool(executed),
            "veto_reason": veto_reason,
            "ctx": ctx or {},
        }
        self._write(payload)

    def log_trade_open(
        self,
        signal_id: str,
        level: str,
        side: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        sl_ticks: int,
        qty: int,
        parent_cid: Optional[str] = None,
        tp_cid: Optional[str] = None,
        sl_cid: Optional[str] = None,
        trade_account: Optional[str] = None,
        ts_event_ns: Optional[int] = None,
        **ctx,
    ) -> None:
        """Log TRADE OPEN (bracket DTC envoye OU dry-run sans envoi)."""
        payload = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns if ts_event_ns is not None else _now_ns(),
            "bot": self.bot_version,
            "event": "TRADE_OPEN",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "side": side,
            "level": level,
            "entry_price": _safe_float(entry_price),
            "sl_price": _safe_float(sl_price),
            "tp_price": _safe_float(tp_price),
            "sl_ticks": int(sl_ticks),
            "qty": int(qty),
            "parent_cid": parent_cid,
            "tp_cid": tp_cid,
            "sl_cid": sl_cid,
            "trade_account": trade_account,
            "executed": True,
            "ctx": ctx or {},
        }
        self._write(payload)

    def log_trade_close(
        self,
        signal_id: str,
        level: str,
        side: str,
        exit_price: float,
        exit_cause: str,
        pnl_R: float,
        pnl_usd: float,
        duration_bars: int,
        ts_event_ns: Optional[int] = None,
        **ctx,
    ) -> None:
        """Log TRADE CLOSE (TP / SL / TIMEOUT / EOD / MANUAL).

        Fix 28/05 v1 (audit ml-trainer / market-analyst Jackson) :
        - `outcome` = resultat FINANCIER (WIN/LOSS/BREAKEVEN) base sur pnl_usd
        - `slippage_favorable` = flag True si SL+pnl>0 OU TP+pnl<0

        Fix 28/05 v2 (bilan P1#5 Jackson — pattern visible bilan jour persiste) :
        Le caller (paper_trader_v2) passait exit_cause="TP" MEME quand pnl_usd<0
        (slippage defavorable sur fill TP) ce qui bloquait audit forensique :
        trade #8 CASH_LOW LONG → "exit_cause=TP" + "outcome=LOSS" cohabitation
        confuse cote dashboard et grep audits.
        SEMANTIQUE NOUVELLE :
        - `exit_cause` = ALIGNE sur sign(pnl_usd) :
          * pnl>0 et caller=TP → TP (cas standard)
          * pnl<0 et caller=TP → SL (reclasse : TP fill mais perte = slip defavorable)
          * pnl>0 et caller=SL → TP (reclasse : SL fill mais gain = slip favorable)
          * pnl<0 et caller=SL → SL (cas standard)
          * TIMEOUT / EOD / MANUAL → preserve (pas mecanique TP/SL)
        - `exit_cause_mechanical` (NEW) = preserve la valeur caller pour audit DTC
          (quel ordre a effectivement fill cote broker).
        - `outcome` = resultat financier (existing, plus redondant avec exit_cause)
        - `slippage_favorable` = preserve (calcul depuis exit_cause_mechanical)

        Backward compat : `outcome` reste, `pnl_usd`/`pnl_R` invariants. Le
        dashboard paper_tracker.py:1660 compte WIN/LOSS via pnl_R signe — pas
        impacte. Le seul changement de comportement : grep `"exit_cause":"TP"`
        retournera UNIQUEMENT des wins, et `"exit_cause":"SL"` UNIQUEMENT des
        losses (audit forensique propre).
        """
        assert exit_cause in ("TP", "SL", "TIMEOUT", "EOD", "MANUAL"), \
            f"exit_cause invalid : {exit_cause}"

        pnl_safe = _safe_float(pnl_usd)

        # outcome financier (existing)
        if pnl_safe > 0.01:
            outcome = "WIN"
        elif pnl_safe < -0.01:
            outcome = "LOSS"
        else:
            outcome = "BREAKEVEN"

        # 28/05 v2 : preserve trigger mecanique caller
        exit_cause_mechanical = exit_cause

        # 28/05 v2 : reclasse exit_cause sur sign(pnl_usd) UNIQUEMENT pour TP/SL.
        # TIMEOUT / EOD / MANUAL ne sont pas des fills mecaniques TP/SL, on
        # preserve la cause d'origine (info exit_cause_mechanical redondante).
        if exit_cause in ("TP", "SL"):
            if pnl_safe > 0.01:
                exit_cause_aligned = "TP"
            elif pnl_safe < -0.01:
                exit_cause_aligned = "SL"
            else:
                # BREAKEVEN exact : preserve caller pour ne pas perdre info
                exit_cause_aligned = exit_cause
        else:
            exit_cause_aligned = exit_cause

        # slippage_favorable = mismatch entre fill mecanique et signe pnl
        slippage_favorable = (
            (exit_cause_mechanical == "SL" and pnl_safe > 0.01)
            or (exit_cause_mechanical == "TP" and pnl_safe < -0.01)
        )

        payload = {
            "ts": _now_iso(),
            "ts_event_ns": ts_event_ns if ts_event_ns is not None else _now_ns(),
            "bot": self.bot_version,
            "event": "TRADE_CLOSE",
            "signal_id": signal_id,
            "symbol": self.symbol,
            "side": side,
            "level": level,
            "exit_price": _safe_float(exit_price),
            "exit_cause": exit_cause_aligned,       # 28/05 v2 : aligne sur sign(pnl_usd)
            "exit_cause_mechanical": exit_cause_mechanical,  # NEW : trigger DTC origine
            "outcome": outcome,                     # resultat financier (existing)
            "slippage_favorable": slippage_favorable,
            "pnl_R": _safe_float(pnl_R),
            "pnl_usd": pnl_safe,
            "duration_bars": int(duration_bars),
            "ctx": ctx or {},
        }
        self._write(payload)


# Convenience aliases pour clarté call-site
class Bot3V3Logger(Bot3Logger):
    """Alias Bot3Logger(bot_version='v3', symbol='NQ')."""
    def __init__(self, symbol: str = "NQ", persistance: Optional[Any] = None):
        super().__init__(bot_version="v3", symbol=symbol, persistance=persistance)


class Bot3V4Logger(Bot3Logger):
    """Alias Bot3Logger(bot_version='v4', symbol='NQ')."""
    def __init__(self, symbol: str = "NQ", persistance: Optional[Any] = None):
        super().__init__(bot_version="v4", symbol=symbol, persistance=persistance)
