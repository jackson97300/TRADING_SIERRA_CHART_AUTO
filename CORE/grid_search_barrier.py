"""
grid_search_barrier.py — Recherche empirique SL/TP/H optimaux Triple Barrier.

Phase 1 du fix labeling (27/04/2026 soir, demande Jackson).
Probleme : labels actuels TP=9 SL=5 H=20 = bruit pur (SL=1 ATR median = touche random).
Resultat : ML ne capte rien, PF=0.67 ES BUY post-fix anti-triche.

Cette etude teste empiriquement (K_SL, K_TP_ratio, H) sur 351K bars ES :
  - K_SL ∈ {1.0, 1.5, 2.0, 2.5} → SL = K_SL × ATR_at_entry (en ticks)
  - K_TP_ratio ∈ {1.5, 2.0, 2.5} → TP = K_TP_ratio × SL (R:R)
  - H ∈ {30, 60, 90} → horizon en bars 1m

Pour chaque combinaison, on calcule :
  - Distribution labels (% BUY, % SELL, % HOLD)
  - WR moyenne d'un trader random (long/short equiprobable)
  - PF moyen random
  - Si WR_random ≈ 50% et PF_random ≈ 1.0 → bruit pur, ML peut rien capter
  - Si WR_random < 50% (e.g. 45%) → labels asymetriques exploitable

Auteur : MIA Trading System V2
Date   : 2026-04-27 19:00
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import numba

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


@numba.njit(cache=True)
def _label_atr_dynamic(highs, lows, closes, atrs, k_sl, k_tp_ratio, n_bars):
    """
    Triple Barrier ATR-dynamique.

    SL = k_sl × ATR_at_entry (ticks)
    TP = k_tp_ratio × SL (ticks)
    H  = n_bars

    Returns : labels +1/-1/0, exit_offsets, realized_pts
    """
    n = len(closes)
    TICK = 0.25
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
        sl_pts = sl_ticks * TICK
        tp_pts = tp_ticks * TICK

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


def evaluate_barrier(highs, lows, closes, atrs, k_sl, k_tp_ratio, n_bars):
    """Calcule labels + stats pour 1 combinaison."""
    labels, _, realized = _label_atr_dynamic(highs, lows, closes, atrs, k_sl, k_tp_ratio, n_bars)

    n = len(labels)
    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_hold = int((labels == 0).sum())

    # WR random : un trader qui prend random buy/sell sur tous les signaux
    # Sur les bars labelees +1 ou -1, si trader random choisit la bonne direction = win
    # WR_random = 0.5 * P(label != 0) (= % directionnels)
    # Mais on veut surtout : ratio BUY/(BUY+SELL) — si ≠ 0.5 c'est asymetrique
    n_directional = n_buy + n_sell
    pct_directional = n_directional / n if n > 0 else 0.0
    pct_buy_among_directional = n_buy / n_directional if n_directional > 0 else 0.5

    # SL effective median en ticks
    sl_median_ticks = np.nanmedian(atrs) * k_sl
    tp_median_ticks = sl_median_ticks * k_tp_ratio

    return {
        "k_sl": k_sl,
        "k_tp_ratio": k_tp_ratio,
        "n_bars": n_bars,
        "sl_median_t": round(sl_median_ticks, 2),
        "tp_median_t": round(tp_median_ticks, 2),
        "n_buy": n_buy,
        "n_sell": n_sell,
        "n_hold": n_hold,
        "pct_buy": round(n_buy / n * 100, 2),
        "pct_sell": round(n_sell / n * 100, 2),
        "pct_hold": round(n_hold / n * 100, 2),
        "pct_directional": round(pct_directional * 100, 2),
        "buy_sell_balance": round(pct_buy_among_directional, 3),
    }


def main():
    print("=" * 70)
    print("GRID SEARCH BARRIER — Phase 1 ATR-pur (sans niveau protection)")
    print("=" * 70)

    print("\n[1] Loading ES_dataset_v4...")
    df = pd.read_parquet(ROOT / "DATA/datasets/ES_dataset_v4.parquet",
                         columns=["high", "low", "close", "atr", "ts_event"])
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"    {len(df):,} bars ES")

    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)

    print(f"    ATR median = {np.nanmedian(atrs):.2f} ticks")
    print(f"    Range 1bar median = {np.nanmedian((df['high']-df['low']).values)/0.25:.2f} ticks")

    # Grid
    K_SL_VALUES = [1.0, 1.5, 2.0, 2.5]
    K_TP_RATIOS = [1.5, 2.0, 2.5]
    H_VALUES = [20, 30, 60, 90]

    results = []
    total = len(K_SL_VALUES) * len(K_TP_RATIOS) * len(H_VALUES)
    print(f"\n[2] Grid search : {total} combinaisons...")

    t0 = time.perf_counter()
    idx = 0
    for k_sl in K_SL_VALUES:
        for k_tp_ratio in K_TP_RATIOS:
            for n_bars in H_VALUES:
                idx += 1
                t1 = time.perf_counter()
                stats = evaluate_barrier(highs, lows, closes, atrs, k_sl, k_tp_ratio, n_bars)
                elapsed = time.perf_counter() - t1
                stats["time_s"] = round(elapsed, 1)
                results.append(stats)
                print(f"  [{idx:2d}/{total}] K_SL={k_sl} K_TP_ratio={k_tp_ratio} H={n_bars} | "
                      f"SL≈{stats['sl_median_t']:.1f}t TP≈{stats['tp_median_t']:.1f}t | "
                      f"BUY={stats['pct_buy']:.1f}% SELL={stats['pct_sell']:.1f}% "
                      f"HOLD={stats['pct_hold']:.1f}% | bal={stats['buy_sell_balance']:.3f} | "
                      f"{elapsed:.1f}s")

    print(f"\n[3] Total elapsed : {time.perf_counter()-t0:.1f}s")

    # Save + report
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values("pct_directional", ascending=False)

    out_path = ROOT / "DOCS" / "GRID_SEARCH_BARRIER_PHASE1.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Grid Search Barrier — Phase 1 ATR-pur (ES, 27/04/2026)\n\n")
        f.write("## Contexte\n\n")
        f.write("Probleme : labels actuels v4 (TP=9 SL=5 H=20) → PF=0.67 post-fix anti-triche.\n")
        f.write("Cause : SL=5t = 1 ATR median = bruit pur, label random walk.\n\n")
        f.write("## Resultats (trie par % directionnel decroissant)\n\n")
        f.write("Lecture :\n")
        f.write("- **pct_directional** : % bars avec label != 0 (signal exploitable)\n")
        f.write("- **buy_sell_balance** : ratio BUY/(BUY+SELL). Proche de 0.5 = symetrique. Loin = drift directionnel\n")
        f.write("- **SL/TP en ticks median** : pour comparer avec ATR median 5.4t et range 1bar 5t\n\n")
        f.write(df_results.to_markdown(index=False))
        f.write("\n\n## Recommandation\n\n")
        f.write("Sera completee post-Phase 2 (avec niveau protection).\n")

    print(f"\n[4] Rapport : {out_path}")
    print(f"\n[5] TOP 5 combinaisons (% directionnel) :")
    print(df_results.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
