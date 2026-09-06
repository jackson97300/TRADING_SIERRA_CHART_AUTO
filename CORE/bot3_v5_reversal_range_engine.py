"""bot3_v5_reversal_range_engine.py — Moteur Bot 3 v5 Reversal-Range.

REMPLACE le cerveau v4 (fade niveaux, PF 0.66 reel / 0.276 live, KILL 28/05).
Interface IDENTIQUE a Bot3V4Engine (process_bar -> Optional[EntryDecisionV4]) :
branchable dans bot3_v4_data_driven_paper.py sans toucher l'orchestrateur.

# Edge (audit 140j databento NQ, 16/06/2026)

Mecanisme : MEAN-REVERSION vers le VWAP du jour, en jour de RANGE uniquement.
Validation empirique (TP=VWAP, couts 2t, walk-forward 6 folds) :
  - Base (ext>=60t + range) : PF 1.07, WF 5/6 folds, n=15944  (mince mais valide)
  - + confirm delta_bar (premium) : PF 1.50 sur 32j (feature recente, non
    validable historiquement -> le PAPER la valide forward)

Decisions de design VALIDEES par backtest (PAS supposees) :
  1. SL SYMETRIQUE NON-CAPPE (= distance d'extension). Capper DETRUIT l'edge :
     cap 30t -> PF 0.86, cap 40t -> 0.91, uncapped -> 1.05/1.50. La reversion a
     besoin de respirer (overshoot avant retour). Verifie 16/06 (regle Plan C).
  2. FILTRE RANGE OBLIGATOIRE : range PF 1.07 vs trend PF 0.90 (Dalton). C'est
     `ctx_trend_day_score` < 0.4 qui FAIT l'edge.
  3. CONFIRM delta_bar = filtre PREMIUM (Jackson : "que les signaux premium").
     Reduit la frequence a ~1.2 trade/j et porte PF a 1.50 (a valider forward).

# Anti-pattern : ce qui a tue les versions precedentes

Pas de fade aveugle (v4 : PF 0.76-0.98 sur 140j). Pas de confluence BN (EV ~0,
6 angles refutes 16/06). Pas de filtres Pattern 11 curve-fites (N=9-51). Le SEUL
edge robuste sur NQ intraday = mean-reversion en range. Tous les PF>1.3 testes a
la main se sont effondres en walk-forward (concentration/petit echantillon).

Auteur : MIA Trading V2 — v5.0 (2026-06-16, audit reversal-range 140j).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

# Reutilise les types/constantes/dataclass de sortie du moteur v4 (interface
# stable consommee par l'orchestrateur paper).
try:
    from bot3_v4_data_driven_engine import (
        EntryDecisionV4,
        TriggerLevelV4,
        TICK_BY_SYMBOL,
        SIDE_LONG,
        SIDE_SHORT,
    )
except ImportError:  # lance depuis racine projet
    from CORE.bot3_v4_data_driven_engine import (  # type: ignore
        EntryDecisionV4,
        TriggerLevelV4,
        TICK_BY_SYMBOL,
        SIDE_LONG,
        SIDE_SHORT,
    )

TP_MODE_VWAP = "VWAP"


@dataclass
class Bot3V5Params:
    """Configuration Bot 3 v5 Reversal-Range (defaults = design valide 16/06)."""
    # Seuil d'extension minimal vs VWAP (en ticks). Edge croit avec extension ;
    # 60t = plancher ou EV passe positive (audit : 20t -0.7, 40t -0.3, 60t +0.4).
    ext_min_ticks: float = 60.0
    # Jour de range si ctx_trend_day_score < ce seuil (range PF 1.07 vs trend 0.90).
    trend_day_max: float = 0.4
    # Filtre PREMIUM : delta_bar aligne (LONG: >0, SHORT: <0). True = premium.
    require_delta_confirm: bool = True
    # SL : symetrique a l'extension, NON-cappe. Safety max anti-degenere seulement.
    sl_safety_max_ticks: float = 250.0
    # Cooldown entre signaux (barres). Anti re-emission pendant extension prolongee.
    cooldown_bars: int = 30
    # asym_prob documentaire (PF empirique 1.07-1.50 selon premium).
    asym_prob_doc: float = 0.55


def build_v5_trigger() -> List[TriggerLevelV4]:
    """Trigger unique reversal VWAP (l'extension definit le side dynamiquement)."""
    return [TriggerLevelV4(
        name="VWAP_D_REVERSAL", side="DYNAMIC",
        dist_col="dist_vwap_d_pct", family="VWAP", asym_prob=0.55,
    )]


class Bot3V5ReversalRangeEngine:
    """Moteur reversal-range. 1 instance par symbol. Interface = Bot3V4Engine.

    process_bar(row, bar_ts_iso, bar_day) -> EntryDecisionV4 | None.
    PURE LOGIC : aucun I/O, aucun DTC. L'orchestrateur paper gere execution,
    cooldown post-trade, persistance, 1-position-max.
    """

    def __init__(
        self,
        symbol: str,
        triggers: Optional[List[TriggerLevelV4]] = None,
        params: Optional[Bot3V5Params] = None,
        log_fn: Optional[Any] = None,
    ):
        assert symbol in TICK_BY_SYMBOL, (
            f"Symbol {symbol} unsupported (allowed: {list(TICK_BY_SYMBOL.keys())})"
        )
        self.symbol = symbol
        self.params = params or Bot3V5Params()
        self.tick_size = TICK_BY_SYMBOL[symbol]
        self.log_fn = log_fn
        # triggers expose pour compat orchestrateur (snapshot/logging v4).
        self.triggers = triggers or build_v5_trigger()

        # Etat
        self._bar_idx: int = -1
        self._current_day: Optional[str] = None
        self._last_signal_bar_idx: int = -10_000

        # Stats lifetime (tracabilite — regle logs 01/05)
        self._n_bars_processed: int = 0
        self._n_ext_reached: int = 0          # extension >= seuil
        self._n_filtered_trend: int = 0       # rejet jour de tendance
        self._n_filtered_confirm: int = 0     # rejet pas de confirm delta_bar
        self._n_filtered_cooldown: int = 0
        self._n_filtered_levels: int = 0      # sl/tp incoherents
        self._n_entries_emitted: int = 0
        self._n_day_resets: int = 0

    # ─── Public API (miroir Bot3V4Engine) ──────────────────────────────────

    def reset_day(self, new_day: str) -> int:
        active = 1 if self._last_signal_bar_idx > -10_000 else 0
        self._bar_idx = -1
        self._current_day = new_day
        self._last_signal_bar_idx = -10_000
        self._n_day_resets += 1
        return active

    def process_bar(
        self,
        row: Union[Dict[str, Any], Any],
        bar_ts_iso: str,
        bar_day: str,
    ) -> Optional[EntryDecisionV4]:
        """Process une barre live. EntryDecisionV4 si setup reversal-range valide."""
        if bar_day != self._current_day:
            self.reset_day(bar_day)
        self._bar_idx += 1
        self._n_bars_processed += 1

        close = self._safe_float(self._row_get(row, "close"))
        vwap = self._safe_float(self._row_get(row, "vwap_d"))
        if close is None or close <= 0 or vwap is None or vwap <= 0:
            return None

        # 1. Extension vs VWAP (en ticks)
        ext_ticks = abs(close - vwap) / self.tick_size
        if ext_ticks < self.params.ext_min_ticks:
            return None
        self._n_ext_reached += 1

        # 2. Side dynamique : etendu SOUS vwap -> LONG (revert up) ; au-dessus -> SHORT
        if close < vwap:
            side = SIDE_LONG
        elif close > vwap:
            side = SIDE_SHORT
        else:
            return None

        # 3. Filtre RANGE (l'edge). trend_day_score absent -> rejet fail-safe.
        ts = self._safe_float(self._row_get(row, "ctx_trend_day_score"))
        if ts is None or ts >= self.params.trend_day_max:
            self._n_filtered_trend += 1
            return None

        # 4. Confirm PREMIUM : delta_bar aligne au sens du reversal.
        if self.params.require_delta_confirm:
            db = self._safe_float(self._row_get(row, "delta_bar"))
            if db is None:
                self._n_filtered_confirm += 1
                return None
            if (side == SIDE_LONG and db <= 0) or (side == SIDE_SHORT and db >= 0):
                self._n_filtered_confirm += 1
                return None

        # 5. Cooldown anti re-emission
        if self._bar_idx - self._last_signal_bar_idx < self.params.cooldown_bars:
            self._n_filtered_cooldown += 1
            return None

        # 6. SL/TP. TP = VWAP (cible reversion). SL symetrique = distance extension,
        #    NON-cappe (cap detruit l'edge, verifie 16/06). Safety max anti-degenere.
        tp_price = vwap
        sl_dist_ticks = min(ext_ticks, self.params.sl_safety_max_ticks)
        sl_dist = sl_dist_ticks * self.tick_size
        if side == SIDE_LONG:
            sl_price = close - sl_dist
            levels_ok = sl_price < close < tp_price
        else:
            sl_price = close + sl_dist
            levels_ok = tp_price < close < sl_price
        if not levels_ok:
            self._n_filtered_levels += 1
            return None

        # 7. Emission
        self._last_signal_bar_idx = self._bar_idx
        self._n_entries_emitted += 1
        return EntryDecisionV4(
            side=side,
            level_name="VWAP_D_REVERSAL",
            level_family="VWAP",
            asym_prob=self.params.asym_prob_doc,
            entry_close=close,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_ticks=int(round(sl_dist_ticks)),
            swing_used=False,
            tp_mode=TP_MODE_VWAP,
            vpoc_value=None,
            bar_idx=self._bar_idx,
            bar_ts=bar_ts_iso,
        )

    def get_trigger_snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {
            "VWAP_D_REVERSAL": {
                "prev_in_zone": False,
                "last_touch_bar_idx": self._last_signal_bar_idx,
                "touches_today": self._n_entries_emitted,
            }
        }

    def get_stats(self) -> Dict[str, int]:
        return {
            "n_bars_processed": self._n_bars_processed,
            "n_ext_reached": self._n_ext_reached,
            "n_filtered_trend": self._n_filtered_trend,
            "n_filtered_confirm": self._n_filtered_confirm,
            "n_filtered_cooldown": self._n_filtered_cooldown,
            "n_filtered_levels": self._n_filtered_levels,
            "n_entries_emitted": self._n_entries_emitted,
            "n_day_resets": self._n_day_resets,
        }

    # ─── Helpers (memes conventions que v4) ────────────────────────────────

    @staticmethod
    def _row_get(row: Union[Dict[str, Any], Any], key: str) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return getattr(row, key, None)

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):  # NaN/Inf
            return None
        return f
