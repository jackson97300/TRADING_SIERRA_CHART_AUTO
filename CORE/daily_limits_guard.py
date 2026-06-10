"""daily_limits_guard.py — Kill switch daily PnL universel (Bot 1 + Bot 3 v3 + Bot 3 MP).

Grille souveraine Mark Douglas (cf feedback_douglas_consistency_principles.md) :
> "The traders who make the most money are the ones who trade the least
>  aggressively. Consistency beats intensity — every single time."

Implemente 3 garde-fous independants quotidiens par bot :
  1. daily_stop_loss_usd  : cumul_pnl_usd <= seuil negatif  -> BLOQUE entries
  2. daily_stop_win_usd   : cumul_pnl_usd >= seuil positif  -> BLOQUE entries (lock-in)
  3. daily_max_trades     : trade_count >= N                -> BLOQUE entries

Trace de l'incident souche (cf INCIDENT_LOG entry 08/06/2026) :
  Bot 1 SIM1 a continue de trader 4 trades supplementaires apres cumule -$1048
  alors qu'un kill switch -$200 strict aurait du le killer apres trade #2 (-$343).
  Drift catastrophique -$2010 sur 7 trades 100% LONG.

API publique :
  - DailyLimitsConfig : dataclass config (seuils + kill switch global)
  - DailyLimitsGuard  : instance par bot (track cumul, check, persist)
  - load_config_from_env(prefix=...) : helper override env vars

Pattern conception :
  - Module pur (zero dependance autre que stdlib + logging_v2)
  - Pas de coupling avec mia_paper_trader / databento_paper_trader_v2 (injecte)
  - Persistance JSON par jour (bot_id, date) -> resilience crash
  - Reset auto via rollover_if_needed(new_date) appele par le caller au rollover
  - Tests pytest dedies : CORE/tests/test_daily_limits.py
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

# Systeme logs V2 (defense en profondeur : si non dispo, fonctionnel mais silencieux)
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("daily_limits_guard", process="risk")
except Exception:
    _v2log = None


# -----------------------------------------------------------------------------
# Config (centralisee, env vars override)
# -----------------------------------------------------------------------------

@dataclass
class DailyLimitsConfig:
    """Config DailyLimitsGuard — seuils + kill switch master.

    Defaults Mark Douglas (04/06) :
      - daily_stop_loss_usd = -200.0
      - daily_stop_win_usd  = +150.0
      - daily_max_trades    = 5
      - enabled             = True (kill switch master)
      - stop_win_enabled    = True
      - max_trades_enabled  = True
    """
    daily_stop_loss_usd: float = -200.0
    daily_stop_win_usd: float = 150.0
    daily_max_trades: int = 5
    enabled: bool = True
    stop_win_enabled: bool = True
    max_trades_enabled: bool = True

    def __post_init__(self) -> None:
        # Validation defensive : stop_loss doit etre negatif, stop_win positif.
        if self.daily_stop_loss_usd > 0:
            raise ValueError(
                f"daily_stop_loss_usd doit etre <= 0, recu {self.daily_stop_loss_usd}"
            )
        if self.daily_stop_win_usd < 0:
            raise ValueError(
                f"daily_stop_win_usd doit etre >= 0, recu {self.daily_stop_win_usd}"
            )
        if self.daily_max_trades < 0:
            raise ValueError(
                f"daily_max_trades doit etre >= 0, recu {self.daily_max_trades}"
            )


def load_config_from_env(
    prefix: str = "MIA",
    bot_id: Optional[str] = None,
) -> DailyLimitsConfig:
    """Construit DailyLimitsConfig depuis env vars (override defaults).

    Vars supportees (toutes optionnelles, cascade lookup) :
      Niveau 1 - per-bot (si bot_id fourni) :
        - {prefix}_{BOT_ID}_DAILY_LIMITS_ENABLED
        - {prefix}_{BOT_ID}_DAILY_STOP_LOSS
        - {prefix}_{BOT_ID}_DAILY_STOP_WIN
        - {prefix}_{BOT_ID}_DAILY_STOP_WIN_ENABLED
        - {prefix}_{BOT_ID}_DAILY_MAX_TRADES
        - {prefix}_{BOT_ID}_DAILY_MAX_TRADES_ENABLED
      Niveau 2 - global (fallback si per-bot absent) :
        - {prefix}_DAILY_LIMITS_ENABLED    (1/0, default 1)
        - {prefix}_DAILY_STOP_LOSS         (float USD, default -200)
        - {prefix}_DAILY_STOP_WIN          (float USD, default 150)
        - {prefix}_DAILY_STOP_WIN_ENABLED  (1/0, default 1)
        - {prefix}_DAILY_MAX_TRADES        (int, default 5)
        - {prefix}_DAILY_MAX_TRADES_ENABLED (1/0, default 1)

    09/06 SOIR DATA_COLLECTION mode (Jackson) : permet override per-bot pour
    collecte rapide N=60 trades sprint Phase 3 :
      MIA_BOT3_V3_DAILY_STOP_LOSS=-1500
      MIA_DAILY_STOP_WIN_ENABLED=0
      MIA_DAILY_MAX_TRADES_ENABLED=0

    En cas de parse error -> default + log warning V2.
    """
    def _cascade_get(suffix: str, getter, default):
        """Cascade : per-bot > global > default."""
        if bot_id:
            bot_key = f"{prefix}_{bot_id.upper()}_DAILY_{suffix}"
            raw = os.environ.get(bot_key)
            if raw is not None and raw != "":
                return getter(bot_key, default)
        return getter(f"{prefix}_DAILY_{suffix}", default)

    def _get_float(key: str, default: float) -> float:
        raw = os.environ.get(key)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            if _v2log:
                try:
                    _v2log.emit("GENERIC_MAJEUR",
                                msg=f"daily_limits: env var {key}={raw!r} invalide -> default {default}")
                except Exception:
                    pass
            return default

    def _get_int(key: str, default: int) -> int:
        raw = os.environ.get(key)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            if _v2log:
                try:
                    _v2log.emit("GENERIC_MAJEUR",
                                msg=f"daily_limits: env var {key}={raw!r} invalide -> default {default}")
                except Exception:
                    pass
            return default

    def _get_bool(key: str, default: bool) -> bool:
        raw = os.environ.get(key)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    return DailyLimitsConfig(
        daily_stop_loss_usd=_cascade_get("STOP_LOSS", _get_float, -200.0),
        daily_stop_win_usd=_cascade_get("STOP_WIN", _get_float, 150.0),
        daily_max_trades=_cascade_get("MAX_TRADES", _get_int, 5),
        enabled=_cascade_get("LIMITS_ENABLED", _get_bool, True),
        stop_win_enabled=_cascade_get("STOP_WIN_ENABLED", _get_bool, True),
        max_trades_enabled=_cascade_get("MAX_TRADES_ENABLED", _get_bool, True),
    )


# -----------------------------------------------------------------------------
# State persistence
# -----------------------------------------------------------------------------

@dataclass
class _DailyState:
    """State runtime serialise dans {date}_daily_state_{bot_id}.json."""
    bot_id: str
    date_str: str
    cumul_pnl_usd: float = 0.0
    trade_count: int = 0
    stop_loss_triggered: bool = False
    stop_win_triggered: bool = False
    max_trades_triggered: bool = False
    last_update_ts: float = 0.0


# -----------------------------------------------------------------------------
# Guard
# -----------------------------------------------------------------------------

class DailyLimitsGuard:
    """Kill switch daily PnL universel.

    Cycle de vie :
      __init__(bot_id, config, state_dir) -> load state du jour (ou cree neuf)
      check_allow(symbol) -> (True, "") ou (False, reason)
      on_trade_close(pnl_usd) -> update cumul + trade_count + persist
      rollover_if_needed(new_date_str) -> reset si date change
      reset() -> reset manuel (rare, debug)

    Thread safety : RLock interne. Le caller peut appeler depuis n'importe
    quel thread (incl. DTC daemon thread pour on_trade_close).
    """

    REASON_STOP_LOSS = "daily_stop_loss"
    REASON_STOP_WIN = "daily_stop_win"
    REASON_MAX_TRADES = "daily_max_trades"
    REASON_DISABLED = "daily_limits_disabled"  # debug only, jamais bloquant

    def __init__(
        self,
        bot_id: str,
        config: DailyLimitsConfig,
        state_dir: str,
        date_str: str,
    ) -> None:
        if not bot_id:
            raise ValueError("bot_id obligatoire (ex: 'bot1', 'bot3_v3', 'bot3_mp')")
        if not date_str:
            raise ValueError("date_str obligatoire (format YYYYMMDD)")
        self.bot_id = bot_id
        self.config = config
        self.state_dir = state_dir
        self._lock = threading.RLock()
        os.makedirs(self.state_dir, exist_ok=True)
        self._state = _DailyState(bot_id=bot_id, date_str=date_str)
        self._load_or_init(date_str)

    # ---------------- File path helpers ----------------

    def _state_file(self, date_str: str) -> str:
        return os.path.join(
            self.state_dir, f"{date_str}_daily_state_{self.bot_id}.json"
        )

    # ---------------- Load / persist ----------------

    def _load_or_init(self, date_str: str) -> None:
        """Charge state existant ou cree neuf (boot)."""
        fp = self._state_file(date_str)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Validation : doit matcher bot_id + date_str
                if data.get("bot_id") == self.bot_id and data.get("date_str") == date_str:
                    self._state = _DailyState(
                        bot_id=self.bot_id,
                        date_str=date_str,
                        cumul_pnl_usd=float(data.get("cumul_pnl_usd", 0.0)),
                        trade_count=int(data.get("trade_count", 0)),
                        stop_loss_triggered=bool(data.get("stop_loss_triggered", False)),
                        stop_win_triggered=bool(data.get("stop_win_triggered", False)),
                        max_trades_triggered=bool(data.get("max_trades_triggered", False)),
                        last_update_ts=float(data.get("last_update_ts", 0.0)),
                    )
                    return
            except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
                if _v2log:
                    try:
                        _v2log.emit(
                            "GENERIC_MAJEUR",
                            msg=f"daily_limits: corruption state file {fp} : {e!r} -> reset",
                        )
                    except Exception:
                        pass
        # Sinon : state neuf
        self._state = _DailyState(bot_id=self.bot_id, date_str=date_str)
        self._save_locked()

    def _save_locked(self) -> None:
        """Persist state (caller doit detenir le lock)."""
        fp = self._state_file(self._state.date_str)
        tmp = fp + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self._state), f, ensure_ascii=False, indent=2)
            os.replace(tmp, fp)
        except OSError as e:
            if _v2log:
                try:
                    _v2log.emit(
                        "GENERIC_MAJEUR",
                        msg=f"daily_limits: persist state {fp} echec : {e!r}",
                    )
                except Exception:
                    pass

    # ---------------- Rebuild from trades file (cold start fallback) ----------------

    def rebuild_from_trades(self, pnl_usd_iter) -> None:
        """Reconstruit cumul + trade_count depuis un iterable de pnl_usd.

        Utile au boot si state file absent mais trades fichier present
        (resilience crash). Le caller passe par exemple les `pnl_usd` des
        trades du jour deja loggues dans `{date}_trades.jsonl`.
        """
        with self._lock:
            total = 0.0
            count = 0
            for pnl in pnl_usd_iter:
                if pnl is None:
                    # Skip timeouts / RECOVERED qui n'ont pas de pnl fiable
                    continue
                try:
                    total += float(pnl)
                    count += 1
                except (TypeError, ValueError):
                    continue
            self._state.cumul_pnl_usd = total
            self._state.trade_count = count
            # Re-evaluer les triggers : si on est deja au-dela des seuils, marquer.
            cfg = self.config
            self._state.stop_loss_triggered = (
                total <= cfg.daily_stop_loss_usd
            )
            self._state.stop_win_triggered = (
                cfg.stop_win_enabled and total >= cfg.daily_stop_win_usd
            )
            self._state.max_trades_triggered = (
                cfg.max_trades_enabled and count >= cfg.daily_max_trades
            )
            import time as _t
            self._state.last_update_ts = _t.time()
            self._save_locked()
            if _v2log:
                try:
                    _v2log.emit(
                        "DAILY_LIMITS_REBUILT",
                        bot_id=self.bot_id, date=self._state.date_str,
                        cumul_usd=round(total, 2), trades=count,
                        stop_loss_triggered=self._state.stop_loss_triggered,
                        stop_win_triggered=self._state.stop_win_triggered,
                        max_trades_triggered=self._state.max_trades_triggered,
                    )
                except Exception:
                    pass

    # ---------------- Core API ----------------

    def check_allow(self, symbol: str) -> Tuple[bool, str]:
        """Verifie si une nouvelle entry est autorisee.

        Returns:
            (True, "")  si autorise
            (False, reason)  si bloque (reason = REASON_STOP_LOSS, etc.)

        Ne mute PAS le state (read-only check). Emit codes log V2 sur trigger.
        Rate limit anti-spam : 1 emit par (symbol, reason) par 60s.
        """
        with self._lock:
            cfg = self.config

            # Kill switch master : si disabled -> tout passe (log INFO une fois)
            if not cfg.enabled:
                return True, ""

            cumul = self._state.cumul_pnl_usd
            count = self._state.trade_count

            # Ordre check : stop_loss (CRITIQUE) > max_trades > stop_win
            # Logique : si on a perdu, on coupe avant tout. Si on a fait trop de
            # trades, on coupe avant le profit-lock. Sinon stop_win.

            if cumul <= cfg.daily_stop_loss_usd:
                self._emit_block_throttled(
                    code="GATE_DAILY_STOP_LOSS_TRIGGERED",
                    symbol=symbol,
                    cumul_usd=cumul,
                    limit_usd=cfg.daily_stop_loss_usd,
                    trades=count,
                )
                return False, self.REASON_STOP_LOSS

            if cfg.max_trades_enabled and count >= cfg.daily_max_trades:
                self._emit_block_throttled(
                    code="GATE_DAILY_MAX_TRADES_TRIGGERED",
                    symbol=symbol,
                    cumul_usd=cumul,
                    trades=count,
                    limit=cfg.daily_max_trades,
                )
                return False, self.REASON_MAX_TRADES

            if cfg.stop_win_enabled and cumul >= cfg.daily_stop_win_usd:
                self._emit_block_throttled(
                    code="GATE_DAILY_STOP_WIN_TRIGGERED",
                    symbol=symbol,
                    cumul_usd=cumul,
                    limit_usd=cfg.daily_stop_win_usd,
                    trades=count,
                )
                return False, self.REASON_STOP_WIN

            return True, ""

    def on_trade_open(self) -> None:
        """Hook a appeler des qu'un trade s'OUVRE (avant fill confirme).

        09/06 fix Mark Douglas Phase 2 sprint stabilite Bot 3 v3 :
        compte le trade a l'INTENT (open) plutot qu'au CLOSE. Garantit
        respect strict max_trades meme si flatten externe / OCO orphan /
        crash sans close propre (cas observes 09/06 matin Bot 3 v3 :
        trade_count restait a 0 malgre 2 OPEN car aucun fill close DTC).

        Mark Douglas "5 trades/jour" = 5 INTENTS pas 5 closes propres.

        Increment trade_count uniquement (pas cumul - le cumul reste lie
        au close via on_trade_close pour PnL realise). Persist + verifie
        trigger max_trades.
        """
        with self._lock:
            cfg = self.config
            import time as _t
            self._state.last_update_ts = _t.time()
            self._state.trade_count = self._state.trade_count + 1
            new_count = self._state.trade_count
            # Verif trigger max_trades (one-shot)
            crossed_max = (
                cfg.max_trades_enabled
                and not self._state.max_trades_triggered
                and new_count >= cfg.daily_max_trades
            )
            if crossed_max:
                self._state.max_trades_triggered = True
            # Persist
            self._save_locked()

        # Emit logs HORS lock apres save (state coherent)
        if _v2log:
            try:
                _v2log.emit(
                    "DAILY_PNL_UPDATE",
                    bot_id=self.bot_id, date=self._state.date_str,
                    cumul_usd=round(self._state.cumul_pnl_usd, 2),
                    delta_usd=0.0,  # open = pas de delta cumul
                    trades=new_count,
                )
            except Exception:
                pass
            if crossed_max:
                try:
                    _v2log.emit(
                        "GATE_DAILY_STOP_MAX_TRADES_TRIGGERED",
                        bot_id=self.bot_id, date=self._state.date_str,
                        trades=new_count, limit=cfg.daily_max_trades,
                        source="on_trade_open",
                    )
                except Exception:
                    pass

    def on_trade_close(self, pnl_usd: Optional[float],
                       increment_count: bool = True) -> None:
        """Hook a appeler apres chaque close de trade.

        Update cumul + trade_count (optionnel) + persist. Emit codes log
        update + trigger si seuil franchi (one-shot, pas en boucle).
        Args:
            pnl_usd : pnl en USD du trade ferme. None = timeout/recovered,
                      on incremente trade_count mais pas cumul.
            increment_count : 09/06 fix Mark Douglas Phase 2. Si False,
                      ne PAS incrementer trade_count (= caller a deja
                      appele on_trade_open() au moment du OPEN). Default
                      True = legacy compat 08/06.
        """
        with self._lock:
            cfg = self.config
            prev_cumul = self._state.cumul_pnl_usd
            prev_count = self._state.trade_count
            import time as _t
            self._state.last_update_ts = _t.time()
            # 09/06 fix double-comptage : skip increment si caller a deja open()
            if increment_count:
                self._state.trade_count = prev_count + 1
            if pnl_usd is not None:
                try:
                    self._state.cumul_pnl_usd = prev_cumul + float(pnl_usd)
                except (TypeError, ValueError):
                    # Garde le cumul si pnl_usd parse fail
                    pass
            new_cumul = self._state.cumul_pnl_usd
            new_count = self._state.trade_count

            # Detection franchissement seuil (one-shot Discord alert)
            crossed_loss = (
                not self._state.stop_loss_triggered
                and new_cumul <= cfg.daily_stop_loss_usd
            )
            crossed_win = (
                cfg.stop_win_enabled
                and not self._state.stop_win_triggered
                and new_cumul >= cfg.daily_stop_win_usd
            )
            crossed_max = (
                cfg.max_trades_enabled
                and not self._state.max_trades_triggered
                and new_count >= cfg.daily_max_trades
            )

            if crossed_loss:
                self._state.stop_loss_triggered = True
            if crossed_win:
                self._state.stop_win_triggered = True
            if crossed_max:
                self._state.max_trades_triggered = True

            self._save_locked()

            # Emit logs hors lock seulement APRES save (state coherent)
            if _v2log:
                try:
                    _v2log.emit(
                        "DAILY_PNL_UPDATE",
                        bot_id=self.bot_id, date=self._state.date_str,
                        cumul_usd=round(new_cumul, 2),
                        delta_usd=round((new_cumul - prev_cumul), 2),
                        trades=new_count,
                    )
                except Exception:
                    pass

                if crossed_loss:
                    try:
                        _v2log.emit(
                            "GATE_DAILY_STOP_LOSS_TRIGGERED",
                            bot_id=self.bot_id, sym="*",
                            cumul_usd=round(new_cumul, 2),
                            limit_usd=cfg.daily_stop_loss_usd,
                            trades=new_count,
                        )
                    except Exception:
                        pass
                if crossed_max:
                    try:
                        _v2log.emit(
                            "GATE_DAILY_MAX_TRADES_TRIGGERED",
                            bot_id=self.bot_id, sym="*",
                            cumul_usd=round(new_cumul, 2),
                            trades=new_count, limit=cfg.daily_max_trades,
                        )
                    except Exception:
                        pass
                if crossed_win:
                    try:
                        _v2log.emit(
                            "GATE_DAILY_STOP_WIN_TRIGGERED",
                            bot_id=self.bot_id, sym="*",
                            cumul_usd=round(new_cumul, 2),
                            limit_usd=cfg.daily_stop_win_usd,
                            trades=new_count,
                        )
                    except Exception:
                        pass

    def rollover_if_needed(self, new_date_str: str) -> bool:
        """Reset le state si la date change (minuit UTC ou CME day rollover).

        Returns True si rollover effectue, False sinon.
        """
        with self._lock:
            if new_date_str == self._state.date_str:
                return False
            prev_date = self._state.date_str
            prev_cumul = self._state.cumul_pnl_usd
            prev_count = self._state.trade_count
            self._state = _DailyState(bot_id=self.bot_id, date_str=new_date_str)
            self._save_locked()
            if _v2log:
                try:
                    _v2log.emit(
                        "DAILY_LIMITS_RESET",
                        bot_id=self.bot_id, prev_date=prev_date,
                        new_date=new_date_str,
                        prev_cumul_usd=round(prev_cumul, 2),
                        prev_trades=prev_count,
                    )
                except Exception:
                    pass
            return True

    def reset(self) -> None:
        """Reset manuel (debug, tests). Garde la meme date_str."""
        with self._lock:
            d = self._state.date_str
            self._state = _DailyState(bot_id=self.bot_id, date_str=d)
            self._save_locked()

    # ---------------- Snapshot pour dashboard / state.json ----------------

    def snapshot(self) -> Dict[str, object]:
        """Snapshot read-only pour exposition dashboard / state.json."""
        with self._lock:
            cfg = self.config
            return {
                "bot_id": self.bot_id,
                "date": self._state.date_str,
                "enabled": cfg.enabled,
                "cumul_pnl_usd": round(self._state.cumul_pnl_usd, 2),
                "trade_count": self._state.trade_count,
                "stop_loss_usd": cfg.daily_stop_loss_usd,
                "stop_loss_triggered": self._state.stop_loss_triggered,
                "stop_win_usd": cfg.daily_stop_win_usd,
                "stop_win_enabled": cfg.stop_win_enabled,
                "stop_win_triggered": self._state.stop_win_triggered,
                "max_trades": cfg.daily_max_trades,
                "max_trades_enabled": cfg.max_trades_enabled,
                "max_trades_triggered": self._state.max_trades_triggered,
                "last_update_ts": self._state.last_update_ts,
            }

    # ---------------- Private helpers ----------------

    # Anti-spam : 60s entre 2 emits du meme (symbol, reason).
    _EMIT_THROTTLE_SEC = 60.0

    def _emit_block_throttled(self, code: str, symbol: str, **ctx) -> None:
        """Emit log V2 avec throttle 60s par (symbol, code). Caller doit detenir le lock.

        Empeche spam logs quand le bot tourne en boucle sur un meme signal bloque.
        """
        if not _v2log:
            return
        # Lazy init throttle dict
        if not hasattr(self, "_emit_last_ts"):
            self._emit_last_ts: Dict[Tuple[str, str], float] = {}
        import time as _t
        key = (symbol or "*", code)
        now = _t.time()
        last = self._emit_last_ts.get(key, 0.0)
        if (now - last) < self._EMIT_THROTTLE_SEC:
            return
        self._emit_last_ts[key] = now
        try:
            _v2log.emit(code, bot_id=self.bot_id, sym=symbol or "*", **ctx)
        except Exception:
            pass
