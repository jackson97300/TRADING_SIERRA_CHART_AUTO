"""Regime scorer pour Bot MR (Phase 3 alternative score continu).

Approche : score [-100, +100] pondere base sur features multiples.
Capture la non-monotonie observee dans calibration empirique 9j (deciles
disperses EV<0).

Output : regime classification (5 niveaux + PANIC override) + score brut.

Features ponderees :
  1. Slope (vwap_slope_30 normalise par stdev symbol) : poids 30%
  2. Swings ratio (bars_since_high / bars_since_low) : poids 25%
  3. ATR z-score (volatility regime, neutre par direction) : poids 0% direction
  4. VIX absolute (panic trigger) : panic flag separe
  5. Delta day (CVD direction) : poids 15%
  6. Ctx trend day score : poids 15%

Total = 85% (30+25+0+15+15). Marge 15% permet a un signal extreme d'atteindre
[-100, +100] sans saturation immediate. Si fields manquent, fallback gracieux
(contribution=0). VIX/ATR flag panic separe (overrides regime classification).

Reference : feedback calibration empirique 18/06 = vote majoritaire binaire
sur slope_30 perd l'info non-monotone des deciles. Score continu pondere
capture mieux la complexite multi-feature.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from CORE.bot_mean_revert.config import BotMRConfig


# Stdev empiriques sample 9j (memes valeurs que slope thresholds par symbole).
# Permet de normaliser slope_30 en sigma puis scale a [-30, +30].
SLOPE_STDEV_BY_SYM = {
    "ES": 1.42,
    "NQ": 8.54,
    "MGC": 1.0,  # estime (peu de data MGC)
}


@dataclass(frozen=True)
class RegimeScore:
    """Output du RegimeScorer.

    Attributes:
        score : score continu pondere clampe a [-100, +100].
            Negatif = bearish, positif = bullish, |score|<30 = RANGE.
        regime : classification finale (TREND_DOWN_STRONG, TREND_DOWN_WEAK,
            RANGE, TREND_UP_WEAK, TREND_UP_STRONG, PANIC).
        panic : True si VIX > VIX_ABS_PANIC OU atr_z > 2.5.
            Si panic, regime force a "PANIC" (override classification score).
        features : contributions par feature (debug / tracabilite J+1).
        reason : message lisible pour log.
    """
    score: float
    regime: str
    panic: bool
    features: dict
    reason: str


class RegimeScorer:
    """Score continu pondere multi-features pour regime classification.

    Use case : alternative au vote majoritaire binaire (kissingier).
    Capture la non-monotonie observee dans calibration empirique deciles
    slope_30 -> EV (deciles negatifs disperses, certains tres profitables).

    Pattern :
        scorer = RegimeScorer(cfg)
        rs = scorer.classify(bar, symbol="ES")
        if not scorer.allows_direction(rs, "LONG"):
            return SKIP

    Fallback : si un field bar est absent / None / non-castable, la
    contribution retourne 0. Le score reste valide sur les features
    disponibles.
    """

    def __init__(self, cfg: BotMRConfig):
        self.cfg = cfg

    # ============================================================
    # Helpers castage robuste
    # ============================================================
    @staticmethod
    def _safe_float(x) -> Optional[float]:
        """Cast robuste vers float. Retourne None si non-castable."""
        if x is None:
            return None
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    # ============================================================
    # Normalisation slope
    # ============================================================
    def _normalize_slope(self, slope_30: float, symbol: str) -> float:
        """Normalise slope par stdev symbol -> sigma units.

        Retour : slope / stdev (typiquement entre [-3, +3] sigma).
        Si stdev=0 ou symbole inconnu : retourne 0.0 (safe fallback).
        """
        stdev = SLOPE_STDEV_BY_SYM.get(symbol.upper(), 1.0)
        if stdev <= 0:
            return 0.0
        return slope_30 / stdev

    # ============================================================
    # Contributions par feature
    # ============================================================
    def _contrib_slope(self, bar: dict, symbol: str) -> float:
        """Contribution slope normalisee. Range : [-30, +30] (30% du score).

        Clip a +/- 3 sigma pour eviter outliers dominent le score.
        """
        raw = self._safe_float(bar.get("vwap_slope_30"))
        if raw is None:
            return 0.0
        slope_norm = self._normalize_slope(raw, symbol)
        # Clip [-3, +3] sigma puis scale a [-30, +30]
        slope_norm = max(-3.0, min(3.0, slope_norm))
        return (slope_norm / 3.0) * 30.0

    def _contrib_swing(self, bar: dict) -> float:
        """Contribution swing ratio. Range : [-25, +25] (25% du score).

        Ratio bs_low / bs_high :
          - > 1 (log positif) = low vieux = uptrend = score positif
          - < 1 (log negatif) = high vieux = downtrend = score negatif
        log ratio pour normaliser : log(0.5) = -0.69, log(2) = +0.69.
        Clip [-1.5, +1.5] log-units = ratio 0.22x..4.5x.
        """
        bs_high = self._safe_float(bar.get("bars_since_last_swing_high"))
        bs_low = self._safe_float(bar.get("bars_since_last_swing_low"))
        if bs_high is None or bs_low is None:
            return 0.0
        if bs_high <= 0 or bs_low <= 0:
            return 0.0
        ratio = bs_low / bs_high  # > 1 = low vieux = uptrend (high recent)
        try:
            log_ratio = math.log(ratio)
        except ValueError:
            return 0.0
        # Clip [-1.5, +1.5] log-units puis scale [-25, +25]
        log_ratio = max(-1.5, min(1.5, log_ratio))
        return (log_ratio / 1.5) * 25.0

    def _contrib_atr_z(self, bar: dict) -> float:
        """Contribution ATR z-score. Range : [0, 0] (neutre par design).

        Note : ATR z-score est neutre directionnellement (haute vol != trend).
        On garde la fonction pour signature uniforme mais retour 0.
        La detection vol-spike est captee separement par _panic_flag.
        Reservation : si on veut un jour penaliser regimes atypiques RANGE,
        on pourra activer ici (poids 15%).
        """
        # Conserve la lecture pour futur usage (pas de dead code intent).
        _ = self._safe_float(bar.get("ctx_atr_zscore"))
        return 0.0

    def _contrib_delta_day(self, bar: dict) -> float:
        """Contribution delta cumulatif du jour. Range : [-15, +15] (15%).

        Fallback delta_day -> cvd si delta_day absent.
        Normalise par 100k (clip): typique ES median 0-50k, max ~150k extreme.
        """
        d = self._safe_float(bar.get("delta_day"))
        if d is None:
            d = self._safe_float(bar.get("cvd"))
        if d is None:
            return 0.0
        # Clip [-100k, +100k] -> [-1, +1] -> [-15, +15]
        d_norm = max(-100_000.0, min(100_000.0, d)) / 100_000.0
        return d_norm * 15.0

    def _contrib_trend_day_score(self, bar: dict) -> float:
        """Contribution ctx_trend_day_score (Game Changer feature).

        Range : feature deja entre [-1, +1] -> scale [-15, +15] (15% du score).
        """
        t = self._safe_float(bar.get("ctx_trend_day_score"))
        if t is None:
            return 0.0
        t = max(-1.0, min(1.0, t))
        return t * 15.0

    # ============================================================
    # Panic flag
    # ============================================================
    def _panic_flag(self, bar: dict) -> bool:
        """Detecte regime panic. Override classification score -> regime="PANIC".

        Triggers :
          - VIX absolu > VIX_ABS_PANIC (default 30)
          - ATR z-score > 2.5 (volatility regime atypique extreme)

        Note : on n'utilise PAS ici le check VIX_INTRADAY_SPIKE_PCT (deja gere
        par regime_filter dans signal_engine). Le panic flag est plus brutal
        et override toute classification fine.
        """
        vix = self._safe_float(bar.get("vix_level"))
        if vix is not None and vix > self.cfg.VIX_ABS_PANIC:
            return True
        atr_z = self._safe_float(bar.get("ctx_atr_zscore"))
        if atr_z is not None and atr_z > 2.5:
            return True
        return False

    # ============================================================
    # Classification score -> regime
    # ============================================================
    def classify_to_regime(self, score: float, panic: bool) -> str:
        """Mappe score continu -> regime categoriel.

        Seuils :
          score < -strong  -> TREND_DOWN_STRONG
          score < -weak    -> TREND_DOWN_WEAK
          score <= +weak   -> RANGE
          score <= +strong -> TREND_UP_WEAK
          score >  +strong -> TREND_UP_STRONG
          panic=True       -> PANIC (override tout)

        Defaults : strong=60, weak=30. Configurables via env.
        """
        if panic:
            return "PANIC"
        strong = self.cfg.REGIME_SCORE_STRONG_THRESHOLD
        weak = self.cfg.REGIME_SCORE_WEAK_THRESHOLD
        if score < -strong:
            return "TREND_DOWN_STRONG"
        if score < -weak:
            return "TREND_DOWN_WEAK"
        if score <= weak:
            return "RANGE"
        if score <= strong:
            return "TREND_UP_WEAK"
        return "TREND_UP_STRONG"

    # ============================================================
    # API publique
    # ============================================================
    def classify(self, bar: dict, symbol: str) -> RegimeScore:
        """Calcule le score regime et retourne RegimeScore.

        Args:
            bar : dict bar enrichi (sierra_enriched format).
            symbol : "ES" / "NQ" / "MGC".

        Returns:
            RegimeScore(score, regime, panic, features, reason).
        """
        c_slope = self._contrib_slope(bar, symbol)
        c_swing = self._contrib_swing(bar)
        c_atr = self._contrib_atr_z(bar)
        c_delta = self._contrib_delta_day(bar)
        c_trend = self._contrib_trend_day_score(bar)
        panic = self._panic_flag(bar)

        score = c_slope + c_swing + c_atr + c_delta + c_trend
        # Clip final [-100, +100]
        score = max(-100.0, min(100.0, score))

        regime = self.classify_to_regime(score, panic)

        return RegimeScore(
            score=round(score, 1),
            regime=regime,
            panic=panic,
            features={
                "slope": round(c_slope, 1),
                "swing": round(c_swing, 1),
                "atr": round(c_atr, 1),
                "delta": round(c_delta, 1),
                "trend_day": round(c_trend, 1),
            },
            reason=f"score={score:.1f} -> {regime}",
        )

    def allows_direction(self, regime_score: RegimeScore, direction: str) -> bool:
        """Decision finale : autorise-t-on la direction ?

        Politique :
          - PANIC : bloque tout (no MR en regime panic)
          - TREND_DOWN_STRONG : bloque LONG (catch falling knife)
          - TREND_UP_STRONG : bloque SHORT (catch rising rocket)
          - TREND_*_WEAK : autorise les deux directions (regime modere,
            MR pertinent contre la tendance faible)
          - RANGE : autorise les deux directions (zone neutre MR ideal)

        Note : on n'inverse pas le mean revert sur tendance forte. Un trader
        MR pro skippe simplement les regimes trop trendy plutot que de
        chasser la tendance forte (qui peut continuer).
        """
        if regime_score.regime == "PANIC":
            return False
        if regime_score.regime == "TREND_DOWN_STRONG" and direction == "LONG":
            return False  # catch falling knife
        if regime_score.regime == "TREND_UP_STRONG" and direction == "SHORT":
            return False  # catch rising rocket
        # TREND_*_WEAK et RANGE : MR pertinent
        return True
