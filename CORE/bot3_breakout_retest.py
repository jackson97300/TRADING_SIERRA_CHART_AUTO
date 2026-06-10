"""Bot 3 — Setup distinct BREAKOUT_RETEST (canon Steidlmayer/Dalton).

State machine par (symbol, level_name) :

  TOUCH (orderflow crush detecte)
       |
       v
  PENDING_ACCEPTANCE
    - attendre BREAKOUT_N_ACCEPTANCE_BARS (5) barres
    - acceptance hybride TPO-printed (FIX #10, market-analyst Section 2) :
        * close du cote casse = 1.0 confirm (forte acceptance)
        * wick du cote casse >= BREAKOUT_WICK_ATR_RATIO * atr = 0.5 confirm
    - somme >= BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD (2.5) → ACCEPTED
    - sinon → CANCELLED (CRUSH_ABSORBED)
       |
       v
  WAIT_RETEST
    - attendre max BREAKOUT_RETEST_DEADLINE_BARS (30) barres
    - check : abs(dist_signed) <= BREAKOUT_RETEST_PROXIMITY_MULTIPLIER * proximity ?
    - sur retest : delta + finish coherents avec direction breakout
      (FIX #2 market-analyst : seuils normalises via rvol)
    - oui → ENTRY BREAKOUT_RETEST (signal genere)
    - sinon (timeout ou rejection meme cote) → CANCELLED (RETEST_TIMEOUT)

Cooldown post-cancel (FIX #8) : apres CRUSH_ABSORBED ou RETEST_TIMEOUT, on
attend BREAKOUT_COOLDOWN_AFTER_CANCEL_BARS (10) bars avant nouveau register
sur le meme (symbol, level_name).

Module pure state (pas de side effect, pas d'I/O). L'integration et l'envoi
de signal sont du resort de bot3_mp_engine.
Les codes log BOT3_BREAKOUT_* sont emis par mp_engine en consommant les
events retournes par les transitions (pattern observer).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    from .bot3_config import (
        BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD,
        BREAKOUT_COOLDOWN_AFTER_CANCEL_BARS,
        BREAKOUT_N_ACCEPTANCE_BARS,
        BREAKOUT_N_ACCEPTANCE_CONFIRMS_REQUIRED,
        BREAKOUT_RETEST_DEADLINE_BARS,
        BREAKOUT_RETEST_DELTA_BASE,
        BREAKOUT_RETEST_FINISH_BASE,
        BREAKOUT_RETEST_PROXIMITY_MULTIPLIER,
        BREAKOUT_WICK_ATR_RATIO,
    )
except ImportError:
    from bot3_config import (
        BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD,
        BREAKOUT_COOLDOWN_AFTER_CANCEL_BARS,
        BREAKOUT_N_ACCEPTANCE_BARS,
        BREAKOUT_N_ACCEPTANCE_CONFIRMS_REQUIRED,
        BREAKOUT_RETEST_DEADLINE_BARS,
        BREAKOUT_RETEST_DELTA_BASE,
        BREAKOUT_RETEST_FINISH_BASE,
        BREAKOUT_RETEST_PROXIMITY_MULTIPLIER,
        BREAKOUT_WICK_ATR_RATIO,
    )


# ════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ════════════════════════════════════════════════════════════════════════

@dataclass
class BreakoutRetestState:
    """Etat d'un setup BREAKOUT_RETEST pour un (symbol, level_name)."""
    state: str                           # PENDING_ACCEPTANCE / WAIT_RETEST / DONE
    symbol: str
    level_name: str
    level_def: dict                      # snapshot du level_def au touch
    side_break: str                      # "SHORT" (support casse) ou "LONG" (resistance cassee)
    touch_bar_idx: int                   # bar counter du Bot3Engine au moment du touch
    touch_bar_ts: str
    touch_price: float                   # close de la barre de touch
    touch_dist_signed: float             # dist signed (% V4 convention) au touch
    level_price: float                   # FIX #1 (CRITIQUE) : level_price calcule au register, plus de reconstruction approximative
    proximity_pct: float                 # proximity_pct du level_def (en %, V4 convention)
    n_acceptance_bars_seen: int = 0
    acceptance_score: float = 0.0        # FIX #10 : somme confirms (1.0 close, 0.5 wick)
    acceptance_bars_data: list = field(default_factory=list)
    accepted_at_idx: Optional[int] = None
    retest_deadline_idx: Optional[int] = None
    retest_idx: Optional[int] = None
    retest_price: Optional[float] = None
    cancel_reason: Optional[str] = None
    created_at_iso: str = ""
    state_id: str = ""


@dataclass
class BreakoutRetestSignal:
    """Signal genere par la state machine quand ENTRY confirmee."""
    state_id: str
    symbol: str
    level_name: str
    side: str                # direction du trade (= side_break)
    entry_price: float
    entry_bar_ts: str
    touch_bar_ts: str
    touch_price: float
    accepted_at_bar_ts: str
    retest_bar_ts: str
    n_bars_touch_to_retest: int
    retest_dist_signed: float
    acceptance_score: float
    snapshot_acceptance: list
    snapshot_retest: dict


@dataclass
class BreakoutRetestEvent:
    """Event emis par la state machine pour que mp_engine emit les logs.

    FIX #3 (review code-reviewer 03/05) : codes BOT3_BREAKOUT_* doivent
    etre emis en prod. State machine = pure (no side effect) → retourne
    events que mp_engine consomme.
    """
    event_type: str          # PENDING / ACCEPTED / CRUSH_ABSORBED / RETEST_TIMEOUT
    state_id: str
    symbol: str
    level_name: str
    side_break: str
    payload: dict


# ════════════════════════════════════════════════════════════════════════
# STATE MACHINE
# ════════════════════════════════════════════════════════════════════════

class BreakoutRetestStateMachine:
    """State machine BREAKOUT_RETEST pour Bot 3.

    Stockage par (symbol, level_name) → 1 state actif max simultane.
    Anti-replay : nouveau touch ignore si state actif.
    Cooldown post-cancel (FIX #8) : apres DONE, attente N bars avant re-register.
    """

    def __init__(self):
        self._states: dict[tuple[str, str], BreakoutRetestState] = {}
        # Historique pour cooldown post-cancel : (symbol, level) → (last_done_idx, reason)
        self._cooldown: dict[tuple[str, str], tuple[int, str]] = {}
        # Events emis par les dernieres transitions (consommes par mp_engine)
        self._pending_events: list[BreakoutRetestEvent] = []
        self.stats = {
            "n_pending_registered": 0,
            "n_register_skipped_cooldown": 0,
            "n_register_skipped_active": 0,
            "n_acceptance_confirmed": 0,
            "n_acceptance_cancelled": 0,
            "n_retest_entry": 0,
            "n_retest_timeout": 0,
        }

    def register_pending_breakout(
        self,
        symbol: str,
        level_name: str,
        level_def: dict,
        side_break: str,
        touch_bar_idx: int,
        touch_bar_ts: str,
        touch_price: float,
        touch_dist_signed: float,
        level_price: float,                  # FIX #1 : injection directe
        ctx_at_touch: dict,
    ) -> Optional[BreakoutRetestState]:
        """Enregistre un pending breakout au touch + crush detecte.

        FIX #1 : level_price PASSE par mp_engine (calcule depuis dist_pct V4
        en %), plus de reconstruction approximative dans la state machine.
        FIX #8 : skip si cooldown post-cancel actif.

        Returns None si :
          - state actif existe sur ce (symbol, level)
          - cooldown post-cancel pas encore termine
        """
        key = (symbol, level_name)

        # Anti-replay state actif
        if key in self._states and self._states[key].state != "DONE":
            self.stats["n_register_skipped_active"] += 1
            return None

        # FIX #8 : cooldown post-cancel
        if key in self._cooldown:
            last_done_idx, last_reason = self._cooldown[key]
            if touch_bar_idx - last_done_idx < BREAKOUT_COOLDOWN_AFTER_CANCEL_BARS:
                self.stats["n_register_skipped_cooldown"] += 1
                return None

        state = BreakoutRetestState(
            state="PENDING_ACCEPTANCE",
            symbol=symbol,
            level_name=level_name,
            level_def=dict(level_def),
            side_break=side_break,
            touch_bar_idx=touch_bar_idx,
            touch_bar_ts=touch_bar_ts,
            touch_price=touch_price,
            touch_dist_signed=touch_dist_signed,
            level_price=level_price,
            proximity_pct=level_def.get("proximity_pct", 0.05),
            retest_deadline_idx=touch_bar_idx + BREAKOUT_N_ACCEPTANCE_BARS + BREAKOUT_RETEST_DEADLINE_BARS,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
            state_id=uuid.uuid4().hex[:12],
        )
        # Snapshot bar de touch
        state.acceptance_bars_data.append({
            "bar_idx": touch_bar_idx,
            "bar_ts": touch_bar_ts,
            "close": touch_price,
            "dist_signed": touch_dist_signed,
            "level_price": level_price,
            "ctx_summary": {
                "delta_bar": ctx_at_touch.get("delta_bar"),
                "finish_strength": ctx_at_touch.get("finish_strength"),
                "rvol": ctx_at_touch.get("rvol"),
                "session": ctx_at_touch.get("session"),
            },
        })
        self._states[key] = state
        self.stats["n_pending_registered"] += 1

        # Event PENDING pour mp_engine emit log
        self._pending_events.append(BreakoutRetestEvent(
            event_type="PENDING",
            state_id=state.state_id,
            symbol=symbol,
            level_name=level_name,
            side_break=side_break,
            payload={"touch_bar_ts": touch_bar_ts, "level_price": level_price},
        ))
        return state

    def update_on_bar(
        self,
        symbol: str,
        bar: dict,
        bar_idx: int,
        bar_ts: str,
        close: float,
        high: float,
        low: float,
        atr: float,
    ) -> Optional[BreakoutRetestSignal]:
        """Avance la state machine pour TOUS les states actifs du symbole.

        FIX #1 : utilise state.level_price (deja calcule au register, pas reconstruction)
        FIX #2 : seuils delta/finish normalises via rvol au retest
        FIX #10 : acceptance hybride (close + wick TPO printed)

        Args:
            high, low : pour TPO printed wick check
            atr : pour seuil wick

        Returns:
            BreakoutRetestSignal si entry confirmee sur cette bar.
        """
        signal: Optional[BreakoutRetestSignal] = None
        keys_to_clean: list[tuple[str, str]] = []

        for key, state in self._states.items():
            if state.symbol != symbol:
                continue
            if state.state == "DONE":
                keys_to_clean.append(key)
                continue

            # ─── PENDING_ACCEPTANCE → check N_ACCEPTANCE_BARS suivantes ───
            if state.state == "PENDING_ACCEPTANCE":
                bars_since_touch = bar_idx - state.touch_bar_idx
                if bars_since_touch <= 0:
                    continue
                if bars_since_touch > BREAKOUT_N_ACCEPTANCE_BARS:
                    # Window terminee : decision finale
                    if state.acceptance_score >= BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD:
                        # ACCEPTED → WAIT_RETEST
                        state.state = "WAIT_RETEST"
                        state.accepted_at_idx = bar_idx
                        self.stats["n_acceptance_confirmed"] += 1
                        self._pending_events.append(BreakoutRetestEvent(
                            event_type="ACCEPTED",
                            state_id=state.state_id,
                            symbol=symbol,
                            level_name=state.level_name,
                            side_break=state.side_break,
                            payload={
                                "score": state.acceptance_score,
                                "n_seen": state.n_acceptance_bars_seen,
                                # P3 ultra riche : bars data complete
                                "acceptance_bars_data": list(state.acceptance_bars_data),
                                "level_price": state.level_price,
                                "touch_bar_ts": state.touch_bar_ts,
                                "touch_price": state.touch_price,
                            },
                        ))
                    else:
                        # CRUSH_ABSORBED
                        state.state = "DONE"
                        state.cancel_reason = "CRUSH_ABSORBED"
                        self.stats["n_acceptance_cancelled"] += 1
                        self._cooldown[key] = (bar_idx, "CRUSH_ABSORBED")
                        self._pending_events.append(BreakoutRetestEvent(
                            event_type="CRUSH_ABSORBED",
                            state_id=state.state_id,
                            symbol=symbol,
                            level_name=state.level_name,
                            side_break=state.side_break,
                            payload={
                                "score": state.acceptance_score,
                                "threshold": BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD,
                                # P3 ultra riche
                                "acceptance_bars_data": list(state.acceptance_bars_data),
                                "level_price": state.level_price,
                                "touch_bar_ts": state.touch_bar_ts,
                                "touch_price": state.touch_price,
                            },
                        ))
                        keys_to_clean.append(key)
                    continue

                # FIX #10 : acceptance hybride TPO-printed (close + wick)
                # TIER S (Jackson 03/05) : penalite si wick OPPOSE >= 0.50 = hammer/shooting reverse.
                # bar_lower_wick_pct sur SHORT breakout = la barre a reverse depuis le bas = trap.
                # bar_upper_wick_pct sur LONG breakout = shooting star = reversal probable.
                level_price = state.level_price
                close_confirm = 0.0
                wick_confirm = 0.0
                bar_lower_wick = bar.get("bar_lower_wick_pct", 0.0) if hasattr(bar, "get") else 0.0
                bar_upper_wick = bar.get("bar_upper_wick_pct", 0.0) if hasattr(bar, "get") else 0.0
                try:
                    bar_lower_wick = float(bar_lower_wick or 0.0)
                    bar_upper_wick = float(bar_upper_wick or 0.0)
                except (TypeError, ValueError):
                    bar_lower_wick = 0.0
                    bar_upper_wick = 0.0
                if state.side_break == "SHORT":
                    # Support casse → on cherche TPO printed below level
                    if close < level_price:
                        # close confirme : 1.0 plein OU 0.5 si hammer reverse (long lower wick)
                        close_confirm = 0.5 if bar_lower_wick >= 0.50 else 1.0
                    elif low < level_price and atr > 0:
                        wick_below_pts = level_price - low
                        if wick_below_pts >= BREAKOUT_WICK_ATR_RATIO * atr:
                            wick_confirm = 0.5
                else:  # LONG (resistance cassee)
                    if close > level_price:
                        # close confirme : 1.0 OU 0.5 si shooting star reverse (long upper wick)
                        close_confirm = 0.5 if bar_upper_wick >= 0.50 else 1.0
                    elif high > level_price and atr > 0:
                        wick_above_pts = high - level_price
                        if wick_above_pts >= BREAKOUT_WICK_ATR_RATIO * atr:
                            wick_confirm = 0.5

                bar_confirm = max(close_confirm, wick_confirm)
                state.n_acceptance_bars_seen += 1
                state.acceptance_score += bar_confirm
                state.acceptance_bars_data.append({
                    "bar_idx": bar_idx,
                    "bar_ts": bar_ts,
                    "close": close,
                    "high": high,
                    "low": low,
                    "level_price": level_price,
                    "close_confirm": close_confirm,
                    "wick_confirm": wick_confirm,
                    "score_so_far": state.acceptance_score,
                })

                # Early exit : si score deja >= threshold + minimum bars vus
                if state.acceptance_score >= BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD \
                   and bars_since_touch >= BREAKOUT_N_ACCEPTANCE_CONFIRMS_REQUIRED:
                    state.state = "WAIT_RETEST"
                    state.accepted_at_idx = bar_idx
                    self.stats["n_acceptance_confirmed"] += 1
                    self._pending_events.append(BreakoutRetestEvent(
                        event_type="ACCEPTED",
                        state_id=state.state_id,
                        symbol=symbol,
                        level_name=state.level_name,
                        side_break=state.side_break,
                        payload={
                            "score": state.acceptance_score,
                            "n_seen": state.n_acceptance_bars_seen,
                            # P3 ultra riche
                            "acceptance_bars_data": list(state.acceptance_bars_data),
                            "level_price": state.level_price,
                            "touch_bar_ts": state.touch_bar_ts,
                            "touch_price": state.touch_price,
                        },
                    ))
                continue

            # ─── WAIT_RETEST → cherche retest du niveau ───
            if state.state == "WAIT_RETEST":
                if bar_idx > state.retest_deadline_idx:
                    # Timeout
                    state.state = "DONE"
                    state.cancel_reason = "RETEST_TIMEOUT"
                    self.stats["n_retest_timeout"] += 1
                    self._cooldown[key] = (bar_idx, "RETEST_TIMEOUT")
                    self._pending_events.append(BreakoutRetestEvent(
                        event_type="RETEST_TIMEOUT",
                        state_id=state.state_id,
                        symbol=symbol,
                        level_name=state.level_name,
                        side_break=state.side_break,
                        payload={
                            "max_bars": BREAKOUT_RETEST_DEADLINE_BARS,
                            # P3 ultra riche
                            "acceptance_bars_data": list(state.acceptance_bars_data),
                            "accepted_at_idx": state.accepted_at_idx,
                            "level_price": state.level_price,
                            "touch_bar_ts": state.touch_bar_ts,
                        },
                    ))
                    keys_to_clean.append(key)
                    continue

                # Verifier si retest : dist au niveau d'origine (V4 % convention)
                dist_col = state.level_def.get("dist_col")
                if not dist_col:
                    continue
                dist_signed = bar.get(dist_col) if hasattr(bar, "get") else None
                if dist_signed is None:
                    continue
                try:
                    dist_signed = float(dist_signed)
                except (TypeError, ValueError):
                    continue
                if dist_signed != dist_signed:  # NaN
                    continue

                retest_proximity = state.proximity_pct * BREAKOUT_RETEST_PROXIMITY_MULTIPLIER
                if abs(dist_signed) > retest_proximity:
                    continue  # pas de retest ce tour

                # FIX #2 : seuils normalises via rvol
                rvol = bar.get("rvol", 1.0) if hasattr(bar, "get") else 1.0
                try:
                    rvol = float(rvol)
                except (TypeError, ValueError):
                    rvol = 1.0
                rvol_factor = max(rvol, 0.5)
                delta_threshold = BREAKOUT_RETEST_DELTA_BASE * rvol_factor
                finish_threshold = BREAKOUT_RETEST_FINISH_BASE * rvol_factor

                delta = bar.get("delta_bar", 0.0) or 0.0
                finish = bar.get("finish_strength", 0.0) or 0.0
                try:
                    delta = float(delta); finish = float(finish)
                except (TypeError, ValueError):
                    delta = 0.0; finish = 0.0

                if state.side_break == "SHORT":
                    rejection_ok = (delta < -delta_threshold) and (finish < -finish_threshold)
                else:
                    rejection_ok = (delta > delta_threshold) and (finish > finish_threshold)

                if not rejection_ok:
                    continue   # retest sans rejection coherent : continue d'attendre

                # ENTRY confirmee
                state.state = "DONE"
                state.retest_idx = bar_idx
                state.retest_price = close
                self.stats["n_retest_entry"] += 1

                # FIX code-reviewer P3 (03/05) : emit event RETEST_ENTRY pour
                # persister les wins symetriquement aux fails (CRUSH/TIMEOUT).
                self._pending_events.append(BreakoutRetestEvent(
                    event_type="RETEST_ENTRY",
                    state_id=state.state_id,
                    symbol=symbol,
                    level_name=state.level_name,
                    side_break=state.side_break,
                    payload={
                        "side": state.side_break,
                        "entry_price": close,
                        "n_bars_touch_to_retest": bar_idx - state.touch_bar_idx,
                        "retest_dist_signed": dist_signed,
                        "delta_at_retest": delta,
                        "finish_at_retest": finish,
                        "rvol_at_retest": rvol,
                        "acceptance_score": state.acceptance_score,
                        "acceptance_bars_data": list(state.acceptance_bars_data),
                        "level_price": state.level_price,
                        "touch_bar_ts": state.touch_bar_ts,
                        "touch_price": state.touch_price,
                    },
                ))

                signal = BreakoutRetestSignal(
                    state_id=state.state_id,
                    symbol=symbol,
                    level_name=state.level_name,
                    side=state.side_break,
                    entry_price=close,
                    entry_bar_ts=bar_ts,
                    touch_bar_ts=state.touch_bar_ts,
                    touch_price=state.touch_price,
                    accepted_at_bar_ts=bar_ts,
                    retest_bar_ts=bar_ts,
                    n_bars_touch_to_retest=bar_idx - state.touch_bar_idx,
                    retest_dist_signed=dist_signed,
                    acceptance_score=state.acceptance_score,
                    snapshot_acceptance=list(state.acceptance_bars_data),
                    snapshot_retest={
                        "bar_idx": bar_idx,
                        "bar_ts": bar_ts,
                        "close": close,
                        "dist_signed": dist_signed,
                        "delta_bar": delta,
                        "finish_strength": finish,
                        "rvol": rvol,
                        "delta_threshold_used": delta_threshold,
                        "finish_threshold_used": finish_threshold,
                    },
                )
                keys_to_clean.append(key)
                # Politique 1 entry/bar (commentaire reformule selon code-reviewer m-1)
                break

        # Cleanup states DONE
        for k in keys_to_clean:
            self._states.pop(k, None)

        return signal

    def consume_events(self) -> list[BreakoutRetestEvent]:
        """Recupere et clear les events generes depuis le dernier appel.

        FIX #3 : appele par mp_engine apres chaque update_on_bar pour emettre
        les codes log BOT3_BREAKOUT_* (state machine reste pure).
        """
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_active_states(self, symbol: Optional[str] = None) -> dict:
        """Retourne dict des states actifs (pour state.json dashboard)."""
        out = {}
        for key, state in self._states.items():
            if symbol is not None and state.symbol != symbol:
                continue
            if state.state == "DONE":
                continue
            out[f"{key[0]}::{key[1]}"] = {
                "state": state.state,
                "symbol": state.symbol,
                "level_name": state.level_name,
                "side_break": state.side_break,
                "touch_bar_ts": state.touch_bar_ts,
                "touch_price": state.touch_price,
                "level_price": state.level_price,
                "n_acceptance_bars_seen": state.n_acceptance_bars_seen,
                "acceptance_score": round(state.acceptance_score, 2),
                "accepted_at_idx": state.accepted_at_idx,
                "retest_deadline_idx": state.retest_deadline_idx,
                "state_id": state.state_id,
            }
        return out

    def stats_snapshot(self) -> dict:
        """Stats cumul session pour audit."""
        return dict(self.stats)
