"""setup_engine.py — Engine PAPER_TRADE actif Bot 2 Sim2 (V4 Databento).

Created : 2026-05-02 dimanche soir.
Mode : PAPER_TRADE actif des lundi 13:30 UTC (ouverture RTH).

ARCHITECTURE :
  SetupEngine (eval triggers + resolve confluence)
  RiskManager (isole par symbole : NQ et ES independants)
  PositionTracker (1 position max par symbole, MFE/MAE en live)
  TradeLogger (JSONL append-only avec features_at_entry + outcome)

GARDE-FOUS PAR SYMBOLE :
  - max_losses_per_day = 3 (NQ et ES separes)
  - kill_switch_daily_pnl = -$900 (NQ et ES separes)
  - position_size = 3 micros (NQ MNQ / ES MES)
  - max_open_positions_per_symbol = 1
  - RTH_ONLY = True (is_in_us_cash == 1)

ANTI DOUBLE-TRIGGER (CRITIQUE) :
  Le poll loop tourne toutes les 30s mais le pipeline V4 batch toutes les 5min.
  Sans dedup, le SetupEngine triggere 10x sur la meme bar -> 10 trades sur 1 signal.
  Solution : last_bar_ts[symbol] garde l'ts de la derniere bar evaluee, et on
  ne re-evalue PAS si bar_ts <= last_bar_ts[symbol].

LOGS V2 :
  - LOGS/setups_observed/YYYYMMDD_setups_trades.jsonl (1 entry par trade)
  - LOGS/decisions/decisions_YYYYMMDD_paper.jsonl (codes V2 catalog)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SETUPS_LOG_DIR = ROOT / "LOGS" / "setups_observed"

try:
    from CORE.constants import get_cme_trading_day
except ImportError:
    from constants import get_cme_trading_day

try:
    from CORE.setup_definitions import evaluate_all_setups, SETUP_REGISTRY
except ImportError:
    from setup_definitions import evaluate_all_setups, SETUP_REGISTRY

# Logging V2 (optionnel : si module absent, no-op)
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("setup_engine", process="paper")
except Exception:
    _v2log = None


def _emit(code: str, **ctx):
    """Emit log V2 avec fail-loud stderr si erreur."""
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception as e:
            import sys
            print(f"[EMIT_FAIL] code={code} err={type(e).__name__}: {e} ctx={ctx}",
                  file=sys.stderr, flush=True)


# ═══════════════════════════════════════════════════════════════════
# CONFIG — RISK / GUARD_RAILS
# ═══════════════════════════════════════════════════════════════════

# ─── PHASE 1 FREE-RUN MODE (Jackson 02/05 soir) ────────────────────
# Configuration PAPER FREE pour collecte data maximale Phase 1 :
#   - max_losses_per_day DESACTIVE (None) → trade libre
#   - kill_switch_daily_pnl DESACTIVE (None) → trade libre
#   - GLOBAL_KILL_SWITCH DESACTIVE (None)
#   Surveillance manuelle Jackson + STOP.flag dernier recours.
#   En LIVE capital reel : reactiver les 3 garde-fous.
#
# CONSERVES ACTIFS :
#   - Veto ATR extreme (anti flash crash structurel)
#   - Veto news eco (within_news_*_5m)
#   - Trading window 02h-21h UTC (= 4h-23h FR ete)
#   - 1 position max par symbole
#   - Anti double-trigger
PHASE_1_FREE_RUN = True   # False = reactive max_losses + kill switch

RISK_PER_SYMBOL = {
    "NQ": {
        "max_losses_per_day": None if PHASE_1_FREE_RUN else 3,
        "kill_switch_daily_pnl": None if PHASE_1_FREE_RUN else -900.0,
    },
    "ES": {
        "max_losses_per_day": None if PHASE_1_FREE_RUN else 3,
        "kill_switch_daily_pnl": None if PHASE_1_FREE_RUN else -900.0,
    },
}

# Kill switch GLOBAL cross-symbole — DESACTIVE Phase 1 free-run.
GLOBAL_KILL_SWITCH_DAILY_PNL = None if PHASE_1_FREE_RUN else -1800.0

# Veto volatilite extreme (anti flash crash) — TOUJOURS ACTIF (structurel).
# 04/05 SOIR FIX (audit code-reviewer + verification empirique Jackson) :
# Bug calibration : 0.005 = 0.5% atr_14m_pct vetait 99.8% ES / 100% NQ des bars.
# Empirique mai 2026 : ES p50=1.4% p99=6.1% max=6.5%, NQ p50=2.1% p99=9.7% max=10.3%.
# Cause Bot 2 = 0 trade aujourd'hui (112 BOT2_REGIME_OBSERVE / 0 SETUP_DETECTED).
# Nouveau seuil 0.10 (10%) = vraie volatilite extreme (flash crash) :
#   ES : 0% vetoes, NQ : 0.18% vetoes (top 1% legitimes).
# A backtester pour confirmer Fix 2 (ratio bar_range/ATR) si edge anti-spike valide.
VETO_ATR_14M_PCT_MAX = 0.10

# ─── TRADING WINDOW (Jackson 02/05 soir) ───────────────────────────
# Trade entre 4h FR (02h UTC ete DST) et 23h FR (21h UTC ete DST).
# = pause sommeil 23h-4h FR pendant laquelle on ne trade pas.
# Couvre : Asia tail (02-07 UTC) + London (07-13:30) + RTH US (13:30-20) + early AH (20-21)
# Note : en hiver (UTC+1 Paris), shifter de 1h → ajuster manuellement si besoin.
TRADING_WINDOW_START_UTC = 2   # 4h Paris ete = 02h UTC
TRADING_WINDOW_END_UTC = 21    # 23h Paris ete = 21h UTC

# ─── VETO NEWS ECO (Jackson 02/05 + FIX B-3 review market-analyst) ──
# Skip trade si dans la fenetre 15min avant/apres une news eco majeure.
# FIX B-3 (02/05 soir) : 5min trop court pour news tier-1.
#   FOMC : volatilite jusqu'a 30min apres
#   NFP/CPI : volatilite primaire 15-30min
#   → 15min minimum pour anti-noise news.
# Features V4 : within_news_*_5m garde (true positive garanti)
#  + extension via mins_to/since_news < 15
NEWS_BUFFER_MINUTES = 15

def is_in_news_buffer(bar) -> bool:
    """Retourne True si on est dans la fenetre +/-15min d'une news eco."""
    # 1. Check les flags within_news_*_5m
    news_flags = ["within_news_715_5m", "within_news_730_5m",
                  "within_news_830_5m", "within_news_845_5m",
                  "within_news_900_5m", "within_news_930_5m"]
    for flag in news_flags:
        v = bar.get(flag) if hasattr(bar, "get") else None
        try:
            if int(v) == 1:
                return True
        except (ValueError, TypeError):
            pass
    # 2. Fallback mins_to/since_news (-1 = no upcoming news today)
    try:
        mins_to = bar.get("mins_to_next_news")
        if mins_to is not None and 0 <= float(mins_to) < NEWS_BUFFER_MINUTES:
            return True
    except (ValueError, TypeError):
        pass
    try:
        mins_since = bar.get("mins_since_news")
        if mins_since is not None and 0 <= float(mins_since) < NEWS_BUFFER_MINUTES:
            return True
    except (ValueError, TypeError):
        pass
    return False


def compute_session_label(bar_ts_str: str) -> str:
    """Categorise la session selon l'heure UTC du bar (futures CME).

    Conventions :
      - Asia      : 23:00-07:00 UTC (open dimanche 23:00 → fin lundi 07:00)
      - London    : 07:00-13:30 UTC
      - RTH US    : 13:30-20:00 UTC
      - After Hrs : 20:00-23:00 UTC
    """
    try:
        if isinstance(bar_ts_str, str):
            dt = datetime.fromisoformat(bar_ts_str.replace("Z", "+00:00"))
        else:
            dt = bar_ts_str
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        h = dt.hour
        m = dt.minute
        # RTH : 13:30 - 20:00
        if (h == 13 and m >= 30) or (14 <= h < 20):
            return "RTH_US"
        # London : 07:00 - 13:30
        if 7 <= h < 13 or (h == 13 and m < 30):
            return "LONDON"
        # After hours : 20:00 - 23:00
        if 20 <= h < 23:
            return "AFTER_HOURS_US"
        # Asia : 23:00-07:00 (et 00:00-07:00 inclus)
        return "ASIA"
    except Exception:
        return "UNKNOWN"

# FIX market-analyst : regime_label tracker pour audit Phase 1 cross-regime.
# Permet de mesurer PF par regime VIX et ajuster setups (notamment SHORT) si bull.
def compute_regime_label(vix_level: Optional[float]) -> str:
    """Categorise le regime via VIX. Pour log Phase 1."""
    if vix_level is None:
        return "UNKNOWN"
    try:
        v = float(vix_level)
        if v != v:  # NaN
            return "UNKNOWN"
        if v < 14:
            return "BULL_STRONG"
        if v < 18:
            return "BULL_MILD"
        if v < 22:
            return "NEUTRAL"
        if v < 28:
            return "BEAR_MILD"
        return "BEAR_STRONG"
    except (ValueError, TypeError):
        return "UNKNOWN"

# ─── TRAILING STOP (Option B Jackson, validee 2026-05-02) ──────────
# Pourquoi pas TP fixe (Option A) :
#   Le PF backtest 2.27 SELL_TOP_RANGE NQ vient de fwd_15m_ticks (close-to-close)
#   pas TP touch. Avec TP fixe 300t, les setups petits move (+50/+100t avg) ne
#   touchent JAMAIS le TP -> sortie timeout = profit faible. Avec trailing 80/60,
#   on laisse passer les petits (timeout 30min) et on verrouille les gros moves.
#
# Calibration NQ : SELL_TOP_RANGE avg=+53t, best=+913t -> activation 80t cap les
#   small moves (timeout), trail 60t verrouille les big moves a -60t depuis MFE.
#
# DTC implementation :
#   - Bracket initial : parent MARKET + SL STOP + TP LIMIT au tp_cap (securite)
#   - Bot tracke trailing en local a chaque poll cycle (update via update_mfe_mae)
#   - Si trailing trigger -> bot envoie cancel SL+TP + close MARKET via DTC
# DEPRECATED 02/06/2026 — Bot 2 V2 historique gated par MIA_BOT2_V2_PAPER_ENABLED
# (default "0" = OFF depuis 05/05/2026, remplacé par BN V4 sur Sim2).
# Valeurs ci-dessous obsolètes (MICRO MNQ/MES) post-rollback "TOUT EN MINI" 02/06.
# Si Jackson réactive un jour Bot 2 V2 : MIGRER vers MINI standard d'abord
# (n_contracts=1, tick_value_dollars=1.25 NQ / 12.50 ES, contract NQM26/ESM26).
# Dette R2 — cf IDEAS_BACKLOG.md + INCIDENT_LOG entry 02/06.
TRAILING_CONFIG = {
    "NQ": {
        "n_contracts": 3,
        "sl_ticks": 200,                 # SL fixe depuis l'entree
        "trailing_activation_ticks": 80, # trailing s'active apres +80t profit (MFE)
        "trailing_distance_ticks": 60,   # trailing suit a 60t derriere le MFE
        "timeout_minutes": 40,           # Phase 1, large pour collecter MFE/MAE
        "tp_cap_ticks": 500,             # cap absolu (rarement touche)
        "tick_value_dollars": 0.50,      # MNQ — OBSOLETE migrer 1.25 MINI si reactivation
    },
    "ES": {
        "n_contracts": 3,
        "sl_ticks": 80,
        "trailing_activation_ticks": 32, # ~8 points ES
        "trailing_distance_ticks": 24,   # ~6 points ES
        "timeout_minutes": 40,           # Phase 1, large pour collecter MFE/MAE
        "tp_cap_ticks": 200,
        "tick_value_dollars": 1.25,      # MES — OBSOLETE migrer 12.50 MINI si reactivation
    },
}
# AJUSTEMENT POST-PHASE 1 (apres 100 trades) :
#   - si >50% exit par timeout -> reduire timeout_minutes a 30
#   - si <10% exit par timeout -> garder 40min ou augmenter
#   - re-calibrer trailing_activation/distance par setup selon MFE/MAE empiriques

# ─── POSITIONS SIMULTANEES (Jackson 2026-05-02) ──────────────────
# Paper mode : 1 position max PAR INSTRUMENT.
# NQ et ES sont independants (risk separe, setups separes, budget separe).
# Donc max 2 trades ouverts simultanes : 1 NQ + 1 ES.
# Bloquer l'un a cause de l'autre = perte de data inutile en paper.
# En live, passer MAX_POSITIONS_PER_SYMBOL a 1 global = changement 1 ligne.
MAX_POSITIONS_PER_SYMBOL = 1

TICK_SIZE = 0.25  # ES + NQ


# ═══════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """Signal exécutable produit par SetupEngine.evaluate()."""
    symbol: str
    side: str  # "LONG" ou "SHORT"
    setups: list[str]  # noms des setups qui ont triggered (>=1)
    confluence: bool   # True si >=2 setups same direction
    bar_ts: str        # timestamp barre source
    price: float       # prix close de la barre source
    features_at_trigger: dict  # snapshot features clés


@dataclass
class Position:
    """Position ouverte. 1 max par symbole, NQ et ES independants."""
    symbol: str
    side: str
    setups: list[str]
    confluence: bool
    n_contracts: int
    entry_price: float
    entry_ts_utc: str
    sl_price: float          # SL fixe initial (200t NQ / 80t ES)
    tp_cap_price: float      # TP cap securite (500t NQ / 200t ES) — rarement touche
    timeout_at_utc: str
    features_at_entry: dict
    # Tracking live
    mfe_ticks: float = 0.0   # max favorable excursion (en ticks depuis entree)
    mae_ticks: float = 0.0   # max adverse excursion (en ticks depuis entree)
    bars_held: int = 0
    # Trailing stop state
    trailing_activated: bool = False         # passe a True quand MFE >= activation_threshold
    trailing_stop_price: Optional[float] = None  # prix du trailing courant (None tant que pas active)
    # FIX B1 CRITIQUE (incident TR40_NQ 01/05) : signal au caller que le SL broker
    # doit etre cancel+replace. Le caller DOIT :
    #   1. Detecter trailing_pending_broker_update == True
    #   2. Cancel SL broker existant via DTC
    #   3. Envoyer nouveau SL au prix trailing_stop_price
    #   4. Reset trailing_pending_broker_update = False sur succes
    # Sans ca, trailing virtuel = donnees Phase 1 invalides (TRAILING fired
    # cote bot mais position pas reellement cancelled cote SC).
    trailing_pending_broker_update: bool = False
    # Track broker SL price actuel (cancel+replace verifiable par audit J+1)
    broker_sl_price_current: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════
# RISK MANAGER — isole par symbole
# ═══════════════════════════════════════════════════════════════════

class RiskManager:
    """Risk management isole par symbole. NQ et ES n'interagissent PAS."""

    def __init__(self):
        self.n_losses_today = {"NQ": 0, "ES": 0}
        self.daily_pnl = {"NQ": 0.0, "ES": 0.0}
        self.flat_until_eod = {"NQ": False, "ES": False}
        self.flat_reason = {"NQ": None, "ES": None}
        self.trading_day = get_cme_trading_day()

    def _rotate_day_if_needed(self):
        """Reset compteurs au rollover CME 18:00 ET."""
        today = get_cme_trading_day()
        if today != self.trading_day:
            self.n_losses_today = {"NQ": 0, "ES": 0}
            self.daily_pnl = {"NQ": 0.0, "ES": 0.0}
            self.flat_until_eod = {"NQ": False, "ES": False}
            self.flat_reason = {"NQ": None, "ES": None}
            self.trading_day = today
            _emit("DAILY_RESET", trading_day=str(today))

    def can_trade(self, symbol: str) -> tuple[bool, str]:
        """Verifie si on peut ouvrir une position sur ce symbole.

        Hierarchie des kill switches (skip si None Phase 1 free-run) :
          1. GLOBAL kill switch (cross-symbole) — flash crash protection
          2. Per-symbol kill switch
          3. Per-symbol max losses
        """
        self._rotate_day_if_needed()
        if symbol not in RISK_PER_SYMBOL:
            return False, f"UNKNOWN_SYMBOL_{symbol}"

        # 1. GLOBAL kill switch (None = desactive Phase 1)
        if GLOBAL_KILL_SWITCH_DAILY_PNL is not None:
            total_pnl = sum(self.daily_pnl.values())
            if total_pnl <= GLOBAL_KILL_SWITCH_DAILY_PNL:
                for sym in ("NQ", "ES"):
                    self._activate_flat(sym, f"GLOBAL_KILL_SWITCH_TOTAL_{total_pnl:.0f}")
                return False, f"GLOBAL_KILL_SWITCH_TOTAL_{total_pnl:.0f}"

        cfg = RISK_PER_SYMBOL[symbol]
        if self.flat_until_eod[symbol]:
            return False, self.flat_reason[symbol] or f"FLAT_UNTIL_EOD_{symbol}"

        # 2. Max losses per day (None = desactive Phase 1)
        max_losses = cfg.get("max_losses_per_day")
        if max_losses is not None and self.n_losses_today[symbol] >= max_losses:
            self._activate_flat(symbol, f"MAX_LOSSES_{symbol}")
            return False, f"MAX_LOSSES_{symbol}"

        # 3. Kill switch dollar (None = desactive Phase 1)
        kill_pnl = cfg.get("kill_switch_daily_pnl")
        if kill_pnl is not None and self.daily_pnl[symbol] <= kill_pnl:
            self._activate_flat(symbol, f"KILL_SWITCH_{symbol}")
            return False, f"KILL_SWITCH_{symbol}"

        return True, "OK"

    def _activate_flat(self, symbol: str, reason: str):
        """FIX B5 : emit le bon code log selon la cause (pas KILL_DD_DAILY pour tout)."""
        if not self.flat_until_eod[symbol]:
            self.flat_until_eod[symbol] = True
            self.flat_reason[symbol] = reason
            cfg = RISK_PER_SYMBOL[symbol]
            # FIX B5 : router vers le bon code log selon la cause
            if reason.startswith("MAX_LOSSES"):
                _emit("GATE_RISK_FLAT_BY_LOSSES",
                      sym=symbol,
                      n_losses=self.n_losses_today[symbol],
                      max_losses=cfg.get("max_losses_per_day", "N/A"))
            elif reason.startswith("KILL_SWITCH"):
                _emit("GATE_RISK_KILL_SWITCH",
                      sym=symbol,
                      daily_pnl=round(self.daily_pnl[symbol], 2),
                      limit=cfg.get("kill_switch_daily_pnl", "N/A"))
            elif reason.startswith("GLOBAL_KILL_SWITCH"):
                _emit("KILL_DD_DAILY",
                      pnl=round(sum(self.daily_pnl.values()), 2),
                      limit=GLOBAL_KILL_SWITCH_DAILY_PNL)
            else:
                _emit("KILL_DD_DAILY",
                      pnl=round(self.daily_pnl[symbol], 2),
                      limit=cfg.get("kill_switch_daily_pnl", "N/A"))

    def on_trade_close(self, symbol: str, pnl_dollars: float, is_loss: bool):
        """Update apres fermeture trade."""
        self._rotate_day_if_needed()
        self.daily_pnl[symbol] += pnl_dollars
        if is_loss:
            self.n_losses_today[symbol] += 1
        # Re-check : peut declencher kill switch
        self.can_trade(symbol)

    def state_snapshot(self) -> dict:
        """Pour state.json dashboard."""
        # Phase 1 free run : kill_switch_daily_pnl peut etre None
        exposure = 0.0
        for s in ("NQ", "ES"):
            kill = RISK_PER_SYMBOL[s].get("kill_switch_daily_pnl")
            if kill is not None:
                exposure += abs(kill)
        snap = {
            "trading_day": str(self.trading_day),
            "exposure_total_max_eod": exposure if exposure > 0 else "FREE_RUN",
            "phase_1_free_run": PHASE_1_FREE_RUN,
        }
        for sym in ("NQ", "ES"):
            cfg = RISK_PER_SYMBOL[sym]
            max_losses = cfg.get("max_losses_per_day")
            kill_pnl = cfg.get("kill_switch_daily_pnl")
            snap[sym] = {
                "n_losses": self.n_losses_today[sym],
                "daily_pnl": round(self.daily_pnl[sym], 2),
                "flat_until_eod": self.flat_until_eod[sym],
                "flat_reason": self.flat_reason[sym],
                "remaining_losses": (
                    max(0, max_losses - self.n_losses_today[sym])
                    if max_losses is not None else "UNLIMITED"
                ),
                "remaining_dollar": (
                    max(0.0, self.daily_pnl[sym] - kill_pnl)
                    if kill_pnl is not None else "UNLIMITED"
                ),
            }
        return snap


# ═══════════════════════════════════════════════════════════════════
# SETUP ENGINE — eval triggers + resolve confluence + dedup
# ═══════════════════════════════════════════════════════════════════

class SetupEngine:
    """Evalue les setups V4 Bot 2 et produit Signal exécutable.

    Anti double-trigger : last_bar_ts par symbole.
    """

    # Features critiques a snapshotter pour audit (entry + exit)
    SNAPSHOT_FEATURES = [
        # === Base (V1) ===
        "position_in_range", "finish_strength", "delta_bar", "rvol",
        "dist_vwap_d_pct", "im_cross_delta_agreement_5",
        "time_to_session_close_norm", "delta_day_dir",
        "dist_1d_max_ticks_pct", "dist_1d_min_ticks_pct",
        "ctx_delta_exhaustion", "vwap_slope_10",
        "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
        "n_naked_poc_within_0_5pct",
        "rvol_zscore", "atr_14m_pct",
        "is_in_us_cash", "vix_level",
        # === Voie A (03/05) : POC migration ===
        "poc_migration_dir", "ctx_poc_migration_10", "ctx_va_developing_10",
        # === Voie A+ (03/05) : Dalton + traps + flow + naked POC + structure ===
        "open_type", "day_type",
        "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
        "cvd_session", "cvd_day",
        "dist_naked_poc_nearest_pct", "naked_poc_age_max_days",
        "ctx_failed_auction", "ctx_rotation_factor_20",
        # === Voie A++ (03/05) : GEX + spike origin + absorb_at_level + SMT + segment ===
        "bool_gex_flip_zone", "dist_gex_nearest_up_pct", "dist_gex_nearest_dn_pct",
        "dist_last_spike_origin_pct", "bars_since_last_spike",
        "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
        "im_smt_divergence",
        "session_segment",
        # === Big traders / whales (Jackson 03/05) ===
        "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
        "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
        "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar", "p99_trade_size",
        # === ICT / Wyckoff (liquidity sweeps + equal highs/lows) ===
        "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
        "equal_highs_detected", "equal_lows_detected",
        # === IB extension ===
        "ctx_ib_extension_ratio",
        # === VWAP cross events + alignment gaps ===
        "vwap_d_cross_up", "vwap_d_cross_dn",
        "vwap_w_minus_d_pct", "vwap_m_minus_w_pct",
        # === Bar patterns (structure de la barre de contact) ===
        "long_up_bar", "long_dn_bar",
        "long_dn_up_pattern", "long_up_dn_pattern",
        "rotation_up", "rotation_dn",
        # === Volume profile structure ===
        "cur_va_n_buckets", "cur_va_total_vol",
        "n_single_prints_pct", "has_single_print_above",
        "max_single_print_zone_width_ticks",
        # === ATR regime (expansion vs contraction vol) ===
        "atr_regime_zscore_60d",
        # === Roll day (deformation volume front/back month) ===
        "is_roll_day", "roll_phase", "days_since_roll",
    ]

    def __init__(self):
        # Anti double-trigger : on ne re-evalue pas la meme bar 2x
        self.last_bar_ts: dict[str, Optional[str]] = {"NQ": None, "ES": None}

    def evaluate(self, bar, symbol: str) -> Optional[Signal]:
        """Evalue les setups sur 1 bar. Retourne Signal ou None.

        Returns:
            Signal si triggers convergent (LONG ou SHORT all same direction)
            None si :
              - bar_ts identique au dernier (dedup)
              - aucun trigger
              - conflit (LONG + SHORT en meme temps)
              - hors RTH (is_in_us_cash != 1)
        """
        if symbol not in ("NQ", "ES"):
            return None

        # ─── ANTI DOUBLE-TRIGGER (critique) ─────────────────
        bar_ts_raw = bar.get("ts_event") if hasattr(bar, "get") else None
        if bar_ts_raw is None:
            return None
        bar_ts_str = str(bar_ts_raw)
        if self.last_bar_ts[symbol] == bar_ts_str:
            # FIX B4 : emit DEDUP_BAR_TS pour audit J+1
            _emit("DEDUP_BAR_TS", sym=symbol, bar_ts=bar_ts_str)
            return None  # deja evaluee

        # ─── FILTRE TRADING WINDOW (Jackson 02/05) ──────────
        # 24h ALL SESSIONS mais avec pause sommeil 23h-4h FR (= 21h-02h UTC ete).
        try:
            dt = datetime.fromisoformat(bar_ts_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hour_utc = dt.hour
            in_window = (TRADING_WINDOW_START_UTC <= hour_utc < TRADING_WINDOW_END_UTC)
            if not in_window:
                _emit("GATE_RTH_BLOCK", sym=symbol,
                      hour_utc=float(hour_utc),
                      reason=f"outside_trading_window_{TRADING_WINDOW_START_UTC}h-{TRADING_WINDOW_END_UTC}h_UTC")
                self.last_bar_ts[symbol] = bar_ts_str
                return None
        except (ValueError, TypeError):
            self.last_bar_ts[symbol] = bar_ts_str
            return None

        # ─── VETO NEWS ECO (Jackson 02/05) ──────────────────
        # Skip si dans la fenetre +/-5min d'une news majeure (FOMC, NFP, CPI, etc.)
        if is_in_news_buffer(bar):
            _emit("GATE_RTH_BLOCK", sym=symbol,
                  hour_utc=0.0,
                  reason="within_news_buffer_5min")
            self.last_bar_ts[symbol] = bar_ts_str
            return None

        # ─── FIX market-analyst : VETO ATR EXTREME (anti flash crash) ───
        atr_pct = bar.get("atr_14m_pct") if hasattr(bar, "get") else None
        if atr_pct is not None:
            try:
                a = float(atr_pct)
                if a == a and a > VETO_ATR_14M_PCT_MAX:
                    _emit("VOLATILITY_SPIKE",
                          ratio=a / VETO_ATR_14M_PCT_MAX,
                          limit=VETO_ATR_14M_PCT_MAX)
                    self.last_bar_ts[symbol] = bar_ts_str
                    return None
            except (ValueError, TypeError):
                pass

        # ─── EVAL SETUPS ─────────────────────────────────────
        triggered = evaluate_all_setups(bar, symbol)
        # On marque maintenant la bar comme vue (qu'il y ait trigger ou pas)
        self.last_bar_ts[symbol] = bar_ts_str

        if not triggered:
            # 04/05 SOIR : audit "0 setup detecte" Bot 2 V2 (Jackson empirique).
            # Trace explicite quand evaluate_all_setups retourne [] pour
            # distinguer "evaluated mais aucun match" vs "jamais evalue".
            # Audit J+1 : compter SETUP_NO_TRIGGER vs SETUP_DETECTED.
            try:
                _emit("SETUP_NO_TRIGGER", sym=symbol, bar_ts=bar_ts_str)
            except Exception:
                pass
            return None

        # ─── RESOLVE CONFLUENCE / CONFLICT ───────────────────
        sides = {t["side"] for t in triggered}
        if len(sides) > 1:
            # Conflict : LONG + SHORT en meme temps -> SKIP
            _emit("SETUP_CONFLICT_SKIP",
                  symbol=symbol,
                  setups_long=[t["name"] for t in triggered if t["side"] == "LONG"],
                  setups_short=[t["name"] for t in triggered if t["side"] == "SHORT"],
                  bar_ts=bar_ts_str)
            return None

        side = sides.pop()
        names = [t["name"] for t in triggered]

        # ─── BUILD SIGNAL ────────────────────────────────────
        price = bar.get("close") if hasattr(bar, "get") else None
        try:
            price = float(price)
        except (ValueError, TypeError):
            return None

        features_snapshot = {}
        for feat in self.SNAPSHOT_FEATURES:
            v = bar.get(feat) if hasattr(bar, "get") else None
            if v is not None:
                try:
                    f = float(v)
                    if f == f and abs(f) != float("inf"):
                        features_snapshot[feat] = round(f, 6)
                except (ValueError, TypeError):
                    pass

        signal = Signal(
            symbol=symbol,
            side=side,
            setups=names,
            confluence=len(names) > 1,
            bar_ts=bar_ts_str,
            price=price,
            features_at_trigger=features_snapshot,
        )

        if signal.confluence:
            _emit("SETUP_CONFLUENCE",
                  symbol=symbol, side=side, setups=names,
                  bar_ts=bar_ts_str, price=price)
        else:
            _emit("SETUP_TRIGGERED",
                  symbol=symbol, side=side, setup=names[0],
                  bar_ts=bar_ts_str, price=price)

        return signal


# ═══════════════════════════════════════════════════════════════════
# POSITION TRACKER — MFE/MAE update pendant la vie du trade
# ═══════════════════════════════════════════════════════════════════

def make_position(signal: Signal, fill_price: float, fill_ts_utc: str) -> Position:
    """Cree une Position depuis un Signal + fill DTC.

    Place SL fixe + TP cap securite. Trailing stop sera calcule dynamiquement
    pendant la vie du trade via update_mfe_mae (pas figé a l'entree).
    """
    cfg = TRAILING_CONFIG[signal.symbol]
    sl_pts = cfg["sl_ticks"] * TICK_SIZE
    tp_cap_pts = cfg["tp_cap_ticks"] * TICK_SIZE

    if signal.side == "LONG":
        sl_price = fill_price - sl_pts
        tp_cap_price = fill_price + tp_cap_pts
    else:  # SHORT
        sl_price = fill_price + sl_pts
        tp_cap_price = fill_price - tp_cap_pts

    # Timeout
    fill_dt = datetime.fromisoformat(fill_ts_utc.replace("Z", "+00:00"))
    if fill_dt.tzinfo is None:
        fill_dt = fill_dt.replace(tzinfo=timezone.utc)
    timeout_dt = fill_dt.timestamp() + cfg["timeout_minutes"] * 60
    timeout_str = datetime.fromtimestamp(timeout_dt, tz=timezone.utc).isoformat()

    return Position(
        symbol=signal.symbol,
        side=signal.side,
        setups=signal.setups,
        confluence=signal.confluence,
        n_contracts=cfg["n_contracts"],
        entry_price=fill_price,
        entry_ts_utc=fill_ts_utc,
        sl_price=sl_price,
        tp_cap_price=tp_cap_price,
        timeout_at_utc=timeout_str,
        features_at_entry=signal.features_at_trigger,
    )


def update_mfe_mae(position: Position, current_price: float) -> Position:
    """Update MFE/MAE en ticks + active/update trailing stop si applicable.

    Logique trailing :
      1. Si MFE >= trailing_activation_ticks et trailing pas encore active :
         active trailing, place trailing_stop_price = entry_price ± distance
         (cote favorable)
      2. Si trailing deja active : maj trailing_stop_price uniquement si le
         nouveau MFE est plus haut (LONG) ou plus bas (SHORT) — anti-recul.

    FIX B1 (incident TR40_NQ 01/05) : si trailing_stop_price change, set
    trailing_pending_broker_update=True. Le caller DOIT cancel+replace le
    SL broker avant de re-appeler check_exit_condition, sinon donnees biaisees.

    A appeler a chaque tick / barre.
    """
    cfg = TRAILING_CONFIG[position.symbol]
    activation_ticks = cfg["trailing_activation_ticks"]
    distance_ticks = cfg["trailing_distance_ticks"]

    delta_pts = current_price - position.entry_price
    delta_ticks = delta_pts / TICK_SIZE

    if position.side == "LONG":
        # favorable = price up
        if delta_ticks > position.mfe_ticks:
            position.mfe_ticks = delta_ticks
        # adverse = price down (negatif)
        if delta_ticks < 0 and abs(delta_ticks) > position.mae_ticks:
            position.mae_ticks = abs(delta_ticks)

        # Trailing logic LONG
        if position.mfe_ticks >= activation_ticks:
            # Trailing devrait etre actif. Calculer le prix trailing actuel.
            best_price = position.entry_price + position.mfe_ticks * TICK_SIZE
            new_trailing = best_price - distance_ticks * TICK_SIZE
            if not position.trailing_activated:
                position.trailing_activated = True
                position.trailing_stop_price = new_trailing
                position.trailing_pending_broker_update = True  # FIX B1
                _emit("TRAILING_ACTIVATED",
                      sym=position.symbol, old=position.sl_price,
                      new=round(new_trailing, 2))
            else:
                # Trail anti-recul : on ne BAISSE PAS le trailing pour LONG
                if (position.trailing_stop_price is None
                        or new_trailing > position.trailing_stop_price):
                    old = position.trailing_stop_price
                    position.trailing_stop_price = new_trailing
                    position.trailing_pending_broker_update = True  # FIX B1
                    _emit("TRAILING_ACTIVATED",
                          sym=position.symbol, old=round(old, 2) if old else None,
                          new=round(new_trailing, 2))

    else:  # SHORT
        # favorable = price down
        if -delta_ticks > position.mfe_ticks:
            position.mfe_ticks = -delta_ticks
        # adverse = price up
        if delta_ticks > 0 and delta_ticks > position.mae_ticks:
            position.mae_ticks = delta_ticks

        # Trailing logic SHORT
        if position.mfe_ticks >= activation_ticks:
            best_price = position.entry_price - position.mfe_ticks * TICK_SIZE
            new_trailing = best_price + distance_ticks * TICK_SIZE
            if not position.trailing_activated:
                position.trailing_activated = True
                position.trailing_stop_price = new_trailing
                position.trailing_pending_broker_update = True  # FIX B1
                _emit("TRAILING_ACTIVATED",
                      sym=position.symbol, old=position.sl_price,
                      new=round(new_trailing, 2))
            else:
                # Trail anti-recul : on ne MONTE PAS le trailing pour SHORT
                if (position.trailing_stop_price is None
                        or new_trailing < position.trailing_stop_price):
                    old = position.trailing_stop_price
                    position.trailing_stop_price = new_trailing
                    position.trailing_pending_broker_update = True  # FIX B1
                    _emit("TRAILING_ACTIVATED",
                          sym=position.symbol, old=round(old, 2) if old else None,
                          new=round(new_trailing, 2))

    return position


# ═══════════════════════════════════════════════════════════════════
# SETUP STATS TRACKER (Jackson 02/05) — track reussite par setup
# ═══════════════════════════════════════════════════════════════════

class SetupStatsTracker:
    """Tracker cumulatif par setup (in-memory + persist state.json).

    Chaque trade fermé met a jour les stats du/des setups qui ont declenche
    le trade. Pour confluence, le PnL est attribue a CHAQUE setup individuel
    (pas split) — permet de mesurer la "contribution" reelle de chaque setup.

    Stats trackees par setup :
      - n_trades, n_wins, wr_pct
      - pnl_total_usd, pnl_avg_usd
      - mfe_avg_ticks, mae_avg_ticks
      - exit_reason_counts (TP_CAP/SL/TRAILING/TIMEOUT)
      - n_solo_trades, n_confluence_trades
      - sessions : counts par session_label (ASIA/LONDON/RTH_US/AFTER_HOURS_US)
    """

    def __init__(self):
        self.stats: dict[str, dict] = {}  # setup_name -> stats dict

    def _ensure_setup(self, setup_name: str):
        if setup_name not in self.stats:
            self.stats[setup_name] = {
                "n_trades": 0,
                "n_wins": 0,
                "n_losses": 0,
                "pnl_total_usd": 0.0,
                "pnl_total_ticks": 0.0,
                "mfe_sum_ticks": 0.0,
                "mae_sum_ticks": 0.0,
                "exit_reasons": {},  # count par reason
                "n_solo_trades": 0,
                "n_confluence_trades": 0,
                "sessions": {},  # count par session_label
            }

    def record_trade(self, position: Position, pnl_dollars: float,
                     pnl_ticks: float, exit_reason: str,
                     session_label: str):
        """Update stats pour CHAQUE setup qui a contribue au trade.

        FIX B-4 (02/05 soir review market-analyst) : pour confluence (>=2 setups),
        on SPLIT le PnL au prorata 1/n_setups au lieu d'attribuer 100% a chacun.
        Sinon les setups "jamais solos" auront PF artificiellement gonfles
        (double-comptage) et fausseront la calibration Phase 2.

        Solo : 1 setup → 100% du PnL attribue.
        Confluence 2 setups : 50% chacun.
        Confluence 3 setups : 33% chacun.
        Etc.
        """
        is_winner = pnl_dollars > 0
        is_solo = not position.confluence
        n_setups = len(position.setups)
        # Split prorata
        pnl_dollars_share = pnl_dollars / n_setups if n_setups > 0 else 0.0
        pnl_ticks_share = pnl_ticks / n_setups if n_setups > 0 else 0.0
        # MFE/MAE = pas split (= max favorable/adverse du trade, attribuable
        # entierement a chaque setup pour mesurer "ce que CE setup a permis")
        # mais comptabilises avec un share pour le moyennage.

        for setup_name in position.setups:
            self._ensure_setup(setup_name)
            s = self.stats[setup_name]
            s["n_trades"] += 1
            if is_winner:
                s["n_wins"] += 1
            else:
                s["n_losses"] += 1
            # FIX B-4 : split prorata
            s["pnl_total_usd"] += pnl_dollars_share
            s["pnl_total_ticks"] += pnl_ticks_share
            s["mfe_sum_ticks"] += position.mfe_ticks
            s["mae_sum_ticks"] += position.mae_ticks
            s["exit_reasons"][exit_reason] = s["exit_reasons"].get(exit_reason, 0) + 1
            if is_solo:
                s["n_solo_trades"] += 1
            else:
                s["n_confluence_trades"] += 1
            s["sessions"][session_label] = s["sessions"].get(session_label, 0) + 1

    def snapshot(self) -> dict:
        """Snapshot pour state.json — calcule WR/PF/avg a la lecture."""
        out = {}
        for setup_name, s in self.stats.items():
            n = s["n_trades"]
            n_wins = s["n_wins"]
            n_losses = s["n_losses"]
            wr_pct = round((n_wins / n * 100), 1) if n > 0 else 0.0
            pnl_avg = round(s["pnl_total_usd"] / n, 2) if n > 0 else 0.0
            mfe_avg = round(s["mfe_sum_ticks"] / n, 2) if n > 0 else 0.0
            mae_avg = round(s["mae_sum_ticks"] / n, 2) if n > 0 else 0.0
            # PF approx : on n'a pas la decomposition gains/pertes individuelle
            # ici, juste le total. Pour PF exact, utiliser le script d'analyse.
            out[setup_name] = {
                "n_trades": n,
                "n_wins": n_wins,
                "n_losses": n_losses,
                "wr_pct": wr_pct,
                "pnl_total_usd": round(s["pnl_total_usd"], 2),
                "pnl_total_ticks": round(s["pnl_total_ticks"], 2),
                "pnl_avg_usd": pnl_avg,
                "mfe_avg_ticks": mfe_avg,
                "mae_avg_ticks": mae_avg,
                "n_solo": s["n_solo_trades"],
                "n_confluence": s["n_confluence_trades"],
                "exit_reasons": dict(s["exit_reasons"]),
                "sessions": dict(s["sessions"]),
            }
        # Sort by pnl_total_usd descending
        out = dict(sorted(out.items(),
                          key=lambda x: x[1]["pnl_total_usd"], reverse=True))
        return out

    def reset(self):
        """Reset stats (rollover trading day)."""
        self.stats.clear()


def acknowledge_broker_sl_update(position: Position, new_broker_sl_price: float) -> None:
    """FIX B1 : appele par le caller (databento_paper_trader) APRES cancel+replace
    DTC reussi. Reset le flag pending et update le broker_sl_price_current
    pour reflet exact du SL place cote broker.
    """
    position.broker_sl_price_current = new_broker_sl_price
    position.trailing_pending_broker_update = False


def compute_seconds_until_timeout(position: Position) -> int:
    """Pour dashboard : countdown timeout en secondes.

    Returns secondes restantes avant timeout (>= 0). Si timeout depasse,
    retourne 0 (le bot va close au prochain cycle).
    """
    try:
        timeout_dt = datetime.fromisoformat(
            position.timeout_at_utc.replace("Z", "+00:00")
        )
        if timeout_dt.tzinfo is None:
            timeout_dt = timeout_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        delta = (timeout_dt - now_dt).total_seconds()
        return max(0, int(delta))
    except (ValueError, TypeError):
        return 0


def check_exit_condition(position: Position, current_price: float,
                          current_ts_utc: str) -> Optional[str]:
    """Retourne raison de sortie ou None si trade reste ouvert.

    Ordre de priorite :
      1. SL initial (200t NQ / 80t ES) — protection downside
      2. TP cap (500t NQ / 200t ES) — securite anti-tail extreme
      3. Trailing stop (si active) — verrouille les gains
      4. Timeout 30min — filet final

    Returns: "SL" | "TP_CAP" | "TRAILING" | "TIMEOUT" | None
    """
    # ─── 1. SL initial (priorite max) ─────────────────────────
    if position.side == "LONG":
        if current_price <= position.sl_price:
            return "SL"
    else:  # SHORT
        if current_price >= position.sl_price:
            return "SL"

    # ─── 2. TP cap (securite extreme) ─────────────────────────
    if position.side == "LONG":
        if current_price >= position.tp_cap_price:
            return "TP_CAP"
    else:  # SHORT
        if current_price <= position.tp_cap_price:
            return "TP_CAP"

    # ─── 3. Trailing stop (si active) ─────────────────────────
    # FIX B1 : si pending_broker_update == True, le trailing n'est pas encore
    # actif cote broker -> ne PAS declencher TRAILING (eviter reproduce TR40_NQ
    # 01/05 ou bot ferme position virtuellement mais broker garde position ouverte).
    if (position.trailing_activated
            and position.trailing_stop_price is not None
            and not position.trailing_pending_broker_update):
        if position.side == "LONG":
            if current_price <= position.trailing_stop_price:
                _emit("TRAILING_TRIGGERED",
                      sym=position.symbol, side=position.side,
                      trailing_stop=round(position.trailing_stop_price, 2),
                      mfe_ticks=round(position.mfe_ticks, 2),
                      pnl_ticks=round((current_price - position.entry_price) / TICK_SIZE, 2))
                return "TRAILING"
        else:  # SHORT
            if current_price >= position.trailing_stop_price:
                _emit("TRAILING_TRIGGERED",
                      sym=position.symbol, side=position.side,
                      trailing_stop=round(position.trailing_stop_price, 2),
                      mfe_ticks=round(position.mfe_ticks, 2),
                      pnl_ticks=round((position.entry_price - current_price) / TICK_SIZE, 2))
                return "TRAILING"

    # ─── 4. Timeout (filet de securite final) ─────────────────
    try:
        now_dt = datetime.fromisoformat(current_ts_utc.replace("Z", "+00:00"))
        timeout_dt = datetime.fromisoformat(position.timeout_at_utc.replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        if timeout_dt.tzinfo is None:
            timeout_dt = timeout_dt.replace(tzinfo=timezone.utc)
        if now_dt >= timeout_dt:
            return "TIMEOUT"
    except (ValueError, TypeError):
        pass

    return None


# ═══════════════════════════════════════════════════════════════════
# TRADE LOGGER — JSONL append-only
# ═══════════════════════════════════════════════════════════════════

def _trade_log_path() -> Path:
    """FIX I4 : utilise CME trading day (rollover 18:00 ET DST-aware) au lieu
    de UTC midnight. Aligne le nom du fichier log avec la session de trading
    reelle (RiskManager rotate aussi sur CME day) → audit J+1 coherent.
    """
    SETUPS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = get_cme_trading_day()
    today_str = today.strftime("%Y%m%d") if hasattr(today, "strftime") else str(today)
    return SETUPS_LOG_DIR / f"{today_str}_setups_trades.jsonl"


def log_trade_entry(position: Position):
    """Logue l'entry d'un trade (ts_exit, exit_reason, pnl rempli plus tard).
    FIX B4 : emit SETUP_TRADE_OPEN code catalog.
    FIX market-analyst : ajout regime_label + setup_label_solo_or_confluence.
    """
    setup_label = position.setups[0] if not position.confluence else "+".join(position.setups)
    # Solo vs confluence label pour analyse Phase 1 (PF par type)
    if not position.confluence:
        solo_or_confluence_label = f"SOLO_{position.setups[0]}"
    else:
        solo_or_confluence_label = f"CONFLUENCE_{len(position.setups)}_{'+'.join(position.setups)}"
    # Regime label depuis vix_level snapshot at entry
    vix_at_entry = position.features_at_entry.get("vix_level")
    regime_label = compute_regime_label(vix_at_entry)
    # Session label (Jackson 02/05) — Asia / London / RTH_US / AFTER_HOURS_US
    session_label = compute_session_label(position.entry_ts_utc)

    _emit("SETUP_TRADE_OPEN",
          sym=position.symbol, side=position.side, setup=setup_label,
          entry_price=position.entry_price, sl_price=position.sl_price,
          tp_cap_price=position.tp_cap_price)
    entry = {
        "event": "ENTRY",
        "ts_entry": position.entry_ts_utc,
        "ts_exit": None,
        "symbol": position.symbol,
        "setup_name": setup_label,
        "setup_label_solo_or_confluence": solo_or_confluence_label,  # FIX market-analyst
        "regime_label": regime_label,                                # FIX market-analyst
        "session_label": session_label,                              # Jackson 02/05
        "side": position.side,
        "confluence": position.confluence,
        "all_setups": position.setups,
        "n_contracts": position.n_contracts,
        "price_entry": position.entry_price,
        "price_exit": None,
        "exit_reason": None,
        "pnl_ticks": None,
        "pnl_dollars": None,
        "mfe_ticks": 0.0,
        "mae_ticks": 0.0,
        "duration_seconds": None,
        "sl_price": position.sl_price,
        "tp_cap_price": position.tp_cap_price,
        "trailing_activated": False,
        "trailing_stop_price": None,
        "timeout_at_utc": position.timeout_at_utc,
        "features_at_entry": position.features_at_entry,
        "mode": "PAPER_TRADE",
    }
    try:
        with _trade_log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        import sys
        print(f"[log_trade_entry FAIL] {e}", file=sys.stderr, flush=True)


def log_trade_exit(position: Position, exit_price: float, exit_reason: str,
                     exit_ts_utc: str):
    """Logue l'exit du trade (1 nouvelle entry JSONL avec event='EXIT').

    NB : on ecrit une 2eme ligne plutot que de modifier l'ENTRY (append-only
    safe). L'audit script merge ENTRY + EXIT par (ts_entry, symbol).

    Returns: (pnl_dollars, is_winner) pour update RiskManager.
    """
    cfg = TRAILING_CONFIG[position.symbol]
    delta_pts = exit_price - position.entry_price
    delta_ticks = delta_pts / TICK_SIZE
    if position.side == "SHORT":
        delta_ticks = -delta_ticks
    pnl_ticks = round(delta_ticks, 2)
    pnl_dollars = round(pnl_ticks * cfg["tick_value_dollars"] * position.n_contracts, 2)

    try:
        entry_dt = datetime.fromisoformat(position.entry_ts_utc.replace("Z", "+00:00"))
        exit_dt = datetime.fromisoformat(exit_ts_utc.replace("Z", "+00:00"))
        duration = (exit_dt - entry_dt).total_seconds()
    except (ValueError, TypeError):
        duration = None

    setup_label = position.setups[0] if not position.confluence else "+".join(position.setups)
    if not position.confluence:
        solo_or_confluence_label = f"SOLO_{position.setups[0]}"
    else:
        solo_or_confluence_label = f"CONFLUENCE_{len(position.setups)}_{'+'.join(position.setups)}"
    vix_at_entry = position.features_at_entry.get("vix_level")
    regime_label = compute_regime_label(vix_at_entry)
    # Session label entry+exit pour analyse Phase 1
    session_entry = compute_session_label(position.entry_ts_utc)
    session_exit = compute_session_label(exit_ts_utc)

    exit_log = {
        "event": "EXIT",
        "ts_entry": position.entry_ts_utc,
        "ts_exit": exit_ts_utc,
        "symbol": position.symbol,
        "setup_name": setup_label,
        "setup_label_solo_or_confluence": solo_or_confluence_label,  # FIX market-analyst
        "regime_label": regime_label,                                # FIX market-analyst
        "session_label_entry": session_entry,                        # Jackson 02/05
        "session_label_exit": session_exit,                          # Jackson 02/05 (cross-session?)
        "side": position.side,
        "confluence": position.confluence,
        "all_setups": position.setups,
        "n_contracts": position.n_contracts,
        "price_entry": position.entry_price,
        "price_exit": exit_price,
        "exit_reason": exit_reason,    # "SL" | "TP_CAP" | "TRAILING" | "TIMEOUT" | "MANUAL"
        "pnl_ticks": pnl_ticks,
        "pnl_dollars": pnl_dollars,
        "mfe_ticks": round(position.mfe_ticks, 2),
        "mae_ticks": round(position.mae_ticks, 2),
        "duration_seconds": duration,
        "sl_price": position.sl_price,
        "tp_cap_price": position.tp_cap_price,
        "trailing_activated": position.trailing_activated,
        "trailing_stop_price": (round(position.trailing_stop_price, 2)
                                if position.trailing_stop_price is not None else None),
        "features_at_entry": position.features_at_entry,
        "mode": "PAPER_TRADE",
    }
    try:
        with _trade_log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(exit_log, ensure_ascii=False) + "\n")
    except Exception as e:
        import sys
        print(f"[log_trade_exit FAIL] {e}", file=sys.stderr, flush=True)

    # FIX B4 : emit SETUP_TRADE_CLOSE code catalog
    setup_label = position.setups[0] if not position.confluence else "+".join(position.setups)
    _emit("SETUP_TRADE_CLOSE",
          sym=position.symbol, side=position.side, setup=setup_label,
          exit_reason=exit_reason, pnl_ticks=pnl_ticks, pnl_dollars=pnl_dollars,
          mfe_ticks=round(position.mfe_ticks, 2),
          mae_ticks=round(position.mae_ticks, 2))

    return pnl_dollars, pnl_ticks > 0


# ═══════════════════════════════════════════════════════════════════
# Smoke test
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test SetupEngine + dedup
    engine = SetupEngine()
    risk = RiskManager()

    bar1 = {
        "ts_event": "2026-05-05T14:00:00+00:00",
        "is_in_us_cash": 1,
        "close": 27800.0,
        "position_in_range": 0.95,
        "finish_strength": -20,
        "vix_level": 18.5,
    }
    sig1 = engine.evaluate(bar1, "NQ")
    print(f"Bar1 NQ : signal={'OUI' if sig1 else 'NON'}")
    if sig1:
        print(f"  side={sig1.side} setups={sig1.setups} confluence={sig1.confluence}")

    # Re-evaluation meme bar (dedup actif)
    sig2 = engine.evaluate(bar1, "NQ")
    print(f"Bar1 NQ (re-eval) : signal={'OUI' if sig2 else 'NON (dedup OK)'}")
    assert sig2 is None, "DEDUP DOIT BLOQUER"

    # Bar suivante
    bar2 = {**bar1, "ts_event": "2026-05-05T14:01:00+00:00"}
    sig3 = engine.evaluate(bar2, "NQ")
    print(f"Bar2 NQ : signal={'OUI' if sig3 else 'NON'} (nouveau ts -> ok)")

    # Risk state
    print(f"\nRisk snapshot : {json.dumps(risk.state_snapshot(), indent=2)}")
    can, reason = risk.can_trade("NQ")
    print(f"can_trade NQ : {can} ({reason})")

    # Make position + simulate trades pour verifier MFE/MAE + TRAILING
    if sig1:
        pos = make_position(sig1, fill_price=27800.0, fill_ts_utc=bar1["ts_event"])
        print(f"\nPosition : entry={pos.entry_price} sl={pos.sl_price} tp_cap={pos.tp_cap_price}")
        print(f"  Trailing config NQ : activation 80t / distance 60t / timeout 40min")

        # SHORT, prix descend de 27800 -> 27780 (+80t favorable, trailing activation)
        update_mfe_mae(pos, 27780.0)
        print(f"  Apres prix=27780 (+80t MFE) : trailing_activated={pos.trailing_activated} "
              f"trailing_stop={pos.trailing_stop_price}")
        assert pos.trailing_activated, "Trailing devrait s'activer a +80t MFE"
        assert pos.trailing_stop_price == 27795.0, f"Trailing devrait etre 27780+60t=27795, got {pos.trailing_stop_price}"

        # Prix continue 27780 -> 27750 (+125t MFE, trailing trail down)
        update_mfe_mae(pos, 27750.0)
        print(f"  Apres prix=27750 (+200t MFE) : trailing_stop={pos.trailing_stop_price}")
        assert pos.trailing_stop_price == 27765.0, f"Trailing devrait suivre a 27750+60t=27765, got {pos.trailing_stop_price}"

        # Prix recule a 27770 (MFE inchange, trailing inchange — anti-recul)
        update_mfe_mae(pos, 27770.0)
        print(f"  Apres prix=27770 (recul, MFE garde 200t) : trailing_stop={pos.trailing_stop_price}")
        assert pos.trailing_stop_price == 27765.0, "Trailing ne doit PAS reculer"

        # FIX B1 : caller doit ack le broker SL update avant TRAILING peut declencher
        print(f"  Pending broker update : {pos.trailing_pending_broker_update}")
        acknowledge_broker_sl_update(pos, new_broker_sl_price=27765.0)
        print(f"  Apres ack broker : pending={pos.trailing_pending_broker_update}, broker_sl={pos.broker_sl_price_current}")

        # Maintenant prix touche trailing 27765 -> exit TRAILING
        exit_reason = check_exit_condition(pos, 27765.0, "2026-05-05T14:10:00+00:00")
        print(f"  Apres prix=27765 : exit_reason={exit_reason}")
        assert exit_reason == "TRAILING", f"Devrait sortir TRAILING, got {exit_reason}"

        print(f"\n  Position finale :")
        print(f"    MFE = {pos.mfe_ticks}t | MAE = {pos.mae_ticks}t")
        print(f"    Trailing activated = {pos.trailing_activated}")
        print(f"    PnL ticks = +{(pos.entry_price - 27765.0) / TICK_SIZE:.0f}t (SHORT)")
        print(f"\nALL TRAILING TESTS PASSED ✓")
