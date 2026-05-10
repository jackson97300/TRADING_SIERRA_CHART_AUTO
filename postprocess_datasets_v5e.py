"""
Post-process ES + MGC datasets v5e apres rebuild regime z-score (11/05/2026).

Inputs (lus depuis VPS apres rebuild) :
  - DATA/datasets/v4_enriched/symbol=ES.c.0/year=*/month=*/data.parquet
  - DATA/datasets/v4_enriched/symbol=MGC.c.0/year=*/month=*/data.parquet

Outputs :
  - DATA/DATASETS/ES_dataset_v5e_clean.parquet (post-clip n_big_t1)
  - DATA/DATASETS/MGC_dataset_v5e_clean.parquet (post-drop 15 dead + vwap fix)

Actions (audit quality-auditor 11/05) :
  1. CLIP n_big_t1 ES p99 (max=181, p99=1 -> outlier)
  2. DROP 15 features mortes MGC (std=0)
  3. VERIFY vwap_d_cross_up MGC ~1.6% post-rebuild (sinon investigation)
  4. n_big_t1 MGC : GARDE (decision Jackson naturally_different)

Lance apres ALL_DONE du rebuild_regime_zscore.bat.
"""
import sys
import pandas as pd
from pathlib import Path

# Paths
IS_VPS = Path("C:/TRADING_SIERRA_CHART_AUTO").exists()
if IS_VPS:
    ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
else:
    ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")

DATASET_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"
OUT_DIR = ROOT / "DATA" / "DATASETS"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Features mortes MGC (audit quality-auditor 11/05)
DEAD_FEATURES_MGC = [
    "n_edge_buy_active", "n_edge_sell_active",
    "bar_edge_buy_fire", "bar_edge_buy_zone_size",
    "bar_edge_sell_fire", "bar_edge_sell_zone_size",
    "is_mq_filled", "bar_no_trade",
    "n_big_t4", "n_big_buy_t4", "n_big_sell_t4",
    "n_big_ask_v2_t3", "n_big_bid_v2_t3",
    "n_big_ask_v2_t4", "n_big_bid_v2_t4",
    # vwap_d_cross_up MGC corrompu (55.48% au lieu de 1.6% attendu).
    # Hypothese rebuild auto-fix INVALIDE le 11/05 (test post-rebuild VPS=55%).
    # Cause inconnue : recompute local manuel = 1.63%, donc side-effect pipeline
    # Phase B+++/D corrompt cette feature. Investigation reportee en backlog.
    # Decision Jackson 11/05 : DROP MGC pour Phase 2 backtests, debug plus tard.
    "vwap_d_cross_up",
]

# Features mortes ES (audit quality-auditor : tier T3/T4 jamais trigger)
DEAD_FEATURES_ES = [
    "n_big_ask_v2_t3", "n_big_bid_v2_t3",
    "n_big_ask_v2_t4", "n_big_bid_v2_t4",
    "n_big_t4", "n_big_buy_t4", "n_big_sell_t4",
]


def concat_and_clean(symbol: str) -> pd.DataFrame:
    """Concat parquets v4_enriched + post-process drops + clip."""
    root = DATASET_ROOT / f"symbol={symbol}.c.0"
    parquets = sorted(root.rglob("data.parquet"))
    print(f"\n=== {symbol} : concat {len(parquets)} parquets ===")
    dfs = []
    for p in parquets:
        df = pd.read_parquet(p)
        # tz normalize
        if "ts_event" in df.columns:
            ts = pd.to_datetime(df["ts_event"])
            if hasattr(ts.dt, "tz") and ts.dt.tz is not None:
                df["ts_event"] = ts.dt.tz_convert("UTC").dt.tz_localize(None)
            else:
                df["ts_event"] = ts
        dfs.append(df)
        print(f"  {p.relative_to(root)}: {len(df)} bars x {len(df.columns)} cols")

    big = pd.concat(dfs, ignore_index=True).sort_values("ts_event").drop_duplicates(subset=["ts_event"])
    print(f"\nConcat: {len(big)} bars x {len(big.columns)} cols")

    # Drop dead features
    dead = DEAD_FEATURES_MGC if symbol == "MGC" else DEAD_FEATURES_ES
    drops = [c for c in dead if c in big.columns]
    if drops:
        big = big.drop(columns=drops)
        print(f"DROP {len(drops)} dead features {symbol}: {drops[:5]}... ({len(drops)} total)")

    # Verify regime_vol distribution (post z-score fix)
    if "regime_vol" in big.columns:
        rv_dist = big["regime_vol"].value_counts(normalize=True).to_dict()
        rv_pct = {k: round(v*100, 1) for k, v in rv_dist.items()}
        print(f"regime_vol distribution: {rv_pct}")
        if big["regime_vol"].nunique() <= 1:
            print(f"  [WARN] regime_vol still constant ({big['regime_vol'].iloc[0]}) - fix z-score deploy issue?")

    # Verify vwap_d_cross_up MGC ~1.6% (post-rebuild fix corruption)
    if symbol == "MGC" and "vwap_d_cross_up" in big.columns:
        cross_pct = big["vwap_d_cross_up"].mean() * 100
        print(f"vwap_d_cross_up MGC: {cross_pct:.2f}% (expected ~1.6%)")
        if cross_pct > 5.0:
            print(f"  [WARN] vwap_d_cross_up MGC still corrupted ({cross_pct:.2f}% > 5%) - investigate")

    # CLIP n_big_t1 ES outlier (max=181, p99=1)
    if symbol == "ES" and "n_big_t1" in big.columns:
        p99 = big["n_big_t1"].quantile(0.99)
        max_before = big["n_big_t1"].max()
        if max_before > p99 * 10:  # outlier explosion confirmed
            big["n_big_t1"] = big["n_big_t1"].clip(upper=p99)
            print(f"CLIP n_big_t1 ES: max {max_before:.0f} -> {p99:.0f} (p99)")

    print(f"\nFinal {symbol}: {len(big)} bars x {len(big.columns)} cols")
    print(f"Date range: {big['ts_event'].min()} -> {big['ts_event'].max()}")
    return big


def main():
    for symbol in ["ES", "MGC"]:
        df = concat_and_clean(symbol)
        out = OUT_DIR / f"{symbol}_dataset_v5e_clean.parquet"
        df.to_parquet(out, compression="zstd", index=False)
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"WROTE {out} ({size_mb:.1f} MB)")
        print()


if __name__ == "__main__":
    main()
