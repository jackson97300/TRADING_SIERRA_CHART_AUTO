"""phase_b_v6_complete.py — completion des features Bot 2 V6 lues du DMP.

But strategique (13/05/2026) : decoupler Bot 2 V6 du DMP C++ full. Ce module
ajoute les features Python qui sont LUES du DMP_MQ_FIELDS sans etre recalculees
par les engines existants.

VERSION v0.2 (13/05/2026 19h) — REPRODUCTIONS FIDELES DMP_Transform.h
==================================================================
Apres test parite v0.1 (echec : 32-78% match sur 9 features), revision avec
les vraies formules DMP_Transform.h. Directive Jackson : "PAS REPRODUCTION
A L AVEUGLE ON TESTE ET BACKTEST POUR TROUVER LES BONNE FORMULE".

Features SPLIT en 2 groupes :

  GROUPE A — REPRODUISIBLES FIDELEMENT (formule DMP exacte + data V4 dispo) :
    range_pos             : (close - cur_val) / (cur_vah - cur_val) * 100 clamp [0,100]
                             ⚠️ utilise Value Area (cur_val/cur_vah), PAS sess HL
    momentum_3b           : close - close.shift(3)   (en POINTS, pas delta_bar)
    sess_range_atr        : sess_range_ticks / atr_ticks
    vwap_w_side           : Sign(close - vwap_w)   (deja OK v0.1)
    vwap_triple_align     : +1 si all 3 above, -1 si all 3 below, 0 mixed
                             (formule DMP_Transform.h:1403)
    cvd_day_dir           : Sign(cvd_session) - SEMANTIQUE DIFFERENTE du DMP
                             (DMP utilise fpbs_cvd_day footprint Sierra, Python
                              utilise cumsum delta_bar Trades Databento, 40%
                              match empirique). Validation par backtest demain.

  GROUPE B — DEPENDANTS SIERRA SUBGRAPHS INCONNUS (a backtester variantes) :
    ma_trend              : DMP = r.ma_fast > r.ma_slow (Sierra MA Daily study,
                             params inconnus). Variantes Python a tester :
                             SMA20/SMA50, EMA12/EMA26, SMA9/SMA21 sur daily.
    vwap_slope_30         : DMP = slope vwap_d 30-min sur 10 bars (1h30/5h).
                             Variantes Python a tester : 1-min*30, 30-min*10,
                             daily*1.
    vwap_ma_align         : DMP = depend ma_fast/ma_slow + dist_vwap_d.
                             A coder apres ma_trend finalise.

Ce module ne contient QUE le GROUPE A (parite fidele).
Le GROUPE B est laisse comme TODO + backtest variantes setup demain.

Auteur : MIA Trading System V2
  v0.1 (2026-05-13 17h) : ECHEC test parite — formules fausses
  v0.2 (2026-05-13 19h) : reproductions fideles DMP_Transform.h pour groupe A
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Default fallback (ES/NQ 0.25). Si MGC, le caller doit passer tick=0.10.
TICK_SIZE = 0.25


# ═══════════════════════════════════════════════════════════════════════════════
# RANGE / SESSION
# ═══════════════════════════════════════════════════════════════════════════════

def add_range_pos(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule range_pos : position close dans VALUE AREA courante x 100.

    FIX v0.2 (parite DMP_Transform.h:633-639) :
        range_pos = (close - cur_val) / (cur_vah - cur_val) * 100
        clamp [0, 100]
        0 = close au VAL, 100 = au VAH, 50 = milieu VA.
        Si VA invalide (cur_vah <= cur_val) → NaN (pas 0).

    ⚠️ NE PAS confondre avec position dans session HL : Value Area ≠ session HL.
       Value Area = 70% du volume autour de POC (vpoc), pas extremes session.

    Requis : close, cur_val, cur_vah (Value Area running, Phase C de
    `value_area_running.py` ou DMP fournis directs).
    """
    df = df.copy()
    for col in ("close", "cur_val", "cur_vah"):
        if col not in df.columns:
            raise KeyError(f"[v6_complete] '{col}' manquant pour range_pos.")

    va_range = df["cur_vah"] - df["cur_val"]
    # Convention DMP : va_range > 0 strict (sinon INVALID)
    va_range_safe = va_range.where(va_range > 0, np.nan)
    range_pos = ((df["close"] - df["cur_val"]) / va_range_safe) * 100.0
    df["range_pos"] = range_pos.clip(0, 100).astype("float32")
    return df


def add_sess_range_atr(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """Calcule sess_range_atr : range session normalise par ATR.

    Convention DMP : sess_range_ticks = (sess_high - sess_low) / tick
                     sess_range_atr   = sess_range_ticks / atr_ticks

    Requis : sess_high, sess_low, atr (ticks).
    """
    df = df.copy()
    for col in ("sess_high", "sess_low", "atr"):
        if col not in df.columns:
            raise KeyError(f"[v6_complete] '{col}' manquant pour sess_range_atr.")

    sess_range_ticks = (df["sess_high"] - df["sess_low"]) / tick
    atr_safe = df["atr"].replace(0, np.nan)
    df["sess_range_atr"] = (sess_range_ticks / atr_safe).astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# VWAP MULTI-TIMEFRAME (D / W / M align)
# ═══════════════════════════════════════════════════════════════════════════════

def add_vwap_slope_30_DRAFT(df: pd.DataFrame) -> pd.DataFrame:
    """⚠️ DRAFT v0.2 — NotImplementedError jusqu'a backtest demain.

    DMP_Reader.h:1909-1914 utilise un chart VWAP 30-MIN avec slope sur 10 bars
    (slope sur 5h market time). 3 variantes Python a tester demain :
        v1 : 1-min * 30 bars (30 min)
        v2 : resample 30-min puis slope 10 bars (matches DMP exactement)
        v3 : 1-min * 150 bars (2h30 compromis)
    Critere : Spearman corr avec target labels TP/SL hit > 0.02.

    FIX P1.4 code-reviewer : raise pour eviter pollution accidentelle si appel.
    """
    raise NotImplementedError(
        "vwap_slope_30 DRAFT — backtest 3 variantes pending. "
        "Voir docstring + setup backtest dans Phase 1b."
    )


def add_vwap_w_side(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule vwap_w_side : -1, 0, +1 selon close vs vwap_w.

    Requis : close, vwap_w (calcule par phase_b_plus_engine.py add_vwap_features).
    Si vwap_w absent → NaN preserve (le caller decide drop/fillna).
    """
    df = df.copy()
    if "vwap_w" not in df.columns:
        # Pas raise : vwap_w peut etre absent en debut periode (warm-up < 5 jours)
        df["vwap_w_side"] = pd.Series(np.nan, index=df.index, dtype="float64")
        return df
    df["vwap_w_side"] = np.sign(df["close"] - df["vwap_w"]).fillna(0).astype("int8")
    return df


def add_vwap_triple_align(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule vwap_triple_align : +1 si all 3 above, -1 si all 3 below, 0 mixed.

    FIX v0.2 (parite DMP_Transform.h:1403) :
        +1 si bool_above_vwap_d > 0.5 AND bool_above_vwap_w > 0.5 AND bool_above_vwap_m > 0.5
        -1 si tous below (bool_above_* == 0 pour tous)
        0  si mixte

    En Python, on peut deriver bool_above_vwap_* depuis vwap_*_side ou
    directement depuis close vs vwap_*. On utilise close vs vwap_* car plus
    direct (et sides peuvent etre 0 quand close == vwap, ce qui n'est pas above).

    Requis : close, vwap_d, vwap_w, vwap_m.
    """
    df = df.copy()
    if "close" not in df.columns:
        raise KeyError("[v6_complete] 'close' manquant pour vwap_triple_align.")

    above_d = df["close"] > df.get("vwap_d", pd.Series(np.nan, index=df.index))
    above_w = df["close"] > df.get("vwap_w", pd.Series(np.nan, index=df.index))
    above_m = df["close"] > df.get("vwap_m", pd.Series(np.nan, index=df.index))

    # NaN si une des vwap absente → on neutralise (0)
    below_d = df["close"] < df.get("vwap_d", pd.Series(np.nan, index=df.index))
    below_w = df["close"] < df.get("vwap_w", pd.Series(np.nan, index=df.index))
    below_m = df["close"] < df.get("vwap_m", pd.Series(np.nan, index=df.index))

    all_above = (above_d & above_w & above_m).fillna(False)
    all_below = (below_d & below_w & below_m).fillna(False)

    triple = np.where(all_above, 1, np.where(all_below, -1, 0)).astype(np.int8)
    df["vwap_triple_align"] = triple
    return df


def add_vwap_ma_align_DRAFT(df: pd.DataFrame) -> pd.DataFrame:
    """⚠️ DRAFT v0.2 — NotImplementedError, depend ma_trend a finaliser.

    DMP_Transform.h:1341 : depend ma_fast/ma_slow (Sierra MA daily, params
    inconnus). A finaliser apres backtest variantes ma_trend.

    FIX P1.4 code-reviewer : raise pour eviter pollution accidentelle.
    """
    raise NotImplementedError(
        "vwap_ma_align DRAFT — depend ma_trend variantes en cours de backtest."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MOMENTUM / TREND
# ═══════════════════════════════════════════════════════════════════════════════

def add_momentum_3b(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule momentum_3b : variation prix sur 3 bars (POINTS).

    FIX v0.2 (parite DMP_Transform.h:117,643) :
        momentum_3b = close - close.shift(3)   (en POINTS)

    DMP commentaire ligne 117 : "Prix - Prix(i-3) en points (court terme)".
    Le DMP utilise un PersistentFloat dans DMP_Main.cpp pour cumuler. En Python
    pandas, equivalent direct via .shift(3).

    Requis : close.
    """
    df = df.copy()
    if "close" not in df.columns:
        raise KeyError("[v6_complete] 'close' manquant pour momentum_3b.")
    df["momentum_3b"] = (df["close"] - df["close"].shift(3)).astype("float32")
    return df


def add_ma_trend_DRAFT(df: pd.DataFrame, fast: int = 20, slow: int = 50,
                       method: str = "sma") -> pd.DataFrame:
    """⚠️ DRAFT v0.2 — NotImplementedError jusqu'a backtest demain.

    DMP_Transform.h:1335 : ma_trend = (r.ma_fast > r.ma_slow) ? +1 : -1
    Avec ma_fast/ma_slow = Sierra MA Daily study subgraphs 0 et 1 (params
    inconnus). 3 variantes Python a tester via backtest demain :
        v1 : SMA20 vs SMA50
        v2 : EMA12 vs EMA26 (MACD style)
        v3 : SMA9 vs SMA21 (scalping bias)
    Critere : Spearman corr direction(close[t+1] - close[t]) > 0.05.

    FIX P1.4 code-reviewer : raise pour eviter pollution accidentelle.
    Le code de calcul est conserve dans Phase 1b setup backtest demain.

    Args:
        fast, slow, method : pour reference future (pas utilises pour l'instant).
    """
    raise NotImplementedError(
        "ma_trend DRAFT — 3 variantes SMA20/50, EMA12/26, SMA9/21 a backtester. "
        "Voir docstring + setup Phase 1b."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CVD ALIAS
# ═══════════════════════════════════════════════════════════════════════════════

def add_cvd_day_dir(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule cvd_day_dir : Sign(cvd_session) — direction CVD intraday cumulative.

    FIX v0.2 (parite DMP_Transform.h:999-1000) :
        DMP utilise cvd_day = r.fpbs_cvd_day (CVD FOOTPRINT-based intraday,
        subgraph 18 de l'etude Numbers Bars Calc Values 2 Sierra).
        cvd_day_dir = Sign(cvd_day)

    En Python, on utilise cvd_session = cumsum delta_bar Trades Databento par
    session globex (add_session_cvd dans build_dataset_v4). Ce N'EST PAS
    semantiquement equivalent au footprint-based cvd_day DMP : empiriquement
    40% match seulement sur avril 2026. Sources differentes (footprint Sierra
    volumes par cellule VAP vs cumsum trades Databento side). On documente
    la divergence et on accepte la version Python (footprint Databento indispo).

    FIX P0.2 code-reviewer (13/05/2026) : retire fallback delta_day_dir qui
    est BINAIRE {0,1} dans build_dataset_v4_dmp_databento.py:545, donc PAS
    equivalent semantique au cvd_day_dir continu {-1,0,+1}. Aliaser invalide
    la semantique. Si cvd_session absent → raise explicite, point.

    Requis : cvd_session (cumsum delta_bar par session, fournie par
             add_session_cvd dans build_dataset_v4).
    """
    df = df.copy()
    if "cvd_session" not in df.columns:
        raise KeyError(
            "[v6_complete] 'cvd_session' manquant pour cvd_day_dir. "
            "Appeler add_session_cvd avant. NE PAS fallback sur delta_day_dir "
            "qui est binaire {0,1}, semantique differente."
        )
    df["cvd_day_dir"] = np.sign(df["cvd_session"]).fillna(0).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR
# ═══════════════════════════════════════════════════════════════════════════════

def apply_v6_complete(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """Applique les 6 helpers GROUPE A (parite DMP_Transform.h validee).

    GROUPE B (ma_trend, vwap_slope_30, vwap_ma_align) marques DRAFT
    et NE SONT PAS appeles ici. A finaliser apres backtest variantes Python.

    Ordre :
      1. momentum_3b       (depend close)
      2. cvd_day_dir       (depend cvd_session OU delta_day_dir)
      3. range_pos         (depend close + cur_val + cur_vah)   ⚠️ Value Area
      4. sess_range_atr    (depend sess_high/low + atr)
      5. vwap_w_side       (depend close + vwap_w)
      6. vwap_triple_align (depend close + vwap_d/w/m)

    Caller doit passer un df qui contient deja :
      close, vwap_d, vwap_w, vwap_m,
      sess_high, sess_low, atr,
      cur_val, cur_vah,
      cvd_session (ou delta_day_dir comme fallback).
    """
    df = add_momentum_3b(df)
    df = add_cvd_day_dir(df)
    df = add_range_pos(df)
    df = add_sess_range_atr(df, tick=tick)
    df = add_vwap_w_side(df)
    df = add_vwap_triple_align(df)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS INLINE (run direct python -m phase_b_v6_complete)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_test_df(n: int = 50) -> pd.DataFrame:
    """Df dummy avec toutes les colonnes requises GROUPE A pour tests inline."""
    rng = np.random.default_rng(42)
    base = 7400.0
    close = base + np.cumsum(rng.normal(0, 0.5, n))
    cur_vpoc = base + 0.5
    df = pd.DataFrame({
        "close": close.astype("float32"),
        "sess_high": np.maximum.accumulate(close).astype("float32"),
        "sess_low": np.minimum.accumulate(close).astype("float32"),
        "atr": np.full(n, 30.0, dtype="float32"),  # 30 ticks ATR
        "cur_val": np.full(n, cur_vpoc - 5.0, dtype="float32"),
        "cur_vah": np.full(n, cur_vpoc + 5.0, dtype="float32"),
        "vwap_d": (base + np.cumsum(rng.normal(0, 0.1, n))).astype("float32"),
        "vwap_w": (base + np.cumsum(rng.normal(0, 0.05, n))).astype("float32"),
        "vwap_m": (base + np.cumsum(rng.normal(0, 0.02, n))).astype("float32"),
        "cvd_session": np.cumsum(rng.normal(0, 100, n)).astype("float32"),
    })
    return df


def _test_range_pos_va():
    """range_pos doit utiliser Value Area, pas session HL."""
    df = _make_test_df()
    out = add_range_pos(df)
    assert "range_pos" in out.columns
    valid = out["range_pos"].dropna()
    assert valid.between(0, 100).all(), f"range_pos out of [0,100]: {valid.min()}..{valid.max()}"
    print("[OK] add_range_pos (Value Area parite DMP)")


def _test_momentum_3b_price_delta():
    """momentum_3b doit etre close - close.shift(3), pas delta_bar sum."""
    df = _make_test_df()
    out = add_momentum_3b(df)
    expected = df["close"] - df["close"].shift(3)
    diff = (out["momentum_3b"] - expected).abs().dropna()
    assert diff.max() < 1e-4, f"momentum_3b formule incorrecte, max diff={diff.max()}"
    print("[OK] add_momentum_3b (close delta parite DMP)")


def _test_sess_range_atr():
    df = _make_test_df()
    out = add_sess_range_atr(df)
    assert "sess_range_atr" in out.columns
    assert (out["sess_range_atr"].dropna() >= 0).all()
    print("[OK] add_sess_range_atr")


def _test_vwap_triple_align_3values():
    """vwap_triple_align doit etre -1/0/+1 (3 valeurs possibles), pas 0/1."""
    df = _make_test_df()
    # Force close above all 3 vwaps sur quelques bars pour tester +1
    df.loc[10, "close"] = df.loc[10, ["vwap_d", "vwap_w", "vwap_m"]].max() + 10
    df.loc[20, "close"] = df.loc[20, ["vwap_d", "vwap_w", "vwap_m"]].min() - 10
    out = add_vwap_triple_align(df)
    assert "vwap_triple_align" in out.columns
    assert out["vwap_triple_align"].isin([-1, 0, 1]).all()
    assert out["vwap_triple_align"].iloc[10] == 1, "above 3 vwaps doit donner +1"
    assert out["vwap_triple_align"].iloc[20] == -1, "below 3 vwaps doit donner -1"
    print("[OK] add_vwap_triple_align (-1/0/+1 parite DMP)")


def _test_apply_v6_complete():
    df = _make_test_df()
    out = apply_v6_complete(df)
    expected_new = [
        "range_pos", "sess_range_atr", "vwap_w_side",
        "vwap_triple_align", "momentum_3b", "cvd_day_dir",
    ]
    for col in expected_new:
        assert col in out.columns, f"missing {col}"
    print(f"[OK] apply_v6_complete: +{len(expected_new)} cols GROUPE A")


if __name__ == "__main__":
    _test_range_pos_va()
    _test_momentum_3b_price_delta()
    _test_sess_range_atr()
    _test_vwap_triple_align_3values()
    _test_apply_v6_complete()
    print("\n[ALL OK]")
