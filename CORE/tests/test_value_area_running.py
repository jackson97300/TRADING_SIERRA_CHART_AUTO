"""
test_value_area_running.py — Tests Phase C VPOC/VA running cumsum.

Tests critiques :
  1. Invariants (val <= vpoc <= vah pour toutes les bars valides)
  2. No-lookahead : cur_vpoc[i] inchange si on tronque trades > bar_i.end_ts
  3. Idempotence : 2 runs successifs identiques
  4. Session reset : nouvelle session reinitialise le cumul VAP
  5. Convergence : last bar de session = VP calcule sur tous trades de la session
  6. Cas degeneres : empty trades, empty df, single trade

Lancer : pytest CORE/tests/test_value_area_running.py -v

Auteur : Phase C V4 (2026-04-27)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Permet import depuis CORE/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from value_area_running import (
    apply_value_area_running,
    check_va_invariants,
    _compute_va_from_arrays,
)
from phase_b_helpers import add_session_metadata, compute_volume_profile_dict


DBN_ROOT = Path(__file__).resolve().parents[2] / "DATA" / "databento" / "GLBX.MDP3"


def _load_real_day(symbol: str, target_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Charge OHLCV 1m + Trades pour 1 jour calendar UTC."""
    import duckdb
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC';")

    ohlcv_pattern = (DBN_ROOT / "ohlcv-1m" / f"symbol={symbol}.c.0" / "**" / "*.parquet").as_posix()
    df = con.execute(f"""
        SELECT ts_event::TIMESTAMP AS ts_event, open, high, low, close, volume
        FROM read_parquet('{ohlcv_pattern}', hive_partitioning=true)
        WHERE ts_event >= TIMESTAMP '{target_date}'
          AND ts_event <  TIMESTAMP '{target_date + timedelta(days=1)}'
        ORDER BY ts_event
    """).fetchdf()

    trades_pattern = (DBN_ROOT / "trades" / f"symbol={symbol}.c.0" / "**" / "*.parquet").as_posix()
    trades = con.execute(f"""
        SELECT ts_event::TIMESTAMP AS ts_event, price, size
        FROM read_parquet('{trades_pattern}', hive_partitioning=true)
        WHERE ts_event >= TIMESTAMP '{target_date}'
          AND ts_event <  TIMESTAMP '{target_date + timedelta(days=1)}'
          AND size > 0
        ORDER BY ts_event
    """).fetchdf()
    con.close()

    df["ts_event"] = pd.to_datetime(df["ts_event"]).dt.tz_localize("UTC")
    trades["ts_event"] = pd.to_datetime(trades["ts_event"]).dt.tz_localize("UTC")
    df = add_session_metadata(df)
    return df, trades


# ──────────────────────────────────────────────────────────────────────────
# 1. Tests unitaires _compute_va_from_arrays
# ──────────────────────────────────────────────────────────────────────────

def test_compute_va_matches_legacy_steidlmayer():
    """L'algo VA Phase C reproduit exactement l'algo de compute_volume_profile_dict."""
    vbp = {100.0: 50, 100.25: 80, 100.5: 100, 100.75: 70, 101.0: 30}
    legacy = compute_volume_profile_dict(vbp, value_area_pct=70.0)

    prices = np.array(sorted(vbp.keys()), dtype=np.float64)
    vols = np.array([vbp[p] for p in prices], dtype=np.float64)
    vpoc, vah, val = _compute_va_from_arrays(vols, prices, target_pct=70.0)

    assert vpoc == legacy["vpoc"], f"VPOC: {vpoc} vs legacy {legacy['vpoc']}"
    assert vah == legacy["vah"], f"VAH: {vah} vs legacy {legacy['vah']}"
    assert val == legacy["val"], f"VAL: {val} vs legacy {legacy['val']}"


def test_compute_va_empty_returns_nan():
    """Empty input -> all NaN."""
    vpoc, vah, val = _compute_va_from_arrays(
        np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    )
    assert np.isnan(vpoc) and np.isnan(vah) and np.isnan(val)


def test_compute_va_single_price():
    """Single price -> vpoc = vah = val = that price."""
    prices = np.array([100.0], dtype=np.float64)
    vols = np.array([50.0], dtype=np.float64)
    vpoc, vah, val = _compute_va_from_arrays(vols, prices)
    assert vpoc == vah == val == 100.0


# ──────────────────────────────────────────────────────────────────────────
# 2. Tests apply_value_area_running sur donnees reelles
# ──────────────────────────────────────────────────────────────────────────

def test_invariants_on_real_day():
    """Sur 1 jour ES reel, val <= vpoc <= vah pour toutes les bars valides."""
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out = apply_value_area_running(df, trades)
    inv = check_va_invariants(out)
    assert inv["ok"], f"Invariants violates: {inv}"


def test_no_lookahead_on_real_day():
    """
    Test critique : cur_vpoc[bar_i] doit etre identique avec ou sans trades
    futurs > bar_i.end_ts dans trades_df.
    """
    df, trades = _load_real_day("ES", date(2026, 4, 24))

    # Run complet
    full_out = apply_value_area_running(df.copy(), trades.copy())

    # Pour 3 bars test (early, mid, late session), tronquer trades
    test_bars = [100, 500, 1000]
    for bar_i in test_bars:
        if bar_i >= len(df):
            continue
        bar_end_ts = df.iloc[bar_i]["ts_event"] + pd.Timedelta(minutes=1)
        trades_truncated = trades[trades["ts_event"] < bar_end_ts].copy()

        # Re-run sur df tronque a bar_i+1 + trades tronques
        df_truncated = df.iloc[:bar_i + 1].copy()
        truncated_out = apply_value_area_running(df_truncated, trades_truncated)

        full_vpoc = full_out.iloc[bar_i]["cur_vpoc"]
        trunc_vpoc = truncated_out.iloc[bar_i]["cur_vpoc"]

        if pd.isna(full_vpoc) and pd.isna(trunc_vpoc):
            continue  # both NaN ok
        assert full_vpoc == trunc_vpoc, (
            f"LOOKAHEAD detecte bar {bar_i}: full={full_vpoc} vs truncated={trunc_vpoc}"
        )


def test_idempotence():
    """Apply 2x sur meme input -> output identique."""
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out1 = apply_value_area_running(df.copy(), trades.copy())
    out2 = apply_value_area_running(df.copy(), trades.copy())

    pd.testing.assert_series_equal(out1["cur_vpoc"], out2["cur_vpoc"])
    pd.testing.assert_series_equal(out1["cur_vah"], out2["cur_vah"])
    pd.testing.assert_series_equal(out1["cur_val"], out2["cur_val"])


def test_idempotence_after_double_apply():
    """
    Apply Phase C sur df qui contient deja cur_vpoc (re-run case) -> ne plante pas
    et produit meme resultat.
    """
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out1 = apply_value_area_running(df.copy(), trades.copy())
    out2 = apply_value_area_running(out1.copy(), trades.copy())

    pd.testing.assert_series_equal(out1["cur_vpoc"], out2["cur_vpoc"])


def test_session_reset_between_days():
    """Sur 2 jours, le cumul VAP doit reinitialiser entre sessions."""
    df_day1, trades_day1 = _load_real_day("ES", date(2026, 4, 23))
    df_day2, trades_day2 = _load_real_day("ES", date(2026, 4, 24))

    df = pd.concat([df_day1, df_day2], ignore_index=True)
    trades = pd.concat([trades_day1, trades_day2], ignore_index=True)
    out = apply_value_area_running(df, trades)

    # Au moins 2 sessions distinctes detectees
    assert out["session_date_trading"].nunique() >= 2

    # Premier bar de la 2eme session : VP doit etre construit a partir de RIEN
    # = 1 seul trade ou tres peu -> VAH/VAL proche du POC (small range)
    sess_dates = sorted(out["session_date_trading"].unique())
    sess2_first_idx = out[out["session_date_trading"] == sess_dates[1]].index[0]
    sess2_first = out.iloc[sess2_first_idx]

    # Range VAH-VAL au premier bar < 50 ticks (typique en debut session)
    if not pd.isna(sess2_first["cur_vah"]):
        range_first = sess2_first["cur_vah"] - sess2_first["cur_val"]
        assert range_first < 50.0, f"Premiere bar session 2 : range VA={range_first} trop large"


def test_first_valid_bar_has_running_vpoc():
    """La 1ere bar valide doit avoir cur_vpoc defini (au moins 1 trade)."""
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out = apply_value_area_running(df, trades)
    first_valid = out["cur_vpoc"].first_valid_index()
    assert first_valid is not None, "Aucune bar avec cur_vpoc valide"
    assert first_valid <= 5, f"Premiere bar valide trop tard : idx={first_valid}"


def test_running_evolution():
    """cur_vpoc doit avoir nunique > 1 (sinon = constant = lookahead)."""
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out = apply_value_area_running(df, trades)
    n_unique = out["cur_vpoc"].nunique()
    assert n_unique > 1, f"cur_vpoc constant intraday (nunique={n_unique}) = lookahead/bug"


def test_inside_value_area_consistency():
    """inside_value_area[i] = 1 ssi cur_val[i] <= close[i] <= cur_vah[i]."""
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out = apply_value_area_running(df, trades)
    valid = out.dropna(subset=["cur_vah", "cur_val"])
    expected = ((valid["close"] >= valid["cur_val"]) & (valid["close"] <= valid["cur_vah"])).astype("int8")
    actual = valid["inside_value_area"].astype("int8")
    pd.testing.assert_series_equal(expected, actual, check_names=False)


def test_dist_pct_signs():
    """dist_cur_*_pct = (level - close) / close * 100 : signe coherent.

    FIX BUG D 15/05/2026 : convention unique (level - close) compliant DMP C++
    (positif = niveau au-dessus du close).
    """
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    out = apply_value_area_running(df, trades)
    valid = out.dropna(subset=["cur_vpoc"])
    # Convention (level - close) : si vpoc > close -> dist_pct > 0
    above = valid[valid["cur_vpoc"] > valid["close"]]
    assert (above["dist_cur_vpoc_pct"] > 0).all(), "Sign inconsistent dist_cur_vpoc_pct"


# ──────────────────────────────────────────────────────────────────────────
# 3. Tests cas degeneres
# ──────────────────────────────────────────────────────────────────────────

def test_empty_trades_raises():
    """trades_df vide -> ValueError fail-loud (pas silent fail)."""
    df, _ = _load_real_day("ES", date(2026, 4, 24))
    with pytest.raises(ValueError, match="trades_df vide"):
        apply_value_area_running(df, pd.DataFrame())


def test_none_trades_raises():
    """trades_df=None -> ValueError fail-loud."""
    df, _ = _load_real_day("ES", date(2026, 4, 24))
    with pytest.raises(ValueError, match="trades_df vide"):
        apply_value_area_running(df, None)


def test_missing_required_cols_raises():
    """df sans session_date_trading -> KeyError fail-loud."""
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    df_bad = df.drop(columns=["session_date_trading"])
    with pytest.raises(KeyError, match="session_date_trading"):
        apply_value_area_running(df_bad, trades)


def test_index_non_trivial_resets_defensively():
    """
    FIX MAJEUR 1 (code-reviewer 27/04) : si l'appelant passe un df avec index
    non-RangeIndex (ex: filtrage prealable), apply_value_area_running doit
    reset_index defensivement et ne PAS produire un bug silencieux.
    """
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    # Simuler filtrage prealable qui casse l'index (skip first 10 bars)
    df_skewed = df.iloc[10:].copy()
    # df_skewed.index = [10, 11, 12, ...] non-RangeIndex
    assert not df_skewed.index.equals(pd.RangeIndex(len(df_skewed)))
    out = apply_value_area_running(df_skewed, trades)
    # Doit produire un output valide (pas de crash, pas de NaN systematique)
    assert out["cur_vpoc"].notna().sum() > len(out) * 0.5
    inv = check_va_invariants(out)
    assert inv["ok"]


def test_boundary_trade_assigned_to_starting_bar():
    """
    FIX MAJEUR 2 (code-reviewer 27/04) : test explicite de la convention
    boundary [bar_start, bar_start + 60s).

    Un trade au timestamp EXACT d'une bar_start est attribue a CETTE bar
    (pas a la precedente). Verifie via searchsorted(side='right') - 1.
    """
    df, trades = _load_real_day("ES", date(2026, 4, 24))

    # Identifier 1 bar mid-session
    bar_idx = 500
    bar_start = df.iloc[bar_idx]["ts_event"]

    # Construire un trades_df synthetique : 1 trade au boundary EXACT
    synthetic_trades = pd.DataFrame({
        "ts_event": [bar_start, bar_start + pd.Timedelta(seconds=30)],
        "price": [7150.00, 7151.25],
        "size": [100, 200],
    })

    # df reduit : juste 2 bars (bar_idx et bar_idx+1)
    df_small = df.iloc[bar_idx:bar_idx + 2].copy().reset_index(drop=True)
    out = apply_value_area_running(df_small, synthetic_trades)

    # Convention : trade a bar_start exact -> attribue a bar 0 (=bar_idx)
    # Donc cur_vpoc[0] doit voir les 2 trades (POC = 7151.25 car size=200 > 100)
    assert out.iloc[0]["cur_vpoc"] == 7151.25, (
        f"Convention boundary cassee : cur_vpoc[0] = {out.iloc[0]['cur_vpoc']}, "
        f"attendu 7151.25 (trade au boundary doit etre dans bar 0)"
    )
    assert out.iloc[0]["cur_va_n_buckets"] == 2, (
        f"n_buckets = {out.iloc[0]['cur_va_n_buckets']}, attendu 2 (2 prix uniques)"
    )


# ──────────────────────────────────────────────────────────────────────────
# 4. Performance benchmark (skip si trop lent)
# ──────────────────────────────────────────────────────────────────────────

def test_perf_under_60s_per_day():
    """1 jour ES doit s'executer en moins de 60s."""
    import time
    df, trades = _load_real_day("ES", date(2026, 4, 24))
    t0 = time.perf_counter()
    apply_value_area_running(df, trades)
    elapsed = time.perf_counter() - t0
    assert elapsed < 60.0, f"Trop lent : {elapsed:.1f}s pour 1 jour (target < 60s)"
    print(f"  Perf: {elapsed:.2f}s pour 1 jour ES")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
