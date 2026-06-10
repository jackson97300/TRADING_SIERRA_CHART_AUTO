"""test_dsr_bias_vwap.py — Validation DSR Lopez du top Round 4 bias_vwap.

Apres re-run Round 4 sur v4_pure complet (oct 2025 -> mai 2026, 194 jours),
le mode `bias_vwap` emerge avec PF median 1.30 sur 32 buckets et PnL +1659R.
Top config : NQ SL=30 bias_vwap n=271 PF 1.42 +102.80R.

Mais Round 4 N'A PAS de DSR Lopez ni walk-forward. On reprend les top
configs, on simule en re-utilisant la logique Round 4, et on calcule PSR/DSR
avec haircut N=32 (32 buckets testes).

OUTPUT : LOGS/bot3_reform/dsr_bias_vwap/REPORT.md
"""
from __future__ import annotations

import glob
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot3_reform_backtester import (
    Trade,
    _safe_float,
    assign_folds,
    compute_psr_dsr,
    compute_walk_forward,
    get_session_label,
    get_slippage,
    stats_of,
    TICK_SIZE,
    COMMISSION_PER_RT,
)
from CORE.research.backtest_bot3_1d_target_v2 import (
    OPEN_WINDOWS_UTC,
    PERIOD_START,
    PERIOD_END,
    load_v4,
    find_first_bar_per_window,
)


# ════════════════════════════════════════════════════════════════════════
# CONFIGS TO TEST (top picks from Round 4)
# ════════════════════════════════════════════════════════════════════════

TOP_CONFIGS = [
    # (sym, sl_ticks, target_min_pct, mode, label)
    ("NQ", 30, 0.0, "bias_vwap", "TOP1_NQ_SL30_BIASVWAP"),
    ("NQ", 30, 0.1, "bias_vwap", "TOP2_NQ_SL30_BIASVWAP_TM01"),
    ("NQ", 60, 0.0, "bias_vwap", "TOP3_NQ_SL60_BIASVWAP"),
    ("NQ", 40, 0.0, "bias_vwap", "NQ_SL40_BIASVWAP"),
    ("ES", 40, 0.5, "always_long", "TOP_ES_SL40_ALONG_TM05"),
    ("ES", 40, 0.5, "bias_vwap", "ES_SL40_BIASVWAP_TM05"),
    ("ES", 30, 0.0, "bias_vwap", "ES_SL30_BIASVWAP"),
    ("ES", 60, 0.5, "bias_vwap", "ES_SL60_BIASVWAP_TM05"),
]


def simulate_round4_trade(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    target_pct: float,
    sl_ticks: int,
    tick: float,
    symbol: str,
    config_name: str,
    timeout_bars: int = 360,
) -> Trade | None:
    """Reproduit logique simulate_trade Round 4 avec anti-triche + slippage."""
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = _safe_float(entry_bar.get("close"))
    if entry_price <= 0:
        return None
    entry_date = entry_bar["date"]
    session = get_session_label(entry_bar)

    slip_entry = get_slippage(session, "entry") * tick
    slip_sl = get_slippage(session, "sl") * tick
    slip_tp = get_slippage(session, "tp") * tick

    if direction == "long":
        entry_with_slip = entry_price + slip_entry
        sl_price = entry_with_slip - sl_ticks * tick
        tp_price = entry_with_slip * (1 + target_pct / 100.0)
    else:
        entry_with_slip = entry_price - slip_entry
        sl_price = entry_with_slip + sl_ticks * tick
        tp_price = entry_with_slip * (1 + target_pct / 100.0)

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
        hj = _safe_float(bj.get("high"))
        lj = _safe_float(bj.get("low"))
        if hj <= 0 or lj <= 0:
            continue
        if direction == "long":
            sl_hit = lj <= sl_price
            tp_hit = hj >= tp_price
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
            sl_hit = hj >= sl_price
            tp_hit = lj <= tp_price
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

    if direction == "long":
        pnl_pts = exit_price - entry_with_slip
    else:
        pnl_pts = entry_with_slip - exit_price
    pnl_ticks_gross = pnl_pts / tick
    tick_value = 1.25 if symbol == "ES" else 0.50
    pnl_dollars_net = pnl_ticks_gross * tick_value - COMMISSION_PER_RT
    pnl_R = pnl_ticks_gross / sl_ticks if sl_ticks > 0 else 0.0

    return Trade(
        trade_id=f"{config_name}_{entry_idx}",
        variant=config_name,
        symbol=symbol,
        level_name="OPEN_WINDOW",
        level_tier=1,
        level_family="WINDOW",
        side=direction.upper(),
        side_original=direction.upper(),
        entry_bar_ts=entry_bar["ts_event"].isoformat(),
        entry_bar_idx=int(entry_idx),
        entry_price=round(entry_price, 4),
        entry_price_with_slip=round(entry_with_slip, 4),
        sl_price=round(sl_price, 4),
        tp_price=round(tp_price, 4),
        sl_ticks=sl_ticks,
        target_pct=round(target_pct, 4),
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
        rvol_at_entry=_safe_float(entry_bar.get("rvol_5", 0.0)),
    )


def run_config(
    df: pd.DataFrame,
    symbol: str,
    sl_ticks: int,
    target_min_pct: float,
    mode: str,
    config_name: str,
    tick: float = 0.25,
) -> List[Trade]:
    """Reproduit la logique Round 4 pour 1 config."""
    trades: List[Trade] = []
    windows = find_first_bar_per_window(df)
    last_exit_idx = -1
    for win_name, idx in windows:
        if idx <= last_exit_idx:
            continue
        bar = df.iloc[idx]
        dmax = _safe_float(bar.get("dist_1d_max_ticks_pct"), 0.0)
        dmin = _safe_float(bar.get("dist_1d_min_ticks_pct"), 0.0)

        if mode == "always_long":
            direction = "long"
            target = dmax
        elif mode == "always_short":
            direction = "short"
            target = dmin
        elif mode == "closest_target":
            if abs(dmax) < abs(dmin):
                direction, target = "long", dmax
            else:
                direction, target = "short", dmin
        elif mode == "bias_vwap":
            slope = _safe_float(bar.get("vwap_slope_10"), 0.0)
            if slope > 0:
                direction, target = "long", dmax
            else:
                direction, target = "short", dmin
        else:
            continue

        if abs(target) < target_min_pct:
            continue
        if direction == "long" and target <= 0:
            continue
        if direction == "short" and target >= 0:
            continue

        trade = simulate_round4_trade(
            df=df,
            entry_idx=idx,
            direction=direction,
            target_pct=target,
            sl_ticks=sl_ticks,
            tick=tick,
            symbol=symbol,
            config_name=config_name,
        )
        if trade is None:
            continue
        trades.append(trade)
        last_exit_idx = trade.exit_bar_idx
    return trades


def main():
    OUT_DIR = ROOT / "LOGS" / "bot3_reform" / "dsr_bias_vwap"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*80}")
    print(f"DSR LOPEZ VALIDATION — top configs Round 4 bias_vwap")
    print(f"{'='*80}\n")

    # Load datasets
    dfs: Dict[str, pd.DataFrame] = {}
    for sym in ["NQ", "ES"]:
        print(f"[LOAD] {sym}...", flush=True)
        t0 = time.time()
        dfs[sym] = load_v4(sym)
        print(f"  {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours "
              f"({time.time()-t0:.1f}s)", flush=True)

    results: List[Dict] = []
    for sym, sl_ticks, target_min_pct, mode, label in TOP_CONFIGS:
        print(f"\n[RUN] {label} (sym={sym} SL={sl_ticks} TM={target_min_pct} mode={mode})...",
              flush=True)
        t0 = time.time()
        trades = run_config(
            df=dfs[sym],
            symbol=sym,
            sl_ticks=sl_ticks,
            target_min_pct=target_min_pct,
            mode=mode,
            config_name=label,
        )
        trades = assign_folds(trades)
        elapsed = time.time() - t0

        metrics = stats_of(trades)
        wf = compute_walk_forward(trades)
        # Haircut N=32 (32 buckets testes initialement dans Round 4 par mode/sl/TM)
        dsr_dict = compute_psr_dsr(trades, n_trials=32)

        # Save trades
        bdir = OUT_DIR / label
        bdir.mkdir(parents=True, exist_ok=True)
        with open(bdir / "trades.jsonl", "w", encoding="utf-8") as f:
            for t in trades:
                f.write(json.dumps(asdict(t)) + "\n")

        row = {
            "label": label,
            "sym": sym,
            "sl_ticks": sl_ticks,
            "target_min_pct": target_min_pct,
            "mode": mode,
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
        print(f"  n={metrics['n']:4d} WR={metrics['wr_pct']:5.1f}% "
              f"PF={metrics['pf']:5.2f} PnL={metrics['pnl_R_total']:+7.2f}R "
              f"DSR={dsr_dict['dsr']:.3f} PF_min_fold={wf['pf_min_fold']:.2f}",
              flush=True)

    # CSV + REPORT
    df_res = pd.DataFrame(results)
    csv_path = OUT_DIR / "summary_dsr.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n[CSV] {csv_path}", flush=True)

    report = []
    report.append("# DSR Lopez Validation — Round 4 bias_vwap top configs\n")
    report.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    report.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END}")
    report.append(f"Source : v4_pure (oct 2025 -> mai 2026, 194 jours)")
    report.append(f"Haircut DSR : N=32 trials (Round 4 = 32 buckets par mode/sl/TM)")
    report.append(f"\nMode bias_vwap : si vwap_slope_10 > 0 → LONG vers 1d_max ; "
                  "sinon → SHORT vers 1d_min\n")

    report.append("## Resultats\n")
    df_sorted = df_res.sort_values("dsr", ascending=False)
    report.append("| Config | Sym | SL | TM | Mode | n | WR% | PF | PnL_R | DSR | PF_min_fold | "
                  "n_folds_pf>1.3 |")
    report.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in df_sorted.iterrows():
        report.append(
            f"| **{r['label']}** | {r['sym']} | {r['sl_ticks']}t | {r['target_min_pct']} | "
            f"{r['mode']} | {r['n']} | {r['wr_pct']} | {r['pf']} | {r['pnl_R_total']} | "
            f"{r['dsr']} | {r['pf_min_fold']} | {r['n_folds_pf_gt_1_3']}/12 |"
        )

    candidates = df_res[
        (df_res["n"] >= 100) & (df_res["pf"] >= 1.3) & (df_res["dsr"] >= 0.30)
    ].sort_values("dsr", ascending=False)
    report.append("\n## Verdict\n")
    if len(candidates) > 0:
        report.append(f"**GO PHASE B** : {len(candidates)} bucket(s) eligible(s) :")
        for _, r in candidates.iterrows():
            report.append(
                f"  - {r['label']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}"
            )
    else:
        report.append("**NOGO** : aucun bucket n>=100 ET PF>=1.3 ET DSR>=0.30")
        top3 = df_sorted.head(3)
        report.append("\nTop 3 :")
        for _, r in top3.iterrows():
            report.append(
                f"  - {r['label']} : n={r['n']}, PF={r['pf']}, DSR={r['dsr']}, "
                f"PF_min_fold={r['pf_min_fold']}"
            )

    report_path = OUT_DIR / "REPORT.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(f"[REPORT] {report_path}\n", flush=True)

    print(f"\n{'='*80}")
    print("FINAL")
    print(f"{'='*80}")
    print(df_sorted[["label", "n", "wr_pct", "pf", "dsr", "pf_min_fold"]].to_string(index=False))


if __name__ == "__main__":
    main()
