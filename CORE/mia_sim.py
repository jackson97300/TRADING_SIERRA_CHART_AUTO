"""
mia_sim.py — Simulateur de Backtest Complet
============================================

Regroupe TOUTES les conditions d'entrée et simule des trades réels:
  Couche 1: Filtre session (phase 🟢 uniquement)
  Couche 2: Biais contextuel (7 CORE features)
  Couche 3: Zone de réaction (niveau + biais aligné)
  Couche 4: SL/TP (mur Tier 1/2 + 3 micros)

Simule barre par barre:
  - 3 MNQ par trade (TP1 + Trailing + Runner)
  - Cooldown entre trades (3 min win, 5 min loss)
  - Daily loss limit ($500)
  - Max trades par jour (8)
  - Filtre horaire (phases 🟢 seulement)

Schema 3.6.0 — 250 colonnes
Intègre: Edge Zones (dist_ext_edge_buy/sell), COLOR_2 (continuation),
         Retest tracking, BN score composite avec bonus COLOR_2,
         RVOL absorption (rvol_absorb_buy/sell), Extension LONG (dist_ext_long),
         Double Top/Bottom (mia_double_top.py confirmation booster)

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_sim.py

Auteur : MIA Trading System
Date   : 2026-03-13
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from dmp_reader import DmpReader
from ib_recalc import IBRecalc
from rolling_features import RollingFeatures
from intermarket_features import IntermarketFeatures
from mia_entry import EntryEngine
from mia_sltp import SLTPEngine
from mia_menthorq_reader import MenthorQReader

# 🆕 Double Top/Bottom confluence
try:
    from mia_double_top import detect_double_top_bottom, RetestResult
    HAS_DOUBLE_TOP = True
except ImportError:
    HAS_DOUBLE_TOP = False


# ═════════════════════════════════════════════════════════════════════
# CONFIG SIMULATION
# ═════════════════════════════════════════════════════════════════════

@dataclass
class SimConfig:
    """Configuration du simulateur."""
    symbol: str = "NQ"
    tick_size: float = 0.25
    tick_value_micro: float = 0.50   # $0.50/tick pour MNQ ($0.125 MES)
    n_micros: int = 3                # 3 micro-contrats

    # Cooldown (en barres, ~1 barre = 1 min)
    cooldown_win: int = 3            # 3 barres après win
    cooldown_loss: int = 5           # 5 barres après loss

    # Limites journalières
    daily_loss_limit: float = -500.0  # Stop trading si PnL jour < -$500
    max_trades_per_day: int = 16      # 🆕 16 global (8 NQ + 8 ES)
    max_trades_per_session: int = 5   # 🆕 Max 5 trades par session (London/US/etc)

    # Filtre momentum court terme
    # FIX 07/03: ne pas entrer contre un move > 5 pts en 3 barres
    momentum_filter_pts: float = 5.0  # Seuil en points
    momentum_bars: int = 3            # Lookback en barres

    # Phases autorisées (du Test 12 + Test 15 + SIM 13/03)
    # 🟢 Open_30m (score 2.2), IB_Form (1.8)
    # 🔴 Pre_Open = 29% WR en sim, -$177 → EXCLU
    allowed_phases: List[str] = field(default_factory=lambda: [
        'London', 'Open_30m', 'IB_Form',
        'Mid_AM', 'Afternoon', 'Power_Hr'
    ])
    # Asia exclu (r=0.02) | Asia_Late exclu (r=0.14, score 0.4)

    # Trailing (micro #2)
    trailing_start_ticks: int = 20   # Activer après +20t
    trailing_dist_ticks: int = 12    # Suivre à 12t

    @staticmethod
    def for_es() -> 'SimConfig':
        """Config adaptée ES (MES micro)."""
        cfg = SimConfig(
            symbol="ES",
            tick_size=0.25,
            tick_value_micro=0.125,     # $0.125/tick MES (vs $0.50 MNQ)
            n_micros=3,
            max_trades_per_day=16,
            max_trades_per_session=5,
            momentum_filter_pts=1.5,    # ES bouge ~4x moins que NQ
            allowed_phases=[
                'London', 'Open_30m', 'IB_Form',
                'Mid_AM', 'Afternoon', 'Power_Hr'
            ],
            trailing_start_ticks=8,     # ES = ticks plus petits en valeur
            trailing_dist_ticks=5,
        )
        return cfg

    @staticmethod
    def for_nq() -> 'SimConfig':
        """Config NQ (MNQ micro) — défaut."""
        return SimConfig()


# ═════════════════════════════════════════════════════════════════════
# STRUCTURES
# ═════════════════════════════════════════════════════════════════════

@dataclass
class MicroPosition:
    """État d'un micro-contrat."""
    active: bool = False
    entry_ticks: float = 0.0  # Prix d'entrée en ticks depuis 0
    sl_ticks: float = 0.0     # Distance SL
    tp_ticks: float = 0.0     # Distance TP (0 = trailing only)
    trailing: bool = False     # Mode trailing activé?
    trail_high: float = 0.0   # MFE pour le trailing
    exit_ticks: float = 0.0   # PnL en ticks à la sortie
    exit_reason: str = ""


@dataclass
class SimTrade:
    """Un trade complet (3 micros)."""
    bar_entry: int = 0
    bar_exit: int = 0
    direction: int = 0         # +1 LONG, -1 SHORT
    entry_price: float = 0.0
    phase: str = ""
    session: str = ""          # 🆕 Session ID (Asia/London/US)
    zone: str = ""
    sl_wall: str = ""
    sl_ticks: float = 0.0
    confidence: float = 0.0
    bias: float = 0.0

    # Résultat par micro
    m1_pnl_ticks: float = 0.0
    m1_exit: str = ""
    m2_pnl_ticks: float = 0.0
    m2_exit: str = ""
    m3_pnl_ticks: float = 0.0
    m3_exit: str = ""

    # Total
    total_pnl_ticks: float = 0.0
    total_pnl_usd: float = 0.0


@dataclass
class DayResult:
    """Résultat d'une journée."""
    date: str = ""
    symbol: str = ""
    n_bars: int = 0
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    total_pnl_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    trades: List[SimTrade] = field(default_factory=list)

    @property
    def win_rate(self):
        return self.n_wins / self.n_trades * 100 if self.n_trades > 0 else 0

    @property
    def profit_factor(self):
        gross_win = sum(t.total_pnl_usd for t in self.trades if t.total_pnl_usd > 0)
        gross_loss = abs(sum(t.total_pnl_usd for t in self.trades if t.total_pnl_usd < 0))
        return gross_win / gross_loss if gross_loss > 0 else float('inf')

    @property
    def avg_trade(self):
        return self.total_pnl_usd / self.n_trades if self.n_trades > 0 else 0


# ═════════════════════════════════════════════════════════════════════
# PHASES (copie de mia_bench Test 12)
# ═════════════════════════════════════════════════════════════════════

def get_phase(h: int, m: int) -> str:
    if h >= 18 or h < 2:    return 'Asia'
    if 2 <= h < 4:           return 'Asia_Late'
    if 4 <= h < 8:           return 'London'
    if 8 <= h < 9:           return 'Pre_Mkt'
    if h == 9 and m < 30:    return 'Pre_Open'
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return 'Open_30m'
    if (h == 10 and m >= 30) or (h == 11 and m < 30): return 'IB_Form'
    if 11 <= h < 13:         return 'Mid_AM'
    if 13 <= h < 15:         return 'Afternoon'
    if 15 <= h < 16:         return 'Power_Hr'
    return 'Other'


# ═════════════════════════════════════════════════════════════════════
# SIMULATEUR
# ═════════════════════════════════════════════════════════════════════

class TradeSimulator:
    """
    Simule le pipeline complet barre par barre.

    Usage:
        sim = TradeSimulator()
        result = sim.run("20260305", nq_raw, es_raw)
        sim.report([result])
    """

    def __init__(self, config: SimConfig = None):
        self.cfg = config or SimConfig()
        self.rf = RollingFeatures()
        self.im = IntermarketFeatures()
        self.entry = EntryEngine()
        self.sltp = SLTPEngine(symbol=self.cfg.symbol)

    # ─── RUN UNE JOURNÉE ──────────────────────────────────────────

    def run(self, date: str, nq_raw: pd.DataFrame, es_raw: pd.DataFrame
            ) -> DayResult:
        """
        Simule une journée complète.

        Args:
            date: "20260305"
            nq_raw: DataFrame brut DmpReader pour NQ
            es_raw: DataFrame brut DmpReader pour ES
        """
        result = DayResult(date=date, symbol=self.cfg.symbol)

        # Pipeline: features → intermarket → menthorq → entry → sltp
        target = self.cfg.symbol
        if target == "NQ":
            df_target = self.rf.compute(nq_raw)
            df_other = self.rf.compute(es_raw)
            df = self.im.compute(df_target, df_other, target="NQ")
        else:
            df_target = self.rf.compute(es_raw)
            df_other = self.rf.compute(nq_raw)
            df = self.im.compute(df_target, df_other, target="ES")

        # Enrichir avec MenthorQ (optionnel — ne bloque pas si absent)
        try:
            mq = MenthorQReader("DATA/MENTHORQ")
            df = mq.enrich(df, date, target, tick_size=0.25)
        except Exception:
            pass

        df = df.reset_index(drop=True)
        df = self.entry.compute(df)
        df = self.sltp.compute(df)

        # Ajouter phase
        df['phase'] = [get_phase(h, m) for h, m in
                       zip(df['datetime_et'].dt.hour, df['datetime_et'].dt.minute)]

        result.n_bars = len(df)

        # 🆕 Préparer list[dict] pour mia_double_top
        bars_list = df.to_dict('records') if HAS_DOUBLE_TOP else None

        # ── Simulation barre par barre ──
        cooldown = 0
        day_pnl = 0.0
        day_peak = 0.0
        day_dd = 0.0

        for i in range(len(df) - 15):  # Besoin de 15 barres futures

            # Cooldown
            if cooldown > 0:
                cooldown -= 1
                continue

            # Daily limit check
            if day_pnl <= self.cfg.daily_loss_limit:
                result.halted = True
                result.halt_reason = f"Daily limit ${day_pnl:.0f}"
                break

            # Max trades check (global)
            if result.n_trades >= self.cfg.max_trades_per_day:
                result.halted = True
                result.halt_reason = f"Max {self.cfg.max_trades_per_day} trades"
                break

            row = df.iloc[i]

            # ═══ CONDITION 1: Signal entry ═══
            sig = int(row.get('entry_signal', 0))
            if sig == 0:
                continue

            # ═══ CONDITION 2: SLTP valide ═══
            if not row.get('sltp_valid', False):
                continue

            # ═══ CONDITION 3: Phase autorisée ═══
            phase = row['phase']
            if phase not in self.cfg.allowed_phases:
                continue

            # ═══ CONDITION 3B: Max trades par session ═══
            session_id = row.get('session_id', '')
            session_trades = sum(1 for t in result.trades if t.session == session_id)
            if session_trades >= self.cfg.max_trades_per_session:
                continue  # Skip, pas halt — autres sessions peuvent trader
                continue

            # ═══ CONDITION 4: Filtre momentum court terme ═══
            # Ne pas entrer SHORT si prix monte fort, ni LONG si prix baisse fort
            if i >= self.cfg.momentum_bars:
                price_now = row['price']
                price_before = df.iloc[i - self.cfg.momentum_bars]['price']
                momentum = price_now - price_before  # positif = prix monte

                if sig == -1 and momentum > self.cfg.momentum_filter_pts:
                    continue  # SHORT contre momentum haussier → SKIP
                if sig == 1 and momentum < -self.cfg.momentum_filter_pts:
                    continue  # LONG contre momentum baissier → SKIP

            # ═══ TOUTES CONDITIONS OK → SCORER LA CONFLUENCE ═══
            # 🆕 3.5.2: Bonus confluence edge zones, COLOR_2, retest
            conf_bonus = 0.0
            conf_tags = []

            # Edge zone à proximité (dist_ext_edge_buy/sell)
            if sig == 1:  # LONG
                d_edge = row.get('dist_ext_edge_buy')
                if d_edge is not None and abs(d_edge) <= 15:
                    conf_bonus += 0.10
                    conf_tags.append('EDGE_BUY')
            else:  # SHORT
                d_edge = row.get('dist_ext_edge_sell')
                if d_edge is not None and abs(d_edge) <= 15:
                    conf_bonus += 0.10
                    conf_tags.append('EDGE_SELL')

            # COLOR zone type 2 (double stacké = continuation)
            if sig == 1 and row.get('bn_color_up_2', 0) == 1:
                conf_bonus += 0.08
                conf_tags.append('COLOR2_UP')
            if sig == -1 and row.get('bn_color_dn_2', 0) == 1:
                conf_bonus += 0.08
                conf_tags.append('COLOR2_DN')

            # Retest avec divergence delta
            if sig == -1 and row.get('retest_high_count', 0) > 0 and row.get('retest_high_delta_div', 0) == 1:
                conf_bonus += 0.12
                conf_tags.append('RETEST_H_DIV')
            if sig == 1 and row.get('retest_low_count', 0) > 0 and row.get('retest_low_delta_div', 0) == 1:
                conf_bonus += 0.12
                conf_tags.append('RETEST_L_DIV')

            # BN score fort dans la direction
            bn_raw = row.get('bn_score_raw', 0)
            if sig == 1 and bn_raw > 0.3:
                conf_bonus += 0.05
                conf_tags.append('BN_BULL')
            if sig == -1 and bn_raw < -0.3:
                conf_bonus += 0.05
                conf_tags.append('BN_BEAR')

            # COLOR zone + EDGE zone sur BARRES = double confirmation
            if sig == 1 and row.get('bar_color_up', 0) == 1 and row.get('bar_edge_buy', 0) == 1:
                conf_bonus += 0.05
                conf_tags.append('BAR_CONF')
            if sig == -1 and row.get('bar_color_dn', 0) == 1 and row.get('bar_edge_sell', 0) == 1:
                conf_bonus += 0.05
                conf_tags.append('BAR_CONF')

            # 🆕 3.6.0: RVOL absorption (signal fort — volume spike + absorption)
            if sig == 1 and row.get('rvol_absorb_buy', 0) == 1:
                conf_bonus += 0.15
                conf_tags.append('RVOL_ABS_BUY')
            if sig == -1 and row.get('rvol_absorb_sell', 0) == 1:
                conf_bonus += 0.15
                conf_tags.append('RVOL_ABS_SELL')

            # RVOL spike directionnel (confirmation momentum)
            if sig == 1 and row.get('rvol_buy', 0) == 1:
                conf_bonus += 0.08
                conf_tags.append('RVOL_BUY')
            if sig == -1 and row.get('rvol_sell', 0) == 1:
                conf_bonus += 0.08
                conf_tags.append('RVOL_SELL')

            # Extension LONG BAR = support/résistance momentum
            if sig == 1:
                d_long = row.get('dist_ext_long_dn')
                if d_long is not None and abs(d_long) <= 10:
                    conf_bonus += 0.10
                    conf_tags.append('EXT_LONG_DN')
            if sig == -1:
                d_long = row.get('dist_ext_long_up')
                if d_long is not None and abs(d_long) <= 10:
                    conf_bonus += 0.10
                    conf_tags.append('EXT_LONG_UP')

            # 🆕 3.6.0: Range Entry — VA extrêmes (mean reversion)
            va_pos = row.get('va_position_pct', 0.5)
            inside_va = row.get('inside_cur_va', 0)
            if inside_va == 1 and va_pos is not None:
                if sig == -1 and va_pos > 0.80:
                    conf_bonus += 0.10
                    conf_tags.append('VA_TOP')
                elif sig == 1 and va_pos < 0.20:
                    conf_bonus += 0.10
                    conf_tags.append('VA_BOT')

            # 🆕 3.6.0: Exhaustion (multi-barres momentum reversal)
            momentum_5b = row.get('momentum_5b', 0) or 0
            finish = row.get('finish_strength', 0) or 0
            if sig == 1 and momentum_5b < -3.0 and finish > 15:
                conf_bonus += 0.08
                conf_tags.append('EXHAUST_BUY')
            if sig == -1 and momentum_5b > 3.0 and finish < -15:
                conf_bonus += 0.08
                conf_tags.append('EXHAUST_SELL')

            # 🆕 3.6.0: Volume climax (rvol spike contradictoire)
            rvol_val = row.get('rvol', 1.0) or 1.0
            if rvol_val >= 2.5:
                if sig == 1 and finish > 15:
                    conf_bonus += 0.10
                    conf_tags.append('VOL_CLIMAX_BUY')
                elif sig == -1 and finish < -15:
                    conf_bonus += 0.10
                    conf_tags.append('VOL_CLIMAX_SELL')

            # 🆕 14/03/2026: MARKET PROFILE AVANCÉ (5 features)

            # Failed Auction (sortie VA + retour rapide = reversal)
            if row.get('ctx_failed_auction', 0) == 1:
                conf_bonus += 0.08
                conf_tags.append('FAILED_AUCTION')

            # POC Migration confirme la direction
            poc_mig = row.get('ctx_poc_migration_10', 0) or 0
            if sig == 1 and poc_mig > 0.01:
                conf_bonus += 0.03
                conf_tags.append('POC_MIG_UP')
            elif sig == -1 and poc_mig < -0.01:
                conf_bonus += 0.03
                conf_tags.append('POC_MIG_DN')

            # Rotation Factor élevé = range → bonus mean reversion vers POC
            rot = row.get('ctx_rotation_factor_20', 0) or 0
            if rot >= 4:
                vpoc_dist = row.get('dist_cur_vpoc', 0) or 0
                if (sig == 1 and vpoc_dist > 0) or (sig == -1 and vpoc_dist < 0):
                    conf_bonus += 0.05
                    conf_tags.append('ROTATION_MR')

            # IB Extension > 2.0 = trend day → bonus si aligné, malus si contra
            ib_ext = row.get('ctx_ib_extension_ratio', 1.0) or 1.0
            if ib_ext > 2.0:
                ib_dir = 1 if row.get('ib_broken_up', 0) == 1 else (
                    -1 if row.get('ib_broken_down', 0) == 1 else 0)
                if ib_dir != 0 and sig == ib_dir:
                    conf_bonus += 0.05
                    conf_tags.append('IB_EXT_TREND')
                elif ib_dir != 0 and sig == -ib_dir:
                    conf_bonus -= 0.05
                    conf_tags.append('IB_EXT_CONTRA')

            # 🆕 3.6.0: Double Top/Bottom (confirmation booster)
            if HAS_DOUBLE_TOP and bars_list is not None:
                try:
                    retest = detect_double_top_bottom(bars_list, i, symbol=self.cfg.symbol)
                    if retest.is_active():
                        if not retest.is_contra(sig):
                            # Aligné → boost
                            conf_bonus += retest.boost_score
                            dt_type = "DT" if retest.boost_direction < 0 else "DB"
                            level = f"@{retest.structural_level_name}" if retest.has_structural_confluence else ""
                            conf_tags.append(f"{dt_type}{level}")
                        else:
                            # Contra → pénalité
                            conf_bonus -= 0.25
                            dt_type = "DT" if retest.boost_direction < 0 else "DB"
                            conf_tags.append(f"CONTRA_{dt_type}")
                except Exception:
                    pass  # Ne pas casser le pipeline

            # ═══ SIMULER LE TRADE (avec bonus confluence) ═══
            trade = self._simulate_trade(df, i, row, sig, conf_bonus, conf_tags)

            day_pnl += trade.total_pnl_usd
            if day_pnl > day_peak:
                day_peak = day_pnl
            dd = day_peak - day_pnl
            if dd > day_dd:
                day_dd = dd

            result.trades.append(trade)
            result.n_trades += 1
            if trade.total_pnl_usd > 0:
                result.n_wins += 1
            else:
                result.n_losses += 1

            # Cooldown
            cooldown = self.cfg.cooldown_win if trade.total_pnl_usd > 0 \
                else self.cfg.cooldown_loss

        result.total_pnl_usd = day_pnl
        result.max_drawdown_usd = day_dd
        return result

    # ─── SIMULER UN TRADE ─────────────────────────────────────────

    def _simulate_trade(self, df: pd.DataFrame, bar_idx: int,
                        row: pd.Series, direction: int,
                        conf_bonus: float = 0.0,
                        conf_tags: List[str] = None) -> SimTrade:
        """Simule un trade avec 3 micros sur les barres futures."""

        trade = SimTrade(
            bar_entry=bar_idx,
            direction=direction,
            entry_price=row['price'],
            phase=row.get('phase', ''),
            session=row.get('session_id', ''),
            zone=row.get('entry_zone', ''),
            sl_wall=row.get('sltp_sl_wall', ''),
            sl_ticks=row.get('sltp_sl_ticks', 0),
            confidence=row.get('entry_conf', 0) + conf_bonus,
            bias=row.get('entry_bias', 0),
        )
        if conf_tags:
            trade.zone += f" [{'+'.join(conf_tags)}]"

        sl_t = trade.sl_ticks
        tp1_t = row.get('sltp_tp1_ticks', sl_t)
        tp3_t = row.get('sltp_tp3_ticks', sl_t * 2)
        ep = trade.entry_price
        ts = self.cfg.tick_size

        # Les 3 micros
        m1_done = False; m2_done = False; m3_done = False
        m1_pnl = 0; m2_pnl = 0; m3_pnl = 0
        trail_active = False
        trail_high = 0.0
        trail_sl = 0.0  # Trailing stop level en ticks favorable

        # Scanner les barres futures
        max_bars = min(15, len(df) - bar_idx - 1)

        for j in range(1, max_bars + 1):
            future_row = df.iloc[bar_idx + j]
            fp = future_row['price']

            # Excursion en ticks favorable
            if direction == 1:
                exc_high = (future_row.get('high', fp) - ep) / ts
                exc_low = (future_row.get('low', fp) - ep) / ts
            else:
                exc_high = (ep - future_row.get('low', fp)) / ts
                exc_low = (ep - future_row.get('high', fp)) / ts

            # Excursion avec le prix de clôture
            if direction == 1:
                exc_close = (fp - ep) / ts
            else:
                exc_close = (ep - fp) / ts

            # ── SL CHECK (tous les micros encore ouverts) ──
            if exc_low <= -sl_t:
                if not m1_done:
                    m1_pnl = -sl_t; m1_done = True
                    trade.m1_exit = "SL"
                if not m2_done:
                    m2_pnl = -sl_t; m2_done = True
                    trade.m2_exit = "SL"
                if not m3_done:
                    m3_pnl = -sl_t; m3_done = True
                    trade.m3_exit = "SL"
                trade.bar_exit = bar_idx + j
                break

            # ── MICRO 1: TP1 ──
            if not m1_done and exc_high >= tp1_t:
                m1_pnl = tp1_t
                m1_done = True
                trade.m1_exit = f"TP1({tp1_t:.0f}t)"

                # Quand M1 est sorti, monter le SL de M2/M3 au breakeven
                # (simplifié: on ne modifie pas le SL ici, le trailing s'en charge)

            # ── MICRO 2: TRAILING ──
            if not m2_done:
                if exc_high > trail_high:
                    trail_high = exc_high

                if not trail_active and trail_high >= self.cfg.trailing_start_ticks:
                    trail_active = True
                    trail_sl = trail_high - self.cfg.trailing_dist_ticks

                if trail_active:
                    new_trail_sl = trail_high - self.cfg.trailing_dist_ticks

                    # 🆕 3.5.2: Dynamic SL to nearest edge/color zone behind trade
                    # Si une zone edge/color est entre le prix et le trailing SL,
                    # resserrer le trailing au niveau de cette zone
                    if direction == 1:  # LONG: support en-dessous
                        d_edge = future_row.get('dist_ext_edge_buy')
                        d_color = future_row.get('dist_ext_color_up')
                    else:  # SHORT: résistance au-dessus
                        d_edge = future_row.get('dist_ext_edge_sell')
                        d_color = future_row.get('dist_ext_color_dn')

                    # Zone edge = point de rebond probable → bon trailing SL
                    for zone_dist in [d_edge, d_color]:
                        if zone_dist is not None and not pd.isna(zone_dist):
                            # Convertir: zone_dist est en ticks depuis le prix actuel
                            # Pour un LONG, dist_edge_buy négatif = edge en-dessous
                            zone_as_trail = exc_close + abs(zone_dist) if direction == 1 \
                                else exc_close + abs(zone_dist)
                            # Ne resserrer que si la zone est DERRIÈRE le prix (en favorable)
                            # et meilleure que le trailing actuel
                            if 0 < abs(zone_dist) < self.cfg.trailing_dist_ticks:
                                edge_trail = exc_close - abs(zone_dist) - 2  # 2t marge
                                if edge_trail > new_trail_sl:
                                    new_trail_sl = edge_trail

                    if new_trail_sl > trail_sl:
                        trail_sl = new_trail_sl

                    # Trailing SL touché?
                    if exc_close <= trail_sl or exc_low <= trail_sl:
                        m2_pnl = max(trail_sl, 0)  # Au moins breakeven
                        m2_done = True
                        trade.m2_exit = f"TRAIL({m2_pnl:.0f}t)"

            # ── MICRO 3: RUNNER ──
            if not m3_done and exc_high >= tp3_t:
                m3_pnl = tp3_t
                m3_done = True
                trade.m3_exit = f"TP3({tp3_t:.0f}t)"

        # Fermer ce qui reste au prix de la dernière barre
        last_bar = bar_idx + max_bars
        if last_bar < len(df):
            lp = df.iloc[last_bar]['price']
            if direction == 1:
                final_exc = (lp - ep) / ts
            else:
                final_exc = (ep - lp) / ts
        else:
            final_exc = 0

        if not m1_done:
            m1_pnl = final_exc; trade.m1_exit = "EOB"
        if not m2_done:
            m2_pnl = final_exc; trade.m2_exit = "EOB"
        if not m3_done:
            m3_pnl = final_exc; trade.m3_exit = "EOB"

        trade.bar_exit = last_bar
        trade.m1_pnl_ticks = m1_pnl
        trade.m2_pnl_ticks = m2_pnl
        trade.m3_pnl_ticks = m3_pnl
        trade.total_pnl_ticks = m1_pnl + m2_pnl + m3_pnl
        trade.total_pnl_usd = trade.total_pnl_ticks * self.cfg.tick_value_micro

        return trade

    # ─── RUN MULTI-JOURS ──────────────────────────────────────────

    def run_all(self, base_path: str = ".") -> List[DayResult]:
        """
        Découvre tous les JSONL et simule chaque jour.
        🆕 3.6.0: Trade NQ ET ES (dual symbole).
        """
        import glob, os, re

        reader = DmpReader(base_path)

        # Découvrir les fichiers
        pattern = os.path.join(base_path, "*_*.jsonl")
        files = glob.glob(pattern)

        dates = {}
        for f in files:
            m = re.search(r'(\d{8})_(NQ|ES)\.jsonl', os.path.basename(f))
            if m:
                date, sym = m.group(1), m.group(2)
                dates.setdefault(date, {})[sym] = f

        results = []
        for date in sorted(dates.keys()):
            syms = dates[date]
            if 'NQ' not in syms or 'ES' not in syms:
                continue

            ib = IBRecalc()
            nq_raw = ib.compute(reader.load_file(syms['NQ']), symbol="NQ")
            es_raw = ib.compute(reader.load_file(syms['ES']), symbol="ES")

            # ── NQ ──
            day_nq = self.run(date, nq_raw, es_raw)
            results.append(day_nq)

            # ── ES ──
            sim_es = TradeSimulator(SimConfig.for_es())
            day_es = sim_es.run(date, nq_raw, es_raw)
            results.append(day_es)

        return results

    # ─── RAPPORT ──────────────────────────────────────────────────

    @staticmethod
    def report(days: List[DayResult]) -> str:
        """Génère un rapport complet."""
        lines = []
        lines.append("╔══════════════════════════════════════════════════════════════╗")
        lines.append("║             MIA SIM — RAPPORT DE BACKTEST                   ║")
        lines.append("╚══════════════════════════════════════════════════════════════╝")
        lines.append("")

        if not days:
            lines.append("  Aucun jour simulé.")
            return "\n".join(lines)

        all_trades = []
        total_pnl = 0
        total_trades = 0
        total_wins = 0
        total_losses = 0
        max_dd = 0
        equity_curve = [0]

        # ── Par jour ──
        lines.append("  ── RÉSULTATS PAR JOUR ──")
        lines.append("")
        lines.append(f"  {'Date':10s} {'Sym':>3s} {'Trades':>7s} {'W/L':>6s} {'WR':>5s} "
                     f"{'PnL':>8s} {'PF':>6s} {'Avg':>7s} {'MaxDD':>7s} {'Halt'}")
        lines.append("  " + "-" * 70)

        for day in days:
            halt = day.halt_reason if day.halted else ""
            pf = f"{day.profit_factor:.2f}" if day.profit_factor < 100 else "∞"

            lines.append(f"  {day.date:10s} {day.symbol:>3s} {day.n_trades:>6d}  "
                         f"{day.n_wins}/{day.n_losses:>2d}  {day.win_rate:>4.0f}%  "
                         f"${day.total_pnl_usd:>+7.0f} {pf:>5s} "
                         f"${day.avg_trade:>+6.0f} ${day.max_drawdown_usd:>5.0f}  {halt}")

            all_trades.extend(day.trades)
            total_pnl += day.total_pnl_usd
            total_trades += day.n_trades
            total_wins += day.n_wins
            total_losses += day.n_losses
            if day.max_drawdown_usd > max_dd:
                max_dd = day.max_drawdown_usd

            # Equity curve
            for t in day.trades:
                equity_curve.append(equity_curve[-1] + t.total_pnl_usd)

        # ── Totaux ──
        lines.append("")
        lines.append("  ── TOTAUX ──")
        lines.append("")

        wr = total_wins / total_trades * 100 if total_trades > 0 else 0
        gross_win = sum(t.total_pnl_usd for t in all_trades if t.total_pnl_usd > 0)
        gross_loss = abs(sum(t.total_pnl_usd for t in all_trades if t.total_pnl_usd < 0))
        pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
        avg_win = np.mean([t.total_pnl_usd for t in all_trades if t.total_pnl_usd > 0]) \
            if total_wins > 0 else 0
        avg_loss = np.mean([t.total_pnl_usd for t in all_trades if t.total_pnl_usd < 0]) \
            if total_losses > 0 else 0

        # Max drawdown sur equity curve
        peak = 0; max_eq_dd = 0
        for eq in equity_curve:
            if eq > peak: peak = eq
            dd = peak - eq
            if dd > max_eq_dd: max_eq_dd = dd

        n_actual_days = len(set(d.date for d in days))
        lines.append(f"  Jours:          {n_actual_days}")
        lines.append(f"  Symboles:       {', '.join(sorted(set(d.symbol for d in days)))}")
        lines.append(f"  Trades:         {total_trades} ({total_trades/max(n_actual_days,1):.1f}/jour)")
        lines.append(f"  Win/Loss:       {total_wins}/{total_losses}")
        lines.append(f"  Win Rate:       {wr:.0f}%")
        lines.append(f"  PnL total:      ${total_pnl:+,.0f}")
        lines.append(f"  PnL/jour:       ${total_pnl/max(n_actual_days,1):+,.0f}")
        lines.append(f"  Profit Factor:  {pf:.2f}")
        lines.append(f"  Avg win:        ${avg_win:+,.0f}")
        lines.append(f"  Avg loss:       ${avg_loss:+,.0f}")
        lines.append(f"  Avg trade:      ${total_pnl/total_trades:+,.1f}" if total_trades > 0 else "")
        lines.append(f"  Max Drawdown:   ${max_eq_dd:,.0f}")

        # ── Par symbole ──
        symbols = sorted(set(d.symbol for d in days))
        if len(symbols) > 1:
            lines.append("")
            lines.append("  ── PAR SYMBOLE ──")
            lines.append("")
            lines.append(f"  {'Sym':5s} {'Trades':>7s} {'WR':>5s} {'PnL':>9s} {'PF':>7s} {'Avg':>8s}")
            lines.append("  " + "-" * 50)
            for sym in symbols:
                sym_days = [d for d in days if d.symbol == sym]
                st = sum(d.n_trades for d in sym_days)
                sw = sum(d.n_wins for d in sym_days)
                sl = sum(d.n_losses for d in sym_days)
                sp = sum(d.total_pnl_usd for d in sym_days)
                swr = sw / st * 100 if st > 0 else 0
                sgw = sum(t.total_pnl_usd for d in sym_days for t in d.trades if t.total_pnl_usd > 0)
                sgl = abs(sum(t.total_pnl_usd for d in sym_days for t in d.trades if t.total_pnl_usd < 0))
                spf = sgw / sgl if sgl > 0 else float('inf')
                spf_s = f"{spf:.2f}" if spf < 100 else "∞"
                savg = sp / st if st > 0 else 0
                lines.append(f"  {sym:5s} {st:>6d} {swr:>5.0f}% ${sp:>+8.0f} {spf_s:>7s} ${savg:>+7.0f}")
        lines.append("")

        # ── Détail des trades ──
        lines.append("  ── DÉTAIL DES TRADES ──")
        lines.append("")
        lines.append(f"  {'#':>3s} {'Sym':>3s} {'Bar':>5s} {'Dir':>5s} {'Phase':10s} {'Zone':12s} "
                     f"{'Wall':14s} {'SL':>4s} {'M1':>12s} {'M2':>12s} {'M3':>12s} "
                     f"{'Total':>7s}")
        lines.append("  " + "-" * 115)

        trade_num = 0
        for day in days:
            for t in day.trades:
                trade_num += 1
                d = "LONG" if t.direction == 1 else "SHORT"
                m1 = f"{t.m1_exit}({t.m1_pnl_ticks:+.0f}t)"
                m2 = f"{t.m2_exit}({t.m2_pnl_ticks:+.0f}t)"
                m3 = f"{t.m3_exit}({t.m3_pnl_ticks:+.0f}t)"

                lines.append(f"  {trade_num:>3d} {day.symbol:>3s} {t.bar_entry:>5d} {d:>5s} {t.phase:10s} "
                             f"{t.zone:12s} {t.sl_wall:14s} {t.sl_ticks:>3.0f}t "
                             f"{m1:>12s} {m2:>12s} {m3:>12s} ${t.total_pnl_usd:>+6.0f}")

        lines.append("")

        # ── Par phase ──
        if all_trades:
            lines.append("  ── PAR PHASE ──")
            lines.append("")
            phases = {}
            for t in all_trades:
                phases.setdefault(t.phase, []).append(t)

            lines.append(f"  {'Phase':12s} {'Trades':>7s} {'WR':>5s} {'PnL':>8s} {'PF':>6s} {'Avg':>7s}")
            lines.append("  " + "-" * 50)

            for phase in sorted(phases.keys()):
                trades = phases[phase]
                n = len(trades)
                w = sum(1 for t in trades if t.total_pnl_usd > 0)
                pnl = sum(t.total_pnl_usd for t in trades)
                gw = sum(t.total_pnl_usd for t in trades if t.total_pnl_usd > 0)
                gl = abs(sum(t.total_pnl_usd for t in trades if t.total_pnl_usd < 0))
                pf_ph = gw / gl if gl > 0 else float('inf')
                pf_s = f"{pf_ph:.2f}" if pf_ph < 100 else "∞"

                lines.append(f"  {phase:12s} {n:>6d}  {w/n*100:>4.0f}% ${pnl:>+7.0f} "
                             f"{pf_s:>5s} ${pnl/n:>+6.0f}")

            lines.append("")

        # ── Par mur SL ──
        if all_trades:
            lines.append("  ── PAR MUR SL ──")
            lines.append("")
            walls = {}
            for t in all_trades:
                w = t.sl_wall or "AUCUN"
                walls.setdefault(w, []).append(t)

            for wall in sorted(walls.keys(), key=lambda w: -len(walls[w])):
                trades = walls[wall]
                n = len(trades)
                w_count = sum(1 for t in trades if t.total_pnl_usd > 0)
                pnl = sum(t.total_pnl_usd for t in trades)
                lines.append(f"  {wall:20s}: {n} trades, {w_count}W, ${pnl:+.0f}")

            lines.append("")

        # ── Equity curve (texte) ──
        lines.append("  ── EQUITY CURVE ──")
        lines.append("")
        if len(equity_curve) > 1:
            max_eq = max(equity_curve)
            min_eq = min(equity_curve)
            span = max(max_eq - min_eq, 1)

            for i, eq in enumerate(equity_curve[1:]):  # Skip initial 0
                bar_len = int((eq - min_eq) / span * 40)
                lines.append(f"  T{i+1:>2d} ${eq:>+7.0f} {'█' * bar_len}")

        lines.append("")

        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    import sys, os, time

    base = sys.argv[1] if len(sys.argv) > 1 else "."

    print("MIA SIM — Backtest complet")
    print()

    t0 = time.perf_counter()

    sim = TradeSimulator()
    days = sim.run_all(base)

    elapsed = time.perf_counter() - t0

    report = sim.report(days)
    print(report)

    # Sauvegarder
    report_path = os.path.join(base, "MIA_SIM_REPORT.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Rapport sauvegardé: {report_path}")
    print(f"  Temps: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
