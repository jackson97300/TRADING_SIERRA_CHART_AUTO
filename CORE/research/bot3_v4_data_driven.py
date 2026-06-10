"""bot3_v4_data_driven.py — Bot 3 v4 base sur analyse empirique 54K bounces.

Jackson directive 24/05/2026 : design data-driven a partir des bounces reels
identifies via analyze_real_reaction_zones.py.

TRIGGERS (asymetries empiriques) :
  LONG :
    - SWING_LOW touch (81% conditional LONG bounce)
    - VWAP_D_SD2D touch (72% LONG)
    - CUR_VAL touch (61% LONG)
  SHORT :
    - SWING_HIGH touch (76% SHORT)
    - VWAP_D_SD2U touch (72% SHORT)
    - CUR_VAH touch (63% SHORT)

TP MAGNET : CUR_VPOC (present dans 26% des bounces, magnet directionnel)
TP FALLBACK : 1.5R si VPOC trop loin ou trop proche

SL : swing oppose +/- 5 ticks, fallback 12-15 ticks
NEWS VETO : fail-closed
BONUS CONFIRMATION (optional) :
  - LONG : delta_div_sell==1 (vendeur epuise) ou long_up_bar==1
  - SHORT : delta_div_buy==1 ou long_dn_bar==1
PAS DE FILTER REGIME (TREND 56% des bounces empirique).

MATRIX : 2 sym x 2 TP modes (VPOC magnet / R1.5) x 2 bonus (yes/no) = 8 buckets.

OUTPUT : LOGS/bot3_v4/REPORT.md
"""
from __future__ import annotations

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
from CORE.research.bot3_reform_variants import filter_news_veto


# ════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════

TOUCH_BUFFER_PCT = 0.02      # 0.02% = ~4 ticks NQ a 20K

# 6 niveaux empiriquement valides
TRIGGER_LEVELS_LONG = [
    ("SWING_LOW", "dist_last_swing_low_pct", 0.81),       # asym 81% LONG
    ("VWAP_D_SD2D", "dist_vwap_d_sd2d_pct", 0.72),         # 72% LONG
    ("CUR_VAL", "dist_cur_val_pct", 0.61),                 # 61% LONG
]
TRIGGER_LEVELS_SHORT = [
    ("SWING_HIGH", "dist_last_swing_high_pct", 0.76),
    ("VWAP_D_SD2U", "dist_vwap_d_sd2u_pct", 0.72),
    ("CUR_VAH", "dist_cur_vah_pct", 0.63),
]

SL_FALLBACK_NQ = 15          # fallback SL si swing absent (12-18 ticks selon volat)
SL_FALLBACK_ES = 8
SL_BUFFER_TICKS = 5          # buffer au-dela swing

TIMEOUT_BARS = 120           # 2h max (bounces median 52 ticks dans 15 bars, 2h amplement)

COOLDOWN_BARS = 30           # min 30 bars entre 2 trades meme niveau
MAX_PER_LEVEL_PER_DAY = 2    # 2 trades max par niveau par jour

OUT_DIR = ROOT / "LOGS" / "bot3_v4"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# TOUCH DETECTION (first-touch + cooldown)
# ════════════════════════════════════════════════════════════════════════

def detect_first_touches(
    df: pd.DataFrame,
    dist_col: str,
    cooldown_bars: int = COOLDOWN_BARS,
    max_per_day: int = MAX_PER_LEVEL_PER_DAY,
) -> List[int]:
    """First-touch detection : abs(dist) <= TOUCH_BUFFER ET prev abs(dist) > TOUCH_BUFFER."""
    if dist_col not in df.columns:
        return []
    n = len(df)
    abs_dist = df[dist_col].abs().values
    in_zone = (abs_dist <= TOUCH_BUFFER_PCT) & np.isfinite(abs_dist)
    prev_in = np.concatenate([[False], in_zone[:-1]])
    first_touch = in_zone & (~prev_in)
    dates = df["date"].values

    kept = []
    last_idx = -10000
    day_count: Dict[str, int] = {}
    for i in np.where(first_touch)[0]:
        if i - last_idx < cooldown_bars:
            continue
        day = dates[i]
        if day_count.get(day, 0) >= max_per_day:
            continue
        kept.append(int(i))
        last_idx = int(i)
        day_count[day] = day_count.get(day, 0) + 1
    return kept


# ════════════════════════════════════════════════════════════════════════
# BONUS CONFIRMATION
# ════════════════════════════════════════════════════════════════════════

def has_bonus_confirmation(row: pd.Series, side: str) -> bool:
    """LONG bonus : delta_div_sell==1 OR long_up_bar==1
       SHORT bonus : delta_div_buy==1 OR long_dn_bar==1
    """
    if side == "LONG":
        for col in ("delta_div_sell", "long_up_bar"):
            v = row.get(col, 0)
            try:
                if int(v) == 1:
                    return True
            except (TypeError, ValueError):
                continue
    else:
        for col in ("delta_div_buy", "long_dn_bar"):
            v = row.get(col, 0)
            try:
                if int(v) == 1:
                    return True
            except (TypeError, ValueError):
                continue
    return False


# ════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ════════════════════════════════════════════════════════════════════════

def simulate_v4_trade(
    df: pd.DataFrame,
    entry_idx: int,
    level_name: str,
    level_family: str,
    side: str,
    symbol: str,
    tp_mode: str,            # "VPOC" ou "R15"
    variant_name: str,
    trade_id: str,
) -> Optional[Trade]:
    """Simulate Bot 3 v4 trade :
       - Entry au close de la bar de touch
       - SL : swing oppose +/- 5t (fallback)
       - TP : cur_VPOC magnet OR 1.5R selon mode
    """
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
        # SL : swing low recent - 5t
        swing = _safe_float(entry_bar.get("_last_swing_low_price"))
        if swing > 0 and swing < entry_with_slip:
            sl_price = swing - SL_BUFFER_TICKS * TICK_SIZE
            sl_ticks = round((entry_with_slip - sl_price) / TICK_SIZE)
            # Cap SL pour eviter SL trop loin (e.g. swing tres ancien)
            if sl_ticks > sl_fallback * 2.5:
                sl_ticks = sl_fallback
                sl_price = entry_with_slip - sl_ticks * TICK_SIZE
        else:
            sl_ticks = sl_fallback
            sl_price = entry_with_slip - sl_ticks * TICK_SIZE
        if sl_ticks < 5:
            sl_ticks = 5
            sl_price = entry_with_slip - 5 * TICK_SIZE
        # TP
        if tp_mode == "VPOC":
            vpoc = _safe_float(entry_bar.get("cur_vpoc"))
            if vpoc > entry_with_slip and (vpoc - entry_with_slip) >= 5 * TICK_SIZE:
                tp_price = vpoc
            else:
                tp_price = entry_with_slip + 1.5 * sl_ticks * TICK_SIZE
        else:  # R15
            tp_price = entry_with_slip + 1.5 * sl_ticks * TICK_SIZE
    else:  # SHORT
        entry_with_slip = entry_price - slip_entry
        swing = _safe_float(entry_bar.get("_last_swing_high_price"))
        if swing > 0 and swing > entry_with_slip:
            sl_price = swing + SL_BUFFER_TICKS * TICK_SIZE
            sl_ticks = round((sl_price - entry_with_slip) / TICK_SIZE)
            if sl_ticks > sl_fallback * 2.5:
                sl_ticks = sl_fallback
                sl_price = entry_with_slip + sl_ticks * TICK_SIZE
        else:
            sl_ticks = sl_fallback
            sl_price = entry_with_slip + sl_ticks * TICK_SIZE
        if sl_ticks < 5:
            sl_ticks = 5
            sl_price = entry_with_slip + 5 * TICK_SIZE
        if tp_mode == "VPOC":
            vpoc = _safe_float(entry_bar.get("cur_vpoc"))
            if vpoc > 0 and vpoc < entry_with_slip and (entry_with_slip - vpoc) >= 5 * TICK_SIZE:
                tp_price = vpoc
            else:
                tp_price = entry_with_slip - 1.5 * sl_ticks * TICK_SIZE
        else:
            tp_price = entry_with_slip - 1.5 * sl_ticks * TICK_SIZE

    end_idx = min(len(df), entry_idx + 1 + TIMEOUT_BARS)
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
    pnl_ticks = pnl_pts / TICK_SIZE
    pnl_dollars = pnl_ticks * tick_value - COMMISSION_PER_RT
    pnl_R = pnl_ticks / sl_ticks if sl_ticks > 0 else 0.0

    return Trade(
        trade_id=trade_id,
        variant=variant_name,
        symbol=symbol,
        level_name=level_name,
        level_tier=1,
        level_family=level_family,
        side=side,
        side_original=side,
        entry_bar_ts=entry_bar["ts_event"].isoformat(),
        entry_bar_idx=int(entry_idx),
        entry_price=round(entry_price, 4),
        entry_price_with_slip=round(entry_with_slip, 4),
        sl_price=round(sl_price, 4),
        tp_price=round(tp_price, 4),
        sl_ticks=int(sl_ticks),
        target_pct=0.0,
        exit_bar_ts=df.iloc[exit_idx]["ts_event"].isoformat(),
        exit_bar_idx=int(exit_idx),
        exit_price=round(exit_price, 4),
        exit_price_with_slip=round(exit_price, 4),
        exit_reason=exit_reason,
        duration_bars=int(exit_idx - entry_idx),
        pnl_ticks_gross=round(pnl_ticks, 2),
        pnl_ticks_net=round(pnl_dollars / tick_value, 2),
        pnl_R=round(pnl_R, 4),
        pnl_dollars_net=round(pnl_dollars, 2),
        session_at_entry=session,
        regime_mode_at_entry=str(entry_bar.get("regime_mode", "")),
        regime_favor_at_entry=str(entry_bar.get("regime_favor", "")),
        rvol_at_entry=0.0,
    )


# ════════════════════════════════════════════════════════════════════════
# RUN BUCKET
# ════════════════════════════════════════════════════════════════════════

def run_v4_bucket(
    df: pd.DataFrame,
    symbol: str,
    tp_mode: str,
    require_bonus: bool,
    variant_name: str,
) -> List[Trade]:
    """Run Bot 3 v4 sur 1 symbol avec config :
       - 6 niveaux triggers (3 LONG + 3 SHORT)
       - TP : VPOC magnet ou R1.5
       - Bonus confirmation : optionnel
    """
    all_entries: List[Tuple[int, str, str, str]] = []
    # LONG triggers
    for lv_name, dist_col, _ in TRIGGER_LEVELS_LONG:
        touches = detect_first_touches(df, dist_col)
        for idx in touches:
            family = "SWING" if "SWING" in lv_name else ("VWAP" if "VWAP" in lv_name else "MP")
            all_entries.append((idx, lv_name, family, "LONG"))
    # SHORT triggers
    for lv_name, dist_col, _ in TRIGGER_LEVELS_SHORT:
        touches = detect_first_touches(df, dist_col)
        for idx in touches:
            family = "SWING" if "SWING" in lv_name else ("VWAP" if "VWAP" in lv_name else "MP")
            all_entries.append((idx, lv_name, family, "SHORT"))

    # Sort + dedup 1 trade per bar + tracking last_exit
    all_entries.sort(key=lambda x: x[0])
    trades: List[Trade] = []
    last_exit_idx = -1
    seen_bars = set()
    counter = 0
    for idx, lv_name, family, side in all_entries:
        if idx <= last_exit_idx:
            continue
        if idx in seen_bars:
            continue
        seen_bars.add(idx)
        row = df.iloc[idx]
        # News veto
        if not filter_news_veto(row, side):
            continue
        # Bonus confirmation
        if require_bonus and not has_bonus_confirmation(row, side):
            continue
        counter += 1
        trade_id = f"{variant_name}_{symbol}_{counter:05d}"
        trade = simulate_v4_trade(
            df=df, entry_idx=idx,
            level_name=lv_name, level_family=family,
            side=side, symbol=symbol,
            tp_mode=tp_mode, variant_name=variant_name,
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
    print(f"BOT 3 v4 — DATA-DRIVEN (6 triggers empiriques + VPOC magnet)")
    print(f"{'='*80}\n")

    print("Triggers LONG : SWING_LOW (81%), VWAP_D_SD2D (72%), CUR_VAL (61%)")
    print("Triggers SHORT : SWING_HIGH (76%), VWAP_D_SD2U (72%), CUR_VAH (63%)")
    print("TP : VPOC magnet OU R1.5")
    print(f"SL : swing oppose +/- {SL_BUFFER_TICKS}t (fallback {SL_FALLBACK_NQ}/{SL_FALLBACK_ES}t)")
    print(f"News veto fail-closed, cooldown {COOLDOWN_BARS} bars, max {MAX_PER_LEVEL_PER_DAY}/level/day\n")

    dfs: Dict[str, pd.DataFrame] = {}
    for sym in ["NQ", "ES"]:
        print(f"[LOAD] {sym}...", flush=True)
        t0 = time.time()
        dfs[sym] = load_v4_enriched(sym)
        print(f"  {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours "
              f"({time.time()-t0:.1f}s)", flush=True)

    results: List[Dict] = []
    for sym in ["NQ", "ES"]:
        for tp_mode in ["VPOC", "R15"]:
            for require_bonus in (False, True):
                bonus_s = "_bonus" if require_bonus else ""
                name = f"V4_{sym}_TP_{tp_mode}{bonus_s}"
                t0 = time.time()
                trades = run_v4_bucket(
                    df=dfs[sym], symbol=sym, tp_mode=tp_mode,
                    require_bonus=require_bonus, variant_name=name,
                )
                trades = assign_folds(trades)
                elapsed = time.time() - t0
                metrics = stats_of(trades)
                wf = compute_walk_forward(trades)
                dsr_dict = compute_psr_dsr(trades, n_trials=8)  # 8 buckets
                # Save trades
                bdir = OUT_DIR / name
                bdir.mkdir(parents=True, exist_ok=True)
                with open(bdir / "trades.jsonl", "w", encoding="utf-8") as f:
                    for t in trades:
                        f.write(json.dumps(asdict(t)) + "\n")
                row = {
                    "bucket": name, "symbol": sym, "tp_mode": tp_mode,
                    "require_bonus": require_bonus,
                    **metrics,
                    "dsr": dsr_dict["dsr"], "psr": dsr_dict["psr"],
                    "sharpe": dsr_dict["sharpe"],
                    "pf_min_fold": wf["pf_min_fold"],
                    "pf_median_fold": wf["pf_median_fold"],
                    "n_folds_pf_gt_1_3": wf["n_folds_pf_gt_1_3"],
                    "wf_consistency": wf["wf_consistency"],
                    "runtime_sec": round(elapsed, 1),
                }
                results.append(row)
                print(f"  {name:30s} n={metrics['n']:4d} WR={metrics['wr_pct']:5.1f}% "
                      f"PF={metrics['pf']:5.2f} DSR={dsr_dict['dsr']:.3f} "
                      f"PF_min_fold={wf['pf_min_fold']:.2f}", flush=True)

    df_res = pd.DataFrame(results)
    df_res.to_csv(OUT_DIR / "summary_v4.csv", index=False)

    # REPORT
    report = []
    report.append("# Bot 3 v4 — Data-driven (54K bounces empirique)\n")
    report.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    report.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END}")
    report.append("Triggers LONG : SWING_LOW (81%), VWAP_D_SD2D (72%), CUR_VAL (61%)")
    report.append("Triggers SHORT : SWING_HIGH (76%), VWAP_D_SD2U (72%), CUR_VAH (63%)")
    report.append("TP modes : VPOC magnet (cur_vpoc) ou R1.5 fallback")
    report.append("SL : swing oppose +/- 5t (fallback 15/8t)")
    report.append("News veto fail-closed, no regime filter (TREND 56% des bounces)\n")

    report.append("## Resultats matrix (sorted by DSR desc)\n")
    df_sorted = df_res.sort_values("dsr", ascending=False)
    report.append("| Bucket | Sym | TP | Bonus | n | WR% | PF | DSR | PF_min_fold |")
    report.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in df_sorted.iterrows():
        b = "YES" if r["require_bonus"] else "no"
        report.append(f"| **{r['bucket']}** | {r['symbol']} | {r['tp_mode']} | {b} | "
                      f"{r['n']} | {r['wr_pct']} | {r['pf']} | {r['dsr']} | "
                      f"{r['pf_min_fold']} |")

    # Critere recalibre pragmatique
    candidates = df_res[
        (df_res["n"] >= 50) & (df_res["pf"] >= 1.0) & (df_res["dsr"] >= 0.10)
    ].sort_values("dsr", ascending=False)
    report.append("\n## Verdict (criteres pragmatiques : n>=50, PF>=1.0, DSR>=0.10)\n")
    if len(candidates) > 0:
        report.append(f"**{len(candidates)} bucket(s) GO pragmatique** :")
        for _, r in candidates.iterrows():
            b = "YES" if r["require_bonus"] else "no"
            report.append(f"  - {r['bucket']} (TP={r['tp_mode']}, bonus={b}) : "
                          f"n={r['n']}, PF={r['pf']}, DSR={r['dsr']}, "
                          f"PF_min_fold={r['pf_min_fold']}")
    else:
        report.append("**NOGO pragmatique** : aucun bucket n>=50, PF>=1.0, DSR>=0.10")
        report.append("\nTop 3 :")
        for _, r in df_sorted.head(3).iterrows():
            report.append(f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}")

    (OUT_DIR / "REPORT.md").write_text("\n".join(report), encoding="utf-8")

    print(f"\n[CSV] {OUT_DIR / 'summary_v4.csv'}")
    print(f"[REPORT] {OUT_DIR / 'REPORT.md'}")

    # Console summary
    print(f"\n{'='*80}")
    print("TOP par DSR")
    print(f"{'='*80}")
    print(df_sorted[["bucket", "n", "wr_pct", "pf", "dsr", "pf_min_fold"]].to_string(index=False))


if __name__ == "__main__":
    main()
