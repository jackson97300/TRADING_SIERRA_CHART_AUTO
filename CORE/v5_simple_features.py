"""
v5_simple_features.py — 6 features simples V5 (Jackson validation 02/05 samedi).

Created : 2026-05-02 samedi V5 build
Source : INVENTAIRE_DUMPER_VS_BOT.md TIER 2 booléens contextuels manquants V4.

Reproduit en Python depuis V4 dataset (jamais re-import DMP polluant) :

  1. bool_near_level     : proximité < 5 ticks d'au moins 1 level clé
  2. bool_ib_inside      : ib_complete=1 ET close in [ib_low, ib_high]
  3. bool_session_early  : ts_event UTC hour < 14 (≈ avant 10h ET DST)
  4. bool_va_confluence  : |cur_vpoc - prev_vpoc| / tick < 10
  5. vwap_triple_align   : -1/0/+1 selon position close vs vwap_d/w/m
  6. dist_open_cash      : (close - open_930_et) / TICK_SIZE

Dépendances V4 (toutes vérifiées présentes) :
  cur_vpoc, prev_vpoc, cur_vah, cur_val, vwap_d, vwap_w, vwap_m, pvwap,
  ib_high, ib_low, ib_complete, open_930_et, close, ts_event
"""

from __future__ import annotations
import pandas as pd
import numpy as np

TICK_SIZE = 0.25  # ES + NQ futures

# Niveaux clés pour bool_near_level
KEY_LEVELS = [
    "cur_vpoc", "cur_vah", "cur_val",
    "vwap_d", "vwap_w", "pvwap",
    "ib_high", "ib_low",
]

# Seuils
NEAR_LEVEL_THRESHOLD_TICKS = 5
VA_CONFLUENCE_THRESHOLD_TICKS = 10
SESSION_EARLY_HOUR_ET = 10  # avant 10h ET (DST-safe via tz_convert)


def add_v5_simple_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les 6 features simples V5 au dataset.

    Args:
        df : DataFrame V4 indexé ts_event ou avec col ts_event.
             Doit contenir close, ib_high/low, ib_complete, cur_vpoc,
             prev_vpoc, vwap_d/w/m, open_930_et.

    Returns:
        DataFrame enrichi avec 6 nouvelles cols.
    """
    out = df.copy()

    # Validation dependances (review code-reviewer 02/05 R4 : pvwap inclus)
    required = ["close", "cur_vpoc", "prev_vpoc", "cur_vah", "cur_val",
                "vwap_d", "vwap_w", "vwap_m", "pvwap", "ib_high", "ib_low",
                "ib_complete", "open_930_et", "ts_event"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        print(f"[v5_simple] WARN cols absentes : {missing}")

    close = out["close"]

    # 1. bool_near_level : proximité < 5 ticks d'au moins 1 level
    near = pd.Series(False, index=out.index)
    for lvl in KEY_LEVELS:
        if lvl in out.columns:
            dist_ticks = (close - out[lvl]).abs() / TICK_SIZE
            # NaN level → distance NaN → near = False (pas affirmer)
            near = near | (dist_ticks < NEAR_LEVEL_THRESHOLD_TICKS).fillna(False)
    out["bool_near_level"] = near.astype("Int8")

    # 2. bool_ib_inside : ib_complete=1 AND ib_low <= close <= ib_high
    if all(c in out.columns for c in ["ib_complete", "ib_low", "ib_high"]):
        ib_inside = (
            (out["ib_complete"] == 1)
            & (close >= out["ib_low"])
            & (close <= out["ib_high"])
        ).fillna(False)
        out["bool_ib_inside"] = ib_inside.astype("Int8")
    else:
        out["bool_ib_inside"] = pd.Series(0, index=out.index, dtype="Int8")

    # 3. bool_session_early : avant 10h ET (DST-safe via tz_convert New_York)
    # FIX review code-reviewer R5 : DST-safe (ne pas hardcoder UTC threshold,
    # ET swift hiver/ete = 1h decalage qui pollue label sur backfill 7 mois).
    if "ts_event" in out.columns:
        ts = pd.to_datetime(out["ts_event"], utc=True)
        ts_et = ts.dt.tz_convert("America/New_York")
        out["bool_session_early"] = (ts_et.dt.hour < SESSION_EARLY_HOUR_ET).astype("Int8")
    else:
        out["bool_session_early"] = pd.Series(0, index=out.index, dtype="Int8")

    # 4. bool_va_confluence : cur_vpoc proche de prev_vpoc
    if "cur_vpoc" in out.columns and "prev_vpoc" in out.columns:
        va_conflu = (
            (out["cur_vpoc"] - out["prev_vpoc"]).abs() / TICK_SIZE < VA_CONFLUENCE_THRESHOLD_TICKS
        ).fillna(False)
        out["bool_va_confluence"] = va_conflu.astype("Int8")
    else:
        out["bool_va_confluence"] = pd.Series(0, index=out.index, dtype="Int8")

    # 5. vwap_triple_align : -1 (tous below) / 0 (mixte) / +1 (tous above)
    # FIX review code-reviewer R7 : Int8 nullable homogene avec autres bools
    if all(c in out.columns for c in ["vwap_d", "vwap_w", "vwap_m"]):
        above_d = close > out["vwap_d"]
        above_w = close > out["vwap_w"]
        above_m = close > out["vwap_m"]
        all_above = (above_d & above_w & above_m).fillna(False)
        all_below = ((~above_d) & (~above_w) & (~above_m)).fillna(False)
        align = pd.Series(0, index=out.index, dtype="Int8")
        align.loc[all_above] = 1
        align.loc[all_below] = -1
        out["vwap_triple_align"] = align
    else:
        out["vwap_triple_align"] = pd.Series(0, index=out.index, dtype="Int8")

    # 6. dist_open_cash : ticks vs open 9:30 ET
    if "open_930_et" in out.columns:
        out["dist_open_cash"] = (close - out["open_930_et"]) / TICK_SIZE
    else:
        out["dist_open_cash"] = pd.Series(np.nan, index=out.index, dtype="float32")

    new_cols = ["bool_near_level", "bool_ib_inside", "bool_session_early",
                "bool_va_confluence", "vwap_triple_align", "dist_open_cash"]
    print(f"[v5_simple] +{len(new_cols)} features ajoutées : {new_cols}")
    return out


# ═════════════════════════════════════════════════════════════════════
# CLI smoke test
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    df = pd.read_parquet(ROOT / "DATA" / "DATASETS" / "ES_dataset_v4.parquet")
    print(f"[smoke] V4 ES loaded : {df.shape}")
    df_v5 = add_v5_simple_features(df)
    print(f"[smoke] V5 enriched : {df_v5.shape}")
    print()
    new_cols = ["bool_near_level", "bool_ib_inside", "bool_session_early",
                "bool_va_confluence", "vwap_triple_align", "dist_open_cash"]
    for c in new_cols:
        if c in df_v5.columns:
            s = df_v5[c]
            print(f"  {c:25} : NaN={s.isna().mean():.1%}, "
                  f"unique={s.nunique()}, "
                  f"mean={s.dropna().astype(float).mean():.3f}")
