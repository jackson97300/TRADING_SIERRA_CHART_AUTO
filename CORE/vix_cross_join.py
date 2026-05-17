"""
VIX cross-join pour MGC - 12/05/2026

Le pipeline V4 MGC utilise Databento exclusivement (pas DMP JSONL Sierra),
donc vix_level/vix_regime sont absents du parquet MGC v4_enriched (verifie
12/05 : 0 cols VIX dans DATA/datasets/v4_enriched/symbol=MGC.c.0/).

VIX cash CBOE est unique au monde (pas MGC-specifique vs ES-specifique).
Solution : cross-join VIX depuis DMP JSONL ES sur ts_event UTC commun.

Source : DATA/ES/YYYYMMDD_ES.jsonl champs `vix_level` + `vix_regime`
(populates par DMP C++ via Chart 15 VIX cash).

Output : df_mgc enrichi avec vix_level (float) + vix_regime (0/1/2/3).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


VIX_FIELDS = ["ts", "vix_level", "vix_regime"]
DMP_ES_DIR = Path("DATA/ES")  # relative to project root


def load_vix_from_es_jsonl(start: date, end: date, dmp_es_dir: Path | None = None) -> pd.DataFrame:
    """Load vix_level + vix_regime from ES DMP JSONL files.

    VIX est globalement commun (CBOE cash), donc lecture depuis ES JSONL suffit
    pour cross-join sur MGC (meme ts_event UTC, 1-min granularite).

    Args:
        start, end : range dates inclusif
        dmp_es_dir : override path (par defaut DATA/ES relative project root)

    Returns:
        DataFrame ['ts_event', 'vix_level', 'vix_regime'] dedupliquee par minute.
        Empty si aucun fichier trouve.
    """
    if dmp_es_dir is None:
        dmp_es_dir = DMP_ES_DIR

    rows = []
    cur = start
    while cur <= end:
        ymd = cur.strftime("%Y%m%d")
        fpath = dmp_es_dir / f"{ymd}_ES.jsonl"
        if fpath.exists() and fpath.stat().st_size > 1000:
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        try:
                            d = json.loads(line)
                            row = {k: d.get(k) for k in VIX_FIELDS}
                            rows.append(row)
                        except Exception:
                            continue
            except Exception as e:
                print(f"  [WARN] VIX read {fpath.name}: {e}")
        cur += timedelta(days=1)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None).dt.floor("min")
    df = df.drop(columns=["ts"])
    # De-dup par minute (DMP peut ecrire 2 lignes/min)
    df = df.groupby("ts_event").last().reset_index()
    # Drop rows ou VIX absent ou invalide (0.0 = DMP sentinel "invalid")
    df = df[df["vix_level"].notna() & (df["vix_level"] > 0)]
    return df[["ts_event", "vix_level", "vix_regime"]]


def add_vix_cross_join(df_mgc: pd.DataFrame, dmp_es_dir: Path | None = None) -> pd.DataFrame:
    """Cross-join VIX (depuis ES JSONL) sur df_mgc via ts_event.

    Strategy : merge_asof backward (assigne dernier VIX connu <= ts_event MGC).
    Tolerance 5 min (VIX cash mis a jour ~chaque minute en RTH, plus rare AH).

    Args:
        df_mgc : DataFrame MGC avec colonne 'ts_event' (datetime64, UTC-naive)

    Returns:
        df_mgc + 2 colonnes ['vix_level', 'vix_regime']. NaN si pas de match.
    """
    if df_mgc.empty:
        df_mgc["vix_level"] = np.nan
        df_mgc["vix_regime"] = np.nan
        return df_mgc

    ts_min = pd.to_datetime(df_mgc["ts_event"]).min()
    ts_max = pd.to_datetime(df_mgc["ts_event"]).max()
    # Marge 1 jour avant pour merge_asof backward
    start = (ts_min - pd.Timedelta(days=1)).date()
    end = ts_max.date()

    df_vix = load_vix_from_es_jsonl(start, end, dmp_es_dir=dmp_es_dir)

    if df_vix.empty:
        print(f"  [WARN] VIX cross-join : aucun ES JSONL VIX trouve {start} -> {end}")
        df_mgc = df_mgc.copy()
        df_mgc["vix_level"] = np.nan
        df_mgc["vix_regime"] = np.nan
        return df_mgc

    # Sort obligatoire pour merge_asof
    df_mgc = df_mgc.sort_values("ts_event").reset_index(drop=True)
    df_vix = df_vix.sort_values("ts_event").reset_index(drop=True)

    # Ensure datetime64 (drop tz if present)
    df_mgc["ts_event"] = pd.to_datetime(df_mgc["ts_event"]).dt.tz_localize(None) \
        if pd.api.types.is_datetime64tz_dtype(df_mgc["ts_event"]) \
        else pd.to_datetime(df_mgc["ts_event"])

    merged = pd.merge_asof(
        df_mgc,
        df_vix,
        on="ts_event",
        direction="backward",
        tolerance=pd.Timedelta(minutes=5),
    )

    n_matched = merged["vix_level"].notna().sum()
    pct = 100 * n_matched / len(merged) if len(merged) > 0 else 0
    print(f"  VIX cross-join : {n_matched}/{len(merged)} bars matched ({pct:.1f}%)")

    return merged


if __name__ == "__main__":
    # Test rapide : load VIX 1 jour, check shape
    import sys
    test_start = date(2026, 4, 23)
    test_end = date(2026, 4, 23)
    root = Path(__file__).resolve().parents[1]
    dmp_dir = root / "DATA" / "ES"
    df = load_vix_from_es_jsonl(test_start, test_end, dmp_es_dir=dmp_dir)
    print(f"VIX 1 day {test_start} : {len(df)} bars")
    if not df.empty:
        print(df.head(3).to_string())
        print(f"Range vix_level : {df['vix_level'].min():.2f} - {df['vix_level'].max():.2f}")
        print(f"Regime distribution : {df['vix_regime'].value_counts().to_dict()}")
