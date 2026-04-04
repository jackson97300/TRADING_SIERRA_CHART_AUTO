"""
═══════════════════════════════════════════════════════════════════════
MIA Regime Engine — Le cerveau du nouveau paradigme
═══════════════════════════════════════════════════════════════════════

Rôle : Analyser une séquence de snapshots et déterminer :
  1. open_zone     — Où on a ouvert vs VA veille
  2. open_type     — OD / OTD / ORR / OAIR / OAOR / ODF
  3. ib_analysis   — IB large/étroite + cassures
  4. regime        — TREND / ROTATION / REVERSAL / BREAKOUT / INCERTAIN
  5. day_type      — NonTrend / Normal / NormVar / Neutral / Trend (évolutif)
  6. rule_80pct    — Signal haute conviction

Usage :
  engine = RegimeEngine(tick_size=0.25)  # NQ
  for snap in snapshots:
      result = engine.update(snap)
      print(result.regime, result.direction, result.confidence)

Auteur : MIA Trading System
Date   : 2026-03-01
═══════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List, Dict, Any
import json


# ═════════════════════════════════════════════════════════════════════
# ENUMS
# ═════════════════════════════════════════════════════════════════════

class OpenZone(IntEnum):
    """Position de l'open vs VA veille + PDH/PDL"""
    UNKNOWN      = 0
    BELOW_PDL    = 1   # Bien en-dessous de la PVAL (gap down)
    PVAL_PDL     = 2   # Entre PVAL et PDL 
    POC_VAL      = 3   # Entre PVPOC et PVAL (value basse)
    AT_POC       = 4   # Proche du PVPOC (±10 ticks)
    VAH_POC      = 5   # Entre PVAH et PVPOC (value haute)
    PDH_VAH      = 6   # Entre PDH et PVAH
    ABOVE_PDH    = 7   # Bien au-dessus de PVAH (gap up)


class OpenType(IntEnum):
    """Type d'ouverture Market Profile (12 types)"""
    UNKNOWN   = 0
    OD_UP     = 1    # Open Drive Up — tendance immédiate haussière
    OD_DOWN   = 2    # Open Drive Down — tendance immédiate baissière
    OTD_UP    = 3    # Open Test Drive Up — test puis hausse
    OTD_DOWN  = 4    # Open Test Drive Down — test puis baisse
    ORR_UP    = 5    # Open Rejection Reverse Up — rejet bas → hausse
    ORR_DOWN  = 6    # Open Rejection Reverse Down — rejet haut → baisse
    OAIR      = 7    # Open Auction In Range — rotation dans la VA
    OAOR_UP   = 8    # Open Auction Out Range Up — gap up tenu
    OAOR_DOWN = 9    # Open Auction Out Range Down — gap down tenu
    ODF_UP    = 10   # Open Drive Fail → reversal haussier
    ODF_DOWN  = 11   # Open Drive Fail → reversal baissier


class Regime(IntEnum):
    """Régime de trading — dicte les règles"""
    INCERTAIN  = 0
    TREND      = 1
    ROTATION   = 2
    REVERSAL   = 3
    BREAKOUT   = 4


class DayType(IntEnum):
    """Type de journée Market Profile (évolutif)"""
    UNKNOWN    = 0
    NON_TREND  = 1   # IB < 15% ATR, journée comprimée
    NORMAL     = 2   # IB > 80% ATR, range sans extension  
    NORM_VAR   = 3   # Extension 1 côté (le plus fréquent ~42%)
    NEUTRAL    = 4   # Extension 2 côtés, close au milieu
    TREND      = 5   # Extension > 2×IB sur 1 côté


# ═════════════════════════════════════════════════════════════════════
# STRUCTURES DE SORTIE
# ═════════════════════════════════════════════════════════════════════

@dataclass
class RegimeResult:
    """Résultat complet de l'analyse de régime"""
    # Régime
    regime: Regime = Regime.INCERTAIN
    direction: int = 0           # +1=bullish, -1=bearish, 0=neutre
    confidence: float = 0.0      # 0.0 à 1.0
    
    # Composantes
    open_zone: OpenZone = OpenZone.UNKNOWN
    open_type: OpenType = OpenType.UNKNOWN
    day_type: DayType = DayType.UNKNOWN
    
    # IB
    ib_range_ticks: float = 0.0
    ib_range_atr: float = 0.0
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_broken_up: bool = False
    ib_broken_down: bool = False
    ib_complete: bool = False
    
    # Règle 80%
    rule_80pct: bool = False
    rule_80pct_direction: int = 0
    gap_filled: bool = False
    gap_direction: int = 0  # +1=vers PVAH, -1=vers PVAL
    
    # VIX
    vix: float = 0.0
    vix_regime: int = 0  # 0=calme, 1=normal, 2=volatile, 3=extrême
    
    # Contexte
    open_price: float = 0.0
    session_minutes: float = 0.0
    reason: str = ""
    
    def summary(self) -> str:
        dir_str = {1: "BULLISH", -1: "BEARISH", 0: "NEUTRE"}[self.direction]
        return (
            f"RÉGIME={self.regime.name} | DIR={dir_str} | CONF={self.confidence:.0%}\n"
            f"  Open: zone={self.open_zone.name}, type={self.open_type.name}\n"
            f"  IB: {self.ib_range_ticks:.0f}t (ATR×{self.ib_range_atr:.2f})"
            f" {'▲CASSÉ' if self.ib_broken_up else ''}"
            f"{'▼CASSÉ' if self.ib_broken_down else ''}\n"
            f"  DayType={self.day_type.name} | VIX={self.vix:.1f}"
            f" | R80={'✅' if self.rule_80pct else '—'}"
            f"{'  | GAP_COMBLÉ!' if self.gap_filled else ''}\n"
            f"  → {self.reason}"
        )


# ═════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═════════════════════════════════════════════════════════════════════

# IB thresholds (ratio IB_range / ATR)
IB_NARROW_RATIO = 0.40    # IB < 40% ATR → compression, breakout probable
IB_WIDE_RATIO   = 0.80    # IB > 80% ATR → trend day

# Open Type detection (ticks)
OD_MIN_MOVE_ATR      = 0.15   # Open Drive : move min = 15% ATR sans retrace
OD_MAX_RETRACE_PCT   = 0.25   # OD : retrace max = 25% du move
OTD_MIN_TEST_TICKS   = 10     # OTD : test min = 10 ticks avant reversal
ORR_MIN_REJECT_ATR   = 0.10   # ORR : rejet min = 10% ATR
OAIR_MAX_RANGE_ATR   = 0.30   # OAIR : range max = 30% ATR (rotation)
POC_PROXIMITY_TICKS  = 10     # Proximité POC (pour open_zone AT_POC)

# Rule 80%
R80_BARS_IN_VA       = 8      # Nb barres minimum dans la VA (si barres ~1min = ~8min)

# Day Type
DT_NON_TREND_IB_ATR  = 0.15   # IB < 15% ATR
DT_NORMAL_IB_ATR     = 0.80   # IB > 80% ATR, pas d'extension
DT_TREND_EXT_RATIO   = 2.0    # Extension > 2× IB range

# Session timing (secondes depuis open RTH 9h30 ET)
IB_DURATION_SEC      = 3600   # 60 minutes pour former l'IB
OPEN_TYPE_MIN_SEC    = 1800   # 30 minutes minimum pour classifier l'open type


# ═════════════════════════════════════════════════════════════════════
# MOTEUR DE RÉGIME
# ═════════════════════════════════════════════════════════════════════

class RegimeEngine:
    """
    Moteur principal de classification du régime de trading.
    
    Alimenté par des snapshots JSON du bot Python.
    Maintient un état interne pour les calculs séquentiels
    (Open Type, Day Type, Rule 80%).
    """
    
    def __init__(self, tick_size: float = 0.25, symbol: str = "NQ"):
        self.tick_size = tick_size
        self.symbol = symbol
        
        # État de la session (reset chaque jour)
        self.session_date: Optional[str] = None
        self.open_price: float = 0.0          # Prix à 9h30 exact
        self.session_high: float = 0.0
        self.session_low: float = float('inf')
        self.first_30min_high: float = 0.0
        self.first_30min_low: float = float('inf')
        self.first_30min_prices: List[float] = []
        
        # PV levels (veille)
        self.pvah: float = 0.0
        self.pvpoc: float = 0.0
        self.pval: float = 0.0
        self.pvwap: float = 0.0
        
        # IB
        self.ib_high: float = 0.0
        self.ib_low: float = float('inf')
        self.ib_complete: bool = False
        
        # Open Type state
        self.open_type: OpenType = OpenType.UNKNOWN
        self.open_type_locked: bool = False
        self.od_direction: int = 0   # Tracking Open Drive
        self.od_max_price: float = 0.0
        self.od_min_price: float = float('inf')
        
        # Rule 80% state
        self.r80_state: str = "IDLE"  # IDLE → OUTSIDE → ENTERED_VA → CONFIRMED
        self.r80_direction: int = 0
        self.r80_bars_in_va: int = 0
        
        # Day Type tracking
        self.extension_up: bool = False
        self.extension_down: bool = False
        
        # NOUVEAU : Évolution dynamique du régime
        self.gap_filled: bool = False       # Le gap initial s'est comblé
        self.gap_direction: int = 0          # +1=gap up, -1=gap down
        self.price_vs_open_pct: float = 0.0  # % du move depuis l'open vs ATR
        
        # ATR (updated from snapshot)
        self.atr: float = 0.0
        
        # NOUVEAUX : Données enrichies depuis snapshot
        self.in_value_area: bool = False
        self.volatility_regime_cont: float = 0.0   # 0-1 continuous
        self.intermarket_divergence: int = 0         # 0=none, 1=divergence
        self.nq_es_relative_strength: float = 0.0    # z-score
        self.overnight_high: float = 0.0
        self.overnight_low: float = 0.0
        self.position_in_range: float = 50.0         # 0=low, 100=high
        self.day_range_pct: float = 0.0              # % range du jour
        
        # Dernier résultat
        self.result = RegimeResult()
        self.snap_count: int = 0
    
    # ─────────────────────────────────────────────────────────────────
    # RESET JOURNALIER
    # ─────────────────────────────────────────────────────────────────
    
    def reset_session(self):
        """Reset pour une nouvelle session RTH."""
        self.open_price = 0.0
        self.session_high = 0.0
        self.session_low = float('inf')
        self.first_30min_high = 0.0
        self.first_30min_low = float('inf')
        self.first_30min_prices = []
        self.ib_high = 0.0
        self.ib_low = float('inf')
        self.ib_complete = False
        self.open_type = OpenType.UNKNOWN
        self.open_type_locked = False
        self.od_direction = 0
        self.od_max_price = 0.0
        self.od_min_price = float('inf')
        self.r80_state = "IDLE"
        self.r80_direction = 0
        self.r80_bars_in_va = 0
        self.extension_up = False
        self.extension_down = False
        self.gap_filled = False
        self.gap_direction = 0
        self.price_vs_open_pct = 0.0
        self.result = RegimeResult()
        self.snap_count = 0
    
    # ─────────────────────────────────────────────────────────────────
    # UPDATE PRINCIPAL
    # ─────────────────────────────────────────────────────────────────
    
    def update(self, snap: Dict[str, Any]) -> RegimeResult:
        """
        Traite un snapshot et retourne le régime actuel.
        
        Args:
            snap: Dictionnaire JSON du bot Python
            
        Returns:
            RegimeResult avec le régime classifié
        """
        self.snap_count += 1
        
        # Extraire les données
        mid = snap.get('mid', 0)
        high = snap.get('high', mid)
        low = snap.get('low', mid)
        elapsed_s = snap.get('session_elapsed_s', snap.get('elapsed_s', 0))
        self.atr = snap.get('atr', self.atr) or self.atr
        vix = snap.get('vix', 0)
        
        # Nouveaux champs enrichis
        self.in_value_area = snap.get('in_value_area', False)
        self.volatility_regime_cont = snap.get('volatility_regime_cont', 0)
        im = snap.get('intermarkets', {})
        self.intermarket_divergence = im.get('divergence_flag', 0)
        self.nq_es_relative_strength = im.get('nq_es_rs_z_120s', 0)
        struct = snap.get('structure', {})
        self.overnight_high = struct.get('onh', 0)
        self.overnight_low = struct.get('onl', 0)
        self.position_in_range = snap.get('position_in_range', 50)
        self.day_range_pct = snap.get('day_range_pct', 0)
        
        # PV levels (depuis le snapshot)
        vva = snap.get('vva', {})
        if vva.get('vah', 0) > 0:
            self.pvah = vva['vah']
            self.pval = vva['val']
            self.pvpoc = vva['vpoc']
        self.pvwap = snap.get('pvwap', self.pvwap) or self.pvwap
        
        # IB (depuis structure ou calculé)
        struct = snap.get('structure', {})
        if struct.get('ibh', 0) > 0:
            self.ib_high = struct['ibh']
        if struct.get('ibl', 0) > 0:
            self.ib_low = struct['ibl']
        
        # Premier prix = open
        if self.open_price == 0 and mid > 0:
            self.open_price = mid
        
        # Session high/low
        if high > 0:
            self.session_high = max(self.session_high, high)
        if low > 0 and low < 1e9:
            self.session_low = min(self.session_low, low)
        
        # Premières 30 minutes — tracking pour open_type
        if elapsed_s <= OPEN_TYPE_MIN_SEC:
            self.first_30min_prices.append(mid)
            if high > 0:
                self.first_30min_high = max(self.first_30min_high, high)
            if low > 0 and low < 1e9:
                self.first_30min_low = min(self.first_30min_low, low)
        
        # IB tracking (premières 60 minutes OU depuis structure Sierra Chart)
        # Priorité : données structure si disponibles (plus fiable)
        if struct.get('ibh', 0) > 0 and struct.get('ibl', 0) > 0:
            self.ib_high = max(self.ib_high, struct['ibh'])
            if struct['ibl'] > 0:
                self.ib_low = min(self.ib_low, struct['ibl']) if self.ib_low < 1e9 else struct['ibl']
        
        # Aussi tracker depuis les high/low des barres
        if elapsed_s <= IB_DURATION_SEC:
            if high > 0:
                self.ib_high = max(self.ib_high, high)
            if low > 0 and low < 1e9:
                self.ib_low = min(self.ib_low, low) if self.ib_low < 1e9 else low
        
        if elapsed_s > IB_DURATION_SEC and not self.ib_complete:
            if self.ib_high > 0 and self.ib_low < 1e9:
                self.ib_complete = True
        
        # ─── Calculs ───
        
        # 1. Open Zone
        open_zone = self._calc_open_zone(self.open_price)
        
        # 2. Open Type (après 30 min)
        if elapsed_s >= OPEN_TYPE_MIN_SEC and not self.open_type_locked:
            self.open_type = self._classify_open_type(mid, elapsed_s)
            if elapsed_s >= IB_DURATION_SEC:
                self.open_type_locked = True
        
        # 3. IB Analysis
        ib_range = (self.ib_high - self.ib_low) / self.tick_size if self.ib_high > self.ib_low else 0
        atr_ticks = self.atr / self.tick_size if self.atr > 0 else 1
        ib_ratio = ib_range / atr_ticks if atr_ticks > 0 else 0
        ib_broken_up = mid > self.ib_high and self.ib_complete
        ib_broken_down = mid < self.ib_low and self.ib_complete
        
        # Track extensions
        if ib_broken_up:
            self.extension_up = True
        if ib_broken_down:
            self.extension_down = True
        
        # 4. Day Type (évolutif)
        day_type = self._calc_day_type(ib_ratio, mid)
        
        # 5. Rule 80%
        r80 = self._update_rule_80(mid, elapsed_s)
        
        # 6. VIX regime
        if vix > 35: vix_regime = 3
        elif vix > 25: vix_regime = 2
        elif vix > 15: vix_regime = 1
        else: vix_regime = 0
        
        # 6b. ÉVOLUTION DYNAMIQUE — Gap tracking
        if self.pvah > 0 and self.open_price > 0:
            if self.open_price > self.pvah:
                self.gap_direction = 1  # gap up
                if mid < self.pvah:
                    self.gap_filled = True
            elif self.open_price < self.pval:
                self.gap_direction = -1  # gap down
                if mid > self.pval:
                    self.gap_filled = True
        
        # 6c. Direction réelle du prix vs open (en % d'ATR)
        if self.atr > 0 and self.open_price > 0:
            self.price_vs_open_pct = (mid - self.open_price) / self.atr
        
        # 7. RÉGIME FINAL
        regime, direction, confidence, reason = self._determine_regime(
            open_zone, self.open_type, ib_ratio, ib_broken_up, ib_broken_down,
            day_type, r80, vix_regime, mid
        )
        
        # Ajustement intermarket (baisse confiance si divergence ES/NQ)
        regime, direction, confidence, reason = self._apply_intermarket_modifier(
            regime, direction, confidence, reason
        )
        
        # Construire le résultat
        self.result = RegimeResult(
            regime=regime,
            direction=direction,
            confidence=confidence,
            open_zone=open_zone,
            open_type=self.open_type,
            day_type=day_type,
            ib_range_ticks=ib_range,
            ib_range_atr=ib_ratio,
            ib_high=self.ib_high,
            ib_low=self.ib_low if self.ib_low < 1e9 else 0,
            ib_broken_up=ib_broken_up,
            ib_broken_down=ib_broken_down,
            ib_complete=self.ib_complete,
            rule_80pct=r80,
            rule_80pct_direction=self.r80_direction,
            gap_filled=self.gap_filled,
            gap_direction=self.gap_direction,
            vix=vix,
            vix_regime=vix_regime,
            open_price=self.open_price,
            session_minutes=elapsed_s / 60.0,
            reason=reason,
        )
        
        return self.result
    
    # ─────────────────────────────────────────────────────────────────
    # OPEN ZONE
    # ─────────────────────────────────────────────────────────────────
    
    def _calc_open_zone(self, price: float) -> OpenZone:
        """Classifie la zone d'ouverture vs VA veille."""
        if price <= 0 or self.pvah <= 0:
            return OpenZone.UNKNOWN
        
        poc_prox = POC_PROXIMITY_TICKS * self.tick_size
        
        # Distances
        dist_above_pvah = (price - self.pvah) / self.tick_size
        dist_below_pval = (self.pval - price) / self.tick_size
        
        if price > self.pvah:
            if dist_above_pvah > 50:  # > 50 ticks au-dessus
                return OpenZone.ABOVE_PDH
            return OpenZone.PDH_VAH
        elif price > self.pvpoc + poc_prox:
            return OpenZone.VAH_POC
        elif price > self.pvpoc - poc_prox:
            return OpenZone.AT_POC
        elif price > self.pval:
            return OpenZone.POC_VAL
        else:
            if dist_below_pval > 50:
                return OpenZone.BELOW_PDL
            return OpenZone.PVAL_PDL
    
    # ─────────────────────────────────────────────────────────────────
    # OPEN TYPE CLASSIFICATION
    # ─────────────────────────────────────────────────────────────────
    
    def _classify_open_type(self, current_price: float, elapsed_s: float) -> OpenType:
        """
        Classifie le type d'ouverture basé sur le comportement des 30 premières minutes.
        
        Logique simplifiée mais fidèle aux principes Market Profile :
        - OD  : move directionnel fort sans retrace significatif
        - OTD : test d'un niveau puis reversal
        - ORR : rejet brutal d'un extrême
        - OAIR: oscillation dans un range étroit (< 30% ATR)
        - OAOR: gap ouvert qui ne se comble pas
        - ODF : Open Drive qui échoue (retrace > 75%)
        """
        atr_ticks = self.atr / self.tick_size if self.atr > 0 else 400
        open_p = self.open_price
        
        if open_p <= 0:
            return OpenType.UNKNOWN
        
        # Utiliser IB high/low comme proxy si first_30min est incomplet
        hi_30 = self.first_30min_high if self.first_30min_high > 0 else self.ib_high
        lo_30 = self.first_30min_low if self.first_30min_low < 1e9 else (self.ib_low if self.ib_low < 1e9 else open_p)
        
        if hi_30 <= 0 or lo_30 <= 0 or lo_30 >= 1e9:
            return OpenType.UNKNOWN
        range_30 = (hi_30 - lo_30) / self.tick_size
        
        # Move depuis l'open
        up_move = (hi_30 - open_p) / self.tick_size
        down_move = (open_p - lo_30) / self.tick_size
        net_move = (current_price - open_p) / self.tick_size
        
        # Retrace depuis le high/low
        retrace_from_high = (hi_30 - current_price) / self.tick_size if hi_30 > current_price else 0
        retrace_from_low = (current_price - lo_30) / self.tick_size if current_price > lo_30 else 0
        
        # Minimum move pour considérer un drive
        min_drive = OD_MIN_MOVE_ATR * atr_ticks
        
        # ── OAOR : gap non comblé ──
        # Si on a ouvert hors de la VA veille ET le prix actuel reste hors VA
        if self.pvah > 0:
            if open_p > self.pvah and lo_30 > self.pvah and current_price > self.pvah:
                return OpenType.OAOR_UP
            if open_p < self.pval and hi_30 < self.pval and current_price < self.pval:
                return OpenType.OAOR_DOWN
        
        # ── Open Drive ──
        # Move fort, retrace minime
        if up_move > min_drive and retrace_from_high < up_move * OD_MAX_RETRACE_PCT:
            # Vérifier si c'est un ODF (drive qui a échoué)
            if net_move < up_move * 0.25:  # Le prix a retracé > 75% du move
                return OpenType.ODF_DOWN  # Drive up échoué = reversal bearish
            return OpenType.OD_UP
        
        if down_move > min_drive and retrace_from_low < down_move * OD_MAX_RETRACE_PCT:
            if net_move > -down_move * 0.25:
                return OpenType.ODF_UP    # Drive down échoué = reversal bullish
            return OpenType.OD_DOWN
        
        # ── OTD : Test puis reversal ──
        # Le prix teste un côté (> 10 ticks) puis revient de l'autre côté de l'open
        if up_move > OTD_MIN_TEST_TICKS and current_price < open_p:
            return OpenType.OTD_DOWN
        if down_move > OTD_MIN_TEST_TICKS and current_price > open_p:
            return OpenType.OTD_UP
        
        # ── ORR : Rejet brutal ──
        # Comme OTD mais plus violent — le move final est > le test initial
        orr_threshold = ORR_MIN_REJECT_ATR * atr_ticks
        if up_move > orr_threshold and (open_p - current_price) / self.tick_size > up_move:
            return OpenType.ORR_DOWN
        if down_move > orr_threshold and (current_price - open_p) / self.tick_size > down_move:
            return OpenType.ORR_UP
        
        # ── OAIR : Rotation dans un range étroit ──
        if range_30 < OAIR_MAX_RANGE_ATR * atr_ticks:
            return OpenType.OAIR
        
        # Défaut basé sur direction nette
        if abs(net_move) > min_drive * 0.5:
            return OpenType.OTD_UP if net_move > 0 else OpenType.OTD_DOWN
        
        return OpenType.OAIR  # Pas de conviction claire = rotation
    
    # ─────────────────────────────────────────────────────────────────
    # DAY TYPE
    # ─────────────────────────────────────────────────────────────────
    
    def _calc_day_type(self, ib_ratio: float, current_price: float) -> DayType:
        """Classifie le type de journée (évolutif)."""
        if not self.ib_complete:
            return DayType.UNKNOWN
        
        ib_range = self.ib_high - self.ib_low
        if ib_range <= 0:
            return DayType.UNKNOWN
        
        # Extension au-delà de l'IB
        ext_up = max(0, self.session_high - self.ib_high)
        ext_down = max(0, self.ib_low - self.session_low)
        
        # NonTrend : IB très petite
        if ib_ratio < DT_NON_TREND_IB_ATR:
            return DayType.NON_TREND
        
        # Trend Day : extension > 2× IB d'un côté
        if ext_up > DT_TREND_EXT_RATIO * ib_range and not self.extension_down:
            return DayType.TREND
        if ext_down > DT_TREND_EXT_RATIO * ib_range and not self.extension_up:
            return DayType.TREND
        
        # Neutral : extension des 2 côtés
        if self.extension_up and self.extension_down:
            return DayType.NEUTRAL
        
        # NormVar : extension 1 côté
        if self.extension_up or self.extension_down:
            return DayType.NORM_VAR
        
        # Normal : IB large, pas d'extension
        if ib_ratio > DT_NORMAL_IB_ATR:
            return DayType.NORMAL
        
        return DayType.NORM_VAR  # Défaut : le plus fréquent
    
    # ─────────────────────────────────────────────────────────────────
    # RULE 80%
    # ─────────────────────────────────────────────────────────────────
    
    def _update_rule_80(self, price: float, elapsed_s: float) -> bool:
        """
        Machine à états pour la Règle des 80%.
        
        Condition : Open HORS de la VA veille → prix entre dans la VA 
                    → reste dans la VA pendant R80_BARS_IN_VA barres
                    → 80% de probabilité de traverser toute la VA.
        
        Utilise `in_value_area` du snapshot comme source de vérité quand disponible.
        """
        if self.pvah <= 0 or self.pval <= 0:
            return False
        
        # Utiliser in_value_area du snapshot (plus fiable car calculé par Sierra)
        in_va = self.in_value_area if self.in_value_area is not None else (self.pval <= price <= self.pvah)
        
        if self.r80_state == "IDLE":
            # L'open était-il hors de la VA ?
            if self.open_price > self.pvah:
                self.r80_state = "OUTSIDE"
                self.r80_direction = -1  # Vers PVAL (traverser vers le bas)
            elif self.open_price < self.pval:
                self.r80_state = "OUTSIDE"
                self.r80_direction = +1  # Vers PVAH (traverser vers le haut)
            else:
                self.r80_state = "NA"  # Open dans la VA → règle non applicable
        
        elif self.r80_state == "OUTSIDE":
            if in_va:
                self.r80_state = "ENTERED_VA"
                self.r80_bars_in_va = 1
        
        elif self.r80_state == "ENTERED_VA":
            if in_va:
                self.r80_bars_in_va += 1
                if self.r80_bars_in_va >= R80_BARS_IN_VA:
                    self.r80_state = "CONFIRMED"
                    return True
            else:
                # Sorti de la VA → reset
                self.r80_state = "OUTSIDE"
                self.r80_bars_in_va = 0
        
        elif self.r80_state == "CONFIRMED":
            return True
        
        return False
    
    # ─────────────────────────────────────────────────────────────────
    # RÉGIME FINAL
    # ─────────────────────────────────────────────────────────────────
    
    def _determine_regime(
        self, open_zone, open_type, ib_ratio, ib_broken_up, ib_broken_down,
        day_type, r80, vix_regime, current_price
    ) -> tuple:
        """
        Détermine le régime final — AVEC ÉVOLUTION DYNAMIQUE.
        
        Principe : l'open_type donne le biais initial, mais le marché peut
        CONTREDIRE ce biais. Quand ça arrive, on doit changer de régime.
        
        Cas critiques gérés :
        - OAOR_UP + gap comblé → REVERSAL BEARISH (pas trend bullish!)
        - OAOR_UP + IB cassé vers le bas → BREAKOUT/TREND BEARISH
        - OD_UP + prix retombe sous l'open → ODF_DOWN → REVERSAL
        - TREND + extensions des deux côtés → ROTATION
        
        Returns: (regime, direction, confidence, reason)
        """
        # ── VIX extrême → INCERTAIN ──
        if vix_regime >= 3 or self.volatility_regime_cont > 0.8:
            return (Regime.INCERTAIN, 0, 0.2, "Volatilité extrême (VIX>35 ou vol_regime>0.8)")
        
        # ── Pas encore assez de données ──
        if open_type == OpenType.UNKNOWN:
            return (Regime.INCERTAIN, 0, 0.1, "Open type pas encore classifié")
        
        # ══════════════════════════════════════════════════════════════
        # COUCHE 1 : OVERRIDES DYNAMIQUES (priorité sur l'open_type)
        # ══════════════════════════════════════════════════════════════
        
        # ── OVERRIDE : OAOR dont le gap s'est comblé ──
        if open_type in (OpenType.OAOR_UP, OpenType.OAOR_DOWN) and self.gap_filled:
            # Le gap s'est comblé → l'OAOR est invalidé
            # Analyser ce qui se passe maintenant
            if ib_broken_down and self.gap_direction > 0:
                # Gap up comblé + IB cassé en bas = SELL-OFF
                if day_type == DayType.TREND:
                    return (Regime.TREND, -1, 0.85, "Gap UP comblé + sell-off = Trend Day BEARISH")
                return (Regime.BREAKOUT, -1, 0.75, "Gap UP comblé + IB cassé bas = Breakout BEARISH")
            elif ib_broken_up and self.gap_direction < 0:
                if day_type == DayType.TREND:
                    return (Regime.TREND, 1, 0.85, "Gap DOWN comblé + rally = Trend Day BULLISH")
                return (Regime.BREAKOUT, 1, 0.75, "Gap DOWN comblé + IB cassé haut = Breakout BULLISH")
            else:
                # Gap comblé mais pas de break IB clair → reversal puis rotation
                d = -1 if self.gap_direction > 0 else 1
                if r80:
                    return (Regime.REVERSAL, d, 0.80, f"Gap comblé + Rule 80% = Reversal {'BEAR' if d<0 else 'BULL'}")
                return (Regime.REVERSAL, d, 0.65, f"Gap comblé = Reversal {'BEAR' if d<0 else 'BULL'}")
        
        # ── OVERRIDE : Prix très loin de l'open dans la mauvaise direction ──
        # Si OAOR_UP mais prix < open - 30% ATR → le gap tient mais le marché vend
        if open_type == OpenType.OAOR_UP and self.price_vs_open_pct < -0.30:
            if ib_broken_down:
                return (Regime.TREND, -1, 0.80, "OAOR_UP invalide: prix -30% ATR sous open + IB cassé bas")
            return (Regime.REVERSAL, -1, 0.60, "OAOR_UP affaibli: prix significativement sous l'open")
        if open_type == OpenType.OAOR_DOWN and self.price_vs_open_pct > 0.30:
            if ib_broken_up:
                return (Regime.TREND, 1, 0.80, "OAOR_DOWN invalide: prix +30% ATR au-dessus open + IB cassé haut")
            return (Regime.REVERSAL, 1, 0.60, "OAOR_DOWN affaibli: prix significativement au-dessus de l'open")
        
        # ── OVERRIDE : Extensions contradictoires ──
        if self.extension_up and self.extension_down:
            # Les deux côtés de l'IB ont été cassés → journée de rotation large
            return (Regime.ROTATION, 0, 0.60, "Extensions UP et DOWN = rotation large (Double Distribution)")
        
        # ══════════════════════════════════════════════════════════════
        # COUCHE 2 : CLASSIFICATION STANDARD (basée sur open_type)
        # ══════════════════════════════════════════════════════════════
        
        # ── REVERSAL : ODF ou ORR ──
        if open_type in (OpenType.ODF_UP, OpenType.ODF_DOWN):
            d = 1 if open_type == OpenType.ODF_UP else -1
            conf = 0.90 if r80 else 0.75
            reason = f"ODF détecté → reversal {'haussier' if d > 0 else 'baissier'}"
            if r80:
                reason += " + Règle 80% active"
            return (Regime.REVERSAL, d, conf, reason)
        
        if open_type in (OpenType.ORR_UP, OpenType.ORR_DOWN):
            d = 1 if open_type == OpenType.ORR_UP else -1
            conf = 0.70 if r80 else 0.60
            reason = f"ORR → rejet {'haussier' if d > 0 else 'baissier'}"
            return (Regime.REVERSAL, d, conf, reason)
        
        # ── TREND : Open Drive + IB large ──
        if open_type in (OpenType.OD_UP, OpenType.OD_DOWN):
            d = 1 if open_type == OpenType.OD_UP else -1
            conf = 0.85
            if ib_ratio > IB_WIDE_RATIO:
                conf = 0.90
            return (Regime.TREND, d, conf, f"Open Drive {'UP' if d > 0 else 'DOWN'}")
        
        if day_type == DayType.TREND:
            # Direction basée sur l'extension la plus récente
            if self.extension_up and not self.extension_down:
                d = 1
            elif self.extension_down and not self.extension_up:
                d = -1
            else:
                d = 1 if self.price_vs_open_pct > 0 else -1
            return (Regime.TREND, d, 0.80, "Trend Day confirmé par extension > 2×IB")
        
        # ── OAOR valide (gap non comblé) ──
        if open_type in (OpenType.OAOR_UP, OpenType.OAOR_DOWN):
            d = 1 if open_type == OpenType.OAOR_UP else -1
            # Vérifier que le prix ne contredit pas
            if d > 0 and ib_broken_down:
                return (Regime.BREAKOUT, -1, 0.70, "OAOR_UP mais IB cassé bas → breakout baissier")
            if d < 0 and ib_broken_up:
                return (Regime.BREAKOUT, 1, 0.70, "OAOR_DOWN mais IB cassé haut → breakout haussier")
            return (Regime.TREND, d, 0.65, f"Gap {'haussier' if d > 0 else 'baissier'} non comblé")
        
        # ── BREAKOUT : IB étroite ──
        if ib_ratio < IB_NARROW_RATIO and self.ib_complete:
            d = 0
            if ib_broken_up: d = 1
            elif ib_broken_down: d = -1
            conf = 0.70 if d != 0 else 0.50
            reason = "IB étroite → breakout"
            if d != 0:
                reason += f" {'haussier' if d > 0 else 'baissier'} confirmé"
            else:
                reason += " en attente de direction"
            return (Regime.BREAKOUT, d, conf, reason)
        
        # ── ROTATION : OAIR + IB moyenne ──
        if open_type == OpenType.OAIR:
            return (Regime.ROTATION, 0, 0.65, "Auction in Range → rotation")
        
        if day_type == DayType.NEUTRAL:
            return (Regime.ROTATION, 0, 0.55, "Neutral Day → fader les extrêmes")
        
        if day_type == DayType.NORMAL:
            return (Regime.ROTATION, 0, 0.55, "Normal Day → range, pas d'extension")
        
        # ── OTD → direction modérée ──
        if open_type in (OpenType.OTD_UP, OpenType.OTD_DOWN):
            d = 1 if open_type == OpenType.OTD_UP else -1
            if ib_ratio > IB_WIDE_RATIO:
                return (Regime.TREND, d, 0.70, f"OTD {'UP' if d > 0 else 'DOWN'} + IB large")
            return (Regime.ROTATION, d, 0.55, f"OTD {'UP' if d > 0 else 'DOWN'} → rotation directionnelle")
        
        # ── DÉFAUT ──
        return (Regime.INCERTAIN, 0, 0.30, "Pas de pattern clair identifié")
    
    def _apply_intermarket_modifier(self, regime, direction, confidence, reason):
        """Ajuste confiance si divergence intermarket ES/NQ détectée."""
        if self.intermarket_divergence != 0:
            confidence = max(0.10, confidence - 0.15)
            reason += " ⚠️ divergence ES/NQ"
        # NQ relative strength extreme = potentiel reversal
        if abs(self.nq_es_relative_strength) > 2.0:
            confidence = max(0.10, confidence - 0.10)
            reason += f" | RS_z={self.nq_es_relative_strength:+.1f}"
        return regime, direction, confidence, reason


# ═════════════════════════════════════════════════════════════════════
# TESTS ET DÉMO
# ═════════════════════════════════════════════════════════════════════

def demo_with_snapshot():
    """Démo avec le snapshot réel du bot Python."""
    
    # Snapshot NQ réel
    snap = {
        "mid": 25677.88, "high": 25680.50, "low": 25677.25,
        "vix": 15.87, "atr": 371.05,
        "session_elapsed_s": 135, "session_progress": 0.004167,
        "pvwap": 25723.77,
        "vva": {"vah": 25971.75, "val": 25548.00, "vpoc": 25690.00},
        "structure": {"onh": 25435.50, "onl": 25435.00,
                      "ibh": 25762.50, "ibl": 25564.75},
        "volatility_regime": 1.0,
        "session_id": "US",
    }
    
    print("=" * 72)
    print("  DÉMO — Snapshot NQ réel")
    print("=" * 72)
    
    engine = RegimeEngine(tick_size=0.25, symbol="NQ")
    result = engine.update(snap)
    print(f"\n{result.summary()}")
    
    # Simuler l'avancement du temps (30 min plus tard)
    print("\n" + "─" * 72)
    print("  Simulation : +30 minutes (prix monte à 25720)")
    print("─" * 72)
    
    snap2 = dict(snap)
    snap2["mid"] = 25720.00
    snap2["high"] = 25725.00
    snap2["low"] = 25670.00
    snap2["session_elapsed_s"] = 1935  # 32 minutes
    
    result2 = engine.update(snap2)
    print(f"\n{result2.summary()}")
    
    # +60 min, IB formée
    print("\n" + "─" * 72)
    print("  Simulation : +60 minutes (IB complète, prix à 25750)")
    print("─" * 72)
    
    snap3 = dict(snap)
    snap3["mid"] = 25750.00
    snap3["high"] = 25765.00
    snap3["low"] = 25660.00
    snap3["session_elapsed_s"] = 3700
    
    result3 = engine.update(snap3)
    print(f"\n{result3.summary()}")
    
    # +120 min, breakout IB
    print("\n" + "─" * 72)
    print("  Simulation : +120 minutes (breakout IB High, prix à 25780)")
    print("─" * 72)
    
    snap4 = dict(snap)
    snap4["mid"] = 25780.00
    snap4["high"] = 25790.00
    snap4["low"] = 25740.00
    snap4["session_elapsed_s"] = 7200
    
    result4 = engine.update(snap4)
    print(f"\n{result4.summary()}")


def demo_scenarios():
    """Test les différents scénarios de régime."""
    
    print("\n" + "=" * 72)
    print("  TEST DES 5 RÉGIMES")
    print("=" * 72)
    
    scenarios = [
        {
            "name": "TREND — Open Drive Up",
            "snaps": [
                {"mid": 26000, "high": 26005, "low": 25995, "atr": 370, "vix": 18,
                 "session_elapsed_s": 60, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 0, "ibl": 0, "onh": 0, "onl": 0}},
                # Prix monte sans retrace pendant 30 min
                {"mid": 26080, "high": 26085, "low": 26070, "atr": 370, "vix": 18,
                 "session_elapsed_s": 1900, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 26085, "ibl": 25995, "onh": 0, "onl": 0}},
            ]
        },
        {
            "name": "ROTATION — Open Auction In Range",
            "snaps": [
                {"mid": 25870, "high": 25875, "low": 25865, "atr": 370, "vix": 16,
                 "session_elapsed_s": 60, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 0, "ibl": 0, "onh": 0, "onl": 0}},
                # Prix oscille dans un range étroit
                {"mid": 25885, "high": 25895, "low": 25855, "atr": 370, "vix": 16,
                 "session_elapsed_s": 1900, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 25895, "ibl": 25855, "onh": 0, "onl": 0}},
            ]
        },
        {
            "name": "REVERSAL — Open Drive Fail",
            "snaps": [
                {"mid": 25950, "high": 25960, "low": 25945, "atr": 370, "vix": 20,
                 "session_elapsed_s": 60, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 0, "ibl": 0, "onh": 0, "onl": 0}},
                # Drive up initial puis crash
                {"mid": 25850, "high": 25980, "low": 25840, "atr": 370, "vix": 20,
                 "session_elapsed_s": 1900, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 25980, "ibl": 25840, "onh": 0, "onl": 0}},
            ]
        },
        {
            "name": "BREAKOUT — IB étroite",
            "snaps": [
                {"mid": 25870, "high": 25872, "low": 25868, "atr": 370, "vix": 14,
                 "session_elapsed_s": 60, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 0, "ibl": 0, "onh": 0, "onl": 0}},
                # Range très étroit pendant 30 min
                {"mid": 25878, "high": 25890, "low": 25860, "atr": 370, "vix": 14,
                 "session_elapsed_s": 1900, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 25890, "ibl": 25860, "onh": 0, "onl": 0}},
                # IB formée, étroite
                {"mid": 25882, "high": 25892, "low": 25858, "atr": 370, "vix": 14,
                 "session_elapsed_s": 3700, "pvwap": 25900,
                 "vva": {"vah": 25950, "val": 25800, "vpoc": 25870},
                 "structure": {"ibh": 25892, "ibl": 25858, "onh": 0, "onl": 0}},
            ]
        },
    ]
    
    for scenario in scenarios:
        print(f"\n{'─' * 72}")
        print(f"  Scénario : {scenario['name']}")
        print(f"{'─' * 72}")
        
        engine = RegimeEngine(tick_size=0.25, symbol="NQ")
        for i, snap in enumerate(scenario['snaps']):
            result = engine.update(snap)
            elapsed = snap['session_elapsed_s']
            print(f"\n  [T+{elapsed//60}min] Prix={snap['mid']}")
            print(f"  {result.summary()}")


if __name__ == "__main__":
    demo_with_snapshot()
    demo_scenarios()
