"""test_engine_parity.py — outil reutilisable test parite batch vs streaming.

Phase 3a Jour 5 du Chantier 3 (Live Enricher Option D), reframe Plan agent.

Plan agent verdict Jour 5 : refacto engines streaming-aware DOIT etre validee
par test parite strict pour eviter Pattern 11 V1 (refacto 13 engines avec
drift cumulatif si critere lache).

Critere parite strict (Plan agent recommandations) :
  - Colonnes int / bool / categorial : == exact (pas de tolerance)
  - Colonnes float                  : abs_diff.max() < 1e-9 (IEEE 754)
  - NaN mask                        : df_batch.isna() == df_stream.isna()
  - Structure                       : memes colonnes + memes dtypes

Outil reutilisable :
  test_engine_parity(
      engine_name="vix_lite",
      batch_fn=enrich_vix_lite,           # API batch existante
      streaming_fn=enrich_vix_lite_streaming,  # API streaming nouvelle
      state_factory=VixLiteState,
      input_df=df_real,
      float_atol=1e-9,
  ) -> dict[str, Any]  # report

Usage CLI :
  python -m tools.test_engine_parity --engine vix_lite

Auteur : MIA Trading System V2
  v1.0 (2026-05-13 nuit) : version initiale Phase 3a Jour 5
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


def _nan_mask_match(s_batch: pd.Series, s_stream: pd.Series) -> tuple[bool, int]:
    """Compare NaN mask exact. Returns (match, n_diff)."""
    mask_batch = s_batch.isna()
    mask_stream = s_stream.isna()
    diff = (mask_batch != mask_stream)
    return (not diff.any(), int(diff.sum()))


def _value_match(
    s_batch: pd.Series,
    s_stream: pd.Series,
    float_atol: float = 1e-9,
) -> tuple[bool, dict]:
    """Compare valeurs non-NaN. int/bool: ==, float: abs_diff < atol.

    Returns (match, stats).
    """
    # Compare sur les bars ou les 2 sont non-NaN
    both_valid = s_batch.notna() & s_stream.notna()
    if both_valid.sum() == 0:
        return (True, {"n_compare": 0, "all_nan_match": True})

    b = s_batch[both_valid]
    st = s_stream[both_valid]

    # Type detection
    is_int = pd.api.types.is_integer_dtype(b) and pd.api.types.is_integer_dtype(st)
    is_bool = pd.api.types.is_bool_dtype(b) and pd.api.types.is_bool_dtype(st)
    is_datetime = pd.api.types.is_datetime64_any_dtype(b) and pd.api.types.is_datetime64_any_dtype(st)
    is_object = pd.api.types.is_object_dtype(b) and pd.api.types.is_object_dtype(st)
    is_string = pd.api.types.is_string_dtype(b) and pd.api.types.is_string_dtype(st)

    if is_int or is_bool or is_datetime or is_object or is_string:
        # Exact match required (passthrough columns identiques)
        match_mask = (b == st)
        n_diff = int((~match_mask).sum())
        dtype_label = (
            "int" if is_int else "bool" if is_bool else
            "datetime" if is_datetime else "string" if is_string else "object"
        )
        return (n_diff == 0, {
            "n_compare": int(both_valid.sum()),
            "n_diff_exact": n_diff,
            "dtype": dtype_label,
        })
    else:
        # Float : abs_diff.max() < atol
        try:
            diff = (b.astype("float64") - st.astype("float64")).abs()
        except (TypeError, ValueError) as e:
            return (False, {"error": f"dtype mismatch: {e}"})
        max_diff = float(diff.max())
        return (max_diff < float_atol, {
            "n_compare": int(both_valid.sum()),
            "max_diff": max_diff,
            "atol": float_atol,
            "dtype": "float",
        })


def test_engine_parity(
    engine_name: str,
    batch_fn: Callable[[pd.DataFrame], pd.DataFrame],
    streaming_fn: Callable[[dict, Any], dict],
    state_factory: Callable[[], Any],
    input_df: pd.DataFrame,
    float_atol: float = 1e-9,
    verbose: bool = True,
) -> dict[str, Any]:
    """Test parite strict batch vs streaming pour 1 engine.

    Args:
        engine_name : nom logique pour affichage
        batch_fn(df) -> df enriched
        streaming_fn(row_dict, state) -> enriched_row_dict
        state_factory() -> nouveau state (creer 1 fois pour streaming complet)
        input_df : DataFrame entree (avant enrichissement)
        float_atol : tolerance abs_diff pour floats (default IEEE 754)
        verbose : print rapport

    Returns:
        dict report avec keys :
          status : "PASS" / "FAIL"
          n_rows : nb rows testes
          n_cols_compared : nb colonnes comparees
          failures : list[dict] des colonnes en echec
          summary : str resumee
    """
    # 1. Run batch
    df_batch = batch_fn(input_df.copy())

    # 2. Run streaming row-by-row
    state = state_factory()
    rows_stream = []
    for _, row in input_df.iterrows():
        enriched = streaming_fn(row.to_dict(), state)
        rows_stream.append(enriched)
    df_stream = pd.DataFrame(rows_stream, index=input_df.index)

    # 3. Compare structure
    cols_batch = set(df_batch.columns)
    cols_stream = set(df_stream.columns)
    missing_in_stream = cols_batch - cols_stream
    extra_in_stream = cols_stream - cols_batch
    common = cols_batch & cols_stream

    # 4. Compare colonnes communes
    failures = []
    for col in sorted(common):
        s_batch = df_batch[col]
        s_stream = df_stream[col]

        nan_match, n_nan_diff = _nan_mask_match(s_batch, s_stream)
        val_match, val_stats = _value_match(s_batch, s_stream, float_atol=float_atol)

        if not nan_match:
            failures.append({
                "col": col, "reason": "NaN mask mismatch",
                "n_diff": n_nan_diff,
            })
        if not val_match:
            failures.append({
                "col": col, "reason": "value mismatch",
                "stats": val_stats,
            })

    # 5. Build report
    report = {
        "engine_name": engine_name,
        "n_rows": len(input_df),
        "n_cols_input": len(input_df.columns),
        "n_cols_batch": len(df_batch.columns),
        "n_cols_stream": len(df_stream.columns),
        "n_cols_common": len(common),
        "n_cols_missing_in_stream": len(missing_in_stream),
        "n_cols_extra_in_stream": len(extra_in_stream),
        "missing_in_stream": sorted(missing_in_stream),
        "extra_in_stream": sorted(extra_in_stream),
        "n_failures": len(failures),
        "failures": failures,
        "status": "PASS" if (
            len(failures) == 0
            and len(missing_in_stream) == 0
        ) else "FAIL",
        "float_atol": float_atol,
    }

    if verbose:
        _print_report(report)

    return report


def test_warmup_parity(
    engine_name: str,
    streaming_fn: Callable[[dict, Any], dict],
    state_factory: Callable[[], Any],
    input_df: pd.DataFrame,
    restart_at_idx: int,
    float_atol: float = 1e-9,
    verbose: bool = True,
) -> dict[str, Any]:
    """Test parite warmup R2 (Plan agent reserve R2).

    Verifie : df_stream_continu_J0_JN vs df_stream_J0_Jmid + pickle.save +
    pickle.load + df_stream_Jmid_JN.

    Si state mal serialise, les 2 chemins divergent -> FAIL.
    Critique pour engines stateful (EMA, rolling, etc.).

    Args:
        engine_name : nom logique
        streaming_fn(row, state) -> enriched_row
        state_factory() -> nouveau state
        input_df : DataFrame entree (>= restart_at_idx + 100 rows)
        restart_at_idx : indice ou on simule un restart (pickle save+load)
        float_atol : tolerance abs_diff pour floats
        verbose : print rapport

    Returns:
        dict report (status PASS/FAIL + stats).
    """
    import pickle

    if restart_at_idx <= 0 or restart_at_idx >= len(input_df):
        return {"status": "ERROR", "reason": "invalid restart_at_idx"}

    # Path 1 : streaming continu de 0 a len(input_df)
    state_continu = state_factory()
    rows_continu = []
    for _, row in input_df.iterrows():
        enriched = streaming_fn(row.to_dict(), state_continu)
        rows_continu.append(enriched)
    df_continu = pd.DataFrame(rows_continu, index=input_df.index)

    # Path 2 : streaming 0..restart_idx, pickle save+load, restart..end
    state_part1 = state_factory()
    rows_part1 = []
    for i, (_, row) in enumerate(input_df.iterrows()):
        if i >= restart_at_idx:
            break
        enriched = streaming_fn(row.to_dict(), state_part1)
        rows_part1.append(enriched)

    # SIMULATE RESTART : pickle save + load
    try:
        pickled = pickle.dumps(state_part1, protocol=pickle.HIGHEST_PROTOCOL)
        state_restart = pickle.loads(pickled)
    except (pickle.PickleError, TypeError) as e:
        report = {
            "engine_name": engine_name,
            "test_type": "warmup_R2",
            "status": "FAIL",
            "reason": f"pickle round-trip failed: {e}",
        }
        if verbose:
            print(f"WARMUP R2 PARITY FAIL : {engine_name} pickle error : {e}")
        return report

    rows_part2 = []
    for i, (_, row) in enumerate(input_df.iterrows()):
        if i < restart_at_idx:
            continue
        enriched = streaming_fn(row.to_dict(), state_restart)
        rows_part2.append(enriched)

    df_restart = pd.DataFrame(rows_part1 + rows_part2, index=input_df.index)

    # Compare df_continu vs df_restart (DOIT etre identique si state bien serialise)
    failures = []
    for col in sorted(set(df_continu.columns) & set(df_restart.columns)):
        s_c = df_continu[col]
        s_r = df_restart[col]
        nan_match, n_nan_diff = _nan_mask_match(s_c, s_r)
        val_match, val_stats = _value_match(s_c, s_r, float_atol=float_atol)
        if not nan_match:
            failures.append({"col": col, "reason": "NaN mask mismatch", "n_diff": n_nan_diff})
        if not val_match:
            failures.append({"col": col, "reason": "value mismatch", "stats": val_stats})

    report = {
        "engine_name": engine_name,
        "test_type": "warmup_R2",
        "n_rows_total": len(input_df),
        "restart_at_idx": restart_at_idx,
        "n_failures": len(failures),
        "failures": failures,
        "status": "PASS" if len(failures) == 0 else "FAIL",
        "float_atol": float_atol,
    }
    if verbose:
        print("=" * 70)
        print(f"WARMUP R2 PARITY — engine '{engine_name}'")
        print(f"  Restart at idx : {restart_at_idx}/{len(input_df)}")
        print(f"  Status         : {report['status']}")
        if failures:
            print(f"  Failures ({len(failures)}) :")
            for f in failures[:5]:
                print(f"    - {f}")
        print("=" * 70)
    return report


def test_state_pickle_roundtrip(
    engine_name: str,
    streaming_fn: Callable[[dict, Any], dict],
    state_factory: Callable[[], Any],
    sample_row: dict,
    verbose: bool = True,
) -> dict[str, Any]:
    """Test isolated pickle roundtrip du state apres N appels streaming.

    Verifie que state contient bien les attributs necessaires (sinon
    fallback silencieux Pattern 11) et que pickle preserve l'etat.
    """
    import pickle
    state = state_factory()
    # Run 10 appels pour mater le state
    for _ in range(10):
        streaming_fn(sample_row, state)
    try:
        pickled = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
        state_reloaded = pickle.loads(pickled)
        # Verify type
        assert type(state_reloaded) is type(state)
        # Run 1 more appel sur state reloaded vs state original (deep copy)
        import copy
        state_copy = copy.deepcopy(state)
        out_a = streaming_fn(sample_row, state_reloaded)
        out_b = streaming_fn(sample_row, state_copy)
        # Compare outputs
        for k in set(out_a) & set(out_b):
            va, vb = out_a[k], out_b[k]
            if va is None and vb is None:
                continue
            if isinstance(va, float) and isinstance(vb, float):
                if pd.isna(va) and pd.isna(vb):
                    continue
                if abs(va - vb) > 1e-12:
                    return {
                        "status": "FAIL",
                        "reason": f"pickle reloaded != deepcopy for {k}: {va} vs {vb}"
                    }
            elif va != vb:
                return {"status": "FAIL", "reason": f"output mismatch {k}: {va} vs {vb}"}
        if verbose:
            print(f"[OK] pickle roundtrip {engine_name} (state.dict={state.__dict__})")
        return {"status": "PASS"}
    except Exception as e:
        return {"status": "FAIL", "reason": f"pickle error: {e}"}


def _print_report(report: dict) -> None:
    """Print rapport formatte console."""
    print("=" * 70)
    print(f"PARITE BATCH vs STREAMING — engine '{report['engine_name']}'")
    print("=" * 70)
    print(f"  Status                  : {report['status']}")
    print(f"  Rows testees            : {report['n_rows']}")
    print(f"  Cols (input/batch/stream/common) : "
          f"{report['n_cols_input']}/{report['n_cols_batch']}/"
          f"{report['n_cols_stream']}/{report['n_cols_common']}")
    print(f"  Float atol              : {report['float_atol']}")
    if report['n_cols_missing_in_stream'] > 0:
        print(f"  MISSING in stream       : {report['missing_in_stream']}")
    if report['n_cols_extra_in_stream'] > 0:
        print(f"  EXTRA in stream         : {report['extra_in_stream']}")
    if report['failures']:
        print(f"  FAILURES ({len(report['failures'])}) :")
        for f in report['failures'][:10]:
            print(f"    - {f}")
    print("=" * 70)


def _test_vix_lite():
    """Test parite vix_lite (pilote stateless Phase 3a Jour 5)."""
    from vix_lite_reader import (
        load_vix_lite_jsonl, enrich_vix_lite,
        VixLiteState, enrich_vix_lite_streaming,
    )

    # Load donnees reelles VIX (sync VPS si dispo)
    today = date(2026, 5, 13)
    df = load_vix_lite_jsonl(today - timedelta(days=2), today)
    if df.empty:
        print("[SKIP] aucun fichier VIX_Lite local pour test vix_lite parity")
        return

    print(f"\nTest vix_lite parite sur {len(df)} rows reelles...")
    report = test_engine_parity(
        engine_name="vix_lite",
        batch_fn=enrich_vix_lite,
        streaming_fn=enrich_vix_lite_streaming,
        state_factory=VixLiteState,
        input_df=df,
        float_atol=1e-9,
    )
    return report


def _make_synth_vix_df(n: int = 500, n_nan_gap_start: int = 200, n_nan_gap_len: int = 5) -> pd.DataFrame:
    """Genere DataFrame synth VIX avec NaN gap (P0-2 audit code-reviewer).

    Critique : valide convention NaN streaming != divergence pandas default.
    Avec ignore_na=True (notre choix), le state garde l'EMA et reprend au
    prochain non-NaN sans drift. Test sur >= 200 rows pour atteindre regime
    stable EMA(span=60).
    """
    import numpy as np
    np.random.seed(42)
    base = 17.0
    # Walk aleatoire stable
    vix_walk = base + np.cumsum(np.random.normal(0, 0.05, n))
    # Injecter NaN gap
    vix_walk[n_nan_gap_start: n_nan_gap_start + n_nan_gap_len] = np.nan
    return pd.DataFrame({"vix_level": vix_walk})


def _test_vix_ema_60():
    """Test pilote stateful EMA(vix_level, 60) — 3 niveaux parite + NaN gap.

    Plan agent recommendation engine N°2 stateful trivial pour valider
    definitivement la convention API streaming :
      Niveau 1 : parite batch vs stream (test_engine_parity)
      Niveau 2 : pickle roundtrip state (test_state_pickle_roundtrip)
      Niveau 3 : warmup R2 continu vs restart (test_warmup_parity)
      Niveau 4 (P0-2 fix) : NaN gap synthetic >= 200 rows
    """
    from vix_lite_reader import (
        load_vix_lite_jsonl, apply_vix_ema_batch, apply_vix_ema_streaming, VixEmaState,
    )

    today = date(2026, 5, 13)
    df = load_vix_lite_jsonl(today - timedelta(days=2), today)
    if df.empty or len(df) < 5:
        # Fallback synth si pas de donnees reelles (anti SKIP silencieux)
        print(f"[INFO] live data insufficient ({len(df) if not df.empty else 0} rows), use synth 500 rows...")
        df = _make_synth_vix_df(n=500, n_nan_gap_start=200, n_nan_gap_len=5)
    elif len(df) < 200:
        # Augmenter avec synth pour avoir >= 200 rows
        synth = _make_synth_vix_df(n=500 - len(df), n_nan_gap_start=100, n_nan_gap_len=5)
        df = pd.concat([df[["vix_level"]], synth], ignore_index=True)

    print(f"\nTest vix_ema_60 parite sur {len(df)} rows reelles...")

    # NIVEAU 1 : parite batch vs streaming
    print("\n--- NIVEAU 1 : parite batch vs streaming ---")
    report1 = test_engine_parity(
        engine_name="vix_ema_60",
        batch_fn=apply_vix_ema_batch,
        streaming_fn=apply_vix_ema_streaming,
        state_factory=VixEmaState,
        input_df=df,
        float_atol=1e-9,
    )

    # NIVEAU 2 : pickle roundtrip
    print("\n--- NIVEAU 2 : pickle roundtrip state ---")
    sample_row = df.iloc[0].to_dict()
    report2 = test_state_pickle_roundtrip(
        engine_name="vix_ema_60",
        streaming_fn=apply_vix_ema_streaming,
        state_factory=VixEmaState,
        sample_row=sample_row,
    )

    # NIVEAU 3 : warmup R2 (continu vs restart au milieu)
    print("\n--- NIVEAU 3 : warmup R2 (continu vs restart pickle save+load) ---")
    mid = len(df) // 2
    report3 = test_warmup_parity(
        engine_name="vix_ema_60",
        streaming_fn=apply_vix_ema_streaming,
        state_factory=VixEmaState,
        input_df=df,
        restart_at_idx=mid,
        float_atol=1e-9,
    )

    all_pass = (
        report1.get("status") == "PASS"
        and report2.get("status") == "PASS"
        and report3.get("status") == "PASS"
    )
    print(f"\n{'=' * 70}")
    print(f"GLOBAL vix_ema_60 : {'ALL 3 LEVELS PASS' if all_pass else 'FAIL'}")
    print(f"  Niveau 1 (parite batch/stream) : {report1.get('status')}")
    print(f"  Niveau 2 (pickle roundtrip)    : {report2.get('status')}")
    print(f"  Niveau 3 (warmup R2)           : {report3.get('status')}")
    print("=" * 70)
    return {"level1": report1, "level2": report2, "level3": report3, "all_pass": all_pass}


def _test_session_metadata():
    """Test sub-engine #1 add_session_metadata (Chantier 3 Phase 3b Lundi).

    Stateless engine row-level pur. 3 niveaux parite :
      Niveau 1 : parite batch vs streaming
      Niveau 2 : pickle roundtrip state (state vide)
      Niveau 3 : warmup R2 (trivial vu stateless mais test toujours)
    """
    from phase_b_helpers import (
        add_session_metadata,
        add_session_metadata_streaming,
        SessionMetadataState,
    )
    import numpy as np
    import pandas as pd

    # Synth DataFrame : 200 bars 1-min couvrant Asia + London + US + after-hours
    # avec cross-day boundary (test asia_start logique session_date_trading)
    start = pd.Timestamp("2026-05-12 22:00:00", tz="UTC")  # 18:00 ET dim soir
    ts_range = pd.date_range(start, periods=200, freq="5min").tz_localize(None)
    df = pd.DataFrame({"ts_event": ts_range})

    print(f"\nTest session_metadata parite sur {len(df)} rows synth...")

    # FIX P0-2 audit 13/05 nuit : matrice bounds (couvre None + ES/NQ + MGC).
    # Test parite doit valider que batch et streaming convergent pour CHAQUE
    # configuration bounds. Anti faux PASS "happy path bounds=None only".
    MGC_BOUNDS = {"asia_start": 1080, "us_start": 510, "us_after_start": 810}  # 08:30-13:30 RTH gold
    bounds_matrix = [
        ("default_None", None),
        ("ES_NQ_explicit", {"asia_start": 1080, "us_start": 570, "us_after_start": 960}),
        ("MGC_gold_RTH", MGC_BOUNDS),
    ]

    all_level1_pass = True
    for bounds_name, bounds_cfg in bounds_matrix:
        print(f"\n--- NIVEAU 1 : parite batch vs streaming (bounds={bounds_name}) ---")

        def batch_fn(d, _bcfg=bounds_cfg):
            return add_session_metadata(d, bounds=_bcfg)

        def stream_fn(row, state, _bcfg=bounds_cfg):
            return add_session_metadata_streaming(row, state, bounds=_bcfg)

        report_b = test_engine_parity(
            engine_name=f"session_metadata[{bounds_name}]",
            batch_fn=batch_fn,
            streaming_fn=stream_fn,
            state_factory=SessionMetadataState,
            input_df=df,
            float_atol=1e-9,
        )
        if report_b["status"] != "PASS":
            all_level1_pass = False

    # FIX P0-2 (suite) : valider raise KeyError sur bounds partiel (fail-loud)
    print("\n--- NIVEAU 1 BIS : fail-loud bounds partiel (KeyError explicite) ---")
    partial_bounds = {"asia_start": 1080}  # manque us_start + us_after_start
    raised_batch = False
    raised_stream = False
    try:
        add_session_metadata(df.copy(), bounds=partial_bounds)
    except KeyError:
        raised_batch = True
    try:
        state_partial = SessionMetadataState()
        add_session_metadata_streaming(df.iloc[0].to_dict(), state_partial, bounds=partial_bounds)
    except KeyError:
        raised_stream = True
    if raised_batch and raised_stream:
        print("[OK] batch + stream raise KeyError explicite sur bounds partiel (anti Pattern 11)")
    else:
        print(f"[FAIL] silent fallback persiste : batch_raised={raised_batch} stream_raised={raised_stream}")
        all_level1_pass = False

    # Le rapport principal utilise bounds=None (compat compat outil downstream)
    def batch_fn_default(d):
        return add_session_metadata(d, bounds=None)

    def stream_fn_default(row, state):
        return add_session_metadata_streaming(row, state, bounds=None)

    report1 = test_engine_parity(
        engine_name="session_metadata",
        batch_fn=batch_fn_default,
        streaming_fn=stream_fn_default,
        state_factory=SessionMetadataState,
        input_df=df,
        float_atol=1e-9,
        verbose=False,
    )
    if not all_level1_pass:
        report1["status"] = "FAIL"

    print("\n--- NIVEAU 2 : pickle roundtrip state ---")
    sample_row = df.iloc[0].to_dict()
    report2 = test_state_pickle_roundtrip(
        engine_name="session_metadata",
        streaming_fn=stream_fn,
        state_factory=SessionMetadataState,
        sample_row=sample_row,
    )

    print("\n--- NIVEAU 3 : warmup R2 (continu vs restart) ---")
    report3 = test_warmup_parity(
        engine_name="session_metadata",
        streaming_fn=stream_fn,
        state_factory=SessionMetadataState,
        input_df=df,
        restart_at_idx=100,
        float_atol=1e-9,
    )

    all_pass = (
        report1.get("status") == "PASS"
        and report2.get("status") == "PASS"
        and report3.get("status") == "PASS"
    )
    print(f"\n{'=' * 70}")
    print(f"GLOBAL session_metadata : {'ALL 3 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"level1": report1, "level2": report2, "level3": report3, "all_pass": all_pass}


def _test_ib_features():
    """Test sub-engine #2 add_ib_features (state daily IB groupby).

    Plus complexe que sub-engine #1 :
      - State : ib_high/low cumulative reset par session
      - Anti-leak : ib_high/low NaN si ib_complete=0
      - Edge case : changement session ET pendant IB window
    """
    from phase_b_helpers import (
        add_session_metadata,
        add_ib_features,
        add_ib_features_streaming,
        IBState,
    )
    import numpy as np
    import pandas as pd

    # Synth DataFrame : 3 jours x bars 1-min couvrant pré-IB + IB + post-IB
    # On veut couvrir : 09:00 (pre-IB), 09:30-10:30 (IB), 10:30-16:00 (post-IB)
    # Sur 3 jours pour tester reset session
    bars = []
    base_price = 5800.0
    for day_offset in range(3):
        start_et = pd.Timestamp(f"2026-05-1{2 + day_offset} 13:00:00", tz="UTC")  # 09:00 ET
        # 8 heures bars 1-min = 480 bars/jour
        for i in range(480):
            ts = start_et + pd.Timedelta(minutes=i)
            high = base_price + i * 0.1 + day_offset * 5
            low = high - 0.5
            close = (high + low) / 2
            bars.append({"ts_event": ts.tz_localize(None), "high": high, "low": low, "close": close})

    df = pd.DataFrame(bars)
    df = add_session_metadata(df, bounds=None)  # ajout date_et, mins_et, is_ib_window

    print(f"\nTest ib_features parite sur {len(df)} rows synth (3 jours)...")

    bounds = None
    def batch_fn(d):
        return add_ib_features(d.copy(), tick=0.25, bounds=bounds)

    def stream_fn(row, state):
        return add_ib_features_streaming(row, state, tick=0.25, bounds=bounds)

    print("\n--- NIVEAU 1 : parite batch vs streaming ---")
    report1 = test_engine_parity(
        engine_name="ib_features",
        batch_fn=batch_fn,
        streaming_fn=stream_fn,
        state_factory=IBState,
        input_df=df,
        float_atol=1e-9,
    )

    print("\n--- NIVEAU 2 : pickle roundtrip state (NON-VIDE post-IB window) ---")
    # FIX P0-3 audit code-reviewer : sample_row dans IB window = state non-vide
    # apres warmup. Sinon pickle test trivial (state vide = PASS sans verifier).
    # On utilise row 60 (= 10:00 ET, milieu IB window jour 1) pour s'assurer
    # que state.ib_high/low sont mis a jour avant pickle test.
    state_test = IBState()
    for i, (_, row) in enumerate(df.iterrows()):
        if i >= 100:
            break
        stream_fn(row.to_dict(), state_test)
    print(f"  state apres 100 bars (devrait NON-vide) : {state_test.__dict__}")
    # Assertion explicite : state DOIT etre non-vide pour valider pickle utile
    assert state_test.ib_high is not None, (
        f"P0-3 fix : state.ib_high doit etre non-None apres 100 bars IB. "
        f"State : {state_test.__dict__}"
    )
    assert state_test.n_ib_bars_seen > 0, "P0-3 fix : n_ib_bars_seen doit etre > 0"
    # Sample row dans IB window pour test pickle utile (state evolue)
    sample_row = df.iloc[60].to_dict()  # ~10:00 ET = milieu IB
    report2 = test_state_pickle_roundtrip(
        engine_name="ib_features",
        streaming_fn=stream_fn,
        state_factory=IBState,
        sample_row=sample_row,
    )

    print("\n--- NIVEAU 3 : warmup R2 (restart pendant IB window critique) ---")
    # Restart à idx 35 (= ~09:30 ET début IB) : state.ib_high partiel pour jour 1
    # MAIS pickle save+load -> jour 2 et 3 doivent matcher continu
    report3 = test_warmup_parity(
        engine_name="ib_features",
        streaming_fn=stream_fn,
        state_factory=IBState,
        input_df=df,
        restart_at_idx=500,  # après jour 1 complet, début jour 2
        float_atol=1e-9,
    )

    all_pass = (
        report1.get("status") == "PASS"
        and report2.get("status") == "PASS"
        and report3.get("status") == "PASS"
    )
    print(f"\n{'=' * 70}")
    print(f"GLOBAL ib_features : {'ALL 3 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"level1": report1, "level2": report2, "level3": report3, "all_pass": all_pass}


def _test_session_high_low():
    """Test sub-engine #3 add_session_high_low (2 axes parallele).

    Couvre :
      - Reset session_date_trading (CME futures)
      - Reset date_et (cash RTH)
      - Anti-leak cash_high/low = NaN hors cash session
      - is_new_sess_high/low + is_new_cash_high/low events
      - Edge case GAP cash (halt mid-session) : critique pour parite shift(1)
    """
    from phase_b_helpers import (
        add_session_metadata,
        add_session_high_low,
        add_session_high_low_streaming,
        SessionHighLowState,
    )
    import numpy as np
    import pandas as pd

    # Synth 3 jours x 480 bars/jour, 09:00-17:00 ET, varying highs to trigger events
    bars = []
    base_price = 5800.0
    for day_offset in range(3):
        start_et = pd.Timestamp(f"2026-05-1{2 + day_offset} 13:00:00", tz="UTC")  # 09:00 ET
        for i in range(480):
            ts = start_et + pd.Timedelta(minutes=i)
            # Oscillation pour tester is_new events (parfois high monte, parfois pas)
            wave = np.sin(i / 30.0) * 2.0
            high = base_price + i * 0.05 + wave + day_offset * 5
            low = high - 0.5
            close = (high + low) / 2
            bars.append({
                "ts_event": ts.tz_localize(None),
                "high": high,
                "low": low,
                "close": close,
            })

    df = pd.DataFrame(bars)
    df = add_session_metadata(df, bounds=None)

    print(f"\nTest session_high_low parite sur {len(df)} rows synth (3 jours)...")

    def batch_fn(d):
        return add_session_high_low(d.copy(), tick=0.25, bounds=None)

    def stream_fn(row, state):
        return add_session_high_low_streaming(row, state, tick=0.25)

    print("\n--- NIVEAU 1 : parite batch vs streaming ---")
    report1 = test_engine_parity(
        engine_name="session_high_low",
        batch_fn=batch_fn,
        streaming_fn=stream_fn,
        state_factory=SessionHighLowState,
        input_df=df,
        float_atol=1e-9,
    )

    print("\n--- NIVEAU 2 : pickle roundtrip state NON-VIDE (mid-cash) ---")
    # Warmup pour avoir state cash_high/low + sess_high/low populated
    # Row ~60 = 10:00 ET = milieu cash session jour 1
    state_test = SessionHighLowState()
    for i, (_, row) in enumerate(df.iterrows()):
        if i >= 100:
            break
        stream_fn(row.to_dict(), state_test)
    print(f"  state apres 100 bars : "
          f"sess_high={state_test.sess_high}, sess_low={state_test.sess_low}, "
          f"cash_high={state_test.cash_high}, cash_low={state_test.cash_low}, "
          f"sess_n={state_test.sess_n_bars}, cash_n={state_test.cash_n_bars}")
    assert state_test.sess_high is not None, "P0 : sess_high doit etre non-None apres 100 bars"
    assert state_test.cash_high is not None, "P0 : cash_high doit etre non-None apres 100 bars (mid-cash)"
    assert state_test.sess_n_bars >= 100, "P0 : sess_n_bars >= 100"
    assert state_test.cash_n_bars > 0, "P0 : au moins quelques cash bars"

    sample_row = df.iloc[100].to_dict()  # mid-cash session
    report2 = test_state_pickle_roundtrip(
        engine_name="session_high_low",
        streaming_fn=stream_fn,
        state_factory=SessionHighLowState,
        sample_row=sample_row,
    )

    print("\n--- NIVEAU 3 : warmup R2 restart cross-session ---")
    # Restart idx 500 = milieu jour 2 (apres reset session_date_trading)
    report3 = test_warmup_parity(
        engine_name="session_high_low",
        streaming_fn=stream_fn,
        state_factory=SessionHighLowState,
        input_df=df,
        restart_at_idx=500,
        float_atol=1e-9,
    )

    # ─── NIVEAU 4 (BONUS) : Edge case GAP cash (halt mid-session) ───────────
    # Verifier que cash_high NaN sur ligne halt + is_new_cash_high=0 ligne post-halt
    # meme si high > cash_high cumule.
    print("\n--- NIVEAU 4 BONUS : edge case GAP cash (halt mid-session) ---")
    bars_halt = []
    start_et = pd.Timestamp("2026-05-15 13:00:00", tz="UTC")  # 09:00 ET
    base = 5800.0
    for i in range(480):
        ts = start_et + pd.Timedelta(minutes=i)
        high = base + i * 0.1
        low = high - 0.5
        bars_halt.append({
            "ts_event": ts.tz_localize(None),
            "high": high, "low": low, "close": (high + low) / 2,
        })
    df_halt = pd.DataFrame(bars_halt)
    df_halt = add_session_metadata(df_halt, bounds=None)
    # Forcer halt : is_cash_session=0 sur 5 bars en plein milieu cash
    cash_mask = df_halt["is_cash_session"] == 1
    cash_indices = df_halt.index[cash_mask].tolist()
    halt_idx = cash_indices[len(cash_indices) // 2:len(cash_indices) // 2 + 5]
    df_halt.loc[halt_idx, "is_cash_session"] = 0

    batch_halt = add_session_high_low(df_halt.copy(), tick=0.25, bounds=None)
    state_halt = SessionHighLowState()
    stream_rows = []
    for _, r in df_halt.iterrows():
        out = stream_fn(r.to_dict(), state_halt)
        stream_rows.append(out)
    stream_halt = pd.DataFrame(stream_rows)

    # Check parite sur les 12 features y compris pendant le halt
    cols_check = [
        "sess_high", "sess_low", "cash_high", "cash_low",
        "dist_sess_high_pct", "dist_sess_low_pct",
        "dist_cash_high_pct", "dist_cash_low_pct",
        "is_new_sess_high", "is_new_sess_low",
        "is_new_cash_high", "is_new_cash_low",
    ]
    max_diff_halt = 0.0
    failed_cols = []
    for col in cols_check:
        if col not in stream_halt.columns or col not in batch_halt.columns:
            failed_cols.append(f"{col}:missing")
            continue
        b = batch_halt[col].astype("float64").values
        s = stream_halt[col].astype("float64").values
        # NaN compare equal
        diff = np.abs(np.where(np.isnan(b) & np.isnan(s), 0, np.where(np.isnan(b) | np.isnan(s), 1e9, b - s)))
        col_max = float(np.nanmax(diff))
        if col_max > 1e-9:
            failed_cols.append(f"{col}:diff={col_max:.6e}")
        max_diff_halt = max(max_diff_halt, col_max)

    # Specifique : verifier que cash_high == NaN sur lignes halt
    halt_cash_high_batch = batch_halt.loc[halt_idx, "cash_high"]
    halt_cash_high_stream = stream_halt.loc[halt_idx, "cash_high"]
    assert halt_cash_high_batch.isna().all(), \
        f"batch cash_high doit etre NaN pendant halt : {halt_cash_high_batch.tolist()}"
    assert halt_cash_high_stream.isna().all(), \
        f"stream cash_high doit etre NaN pendant halt : {halt_cash_high_stream.tolist()}"

    report4_status = "PASS" if max_diff_halt < 1e-9 and not failed_cols else "FAIL"
    print(f"  halt_idx={list(halt_idx)} cash_high all NaN : OK")
    print(f"  max_diff sur 12 features (halt edge) : {max_diff_halt:.6e}")
    print(f"  failed_cols : {failed_cols}")
    print(f"  GAP CASH PARITE : {report4_status}")
    report4 = {"status": report4_status, "max_diff": max_diff_halt, "failed_cols": failed_cols}

    all_pass = (
        report1.get("status") == "PASS"
        and report2.get("status") == "PASS"
        and report3.get("status") == "PASS"
        and report4["status"] == "PASS"
    )
    print(f"\n{'=' * 70}")
    print(f"GLOBAL session_high_low : {'ALL 4 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {
        "level1": report1, "level2": report2, "level3": report3,
        "level4_halt": report4, "all_pass": all_pass,
    }


def _test_volume_profile():
    """Test sub-engine #4 add_volume_profile_features (RUNNING VPOC intraday).

    DIVERGENCE BATCH/STREAM DOCUMENTEE :
      - Batch : cur_vpoc CONSTANT per session (fin de session, broadcast)
      - Stream : cur_vpoc EVOLUE intraday (running VPOC sur trades accumules)
      - Parite VRAIE uniquement sur LAST BAR de chaque session

    Test verifie :
      - Last bar parite : stream final running VPOC == batch session VPOC (atol 1e-6)
      - State pickle roundtrip (mid-session, state non-vide)
      - Rotation session : prev_* correctement transferes apres detection nouvelle
        session_date_trading

    NB : on n'utilise PAS test_engine_parity standard (row-by-row PASS impossible).
    """
    from phase_b_helpers import (
        add_session_metadata,
        add_volume_profile_features,
        add_volume_profile_features_streaming,
        VolumeProfileState,
    )
    import numpy as np
    import pandas as pd
    import pickle

    # Build synth : 3 sessions CME (dim 18h ET -> ven 17h ET)
    # Simplification : on prend 3 jours calendar consecutifs, chacun avec ses propres trades.
    # add_session_metadata calcule session_date_trading.
    bars = []
    trades = []
    np.random.seed(42)
    for day_offset in range(3):
        date_str = f"2026-05-1{2 + day_offset}"
        # Bars 09:00 ET (13:00 UTC) - 16:00 ET (20:00 UTC) = 420 bars
        start_et = pd.Timestamp(f"{date_str} 13:00:00", tz="UTC")
        for i in range(420):
            ts_bar = start_et + pd.Timedelta(minutes=i)
            high = 5800.0 + day_offset * 5 + np.sin(i / 30.0) * 2.0 + i * 0.02
            low = high - 0.5
            close = (high + low) / 2
            bars.append({
                "ts_event": ts_bar.tz_localize(None),
                "open": close - 0.1, "high": high, "low": low, "close": close,
                "volume": 100, "delta_bar": 0,
            })
            # ~20 trades per bar, prix entre low et high
            n_trades = np.random.randint(15, 30)
            for _ in range(n_trades):
                price = np.random.uniform(low, high)
                size = np.random.randint(1, 10)
                # ts_event du trade : entre ts_bar et ts_bar + 1min (within bar window)
                ts_trade = ts_bar + pd.Timedelta(seconds=np.random.randint(0, 60))
                trades.append({
                    "ts_event": ts_trade.tz_localize(None),
                    "price": float(price),
                    "size": int(size),
                })

    df = pd.DataFrame(bars)
    trades_df = pd.DataFrame(trades)
    # ts_event tz-naive partout (bars + trades) pour pouvoir comparer dans stream loop.
    # Pour le batch, on tz_localize uniquement la copie passee a la fonction.
    df = add_session_metadata(df, bounds=None)

    print(f"\nTest volume_profile parite : {len(df)} bars + {len(trades_df)} trades synth")

    # BATCH reference (trades doivent etre tz-aware pour add_volume_profile_features)
    trades_df_batch = trades_df.copy()
    trades_df_batch["ts_event"] = pd.to_datetime(
        trades_df_batch["ts_event"]
    ).dt.tz_localize("UTC")
    batch_df = add_volume_profile_features(df.copy(), trades_df=trades_df_batch,
                                            tick=0.25, bounds=None)
    print(f"  Batch sessions detectees : {batch_df['session_date_trading'].unique()}")

    # STREAM : iterate bar par bar avec trades_in_window
    # FIX P1.1 audit code-reviewer : convention "trades de la bar i" = trades
    # ts in [bar_i.ts_event, bar_(i+1).ts_event). Stream est appele AU CLOSE
    # de chaque bar avec les trades survenus pendant la duration de la bar.
    # Pour la DERNIERE bar : on assume duration = 1min (synth) car pas de
    # next_bar disponible. Sans ce fix, les trades de la derniere bar etaient
    # drainees sans appel stream -> stream tronque vs batch complet -> faux PASS
    # masque par tolerance 0.25.
    state = VolumeProfileState()
    df_sorted = df.sort_values("ts_event").reset_index(drop=True)
    trades_df_sorted = trades_df.sort_values("ts_event").reset_index(drop=True)
    trades_arr = trades_df_sorted.to_dict("records")
    trade_idx = 0
    stream_rows = []
    n_bars = len(df_sorted)
    for i in range(n_bars):
        bar_row = df_sorted.iloc[i]
        bar_ts = bar_row["ts_event"]
        # ts_close de cette bar = ts_event de la bar i+1 (ou ts_event + 1min si derniere)
        if i + 1 < n_bars:
            bar_close_ts = df_sorted.iloc[i + 1]["ts_event"]
        else:
            bar_close_ts = bar_ts + pd.Timedelta(minutes=1)
        # Window = trades [bar_ts, bar_close_ts) = trades survenus PENDANT cette bar
        window = []
        while trade_idx < len(trades_arr):
            t = trades_arr[trade_idx]
            if t["ts_event"] < bar_close_ts:
                window.append({"price": t["price"], "size": t["size"]})
                trade_idx += 1
            else:
                break
        out = add_volume_profile_features_streaming(
            bar_row.to_dict(), state, trades_in_window=window, tick=0.25,
        )
        stream_rows.append(out)
    # Sanity : aucun trade ne doit rester non traite avec convention propre
    assert trade_idx == len(trades_arr), (
        f"P1.1 fix : {len(trades_arr) - trade_idx} trades non traites "
        f"(derniere bar window incomplete)"
    )
    stream_df = pd.DataFrame(stream_rows)

    # PARITE : last bar of each session
    # 2 niveaux de tolerance (P1.1 audit) :
    #   - pdh/pdl/cur_pdh/cur_pdl : max/min exacts SANS bucketing -> atol 1e-6
    #   - VPOC/VAH/VAL : tie-break depend ordre insertion dict -> atol 0.25 (1 tick)
    print("\n--- NIVEAU 1 : parite LAST BAR de chaque session ---")
    all_pass = True
    sessions = sorted(df_sorted["session_date_trading"].unique())
    cols_exact = ["cur_pdh", "cur_pdl", "pdh", "pdl"]  # atol 1e-6
    cols_bucket = ["cur_vpoc", "cur_vah", "cur_val",
                    "prev_vpoc", "prev_vah", "prev_val"]  # atol 0.25 (tie-break)
    for sess in sessions:
        mask_b = batch_df["session_date_trading"] == sess
        mask_s = stream_df["session_date_trading"] == sess
        last_idx_b = batch_df.index[mask_b][-1]
        last_idx_s = stream_df.index[mask_s][-1]
        b_row = batch_df.loc[last_idx_b]
        s_row = stream_df.loc[last_idx_s]
        diffs = {}

        def _check(col, atol):
            b_val = b_row[col]
            s_val = s_row[col]
            if pd.isna(b_val) and pd.isna(s_val):
                return
            if pd.isna(b_val) or pd.isna(s_val):
                diffs[col] = f"NaN mismatch (b={b_val}, s={s_val})"
                return
            d = abs(float(b_val) - float(s_val))
            if d > atol + 1e-9:
                diffs[col] = f"diff={d:.6f} (b={b_val:.4f}, s={s_val:.4f}) atol={atol}"

        for col in cols_exact:
            _check(col, atol=1e-6)
        for col in cols_bucket:
            _check(col, atol=0.25)

        sess_ok = len(diffs) == 0
        all_pass = all_pass and sess_ok
        print(f"  Session {sess} : {'PASS' if sess_ok else 'FAIL'} "
              f"({len(diffs)} divergences)")
        if diffs:
            for col, msg in diffs.items():
                print(f"    {col} : {msg}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")

    # NIVEAU 2 : pickle roundtrip state NON-VIDE
    print("\n--- NIVEAU 2 : pickle roundtrip state mid-session ---")
    # Warmup half session 1
    state_pickle = VolumeProfileState()
    half = len(df_sorted) // 6  # mid session 1
    trade_idx2 = 0
    for i, (_, bar_row) in enumerate(df_sorted.iterrows()):
        if i >= half:
            break
        bar_ts = bar_row["ts_event"]
        window = []
        while trade_idx2 < len(trades_arr) and trades_arr[trade_idx2]["ts_event"] < bar_ts:
            t = trades_arr[trade_idx2]
            window.append({"price": t["price"], "size": t["size"]})
            trade_idx2 += 1
        add_volume_profile_features_streaming(
            bar_row.to_dict(), state_pickle, trades_in_window=window, tick=0.25,
        )

    print(f"  state pre-pickle : n_trades={state_pickle.n_trades_session}, "
          f"n_buckets={len(state_pickle.price_volume)}, "
          f"pdh={state_pickle.pdh_running:.4f}, pdl={state_pickle.pdl_running:.4f}")
    assert state_pickle.n_trades_session > 0, "P0 : state vide post-warmup"
    assert len(state_pickle.price_volume) > 0, "P0 : price_volume vide"

    blob = pickle.dumps(state_pickle)
    state_restored = pickle.loads(blob)
    assert state_restored.n_trades_session == state_pickle.n_trades_session
    assert state_restored.price_volume == state_pickle.price_volume
    assert state_restored.pdh_running == state_pickle.pdh_running
    assert state_restored.pdl_running == state_pickle.pdl_running
    assert state_restored.current_session_date_trading == state_pickle.current_session_date_trading
    # Test row produit meme output apres pickle
    test_row = df_sorted.iloc[half].to_dict()
    out_orig = add_volume_profile_features_streaming(
        test_row, state_pickle, trades_in_window=[], tick=0.25,
    )
    out_restored = add_volume_profile_features_streaming(
        test_row, state_restored, trades_in_window=[], tick=0.25,
    )
    pickle_ok = True
    cols_all = cols_exact + cols_bucket
    for col in cols_all:
        a, b = out_orig.get(col), out_restored.get(col)
        if pd.isna(a) and pd.isna(b):
            continue
        if pd.isna(a) or pd.isna(b) or abs(a - b) > 1e-9:
            print(f"    pickle FAIL on {col}: orig={a} restored={b}")
            pickle_ok = False
    print(f"  Niveau 2 status : {'PASS' if pickle_ok else 'FAIL'}")

    # NIVEAU 3 : rotation session
    print("\n--- NIVEAU 3 : rotation session prev_* transfere ---")
    state_rot = VolumeProfileState()
    n_session_1 = sum(df_sorted["session_date_trading"] == sessions[0])
    trade_idx3 = 0
    # Process full session 1
    for i in range(n_session_1):
        bar_row = df_sorted.iloc[i]
        bar_ts = bar_row["ts_event"]
        window = []
        while trade_idx3 < len(trades_arr) and trades_arr[trade_idx3]["ts_event"] < bar_ts:
            t = trades_arr[trade_idx3]
            window.append({"price": t["price"], "size": t["size"]})
            trade_idx3 += 1
        add_volume_profile_features_streaming(
            bar_row.to_dict(), state_rot, trades_in_window=window, tick=0.25,
        )
    vpoc_session_1 = state_rot.price_volume and compute_vpoc_from_dict(state_rot.price_volume)
    # Process first bar of session 2 (triggers rotation)
    bar_row2 = df_sorted.iloc[n_session_1]
    bar_ts2 = bar_row2["ts_event"]
    window2 = []
    while trade_idx3 < len(trades_arr) and trades_arr[trade_idx3]["ts_event"] < bar_ts2:
        t = trades_arr[trade_idx3]
        window2.append({"price": t["price"], "size": t["size"]})
        trade_idx3 += 1
    out_post_rot = add_volume_profile_features_streaming(
        bar_row2.to_dict(), state_rot, trades_in_window=window2, tick=0.25,
    )
    print(f"  Post-rotation : prev_vpoc={state_rot.prev_vpoc}, "
          f"current_session={state_rot.current_session_date_trading}")
    rot_ok = (
        state_rot.prev_vpoc is not None
        and state_rot.current_session_date_trading == sessions[1]
        and len(state_rot.price_volume) > 0  # nouvelle session a deja des trades
    )
    print(f"  Niveau 3 status : {'PASS' if rot_ok else 'FAIL'}")

    all_pass = all_pass and pickle_ok and rot_ok
    print(f"\n{'=' * 70}")
    print(f"GLOBAL volume_profile : {'ALL 3 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def compute_vpoc_from_dict(price_volume):
    """Helper local : VPOC depuis price_volume dict."""
    if not price_volume:
        return None
    return max(price_volume, key=price_volume.get)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="vix_lite",
                        choices=["vix_lite", "vix_ema_60", "session_metadata",
                                 "ib_features", "session_high_low",
                                 "volume_profile", "all"])
    args = parser.parse_args()

    if args.engine in ("vix_lite", "all"):
        report = _test_vix_lite()
        if report and report["status"] != "PASS":
            sys.exit(1)

    if args.engine in ("vix_ema_60", "all"):
        report = _test_vix_ema_60()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("session_metadata", "all"):
        report = _test_session_metadata()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("ib_features", "all"):
        report = _test_ib_features()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("session_high_low", "all"):
        report = _test_session_high_low()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("volume_profile", "all"):
        report = _test_volume_profile()
        if report and not report.get("all_pass"):
            sys.exit(1)


if __name__ == "__main__":
    main()
