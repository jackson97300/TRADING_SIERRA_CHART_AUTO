"""bot3_v3_zone_reversal_scalp.py — Bot 3 v3 paradigme Jackson 24/05/2026.

Jackson directive : changer paradigme - trading de zones a reaction + reversals
+ petits scalps.

CONCEPT :
  Trader UNIQUEMENT dans zones de reaction prouvees (niveau ou prix a deja
  reagi >=2 fois dans 5 jours precedents), sur setup reversal V4 (long_dn_up
  / long_up_dn pattern + bonus rvol_extreme), avec TP/SL courts (scalp).

3 PILIERS :
  1. ZONE REACTION : niveau touche >=2x dans 5 jours precedents AVEC bounce >=15t
  2. REVERSAL SETUP : long_dn_up_pattern==1 (LONG) ou long_up_dn_pattern==1 (SHORT)
  3. SCALP : SL court (swing +/- 3t, fallback 12t NQ / 6t ES), TP R-multiple
     court (1.0R/1.5R/2R), timeout 60 bars max

FILTERS :
  - regime_mode != TREND (zones cassent en trend)
  - news veto fail-closed

MATRIX : 22 levels × 3 R-multiples × 2 (with/without rvol_extreme bonus) × 2 sym
       × 2 (with/without zone reaction filter) = ~48 buckets

OUTPUT : LOGS/bot3_v3_zones/REPORT.md
"""
from __future__ import annotations

import glob
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot3_reform_backtester import (
    COMMISSION_PER_RT,
    LOG_DIR,
    PERIOD_END,
    PERIOD_START,
    SLIPPAGE,
    TICK_SIZE,
    Trade,
    _safe_float,
    assign_folds,
    compute_psr_dsr,
    compute_walk_forward,
    get_session_label,
    get_slippage,
    load_v4_enriched,
    stats_of,
)
from CORE.research.bot3_reform_variants import (
    LEVELS_V1_LONG,
    LEVELS_V4_SHORT,
    LevelDef,
    filter_news_veto,
    filter_regime_no_trend,
)


# ════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════

TOUCH_BUFFER_PCT = 0.02      # 0.02% = ~4 ticks NQ pour detection touch
BOUNCE_MIN_TICKS_NQ = 15     # bounce min apres touch pour validation zone NQ
BOUNCE_MIN_TICKS_ES = 6      # ES (atr plus faible)
BOUNCE_WINDOW_BARS = 20      # fenetre pour mesurer bounce post-touch
ZONE_LOOKBACK_DAYS = 5       # historique pour compter touches (5 jours roulants)
ZONE_MIN_REACTIONS = 2       # minimum 2 touches+bounce pour qualifier zone

SL_FALLBACK_NQ = 12          # SL court NQ
SL_FALLBACK_ES = 6           # SL court ES
SL_BUFFER_TICKS = 3          # buffer au-dela swing

TIMEOUT_BARS = 60            # 1h max (scalp)

OUT_DIR = ROOT / "LOGS" / "bot3_v3_zones"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# ZONE REACTION DETECTION
# ════════════════════════════════════════════════════════════════════════

def detect_touches_with_bounce(
    df: pd.DataFrame,
    level: LevelDef,
    bounce_ticks: int,
) -> List[int]:
    """Detecte les bars ou prix touche le niveau ET bounce >=bounce_ticks dans
    WINDOW_RETEST_CONFIRM bars suivants.

    Returns list of bar_idx avec touch+bounce confirme.
    """
    if level.dist_col not in df.columns:
        return []

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    dist_vals = df[level.dist_col].values
    n = len(df)

    touches = []
    side = level.side_default
    # Detecter first-touch (abs dist <= TOUCH_BUFFER)
    abs_dist = np.abs(dist_vals)
    in_zone = abs_dist <= TOUCH_BUFFER_PCT
    in_zone_prev = np.concatenate([[False], in_zone[:-1]])
    first_touch = in_zone & (~in_zone_prev)

    for i in np.where(first_touch)[0]:
        if i >= n - BOUNCE_WINDOW_BARS:
            continue
        if pd.isna(dist_vals[i]):
            continue
        touch_price = closes[i]
        # Mesurer bounce : si LONG level (support), prix doit monter de bounce_ticks
        # Si SHORT level (resistance), prix doit descendre de bounce_ticks
        bounce_target = bounce_ticks * TICK_SIZE
        bounced = False
        for j in range(i + 1, min(i + 1 + BOUNCE_WINDOW_BARS, n)):
            if side == "LONG":
                if highs[j] - touch_price >= bounce_target:
                    bounced = True
                    break
                if lows[j] < touch_price - bounce_target * 1.5:
                    break  # ca casse, pas bounce
            else:
                if touch_price - lows[j] >= bounce_target:
                    bounced = True
                    break
                if highs[j] > touch_price + bounce_target * 1.5:
                    break
        if bounced:
            touches.append(int(i))
    return touches


def is_zone_active(
    touches: List[int],
    current_idx: int,
    lookback_bars: int,
    min_reactions: int,
) -> bool:
    """Zone est active si >=min_reactions touches+bounce dans lookback_bars precedents."""
    threshold_idx = current_idx - lookback_bars
    recent = sum(1 for t in touches if threshold_idx <= t < current_idx)
    return recent >= min_reactions


# ════════════════════════════════════════════════════════════════════════
# REVERSAL SIGNAL DETECTION
# ════════════════════════════════════════════════════════════════════════

def has_reversal_signal(row: pd.Series, side: str, require_rvol: bool = False) -> bool:
    """Detect reversal signal sur la bar courante.

    LONG : long_dn_up_pattern==1 (V4 Jackson reversal LONG)
    SHORT : long_up_dn_pattern==1 (V4 Jackson reversal SHORT)
    Bonus optional : rvol_extreme==1 (exhaustion)
    """
    if side == "LONG":
        pat = row.get("long_dn_up_pattern", 0)
    else:
        pat = row.get("long_up_dn_pattern", 0)
    try:
        if int(pat) != 1:
            return False
    except (TypeError, ValueError):
        return False
    if require_rvol:
        rv = row.get("rvol_extreme", 0)
        try:
            if int(rv) != 1:
                return False
        except (TypeError, ValueError):
            return False
    return True


# ════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION (scalp)
# ════════════════════════════════════════════════════════════════════════

def simulate_scalp_trade(
    df: pd.DataFrame,
    entry_idx: int,
    level: LevelDef,
    side: str,
    target_R: float,
    symbol: str,
    variant_name: str,
    trade_id: str,
    timeout_bars: int = TIMEOUT_BARS,
) -> Optional[Trade]:
    """Simulate scalp trade avec SL swing-based + TP R-multiple court."""
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = _safe_float(entry_bar.get("close"))
    if entry_price <= 0:
        return None
    entry_date = entry_bar["date"]
    session = get_session_label(entry_bar)

    slip_entry = get_slippage(session, "entry") * TICK_SIZE
    slip_sl = get_slippage(session, "sl") * TICK_SIZE
    slip_tp = get_slippage(session, "tp") * TICK_SIZE
    tick_value = 1.25 if symbol == "ES" else 0.50
    sl_fallback = SL_FALLBACK_NQ if symbol == "NQ" else SL_FALLBACK_ES

    if side == "LONG":
        entry_with_slip = entry_price + slip_entry
        swing = _safe_float(entry_bar.get("_last_swing_low_price"))
        if swing > 0 and swing < entry_with_slip:
            sl_price = swing - SL_BUFFER_TICKS * TICK_SIZE
            sl_ticks = round((entry_with_slip - sl_price) / TICK_SIZE)
            if sl_ticks > sl_fallback * 2:  # SL trop loin, cap
                sl_ticks = sl_fallback
                sl_price = entry_with_slip - sl_ticks * TICK_SIZE
        else:
            sl_ticks = sl_fallback
            sl_price = entry_with_slip - sl_ticks * TICK_SIZE
        if sl_ticks < 4:
            sl_ticks = 4
            sl_price = entry_with_slip - 4 * TICK_SIZE
        tp_price = entry_with_slip + target_R * sl_ticks * TICK_SIZE
    else:
        entry_with_slip = entry_price - slip_entry
        swing = _safe_float(entry_bar.get("_last_swing_high_price"))
        if swing > 0 and swing > entry_with_slip:
            sl_price = swing + SL_BUFFER_TICKS * TICK_SIZE
            sl_ticks = round((sl_price - entry_with_slip) / TICK_SIZE)
            if sl_ticks > sl_fallback * 2:
                sl_ticks = sl_fallback
                sl_price = entry_with_slip + sl_ticks * TICK_SIZE
        else:
            sl_ticks = sl_fallback
            sl_price = entry_with_slip + sl_ticks * TICK_SIZE
        if sl_ticks < 4:
            sl_ticks = 4
            sl_price = entry_with_slip + 4 * TICK_SIZE
        tp_price = entry_with_slip - target_R * sl_ticks * TICK_SIZE

    end_idx = min(len(df), entry_idx + 1 + timeout_bars)
    exit_idx = -1
    exit_price = 0.0
    exit_reason = ""
    for j in range(entry_idx + 1, end_idx):
        bj = df.iloc[j]
        if bj["date"] != entry_date:
            exit_idx = j - 1
            exit_price = _safe_float(df.iloc[j - 1].get("close"))
            exit_reason = "EOD"
            break
        h = _safe_float(bj.get("high"))
        lw = _safe_float(bj.get("low"))
        if h <= 0 or lw <= 0:
            continue
        if side == "LONG":
            sl_hit = lw <= sl_price
            tp_hit = h >= tp_price
            if sl_hit and tp_hit:
                exit_idx, exit_price, exit_reason = j, sl_price - slip_sl, "SL"
                break
            if sl_hit:
                exit_idx, exit_price, exit_reason = j, sl_price - slip_sl, "SL"
                break
            if tp_hit:
                exit_idx, exit_price, exit_reason = j, tp_price - slip_tp, "TP"
                break
        else:
            sl_hit = h >= sl_price
            tp_hit = lw <= tp_price
            if sl_hit and tp_hit:
                exit_idx, exit_price, exit_reason = j, sl_price + slip_sl, "SL"
                break
            if sl_hit:
                exit_idx, exit_price, exit_reason = j, sl_price + slip_sl, "SL"
                break
            if tp_hit:
                exit_idx, exit_price, exit_reason = j, tp_price + slip_tp, "TP"
                break
    if exit_idx == -1:
        exit_idx = end_idx - 1
        exit_price = _safe_float(df.iloc[exit_idx].get("close"))
        exit_reason = "TIMEOUT"

    if side == "LONG":
        pnl_pts = exit_price - entry_with_slip
    else:
        pnl_pts = entry_with_slip - exit_price
    pnl_ticks_gross = pnl_pts / TICK_SIZE
    pnl_dollars_net = pnl_ticks_gross * tick_value - COMMISSION_PER_RT
    pnl_R = pnl_ticks_gross / sl_ticks if sl_ticks > 0 else 0.0

    return Trade(
        trade_id=trade_id,
        variant=variant_name,
        symbol=symbol,
        level_name=level.name,
        level_tier=level.tier,
        level_family=level.family,
        side=side,
        side_original=level.side_default,
        entry_bar_ts=entry_bar["ts_event"].isoformat(),
        entry_bar_idx=int(entry_idx),
        entry_price=round(entry_price, 4),
        entry_price_with_slip=round(entry_with_slip, 4),
        sl_price=round(sl_price, 4),
        tp_price=round(tp_price, 4),
        sl_ticks=int(sl_ticks),
        target_pct=round(target_R, 4),
        exit_bar_ts=df.iloc[exit_idx]["ts_event"].isoformat(),
        exit_bar_idx=int(exit_idx),
        exit_price=round(exit_price, 4),
        exit_price_with_slip=round(exit_price, 4),
        exit_reason=exit_reason,
        duration_bars=int(exit_idx - entry_idx),
        pnl_ticks_gross=round(pnl_ticks_gross, 2),
        pnl_ticks_net=round(pnl_dollars_net / tick_value, 2),
        pnl_R=round(pnl_R, 4),
        pnl_dollars_net=round(pnl_dollars_net, 2),
        session_at_entry=session,
        regime_mode_at_entry=str(entry_bar.get("regime_mode", "")),
        regime_favor_at_entry=str(entry_bar.get("regime_favor", "")),
        rvol_at_entry=_safe_float(entry_bar.get("rvol_extreme", 0)),
    )


# ════════════════════════════════════════════════════════════════════════
# RUN VARIANT
# ════════════════════════════════════════════════════════════════════════

def run_v3(
    df: pd.DataFrame,
    symbol: str,
    target_R: float,
    require_rvol: bool,
    use_zone_filter: bool,
    use_regime_filter: bool,
    levels: List[LevelDef],
    variant_name: str,
) -> List[Trade]:
    """Run Bot 3 v3 sur symbol :
       - Pour chaque level, detecter touches avec bounce historique
       - Pour chaque bar present : si touch + reversal signal + (optional) zone active
                                   + (optional) regime != TREND + news veto OK → ENTRY
    """
    bounce_ticks = BOUNCE_MIN_TICKS_NQ if symbol == "NQ" else BOUNCE_MIN_TICKS_ES
    # Cooldown : 1 trade par bar et par niveau
    all_entries: List[Tuple[int, LevelDef, str]] = []

    for level in levels:
        # Detecter touches historiques avec bounce confirme
        touches = detect_touches_with_bounce(df, level, bounce_ticks)
        if not touches:
            continue
        side = level.side_default
        # Pour chaque touch, verifier conditions entry
        for touch_idx in touches:
            row = df.iloc[touch_idx]
            # Reversal signal sur cette bar ?
            if not has_reversal_signal(row, side, require_rvol=require_rvol):
                continue
            # Zone reaction active ?
            if use_zone_filter:
                # Compter touches dans 5 jours precedents (= 5*1440 bars)
                lookback_bars = ZONE_LOOKBACK_DAYS * 1440
                if not is_zone_active(touches, touch_idx, lookback_bars, ZONE_MIN_REACTIONS):
                    continue
            # Regime filter
            if use_regime_filter and not filter_regime_no_trend(row, side):
                continue
            # News veto
            if not filter_news_veto(row, side):
                continue
            all_entries.append((touch_idx, level, side))

    # Dedupe par bar (1 trade par bar max) + tracking last_exit
    all_entries.sort(key=lambda x: x[0])
    trades: List[Trade] = []
    last_exit_idx = -1
    counter = 0
    seen_bars = set()
    for idx, level, side in all_entries:
        if idx <= last_exit_idx:
            continue
        if idx in seen_bars:
            continue
        seen_bars.add(idx)
        counter += 1
        trade_id = f"{variant_name}_{symbol}_{counter:05d}"
        trade = simulate_scalp_trade(
            df=df,
            entry_idx=idx,
            level=level,
            side=side,
            target_R=target_R,
            symbol=symbol,
            variant_name=variant_name,
            trade_id=trade_id,
        )
        if trade is None:
            continue
        trades.append(trade)
        last_exit_idx = trade.exit_bar_idx
    return trades


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{'='*80}")
    print(f"BOT 3 v3 — ZONES REACTION + REVERSAL + SCALP")
    print(f"{'='*80}\n")

    levels = list(LEVELS_V1_LONG) + list(LEVELS_V4_SHORT)
    print(f"Levels actifs : {len(levels)}")
    print(f"Zone reaction : touch >= {ZONE_MIN_REACTIONS}x dans {ZONE_LOOKBACK_DAYS}j")
    print(f"Reversal signal : long_dn_up_pattern (LONG) / long_up_dn_pattern (SHORT)")
    print(f"Scalp : SL court (swing +/- 3t, fallback {SL_FALLBACK_NQ}/{SL_FALLBACK_ES}t)\n")

    dfs: Dict[str, pd.DataFrame] = {}
    for sym in ["NQ", "ES"]:
        print(f"[LOAD] {sym}...", flush=True)
        t0 = time.time()
        dfs[sym] = load_v4_enriched(sym)
        print(f"  {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours "
              f"({time.time()-t0:.1f}s)", flush=True)

    R_MULTIPLES = [1.0, 1.5, 2.0]
    results: List[Dict] = []

    for sym in ["NQ", "ES"]:
        for r in R_MULTIPLES:
            for require_rvol in (False, True):
                for use_zone in (False, True):
                    # use_regime always True (regime filter recommanded)
                    rvol_s = "_rvol" if require_rvol else ""
                    zone_s = "_zone" if use_zone else "_nozone"
                    name = f"V3_{sym}_R{r}{rvol_s}{zone_s}".replace(".", "p")
                    t0 = time.time()
                    trades = run_v3(
                        df=dfs[sym],
                        symbol=sym,
                        target_R=r,
                        require_rvol=require_rvol,
                        use_zone_filter=use_zone,
                        use_regime_filter=True,
                        levels=levels,
                        variant_name=name,
                    )
                    trades = assign_folds(trades)
                    elapsed = time.time() - t0
                    metrics = stats_of(trades)
                    wf = compute_walk_forward(trades)
                    dsr_dict = compute_psr_dsr(trades, n_trials=24)
                    # Save trades
                    bdir = OUT_DIR / name
                    bdir.mkdir(parents=True, exist_ok=True)
                    with open(bdir / "trades.jsonl", "w", encoding="utf-8") as f:
                        for t in trades:
                            f.write(json.dumps(asdict(t)) + "\n")
                    row = {
                        "bucket": name,
                        "symbol": sym,
                        "target_R": r,
                        "require_rvol": require_rvol,
                        "use_zone": use_zone,
                        **metrics,
                        "dsr": dsr_dict["dsr"],
                        "psr": dsr_dict["psr"],
                        "sharpe": dsr_dict["sharpe"],
                        "pf_min_fold": wf["pf_min_fold"],
                        "n_folds_pf_gt_1_3": wf["n_folds_pf_gt_1_3"],
                        "runtime_sec": round(elapsed, 1),
                    }
                    results.append(row)
                    print(f"  {name:35s} n={metrics['n']:4d} "
                          f"WR={metrics['wr_pct']:5.1f}% PF={metrics['pf']:5.2f} "
                          f"DSR={dsr_dict['dsr']:.3f}", flush=True)

    df_res = pd.DataFrame(results)
    csv_path = OUT_DIR / "summary_v3.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n[CSV] {csv_path}")

    # REPORT
    report = []
    report.append("# Bot 3 v3 — Zones Reaction + Reversal + Scalp\n")
    report.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    report.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END} (MenthorQ propre)")
    report.append(f"Levels : 22 (V1 LONG + V4 SHORT)")
    report.append(f"Zone reaction : >= {ZONE_MIN_REACTIONS} touches+bounce dans "
                  f"{ZONE_LOOKBACK_DAYS}j precedents (bounce min "
                  f"{BOUNCE_MIN_TICKS_NQ}t NQ / {BOUNCE_MIN_TICKS_ES}t ES)")
    report.append(f"Reversal signal : long_dn_up_pattern (LONG) / long_up_dn_pattern (SHORT)")
    report.append(f"Scalp : SL swing recent + 3t (fallback {SL_FALLBACK_NQ}t NQ "
                  f"/ {SL_FALLBACK_ES}t ES), TP R-multiple, timeout {TIMEOUT_BARS}b")
    report.append(f"Regime filter : actif (skip TREND)")
    report.append(f"News veto : actif fail-closed")
    report.append(f"DSR haircut : N=24 (24 buckets)\n")

    report.append("## TOP par DSR\n")
    df_sorted = df_res.sort_values("dsr", ascending=False)
    report.append("| Bucket | Sym | R | rvol | zone | n | WR% | PF | DSR | PF_min_fold |")
    report.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in df_sorted.iterrows():
        rvol_s = "YES" if r["require_rvol"] else "no"
        zone_s = "YES" if r["use_zone"] else "no"
        report.append(
            f"| **{r['bucket']}** | {r['symbol']} | {r['target_R']}R | {rvol_s} | "
            f"{zone_s} | {r['n']} | {r['wr_pct']} | {r['pf']} | "
            f"{r['dsr']} | {r['pf_min_fold']} |"
        )

    candidates = df_res[
        (df_res["n"] >= 50) & (df_res["pf"] >= 1.3) & (df_res["dsr"] >= 0.30)
    ].sort_values("dsr", ascending=False)
    report.append("\n## Verdict\n")
    if len(candidates) > 0:
        report.append(f"**GO** : {len(candidates)} bucket(s) eligible(s) (n>=50, PF>=1.3, DSR>=0.30) :")
        for _, r in candidates.iterrows():
            report.append(f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}")
    else:
        report.append("**NOGO sur criteres strict (n>=50, PF>=1.3, DSR>=0.30)**")
        # Top 5
        report.append("\nTop 5 :")
        for _, r in df_sorted.head(5).iterrows():
            report.append(f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}")

    (OUT_DIR / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print(f"[REPORT] {OUT_DIR / 'REPORT.md'}")

    print(f"\n{'='*80}")
    print(f"TOP 10 par DSR")
    print(f"{'='*80}")
    print(df_sorted[["bucket", "n", "wr_pct", "pf", "dsr", "pf_min_fold"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
