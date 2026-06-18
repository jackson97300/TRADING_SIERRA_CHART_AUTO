"""test_cvd_session_override.py - Tests pour cvd_session_override.

Validation INCIDENT_LOG #59 fix : override cvd_day Python depuis delta_bar
cumule par session ET-based (CME 18:00 boundary).

Date : 2026-06-15
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from CORE.cvd_session_override import (
    CVDSessionOverrideState,
    _cme_session_id_from_ts_ms,
    _sign,
    override_cvd_day_session,
)


# ════════════════════════════════════════════════════════════════════════════
# FAKE STATE
# ════════════════════════════════════════════════════════════════════════════

class FakeState:
    """Mock minimal de LiveEnricherState (juste engine_states + get_engine_state)."""

    def __init__(self):
        self.engine_states = {}

    def get_engine_state(self, name, factory=dict):
        if name not in self.engine_states:
            self.engine_states[name] = factory()
        return self.engine_states[name]


def _ts_ms_et(year, month, day, hour_et, minute=0):
    """Compute ts_ms UTC from ET timestamp (UTC-4 DST juin/octobre)."""
    dt_et = datetime(year, month, day, hour_et, minute)
    dt_utc = dt_et + timedelta(hours=4)  # ET -> UTC en DST
    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return int(dt_utc.timestamp() * 1000)


# ════════════════════════════════════════════════════════════════════════════
# TEST helpers
# ════════════════════════════════════════════════════════════════════════════

def test_sign():
    assert _sign(0) == 0
    assert _sign(1.5) == 1
    assert _sign(-3.2) == -1
    assert _sign(0.0) == 0


def test_session_id_cme_boundary_17h_et_is_same_day():
    """17:00 ET = derniere bar de la session J."""
    ts = _ts_ms_et(2026, 6, 15, 17, 30)  # 17:30 ET
    sid = _cme_session_id_from_ts_ms(ts)
    assert sid == "2026-06-15"


def test_session_id_cme_boundary_18h_et_is_next_day():
    """18:00 ET = debut nouvelle session J+1."""
    ts = _ts_ms_et(2026, 6, 15, 18, 30)  # 18:30 ET
    sid = _cme_session_id_from_ts_ms(ts)
    assert sid == "2026-06-16"


def test_session_id_morning_rth():
    """09:30 ET RTH open = session J."""
    ts = _ts_ms_et(2026, 6, 16, 9, 30)
    sid = _cme_session_id_from_ts_ms(ts)
    assert sid == "2026-06-16"


def test_session_id_asia_overnight():
    """02:00 ET (Asia session) = session J (toujours apres 18:00 ET J-1)."""
    ts = _ts_ms_et(2026, 6, 16, 2, 0)
    sid = _cme_session_id_from_ts_ms(ts)
    assert sid == "2026-06-16"


def test_session_id_winter_dst_boundary():
    """Fix R1 code-reviewer : verifier DST winter (EST UTC-5) boundary correct.

    En decembre, ET = UTC-5 (pas UTC-4 comme en juin). Le code AVANT R1
    hardcodait UTC-4, donc 17:00 ET (= 22:00 UTC EST) etait interprete
    comme 18:00 ET = nouvelle session a tort.

    APRES R1 (zoneinfo America/New_York) : DST gere automatiquement.
    17:00 ET reste session J, 18:00 ET passe a session J+1.
    """
    # 15 dec 2026 17:30 ET EST (UTC-5) = 22:30 UTC
    dt_et_17h30 = datetime(2026, 12, 15, 17, 30)
    dt_utc_22h30 = dt_et_17h30 + timedelta(hours=5)  # EST
    dt_utc_22h30 = dt_utc_22h30.replace(tzinfo=timezone.utc)
    ts = int(dt_utc_22h30.timestamp() * 1000)
    sid = _cme_session_id_from_ts_ms(ts)
    assert sid == "2026-12-15", f"DST winter 17:30 ET doit etre session J : {sid}"

    # 15 dec 2026 18:30 ET EST (UTC-5) = 23:30 UTC
    dt_et_18h30 = datetime(2026, 12, 15, 18, 30)
    dt_utc_23h30 = dt_et_18h30 + timedelta(hours=5)
    dt_utc_23h30 = dt_utc_23h30.replace(tzinfo=timezone.utc)
    ts2 = int(dt_utc_23h30.timestamp() * 1000)
    sid2 = _cme_session_id_from_ts_ms(ts2)
    assert sid2 == "2026-12-16", f"DST winter 18:30 ET doit etre session J+1 : {sid2}"


# ════════════════════════════════════════════════════════════════════════════
# TEST override
# ════════════════════════════════════════════════════════════════════════════

def test_override_first_bar_creates_state():
    state = FakeState()
    ts = _ts_ms_et(2026, 6, 15, 19, 0)  # 19:00 ET = session 16/06
    payload = {"ts": ts, "delta_bar": 100, "cvd_day": 99999, "cvd_day_dir": 1,
               "delta_day": 88888, "delta_day_dir": -1}

    out = override_cvd_day_session(payload, state, "NQ")

    assert out["cvd_day"] == 100.0
    assert out["cvd_day_dir"] == 1
    # Fix #73 (18/06) : delta_day + delta_day_dir aussi override
    assert out["delta_day"] == 100.0
    assert out["delta_day_dir"] == 1
    # State stocke
    s = state.engine_states["cvd_session_override_NQ"]
    assert s.session_id == "2026-06-16"
    assert s.cvd_cumul == 100.0
    assert s.n_bars_session == 1


def test_override_delta_day_equals_cvd_day_fix_73():
    """Fix #73 : apres override, delta_day == cvd_day TOUJOURS (meme metrique source)."""
    state = FakeState()
    ts1 = _ts_ms_et(2026, 6, 15, 19, 0)
    ts2 = _ts_ms_et(2026, 6, 15, 19, 1)

    override_cvd_day_session({"ts": ts1, "delta_bar": 50}, state, "NQ")
    p = override_cvd_day_session({"ts": ts2, "delta_bar": -120}, state, "NQ")

    # Equivalence parfaite (vrai fix Jackson mentor mode 18/06)
    assert p["cvd_day"] == -70.0
    assert p["delta_day"] == p["cvd_day"]
    assert p["cvd_day_dir"] == p["delta_day_dir"]
    assert p["cvd_day_dir"] == -1


def test_override_cumul_same_session():
    state = FakeState()
    ts1 = _ts_ms_et(2026, 6, 15, 19, 0)  # session 16/06
    ts2 = _ts_ms_et(2026, 6, 15, 19, 1)
    ts3 = _ts_ms_et(2026, 6, 16, 10, 0)  # encore session 16/06

    override_cvd_day_session({"ts": ts1, "delta_bar": 100}, state, "NQ")
    override_cvd_day_session({"ts": ts2, "delta_bar": -250}, state, "NQ")
    p = override_cvd_day_session({"ts": ts3, "delta_bar": 50}, state, "NQ")

    assert p["cvd_day"] == -100.0  # 100 - 250 + 50
    assert p["cvd_day_dir"] == -1
    assert state.engine_states["cvd_session_override_NQ"].n_bars_session == 3


def test_override_reset_new_session_18h_et():
    """Cross-session ET 17:55 -> 18:05 doit reset cumul."""
    state = FakeState()

    # Session J : 17:55 ET cumul +500
    ts_j = _ts_ms_et(2026, 6, 15, 17, 55)
    override_cvd_day_session({"ts": ts_j, "delta_bar": 500}, state, "NQ")
    assert state.engine_states["cvd_session_override_NQ"].cvd_cumul == 500.0
    assert state.engine_states["cvd_session_override_NQ"].session_id == "2026-06-15"

    # Session J+1 : 18:05 ET nouveau cumul depuis 0
    ts_j1 = _ts_ms_et(2026, 6, 15, 18, 5)  # 18:05 ET = session 16/06
    p = override_cvd_day_session({"ts": ts_j1, "delta_bar": -30}, state, "NQ")
    assert p["cvd_day"] == -30.0  # Reset puis -30
    assert p["cvd_day_dir"] == -1
    s = state.engine_states["cvd_session_override_NQ"]
    assert s.session_id == "2026-06-16"
    assert s.cvd_cumul == -30.0
    assert s.n_bars_session == 1  # Reset counter aussi


def test_override_symbol_isolation_nq_es():
    """NQ et ES = states independants."""
    state = FakeState()
    ts = _ts_ms_et(2026, 6, 16, 10, 0)

    override_cvd_day_session({"ts": ts, "delta_bar": 100}, state, "NQ")
    override_cvd_day_session({"ts": ts, "delta_bar": -200}, state, "ES")

    assert state.engine_states["cvd_session_override_NQ"].cvd_cumul == 100.0
    assert state.engine_states["cvd_session_override_ES"].cvd_cumul == -200.0


def test_override_missing_delta_bar_skips_silently():
    state = FakeState()
    ts = _ts_ms_et(2026, 6, 16, 10, 0)
    payload = {"ts": ts, "cvd_day": 999}

    out = override_cvd_day_session(payload, state, "NQ")
    # Pas de override : cvd_day reste comme avant
    assert out["cvd_day"] == 999
    # State pas cree
    assert "cvd_session_override_NQ" not in state.engine_states


def test_override_missing_ts_skips():
    state = FakeState()
    payload = {"delta_bar": 100, "cvd_day": 999}
    out = override_cvd_day_session(payload, state, "NQ")
    assert out["cvd_day"] == 999


def test_override_invalid_delta_bar_skips():
    state = FakeState()
    ts = _ts_ms_et(2026, 6, 16, 10, 0)
    payload = {"ts": ts, "delta_bar": "not_a_number", "cvd_day": 999}
    out = override_cvd_day_session(payload, state, "NQ")
    assert out["cvd_day"] == 999


def test_override_idempotent_same_input():
    """Le helper accumule, donc 2 calls != idempotent au sens strict.

    Verification : meme bar appelee 2 fois consecutivement double cumul.
    """
    state = FakeState()
    ts = _ts_ms_et(2026, 6, 16, 10, 0)

    override_cvd_day_session({"ts": ts, "delta_bar": 100}, state, "NQ")
    p2 = override_cvd_day_session({"ts": ts, "delta_bar": 100}, state, "NQ")

    # 2 calls = 200 (par design : la fonction n'a pas de dedup, le pipeline
    # appelle 1 fois par bar livree)
    assert p2["cvd_day"] == 200.0


def test_override_distribution_realiste():
    """Simulation 1000 bars random : distribution +1/-1/0 doit etre coherente."""
    import random
    random.seed(42)
    state = FakeState()
    base_ts = _ts_ms_et(2026, 6, 16, 9, 30)

    signs = {1: 0, 0: 0, -1: 0}
    for i in range(1000):
        ts = base_ts + i * 60_000  # +1 min par bar
        delta = random.gauss(0, 50)  # delta moyen 0, std 50
        p = override_cvd_day_session({"ts": ts, "delta_bar": delta}, state, "NQ")
        signs[p["cvd_day_dir"]] += 1

    # Sur random walk centre 0, on s'attend a +/- equilibre, pas tout +1
    total = sum(signs.values())
    assert signs[1] / total < 0.99, f"Trop de +1 : {signs}"
    assert signs[-1] / total > 0.01, f"Pas assez de -1 : {signs}"
    # Pas TOUS positifs (= bug reproduit)
    assert signs[1] != total, "Bug reproduit : 100% +1"


# ════════════════════════════════════════════════════════════════════════════
# REGRESSION 18/06 : clobber cvd_day par phase_b + reset cross-session
# (INCIDENT_LOG #66 — add_cvd_momentum_streaming ecrasait cvd_day et ne resettait
#  jamais quand session_date_trading absent du payload en live Sierra)
# ════════════════════════════════════════════════════════════════════════════

def _ts_et(y, mo, d, h, mi):
    try:
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
    except ImportError:  # pragma: no cover
        ny = None
    dt = datetime(y, mo, d, h, mi, tzinfo=ny) if ny else datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def test_cvd_momentum_resets_via_ts_when_session_date_absent():
    """Fix #66 : sans session_date_trading, reset doit fire a 18:00 ET via ts."""
    from CORE.phase_b_rolling_inputs_streaming import (
        add_cvd_momentum_streaming, CVDMomentumState,
    )
    st = CVDMomentumState()
    seq = [
        (_ts_et(2026, 6, 17, 16, 58), 100, 100),
        (_ts_et(2026, 6, 17, 16, 59), 50, 150),
        (_ts_et(2026, 6, 17, 18, 0), -30, -30),   # reset CME 18:00 ET
        (_ts_et(2026, 6, 17, 18, 1), -20, -50),
    ]
    for ts, delta, expected in seq:
        out = add_cvd_momentum_streaming({"delta_bar": delta, "ts": ts}, st)
        assert out["cvd_day"] == expected, f"ts={ts} cvd_day={out['cvd_day']} != {expected}"


def test_cvd_momentum_uses_session_date_when_present():
    """Parite : si session_date_trading present, on l'utilise (pas le fallback ts)."""
    from CORE.phase_b_rolling_inputs_streaming import (
        add_cvd_momentum_streaming, CVDMomentumState,
    )
    st = CVDMomentumState()
    o1 = add_cvd_momentum_streaming({"delta_bar": 100, "session_date_trading": "D1"}, st)
    o2 = add_cvd_momentum_streaming({"delta_bar": 50, "session_date_trading": "D1"}, st)
    o3 = add_cvd_momentum_streaming({"delta_bar": -30, "session_date_trading": "D2"}, st)
    assert (o1["cvd_day"], o2["cvd_day"], o3["cvd_day"]) == (100, 150, -30)
