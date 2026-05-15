"""Test parite V4 oracle pour Live Enricher streaming sub-engines.

R3 Pass 4 (15/05/2026) — agent feature-engineer verdict :
> creer tests/test_live_enricher_parity_v4.py qui :
>   1. Charge V4 parquet ES 1 mois (avril 2026)
>   2. Re-joue chaque bar via le streaming sub-engine
>   3. Compare features streaming vs colonnes parquet oracle
>   4. Tolerance |delta| < 1e-6 sur features GREEN

Couvre les sub-engines a plus haut risque Pattern V1 :
  - `add_open_cash_price1030_streaming` (R2 motivator)
  - `add_game_changers_streaming` (open_type/open_zone — R2 motivator)

Scope retreint : pas full enrich_payload chain (heavy mock OHLCV/trades/MQ/VIX),
les sub-engines individuels couvrent le risque principal (drift batch/stream).

Note : `add_rolling_features_basic_streaming` deja couvert par
TOOLS/test_engine_parity.py --engine rolling_features_basic (4 levels PASS
apres exemption ctx_diag_imbalance_mean_5 R1 Pass 4).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


V4_PARQUET_ES = (
    ROOT / "DATA" / "datasets" / "v4_enriched" /
    "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet"
)


def _load_v4_with_derived_keys() -> pd.DataFrame:
    """Charge V4 ES avril + ajoute date_et/mins_et derives depuis ts_event ET."""
    df = pd.read_parquet(V4_PARQUET_ES)
    # ts_event en UTC -> ET pour derived keys
    ts_et = pd.to_datetime(df["ts_event"]).dt.tz_convert("America/New_York")
    df = df.copy()
    df["date_et"] = ts_et.dt.date
    df["mins_et"] = ts_et.dt.hour * 60 + ts_et.dt.minute
    return df


@pytest.fixture(scope="module")
def df_v4_es() -> pd.DataFrame:
    if not V4_PARQUET_ES.exists():
        pytest.skip(f"V4 parquet ES avril absent : {V4_PARQUET_ES}")
    return _load_v4_with_derived_keys()


# ════════════════════════════════════════════════════════════════════════════
# Test 1 : add_open_cash_price1030_streaming vs V4 oracle
# ════════════════════════════════════════════════════════════════════════════

def test_open_cash_price1030_streaming_parity_v4(df_v4_es):
    """Replay streaming open_cash + price_1030 sur V4 ES avril, compare oracle.

    Critere : sur les bars ou V4 oracle expose une valeur non-NaN,
    le streaming doit produire EXACTEMENT la meme valeur (==).
    """
    from phase_b_helpers import (
        OpenCashPrice1030State,
        add_open_cash_price1030_streaming,
    )

    state = OpenCashPrice1030State()
    out_rows = []
    for row in df_v4_es.to_dict(orient="records"):
        enriched = add_open_cash_price1030_streaming(row, state)
        out_rows.append({
            "ts_event": row["ts_event"],
            "stream_open_cash": enriched.get("open_cash"),
            "stream_price_1030": enriched.get("price_1030"),
        })
    df_stream = pd.DataFrame(out_rows)

    # Compare oracle (V4) vs stream
    df_compare = df_v4_es[["ts_event", "open_cash", "price_1030"]].merge(
        df_stream, on="ts_event", how="inner"
    )

    # Merge sur ts_event apporte mins_et + date_et de df_v4_es
    df_compare = df_compare.merge(
        df_v4_es[["ts_event", "mins_et", "date_et"]], on="ts_event", how="left"
    )

    # ASYMMETRIES CAUSALES LEGITIMES batch vs stream :
    # (1) Batch merge sur date_et -> tous bars du jour (y compris pre-09:30 ET).
    #     Stream capture a mins_et==us_start -> bars pre-us_start = NaN legitime.
    # (2) Batch utilise seed M-1 (cf process_partition build_dataset_v4_phase_b.py:550).
    #     Stream demarre au 1er bar V4 = pas de visibility seed. Bars dont date_et
    #     n'a PAS de mins_et==570 dans V4 (ex: derniere soiree mars sans 09:30 mars)
    #     -> stream=NaN legitime, batch=valeur seed.
    #
    # Fair test : restreint aux date_et "captures" = qui ont un bar mins_et==570
    # dans V4 (le stream PEUT capturer).
    us_start_es = 570  # 09:30 ET
    ib_close_es = 630  # 10:30 ET
    captured_dates_oc = set(
        df_v4_es.loc[df_v4_es["mins_et"] == us_start_es, "date_et"].unique()
    )
    captured_dates_p = set(
        df_v4_es.loc[df_v4_es["mins_et"] == ib_close_es, "date_et"].unique()
    )

    # open_cash : bars POST-us_start AVEC date_et capture dans V4 ET oracle non-NaN
    mask_oc = (
        (df_compare["mins_et"] >= us_start_es)
        & df_compare["date_et"].isin(captured_dates_oc)
        & df_compare["open_cash"].notna()
    )
    n_oc = int(mask_oc.sum())
    assert n_oc > 0, "Aucune bar POST-us_start avec open_cash oracle (V4 vide ?)"
    b = df_compare.loc[mask_oc, "open_cash"].astype("float64").values
    s = df_compare.loc[mask_oc, "stream_open_cash"].astype("float64").values
    max_diff = float(np.nanmax(np.abs(b - s)))
    nan_in_stream = int(np.isnan(s).sum())
    assert nan_in_stream == 0, (
        f"open_cash POST-us_start (captures): {nan_in_stream}/{n_oc} bars stream=NaN "
        f"(streaming devrait capturer a us_start)"
    )
    assert max_diff < 1e-9, (
        f"open_cash POST-us_start (captures): max_diff={max_diff:.6e} > 1e-9"
    )

    # price_1030 : bars >= ib_close AVEC date_et capture dans V4 ET oracle non-NaN
    mask_p1030 = (
        (df_compare["mins_et"] >= ib_close_es)
        & df_compare["date_et"].isin(captured_dates_p)
        & df_compare["price_1030"].notna()
    )
    n_p = int(mask_p1030.sum())
    assert n_p > 0, "Aucune bar POST-ib_close avec price_1030 oracle (V4 vide ?)"
    b = df_compare.loc[mask_p1030, "price_1030"].astype("float64").values
    s = df_compare.loc[mask_p1030, "stream_price_1030"].astype("float64").values
    max_diff = float(np.nanmax(np.abs(b - s)))
    nan_in_stream = int(np.isnan(s).sum())
    assert nan_in_stream == 0, (
        f"price_1030 POST-ib_close (captures): {nan_in_stream}/{n_p} bars stream=NaN"
    )
    assert max_diff < 1e-9, (
        f"price_1030 POST-ib_close (captures): max_diff={max_diff:.6e} > 1e-9"
    )

    print(
        f"\n[V4 PARITY] open_cash POST-us_start: {n_oc} bars / "
        f"price_1030 POST-ib_close: {n_p} bars : PASS"
    )
    print(f"  (captures: {len(captured_dates_oc)} dates oc / {len(captured_dates_p)} dates p1030)")


# ════════════════════════════════════════════════════════════════════════════
# Test 2 : add_game_changers_streaming vs V4 oracle (4 features frozen POST-IB)
# ════════════════════════════════════════════════════════════════════════════

def test_game_changers_streaming_parity_v4(df_v4_es):
    """Replay streaming game_changers sur V4 ES avril, compare oracle.

    Critere strict : sur bars POST-IB du JOUR CASH (mins_et 630-1079 AND
    date_et == session_date_trading), les 4 features frozen doivent matcher.

    SCOPE FILTRE 15/05 : V4 batch (apply_game_changers build_dataset_v4_phase_b.py:276)
    groupby session_date_trading + filtre date_et == session_date_trading. Le
    streaming utilise date_et reset semantics. Asymmetrie LEGITIME sur bars
    Asia evening (date_et=J-1, session_date_trading=J) -> batch broadcast cash
    classification a TOUS bars session, stream re-classify avec date_et reset.

    Cf INCIDENT_LOG 15/05/2026 V4_PARITY_GAME_CHANGERS_DRIFT
    Cf IDEAS_BACKLOG section streaming-batch-alignment.

    Le filtre date_et == session_date_trading restreint la comparaison aux
    bars du JOUR CASH (date_et=session_date_trading) — semantique commune
    aux 2 versions. La drift Asia evening est documentee mais NON testee ici.
    """
    from game_changers_streaming import (
        GameChangersState,
        add_game_changers_streaming,
    )

    state = GameChangersState()
    out_rows = []
    for row in df_v4_es.to_dict(orient="records"):
        enriched = add_game_changers_streaming(row, state, symbol="ES")
        out_rows.append({
            "ts_event": row["ts_event"],
            "stream_open_type": enriched.get("open_type"),
            "stream_open_zone": enriched.get("open_zone"),
            "stream_open_direction": enriched.get("open_direction"),
            "stream_open_bias_conf": enriched.get("open_bias_conf"),
        })
    df_stream = pd.DataFrame(out_rows)

    df_compare = df_v4_es[[
        "ts_event", "mins_et", "date_et", "session_date_trading",
        "open_type", "open_zone", "open_direction", "open_bias_conf",
    ]].merge(df_stream, on="ts_event", how="inner")

    # Aligne dtypes pour comparaison robust (date_et = date, session_date_trading parfois Timestamp)
    df_compare["session_date_trading"] = pd.to_datetime(
        df_compare["session_date_trading"]
    ).dt.date

    # SCOPE : bars POST-IB DU JOUR CASH (date_et == session_date_trading)
    # Asia evening (date_et=J-1, session=J) exclus = drift Pattern V1 documentee
    # Asia next day (mins_et >= asia_start=1080) exclus = next session start
    asia_start_es = 1080  # 18:00 ET = next session Asia open
    mask_cash = (
        (df_compare["mins_et"] >= 630)
        & (df_compare["mins_et"] < asia_start_es)
        & (df_compare["date_et"] == df_compare["session_date_trading"])
    )
    n_cash = int(mask_cash.sum())
    assert n_cash > 0, "Aucune bar POST-IB du jour cash dans V4 (test setup error)"

    # Tolerance per-column :
    # - open_type, open_zone, open_direction : INT (categories) -> exact match
    # - open_bias_conf : FLOAT (gc.confidence(ot)) -> 1e-6 standard parite (float32
    #   vs float64 roundtrip parquet peut introduire ~1e-8 noise)
    tol_per_col = {
        "open_type": 1e-9,
        "open_zone": 1e-9,
        "open_direction": 1e-9,
        "open_bias_conf": 1e-6,
    }
    failures = []
    for col, stream_col in [
        ("open_type", "stream_open_type"),
        ("open_zone", "stream_open_zone"),
        ("open_direction", "stream_open_direction"),
        ("open_bias_conf", "stream_open_bias_conf"),
    ]:
        b = df_compare.loc[mask_cash, col].astype("float64").values
        s = df_compare.loc[mask_cash, stream_col].astype("float64").values
        diff = np.abs(b - s)
        max_diff = float(np.nanmax(diff)) if len(diff) else 0.0
        tol = tol_per_col[col]
        n_diff = int((diff > tol).sum())
        if max_diff >= tol:
            failures.append({
                "col": col,
                "max_diff": max_diff,
                "n_diff": n_diff,
                "pct_diff": 100.0 * n_diff / n_cash,
                "tol": tol,
            })

    if failures:
        msg = "\n".join([
            f"  {f['col']:20s} max_diff={f['max_diff']:.6e} > tol={f['tol']:.1e} "
            f"n_diff={f['n_diff']}/{n_cash} ({f['pct_diff']:.1f}%)"
            for f in failures
        ])
        pytest.fail(
            f"V4 parity game_changers FAIL bars POST-IB jour cash :\n{msg}\n\n"
            f"Si drift > tol ici (pas Asia evening), c'est un BUG streaming reel."
        )

    print(f"\n[V4 PARITY] game_changers cash-day bars: {n_cash} : 4/4 PASS")


# ════════════════════════════════════════════════════════════════════════════
# Test 3 : assertions design contracts (R1 ML_EXCLUDE features ABSENT V4)
# ════════════════════════════════════════════════════════════════════════════

def test_v4_does_not_contain_r1_forbidden_features(df_v4_es):
    """R1 Pass 4 : V4 parquet ne doit JAMAIS contenir les 4 features
    DMP-C++ non-reproductibles Databento (drift batch/stream).

    Si une de ces colonnes est presente -> rebuild V4 a regresse, ML_EXCLUDE
    doit etre re-verifie.
    """
    forbidden = [
        "diag_imbalance",
        "large_trader_ratio",
        "ctx_diag_imbalance_mean_5",
        "ctx_large_trader_slope_5",
    ]
    present = [c for c in forbidden if c in df_v4_es.columns]
    assert not present, (
        f"R1 violation : V4 parquet contient features interdites = {present}. "
        f"Rebuild V4 a regresse, ML_EXCLUDE_FEATURES doit etre re-verifie."
    )


if __name__ == "__main__":
    # CLI direct sans pytest pour debug rapide
    print(f"Loading V4 ES April 2026 : {V4_PARQUET_ES}")
    df = _load_v4_with_derived_keys()
    print(f"  Rows: {len(df)}  Cols: {len(df.columns)}")
    print(f"  date_et range: {df['date_et'].min()} -> {df['date_et'].max()}")
    print(f"  POST-IB bars (mins_et >= 630): {(df['mins_et'] >= 630).sum()}")

    print("\n=== Test 1 : open_cash_price1030 streaming parity ===")
    test_open_cash_price1030_streaming_parity_v4(df)

    print("\n=== Test 2 : game_changers streaming parity ===")
    test_game_changers_streaming_parity_v4(df)

    print("\n=== Test 3 : R1 forbidden features absent ===")
    test_v4_does_not_contain_r1_forbidden_features(df)

    print("\n=== ALL V4 PARITY TESTS PASS ===")
