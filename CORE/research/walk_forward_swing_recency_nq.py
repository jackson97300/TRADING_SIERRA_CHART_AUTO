"""
Walk-forward 12-fold time-series CV pour edge swing recency mean reversion NQ.

DEDUPLICATION : non-overlapping trades (cooldown EXIT_HORIZON=3 bars apres entry).
Sans dedup → overlap massif (6 barres consecutives = même setup), PF gonflé.

Setup :
- LONG : bars_since_last_swing_low <= 5 (transition fresh ou maintenue) → entry close[t]
- SHORT : bars_since_last_swing_high <= 5 → entry close[t]
- Exit close[t+3]

Costs réalistes (1 micro NQ) :
- Commission $0.50 RT
- Slip entry 1.5t + slip exit 1.5t = 3t round-trip
- Tick value NQ micro = $0.50 / 0.25 pt

Critères PRAGMATIQUES (Jackson 13/05) :
- PF >= 1.3 global, PF > 1.0 sur >= 8/12 folds, n par fold >= 30, WR >= 60%, no catastrophe
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

NQ_TICK = 0.25
NQ_TICK_VALUE = 0.50  # micro
SLIP_TICKS = 3.0      # round-trip
COMMISSION_USD = 0.50 # round-trip micro NQ

DATA_GLOB = "DATA/datasets/v4_enriched/symbol=NQ.c.0/year=*/month=*/data.parquet"
EXIT_HORIZON = 3
COOLDOWN_BARS = EXIT_HORIZON  # non-overlapping


def load_all() -> pd.DataFrame:
    files = sorted(glob.glob(DATA_GLOB))
    print(f"[load] {len(files)} parquet files")
    cols = [
        "ts_event",
        "close",
        "bars_since_last_swing_low",
        "bars_since_last_swing_high",
        "rvol_regime",
    ]
    dfs = [pd.read_parquet(f, columns=cols) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["fut_close"] = df["close"].shift(-EXIT_HORIZON)
    df["fut_r3_ticks"] = (df["fut_close"] - df["close"]) / NQ_TICK
    print(f"[load] total bars: {len(df):,}")
    print(f"[load] date range: {df['ts_event'].min()} -> {df['ts_event'].max()}")
    return df


def build_signals_nonoverlapping(df: pd.DataFrame) -> pd.DataFrame:
    """Signaux <=5 avec cooldown 3 bars (non-overlap)."""
    long_raw = (df["bars_since_last_swing_low"] >= 0) & (df["bars_since_last_swing_low"] <= 5)
    short_raw = (df["bars_since_last_swing_high"] >= 0) & (df["bars_since_last_swing_high"] <= 5)

    both = long_raw & short_raw
    prefer_long = df["bars_since_last_swing_low"] < df["bars_since_last_swing_high"]
    raw_side = np.where(
        both,
        np.where(prefer_long, 1, -1),
        np.where(long_raw, 1, np.where(short_raw, -1, 0)),
    )

    # Cooldown : si trade entry à barre i, suivante possible à i+COOLDOWN_BARS
    side = np.zeros(len(df), dtype=np.int8)
    last_entry = -10_000
    for i in range(len(df)):
        if raw_side[i] != 0 and (i - last_entry) >= COOLDOWN_BARS:
            side[i] = raw_side[i]
            last_entry = i
    df["side"] = side
    df = df.dropna(subset=["fut_r3_ticks"]).reset_index(drop=True)
    return df


def apply_costs(gross_ticks: float) -> tuple[float, float]:
    net_ticks = gross_ticks - SLIP_TICKS
    net_usd = net_ticks * NQ_TICK_VALUE - COMMISSION_USD
    return net_ticks, net_usd


def fold_stats(df_fold: pd.DataFrame) -> dict:
    trades = df_fold[df_fold["side"] != 0].copy()
    if len(trades) == 0:
        return {"n": 0, "n_long": 0, "n_short": 0, "PF": np.nan, "WR": np.nan, "PnL_usd": 0.0}
    trades["gross_ticks"] = trades["side"] * trades["fut_r3_ticks"]
    trades["net_ticks"], trades["net_usd"] = zip(*trades["gross_ticks"].apply(apply_costs))

    wins = trades[trades["net_usd"] > 0]
    losses = trades[trades["net_usd"] < 0]
    gross_win = wins["net_usd"].sum()
    gross_loss = -losses["net_usd"].sum()
    pf = gross_win / gross_loss if gross_loss > 1e-9 else np.inf
    wr = len(wins) / len(trades)
    return {
        "n": len(trades),
        "n_long": int((trades["side"] == 1).sum()),
        "n_short": int((trades["side"] == -1).sum()),
        "PF": pf,
        "WR": wr,
        "PnL_usd": float(trades["net_usd"].sum()),
    }


def walk_forward(df: pd.DataFrame, n_folds: int = 12):
    n = len(df)
    fold_size = n // n_folds
    rows = []
    for k in range(n_folds):
        start = k * fold_size
        end = (k + 1) * fold_size if k < n_folds - 1 else n
        df_fold = df.iloc[start:end]
        st = fold_stats(df_fold)
        period = f"{df_fold['ts_event'].iloc[0].date()} -> {df_fold['ts_event'].iloc[-1].date()}"
        rows.append({
            "fold": k + 1,
            "period": period,
            "n": st["n"],
            "n_long": st["n_long"],
            "n_short": st["n_short"],
            "PF": st["PF"],
            "WR": st["WR"],
            "PnL_usd": st["PnL_usd"],
        })
    folds = pd.DataFrame(rows)
    glob = fold_stats(df)
    return folds, glob


def side_breakdown(df: pd.DataFrame):
    print("\n=== Side breakdown global (post dedup) ===")
    for s, label in [(1, "LONG "), (-1, "SHORT")]:
        sub = df[df["side"] == s]
        if len(sub) == 0:
            continue
        st = fold_stats(sub.assign(side=s))
        print(f"  {label}  n={st['n']:>5}  PF={st['PF']:.2f}  WR={st['WR']:.1%}  PnL=${st['PnL_usd']:,.0f}")


def regime_filter_analysis(df: pd.DataFrame):
    print("\n=== rvol_regime breakdown (toutes positions) ===")
    for reg in sorted(df["rvol_regime"].dropna().unique()):
        sub = df[df["rvol_regime"] == reg]
        st = fold_stats(sub)
        print(f"  rvol_regime={int(reg)}  n={st['n']:>5}  PF={st['PF']:.2f}  WR={st['WR']:.1%}  PnL=${st['PnL_usd']:,.0f}")


def verdict(folds: pd.DataFrame, glob: dict) -> str:
    pf_global = glob["PF"]
    wr_global = glob["WR"]
    n_folds_above_1 = (folds["PF"] > 1.0).sum()
    n_folds_above_13 = (folds["PF"] >= 1.3).sum()
    min_n_fold = folds["n"].min()
    pnl_std = folds["PnL_usd"].std()
    pnl_mean = folds["PnL_usd"].mean()
    cat_threshold = pnl_mean - 2 * pnl_std
    catastrophe = int((folds["PnL_usd"] < cat_threshold).sum())

    print("\n=== Verdict pragmatique ===")
    print(f"  PF global       : {pf_global:.2f}  (cible >= 1.3)")
    print(f"  WR global       : {wr_global:.1%}  (cible >= 60%)")
    print(f"  Folds PF>1.0    : {n_folds_above_1}/12  (cible >= 8)")
    print(f"  Folds PF>=1.3   : {n_folds_above_13}/12  (info)")
    print(f"  Min n par fold  : {min_n_fold}  (cible >= 30)")
    print(f"  Folds catastr   : {catastrophe}/12  (cible 0)")
    print(f"  PnL$ mean fold  : {pnl_mean:,.0f}")
    print(f"  PnL$ std fold   : {pnl_std:,.0f}")

    if pf_global < 1.1:
        return "NOGO — PF global < 1.1"
    if n_folds_above_1 < 6:
        return "NOGO — instabilite (PF>1 sur < 6/12 folds)"
    if catastrophe > 0:
        return "NOGO — fold catastrophe (>2 sigma)"
    if min_n_fold < 30:
        return "NOGO — n par fold insuffisant"
    if pf_global >= 1.3 and n_folds_above_1 >= 8 and wr_global >= 0.60:
        return "GO — tous criteres pragmatiques OK"
    if pf_global >= 1.2 and n_folds_above_1 >= 7:
        return "GO-AVEC-RESERVES — criteres principaux OK, secondaires marginal"
    return "MARGINAL — decision Jackson"


def main():
    df = load_all()
    df = build_signals_nonoverlapping(df)
    n_long = (df["side"] == 1).sum()
    n_short = (df["side"] == -1).sum()
    print(f"\n[signals NON-OVERLAP] LONG  : {n_long:,}")
    print(f"[signals NON-OVERLAP] SHORT : {n_short:,}")

    folds, glob = walk_forward(df, n_folds=12)

    print("\n=== Walk-forward 12-fold (non-overlapping) ===")
    print(folds.to_string(index=False, float_format=lambda x: f"{x:.2f}" if abs(x) < 100 else f"{x:,.0f}"))

    print("\n=== Global agrege ===")
    for k, v in glob.items():
        if k == "PnL_usd":
            print(f"  {k}: ${v:,.0f}")
        elif k == "PF":
            print(f"  {k}: {v:.2f}")
        elif k == "WR":
            print(f"  {k}: {v:.1%}")
        else:
            print(f"  {k}: {v}")

    side_breakdown(df)
    regime_filter_analysis(df)

    v = verdict(folds, glob)
    print(f"\nVERDICT FINAL : {v}\n")

    out = Path("DATA/research/walk_forward_swing_recency_nq.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    folds.to_csv(out, index=False)
    print(f"Folds exported: {out}")


if __name__ == "__main__":
    main()
