"""bn_v3_engine.py — Battle Navale V3 (Dow Theory + Linda Raschke Holy Grail).

Mission : detection setup BN sur PULLBACK (vs BN V2 qui entrait sur breakout = late).
Base sur literature pro :
  - Dow Theory : trend = HH+HL successifs (LONG) ou LH+LL (SHORT)
  - Linda Raschke "Holy Grail" : entry sur 1ere pullback en trend fort (ADX>25 + EMA20)
  - Fibonacci : pullback 30-62% acceptable, >62% = trend casse
  - Range detector V3 : anti-filtre pour eviter trades en range

8 regles d'or (validees Jackson 07/05) — implementation V3 :
  1. REGLE OR ABSOLUE : aucune rouge ne ferme sous base verte (sinon invalidation)
     -> V3 : SL = pullback_low - 4t (LONG) / pullback_high + 4t (SHORT). Si bar rouge
     ferme sous SL = exit. Pas de check explicite "rouge < base verte" (le SL au
     pullback_low est l'enveloppe de cette regle dans le contexte Dow + Fibo).
  2. STOP NE DESCEND JAMAIS (Dow trailing pure)
     -> V3 : detect_recharge() preserve state.sl_price (regle 2 commentee L605)
  3. CASSURE CONFIRMEE + CLOSE (pas anticipation)
     -> V3 : Dow trend confirmation = 3 HH+HL ou LH+LL successifs CLOTURES (pas wick)
  4. UNE SEULE VIOLATION = SORTIE
     -> V3 : SL hit unique -> _flatten() immediat (paper_loop:_check_active_position)
  5. POSITION SIZE FIXED + DRAWDOWN 7 TICKS
     -> V3 : N_CONTRACTS_INITIAL=2 fixe, drawdown gere via SL pullback_low - 4t
     buffer (vs 7t BN V2 - relaxe sur Fibo 30-62%)
  6. DIRECTION = AVEC TENDANCE (pas contre-trend)
     -> V3 : EMA(20) slope direction filter + Dow trend obligatoire
  7. UN SETUP BN = UN TRADE (pas re-entry)
     -> V3 : state.last_setup_idx anti re-entry < 10 bars
  8. SL HIT = BIAS INVALIDE
     -> V3 : state.invalidated=True post SL_HIT (BNV3State.invalidation_reason)

Triple confirmation anti-range (Jackson 07/05 "si marche en range on peut se faire avoir") :
  - Range detector V3 (range_detector_v3.py) : si is_range=True -> SKIP
  - ADX(14) > 25 : trend fort confirme (Holy Grail strict 30, on relache 25)
  - EMA(20) slope > 0 (LONG) ou < 0 (SHORT) : direction confirmee

Pullback Fibonacci :
  - 30-62% du dernier swing (HH-HL pour LONG, LL-LH pour SHORT)
  - Si <30% : trop shallow, pas de retracement reel
  - Si >62% : trend casse, on n'entre pas

API standalone (peut s'integrer Bot 2 V6 paper Sim2 OU Bot 3 Sim1) :

    engine = BNV3Engine(sym="NQ")
    state = BNV3State()
    for bar_i in range(60, len(df)):
        result = engine.detect(df.iloc[:bar_i+1], state)
        if result.signal == "LONG_ENTRY":
            print(f"Entry @{result.entry_price}, SL {result.sl}, TP {result.tp_partial}")

Date : 2026-05-07
Auteur : MIA Trading System (BN V3 = redesign apres BN V2 NOGO empirique 0/4 detections)
References pro :
  - https://oxfordstrat.com/trading-strategies/dow-theory-trend/ (Dow pullback strategy)
  - https://tradersmastermind.com/linda-raschke-trading-strategy/ (Holy Grail)
  - https://damnpropfirms.com/.../how-to-trade-nq-pullbacks-without-chasing-like-an-idiot/ (NQ pullback)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List

import logging
import numpy as np
import pandas as pd

from CORE.range_detector import atr_wilder, adx_wilder

log = logging.getLogger(__name__)


# ─── Config ────────────────────────────────────────────────────────────────

TICK_SIZE: dict[str, float] = {"NQ": 0.25, "ES": 0.25}

# Detection swings Dow (Jackson observation 4 jours = pullback median 60-90t)
SWING_MIN_BARS = 3                     # Pivot confirme apres 3 bars sans depassement
SWING_LOOKBACK = 90                    # Cherche pivots dans les 90 dernieres bars (vs 30 BN V2)
DOW_MIN_SWINGS = 3                     # 3 HH+HL ou LH+LL successifs (Dow strict)

# Pullback Fibonacci (validee literature pro)
PULLBACK_MIN_RATIO = 0.30              # 30% min (sinon trop shallow = pas de pullback reel)
PULLBACK_MAX_RATIO = 0.62              # 62% max (Fibonacci 61.8% = limite trend casse)

# Holy Grail Linda Raschke (relachement vs strict 30 → 25 pour plus de signaux)
ADX_MIN_TREND = 25.0                   # ADX(14) > 25 = trend fort
EMA_PERIOD = 20                        # EMA(20) Holy Grail standard

# Confirmation rebond (1 bar par defaut, ajustable)
REBOUND_CONFIRMATION_BARS = 1          # 1 bar verte (LONG) ou rouge (SHORT) apres pullback bottom

# SL/TP (Jackson scale-out + BE confirme weekend specs)
SL_BUFFER_TICKS = 4                    # 4t sous HL (LONG) ou sur LH (SHORT)
SCALE_OUT_TRIGGER_TICKS = {"NQ": 60, "ES": 25}   # MFE 60t NQ = $60 (50% scale-out)
SCALE_OUT_PCT = 0.50                   # 50% de position fermee au trigger

# Sizing Jackson 07/05 directive : Bot 2 EXCLUSIF, 2 contrats init + recharge Long Up/Dn Bar
N_CONTRACTS_INITIAL = 2                # 2 micros entry (vs 4)
MAX_PYRAMID_LOADS = 2                  # Recharges max (cap anti pattern 11) -> total max 4 micros
RECHARGE_TRIGGER_LONG = "long_up_bar"  # Feature parquet v4 enrichi (Bot 2 Databento) : Long Up Bar
RECHARGE_TRIGGER_SHORT = "long_dn_bar" # Feature parquet v4 enrichi (Bot 2 Databento) : Long Down Bar
# Note: noms differents selon source. JSONL DMP brut = bn_long_up/bn_long_dn,
# parquet v4 enrichi = long_up_bar/long_dn_bar. Bot 2 utilise parquet v4.
RECHARGE_MIN_BARS_GAP = 3              # Au moins 3 bars entre 2 recharges (anti spam)

# Anti-range (recycle range_detector_v3)
USE_RANGE_DETECTOR_FILTER = True       # Si range_detector dit is_range=True -> SKIP

# ─── Mode 2 : amorce post-consolidation/range break (Jackson 13/05) ───
# Philosophie : la BN demarre TRES SOUVENT apres une consolidation laterale.
# V3 Mode 1 (Holy Grail pullback) attend tendance Dow confirmee = rate l'amorce.
# Mode 2 = entry sur cassure franche du range avec volume + confirmation footprint.
# Mutuellement exclusif avec Mode 1 (premier qui declenche).
MODE2_LOOKBACK_RANGE_BARS = 30         # Range doit avoir ete vu sur les 30 dernieres bars
MODE2_VOL_RATIO_MIN = 1.8              # Volume bar cassure > 1.8x rolling_mean_30
MODE2_VOL_LOOKBACK = 30                # Fenetre rolling_mean volume
MODE2_BREAKOUT_BUFFER_TICKS = 2        # Cassure confirmee si close > range_high + 2t (ou < range_low - 2t)
MODE2_SL_INITIAL_TICKS = 80            # Stop initial 20 pts NQ sous entry (Jackson 13/05 "28680 pour 28700")
MODE2_TP_PROJECTION_RATIO = 1.5        # TP = range_size * 1.5 (projection Crabel mesuree)
MODE2_TP_CAP_TICKS = {"NQ": 200, "ES": 80}  # Cap TP pour ne pas demander la lune
MODE2_DIST_SWING_VETO_ATR = 0.3        # Veto si close trop pres swing extreme (Jackson 11/05)
MODE2_DIST_MQ_VETO_ATR = 0.3           # Veto si breakout dans un mur MenthorQ < 0.3 ATR
MODE2_COOLDOWN_BARS = 60               # Anti re-entry sur meme range : 60 bars cooldown

# ─── Mode 3 : amorce post-capitulation V-bottom / Λ-top (Jackson 13/05) ───
# Philosophie : "apres une descente et un depart en V" — capitulation vendeurs
# + absorption institutionnelle + rebound violent. Cf trade ref Jackson 20/04 NQ
# (drop -208 pts en 90min puis +124 pts en 22min).
# 3 fixes methodologiques (audit market-analyst 13/05) vs v_reversal.py original :
#   #1 : footprint relaxe -> long_up_bar=1 sur barre OU color_up sur 2/3 dernieres
#   #2 : vol baseline calculee sur 20 bars AVANT le drop (pre-capitulation), pas glissant
#   #3 : filtre MenthorQ key levels + distinction post-range vs post-trend
MODE3_LOOKBACK_DROP_BARS = 15          # Fenetre detection capitulation (15 bars)
MODE3_DROP_MIN_ATR = 2.5               # Drop >= 2.5 ATR sur les 15 dernieres bars
MODE3_BARS_SINCE_LOW_MAX = 5           # Low recent : <= 5 bars apres le low absolu
MODE3_VOL_RATIO_MIN = 2.0              # Vol rebound > 2.0x vol pre-drop baseline (FIX #2)
MODE3_VOL_PRE_DROP_LOOKBACK = 20       # 20 bars AVANT le drop pour baseline (FIX #2)
MODE3_COLOR_CONFIRM_BARS = 3           # Footprint relaxe : color_up sur 2/3 dernieres (FIX #1)
MODE3_MQ_KEY_LEVEL_VETO_ATR = 1.0      # Veto si V trop loin du support options (FIX #3)
MODE3_SL_BUFFER_TICKS = 6              # SL = swing_low - 6 ticks (NQ buffer V-bottom)
MODE3_TP_FIB_RATIO = 0.50              # TP partial = 50% Fib retracement du drop
MODE3_TP_MIN_TICKS = {"NQ": 40, "ES": 16}   # TP minimum (eviter trades nuls)
MODE3_TP_MAX_TICKS = {"NQ": 120, "ES": 48}  # TP maximum (cap raisonnable)
MODE3_COOLDOWN_BARS = 60               # Anti re-entry meme V-bottom


# ─── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class BNV3Swing:
    """Pivot Dow : HH/HL/LH/LL."""
    idx: int
    price: float
    swing_type: str                    # HIGH | LOW
    dow: str                           # HH | HL | LH | LL
    confirmed: bool = True


@dataclass
class BNV3State:
    """Etat persistant moteur (track active setup, anti re-entry, recharges)."""
    active: bool = False
    direction: Optional[str] = None    # LONG | SHORT
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_partial_price: Optional[float] = None
    last_setup_idx: int = -1           # idx du dernier setup pour anti re-entry
    invalidated: bool = False
    invalidation_reason: Optional[str] = None
    # Pyramiding (07/05 Jackson directive)
    n_contracts_loaded: int = 0        # Total contrats charges (init + recharges)
    n_recharges: int = 0               # Nombre de recharges effectuees
    last_recharge_idx: int = -1        # idx derniere recharge (anti spam)
    # Amorce tracking (Jackson 13/05 : 3 portes d'entree BN)
    amorce_mode: Optional[str] = None  # "HOLY_GRAIL" (Mode 1) | "RANGE_BREAK" (Mode 2) | "V_REVERSAL" (Mode 3)
    last_mode2_idx: int = -1           # idx derniere amorce Mode 2 (anti re-entry meme range)
    last_mode3_idx: int = -1           # idx derniere amorce Mode 3 (anti re-entry meme V-bottom)


@dataclass
class BNV3Result:
    """Resultat 1 detection."""
    signal: str = "NONE"               # LONG_ENTRY | SHORT_ENTRY | RECHARGE_LONG | RECHARGE_SHORT | NONE
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_partial_price: Optional[float] = None
    n_contracts: int = 0               # Quantite a envoyer (initial=2, recharge=1)

    # Diagnostics (pour audit + tests)
    n_swings: int = 0
    n_hh: int = 0
    n_hl: int = 0
    n_lh: int = 0
    n_ll: int = 0
    is_uptrend_dow: bool = False
    is_downtrend_dow: bool = False
    is_range: bool = False
    adx: Optional[float] = None
    adx_ok: bool = False
    ema20_slope: Optional[float] = None
    ema20_ok: bool = False
    pullback_ratio: Optional[float] = None
    pullback_ok: bool = False
    rebound_confirmed: bool = False
    reject_reason: str = ""


# ─── Engine ────────────────────────────────────────────────────────────────

class BNV3Engine:
    """BN V3 detection : Dow + Holy Grail + Fibonacci pullback + anti-range.

    Usage standalone (deployable Bot 2 Sim2 OU Bot 3 Sim1) :
        eng = BNV3Engine(sym="NQ")
        state = BNV3State()
        result = eng.detect(df, state)
        if result.signal == "LONG_ENTRY":
            # send order via DTC executor
    """

    REQUIRED_OHLC = ("high", "low", "close", "open")

    def __init__(self, sym: str = "NQ",
                 swing_min_bars: int = SWING_MIN_BARS,
                 swing_lookback: int = SWING_LOOKBACK,
                 dow_min_swings: int = DOW_MIN_SWINGS,
                 pullback_min: float = PULLBACK_MIN_RATIO,
                 pullback_max: float = PULLBACK_MAX_RATIO,
                 adx_min: float = ADX_MIN_TREND,
                 ema_period: int = EMA_PERIOD,
                 use_range_filter: bool = USE_RANGE_DETECTOR_FILTER,
                 enable_mode2_range_break: bool = False,
                 enable_mode3_v_reversal: bool = False):
        if sym not in TICK_SIZE:
            raise ValueError(f"Instrument inconnu: {sym}")
        self.sym = sym
        self.tick_size = TICK_SIZE[sym]
        self.swing_min_bars = swing_min_bars
        self.swing_lookback = swing_lookback
        self.dow_min_swings = dow_min_swings
        self.pullback_min = pullback_min
        self.pullback_max = pullback_max
        self.adx_min = adx_min
        self.ema_period = ema_period
        self.use_range_filter = use_range_filter
        self.enable_mode2_range_break = enable_mode2_range_break
        self.enable_mode3_v_reversal = enable_mode3_v_reversal

        # Range detector (lazy import pour eviter dependance circulaire)
        self._range_detector = None
        if use_range_filter:
            try:
                from CORE.range_detector_v3 import RangeDetectorV3
                self._range_detector = RangeDetectorV3(sym=sym)
            except ImportError:
                log.warning("range_detector_v3 import fail -> range filter desactive")
                self.use_range_filter = False

    # ─── Helpers ───

    def _validate_input(self, df: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_OHLC if c not in df.columns]
        if missing:
            raise ValueError(f"Colonnes OHLC manquantes: {missing}")

    def _detect_swings(self, df: pd.DataFrame) -> List[BNV3Swing]:
        """Detecte tous les swings HH/HL/LH/LL sur SWING_LOOKBACK dernieres bars."""
        n = len(df)
        if n < self.swing_min_bars * 2:
            return []
        start = max(0, n - self.swing_lookback)
        w = df.iloc[start:n].reset_index(drop=True)
        highs = w["high"].to_numpy()
        lows = w["low"].to_numpy()

        swings: List[BNV3Swing] = []
        n_w = len(w)

        # Pivots highs
        for i in range(self.swing_min_bars, n_w - self.swing_min_bars):
            left = highs[i - self.swing_min_bars:i]
            right = highs[i + 1:i + self.swing_min_bars + 1]
            if highs[i] > left.max() and highs[i] > right.max():
                swings.append(BNV3Swing(
                    idx=start + i, price=float(highs[i]),
                    swing_type="HIGH", dow="?",
                ))

        # Pivots lows
        for i in range(self.swing_min_bars, n_w - self.swing_min_bars):
            left = lows[i - self.swing_min_bars:i]
            right = lows[i + 1:i + self.swing_min_bars + 1]
            if lows[i] < left.min() and lows[i] < right.min():
                swings.append(BNV3Swing(
                    idx=start + i, price=float(lows[i]),
                    swing_type="LOW", dow="?",
                ))

        # Tri ordre temporel
        swings.sort(key=lambda s: s.idx)

        # Classify HH/LH/HL/LL
        last_h = None
        last_l = None
        for s in swings:
            if s.swing_type == "HIGH":
                if last_h is None or s.price > last_h:
                    s.dow = "HH"
                else:
                    s.dow = "LH"
                last_h = s.price
            else:
                if last_l is None or s.price > last_l:
                    s.dow = "HL"
                else:
                    s.dow = "LL"
                last_l = s.price
        return swings

    def _is_uptrend_dow(self, swings: List[BNV3Swing]) -> bool:
        """Trend up Dow strict : >= N HH croissants ET HL croissants successifs."""
        hhs = [s for s in swings if s.dow == "HH"]
        hls = [s for s in swings if s.dow == "HL"]
        if len(hhs) < self.dow_min_swings or len(hls) < self.dow_min_swings:
            return False
        # Verifier monotonie croissante des N derniers
        last_hhs = hhs[-self.dow_min_swings:]
        last_hls = hls[-self.dow_min_swings:]
        for i in range(1, self.dow_min_swings):
            if last_hhs[i].price <= last_hhs[i - 1].price:
                return False
            if last_hls[i].price <= last_hls[i - 1].price:
                return False
        return True

    def _is_downtrend_dow(self, swings: List[BNV3Swing]) -> bool:
        lhs = [s for s in swings if s.dow == "LH"]
        lls = [s for s in swings if s.dow == "LL"]
        if len(lhs) < self.dow_min_swings or len(lls) < self.dow_min_swings:
            return False
        last_lhs = lhs[-self.dow_min_swings:]
        last_lls = lls[-self.dow_min_swings:]
        for i in range(1, self.dow_min_swings):
            if last_lhs[i].price >= last_lhs[i - 1].price:
                return False
            if last_lls[i].price >= last_lls[i - 1].price:
                return False
        return True

    def _compute_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _check_adx(self, df: pd.DataFrame) -> tuple[float, bool]:
        """Calcule ADX(14) et retourne (value, ok=value>=adx_min). R1 fix : fail-loud."""
        try:
            highs = df["high"].to_numpy(dtype=np.float64)
            lows = df["low"].to_numpy(dtype=np.float64)
            closes = df["close"].to_numpy(dtype=np.float64)
            adx = adx_wilder(highs, lows, closes, n=14)
            if np.isnan(adx):
                return 0.0, False
            return float(adx), float(adx) >= self.adx_min
        except Exception as e:
            log.warning(f"BNV3 ADX compute fail: {type(e).__name__}: {e}")
            return 0.0, False

    def _check_ema_slope(self, df: pd.DataFrame, direction: str) -> tuple[float, bool]:
        """Verifie EMA(20) slope dans la bonne direction.

        LONG : slope positive (EMA monte)
        SHORT : slope negative (EMA descend)
        """
        try:
            ema = self._compute_ema(df["close"], self.ema_period)
            if len(ema) < 11:
                return 0.0, False
            slope = float(ema.iloc[-1] - ema.iloc[-11]) / 10.0  # slope sur 10 bars
            if direction == "LONG":
                return slope, slope > 0
            else:
                return slope, slope < 0
        except Exception as e:
            log.warning(f"BNV3 EMA slope compute fail: {type(e).__name__}: {e}")
            return 0.0, False

    def _check_range_filter(self, df: pd.DataFrame) -> bool:
        """Anti-trap range : si range_detector dit is_range=True, SKIP.

        Returns True si on est en RANGE (et donc on doit SKIP), False sinon.
        """
        if not self.use_range_filter or self._range_detector is None:
            return False
        try:
            result = self._range_detector.detect(df)
            return bool(result.is_range)
        except Exception as e:
            log.warning(f"range_detector error: {e}")
            return False

    def _check_pullback_fibonacci(self, swings: List[BNV3Swing], df: pd.DataFrame,
                                   direction: str
                                   ) -> tuple[Optional[float], bool, Optional[BNV3Swing]]:
        """Verifie pullback ratio Fibonacci.

        LONG : pullback HH -> pullback_low actuel, ratio = pullback_size / swing_size
        SHORT : pullback LL -> pullback_high actuel
        """
        if direction == "LONG":
            hhs = [s for s in swings if s.dow == "HH"]
            hls = [s for s in swings if s.dow == "HL"]
            if len(hhs) < 1 or len(hls) < 2:
                return None, False, None
            last_hh = hhs[-1]
            # Last swing range = HH - prev HL
            prev_hl = hls[-2] if hls[-2].idx < last_hh.idx else hls[-1]
            swing_range = last_hh.price - prev_hl.price
            if swing_range <= 0:
                return None, False, None
            # Pullback actuel : current low low (last 5 bars)
            recent_low = float(df["low"].iloc[-5:].min())
            pullback_size = last_hh.price - recent_low
            if pullback_size <= 0:
                return None, False, None
            ratio = pullback_size / swing_range
            ok = self.pullback_min <= ratio <= self.pullback_max
            return ratio, ok, last_hh
        else:  # SHORT
            lls = [s for s in swings if s.dow == "LL"]
            lhs = [s for s in swings if s.dow == "LH"]
            if len(lls) < 1 or len(lhs) < 2:
                return None, False, None
            last_ll = lls[-1]
            prev_lh = lhs[-2] if lhs[-2].idx < last_ll.idx else lhs[-1]
            swing_range = prev_lh.price - last_ll.price
            if swing_range <= 0:
                return None, False, None
            recent_high = float(df["high"].iloc[-5:].max())
            pullback_size = recent_high - last_ll.price
            if pullback_size <= 0:
                return None, False, None
            ratio = pullback_size / swing_range
            ok = self.pullback_min <= ratio <= self.pullback_max
            return ratio, ok, last_ll

    def _check_recharge_signal(self, df: pd.DataFrame, direction: str) -> tuple[bool, str]:
        """Detecte signal de recharge sur derniere bar.

        LONG : feature long_up_bar == 1 (parquet v4 enrichi Bot 2)
        SHORT : feature long_dn_bar == 1 (parquet v4 enrichi Bot 2)

        Returns (should_recharge, source_feature).

        R2 fix : log warning si colonne absente (vieux historique pre-fix).
        """
        if len(df) < 1:
            return False, ""
        last = df.iloc[-1]
        col = RECHARGE_TRIGGER_LONG if direction == "LONG" else RECHARGE_TRIGGER_SHORT
        if col not in df.columns:
            log.warning(f"BNV3 recharge col '{col}' MISSING in df (vieux historique pre-fix?). "
                        f"Disponibles starts: {[c for c in df.columns[:50]]}")
            return False, ""
        val = last.get(col, 0)
        if val is not None and float(val) >= 1.0:
            return True, col
        return False, ""

    def _check_rebound(self, df: pd.DataFrame, direction: str) -> bool:
        """Confirmation rebound apres pullback.

        LONG : last bar verte (close > open) AND close > prev close
        SHORT : last bar rouge (close < open) AND close < prev close
        """
        if len(df) < 2:
            return False
        last = df.iloc[-1]
        prev = df.iloc[-2]
        if direction == "LONG":
            bar_green = last["close"] > last["open"]
            close_up = last["close"] > prev["close"]
            return bool(bar_green and close_up)
        else:
            bar_red = last["close"] < last["open"]
            close_down = last["close"] < prev["close"]
            return bool(bar_red and close_down)

    # ─── Trail "derniere verte la plus basse" (Jackson 13/05/2026) ───
    #
    # Regle observee chart NQ 13/05 sur replies 2->3, 4->5, 6->7 :
    #   "en tendance haussiere, tant que aucune rouge ne ferme sous le low
    #    de la verte la plus basse du leg haussier actif, la tendance continue".
    #
    # Implementation = trailing structurel Dow pur (regles #1 + #2 V3 actives).
    # ref_low se met a jour automatiquement quand un nouveau swing low est
    # confirme (= nouveau leg). Le SL initial pullback_low - 4t reste
    # l'enveloppe d'entry, ce helper sert au TRAILING en cours de trade.
    #
    # Statut : helper isolated, PAS branche dans detect()/detect_recharge()/
    # detect_iterative() tant que pas valide visuellement + backtest preservation.

    def _find_trail_ref_level(self, df: pd.DataFrame,
                               direction: str) -> Optional[float]:
        """Trouve niveau de reference trail "vert le plus bas du leg actif".

        LONG  : depuis dernier swing low confirme, low de la bougie verte
                (close > open) avec le LOW le plus bas.
        SHORT : depuis dernier swing high confirme, high de la bougie rouge
                (close < open) avec le HIGH le plus haut.

        Returns:
            float : niveau de reference (low pour LONG, high pour SHORT).
            None  : si aucun swing confirme dans la fenetre, ou aucune
                    bougie de la bonne couleur dans le leg.
        """
        swings = self._detect_swings(df)
        if not swings:
            return None

        if direction == "LONG":
            ref_idx = None
            for s in reversed(swings):
                if s.swing_type == "LOW":
                    ref_idx = s.idx
                    break
            if ref_idx is None or ref_idx >= len(df) - 1:
                return None
            leg = df.iloc[ref_idx:]
            greens = leg[leg["close"] > leg["open"]]
            if len(greens) == 0:
                return None
            return float(greens["low"].min())

        elif direction == "SHORT":
            ref_idx = None
            for s in reversed(swings):
                if s.swing_type == "HIGH":
                    ref_idx = s.idx
                    break
            if ref_idx is None or ref_idx >= len(df) - 1:
                return None
            leg = df.iloc[ref_idx:]
            reds = leg[leg["close"] < leg["open"]]
            if len(reds) == 0:
                return None
            return float(reds["high"].max())

        return None

    def check_lowest_green_trail(self, df: pd.DataFrame,
                                  state: BNV3State) -> dict:
        """Verifie si tendance brisee selon regle Jackson 13/05 "rouge sous
        verte la plus basse du leg actif".

        LONG  : trend_broken si bar rouge ET close < ref_low_green.
        SHORT : trend_broken si bar verte ET close > ref_high_red.

        Returns:
            dict {trend_broken, ref_level, last_bar_color, last_close, reason}.
        """
        if not state.active or state.direction is None:
            return {
                "trend_broken": False, "ref_level": None,
                "last_bar_color": None, "last_close": float("nan"),
                "reason": "no_active_trade",
            }

        ref = self._find_trail_ref_level(df, state.direction)
        if ref is None:
            return {
                "trend_broken": False, "ref_level": None,
                "last_bar_color": None, "last_close": float("nan"),
                "reason": "no_ref_level_in_leg",
            }

        last = df.iloc[-1]
        last_close = float(last["close"])
        last_open = float(last["open"])

        if state.direction == "LONG":
            is_red = last_close < last_open
            broken = bool(is_red and last_close < ref)
            reason = (f"trail_LONG close={last_close:.2f} "
                      f"ref_low_green={ref:.2f} red={is_red} broken={broken}")
            color = "RED" if is_red else ("GREEN" if last_close > last_open else "DOJI")
        else:  # SHORT
            is_green = last_close > last_open
            broken = bool(is_green and last_close > ref)
            reason = (f"trail_SHORT close={last_close:.2f} "
                      f"ref_high_red={ref:.2f} green={is_green} broken={broken}")
            color = "GREEN" if is_green else ("RED" if last_close < last_open else "DOJI")

        return {
            "trend_broken": broken,
            "ref_level": ref,
            "last_bar_color": color,
            "last_close": last_close,
            "reason": reason,
        }

    # ─── Helper : finalise state apres setup OK (Mode 1, 2 ou 3) ───

    def _finalize_setup_state(self, state: BNV3State, result: BNV3Result,
                               end_idx: int, amorce_mode: str) -> None:
        """Initialise completement BNV3State apres un signal LONG/SHORT_ENTRY.

        Appele depuis Mode 1, Mode 2 ET Mode 3 success pour garantir que :
        - simulate_trade lit state.direction/active/entry/sl/tp correctement
        - detect_recharge a state valide
        - check_lowest_green_trail a state.active=True

        Bug audit code-reviewer 13/05 P0 #1 : Mode 2/3 oubliaient ces inits ->
        state.direction=None -> simulator crash. Helper unique = fail-safe.
        """
        state.active = True
        state.direction = result.direction
        state.entry_price = result.entry_price
        state.sl_price = result.sl_price
        state.tp_partial_price = result.tp_partial_price
        state.last_setup_idx = end_idx
        state.invalidated = False
        state.invalidation_reason = None
        state.n_contracts_loaded = N_CONTRACTS_INITIAL
        state.n_recharges = 0
        state.last_recharge_idx = -1
        state.amorce_mode = amorce_mode

    # ─── Mode 2 : amorce post-consolidation / range break (Jackson 13/05) ───

    def _detect_amorce_range_break(self, df: pd.DataFrame,
                                    state: BNV3State) -> BNV3Result:
        """Mode 2 amorce BN : cassure de range/consolidation avec volume.

        Jackson 13/05/2026 : "Sa commence apres un range ou apres une descente
        et un depart en V. Souvent apres une consolidation."

        Prerequis :
          - Range detector V3 a vu is_range=True dans les MODE2_LOOKBACK_RANGE_BARS
            dernieres bars (= consolidation confirmee recemment)
          - range_break_risk == UP_BREAK_IMMINENT ou DOWN_BREAK_IMMINENT (already calcule)
            OU bar courante ferme franchement au-dessus range_high (LONG) / sous range_low (SHORT)

        Conditions entry LONG :
          - close > range_high_zone + MODE2_BREAKOUT_BUFFER_TICKS * tick_size
          - total_vol > MODE2_VOL_RATIO_MIN * rolling_mean(MODE2_VOL_LOOKBACK)
          - long_up_bar==1 OR bn_long_up==1 (confirmation footprint)

        Vetos :
          - dist_swing_high_atr < MODE2_DIST_SWING_VETO_ATR (trop pres swing recent)
          - dist_mq_call_res_atr < MODE2_DIST_MQ_VETO_ATR (breakout dans mur call = piege)
          - Cooldown : MODE2_COOLDOWN_BARS depuis derniere amorce Mode 2

        Setup BN si OK :
          - entry_price = close
          - sl_price = entry_price - MODE2_SL_INITIAL_TICKS * tick_size (LONG)
          - tp_partial = entry + range_size * MODE2_TP_PROJECTION_RATIO (capped)
        """
        result = BNV3Result()

        # 1. Range detector dispo
        if self._range_detector is None:
            result.reject_reason = "mode2_no_range_detector"
            return result

        # 2. Cooldown anti re-entry meme range
        cur_idx = len(df) - 1
        if state.last_mode2_idx >= 0 and (cur_idx - state.last_mode2_idx) < MODE2_COOLDOWN_BARS:
            result.reject_reason = f"mode2_cooldown ({cur_idx - state.last_mode2_idx}/{MODE2_COOLDOWN_BARS})"
            return result

        # 3. UN SEUL appel range_detector sur fenetre courante (perf : evite 5 calls)
        # range_detector_v3 expose :
        #   - is_range=True si encore en consolidation
        #   - range_break_risk=UP/DOWN_BREAK_IMMINENT si pre-breakout detecte
        #   - range_high_zone / range_low_zone (quantiles 95/5 + buffer ticks)
        try:
            rr = self._range_detector.detect(df)
        except Exception as e:
            result.reject_reason = f"mode2_detector_error: {type(e).__name__}"
            return result

        range_zone_high = rr.range_high_zone
        range_zone_low = rr.range_low_zone
        if range_zone_high is None or range_zone_low is None:
            result.reject_reason = "mode2_no_range_zones"
            return result

        # Eligibilite : soit on est encore en range (cassure en cours), soit on a
        # un signal range_break_risk imminent (= pre-breakout detecte).
        # Si is_range=False ET range_break_risk=NONE = pas de contexte range -> SKIP
        is_range = getattr(rr, "is_range", False)
        break_risk = getattr(rr, "range_break_risk", "NONE")
        if not is_range and break_risk == "NONE":
            result.reject_reason = "mode2_no_range_context"
            return result

        # 4. Detection cassure sur bar courante
        last = df.iloc[-1]
        close = float(last["close"])
        buffer_pts = MODE2_BREAKOUT_BUFFER_TICKS * self.tick_size

        breakout_long = close > (range_zone_high + buffer_pts)
        breakout_short = close < (range_zone_low - buffer_pts)

        # Si break_risk indique direction, l'utiliser comme confirmation supplementaire
        if break_risk == "UP_BREAK_IMMINENT" and not breakout_long:
            # Pre-breakout signale mais close pas encore au-dessus : attendre
            result.reject_reason = "mode2_up_break_imminent_not_confirmed"
            return result
        if break_risk == "DOWN_BREAK_IMMINENT" and not breakout_short:
            result.reject_reason = "mode2_down_break_imminent_not_confirmed"
            return result

        if not (breakout_long or breakout_short):
            result.reject_reason = "mode2_no_breakout"
            return result

        direction = "LONG" if breakout_long else "SHORT"

        # 5. Filtre volume : vol bar courante > MODE2_VOL_RATIO_MIN * rolling_mean
        if "total_vol" in df.columns and cur_idx >= MODE2_VOL_LOOKBACK:
            recent_vol = df["total_vol"].iloc[cur_idx - MODE2_VOL_LOOKBACK:cur_idx]
            vol_baseline = float(recent_vol.mean())
            vol_current = float(last["total_vol"])
            vol_ratio = vol_current / max(vol_baseline, 1.0)
            if vol_ratio < MODE2_VOL_RATIO_MIN:
                result.reject_reason = f"mode2_low_volume (ratio={vol_ratio:.2f} < {MODE2_VOL_RATIO_MIN})"
                return result
        # Si pas de total_vol dispo, on accepte (degraded mode pour tests synthetiques)

        # 6. Confirmation footprint (au moins 1 des 2 features)
        long_bar_col = "long_up_bar" if direction == "LONG" else "long_dn_bar"
        bn_color_col = "bn_color_up" if direction == "LONG" else "bn_color_dn"
        footprint_ok = False
        if long_bar_col in df.columns:
            footprint_ok = footprint_ok or bool(last[long_bar_col] == 1)
        if bn_color_col in df.columns:
            footprint_ok = footprint_ok or bool(last[bn_color_col] == 1)
        if not footprint_ok:
            # En mode degraded (test synthetique sans ces cols), on tolere
            has_either_col = (long_bar_col in df.columns) or (bn_color_col in df.columns)
            if has_either_col:
                result.reject_reason = "mode2_no_footprint_confirm"
                return result

        # 7. Veto swing proximity (Jackson 11/05 feedback_swing_proximity_veto)
        # P0 FIX #4 (audit 13/05) : noms reels v4 = dist_last_swing_high_pct (% du prix).
        # ATR en TICKS, donc convertir pct -> ticks d'abord : dist_ticks = pct*close/tick_size
        swing_col = "dist_last_swing_high_pct" if direction == "LONG" else "dist_last_swing_low_pct"
        if "atr" in df.columns and swing_col in df.columns:
            atr_ticks = float(last["atr"])
            close_price = float(last["close"])
            if atr_ticks > 0 and close_price > 0:
                dist_pct = float(last[swing_col])
                if not np.isnan(dist_pct):
                    dist_pts = abs(dist_pct) * close_price
                    dist_ticks = dist_pts / self.tick_size
                    dist_atr = dist_ticks / atr_ticks
                    if dist_atr < MODE2_DIST_SWING_VETO_ATR:
                        result.reject_reason = f"mode2_swing_proximity_veto ({swing_col} dist={dist_atr:.2f} ATR)"
                        return result

        # 8. Veto MenthorQ wall (call resistance pour LONG, put support pour SHORT)
        # P0 FIX #3 (audit 13/05) : noms reels v4 = dist_mq_call_pct + dist_mq_call_0dte_pct
        # (et put). Prioriser 0DTE puis fallback day-level. Toujours en pct du prix.
        if direction == "LONG":
            mq_cols = ("dist_mq_call_0dte_pct", "dist_mq_call_pct")
        else:
            mq_cols = ("dist_mq_put_0dte_pct", "dist_mq_put_pct")

        if "atr" in df.columns:
            atr_ticks = float(last["atr"])
            close_price = float(last["close"])
            for mq_col in mq_cols:
                if mq_col not in df.columns:
                    continue
                if atr_ticks <= 0 or close_price <= 0:
                    break
                dist_pct = float(last[mq_col])
                if np.isnan(dist_pct):
                    continue
                dist_pts = abs(dist_pct) * close_price
                dist_ticks = dist_pts / self.tick_size
                dist_atr = dist_ticks / atr_ticks
                if dist_atr < MODE2_DIST_MQ_VETO_ATR:
                    result.reject_reason = f"mode2_mq_wall_veto ({mq_col} dist={dist_atr:.2f} ATR)"
                    return result
                break  # 1ere col trouvee = decision finale

        # === SETUP BN MODE 2 OK ===
        entry_price = close
        if direction == "LONG":
            sl_price = entry_price - MODE2_SL_INITIAL_TICKS * self.tick_size
        else:
            sl_price = entry_price + MODE2_SL_INITIAL_TICKS * self.tick_size

        # TP projection Crabel : range_size * 1.5, capped
        range_size_pts = range_zone_high - range_zone_low
        tp_projection_pts = range_size_pts * MODE2_TP_PROJECTION_RATIO
        tp_cap_pts = MODE2_TP_CAP_TICKS[self.sym] * self.tick_size
        tp_distance = min(tp_projection_pts, tp_cap_pts)
        if direction == "LONG":
            tp_partial_price = entry_price + tp_distance
        else:
            tp_partial_price = entry_price - tp_distance

        result.signal = "LONG_ENTRY" if direction == "LONG" else "SHORT_ENTRY"
        result.direction = direction
        result.entry_price = entry_price
        result.sl_price = sl_price
        result.tp_partial_price = tp_partial_price
        result.n_contracts = N_CONTRACTS_INITIAL
        result.reject_reason = f"mode2_RANGE_BREAK_{direction}_amorce"  # info pour log

        return result

    # ─── Mode 3 : amorce post-capitulation V-bottom / Λ-top (Jackson 13/05) ───

    def _detect_amorce_v_reversal(self, df: pd.DataFrame,
                                   state: BNV3State) -> BNV3Result:
        """Mode 3 amorce BN : V-bottom / Λ-top apres capitulation violente.

        Jackson 13/05/2026 : "apres une descente et un depart en V" (plus rare
        que Mode 2 mais devastateur quand declenche).
        Trade ref Jackson 20/04 NQ : drop -208 pts en 90min, rebond +124 pts en 22min.

        3 fixes methodologiques (audit market-analyst 13/05 sur v_reversal.py original) :
          FIX #1 : Footprint relaxe -> long_up_bar=1 sur barre OU bn_color_up=1
                   sur >= 2 des 3 dernieres barres (vs simultane sur meme barre)
          FIX #2 : Vol baseline calculee sur 20 bars AVANT le drop, pas glissant
                   (sinon baseline incorporerait la capitulation = ratio biaise)
          FIX #3 : Filtre MenthorQ key levels (dist_mq_put_0dte_atr < 1.0 pour LONG)
                   + distinction post-range vs post-trend (rare event vs bruit)

        Conditions entry LONG (V-bottom) :
          - Drop >= MODE3_DROP_MIN_ATR sur MODE3_LOOKBACK_DROP_BARS dernieres bars
          - Low absolu recent : bars_since_low <= MODE3_BARS_SINCE_LOW_MAX
          - FIX #1 : long_up_bar=1 OR (bn_color_up >= 2 sur 3 dernieres bars)
          - FIX #2 : vol_current > MODE3_VOL_RATIO_MIN * vol_pre_drop_baseline
          - FIX #3 : dist_mq_put_sup_atr <= MODE3_MQ_KEY_LEVEL_VETO_ATR (confluence options)

        SL/TP :
          - SL = swing_low - MODE3_SL_BUFFER_TICKS (LONG)
          - TP = 50% Fib retracement du drop, clipped [MIN, MAX]
        """
        result = BNV3Result()
        cur_idx = len(df) - 1

        # 1. Cooldown anti re-entry
        if state.last_mode3_idx >= 0 and (cur_idx - state.last_mode3_idx) < MODE3_COOLDOWN_BARS:
            result.reject_reason = f"mode3_cooldown ({cur_idx - state.last_mode3_idx}/{MODE3_COOLDOWN_BARS})"
            return result

        # 2. Detection capitulation : drop sur les MODE3_LOOKBACK_DROP_BARS bars
        if cur_idx < MODE3_LOOKBACK_DROP_BARS + MODE3_VOL_PRE_DROP_LOOKBACK + 5:
            result.reject_reason = "mode3_insufficient_history"
            return result

        # Recuperer ATR (fallback approx si absent)
        atr_val = None
        if "atr" in df.columns:
            atr_val = float(df.iloc[-1]["atr"])
        if atr_val is None or atr_val <= 0 or np.isnan(atr_val):
            # Fallback : ATR approx sur 14 bars (Wilder simple)
            recent_high = df["high"].iloc[-14:].values
            recent_low = df["low"].iloc[-14:].values
            atr_val = float(np.mean(recent_high - recent_low))
        if atr_val <= 0:
            result.reject_reason = "mode3_atr_zero"
            return result

        # Fenetre drop : 15 dernieres bars
        window_high = float(df["high"].iloc[-MODE3_LOOKBACK_DROP_BARS:].max())
        low_slice = df["low"].iloc[-MODE3_LOOKBACK_DROP_BARS:].reset_index(drop=True)
        local_low_pos = int(low_slice.values.argmin())
        absolute_low_idx = cur_idx - MODE3_LOOKBACK_DROP_BARS + 1 + local_low_pos
        absolute_low_price = float(low_slice.iloc[local_low_pos])

        # P0 FIX #2 (audit code-reviewer 13/05) : ATR est en TICKS (cf lessons.md
        # "ATR dans JSONL est en TICKS verifie 09/04"). drop est en POINTS de prix.
        # Pour ratio coherent, convertir drop_points -> drop_ticks AVANT division.
        drop_pts = window_high - absolute_low_price
        drop_ticks = drop_pts / self.tick_size
        drop_atr = drop_ticks / atr_val

        if drop_atr < MODE3_DROP_MIN_ATR:
            result.reject_reason = f"mode3_no_capitulation (drop={drop_atr:.2f} ATR < {MODE3_DROP_MIN_ATR})"
            return result

        # 3. Low recent : <= MODE3_BARS_SINCE_LOW_MAX bars depuis le low absolu
        bars_since_low = cur_idx - absolute_low_idx
        if bars_since_low > MODE3_BARS_SINCE_LOW_MAX:
            result.reject_reason = f"mode3_low_too_far ({bars_since_low} > {MODE3_BARS_SINCE_LOW_MAX} bars)"
            return result

        # Direction = LONG si capitulation baissiere (drop) + low recent
        # SHORT (Λ-top) = symetrique : spike haussier + high recent
        direction = "LONG"  # focus LONG d'abord, mirror SHORT plus tard si besoin

        # 4. FIX #1 — Footprint relaxe : long_up_bar=1 OR color_up >= 2/3 dernieres
        last = df.iloc[-1]
        footprint_ok = False
        # Test long_up_bar sur bar courante
        if "long_up_bar" in df.columns:
            footprint_ok = footprint_ok or bool(last["long_up_bar"] == 1)
        elif "bn_long_up" in df.columns:
            footprint_ok = footprint_ok or bool(last["bn_long_up"] == 1)
        # Test color_up sur 2/3 dernieres bars (FIX #1)
        if not footprint_ok and "bn_color_up" in df.columns:
            color_up_recent = df["bn_color_up"].iloc[-MODE3_COLOR_CONFIRM_BARS:].values
            n_color_up = int((color_up_recent == 1).sum())
            if n_color_up >= 2:
                footprint_ok = True
        # Mode degraded : si aucune feature footprint dispo, on tolere
        has_footprint_cols = (any(c in df.columns for c in ["long_up_bar", "bn_long_up", "bn_color_up"]))
        if has_footprint_cols and not footprint_ok:
            result.reject_reason = "mode3_no_footprint_confirm (FIX #1 echec)"
            return result

        # 5. FIX #2 — Vol baseline calculee sur 20 bars AVANT le drop (pas glissant)
        if "total_vol" in df.columns:
            drop_start_idx = cur_idx - MODE3_LOOKBACK_DROP_BARS
            pre_drop_start = max(0, drop_start_idx - MODE3_VOL_PRE_DROP_LOOKBACK)
            pre_drop_end = drop_start_idx
            if pre_drop_end - pre_drop_start >= 5:  # min 5 bars pour baseline valide
                vol_pre_drop = df["total_vol"].iloc[pre_drop_start:pre_drop_end]
                vol_baseline = float(vol_pre_drop.mean())
                vol_current = float(last["total_vol"])
                vol_ratio = vol_current / max(vol_baseline, 1.0)
                if vol_ratio < MODE3_VOL_RATIO_MIN:
                    result.reject_reason = f"mode3_low_volume (ratio={vol_ratio:.2f} < {MODE3_VOL_RATIO_MIN}, FIX #2)"
                    return result
            # Sinon : pas assez d'historique, on tolere

        # 6. FIX #3 — V-bottom doit etre proche put_support (rare event Lopez)
        # P0 FIX (audit 13/05) : noms reels v4 = dist_mq_put_0dte_pct + dist_mq_put_pct
        # ATR en TICKS, dist en pct du prix -> conversion obligatoire avant ratio.
        mq_cols_put = ("dist_mq_put_0dte_pct", "dist_mq_put_pct")
        close_price = float(last["close"])
        mq_check_done = False
        for mq_col in mq_cols_put:
            if mq_col not in df.columns:
                continue
            dist_pct = float(last[mq_col])
            if np.isnan(dist_pct):
                continue
            mq_check_done = True
            dist_pts = abs(dist_pct) * close_price
            dist_ticks = dist_pts / self.tick_size
            dist_mq_atr = dist_ticks / atr_val
            if dist_mq_atr > MODE3_MQ_KEY_LEVEL_VETO_ATR:
                result.reject_reason = f"mode3_no_mq_confluence ({mq_col} dist={dist_mq_atr:.2f} ATR > {MODE3_MQ_KEY_LEVEL_VETO_ATR}, FIX #3)"
                return result
            break  # 1ere col trouvee = decision finale

        # === SETUP BN MODE 3 OK ===
        entry_price = float(last["close"])
        sl_price = absolute_low_price - MODE3_SL_BUFFER_TICKS * self.tick_size

        # TP = 50% Fib retracement du drop, clipped [MIN, MAX]
        tp_fib_pts = drop_pts * MODE3_TP_FIB_RATIO
        tp_min_pts = MODE3_TP_MIN_TICKS[self.sym] * self.tick_size
        tp_max_pts = MODE3_TP_MAX_TICKS[self.sym] * self.tick_size
        tp_distance = max(tp_min_pts, min(tp_fib_pts, tp_max_pts))
        tp_partial_price = entry_price + tp_distance

        result.signal = "LONG_ENTRY"
        result.direction = "LONG"
        result.entry_price = entry_price
        result.sl_price = sl_price
        result.tp_partial_price = tp_partial_price
        result.n_contracts = N_CONTRACTS_INITIAL
        result.reject_reason = "mode3_V_REVERSAL_LONG_amorce"

        return result

    # ─── API publique ───

    def detect(self, df: pd.DataFrame, state: BNV3State) -> BNV3Result:
        """Detecte un setup BN V3 sur la fenetre fournie.

        Pipeline :
          1. Validate input (OHLC cols)
          2. Detect swings + Dow trend
          3. Filtre 1 : range_detector (anti-trap)
          4. Filtre 2 : ADX > 25
          5. Filtre 3 : EMA(20) slope direction
          6. Pullback Fibonacci 30-62%
          7. Rebound confirmation
          8. Anti re-entry (1 setup = 1 trade)
        """
        result = BNV3Result()
        self._validate_input(df)

        if len(df) < max(self.swing_lookback, 60):
            result.reject_reason = "insufficient_bars"
            return result

        # Swings + Dow trend
        swings = self._detect_swings(df)
        result.n_swings = len(swings)
        result.n_hh = sum(1 for s in swings if s.dow == "HH")
        result.n_hl = sum(1 for s in swings if s.dow == "HL")
        result.n_lh = sum(1 for s in swings if s.dow == "LH")
        result.n_ll = sum(1 for s in swings if s.dow == "LL")
        result.is_uptrend_dow = self._is_uptrend_dow(swings)
        result.is_downtrend_dow = self._is_downtrend_dow(swings)

        if not (result.is_uptrend_dow or result.is_downtrend_dow):
            # MODE 2 — amorce post-consolidation/range_break (Jackson 13/05)
            # Si Mode 1 (Holy Grail) ne trouve pas de trend Dow, on essaye Mode 2.
            # Mutuellement exclusif : premier qui declenche prend.
            if self.enable_mode2_range_break:
                mode2_result = self._detect_amorce_range_break(df, state)
                if mode2_result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
                    cur_idx = len(df) - 1
                    state.last_mode2_idx = cur_idx
                    # P0 FIX #1 : state fully initialized via helper
                    self._finalize_setup_state(state, mode2_result, cur_idx,
                                                amorce_mode="RANGE_BREAK")
                    return mode2_result

            # MODE 3 — amorce post-capitulation V-bottom (Jackson 13/05)
            # Si Mode 1 ET Mode 2 ne declenchent pas, on essaye Mode 3.
            if self.enable_mode3_v_reversal:
                mode3_result = self._detect_amorce_v_reversal(df, state)
                if mode3_result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
                    cur_idx = len(df) - 1
                    state.last_mode3_idx = cur_idx
                    # P0 FIX #1 : state fully initialized via helper
                    self._finalize_setup_state(state, mode3_result, cur_idx,
                                                amorce_mode="V_REVERSAL")
                    return mode3_result

            result.reject_reason = "no_dow_trend"
            return result

        direction = "LONG" if result.is_uptrend_dow else "SHORT"

        # Filtre 1 : Range detector (anti-trap)
        result.is_range = self._check_range_filter(df)
        if result.is_range:
            # P1 FIX (audit code-reviewer 13/05) : si on est en range, c'est EXACTEMENT
            # le contexte ou Mode 2 doit surveiller la cassure. Sinon Mode 2 ne se
            # declenche jamais (Mode 1 Dow detecte un faux trend dans le range et
            # skip avant que Mode 2 ait sa chance).
            if self.enable_mode2_range_break:
                mode2_result = self._detect_amorce_range_break(df, state)
                if mode2_result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
                    cur_idx = len(df) - 1
                    state.last_mode2_idx = cur_idx
                    self._finalize_setup_state(state, mode2_result, cur_idx,
                                                amorce_mode="RANGE_BREAK")
                    return mode2_result
            result.reject_reason = "range_detected_skip"
            return result

        # Filtre 2 : ADX > 25
        result.adx, result.adx_ok = self._check_adx(df)
        if not result.adx_ok:
            result.reject_reason = f"adx_too_low ({result.adx:.1f} < {self.adx_min})"
            return result

        # Filtre 3 : EMA(20) slope direction
        result.ema20_slope, result.ema20_ok = self._check_ema_slope(df, direction)
        if not result.ema20_ok:
            result.reject_reason = f"ema20_slope_wrong_direction ({result.ema20_slope:.4f})"
            return result

        # Filtre 4 : Pullback Fibonacci
        result.pullback_ratio, result.pullback_ok, last_pivot = \
            self._check_pullback_fibonacci(swings, df, direction)
        if not result.pullback_ok:
            result.reject_reason = (
                f"pullback_invalid (ratio={result.pullback_ratio}, "
                f"required {self.pullback_min}-{self.pullback_max})"
            )
            return result

        # Filtre 5 : Rebound confirmation
        result.rebound_confirmed = self._check_rebound(df, direction)
        if not result.rebound_confirmed:
            result.reject_reason = "no_rebound_confirmation"
            return result

        # Anti re-entry : si setup deja pris recemment, skip
        end_idx = len(df) - 1
        if state.last_setup_idx > 0 and (end_idx - state.last_setup_idx) < 10:
            result.reject_reason = "anti_re_entry_recent_setup"
            return result

        # === SETUP VALIDE ===
        last_close = float(df.iloc[-1]["close"])

        if direction == "LONG":
            # SL = low recent (last 5 bars) - 4 ticks buffer
            recent_low = float(df["low"].iloc[-5:].min())
            sl_price = recent_low - SL_BUFFER_TICKS * self.tick_size
            tp_partial_price = last_close + SCALE_OUT_TRIGGER_TICKS[self.sym] * self.tick_size
        else:
            recent_high = float(df["high"].iloc[-5:].max())
            sl_price = recent_high + SL_BUFFER_TICKS * self.tick_size
            tp_partial_price = last_close - SCALE_OUT_TRIGGER_TICKS[self.sym] * self.tick_size

        result.signal = f"{direction}_ENTRY"
        result.direction = direction
        result.entry_price = last_close
        result.sl_price = round(sl_price, 4)
        result.tp_partial_price = round(tp_partial_price, 4)
        result.n_contracts = N_CONTRACTS_INITIAL  # 2 contrats init (Jackson 07/05)
        result.reject_reason = ""  # success

        # Update state via helper (Mode 1 amorce HOLY_GRAIL)
        self._finalize_setup_state(state, result, end_idx, amorce_mode="HOLY_GRAIL")

        return result

    def detect_recharge(self, df: pd.DataFrame, state: BNV3State) -> BNV3Result:
        """Detecte signal de recharge pendant trade actif.

        Conditions cumulatives :
          1. state.active = True (position ouverte)
          2. state.n_recharges < MAX_PYRAMID_LOADS
          3. Gap >= RECHARGE_MIN_BARS_GAP depuis derniere recharge
          4. Last bar a Long Up Bar (LONG) ou Long Down Bar (SHORT)
          5. Trend Dow tjs valide (HH+HL ou LH+LL)
          6. Price > entry (LONG) ou < entry (SHORT) -> trade in profit (anti recharge en perte)

        Returns BNV3Result avec signal='RECHARGE_LONG'/'RECHARGE_SHORT' si OK.
        """
        result = BNV3Result()
        if not state.active or state.direction is None:
            result.reject_reason = "no_active_setup"
            return result

        if state.n_recharges >= MAX_PYRAMID_LOADS:
            result.reject_reason = f"max_recharges_reached ({state.n_recharges}/{MAX_PYRAMID_LOADS})"
            return result

        end_idx = len(df) - 1
        if state.last_recharge_idx > 0:
            gap = end_idx - state.last_recharge_idx
            if gap < RECHARGE_MIN_BARS_GAP:
                result.reject_reason = f"recharge_too_close (gap={gap} < {RECHARGE_MIN_BARS_GAP})"
                return result

        direction = state.direction
        last_close = float(df.iloc[-1]["close"])

        # Anti recharge en perte (Jackson : on charge SI dans le sens du profit)
        if state.entry_price is not None:
            if direction == "LONG" and last_close < state.entry_price:
                result.reject_reason = "in_loss_no_recharge_long"
                return result
            if direction == "SHORT" and last_close > state.entry_price:
                result.reject_reason = "in_loss_no_recharge_short"
                return result

        # Trend toujours valide ?
        swings = self._detect_swings(df)
        if direction == "LONG" and not self._is_uptrend_dow(swings):
            result.reject_reason = "uptrend_broken"
            return result
        if direction == "SHORT" and not self._is_downtrend_dow(swings):
            result.reject_reason = "downtrend_broken"
            return result

        # Signal Long Up/Dn Bar present sur derniere bar ?
        should_recharge, source_feature = self._check_recharge_signal(df, direction)
        if not should_recharge:
            result.reject_reason = f"no_recharge_signal (col={RECHARGE_TRIGGER_LONG if direction == 'LONG' else RECHARGE_TRIGGER_SHORT})"
            return result

        # === RECHARGE OK ===
        result.signal = f"RECHARGE_{direction}"
        result.direction = direction
        result.entry_price = last_close
        result.sl_price = state.sl_price  # SL global inchange (regle 2 : stop ne descend jamais)
        result.tp_partial_price = state.tp_partial_price
        result.n_contracts = 1  # Recharge = 1 contrat additionnel
        result.reject_reason = ""

        # Update state
        state.n_contracts_loaded += 1
        state.n_recharges += 1
        state.last_recharge_idx = end_idx

        return result

    def detect_iterative(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pour backtest : detect sur chaque bar, retourne df augmente."""
        n = len(df)
        signals = ["NONE"] * n
        directions = [None] * n
        entries = [np.nan] * n
        sls = [np.nan] * n
        tps = [np.nan] * n
        reasons = [""] * n
        state = BNV3State()

        for i in range(self.swing_lookback, n):
            window = df.iloc[:i + 1]
            try:
                r = self.detect(window, state)
            except Exception as e:
                log.warning(f"detect error idx={i}: {e}")
                continue
            signals[i] = r.signal
            directions[i] = r.direction
            entries[i] = r.entry_price if r.entry_price is not None else np.nan
            sls[i] = r.sl_price if r.sl_price is not None else np.nan
            tps[i] = r.tp_partial_price if r.tp_partial_price is not None else np.nan
            reasons[i] = r.reject_reason

            # Reset state apres detection (anti spam, mais permet nouveau setup apres ~10 bars)
            if r.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
                state = BNV3State()
                state.last_setup_idx = i  # garde anti re-entry

        df_out = df.copy()
        df_out["bn_v3_signal"] = signals
        df_out["bn_v3_direction"] = directions
        df_out["bn_v3_entry"] = entries
        df_out["bn_v3_sl"] = sls
        df_out["bn_v3_tp_partial"] = tps
        df_out["bn_v3_reason"] = reasons
        return df_out
