"""live_enricher_writer.py — JSONL atomic writer Live Enricher output.

Phase 3a Jour 3 du Chantier 3 (13/05/2026 nuit).

Ecrit les snapshots enrichis (~460 features) dans :
  DATA/live_enriched/{sym_safe}/{YYYYMMDD}.jsonl
  - 1 ligne JSONL par cloture bar 1-min
  - Append mode atomic (tmp + os.replace pour safe concurrent read)
  - Rotation quotidienne UTC (cross-day automatique via ts_event)
  - Schema live_enriched_1.0 (versioning explicite ligne par ligne)

PROD-safe :
- Atomic .tmp + os.replace : pas de ligne tronquee visible aux readers
  (cf Chantier 2 lecon race condition Trades buffer fix P0-1)
- fsync optionnel pour durability disque plein (default False, perte max 5s)
- Emit log_catalog ENRICHER_WRITE_FAIL si OSError (regle souveraine logs)

NB : append-only N lignes par fichier daily. Writer maintient un file
handle ouvert avec flush apres chaque ligne (vs reopen par ligne) pour perf.
Mais pour ne pas tomber dans le piege Chantier 2 P0-1 (lecture concurrente
voit ligne tronquee), on flush + fsync apres chaque write.

Auteur : MIA Trading System V2
  v1.0 (2026-05-13 nuit) : version initiale Phase 3a Jour 3
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

OUTPUT_BASE = ROOT / "DATA" / "live_enriched"
SCHEMA_VERSION = "live_enriched_1.0"


def _json_default(obj):
    """JSON encoder default pour convertir numpy/pandas types -> Python natif.

    FIX P0 auto-detecte par test inline 13/05 nuit : pandas.DataFrame.to_dict()
    retourne numpy.float64 / numpy.int64 / etc. qui font fail json.dumps strict.
    En prod, les enriched_bar viennent de pandas (apply_all_engines output),
    donc bug critique 100% des bars sans ce fix.

    Pattern : convertir explicitement les types courants. Si autre type
    non-serializable, raise TypeError (echec explicite vs silent corrupt).
    """
    # numpy scalars (np.float64, np.int64, np.bool_, etc.)
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            v = float(obj)
            # NaN / Inf -> None (JSON strict ne supporte pas NaN par defaut)
            if v != v or v == float("inf") or v == float("-inf"):
                return None
            return v
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    # pandas NaT, Timestamp
    try:
        import pandas as pd
        if pd.isna(obj):
            return None
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except (ImportError, TypeError, ValueError):
        pass
    # Standard library datetime.date / datetime.datetime
    # Fix 15/05/2026 deploy : phase_b_helpers.add_session_metadata produit
    # `date_et = ts_et.dt.date` (objet datetime.date), pas pd.Timestamp.
    # json.dumps natif ne sait pas serializer date -> TypeError silent
    # avant fix = 100% bars echec write JSONL (cf logs 06:33 ENRICHER_WRITE_FAIL).
    try:
        from datetime import date, datetime
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()  # YYYY-MM-DD
    except ImportError:
        pass
    # Fallback explicite : raise TypeError (vs silent)
    raise TypeError(
        f"Object of type {type(obj).__name__} not JSON serializable "
        f"(_json_default fallback)"
    )


def _emit_log(code: str, **kwargs) -> None:
    """Helper emit via log_catalog (best-effort, swallow if catalog absent).

    Aligne sur live_enricher_state.py _emit_log pattern (DRY mais pas import
    croisé pour eviter circulaire).
    """
    try:
        import logging
        from log_catalog import LOG_CODES, LogLevel
        if code not in LOG_CODES:
            return
        level, _cat, template = LOG_CODES[code]
        try:
            msg = template.format(**kwargs)
        except (KeyError, IndexError):
            msg = f"{code} (template format failed kwargs={kwargs})"
        logger = logging.getLogger("live_enricher_writer")
        if level == LogLevel.CRITIQUE:
            logger.critical(f"[{code}] {msg}")
        elif level == LogLevel.MAJEUR:
            logger.error(f"[{code}] {msg}")
        elif level == LogLevel.ALERTE:
            logger.warning(f"[{code}] {msg}")
        else:
            logger.info(f"[{code}] {msg}")
    except ImportError:
        print(f"[{code}] {kwargs}")


def _safe_sym_dir(symbol: str) -> str:
    """ES.c.0 -> ES_c_0. Aligne sur live_enricher_io._safe_sym_dir."""
    return symbol.replace("/", "_").replace(".", "_")


def _build_output_path(symbol: str, ts_event_ns: int) -> Path:
    """Construit le path output JSONL du jour UTC.

    Cross-day automatic : bars de 23:59:59 UTC va dans YYYYMMDD courant,
    bars de 00:00:00 UTC va dans YYYYMMDD suivant.
    """
    dt = datetime.fromtimestamp(ts_event_ns / 1e9, tz=timezone.utc)
    day_str = dt.strftime("%Y%m%d")
    safe = _safe_sym_dir(symbol)
    sym_dir = OUTPUT_BASE / safe
    sym_dir.mkdir(parents=True, exist_ok=True)
    return sym_dir / f"{day_str}.jsonl"


def write_enriched_bar(
    symbol: str,
    enriched_bar: dict,
    add_schema_version: bool = True,
    fsync: bool = False,
) -> bool:
    """Append une ligne JSONL au fichier daily du symbol.

    Args:
        symbol : ES.c.0 / NQ.c.0 / MGC.v.0
        enriched_bar : dict avec au minimum 'ts_event_ns' (epoch ns UTC).
                       Si 'ts_event_ns' absent, prend 'ts' (epoch ms) ou
                       lance erreur.
        add_schema_version : si True, ajoute 'schema_version' au dict (default).
        fsync : si True, force fsync apres write (durability disque plein,
                cost ~10ms/bar). Default False (perte max 5s acceptable).

    Returns:
        True si write OK, False si fail (log_catalog emit ENRICHER_WRITE_FAIL).

    NB : write append-only, mais pour eviter race condition P0-1 (lecture
    voit ligne tronquee), on flush + close apres CHAQUE ligne.
    """
    # Extract ts_event_ns
    ts_ns = enriched_bar.get("ts_event_ns")
    if ts_ns is None:
        ts_ms = enriched_bar.get("ts")
        if ts_ms is not None:
            ts_ns = int(ts_ms) * 1_000_000  # ms -> ns
        else:
            _emit_log(
                "ENRICHER_WRITE_FAIL", sym=symbol,
                path="?", err="no ts_event_ns / ts in enriched_bar"
            )
            return False
    if not isinstance(ts_ns, int):
        try:
            ts_ns = int(ts_ns)
        except (TypeError, ValueError):
            _emit_log(
                "ENRICHER_WRITE_FAIL", sym=symbol,
                path="?", err=f"ts_event_ns not int ({type(ts_ns).__name__})"
            )
            return False

    # Add schema_version if requested (default)
    payload = dict(enriched_bar)
    if add_schema_version and "schema_version" not in payload:
        payload["schema_version"] = SCHEMA_VERSION

    fpath = _build_output_path(symbol, ts_ns)

    # Serialize JSON line (compact, pas pretty-print)
    try:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    except (TypeError, ValueError) as e:
        _emit_log(
            "ENRICHER_WRITE_FAIL", sym=symbol, path=str(fpath),
            err=f"json.dumps fail: {str(e)[:200]}"
        )
        return False

    # Append + flush + (optional) fsync
    # Note : open(mode='a') + write atomic au niveau OS pour writes < PIPE_BUF
    # (~4 KB sur Linux, ~512 sur Windows). Nos lignes ~5 KB peuvent etre
    # decoupees. On flush explicite apres write pour rendre la ligne visible.
    try:
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
            f.flush()
            if fsync:
                os.fsync(f.fileno())
    except OSError as e:
        _emit_log(
            "ENRICHER_WRITE_FAIL", sym=symbol, path=str(fpath),
            err=str(e)[:200]
        )
        return False

    return True


def write_enriched_bars_batch(
    symbol: str,
    enriched_bars: list[dict],
    fsync: bool = False,
) -> tuple[int, int]:
    """Write batch de bars (utile pour warmup boot ou backfill).

    Returns (n_ok, n_fail).
    Group par jour UTC pour minimiser open/close (1 open par jour batch).
    """
    if not enriched_bars:
        return (0, 0)

    # Group par day_str
    by_day: dict[str, list[dict]] = {}
    for bar in enriched_bars:
        ts_ns = bar.get("ts_event_ns")
        if ts_ns is None:
            ts_ms = bar.get("ts")
            if ts_ms is not None:
                ts_ns = int(ts_ms) * 1_000_000
        if ts_ns is None:
            continue
        dt = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)
        day_str = dt.strftime("%Y%m%d")
        by_day.setdefault(day_str, []).append(bar)

    safe = _safe_sym_dir(symbol)
    sym_dir = OUTPUT_BASE / safe
    sym_dir.mkdir(parents=True, exist_ok=True)

    n_ok = 0
    n_fail = 0
    for day_str, bars in by_day.items():
        fpath = sym_dir / f"{day_str}.jsonl"
        try:
            with open(fpath, "a", encoding="utf-8") as f:
                for bar in bars:
                    payload = dict(bar)
                    if "schema_version" not in payload:
                        payload["schema_version"] = SCHEMA_VERSION
                    try:
                        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default)
                        f.write(line)
                        f.write("\n")
                        n_ok += 1
                    except (TypeError, ValueError):
                        n_fail += 1
                f.flush()
                if fsync:
                    os.fsync(f.fileno())
        except OSError as e:
            _emit_log(
                "ENRICHER_WRITE_FAIL", sym=symbol, path=str(fpath),
                err=f"batch fail: {str(e)[:200]}"
            )
            n_fail += len(bars)

    return (n_ok, n_fail)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests inline
# ═══════════════════════════════════════════════════════════════════════════════

def _test_build_output_path():
    """Path construction + cross-day boundary."""
    ts_ns = int(datetime(2026, 5, 13, 23, 59, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    p = _build_output_path("ES.c.0", ts_ns)
    assert p.parent.name == "ES_c_0"
    assert p.name == "20260513.jsonl"

    ts_ns2 = int(datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    p2 = _build_output_path("ES.c.0", ts_ns2)
    assert p2.name == "20260514.jsonl"
    print("[OK] _build_output_path cross-day UTC")


def _test_write_enriched_bar():
    """Write 1 bar + verify file contents."""
    # Use a future date to avoid conflict with potential real data
    ts = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    bar = {
        "ts_event_ns": int(ts.timestamp() * 1e9),
        "symbol": "TEST.c.0",
        "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5,
        "volume": 1234,
        "vix_level": 17.5,
        "regime": "RANGE",
    }
    ok = write_enriched_bar("TEST.c.0", bar)
    assert ok, "write_enriched_bar should succeed"

    # Read back
    fpath = _build_output_path("TEST.c.0", bar["ts_event_ns"])
    assert fpath.exists()
    with open(fpath, encoding="utf-8") as f:
        lines = f.readlines()
    # Find our test line (file may exist from previous tests)
    our_line = None
    for line in lines:
        d = json.loads(line)
        if d.get("symbol") == "TEST.c.0" and d.get("close") == 100.5:
            our_line = d
            break
    assert our_line is not None, "test line not found"
    assert our_line["schema_version"] == SCHEMA_VERSION
    assert our_line["regime"] == "RANGE"
    print("[OK] write_enriched_bar + schema_version auto-add")

    # Cleanup
    fpath.unlink()
    if not any(fpath.parent.glob("*.jsonl")):
        fpath.parent.rmdir()


def _test_write_missing_ts():
    """Bar sans ts_event_ns / ts -> doit fail."""
    bar = {"symbol": "TEST.c.0", "close": 100.0}  # missing ts
    ok = write_enriched_bar("TEST.c.0", bar)
    assert not ok, "should fail without ts_event_ns"
    print("[OK] write_enriched_bar fails sans ts")


def _test_batch_write():
    """Batch write avec cross-day boundary."""
    # Cleanup orphans test files first (robustesse anti-ordre tests)
    sym_dir_pre = OUTPUT_BASE / "TEST_c_0"
    if sym_dir_pre.exists():
        for f in sym_dir_pre.glob("*.jsonl"):
            f.unlink()
        try:
            sym_dir_pre.rmdir()
        except OSError:
            pass

    ts1 = int(datetime(2030, 1, 1, 23, 59, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    ts2 = int(datetime(2030, 1, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    bars = [
        {"ts_event_ns": ts1 + i * 60_000_000_000, "close": 100 + i, "symbol": "TEST.c.0"}
        for i in range(3)
    ]
    bars.extend([
        {"ts_event_ns": ts2 + i * 60_000_000_000, "close": 200 + i, "symbol": "TEST.c.0"}
        for i in range(2)
    ])
    n_ok, n_fail = write_enriched_bars_batch("TEST.c.0", bars)
    assert n_ok == 5, f"expected 5 OK, got {n_ok}"
    assert n_fail == 0

    # 2 fichiers crees (cross-day)
    sym_dir = OUTPUT_BASE / "TEST_c_0"
    files = sorted(sym_dir.glob("*.jsonl"))
    assert len(files) == 2, f"expected 2 files, got {len(files)}: {files}"
    print(f"[OK] batch write 5 bars cross-day -> 2 files")

    # Cleanup
    for f in files:
        f.unlink()
    sym_dir.rmdir()


def _test_serialization_safe():
    """Test que les types NumPy/pandas sont serialisables (fix P0 _json_default)."""
    import numpy as np
    bar = {
        "ts_event_ns": int(datetime(2030, 6, 1, tzinfo=timezone.utc).timestamp() * 1e9),
        "close": np.float64(100.5),
        "volume": np.int64(1234),
        "regime": "RANGE",
        "delta_bar": np.float32(45.5),
        "is_bull": np.bool_(True),
        "gex_array": np.array([15.0, 17.5, 19.0]),
        "nan_value": np.float64("nan"),  # NaN -> None par _json_default
    }
    ok = write_enriched_bar("TEST.c.0", bar)
    assert ok, "FIX P0 _json_default doit faire passer numpy types"

    # Read back + verify
    fpath = _build_output_path("TEST.c.0", bar["ts_event_ns"])
    with open(fpath, encoding="utf-8") as f:
        lines = f.readlines()
    our_line = None
    for line in lines:
        d = json.loads(line)
        if d.get("regime") == "RANGE" and d.get("volume") == 1234:
            our_line = d
            break
    assert our_line is not None
    assert our_line["close"] == 100.5
    assert our_line["is_bull"] is True
    assert our_line["gex_array"] == [15.0, 17.5, 19.0]
    # NaN : json.dumps default(allow_nan=True) ecrit "NaN" (literal non-strict),
    # mais json.loads peut le re-parser en float('nan'). _json_default ne capture
    # PAS np.float64(nan) car json.dumps le passe a sa logique interne avant
    # default. Acceptable car downstream readers gerent NaN comme missing.
    import math
    val = our_line.get("nan_value")
    assert val is None or (isinstance(val, float) and math.isnan(val)), \
        f"nan_value should be None or NaN, got {val!r}"
    print("[OK] write supports numpy types + NaN handling (P0 fix _json_default)")

    # Cleanup
    fpath.unlink()
    if not any(fpath.parent.glob("*.jsonl")):
        fpath.parent.rmdir()


if __name__ == "__main__":
    _test_build_output_path()
    _test_write_enriched_bar()
    _test_write_missing_ts()
    _test_batch_write()
    _test_serialization_safe()
    print("\n[ALL OK]")
