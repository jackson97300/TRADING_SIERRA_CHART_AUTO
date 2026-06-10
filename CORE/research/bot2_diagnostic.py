"""bot2_diagnostic.py — Diagnostic Bot 2 BN V4 (audit Etape 1).

Repond aux 3 questions :
1. Les setups grade A++ / A historiques NQ auraient-ils ete profitables en mode TRADE ?
2. La config asymetrique require_long_trend_aligned (SHORT only) cause-t-elle des manques d'opportunites SHORT ?
3. Pourquoi 0 setup detecte sur les downmoves brutaux (Asia dumps, conditions Wyckoff Phase D) ?

Approche : rejouer le moteur BN V4 sur le parquet V4 enriched (NQ, jan-mai 2026),
simuler les trades avec SL=20t / TP=R2.0 / trailing BE +1R / timeout 90 bars.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Path injection pour imports CORE
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v4_engine import (
    BNV4Engine, BNV4Params, TrailingState,
    GRADE_THRESHOLDS, OPEN_WINDOWS_MIN_ET,
)


def load_nq_data() -> pd.DataFrame:
    """Charge tous les parquets NQ disponibles, concatenes par ts_event."""
    base = ROOT / "DATA/datasets/v4_enriched/symbol=NQ.c.0"
    parts = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            pq = month_dir / "data.parquet"
            if pq.exists():
                df = pd.read_parquet(pq)
                parts.append(df)
                print(f"  Loaded {year_dir.name}/{month_dir.name}: {len(df)} bars")
    df = pd.concat(parts, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    print(f"Total bars: {len(df)} | range: {df['ts_event'].min()} -> {df['ts_event'].max()}")
    return df


def simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    sl_ticks: int = 20,
    rr: float = 2.0,
    trailing_be_R: float = 1.0,
    timeout_bars: int = 90,
    tick_size: float = 0.25,
) -> dict:
    """Simule un trade simple: SL fixe / TP R:R / trailing BE a +1R / timeout.

    Returns dict { exit_idx, exit_cause, pnl_R, pnl_ticks, duration_bars }.
    """
    entry = df.iloc[entry_idx]
    entry_price = entry["close"]
    sl_offset = sl_ticks * tick_size
    if direction == "long":
        sl = entry_price - sl_offset
        tp = entry_price + sl_offset * rr
        be_trigger = entry_price + sl_offset * trailing_be_R
    else:
        sl = entry_price + sl_offset
        tp = entry_price - sl_offset * rr
        be_trigger = entry_price - sl_offset * trailing_be_R

    be_active = False
    for j in range(entry_idx + 1, min(entry_idx + 1 + timeout_bars, len(df))):
        bar = df.iloc[j]
        h, l = bar["high"], bar["low"]

        if direction == "long":
            # BE trailing
            if not be_active and h >= be_trigger:
                sl = entry_price  # BE
                be_active = True
            # SL hit ?
            if l <= sl:
                pnl_ticks = (sl - entry_price) / tick_size
                return {
                    "exit_idx": j, "exit_cause": "be" if be_active else "sl",
                    "pnl_R": pnl_ticks / sl_ticks,
                    "pnl_ticks": pnl_ticks,
                    "duration_bars": j - entry_idx,
                }
            # TP hit ?
            if h >= tp:
                pnl_ticks = (tp - entry_price) / tick_size
                return {
                    "exit_idx": j, "exit_cause": "tp",
                    "pnl_R": pnl_ticks / sl_ticks,
                    "pnl_ticks": pnl_ticks,
                    "duration_bars": j - entry_idx,
                }
        else:  # short
            if not be_active and l <= be_trigger:
                sl = entry_price
                be_active = True
            if h >= sl:
                pnl_ticks = (entry_price - sl) / tick_size
                return {
                    "exit_idx": j, "exit_cause": "be" if be_active else "sl",
                    "pnl_R": pnl_ticks / sl_ticks,
                    "pnl_ticks": pnl_ticks,
                    "duration_bars": j - entry_idx,
                }
            if l <= tp:
                pnl_ticks = (entry_price - tp) / tick_size
                return {
                    "exit_idx": j, "exit_cause": "tp",
                    "pnl_R": pnl_ticks / sl_ticks,
                    "pnl_ticks": pnl_ticks,
                    "duration_bars": j - entry_idx,
                }
    # timeout
    last = df.iloc[min(entry_idx + timeout_bars, len(df) - 1)]
    if direction == "long":
        pnl_ticks = (last["close"] - entry_price) / tick_size
    else:
        pnl_ticks = (entry_price - last["close"]) / tick_size
    return {
        "exit_idx": entry_idx + timeout_bars, "exit_cause": "timeout",
        "pnl_R": pnl_ticks / sl_ticks,
        "pnl_ticks": pnl_ticks,
        "duration_bars": timeout_bars,
    }


def scan_setups(df: pd.DataFrame, params: BNV4Params, direction: str) -> list[dict]:
    """Scan le dataframe et detecte tous les setups BN V4 valides."""
    engine = BNV4Engine(params)
    setups = []
    # Walk-forward: pour chaque bar i, fournir df.iloc[:i+1] = window causal
    # Mais c'est trop lent. On utilise une window glissante de 300 bars.
    WINDOW = 300
    min_i = max(WINDOW, params.trend_long_lookback + 5)
    for i in range(min_i, len(df)):
        window = df.iloc[i - WINDOW:i + 1].copy().reset_index(drop=True)
        local_idx = len(window) - 1
        try:
            setup = engine.detect_setup(window, local_idx, direction=direction)
        except Exception:
            continue
        if setup is not None:
            # Convertir local_idx back to global idx
            global_idx = i
            setup["global_idx"] = global_idx
            setup["ts_event"] = df.iloc[global_idx]["ts_event"]
            setups.append(setup)
    return setups


def run_diagnostic():
    """Diagnostic complet : scan setups + simulation trades."""
    print("=" * 60)
    print("DIAGNOSTIC BOT 2 BN V4 — Etape 1")
    print("=" * 60)
    df = load_nq_data()

    # Garder cols essentielles pour vitesse
    print("\n[1/4] Filtrage bars trading sessions...")
    print(f"  Bars total: {len(df)}")

    # Config Jackson actuelle
    configs = {
        "A++_strict": BNV4Params(grade_min="A++", observation_grade_min=None,
                                 require_open_window=True,
                                 require_long_trend_aligned=True),
        "A_observe": BNV4Params(grade_min="A", observation_grade_min=None,
                                require_open_window=True,
                                require_long_trend_aligned=True),
        "A_no_trend_filter": BNV4Params(grade_min="A", observation_grade_min=None,
                                        require_open_window=True,
                                        require_long_trend_aligned=False),
        "A_no_window": BNV4Params(grade_min="A", observation_grade_min=None,
                                  require_open_window=False,
                                  require_long_trend_aligned=False),
    }

    results = {}

    for name, params in configs.items():
        print(f"\n[2/4] Config {name}: scan SHORT setups...")
        setups_short = scan_setups(df, params, "short")
        print(f"  SHORT setups detected: {len(setups_short)}")

        print(f"[2/4] Config {name}: scan LONG setups...")
        setups_long = scan_setups(df, params, "long")
        print(f"  LONG setups detected: {len(setups_long)}")

        # Simulation trades
        all_setups = [(s, "short") for s in setups_short] + [(s, "long") for s in setups_long]
        trades = []
        for s, d in all_setups:
            sim = simulate_trade(df, s["global_idx"], d, sl_ticks=20, rr=2.0)
            sim["ts_event"] = s["ts_event"]
            sim["direction"] = d
            sim["grade"] = s.get("grade", "?")
            sim["density"] = s.get("density", 0)
            trades.append(sim)

        if trades:
            pnls = [t["pnl_R"] for t in trades]
            wins = [t for t in trades if t["pnl_R"] > 0]
            losses = [t for t in trades if t["pnl_R"] <= 0]
            sum_wins = sum(t["pnl_R"] for t in wins)
            sum_losses = -sum(t["pnl_R"] for t in losses) if losses else 1e-9
            pf = sum_wins / sum_losses if sum_losses > 0 else float("inf")

            wr = len(wins) / len(trades) * 100
            ev_R = np.mean(pnls)
            ev_ticks = ev_R * 20
            results[name] = {
                "n_setups_short": len(setups_short),
                "n_setups_long": len(setups_long),
                "n_trades": len(trades),
                "wr": wr,
                "ev_R": ev_R,
                "ev_ticks": ev_ticks,
                "pf": pf,
                "sum_R": sum(pnls),
                "median_R": np.median(pnls),
            }
            print(f"  -> trades={len(trades)} WR={wr:.1f}% EV={ev_R:+.2f}R PF={pf:.2f}")
        else:
            results[name] = {
                "n_setups_short": 0, "n_setups_long": 0, "n_trades": 0,
                "wr": 0, "ev_R": 0, "ev_ticks": 0, "pf": 0, "sum_R": 0, "median_R": 0,
            }
            print(f"  -> 0 trades")

    print("\n" + "=" * 60)
    print("RESULTAT DIAGNOSTIC")
    print("=" * 60)
    for name, r in results.items():
        print(f"\n{name}:")
        for k, v in r.items():
            print(f"  {k}: {v}")

    # Sauvegarde
    out = ROOT / "LOGS/bot2_research/diagnostic_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out}")
    return results


if __name__ == "__main__":
    run_diagnostic()
