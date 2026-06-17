"""M4 Risk Gate — 2 modes : COLLECT (data) + PROD (prop firm).

Architecture scellee : M1 Reader → M2 Decide → M4 Risk (HARD GATE) → M3 SLTP → M5 Execution.

**Mode COLLECT (paper data collection, shadow log 30j)** :
- Seul actif : cooldown apres trade + kill switch fichier STOP.flag
- Inactifs : daily PnL limit, n_consec_sl, max_trades/jour, sizing adaptive
- Sizing fixe : 1 micro
- Justification : MAXIMISER n trades pour calibration empirique Lopez DSR/PSR (n>=100)

**Mode PROD (prop firm Topstep)** :
- Tout actif : daily PnL limit, n_consec_sl, max_trades, cooldown, kill switch
- Sizing : Half-Kelly adapte conviction
- Justification : protection capital live

Decision Jackson 27/05/2026 : "ON DOIS LE LAISSER TRADER COLLECTE DE DONNEES".
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .contract import RiskEvent, RiskGate, SizingDecision


# =============================================================================
# Pydantic config + state
# =============================================================================


class RiskConfig(BaseModel):
    """Config Risk. 2 profils via mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["collect", "prod"]

    # Cooldown (actif les 2 modes, anti-revenge basique)
    cooldown_after_trade_sec: int = Field(default=180, ge=0,
                                          description="3min collect, 600 prod")

    # Kill switch (actif les 2 modes)
    kill_switch_file: str = Field(default="STOP.flag",
                                  description="Path fichier flag manuel")

    # === Gates COLLECT-OFF / PROD-ON ===
    daily_pnl_loss_limit_usd: Optional[float] = Field(
        default=None,
        description="None=disabled (collect). PROD: -1000 par symbol typiquement.",
    )
    n_consec_sl_max: Optional[int] = Field(
        default=None,
        description="None=disabled (collect). PROD: 3.",
    )
    max_trades_per_day: Optional[int] = Field(
        default=None,
        description="None=disabled (collect). PROD: 5.",
    )
    # FIX 17/06 (Jackson audit observabilite) : hook session gate optionnel.
    # Bot 4 = 24h SAFE COLLECT par design (aucune restriction session active).
    # Si on veut restreindre futur : passer tuple ("US",) ou ("ASIA","LONDON","US").
    # None = comportement actuel (aucun filtre session, garde-fou bypass).
    # NOTE : le check est dans main.py:_process_symbol (pas dans check_pre_entry
    # car risk.py ne recoit pas le bar avec session_id).
    tradable_sessions: Optional[tuple] = Field(
        default=None,
        description="None=24h (current). Tuple (ex: ('US','ASIA','LONDON')) pour restreindre.",
    )

    # === Sizing ===
    sizing_mode: Literal["fixed_1", "fixed_max", "half_kelly"] = Field(
        default="fixed_1",
        description=(
            "fixed_1 (1 micro fixe collect) / "
            "fixed_max (= max_micros_per_trade fixe paper) / "
            "half_kelly (prod adaptive conviction)"
        ),
    )
    max_micros_per_trade: int = Field(default=3, ge=1, le=10)

    @classmethod
    def collect_mode(cls) -> "RiskConfig":
        """Preset COLLECT : seul cooldown + kill switch actifs."""
        return cls(
            mode="collect",
            cooldown_after_trade_sec=180,  # 3 min anti-revenge
            daily_pnl_loss_limit_usd=None,
            n_consec_sl_max=None,
            max_trades_per_day=None,
            sizing_mode="fixed_1",
            max_micros_per_trade=1,
        )

    @classmethod
    def prod_mode(cls) -> "RiskConfig":
        """Preset PROD prop firm : tout actif."""
        return cls(
            mode="prod",
            cooldown_after_trade_sec=600,  # 10 min cooldown plus serre prod
            daily_pnl_loss_limit_usd=-1000.0,
            n_consec_sl_max=3,
            max_trades_per_day=5,
            sizing_mode="half_kelly",
            max_micros_per_trade=3,
        )

    @classmethod
    def paper_aggressive_mode(cls) -> "RiskConfig":
        """Preset PAPER Sim4 Bot 4 : execute max trades, kill switch + cooldown actifs.

        Decision Jackson 27/05 : "DEMARRER EN PAPER PAS EN SHADOW, RIEN A PERDRE,
        BOT 4 DOIT EXECUTER LES TRADES" → on saute Phase 6 shadow log.

        Differences vs COLLECT (1 micro safe) :
        - 3 micros sizing (realiste Jackson trade ainsi)
        - Cooldown 900s (15min) post-trade (Jackson 16/06 : selectivite premium)

        Differences vs PROD (protections firm) :
        - Pas de daily PnL limit (paper = rien a perdre)
        - Pas de circuit breaker (on veut voir l'edge sans masque)
        - Pas de max trades/jour (la selectivite premium + cooldown 15min limitent)

        Garde-fous actifs :
        - Cooldown 900s (15 min) post-trade (Jackson 16/06 : anti-overtrading,
          combine avec filtre signaux PREMIUM dans scenario_decide)
        - Kill switch fichier STOP.flag (safety)
        - Gate positions_open >= 1 (1 position max symbol, CLAUDE.md)
        """
        return cls(
            mode="prod",  # mode field reste prod (= tout active a la base)
            cooldown_after_trade_sec=900,  # 15 min (Jackson 16/06 selectivite)
            daily_pnl_loss_limit_usd=None,  # disabled
            n_consec_sl_max=None,  # disabled
            max_trades_per_day=None,  # illimite
            sizing_mode="fixed_max",  # paper = 3 micros fixe (Jackson reality)
            max_micros_per_trade=3,  # 3 micros Jackson reality NQ/ES/MGC
        )


@dataclass
class RiskState:
    """Etat runtime par symbole (cooldown + daily counters)."""

    cooldown_until_ts_ns: Optional[int] = None
    daily_pnl_usd: float = 0.0
    consec_sl_count: int = 0
    trades_today: int = 0
    positions_open: int = 0
    current_session_date: Optional[str] = None  # reset daily counters
    last_trade_ts_ns: Optional[int] = None
    last_trade_pnl_usd: Optional[float] = None
    last_trade_exit_reason: Optional[str] = None

    def reset_daily(self, new_session_date: str) -> None:
        self.daily_pnl_usd = 0.0
        self.consec_sl_count = 0
        self.trades_today = 0
        self.current_session_date = new_session_date


# =============================================================================
# Risk Manager
# =============================================================================


class RiskManager:
    """Gestionnaire risk multi-symbol avec 2 modes COLLECT/PROD.

    Usage :
        risk = RiskManager(config=RiskConfig.collect_mode())
        allow, reason, event = risk.check_pre_entry(
            symbol="NQ", direction="LONG", conviction=0.85,
            decision_id="D-NQ-...", bar_ts_event_ns=..., session_date_trading="2026-05-27"
        )
        if allow:
            # ... execute trade
            risk.on_trade_open(symbol, signal_id, ts_ns)
        # apres close :
        risk.on_trade_close(symbol, signal_id, pnl_usd=+45, exit_reason="TP1", ts_ns=...)
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig.collect_mode()
        self.states: Dict[str, RiskState] = defaultdict(RiskState)
        self._kill_switch_path = self.config.kill_switch_file

    # -------------------------------------------------------------------------
    # API publique
    # -------------------------------------------------------------------------

    def check_pre_entry(
        self,
        *,
        symbol: Literal["NQ", "ES", "MGC"],
        direction: Literal["LONG", "SHORT"],
        conviction: float,
        decision_id: str,
        bar_ts_event_ns: int,
        session_date_trading: str,
    ) -> tuple[bool, str, RiskEvent]:
        """Evalue tous les gates risk et retourne (allow, blocking_reason, RiskEvent).

        Returns:
            (True, "", event) si ALLOW
            (False, reason, event) si BLOCK
        """
        state = self.states[symbol]
        # Reset daily si nouveau jour CME
        if state.current_session_date != session_date_trading:
            state.reset_daily(session_date_trading)

        gates: List[RiskGate] = []
        blocking_gate: Optional[str] = None
        blocking_reason: Optional[str] = None

        # === 1. Kill switch (actif les 2 modes) ===
        kill_active = os.path.isfile(self._kill_switch_path)
        gates.append(RiskGate(
            name="kill_switch",
            passed=not kill_active,
            value=kill_active,
            threshold=False,
            reason=f"file={self._kill_switch_path}",
        ))
        if kill_active and blocking_gate is None:
            blocking_gate = "kill_switch"
            blocking_reason = f"STOP.flag detected ({self._kill_switch_path})"

        # === 1bis. Position deja ouverte (fix P1-2 review, anti CLAUDE.md "1 position max") ===
        position_already_open = state.positions_open >= 1
        gates.append(RiskGate(
            name="risk_per_sym",
            passed=not position_already_open,
            value=state.positions_open,
            threshold=1,
            reason=f"positions_open={state.positions_open}",
        ))
        if position_already_open and blocking_gate is None:
            blocking_gate = "risk_per_sym"
            blocking_reason = f"position deja ouverte sur {symbol} (max 1)"

        # === 2. Cooldown (actif les 2 modes) ===
        cooldown_passed, cooldown_value, cooldown_reason = self._check_cooldown(
            state, bar_ts_event_ns
        )
        gates.append(RiskGate(
            name="cooldown",
            passed=cooldown_passed,
            value=cooldown_value,
            threshold=self.config.cooldown_after_trade_sec,
            reason=cooldown_reason,
        ))
        if not cooldown_passed and blocking_gate is None:
            blocking_gate = "cooldown"
            blocking_reason = cooldown_reason

        # === 3. Daily PnL limit (PROD only) ===
        if self.config.daily_pnl_loss_limit_usd is not None:
            limit = self.config.daily_pnl_loss_limit_usd
            pnl_passed = state.daily_pnl_usd > limit
            gates.append(RiskGate(
                name="daily_pnl_limit",
                passed=pnl_passed,
                value=state.daily_pnl_usd,
                threshold=limit,
                reason=f"daily_pnl=${state.daily_pnl_usd:.2f} vs limit ${limit:.2f}",
            ))
            if not pnl_passed and blocking_gate is None:
                blocking_gate = "daily_pnl_limit"
                blocking_reason = (
                    f"daily_pnl ${state.daily_pnl_usd:.2f} <= limit ${limit:.2f}"
                )

        # === 4. Circuit breaker n_consec_sl (PROD only) ===
        if self.config.n_consec_sl_max is not None:
            max_sl = self.config.n_consec_sl_max
            cb_passed = state.consec_sl_count < max_sl
            gates.append(RiskGate(
                name="circuit_breaker",
                passed=cb_passed,
                value=state.consec_sl_count,
                threshold=max_sl,
                reason=f"consec_sl={state.consec_sl_count}/{max_sl}",
            ))
            if not cb_passed and blocking_gate is None:
                blocking_gate = "circuit_breaker"
                blocking_reason = f"consec_sl {state.consec_sl_count} >= {max_sl}"

        # === 5. Max trades/jour (PROD only) ===
        if self.config.max_trades_per_day is not None:
            max_t = self.config.max_trades_per_day
            trades_passed = state.trades_today < max_t
            gates.append(RiskGate(
                name="risk_per_sym",
                passed=trades_passed,
                value=state.trades_today,
                threshold=max_t,
                reason=f"trades_today={state.trades_today}/{max_t}",
            ))
            if not trades_passed and blocking_gate is None:
                blocking_gate = "risk_per_sym"
                blocking_reason = f"trades_today {state.trades_today} >= {max_t}"

        # === Decision finale + Sizing ===
        allow = blocking_gate is None
        sizing_decision: Optional[SizingDecision] = None
        if allow:
            n_micros = self._compute_sizing(conviction)
            sizing_decision = SizingDecision(
                n_micros=n_micros,
                conviction_used=conviction,
                sizing_formula=(
                    "fixed_1" if self.config.sizing_mode == "fixed_1"
                    else f"half_kelly_conv_{conviction:.2f}"
                ),
                symbol_max_micros=self.config.max_micros_per_trade,
            )

        # === Build RiskEvent Pydantic ===
        event = self._build_event(
            decision_id=decision_id,
            bar_ts_event_ns=bar_ts_event_ns,
            session_date_trading=session_date_trading,
            symbol=symbol,
            gates=gates,
            kill_switch_active=kill_active,
            allow=allow,
            blocking_gate=blocking_gate,
            blocking_reason=blocking_reason,
            sizing_decision=sizing_decision,
        )

        return (allow, blocking_reason or "", event)

    def on_trade_open(
        self, *, symbol: str, signal_id: str, ts_event_ns: int,
        session_date_trading: Optional[str] = None,
    ) -> None:
        """Trade ouvert : marquer position open.

        Fix P1-1 review : set current_session_date pour eviter reset_daily silent
        au prochain check_pre_entry du jour suivant (qui effacerait PnL/counters).
        """
        state = self.states[symbol]
        if state.current_session_date is None:
            state.current_session_date = session_date_trading
        state.positions_open += 1
        state.trades_today += 1

    def on_trade_close(
        self, *, symbol: str, signal_id: str, pnl_usd: float,
        exit_reason: str, ts_event_ns: int,
        session_date_trading: Optional[str] = None,
    ) -> None:
        """Trade ferme : update PnL + cooldown + consec_sl.

        Fix P1-1 review : set current_session_date pour eviter reset_daily silent.
        """
        state = self.states[symbol]
        if state.current_session_date is None:
            state.current_session_date = session_date_trading
        state.positions_open = max(0, state.positions_open - 1)
        state.daily_pnl_usd += pnl_usd
        state.last_trade_ts_ns = ts_event_ns
        state.last_trade_pnl_usd = pnl_usd
        state.last_trade_exit_reason = exit_reason
        if pnl_usd < 0:
            state.consec_sl_count += 1
        else:
            state.consec_sl_count = 0
        # Cooldown apres trade (actif les 2 modes)
        state.cooldown_until_ts_ns = ts_event_ns + (
            self.config.cooldown_after_trade_sec * 1_000_000_000
        )

    def is_killed(self) -> bool:
        """Kill switch global (fichier present)."""
        return os.path.isfile(self._kill_switch_path)

    def cooldown_remaining_sec(self, symbol: str, now_ts_ns: int) -> float:
        """Secondes restantes de cooldown pour symbol."""
        state = self.states[symbol]
        if state.cooldown_until_ts_ns is None:
            return 0.0
        diff_ns = state.cooldown_until_ts_ns - now_ts_ns
        return max(0.0, diff_ns / 1_000_000_000)

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _check_cooldown(
        self, state: RiskState, now_ts_ns: int,
    ) -> tuple[bool, float, str]:
        """Returns (passed, sec_remaining, reason)."""
        if state.cooldown_until_ts_ns is None:
            return (True, 0.0, "no_previous_trade")
        diff_ns = state.cooldown_until_ts_ns - now_ts_ns
        if diff_ns <= 0:
            return (True, 0.0, "cooldown_expired")
        sec_remain = diff_ns / 1_000_000_000
        return (False, sec_remain, f"cooldown {sec_remain:.0f}s remaining")

    def _compute_sizing(self, conviction: float) -> int:
        """Sizing selon mode :
        - fixed_1 : toujours 1 micro (mode COLLECT safe)
        - fixed_max : toujours max_micros_per_trade (mode PAPER Jackson reality)
        - half_kelly : scale conviction [0,1] vers [1, max_micros] (mode PROD adaptive)
        """
        if self.config.sizing_mode == "fixed_1":
            return 1
        if self.config.sizing_mode == "fixed_max":
            return self.config.max_micros_per_trade
        # half_kelly
        conv = max(0.0, min(1.0, conviction))
        n = max(1, round(conv * self.config.max_micros_per_trade))
        return n

    def _build_event(
        self, *, decision_id: str, bar_ts_event_ns: int,
        session_date_trading: str, symbol: str,
        gates: List[RiskGate], kill_switch_active: bool,
        allow: bool, blocking_gate: Optional[str],
        blocking_reason: Optional[str],
        sizing_decision: Optional[SizingDecision],
    ) -> RiskEvent:
        state = self.states[symbol]

        # Cooldowns ISO (snapshot per-symbol)
        cooldowns_iso: Dict[str, Optional[str]] = {}
        for sym, st in self.states.items():
            if st.cooldown_until_ts_ns is None:
                cooldowns_iso[sym] = None
            else:
                cooldowns_iso[sym] = datetime.fromtimestamp(
                    st.cooldown_until_ts_ns / 1e9, tz=timezone.utc
                ).isoformat()

        consec_sl_count = {sym: st.consec_sl_count for sym, st in self.states.items()}
        positions_open = {sym: st.positions_open for sym, st in self.states.items()}

        # daily_pnl_limit_usd : meme en COLLECT on emit la valeur (None convertit a 0
        # car contract.py exige float). Decision : utiliser 0.0 en COLLECT pour
        # signaler "no limit", documenter dans note.
        daily_pnl_limit_for_event = (
            self.config.daily_pnl_loss_limit_usd
            if self.config.daily_pnl_loss_limit_usd is not None
            else 0.0
        )

        return RiskEvent(
            decision_id=decision_id,
            bar_ts_event_ns=bar_ts_event_ns,
            session_date_trading=session_date_trading,
            symbol=symbol,
            gates=gates,
            kill_switch_active=kill_switch_active,
            daily_pnl_usd=state.daily_pnl_usd,
            daily_pnl_limit_usd=daily_pnl_limit_for_event,
            cooldowns_active=cooldowns_iso,
            consecutive_sl_count=consec_sl_count,
            positions_open=positions_open,
            exposure_usd=0.0,  # TODO Phase 7 : calcul exposure live
            sizing_decision=sizing_decision,
            risk_decision="ALLOW" if allow else "BLOCK",
            blocking_gate=blocking_gate,
            blocking_reason=blocking_reason,
        )
