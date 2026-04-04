"""
MIA Trade Simulator — Valider avant de trader
Rôle : Lit une séquence de snapshots, simule le pipeline complet
       Régime → Zone → Trigger → Trade → SL/TP → Résultat
Auteur : MIA Trading System | Date : 2026-03-01
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from mia_regime import RegimeEngine, RegimeResult, Regime
from mia_zones import ZoneEngine, Zone, format_zones
from mia_trigger import TriggerEngine, TriggerResult, TriggerSignal
import json


# ═════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═════════════════════════════════════════════════════════════════════

# SL/TP par régime : (SL ratio ATR, TP ratio ATR, trailing activate ratio ATR, trailing distance ratio ATR)
# Exemple : SL=0.10 sur NQ ATR=350 → SL = 35 pts = 140 ticks
SLTP_CONFIG = {
    ("NQ", Regime.TREND):     (0.10, 0.00, 0.06, 0.04),   # TP=0 → trailing only
    ("NQ", Regime.ROTATION):  (0.08, 0.10, 0.07, 0.04),   # TP fixe
    ("NQ", Regime.REVERSAL):  (0.06, 0.12, 0.08, 0.03),   # SL serré, TP large
    ("NQ", Regime.BREAKOUT):  (0.07, 0.12, 0.06, 0.04),   # TP = extension
    ("NQ", Regime.INCERTAIN): (0.06, 0.07, 0.05, 0.03),   # Conservateur
    ("ES", Regime.TREND):     (0.10, 0.00, 0.06, 0.04),
    ("ES", Regime.ROTATION):  (0.08, 0.10, 0.07, 0.04),
    ("ES", Regime.REVERSAL):  (0.06, 0.12, 0.08, 0.03),
    ("ES", Regime.BREAKOUT):  (0.07, 0.12, 0.06, 0.04),
    ("ES", Regime.INCERTAIN): (0.06, 0.07, 0.05, 0.03),
}

# Cooldown après un trade (en snapshots, pas en secondes — dépend de la fréquence)
COOLDOWN_SNAPS = 30      # ~30 snapshots de cooldown entre trades
MAX_TRADES_PER_DAY = 6   # Max 6 trades par session
MIN_SESSION_PROGRESS = 0.02   # Pas de trade avant 2% de session (~7 min)
MAX_SESSION_PROGRESS = 0.90   # Pas de nouveau trade après 90% de session


# ═════════════════════════════════════════════════════════════════════
# STRUCTURES
# ═════════════════════════════════════════════════════════════════════

@dataclass
class SimTrade:
    """Un trade simulé."""
    entry_time_s: float      # Session elapsed en secondes
    entry_price: float
    direction: int           # +1=LONG, -1=SHORT
    regime: str              # Nom du régime
    zone_name: str           # Zone qui a déclenché
    zone_score: int          # Score de la zone
    trigger_signal: str      # WEAK/MODERATE/STRONG
    trigger_confs: int       # Nombre de confirmations
    sl_price: float
    tp_price: float          # 0 = trailing only
    trailing_active: float   # Prix d'activation trailing
    trailing_dist_ticks: float

    # Résultat
    exit_time_s: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""    # SL/TP/TRAILING/EOD
    pnl_ticks: float = 0.0
    pnl_pts: float = 0.0
    peak_favorable: float = 0.0   # Max excursion favorable en ticks
    peak_adverse: float = 0.0     # Max excursion adverse en ticks
    is_closed: bool = False


@dataclass
class SimSession:
    """Résultat d'une session simulée."""
    date: str = ""
    symbol: str = ""
    regime: str = ""
    regime_direction: str = ""
    num_trades: int = 0
    wins: int = 0
    losses: int = 0
    be: int = 0   # Breakeven
    total_pnl_ticks: float = 0.0
    total_pnl_pts: float = 0.0
    trades: List[SimTrade] = field(default_factory=list)

    @property
    def win_rate(self):
        return self.wins / self.num_trades * 100 if self.num_trades > 0 else 0

    @property
    def profit_factor(self):
        gross_profit = sum(t.pnl_ticks for t in self.trades if t.pnl_ticks > 0)
        gross_loss = abs(sum(t.pnl_ticks for t in self.trades if t.pnl_ticks < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')


# ═════════════════════════════════════════════════════════════════════
# SIMULATEUR
# ═════════════════════════════════════════════════════════════════════

class TradeSimulator:
    """
    Simule le pipeline complet MIA sur une séquence de snapshots.
    """

    def __init__(self, tick_size: float = 0.25, symbol: str = "NQ"):
        self.tick_size = tick_size
        self.symbol = symbol
        self.point_value = 20.0 if symbol == "NQ" else 50.0

        # Sous-moteurs
        self.regime_engine = RegimeEngine(tick_size=tick_size, symbol=symbol)
        self.zone_engine = ZoneEngine(tick_size=tick_size, symbol=symbol)
        self.trigger_engine = TriggerEngine(tick_size=tick_size, symbol=symbol)

        # État
        self.open_trade: Optional[SimTrade] = None
        self.trades: List[SimTrade] = []
        self.cooldown: int = 0
        self.trailing_stop: float = 0.0
        self.trailing_active: bool = False

    def run_session(self, snapshots: List[Dict], date: str = "sim") -> SimSession:
        """
        Simule une session complète.

        Args:
            snapshots: Liste de snapshots JSON ordonnés chronologiquement
            date: Identifiant de la session

        Returns:
            SimSession avec les résultats
        """
        # Reset
        self.regime_engine.reset_session()
        self.open_trade = None
        self.trades = []
        self.cooldown = 0
        self.trailing_stop = 0.0
        self.trailing_active = False

        session = SimSession(date=date, symbol=self.symbol)

        for snap in snapshots:
            mid = snap.get('mid', 0)
            if mid <= 0:
                continue

            elapsed = snap.get('session_elapsed_s', 0)
            progress = snap.get('session_progress', 0)

            # 1. Update régime
            regime = self.regime_engine.update(snap)

            # 2. Gérer le trade ouvert
            if self.open_trade and not self.open_trade.is_closed:
                self._manage_open_trade(mid, elapsed)

            # 3. Cooldown
            if self.cooldown > 0:
                self.cooldown -= 1
                continue

            # 4. Vérifier les gardes
            if self.open_trade and not self.open_trade.is_closed:
                continue  # Déjà en trade
            if len(self.trades) >= MAX_TRADES_PER_DAY:
                continue
            if progress < MIN_SESSION_PROGRESS:
                continue
            if progress > MAX_SESSION_PROGRESS:
                continue

            # 5. Chercher un nouveau trade
            zones = self.zone_engine.update(snap, regime)
            trigger = self.trigger_engine.evaluate(snap, zones, regime)

            if trigger.signal >= TriggerSignal.MODERATE and trigger.direction != 0:
                # GARDE : pas de trade en régime INCERTAIN
                if regime.regime == Regime.INCERTAIN:
                    continue
                self._open_trade(trigger, regime, mid, elapsed)

        # Fin de session — fermer le trade ouvert
        if self.open_trade and not self.open_trade.is_closed:
            last_mid = snapshots[-1].get('mid', 0) if snapshots else 0
            last_elapsed = snapshots[-1].get('session_elapsed_s', 0) if snapshots else 0
            self._close_trade(last_mid, last_elapsed, "EOD")

        # Compiler les résultats
        session.regime = regime.regime.name if regime else "?"
        dir_map = {1: "BULL", -1: "BEAR", 0: "NEUTRE"}
        session.regime_direction = dir_map.get(regime.direction, "?") if regime else "?"
        session.trades = self.trades
        session.num_trades = len(self.trades)
        session.wins = sum(1 for t in self.trades if t.pnl_ticks > 0)
        session.losses = sum(1 for t in self.trades if t.pnl_ticks < 0)
        session.be = sum(1 for t in self.trades if t.pnl_ticks == 0)
        session.total_pnl_ticks = sum(t.pnl_ticks for t in self.trades)
        session.total_pnl_pts = session.total_pnl_ticks * self.tick_size

        return session

    def _open_trade(self, trigger: TriggerResult, regime: RegimeResult,
                    price: float, elapsed: float):
        """Ouvre un nouveau trade avec SL/TP basé sur ATR."""
        d = trigger.direction
        r = regime.regime
        atr = self.regime_engine.atr if self.regime_engine.atr > 0 else 350  # fallback

        # SL/TP config (ratios d'ATR)
        cfg_key = (self.symbol, r)
        sl_ratio, tp_ratio, trail_act_ratio, trail_dist_ratio = SLTP_CONFIG.get(
            cfg_key, (0.08, 0.10, 0.06, 0.04)
        )

        sl_pts = atr * sl_ratio
        tp_pts = atr * tp_ratio if tp_ratio > 0 else 0
        trail_act_pts = atr * trail_act_ratio
        trail_dist_pts = atr * trail_dist_ratio

        sl_price = price - d * sl_pts
        tp_price = price + d * tp_pts if tp_pts > 0 else 0
        trail_act_price = price + d * trail_act_pts

        self.open_trade = SimTrade(
            entry_time_s=elapsed,
            entry_price=price,
            direction=d,
            regime=r.name,
            zone_name=trigger.zone.name if trigger.zone else "?",
            zone_score=trigger.zone.total_score if trigger.zone else 0,
            trigger_signal=trigger.signal.name,
            trigger_confs=trigger.confirmations,
            sl_price=sl_price,
            tp_price=tp_price,
            trailing_active=trail_act_price,
            trailing_dist_ticks=trail_dist_pts / self.tick_size,
        )
        self.trailing_active = False
        self.trailing_stop = 0.0

    def _manage_open_trade(self, price: float, elapsed: float):
        """Gère SL/TP/Trailing d'un trade ouvert."""
        t = self.open_trade
        d = t.direction

        # Excursions
        favorable = (price - t.entry_price) / self.tick_size * d
        adverse = -favorable
        t.peak_favorable = max(t.peak_favorable, favorable)
        t.peak_adverse = max(t.peak_adverse, max(0, adverse))

        # SL hit ?
        if d > 0 and price <= t.sl_price:
            self._close_trade(t.sl_price, elapsed, "SL")
            return
        if d < 0 and price >= t.sl_price:
            self._close_trade(t.sl_price, elapsed, "SL")
            return

        # TP hit ? (si TP > 0)
        if t.tp_price > 0:
            if d > 0 and price >= t.tp_price:
                self._close_trade(t.tp_price, elapsed, "TP")
                return
            if d < 0 and price <= t.tp_price:
                self._close_trade(t.tp_price, elapsed, "TP")
                return

        # Trailing stop
        if not self.trailing_active:
            if d > 0 and price >= t.trailing_active:
                self.trailing_active = True
                self.trailing_stop = price - t.trailing_dist_ticks * self.tick_size
            elif d < 0 and price <= t.trailing_active:
                self.trailing_active = True
                self.trailing_stop = price + t.trailing_dist_ticks * self.tick_size
        else:
            # Update trailing
            if d > 0:
                new_trail = price - t.trailing_dist_ticks * self.tick_size
                self.trailing_stop = max(self.trailing_stop, new_trail)
                if price <= self.trailing_stop:
                    self._close_trade(self.trailing_stop, elapsed, "TRAILING")
                    return
            else:
                new_trail = price + t.trailing_dist_ticks * self.tick_size
                self.trailing_stop = min(self.trailing_stop, new_trail)
                if price >= self.trailing_stop:
                    self._close_trade(self.trailing_stop, elapsed, "TRAILING")
                    return

    def _close_trade(self, price: float, elapsed: float, reason: str):
        """Ferme le trade ouvert."""
        t = self.open_trade
        t.exit_price = price
        t.exit_time_s = elapsed
        t.exit_reason = reason
        t.pnl_ticks = (price - t.entry_price) / self.tick_size * t.direction
        t.pnl_pts = t.pnl_ticks * self.tick_size
        t.is_closed = True
        self.trades.append(t)
        self.open_trade = None
        self.cooldown = COOLDOWN_SNAPS


# ═════════════════════════════════════════════════════════════════════
# FORMATAGE
# ═════════════════════════════════════════════════════════════════════

def format_session(s: SimSession) -> str:
    lines = [
        f"\n{'=' * 80}",
        f"  SESSION : {s.date} | {s.symbol} | Régime: {s.regime} {s.regime_direction}",
        f"{'=' * 80}",
        f"  Trades: {s.num_trades} | W:{s.wins} L:{s.losses} BE:{s.be} "
        f"| WR: {s.win_rate:.0f}% | PF: {s.profit_factor:.2f}",
        f"  PnL: {s.total_pnl_ticks:+.0f} ticks ({s.total_pnl_pts:+.2f} pts "
        f"= ${s.total_pnl_pts * (20 if s.symbol == 'NQ' else 50):+.0f})",
        f"{'─' * 80}",
    ]

    for i, t in enumerate(s.trades, 1):
        d = "LONG" if t.direction > 0 else "SHORT"
        emoji = "+" if t.pnl_ticks > 0 else "-" if t.pnl_ticks < 0 else "="
        lines.append(
            f"  {emoji} Trade {i}: {d} @ {t.entry_price:.2f} → {t.exit_price:.2f} "
            f"({t.exit_reason}) | {t.pnl_ticks:+.0f}t "
            f"| Zone: {t.zone_name} (s{t.zone_score}) "
            f"| {t.trigger_signal}({t.trigger_confs}conf) "
            f"| MFE:{t.peak_favorable:.0f}t MAE:{t.peak_adverse:.0f}t"
        )

    lines.append(f"{'=' * 80}")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════════════

def generate_fake_session(scenario="trend_up"):
    """Génère une fausse session pour tester le simulateur."""
    snaps = []
    base_price = 25690.00
    tick = 0.25

    # PV levels constants
    pv = {"vah": 25971.75, "val": 25548.00, "vpoc": 25690.00}
    struct_base = {"ibh": 0, "ibl": 0, "onh": 0, "onl": 0}

    if scenario == "trend_up":
        # Prix monte régulièrement avec des pullbacks
        prices = [
            # 0-30 min : open + montée initiale
            25690, 25695, 25700, 25705, 25710, 25715, 25720, 25725, 25730, 25735,
            # 30-60 min : IB formation
            25740, 25738, 25742, 25745, 25748, 25750, 25747, 25752, 25755, 25758,
            # 60-90 min : pullback vers PVPOC
            25755, 25750, 25745, 25740, 25735, 25730, 25725, 25720, 25715, 25710,
            # 90-120 min : rebond et continuation
            25700, 25695, 25692, 25690, 25693, 25698, 25705, 25712, 25720, 25728,
            # 120-180 min : breakout IB
            25735, 25742, 25750, 25758, 25765, 25770, 25775, 25780, 25785, 25790,
            25795, 25790, 25792, 25795, 25800, 25805, 25810, 25808, 25812, 25815,
        ]
    elif scenario == "rotation":
        # Prix oscille entre PVAL et PVAH
        prices = [
            25690, 25695, 25700, 25695, 25690, 25685, 25680, 25685, 25690, 25695,
            25700, 25705, 25710, 25715, 25720, 25715, 25710, 25705, 25700, 25695,
            25690, 25685, 25680, 25675, 25670, 25675, 25680, 25685, 25690, 25695,
            25700, 25705, 25710, 25715, 25720, 25725, 25720, 25715, 25710, 25705,
            25700, 25695, 25690, 25685, 25680, 25685, 25690, 25695, 25700, 25705,
            25700, 25695, 25690, 25688, 25690, 25695, 25698, 25700, 25695, 25690,
        ]
    else:
        prices = [base_price + i * tick for i in range(60)]

    session_duration = 23400  # 6h30 RTH
    dt = session_duration / len(prices)

    for i, p in enumerate(prices):
        elapsed = dt * i
        progress = elapsed / session_duration

        # BN score suit la tendance
        if scenario == "trend_up" and i > 25:
            bn_score = 0.06 + (i/len(prices)) * 0.04
            delta_pct = 0.10 + (i/len(prices)) * 0.10
            cvd = 500 + i * 80
        elif scenario == "rotation":
            # Alterne selon la position dans le range
            if p > 25700:
                bn_score = -0.04; delta_pct = -0.08; cvd = -200
            elif p < 25685:
                bn_score = 0.05; delta_pct = 0.10; cvd = 300
            else:
                bn_score = 0.01; delta_pct = 0.02; cvd = 50
        else:
            bn_score = 0.02; delta_pct = 0.05; cvd = 200

        # IB update
        struct = dict(struct_base)
        if i > 0:
            struct["ibh"] = max(prices[:min(i+1, 20)])  # IB = 20 premiers snaps
            struct["ibl"] = min(prices[:min(i+1, 20)])

        snap = {
            "mid": p, "high": p + 1.5, "low": p - 1.5,
            "vix": 16.0, "atr": 371.05,
            "session_elapsed_s": elapsed, "session_progress": progress,
            "pvwap": 25723.77,
            "vva": pv,
            "structure": struct,
            "vwap": 25692.20 + (i * 0.5 if scenario == "trend_up" else 0),
            "vwap_up1": 25696.38, "vwap_dn1": 25683.81,
            "vwap_up2": 25700.58, "vwap_dn2": 25679.62,
            "vwap_weekly": 25549.20,
            "gex_3": 25700.00, "hvl": 25360.00, "gamma_wall_0dte": 25600.00,
            "blind_spot_4": 25692.25,
            "ext_lines": {"nearest_support": p - 5, "nearest_resist": p + 5},
            "bataille_navale": {
                "score": bn_score, "signal": 1 if bn_score > 0.03 else 0,
                "edge_buy": 6 if bn_score > 0 else 3,
                "edge_sell": 3 if bn_score > 0 else 6,
                "absorb_ask": 3 if delta_pct > 0.08 else 0,
                "absorb_bid": 3 if delta_pct < -0.08 else 0,
                "color_up": 1000, "color_down": 900,
            },
            "deltaPct": delta_pct,
            "cum_delta_day": cvd,
            "smart_money_flow": delta_pct,
            "vwap_analysis": {
                "vwap_slope_10": 0.012 if scenario == "trend_up" else 0.002
            },
            "dom_features": {
                "imbalance_1_3": 0.20 if delta_pct > 0.05 else -0.10
            },
        }
        snaps.append(snap)

    return snaps


def demo():
    print("=" * 80)
    print("  MIA TRADE SIMULATOR — TEST SUR DONNÉES SIMULÉES")
    print("=" * 80)

    sim = TradeSimulator(tick_size=0.25, symbol="NQ")

    # Test Trend Up
    snaps_trend = generate_fake_session("trend_up")
    session1 = sim.run_session(snaps_trend, "2026-03-01_TREND")
    print(format_session(session1))

    # Test Rotation
    sim2 = TradeSimulator(tick_size=0.25, symbol="NQ")
    snaps_rot = generate_fake_session("rotation")
    session2 = sim2.run_session(snaps_rot, "2026-03-01_ROTATION")
    print(format_session(session2))

    # Résumé global
    print(f"\n{'=' * 80}")
    print(f"  RÉSUMÉ GLOBAL")
    print(f"{'=' * 80}")
    all_trades = session1.trades + session2.trades
    total = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl_ticks > 0)
    pnl = sum(t.pnl_ticks for t in all_trades)
    print(f"  Total trades : {total}")
    print(f"  Win Rate     : {wins/total*100:.0f}%" if total > 0 else "  No trades")
    print(f"  PnL total    : {pnl:+.0f} ticks ({pnl*0.25:+.2f} pts)")
    print(f"  PnL $        : ${pnl*0.25*20:+.0f}")


if __name__ == "__main__":
    demo()
