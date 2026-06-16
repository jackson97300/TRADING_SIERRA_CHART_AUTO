"""Signal engine Bot Mean Revert VWAP.

Logique mean reversion (sweep v2 valide) :
  Entry LONG :  dist_vwap_d_sdNd_pct <= -threshold  + filtres regime ES/NQ
  Entry SHORT : dist_vwap_d_sdNu_pct >=  threshold  + filtres regime ES/NQ

SL/TP : SL fixe ticks (20 ES / 35 NQ), TP = SL * RR (1.5).

Reference : detect_mean_revert_signal de CORE/research/sweep_bot_mean_revert_v2.py
Pattern : encapsule dans SignalEngine pour reuse propre dans le bot prod.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from CORE.bot_mean_revert.config import BotMRConfig

try:
    from CORE.constants import get_tick_size
except ImportError:  # pragma: no cover - fallback flat sys.path
    from constants import get_tick_size  # type: ignore


# Pre-open US bruit (sweep ES : skip_preopen_us=True ameliore PF)
PREOPEN_US_START_MIN = 11 * 60 + 30  # 11:30 UTC
PREOPEN_US_END_MIN = 13 * 60 + 30    # 13:30 UTC


def _f(x, default=0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _b(x) -> bool:
    if x is True or x == 1 or x == "true":
        return True
    return False


@dataclass(frozen=True)
class SignalResult:
    """Resultat evaluation signal mean revert."""
    tradable: bool
    direction: Optional[str] = None  # "LONG" / "SHORT" / None
    skip_reason: str = ""
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    sl_ticks: int = 0
    tp_ticks: int = 0
    rr_ratio: float = 0.0
    sd_level: str = ""
    signal_id: str = ""
    bar_ts: Optional[int] = None
    # Contexte enrichi pour audit JSONL
    vwap_slope_30: float = 0.0
    vix_level: float = 0.0
    rvol_zscore: float = 0.0
    session_id: str = ""
    ctx_trend_day_score: float = 0.0


class SignalEngine:
    """Moteur de detection mean revert + sizing SL/TP."""

    def __init__(self, symbol: str, cfg: BotMRConfig):
        self.symbol = symbol.upper()
        self.cfg = cfg
        self._cooldown_until_ts = 0.0
        # Compteur bars pour cooldown_bars (incrementations a chaque evaluate)
        self._bars_since_last_trade = cfg.COOLDOWN_BARS  # ready immediat au boot
        self._traded_signal_ids: set = set()

    def register_trade(self, signal_id: str) -> None:
        """A appeler apres ordre envoye : reset cooldown + lock signal_id."""
        if signal_id:
            self._traded_signal_ids.add(signal_id)
        self._bars_since_last_trade = 0

    def _bump_bar_counter(self) -> None:
        self._bars_since_last_trade += 1

    def _check_session(self, bar: dict) -> tuple[bool, str, str]:
        """Verifie si la session est tradable pour ce symbole.

        Returns: (allowed, session_phase, reason)
        """
        session_id = (bar.get("session_id") or "").upper()
        is_in_us = bool(bar.get("is_in_us_cash"))
        allowed_sessions = self.cfg.tradable_sessions(self.symbol)

        # Normalisation phase
        if is_in_us or session_id == "US":
            phase = "US"
        elif session_id == "ASIA":
            phase = "ASIA"
        elif session_id == "LONDON":
            phase = "LONDON"
        elif session_id == "US_AFTER":
            phase = "POST_RTH"
        elif session_id:
            phase = session_id
        else:
            phase = "?"

        if phase not in allowed_sessions:
            return False, phase, f"SESSION_NOT_ALLOWED:{phase}"

        # Pre-open US 11:30-13:30 UTC bruit (uniquement si US session active)
        if self.cfg.SKIP_PREOPEN_US and phase == "US":
            ts_ms = bar.get("ts", 0)
            if ts_ms:
                try:
                    dt_utc = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
                    mins = dt_utc.hour * 60 + dt_utc.minute
                    if PREOPEN_US_START_MIN <= mins < PREOPEN_US_END_MIN:
                        return False, phase, "PREOPEN_US_SKIP"
                except (OSError, ValueError, OverflowError):
                    pass

        return True, phase, ""

    def _apply_regime_filter(
        self,
        direction: str,
        slope_30: float,
        vix: float,
        trend_day_score: float,
    ) -> tuple[bool, str]:
        """Filtre regime asymetrique ES (trend_align) / NQ (contrarian).

        Returns: (allow, reject_reason)
        """
        mode = self.cfg.regime_filter_mode(self.symbol)
        if mode == "off":
            return True, ""

        if mode == "trend_align_es":
            # LONG necessite slope_30 > 0, SHORT slope_30 < 0
            if direction == "LONG" and slope_30 <= 0:
                return False, f"REGIME_TREND_ES_LONG_BLOCKED:slope_30={slope_30:.4f}"
            if direction == "SHORT":
                if slope_30 >= 0:
                    return False, f"REGIME_TREND_ES_SHORT_BLOCKED:slope_30={slope_30:.4f}"
                if self.cfg.VIX_MIN_FOR_SHORT > 0 and vix <= self.cfg.VIX_MIN_FOR_SHORT:
                    return False, f"VIX_TOO_LOW_FOR_SHORT:{vix:.2f}<={self.cfg.VIX_MIN_FOR_SHORT:.2f}"
            return True, ""

        if mode == "contrarian_nq":
            # LONG necessite slope_30 < 0, SHORT slope_30 > 0
            if direction == "LONG" and slope_30 >= 0:
                return False, f"REGIME_CONTRA_NQ_LONG_BLOCKED:slope_30={slope_30:.4f}"
            if direction == "SHORT":
                if slope_30 <= 0:
                    return False, f"REGIME_CONTRA_NQ_SHORT_BLOCKED:slope_30={slope_30:.4f}"
                if trend_day_score > self.cfg.NQ_TREND_DAY_MAX:
                    return False, f"NQ_TREND_DAY_TOO_HIGH:{trend_day_score:.2f}>{self.cfg.NQ_TREND_DAY_MAX:.2f}"
            return True, ""

        return True, ""

    def evaluate(self, bar: dict) -> SignalResult:
        """Evalue la bar courante et retourne un SignalResult.

        Tous les paths emettent un SignalResult (jamais None) avec skip_reason
        explicite pour audit JSONL.
        """
        self._bump_bar_counter()
        bar_ts = bar.get("ts")
        session_id = (bar.get("session_id") or "").upper()
        vwap_slope_30 = _f(bar.get("vwap_slope_30"))
        vix = _f(bar.get("vix_level"))
        rvol_z = _f(bar.get("rvol_zscore"))
        trend_day_score = _f(bar.get("ctx_trend_day_score"))

        base_ctx = {
            "bar_ts": bar_ts,
            "session_id": session_id,
            "vwap_slope_30": vwap_slope_30,
            "vix_level": vix,
            "rvol_zscore": rvol_z,
            "ctx_trend_day_score": trend_day_score,
            "sd_level": self.cfg.SD_LEVEL,
        }

        # 1. Cooldown bars
        if self._bars_since_last_trade < self.cfg.COOLDOWN_BARS:
            return SignalResult(
                tradable=False,
                skip_reason=f"COOLDOWN:{self._bars_since_last_trade}/{self.cfg.COOLDOWN_BARS}",
                **base_ctx,
            )

        # 2. Session
        sess_ok, phase, sess_reason = self._check_session(bar)
        base_ctx["session_id"] = phase
        if not sess_ok:
            return SignalResult(
                tradable=False,
                skip_reason=sess_reason,
                **base_ctx,
            )

        # 3. RVOL min
        if rvol_z < self.cfg.RVOL_ZSCORE_MIN:
            return SignalResult(
                tradable=False,
                skip_reason=f"RVOL_TOO_LOW:{rvol_z:.2f}<{self.cfg.RVOL_ZSCORE_MIN:.2f}",
                **base_ctx,
            )

        # 4. Distances SD bands
        if self.cfg.SD_LEVEL == "sd3":
            d_low = _f(bar.get("dist_vwap_d_sd3d_pct"))
            d_high = _f(bar.get("dist_vwap_d_sd3u_pct"))
        else:
            d_low = _f(bar.get("dist_vwap_d_sd2d_pct"))
            d_high = _f(bar.get("dist_vwap_d_sd2u_pct"))

        thr = self.cfg.SD_THRESHOLD_PCT
        direction: Optional[str] = None
        if d_low <= -thr:
            direction = "LONG"
        elif d_high >= thr:
            direction = "SHORT"
        else:
            return SignalResult(
                tradable=False,
                skip_reason=f"NO_EXTENSION:d_low={d_low:.3f} d_high={d_high:.3f} thr={thr:.3f}",
                **base_ctx,
            )

        # 5. Exhaustion ctx (optionnel)
        if self.cfg.REQUIRE_EXHAUSTION:
            climax = _b(bar.get("ctx_climax_signal"))
            failed_auct = _b(bar.get("ctx_failed_auction"))
            delta_exh = _b(bar.get("ctx_delta_exhaustion"))
            mom_exh = _b(bar.get("ctx_momentum_exhaustion"))
            if not (climax or failed_auct or delta_exh or mom_exh):
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason="EXHAUSTION_REQUIRED_NONE", **base_ctx,
                )

        # 6. Delta direction (optionnel)
        if self.cfg.REQUIRE_DELTA_DIRECTION:
            delta_bar = _f(bar.get("delta_bar"))
            if direction == "LONG" and delta_bar <= 0:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"DELTA_NEG_FOR_LONG:{delta_bar:.0f}", **base_ctx,
                )
            if direction == "SHORT" and delta_bar >= 0:
                return SignalResult(
                    tradable=False, direction=direction,
                    skip_reason=f"DELTA_POS_FOR_SHORT:{delta_bar:.0f}", **base_ctx,
                )

        # 7. Regime filter asymetrique
        regime_ok, regime_reason = self._apply_regime_filter(
            direction, vwap_slope_30, vix, trend_day_score,
        )
        if not regime_ok:
            return SignalResult(
                tradable=False, direction=direction,
                skip_reason=regime_reason, **base_ctx,
            )

        # 8. Compute entry/SL/TP
        entry_price = _f(bar.get("close"))
        if entry_price <= 0:
            return SignalResult(
                tradable=False, direction=direction,
                skip_reason="INVALID_CLOSE_PRICE", **base_ctx,
            )

        tick = get_tick_size(self.symbol)
        sl_ticks = self.cfg.sl_ticks(self.symbol)
        tp_ticks = int(round(sl_ticks * self.cfg.RR))

        if direction == "LONG":
            sl_price = entry_price - sl_ticks * tick
            tp_price = entry_price + tp_ticks * tick
        else:
            sl_price = entry_price + sl_ticks * tick
            tp_price = entry_price - tp_ticks * tick

        # signal_id unique : sym+bar_ts+direction (deterministe + uuid suffix)
        sid_base = f"{self.symbol}_{bar_ts}_{direction}"
        signal_id = f"BOTMR_{sid_base}_{uuid.uuid4().hex[:6]}"

        return SignalResult(
            tradable=True,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_ticks=sl_ticks,
            tp_ticks=tp_ticks,
            rr_ratio=self.cfg.RR,
            signal_id=signal_id,
            **base_ctx,
        )
