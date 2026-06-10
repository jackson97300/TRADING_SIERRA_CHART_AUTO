"""bot3_continuation_backtester.py — Option 1 Phase A.

Jackson 24/05/2026 : apres Option 2 NOGO 30/30, on teste paradigme inverse :
CONTINUATION POST-RETEST au lieu de FADE FIRST-TOUCH.

HYPOTHESE : en regime TREND, les niveaux casent et le bon trade est dans
le sens du breakout, pas contre. Pattern documente expertise Jackson 11/05
(memoire feedback_range_confirmation_breakout) + Wyckoff phase E + Dalton
breakout failure → retest → continuation.

STATE MACHINE (par niveau, par jour) :
  ETAT 0 : WAITING_TOUCH  → prix loin du level
  ETAT 1 : ARMED          → premier touch (abs dist <= 0.02%)
  ETAT 2 : BREAKOUT       → close > level + 5 ticks (LONG) dans 60 bars
  ETAT 3 : WAITING_RETEST → prix revient toucher level +/- 5 ticks dans 120 bars
  ETAT 4 : CONFIRMATION   → long_up_bar=1 (LONG) ou long_dn_bar=1 (SHORT) sur
                            une des 3 bars suivant le retest
  ENTRY : close de la bar de confirmation

SL : sous swing low recent (_last_swing_low_price - 3 ticks) LONG
     ou au-dessus swing high (_last_swing_high_price + 3 ticks) SHORT
     Fallback si swing absent : entry +/- 30 ticks NQ / 20 ticks ES

TP : R-multiple (1.5R / 2R / 3R) ou ATR-multiple alternatif

Filter regime : regime_mode == 'TREND' uniquement
Filter news : actif (fail-closed)

LEVELS testes : 13 LONG (V1 baseline) + 9 SHORT (V4 additif) = 22 niveaux.

OUTPUT : LOGS/bot3_continuation/REPORT_CONTINUATION.md
"""
from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
    verdict_from_metrics,
)
from CORE.research.bot3_reform_variants import (
    LEVELS_V1_LONG,
    LEVELS_V4_SHORT,
    LevelDef,
    filter_news_veto,
    filter_regime_trend_only,
)


# ════════════════════════════════════════════════════════════════════════
# CONFIG STATE MACHINE
# ════════════════════════════════════════════════════════════════════════

# Buffers detection (en pourcentage du prix)
TOUCH_BUFFER_PCT = 0.02      # 0.02% = ~4 ticks NQ a 20000 / ~1 tick ES a 5500
BREAKOUT_BUFFER_PCT = 0.025  # 0.025% = ~5 ticks NQ
RETEST_BUFFER_PCT = 0.025    # 0.025% = ~5 ticks NQ

# Fenetres temporelles (en bars 1min)
WINDOW_TOUCH_TO_BREAKOUT = 60     # 1h max apres touch pour breakout
WINDOW_BREAKOUT_TO_RETEST = 120   # 2h max apres breakout pour retest
WINDOW_RETEST_CONFIRM = 3         # 3 bars apres retest pour confirmation

# SL fallback si swing absent (ticks)
SL_FALLBACK_NQ = 30
SL_FALLBACK_ES = 20
SL_BUFFER_TICKS = 3              # tick au-dela du swing pour SL

OUT_DIR = LOG_DIR.parent / "bot3_continuation"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# STATE MACHINE PAR NIVEAU
# ════════════════════════════════════════════════════════════════════════

@dataclass
class LevelState:
    """Etat machine pour 1 niveau sur 1 jour."""
    state: str = "WAITING_TOUCH"  # WAITING_TOUCH / ARMED / BREAKOUT / WAITING_RETEST
    touch_idx: int = -1
    breakout_idx: int = -1
    retest_idx: int = -1
    level_price: float = 0.0


def _level_price_at(row: pd.Series, level: LevelDef) -> Optional[float]:
    """Reconstruit le prix absolu du niveau a partir de la distance pct.

    dist_*_pct = (level - close) / close * 100  (sign convention)
    → level = close * (1 + dist_pct / 100)
    """
    close = _safe_float(row.get("close"))
    dist = row.get(level.dist_col)
    if close <= 0 or dist is None or pd.isna(dist):
        return None
    try:
        return close * (1 + float(dist) / 100.0)
    except (TypeError, ValueError):
        return None


def detect_continuation_entries(
    df: pd.DataFrame,
    level: LevelDef,
) -> List[Tuple[int, float, float, str]]:
    """Detecte les entries continuation pour 1 niveau sur tout le DF.

    VERSION SIMPLE : 1 seule boucle for, etat track via variables locales.

    Returns liste de (entry_idx, level_price, sl_price, side).

    Logique :
      1. touch (abs dist <= TOUCH_BUFFER_PCT) → ARM (memoriser touch_idx)
      2. breakout (close > level + BREAKOUT_BUFFER) dans 60 bars → BREAKOUT
      3. retest (abs dist <= RETEST_BUFFER) dans 120 bars apres breakout → RETEST
      4. confirmation (long_up/dn_bar==1) dans 3 bars apres retest → ENTRY
      5. SL = swing recent +/- 3 ticks ; entry = close de la bar de confirmation
    """
    entries: List[Tuple[int, float, float, str]] = []
    if level.dist_col not in df.columns:
        return entries

    side = level.side_default
    dates = df["date"].values
    closes = df["close"].values
    dist_vals = df[level.dist_col].values

    confirm_col = "long_up_bar" if side == "LONG" else "long_dn_bar"
    swing_col = "_last_swing_low_price" if side == "LONG" else "_last_swing_high_price"
    has_confirm = confirm_col in df.columns
    has_swing = swing_col in df.columns
    confirm_vals = df[confirm_col].values if has_confirm else None
    swing_vals = df[swing_col].values if has_swing else None

    n = len(df)
    state = "WAITING_TOUCH"
    touch_idx = -1
    breakout_idx = -1
    retest_idx = -1
    level_price_locked = 0.0
    current_day = None

    for i in range(n):
        # Reset au changement de jour
        if dates[i] != current_day:
            state = "WAITING_TOUCH"
            current_day = dates[i]
            touch_idx = -1
            breakout_idx = -1
            retest_idx = -1

        close = closes[i]
        dist_pct = dist_vals[i]
        if close <= 0 or pd.isna(dist_pct):
            continue
        level_price = close * (1 + float(dist_pct) / 100.0)
        dist_abs_pct = abs(float(dist_pct))

        # Transitions
        if state == "WAITING_TOUCH":
            if dist_abs_pct <= TOUCH_BUFFER_PCT:
                state = "ARMED"
                touch_idx = i
                level_price_locked = level_price
            continue

        if state == "ARMED":
            # Timeout
            if i - touch_idx > WINDOW_TOUCH_TO_BREAKOUT:
                state = "WAITING_TOUCH"
                continue
            # Breakout
            if side == "LONG":
                if close > level_price_locked * (1 + BREAKOUT_BUFFER_PCT / 100.0):
                    state = "BREAKOUT"
                    breakout_idx = i
            else:
                if close < level_price_locked * (1 - BREAKOUT_BUFFER_PCT / 100.0):
                    state = "BREAKOUT"
                    breakout_idx = i
            continue

        if state == "BREAKOUT":
            # Timeout
            if i - breakout_idx > WINDOW_BREAKOUT_TO_RETEST:
                state = "WAITING_TOUCH"
                continue
            # Retest
            dist_to_locked = abs(close - level_price_locked) / close * 100.0
            if dist_to_locked <= RETEST_BUFFER_PCT:
                state = "WAITING_RETEST"
                retest_idx = i
            continue

        if state == "WAITING_RETEST":
            # Confirmation dans les 3 bars (retest_idx inclus)
            if i - retest_idx > WINDOW_RETEST_CONFIRM:
                state = "WAITING_TOUCH"
                continue
            if has_confirm:
                cv = confirm_vals[i]
                try:
                    if int(cv) == 1:
                        # ENTRY au close de cette bar
                        entry_close = close
                        if has_swing and not pd.isna(swing_vals[i]):
                            swing = float(swing_vals[i])
                            if side == "LONG" and swing > 0 and swing < entry_close:
                                sl_price = swing - SL_BUFFER_TICKS * TICK_SIZE
                            elif side == "SHORT" and swing > 0 and swing > entry_close:
                                sl_price = swing + SL_BUFFER_TICKS * TICK_SIZE
                            else:
                                sl_fb = SL_FALLBACK_NQ * TICK_SIZE
                                sl_price = entry_close - sl_fb if side == "LONG" else entry_close + sl_fb
                        else:
                            sl_fb = SL_FALLBACK_NQ * TICK_SIZE
                            sl_price = entry_close - sl_fb if side == "LONG" else entry_close + sl_fb
                        entries.append((i, level_price_locked, sl_price, side))
                        # Reset
                        state = "WAITING_TOUCH"
                except (TypeError, ValueError):
                    pass
            continue

    return entries


# ════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION (adapt continuation)
# ════════════════════════════════════════════════════════════════════════

def simulate_continuation_trade(
    df: pd.DataFrame,
    entry_idx: int,
    level: LevelDef,
    side: str,
    sl_price: float,
    target_R: float,
    timeout_bars: int,
    variant_name: str,
    symbol: str,
    trade_id: str,
) -> Optional[Trade]:
    """Simulate trade avec SL pre-calcule (swing-based) et TP R-multiple.

    SL slip toujours adverse. TP slip favorable mais conservative.
    """
    if entry_idx >= len(df) - 1:
        return None

    entry_bar = df.iloc[entry_idx]
    entry_price = _safe_float(entry_bar.get("close"))
    if entry_price <= 0:
        return None
    entry_date = entry_bar["date"]
    session = get_session_label(entry_bar)

    slip_entry_ticks = get_slippage(session, "entry")
    slip_sl_ticks = get_slippage(session, "sl")
    slip_tp_ticks = get_slippage(session, "tp")
    slip_entry = slip_entry_ticks * TICK_SIZE
    slip_sl = slip_sl_ticks * TICK_SIZE
    slip_tp = slip_tp_ticks * TICK_SIZE

    if side == "LONG":
        entry_with_slip = entry_price + slip_entry
        # SL fournit par caller (swing-based), avec slip adverse au fill
        sl_ticks_actual = round((entry_with_slip - sl_price) / TICK_SIZE)
        if sl_ticks_actual < 5:  # safety : SL minimum 5 ticks
            sl_ticks_actual = 5
            sl_price = entry_with_slip - 5 * TICK_SIZE
        tp_price = entry_with_slip + target_R * sl_ticks_actual * TICK_SIZE
    else:
        entry_with_slip = entry_price - slip_entry
        sl_ticks_actual = round((sl_price - entry_with_slip) / TICK_SIZE)
        if sl_ticks_actual < 5:
            sl_ticks_actual = 5
            sl_price = entry_with_slip + 5 * TICK_SIZE
        tp_price = entry_with_slip - target_R * sl_ticks_actual * TICK_SIZE

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
        low = _safe_float(bj.get("low"))
        if h <= 0 or low <= 0:
            continue
        if side == "LONG":
            sl_hit = low <= sl_price
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
            tp_hit = low <= tp_price
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
    tick_value = 1.25 if symbol == "ES" else 0.50
    pnl_dollars_gross = pnl_ticks_gross * tick_value
    pnl_dollars_net = pnl_dollars_gross - COMMISSION_PER_RT
    pnl_R = pnl_ticks_gross / sl_ticks_actual if sl_ticks_actual > 0 else 0.0
    pnl_ticks_net = pnl_dollars_net / tick_value

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
        sl_ticks=int(sl_ticks_actual),
        target_pct=round(target_R, 4),  # store target_R dans target_pct field
        exit_bar_ts=df.iloc[exit_idx]["ts_event"].isoformat(),
        exit_bar_idx=int(exit_idx),
        exit_price=round(exit_price, 4),
        exit_price_with_slip=round(exit_price, 4),
        exit_reason=exit_reason,
        duration_bars=int(exit_idx - entry_idx),
        pnl_ticks_gross=round(pnl_ticks_gross, 2),
        pnl_ticks_net=round(pnl_ticks_net, 2),
        pnl_R=round(pnl_R, 4),
        pnl_dollars_net=round(pnl_dollars_net, 2),
        session_at_entry=session,
        regime_mode_at_entry=str(entry_bar.get("regime_mode", "")),
        regime_favor_at_entry=str(entry_bar.get("regime_favor", "")),
        rvol_at_entry=_safe_float(entry_bar.get("rvol_5", 0.0)),
    )


# ════════════════════════════════════════════════════════════════════════
# RUN VARIANT CONTINUATION
# ════════════════════════════════════════════════════════════════════════

def run_continuation(
    df: pd.DataFrame,
    symbol: str,
    target_R: float,
    use_trend_filter: bool,
    levels: List[LevelDef],
    variant_name: str,
) -> List[Trade]:
    """Run state machine continuation pour tous levels et collecte trades."""
    trades: List[Trade] = []
    sl_fallback = SL_FALLBACK_NQ if symbol == "NQ" else SL_FALLBACK_ES

    # Detection toutes entries (avant filters)
    all_entries: List[Tuple[int, float, float, str, LevelDef]] = []
    for level in levels:
        ents = detect_continuation_entries(df, level)
        for entry_idx, lv_price, sl_price, side in ents:
            all_entries.append((entry_idx, lv_price, sl_price, side, level))

    # Sort par entry_idx pour deduplication (1 trade par bar max)
    all_entries.sort(key=lambda x: x[0])
    last_exit_idx = -1
    trade_counter = 0
    for entry_idx, lv_price, sl_price, side, level in all_entries:
        if entry_idx <= last_exit_idx:
            continue
        row = df.iloc[entry_idx]
        # Filters
        if not filter_news_veto(row, side):
            continue
        if use_trend_filter and not filter_regime_trend_only(row, side):
            continue

        trade_counter += 1
        trade_id = f"{variant_name}_{symbol}_{trade_counter:05d}"
        trade = simulate_continuation_trade(
            df=df,
            entry_idx=entry_idx,
            level=level,
            side=side,
            sl_price=sl_price,
            target_R=target_R,
            timeout_bars=360,
            variant_name=variant_name,
            symbol=symbol,
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
    print(f"OPTION 1 — CONTINUATION POST-RETEST (state machine 4 etats)")
    print(f"{'='*80}\n")

    levels_full = list(LEVELS_V1_LONG) + list(LEVELS_V4_SHORT)
    print(f"Levels actifs : {len(levels_full)} ({len(LEVELS_V1_LONG)} LONG + "
          f"{len(LEVELS_V4_SHORT)} SHORT)\n")

    # Charge datasets
    dfs: Dict[str, pd.DataFrame] = {}
    for sym in ["NQ", "ES"]:
        print(f"[LOAD] {sym}...", flush=True)
        t0 = time.time()
        dfs[sym] = load_v4_enriched(sym)
        print(f"  {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours "
              f"({time.time()-t0:.1f}s)", flush=True)

    R_MULTIPLES = [1.5, 2.0, 3.0]
    results: List[Dict] = []
    for sym in ["NQ", "ES"]:
        for r in R_MULTIPLES:
            for trend_on in (False, True):
                trend_suffix = "_TREND" if trend_on else ""
                name = f"CONT_{sym}_R{r}{trend_suffix}".replace(".", "p")
                t0 = time.time()
                trades = run_continuation(
                    df=dfs[sym],
                    symbol=sym,
                    target_R=r,
                    use_trend_filter=trend_on,
                    levels=levels_full,
                    variant_name=name,
                )
                trades = assign_folds(trades)
                elapsed = time.time() - t0
                metrics = stats_of(trades)
                wf = compute_walk_forward(trades)
                dsr_dict = compute_psr_dsr(trades, n_trials=12)  # 12 buckets
                verdict = verdict_from_metrics(metrics, wf, dsr_dict)
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
                    "trend_filter": trend_on,
                    "verdict": verdict,
                    **metrics,
                    "dsr": dsr_dict["dsr"],
                    "psr": dsr_dict["psr"],
                    "sharpe": dsr_dict["sharpe"],
                    "pf_min_fold": wf["pf_min_fold"],
                    "pf_median_fold": wf["pf_median_fold"],
                    "n_folds_pf_gt_1_3": wf["n_folds_pf_gt_1_3"],
                    "wf_consistency": wf["wf_consistency"],
                    "runtime_sec": round(elapsed, 1),
                }
                results.append(row)
                print(f"  {name:30s} n={metrics['n']:4d} WR={metrics['wr_pct']:5.1f}% "
                      f"PF={metrics['pf']:5.2f} DSR={dsr_dict['dsr']:.3f} {verdict}",
                      flush=True)

    df_res = pd.DataFrame(results)
    csv_path = OUT_DIR / "summary_continuation.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n[CSV] {csv_path}")

    # REPORT
    report = []
    report.append("# Option 1 Phase A — Continuation Post-Retest (state machine)\n")
    report.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    report.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END}")
    report.append(f"Levels : 13 LONG (V1 baseline) + 9 SHORT (V4) = 22 niveaux")
    report.append(f"State machine : touch → breakout (60b) → retest (120b) → confirmation (3b)")
    report.append(f"SL : swing recent +/- 3t (fallback {SL_FALLBACK_NQ}/{SL_FALLBACK_ES}t)")
    report.append(f"DSR haircut : N=12 (12 buckets testes)\n")

    report.append("## TOP par DSR\n")
    df_sorted = df_res.sort_values("dsr", ascending=False)
    report.append("| Bucket | Sym | R | TREND | n | WR% | PF | DSR | PF_min_fold | n_folds_pf>1.3 |")
    report.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in df_sorted.iterrows():
        report.append(
            f"| **{r['bucket']}** | {r['symbol']} | {r['target_R']}R | "
            f"{'YES' if r['trend_filter'] else 'no'} | "
            f"{r['n']} | {r['wr_pct']} | {r['pf']} | {r['dsr']} | "
            f"{r['pf_min_fold']} | {r['n_folds_pf_gt_1_3']}/12 |"
        )

    candidates = df_res[
        (df_res["n"] >= 100) & (df_res["pf"] >= 1.3) & (df_res["dsr"] >= 0.30)
    ].sort_values("dsr", ascending=False)
    report.append("\n## Verdict\n")
    if len(candidates) > 0:
        report.append(f"**GO PHASE B** : {len(candidates)} bucket(s) eligible(s) :")
        for _, r in candidates.iterrows():
            report.append(
                f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}"
            )
    else:
        report.append("**NOGO OPTION 1** : aucun bucket n>=100 ET PF>=1.3 ET DSR>=0.30")
        report.append("\nConclusion : ni FADE (Option 2 NOGO) ni CONTINUATION (Option 1 NOGO)")
        report.append("→ Bot 3 paradigm cassé. Recommandation : kill Bot 3, slot pour BN V4 size++")
        top3 = df_sorted.head(3)
        report.append("\nTop 3 candidats :")
        for _, r in top3.iterrows():
            report.append(
                f"  - {r['bucket']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}"
            )

    report_path = OUT_DIR / "REPORT_CONTINUATION.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(f"[REPORT] {report_path}")

    print(f"\n{'='*80}")
    print(f"TOP 10 par DSR")
    print(f"{'='*80}")
    print(df_sorted[["bucket", "n", "wr_pct", "pf", "dsr", "pf_min_fold"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
