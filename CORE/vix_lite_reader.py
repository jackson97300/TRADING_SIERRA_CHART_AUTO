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

import numpy as np
import pandas as pd

# Sanity ranges alignes DMP_Reader.h:2103-2113 + VIX_Lite.cpp v1.3 :
#   vix_level : prix VIX cash 5..200 (low historique 9.14 + crash protect)
#   vix MQ levels : 5..150 (covid 2020 peak 82.69 + niveaux MQ peuvent monter 85-95)
VIX_LEVEL_MIN = 5.0
VIX_LEVEL_MAX = 200.0
VIX_MQ_MIN    = 5.0
VIX_MQ_MAX    = 150.0

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

    # FIX P0-1 (audit code-reviewer 13/05/2026) : sanity filter aligne DMP_Reader.h
    # + VIX_Lite.cpp v1.3 guards. Si JSONL contient une valeur out-of-range (bug
    # C++ guard ou MenthorQ reset post-16h), on aligne sur DMP_INVALID → NaN.
    # Evite divergence J+7 audit vix vs vixl sur edge cases.
    if "vix_level" in out.columns:
        out["vix_level"] = out["vix_level"].where(
            out["vix_level"].between(VIX_LEVEL_MIN, VIX_LEVEL_MAX), np.nan
        )
    mq_level_cols = [
        "vix_call", "vix_put", "vix_hvl", "vix_1d_min", "vix_1d_max",
        "vix_call_0dte", "vix_put_0dte", "vix_hvl_0dte", "vix_gamma_wall_0dte",
    ]
    for col in mq_level_cols:
        if col in out.columns:
            out[col] = out[col].where(out[col].between(VIX_MQ_MIN, VIX_MQ_MAX), np.nan)
    # GEX VIX (sg9-sg18) : meme range que MQ levels
    for i in range(10):
        col = f"vix_gex_{i}"
        if col in out.columns:
            out[col] = out[col].where(out[col].between(VIX_MQ_MIN, VIX_MQ_MAX), np.nan)

    # FIX P0-3 (audit code-reviewer) : vix_regime en float64 pour s'aligner sur
    # DMP_Transform.h:683-689 qui ecrit f.vix_regime = 1.0f (float). Sinon J+7
    # audit dtype mismatch (int64 vs float64) → faux positif d'incoherence.
    out["vix_regime"] = out["vix_level"].apply(compute_vix_regime).astype("float64")

    # Distance GEX nearest up/dn
    gex_cols = [f"vix_gex_{i}" for i in range(10)]
    def _row_gex_dists(row):
        gex = [row[c] for c in gex_cols if c in row.index]
        return compute_vix_gex_distances(row["vix_level"], gex)

    dists = out.apply(_row_gex_dists, axis=1, result_type="expand")
    out["dist_vix_gex_nearest_up"] = dists[0]
    out["dist_vix_gex_nearest_dn"] = dists[1]

    # Distances aux niveaux MQ (en points VIX, pas ticks — convention DMP_Transform.h:679
    # dist = level - vix_level, signe positif si level au-dessus).
    # FIX P0-2 (audit code-reviewer) : dtype float64 explicit quand colonne absente
    # (sinon pd.Series([None]*N) crée dtype object → casse parquet writer).
    def _diff(level_col):
        if level_col not in out.columns:
            return pd.Series(np.nan, index=out.index, dtype="float64")
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
# API STREAMING (Chantier 3 Live Enricher Phase 3a Jour 5)
# ============================================================
# Convention API streaming-aware Option D : ajout EN PARALLELE de la batch
# (additive-only, ne touche pas enrich_vix_lite/load_vix_lite_jsonl).
#
# vix_lite est PILOTE STATELESS : features pure row-level (sanity filter,
# distance level - close, regime classification, GEX nearest, above_hvl).
# Aucun rolling state. Convention VixLiteState vide reservee pour evolution.
#
# Plan agent verdict 13/05/2026 nuit : pilote stateless valide UNIQUEMENT
# l'outillage (tools/test_engine_parity.py + factory pattern). Le vrai test
# Pattern 11 (sérialisation, warmup R2, drift EMA) sera Lundi engine N°2
# stateful (e.g. EMA(vix_level, 60) wrapper).
#
# DRY garanti : batch enrich_vix_lite() vectorise rapide N'EST PAS modifie.
# Le streaming fait la meme transformation row-by-row pour live_enricher.
from dataclasses import dataclass


@dataclass
class VixLiteState:
    """State pilote stateless (Phase 3a Jour 5 reframe Plan agent).

    AUCUN state rolling : features pure row-level (sign(close - vwap),
    distance level - close, regime classification, above_hvl boolean).
    Reservé pour evolution future (e.g. EMA vix_level historique, regime
    transition counter pour debounce).

    Convention : factory pattern via state.get_engine_state("vix_lite", VixLiteState)
    dans live_enricher.py _process_bar_cycle pour valider l'API uniforme.
    """
    pass


def _filter_range_inplace(d: dict, col: str, lo: float, hi: float) -> None:
    """Sanity filter aligne batch enrich_vix_lite() : si v hors [lo,hi] -> NaN.

    Convention pandas .between(lo, hi) (inclusive). Si v est None/NaN, no-op.
    """
    v = d.get(col)
    if v is None:
        return
    try:
        # pd.isna gere NaN et None
        if pd.isna(v):
            return
        if not (lo <= v <= hi):
            d[col] = np.nan
    except (TypeError, ValueError):
        d[col] = np.nan


def enrich_vix_lite_streaming(row: dict, state: VixLiteState) -> dict:
    """API streaming vix_lite : enrich 1 row VIX (pilote Chantier 3 Jour 5).

    Reproduit fidelement enrich_vix_lite() (batch) en mode row-by-row.
    Convention DRY : pour test parite, batch_fn(df) appelee independamment
    via vectorise rapide (vs streaming iterrows lent). Le streaming est
    appele par live_enricher dans _process_bar_cycle.

    Args:
        row : dict avec inputs VIX (vix_level, vix_call, vix_put, vix_hvl,
              vix_1d_min/max, vix_call_0dte, vix_put_0dte, vix_hvl_0dte,
              vix_gamma_wall_0dte, vix_gex_0..9).
        state : VixLiteState (non utilise pilote stateless, requis pour
                convention API uniforme).

    Returns:
        dict enriched avec : sanity-filtered inputs + vix_regime +
        dist_vix_call/put/hvl + dist_vix_*_0dte + dist_vix_gamma_wall_0dte +
        dist_vix_gex_nearest_up/dn + vix_above_hvl + vix_above_hvl_0dte.
    """
    out = dict(row)

    # 1. Sanity filter aligne enrich_vix_lite() (P0-1 audit 13/05)
    _filter_range_inplace(out, "vix_level", VIX_LEVEL_MIN, VIX_LEVEL_MAX)
    for col in (
        "vix_call", "vix_put", "vix_hvl", "vix_1d_min", "vix_1d_max",
        "vix_call_0dte", "vix_put_0dte", "vix_hvl_0dte", "vix_gamma_wall_0dte",
    ):
        _filter_range_inplace(out, col, VIX_MQ_MIN, VIX_MQ_MAX)
    for i in range(10):
        _filter_range_inplace(out, f"vix_gex_{i}", VIX_MQ_MIN, VIX_MQ_MAX)

    # 2. vix_regime (float64 aligne enrich_vix_lite P0-3)
    vl = out.get("vix_level")
    out["vix_regime"] = float(compute_vix_regime(vl))

    # 3. dist_vix_* (level - vix_level), aligne enrich_vix_lite _diff()
    def _diff_row(level_col: str) -> Optional[float]:
        v = out.get(level_col)
        if v is None or vl is None:
            return np.nan
        try:
            if pd.isna(v) or pd.isna(vl):
                return np.nan
        except (TypeError, ValueError):
            return np.nan
        return float(v) - float(vl)

    out["dist_vix_call"] = _diff_row("vix_call")
    out["dist_vix_put"] = _diff_row("vix_put")
    out["dist_vix_hvl"] = _diff_row("vix_hvl")
    out["dist_vix_call_0dte"] = _diff_row("vix_call_0dte")
    out["dist_vix_put_0dte"] = _diff_row("vix_put_0dte")
    out["dist_vix_hvl_0dte"] = _diff_row("vix_hvl_0dte")
    out["dist_vix_gamma_wall_0dte"] = _diff_row("vix_gamma_wall_0dte")

    # 4. dist_vix_gex_nearest_up/dn
    gex = [out.get(f"vix_gex_{i}") for i in range(10)]
    up, dn = compute_vix_gex_distances(vl, gex)
    out["dist_vix_gex_nearest_up"] = up if up is not None else np.nan
    out["dist_vix_gex_nearest_dn"] = dn if dn is not None else np.nan

    # 5. above_hvl booleans (int)
    out["vix_above_hvl"] = compute_vix_above_hvl(vl, out.get("vix_hvl"))
    out["vix_above_hvl_0dte"] = compute_vix_above_hvl(vl, out.get("vix_hvl_0dte"))

    return out


# ============================================================
# ENGINE N°2 PILOTE STATEFUL — EMA(vix_level, 60)
# ============================================================
# Phase 3a Jour 5 (suite Plan agent recommendation engine N°2 stateful trivial).
#
# Convention API streaming-aware Option D VALIDEE definitivement par ce pilote :
#   1. State serialise pickle proprement (pas threading.RLock dans state)
#   2. Warmup R2 parity OK (continu == restart au milieu apres pickle save+load)
#   3. Pickle roundtrip OK (state apres N appels == state reloaded)
#
# Wrapper EMA(vix_level, span=60) = exponential moving average sur prix VIX.
# Utile en regime smoothing (transitions vix_regime moins bruite via EMA).
# Formule Wilder : ema[t] = alpha * x[t] + (1-alpha) * ema[t-1]
#                  avec alpha = 2/(span+1) = 2/61 ≈ 0.0328 pour span=60.

@dataclass
class VixEmaState:
    """State pilote stateful (Plan agent recommandation engine N°2).

    Maintient last_ema (float | None pour cold start) entre appels streaming.

    Attribut UNIQUE : last_ema. Volontairement minimal pour forcer tests :
      - Sérialisation pickle (last_ema = float OK, threading.Lock NOT OK)
      - Warmup R2 (continu vs restart : last_ema reload identique)
      - Drift IEEE 754 cumulatif (EMA = sum(alpha * x * (1-alpha)^k) → calcul incremental)

    Convention NaN : ignore_na=True (saute les NaN, ne propage pas le decay).
      Aligne sur `pd.ewm(span=span, adjust=False, ignore_na=True).mean()`.
      Justification : si VIX_Lite scsf restart 5 min sur VPS, on a un NaN gap.
      Avec ignore_na=False, le state diverge pendant 24h+ (decay >99% pour span=60).
      ignore_na=True traite NaN comme "no info" -> garde state, attend next non-NaN.

    Convention : factory pattern via state.get_engine_state("vix_ema_60", VixEmaState).
    """
    last_ema: Optional[float] = None
    span: int = 60  # EMA span (alpha = 2/(span+1))

    def __post_init__(self):
        # FIX P1-3 audit code-reviewer : validation span avant utilisation
        if not isinstance(self.span, int) or self.span < 2:
            raise ValueError(
                f"VixEmaState.span must be int >= 2 (got {self.span}). "
                f"span=1 donne alpha=1 (EMA = derniere valeur, inutile)."
            )

    @property
    def alpha(self) -> float:
        return 2.0 / (self.span + 1)


def apply_vix_ema_streaming(row: dict, state: VixEmaState) -> dict:
    """API streaming EMA(vix_level) (engine N°2 pilote stateful).

    Calcule vix_level_ema_60 incremental :
      ema[t] = alpha * vix_level[t] + (1-alpha) * ema[t-1]
      Cold start : ema[0] = vix_level[0]

    Si vix_level est NaN/None : passe-through (no update state).
    Si state.last_ema is None : init avec vix_level courant.

    Args:
        row : dict avec 'vix_level' (float, deja sanity-filtered par
              enrich_vix_lite_streaming).
        state : VixEmaState mutable (last_ema updated).

    Returns:
        dict row + 'vix_level_ema_60' (float | None si pas encore initialise).
    """
    out = dict(row)
    vl = out.get("vix_level")

    # Handle NaN/None : passe-through
    try:
        if vl is None or pd.isna(vl):
            out["vix_level_ema_60"] = state.last_ema  # peut etre None si jamais init
            return out
    except (TypeError, ValueError):
        out["vix_level_ema_60"] = state.last_ema
        return out

    vl_f = float(vl)

    # Cold start init
    if state.last_ema is None:
        state.last_ema = vl_f
        out["vix_level_ema_60"] = vl_f
        return out

    # Incremental EMA update
    a = state.alpha
    new_ema = a * vl_f + (1.0 - a) * state.last_ema
    state.last_ema = new_ema
    out["vix_level_ema_60"] = new_ema
    return out


def apply_vix_ema_batch(df: pd.DataFrame, span: int = 60) -> pd.DataFrame:
    """API batch EMA(vix_level) : oracle pandas ewm directement (perf + DRY).

    FIX P0-1 audit code-reviewer 13/05 nuit : initialement, on appelait
    streaming dans une boucle (DRY claim Plan agent). MAIS la convention NaN
    de notre streaming (ignore_na=True : saute NaN, garde state) divergeait
    silencieusement vs pandas default (ignore_na=False : decay multiplie par
    gap NaN). max_diff post-NaN = 7.26e-3 >> 1e-9.

    Decision : `apply_vix_ema_streaming` PRESERVE le state apres NaN (utile
    en prod si gap data Databento 5 min). On aligne le batch sur la MEME
    convention via pandas `ewm(span, adjust=False, ignore_na=True)`.

    Vrai DRY : le batch est l'oracle, le streaming doit matcher exactement.
    Test parite valide cette egalite.

    Args:
        df : DataFrame avec 'vix_level'.
        span : EMA span (default 60, alpha = 2/(span+1)).

    Returns:
        df + 'vix_level_ema_60' colonne (perf O(N) pandas vectorise, ~100ms
        pour 86k rows vs 30s iterrows naive).
    """
    out = df.copy()
    if "vix_level" not in out.columns:
        raise KeyError("'vix_level' manquant pour apply_vix_ema_batch")
    # Convention ignore_na=True alignee streaming (cf docstring VixEmaState).
    # adjust=False = formule recurrente ema[t] = alpha * x + (1-alpha) * ema[t-1]
    # (vs adjust=True qui fait sum infinite series normalisee, plus precis mais
    # different + ne supporte pas streaming).
    out[f"vix_level_ema_{span}"] = (
        out["vix_level"].ewm(span=span, adjust=False, ignore_na=True).mean()
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
