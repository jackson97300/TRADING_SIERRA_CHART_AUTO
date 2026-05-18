"""tests/bot3/test_plot_twist_detectors.py - Tests Phase 2 PlotTwistDetectors.

Tests pytest pour `CORE/bot3_plot_twist_detectors.py`.
Coverage cible >= 90%. Tests par detector + integration scan_all + throttle + pickle.

HISTORY
2026-05-18 PM : creation tests Phase 2 J+1 (4 detectors x ~5 tests + integration)
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field

import pytest

from CORE.bot3_plot_twist_detectors import (
    BARS_HISTORY_MAXLEN,
    CAPITULATION_BARS_REQUIRED,
    DIVERGENCE_PRICE_LOOKBACK,
    PlotTwist,
    PlotTwistDetectorsState,
    THROTTLE_TWIST_BARS,
    VOL_Z_ANOMALY_MIN,
    VOL_Z_CAPITULATION_MIN,
    detect_capitulation,
    detect_divergence,
    detect_structure_break,
    detect_volume_anomaly,
    scan_all,
)


# ─── Stubs ────────────────────────────────────────────────────────────────


@dataclass
class StubSwingPoint:
    price: float = 0.0
    bar_idx: int = -1


@dataclass
class StubSwingState:
    last_swing_high: StubSwingPoint = field(default_factory=StubSwingPoint)
    last_swing_low: StubSwingPoint = field(default_factory=StubSwingPoint)


def _make_bar(
    ts: str = "2026-05-18T13:30:00Z",
    close: float = 100.0,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    atr: float = 5.0,
    vol_z: float = 0.0,
    cvd: float = 0.0,
) -> dict:
    return {
        "ts_event_iso": ts,
        "close": close,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "atr": atr,
        "vol_zscore_20": vol_z,
        "cvd_5d_rolling_ffd": cvd,
    }


# ════════════════════════════════════════════════════════════════════════════
# STRUCTURE_BREAK (ICT BOS/CHoCH)
# ════════════════════════════════════════════════════════════════════════════


def test_structure_break_bullish_BOS_acceptance_multi_bar():
    """FIX R1 acceptance Dalton MOM Ch.7 : BOS fire APRES BOS_ACCEPTANCE_BARS_REQUIRED
    bars consecutives close > swing+2*tick. Pas fire instant (anti ICT liquidity sweep).
    """
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))

    # Bar 1 : close casse swing → enregistre pending (pas de fire)
    state.bar_idx_current = 10
    bar1 = _make_bar(close=100.6, vol_z=1.0)
    t1 = detect_structure_break(state, bar1, swing, tick_size=0.25)
    assert t1 is None
    assert state.bos_pending_dir == +1
    assert state.bos_pending_bars_confirmed == 1

    # Bar 2 : close TOUJOURS > swing → confirme acceptance → FIRE
    state.bar_idx_current = 11
    bar2 = _make_bar(close=100.8, vol_z=1.0)
    t2 = detect_structure_break(state, bar2, swing, tick_size=0.25)
    assert t2 is not None
    assert t2.direction == +1
    assert t2.severity > 0


def test_structure_break_bearish_BOS_acceptance_multi_bar():
    """FIX R1 : BOS bearish 2 bars acceptance avant fire."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))

    state.bar_idx_current = 10
    t1 = detect_structure_break(state, _make_bar(close=99.4, vol_z=1.0),
                                 swing, tick_size=0.25)
    assert t1 is None
    state.bar_idx_current = 11
    t2 = detect_structure_break(state, _make_bar(close=99.2, vol_z=1.0),
                                 swing, tick_size=0.25)
    assert t2 is not None
    assert t2.direction == -1


def test_structure_break_acceptance_aborted_on_retrace():
    """FIX R1 anti ICT sweep trap : si close retrace au-dessus/sous swing entre
    bar 1 et bar 2, pending ABORT (faux BOS / liquidity grab)."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))

    # Bar 1 : pending BOS bullish
    state.bar_idx_current = 10
    detect_structure_break(state, _make_bar(close=100.6, vol_z=1.0),
                           swing, tick_size=0.25)
    assert state.bos_pending_dir == +1

    # Bar 2 : close revient SOUS swing → abort pending
    state.bar_idx_current = 11
    t2 = detect_structure_break(state, _make_bar(close=99.8, vol_z=1.0),
                                 swing, tick_size=0.25)
    assert t2 is None
    assert state.bos_pending_dir == 0  # reset


def test_structure_break_no_fire_if_vol_z_negative():
    """close casse swing mais vol_z <= 0 = pas de confirmation acceptance."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 10
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    bar = _make_bar(close=101.0, vol_z=-0.5)  # vol_z<=0
    twist = detect_structure_break(state, bar, swing, tick_size=0.25)
    assert twist is None


def test_structure_break_throttle_anti_double_fire():
    """FIX R1 : apres 1 BOS valide, le suivant doit attendre 30 bars throttle.

    Maintenant le test fait 2 bars pour confirme le 1er BOS, puis tente une 3eme
    bar pour voir si throttle bloque.
    """
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))

    # 1er BOS : 2 bars acceptance
    state.bar_idx_current = 10
    detect_structure_break(state, _make_bar(close=101.0, vol_z=1.0),
                           swing, tick_size=0.25)
    state.bar_idx_current = 11
    t_first = detect_structure_break(state, _make_bar(close=101.5, vol_z=1.0),
                                      swing, tick_size=0.25)
    assert t_first is not None

    # Bar 12 : tente nouveau BOS dans throttle = bloque (global + same dir)
    state.bar_idx_current = 12
    t_second = detect_structure_break(state, _make_bar(close=102.0, vol_z=1.0),
                                       swing, tick_size=0.25)
    assert t_second is None  # throttle global 10 bars


def test_structure_break_handles_missing_swing_state():
    """swing_state None : ne fire pas (pas de reference)."""
    state = PlotTwistDetectorsState(symbol="ES")
    bar = _make_bar(close=105.0, vol_z=1.5)
    twist = detect_structure_break(state, bar, None)
    assert twist is None


def _fire_bos(state, swing, bar_idx_start, close, tick=0.25):
    """Helper : fire BOS confirme apres 2 bars acceptance (R1)."""
    state.bar_idx_current = bar_idx_start
    detect_structure_break(state, _make_bar(close=close, vol_z=1.0), swing,
                           tick_size=tick)
    state.bar_idx_current = bar_idx_start + 1
    return detect_structure_break(state, _make_bar(close=close + 0.1, vol_z=1.0),
                                   swing, tick_size=tick)


def test_R3_severity_normalized_in_ticks_cross_symbol():
    """FIX R3 : severity STRUCTURE_BREAK en ticks (cross-symbol invariant)."""
    # 10 ticks de cassure ES (tick=0.25 → 2.5pt) = severity ~1.0
    state_es = PlotTwistDetectorsState(symbol="ES")
    swing_es = StubSwingState(last_swing_high=StubSwingPoint(price=5000.0))
    twist_es = _fire_bos(state_es, swing_es, bar_idx_start=10,
                         close=5002.5, tick=0.25)
    assert twist_es is not None

    # 10 ticks MGC (tick=0.10 → 1.0pt) = MEME severity
    state_mgc = PlotTwistDetectorsState(symbol="MGC")
    swing_mgc = StubSwingState(last_swing_high=StubSwingPoint(price=2200.0))
    twist_mgc = _fire_bos(state_mgc, swing_mgc, bar_idx_start=10,
                          close=2201.0, tick=0.10)
    assert twist_mgc is not None
    # Severity identique (cross-symbol invariant)
    assert twist_es.severity == pytest.approx(twist_mgc.severity, abs=0.1)


def test_R8_BOS_throttle_global_blocks_direction_switch_in_chop():
    """FIX R8 : THROTTLE_BOS_GLOBAL=10 empeche switch rapide chop."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(
        last_swing_high=StubSwingPoint(price=100.0),
        last_swing_low=StubSwingPoint(price=99.0),
    )
    # BOS bullish confirmed a idx=10-11
    t1 = _fire_bos(state, swing, bar_idx_start=10, close=101.0)
    assert t1 is not None and t1.direction == +1

    # BOS bearish tente a idx=15 (4 bars apres confirm idx=11) - GLOBAL bloque
    state.bar_idx_current = 15
    bar_down = _make_bar(close=98.0, vol_z=1.0)
    t2 = detect_structure_break(state, bar_down, swing, tick_size=0.25)
    assert t2 is None  # Bloque par global throttle


def test_R8_BOS_trackers_separes_bullish_bearish():
    """FIX R8 : trackers separes last_BOS_bullish_bar_idx vs bearish."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(
        last_swing_high=StubSwingPoint(price=100.0),
        last_swing_low=StubSwingPoint(price=99.0),
    )
    # BOS bullish confirmed idx=10-11
    t1 = _fire_bos(state, swing, bar_idx_start=10, close=101.0)
    assert t1 is not None
    assert state.last_BOS_bullish_bar_idx == 11
    assert state.last_BOS_bearish_bar_idx == -1

    # BOS bearish confirmed idx=25-26 (apres global+bearish throttle)
    state.bar_idx_current = 25
    detect_structure_break(state, _make_bar(close=98.0, vol_z=1.0),
                            swing, tick_size=0.25)
    state.bar_idx_current = 26
    t2 = detect_structure_break(state, _make_bar(close=97.8, vol_z=1.0),
                                 swing, tick_size=0.25)
    assert t2 is not None
    assert state.last_BOS_bearish_bar_idx == 26
    assert state.last_BOS_bullish_bar_idx == 11  # preserve


def test_R6_CHoCH_short_throttle_in_uptrend():
    """FIX R6 : BOS bearish dans trend UP etabli (hh_count_60 >= 5) = CHoCH
    = throttle court 5 bars (vs 30 bars BOS continuation).
    """
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(
        last_swing_high=StubSwingPoint(price=100.0),
        last_swing_low=StubSwingPoint(price=99.0),
    )
    # Fire 1er BOS bearish dans trend UP (CHoCH)
    story = {"hh_count_60": 7, "ll_count_60": 0}  # trend up etabli
    state.bar_idx_current = 10
    detect_structure_break(state, _make_bar(close=98.0, vol_z=1.0), swing,
                           tick_size=0.25, story_trackers=story)
    state.bar_idx_current = 11
    t1 = detect_structure_break(state, _make_bar(close=97.8, vol_z=1.0), swing,
                                 tick_size=0.25, story_trackers=story)
    assert t1 is not None  # confirmed acceptance

    # Bar 17 = 6 bars apres confirm (> THROTTLE_CHOCH_BARS=5)
    # Mais < global throttle 10, donc bloque par global. Apres bar 22 :
    state.bar_idx_current = 22
    detect_structure_break(state, _make_bar(close=97.5, vol_z=1.0), swing,
                           tick_size=0.25, story_trackers=story)
    state.bar_idx_current = 23
    t2 = detect_structure_break(state, _make_bar(close=97.3, vol_z=1.0), swing,
                                 tick_size=0.25, story_trackers=story)
    # 12 bars apres 1er confirm = > 10 global + > 5 CHoCH throttle = fire
    assert t2 is not None


# ════════════════════════════════════════════════════════════════════════════
# VOLUME_ANOMALY (Wyckoff climax)
# ════════════════════════════════════════════════════════════════════════════


def test_volume_anomaly_fires_at_threshold():
    """vol_z > VOL_Z_ANOMALY_MIN (=2.5) → VOLUME_ANOMALY."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=100.0, vol_z=2.8)  # > 2.5
    twist = detect_volume_anomaly(state, bar)
    assert twist is not None
    assert twist.twist_type == "VOLUME_ANOMALY"
    assert twist.severity > 0


def test_volume_anomaly_direction_wyckoff_canon_selling_climax():
    """FIX R2 review market-analyst : Pruden Ch.5 selling climax = close<open +
    vol_z extreme MAIS signal BULLISH (acheteurs absorbants entrent au plancher).
    Direction = +1 (INVERSE de close-open sign).

    Avant fix : direction = -1 (suit close-open) = INVERSE de Wyckoff = bug semantique.
    """
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    # Selling climax : close < open + grosse vol
    bar = _make_bar(close=98.0, open_=102.0, vol_z=3.0)
    twist = detect_volume_anomaly(state, bar)
    assert twist is not None
    # Wyckoff canon : selling climax (panic sellers absorbed) = BULLISH signal
    assert twist.direction == +1


def test_volume_anomaly_direction_wyckoff_canon_buying_climax():
    """FIX R2 : Pruden buying climax = close>open + vol extreme MAIS signal BEARISH
    (vendeurs absorbants livrent au sommet). Direction = -1."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=102.0, open_=98.0, vol_z=3.0)  # close>open
    twist = detect_volume_anomaly(state, bar)
    assert twist is not None
    assert twist.direction == -1  # absorption thesis : opposed to bar direction


def test_volume_anomaly_direction_delta_pct_priority():
    """FIX R2 : si delta_pct present, prend priorite sur close-open.
    delta_pct > 0 = buyers aggress = direction climax = -1 (absorbants vendent)."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=102.0, open_=98.0, vol_z=3.0)
    bar["delta_pct"] = 0.5  # buyers aggress fort
    twist = detect_volume_anomaly(state, bar)
    assert twist is not None
    assert twist.direction == -1  # contra aggressor buyers


def test_volume_anomaly_no_fire_below_threshold():
    """vol_z < VOL_Z_ANOMALY_MIN (=2.5) : no fire."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=100.0, vol_z=2.0)  # < 2.5
    twist = detect_volume_anomaly(state, bar)
    assert twist is None


def test_volume_anomaly_throttle():
    """2 fires consecutifs < 3 bars apart : seul le 1er fire."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=100.0, vol_z=2.8)
    t1 = detect_volume_anomaly(state, bar)
    assert t1 is not None
    state.bar_idx_current = 6
    t2 = detect_volume_anomaly(state, bar)
    assert t2 is None


# ════════════════════════════════════════════════════════════════════════════
# DIVERGENCE (price vs CVD - Wyckoff effort/result)
# ════════════════════════════════════════════════════════════════════════════


def test_divergence_requires_min_history():
    """< DIVERGENCE_PRICE_LOOKBACK bars : pas de divergence."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 1
    bar = _make_bar(close=100.0, cvd=1000.0)
    twist = detect_divergence(state, bar)
    assert twist is None


def test_divergence_bearish_NEW_HH_extreme_cvd_DOWN():
    """high_now > max(highs window) ET cvd_now < cvd_ref → divergence -1.

    Fix 18/05 Wyckoff canon : exige NEW EXTREME absolu, pas juste mouvement up.
    """
    state = PlotTwistDetectorsState(symbol="ES")
    # Fill bars_history avec high=105 max + cvd croissant
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": 2000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    # bar actuelle : NEW HH (110.5 > max(105) window) + CVD descend
    bar = _make_bar(close=110.0, high=110.5, cvd=1000.0)
    twist = detect_divergence(state, bar)
    assert twist is not None
    assert twist.direction == -1


def test_divergence_bullish_NEW_LL_extreme_cvd_UP():
    """low_now < min(lows window) ET cvd_now > cvd_ref → divergence +1."""
    state = PlotTwistDetectorsState(symbol="ES")
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": -1000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    # NEW LL : low_now 89.5 < min(95) window + cvd up
    bar = _make_bar(close=90.0, low=89.5, cvd=500.0)
    twist = detect_divergence(state, bar)
    assert twist is not None
    assert twist.direction == +1


def test_divergence_no_fire_without_new_extreme():
    """Fix 18/05 : price moves UP mais PAS new HH absolu = pas de divergence.

    Avant fix : ANY price up + CVD down = divergence (trop sensible).
    Apres fix : exige high_now > max(window).
    """
    state = PlotTwistDetectorsState(symbol="ES")
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": 2000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    # bar high=104 (PAS new HH, max window=105) + CVD descend
    # Avant fix : firait sur high_now > high_ref simple. Apres fix : non.
    bar = _make_bar(close=103.0, high=104.0, cvd=1000.0)
    twist = detect_divergence(state, bar)
    assert twist is None


def test_divergence_no_fire_if_price_and_cvd_aligned():
    """Price NEW HH + CVD up = aligne = pas de divergence."""
    state = PlotTwistDetectorsState(symbol="ES")
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": 1000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    bar = _make_bar(close=110.0, high=110.5, cvd=3000.0)  # NEW HH + CVD up = aligne
    twist = detect_divergence(state, bar)
    assert twist is None


# ════════════════════════════════════════════════════════════════════════════
# CAPITULATION (3+ bars climax consecutifs)
# ════════════════════════════════════════════════════════════════════════════


def test_capitulation_requires_3_consecutive_climax():
    """1 bar climax = pas de capitulation (besoin 3 consecutifs)."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 1
    # Bar climax : vol_z>2.5 + range>1.5*atr
    bar = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                    atr=5.0, vol_z=3.0)  # range=13 > 1.5*5=7.5
    twist = detect_capitulation(state, bar)
    assert twist is None  # 1 seule bar


def test_capitulation_fires_after_3_bars_in_window():
    """FIX R7 : 3+ climax dans WINDOW 5 bars (peut avoir retracements
    Pruden Three Pushes canon). FIX R2 : direction Wyckoff canon INVERSE."""
    state = PlotTwistDetectorsState(symbol="ES")
    # close<open + climax = selling climax bars → direction = +1 (bullish absorption)
    bar_template = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                              atr=5.0, vol_z=3.5)
    state.bar_idx_current = 1
    detect_capitulation(state, bar_template)
    state.bar_idx_current = 2
    detect_capitulation(state, bar_template)
    state.bar_idx_current = 3
    twist = detect_capitulation(state, bar_template)
    assert twist is not None
    assert twist.twist_type == "CAPITULATION"
    # FIX R2+R7 : direction Wyckoff canon = INVERSE close-open
    # close<open (selling climax bars) → signal BULLISH absorption
    assert twist.direction == +1


def test_R7_capitulation_window_based_with_retracement():
    """FIX R7 Pruden Three Pushes canon : permet retracement intermediaire.

    Avant : 3 bars consecutifs strict → reset au moindre non-climax.
    Apres : window 5 bars, >= 3 climax dedans = fire.

    Scenario : climax-climax-NORMAL-climax-climax = 4 climax dans window 5 bars.
    """
    state = PlotTwistDetectorsState(symbol="ES")
    climax = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                       atr=5.0, vol_z=3.5)
    normal = _make_bar(close=100.0, vol_z=1.0)  # PAS climax

    state.bar_idx_current = 1
    t1 = detect_capitulation(state, climax)  # climax 1, no fire
    assert t1 is None
    state.bar_idx_current = 2
    t2 = detect_capitulation(state, climax)  # climax 2, no fire
    assert t2 is None
    state.bar_idx_current = 3
    t3 = detect_capitulation(state, normal)  # retracement, no append
    assert t3 is None
    state.bar_idx_current = 4
    # climax 3eme dans window (bars 1, 2, 4) → FIRE (3+ dans window 5 bars)
    twist = detect_capitulation(state, climax)
    assert twist is not None
    assert twist.triggering_features["n_climax_bars"] >= 3


def test_capitulation_reset_on_non_climax_bar():
    """climax-climax-NORMAL-climax = pas 3 consecutifs."""
    state = PlotTwistDetectorsState(symbol="ES")
    climax = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                       atr=5.0, vol_z=3.0)
    normal = _make_bar(close=100.0, vol_z=1.0)  # pas climax
    state.bar_idx_current = 1
    detect_capitulation(state, climax)
    state.bar_idx_current = 2
    detect_capitulation(state, climax)
    state.bar_idx_current = 3
    detect_capitulation(state, normal)  # reset buffer
    assert len(state.climax_buffer) == 0
    state.bar_idx_current = 4
    twist = detect_capitulation(state, climax)
    assert twist is None  # buffer juste reset, 1 bar


def test_capitulation_direction_buying_climax_bearish_wyckoff():
    """FIX R2+R7 : 3 bars close>open + climax = buying climax = signal BEARISH
    (vendeurs absorbants livrent au sommet). Direction = -1 (Wyckoff canon)."""
    state = PlotTwistDetectorsState(symbol="ES")
    bar = _make_bar(close=102.0, open_=98.0, high=105.0, low=92.0,
                    atr=5.0, vol_z=3.5)
    for i in range(1, 4):
        state.bar_idx_current = i
        result = detect_capitulation(state, bar)
    assert result is not None
    # close>open (buying climax bars) → Wyckoff canon : signal BEARISH absorption
    assert result.direction == -1


# ════════════════════════════════════════════════════════════════════════════
# scan_all integration
# ════════════════════════════════════════════════════════════════════════════


def test_scan_all_increments_bar_idx():
    """Chaque scan_all increment bar_idx_current."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    for i in range(5):
        scan_all(state, _make_bar(close=100.0), swing)
    assert state.bar_idx_current == 5


def test_scan_all_appends_bars_history():
    """bars_history.append apres detection (preserve lookback CVD)."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    for i in range(15):
        scan_all(state, _make_bar(close=100.0 + i, cvd=1000.0 + i * 100), swing)
    assert len(state.bars_history) == BARS_HISTORY_MAXLEN  # ring buffer FIFO


def test_scan_all_multiple_twists_same_bar():
    """VOLUME_ANOMALY peut fire seule sur 1 bar (BOS necessite 2 bars R1)."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    bar = _make_bar(close=101.0, open_=99.5, high=105.0, low=95.0,
                    atr=5.0, vol_z=3.0)  # > VOL_Z_ANOMALY_MIN=2.5

    # Bar 1 : VOLUME_ANOMALY fire + BOS pending (pas encore confirmed R1)
    twists1 = scan_all(state, bar, swing, tick_size=0.25)
    twist_types1 = {t.twist_type for t in twists1}
    assert "VOLUME_ANOMALY" in twist_types1
    assert "STRUCTURE_BREAK" not in twist_types1  # pending, pas fire

    # Bar 2 : BOS confirmed acceptance
    bar2 = _make_bar(close=101.5, open_=100.5, high=105.0, low=95.0,
                    atr=5.0, vol_z=1.0)
    twists2 = scan_all(state, bar2, swing, tick_size=0.25)
    twist_types2 = {t.twist_type for t in twists2}
    assert "STRUCTURE_BREAK" in twist_types2


def test_pickle_roundtrip_preserves_state():
    """Pickle dump/load preserve bars_history + climax_buffer + last_twist_bar_idx."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    for i in range(8):
        scan_all(state, _make_bar(close=100.0 + i, cvd=1000.0 + i * 100), swing)
    state.last_twist_bar_idx["TEST"] = 42

    blob = pickle.dumps(state)
    loaded = pickle.loads(blob)
    assert loaded.symbol == "ES"
    assert len(loaded.bars_history) == 8
    assert loaded.bar_idx_current == 8
    assert loaded.last_twist_bar_idx["TEST"] == 42
    # _lock recreee au load
    with loaded.lock:
        pass


def test_scan_all_handles_nan_gracefully():
    """Bars avec NaN ne crashent pas."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    bar = {
        "ts_event_iso": "x",
        "close": float("nan"), "open": float("nan"),
        "high": float("nan"), "low": float("nan"),
        "atr": float("nan"), "vol_zscore_20": float("nan"),
        "cvd_5d_rolling_ffd": float("nan"),
    }
    twists = scan_all(state, bar, swing)
    assert isinstance(twists, list)  # pas de crash
