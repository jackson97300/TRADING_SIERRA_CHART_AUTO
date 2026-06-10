"""
Investigation des bars avec close mismatch (DMP vs DBN).
Affiche le contexte autour de chaque mismatch pour comprendre la cause.
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK = 0.25
TOL = TICK / 2


def load_dmp(jsonl_path):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                rows.append({
                    "ts_ms": d.get("ts"),
                    "close": d.get("price"),
                    "high": d.get("bar_high"),
                    "low": d.get("bar_low"),
                    "vol": d.get("total_vol"),
                    "buy_vol": d.get("buy_vol"),
                    "sell_vol": d.get("sell_vol"),
                })
            except Exception:
                pass
    df = pd.DataFrame(rows)
    df["ts_raw"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["ts_utc"] = df["ts_raw"].dt.round("min")
    df["sec"] = df["ts_raw"].dt.second
    return df.sort_values("ts_raw").reset_index(drop=True)


def load_dbn_pair(symbol):
    parts = []
    for day in ["23", "24"]:
        p = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m" / f"symbol={symbol}.c.0" / "year=2026" / "month=04" / f"day={day}" / "data.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    return pd.concat(parts).sort_index()


def investigate(symbol):
    print(f"\n{'='*100}")
    print(f" INVESTIGATION MISMATCHES — {symbol}")
    print(f"{'='*100}")

    dmp_raw = pd.concat([
        load_dmp(ROOT / "DATA" / symbol / "20260423_" + symbol + ".jsonl"),
        load_dmp(ROOT / "DATA" / symbol / "20260424_" + symbol + ".jsonl"),
    ], ignore_index=True)

    dmp_agg = dmp_raw.groupby("ts_utc").agg(
        close=("close", "last"),
        high=("high", "max"),
        low=("low", "min"),
        vol=("vol", "sum"),
        n_entries=("ts_ms", "count"),
        sec_list=("sec", lambda s: list(s)),
    )

    dbn = load_dbn_pair(symbol)

    win_start = max(dmp_agg.index.min(), dbn.index.min())
    win_end = min(dmp_agg.index.max(), dbn.index.max())
    dmp_w = dmp_agg.loc[win_start:win_end]
    dbn_w = dbn.loc[win_start:win_end]

    joined = dmp_w[["close", "high", "low", "vol", "n_entries", "sec_list"]].add_suffix("_dmp").join(
        dbn_w[["open", "high", "low", "close", "volume"]].add_suffix("_dbn"),
        how="inner",
    )

    # Close mismatches
    joined["close_diff"] = joined["close_dmp"] - joined["close_dbn"]
    mismatches = joined[joined["close_diff"].abs() > TOL]

    print(f"\nTotal bars communs : {len(joined)}")
    print(f"Close mismatches (|diff| > {TOL}) : {len(mismatches)}")

    if mismatches.empty:
        print("\n  Aucun mismatch — OK")
        return

    print(f"\n{'='*100}")
    for ts, row in mismatches.iterrows():
        print(f"\n--- MISMATCH @ {ts} ---")
        print(f"  DMP : close={row['close_dmp']:.2f}  high={row['high_dmp']:.2f}  low={row['low_dmp']:.2f}  vol={int(row['vol_dmp'])}")
        print(f"  DBN : close={row['close_dbn']:.2f}  high={row['high_dbn']:.2f}  low={row['low_dbn']:.2f}  vol={int(row['volume_dbn'])}  open={row['open_dbn']:.2f}")
        print(f"  diff close = {row['close_diff']:+.2f} ({row['close_diff']/TICK:+.1f} ticks)")
        print(f"  DMP n_entries={row['n_entries_dmp']} sec={row['sec_list_dmp']}")
        # Verifie si DMP avait 2 entries (sec=00 + sec=59)
        if row["n_entries_dmp"] > 1:
            # Affiche les 2 entries brutes
            raw = dmp_raw[dmp_raw["ts_utc"] == ts].sort_values("ts_raw")
            print(f"    Raw DMP entries:")
            for _, r in raw.iterrows():
                print(f"      ts={r['ts_raw']} (sec={r['sec']:02d}) close={r['close']:.2f} hi={r['high']:.2f} lo={r['low']:.2f} vol={int(r['vol'])}")

        # Voisinage : 3 bars avant/apres dans DBN
        idx_pos = joined.index.get_loc(ts)
        lo, hi = max(0, idx_pos - 2), min(len(joined), idx_pos + 3)
        ctx = joined.iloc[lo:hi][["close_dmp", "close_dbn", "vol_dmp", "volume_dbn", "n_entries_dmp"]]
        print(f"\n  Contexte (3 bars autour):")
        for ctx_ts, ctx_row in ctx.iterrows():
            marker = " <<< MISMATCH" if ctx_ts == ts else ""
            print(f"    {ctx_ts}  DMP_close={ctx_row['close_dmp']:.2f}  DBN_close={ctx_row['close_dbn']:.2f}  DMP_vol={int(ctx_row['vol_dmp']):>6d}  DBN_vol={int(ctx_row['volume_dbn']):>6d}  n={ctx_row['n_entries_dmp']}{marker}")


# Need fix: f-string concat path issue
def investigate_safe(symbol):
    print(f"\n{'='*100}")
    print(f" INVESTIGATION MISMATCHES — {symbol}")
    print(f"{'='*100}")

    dmp_files = [
        ROOT / "DATA" / symbol / f"20260423_{symbol}.jsonl",
        ROOT / "DATA" / symbol / f"20260424_{symbol}.jsonl",
    ]
    dmp_raw = pd.concat([load_dmp(p) for p in dmp_files], ignore_index=True)

    dmp_agg = dmp_raw.groupby("ts_utc").agg(
        close=("close", "last"),
        high=("high", "max"),
        low=("low", "min"),
        vol=("vol", "sum"),
        n_entries=("ts_ms", "count"),
        sec_list=("sec", lambda s: list(s)),
    )

    dbn = load_dbn_pair(symbol)
    win_start = max(dmp_agg.index.min(), dbn.index.min())
    win_end = min(dmp_agg.index.max(), dbn.index.max())
    dmp_w = dmp_agg.loc[win_start:win_end]
    dbn_w = dbn.loc[win_start:win_end]

    joined = dmp_w[["close", "high", "low", "vol", "n_entries", "sec_list"]].add_suffix("_dmp").join(
        dbn_w[["open", "high", "low", "close", "volume"]].add_suffix("_dbn"),
        how="inner",
    )

    joined["close_diff"] = joined["close_dmp"] - joined["close_dbn"]
    mismatches = joined[joined["close_diff"].abs() > TOL]

    print(f"\nTotal bars communs : {len(joined)}")
    print(f"Close mismatches (|diff| > {TOL}) : {len(mismatches)}")

    if mismatches.empty:
        print("  Aucun mismatch")
        return

    for ts, row in mismatches.iterrows():
        print(f"\n--- MISMATCH @ {ts} ---")
        print(f"  DMP : close={row['close_dmp']:.2f}  high={row['high_dmp']:.2f}  low={row['low_dmp']:.2f}  vol={int(row['vol_dmp'])}  n_entries={row['n_entries_dmp']} sec={row['sec_list_dmp']}")
        print(f"  DBN : close={row['close_dbn']:.2f}  high={row['high_dbn']:.2f}  low={row['low_dbn']:.2f}  vol={int(row['volume_dbn'])}  open={row['open_dbn']:.2f}")
        print(f"  diff close = {row['close_diff']:+.2f} ({row['close_diff']/TICK:+.1f} ticks)")

        if row["n_entries_dmp"] > 1:
            raw = dmp_raw[dmp_raw["ts_utc"] == ts].sort_values("ts_raw")
            print(f"  Raw DMP entries:")
            for _, r in raw.iterrows():
                print(f"    ts={r['ts_raw']} sec={r['sec']:02d} close={r['close']:.2f} hi={r['high']:.2f} lo={r['low']:.2f} vol={int(r['vol'])}")

        idx_pos = joined.index.get_loc(ts)
        lo, hi = max(0, idx_pos - 2), min(len(joined), idx_pos + 3)
        ctx = joined.iloc[lo:hi]
        print(f"  Contexte:")
        for ctx_ts, ctx_row in ctx.iterrows():
            mark = " <<<" if ctx_ts == ts else ""
            print(f"    {ctx_ts} DMP_c={ctx_row['close_dmp']:.2f} DBN_c={ctx_row['close_dbn']:.2f} DMP_v={int(ctx_row['vol_dmp']):>6d} DBN_v={int(ctx_row['volume_dbn']):>6d} n={ctx_row['n_entries_dmp']}{mark}")


if __name__ == "__main__":
    investigate_safe("ES")
    investigate_safe("NQ")
