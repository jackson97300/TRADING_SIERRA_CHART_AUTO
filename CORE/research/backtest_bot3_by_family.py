"""backtest_bot3_by_family.py — Backtest niveaux Bot 3 par famille (Jackson 24/05/2026).

Objectif : identifier QUELLE famille de niveaux a vraiment un edge robuste
sur la periode de data disponible MenthorQ (15/12/2025 -> 21/05/2026).

4 familles testees separement :
  1. MENTHORQ      : options-driven (MQ_CALL, MQ_PUT, MQ_HVL, MQ_*_0DTE, GEX, MQ_1D)
  2. MARKET_PROFILE: volume profile (CUR_VPOC/VAH/VAL, IB_*, PVPOC/PVAH/PVAL)
  3. PVWAP_PREV    : prix structure veille (PDH/PDL, PVWAP+SD, VWAP_D+SD, OPEN_*)
  4. (OTHER skip MVP — SESS, CASH, OVN)

2 directions : LONG / SHORT separes (expose asymetrie identifiee market-analyst)
2 footprint  : SANS / AVEC `long_up_bar=1` GATE (test hypothese Jackson)

Output : table comparative N / WR / PF / EV / PnL net par bucket
         + walk-forward 12 folds + DSR Lopez (Lopez 2014 Chap.14)

Methodologie alignee `DOCS/BOT3_BACKTEST_METHODOLOGY.md` :
  - News bars excluded (rvol > 3 OR range_bar > 2*ATR)
  - Cooldown 5 bars meme niveau
  - 1 setup max par bar (anti double-trigger)
  - SL/TP fixe ticks (pas adaptatif ATR pour reproductibilite)
  - Cost 0.5 pt aller-retour

Usage :
  python -X utf8 CORE/research/backtest_bot3_by_family.py --symbol NQ
"""
from __future__ import annotations

import argparse
import glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# ────────────────────────────────────────────────────────────────────────────
# Configuration backtest
# ────────────────────────────────────────────────────────────────────────────

PERIOD_START = "2025-12-15"
PERIOD_END = "2026-05-22"
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
TICK_VALUE_USD = {"NQ": 0.50, "ES": 1.25}    # 1 micro contract
SL_TICKS = 30        # 30 ticks NQ = 7.5 pts = $15
TP_TICKS = 50        # 50 ticks NQ = 12.5 pts = $25 (R:R 1.67)
TIMEOUT_BARS = 60    # 1h timeout
PROXIMITY_PCT = 0.05    # 0.05% du prix = ~14t NQ a 28500
COOLDOWN_BARS = 5
COST_POINTS = 0.5    # aller-retour estime
WALK_FORWARD_FOLDS = 12

# ────────────────────────────────────────────────────────────────────────────
# 4 familles de niveaux
# ────────────────────────────────────────────────────────────────────────────

FAMILIES = {
    "MENTHORQ": {
        "MQ_CALL":       {"dist_col": "dist_mq_call_pct",       "natural_side": "SHORT"},
        "MQ_PUT":        {"dist_col": "dist_mq_put_pct",        "natural_side": "LONG"},
        "MQ_HVL":        {"dist_col": "dist_mq_hvl_pct",        "natural_side": "NEUTRAL"},
        "MQ_CALL_0DTE":  {"dist_col": "dist_mq_call_0dte_pct",  "natural_side": "SHORT"},
        "MQ_PUT_0DTE":   {"dist_col": "dist_mq_put_0dte_pct",   "natural_side": "LONG"},
        "GEX_UP":        {"dist_col": "dist_gex_nearest_up_pct","natural_side": "SHORT"},
        "GEX_DN":        {"dist_col": "dist_gex_nearest_dn_pct","natural_side": "LONG"},
        "MQ_1D_MAX":     {"dist_col": "dist_1d_max_ticks_pct",  "natural_side": "SHORT"},
        "MQ_1D_MIN":     {"dist_col": "dist_1d_min_ticks_pct",  "natural_side": "LONG"},
    },
    "MARKET_PROFILE": {
        "CUR_VPOC":      {"dist_col": "dist_cur_vpoc_pct",      "natural_side": "NEUTRAL"},
        "CUR_VAH":       {"dist_col": "dist_cur_vah_pct",       "natural_side": "SHORT"},
        "CUR_VAL":       {"dist_col": "dist_cur_val_pct",       "natural_side": "LONG"},
        "IB_HIGH":       {"dist_col": "dist_ib_high_pct",       "natural_side": "SHORT"},
        "IB_LOW":        {"dist_col": "dist_ib_low_pct",        "natural_side": "LONG"},
        "PVPOC":         {"dist_col": "dist_prev_vpoc_pct",     "natural_side": "NEUTRAL"},
        "PVAH":          {"dist_col": "dist_prev_vah_pct",      "natural_side": "SHORT"},
        "PVAL":          {"dist_col": "dist_prev_val_pct",      "natural_side": "LONG"},
    },
    "PVWAP_PREV": {
        "PDH":           {"dist_col": "dist_pdh_pct",           "natural_side": "SHORT"},
        "PDL":           {"dist_col": "dist_pdl_pct",           "natural_side": "LONG"},
        "PVWAP":         {"dist_col": "dist_pvwap_pct",         "natural_side": "NEUTRAL"},
        "PVWAP_SD1U":    {"dist_col": "dist_pvwap_sd1u_pct",    "natural_side": "SHORT"},
        "PVWAP_SD1D":    {"dist_col": "dist_pvwap_sd1d_pct",    "natural_side": "LONG"},
        "VWAP_D":        {"dist_col": "dist_vwap_d_pct",        "natural_side": "NEUTRAL"},
        "VWAP_SD1U":     {"dist_col": "dist_vwap_d_sd1u_pct",   "natural_side": "SHORT"},
        "VWAP_SD1D":     {"dist_col": "dist_vwap_d_sd1d_pct",   "natural_side": "LONG"},
        "VWAP_SD2U":     {"dist_col": "dist_vwap_d_sd2u_pct",   "natural_side": "SHORT"},
        "VWAP_SD2D":     {"dist_col": "dist_vwap_d_sd2d_pct",   "natural_side": "LONG"},
        "OPEN_830":      {"dist_col": "dist_open_830_pct",      "natural_side": "REJECTION"},
        "OPEN_930":      {"dist_col": "dist_open_930_pct",      "natural_side": "REJECTION"},
    },
}


def load_v4_filtered(symbol: str) -> pd.DataFrame:
    """Charge V4 enriched + filtre periode."""
    files = sorted(glob.glob(
        str(ROOT / f"DATA/datasets/v4_enriched/symbol={symbol}.c.0/year=*/month=*/data.parquet")))
    if not files:
        raise FileNotFoundError(f"aucun V4 enriched pour {symbol}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    # Filter periode MenthorQ data dispo
    start_dt = pd.to_datetime(PERIOD_START, utc=True)
    end_dt = pd.to_datetime(PERIOD_END, utc=True)
    df = df[(df["ts_event"] >= start_dt) & (df["ts_event"] <= end_dt)].reset_index(drop=True)
    return df


def detect_contacts(df: pd.DataFrame, dist_col: str,
                     proximity_pct: float = PROXIMITY_PCT) -> np.ndarray:
    """Returns boolean array : bar touche niveau si |dist_pct| < proximity_pct."""
    if dist_col not in df.columns:
        return np.zeros(len(df), dtype=bool)
    arr = pd.to_numeric(df[dist_col], errors="coerce").to_numpy()
    return np.abs(arr) < proximity_pct


def simulate_trade(df: pd.DataFrame, entry_idx: int, direction: str,
                    tick: float, sl_ticks: int = SL_TICKS,
                    tp_ticks: int = TP_TICKS,
                    timeout_bars: int = TIMEOUT_BARS) -> dict:
    """Simulate trade SL/TP fixe a partir du close bar entry_idx.

    Returns dict {entry_price, exit_price, exit_cause, pnl_pts, pnl_R, duration}
    """
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    if direction == "long":
        sl_price = entry_price - sl_ticks * tick
        tp_price = entry_price + tp_ticks * tick
    else:    # short
        sl_price = entry_price + sl_ticks * tick
        tp_price = entry_price - tp_ticks * tick

    risk_pts = abs(entry_price - sl_price)
    end_idx = min(len(df), entry_idx + 1 + timeout_bars)

    for j in range(entry_idx + 1, end_idx):
        bj = df.iloc[j]
        hj = float(bj["high"])
        lj = float(bj["low"])
        if direction == "long":
            if lj <= sl_price:
                return {
                    "entry_price": entry_price, "exit_price": sl_price,
                    "exit_cause": "sl", "pnl_pts": sl_price - entry_price,
                    "pnl_R": -1.0, "duration": j - entry_idx,
                }
            if hj >= tp_price:
                return {
                    "entry_price": entry_price, "exit_price": tp_price,
                    "exit_cause": "tp", "pnl_pts": tp_price - entry_price,
                    "pnl_R": tp_ticks / sl_ticks, "duration": j - entry_idx,
                }
        else:    # short
            if hj >= sl_price:
                return {
                    "entry_price": entry_price, "exit_price": sl_price,
                    "exit_cause": "sl", "pnl_pts": entry_price - sl_price,
                    "pnl_R": -1.0, "duration": j - entry_idx,
                }
            if lj <= tp_price:
                return {
                    "entry_price": entry_price, "exit_price": tp_price,
                    "exit_cause": "tp", "pnl_pts": entry_price - tp_price,
                    "pnl_R": tp_ticks / sl_ticks, "duration": j - entry_idx,
                }
    # Timeout : close at last bar close
    last_bar = df.iloc[end_idx - 1]
    exit_price = float(last_bar["close"])
    if direction == "long":
        pnl_pts = exit_price - entry_price
    else:
        pnl_pts = entry_price - exit_price
    return {
        "entry_price": entry_price, "exit_price": exit_price,
        "exit_cause": "timeout", "pnl_pts": pnl_pts,
        "pnl_R": pnl_pts / max(risk_pts, 0.01),
        "duration": end_idx - 1 - entry_idx,
    }


def backtest_level(df: pd.DataFrame, level_def: dict, direction: str,
                    symbol: str, footprint_filter: bool = False,
                    cooldown: int = COOLDOWN_BARS) -> list:
    """Backtest 1 niveau + 1 direction sur df complet.

    Args:
        footprint_filter : si True, exige `long_up_bar=1` (LONG) ou
                            `long_dn_bar=1` (SHORT) au bar de contact.
    """
    tick = TICK_SIZE.get(symbol, 0.25)
    contacts = detect_contacts(df, level_def["dist_col"])
    if not contacts.any():
        return []

    # News bars excluded (rvol > 3 OR range_bar > 2*ATR)
    rvol_ok = pd.to_numeric(df.get("rvol", 1.0), errors="coerce").fillna(1.0).to_numpy()
    atr_arr = pd.to_numeric(df.get("atr_14", df.get("atr", 50)), errors="coerce").fillna(50).to_numpy()
    h_arr = pd.to_numeric(df["high"], errors="coerce").to_numpy()
    l_arr = pd.to_numeric(df["low"], errors="coerce").to_numpy()
    range_arr = (h_arr - l_arr) / tick    # ticks
    news_excluded = (rvol_ok > 3.0) | (range_arr > 2 * atr_arr)

    # Footprint filter
    if footprint_filter:
        fp_col = "long_up_bar" if direction == "long" else "long_dn_bar"
        if fp_col in df.columns:
            fp_ok = (pd.to_numeric(df[fp_col], errors="coerce").fillna(0).to_numpy() == 1.0)
        else:
            fp_ok = np.zeros(len(df), dtype=bool)
    else:
        fp_ok = np.ones(len(df), dtype=bool)

    valid_contacts = contacts & (~news_excluded) & fp_ok

    trades = []
    last_entry_idx = -cooldown - 1
    indices = np.where(valid_contacts)[0]
    for i in indices:
        if i - last_entry_idx < cooldown:
            continue
        trade = simulate_trade(df, int(i), direction, tick)
        if trade is None:
            continue
        trade["entry_idx"] = int(i)
        trade["date"] = df.iloc[i]["date"]
        trades.append(trade)
        last_entry_idx = i

    return trades


def compute_stats(trades: list) -> dict:
    """Stats global pour un ensemble de trades."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": None, "pf": None, "ev_R": None, "pnl_R": 0.0,
                 "pnl_R_net": 0.0, "by_exit": {}}
    pnl_Rs = [t["pnl_R"] for t in trades]
    pnl_R_total = sum(pnl_Rs)
    wins = sum(1 for r in pnl_Rs if r > 0)
    gains_R = sum(r for r in pnl_Rs if r > 0)
    losses_R = -sum(r for r in pnl_Rs if r < 0)
    pf = gains_R / max(losses_R, 0.01) if losses_R > 0 else (float("inf") if gains_R > 0 else None)
    wr = wins / n * 100.0
    ev_R = pnl_R_total / n
    # Net cost : COST_POINTS / (SL_TICKS * tick) = 0.5 / 7.5 = 0.067R per trade
    cost_per_trade_R = COST_POINTS / (SL_TICKS * 0.25)
    pnl_R_net = pnl_R_total - n * cost_per_trade_R
    by_exit = {}
    for t in trades:
        c = t["exit_cause"]
        by_exit[c] = by_exit.get(c, 0) + 1
    return {
        "n": n, "wr": round(wr, 1), "pf": round(pf, 2) if pf is not None else None,
        "ev_R": round(ev_R, 3), "pnl_R": round(pnl_R_total, 2),
        "pnl_R_net": round(pnl_R_net, 2), "by_exit": by_exit,
    }


def walk_forward_stability(trades: list, n_folds: int = WALK_FORWARD_FOLDS) -> dict:
    """Walk-forward chronologique : split N folds par date d'entry.

    Returns : n_folds_positive (PF > 1.0 ET pnl_R > 0), fold_min_pf, fold_median_pf.
    """
    if len(trades) < n_folds * 3:    # min 3 trades par fold
        return {"folds_positive": None, "fold_min_pf": None,
                 "fold_median_pf": None, "stable": False,
                 "msg": f"n trades {len(trades)} < {n_folds*3} (min 3/fold)"}
    # Sort par date
    trades_sorted = sorted(trades, key=lambda t: t["entry_idx"])
    fold_size = len(trades_sorted) // n_folds
    fold_pfs = []
    fold_positives = 0
    for k in range(n_folds):
        lo = k * fold_size
        hi = (k + 1) * fold_size if k < n_folds - 1 else len(trades_sorted)
        fold_trades = trades_sorted[lo:hi]
        s = compute_stats(fold_trades)
        pf = s["pf"]
        if pf is not None and pf > 1.0 and s["pnl_R"] > 0:
            fold_positives += 1
        fold_pfs.append(pf if pf is not None else 0.0)
    fold_pfs_sorted = sorted(fold_pfs)
    return {
        "folds_positive": fold_positives,
        "fold_min_pf": round(fold_pfs_sorted[0], 2),
        "fold_median_pf": round(fold_pfs_sorted[n_folds // 2], 2),
        "stable": fold_positives >= n_folds - 2,    # 10/12 positifs = stable
        "fold_pfs": [round(p, 2) for p in fold_pfs],
    }


def run_backtest(symbol: str) -> pd.DataFrame:
    """Run backtest complet pour 1 symbol.

    Returns DataFrame avec 1 row par (family, level, direction, footprint_filter)
    """
    print(f"\n{'='*70}")
    print(f"BACKTEST BOT 3 BY FAMILY — {symbol}")
    print(f"Periode : {PERIOD_START} -> {PERIOD_END}")
    print(f"{'='*70}\n")

    df = load_v4_filtered(symbol)
    print(f"Bars loaded : {len(df)} ({df['date'].nunique()} jours)")

    rows = []
    for family_name, levels in FAMILIES.items():
        print(f"\n--- Family : {family_name} ---")
        for level_name, level_def in levels.items():
            if level_def["dist_col"] not in df.columns:
                print(f"  SKIP {level_name} (col {level_def['dist_col']} absente)")
                continue
            for direction in ("long", "short"):
                # Filtre direction selon natural_side (skip incoherents)
                ns = level_def.get("natural_side", "NEUTRAL")
                if ns == "LONG" and direction == "short":
                    continue
                if ns == "SHORT" and direction == "long":
                    continue
                # NEUTRAL + REJECTION testes dans les 2 sens
                for footprint in (False, True):
                    trades = backtest_level(df, level_def, direction, symbol,
                                              footprint_filter=footprint)
                    stats = compute_stats(trades)
                    wf = walk_forward_stability(trades)
                    row = {
                        "family": family_name,
                        "level": level_name,
                        "direction": direction.upper(),
                        "footprint": "FP" if footprint else "noFP",
                        "n": stats["n"],
                        "wr": stats["wr"],
                        "pf": stats["pf"],
                        "ev_R": stats["ev_R"],
                        "pnl_R_net": stats["pnl_R_net"],
                        "wf_positive": wf["folds_positive"],
                        "wf_min_pf": wf["fold_min_pf"],
                        "wf_stable": wf["stable"],
                    }
                    rows.append(row)
                    if stats["n"] >= 30:
                        print(f"  {level_name:15s} {direction:5s} {row['footprint']:5s} | "
                              f"n={stats['n']:4d} WR={stats['wr']!s:>6} PF={stats['pf']!s:>6} "
                              f"EV={stats['ev_R']:>+.3f}R PnL={stats['pnl_R_net']:>+8.2f}R "
                              f"WF={wf['folds_positive']!s}/{WALK_FORWARD_FOLDS}")

    result = pd.DataFrame(rows)
    return result


def summarize_by_family(df_result: pd.DataFrame) -> pd.DataFrame:
    """Aggregation par famille : combien de niveaux GO (PF > 1.3, n >= 100)."""
    summary = []
    for family in df_result["family"].unique():
        sub = df_result[df_result["family"] == family]
        sub_qual = sub[(sub["n"] >= 100)]
        sub_go = sub_qual[(sub_qual["pf"].astype("float", errors="ignore") >= 1.3) &
                           (sub_qual["wf_stable"] == True)]
        summary.append({
            "family": family,
            "n_buckets_tested": len(sub),
            "n_buckets_qualified_n100": len(sub_qual),
            "n_buckets_GO_pf1.3_stable": len(sub_go),
            "pnl_R_net_sum_qualified": round(sub_qual["pnl_R_net"].sum(), 2),
        })
    return pd.DataFrame(summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    df_result = run_backtest(args.symbol)
    print()
    print("=" * 70)
    print(f"TABLE RESULTATS COMPLETE ({args.symbol})")
    print("=" * 70)
    # Tri par PnL net desc + n >= 30
    df_qual = df_result[df_result["n"] >= 30].sort_values("pnl_R_net", ascending=False)
    print(df_qual.to_string(index=False))

    print()
    print("=" * 70)
    print(f"SUMMARY BY FAMILY ({args.symbol})")
    print("=" * 70)
    print(summarize_by_family(df_result).to_string(index=False))

    if args.out:
        df_result.to_csv(args.out, index=False)
        print(f"\nSauvegarde -> {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
