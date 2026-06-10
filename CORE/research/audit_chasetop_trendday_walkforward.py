"""audit_chasetop_trendday_walkforward.py — Audit empirique ChaseTopGate + TREND DAY.

Demande Jackson 07/05 : Bot 1+2 V6 = 0 trade le 06/05 a cause du filtre defensif
ChaseTopGate (range_pos >= 60% bloque LONG) + Conseil ATTENDRE. Audit Lopez-compliant
pour calibrer empiriquement le seuil et detecter trend days ou la regle s'inverse.

Methodologie :
  1. Pour chaque bar (i) du dataset v5e clean : simule LONG et SHORT entry path-aware
     scan high/low forward 60 bars avec TP=30t, SL=30t (R:R 1.0 baseline).
  2. Bin par pct_in_range (10% bins 0-100).
  3. Calcule WR + mean_pnl_ticks + Sharpe par bin × direction × trend_day_flag.
  4. Detection trend day : pct_in_range mediane >=80% (ou <=20% pour SHORT trend) sur
     fenetre 60 bars avant le bar i.
  5. Walk-forward 12 folds chronologiques (1 an / 12 = 1 mois par fold).
  6. Bootstrap CI 1000 sur les metriques (Lopez ch.4 sample weight uniqueness fait par
     dataset_builder, pas re-applique ici).

Output : tableau recommandations seuils ChaseTopGate.

Run : python -X utf8 CORE/research/audit_chasetop_trendday_walkforward.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
DATASETS_DIR = ROOT / "DATA" / "DATASETS"
OUT_DIR = ROOT / "DATA"

# ─── Config ────────────────────────────────────────────────────────────────
HORIZON_BARS = 60
TICK_SIZE = 0.25
SLIPPAGE_TICKS = 2.0

# TP/SL ticks pour simulation (R:R 1.0 baseline = neutre, isole l'effet range_pos)
TP_TICKS = 30
SL_TICKS = 30

# Bins pct_in_range
RANGE_BINS = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50),
              (50, 60), (60, 70), (70, 80), (80, 90), (90, 100)]

# Trend day detection : sur les 60 bars precedant bar i, pct_in_range median >= 80
TREND_DAY_LOOKBACK_BARS = 60
TREND_DAY_RANGE_POS_THRESHOLD = 80.0  # LONG trend day
TREND_DAY_SHORT_THRESHOLD = 20.0       # SHORT trend day (mirror)

# Walk-forward
N_FOLDS = 12
N_BOOTSTRAP = 1000


def compute_path_outcomes(closes, highs, lows, fires_idx, dir_value,
                          sl_ticks, tp_ticks):
    """Path-aware outcome simulation."""
    n = len(closes)
    sl_pts = sl_ticks * TICK_SIZE
    tp_pts = tp_ticks * TICK_SIZE
    outcomes = np.zeros(len(fires_idx), dtype=np.int8)
    pnl_ticks_list = np.zeros(len(fires_idx), dtype=np.float32)

    for k, i in enumerate(fires_idx):
        if i + HORIZON_BARS >= n:
            outcomes[k] = -99
            continue
        entry = closes[i]
        if dir_value == 1:
            tp_target = entry + tp_pts
            sl_target = entry - sl_pts
        else:
            tp_target = entry - tp_pts
            sl_target = entry + sl_pts

        outcome = 0  # TIMEOUT
        for j in range(1, HORIZON_BARS + 1):
            h = highs[i + j]
            l = lows[i + j]
            if dir_value == 1:
                if l <= sl_target:
                    outcome = -1
                    break
                if h >= tp_target:
                    outcome = 1
                    break
            else:
                if h >= sl_target:
                    outcome = -1
                    break
                if l <= tp_target:
                    outcome = 1
                    break

        outcomes[k] = outcome
        if outcome == 1:
            pnl_ticks_list[k] = tp_ticks - SLIPPAGE_TICKS
        elif outcome == -1:
            pnl_ticks_list[k] = -sl_ticks - SLIPPAGE_TICKS
        else:
            timeout_pnl = (closes[i + HORIZON_BARS] - entry) * dir_value
            pnl_ticks_list[k] = (timeout_pnl / TICK_SIZE) - SLIPPAGE_TICKS
    valid_mask = outcomes != -99
    return outcomes[valid_mask], pnl_ticks_list[valid_mask], fires_idx[valid_mask]


def detect_trend_day(pct_in_range, lookback=TREND_DAY_LOOKBACK_BARS):
    """Pour chaque bar, calcule median pct_in_range sur lookback bars.
    Trend LONG day si median >= 80, SHORT day si <= 20.
    """
    s = pd.Series(pct_in_range).rolling(lookback, min_periods=lookback // 2).median()
    is_trend_long = (s >= TREND_DAY_RANGE_POS_THRESHOLD).fillna(False).values
    is_trend_short = (s <= TREND_DAY_SHORT_THRESHOLD).fillna(False).values
    return is_trend_long, is_trend_short


def bootstrap_ci(arr, n_boot=N_BOOTSTRAP, ci=0.95):
    if len(arr) < 10:
        return (np.nan, np.nan)
    rng = np.random.default_rng(42)
    boots = np.array([
        np.mean(rng.choice(arr, size=len(arr), replace=True))
        for _ in range(n_boot)
    ])
    lo = np.percentile(boots, (1 - ci) / 2 * 100)
    hi = np.percentile(boots, (1 + ci) / 2 * 100)
    return (lo, hi)


def analyze_bin(pnl_arr, outcomes_arr):
    if len(pnl_arr) < 30:
        return None
    wr = float((outcomes_arr == 1).mean())
    sl_rate = float((outcomes_arr == -1).mean())
    to_rate = float((outcomes_arr == 0).mean())
    mean_pnl = float(pnl_arr.mean())
    sharpe = float(pnl_arr.mean() / (pnl_arr.std() + 1e-9))
    ci_low, ci_high = bootstrap_ci(pnl_arr)
    return {
        "n": len(pnl_arr),
        "wr": round(wr * 100, 1),
        "sl_rate": round(sl_rate * 100, 1),
        "to_rate": round(to_rate * 100, 1),
        "mean_pnl_ticks": round(mean_pnl, 2),
        "sharpe": round(sharpe, 3),
        "ci_low": round(ci_low, 2) if not np.isnan(ci_low) else None,
        "ci_high": round(ci_high, 2) if not np.isnan(ci_high) else None,
    }


def run_audit(symbol):
    print(f"\n{'='*100}")
    print(f"  AUDIT {symbol} — ChaseTopGate + TREND DAY walk-forward")
    print(f"{'='*100}")

    fp = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    if not fp.exists():
        print(f"  SKIP — fichier {fp} introuvable")
        return None

    print(f"  Loading {fp.name}...")
    t0 = time.time()
    df = pd.read_parquet(fp)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"  Loaded in {time.time()-t0:.1f}s, shape {df.shape}")

    # Filtrer pct_in_range valide
    mask_pct = df["pct_in_range"].notna() & (df["pct_in_range"] >= 0) & (df["pct_in_range"] <= 100)
    df_valid = df[mask_pct].reset_index(drop=True)
    print(f"  Bars valid pct_in_range : {len(df_valid)} / {len(df)}")

    closes = df_valid["close"].values.astype(np.float64)
    highs = df_valid["high"].values.astype(np.float64)
    lows = df_valid["low"].values.astype(np.float64)
    pct_range = df_valid["pct_in_range"].values.astype(np.float64)

    # Trend day flags
    is_trend_long, is_trend_short = detect_trend_day(pct_range)
    print(f"  Trend LONG days bars : {is_trend_long.sum()} ({100*is_trend_long.mean():.1f}%)")
    print(f"  Trend SHORT days bars : {is_trend_short.sum()} ({100*is_trend_short.mean():.1f}%)")

    # Simule LONG et SHORT pour TOUS les bars
    all_idx = np.arange(len(df_valid))
    print(f"  Simulating LONG outcomes...")
    t0 = time.time()
    out_long, pnl_long, valid_long = compute_path_outcomes(
        closes, highs, lows, all_idx, dir_value=1,
        sl_ticks=SL_TICKS, tp_ticks=TP_TICKS)
    print(f"  Done in {time.time()-t0:.1f}s, n={len(pnl_long)}")
    print(f"  Simulating SHORT outcomes...")
    t0 = time.time()
    out_short, pnl_short, valid_short = compute_path_outcomes(
        closes, highs, lows, all_idx, dir_value=-1,
        sl_ticks=SL_TICKS, tp_ticks=TP_TICKS)
    print(f"  Done in {time.time()-t0:.1f}s, n={len(pnl_short)}")

    # ─── Analyse 1 : WR par bin pct_in_range × direction (full data) ──────
    print(f"\n  ─── ANALYSIS 1 : WR par bin pct_in_range × direction (full data) ───")
    print(f"  {'Bin':<10} | {'LONG n':<7} | LONG WR | LONG mean_pnl | {'SHORT n':<8} | SHORT WR | SHORT mean_pnl")
    rows_a = []
    for lo, hi in RANGE_BINS:
        mask = (pct_range[valid_long] >= lo) & (pct_range[valid_long] < (hi + 0.001 if hi == 100 else hi))
        if mask.sum() < 30:
            continue
        long_stats = analyze_bin(pnl_long[mask], out_long[mask])
        mask_s = (pct_range[valid_short] >= lo) & (pct_range[valid_short] < (hi + 0.001 if hi == 100 else hi))
        short_stats = analyze_bin(pnl_short[mask_s], out_short[mask_s])
        if long_stats and short_stats:
            print(f"  {lo:>3}-{hi:<3}%  | {long_stats['n']:>6d}  | {long_stats['wr']:>5.1f}% | {long_stats['mean_pnl_ticks']:>+8.2f}t   | "
                  f"{short_stats['n']:>7d}  | {short_stats['wr']:>5.1f}%  | {short_stats['mean_pnl_ticks']:>+8.2f}t")
            rows_a.append({
                "bin_lo": lo, "bin_hi": hi,
                "long": long_stats, "short": short_stats,
            })

    # ─── Analyse 2 : trend day vs non-trend day (LONG seulement) ─────────
    print(f"\n  ─── ANALYSIS 2 : LONG en TREND LONG day (pct_range median >=80% sur 60bars) vs autres ───")
    is_trend_long_at_valid = is_trend_long[valid_long]
    print(f"  {'Bin':<10} | {'TrendDay n':<11} | TD WR | TD mean_pnl | {'NonTrend n':<11} | NT WR | NT mean_pnl | DELTA")
    for lo, hi in RANGE_BINS:
        if hi <= 50:
            continue  # Trend LONG day = range_pos haut, ne s'applique qu'aux bins haut
        mask_bin = (pct_range[valid_long] >= lo) & (pct_range[valid_long] < (hi + 0.001 if hi == 100 else hi))
        mask_td = mask_bin & is_trend_long_at_valid
        mask_nt = mask_bin & ~is_trend_long_at_valid
        td_stats = analyze_bin(pnl_long[mask_td], out_long[mask_td])
        nt_stats = analyze_bin(pnl_long[mask_nt], out_long[mask_nt])
        if td_stats and nt_stats:
            delta = td_stats["mean_pnl_ticks"] - nt_stats["mean_pnl_ticks"]
            print(f"  {lo:>3}-{hi:<3}%  | {td_stats['n']:>10d}  | {td_stats['wr']:>5.1f}% | {td_stats['mean_pnl_ticks']:>+8.2f}t  | "
                  f"{nt_stats['n']:>10d}  | {nt_stats['wr']:>5.1f}% | {nt_stats['mean_pnl_ticks']:>+8.2f}t  | {delta:>+6.2f}t")

    # ─── Analyse 3 : walk-forward stability (12 folds chronologiques) ───
    print(f"\n  ─── ANALYSIS 3 : walk-forward 12 folds — stabilite seuil ChaseTopGate=60% LONG ───")
    fold_size = len(df_valid) // N_FOLDS
    print(f"  {'Fold':<6} | LONG_60_100 n | WR | mean_pnl | LONG_0_60 n | WR | mean_pnl | DELTA(60-100 vs 0-60)")
    for f in range(N_FOLDS):
        f_start = f * fold_size
        f_end = (f + 1) * fold_size if f < N_FOLDS - 1 else len(df_valid)
        fold_idx = np.arange(f_start, f_end)
        # Filter aux indices effectivement simules (valid_long ⊂ all_idx)
        # Map valid_long → position dans pnl_long array
        vl_set = set(valid_long.tolist())
        in_fold_mask = np.array([i in vl_set and f_start <= i < f_end for i in valid_long])
        if in_fold_mask.sum() < 100:
            continue
        pct_fold = pct_range[valid_long][in_fold_mask]
        out_fold = out_long[in_fold_mask]
        pnl_fold = pnl_long[in_fold_mask]
        m_high = pct_fold >= 60
        m_low = pct_fold < 60
        h_stats = analyze_bin(pnl_fold[m_high], out_fold[m_high])
        l_stats = analyze_bin(pnl_fold[m_low], out_fold[m_low])
        if h_stats and l_stats:
            delta = h_stats["mean_pnl_ticks"] - l_stats["mean_pnl_ticks"]
            print(f"  fold{f+1:<2}  | {h_stats['n']:>11d}  | {h_stats['wr']:>5.1f}% | {h_stats['mean_pnl_ticks']:>+7.2f}t | "
                  f"{l_stats['n']:>10d}  | {l_stats['wr']:>5.1f}% | {l_stats['mean_pnl_ticks']:>+7.2f}t | {delta:>+6.2f}t")

    return {
        "symbol": symbol,
        "n_bars": len(df_valid),
        "n_trend_long_bars": int(is_trend_long.sum()),
        "n_trend_short_bars": int(is_trend_short.sum()),
        "rows_full": rows_a,
    }


def main():
    print("=" * 100)
    print("  AUDIT ChaseTopGate + TREND DAY")
    print("  Methodologie : path-aware forward 60bars, R:R 1.0 baseline, walk-forward 12 folds")
    print("=" * 100)
    results = {}
    for sym in ("ES", "NQ"):
        r = run_audit(sym)
        if r is not None:
            results[sym] = r

    out_fp = OUT_DIR / f"audit_chasetop_trendday_{int(time.time())}.json"
    out_fp.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\n  Report : {out_fp}")


if __name__ == "__main__":
    main()
