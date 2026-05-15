"""Test empirique R2 seed warmup OpenCashPrice1030 depuis V4.

Couvre :
  1. Cold start avec V4 parquet today bars + open_cash captured -> seed OK
  2. Cold start avec V4 parquet sans today's bars -> seed=None (no crash)
  3. Cold start sans V4 parquet -> no crash, state empty
  4. Bug R2 fix : warmup_from_v4=True n'avale plus AttributeError silent
"""
import sys
from pathlib import Path
import tempfile
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from live_enricher_state import initialize_state, _state_path, LiveEnricherState


def _clear_snapshot(sym: str):
    p = _state_path(sym)
    if p.exists():
        p.unlink()


def test_1_seed_from_v4_today():
    """Cold start + V4 parquet today bars open_cash 4500 / price_1030 4520 -> seed."""
    sym = "TEST_R2_1.c.0"
    _clear_snapshot(sym)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = Path(f.name)
    today_et = pd.Timestamp("2026-05-15").date()
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-15 13:30", periods=10, freq="1min", tz="UTC"),
        "date_et": [today_et] * 10,
        "mins_et": list(range(570, 580)),
        "close": [4499.0, 4500.0, 4500.5, 4500.75, 4501.0, 4520.0, 4521.0, 4521.5, 4522.0, 4522.5],
        "open_cash": [np.nan, 4500.0, 4500.0, 4500.0, 4500.0, 4500.0, 4500.0, 4500.0, 4500.0, 4500.0],
        "price_1030": [np.nan, np.nan, np.nan, np.nan, np.nan, 4520.0, 4520.0, 4520.0, 4520.0, 4520.0],
    })
    df.to_parquet(tmp_path)

    state = initialize_state(sym, warmup_from_v4=True, v4_parquet_path=tmp_path)
    assert state.n_bars_processed == 10, f"n_bars_processed={state.n_bars_processed}"

    s = state.engine_states.get("open_cash_price1030")
    assert s is not None, "OpenCashPrice1030State should be seeded"
    assert s.cached_open_cash == 4500.0, f"cached_open_cash={s.cached_open_cash}"
    assert s.cached_price_1030 == 4520.0, f"cached_price_1030={s.cached_price_1030}"
    assert s.current_date_et == today_et
    tmp_path.unlink()
    print("[OK] test_1_seed_from_v4_today : open_cash=4500 price_1030=4520")


def test_2_no_today_bars_no_seed():
    """V4 parquet sans bars today -> no seed mais bars chargees."""
    sym = "TEST_R2_2.c.0"
    _clear_snapshot(sym)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = Path(f.name)
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-13 13:30", periods=5, freq="1min", tz="UTC"),
        "date_et": [pd.Timestamp("2026-05-13").date()] * 5,
        "mins_et": list(range(570, 575)),
        "close": [4498.0, 4499.0, 4500.0, 4501.0, 4502.0],
        # PAS de open_cash/price_1030 captures
    })
    df.to_parquet(tmp_path)

    state = initialize_state(sym, warmup_from_v4=True, v4_parquet_path=tmp_path)
    assert state.n_bars_processed == 5
    s = state.engine_states.get("open_cash_price1030")
    assert s is None, f"no seed expected, got {s}"
    tmp_path.unlink()
    print("[OK] test_2_no_today_bars_no_seed : no engine_state seeded")


def test_3_no_parquet_no_crash():
    """V4 parquet absent -> state vide, pas de crash."""
    sym = "TEST_R2_3.c.0"
    _clear_snapshot(sym)
    state = initialize_state(
        sym, warmup_from_v4=True, v4_parquet_path=Path("/nonexistent/path.parquet")
    )
    assert state.symbol == sym
    assert state.n_bars_processed == 0
    print("[OK] test_3_no_parquet_no_crash")


def test_4_bug_fix_silent_attributeerror():
    """Avant fix : state.bars_df=df levait AttributeError silent (except: pass).

    Apres fix : bars_df populated via _bars_deque + warmup emit log_catalog
    si exception (anti-Pattern V1).
    """
    sym = "TEST_R2_4.c.0"
    _clear_snapshot(sym)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = Path(f.name)
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-15 00:00", periods=100, freq="1min", tz="UTC"),
        "date_et": [pd.Timestamp("2026-05-15").date()] * 100,
        "mins_et": list(range(100)),
        "close": list(range(4500, 4600)),
    })
    df.to_parquet(tmp_path)

    state = initialize_state(sym, warmup_from_v4=True, v4_parquet_path=tmp_path)
    # Verifie bars_df materializable + populee
    assert state.n_bars_processed == 100, f"got {state.n_bars_processed}"
    bars_df = state.bars_df
    assert len(bars_df) == 100, f"bars_df len={len(bars_df)}"
    assert "close" in bars_df.columns
    tmp_path.unlink()
    print("[OK] test_4_bug_fix_silent_attributeerror : bars_df pop=100 (avant fix=0)")


def test_5_multi_days_seed_today_only():
    """S1 code-reviewer : 60j de bars, last day a 5 bars seulement.
    Seed doit prendre last day, pas les autres.
    """
    sym = "TEST_R2_5.c.0"
    _clear_snapshot(sym)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = Path(f.name)

    # 59 jours x 5 bars J-N..J-1 + 5 bars J0
    rows = []
    for d in range(59):
        date_d = pd.Timestamp("2026-05-15") - pd.Timedelta(days=59 - d)
        for m in range(5):
            rows.append({
                "ts_event": date_d + pd.Timedelta(minutes=570 + m),
                "date_et": date_d.date(),
                "mins_et": 570 + m,
                "close": 4000.0 + d * 10 + m,
                "open_cash": 4000.0 + d * 10,
                "price_1030": 4020.0 + d * 10,
            })
    # J0 = 15/05 5 bars dont open_cash=5000 / price_1030=5020 specifiques
    for m in range(5):
        rows.append({
            "ts_event": pd.Timestamp("2026-05-15") + pd.Timedelta(minutes=570 + m),
            "date_et": pd.Timestamp("2026-05-15").date(),
            "mins_et": 570 + m,
            "close": 5000.0 + m,
            "open_cash": 5000.0,
            "price_1030": 5020.0,
        })
    df = pd.DataFrame(rows)
    df.to_parquet(tmp_path)

    state = initialize_state(sym, warmup_from_v4=True, v4_parquet_path=tmp_path)
    s = state.engine_states.get("open_cash_price1030")
    assert s is not None, "seed missing"
    assert s.cached_open_cash == 5000.0, f"expected 5000, got {s.cached_open_cash}"
    assert s.cached_price_1030 == 5020.0, f"expected 5020, got {s.cached_price_1030}"
    assert s.current_date_et == pd.Timestamp("2026-05-15").date()
    tmp_path.unlink()
    print("[OK] test_5_multi_days_seed_today_only : 60j buffer + seed J0 OK")


def test_6_dtype_timestamp_vs_date():
    """S2 code-reviewer : date_et persistee comme datetime64 vs date.
    parquet roundtrip peut changer dtype. Verifier idempotence seed.
    """
    sym = "TEST_R2_6.c.0"
    _clear_snapshot(sym)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = Path(f.name)
    # date_et stocke comme pd.Timestamp (datetime64[ns]) au lieu de date
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-15 13:30", periods=3, freq="1min", tz="UTC"),
        "date_et": pd.to_datetime(["2026-05-15"] * 3),  # datetime64[ns]
        "mins_et": [570, 571, 572],
        "close": [4500.0, 4500.5, 4501.0],
        "open_cash": [4500.0, 4500.0, 4500.0],
        "price_1030": [4520.0, 4520.0, 4520.0],
    })
    df.to_parquet(tmp_path)

    state = initialize_state(sym, warmup_from_v4=True, v4_parquet_path=tmp_path)
    s = state.engine_states.get("open_cash_price1030")
    assert s is not None, "seed missing on Timestamp dtype"
    assert s.cached_open_cash == 4500.0
    assert s.cached_price_1030 == 4520.0
    # dtype current_date_et doit etre une Timestamp ou date - les 2 OK tant que ==
    print(f"[OK] test_6_dtype_timestamp_vs_date : dtype={type(s.current_date_et).__name__}")
    tmp_path.unlink()


if __name__ == "__main__":
    test_1_seed_from_v4_today()
    test_2_no_today_bars_no_seed()
    test_3_no_parquet_no_crash()
    test_4_bug_fix_silent_attributeerror()
    test_5_multi_days_seed_today_only()
    test_6_dtype_timestamp_vs_date()
    print("\n=== TOUS LES 6 TESTS R2 PASS ===")
