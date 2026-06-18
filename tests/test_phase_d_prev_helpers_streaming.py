"""Tests phase_d_prev_helpers_streaming (INCIDENT #76).

Couvre :
- L1 unit : warmup, cross-day transition, signe convention DMP,
           non-atomic snapshot, bar_high/bar_low sources pdh/pdl
- L2 integration : multi-session sequentielle
- L3 regression : Q1 atomicite Plan agent, Q2 source bar_high (NOT cash_high)
- L4 feature flags : MIA_PREV_VA_WIRE_ENABLED + MIA_PREV_DAY_HL_WIRE_ENABLED
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Path resolution (CORE/ or workspace root)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "CORE") not in sys.path:
    sys.path.insert(0, str(_ROOT / "CORE"))

from phase_d_prev_helpers_streaming import (  # noqa: E402
    PrevHelpersState,
    add_phase_d_prev_helpers_streaming,
    make_prev_helpers_state,
)


# ════════════════════════════════════════════════════════════════════════════
# L1 - Unit tests
# ════════════════════════════════════════════════════════════════════════════

def _bar(sess="2026-06-12", close=7400.0, **kwargs) -> dict:
    """Helper bar factory."""
    base = {
        "session_date_trading": sess,
        "close": close,
        "cur_vah": close + 5,
        "cur_val": close - 5,
        "cur_vpoc": close,
        "bar_high": close + 2,
        "bar_low": close - 2,
    }
    base.update(kwargs)
    return base


def test_warmup_first_session_returns_nan():
    """Au 1er bar, pas de prev session vue -> tous helpers + dist = NaN."""
    state = make_prev_helpers_state()
    out = add_phase_d_prev_helpers_streaming(_bar(), state)
    for k in ("prev_vah", "prev_val", "prev_vpoc", "pdh", "pdl",
              "dist_prev_vah_pct", "dist_prev_val_pct",
              "dist_prev_vpoc_pct", "dist_pdh_pct", "dist_pdl_pct"):
        assert k in out, f"Missing key {k}"
        v = out[k]
        assert v != v, f"{k} should be NaN at warmup, got {v}"


def test_emit_after_first_session_transition():
    """Apres transition session 1 -> 2, prev_* = EOD session 1."""
    state = make_prev_helpers_state()

    # Session 1 : 5 bars, tracker EOD evolue
    for i in range(5):
        b = _bar(sess="2026-06-12", close=7400.0 + i,
                 cur_vah=7405.0 + i, cur_val=7395.0 + i, cur_vpoc=7400.0 + i,
                 bar_high=7402.0 + i, bar_low=7398.0 + i)
        out = add_phase_d_prev_helpers_streaming(b, state)
        # Pas encore de prev session
        assert out["prev_vah"] != out["prev_vah"]  # NaN

    # EOD session 1 :
    # cur_vah/val/vpoc derniere = 7409/7399/7404 (i=4)
    # max(bar_high) = 7406 (i=4), min(bar_low) = 7398 (i=0)
    assert state.current_eod_vah == 7409.0
    assert state.current_eod_session_high == 7406.0
    assert state.current_eod_session_low == 7398.0

    # Session 2 : 1 bar, transition declenchee, prev_* = EOD session 1
    b2 = _bar(sess="2026-06-14", close=7420.0)
    out2 = add_phase_d_prev_helpers_streaming(b2, state)
    assert out2["prev_vah"] == 7409.0
    assert out2["prev_val"] == 7399.0
    assert out2["prev_vpoc"] == 7404.0
    assert out2["pdh"] == 7406.0   # max(bar_high) session 1
    assert out2["pdl"] == 7398.0   # min(bar_low) session 1


def test_constant_intra_session():
    """Sur N bars meme session, prev_* = CONSTANT (= EOD session J-1)."""
    state = make_prev_helpers_state()
    # Session 1 warmup
    for i in range(3):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-12", close=7400.0 + i,
                 cur_vah=7405.0, cur_val=7395.0, cur_vpoc=7400.0,
                 bar_high=7405.0, bar_low=7398.0),
            state,
        )
    # Session 2 : 20 bars, verifier que prev_* ne change pas
    prev_vah_seen = set()
    pdh_seen = set()
    for i in range(20):
        out = add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-14", close=7420.0 + i * 0.5),
            state,
        )
        prev_vah_seen.add(out["prev_vah"])
        pdh_seen.add(out["pdh"])
    assert len(prev_vah_seen) == 1, f"prev_vah varies: {prev_vah_seen}"
    assert len(pdh_seen) == 1, f"pdh varies: {pdh_seen}"


def test_dist_pct_sign_convention_dmp():
    """REGRESSION INCIDENT #75 : signe positif si level > close.

    Convention DMP (DMP_F3_DistNormalisees.h:101) :
        dist = (level - close) / close * 100
        POSITIF si level au-dessus close
    """
    state = make_prev_helpers_state()
    # Setup prev session avec valeurs connues
    add_phase_d_prev_helpers_streaming(
        _bar(sess="2026-06-12", close=7400.0,
             cur_vah=7450.0, cur_val=7350.0, cur_vpoc=7400.0,
             bar_high=7500.0, bar_low=7300.0),
        state,
    )
    # Transition : prev_session_* = ces valeurs
    out = add_phase_d_prev_helpers_streaming(
        _bar(sess="2026-06-14", close=7400.0,
             cur_vah=7400.0, cur_val=7400.0, cur_vpoc=7400.0,
             bar_high=7400.0, bar_low=7400.0),
        state,
    )

    # close=7400, prev_vah=7450 (au-dessus) -> POSITIF
    assert out["dist_prev_vah_pct"] > 0, \
        f"prev_vah=7450 > close=7400 -> dist devrait etre POSITIF, got {out['dist_prev_vah_pct']}"
    # close=7400, prev_val=7350 (en-dessous) -> NEGATIF
    assert out["dist_prev_val_pct"] < 0, \
        f"prev_val=7350 < close=7400 -> dist devrait etre NEGATIF, got {out['dist_prev_val_pct']}"
    # close=7400, pdh=7500 (au-dessus) -> POSITIF
    assert out["dist_pdh_pct"] > 0
    # close=7400, pdl=7300 (en-dessous) -> NEGATIF
    assert out["dist_pdl_pct"] < 0

    # Valeur exacte : (7450 - 7400) / 7400 * 100 = 0.6757
    assert abs(out["dist_prev_vah_pct"] - 0.6757) < 0.001


def test_pdh_source_is_bar_high_not_cash_high():
    """Q2 Plan agent : pdh = max(bar_high) 24h, PAS cash_high (RTH).

    Source confirmee empirique 15/06 ES : pdh=7560 = max(bar_high) 24h,
    cash_high RTH = 7498 (different).
    """
    state = make_prev_helpers_state()
    # Session 1 : cash_high (RTH) BAS, mais bar_high (overnight) HAUT
    for _ in range(3):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-12", close=7400.0,
                 cur_vah=7405.0, cur_val=7395.0, cur_vpoc=7400.0,
                 bar_high=7500.0,   # bar_high overnight
                 bar_low=7300.0,
                 cash_high=7450.0,  # RTH only (= different)
                 cash_low=7350.0),
            state,
        )
    # Transition
    out = add_phase_d_prev_helpers_streaming(
        _bar(sess="2026-06-14", close=7400.0), state)
    # pdh DOIT etre 7500 (bar_high), PAS 7450 (cash_high)
    assert out["pdh"] == 7500.0, f"pdh should be bar_high=7500, got {out['pdh']}"
    assert out["pdl"] == 7300.0


def test_non_atomic_snapshot_preserves_partial():
    """Q1 Plan agent : snapshot non-atomique. Si une source manque PENDANT
    TOUTE la session courante, prev_X garde l'ancienne valeur au lieu
    d'ecraser avec None.
    """
    state = make_prev_helpers_state()
    # Setup prev session 10 : tracker EOD = (7050, 6950, 7000, 7100, 6900)
    for _ in range(2):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-10", close=7000.0,
                 cur_vah=7050.0, cur_val=6950.0, cur_vpoc=7000.0,
                 bar_high=7100.0, bar_low=6900.0),
            state,
        )
    # Premier bar session 12 (= bar de transition).
    # IMPORTANT : cur_vah=None DES le 1er bar pour ne pas re-injecter
    # current_eod_vah a 7050+ via update post-transition.
    add_phase_d_prev_helpers_streaming(
        _bar(sess="2026-06-12", close=7100.0,
             cur_vah=None, cur_val=7090.0, cur_vpoc=7100.0,
             bar_high=7200.0, bar_low=7000.0),
        state,
    )
    # Apres transition 10 -> 12 : snapshot complet (toutes sources valid)
    assert state.prev_session_vah == 7050.0
    assert state.prev_session_pdh == 7100.0  # max bar_high session 10

    # Reste session 12 : toujours cur_vah=None (= absent)
    for _ in range(3):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-12", close=7110.0,
                 cur_vah=None, cur_val=7095.0, cur_vpoc=7105.0,
                 bar_high=7210.0, bar_low=7010.0),
            state,
        )
    # current_eod_vah doit etre None (jamais set en session 12)
    assert state.current_eod_vah is None

    # Transition vers 14 : current_eod_vah=None -> ne snapshot pas
    add_phase_d_prev_helpers_streaming(
        _bar(sess="2026-06-14", close=7300.0,
             cur_vah=None, cur_val=None, cur_vpoc=None,
             bar_high=None, bar_low=None),
        state,
    )
    # prev_session_vah GARDE 7050 (du snapshot 10->12)
    assert state.prev_session_vah == 7050.0, \
        f"prev_session_vah doit garder 7050, got {state.prev_session_vah}"
    # MAIS prev_val/vpoc/pdh/pdl mis a jour (sources valides session 12)
    assert state.prev_session_val == 7095.0
    assert state.prev_session_vpoc == 7105.0
    assert state.prev_session_pdh == 7210.0  # max bar_high session 12
    assert state.prev_session_pdl == 7000.0  # min bar_low session 12 (1er bar)


# ════════════════════════════════════════════════════════════════════════════
# L4 - Feature flags
# ════════════════════════════════════════════════════════════════════════════

def test_flag_va_disabled_blocks_prev_va(monkeypatch):
    """MIA_PREV_VA_WIRE_ENABLED=0 : prev_vah/val/vpoc + dist absents."""
    monkeypatch.setenv("MIA_PREV_VA_WIRE_ENABLED", "0")
    state = make_prev_helpers_state()
    # Setup prev session
    for _ in range(2):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-10", close=7000.0), state)
    add_phase_d_prev_helpers_streaming(_bar(sess="2026-06-12"), state)

    out = add_phase_d_prev_helpers_streaming(_bar(sess="2026-06-12"), state)
    # VA helpers absents
    assert "prev_vah" not in out
    assert "prev_val" not in out
    assert "prev_vpoc" not in out
    assert "dist_prev_vah_pct" not in out
    # H/L helpers presents (default flag=1)
    assert "pdh" in out
    assert "pdl" in out


def test_flag_hl_disabled_blocks_pdh_pdl(monkeypatch):
    """MIA_PREV_DAY_HL_WIRE_ENABLED=0 : pdh/pdl + dist absents."""
    monkeypatch.setenv("MIA_PREV_DAY_HL_WIRE_ENABLED", "0")
    state = make_prev_helpers_state()
    for _ in range(2):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-10", close=7000.0), state)
    add_phase_d_prev_helpers_streaming(_bar(sess="2026-06-12"), state)

    out = add_phase_d_prev_helpers_streaming(_bar(sess="2026-06-12"), state)
    # H/L helpers absents
    assert "pdh" not in out
    assert "pdl" not in out
    assert "dist_pdh_pct" not in out
    # VA helpers presents
    assert "prev_vah" in out


def test_both_flags_disabled_no_output(monkeypatch):
    """Les 2 flags off : aucune feature emise."""
    monkeypatch.setenv("MIA_PREV_VA_WIRE_ENABLED", "0")
    monkeypatch.setenv("MIA_PREV_DAY_HL_WIRE_ENABLED", "0")
    state = make_prev_helpers_state()
    out = add_phase_d_prev_helpers_streaming(_bar(), state)
    for k in ("prev_vah", "prev_val", "prev_vpoc", "pdh", "pdl",
              "dist_prev_vah_pct", "dist_pdh_pct"):
        assert k not in out


# ════════════════════════════════════════════════════════════════════════════
# L1bis - Edge cases
# ════════════════════════════════════════════════════════════════════════════

def test_no_session_date_returns_nan():
    """Si session_date_trading absent + date_et absent, NaN partout."""
    state = make_prev_helpers_state()
    bar = {"close": 7400.0, "cur_vah": 7405.0}
    out = add_phase_d_prev_helpers_streaming(bar, state)
    for k in ("prev_vah", "prev_val", "prev_vpoc", "pdh", "pdl"):
        assert k in out
        assert out[k] != out[k]  # NaN


def test_close_zero_returns_nan_distances():
    """Close <= 0 : distances NaN (anti div/0)."""
    state = make_prev_helpers_state()
    for _ in range(2):
        add_phase_d_prev_helpers_streaming(
            _bar(sess="2026-06-10", close=7000.0), state)
    add_phase_d_prev_helpers_streaming(_bar(sess="2026-06-12"), state)

    # Bar avec close=0 -> distances NaN mais helpers absolus OK
    out = add_phase_d_prev_helpers_streaming(
        _bar(sess="2026-06-12", close=0.0), state)
    assert out["dist_prev_vah_pct"] != out["dist_prev_vah_pct"]
    assert out["dist_pdh_pct"] != out["dist_pdh_pct"]


def test_session_date_pd_timestamp_format():
    """Plan agent Q1 normalisation : pd.Timestamp gere correctement."""
    import pandas as pd
    state = make_prev_helpers_state()
    bar = _bar(sess=pd.Timestamp("2026-06-12 09:30:00"))
    out = add_phase_d_prev_helpers_streaming(bar, state)
    # current_session_date normalise ISO date only
    assert state.current_session_date == "2026-06-12"
    # Bar suivant meme session
    bar2 = _bar(sess=pd.Timestamp("2026-06-12 14:00:00"))
    add_phase_d_prev_helpers_streaming(bar2, state)
    # Pas de transition declenchee
    assert state.current_session_date == "2026-06-12"


def test_bar_high_fallback_to_high():
    """Si bar_high absent, fallback sur 'high'."""
    state = make_prev_helpers_state()
    bar = _bar(sess="2026-06-12", close=7400.0,
               bar_high=None, high=7500.0,
               bar_low=None, low=7300.0)
    add_phase_d_prev_helpers_streaming(bar, state)
    assert state.current_eod_session_high == 7500.0
    assert state.current_eod_session_low == 7300.0


# ════════════════════════════════════════════════════════════════════════════
# L3 - Regression patterns
# ════════════════════════════════════════════════════════════════════════════

def test_state_idempotent_on_replay():
    """Rejouer 2x le meme bar = meme output (idempotence)."""
    state1 = make_prev_helpers_state()
    state2 = make_prev_helpers_state()
    bars = [
        _bar(sess="2026-06-10", close=7000.0),
        _bar(sess="2026-06-12", close=7050.0),
        _bar(sess="2026-06-12", close=7055.0),
    ]
    last_out1 = None
    for b in bars:
        last_out1 = add_phase_d_prev_helpers_streaming(b, state1)
    last_out2 = None
    for b in bars:
        last_out2 = add_phase_d_prev_helpers_streaming(b, state2)
    # Outputs identiques
    for k in ("prev_vah", "prev_val", "prev_vpoc", "pdh", "pdl"):
        v1, v2 = last_out1.get(k), last_out2.get(k)
        # NaN == NaN
        if v1 != v1 and v2 != v2:
            continue
        assert v1 == v2, f"Idempotence broken on {k}: {v1} vs {v2}"
