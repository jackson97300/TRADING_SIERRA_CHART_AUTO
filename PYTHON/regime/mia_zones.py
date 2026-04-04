"""
MIA Zone Engine — Où attendre le prix
Rôle : Identifier les 6-8 niveaux de trading actifs avec scoring et confluence.
Auteur : MIA Trading System | Date : 2026-03-01
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, List, Dict, Any, Tuple
from mia_regime import RegimeResult, Regime, OpenType, OpenZone

# ═════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═════════════════════════════════════════════════════════════════════
CONFLUENCE_TICKS = 5
CONFLUENCE_TICKS_WIDE = 10
ZONE_ACTIVE_TICKS_NQ = 150
ZONE_ACTIVE_TICKS_ES = 80
ZONE_PROXIMITY_TICKS = 10
MAX_ZONES = 8
MIN_SCORE_ACTIVE = 3
MIN_SCORE_HIGH_CONVICTION = 5

class ZoneSource(IntEnum):
    PV_VPOC=1; PV_VAH=2; PV_VAL=3; PV_VWAP=4; PV_SD1=5; PV_SD2=6
    IB_HIGH=10; IB_LOW=11
    SESS_VPOC=15; SESS_VAH=16; SESS_VAL=17
    VWAP_DAY=20; VWAP_SD1U=21; VWAP_SD1D=22; VWAP_SD2U=23; VWAP_SD2D=24; VWAP_WEEKLY=25
    VWAP_WEEKLY_SD=26; VWAP_MONTHLY=27
    MQ_GEX=30; MQ_HVL=31; MQ_GAMMA=32; MQ_CALL=33; MQ_PUT=34; MQ_BLIND=35; MQ_WALL=36
    OPEN_PRICE=40; SWING_HIGH=50; SWING_LOW=51
    PREV_DAY_HIGH=60; PREV_DAY_LOW=61; OVERNIGHT_HIGH=62; OVERNIGHT_LOW=63

@dataclass
class Zone:
    name: str; price: float; source: ZoneSource; base_score: int
    confluence_bonus: int; total_score: int; distance_ticks: float; abs_distance: float
    direction: int; confluence_with: str; is_active: bool; is_proximate: bool

    @property
    def is_high_conviction(self): return self.total_score >= MIN_SCORE_HIGH_CONVICTION

    def __repr__(self):
        d = "SUP" if self.direction > 0 else "RES" if self.direction < 0 else "S/R"
        hc = " *" if self.is_high_conviction else ""
        prox = " <<" if self.is_proximate else ""
        c = f" [{self.confluence_with}]" if self.confluence_with else ""
        return (f"{self.name:<22} {self.price:>10.2f} {self.distance_ticks:>+8.0f}t "
                f"score={self.total_score}({self.base_score}+{self.confluence_bonus}) "
                f"{d}{c}{hc}{prox}")

class ZoneEngine:
    def __init__(self, tick_size=0.25, symbol="NQ"):
        self.tick_size = tick_size
        self.symbol = symbol
        self.max_dist = ZONE_ACTIVE_TICKS_NQ if symbol == "NQ" else ZONE_ACTIVE_TICKS_ES

    def update(self, snap: Dict[str, Any], regime: RegimeResult) -> List[Zone]:
        mid = snap.get('mid', 0)
        if mid <= 0: return []
        raw = self._extract_levels(snap, regime)
        zones = []
        for name, price, source, base in raw:
            if price <= 0: continue
            dist = (price - mid) / self.tick_size
            ad = abs(dist)
            direction = -1 if dist > 2 else (1 if dist < -2 else 0)
            zones.append(Zone(name=name, price=price, source=source, base_score=base,
                confluence_bonus=0, total_score=base, distance_ticks=dist, abs_distance=ad,
                direction=direction, confluence_with="", is_active=ad <= self.max_dist,
                is_proximate=ad <= ZONE_PROXIMITY_TICKS))
        zones = self._confluence(zones)
        zones = self._filter_regime(zones, regime)
        zones.sort(key=lambda z: (-z.total_score, z.abs_distance))
        return zones[:MAX_ZONES]

    def _extract_levels(self, snap, regime):
        levels = []
        vva = snap.get('vva', {}); struct = snap.get('structure', {})
        # PV Levels
        for k, n, src, sc in [
            ('vpoc','PVPOC',ZoneSource.PV_VPOC,4), ('vah','PVAH',ZoneSource.PV_VAH,3),
            ('val','PVAL',ZoneSource.PV_VAL,3)]:
            v = vva.get(k, 0)
            if v > 0: levels.append((n, v, src, sc))
        pvwap = snap.get('pvwap', 0)
        if pvwap > 0: levels.append(("PVWAP", pvwap, ZoneSource.PV_VWAP, 2))
        for k, n, src in [('pvwap_up1','PVWAP+1SD',ZoneSource.PV_SD1),
            ('pvwap_dn1','PVWAP-1SD',ZoneSource.PV_SD1),
            ('pvwap_up2','PVWAP+2SD',ZoneSource.PV_SD2),
            ('pvwap_dn2','PVWAP-2SD',ZoneSource.PV_SD2)]:
            v = snap.get(k, 0)
            if v > 0: levels.append((n, v, src, 1))
        # IB
        ibh = regime.ib_high if regime.ib_high > 0 else struct.get('ibh', 0)
        ibl = regime.ib_low if regime.ib_low > 0 else struct.get('ibl', 0)
        if ibh > 0: levels.append(("IB_HIGH", ibh, ZoneSource.IB_HIGH, 3))
        if ibl > 0 and ibl < 1e9: levels.append(("IB_LOW", ibl, ZoneSource.IB_LOW, 3))
        # VWAP Day + SD
        vwap = snap.get('vwap', 0)
        if vwap > 0: levels.append(("VWAP_D", vwap, ZoneSource.VWAP_DAY, 2))
        for k, n, src in [('vwap_up1','VWAP+1SD',ZoneSource.VWAP_SD1U),
            ('vwap_dn1','VWAP-1SD',ZoneSource.VWAP_SD1D),
            ('vwap_up2','VWAP+2SD',ZoneSource.VWAP_SD2U),
            ('vwap_dn2','VWAP-2SD',ZoneSource.VWAP_SD2D)]:
            v = snap.get(k, 0)
            if v > 0: levels.append((n, v, src, 2))
        vwap_w = snap.get('vwap_weekly', 0)
        if vwap_w > 0: levels.append(("VWAP_W", vwap_w, ZoneSource.VWAP_WEEKLY, 2))
        # VWAP Weekly SD bands
        vw_up1 = snap.get('vwap_weekly_up1', 0)
        vw_dn1 = snap.get('vwap_weekly_dn1', 0)
        if vw_up1 > 0: levels.append(("VWAP_W+1SD", vw_up1, ZoneSource.VWAP_WEEKLY_SD, 1))
        if vw_dn1 > 0: levels.append(("VWAP_W-1SD", vw_dn1, ZoneSource.VWAP_WEEKLY_SD, 1))
        # VWAP Monthly (HTF majeur)
        vwap_m = snap.get('vwap_monthly', 0)
        if vwap_m > 0: levels.append(("VWAP_M", vwap_m, ZoneSource.VWAP_MONTHLY, 3))
        # Open
        if regime.open_price > 0: levels.append(("OPEN", regime.open_price, ZoneSource.OPEN_PRICE, 1))
        # MenthorQ
        for i in range(1, 11):
            g = snap.get(f'gex_{i}', 0)
            if g > 0: levels.append((f"GEX_{i}", g, ZoneSource.MQ_GEX, 2 if i <= 3 else 1))
        for k, n, src in [('hvl','HVL',ZoneSource.MQ_HVL),
            ('gamma_wall_0dte','GAMMA',ZoneSource.MQ_GAMMA)]:
            v = snap.get(k, 0)
            if v > 0: levels.append((n, v, src, 2))
        # HVL 0DTE (distinct du HVL standard)
        hvl0 = snap.get('hvl_0dte', 0)
        hvl_std = snap.get('hvl', 0)
        if hvl0 > 0 and abs(hvl0 - hvl_std) > self.tick_size * 5:
            levels.append(("HVL_0DTE", hvl0, ZoneSource.MQ_HVL, 2))
        for k, n in [('call_resistance','CALL'),('put_support','PUT'),
            ('call_resistance_0dte','CALL_0DTE'),('put_support_0dte','PUT_0DTE')]:
            v = snap.get(k, 0)
            if v > 0: levels.append((n, v, ZoneSource.MQ_CALL if 'call' in k else ZoneSource.MQ_PUT, 1))
        # Blind Spots (3 plus proches)
        mid = snap.get('mid', 0)
        blinds = []
        for i in range(9):
            bs = snap.get(f'blind_spot_{i}', 0)
            if bs > 0 and mid > 0: blinds.append((abs(bs-mid), bs, i))
        blinds.sort()
        for _, bp, bi in blinds[:3]:
            levels.append((f"BLIND_{bi}", bp, ZoneSource.MQ_BLIND, 1))
        # Extension Lines
        ext = snap.get('ext_lines', {})
        es = ext.get('nearest_support', 0); er = ext.get('nearest_resist', 0)
        if es > 0: levels.append(("EXT_SUP", es, ZoneSource.SWING_LOW, 1))
        if er > 0: levels.append(("EXT_RES", er, ZoneSource.SWING_HIGH, 1))
        # Next Wall MenthorQ (mur le plus proche avec force)
        nw = snap.get('next_wall', {})
        nw_price = nw.get('price', 0); nw_str = nw.get('strength', 0)
        if nw_price > 0 and nw_str > 0.2:
            nw_name = f"WALL_{nw.get('side','?').upper()}"
            nw_score = 3 if nw_str > 0.5 else 2
            levels.append((nw_name, nw_price, ZoneSource.MQ_WALL, nw_score))
        # Previous Day Range (1d_max/min)
        pd_high = snap.get('1d_max', 0); pd_low = snap.get('1d_min', 0)
        if pd_high > 0: levels.append(("PDH", pd_high, ZoneSource.PREV_DAY_HIGH, 2))
        if pd_low > 0: levels.append(("PDL", pd_low, ZoneSource.PREV_DAY_LOW, 2))
        # Overnight High/Low
        onh = struct.get('onh', 0); onl = struct.get('onl', 0)
        if onh > 0 and onl > 0 and abs(onh - onl) > self.tick_size * 4:
            levels.append(("ONH", onh, ZoneSource.OVERNIGHT_HIGH, 1))
            levels.append(("ONL", onl, ZoneSource.OVERNIGHT_LOW, 1))
        return levels

    def _confluence(self, zones):
        mq_src = {ZoneSource.MQ_GEX, ZoneSource.MQ_HVL, ZoneSource.MQ_GAMMA,
                  ZoneSource.MQ_CALL, ZoneSource.MQ_PUT, ZoneSource.MQ_BLIND, ZoneSource.MQ_WALL}
        structural = [z for z in zones if z.source not in mq_src]
        menthorq = [z for z in zones if z.source in mq_src]
        for sz in structural:
            best_b, best_n = 0, ""
            for mz in menthorq:
                d = abs(sz.price - mz.price) / self.tick_size
                if d <= CONFLUENCE_TICKS and 2 > best_b: best_b, best_n = 2, mz.name
                elif d <= CONFLUENCE_TICKS_WIDE and 1 > best_b: best_b, best_n = 1, mz.name
            if best_b > 0:
                sz.confluence_bonus = best_b
                sz.total_score = sz.base_score + best_b
                sz.confluence_with = best_n
                sz.name = f"{sz.name}+{best_n}"
        return zones

    def _filter_regime(self, zones, regime):
        r, d = regime.regime, regime.direction
        filtered = []
        for z in zones:
            if z.is_proximate and z.total_score >= MIN_SCORE_ACTIVE: filtered.append(z); continue
            if z.is_proximate and z.total_score < MIN_SCORE_ACTIVE: continue  # Proximate mais trop faible
            # IB toujours visible si formé (structure fondamentale)
            if z.source in (ZoneSource.IB_HIGH, ZoneSource.IB_LOW) and regime.ib_complete:
                z.is_active = True
            if not z.is_active: continue
            if z.total_score < MIN_SCORE_ACTIVE: continue
            if r == Regime.TREND:
                if d > 0 and z.direction >= 0: filtered.append(z)
                elif d < 0 and z.direction <= 0: filtered.append(z)
                elif z.total_score >= MIN_SCORE_HIGH_CONVICTION: filtered.append(z)
                elif d == 0: filtered.append(z)
            elif r == Regime.ROTATION: filtered.append(z)
            elif r == Regime.REVERSAL: filtered.append(z)
            elif r == Regime.BREAKOUT:
                if z.source in (ZoneSource.IB_HIGH, ZoneSource.IB_LOW):
                    z.base_score += 1; z.total_score += 1
                filtered.append(z)
            else:
                if z.total_score >= MIN_SCORE_HIGH_CONVICTION: filtered.append(z)
        return self._dedup(filtered)

    def _dedup(self, zones, threshold=3.0):
        if not zones: return zones
        sz = sorted(zones, key=lambda z: z.price)
        result = [sz[0]]
        for z in sz[1:]:
            prev = result[-1]
            if abs(z.price - prev.price) / self.tick_size < threshold:
                if z.total_score > prev.total_score:
                    z.name = f"{z.name}~{prev.name}"; result[-1] = z
                else: prev.name = f"{prev.name}~{z.name}"
            else: result.append(z)
        return result

def format_zones(zones, title="ZONES ACTIVES"):
    lines = [f"\n{'='*80}", f"  {title} ({len(zones)} zones)", f"{'='*80}",
             f"  {'Niveau':<22} {'Prix':>10} {'Dist':>8} {'Score':>15} Type", f"  {'~'*75}"]
    for z in zones: lines.append(f"  {z}")
    hc = sum(1 for z in zones if z.is_high_conviction)
    px = sum(1 for z in zones if z.is_proximate)
    lines.append(f"  {'~'*75}")
    lines.append(f"  Haute conviction: {hc} | Proximité immédiate: {px}")
    return "\n".join(lines)

def demo():
    from mia_regime import RegimeEngine
    snap = {
        "mid": 25677.88, "high": 25680.50, "low": 25677.25,
        "vix": 15.87, "atr": 371.05, "session_elapsed_s": 4000,
        "pvwap": 25723.77, "pvwap_up1": 25758.66, "pvwap_dn1": 25688.88,
        "pvwap_up2": 25793.55, "pvwap_dn2": 25654.00,
        "vva": {"vah": 25971.75, "val": 25548.00, "vpoc": 25690.00},
        "structure": {"onh": 25435.50, "onl": 25435.00, "ibh": 25762.50, "ibl": 25564.75},
        "vwap": 25692.20, "vwap_up1": 25696.38, "vwap_dn1": 25683.81,
        "vwap_up2": 25700.58, "vwap_dn2": 25679.62, "vwap_weekly": 25549.20,
        "gex_1": 25400.00, "gex_2": 25800.00, "gex_3": 25700.00,
        "gex_4": 25900.00, "gex_5": 25750.00, "gex_6": 26200.00, "gex_7": 26100.00,
        "gex_8": 25200.00, "gex_9": 25100.00, "gex_10": 25370.00,
        "hvl": 25360.00, "gamma_wall_0dte": 25600.00,
        "call_resistance": 25600.00, "put_support": 25000.00,
        "call_resistance_0dte": 25600.00, "put_support_0dte": 25850.00,
        "blind_spot_0": 26005.79, "blind_spot_1": 25215.45, "blind_spot_2": 25754.46,
        "blind_spot_3": 25423.49, "blind_spot_4": 25692.25, "blind_spot_5": 25311.51,
        "blind_spot_6": 25364.74, "blind_spot_7": 25402.18, "blind_spot_8": 25596.66,
        "ext_lines": {"nearest_support": 25680.00, "nearest_resist": 25678.75},
    }

    # Test ROTATION
    regime = RegimeResult()
    regime.regime = Regime.ROTATION; regime.direction = 0; regime.confidence = 0.65
    regime.open_zone = OpenZone.POC_VAL; regime.open_type = OpenType.OAIR
    regime.ib_high = 25762.50; regime.ib_low = 25564.75
    regime.ib_complete = True; regime.open_price = 25677.88

    engine = ZoneEngine(tick_size=0.25, symbol="NQ")
    zones = engine.update(snap, regime)
    print(format_zones(zones, "ROTATION — Fader les extremes, TP=POC"))

    # Test TREND UP
    regime.regime = Regime.TREND; regime.direction = 1; regime.open_type = OpenType.OD_UP
    zones2 = engine.update(snap, regime)
    print(format_zones(zones2, "TREND UP — Supports pour pullback"))

    # Test BREAKOUT
    regime.regime = Regime.BREAKOUT; regime.direction = 0; regime.open_type = OpenType.OAIR
    zones3 = engine.update(snap, regime)
    print(format_zones(zones3, "BREAKOUT — IB levels prioritaires"))

if __name__ == "__main__":
    demo()
