"""Tests E2E sample JSONL reel - validation pipeline complet bot4_v2.

Phase P5.3.C : execution dry-run sur 100 bars NQ historiques reels pour valider :
- ContextBuilder consume bars 621-features sans crash
- DecisionRouter route_bar(ctx) ne crash pas
- PositionReconciler tick() OK
- BotMainLoop.run() max_cycles=100 termine clean
- Metriques attendues (compteurs > 0 sur certaines categories)

EXCLU scope :
- Backtest preservation wins (P6 + Jackson budget broker)
- Validation P&L (dry-run = aucun trade reel)
- Comparaison Bot 4 v2 vs Bot 3 BN V4 (necessite 14j historiques + replay
  multi-bot harness)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bot4_v2.main.__main__ import main


# Fixture sample 100 bars NQ reels (DATA/live_enriched/sierra/NQ/20260624)
SAMPLE_PATH = Path(__file__).parent / "fixtures" / "sample_100_NQ.jsonl"


# ============================================================
# E2E light : pipeline complet sans crash
# ============================================================


def test_e2e_replay_100_bars_real_nq_no_crash(tmp_path):
    """100 bars NQ reels via main() dry-run -> exit 0 sans crash."""
    if not SAMPLE_PATH.exists():
        pytest.skip(f"Fixture {SAMPLE_PATH} absent")
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()
    rc = main([
        "--symbols", "NQ",
        "--replay", str(SAMPLE_PATH),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "100",
        "--heartbeat-sec", "0",
    ])
    assert rc == 0


def test_e2e_replay_50_bars_subset(tmp_path):
    """Subset 50 premiers bars -> exit 0."""
    if not SAMPLE_PATH.exists():
        pytest.skip(f"Fixture {SAMPLE_PATH} absent")
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()
    rc = main([
        "--symbols", "NQ",
        "--replay", str(SAMPLE_PATH),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "50",
        "--heartbeat-sec", "0",
    ])
    assert rc == 0


def test_e2e_no_signal_handler_pytest_mode(tmp_path):
    """Verifie install_signal_handlers=True dans main() ne crash pas pytest.

    Le handler signal.signal raise ValueError si pas dans main thread,
    mais on catch dans BotMainLoop._install_signal_handlers (R5.2 ULTRATHINK).
    """
    if not SAMPLE_PATH.exists():
        pytest.skip(f"Fixture {SAMPLE_PATH} absent")
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()
    rc = main([
        "--symbols", "NQ",
        "--replay", str(SAMPLE_PATH),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "10",
        "--heartbeat-sec", "0",
    ])
    assert rc == 0


# ============================================================
# Wiring complet : context_builder + router + reconciler
# ============================================================


def test_e2e_build_loop_with_real_replay_stream(tmp_path):
    """build_loop construit BotMainLoop complet sans crash sur sample reel."""
    if not SAMPLE_PATH.exists():
        pytest.skip(f"Fixture {SAMPLE_PATH} absent")
    from bot4_v2.main.__main__ import build_loop, parse_args

    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()
    args = parse_args([
        "--symbols", "NQ",
        "--replay", str(SAMPLE_PATH),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "10",
        "--heartbeat-sec", "0",
    ])
    loop = build_loop(args)
    assert loop is not None
    assert loop.settings.symbols == ("NQ",)
    assert loop.settings.max_cycles == 10
    assert loop.processed_bars == 0  # avant run


# ============================================================
# Smoke test : run reel + verify counters
# ============================================================


def test_e2e_run_collects_metrics_dry_run(tmp_path):
    """run() dry-run sur 100 bars -> processed_bars cohérent."""
    if not SAMPLE_PATH.exists():
        pytest.skip(f"Fixture {SAMPLE_PATH} absent")
    from bot4_v2.main.__main__ import build_loop, parse_args

    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()
    args = parse_args([
        "--symbols", "NQ",
        "--replay", str(SAMPLE_PATH),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "100",
        "--heartbeat-sec", "0",
    ])
    loop = build_loop(args)
    loop.run()
    # Avec max_cycles=100 + 100 bars dispo, devrait traiter 100 bars
    assert loop.processed_bars == 100
    # total_dispatches >= 0 (peut etre 0 si aucun setup ne trigger).
    # Pour 2 detectors stricts sur 100 bars NQ reels = probablement 0 dispatch
    # (les filtres confluence/regime/PA sont severes).
    assert loop.total_dispatches >= 0


def test_e2e_real_bars_have_expected_features(tmp_path):
    """Sanity check : sample contient les features minimales attendues."""
    if not SAMPLE_PATH.exists():
        pytest.skip(f"Fixture {SAMPLE_PATH} absent")
    import json
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        first_line = f.readline()
    bar = json.loads(first_line)
    # Features critiques pour context_builder
    assert "sym" in bar or "symbol" in bar
    assert "high" in bar
    assert "low" in bar
    assert "close" in bar
    assert "atr" in bar
    assert "atr_14m" in bar
    # ts pour date extraction
    assert "ts_event" in bar or "ts" in bar


# ============================================================
# R8 ULTRATHINK : test crafted setup avec dispatch garanti
# ============================================================


def test_e2e_crafted_setup_produces_dispatch(tmp_path):
    """R8 review : prouver que pipeline produit reellement des fires/dispatches.

    Setup synthetique : 3 bars NQ avec Sweep_Reclaim_N1 detector qui DOIT fire.
    - Bar 1 : sweep_high triggered (sweep_high_lag1=1 prepare bar 2)
    - Bar 2 : reclaim down (close < high) avec sweep_high_lag1=1 -> fire SHORT
    - Bar 3 : entry touch -> ACTIVE (post-confirm logique)

    Goal : verifier que registry detecte fire ET router add instance.
    """
    import json

    sample_path = tmp_path / "crafted_setup.jsonl"
    base_ts = "2026-06-26T14:0"
    # Features minimales pour passer regime + narrative + sweep detection
    bars = [
        {
            "sym": "NQ", "ts_event": f"{base_ts}0:00+00:00",
            "high": 20020.0, "low": 19995.0, "close": 20005.0, "open": 20010.0,
            "atr": 10.0, "atr_14m": 40.0,
            "vix_level": 18.0, "vwap_d": 20000.0,
            "delta_bar": -150.0,
            "sweep_high_lag1": 1,  # sweep happened previous bar
        },
        {
            "sym": "NQ", "ts_event": f"{base_ts}1:00+00:00",
            "high": 20015.0, "low": 19990.0, "close": 19998.0, "open": 20005.0,
            "atr": 10.0, "atr_14m": 40.0,
            "vix_level": 18.0, "vwap_d": 20000.0,
            "delta_bar": -200.0,
            "sweep_high_lag1": 1,  # continue sweep flag bar suivante
        },
        {
            "sym": "NQ", "ts_event": f"{base_ts}2:00+00:00",
            "high": 20005.0, "low": 19985.0, "close": 19995.0, "open": 19998.0,
            "atr": 10.0, "atr_14m": 40.0,
            "vix_level": 18.0, "vwap_d": 20000.0,
            "delta_bar": -100.0,
            "sweep_high_lag1": 1,
        },
    ]
    sample_path.write_text(
        "\n".join(json.dumps(b) for b in bars) + "\n",
        encoding="utf-8",
    )
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()

    from bot4_v2.main.__main__ import build_loop, parse_args

    args = parse_args([
        "--symbols", "NQ",
        "--replay", str(sample_path),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "3",
        "--heartbeat-sec", "0",
    ])
    loop = build_loop(args)
    loop.run()
    # Au moins 1 fire emis sur 3 bars (Sweep_Reclaim_N1 SHORT setup garanti)
    nq_tracker = loop._router.trackers.get("NQ")
    # Soit instance creee (PENDING), soit fire dans audit metrics
    # Si pipeline correct : au moins 1 instance ou dispatched bracket
    fired_or_added = (
        (nq_tracker is not None and nq_tracker.n_instances >= 1)
        or loop.total_dispatches >= 1
    )
    assert fired_or_added, (
        f"Pipeline n'a pas detecte le setup crafted Sweep_Reclaim. "
        f"tracker.n_instances={nq_tracker.n_instances if nq_tracker else 0}, "
        f"total_dispatches={loop.total_dispatches}"
    )
