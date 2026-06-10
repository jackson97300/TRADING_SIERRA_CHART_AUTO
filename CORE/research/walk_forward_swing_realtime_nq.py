"""
Walk-forward 12-fold avec signal REELLEMENT leak-free.

Le swing pivot dans V4 enriched est calcule avec lookback futur (~30 bars
mediane). Pour reproduire ce qu'on saurait en TEMPS REEL, on decale le signal
de N bars (N = lag retard supposé pour confirmer un pivot).

Strategy : on entre quand on apprend qu'un swing s'est forme N bars dans le
passe. Entry close[t], Exit close[t+3].

Test multi-lag : N = 10, 15, 20, 30 pour cerner le break-even.
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


def build_signals_lagged(df: pd.DataFrame, lag_bars: int):
    """Trade quand bars_since vient de revenir à == lag_bars (signal connu lag bars apres pivot)."""
    # Original fresh==0 transition (with leak)
    long_raw = (df["bars_since_last_swing_low"] == 0).astype(int)
    short_raw = (df["bars_since_last_swing_high"] == 0).astype(int)
    # Shift forward by lag_bars: on agit lag_bars apres le pivot reel
    long_shifted = long_raw.shift(lag_bars).fillna(0).astype(int)
    short_shifted = short_raw.shift(lag_bars).fillna(0).astype(int)

    both = (long_shifted == 1) & (short_shifted == 1)
    raw_side = np.where(both, 0, np.where(long_shifted == 1, 1, np.where(short_shifted == 1, -1, 0)))

    side = np.zeros(len(df), dtype=np.int8)
    last_entry = -10_000
    for i in range(len(df)):
        if raw_side[i] != 0 and (i - last_entry) >= COOLDOWN_BARS:
            side[i] = raw_side[i]
            last_entry = i
    df = df.copy()
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


def verdict_str(folds, glob):
    pf = glob["PF"]
    wr = glob["WR"]
    above1 = (folds["PF"] > 1.0).sum()
    minn = folds["n"].min()
    mean = folds["PnL_usd"].mean()
    std = folds["PnL_usd"].std()
    cat = int((folds["PnL_usd"] < mean - 2 * std).sum())
    if pf < 1.1:
        return f"NOGO (PF={pf:.2f} < 1.1)"
    if above1 < 6:
        return f"NOGO (folds>1 {above1}/12 < 6)"
    if cat > 0:
        return f"NOGO ({cat} catastrophe)"
    if minn < 30:
        return f"NOGO (min n {minn} < 30)"
    if pf >= 1.3 and above1 >= 8 and wr >= 0.60:
        return "GO"
    if pf >= 1.2 and above1 >= 7:
        return "GO-AVEC-RESERVES"
    return "MARGINAL"


def main():
    df_raw = load_all()
    print(f"[load] {len(df_raw):,} bars")

    summary_rows = []
    for lag in [10, 15, 20, 30, 45]:
        print(f"\n{'='*60}")
        print(f"LAG = {lag} bars (signal disponible {lag} bars apres pivot)")
        print(f"{'='*60}")
        df = build_signals_lagged(df_raw, lag)
        n_long = (df["side"] == 1).sum()
        n_short = (df["side"] == -1).sum()
        print(f"Signals: LONG={n_long}  SHORT={n_short}")

        folds, glob = walk_forward(df, 12)
        print("\nWalk-forward 12 folds:")
        print(folds.to_string(index=False, float_format=lambda x: f"{x:.2f}" if abs(x) < 100 else f"{x:,.0f}"))
        print(f"\nGlobal n={glob['n']}, PF={glob['PF']:.2f}, WR={glob['WR']:.1%}, PnL=${glob['PnL_usd']:,.0f}")
        v = verdict_str(folds, glob)
        print(f"VERDICT lag={lag}: {v}")

        summary_rows.append({
            "lag": lag,
            "n": glob["n"],
            "PF": glob["PF"],
            "WR": glob["WR"],
            "PnL_usd": glob["PnL_usd"],
            "folds_above_1": int((folds["PF"] > 1.0).sum()),
            "verdict": v,
        })

        Path("DATA/research").mkdir(parents=True, exist_ok=True)
        folds.to_csv(f"DATA/research/walk_forward_swing_lag{lag}_nq.csv", index=False)

    print("\n" + "=" * 60)
    print("SUMMARY MULTI-LAG")
    print("=" * 60)
    summary = pd.DataFrame(summary_rows)
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}" if abs(x) < 100 else f"{x:,.0f}"))


if __name__ == "__main__":
    main()
