"""Tests bot4_v2/observability/calibration_persistence."""
from __future__ import annotations

import json
import logging
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from bot4_v2.observability.calibration_persistence import (
    MAX_AGE_DAYS,
    N_MIN_TRADES,
    Calibration,
    CalibrationError,
    CalibrationMetadata,
    list_calibrations,
    load_calibration,
    save_calibration,
)


class _FakeModel:
    """Mock isotonic regression : retourne une P(win) fixe."""

    def __init__(self, p_win: float = 0.65):
        self.p_win = p_win

    def predict(self, score: float) -> float:
        return self.p_win

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FakeModel) and self.p_win == other.p_win


def _make_metadata(
    *,
    n_trades: int = 150,
    fit_ts: str | None = None,
    dsr: float = 0.96,
    pf: float = 1.5,
) -> CalibrationMetadata:
    if fit_ts is None:
        fit_ts = datetime.now(timezone.utc).isoformat()
    return CalibrationMetadata(
        scenario_name="Bearish_Rejection",
        symbol="NQ",
        regime="CALM_RANGE",
        n_trades=n_trades,
        fit_ts=fit_ts,
        pf=pf,
        wr=0.55,
        sharpe=1.5,
        dsr=dsr,
        method="isotonic",
        notes="test fixture",
    )


# ============================================================
# CalibrationMetadata serialization
# ============================================================

def test_metadata_to_dict_roundtrip():
    meta = _make_metadata()
    d = meta.to_dict()
    meta2 = CalibrationMetadata.from_dict(d)
    assert meta2 == meta


def test_metadata_from_dict_missing_keys_raises():
    with pytest.raises(KeyError):
        CalibrationMetadata.from_dict({"scenario_name": "X"})  # missing rest


def test_metadata_from_dict_bad_types_raises():
    bad = {
        "scenario_name": "X",
        "symbol": "NQ",
        "regime": "CALM",
        "n_trades": "not_int",
        "fit_ts": "2026-06-25T00:00:00Z",
        "pf": 1.0,
        "wr": 0.5,
        "sharpe": 1.0,
        "dsr": 0.95,
        "method": "isotonic",
    }
    with pytest.raises((ValueError, TypeError)):
        CalibrationMetadata.from_dict(bad)


def test_metadata_frozen_immutable():
    """R5 review : assertion stricte FrozenInstanceError (pas Exception generique)."""
    meta = _make_metadata()
    with pytest.raises(FrozenInstanceError):
        meta.scenario_name = "Other"  # type: ignore


# ============================================================
# save_calibration
# ============================================================

def test_save_calibration_writes_files(tmp_path):
    meta = _make_metadata(n_trades=150)
    model = _FakeModel(0.62)
    meta_path, model_path = save_calibration(tmp_path, meta, model)
    assert meta_path.exists()
    assert model_path.exists()
    assert meta_path.suffix == ".json"
    assert model_path.suffix == ".pkl"


def test_save_calibration_refuses_small_sample(tmp_path):
    """Garde-fou Lopez : refuse n_trades < N_MIN_TRADES sans force=True."""
    meta = _make_metadata(n_trades=50)  # < 100
    model = _FakeModel()
    with pytest.raises(CalibrationError) as exc_info:
        save_calibration(tmp_path, meta, model)
    assert "N_MIN_TRADES" in str(exc_info.value)


def test_save_calibration_accepts_small_sample_with_force(tmp_path):
    """force=True bypass garde-fou (TESTS ONLY)."""
    meta = _make_metadata(n_trades=10)
    model = _FakeModel()
    meta_path, model_path = save_calibration(tmp_path, meta, model, force=True)
    assert meta_path.exists()
    assert model_path.exists()


def test_save_calibration_creates_parent_dir(tmp_path):
    """Si base_dir n'existe pas, doit etre cree."""
    base = tmp_path / "nested" / "calibrations"
    assert not base.exists()
    meta = _make_metadata()
    save_calibration(base, meta, _FakeModel())
    assert base.exists()


def test_save_calibration_filename_key_format(tmp_path):
    meta = _make_metadata()  # NQ, Bearish_Rejection, CALM_RANGE
    meta_path, model_path = save_calibration(tmp_path, meta, _FakeModel())
    assert meta_path.name == "NQ_Bearish_Rejection_CALM_RANGE.json"
    assert model_path.name == "NQ_Bearish_Rejection_CALM_RANGE.pkl"


# ============================================================
# load_calibration
# ============================================================

def test_load_calibration_roundtrip(tmp_path):
    meta = _make_metadata()
    model = _FakeModel(0.72)
    save_calibration(tmp_path, meta, model)
    cal = load_calibration(tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE")
    assert isinstance(cal, Calibration)
    assert cal.metadata == meta
    assert cal.model == model
    # Predict callable apres load
    assert cal.model.predict(50.0) == 0.72


def test_load_calibration_metadata_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_calibration(tmp_path, "NQ", "Inexistant", "CALM_RANGE")


def test_load_calibration_model_missing(tmp_path):
    """Metadata existe mais pickle manquant."""
    meta = _make_metadata()
    save_calibration(tmp_path, meta, _FakeModel())
    # Supprime juste le pickle
    (tmp_path / "NQ_Bearish_Rejection_CALM_RANGE.pkl").unlink()
    with pytest.raises(FileNotFoundError):
        load_calibration(tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE")


def test_load_calibration_metadata_corrupt_json(tmp_path):
    bad = tmp_path / "NQ_Bad_CALM_RANGE.json"
    bad.write_text("not valid json {", encoding="utf-8")
    # Cree fake model file pour eviter FileNotFoundError du model
    (tmp_path / "NQ_Bad_CALM_RANGE.pkl").write_bytes(b"x")
    with pytest.raises(CalibrationError) as exc_info:
        load_calibration(tmp_path, "NQ", "Bad", "CALM_RANGE")
    assert "corrompu" in str(exc_info.value).lower()


def test_load_calibration_metadata_invalid_structure(tmp_path):
    bad = tmp_path / "NQ_Bad_CALM_RANGE.json"
    bad.write_text(json.dumps({"only_one_key": "val"}), encoding="utf-8")
    (tmp_path / "NQ_Bad_CALM_RANGE.pkl").write_bytes(b"x")
    with pytest.raises(CalibrationError) as exc_info:
        load_calibration(tmp_path, "NQ", "Bad", "CALM_RANGE")
    assert "invalide" in str(exc_info.value).lower()


def test_load_calibration_pickle_corrupt(tmp_path):
    meta = _make_metadata()
    save_calibration(tmp_path, meta, _FakeModel())
    # Corrupt pickle
    (tmp_path / "NQ_Bearish_Rejection_CALM_RANGE.pkl").write_bytes(b"not a pickle")
    with pytest.raises(CalibrationError) as exc_info:
        load_calibration(tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE")
    assert "corrompu" in str(exc_info.value).lower()


def test_load_calibration_age_too_old(tmp_path):
    """Garde-fou age : refuse si > max_age_days."""
    old_ts = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS + 5)).isoformat()
    meta = _make_metadata(fit_ts=old_ts)
    save_calibration(tmp_path, meta, _FakeModel())
    with pytest.raises(CalibrationError) as exc_info:
        load_calibration(tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE")
    assert "stale" in str(exc_info.value).lower()


def test_load_calibration_custom_max_age_days(tmp_path):
    """max_age_days parameter permet personnalisation."""
    age = 5  # plus jeune que default 30j
    ts = (datetime.now(timezone.utc) - timedelta(days=age + 1)).isoformat()
    meta = _make_metadata(fit_ts=ts)
    save_calibration(tmp_path, meta, _FakeModel())
    # avec max_age_days=age (5), 5+1 > 5 -> CalibrationError
    with pytest.raises(CalibrationError):
        load_calibration(
            tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE",
            max_age_days=age,
        )
    # avec max_age_days=age+10 (15), 5+1 < 15 -> OK
    cal = load_calibration(
        tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE",
        max_age_days=age + 10,
    )
    assert isinstance(cal, Calibration)


def test_load_calibration_fit_ts_with_z_suffix(tmp_path):
    """Verifie support fit_ts ISO 8601 avec suffixe 'Z' (UTC)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = _make_metadata(fit_ts=ts)
    save_calibration(tmp_path, meta, _FakeModel())
    cal = load_calibration(tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE")
    assert cal.metadata.fit_ts == ts


# ============================================================
# list_calibrations
# ============================================================

def test_list_calibrations_empty_dir(tmp_path):
    assert list_calibrations(tmp_path) == []


def test_list_calibrations_nonexistent_dir(tmp_path):
    assert list_calibrations(tmp_path / "does_not_exist") == []


def test_list_calibrations_multiple_sorted_desc(tmp_path):
    """Plusieurs calibrations doivent etre triees par fit_ts descending."""
    ts_old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    ts_new = datetime.now(timezone.utc).isoformat()
    meta_old = CalibrationMetadata(
        scenario_name="Old", symbol="NQ", regime="CALM_RANGE",
        n_trades=120, fit_ts=ts_old, pf=1.3, wr=0.5, sharpe=1.0, dsr=0.95,
        method="isotonic",
    )
    meta_new = CalibrationMetadata(
        scenario_name="New", symbol="NQ", regime="CALM_RANGE",
        n_trades=130, fit_ts=ts_new, pf=1.4, wr=0.52, sharpe=1.1, dsr=0.96,
        method="isotonic",
    )
    save_calibration(tmp_path, meta_old, _FakeModel())
    save_calibration(tmp_path, meta_new, _FakeModel())
    listed = list_calibrations(tmp_path)
    assert len(listed) == 2
    assert listed[0].scenario_name == "New"
    assert listed[1].scenario_name == "Old"


def test_list_calibrations_skips_corrupt_json(tmp_path, caplog):
    """Fichier JSON corrompu -> skip + warning (pas crash)."""
    # 1 valide
    meta_valid = _make_metadata()
    save_calibration(tmp_path, meta_valid, _FakeModel())
    # 1 corrompu
    (tmp_path / "NQ_Corrupt_CALM_RANGE.json").write_text("{not json", encoding="utf-8")
    listed = list_calibrations(tmp_path)
    assert len(listed) == 1
    assert listed[0].scenario_name == "Bearish_Rejection"


# ============================================================
# Constants
# ============================================================

def test_n_min_trades_lopez_compliant():
    """N_MIN_TRADES doit etre >= 100 (Lopez AFML)."""
    assert N_MIN_TRADES >= 100


def test_max_age_days_reasonable():
    """MAX_AGE_DAYS doit etre raisonnable (anti-stale)."""
    assert 7 <= MAX_AGE_DAYS <= 90


# ============================================================
# R1 R3 R4 review : tests pour patches appliques
# ============================================================

def test_save_calibration_force_logs_warning(tmp_path, caplog):
    """R1 review : force=True bypass doit emit warning audit (pas silent)."""
    meta = _make_metadata(n_trades=10)
    with caplog.at_level(
        logging.WARNING, logger="bot4_v2.observability.calibration_persistence"
    ):
        save_calibration(tmp_path, meta, _FakeModel(), force=True)
    assert any("FORCE bypass" in r.message for r in caplog.records)


def test_load_calibration_fit_ts_in_future_raises(tmp_path):
    """R4 review : fit_ts dans le futur (clock skew) -> CalibrationError explicit."""
    future_ts = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    meta = _make_metadata(fit_ts=future_ts)
    save_calibration(tmp_path, meta, _FakeModel())
    with pytest.raises(CalibrationError) as exc_info:
        load_calibration(tmp_path, "NQ", "Bearish_Rejection", "CALM_RANGE")
    assert "future" in str(exc_info.value).lower()


def test_save_calibration_rejects_path_traversal_scenario(tmp_path):
    """R3 review : path traversal via scenario_name doit etre bloque."""
    meta = CalibrationMetadata(
        scenario_name="../../etc/passwd",  # tentative path traversal
        symbol="NQ",
        regime="CALM_RANGE",
        n_trades=150,
        fit_ts=datetime.now(timezone.utc).isoformat(),
        pf=1.5, wr=0.55, sharpe=1.5, dsr=0.96,
        method="isotonic",
    )
    with pytest.raises(CalibrationError) as exc_info:
        save_calibration(tmp_path, meta, _FakeModel())
    assert "path safety" in str(exc_info.value).lower()


def test_save_calibration_rejects_path_traversal_symbol(tmp_path):
    """R3 review : symbol avec slash/dot doit etre bloque."""
    meta = CalibrationMetadata(
        scenario_name="ValidScenario",
        symbol="NQ/../bad",
        regime="CALM_RANGE",
        n_trades=150,
        fit_ts=datetime.now(timezone.utc).isoformat(),
        pf=1.5, wr=0.55, sharpe=1.5, dsr=0.96,
        method="isotonic",
    )
    with pytest.raises(CalibrationError):
        save_calibration(tmp_path, meta, _FakeModel())


def test_save_calibration_rejects_path_traversal_regime(tmp_path):
    """R3 review : regime avec espace/null doit etre bloque."""
    meta = CalibrationMetadata(
        scenario_name="ValidScenario",
        symbol="NQ",
        regime="BAD REGIME",  # espace interdit
        n_trades=150,
        fit_ts=datetime.now(timezone.utc).isoformat(),
        pf=1.5, wr=0.55, sharpe=1.5, dsr=0.96,
        method="isotonic",
    )
    with pytest.raises(CalibrationError):
        save_calibration(tmp_path, meta, _FakeModel())
