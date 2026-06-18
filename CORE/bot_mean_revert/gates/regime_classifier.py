"""Regime classifier pour Bot MR (Phase 3 18/06).

Approche KISS vote majoritaire 3 signaux INDEPENDANTS :
  1. Slope-based     : vwap_slope_30 vs seuils par symbole (Phase 2 deja deploye)
  2. Swing structure : ratio bars_since_high / bars_since_low (LL/HH chain)
  3. Panic           : VIX absolu OR ctx_atr_zscore (vol extreme)

Output enum : RANGE / TREND_DOWN / TREND_UP / PANIC

Action Bot MR (via helper `allows_direction`) :
  - RANGE       : LONG/SHORT MR normaux
  - TREND_DOWN  : bloque LONG (catch falling knife)
  - TREND_UP    : bloque SHORT (contre-trend dangereux)
  - PANIC       : bloque tout (regime extreme = pas de MR)

PANIC est PRIORITAIRE : 1 seul vote PANIC dans les 3 signaux = regime PANIC.
Sinon vote majoritaire classique (max sur RANGE / TREND_DOWN / TREND_UP).

Reference design : carnage ES 18/06 -$1025 broker E-mini sur 4 LONGs en
descente. Le regime_filter scalaire (slope_30 < threshold) ne capture pas
tous les regimes. Vote 3 signaux = decision robuste + deterministe (pas
de score pondere, pas de tuning hyper-fragile).

Note ctx_atr_zscore : ABSENT du bar sierra_enriched a ce jour (verifie sur
20260615_ES). Le signal_panic ne perd pas en robustesse : fallback gracieux
vers VIX absolu seul. Si ctx_atr_zscore apparait dans une future version
DMP, l'enrichissement est transparent (aucun code a toucher).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Etats possibles (constantes pour grep / refactor)
REGIME_RANGE = "RANGE"
REGIME_TREND_DOWN = "TREND_DOWN"
REGIME_TREND_UP = "TREND_UP"
REGIME_PANIC = "PANIC"


@dataclass(frozen=True)
class RegimeVerdict:
    """Verdict immutable du classifier.

    Attributs :
        regime   : "RANGE" | "TREND_DOWN" | "TREND_UP" | "PANIC"
        votes    : {"RANGE": int, "TREND_DOWN": int, "TREND_UP": int, "PANIC": int}
        signals  : {"slope": str, "swing": str, "panic": str} (vote de chaque signal)
        reason   : courte explication pour log (vote majo / panic priority).
    """
    regime: str
    votes: dict
    signals: dict
    reason: str


class RegimeClassifier:
    """Vote majoritaire 3 signaux INDEPENDANTS pour decision regime.

    Usage prod :
        clf = RegimeClassifier(cfg)
        verdict = clf.classify(bar, symbol="ES")
        if not clf.allows_direction(verdict, "LONG"):
            # skip trade : regime ne permet pas la direction
            ...

    Threading : stateless apres init (cfg frozen dataclass). Reuse safe
    cross-thread / cross-symbole.
    """

    # Bornes ratio swing (PHI tightened si besoin Phase 4 calibration)
    SWING_RATIO_TREND_DOWN = 2.0  # high tres vieux / low recent
    SWING_RATIO_TREND_UP = 0.5    # low tres vieux / high recent
    # Bornes panic
    ATR_ZSCORE_PANIC_DEFAULT = 2.5  # fallback si cfg.ATR_ZSCORE_PANIC absent

    def __init__(self, cfg):
        """Args:
            cfg: BotMRConfig (lit slope_30_min_long, slope_30_max_short,
                 VIX_ABS_PANIC, ATR_ZSCORE_PANIC).
        """
        self.cfg = cfg

    # ------------------------------------------------------------------
    # SIGNAL 1 : SLOPE-BASED
    # ------------------------------------------------------------------
    def _signal_slope(self, bar: dict, symbol: str) -> str:
        """Vote SLOPE.

        Utilise les seuils per-symbole deja deployes Phase 2 :
          - ES : +/- 0.5 (stdev empirique 1.42)
          - NQ : +/- 3.0 (stdev empirique 8.54, 6x ES)
          - MGC/unknown : +/- 0.3 (fallback generique)

        Convention :
          - slope_30 < min_long  -> TREND_DOWN (bearish franc)
          - slope_30 > max_short -> TREND_UP (bullish franc)
          - sinon -> RANGE (neutre)

        Fail-safe : si slope_30 absent ou non-castable, vote RANGE (neutre).
        """
        raw = bar.get("vwap_slope_30")
        if raw is None:
            return REGIME_RANGE
        try:
            slope_f = float(raw)
        except (TypeError, ValueError):
            return REGIME_RANGE
        min_long = self.cfg.slope_30_min_long(symbol)
        max_short = self.cfg.slope_30_max_short(symbol)
        if slope_f < min_long:
            return REGIME_TREND_DOWN
        if slope_f > max_short:
            return REGIME_TREND_UP
        return REGIME_RANGE

    # ------------------------------------------------------------------
    # SIGNAL 2 : SWING STRUCTURE
    # ------------------------------------------------------------------
    def _signal_swing(self, bar: dict) -> str:
        """Vote SWING.

        Utilise le ratio `bars_since_last_swing_high / bars_since_last_swing_low`
        comme proxy LL/HH chain :
          - ratio > 2.0  : high tres vieux, low recent = lower lows = TREND_DOWN
          - ratio < 0.5  : low tres vieux, high recent = higher highs = TREND_UP
          - 0.5 <= ratio <= 2.0 : entre swings = RANGE

        Fail-safe :
          - fields absents -> RANGE
          - division par zero (low ou high = 0, swing simultane) -> RANGE
            (un swing a l'instant t = signal neutre, on attend confirmation)
        """
        bs_high = bar.get("bars_since_last_swing_high")
        bs_low = bar.get("bars_since_last_swing_low")
        if bs_high is None or bs_low is None:
            return REGIME_RANGE
        try:
            bs_high_f = float(bs_high)
            bs_low_f = float(bs_low)
        except (TypeError, ValueError):
            return REGIME_RANGE
        # Eviter division par zero : si l'un des deux est 0 (swing instantane)
        # ou negatif (donnee invalide), on reste neutre.
        if bs_low_f <= 0 or bs_high_f <= 0:
            return REGIME_RANGE
        ratio = bs_high_f / bs_low_f
        if ratio > self.SWING_RATIO_TREND_DOWN:
            return REGIME_TREND_DOWN
        if ratio < self.SWING_RATIO_TREND_UP:
            return REGIME_TREND_UP
        return REGIME_RANGE

    # ------------------------------------------------------------------
    # SIGNAL 3 : PANIC DETECTION
    # ------------------------------------------------------------------
    def _signal_panic(self, bar: dict) -> str:
        """Vote PANIC.

        OR logique : VIX absolu > VIX_ABS_PANIC OR ctx_atr_zscore > seuil.

        Note : ctx_atr_zscore est ABSENT des bars sierra_enriched courants
        (verifie 18/06 sur 20260615_ES). Le fallback est gracieux : on lit
        vix_level seul. Si une future version DMP ajoute le field, le check
        s'active automatiquement (zero refacto requis).

        Si aucun des deux fields ne vote PANIC -> RANGE (vote neutre dans le
        comptage majoritaire).
        """
        # VIX absolu
        vix_raw = bar.get("vix_level")
        if vix_raw is not None:
            try:
                if float(vix_raw) > self.cfg.VIX_ABS_PANIC:
                    return REGIME_PANIC
            except (TypeError, ValueError):
                pass
        # ATR z-score (peut etre absent)
        atr_raw = bar.get("ctx_atr_zscore")
        if atr_raw is not None:
            try:
                atr_z = float(atr_raw)
                # Lit seuil cfg ATR_ZSCORE_PANIC avec fallback default.
                atr_threshold = getattr(
                    self.cfg, "ATR_ZSCORE_PANIC", self.ATR_ZSCORE_PANIC_DEFAULT,
                )
                if atr_z > atr_threshold:
                    return REGIME_PANIC
            except (TypeError, ValueError):
                pass
        return REGIME_RANGE

    # ------------------------------------------------------------------
    # CLASSIFY (vote majoritaire)
    # ------------------------------------------------------------------
    def classify(self, bar: dict, symbol: str) -> RegimeVerdict:
        """Classifie le regime en agregant les 3 votes.

        Regles :
          1. PANIC PRIORITAIRE : si >= 1 vote PANIC -> verdict PANIC immediat.
          2. Sinon : argmax sur {RANGE, TREND_DOWN, TREND_UP}.

        Cas d'egalite (ex: 1 vote RANGE + 1 TREND_DOWN + 1 TREND_UP) :
          `max(dict, key=dict.get)` retourne la premiere cle avec la valeur
          maximale dans l'ordre d'insertion. Convention : on insere RANGE
          en premier, donc RANGE l'emporte en cas d'egalite parfaite.
          Conservateur : RANGE = trade autorise normal, ne bloque rien.
        """
        s_slope = self._signal_slope(bar, symbol)
        s_swing = self._signal_swing(bar)
        s_panic = self._signal_panic(bar)

        # Order matters : RANGE en premier => gagne en cas d'egalite max().
        votes = {
            REGIME_RANGE: 0,
            REGIME_TREND_DOWN: 0,
            REGIME_TREND_UP: 0,
            REGIME_PANIC: 0,
        }
        votes[s_slope] += 1
        votes[s_swing] += 1
        votes[s_panic] += 1

        signals = {"slope": s_slope, "swing": s_swing, "panic": s_panic}

        # PANIC PRIORITAIRE (1 vote suffit)
        if votes[REGIME_PANIC] > 0:
            return RegimeVerdict(
                regime=REGIME_PANIC,
                votes=votes,
                signals=signals,
                reason=f"PANIC priority (votes={votes[REGIME_PANIC]})",
            )

        # Vote majoritaire (RANGE prevaut en cas d'egalite via ordre insertion)
        regime = max(votes, key=votes.get)
        return RegimeVerdict(
            regime=regime,
            votes=votes,
            signals=signals,
            reason=f"majority vote: {votes}",
        )

    # ------------------------------------------------------------------
    # DECISION : autorise direction ?
    # ------------------------------------------------------------------
    def allows_direction(self, verdict: RegimeVerdict, direction: str) -> bool:
        """True si le regime autorise cette direction de trade.

        Matrice :
          - PANIC      : bloque tout (LONG + SHORT)
          - TREND_DOWN : bloque LONG (catch falling knife)
          - TREND_UP   : bloque SHORT (contre-trend)
          - RANGE      : autorise LONG + SHORT (mode normal MR)

        Args:
            verdict : RegimeVerdict retourne par classify()
            direction : "LONG" ou "SHORT"
        """
        if verdict.regime == REGIME_PANIC:
            return False
        if verdict.regime == REGIME_TREND_DOWN and direction == "LONG":
            return False
        if verdict.regime == REGIME_TREND_UP and direction == "SHORT":
            return False
        return True
