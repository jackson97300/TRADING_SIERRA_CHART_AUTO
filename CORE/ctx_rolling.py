"""ctx_rolling.py — Features contextuelles rolling (climax, absorption, exhaustion).

Phase 3.5 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.6

⚠️ MODULE CRITIQUE — DSR Lopez ≥ 0.5 OBLIGATOIRE avant prod.

Validation reportee Phase 4 dual-run (data reelle 5 jours) :
- DSR Lopez 12-fold walk-forward sur features climax/failed_auction/exhaustion
- Convergence cross-fold > 60% sur features SIGNED
- HHI top-2 < 33% (anti concentration)
- Costs slippage inclus

Tests structurels seulement (this module) : verifient math + boundaries +
fail-loud. La validation EDGE attend Phase 4. Cf `.claude/rules/critical-tasks-review.md`
critere 8 (audit producing edge candidates -> ml-trainer obligatoire avant integration).

25 features rolling context :

## Climax / Failed auction (2)
  1.  ctx_climax_signal     : bool, vol_z > 2 ET range_pos extreme (>0.9 OR <0.1)
  2.  ctx_failed_auction    : bool, new extreme bar ET cloture proche du middle

## Absorption (3)
  3.  ctx_absorption_score_5  : float, mean |bn_absorb_*| 5 bars
  4.  ctx_absorption_streak_5 : int, streak consecutif absorption
  5.  ctx_instant_absorption  : bool, absorption sur bar courante

## Exhaustion (2)
  6.  ctx_delta_exhaustion    : bool, |delta_z| > 2 ET small price move
  7.  ctx_momentum_exhaustion : bool, |price_slope| decline sur 5 bars

## Poor high/low + excess (5)
  8.  ctx_poor_high            : bool, new high + small body bullish (rejet)
  9.  ctx_poor_low             : bool, new low + small body bearish
  10. ctx_excess_high_bars     : int, count bars > EMA20
  11. ctx_excess_low_bars      : int, count bars < EMA20
  12. ctx_double_top_trap      : bool, 2 highs equivalent + delta divergence

## Volume rolling (3)
  13. ctx_vol_sell_buy_ratio_5 : float, mean sell_vol/buy_vol sur 5 bars
  14. ctx_vol_slope_5          : float SIGNED, slope total_vol 5 bars
  15. ctx_vol_z_5              : float SIGNED, z-score total_vol vs window_long (20).
                                 NOTE : nom "5" historique design doc, calcul reel sur 20.
                                 A renommer ctx_vol_z_20 Phase 5 si DSR confirme utilite.

## Finish strength + VWAP velocity (4)
  16. ctx_finish_strength_mean_5 : float, mean finish_strength 5 bars
  17. ctx_dist_vwap_velocity    : float SIGNED, delta dist_vwap_d sur 3 bars
  18. ctx_vwap_slope_accel      : float SIGNED, 2nd derivative slope VWAP
  19. ctx_va_position_velocity  : float SIGNED, delta va_position_pct sur 3 bars

## Price action + delta rolling (4)
  20. ctx_side_flip_count_10  : int, count alternances bull/bear bars 10
  21. ctx_range_vs_atr_10     : float, mean bar_range / atr 10 bars
  22. ctx_price_slope_5       : float SIGNED, slope linregress close 5 bars
  23. ctx_delta_sum_3         : float SIGNED, sum delta_bar 3 bars

## Delta rolling + recovery (2)
  24. ctx_delta_slope_5       : float SIGNED, slope delta_bar 5 bars
  25. ctx_rvol_session        : float, total_vol / mean total_vol session

Sources :
  - OHLC : close, bar_high, bar_low
  - Volume : delta_bar, total_vol, buy_vol, sell_vol
  - Indicateurs : atr, vwap_d
  - Sierra deja calcule : finish_strength, range_pos, va_position_pct (Phase 4 dual-run)
  - Absorption Sierra : bn_absorb_ask, bn_absorb_bid (optionnels)

Garde-fou SIGNE (8 features SIGNEES) :
  - ctx_vol_slope_5, ctx_vol_z_5 (volume direction)
  - ctx_dist_vwap_velocity, ctx_vwap_slope_accel (VWAP momentum)
  - ctx_va_position_velocity (VA position momentum)
  - ctx_price_slope_5, ctx_delta_sum_3, ctx_delta_slope_5 (price/delta direction)
  - Convention : positif = haussier, negatif = baissier
  - Validation Phase 4 obligatoire avant trust

Anti-patterns interdits :
  - Composite hardcode "veto if climax" -> features brutes (laisse ML)
  - Silent fallback : NaN propre cold-start
  - DSR validation skip -> Phase 4 obligatoire avant prod

Auteur : MIA Trading V2 (Phase 3.5 Sierra Migration)
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

# Windows rolling configurables
WINDOW_5 = 5
WINDOW_10 = 10
WINDOW_20 = 20
EMA_PERIOD = 20

# Thresholds (calibration empirique Phase 4)
VOL_Z_CLIMAX_THRESHOLD = 2.0       # z-score volume pour climax
RANGE_POS_EXTREME_HIGH = 0.9       # range_pos > 0.9 = bar pres du high
RANGE_POS_EXTREME_LOW = 0.1
DELTA_Z_EXHAUSTION = 2.0           # z-score delta pour exhaustion
SMALL_BODY_RATIO = 0.3             # body / range < 0.3 = small body
POOR_HIGH_REJECT_RATIO = 0.6       # close <= bar_low + 0.6*range = rejet
ABSORPTION_THRESHOLD = 0.5         # |bn_absorb_*| > 0.5 = absorption active
DOUBLE_TOP_TOLERANCE_ATR = 0.3     # 2 highs egaux a 0.3 ATR pres
MOMENTUM_DECAY_RATIO = 0.5         # slope_5 < 50% slope_prev -> exhaustion
                                    # (extrait constante fix review B7.1 10/06)


class CtxRollingCalculator:
    """Calculateur stateful 25 features contextuelles rolling.

    Usage:
        calc = CtxRollingCalculator()
        for bar in bars:
            features = calc.update(
                close=bar["close"],
                bar_high=bar["bar_high"],
                bar_low=bar["bar_low"],
                delta_bar=bar["delta_bar"],
                total_vol=bar["total_vol"],
                buy_vol=bar.get("buy_vol", np.nan),
                sell_vol=bar.get("sell_vol", np.nan),
                atr=bar["atr"],
                vwap_d=bar.get("vwap_d", np.nan),
                finish_strength=bar.get("finish_strength", np.nan),
                range_pos=bar.get("range_pos", np.nan),
                va_position_pct=bar.get("va_position_pct", np.nan),
                bn_absorb_ask=bar.get("bn_absorb_ask", 0.0),
                bn_absorb_bid=bar.get("bn_absorb_bid", 0.0),
            )

    Reset cross-day : caller appelle calc.reset() au boundary 18:00 ET.
    """

    def __init__(
        self,
        window_short: int = WINDOW_5,
        window_medium: int = WINDOW_10,
        window_long: int = WINDOW_20,
    ) -> None:
        self.window_short = window_short
        self.window_medium = window_medium
        self.window_long = window_long

        # Rolling buffers OHLC
        self._close_buffer: deque[float] = deque(maxlen=window_long)
        self._high_buffer: deque[float] = deque(maxlen=window_long)
        self._low_buffer: deque[float] = deque(maxlen=window_long)
        # Volume
        self._delta_buffer: deque[float] = deque(maxlen=window_long)
        self._vol_buffer: deque[float] = deque(maxlen=window_long)
        self._buy_vol_buffer: deque[float] = deque(maxlen=window_short)
        self._sell_vol_buffer: deque[float] = deque(maxlen=window_short)
        # Indicators
        self._atr_buffer: deque[float] = deque(maxlen=window_medium)
        self._vwap_buffer: deque[float] = deque(maxlen=window_short)
        self._dist_vwap_buffer: deque[float] = deque(maxlen=window_short)
        self._va_pos_buffer: deque[float] = deque(maxlen=window_short)
        self._finish_buffer: deque[float] = deque(maxlen=window_short)
        # Absorption rolling
        self._absorb_buffer: deque[float] = deque(maxlen=window_short)
        # Session volume tracking (pour rvol_session)
        self._session_vol_count: int = 0
        self._session_vol_sum: float = 0.0
        # Day-level high tracker (pour double_top)
        self._recent_highs: deque[dict] = deque(maxlen=10)
        # EMA 20 close (smoothed running)
        self._ema_close: Optional[float] = None
        # State pour streaks
        self._absorption_streak: int = 0
        self._last_side_was_bull: Optional[bool] = None

    def reset(self) -> None:
        """Reset state cross-day."""
        for buf in [self._close_buffer, self._high_buffer, self._low_buffer,
                    self._delta_buffer, self._vol_buffer,
                    self._buy_vol_buffer, self._sell_vol_buffer,
                    self._atr_buffer, self._vwap_buffer, self._dist_vwap_buffer,
                    self._va_pos_buffer, self._finish_buffer,
                    self._absorb_buffer]:
            buf.clear()
        self._session_vol_count = 0
        self._session_vol_sum = 0.0
        self._recent_highs.clear()
        self._ema_close = None
        self._absorption_streak = 0
        self._last_side_was_bull = None

    def update(
        self,
        close: Optional[float],
        bar_high: Optional[float],
        bar_low: Optional[float],
        delta_bar: Optional[float],
        total_vol: Optional[float],
        atr: Optional[float],
        buy_vol: Optional[float] = None,
        sell_vol: Optional[float] = None,
        vwap_d: Optional[float] = None,
        finish_strength: Optional[float] = None,
        range_pos: Optional[float] = None,
        va_position_pct: Optional[float] = None,
        bn_absorb_ask: float = 0.0,
        bn_absorb_bid: float = 0.0,
    ) -> dict:
        """Update buffers + compute 25 features."""
        # Validation inputs critiques (OHLC + atr requis)
        if any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in (close, bar_high, bar_low, delta_bar, total_vol, atr)) \
                or atr == 0:
            return self._empty_features()

        close = float(close)
        bar_high = float(bar_high)
        bar_low = float(bar_low)
        delta_bar = float(delta_bar)
        total_vol = float(total_vol)
        atr = float(atr)
        buy_vol = float(buy_vol) if buy_vol is not None and not (
            isinstance(buy_vol, float) and np.isnan(buy_vol)) else np.nan
        sell_vol = float(sell_vol) if sell_vol is not None and not (
            isinstance(sell_vol, float) and np.isnan(sell_vol)) else np.nan
        vwap_d = float(vwap_d) if vwap_d is not None and not (
            isinstance(vwap_d, float) and np.isnan(vwap_d)) else np.nan
        finish_strength = float(finish_strength) if finish_strength is not None \
            and not (isinstance(finish_strength, float) and np.isnan(finish_strength)) \
            else np.nan
        range_pos = float(range_pos) if range_pos is not None and not (
            isinstance(range_pos, float) and np.isnan(range_pos)) else np.nan
        va_position_pct = float(va_position_pct) if va_position_pct is not None \
            and not (isinstance(va_position_pct, float)
                     and np.isnan(va_position_pct)) else np.nan

        # Push buffers
        self._close_buffer.append(close)
        self._high_buffer.append(bar_high)
        self._low_buffer.append(bar_low)
        self._delta_buffer.append(delta_bar)
        self._vol_buffer.append(total_vol)
        self._atr_buffer.append(atr)
        if not np.isnan(buy_vol):
            self._buy_vol_buffer.append(buy_vol)
        if not np.isnan(sell_vol):
            self._sell_vol_buffer.append(sell_vol)
        if not np.isnan(vwap_d):
            self._vwap_buffer.append(vwap_d)
            self._dist_vwap_buffer.append(close - vwap_d)
        if not np.isnan(va_position_pct):
            self._va_pos_buffer.append(va_position_pct)
        if not np.isnan(finish_strength):
            self._finish_buffer.append(finish_strength)

        # Absorption score = max(|absorb_ask|, |absorb_bid|)
        absorb_now = max(abs(bn_absorb_ask), abs(bn_absorb_bid))
        self._absorb_buffer.append(absorb_now)

        # Session volume tracking
        self._session_vol_count += 1
        self._session_vol_sum += total_vol

        # EMA 20 close smoothing
        if self._ema_close is None:
            self._ema_close = close
        else:
            alpha = 2.0 / (EMA_PERIOD + 1)
            self._ema_close = alpha * close + (1 - alpha) * self._ema_close

        # Cold-start : buffer < window_short -> NaN propre
        if len(self._close_buffer) < self.window_short:
            return self._empty_features()

        # ──────────────────────────────────────────────────────────────
        # Compute features
        # ──────────────────────────────────────────────────────────────
        bar_range = max(bar_high - bar_low, 1e-9)  # anti div zero
        body = close - (bar_high + bar_low) / 2.0

        # Volume z-score (sur window_long si dispo, sinon window_short)
        vol_mean = np.mean(list(self._vol_buffer))
        vol_std = np.std(list(self._vol_buffer))
        vol_z = (total_vol - vol_mean) / vol_std if vol_std > 0 else 0.0

        # Climax signal : volume spike + bar pres d'un extreme
        climax = (
            abs(vol_z) > VOL_Z_CLIMAX_THRESHOLD
            and not np.isnan(range_pos)
            and (range_pos > RANGE_POS_EXTREME_HIGH
                 or range_pos < RANGE_POS_EXTREME_LOW)
        )

        # Failed auction : new extreme + cloture middle
        new_high_bar = bar_high >= max(self._high_buffer)
        new_low_bar = bar_low <= min(self._low_buffer)
        body_in_middle = abs(body) / bar_range < SMALL_BODY_RATIO
        failed_auction = (new_high_bar or new_low_bar) and body_in_middle

        # Absorption metrics
        absorb_score_5 = np.mean(list(self._absorb_buffer))
        instant_absorption = absorb_now > ABSORPTION_THRESHOLD
        if instant_absorption:
            self._absorption_streak += 1
        else:
            self._absorption_streak = 0

        # Delta exhaustion : grand delta_z + petit price move
        delta_mean = np.mean(list(self._delta_buffer))
        delta_std = np.std(list(self._delta_buffer))
        delta_z = (delta_bar - delta_mean) / delta_std if delta_std > 0 else 0.0
        price_move_atr = abs(close - self._close_buffer[-2]) / atr if len(
            self._close_buffer) >= 2 else 0
        delta_exhaustion = abs(delta_z) > DELTA_Z_EXHAUSTION and price_move_atr < 0.2

        # Momentum exhaustion : slope_price magnitude decroit
        if len(self._close_buffer) >= self.window_short:
            slope_5 = self._slope(list(self._close_buffer)[-self.window_short:])
            slope_3_prev = self._slope(
                list(self._close_buffer)[-(self.window_short + 2):-2]
            ) if len(self._close_buffer) >= self.window_short + 2 else slope_5
            momentum_exhaustion = (
                abs(slope_5) < abs(slope_3_prev) * MOMENTUM_DECAY_RATIO
                and slope_3_prev != 0
            )
        else:
            slope_5 = 0.0
            momentum_exhaustion = False

        # Poor high/low : new extreme + petit corps + rejet
        body_bullish = close > bar_low + bar_range * POOR_HIGH_REJECT_RATIO
        body_bearish = close < bar_high - bar_range * POOR_HIGH_REJECT_RATIO
        poor_high = new_high_bar and not body_bullish
        poor_low = new_low_bar and not body_bearish

        # Excess bars vs EMA20
        excess_high = sum(1 for c in self._close_buffer
                         if c > self._ema_close)
        excess_low = sum(1 for c in self._close_buffer
                        if c < self._ema_close)

        # Double top trap : 2 derniers highs egaux + delta divergence
        if new_high_bar:
            self._recent_highs.append({
                "price": bar_high,
                "delta": delta_bar,
                "bar_idx": len(self._close_buffer),
            })
        double_top = False
        if len(self._recent_highs) >= 2:
            h1 = self._recent_highs[-1]
            h2 = self._recent_highs[-2]
            same_level = abs(h1["price"] - h2["price"]) < DOUBLE_TOP_TOLERANCE_ATR * atr
            delta_div = h1["delta"] < h2["delta"]  # delta plus faible 2eme top
            double_top = same_level and delta_div

        # Volume sell/buy ratio
        if (self._buy_vol_buffer and self._sell_vol_buffer
                and len(self._buy_vol_buffer) >= self.window_short):
            buy_sum = sum(self._buy_vol_buffer)
            sell_sum = sum(self._sell_vol_buffer)
            vol_sb_ratio = sell_sum / buy_sum if buy_sum > 0 else np.nan
        else:
            vol_sb_ratio = np.nan

        # Volume slope 5
        if len(self._vol_buffer) >= self.window_short:
            vol_slope = self._slope(list(self._vol_buffer)[-self.window_short:])
        else:
            vol_slope = np.nan

        # Finish strength mean
        finish_mean = (
            np.mean(list(self._finish_buffer))
            if self._finish_buffer else np.nan
        )

        # VWAP velocity
        if len(self._dist_vwap_buffer) >= 3:
            dist_vwap_vel = self._dist_vwap_buffer[-1] - self._dist_vwap_buffer[-3]
        else:
            dist_vwap_vel = np.nan

        # VWAP slope acceleration (2nd derivative)
        if len(self._vwap_buffer) >= self.window_short:
            vwap_vals = list(self._vwap_buffer)
            slope_recent = self._slope(vwap_vals[-3:])
            slope_prev = self._slope(vwap_vals[:-1][-3:]) if len(vwap_vals) >= 4 else slope_recent
            vwap_slope_accel = slope_recent - slope_prev
        else:
            vwap_slope_accel = np.nan

        # VA position velocity
        if len(self._va_pos_buffer) >= 3:
            va_pos_vel = self._va_pos_buffer[-1] - self._va_pos_buffer[-3]
        else:
            va_pos_vel = np.nan

        # Side flip count 10 (alternances bull/bear)
        side_flips = 0
        prev_side = None
        for c, h, l in zip(list(self._close_buffer)[-self.window_medium:],
                          list(self._high_buffer)[-self.window_medium:],
                          list(self._low_buffer)[-self.window_medium:]):
            mid = (h + l) / 2.0
            curr_side = c > mid
            if prev_side is not None and curr_side != prev_side:
                side_flips += 1
            prev_side = curr_side

        # Range vs ATR 10
        if len(self._high_buffer) >= self.window_medium:
            ranges = [h - l for h, l in zip(
                list(self._high_buffer)[-self.window_medium:],
                list(self._low_buffer)[-self.window_medium:]
            )]
            atr_mean = np.mean(list(self._atr_buffer)[-self.window_medium:])
            range_vs_atr = np.mean(ranges) / atr_mean if atr_mean > 0 else np.nan
        else:
            range_vs_atr = np.nan

        # Delta sum/slope rolling
        delta_sum_3 = sum(list(self._delta_buffer)[-3:]) if len(
            self._delta_buffer) >= 3 else np.nan
        delta_slope_5 = self._slope(
            list(self._delta_buffer)[-self.window_short:]
        ) if len(self._delta_buffer) >= self.window_short else np.nan

        # RVol session
        if self._session_vol_count > 0:
            mean_session_vol = self._session_vol_sum / self._session_vol_count
            rvol_session = total_vol / mean_session_vol if mean_session_vol > 0 else np.nan
        else:
            rvol_session = np.nan

        return {
            # Climax / Failed auction
            "ctx_climax_signal": bool(climax),
            "ctx_failed_auction": bool(failed_auction),
            # Absorption
            "ctx_absorption_score_5": float(absorb_score_5),
            "ctx_absorption_streak_5": int(self._absorption_streak),
            "ctx_instant_absorption": bool(instant_absorption),
            # Exhaustion
            "ctx_delta_exhaustion": bool(delta_exhaustion),
            "ctx_momentum_exhaustion": bool(momentum_exhaustion),
            # Poor highs/lows + excess + double top
            "ctx_poor_high": bool(poor_high),
            "ctx_poor_low": bool(poor_low),
            "ctx_excess_high_bars": int(excess_high),
            "ctx_excess_low_bars": int(excess_low),
            "ctx_double_top_trap": bool(double_top),
            # Volume rolling
            "ctx_vol_sell_buy_ratio_5": vol_sb_ratio,
            "ctx_vol_slope_5": vol_slope,
            "ctx_vol_z_5": float(vol_z),
            # Finish + VWAP velocity
            "ctx_finish_strength_mean_5": finish_mean,
            "ctx_dist_vwap_velocity": dist_vwap_vel,
            "ctx_vwap_slope_accel": vwap_slope_accel,
            "ctx_va_position_velocity": va_pos_vel,
            # Price action
            "ctx_side_flip_count_10": int(side_flips),
            "ctx_range_vs_atr_10": range_vs_atr,
            "ctx_price_slope_5": float(slope_5),
            # Delta rolling
            "ctx_delta_sum_3": delta_sum_3,
            "ctx_delta_slope_5": delta_slope_5,
            # Volume session
            "ctx_rvol_session": rvol_session,
        }

    @staticmethod
    def _slope(values: list[float]) -> float:
        """Linregress slope sur values (x = indices 0..N-1)."""
        n = len(values)
        if n < 2:
            return 0.0
        x = np.arange(n, dtype=np.float64)
        y = np.asarray(values, dtype=np.float64)
        x_mean = x.mean()
        y_mean = y.mean()
        cov = np.mean((x - x_mean) * (y - y_mean))
        var_x = np.mean((x - x_mean) ** 2)
        return float(cov / var_x) if var_x > 0 else 0.0

    @staticmethod
    def _empty_features() -> dict:
        """Features defaut cold-start / NaN inputs."""
        return {
            "ctx_climax_signal": False,
            "ctx_failed_auction": False,
            "ctx_absorption_score_5": np.nan,
            "ctx_absorption_streak_5": 0,
            "ctx_instant_absorption": False,
            "ctx_delta_exhaustion": False,
            "ctx_momentum_exhaustion": False,
            "ctx_poor_high": False,
            "ctx_poor_low": False,
            "ctx_excess_high_bars": 0,
            "ctx_excess_low_bars": 0,
            "ctx_double_top_trap": False,
            "ctx_vol_sell_buy_ratio_5": np.nan,
            "ctx_vol_slope_5": np.nan,
            "ctx_vol_z_5": np.nan,
            "ctx_finish_strength_mean_5": np.nan,
            "ctx_dist_vwap_velocity": np.nan,
            "ctx_vwap_slope_accel": np.nan,
            "ctx_va_position_velocity": np.nan,
            "ctx_side_flip_count_10": 0,
            "ctx_range_vs_atr_10": np.nan,
            "ctx_price_slope_5": np.nan,
            "ctx_delta_sum_3": np.nan,
            "ctx_delta_slope_5": np.nan,
            "ctx_rvol_session": np.nan,
        }


def compute_ctx_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec colonnes minimum requises :
             close, bar_high, bar_low, delta_bar, total_vol, atr.
             Optionnelles : buy_vol, sell_vol, vwap_d, finish_strength,
             range_pos, va_position_pct, bn_absorb_ask, bn_absorb_bid.

    Returns:
        DataFrame copie + 25 colonnes ctx_*.

    Raises:
        ValueError : si colonne requise manquante.
    """
    required = ["close", "bar_high", "bar_low", "delta_bar", "total_vol", "atr"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"compute_ctx_rolling_features : colonnes requises manquantes {missing}"
        )

    result = df.copy()
    calc = CtxRollingCalculator()
    rows = []

    for _, row in df.iterrows():
        rows.append(calc.update(
            close=row["close"],
            bar_high=row["bar_high"],
            bar_low=row["bar_low"],
            delta_bar=row["delta_bar"],
            total_vol=row["total_vol"],
            atr=row["atr"],
            buy_vol=row.get("buy_vol", np.nan),
            sell_vol=row.get("sell_vol", np.nan),
            vwap_d=row.get("vwap_d", np.nan),
            finish_strength=row.get("finish_strength", np.nan),
            range_pos=row.get("range_pos", np.nan),
            va_position_pct=row.get("va_position_pct", np.nan),
            bn_absorb_ask=row.get("bn_absorb_ask", 0.0),
            bn_absorb_bid=row.get("bn_absorb_bid", 0.0),
        ))

    features_df = pd.DataFrame(rows, index=result.index)
    for col in features_df.columns:
        result[col] = features_df[col].values
    return result
