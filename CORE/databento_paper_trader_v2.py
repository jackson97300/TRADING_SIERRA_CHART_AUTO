"""databento_paper_trader_v2.py — Bot 2 V2 PAPER_TRADE actif Sim2 (V4 Databento).

Created : 2026-05-02 dimanche soir.
Mode    : PAPER_TRADE actif des lundi 13:30 UTC (ouverture RTH).
Service nssm : MIA-DataBento-Paper-V2 (nouveau, parallel a V1).

ARCHITECTURE (vs V1) :
  V1 ConsensusScorer (9 groupes ponderes empiriques) → REMPLACE
  V2 SetupEngine (11 setups validés empiriquement edge_discovery 1 an)

GARDE-FOUS :
  - Risk isolé par symbole (NQ -$900 / ES -$900) + global -$1800
  - Veto ATR extreme (atr_14m_pct > 0.005)
  - Anti double-trigger (last_bar_ts par symbole)
  - 1 position max par symbole (NQ + ES simultanés OK)
  - RTH-only (is_in_us_cash == 1)

TRAILING STOP (Option B Jackson) :
  - SL fixe initial (200t NQ / 80t ES)
  - Trailing activation 80t NQ / 32t ES
  - Trailing distance 60t NQ / 24t ES
  - Timeout 40min Phase 1
  - TP cap securite 500t NQ / 200t ES

CRITIQUE : cancel+replace SL DTC quand trailing_pending_broker_update == True
  (anti-reproduction incident TR40_NQ 01/05/2026).

Usage :
  python -X utf8 CORE/databento_paper_trader_v2.py                # paper Sim2
  python -X utf8 CORE/databento_paper_trader_v2.py --dry-run      # log only, pas DTC
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

from setup_engine import (
    SetupEngine,
    RiskManager,
    SetupStatsTracker,
    Signal,
    Position,
    make_position,
    update_mfe_mae,
    acknowledge_broker_sl_update,
    check_exit_condition,
    log_trade_entry,
    log_trade_exit,
    compute_seconds_until_timeout,
    compute_session_label,
    TRAILING_CONFIG,
    RISK_PER_SYMBOL,
    GLOBAL_KILL_SWITCH_DAILY_PNL,
    PHASE_1_FREE_RUN,
    TRADING_WINDOW_START_UTC,
    TRADING_WINDOW_END_UTC,
    TICK_SIZE,
)

# ─── Bot 3 MP (Market Profile, in-process, Sim1 isole, 03/05/2026) ─────
from bot3_mp_engine import Bot3Engine, reason_to_log_code
from bot3_config import (
    BOT3_OBSERVE_ONLY,
    BOT3_ENABLE_TIER2,
    BOT3_ENABLE_TIER3,
    BOT3_TRADE_REJECTIONS,
    BOT3_TRADE_BREAKOUTS,
)
from bot3_level_definitions import (
    get_active_levels,
    get_level_baseline_pf,
    get_level_baseline_rej,
)


def _bot3_count_active_levels() -> int:
    """Count moyen de niveaux actifs entre NQ et ES (filtres symbole appliques).

    FIX M-5 (review code-reviewer 03/05) : remplace l'ancien hardcode
    `5 + 5 + 3` qui ignorait CUR_VPOC ES-only, PVAL NQ-only, Tier 3 NQ-only/ES-only.
    Inclut les TIER2_LEVELS_NEUTRAL en Phase 1 OBSERVE pour log live.
    """
    enable_neutral = BOT3_OBSERVE_ONLY  # Phase 1 = log NEUTRAL aussi
    n_nq = len(get_active_levels(
        enable_tier2=BOT3_ENABLE_TIER2,
        enable_tier3=BOT3_ENABLE_TIER3,
        symbol="NQ",
        enable_tier2_neutral=enable_neutral,
    ))
    n_es = len(get_active_levels(
        enable_tier2=BOT3_ENABLE_TIER2,
        enable_tier3=BOT3_ENABLE_TIER3,
        symbol="ES",
        enable_tier2_neutral=enable_neutral,
    ))
    return (n_nq + n_es) // 2

try:
    from constants import get_cme_trading_day
except ImportError:
    from CORE.constants import get_cme_trading_day

# Logging V2
try:
    from logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("databento_paper_v2", process="paper_v2")
except ImportError:
    _v2log = None


def _emit(code: str, **ctx):
    """Emit V2 log avec fail-loud stderr."""
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception as e:
            print(f"[EMIT_FAIL_V2] code={code} err={type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)


# DTC (optionnel : --dry-run desactive)
try:
    from dtc_connector import DTCConnector, BUY as DTC_BUY, SELL as DTC_SELL
    from bot_config import DTCConfig, INSTRUMENTS as BOT_INSTRUMENTS
    _DTC_OK = True
except ImportError as _e:
    print(f"[WARN] DTC import failed : {_e}")
    _DTC_OK = False
    DTC_BUY, DTC_SELL = 1, 2


# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

DATASET_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"
STATE_FILE = ROOT / "DATA" / "PAPER_TRADES" / "databento_paper_v2_state.json"
STATE_FILE_BOT3 = ROOT / "DATA" / "PAPER_TRADES" / "databento_paper_v3_state.json"
STOP_FLAG_GLOBAL = ROOT / "DATA" / "BOT_CONTROL" / "STOP.flag"
STOP_FLAG_LOCAL = ROOT / "DATA" / "BOT_CONTROL" / "STOP_DATABENTO_V2.flag"

POLL_INTERVAL_SEC = 30  # poll loop 30s

# Watchdog freshness (mêmes seuils que V1)
DATA_FRESH_THR_SEC = 600
DATA_WARN_THR_SEC = 1500
DATA_CRIT_THR_SEC = 2700

TRADE_ACCOUNT = os.environ.get("MIA_TRADE_ACCOUNT", "Sim2")

SYMBOLS = ["NQ", "ES"]
SYMBOL_TO_CONTRACT = {"NQ": "NQM26-CME", "ES": "ESM26-CME"}


# ═══════════════════════════════════════════════════════════════════
# DATA LOADER (V4 enriched parquet)
# ═══════════════════════════════════════════════════════════════════

def load_last_bar(symbol: str) -> Optional[pd.Series]:
    """Charge la derniere barre V4 enrichie pour le symbole.

    Cherche dans le mois courant, fallback mois precedent.
    """
    now_utc = datetime.now(timezone.utc)
    candidates = []
    for offset in (0, -1):
        m = now_utc.month + offset
        y = now_utc.year
        if m < 1:
            m += 12
            y -= 1
        elif m > 12:
            m -= 12
            y += 1
        fp = DATASET_ROOT / f"symbol={symbol}.c.0" / f"year={y}" / f"month={m:02d}" / "data.parquet"
        if fp.exists():
            candidates.append(fp)
    if not candidates:
        return None
    try:
        df = pd.read_parquet(candidates[0])
        if df.empty:
            return None
        df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts_event"]).sort_values("ts_event")
        return df.iloc[-1]
    except Exception as e:
        _emit("BAR_LOAD_NONE", sym=symbol, reason=f"parquet_read_fail: {e}")
        return None


def bar_age_seconds(bar: pd.Series) -> float:
    """Age de la barre en secondes."""
    try:
        ts = pd.to_datetime(bar["ts_event"], utc=True)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        return (datetime.now(timezone.utc) - ts.to_pydatetime()).total_seconds()
    except Exception:
        return 999999.0


# ═══════════════════════════════════════════════════════════════════
# BOT V2
# ═══════════════════════════════════════════════════════════════════

class Bot3RiskManager:
    """Cooldown + circuit breaker Bot 3 (aligne Bot 1 + Bot 2).

    Pattern :
      - last_close_time[sym] : timestamp dernier close (cooldown 15 min anti re-entry)
      - consecutive_sl[sym] : compteur SL consec (reset sur win)
      - breaker_until[sym] : timestamp fin pause apres 3 SL consec (60 min)

    Source : 07/05 incident 2 SL en 4 min sans cooldown -> -$801 NQ Bot 3.
    Reference : Bot 2 RiskManager (CORE/databento_paper_trader.py:438-470).
    """

    def __init__(self):
        try:
            from bot3_config import (COOLDOWN_BOT3_MIN, MAX_CONSECUTIVE_SL_BOT3,
                                     PAUSE_AFTER_BREAKER_BOT3_MIN)
        except ImportError:
            from CORE.bot3_config import (COOLDOWN_BOT3_MIN, MAX_CONSECUTIVE_SL_BOT3,
                                          PAUSE_AFTER_BREAKER_BOT3_MIN)
        self.cooldown_min = COOLDOWN_BOT3_MIN
        self.max_consec_sl = MAX_CONSECUTIVE_SL_BOT3
        self.pause_breaker_min = PAUSE_AFTER_BREAKER_BOT3_MIN
        self.last_close_time: dict[str, datetime] = {}
        self.consecutive_sl: dict[str, int] = {"NQ": 0, "ES": 0}
        self.breaker_until: dict[str, Optional[datetime]] = {"NQ": None, "ES": None}

    def to_dict(self) -> dict:
        """11/05 J3 FIX BUG COOLDOWN : serialise state pour persistance JSON.

        Cause root incident 11/05 : 2 trades en violation cooldown 15min car
        Bot 3 process restart EFFACE last_close_time={} → can_trade() retourne OK.
        Fix : persister state dans STATE_FILE_BOT3 + restore au boot.
        """
        return {
            "last_close_time": {
                sym: ts.isoformat() if ts else None
                for sym, ts in self.last_close_time.items()
            },
            "consecutive_sl": dict(self.consecutive_sl),
            "breaker_until": {
                sym: (ts.isoformat() if ts else None)
                for sym, ts in self.breaker_until.items()
            },
        }

    def restore_from_dict(self, state: dict) -> None:
        """11/05 J3 FIX BUG COOLDOWN : restore state depuis JSON state file."""
        if not state:
            return
        from datetime import datetime as _dt
        for sym, ts_iso in (state.get("last_close_time") or {}).items():
            if ts_iso:
                try:
                    self.last_close_time[sym] = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
        for sym, cnt in (state.get("consecutive_sl") or {}).items():
            self.consecutive_sl[sym] = int(cnt)
        for sym, ts_iso in (state.get("breaker_until") or {}).items():
            if ts_iso:
                try:
                    self.breaker_until[sym] = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

    def can_trade(self, symbol: str) -> tuple[bool, str]:
        """Retourne (allow, reason). Reason en MAJ codes Bot 1+2."""
        now = datetime.now(timezone.utc)
        last = self.last_close_time.get(symbol)
        if last and (now - last) < timedelta(minutes=self.cooldown_min):
            remaining = self.cooldown_min - (now - last).total_seconds() / 60.0
            return False, f"COOLDOWN_{self.cooldown_min}MIN_REMAINING_{remaining:.1f}MIN"
        until = self.breaker_until.get(symbol)
        if until and now < until:
            remaining = (until - now).total_seconds() / 60.0
            return False, f"CIRCUIT_BREAKER_REMAINING_{remaining:.1f}MIN"
        return True, "OK"

    def on_trade_close(self, symbol: str, pnl_ticks: Optional[float]) -> dict:
        """Update state apres fermeture trade.

        - last_close_time = now
        - Si pnl_ticks < 0 : consecutive_sl++. Si >= max -> breaker_until = now + pause.
        - Si pnl_ticks >= 0 : reset consecutive_sl = 0.
        - Si pnl_ticks is None (pnl_estimated/timeout) : NE PAS incrementer consec_sl
          mais quand meme update last_close_time pour cooldown 15min.

        Returns dict diagnostic pour log/audit.
        """
        now = datetime.now(timezone.utc)
        self.last_close_time[symbol] = now
        breaker_triggered = False
        if pnl_ticks is None:
            # Cas timeout/recovered : pnl inconnu, pas de signal SL fiable
            return {
                "consecutive_sl": self.consecutive_sl.get(symbol, 0),
                "breaker_triggered": False,
                "cooldown_until": (now + timedelta(minutes=self.cooldown_min)).isoformat(),
                "pnl_ticks": None,
            }
        if pnl_ticks < 0:
            self.consecutive_sl[symbol] = self.consecutive_sl.get(symbol, 0) + 1
            if self.consecutive_sl[symbol] >= self.max_consec_sl:
                self.breaker_until[symbol] = now + timedelta(minutes=self.pause_breaker_min)
                breaker_triggered = True
        else:
            self.consecutive_sl[symbol] = 0
            self.breaker_until[symbol] = None  # reset breaker au 1er win
        return {
            "consecutive_sl": self.consecutive_sl.get(symbol, 0),
            "breaker_triggered": breaker_triggered,
            "breaker_until": self.breaker_until[symbol].isoformat() if self.breaker_until.get(symbol) else None,
            "cooldown_until": (now + timedelta(minutes=self.cooldown_min)).isoformat(),
            "pnl_ticks": float(pnl_ticks),
        }


class DatabentoPaperTraderV2:
    """Bot 2 V2 — SetupEngine + RiskManager isole + Trailing avec broker ack."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.setup_engine = SetupEngine()
        self.risk = RiskManager()
        # Tracker reussite par setup (Jackson 02/05) — cumul session
        self.setup_stats = SetupStatsTracker()
        # Position state par symbole : 1 max chacun
        self.positions: dict[str, Optional[Position]] = {"NQ": None, "ES": None}
        # DTC bracket IDs par symbole (pour cancel/replace)
        self.bracket_ids: dict[str, dict] = {"NQ": {}, "ES": {}}

        # ─── Bot 3 MP (in-process, isole, 03/05) ──────────────────────
        # Bot 3 partage le poll loop et le DTC connector (Sim2 partagee
        # actuellement — sera Sim1 quand Jackson confirmera le port DTC).
        # Phase 1 OBSERVE_ONLY : Bot 3 logge les contacts mais ne trade pas.
        self.bot3_engine = Bot3Engine()
        # Bot 3 stats : par niveau, isole de setup_stats
        self.bot3_level_stats: dict[str, dict] = {}    # {level_name: {n_contacts, n_go, n_skip, ...}}
        self.bot3_recent_decisions: list = []           # ring buffer 50 dernieres
        self.bot3_counters_today = {
            "n_contacts": {"NQ": 0, "ES": 0},
            "n_go": {"NQ": 0, "ES": 0},
            "n_skip": {"NQ": 0, "ES": 0},
            "n_veto": {"NQ": 0, "ES": 0},
        }
        self.bot3_trading_day: Optional[str] = None
        # Positions Bot 3 (isolees de self.positions Bot 2). 1 max par symbole.
        self._bot3_positions: dict[str, Optional[dict]] = {"NQ": None, "ES": None}
        # FIX R1 (Jackson 03/05 soir) : pattern Bot 1 — track CIDs Bot 3 pour routing fills.
        # cid → {"sym", "type" in {"parent","tp","sl"}, "signal_id"}
        self._bot3_cid_index: dict[str, dict] = {}
        # Anti double-close (Bot 1 _pos_lock equivalent — single thread Python OK ici)
        import threading
        self._bot3_pos_lock = threading.Lock()
        # 11/05 Jackson "met a jour les log on dois pouvoir suivre tout les blocage"
        # Throttle emit par (sym, code) — evite spam log cycle 1s × position 30min = 1800 lignes.
        self._bot3_emit_throttle: dict[tuple[str, str], float] = {}
        # 07/05 Jackson directive "ANALYSE LE COOLDOWN DES AUTRES BOT ET APLIQUE LE MEME"
        # Cooldown 15min post-close + circuit breaker 3 SL → 60min pause (par symbole).
        # Aligne Bot 1 (mia_paper_trader.py) + Bot 2 (databento_paper_trader.py:RiskManager).
        self._bot3_risk = Bot3RiskManager()
        # DTC connector (DTCConfig accepte uniquement host/port/protocol/timeouts;
        # trade_account et username sont passes a chaque ordre via TRADE_ACCOUNT global)
        self.dtc: Optional[DTCConnector] = None
        if not dry_run and _DTC_OK:
            cfg = DTCConfig(
                host=os.environ.get("MIA_DTC_HOST", "127.0.0.1"),
                port=int(os.environ.get("MIA_DTC_PORT", "11099")),
            )
            self.dtc = DTCConnector(cfg)
            self.dtc.on_order_update = self._on_order_update_callback
        self._stop = threading.Event()
        # Setup signal handlers
        signal.signal(signal.SIGINT, lambda *_: self._stop.set())
        try:
            signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
        except (AttributeError, ValueError):
            pass

    def _bot3_emit_throttled(self, code: str, throttle_sec: float = 60.0, **kw) -> None:
        """Emit avec throttle par (sym, code) — anti spam log cycle 1s.

        Pour blocages haut volume (bar=None, bar stale, deja en position).
        1 emit par fenetre throttle_sec. Reset au prochain cycle apres expiry.
        Jackson 11/05 : 'on dois pouvoir suivre tout les blocage'.

        Fix code-reviewer 11/05 : assert sym present dans kw (fail-loud).
        Sinon tous les codes sans sym sharent meme key ("?", code) = collision.
        """
        sym = kw.get("sym")
        assert sym is not None, (
            f"_bot3_emit_throttled requires 'sym' kwarg (code={code}) — "
            "throttle key (sym, code) sans sym = collision."
        )
        key = (sym, code)
        now = time.time()
        last = self._bot3_emit_throttle.get(key, 0.0)
        if now - last < throttle_sec:
            return
        self._bot3_emit_throttle[key] = now
        _emit(code, **kw)

    def _ensure_dtc_connected(self) -> bool:
        if self.dry_run:
            return True
        if self.dtc is None:
            return False
        if not getattr(self.dtc, "connected", False):
            ok = self.dtc.connect()
            if not ok:
                _emit("DTC_DISCONNECT", reason="initial_connect_fail")
                return False
            _emit("DTC_CONNECT", host="localhost", port=11099)
        return True

    def _check_stop_flags(self) -> Optional[str]:
        """Retourne raison stop si flag detecte."""
        if STOP_FLAG_GLOBAL.exists():
            return "STOP.flag GLOBAL"
        if STOP_FLAG_LOCAL.exists():
            return "STOP_DATABENTO_V2.flag LOCAL"
        return None

    def _bot3_handle_dtc_fill(self, msg: dict, cid: str) -> bool:
        """FIX #1 (review code-reviewer + market-analyst 03/05 round 5) :
        Pattern Bot 1 — handle Bot 3 fill + close position + emit BOT3_TRADE_CLOSE.

        FIX 06/05 soir (Jackson "PAS DE PNL=0 PNL TOUJOURS A ZERO") : ajout cas
        `cid_type == "flatten"` pour capturer le fill du Type 209 SUBMIT_FLATTEN_POSITION_ORDER.
        Sans ce fix, les TIMEOUT 60min flatten retournaient un fill que le bot ne
        reconnaissait pas (CID `BOT3_FLUSH_*` jamais enregistre dans _bot3_cid_index)
        -> exit_price=null, pnl_known=false. Bug structurel identifie sur les 5 trades du 06/05.

        Returns True si fill traite (cid Bot 3), False sinon.
        """
        if cid not in self._bot3_cid_index:
            return False
        try:
            status = int(msg.get("OrderStatus", 0))
            if status != 7:                     # pas Filled
                return True                      # cid Bot 3 mais pas fill final
            entry = self._bot3_cid_index[cid]
            sym = entry["sym"]
            cid_type = entry["type"]            # "parent" / "tp" / "sl" / "flatten"
            fill_price = float(msg.get("AverageFillPrice", 0))
            with self._bot3_pos_lock:
                pos = self._bot3_positions.get(sym)

                # Cas "flatten" (Type 209 timeout) : la position peut deja etre None
                # (si _bot3_check_timeout a deja set _bot3_positions[sym] = None apres
                # log_trade_close avec pnl=null). On utilise pos_snapshot du _cid_index
                # pour reconstruire le pnl reel apres-coup et reemettre un trade close
                # avec pnl_known=true (correction du log precedent).
                if cid_type == "flatten" and fill_price > 0:
                    pos_snap = entry.get("pos_snapshot") or pos or {}
                    if not pos_snap.get("entry_price"):
                        _emit("BOT3_FLATTEN_FILL_NO_ENTRY",
                              sym=sym, fill_price=fill_price, cid=cid[:20],
                              msg="entry_price absent du snapshot - skip pnl calc")
                        self._bot3_cid_index.pop(cid, None)
                        return True
                    dir_sign = 1 if pos_snap.get("side") == "LONG" else -1
                    pnl_ticks = round((fill_price - pos_snap["entry_price"]) / TICK_SIZE * dir_sign, 2)
                    try:
                        from bot3_config import GUARD_RAILS_BOT3 as GR
                    except ImportError:
                        from CORE.bot3_config import GUARD_RAILS_BOT3 as GR
                    pnl_dollars = round(
                        pnl_ticks * GR[sym]["tick_value"] * pos_snap.get("n_contracts", 3), 2)
                    duration_s = entry.get("duration_s", 0)
                    flatten_reason = entry.get("close_reason", "TIMEOUT_FLATTEN")
                    _emit("BOT3_FLATTEN_FILL_CAPTURED",
                          sym=sym, level=pos_snap.get("level", "?"),
                          fill_price=fill_price, entry=pos_snap["entry_price"],
                          pnl_ticks=pnl_ticks, pnl_usd=pnl_dollars,
                          reason=flatten_reason, cid=cid[:20])
                    # Re-log via JSONL : append une entree corrigee avec pnl_known=true.
                    # L'ancienne entree TIMEOUT pnl=null reste pour audit ("ce qui a ete
                    # logge a chaud") mais cette nouvelle ligne donne le pnl reel.
                    # Le dashboard prendra la ligne la plus recente par signal_id.
                    self._bot3_log_trade_close(
                        sym=sym, pos=pos_snap, exit_price=fill_price,
                        pnl_ticks=pnl_ticks, pnl_dollars=pnl_dollars,
                        reason=flatten_reason, duration_s=int(duration_s)
                    )
                    # Compteurs win/loss correction si pnl positif/negatif
                    if pnl_ticks < 0:
                        self.bot3_counters_today.setdefault("n_losses", {"NQ": 0, "ES": 0})
                        # Pas de increment ici — le n_losses a deja ete update au moment
                        # du timeout (avant fill) via reason=TIMEOUT. Eviter double-comptage.
                    self._bot3_cid_index.pop(cid, None)
                    return True

                if pos is None:
                    return True

                if cid_type == "parent" and fill_price > 0:
                    # Update entry_price avec fill reel + slippage
                    old_entry = pos["entry_price"]
                    pos["entry_price"] = fill_price
                    dir_sign = 1 if pos["side"] == "LONG" else -1
                    slip = round((fill_price - old_entry) / TICK_SIZE * dir_sign, 2)
                    pos["slip_entry_ticks"] = slip
                    _emit("PARENT_FILL_RECORDED",
                          sym=sym, fill_price=fill_price, old_entry=old_entry,
                          slip_ticks=slip, parent_id=cid)
                    return True

                if cid_type in ("tp", "sl") and fill_price > 0:
                    # Exit fill : close position + reset
                    outcome = "TP" if cid_type == "tp" else "SL"
                    expected = pos.get("tp_cap_price") if cid_type == "tp" else pos.get("sl_price")
                    dir_sign = 1 if pos["side"] == "LONG" else -1
                    slip_exit = round((fill_price - expected) / TICK_SIZE * dir_sign, 2) if expected else 0.0
                    pnl_ticks = round((fill_price - pos["entry_price"]) / TICK_SIZE * dir_sign, 2)
                    # R4 (review 04/05) : retire `cfg = GUARD_RAILS_BOT3 = None` (coquille refactor)
                    try:
                        from bot3_config import GUARD_RAILS_BOT3 as GR
                    except ImportError:
                        from CORE.bot3_config import GUARD_RAILS_BOT3 as GR
                    pnl_dollars = pnl_ticks * GR[sym]["tick_value"] * pos.get("n_contracts", 3)
                    duration_s = (datetime.now(timezone.utc) - datetime.fromisoformat(
                        pos["ts_open"].replace("Z", "+00:00"))).total_seconds() if pos.get("ts_open") else 0
                    _emit("BOT3_TRADE_CLOSE",
                          sym=sym, level=pos["level"], reason=outcome,
                          pnl=pnl_ticks, mfe=pos.get("mfe_ticks", 0),
                          mae=pos.get("mae_ticks", 0), dur=int(duration_s))
                    # Update compteurs Bot 3 (FIX #3)
                    self.bot3_counters_today.setdefault("n_trades", {"NQ": 0, "ES": 0})
                    self.bot3_counters_today.setdefault("n_losses", {"NQ": 0, "ES": 0})
                    self.bot3_counters_today["n_trades"][sym] += 1
                    if pnl_ticks < 0:
                        self.bot3_counters_today["n_losses"][sym] += 1
                    # SOLUTION DURABLE 06/05 (Jackson "PAS DE DETTE") : append-only
                    # JSONL pattern Bot 1/2, source de verite unique pour dashboard
                    # closed_today + audit J+30 cross-bots.
                    self._bot3_log_trade_close(
                        sym=sym, pos=pos, exit_price=fill_price,
                        pnl_ticks=pnl_ticks, pnl_dollars=pnl_dollars,
                        reason=outcome, duration_s=int(duration_s)
                    )
                    # Cleanup CIDs Bot 3
                    for c in (pos.get("parent_id"), pos.get("tp_cid"), pos.get("sl_cid")):
                        self._bot3_cid_index.pop(c, None)
                    # RESET position
                    self._bot3_positions[sym] = None
            return True
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3", fn_name="_bot3_handle_dtc_fill",
                  exc_type=type(e).__name__, exc_msg=str(e))
            return True

    def _bot3_check_timeout(self) -> None:
        """FIX #1 (04/05) + REWRITE 06/05 (P0.3+P0.4) : timeout 60min anti-orphelin V2.

        Sequence anti-orphelin V2 (06/05) :
          1. Cancel TP par CID (si trace) - le pos["tp_cid"] est parfois None pour
             positions RECOVERED -> pas grave, P0.3 step 6.5 catchera
          2. Cancel SL par CID (idem)
          3. Wait 1s propagation
          4. R1 verify position broker (anti race) via request_position_blocking
             - qty=0 : deja flat (TP/SL ont fill avant timeout)
             - qty=None : DTC freeze
          5. MARKET CLOSE Type 208 OpenCloseTrade=2 si position residuelle
          6. Wait 2s pour fill
          --- AJOUTS 06/05 (P0.3) ---
          6.5. CANCEL-ALL-WORKING : Type 300 query open orders pour ce symbole +
               cancel chaque working order trouve via Type 203. Catche les SL/TP
               orphelins quand pos["tp_cid"]/sl_cid sont None (recovery boot)
               OU quand Sierra Chart n'a pas reconnu les ClientOrderID en step 1-2.
          --- ---
          7. Type 209 SUBMIT_FLATTEN_POSITION_ORDER (defense par symbole)
          8. Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (bouclier ultime)
          --- AJOUTS 06/05 (P0.4) ---
          9. VERIFY POST-CLEANUP : re-query Type 300 open orders. Si > 0 working
             matching contract -> emit BOT3_ORPHAN_DETECTED_POST_CLEANUP CRITIQUE
             + Discord webhook. Re-cancel automatique de chaque survivant.
          --- ---

        Cf .claude/rules/orphan-prevention.md (etapes 6.5 et 9 ajoutees 06/05).
        """
        try:
            from bot3_config import GUARD_RAILS_BOT3 as GR, TRADE_ACCOUNT_BOT3
        except ImportError:
            from CORE.bot3_config import GUARD_RAILS_BOT3 as GR, TRADE_ACCOUNT_BOT3
        now_utc = datetime.now(timezone.utc)
        with self._bot3_pos_lock:  # R5 : protection lock
            for sym in SYMBOLS:
                pos = self._bot3_positions.get(sym)
                if pos is None:
                    continue
                ts_open_str = pos.get("ts_open")
                if not ts_open_str:
                    continue
                try:
                    ts_open = datetime.fromisoformat(ts_open_str.replace("Z", "+00:00"))
                    age_min = (now_utc - ts_open).total_seconds() / 60.0
                except Exception:
                    continue
                timeout_min = GR[sym]["timeout_minutes"]
                if age_min <= timeout_min:
                    continue

                contract = SYMBOL_TO_CONTRACT[sym]

                # FIX 06/05 soir : calcul close_reason en AMONT (deplace depuis ETAPE 8)
                # car utilise dans ETAPE 7a pour tracker flush_cid (capture fill Type 209).
                close_reason = ("RECOVERED_TIMEOUT"
                                if pos.get("level") == "_RECOVERED_BOOT_"
                                else "TIMEOUT")

                # R3 : DTC down -> ORPHAN_RISK + skip cleanup interne
                if not self.dry_run and not self.dtc:
                    _emit("BOT3_DTC_DOWN_ORPHAN_RISK",
                          sym=sym, level=pos["level"], age_min=round(age_min, 1))
                    self._bot3_positions[sym] = None
                    continue

                # ETAPE 1+2 : Cancel TP + SL (R2 : log fail-loud, pas except: pass)
                cancel_failed = []
                if not self.dry_run and self.dtc:
                    for label, cid in (("tp", pos.get("tp_cid")), ("sl", pos.get("sl_cid"))):
                        if not cid:
                            continue
                        try:
                            ok = self.dtc.cancel_order(cid, trade_account=TRADE_ACCOUNT_BOT3)
                            if not ok:
                                cancel_failed.append(label)
                        except Exception as e:
                            cancel_failed.append(label)
                            _emit("BOT3_TIMEOUT_CANCEL_EXCEPTION",
                                  sym=sym, label=label, cid=cid, err=str(e)[:200])
                    if cancel_failed:
                        _emit("BOT3_TIMEOUT_CANCEL_FAIL_ORPHAN_RISK",
                              sym=sym, level=pos["level"], failed=cancel_failed)

                # ETAPE 3 : wait propagation cancels
                time.sleep(1.0)

                # R1 : ETAPE 4 : verify position broker AVANT MARKET CLOSE (anti race)
                qty_broker = None
                if not self.dry_run and self.dtc:
                    try:
                        qty_broker = self.dtc.request_position_blocking(
                            contract, trade_account=TRADE_ACCOUNT_BOT3, timeout=2.0)
                    except Exception as e:
                        _emit("BOT3_TIMEOUT_REQUEST_POS_FAIL", sym=sym, err=str(e)[:200])

                if qty_broker == 0:
                    _emit("BOT3_TIMEOUT_ALREADY_FLAT",
                          sym=sym, level=pos["level"], age_min=round(age_min, 1))
                elif qty_broker is None:
                    _emit("BOT3_TIMEOUT_POSITION_UNKNOWN",
                          sym=sym, level=pos["level"], age_min=round(age_min, 1))
                else:
                    # ETAPE 5 : MARKET CLOSE Type 208 OpenCloseTrade=2
                    n_to_close = abs(qty_broker)
                    side_close = DTC_SELL if qty_broker > 0 else DTC_BUY
                    close_cid = f"BOT3_TIMEOUT_CLOSE_{sym[:2]}_{int(now_utc.timestamp()) % 100000}"

                    # FIX 08/05 BUG FONDAMENTAL (root cause "TIMEOUT pnl=None depuis 4 jours") :
                    # Le close_cid Type 208 n'etait JAMAIS enregistre dans _bot3_cid_index.
                    # Resultat : _bot3_handle_dtc_fill recevait l'ORDER_UPDATE Status=7
                    # avec ce CID inconnu, retournait False, fill ignore = pnl jamais capture.
                    # Pattern aligne flush_cid Type 209 (deja tracke ligne 691+).
                    # Type 208 OpenCloseTrade=2 capture le fill sur Sim1 (vs Type 209 mort).
                    self._bot3_cid_index[close_cid] = {
                        "sym": sym,
                        "type": "flatten",  # reuse code path "flatten" deja existant
                        "signal_id": pos.get("signal_id"),
                        "pos_snapshot": dict(pos),
                        "duration_s": int(age_min * 60),
                        "close_reason": close_reason,
                    }
                    try:
                        self.dtc._send({
                            "Type": 208,
                            "Symbol": contract,
                            "ClientOrderID": close_cid,
                            "OrderType": 1,
                            "BuySell": side_close,
                            "Quantity": n_to_close,
                            "TradeAccount": TRADE_ACCOUNT_BOT3,
                            "IsAutomatedOrder": 1,
                            "OpenCloseTrade": 2,
                            "TimeInForce": 0,
                        })
                        _emit("BOT3_TIMEOUT_FORCE_CLOSE",
                              sym=sym, level=pos["level"],
                              close_cid=close_cid, qty=n_to_close,
                              age_min=round(age_min, 1))
                    except Exception as e:
                        _emit("BOT3_TIMEOUT_CLOSE_FAIL", sym=sym, err=str(e)[:200])
                        # Cleanup cid_index si _send fail (anti-leak)
                        self._bot3_cid_index.pop(close_cid, None)

                # ETAPE 6 : wait pour fill MARKET CLOSE
                time.sleep(2.0)

                # ETAPE 6.5 (P0.3 06/05) : CANCEL-ALL-WORKING par symbole.
                # Type 209/210 plus bas ne cancel PAS les Working orders sans
                # position attachee (observe 06/05 : "No working orders to cancel
                # for Symbol and Account" alors que des SL/TP etaient Working dans
                # le DOM None.data - bug structurel SC). On query Type 300 pour
                # identifier les survivants ET les cancel via Type 203 explicit.
                if not self.dry_run and self.dtc:
                    try:
                        working_orders = self.dtc.request_open_orders_blocking(
                            trade_account=TRADE_ACCOUNT_BOT3,
                            symbol_filter=contract,
                            timeout=2.0)
                        if working_orders is None:
                            working_orders = []
                        # Filtrer pour matcher contract (defensif si SC ne respecte pas le filter)
                        sym_working = [o for o in working_orders
                                       if o.get("Symbol") == contract or contract in o.get("Symbol", "")]
                        if sym_working:
                            _emit("BOT3_TIMEOUT_CANCEL_ALL_WORKING_FOUND",
                                  sym=sym, n=len(sym_working),
                                  cids=[o.get("ClientOrderID", "")[:20] for o in sym_working])
                            for o in sym_working:
                                cid_to_cancel = o.get("ClientOrderID", "")
                                if not cid_to_cancel:
                                    continue
                                try:
                                    self.dtc.cancel_order(
                                        cid_to_cancel,
                                        trade_account=TRADE_ACCOUNT_BOT3)
                                except Exception as e:
                                    _emit("BOT3_TIMEOUT_CANCEL_ALL_FAIL",
                                          sym=sym, cid=cid_to_cancel[:20], err=str(e)[:200])
                            time.sleep(0.5)  # propagation cancels
                    except Exception as e:
                        _emit("BOT3_TIMEOUT_CANCEL_ALL_QUERY_FAIL",
                              sym=sym, err=str(e)[:200])

                # ETAPE 7a : Type 209 SUBMIT_FLATTEN_POSITION_ORDER (defense en profondeur)
                # BUG FIX 04/05 : ClientOrderID OBLIGATOIRE sinon SC rejette
                # ('ClientOrderID field is not set' dans logs SC).
                # FIX 06/05 soir (Jackson "PNL TOUJOURS A ZERO") : tracker flush_cid
                # AVANT _send pour que _bot3_handle_dtc_fill puisse capturer le fill
                # Type 209 et calculer pnl reel via pos_snapshot. Sans ce tracking,
                # tous les TIMEOUT 60min finissaient avec exit_price=null + pnl_known=false.
                if not self.dry_run and self.dtc:
                    try:
                        flush_cid = f"BOT3_FLUSH_{sym[:2]}_{int(now_utc.timestamp()) % 100000}"
                        # Snapshot pos AVANT _send (la pos sera reset a None apres
                        # log_trade_close ETAPE 8). Le snapshot permet de reconstituer
                        # le pnl reel quand le fill Type 209 arrive 100-500ms plus tard.
                        self._bot3_cid_index[flush_cid] = {
                            "sym": sym,
                            "type": "flatten",
                            "signal_id": pos.get("signal_id"),
                            "pos_snapshot": dict(pos),
                            "duration_s": int(age_min * 60),
                            "close_reason": close_reason,
                        }
                        self.dtc._send({
                            "Type": 209,
                            "ClientOrderID": flush_cid,
                            "Symbol": contract,
                            "TradeAccount": TRADE_ACCOUNT_BOT3,
                            "Exchange": "CME",
                            "IsAutomatedOrder": 1,
                        })
                        _emit("BOT3_TIMEOUT_FLATTEN_SYM", sym=sym, cid=flush_cid)
                    except Exception as e:
                        _emit("BOT3_TIMEOUT_FLATTEN_FAIL", sym=sym, err=str(e)[:200])

                # ETAPE 7b : Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (bouclier ultime)
                # Bot 3 = Sim1 dedie (1 trade max simultane par symbole) -> Type 210 SAFE.
                if not self.dry_run and self.dtc:
                    try:
                        flush_acct_cid = f"BOT3_FLUSH_ACCT_{int(now_utc.timestamp()) % 100000}"
                        self.dtc._send({
                            "Type": 210,
                            "ClientOrderID": flush_acct_cid,
                            "TradeAccount": TRADE_ACCOUNT_BOT3,
                            "IsAutomatedOrder": 1,
                        })
                        _emit("BOT3_TIMEOUT_FLATTEN_ACCOUNT",
                              account=TRADE_ACCOUNT_BOT3, cid=flush_acct_cid)
                    except Exception as e:
                        _emit("BOT3_TIMEOUT_FLATTEN_ACCOUNT_FAIL", err=str(e)[:200])

                # ETAPE 9 (P0.4 06/05) : VERIFY POST-CLEANUP.
                # Wait 2s pour propagation Type 209/210, puis re-query Type 300.
                # Si > 0 working orders matching contract -> ORPHELIN PERSISTANT.
                # Re-cancel chaque + emit ALERTE CRITIQUE (Discord deja branche
                # via le router log V2 sur niveau CRITIQUE).
                if not self.dry_run and self.dtc:
                    time.sleep(2.0)
                    try:
                        post_orders = self.dtc.request_open_orders_blocking(
                            trade_account=TRADE_ACCOUNT_BOT3,
                            symbol_filter=contract,
                            timeout=2.0)
                        if post_orders is None:
                            post_orders = []
                        post_sym = [o for o in post_orders
                                    if o.get("Symbol") == contract or contract in o.get("Symbol", "")]
                        if post_sym:
                            _emit("BOT3_ORPHAN_DETECTED_POST_CLEANUP",
                                  sym=sym, n=len(post_sym),
                                  cids=[o.get("ClientOrderID", "")[:20] for o in post_sym],
                                  level=pos.get("level"),
                                  msg="ALERTE: Working orders survivent apres Type 209+210 - re-cancel et investiguer")
                            # Tentative de re-cancel finale
                            for o in post_sym:
                                cid_post = o.get("ClientOrderID", "")
                                if not cid_post:
                                    continue
                                try:
                                    self.dtc.cancel_order(cid_post,
                                                          trade_account=TRADE_ACCOUNT_BOT3)
                                except Exception as e:
                                    _emit("BOT3_ORPHAN_RECANCEL_FAIL",
                                          sym=sym, cid=cid_post[:20], err=str(e)[:200])
                        else:
                            _emit("BOT3_TIMEOUT_CLEANUP_VERIFIED_CLEAN",
                                  sym=sym, level=pos.get("level"))
                    except Exception as e:
                        _emit("BOT3_ORPHAN_VERIFY_QUERY_FAIL",
                              sym=sym, err=str(e)[:200])

                # ETAPE 7c (FIX 08/05 Plan B : MIGRATION FINALE vers live_cache)
                # Apres tests empiriques :
                #   - JSONL DMP : lag 60-110s (write Sierra Chart en fin de bar)
                #   - Databento parquet OHLCV-1m : lag 60-900s (pipeline cycle 3-5 min)
                #   - live_cache (DATA/LIVE_CACHE/_last.json) : lag <60s (stream Databento direct)
                # live_cache = source la plus fraiche, alignee Bot 2 V6 dual-source pattern.
                # Mis a jour par databento_live_stream.py.
                # Flag pnl_estimated=True exclut trade des metriques Lopez officielles.
                exit_price_approx = None
                pnl_ticks_approx = None
                pnl_usd_approx = None
                pnl_estimated = False
                try:
                    try:
                        from CORE import live_cache
                    except ImportError:
                        import live_cache  # type: ignore
                    cache_bar = live_cache.read_bar(sym, max_age_sec=300)
                    if cache_bar is not None and pos.get("entry_price"):
                        bar_close_f = float(cache_bar.get("close", 0))
                        bar_age = float(cache_bar.get("age_sec", 99999))
                        if bar_age <= 300 and bar_close_f > 0:
                            dir_sign = 1 if pos.get("side") == "LONG" else -1
                            entry = float(pos["entry_price"])
                            tick = GR[sym]["tick_size"]
                            tick_value = GR[sym]["tick_value"]
                            n_contracts = pos.get("n_contracts", 3)
                            pnl_ticks_approx = round(
                                (bar_close_f - entry) / tick * dir_sign, 2)
                            pnl_usd_approx = round(
                                pnl_ticks_approx * tick_value * n_contracts, 2)
                            exit_price_approx = bar_close_f
                            pnl_estimated = True
                            _emit("BOT3_TIMEOUT_PNL_APPROX",
                                  sym=sym, entry=entry,
                                  exit_approx=bar_close_f,
                                  pnl_ticks_approx=pnl_ticks_approx,
                                  pnl_usd_approx=pnl_usd_approx,
                                  bar_age_s=int(bar_age),
                                  mfe=pos.get("mfe_ticks", 0),
                                  mae=pos.get("mae_ticks", 0))
                        else:
                            _emit("BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE",
                                  sym=sym, bar_age_s=int(bar_age))
                    else:
                        _emit("BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE",
                              sym=sym, bar_age_s=99999)
                except Exception as e:
                    _emit("BOT3_TIMEOUT_PNL_APPROX_FAIL",
                          sym=sym, err=str(e)[:200])

                # ETAPE 8 : Emit BOT3_TRADE_CLOSE + cleanup
                # R1 (review 04/05) : reason distinct pour positions recovered (boot)
                # vs TIMEOUT reel — eviter pollution setup_stats avec faux pnl=0.
                # close_reason calcule en amont (fix 06/05 pour ETAPE 7a flush_cid tracking).
                #
                # FIX 07/05 Solution A : pnl=approx (close last bar) au lieu de None
                # si bar dispo + age <= 90s. Sinon pnl=None (frontend affiche "—").
                # 31 TIMEOUT_FLATTEN_SYM envoyes / 0 FLATTEN_FILL_CAPTURED sur 4 jours
                # = fix 06/05 mort. Solution A approxime pnl reel via close bar.
                _emit("BOT3_TRADE_CLOSE",
                      sym=sym, level=pos["level"], reason=close_reason,
                      pnl=pnl_usd_approx, mfe=pos.get("mfe_ticks", 0),
                      mae=pos.get("mae_ticks", 0), dur=int(age_min * 60),
                      pnl_known=pnl_estimated, pnl_estimated=pnl_estimated)
                # JSONL append-only : exit_price = approx si dispo, sinon null.
                # pnl_ticks/usd = approx si dispo, sinon null. pnl_estimated flag
                # permet distinction frontend (affichage "$X.XX*" pour estim, "$X.XX"
                # pour known via TP/SL fill capture).
                self._bot3_log_trade_close(
                    sym=sym, pos=pos, exit_price=exit_price_approx,
                    pnl_ticks=pnl_ticks_approx, pnl_dollars=pnl_usd_approx,
                    reason=close_reason, duration_s=int(age_min * 60),
                    pnl_estimated=pnl_estimated,
                )
                for c in (pos.get("parent_id"), pos.get("tp_cid"), pos.get("sl_cid")):
                    self._bot3_cid_index.pop(c, None)
                self._bot3_positions[sym] = None

    def _bot3_recover_open_positions(self) -> None:
        """FIX #1 (04/05) + REWRITE 06/05 (P0.2 anti-orphelin) — Restaure tracking au boot.

        Avant fix 06/05 : restart Bot 3 avec position broker ouverte -> placeholder
        avec tp_cid=None, sl_cid=None, entry_price=0 -> _bot3_check_timeout ne pouvait
        PAS cancel les Working orders TP/SL (cancel_order skip si cid=None) -> Type 209
        flat la position MAIS laisse les TP/SL Working orphelins dans le DOM.

        Apres fix 06/05 : query Type 305 (position) + Type 300 (open orders) pour
        reconstituer l'etat REEL :
          - entry_price = AverageFillPrice broker (via P2.1)
          - tp_cid/tp_cap_price = identifies depuis Working order LIMIT (OpenCloseTrade=2)
          - sl_cid/sl_price = identifies depuis Working order STOP (OpenCloseTrade=2)
          - parent_id reste None (parent fill historique non identifiable post-restart,
            mais parent est deja flat normalement — ce n'est pas un bug).

        Si TP/SL identifies : pos["tp_cid"]/pos["sl_cid"] valides -> _bot3_check_timeout
        peut cancel-then-flatten proprement (sequence anti-orphelin complete).

        Si TP ou SL ABSENT (1 seul orphelin trouve, OU les 2 absents alors qu'on a une
        position) : on logge BOT3_RECOVER_PARTIAL_BRACKET ou BOT3_RECOVER_NO_BRACKET
        pour traceabilite + on flat immediatement (force timeout) car on ne peut pas
        proteger la position (asymetrie SL/TP).

        Le ts_open est force a now-60min pour declencher le timeout au prochain check
        cycle (15s) -> cleanup via sequence anti-orphelin (incluant cancel-all-working
        P0.3 qui catch les ordres broker non-traques).
        """
        try:
            from bot3_config import TRADE_ACCOUNT_BOT3
        except ImportError:
            from CORE.bot3_config import TRADE_ACCOUNT_BOT3
        from datetime import timedelta

        # P0.2 step 1 : query toutes les working orders du compte une seule fois
        # (evite N queries Type 300 pour N symbols).
        all_working_orders = []
        try:
            res = self.dtc.request_open_orders_blocking(
                trade_account=TRADE_ACCOUNT_BOT3, timeout=3.0)
            if res is not None:
                all_working_orders = res
        except Exception as e:
            _emit("BOT3_RECOVER_OPEN_ORDERS_QUERY_FAIL", err=str(e)[:200])

        for sym in SYMBOLS:
            try:
                contract = SYMBOL_TO_CONTRACT[sym]
                # P2.1 (06/05) : utilise version qui retourne (qty, avg_price)
                pos_result = self.dtc.request_position_with_avg_price(
                    contract, trade_account=TRADE_ACCOUNT_BOT3, timeout=3.0)
            except Exception as e:
                _emit("BOT3_RECOVER_QUERY_FAIL", sym=sym, err=str(e)[:200])
                continue
            if pos_result is None:
                _emit("BOT3_RECOVER_QUERY_TIMEOUT", sym=sym)
                continue
            qty, avg_price = pos_result
            if qty is None:
                _emit("BOT3_RECOVER_QUERY_TIMEOUT", sym=sym)
                continue
            if qty == 0:
                # Position deja flat : check si on a des Working orders orphelins
                # quand meme (ex: parent fill puis SL fill puis bot down avant cancel TP).
                # Si oui -> cancel maintenant pour cleanup ascendant.
                orphan_orders = [o for o in all_working_orders
                                 if o.get("Symbol") == contract or contract in o.get("Symbol", "")]
                if orphan_orders:
                    _emit("BOT3_RECOVER_ORPHANS_FOUND_QTY_ZERO",
                          sym=sym, n_orphans=len(orphan_orders),
                          cids=[o.get("ClientOrderID", "")[:20] for o in orphan_orders])
                    for o in orphan_orders:
                        try:
                            self.dtc.cancel_order(
                                o.get("ClientOrderID", ""),
                                trade_account=TRADE_ACCOUNT_BOT3)
                        except Exception as e:
                            _emit("BOT3_RECOVER_CANCEL_ORPHAN_FAIL",
                                  sym=sym, cid=o.get("ClientOrderID", ""), err=str(e)[:200])
                continue

            # P0.2 step 2 : matcher les working orders au sym pour reconstituer
            # tp_cid (LIMIT, OpenCloseTrade=2) et sl_cid (STOP, OpenCloseTrade=2).
            # OrderType : 1=MARKET, 2=LIMIT, 3=STOP, 4=STOP_LIMIT (cf dtc_connector.py:60-63)
            sym_orders = [o for o in all_working_orders
                          if o.get("Symbol") == contract or contract in o.get("Symbol", "")]
            limit_orders = [o for o in sym_orders if o.get("OrderType", 0) == 2]
            stop_orders = [o for o in sym_orders if o.get("OrderType", 0) in (3, 4)]

            # P0-B (06/05 review) : detection multi-bracket AMBIGU.
            # Si > 1 LIMIT ou > 1 STOP -> impossible de savoir quel TP/SL appartient
            # au bracket courant (peut-etre orphelins de trades anciens). Force le
            # path "no bracket" -> timeout immediat declenche cancel-all (P0.3) qui
            # nettoie tous les Working sans risque de mauvais matching cids/prices.
            ambiguous_bracket = len(limit_orders) > 1 or len(stop_orders) > 1
            if ambiguous_bracket:
                _emit("BOT3_RECOVER_AMBIGUOUS_BRACKET",
                      sym=sym, qty=int(qty),
                      n_limit=len(limit_orders), n_stop=len(stop_orders),
                      n_total_working=len(sym_orders),
                      msg="Multiple TP/SL working - impossible matcher bracket courant - force timeout cancel-all")
                tp_order = None
                sl_order = None
            else:
                tp_order = limit_orders[0] if limit_orders else None
                sl_order = stop_orders[0] if stop_orders else None

            tp_cid = tp_order.get("ClientOrderID", "") if tp_order else None
            sl_cid = sl_order.get("ClientOrderID", "") if sl_order else None
            tp_price = float(tp_order.get("Price1", 0)) if tp_order else 0.0
            sl_price = float(sl_order.get("StopPrice", 0) or sl_order.get("Price1", 0)) if sl_order else 0.0

            # Si on identifie TP+SL : re-register OCO pair cote connector pour que
            # les fills futurs declenchent l'OCO manuel (cancel oppose).
            if tp_cid and sl_cid:
                try:
                    self.dtc.register_oco_pair(tp_cid, sl_cid)
                except Exception as e:
                    _emit("BOT3_RECOVER_OCO_REGISTER_FAIL",
                          sym=sym, tp_cid=tp_cid, sl_cid=sl_cid, err=str(e)[:200])

            # R3 (review 04/05) : idempotence — ne pas ecraser une position deja trackee
            ts_open_old = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
            side = "LONG" if qty > 0 else "SHORT"
            n_contracts = abs(int(qty))
            with self._bot3_pos_lock:
                if self._bot3_positions.get(sym) is not None:
                    _emit("BOT3_RECOVER_SKIP_ALREADY_TRACKED",
                          sym=sym, qty=int(qty),
                          existing_level=self._bot3_positions[sym].get("level"))
                    continue
                self._bot3_positions[sym] = {
                    "signal_id": f"RECOVERED_{sym}",
                    "level": "_RECOVERED_BOOT_",
                    "side": side,
                    "action": "RECOVERED",
                    "n_contracts": n_contracts,
                    "entry_price": float(avg_price) if avg_price > 0 else 0.0,
                    "sl_price": sl_price,
                    "tp_cap_price": tp_price,
                    "ts_open": ts_open_old,     # force timeout au prochain check
                    "parent_id": None,
                    "tp_cid": tp_cid,
                    "sl_cid": sl_cid,
                    "mfe_ticks": 0.0,
                    "mae_ticks": 0.0,
                }
                # Re-populate _bot3_cid_index pour routing fills si TP/SL fill
                # entre le boot et le timeout (rare mais possible).
                if tp_cid:
                    self._bot3_cid_index[tp_cid] = {"sym": sym, "type": "tp",
                                                    "signal_id": f"RECOVERED_{sym}"}
                if sl_cid:
                    self._bot3_cid_index[sl_cid] = {"sym": sym, "type": "sl",
                                                    "signal_id": f"RECOVERED_{sym}"}

            # Diagnostic emits selon completude bracket reconstitue
            if tp_cid and sl_cid:
                _emit("BOT3_RECOVER_FULL_BRACKET",
                      sym=sym, qty=int(qty), side=side, avg_price=float(avg_price),
                      tp_cid=tp_cid[:20], sl_cid=sl_cid[:20],
                      tp_price=tp_price, sl_price=sl_price)
            elif tp_cid or sl_cid:
                _emit("BOT3_RECOVER_PARTIAL_BRACKET",
                      sym=sym, qty=int(qty), side=side,
                      tp_cid=tp_cid[:20] if tp_cid else None,
                      sl_cid=sl_cid[:20] if sl_cid else None,
                      n_working_total=len(sym_orders))
            else:
                _emit("BOT3_RECOVER_NO_BRACKET_FOUND",
                      sym=sym, qty=int(qty), side=side,
                      n_working_total=len(sym_orders),
                      msg="position broker sans TP/SL Working - timeout immediat declenchera P0.3 cancel-all + flatten")

            _emit("BOT3_RECOVER_POSITION_RESTORED",
                  sym=sym, qty=int(qty), side=side,
                  avg_price=float(avg_price),
                  has_tp=bool(tp_cid), has_sl=bool(sl_cid),
                  ts_open_force=ts_open_old)

    def _bot3_update_mfe_mae(self) -> None:
        """FIX BUG MFE/MAE = 0 systematique (Jackson 04/05 matin).

        Met a jour MFE (Max Favorable Excursion) + MAE (Max Adverse Excursion)
        pour chaque position Bot 3 ouverte sur la barre courante. Sans cet update,
        les positions ouvertes ne tracent JAMAIS leur excursion → MFE=MAE=0
        au timeout = pas d'audit calibration possible.

        Refacto 11/05 17:30 (Phase 1b ACTION review code-reviewer fix #1) :
        Update MFE/MAE INSIDE lock (atomic pour pos dict). Mais appels
        _bot3_check_trailing_observation/ladder HORS lock (snapshot pattern).
        Sinon _bot3_modify_sl_via_dtc re-prend lock = DEADLOCK garanti
        (threading.Lock non-reentrant).
        """
        try:
            from bot3_config import GUARD_RAILS_BOT3 as GR
        except ImportError:
            from CORE.bot3_config import GUARD_RAILS_BOT3 as GR
        # STEP 1 : update MFE/MAE inside lock (atomic), collect snapshot pour traitement hors lock
        positions_snapshot = []
        with self._bot3_pos_lock:
            for sym in SYMBOLS:
                pos = self._bot3_positions.get(sym)
                if pos is None:
                    continue
                bar = load_last_bar(sym)
                if bar is None:
                    continue
                bar_dict = bar.to_dict()
                high = bar_dict.get("high")
                low = bar_dict.get("low")
                if high is None or low is None:
                    continue
                tick_size = GR[sym].get("tick_size", 0.25)
                entry = pos.get("entry_price", 0)
                if entry <= 0:
                    continue
                dir_sign = 1 if pos["side"] == "LONG" else -1
                if dir_sign == 1:
                    excursion = (high - entry) / tick_size
                    adverse = (low - entry) / tick_size
                else:
                    excursion = (entry - low) / tick_size
                    adverse = (entry - high) / tick_size
                pos["mfe_ticks"] = max(pos.get("mfe_ticks", 0.0), float(excursion))
                pos["mae_ticks"] = min(pos.get("mae_ticks", 0.0), float(adverse))
                # Add to snapshot pour appels HORS lock
                positions_snapshot.append((sym, pos, tick_size))

        # STEP 2 : appels observation + ladder HORS lock (mode ACTION peut re-prendre lock dans modify_sl)
        for sym, pos, tick_size in positions_snapshot:
            # 07/05 PHASE 1 OBSERVATION : trailing + BE log only
            self._bot3_check_trailing_observation(sym, pos, tick_size, GR)
            # 11/05 LADDER PROFIT-LOCKING Phase 1a/1b (Jackson Solution D2 "pas gourmand")
            # Phase 1b ACTION peut re-prendre _bot3_pos_lock pour update pos dict — OK hors lock principal.
            self._bot3_check_trailing_ladder(sym, pos, tick_size, GR)

    def _bot3_check_trailing_observation(self, sym, pos, tick_size, GR):
        """Trailing + BE en mode OBSERVATION (Jackson 07/05).

        Detecte 2 evenements et log :
          1. BE trigger : MFE >= trailing_be_trigger_ticks → SL hypothetique = entry
          2. Trailing trigger : MFE >= trailing_active_trigger_ticks → SL hypothetique = MFE_price - trailing_distance

        En mode OBSERVE_ONLY (default) : pas de modify DTC, juste logs structurels
        pour audit J+7 (compter combien de trades auraient bien profite, calc gain
        theorique, mesurer faux positifs).

        Edge bar-by-bar : appele une fois par bar dans _bot3_update_mfe_mae. Idempotent
        via flags `pos["trailing_be_observed"]` et `pos["trailing_active_observed"]`
        (log unique par phase, pas de spam).
        """
        try:
            cfg = GR.get(sym, {})
            be_trigger = cfg.get("trailing_be_trigger_ticks")
            active_trigger = cfg.get("trailing_active_trigger_ticks")
            trailing_dist = cfg.get("trailing_distance_ticks")
            if not (be_trigger and active_trigger and trailing_dist):
                return  # config trailing pas dispo pour ce sym
            mfe = pos.get("mfe_ticks", 0.0)
            entry = pos.get("entry_price", 0)
            if entry <= 0 or mfe <= 0:
                return
            dir_sign = 1 if pos["side"] == "LONG" else -1
            # MFE price reel = entry + MFE * dir * tick_size
            mfe_price = entry + dir_sign * mfe * tick_size

            # Trigger 1 : BE (MFE >= be_trigger)
            if mfe >= be_trigger and not pos.get("trailing_be_observed"):
                pos["trailing_be_observed"] = True
                _emit("BOT3_TRAILING_BE_OBSERVED",
                      sym=sym, level=pos.get("level", "?"),
                      side=pos["side"],
                      entry_price=round(entry, 2),
                      current_mfe_ticks=round(mfe, 1),
                      be_trigger_ticks=be_trigger,
                      sl_current=round(pos.get("sl_price", 0), 2),
                      sl_hypothetical_be=round(entry, 2),
                      ts_open=pos.get("ts_open"),
                      signal_id=pos.get("signal_id"))

            # Trigger 2 : Trailing actif (MFE >= active_trigger)
            if mfe >= active_trigger:
                # SL hypothetique = MFE_price - trailing_dist (LONG) / + (SHORT)
                trailing_sl_hyp = mfe_price - dir_sign * trailing_dist * tick_size
                # Log seulement si nouveau peak MFE (sinon spam toutes les bars)
                last_observed_mfe = pos.get("trailing_last_logged_mfe", 0)
                if mfe > last_observed_mfe + (trailing_dist / 4):  # log si MFE progresse de 25% du trailing_dist
                    pos["trailing_last_logged_mfe"] = mfe
                    pos["trailing_active_observed"] = True
                    _emit("BOT3_TRAILING_UPDATE_OBSERVED",
                          sym=sym, level=pos.get("level", "?"),
                          side=pos["side"],
                          entry_price=round(entry, 2),
                          current_mfe_ticks=round(mfe, 1),
                          mfe_price=round(mfe_price, 2),
                          active_trigger_ticks=active_trigger,
                          trailing_distance_ticks=trailing_dist,
                          sl_current=round(pos.get("sl_price", 0), 2),
                          sl_hypothetical_trailing=round(trailing_sl_hyp, 2),
                          ts_open=pos.get("ts_open"),
                          signal_id=pos.get("signal_id"))
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym=sym, fn_name="_bot3_check_trailing_observation",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def _bot3_check_trailing_ladder(self, sym, pos, tick_size, GR):
        """Profit-locking ladder par paliers MFE (Jackson Solution D2, 11/05).

        Quand MFE atteint un seuil (palier), le SL bouge a entry + sl_lock_ticks
        (lock minimum profit garanti). Le SL ne redescend JAMAIS, seulement monte
        avec les paliers successifs. TP initial reste pour laisser respirer.

        Phase 1a (cette implementation) :
          MODE OBSERVE = log BOT3_LADDER_WOULD_LOCK_PALIER_N sans action DTC
        Phase 1b (future, 7 fixes anti-orphan obligatoires) :
          MODE ACTION = cancel SL actuel + send new stop @ entry + sl_lock * tick_size

        Kill switches :
          MIA_BOT3_LADDER_ENABLED=0 (default) - fonction return early
          MIA_BOT3_LADDER_MODE=OBSERVE|ACTION (default OBSERVE)

        Diagnostic emit BOT3_LADDER_TICK obligatoire a chaque call (debug call path).
        """
        # Kill switch global
        if os.environ.get("MIA_BOT3_LADDER_ENABLED", "0") != "1":
            return
        try:
            mode = os.environ.get("MIA_BOT3_LADDER_MODE", "OBSERVE").upper()
            cfg = GR.get(sym, {})
            paliers = cfg.get("ladder_paliers", [])

            mfe = float(pos.get("mfe_ticks", 0.0))
            entry = float(pos.get("entry_price", 0.0))
            executed = pos.setdefault("ladder_executed_paliers", set())

            # Diagnostic emit OBLIGATOIRE — confirme fonction tourne au runtime
            _emit("BOT3_LADDER_TICK",
                  sym=sym, mfe=round(mfe, 1),
                  entry=round(entry, 2),
                  n_paliers=len(paliers),
                  executed_count=len(executed),
                  mode=mode,
                  ts_open=pos.get("ts_open"),
                  signal_id=pos.get("signal_id"))

            if not paliers:
                return
            if entry <= 0 or mfe <= 0:
                return

            dir_sign = 1 if pos["side"] == "LONG" else -1
            n_contracts = cfg.get("n_contracts", 3)
            tick_value = cfg.get("tick_value", 0.50)

            for palier_idx, (mfe_seuil, sl_lock_ticks) in enumerate(paliers):
                if palier_idx in executed:
                    continue
                if mfe < mfe_seuil:
                    # paliers ordonnes croissants : si MFE < seuil_i alors < seuil_(i+1) aussi
                    break

                new_sl_price = entry + dir_sign * sl_lock_ticks * tick_size
                lock_usd = sl_lock_ticks * tick_value * n_contracts

                if mode == "OBSERVE":
                    _emit("BOT3_LADDER_WOULD_LOCK",
                          sym=sym, palier=palier_idx + 1,
                          side=pos.get("side"),
                          level=pos.get("level", "?"),
                          mfe_ticks=round(mfe, 1),
                          mfe_seuil_ticks=mfe_seuil,
                          sl_lock_ticks=sl_lock_ticks,
                          sl_old_price=round(pos.get("sl_price", 0), 2),
                          sl_new_price=round(new_sl_price, 2),
                          lock_usd=round(lock_usd, 2),
                          ts_open=pos.get("ts_open"),
                          signal_id=pos.get("signal_id"))
                    executed.add(palier_idx)  # idempotent : 1 log par palier par trade
                elif mode == "ACTION":
                    # Phase 1b ACTION (11/05 17:00) — cancel SL + send new stop
                    # avec 7 fixes anti-orphan (cf .claude/rules/orphan-prevention.md)
                    #   1. ABORT si cancel echoue → alert CRITIQUE BOT3_LADDER_NO_SL
                    #   2. _order_trade_accounts[new_sl_cid] = TRADE_ACCOUNT_BOT3 (fix H6)
                    #   3. register_oco_pair AVANT send nouveau SL (pre-register)
                    #   4. OrderType=3 STOP + StopPrice
                    #   5. Idempotent : executed.add(palier_idx) AVANT modify (anti retry boucle)
                    #   6. Modify HORS lock _bot3_pos_lock (cf _bot3_check_trailing_ladder
                    #      est deja appele HORS lock depuis _bot3_update_mfe_mae, OK)
                    #   7. Alert BOT3_LADDER_NO_SL_ALERT si position sans SL apres modify
                    executed.add(palier_idx)  # Fix #5 : idempotent AVANT modify
                    ok = self._bot3_modify_sl_via_dtc(
                        sym=sym, pos=pos,
                        new_sl_price=new_sl_price,
                        palier_idx=palier_idx + 1,
                        lock_usd=lock_usd,
                    )
                    if not ok:
                        # Fix #1 + #7 : alert CRITIQUE position sans SL = ORPHAN RISK
                        _emit("BOT3_LADDER_NO_SL_ALERT",
                              sym=sym, palier=palier_idx + 1,
                              level=pos.get("level", "?"),
                              msg="ladder modify SL FAILED — position sans SL = ORPHAN RISK",
                              old_sl_cid=pos.get("sl_cid"),
                              entry=round(entry, 2),
                              attempted_new_sl=round(new_sl_price, 2))
                else:
                    _emit("BOT3_LADDER_INVALID_MODE",
                          sym=sym, mode=mode,
                          msg="MIA_BOT3_LADDER_MODE must be OBSERVE or ACTION")
                    return
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym=sym, fn_name="_bot3_check_trailing_ladder",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def _bot3_modify_sl_via_dtc(self, sym: str, pos: dict, new_sl_price: float,
                                  palier_idx: int, lock_usd: float) -> bool:
        """Phase 1b ACTION (Jackson 11/05 17:00) — Modify SL via cancel + replace DTC.

        7 fixes anti-orphan obligatoires (cf .claude/rules/orphan-prevention.md) :
          1. ABORT si cancel echoue → caller emet BOT3_LADDER_NO_SL_ALERT
          2. _order_trade_accounts[new_sl_cid] = TRADE_ACCOUNT_BOT3 (fix H6)
          3. register_oco_pair AVANT send nouveau SL (pre-register protection)
          4. OrderType=3 STOP + StopPrice
          5. Idempotence : caller marque executed AVANT cet appel
          6. Modify HORS lock _bot3_pos_lock (caller appele depuis hors-lock)
          7. Verify : si pos["sl_cid"] None apres modify = ORPHAN, caller alerte

        Returns:
            True si modify reussi (new SL place + pos update + OCO re-register)
            False si echec a n'importe quelle etape (caller emet alert + retry plus tard)
        """
        if self.dtc is None or not self.dtc.connected:
            _emit("BOT3_LADDER_MODIFY_DTC_DOWN",
                  sym=sym, palier=palier_idx,
                  msg="DTC not connected — cannot modify SL")
            return False

        try:
            from bot3_config import TRADE_ACCOUNT_BOT3
        except ImportError:
            from CORE.bot3_config import TRADE_ACCOUNT_BOT3

        old_sl_cid = pos.get("sl_cid")
        tp_cid = pos.get("tp_cid")
        if not old_sl_cid:
            _emit("BOT3_LADDER_MODIFY_NO_OLD_SL_CID",
                  sym=sym, palier=palier_idx,
                  msg="pos.sl_cid manquant — skip ladder modify (probable recovery boot)")
            return False

        # Determiner symbol contract + side du new SL (opposite de la position)
        # NQ LONG = SL est SELL stop ; SHORT = SL est BUY stop
        side_long = (pos.get("side") == "LONG")
        new_sl_side = "SELL" if side_long else "BUY"
        # Use BOT 2 V2 INSTRUMENTS for contract resolution (Bot 3 shares DTC connector)
        try:
            contract = BOT_INSTRUMENTS[sym].contract
        except (KeyError, AttributeError):
            _emit("BOT3_LADDER_MODIFY_CONTRACT_LOOKUP_FAIL",
                  sym=sym, palier=palier_idx)
            return False

        # STEP A : Cancel old SL via Type 203 (avec ServerOrderID + TradeAccount = fix H6)
        try:
            cancel_ok = self.dtc.cancel_order(old_sl_cid, trade_account=TRADE_ACCOUNT_BOT3)
        except Exception as e:
            _emit("BOT3_LADDER_CANCEL_EXCEPTION",
                  sym=sym, palier=palier_idx,
                  old_sl_cid=old_sl_cid,
                  exc=type(e).__name__, msg=str(e)[:200])
            return False
        if not cancel_ok:
            _emit("BOT3_LADDER_CANCEL_FAILED",
                  sym=sym, palier=palier_idx,
                  old_sl_cid=old_sl_cid,
                  msg="dtc.cancel_order returned False — ABORT modify")
            return False

        # Fix #3 (code-reviewer 11/05) : cleanup OCO mapping ancien (bidirectionnel)
        # register_oco_pair fait _oco_pairs[tp]=sl + _oco_pairs[sl]=tp. cancel_order
        # ne nettoie pas. Sans ce cleanup, old_sl_cid + tp_cid restent mapped vers
        # un sl_cid qui n'existe plus.
        self.dtc._oco_pairs.pop(old_sl_cid, None)
        if tp_cid:
            self.dtc._oco_pairs.pop(tp_cid, None)

        # Wait 0.3s pour propagation cancel + ServerOrderID resolution (cf cancel_order doc)
        time.sleep(0.3)

        # Fix #2 (code-reviewer 11/05) : verify position EXISTS broker AVANT send new SL
        # Sinon race condition : pendant les 0.3s, le marché peut traverser l'old SL
        # → SC fill l'old SL avant cancel propagation → position close DTC
        # → on enverrait un new STOP qui crée trade INVERSE (catastrophique)
        try:
            qty = self.dtc.request_position_blocking(
                contract, trade_account=TRADE_ACCOUNT_BOT3, timeout=2.0
            )
        except Exception as e:
            _emit("BOT3_LADDER_POS_VERIFY_EXCEPTION",
                  sym=sym, palier=palier_idx, exc=type(e).__name__, msg=str(e)[:200])
            return False
        if qty is None:
            _emit("BOT3_LADDER_POS_VERIFY_TIMEOUT",
                  sym=sym, palier=palier_idx,
                  msg="request_position_blocking timeout — abort modify")
            return False
        if qty == 0:
            _emit("BOT3_LADDER_POS_CLOSED_DURING_MODIFY",
                  sym=sym, palier=palier_idx,
                  old_sl_cid=old_sl_cid,
                  msg="position broker qty=0 pendant wait cancel — abort modify (anti trade inverse)")
            # Update pos dict pour refleter close
            with self._bot3_pos_lock:
                pos["sl_cid"] = None  # signaler que SL n'existe plus
            return False

        # STEP B : Generate new SL ClientOrderID + pre-register OCO/TA (fixes #2 + #3)
        import uuid as _uuid
        new_sl_cid = f"BOT3_LADDER_SL_{sym[:2]}_{_uuid.uuid4().hex[:8]}"
        # Fix H6 : pre-register trade_account AVANT send (anti-orphan)
        self.dtc._order_trade_accounts[new_sl_cid] = TRADE_ACCOUNT_BOT3
        # Pre-register OCO pair tp_cid <-> new_sl_cid AVANT send
        if tp_cid:
            self.dtc.register_oco_pair(tp_cid, new_sl_cid)

        # STEP C : Send new STOP order (Type 208 + OrderType=STOP + StopPrice)
        try:
            from dtc_connector import STOP, BUY as DTC_BUY, SELL as DTC_SELL, DTC_MARKET_ORDER
        except ImportError:
            from BOT.dtc_connector import STOP, BUY as DTC_BUY, SELL as DTC_SELL, DTC_MARKET_ORDER

        side_int = DTC_SELL if new_sl_side == "SELL" else DTC_BUY
        quantity = int(pos.get("n_contracts", 3))

        try:
            self.dtc._send({
                "Type": DTC_MARKET_ORDER,
                "Symbol": contract,
                "ClientOrderID": new_sl_cid,
                "OrderType": STOP,
                "BuySell": side_int,
                "Quantity": quantity,
                "Price1": float(new_sl_price),
                "StopPrice": float(new_sl_price),
                "TimeInForce": 0,
                "TradeAccount": TRADE_ACCOUNT_BOT3,
                "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2,
            })
        except Exception as e:
            _emit("BOT3_LADDER_SEND_NEW_SL_EXCEPTION",
                  sym=sym, palier=palier_idx,
                  new_sl_cid=new_sl_cid,
                  exc=type(e).__name__, msg=str(e)[:200])
            # Fix #3 (code-reviewer 11/05) : cleanup BIDIRECTIONNEL OCO pour eviter orphan
            # register_oco_pair stocke 2 directions : _oco_pairs[tp]=sl + _oco_pairs[sl]=tp
            # Pop seulement new_sl_cid laisse tp_cid -> new_sl_cid (mort) = orphan mapping
            self.dtc._order_trade_accounts.pop(new_sl_cid, None)
            self.dtc._oco_pairs.pop(new_sl_cid, None)
            if tp_cid:
                self.dtc._oco_pairs.pop(tp_cid, None)
            return False

        # STEP D : Update pos avec new SL info (fix #7 : pas None pour eviter ORPHAN ALERT)
        with self._bot3_pos_lock:  # mini-lock juste pour update pos dict (pas DTC ops)
            pos["sl_cid"] = new_sl_cid
            pos["sl_price"] = float(new_sl_price)
            # Audit trail
            ladder_history = pos.setdefault("ladder_sl_history", [])
            ladder_history.append({
                "palier": palier_idx,
                "old_sl_cid": old_sl_cid,
                "new_sl_cid": new_sl_cid,
                "new_sl_price": float(new_sl_price),
                "lock_usd": float(lock_usd),
                "ts_iso": datetime.now(timezone.utc).isoformat(),
            })

        _emit("BOT3_LADDER_SL_MODIFIED",
              sym=sym, palier=palier_idx,
              side=pos.get("side"),
              level=pos.get("level", "?"),
              old_sl_cid=old_sl_cid,
              new_sl_cid=new_sl_cid,
              new_sl_price=round(float(new_sl_price), 2),
              lock_usd=round(float(lock_usd), 2),
              ts_open=pos.get("ts_open"),
              signal_id=pos.get("signal_id"))
        return True

    def _on_order_update_callback(self, msg: dict):
        """Callback DTC pour fills parent + OCO.

        FIX B-1 (review code-reviewer 02/05) : NE PAS recalculer sl_price /
        tp_cap_price au fill. Les SL et TP_LIMIT envoyes au broker SONT
        bases sur signal.price (envoyes AVANT le fill parent). Si on les
        recalcule depuis fill_price ici, on a desync :
          - Bot pense SL = fill - 200t (recalcule)
          - Broker a SL = signal.price - 200t (ce qui a ete envoye)
        = TR40_NQ inverse.

        Solution : track entry_price reel (pour MFE/MAE corrects) + slip,
        mais GARDER sl_price/tp_cap_price aux valeurs envoyees au broker.
        """
        try:
            cid = str(msg.get("ClientOrderID", ""))
            # FIX #1 (review code-reviewer 03/05) : routing Bot 3 D'ABORD
            # (anti-corruption croisee Bot 2/Bot 3 — patterns Bot 1).
            if self._bot3_handle_dtc_fill(msg, cid):
                return  # cid Bot 3 traite, pas Bot 2

            status = int(msg.get("OrderStatus", 0))
            if status != 7:  # pas Filled
                return
            # Parent fill : detecter le symbole via bracket_ids
            for sym in SYMBOLS:
                bracket = self.bracket_ids.get(sym, {})
                if cid == bracket.get("parent_id"):
                    fill_price = float(msg.get("AverageFillPrice", 0))
                    if fill_price > 0 and self.positions[sym] is not None:
                        old_entry = self.positions[sym].entry_price
                        slip_ticks = round(abs(fill_price - old_entry) / TICK_SIZE, 2)
                        # Update entry_price = fill reel (pour MFE/MAE corrects)
                        # MAIS on NE TOUCHE PAS sl_price ni tp_cap_price :
                        # ils restent aux valeurs effectivement envoyees au broker.
                        self.positions[sym].entry_price = fill_price
                        _emit("PARENT_FILL_RECORDED",
                              sym=sym, fill_price=fill_price,
                              old_entry=old_entry, slip_ticks=slip_ticks,
                              parent_id=cid)
                    break
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="?", fn_name="_on_order_update_callback",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def execute_trade(self, signal: Signal) -> bool:
        """Envoie l'ordre paper via DTC ou simule en dry-run.

        Returns True si trade ouvert, False sinon.
        """
        cfg = TRAILING_CONFIG[signal.symbol]
        sl_pts = cfg["sl_ticks"] * TICK_SIZE
        tp_cap_pts = cfg["tp_cap_ticks"] * TICK_SIZE

        # 04/05 Etape 1 (anti-slippage long terme) : utilise live ref Databento
        # au lieu de signal.price (parquet/JSONL DMP qui peut avoir 30s+ retard).
        # Reduit slippage entry de ~30t a ~1-3t (valide V1 fin avril 2026).
        try:
            from CORE import live_cache
        except ImportError:
            import live_cache  # type: ignore
        live_ref, ref_source = live_cache.get_signal_entry_ref(
            signal.symbol, fallback=float(signal.price)
        )
        if ref_source == "FALLBACK" and live_cache.FALLBACK_MODE == "STRICT":
            _emit("LIVE_CACHE_STALE_SKIP",
                  sym=signal.symbol, signal_price=float(signal.price),
                  fallback_mode=live_cache.FALLBACK_MODE)
            return False
        drift_signal = (live_ref - float(signal.price)) / TICK_SIZE
        _emit("LIVE_REF_USED",
              sym=signal.symbol, bot="bot2_v2",
              signal_price=float(signal.price), live_ref=live_ref,
              ref_source=ref_source, drift_ticks=round(drift_signal, 1))

        if signal.side == "LONG":
            side_int = DTC_BUY
            sl_price = live_ref - sl_pts
            tp_cap_price = live_ref + tp_cap_pts
        else:
            side_int = DTC_SELL
            sl_price = live_ref + sl_pts
            tp_cap_price = live_ref - tp_cap_pts

        contract = SYMBOL_TO_CONTRACT[signal.symbol]
        n_contracts = cfg["n_contracts"]

        # ─── DRY RUN : pas d'envoi DTC ──────────────────────────
        if self.dry_run:
            now_utc = datetime.now(timezone.utc).isoformat()
            position = make_position(signal, fill_price=signal.price, fill_ts_utc=now_utc)
            position.broker_sl_price_current = position.sl_price
            self.positions[signal.symbol] = position
            log_trade_entry(position)
            print(f"[DRY-RUN] Trade OPEN {signal.symbol} {signal.side} "
                  f"setups={signal.setups} entry={signal.price} "
                  f"sl={sl_price} tp_cap={tp_cap_price}")
            return True

        # ─── PRODUCTION DTC ─────────────────────────────────────
        if not self._ensure_dtc_connected():
            _emit("DTC_DISCONNECT", reason="not_connected_at_trade")
            return False

        # 04/05 Etape 2 : signal_ref_price + sl_ticks/tp_ticks pour reprice eventuel
        sl_ticks_val = int(round(sl_pts / TICK_SIZE))
        tp_ticks_val = int(round(tp_cap_pts / TICK_SIZE))
        parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
            symbol=contract,
            side=side_int,
            quantity=n_contracts,
            sl_price=sl_price,
            tp_price=tp_cap_price,
            trade_account=TRADE_ACCOUNT,
            signal_ref_price=live_ref,
            sl_ticks=sl_ticks_val,
            tp_ticks=tp_ticks_val,
            tick_size=TICK_SIZE,
        )
        if not parent_id:
            _emit("ORDER_REJECT", sym=signal.symbol,
                  err_code="bracket_send_fail", err_msg="empty parent_id")
            return False

        # Initialise position dans le bot (entry_price sera ajuste sur fill)
        now_utc = datetime.now(timezone.utc).isoformat()
        position = make_position(signal, fill_price=signal.price, fill_ts_utc=now_utc)
        position.broker_sl_price_current = sl_price
        self.positions[signal.symbol] = position
        self.bracket_ids[signal.symbol] = {
            "parent_id": parent_id, "tp_cid": tp_cid, "sl_cid": sl_cid,
        }
        log_trade_entry(position)
        return True

    def update_position_during_trade(self, sym: str, current_price: float, current_ts_utc: str):
        """Update MFE/MAE + cancel+replace SL si trailing pending.

        FIX B1 (incident TR40_NQ 01/05) : si trailing_pending_broker_update,
        on cancel l'ancien SL DTC + envoie un nouveau SL au prix trailing,
        PUIS acknowledge cote bot. Sans ca = trailing virtuel = data invalide.
        """
        pos = self.positions[sym]
        if pos is None:
            return
        update_mfe_mae(pos, current_price)

        # ─── CANCEL+REPLACE SL si trailing pending ──────────────
        if pos.trailing_pending_broker_update and pos.trailing_stop_price is not None:
            if self.dry_run:
                # Simule l'ack (pour test sans DTC)
                acknowledge_broker_sl_update(pos, pos.trailing_stop_price)
            else:
                bracket = self.bracket_ids.get(sym, {})
                sl_cid = bracket.get("sl_cid")
                if sl_cid and self.dtc:
                    # Cancel ancien SL
                    cancelled = self.dtc.cancel_order(sl_cid, trade_account=TRADE_ACCOUNT)
                    if cancelled:
                        # Envoie nouveau SL au prix trailing
                        contract = SYMBOL_TO_CONTRACT[sym]
                        side_int = DTC_SELL if pos.side == "LONG" else DTC_BUY
                        cfg = TRAILING_CONFIG[sym]
                        new_sl_cid = f"MIA_SL_TR_{int(time.time() * 1000) % 100000}"
                        try:
                            self.dtc._send({
                                "Type": 208,
                                "Symbol": contract,
                                "ClientOrderID": new_sl_cid,
                                "OrderType": 3,  # STOP
                                "BuySell": side_int,
                                "Quantity": cfg["n_contracts"],
                                "Price1": float(pos.trailing_stop_price),
                                "StopPrice": float(pos.trailing_stop_price),
                                "TimeInForce": 0,
                                "TradeAccount": TRADE_ACCOUNT,
                                "IsAutomatedOrder": 1,
                                "OpenCloseTrade": 2,
                            })
                            # Re-register OCO avec le nouveau SL CID
                            tp_cid = bracket.get("tp_cid")
                            if tp_cid and hasattr(self.dtc, "register_oco_pair"):
                                self.dtc.register_oco_pair(tp_cid, new_sl_cid)
                            self.bracket_ids[sym]["sl_cid"] = new_sl_cid
                            old_broker_sl = pos.broker_sl_price_current
                            acknowledge_broker_sl_update(pos, pos.trailing_stop_price)
                            # FIX B-2 (02/05) : code OK pour succes
                            _emit("TRAILING_BROKER_REPLACED_OK",
                                  sym=sym,
                                  old_sl=round(old_broker_sl, 2) if old_broker_sl else None,
                                  new_sl=round(pos.trailing_stop_price, 2),
                                  new_sl_cid=new_sl_cid)
                        except Exception as e:
                            _emit("TRAILING_BROKER_REPLACE_FAILED",
                                  sym=sym, old_sl=pos.broker_sl_price_current,
                                  new_sl=pos.trailing_stop_price,
                                  err=str(e))
                            # Pas d'ack -> retry au prochain cycle

        # ─── Check exit ─────────────────────────────────────────
        exit_reason = check_exit_condition(pos, current_price, current_ts_utc)
        if exit_reason is not None:
            self._close_position(sym, current_price, exit_reason, current_ts_utc)

    def _close_position(self, sym: str, exit_price: float, exit_reason: str,
                        exit_ts_utc: str):
        """Ferme la position via DTC market close + log + update risk."""
        pos = self.positions[sym]
        if pos is None:
            return

        # ─── DRY RUN ─────────────────────────────────────────────
        if self.dry_run:
            pnl_dollars, is_winner = log_trade_exit(pos, exit_price, exit_reason, exit_ts_utc)
            self.risk.on_trade_close(sym, pnl_dollars, is_loss=(pnl_dollars < 0))
            # Tracker reussite par setup (Jackson 02/05)
            cfg = TRAILING_CONFIG[sym]
            pnl_ticks = pnl_dollars / (cfg["tick_value_dollars"] * cfg["n_contracts"])
            session_label = compute_session_label(exit_ts_utc)
            self.setup_stats.record_trade(pos, pnl_dollars, pnl_ticks,
                                            exit_reason, session_label)
            print(f"[DRY-RUN] Trade CLOSE {sym} reason={exit_reason} "
                  f"pnl=${pnl_dollars} winner={is_winner}")
            self.positions[sym] = None
            self.bracket_ids[sym] = {}
            return

        # ─── PRODUCTION ──────────────────────────────────────────
        if not self.dtc:
            return
        # Cancel TP + SL pour eviter orphelins
        bracket = self.bracket_ids.get(sym, {})
        for cid_key in ("tp_cid", "sl_cid"):
            cid = bracket.get(cid_key)
            if cid:
                try:
                    self.dtc.cancel_order(cid, trade_account=TRADE_ACCOUNT)
                except Exception:
                    pass

        # Send MARKET close (opposite side)
        contract = SYMBOL_TO_CONTRACT[sym]
        close_side = DTC_SELL if pos.side == "LONG" else DTC_BUY
        cfg = TRAILING_CONFIG[sym]
        close_cid = f"MIA_CL_{int(time.time() * 1000) % 100000}"
        try:
            self.dtc._send({
                "Type": 208,
                "Symbol": contract,
                "ClientOrderID": close_cid,
                "OrderType": 1,  # MARKET
                "BuySell": close_side,
                "Quantity": cfg["n_contracts"],
                "TradeAccount": TRADE_ACCOUNT,
                "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2,
                "TimeInForce": 0,
            })
        except Exception as e:
            _emit("ORDER_REJECT", sym=sym, err_code="close_send_fail",
                  err_msg=str(e))

        # Log + update risk (utiliser exit_price comme proxy fill, ajustable post-fill)
        pnl_dollars, is_winner = log_trade_exit(pos, exit_price, exit_reason, exit_ts_utc)
        self.risk.on_trade_close(sym, pnl_dollars, is_loss=(pnl_dollars < 0))
        # Tracker reussite par setup (Jackson 02/05)
        cfg = TRAILING_CONFIG[sym]
        pnl_ticks = pnl_dollars / (cfg["tick_value_dollars"] * cfg["n_contracts"])
        session_label = compute_session_label(exit_ts_utc)
        self.setup_stats.record_trade(pos, pnl_dollars, pnl_ticks,
                                        exit_reason, session_label)
        self.positions[sym] = None
        self.bracket_ids[sym] = {}

    def _persist_state(self):
        """Ecrit state.json pour dashboard.

        Inclut (Jackson 02/05) :
          - countdown timeout par position (pour onglet Trade en cours)
          - session_label entry par position (pour detail trade)
        """
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Enrichir positions avec countdown + session
            positions_enriched = {}
            for sym, pos in self.positions.items():
                if pos is None:
                    positions_enriched[sym] = None
                else:
                    pos_dict = asdict(pos)
                    pos_dict["seconds_until_timeout"] = compute_seconds_until_timeout(pos)
                    pos_dict["session_label_entry"] = compute_session_label(pos.entry_ts_utc)
                    positions_enriched[sym] = pos_dict

            state = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "trading_day": str(get_cme_trading_day()),
                "mode": "PAPER_TRADE_V2_FREE_RUN" if PHASE_1_FREE_RUN else "PAPER_TRADE_V2_RISK_ON",
                "dry_run": self.dry_run,
                "trade_account": TRADE_ACCOUNT,
                "trading_window_utc": f"{TRADING_WINDOW_START_UTC}h-{TRADING_WINDOW_END_UTC}h",
                "phase_1_free_run": PHASE_1_FREE_RUN,
                "risk": self.risk.state_snapshot(),
                "positions": positions_enriched,
                # Tracker reussite par setup (Jackson 02/05) — pour dashboard
                "setup_stats": self.setup_stats.snapshot(),
                "engine": "SetupEngine",
                "n_setups_total": 11,
            }
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="state", fn_name="_persist_state",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def poll_cycle(self):
        """1 cycle de poll : pour chaque symbole, eval + maybe trade + maybe close."""
        for sym in SYMBOLS:
            try:
                # Si position ouverte -> update + check exit
                if self.positions[sym] is not None:
                    bar = load_last_bar(sym)
                    if bar is None:
                        continue
                    current_price = float(bar["close"])
                    current_ts_utc = str(bar["ts_event"])
                    self.update_position_during_trade(sym, current_price, current_ts_utc)
                    continue

                # Sinon : check risk + load bar + eval setup
                can_trade, reason = self.risk.can_trade(sym)
                if not can_trade:
                    continue

                bar = load_last_bar(sym)
                if bar is None:
                    _emit("BAR_LOAD_NONE", sym=sym, reason="no_parquet")
                    continue

                # Watchdog freshness
                age = bar_age_seconds(bar)
                if age > DATA_CRIT_THR_SEC:
                    _emit("DMP_JSONL_STALE", age=int(age), limit=DATA_CRIT_THR_SEC)
                    continue

                bar_dict = bar.to_dict()
                bar_dict["ts_event"] = str(bar_dict["ts_event"])

                # ─── KILL-SWITCH Bot 2 V2 (05/05) ─────────────────────────────
                # V6 (mia2_brain_v6_databento.py) a remplace Bot 2 V2 sur Sim2.
                # Si Bot 2 V2 reste actif, double trading sur Sim2 = conflit DTC.
                # Env var MIA_BOT2_V2_PAPER_ENABLED=0 (default) skip le pipeline
                # Bot 2 V2 sans toucher Bot 3 (meme process). Reactiver via :
                # nssm set MIA-DataBento-Paper-V2 AppEnvironmentExtra MIA_BOT2_V2_PAPER_ENABLED=1
                if os.environ.get("MIA_BOT2_V2_PAPER_ENABLED", "0") != "1":
                    continue  # Bot 3 (autre boucle) continue normalement

                # 🆕 03/05 (Plan B regime_engine — Option A filtre directionnel SOFT)
                # Bot 2 (SetupEngine 11 setups) : skip UNIQUEMENT si signal contraire au
                # regime favor (forte conviction). Pas de skip si NEUTRE ou non-actionable.
                # Pattern empirique : 9/10 setups = mean reversion/RANGE, 1/10 = TREND.
                # Sans le filtre, Bot 2 prend des LONG en regime SHORT-fort = perdants.
                # Estimation impact : 15-20% trades skippes (les pires contre-tendance).
                try:
                    from CORE.regime_engine import compute_regime, REGIME_SKIP_ENABLED, REGIME_CALIB_VERSION
                    regime = compute_regime(bar_dict)
                    _emit("BOT2_REGIME_OBSERVE",
                          sym=sym, regime_mode=regime.mode, regime_favor=regime.favor,
                          regime_vol=regime.vol_regime,
                          regime_trend_votes=regime.trend_votes,
                          regime_range_votes=regime.range_votes,
                          regime_confidence=regime.confidence,
                          regime_actionable=int(regime.is_actionable),
                          calib_version=REGIME_CALIB_VERSION)
                except Exception as e:
                    _emit("BOT2_REGIME_ERROR", sym=sym,
                          err_type=type(e).__name__, err_msg=str(e)[:200])
                    regime = None
                    REGIME_SKIP_ENABLED = False  # fail-safe si import echoue

                signal_obj = self.setup_engine.evaluate(bar_dict, sym)
                if signal_obj is None:
                    continue

                # FILTRE DIRECTIONNEL SOFT (Jackson 03/05 — Option A)
                # R1 fix : kill switch env MIA_REGIME_SKIP_ENABLED (rollback rapide)
                # Skip UNIQUEMENT si :
                #   1. REGIME_SKIP_ENABLED=True (env flag)
                #   2. regime.is_actionable=True (forte conviction)
                #   3. AND regime.favor != NEUTRE
                #   4. AND signal_obj.side CONTRAIRE a regime.favor
                # Sinon : trade autorise. Ne touche PAS aux 11 setups valides.
                if REGIME_SKIP_ENABLED and regime is not None \
                        and regime.is_actionable and regime.favor != "NEUTRE":
                    sig_side = signal_obj.side  # "LONG" ou "SHORT"
                    if (sig_side == "LONG" and regime.favor == "SHORT") or \
                       (sig_side == "SHORT" and regime.favor == "LONG"):
                        _emit("BOT2_REGIME_SKIP",
                              sym=sym, sig_side=sig_side,
                              regime_favor=regime.favor, regime_mode=regime.mode,
                              regime_confidence=regime.confidence,
                              calib_version=REGIME_CALIB_VERSION,
                              setup=signal_obj.setups[0] if not signal_obj.confluence
                              else "+".join(signal_obj.setups))
                        continue

                # Trade !
                opened = self.execute_trade(signal_obj)
                if opened:
                    # Capture regime au moment de l'entry pour calibration cross-setup x regime
                    try:
                        regime_at_entry_mode = regime.mode if regime else "UNKNOWN"
                        regime_at_entry_favor = regime.favor if regime else "UNKNOWN"
                    except Exception:
                        regime_at_entry_mode = "UNKNOWN"
                        regime_at_entry_favor = "UNKNOWN"
                    _emit("SETUP_TRADE_OPEN",
                          sym=sym, side=signal_obj.side,
                          setup=signal_obj.setups[0] if not signal_obj.confluence
                          else "+".join(signal_obj.setups),
                          entry_price=signal_obj.price,
                          sl_price=self.positions[sym].sl_price,
                          tp_cap_price=self.positions[sym].tp_cap_price,
                          regime_mode=regime_at_entry_mode,
                          regime_favor=regime_at_entry_favor)
            except Exception as e:
                _emit("PY_EXCEPTION_HOT_PATH",
                      sym=sym, fn_name="poll_cycle",
                      exc_type=type(e).__name__, exc_msg=str(e))

        # ─── Bot 3 MP eval en parallele (in-process, isole) ──────────
        # Bot 3 ne perturbe pas Bot 2 : positions/stats/risk independants.
        # Phase 1 OBSERVE_ONLY : on logge les contacts + decisions sans trader.
        self._bot3_poll_cycle()

    # ═══════════════════════════════════════════════════════════════
    # BOT 3 MP — eval + persist (in-process, Sim1 isole, 03/05/2026)
    # ═══════════════════════════════════════════════════════════════

    def _bot3_reset_today_if_rollover(self) -> None:
        """Reset les compteurs Bot 3 au rollover trading day CME (18:00 ET)."""
        cur_day = str(get_cme_trading_day())
        if self.bot3_trading_day != cur_day:
            if self.bot3_trading_day is not None:
                # Vrai rollover : reset compteurs (le journal JSONL utilise CME day
                # dans son nom de fichier, donc rotation auto, pas de reset memoire)
                self.bot3_counters_today = {
                    "n_contacts": {"NQ": 0, "ES": 0},
                    "n_go": {"NQ": 0, "ES": 0},
                    "n_skip": {"NQ": 0, "ES": 0},
                    "n_veto": {"NQ": 0, "ES": 0},
                }
            self.bot3_trading_day = cur_day

    def _compute_last_bar_age(self) -> float:
        """Calcule age (secondes) derniere bar disponible pour heartbeat.

        FIX 08/05 (Plan B Bot 3 align Bot 2 V6 dual-source) :
        - Priorite : `live_cache.read_bar()` (DATA/LIVE_CACHE/_last.json, ~60s lag)
          mis a jour par databento_live_stream.py
        - Fallback : `load_last_bar()` v4 enriched (lag 18 min structurel pipeline)
        Aligne pattern Bot 2 V6 `_compute_last_bar_age_for_heartbeat()` qui lit
        le dashboard banner (provenant aussi de DMP/cache live).

        Sert au watchdog (mia_watchdog.check_jsonl_last_bar_age).
        Fallback **99999.0** si erreur = sentinel CRIT force watchdog kill.
        """
        try:
            from datetime import datetime, timezone
            try:
                from CORE import live_cache
            except ImportError:
                import live_cache  # type: ignore
            now = datetime.now(timezone.utc)
            ages = []
            for sym in SYMBOLS:
                # Priorite : live cache (frais ~60s, source Databento stream)
                try:
                    cache_bar = live_cache.read_bar(sym)
                    if cache_bar is not None and cache_bar.get("age_sec") is not None:
                        ages.append(float(cache_bar["age_sec"]))
                        continue  # live cache OK pour ce symbol, skip fallback v4
                except Exception:
                    pass
                # Fallback : v4 enriched parquet (lag 18 min mais ML cumulatives)
                try:
                    bar = load_last_bar(sym)
                    if bar is not None:
                        ts = bar.get("ts_event") if isinstance(bar, dict) else getattr(bar, "ts_event", None)
                        if ts is not None:
                            ts_dt = pd.to_datetime(ts, utc=True)
                            ages.append((now - ts_dt.to_pydatetime()).total_seconds())
                except Exception:
                    pass
            return float(max(ages)) if ages else 99999.0
        except Exception:
            return 99999.0

    def _bot3_log_trade_close(self, sym: str, pos: dict, exit_price,
                                pnl_ticks, pnl_dollars,
                                reason: str, duration_s: int,
                                pnl_estimated: bool = False) -> None:
        """SOLUTION DURABLE 06/05 (Jackson "PAS DE DETTE SOLUTION LONG TERME") :
        log trade ferme append-only dans `{cme_day}_databento_v3_trades.jsonl`.

        Pattern aligne Bot 1 (`{date}_trades.jsonl`) et Bot 2 V2
        (`{date}_databento_trades.jsonl`). Source de verite unique :
        - Audit J+1/J+7/J+30 via glob (pattern existant)
        - Restart-safe (fichier persiste, pas de buffer memoire)
        - Pas de cap, historique illimite
        - Dashboard lit le fichier (pas le state.json) pour `closed_today`

        Appele par les 2 chemins de close Bot 3 :
        - `_bot3_handle_dtc_fill` (TP/SL fill — pnl_ticks/dollars connus)
        - `_bot3_check_timeout` (TIMEOUT/RECOVERED — pnl_ticks=None car SL/TP
          orphelins fermes par MARKET CLOSE Type 208 dont le fill ne remonte
          pas par `_bot3_handle_dtc_fill` apres cleanup CIDs anti-orphelin).

        Convention pnl=None : frontend affiche `—` (pas $0) pour ne pas polluer
        le total P&L dashboard avec faux flat.
        """
        try:
            cme_day = str(get_cme_trading_day())
            fp = STATE_FILE_BOT3.parent / f"{cme_day}_databento_v3_trades.jsonl"
            fp.parent.mkdir(parents=True, exist_ok=True)
            # Schema aligne Bot 2 V2 (`databento_trades.jsonl`) pour audit cross-bot
            # unifie + reuse `_iter_trades_from_files` qui filtre par `exit_time`.
            ts_close = datetime.now(timezone.utc)
            ts_open_str = pos.get("ts_open")
            trade = {
                "schema_version": "bot3_mp_v1",
                "trade_account": "Sim1",
                "entry_time": ts_open_str,
                "exit_time": ts_close.isoformat(),
                "ts_open": ts_open_str,           # alias retro-compat
                "ts_close": ts_close.isoformat(), # alias retro-compat
                "symbol": sym,
                "side": pos.get("side"),
                "direction": pos.get("side"),
                "level": pos.get("level"),
                "action": pos.get("action"),
                "n_contracts": pos.get("n_contracts", 3),
                "n_micros": pos.get("n_contracts", 3),  # alias compat Bot 2 V2
                "entry_price": pos.get("entry_price"),
                "exit_price": float(exit_price) if exit_price is not None else None,
                "outcome": reason,
                "exit_reason": reason,
                "reason": reason,
                "pnl_ticks": None if pnl_ticks is None else float(pnl_ticks),
                "pnl_usd": None if pnl_dollars is None else float(pnl_dollars),
                "pnl_known": pnl_ticks is not None,
                "pnl_estimated": bool(pnl_estimated),  # True si Solution A approx via close bar
                "mfe_ticks": float(pos.get("mfe_ticks", 0) or 0),
                "mae_ticks": float(pos.get("mae_ticks", 0) or 0),
                "duration_sec": int(duration_s) if duration_s is not None else 0,
                "parent_id": pos.get("parent_id"),
                "tp_cid": pos.get("tp_cid"),
                "sl_cid": pos.get("sl_cid"),
                "signal_id": pos.get("signal_id"),
                "tier": pos.get("level_tier"),
                "confidence": pos.get("confidence"),
            }
            with fp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(trade, default=str) + "\n")

            # 07/05 update Bot3RiskManager (cooldown + circuit breaker)
            # Aligne Bot 1+2. Trigger sur SL/TP/TIMEOUT (tout close).
            try:
                risk_state = self._bot3_risk.on_trade_close(sym, pnl_ticks)
                if risk_state.get("breaker_triggered"):
                    _emit("BOT3_CIRCUIT_BREAKER_TRIGGERED",
                          sym=sym, consec_sl=risk_state["consecutive_sl"],
                          breaker_until=risk_state["breaker_until"],
                          pause_min=self._bot3_risk.pause_breaker_min,
                          last_pnl_ticks=risk_state["pnl_ticks"])
            except Exception as e:
                _emit("PY_EXCEPTION_HOT_PATH",
                      sym=sym, fn_name="_bot3_risk.on_trade_close",
                      exc_type=type(e).__name__, exc_msg=str(e))
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3", fn_name="_bot3_log_trade_close",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def _bot3_poll_cycle(self) -> None:
        """1 cycle Bot 3 : pour chaque symbole, eval contacts + execution DTC Sim1.

        Jackson 03/05 soir : PAPER ACTIF (compte Sim1 demo, pas de risque).
        Trades envoyes via DTC connector partage Bot 2 mais routes vers Sim1
        via TRADE_ACCOUNT_BOT3.
        """
        try:
            self._bot3_reset_today_if_rollover()
            # FIX #1 : check timeout positions actives (anti zombie)
            self._bot3_check_timeout()
            for sym in SYMBOLS:
                # FIX #3 : cap data quality 20 trades/jour 10 losses/jour
                cnt = self.bot3_counters_today
                n_trades = cnt.get("n_trades", {}).get(sym, 0)
                n_losses = cnt.get("n_losses", {}).get(sym, 0)
                from bot3_config import RISK_BOT3 as RB
                max_t = RB[sym].get("max_trades_per_day")
                max_l = RB[sym].get("max_losses_per_day")
                if max_t is not None and n_trades >= max_t:
                    if n_trades == max_t:    # log 1x au moment de l'atteinte
                        _emit("BOT3_CAP_TRADES_REACHED",
                              sym=sym, n_trades=n_trades, max=max_t)
                    continue
                if max_l is not None and n_losses >= max_l:
                    if n_losses == max_l:
                        _emit("BOT3_CAP_LOSSES_REACHED",
                              sym=sym, n_losses=n_losses, max=max_l)
                    continue
                # 04/05 fix MFE/MAE : update positions ouvertes AVANT skip "deja en position"
                # Sinon les bars d'attente n'updatent jamais MFE/MAE des positions ouvertes.
                self._bot3_update_mfe_mae()

                # 1 position max par symbole (Bot 3 isole de Bot 2)
                if sym in self._bot3_positions and self._bot3_positions[sym] is not None:
                    # 11/05 Jackson : tracer blocage "deja en position" (throttle 300s
                    # car cycle 1s × position 30min = 1800 lignes sinon. INFO suffisant
                    # car non-anomalie — c'est le filtre 1 trade max par symbole).
                    _pos = self._bot3_positions[sym]
                    self._bot3_emit_throttled("BOT3_ALREADY_IN_POSITION",
                                                throttle_sec=300.0,
                                                sym=sym,
                                                level=_pos.get("level", "?"),
                                                side=_pos.get("side", "?"),
                                                mfe_ticks=round(_pos.get("mfe_ticks", 0.0), 1))
                    continue   # position Bot 3 deja ouverte sur ce symbole

                bar = load_last_bar(sym)
                if bar is None:
                    # 11/05 Jackson : tracer blocage bar manquante (throttle 60s)
                    self._bot3_emit_throttled("BOT3_BAR_NONE", sym=sym)
                    continue
                age = bar_age_seconds(bar)
                if age > DATA_CRIT_THR_SEC:
                    # 11/05 Jackson : tracer blocage bar stale (throttle 300s ALERTE)
                    # review code-reviewer : MAJEUR + 60s = spam Discord, donc ALERTE + 300s
                    self._bot3_emit_throttled("BOT3_BAR_STALE",
                                                throttle_sec=300.0,
                                                sym=sym, age=int(age),
                                                limit=DATA_CRIT_THR_SEC)
                    continue
                bar_dict = bar.to_dict()
                bar_dict["ts_event"] = str(bar_dict["ts_event"])

                # 🆕 03/05 (Plan B regime_engine — Option A filtre directionnel SOFT)
                # Bot 3 (24 niveaux MP rules) : skip UNIQUEMENT si signal contraire au
                # regime favor (forte conviction). Pas de skip si NEUTRE ou non-actionable.
                # Estimation impact : 15-20% trades skippes (contre-tendance).
                try:
                    from CORE.regime_engine import compute_regime, REGIME_SKIP_ENABLED, REGIME_CALIB_VERSION
                    regime = compute_regime(bar_dict)
                    _emit("BOT3_REGIME_OBSERVE",
                          sym=sym,
                          regime_mode=regime.mode,
                          regime_favor=regime.favor,
                          regime_vol=regime.vol_regime,
                          regime_trend_votes=regime.trend_votes,
                          regime_range_votes=regime.range_votes,
                          regime_confidence=regime.confidence,
                          regime_actionable=int(regime.is_actionable),
                          calib_version=REGIME_CALIB_VERSION)
                except Exception as e:
                    _emit("BOT3_REGIME_ERROR", sym=sym,
                          err_type=type(e).__name__, err_msg=str(e)[:200])
                    regime = None
                    REGIME_SKIP_ENABLED = False  # fail-safe si import echoue

                signal, decisions = self.bot3_engine.evaluate(bar_dict, sym)

                for d in decisions:
                    self._bot3_record_decision(d, sym)

                self._bot3_emit_breakout_events()

                # Execution DTC si signal genere (PAPER actif)
                if signal is not None and BOT3_OBSERVE_ONLY:
                    # 11/05 Jackson : tracer signal genere mais OBSERVE_ONLY actif
                    # (paper desactive = mode test/dev) — pas de throttle, 1 par signal
                    _emit("BOT3_OBSERVE_ONLY_SKIP",
                          sym=sym, side=signal.side,
                          level=signal.level_name,
                          signal_id=getattr(signal, "signal_id", None))
                if signal is not None and not BOT3_OBSERVE_ONLY:
                    # 🆕 09/05 (Bot 3 v2) : BYPASS filter regime si bucket SIDAK / COMBO_BOOSTED
                    # Sidak strict cross-régime validé → pas besoin de double protection.
                    # Combos boostés Bonferroni-validés → idem.
                    sig_bucket = getattr(signal, 'bucket', 'HERITAGE')
                    bypass_filter = sig_bucket in ('SIDAK', 'COMBO_BOOSTED')

                    # FILTRE DIRECTIONNEL SOFT (Jackson 03/05 — Option A) — héritage seul
                    # R1 fix : kill switch env MIA_REGIME_SKIP_ENABLED (rollback rapide)
                    if not bypass_filter and REGIME_SKIP_ENABLED and regime is not None \
                            and regime.is_actionable and regime.favor != "NEUTRE":
                        sig_side = signal.side  # "LONG" ou "SHORT"
                        if (sig_side == "LONG" and regime.favor == "SHORT") or \
                           (sig_side == "SHORT" and regime.favor == "LONG"):
                            _emit("BOT3_REGIME_SKIP",
                                  sym=sym, sig_side=sig_side,
                                  level=signal.level_name,
                                  regime_favor=regime.favor,
                                  regime_mode=regime.mode,
                                  regime_confidence=regime.confidence,
                                  calib_version=REGIME_CALIB_VERSION,
                                  bucket=sig_bucket)
                            continue

                    # 🆕 B2 fix code-reviewer 09/05 : emit TOUJOURS quand bucket SIDAK/COMBO
                    # (peu importe l'état regime) pour traçabilité audit J+1.
                    # Catche aussi le cas regime=None (BOT3_REGIME_ERROR fallback).
                    if bypass_filter:
                        _emit("BOT3_FILTER_BYPASS_SIDAK_COMBO",
                              sym=sym, sig_side=signal.side,
                              level=signal.level_name,
                              bucket=sig_bucket,
                              regime_favor=(regime.favor if regime else "ERROR"),
                              regime_mode=(regime.mode if regime else "ERROR"),
                              regime_confidence=(regime.confidence if regime else 0.0),
                              regime_actionable=int(bool(regime and regime.is_actionable)))

                    self._bot3_execute_trade(signal)
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="?", fn_name="_bot3_poll_cycle",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def _compute_sltp_wall_aware(self, signal) -> dict:
        """🆕 09/05 (Bot 3 v2) — Calcule SL/TP via VRAI SLTPEngine pour bucket SIDAK/COMBO_BOOSTED.

        Convertit la bar v4 enriched (dist_*_pct en %) en input SLTPEngine
        (dist_* en ticks signés), puis appelle engine.evaluate_single().

        Returns dict :
          {valid: True, sl_ticks, tp_ticks, sl_wall, tp_wall, rr}
          OU
          {valid: False, reject: str}  → fallback standard Bot 3 dans appelant
        """
        import math
        try:
            from CORE.mia_sltp import SLTPEngine
        except ImportError:
            from mia_sltp import SLTPEngine
        try:
            from bot3_config import GUARD_RAILS_BOT3
        except ImportError:
            from CORE.bot3_config import GUARD_RAILS_BOT3

        # 🆕 B3 fix code-reviewer 09/05 : safe_float catch NaN/inf qui plantaient SLTPEngine
        def _safe_float(x, default):
            try:
                v = float(x)
                if v != v or not math.isfinite(v):
                    return default
                return v
            except (TypeError, ValueError):
                return default

        sym = signal.symbol
        direction = 1 if signal.side == "LONG" else -1
        bar = signal.bar_at_touch or {}
        cfg = GUARD_RAILS_BOT3[sym]
        tick = cfg["tick_size"]

        close_raw = bar.get("close")
        close = _safe_float(close_raw, 0.0)
        if close <= 0:
            return {"valid": False, "reject": "BAR_CLOSE_INVALID"}

        # Build SLTPEngine input : OHLC + dist_*_pct → dist_* en ticks
        sltp_input = {
            "close": close,
            "high": _safe_float(bar.get("high"), close),
            "low": _safe_float(bar.get("low"), close),
            "open": _safe_float(bar.get("open"), close),
        }
        for col in list(bar.keys()):
            if not (isinstance(col, str) and col.startswith("dist_") and col.endswith("_pct")):
                continue
            col_ticks = col[:-4]  # strip "_pct"
            v = bar.get(col)
            if v is None:
                continue
            try:
                vf = float(v)
                if vf != vf:  # NaN
                    continue
                sltp_input[col_ticks] = vf / 100.0 * close / tick
            except (ValueError, TypeError):
                continue

        # Helpers SLTPEngine consomme parfois
        for k in ("atr", "rvol", "cvd_5d_rolling_ffd"):
            v = bar.get(k)
            if v is None:
                continue
            try:
                vf = float(v)
                if vf == vf:
                    sltp_input[k] = vf
            except (ValueError, TypeError):
                pass

        try:
            engine = SLTPEngine(symbol=sym)
            result = engine.evaluate_single(sltp_input, direction)
        except Exception as e:
            return {"valid": False,
                    "reject": f"SLTPENGINE_EXCEPTION:{type(e).__name__}:{str(e)[:80]}"}

        if result.valid:
            return {
                "valid": True,
                "sl_ticks": int(round(result.sl_ticks)),
                "tp_ticks": int(round(result.tp1_ticks)),
                "sl_wall": result.sl_wall or "",
                "tp_wall": result.tp1_wall or "",
                "rr": float(result.rr_ratio or 0.0),
            }
        return {"valid": False, "reject": result.reject_reason or "UNKNOWN"}

    def _bot3_execute_trade(self, signal) -> bool:
        """Envoie le bracket DTC Bot 3 sur Sim1 (TradeAccount route le compte).

        Reuse le DTCConnector partage avec Bot 2 (meme port) mais TRADE_ACCOUNT_BOT3="Sim1".
        Tracking position dans self._bot3_positions (isole de self.positions Bot 2).
        """
        try:
            from bot3_config import TRADE_ACCOUNT_BOT3, GUARD_RAILS_BOT3
        except ImportError:
            from CORE.bot3_config import TRADE_ACCOUNT_BOT3, GUARD_RAILS_BOT3

        sym = signal.symbol

        # 07/05 GATE COOLDOWN + CIRCUIT BREAKER (Jackson directive)
        # Aligne Bot 1 (mia_paper_trader.py:1260-1272) + Bot 2 (databento_paper_trader.py:442-456).
        # Bloque re-entry < 15 min post-close + pause 60 min apres 3 SL consec.
        allow, reason = self._bot3_risk.can_trade(sym)
        if not allow:
            if reason.startswith("COOLDOWN"):
                _emit("BOT3_COOLDOWN_BLOCK",
                      sym=sym, side=signal.side,
                      level=signal.level_name, reason=reason,
                      cooldown_min=self._bot3_risk.cooldown_min)
            elif reason.startswith("CIRCUIT_BREAKER"):
                _emit("BOT3_CIRCUIT_BREAKER_BLOCK",
                      sym=sym, side=signal.side,
                      level=signal.level_name, reason=reason,
                      consec_sl=self._bot3_risk.consecutive_sl.get(sym, 0),
                      max_consec_sl=self._bot3_risk.max_consec_sl)
            return False

        cfg = GUARD_RAILS_BOT3[sym]

        # 🆕 09/05 (Bot 3 v2) : routage SL/TP selon bucket
        # SIDAK / COMBO_BOOSTED → tentative SLTPEngine wall-aware (mia_sltp.py)
        # Si SLTPEngine reject (pas de mur exploitable) → fallback standard Bot 3
        # HERITAGE → standard Bot 3 actuel (inchangé)
        sig_bucket = getattr(signal, 'bucket', 'HERITAGE')
        sltp_mode = "STANDARD"

        if sig_bucket in ('SIDAK', 'COMBO_BOOSTED'):
            sltp_result = self._compute_sltp_wall_aware(signal)
            if sltp_result['valid']:
                sl_pts = sltp_result['sl_ticks'] * cfg["tick_size"]
                tp_pts = sltp_result['tp_ticks'] * cfg["tick_size"]
                sltp_mode = "WALL_AWARE"
                _emit("BOT3_SIDAK_SLTP_WALL_AWARE",
                      sym=sym, bucket=sig_bucket,
                      level=signal.level_name, side=signal.side,
                      sl_ticks=sltp_result['sl_ticks'],
                      tp_ticks=sltp_result['tp_ticks'],
                      sl_wall=sltp_result.get('sl_wall', ''),
                      tp_wall=sltp_result.get('tp_wall', ''),
                      rr=round(sltp_result.get('rr', 0), 2))
            else:
                # Fallback standard Bot 3 (signal.sl_ticks placeholder × tp_rr_ratio)
                sl_pts = signal.sl_ticks * cfg["tick_size"]
                rr_ratio = cfg.get("tp_rr_ratio", 1.5)
                tp_pts_target = sl_pts * rr_ratio
                tp_cap_pts = cfg["tp_cap_ticks"] * cfg["tick_size"]
                tp_pts = min(tp_pts_target, tp_cap_pts)
                sltp_mode = "FALLBACK_STANDARD"
                _emit("BOT3_SIDAK_SLTP_FALLBACK",
                      sym=sym, bucket=sig_bucket,
                      level=signal.level_name, side=signal.side,
                      reject_reason=sltp_result.get('reject', '')[:80],
                      fallback_sl_ticks=int(round(sl_pts / cfg["tick_size"])),
                      fallback_tp_ticks=int(round(tp_pts / cfg["tick_size"])))
        else:
            # HERITAGE — standard Bot 3 actuel (inchangé)
            sl_pts = signal.sl_ticks * cfg["tick_size"]
            rr_ratio = cfg.get("tp_rr_ratio", 1.5)
            tp_pts_target = sl_pts * rr_ratio
            tp_cap_pts = cfg["tp_cap_ticks"] * cfg["tick_size"]
            tp_pts = min(tp_pts_target, tp_cap_pts)  # cap securite

        # 04/05 Etape 1 (anti-slippage long terme) : live ref Databento
        # au lieu de signal.price_entry_ref (parquet/JSONL DMP qui peut avoir 30s+).
        # Reduit slippage entry de ~30t a ~1-3t (valide V1 fin avril 2026).
        try:
            from CORE import live_cache
        except ImportError:
            import live_cache  # type: ignore
        live_ref, ref_source = live_cache.get_signal_entry_ref(
            sym, fallback=float(signal.price_entry_ref)
        )
        if ref_source == "FALLBACK" and live_cache.FALLBACK_MODE == "STRICT":
            _emit("LIVE_CACHE_STALE_SKIP",
                  sym=sym, bot="bot3", level=signal.level_name,
                  signal_price=float(signal.price_entry_ref),
                  fallback_mode=live_cache.FALLBACK_MODE)
            return False
        drift_signal = (live_ref - float(signal.price_entry_ref)) / cfg["tick_size"]
        _emit("LIVE_REF_USED",
              sym=sym, bot="bot3", level=signal.level_name,
              signal_price=float(signal.price_entry_ref), live_ref=live_ref,
              ref_source=ref_source, drift_ticks=round(drift_signal, 1))

        # 12/05 FIX DRIFT REJECT (cf INCIDENT_LOG 2026-05-12 03:30) :
        # Si drift signal <-> live_ref > MAX_DRIFT_TICKS, refuser le trade.
        # Signal calcule sur V4 enriched stale (lag 18min) -> drift jusqu'a 173t.
        # Au-dessus du seuil, le signal n'est plus pertinent et trade fillerait
        # au mauvais prix vs setup theorique. Pattern fail-loud anti-pattern 11.
        try:
            from CORE.bot3_config import MAX_DRIFT_TICKS
        except ImportError:
            from bot3_config import MAX_DRIFT_TICKS  # type: ignore
        drift_abs = abs(drift_signal)
        max_drift = MAX_DRIFT_TICKS.get(sym, 20)
        if drift_abs > max_drift:
            _emit("BOT_DRIFT_REJECT",
                  sym=sym, direction=signal.side,
                  drift_ticks=round(drift_abs, 1),
                  threshold=max_drift, bot="bot3_mp")
            return False
        # 12/05 FIX Jackson : alerte precoce drift 50-100% seuil pour visibilite
        # immediate dashboard avant le reject (pas attendre que ca arrive).
        if drift_abs >= max_drift * 0.5:
            _emit("BOT_DRIFT_WARNING",
                  sym=sym, direction=signal.side,
                  drift_ticks=round(drift_abs, 1),
                  threshold=max_drift, bot="bot3_mp")

        if signal.side == "LONG":
            side_int = DTC_BUY
            sl_price = live_ref - sl_pts
            tp_cap_price = live_ref + tp_pts
        else:
            side_int = DTC_SELL
            sl_price = live_ref + sl_pts
            tp_cap_price = live_ref - tp_pts

        contract = SYMBOL_TO_CONTRACT[sym]

        if self.dry_run:
            _emit("BOT3_TRADE_OPEN",
                  sym=sym, level=signal.level_name,
                  side=signal.side, action=signal.action,
                  qty=signal.n_contracts, price=signal.price_entry_ref,
                  sl=signal.sl_ticks, conf=signal.confidence)
            self._bot3_positions[sym] = {
                "signal_id": signal.signal_id,
                "level": signal.level_name,
                "side": signal.side,
                "entry_price": signal.price_entry_ref,
                "sl_price": sl_price,
                "tp_cap_price": tp_cap_price,
                "ts_open": signal.ts_event,
            }
            return True

        if not self._ensure_dtc_connected():
            # 11/05 Jackson : tracer blocage execute_trade DTC down (rare, CRITIQUE)
            _emit("BOT3_EXECUTE_DTC_DOWN",
                  sym=sym, side=signal.side,
                  level=signal.level_name,
                  signal_id=getattr(signal, "signal_id", None))
            return False

        # Bracket DTC avec TRADE_ACCOUNT="Sim1" (route le compte sur Sim1)
        # 04/05 Etape 2 : signal_ref_price + ticks pour slip metric + reprice eventuel
        sl_ticks_val = int(round(sl_pts / cfg["tick_size"]))
        tp_ticks_val = int(round(tp_pts / cfg["tick_size"]))
        parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
            symbol=contract,
            side=side_int,
            quantity=signal.n_contracts,
            sl_price=sl_price,
            tp_price=tp_cap_price,
            trade_account=TRADE_ACCOUNT_BOT3,    # "Sim1" → route Bot 3
            signal_ref_price=live_ref,
            sl_ticks=sl_ticks_val,
            tp_ticks=tp_ticks_val,
            tick_size=cfg["tick_size"],
        )
        if not parent_id:
            _emit("ORDER_REJECT", sym=sym,
                  err_code="bot3_bracket_fail", err_msg="empty parent_id")
            return False

        # 12/05 FIX entry_price (cf INCIDENT_LOG 2026-05-12 03:30) : recuperer
        # fill_price REEL broker via get_last_fill_price() au lieu de signal_price.
        # CRITIQUE Bot 3 : V4 enriched stale 18min -> drift signal<->fill jusqu'a 173t.
        # Resout race condition _handle_dtc_fill cid_type=="parent" (code mort).
        fill_price_real = 0.0
        try:
            fill_price_real = self.dtc.get_last_fill_price(parent_id) or 0.0
        except Exception:
            fill_price_real = 0.0
        entry_price_effective = fill_price_real if fill_price_real > 0 else signal.price_entry_ref
        entry_drift_ticks = 0.0
        if fill_price_real > 0:
            _dir_sign = 1 if signal.side == "LONG" else -1
            entry_drift_ticks = round(
                (fill_price_real - signal.price_entry_ref) / cfg["tick_size"] * _dir_sign, 1
            )
            _emit("BOT_ENTRY_FILL_RECORDED",
                  sym=sym, direction=signal.side,
                  signal_price=signal.price_entry_ref,
                  fill_price=fill_price_real,
                  drift_ticks=entry_drift_ticks,
                  bot="bot3_mp")

        self._bot3_positions[sym] = {
            "signal_id": signal.signal_id,
            "level": signal.level_name,
            "side": signal.side,
            "action": signal.action,
            "n_contracts": signal.n_contracts,
            "entry_price": entry_price_effective,  # 12/05 FIX : fill_price reel
            "signal_price": signal.price_entry_ref,  # 12/05 FIX : tracking signal separe
            "entry_drift_ticks": entry_drift_ticks,  # 12/05 FIX : audit drift
            "sl_price": sl_price,
            "tp_cap_price": tp_cap_price,
            "parent_id": parent_id, "tp_cid": tp_cid, "sl_cid": sl_cid,
            "ts_open": signal.ts_event,
            "mfe_ticks": 0.0, "mae_ticks": 0.0,
        }
        # FIX #1 : tracker CIDs pour routing fills Bot 3
        self._bot3_cid_index[parent_id] = {"sym": sym, "type": "parent",
                                            "signal_id": signal.signal_id}
        self._bot3_cid_index[tp_cid] = {"sym": sym, "type": "tp",
                                         "signal_id": signal.signal_id}
        self._bot3_cid_index[sl_cid] = {"sym": sym, "type": "sl",
                                         "signal_id": signal.signal_id}
        _emit("BOT3_TRADE_OPEN",
              sym=sym, level=signal.level_name,
              side=signal.side, action=signal.action,
              qty=signal.n_contracts, price=entry_price_effective,  # 12/05 FIX : fill reel
              sl=signal.sl_ticks, conf=signal.confidence)
        return True

    def _bot3_record_decision(self, decision, sym: str) -> None:
        """Enregistre une decision Bot 3 : compteurs + level_stats + log_catalog."""
        # Compteurs today
        self.bot3_counters_today["n_contacts"][sym] += 1
        if decision.decision == "GO":
            self.bot3_counters_today["n_go"][sym] += 1
        elif decision.reason.startswith("VETO_"):
            self.bot3_counters_today["n_veto"][sym] += 1
        else:
            self.bot3_counters_today["n_skip"][sym] += 1

        # Level stats
        ln = decision.level_name
        if ln not in self.bot3_level_stats:
            self.bot3_level_stats[ln] = {
                "tier": decision.level_tier,
                "n_contacts": 0,
                "n_go": 0,
                "n_skip": 0,
                "baseline_rej": get_level_baseline_rej(ln, sym),
                "baseline_pf": get_level_baseline_pf(ln, sym),
                "rejection_rate_live": None,
                "pf": None,
                "pnl_total_usd": 0,
                "avg_confidence": None,
            }
        ls = self.bot3_level_stats[ln]
        ls["n_contacts"] += 1
        if decision.decision == "GO":
            ls["n_go"] += 1
        else:
            ls["n_skip"] += 1
        # rejection_rate_live = % des contacts qui ont eu GO
        if ls["n_contacts"] > 0:
            ls["rejection_rate_live"] = round(ls["n_go"] / ls["n_contacts"] * 100, 1)

        # Recent decisions ring buffer (50 dernieres pour state.json envoie 20)
        self.bot3_recent_decisions.append({
            "ts": decision.ts_event,
            "bar_ts": decision.bar_ts,
            "symbol": decision.symbol,
            "level_name": decision.level_name,
            "level_tier": decision.level_tier,
            "decision": decision.decision,
            "reason": decision.reason,
        })
        if len(self.bot3_recent_decisions) > 50:
            self.bot3_recent_decisions = self.bot3_recent_decisions[-50:]

        # Log via log_catalog avec code stable mappe
        # FIX M-3 (review code-reviewer 03/05) : adapter les kwargs par code log
        # pour eviter VALIDATION_MISS (avant : tous les codes recevaient
        # rvol=0.0 limit=0.3 mins_since=0 hardcodes -> valeurs reelles jamais loggees).
        log_code = reason_to_log_code(decision.reason)
        ctx_d = decision.ctx or {}
        if decision.decision == "GO":
            _emit("BOT3_LEVEL_CONTACT",
                  sym=sym, level=ln,
                  dist=0.0, tier=decision.level_tier)
        elif log_code == "BOT3_VETO_VOL_DEAD":
            _emit(log_code, sym=sym,
                  rvol=ctx_d.get("rvol", 0.0), limit=0.3)
        elif log_code == "BOT3_VETO_NEWS":
            _emit(log_code, sym=sym,
                  reason=decision.reason,
                  mins_since=ctx_d.get("mins_since_news", 999))
        elif log_code == "BOT3_VETO_ROLL_DAY":
            _emit(log_code, sym=sym)
        elif log_code == "BOT3_TIER3_MISS":
            _emit(log_code, sym=sym, level=ln, detail=decision.reason)
        elif log_code == "BOT3_LEVEL_DEF_INVALID":
            _emit(log_code, sym=sym, level=ln,
                  side_value=decision.reason)
        else:
            # SKIP generique
            _emit(log_code, sym=sym, level=ln, reason=decision.reason)

    def _bot3_emit_breakout_events(self) -> None:
        """Emit codes log BOT3_BREAKOUT_* + persist JSONL ultra riche (Jackson 03/05).

        FIX #3 : evite KeyError silent (codes definis dans log_catalog mais pas emis).
        Snapshot bar-by-bar : a chaque event terminal (ACCEPTED/CRUSH/TIMEOUT),
        on persiste la trace complete (touch + acceptance_bars_data + retest)
        en JSONL pour audit Phase 1.
        Bonus 3 : tag bot_id="BOT3_MP" pour A/B comparison Bot 2 vs Bot 3.
        """
        try:
            events = self.bot3_engine._pending_breakout_events
            for evt in events:
                if evt.event_type == "PENDING":
                    _emit("BOT3_BREAKOUT_PENDING",
                          sym=evt.symbol, level=evt.level_name,
                          side=evt.side_break)
                elif evt.event_type == "ACCEPTED":
                    _emit("BOT3_BREAKOUT_ACCEPTED",
                          sym=evt.symbol, level=evt.level_name,
                          side=evt.side_break,
                          confirms=evt.payload.get("score", 0),
                          required=evt.payload.get("threshold", 2.5))
                elif evt.event_type == "CRUSH_ABSORBED":
                    _emit("BOT3_BREAKOUT_CRUSH_ABSORBED",
                          sym=evt.symbol, level=evt.level_name,
                          confirms=evt.payload.get("score", 0),
                          required=evt.payload.get("threshold", 2.5))
                    self._bot3_persist_breakout_event_jsonl(evt, terminal=True)
                elif evt.event_type == "RETEST_TIMEOUT":
                    _emit("BOT3_BREAKOUT_RETEST_TIMEOUT",
                          sym=evt.symbol, level=evt.level_name,
                          max_bars=evt.payload.get("max_bars", 30))
                    self._bot3_persist_breakout_event_jsonl(evt, terminal=True)
                # FIX code-reviewer P3 (03/05) : persister AUSSI les WINS (RETEST_ENTRY)
                # pour audit J+30 symetrique (sinon biais : que les fails loggees).
                elif evt.event_type == "RETEST_ENTRY":
                    # FIX B4 (review code-reviewer 03/05) : sl_ticks calcule
                    # cote signal builder (pas dans payload state machine).
                    # Retire du template log pour eviter "sl=0t" mensonger.
                    _emit("BOT3_BREAKOUT_RETEST_ENTRY",
                          sym=evt.symbol, level=evt.level_name,
                          side=evt.payload.get("side", "?"),
                          entry_price=evt.payload.get("entry_price", 0),
                          n_bars=evt.payload.get("n_bars_touch_to_retest", 0))
                    self._bot3_persist_breakout_event_jsonl(evt, terminal=True)
            self.bot3_engine._pending_breakout_events.clear()
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3_breakout_events", fn_name="_bot3_emit_breakout_events",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def _bot3_persist_breakout_event_jsonl(self, event, terminal: bool = False) -> None:
        """P3 + Bonus 3 (Jackson 03/05) : snapshot ultra riche breakout terminal.

        Pour chaque event DONE (CRUSH_ABSORBED, RETEST_TIMEOUT, ENTRY signal),
        persister la trace complete en JSONL pour audit J+30 :
          - bot_id (A/B tagging)
          - level_name + side_break
          - touch_bar_ts + ctx_at_touch
          - acceptance_bars_data (5 bars detaillees, close + wick + level_price)
          - retest_data si applicable
          - event_type final + payload (score, threshold, max_bars)
        """
        from pathlib import Path
        try:
            log_dir = ROOT / "LOGS" / "bot3_breakouts"
            log_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file = log_dir / f"breakout_events_{date_str}.jsonl"

            # Recuperer le state final via state_id (deja DONE = pas dans _states actif,
            # mais on a les info dans event.payload + acceptance_bars_data)
            record = {
                "ts_persist": datetime.now(timezone.utc).isoformat(),
                "bot_id": "BOT3_MP",                  # Bonus 3 A/B tagging
                "state_id": event.state_id,
                "symbol": event.symbol,
                "level_name": event.level_name,
                "side_break": event.side_break,
                "event_type": event.event_type,       # CRUSH_ABSORBED / RETEST_TIMEOUT / RETEST_ENTRY
                "terminal": terminal,
                "payload": event.payload,
            }
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3_breakout_jsonl", fn_name="_bot3_persist_breakout_event_jsonl",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def _bot3_persist_state(self) -> None:
        """Ecrit databento_paper_v3_state.json pour le dashboard Bot 3."""
        try:
            STATE_FILE_BOT3.parent.mkdir(parents=True, exist_ok=True)
            phase = "OBSERVE_ONLY" if BOT3_OBSERVE_ONLY else (
                "PAPER_FULL" if (BOT3_ENABLE_TIER2 or BOT3_ENABLE_TIER3) else "PAPER_TIER1"
            )
            state = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "trading_day": str(get_cme_trading_day()),
                "mode": "OBSERVE_ONLY" if BOT3_OBSERVE_ONLY else "PAPER_TRADE",
                "trade_account": "Sim1",        # cible Bot 3 (a confirmer Jackson)
                "trading_window_utc": "2h-21h",
                "phase": phase,
                "trade_rejections": BOT3_TRADE_REJECTIONS,
                "trade_breakouts": BOT3_TRADE_BREAKOUTS,
                "tier2_enabled": BOT3_ENABLE_TIER2,
                "tier3_enabled": BOT3_ENABLE_TIER3,
                # 04/05 SOIR FIX (audit code-reviewer) : expose les positions reelles
                # au lieu de null hardcode (Phase 1 -> Phase 2 transition oublies).
                # 05/05 SOIR FIX : `_bot3_positions[sym]` peut etre dict OU objet.
                # `.__dict__` crash sur dict (PY_EXCEPTION_HOT_PATH boucle 30s).
                # Helper inline supporte les 2 types pour serialisation JSON robuste.
                "positions": {
                    sym: (
                        None if self._bot3_positions.get(sym) is None
                        else self._bot3_positions.get(sym)
                        if isinstance(self._bot3_positions.get(sym), dict)
                        else getattr(self._bot3_positions.get(sym), "__dict__", None)
                    )
                    for sym in SYMBOLS
                },
                "level_stats": self.bot3_level_stats,
                "recent_decisions": self.bot3_recent_decisions[-20:],
                "n_contacts_today": self.bot3_counters_today["n_contacts"],
                "n_go_today": self.bot3_counters_today["n_go"],
                "n_skip_today": self.bot3_counters_today["n_skip"],
                "n_veto_today": self.bot3_counters_today["n_veto"],
                # NOTE 06/05 (refacto Plan agent GO) : closed_today retire du state.json.
                # Lecture via journal append-only `{cme_day}_databento_v3_trades.jsonl`
                # cote dashboard (pattern Bot 1/2). Source de verite unique = fichier.
                "engine": "Bot3Engine_MP",
                # FIX M-5 (review code-reviewer 03/05) : count dynamique
                # via get_active_levels (tient compte filtre symbole CUR_VPOC ES-only,
                # PVAL NQ-only, etc.). On retourne le count moyen NQ+ES / 2 arrondi.
                "n_levels_active": _bot3_count_active_levels(),
                # 11/05 J3 FIX BUG COOLDOWN : persister _bot3_risk state.
                # Sans ca, restart Bot 3 -> last_close_time={} -> cooldown 15min
                # ne se declenche pas (2 violations confirmees 11/05 : 9.1min et 3.0min).
                "risk_state": self._bot3_risk.to_dict() if hasattr(self, "_bot3_risk") else {},
            }
            tmp = STATE_FILE_BOT3.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            tmp.replace(STATE_FILE_BOT3)
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3_state", fn_name="_bot3_persist_state",
                  exc_type=type(e).__name__, exc_msg=str(e))

    def run(self):
        """Boucle principale : poll toutes les POLL_INTERVAL_SEC secondes."""
        _emit("BOOT_START", component="databento_paper_v2",
              version="1.0", pid=os.getpid())
        if not self.dry_run:
            ok = self._ensure_dtc_connected()
            if not ok:
                _emit("BOOT_FAIL_PREFLIGHT", check="dtc_initial_connect")
                print("[FATAL] DTC initial connect failed")
                return
        _emit("BOOT_READY",
              dtc=("OK" if not self.dry_run else "DRY_RUN"),
              model="SetupEngine_v1",
              data="V4_enriched_parquet")
        # Bot 3 MP boot ready
        _emit("BOT3_BOOT_READY",
              phase=("OBSERVE_ONLY" if BOT3_OBSERVE_ONLY else "PAPER"),
              tier1=True,
              tier2=BOT3_ENABLE_TIER2,
              tier3=BOT3_ENABLE_TIER3,
              observe=BOT3_OBSERVE_ONLY)

        # 11/05 J3 FIX BUG COOLDOWN : restore _bot3_risk state depuis JSON.
        # Sans ce fix, restart Bot 3 -> last_close_time={} -> cooldown 15min
        # ne se declenche pas (2 violations confirmees 11/05).
        try:
            if STATE_FILE_BOT3.exists():
                _state = json.loads(STATE_FILE_BOT3.read_text(encoding="utf-8"))
                _risk_state = _state.get("risk_state", {})
                if _risk_state:
                    self._bot3_risk.restore_from_dict(_risk_state)
                    _emit("BOT3_RISK_STATE_RESTORED",
                          n_last_close=len(self._bot3_risk.last_close_time),
                          consec_sl_nq=self._bot3_risk.consecutive_sl.get("NQ", 0),
                          consec_sl_es=self._bot3_risk.consecutive_sl.get("ES", 0))
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3_risk_restore", fn_name="restore_risk_state",
                  exc_type=type(e).__name__, exc_msg=str(e))

        # 04/05 FIX #1 anti-doublon restart : query broker positions Sim1 au boot
        # et restorer tracking si position != 0. Sans ce fix, le restart re-ouvrait
        # le meme setup -> 2 trades simultanes (incident 14:01/14:05 OPEN_830 ES).
        if not self.dry_run and self.dtc:
            self._bot3_recover_open_positions()
        # NOTE 06/05 : pas de restore du journal closed_today necessaire — la
        # solution durable utilise un fichier JSONL append-only persistant
        # (`{cme_day}_databento_v3_trades.jsonl`), restart-safe par construction.

        last_persist = 0
        last_heartbeat = 0
        while not self._stop.is_set():
            # Check STOP flags
            stop_reason = self._check_stop_flags()
            if stop_reason:
                _emit("BOT_KILL_SWITCH_ACTIVATED", n_closed=0)
                print(f"[KILL] {stop_reason}")
                # Flatten positions ouvertes
                for sym in SYMBOLS:
                    if self.positions[sym] is not None:
                        bar = load_last_bar(sym)
                        if bar is not None:
                            self._close_position(sym, float(bar["close"]),
                                                  "KILL_SWITCH",
                                                  datetime.now(timezone.utc).isoformat())
                break

            self.poll_cycle()

            # Persist state.json toutes les 30s (Bot 2 V2 + Bot 3 MP)
            now = time.time()
            if now - last_persist > 30:
                self._persist_state()
                self._bot3_persist_state()
                last_persist = now

            # FIX URGENT 06/05 (Jackson "TROP DE REDEMARAGE") : emit BOT_HEARTBEAT
            # toutes 30s pour que le watchdog voit le bot vivant. Sans ca,
            # mia_watchdog ne trouve pas BOT_HEARTBEAT dans events_*_paper_v2.jsonl
            # → SOURCE_CRIT → restart cyclique 15-25 min (34 restarts/jour observe).
            # last_bar_age = age (sec) de la derniere bar Databento processee
            # (pour Bot 3 = approximation via load_last_bar).
            if now - last_heartbeat > 30:
                last_bar_age = self._compute_last_bar_age()
                _emit("BOT_HEARTBEAT", last_bar_age=last_bar_age, bot="bot3_databento_v2")
                last_heartbeat = now

            # Attendre prochain poll
            self._stop.wait(POLL_INTERVAL_SEC)

        # 04/05 FIX #2c + REWRITE 06/05 (P1.1 anti-orphelin) : shutdown PRE-EMPTIVE
        # cancel TP/SL si traces, puis flatten Type 209/210 + verify post-cleanup.
        # Sans ce fix : SIGTERM watchdog → loop exit → positions broker preservees
        # POUR le _bot3_recover_open_positions du prochain boot. MAIS les TP/SL
        # Working restent dans le DOM. Si TP fill 50ms apres SIGTERM mais avant
        # disconnect() (drain 3s P1.2 ajoute) → OCO manuel rate → orphelin SL.
        # P1.1 : on cancel proactif au shutdown si possible.
        try:
            now_utc = datetime.now(timezone.utc)
            try:
                from bot3_config import TRADE_ACCOUNT_BOT3
            except ImportError:
                from CORE.bot3_config import TRADE_ACCOUNT_BOT3

            with self._bot3_pos_lock:
                for sym in SYMBOLS:
                    pos = self._bot3_positions.get(sym)
                    if pos is None:
                        continue
                    try:
                        ts_open = datetime.fromisoformat(pos.get("ts_open", "").replace("Z", "+00:00"))
                        dur_s = int((now_utc - ts_open).total_seconds())
                    except Exception:
                        dur_s = 0
                    _emit("BOT3_TRADE_CLOSE",
                          sym=sym, level=pos.get("level", "?"),
                          reason="SHUTDOWN_OPEN_POSITION",
                          pnl=0, mfe=pos.get("mfe_ticks", 0),
                          mae=pos.get("mae_ticks", 0), dur=dur_s)

                    # P1.1 (06/05) : pre-emptive cancel TP/SL si traces.
                    # Best-effort : exceptions silencieuses, le drain disconnect P1.2
                    # + recovery prochain boot P0.2 + sequence anti-orphelin V2 P0.3
                    # garantissent le cleanup.
                    if not self.dry_run and self.dtc:
                        for label, cid in (("tp", pos.get("tp_cid")),
                                           ("sl", pos.get("sl_cid"))):
                            if not cid:
                                continue
                            try:
                                self.dtc.cancel_order(cid, trade_account=TRADE_ACCOUNT_BOT3)
                                _emit("BOT3_SHUTDOWN_PREEMPTIVE_CANCEL",
                                      sym=sym, label=label, cid=cid[:20])
                            except Exception as e:
                                _emit("BOT3_SHUTDOWN_CANCEL_FAIL",
                                      sym=sym, label=label, err=str(e)[:200])
        except Exception as e:
            _emit("PY_EXCEPTION_HOT_PATH",
                  sym="bot3", fn_name="shutdown_close_log",
                  exc_type=type(e).__name__, exc_msg=str(e))

        _emit("BOT_SHUTDOWN", reason="stop_signal")
        if self.dtc and not self.dry_run:
            try:
                # P1.2 (06/05) : drain 3s pour laisser le _recv_loop traiter
                # un eventuel ORDER_UPDATE 301 TP/SL fill arrive juste avant SIGTERM.
                # Sans drain, OCO manuel ne s'execute pas → orphelin SL/TP.
                self.dtc.disconnect(drain_timeout=3.0)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="MIA Bot 2 V2 — PAPER_TRADE actif Sim2")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule sans envoyer d'ordres DTC (pour test)")
    args = parser.parse_args()

    print("=" * 70)
    print(f"MIA Bot 2 V2 — PAPER_TRADE actif Sim2")
    print(f"  Mode    : {'DRY-RUN (no DTC)' if args.dry_run else 'LIVE PAPER (DTC Sim2)'}")
    print(f"  Engine  : SetupEngine (11 setups validated empirically)")
    print(f"  Risk    : NQ -$900 / ES -$900 / Global -$1800 (isolated)")
    print(f"  Trailing: Phase 1 (timeout 40min, MFE/MAE collection)")
    print(f"  Symbols : {SYMBOLS}")
    print("=" * 70)

    bot = DatabentoPaperTraderV2(dry_run=args.dry_run)
    bot.run()


if __name__ == "__main__":
    main()
