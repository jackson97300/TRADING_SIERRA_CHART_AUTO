"""Test Phase 3c-C : verifier 7 features rolling streaming.

Utilise un MOCK LiveEnricherState + simulation multi-bars pour valider :
1. atr_regime_zscore_60d : None pendant warm-up (<13800 bars), valeur valide apres
2. dist_naked_poc_nearest_pct : detection naked POC J-1 puis retire si touche
3. is_roll_day / days_since_roll / roll_phase : detection instrument_id change
4. cvd_5d_rolling_ffd : warm-up (~20-30 bars de width), valeur post-warmup
5. cur_va_n_buckets / cur_va_total_vol : lit volume_profile state si present

Strategie : injecter directement engine_states pour bypasser la chain complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.enricher_chain import _apply_phase_3c_C


class MockState:
    """Mock LiveEnricherState minimum pour test."""

    def __init__(self):
        self.engine_states = {}

    def get_engine_state(self, engine_name, factory=dict):
        if engine_name not in self.engine_states:
            self.engine_states[engine_name] = factory()
        return self.engine_states[engine_name]


class MockVolumeProfileState:
    """Mock VolumeProfileState avec price_volume cumulatif."""

    def __init__(self):
        # Simule 5 prix buckets avec volumes (session courante)
        self.price_volume = {
            29168.25: 120.0,
            29168.50: 95.0,
            29168.75: 150.0,
            29169.00: 80.0,
            29169.25: 60.0,
        }


SNAPSHOT_BASE = {
    "symbol": "NQ.c.0",
    "instrument_id": 42004058,
    "ts_event_iso": "2026-05-15T20:46:00+00:00",
    "open": 29170.75, "high": 29172.0, "low": 29168.25, "close": 29168.25,
    "volume": 89, "delta_bar": 28.0,
    "atr": 24.928571,
    "cvd_day": 1538.0,
    "session_date_trading": "2026-05-15",
    "prev_vpoc": 29200.5,
}


def _log_fn(code, **kwargs):
    print(f"  [LOG] {code}: {kwargs}")


def test_phase_c_single_bar():
    print("=" * 70)
    print("  TEST 1 : SINGLE BAR — warm-up attendu (None majoritaire)")
    print("=" * 70)
    state = MockState()
    state.engine_states["volume_profile"] = MockVolumeProfileState()
    payload = dict(SNAPSHOT_BASE)

    _apply_phase_3c_C(payload, state, "NQ.c.0", _log_fn)

    expected = {
        "atr_regime_zscore_60d", "dist_naked_poc_nearest_pct",
        "is_roll_day", "days_since_roll", "roll_phase",
        "cvd_5d_rolling_ffd",
        "cur_va_n_buckets", "cur_va_total_vol",
    }
    print(f"\n=== VALEURS bar 1 ===")
    for k in sorted(expected):
        print(f"  {k:32s} = {payload.get(k)}")

    assert payload["atr_regime_zscore_60d"] is None, "warm-up ATR z attendu"
    assert payload["is_roll_day"] == 0, "pas de roll au bar 1"
    assert payload["days_since_roll"] is None, "jamais vu de roll = None"
    assert payload["roll_phase"] is None, "jamais vu de roll = None"
    assert payload["cvd_5d_rolling_ffd"] is None, "warm-up FFD attendu (<width)"
    assert payload["cur_va_n_buckets"] == 5, "5 buckets dans mock VP state"
    assert payload["cur_va_total_vol"] == 505.0, "120+95+150+80+60 = 505"
    print("[OK] Test 1 PASS")
    return state, payload


def test_phase_c_naked_poc_session_bascule(state):
    """Test bascule session : push prev_vpoc en history, build active_pocs."""
    print("\n" + "=" * 70)
    print("  TEST 2 : NAKED POC bascule session J -> J+1")
    print("=" * 70)
    # Bar 2 : meme session, recalcul -> tracker doit accumuler last_seen_prev_vpoc
    p2 = dict(SNAPSHOT_BASE)
    p2["close"] = 29170.0
    _apply_phase_3c_C(p2, state, "NQ.c.0", _log_fn)
    print(f"  Bar 2 same sess : dist_naked_poc={p2.get('dist_naked_poc_nearest_pct')}")
    # Bar 3 : nouvelle session, prev_vpoc=29200 doit etre push en history,
    #         active_pocs doit contenir 1 element a age 1
    p3 = dict(SNAPSHOT_BASE)
    p3["session_date_trading"] = "2026-05-16"
    p3["prev_vpoc"] = 29250.0   # nouveau prev_vpoc J-1
    p3["close"] = 29180.0
    p3["high"] = 29185.0
    p3["low"] = 29178.0
    _apply_phase_3c_C(p3, state, "NQ.c.0", _log_fn)
    pc_state = state.engine_states["phase_3c_c"]
    history = list(pc_state["sess_pvpoc_history"])
    actives = pc_state["naked_pocs_active"]
    print(f"\n  history apres bascule  : {history}")
    print(f"  active_pocs            : {actives}")
    print(f"  dist_naked_poc_nearest_pct bar 3 : {p3.get('dist_naked_poc_nearest_pct')}")
    assert len(history) == 1, f"history doit contenir 1 entry, a {len(history)}"
    assert history[0] == ("2026-05-15", 29200.5), "premier push history incorrect"
    assert len(actives) == 1, f"1 active POC attendu (J-1)"
    # Bar 4 : meme session J+1, bar englobe le POC 29200.5 -> doit etre retire
    p4 = dict(p3)
    p4["low"] = 29195.0   # encadre 29200.5
    p4["high"] = 29205.0
    _apply_phase_3c_C(p4, state, "NQ.c.0", _log_fn)
    actives_after = pc_state["naked_pocs_active"]
    print(f"\n  active_pocs apres touche : {actives_after}")
    print(f"  dist_naked_poc_nearest_pct bar 4 : {p4.get('dist_naked_poc_nearest_pct')}")
    assert len(actives_after) == 0, "POC doit etre retire apres touche"
    assert p4["dist_naked_poc_nearest_pct"] is None, "plus de POC actif -> None"
    print("[OK] Test 2 PASS")


def test_phase_c_roll_detection(state):
    """Test detection roll par changement instrument_id."""
    print("\n" + "=" * 70)
    print("  TEST 3 : ROLL detection (instrument_id change)")
    print("=" * 70)
    pc_state = state.engine_states["phase_3c_c"]
    print(f"  last_iid avant roll : {pc_state['last_instrument_id']}")
    p5 = dict(SNAPSHOT_BASE)
    p5["session_date_trading"] = "2026-05-17"  # nouvelle session
    p5["instrument_id"] = 42999999             # nouveau contrat
    _apply_phase_3c_C(p5, state, "NQ.c.0", _log_fn)
    print(f"  is_roll_day={p5['is_roll_day']}")
    print(f"  days_since_roll={p5['days_since_roll']}")
    print(f"  roll_phase={p5['roll_phase']}")
    assert p5["is_roll_day"] == 1, "roll doit etre detecte"
    assert p5["days_since_roll"] == 0.0, "0 bars depuis roll = 0 days"
    assert p5["roll_phase"] == 0, "early phase = 0"

    # Avancer 1500 bars sans nouveau roll
    for i in range(1500):
        p_x = dict(p5)
        p_x["ts_event_iso"] = f"2026-05-17T{20 + i//60:02d}:{i%60:02d}:00+00:00"
        _apply_phase_3c_C(p_x, state, "NQ.c.0", _log_fn)
    final = dict(p5)
    final["ts_event_iso"] = "2026-05-18T00:00:00+00:00"
    _apply_phase_3c_C(final, state, "NQ.c.0", _log_fn)
    bsr = pc_state["bars_since_roll"]
    print(f"\n  Apres ~1501 bars : bars_since_roll={bsr}, days={final['days_since_roll']}, phase={final['roll_phase']}")
    assert bsr > 1380, f"compteur bars doit grandir, a {bsr}"
    assert final["days_since_roll"] > 1.0, "1500 bars > 1 trading day"
    print("[OK] Test 3 PASS")


def test_phase_c_ffd_warmup():
    """Test FFD : warmup necessaire (width) puis valeur valide."""
    print("\n" + "=" * 70)
    print("  TEST 4 : CVD 5d FFD warmup + emission")
    print("=" * 70)
    state = MockState()
    p = dict(SNAPSHOT_BASE)
    # Premiere bar pour init state + push 1 cvd dans buffer
    _apply_phase_3c_C(p, state, "NQ.c.0", _log_fn)
    pc_state = state.engine_states["phase_3c_c"]
    width = len(pc_state["ffd_weights"])
    buf_init = len(pc_state["cvd_buffer"])
    print(f"  FFD weights width = {width}, buffer apres bar 1 = {buf_init}")
    # Simuler bars supplementaires avec cvd_day croissant.
    # Threshold emission : len(buf) >= width => need (width - buf_init) ajouts.
    last_val = None
    bars_needed = width - buf_init
    for i in range(bars_needed + 5):
        pp = dict(SNAPSHOT_BASE)
        pp["cvd_day"] = 1000.0 + i * 50.0
        _apply_phase_3c_C(pp, state, "NQ.c.0", _log_fn)
        last_val = pp.get("cvd_5d_rolling_ffd")
        # Buffer size apres cet ajout = buf_init + i + 1
        cur_buf_size = buf_init + i + 1
        if cur_buf_size < width:
            assert last_val is None, (
                f"warm-up: NaN attendu a buf_size={cur_buf_size}<{width}, got {last_val}"
            )
    print(f"  FFD final value apres {bars_needed + 5} bars suppl. = {last_val}")
    assert last_val is not None, "FFD doit emettre apres warmup"
    assert isinstance(last_val, float), "FFD doit etre float"
    print("[OK] Test 4 PASS")


def test_phase_c_atr_z_warmup():
    """Test ATR z-score : warmup MIN_PERIODS bars avant emission."""
    print("\n" + "=" * 70)
    print("  TEST 5 : ATR Z-score warmup (simulation rapide)")
    print("=" * 70)
    from CORE.enricher_chain import _ATR_Z_MIN_PERIODS
    state = MockState()
    # Bypass MIN_PERIODS pour test rapide (sinon 13800 bars = 30s+)
    # On simule en pre-remplissant le buffer
    pc_state = _ApplyPhase3cCStateInjector(state)
    # Re-simuler 1 bar normale apres pre-fill
    p = dict(SNAPSHOT_BASE)
    _apply_phase_3c_C(p, state, "NQ.c.0", _log_fn)
    z = p.get("atr_regime_zscore_60d")
    print(f"  ATR z apres pre-fill : {z}")
    assert z is not None, "post-warmup doit emettre valeur"
    assert isinstance(z, float), "z doit etre float"
    # Avec atr=24.928 constant et buffer constant variance=0 -> None attendu
    # Pour validation valeur, on injecte un buffer hetero
    print("[OK] Test 5 PASS (warmup OK)")


def _ApplyPhase3cCStateInjector(state):
    """Helper : pre-fill ATR buffer avec valeurs heterogenes pour test rapide."""
    from collections import deque
    from CORE.enricher_chain import (
        _ATR_Z_WINDOW_BARS, _ATR_Z_MIN_PERIODS, _compute_ffd_weights,
    )
    buf = deque(maxlen=_ATR_Z_WINDOW_BARS)
    s = 0.0
    sq = 0.0
    for i in range(_ATR_Z_MIN_PERIODS + 100):
        v = 20.0 + (i % 11)   # hetero pour avoir variance > 0
        buf.append(v)
        s += v
        sq += v * v
    state.engine_states["phase_3c_c"] = {
        "atr_buffer": buf,
        "atr_sum": s,
        "atr_sum_sq": sq,
        "sess_pvpoc_history": deque(maxlen=7),
        "naked_pocs_active": [],
        "current_npoc_sess": None,
        "last_seen_prev_vpoc": None,
        "last_instrument_id": None,
        "bars_since_roll": None,
        "current_roll_sess": None,
        "roll_today_flag": 0,
        "cvd_buffer": deque(maxlen=64),
        "ffd_weights": _compute_ffd_weights(),
        "symbol": "NQ",
    }
    return state.engine_states["phase_3c_c"]


def main():
    state, payload = test_phase_c_single_bar()
    test_phase_c_naked_poc_session_bascule(state)
    test_phase_c_roll_detection(state)
    test_phase_c_ffd_warmup()
    test_phase_c_atr_z_warmup()

    print("\n" + "=" * 70)
    print("  VERDICT : 5/5 tests PASS")
    print("=" * 70)


if __name__ == "__main__":
    main()
