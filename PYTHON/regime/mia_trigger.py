"""
MIA Trigger Engine — Quand appuyer sur le bouton
Rôle : Quand le prix est dans une zone active, évaluer si l'order flow confirme.
Auteur : MIA Trading System | Date : 2026-03-01
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, List, Dict, Any
from mia_regime import RegimeResult, Regime
from mia_zones import Zone, ZoneSource

# ═════════════════════════════════════════════════════════════════════
# CONSTANTES PAR RÉGIME
# ═════════════════════════════════════════════════════════════════════

# Seuils BN score (force signal Bataille Navale)
BN_THRESHOLD = {
    Regime.TREND:     0.03,    # Moins exigeant, le régime fait le travail
    Regime.ROTATION:  0.05,    # Plus exigeant, on trade contre le flux immédiat
    Regime.REVERSAL:  0.10,    # Très exigeant, signal doit être VIOLENT
    Regime.BREAKOUT:  0.05,    # Moyen, on attend confirmation du break
    Regime.INCERTAIN: 0.15,    # Ultra exigeant, presque impossible
}

# Seuils delta pourcentage
DELTA_PCT_THRESHOLD = 0.05     # |deltaPct| > 5% pour confirmer direction

# Seuils absorption
ABSORB_MIN = 2                 # Minimum 2 absorptions pour signal

# CVD minimum change
CVD_MIN_CHANGE = 100           # Changement CVD jour minimum (en contracts)


# ═════════════════════════════════════════════════════════════════════
# STRUCTURES
# ═════════════════════════════════════════════════════════════════════

class TriggerSignal(IntEnum):
    """Résultat du trigger"""
    NO_ZONE      = 0    # Pas dans une zone active
    NO_TRIGGER   = 1    # Dans une zone mais order flow pas aligné
    WEAK         = 2    # Signal faible (1 confirmation)
    MODERATE     = 3    # Signal modéré (2 confirmations)
    STRONG       = 4    # Signal fort (3+ confirmations)


@dataclass
class TriggerResult:
    """Résultat complet de l'évaluation du trigger"""
    signal: TriggerSignal = TriggerSignal.NO_ZONE
    direction: int = 0          # +1=LONG, -1=SHORT
    zone: Optional[Zone] = None # Zone qui a déclenché
    confidence: float = 0.0     # 0.0 à 1.0

    # Détails des 8 confirmations
    bn_aligned: bool = False
    delta_aligned: bool = False
    cvd_aligned: bool = False
    absorb_present: bool = False
    vwap_slope_aligned: bool = False
    dom_aligned: bool = False
    institutional_aligned: bool = False   # NOUVEAU
    micro_aligned: bool = False           # NOUVEAU

    # Valeurs brutes
    bn_score: float = 0.0
    delta_pct: float = 0.0
    cvd_day: int = 0
    absorb_count: int = 0
    vwap_slope: float = 0.0
    institutional_pressure: float = 0.0   # NOUVEAU
    ob_center: float = 0.0               # NOUVEAU

    reason: str = ""
    confirmations: int = 0

    def summary(self) -> str:
        if self.signal == TriggerSignal.NO_ZONE:
            return "TRIGGER: Pas dans une zone active"
        if self.signal == TriggerSignal.NO_TRIGGER:
            return f"TRIGGER: Zone {self.zone.name if self.zone else '?'} — pas de confirmation OF"

        dir_str = "LONG" if self.direction > 0 else "SHORT"
        checks = []
        if self.bn_aligned: checks.append(f"BN={self.bn_score:+.3f}")
        if self.delta_aligned: checks.append(f"Δ={self.delta_pct:+.1%}")
        if self.cvd_aligned: checks.append(f"CVD={self.cvd_day:+d}")
        if self.absorb_present: checks.append(f"ABS={self.absorb_count}")
        if self.vwap_slope_aligned: checks.append(f"VWAP_S={self.vwap_slope:+.4f}")
        if self.dom_aligned: checks.append("DOM")
        if self.institutional_aligned: checks.append(f"INST={self.institutional_pressure:.2f}")
        if self.micro_aligned: checks.append(f"µOB={self.ob_center:+.2f}")

        zone_name = self.zone.name if self.zone else "?"
        zone_price = f"{self.zone.price:.2f}" if self.zone else "?"
        return (
            f"TRIGGER: {self.signal.name} {dir_str} "
            f"@ {zone_name} ({zone_price}) "
            f"| {self.confirmations} conf: {', '.join(checks)}\n"
            f"  → {self.reason}"
        )


# ═════════════════════════════════════════════════════════════════════
# MOTEUR DE TRIGGER
# ═════════════════════════════════════════════════════════════════════

class TriggerEngine:
    """
    Évalue si l'order flow confirme un trade dans une zone active.

    Logique :
    1. Trouver la zone proximale (prix < ZONE_PROXIMITY_TICKS)
    2. Déterminer la direction attendue (zone.direction)
    3. Vérifier les confirmations order flow :
       - BN score aligné avec la direction
       - Delta / DeltaPct aligné
       - CVD journée aligné
       - Absorption visible (contre-direction)
       - VWAP slope aligné
       - DOM imbalance
    4. Compter les confirmations et scorer

    Seuils adaptés au régime :
    - TREND    : 2 confirmations suffisent (le régime porte)
    - ROTATION : 3 confirmations (on trade contre le flux)
    - REVERSAL : 3+ confirmations fortes (signal violent)
    - BREAKOUT : 2+ avec volume élevé
    """

    def __init__(self, tick_size: float = 0.25, symbol: str = "NQ"):
        self.tick_size = tick_size
        self.symbol = symbol

    def evaluate(
        self, snap: Dict[str, Any], zones: List[Zone], regime: RegimeResult
    ) -> TriggerResult:
        """
        Évalue le trigger sur la zone la plus proche.

        Args:
            snap: Snapshot JSON
            zones: Zones triées du ZoneEngine
            regime: Régime du RegimeEngine

        Returns:
            TriggerResult
        """
        # 1. Trouver la zone proximate
        target_zone = None
        for z in zones:
            if z.is_proximate:
                # En TREND, ne garder que les zones dans le bon sens
                if regime.regime == Regime.TREND and regime.direction != 0:
                    if regime.direction > 0 and z.direction < 0:
                        continue  # Pas de short en trend up
                    if regime.direction < 0 and z.direction > 0:
                        continue  # Pas de long en trend down
                target_zone = z
                break

        if target_zone is None:
            return TriggerResult(signal=TriggerSignal.NO_ZONE)

        # 2. Direction attendue
        trade_dir = self._determine_direction(target_zone, regime, snap)
        if trade_dir == 0:
            return TriggerResult(
                signal=TriggerSignal.NO_TRIGGER, zone=target_zone,
                reason="Direction ambiguë — zone neutre sans biais régime"
            )

        # 3. Extraire TOUTES les données order flow
        bn = snap.get('bataille_navale', {})
        bn_score = bn.get('score', 0)
        delta_pct = snap.get('deltaPct', 0)
        cvd_day = snap.get('cum_delta_day', 0)
        absorb_ask = bn.get('absorb_ask', 0)
        absorb_bid = bn.get('absorb_bid', 0)
        vwap_slope = snap.get('vwap_analysis', {}).get('vwap_slope_10', 0)
        dom = snap.get('dom_features', {})
        dom_imb = dom.get('imbalance_1_3', 0)

        # Nouveaux champs
        inst_pressure = snap.get('institutional_pressure', 0.5)  # 0=bearish, 1=bullish
        ob_center = snap.get('ob_center_tanh', 0)               # -1=bearish, +1=bullish
        delta_burst = snap.get('delta_burst', 0)
        delta_flip = snap.get('delta_flip', False)
        stacked_ask = snap.get('stacked_imbalance_ask_rows', 0)
        stacked_bid = snap.get('stacked_imbalance_bid_rows', 0)
        microprice = snap.get('microprice', 0)
        mid = snap.get('mid', 0)
        mia_bull = snap.get('mia_bullish_score', 0.5)  # 0=bearish, 1=bullish

        # 4. Évaluer les 8 confirmations
        result = TriggerResult(zone=target_zone, direction=trade_dir)
        result.bn_score = bn_score
        result.delta_pct = delta_pct
        result.cvd_day = cvd_day
        result.vwap_slope = vwap_slope
        result.institutional_pressure = inst_pressure
        result.ob_center = ob_center

        bn_thresh = BN_THRESHOLD.get(regime.regime, 0.10)

        # ── CHECK 1 : BN Score ──
        # Principal : score > seuil dans la direction
        # Renforcé : edge dominance OU triple imprints alignés
        if trade_dir > 0 and bn_score > bn_thresh:
            result.bn_aligned = True
        elif trade_dir < 0 and bn_score < -bn_thresh:
            result.bn_aligned = True
        elif trade_dir > 0 and bn.get('edge_buy', 0) > bn.get('edge_sell', 0) * 1.5:
            result.bn_aligned = True
        elif trade_dir < 0 and bn.get('edge_sell', 0) > bn.get('edge_buy', 0) * 1.5:
            result.bn_aligned = True
        # Renforcement par triple imprints
        elif trade_dir > 0 and bn.get('triple_bid', 0) > bn.get('triple_ask', 0) * 1.3:
            result.bn_aligned = True
        elif trade_dir < 0 and bn.get('triple_ask', 0) > bn.get('triple_bid', 0) * 1.3:
            result.bn_aligned = True

        # ── CHECK 2 : Delta ──
        # Principal : deltaPct aligné
        # Renforcé : delta_burst > 30 dans la direction OU delta_flip favorable
        if trade_dir > 0 and delta_pct > DELTA_PCT_THRESHOLD:
            result.delta_aligned = True
        elif trade_dir < 0 and delta_pct < -DELTA_PCT_THRESHOLD:
            result.delta_aligned = True
        # Renforcement par burst de delta
        elif delta_burst > 30:
            if trade_dir > 0 and delta_pct > 0:
                result.delta_aligned = True
            elif trade_dir < 0 and delta_pct < 0:
                result.delta_aligned = True

        # ── CHECK 3 : CVD jour ──
        if trade_dir > 0 and cvd_day > CVD_MIN_CHANGE:
            result.cvd_aligned = True
        elif trade_dir < 0 and cvd_day < -CVD_MIN_CHANGE:
            result.cvd_aligned = True

        # ── CHECK 4 : Absorption ──
        # Renforcé par stacked imbalances
        total_absorb_bull = absorb_ask + stacked_bid  # Ask absorbée + bid empilé = bullish
        total_absorb_bear = absorb_bid + stacked_ask  # Bid absorbée + ask empilé = bearish
        if trade_dir > 0 and total_absorb_bull >= ABSORB_MIN:
            result.absorb_present = True
            result.absorb_count = total_absorb_bull
        elif trade_dir < 0 and total_absorb_bear >= ABSORB_MIN:
            result.absorb_present = True
            result.absorb_count = total_absorb_bear

        # ── CHECK 5 : VWAP Slope ──
        if trade_dir > 0 and vwap_slope > 0.005:
            result.vwap_slope_aligned = True
        elif trade_dir < 0 and vwap_slope < -0.005:
            result.vwap_slope_aligned = True

        # ── CHECK 6 : DOM Imbalance ──
        # Renforcé par depth et slope du book
        depth_ask = dom.get('depth_ask', 0)
        depth_bid = dom.get('depth_bid', 0)
        if trade_dir > 0 and (dom_imb > 0.15 or (depth_bid > depth_ask * 1.3)):
            result.dom_aligned = True
        elif trade_dir < 0 and (dom_imb < -0.15 or (depth_ask > depth_bid * 1.3)):
            result.dom_aligned = True

        # ── CHECK 7 : Pression Institutionnelle (NOUVEAU) ──
        # institutional_pressure : 0 = full bearish, 0.5 = neutre, 1 = full bullish
        if trade_dir > 0 and inst_pressure > 0.60:
            result.institutional_aligned = True
        elif trade_dir < 0 and inst_pressure < 0.40:
            result.institutional_aligned = True

        # ── CHECK 8 : Micro-structure (NOUVEAU) ──
        # Combine ob_center_tanh (-1 à +1) et microprice vs mid
        micro_bias = 0.0
        if ob_center != 0:
            micro_bias += ob_center * 0.5  # -0.5 à +0.5
        if microprice > 0 and mid > 0:
            micro_diff = (microprice - mid) / self.tick_size  # en ticks
            micro_bias += max(-0.5, min(0.5, micro_diff * 0.1))  # clamp
        if trade_dir > 0 and micro_bias > 0.20:
            result.micro_aligned = True
        elif trade_dir < 0 and micro_bias < -0.20:
            result.micro_aligned = True

        # 5. Compter et classifier
        confs = sum([
            result.bn_aligned, result.delta_aligned, result.cvd_aligned,
            result.absorb_present, result.vwap_slope_aligned, result.dom_aligned,
            result.institutional_aligned, result.micro_aligned
        ])
        result.confirmations = confs

        # Seuils par régime (ajustés pour 8 checks au lieu de 6)
        min_confs = self._min_confirmations(regime.regime)

        if confs >= min_confs + 2:
            result.signal = TriggerSignal.STRONG
            result.confidence = min(0.90, 0.50 + confs * 0.08)
        elif confs >= min_confs + 1:
            result.signal = TriggerSignal.MODERATE
            result.confidence = min(0.75, 0.40 + confs * 0.08)
        elif confs >= min_confs:
            result.signal = TriggerSignal.WEAK
            result.confidence = min(0.60, 0.25 + confs * 0.08)
        else:
            result.signal = TriggerSignal.NO_TRIGGER
            result.confidence = confs * 0.08
            result.reason = f"Seulement {confs}/{min_confs} confirmations"
            return result

        # Bonus haute conviction zone
        if target_zone.is_high_conviction:
            result.confidence = min(1.0, result.confidence + 0.10)
            result.reason = f"Zone HC {target_zone.name} + {confs}/8 confirmations OF"
        else:
            result.reason = f"Zone {target_zone.name} + {confs}/8 confirmations OF"

        # Bonus Rule 80%
        if regime.rule_80pct and trade_dir == regime.rule_80pct_direction:
            result.confidence = min(1.0, result.confidence + 0.10)
            result.reason += " + Rule80%"

        # Bonus mia_bullish_score (composite ancien bot)
        if trade_dir > 0 and mia_bull > 0.65:
            result.confidence = min(1.0, result.confidence + 0.05)
        elif trade_dir < 0 and mia_bull < 0.35:
            result.confidence = min(1.0, result.confidence + 0.05)

        # Malus delta_flip (changement récent de direction delta = prudence)
        if delta_flip:
            result.confidence = max(0.10, result.confidence - 0.10)
            result.reason += " ⚠️ delta_flip"

        return result

    def _determine_direction(self, zone: Zone, regime: RegimeResult, snap: Dict = None) -> int:
        """Détermine la direction du trade."""
        zone_dir = zone.direction  # +1=support(long), -1=resist(short), 0=ambigu

        if zone_dir != 0:
            if regime.regime == Regime.TREND:
                if regime.direction != 0 and zone_dir != regime.direction:
                    return 0
                return regime.direction if regime.direction != 0 else zone_dir
            elif regime.regime == Regime.ROTATION:
                return zone_dir
            elif regime.regime == Regime.REVERSAL:
                return regime.direction if regime.direction != 0 else zone_dir
            elif regime.regime == Regime.BREAKOUT:
                return regime.direction if regime.direction != 0 else zone_dir
            return zone_dir

        # Zone neutre (S/R, prix pile dessus) — déterminer direction
        # En TREND : direction du régime
        if regime.regime == Regime.TREND:
            return regime.direction
        # En REVERSAL : direction du régime
        if regime.regime == Regime.REVERSAL:
            return regime.direction
        # En BREAKOUT : direction du break
        if regime.regime == Regime.BREAKOUT:
            return regime.direction
        # En ROTATION ou INCERTAIN : utiliser l'order flow (acheter si flow haussier sur support)
        if snap:
            delta_pct = snap.get('deltaPct', snap.get('smart_money_flow', 0))
            if delta_pct > DELTA_PCT_THRESHOLD: return 1
            elif delta_pct < -DELTA_PCT_THRESHOLD: return -1
            # Fallback BN
            bn = snap.get('bataille_navale', {})
            if bn.get('score', 0) > 0.03: return 1
            elif bn.get('score', 0) < -0.03: return -1
        return regime.direction  # Dernier recours

    def _min_confirmations(self, regime: Regime) -> int:
        """Nombre minimum de confirmations par régime (sur 8 checks)."""
        return {
            Regime.TREND:     3,  # Le régime porte, 3/8 suffit
            Regime.ROTATION:  4,  # Contre le flux, plus de confirmations
            Regime.REVERSAL:  4,  # Signal fort requis
            Regime.BREAKOUT:  3,  # Volume + direction suffisent
            Regime.INCERTAIN: 6,  # Quasi impossible = c'est le but
        }.get(regime, 5)


# ═════════════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════════════

def demo():
    from mia_regime import RegimeResult, Regime, OpenType, OpenZone
    from mia_zones import Zone, ZoneSource, ZoneEngine, format_zones

    # Snapshot avec signaux d'achat clairs (prix au PVPOC, BN haussier, CVD positif)
    snap_bullish = {
        "mid": 25690.00, "high": 25692.00, "low": 25688.00,
        "vix": 15.87, "atr": 371.05, "session_elapsed_s": 5000,
        "pvwap": 25723.77, "pvwap_up1": 25758.66, "pvwap_dn1": 25688.88,
        "vva": {"vah": 25971.75, "val": 25548.00, "vpoc": 25690.00},
        "structure": {"ibh": 25762.50, "ibl": 25564.75, "onh": 0, "onl": 0},
        "vwap": 25692.20, "vwap_up1": 25696.38, "vwap_dn1": 25683.81,
        "vwap_up2": 25700.58, "vwap_dn2": 25679.62, "vwap_weekly": 25549.20,
        "gex_1": 25400.00, "gex_2": 25800.00, "gex_3": 25700.00,
        "hvl": 25360.00, "gamma_wall_0dte": 25600.00,
        "call_resistance": 25600.00, "put_support": 25000.00,
        "blind_spot_4": 25692.25,
        "ext_lines": {"nearest_support": 25688.00, "nearest_resist": 25695.00},
        # Order flow HAUSSIER
        "bataille_navale": {
            "score": 0.08, "signal": 1,
            "edge_buy": 8, "edge_sell": 3,
            "absorb_ask": 3, "absorb_bid": 0,
            "color_up": 1200, "color_down": 800,
            "triple_ask": 200, "triple_bid": 100,
        },
        "deltaPct": 0.15,
        "cum_delta_day": 2500,
        "smart_money_flow": 0.20,
        "vwap_analysis": {"vwap_slope_10": 0.015, "vwap_slope_30": 0.010},
        "dom_features": {"imbalance_1_3": 0.25, "imbalance_6_10": 0.10},
    }

    # Snapshot avec signaux neutres
    snap_neutral = dict(snap_bullish)
    snap_neutral["bataille_navale"] = {
        "score": 0.001, "signal": 0, "edge_buy": 4, "edge_sell": 4,
        "absorb_ask": 0, "absorb_bid": 0, "color_up": 950, "color_down": 950,
        "triple_ask": 150, "triple_bid": 150,
    }
    snap_neutral["deltaPct"] = 0.01
    snap_neutral["cum_delta_day"] = 50
    snap_neutral["vwap_analysis"] = {"vwap_slope_10": 0.001}
    snap_neutral["dom_features"] = {"imbalance_1_3": 0.02}

    # Setup régime ROTATION
    regime = RegimeResult()
    regime.regime = Regime.ROTATION; regime.direction = 0; regime.confidence = 0.65
    regime.ib_high = 25762.50; regime.ib_low = 25564.75
    regime.ib_complete = True; regime.open_price = 25680.00

    zone_engine = ZoneEngine(tick_size=0.25, symbol="NQ")
    trigger_engine = TriggerEngine(tick_size=0.25, symbol="NQ")

    print("=" * 80)
    print("  TEST 1 : ROTATION + Prix au PVPOC + Order Flow HAUSSIER")
    print("=" * 80)
    zones = zone_engine.update(snap_bullish, regime)
    result = trigger_engine.evaluate(snap_bullish, zones, regime)
    print(f"\n  {result.summary()}")

    print(f"\n\n{'=' * 80}")
    print("  TEST 2 : ROTATION + Prix au PVPOC + Order Flow NEUTRE")
    print("=" * 80)
    zones2 = zone_engine.update(snap_neutral, regime)
    result2 = trigger_engine.evaluate(snap_neutral, zones2, regime)
    print(f"\n  {result2.summary()}")

    print(f"\n\n{'=' * 80}")
    print("  TEST 3 : TREND UP + Prix au PVPOC + Order Flow HAUSSIER")
    print("=" * 80)
    regime.regime = Regime.TREND; regime.direction = 1
    zones3 = zone_engine.update(snap_bullish, regime)
    result3 = trigger_engine.evaluate(snap_bullish, zones3, regime)
    print(f"\n  {result3.summary()}")

    print(f"\n\n{'=' * 80}")
    print("  TEST 4 : INCERTAIN + Prix au PVPOC + Order Flow HAUSSIER")
    print("  (Devrait être quasi impossible)")
    print("=" * 80)
    regime.regime = Regime.INCERTAIN; regime.direction = 0
    zones4 = zone_engine.update(snap_bullish, regime)
    result4 = trigger_engine.evaluate(snap_bullish, zones4, regime)
    print(f"\n  {result4.summary()}")

if __name__ == "__main__":
    demo()
