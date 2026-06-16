"""Signal engine Bot BN V4 - wrap BNV4Engine + rolling window deque.

Architecture :
  - Maintient un deque(maxlen=500) de bars par symbole
  - A chaque on_bar(row), append + appel BNV4Engine.detect_setup
  - Renvoie un SignalDecision agnostique consomme par main.py

Le moteur pur CORE.bn_v4_engine.BNV4Engine est inchange (logique unifiee
backtest/live PF 4.66 NQ A++ Jackson 23/05).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable

import pandas as pd

from CORE.bn_v4_engine import BNV4Engine, BNV4Params, GRADE_THRESHOLDS, TICK_SIZE
from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.sierra_compat import enrich_sierra_bar_for_bn_v4


@dataclass
class SignalDecision:
    """Verdict signal_engine pour une bar."""
    tradable: bool = False
    direction: Optional[str] = None  # "long" / "short" / None
    setup: Optional[dict] = None
    skip_reason: str = ""
    # Hypothetical : on a un setup mais session/grade non-tradable (audit)
    hypothetical: bool = False
    # Grade calcule meme si non-tradable (pour shadow log A/B)
    grade: Optional[str] = None


class SignalEngine:
    """Maintient une rolling window par symbole + wrapper BNV4Engine.

    Pattern :
      eng = SignalEngine(symbol="NQ", cfg=cfg, log_fn=log_fn)
      while running:
          bar = data_source.read_last_bar()
          decision = eng.on_bar(bar)
          if decision.tradable:
              router.send_bracket(decision)
    """

    def __init__(
        self,
        symbol: str,
        cfg: BotBNV4Config,
        log_fn: Optional[Callable] = None,
    ):
        self.symbol = symbol.upper()
        self.cfg = cfg
        self.log_fn = log_fn  # injecte par main.py (emit BOTBN_*)

        # Bars rolling window : N=500 = couvre lookback 240 + marge
        self._buf: deque = deque(maxlen=cfg.SIGNAL_ROLLING_WINDOW_BARS)

        # Construit BNV4Params depuis BotBNV4Config (mapping explicite)
        params = BNV4Params(
            prox_pct=cfg.BOTTOM_ZONE_PROXIMITY_PCT,
            n_levels_min=cfg.BOTTOM_ZONE_N_LEVELS_MIN,
            grade_min=cfg.GRADE_MIN,
            trend_lookback=cfg.TREND_LOOKBACK_BARS,
            trend_slope_min=cfg.TREND_SLOPE_THRESHOLD,
            require_open_window=cfg.REQUIRE_OPEN_WINDOW,
            require_long_trend_aligned=cfg.REQUIRE_LONG_TREND_ALIGNED,
            timeout_bars=cfg.TIMEOUT_BARS,
            max_risk_ticks=cfg.MAX_RISK_TICKS,
            min_risk_ticks=cfg.MIN_RISK_TICKS,
            # Observation grade : si shadow_log activated, on observe grade A (down 1
            # cran depuis A++). Permet log_decision_jsonl en mode "OBSERVE".
            observation_grade_min=(
                "A" if (cfg.SHADOW_LOG_GRADES_AB and cfg.GRADE_MIN == "A++") else None
            ),
        )
        self._params = params
        self.engine = BNV4Engine(
            params=params,
            symbol=self.symbol,
            log_fn=log_fn,
        )

    def is_ready(self) -> bool:
        """True si rolling window contient assez de bars pour evaluer
        trend_lookback (60) + trend_long_lookback (240)."""
        return len(self._buf) >= max(
            self._params.trend_lookback,
            self._params.trend_long_lookback,
        )

    def n_bars(self) -> int:
        return len(self._buf)

    def on_bar(self, raw_bar: dict) -> SignalDecision:
        """Ingere une nouvelle bar et evalue setup.

        Args:
            raw_bar : dict depuis sierra_enriched JSONL (615+ fields)

        Returns:
            SignalDecision : verdict tradable + setup info.
        """
        if not raw_bar:
            return SignalDecision(skip_reason="EMPTY_BAR")

        # Enrich features manquantes (5 dist_*_pct + big_buy_dominance)
        enriched = enrich_sierra_bar_for_bn_v4(dict(raw_bar))

        # Append a la rolling window
        self._buf.append(enriched)

        if not self.is_ready():
            return SignalDecision(skip_reason=f"WARMUP_{len(self._buf)}/{self._params.trend_long_lookback}")

        # Construire DataFrame depuis le deque (cost ~0.5ms pour 500 rows)
        # On garde un DataFrame complet a chaque tick - alternative serait
        # d'utiliser un DF persistent en rolling, mais l'overhead deque->df
        # reste negligeable sur 500 bars/tick toutes les 15s.
        df = pd.DataFrame(list(self._buf))
        i = len(df) - 1

        # Direction : selon DIRECTION_MODE config
        directions: tuple
        if self.cfg.DIRECTION_MODE == "long":
            directions = ("long",)
        elif self.cfg.DIRECTION_MODE == "short":
            directions = ("short",)
        else:  # "both"
            directions = ("long", "short")

        # Test chaque direction. Premiere qui fire wins (rare collision).
        for direction in directions:
            try:
                setup = self.engine.detect_setup(df, i, direction)
            except Exception as exc:  # noqa: BLE001
                # OHLC fail-loud peut raise ValueError - on capture pour log
                return SignalDecision(
                    skip_reason=f"DETECT_EXCEPTION:{type(exc).__name__}:{exc}",
                )
            if setup is None:
                continue
            # Setup detecte
            mode = setup.get("mode", "TRADE")
            grade = setup.get("grade", "?")
            if mode == "TRADE":
                return SignalDecision(
                    tradable=True,
                    direction=direction,
                    setup=setup,
                    grade=grade,
                )
            else:
                # OBSERVE / OBSERVE_WINDOW : pas de trade reel, log hypo
                return SignalDecision(
                    tradable=False,
                    direction=direction,
                    setup=setup,
                    hypothetical=True,
                    grade=grade,
                    skip_reason=f"OBSERVE_MODE:{mode}",
                )

        return SignalDecision(skip_reason="NO_SETUP")

    def get_last_bar(self) -> Optional[dict]:
        """Snapshot derniere bar du buffer (read-only)."""
        if not self._buf:
            return None
        return dict(self._buf[-1])
