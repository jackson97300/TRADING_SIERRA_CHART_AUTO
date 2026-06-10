"""
Walk-forward 12-fold avec signal LEAK-FREE : swing_*_active_lag10.

`bars_since_last_swing_low` a un look-ahead leak (swing pivot detecte ~30 bars
apres le creux reel). Confirme empirique : PF 25 / WR 88% sur strict.

`swing_low_active_lag10` = 1 si pivot confirme avec lag de 10 bars (real-time safe).
On long quand cette feature passe a 1.
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
    cols = ["ts_event", "close", "swing_low_active_lag10", "swing_high_active_lag10", "rvol_regime"]
    dfs = [pd.read_parquet(f, columns=cols) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["fut_close"] = df["close"].shift(-EXIT_HORIZON)
    df["fut_r3_ticks"] = (df["fut_close"] - df["close"]) / NQ_TICK
    print(f"[load] total bars: {len(df):,}")
    return df


def build_signals(df):
    """Entry quand swing_*_active_lag10 == 1 (pivot confirme, leak-free)."""
    long_raw = df["swing_low_active_lag10"] == 1
    short_raw = df["swing_high_active_lag10"] == 1
    both = long_raw & short_raw
    raw_side = np.where(both, 0, np.where(long_raw, 1, np.where(short_raw, -1, 0)))

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
    return {
        "n": len(t),
        "n_long": int((t["side"] == 1).sum()),
        "n_short": int((t["side"] == -1).sum()),
        "PF": pf,
        "WR": len(w) / len(t),
        "PnL_usd": float(t["net_usd"].sum()),
    }


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


def verdict(folds, glob):
    pf = glob["PF"]
    wr = glob["WR"]
    above1 = (folds["PF"] > 1.0).sum()
    above13 = (folds["PF"] >= 1.3).sum()
    minn = folds["n"].min()
    mean = folds["PnL_usd"].mean()
    std = folds["PnL_usd"].std()
    cat = int((folds["PnL_usd"] < mean - 2 * std).sum())
    print("\n=== Verdict pragmatique ===")
    print(f"  PF global       : {pf:.2f}  (cible >= 1.3)")
    print(f"  WR global       : {wr:.1%}  (cible >= 60%)")
    print(f"  Folds PF>1.0    : {above1}/12  (cible >= 8)")
    print(f"  Folds PF>=1.3   : {above13}/12")
    print(f"  Min n/fold      : {minn}  (cible >= 30)")
    print(f"  Folds catastr   : {cat}/12")
    print(f"  Mean PnL$/fold  : {mean:,.0f}")
    print(f"  Std PnL$/fold   : {std:,.0f}")
    if pf < 1.1:
        return "NOGO — PF < 1.1"
    if above1 < 6:
        return "NOGO — instabilite (PF>1 < 6/12)"
    if cat > 0:
        return "NOGO — fold catastrophe"
    if minn < 30:
        return "NOGO — n par fold insuffisant"
    if pf >= 1.3 and above1 >= 8 and wr >= 0.60:
        return "GO — tous criteres OK"
    if pf >= 1.2 and above1 >= 7:
        return "GO-AVEC-RESERVES"
    return "MARGINAL — decision Jackson"


def main():
    df = load_all()
    df = build_signals(df)
    print(f"\n[lag10 signals NON-OVERLAP] LONG={(df['side']==1).sum():,}  SHORT={(df['side']==-1).sum():,}")
    folds, glob = walk_forward(df, 12)
    print("\n=== Walk-forward LEAK-FREE (lag10) ===")
    print(folds.to_string(index=False, float_format=lambda x: f"{x:.2f}" if abs(x) < 100 else f"{x:,.0f}"))
    print(f"\nGlobal: n={glob['n']}, PF={glob['PF']:.2f}, WR={glob['WR']:.1%}, PnL=${glob['PnL_usd']:,.0f}")

    # Side breakdown
    print("\n=== Side breakdown ===")
    for s, lbl in [(1, "LONG "), (-1, "SHORT")]:
        sub = df[df["side"] == s]
        if len(sub):
            st = fold_stats(sub.assign(side=s))
            print(f"  {lbl}  n={st['n']:>5}  PF={st['PF']:.2f}  WR={st['WR']:.1%}  PnL=${st['PnL_usd']:,.0f}")

    # rvol_regime
    print("\n=== rvol_regime breakdown ===")
    for reg in sorted(df["rvol_regime"].dropna().unique()):
        st = fold_stats(df[df["rvol_regime"] == reg])
        if st["n"] > 0:
            print(f"  rvol={int(reg)}  n={st['n']:>4}  PF={st['PF']:.2f}  WR={st['WR']:.1%}  PnL=${st['PnL_usd']:,.0f}")

    print(f"\nVERDICT FINAL : {verdict(folds, glob)}\n")
    Path("DATA/research").mkdir(parents=True, exist_ok=True)
    folds.to_csv("DATA/research/walk_forward_swing_lag10_nq.csv", index=False)
    print("Folds CSV: DATA/research/walk_forward_swing_lag10_nq.csv")


if __name__ == "__main__":
    main()
