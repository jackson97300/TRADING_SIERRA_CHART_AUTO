"""
smoke_test_mq_cat4_per_tf.py — Smoke test MQ x 3 TF + CAT4 x 3 TF.

Created : 2026-05-02 01:00 UTC (nuit, mode auto avec contrôle agent).
Goal : valider que add_mq_levels_per_tf et add_im_features_per_tf ne
crashent pas sur vraies donnees Databento parquet (1 jour ES + NQ).

Si le smoke passe : code MQ + CAT4 utilisable samedi sans debug.
Si crash : noter erreur exacte dans output, fix samedi 9h tete reposee.
"""

from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from enrich_dataset_v5_htf import (
    enrich_1m_with_all_htf,
    add_mq_levels_per_tf,
    add_im_features_per_tf,
)

PARQUET_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"


def load_one_day_from_parquet(symbol: str, year: int, month: int, day: int) -> pd.DataFrame:
    base = PARQUET_ROOT / f"symbol={symbol}" / f"year={year}" / f"month={month}" / f"day={day}"
    if not base.exists():
        return pd.DataFrame()
    parts = []
    for p in sorted(base.glob("*.parquet")):
        df = pd.read_parquet(p)
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    full = pd.concat(parts, ignore_index=True)
    if "ts_event" not in full.columns:
        full = full.reset_index().rename(columns={"index": "ts_event"})
    full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
    full = full.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)
    return full


def main():
    print("=" * 70)
    print("SMOKE TEST MQ x 3 TF + CAT4 x 3 TF")
    print("=" * 70)

    target_year, target_month = 2026, 4
    target_day = None
    for d in range(28, 21, -1):
        nq_dir = PARQUET_ROOT / "symbol=NQ.c.0" / f"year={target_year}" / f"month={target_month}" / f"day={d}"
        es_dir = PARQUET_ROOT / "symbol=ES.c.0" / f"year={target_year}" / f"month={target_month}" / f"day={d}"
        if nq_dir.exists() and es_dir.exists():
            target_day = d
            break
    if target_day is None:
        print("[FAIL] Aucun jour avec ES + NQ disponible avril 2026")
        sys.exit(1)
    print(f"  Test sur {target_year}-{target_month:02d}-{target_day:02d}")

    df_nq = load_one_day_from_parquet("NQ.c.0", target_year, target_month, target_day)
    df_es = load_one_day_from_parquet("ES.c.0", target_year, target_month, target_day)
    print(f"  NQ bars 1m : {len(df_nq)}")
    print(f"  ES bars 1m : {len(df_es)}")
    if df_nq.empty or df_es.empty:
        print("[FAIL] Pas de donnees")
        sys.exit(1)

    print("\n[1/3] enrich_1m_with_all_htf NQ ...")
    try:
        df_nq_v5 = enrich_1m_with_all_htf(df_nq)
        htf_cols = [c for c in df_nq_v5.columns if any(c.endswith(s) for s in ("_5m", "_15m", "_1h"))]
        print(f"  OK -- {len(df_nq_v5)} rows, +{len(htf_cols)} HTF cols")
    except Exception as e:
        print(f"  [CRASH enrich NQ] {type(e).__name__}: {e}")
        sys.exit(2)

    print("\n[2/3] enrich_1m_with_all_htf ES ...")
    try:
        df_es_v5 = enrich_1m_with_all_htf(df_es)
        htf_cols_es = [c for c in df_es_v5.columns if any(c.endswith(s) for s in ("_5m", "_15m", "_1h"))]
        print(f"  OK -- {len(df_es_v5)} rows, +{len(htf_cols_es)} HTF cols")
    except Exception as e:
        print(f"  [CRASH enrich ES] {type(e).__name__}: {e}")
        sys.exit(2)

    print("\n[3a/3] add_mq_levels_per_tf NQ ...")
    df_nq_v5["close"] = df_nq_v5["close"].astype(float)
    df_nq_v5["mq_call"] = df_nq_v5["close"] + 50
    df_nq_v5["mq_put"] = df_nq_v5["close"] - 50
    df_nq_v5["mq_hvl"] = df_nq_v5["close"] - 10
    df_nq_v5["dist_mq_call_pct"] = (df_nq_v5["mq_call"] - df_nq_v5["close"]) / df_nq_v5["close"] * 100
    df_nq_v5["dist_mq_put_pct"] = (df_nq_v5["mq_put"] - df_nq_v5["close"]) / df_nq_v5["close"] * 100
    df_nq_v5["dist_mq_hvl_pct"] = (df_nq_v5["mq_hvl"] - df_nq_v5["close"]) / df_nq_v5["close"] * 100
    df_nq_v5["bool_above_mq_call"] = (df_nq_v5["close"] > df_nq_v5["mq_call"]).astype("Int8")
    df_nq_v5["bool_above_mq_hvl"] = (df_nq_v5["close"] > df_nq_v5["mq_hvl"]).astype("Int8")
    df_nq_v5["dist_1d_min_ticks"] = -200
    df_nq_v5["dist_1d_max_ticks"] = 200
    try:
        df_nq_mq = add_mq_levels_per_tf(df_nq_v5)
        new_mq_cols = [c for c in df_nq_mq.columns if c not in df_nq_v5.columns]
        print(f"  OK -- {len(df_nq_mq)} rows, +{len(new_mq_cols)} cols MQ per TF")
        sample_cols = [c for c in new_mq_cols if c.startswith("dist_mq_call_pct") or c.startswith("bool_above_mq_call")][:6]
        if sample_cols:
            print(f"  Sample cols : {sample_cols}")
            print(df_nq_mq[sample_cols].describe().to_string())
    except Exception as e:
        print(f"  [CRASH MQ] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(3)

    print("\n[3b/3] add_im_features_per_tf (ES + NQ) ...")
    try:
        df_es_im, df_nq_im = add_im_features_per_tf(df_es_v5, df_nq_v5)
        new_im_cols_nq = [c for c in df_nq_im.columns if c.startswith("im_") and c not in df_nq_v5.columns]
        new_im_cols_es = [c for c in df_es_im.columns if c.startswith("im_") and c not in df_es_v5.columns]
        print(f"  OK -- NQ +{len(new_im_cols_nq)} im cols, ES +{len(new_im_cols_es)} im cols")
        if new_im_cols_nq:
            print(f"  Sample NQ : {new_im_cols_nq[:6]}")
    except Exception as e:
        print(f"  [CRASH CAT4] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(4)

    print("\n" + "=" * 70)
    print("SMOKE TEST PASSED -- MQ + CAT4 utilisables samedi")
    print("=" * 70)


if __name__ == "__main__":
    main()
