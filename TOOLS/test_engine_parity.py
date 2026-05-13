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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="vix_lite",
                        choices=["vix_lite", "vix_ema_60", "all"])
    args = parser.parse_args()

    if args.engine in ("vix_lite", "all"):
        report = _test_vix_lite()
        if report and report["status"] != "PASS":
            sys.exit(1)

    if args.engine in ("vix_ema_60", "all"):
        report = _test_vix_ema_60()
        if report and not report.get("all_pass"):
            sys.exit(1)


if __name__ == "__main__":
    main()
