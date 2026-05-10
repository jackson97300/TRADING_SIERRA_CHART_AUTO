"""
footprint_builder.py — Reconstruction footprint cellule depuis Databento Trades.

Le "footprint" est une reconstruction de l'orderflow par cellule de prix :
  Pour chaque bar i et chaque prix P traite dans la bar :
    - ask_vol = volume des trades aggressor BUY (lifting offer)
    - bid_vol = volume des trades aggressor SELL (hitting bid)

Cette reconstruction permet de calculer ensuite :
  - Imbalance diagonale (Ask[P+tick] / Bid[P]) -> Edge Zones
  - Imbalance verticale (Ask[P] / Bid[P]) -> Reversal Imbalance
  - Stacks (cellules consecutives Ask>>Bid ou Bid>>Ask) -> Stacked Imbalance / Triple
  - Absorption (gros volume Ask au high mais close < high) -> Absorption Ask

Convention Databento `side` (verifie sur leurs docs) :
  'A' = aggressor BUY (acheteur agressif lifte l'offer)  -> AskVolume au prix
  'B' = aggressor SELL (vendeur agressif hit le bid)     -> BidVolume au prix
  'N' = auction/halt/mid (no aggressor)                  -> ignore (exclu du footprint)

Equivalent Sierra Chart :
  AVAP(price, offset=0) -> Ask Volume At Price (la cellule rose/orange dans le footprint)
  BVAP(price, offset=0) -> Bid Volume At Price (la cellule bleue dans le footprint)

Performance :
  Pour 1 mois (~25K bars + ~8M trades), ~30s en Python pur.
  Vectorise via groupby(['bar_idx', 'price_bucket']) pour minimiser les boucles.

Auteur : Phase B+++ Bloc 3 (2026-04-26) - feature #1 Edge Zones prereq
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement


def build_footprint_per_bar(
    trades_df: pd.DataFrame,
    bar_starts: pd.Series,
    tick: float = TICK_SIZE,
) -> Dict[int, Dict[float, Dict[str, float]]]:
    """
    Reconstruit le footprint cellule pour chaque bar.

    Args:
        trades_df: DataFrame trades avec colonnes ts_event, price, size, side
                   (filtre prealable : trades dans la fenetre des bars)
        bar_starts: Series timestamps des debut de chaque bar (taille N)
        tick: tick size de l'instrument (0.25 pour ES + NQ)

    Returns:
        dict[bar_idx (0..N-1) -> dict[price (rounded to tick) -> {
            'ask_vol': float (sum sizes side='A'),
            'bid_vol': float (sum sizes side='B'),
            'total_vol': float,
            'n_trades': int
        }]]

    Notes:
      - Si un bar n'a pas de trades : entry absente du dict (caller doit handle)
      - side='N' (auctions) sont ignores
      - price arrondi au tick le plus proche (ex: 6500.0625 -> 6500.0 si tick=0.25)
    """
    if trades_df.empty:
        return {}

    df = trades_df.copy()

    # Tz-align : both trades_df.ts_event and bar_starts must be tz-aware UTC (or both naive)
    bar_starts_s = pd.Series(bar_starts).reset_index(drop=True)
    if df["ts_event"].dt.tz is not None and bar_starts_s.dt.tz is None:
        bar_starts_s = bar_starts_s.dt.tz_localize("UTC")
    elif df["ts_event"].dt.tz is None and bar_starts_s.dt.tz is not None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")

    # Bucketize prix au tick
    df["price_bucket"] = (df["price"] / tick).round() * tick

    # Filter side='N' (auctions/halts/mid)
    df = df[df["side"].isin(["A", "B"])]
    if df.empty:
        return {}

    # Bin trades to bar idx via searchsorted
    bar_starts_arr = bar_starts_s.values
    df_sorted = df.sort_values("ts_event").reset_index(drop=True)
    bar_idx = np.searchsorted(bar_starts_arr, df_sorted["ts_event"].values, side="right") - 1
    bar_idx = np.clip(bar_idx, 0, len(bar_starts_arr) - 1)
    df_sorted["bar_idx"] = bar_idx

    # Filter trades hors fenetre (avant 1ere bar)
    df_sorted = df_sorted[df_sorted["ts_event"] >= bar_starts_s.iloc[0]]
    if df_sorted.empty:
        return {}

    # Aggregate par (bar_idx, price_bucket, side) pour minimiser boucles
    # Approach vectorise : pivot sur side
    agg = df_sorted.groupby(["bar_idx", "price_bucket", "side"]).agg(
        vol=("size", "sum"),
        n=("size", "count"),
    ).reset_index()

    # Build dict structure - itertuples 10x plus rapide que iterrows (review 26/04)
    footprint: Dict[int, Dict[float, Dict[str, float]]] = {}
    for row in agg.itertuples(index=False):
        bidx = int(row.bar_idx)
        price = float(row.price_bucket)
        side = row.side
        vol = float(row.vol)
        n = int(row.n)

        if bidx not in footprint:
            footprint[bidx] = {}
        if price not in footprint[bidx]:
            footprint[bidx][price] = {"ask_vol": 0.0, "bid_vol": 0.0,
                                       "total_vol": 0.0, "n_trades": 0}

        if side == "A":
            footprint[bidx][price]["ask_vol"] = vol
        elif side == "B":
            footprint[bidx][price]["bid_vol"] = vol
        footprint[bidx][price]["total_vol"] += vol
        footprint[bidx][price]["n_trades"] += n

    return footprint


def get_footprint_stats(footprint: Dict[int, Dict[float, Dict[str, float]]]) -> Dict[str, float]:
    """Stats globaux pour debug : n bars, n cells total, max ask, max bid, etc."""
    n_bars = len(footprint)
    n_cells = sum(len(cells) for cells in footprint.values())
    if n_cells == 0:
        return {"n_bars": 0, "n_cells": 0}

    all_ask = []
    all_bid = []
    for cells in footprint.values():
        for cell in cells.values():
            all_ask.append(cell["ask_vol"])
            all_bid.append(cell["bid_vol"])

    return {
        "n_bars": n_bars,
        "n_cells": n_cells,
        "avg_cells_per_bar": n_cells / n_bars,
        "max_ask_vol": max(all_ask) if all_ask else 0,
        "max_bid_vol": max(all_bid) if all_bid else 0,
        "median_ask_vol": np.median(all_ask) if all_ask else 0,
        "median_bid_vol": np.median(all_bid) if all_bid else 0,
    }
