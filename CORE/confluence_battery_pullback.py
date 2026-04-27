"""
confluence_battery_pullback.py — Tests setup PULLBACK CONTINUATION Jackson.

Pattern observé visuellement par Jackson :
  "Le prix monte, puis léger replis sur des nouveaux color up
   et long_down_up bar, ET il repart. Ça arrive souvent."

Décomposition :
  - Trend UP en cours (delta day positif, possiblement above VWAP daily)
  - Pullback léger proche zone color up récente
  - long_dn_up_pattern fire (rejection wick down→up sur la bar)
  - RTH only (clean order flow)
  - → BUY continuation

Variantes testées :
  P01 : BUY pullback long_dn_up + color_up + delta>0 + RTH
  P02 : BUY pullback + above VWAP_d (filter trend strict)
  P03 : BUY pullback + MQ HVL confluence
  P04 : BUY pullback + cluster recent (n_color_up_zones_active >= 5)
  P05 : SELL pullback symmetric (long_up_dn + color_dn + delta<0 + below VWAP)
  P06 : SELL pullback symmetric simple
  P07 : BUY pullback + bn_trapped_sellers_at_support (Acosta confluence)
  P08 : BUY pullback + edge_zone_buy_fire (edge zone confluence)

Triple Barrier ATR-dynamique cohérent v5 : K_SL=1.5, K_TP=2.0, H=60.

Auteur : MIA Trading System V2
Date   : 2026-04-28 00:30
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from strategy_battery_test import (
    mc_permutation_shuffle_order, bootstrap_pf_ci, benjamini_hochberg,
)

TICK_SIZE = 0.25
K_SL = 1.5
K_TP_RATIO = 2.0
HORIZON = 60
COOLDOWN_BARS = 3
MAX_TRADES_PER_DAY = 5
COST_TICKS = {"ES": 2.3, "NQ": 5.2}

PROX_THRESHOLD = 0.1  # 0.1% du prix


def _g(df, col, fill=0.0):
    if col not in df.columns:
        return np.full(len(df), fill)
    return pd.to_numeric(df[col], errors="coerce").fillna(fill).values


# ═══════════════════════════════════════════════════════════════════════
# 8 variantes pullback continuation
# ═══════════════════════════════════════════════════════════════════════

def p01_buy_pullback_simple(df):
    """BUY : long_dn_up_pattern + proche color_up + delta>0 + RTH."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_color_up = _g(df, "dist_color_up_nearest_pct")
    pattern = _g(df, "long_dn_up_pattern")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta > 0)
        & (np.abs(d_color_up) < PROX_THRESHOLD)
        & (pattern == 1)
        & (rth == 1)
    )
    sig[cond] = 1
    return sig


def p02_buy_pullback_above_vwap(df):
    """BUY pullback + above VWAP daily (filter trend strict)."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_vwap = _g(df, "dist_vwap_d_atr")
    d_color_up = _g(df, "dist_color_up_nearest_pct")
    pattern = _g(df, "long_dn_up_pattern")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta > 0)
        & (d_vwap > 0)
        & (np.abs(d_color_up) < PROX_THRESHOLD)
        & (pattern == 1)
        & (rth == 1)
    )
    sig[cond] = 1
    return sig


def p03_buy_pullback_mq_hvl(df):
    """BUY pullback + MQ HVL confluence."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_color_up = _g(df, "dist_color_up_nearest_pct")
    d_hvl = _g(df, "dist_mq_hvl_pct", fill=99.0)
    pattern = _g(df, "long_dn_up_pattern")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta > 0)
        & (np.abs(d_color_up) < PROX_THRESHOLD)
        & (pattern == 1)
        & (rth == 1)
        & (np.abs(d_hvl) < 0.5)
    )
    sig[cond] = 1
    return sig


def p04_buy_pullback_cluster(df):
    """BUY pullback + n_color_up_zones_active >= 5 (zone récente nombreuse)."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_color_up = _g(df, "dist_color_up_nearest_pct")
    n_zones = _g(df, "n_color_up_zones_active")
    pattern = _g(df, "long_dn_up_pattern")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta > 0)
        & (np.abs(d_color_up) < PROX_THRESHOLD)
        & (n_zones >= 5)
        & (pattern == 1)
        & (rth == 1)
    )
    sig[cond] = 1
    return sig


def p05_sell_pullback_above_vwap_inverted(df):
    """SELL : long_up_dn + color_dn + delta<0 + below VWAP_d (full symmetric)."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_vwap = _g(df, "dist_vwap_d_atr")
    d_color_dn = _g(df, "dist_color_dn_nearest_pct")
    pattern = _g(df, "long_up_dn_pattern")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta < 0)
        & (d_vwap < 0)
        & (np.abs(d_color_dn) < PROX_THRESHOLD)
        & (pattern == 1)
        & (rth == 1)
    )
    sig[cond] = -1
    return sig


def p06_sell_pullback_simple(df):
    """SELL pullback simple."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_color_dn = _g(df, "dist_color_dn_nearest_pct")
    pattern = _g(df, "long_up_dn_pattern")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta < 0)
        & (np.abs(d_color_dn) < PROX_THRESHOLD)
        & (pattern == 1)
        & (rth == 1)
    )
    sig[cond] = -1
    return sig


def p07_buy_pullback_trapped_sellers(df):
    """BUY pullback + bn_trapped_sellers_at_support (Acosta-style confluence)."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_color_up = _g(df, "dist_color_up_nearest_pct")
    pattern = _g(df, "long_dn_up_pattern")
    trapped = _g(df, "bn_trapped_sellers_at_support")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta > 0)
        & (np.abs(d_color_up) < PROX_THRESHOLD * 2)  # élargi vu trapped rare
        & ((pattern == 1) | (trapped == 1))           # OR (élargit fires)
        & (rth == 1)
    )
    sig[cond] = 1
    return sig


def p08_buy_pullback_edge_zone(df):
    """BUY pullback + bar_edge_buy_fire confluence."""
    sig = np.zeros(len(df), dtype=int)
    delta = _g(df, "delta_day_dir")
    d_color_up = _g(df, "dist_color_up_nearest_pct")
    pattern = _g(df, "long_dn_up_pattern")
    edge_buy = _g(df, "bar_edge_buy_fire")
    rth = _g(df, "is_in_us_cash")
    cond = (
        (delta > 0)
        & (np.abs(d_color_up) < PROX_THRESHOLD)
        & ((pattern == 1) | (edge_buy == 1))
        & (rth == 1)
    )
    sig[cond] = 1
    return sig


PULLBACKS = [
    ("P01", "BUY pullback simple (delta+color_up+long_dn_up)", p01_buy_pullback_simple),
    ("P02", "BUY pullback + above VWAP_d (trend strict)", p02_buy_pullback_above_vwap),
    ("P03", "BUY pullback + MQ HVL confluence", p03_buy_pullback_mq_hvl),
    ("P04", "BUY pullback + n_color_up_zones >= 5", p04_buy_pullback_cluster),
    ("P05", "SELL pullback + below VWAP_d (full symm)", p05_sell_pullback_above_vwap_inverted),
    ("P06", "SELL pullback simple", p06_sell_pullback_simple),
    ("P07", "BUY pullback + trapped_sellers_at_support OR", p07_buy_pullback_trapped_sellers),
    ("P08", "BUY pullback + edge_buy_fire OR", p08_buy_pullback_edge_zone),
]


# ═══════════════════════════════════════════════════════════════════════
# Sim + stats (réutilise le pattern strategy_battery_v5)
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
    def n_trades(self): return len(self.trades)
    @property
    def win_rate(self): return sum(1 for t in self.trades if t.won)/self.n_trades if self.n_trades else 0
    @property
    def total_pnl(self): return sum(t.pnl_ticks for t in self.trades)
    @property
    def gross_wins(self): return sum(t.pnl_ticks for t in self.trades if t.won)
    @property
    def gross_losses(self): return abs(sum(t.pnl_ticks for t in self.trades if not t.won))
    @property
    def profit_factor(self):
        if self.n_trades == 0: return float("nan")
        if self.gross_losses <= 0: return float("inf") if self.gross_wins > 0 else float("nan")
        return self.gross_wins / self.gross_losses
    @property
    def ev_per_trade(self): return self.total_pnl/self.n_trades if self.n_trades else 0
    @property
    def trades_per_day(self): return self.n_trades/self.n_days if self.n_days else 0
    @property
    def max_drawdown(self):
        if not self.trades: return 0
        cumsum = np.cumsum([t.pnl_ticks for t in self.trades])
        peak = np.maximum.accumulate(cumsum)
        return float((peak - cumsum).max())
    @property
    def sharpe_daily(self):
        if self.n_trades < 5 or self.n_days < 5: return 0
        daily = defaultdict(float)
        for t in self.trades:
            if t.date: daily[t.date] += t.pnl_ticks
        arr = np.array(list(daily.values()))
        if len(arr) < 5 or arr.std() < 1e-6: return 0
        return float(arr.mean()/arr.std()*np.sqrt(252.0))


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
        if signal[i] == 0: continue
        if i - last_bar < COOLDOWN_BARS: continue
        d = dates[i]
        if daily_count.get(d, 0) >= MAX_TRADES_PER_DAY: continue
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t): continue
        sl_ticks = K_SL * atr_t
        tp_ticks = K_TP_RATIO * sl_ticks
        direction = int(signal[i])
        entry = closes[i]
        if not np.isfinite(entry): continue
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
        for k in range(1, HORIZON+1):
            j = i + k
            if j >= n: break
            h = highs[j]; l = lows[j]
            if direction == 1:
                if l <= sl_lvl:
                    exit_pnl = -sl_ticks - cost; hit_type = "sl"; break
                if h >= tp_lvl:
                    exit_pnl = tp_ticks - cost; hit_type = "tp"; break
            else:
                if h >= sl_lvl:
                    exit_pnl = -sl_ticks - cost; hit_type = "sl"; break
                if l <= tp_lvl:
                    exit_pnl = tp_ticks - cost; hit_type = "tp"; break
        else:
            exit_close = closes[i + HORIZON] if (i + HORIZON) < n else entry
            exit_pnl = (exit_close - entry)/TICK_SIZE*direction - cost
        trades.append(TradeResult(
            direction=direction, entry_bar=i, pnl_ticks=float(exit_pnl),
            won=exit_pnl > 0, date=str(d) if d else None, hit_type=hit_type,
        ))
        last_bar = i
        daily_count[d] = daily_count.get(d, 0) + 1
    return SimResult(name=name, trades=trades, n_bars=n, n_days=len(unique_days))


def compute_verdict(sim, mc_p, pf_lo, bh):
    if sim.n_trades < 30: return "NO-GO (n<30)"
    if not np.isfinite(sim.profit_factor) or sim.profit_factor < 1.3: return "NO-GO (PF<1.3)"
    if sim.win_rate < 0.35: return "NO-GO (WR<35%)"
    if sim.ev_per_trade < 1.0: return "NO-GO (EV<1t)"
    if np.isfinite(mc_p) and mc_p > 0.10: return "NO-GO (MC>0.10)"
    if not bh: return "CAUTION (not BH)"
    if np.isfinite(pf_lo) and pf_lo < 1.0: return "CAUTION (PF_lo<1)"
    if sim.profit_factor >= 1.5 and sim.win_rate >= 0.42 and np.isfinite(mc_p) and mc_p <= 0.05: return "GO"
    return "CAUTION"


def run_battery(symbol):
    print(f"\n{'='*70}")
    print(f"  PULLBACK BATTERY — {symbol}")
    print(f"{'='*70}")
    df = pd.read_parquet(ROOT / f"DATA/datasets/{symbol}_dataset_v5c.parquet")
    n_days = pd.to_datetime(df["ts"], unit="ms").dt.date.nunique()
    print(f"  {len(df):,} bars × {df.shape[1]} cols, {n_days} jours")

    results = []
    for code, name, func in PULLBACKS:
        try: signal = func(df)
        except Exception as e:
            print(f"  [{code}] ERROR : {e}"); continue
        n_signals = int((signal != 0).sum())
        if n_signals < 10:
            print(f"  [{code}] {name[:42]:<42} {n_signals:>5} signals (skip)")
            results.append({"code": code, "name": name, "symbol": symbol, "n_signals": n_signals,
                            "n_trades": 0, "win_rate": 0, "profit_factor": float("nan"),
                            "ev_per_trade": 0, "sharpe_daily": 0, "max_dd": 0, "trades_day": 0,
                            "total_pnl": 0, "mc_p_value": float("nan"), "pf_ci_lo": float("nan"),
                            "pf_ci_hi": float("nan"), "verdict": "NO-GO (signals)",
                            "hit_tp": 0, "hit_sl": 0, "hit_time": 0})
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
        results.append({"code": code, "name": name, "symbol": symbol, "n_signals": n_signals,
                        "n_trades": sim.n_trades, "win_rate": sim.win_rate,
                        "profit_factor": sim.profit_factor, "ev_per_trade": sim.ev_per_trade,
                        "sharpe_daily": sim.sharpe_daily, "max_dd": sim.max_drawdown,
                        "trades_day": sim.trades_per_day, "total_pnl": sim.total_pnl,
                        "mc_p_value": mc_p, "pf_ci_lo": pf_lo, "pf_ci_hi": pf_hi,
                        "hit_tp": hit_tp, "hit_sl": hit_sl, "hit_time": hit_time, "verdict": "TBD"})
        pf_str = f"{sim.profit_factor:.2f}" if np.isfinite(sim.profit_factor) else "inf"
        mc_str = f"{mc_p:.3f}" if np.isfinite(mc_p) else "n/a"
        print(f"  [{code}] {name[:40]:<40} sig={n_signals:>5} trades={sim.n_trades:>4} "
              f"WR={sim.win_rate*100:>4.1f}% PF={pf_str:>5} EV={sim.ev_per_trade:+5.1f}t "
              f"Sharpe={sim.sharpe_daily:>5.2f} MC={mc_str}")
    pvals = [r["mc_p_value"] for r in results]
    bh_sig = benjamini_hochberg(pvals, alpha=0.05)
    for r, sig_bh in zip(results, bh_sig):
        if r["n_trades"] < 30: continue
        r["bh_significant"] = bool(sig_bh)
        fake_sim = type("F", (), {"n_trades": r["n_trades"], "profit_factor": r["profit_factor"],
                                   "win_rate": r["win_rate"], "ev_per_trade": r["ev_per_trade"]})()
        r["verdict"] = compute_verdict(fake_sim, r["mc_p_value"], r["pf_ci_lo"], sig_bh)
    return results


def main():
    print("=" * 70)
    print("PULLBACK CONTINUATION BATTERY — Setup Jackson visuel")
    print("=" * 70)
    print(f"  K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON} prox={PROX_THRESHOLD}%")
    all_results = []
    for sym in ["ES", "NQ"]:
        try: all_results.extend(run_battery(sym))
        except Exception as e: print(f"\n[ERROR] {sym}: {e}")
    if not all_results: return
    out_path = ROOT / "DOCS" / "CONFLUENCE_BATTERY_PULLBACK.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Pullback Continuation Battery — Setup Jackson\n\n")
        f.write(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Pattern observe** : prix monte → pullback color_up + long_dn_up bar → repart\n\n")
        f.write(f"**TB** : K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON}\n\n")
        f.write("## Top par PF\n\n")
        f.write("| # | Code | Variante | Sym | Trades | WR | PF | EV | Sharpe | MC_p | BH | Verdict |\n")
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
        f.write("\n## Variantes non-evaluables (signals < 10)\n\n")
        for r in [r for r in all_results if r["n_trades"] < 30]:
            f.write(f"- {r['code']} {r['name']} ({r['symbol']}) : {r['n_signals']} signaux, {r['n_trades']} trades\n")
    print(f"\n[SAVED] {out_path}")
    print("\n" + "=" * 70)
    print("TOP CONFLUENCES")
    print("=" * 70)
    sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
    sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
    for r in sortable:
        pf = f"{r['profit_factor']:.2f}"
        bh = "OK" if r.get("bh_significant", False) else "no"
        print(f"  [{r['code']}] {r['symbol']:<2} {r['name'][:42]:<42} | "
              f"trades={r['n_trades']:>4} WR={r['win_rate']*100:>4.1f}% PF={pf} "
              f"EV={r['ev_per_trade']:+5.1f}t Sharpe={r['sharpe_daily']:.2f} BH={bh} | {r['verdict']}")


if __name__ == "__main__":
    main()
