"""regime_classifier.py - Classification régime marché Bot 1 Mean Revert.

REFERENCE : Backtest market-analyst 24/06/2026 (sample 7j, 22929 bars, 67 trades).

Architecture V_FINAL validée empiriquement :
- 5 régimes mutuellement exclusifs, seuils dérivés de quantiles observés
- 3 règles d'exclusion (régime, session) basées sur clusters losers
- Validation cross-period : TRAIN 5j +$185, TEST 2j +$114, sans-FOMC +$224
- Wins préservés 95% (sacrifie 5%, evite -$299 en SL retroactif)

Régimes :
    CALM_RANGE   (66.3% bars) : VIX<19.5, atr_pct<0.048, pas trend     → MR classique OK
    VOLATILE_RANGE (10.7%)    : atr_pct>=0.048, pas trend              → MR avec strict filter
    TREND_DOWN   (2.5%, run=9): trend_prob>=0.35, slope_smoothed<=-1.5 → Pas MR contre trend
    TREND_UP     (6.6%, run=1): trend_prob>=0.35, slope_smoothed>=+1.5 → Pas MR contre trend (oscille)
    PANIC        (13.9%)      : VIX>=19.5 OU atr_pct>=0.076            → No trade

Sessions (heure UTC du bar) :
    asia    : 00h-07h UTC (Asia + early London)
    london  : 07h-13h UTC (London + EU pre-RTH)
    us_cash : 13h-21h UTC (RTH US, incluant pre-RTH 13h-13h30)
    ah      : 21h-24h UTC (After Hours, déjà bloqué par PROP #2)

Blacklist V_FINAL (3 règles) :
    (PANIC, any)                 → NO_TRADE (event-driven, illiquide)
    (CALM_RANGE, us_cash)        → NO_TRADE (chop institutionnel, 0% WR sample)
    (VOLATILE_RANGE, asia)       → NO_TRADE (panic post-news Asia, 11% WR sample)

Convention thread-safety :
- Instance unique par bot, stateful (smoothing EWM par symbole)
- NON thread-safe, à utiliser dans boucle synchrone
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


class Regime(str, Enum):
    """Régime marché détecté (5 mutuellement exclusifs)."""
    CALM_RANGE = "CALM_RANGE"
    VOLATILE_RANGE = "VOLATILE_RANGE"
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    PANIC = "PANIC"


@dataclass(frozen=True)
class RegimeThresholds:
    """Seuils dérivés de l'étude empirique 22929 bars 16-24/06/2026.

    Robustesse vérifiée : variation ±10% des seuils → 80% classifications
    identiques (cf section 4 backtest).
    """
    # PANIC (priority first - event-driven)
    # AVANT fix audit 30/06 : OR (vix>=19.5 OU atr>=0.076) -> 19.3% bars PANIC, 91% faux positifs.
    # APRES fix : cross-feature AND + fallback VIX extreme seul.
    # Empirique 9104 bars sem 22-25/06 : PANIC OR=19.3% -> AND=1.9%, reduction -89.9%.
    vix_panic: float = 19.5  # p95 VIX observe (cross-confirmation requise)
    atr_pct_panic: float = 0.076  # p90 ATR% (cross-confirmation requise)
    vix_panic_extreme: float = 25.0  # vrai event news/crisis (VIX >= 25 = volatility cluster cf historique 2008/2020/2018)

    # VOLATILE_RANGE
    atr_pct_volatile: float = 0.048  # p75 ATR%

    # TREND (probability seuil + slope smoothed)
    trend_probability_min: float = 0.35  # p75 trend_day_probability
    slope_smoothed_trend_down: float = -1.5
    slope_smoothed_trend_up: float = +1.5


class RegimeClassifier:
    """Classifier stateful (smoothing EWM slope_30 par symbole).

    Usage :
        clf = RegimeClassifier()
        regime = clf.classify(bar, symbol="NQ")  # appelé 1x par bar
        if regime == Regime.PANIC:
            ...
    """

    def __init__(
        self,
        thresholds: Optional[RegimeThresholds] = None,
        ewm_alpha: float = 0.4,
    ):
        """
        Args:
            thresholds : seuils détection (default = V_FINAL backtest)
            ewm_alpha : poids EWM smoothing slope_30 (0.4 = 5 bars effectifs)
        """
        self.thresholds = thresholds or RegimeThresholds()
        if not 0.0 < ewm_alpha <= 1.0:
            raise ValueError(f"ewm_alpha must be in (0, 1], got {ewm_alpha}")
        self.ewm_alpha = ewm_alpha
        # Per-symbol EWM state (isolation ES vs NQ)
        self._slope_ewm: dict[str, float] = {}

    def reset(self) -> None:
        """Reset state EWM (utile pour tests + nouvelle session)."""
        self._slope_ewm.clear()

    def _update_slope_ewm(self, symbol: str, slope_30: float) -> float:
        """Update EWM slope per symbol, return smoothed value."""
        prev = self._slope_ewm.get(symbol)
        if prev is None:
            self._slope_ewm[symbol] = slope_30
        else:
            self._slope_ewm[symbol] = (
                self.ewm_alpha * slope_30 + (1.0 - self.ewm_alpha) * prev
            )
        return self._slope_ewm[symbol]

    def get_slope_smoothed(self, symbol: str) -> Optional[float]:
        """Read current smoothed slope (None si jamais classify pour ce sym)."""
        return self._slope_ewm.get(symbol)

    def classify(self, bar: dict, symbol: str) -> Regime:
        """Classifie le régime marché du bar courant pour ce symbole.

        Args:
            bar : dict bar enriched (features sierra_enriched)
            symbol : ES / NQ / MGC (pour isolation EWM)

        Returns:
            Regime enum membre (5 mutuellement exclusifs)

        Note : si features critiques absentes → fallback CALM_RANGE
        (default conservateur = ne pas trigger panic ou trend sans signal clair).
        """
        # Lecture features avec fallback safe (features absentes -> 0)
        def _f(key: str, default: float = 0.0) -> float:
            val = bar.get(key)
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        vix = _f("vix_level", 0.0)
        atr_pct = _f("atr_14m_pct", 0.0)
        trend_prob = _f("trend_day_probability", 0.0)
        slope_30 = _f("vwap_slope_30", 0.0)

        # Update EWM smoothing (état stateful)
        slope_smoothed = self._update_slope_ewm(symbol, slope_30)

        # 1. PANIC priorite absolue (event-driven, ecrase tout)
        # Fix audit 30/06 : OR -> AND cross-confirmation pour eliminer faux positifs
        # AVANT (OR) : 19.3% bars classees PANIC sem 22-25/06 dont 91% sans VIX reel
        # APRES (AND) : 1.9% bars PANIC (vraie cross-feature confirmation)
        # Cf DOCS/INCIDENT_LOG.md #94+ pour audit weekend.
        # Trigger primaire : VIX modere ET ATR modere = vrai cross-feature event
        if (vix >= self.thresholds.vix_panic
                and atr_pct >= self.thresholds.atr_pct_panic):
            return Regime.PANIC
        # Fallback : VIX extreme seul (event news/crisis, p99.5 historique)
        # Evite de rater une vraie panique news ou ATR n'a pas encore propage
        if vix >= self.thresholds.vix_panic_extreme:
            return Regime.PANIC

        # 2. TREND (priorité 2, requiert probability + slope strong)
        if trend_prob >= self.thresholds.trend_probability_min:
            if slope_smoothed <= self.thresholds.slope_smoothed_trend_down:
                return Regime.TREND_DOWN
            if slope_smoothed >= self.thresholds.slope_smoothed_trend_up:
                return Regime.TREND_UP

        # 3. VOLATILE_RANGE (atr eleve mais pas trend)
        if atr_pct >= self.thresholds.atr_pct_volatile:
            return Regime.VOLATILE_RANGE

        # 4. CALM_RANGE par defaut (residuel)
        return Regime.CALM_RANGE


# ============================================================================
# Sessions UTC (alignées avec PROP #2 skip AH)
# ============================================================================

def detect_session_utc(hour_utc: int) -> str:
    """Detecte session marché basée sur l'heure UTC du bar.

    Convention V_FINAL :
        asia    : 00h-07h UTC (Asia + early London prep)
        london  : 07h-13h UTC (London RTH + EU pre-US)
        us_cash : 13h-21h UTC (RTH US, incluant pre-RTH 13h-13h30)
        ah      : 21h-24h UTC (After Hours)

    Note : (régime, ah) est déjà bloqué par PROP #2 (SKIP_AH_SESSION).
    """
    if 0 <= hour_utc < 7:
        return "asia"
    if 7 <= hour_utc < 13:
        return "london"
    if 13 <= hour_utc < 21:
        return "us_cash"
    return "ah"


# ============================================================================
# Blacklist V_FINAL (3 règles validées empirique sur 67 trades)
# ============================================================================

# Format string : "REGIME:session" ou "REGIME:*" (any session)
DEFAULT_BLACKLIST_V_FINAL: tuple = (
    "PANIC:*",  # event-driven, illiquide, no MR
    "CALM_RANGE:us_cash",  # chop institutionnel, 0% WR sample
    "VOLATILE_RANGE:asia",  # panic post-news Asia, 11% WR
)


def parse_blacklist(blacklist_strs: Iterable[str]) -> frozenset[tuple[str, str]]:
    """Parse "REGIME:session" strings en set de tuples.

    "PANIC:*" est expansé à toutes les sessions.
    """
    all_sessions = ("asia", "london", "us_cash", "ah")
    result: set[tuple[str, str]] = set()
    for entry in blacklist_strs:
        if ":" not in entry:
            continue  # format invalide, skip silencieusement
        regime_str, session_str = entry.split(":", 1)
        regime_str = regime_str.strip().upper()
        session_str = session_str.strip().lower()
        if session_str == "*":
            for sess in all_sessions:
                result.add((regime_str, sess))
        else:
            result.add((regime_str, session_str))
    return frozenset(result)


def is_blacklisted(
    regime: Regime,
    session: str,
    blacklist: frozenset[tuple[str, str]],
) -> bool:
    """Verifie si (régime, session) est dans la blacklist."""
    return (regime.value, session.lower()) in blacklist
