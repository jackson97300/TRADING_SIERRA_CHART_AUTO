"""
label_v4_dataset.py — Labeler V4 (Triple Barrier + sample_weight Lopez AFML).

Labelle directement le dataset v4_enriched 24m (175 ML features) en :
  1. Chargeant les 13 mois ES + NQ (concat)
  2. Calculant labels Triple Barrier (TP/SL ticks fixes)
  3. Calculant sample_weight Lopez ch.4 (label uniqueness)
  4. Sauvant ES_dataset_v4.parquet + NQ_dataset_v4.parquet

Avantages vs labeler.py V1 :
  - Pas de dependance sur DMP JSONL legacy
  - Direct sur backfill 24m enrichi
  - Use bar_high/bar_low (deja ajoutes par Phase 1)

Triple Barrier (Lopez AFML ch.3) :
  TP = +tp_ticks * tick
  SL = -sl_ticks * tick
  Horizon : forward_bars (= 20 bars 1m = 20 min)
  label = +1 si TP touche en premier
  label = -1 si SL touche en premier
  label =  0 si horizon atteint sans TP/SL (timeout)

Sample weight (Lopez AFML ch.4) :
  Pour chaque label, compte combien d'autres labels chevauchent (concurrence).
  weight = 1 / max(1, mean_concurrent_labels)
  Lopez : evite biais regression sur labels trop overlapping.

Auteur : Phase ML V4 (2026-04-27)
"""
from __future__ import annotations

import sys
import time
import glob
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import numba

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Constantes Lopez (cf CLAUDE.md)
TICK_SIZE = {"ES": 0.25, "NQ": 0.25}
TP_TICKS = {"ES": 9, "NQ": 36}    # R:R 1.8 (calibre Jackson 29/03)
SL_TICKS = {"ES": 5, "NQ": 20}
FORWARD_BARS = 20  # 20 min (= horizon Triple Barrier)


@numba.njit(cache=True)
def _simulate_tpsl_numba(highs, lows, closes, tp_pts, sl_pts, n_bars):
    """
    Triple Barrier propre : 2 simulations independantes BUY + SELL, reconciliation.

    BUY win : TP_long (+tp_pts) touche AVANT SL_long (-sl_pts).
    SELL win : TP_short (-tp_pts) touche AVANT SL_short (+sl_pts).
    Si les 2 touchent dans n_bars : le PREMIER gagne (offset minimum).
    Sinon : HOLD (0).

    Returns : labels +1/-1/0, exit_offsets, realized_pts
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int8)
    exit_offsets = np.full(n, n_bars, dtype=np.int32)
    realized = np.zeros(n, dtype=np.float32)

    for i in range(n - n_bars):
        entry = closes[i]
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
            if l <= sl_long:  # SL touched first
                buy_offset = k
                break
            if h >= tp_long:  # TP touched first
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
            if h >= sl_short:  # SL touched first (prix monte)
                sell_offset = k
                break
            if l <= tp_short:  # TP touched first (prix baisse)
                sell_win = True
                sell_offset = k
                break

        # Reconciliation : qui a "win" en premier ?
        if buy_win and sell_win:
            # Les 2 win dans n_bars -> celui avec offset min gagne
            if buy_offset < sell_offset:
                labels[i] = 1
                exit_offsets[i] = buy_offset
                realized[i] = tp_pts
            elif sell_offset < buy_offset:
                labels[i] = -1
                exit_offsets[i] = sell_offset
                realized[i] = -tp_pts
            else:
                # Meme bar : conservateur HOLD
                labels[i] = 0
                exit_offsets[i] = buy_offset
        elif buy_win:
            labels[i] = 1
            exit_offsets[i] = buy_offset
            realized[i] = tp_pts
        elif sell_win:
            labels[i] = -1
            exit_offsets[i] = sell_offset
            realized[i] = -tp_pts
        else:
            labels[i] = 0
            exit_offsets[i] = min(buy_offset, sell_offset)

    return labels, exit_offsets, realized


def compute_sample_weight_uniqueness(labels: np.ndarray, exit_offsets: np.ndarray) -> np.ndarray:
    """
    Lopez AFML ch.4 : sample_weight = 1 / nb labels concurrents.

    Si label[i] a horizon [i, i+exit_offset[i]], il est "concurrent" avec tous
    les labels j tel que [j, j+exit_offset[j]] chevauche [i, i+exit_offset[i]].
    """
    n = len(labels)
    # Pour chaque bar t, compter nb labels actifs (= dont l'horizon couvre t)
    coverage = np.zeros(n, dtype=np.int32)
    for i in range(n):
        end = min(i + exit_offsets[i], n)
        coverage[i:end] += 1

    # Pour chaque label i, mean coverage sur son horizon
    weights = np.ones(n, dtype=np.float64)
    for i in range(n):
        end = min(i + exit_offsets[i], n)
        if end > i:
            mean_cov = coverage[i:end].mean()
            weights[i] = 1.0 / max(1.0, mean_cov)
    return weights


def label_v4_symbol(symbol: str) -> pd.DataFrame:
    """
    Charge v4_enriched 24m pour un symbol, applique Triple Barrier + sample_weight.

    Returns :
        DataFrame avec features ML + label + sample_weight + exit_offset
    """
    print(f"\n{'='*60}")
    print(f"  LABELING V4 — {symbol}")
    print(f"{'='*60}")

    # 1. Charger 13 mois v4_enriched
    paths = sorted(glob.glob(str(ROOT / f"DATA/datasets/v4_enriched/symbol={symbol}.c.0/year=*/month=*/data.parquet")))
    if not paths:
        raise FileNotFoundError(f"Pas de partitions v4_enriched pour {symbol}")
    print(f"  [1/4] Loading {len(paths)} partitions...")
    df_list = [pd.read_parquet(p) for p in paths]
    df = pd.concat(df_list, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"        {len(df):,} bars total")

    # 2. Triple Barrier
    print(f"  [2/4] Triple Barrier labeling (TP={TP_TICKS[symbol]}t, SL={SL_TICKS[symbol]}t, H={FORWARD_BARS}bars)...")
    tick = TICK_SIZE[symbol]
    tp_pts = TP_TICKS[symbol] * tick
    sl_pts = SL_TICKS[symbol] * tick

    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)

    t0 = time.perf_counter()
    labels, exit_offsets, realized = _simulate_tpsl_numba(
        highs, lows, closes, tp_pts, sl_pts, FORWARD_BARS
    )
    print(f"        Done in {time.perf_counter()-t0:.1f}s")

    # 3. Sample weight uniqueness Lopez
    print(f"  [3/4] Sample weight uniqueness Lopez ch.4...")
    t0 = time.perf_counter()
    sample_weight = compute_sample_weight_uniqueness(labels, exit_offsets)
    print(f"        Done in {time.perf_counter()-t0:.1f}s")
    print(f"        Mean sample_weight : {sample_weight.mean():.3f}")

    # 4. Stats labels
    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_hold = int((labels == 0).sum())
    print(f"  [4/4] Labels : BUY={n_buy} ({n_buy/len(df)*100:.1f}%), "
          f"SELL={n_sell} ({n_sell/len(df)*100:.1f}%), "
          f"HOLD={n_hold} ({n_hold/len(df)*100:.1f}%)")

    # Ajouter cols
    df["label"] = labels
    df["exit_offset"] = exit_offsets
    df["realized_pts"] = realized
    df["sample_weight"] = sample_weight

    # ts en ms epoch (compat train_lightgbm.py walk_forward_splits)
    # FIX 27/04 : ts_event est datetime64[us, UTC] (microsec, pas nanos).
    # astype("int64") retourne donc microsec. Pour ms : // 1000.
    df["ts"] = (df["ts_event"].astype("int64") // 1000).astype("int64")

    # partial_session : marquer derniers FORWARD_BARS (pas assez de futur)
    df["partial_session"] = False
    df.loc[df.index[-FORWARD_BARS:], "partial_session"] = True

    return df


def main():
    print("=" * 70)
    print("LABEL V4 DATASET — Triple Barrier + Sample Weight Lopez")
    print("=" * 70)

    out_dir = ROOT / "DATA" / "datasets"
    out_dir.mkdir(parents=True, exist_ok=True)

    for symbol in ["ES", "NQ"]:
        df_labeled = label_v4_symbol(symbol)
        out_path = out_dir / f"{symbol}_dataset_v4.parquet"
        df_labeled.to_parquet(out_path, index=False)
        print(f"  [SAVED] {out_path} ({out_path.stat().st_size // 1024 // 1024} MB)")
        print()


if __name__ == "__main__":
    main()
