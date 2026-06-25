"""Bot 4 v2 shadow_logger — capture EVERY scenario fire + outcome 30 bars.

Module CENTRAL Phase P1 : sans cet outil, aucune calibration empirique possible
en P6. Le verdict ml-trainer 25/06 etait : "Plan PHASE A-D refus calibrer
avec les donnees actuelles. Shadow log 30j obligatoire AVANT meta-labeling."

Pattern :
- Sur chaque bar, scenarios actifs evaluent leur trigger.
- Si scenario fire -> `logger.log_fire(ShadowFire)` -> append JSONL + ajout
  buffer pending (waiting outcome).
- Sur chaque bar suivante, `logger.update_outcomes(bar)` evalue les pending :
  TP hit ? SL hit ? Timeout horizon ?
- Quand outcome decide (TP/SL/TIMEOUT) -> append outcome JSONL + remove pending.

Garde-fous :
- Aucun trade execute. Zero impact prod. Pure observation.
- Persistance fail-soft : si disk full -> emit warning + drop event (anti crash).
- Pas de pickle (JSONL append-only) -> auditable + diffable + grep-able.

Spec section 4 P1 specification :
- Output `LOGS/shadow_scenarios/shadow_YYYYMMDD_{symbol}.jsonl` append-only.
- Outcome capture worker async : pas implemente ici (caller `update_outcomes`).
- Tests integration : >=10 tests pytest + dry-run 1j >10 events.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)

# Outcome status enum (string pour serialization JSONL)
OutcomeStatus = Literal["PENDING", "TP_HIT", "SL_HIT", "TIMEOUT", "INVALIDATED"]


@dataclass(frozen=True)
class ShadowFire:
    """Event scenario fire + outcome eventuel.

    Immutable. Caller cree un new ShadowFire complet (avec outcome ou non).
    """

    # ============================================================
    # IDENTITE
    # ============================================================
    signal_id: str  # UUID unique
    ts_fire: str  # ISO 8601 UTC fire bar timestamp
    symbol: str  # NQ / ES / MGC
    scenario_name: str
    direction: Literal["LONG", "SHORT"]

    # ============================================================
    # CONTEXTE FIRE (immutable)
    # ============================================================
    heuristic_score: int  # 0-100
    primary: bool  # True si top scenario du bar (vs secondaires)
    regime: str  # CALM_RANGE / VOLATILE_RANGE / TREND_UP / TREND_DOWN / PANIC
    session_id: int  # 0=Asia, 1=London, 2=US, 3=US_AH
    entry_price: float
    target_1: float
    target_2: float | None
    stop_loss: float
    r_r_ratio: float  # |target_1 - entry| / |entry - stop_loss|

    # ============================================================
    # OUTCOME (rempli a t+horizon_bars par update_outcome)
    # ============================================================
    outcome_status: OutcomeStatus = "PENDING"
    outcome_ts: str | None = None  # ISO 8601 quand outcome decide
    pnl_ticks_h: float | None = None  # PnL final (positif=win)
    mfe_ticks: float | None = None  # Max Favorable Excursion
    mae_ticks: float | None = None  # Max Adverse Excursion
    tp1_hit: bool | None = None
    tp2_hit: bool | None = None
    sl_hit: bool | None = None
    duration_bars: int | None = None

    # ============================================================
    # META
    # ============================================================
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize en dict pour JSONL."""
        return {
            "signal_id": self.signal_id,
            "ts_fire": self.ts_fire,
            "symbol": self.symbol,
            "scenario_name": self.scenario_name,
            "direction": self.direction,
            "heuristic_score": self.heuristic_score,
            "primary": self.primary,
            "regime": self.regime,
            "session_id": self.session_id,
            "entry_price": self.entry_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "stop_loss": self.stop_loss,
            "r_r_ratio": self.r_r_ratio,
            "outcome_status": self.outcome_status,
            "outcome_ts": self.outcome_ts,
            "pnl_ticks_h": self.pnl_ticks_h,
            "mfe_ticks": self.mfe_ticks,
            "mae_ticks": self.mae_ticks,
            "tp1_hit": self.tp1_hit,
            "tp2_hit": self.tp2_hit,
            "sl_hit": self.sl_hit,
            "duration_bars": self.duration_bars,
            "extra": self.extra,
        }


@dataclass
class _PendingFire:
    """Etat interne pour un fire en attente d'outcome."""

    fire: ShadowFire
    bars_seen: int = 0
    mfe_ticks: float = 0.0
    mae_ticks: float = 0.0

    def update_excursion(self, bar_high: float, bar_low: float, tick_size: float) -> None:
        """Update MFE/MAE selon bar high/low."""
        entry = self.fire.entry_price
        if self.fire.direction == "LONG":
            fav = (bar_high - entry) / tick_size
            adv = (bar_low - entry) / tick_size  # negative
        else:  # SHORT
            fav = (entry - bar_low) / tick_size
            adv = (entry - bar_high) / tick_size  # negative
        if fav > self.mfe_ticks:
            self.mfe_ticks = fav
        if adv < self.mae_ticks:
            self.mae_ticks = adv


class ShadowLogger:
    """Logger JSONL append-only par jour + tracking pending fires.

    Thread-safety : NON. Caller doit serialiser les appels (lock externe si
    multi-thread). Bot 4 v2 main loop = single thread donc OK.

    Usage :
        cfg = get_settings()
        sl = ShadowLogger(cfg.shadow_logs_dir, horizon_bars=30)
        # Sur chaque bar :
        sl.update_outcomes(bar)  # check pending fires
        # Si scenario fire :
        fire = ShadowFire(signal_id=..., ts_fire=..., ...)
        sl.log_fire(fire)
    """

    # Tick sizes par symbole (source unique CORE/constants.py — duplique ici
    # pour découplage P1, sera fork P2)
    _TICK_SIZE = {
        "NQ": 0.25,
        "ES": 0.25,
        "MGC": 0.10,
    }

    def __init__(
        self,
        output_dir: Path,
        horizon_bars: int = 30,
        enabled: bool = True,
    ):
        """Init logger.

        Args:
            output_dir : repertoire JSONL append-only
            horizon_bars : nb bars max avant outcome=TIMEOUT
            enabled : si False, log_fire et update_outcomes sont no-op
        """
        self._output_dir = output_dir
        self._horizon_bars = horizon_bars
        self._enabled = enabled
        self._pending: dict[str, _PendingFire] = {}
        if self._enabled:
            self._output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def n_pending(self) -> int:
        """Nombre de fires en attente d'outcome."""
        return len(self._pending)

    def log_fire(self, fire: ShadowFire) -> bool:
        """Persiste un fire (status=PENDING) et l'ajoute au buffer outcomes.

        Args:
            fire : ShadowFire complet avec outcome_status="PENDING"

        Returns:
            True si persiste OK, False si erreur disk ou disabled
        """
        if not self._enabled:
            return False

        if fire.signal_id in self._pending:
            _LOG.warning(
                "log_fire: signal_id=%s deja en pending (ignore duplicate)",
                fire.signal_id,
            )
            return False

        path = self._daily_path(fire.symbol, fire.ts_fire)
        if not self._append_jsonl(path, fire.to_dict()):
            return False

        self._pending[fire.signal_id] = _PendingFire(fire=fire)
        return True

    def update_outcomes(
        self,
        symbol: str,
        bar_ts: str,
        bar_high: float,
        bar_low: float,
        bar_close: float,
    ) -> list[ShadowFire]:
        """Evalue tous les pending fires du symbole sur cette bar.

        Pour chaque pending :
        - Update MFE/MAE
        - Check TP / SL hit (wick-based)
        - Check timeout horizon_bars
        - Si decide -> append outcome JSONL + remove pending

        Args:
            symbol : NQ / ES / MGC
            bar_ts : ts ISO 8601 UTC
            bar_high, bar_low, bar_close : OHLC bar courante

        Returns:
            Liste ShadowFire decidees cette bar (outcome_status != PENDING)
        """
        if not self._enabled:
            return []

        # R2 review : fail-loud si symbole inconnu (anti silent fallback).
        # P2 fork : remplacer par CORE.constants.get_tick_size() (backlog tick-size-policy).
        tick_size = self._TICK_SIZE.get(symbol.upper())
        if tick_size is None:
            _LOG.warning(
                "shadow_logger: symbole '%s' inconnu, fallback 0.25. "
                "Symboles supportes : NQ ES MGC. Backlog P2 : fork CORE.constants.",
                symbol,
            )
            tick_size = 0.25
        decided: list[ShadowFire] = []

        # Iterate sur copie keys car on peut pop pendant iteration
        for signal_id in list(self._pending.keys()):
            pending = self._pending[signal_id]
            if pending.fire.symbol != symbol:
                continue

            pending.bars_seen += 1
            pending.update_excursion(bar_high, bar_low, tick_size)

            outcome = self._evaluate_outcome(
                pending, bar_high, bar_low, bar_close, bar_ts, tick_size
            )
            if outcome is not None:
                self._append_jsonl(
                    self._daily_path(symbol, outcome.ts_fire),
                    outcome.to_dict(),
                )
                decided.append(outcome)
                del self._pending[signal_id]

        return decided

    def _evaluate_outcome(
        self,
        pending: _PendingFire,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        bar_ts: str,
        tick_size: float,
    ) -> ShadowFire | None:
        """Decide outcome pour un pending. Returns ShadowFire decidee ou None."""
        fire = pending.fire

        # Check TP / SL hit (wick-based)
        if fire.direction == "LONG":
            tp1_hit = bar_high >= fire.target_1
            sl_hit = bar_low <= fire.stop_loss
        else:  # SHORT
            tp1_hit = bar_low <= fire.target_1
            sl_hit = bar_high >= fire.stop_loss

        # SL priorite si meme bar (conservateur, anti optimisme retest)
        if sl_hit:
            return self._build_outcome(
                pending, bar_ts, status="SL_HIT",
                exit_price=fire.stop_loss, tp1=False, sl=True, tick_size=tick_size,
            )
        if tp1_hit:
            return self._build_outcome(
                pending, bar_ts, status="TP_HIT",
                exit_price=fire.target_1, tp1=True, sl=False, tick_size=tick_size,
            )

        # Timeout
        if pending.bars_seen >= self._horizon_bars:
            return self._build_outcome(
                pending, bar_ts, status="TIMEOUT",
                exit_price=bar_close, tp1=False, sl=False, tick_size=tick_size,
            )

        return None  # toujours en attente

    @staticmethod
    def _build_outcome(
        pending: _PendingFire,
        bar_ts: str,
        *,
        status: OutcomeStatus,
        exit_price: float,
        tp1: bool,
        sl: bool,
        tick_size: float,
    ) -> ShadowFire:
        """Construit ShadowFire decidee a partir d'un pending."""
        fire = pending.fire
        if fire.direction == "LONG":
            pnl_ticks = (exit_price - fire.entry_price) / tick_size
        else:
            pnl_ticks = (fire.entry_price - exit_price) / tick_size

        # Frozen dataclass : on cree nouveau via __init__
        return ShadowFire(
            signal_id=fire.signal_id,
            ts_fire=fire.ts_fire,
            symbol=fire.symbol,
            scenario_name=fire.scenario_name,
            direction=fire.direction,
            heuristic_score=fire.heuristic_score,
            primary=fire.primary,
            regime=fire.regime,
            session_id=fire.session_id,
            entry_price=fire.entry_price,
            target_1=fire.target_1,
            target_2=fire.target_2,
            stop_loss=fire.stop_loss,
            r_r_ratio=fire.r_r_ratio,
            outcome_status=status,
            outcome_ts=bar_ts,
            pnl_ticks_h=round(pnl_ticks, 2),
            mfe_ticks=round(pending.mfe_ticks, 2),
            mae_ticks=round(pending.mae_ticks, 2),
            tp1_hit=tp1,
            tp2_hit=None,  # target_2 logic Phase P3+
            sl_hit=sl,
            duration_bars=pending.bars_seen,
            extra=fire.extra,
        )

    def _daily_path(self, symbol: str, ts_iso: str) -> Path:
        """Path JSONL append-only daily pour (symbol, date).

        R1 review : fail-loud si ts_iso invalide. Warning + fallback now UTC,
        mais JAMAIS silent (anti-pattern critical-tasks-review.md). Le fallback
        est tracable pour audit P6 si pattern recurrent (pollution daily files).
        """
        try:
            dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError) as exc:
            _LOG.warning(
                "shadow_logger: ts_fire invalide '%s' (exc=%s). "
                "Fallback datetime.now UTC -> fire dans fichier jour courant. "
                "Risque pollution daily files si pattern recurrent (P6 calibration).",
                ts_iso, exc,
            )
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        date_str = dt.strftime("%Y%m%d")
        return self._output_dir / f"shadow_{date_str}_{symbol.upper()}.jsonl"

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> bool:
        """Append record JSONL fail-soft.

        Returns True si append OK, False si OSError (disk full, perms, etc.).
        """
        try:
            # JSONL standard : separateur "\n" Unix-style cross-platform (PAS
            # os.linesep qui produit \r\n Windows et casse strip().split('\n')).
            line = json.dumps(record, ensure_ascii=False, default=str)
            with path.open("a", encoding="utf-8", newline="") as f:
                f.write(line + "\n")
            return True
        except OSError as exc:
            _LOG.warning(
                "shadow_logger: append fail path=%s exc=%s (event dropped)",
                path, exc,
            )
            return False
        except (TypeError, ValueError) as exc:
            _LOG.warning(
                "shadow_logger: json encode fail path=%s exc=%s (event dropped)",
                path, exc,
            )
            return False
