"""backtest_bot3_1d_target_round5.py — Validation Lopez DSR du signal 1d_max.

Round 4 a identifie : always_long vers 1d_max sur 1ere bar des fenetres opens
(Asia + London + NY) = PF 2.28 median sur 1124 trades aggregate.

Round 5 valide statistiquement :
  1. Walk-forward 12-fold chronologique sur la config gagnante
  2. DSR Lopez (PSR vs SR=0 + haircut multiple testing)
  3. Regime-aware : LONG si bull (vwap_slope_30 J-1 > 0), SHORT si bear, sinon SKIP
  4. Footprint filter : ajouter long_up_bar=1 (LONG) gate

Configs gagnantes Round 4 a valider :
  - NQ always_long SL=60t (PF 3.55, +63.63R)
  - ES always_long SL=30t (PF 2.64, +31R)

Lopez formula DSR :
  PSR(SR*) = Phi((SR_obs - SR_target) * sqrt(N-1) / std_SR)
  std_SR = sqrt((1 - gamma3*SR + (gamma4-1)/4 * SR^2) / (N-1))
  DSR = PSR^N_trials (haircut multiple testing)
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
TICK_NQ = 0.25
PERIOD_START = "2025-12-15"
PERIOD_END = "2026-05-22"
N_FOLDS = 12
N_TRIALS_TESTED = 32    # Round 4 = 32 buckets x mode = 4 variantes SL * 4 target * 2 sym

OPEN_WINDOWS_UTC = [
    ("ASIA", "00:00", "00:30"),
    ("LONDON", "07:00", "07:30"),
    ("NY", "13:30", "14:00"),
]


def load_v4(symbol: str) -> pd.DataFrame:
    files = sorted(glob.glob(
        str(ROOT / f"DATA/datasets/v4_enriched/symbol={symbol}.c.0/year=*/month=*/data.parquet")))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    df["time_utc"] = df["ts_event"].dt.strftime("%H:%M")
    start_dt = pd.to_datetime(PERIOD_START, utc=True)
    end_dt = pd.to_datetime(PERIOD_END, utc=True)
    df = df[(df["ts_event"] >= start_dt) & (df["ts_event"] <= end_dt)].reset_index(drop=True)
    return df


def find_entry_windows(df: pd.DataFrame) -> list:
    """1ere bar par (date, window). Returns list of (win_name, df_idx)."""
    results = []
    for win_name, start, end in OPEN_WINDOWS_UTC:
        mask = (df["time_utc"] >= start) & (df["time_utc"] <= end)
        sub = df[mask]
        first_per_day_win = sub.groupby("date").head(1)
        for idx in first_per_day_win.index:
            results.append((win_name, idx))
    return results


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return default
        return f
    except (TypeError, ValueError):
        return default


def compute_prev_day_regime(df: pd.DataFrame) -> dict:
    """Pour chaque date, calcule mean(vwap_slope_10) du jour PRECEDENT.

    Returns {date_str: regime_str} avec regime in {BULL, BEAR, RANGE}.
    """
    df_clean = df[df["vwap_slope_10"].notna()].copy()
    daily_slope = df_clean.groupby("date")["vwap_slope_10"].mean()
    daily_slope_prev = daily_slope.shift(1)
    regime = {}
    for d, slope_prev in daily_slope_prev.items():
        if pd.isna(slope_prev):
            regime[d] = "RANGE"
        elif slope_prev > 0.001:
            regime[d] = "BULL"
        elif slope_prev < -0.001:
            regime[d] = "BEAR"
        else:
            regime[d] = "RANGE"
    return regime


def simulate_trade(df, entry_idx, direction, target_pct, sl_ticks, tick, timeout=360):
    if entry_idx >= len(df) - 1:
        return None
    eb = df.iloc[entry_idx]
    ep = float(eb["close"])
    edate = eb["date"]
    if direction == "long":
        sl = ep - sl_ticks * tick
        tp = ep * (1 + target_pct / 100.0)
    else:
        sl = ep + sl_ticks * tick
        tp = ep * (1 + target_pct / 100.0)
    end = min(len(df), entry_idx + 1 + timeout)
    for j in range(entry_idx + 1, end):
        bj = df.iloc[j]
        if bj["date"] != edate:
            xp = float(df.iloc[j - 1]["close"])
            pnl = (xp - ep) if direction == "long" else (ep - xp)
            return {"pnl_R": pnl / (sl_ticks * tick), "exit": "eod"}
        h = float(bj["high"]); l = float(bj["low"])
        if direction == "long":
            if l <= sl: return {"pnl_R": -1.0, "exit": "sl"}
            if h >= tp: return {"pnl_R": (tp - ep) / (sl_ticks * tick), "exit": "tp"}
        else:
            if h >= sl: return {"pnl_R": -1.0, "exit": "sl"}
            if l <= tp: return {"pnl_R": (ep - tp) / (sl_ticks * tick), "exit": "tp"}
    xp = float(df.iloc[end - 1]["close"])
    pnl = (xp - ep) if direction == "long" else (ep - xp)
    return {"pnl_R": pnl / (sl_ticks * tick), "exit": "timeout"}


def gen_trades_config(df, sl_ticks, regime_aware=False, footprint_filter=False,
                       direction_mode="always_long"):
    """Genere les trades pour 1 config donnee.

    direction_mode :
      - always_long : LONG vers 1d_max systematique
      - regime : LONG bull / SHORT bear / SKIP range (necessite regime_aware=True)
    """
    tick = 0.25
    windows = find_entry_windows(df)
    regime_by_date = compute_prev_day_regime(df) if regime_aware else {}
    trades = []
    for win_name, idx in windows:
        bar = df.iloc[idx]
        dmax = _safe_float(bar.get("dist_1d_max_ticks_pct"), 0.0)
        dmin = _safe_float(bar.get("dist_1d_min_ticks_pct"), 0.0)

        if direction_mode == "always_long":
            direction = "long"
            target = dmax
            if target <= 0:
                continue
        elif direction_mode == "regime":
            reg = regime_by_date.get(bar["date"], "RANGE")
            if reg == "BULL":
                direction = "long"
                target = dmax
                if target <= 0: continue
            elif reg == "BEAR":
                direction = "short"
                target = dmin
                if target >= 0: continue
            else:
                continue
        else:
            continue

        if footprint_filter:
            if direction == "long":
                fp = _safe_float(bar.get("long_up_bar"), 0.0)
            else:
                fp = _safe_float(bar.get("long_dn_bar"), 0.0)
            if fp != 1.0:
                continue

        trade = simulate_trade(df, idx, direction, target, sl_ticks, tick)
        if trade is None: continue
        trade["window"] = win_name
        trade["date"] = bar["date"]
        trade["direction"] = direction
        trades.append(trade)
    return trades


def compute_stats(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": None, "pf": None, "ev_R": None, "pnl_R": 0.0}
    rs = [t["pnl_R"] for t in trades]
    wins = sum(1 for r in rs if r > 0)
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    pf = gains / max(losses, 0.01) if losses > 0 else None
    return {
        "n": n, "wr": round(wins / n * 100, 1),
        "pf": round(pf, 2) if pf is not None else None,
        "ev_R": round(sum(rs) / n, 3),
        "pnl_R": round(sum(rs), 2),
    }


def walk_forward(trades, n_folds=N_FOLDS):
    """Chronological walk-forward sur les trades."""
    trades_sorted = sorted(trades, key=lambda t: t["date"])
    n = len(trades_sorted)
    if n < n_folds * 3:
        return {"folds_positive": None, "fold_pfs": [], "stable": False,
                 "msg": f"n={n} < {n_folds*3} (min 3/fold)"}
    fold_size = n // n_folds
    fold_results = []
    for k in range(n_folds):
        lo = k * fold_size
        hi = (k + 1) * fold_size if k < n_folds - 1 else n
        s = compute_stats(trades_sorted[lo:hi])
        fold_results.append(s)
    pfs = [s["pf"] if s["pf"] is not None else 0.0 for s in fold_results]
    folds_positive = sum(1 for s in fold_results
                          if s["pf"] is not None and s["pf"] > 1.0 and s["pnl_R"] > 0)
    return {
        "folds_positive": folds_positive,
        "fold_pfs": [round(p, 2) for p in pfs],
        "fold_pnls": [s["pnl_R"] for s in fold_results],
        "stable": folds_positive >= n_folds - 2,
        "fold_n_median": int(np.median([s["n"] for s in fold_results])),
    }


def compute_dsr_lopez(trades, n_trials=N_TRIALS_TESTED):
    """DSR Lopez = PSR^N_trials.

    PSR(SR*) = Phi((SR - SR_target) * sqrt(N-1) / std_SR)
    Avec ajustement skew/kurtosis.
    """
    if len(trades) < 30:
        return {"sr": None, "psr": None, "dsr": None,
                 "msg": "n < 30 insuffisant Lopez"}
    rs = np.array([t["pnl_R"] for t in trades])
    mu = rs.mean()
    sigma = rs.std(ddof=1)
    if sigma == 0:
        return {"sr": None, "psr": None, "dsr": None, "msg": "sigma=0"}
    sr_per_trade = mu / sigma    # Sharpe per-trade (annualised non requis ici)
    # Sharpe annualise ~ SR_per_trade * sqrt(N_trades_per_year)
    # Pour comparaison Lopez : on calcule PSR vs SR_target = 0
    n = len(rs)
    skew = stats.skew(rs)
    kurt = stats.kurtosis(rs, fisher=False)    # kurt non-Fisher
    # Variance estimateur SR
    var_sr = (1 - skew * sr_per_trade + (kurt - 1) / 4.0 * sr_per_trade ** 2) / (n - 1)
    std_sr = np.sqrt(max(var_sr, 1e-9))
    # PSR vs SR_target = 0
    z = sr_per_trade / std_sr
    psr = stats.norm.cdf(z)
    # DSR = PSR^N_trials
    dsr = psr ** n_trials
    return {
        "sr": round(sr_per_trade, 4),
        "psr": round(psr, 4),
        "dsr": round(dsr, 4),
        "skew": round(skew, 3),
        "kurt": round(kurt, 3),
        "n": n,
    }


def run_round5_config(df, sym, sl_ticks, regime_aware, footprint, direction_mode):
    trades = gen_trades_config(df, sl_ticks, regime_aware=regime_aware,
                                 footprint_filter=footprint,
                                 direction_mode=direction_mode)
    s = compute_stats(trades)
    wf = walk_forward(trades)
    dsr = compute_dsr_lopez(trades)
    return {
        "sym": sym, "sl_ticks": sl_ticks,
        "direction_mode": direction_mode,
        "regime_aware": regime_aware,
        "footprint": footprint,
        "n": s["n"], "wr": s["wr"], "pf": s["pf"],
        "ev_R": s["ev_R"], "pnl_R": s["pnl_R"],
        "wf_positive": wf["folds_positive"],
        "wf_stable": wf["stable"],
        "wf_pfs": wf.get("fold_pfs", []),
        "wf_n_median": wf.get("fold_n_median", 0),
        "sr_per_trade": dsr.get("sr"),
        "psr": dsr.get("psr"),
        "dsr_lopez": dsr.get("dsr"),
        "skew": dsr.get("skew"),
    }


def main():
    print("=" * 90)
    print("ROUND 5 — Validation Lopez DSR + Walk-forward + Regime-aware + Footprint filter")
    print("=" * 90)
    print()

    configs = [
        # (sym, sl_ticks, regime_aware, footprint, direction_mode)
        ("NQ", 60, False, False, "always_long"),    # baseline Round 4 winner NQ
        ("NQ", 60, False, True,  "always_long"),    # + footprint
        ("NQ", 60, True,  False, "regime"),          # regime-aware
        ("NQ", 60, True,  True,  "regime"),          # regime + footprint
        ("NQ", 40, False, False, "always_long"),
        ("NQ", 30, False, False, "always_long"),
        ("ES", 30, False, False, "always_long"),    # baseline Round 4 winner ES
        ("ES", 30, False, True,  "always_long"),
        ("ES", 30, True,  False, "regime"),
        ("ES", 30, True,  True,  "regime"),
        ("ES", 20, False, False, "always_long"),
    ]

    results = []
    dfs = {}
    for sym, sl, ra, fp, mode in configs:
        if sym not in dfs:
            dfs[sym] = load_v4(sym)
            print(f"{sym} loaded : {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours")
        print(f"\nRun : {sym} SL={sl}t regime_aware={ra} footprint={fp} mode={mode}")
        r = run_round5_config(dfs[sym], sym, sl, ra, fp, mode)
        results.append(r)
        print(f"  n={r['n']} WR={r['wr']}% PF={r['pf']} EV={r['ev_R']:+}R "
              f"PnL={r['pnl_R']:+.2f}R WF={r['wf_positive']}/{N_FOLDS} stable={r['wf_stable']}")
        print(f"  SR/trade={r['sr_per_trade']} PSR={r['psr']} DSR_Lopez={r['dsr_lopez']} "
              f"(N_trials={N_TRIALS_TESTED})")
        print(f"  WF PFs : {r['wf_pfs']}")

    df_res = pd.DataFrame(results)
    print()
    print("=" * 90)
    print("SUMMARY — Top configs par DSR Lopez")
    print("=" * 90)
    # Filtre DSR not None puis tri desc
    df_qual = df_res[df_res["dsr_lopez"].notna()].sort_values("dsr_lopez", ascending=False)
    cols = ["sym", "sl_ticks", "direction_mode", "regime_aware", "footprint",
             "n", "wr", "pf", "pnl_R", "wf_positive", "wf_stable", "psr", "dsr_lopez"]
    print(df_qual[cols].to_string(index=False))

    print()
    print("=" * 90)
    print("LOPEZ DECISION CRITERIA")
    print("=" * 90)
    print("  GO       : DSR_Lopez > 0.95 + WF_stable (>=10/12 folds positifs) + n>=100")
    print("  RESERVES : DSR_Lopez > 0.50 + WF >=8/12 + n>=50")
    print("  NOGO     : DSR_Lopez <= 0.50 OR WF < 8/12 OR n<50")
    print()
    for _, r in df_qual.iterrows():
        dsr = r["dsr_lopez"]
        wfp = r["wf_positive"] if r["wf_positive"] is not None else 0
        n = r["n"]
        if dsr > 0.95 and wfp >= 10 and n >= 100:
            verdict = "GO"
        elif dsr > 0.50 and wfp >= 8 and n >= 50:
            verdict = "RESERVES"
        else:
            verdict = "NOGO"
        print(f"  {r['sym']} SL={r['sl_ticks']}t mode={r['direction_mode']:12s} "
              f"ra={r['regime_aware']!s:5s} fp={r['footprint']!s:5s} "
              f"-> {verdict} (dsr={dsr}, wf={wfp}/{N_FOLDS}, n={n})")

    df_res.to_csv(ROOT / "DATA" / "bot3_round5_results.csv", index=False)
    print(f"\nSauvegarde -> DATA/bot3_round5_results.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
