"""Sweep parametres Bot Confluence (zones color/long + volume confirmation).

Cadrage 16/06/2026 : Jackson trade ces confluences en manuel avec succes.
Avant deploy paper Sim1, sweep rapide sur 4-6 jours sierra_enriched pour
trouver des parametres RAISONNABLES par indice (ES/NQ).

ATTENTION : n<100/bucket = INDICATIF, pas statistique (cf
feedback_data_mining_trap.md). Resultats a prendre comme "ordre de grandeur"
pas comme "edge prouve". Validation reelle = paper Sim1 14+ jours minimum.

Logique testee :
  Entry LONG :
    1. dist_color_up_nearest_pct AND/OR dist_long_up_nearest_pct dans buffer
    2. n_color_up_cluster_within_0_2pct + n_long_up_cluster_within_0_2pct >= confluence_min
    3. delta_bar > 0 AND rvol >= rvol_min AND finish_strength > 0
  Symetrique SHORT.

Simulation TP/SL :
  SL fixe ticks (15 ES / 25 NQ), TP = SL * RR
  Cherche dans les N bars suivantes lequel touche le premier
  Sortie : "TP" / "SL" / "TIMEOUT" (apres MAX_BARS)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from itertools import product
from pathlib import Path
from typing import Optional


TICK_BY_SYM = {"ES": 0.25, "NQ": 0.25, "MGC": 0.10}
USD_PER_TICK = {"ES": 1.25, "NQ": 0.50, "MGC": 1.00}

# SL fixe par sym (calibre largeur typique zone)
SL_TICKS_BY_SYM = {"ES": 12, "NQ": 25, "MGC": 30}

MAX_BARS_HOLD = 60  # 1h


def _safe_float(x, default=0.0):
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _safe_int(x, default=0):
    if x is None:
        return default
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def load_bars(path: Path) -> list[dict]:
    """Charge toutes les bars d'un JSONL."""
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


def detect_signal(
    bar: dict,
    *,
    buffer_pct: float,
    confluence_min: int,
    rvol_min: float,
    require_bar_confirmation: bool = False,
) -> Optional[str]:
    """Retourne 'LONG' / 'SHORT' / None si pas de signal sur cette bar."""
    # Distances aux zones (dist_*_nearest_pct sont en POURCENT)
    d_color_up = _safe_float(bar.get("dist_color_up_nearest_pct"))
    d_color_dn = _safe_float(bar.get("dist_color_dn_nearest_pct"))
    d_long_up = _safe_float(bar.get("dist_long_up_nearest_pct"))
    d_long_dn = _safe_float(bar.get("dist_long_dn_nearest_pct"))

    # Confluence count (n zones dans 0.2% du prix)
    n_color_up = _safe_int(bar.get("n_color_up_cluster_within_0_2pct"))
    n_color_dn = _safe_int(bar.get("n_color_dn_cluster_within_0_2pct"))
    n_long_up = _safe_int(bar.get("n_long_up_cluster_within_0_2pct"))
    n_long_dn = _safe_int(bar.get("n_long_dn_cluster_within_0_2pct"))

    # Volume / delta confirmation
    delta_bar = _safe_float(bar.get("delta_bar"))
    rvol = _safe_float(bar.get("rvol"))
    finish_strength = _safe_float(bar.get("finish_strength"))
    bar_color_up = _safe_int(bar.get("bar_color_up"))
    bar_color_dn = _safe_int(bar.get("bar_color_dn"))

    if rvol < rvol_min:
        return None

    # LONG : proche zone color_up OR long_up + confluence
    long_at_zone = (
        (d_color_up is not None and 0 < d_color_up <= buffer_pct) or
        (d_long_up is not None and 0 < d_long_up <= buffer_pct)
    )
    long_confluence = (n_color_up + n_long_up) >= confluence_min
    long_volume_ok = delta_bar > 0 and finish_strength > 0
    long_bar_ok = (bar_color_up == 1) if require_bar_confirmation else True

    if long_at_zone and long_confluence and long_volume_ok and long_bar_ok:
        return "LONG"

    # SHORT : symetrique
    short_at_zone = (
        (d_color_dn is not None and -buffer_pct <= d_color_dn < 0) or
        (d_long_dn is not None and -buffer_pct <= d_long_dn < 0)
    )
    short_confluence = (n_color_dn + n_long_dn) >= confluence_min
    short_volume_ok = delta_bar < 0 and finish_strength < 0
    short_bar_ok = (bar_color_dn == 1) if require_bar_confirmation else True

    if short_at_zone and short_confluence and short_volume_ok and short_bar_ok:
        return "SHORT"

    return None


def simulate_trade(
    entry_idx: int, side: str, bars: list[dict], sym: str, rr: float
) -> dict:
    """Simule TP/SL sur bars suivantes. Returns dict {outcome, pnl_ticks, bars_held}."""
    tick = TICK_BY_SYM[sym]
    sl_ticks = SL_TICKS_BY_SYM[sym]
    tp_ticks = int(round(sl_ticks * rr))

    entry_bar = bars[entry_idx]
    entry_price = _safe_float(entry_bar.get("close"))
    if entry_price <= 0:
        return {"outcome": "INVALID", "pnl_ticks": 0, "bars_held": 0}

    if side == "LONG":
        sl_price = entry_price - sl_ticks * tick
        tp_price = entry_price + tp_ticks * tick
    else:
        sl_price = entry_price + sl_ticks * tick
        tp_price = entry_price - tp_ticks * tick

    for k in range(1, min(MAX_BARS_HOLD + 1, len(bars) - entry_idx)):
        nxt = bars[entry_idx + k]
        nxt_high = _safe_float(nxt.get("bar_high")) or _safe_float(nxt.get("high"))
        nxt_low = _safe_float(nxt.get("bar_low")) or _safe_float(nxt.get("low"))
        if nxt_high <= 0 or nxt_low <= 0:
            continue

        if side == "LONG":
            # SL hit ?
            if nxt_low <= sl_price:
                return {"outcome": "SL", "pnl_ticks": -sl_ticks, "bars_held": k}
            # TP hit ?
            if nxt_high >= tp_price:
                return {"outcome": "TP", "pnl_ticks": tp_ticks, "bars_held": k}
        else:
            if nxt_high >= sl_price:
                return {"outcome": "SL", "pnl_ticks": -sl_ticks, "bars_held": k}
            if nxt_low <= tp_price:
                return {"outcome": "TP", "pnl_ticks": tp_ticks, "bars_held": k}

    # TIMEOUT : sortie au close MAX_BARS_HOLD
    exit_idx = min(entry_idx + MAX_BARS_HOLD, len(bars) - 1)
    exit_price = _safe_float(bars[exit_idx].get("close"))
    if exit_price <= 0:
        return {"outcome": "TIMEOUT", "pnl_ticks": 0, "bars_held": MAX_BARS_HOLD}
    pnl_pts = (exit_price - entry_price) if side == "LONG" else (entry_price - exit_price)
    pnl_t = int(round(pnl_pts / tick))
    return {"outcome": "TIMEOUT", "pnl_ticks": pnl_t, "bars_held": MAX_BARS_HOLD}


def backtest_config(
    bars: list[dict], sym: str, *, buffer_pct, confluence_min, rvol_min,
    rr, require_bar_confirmation, cooldown_bars=30,
) -> dict:
    """Run un backtest avec ces parametres."""
    trades = []
    last_entry_idx = -cooldown_bars
    for i, bar in enumerate(bars):
        if i - last_entry_idx < cooldown_bars:
            continue
        side = detect_signal(
            bar,
            buffer_pct=buffer_pct,
            confluence_min=confluence_min,
            rvol_min=rvol_min,
            require_bar_confirmation=require_bar_confirmation,
        )
        if side is None:
            continue
        result = simulate_trade(i, side, bars, sym, rr)
        result["side"] = side
        result["session_id"] = bar.get("session_id", "?")
        result["entry_bar_ts"] = bar.get("ts", 0)
        trades.append(result)
        last_entry_idx = i

    # Stats
    n = len(trades)
    if n == 0:
        return {"n_trades": 0}
    wins = [t for t in trades if t["outcome"] == "TP"]
    losses = [t for t in trades if t["outcome"] == "SL"]
    timeouts = [t for t in trades if t["outcome"] == "TIMEOUT"]
    pnl_ticks = sum(t["pnl_ticks"] for t in trades)
    pnl_usd = pnl_ticks * USD_PER_TICK[sym]
    gross_win = sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] > 0)
    gross_loss = abs(sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else 0
    wr = len(wins) / n * 100

    # Distribution par session
    by_sess = defaultdict(int)
    for t in trades:
        by_sess[t["session_id"]] += 1

    return {
        "n_trades": n,
        "n_tp": len(wins),
        "n_sl": len(losses),
        "n_timeout": len(timeouts),
        "wr_pct": wr,
        "pf": pf,
        "pnl_ticks": pnl_ticks,
        "pnl_usd": pnl_usd,
        "by_session": dict(by_sess),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sym", required=True, choices=["ES", "NQ", "MGC"])
    parser.add_argument("--data-dir", default="DATA/live_enriched/sierra")
    args = parser.parse_args()

    sym = args.sym
    data_dir = Path(args.data_dir) / sym
    files = sorted(data_dir.glob("*_sierra_enriched.jsonl"))
    if not files:
        print(f"NO files in {data_dir}")
        return

    print(f"=== {sym} : {len(files)} fichiers ===")
    all_bars = []
    for f in files:
        bars = load_bars(f)
        print(f"  {f.name} : {len(bars)} bars")
        all_bars.extend(bars)
    print(f"Total bars : {len(all_bars)}")
    print()

    # Sweep
    buffer_grid = [0.05, 0.10, 0.15]  # %
    confluence_grid = [2, 3, 4]
    rvol_grid = [1.0, 1.2, 1.5]
    rr_grid = [1.5]
    bar_conf_grid = [False, True]

    results = []
    for bf, cf, rv, rr, bc in product(buffer_grid, confluence_grid, rvol_grid, rr_grid, bar_conf_grid):
        stats = backtest_config(
            all_bars, sym,
            buffer_pct=bf, confluence_min=cf, rvol_min=rv,
            rr=rr, require_bar_confirmation=bc,
        )
        if stats["n_trades"] == 0:
            continue
        results.append({
            "buffer_pct": bf, "confluence_min": cf, "rvol_min": rv,
            "rr": rr, "bar_conf": bc,
            **stats,
        })

    # Tri par PF * sqrt(n) pour balance qualite/volume
    results.sort(key=lambda r: r["pf"] * (r["n_trades"] ** 0.5), reverse=True)

    print(f"=== Top 10 configs {sym} (tri PF * sqrt(n)) ===")
    print(f"{'buf%':>5} {'conf':>4} {'rvol':>5} {'rr':>4} {'bc':>3} | {'n':>4} {'WR%':>5} {'PF':>5} {'pnl_t':>7} {'pnl_$':>9} sessions")
    print("-" * 110)
    for r in results[:10]:
        sess_str = ", ".join(f"{s}:{n}" for s, n in r["by_session"].items())
        print(
            f"{r['buffer_pct']:5.2f} {r['confluence_min']:4d} {r['rvol_min']:5.2f} "
            f"{r['rr']:4.1f} {str(r['bar_conf'])[0]:>3} | "
            f"{r['n_trades']:4d} {r['wr_pct']:5.1f} {r['pf']:5.2f} "
            f"{r['pnl_ticks']:7d} ${r['pnl_usd']:8.0f} {sess_str}"
        )


if __name__ == "__main__":
    main()
