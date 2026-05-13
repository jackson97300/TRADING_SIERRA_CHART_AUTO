"""vix_lite_reader.py — Loader + derivees VIX_Lite JSONL (schema vix_levels_1.1).

Source : DATA/vix_levels/year=YYYY/month=M/day=D/vix.jsonl
Produit : DataFrame VIX + features derivees calculees Python (regime, distances GEX).

But strategique (13/05/2026) : decoupler progressivement Bot 2 V6 + pipeline V4
du DMP C++ full pour les features VIX. Phase 1 = ce module standalone, validable
en isolation. Phase 2 = integration dans build_dataset_v4_dmp_databento.py.
Phase 3 = retrait des vix_* du DMP_MQ_FIELDS (full Databento).

Schema vix_levels_1.1 (20 valeurs par ligne) :
  ts (epoch ms UTC), schema_version,
  vix_level (prix VIX courant),
  vix_call, vix_put, vix_hvl,
  vix_1d_min, vix_1d_max,
  vix_call_0dte, vix_gamma_wall_0dte,
  vix_put_0dte, vix_hvl_0dte,
  vix_gex (array de 10 floats : GEX 1..10)

Auteur : MIA Trading System V2
  v1.0 (2026-05-13) : version initiale, parse JSONL + compute regime + dist_gex
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VIX_LITE_ROOT = ROOT / "DATA" / "vix_levels"


# ============================================================
# DERIVEES — pure functions (testables)
# ============================================================

def compute_vix_regime(level: Optional[float]) -> int:
    """Categorie regime VIX alignee DMP_Transform.h:683-689 :
        0 = calme    (VIX <= 15)
        1 = normal   (15 < VIX <= 25)
        2 = volatile (25 < VIX <= 35)
        3 = extreme  (VIX > 35)
    Si level None/NaN → fallback regime=1 (normal) comme le DMP (`fallback : regime normal`).
    """
    if level is None or pd.isna(level):
        return 1
    if level > 35.0:
        return 3
    if level > 25.0:
        return 2
    if level > 15.0:
        return 1
    return 0


def compute_vix_gex_distances(level: Optional[float], gex: Optional[list]) -> tuple[Optional[float], Optional[float]]:
    """Distance signed du VIX courant aux GEX nearest up/down (en points VIX, pas ticks).

    Returns (dist_up, dist_dn) :
        dist_up = GEX above_nearest - level    (> 0 si GEX au-dessus)
        dist_dn = GEX below_nearest - level    (< 0 si GEX en-dessous)
    Si pas de GEX au-dessus → dist_up = None. Idem dist_dn.
    Aligne sur convention DMP `dist_*_nearest_*` = (level - cur_price).
    """
    if level is None or pd.isna(level) or gex is None:
        return (None, None)

    valid_gex = [g for g in gex if g is not None and not pd.isna(g) and g > 0]
    if not valid_gex:
        return (None, None)

    above = [g for g in valid_gex if g > level]
    below = [g for g in valid_gex if g < level]

    dist_up = (min(above) - level) if above else None
    dist_dn = (max(below) - level) if below else None
    return (dist_up, dist_dn)


def compute_vix_above_hvl(level: Optional[float], hvl: Optional[float]) -> int:
    """1 si VIX > HVL (regime incertain selon DMP_Transform.h:692-693). 0 sinon ou None."""
    if level is None or hvl is None or pd.isna(level) or pd.isna(hvl):
        return 0
    return 1 if level > hvl else 0


# ============================================================
# LOADER — lecture Hive partitionne
# ============================================================

def load_vix_lite_jsonl(start: date, end: date) -> pd.DataFrame:
    """Charge VIX_Lite JSONL en DataFrame entre [start, end] inclus.

    Format Hive : DATA/vix_levels/year=YYYY/month=M/day=D/vix.jsonl
    1 ligne/min (RTH only en pratique, hors RTH = valeur figee CBOE).

    Returns DataFrame avec colonnes :
        ts_event (datetime UTC naive, floor min),
        vix_level, vix_call, vix_put, vix_hvl,
        vix_1d_min, vix_1d_max,
        vix_call_0dte, vix_gamma_wall_0dte,
        vix_put_0dte, vix_hvl_0dte,
        vix_gex_0..vix_gex_9 (10 colonnes flat),
        schema_version
    """
    rows: list[dict] = []
    cur = start
    while cur <= end:
        # Format Hive : year=YYYY/month=M/day=D (note : NO leading zero sur month/day,
        # cohérent avec MQ_Lite.cpp:185-187 et VIX_Lite.cpp:163-165)
        fpath = VIX_LITE_ROOT / f"year={cur.year}" / f"month={cur.month}" / f"day={cur.day}" / "vix.jsonl"
        if fpath.exists() and fpath.stat().st_size > 50:
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            rows.append(d)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                print(f"  [WARN] VIX_Lite read {fpath.name}: {e}")
        cur += timedelta(days=1)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # ts (epoch ms) -> ts_event (datetime UTC naive, floor min)
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None).dt.floor("min")
    df = df.drop(columns=["ts"])

    # Flatten vix_gex array : 1 colonne par GEX index
    if "vix_gex" in df.columns:
        # array peut etre None ou liste de 10 float/null
        gex_df = pd.DataFrame(
            df["vix_gex"].apply(lambda x: x if isinstance(x, list) and len(x) == 10 else [None] * 10).tolist(),
            columns=[f"vix_gex_{i}" for i in range(10)],
            index=df.index,
        )
        df = pd.concat([df.drop(columns=["vix_gex"]), gex_df], axis=1)

    # De-dup : si plusieurs lignes par minute (boot, rebuild), prendre la derniere
    df = df.groupby("ts_event").last().reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def enrich_vix_lite(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les features derivees au DataFrame VIX_Lite : regime, dist_gex.

    Calculees a la volee depuis vix_level + vix_gex_* + vix_hvl :
        vix_regime           : 0..3 categoriel
        dist_vix_gex_nearest_up : points (VIX above_nearest_gex - level)
        dist_vix_gex_nearest_dn : points (VIX below_nearest_gex - level)
        vix_above_hvl        : binaire 0/1
        dist_vix_hvl         : points (hvl - level)
        dist_vix_call        : points (call - level)
        dist_vix_put         : points (put - level)
        dist_vix_call_0dte   : points (call_0dte - level)
        dist_vix_put_0dte    : points (put_0dte - level)
        dist_vix_hvl_0dte    : points (hvl_0dte - level)
        vix_above_hvl_0dte   : binaire 0/1
    """
    if df.empty:
        return df

    out = df.copy()

    # Regime
    out["vix_regime"] = out["vix_level"].apply(compute_vix_regime)

    # Distance GEX nearest up/dn
    gex_cols = [f"vix_gex_{i}" for i in range(10)]
    def _row_gex_dists(row):
        gex = [row[c] for c in gex_cols if c in row.index]
        return compute_vix_gex_distances(row["vix_level"], gex)

    dists = out.apply(_row_gex_dists, axis=1, result_type="expand")
    out["dist_vix_gex_nearest_up"] = dists[0]
    out["dist_vix_gex_nearest_dn"] = dists[1]

    # Distances aux niveaux MQ (en points VIX, pas ticks — convention DMP_Transform.h:679)
    def _diff(level_col):
        if level_col not in out.columns:
            return pd.Series([None] * len(out), index=out.index)
        return out[level_col] - out["vix_level"]

    out["dist_vix_call"] = _diff("vix_call")
    out["dist_vix_put"] = _diff("vix_put")
    out["dist_vix_hvl"] = _diff("vix_hvl")
    out["dist_vix_call_0dte"] = _diff("vix_call_0dte")
    out["dist_vix_put_0dte"] = _diff("vix_put_0dte")
    out["dist_vix_hvl_0dte"] = _diff("vix_hvl_0dte")
    out["dist_vix_gamma_wall_0dte"] = _diff("vix_gamma_wall_0dte")

    # Above HVL booleans
    out["vix_above_hvl"] = out.apply(
        lambda r: compute_vix_above_hvl(r["vix_level"], r.get("vix_hvl")), axis=1
    )
    out["vix_above_hvl_0dte"] = out.apply(
        lambda r: compute_vix_above_hvl(r["vix_level"], r.get("vix_hvl_0dte")), axis=1
    )

    return out


# ============================================================
# TESTS INLINE (run direct python -m vix_lite_reader)
# ============================================================

def _test_compute_vix_regime():
    assert compute_vix_regime(10.0) == 0
    assert compute_vix_regime(18.0) == 1
    assert compute_vix_regime(28.0) == 2
    assert compute_vix_regime(40.0) == 3
    assert compute_vix_regime(None) == 1
    assert compute_vix_regime(float("nan")) == 1
    print("[OK] compute_vix_regime")


def _test_compute_vix_gex_distances():
    # GEX = [15, 17.5, 19, 18.5, 16.5] avec level=18
    # above_nearest = 18.5, dist_up = +0.5
    # below_nearest = 17.5, dist_dn = -0.5
    up, dn = compute_vix_gex_distances(18.0, [15.0, 17.5, 19.0, 18.5, 16.5])
    assert abs(up - 0.5) < 1e-6, f"expected 0.5, got {up}"
    assert abs(dn - (-0.5)) < 1e-6, f"expected -0.5, got {dn}"

    # Level > all GEX → dist_up = None
    up, dn = compute_vix_gex_distances(25.0, [15.0, 17.5, 19.0])
    assert up is None
    assert abs(dn - (-6.0)) < 1e-6

    # Level < all GEX → dist_dn = None
    up, dn = compute_vix_gex_distances(10.0, [15.0, 17.5])
    assert abs(up - 5.0) < 1e-6
    assert dn is None

    # Empty GEX → (None, None)
    up, dn = compute_vix_gex_distances(18.0, None)
    assert up is None and dn is None

    print("[OK] compute_vix_gex_distances")


def _test_load_real_data():
    """Test sur les donnees reelles du VPS si dispo localement."""
    today = date(2026, 5, 13)
    df = load_vix_lite_jsonl(today, today)
    if df.empty:
        print(f"[SKIP] aucun fichier VIX_Lite local pour {today} (normal si VPS only)")
        return
    print(f"[OK] load_vix_lite_jsonl: {len(df)} lignes")
    print(df.head())

    df_enr = enrich_vix_lite(df)
    print(f"[OK] enrich_vix_lite: +{len(df_enr.columns) - len(df.columns)} colonnes derivees")
    print("Last row:", df_enr.iloc[-1].to_dict())


if __name__ == "__main__":
    _test_compute_vix_regime()
    _test_compute_vix_gex_distances()
    _test_load_real_data()
    print("\n[ALL OK]")
