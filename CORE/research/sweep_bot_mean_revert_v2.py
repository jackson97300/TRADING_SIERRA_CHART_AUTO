"""Sweep parametres Bot Mean Reversion VWAP.

Jackson 16/06/2026 : "Mean Reversion est celui qui m'a donne le meilleur
[resultat] depuis que j'ai commence avec les bots."

Logique testee :
  Entry LONG (reversion bullish depuis extension basse) :
    1. dist_vwap_d_sd2d_pct <= -sd_threshold (prix sous SD2d extension extreme)
    2. RVOL_zscore >= rvol_min (volume capitulation)
    3. (optionnel) ctx_climax_signal OR ctx_failed_auction (exhaustion vendeur)
    4. delta_bar > 0 (acheteurs reviennent)
  Entry SHORT symetrique sur SD2u (extension haute).

Simulation TP/SL :
  SL fixe ticks (20 ES / 35 NQ) calibre tight pour mean revert
  TP = SL * RR

ATTENTION : 4-6 jours data = INDICATIF, pas statistique. Mais les extensions
SD bands se touchent ~5-15 fois/jour/sym = sample plus large que confluence
zones (~1-10 fois/jour) donc resultat plus signal/noise.

Ref academique : Andersen-Bollerslev 1998, Hong-Stein 1999, Lo-Mamaysky-Wang 2000.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional


TICK_BY_SYM = {"ES": 0.25, "NQ": 0.25, "MGC": 0.10}
USD_PER_TICK = {"ES": 1.25, "NQ": 0.50, "MGC": 1.00}

# SL calibre mean revert tight (extension SD3 = SL logique)
SL_TICKS_BY_SYM = {"ES": 20, "NQ": 35, "MGC": 50}

MAX_BARS_HOLD = 60


def _f(x, default=0.0):
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x, default=0):
    if x is None:
        return default
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _b(x):
    if x is True or x == 1 or x == "true":
        return True
    return False


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


def detect_mean_revert_signal(
    bar: dict,
    *,
    sd_threshold_pct: float,
    rvol_zscore_min: float,
    require_exhaustion: bool,
    require_delta_direction: bool,
    use_sd_level: str = "sd2",
    regime_filter_mode: str = "off",
    skip_london: bool = False,
    skip_preopen_us: bool = False,
    trend_day_max: float = 1.0,
    vix_min_for_short: float = 0.0,
) -> Optional[str]:
    """Detecte signal mean revert v2. Retourne 'LONG' / 'SHORT' / None.

    Convention sierra_enriched :
      dist_vwap_d_sd2d_pct < 0 si prix sous SD2d (extension extreme low)
      dist_vwap_d_sd2u_pct > 0 si prix au-dessus SD2u (extension extreme high)
    """
    # FILTRE 3a : skip London session
    session_id = (bar.get('session_id') or '').lower()
    if skip_london and session_id == 'london':
        return None

    # FILTRE 3b : skip 11:30-13:30 UTC (pre-open US bruit)
    if skip_preopen_us:
        ts_ms = bar.get('ts', 0)
        if ts_ms > 0:
            try:
                dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                minute_of_day_utc = dt_utc.hour * 60 + dt_utc.minute
                if 11 * 60 + 30 <= minute_of_day_utc < 13 * 60 + 30:
                    return None
            except (OSError, ValueError, OverflowError):
                pass

    # FILTRE bonus : trend_day_max
    if trend_day_max < 1.0:
        trend_day_score = _f(bar.get('ctx_trend_day_score'))
        if trend_day_score > trend_day_max:
            return None

    # Charger distances aux SD bands
    if use_sd_level == "sd2":
        d_low = _f(bar.get("dist_vwap_d_sd2d_pct"))
        d_high = _f(bar.get("dist_vwap_d_sd2u_pct"))
    else:  # sd3
        d_low = _f(bar.get("dist_vwap_d_sd3d_pct"))
        d_high = _f(bar.get("dist_vwap_d_sd3u_pct"))

    rvol_z = _f(bar.get("rvol_zscore"))
    if rvol_z < rvol_zscore_min:
        return None

    # Exhaustion check
    climax = _b(bar.get("ctx_climax_signal"))
    failed_auct = _b(bar.get("ctx_failed_auction"))
    delta_exhaust = _b(bar.get("ctx_delta_exhaustion"))
    momentum_exhaust = _b(bar.get("ctx_momentum_exhaustion"))
    exhaustion_ok = (
        (not require_exhaustion)
        or climax or failed_auct or delta_exhaust or momentum_exhaust
    )
    if not exhaustion_ok:
        return None

    delta_bar = _f(bar.get("delta_bar"))
    slope_30 = _f(bar.get("vwap_slope_30"))
    vix = _f(bar.get("vix_level"))

    # LONG : prix sous SD extension extreme low
    if d_low <= -sd_threshold_pct:
        # FILTRE 1 : Regime asymetrique LONG
        if regime_filter_mode == 'trend_align_es':
            if slope_30 <= 0:
                return None
        elif regime_filter_mode == 'contrarian_nq':
            if slope_30 >= 0:
                return None
        if require_delta_direction and delta_bar <= 0:
            return None
        return "LONG"

    # SHORT : prix au-dessus SD extension extreme high
    if d_high >= sd_threshold_pct:
        # FILTRE 1 : Regime asymetrique SHORT
        if regime_filter_mode == 'trend_align_es':
            if slope_30 >= 0:
                return None
            if vix_min_for_short > 0 and vix <= vix_min_for_short:
                return None
        elif regime_filter_mode == 'contrarian_nq':
            if slope_30 <= 0:
                return None
        if require_delta_direction and delta_bar >= 0:
            return None
        return "SHORT"

    return None


def simulate_trade(
    entry_idx: int, side: str, bars: list[dict], sym: str, rr: float
) -> dict:
    tick = TICK_BY_SYM[sym]
    sl_ticks = SL_TICKS_BY_SYM[sym]
    tp_ticks = int(round(sl_ticks * rr))

    entry_price = _f(bars[entry_idx].get("close"))
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
        nxt_high = _f(nxt.get("bar_high")) or _f(nxt.get("high"))
        nxt_low = _f(nxt.get("bar_low")) or _f(nxt.get("low"))
        if nxt_high <= 0 or nxt_low <= 0:
            continue

        if side == "LONG":
            if nxt_low <= sl_price:
                return {"outcome": "SL", "pnl_ticks": -sl_ticks, "bars_held": k}
            if nxt_high >= tp_price:
                return {"outcome": "TP", "pnl_ticks": tp_ticks, "bars_held": k}
        else:
            if nxt_high >= sl_price:
                return {"outcome": "SL", "pnl_ticks": -sl_ticks, "bars_held": k}
            if nxt_low <= tp_price:
                return {"outcome": "TP", "pnl_ticks": tp_ticks, "bars_held": k}

    exit_idx = min(entry_idx + MAX_BARS_HOLD, len(bars) - 1)
    exit_price = _f(bars[exit_idx].get("close"))
    if exit_price <= 0:
        return {"outcome": "TIMEOUT", "pnl_ticks": 0, "bars_held": MAX_BARS_HOLD}
    pnl_pts = (exit_price - entry_price) if side == "LONG" else (entry_price - exit_price)
    pnl_t = int(round(pnl_pts / tick))
    return {"outcome": "TIMEOUT", "pnl_ticks": pnl_t, "bars_held": MAX_BARS_HOLD}


def backtest_config(
    bars: list[dict], sym: str, *, sd_threshold_pct, rvol_zscore_min,
    require_exhaustion, require_delta_direction, rr, sd_level,
    cooldown_bars=30,
    regime_filter_mode='off',
    skip_london=False,
    skip_preopen_us=False,
    trend_day_max=1.0,
    vix_min_for_short=0.0,
) -> dict:
    trades = []
    last_entry_idx = -cooldown_bars
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
        result = simulate_trade(i, side, bars, sym, rr)
        result["side"] = side
        result["session_id"] = bar.get("session_id", "?")
        trades.append(result)
        last_entry_idx = i

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

    print(f"=== {sym} v2 : {len(files)} fichiers ===")
    all_bars = []
    for f in files:
        bars = load_bars(f)
        print(f"  {f.name} : {len(bars)} bars")
        all_bars.extend(bars)
    print(f"Total bars : {len(all_bars)}")
    print()

    if sym == 'ES':
        regime_mode = 'trend_align_es'
        skip_lon = True
        skip_pre = True
        trend_max = 1.0
        vix_min_sh = 20.0
        print('FILTRES ES : trend_align_es | skip_london=True | skip_preopen_us=True | vix_min_short=20')
    elif sym == 'NQ':
        regime_mode = 'contrarian_nq'
        skip_lon = False
        skip_pre = False
        trend_max = 0.65
        vix_min_sh = 0.0
        print('FILTRES NQ : contrarian_nq | skip_london=False (Asia+London OK) | trend_day_max=0.65')
    else:
        regime_mode = 'off'
        skip_lon = False
        skip_pre = False
        trend_max = 1.0
        vix_min_sh = 0.0
    print()

    # Sweep parametres
    sd_thresholds = [0.0, 0.02, 0.05]  # % au-dela du SD level (0 = just touch)
    rvol_zscore_mins = [0.0, 0.5, 1.0, 1.5]
    exhaustion_required = [False, True]
    delta_required = [False, True]
    rr_grid = [1.5, 2.0]
    sd_level_grid = ["sd2", "sd3"]

    results = []
    for sd, rv, ex, de, rr, sdl in product(
        sd_thresholds, rvol_zscore_mins, exhaustion_required,
        delta_required, rr_grid, sd_level_grid,
    ):
        stats = backtest_config(
            all_bars, sym,
            sd_threshold_pct=sd, rvol_zscore_min=rv,
            require_exhaustion=ex, require_delta_direction=de,
            rr=rr, sd_level=sdl,
            regime_filter_mode=regime_mode,
            skip_london=skip_lon,
            skip_preopen_us=skip_pre,
            trend_day_max=trend_max,
            vix_min_for_short=vix_min_sh,
        )
        if stats["n_trades"] < 5:
            continue  # skip noise
        results.append({
            "sd_thr_pct": sd, "rvol_z_min": rv,
            "exh_req": ex, "delta_req": de, "rr": rr, "sd_lvl": sdl,
            **stats,
        })

    # Tri par PF * sqrt(n)
    results.sort(key=lambda r: r["pf"] * (r["n_trades"] ** 0.5), reverse=True)

    print(f"=== Top 15 configs {sym} v2 (n>=5, tri PF * sqrt(n)) ===")
    print(f"{'sd':>4} {'thr%':>5} {'rvolZ':>5} {'exh':>3} {'dlt':>3} {'rr':>4} | {'n':>4} {'WR%':>5} {'PF':>5} {'pnl_t':>6} {'pnl_$':>9} | sessions | sides")
    print("-" * 145)
    for r in results[:15]:
        sess_str = ", ".join(f"{s}:{n}" for s, n in r["by_session"].items())
        side_str = ", ".join(f"{s}:{n}" for s, n in r["by_side"].items())
        print(
            f"{r['sd_lvl']:>4} {r['sd_thr_pct']:5.2f} {r['rvol_z_min']:5.1f} "
            f"{str(r['exh_req'])[0]:>3} {str(r['delta_req'])[0]:>3} {r['rr']:4.1f} | "
            f"{r['n_trades']:4d} {r['wr_pct']:5.1f} {r['pf']:5.2f} "
            f"{r['pnl_ticks']:6d} ${r['pnl_usd']:8.0f} | {sess_str} | {side_str}"
        )

    # PnL par session (top config)
    if results:
        best = results[0]
        print()
        print(f"=== Best config breakdown ===")
        print(f"PnL par session : {best['by_session_pnl']}")
        print(f"N trades par side : {best['by_side']}")
        print(f"PnL par side : {best['by_side_pnl']}")


if __name__ == "__main__":
    main()
