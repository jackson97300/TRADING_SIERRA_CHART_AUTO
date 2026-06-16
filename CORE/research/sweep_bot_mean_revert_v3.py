"""Sweep v3 Bot Mean Revert : Intermarket Confirmation (Jackson 16/06/2026).

CONTEXTE :
  Sweep v2 NQ : PF 0.92 sur Asia (insuffisant -> DRY_EVAL_NQ=True en prod)
  Sweep v2 ES : PF 1.69 sur US (validated, NQ rest hypothetical)

HYPOTHESE v3 :
  NQ trade en LIVE avec IntermarketGate : NQ LONG seulement si ES (leader)
  touche un niveau structurel (VWAP_W principal) + bullish bias (bar verte ou
  delta > 0). Symetrique pour SHORT (bar rouge / delta < 0).

  Hypothese empirique forte : ce filtre supprime les signaux NQ isoles
  non-confirmes par ES et pousse PF NQ vers >= 1.20.

USAGE :
  python -X utf8 -m CORE.research.sweep_bot_mean_revert_v3 --sym NQ
  python -X utf8 -m CORE.research.sweep_bot_mean_revert_v3 --sym ES

DESIGN :
  - Aligne bars ES + NQ par bar_ts (ts) pour utiliser ES comme leader de NQ
  - Compare PF NQ AVEC vs SANS intermarket filter (A/B test sur meme sample)
  - Test plusieurs proximity thresholds (0.05, 0.10, 0.15, 0.20, 0.30%)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from CORE.research.sweep_bot_mean_revert_v2 import (
    SL_TICKS_BY_SYM,
    TICK_BY_SYM,
    USD_PER_TICK,
    backtest_config,
    detect_mean_revert_signal,
    load_bars,
    simulate_trade,
    _f,
    _i,
    _b,
)


# Reuse LEADER_LEVELS depuis gate (source unique de verite)
from CORE.bot_mean_revert.gates.intermarket import LEADER_LEVELS


def index_leader_bars_by_ts(leader_bars: list[dict]) -> dict[int, dict]:
    """Index les bars leader par ts pour lookup O(1)."""
    out: dict[int, dict] = {}
    for b in leader_bars:
        ts = b.get("ts")
        if ts is not None:
            try:
                out[int(ts)] = b
            except (TypeError, ValueError):
                continue
    return out


def find_leader_bar_at_or_before(
    leader_idx: dict[int, dict],
    target_ts: int,
    max_lookback_ms: int = 120_000,
) -> Optional[dict]:
    """Trouve la bar leader la plus proche <= target_ts (max 2 min lookback).

    Strategie : on cherche d'abord exact match, sinon on scan
    target_ts, target_ts-60s, target_ts-120s (bars 1 min sierra_enriched).
    """
    # Exact match (cas le plus frequent : bars sync minute par minute)
    if target_ts in leader_idx:
        return leader_idx[target_ts]
    # Scan a rebours par tranches de 1 sec jusqu'a max_lookback
    # (pour donnees avec ts non aligne pile minute)
    for delta in range(1, max_lookback_ms + 1, 1000):
        candidate_ts = target_ts - delta
        if candidate_ts in leader_idx:
            return leader_idx[candidate_ts]
    return None


def intermarket_confirm(
    leader_bar: Optional[dict],
    direction: str,
    proximity_thr_pct: float,
) -> tuple[bool, str]:
    """Reproduit IntermarketGate.confirm() sans dependre du config dataclass.

    Returns: (allowed, reason)
    """
    if leader_bar is None:
        return False, "leader_bar_missing"

    nearest_level: Optional[str] = None
    nearest_dist: float = float("inf")
    for col, name in LEADER_LEVELS:
        d_raw = leader_bar.get(col)
        if d_raw is None:
            continue
        try:
            d = float(d_raw)
        except (TypeError, ValueError):
            continue
        d_abs = abs(d)
        if d_abs <= proximity_thr_pct and d_abs < nearest_dist:
            nearest_level = name
            nearest_dist = d_abs

    if nearest_level is None:
        return False, "leader_no_level_proximity"

    delta_bar = _f(leader_bar.get("delta_bar"))
    bar_color_up = _i(leader_bar.get("bar_color_up"))
    bar_color_dn = _i(leader_bar.get("bar_color_dn"))

    if direction == "LONG":
        bullish = (bar_color_up == 1) or (delta_bar > 0)
        if bullish:
            return True, f"leader@{nearest_level}+bullish"
        return False, f"leader@{nearest_level}_no_bullish_bias"
    if direction == "SHORT":
        bearish = (bar_color_dn == 1) or (delta_bar < 0)
        if bearish:
            return True, f"leader@{nearest_level}+bearish"
        return False, f"leader@{nearest_level}_no_bearish_bias"
    return False, f"unknown_direction:{direction}"


def backtest_with_intermarket(
    bars: list[dict],
    leader_idx: Optional[dict[int, dict]],
    sym: str,
    *,
    sd_threshold_pct: float,
    rvol_zscore_min: float,
    require_exhaustion: bool,
    require_delta_direction: bool,
    rr: float,
    sd_level: str,
    cooldown_bars: int = 30,
    regime_filter_mode: str = "off",
    skip_london: bool = False,
    skip_preopen_us: bool = False,
    trend_day_max: float = 1.0,
    vix_min_for_short: float = 0.0,
    intermarket_enabled: bool = False,
    intermarket_proximity_pct: float = 0.10,
) -> dict:
    """Identique a backtest_config v2 + filtre intermarket optionnel."""
    trades = []
    last_entry_idx = -cooldown_bars
    n_blocked_by_intermarket = 0
    intermarket_block_reasons: dict[str, int] = defaultdict(int)

    for i, bar in enumerate(bars):
        if i - last_entry_idx < cooldown_bars:
            continue
        side = detect_mean_revert_signal(
            bar,
            sd_threshold_pct=sd_threshold_pct,
            rvol_zscore_min=rvol_zscore_min,
            require_exhaustion=require_exhaustion,
            require_delta_direction=require_delta_direction,
            use_sd_level=sd_level,
            regime_filter_mode=regime_filter_mode,
            skip_london=skip_london,
            skip_preopen_us=skip_preopen_us,
            trend_day_max=trend_day_max,
            vix_min_for_short=vix_min_for_short,
        )
        if side is None:
            continue

        # NOUVEAU : filtre intermarket
        if intermarket_enabled and leader_idx is not None:
            bar_ts = bar.get("ts", 0)
            try:
                bar_ts_int = int(bar_ts)
            except (TypeError, ValueError):
                bar_ts_int = 0
            leader_bar = find_leader_bar_at_or_before(leader_idx, bar_ts_int)
            ok, reason = intermarket_confirm(leader_bar, side, intermarket_proximity_pct)
            if not ok:
                n_blocked_by_intermarket += 1
                intermarket_block_reasons[reason] += 1
                continue  # Skip ce signal

        result = simulate_trade(i, side, bars, sym, rr)
        result["side"] = side
        result["session_id"] = bar.get("session_id", "?")
        trades.append(result)
        last_entry_idx = i

    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "n_blocked_intermarket": n_blocked_by_intermarket,
            "intermarket_block_reasons": dict(intermarket_block_reasons),
        }
    wins = [t for t in trades if t["outcome"] == "TP"]
    losses = [t for t in trades if t["outcome"] == "SL"]
    timeouts = [t for t in trades if t["outcome"] == "TIMEOUT"]
    pnl_ticks = sum(t["pnl_ticks"] for t in trades)
    pnl_usd = pnl_ticks * USD_PER_TICK[sym]
    gross_win = sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] > 0)
    gross_loss = abs(sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0)
    wr = len(wins) / n * 100

    by_sess = defaultdict(int)
    by_sess_pnl = defaultdict(int)
    by_side = defaultdict(int)
    by_side_pnl = defaultdict(int)
    for t in trades:
        by_sess[t["session_id"]] += 1
        by_sess_pnl[t["session_id"]] += t["pnl_ticks"]
        by_side[t["side"]] += 1
        by_side_pnl[t["side"]] += t["pnl_ticks"]

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
        "by_session_pnl": dict(by_sess_pnl),
        "by_side": dict(by_side),
        "by_side_pnl": dict(by_side_pnl),
        "n_blocked_intermarket": n_blocked_by_intermarket,
        "intermarket_block_reasons": dict(intermarket_block_reasons),
    }


def _print_result_row(label: str, r: dict, sym: str) -> None:
    if r["n_trades"] == 0:
        print(f"  [{label}] n=0 trades (blocked_inter={r.get('n_blocked_intermarket', 0)})")
        return
    print(
        f"  [{label}] n={r['n_trades']:3d} "
        f"WR={r['wr_pct']:5.1f}% PF={r['pf']:5.2f} "
        f"pnl={r['pnl_ticks']:+5d}t ${r['pnl_usd']:+7.0f} "
        f"blocked_inter={r.get('n_blocked_intermarket', 0)}"
    )
    if "by_session" in r:
        sess_str = ", ".join(f"{s}:{n}" for s, n in r["by_session"].items())
        print(f"        sessions: {sess_str}")
    if "by_side" in r:
        side_str = ", ".join(f"{s}:{n}" for s, n in r["by_side"].items())
        print(f"        sides:    {side_str}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sym", required=True, choices=["ES", "NQ"])
    parser.add_argument("--data-dir", default="DATA/live_enriched/sierra")
    parser.add_argument("--proximity-grid",
                        default="0.05,0.10,0.15,0.20,0.30",
                        help="Comma-separated proximity thresholds % (default 0.05,0.10,0.15,0.20,0.30)")
    args = parser.parse_args()

    sym = args.sym
    data_dir = Path(args.data_dir) / sym

    files = sorted(data_dir.glob("*_sierra_enriched.jsonl"))
    if not files:
        print(f"NO files in {data_dir}")
        return

    print(f"=== {sym} v3 (Intermarket Confirmation) : {len(files)} fichiers ===")
    all_bars = []
    for f in files:
        bars = load_bars(f)
        print(f"  {f.name} : {len(bars)} bars")
        all_bars.extend(bars)
    print(f"Total bars {sym} : {len(all_bars)}")
    print()

    # Charger le leader (ES si on teste NQ, sinon NQ pour symetrie)
    leader_sym = "ES" if sym == "NQ" else "NQ"
    leader_dir = Path(args.data_dir) / leader_sym
    leader_files = sorted(leader_dir.glob("*_sierra_enriched.jsonl"))
    leader_idx: Optional[dict[int, dict]] = None
    if leader_files:
        leader_bars = []
        for f in leader_files:
            leader_bars.extend(load_bars(f))
        leader_idx = index_leader_bars_by_ts(leader_bars)
        print(f"Leader {leader_sym} : {len(leader_bars)} bars indexed ({len(leader_idx)} unique ts)")
    else:
        print(f"WARNING : pas de leader {leader_sym} dispo, intermarket gate inactif")
    print()

    # Config canonique v2 best per symbol
    if sym == "ES":
        cfg_v2 = dict(
            sd_threshold_pct=0.0,
            rvol_zscore_min=0.0,
            require_exhaustion=False,
            require_delta_direction=False,
            rr=1.5,
            sd_level="sd3",
            regime_filter_mode="trend_align_es",
            skip_london=True,
            skip_preopen_us=True,
            trend_day_max=1.0,
            vix_min_for_short=20.0,
        )
        print("CONFIG ES : trend_align_es | skip_london=True | skip_preopen=True | vix>20 SHORT")
    elif sym == "NQ":
        cfg_v2 = dict(
            sd_threshold_pct=0.0,
            rvol_zscore_min=0.0,
            require_exhaustion=False,
            require_delta_direction=False,
            rr=1.5,
            sd_level="sd3",
            regime_filter_mode="contrarian_nq",
            skip_london=False,
            skip_preopen_us=False,
            trend_day_max=0.65,
            vix_min_for_short=0.0,
        )
        print("CONFIG NQ : contrarian_nq | Asia+London OK | trend_day_max=0.65")
    print()

    # === BASELINE : sans intermarket gate (= sweep v2 baseline) ===
    print(f"=== BASELINE {sym} (SANS IntermarketGate) ===")
    res_baseline = backtest_with_intermarket(
        all_bars, leader_idx, sym,
        **cfg_v2,
        intermarket_enabled=False,
    )
    _print_result_row("baseline", res_baseline, sym)
    print()

    # === AVEC intermarket gate : grid de proximity ===
    proximity_grid = [float(x) for x in args.proximity_grid.split(",")]
    print(f"=== AVEC IntermarketGate (grid proximity %) ===")
    results_inter = []
    for prox in proximity_grid:
        res = backtest_with_intermarket(
            all_bars, leader_idx, sym,
            **cfg_v2,
            intermarket_enabled=True,
            intermarket_proximity_pct=prox,
        )
        _print_result_row(f"prox={prox:.2f}%", res, sym)
        results_inter.append((prox, res))
    print()

    # === COMPARAISON ===
    print(f"=== A/B SUMMARY {sym} ===")
    n_base = res_baseline.get("n_trades", 0)
    pf_base = res_baseline.get("pf", 0.0)
    print(f"baseline                : n={n_base:3d} PF={pf_base:5.2f} pnl=${res_baseline.get('pnl_usd', 0):+7.0f}")
    for prox, r in results_inter:
        n_r = r.get("n_trades", 0)
        pf_r = r.get("pf", 0.0)
        pf_delta = pf_r - pf_base
        n_delta = n_r - n_base
        print(
            f"intermarket prox={prox:.2f}% : n={n_r:3d} (vs base {n_delta:+d}) "
            f"PF={pf_r:5.2f} (delta {pf_delta:+.2f}) "
            f"pnl=${r.get('pnl_usd', 0):+7.0f}"
        )
        blocks = r.get("intermarket_block_reasons", {})
        if blocks:
            top_reasons = sorted(blocks.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"  Top block reasons : {top_reasons}")

    print()
    # Best config interpretation
    best = max(results_inter, key=lambda x: x[1].get("pf", 0.0))
    best_prox, best_r = best
    print(f"=== VERDICT {sym} ===")
    if best_r.get("n_trades", 0) < 5:
        print(f"  Best prox={best_prox:.2f}% mais n={best_r.get('n_trades', 0)} insuffisant")
    else:
        verdict = "GO (PF >= 1.20)" if best_r.get("pf", 0.0) >= 1.20 else "MARGINAL"
        print(
            f"  Best prox={best_prox:.2f}% : n={best_r.get('n_trades', 0)} "
            f"PF={best_r.get('pf', 0.0):.2f} -> {verdict}"
        )


if __name__ == "__main__":
    main()
