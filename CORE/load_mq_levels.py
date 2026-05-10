"""load_mq_levels.py — Loader pour DATA/mq_levels/ (MQ_Lite Hive partitioned).

Source brute :
  DATA/mq_levels/{ES,NQ}/year=YYYY/month=M/day=D/levels.jsonl
  ~5 lignes/jour/sym (init + new_day + level_change MenthorQ 1-2x/jour)

Pipeline :
  1. Read JSONL Hive partitioned (1 row = snapshot des 24 niveaux a un ts donne)
  2. Build levels_df cumul (avec ts, sym, mq_call, mq_put, ..., mq_gex[10], mq_blind[10])
  3. asof merge avec bars_df (chaque bar 1min recupere les niveaux les plus recents <= bar.ts)
  4. Calcule les distances ticks (dist_mq_call/put/hvl, dist_gex_nearest_up/dn, dist_blind_*)
  5. Calcule les booleans (bool_above_mq_call/hvl, bool_gex_flip_zone)
  6. Calcule gex_cluster_count (nb GEX dans rayon 30 ticks autour close)

Output schema = compatible drop-in avec load_dmp_jsonl() de build_dataset_v4_dmp_databento.py.
Champs produits = DMP_MQ_FIELDS (build_dataset_v4_dmp_databento.py:494).

Note : le fallback 0DTE superposes (Call_0DTE absent → HVL_0DTE → Call) est deja applique
       cote C++ MQ_Lite (cf MQ_Lite.cpp:225-233). Ici on ne re-fallback pas.

Usage :
    from CORE.load_mq_levels import load_mq_levels, attach_mq_distances

    levels_df = load_mq_levels("ES", date(2026, 4, 28), date(2026, 4, 28))
    bars_df = attach_mq_distances(bars_df, levels_df, tick_size=0.25)
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MQ_LEVELS_ROOT = ROOT / "DATA" / "mq_levels"
TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement
GEX_CLUSTER_RADIUS_TICKS = 30  # cf DMP_Transform.h:716, MQ_Lite.cpp:51

# Schema attendu downstream (build_dataset_v4_dmp_databento.py:494)
DMP_MQ_FIELDS = [
    "ts_event",
    "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
    "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
    "dist_1d_min_ticks", "dist_1d_max_ticks",
    "dist_gex_nearest_up", "dist_gex_nearest_dn",
    "dist_blind_nearest_up", "dist_blind_nearest_dn",
    "gex_cluster_count",
    "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
    # Note : dist_vix_gex_nearest_up/dn pas inclus ici (VIX retire de MQ_Lite v2,
    # cf MQ_Lite.cpp v2.0 changelog). A re-injecter Phase 2 via dumper VIX separe.
]


def _read_jsonl_file(fp: Path) -> list[dict]:
    """Read 1 levels.jsonl file → list of dicts."""
    rows = []
    if not fp.exists() or fp.stat().st_size == 0:
        return rows
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_mq_levels(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Load tous les MQ levels JSONL dans la fenetre [start, end].

    Returns DataFrame trie par ts avec colonnes :
        ts_event (datetime UTC, naive, floor minute)
        mq_call, mq_put, mq_hvl, mq_call_0dte, mq_put_0dte, mq_hvl_0dte (float ou NaN)
        mq_1d_min, mq_1d_max (float ou NaN)
        mq_gex (list[float|None] de longueur 10)
        mq_blind (list[float|None] de longueur 10)
        trigger (str : "init" / "new_day" / "level_change")
    """
    # MGC ajoute 10/05/2026 (Chantier 5/7) - dump JSONL via scsf_MIA_MQ_Lite_GC
    # produit DATA/mq_levels/GC/year=Y/month=M/day=D/levels.jsonl
    # Mapping symbole Python "MGC" -> dossier filesystem "GC" via SYMBOL_TO_FS_DIR
    # centralise (R1 fix code-reviewer 10/05).
    try:
        from CORE.constants import get_fs_dir, SYMBOL_TO_FS_DIR
    except ImportError:
        from constants import get_fs_dir, SYMBOL_TO_FS_DIR

    if symbol not in SYMBOL_TO_FS_DIR:
        raise ValueError(
            f"symbol must be in {list(SYMBOL_TO_FS_DIR.keys())}, got {symbol!r}"
        )
    fs_symbol = get_fs_dir(symbol)

    rows = []
    cur = start
    while cur <= end:
        partition = (MQ_LEVELS_ROOT / fs_symbol /
                     f"year={cur.year}" / f"month={cur.month}" / f"day={cur.day}")
        fp = partition / "levels.jsonl"
        rows.extend(_read_jsonl_file(fp))
        cur += timedelta(days=1)

    if not rows:
        # R2 fix code-reviewer 10/05 : warning explicite (anti-data-quality-trap).
        # Si MGC fraichement deploye (1ere semaine) ou MQ_Lite chart pas encore
        # attache, le pipeline downstream va generer NaN/0 pour TOUTES les
        # features mq_*/dist_mq_*/gex_*/blind_* -> ML apprend faux niveaux Gold.
        print(
            f"[WARN] load_mq_levels({symbol}): 0 rows on [{start},{end}] dans "
            f"{MQ_LEVELS_ROOT / fs_symbol} — features MQ seront NaN/0. "
            f"Verifier que scsf_MIA_MQ_Lite_{fs_symbol} est attache + actif."
        )
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Convertir ts (epoch ms) → datetime UTC naive floor minute
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None)
    # PAS de floor minute ici : les niveaux peuvent changer au sein d'une minute,
    # on garde la precision. Le merge asof gerera l'alignement.
    df = df.drop(columns=["ts"]).sort_values("ts_event").reset_index(drop=True)
    return df


def _calc_dist_ticks(level: float | None, price: float, tick_size: float) -> float:
    """Calcule (level - price) / tick_size, NaN si level invalide."""
    if level is None or pd.isna(level) or level <= 0:
        return np.nan
    return (level - price) / tick_size


def _nearest_above_below(levels: list, price: float, tick_size: float) -> tuple[float, float]:
    """Retourne (dist_above_ticks, dist_below_ticks) — NaN si rien."""
    above = np.nan
    below = np.nan
    if not isinstance(levels, (list, tuple, np.ndarray)):
        return above, below
    for lvl in levels:
        if lvl is None or pd.isna(lvl) or lvl <= 0:
            continue
        d = (lvl - price) / tick_size
        if d >= 0:
            if np.isnan(above) or d < above:
                above = d
        else:
            if np.isnan(below) or d > below:
                below = d
    return above, below


def _gex_cluster_count(gex_levels: list, price: float, tick_size: float, radius: int) -> int:
    """Nombre de GEX dans rayon (en ticks)."""
    if not isinstance(gex_levels, (list, tuple, np.ndarray)):
        return 0
    n = 0
    for lvl in gex_levels:
        if lvl is None or pd.isna(lvl) or lvl <= 0:
            continue
        d = abs(lvl - price) / tick_size
        if d <= radius:
            n += 1
    return n


def attach_mq_distances(bars_df: pd.DataFrame, levels_df: pd.DataFrame,
                         tick_size: float = TICK_SIZE) -> pd.DataFrame:
    """Merge asof bars_df + levels_df + calcule les distances + bool + count.

    Args:
        bars_df : DataFrame avec colonnes ['ts_event', 'close'] (au minimum).
                  ts_event en datetime UTC naive.
        levels_df : output de load_mq_levels() — peut etre vide.
        tick_size : par defaut 0.25 (ES = NQ).

    Returns:
        bars_df enrichi avec les colonnes DMP_MQ_FIELDS (sauf ts_event qui existe deja).
        Si levels_df est vide → toutes les colonnes MQ a NaN.
    """
    if "ts_event" not in bars_df.columns:
        raise ValueError("bars_df must contain 'ts_event' column")
    if "close" not in bars_df.columns:
        raise ValueError("bars_df must contain 'close' column")

    bars_df = bars_df.copy()

    # Initialise toutes les colonnes MQ a NaN si levels vide
    if levels_df is None or levels_df.empty:
        for col in DMP_MQ_FIELDS:
            if col == "ts_event":
                continue
            if col in ("bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
                       "gex_cluster_count"):
                bars_df[col] = 0  # int defaults
            else:
                bars_df[col] = np.nan
        return bars_df

    # Merge asof : pour chaque bar.ts, trouve la levels row avec ts <= bar.ts
    bars_sorted = bars_df.sort_values("ts_event").reset_index(drop=False)  # garde index original
    levels_sorted = levels_df.sort_values("ts_event").reset_index(drop=True)

    # FIX dtype : Databento OHLCV ts_event = <M8[us], levels = <M8[ns].
    # pandas merge_asof exige meme dtype. On force ns sur les 2.
    bars_sorted["ts_event"] = pd.to_datetime(bars_sorted["ts_event"]).astype("datetime64[ns]")
    levels_sorted["ts_event"] = pd.to_datetime(levels_sorted["ts_event"]).astype("datetime64[ns]")

    merged = pd.merge_asof(
        bars_sorted,
        levels_sorted,
        on="ts_event",
        direction="backward",  # last levels <= bar.ts
        suffixes=("", "_lvl"),
    )

    # Ordre original
    merged = merged.sort_values("index").set_index("index").reset_index(drop=True)
    bars_df = merged

    # Calcule distances + bool + count par row
    closes = bars_df["close"].values
    n = len(bars_df)

    # Pre-allocate
    out_cols = {col: np.full(n, np.nan, dtype=np.float64) for col in [
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
        "dist_1d_min_ticks", "dist_1d_max_ticks",
        "dist_gex_nearest_up", "dist_gex_nearest_dn",
        "dist_blind_nearest_up", "dist_blind_nearest_dn",
    ]}
    out_cols["gex_cluster_count"] = np.zeros(n, dtype=np.int32)
    out_cols["bool_above_mq_call"] = np.zeros(n, dtype=np.int32)
    out_cols["bool_above_mq_hvl"] = np.zeros(n, dtype=np.int32)
    out_cols["bool_gex_flip_zone"] = np.zeros(n, dtype=np.int32)

    # Helper d'acces sur un attribut row (None si pas merge)
    def _get(row_idx, col):
        v = bars_df[col].iloc[row_idx] if col in bars_df.columns else None
        if v is None or pd.isna(v):
            return None
        return v

    for i in range(n):
        price = closes[i]
        if price is None or pd.isna(price):
            continue

        mq_call = _get(i, "mq_call")
        mq_put = _get(i, "mq_put")
        mq_hvl = _get(i, "mq_hvl")

        out_cols["dist_mq_call"][i] = _calc_dist_ticks(mq_call, price, tick_size)
        out_cols["dist_mq_put"][i] = _calc_dist_ticks(mq_put, price, tick_size)
        out_cols["dist_mq_hvl"][i] = _calc_dist_ticks(mq_hvl, price, tick_size)
        out_cols["dist_mq_call_0dte"][i] = _calc_dist_ticks(_get(i, "mq_call_0dte"), price, tick_size)
        out_cols["dist_mq_put_0dte"][i] = _calc_dist_ticks(_get(i, "mq_put_0dte"), price, tick_size)
        out_cols["dist_mq_hvl_0dte"][i] = _calc_dist_ticks(_get(i, "mq_hvl_0dte"), price, tick_size)
        out_cols["dist_1d_min_ticks"][i] = _calc_dist_ticks(_get(i, "mq_1d_min"), price, tick_size)
        out_cols["dist_1d_max_ticks"][i] = _calc_dist_ticks(_get(i, "mq_1d_max"), price, tick_size)

        # GEX array
        gex = bars_df["mq_gex"].iloc[i] if "mq_gex" in bars_df.columns else None
        gex_above, gex_below = _nearest_above_below(gex, price, tick_size)
        out_cols["dist_gex_nearest_up"][i] = gex_above
        out_cols["dist_gex_nearest_dn"][i] = gex_below
        out_cols["gex_cluster_count"][i] = _gex_cluster_count(gex, price, tick_size,
                                                                GEX_CLUSTER_RADIUS_TICKS)

        # Blind array
        blind = bars_df["mq_blind"].iloc[i] if "mq_blind" in bars_df.columns else None
        blind_above, blind_below = _nearest_above_below(blind, price, tick_size)
        out_cols["dist_blind_nearest_up"][i] = blind_above
        out_cols["dist_blind_nearest_dn"][i] = blind_below

        # Booleans
        if mq_call is not None and not pd.isna(mq_call):
            out_cols["bool_above_mq_call"][i] = 1 if price > mq_call else 0
        if mq_hvl is not None and not pd.isna(mq_hvl):
            out_cols["bool_above_mq_hvl"][i] = 1 if price > mq_hvl else 0
        if (mq_call is not None and not pd.isna(mq_call)
                and mq_put is not None and not pd.isna(mq_put)):
            out_cols["bool_gex_flip_zone"][i] = 1 if (mq_put <= price <= mq_call) else 0

    # Drop les colonnes raw level (mq_call, mq_put, etc.) une fois les distances calculees
    raw_level_cols = ["mq_call", "mq_put", "mq_hvl", "mq_call_0dte", "mq_put_0dte",
                      "mq_hvl_0dte", "mq_1d_min", "mq_1d_max", "mq_gex", "mq_blind",
                      "sym", "schema_version", "trigger"]
    for col in raw_level_cols:
        if col in bars_df.columns:
            bars_df = bars_df.drop(columns=[col])

    # Inject les calculated cols
    for col, vals in out_cols.items():
        bars_df[col] = vals

    return bars_df


# ============================================================
# Smoke test standalone
# ============================================================
if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("  SMOKE TEST load_mq_levels")
    print("=" * 70)

    today = date(2026, 4, 28)

    for sym in ["ES", "NQ"]:
        print(f"\n--- {sym} ---")
        df = load_mq_levels(sym, today, today)
        if df.empty:
            print(f"  no data for {sym} on {today}")
            continue
        print(f"  rows: {len(df)}")
        print(f"  cols: {list(df.columns)}")
        print(f"  triggers: {df['trigger'].value_counts().to_dict() if 'trigger' in df.columns else '<missing>'}")
        if "mq_call" in df.columns:
            print(f"  mq_call range: {df['mq_call'].min()} - {df['mq_call'].max()}")
        if "mq_blind" in df.columns:
            n_blind_lists = df["mq_blind"].apply(lambda x: isinstance(x, list)).sum()
            print(f"  mq_blind list rows: {n_blind_lists}/{len(df)}")
        # Test attach_mq_distances avec une fake bar
        fake_bars = pd.DataFrame({
            "ts_event": [df["ts_event"].max() + pd.Timedelta(seconds=30)],
            "close": [7165.0 if sym == "ES" else 27152.75],
        })
        enriched = attach_mq_distances(fake_bars, df)
        print(f"  enriched cols: {sorted(c for c in enriched.columns if c.startswith(('dist_', 'bool_', 'gex_')))}")
        print(f"  sample : {enriched.iloc[0].to_dict()}")
