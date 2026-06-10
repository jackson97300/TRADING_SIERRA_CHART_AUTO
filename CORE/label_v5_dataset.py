"""
label_v5_dataset.py — Labeler V5 (Triple Barrier ATR-dynamique, sortie du bruit).

V4 etait : TP=9t SL=5t H=20 fixes -> SL=1 ATR median = bruit pur, PF=0.67 ML.
V5 fix Jackson 27/04 soir : SL/TP en fonction de ATR_at_entry (ticks).

Constantes choisies via grid_search_barrier.py Phase 1 (48 combinaisons testees) :
  K_SL = 1.5         -> SL = 1.5 × ATR_at_entry (median ~8 ticks ES, sortie du bruit)
  K_TP_RATIO = 2.0   -> TP = 2.0 × SL (R:R 2.0 standard pro)
  FORWARD_BARS = 60  -> 1h horizon (capter mouvement directionnel)

Distribution attendue (validee Phase 1 sur 351K bars ES) :
  BUY  ~32% / SELL ~32% / HOLD ~35%   (balanced 33/33/35 = Lopez ideal)
  Balance BUY/SELL = 0.503 (symetrique, pas de drift directionnel)

Output : ES_dataset_v5.parquet, NQ_dataset_v5.parquet
TODO Phase 2B : ajouter SL protege par niveau + TP cappe par mur.

Auteur : MIA Trading System V2
Date   : 2026-04-27 19:30
"""
from __future__ import annotations

import sys
import time
import glob
from pathlib import Path

import numpy as np
import pandas as pd
import numba

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Constantes V5 ATR-dynamique (cf DOCS/GRID_SEARCH_BARRIER_PHASE1.md)
TICK_SIZE = {"ES": 0.25, "NQ": 0.25}
K_SL = 1.5            # SL = 1.5 × ATR_at_entry (ticks)
K_TP_RATIO = 2.0      # TP = 2.0 × SL (R:R 2.0)
FORWARD_BARS = 60     # 60 bars 1m = 1h horizon


@numba.njit(cache=True)
def _label_atr_dynamic(highs, lows, closes, atrs, k_sl, k_tp_ratio, n_bars, tick_size):
    """
    Triple Barrier ATR-dynamique (V5).

    Pour chaque bar i :
      sl_ticks = k_sl × ATR_at_entry[i]
      tp_ticks = k_tp_ratio × sl_ticks
      Simulation BUY + SELL independantes sur n_bars forward, reconciliation.
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int8)
    exit_offsets = np.full(n, n_bars, dtype=np.int32)
    realized = np.zeros(n, dtype=np.float32)

    for i in range(n - n_bars):
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_ticks = k_sl * atr_t
        tp_ticks = k_tp_ratio * sl_ticks

        entry = closes[i]
        sl_pts = sl_ticks * tick_size
        tp_pts = tp_ticks * tick_size

        tp_long = entry + tp_pts
        sl_long = entry - sl_pts
        tp_short = entry - tp_pts
        sl_short = entry + sl_pts

        # BUY simulation
        buy_win = False
        buy_offset = n_bars
        for k in range(1, n_bars + 1):
            if i + k >= n:
                break
            h = highs[i + k]
            l = lows[i + k]
            if l <= sl_long:
                buy_offset = k
                break
            if h >= tp_long:
                buy_win = True
                buy_offset = k
                break

        # SELL simulation
        sell_win = False
        sell_offset = n_bars
        for k in range(1, n_bars + 1):
            if i + k >= n:
                break
            h = highs[i + k]
            l = lows[i + k]
            if h >= sl_short:
                sell_offset = k
                break
            if l <= tp_short:
                sell_win = True
                sell_offset = k
                break

        # Reconciliation
        if buy_win and sell_win:
            if buy_offset < sell_offset:
                labels[i] = 1
                exit_offsets[i] = buy_offset
                realized[i] = tp_ticks
            elif sell_offset < buy_offset:
                labels[i] = -1
                exit_offsets[i] = sell_offset
                realized[i] = -tp_ticks
            else:
                labels[i] = 0
                exit_offsets[i] = buy_offset
        elif buy_win:
            labels[i] = 1
            exit_offsets[i] = buy_offset
            realized[i] = tp_ticks
        elif sell_win:
            labels[i] = -1
            exit_offsets[i] = sell_offset
            realized[i] = -tp_ticks
        else:
            labels[i] = 0
            exit_offsets[i] = min(buy_offset, sell_offset)

    return labels, exit_offsets, realized


def compute_sample_weight_uniqueness(labels: np.ndarray, exit_offsets: np.ndarray) -> np.ndarray:
    """Lopez AFML ch.4 : sample_weight = 1 / nb labels concurrents (uniqueness)."""
    n = len(labels)
    coverage = np.zeros(n, dtype=np.int32)
    for i in range(n):
        end = min(i + exit_offsets[i], n)
        coverage[i:end] += 1
    weights = np.ones(n, dtype=np.float64)
    for i in range(n):
        end = min(i + exit_offsets[i], n)
        if end > i:
            mean_cov = coverage[i:end].mean()
            weights[i] = 1.0 / max(1.0, mean_cov)
    return weights


def label_v5_symbol(symbol: str) -> pd.DataFrame:
    """Charge v4_enriched 24m, applique Triple Barrier ATR-dynamique."""
    print(f"\n{'='*60}")
    print(f"  LABELING V5 (ATR-dynamique) — {symbol}")
    print(f"{'='*60}")

    paths = sorted(glob.glob(str(ROOT / f"DATA/datasets/v4_enriched/symbol={symbol}.c.0/year=*/month=*/data.parquet")))
    if not paths:
        raise FileNotFoundError(f"Pas de partitions v4_enriched pour {symbol}")
    print(f"  [1/4] Loading {len(paths)} partitions...")
    df_list = [pd.read_parquet(p) for p in paths]
    df = pd.concat(df_list, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"        {len(df):,} bars total")

    # Triple Barrier ATR-dynamique
    print(f"  [2/4] Triple Barrier ATR-dynamique (K_SL={K_SL}, K_TP_ratio={K_TP_RATIO}, H={FORWARD_BARS}bars)...")
    tick = TICK_SIZE[symbol]

    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)

    print(f"        ATR median = {np.nanmedian(atrs):.2f} ticks (SL median ≈ {K_SL*np.nanmedian(atrs):.1f}t, TP median ≈ {K_SL*K_TP_RATIO*np.nanmedian(atrs):.1f}t)")

    t0 = time.perf_counter()
    labels, exit_offsets, realized = _label_atr_dynamic(
        highs, lows, closes, atrs, K_SL, K_TP_RATIO, FORWARD_BARS, tick
    )
    print(f"        Done in {time.perf_counter()-t0:.1f}s")

    # Sample weight uniqueness Lopez
    print(f"  [3/4] Sample weight uniqueness Lopez ch.4...")
    t0 = time.perf_counter()
    sample_weight = compute_sample_weight_uniqueness(labels, exit_offsets)
    print(f"        Done in {time.perf_counter()-t0:.1f}s")
    print(f"        Mean sample_weight : {sample_weight.mean():.3f}")

    # Stats labels
    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_hold = int((labels == 0).sum())
    print(f"  [4/4] Labels : BUY={n_buy} ({n_buy/len(df)*100:.1f}%), "
          f"SELL={n_sell} ({n_sell/len(df)*100:.1f}%), "
          f"HOLD={n_hold} ({n_hold/len(df)*100:.1f}%)")
    if n_buy + n_sell > 0:
        print(f"        Balance BUY/(BUY+SELL) = {n_buy/(n_buy+n_sell):.3f}")

    # Ajouter cols
    df["label"] = labels
    df["exit_offset"] = exit_offsets
    df["realized_pts"] = realized
    df["sample_weight"] = sample_weight

    # ts ms epoch (compat walk_forward_splits)
    df["ts"] = (df["ts_event"].astype("int64") // 1000).astype("int64")

    df["partial_session"] = False
    df.loc[df.index[-FORWARD_BARS:], "partial_session"] = True

    return df


def main():
    print("=" * 70)
    print("LABEL V5 DATASET — Triple Barrier ATR-dynamique (Lopez compliant)")
    print("=" * 70)
    print(f"  K_SL = {K_SL}  (SL = K_SL × ATR_at_entry, sortie du bruit)")
    print(f"  K_TP_RATIO = {K_TP_RATIO}  (R:R standard 2.0)")
    print(f"  FORWARD_BARS = {FORWARD_BARS}  (horizon 1h sur 1m)")
    print(f"  Source : DOCS/GRID_SEARCH_BARRIER_PHASE1.md")

    out_dir = ROOT / "DATA" / "datasets"
    out_dir.mkdir(parents=True, exist_ok=True)

    for symbol in ["ES", "NQ"]:
        df_labeled = label_v5_symbol(symbol)
        out_path = out_dir / f"{symbol}_dataset_v5.parquet"
        df_labeled.to_parquet(out_path, index=False)
        print(f"  [SAVED] {out_path} ({out_path.stat().st_size // 1024 // 1024} MB)")
        print()


if __name__ == "__main__":
    main()
