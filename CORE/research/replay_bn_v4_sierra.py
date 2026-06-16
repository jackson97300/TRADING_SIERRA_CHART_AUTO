"""Phase B BN V4 : replay sur sierra_enriched + probe aggressor_imbalance.

Mission : valider que la migration sierra_enriched preserve l'edge BN V4 (PF 4.66
historique sur Databento).

Methode :
  1. Charge tous les JSONL sierra_enriched ES + NQ disponibles
  2. Enrichit chaque bar via sierra_compat (5 features reconstruites)
  3. Applique BNV4Engine.detect_setup() bar par bar (LONG only par defaut)
  4. Pour chaque setup detecte : simulation trade simple (SL fixe initial,
     timeout 90 bars, sortie au prochain hit SL ou TP_estime = sl_ticks * 2 RR)
  5. Reporte stats : N setups par grade, PF approx, distribution aggressor

ATTENTION : ce N'EST PAS un backtest pro (pas de trailing Dow pivot, pas de cost
inclus, pas de walk-forward). C'est un PROBE empirique pour valider :
  - Les features sierra_enriched produisent assez de setups
  - L'edge brut n'a pas explose (PF reste >> 1.0)
  - aggressor_imbalance distribution coherente (seuil 0.5 calibre)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Imports projet
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from CORE.bn_v4_engine import BNV4Engine, BNV4Params
from CORE.bot_bn_v4.sierra_compat import enrich_sierra_bar_for_bn_v4


TICK = {"NQ": 0.25, "ES": 0.25}
USD_PER_TICK = {"NQ": 0.50, "ES": 1.25}  # micros


def load_bars(path: Path) -> list[dict]:
    bars = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    bars.sort(key=lambda b: b.get("ts", 0))
    return bars


def probe_aggressor_distribution(bars: list[dict], sym: str) -> dict:
    """Probe distribution aggressor_imbalance sur les bars."""
    vals = []
    for b in bars:
        v = b.get("aggressor_imbalance")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
    if not vals:
        return {"sym": sym, "n": 0}
    arr = np.array(vals)
    return {
        "sym": sym,
        "n": len(arr),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "pct_above_0.5": float((arr >= 0.5).sum() / len(arr) * 100),
        "pct_below_-0.5": float((arr <= -0.5).sum() / len(arr) * 100),
        "source": next((b.get("_aggressor_source") for b in bars[:5] if b.get("_aggressor_source")), "?"),
    }


def simulate_trade(df: pd.DataFrame, entry_idx: int, sym: str,
                    sl_ticks: int, rr_target: float = 2.0) -> dict:
    """Simulation simple : SL fixe initial + TP = SL * RR_target. Timeout 90 bars."""
    tick = TICK[sym]
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar.get("close") or 0)
    if entry_price <= 0:
        return {"outcome": "INVALID", "pnl_ticks": 0, "bars_held": 0}

    # LONG only
    sl_price = entry_price - sl_ticks * tick
    tp_price = entry_price + sl_ticks * rr_target * tick

    max_hold = min(90, len(df) - entry_idx - 1)
    for k in range(1, max_hold + 1):
        nxt = df.iloc[entry_idx + k]
        nxt_low = float(nxt.get("bar_low") or nxt.get("low") or 0)
        nxt_high = float(nxt.get("bar_high") or nxt.get("high") or 0)
        if nxt_low <= 0 or nxt_high <= 0:
            continue
        if nxt_low <= sl_price:
            return {"outcome": "SL", "pnl_ticks": -sl_ticks, "bars_held": k}
        if nxt_high >= tp_price:
            return {"outcome": "TP", "pnl_ticks": int(sl_ticks * rr_target), "bars_held": k}

    # Timeout : exit au close
    exit_idx = min(entry_idx + max_hold, len(df) - 1)
    exit_price = float(df.iloc[exit_idx].get("close") or entry_price)
    pnl_pts = exit_price - entry_price
    pnl_t = int(round(pnl_pts / tick))
    return {"outcome": "TIMEOUT", "pnl_ticks": pnl_t, "bars_held": max_hold}


def replay_bn_v4_on_sym(sym: str, data_dir: Path, grade_min: str = "A++") -> dict:
    """Replay BN V4 sur tous les jours sierra_enriched du sym."""
    files = sorted(data_dir.glob(f"*_{sym}_sierra_enriched.jsonl"))
    if not files:
        return {"sym": sym, "n_files": 0}

    all_bars = []
    for f in files:
        bars = load_bars(f)
        # Enrich each bar with sierra_compat (in-place)
        for b in bars:
            enrich_sierra_bar_for_bn_v4(b)
        all_bars.extend(bars)
        print(f"  {f.name} : {len(bars)} bars")

    # Build DataFrame from bars
    df = pd.DataFrame(all_bars)
    if df.empty or "close" not in df.columns:
        return {"sym": sym, "n_files": len(files), "error": "empty df"}

    # Setup BNV4Engine
    params = BNV4Params(
        grade_min=grade_min,
        require_open_window=False,  # off pour avoir plus de setups en probe
        require_long_trend_aligned=False,
    )
    engine = BNV4Engine(params)

    # Replay : detect_setup sur fenetre glissante 250 bars
    WINDOW = 250
    trades = []
    grades_seen = Counter()
    setups_total = 0
    last_entry_idx = -120  # cooldown 120 bars entre 2 setups

    print(f"\nReplaying {sym} on {len(df)} bars (window={WINDOW})...")
    for i in range(WINDOW, len(df) - 90):
        if i - last_entry_idx < 120:
            continue
        window = df.iloc[i - WINDOW:i + 1].reset_index(drop=True)
        window_idx = WINDOW  # current bar
        try:
            setup = engine.detect_setup(window, window_idx, direction="long")
        except Exception:
            continue
        if setup is None:
            continue

        setups_total += 1
        grade = setup.get("grade", "?")
        grades_seen[grade] += 1

        if grade != grade_min and grade not in ("A++",):
            continue  # skip si pas le grade requis

        # Simuler trade
        sl_ticks = 14 if sym == "ES" else 25  # SL approximatif
        result = simulate_trade(df, i, sym, sl_ticks=sl_ticks, rr_target=2.0)
        result["grade"] = grade
        result["bar_idx"] = i
        result["ts"] = int(df.iloc[i].get("ts", 0))
        trades.append(result)
        last_entry_idx = i

    # Stats
    n = len(trades)
    if n == 0:
        return {
            "sym": sym, "n_files": len(files), "n_bars": len(df),
            "setups_total": setups_total,
            "grades_distribution": dict(grades_seen),
            "n_trades": 0,
            "msg": f"Aucun trade {grade_min} sur sample",
        }

    wins = [t for t in trades if t["outcome"] == "TP"]
    losses = [t for t in trades if t["outcome"] == "SL"]
    timeouts = [t for t in trades if t["outcome"] == "TIMEOUT"]
    gross_win = sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] > 0)
    gross_loss = abs(sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else 0
    pnl_ticks = sum(t["pnl_ticks"] for t in trades)
    pnl_usd = pnl_ticks * USD_PER_TICK[sym]

    return {
        "sym": sym, "n_files": len(files), "n_bars": len(df),
        "setups_total": setups_total,
        "grades_distribution": dict(grades_seen),
        "grade_min_used": grade_min,
        "n_trades": n,
        "n_tp": len(wins),
        "n_sl": len(losses),
        "n_timeout": len(timeouts),
        "wr_pct": round(len(wins) / n * 100, 1),
        "pf": round(pf, 2) if pf != float("inf") else "inf",
        "pnl_ticks": pnl_ticks,
        "pnl_usd": round(pnl_usd, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="DATA/live_enriched/sierra")
    parser.add_argument("--grade-min", default="A++", choices=["A++", "A", "B", "C"])
    args = parser.parse_args()

    data_root = Path(args.data_dir)

    # Probe aggressor sur 1 jour NQ
    nq_files = sorted((data_root / "NQ").glob("*_NQ_sierra_enriched.jsonl"))
    if nq_files:
        sample_bars = load_bars(nq_files[-1])  # dernier jour
        probe = probe_aggressor_distribution(sample_bars, "NQ")
        print("=" * 72)
        print(f"PROBE aggressor_imbalance NQ ({nq_files[-1].name})")
        print("=" * 72)
        for k, v in probe.items():
            print(f"  {k}: {v}")
        print()

    # Replay BN V4 par sym
    for sym in ["NQ", "ES"]:
        sym_dir = data_root / sym
        if not sym_dir.exists():
            continue
        print("=" * 72)
        print(f"REPLAY BN V4 sur {sym} (grade_min={args.grade_min})")
        print("=" * 72)
        result = replay_bn_v4_on_sym(sym, sym_dir, grade_min=args.grade_min)
        print()
        for k, v in result.items():
            print(f"  {k}: {v}")
        print()


if __name__ == "__main__":
    main()
