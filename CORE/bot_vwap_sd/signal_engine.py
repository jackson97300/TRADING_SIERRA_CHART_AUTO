"""Signal engine Bot 5 VWAP-SD : 4 setups reversion bandes VWAP daily.

Architecture :
  - Stateless eval bar par bar (pas de rolling window required vs BN V4)
  - on_bar(raw_bar) -> SignalDecision
  - 4 setups testes dans l'ordre A, B, C, D - premier qui fire wins

Edge fundamental : mean reversion VWAP daily standard deviation bands.
Market makers short gamma fadent overbought (SD2u-SD3u) et oversold (SD2d-SD3d).
Microstructure documentee Dalton/Hurst.

Convention features Sierra DMP :
  dist_vwap_d_sd2u = SD2u_price - close (POSITIF si SD2u au-dessus du close)
  -> "close dans zone SD2u-SD3u" = dist_vwap_d_sd2u < 0 AND dist_vwap_d_sd3u > 0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Callable

from CORE.bot_vwap_sd.config import VwapSdConfig

# FIX review #1 CRITIQUE 20/06 : importer get_tick_size depuis source unique
# (cf .claude/rules/tick-size-policy.md). Anti-pattern variable locale hardcodee.
try:
    from CORE.constants import get_tick_size
except ImportError:
    from constants import get_tick_size  # type: ignore


# FIX review #6 IMPORTANT 20/06 : frozen=True pour coherence avec VwapSdConfig
# et eviter mutation accidentelle apres retour on_bar (race condition).
@dataclass(frozen=True)
class SignalDecision:
    """Verdict signal_engine pour une bar."""
    tradable: bool = False
    direction: Optional[str] = None  # "long" / "short" / None
    setup_id: Optional[str] = None   # "A" / "B" / "C" / "D" / None
    tp_ticks: int = 0
    sl_ticks: int = 0
    skip_reason: str = ""
    # Shadow : detecte mais pas trade (Setup D n=13 insuffisant, B/C edge marginal)
    shadow: bool = False
    # Snapshot features cles pour log/debug (immutable via field default_factory)
    snapshot: Optional[dict] = None


class VwapSdSignalEngine:
    """Engine VWAP-SD reversion.

    Pattern :
      eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg, log_fn=log_fn)
      decision = eng.on_bar(bar)
      if decision.tradable:
          router.send_bracket(decision)
    """

    def __init__(
        self,
        symbol: str,
        cfg: VwapSdConfig,
        log_fn: Optional[Callable] = None,
    ):
        self.symbol = symbol.upper()
        self.cfg = cfg
        self.log_fn = log_fn  # injecte par main.py

    def on_bar(self, raw_bar: dict) -> SignalDecision:
        """Ingere une nouvelle bar et evalue setup VWAP-SD."""
        if not raw_bar:
            return SignalDecision(skip_reason="EMPTY_BAR")

        # Verification RTH session (Setup VWAP-SD = RTH US only)
        if not raw_bar.get("is_in_us_cash", False):
            return SignalDecision(skip_reason="NOT_RTH")

        sd2u = raw_bar.get("dist_vwap_d_sd2u")
        sd3u = raw_bar.get("dist_vwap_d_sd3u")
        sd2d = raw_bar.get("dist_vwap_d_sd2d")
        sd3d = raw_bar.get("dist_vwap_d_sd3d")
        slope = raw_bar.get("vwap_slope_30")

        # Garde-fou : features manquantes -> skip (pas de fallback silencieux)
        if any(v is None for v in (sd2u, sd3u, sd2d, sd3d)):
            return SignalDecision(skip_reason="MISSING_VWAP_SD_FEATURES")

        snapshot = {
            "close": raw_bar.get("close"),
            "dist_vwap_d_sd2u": sd2u,
            "dist_vwap_d_sd3u": sd3u,
            "dist_vwap_d_sd2d": sd2d,
            "dist_vwap_d_sd3d": sd3d,
            "vwap_slope_30": slope,
            "session_segment": raw_bar.get("session_segment"),
        }

        # =====================================================
        # SETUP A : NQ SHORT - close ENTRE SD2u et SD3u + confluence niveau
        # Empirique 8j : baseline PF 2.26 / avec confluence 500t PF 26.00
        # Filtre confluence : >=1 niveau resistance au-dessus PROCHE
        # Niveaux : mq_call (gamma wall), prev_vah, vwap_w_sd2u, swing_high
        # =====================================================
        if (
            self.symbol == "NQ"
            and self.cfg.SETUP_A_ENABLED
            and sd2u < 0  # close au-dessus de SD2u
            and sd3u > 0  # close en-dessous de SD3u
        ):
            # Filtre anti-trend-day (decouverte empirique 20/06) :
            # IB > N ATR = volatility expansion = trend day en cours
            # Sur 8j NQ : jour 12/06 (ib_atr=2.11) = seul jour problematique
            if self.cfg.SETUP_A_ANTITREND_ENABLED:
                ib_atr = raw_bar.get("ib_range_atr")
                if ib_atr is not None and ib_atr >= self.cfg.SETUP_A_MAX_IB_RANGE_ATR:
                    return SignalDecision(
                        tradable=False,
                        direction="short",
                        setup_id="A",
                        tp_ticks=self.cfg.SETUP_A_TP_TICKS,
                        sl_ticks=self.cfg.SETUP_A_SL_TICKS,
                        skip_reason=f"TREND_DAY_IB_EXPANSION:{ib_atr:.2f}",
                        snapshot={**snapshot, "ib_range_atr": ib_atr},
                    )

            # Filtre confluence niveau institutionnel (resistance au-dessus)
            confluence_ok = True
            confluence_levels = []
            if self.cfg.SETUP_A_CONFLUENCE_ENABLED:
                thresh = self.cfg.SETUP_A_CONFLUENCE_THRESHOLD_TICKS
                # Convention DMP : dist = level - close. Positif = level au-dessus.
                # Pour SHORT on cherche resistance AU-DESSUS PROCHE.
                candidates = {
                    "mq_call": raw_bar.get("dist_mq_call"),
                    "prev_vah": raw_bar.get("dist_prev_vah"),
                    "vwap_w_sd2u": raw_bar.get("dist_vwap_w_sd2u"),
                    "swing_high": raw_bar.get("dist_swing_high"),
                }
                # FIX review #3 IMPORTANT 20/06 : detecter cas TOUTES candidates None
                # (pipeline DMP bug) et emit MAJEUR au lieu de silent fallback.
                non_null = {k: v for k, v in candidates.items() if v is not None}
                if not non_null:
                    if self.log_fn is not None:
                        try:
                            self.log_fn(
                                "BOTVWAPSD_CONFLUENCE_FEATURES_ALL_NONE",
                                sym=self.symbol,
                                missing_features=list(candidates.keys()),
                            )
                        except Exception:  # noqa: BLE001
                            pass
                    return SignalDecision(
                        tradable=False,
                        direction="short",
                        setup_id="A",
                        tp_ticks=self.cfg.SETUP_A_TP_TICKS,
                        sl_ticks=self.cfg.SETUP_A_SL_TICKS,
                        skip_reason="CONFLUENCE_FEATURES_ALL_NONE",
                        snapshot=snapshot,
                    )
                # FIX review #1 CRITIQUE 20/06 : tick_size via helper (source unique)
                tick = get_tick_size(self.symbol)
                thresh_points = thresh * tick
                for lvl_name, dist in non_null.items():
                    if 0 < dist < thresh_points:
                        confluence_levels.append(f"{lvl_name}={dist:.0f}pts")
                confluence_ok = len(confluence_levels) > 0

            if not confluence_ok:
                # Detecte mais skip : pas de confluence niveau (n'est PAS un bug,
                # c'est un filtre par design : edge marche seulement avec confluence)
                return SignalDecision(
                    tradable=False,
                    direction="short",
                    setup_id="A",
                    tp_ticks=self.cfg.SETUP_A_TP_TICKS,
                    sl_ticks=self.cfg.SETUP_A_SL_TICKS,
                    skip_reason="NO_RESISTANCE_CONFLUENCE",
                    snapshot={**snapshot, "confluence_levels": []},
                )

            return SignalDecision(
                tradable=True,
                direction="short",
                setup_id="A",
                tp_ticks=self.cfg.SETUP_A_TP_TICKS,
                sl_ticks=self.cfg.SETUP_A_SL_TICKS,
                snapshot={**snapshot, "confluence_levels": confluence_levels},
            )

        # =====================================================
        # SETUP B : NQ LONG - close ENTRE SD2d et SD3d
        # VERDICT EMPIRIQUE 20/06 : PF 0.52, EV -8.2t, -$304/8j -> EDGE INVERSE LIVE
        # DESACTIVE par defaut. Mode SHADOW collecte pour reevaluation.
        # =====================================================
        if (
            self.symbol == "NQ"
            and sd2d > 0  # close en-dessous de SD2d
            and sd3d < 0  # close au-dessus de SD3d
        ):
            # FIX review #2 CRITIQUE 20/06 : log distinct DISABLED vs SHADOW
            # pour traceability operationnelle (sinon Jackson ne distingue pas).
            if not self.cfg.SETUP_B_ENABLED:
                skip_reason = "SETUP_B_DISABLED"
                is_shadow = True
            elif self.cfg.SETUP_B_SHADOW:
                skip_reason = "SHADOW_EDGE_INVERSE_LIVE"
                is_shadow = True
            else:
                skip_reason = ""
                is_shadow = False
            return SignalDecision(
                tradable=not is_shadow,
                direction="long",
                setup_id="B",
                tp_ticks=self.cfg.SETUP_B_TP_TICKS,
                sl_ticks=self.cfg.SETUP_B_SL_TICKS,
                shadow=is_shadow,
                skip_reason=skip_reason,
                snapshot=snapshot,
            )

        # =====================================================
        # SETUP C : ES LONG - close ENTRE SD2d et SD3d ET slope >= 0
        # VERDICT EMPIRIQUE 20/06 : PF 1.18, EV +1.0t, +$42/8j -> MARGINAL
        # DESACTIVE par defaut. Mode SHADOW pour reevaluation 30j.
        # CAVEAT : concentration 31/44 le 18/06 (70%) -> monitor si reactive.
        # =====================================================
        if (
            self.symbol == "ES"
            and sd2d > 0
            and sd3d < 0
            and slope is not None
            and slope >= self.cfg.SETUP_C_MIN_SLOPE
        ):
            # FIX review #2 CRITIQUE 20/06 : log distinct DISABLED vs SHADOW
            if not self.cfg.SETUP_C_ENABLED:
                skip_reason = "SETUP_C_DISABLED"
                is_shadow = True
            elif self.cfg.SETUP_C_SHADOW:
                skip_reason = "SHADOW_MARGINAL_EDGE"
                is_shadow = True
            else:
                skip_reason = ""
                is_shadow = False
            return SignalDecision(
                tradable=not is_shadow,
                direction="long",
                setup_id="C",
                tp_ticks=self.cfg.SETUP_C_TP_TICKS,
                sl_ticks=self.cfg.SETUP_C_SL_TICKS,
                shadow=is_shadow,
                skip_reason=skip_reason,
                snapshot=snapshot,
            )

        # =====================================================
        # SETUP D : ES SHORT - close ENTRE SD2u et SD3u
        # SHADOW : n=13 insuffisant statistiquement (market-analyst)
        # Log mais ne trade PAS (sauf SETUP_D_ENABLED=True explicit)
        # =====================================================
        if (
            self.symbol == "ES"
            and sd2u < 0
            and sd3u > 0
        ):
            # FIX review #2 CRITIQUE 20/06 : log distinct DISABLED vs SHADOW
            if not self.cfg.SETUP_D_ENABLED:
                skip_reason = "SETUP_D_DISABLED"
                is_shadow = True
            elif self.cfg.SETUP_D_SHADOW:
                skip_reason = "SHADOW_INSUFFICIENT_N"
                is_shadow = True
            else:
                skip_reason = ""
                is_shadow = False
            return SignalDecision(
                tradable=not is_shadow,
                direction="short",
                setup_id="D",
                tp_ticks=self.cfg.SETUP_D_TP_TICKS,
                sl_ticks=self.cfg.SETUP_D_SL_TICKS,
                shadow=is_shadow,
                skip_reason=skip_reason,
                snapshot=snapshot,
            )

        return SignalDecision(skip_reason="NO_SETUP")

    def emit_decision_log(self, decision: SignalDecision, raw_bar: dict) -> None:
        """FIX review #5 IMPORTANT 20/06 : centralise emit log_decision_jsonl.

        Le main.py doit appeler cette methode apres chaque on_bar pour eviter
        que log_decision_jsonl soit orphelin (pattern VALIDATION_MISS).

        Inject ici car le main.py peut etre incomplete encore - le test
        d'integration peut verifier que ce methode est bien appele.
        """
        if not decision.setup_id:
            return
        try:
            from CORE.bot_vwap_sd.logger import log_decision_jsonl
            log_decision_jsonl(
                bar_ts=str(raw_bar.get("ts_event", "")),
                symbol=self.symbol,
                direction=decision.direction,
                setup_id=decision.setup_id,
                tradable=decision.tradable,
                skip_reason=decision.skip_reason or "",
                session_phase=str(raw_bar.get("session_segment", "")),
                shadow=decision.shadow,
                snapshot=decision.snapshot,
            )
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("bot_vwap_sd").warning(
                f"emit_decision_log fail: {e}"
            )

    def describe_setups(self) -> dict:
        """Retourne description des setups actifs (debug/dashboard)."""
        return {
            "A": {
                "symbol": "NQ", "direction": "short",
                "enabled": self.cfg.SETUP_A_ENABLED,
                "trigger": "close ENTRE SD2u et SD3u (overbought reversion)",
                "tp_ticks": self.cfg.SETUP_A_TP_TICKS,
                "sl_ticks": self.cfg.SETUP_A_SL_TICKS,
            },
            "B": {
                "symbol": "NQ", "direction": "long",
                "enabled": self.cfg.SETUP_B_ENABLED,
                "trigger": "close ENTRE SD2d et SD3d (oversold reversion)",
                "tp_ticks": self.cfg.SETUP_B_TP_TICKS,
                "sl_ticks": self.cfg.SETUP_B_SL_TICKS,
            },
            "C": {
                "symbol": "ES", "direction": "long",
                "enabled": self.cfg.SETUP_C_ENABLED,
                "trigger": "close ENTRE SD2d et SD3d AND vwap_slope_30 >= 0",
                "tp_ticks": self.cfg.SETUP_C_TP_TICKS,
                "sl_ticks": self.cfg.SETUP_C_SL_TICKS,
            },
            "D": {
                "symbol": "ES", "direction": "short",
                "enabled": self.cfg.SETUP_D_ENABLED,
                "shadow": self.cfg.SETUP_D_SHADOW,
                "trigger": "close ENTRE SD2u et SD3u (SHADOW n insuffisant)",
                "tp_ticks": self.cfg.SETUP_D_TP_TICKS,
                "sl_ticks": self.cfg.SETUP_D_SL_TICKS,
            },
        }
