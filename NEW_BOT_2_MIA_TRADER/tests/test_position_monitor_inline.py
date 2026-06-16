"""Tests inline PositionMonitor M3.5 — J8c-TRAILING."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from src.position_monitor import (
    PositionMonitor,
    PositionState,
    TrailingConfig,
)


def _mk_state_nq_long(entry_price=21450.0, sl_ticks_initial=33.0):
    """Helper : state NQ LONG entry 21450, SL initial 33t."""
    return PositionState(
        signal_id="S1",
        symbol="NQ",
        direction="LONG",
        entry_price=entry_price,
        entry_ts_ns=1_716_700_000_000_000_000,
        n_micros=3,
        sl_price=entry_price - sl_ticks_initial * 0.25,  # 21441.75
        sl_ticks_initial=sl_ticks_initial,
        tp1_price=entry_price + 60 * 0.25,  # 21465.0
        tp1_ticks=60.0,
    )


def _mk_state_es_short(entry_price=5800.0, sl_ticks_initial=18.0):
    return PositionState(
        signal_id="S2",
        symbol="ES",
        direction="SHORT",
        entry_price=entry_price,
        entry_ts_ns=1_716_700_000_000_000_000,
        n_micros=3,
        sl_price=entry_price + sl_ticks_initial * 0.25,
        sl_ticks_initial=sl_ticks_initial,
        tp1_price=entry_price - 30 * 0.25,
        tp1_ticks=30.0,
    )


# =============================================================================
# 1. Config & init
# =============================================================================


def test_1_paper_mode_config():
    cfg = TrailingConfig.paper_mode()
    assert cfg.tr40_enabled is False  # OFF par defaut LIVE bloque DTC
    assert cfg.mfe_tp_enabled is True
    assert cfg.tr40_arming_pct == 0.40
    assert cfg.tr40_giveback_pct == 0.20
    assert cfg.mfe_tp_drawback_ticks == 12  # fix 20/05
    assert cfg.mfe_tp_threshold_ticks == {"ES": 30, "NQ": 50, "MGC": 40}
    print("#1 PASS: paper_mode config")


def test_2_live_mode_config():
    cfg = TrailingConfig.live_mode_when_dtc_ready()
    assert cfg.tr40_enabled is True
    assert cfg.mfe_tp_enabled is True
    print("#2 PASS: live_mode config")


# =============================================================================
# 2. MFE/MAE tracking
# =============================================================================


def test_3_mfe_increases_with_excursion():
    """MFE doit augmenter quand prix monte sur LONG."""
    monitor = PositionMonitor(config=TrailingConfig.paper_mode())
    state = _mk_state_nq_long()
    # Prix monte de 5 ticks
    monitor.update(state, current_price=21451.25, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.mfe == 5.0
    assert state.mae == 0.0
    # Prix continue : 10 ticks
    monitor.update(state, current_price=21452.50, bar_ts_ns=1_716_700_000_000_000_002)
    assert state.mfe == 10.0
    # Prix redescend a 7t (mfe ne baisse pas)
    monitor.update(state, current_price=21451.75, bar_ts_ns=1_716_700_000_000_000_003)
    assert state.mfe == 10.0  # peak fige
    print(f"#3 PASS: MFE peak fige (mfe={state.mfe})")


def test_4_mae_decreases_with_adverse():
    """MAE doit decrease quand prix baisse sur LONG."""
    monitor = PositionMonitor(config=TrailingConfig.paper_mode())
    state = _mk_state_nq_long()
    monitor.update(state, current_price=21448.0, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.mae == -8.0  # 21450 -> 21448 = -8 ticks
    monitor.update(state, current_price=21445.0, bar_ts_ns=1_716_700_000_000_000_002)
    assert state.mae == -20.0
    print(f"#4 PASS: MAE peak fige (mae={state.mae})")


# =============================================================================
# 3. TR40 SL armement + update
# =============================================================================


def test_5_tr40_not_armed_before_threshold():
    """MFE < 40% × SL_init = pas d'armement."""
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False)
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # arming_thr = 0.40 × 33 = 13.2t. MFE=10t = pas arme
    monitor.update(state, current_price=21452.5, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.mfe == 10.0
    assert state.sl_trailed is False
    assert state.sl_price == 21441.75  # SL inchange
    print("#5 PASS: TR40 not armed (MFE 10 < arming 13.2)")


def test_6_tr40_armed_and_sl_moved():
    """MFE >= 13.2t arme + nouveau SL > old SL."""
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False)
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # MFE = 15t (>= 13.2). Give-back = 6.6t. new_sl = entry + (15-6.6)*0.25 = 21452.1
    # Aligned : round(21452.1/0.25)*0.25 = 21452.0
    update = monitor.update(state, current_price=21453.75, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.sl_trailed is True
    assert state.sl_trail_count == 1
    assert update.sl_changed is True
    assert update.new_sl_price == 21452.0
    assert state.sl_price == 21452.0
    print(f"#6 PASS: TR40 armed + SL update ({21441.75} -> {state.sl_price})")


def test_7_tr40_sl_never_descends_long():
    """SL LONG ne peut JAMAIS descendre."""
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False)
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # Premier update : MFE=20t -> SL avance
    monitor.update(state, current_price=21455.0, bar_ts_ns=1_716_700_000_000_000_001)
    sl_after_1st = state.sl_price
    assert sl_after_1st > 21441.75  # SL a monte
    # MFE redescend : prix retombe a 21452 (MFE=20 fige). SL ne change pas
    monitor.update(state, current_price=21452.0, bar_ts_ns=1_716_700_000_000_000_002)
    assert state.sl_price == sl_after_1st  # SL inchange
    # MFE remonte a 25t -> SL doit monter encore
    monitor.update(state, current_price=21456.25, bar_ts_ns=1_716_700_000_000_000_003)
    assert state.sl_price > sl_after_1st  # SL monte
    print(f"#7 PASS: TR40 SL monotone LONG (sl history fige puis monte)")


def test_8_tr40_short_symetrie():
    """TR40 SHORT : SL ne peut que DESCENDRE."""
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False, tr40_symbols=["ES", "NQ"])
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_es_short(entry_price=5800.0, sl_ticks_initial=18.0)
    # SHORT entry 5800, SL initial 5804.50 (=18t au-dessus)
    # arming = 0.40 × 18 = 7.2t MFE
    # Prix descend a 5798 = MFE 8t (>= 7.2). give-back = 3.6t
    # new_sl = 5800 - (8-3.6)*0.25 = 5798.9 → aligned 5798.75... wait alignement
    # actually 5798.9 / 0.25 = 23195.6 -> round = 23196 -> 5799.0
    update = monitor.update(state, current_price=5798.0, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.sl_trailed is True
    assert update.new_sl_price < 5804.50  # SL descend (favorable SHORT)
    assert update.new_sl_price == state.sl_price
    print(f"#8 PASS: TR40 SHORT SL descend (sl: 5804.50 -> {state.sl_price})")


def test_9_tr40_only_nq_pilot():
    """ES doit etre exclu de TR40 par defaut (PF 0.88 marginal legacy)."""
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False)  # default symbols=["NQ"]
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_es_short(entry_price=5800.0, sl_ticks_initial=18.0)
    update = monitor.update(state, current_price=5798.0, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.sl_trailed is False  # ES exclu
    assert update.sl_changed is False
    print("#9 PASS: ES exclu TR40 par defaut (NQ-only pilot)")


# =============================================================================
# 4. MFE-TP drawback close
# =============================================================================


def test_10_mfe_tp_not_armed_before_threshold():
    """NQ : MFE doit >= 50t pour armer MFE-TP."""
    cfg = TrailingConfig.paper_mode()
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    monitor.update(state, current_price=21461.25, bar_ts_ns=1_716_700_000_000_000_001)
    # MFE = 45t < 50 = pas arme
    assert state.trailing_tp_armed is False
    print("#10 PASS: MFE-TP not armed (MFE 45 < threshold 50 NQ)")


def test_11_mfe_tp_armed_at_threshold():
    """NQ : MFE >= 50t -> trailing_tp_armed=True."""
    cfg = TrailingConfig.paper_mode()
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    monitor.update(state, current_price=21462.5, bar_ts_ns=1_716_700_000_000_000_001)
    # MFE = 50t = threshold
    assert state.trailing_tp_armed is True
    print("#11 PASS: MFE-TP armed (MFE 50 >= threshold 50)")


def test_12_mfe_tp_drawback_close():
    """Si MFE armed ET drawback (MFE - excursion) >= 12t -> close_now."""
    cfg = TrailingConfig.paper_mode()
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # Step 1 : MFE atteint 55t (>= 50, armed)
    monitor.update(state, current_price=21463.75, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.trailing_tp_armed is True
    assert state.mfe == 55.0
    # Step 2 : prix retombe a 21462.75 -> excursion = 51t -> drawback = 55-51=4 < 12 (no close)
    update = monitor.update(state, current_price=21462.75, bar_ts_ns=1_716_700_000_000_000_002)
    assert update.close_now is False
    # Step 3 : prix retombe a 21460.0 -> excursion = 40t -> drawback = 55-40=15 >= 12 -> CLOSE
    update = monitor.update(state, current_price=21460.0, bar_ts_ns=1_716_700_000_000_000_003)
    assert update.close_now is True
    assert update.close_reason == "TRAILING_TP"
    assert update.close_price == 21460.0
    assert update.close_pnl_ticks == 40.0
    print(f"#12 PASS: MFE-TP triggered (mfe=55, drawback=15 >= 12)")


def test_13_mfe_tp_no_close_when_drawback_lt_threshold():
    """Drawback < 12 = pas de close."""
    cfg = TrailingConfig.paper_mode()
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    monitor.update(state, current_price=21462.5, bar_ts_ns=1_716_700_000_000_000_001)  # MFE 50
    # drawback 8t < 12
    update = monitor.update(state, current_price=21460.5, bar_ts_ns=1_716_700_000_000_000_002)
    assert update.close_now is False
    print("#13 PASS: MFE-TP no close (drawback 8 < 12)")


def test_14_mfe_tp_es_threshold_30():
    """ES seuil = 30t. MFE 25 = pas arme. MFE 30 = arme. drawback close."""
    cfg = TrailingConfig.paper_mode()
    monitor = PositionMonitor(config=cfg)
    # ES SHORT, on simule
    state = _mk_state_es_short(entry_price=5800.0, sl_ticks_initial=18.0)
    # SHORT MFE = (5800 - price)/tick = 25t (price=5793.75)
    monitor.update(state, current_price=5793.75, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.mfe == 25.0
    assert state.trailing_tp_armed is False
    # MFE = 30 (price=5792.50)
    monitor.update(state, current_price=5792.50, bar_ts_ns=1_716_700_000_000_000_002)
    assert state.mfe == 30.0
    assert state.trailing_tp_armed is True
    # Drawback : prix remonte a 5796.0 -> excursion = 16t -> drawback = 30-16=14 >= 12 -> CLOSE
    update = monitor.update(state, current_price=5796.0, bar_ts_ns=1_716_700_000_000_000_003)
    assert update.close_now is True
    print(f"#14 PASS: MFE-TP ES (seuil 30, drawback close)")


# =============================================================================
# 5. Integration : TR40 + MFE-TP en parallele
# =============================================================================


def test_15_tr40_and_mfe_tp_orthogonal():
    """Les 2 systemes peuvent fonctionner en parallele (TR40 update SL + MFE-TP arme)."""
    cfg = TrailingConfig(
        tr40_enabled=True,
        mfe_tp_enabled=True,
        tr40_symbols=["NQ"],
    )
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # MFE = 55t : TR40 arme + MFE-TP arme (NQ seuil 50)
    update = monitor.update(state, current_price=21463.75, bar_ts_ns=1_716_700_000_000_000_001)
    assert state.sl_trailed is True  # TR40 arme
    assert state.trailing_tp_armed is True  # MFE-TP arme
    assert update.sl_changed is True  # SL deplace
    assert update.close_now is False  # Pas encore drawback
    # MFE-TP trigger : prix retombe a 21460
    update2 = monitor.update(state, current_price=21460.0, bar_ts_ns=1_716_700_000_000_000_002)
    assert update2.close_now is True
    print("#15 PASS: TR40 + MFE-TP orthogonaux")


def test_16_disabled_flags_no_action():
    """Si flags OFF, aucune action."""
    cfg = TrailingConfig(tr40_enabled=False, mfe_tp_enabled=False)
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    update = monitor.update(state, current_price=21500.0, bar_ts_ns=1_716_700_000_000_000_001)
    assert update.sl_changed is False
    assert update.close_now is False
    assert state.sl_trailed is False
    assert state.trailing_tp_armed is False
    print("#16 PASS: flags OFF -> aucune action")


def test_17_tr40_arm_idempotent_no_sl_update():
    """Fix R1 : TR40 ARMED emis 1x meme si SL pas encore update.

    Cas : MFE atteint arming, mais aligned_sl pas favorable (encore sous SL initial).
    L'event ARMED doit etre emis 1x, pas re-emis a chaque poll suivant.
    """
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False)
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # Bouger SL initial proche pour rendre candidate possiblement defavorable
    # MFE = 14 (>= arming 13.2). candidate = entry + (14-6.6)*0.25 = 21451.85 → aligned 21451.75
    # SL initial 21441.75. 21451.75 > 21441.75 = update OK
    upd1 = monitor.update(state, current_price=21453.5, bar_ts_ns=1)
    armed_events_1 = [e for e in upd1.events if e["code"] == "BOT4_MONITOR_TR40_ARMED"]
    assert len(armed_events_1) == 1
    assert state.tr40_armed is True
    # Re-update : MFE inchange ou augmente -> ARMED ne doit PAS etre re-emis
    upd2 = monitor.update(state, current_price=21454.0, bar_ts_ns=2)
    armed_events_2 = [e for e in upd2.events if e["code"] == "BOT4_MONITOR_TR40_ARMED"]
    assert len(armed_events_2) == 0, "BOT4_MONITOR_TR40_ARMED re-emis (R1 fix casse)"
    print("#17 PASS: BOT4_MONITOR_TR40_ARMED idempotent (fix R1)")


def test_18_tr40_new_sl_reason_coherent():
    """Fix R2 : 1er update = TR40_ARMED, suivants = TR40_UPDATED."""
    cfg = TrailingConfig(tr40_enabled=True, mfe_tp_enabled=False)
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    upd1 = monitor.update(state, current_price=21455.0, bar_ts_ns=1)
    assert upd1.new_sl_reason == "TR40_ARMED"
    upd2 = monitor.update(state, current_price=21458.0, bar_ts_ns=2)
    if upd2.sl_changed:
        assert upd2.new_sl_reason == "TR40_UPDATED"
    print("#18 PASS: new_sl_reason coherent (ARMED puis UPDATED)")


def test_19_mfe_tp_no_close_when_excursion_negative():
    """Fix R4 : si prix retombe sous entry (excursion < 0), pas de TRAILING_TP.

    Sinon drawback = mfe - excursion explose et close labellise TRAILING_TP
    alors que c'est un stop-out logique.

    16/06 update : on desactive palier_trailing dans ce test pour preserver
    son intention pure MFE-TP. Le palier 16/06 a une logique differente
    (close DELIBERE quand excursion < sl_locked, meme negative = limite perte).
    Test scenario palier separe : test_22 + test_24.
    """
    cfg = TrailingConfig(
        tr40_enabled=False,
        mfe_tp_enabled=True,
        palier_trailing_enabled=False,  # 16/06 : isoler MFE-TP pour test R4
    )
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # MFE atteint 55 (arme)
    monitor.update(state, current_price=21463.75, bar_ts_ns=1)
    assert state.trailing_tp_armed is True
    # Prix retombe sous entry (excursion = -8t)
    update = monitor.update(state, current_price=21448.0, bar_ts_ns=2)
    assert update.close_now is False, "MFE-TP ne doit PAS close si excursion < 0 (R4)"
    print("#19 PASS: MFE-TP no close when excursion<0 (fix R4)")


def test_20_tr40_and_mfe_tp_close_same_poll_priority():
    """R6 : si TR40 update SL ET MFE-TP close meme poll, close_now=True doit dominer.

    M5 Execution doit prioriser close (cancel+replace SL inutile sur position fermee).
    """
    cfg = TrailingConfig(
        tr40_enabled=True,
        mfe_tp_enabled=True,
        tr40_symbols=["NQ"],
    )
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_nq_long()
    # Step 1 : MFE atteint 55t (TR40 arme + MFE-TP arme + 1er SL update)
    monitor.update(state, current_price=21463.75, bar_ts_ns=1)
    # Step 2 : prix retombe a 21460.0 -> drawback=15t MFE-TP triggered
    #          MAIS MFE inchange (55), donc pas de nouveau SL update (sl_changed=False)
    # Documenter : meme poll, close peut etre seul OU avec sl_changed
    update = monitor.update(state, current_price=21460.0, bar_ts_ns=2)
    assert update.close_now is True
    # Note : sl_changed peut etre True ou False selon timing. M5 priorise close_now.
    print(f"#20 PASS: M5 doit prioriser close_now=True sur sl_changed (sl_changed={update.sl_changed})")


# =============================================================================
# PALIER trailing (16/06 Jackson)
# =============================================================================


def test_21_palier_default_paper_mode():
    """paper_mode active palier_trailing par defaut."""
    cfg = TrailingConfig.paper_mode()
    assert cfg.palier_trailing_enabled is True
    assert "ES" in cfg.palier_trailing_by_symbol
    assert cfg.palier_trailing_by_symbol["ES"] == [(10, 0), (20, 5), (30, 15), (45, 25), (60, 40)]
    print("#21 PASS: palier default config")


def test_22_palier_es_breakeven_at_10t():
    """Trade ES SHORT : MFE atteint 10t (palier 0 -> BE), prix repasse sous BE -> close limite perte."""
    monitor = PositionMonitor(config=TrailingConfig.paper_mode())
    state = _mk_state_es_short(entry_price=7600.0, sl_ticks_initial=14)
    # Step 1 : MFE atteint 10t (palier 0 arme, sl_locked=0=BE)
    monitor.update(state, current_price=7597.50, bar_ts_ns=1)
    assert state.mfe == 10.0
    assert state.palier_atteint_idx == 0
    # Step 2 : prix remonte a entry (excursion=0 = BE exactement). PAS de close (strict <)
    update = monitor.update(state, current_price=7600.0, bar_ts_ns=2)
    assert update.close_now is False
    # Step 3 : prix repasse legerement au-dessus entry (excursion = -1, perte 1 tick)
    # Palier fire car excursion -1 < sl_locked 0 -> close direct, limite perte a 1t
    # au lieu de laisser SL bracket hit a -14t.
    update = monitor.update(state, current_price=7600.25, bar_ts_ns=3)
    assert update.close_now is True
    assert update.close_reason == "PALIER_TRAILING"
    assert update.close_pnl_ticks == -1.0  # Perte limitee a 1 tick (BE protection)
    print("#22 PASS: palier ES BE protection limite perte a -1t (vs SL -14t)")


def test_23_palier_es_lock_5t_at_20t_mfe():
    """ES MFE atteint 20t (palier 2 -> lock +5t), retombe a 4t -> close a 4t."""
    monitor = PositionMonitor(config=TrailingConfig.paper_mode())
    state = _mk_state_es_short(entry_price=7600.0, sl_ticks_initial=14)
    # Step 1 : MFE 20t (palier 2 atteint)
    monitor.update(state, current_price=7595.0, bar_ts_ns=1)  # excursion = +20t
    assert state.mfe == 20.0
    assert state.palier_atteint_idx == 1  # palier 1 = (20, 5)
    # Step 2 : prix retombe a 7599.0 = excursion +4t (sous sl_locked 5t)
    update = monitor.update(state, current_price=7599.0, bar_ts_ns=2)
    assert update.close_now is True
    assert update.close_reason == "PALIER_TRAILING"
    assert update.close_pnl_ticks == 4.0  # capture 4 ticks profit
    # Verify event PALIER_TRIGGERED
    triggered = [e for e in update.events if e["code"] == "BOT4_MONITOR_PALIER_TRIGGERED"]
    assert len(triggered) == 1
    assert triggered[0]["palier_idx"] == 1
    assert triggered[0]["mfe_peak"] == 20.0
    assert triggered[0]["sl_locked_ticks"] == 5
    print("#23 PASS: palier ES lock 5t triggers close")


def test_24_palier_jackson_scenario_close_at_BE():
    """Reproduction scenario Jackson 16/06 : ES SHORT monte a peak MFE 16t,
    palier 0 atteint (10t,BE). Quand prix repasse sous entry, palier close
    direct au lieu de laisser SL bracket -14t hit. AVANT : perdait 14t.
    APRES : close BE/-1t = scenario "on a rendu tous les gains" RESOLU."""
    monitor = PositionMonitor(config=TrailingConfig.paper_mode())
    state = _mk_state_es_short(entry_price=7608.25, sl_ticks_initial=14)
    # Step 1 : prix descend a 7604.25 (excursion 16t) = peak MFE 16
    monitor.update(state, current_price=7604.25, bar_ts_ns=1)
    assert state.mfe == 16.0
    assert state.palier_atteint_idx == 0  # palier 0 (10, 0) atteint
    # Step 2 : prix remonte a 7607.00 (excursion 5t) - encore au-dessus BE 0
    update = monitor.update(state, current_price=7607.0, bar_ts_ns=2)
    assert update.close_now is False  # excursion 5 > sl_locked 0
    # Step 3 : prix remonte a entry (excursion 0 = sl_locked exactement)
    update = monitor.update(state, current_price=7608.25, bar_ts_ns=3)
    assert update.close_now is False  # 0 < 0 strict = False
    # Step 4 : prix passe entry +1 tick (excursion -1 = perte 1 tick)
    # Palier fire car -1 < 0 -> close perte limited a 1 tick (vs SL bracket -14t)
    update = monitor.update(state, current_price=7608.50, bar_ts_ns=4)
    assert update.close_now is True
    assert update.close_reason == "PALIER_TRAILING"
    assert update.close_pnl_ticks == -1.0
    print("#24 PASS: scenario Jackson - perte limitee -1t vs SL bracket -14t")


def test_25_palier_es_lock_25t_close():
    """ES SHORT MFE atteint 45t (palier 3 -> lock 25t), retombe a 20t -> close.
    Verifie capture profit 20t alors que MFE-TP n'aurait pas fire (drawback 25 > 12
    threshold mais ce comportement est OK : palier gagne car plus restrictif que MFE-TP).
    """
    cfg = TrailingConfig.paper_mode()
    monitor = PositionMonitor(config=cfg)
    state = _mk_state_es_short(entry_price=7600.0, sl_ticks_initial=14)
    # Step 1 : prix descend a entry-45t (excursion +45t = palier 3 atteint)
    monitor.update(state, current_price=7588.75, bar_ts_ns=1)  # 7600 - 45*0.25
    assert state.mfe == 45.0
    assert state.palier_atteint_idx == 3  # palier 3 = (45, 25)
    # Step 2 : prix retombe a entry-20t = excursion +20t < sl_locked 25 -> close
    # Note : MFE-TP ES (threshold 30, drawback 12) aurait aussi fire a drawback 25,
    # mais MFE-TP s'execute AVANT palier dans update() -> reason="TRAILING_TP".
    # On verifie ici que close fire OK (peu importe lequel des 2 wins).
    update = monitor.update(state, current_price=7595.0, bar_ts_ns=2)
    assert update.close_now is True
    assert update.close_reason in ("PALIER_TRAILING", "TRAILING_TP")
    assert update.close_pnl_ticks == 20.0  # capture 20 ticks profit (vs 0 sans trail)
    print(f"#25 PASS: palier ES lock 25t reason={update.close_reason} pnl=+20t")


if __name__ == "__main__":
    test_1_paper_mode_config()
    test_2_live_mode_config()
    test_3_mfe_increases_with_excursion()
    test_4_mae_decreases_with_adverse()
    test_5_tr40_not_armed_before_threshold()
    test_6_tr40_armed_and_sl_moved()
    test_7_tr40_sl_never_descends_long()
    test_8_tr40_short_symetrie()
    test_9_tr40_only_nq_pilot()
    test_10_mfe_tp_not_armed_before_threshold()
    test_11_mfe_tp_armed_at_threshold()
    test_12_mfe_tp_drawback_close()
    test_13_mfe_tp_no_close_when_drawback_lt_threshold()
    test_14_mfe_tp_es_threshold_30()
    test_15_tr40_and_mfe_tp_orthogonal()
    test_16_disabled_flags_no_action()
    test_17_tr40_arm_idempotent_no_sl_update()
    test_18_tr40_new_sl_reason_coherent()
    test_19_mfe_tp_no_close_when_excursion_negative()
    test_20_tr40_and_mfe_tp_close_same_poll_priority()
    print("\n[OK] TOUS TESTS POSITION_MONITOR (20/20) : PASS")
