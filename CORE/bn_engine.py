"""bn_engine.py — Battle Navale V2 (V4 enriched, Dow Theory + Vikings vs Defenseurs).

Methodologie signature Jackson : trades en TENDANCE forte, rare mais haute qualite.

Inspire des fichiers V1 dans BATAILLE_NAVAL_BN/ (jamais valides empiriquement car
construits sur stubs Sierra). V2 utilise UNIQUEMENT les features V4 enriched
(toutes calculees par C++ DMP + rolling_features Python).

═══════════════════════════════════════════════════════════════════════════════
8 REGLES D'OR (validees Jackson 07/05/2026) :

  1. REGLE D'OR ABSOLUE
     - LONG  : aucune ROUGE (close<open) ne FERME sous une BASE VERTE
                → sinon invalidation immediate (bias bullish casse)
     - SHORT : aucune VERTE (close>open) ne FERME au-dessus d'une BASE ROUGE
                → sinon invalidation immediate (bias bearish casse)

  2. STOP NE DESCEND JAMAIS (Dow trailing pure)
     - LONG  : trail_sl monte avec chaque nouveau HL confirme, jamais arriere
     - SHORT : trail_sl descend avec chaque nouveau LH confirme, jamais arriere

  3. CASSURE CONFIRMEE + CLOSE
     - On entre / on monte le stop UNIQUEMENT quand close depasse precedent HH
     - Pas d'anticipation sur la meche/intrabar

  4. UNE SEULE VIOLATION = SORTIE
     - Pas de seconde chance, pas de "wait and see"

  5. POSITION SIZE FIXED + DRAWDOWN 7 TICKS
     - SL initial = 7 ticks (drawdown max $87.50 sur ES, $35 sur NQ micro)
     - 1 contrat micro fixed (anti panic)

  6. DIRECTION = AVEC LA TENDANCE
     - Pas de contre-trend
     - Trend direction = sequence Dow (HH+HL pour LONG, LH+LL pour SHORT)

  7. UN SETUP BN = UN TRADE
     - Pas de re-entry apres SL hit
     - Le bias est invalide, on attend un nouveau setup propre

  8. INVALIDATION QUAND SL TOUCHE
     - SL hit = setup mort, bias invalide
     - Reset etat engine, pas de "essai 2"

═══════════════════════════════════════════════════════════════════════════════

API minimale :

    engine = BNEngine(sym="NQ")
    state = BNState()                # etat persistant (track active setup)
    for bar_i in range(60, len(df)):
        result = engine.update(df.iloc[:bar_i+1], state)
        if result.signal == "LONG_ENTRY":
            print(f"Entry zone {result.entry_zone_low}-{result.entry_zone_high}, SL {result.sl}")
        elif result.action == "TRAIL_SL":
            print(f"Trail SL → {state.trail_sl}")
        elif result.action == "INVALIDATE":
            print(f"Invalidation : {result.reason}")

Date : 2026-05-07
Auteur : MIA Trading System (V2 = V4 enriched, V1 = stubs)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List

import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────

TICK_SIZE: dict[str, float] = {"NQ": 0.25, "ES": 0.25}

# Regle 5 : SL initial fixe 7 ticks
SL_INITIAL_TICKS = 7
ENTRY_ZONE_TICKS = 5            # Zone entree 5 ticks (pas un prix exact)

# Detection base (consolidation = camp)
# Jackson observation 07/05 : "1 trade/journee noir la semaine" → ~5 trades/mois
# Notre backtest precedent (5 bars min) = 1.69/jour = trop. Augmente a 8 bars
# pour vraie consolidation (= 8 min sur 1min NQ, balance area visible Steidlmayer).
BASE_MIN_DURATION = 5            # 5 bars = base minimum (compromis frequence/qualite)
# Volatilite-normalise par instrument (NQ ATR ~80t/min, ES ATR ~24t/min)
# Calibrage : ~0.5 * ATR_typique sur 8 bars
BASE_MAX_RANGE_TICKS_BY_SYM: dict[str, int] = {
    "NQ": 40,  # 10 pts NQ (ATR median ~80t/min × 0.5)
    "ES": 12,  # 3 pts ES (ATR median ~24t/min × 0.5)
}
BASE_LOOKBACK = 20               # cherche bases dans les 20 dernieres bars

# Dow trend confirmation : Jackson methode = vraie sequence Dow 3+ swings
# (Hamilton/Rhea original = 3 HH+HL pour confirmer trend, pas 2)
DOW_MIN_SWINGS = 2               # >= 2 HH + 2 HL croissants (plus permissif)

# Pyramidage : Jackson "au fur et a mesure que sa monte je recharge"
# Add 1 contrat a chaque trail confirme. Max 5 contrats (anti over-leverage).
PYRAMID_MAX_CONTRACTS = 5

# Detection swings Dow
SWING_MIN_BARS = 3               # >= 3 bars depuis pivot pour valider swing
SWING_LOOKBACK = 30              # historique swings

# Regle d'or check
GOLDEN_RULE_LOOKBACK = 30        # cherche violations dans les 30 dernieres bars
VIOLATION_TOLERANCE_TICKS = 1.0  # tolerance close violation (1 tick = bruit acceptable)


# ─── Dataclasses ──────────────────────────────────────────────────────────

@dataclass
class BNBase:
    """Zone consolidation = camp Vikings (verte) ou Defenseurs (rouge)."""
    idx_start: int
    idx_end: int
    base_high: float
    base_low: float
    base_type: str                # "green" (Vikings) | "red" (Defenseurs) | "neutral"
    range_ticks: float
    duration_bars: int
    quality: float = 0.0          # 0-1


@dataclass
class BNSwing:
    """Swing Dow : pivot HH/HL/LH/LL."""
    idx: int
    price: float
    swing_type: str               # "HH" | "HL" | "LH" | "LL"
    confirmed: bool = False       # True si close suivante valide le swing


@dataclass
class BNContract:
    """Un contrat individuel dans une position pyramide."""
    entry_idx: int
    entry_price: float
    size: int = 1


@dataclass
class BNState:
    """Etat persistant du moteur (track active setup)."""
    # Setup actif
    active: bool = False
    direction: Optional[str] = None       # "LONG" | "SHORT" | None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    sl_initial: Optional[float] = None
    trail_sl: Optional[float] = None
    last_swing_for_trail: Optional[BNSwing] = None
    last_hh_price: Optional[float] = None  # pour LONG : dernier HH casse
    last_ll_price: Optional[float] = None  # pour SHORT : dernier LL casse
    base_anchor: Optional[BNBase] = None   # base d'origine du setup
    # Pyramidage Jackson : add 1 contrat par trail confirme
    contracts: List[BNContract] = field(default_factory=list)
    # Historique
    bases_history: List[BNBase] = field(default_factory=list)
    swings_history: List[BNSwing] = field(default_factory=list)
    # Invalidation
    invalidated: bool = False
    invalidation_reason: Optional[str] = None


@dataclass
class BNResult:
    """Resultat 1 update."""
    signal: str = "NONE"          # "LONG_ENTRY" | "SHORT_ENTRY" | "NONE"
    action: str = "HOLD"          # "HOLD" | "TRAIL_SL" | "ADD_CONTRACT" | "INVALIDATE" | "EXIT_SL_HIT"
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    sl: Optional[float] = None
    new_trail_sl: Optional[float] = None
    direction: Optional[str] = None
    add_contract_price: Optional[float] = None  # Prix d'ajout pour pyramide
    n_contracts: int = 0           # nb contrats apres update
    reason: str = ""
    # Diagnostics
    current_base_type: Optional[str] = None
    n_swings: int = 0
    golden_rule_violated: bool = False


# ─── Engine ───────────────────────────────────────────────────────────────

class BNEngine:
    """Battle Navale V2 — implementation 8 regles d'or sur V4 enriched.

    Stateless detector + state object passe en argument (pure fonctionnel).
    """

    REQUIRED_OHLC = ("high", "low", "close", "open")
    OPTIONAL_FEATURES = (
        "long_up_bar", "long_dn_bar",
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "bars_since_last_swing_high", "bars_since_last_swing_low",
        "_last_swing_high_price", "_last_swing_low_price",
    )

    def __init__(self, sym: str = "NQ"):
        if sym not in TICK_SIZE:
            raise ValueError(f"Instrument inconnu: {sym}")
        self.sym = sym
        self.tick_size = TICK_SIZE[sym]
        self.sl_initial_pts = SL_INITIAL_TICKS * self.tick_size
        self.entry_zone_pts = ENTRY_ZONE_TICKS * self.tick_size
        self.base_max_range_ticks = BASE_MAX_RANGE_TICKS_BY_SYM.get(sym, 40)

    # ─── Detection helpers ───

    def _detect_base(self, df: pd.DataFrame, end_idx: int) -> Optional[BNBase]:
        """Detecte une base de consolidation finissant au plus tard a end_idx.

        Une base = >= BASE_MIN_DURATION bars consecutives dans une zone serree
        (range <= BASE_MAX_RANGE_TICKS), avec couleur dominante.
        """
        if end_idx < BASE_MIN_DURATION - 1:
            return None

        # FIX C1 : keep BEST (longest) base, pas le premier match
        best_base = None
        for start in range(max(0, end_idx - BASE_LOOKBACK), end_idx - BASE_MIN_DURATION + 2):
            window = df.iloc[start:end_idx + 1]
            if len(window) < BASE_MIN_DURATION:
                continue

            highs = window["high"].to_numpy()
            lows = window["low"].to_numpy()
            opens = window["open"].to_numpy()
            closes = window["close"].to_numpy()

            range_pts = float(highs.max() - lows.min())
            range_ticks = range_pts / self.tick_size

            if range_ticks > self.base_max_range_ticks:
                continue

            # Couleur dominante : compte bougies vertes vs rouges
            n_green = int(np.sum(closes > opens))
            n_red = int(np.sum(closes < opens))
            n_total = len(window)

            if n_green >= int(0.6 * n_total):
                base_type = "green"
            elif n_red >= int(0.6 * n_total):
                base_type = "red"
            else:
                base_type = "neutral"

            # Quality = 0.5 base + 0.5 selon "puretee" couleur
            purity = max(n_green, n_red) / max(n_total, 1)
            quality = 0.5 + 0.5 * purity

            candidate = BNBase(
                idx_start=start,
                idx_end=end_idx,
                base_high=float(highs.max()),
                base_low=float(lows.min()),
                base_type=base_type,
                range_ticks=range_ticks,
                duration_bars=n_total,
                quality=quality,
            )
            # Garder la plus longue (priorite duration > quality si egal)
            if best_base is None or candidate.duration_bars > best_base.duration_bars:
                best_base = candidate
            elif candidate.duration_bars == best_base.duration_bars and candidate.quality > best_base.quality:
                best_base = candidate

        return best_base

    def _detect_swings(self, df: pd.DataFrame, end_idx: int) -> List[BNSwing]:
        """Detecte les swings (HH/HL/LH/LL) sur les SWING_LOOKBACK dernieres bars.

        Utilise pivots simples : un haut local est confirme apres SWING_MIN_BARS bars
        sans nouveau plus haut.
        """
        if end_idx < SWING_MIN_BARS * 2:
            return []

        start = max(0, end_idx - SWING_LOOKBACK)
        window = df.iloc[start:end_idx + 1]
        highs = window["high"].to_numpy()
        lows = window["low"].to_numpy()

        swings: List[BNSwing] = []
        n = len(window)

        # Pivots highs (LH ou HH selon direction)
        for i in range(SWING_MIN_BARS, n - SWING_MIN_BARS):
            left = highs[i - SWING_MIN_BARS:i]
            right = highs[i + 1:i + SWING_MIN_BARS + 1]
            if highs[i] > left.max() and highs[i] > right.max():
                # Determine HH ou LH par rapport au precedent pivot high
                prev_highs = [s for s in swings if s.swing_type in ("HH", "LH")]
                if prev_highs and highs[i] > prev_highs[-1].price:
                    swing_type = "HH"
                elif prev_highs and highs[i] < prev_highs[-1].price:
                    swing_type = "LH"
                else:
                    swing_type = "HH"  # premier pivot = HH par defaut
                swings.append(BNSwing(
                    idx=start + i, price=float(highs[i]),
                    swing_type=swing_type, confirmed=True
                ))

        # Pivots lows (HL ou LL)
        for i in range(SWING_MIN_BARS, n - SWING_MIN_BARS):
            left = lows[i - SWING_MIN_BARS:i]
            right = lows[i + 1:i + SWING_MIN_BARS + 1]
            if lows[i] < left.min() and lows[i] < right.min():
                prev_lows = [s for s in swings if s.swing_type in ("HL", "LL")]
                if prev_lows and lows[i] > prev_lows[-1].price:
                    swing_type = "HL"
                elif prev_lows and lows[i] < prev_lows[-1].price:
                    swing_type = "LL"
                else:
                    swing_type = "HL"
                swings.append(BNSwing(
                    idx=start + i, price=float(lows[i]),
                    swing_type=swing_type, confirmed=True
                ))

        # Tri par idx
        swings.sort(key=lambda s: s.idx)
        return swings

    def _is_uptrend_dow(self, swings: List[BNSwing]) -> bool:
        """Trend up Dow = >= DOW_MIN_SWINGS HH croissants ET HL croissants.

        Hamilton/Rhea (Dow Theory original) : 3 HH+HL successifs requis.
        2 etait laxiste, 3 = vraie sequence trend confirmee.
        """
        sorted_sw = sorted(swings, key=lambda s: s.idx)
        hhs = [s for s in sorted_sw if s.swing_type == "HH"]
        hls = [s for s in sorted_sw if s.swing_type == "HL"]
        if len(hhs) < DOW_MIN_SWINGS or len(hls) < DOW_MIN_SWINGS:
            return False
        # Verifier monotonie croissante stricte des N derniers HH et HL
        last_hhs = hhs[-DOW_MIN_SWINGS:]
        last_hls = hls[-DOW_MIN_SWINGS:]
        for i in range(1, DOW_MIN_SWINGS):
            if last_hhs[i].price <= last_hhs[i - 1].price:
                return False
            if last_hls[i].price <= last_hls[i - 1].price:
                return False
        return True

    def _is_downtrend_dow(self, swings: List[BNSwing]) -> bool:
        sorted_sw = sorted(swings, key=lambda s: s.idx)
        lhs = [s for s in sorted_sw if s.swing_type == "LH"]
        lls = [s for s in sorted_sw if s.swing_type == "LL"]
        if len(lhs) < DOW_MIN_SWINGS or len(lls) < DOW_MIN_SWINGS:
            return False
        last_lhs = lhs[-DOW_MIN_SWINGS:]
        last_lls = lls[-DOW_MIN_SWINGS:]
        for i in range(1, DOW_MIN_SWINGS):
            if last_lhs[i].price >= last_lhs[i - 1].price:
                return False
            if last_lls[i].price >= last_lls[i - 1].price:
                return False
        return True

    def _check_golden_rule(
        self,
        df: pd.DataFrame,
        end_idx: int,
        base: BNBase,
        direction: str,
    ) -> bool:
        """Regle d'or : detecte si une bougie de couleur opposee a CLOSE
        sous (LONG) / sur (SHORT) la base d'origine.

        Returns True si VIOLATION detectee → invalidation.
        """
        start = max(base.idx_end + 1, end_idx - GOLDEN_RULE_LOOKBACK)
        if start > end_idx:
            return False

        window = df.iloc[start:end_idx + 1]
        opens = window["open"].to_numpy()
        closes = window["close"].to_numpy()
        tol = VIOLATION_TOLERANCE_TICKS * self.tick_size

        if direction == "LONG":
            # Cherche ROUGE qui ferme SOUS base_low
            for i in range(len(window)):
                if closes[i] < opens[i] and closes[i] < (base.base_low - tol):
                    return True
        elif direction == "SHORT":
            # Cherche VERTE qui ferme AU-DESSUS base_high
            for i in range(len(window)):
                if closes[i] > opens[i] and closes[i] > (base.base_high + tol):
                    return True
        return False

    def _check_breakout_close(
        self,
        df: pd.DataFrame,
        end_idx: int,
        ref_price: float,
        direction: str,
    ) -> bool:
        """Regle 3 : close au-dessus (LONG) / sous (SHORT) ref_price.

        Strict : on attend la close, pas la meche.
        """
        if end_idx < 0 or end_idx >= len(df):
            return False
        close = float(df.iloc[end_idx]["close"])
        tol = VIOLATION_TOLERANCE_TICKS * self.tick_size

        if direction == "LONG":
            return close > (ref_price + tol)
        elif direction == "SHORT":
            return close < (ref_price - tol)
        return False

    # ─── API publique ───

    def update(self, df: pd.DataFrame, state: BNState) -> BNResult:
        """Update etat sur la derniere bar de df. Modifie state in-place.

        Returns BNResult avec action a prendre (HOLD, TRAIL_SL, INVALIDATE, etc.).
        """
        result = BNResult()

        if len(df) < BASE_MIN_DURATION + SWING_MIN_BARS * 2:
            result.reason = "insufficient_bars"
            return result

        end_idx = len(df) - 1
        last_bar = df.iloc[end_idx]
        last_close = float(last_bar["close"])

        # === SI SETUP ACTIF : verifier invalidation + trailing ===
        if state.active and state.base_anchor is not None and state.direction is not None:
            # FIX C2 : SL hit sur low/high intra-bar (pas close) — un STOP s'execute intra-bar
            last_low = float(last_bar["low"])
            last_high = float(last_bar["high"])
            sl_to_check = state.trail_sl if state.trail_sl is not None else state.sl_initial
            if state.direction == "LONG" and last_low <= sl_to_check:
                state.invalidated = True
                state.invalidation_reason = "sl_hit"
                state.active = False
                result.action = "EXIT_SL_HIT"
                result.sl = sl_to_check
                result.reason = f"low {last_low} <= SL {sl_to_check}"
                return result
            if state.direction == "SHORT" and last_high >= sl_to_check:
                state.invalidated = True
                state.invalidation_reason = "sl_hit"
                state.active = False
                result.action = "EXIT_SL_HIT"
                result.sl = sl_to_check
                result.reason = f"high {last_high} >= SL {sl_to_check}"
                return result

            # Regle 1 : Golden rule violation
            if self._check_golden_rule(df, end_idx, state.base_anchor, state.direction):
                state.invalidated = True
                state.invalidation_reason = "golden_rule"
                state.active = False
                result.action = "INVALIDATE"
                result.reason = "golden_rule_violated"
                result.golden_rule_violated = True
                return result

            # Regle 2+3 : trailing stop si nouvelle cassure HH (LONG) / LL (SHORT)
            swings = self._detect_swings(df, end_idx)
            result.n_swings = len(swings)

            if state.direction == "LONG":
                # FIX M4 + M6 : ref de cassure = HH connu PRECEDENT (state.last_hh_price), pas le HH detecte.
                # Trail = max(HL nouveaux), pas le dernier (un HL non-croissant signale fin de trend).
                ref_idx = state.last_swing_for_trail.idx if state.last_swing_for_trail else -1
                new_hhs = [s for s in swings if s.swing_type == "HH" and s.idx > ref_idx]
                new_hls = [s for s in swings if s.swing_type == "HL" and s.idx > ref_idx]
                if new_hhs and new_hls:
                    last_hh = max(new_hhs, key=lambda s: s.price)
                    # Cassure confirmee : close > precedent HH (state.last_hh_price)
                    ref_break = state.last_hh_price if state.last_hh_price is not None else last_hh.price
                    if last_hh.price > (state.last_hh_price or 0):
                        if self._check_breakout_close(df, end_idx, ref_break, "LONG"):
                            # Trail SL = MAX HL
                            new_trail = max(s.price for s in new_hls)
                            if state.trail_sl is None or new_trail > state.trail_sl:
                                state.trail_sl = new_trail
                                state.last_swing_for_trail = max(new_hls, key=lambda s: s.price)
                                state.last_hh_price = last_hh.price
                                # PYRAMIDE : add 1 contrat (Jackson "je recharge")
                                if len(state.contracts) < PYRAMID_MAX_CONTRACTS:
                                    state.contracts.append(BNContract(
                                        entry_idx=end_idx, entry_price=last_close, size=1,
                                    ))
                                    result.action = "ADD_CONTRACT"
                                    result.add_contract_price = last_close
                                else:
                                    result.action = "TRAIL_SL"
                                result.new_trail_sl = new_trail
                                result.n_contracts = len(state.contracts)
                                result.reason = (
                                    f"HH break confirmed close > {ref_break}, trail to max HL {new_trail}, "
                                    f"contracts={len(state.contracts)}"
                                )
                                return result
            else:  # SHORT
                ref_idx = state.last_swing_for_trail.idx if state.last_swing_for_trail else -1
                new_lls = [s for s in swings if s.swing_type == "LL" and s.idx > ref_idx]
                new_lhs = [s for s in swings if s.swing_type == "LH" and s.idx > ref_idx]
                if new_lls and new_lhs:
                    last_ll = min(new_lls, key=lambda s: s.price)
                    ref_break = state.last_ll_price if state.last_ll_price is not None else last_ll.price
                    if last_ll.price < (state.last_ll_price or float('inf')):
                        if self._check_breakout_close(df, end_idx, ref_break, "SHORT"):
                            new_trail = min(s.price for s in new_lhs)
                            if state.trail_sl is None or new_trail < state.trail_sl:
                                state.trail_sl = new_trail
                                state.last_swing_for_trail = min(new_lhs, key=lambda s: s.price)
                                state.last_ll_price = last_ll.price
                                if len(state.contracts) < PYRAMID_MAX_CONTRACTS:
                                    state.contracts.append(BNContract(
                                        entry_idx=end_idx, entry_price=last_close, size=1,
                                    ))
                                    result.action = "ADD_CONTRACT"
                                    result.add_contract_price = last_close
                                else:
                                    result.action = "TRAIL_SL"
                                result.new_trail_sl = new_trail
                                result.n_contracts = len(state.contracts)
                                result.reason = (
                                    f"LL break confirmed close < {ref_break}, trail to min LH {new_trail}, "
                                    f"contracts={len(state.contracts)}"
                                )
                                return result

            result.action = "HOLD"
            result.reason = "setup_active_no_change"
            return result

        # === PAS DE SETUP ACTIF : chercher nouveau setup (apres invalidation OK) ===
        base = self._detect_base(df, end_idx - 1)  # base finissant avant la bar courante
        if base is None or base.base_type == "neutral":
            result.reason = "no_clear_base"
            result.current_base_type = base.base_type if base else None
            return result

        # FIX M5 : Regle 7 reelle = pas de re-entry sur la MEME base apres invalidation.
        # Si invalidated et la base detectee chevauche l'ancienne base_anchor, skip.
        if state.invalidated and state.base_anchor is not None:
            if base.idx_start <= state.base_anchor.idx_end:
                result.reason = "regle7_meme_base_invalidee"
                result.current_base_type = base.base_type
                return result

        result.current_base_type = base.base_type

        swings = self._detect_swings(df, end_idx)
        result.n_swings = len(swings)
        if len(swings) < 4:
            result.reason = "insufficient_swings"
            return result

        # Regle 6 : direction = avec la tendance Dow
        if base.base_type == "green" and self._is_uptrend_dow(swings):
            # Setup LONG potentiel : cherche cassure HH avec close
            sorted_hhs = sorted(
                [s for s in swings if s.swing_type == "HH"],
                key=lambda s: s.idx,
            )
            if len(sorted_hhs) < 2:
                result.reason = "no_HH_to_break"
                return result

            # FIX M6 : ref de cassure = AVANT-DERNIER HH (le HH precedent), pas le dernier
            ref_hh = sorted_hhs[-2]
            last_hh = sorted_hhs[-1]
            # Regle 3 : close confirmee au-dessus du HH precedent
            if not self._check_breakout_close(df, end_idx, ref_hh.price, "LONG"):
                result.reason = "no_breakout_close_LONG"
                return result

            # Regle 1 : pas de violation golden rule deja presente
            if self._check_golden_rule(df, end_idx, base, "LONG"):
                result.reason = "golden_rule_already_violated"
                result.golden_rule_violated = True
                return result

            # SETUP LONG VALIDE
            entry_mid = last_close
            entry_low = entry_mid - (self.entry_zone_pts / 2.0)
            entry_high = entry_mid + (self.entry_zone_pts / 2.0)
            sl = base.base_low - self.sl_initial_pts  # SL sous base + 7 ticks safety

            state.active = True
            state.direction = "LONG"
            state.entry_zone_low = entry_low
            state.entry_zone_high = entry_high
            state.sl_initial = sl
            state.trail_sl = sl
            state.last_hh_price = last_hh.price
            state.base_anchor = base
            state.invalidated = False
            state.bases_history.append(base)
            # 1er contrat
            state.contracts = [BNContract(entry_idx=end_idx, entry_price=last_close, size=1)]

            result.signal = "LONG_ENTRY"
            result.action = "ENTRY"
            result.entry_zone_low = entry_low
            result.entry_zone_high = entry_high
            result.sl = sl
            result.direction = "LONG"
            result.n_contracts = 1
            result.reason = f"green_base + uptrend Dow + close > HH ref {ref_hh.price}"
            return result

        if base.base_type == "red" and self._is_downtrend_dow(swings):
            sorted_lls = sorted(
                [s for s in swings if s.swing_type == "LL"],
                key=lambda s: s.idx,
            )
            if len(sorted_lls) < 2:
                result.reason = "no_LL_to_break"
                return result

            ref_ll = sorted_lls[-2]
            last_ll = sorted_lls[-1]
            if not self._check_breakout_close(df, end_idx, ref_ll.price, "SHORT"):
                result.reason = "no_breakout_close_SHORT"
                return result

            if self._check_golden_rule(df, end_idx, base, "SHORT"):
                result.reason = "golden_rule_already_violated"
                result.golden_rule_violated = True
                return result

            entry_mid = last_close
            entry_low = entry_mid - (self.entry_zone_pts / 2.0)
            entry_high = entry_mid + (self.entry_zone_pts / 2.0)
            sl = base.base_high + self.sl_initial_pts

            state.active = True
            state.direction = "SHORT"
            state.entry_zone_low = entry_low
            state.entry_zone_high = entry_high
            state.sl_initial = sl
            state.trail_sl = sl
            state.last_ll_price = last_ll.price
            state.base_anchor = base
            state.invalidated = False
            state.bases_history.append(base)
            state.contracts = [BNContract(entry_idx=end_idx, entry_price=last_close, size=1)]

            result.signal = "SHORT_ENTRY"
            result.action = "ENTRY"
            result.entry_zone_low = entry_low
            result.entry_zone_high = entry_high
            result.sl = sl
            result.direction = "SHORT"
            result.n_contracts = 1
            result.reason = f"red_base + downtrend Dow + close < LL ref {ref_ll.price}"
            return result

        result.reason = "no_setup_aligned"
        return result
