"""Tests Plan A dedup Sierra (Prop 1B+2 atomique + Prop 3 metadata)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))
sys.path.insert(0, str(_ROOT / "BOT"))


def test_dedup_keeps_complete_bar_over_intermediate():
    """Test #1 review : 2 bars meme ts, une OHLC=None, une complete -> complete wins."""
    from CORE.research.sierra_dedup import dedup_jsonl
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "in.jsonl"
        dst = td / "out.jsonl"
        bars = [
            # Bar incomplete first (Sierra mid-formation)
            {"ts": 1781190420000, "sym": "NQ", "high": None, "low": None,
             "open": 28680.0, "close": 28685.0, "volume": None,
             "delta_bar": 0, "buy_vol": None, "sell_vol": None, "ask_pct": 0.5},
            # Bar complete later
            {"ts": 1781190420000, "sym": "NQ", "high": 28705.0, "low": 28680.0,
             "open": 28680.0, "close": 28700.0, "volume": 1000,
             "delta_bar": 50, "buy_vol": 525, "sell_vol": 475, "ask_pct": 0.55},
        ]
        with open(src, "w") as f:
            for b in bars:
                f.write(json.dumps(b) + "\n")
        stats = dedup_jsonl(src, dst)
        # Lire output
        with open(dst) as fh:
            out_bars = [json.loads(l) for l in fh.readlines()]
        assert len(out_bars) == 1
        # La complete (high=28705) wins
        assert out_bars[0]["high"] == 28705.0
        assert out_bars[0]["volume"] == 1000


def test_dedup_preserves_distinct_minutes():
    """Test #2 review : bars 13:00 et 13:01 distinctes, pas deduplicated."""
    from CORE.research.sierra_dedup import dedup_jsonl
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "in.jsonl"
        dst = td / "out.jsonl"
        bars = [
            {"ts": 1781190420000, "sym": "NQ", "high": 100, "low": 95,
             "open": 98, "close": 99, "volume": 500},
            {"ts": 1781190480000, "sym": "NQ", "high": 102, "low": 97,
             "open": 99, "close": 101, "volume": 600},
        ]
        with open(src, "w") as f:
            for b in bars:
                f.write(json.dumps(b) + "\n")
        dedup_jsonl(src, dst)
        with open(dst) as fh:
            out_bars = [json.loads(l) for l in fh.readlines()]
        assert len(out_bars) == 2  # distinct minutes preserved


def test_round_to_minute_uses_round_not_floor():
    """FIX Jackson 11/06 : ts 12:12:59 round vers 12:13:00 (nearest), PAS 12:12.

    Empirique 200 bars NQ : 31% des bars Sierra ferment a HH:MM:59.
    FLOOR collisionnait avec bar HH:MM:00 -> 31% bars perdues dedup.
    ROUND capture correctement la bar suivante.
    """
    from CORE.research.sierra_dedup import round_ts_to_minute
    # 13:12:59 UTC en ms -> round vers 13:13:00
    ts_59 = 1781183579000  # 13:12:59
    ts_13_00 = 1781183580000  # 13:13:00
    assert round_ts_to_minute(ts_59) == ts_13_00
    # 13:12:00 reste 13:12:00
    ts_00 = 1781183520000
    assert round_ts_to_minute(ts_00) == ts_00
    # Demi-minute (30s) : convention `round` Python = round-half-to-even
    # 30s = exactement 0.5 minute. Comportement deterministe documente.
    ts_30 = 1781183550000  # 13:12:30
    # 1781183550000 / 60000 = 29686392.5 -> round = 29686392 (even) -> *60000
    assert round_ts_to_minute(ts_30) == 1781183520000  # 13:12:00 (banker rounding)


def test_bars_since_boot_per_symbol():
    """Test #4 review : mode multi-symbol, compteurs ES/NQ isoles."""
    import importlib
    import BOT.run_sierra_enricher as r
    importlib.reload(r)  # reset state per test
    def mksample():
        return {"ts": 1781190420000, "sym": "ES", "close": 6700.0,
                 "high": 6705, "low": 6695, "open": 6698, "volume": 100,
                 "im_cross_delta_agreement_5": 0.5}
    s1 = mksample(); r._inject_observability_metadata(s1, "ES"); out_es1 = s1
    s2 = mksample(); r._inject_observability_metadata(s2, "ES"); out_es2 = s2
    s3 = mksample(); r._inject_observability_metadata(s3, "NQ"); out_nq1 = s3
    assert out_es2["bars_since_boot"] == 2
    assert out_nq1["bars_since_boot"] == 1
    # boot_id identique
    assert out_es1["boot_id"] == out_nq1["boot_id"]


def test_data_quality_flag_warmup_to_stable():
    """Test #5 review : compteur warmup (1-9) puis stable (10+)."""
    import importlib
    import BOT.run_sierra_enricher as r
    importlib.reload(r)
    sample = {"ts": 1781190420000, "sym": "ES", "close": 6700.0,
              "high": 6705, "low": 6695, "open": 6698, "volume": 100,
              "im_cross_delta_agreement_5": 0.5}
    flags = []
    for _ in range(12):
        r._inject_observability_metadata(sample, "ES"); out = sample
        flags.append(out["data_quality_flag"])
    # 9 first warmup, 10+ stable
    assert flags[0] == "warmup"
    assert flags[8] == "warmup"  # 9eme bar = warmup (< 10 threshold)
    assert flags[9] == "stable"  # 10eme bar = stable
    assert flags[-1] == "stable"


def test_data_quality_flag_degraded_when_im_nan():
    """Test bonus : im_* NaN apres warmup -> degraded."""
    import importlib
    import math
    import BOT.run_sierra_enricher as r
    importlib.reload(r)
    # 10 bars stable warmup
    sample = {"ts": 1781190420000, "sym": "ES", "close": 6700.0,
              "im_cross_delta_agreement_5": 0.5}
    for _ in range(11):
        r._inject_observability_metadata(sample, "ES")
    # Bar 12 avec im_* NaN
    bad = {"ts": 1781190420000, "sym": "ES", "close": 6700.0,
           "im_cross_delta_agreement_5": float("nan")}
    r._inject_observability_metadata(bad, "ES")
    assert bad["data_quality_flag"] == "degraded"


def test_dedup_skip_before_idx():
    """Etape 0 1A : skip bars avant idx (exclu runs pre-deploy OHLCV=None)."""
    from CORE.research.sierra_dedup import dedup_jsonl
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "in.jsonl"
        dst = td / "out.jsonl"
        # 3 bars : 2 pre-deploy incompletes + 1 post complete
        bars = [
            {"ts": 1781190420000, "sym": "NQ", "high": None, "volume": None,
             "open": 1, "close": 2, "low": None},
            {"ts": 1781190480000, "sym": "NQ", "high": None, "volume": None,
             "open": 3, "close": 4, "low": None},
            {"ts": 1781190540000, "sym": "NQ", "high": 10, "low": 5,
             "open": 7, "close": 9, "volume": 100},
        ]
        with open(src, "w") as f:
            for b in bars:
                f.write(json.dumps(b) + "\n")
        stats = dedup_jsonl(src, dst, skip_before_idx=2)
        with open(dst) as fh:
            out_bars = [json.loads(l) for l in fh.readlines()]
        # Output = 1 bar (la 3e)
        assert len(out_bars) == 1
        assert out_bars[0]["volume"] == 100
        assert stats["n_skip"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
