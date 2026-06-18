"""Tests CONFLUENCE NIVEAU MENTHORQ Bot MR (anti entry isolee 18/06/2026).

Calibre carnage 18/06 : 4 LONGs ES dans le vide entre 2 niveaux structurels
(7548, 7554, 7558, 7533) sans confluence = -$1025 broker. Un trader pro entre
uniquement quand 2-3 niveaux MenthorQ/GEX/VWAP SD clusterisent dans <10t.

Implementation : consomme les `dist_*_pct` et `dist_*_ticks` deja pre-calcules
par le DMP/enricher cote Sierra (verifie sur sierra_enriched du 15/06).
"""
from __future__ import annotations

import datetime as _dt

import pytest

from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import (
    MQ_LEVEL_DIST_FIELDS,
    SignalEngine,
)


# ==========================================================================
# Helpers (alignes test_signal_engine.py / test_no_reentry.py)
# ==========================================================================


def _ts_now_us() -> int:
    """ts ms en plein milieu RTH US (15:00 UTC = 11:00 ET)."""
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=15, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _make_bar_es_long(close_price: float = 5800.0, **overrides) -> dict:
    """Bar ES synthetique RTH avec extension SD3 down -> setup LONG.

    Par defaut AUCUN niveau MQ proche : tous les `dist_*` sont mis a une
    valeur loin du seuil pour que le filtre confluence trouve 0 level proche.
    On peut override via kwargs pour injecter des niveaux proches.
    """
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": close_price,
        "bar_high": close_price + 1.0,
        "bar_low": close_price - 1.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": -0.10,
        "dist_vwap_d_sd3u_pct": -0.20,
        "vwap_slope_30": 0.05,  # trend_align_es LONG
        # Defaults : tous niveaux LOIN (au-dela radius_ticks=10 ES, ~5% prix)
        "dist_mq_hvl_pct": 5.0,
        "dist_mq_hvl_0dte_pct": 5.0,
        "dist_mq_call_pct": 5.0,
        "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0,
        "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 5.0,
        "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0,
        "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0,
        "dist_vwap_w_sd1d_pct": -3.0,
        # Phase 4 18/06 defaults neutres pour 3 filtres orderflow/anti-top/momentum
        "delta_bar": 50.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
    }
    bar.update(overrides)
    return bar


# ==========================================================================
# 1. Config (defaults + env override + helper)
# ==========================================================================


def test_default_confluence_thresholds():
    """Defaults RECALIBRES 18/06 : min=1 level, radius ES=15, NQ=50, MGC=20.

    Avant recal : min=2/radius=10/30 -> stub backtest=0 trades (trop strict).
    Phase 1 permissif : 1 level / 15-50t. NQ bloque 100% car niveaux MQ typiques
    >150t du prix (echelle prix NQ 1.6x ES).
    Phase 2 18/06 (calibre live) : 100t ES / 250t NQ = ~0.5% du prix.
    """
    cfg = BotMRConfig()
    # Phase 2 18/06 : DISABLED par defaut (asymetrie echelle NQ/ES non resolue
    # avec radius en ticks). Activable via BOTMR_CONFLUENCE_FILTER_ENABLED=1.
    assert cfg.CONFLUENCE_FILTER_ENABLED is False
    assert cfg.CONFLUENCE_MIN_LEVELS == 1
    assert cfg.CONFLUENCE_RADIUS_TICKS_ES == 100
    assert cfg.CONFLUENCE_RADIUS_TICKS_NQ == 250
    assert cfg.CONFLUENCE_RADIUS_TICKS_MGC == 20


def test_env_override_confluence(monkeypatch):
    """Env vars BOTMR_* override les defaults."""
    monkeypatch.setenv("BOTMR_CONFLUENCE_FILTER_ENABLED", "false")
    monkeypatch.setenv("BOTMR_CONFLUENCE_MIN_LEVELS", "3")
    monkeypatch.setenv("BOTMR_CONFLUENCE_RADIUS_ES", "15")
    monkeypatch.setenv("BOTMR_CONFLUENCE_RADIUS_NQ", "40")
    monkeypatch.setenv("BOTMR_CONFLUENCE_RADIUS_MGC", "25")
    cfg = BotMRConfig.from_env()
    assert cfg.CONFLUENCE_FILTER_ENABLED is False
    assert cfg.CONFLUENCE_MIN_LEVELS == 3
    assert cfg.CONFLUENCE_RADIUS_TICKS_ES == 15
    assert cfg.CONFLUENCE_RADIUS_TICKS_NQ == 40
    assert cfg.CONFLUENCE_RADIUS_TICKS_MGC == 25


def test_confluence_radius_helper():
    """Helper cfg.confluence_radius_ticks(symbol) retourne le seuil correct (recal Phase 2 18/06)."""
    cfg = BotMRConfig()
    assert cfg.confluence_radius_ticks("ES") == 100
    assert cfg.confluence_radius_ticks("es") == 100  # case insensitive
    assert cfg.confluence_radius_ticks("NQ") == 250
    assert cfg.confluence_radius_ticks("MGC") == 20
    assert cfg.confluence_radius_ticks("ZZ") == 100  # default = ES


def test_mq_level_dist_fields_exhaustive():
    """La liste MQ_LEVEL_DIST_FIELDS contient les fields de sierra_enriched.

    Verifie qu'on a au moins les MenthorQ (HVL/Call/Put jour+0DTE), les GEX
    nearest, le 1d range, et les VWAP SD bands. Pas de duplication.
    """
    fields = [f for f, _u in MQ_LEVEL_DIST_FIELDS]
    units = {f: u for f, u in MQ_LEVEL_DIST_FIELDS}
    # Pas de duplication
    assert len(fields) == len(set(fields))
    # Au moins ces familles
    assert "dist_mq_hvl_pct" in fields
    assert "dist_mq_hvl_0dte_pct" in fields
    assert "dist_mq_call_pct" in fields
    assert "dist_mq_put_pct" in fields
    assert "dist_gex_nearest_up_pct" in fields
    assert "dist_1d_max_ticks" in fields
    # Units coherentes
    assert units["dist_mq_hvl_pct"] == "pct"
    assert units["dist_1d_max_ticks"] == "ticks"


# ==========================================================================
# 2. SignalEngine - logique de comptage des niveaux proches
# ==========================================================================


def test_signal_engine_block_isolated_entry(tmp_path):
    """Entry candidate sans aucun niveau proche -> BLOCK NO_CONFLUENCE.

    Format actuel (Phase 2 recal live 18/06) : "NO_CONFLUENCE:0<1_levels_in_100t".
    Test forces radius=15 pour conserver le scenario "tous loin".
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True, CONFLUENCE_RADIUS_TICKS_ES=15)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(close_price=5800.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False, f"Doit etre bloque mais skip_reason={sig.skip_reason}"
    assert "NO_CONFLUENCE" in sig.skip_reason
    assert sig.direction == "LONG"
    assert "0<1" in sig.skip_reason
    assert "15t" in sig.skip_reason


def test_signal_engine_allow_confluent_entry(tmp_path):
    """Entry avec >=2 niveaux dans 10t (ES) -> pas de block NO_CONFLUENCE.

    Strategie : on injecte 2 niveaux a moins de 10t = 2.5 pts (ES tick=0.25).
    En pct sur close=5800 : 2.5/5800*100 = 0.043% -> dist_pct=0.04 OK.
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(
        close_price=5800.0,
        # 2 niveaux MQ tres proches (< 10t)
        dist_mq_hvl_0dte_pct=0.02,  # = ~1.16 pt = ~4.6 ticks
        dist_gex_nearest_up_pct=0.03,  # = ~1.74 pt = ~7 ticks
    )
    sig = eng.evaluate(bar)
    # Pas bloque par NO_CONFLUENCE (autres gates peuvent bloquer, c'est OK)
    assert "NO_CONFLUENCE" not in (sig.skip_reason or ""), (
        f"skip_reason={sig.skip_reason}"
    )


def test_signal_engine_one_level_blocks(tmp_path):
    """1 seul niveau proche (min=2 forced) -> BLOCK avec count=1.

    Apres recal 18/06, default min=1 donc 1 level PASSE. Pour tester ce cas,
    on force CONFLUENCE_MIN_LEVELS=2 (avant recal) pour valider que le filter
    fonctionne quand min>=2.
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True, CONFLUENCE_MIN_LEVELS=2)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(
        close_price=5800.0,
        dist_mq_hvl_0dte_pct=0.02,  # 1 seul niveau proche
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "NO_CONFLUENCE" in sig.skip_reason
    assert "1<2" in sig.skip_reason


def test_signal_engine_disabled_bypass(tmp_path):
    """CONFLUENCE_FILTER_ENABLED=False -> jamais de block NO_CONFLUENCE."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=False)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(close_price=5800.0)  # 0 level proche
    sig = eng.evaluate(bar)
    assert "NO_CONFLUENCE" not in (sig.skip_reason or "")


def test_signal_engine_min_levels_custom(tmp_path):
    """Avec CONFLUENCE_MIN_LEVELS=3, 2 niveaux proches -> toujours block."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True, CONFLUENCE_MIN_LEVELS=3)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(
        close_price=5800.0,
        dist_mq_hvl_0dte_pct=0.02,
        dist_gex_nearest_up_pct=0.03,
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "NO_CONFLUENCE" in sig.skip_reason
    assert "2<3" in sig.skip_reason


# ==========================================================================
# 3. Radius per symbol (ES=10, NQ=30, MGC=20)
# ==========================================================================


def test_radius_per_symbol_nq_wider(tmp_path):
    """NQ utilise radius > ES (echelle prix 1.6x). Test force radius bas pour scenario.

    Phase 2 18/06 : defaults 100t ES / 250t NQ. Pour ce test, on force radius
    plus bas (15t ES, 50t NQ) pour verifier la logique de comparaison.
    """
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True, CONFLUENCE_RADIUS_TICKS_ES=15, CONFLUENCE_RADIUS_TICKS_NQ=50)
    # Test ES : 20t > radius_es=15t -> BLOCK (0 levels in radius)
    store_es = PositionStore(path=tmp_path / "state_es.json")
    eng_es = SignalEngine("ES", cfg, store=store_es)
    bar_es = _make_bar_es_long(
        close_price=5800.0,
        dist_mq_hvl_0dte_pct=0.086,  # 5 pts = 20 ticks @ 5800
        dist_gex_nearest_up_pct=0.086,
    )
    sig_es = eng_es.evaluate(bar_es)
    # Tous niveaux a 20t : aucun n'est dans rayon 15t ES -> 0<1 BLOCK
    assert sig_es.tradable is False
    assert "NO_CONFLUENCE" in sig_es.skip_reason
    assert "0<1" in sig_es.skip_reason

    # Test NQ : meme setup mais radius NQ=30t -> les 2 levels passent
    store_nq = PositionStore(path=tmp_path / "state_nq.json")
    # NQ utilise contrarian_nq mode : LONG si slope<0
    eng_nq = SignalEngine("NQ", cfg, store=store_nq)
    bar_nq = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 20000.0,
        "bar_high": 20001.0,
        "bar_low": 19999.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": -0.10,
        "dist_vwap_d_sd3u_pct": -0.20,
        "vwap_slope_30": -0.05,  # NQ contrarian : LONG si slope<0
        # Defaults loin sauf 2 proches a 20t (~5 pts @ 20000)
        "dist_mq_hvl_pct": 5.0,
        "dist_mq_hvl_0dte_pct": 0.025,  # 5 pts = 20 ticks @ 20000
        "dist_mq_call_pct": 5.0,
        "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0,
        "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 0.025,  # 20 ticks @ 20000
        "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0,
        "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0,
        "dist_vwap_w_sd1d_pct": -3.0,
    }
    sig_nq = eng_nq.evaluate(bar_nq)
    # NQ : 20t <= radius_nq=30t -> 2 niveaux proches, pas de NO_CONFLUENCE
    assert "NO_CONFLUENCE" not in (sig_nq.skip_reason or "")


# ==========================================================================
# 4. Robustness : champs absents / None / NaN / string
# ==========================================================================


def test_signal_engine_bypass_when_no_fields_present(tmp_path):
    """Si AUCUN field dist_* present (bar test ou pre-enrichment) -> bypass filtre.

    Cette semantique preserve la non-regression sur tests legacy qui n'injectent
    pas les distances MenthorQ. Au 1er bar live enrichi, le filtre s'active.
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True)
    eng = SignalEngine("ES", cfg, store=store)
    # On strip TOUS les dist_mq_* / gex / 1d / vwap_sd1d
    bar = _make_bar_es_long(close_price=5800.0)
    for f, _u in MQ_LEVEL_DIST_FIELDS:
        bar.pop(f, None)
    sig = eng.evaluate(bar)
    # AUCUN field present -> bypass -> pas de NO_CONFLUENCE
    assert "NO_CONFLUENCE" not in (sig.skip_reason or "")


def test_signal_engine_active_when_one_field_present(tmp_path):
    """Des qu'au moins 1 field dist_* est present, le filtre s'active.

    Garde-fou : un seul niveau loin -> 0 dans rayon -> BLOCK NO_CONFLUENCE.
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True)
    eng = SignalEngine("ES", cfg, store=store)
    # On strip TOUS sauf un, et on met ce field LOIN
    bar = _make_bar_es_long(close_price=5800.0)
    for f, _u in MQ_LEVEL_DIST_FIELDS:
        bar.pop(f, None)
    bar["dist_mq_hvl_pct"] = 5.0  # ~290 pts = 1160 ticks, LOIN du radius 15
    sig = eng.evaluate(bar)
    # 1 field present mais 0 dans rayon -> BLOCK (apres recal 18/06 min=1)
    assert sig.tradable is False
    assert "NO_CONFLUENCE" in sig.skip_reason
    assert "0<1" in sig.skip_reason


def test_signal_engine_handles_none_values(tmp_path):
    """Champs dist_* = None : pas de crash, ignore (None != field present).

    Les defaults loin restent presents (dist_mq_call_pct, etc.), donc le filtre
    s'active normalement et bloque (0 dans rayon vu defaults a 5%).
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(
        close_price=5800.0,
        dist_mq_hvl_pct=None,  # remplace les 2 fields par None
        dist_mq_hvl_0dte_pct=None,
    )
    sig = eng.evaluate(bar)
    # Pas de crash. 10+ fields encore presents (defaults loin) -> filtre actif
    # -> 0 niveau dans rayon -> BLOCK
    assert sig.tradable is False
    assert "NO_CONFLUENCE" in sig.skip_reason


def test_signal_engine_handles_invalid_string(tmp_path):
    """Champs dist_* = string non-numerique : pas de crash, ignore."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(
        close_price=5800.0,
        dist_mq_hvl_pct="invalid",
        dist_mq_call_pct="N/A",
    )
    sig = eng.evaluate(bar)
    # Pas de crash. Autres fields default presents (10 fields loin) -> filtre actif -> BLOCK.
    assert "NO_CONFLUENCE" in sig.skip_reason


def test_signal_engine_handles_invalid_close(tmp_path):
    """close=0 ou negatif : confluence check skip (autre gate prend le relais)."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig(CONFLUENCE_FILTER_ENABLED=True)
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(close_price=5800.0)
    bar["close"] = 0.0  # force close invalide
    sig = eng.evaluate(bar)
    # Confluence skip silencieusement (candidate_price <= 0), donc le check
    # NO_EXTENSION ou INVALID_CLOSE_PRICE peut prendre le relais.
    # Verifie juste pas de crash.
    assert sig.tradable is False
