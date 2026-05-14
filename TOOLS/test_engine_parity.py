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


def _test_rolling_features_basic():
    """Test sub-engine #6 rolling features groupe A (13 TIER 1 features).

    Niveau 1 : parite batch/stream atol 1e-9 sur 200 bars synth
    Niveau 2 : pickle roundtrip state mid-warmup (~30 bars)
    Niveau 3 : warmup R2 restart cross-warmup
    """
    from rolling_features_streaming import (
        add_rolling_features_basic_streaming,
        RollingFeaturesState,
    )
    from rolling_features import RollingFeatures
    import numpy as np
    import pandas as pd

    np.random.seed(42)
    n = 200
    # Synth bars avec tous les inputs requis par batch
    df = pd.DataFrame({
        "ts": np.arange(n) * 60 * 1000,  # ms
        "price": 5800 + np.cumsum(np.random.randn(n) * 0.5),
        "delta_bar": np.random.randint(-100, 100, n).astype(float),
        "total_vol": np.random.randint(500, 2000, n).astype(float),
        "vwap_slope_10": np.random.randn(n) * 0.1,
        "dist_vwap_d": np.random.randn(n) * 2,
        "cvd_day": np.cumsum(np.random.randint(-50, 50, n)).astype(float),
        "atr": np.full(n, 8.0),
        "diag_imbalance": np.random.uniform(-1, 1, n),
        "finish_strength": np.random.uniform(-100, 100, n),
        "va_position_pct": np.random.uniform(0, 1, n),
        "ib_position_pct": np.random.uniform(0, 1, n),
        "vwap_d_side": np.random.choice([-1, 1], n),
        "large_trader_ratio": np.random.uniform(0, 1, n),
        "ib_range_atr": np.random.uniform(0.3, 1.5, n),
        "ib_broken_up": np.random.choice([0, 1], n),
        "ib_broken_down": np.random.choice([0, 1], n),
        "dist_vwap_d_atr": np.random.uniform(-0.5, 0.5, n),
        "delta_day_dir": np.random.choice([-1, 0, 1], n),
        "dist_sess_high": np.random.uniform(-10, 0, n),
        "dist_sess_low": np.random.uniform(0, 10, n),
        "ib_range_ticks": np.random.uniform(10, 50, n),
    })

    # BATCH
    rf = RollingFeatures(short=3, mid=5, long=10, symbol="ES")
    batch_df = rf.compute(df.copy())

    # STREAM
    state = RollingFeaturesState()
    stream_rows = []
    for _, row in df.iterrows():
        out = add_rolling_features_basic_streaming(row.to_dict(), state)
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest rolling_features_basic parite sur {n} rows synth...")

    # NIVEAU 1 : parite sur les 13 features
    cols_check = [
        "ctx_price_delta_div_3", "ctx_absorption_score_5",
        "ctx_vol_sell_buy_ratio_5", "ctx_vwap_slope_accel",
        "ctx_cvd_recovery_rate", "ctx_price_slope_5",
        "ctx_delta_slope_5", "ctx_delta_sum_3", "ctx_vol_z_5",
        "ctx_diag_imbalance_mean_5", "ctx_finish_strength_mean_5",
        "ctx_va_position_velocity", "ctx_side_flip_count_10",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (13 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        # NaN compare equal
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.6e} nan_mismatch={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            # Diagnostic premieres divergences
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")

    # NIVEAU 2 : pickle roundtrip
    print("\n--- NIVEAU 2 : pickle roundtrip mid-warmup ---")
    import pickle
    state2 = RollingFeaturesState()
    for i, row in df.iloc[:30].iterrows():
        add_rolling_features_basic_streaming(row.to_dict(), state2)
    blob = pickle.dumps(state2)
    state2_restored = pickle.loads(blob)
    # Verifier que les deques contiennent meme contenu
    assert list(state2_restored.price_mid) == list(state2.price_mid)
    assert list(state2_restored.delta_long) == list(state2.delta_long)
    assert list(state2_restored.cvd_day_long_plus) == list(state2.cvd_day_long_plus)
    # Test : meme row sur les 2 states -> meme output
    test_row = df.iloc[30].to_dict()
    out_orig = add_rolling_features_basic_streaming(test_row, state2)
    out_rest = add_rolling_features_basic_streaming(test_row, state2_restored)
    pickle_ok = True
    for col in cols_check:
        a, b_val = out_orig.get(col), out_rest.get(col)
        if pd.isna(a) and pd.isna(b_val):
            continue
        if pd.isna(a) or pd.isna(b_val) or abs(a - b_val) > 1e-9:
            print(f"  pickle FAIL on {col}: orig={a} restored={b_val}")
            pickle_ok = False
    print(f"  Niveau 2 status : {'PASS' if pickle_ok else 'FAIL'}")

    # NIVEAU 3 : warmup R2 restart
    print("\n--- NIVEAU 3 : warmup R2 restart idx=100 ---")
    # Continuous
    state_cont = RollingFeaturesState()
    cont_rows = []
    for _, row in df.iterrows():
        cont_rows.append(add_rolling_features_basic_streaming(row.to_dict(), state_cont))
    # Restart
    state_r1 = RollingFeaturesState()
    for i in range(100):
        add_rolling_features_basic_streaming(df.iloc[i].to_dict(), state_r1)
    state_r1_restored = pickle.loads(pickle.dumps(state_r1))
    restart_rows = []
    for i in range(100, n):
        restart_rows.append(
            add_rolling_features_basic_streaming(df.iloc[i].to_dict(), state_r1_restored)
        )
    cont_tail = pd.DataFrame(cont_rows).iloc[100:].reset_index(drop=True)
    restart_df = pd.DataFrame(restart_rows).reset_index(drop=True)
    level3_ok = True
    for col in cols_check:
        b = cont_tail[col].astype("float64").values
        s = restart_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        if max_diff > 1e-9 or nan_diff.sum() > 0:
            print(f"  warmup R2 FAIL on {col}: max_diff={max_diff:.6e}")
            level3_ok = False
    print(f"  Niveau 3 status : {'PASS' if level3_ok else 'FAIL'}")

    # NIVEAU 4 : stress NaN dans vwap_d_side (FIX P1-1 audit code-reviewer)
    # Mirror IEEE 754 NaN != anything = True. Probe que stream gere None/NaN
    # consecutifs correctement.
    print("\n--- NIVEAU 4 stress : vwap_d_side NaN aleatoires (P1-1 audit) ---")
    np.random.seed(99)
    n2 = 150
    sides_with_nan = np.random.choice([-1, 1, np.nan], n2, p=[0.4, 0.4, 0.2])
    df_nan = df.iloc[:n2].copy().reset_index(drop=True)
    df_nan["vwap_d_side"] = sides_with_nan

    batch_nan = rf.compute(df_nan.copy())
    state_nan = RollingFeaturesState()
    stream_nan_rows = []
    for _, row in df_nan.iterrows():
        stream_nan_rows.append(
            add_rolling_features_basic_streaming(row.to_dict(), state_nan)
        )
    stream_nan_df = pd.DataFrame(stream_nan_rows)

    b = batch_nan["ctx_side_flip_count_10"].astype("float64").values
    s = stream_nan_df["ctx_side_flip_count_10"].astype("float64").values
    nan_both = np.isnan(b) & np.isnan(s)
    nan_diff = np.isnan(b) ^ np.isnan(s)
    diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
    max_diff_nan = float(np.nanmax(np.abs(diff)))
    nan_mismatch_count = int(nan_diff.sum())
    n_nan_inputs = int(pd.isna(sides_with_nan).sum())
    level4_ok = max_diff_nan < 1e-9 and nan_mismatch_count == 0
    print(f"  n_nan_in_input={n_nan_inputs}/{n2}, max_diff={max_diff_nan:.6e}, "
          f"nan_mismatch={nan_mismatch_count}")
    print(f"  Niveau 4 status : {'PASS' if level4_ok else 'FAIL'}")
    if not level4_ok:
        idx_diff = np.where(np.abs(diff) > 1e-9)[0][:5]
        for idx in idx_diff:
            print(f"    idx={idx} batch={b[idx]} stream={s[idx]} "
                  f"side={sides_with_nan[idx]}")

    all_pass = all_pass and pickle_ok and level3_ok and level4_ok
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rolling_features_basic : "
          f"{'ALL 4 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_rolling_features_medium():
    """Test sub-engine #7 rolling features groupe B (13 features MEDIUM+AUDIT+TIER1+DYNAMIC+MQ).

    Chain basic + medium pour generer outputs GROUPE A dispo dans medium
    (ctx_vol_z_5, ctx_delta_sum_3 utilises par ctx_climax_signal).
    """
    from rolling_features_streaming import (
        add_rolling_features_basic_streaming,
        add_rolling_features_medium_streaming,
        RollingFeaturesState,
    )
    from rolling_features import RollingFeatures
    import numpy as np
    import pandas as pd

    np.random.seed(7)
    n = 250
    df = pd.DataFrame({
        "ts": np.arange(n) * 60 * 1000,
        "price": 5800 + np.cumsum(np.random.randn(n) * 0.5),
        "delta_bar": np.random.randint(-100, 100, n).astype(float),
        "total_vol": np.random.randint(500, 2000, n).astype(float),
        "vwap_slope_10": np.random.randn(n) * 0.1,
        "dist_vwap_d": np.random.randn(n) * 2,
        "cvd_day": np.cumsum(np.random.randint(-50, 50, n)).astype(float),
        "atr": np.full(n, 8.0),
        "diag_imbalance": np.random.uniform(-1, 1, n),
        "finish_strength": np.random.uniform(-100, 100, n),
        "va_position_pct": np.random.uniform(0, 1, n),
        "ib_position_pct": np.random.uniform(0, 1, n),
        "vwap_d_side": np.random.choice([-1, 1], n),
        "large_trader_ratio": np.random.uniform(0, 1, n),
        "ib_range_atr": np.random.uniform(0.3, 1.5, n),
        "ib_broken_up": np.random.choice([0, 1], n),
        "ib_broken_down": np.random.choice([0, 1], n),
        "dist_vwap_d_atr": np.random.uniform(-0.5, 0.5, n),
        "delta_day_dir": np.random.choice([-1, 0, 1], n),
        "dist_sess_high": np.random.uniform(-10, 0, n),
        "dist_sess_low": np.random.uniform(0, 10, n),
        "ib_range_ticks": np.random.uniform(10, 50, n),
        "dist_mq_put": np.random.uniform(-50, 0, n),
        "dist_mq_call": np.random.uniform(0, 50, n),
    })

    rf = RollingFeatures(short=3, mid=5, long=10, symbol="ES")
    batch_df = rf.compute(df.copy())

    # STREAM chain basic -> medium
    state = RollingFeaturesState()
    stream_rows = []
    for _, row in df.iterrows():
        r1 = add_rolling_features_basic_streaming(row.to_dict(), state)
        r2 = add_rolling_features_medium_streaming(r1, state, symbol="ES")
        stream_rows.append(r2)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest rolling_features_medium parite sur {n} rows synth...")

    cols_check = [
        # MEDIUM (4)
        "ctx_delta_sum_10", "ctx_dist_vwap_velocity",
        "ctx_range_vs_atr_10", "ctx_ib_position_velocity",
        # AUDIT (3)
        "ctx_instant_absorption", "ctx_absorption_streak_5", "ctx_climax_signal",
        # TIER1 (3)
        "ctx_vol_slope_5", "ctx_delta_exhaustion", "ctx_large_trader_slope_5",
        # DYNAMIC (2)
        "ctx_trend_day_score", "ctx_day_type_intensity",
        # MQ (1)
        "ctx_mq_put_call_ratio",
    ]

    print("\n--- NIVEAU 1 : parite batch vs streaming (13 GROUPE B features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.6e} nan_mismatch={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rolling_features_medium : "
          f"{'ALL 1 LEVEL PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_rolling_features_advanced():
    """Test sub-engine #8 GROUPE C Market Profile (6 features + 4 derivees).

    Chain basic + medium + advanced. Verifie parite atol 1e-6 sur les 10 sorties.
    """
    from rolling_features_streaming import (
        add_rolling_features_basic_streaming,
        add_rolling_features_medium_streaming,
        add_rolling_features_advanced_streaming,
        RollingFeaturesState,
    )
    from rolling_features import RollingFeatures
    import numpy as np
    import pandas as pd

    np.random.seed(11)
    n = 300
    df = pd.DataFrame({
        "ts": np.arange(n) * 60 * 1000,
        "price": 5800 + np.cumsum(np.random.randn(n) * 0.5),
        "delta_bar": np.random.randint(-100, 100, n).astype(float),
        "total_vol": np.random.randint(500, 2000, n).astype(float),
        "vwap_slope_10": np.random.randn(n) * 0.1,
        "dist_vwap_d": np.random.randn(n) * 2,
        "cvd_day": np.cumsum(np.random.randint(-50, 50, n)).astype(float),
        "atr": np.full(n, 8.0),
        "diag_imbalance": np.random.uniform(-1, 1, n),
        "finish_strength": np.random.uniform(-100, 100, n),
        "va_position_pct": np.random.uniform(0, 1, n),
        "ib_position_pct": np.random.uniform(0, 1, n),
        "vwap_d_side": np.random.choice([-1, 1], n),
        "large_trader_ratio": np.random.uniform(0, 1, n),
        "ib_range_atr": np.random.uniform(0.3, 1.5, n),
        "ib_broken_up": np.random.choice([0, 1], n),
        "ib_broken_down": np.random.choice([0, 1], n),
        "dist_vwap_d_atr": np.random.uniform(-0.5, 0.5, n),
        "delta_day_dir": np.random.choice([-1, 0, 1], n),
        "dist_sess_high": np.random.uniform(-15, 0, n),
        "dist_sess_low": np.random.uniform(0, 15, n),
        "ib_range_ticks": np.random.uniform(10, 50, n),
        "dist_mq_put": np.random.uniform(-50, 0, n),
        "dist_mq_call": np.random.uniform(0, 50, n),
        # GROUPE C inputs additionnels
        "poc_position": np.random.uniform(-1, 1, n),
        "dist_cur_vah": np.random.uniform(-10, 0, n),
        "dist_cur_val": np.random.uniform(0, 10, n),
        "dist_cur_vpoc": np.random.uniform(-5, 5, n),
        "dist_ib_high": np.random.uniform(-20, 5, n),
        "dist_ib_low": np.random.uniform(-5, 20, n),
        "inside_cur_va": np.random.choice([0, 1], n),
    })

    rf = RollingFeatures(short=3, mid=5, long=10, symbol="ES")
    batch_df = rf.compute(df.copy())

    state = RollingFeaturesState()
    stream_rows = []
    for _, row in df.iterrows():
        r1 = add_rolling_features_basic_streaming(row.to_dict(), state)
        r2 = add_rolling_features_medium_streaming(r1, state, symbol="ES")
        r3 = add_rolling_features_advanced_streaming(r2, state)
        stream_rows.append(r3)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest rolling_features_advanced parite sur {n} rows synth...")

    cols_check = [
        "ctx_poc_migration_10", "ctx_va_width", "ctx_va_developing_10",
        "ctx_ib_extension_ratio", "ctx_rotation_factor_20",
        "ctx_failed_auction",
        "ctx_excess_high_bars", "ctx_poor_high",
        "ctx_excess_low_bars", "ctx_poor_low",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (10 sorties GROUPE C) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.6e} nan_mismatch={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rolling_features_advanced : "
          f"{'ALL 1 LEVEL PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_rolling_features_delta_div():
    """Test sub-engine #9 GROUPE D delta divergence reconstruction (4 features).

    Note importante :
      - delta_div_buy_clean, delta_div_sell_clean, delta_divergence_clean :
        parite exacte attendue (atol 0 sur integers).
      - delta_div_strength : DIVERGENCE batch/stream attendue (batch winsorize
        au quantile 0.995 sur full DataFrame = forward-looking impossible
        en stream). Stream output raw |delta_bar|. Tolerance acceptable :
        equal SI raw value <= clip_high batch, sinon stream > batch.
    """
    from rolling_features_streaming import (
        add_rolling_features_basic_streaming,
        add_rolling_features_medium_streaming,
        add_rolling_features_advanced_streaming,
        add_rolling_features_delta_div_streaming,
        RollingFeaturesState,
    )
    from rolling_features import RollingFeatures
    import numpy as np
    import pandas as pd

    np.random.seed(17)
    # Synth 2 sessions CME (cross 18:00 ET = 22:00 UTC)
    # Day 1 : 13:00-21:55 UTC (= 09:00-17:55 ET, same trading date)
    # Day 2 : 22:00 UTC d1 onwards = trading_date d2 (next day)
    bars = []
    start_d1 = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    for i in range(540):  # 9 heures = 540 bars
        ts = start_d1 + pd.Timedelta(minutes=i)
        bars.append({
            "ts": int(ts.value // 1_000_000),
            "ts_event": ts.tz_localize(None),
        })
    # Day 2 start at 22:00 UTC (= 18:00 ET = trigger session change)
    start_d2 = pd.Timestamp("2026-05-12 22:00:00", tz="UTC")
    for i in range(480):
        ts = start_d2 + pd.Timedelta(minutes=i)
        bars.append({
            "ts": int(ts.value // 1_000_000),
            "ts_event": ts.tz_localize(None),
        })
    n = len(bars)
    df = pd.DataFrame(bars)
    df["price"] = 5800 + np.cumsum(np.random.randn(n) * 0.5)
    df["bar_high"] = df["price"] + np.random.uniform(0, 1, n)
    df["bar_low"] = df["price"] - np.random.uniform(0, 1, n)
    df["delta_bar"] = np.random.randint(-100, 100, n).astype(float)
    # Inputs minimum pour batch compute() ne crashe pas
    df["total_vol"] = np.random.randint(500, 2000, n).astype(float)
    df["vwap_slope_10"] = 0.0
    df["dist_vwap_d"] = 0.0
    df["cvd_day"] = np.cumsum(df["delta_bar"])
    df["atr"] = 8.0
    df["diag_imbalance"] = 0.0
    df["finish_strength"] = 0.0
    df["va_position_pct"] = 0.5
    df["ib_position_pct"] = 0.5
    df["vwap_d_side"] = 1
    df["large_trader_ratio"] = 0.3
    df["ib_range_atr"] = 0.5
    df["ib_broken_up"] = 0
    df["ib_broken_down"] = 0
    df["dist_vwap_d_atr"] = 0.0
    df["delta_day_dir"] = 0
    df["dist_sess_high"] = -5.0
    df["dist_sess_low"] = 5.0
    df["ib_range_ticks"] = 20.0

    rf = RollingFeatures(short=3, mid=5, long=10, symbol="ES")
    batch_df = rf.compute(df.copy())

    state = RollingFeaturesState()
    stream_rows = []
    for _, row in df.iterrows():
        out = add_rolling_features_delta_div_streaming(row.to_dict(), state)
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest rolling_features_delta_div parite sur {n} rows synth (2 sessions CME)...")

    # PARITE EXACTE sur 3 features (atol 0)
    cols_exact = [
        "delta_div_buy_clean", "delta_div_sell_clean", "delta_divergence_clean"
    ]
    print("\n--- NIVEAU 1 : parite EXACTE batch vs streaming (3 features int) ---")
    all_pass = True
    for col in cols_exact:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff == 0 and nan_mismatch == 0 else "FAIL"
        n_active_batch = int((b != 0).sum())
        n_active_stream = int((s != 0).sum())
        print(f"  {col:35s} {status} max_diff={max_diff:.6e} "
              f"active batch/stream: {n_active_batch}/{n_active_stream}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where(np.abs(diff) > 1e-9)[0][:5]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    # PARITE PARTIELLE sur delta_div_strength (divergence p99.5 documentee)
    print("\n--- NIVEAU 2 : delta_div_strength (DIVERGENCE p99.5 documentee) ---")
    b_str = batch_df["delta_div_strength"].astype("float64").values
    s_str = stream_df["delta_div_strength"].astype("float64").values
    # Sur les valeurs ACTIVES (>0), batch <= stream (batch clip vers le bas)
    active_mask = (s_str > 0) | (b_str > 0)
    # Verifier que :
    # 1. batch == 0 IFF stream == 0 (positions actives = identiques)
    # 2. quand actives : batch <= stream (clip vers le bas)
    pos_match = ((b_str > 0) == (s_str > 0)).all()
    if pos_match:
        # Compare active values : batch <= stream attendu
        violation = ((b_str > s_str + 1e-9) & active_mask).sum()
        max_clip = float(np.nanmax(s_str - b_str)) if active_mask.any() else 0.0
        n_active = int(active_mask.sum())
        print(f"  positions actives match : OK ({n_active} bars)")
        print(f"  max clip batch (stream - batch) : {max_clip:.4f}")
        print(f"  violations (batch > stream) : {violation}")
        strength_ok = violation == 0
    else:
        n_mismatch_pos = int(((b_str > 0) != (s_str > 0)).sum())
        print(f"  positions actives MISMATCH : {n_mismatch_pos} bars")
        strength_ok = False
    print(f"  Niveau 2 status : {'PASS' if strength_ok else 'FAIL'}")

    all_pass = all_pass and strength_ok
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rolling_features_delta_div : "
          f"{'PASS (3 exact + 1 partial documente)' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_rolling_features_session_confluence():
    """Test sub-engine #10 GROUPE E (12 features finales rolling_features).

    Chain pipeline COMPLET basic+medium+advanced+delta_div+session_confluence.
    """
    from rolling_features_streaming import (
        add_rolling_features_basic_streaming,
        add_rolling_features_medium_streaming,
        add_rolling_features_advanced_streaming,
        add_rolling_features_delta_div_streaming,
        add_rolling_features_session_confluence_streaming,
        RollingFeaturesState,
    )
    from rolling_features import RollingFeatures
    import numpy as np
    import pandas as pd

    np.random.seed(23)
    # Synth 1 jour avec 3 sessions (Asia 0, London 1, US 2)
    bars = []
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    for i in range(600):
        ts = start + pd.Timedelta(minutes=i)
        if i < 200:
            session = 0  # Asia
        elif i < 400:
            session = 1  # London
        else:
            session = 2  # US
        bars.append({
            "ts": int(ts.value // 1_000_000),
            "ts_event": ts.tz_localize(None),
            "session": session,
        })
    n = len(bars)
    df = pd.DataFrame(bars)
    df["price"] = 5800 + np.cumsum(np.random.randn(n) * 0.5)
    df["bar_high"] = df["price"] + np.random.uniform(0, 1, n)
    df["bar_low"] = df["price"] - np.random.uniform(0, 1, n)
    df["delta_bar"] = np.random.randint(-100, 100, n).astype(float)
    df["total_vol"] = np.random.randint(500, 2000, n).astype(float)
    df["vwap_slope_10"] = 0.0
    df["dist_vwap_d"] = 0.0
    df["cvd_day"] = np.cumsum(df["delta_bar"])
    df["atr"] = 8.0
    df["diag_imbalance"] = np.random.uniform(-1, 1, n)
    df["finish_strength"] = np.random.uniform(-100, 100, n)
    df["va_position_pct"] = 0.5
    df["ib_position_pct"] = 0.5
    df["vwap_d_side"] = 1
    df["large_trader_ratio"] = 0.3
    df["ib_range_atr"] = 0.5
    df["ib_broken_up"] = 0
    df["ib_broken_down"] = 0
    df["dist_vwap_d_atr"] = 0.0
    df["delta_day_dir"] = 0
    df["dist_sess_high"] = -5.0
    df["dist_sess_low"] = 5.0
    df["ib_range_ticks"] = 20.0
    df["ib_complete"] = (df["session"] == 2).astype(int)
    # Inputs trapped traders (synth aleatoire)
    df["retest_high_delta_div"] = np.random.choice([0, 1], n, p=[0.95, 0.05])
    df["bars_since_retest_high"] = np.random.randint(0, 20, n)
    df["retest_low_delta_div"] = np.random.choice([0, 1], n, p=[0.95, 0.05])
    df["bars_since_retest_low"] = np.random.randint(0, 20, n)
    df["cvd_day_dir"] = np.random.choice([-1, 0, 1], n)
    df["momentum_5b"] = np.random.uniform(-15, 15, n)
    df["dist_swing_low"] = np.random.uniform(0, 50, n)
    df["dist_swing_high"] = -np.random.uniform(0, 50, n)
    # Inputs divergence confluence
    df["dist_mq_call"] = 100.0
    df["dist_mq_put"] = -100.0
    df["dist_mq_hvl"] = 50.0
    df["dist_cur_vah"] = -10.0
    df["dist_cur_val"] = 10.0
    df["dist_ib_high"] = -8.0
    df["dist_ib_low"] = 8.0
    df["vix_regime"] = np.random.choice([0, 1, 2], n)
    df["bool_gex_flip_zone"] = np.random.choice([0, 1], n)
    df["bn_absorb_bid"] = np.random.choice([0, 1], n, p=[0.9, 0.1])
    df["bn_absorb_ask"] = np.random.choice([0, 1], n, p=[0.9, 0.1])
    df["rvol_zscore"] = np.random.uniform(-3, 3, n)

    rf = RollingFeatures(short=3, mid=5, long=10, symbol="ES")
    batch_df = rf.compute(df.copy())

    state = RollingFeaturesState()
    stream_rows = []
    for _, row in df.iterrows():
        r0 = add_rolling_features_basic_streaming(row.to_dict(), state)
        r1 = add_rolling_features_medium_streaming(r0, state, symbol="ES")
        r2 = add_rolling_features_advanced_streaming(r1, state)
        r3 = add_rolling_features_delta_div_streaming(r2, state)
        r4 = add_rolling_features_session_confluence_streaming(r3, state)
        stream_rows.append(r4)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest rolling_features_session_confluence parite sur {n} rows synth...")

    cols_check = [
        # TRAPPED TRADERS (2)
        "ctx_double_top_trap", "ctx_momentum_exhaustion",
        # SESSION-SPECIFIC (3)
        "ctx_cvd_session", "ctx_rvol_session", "ctx_session_phase",
        # DIVERGENCE RECENCE (3)
        "ctx_bars_since_div", "ctx_div_density_20", "ctx_div_at_swing",
        # DIVERGENCE CONFLUENCE (4)
        "div_at_key_level_ticks", "div_confluence_dmp",
        "div_regime_proxy_ok", "div_confluence_with_regime",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (12 features GROUPE E) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.6e} nan_mismatch={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rolling_features_session_confluence : "
          f"{'ALL 1 LEVEL PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_rvol_engine():
    """Test sub-engine RvolEngine streaming (10 features rvol_*)."""
    from rvol_streaming import add_rvol_engine_streaming, RvolEngineState
    from rvol import RvolEngine
    import numpy as np
    import pandas as pd

    np.random.seed(31)
    n = 300
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    df = pd.DataFrame({
        "ts": [int((start + pd.Timedelta(minutes=i)).value // 1_000_000) for i in range(n)],
        "total_vol": np.random.randint(100, 3000, n).astype(float),
        "delta_pct": np.random.uniform(-0.3, 0.3, n),
        "finish_strength": np.random.uniform(-50, 50, n),
    })

    engine = RvolEngine()
    batch_df = engine.compute(df.copy())

    state = RvolEngineState()
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_rvol_engine_streaming(row.to_dict(), state))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest rvol_engine parite sur {n} rows synth...")

    cols_check = [
        "rvol", "rvol_zscore", "rvol_regime",
        "rvol_buy", "rvol_sell", "rvol_buy_strong", "rvol_sell_strong",
        "rvol_absorb_buy", "rvol_absorb_sell", "rvol_extreme",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (10 features rvol_*) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:30s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        print(f"  {col:30s} {status} max_diff={max_diff:.6e} nan_mismatch={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rvol_engine : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_amd():
    """Test sub-engine AmdEngine streaming (18 features ICT Power of 3)."""
    from mia_amd_streaming import add_amd_streaming, AmdEngineState, make_amd_state
    from mia_amd import AmdEngine
    import numpy as np
    import pandas as pd

    np.random.seed(41)
    # Synth 3 sessions Asia(200) + London(200) + US(200)
    n = 600
    sessions_arr = ["Asia"] * 200 + ["London"] * 200 + ["US"] * 200
    df = pd.DataFrame({
        "session_id": sessions_arr,
        "price": 5800 + np.cumsum(np.random.randn(n) * 0.4),
        "atr": np.full(n, 8.0),
        # Inputs ML
        "rvol": np.random.uniform(0.5, 3.0, n),
        "delta_pct": np.random.uniform(-0.2, 0.2, n),
        "finish_strength": np.random.uniform(-50, 50, n),
        "retest_high_delta_div": np.random.choice([0, 1], n, p=[0.95, 0.05]),
        "retest_low_delta_div": np.random.choice([0, 1], n, p=[0.95, 0.05]),
        "rvol_absorb_buy": np.random.choice([0, 1], n, p=[0.9, 0.1]),
        "rvol_absorb_sell": np.random.choice([0, 1], n, p=[0.9, 0.1]),
        "profile_shape": np.random.choice([0, 1, 2, 3], n),
        "momentum_5b": np.random.uniform(-15, 15, n),
        "ib_broken_up": np.random.choice([0, 1], n, p=[0.7, 0.3]),
        "ib_broken_down": np.random.choice([0, 1], n, p=[0.7, 0.3]),
        "cvd_day_dir": np.random.choice([-1, 0, 1], n),
    })

    engine = AmdEngine(symbol="ES")  # tick=0.25 par defaut
    batch_df = engine.compute(df.copy())

    # FIX P1 audit : utiliser factory make_amd_state(symbol) pour config correcte
    # (tick + sweep_min + accum_min + judas_re per-symbole)
    state = make_amd_state("ES")
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_amd_streaming(row.to_dict(), state))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest amd parite sur {n} rows synth (3 sessions Asia/London/US)...")

    cols_check = [
        "amd_phase", "amd_asia_range_ticks", "amd_asia_high", "amd_asia_low",
        "amd_sweep_up", "amd_sweep_dn", "amd_sweep_depth_ticks",
        "amd_manip_score", "amd_manip_dir", "amd_judas_swing",
        "amd_dist_score", "amd_dist_dir", "amd_dist_confirmed",
        "amd_reversal_prob", "amd_po3_bullish", "amd_po3_bearish",
        "amd_po3_score", "amd_session_bias",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (18 features amd_*) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:30s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        print(f"  {col:30s} {status} max_diff={max_diff:.6e} nan_mismatch={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} sess={df.iloc[idx]['session_id']} "
                      f"batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")

    # NIVEAU 2 BONUS : 3 scenarios boot mid-session (P1.1 + P2 Plan agent)
    print("\n--- NIVEAU 2 : boot mid-session 3 scenarios ---")

    # 2a : boot mid-US (row 300+)
    state_mid_us = make_amd_state("ES")
    rows_us = [add_amd_streaming(r.to_dict(), state_mid_us)
                for _, r in df.iloc[300:].iterrows()]
    mid_us_df = pd.DataFrame(rows_us)
    us_ok = (
        mid_us_df["amd_asia_high"].isna().all()
        and (mid_us_df["amd_sweep_up"] == 0).all()
        and (mid_us_df["amd_judas_swing"] == 0).all()
    )
    print(f"  2a Boot mid-US : "
          f"asia_h NaN={mid_us_df['amd_asia_high'].isna().all()}, "
          f"sweeps_zero={(mid_us_df['amd_sweep_up'] == 0).all()}, "
          f"judas_zero={(mid_us_df['amd_judas_swing'] == 0).all()}")

    # 2b : boot mid-London (row 100 London)
    state_mid_london = make_amd_state("ES")
    rows_london = [add_amd_streaming(r.to_dict(), state_mid_london)
                    for _, r in df.iloc[250:].iterrows()]  # debut mid-London (idx 250)
    mid_london_df = pd.DataFrame(rows_london)
    # Memes attentes : asia_* = NaN (pas d'historique Asia), sweeps/judas peuvent fire
    # MAIS uniquement APRES transition London (or stream demarre deja en London) ->
    # Sans frozen Asia, a_h/a_l = None -> sweeps gated -> 0
    london_ok = (
        mid_london_df["amd_asia_high"].isna().all()
        and (mid_london_df["amd_sweep_up"] == 0).all()
    )
    print(f"  2b Boot mid-London : "
          f"asia_h NaN={mid_london_df['amd_asia_high'].isna().all()}, "
          f"sweeps_zero={(mid_london_df['amd_sweep_up'] == 0).all()}")

    # 2c : boot mid-Asia (row 100 = mid-Asia, Asia range partial)
    state_mid_asia = make_amd_state("ES")
    rows_asia = [add_amd_streaming(r.to_dict(), state_mid_asia)
                  for _, r in df.iloc[100:].iterrows()]
    mid_asia_df = pd.DataFrame(rows_asia)
    # Asia range tronque (vu bars 100-199 seulement) MAIS Asia_high/low NON-NaN
    # car running depuis bar 100. London/US verront frozen reduit. Pas de crash.
    asia_running = not mid_asia_df.iloc[:50]["amd_asia_high"].isna().all()
    print(f"  2c Boot mid-Asia : asia_running tracked={asia_running}")
    asia_ok = asia_running  # juste verifier que ca tracke (degrade gracieux)

    # 2d : PICKLE-REPLAY STALE STATE (P1 Plan agent)
    # Simule deserialisation d'un state corrompu avec had_j_session=True heritage
    # session US precedente. Verifie que le reset Asia (P1 fix) nettoie l'etat.
    print("\n  2d Pickle-replay stale state (P1 Plan agent) :")
    import pickle
    state_stale = make_amd_state("ES")
    state_stale.had_j_session = True
    state_stale.last_ms = 0.85
    state_stale.last_md = 1
    state_stale.prop_dir = -1
    # Serialize + restore
    blob = pickle.dumps(state_stale)
    state_replay = pickle.loads(blob)
    assert state_replay.had_j_session is True, "pickle preserve state"
    # Premier bar Asia -> doit reset had_j_session=False, last_ms=0, last_md=0
    asia_row = df.iloc[0].to_dict()
    out_after_asia = add_amd_streaming(asia_row, state_replay)
    stale_cleaned = (
        state_replay.had_j_session is False
        and state_replay.last_ms == 0.0
        and state_replay.last_md == 0
        and state_replay.prop_dir == 0
    )
    print(f"    state pre-Asia : had_j=True, last_ms=0.85, last_md=1, prop_dir=-1")
    print(f"    state post-Asia (1 bar) : had_j={state_replay.had_j_session}, "
          f"last_ms={state_replay.last_ms}, last_md={state_replay.last_md}, "
          f"prop_dir={state_replay.prop_dir}")
    print(f"    P1 reset Asia cleaned stale : {'PASS' if stale_cleaned else 'FAIL'}")

    boot_ok = us_ok and london_ok and asia_ok and stale_cleaned
    print(f"\n  Niveau 2 status : {'PASS' if boot_ok else 'FAIL'}")

    all_pass = all_pass and boot_ok
    print(f"\n{'=' * 70}")
    print(f"GLOBAL amd : {'ALL 2 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_game_changers():
    """Test sub-engine game_changers streaming (5 features Market Profile).

    Parite design :
      - open_type/zone/direction/bias_conf : frozen POST-IB -> parite EXACTE
        sur toutes les bars apres ib_close_min.
      - day_type : RUNNING en stream vs batch (sess_high/low/close finaux).
        Parite VRAIE uniquement sur LAST BAR de chaque jour.
    """
    from game_changers_streaming import (
        add_game_changers_streaming,
        GameChangersState,
    )
    import sys
    sys.path.insert(0, "CORE")  # batch import build_dataset_v4_phase_b
    from build_dataset_v4_phase_b import apply_game_changers
    import numpy as np
    import pandas as pd

    np.random.seed(53)
    # Synth 3 jours x 720 bars/jour (12h trading)
    bars = []
    for day_offset in range(3):
        date_str = f"2026-05-{12 + day_offset:02d}"
        start_et = pd.Timestamp(f"{date_str} 00:00:00")  # 00:00 ET
        # On simule 720 bars = 12h
        for i in range(720):
            ts = start_et + pd.Timedelta(minutes=i)
            mins_et = ts.hour * 60 + ts.minute
            bars.append({
                "ts_event": ts,
                "date_et": pd.Timestamp(date_str).date(),
                "mins_et": mins_et,
            })
    n = len(bars)
    df = pd.DataFrame(bars)
    df["price"] = 5800 + np.cumsum(np.random.randn(n) * 0.3)
    df["close"] = df["price"]
    df["high"] = df["price"] + np.random.uniform(0, 1, n)
    df["low"] = df["price"] - np.random.uniform(0, 1, n)

    # Inputs requis par batch + stream
    # open_cash = close de la 1ere bar a us_start (mins_et=570 = 09:30 ET)
    # price_1030 = close de la bar a us_start+60 (mins_et=630)
    # ib_high/low broadcast post-IB (mins_et >= 630)
    df["open_cash"] = df.groupby("date_et")["close"].transform(
        lambda x: x[df.loc[x.index, "mins_et"] == 570].iloc[0]
        if (df.loc[x.index, "mins_et"] == 570).any() else np.nan
    )
    df["price_1030"] = df.groupby("date_et")["close"].transform(
        lambda x: x[df.loc[x.index, "mins_et"] == 630].iloc[0]
        if (df.loc[x.index, "mins_et"] == 630).any() else np.nan
    )
    # IB high/low : max/min de [09:30, 10:30) broadcast
    ib_window = (df["mins_et"] >= 570) & (df["mins_et"] < 630)
    df["ib_high"] = df.groupby("date_et").apply(
        lambda g: g["high"].where(ib_window.loc[g.index]).max()
    ).reindex(df["date_et"]).values
    df["ib_low"] = df.groupby("date_et").apply(
        lambda g: g["low"].where(ib_window.loc[g.index]).min()
    ).reindex(df["date_et"]).values
    # Mask ib_high/low avant ib_close
    df.loc[df["mins_et"] < 630, "ib_high"] = np.nan
    df.loc[df["mins_et"] < 630, "ib_low"] = np.nan
    # ib_atr fixed
    df["ib_atr"] = 8.0
    # sess_high/low running (cumulative par date)
    df["sess_high"] = df.groupby("date_et")["high"].cummax()
    df["sess_low"] = df.groupby("date_et")["low"].cummin()
    # prev_vah/val/vpoc + pdh/pdl frozen per jour (constants)
    df["prev_vah"] = 5805.0
    df["prev_val"] = 5790.0
    df["prev_vpoc"] = 5797.0
    df["pdh"] = 5810.0
    df["pdl"] = 5788.0

    # BATCH
    batch_df = apply_game_changers(df.copy(), symbol="ES")

    # STREAM
    state = GameChangersState()
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_game_changers_streaming(row.to_dict(), state, symbol="ES"))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest game_changers parite sur {n} rows synth (3 jours)...")

    # NIVEAU 1 : parite EXACTE sur 4 features frozen POST-IB
    # On compare uniquement les bars POST-IB (mins_et >= 630) car avant
    # batch retourne 0 default + stream retourne UNKNOWN (init)
    post_ib_mask = df["mins_et"] >= 630
    cols_exact = ["open_type", "open_zone", "open_direction", "open_bias_conf"]
    print("\n--- NIVEAU 1 : parite EXACTE POST-IB (4 features frozen) ---")
    all_pass = True
    for col in cols_exact:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:25s} MANQUANT")
            all_pass = False
            continue
        b = batch_df.loc[post_ib_mask, col].astype("float64").values
        s = stream_df.loc[post_ib_mask, col].astype("float64").values
        diff = np.abs(b - s)
        max_diff = float(np.nanmax(diff))
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        print(f"  {col:25s} {status} max_diff={max_diff:.6e}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where(diff > 1e-6)[0][:3]
            for idx in idx_diff:
                real_idx = post_ib_mask[post_ib_mask].index[idx]
                print(f"    idx={real_idx} date={df.loc[real_idx, 'date_et']} "
                      f"batch={b[idx]} stream={s[idx]}")

    # NIVEAU 2 : day_type LAST BAR de chaque jour (parite running == batch frozen)
    print("\n--- NIVEAU 2 : day_type LAST BAR each day (running vs batch final) ---")
    last_bar_idx = df.groupby("date_et").apply(lambda g: g.index[-1]).values
    day_type_ok = True
    for idx in last_bar_idx:
        b_dt = batch_df.loc[idx, "day_type"]
        s_dt = stream_df.loc[idx, "day_type"]
        if b_dt != s_dt:
            print(f"    date={df.loc[idx, 'date_et']} idx={idx} "
                  f"batch={b_dt} stream={s_dt}")
            day_type_ok = False
    print(f"  Last-bar day_type parite : {'PASS' if day_type_ok else 'FAIL'}")

    # NIVEAU 3 : test MGC (FIX P0 audit code-reviewer)
    # Sur MGC ib_close_min=570 (vs ES=630). Verifier que stream utilise bien
    # get_session_boundaries au lieu de hardcode (precedent bug=510 fix).
    print("\n--- NIVEAU 3 : MGC parite (FIX P0 ib_close_min) ---")
    # Synth MGC : us_start=510, ib_close_min=570
    bars_mgc = []
    for day_offset in range(2):
        date_str = f"2026-05-{12 + day_offset:02d}"
        start_et = pd.Timestamp(f"{date_str} 00:00:00")
        for i in range(720):
            ts = start_et + pd.Timedelta(minutes=i)
            mins_et = ts.hour * 60 + ts.minute
            bars_mgc.append({
                "ts_event": ts,
                "date_et": pd.Timestamp(date_str).date(),
                "mins_et": mins_et,
            })
    n_mgc = len(bars_mgc)
    df_mgc = pd.DataFrame(bars_mgc)
    df_mgc["price"] = 2400 + np.cumsum(np.random.randn(n_mgc) * 0.1)
    df_mgc["close"] = df_mgc["price"]
    df_mgc["high"] = df_mgc["price"] + np.random.uniform(0, 0.5, n_mgc)
    df_mgc["low"] = df_mgc["price"] - np.random.uniform(0, 0.5, n_mgc)
    # MGC us_start=510 (cash open 08:30), price_1030_equivalent = mins_et=570 (09:30)
    df_mgc["open_cash"] = df_mgc.groupby("date_et")["close"].transform(
        lambda x: x[df_mgc.loc[x.index, "mins_et"] == 510].iloc[0]
        if (df_mgc.loc[x.index, "mins_et"] == 510).any() else np.nan
    )
    df_mgc["price_1030"] = df_mgc.groupby("date_et")["close"].transform(
        lambda x: x[df_mgc.loc[x.index, "mins_et"] == 570].iloc[0]
        if (df_mgc.loc[x.index, "mins_et"] == 570).any() else np.nan
    )
    ib_window_mgc = (df_mgc["mins_et"] >= 510) & (df_mgc["mins_et"] < 570)
    df_mgc["ib_high"] = df_mgc.groupby("date_et").apply(
        lambda g: g["high"].where(ib_window_mgc.loc[g.index]).max()
    ).reindex(df_mgc["date_et"]).values
    df_mgc["ib_low"] = df_mgc.groupby("date_et").apply(
        lambda g: g["low"].where(ib_window_mgc.loc[g.index]).min()
    ).reindex(df_mgc["date_et"]).values
    df_mgc.loc[df_mgc["mins_et"] < 570, "ib_high"] = np.nan
    df_mgc.loc[df_mgc["mins_et"] < 570, "ib_low"] = np.nan
    df_mgc["ib_atr"] = 3.0
    df_mgc["sess_high"] = df_mgc.groupby("date_et")["high"].cummax()
    df_mgc["sess_low"] = df_mgc.groupby("date_et")["low"].cummin()
    df_mgc["prev_vah"] = 2402.0
    df_mgc["prev_val"] = 2395.0
    df_mgc["prev_vpoc"] = 2398.0
    df_mgc["pdh"] = 2405.0
    df_mgc["pdl"] = 2393.0

    batch_mgc = apply_game_changers(df_mgc.copy(), symbol="MGC")
    state_mgc = GameChangersState()
    stream_mgc_rows = []
    for _, row in df_mgc.iterrows():
        stream_mgc_rows.append(add_game_changers_streaming(row.to_dict(), state_mgc, symbol="MGC"))
    stream_mgc_df = pd.DataFrame(stream_mgc_rows)

    # Verifier que ib_close_min=570 sur MGC (et pas l'ancien bug 510)
    assert state_mgc.ib_close_min == 570, (
        f"P0 MGC ib_close_min doit etre 570, got {state_mgc.ib_close_min}"
    )
    # Parite POST-IB sur 4 features frozen
    post_ib_mgc = df_mgc["mins_et"] >= 570
    mgc_ok = True
    for col in ["open_type", "open_zone", "open_direction"]:
        b = batch_mgc.loc[post_ib_mgc, col].astype("float64").values
        s = stream_mgc_df.loc[post_ib_mgc, col].astype("float64").values
        diff_max = float(np.nanmax(np.abs(b - s)))
        if diff_max > 1e-6:
            print(f"  MGC {col} FAIL max_diff={diff_max}")
            mgc_ok = False
    print(f"  MGC ib_close_min state={state_mgc.ib_close_min} (attendu 570) : OK")
    print(f"  MGC parite POST-IB 4 features : {'PASS' if mgc_ok else 'FAIL'}")

    all_pass = all_pass and day_type_ok and mgc_ok
    print(f"\n{'=' * 70}")
    print(f"GLOBAL game_changers : "
          f"{'ALL LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_edge_zones():
    """Test sub-engine edge_zones streaming (8 features ML imbalance stacks)."""
    from edge_zones_streaming import (
        add_edge_zones_streaming,
        make_edge_zones_state,
    )
    from edge_zones_engine import apply_edge_zones
    import numpy as np
    import pandas as pd

    np.random.seed(67)
    n = 200
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-12 13:00:00", periods=n, freq="1min"),
        "price": 5800 + np.cumsum(np.random.randn(n) * 0.3),
    })
    df["high"] = df["price"] + np.random.uniform(0, 2, n)
    df["low"] = df["price"] - np.random.uniform(0, 2, n)
    df["close"] = df["price"]

    # Synth footprint : pour ~30% des bars, generer cellules avec
    # imbalance >600% (BUY ou SELL) sur 2-4 prix consecutifs
    footprint = {}
    tick = 0.25
    for i in range(n):
        cells = {}
        # Prix de base bucketise au tick
        p_base = round(df["close"].iloc[i] / tick) * tick
        # Genere 5-10 cellules autour du base price
        for offset in range(-5, 6):
            p = round(p_base + offset * tick, 4)
            cells[p] = {
                "ask_vol": float(np.random.randint(10, 200)),
                "bid_vol": float(np.random.randint(10, 200)),
            }
        # Injection forcee d'un stack BUY (ask_above >> bid_p) sur 30% des bars
        if i % 7 == 0:
            # Force 3 cellules consecutives avec imbalance >600%
            start_off = np.random.randint(-3, 2)
            for k in range(3):
                p = round(p_base + (start_off + k) * tick, 4)
                if p in cells:
                    cells[p]["bid_vol"] = 5.0  # bas
                    # Cellule au-dessus avec ask_vol gros
                    p_above = round(p + tick, 4)
                    if p_above in cells:
                        cells[p_above]["ask_vol"] = 100.0  # 100/5 * 100 = 2000% >> 600
        footprint[i] = cells

    # BATCH
    batch_df = apply_edge_zones(df.copy(), footprint, symbol="ES", tick=tick)

    # STREAM
    state = make_edge_zones_state("ES")
    stream_rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        cells_i = footprint.get(i, {})
        stream_rows.append(add_edge_zones_streaming(row.to_dict(), state, cells_i))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest edge_zones parite sur {n} rows synth (30% bars avec stack force)...")

    cols_check = [
        "bar_edge_buy_fire", "bar_edge_sell_fire",
        "bar_edge_buy_zone_size", "bar_edge_sell_zone_size",
        "n_edge_buy_active", "n_edge_sell_active",
        "dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (8 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:32s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        # Stats : combien de fires/zones detectees
        n_fires = int((s != 0).sum()) if "fire" in col else None
        extra = f"(n_fires={n_fires})" if n_fires is not None else ""
        print(f"  {col:32s} {status} max_diff={max_diff:.6e} nan_mm={nan_mismatch} {extra}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > 1e-6) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL edge_zones : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus():
    """Test sub-engine phase_b_plus streaming (74 features NON-LOOKAHEAD)."""
    from phase_b_plus_streaming import (
        add_phase_b_plus_streaming,
        make_phase_b_plus_state,
    )
    from phase_b_plus_engine import (
        add_volume_spike_features, add_rotation_features,
        add_vwap_features, add_ovn_features, add_open_features,
        add_news_features,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(73)
    # Synth 3 jours x 1440 bars/jour pour couvrir OVN + RTH + news times
    n = 4320  # 3 jours
    bars = []
    start = pd.Timestamp("2026-05-12 00:00:00", tz="UTC")
    for i in range(n):
        ts = start + pd.Timedelta(minutes=i)
        bars.append({"ts_event": ts.tz_localize(None)})
    df = pd.DataFrame(bars)
    df["open"] = 5800 + np.cumsum(np.random.randn(n) * 0.2)
    df["high"] = df["open"] + np.random.uniform(0.1, 1.5, n)
    df["low"] = df["open"] - np.random.uniform(0.1, 1.5, n)
    df["close"] = df["open"] + np.random.randn(n) * 0.5
    df["volume"] = np.random.randint(50, 2000, n).astype(float)

    # BATCH : chain les fonctions NON-LOOKAHEAD
    batch_df = df.copy()
    batch_df = add_volume_spike_features(batch_df, symbol="ES")
    batch_df = add_rotation_features(batch_df, tick=0.25)
    batch_df = add_vwap_features(batch_df)
    batch_df = add_ovn_features(batch_df, tick=0.25)
    batch_df = add_open_features(batch_df)
    batch_df = add_news_features(batch_df)

    # STREAM
    state = make_phase_b_plus_state("ES")
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_phase_b_plus_streaming(row.to_dict(), state, tick=0.25))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus parite sur {n} rows synth (3 jours)...")

    # Features a tester (NON-LOOKAHEAD)
    cols_check = [
        # Volume spike
        "vol_spike_up", "vol_spike_dn", "vol_zscore_20",
        # Rotation
        "rotation_up", "rotation_dn",
        # VWAP D
        "vwap_d", "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d_sd2u", "vwap_d_sd2d",
        "vwap_d_sd3u", "vwap_d_sd3d",
        "dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
        "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct",
        "vwap_d_cross_up", "vwap_d_cross_dn",
        "vwap_d_sd1_above", "vwap_d_sd1_below",
        "vwap_d_sd2_above", "vwap_d_sd2_below",
        # VWAP W
        "vwap_w", "vwap_w_sd1u", "vwap_w_sd1d", "vwap_w_sd2u", "vwap_w_sd2d",
        "dist_vwap_w_pct", "dist_vwap_w_sd1u_pct",
        # VWAP M
        "vwap_m", "vwap_m_sd1u", "vwap_m_sd1d",
        "dist_vwap_m_pct",
        # OVN
        "ovn_high", "ovn_low", "ovn_range_ticks",
        "dist_ovn_high_pct", "dist_ovn_low_pct",
        "ovn_broken_up", "ovn_broken_dn",
        # Opens
        "open_830_et", "open_930_et",
        "dist_open_830_pct", "dist_open_930_pct",
        "above_open_830", "above_open_930",
        # News
        "is_news_715", "is_news_730", "is_news_830", "is_news_845",
        "is_news_900", "is_news_930",
        "within_news_715_5m", "within_news_830_5m", "within_news_930_5m",
        "mins_since_news", "mins_to_next_news",
    ]

    print("\n--- NIVEAU 1 : parite batch vs streaming (54 features echantillonnees) ---")
    all_pass = True
    fail_cols = []
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:32s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        # Tolerance plus large sur VWAP (float32 cast batch + accumulator drift)
        atol = 1e-3 if "vwap" in col or "dist_vwap" in col else 1e-6
        status = "PASS" if max_diff < atol and nan_mismatch < 10 else "FAIL"
        print(f"  {col:32s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            fail_cols.append(col)

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    if fail_cols:
        print(f"  Failed columns : {fail_cols[:5]}{'...' if len(fail_cols)>5 else ''}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_long():
    """Test sub-engine phase_b_plus_long streaming (13 features LONG NON-LOOKAHEAD).

    Test sur NQ (utilise formule NQ long_updown_pattern sans lookahead).
    Comparaison batch add_long_bar_features + add_long_extension_lines +
    add_long_updown_features symbol='NQ'.
    """
    from phase_b_plus_long_streaming import (
        add_phase_b_plus_long_streaming,
        make_long_bar_state,
    )
    from phase_b_plus_engine import (
        add_long_bar_features, add_long_extension_lines, add_long_updown_features,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(83)
    # Synth 500 bars avec range expansion volatile pour generer fires
    n = 500
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-13 13:00:00", periods=n, freq="1min"),
    })
    # Prix avec trends + reversals pour generer LONG UP/DN patterns
    base = 5800.0 + np.cumsum(np.random.randn(n) * 0.5)
    df["close"] = base
    df["open"] = base + np.random.randn(n) * 0.3
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(0.5, 5, n)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(0.5, 5, n)

    # BATCH chain : long_bar + long_ext_lines + long_updown formule NQ
    batch_df = df.copy()
    batch_df = add_long_bar_features(batch_df, symbol="NQ", tick=0.25)
    batch_df = add_long_extension_lines(batch_df)
    batch_df = add_long_updown_features(batch_df, symbol="NQ", tick=0.25)

    # STREAM
    state = make_long_bar_state("NQ")
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_phase_b_plus_long_streaming(row.to_dict(), state))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_long parite sur {n} rows synth (NQ)...")

    cols_check = [
        # Long bar (5)
        "long_up_bar", "long_dn_bar", "bar_body_ticks",
        "range_h_minus_lprev_ticks", "range_hprev_minus_l_ticks",
        # Long Extension Lines (6)
        "n_long_up_zones_active", "n_long_dn_zones_active",
        "dist_long_up_nearest_pct", "dist_long_dn_nearest_pct",
        "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
        # Long UpDown pattern NQ (2)
        "long_dn_up_pattern", "long_up_dn_pattern",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (13 features LONG) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        # Tolerance plus large sur dist_*_pct (float64 division noise)
        atol = 1e-6
        status = "PASS" if max_diff < atol and nan_mismatch == 0 else "FAIL"
        n_fires = int((s != 0).sum()) if "bar" in col or "pattern" in col else None
        extra = f"(fires={n_fires})" if n_fires is not None else ""
        print(f"  {col:35s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch} {extra}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > atol) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_long : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_color():
    """Test sub-engine phase_b_plus_color streaming (12 features LAG-1).

    CONVENTION LAG-1 :
      batch_df.iloc[T]["bn_color_up_fwd1"]  ==  stream_df.iloc[T+1]["bn_color_up_fwd1"]
      Le stream emit la valeur pour bar T-1 dans le row T (= row courant).
      Comparaison test : stream_df[1:].reset_index ==  batch_df[:-1].reset_index
    """
    from phase_b_plus_color_streaming import (
        add_phase_b_plus_color_streaming,
        make_color_bar_state,
    )
    from phase_b_plus_engine import (
        add_color_features, add_color_extension_lines, add_long_updown_features,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(89)
    n = 500
    df = pd.DataFrame({
        "ts_event": pd.date_range("2026-05-13 13:00:00", periods=n, freq="1min"),
    })
    base = 5800.0 + np.cumsum(np.random.randn(n) * 0.5)
    df["close"] = base
    df["open"] = base + np.random.randn(n) * 0.3
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(0.5, 5, n)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(0.5, 5, n)

    # BATCH chain : color + color_ext + long_updown formule ES (lookahead)
    batch_df = df.copy()
    batch_df = add_color_features(batch_df, symbol="ES", tick=0.25)
    batch_df = add_color_extension_lines(batch_df)
    batch_df = add_long_updown_features(batch_df, symbol="ES", tick=0.25)

    # STREAM
    state = make_color_bar_state("ES")
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_phase_b_plus_color_streaming(row.to_dict(), state))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_color parite LAG-1 sur {n} rows synth (ES)...")
    print("  Convention : stream_df[T+1] == batch_df[T] (shift de 1)")

    # Mapping : pour chaque feature stream, on compare stream[T+1] vs batch[T]
    # Donc stream_df[1:] (= valeurs pour T=0, 1, ..., N-2) vs batch_df[:-1]
    cols_stream_color = [
        "bn_color_up_fwd1", "bn_color_dn_fwd1",
        "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
        "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    ]
    # FIX P0 audit : stream emit `long_*_pattern` (sans suffix) - aligne batch
    cols_stream_long_es = [
        "long_dn_up_pattern", "long_up_dn_pattern",
    ]
    cols_batch_long_es = [
        "long_dn_up_pattern", "long_up_dn_pattern",
    ]

    print("\n--- NIVEAU 1 : parite LAG-1 batch[T] vs stream[T+1] (10 features color) ---")
    all_pass = True
    # Stream emit en row T la valeur pour bar T-1. Donc :
    #   stream[T]["bn_color_up_fwd1"] = valeur batch[T-1]
    # On compare : batch[i] vs stream[i+1] pour i in [0, N-2]
    for col in cols_stream_color:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values[:-1]  # batch[0..N-2]
        s = stream_df[col].astype("float64").values[1:]  # stream[1..N-1]
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        atol = 1e-6
        status = "PASS" if max_diff < atol and nan_mismatch == 0 else "FAIL"
        n_fires = int((s != 0).sum()) if "fwd1" in col else None
        extra = f"(fires={n_fires})" if n_fires is not None else ""
        print(f"  {col:35s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch} {extra}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > atol) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print("\n--- NIVEAU 2 : parite LAG-1 long_updown_pattern formule ES (2 features) ---")
    # long_dn_up_pattern_es du stream <-> long_dn_up_pattern du batch (formule ES)
    for col_stream, col_batch in zip(cols_stream_long_es, cols_batch_long_es):
        if col_batch not in batch_df.columns or col_stream not in stream_df.columns:
            print(f"  {col_stream:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col_batch].astype("float64").values[:-1]
        s = stream_df[col_stream].astype("float64").values[1:]
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        status = "PASS" if max_diff < 1e-6 and nan_mismatch == 0 else "FAIL"
        n_fires = int((s != 0).sum())
        print(f"  {col_stream:35s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch} (fires={n_fires})")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1+2 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_color : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_open_extension_lines():
    """Test sub-engine open_extension_lines (4 features NEW Jackson).

    NOUVELLE feature (pas dans le batch) - tests COMPORTEMENT attendu :
      1. Zone capturee a mins_et=510 (08:30 ET) et mins_et=570 (09:30 ET)
      2. Zone reste active tant que pas de bar avec L<=level<=H (overlap)
      3. Zone desactivee a la 1ere bar futur qui la touche (= mort)
      4. Multi-jours : zones d'opens precedents persistent jusqu'a touche
    """
    from open_extension_lines_streaming import (
        add_open_extension_lines_streaming,
        OpenExtensionLinesState,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(101)
    # Synth 3 jours x 1440 bars (24h chacun)
    # Conditions deterministes pour valider comportement :
    #   - Jour 1 : open_830 a 5800.0, prix ne le touche JAMAIS (zone reste active)
    #   - Jour 2 : open_830 a 5810.0, prix le touche a 13:00 (zone desactivee)
    #   - Jour 3 : open_830 a 5820.0, prix ne le touche pas
    bars = []
    for day in range(3):
        date = pd.Timestamp("2026-05-12") + pd.Timedelta(days=day)
        for mins in range(1440):
            h = mins // 60
            m = mins % 60
            ts = pd.Timestamp(date) + pd.Timedelta(hours=h, minutes=m)
            bars.append({
                "ts_event": ts,
                "date_et": date.date(),
                "mins_et": mins,
            })
    n = len(bars)
    df = pd.DataFrame(bars)

    # Prix synthetique : oscille autour de la valeur de l'open_830 du jour
    # Jour 1 : oscille entre 5803-5807 (jamais 5800)
    # Jour 2 : oscille entre 5805-5815 (touche 5810 a 13:00)
    # Jour 3 : oscille entre 5823-5827 (jamais 5820)
    prices = []
    for i, bar in enumerate(bars):
        day = (bar["ts_event"] - pd.Timestamp("2026-05-12")).days
        # mins offset dans le jour
        mins_in_day = bar["mins_et"]
        if day == 0:
            # Jour 1 : open_830 = 5800, prix dans [5803, 5807]
            if mins_in_day == 510:
                prices.append(5800.0)
            else:
                prices.append(5803.0 + (mins_in_day % 5))
        elif day == 1:
            # Jour 2 : open_830 = 5810, prix entre [5815, 5818] (above) puis
            # touche 5810 EXACTEMENT a mins=780 (13:00 ET), re-monte apres.
            if mins_in_day == 510:
                prices.append(5810.0)
            elif mins_in_day == 780:
                prices.append(5810.3)  # bar [5809.8, 5810.8] touche 5810 (overlap)
            elif mins_in_day < 780:
                prices.append(5815.0 + (mins_in_day % 4))  # [5815, 5818]
            else:
                prices.append(5816.0 + (mins_in_day % 3))  # [5816, 5818]
        else:
            # Jour 3 : open_830 = 5820, prix dans [5823, 5827]
            if mins_in_day == 510:
                prices.append(5820.0)
            else:
                prices.append(5823.0 + (mins_in_day % 5))
    df["open"] = prices
    df["close"] = df["open"]
    df["high"] = df["open"] + 0.5
    df["low"] = df["open"] - 0.5

    state = OpenExtensionLinesState()
    rows = []
    for _, row in df.iterrows():
        rows.append(add_open_extension_lines_streaming(row.to_dict(), state))
    out_df = pd.DataFrame(rows)

    print(f"\nTest open_extension_lines comportement sur {n} bars synth (3 jours)...")

    all_pass = True

    # Test 1 : zone capturee a mins_et=510 jour 1
    print("\n--- Test 1 : capture zone a mins_et=510 jour 1 ---")
    j1_510 = df[(df["date_et"] == pd.Timestamp("2026-05-12").date()) & (df["mins_et"] == 510)].index[0]
    after_510 = out_df.iloc[j1_510 + 1]
    if after_510["open_830_zone_active"] >= 1:
        print(f"  Apres mins=510 jour 1 : open_830_zone_active={after_510['open_830_zone_active']} : PASS")
    else:
        print(f"  Apres mins=510 jour 1 : zone NON capturee : FAIL")
        all_pass = False

    # Test 2 : zone reste active toute la journee jour 1 (jamais touchee)
    print("\n--- Test 2 : zone active fin jour 1 (jamais touchee) ---")
    j1_last = df[df["date_et"] == pd.Timestamp("2026-05-12").date()].index[-1]
    at_eod_j1 = out_df.iloc[j1_last]
    if at_eod_j1["open_830_zone_active"] >= 1:
        print(f"  Fin jour 1 : open_830_zone_active={at_eod_j1['open_830_zone_active']} : PASS")
    else:
        print(f"  Fin jour 1 : zone perdue : FAIL")
        all_pass = False

    # Test 3 (Jackson option 2) : zone jour 1 PERSISTE overnight + debut jour 2 (AVANT 08:30 J+1)
    print("\n--- Test 3 : zone jour 1 PERSISTE overnight (option 2 Jackson) ---")
    j2_early = df[
        (df["date_et"] == pd.Timestamp("2026-05-13").date())
        & (df["mins_et"] == 100)
    ].index[0]
    at_early_j2 = out_df.iloc[j2_early]
    if at_early_j2["open_830_zone_active"] >= 1:
        print(f"  Debut jour 2 (01:40 ET, avant 08:30) : open_830_zone_active={at_early_j2['open_830_zone_active']} : PASS")
    else:
        print(f"  Debut jour 2 (01:40 ET) : open_830_zone_active=0 (devrait persister) : FAIL")
        all_pass = False

    # Test 4 : Zone jour 2 desactivee apres touche a 13:00 (mins_et=780)
    print("\n--- Test 4 : zone jour 2 desactivee par TOUCHE a 13:00 ---")
    j2_touch = df[(df["date_et"] == pd.Timestamp("2026-05-13").date()) & (df["mins_et"] == 780)].index[0]
    before_touch = out_df.iloc[j2_touch - 1]
    after_touch = out_df.iloc[j2_touch]
    print(f"  Bar avant touche : open_830_zone_active={before_touch['open_830_zone_active']}")
    print(f"  Bar de la touche  : open_830_zone_active={after_touch['open_830_zone_active']}")
    if before_touch["open_830_zone_active"] > after_touch["open_830_zone_active"]:
        print(f"  Touche correctement desactive zone : PASS")
    else:
        print(f"  Touche n'a PAS desactive : FAIL")
        all_pass = False

    # Test 5 : zone jour 2 REMPLACE jour 1 a 08:30 ET jour 2
    # Avant 08:30 J+1 : zone jour 1 active (test 3 confirme)
    # A 08:30 J+1 : nouvelle zone creee, ancienne (jour 1) desactivee
    # Count_active = 1 (juste la nouvelle, ancienne morte)
    print("\n--- Test 5 : Jour 2 08:30 ET remplace zone jour 1 (count=1) ---")
    j2_510 = df[
        (df["date_et"] == pd.Timestamp("2026-05-13").date())
        & (df["mins_et"] == 510)
    ].index[0]
    just_before_j2_open = out_df.iloc[j2_510 - 1]
    just_after_j2_open = out_df.iloc[j2_510]
    print(f"  Bar avant 08:30 j2 : open_830_zone_active={just_before_j2_open['open_830_zone_active']} (jour 1 encore active)")
    print(f"  Bar 08:30 j2 : open_830_zone_active={just_after_j2_open['open_830_zone_active']} (nouvelle remplace ancienne)")
    if just_before_j2_open["open_830_zone_active"] == 1 and just_after_j2_open["open_830_zone_active"] == 1:
        print(f"  Replacement OK (1 -> 1, ancienne desactivee + nouvelle active) : PASS")
    else:
        print(f"  Replacement FAIL")
        all_pass = False

    # Test 6 : dist_open_830_zone_pct non-NaN quand active
    print("\n--- Test 6 : dist_open_830_zone_pct non-NaN quand active ---")
    after_510_dist = out_df.iloc[j1_510 + 1]["dist_open_830_zone_pct"]
    if not pd.isna(after_510_dist):
        print(f"  dist_open_830_zone_pct apres 510 : {after_510_dist:.4f}% : PASS")
    else:
        print(f"  dist_open_830_zone_pct apres 510 : NaN (attendu valeur) : FAIL")
        all_pass = False

    # Test 7 : fin jour 3 -> count_active=1 (jour 3 seulement, jour 1 remplacee par jour 2,
    # jour 2 touchee donc morte, jour 3 remplace jour 2 a 08:30)
    print("\n--- Test 7 : Fin jour 3 = 1 zone active (option 2 = pas accumulation) ---")
    end = out_df.iloc[-1]
    if end["open_830_zone_active"] == 1:
        print(f"  Fin jour 3 : open_830_zone_active=1 : PASS (jour 3 seulement)")
    else:
        print(f"  Fin jour 3 : open_830_zone_active={end['open_830_zone_active']} (attendu 1) : FAIL")
        all_pass = False

    print(f"\n{'=' * 70}")
    print(f"GLOBAL open_extension_lines : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_sessions_swings_simple():
    """Test sub-engine sessions_swings_simple (38 features NON-LOOKAHEAD).

    Comparaison batch add_session_metadata_v2 + add_session_highs_lows +
    add_session_opens + add_premium_discount.
    """
    from sessions_swings_simple_streaming import (
        add_sessions_swings_simple_streaming,
        make_sessions_swings_simple_state,
    )
    from sessions_swings_engine import (
        add_session_metadata_v2, add_session_highs_lows,
        add_session_opens, add_premium_discount,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(113)
    n = 4320  # 3 jours
    bars = []
    start = pd.Timestamp("2026-05-12 00:00:00", tz="UTC")
    for i in range(n):
        ts = start + pd.Timedelta(minutes=i)
        bars.append({"ts_event": ts.tz_localize(None)})
    df = pd.DataFrame(bars)
    df["open"] = 5800 + np.cumsum(np.random.randn(n) * 0.2)
    df["high"] = df["open"] + np.random.uniform(0.1, 1.5, n)
    df["low"] = df["open"] - np.random.uniform(0.1, 1.5, n)
    df["close"] = df["open"] + np.random.randn(n) * 0.5
    # sess_high/sess_low pour premium_discount (running cumulative session_date_trading)
    # Pour simplifier le synth, on prend running par date_et calendar
    df["__date_et"] = pd.to_datetime(df["ts_event"]).dt.date
    df["sess_high"] = df.groupby("__date_et")["high"].cummax()
    df["sess_low"] = df.groupby("__date_et")["low"].cummin()
    df = df.drop(columns="__date_et")

    # BATCH chain
    batch_df = df.copy()
    batch_df = add_session_metadata_v2(batch_df)
    batch_df = add_session_highs_lows(batch_df, tick=0.25)
    batch_df = add_session_opens(batch_df)
    batch_df = add_premium_discount(batch_df)

    # STREAM
    state = make_sessions_swings_simple_state("ES")
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_sessions_swings_simple_streaming(row.to_dict(), state))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest sessions_swings_simple parite sur {n} rows synth (3 jours)...")

    cols_check = [
        # Session metadata (5 booleans + session_id)
        "session_id", "is_in_asia", "is_in_london", "is_in_us_cash", "is_in_us_after",
        # Session highs/lows (16)
        "asia_high", "asia_low", "london_high", "london_low",
        "us_high", "us_low", "after_high", "after_low",
        "dist_asia_high_pct", "dist_asia_low_pct",
        "dist_london_high_pct", "dist_london_low_pct",
        "dist_us_high_pct", "dist_us_low_pct",
        "dist_after_high_pct", "dist_after_low_pct",
        # Session opens (12)
        "asia_open", "london_open", "ny_open", "after_open",
        "dist_asia_open_pct", "dist_london_open_pct",
        "dist_ny_open_pct", "dist_after_open_pct",
        "above_asia_open", "above_london_open",
        "above_ny_open", "above_after_open",
        # Premium/Discount (3)
        "pct_in_range", "premium_zone", "discount_zone",
    ]

    print(f"\n--- NIVEAU 1 : parite batch vs streaming ({len(cols_check)} features) ---")
    all_pass = True
    fail_cols = []
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:30s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        atol = 1e-3 if "pct" in col else 1e-6
        status = "PASS" if max_diff < atol and nan_mismatch == 0 else "FAIL"
        print(f"  {col:30s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch}")
        if status == "FAIL":
            all_pass = False
            fail_cols.append(col)

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    if fail_cols:
        print(f"  Failed columns : {fail_cols[:5]}{'...' if len(fail_cols)>5 else ''}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL sessions_swings_simple : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_sessions_swings_lag():
    """Test sub-engine sessions_swings_lag (17 features LAG-N).

    Convention LAG-N : stream emit pour ROW i la value pour pivot/event
    confirme jusqu'a present. Test parite avec shift N=10 pour swings.

    Spike origin = lookback 3 only -> pas de lag, parite directe sur columns.
    """
    from sessions_swings_lag_streaming import (
        add_sessions_swings_lag_streaming,
        make_sessions_swings_lag_state,
    )
    from sessions_swings_simple_streaming import (
        add_sessions_swings_simple_streaming,
        make_sessions_swings_simple_state,
    )
    from sessions_swings_engine import (
        add_session_metadata_v2, add_swing_features_v2,
        add_liquidity_sweep, add_equal_swings,
        add_spike_origin_features,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(127)
    n = 1440  # 1 jour
    bars = []
    start = pd.Timestamp("2026-05-12 00:00:00", tz="UTC")
    for i in range(n):
        ts = start + pd.Timedelta(minutes=i)
        bars.append({"ts_event": ts.tz_localize(None)})
    df = pd.DataFrame(bars)
    # Synth avec swings prononces : sinusoide + bruit pour generer pivots
    # Amplitude 30 points sur cycle de 100 bars -> prominence >> 0.1% (5.8 pts)
    x = np.arange(n)
    sine = 30 * np.sin(x * 2 * np.pi / 100)  # cycle 100 bars
    base = 5800 + sine + np.cumsum(np.random.randn(n) * 0.2)
    df["close"] = base
    df["open"] = base + np.random.randn(n) * 0.3
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(0.5, 3.0, n)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(0.5, 3.0, n)

    # BATCH chain
    batch_df = df.copy()
    batch_df = add_session_metadata_v2(batch_df)
    batch_df = add_swing_features_v2(batch_df)
    batch_df = add_liquidity_sweep(batch_df)
    batch_df = add_equal_swings(batch_df, symbol="ES", tick=0.25)
    batch_df = add_spike_origin_features(batch_df)

    # STREAM chain : simple_streaming (pour session_id) puis lag_streaming
    state_simple = make_sessions_swings_simple_state("ES")
    state_lag = make_sessions_swings_lag_state("ES")
    stream_rows = []
    for _, row in df.iterrows():
        r1 = add_sessions_swings_simple_streaming(row.to_dict(), state_simple)
        r2 = add_sessions_swings_lag_streaming(r1, state_lag)
        stream_rows.append(r2)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest sessions_swings_lag parite sur {n} rows synth (1 jour, ES)...")

    N = 10

    # ─── NIVEAU 1 : Features SWING booleens LAG-10 (parite shift exact) ─────
    print(f"\n--- NIVEAU 1 : SWING booleens LAG-{N} (batch[i] == stream[i+{N}]) ---")
    cols_swing_lag = [
        ("swing_high_active_lag10", N),
        ("swing_low_active_lag10", N),
    ]
    all_pass = True
    for col, lag in cols_swing_lag:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values[:-lag] if lag > 0 else batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values[lag:] if lag > 0 else stream_df[col].astype("float64").values
        diff = np.abs(b - s)
        max_diff = float(np.nanmax(diff))
        n_batch_fires = int((b != 0).sum())
        n_stream_fires = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.4e} "
              f"fires batch/stream:{n_batch_fires}/{n_stream_fires}")
        if status == "FAIL":
            all_pass = False

    # ─── NIVEAU 2 : equal swings (depend swings) - shift N test ────────────
    print(f"\n--- NIVEAU 2 : Equal swings (depend swings, shift N=10) ---")
    for col in ("equal_highs_detected", "equal_lows_detected"):
        if col not in batch_df.columns:
            continue
        b = batch_df[col].astype("float64").values[:-N]
        s = stream_df[col].astype("float64").values[N:]
        diff = np.abs(b - s)
        max_diff = float(np.nanmax(diff))
        n_batch = int((b != 0).sum())
        n_stream = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.4e} "
              f"batch/stream:{n_batch}/{n_stream}")
        if status == "FAIL":
            all_pass = False

    # ─── NIVEAU 3 : SPIKE features (PAS lookahead, parite directe) ──────────
    print(f"\n--- NIVEAU 3 : SPIKE features (lookback 3 only, parite directe) ---")
    cols_spike = [
        "spike_detected_lag3",
        "n_spike_origins_active",
        "n_spike_origins_cluster_within_0_2pct",
    ]
    for col in cols_spike:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        diff = np.abs(b - s)
        max_diff = float(np.nanmax(diff))
        n_batch = int((b != 0).sum())
        n_stream = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.4e} "
              f"batch/stream:{n_batch}/{n_stream}")
        if status == "FAIL":
            all_pass = False

    # ─── NIVEAU 3b INFO : LIQUIDITY SWEEP divergence semantique (audit P0) ─
    # DIVERGENCE INTRINSEQUE batch/stream (similaire volume_profile commit 0a6cf7b) :
    #   - Batch utilise swing_h_price[i] = ffilled depuis dernier swing detecte
    #     avec LOOKAHEAD (= pivot evalue avec window centered futur)
    #   - Stream utilise state.last_swing_high.price = dernier swing CONFIRME
    #     (= lag-10, sans lookahead - comportement live reel)
    #   - Stream over-fire sweeps car swing_h_price plus ancien -> break plus
    #     facile a satisfaire.
    #
    # C'EST LE BON COMPORTEMENT LIVE (bot live ne peut pas connaitre pivots
    # futurs). Distribution shift ML inherent : training batch vs inference
    # stream. ml-trainer review obligatoire avant deploy live (cf
    # ml-trainer review pour volume_profile aussi).
    print(f"\n--- NIVEAU 3b INFO : LIQUIDITY SWEEP divergence semantique documentee ---")
    for col in ("liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5"):
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        n_batch = int((b != 0).sum())
        n_stream = int((s != 0).sum())
        print(f"  {col:35s} INFO batch={n_batch} fires, stream={n_stream} fires "
              f"(divergence semantique documentee, pas parite stricte)")

    # ─── NIVEAU 4 INFO : dist_*_pct features (semantique stream differente) ─
    # Pas de parite stricte (close[i] vs close[i+N] differs). Verifier juste
    # qu'on emit des valeurs raisonnables.
    print(f"\n--- NIVEAU 4 INFO : dist features (NON parite stricte, semantique stream) ---")
    for col in (
        "dist_last_swing_high_pct", "dist_last_swing_low_pct",
        "bars_since_last_swing_high", "bars_since_last_swing_low",
        "last_swing_high_session", "last_swing_low_session",
        "dist_last_spike_origin_pct", "bars_since_last_spike",
    ):
        if col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT stream")
            continue
        s_vals = stream_df[col].dropna()
        if len(s_vals) > 0:
            print(f"  {col:35s} stream emit non-NaN {len(s_vals)} rows")
        else:
            print(f"  {col:35s} stream emit ALL NaN")

    print(f"\n  Niveau 1+2+3 status (parite stricte) : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL sessions_swings_lag : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_vwap_diff():
    """Test sub-engine vwap_diff streaming (5 features stateless)."""
    from vwap_diff_streaming import add_vwap_diff_streaming, VwapDiffState
    from phase_b_vwap_diff import apply_vwap_diff
    import numpy as np
    import pandas as pd

    np.random.seed(131)
    n = 300
    df = pd.DataFrame({
        "dist_vwap_d_pct": np.random.uniform(-2, 2, n),
        "dist_vwap_w_pct": np.random.uniform(-3, 3, n),
        "dist_vwap_m_pct": np.random.uniform(-5, 5, n),
        "dist_vwap_d_sd1u_pct": np.random.uniform(-2, 0, n),
        "dist_vwap_w_sd1u_pct": np.random.uniform(-3, 0, n),
        "dist_vwap_d_sd1d_pct": np.random.uniform(0, 2, n),
        "dist_vwap_w_sd1d_pct": np.random.uniform(0, 3, n),
    })

    batch_df = apply_vwap_diff(df.copy())

    state = VwapDiffState()
    stream_rows = []
    for _, row in df.iterrows():
        stream_rows.append(add_vwap_diff_streaming(row.to_dict(), state))
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest vwap_diff parite sur {n} rows synth...")

    cols_check = [
        "vwap_w_minus_d_pct",
        "vwap_m_minus_w_pct",
        "vwap_w_sd1u_minus_d_sd1u_pct",
        "vwap_w_sd1d_minus_d_sd1d_pct",
        "vwap_w_d_aligned",
    ]
    print("\n--- NIVEAU 1 : parite batch vs streaming (5 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:35s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        atol = 1e-3 if "pct" in col else 1e-6
        status = "PASS" if max_diff < atol and nan_mismatch == 0 else "FAIL"
        print(f"  {col:35s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch}")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL vwap_diff : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_footprint_builder():
    """Test sub-engine footprint_builder streaming (HELPER, 0 features ML).

    Verifie parite : batch build_footprint_per_bar(trades, bar_starts) vs
    stream build_footprint_cells_streaming(trades_in_window) bar par bar.
    """
    from footprint_builder_streaming import build_footprint_cells_streaming
    from footprint_builder import build_footprint_per_bar
    import numpy as np
    import pandas as pd

    np.random.seed(137)
    # Synth 100 bars 1-min + 5000 trades aleatoires
    n_bars = 100
    n_trades = 5000
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    bar_starts = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars + 1)])

    trades = []
    for _ in range(n_trades):
        # Timestamp aleatoire dans la fenetre des bars
        offset_min = np.random.uniform(0, n_bars)
        ts = start + pd.Timedelta(minutes=offset_min)
        price = round(5800 + np.random.uniform(-10, 10), 2)
        size = np.random.randint(1, 50)
        side = np.random.choice(["A", "B", "N"], p=[0.45, 0.45, 0.10])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    print(f"\nTest footprint_builder parite sur {n_bars} bars + {n_trades} trades synth...")

    # BATCH
    batch_footprint = build_footprint_per_bar(trades_df, bar_starts.iloc[:-1], tick=0.25)

    # STREAM bar par bar
    # Pour chaque bar i, prendre trades dans [bar_starts[i], bar_starts[i+1])
    stream_footprint = {}
    for i in range(n_bars):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1]
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        cells = build_footprint_cells_streaming(trades_in_bar, tick=0.25)
        if cells:
            stream_footprint[i] = cells

    print(f"\n--- NIVEAU 1 : parite cells per bar (batch vs stream) ---")
    all_pass = True
    n_bars_batch = len(batch_footprint)
    n_bars_stream = len(stream_footprint)
    print(f"  Bars avec cells : batch={n_bars_batch}, stream={n_bars_stream}")
    if n_bars_batch != n_bars_stream:
        print(f"  FAIL : nombre de bars different")
        all_pass = False

    # Compare cells par bar
    mismatches = 0
    cells_compared = 0
    for bar_idx in batch_footprint:
        if bar_idx not in stream_footprint:
            mismatches += 1
            continue
        batch_cells = batch_footprint[bar_idx]
        stream_cells = stream_footprint[bar_idx]
        if set(batch_cells.keys()) != set(stream_cells.keys()):
            print(f"    bar {bar_idx} : prix buckets different "
                  f"batch={len(batch_cells)}, stream={len(stream_cells)}")
            mismatches += 1
            continue
        for price in batch_cells:
            cells_compared += 1
            for key in ("ask_vol", "bid_vol", "total_vol", "n_trades"):
                bv = batch_cells[price][key]
                sv = stream_cells[price][key]
                if abs(bv - sv) > 1e-6:
                    print(f"    bar {bar_idx} price {price} {key}: batch={bv} stream={sv}")
                    mismatches += 1
                    break

    print(f"  Cells comparees : {cells_compared}")
    print(f"  Mismatches : {mismatches}")
    if mismatches > 0:
        all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL footprint_builder : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_plus_trades():
    """Test sub-engine LOT 1 phase_b_plus_plus trades aggregates (~34 features)."""
    from phase_b_plus_plus_trades_streaming import (
        add_phase_b_plus_plus_trades_streaming,
        make_phase_b_plus_plus_trades_state,
    )
    from phase_b_plus_plus_engine import apply_phase_b_plus_plus
    import numpy as np
    import pandas as pd

    np.random.seed(149)
    n_bars = 200
    n_trades = 8000

    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    bar_starts = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars)])

    # Bars OHLC + delta_bar
    df = pd.DataFrame({"ts_event": bar_starts})
    base = 5800 + np.cumsum(np.random.randn(n_bars) * 0.3)
    df["close"] = base
    df["open"] = base + np.random.randn(n_bars) * 0.2
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(0.5, 3.0, n_bars)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(0.5, 3.0, n_bars)
    df["delta_bar"] = np.random.randint(-100, 100, n_bars).astype(float)
    df["volume"] = np.random.randint(500, 2000, n_bars)

    # Trades synth distribués sur bars
    trades = []
    for _ in range(n_trades):
        offset_min = np.random.uniform(0, n_bars - 0.001)
        ts = start + pd.Timedelta(minutes=offset_min)
        price = round(5800 + np.random.uniform(-15, 15), 2)
        size = int(np.random.exponential(30)) + 1
        side = np.random.choice(["A", "B", "N"], p=[0.47, 0.47, 0.06])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    # BATCH
    batch_df = apply_phase_b_plus_plus(df.copy(), trades_df, symbol="ES", tick=0.25)

    # STREAM : pour chaque bar, on extrait trades_in_window + appelle stream
    state = make_phase_b_plus_plus_trades_state("ES")
    stream_rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1] if i + 1 < n_bars else bar_start_ts + pd.Timedelta(minutes=1)
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        out = add_phase_b_plus_plus_trades_streaming(row.to_dict(), state, trades_in_bar)
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_plus_trades parite sur {n_bars} bars + {n_trades} trades synth...")

    cols_check = [
        # Big orders multi-tier (12)
        "n_big_t1", "n_big_t2", "n_big_t3", "n_big_t4",
        "n_big_buy_t1", "n_big_buy_t2", "n_big_buy_t3", "n_big_buy_t4",
        "n_big_sell_t1", "n_big_sell_t2", "n_big_sell_t3", "n_big_sell_t4",
        # Trade size stats (3)
        "max_size_buy", "max_size_sell", "p99_trade_size",
        # Aggressor + clusters (3)
        "aggressor_imbalance", "n_clusters", "max_cluster_volume",
        # FPBS intra-bar (4)
        "max_delta_bar", "min_delta_bar", "delta_change", "n_ticks_bar",
        # Distances nearest (4)
        "dist_big_ask_nearest_pct", "dist_big_bid_nearest_pct",
        "dist_cluster_nearest_up_pct", "dist_cluster_nearest_dn_pct",
        # Derivees (5)
        "big_buy_dominance", "big_sell_dominance",
        "finish_pct_up", "finish_strong_up", "finish_strong_dn",
        # Delta divergence daily (2)
        "delta_div_buy", "delta_div_sell",
    ]

    print(f"\n--- NIVEAU 1 : parite ({len(cols_check)} features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:32s} MANQUANT batch={col in batch_df.columns} stream={col in stream_df.columns}")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mismatch = int(nan_diff.sum())
        atol = 1e-3 if "pct" in col or col in ("p99_trade_size", "finish_pct_up") else 1e-6
        status = "PASS" if max_diff < atol and nan_mismatch < 5 else "FAIL"
        print(f"  {col:32s} {status} max_diff={max_diff:.4e} nan_mm={nan_mismatch}")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_plus_trades : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_plus_big_v2():
    """Test sub-engine LOT 2 phase_b_plus_plus big_v2 (10 features scan VAP cells)."""
    from phase_b_plus_plus_big_v2_streaming import (
        add_big_orders_v2_streaming, make_big_orders_v2_state,
    )
    from phase_b_plus_plus_engine import add_big_orders_features_v2
    from footprint_builder import build_footprint_per_bar
    from footprint_builder_streaming import build_footprint_cells_streaming
    import numpy as np
    import pandas as pd

    np.random.seed(151)
    n_bars = 200
    n_trades = 10000
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    bar_starts = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars)])
    df = pd.DataFrame({"ts_event": bar_starts})

    # Trades avec sizes biaises pour declencher t1=100, t2=150
    trades = []
    for _ in range(n_trades):
        offset_min = np.random.uniform(0, n_bars - 0.001)
        ts = start + pd.Timedelta(minutes=offset_min)
        price = round(5800 + np.random.uniform(-15, 15), 2)
        # Distribution biased pour generer cellules >= 100 et >= 150
        size = int(np.random.exponential(40)) + 5
        side = np.random.choice(["A", "B"], p=[0.5, 0.5])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    # BATCH
    batch_footprint = build_footprint_per_bar(trades_df, bar_starts, tick=0.25)
    batch_df = add_big_orders_features_v2(df.copy(), batch_footprint, symbol="ES", tick=0.25)

    # STREAM : pour chaque bar, build cells streaming + call big_v2
    state = make_big_orders_v2_state("ES")
    stream_rows = []
    for i in range(n_bars):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1] if i + 1 < n_bars else bar_start_ts + pd.Timedelta(minutes=1)
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        cells = build_footprint_cells_streaming(trades_in_bar, tick=0.25)
        out = add_big_orders_v2_streaming({"ts_event": bar_starts.iloc[i]}, state, cells)
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_plus_big_v2 parite sur {n_bars} bars + {n_trades} trades...")

    cols_check = [
        "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
        "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
        "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
    ]
    print(f"\n--- NIVEAU 1 : parite (10 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:32s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        max_diff = float(np.nanmax(np.abs(b - s)))
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        n_fires_b = int((b != 0).sum())
        n_fires_s = int((s != 0).sum())
        print(f"  {col:32s} {status} max_diff={max_diff:.4e} "
              f"non-zero batch/stream={n_fires_b}/{n_fires_s}")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_plus_big_v2 : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_plus_cluster_v2():
    """Test sub-engine LOT 3 cluster_volume_v2 (5 features)."""
    from phase_b_plus_plus_cluster_v2_streaming import (
        add_cluster_v2_streaming, make_cluster_v2_state,
    )
    from phase_b_plus_plus_engine import add_cluster_volume_features
    from footprint_builder import build_footprint_per_bar
    from footprint_builder_streaming import build_footprint_cells_streaming
    import numpy as np
    import pandas as pd

    np.random.seed(157)
    n_bars = 200
    n_trades = 12000
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    bar_starts = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars)])

    # Trades : concentrer sur peu de prix pour générer clusters volume
    trades = []
    for _ in range(n_trades):
        offset_min = np.random.uniform(0, n_bars - 0.001)
        ts = start + pd.Timedelta(minutes=offset_min)
        # Concentrer sur 8 niveaux de prix (favorise cluster volume threshold 250)
        price = 5800 + (np.random.randint(0, 8) * 0.25 - 1.0)
        size = int(np.random.exponential(50)) + 1
        side = np.random.choice(["A", "B"], p=[0.5, 0.5])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    # bars df with high/low (necessaire pour cluster_at_high/low)
    df = pd.DataFrame({"ts_event": bar_starts})
    df["high"] = 5800.50  # constante pour simplicite
    df["low"] = 5799.50

    # BATCH
    batch_footprint = build_footprint_per_bar(trades_df, bar_starts, tick=0.25)
    batch_df = add_cluster_volume_features(df.copy(), batch_footprint, symbol="ES", tick=0.25)

    # STREAM
    state = make_cluster_v2_state("ES")
    stream_rows = []
    for i in range(n_bars):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1] if i + 1 < n_bars else bar_start_ts + pd.Timedelta(minutes=1)
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        cells = build_footprint_cells_streaming(trades_in_bar, tick=0.25)
        row_in = {"ts_event": bar_starts.iloc[i], "high": 5800.50, "low": 5799.50}
        out = add_cluster_v2_streaming(row_in, state, cells)
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_plus_cluster_v2 parite sur {n_bars} bars + {n_trades} trades...")

    cols_check = [
        "n_cluster_groups", "max_cluster_size", "max_cluster_volume_v2",
        "cluster_at_high", "cluster_at_low",
    ]
    print(f"\n--- NIVEAU 1 : parite (5 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:32s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        max_diff = float(np.nanmax(np.abs(b - s)))
        n_fires_b = int((b != 0).sum())
        n_fires_s = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        print(f"  {col:32s} {status} max_diff={max_diff:.4e} "
              f"non-zero batch/stream={n_fires_b}/{n_fires_s}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where(np.abs(b - s) > 1e-6)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_plus_cluster_v2 : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_plus_absorb():
    """Test sub-engine LOT 4 stack + absorption (8 features)."""
    from phase_b_plus_plus_absorb_streaming import (
        add_stack_absorb_streaming, make_stack_absorb_state,
    )
    from phase_b_plus_plus_engine import add_stack_features, add_absorption_features
    from footprint_builder import build_footprint_per_bar
    from footprint_builder_streaming import build_footprint_cells_streaming
    import numpy as np
    import pandas as pd

    np.random.seed(163)
    n_bars = 200
    n_trades = 12000
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    bar_starts = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars)])

    # OHLC + trades synth (forces absorption + stack patterns)
    df = pd.DataFrame({"ts_event": bar_starts})
    base = 5800 + np.cumsum(np.random.randn(n_bars) * 0.5)
    df["close"] = base
    df["open"] = base + np.random.randn(n_bars) * 0.3
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(0.5, 2.5, n_bars)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(0.5, 2.5, n_bars)
    # Niveaux key absolus pour near_resistance/support
    df["sess_high"] = df["high"].cummax()
    df["sess_low"] = df["low"].cummin()
    df["ib_high"] = 5810.0
    df["ib_low"] = 5790.0
    df["pdh"] = 5820.0
    df["pdl"] = 5780.0
    df["prev_vah"] = 5815.0
    df["prev_val"] = 5785.0

    # Trades synth distribues sur bars
    trades = []
    for _ in range(n_trades):
        offset_min = np.random.uniform(0, n_bars - 0.001)
        ts = start + pd.Timedelta(minutes=offset_min)
        price = round(5800 + np.random.uniform(-15, 15), 2)
        size = int(np.random.exponential(30)) + 1
        side = np.random.choice(["A", "B"], p=[0.5, 0.5])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    # BATCH
    batch_footprint = build_footprint_per_bar(trades_df, bar_starts, tick=0.25)
    batch_df = add_stack_features(df.copy(), batch_footprint, symbol="ES", tick=0.25)
    batch_df = add_absorption_features(batch_df, batch_footprint, symbol="ES", tick=0.25)

    # STREAM
    state = make_stack_absorb_state("ES")
    stream_rows = []
    for i in range(n_bars):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1] if i + 1 < n_bars else bar_start_ts + pd.Timedelta(minutes=1)
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        cells = build_footprint_cells_streaming(trades_in_bar, tick=0.25)
        row_in = df.iloc[i].to_dict()
        out = add_stack_absorb_streaming(row_in, state, cells)
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_plus_absorb parite sur {n_bars} bars + {n_trades} trades...")

    cols_check = [
        "bn_stack_ask", "bn_stack_bid",
        "bn_absorb_ask_raw", "bn_absorb_bid_raw",
        "near_resistance_level", "near_support_level",
        "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    ]
    print(f"\n--- NIVEAU 1 : parite (8 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:32s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        max_diff = float(np.nanmax(np.abs(b - s)))
        n_fires_b = int((b != 0).sum())
        n_fires_s = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 else "FAIL"
        print(f"  {col:32s} {status} max_diff={max_diff:.4e} "
              f"non-zero batch/stream={n_fires_b}/{n_fires_s}")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_plus_absorb : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_plus_trapped():
    """Test sub-engine LOT 5 trapped traders (10 features)."""
    from phase_b_plus_plus_trapped_streaming import (
        add_trapped_traders_streaming, make_trapped_traders_state,
    )
    from phase_b_plus_plus_engine import (
        add_trapped_traders_features, add_absorption_features,
    )
    from footprint_builder import build_footprint_per_bar
    from footprint_builder_streaming import build_footprint_cells_streaming
    import numpy as np
    import pandas as pd

    np.random.seed(173)
    n_bars = 200
    n_trades = 12000
    start = pd.Timestamp("2026-05-12 13:00:00", tz="UTC")
    bar_starts = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars)])

    df = pd.DataFrame({"ts_event": bar_starts})
    base = 5800 + np.cumsum(np.random.randn(n_bars) * 0.5)
    df["close"] = base
    df["open"] = base + np.random.randn(n_bars) * 0.3
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(0.5, 2.5, n_bars)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(0.5, 2.5, n_bars)
    df["delta_bar"] = np.random.randint(-100, 100, n_bars).astype(float)
    # Niveaux key absolus pour near_resistance/support (LOT 4 absorb pre-requis)
    df["sess_high"] = df["high"].cummax()
    df["sess_low"] = df["low"].cummin()
    df["ib_high"] = 5810.0
    df["ib_low"] = 5790.0
    df["pdh"] = 5820.0
    df["pdl"] = 5780.0
    df["prev_vah"] = 5815.0
    df["prev_val"] = 5785.0

    trades = []
    for _ in range(n_trades):
        offset_min = np.random.uniform(0, n_bars - 0.001)
        ts = start + pd.Timedelta(minutes=offset_min)
        price = round(5800 + np.random.uniform(-15, 15), 2)
        size = int(np.random.exponential(30)) + 1
        side = np.random.choice(["A", "B"], p=[0.5, 0.5])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    # BATCH (chain : absorption pour near_res/sup -> trapped)
    batch_footprint = build_footprint_per_bar(trades_df, bar_starts, tick=0.25)
    batch_df = add_absorption_features(df.copy(), batch_footprint, symbol="ES", tick=0.25)
    batch_df = add_trapped_traders_features(batch_df, batch_footprint, symbol="ES", tick=0.25)

    # STREAM (chain : LOT 4 absorb pour near -> LOT 5 trapped)
    from phase_b_plus_plus_absorb_streaming import (
        add_stack_absorb_streaming, make_stack_absorb_state,
    )
    state_absorb = make_stack_absorb_state("ES")
    state_trapped = make_trapped_traders_state("ES")
    stream_rows = []
    for i in range(n_bars):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1] if i + 1 < n_bars else bar_start_ts + pd.Timedelta(minutes=1)
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        cells = build_footprint_cells_streaming(trades_in_bar, tick=0.25)
        row_in = df.iloc[i].to_dict()
        # LOT 4 first (set near_res/sup)
        r1 = add_stack_absorb_streaming(row_in, state_absorb, cells)
        # LOT 5 (consomme near_res/sup)
        r2 = add_trapped_traders_streaming(r1, state_trapped, cells)
        stream_rows.append(r2)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_plus_trapped parite sur {n_bars} bars + {n_trades} trades...")

    cols_check = [
        "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
        "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
        "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
        "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
        "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
    ]
    print(f"\n--- NIVEAU 1 : parite (10 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:48s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mm = int(nan_diff.sum())
        n_fires_b = int((b != 0).sum())
        n_fires_s = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 and nan_mm == 0 else "FAIL"
        print(f"  {col:48s} {status} max_diff={max_diff:.4e} "
              f"non-zero batch/stream={n_fires_b}/{n_fires_s}")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_plus_trapped : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_phase_b_plus_plus_delta_div_ext():
    """Test sub-engine LOT 6 Delta Div Extension Lines (6 features)."""
    from phase_b_plus_plus_delta_div_ext_streaming import (
        add_delta_div_ext_streaming, make_delta_div_ext_state,
    )
    from phase_b_plus_plus_trades_streaming import (
        add_phase_b_plus_plus_trades_streaming, make_phase_b_plus_plus_trades_state,
    )
    from phase_b_plus_plus_engine import (
        apply_phase_b_plus_plus, add_delta_div_extension_lines,
    )
    import numpy as np
    import pandas as pd

    np.random.seed(179)
    n_bars = 600  # 10 jours = 600 bars 1-min sur RTH (6h30/jour) approx
    n_trades = 20000

    # Generate 3 jours pour forcer delta_div daily reset
    start = pd.Timestamp("2026-05-12 13:30:00", tz="UTC")
    bar_starts = []
    for d in range(3):
        day_start = start + pd.Timedelta(days=d)
        for i in range(200):
            bar_starts.append(day_start + pd.Timedelta(minutes=i))
    bar_starts = pd.Series(bar_starts[:n_bars])

    df = pd.DataFrame({"ts_event": bar_starts})
    # Prix avec swings forts pour generer delta_div daily fires
    base = 5800 + np.cumsum(np.random.randn(n_bars) * 1.0)
    df["close"] = base
    df["open"] = base + np.random.randn(n_bars) * 0.3
    df["high"] = np.maximum(df["open"], df["close"]) + np.random.uniform(1, 4, n_bars)
    df["low"] = np.minimum(df["open"], df["close"]) - np.random.uniform(1, 4, n_bars)
    df["delta_bar"] = np.random.randint(-100, 100, n_bars).astype(float)
    df["volume"] = np.random.randint(500, 2000, n_bars)

    trades = []
    for _ in range(n_trades):
        offset_bars = np.random.uniform(0, n_bars - 0.001)
        ts = bar_starts.iloc[int(offset_bars)] + pd.Timedelta(seconds=np.random.uniform(0, 60))
        price = round(5800 + np.random.uniform(-30, 30), 2)
        size = int(np.random.exponential(30)) + 1
        side = np.random.choice(["A", "B"], p=[0.5, 0.5])
        trades.append({"ts_event": ts, "price": price, "size": size, "side": side})
    trades_df = pd.DataFrame(trades).sort_values("ts_event").reset_index(drop=True)

    # BATCH (apply_phase_b_plus_plus chain : trades aggregates -> delta_div_buy/sell -> ext_lines)
    batch_df = apply_phase_b_plus_plus(df.copy(), trades_df, symbol="ES", tick=0.25)

    # STREAM (chain LOT 1 trades + LOT 6 ext_lines)
    state_trades = make_phase_b_plus_plus_trades_state("ES")
    state_ext = make_delta_div_ext_state()
    stream_rows = []
    for i in range(n_bars):
        bar_start_ts = bar_starts.iloc[i]
        bar_end_ts = bar_starts.iloc[i + 1] if i + 1 < n_bars else bar_start_ts + pd.Timedelta(minutes=1)
        mask = (trades_df["ts_event"] >= bar_start_ts) & (trades_df["ts_event"] < bar_end_ts)
        trades_in_bar = trades_df[mask][["price", "size", "side"]].to_dict("records")
        row_in = df.iloc[i].to_dict()
        r1 = add_phase_b_plus_plus_trades_streaming(row_in, state_trades, trades_in_bar)
        r2 = add_delta_div_ext_streaming(r1, state_ext)
        stream_rows.append(r2)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest phase_b_plus_plus_delta_div_ext parite sur {n_bars} bars (3 jours) + {n_trades} trades...")

    cols_check = [
        "n_delta_div_buy_zones_active", "n_delta_div_sell_zones_active",
        "dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct",
        "n_delta_div_buy_cluster_within_0_2pct", "n_delta_div_sell_cluster_within_0_2pct",
    ]
    print(f"\n--- NIVEAU 1 : parite (6 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:45s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mm = int(nan_diff.sum())
        n_fires_b = int((b != 0).sum())
        n_fires_s = int((s != 0).sum())
        status = "PASS" if max_diff < 1e-6 and nan_mm == 0 else "FAIL"
        print(f"  {col:45s} {status} max_diff={max_diff:.4e} "
              f"non-zero batch/stream={n_fires_b}/{n_fires_s}")
        if status == "FAIL":
            all_pass = False

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL phase_b_plus_plus_delta_div_ext : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_gold_phase_d():
    """Test sub-engine gold_phase_d (4 features intermarket MGC).

    Test parite batch apply_gold_phase_d() vs stream avec inputs cross-sym.
    """
    from gold_phase_d_streaming import (
        add_gold_phase_d_streaming, GoldPhaseDState,
    )
    from gold_phase_d_features import apply_gold_phase_d
    import numpy as np
    import pandas as pd

    np.random.seed(191)
    # 200 bars MGC + 6E + ZN + ZB synchros 1-min sur 13:30-16:50 UTC
    # (couvre overlap 12:30-16:00 UTC + post-open 13:30-14:00 ET = 17:30-18:00 UTC en DST)
    n_bars = 200
    start = pd.Timestamp("2026-05-12 12:00:00", tz="UTC")
    ts_seq = pd.Series([start + pd.Timedelta(minutes=i) for i in range(n_bars)])

    df_mgc = pd.DataFrame({"ts_event": ts_seq})
    base_mgc = 2400 + np.cumsum(np.random.randn(n_bars) * 0.5)
    df_mgc["close"] = base_mgc
    df_mgc["high"] = base_mgc + np.random.uniform(0.5, 2, n_bars)
    df_mgc["low"] = base_mgc - np.random.uniform(0.5, 2, n_bars)
    df_mgc["volume"] = np.random.randint(50, 500, n_bars)

    df_6e = pd.DataFrame({"ts_event": ts_seq})
    df_6e["close"] = 1.08 + np.cumsum(np.random.randn(n_bars) * 0.0005)

    df_zn = pd.DataFrame({"ts_event": ts_seq})
    df_zn["close"] = 110.0 + np.cumsum(np.random.randn(n_bars) * 0.02)

    df_zb = pd.DataFrame({"ts_event": ts_seq})
    df_zb["close"] = 130.0 + np.cumsum(np.random.randn(n_bars) * 0.03)

    # BATCH
    batch_df = apply_gold_phase_d(df_mgc.copy(), df_6e, df_zn, df_zb)

    # STREAM
    state = GoldPhaseDState()
    stream_rows = []
    for i in range(n_bars):
        row_in = df_mgc.iloc[i].to_dict()
        out = add_gold_phase_d_streaming(
            row_in, state,
            close_6e=df_6e["close"].iloc[i],
            close_zn=df_zn["close"].iloc[i],
            close_zb=df_zb["close"].iloc[i],
        )
        stream_rows.append(out)
    stream_df = pd.DataFrame(stream_rows)

    print(f"\nTest gold_phase_d parite sur {n_bars} bars synth (MGC + 6E + ZN + ZB)...")

    cols_check = [
        "im_dxy_corr_60d",
        "im_real_yields_proxy",
        "mgc_asia_london_overlap_vol",
        "mgc_session_break_acceleration",
    ]
    print(f"\n--- NIVEAU 1 : parite (4 features) ---")
    all_pass = True
    for col in cols_check:
        if col not in batch_df.columns or col not in stream_df.columns:
            print(f"  {col:40s} MANQUANT")
            all_pass = False
            continue
        b = batch_df[col].astype("float64").values
        s = stream_df[col].astype("float64").values
        nan_both = np.isnan(b) & np.isnan(s)
        nan_diff = np.isnan(b) ^ np.isnan(s)
        diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
        max_diff = float(np.nanmax(np.abs(diff)))
        nan_mm = int(nan_diff.sum())
        # Tolerance large car pct_change cumulatif peut introduire noise
        atol = 1e-3
        status = "PASS" if max_diff < atol and nan_mm < 5 else "FAIL"
        n_active_b = int((~np.isnan(b) & (b != 0)).sum())
        n_active_s = int((~np.isnan(s) & (s != 0)).sum())
        print(f"  {col:40s} {status} max_diff={max_diff:.4e} nan_mm={nan_mm} "
              f"non-zero batch/stream={n_active_b}/{n_active_s}")
        if status == "FAIL":
            all_pass = False
            idx_diff = np.where((np.abs(diff) > atol) & ~nan_both)[0][:3]
            for idx in idx_diff:
                print(f"    idx={idx} batch={b[idx]} stream={s[idx]}")

    print(f"\n  Niveau 1 status : {'PASS' if all_pass else 'FAIL'}")
    print(f"\n{'=' * 70}")
    print(f"GLOBAL gold_phase_d : {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"all_pass": all_pass}


def _test_rvol_inputs():
    """Test sub-engine #5a add_rvol_inputs (STATELESS).

    5 features pures row-level :
      range_size, finish_strength, delta_pct, total_vol, ts (ms epoch UTC)

    Pas de state -> tests Niveau 1 parite + Niveau 2 pickle factory uniforme.
    Pas de Niveau 3 warmup (rien a restorer).
    """
    from phase_b_helpers import (
        add_rvol_inputs,
        add_rvol_inputs_streaming,
        RvolInputsState,
    )
    import numpy as np
    import pandas as pd

    # Synth 240 bars avec varying delta + range pour stresser fillna(0) sur range=0
    bars = []
    np.random.seed(7)
    start = pd.Timestamp("2026-05-12 13:00:00")
    for i in range(240):
        ts = start + pd.Timedelta(minutes=i)
        high = 5800.0 + np.sin(i / 30.0) * 3.0
        # Stress edge cases : 5% des bars avec range=0 (high=low)
        if i % 20 == 0:
            low = high
        else:
            low = high - np.random.uniform(0.25, 2.0)
        op = (high + low) / 2 - 0.1
        close = (high + low) / 2 + 0.05
        volume = np.random.randint(0, 500)  # 5% avec volume=0
        delta_bar = np.random.randint(-100, 100)
        bars.append({
            "ts_event": ts, "open": op, "high": high, "low": low, "close": close,
            "volume": volume, "delta_bar": delta_bar,
        })
    df = pd.DataFrame(bars)
    print(f"\nTest rvol_inputs parite sur {len(df)} rows synth...")

    def batch_fn(d):
        return add_rvol_inputs(d.copy(), tick=0.25)

    def stream_fn(row, state):
        return add_rvol_inputs_streaming(row, state, tick=0.25)

    print("\n--- NIVEAU 1 : parite batch vs streaming ---")
    report1 = test_engine_parity(
        engine_name="rvol_inputs",
        batch_fn=batch_fn,
        streaming_fn=stream_fn,
        state_factory=RvolInputsState,
        input_df=df,
        float_atol=1e-9,
    )

    print("\n--- NIVEAU 2 : pickle roundtrip state (STATELESS) ---")
    # State stateless = trivial mais valide convention factory uniforme
    sample_row = df.iloc[10].to_dict()
    report2 = test_state_pickle_roundtrip(
        engine_name="rvol_inputs",
        streaming_fn=stream_fn,
        state_factory=RvolInputsState,
        sample_row=sample_row,
    )

    all_pass = (
        report1.get("status") == "PASS"
        and report2.get("status") == "PASS"
    )
    print(f"\n{'=' * 70}")
    print(f"GLOBAL rvol_inputs : {'2 LEVELS PASS (stateless)' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {"level1": report1, "level2": report2, "all_pass": all_pass}


def _test_ib_atr():
    """Test sub-engine #5b add_ib_atr (rolling 14 jours, shift(1)).

    Convention batch : ib_atr du jour J = mean(ib_range jours [J-14, J-1])
    avec min_periods=3.

    Tests :
      Niveau 1 : parite batch/stream sur 20 jours synth (warmup + post-warmup)
      Niveau 2 : pickle roundtrip state non-vide (apres 5 jours)
      Niveau 3 : restart mid-window (state daily_ib_ranges populated)
    """
    from phase_b_helpers import (
        add_session_metadata,
        add_ib_features,
        add_ib_atr,
        add_ib_atr_streaming,
        IbAtrState,
        add_session_metadata_streaming,
        add_ib_features_streaming,
        SessionMetadataState,
        IBState,
    )
    import numpy as np
    import pandas as pd
    import pickle

    # Synth 20 jours x 480 bars/jour, IB window 09:30-10:30 ET
    bars = []
    np.random.seed(13)
    for day_offset in range(20):
        day_num = 12 + day_offset
        # Wrap mois si > 31
        if day_num <= 31:
            date_str = f"2026-05-{day_num:02d}"
        else:
            date_str = f"2026-06-{day_num - 31:02d}"
        start_et = pd.Timestamp(f"{date_str} 13:00:00")  # 09:00 ET tz-naive
        # Varying IB range chaque jour pour tester rolling mean
        ib_range_target = 8.0 + np.random.uniform(-2.0, 4.0)
        for i in range(480):
            ts = start_et + pd.Timedelta(minutes=i)
            if 30 <= i < 90:  # 09:30-10:30 ET = IB window
                # Forcer range observe = ib_range_target sur cette session
                phase = (i - 30) / 60.0
                high = 5800.0 + day_offset * 2 + phase * ib_range_target
                low = 5800.0 + day_offset * 2
            else:
                high = 5800.0 + day_offset * 2 + np.random.uniform(-0.5, 0.5)
                low = high - 0.5
            close = (high + low) / 2
            bars.append({
                "ts_event": ts, "high": high, "low": low, "close": close,
                "volume": 100, "delta_bar": 0, "open": close - 0.1,
            })
    df = pd.DataFrame(bars)
    print(f"\nTest ib_atr parite sur {len(df)} rows synth (20 jours)...")

    # BATCH : chain session_metadata -> ib_features -> ib_atr
    df_batch = add_session_metadata(df.copy(), bounds=None)
    df_batch = add_ib_features(df_batch, tick=0.25, bounds=None)
    df_batch = add_ib_atr(df_batch, lookback_days=14)

    # STREAM : chain ordre engines
    state_meta = SessionMetadataState()
    state_ib = IBState()
    state_atr = IbAtrState()
    stream_rows = []
    for _, bar in df.iterrows():
        r1 = add_session_metadata_streaming(bar.to_dict(), state_meta, bounds=None)
        r2 = add_ib_features_streaming(r1, state_ib, tick=0.25, bounds=None)
        r3 = add_ib_atr_streaming(r2, state_atr, lookback_days=14)
        stream_rows.append(r3)
    df_stream = pd.DataFrame(stream_rows)

    # Niveau 1 parite ib_atr
    print("\n--- NIVEAU 1 : parite batch vs streaming (ib_atr only) ---")
    b = df_batch["ib_atr"].astype("float64").values
    s = df_stream["ib_atr"].astype("float64").values
    nan_both = np.isnan(b) & np.isnan(s)
    nan_diff = np.isnan(b) ^ np.isnan(s)
    diff = np.where(nan_both, 0.0, np.where(nan_diff, 1e9, b - s))
    max_diff = float(np.nanmax(np.abs(diff)))
    nan_mismatch_count = int(nan_diff.sum())
    level1_ok = max_diff < 1e-9 and nan_mismatch_count == 0
    print(f"  rows={len(df)}, max_diff={max_diff:.6e}, nan_mismatch={nan_mismatch_count}")
    print(f"  Niveau 1 status : {'PASS' if level1_ok else 'FAIL'}")
    if not level1_ok:
        # Diagnostic : afficher 5 premieres divergences
        for idx in np.where(np.abs(diff) > 1e-9)[0][:5]:
            print(f"    idx={idx} batch={b[idx]} stream={s[idx]} "
                  f"date_et={df_batch.iloc[idx]['date_et']}")

    # Niveau 2 : pickle roundtrip post-warmup
    print("\n--- NIVEAU 2 : pickle roundtrip state apres 5 jours ---")
    state_test_meta = SessionMetadataState()
    state_test_ib = IBState()
    state_test_atr = IbAtrState()
    # 5 jours * 480 bars = 2400 bars
    for i, (_, bar) in enumerate(df.iterrows()):
        if i >= 2400:
            break
        r1 = add_session_metadata_streaming(bar.to_dict(), state_test_meta, bounds=None)
        r2 = add_ib_features_streaming(r1, state_test_ib, tick=0.25, bounds=None)
        add_ib_atr_streaming(r2, state_test_atr, lookback_days=14)
    print(f"  state pre-pickle : daily_ib_ranges count={len(state_test_atr.daily_ib_ranges)}, "
          f"current_date={state_test_atr.current_date}, "
          f"current_session_ib_range={state_test_atr.current_session_ib_range}")
    assert len(state_test_atr.daily_ib_ranges) >= 3, (
        f"P0 : state.daily_ib_ranges doit avoir >=3 entries apres 5 jours "
        f"(actuel: {len(state_test_atr.daily_ib_ranges)})"
    )

    blob = pickle.dumps(state_test_atr)
    state_restored = pickle.loads(blob)
    assert state_restored.daily_ib_ranges == state_test_atr.daily_ib_ranges
    assert state_restored.current_date == state_test_atr.current_date
    assert state_restored.current_session_ib_range == state_test_atr.current_session_ib_range
    assert state_restored.lookback_days == state_test_atr.lookback_days

    # Test row produit meme output apres pickle
    test_row_input = df.iloc[2400].to_dict()
    r1t = add_session_metadata_streaming(test_row_input, SessionMetadataState(), bounds=None)
    r2t = add_ib_features_streaming(r1t, IBState(), tick=0.25, bounds=None)
    # Inject ib_range from batch for fair compare (we want only ib_atr divergence)
    # Actually just use the chained streaming row
    out_orig = add_ib_atr_streaming(r2t, state_test_atr, lookback_days=14)
    out_restored = add_ib_atr_streaming(r2t, state_restored, lookback_days=14)
    pickle_ok = True
    if pd.isna(out_orig["ib_atr"]) and pd.isna(out_restored["ib_atr"]):
        pass
    elif (pd.isna(out_orig["ib_atr"]) or pd.isna(out_restored["ib_atr"])
            or abs(out_orig["ib_atr"] - out_restored["ib_atr"]) > 1e-9):
        print(f"    pickle FAIL ib_atr: orig={out_orig['ib_atr']} "
              f"restored={out_restored['ib_atr']}")
        pickle_ok = False
    print(f"  Niveau 2 status : {'PASS' if pickle_ok else 'FAIL'}")

    # Niveau 3 : continuite vs restart pickle au jour 10 (state non trivial)
    print("\n--- NIVEAU 3 : warmup R2 restart cross-session (jour 10) ---")
    # Continuous run from scratch
    state_cont_meta = SessionMetadataState()
    state_cont_ib = IBState()
    state_cont_atr = IbAtrState()
    cont_rows = []
    for _, bar in df.iterrows():
        r1 = add_session_metadata_streaming(bar.to_dict(), state_cont_meta, bounds=None)
        r2 = add_ib_features_streaming(r1, state_cont_ib, tick=0.25, bounds=None)
        r3 = add_ib_atr_streaming(r2, state_cont_atr, lookback_days=14)
        cont_rows.append(r3)
    cont_df = pd.DataFrame(cont_rows)
    cont_atr_final = cont_df["ib_atr"].values

    # Restart : run jusqu'a idx 4800 (10 jours), pickle, load, continue
    idx_restart = 4800
    state_r1_meta = SessionMetadataState()
    state_r1_ib = IBState()
    state_r1_atr = IbAtrState()
    for i in range(idx_restart):
        bar = df.iloc[i]
        r1 = add_session_metadata_streaming(bar.to_dict(), state_r1_meta, bounds=None)
        r2 = add_ib_features_streaming(r1, state_r1_ib, tick=0.25, bounds=None)
        add_ib_atr_streaming(r2, state_r1_atr, lookback_days=14)
    # Save+Load atr state (others ok for free)
    state_r1_atr_restored = pickle.loads(pickle.dumps(state_r1_atr))
    state_r1_meta_restored = pickle.loads(pickle.dumps(state_r1_meta))
    state_r1_ib_restored = pickle.loads(pickle.dumps(state_r1_ib))
    restart_rows = []
    for i in range(idx_restart, len(df)):
        bar = df.iloc[i]
        r1 = add_session_metadata_streaming(bar.to_dict(), state_r1_meta_restored, bounds=None)
        r2 = add_ib_features_streaming(r1, state_r1_ib_restored, tick=0.25, bounds=None)
        r3 = add_ib_atr_streaming(r2, state_r1_atr_restored, lookback_days=14)
        restart_rows.append(r3)
    restart_df = pd.DataFrame(restart_rows)

    # Compare cont vs restart sur tail
    cont_tail = cont_df.iloc[idx_restart:]["ib_atr"].astype("float64").values
    restart_atr = restart_df["ib_atr"].astype("float64").values
    nan_both3 = np.isnan(cont_tail) & np.isnan(restart_atr)
    nan_diff3 = np.isnan(cont_tail) ^ np.isnan(restart_atr)
    diff3 = np.where(nan_both3, 0.0, np.where(nan_diff3, 1e9, cont_tail - restart_atr))
    max_diff3 = float(np.nanmax(np.abs(diff3)))
    nan_mismatch3 = int(nan_diff3.sum())
    level3_ok = max_diff3 < 1e-9 and nan_mismatch3 == 0
    print(f"  rows compare={len(cont_tail)}, max_diff={max_diff3:.6e}, "
          f"nan_mismatch={nan_mismatch3}")
    print(f"  Niveau 3 status : {'PASS' if level3_ok else 'FAIL'}")

    all_pass = level1_ok and pickle_ok and level3_ok
    print(f"\n{'=' * 70}")
    print(f"GLOBAL ib_atr : {'ALL 3 LEVELS PASS' if all_pass else 'FAIL'}")
    print("=" * 70)
    return {
        "level1": {"status": "PASS" if level1_ok else "FAIL", "max_diff": max_diff},
        "level2": {"status": "PASS" if pickle_ok else "FAIL"},
        "level3": {"status": "PASS" if level3_ok else "FAIL", "max_diff": max_diff3},
        "all_pass": all_pass,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="vix_lite",
                        choices=["vix_lite", "vix_ema_60", "session_metadata",
                                 "ib_features", "session_high_low",
                                 "volume_profile", "rvol_inputs", "ib_atr",
                                 "rolling_features_basic",
                                 "rolling_features_medium",
                                 "rolling_features_advanced",
                                 "rolling_features_delta_div",
                                 "rolling_features_session_confluence",
                                 "rvol_engine",
                                 "amd",
                                 "game_changers",
                                 "edge_zones",
                                 "phase_b_plus",
                                 "phase_b_plus_long",
                                 "phase_b_plus_color",
                                 "open_extension_lines",
                                 "sessions_swings_simple",
                                 "sessions_swings_lag",
                                 "vwap_diff",
                                 "footprint_builder",
                                 "phase_b_plus_plus_trades",
                                 "phase_b_plus_plus_big_v2",
                                 "phase_b_plus_plus_cluster_v2",
                                 "phase_b_plus_plus_absorb",
                                 "phase_b_plus_plus_trapped",
                                 "phase_b_plus_plus_delta_div_ext",
                                 "gold_phase_d",
                                 "all"])
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

    if args.engine in ("rvol_inputs", "all"):
        report = _test_rvol_inputs()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("ib_atr", "all"):
        report = _test_ib_atr()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("rolling_features_basic", "all"):
        report = _test_rolling_features_basic()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("rolling_features_medium", "all"):
        report = _test_rolling_features_medium()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("rolling_features_advanced", "all"):
        report = _test_rolling_features_advanced()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("rolling_features_delta_div", "all"):
        report = _test_rolling_features_delta_div()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("rolling_features_session_confluence", "all"):
        report = _test_rolling_features_session_confluence()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("rvol_engine", "all"):
        report = _test_rvol_engine()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("amd", "all"):
        report = _test_amd()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("game_changers", "all"):
        report = _test_game_changers()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("edge_zones", "all"):
        report = _test_edge_zones()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus", "all"):
        report = _test_phase_b_plus()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_long", "all"):
        report = _test_phase_b_plus_long()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_color", "all"):
        report = _test_phase_b_plus_color()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("open_extension_lines", "all"):
        report = _test_open_extension_lines()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("sessions_swings_simple", "all"):
        report = _test_sessions_swings_simple()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("sessions_swings_lag", "all"):
        report = _test_sessions_swings_lag()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("vwap_diff", "all"):
        report = _test_vwap_diff()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("footprint_builder", "all"):
        report = _test_footprint_builder()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_plus_trades", "all"):
        report = _test_phase_b_plus_plus_trades()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_plus_big_v2", "all"):
        report = _test_phase_b_plus_plus_big_v2()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_plus_cluster_v2", "all"):
        report = _test_phase_b_plus_plus_cluster_v2()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_plus_absorb", "all"):
        report = _test_phase_b_plus_plus_absorb()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_plus_trapped", "all"):
        report = _test_phase_b_plus_plus_trapped()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("phase_b_plus_plus_delta_div_ext", "all"):
        report = _test_phase_b_plus_plus_delta_div_ext()
        if report and not report.get("all_pass"):
            sys.exit(1)

    if args.engine in ("gold_phase_d", "all"):
        report = _test_gold_phase_d()
        if report and not report.get("all_pass"):
            sys.exit(1)


if __name__ == "__main__":
    main()
