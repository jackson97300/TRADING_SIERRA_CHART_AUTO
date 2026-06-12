"""Tests Phase 1.5 LIVE jitter fix - normalize_payload_ts + round_ts_to_minute.

Cf CORE/sierra_ts.py docstring pour contrat donnees.
Cf DOCS/INCIDENT_LOG.md #48 pour bug detecte par Jackson 12/06 03:00.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# round_ts_to_minute
# ════════════════════════════════════════════════════════════════════════════

def test_round_floor_minute():
    """08:03:59 -> 08:04:00 (round UP a la minute suivante).

    Empirique : 31% des bars Sierra NQ live ferment a :59 (jitter natif).
    """
    from CORE.sierra_ts import round_ts_to_minute
    # 2026-06-12T08:03:59 UTC = 1781243039000 ms
    ts_59 = 1781243039000
    # 2026-06-12T08:04:00 UTC = 1781243040000 ms
    expected = 1781243040000
    assert round_ts_to_minute(ts_59) == expected


def test_round_no_change():
    """08:05:00 -> 08:05:00 (deja sur la minute, no-op)."""
    from CORE.sierra_ts import round_ts_to_minute
    ts_00 = 1781243100000  # 08:05:00 UTC
    assert round_ts_to_minute(ts_00) == ts_00


def test_round_half_even():
    """30s edge case : banker's rounding (Python round half-to-even).

    08:04:30 (1781243070000) -> round(.5) = 0 (even) -> 08:04:00
    08:05:30 (1781243130000) -> round(.5) = 1 (odd) -> 08:06:00

    Edge case quasi-jamais observe en LIVE Sierra (distribution
    binomiale {:00, :59}). Documenter le comportement.
    """
    from CORE.sierra_ts import round_ts_to_minute
    # 08:04:30 -> 08:04:00 (banker even)
    assert round_ts_to_minute(1781243070000) == 1781243040000
    # 08:05:30 -> 08:06:00 (banker odd)
    assert round_ts_to_minute(1781243130000) == 1781243160000


# ════════════════════════════════════════════════════════════════════════════
# normalize_payload_ts
# ════════════════════════════════════════════════════════════════════════════

def test_normalize_3_fields_coherent():
    """Apres normalize, ts/ts_event/ts_event_ns sont coherents (3 representations meme instant)."""
    from datetime import datetime, timezone
    from CORE.sierra_ts import normalize_payload_ts
    payload = {"ts": 1781243039000, "sym": "NQ", "close": 29500.0}
    out = normalize_payload_ts(payload)
    # ts ms ROUND a la minute (multiple de 60000)
    assert out["ts"] == 1781243040000
    assert out["ts"] % 60_000 == 0
    # ts_event ISO depuis ts arrondi : verifie coherence sans hardcoder l'heure
    expected_iso = datetime.fromtimestamp(out["ts"] / 1000.0, tz=timezone.utc).isoformat()
    assert out["ts_event"] == expected_iso
    # ts_event_ns coherent (ms * 1e6)
    assert out["ts_event_ns"] == out["ts"] * 1_000_000


def test_normalize_preserves_ts_raw_ms():
    """ts_raw_ms NEW field = brut Sierra preserve pour debugging."""
    from CORE.sierra_ts import normalize_payload_ts
    raw = 1781243039000  # 08:03:59 UTC (jitter)
    payload = {"ts": raw, "close": 29500.0}
    out = normalize_payload_ts(payload)
    assert out["ts_raw_ms"] == raw
    assert out["ts"] != raw  # change a 08:04:00


def test_normalize_idempotent():
    """normalize(normalize(p)) == normalize(p) (preserve ts_raw_ms ORIGINAL brut)."""
    from CORE.sierra_ts import normalize_payload_ts
    raw = 1781243039000  # 08:03:59 (jitter)
    payload = {"ts": raw, "close": 29500.0}
    once = normalize_payload_ts(payload.copy())
    twice = normalize_payload_ts(once.copy())
    # ts_raw_ms reste = brut original (PAS la version arrondie de la 1ere passe)
    assert twice["ts_raw_ms"] == raw
    # ts toujours arrondi
    assert twice["ts"] == once["ts"]
    assert twice["ts_event"] == once["ts_event"]
    assert twice["ts_event_ns"] == once["ts_event_ns"]


def test_normalize_cross_instrument():
    """ES + NQ avec jitter different -> meme ts canonique apres normalize."""
    from CORE.sierra_ts import normalize_payload_ts
    es_bar = {"ts": 1781243039000, "sym": "ES", "close": 6705.0}  # 08:03:59
    nq_bar = {"ts": 1781243040000, "sym": "NQ", "close": 29500.0}  # 08:04:00
    es_out = normalize_payload_ts(es_bar)
    nq_out = normalize_payload_ts(nq_bar)
    # Apres ROUND : meme ts canonique = joins cross-instrument OK
    assert es_out["ts"] == nq_out["ts"]
    assert es_out["ts_event"] == nq_out["ts_event"]
    assert es_out["ts_event_ns"] == nq_out["ts_event_ns"]
    # Mais raw preserve = origines distinguables
    assert es_out["ts_raw_ms"] != nq_out["ts_raw_ms"]


def test_normalize_noop_missing_ts():
    """Si ts absent : NO-OP (gracieux)."""
    from CORE.sierra_ts import normalize_payload_ts
    payload = {"sym": "NQ", "close": 29500.0}
    out = normalize_payload_ts(payload)
    assert "ts" not in out
    assert "ts_raw_ms" not in out
    assert "ts_event_ns" not in out


def test_normalize_noop_ts_not_numeric():
    """Si ts existe mais non-numerique (string ISO leftover) : NO-OP."""
    from CORE.sierra_ts import normalize_payload_ts
    payload = {"ts": "2026-06-12T08:03:59Z", "sym": "NQ"}
    out = normalize_payload_ts(payload)
    # NO-OP : ts string preserve, pas de ts_raw_ms ni ts_event_ns ajoute
    assert out["ts"] == "2026-06-12T08:03:59Z"
    assert "ts_raw_ms" not in out


def test_normalize_modifies_in_place():
    """normalize mute le dict d'entree ET return meme reference."""
    from CORE.sierra_ts import normalize_payload_ts
    payload = {"ts": 1781243039000}
    out = normalize_payload_ts(payload)
    assert out is payload  # meme reference (mutable)
    assert payload["ts"] == 1781243040000  # mute


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
