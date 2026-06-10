"""Analyse comparative trades 2 bots paper trading.

BOT 1 DMP Sim3 : mia_paper_trader.py (DMP JSONL source, scoring composite)
BOT 2 DB Sim2 : databento_paper_trader.py (Databento source, scoring rules)

Compare : WR, PnL, distribution outcomes, durations, par symbol, par jour.
"""
import json
import sys
from pathlib import Path
from collections import defaultdict
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "DATA" / "PAPER_TRADES"


def load_trades(pattern: str, exclude: str = None) -> pd.DataFrame:
    """Load all trades jsonl matching pattern (excluding `exclude`)."""
    rows = []
    for fp in sorted(PAPER_DIR.glob(pattern)):
        if exclude and exclude in fp.name:
            continue
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def summarize_bot(name: str, df: pd.DataFrame):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    if df.empty:
        print("  AUCUN TRADE")
        return None
    print(f"  Trades total: {len(df)}")
    print(f"  Cols: {list(df.columns)[:15]}{'...' if len(df.columns)>15 else ''}")

    # Detect pnl_ticks col
    pnl_col = "pnl_ticks" if "pnl_ticks" in df.columns else None
    if not pnl_col:
        print("  WARN: no pnl_ticks col")
        return df

    df["_pnl"] = pd.to_numeric(df[pnl_col], errors="coerce").fillna(0)

    # Global stats
    n_total = len(df)
    n_wins = int((df["_pnl"] > 0).sum())
    n_losses = int((df["_pnl"] <= 0).sum())
    wr = n_wins / n_total if n_total else 0
    sum_wins = float(df.loc[df["_pnl"] > 0, "_pnl"].sum())
    sum_losses = float(df.loc[df["_pnl"] <= 0, "_pnl"].sum())  # negatif
    pf = (sum_wins / abs(sum_losses)) if sum_losses != 0 else float("inf")
    total_pnl = float(df["_pnl"].sum())
    pnl_usd_col = "pnl_usd" if "pnl_usd" in df.columns else None
    total_usd = float(pd.to_numeric(df[pnl_usd_col], errors="coerce").fillna(0).sum()) if pnl_usd_col else None

    print(f"\n  GLOBAL:")
    print(f"    n_total={n_total}  wins={n_wins}  losses={n_losses}  WR={wr*100:.1f}%")
    print(f"    sum_wins=+{sum_wins:.0f}t  sum_losses={sum_losses:.0f}t  PF={pf:.2f}")
    print(f"    PnL total: {total_pnl:+.0f} ticks{f' (${total_usd:+.2f})' if total_usd else ''}")
    print(f"    Avg per trade: {total_pnl/n_total:+.1f} ticks")

    # Par symbol
    if "symbol" in df.columns:
        print(f"\n  PAR SYMBOL:")
        for sym in sorted(df["symbol"].unique()):
            sub = df[df["symbol"] == sym]
            sub_wins = int((sub["_pnl"] > 0).sum())
            sub_pnl = float(sub["_pnl"].sum())
            print(f"    {sym}: n={len(sub)}  wins={sub_wins}  WR={sub_wins/len(sub)*100:.1f}%  pnl={sub_pnl:+.0f}t")

    # Par jour si entry_time
    if "entry_time" in df.columns:
        print(f"\n  PAR JOUR:")
        df["_date"] = pd.to_datetime(df["entry_time"], errors="coerce").dt.date
        for d in sorted(df["_date"].dropna().unique()):
            sub = df[df["_date"] == d]
            sub_wins = int((sub["_pnl"] > 0).sum())
            sub_pnl = float(sub["_pnl"].sum())
            print(f"    {d}: n={len(sub):>3d}  wins={sub_wins:>3d}  WR={sub_wins/len(sub)*100:.1f}%  pnl={sub_pnl:+.0f}t")

    # Outcomes distribution
    out_col = "outcome" if "outcome" in df.columns else ("exit_reason" if "exit_reason" in df.columns else None)
    if out_col:
        print(f"\n  OUTCOMES:")
        for out, cnt in df[out_col].value_counts().items():
            sub = df[df[out_col] == out]
            sub_pnl = float(sub["_pnl"].sum())
            print(f"    {out:15s}: n={cnt:>3d}  pnl={sub_pnl:+.0f}t  avg={sub_pnl/cnt:+.1f}t")

    # Duration stats
    if "duration_sec" in df.columns:
        dur = pd.to_numeric(df["duration_sec"], errors="coerce").dropna()
        if len(dur) > 0:
            print(f"\n  DURATION:")
            print(f"    median={dur.median():.0f}s  mean={dur.mean():.0f}s  max={dur.max():.0f}s")

    return df


def main():
    print("="*70)
    print("  ANALYSE COMPARATIVE 2 BOTS PAPER TRADING")
    print("="*70)

    # Bot 1 DMP Sim3
    df_bot1 = load_trades("*_trades.jsonl", exclude="databento")
    df_bot1 = summarize_bot("BOT 1 DMP (Sim3) - mia_paper_trader", df_bot1)

    # Bot 2 DB Sim2
    df_bot2 = load_trades("*_databento_trades.jsonl")
    df_bot2 = summarize_bot("BOT 2 DB (Sim2) - databento_paper_trader", df_bot2)

    # Comparaison cross-bot
    if df_bot1 is not None and not df_bot1.empty and df_bot2 is not None and not df_bot2.empty:
        print(f"\n{'='*70}")
        print(f"  COMPARAISON CROSS-BOT")
        print(f"{'='*70}")
        # WR ratio
        wr1 = (df_bot1["_pnl"] > 0).sum() / len(df_bot1) if len(df_bot1) else 0
        wr2 = (df_bot2["_pnl"] > 0).sum() / len(df_bot2) if len(df_bot2) else 0
        pnl1 = df_bot1["_pnl"].sum()
        pnl2 = df_bot2["_pnl"].sum()
        print(f"  WR Bot1 = {wr1*100:.1f}%  vs  Bot2 = {wr2*100:.1f}%")
        print(f"  PnL Bot1 = {pnl1:+.0f}t  vs  Bot2 = {pnl2:+.0f}t")
        print(f"  N trades Bot1 = {len(df_bot1)}  vs  Bot2 = {len(df_bot2)}")

        # Trades commune (meme jour, meme symbol, meme direction proche)
        if "entry_time" in df_bot1.columns and "entry_time" in df_bot2.columns:
            df_bot1["_dt"] = pd.to_datetime(df_bot1["entry_time"], errors="coerce")
            df_bot2["_dt"] = pd.to_datetime(df_bot2["entry_time"], errors="coerce")

            # Match : même symbol, entry < 5 min apart
            common = []
            for _, t2 in df_bot2.iterrows():
                close_t1 = df_bot1[
                    (df_bot1["symbol"] == t2["symbol"]) &
                    (abs(df_bot1["_dt"] - t2["_dt"]) < pd.Timedelta(minutes=5))
                ]
                if not close_t1.empty:
                    for _, t1 in close_t1.iterrows():
                        common.append({
                            "symbol": t2["symbol"],
                            "ts_bot2": t2["_dt"],
                            "ts_bot1": t1["_dt"],
                            "delta_min": (t1["_dt"] - t2["_dt"]).total_seconds() / 60,
                            "dir_bot1": t1.get("direction"),
                            "dir_bot2": t2.get("direction"),
                            "pnl_bot1": t1.get("pnl_ticks"),
                            "pnl_bot2": t2.get("pnl_ticks"),
                            "outcome_bot1": t1.get("outcome", t1.get("exit_reason")),
                            "outcome_bot2": t2.get("outcome", t2.get("exit_reason")),
                        })
            if common:
                print(f"\n  TRADES PROCHES (meme symbol, entry<5min): {len(common)}")
                df_c = pd.DataFrame(common)
                print(df_c.to_string(index=False))
            else:
                print(f"\n  Aucun trade proche entre les 2 bots")


if __name__ == "__main__":
    main()
