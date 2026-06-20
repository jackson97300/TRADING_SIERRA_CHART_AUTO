"""Tests FIX B.5 BN_V4_WARMUP_SKIP emit visible (schema-auditor 19/06).

Avant fix : check_zone retournait None silencieusement pendant warmup
(i < trend_long_lookback). Empirique : 0/1554 BN_V4_GATE_* emit dans logs
production 18/06 alors que 1554 NO_SETUP decisions JSONL = impossible de
diagnostiquer si warmup vs gate qui bloque.

Apres fix : emit BN_V4_WARMUP_SKIP avec compteur missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_log_code_bn_v4_warmup_skip_registered():
    """Code log BN_V4_WARMUP_SKIP doit etre dans log_catalog."""
    from CORE.log_catalog import LOG_CODES
    from CORE.logging_v2 import LogLevel

    assert "BN_V4_WARMUP_SKIP" in LOG_CODES
    level, category, template = LOG_CODES["BN_V4_WARMUP_SKIP"]
    assert level == LogLevel.INFO, "WARMUP_SKIP = INFO (frequent par design)"
    assert category == "decisions"


def test_source_check_zone_emits_warmup():
    """check_zone doit emit BN_V4_WARMUP_SKIP au lieu de silent return."""
    engine_path = _ROOT / "CORE" / "bn_v4_engine.py"
    content = engine_path.read_text(encoding="utf-8")
    # Apres fix : log_fn("BN_V4_WARMUP_SKIP", ...) AVANT le return None warmup
    assert 'log_fn("BN_V4_WARMUP_SKIP"' in content, \
        "Fix B.5 absent : check_zone doit emit BN_V4_WARMUP_SKIP"


def test_check_zone_warmup_emits_during_warmup():
    """Test fonctionnel : appeler check_zone avec i < trend_long_lookback."""
    import pandas as pd
    from CORE.bn_v4_engine import check_zone, BNV4Params

    # Capture emit
    emitted = []

    def log_fn(code, **ctx):
        emitted.append((code, ctx))

    # Params avec lookback = 240 (default BN V4)
    params = BNV4Params(
        trend_lookback=60,
        trend_long_lookback=240,
        require_open_window=False,
    )

    # DataFrame minimaliste avec i=10 < 240
    df = pd.DataFrame({
        "ts_event": [None] * 11,
        "close": [100.0] * 11,
        "high": [100.0] * 11,
        "low": [100.0] * 11,
        "vwap_slope_10": [0.001] * 11,
    })

    result = check_zone(df, 10, params, "long", log_fn=log_fn, symbol="NQ")
    assert result is None, "check_zone doit return None pendant warmup"

    # Verifier emit warmup_skip
    warmup_emits = [e for e in emitted if e[0] == "BN_V4_WARMUP_SKIP"]
    assert len(warmup_emits) == 1, \
        f"Expected 1 BN_V4_WARMUP_SKIP emit, got {len(warmup_emits)}"
    ctx = warmup_emits[0][1]
    assert ctx["i"] == 10
    assert ctx["needed"] == 240
    assert ctx["missing"] == 230
    assert ctx["sym"] == "NQ"
    assert ctx["direction"] == "long"
