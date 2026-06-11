"""Tests Phase 5.0.A menthorq_v2_sierra_proxy."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_proxy_flip_zone_0_returns_1_stable():
    """bool_gex_flip_zone=0 (stable) -> gamma_condition=1 (long gamma)."""
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    assert compute_gamma_condition_proxy(0) == 1


def test_proxy_flip_zone_1_returns_0_volatile():
    """bool_gex_flip_zone=1 (volatile) -> gamma_condition=0 (short gamma)."""
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    assert compute_gamma_condition_proxy(1) == 0


def test_proxy_none_returns_none():
    """bool_gex_flip_zone absent -> None (fail-closed downstream)."""
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    assert compute_gamma_condition_proxy(None) is None


def test_proxy_invalid_value_returns_none():
    """Valeurs invalides -> None (defense profondeur)."""
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    assert compute_gamma_condition_proxy(2) is None  # hors {0,1}
    assert compute_gamma_condition_proxy(-1) is None
    assert compute_gamma_condition_proxy("invalid") is None
    assert compute_gamma_condition_proxy([1]) is None


def test_proxy_float_compatible():
    """Float 0.0 / 1.0 accepte (Sierra DMP peut emettre float)."""
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    assert compute_gamma_condition_proxy(0.0) == 1
    assert compute_gamma_condition_proxy(1.0) == 0


def test_inject_payload_without_existing():
    """Injection si mq_gamma_condition absent."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    payload = {"bool_gex_flip_zone": 0}
    result = inject_gamma_condition_proxy(payload)
    assert result["mq_gamma_condition"] == 1
    assert result["_mq_gamma_source"] == "sierra_proxy_v2"


def test_inject_payload_with_none_existing():
    """Injection si mq_gamma_condition = None."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    payload = {"mq_gamma_condition": None, "bool_gex_flip_zone": 1}
    result = inject_gamma_condition_proxy(payload)
    assert result["mq_gamma_condition"] == 0
    assert result["_mq_gamma_source"] == "sierra_proxy_v2"


def test_inject_payload_with_existing_preserves():
    """Si mq_gamma_condition deja present non-None : NE PAS overwrite."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    payload = {"mq_gamma_condition": 1, "bool_gex_flip_zone": 1}
    result = inject_gamma_condition_proxy(payload)
    # Source originale (Databento) prioritaire, pas overwrite
    assert result["mq_gamma_condition"] == 1
    assert "_mq_gamma_source" not in result


def test_inject_payload_no_flip_zone_no_injection():
    """Si bool_gex_flip_zone absent : pas d'injection (fail-closed downstream)."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    payload = {"close": 100.0}
    result = inject_gamma_condition_proxy(payload)
    assert "mq_gamma_condition" not in result
    assert "_mq_gamma_source" not in result


def test_inject_modifies_in_place():
    """Verifier mutation in-place + return."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    payload = {"bool_gex_flip_zone": 0}
    result = inject_gamma_condition_proxy(payload)
    assert result is payload  # meme objet
    assert payload["mq_gamma_condition"] == 1


def test_proxy_is_inverse_of_legacy_convention():
    """Le proxy doit etre l'inverse strict de la formule legacy.

    Convention enricher_chain.py:278 (P6b feature-engineer dette #6) :
        bool_gex_flip_zone = 1 - mq_gamma_condition

    Le proxy doit etre tel que reappliquer la formule legacy redonne le flip
    initial (idempotence). Sinon collision silencieuse.

    Reserve I-1 audit code-reviewer 11/06.
    """
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    for flip_initial in (0, 1):
        gamma = compute_gamma_condition_proxy(flip_initial)
        flip_recomputed = 1 - int(gamma)
        assert flip_recomputed == flip_initial, (
            f"Convention violation : flip_initial={flip_initial} -> "
            f"gamma={gamma} -> flip_recomputed={flip_recomputed}. "
            "Le proxy n'est PAS l'inverse strict de la formule legacy."
        )


def test_inject_logs_injected_when_proxy_applied():
    """Verifier emit MQ_PROXY_INJECTED quand proxy injecte (regle R2 logging)."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    logs = []

    def fake_log(code, **kwargs):
        logs.append((code, kwargs))

    payload = {"bool_gex_flip_zone": 1}
    inject_gamma_condition_proxy(payload, log_fn=fake_log, sym="NQ")
    assert len(logs) == 1
    assert logs[0][0] == "MQ_PROXY_INJECTED"
    assert logs[0][1]["gamma"] == 0
    assert logs[0][1]["flip"] == 1
    assert logs[0][1]["sym"] == "NQ"


def test_inject_logs_skipped_when_flip_zone_absent():
    """Verifier emit MQ_PROXY_SKIPPED_NO_FLIP_ZONE (regle R2)."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    logs = []
    payload = {"close": 100.0}
    inject_gamma_condition_proxy(payload, log_fn=lambda c, **k: logs.append((c, k)), sym="ES")
    assert len(logs) == 1
    assert logs[0][0] == "MQ_PROXY_SKIPPED_NO_FLIP_ZONE"
    assert logs[0][1]["sym"] == "ES"


def test_inject_logs_preserved_when_original_set():
    """Verifier emit MQ_PROXY_PRESERVED_ORIGINAL (regle R2)."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    logs = []
    payload = {"mq_gamma_condition": 1, "bool_gex_flip_zone": 1}
    inject_gamma_condition_proxy(payload, log_fn=lambda c, **k: logs.append((c, k)), sym="MGC")
    assert len(logs) == 1
    assert logs[0][0] == "MQ_PROXY_PRESERVED_ORIGINAL"


def test_inject_log_fn_none_is_no_op():
    """log_fn=None ne doit JAMAIS crasher (backward compat)."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    payload = {"bool_gex_flip_zone": 0}
    result = inject_gamma_condition_proxy(payload, log_fn=None, sym="NQ")
    assert result["mq_gamma_condition"] == 1


def test_inject_log_fn_exception_does_not_crash():
    """Si log_fn raise, l'injection reste fonctionnelle (defense in depth)."""
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy

    def bad_log(code, **kwargs):
        raise RuntimeError("simulated log failure")

    payload = {"bool_gex_flip_zone": 1}
    result = inject_gamma_condition_proxy(payload, log_fn=bad_log, sym="NQ")
    assert result["mq_gamma_condition"] == 0


def test_proxy_float_non_binary_returns_none():
    """Defense A.3 : float non-binaire (0.5, 1.5) -> None."""
    from CORE.menthorq_v2_sierra_proxy import compute_gamma_condition_proxy
    assert compute_gamma_condition_proxy(0.5) is None
    assert compute_gamma_condition_proxy(0.99) is None
    assert compute_gamma_condition_proxy(1.5) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
