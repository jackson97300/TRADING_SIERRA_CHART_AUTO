"""
strategy_battery_v5.py — Wrapper strategy_battery_test sur dataset v5 + ATR-dynamique.

Reutilise les 17 hypothèses (H1-H9 + SA-SH) du strategy_battery_test V2 (15/04),
mais :
  1. Charge ES_dataset_v5.parquet (24m enrichi v4 + labels v5) au lieu de JSONL bruts
  2. Simulator FORWARD avec K_SL=1.5 × ATR_at_entry, K_TP=2.0 × SL, H=60 (cohérent v5)
  3. Compare directement aux ML smoke v5 (PF 1.11 ES BUY = baseline à battre)

Goal : voir si une stratégie trader simple bat le PF 1.11 ML. Si OUI, on a soit :
  - Une feature composite à donner au ML (signal + score)
  - Une règle prod simple (sans ML)
  - Un meta-filter Lopez (le ML primary + meta = strategie trader = filtrage)

Auteur : MIA Trading System V2
Date   : 2026-04-27 19:50
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional, Dict
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Reutilise toutes les fonctions h1-h9 + sa-sh
from strategy_battery_test import (
    h1_vwap_reversion, h2_open_drive, h3_failed_ib, h4_1d_magnetism,
    h5_vah_val_rejet, h6_cvd_divergence, h7_intermarket_divergence,
    h8_ofi_residualized, h9_vpin_filter,
    sa_gex_wall_fade, sb_gex_flip_breakout, sc_delta_div_gex,
    sd_absorption_gex, se_vwap_gex_regime, sf_ib_breakout_gex,
    sg_poc_defense, sh_composite_rotation,
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

HYPOTHESES = [
    ("H1", "VWAP mean reversion (Dalton/Chan)", h1_vwap_reversion),
    ("H2", "Open Drive continuation (Dalton)", h2_open_drive),
    ("H3", "Failed IB Poor High (Crabel)", h3_failed_ib),
    ("H4", "1D Max/Min Magnetism (MenthorQ)", h4_1d_magnetism),
    ("H5", "Rejet VAH/VAL + CVD (Dalton)", h5_vah_val_rejet),
    ("H6", "CVD divergence pure (Trader Dale)", h6_cvd_divergence),
    ("H7", "Intermarket ES/NQ divergence", h7_intermarket_divergence),
    ("H8", "OFI residualise (Cont 2014)", h8_ofi_residualized),
    ("H9", "VPIN regime filter (Easley-Lopez 2012)", h9_vpin_filter),
    ("SA", "GEX Wall Fade (SpotGamma)", sa_gex_wall_fade),
    ("SB", "GEX Flip Breakout (SpotGamma)", sb_gex_flip_breakout),
    ("SC", "Delta Divergence + GEX (Bookmap/Dale)", sc_delta_div_gex),
    ("SD", "Absorption + GEX (Acosta)", sd_absorption_gex),
    ("SE", "VWAP + GEX regime (Chan/SpotGamma)", se_vwap_gex_regime),
    ("SF", "IB Breakout + GEX (Crabel)", sf_ib_breakout_gex),
    ("SG", "POC Defense (Acosta/Dalton)", sg_poc_defense),
    ("SH", "Composite Rotation (Dalton)", sh_composite_rotation),
]


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
    hypothesis: str
    trades: List[TradeResult] = field(default_factory=list)
    n_bars: int = 0
    n_days: int = 0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return sum(1 for t in self.trades if t.won) / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_ticks for t in self.trades)

    @property
    def gross_wins(self) -> float:
        return sum(t.pnl_ticks for t in self.trades if t.won)

    @property
    def gross_losses(self) -> float:
        return abs(sum(t.pnl_ticks for t in self.trades if not t.won))

    @property
    def profit_factor(self) -> float:
        if self.n_trades == 0:
            return float("nan")
        if self.gross_losses <= 0:
            return float("inf") if self.gross_wins > 0 else float("nan")
        return self.gross_wins / self.gross_losses

    @property
    def ev_per_trade(self) -> float:
        return self.total_pnl / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def trades_per_day(self) -> float:
        return self.n_trades / self.n_days if self.n_days > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        cumsum = np.cumsum([t.pnl_ticks for t in self.trades])
        peak = np.maximum.accumulate(cumsum)
        return float((peak - cumsum).max())

    @property
    def sharpe_daily(self) -> float:
        if self.n_trades < 5 or self.n_days < 5:
            return 0.0
        daily: Dict[str, float] = defaultdict(float)
        for t in self.trades:
            if t.date is not None:
                daily[t.date] += t.pnl_ticks
        arr = np.array(list(daily.values()), dtype=float)
        if len(arr) < 5 or arr.std() < 1e-6:
            return 0.0
        return float(arr.mean() / arr.std() * np.sqrt(252.0))


def simulate_forward_v5(df: pd.DataFrame, signal: np.ndarray,
                         hypothesis: str, symbol: str) -> SimResult:
    """Simulator forward ATR-dynamique, cohérent avec labeler v5 et simulate_trades."""
    if "close" not in df.columns or "high" not in df.columns or "low" not in df.columns:
        raise RuntimeError(f"Cols high/low/close manquantes (cols dispo: {list(df.columns)[:20]})")

    closes = df["close"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date.values

    cost = COST_TICKS[symbol]
    trades: List[TradeResult] = []
    last_bar = -COOLDOWN_BARS - 1
    daily_count: Dict[object, int] = {}
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

        # Scan forward
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
            # Time exit MTM
            exit_close = closes[i + HORIZON] if (i + HORIZON) < n else entry
            exit_pnl = (exit_close - entry) / TICK_SIZE * direction - cost

        date_str = str(d) if hasattr(d, "isoformat") else None
        trades.append(TradeResult(
            direction=direction, entry_bar=i, pnl_ticks=float(exit_pnl),
            won=exit_pnl > 0, date=date_str, hit_type=hit_type,
        ))
        last_bar = i
        daily_count[d] = daily_count.get(d, 0) + 1

    return SimResult(hypothesis=hypothesis, trades=trades, n_bars=n, n_days=len(unique_days))


def compute_verdict(sim: SimResult, mc_p: float, pf_lo: float, bh_significant: bool) -> str:
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
        return "CAUTION (not BH signif)"
    if np.isfinite(pf_lo) and pf_lo < 1.0:
        return "CAUTION (PF_lo<1)"
    if sim.profit_factor >= 1.5 and sim.win_rate >= 0.42 and np.isfinite(mc_p) and mc_p <= 0.05:
        return "GO"
    return "CAUTION"


def run_battery_v5(symbol: str) -> List[dict]:
    print(f"\n{'='*70}")
    print(f"  BATTERIE V5 — {symbol}")
    print(f"{'='*70}")

    parquet = ROOT / f"DATA/datasets/{symbol}_dataset_v5.parquet"
    if not parquet.exists():
        raise FileNotFoundError(f"Dataset v5 absent : {parquet}")
    df = pd.read_parquet(parquet)
    n_days = pd.to_datetime(df["ts"], unit="ms").dt.date.nunique()
    print(f"  {len(df):,} barres, {n_days} jours, {df.shape[1]} colonnes")

    # ATR check
    if "atr" not in df.columns:
        raise RuntimeError("Colonne 'atr' manquante dans dataset v5")
    print(f"  ATR median = {df['atr'].median():.2f}t  (SL median ≈ {K_SL*df['atr'].median():.1f}t, TP median ≈ {K_SL*K_TP_RATIO*df['atr'].median():.1f}t)")

    results: List[dict] = []
    for code, name, func in HYPOTHESES:
        try:
            signal = func(df)
        except Exception as e:
            print(f"  [{code}] {name} — ERROR : {type(e).__name__}: {str(e)[:80]}")
            continue

        n_signals = int((signal != 0).sum())
        if n_signals < 10:
            print(f"  [{code}] {name} — {n_signals} signaux (features absentes)")
            results.append({
                "code": code, "name": name, "symbol": symbol,
                "n_signals": n_signals, "n_trades": 0,
                "win_rate": 0.0, "profit_factor": float("nan"),
                "ev_per_trade": 0.0, "sharpe_daily": 0.0,
                "max_dd": 0.0, "trades_day": 0.0, "total_pnl": 0.0,
                "mc_p_value": float("nan"),
                "pf_ci_lo": float("nan"), "pf_ci_hi": float("nan"),
                "verdict": "NO-GO (features/signals)",
                "hit_tp": 0, "hit_sl": 0, "hit_time": 0,
            })
            continue

        sim = simulate_forward_v5(df, signal, f"{code}: {name}", symbol)
        mc_p = mc_permutation_shuffle_order(sim, n_iters=2000)  # 2000 plus rapide que 5000
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
        print(f"  [{code}] sig={n_signals:>6} trades={sim.n_trades:>5} "
              f"WR={sim.win_rate*100:>5.1f}% PF={pf_str:>5} "
              f"EV={sim.ev_per_trade:+5.1f}t Sharpe={sim.sharpe_daily:>5.2f} "
              f"MC={mc_p:.3f} TP/SL/Time={hit_tp}/{hit_sl}/{hit_time}")

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


def generate_report(all_results: List[dict]) -> str:
    lines = ["# Strategy Battery V5 — sur dataset 24m parquet + ATR-dynamique"]
    lines.append("")
    lines.append(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Source** : ES_dataset_v5.parquet + NQ_dataset_v5.parquet (24m, 351K bars)")
    lines.append(f"**Simulator** : forward réel ATR-dynamique K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON}")
    lines.append(f"**Costs** : ES {COST_TICKS['ES']}t, NQ {COST_TICKS['NQ']}t")
    lines.append(f"**Cooldown** : {COOLDOWN_BARS} bars, max {MAX_TRADES_PER_DAY} trades/jour")
    lines.append("")
    lines.append("**Comparaison ML v5** : ES BUY PF=1.11 / ES SELL PF=0.63 (post-fix anti-triche)")
    lines.append("- Stratégie qui bat **PF 1.11** = candidate feature composite ML ou règle prod")
    lines.append("- Stratégie qui bat **PF 1.5** = très probablement vrai edge")
    lines.append("")
    lines.append("## Classement par PF (n_trades >= 30)")
    lines.append("")
    lines.append("| Rang | Code | Hypothèse | Sym | Trades | WR | PF | EV | Sharpe | MC_p | BH | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
    sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
    for rank, r in enumerate(sortable, 1):
        pf = f"{r['profit_factor']:.2f}"
        mc = f"{r['mc_p_value']:.3f}" if np.isfinite(r["mc_p_value"]) else "n/a"
        bh = "✓" if r.get("bh_significant", False) else "✗"
        lines.append(f"| {rank} | {r['code']} | {r['name']} | {r['symbol']} | "
                     f"{r['n_trades']} | {r['win_rate']*100:.1f}% | {pf} | "
                     f"{r['ev_per_trade']:+.1f}t | {r['sharpe_daily']:.2f} | "
                     f"{mc} | {bh} | {r['verdict']} |")
    lines.append("")
    lines.append("## Stratégies non-évaluables (features absentes)")
    lines.append("")
    skipped = [r for r in all_results if r["n_trades"] < 30]
    for r in skipped:
        lines.append(f"- {r['code']} {r['name']} ({r['symbol']}) : {r['n_signals']} signaux, {r['n_trades']} trades")
    return "\n".join(lines)


def main():
    print("=" * 70)
    print("STRATEGY BATTERY V5 — 17 stratégies sur dataset 24m + ATR-dynamique")
    print("=" * 70)
    print(f"  K_SL={K_SL} K_TP={K_TP_RATIO} H={HORIZON} (cohérent labeler v5 + simulate_trades)")
    print(f"  Baseline ML : ES BUY PF 1.11 / ES SELL PF 0.63 (post-fix anti-triche)")

    all_results: List[dict] = []
    for sym in ["ES", "NQ"]:
        try:
            results = run_battery_v5(sym)
            all_results.extend(results)
        except Exception as e:
            print(f"\n[ERROR] {sym} : {type(e).__name__}: {e}")
            continue

    if not all_results:
        print("[ERROR] Aucun résultat")
        return

    out_path = ROOT / "DOCS" / "STRATEGY_BATTERY_V5_REPORT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_report(all_results), encoding="utf-8")
    print(f"\n[SAVED] {out_path}")

    # TOP 10 global
    print("\n" + "=" * 70)
    print("TOP 10 stratégies (PF descendant)")
    print("=" * 70)
    sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
    sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
    for r in sortable[:10]:
        pf = f"{r['profit_factor']:.2f}"
        bh = "✓" if r.get("bh_significant", False) else "✗"
        print(f"  [{r['code']}] {r['symbol']:<2} {r['name'][:40]:<40} | "
              f"trades={r['n_trades']:>5} WR={r['win_rate']*100:>4.1f}% PF={pf} "
              f"EV={r['ev_per_trade']:+5.1f}t Sharpe={r['sharpe_daily']:.2f} BH={bh} | {r['verdict']}")


if __name__ == "__main__":
    main()
