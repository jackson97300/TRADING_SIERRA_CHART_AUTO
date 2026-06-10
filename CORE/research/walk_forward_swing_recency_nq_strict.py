"""
Variante STRICTE : trigger uniquement sur transition fresh (bars_since == 0).
Plus proche du sampling bench V4 (n=2078 LONG attendu).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

NQ_TICK = 0.25
NQ_TICK_VALUE = 0.50
SLIP_TICKS = 3.0
COMMISSION_USD = 0.50
DATA_GLOB = "DATA/datasets/v4_enriched/symbol=NQ.c.0/year=*/month=*/data.parquet"
EXIT_HORIZON = 3
COOLDOWN_BARS = EXIT_HORIZON


def load_all():
    files = sorted(glob.glob(DATA_GLOB))
    cols = ["ts_event", "close", "bars_since_last_swing_low", "bars_since_last_swing_high", "rvol_regime"]
    dfs = [pd.read_parquet(f, columns=cols) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["fut_close"] = df["close"].shift(-EXIT_HORIZON)
    df["fut_r3_ticks"] = (df["fut_close"] - df["close"]) / NQ_TICK
    return df


def build_strict(df):
    """Trigger uniquement sur transition (bars_since == 0)."""
    long_raw = (df["bars_since_last_swing_low"] == 0)
    short_raw = (df["bars_since_last_swing_high"] == 0)
    both = long_raw & short_raw
    raw_side = np.where(both, 1, np.where(long_raw, 1, np.where(short_raw, -1, 0)))

    side = np.zeros(len(df), dtype=np.int8)
    last_entry = -10_000
    for i in range(len(df)):
        if raw_side[i] != 0 and (i - last_entry) >= COOLDOWN_BARS:
            side[i] = raw_side[i]
            last_entry = i
    df["side"] = side
    return df.dropna(subset=["fut_r3_ticks"]).reset_index(drop=True)


def apply_costs(g):
    nt = g - SLIP_TICKS
    return nt, nt * NQ_TICK_VALUE - COMMISSION_USD


def fold_stats(df_fold):
    t = df_fold[df_fold["side"] != 0].copy()
    if len(t) == 0:
        return {"n": 0, "n_long": 0, "n_short": 0, "PF": np.nan, "WR": np.nan, "PnL_usd": 0.0}
    t["gross"] = t["side"] * t["fut_r3_ticks"]
    t["net_ticks"], t["net_usd"] = zip(*t["gross"].apply(apply_costs))
    w = t[t["net_usd"] > 0]
    l = t[t["net_usd"] < 0]
    gw, gl = w["net_usd"].sum(), -l["net_usd"].sum()
    pf = gw / gl if gl > 1e-9 else np.inf
    return {"n": len(t), "n_long": int((t["side"] == 1).sum()), "n_short": int((t["side"] == -1).sum()),
            "PF": pf, "WR": len(w) / len(t), "PnL_usd": float(t["net_usd"].sum())}


def walk_forward(df, n_folds=12):
    n = len(df)
    fs = n // n_folds
    rows = []
    for k in range(n_folds):
        s = k * fs
        e = (k + 1) * fs if k < n_folds - 1 else n
        sub = df.iloc[s:e]
        st = fold_stats(sub)
        rows.append({
            "fold": k + 1,
            "period": f"{sub['ts_event'].iloc[0].date()} -> {sub['ts_event'].iloc[-1].date()}",
            **st,
        })
    return pd.DataFrame(rows), fold_stats(df)


def main():
    df = load_all()
    df = build_strict(df)
    n_long = (df["side"] == 1).sum()
    n_short = (df["side"] == -1).sum()
    print(f"[STRICT trigger fresh==0] LONG={n_long}  SHORT={n_short}")
    folds, glob = walk_forward(df, 12)
    print("\n=== Walk-forward STRICT ===")
    print(folds.to_string(index=False, float_format=lambda x: f"{x:.2f}" if abs(x) < 100 else f"{x:,.0f}"))
    print(f"\nGlobal: n={glob['n']}, PF={glob['PF']:.2f}, WR={glob['WR']:.1%}, PnL=${glob['PnL_usd']:,.0f}")

    # rvol_regime breakdown
    print("\n=== rvol_regime breakdown ===")
    for reg in sorted(df["rvol_regime"].dropna().unique()):
        st = fold_stats(df[df["rvol_regime"] == reg])
        print(f"  rvol={int(reg)}  n={st['n']:>4}  PF={st['PF']:.2f}  WR={st['WR']:.1%}  PnL=${st['PnL_usd']:,.0f}")

    folds_above_1 = (folds["PF"] > 1.0).sum()
    folds_above_13 = (folds["PF"] >= 1.3).sum()
    min_n = folds["n"].min()
    cat = ((folds["PnL_usd"] < folds["PnL_usd"].mean() - 2 * folds["PnL_usd"].std())).sum()
    print(f"\nFolds PF>1.0: {folds_above_1}/12")
    print(f"Folds PF>=1.3: {folds_above_13}/12")
    print(f"Min n/fold: {min_n}")
    print(f"Catastrophe folds: {cat}/12")

    Path("DATA/research").mkdir(parents=True, exist_ok=True)
    folds.to_csv("DATA/research/walk_forward_swing_recency_nq_strict.csv", index=False)


if __name__ == "__main__":
    main()
