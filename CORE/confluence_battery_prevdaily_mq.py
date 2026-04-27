"""
confluence_battery_prevdaily_mq.py — Batterie tests confluence Previous Daily + MenthorQ.

20 confluences testees sur dataset v5c (24m ES + NQ avec 18 cols rules) :

SINGLE LEVEL (baseline) :
  C01 : BUY si proche pdl (defense low)
  C02 : SELL si proche pdh (defense high)
  C03 : BUY si proche prev_val (rotation veille)
  C04 : SELL si proche prev_vah
  C05 : BUY si proche pvwap (rebond)
  C06 : BUY si proche mq_put_0dte (gamma support)
  C07 : SELL si proche mq_call_0dte (gamma resistance)
  C08 : BUY si proche mq_hvl + delta up

2-LEVEL CONFLUENCE :
  C09 : BUY si proche prev_val ET mq_put_0dte (Steidlmayer + 0DTE)
  C10 : SELL si proche prev_vah ET mq_call_0dte
  C11 : BUY si proche pdl ET mq_put (double defense)
  C12 : SELL si proche pdh ET mq_call
  C13 : BUY si proche pvwap ET mq_hvl
  C14 : BUY si proche pvwap_sd1d (oversold band)
  C15 : SELL si proche pvwap_sd1u (overbought band)
  C16 : BUY si proche naked_poc + delta up

3-LEVEL CONFLUENCE :
  C17 : BUY si proche {prev_val, mq_put, gex_nearest_dn} (triple support)
  C18 : SELL si proche {prev_vah, mq_call, gex_nearest_up} (triple resistance)
  C19 : BUY si proche {pdl, mq_put_0dte, blind_nearest_dn}
  C20 : SELL si proche {pdh, mq_call_0dte, blind_nearest_up}

Triple Barrier ATR-dynamique cohérent v5 : K_SL=1.5, K_TP=2.0, H=60.
Coûts : ES 2.3t, NQ 5.2t. Cooldown 3 bars, max 5 trades/jour.

Auteur : MIA Trading System V2
Date   : 2026-04-28 00:00
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from strategy_battery_test import (
    mc_permutation_shuffle_order, bootstrap_pf_ci, benjamini_hochberg,
)

# Constantes alignees v5
TICK_SIZE = 0.25
K_SL = 1.5
K_TP_RATIO = 2.0
HORIZON = 60
COOLDOWN_BARS = 3
MAX_TRADES_PER_DAY = 5
COST_TICKS = {"ES": 2.3, "NQ": 5.2}

# Threshold proximité : 0.1% = ~10 ticks ES à 4500 — calibré sur p10/p90
PROX_THRESHOLD = 0.1


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _g(df, col, fill=np.nan):
    if col not in df.columns:
        return np.full(len(df), fill)
    return pd.to_numeric(df[col], errors="coerce").fillna(fill).values


def near_above(dist_arr, threshold=PROX_THRESHOLD):
    """Niveau au-dessus du prix proche : 0 < dist < threshold."""
    return (dist_arr > 0) & (dist_arr < threshold)


def near_below(dist_arr, threshold=PROX_THRESHOLD):
    """Niveau sous le prix proche : -threshold < dist < 0."""
    return (dist_arr > -threshold) & (dist_arr < 0)


def near_any(dist_arr, threshold=PROX_THRESHOLD):
    """Niveau proche peu importe direction : abs(dist) < threshold."""
    return np.abs(dist_arr) < threshold


# ═══════════════════════════════════════════════════════════════════════
# 20 confluences (signal +1/-1/0 par bar)
# ═══════════════════════════════════════════════════════════════════════

def c01_buy_near_pdl(df):
    """BUY si proche PDL (defense low). dist_pdl > 0 = PDL au-dessus = price below PDL."""
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_pdl_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta >= 0)] = 1
    return sig


def c02_sell_near_pdh(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_pdh_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta <= 0)] = -1
    return sig


def c03_buy_near_prev_val(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_prev_val_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta >= 0)] = 1
    return sig


def c04_sell_near_prev_vah(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_prev_vah_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta <= 0)] = -1
    return sig


def c05_buy_near_pvwap(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_pvwap_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta >= 0)] = 1
    return sig


def c06_buy_near_mq_put_0dte(df):
    """BUY si proche put 0DTE wall (gamma support, price retombe vers le wall)."""
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_mq_put_0dte_pct")
    delta = _g(df, "delta_day_dir")
    # Convention v5b : dist_mq_put < 0 = put wall sous le prix
    sig[(d > -PROX_THRESHOLD) & (d < 0) & (delta >= 0)] = 1
    return sig


def c07_sell_near_mq_call_0dte(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_mq_call_0dte_pct")
    delta = _g(df, "delta_day_dir")
    # Convention : dist_mq_call > 0 = call wall au-dessus
    sig[(d > 0) & (d < PROX_THRESHOLD) & (delta <= 0)] = -1
    return sig


def c08_buy_near_mq_hvl(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_mq_hvl_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta > 0)] = 1
    return sig


# ═══ 2-LEVEL CONFLUENCE ═══════════════════════════════════════════════

def c09_buy_prev_val_x_mq_put_0dte(df):
    """BUY si proche prev_val ET proche mq_put_0dte (Steidlmayer + 0DTE)."""
    sig = np.zeros(len(df), dtype=int)
    d_val = _g(df, "dist_prev_val_pct")
    d_put = _g(df, "dist_mq_put_0dte_pct")
    delta = _g(df, "delta_day_dir")
    cond = (np.abs(d_val) < PROX_THRESHOLD) & (np.abs(d_put) < PROX_THRESHOLD) & (delta >= 0)
    sig[cond] = 1
    return sig


def c10_sell_prev_vah_x_mq_call_0dte(df):
    sig = np.zeros(len(df), dtype=int)
    d_vah = _g(df, "dist_prev_vah_pct")
    d_call = _g(df, "dist_mq_call_0dte_pct")
    delta = _g(df, "delta_day_dir")
    cond = (np.abs(d_vah) < PROX_THRESHOLD) & (np.abs(d_call) < PROX_THRESHOLD) & (delta <= 0)
    sig[cond] = -1
    return sig


def c11_buy_pdl_x_mq_put(df):
    sig = np.zeros(len(df), dtype=int)
    d_pdl = _g(df, "dist_pdl_pct")
    d_put = _g(df, "dist_mq_put_pct")
    delta = _g(df, "delta_day_dir")
    cond = (np.abs(d_pdl) < PROX_THRESHOLD) & (np.abs(d_put) < PROX_THRESHOLD * 5) & (delta >= 0)
    sig[cond] = 1
    return sig


def c12_sell_pdh_x_mq_call(df):
    sig = np.zeros(len(df), dtype=int)
    d_pdh = _g(df, "dist_pdh_pct")
    d_call = _g(df, "dist_mq_call_pct")
    delta = _g(df, "delta_day_dir")
    cond = (np.abs(d_pdh) < PROX_THRESHOLD) & (np.abs(d_call) < PROX_THRESHOLD * 5) & (delta <= 0)
    sig[cond] = -1
    return sig


def c13_buy_pvwap_x_mq_hvl(df):
    sig = np.zeros(len(df), dtype=int)
    d_pv = _g(df, "dist_pvwap_pct")
    d_hvl = _g(df, "dist_mq_hvl_pct")
    delta = _g(df, "delta_day_dir")
    cond = (np.abs(d_pv) < PROX_THRESHOLD) & (np.abs(d_hvl) < PROX_THRESHOLD * 3) & (delta > 0)
    sig[cond] = 1
    return sig


def c14_buy_pvwap_sd1d(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_pvwap_sd1d_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta >= 0)] = 1
    return sig


def c15_sell_pvwap_sd1u(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_pvwap_sd1u_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta <= 0)] = -1
    return sig


def c16_buy_naked_poc_delta(df):
    sig = np.zeros(len(df), dtype=int)
    d = _g(df, "dist_naked_poc_nearest_pct")
    delta = _g(df, "delta_day_dir")
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta > 0)] = 1
    sig[(np.abs(d) < PROX_THRESHOLD) & (delta < 0)] = -1
    return sig


# ═══ 3-LEVEL CONFLUENCE ═══════════════════════════════════════════════

def c17_buy_triple_support(df):
    """BUY si proche prev_val ET mq_put ET gex_nearest_dn."""
    sig = np.zeros(len(df), dtype=int)
    d_val = _g(df, "dist_prev_val_pct")
    d_put = _g(df, "dist_mq_put_pct")
    d_gex = _g(df, "dist_gex_nearest_dn_pct")
    delta = _g(df, "delta_day_dir")
    cond = (
        (np.abs(d_val) < PROX_THRESHOLD * 2)
        & (np.abs(d_put) < PROX_THRESHOLD * 5)
        & (np.abs(d_gex) < PROX_THRESHOLD * 3)
        & (delta >= 0)
    )
    sig[cond] = 1
    return sig


def c18_sell_triple_resistance(df):
    sig = np.zeros(len(df), dtype=int)
    d_vah = _g(df, "dist_prev_vah_pct")
    d_call = _g(df, "dist_mq_call_pct")
    d_gex = _g(df, "dist_gex_nearest_up_pct")
    delta = _g(df, "delta_day_dir")
    cond = (
        (np.abs(d_vah) < PROX_THRESHOLD * 2)
        & (np.abs(d_call) < PROX_THRESHOLD * 5)
        & (np.abs(d_gex) < PROX_THRESHOLD * 3)
        & (delta <= 0)
    )
    sig[cond] = -1
    return sig


def c19_buy_pdl_x_put0dte_x_blind_dn(df):
    sig = np.zeros(len(df), dtype=int)
    d_pdl = _g(df, "dist_pdl_pct")
    d_put = _g(df, "dist_mq_put_0dte_pct")
    d_blind = _g(df, "dist_blind_nearest_dn_pct")
    delta = _g(df, "delta_day_dir")
    cond = (
        (np.abs(d_pdl) < PROX_THRESHOLD * 2)
        & (np.abs(d_put) < PROX_THRESHOLD * 3)
        & (np.abs(d_blind) < PROX_THRESHOLD * 3)
        & (delta >= 0)
    )
    sig[cond] = 1
    return sig


def c20_sell_pdh_x_call0dte_x_blind_up(df):
    sig = np.zeros(len(df), dtype=int)
    d_pdh = _g(df, "dist_pdh_pct")
    d_call = _g(df, "dist_mq_call_0dte_pct")
    d_blind = _g(df, "dist_blind_nearest_up_pct")
    delta = _g(df, "delta_day_dir")
    cond = (
        (np.abs(d_pdh) < PROX_THRESHOLD * 2)
        & (np.abs(d_call) < PROX_THRESHOLD * 3)
        & (np.abs(d_blind) < PROX_THRESHOLD * 3)
        & (delta <= 0)
    )
    sig[cond] = -1
    return sig


CONFLUENCES = [
    ("C01", "BUY pdl proximity", c01_buy_near_pdl),
    ("C02", "SELL pdh proximity", c02_sell_near_pdh),
    ("C03", "BUY prev_val proximity", c03_buy_near_prev_val),
    ("C04", "SELL prev_vah proximity", c04_sell_near_prev_vah),
    ("C05", "BUY pvwap proximity", c05_buy_near_pvwap),
    ("C06", "BUY mq_put_0dte gamma support", c06_buy_near_mq_put_0dte),
    ("C07", "SELL mq_call_0dte gamma resist", c07_sell_near_mq_call_0dte),
    ("C08", "BUY mq_hvl + delta up", c08_buy_near_mq_hvl),
    ("C09", "BUY prev_val × mq_put_0dte", c09_buy_prev_val_x_mq_put_0dte),
    ("C10", "SELL prev_vah × mq_call_0dte", c10_sell_prev_vah_x_mq_call_0dte),
    ("C11", "BUY pdl × mq_put", c11_buy_pdl_x_mq_put),
    ("C12", "SELL pdh × mq_call", c12_sell_pdh_x_mq_call),
    ("C13", "BUY pvwap × mq_hvl", c13_buy_pvwap_x_mq_hvl),
    ("C14", "BUY pvwap_sd1d (oversold)", c14_buy_pvwap_sd1d),
    ("C15", "SELL pvwap_sd1u (overbought)", c15_sell_pvwap_sd1u),
    ("C16", "BUY/SELL naked_poc + delta", c16_buy_naked_poc_delta),
    ("C17", "BUY triple support (val × put × gex)", c17_buy_triple_support),
    ("C18", "SELL triple resist (vah × call × gex)", c18_sell_triple_resistance),
    ("C19", "BUY pdl × put_0dte × blind_dn", c19_buy_pdl_x_put0dte_x_blind_dn),
    ("C20", "SELL pdh × call_0dte × blind_up", c20_sell_pdh_x_call0dte_x_blind_up),
]


# ═══════════════════════════════════════════════════════════════════════
# Simulator forward + Stats (réutilise pattern strategy_battery_v5)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    direction: int
    entry_bar: int
    pnl_ticks: float
    won: bool
    date: Optional[str] = None
    hit_type: str = "unknown"


@dataclass
class SimResult:
    name: str
    trades: List[TradeResult] = field(default_factory=list)
    n_bars: int = 0
    n_days: int = 0

    @property
    def n_trades(self):
        return len(self.trades)

    @property
    def win_rate(self):
        return sum(1 for t in self.trades if t.won) / self.n_trades if self.n_trades else 0.0

    @property
    def total_pnl(self):
        return sum(t.pnl_ticks for t in self.trades)

    @property
    def gross_wins(self):
        return sum(t.pnl_ticks for t in self.trades if t.won)

    @property
    def gross_losses(self):
        return abs(sum(t.pnl_ticks for t in self.trades if not t.won))

    @property
    def profit_factor(self):
        if self.n_trades == 0:
            return float("nan")
        if self.gross_losses <= 0:
            return float("inf") if self.gross_wins > 0 else float("nan")
        return self.gross_wins / self.gross_losses

    @property
    def ev_per_trade(self):
        return self.total_pnl / self.n_trades if self.n_trades else 0.0

    @property
    def trades_per_day(self):
        return self.n_trades / self.n_days if self.n_days else 0.0

    @property
    def max_drawdown(self):
        if not self.trades:
            return 0.0
        cumsum = np.cumsum([t.pnl_ticks for t in self.trades])
        peak = np.maximum.accumulate(cumsum)
        return float((peak - cumsum).max())

    @property
    def sharpe_daily(self):
        if self.n_trades < 5 or self.n_days < 5:
            return 0.0
        daily = defaultdict(float)
        for t in self.trades:
            if t.date:
                daily[t.date] += t.pnl_ticks
        arr = np.array(list(daily.values()), dtype=float)
        if len(arr) < 5 or arr.std() < 1e-6:
            return 0.0
        return float(arr.mean() / arr.std() * np.sqrt(252.0))


def simulate_forward(df, signal, name, symbol):
    closes = df["close"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date.values
    cost = COST_TICKS[symbol]
    trades = []
    last_bar = -COOLDOWN_BARS - 1
    daily_count = {}
    unique_days = set(dates.tolist())
    n = len(df)

    for i in range(n - HORIZON - 1):
        if signal[i] == 0:
            continue
        if i - last_bar < COOLDOWN_BARS:
            continue
        d = dates[i]
        if daily_count.get(d, 0) >= MAX_TRADES_PER_DAY:
            continue
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_ticks = K_SL * atr_t
        tp_ticks = K_TP_RATIO * sl_ticks
        direction = int(signal[i])
        entry = closes[i]
        if not np.isfinite(entry):
            continue
        sl_pts = sl_ticks * TICK_SIZE
        tp_pts = tp_ticks * TICK_SIZE
        if direction == 1:
            tp_lvl = entry + tp_pts
            sl_lvl = entry - sl_pts
        else:
            tp_lvl = entry - tp_pts
            sl_lvl = entry + sl_pts

        exit_pnl = -cost
        hit_type = "time"
        for k in range(1, HORIZON + 1):
            j = i + k
            if j >= n:
                break
            h = highs[j]
            l = lows[j]
            if direction == 1:
                if l <= sl_lvl:
                    exit_pnl = -sl_ticks - cost
                    hit_type = "sl"
                    break
                if h >= tp_lvl:
                    exit_pnl = tp_ticks - cost
                    hit_type = "tp"
                    break
            else:
                if h >= sl_lvl:
                    exit_pnl = -sl_ticks - cost
                    hit_type = "sl"
                    break
                if l <= tp_lvl:
                    exit_pnl = tp_ticks - cost
                    hit_type = "tp"
                    break
        else:
            exit_close = closes[i + HORIZON] if (i + HORIZON) < n else entry
            exit_pnl = (exit_close - entry) / TICK_SIZE * direction - cost

        trades.append(TradeResult(
            direction=direction, entry_bar=i, pnl_ticks=float(exit_pnl),
            won=exit_pnl > 0, date=str(d) if d else None, hit_type=hit_type,
        ))
        last_bar = i
        daily_count[d] = daily_count.get(d, 0) + 1

    return SimResult(name=name, trades=trades, n_bars=n, n_days=len(unique_days))


def compute_verdict(sim, mc_p, pf_lo, bh_significant):
    if sim.n_trades < 30:
        return "NO-GO (n<30)"
    if not np.isfinite(sim.profit_factor) or sim.profit_factor < 1.3:
        return "NO-GO (PF<1.3)"
    if sim.win_rate < 0.35:
        return "NO-GO (WR<35%)"
    if sim.ev_per_trade < 1.0:
        return "NO-GO (EV<1t)"
    if np.isfinite(mc_p) and mc_p > 0.10:
        return "NO-GO (MC p>0.10)"
    if not bh_significant:
        return "CAUTION (not BH)"
    if np.isfinite(pf_lo) and pf_lo < 1.0:
        return "CAUTION (PF_lo<1)"
    if sim.profit_factor >= 1.5 and sim.win_rate >= 0.42 and np.isfinite(mc_p) and mc_p <= 0.05:
        return "GO"
    return "CAUTION"


def run_battery(symbol):
    print(f"\n{'='*70}")
    print(f"  CONFLUENCE BATTERY — {symbol}")
    print(f"{'='*70}")
    df = pd.read_parquet(ROOT / f"DATA/datasets/{symbol}_dataset_v5c.parquet")
    n_days = pd.to_datetime(df["ts"], unit="ms").dt.date.nunique()
    print(f"  {len(df):,} bars × {df.shape[1]} cols, {n_days} jours")

    results = []
    for code, name, func in CONFLUENCES:
        try:
            signal = func(df)
        except Exception as e:
            print(f"  [{code}] ERROR : {type(e).__name__}: {str(e)[:80]}")
            continue

        n_signals = int((signal != 0).sum())
        if n_signals < 10:
            print(f"  [{code}] {name[:40]:<40} {n_signals:>5} signals (skip)")
            results.append({
                "code": code, "name": name, "symbol": symbol,
                "n_signals": n_signals, "n_trades": 0,
                "win_rate": 0, "profit_factor": float("nan"),
                "ev_per_trade": 0, "sharpe_daily": 0,
                "max_dd": 0, "trades_day": 0, "total_pnl": 0,
                "mc_p_value": float("nan"),
                "pf_ci_lo": float("nan"), "pf_ci_hi": float("nan"),
                "verdict": "NO-GO (signals)",
                "hit_tp": 0, "hit_sl": 0, "hit_time": 0,
            })
            continue

        sim = simulate_forward(df, signal, f"{code}: {name}", symbol)
        if sim.n_trades < 20:
            mc_p, pf_lo, pf_hi = float("nan"), float("nan"), float("nan")
        else:
            mc_p = mc_permutation_shuffle_order(sim, n_iters=2000)
            pf_lo, pf_hi = bootstrap_pf_ci(sim, n_iters=1000)

        hit_tp = sum(1 for t in sim.trades if t.hit_type == "tp")
        hit_sl = sum(1 for t in sim.trades if t.hit_type == "sl")
        hit_time = sum(1 for t in sim.trades if t.hit_type == "time")

        results.append({
            "code": code, "name": name, "symbol": symbol,
            "n_signals": n_signals,
            "n_trades": sim.n_trades,
            "win_rate": sim.win_rate,
            "profit_factor": sim.profit_factor,
            "ev_per_trade": sim.ev_per_trade,
            "sharpe_daily": sim.sharpe_daily,
            "max_dd": sim.max_drawdown,
            "trades_day": sim.trades_per_day,
            "total_pnl": sim.total_pnl,
            "mc_p_value": mc_p,
            "pf_ci_lo": pf_lo, "pf_ci_hi": pf_hi,
            "hit_tp": hit_tp, "hit_sl": hit_sl, "hit_time": hit_time,
            "verdict": "TBD",
        })
        pf_str = f"{sim.profit_factor:.2f}" if np.isfinite(sim.profit_factor) else "inf"
        mc_str = f"{mc_p:.3f}" if np.isfinite(mc_p) else "n/a"
        print(f"  [{code}] {name[:38]:<38} sig={n_signals:>6} trades={sim.n_trades:>5} "
              f"WR={sim.win_rate*100:>4.1f}% PF={pf_str:>5} EV={sim.ev_per_trade:+5.1f}t "
              f"Sharpe={sim.sharpe_daily:>5.2f} MC={mc_str}")

    # BH FDR
    pvals = [r["mc_p_value"] for r in results]
    bh_sig = benjamini_hochberg(pvals, alpha=0.05)
    for r, sig_bh in zip(results, bh_sig):
        if r["n_trades"] < 30:
            continue
        r["bh_significant"] = bool(sig_bh)
        fake_sim = type("FakeSim", (), {
            "n_trades": r["n_trades"],
            "profit_factor": r["profit_factor"],
            "win_rate": r["win_rate"],
            "ev_per_trade": r["ev_per_trade"],
        })()
        r["verdict"] = compute_verdict(fake_sim, r["mc_p_value"], r["pf_ci_lo"], sig_bh)

    return results


def main():
    print("=" * 70)
    print("CONFLUENCE BATTERY PREVIOUS DAILY + MENTHORQ — 20 confluences")
    print("=" * 70)
    print(f"  K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON} prox_threshold={PROX_THRESHOLD}%")

    all_results = []
    for sym in ["ES", "NQ"]:
        try:
            all_results.extend(run_battery(sym))
        except Exception as e:
            print(f"\n[ERROR] {sym} : {type(e).__name__}: {e}")

    if not all_results:
        return

    # Save MD
    out_path = ROOT / "DOCS" / "CONFLUENCE_BATTERY_PREVDAILY_MQ.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Confluence Battery Previous Daily + MenthorQ\n\n")
        f.write(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Source** : ES/NQ_dataset_v5c.parquet (24m, 351K bars)\n")
        f.write(f"**Triple Barrier** : K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON}\n")
        f.write(f"**Prox threshold** : {PROX_THRESHOLD}% (10 ticks ES @4500)\n")
        f.write(f"**Costs** : ES {COST_TICKS['ES']}t, NQ {COST_TICKS['NQ']}t\n\n")
        f.write("## Top par PF (n_trades >= 30, PF descendant)\n\n")
        f.write("| Rang | Code | Confluence | Sym | Trades | WR | PF | EV | Sharpe | MC_p | BH | Verdict |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
        sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
        for rank, r in enumerate(sortable, 1):
            pf = f"{r['profit_factor']:.2f}"
            mc = f"{r['mc_p_value']:.3f}" if np.isfinite(r["mc_p_value"]) else "n/a"
            bh = "OK" if r.get("bh_significant", False) else "no"
            f.write(f"| {rank} | {r['code']} | {r['name']} | {r['symbol']} | "
                    f"{r['n_trades']} | {r['win_rate']*100:.1f}% | {pf} | "
                    f"{r['ev_per_trade']:+.1f}t | {r['sharpe_daily']:.2f} | "
                    f"{mc} | {bh} | {r['verdict']} |\n")
        f.write("\n## Confluences non-evaluables (signals < 10)\n\n")
        skipped = [r for r in all_results if r["n_trades"] < 30]
        for r in skipped:
            f.write(f"- {r['code']} {r['name']} ({r['symbol']}) : {r['n_signals']} signaux\n")
    print(f"\n[SAVED] {out_path}")

    # TOP 15 console
    print("\n" + "=" * 70)
    print("TOP 15 CONFLUENCES (PF descendant, n_trades >= 30)")
    print("=" * 70)
    sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
    sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
    for r in sortable[:15]:
        pf = f"{r['profit_factor']:.2f}"
        bh = "OK" if r.get("bh_significant", False) else "no"
        print(f"  [{r['code']}] {r['symbol']:<2} {r['name'][:40]:<40} | "
              f"trades={r['n_trades']:>4} WR={r['win_rate']*100:>4.1f}% PF={pf} "
              f"EV={r['ev_per_trade']:+5.1f}t Sharpe={r['sharpe_daily']:.2f} BH={bh} | {r['verdict']}")


if __name__ == "__main__":
    main()
