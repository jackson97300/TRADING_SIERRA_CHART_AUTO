"""
databento_trade_features.py — Reproduction features trade-level depuis Databento

Created : 2026-05-02 samedi V5 build
Author : Jackson — "tout reproduit avec formules depuis Databento, jamais re-import DMP polluant"

Goal : reproduire en Python les features trade-level qui manquent dans V4 :
  - delta_day (cumul delta intraday RTH-reset)
  - large_trader_ratio (LTR) — sum(size > seuil) / total_size per bar
  - volume_imbalance — (buy - sell) / total per bar
  - delta_bar (cohérence redondante avec V4)
  - n_trades, avg_trade_size

Source : DATA/databento/GLBX.MDP3/trades/symbol={SYM}.c.0/year=*/month=*/day=*/data_*.parquet

Schema trades :
  ts_event, price, size, side (B=buyer aggressor, A=seller aggressor, N=neutral)

Output : DataFrame index ts_event 1m bars avec features calculees.
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TRADES_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades"

# Seuils LTR (Lopez : large trader = trade size > seuil)
# Calibres empiriquement sur ES/NQ avril 2026 :
#   ES median size = 1, p99 = ~50, threshold 20 raisonnable
#   NQ median size = 1, p99 = ~30, threshold 10 raisonnable
LTR_THRESHOLDS = {"ES": 20, "NQ": 10, "ES.c.0": 20, "NQ.c.0": 10}


def load_trades_for_period(symbol: str, start_date: str,
                            end_date: str = None) -> pd.DataFrame:
    """Charge trades Databento via path Hive jour par jour (memory-safe).

    Args:
        symbol : 'ES.c.0', 'NQ.c.0'
        start_date : 'YYYY-MM-DD' (obligatoire pour eviter charge 15 ans)
        end_date : 'YYYY-MM-DD' (default = start_date)

    Returns:
        DataFrame trades concat sur la periode.
    """
    base = TRADES_ROOT / f"symbol={symbol}"
    if not base.exists():
        return pd.DataFrame()

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) if end_date else start
    parts = []
    cur = start
    while cur <= end:
        # Path Hive : year=Y/month=M/day=D (sans zero padding)
        day_dir = base / f"year={cur.year}" / f"month={cur.month}" / f"day={cur.day}"
        if day_dir.exists():
            for parquet in sorted(day_dir.glob("data_*.parquet")):
                df = pd.read_parquet(parquet)
                parts.append(df)
        cur += pd.Timedelta(days=1)

    if not parts:
        return pd.DataFrame()
    full = pd.concat(parts, ignore_index=True)
    full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
    full = full.sort_values("ts_event").reset_index(drop=True)
    return full


def compute_trade_features_per_bar(df_trades: pd.DataFrame,
                                      symbol: str,
                                      freq: str = "1min") -> pd.DataFrame:
    """
    Agrege trades level → bars 1m avec features.

    Features par bar :
        - delta_bar : (buy_vol - sell_vol)
        - buy_vol : sum size where side='B'
        - sell_vol : sum size where side='A'
        - total_vol_trades : sum size
        - n_trades : count
        - avg_trade_size : mean size
        - max_trade_size : max size
        - large_trader_ratio : sum(size where size>=threshold) / total_size
        - n_large_trades : count(size >= threshold)
        - volume_imbalance : (buy - sell) / total

    Args:
        df_trades : DataFrame trades Databento
        symbol : 'ES' ou 'NQ' pour LTR threshold
        freq : '1min' default

    Returns:
        DataFrame indexed ts_event_floor avec features per bar.
    """
    if df_trades.empty:
        return pd.DataFrame()

    df = df_trades.copy()
    df["ts_bar"] = df["ts_event"].dt.floor(freq)
    df["is_buy"] = (df["side"] == "B").astype(int)
    df["is_sell"] = (df["side"] == "A").astype(int)
    df["buy_size"] = df["size"] * df["is_buy"]
    df["sell_size"] = df["size"] * df["is_sell"]

    # Threshold LTR
    threshold = LTR_THRESHOLDS.get(symbol, 20)
    df["is_large"] = (df["size"] >= threshold).astype(int)
    df["large_size"] = df["size"] * df["is_large"]

    # Aggregation par bar
    agg = df.groupby("ts_bar").agg(
        buy_vol=("buy_size", "sum"),
        sell_vol=("sell_size", "sum"),
        total_vol_trades=("size", "sum"),
        n_trades=("size", "count"),
        avg_trade_size=("size", "mean"),
        max_trade_size=("size", "max"),
        large_size_sum=("large_size", "sum"),
        n_large_trades=("is_large", "sum"),
    ).reset_index().rename(columns={"ts_bar": "ts_event"})

    # Features derivees
    agg["delta_bar_repro"] = agg["buy_vol"] - agg["sell_vol"]
    agg["large_trader_ratio_repro"] = (
        agg["large_size_sum"] / agg["total_vol_trades"].replace(0, np.nan)
    ).fillna(0)
    agg["volume_imbalance_repro"] = (
        (agg["buy_vol"] - agg["sell_vol"]) / agg["total_vol_trades"].replace(0, np.nan)
    ).fillna(0)

    # delta_day cumul avec RTH reset (9:30 ET = 13:30 UTC)
    agg["date_rth"] = (agg["ts_event"] - pd.Timedelta(hours=13, minutes=30)).dt.date
    agg["delta_day_repro"] = agg.groupby("date_rth")["delta_bar_repro"].cumsum()
    agg = agg.drop(columns=["date_rth", "large_size_sum"])

    return agg


def add_trade_features_to_dataset(df_v4: pd.DataFrame,
                                    symbol: str,
                                    df_trade_features: pd.DataFrame) -> pd.DataFrame:
    """Merge trade features par bar 1m dans V4 dataset."""
    if df_trade_features.empty:
        return df_v4

    out = df_v4.copy()
    # Convert V4 ts → ts_event aligned
    if "ts_event" not in out.columns and "ts" in out.columns:
        out["ts_event"] = pd.to_datetime(out["ts"], unit="ms", utc=True).dt.tz_convert(None)

    # Floor to 1m for join
    out["ts_event"] = out["ts_event"].dt.floor("1min")

    out = out.merge(df_trade_features, on="ts_event", how="left",
                     suffixes=("", "_trades"))
    return out


# ═════════════════════════════════════════════════════════════════════
# CLI smoke test
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Test : load trades ES 1 jour 2025-10-01")
    df = load_trades_for_period("ES.c.0", "2025-10-01", "2025-10-01")
    print(f"  Loaded {len(df)} trades")
    if not df.empty:
        print(f"  Range: {df['ts_event'].min()} → {df['ts_event'].max()}")
        feat = compute_trade_features_per_bar(df, symbol="ES")
        print(f"\n  Features per bar 1m: {len(feat)} bars")
        print(f"  Cols: {[c for c in feat.columns if c != 'ts_event']}")
        print(f"\n  Sample stats:")
        for c in ["delta_bar_repro", "large_trader_ratio_repro",
                  "volume_imbalance_repro", "n_trades", "avg_trade_size"]:
            if c in feat.columns:
                print(f"    {c:30}: mean={feat[c].mean():.3f}, "
                      f"std={feat[c].std():.3f}, p95={feat[c].quantile(0.95):.3f}")
