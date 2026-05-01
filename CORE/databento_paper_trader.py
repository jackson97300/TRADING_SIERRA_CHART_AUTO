"""databento_paper_trader.py — Paper bot RULES sur features Databento enrichies.

Pivot 28/04/2026 (Jackson) :
  - STOP du mia_paper_trader (DMP JSONL pollué + features 30 cols seulement)
  - START sur parquet enrichi 420 cols (Databento + MQ_Lite, données propres)
  - REPRODUIRE rules dashboard (build_conseil_global) avec features enrichies
  - AJOUTER nouveaux signaux basés sur edges identifiés (dist_1d_min, trapped, edge zones)

Architecture :
  Source data:  DATA/datasets/v4_enriched/symbol={ES,NQ}.c.0/year=YYYY/month=MM/data.parquet
  Updated by:   live_pipeline_loop.py (batch 5 min)
  Rules:        ConsensusScorer multi-signaux (équivalent dashboard, sur features propres)
  SL/TP:        SLTPEngine (44 walls Tier 1/2/3, eprouve)
  Orders:       DTCConnector OCO manuel (Sim3 paper / AMP live)
  State:        DATA/PAPER_TRADES/databento_paper_state.json (consommable dashboard)

Verdict logic (porte de DASHBOARD/api/builders.py:1235-1337) :
  bull_pts / bear_pts cumulés sur 7 signaux pondérés :
    1. Bias regime (cvd_5d_rolling_ffd) — poids 2
    2. Aggressor imbalance — poids 1
    3. Position range (dist_pdh/pdl_pct) — poids 1
    4. Cross-instrument agreement (im_cross_delta_agreement_5) — poids 1
    5. MQ gates (dist_mq_call/put/hvl) — poids 1-2
    6. Trapped traders / Edge zones — poids 1 (rare event Lopez)
    7. Edge identifie 28/04 : dist_1d_min_ticks — poids 1

  Verdict :
    BUY  : bull_pts >= 4 AND bear_pts <= 2
    SELL : bear_pts >= 4 AND bull_pts <= 2
    Sinon HOLD

Risk Manager identique mia_paper_trader v2.

Usage :
    python -X utf8 CORE/databento_paper_trader.py                  # paper Sim3
    python -X utf8 CORE/databento_paper_trader.py --dry-run        # log only
    python -X utf8 CORE/databento_paper_trader.py --rth-only       # 09:30-16:00 ET
    python -X utf8 CORE/databento_paper_trader.py --live           # AMP DANGER

Auteur: MIA Trading System V2
Date  : 2026-04-28
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

from mia_sltp import SLTPEngine
# FIX 29/04 (R3 audit) : import top-level avec fallback (Bot 2 run depuis CORE/,
# Bot 1 depuis racine projet → 2 conventions a supporter).
try:
    from constants import get_cme_trading_day
except ImportError:
    from CORE.constants import get_cme_trading_day

# Logging V2 structure (memory feedback_log_debug_protocol.md)
try:
    from logging_v2 import get_logger
    _v2log = get_logger("databento_paper_trader", process="databento_paper")
except ImportError:
    _v2log = None

def _emit(code: str, **ctx):
    """Wrapper safe pour logging_v2 (no-op si module absent).

    FIX audit final 29/04 (R1) : fail-loud stderr en cas d'echec emit
    (avant : `pass` silencieux = pattern VALIDATION_MISS qui masque ajouts
    de codes oublies dans log_catalog.py). Cf awesome-error-handling.md.
    """
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception as e:
            print(f"[EMIT_FAIL] code={code} err={type(e).__name__}: {e} ctx={ctx}",
                  file=sys.stderr, flush=True)

try:
    from dtc_connector import DTCConnector, BUY as DTC_BUY, SELL as DTC_SELL
    from bot_config import DTCConfig, INSTRUMENTS as BOT_INSTRUMENTS
    _DTC_OK = True
except ImportError as _e:
    print(f"[WARN] DTC import failed : {_e}")
    _DTC_OK = False
    DTC_BUY, DTC_SELL = 1, 2

# ============================================================
# CONFIG
# ============================================================
DATASET_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"
STATE_FILE = ROOT / "DATA" / "PAPER_TRADES" / "databento_paper_state.json"
STOP_FLAG = ROOT / "DATA" / "BOT_CONTROL" / "STOP.flag"
# 01/05/2026 (Jackson) : flag local dedie au bot databento (anti-cascade).
# STOP.flag       = kill admin GLOBAL (tous les bots, intervention humaine)
# STOP_DATABENTO.flag = kill LOCAL (data feed stale Databento uniquement)
# Le bot databento lit les DEUX, mais ne CREE QUE le local quand auto-killswitch.
# Evite que stale Databento tue mia_paper_trader (DTC live = data feed different).
STOP_FLAG_LOCAL = ROOT / "DATA" / "BOT_CONTROL" / "STOP_DATABENTO.flag"
# Snapshots = log de TOUS les checks (HOLD + BUY + SELL) pour analyse posterior
SNAPSHOTS_DIR = ROOT / "DATA" / "PAPER_TRADES"

POLL_INTERVAL_SEC = 30
# Watchdog data freshness (01/05 Jackson) — seuils en secondes.
# Calibres pour TOLERER le retard structurel pipeline live_pipeline_loop (~30 min
# en periode de catch-up apres incident). Bot 2 lit DATA/datasets/v4_enriched/
# parquets enrichis par phase BUILD_V4 + PHASE_B (~5-10 min latence normale
# steady-state, plus en catch-up).
#
# v1 01/05 matin : 90/300/900 — TROP STRICT, recovery jamais declenche
#   car pipeline ne descend pas sous 90s. Bot 2 reste pause indefiniment.
# v2 01/05 14:00 (Option B Jackson) : 600/1500/2700 — aligne sur latence pipeline
#   steady-state ~5-10 min + marge catch-up.
DATA_FRESH_THR_SEC = 600       # 10 min = fresh (couvre latence pipeline normale)
DATA_WARN_THR_SEC = 1500       # 25 min = warning (alerte douce)
DATA_CRIT_THR_SEC = 2700       # 45 min = critical → kill local (STOP_DATABENTO.flag)
DATA_RECOVERY_CONSEC_HB = 3    # heartbeats consec frais avant clear flag local
COOLDOWN_MIN = 15
# 30/04 Jackson : alignement sur Bot 1 mia_paper_trader (max_trades_per_day=9999).
# PAS de limite trades/jour en paper (collecte max de donnees). Cooldown 15min
# post-close + circuit breaker 3 SL gardent la safety. Reactivation cap en mode
# LIVE capital reel plus tard.
MAX_TRADES_PER_DAY = 9999
MAX_CONSECUTIVE_SL = 3
PAUSE_AFTER_BREAKER_MIN = 60
GAMMA_CAP_BULL_BEAR = 4   # cap dashboard
# Fallback SL/TP — FIX 29/04 (Jackson) : adaptatif par symbole.
# Avant : 30t/40t fixe = ES SL $112.50 (depasse budget $75) / NQ SL $45 (sous-cale)
# Apres : budget cible $ commun → sl_ticks dynamique selon tick_value × n_micros
# Garde meme exposition $ entre ES et NQ (regles Jackson : risque equitable).
FALLBACK_SL_USD = 60.0     # cible budget SL (< $75 max sltp_engine pour marge)
FALLBACK_RR = 1.33          # Risk/Reward fallback (TP = SL × 1.33)

TICK_SIZE = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.50}

# Patterns tp_wall = "synthetic / no real wall" (Plan A_v2 30/04)
# - "FIXED_*"    : fallback budget $ quand SLTPEngine fail/timeout (cf ligne ~1735)
# - "STANDARD"   : fallback SL × 2.0 quand mia_sltp.py ne trouve aucun mur (cf mia_sltp.py:369,378)
# - "NO_WALL"    : marqueur explicite no-wall
# Si cette taxonomy evolue cote SLTPEngine, mettre a jour ICI seulement.
NO_WALL_TP_PATTERNS_PREFIX = ("FIXED_",)
NO_WALL_TP_PATTERNS_SUBSTR = ("STANDARD", "NO_WALL")


def is_synthetic_tp_wall(tp_wall_str: str) -> bool:
    """True si le tp_wall est un fallback synthetique (pas un mur reel)."""
    if not tp_wall_str:
        return False
    s = str(tp_wall_str)
    if any(s.startswith(p) for p in NO_WALL_TP_PATTERNS_PREFIX):
        return True
    return any(sub in s for sub in NO_WALL_TP_PATTERNS_SUBSTR)


def fallback_sltp_ticks(symbol: str, n_micros: int) -> tuple[int, int]:
    """Calcule fallback SL/TP en ticks depuis budget $ cible.

    ES (tick=$1.25, 3 micros) : 60 / 3.75 = 16t SL → 21t TP
    NQ (tick=$0.50, 3 micros) : 60 / 1.50 = 40t SL → 53t TP
    Risque $ identique entre ES et NQ. Pas de bias instrument.

    FIX audit R4 (29/04) : guard n_micros > 5 → assert pour bloquer
    config extreme ou plancher 8t fait depasser budget significativement.
    Configuration normale : n_micros = 1-3 (paper micro).
    """
    if n_micros > 5:
        raise ValueError(
            f"n_micros={n_micros} > 5 : config extreme non supportee par "
            f"fallback_sltp_ticks (plancher 8t pourrait depasser budget {FALLBACK_SL_USD})")
    tick_val = TICK_VALUE.get(symbol, 1.0)
    sl_ticks = max(8, int(FALLBACK_SL_USD / (tick_val * n_micros)))  # plancher 8t
    tp_ticks = int(sl_ticks * FALLBACK_RR)
    return sl_ticks, tp_ticks
SYMBOLS = ["ES", "NQ"]


@dataclass
class BotConfig:
    poll_interval: int = POLL_INTERVAL_SEC
    paper_mode: bool = True
    dry_run: bool = False
    rth_only: bool = False         # True = 09:30-16:00 ET seulement
    # A/B testing : Sim3 = mia_paper_trader (baseline), Sim2 = databento_paper_trader (challenger)
    trade_account: str = "Sim2"
    quantity: int = 3              # 3 micros (comme paper actuel)
    min_bull_for_buy: int = 4
    max_bear_for_buy: int = 2
    min_bear_for_sell: int = 4
    max_bull_for_sell: int = 2
    # FIX 30/04 (Plan A_v2 audits market-analyst + Phase 0 SHORT) :
    # Vetos paremetrables anti Pattern 11 (= reversibles via cfg, pas hard-block).
    # Gate A : VETO BUY si dist_color_dn_nearest_pct dans (0, X%] (mur color proche).
    # Gate B : VETO SHORT si TP_STANDARD/FIXED (no wall) OU room < ratio*SL.
    # Defaults bases sur audit market-analyst Bot 2 (4 mois historique parquet V4 + Phase 0 SHORTs n=8).
    veto_buy_color_wall_pct: float = 0.05    # 0 = desactive. Audit : 26.2% bars touchent ce filtre.
    veto_short_no_wall: bool = True          # False = desactive (pour A/B test ou regime BEAR confirme).
    veto_short_room_min_ratio: float = 1.5   # tp_ticks / sl_ticks doit etre >= 1.5 (room-to-target).
    # 30/04 v3 (Jackson "ON A ACHETE HAUT DE RANGE") — RangeGate confluence
    range_gate_enabled: bool = True          # False = desactive (anti pattern 11 V1)
    range_gate_min_confluence: int = 2       # >= 2/4 metriques en zone extreme = SKIP
    range_gate_mode: str = "observe"         # "observe" (log only) ou "skip" (mutation)
    # Backtest empirique 30/04 : mode skip = 65% rejection + PnL bloque +753$
    # → mode observe par defaut (R1+S3 code-reviewer). Bench 5j puis switch skip.
    # LOT 2B : EntryQualityGate (graceful degradation Bot 2 V4 manque cvd_bar_delta)
    entry_quality_gate_enabled: bool = True
    entry_quality_gate_strict: bool = False  # False = BOTH_CONTRA, True = AT_LEAST_1


# ============================================================
# CONSENSUS SCORER (porté de DASHBOARD/api/builders.py)
# ============================================================
@dataclass
class ScoreResult:
    direction: str   # "BUY" / "SELL" / "HOLD" / "CONFLIT"
    bull_pts: int
    bear_pts: int
    checks: list[str] = field(default_factory=list)


def _safe_get(bar: pd.Series, col: str, default: float = 0.0) -> float:
    if col not in bar.index:
        return default
    v = bar[col]
    if v is None or pd.isna(v):
        return default
    return float(v)


def score_consensus(bar: pd.Series, cfg: BotConfig) -> ScoreResult:
    """Score multi-signaux porte de build_conseil_global + features Databento enrichies.

    9 groupes de signaux (au lieu de 7 v1) - exploite features Phase B+++ :
      1. Bias regime (cvd_5d_rolling_ffd) - poids 2
      2. Aggressor imbalance - poids 1
      3. Position dans range (dist_pdh/pdl_pct OU position_in_range fallback)
      4. Cross-instrument (im_*) - poids 1
      5. MQ Gamma gate (cap absolu) - poids 1-2
      6. Trapped traders / Edge zones - poids 1
      7. Edge 1d_min/max - poids 1
      8. NEW v2 : Microstructure (delta_bar momentum, bar_body_pct, cvd_session)
      9. NEW v2 : GEX/Blind density (dist_gex_nearest_*, dist_blind_*, gex_cluster_count_z)

    Inputs : 1 bar (pd.Series) de DATA/datasets/v4_enriched/.
    """
    bull_pts = 0
    bear_pts = 0
    checks: list[str] = []

    # 1. BIAS regime (poids 2) — cvd_5d_rolling_ffd >0 = bull, <0 = bear
    cvd_ffd = _safe_get(bar, "cvd_5d_rolling_ffd")
    if cvd_ffd > 50:
        bull_pts += 2
        checks.append(f"bias=BULL (cvd_ffd={cvd_ffd:+.0f})")
    elif cvd_ffd < -50:
        bear_pts += 2
        checks.append(f"bias=BEAR (cvd_ffd={cvd_ffd:+.0f})")
    else:
        checks.append(f"bias=NEUTRAL (cvd_ffd={cvd_ffd:+.0f})")

    # 2. Aggressor imbalance (poids 1)
    aggr = _safe_get(bar, "aggressor_imbalance")
    if aggr > 0.3:
        bull_pts += 1
        checks.append(f"aggr=+{aggr:.2f} BULL")
    elif aggr < -0.3:
        bear_pts += 1
        checks.append(f"aggr={aggr:.2f} BEAR")

    # 3. Position range — dist_pdh_pct / dist_pdl_pct
    # Fallback : position_in_range (0=bottom, 1=top) si pdh/pdl absents
    dist_pdh = _safe_get(bar, "dist_pdh_pct")
    dist_pdl = _safe_get(bar, "dist_pdl_pct")
    pos_in_range = _safe_get(bar, "position_in_range", default=-1.0)
    if dist_pdh > 0:  # au-dessus du PDH
        bear_pts += 1   # zone de reversal court
        checks.append(f"above PDH (+{dist_pdh:.2f}%)")
    elif dist_pdl < 0:  # sous PDL
        bull_pts += 1
        checks.append(f"below PDL ({dist_pdl:.2f}%)")
    elif pos_in_range >= 0:  # fallback range_pos
        if pos_in_range <= 0.20:
            bull_pts += 1
            checks.append(f"range_bottom ({pos_in_range:.2f})")
        elif pos_in_range >= 0.80:
            bear_pts += 1
            checks.append(f"range_top ({pos_in_range:.2f})")

    # 4. Cross-instrument agreement
    cross_agree = _safe_get(bar, "im_cross_delta_agreement_5")
    if cross_agree > 0.7:
        # Les 2 instruments sont d'accord -> direction du delta_agreement signe
        # cross_agree alone n'a pas de signe; on regarde im_smt_divergence pour direction
        smt = _safe_get(bar, "im_smt_divergence")
        if smt > 0.5:
            bull_pts += 1
            checks.append(f"cross_agree+SMT bull")
        elif smt < -0.5:
            bear_pts += 1
            checks.append(f"cross_agree+SMT bear")

    # 5. MQ Gamma gate (cap absolu, comme dashboard)
    bool_above_call = _safe_get(bar, "bool_above_mq_call")
    bool_above_hvl = _safe_get(bar, "bool_above_mq_hvl")
    bool_flip = _safe_get(bar, "bool_gex_flip_zone")
    dist_mq_call = _safe_get(bar, "dist_mq_call_pct", default=10.0)
    dist_mq_put = _safe_get(bar, "dist_mq_put_pct", default=-10.0)

    # Mur Call proche (<0.1% = ~7 ticks ES @ 7000) -> bloque BUY
    block_long = (dist_mq_call > 0 and dist_mq_call < 0.10)
    # Mur Put proche -> bloque SELL
    block_short = (dist_mq_put < 0 and abs(dist_mq_put) < 0.10)
    if block_long:
        bull_pts = min(bull_pts, GAMMA_CAP_BULL_BEAR)
        checks.append(f"BLOCK_LONG mq_call near {dist_mq_call:.3f}%")
    if block_short:
        bear_pts = min(bear_pts, GAMMA_CAP_BULL_BEAR)
        checks.append(f"BLOCK_SHORT mq_put near {dist_mq_put:.3f}%")

    if bool_flip == 1:
        # Dans la zone flip, conflict potentiel
        checks.append("in GEX flip zone")

    # 6. Trapped traders / Edge zones (rare event Lopez)
    trapped_buyers = _safe_get(bar, "bn_trapped_buyers_raw")
    trapped_sellers = _safe_get(bar, "bn_trapped_sellers_raw")
    n_tr_buy_active = _safe_get(bar, "n_trapped_buyers_zones_active")
    n_tr_sell_active = _safe_get(bar, "n_trapped_sellers_zones_active")
    edge_buy = _safe_get(bar, "bar_edge_buy_zone_size")
    edge_sell = _safe_get(bar, "bar_edge_sell_zone_size")

    if trapped_sellers == 1 or n_tr_sell_active >= 2:
        bull_pts += 1   # vendeurs piégés -> squeeze BULL
        checks.append(f"trapped_sellers active")
    if trapped_buyers == 1 or n_tr_buy_active >= 2:
        bear_pts += 1   # acheteurs piégés -> SHORT continuation
        checks.append(f"trapped_buyers active")
    if edge_buy >= 1:
        bull_pts += 1
        checks.append(f"edge_buy={edge_buy:.0f}")
    if edge_sell >= 1:
        bear_pts += 1
        checks.append(f"edge_sell={edge_sell:.0f}")

    # 7. Edge 28/04 — dist_1d_min_ticks (room target bas)
    # Stocké sous nom 'dist_1d_min_ticks_pct' apres normalisation pipeline V4
    dist_1d_min = _safe_get(bar, "dist_1d_min_ticks_pct", default=0.0)
    dist_1d_max = _safe_get(bar, "dist_1d_max_ticks_pct", default=0.0)
    # En %, -100 ticks ES @ 7000 = -0.36%; on prend seuil -0.30%
    if dist_1d_min < -0.30:   # >100 ticks de room vers bas
        bear_pts += 1
        checks.append(f"room_to_1d_min ({dist_1d_min:.2f}%)")
    if dist_1d_max > 0.30:   # >100 ticks de room vers haut
        bull_pts += 1
        checks.append(f"room_to_1d_max (+{dist_1d_max:.2f}%)")

    # ─── REVERT v2 (audit code-reviewer NOGO 28/04 soir) ──────────────────────
    # Bugs detectes empiriquement sur 26435 bars ES :
    #   - bar_body_pct seuil 0.60 = code mort (max=0.65, p99=0.06, 0/26435 fires)
    #   - cvd_session corr 0.72 avec cvd_5d_rolling_ffd = double-compte bias (pattern 11)
    #   - dist_gex_up < 0.10% fire 23.3% = trop frequent pour un cap
    # → Revert au v1 (7 groupes). Backtest v1 vs v2 a faire avant re-introduction
    #   (cf .claude/rules/critical-tasks-review.md Critere 8).
    # → FEATURES list etendue conserve dans _log_snapshot (logging only, pas decision).

    # ─── VERDICT ────────────────────────────────────────────────────────
    direction = "HOLD"
    conflict = (bull_pts >= 3 and bear_pts >= 3)
    if conflict:
        direction = "CONFLIT"
    elif bull_pts >= cfg.min_bull_for_buy and bear_pts <= cfg.max_bear_for_buy:
        direction = "BUY"
    elif bear_pts >= cfg.min_bear_for_sell and bull_pts <= cfg.max_bull_for_sell:
        direction = "SELL"

    return ScoreResult(direction=direction, bull_pts=bull_pts,
                        bear_pts=bear_pts, checks=checks)


# ============================================================
# DATA LOADER
# ============================================================
def load_last_bar(symbol: str) -> Optional[pd.Series]:
    """Charge la derniere barre du parquet enrichi pour le symbole."""
    today = datetime.now(timezone.utc).date()
    partition = (DATASET_ROOT / f"symbol={symbol}.c.0" /
                 f"year={today.year}" / f"month={today.month:02d}" / "data.parquet")
    if not partition.exists():
        sym_root = DATASET_ROOT / f"symbol={symbol}.c.0"
        if not sym_root.exists():
            return None
        candidates = sorted(sym_root.glob("year=*/month=*/data.parquet"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        partition = candidates[0]
    try:
        df = pd.read_parquet(partition)
        if df.empty:
            return None
        return df.iloc[-1]
    except (OSError, ValueError) as e:
        print(f"[ERR] read parquet {partition}: {e}")
        return None


def is_rth(now_utc: datetime) -> bool:
    """RTH = 09:30-16:00 ET = 13:30-20:00 UTC (DST ete) ou 14:30-21:00 UTC (DST hiver).
    Approximation : 13:30-20:00 UTC mardi-vendredi."""
    if now_utc.weekday() >= 5:
        return False
    h = now_utc.hour + now_utc.minute / 60
    return 13.5 <= h <= 20.0


# ============================================================
# RISK MANAGER
# ============================================================
class RiskManager:
    def __init__(self):
        self.last_close_time: dict[str, datetime] = {}
        self.consecutive_sl: dict[str, int] = {"ES": 0, "NQ": 0}
        self.breaker_until: dict[str, datetime] = {}
        self.trades_today: dict[str, int] = {"ES": 0, "NQ": 0}

    def can_trade(self, symbol: str) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        if STOP_FLAG.exists():
            return False, "STOP_FLAG_PRESENT"
        if STOP_FLAG_LOCAL.exists():
            return False, "STOP_FLAG_LOCAL_DATA_STALE"
        last = self.last_close_time.get(symbol)
        if last and (now - last) < timedelta(minutes=COOLDOWN_MIN):
            return False, f"COOLDOWN_{COOLDOWN_MIN}MIN"
        until = self.breaker_until.get(symbol)
        if until and now < until:
            return False, f"CIRCUIT_BREAKER"
        if self.trades_today.get(symbol, 0) >= MAX_TRADES_PER_DAY:
            return False, "MAX_TRADES_DAY"
        return True, "OK"

    def on_trade_open(self, symbol: str):
        self.trades_today[symbol] = self.trades_today.get(symbol, 0) + 1

    def on_trade_close(self, symbol: str, pnl_ticks: float):
        now = datetime.now(timezone.utc)
        self.last_close_time[symbol] = now
        if pnl_ticks < 0:
            self.consecutive_sl[symbol] = self.consecutive_sl.get(symbol, 0) + 1
            if self.consecutive_sl[symbol] >= MAX_CONSECUTIVE_SL:
                self.breaker_until[symbol] = now + timedelta(minutes=PAUSE_AFTER_BREAKER_MIN)
                print(f"[RISK] {symbol} CIRCUIT BREAKER {PAUSE_AFTER_BREAKER_MIN}min")
        else:
            self.consecutive_sl[symbol] = 0


# ============================================================
# MAIN BOT
# ============================================================
class DatabentoPaperTrader:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.risk = RiskManager()
        self.sltp_engines = {sym: SLTPEngine(symbol=sym) for sym in SYMBOLS}
        self.stop_event = threading.Event()
        self.last_bar_ts: dict[str, Optional[Any]] = {sym: None for sym in SYMBOLS}
        self.dtc: Optional["DTCConnector"] = None
        self.active_positions: dict[str, dict] = {}
        self._pos_lock = threading.Lock()
        self._order_to_symbol: dict[str, str] = {}

        # Enrichissement logs (28/04 soir)
        self._bars_processed = {sym: 0 for sym in SYMBOLS}
        self._aggregate_buffer = {sym: {"hold": 0, "buy": 0, "sell": 0,
                                         "conflit": 0, "bull_max": 0, "bear_max": 0}
                                   for sym in SYMBOLS}
        self._last_heartbeat = time.time()
        self._last_aggregate_emit = time.time()
        self._regime_state = {sym: None for sym in SYMBOLS}        # detect change
        self._volatility_bucket = {sym: None for sym in SYMBOLS}   # detect shift
        self._session_state = None                                  # detect transition
        self._mq_levels_state = {sym: {} for sym in SYMBOLS}       # detect MQ refresh
        # 01/05 Jackson : recovery automatique data feed stale.
        # Compteur de heartbeats CONSECUTIFS avec data fraiche (last_age <= THR_FRESH).
        # Si flag local existe ET compteur >= N_RECOVERY → suppr flag + emit RECOVERED.
        self._consec_fresh_hb = 0
        self._heartbeat_interval_sec = 300    # 5 min
        self._aggregate_interval_sec = 300    # 5 min
        # FIX 29/04 : threshold aligne sur DATABENTO_DELAY_MIN (30min) + buffer
        # 5min + pipeline 5min = 2400s. Sans ca, threshold 600s = bot ne trade
        # JAMAIS avec Databento Historical (delai constant ~30min).
        # Pour live trading temps reel : upgrade Databento Live API requise.
        self._stale_threshold_sec = 2400      # 40 min
        # Storm detection BAR_KEY_PARSE_FAIL (audit backlog 29/04 reserve 2)
        # Si pipeline upstream change format bar_ts, parse fail peut firer
        # 60x/min en silence relatif. Counter fenetre glissante 60s + emit
        # CRITIQUE si >= 10 fails/min, reset apres emit pour anti-spam.
        self._bar_key_parse_fail_ts: list[float] = []
        self._bar_key_parse_fail_storm_threshold = 10
        self._bar_key_parse_fail_window_sec = 60

        # ── FIX #1 (29/04) : dedup signal cross-restart ─────────────
        # Cle = "{sym}|{bar_ts_iso}". Persiste sur disque + set in-memory.
        # Au boot reload depuis fichier. Apres trade open append.
        # Sans ca : restart bot = re-trade derniere bar (bug 28/04 soir).
        # FIX R2 (29/04 backlog) : self._date_str est maintenant attribut
        # mutable, le path est recalcule par _rotate_day_if_needed.
        # FIX 29/04 (Jackson) : convention CME (rollover 22:00 UTC = ouverture
        # Asia/CME futures), pas UTC midnight. Sans ca, journee paper desalignee
        # des sessions de trading reelles.
        self._date_str = get_cme_trading_day()
        self._traded_bars_file = SNAPSHOTS_DIR / f"{self._date_str}_databento_traded_bars.txt"
        self._traded_bar_keys: set[str] = set()
        if self._traded_bars_file.exists():
            try:
                with open(self._traded_bars_file, "r", encoding="utf-8") as f:
                    for line in f:
                        k = line.strip()
                        if k:
                            self._traded_bar_keys.add(k)
                print(f"[BOT] dedup loaded {len(self._traded_bar_keys)} bars deja tradees")
            except OSError as e:
                print(f"[BOT] dedup reload failed: {e}")

        # ── FIX #3 (29/04) : OCO recovery au boot ────────────────────
        # Au boot, si state.json contient positions actives au previous run,
        # cancel les TP/SL pending pour eviter orphelins (bug 28/04 NQ).
        self._active_positions_state_file = SNAPSHOTS_DIR / "databento_active_positions.json"

        # ── FIX 29/04 soir (Option 2 cleanup defensif au boot + stale detect) ──
        # 1. Scan archives `.processed.*` <24h pour cancel CIDs orphelins
        #    (cas manual flatten in-session : recovery normal a deja archive
        #    state.json mais des CIDs peuvent rester pending au broker).
        # 2. Stale position runtime : alerte si position ouverte > 30min sans
        #    fill (suspect manual flatten, OCO casse). Pas de cancel auto.
        # Cf chat 29/04 soir + recommandation market-analyst (recadrage Bot 2).
        self._stale_position_threshold_min = 30
        self._archive_scan_window_hours = 24

        # ── SNAPSHOT v3 (29/04) — full features dynamique ────────────
        # Jackson : "ES ET NQ DEVRAIS TOUTE LE SNAPSHOT car on mettra en
        # place des strategies". Avant : liste hardcodee 49 features.
        # Maintenant : tout le parquet enrichi (~395 features non-null par
        # bar typique), filtrage dynamique a CHAQUE bar (pas lazy build car
        # cf audit R2 : cols apparaissent au fil de la journee).
        # Skip nulls cote ecriture pour fichier raisonnable (~12KB/bar).
        self._snapshot_logged_init = False  # log UNE FOIS au boot la liste cols
        self._snapshot_excluded_prefixes = ("_last_",)  # privees enricher
        self._snapshot_excluded_exact = {
            # Partition keys + databento internals + redondants
            "year", "month", "day", "date",
            "instrument_id", "publisher_id", "rtype",
            "ts_event",  # deja dans bar_ts meta
            # Doublons collineaires (memory feedback_ml_features.md)
            "buy_sell_ratio",        # == ask_pct
            "ask_bid_imbalance",     # == delta_pct
            "delta_bar_vol_norm",    # == delta_pct
        }
        self._snapshot_excluded_suffixes = ("_ticks",)  # remplaces par _pct (data-quality.md)

        if not cfg.dry_run and _DTC_OK:
            self.dtc = DTCConnector(DTCConfig())
            connected = self.dtc.connect()
            if not connected:
                print("[BOT] DTC connect FAILED — fallback dry_run")
                self.cfg.dry_run = True
                _emit("DTC_CONNECT_FAIL", account=cfg.trade_account)
            else:
                print(f"[BOT] DTC connected (account={cfg.trade_account})")
                _emit("DTC_CONNECTED", account=cfg.trade_account)
                # FIX B1 (audit code-reviewer 28/04 NOGO) : pattern correct
                # est `on_fill` attribut, pas `register_fill_callback` (n'existe pas).
                # Sans ce fix, _on_dtc_fill JAMAIS appele = orphelins systematiques.
                # Cf BOT/dtc_connector.py:104 + pattern Sim3 mia_paper_trader.py:300.
                self.dtc.on_fill = self._on_dtc_fill
                # OCO recovery seulement si DTC OK (besoin de cancel_order)
                self._reload_active_positions_or_cancel_orphans()
                # FIX 29/04 soir (bug appel manquant) : le scan defensif etait
                # appele dans _reload_active_positions qui return early si
                # state.json absent. On l'appelle ici toujours, INDEPENDAMMENT
                # du state.json. Couvre le cas state.json clean + archives
                # <24h avec CIDs residuels (manual flatten + restart propre).
                self._scan_recent_archives_for_orphan_cancel()
                # FIX 30/04 v3 (Jackson "BOT 2 IL A PAS ATTENDU LE COOLDOWN") :
                # restaurer last_close_time depuis trades.jsonl au boot, sinon
                # restart bot reset in-memory `risk.last_close_time` → cooldown
                # 15min bypass. Cas observe : NQ 14:39:02 close → restart 14:40
                # → NQ 14:48:40 entry = 9min < 15min cooldown.
                self._restore_cooldown_state()

    def _reload_active_positions_or_cancel_orphans(self):
        """FIX #3 (29/04) — OCO recovery au boot.
        FIX 30/04 v2 (Jackson "ORDRE ORPHELIN BOT 2") — query broker AVANT cancel.

        Probleme detecte 30/04 : OCO recovery annulait les brackets de TOUTES
        les positions du state.json en supposant que le _recv_loop a rate un
        fill. MAIS si le fill n'a PAS eu lieu (position toujours active broker),
        on annule les brackets d'une position vivante → orphelin TOTAL :
        - Position broker active sans tracking cote bot
        - Pas de TP/SL → exposition non protegee jusqu'a flatten manuel

        Cas observe : ES SHORT @ 7206.50 ouvert avant 13:19 UTC, 3 restarts
        successifs dans la journee → 3x cancel brackets + archive state.json
        → position broker reste short sans bracket ni tracking.

        Fix architectural : pour CHAQUE position pending, query broker via
        DTC Type 305 (request_position_blocking, ~3s timeout) :
        - broker_qty != 0 → position TOUJOURS ACTIVE → restaurer tracking
          dans active_positions, ne PAS cancel brackets, ne PAS archiver state
        - broker_qty == 0 → fill VRAIMENT eu lieu → vrais orphelins potentiels
          (oppose reste pending) → cancel + archive (comportement original)
        - broker_qty None (timeout DTC) → conservateur : NE PAS cancel + alerte
          (attendre prochain restart pour decider, ne pas detruire des brackets
          de position qu'on ne sait pas si active)
        """
        if not self._active_positions_state_file.exists():
            return
        try:
            with open(self._active_positions_state_file, "r", encoding="utf-8") as f:
                prev_positions = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[BOT] state corrupted: {e} — reset")
            try:
                self._active_positions_state_file.unlink()
            except OSError:
                pass
            return

        if not prev_positions:
            return

        print(f"[BOT] OCO recovery : {len(prev_positions)} positions pending au previous run")
        _emit("OCO_RECOVERY_BOOT", n_positions=len(prev_positions),
              symbols=list(prev_positions.keys()))

        # ─── R1 (code-reviewer 30/04 v2) — Repopuler SIDs AVANT query broker ──
        # Le `_recv_loop` thread est ACTIF des `connect()` (BOT/dtc_connector.py:138).
        # Si un fill ORDER_UPDATE arrive pendant la query broker (3s timeout par
        # position), `_handle_order_update` tente cancel oppose via
        # `_server_order_ids[oppose_cid]` qui sinon serait vide → cancel sans SID
        # = ignore silencieux SC + orphelin (cf fix_oco_orphan.md 02/04).
        # Repopule INCONDITIONNELLEMENT pour eviter cette fenetre de race.
        for sym, pos in prev_positions.items():
            for cid_field, sid_field in (("tp_cid", "tp_sid"), ("sl_cid", "sl_sid")):
                cid = pos.get(cid_field)
                sid = pos.get(sid_field, "")
                if cid and sid:
                    self.dtc._server_order_ids[cid] = sid

        # ─── FIX 30/04 v2 — Query broker AVANT cancel pour distinguer
        # position-active vs orphelin-vrai ───────────────────────────
        positions_active_broker = {}      # sym -> pos (a restaurer)
        positions_orphan_real = {}        # sym -> pos (a cancel)
        positions_unknown = {}            # sym -> pos (timeout DTC)

        for sym, pos in prev_positions.items():
            sc_contract = BOT_INSTRUMENTS.get(sym)
            sc_contract = sc_contract.contract if sc_contract else None
            if not sc_contract:
                # Pas de contract pour ce sym → fallback comportement legacy
                positions_orphan_real[sym] = pos
                continue
            try:
                broker_qty = self.dtc.request_position_blocking(
                    symbol_contract=sc_contract,
                    trade_account=self.cfg.trade_account,
                    timeout=3.0,
                )
            except Exception as e:
                print(f"[BOT] query broker {sym} EXCEPTION: {e} — conservateur (skip)")
                positions_unknown[sym] = pos
                continue

            if broker_qty is None:
                print(f"[BOT] query broker {sym} TIMEOUT → conservateur (skip cancel)")
                _emit("STATE_VS_BROKER_MISMATCH", sym=sym,
                      state_pos=pos.get("side"), broker_pos="TIMEOUT")
                positions_unknown[sym] = pos
            elif broker_qty == 0:
                print(f"[BOT] query broker {sym} = FLAT → vraie orphelin → cancel brackets")
                positions_orphan_real[sym] = pos
            else:
                expected_qty_signed = -self.cfg.quantity if pos.get("side") == "SELL" else self.cfg.quantity
                if broker_qty != expected_qty_signed:
                    # Position active mais quantite different (partial fill ?)
                    print(f"[BOT] query broker {sym} = {broker_qty} (expected {expected_qty_signed}) "
                          f"→ position active, restaure tracking + alerte mismatch")
                    _emit("STATE_VS_BROKER_MISMATCH", sym=sym,
                          state_pos=expected_qty_signed, broker_pos=broker_qty)
                else:
                    print(f"[BOT] query broker {sym} = {broker_qty} → POSITION ACTIVE, restaure tracking")
                positions_active_broker[sym] = pos

        # ─── Restauration positions actives ───────────────────────────
        # Repopule active_positions avec les positions verifiees actives broker.
        # Le _recv_loop reprendra la surveillance des fills. Brackets restent
        # en place (pas de cancel). State.json reste en place pour persistence.
        # SIDs deja repopulees plus haut (R1 anti-race) — pas re-fait ici.
        for sym, pos in positions_active_broker.items():
            # Invariant interne : active_positions[sym]["ts_open"] doit etre
            # un datetime (heartbeat _write_state fait .isoformat() ligne 1132).
            # Le state.json contient ts_open en STRING ISO → convertir.
            ts_open_raw = pos.get("ts_open")
            if isinstance(ts_open_raw, str):
                try:
                    pos["ts_open"] = datetime.fromisoformat(ts_open_raw)
                except (ValueError, TypeError):
                    pos["ts_open"] = datetime.now(timezone.utc)
            with self._pos_lock:
                self.active_positions[sym] = pos
            # Repopule register_oco_pair pour OCO manuel
            tp_cid = pos.get("tp_cid")
            sl_cid = pos.get("sl_cid")
            if tp_cid and sl_cid and hasattr(self.dtc, "register_oco_pair"):
                try:
                    self.dtc.register_oco_pair(tp_cid, sl_cid)
                except Exception:
                    pass
            # R6 (code-reviewer 30/04 v2) : tracabilite prod
            _emit("OCO_RECOVERY_RESTORED", sym=sym,
                  side=pos.get("side"), entry=pos.get("entry"),
                  sl_price=pos.get("sl_price"), tp_price=pos.get("tp_price"))

        # ─── Cancel brackets pour orphelins vrais uniquement ─────────
        # (SIDs deja repopulees plus haut, R1 anti-race).
        if positions_orphan_real:
            for sym, pos in positions_orphan_real.items():
                for cid_field in ("tp_cid", "sl_cid"):
                    cid = pos.get(cid_field)
                    if not cid:
                        continue
                    try:
                        self.dtc.cancel_order(cid, trade_account=self.cfg.trade_account)
                        print(f"[BOT] cancel orphan {sym} {cid_field}={cid}")
                        _emit("OCO_ORPHAN_CANCELED", sym=sym, cid_field=cid_field, cid=cid)
                    except Exception as e:
                        print(f"[BOT] cancel orphan failed {cid}: {e}")
            # Wait 2s pour confirm cancel async DTC
            time.sleep(2)

        # ─── Archivage state.json ────────────────────────────────────
        # Si TOUTES les positions etaient orphelins reels → archive (comportement
        # original). Sinon → garder state.json a jour avec les positions actives
        # restaurees (sans les orphelins cancellees).
        if not positions_active_broker and not positions_unknown:
            # 100% orphelins → archive
            try:
                ts_archive = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                archive_path = self._active_positions_state_file.with_suffix(
                    f".json.processed.{ts_archive}"
                )
                self._active_positions_state_file.rename(archive_path)
                print(f"[BOT] state archived: {archive_path.name}")
            except OSError as e:
                print(f"[BOT] state archive failed (non-fatal): {e}")
        else:
            # Au moins 1 position active OU unknown → re-ecrire state avec
            # les positions a preserver (sans orphelins cancellees).
            kept_positions = {**positions_active_broker, **positions_unknown}
            try:
                with open(self._active_positions_state_file, "w", encoding="utf-8") as f:
                    json.dump(kept_positions, f, indent=2, default=str)
                print(f"[BOT] state preserved : {len(kept_positions)} positions actives/unknown "
                      f"({len(positions_orphan_real)} orphelins cancellees)")
            except OSError as e:
                print(f"[BOT] state rewrite failed (non-fatal): {e}")

    def _scan_recent_archives_for_orphan_cancel(self):
        """Scan archives `databento_active_positions.json.processed.*` des
        dernieres 24h et envoie cancel defensif sur tous les CIDs trouves.

        Couvre le cas : manual flatten in-session avec restart bot rapide
        (sequence : flatten manuel → state.json garde la pos → recovery archive
        et cancel → mais si une autre session anterieure avait des CIDs non
        traites, ils restent pending). Cancel best-effort, DTC tolere les
        cancel sur ordre deja ferme (no-op silencieux).

        Verbose minimal : log juste le nb d'archives + nb cancels envoyes.
        Pas de fail si archive corrompue (skip silencieux).

        Cf recommandation market-analyst 28/04 : "broker reconciliation au
        boot". Implementation light sans query DTC native (ce serait Option 3).
        """
        if not SNAPSHOTS_DIR.exists():
            return
        if self.dtc is None:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._archive_scan_window_hours)
        archives = list(SNAPSHOTS_DIR.glob("databento_active_positions.json.processed.*"))
        if not archives:
            return

        cids_to_cancel: list[tuple[str, str, str, str]] = []
        n_scanned = 0
        for arc in archives:
            try:
                mtime = datetime.fromtimestamp(arc.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    continue
                n_scanned += 1
                with open(arc, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for sym, pos in (data or {}).items():
                    for cid_field, sid_field in (("tp_cid", "tp_sid"), ("sl_cid", "sl_sid")):
                        cid = pos.get(cid_field)
                        sid = pos.get(sid_field, "") or ""
                        if cid:
                            cids_to_cancel.append((sym, cid_field, cid, sid))
            except (OSError, json.JSONDecodeError):
                continue

        if not cids_to_cancel:
            return

        print(f"[BOT] cleanup defensif boot : {n_scanned} archives <24h, {len(cids_to_cancel)} CIDs candidats")
        _emit("CLEANUP_DEFENSIVE_BOOT", n_archives=n_scanned, n_cids=len(cids_to_cancel))

        # Repopule _server_order_ids avant cancel (cf FIX B2 du recovery normal)
        for _sym, _role, cid, sid in cids_to_cancel:
            if sid:
                self.dtc._server_order_ids[cid] = sid

        n_sent = 0
        for sym, role, cid, _sid in cids_to_cancel:
            try:
                # ROLLBACK 29/04 soir : wait_for_sid param disparu (FIX 1
                # rollback). cancel_order non-bloquant maintenant, pas de
                # retry SID interne. Pour archives anciennes les SIDs sont
                # repopules ligne 660-663 si presents dans le JSON archive,
                # sinon cancel sans SID = SC ignore (best-effort).
                self.dtc.cancel_order(cid, trade_account=self.cfg.trade_account)
                n_sent += 1
            except Exception as e:
                print(f"[BOT] cleanup cancel {cid} failed (probable already closed): {e}")
        print(f"[BOT] cleanup defensif : {n_sent}/{len(cids_to_cancel)} cancels envoyes")
        _emit("CLEANUP_DEFENSIVE_DONE", n_sent=n_sent, n_total=len(cids_to_cancel))

    def _restore_cooldown_state(self):
        """FIX 30/04 v3 (Jackson "BOT 2 IL A PAS ATTENDU LE COOLDOWN") :
        restaurer `risk.last_close_time` depuis le DERNIER trade close de
        chaque symbole dans `_databento_trades.jsonl` du jour CME courant.

        Cause bug : `RiskManager.last_close_time` est in-memory only. Restart
        bot → reset → cooldown 15min bypass. Cas observe 30/04 : NQ exit
        14:39:02 → restart bot 14:40 (deploy fix) → NQ entry 14:48:40 = 9min
        < 15min cooldown. La safety net (cooldown post-close) etait cassee
        sur tout restart.

        Solution : au boot, scanner le JSONL trades du day CME courant, prendre
        le dernier exit_ts par symbole, set `risk.last_close_time[sym]` =
        datetime parse iso. Le `can_trade()` calculera `now - last < 15min`
        correctement meme apres restart.

        Idempotence : si pas de trades.jsonl ou symbole absent, no-op (laisse
        last_close_time vide → pas de cooldown applique = comportement normal
        au demarrage frais).
        """
        try:
            today = get_cme_trading_day()
        except Exception as e:
            print(f"[BOT] cooldown restore : get_cme_trading_day failed ({e}) — skip")
            return
        fp = SNAPSHOTS_DIR / f"{today}_databento_trades.jsonl"
        if not fp.exists():
            print(f"[BOT] cooldown restore : pas de trades aujourd'hui ({today})")
            return

        last_exit_per_sym: dict[str, datetime] = {}
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sym = rec.get("symbol")
                    exit_iso = rec.get("exit_time")
                    if not sym or not exit_iso:
                        continue
                    try:
                        exit_dt = datetime.fromisoformat(exit_iso)
                    except (ValueError, TypeError):
                        continue
                    prev = last_exit_per_sym.get(sym)
                    if prev is None or exit_dt > prev:
                        last_exit_per_sym[sym] = exit_dt
        except OSError as e:
            print(f"[BOT] cooldown restore : read failed ({e}) — skip")
            return

        if not last_exit_per_sym:
            print(f"[BOT] cooldown restore : aucun exit_time trouve dans {fp.name}")
            return

        # Set risk.last_close_time uniquement si plus recent que ce qu'on a deja
        # (fresh start = vide donc tous les trades sont applique)
        for sym, exit_dt in last_exit_per_sym.items():
            self.risk.last_close_time[sym] = exit_dt
            now = datetime.now(timezone.utc)
            elapsed_min = (now - exit_dt).total_seconds() / 60.0
            cooldown_remaining = max(0, COOLDOWN_MIN - elapsed_min)
            print(f"[BOT] cooldown restore : {sym} last_close={exit_dt.isoformat()} "
                  f"(elapsed={elapsed_min:.1f}min, cooldown_remaining={cooldown_remaining:.1f}min)")

    def _check_stale_positions(self):
        """Detecte positions ouvertes > N min sans aucun fill = potential orphan.

        Si une position est dans `active_positions` depuis > 30 min sans avoir
        recu d'ORDER_UPDATE de fill sur tp_cid/sl_cid, c'est suspect :
          - Manual flatten par Jackson en SC (TP/SL bot non touches)
          - SC crash/disconnect (DTC perdu en route)
          - OCO casse cote bot (fill recu mais non traite)

        Action : EMIT WARNING uniquement. Pas de cancel auto (risque de
        couper un trade legitime long-running). Jackson peut decider sur la
        base du log.

        Idempotent : emit max 1x par position (flag `_stale_warned`) sinon
        spam toutes les 5min tant que la pos reste.
        """
        now_utc = datetime.now(timezone.utc)
        threshold = timedelta(minutes=self._stale_position_threshold_min)
        with self._pos_lock:
            for sym, pos in list(self.active_positions.items()):
                if pos.get("_stale_warned"):
                    continue
                ts_open = pos.get("ts_open")
                if not ts_open:
                    continue
                if isinstance(ts_open, str):
                    try:
                        ts_open = datetime.fromisoformat(ts_open)
                    except (TypeError, ValueError):
                        continue
                if ts_open.tzinfo is None:
                    ts_open = ts_open.replace(tzinfo=timezone.utc)
                age = now_utc - ts_open
                if age > threshold:
                    age_min = int(age.total_seconds() / 60)
                    pos["_stale_warned"] = True
                    _emit("STALE_POSITION_WARNING", sym=sym, side=pos.get("side"),
                          entry=pos.get("entry"), age_min=age_min,
                          tp_cid=pos.get("tp_cid"), sl_cid=pos.get("sl_cid"),
                          msg_fr=(
                              f"{sym} {pos.get('side')} ouverte depuis {age_min}min "
                              "sans fill TP/SL — verifier Sierra Chart (manual flatten ?)"
                          ))
                    print(f"[BOT] STALE position {sym} {pos.get('side')} {age_min}min — verifier SC")

    def _persist_active_positions(self):
        """FIX #3 — Persiste self.active_positions sur disque (cross-restart safe).

        Appele apres ouverture/fermeture position. Format JSON serializable
        (datetime → isoformat). Permet recovery au boot via
        _reload_active_positions_or_cancel_orphans.

        FIX R1 (audit 28/04) : iteration sous _pos_lock (sinon RuntimeError
        si _on_dtc_fill mute active_positions pendant l'iteration main).
        Ecriture disque hors lock (pas de fsync sous lock).

        FIX B2 (audit 28/04) : sauve aussi tp_sid/sl_sid (ServerOrderIDs)
        pour permettre cancel valide au boot suivant.

        WARNING (audit backlog 29/04) : la phase write tmp+replace est HORS
        lock. Mono-thread safe (appele uniquement depuis main loop ou
        _on_dtc_fill qui est serialise via _pos_lock cote modification).
        Si on ajoute un autre caller multi-threaded, etendre _pos_lock pour
        couvrir tout le flow write+replace.

        FIX audit final 29/04 (R2) : snapshot atomique de _server_order_ids
        via dict(...) qui copie sous GIL en 1 op. Sinon race avec
        _recv_loop daemon (dtc_connector.py:501 mute le dict en parallele).
        """
        # Snapshot atomique sous GIL — evite race avec _recv_loop
        sids = dict(self.dtc._server_order_ids) if self.dtc else {}
        try:
            with self._pos_lock:
                serializable = {}
                for sym, p in self.active_positions.items():
                    ts_open = p.get("ts_open")
                    serializable[sym] = {
                        "parent_id": p.get("parent_id"),
                        "tp_cid": p.get("tp_cid"),
                        "sl_cid": p.get("sl_cid"),
                        "tp_sid": sids.get(p.get("tp_cid"), ""),
                        "sl_sid": sids.get(p.get("sl_cid"), ""),
                        "parent_sid": sids.get(p.get("parent_id"), ""),
                        "side": p.get("side"),
                        "entry": p.get("entry"),
                        "sl_price": p.get("sl_price"),
                        "tp_price": p.get("tp_price"),
                        "ts_open": ts_open.isoformat() if ts_open else None,
                    }
            # FIX backlog 29/04 : write atomique tmp+rename. Sans ca,
            # crash mid-write = state.json tronque = bot reload casse au boot.
            tmp = self._active_positions_state_file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(serializable, f)
            os.replace(tmp, self._active_positions_state_file)
        except OSError as e:
            print(f"[BOT] persist active positions failed: {e}")

    def _rotate_day_if_needed(self):
        """FIX R2 (29/04 backlog) — rollover quotidien pour bot 24/7.

        Si UTC date change depuis init, reset ce qui est quotidien :
          - _traded_bar_keys + _traded_bars_file (nouveau path J+1)
          - _bars_processed (compteur quotidien affiche par BOT_HEARTBEAT)
          - _aggregate_buffer (stats hold/buy/sell/conflit par symbol)
          - _bar_key_parse_fail_ts (storm window 60s — reset propre nouvelle journee)
          - last_bar_ts (sinon le 1er traitement bar de J+1 pourrait skip si
            ts identique par hasard — improbable mais safer)
          - _regime_state, _volatility_bucket, _mq_levels_state, _session_state
            (markers de transition — repartent de None pour detecter changements
            cleanement vs J-1)

        NE PAS reset : active_positions (positions transversent J+1),
        risk state (consec_losses, circuit_pause_until — timestamps absolus),
        _last_heartbeat / _last_aggregate_emit (timestamps absolus).

        Pattern porte de Sim3 mia_paper_trader.py:354-399.
        Appele en tete de boucle run() avant toute autre logique.
        FIX audit final 29/04 (S3) : reset etendu aux markers transition.
        FIX 29/04 (Jackson) : convention CME (18:00 ET bascule, pas 00:00 UTC).
        """
        current_date = get_cme_trading_day()
        if current_date == self._date_str:
            return
        prev_date = self._date_str
        print(f"[BOT] === ROLLOVER DATE {prev_date} -> {current_date} ===")
        _emit("DAY_ROLLOVER", prev_date=prev_date, new_date=current_date,
              dedup_keys_dropped=len(self._traded_bar_keys))
        self._date_str = current_date
        self._traded_bars_file = SNAPSHOTS_DIR / f"{current_date}_databento_traded_bars.txt"
        self._traded_bar_keys = set()
        # Reload si fichier J+1 existe deja (cas restart bot apres minuit)
        if self._traded_bars_file.exists():
            try:
                with open(self._traded_bars_file, "r", encoding="utf-8") as f:
                    for line in f:
                        k = line.strip()
                        if k:
                            self._traded_bar_keys.add(k)
            except OSError:
                pass
        # Reset compteurs quotidiens
        self._bars_processed = {sym: 0 for sym in SYMBOLS}
        self._aggregate_buffer = {sym: {"hold": 0, "buy": 0, "sell": 0,
                                         "conflit": 0, "bull_max": 0, "bear_max": 0}
                                   for sym in SYMBOLS}
        # FIX audit final 29/04 (S3) : reset markers transition + storm + last_bar_ts
        self._bar_key_parse_fail_ts = []
        self.last_bar_ts = {sym: None for sym in SYMBOLS}
        self._regime_state = {sym: None for sym in SYMBOLS}
        self._volatility_bucket = {sym: None for sym in SYMBOLS}
        self._mq_levels_state = {sym: {} for sym in SYMBOLS}
        self._session_state = None
        self._consec_fresh_hb = 0

    def _setup_signals(self):
        def handler(signum, frame):
            print(f"\n[BOT] Signal {signum} recu, arret propre...")
            self.stop_event.set()
        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, handler)

    def _on_dtc_fill(self, fill):
        order_id = getattr(fill, "order_id", "")
        fill_price = getattr(fill, "fill_price", 0.0)
        if not order_id or not fill_price:
            return
        with self._pos_lock:
            # FIX R2 (review code-reviewer 30/04) : reconnaitre AUSSI close_cid
            # (envoye par _check_exit_dtc en MARKET CLOSE force). Sans ce match,
            # le fill du close est ignore -> active_positions garde "active"
            # indefiniment, _check_exit_triggered=True bloque tout futur cycle.
            symbol = self._order_to_symbol.get(order_id)
            # Si pas dans _order_to_symbol, chercher dans active_positions par close_cid
            if not symbol:
                for sym, p in self.active_positions.items():
                    if order_id == p.get("close_cid"):
                        symbol = sym
                        break
            if not symbol or symbol not in self.active_positions:
                return
            pos = self.active_positions[symbol]
            is_tp = (order_id == pos.get("tp_cid"))
            is_sl = (order_id == pos.get("sl_cid"))
            is_close = (order_id == pos.get("close_cid"))
            if not (is_tp or is_sl or is_close):
                return
            entry = pos["entry"]
            side = pos["side"]
            if side == "BUY":
                pnl_ticks = (fill_price - entry) / TICK_SIZE
            else:
                pnl_ticks = (entry - fill_price) / TICK_SIZE
            # Exit type : TP/SL pour brackets normaux, ou outcome stocke pour close
            if is_close:
                exit_type = pos.get("close_outcome") or "CHECK_EXIT"
            else:
                exit_type = "TP" if is_tp else "SL"
            tick_val = TICK_VALUE.get(symbol, 1.0)
            pnl_dollar = pnl_ticks * tick_val * self.cfg.quantity
            print(f"[{symbol}] CLOSE {exit_type} fill={fill_price:.2f} "
                  f"pnl={pnl_ticks:+.0f}t (${pnl_dollar:+.2f})")
            # TRADE_CLOSE_TP/SL template attend : sym, pnl (cf log_catalog.py:97-98)
            _emit(f"TRADE_CLOSE_{exit_type}", sym=symbol, pnl=pnl_ticks,
                  entry=entry, exit_price=fill_price,
                  pnl_usd=pnl_dollar,
                  side=side, account=self.cfg.trade_account,
                  parent_id=pos.get("parent_id"))

            # Log trade ferme pour historique dashboard (BOT 2 DB)
            self._log_closed_trade(symbol, pos, fill_price, exit_type, pnl_ticks, pnl_dollar)

            # ROLLBACK 29/04 soir (verdict code-reviewer NOGO) : le double-cancel
            # tenait le `_pos_lock` pendant 2.3s d'appel `cancel_order` bloquant
            # (sleep 1s + sleep 0.3s + Timer 1s) → freeze main loop + autres
            # ORDER_UPDATE bloques. Le `dtc_connector.py:595` fait deja l'OCO
            # manuel apres cette callback, et `_verify_cancel` Timer 1s plus
            # tard fait le retry SID de maniere non-bloquante.
            #
            # FIX 30/04 (orphan persiste, screenshot Jackson) : capture opposite_cid
            # ICI dans le lock pour cancel fire-and-forget HORS du lock plus bas
            # (pattern suggere code-reviewer). Cf reserve audit : "Si meme 1
            # orphan apparait → reintroduire un cancel non-bloquant (juste
            # _send sans sleep) dans _on_dtc_fill."
            # FIX R2 30/04 : pour close (is_close), brackets deja cancelles dans
            # _check_exit_dtc avant l'envoi du close → pas besoin de FF cancel.
            if is_close:
                opposite_cid_ff = None
            else:
                opposite_cid_ff = pos.get("sl_cid") if is_tp else pos.get("tp_cid")

            del self.active_positions[symbol]
            self._order_to_symbol.pop(pos.get("parent_id"), None)
            self._order_to_symbol.pop(pos.get("tp_cid"), None)
            self._order_to_symbol.pop(pos.get("sl_cid"), None)
            self._order_to_symbol.pop(pos.get("close_cid"), None)  # R2 cleanup
        # ── FIX 30/04 — Cancel fire-and-forget HORS du lock ─────────
        # Sans sleep, sans retry. SC tolere cancel sur ordre deja
        # ferme (no-op silencieux). Si SID dispo → cancel effectif.
        # Si pas de SID → le _verify_cancel Timer 1s du dtc_connector
        # OCO manuel fera le retry. Idempotent.
        if opposite_cid_ff and self.dtc:
            try:
                sid_ff = self.dtc._server_order_ids.get(opposite_cid_ff, "")
                msg_ff = {
                    "Type": 203,  # DTC_CANCEL_ORDER
                    "ClientOrderID": opposite_cid_ff,
                    "TradeAccount": self.cfg.trade_account,
                }
                if sid_ff:
                    msg_ff["ServerOrderID"] = sid_ff
                self.dtc._send(msg_ff)
                print(f"[{symbol}] FF cancel oppose {opposite_cid_ff[:14]} (SID={'ok' if sid_ff else 'missing'})")
            except Exception as _ff_err:
                print(f"[{symbol}] FF cancel fail (non-fatal): {_ff_err}")

        self.risk.on_trade_close(symbol, pnl_ticks)
        self._persist_active_positions()  # FIX #3 — sync state.json
        self._write_state()

    def _log_closed_trade(self, symbol, pos, exit_price, exit_type, pnl_ticks, pnl_dollar):
        """Log trade ferme dans *_databento_trades.jsonl (consume par dashboard BOT 2).

        FIX Tier1 #3 (29/04) : inclut features_at_entry + bar_ts_entry pour
        Lopez meta-labeling. 1 ligne = 1 trade complet self-contained
        (features visibles a l'entree + outcome). Permet entrainement direct
        primary/meta sans join externe.

        FIX 30/04 v4 LOT 2A (Jackson "audit Bot 2 aveugle") : ajout
        `dmp_bar_at_entry` (alias de features_at_entry) + `dmp_bar_at_exit`
        (snapshot bar courante a l'exit). Symetrie avec Bot 1 trades schema.
        Permet audit features post-hoc cross-bots avec script unifie.
        """
        try:
            today = get_cme_trading_day()  # CME rollover 18:00 ET (DST-aware)
            fp = SNAPSHOTS_DIR / f"{today}_databento_trades.jsonl"
            fp.parent.mkdir(parents=True, exist_ok=True)
            ts_open = pos.get("ts_open")
            ts_close = datetime.now(timezone.utc)
            duration_sec = (ts_close - ts_open).total_seconds() if ts_open else None
            features_at_entry = pos.get("features_at_entry", {})

            # LOT 2A : snapshot bar courante a l'exit (parite Bot 1)
            # load_last_bar retourne le dernier bar Databento V4 enrichi.
            dmp_bar_at_exit = {}
            try:
                last_bar = load_last_bar(symbol)
                if last_bar is not None:
                    # Convertit pd.Series -> dict (compat JSON)
                    if hasattr(last_bar, "to_dict"):
                        dmp_bar_at_exit = last_bar.to_dict()
                    elif isinstance(last_bar, dict):
                        dmp_bar_at_exit = last_bar
            except Exception as e:
                print(f"[TRADE_LOG] dmp_bar_at_exit fetch failed: {e}")

            trade = {
                "schema_version": "databento_paper_v3_meta_labeling_with_exit_bar",
                "trade_account": self.cfg.trade_account,
                "symbol": symbol,
                "direction": "SHORT" if pos.get("side") == "SELL" else "LONG",
                "entry_price": pos.get("entry"),
                "exit_price": exit_price,
                "entry_time": ts_open.isoformat() if ts_open else None,
                "exit_time": ts_close.isoformat(),
                "bar_ts_entry": pos.get("bar_ts_entry"),  # FIX Tier1 #3
                "outcome": exit_type,
                "exit_reason": exit_type,
                "pnl_ticks": pnl_ticks,
                "pnl_usd": pnl_dollar,
                "duration_sec": duration_sec,
                "sl_ticks": pos.get("sl_ticks"),
                "tp_ticks": pos.get("tp_ticks"),
                "sl_wall": pos.get("sl_wall", "FIXED"),
                "tp_wall": pos.get("tp_wall", "FIXED"),
                "n_micros": self.cfg.quantity,
                "parent_id": pos.get("parent_id"),
                "tp_cid": pos.get("tp_cid"),
                "sl_cid": pos.get("sl_cid"),
                "bull_pts_entry": pos.get("bull_pts"),  # renommee bull_pts_entry pour clarte
                "bear_pts_entry": pos.get("bear_pts"),
                "checks_entry": pos.get("checks", []),
                "n_features_at_entry": len(features_at_entry),  # observabilite
                "features_at_entry": features_at_entry,  # FIX Tier1 #3 — Lopez meta-labeling
                # LOT 2A : alias `dmp_bar_at_entry` pour parite avec Bot 1 schema.
                # Note : Databento V4 != DMP Sierra (manque profile_shape,
                # cvd_bar_delta, next_wall_dist_ticks, range_pos, etc.).
                # Chantier futur enrichir parquet V4 via build_dataset_v4_*.
                "dmp_bar_at_entry": features_at_entry,  # alias pour audit unifie
                "dmp_bar_at_exit": dmp_bar_at_exit,     # snapshot bar exit (LOT 2A)
                "n_features_at_exit": len(dmp_bar_at_exit),
                # FIX 30/04 nuit : tracking 12 signatures game changers + score
                # Permet analyse walk-forward post-hoc sur n>=30 trades avant
                # activation du gate Phase B.
                "signatures_at_entry": pos.get("signatures_at_entry", {}),
                "sig_score_at_entry": pos.get("sig_score_at_entry", {}),
            }
            with open(fp, "a", encoding="utf-8") as f:
                f.write(json.dumps(trade, default=str) + "\n")
        except OSError as e:
            print(f"[TRADE_LOG] failed: {e}")

    def _write_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            # FIX Tier1 #3 (29/04) : exclure features_at_entry du state.json
            # dashboard (lourd ~10KB/pos). Reste accessible via trades.jsonl.
            state_pos_excluded = {"ts_open", "features_at_entry"}
            state = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "bot": "databento_paper_trader",
                "trade_account": self.cfg.trade_account,
                "active_positions": {
                    sym: {**{k: v for k, v in pos.items() if k not in state_pos_excluded},
                           "ts_open": pos["ts_open"].isoformat() if "ts_open" in pos else None}
                    for sym, pos in self.active_positions.items()
                },
                "risk": {
                    "trades_today": self.risk.trades_today,
                    "consecutive_sl": self.risk.consecutive_sl,
                },
            }
            tmp = STATE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            tmp.replace(STATE_FILE)
        except OSError as e:
            print(f"[STATE] write failed: {e}")

    def _update_position_metrics(self, symbol: str, bar: pd.Series):
        """Met a jour mfe/mae/unrealized_pnl/current_price/bars_held pour la
        position ouverte sur ce symbol.

        Appele a chaque nouvelle bar processed (debut de _process_symbol).
        Permet au dashboard d'afficher l'evolution live d'un trade Bot 2,
        comme deja le cas pour Bot 1 (state.json riche). Sans ce calcul,
        Bot 2 state.json contient UNIQUEMENT les valeurs statiques entry/sl/tp,
        donc dashboard ne peut pas afficher P/L courant ni MFE/MAE running.

        Reference Q2 Jackson 30/04 :
          "QUAND LE BOT 2 A UN TRADE ON NE VOIS PAS LE TRADE EN DIRECT EVOLUER"

        Champs ajoutes dans pos[] (auto-serialises par _write_state) :
        - unrealized_pnl_ticks : signed P/L courant en ticks
        - unrealized_pnl_usd   : signed P/L courant en USD (incluant n_micros)
        - current_price        : last bar close
        - mfe                  : max favorable excursion en ticks (running)
        - mae                  : max adverse excursion en ticks (running)
        - bars_held            : nb de bars depuis ts_open
        - last_bar_ts          : ts_event de la derniere bar processed
        """
        with self._pos_lock:
            pos = self.active_positions.get(symbol)
            if not pos:
                return
            try:
                close_price = float(bar.get("close"))
            except (TypeError, ValueError):
                return
            entry = pos.get("entry")
            side = pos.get("side")
            if not entry or not side:
                return
            # P/L unrealized signe (positif = en profit, negatif = en perte)
            if side == "BUY":
                unrealized_ticks = (close_price - entry) / TICK_SIZE
            else:  # SELL/SHORT
                unrealized_ticks = (entry - close_price) / TICK_SIZE
            # MFE/MAE rolling (init 0 a la 1ere passe)
            mfe = pos.get("mfe", 0.0) or 0.0
            mae = pos.get("mae", 0.0) or 0.0
            pos["mfe"] = max(float(mfe), unrealized_ticks)
            pos["mae"] = min(float(mae), unrealized_ticks)
            pos["unrealized_pnl_ticks"] = round(unrealized_ticks, 2)
            tick_val = TICK_VALUE.get(symbol, 1.0)
            pos["unrealized_pnl_usd"] = round(
                unrealized_ticks * tick_val * self.cfg.quantity, 2
            )
            pos["current_price"] = close_price
            pos["bars_held"] = int(pos.get("bars_held", 0)) + 1
            pos["last_bar_ts"] = str(bar.get("ts_event", ""))

    def _track_market_context(self, symbol: str, bar: pd.Series):
        """Detect changes regime / volatility / session / mq levels → emit events."""
        # Regime (cvd_5d_rolling_ffd > 50 = BULL, < -50 = BEAR, sinon NEUTRAL)
        cvd = bar.get("cvd_5d_rolling_ffd")
        if cvd is not None and not pd.isna(cvd):
            new_regime = "BULL" if cvd > 50 else "BEAR" if cvd < -50 else "NEUTRAL"
            old_regime = self._regime_state[symbol]
            if old_regime is not None and old_regime != new_regime:
                _emit("MARKET_REGIME_CHANGE", sym=symbol,
                      from_regime=old_regime, to_regime=new_regime,
                      cvd_ffd=round(float(cvd), 0))
            self._regime_state[symbol] = new_regime

        # Volatility bucket (atr_14m_pct : <0.05 = LOW, 0.05-0.15 = NORMAL, >0.15 = HIGH)
        atr_pct = bar.get("atr_14m_pct")
        if atr_pct is not None and not pd.isna(atr_pct):
            new_bucket = "LOW" if atr_pct < 0.05 else "HIGH" if atr_pct > 0.15 else "NORMAL"
            old_bucket = self._volatility_bucket[symbol]
            if old_bucket is not None and old_bucket != new_bucket:
                _emit("MARKET_VOLATILITY_SHIFT", sym=symbol,
                      atr_pct=round(float(atr_pct), 4), bucket=new_bucket)
            self._volatility_bucket[symbol] = new_bucket

        # MQ levels update — refactor I4 review (logique plus claire, sans early return)
        changed = False
        for k in ("mq_call", "mq_put", "mq_hvl"):
            v = bar.get(k)
            if v is None or pd.isna(v):
                continue
            v_f = float(v)
            prev = self._mq_levels_state[symbol].get(k)
            if prev is not None and abs(v_f - prev) > 0.01:
                changed = True
            self._mq_levels_state[symbol][k] = v_f
        if changed:
            _emit("MQ_LEVELS_UPDATE", sym=symbol,
                  mq_call=bar.get("mq_call"),
                  mq_put=bar.get("mq_put"),
                  mq_hvl=bar.get("mq_hvl"))

    def _read_live_trade_price(self, symbol: str, max_age_sec: int = 5) -> Optional[float]:
        """Lit le LAST TRADE PRICE depuis DATA/LIVE_CACHE/{sym}_last_trade.json.

        FIX 30/04 nuit : alimente par MIA-Live-OHLCV service (subscribe trades
        schema Databento Live, latence ~100-200ms). Utilise par _check_exit_dtc
        pour anticiper le hit SL/TP avant que SC fille les 2 brackets.

        Args:
            symbol : 'ES' ou 'NQ' (mappe vers ES_c_0_last_trade.json)
            max_age_sec : age max acceptable (default 5s, vu flush 0.5Hz + reseau)

        Returns:
            price (float) si cache present + frais
            None sinon
        """
        sym_full = f"{symbol}.c.0"
        safe_sym = sym_full.replace("/", "_").replace(".", "_")
        cache_path = ROOT / "DATA" / "LIVE_CACHE" / f"{safe_sym}_last_trade.json"
        try:
            if not cache_path.exists():
                return None
            file_age_sec = time.time() - cache_path.stat().st_mtime
            if file_age_sec > max_age_sec:
                return None
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            price = data.get("price")
            if price is None or not isinstance(price, (int, float)) or price <= 0:
                return None
            return float(price)
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None

    def _check_exit_dtc(self, symbol: str):
        """Check proactif : si live trade price touche SL/TP → cancel brackets + MARKET CLOSE.

        Pattern porte de mia_paper_trader.py:check_exit ligne 1600 (Bot 1).
        Difference : Bot 1 utilise banner price (DMP), Bot 2 utilise Databento
        Live trades schema (latence ~100ms) car DTC subscribe_market_data refuse
        par SC server (cf mia_paper_trader.py:312-316).

        FIX 30/04 (Jackson — bug position orpheline ES SHORT 7197.50 nuit du 30/04) :
          - Avant : ne faisait que cancel_order sur les 2 brackets. Si Sim2
            sluggish (low volume Asia), aucun fill ne suit -> position orpheline
            avec brackets cancelles + position ouverte indefiniment.
          - Apres : cancel brackets PUIS send_close_market (Type 208 + OpenCloseTrade=2)
            pour fermer la position immediatement au prix marche.
          - Idempotent : flag `_check_exit_triggered` pour eviter double fire (le
            CHECK_EXIT tourne toutes les 30s/2s tant que conditions vraies).

        Mitigation faux positifs (Plan agent verdict 30/04 nuit) :
          - Skip check si position ouverte depuis < 5s (laisser SC enregistrer
            les brackets avant de check)
          - Skip si live trade cache stale (>5s) → fallback comportement actuel
        """
        with self._pos_lock:
            if symbol not in self.active_positions:
                return
            pos = self.active_positions[symbol]
            # FIX 30/04 : idempotent guard. Si on a deja declenche le close,
            # ne pas re-tenter (sinon on accumule des MARKET CLOSE = double position).
            if pos.get("_check_exit_triggered"):
                return
            ts_open = pos.get("ts_open")
            if ts_open is None:
                return
            # Mitigation : skip si position trop fraiche (<5s)
            if isinstance(ts_open, str):
                try:
                    ts_open = datetime.fromisoformat(ts_open)
                except (TypeError, ValueError):
                    return
            if ts_open.tzinfo is None:
                ts_open = ts_open.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(timezone.utc) - ts_open).total_seconds()
            if age_s < 5:
                return  # trop frais — laisser SC enregistrer les brackets
            side = pos.get("side")
            sl = pos.get("sl_price")
            tp = pos.get("tp_price")
            tp_cid = pos.get("tp_cid")
            sl_cid = pos.get("sl_cid")
            qty = int(pos.get("n_micros") or pos.get("qty") or self.cfg.quantity or 3)
        # Hors lock pour I/O cache + cancel
        if not (sl and tp and tp_cid and sl_cid):
            return
        live_price = self._read_live_trade_price(symbol)
        if live_price is None:
            return  # cache absent ou stale → fallback OCO callback existant

        if side == "BUY":
            hit_sl = live_price <= sl
            hit_tp = live_price >= tp
        else:  # SELL
            hit_sl = live_price >= sl
            hit_tp = live_price <= tp

        if not (hit_sl or hit_tp):
            return

        outcome = "TP" if hit_tp else "SL"
        print(f"[{symbol}] CHECK_EXIT_DTC: {outcome} hit @ {live_price:.2f} "
              f"(sl={sl:.2f} tp={tp:.2f}) — cancel brackets + MARKET CLOSE")

        # FIX 30/04 : flag idempotent AVANT envoi (eviter race si timer rapide)
        with self._pos_lock:
            if symbol in self.active_positions:
                self.active_positions[symbol]["_check_exit_triggered"] = True

        # 1. Cancel les 2 brackets manuellement (idempotent SC tolere cancel
        # sur ordre deja fille). Pattern Bot 1 ligne 1668-1675.
        for cid in (tp_cid, sl_cid):
            try:
                self.dtc.cancel_order(cid, trade_account=self.cfg.trade_account)
            except Exception as e:
                print(f"  cancel {cid} fail (non-fatal): {e}")

        # 2. FIX 30/04 : MARKET CLOSE pour fermer la position au prix marche.
        # Sans ce close, Sim2 sluggish laisse la position ouverte indefiniment
        # malgre les brackets cancelles (incident ES SHORT 7197.50 nuit 30/04).
        # Utilise BOT_INSTRUMENTS pour retrouver le SC contract symbol (= pattern
        # send_market_order ligne 1717).
        try:
            sc_contract = BOT_INSTRUMENTS[symbol].contract
        except (KeyError, AttributeError):
            print(f"[{symbol}] MARKET CLOSE FAIL: pas de contract dans BOT_INSTRUMENTS")
            _emit("CHECK_EXIT_DTC_CLOSE_FAILED", sym=symbol, reason="no_contract")
            # R1 fix : re-armer le flag pour permettre re-tentative
            with self._pos_lock:
                if symbol in self.active_positions:
                    self.active_positions[symbol]["_check_exit_triggered"] = False
            return

        # ANTI-RACE (Jackson "pas de dette" 30/04) : entre les cancel_order brackets
        # ci-dessus et le send_close_market ci-dessous, un fill TP/SL pourrait
        # arriver via _on_dtc_fill et cleanup active_positions[symbol]. Si on
        # send le close apres = FLIP (close 3 sur position deja flat = ouvre 3
        # contre-position). Re-check sous lock juste avant le send.
        with self._pos_lock:
            if symbol not in self.active_positions:
                print(f"[{symbol}] CHECK_EXIT_DTC: race detected — position deja fermee par _on_dtc_fill, skip close")
                _emit("CHECK_EXIT_DTC_RACE_SKIP", sym=symbol, reason="pos_closed_by_fill")
                return

        # FIX R3 (Jackson "pas de dette" 30/04) : poll broker position via Type 305
        # pour eviter FLIP si partial fill. Bloquant 3s timeout. Pattern de
        # flatten_nq_sim2.py:41-47 wrappe dans dtc.request_position_blocking().
        broker_qty = None
        try:
            broker_qty = self.dtc.request_position_blocking(
                symbol_contract=sc_contract,
                trade_account=self.cfg.trade_account,
                timeout=3.0,
            )
        except Exception as e:
            print(f"[{symbol}] poll broker position fail (non-fatal): {e}")

        if broker_qty is None:
            # Poll fail/timeout → fallback bot qty (regression-safe)
            print(f"[{symbol}] WARNING : poll broker timeout, utilise bot qty={qty}")
            actual_qty = qty
        elif abs(broker_qty) == 0:
            # Position deja flat broker → cleanup local sans re-envoyer close
            print(f"[{symbol}] Position deja FLAT broker — skip close, cleanup local")
            _emit("CHECK_EXIT_DTC_HIT", sym=symbol, outcome=outcome,
                  live_price=live_price, sl=sl, tp=tp, age_s=round(age_s, 1),
                  cleanup="already_flat_broker")
            with self._pos_lock:
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
            self._persist_active_positions()
            self._write_state()
            return
        else:
            # Use abs(broker_qty) — peut etre < bot qty si partial fill
            actual_qty = abs(broker_qty)
            if actual_qty != qty:
                print(f"[{symbol}] WARNING : broker qty={actual_qty} != bot qty={qty} (partial fill broker?)")

        # Side oppose pour close (BUY=1, SELL=2 dans dtc_connector)
        close_side = 1 if side == "SELL" else 2  # 1=BUY, 2=SELL
        try:
            close_cid = self.dtc.send_close_market(
                symbol=sc_contract,
                side=close_side,
                quantity=actual_qty,
                trade_account=self.cfg.trade_account,
            )
        except Exception as e:
            print(f"[{symbol}] MARKET CLOSE FAIL: {e}")
            _emit("CHECK_EXIT_DTC_CLOSE_FAILED", sym=symbol, reason=f"exc:{type(e).__name__}")
            # R1 fix : re-armer le flag pour permettre re-tentative
            with self._pos_lock:
                if symbol in self.active_positions:
                    self.active_positions[symbol]["_check_exit_triggered"] = False
            return

        # R1 fix : si close_cid vide (pas connecte), re-armer flag
        if not close_cid:
            print(f"[{symbol}] MARKET CLOSE FAIL: close_cid vide (DTC pas connecte ?)")
            _emit("CHECK_EXIT_DTC_CLOSE_FAILED", sym=symbol, reason="empty_cid")
            with self._pos_lock:
                if symbol in self.active_positions:
                    self.active_positions[symbol]["_check_exit_triggered"] = False
            return

        print(f"[{symbol}] MARKET CLOSE sent cid={close_cid[:12]} "
              f"qty={actual_qty} side={'BUY' if close_side == 1 else 'SELL'} (force close)")

        # R2 fix : tracker close_cid dans la position pour que _on_dtc_fill
        # le reconnaisse au moment du fill et fasse le cleanup complet
        # (state.json + journal trade + risk.on_trade_close).
        # Reserve B review #2 : registre _order_to_symbol coherent avec parent/tp/sl
        # (le fallback search dans _on_dtc_fill reste de toute facon en filet).
        with self._pos_lock:
            if symbol in self.active_positions:
                self.active_positions[symbol]["close_cid"] = close_cid
                self.active_positions[symbol]["close_outcome"] = outcome
                self.active_positions[symbol]["close_live_price"] = live_price
                self._order_to_symbol[close_cid] = symbol

        _emit("CHECK_EXIT_DTC_HIT", sym=symbol, outcome=outcome,
              live_price=live_price, sl=sl, tp=tp, age_s=round(age_s, 1))

    def _read_live_cache_bar(self, symbol: str, max_age_sec: int = 180) -> Optional[dict]:
        """Lit la bar LIVE complete depuis DATA/LIVE_CACHE alimente par MIA-Live-OHLCV.

        Retourne dict avec {ts_event_iso, ts_event_ns, open, high, low, close, volume, age_sec}
        ou None si cache absent/stale.

        01/05/2026 (Jackson "INADMISSIBLE 33 min retard") : permet a Bot 2 de scorer
        sur close LIVE au lieu de close parquet (delay 30 min Historical Databento).
        """
        sym_full = f"{symbol}.c.0"
        safe_sym = sym_full.replace("/", "_").replace(".", "_")
        cache_path = ROOT / "DATA" / "LIVE_CACHE" / f"{safe_sym}_last.json"
        try:
            if not cache_path.exists():
                return None
            file_age_sec = time.time() - cache_path.stat().st_mtime
            if file_age_sec > max_age_sec:
                return None
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            close = data.get("close")
            if close is None or not isinstance(close, (int, float)) or close <= 0:
                return None
            data["age_sec"] = file_age_sec
            return data
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None

    def _enrich_bar_with_live(self, symbol: str, bar: pd.Series) -> tuple[pd.Series, Optional[pd.Timestamp]]:
        """Enrichit la bar parquet (delay 30 min) avec OHLC + distances LIVE.

        Strategy :
        - Lire bar LIVE (latence ~60s)
        - Si dispo + plus recente que parquet : remplacer OHLC + ts_event
        - Garder features structurelles parquet (mq_levels daily, day_type, profile_shape, cvd_*)
        - Recalculer features price-driven : dist_mq_*_pct, dist_pdh/pdl_pct, bool_above_*
        - Logger drift (close_parquet, close_live, delta_ticks) max 1x/min

        Returns:
            (bar_enrichie, live_ts_or_None)
            live_ts_or_None : ts_event LIVE si override applique, None si fallback parquet
        """
        live = self._read_live_cache_bar(symbol, max_age_sec=180)
        if live is None:
            return bar, None  # fallback parquet (no-op)

        parquet_close = float(bar.get("close", 0) or 0)
        live_close = float(live["close"])
        if parquet_close <= 0 or live_close <= 0:
            return bar, None  # safety

        delta_ticks = (live_close - parquet_close) / TICK_SIZE

        # Logger drift (rate-limited 1x/min/symbol)
        if not hasattr(self, "_last_drift_log"):
            self._last_drift_log = {}
        last_log = self._last_drift_log.get(symbol, 0)
        if time.time() - last_log > 60:
            self._last_drift_log[symbol] = time.time()
            _emit("LIVE_BAR_OVERRIDE",
                  sym=symbol,
                  close_parquet=round(parquet_close, 2),
                  close_live=round(live_close, 2),
                  delta_ticks=round(delta_ticks, 1),
                  live_age_sec=round(live["age_sec"], 1))

        # Build enriched bar
        new_bar = bar.copy()
        new_bar["close"] = live_close
        new_bar["open"] = float(live["open"])
        new_bar["high"] = float(live["high"])
        new_bar["low"] = float(live["low"])
        new_bar["volume"] = float(live["volume"])

        # Recalculer dist_mq_*_pct avec close LIVE (mq_* levels broadcast daily, restent valides)
        for level_key in ("mq_call", "mq_put", "mq_hvl"):
            level = bar.get(level_key)
            if level is not None and pd.notna(level):
                level_f = float(level)
                if level_f > 0:
                    dist_key = f"dist_{level_key}_pct"
                    new_bar[dist_key] = (live_close - level_f) / live_close * 100
                    bool_key = f"bool_above_{level_key}"
                    new_bar[bool_key] = 1 if live_close > level_f else 0

        # Recalculer dist_pdh/pdl_pct avec close LIVE
        for level_key, dist_key in [("pdh", "dist_pdh_pct"), ("pdl", "dist_pdl_pct")]:
            level = bar.get(level_key)
            if level is not None and pd.notna(level):
                level_f = float(level)
                if level_f > 0:
                    new_bar[dist_key] = (live_close - level_f) / live_close * 100

        # ts_event LIVE pour le check stale en aval (safe parsing — code-reviewer 01/05)
        live_ts = None
        try:
            ts_iso = live.get("ts_event_iso")
            if ts_iso:
                live_ts = pd.to_datetime(ts_iso).tz_localize(None)
        except (ValueError, TypeError, KeyError):
            live_ts = None  # iso malforme → fallback parquet ts_event en aval
        return new_bar, live_ts

    def _read_live_cache_close(self, symbol: str, fallback: float, max_age_sec: int = 300) -> float:
        """Lit le close LIVE depuis DATA/LIVE_CACHE alimente par MIA-Live-OHLCV.

        Args:
            symbol : 'ES' ou 'NQ' (sera mappe vers 'ES_c_0' pour le filename)
            fallback : valeur a retourner si cache absent ou stale
            max_age_sec : age max acceptable du fichier cache (default 300s = 5 min)

        Returns:
            close_live (float) si cache present + frais
            fallback (float) sinon

        FIX 29/04 soir (5e voie Plan agent) : decouple le timing de fill du
        timing du parquet enrichi (qui a 30 min de retard). Resout slippage
        entry 23t observed sur ES Bot 2.
        """
        # Mapping symbol -> filename (ES.c.0 -> ES_c_0)
        sym_full = f"{symbol}.c.0"
        safe_sym = sym_full.replace("/", "_").replace(".", "_")
        cache_path = ROOT / "DATA" / "LIVE_CACHE" / f"{safe_sym}_last.json"
        try:
            if not cache_path.exists():
                return fallback
            file_age_sec = time.time() - cache_path.stat().st_mtime
            if file_age_sec > max_age_sec:
                # Cache stale (service MIA-Live-OHLCV down ou dans pause weekend)
                return fallback
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            close_live = data.get("close")
            if close_live is None or not isinstance(close_live, (int, float)) or close_live <= 0:
                return fallback
            return float(close_live)
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return fallback

    def _emit_periodic_logs(self):
        """Heartbeat + Aggregate emit toutes les 5 min + state.json toutes les 30s."""
        now = time.time()

        # FIX 30/04 (Jackson dashboard divergence) : write state.json toutes 30s
        # meme sans trade. Avant, _write_state() etait appele uniquement sur
        # OPEN/CLOSE position → state.json stale 4h+ pendant pause = dashboard
        # affiche "Bot DOWN" alors que le service tourne. Heartbeat 30s couvre
        # le seuil dashboard 120s avec marge.
        if not hasattr(self, "_last_state_write_ts"):
            self._last_state_write_ts = 0
        if (now - self._last_state_write_ts) >= 30:
            try:
                self._write_state()
                self._last_state_write_ts = now
            except Exception as e:
                print(f"[BOT] heartbeat _write_state failed: {e}")

        # Heartbeat
        if (now - self._last_heartbeat) >= self._heartbeat_interval_sec:
            with self._pos_lock:
                n_pos = len(self.active_positions)
            total_bars = sum(self._bars_processed.values())
            # FIX 29/04 soir (Option 2) : detection stale position runtime.
            # Tourne au meme rythme que heartbeat (5min) — overhead negligeable.
            self._check_stale_positions()
            # Last bar age
            ages = []
            for sym, ts in self.last_bar_ts.items():
                if ts is not None:
                    try:
                        # FIX audit final 29/04 (S2) : pattern robuste tz-aware/naive.
                        # `pd.to_datetime(x, utc=True)` force UTC quoi que x soit
                        # (naive interprete UTC, tz-aware converti UTC), puis
                        # tz_localize(None) drop tz pour comparison naive.
                        bar_dt = pd.to_datetime(ts, utc=True).tz_localize(None)
                        now_n = datetime.now(timezone.utc).replace(tzinfo=None)
                        ages.append((now_n - bar_dt).total_seconds())
                    except (TypeError, ValueError):
                        pass
            last_age = int(max(ages)) if ages else -1
            _emit("BOT_HEARTBEAT", account=self.cfg.trade_account,
                  n_positions=n_pos, total_bars=total_bars, last_bar_age=last_age)
            self._last_heartbeat = now

            # P0 01/05/2026 (Jackson "ON AURAIS DU AVOIR UN ALERT SUR DONNER PERIMER")
            # Watchdog data freshness : si last_bar_age depasse seuil, alerter.
            #
            # Refactor 01/05 soir (anti-cascade + recovery auto) :
            # - WARN     : > DATA_WARN_THR_SEC  → emit MAJEUR (monitoring, pas action)
            # - CRITICAL : > DATA_CRIT_THR_SEC  → cree STOP_DATABENTO.flag (LOCAL, pas global)
            # - FRESH    : <= DATA_FRESH_THR_SEC consec DATA_RECOVERY_CONSEC_HB → suppr flag
            #
            # Le flag LOCAL pause UNIQUEMENT ce bot (anti-cascade : mia_paper_trader
            # DTC live continue sa route). Recovery auto pour eviter intervention
            # humaine quand stream Databento revient (cas reconnect WebSocket).
            if last_age > 0:
                # Mise a jour compteur recovery (incremental ou reset)
                if last_age <= DATA_FRESH_THR_SEC:
                    self._consec_fresh_hb += 1
                else:
                    self._consec_fresh_hb = 0

                if last_age > DATA_CRIT_THR_SEC:
                    # CRITICAL : creer flag LOCAL UNIQUEMENT s'il n'existe pas deja
                    # (idempotent — anti-pollution logs si stale persiste plusieurs hb)
                    if not STOP_FLAG_LOCAL.exists():
                        try:
                            STOP_FLAG_LOCAL.parent.mkdir(parents=True, exist_ok=True)
                            STOP_FLAG_LOCAL.write_text(
                                f"auto_killswitch_data_feed_stale_critical_"
                                f"age_{last_age}s_at_{datetime.now(timezone.utc).isoformat()}",
                                encoding="utf-8"
                            )
                            _emit("DATA_FEED_STALE_CRITICAL",
                                  account=self.cfg.trade_account,
                                  last_age_sec=last_age,
                                  threshold_sec=DATA_CRIT_THR_SEC,
                                  action="local_killswitch_created")
                            print(f"[DATA_STALE] CRITICAL: bar age {last_age}s "
                                  f"> {DATA_CRIT_THR_SEC}s — STOP_DATABENTO.flag (local) creee")
                        except Exception as e:
                            print(f"[DATA_STALE] auto-killswitch fail: {e}")
                elif last_age > DATA_WARN_THR_SEC:
                    _emit("DATA_FEED_STALE_WARNING",
                          account=self.cfg.trade_account,
                          last_age_sec=last_age,
                          threshold_sec=DATA_WARN_THR_SEC)

                # RECOVERY : flag local existe + N heartbeats consec fresh → clear.
                # Compteur NON reset apres recovery : si data re-stale, on garde le max
                # pour permettre re-recovery rapide (semantique : "data est stable").
                if (STOP_FLAG_LOCAL.exists()
                        and self._consec_fresh_hb >= DATA_RECOVERY_CONSEC_HB
                        and last_age <= DATA_FRESH_THR_SEC):
                    try:
                        STOP_FLAG_LOCAL.unlink()
                        _emit("DATA_FEED_RECOVERED",
                              account=self.cfg.trade_account,
                              last_age_sec=last_age,
                              consec_fresh_hb=self._consec_fresh_hb,
                              action="local_killswitch_removed")
                        print(f"[DATA_RECOVERY] OK: bar age {last_age}s "
                              f"x{self._consec_fresh_hb} consec — STOP_DATABENTO.flag supprime")
                    except Exception as e:
                        print(f"[DATA_RECOVERY] flag removal fail: {e}")

        # Aggregate (HOLD reason)
        if (now - self._last_aggregate_emit) >= self._aggregate_interval_sec:
            for sym in SYMBOLS:
                ag = self._aggregate_buffer[sym]
                n_total = ag["hold"] + ag["buy"] + ag["sell"] + ag["conflit"]
                if n_total > 0:
                    _emit("HOLD_REASON_AGGREGATE", sym=sym, n_bars=n_total,
                          bull_max=ag["bull_max"], bear_max=ag["bear_max"],
                          n_hold=ag["hold"], n_buy=ag["buy"],
                          n_sell=ag["sell"], n_conflit=ag["conflit"])
                # Reset buffer
                self._aggregate_buffer[sym] = {"hold": 0, "buy": 0, "sell": 0,
                                                "conflit": 0, "bull_max": 0, "bear_max": 0}
            self._last_aggregate_emit = now

    def _filter_snapshot_col(self, col: str) -> bool:
        """Retourne True si la col doit etre incluse dans le snapshot.

        Filtre par exclusion (Option B feature-engineer audit) :
          - Drop prefixes prives (`_last_*`)
          - Drop exacts (partition keys, databento internals, doublons collineaires)
          - Drop suffixes (`_ticks` deja remplaces par `_pct` cf data-quality.md)

        FIX audit R2 (29/04) : pas de lazy build (cf R2 code-reviewer).
        Filtrage dynamique a chaque bar pour capturer les cols qui
        apparaissent au fil de la journee (ex: rolling lag10 calcule
        apres 10 bars, asia_open quand session Asia ouvre).
        Cout : ~400 string ops/bar = <0.1ms = negligeable.
        """
        if col.startswith(self._snapshot_excluded_prefixes):
            return False
        if col in self._snapshot_excluded_exact:
            return False
        if col.endswith(self._snapshot_excluded_suffixes):
            return False
        return True

    def _inject_dist_ticks_from_pct(self, bar_dict: dict) -> dict:
        """FIX Tier1 #10 (29/04) — Convertit dist_*_pct → dist_* en ticks.

        Pipeline V4 `add_pct_normalized_distances` (build_dataset_v4_dmp_databento.py:793)
        DROP les versions brutes en ticks au profit de _pct (anti-fuite instrument).
        SLTPEngine (`mia_sltp.py:141+`) cherche `dist_*` (sans `_pct`) pour trouver
        les walls. Sans conversion : reject systematique → fallback FIXED 30/40t.

        Formule inverse :
          dist_X_pct = (dist_X_ticks * TICK_SIZE / close) * 100
          → dist_X_ticks = dist_X_pct * close / (TICK_SIZE * 100)

        Bug observe 28/04 : 3/4 trades Bot 2 DB ont SL fallback FIXED_30T (NQ
        SL=30t ≈ 7.5pts = stoppe sur n'importe quel pullback). Trade #1
        (qui avait SLTPEngine valide via CUR_VAH wall) = exception.
        """
        close = bar_dict.get("close")
        if close is None or pd.isna(close) or close <= 0:
            return bar_dict

        # NOTE : dist_1d_min_ticks_pct et dist_1d_max_ticks_pct gardent le suffix
        # `_ticks` au milieu du nom (heritage build_dataset). On les mappe explicitement.
        # FIX audit 29/04 : swing naming mismatch — V4 produit
        # `dist_last_swing_*_pct` mais SLTPEngine cherche `dist_swing_*` (T2).
        # Sans alias, le wall swing T2 etait mort dans V4. Apres alias, il revit.
        # Toutes les autres dist_*_pct → dist_* simplement (drop _pct).
        special_map = {
            "dist_1d_min_ticks_pct": "dist_1d_min_ticks",
            "dist_1d_max_ticks_pct": "dist_1d_max_ticks",
            "dist_last_swing_high_pct": "dist_swing_high",
            "dist_last_swing_low_pct": "dist_swing_low",
        }

        # Iter sur copy keys car on mute le dict
        for key in list(bar_dict.keys()):
            if not key.endswith("_pct"):
                continue
            if not key.startswith("dist_"):
                continue
            v = bar_dict[key]
            if v is None or pd.isna(v):
                continue
            try:
                ticks = float(v) * float(close) / (TICK_SIZE * 100.0)
            except (TypeError, ValueError):
                continue
            # Nom cible : special_map si applicable, sinon drop _pct
            target_key = special_map.get(key, key[:-4])  # "_pct" = 4 chars
            # Ne pas ecraser une valeur deja presente (precedence aux ticks bruts)
            if target_key not in bar_dict or bar_dict[target_key] is None or pd.isna(bar_dict[target_key]):
                bar_dict[target_key] = ticks
        return bar_dict

    def _extract_features_dict(self, bar: pd.Series) -> dict:
        """Helper : extrait dict features filtre + JSON-safe depuis bar Series.

        Reutilise par _log_snapshot ET stockage features_at_entry pour
        Lopez meta-labeling (snapshot↔outcome linking 29/04).
        """
        features = {}
        for f in bar.index:
            if not self._filter_snapshot_col(f):
                continue
            v = bar[f]
            try:
                if v is None or pd.isna(v):
                    continue
            except (TypeError, ValueError):
                continue
            if isinstance(v, (np.bool_, bool)):
                features[f] = bool(v)
            elif isinstance(v, (np.integer, int)):
                features[f] = int(v)
            elif isinstance(v, (np.floating, float)):
                features[f] = float(v)
            else:
                features[f] = str(v)
        return features

    def _log_snapshot(self, symbol: str, bar: pd.Series, result: ScoreResult,
                       traded: bool, sltp_info: Optional[dict] = None,
                       parent_id: Optional[str] = None):
        """Log snapshot pour analyse posterior. 1 ligne par bar fermee.
        Permet de mesurer l'edge des rules (TP vs SL) sur les features enrichies.

        Snapshot v3 (29/04) : full features dynamique. Skip nulls cote ecriture.
        Schema_version pour permettre migration future.
        FIX 29/04 (Tier1 #3) : `parent_id` permet jointure posterior avec
        outcome trade dans `databento_trades.jsonl`.
        """
        try:
            today = get_cme_trading_day()  # CME rollover 18:00 ET (DST-aware)
            fp = SNAPSHOTS_DIR / f"{today}_databento_paper_snapshots.jsonl"
            fp.parent.mkdir(parents=True, exist_ok=True)

            # Tracabilite : log UNE FOIS au boot count cols incluses + exemple
            # de cols exclues (audit posterior si feature manquante au snapshot).
            if not self._snapshot_logged_init:
                included = [c for c in bar.index if self._filter_snapshot_col(c)]
                excluded = [c for c in bar.index if not self._filter_snapshot_col(c)]
                print(f"[SNAPSHOT v3] init: {len(included)} cols incluses, "
                      f"{len(excluded)} exclues (sample: {excluded[:10]})")
                self._snapshot_logged_init = True

            features = self._extract_features_dict(bar)

            snapshot = {
                "schema_version": "snapshot_v3_full_features",
                "ts": datetime.now(timezone.utc).isoformat(),
                "bar_ts": str(bar.get("ts_event"))[:19],
                "symbol": symbol,
                "direction": result.direction,
                "bull_pts": result.bull_pts,
                "bear_pts": result.bear_pts,
                "checks": result.checks,
                "traded": traded,
                "parent_id": parent_id,  # FIX Tier1 #3 : link snapshot↔outcome
                "n_features": len(features),  # observabilite : combien de features non-null
                "features": features,
                "sltp": sltp_info,
            }
            with open(fp, "a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, default=str) + "\n")
        except OSError as e:
            print(f"[SNAPSHOT] write failed: {e}")

    def _process_symbol(self, symbol: str):
        bar = load_last_bar(symbol)
        if bar is None:
            # 01/05 Jackson "TRACK TOUT" : trace les rejets silencieux
            _emit("BAR_LOAD_NONE", sym=symbol,
                  reason="load_last_bar returned None (parquet absent or empty)")
            return
        # 01/05/2026 (Jackson "INADMISSIBLE 33 min") : enrichir bar parquet (delay
        # 30 min Historical Databento) avec close LIVE (latence 60s) + recompute
        # dist_mq_*_pct + dist_pdh/pdl_pct sur close LIVE. Features structurelles
        # (mq_levels, day_type, profile_shape, cvd_*) restent du parquet (broadcast
        # daily, valides). Si LIVE_CACHE absent/stale → fallback parquet (no-op).
        bar, live_ts = self._enrich_bar_with_live(symbol, bar)

        # ts_event de reference : LIVE si dispo, sinon parquet
        bar_ts = live_ts if live_ts is not None else bar.get("ts_event")
        if self.last_bar_ts[symbol] is not None and bar_ts == self.last_bar_ts[symbol]:
            return
        self.last_bar_ts[symbol] = bar_ts

        # Q2 (Jackson 30/04 "Bot 2 dashboard pas d'evolution live") :
        # maj metrics position (mfe/mae/unrealized_pnl/current_price/bars_held)
        # AVANT validation stale (pour ne pas perdre une bar valide en cas de
        # stale-skip qui se debloque). Auto-serialise via _write_state heartbeat 30s.
        self._update_position_metrics(symbol, bar)

        # ── FIX #2 (29/04) — Bar staleness HARD SKIP ─────────────────
        # Avant : juste WARN. Maintenant : SKIP si bar_age > threshold.
        # Cause bug 28/04 : pipeline gele 1h+ → bot tradait sur bar 16:10
        # alors qu'il etait 17:17 UTC.
        # FIX audit final 29/04 (S2) : pattern robuste tz-aware/naive.
        try:
            bar_dt = pd.to_datetime(bar_ts, utc=True).tz_localize(None)
            now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
            bar_age = (now_naive - bar_dt).total_seconds()
            if bar_age > self._stale_threshold_sec:
                _emit("BAR_STALE_SKIP", sym=symbol,
                      age=int(bar_age), threshold=self._stale_threshold_sec,
                      bar_ts=str(bar_ts)[:19])
                return  # HARD SKIP — pas de trade sur bar perimee
        except (TypeError, ValueError):
            bar_age = None

        # ── ENRICH 2 — Scoring null features detection ────────────────
        # FIX I3 review : substituer dist_pdh/pdl_pct (0% fill partial day) par
        # features fill rate >95% prouve : close, total_vol/volume, atr_14m_pct
        sample_features = ["close", "cvd_5d_rolling_ffd",
                            "aggressor_imbalance", "atr_14m_pct"]
        n_null = sum(1 for f in sample_features
                     if f not in bar.index or bar.get(f) is None or pd.isna(bar.get(f)))
        null_pct = (n_null / len(sample_features)) * 100
        if null_pct > 50:
            _emit("SCORING_NULL_FEATURES", sym=symbol, null_pct=round(null_pct, 1))

        # RTH filter (01/05 Jackson "TRACK TOUT" : plus de silent skip)
        if self.cfg.rth_only:
            now_utc = datetime.now(timezone.utc)
            if not is_rth(now_utc):
                _emit("GATE_RTH_BLOCK", sym=symbol,
                      reason="hors RTH (Regular Trading Hours 13:30-20:00 UTC)",
                      hour_utc=now_utc.hour + now_utc.minute / 60)
                return

        # ── ECO CALENDAR + SESSION GATE (29/04 soir) ─────────────────
        # Calendrier UNIFIE qui regroupe :
        #   1. Events eco High USD (FOMC, NFP, CPI, PCE) : -15min/+30min
        #   2. Open US volatility 09:15-09:45 ET (15:15-15:45 Paris ete)
        #   3. Post-MOC pause 15:30-18:15 ET (lun-jeu) — PILOT 30j 30/04
        #   4. Weekend : vendredi 15:30 ET → dimanche 18:15 ET (CME Asia reopen)
        # Source : CORE/eco_calendar.py — 1 seule verite blocked/not blocked.
        try:
            from CORE import eco_calendar
            blocked, reason, until = eco_calendar.is_blocked_combined()
            if blocked:
                # Throttle log : emit 1x par minute par symbole
                last_emit = getattr(self, "_eco_block_last_emit", {}).get(symbol, 0)
                if time.time() - last_emit > 60:
                    if not hasattr(self, "_eco_block_last_emit"):
                        self._eco_block_last_emit = {}
                    self._eco_block_last_emit[symbol] = time.time()
                    _emit("ECO_BLOCK", sym=symbol, reason=reason or "?",
                          until_utc=until.isoformat() if until else "")
                    print(f"[{symbol}] ECO BLOCK : {reason} (jusqu'a {until.strftime('%H:%M UTC') if until else '?'})")
                return  # silent skip — pas de trade pendant fenetre eco
        except Exception as _eco_err:
            # Fail-safe : si module eco_calendar plante, NE PAS bloquer
            # le bot (continuer a trader). Log warning.
            print(f"[{symbol}] eco_calendar gate fail (non-fatal): {_eco_err}")

        # Score consensus
        result = score_consensus(bar, self.cfg)
        close = float(bar.get("close", 0))
        ts_str = str(bar_ts)[:19]
        print(f"[{symbol}] {ts_str} close={close:.2f} "
              f"bull={result.bull_pts}/bear={result.bear_pts} -> {result.direction}")

        # ── ENRICH 3 — BAR_PROCESSED event (chaque bar) ───────────────
        self._bars_processed[symbol] += 1
        top_checks = result.checks[:3] if result.checks else []
        _emit("BAR_PROCESSED", sym=symbol, bar_ts=str(bar_ts)[:19],
              close=close, bull_pts=result.bull_pts, bear_pts=result.bear_pts,
              direction=result.direction, top_checks=top_checks)

        # ── ENRICH 4 — Aggregate stats par symbol (5 min window) ──────
        ag = self._aggregate_buffer[symbol]
        ag["bull_max"] = max(ag["bull_max"], result.bull_pts)
        ag["bear_max"] = max(ag["bear_max"], result.bear_pts)
        if result.direction == "HOLD":
            ag["hold"] += 1
        elif result.direction == "BUY":
            ag["buy"] += 1
        elif result.direction == "SELL":
            ag["sell"] += 1
        elif result.direction == "CONFLIT":
            ag["conflit"] += 1

        # ── ENRICH 5 — THRESHOLD_NEAR_MISS (bull=3 ou bear=3 = a 1 du seuil) ──
        if (result.bull_pts == self.cfg.min_bull_for_buy - 1
                and result.bear_pts <= self.cfg.max_bear_for_buy):
            _emit("THRESHOLD_NEAR_MISS", sym=symbol,
                  bull_pts=result.bull_pts, bear_pts=result.bear_pts,
                  missing_for_signal="bull+1 -> BUY")
        elif (result.bear_pts == self.cfg.min_bear_for_sell - 1
                and result.bull_pts <= self.cfg.max_bull_for_sell):
            _emit("THRESHOLD_NEAR_MISS", sym=symbol,
                  bull_pts=result.bull_pts, bear_pts=result.bear_pts,
                  missing_for_signal="bear+1 -> SELL")

        # ── ENRICH 6 — Market context tracking ─────────────────────────
        self._track_market_context(symbol, bar)

        # Log snapshot meme si HOLD (pour analyse posterior)
        self._log_snapshot(symbol, bar, result, traded=False)

        if result.direction == "HOLD" or result.direction == "CONFLIT":
            return

        # ── GATE A — VETO BUY si color_dn wall proche (Plan A_v2 30/04) ──────
        # Audit market-analyst : `dist_color_dn_nearest_pct ∈ (0, 0.05%]` → mur
        # color zone immediat 5 ticks au-dessus = stop hunt likely. PF 1.04 → 1.49
        # walk-forward 3/3 sur backtest 4 mois.
        # Source : feedback memoires audit + Plan agent review (paramétrable).
        if (result.direction == "BUY"
                and self.cfg.veto_buy_color_wall_pct
                and self.cfg.veto_buy_color_wall_pct > 0):
            dist_color_dn = bar.get("dist_color_dn_nearest_pct")
            if dist_color_dn is not None and isinstance(dist_color_dn, (int, float)):
                if 0 < dist_color_dn <= self.cfg.veto_buy_color_wall_pct:
                    print(f"[{symbol}] VETO BUY (Gate A) : color_dn wall a "
                          f"{dist_color_dn:.4f}% (seuil {self.cfg.veto_buy_color_wall_pct}%)")
                    _emit("VETO_BUY_COLOR_WALL", sym=symbol,
                          dist_color_dn_pct=round(dist_color_dn, 5),
                          threshold=self.cfg.veto_buy_color_wall_pct,
                          bull_pts=result.bull_pts, bear_pts=result.bear_pts)
                    self._log_snapshot(symbol, bar, result, traded=False)
                    return

        # ── RangeGate (30/04 v3 Jackson "ON A ACHETE HAUT DE RANGE") ────
        # Confluence 4 metriques (VA + IB + DAY + MQ_1D) : skip si >=2/4
        # en zone extreme. Plus cas special "BREAKOUT_VA" (range_pos extreme
        # + inside_cur_va=0). Reversibilite via cfg.range_gate_enabled.
        if getattr(self.cfg, "range_gate_enabled", True):
            try:
                from CORE.range_gate import evaluate_range_gate
            except ImportError:
                from range_gate import evaluate_range_gate
            rg_result = evaluate_range_gate(
                bar, result.direction, symbol,
                enabled=True,
                min_confluence=getattr(self.cfg, "range_gate_min_confluence", 2),
                mode=getattr(self.cfg, "range_gate_mode", "observe"),
            )
            # Log les would_skip meme en mode observe (pour bench 5j)
            if rg_result.would_skip:
                print(f"[{symbol}] RANGE GATE [{rg_result.mode}] {result.direction}: "
                      f"{rg_result.skip_reason}")
                _emit("GATE_RANGE_BLOCK", sym=symbol,
                      direction=result.direction,
                      reason=rg_result.skip_reason,
                      high_count=rg_result.high_count,
                      low_count=rg_result.low_count)
            # Skip uniquement si mode=skip (mutation effective)
            if rg_result.skip:
                self._log_snapshot(symbol, bar, result, traded=False)
                return

        # ── EntryQualityGate (LOT 2B Jackson "ON APPLIQUE") ────────────
        # Bot 2 graceful degradation : Databento V4 manque cvd_bar_delta +
        # next_wall_dist_ticks → seul momentum_5b dispo. Mode BOTH_CONTRA
        # par default = pas de skip Bot 2 (besoin de 2 conditions, ne peut
        # pas avoir 2 sans cvd). Toggle strict_mode=True pour activer
        # filtre sur momentum seul (apres enrichissement parquet V4).
        if getattr(self.cfg, "entry_quality_gate_enabled", True):
            try:
                from CORE.entry_quality_gate import evaluate_entry_quality_gate
            except ImportError:
                from entry_quality_gate import evaluate_entry_quality_gate
            eq_result = evaluate_entry_quality_gate(
                bar, result.direction,
                enabled=True,
                strict_mode=getattr(self.cfg, "entry_quality_gate_strict", False),
            )
            if eq_result.skip:
                print(f"[{symbol}] ENTRY QUALITY SKIP {result.direction}: {eq_result.skip_reason}")
                _emit("GATE_ENTRY_QUALITY_BLOCK", sym=symbol,
                      direction=result.direction,
                      reason=eq_result.skip_reason,
                      momentum_5b=eq_result.momentum_5b,
                      cvd_bar_delta=eq_result.cvd_bar_delta)
                self._log_snapshot(symbol, bar, result, traded=False)
                return

        # Risk check
        allowed, reason = self.risk.can_trade(symbol)
        if not allowed:
            print(f"[{symbol}] RISK BLOCK: {reason}")
            _emit("GATE_RISK_BLOCK", sym=symbol, reason=reason,
                  bull_pts=result.bull_pts, bear_pts=result.bear_pts,
                  direction=result.direction)
            return

        with self._pos_lock:
            if symbol in self.active_positions:
                print(f"[{symbol}] Already in position, skip")
                _emit("GATE_POSITION_BLOCK", sym=symbol, reason="ALREADY_IN_POSITION")
                return

        # ── FIX #1 (29/04) — Dedup cross-restart par (sym, bar_ts) ───
        # Sans ca, restart bot = re-trade derniere bar (bug 28/04 ES double entry).
        # FIX R4 (audit 28/04) : normalisation ISO stricte via strftime.
        # Sans ca, str(bar_ts)[:19] peut donner cles distinctes pour la meme
        # barre selon format pandas (T vs espace, microsecondes, epoch).
        # FIX backlog 29/04 : fail-loud (raise + emit + SKIP) au lieu de
        # fallback silencieux qui pourrait re-introduire le bug double-entry.
        try:
            _bar_dt_norm = pd.to_datetime(bar_ts)
            if _bar_dt_norm is None or pd.isna(_bar_dt_norm):
                raise ValueError("bar_ts is None or NaT")
            bar_key = f"{symbol}|{_bar_dt_norm.strftime('%Y-%m-%dT%H:%M:%S')}"
        except (TypeError, ValueError, AttributeError) as e:
            print(f"[{symbol}] BAR_KEY_PARSE_FAIL bar_ts={bar_ts!r} err={e} — SKIP")
            _emit("BAR_KEY_PARSE_FAIL", sym=symbol, bar_ts=str(bar_ts)[:50],
                  err=type(e).__name__)
            # Storm detection (>= 10 fails/min = pipeline casse en amont)
            now = time.time()
            self._bar_key_parse_fail_ts.append(now)
            cutoff = now - self._bar_key_parse_fail_window_sec
            self._bar_key_parse_fail_ts = [
                t for t in self._bar_key_parse_fail_ts if t >= cutoff
            ]
            if len(self._bar_key_parse_fail_ts) >= self._bar_key_parse_fail_storm_threshold:
                _emit("BAR_KEY_PARSE_FAIL_STORM",
                      n_fails=len(self._bar_key_parse_fail_ts),
                      window_sec=self._bar_key_parse_fail_window_sec)
                self._bar_key_parse_fail_ts = []  # reset anti-spam
            return
        if bar_key in self._traded_bar_keys:
            print(f"[{symbol}] BAR_ALREADY_TRADED skip {bar_key}")
            _emit("BAR_ALREADY_TRADED", sym=symbol, bar_key=bar_key)
            return

        # SL/TP via SLTPEngine — fallback adaptatif si invalid (V4 _pct ou pas de wall).
        # FIX 29/04 (Jackson MES≠MNQ) : fallback sl_ticks dynamique par symbole
        # pour respecter budget $ commun (ES 16t ≈ NQ 40t ≈ $60).
        sl_ticks_use, tp_ticks_use = fallback_sltp_ticks(symbol, self.cfg.quantity)
        sl_wall_used = f"FIXED_{sl_ticks_use}T_${FALLBACK_SL_USD:.0f}"
        tp_wall_used = f"FIXED_{tp_ticks_use}T_RR{FALLBACK_RR}"
        try:
            direction_int = 1 if result.direction == "BUY" else -1
            # FIX Tier1 #10 (29/04) : pipeline V4 fournit dist_*_pct (apres
            # add_pct_normalized_distances qui DROP les _ticks bruts).
            # SLTPEngine cherche dist_* (en ticks). Sans conversion : reject
            # systematique → fallback FIXED 30/40t = SL trop court NQ
            # (3 trades sur 4 du 28/04 = SL fallback = -277 ticks).
            # Formule inverse : ticks = pct * close / (100 * TICK_SIZE)
            bar_dict = self._inject_dist_ticks_from_pct(bar.to_dict())
            sltp = self.sltp_engines[symbol].evaluate_single(bar_dict, direction_int)
            if sltp.valid:
                sl_ticks_use = sltp.sl_ticks
                tp_ticks_use = sltp.tp1_ticks
                sl_wall_used = sltp.sl_wall
                tp_wall_used = sltp.tp1_wall
                print(f"[{symbol}] SLTP walls: sl={sl_ticks_use}t ({sl_wall_used}) tp={tp_ticks_use}t ({tp_wall_used})")

                # 30/04 : tracking observability MQ walls + CAS 4
                # - SLTP_MQ_WALL_USED : MQ level utilise comme TP/SL → freq deploy MQ tiers
                # - SLTP_CAS4_TRIGGERED : capot anti-TP-derriere-mur active → freq bug pre-fix
                if "MQ_" in sl_wall_used or "MQ_" in tp_wall_used:
                    _emit("SLTP_MQ_WALL_USED", sym=symbol,
                          direction=result.direction,
                          role="SL" if "MQ_" in sl_wall_used else "TP",
                          wall_name=sl_wall_used if "MQ_" in sl_wall_used else tp_wall_used,
                          dist_ticks=sl_ticks_use if "MQ_" in sl_wall_used else tp_ticks_use,
                          tier=sltp.sl_wall_tier if "MQ_" in sl_wall_used else 0)
                if getattr(sltp, "cas4_triggered", False):
                    # 🆕 v6 30/04 : enrichi avec subtier (T1 / T2_STRUCTUREL) + col + rr_pre/post
                    _emit("SLTP_CAS4_TRIGGERED", sym=symbol,
                          direction=result.direction,
                          wall_name=sltp.cas4_blocked_wall,
                          wall_col=getattr(sltp, "cas4_blocked_wall_col", ""),
                          subtier=getattr(sltp, "cas4_subtier", ""),
                          tp_ticks=tp_ticks_use,
                          tp_standard=sltp.cas4_tp_standard_pre,
                          wall_dist=sltp.cas4_blocked_wall_dist,
                          rr_pre=getattr(sltp, "cas4_rr_pre", 0.0),
                          rr_post=getattr(sltp, "cas4_rr_post", 0.0),
                          rr=tp_ticks_use / sl_ticks_use if sl_ticks_use > 0 else 0)
                # 🆕 v6 30/04 : T2 observability (mur T2 hors structurel qui aurait capote)
                if getattr(sltp, "cas4_observed_tier2", False):
                    _emit("SLTP_CAS4_T2_OBSERVED", sym=symbol,
                          direction=result.direction,
                          wall_name=sltp.cas4_observed_wall_t2,
                          wall_dist=sltp.cas4_observed_wall_t2_dist,
                          tp_devant=sltp.cas4_observed_tp_devant,
                          tp_actual=tp_ticks_use)
            else:
                print(f"[{symbol}] SLTP invalid ({sltp.reject_reason or 'no walls found'}), "
                      f"fallback adaptatif SL={sl_ticks_use}t TP={tp_ticks_use}t "
                      f"(budget ${FALLBACK_SL_USD}, RR {FALLBACK_RR})")
                # Fallback FIXED applique cote databento_paper (hors mia_sltp). Track freq.
                # 01/05 Jackson "TRACK TOUT" : ajout reject_reason pour debug SLTPEngine
                _emit("SLTP_NO_VALID_WALL", sym=symbol,
                      direction=result.direction,
                      sl_fixed=sl_ticks_use,
                      tp_fixed=tp_ticks_use,
                      reject_reason=str(sltp.reject_reason or "no_walls_found"))
                # 🆕 v6 30/04 : flag dedie quand le rejet est cause par capot CAS 4
                # (mur T1 ou T2_STRUCTUREL qui a fait chuter R:R sous MIN_RR_RATIO).
                # Permet grep ex-post pour calibrer fire rate du fix v6.
                if getattr(sltp, "cas4_caused_reject", False):
                    _emit("SLTP_CAS4_CAUSED_REJECT", sym=symbol,
                          direction=result.direction,
                          wall_name=sltp.cas4_blocked_wall,
                          wall_col=getattr(sltp, "cas4_blocked_wall_col", ""),
                          subtier=getattr(sltp, "cas4_subtier", ""),
                          wall_dist=sltp.cas4_blocked_wall_dist,
                          rr_pre=getattr(sltp, "cas4_rr_pre", 0.0),
                          rr_post=getattr(sltp, "cas4_rr_post", 0.0),
                          reject_reason=sltp.reject_reason)
        except (AttributeError, KeyError) as e:
            print(f"[{symbol}] SLTP exception {e}, fallback fixes")
            _emit("PY_EXCEPTION_HOT_PATH", sym=symbol,
                  fn_name="SLTPEngine.evaluate_single",
                  exc_type=type(e).__name__, exc_msg=str(e))
        except Exception as e:  # noqa: BLE001
            print(f"[{symbol}] SLTP unexpected exception {type(e).__name__}: {e}, fallback fixes")
            _emit("PY_EXCEPTION_HOT_PATH", sym=symbol,
                  fn_name="SLTPEngine.evaluate_single",
                  exc_type=type(e).__name__, exc_msg=str(e))

        # ── GATE B — VETO SHORT si TP no-wall ou room insuffisant (Plan A_v2 30/04) ──
        # Audit Phase 0 SHORTs Bot 2 (n=8) : 3/8 SHORTs avec TP_STANDARD_NO_WALL ou
        # tp_wall == FIXED. Vs LONGs 2/18 (11%). Pattern : SHORT sans mur = TP improbable.
        # Reco market-analyst : skip SHORT si TP fixe OR room_ratio < 1.5x SL.
        # Note : H1 (signal cassé) REFUTÉ + H4 (anecdote n=8) CONFIRMÉ → veto cible
        # l'execution (no wall) pas le signal → reversible et chirurgical.
        if (result.direction == "SELL" and self.cfg.veto_short_no_wall):
            tp_wall_str = str(tp_wall_used or "")
            is_no_wall_tp = is_synthetic_tp_wall(tp_wall_str)
            room_ratio = (tp_ticks_use / sl_ticks_use) if sl_ticks_use and sl_ticks_use > 0 else 0
            insufficient_room = room_ratio < self.cfg.veto_short_room_min_ratio
            if is_no_wall_tp or insufficient_room:
                reason_parts = []
                if is_no_wall_tp:
                    reason_parts.append(f"tp_wall={tp_wall_str}")
                if insufficient_room:
                    reason_parts.append(f"room={room_ratio:.2f}<{self.cfg.veto_short_room_min_ratio}")
                reason_str = "+".join(reason_parts)
                print(f"[{symbol}] VETO SHORT (Gate B) : {reason_str} "
                      f"(sl={sl_ticks_use}t tp={tp_ticks_use}t)")
                _emit("VETO_SHORT_NO_WALL", sym=symbol,
                      tp_wall=tp_wall_str, sl_wall=str(sl_wall_used or ""),
                      sl_ticks=sl_ticks_use, tp_ticks=tp_ticks_use,
                      room_ratio=round(room_ratio, 2),
                      reason=reason_str)
                self._log_snapshot(symbol, bar, result, traded=False)
                return

        # ── FIX 29/04 soir (5e voie Plan agent) — entry price LIVE ──
        # Le parquet enrichi a ~30 min de retard (Databento Historical tier).
        # Bot 2 calcule SL/TP sur `close` de bar vieille → fill marche bouge
        # entre signal et send → slippage 23t systematique.
        # Solution : lire DATA/LIVE_CACHE/{sym}_last.json (alimente par
        # service MIA-Live-OHLCV streaming Databento Live ohlcv-1m, latence ~1min)
        # et utiliser ce close pour calculer SL/TP. Si cache absent ou stale
        # (>5 min) → fallback sur close de bar (comportement actuel preserve).
        # Toutes les calculs en aval continuent avec `close` original (features,
        # logs, position) ; seuls SL/TP/entry_send utilisent `close_for_order`.
        close_for_order = self._read_live_cache_close(symbol, fallback=close)
        slip_signal_to_live = (close_for_order - close) / TICK_SIZE if close_for_order != close else 0
        if slip_signal_to_live != 0:
            print(f"[{symbol}] LIVE close={close_for_order:.2f} (vs bar close {close:.2f} = {slip_signal_to_live:+.1f}t)")
        # Use live close for all subsequent calcs
        close = close_for_order

        # Order
        if self.cfg.dry_run:
            print(f"[{symbol}] DRY {result.direction} @ {close:.2f} "
                  f"sl_t={sltp.sl_ticks} tp_t={sltp.tp1_ticks} | checks: {' | '.join(result.checks[:5])}")
            return

        side_dtc = DTC_BUY if result.direction == "BUY" else DTC_SELL
        # FIX 29/04 (Jackson) : SL ancre au LOW (BUY) / HIGH (SELL) de la bar.
        # Avant : SL relatif au close = stoppe sur n'importe quel wick adverse
        # (cf trade #3 Bot 2 28/04 : LONG @27190 SL @27152 hit en wick puis
        # rebond +96t pris par Bot 1).
        # Apres : SL sous le LOW (BUY) = sous le mouvement adverse deja vu
        # dans la bar = protection structurelle vraie (idee Jackson V1).
        # TP reste relatif au close (objectif standard depuis l'entry).
        # Le SL effectif augmente de (close - bar_low) = plus de room.
        bar_low = bar.get("low")
        bar_high = bar.get("high")
        try:
            bar_low = float(bar_low) if bar_low is not None and not pd.isna(bar_low) else close
            bar_high = float(bar_high) if bar_high is not None and not pd.isna(bar_high) else close
        except (TypeError, ValueError):
            bar_low, bar_high = close, close

        if result.direction == "BUY":
            sl_anchor = min(bar_low, close)  # ancre au plus bas (low ou close si bar marubozu up)
            sl_price = sl_anchor - sl_ticks_use * TICK_SIZE
            tp_price = close + tp_ticks_use * TICK_SIZE
        else:
            sl_anchor = max(bar_high, close)  # ancre au plus haut
            sl_price = sl_anchor + sl_ticks_use * TICK_SIZE
            tp_price = close - tp_ticks_use * TICK_SIZE
        sl_extra_ticks = abs(sl_anchor - close) / TICK_SIZE

        # FIX audit R1 (29/04) : re-cap budget apres ancrage. Si SL ancre fait
        # depasser max_sl_usd ($75), fallback ancre au close + log warn.
        # Sans ca : ancrage silencieux peut violer le budget config (ATR eleve).
        max_sl_usd = self.sltp_engines[symbol].max_sl_usd
        tick_value = TICK_VALUE.get(symbol, 1.0)
        risk_usd = abs(close - sl_price) * tick_value * self.cfg.quantity
        if risk_usd > max_sl_usd:
            print(f"[{symbol}] SL anchored exceeds budget (${risk_usd:.0f} > ${max_sl_usd:.0f}), "
                  f"fallback ancre close")
            _emit("SL_ANCHOR_BUDGET_OVERFLOW", sym=symbol, risk_usd=round(risk_usd, 2),
                  budget=max_sl_usd, sl_extra_ticks=int(sl_extra_ticks))
            if result.direction == "BUY":
                sl_price = close - sl_ticks_use * TICK_SIZE
            else:
                sl_price = close + sl_ticks_use * TICK_SIZE
            sl_extra_ticks = 0  # reset car ancrage abandonné

        # FIX audit R2 (29/04) : etirer TP de meme sl_extra_ticks pour
        # preserver R/R initial (sinon R/R 1.33 → 0.62 sur trade #3).
        # Cohérent avec demande Jackson : protection plus forte avec gain compensé.
        if sl_extra_ticks > 0:
            if result.direction == "BUY":
                tp_price = tp_price + sl_extra_ticks * TICK_SIZE
            else:
                tp_price = tp_price - sl_extra_ticks * TICK_SIZE
            print(f"[{symbol}] SL anchored to bar_{'low' if result.direction == 'BUY' else 'high'} "
                  f"({sl_anchor:.2f} vs close {close:.2f}, +{sl_extra_ticks:.0f}t protection, "
                  f"TP stretched +{sl_extra_ticks:.0f}t pour preserver R/R)")
            # FIX audit R1-bis (29/04) : emit V2 pour audit observabilite
            _emit("SL_ANCHOR_APPLIED", sym=symbol, direction=result.direction,
                  sl_anchor=round(sl_anchor, 2), close=round(close, 2),
                  extra_ticks=int(sl_extra_ticks),
                  is_fallback=("FIXED" in sl_wall_used))

        if not _DTC_OK or symbol not in BOT_INSTRUMENTS:
            print(f"[{symbol}] DTC unavailable")
            # 01/05 Jackson "TRACK TOUT" : trace si DTC indisponible (broker connection KO)
            _emit("GATE_DTC_UNAVAILABLE", sym=symbol,
                  dtc_ok=_DTC_OK, in_instruments=(symbol in BOT_INSTRUMENTS),
                  reason="DTC connector unavailable or symbol not configured")
            return
        contract = BOT_INSTRUMENTS[symbol].contract

        # ════════════════════════════════════════════════════════════
        # 🆕 STEP 6.5 v3 — QualityGate v3 data-driven (01/05/2026)
        # ════════════════════════════════════════════════════════════
        # Calcule features + signatures AVANT envoi ordre, applique QualityGate v3.
        # Si NO_TRADE → bloque envoi + log JSONL. Si STRONG → continue flow normal.
        # Validation : 42 trades 28-30/04+01/05, WR 23.8% → 42.9% (+$1,945 evite paper).
        # Reviews : code-reviewer GO-AVEC-RESERVES, market-analyst GO-AVEC-MONITORING.
        # ════════════════════════════════════════════════════════════
        features_at_entry = self._extract_features_dict(bar)
        bar_ts_entry = str(bar.get("ts_event"))[:19]

        # SIGNATURES (deplacees avant envoi ordre pour QualityGate v3)
        signatures_at_entry = {}
        sig_score_at_entry = {}
        try:
            from CORE import signatures as _sigs_mod
            sig_dir = "LONG" if result.direction == "BUY" else "SHORT"
            signatures_at_entry = _sigs_mod.compute_all(features_at_entry, direction=sig_dir)
            sig_score_at_entry = _sigs_mod.overall_score(signatures_at_entry)
            for sig_name, sig_val in signatures_at_entry.items():
                features_at_entry[f"sig_{sig_name}"] = int(bool(sig_val))
            features_at_entry["sig_score_tier1"] = sig_score_at_entry.get("tier1", 0)
            features_at_entry["sig_score_tier2"] = sig_score_at_entry.get("tier2", 0)
            features_at_entry["sig_score_tier3"] = sig_score_at_entry.get("tier3", 0)
            features_at_entry["sig_score_total"] = sig_score_at_entry.get("total", 0)
            signals_on = [k for k, v in signatures_at_entry.items() if v]
            _emit("SIGNATURES_COMPUTED", sym=symbol, direction=sig_dir,
                  tier1=sig_score_at_entry.get("tier1", 0),
                  tier1_max=sig_score_at_entry.get("tier1_max", 0),
                  tier2=sig_score_at_entry.get("tier2", 0),
                  tier2_max=sig_score_at_entry.get("tier2_max", 0),
                  tier3=sig_score_at_entry.get("tier3", 0),
                  tier3_max=sig_score_at_entry.get("tier3_max", 0),
                  total=sig_score_at_entry.get("total", 0))
            print(f"[{symbol}] SIGNATURES : T1={sig_score_at_entry.get('tier1',0)}/4 "
                  f"T2={sig_score_at_entry.get('tier2',0)}/4 T3={sig_score_at_entry.get('tier3',0)}/4 "
                  f"= {sig_score_at_entry.get('total',0)}/12 | ON: {','.join(signals_on)}")
        except Exception as _sig_err:
            print(f"[{symbol}] signatures fail (non-fatal): {_sig_err}")

        # QualityGate v3 — veto data-driven + scoring composite + hierarchie sizing
        qg_result = None
        try:
            from CORE.quality_gate_v3 import quality_gate, log_decision
            sig_dir = "LONG" if result.direction == "BUY" else "SHORT"
            ma_trend = features_at_entry.get("ma_trend", "FLAT")
            regime = "TREND_UP" if ma_trend == "UP" else (
                "TREND_DOWN" if ma_trend == "DOWN" else "RANGE")
            qg_result = quality_gate(features_at_entry, sig_dir, regime=regime)

            signal_id_qg = f"{symbol}_{bar_ts_entry}"

            if not qg_result.allow:
                # NO_TRADE / VETO — bloquer envoi ordre
                print(f"[{symbol}] QUALITY_GATE v3 BLOCK : {qg_result.reason}")
                _emit("QUALITY_GATE_BLOCK", sym=symbol, direction=sig_dir,
                      tier=qg_result.tier, score=qg_result.score,
                      veto=qg_result.veto_triggered or "",
                      reason=qg_result.reason)
                # Log decision JSONL (executed=False)
                log_decision(qg_result, signal_id=signal_id_qg, symbol=symbol,
                             direction=sig_dir, regime=regime, bar_ts=bar_ts_entry,
                             executed=False)
                return  # ← BLOQUE envoi ordre

            # PASS — log + continuer flow normal
            print(f"[{symbol}] QUALITY_GATE v3 PASS : {qg_result.reason} "
                  f"(breakdown: {qg_result.score_breakdown})")
            _emit("QUALITY_GATE_PASS", sym=symbol, direction=sig_dir,
                  tier=qg_result.tier, score=qg_result.score,
                  sizing=qg_result.sizing)
            log_decision(qg_result, signal_id=signal_id_qg, symbol=symbol,
                         direction=sig_dir, regime=regime, bar_ts=bar_ts_entry,
                         executed=True)
        except Exception as _qg_err:
            # Fail-safe : si QualityGate crash, NE PAS bloquer (mode dégradé temporaire)
            # mais émettre une alerte pour investigation.
            print(f"[{symbol}] quality_gate v3 fail (non-fatal, degraded mode): {_qg_err}")
            _emit("QUALITY_GATE_ERROR", sym=symbol, error=str(_qg_err))

        # ════════════════════════════════════════════════════════════
        # Envoi ordre broker (apres QualityGate v3 PASS)
        # ════════════════════════════════════════════════════════════
        # Observability veto retire (Jackson 01/05) : log SHORT avec delta_div_buy>0
        # juste AVANT envoi ordre (apres tous les gates), pour audit WR pur
        # (= seulement trades reellement executes, pas SHORTs bloques par anti_fomo etc)
        if result.direction == "SELL":
            ddb = features_at_entry.get("delta_div_buy", 0)
            if ddb and ddb > 0:
                _emit("VETO_DELTA_DIV_OBSERVED", sym=symbol,
                      direction="SHORT", delta_div_buy=int(ddb),
                      note="veto_retire_01_05_audit_WR_avant_send_order")
        print(f"[{symbol}] SEND {result.direction} {self.cfg.quantity}x {contract} "
              f"entry~{close:.2f} sl={sl_price:.2f} tp={tp_price:.2f}")
        try:
            parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
                symbol=contract, side=side_dtc, quantity=self.cfg.quantity,
                sl_price=sl_price, tp_price=tp_price, trade_account=self.cfg.trade_account,
            )
        except Exception as e:
            print(f"[{symbol}] DTC error: {e}")
            _emit("ORDER_DTC_ERROR", sym=symbol, error=str(e))
            return
        if not parent_id:
            print(f"[{symbol}] order rejected")
            _emit("ORDER_REJECT_BOT2", sym=symbol, direction=result.direction,
                  entry=close, sl_price=sl_price, tp_price=tp_price)
            return

        with self._pos_lock:
            self.active_positions[symbol] = {
                "parent_id": parent_id, "tp_cid": tp_cid, "sl_cid": sl_cid,
                "side": result.direction, "entry": close,
                "sl_price": sl_price, "tp_price": tp_price,
                "sl_ticks": sl_ticks_use, "tp_ticks": tp_ticks_use,
                "sl_wall": sl_wall_used, "tp_wall": tp_wall_used,
                "bull_pts": result.bull_pts, "bear_pts": result.bear_pts,
                "checks": result.checks,
                "ts_open": datetime.now(timezone.utc),
                "bar_ts_entry": bar_ts_entry,        # FIX Tier1 #3
                "features_at_entry": features_at_entry,  # FIX Tier1 #3
                "signatures_at_entry": signatures_at_entry,    # FIX 30/04 nuit
                "sig_score_at_entry": sig_score_at_entry,      # FIX 30/04 nuit
            }
            self._order_to_symbol[parent_id] = symbol
            self._order_to_symbol[tp_cid] = symbol
            self._order_to_symbol[sl_cid] = symbol
        self.risk.on_trade_open(symbol)

        # FIX #1 — append cle (sym, bar_ts) au fichier dedup (cross-restart safe)
        self._traded_bar_keys.add(bar_key)
        try:
            with open(self._traded_bars_file, "a", encoding="utf-8") as f:
                f.write(f"{bar_key}\n")
        except OSError as e:
            print(f"[BOT] traded_bars persist failed: {e}")

        # FIX #3 — persist active_positions sur disque (recovery au boot)
        self._persist_active_positions()

        self._write_state()
        print(f"[{symbol}] OPEN parent={parent_id[:12]}")
        # TRADE_OPEN template attend : sym, direction, size, price (cf log_catalog.py:96)
        _emit("TRADE_OPEN", sym=symbol, direction=result.direction,
              size=self.cfg.quantity, price=close,
              sl_price=sl_price, tp_price=tp_price,
              sl_ticks=sl_ticks_use, tp_ticks=tp_ticks_use,
              sl_wall=sl_wall_used, tp_wall=tp_wall_used,
              bull_pts=result.bull_pts, bear_pts=result.bear_pts,
              parent_id=parent_id, tp_cid=tp_cid, sl_cid=sl_cid,
              account=self.cfg.trade_account, signal_id=parent_id[-8:])

    def run(self):
        self._setup_signals()
        print("=" * 70)
        print(f" DATABENTO PAPER TRADER (rules) — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
        print(f" Verdict: BUY bull>={self.cfg.min_bull_for_buy} bear<={self.cfg.max_bear_for_buy}")
        print(f"          SELL bear>={self.cfg.min_bear_for_sell} bull<={self.cfg.max_bull_for_sell}")
        print(f" Quantity: {self.cfg.quantity} micros, RTH only: {self.cfg.rth_only}")
        print(f" Mode: {'DRY' if self.cfg.dry_run else f'PAPER ({self.cfg.trade_account})' if self.cfg.paper_mode else f'LIVE ({self.cfg.trade_account})'}")
        print("=" * 70)
        _emit("BOT_START", account=self.cfg.trade_account,
              quantity=self.cfg.quantity, rth_only=self.cfg.rth_only,
              dry_run=self.cfg.dry_run,
              min_bull=self.cfg.min_bull_for_buy, min_bear=self.cfg.min_bear_for_sell)

        while not self.stop_event.is_set():
            # FIX R2 (29/04 backlog) : rollover UTC date pour bot 24/7
            self._rotate_day_if_needed()

            # FIX 30/04 nuit (port pattern Bot 1 check_exit) : check proactif
            # SL/TP via live trade price AVANT _process_symbol. Si hit detecte,
            # cancel les 2 brackets pour eviter "2 fills simultanés" (test
            # round-trip 29/04 nuit a reproduit ce bug).
            for sym in SYMBOLS:
                try:
                    self._check_exit_dtc(sym)
                except Exception as e:
                    print(f"[{sym}] check_exit_dtc fail (non-fatal): {e}")

            for sym in SYMBOLS:
                try:
                    self._process_symbol(sym)
                except Exception as e:
                    print(f"[{sym}] EXCEPTION: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
            # Periodic enrichments (heartbeat + aggregate)
            self._emit_periodic_logs()

            # FIX 30/04 nuit : poll adaptatif. Si position(s) ouverte(s),
            # raccourcir le poll_interval a 2s pour check_exit_dtc reactif
            # (latence trades ~100ms inutile si check toutes les 30s).
            with self._pos_lock:
                has_active_pos = bool(self.active_positions)
            effective_poll = 2 if has_active_pos else self.cfg.poll_interval
            for _ in range(effective_poll):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        if self.dtc:
            with self._pos_lock:
                n_open = len(self.active_positions)
            if n_open == 0:
                self.dtc.disconnect()
                print("[BOT] DTC disconnected.")
            else:
                print(f"[BOT] {n_open} positions open — DTC stays for OCO management")
        print("[BOT] Stopped.")
        _emit("BOT_STOP", account=self.cfg.trade_account,
              positions_open_at_stop=n_open if self.dtc else 0)


def main():
    ap = argparse.ArgumentParser(description="Databento Paper Trader (rules-based)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rth-only", action="store_true")
    ap.add_argument("--live", action="store_true", help="LIVE AMP (DANGER)")
    ap.add_argument("--quantity", type=int, default=3)
    ap.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SEC)
    ap.add_argument("--trade-account", default="Sim2",
                    help="Sim2 (default, A/B vs paper actuel Sim3) | Sim3 | AMP123 (live)")
    args = ap.parse_args()

    cfg = BotConfig(
        poll_interval=args.poll_interval,
        paper_mode=not args.live,
        dry_run=args.dry_run,
        rth_only=args.rth_only,
        quantity=args.quantity,
        trade_account=args.trade_account,
    )
    bot = DatabentoPaperTrader(cfg)
    bot.run()


if __name__ == "__main__":
    main()
