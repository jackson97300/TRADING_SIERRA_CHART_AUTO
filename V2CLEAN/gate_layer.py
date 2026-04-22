"""
V2CLEAN — Gate Layer (17/04/2026)
==================================

Orchestrateur des gates de pré-trade. Chaque barre passe par 5 gates en cascade :

  1. PrecheckGate  — validation input (tz-aware, NaN ratio, features count, data stale)
  2. MacroGate     — session US RTH + VIX + calendrier éco
  3. RiskGate      — position ouverte, cooldowns, DD journalier, circuit breaker,
                     level protection (7 checks combinés)
  4. MenthorQGate  — distance minimum à un niveau options
  5. MLGate        — seuils primary + meta, avec flag require_calibration

Short-circuit : première gate qui REJECT stoppe l'évaluation.
Mode `full_evaluation=True` : toutes gates évaluées (pour debug/analytics).

Design :
  - Protocol au lieu de abstract class (moderne Python 3.11+, pas d'inheritance)
  - Dataclass frozen pour tous les input/output (immutables, thread-safe)
  - Pas de magic numbers (tout depuis CONFIG)
  - Logging sérialisable JSONL via `GateLayerResult.to_json()`
  - Latence cible < 500µs (vérifiée par test)

Post-review : 7 modifications obligatoires agent code-reviewer appliquées.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Mapping, Optional, Protocol, runtime_checkable

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except ImportError:
    import pytz
    _ET = pytz.timezone("America/New_York")

from V2CLEAN.common.json_utils import jsonify_value as _jsonify_value
from V2CLEAN.config import (
    CONFIG,
    CONFIG_SCHEMA_VERSION,
    Direction,
    Symbol,
    is_in_eco_window,
)

# Systeme logs V2 (Chantier 3 22/04)
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("v2clean_gate_layer", process="v2clean")
except Exception:
    _v2log = None


# ═══════════════════════════════════════════════════════════════════════════════
# TYPED METADATA (remplace Mapping[str, Any] trop permissif)
# ═══════════════════════════════════════════════════════════════════════════════

# Pour simplicité Phase 1 : Any mais contraint via docstring par gate
# Phase 2 : TypedDict par gate si besoin
GateMetadata = Mapping[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# DOMAIN DATACLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ProtectedLevel:
    """Niveau de prix temporairement protégé après trade (WIN 20 min, LOSS 30 min).

    Agent requirement : remplacer list[tuple] anonyme par classe dédiée.
    Purge : `is_expired(now)` → True quand à retirer.
    """
    price_low: float
    price_high: float
    expires_at: datetime                    # UTC
    outcome: Literal["WIN", "LOSS"]
    protected_at: datetime                  # UTC

    def __post_init__(self):
        if self.price_low > self.price_high:
            raise ValueError(
                f"price_low ({self.price_low}) > price_high ({self.price_high})"
            )
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be tz-aware")

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def contains(self, price: float) -> bool:
        return self.price_low <= price <= self.price_high


@dataclass(frozen=True)
class PositionState:
    """État positions + risk courant (snapshot bot).

    Agent requirement : étendre avec symbol, entry_ts, daily_trades_by_symbol.
    """
    has_open_position: bool
    open_position_symbol: Optional[Symbol] = None
    open_position_direction: Optional[Direction] = None
    open_position_entry_ts: Optional[datetime] = None
    current_price: float = 0.0
    # Counters globaux
    consecutive_losses: int = 0
    daily_pnl_usd: float = 0.0
    daily_trades_by_symbol: Mapping[Symbol, int] = field(default_factory=dict)
    # Timestamps
    last_trade_close_ts: Optional[datetime] = None
    last_trade_outcome: Optional[Literal["WIN", "LOSS"]] = None
    circuit_breaker_until: Optional[datetime] = None
    # Protection niveaux
    level_protected_ranges: tuple[ProtectedLevel, ...] = ()

    def __post_init__(self):
        # Si position ouverte, symbol doit être défini
        if self.has_open_position and self.open_position_symbol is None:
            raise ValueError("open position requires open_position_symbol")
        # Timestamps tz-aware
        for attr in ("open_position_entry_ts", "last_trade_close_ts",
                     "circuit_breaker_until"):
            val = getattr(self, attr)
            if val is not None and val.tzinfo is None:
                raise ValueError(f"{attr} must be tz-aware")

    def trades_today(self, symbol: Symbol) -> int:
        """Count trades du jour pour ce symbole."""
        return self.daily_trades_by_symbol.get(symbol, 0)

    def has_open_on(self, symbol: Symbol) -> bool:
        """True si position ouverte SPÉCIFIQUEMENT sur ce symbole."""
        return self.has_open_position and self.open_position_symbol == symbol


@dataclass(frozen=True)
class GateState:
    """Input complet d'une évaluation de gate layer."""
    timestamp: datetime                      # UTC, barre courante
    symbol: Symbol
    features_row: Mapping[str, float]        # 266 cols JSONL
    ml_scores: Mapping[str, float]           # p_primary_buy/sell, p_meta
    position_state: PositionState
    vix_level: float

    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be tz-aware UTC")


@dataclass(frozen=True)
class GateResult:
    """Output d'une gate unique."""
    passed: bool
    gate_name: str
    reason: str
    direction_allowed: Direction = Direction.HOLD
    metadata: GateMetadata = field(default_factory=dict)


@dataclass(frozen=True)
class GateLayerResult:
    """Output global de l'orchestrateur."""
    decision: Direction
    all_passed: bool
    rejected_by: Optional[str] = None
    reason: str = ""
    gate_results: tuple[GateResult, ...] = ()
    evaluation_time_ms: float = 0.0
    schema_version: str = CONFIG_SCHEMA_VERSION

    def to_json(self) -> dict:
        """Sérialisation JSONL-compatible (pour logging).

        Convertit datetime→ISO, numpy scalar→Python natif, fallback str()
        pour garantir que json.dumps(result.to_json()) ne crashe jamais.
        """
        return {
            "decision": self.decision.value,
            "all_passed": self.all_passed,
            "rejected_by": self.rejected_by,
            "reason": self.reason,
            "evaluation_time_ms": round(self.evaluation_time_ms, 3),
            "schema_version": self.schema_version,
            "gate_results": [
                {
                    "passed": gr.passed,
                    "gate_name": gr.gate_name,
                    "reason": gr.reason,
                    "direction_allowed": gr.direction_allowed.value,
                    "metadata": _jsonify_value(gr.metadata),
                }
                for gr in self.gate_results
            ],
        }


# _jsonify_value deplace vers V2CLEAN.common.json_utils (17/04/2026)
# Import en tete du module pour eviter duplication avec event_journal


# ═══════════════════════════════════════════════════════════════════════════════
# GATE PROTOCOL
# ═══════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class Gate(Protocol):
    """Contrat d'une gate : nom + méthode evaluate."""
    name: str

    def evaluate(self, state: GateState) -> GateResult: ...


# ═══════════════════════════════════════════════════════════════════════════════
# PRECHECK GATE (validation input — évite crashes downstream)
# ═══════════════════════════════════════════════════════════════════════════════

class PrecheckGate:
    """Vérifie la qualité du snapshot AVANT toute logique métier.

    Checks :
      - features_row contient au moins `min_features_count` colonnes
      - NaN ratio < 5% (bug DMP C++ possible)
      - vix_level finite
      - data stale : now - timestamp < data_stale_seconds

    Note : clock injectable via `clock` callable pour tests déterministes.
    """
    name: str = "precheck"

    def __init__(self,
                 nan_ratio_threshold: float = 0.05,
                 clock: Optional[Callable[[], datetime]] = None):
        self.nan_ratio_threshold = nan_ratio_threshold
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def evaluate(self, state: GateState) -> GateResult:
        cfg = CONFIG

        # Check features count
        n_features = len(state.features_row)
        if n_features < cfg.data.min_features_count:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"features count {n_features} < {cfg.data.min_features_count}",
                metadata={"n_features": n_features},
            )

        # Check NaN ratio (accepte numpy scalars via __float__)
        def _is_nan(x):
            if x is None:
                return True
            try:
                return not math.isfinite(float(x))
            except (TypeError, ValueError):
                return True

        n_nan = sum(1 for v in state.features_row.values() if _is_nan(v))
        nan_ratio = n_nan / max(n_features, 1)
        if nan_ratio > self.nan_ratio_threshold:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"NaN ratio {nan_ratio:.1%} > {self.nan_ratio_threshold:.1%}",
                metadata={"nan_ratio": nan_ratio, "n_nan": n_nan},
            )

        # Check VIX finite
        if not math.isfinite(state.vix_level):
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"vix_level not finite: {state.vix_level}",
            )

        # Check data stale (clock injectable pour tests)
        now = self._clock()
        age_sec = (now - state.timestamp).total_seconds()
        if age_sec > cfg.kill_switch.data_stale_seconds:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"data stale: bar age {age_sec:.0f}s > {cfg.kill_switch.data_stale_seconds}s",
                metadata={"age_sec": round(age_sec, 1)},
            )

        return GateResult(
            passed=True, gate_name=self.name,
            reason="OK",
            metadata={"n_features": n_features, "nan_ratio": round(nan_ratio, 4),
                      "age_sec": round(age_sec, 1)},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MACRO GATE (session + VIX + ECO)
# ═══════════════════════════════════════════════════════════════════════════════

class MacroGate:
    """Gate macro : session trading (24h ou RTH only) + VIX + calendrier ECO.

    Mode "24h" (Jackson 17/04/2026) : autorise Asia + London + RTH + US AH,
    bloque halt CME (17:00-18:00 ET) + weekend (Ven 17:00 ET → Dim 18:00 ET).

    Mode "rth_only" (legacy V1) : RTH 09:30-15:45 ET (flatten -15min).
    """
    name: str = "macro"

    def evaluate(self, state: GateState) -> GateResult:
        cfg = CONFIG
        sess = cfg.session

        # Convertir timestamp UTC → ET
        ts_et = state.timestamp.astimezone(_ET)
        weekday = ts_et.weekday()                  # Monday=0, Sunday=6
        minute_et = ts_et.hour * 60 + ts_et.minute

        # Check weekend CME (Vendredi 17:00 ET → Dimanche 18:00 ET)
        if sess.is_weekend_closed(weekday, minute_et):
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"weekend CME closed ({ts_et.strftime('%a %H:%M')} ET)",
                metadata={"weekday": weekday, "minute_et": minute_et},
            )

        # Check mode : 24h ou RTH only ?
        if sess.mode == "rth_only":
            # Legacy RTH check
            if minute_et < sess.start_minute:
                return GateResult(
                    passed=False, gate_name=self.name,
                    reason=f"pre-RTH: {ts_et.strftime('%H:%M')} ET",
                )
            if minute_et >= sess.trade_end_minute:
                return GateResult(
                    passed=False, gate_name=self.name,
                    reason=f"post-RTH flatten window: {ts_et.strftime('%H:%M')} ET "
                           f"(flatten at {sess.trade_end_minute//60:02d}:"
                           f"{sess.trade_end_minute%60:02d})",
                )
        else:
            # Mode 24h : bloquer uniquement halt CME (17:00-18:00 ET)
            if sess.is_halt(minute_et):
                return GateResult(
                    passed=False, gate_name=self.name,
                    reason=f"daily halt CME ({ts_et.strftime('%H:%M')} ET)",
                    metadata={"session": "halt"},
                )
            # Bloquer aussi flatten window RTH (dernieres 15 min RTH)
            if sess.is_rth(minute_et) and minute_et >= sess.trade_end_minute:
                return GateResult(
                    passed=False, gate_name=self.name,
                    reason=f"RTH flatten window: {ts_et.strftime('%H:%M')} ET",
                    metadata={"session": "rth_flatten"},
                )

        # Check VIX
        if state.vix_level >= cfg.kill_switch.vix_kill_threshold:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"VIX {state.vix_level:.1f} >= {cfg.kill_switch.vix_kill_threshold}",
                metadata={"vix_level": state.vix_level},
            )

        # Check fenêtre ECO
        in_eco, eco_name = is_in_eco_window(state.timestamp)
        if in_eco:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"ECO window: {eco_name}",
                metadata={"eco_event": eco_name},
            )

        # Session name pour journal/audit
        session = sess.session_name(minute_et)
        return GateResult(
            passed=True, gate_name=self.name,
            reason="OK",
            metadata={"session": session, "minute_et": minute_et,
                      "vix_level": state.vix_level},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RISK GATE (7 checks combinés)
# ═══════════════════════════════════════════════════════════════════════════════

class RiskGate:
    """Gate risk : position, trades/day, DD, consec losses, circuit breaker,
    cooldown post-trade, level protection.

    Retourne `metadata["failed_check"]` pour debug facile.
    """
    name: str = "risk"

    def evaluate(self, state: GateState) -> GateResult:
        cfg = CONFIG
        ps = state.position_state
        symbol = state.symbol
        now = state.timestamp

        # Check 1 : position ouverte SUR CE SYMBOLE ?
        if ps.has_open_on(symbol):
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"position already open on {symbol.value}",
                metadata={"failed_check": "position"},
            )

        # Check 2 : trades/day sur ce symbole
        trades_today = ps.trades_today(symbol)
        if trades_today >= cfg.risk.max_trades_per_day:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"trades_today {trades_today} >= {cfg.risk.max_trades_per_day}",
                metadata={"failed_check": "trades_today", "trades_today": trades_today},
            )

        # Check 3 : daily PnL (kill switch $500)
        if ps.daily_pnl_usd <= -cfg.kill_switch.daily_loss_usd:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"daily_pnl {ps.daily_pnl_usd:+.0f} <= "
                       f"-{cfg.kill_switch.daily_loss_usd}",
                metadata={"failed_check": "daily_pnl",
                          "daily_pnl_usd": ps.daily_pnl_usd},
            )

        # Check 4 : consecutive losses
        max_consec = cfg.risk.get_max_consec_losses(symbol)
        if ps.consecutive_losses >= max_consec:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"consec losses {ps.consecutive_losses} >= {max_consec} "
                       f"({symbol.value})",
                metadata={"failed_check": "consec_losses",
                          "consecutive_losses": ps.consecutive_losses},
            )

        # Check 5 : circuit breaker actif
        if ps.circuit_breaker_until is not None and now < ps.circuit_breaker_until:
            remaining = (ps.circuit_breaker_until - now).total_seconds() / 60
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"circuit breaker active ({remaining:.1f} min remaining)",
                metadata={"failed_check": "circuit_breaker",
                          "remaining_minutes": round(remaining, 1)},
            )

        # Check 6 : cooldown post-trade
        if ps.last_trade_close_ts is not None and ps.last_trade_outcome is not None:
            age_sec = (now - ps.last_trade_close_ts).total_seconds()
            if ps.last_trade_outcome == "WIN":
                required_sec = cfg.cooldown.cooldown_after_win_sec
                lock_sec = cfg.cooldown.post_close_lock_win_sec
            else:
                required_sec = cfg.cooldown.cooldown_after_loss_sec
                lock_sec = cfg.cooldown.post_close_lock_loss_sec
            total_lock = required_sec + lock_sec
            if age_sec < total_lock:
                return GateResult(
                    passed=False, gate_name=self.name,
                    reason=f"cooldown after {ps.last_trade_outcome}: "
                           f"{age_sec:.0f}s < {total_lock}s",
                    metadata={"failed_check": "cooldown",
                              "age_sec": round(age_sec, 1),
                              "required_sec": total_lock,
                              "outcome": ps.last_trade_outcome},
                )

        # Check 7 : level protection
        if ps.level_protected_ranges:
            price = ps.current_price
            for lv in ps.level_protected_ranges:
                if lv.is_expired(now):
                    continue  # déjà expiré, skip
                if lv.contains(price):
                    return GateResult(
                        passed=False, gate_name=self.name,
                        reason=f"price {price} in protected range "
                               f"[{lv.price_low}, {lv.price_high}] "
                               f"({lv.outcome}, expires {lv.expires_at.isoformat()})",
                        metadata={"failed_check": "level_protection",
                                  "range": [lv.price_low, lv.price_high],
                                  "outcome": lv.outcome},
                    )

        # Tous les checks OK
        return GateResult(
            passed=True, gate_name=self.name, reason="OK",
            metadata={"trades_today": trades_today,
                      "daily_pnl_usd": ps.daily_pnl_usd},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MENTHORQ GATE (distance minimum niveau)
# ═══════════════════════════════════════════════════════════════════════════════

class MenthorQGate:
    """Gate MenthorQ : min |dist| sur niveaux options <= max_dist configuré."""
    name: str = "menthorq"

    # Features de distance MenthorQ utilisées (en ticks)
    DIST_COLS = (
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte",
        "dist_gex_nearest_up", "dist_gex_nearest_dn",
    )

    def evaluate(self, state: GateState) -> GateResult:
        cfg = CONFIG
        max_dist = cfg.menthorq_gate.get_max_dist(state.symbol)

        # Trouver la distance min absolue parmi les niveaux disponibles
        # (accepte numpy scalars via __float__, sinon skip silencieusement)
        min_abs_dist = float("inf")
        nearest_col: Optional[str] = None
        for col in self.DIST_COLS:
            raw = state.features_row.get(col)
            if raw is None:
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(v):
                continue
            if abs(v) < min_abs_dist:
                min_abs_dist = abs(v)
                nearest_col = col

        if nearest_col is None:
            return GateResult(
                passed=False, gate_name=self.name,
                reason="no MenthorQ distance features available",
            )

        if min_abs_dist > max_dist:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"min_dist {min_abs_dist:.1f}t > {max_dist}t ({state.symbol.value})",
                metadata={"nearest_level": nearest_col,
                          "nearest_distance_ticks": round(min_abs_dist, 1)},
            )

        return GateResult(
            passed=True, gate_name=self.name, reason="OK",
            metadata={"nearest_level": nearest_col,
                      "nearest_distance_ticks": round(min_abs_dist, 1)},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ML GATE (seuils primary + meta, fail-closed si non calibré)
# ═══════════════════════════════════════════════════════════════════════════════

class MLGate:
    """Gate ML : p_primary + p_meta vs seuils. Fail-closed si require_calibration."""
    name: str = "ml"

    def evaluate(self, state: GateState) -> GateResult:
        cfg = CONFIG.ml_gate

        # Fail-closed INCONDITIONNEL : seuils tous à 0 = non calibré = refus.
        # Check sorti du `if require_calibration:` pour éviter que
        # require_calibration=False + seuils=0.0 laisse passer tous les trades.
        all_zero = (cfg.primary_threshold_buy == 0.0
                    and cfg.primary_threshold_sell == 0.0
                    and cfg.meta_threshold == 0.0)
        if all_zero:
            return GateResult(
                passed=False, gate_name=self.name,
                reason="ML not calibrated (all thresholds = 0.0). "
                       "Run train_lightgbm.py + set CONFIG.ml_gate thresholds.",
                metadata={"failed_check": "not_calibrated"},
            )

        p_buy = float(state.ml_scores.get("p_primary_buy", 0.0))
        p_sell = float(state.ml_scores.get("p_primary_sell", 0.0))
        p_meta = state.ml_scores.get("p_meta")
        p_meta_val = float(p_meta) if p_meta is not None else None

        # P0.1 VOIE C (17/04) : mode disable_meta Phase 1.
        # Utilise primary_only_threshold (plus strict) et ignore meta.
        # Features im_* manquantes en live → meta toujours None → fix ce soir
        # via threshold primary renforce (compense absence filtre meta).
        if cfg.disable_meta_phase1:
            thr_buy = cfg.primary_only_threshold_buy
            thr_sell = cfg.primary_only_threshold_sell
        else:
            thr_buy = cfg.primary_threshold_buy
            thr_sell = cfg.primary_threshold_sell

        # Check primary seuils
        buy_ok = p_buy >= thr_buy
        sell_ok = p_sell >= thr_sell

        if not buy_ok and not sell_ok:
            return GateResult(
                passed=False, gate_name=self.name,
                reason=f"p_buy {p_buy:.3f} < {thr_buy} AND "
                       f"p_sell {p_sell:.3f} < {thr_sell}",
                metadata={"p_buy": round(p_buy, 4), "p_sell": round(p_sell, 4),
                          "mode": "primary_only" if cfg.disable_meta_phase1 else "primary+meta"},
            )

        # Check conflit
        if buy_ok and sell_ok:
            # Prendre le plus fort
            if p_buy >= p_sell:
                direction = Direction.BUY
            else:
                direction = Direction.SELL
        elif buy_ok:
            direction = Direction.BUY
        else:
            direction = Direction.SELL

        # P0.1 VOIE C : skip meta checks si disable_meta_phase1 (primary-only mode)
        if not cfg.disable_meta_phase1:
            # Check meta si disponible
            if p_meta_val is not None and p_meta_val < cfg.meta_threshold:
                return GateResult(
                    passed=False, gate_name=self.name,
                    reason=f"p_meta {p_meta_val:.3f} < {cfg.meta_threshold}",
                    metadata={"p_buy": round(p_buy, 4), "p_sell": round(p_sell, 4),
                              "p_meta": round(p_meta_val, 4)},
                )

            # Check combined
            if p_meta_val is not None:
                p_primary = p_buy if direction == Direction.BUY else p_sell
                p_final = p_primary * p_meta_val
                if p_final < cfg.combined_threshold:
                    return GateResult(
                        passed=False, gate_name=self.name,
                        reason=f"p_final {p_final:.3f} < {cfg.combined_threshold}",
                        metadata={"p_buy": round(p_buy, 4), "p_sell": round(p_sell, 4),
                                  "p_meta": round(p_meta_val, 4),
                                  "p_final": round(p_final, 4)},
                    )

        return GateResult(
            passed=True, gate_name=self.name, reason="OK",
            direction_allowed=direction,
            metadata={"p_buy": round(p_buy, 4), "p_sell": round(p_sell, 4),
                      "p_meta": round(p_meta_val, 4) if p_meta_val is not None else None,
                      "direction": direction.value},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# GATE LAYER ORCHESTRATEUR
# ═══════════════════════════════════════════════════════════════════════════════

class GateLayer:
    """Orchestrateur des 5 gates en short-circuit.

    Ordre : Precheck → Macro → Risk → MenthorQ → ML
    (agent correction : Macro avant Risk car élimine hors-session vite)

    Mode full_evaluation=True : toutes gates évaluées (debug/analytics).
    """

    def __init__(self,
                 enabled_symbols: Optional[tuple[Symbol, ...]] = None,
                 gates: Optional[tuple[Gate, ...]] = None):
        self.enabled_symbols = enabled_symbols or CONFIG.enabled_symbols
        # Ordre optimal : Precheck (tri input) → Macro (élimine hors-session)
        # → Risk (cooldowns) → MenthorQ (zone) → ML (direction finale)
        self.gates: tuple[Gate, ...] = gates or (
            PrecheckGate(),
            MacroGate(),
            RiskGate(),
            MenthorQGate(),
            MLGate(),
        )

    def evaluate(self, state: GateState,
                 full_evaluation: bool = False) -> GateLayerResult:
        """Evalue les gates dans l'ordre. Short-circuit par défaut."""
        if state.symbol not in self.enabled_symbols:
            return GateLayerResult(
                decision=Direction.HOLD,
                all_passed=False,
                rejected_by="config",
                reason=f"symbol {state.symbol.value} not in enabled_symbols",
            )

        t0 = time.perf_counter()
        results: list[GateResult] = []
        rejected_by: Optional[str] = None
        rejection_reason: str = ""

        for gate in self.gates:
            result = gate.evaluate(state)
            results.append(result)
            if not result.passed:
                if rejected_by is None:
                    rejected_by = gate.name
                    rejection_reason = result.reason
                if not full_evaluation:
                    break

        elapsed_ms = (time.perf_counter() - t0) * 1000
        all_passed = all(r.passed for r in results)

        if all_passed:
            # Décision finale = direction du MLGate (dernière gate)
            ml_result = next((r for r in results if r.gate_name == "ml"), None)
            decision = ml_result.direction_allowed if ml_result else Direction.HOLD
        else:
            decision = Direction.HOLD

        # V2 log : PASS ou BLOCK par gate (routing selon rejected_by)
        if _v2log:
            sym_val = state.symbol.value if hasattr(state, 'symbol') and hasattr(state.symbol, 'value') else ""
            if all_passed:
                _v2log.emit("GATE_PASSED_ALL", sym=sym_val)
            elif rejected_by == "session":
                phase = str(getattr(state, "session_phase", "unknown"))
                _v2log.emit("GATE_SESSION_BLOCK", phase=phase)
            elif rejected_by == "risk":
                _v2log.emit("GATE_RISK_BLOCK", reason=rejection_reason[:100])
            elif rejected_by:
                _v2log.emit("GATE_RISK_BLOCK", reason=f"{rejected_by}:{rejection_reason[:80]}")

        return GateLayerResult(
            decision=decision,
            all_passed=all_passed,
            rejected_by=rejected_by,
            reason=rejection_reason if rejected_by else "all gates passed",
            gate_results=tuple(results),
            evaluation_time_ms=elapsed_ms,
        )
