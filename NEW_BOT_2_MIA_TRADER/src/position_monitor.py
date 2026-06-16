"""M3.5 PositionMonitor — Trailing TR40 SL + MFE-TP drawback.

Portage du trailing legacy Bot 1 `mia_paper_trader.py:2776-2920` apres audit
market-analyst (verdict GO-AVEC-REWRITE).

2 systemes complementaires (orthogonal pas cascade) :

1. **TR40 SL** (verrouille gains par paliers, NQ-only par defaut) :
   - Armement quand MFE >= 40% du SL initial
   - Give-back 20% du SL initial
   - LONG : new_sl = entry + (MFE - giveback) × tick, jamais descend
   - SHORT : new_sl = entry - (MFE - giveback) × tick, jamais monte
   - Backtest 4 mois NQ : PF 0.99 → 1.32, walk-forward 3/3, CI95 [1.15, 1.51]
   - **Flag OFF par defaut** (LIVE bloque sans cancel+replace DTC — TODO Phase 8)

2. **MFE-TP drawback** (sortie sur retracement depuis peak, all symbols) :
   - Seuil par symbole : ES=30, NQ=50, MGC=40 (volatilite relative)
   - Drawback closer : 12 ticks (fix 20/05, etait 20 — backtest 128 trades +$315)
   - Si MFE >= seuil ET (MFE - excursion_current) >= 12t → close_now
   - Backtest 128 trades : +$2250 (db=12) vs +$1935 (db=20)
   - **Flag ON par defaut** (close direct, pas de DTC cancel+replace requis)

Magic numbers du legacy (0.40, 0.20, 12, 30, 50) → Pydantic TrailingConfig.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

try:
    from CORE.constants import get_tick_size as _get_tick_size  # type: ignore
except ImportError:
    def _get_tick_size(symbol: str) -> float:
        return {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}.get(symbol, 0.25)


# =============================================================================
# Pydantic config
# =============================================================================


class TrailingConfig(BaseModel):
    """Configuration trailing TR40 + MFE-TP. frozen v2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # === TR40 SL ===
    tr40_enabled: bool = Field(
        default=False,
        description="OFF par defaut LIVE (bloque cancel+replace DTC TODO Phase 8). "
        "Activable paper avec True.",
    )
    tr40_arming_pct: float = Field(
        default=0.40, gt=0, lt=1,
        description="MFE doit atteindre tr40_arming_pct × SL_init pour armer",
    )
    tr40_giveback_pct: float = Field(
        default=0.20, ge=0, lt=1,
        description="Give-back appliquee a la nouvelle position SL",
    )
    tr40_symbols: List[str] = Field(
        default_factory=lambda: ["NQ"],
        description="Symbols autorises TR40 (legacy NQ-only, ES PF 0.88 marginal)",
    )

    # === MFE-TP drawback ===
    mfe_tp_enabled: bool = Field(
        default=True,
        description="ON par defaut paper (close direct sans cancel broker)",
    )
    mfe_tp_threshold_ticks: Dict[str, int] = Field(
        default_factory=lambda: {"ES": 30, "NQ": 50, "MGC": 40},
        description="MFE peak requis pour armer trailing TP par symbol",
    )
    mfe_tp_drawback_ticks: int = Field(
        default=12, gt=0,
        description="Retracement depuis peak MFE pour declencher close (fix 20/05)",
    )

    # === PALIER TRAILING (16/06/2026 Jackson souverain) ===
    # Trailing par paliers discrets style swing pro. A chaque palier MFE
    # atteint, le "SL logique" remonte au niveau de profit verrouille.
    # Quand l'excursion courante repasse SOUS le palier le plus haut atteint
    # -> close direct au prix courant (pas de DTC cancel+replace requis).
    # Resout le probleme observe 16/06 : trade ES Bot 4 monte a +16t (MFE peak)
    # puis SL hit -14t car threshold MFE-TP=30t jamais atteint. Avec paliers,
    # MFE 10t -> SL logique=BE, retour BE = close 0 perte (au lieu de -$175).
    palier_trailing_enabled: bool = Field(
        default=True,
        description="ON par defaut paper : close direct au retour sous palier",
    )
    palier_trailing_by_symbol: Dict[str, List[Tuple[int, int]]] = Field(
        default_factory=lambda: {
            # (mfe_threshold_ticks, sl_locked_profit_ticks)
            # ES E-mini : conservateur intelligent
            "ES": [(10, 0), (20, 5), (30, 15), (45, 25), (60, 40)],
            # NQ : volatilite plus haute -> paliers plus larges
            "NQ": [(20, 0), (40, 10), (60, 25), (80, 45), (100, 65)],
            # MGC : intermediaire
            "MGC": [(15, 0), (30, 10), (45, 25), (60, 40)],
        },
        description="Paliers (mfe_thr, sl_lock) tries ascendant. SL_lock=0=BE",
    )

    @classmethod
    def paper_mode(cls) -> "TrailingConfig":
        """Preset paper Sim2/Sim4 : MFE-TP ON, TR40 OFF, PALIER ON (16/06)."""
        return cls(
            tr40_enabled=False,
            mfe_tp_enabled=True,
            palier_trailing_enabled=True,
        )

    @classmethod
    def live_mode_when_dtc_ready(cls) -> "TrailingConfig":
        """Preset LIVE futur : TR40 + MFE-TP ON (requiert DTC cancel+replace)."""
        return cls(
            tr40_enabled=True,
            mfe_tp_enabled=True,
        )


# =============================================================================
# State (per-position)
# =============================================================================


@dataclass
class PositionState:
    """Etat runtime d'une position ouverte (per-symbol).

    Persiste entre polls (10s) via M5 Execution. Field tracking :
    - mfe / mae : Max Favorable / Adverse Excursion (ticks signe)
    - sl_trailed / sl_trail_count : TR40 history
    - trailing_tp_armed : MFE-TP statut
    """

    signal_id: str
    symbol: Literal["NQ", "ES", "MGC"]
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    entry_ts_ns: int
    n_micros: int
    sl_price: float
    sl_ticks_initial: float  # Snapshot au start (jamais ecrase)
    tp1_price: float
    tp1_ticks: float

    # Runtime (initialise par PositionMonitor)
    current_price: Optional[float] = None
    mfe: float = 0.0
    mae: float = 0.0
    bars_held: int = 0
    last_bar_ts_ns: Optional[int] = None

    # TR40
    # Fix R1 review : flag `tr40_armed` separe de `sl_trailed` pour idempotence
    # event ARMED (emis 1x au franchissement seuil, meme si SL pas update).
    tr40_armed: bool = False
    sl_trailed: bool = False
    sl_trail_count: int = 0

    # MFE-TP
    trailing_tp_armed: bool = False

    # Palier trailing (16/06 Jackson souverain).
    # palier_atteint_idx = index du palier le plus haut atteint (-1 = aucun).
    # Incrementee a chaque fois que MFE depasse un nouveau seuil palier.
    # Permet d'emit event ARMED 1x par palier (idempotent cross-restart si state
    # serialise).
    palier_atteint_idx: int = -1

    # Fix C1 review J10 : tracking OCO ClientOrderIDs pour flatten_position_safely.
    # Sans ces refs, flatten ne peut pas annuler TP/SL explicitement (etape 1+2)
    # et doit reposer uniquement sur cancel-all-working (etape 6.5) + Type 209/210.
    # Populer dans main.py:_process_symbol apres send_bracket().
    tp_cid: Optional[str] = None
    sl_cid: Optional[str] = None


# =============================================================================
# Update result
# =============================================================================


@dataclass
class PositionUpdate:
    """Resultat d'un update poll : nouveau SL si TR40 trigger, close si MFE-TP."""

    sl_changed: bool = False
    new_sl_price: Optional[float] = None
    new_sl_reason: Optional[str] = None  # "TR40_ARMED" ou "TR40_UPDATED"

    close_now: bool = False
    close_reason: Optional[str] = None  # "TRAILING_TP"
    close_price: Optional[float] = None
    close_pnl_ticks: Optional[float] = None

    events: List[Dict] = None  # type: ignore  # liste codes log emit (dict pour Telemetry)

    def __post_init__(self):
        if self.events is None:
            self.events = []


# =============================================================================
# PositionMonitor
# =============================================================================


class PositionMonitor:
    """Surveille une position ouverte : update MFE/MAE, TR40 trail, MFE-TP close.

    Usage :
        monitor = PositionMonitor(config=TrailingConfig.paper_mode())
        # Init au fill :
        state = PositionState(signal_id=..., symbol="NQ", direction="LONG", entry_price=21450.0, ...)
        # Polls :
        update = monitor.update(state, current_price=21465.0, bar_ts_ns=...)
        if update.sl_changed:
            # M5 Execution : cancel+replace SL bracket
            state.sl_price = update.new_sl_price
        if update.close_now:
            # M5 Execution : market close + log
            close_trade(state, reason=update.close_reason)
    """

    def __init__(self, config: Optional[TrailingConfig] = None):
        self.config = config or TrailingConfig.paper_mode()

    def update(
        self,
        state: PositionState,
        *,
        current_price: float,
        bar_ts_ns: int,
    ) -> PositionUpdate:
        """Update state avec prix courant + tente trailing.

        Returns PositionUpdate avec action recommandee.
        """
        result = PositionUpdate()
        tick = _get_tick_size(state.symbol)

        # === 1. Update bars_held (sur changement de barre) ===
        if state.last_bar_ts_ns is None or bar_ts_ns != state.last_bar_ts_ns:
            state.bars_held += 1
            state.last_bar_ts_ns = bar_ts_ns

        # === 2. Update current_price + excursion ===
        state.current_price = current_price
        sign = 1 if state.direction == "LONG" else -1
        excursion = (current_price - state.entry_price) / tick * sign

        # MFE = peak gain
        if excursion > state.mfe:
            state.mfe = round(excursion, 1)
        # MAE = peak loss (signe negatif)
        if excursion < state.mae:
            state.mae = round(excursion, 1)

        # === 3. TR40 SL trailing (NQ-only par defaut) ===
        if (
            self.config.tr40_enabled
            and state.symbol in self.config.tr40_symbols
            and state.sl_ticks_initial > 0
        ):
            self._try_tr40_trail(state, tick, result)

        # === 4. MFE-TP drawback close ===
        if self.config.mfe_tp_enabled:
            self._try_mfe_tp_close(state, current_price, tick, excursion, result)

        # === 5. PALIER trailing close (16/06 Jackson) ===
        # Independant de MFE-TP : si excursion repasse SOUS le SL_locked du
        # palier le plus haut atteint, close direct au prix courant.
        # Si MFE-TP a deja set close_now=True, palier ne re-trigger pas.
        # IMPORTANT : pas de guard excursion >= 0 (contrairement a MFE-TP),
        # car palier 0 = BE (sl_locked=0) doit close quand excursion < 0
        # = limiter la perte au lieu de laisser le SL bracket -14t hit.
        # C'est exactement le scenario Jackson 16/06 : trade ES MFE peak 16t
        # puis revient sous entry -> close BE au lieu de perdre -14t au SL.
        if self.config.palier_trailing_enabled and not result.close_now:
            self._try_palier_close(state, current_price, tick, excursion, result)

        return result

    # -------------------------------------------------------------------------
    # TR40 SL
    # -------------------------------------------------------------------------

    def _try_tr40_trail(
        self, state: PositionState, tick: float, result: PositionUpdate,
    ) -> None:
        """Trailing TR40 SL si MFE >= arming_pct × SL_init.

        SL ne va QUE dans le sens favorable.
        """
        arming_thr = self.config.tr40_arming_pct * state.sl_ticks_initial
        give_back = self.config.tr40_giveback_pct * state.sl_ticks_initial

        if state.mfe < arming_thr:
            return  # pas encore arme

        # Fix R1 review : Emit ARM event 1x via flag tr40_armed (idempotent meme
        # si SL pas encore update). sl_trailed reflete les UPDATE reels seulement.
        if not state.tr40_armed:
            state.tr40_armed = True
            # J11 fix P0-3 : signal_id requis pour traceability cross-categories.
            # Code renomme BOT4_MONITOR_TR40_ARMED (catalog v2 J11).
            result.events.append({
                "code": "BOT4_MONITOR_TR40_ARMED",
                "sym": state.symbol,
                "signal_id": state.signal_id,
                "mfe": state.mfe,
                "arming_thr": round(arming_thr, 1),
                "sl_init": state.sl_ticks_initial,
            })

        # Calculer nouveau SL candidat
        sign = 1 if state.direction == "LONG" else -1
        candidate = state.entry_price + sign * (state.mfe - give_back) * tick

        # SL ne peut aller QUE dans le sens favorable
        if state.direction == "LONG" and candidate <= state.sl_price:
            return
        if state.direction == "SHORT" and candidate >= state.sl_price:
            return

        # Alignement tick obligatoire (rejet broker sinon - fix C1 legacy)
        aligned_sl = round(round(candidate / tick) * tick, 4)

        # Verifier que aligned_sl reste dans le bon sens apres alignement
        if state.direction == "LONG" and aligned_sl <= state.sl_price:
            return
        if state.direction == "SHORT" and aligned_sl >= state.sl_price:
            return

        # UPDATE
        old_sl = state.sl_price
        state.sl_price = aligned_sl
        first_update = not state.sl_trailed  # Fix R2 : reason coherent ARMED vs UPDATED
        state.sl_trailed = True
        state.sl_trail_count += 1

        result.sl_changed = True
        result.new_sl_price = aligned_sl
        result.new_sl_reason = "TR40_ARMED" if first_update else "TR40_UPDATED"
        # J11 fix P0-3 : signal_id requis. Code renomme catalog J11.
        result.events.append({
            "code": "BOT4_MONITOR_TR40_UPDATED",
            "sym": state.symbol,
            "signal_id": state.signal_id,
            "old_sl": round(old_sl, 4),
            "new_sl": aligned_sl,
            "mfe": state.mfe,
            "count": state.sl_trail_count,
        })

    # -------------------------------------------------------------------------
    # MFE-TP drawback
    # -------------------------------------------------------------------------

    def _try_mfe_tp_close(
        self,
        state: PositionState,
        current_price: float,
        tick: float,
        excursion: float,
        result: PositionUpdate,
    ) -> None:
        """MFE-TP : close si drawback (MFE - excursion) >= drawback_ticks.

        Activation : MFE >= seuil_symbol (ES=30 / NQ=50 / MGC=40).
        """
        threshold = self.config.mfe_tp_threshold_ticks.get(state.symbol, 30)
        if state.mfe < threshold:
            return  # pas encore arme

        if not state.trailing_tp_armed:
            state.trailing_tp_armed = True
            # J11 fix P0-3 : signal_id + code renomme catalog J11
            result.events.append({
                "code": "BOT4_MONITOR_TRAILING_TP_ARMED",
                "sym": state.symbol,
                "signal_id": state.signal_id,
                "mfe": state.mfe,
                "threshold": threshold,
            })

        # Fix R4 review : si excursion negative (prix sous entry), c'est un
        # stop-out logique pas un trailing TP. On laisse le SL gerer (SL bracket).
        # Sans ce guard, drawback = mfe - excursion peut exploser et close labellise
        # "TRAILING_TP" un trade en perte.
        if excursion < 0:
            return

        drawback = state.mfe - excursion
        if drawback < self.config.mfe_tp_drawback_ticks:
            return  # pas encore declencheur

        # TRIGGER close
        captured_pct = round(100 * excursion / state.mfe, 1) if state.mfe > 0 else 0

        result.close_now = True
        result.close_reason = "TRAILING_TP"
        result.close_price = current_price
        result.close_pnl_ticks = round(excursion, 1)
        # J11 fix P0-3 : signal_id + code renomme catalog J11
        result.events.append({
            "code": "BOT4_MONITOR_TRAILING_TP_TRIGGERED",
            "sym": state.symbol,
            "signal_id": state.signal_id,
            "mfe": state.mfe,
            "excursion": round(excursion, 1),
            "drawback": round(drawback, 1),
            "captured_pct": captured_pct,
        })

    # -------------------------------------------------------------------------
    # PALIER trailing (Jackson 16/06)
    # -------------------------------------------------------------------------

    def _try_palier_close(
        self,
        state: PositionState,
        current_price: float,
        tick: float,
        excursion: float,
        result: PositionUpdate,
    ) -> None:
        """Trailing par paliers : close direct si excursion repasse sous le
        SL_locked du palier le plus haut atteint.

        Paliers : list[(mfe_threshold_ticks, sl_locked_profit_ticks)] ascendant.
        Exemple ES : [(10, 0), (20, 5), (30, 15), (45, 25), (60, 40)]

        Logique :
          1. Trouver l'index du palier max atteint = max idx tel que mfe >= paliers[idx][0]
          2. Si nouveau palier atteint (idx > state.palier_atteint_idx) : emit event ARMED
          3. Si excursion < paliers[max_idx][1] -> close direct (palier descendu)
        """
        paliers = self.config.palier_trailing_by_symbol.get(state.symbol)
        if not paliers:
            return

        # Index du palier le plus haut atteint (-1 = aucun)
        max_idx = -1
        for i, (mfe_thr, _sl_lock) in enumerate(paliers):
            if state.mfe >= mfe_thr:
                max_idx = i
            else:
                break  # paliers ascendants : on s'arrete au premier non atteint

        if max_idx < 0:
            return  # aucun palier atteint encore

        # Emit ARMED event 1x par palier monte (idempotent)
        if max_idx > state.palier_atteint_idx:
            state.palier_atteint_idx = max_idx
            mfe_thr, sl_lock = paliers[max_idx]
            result.events.append({
                "code": "BOT4_MONITOR_PALIER_ARMED",
                "sym": state.symbol,
                "signal_id": state.signal_id,
                "palier_idx": max_idx,
                "mfe_threshold": mfe_thr,
                "sl_locked_ticks": sl_lock,
                "mfe_peak": state.mfe,
            })

        # Verifier si excursion courante < sl_locked du palier atteint -> close
        sl_locked = paliers[max_idx][1]
        if excursion < sl_locked:
            captured_pct = round(100 * excursion / state.mfe, 1) if state.mfe > 0 else 0
            result.close_now = True
            result.close_reason = "PALIER_TRAILING"
            result.close_price = current_price
            result.close_pnl_ticks = round(excursion, 1)
            result.events.append({
                "code": "BOT4_MONITOR_PALIER_TRIGGERED",
                "sym": state.symbol,
                "signal_id": state.signal_id,
                "palier_idx": max_idx,
                "mfe_peak": state.mfe,
                "sl_locked_ticks": sl_locked,
                "excursion": round(excursion, 1),
                "captured_pct": captured_pct,
            })
