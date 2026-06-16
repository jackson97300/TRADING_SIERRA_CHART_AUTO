"""Tests IntermarketGate Bot MR - confirmation cross-instrument NQ via ES leader.

Methodologie Jackson 16/06/2026 :
  - NQ LONG requiert ES proche VWAP_W (ou autre niveau structurel) + bar verte
  - NQ SHORT requiert ES proche niveau + bar rouge
"""
from __future__ import annotations

import dataclasses

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.gates.intermarket import IntermarketGate


def _es_bar(**overrides) -> dict:
    """Bar ES synthetique pour tester gate. Defaults : leader loin de tous niveaux."""
    bar = {
        "ts": 1718524800000,
        "close": 5800.0,
        "bar_color_up": 0,
        "bar_color_dn": 0,
        "delta_bar": 0.0,
        # Tous niveaux structurels far (> 0.10% proximity threshold)
        "dist_vwap_w_pct": 0.50,
        "dist_vwap_d_pct": 0.30,
        "dist_vwap_d_sd1d_pct": 0.40,
        "dist_vwap_d_sd1u_pct": 0.40,
        "dist_vwap_d_sd2d_pct": 0.60,
        "dist_vwap_d_sd2u_pct": 0.60,
        "dist_cur_val_pct": 0.45,
        "dist_cur_vah_pct": 0.45,
        "dist_pdl_pct": 0.70,
        "dist_pdh_pct": 0.70,
        "dist_mq_put_pct": 0.80,
        "dist_mq_call_pct": 0.80,
        "dist_mq_hvl_pct": 0.55,
    }
    bar.update(overrides)
    return bar


# ============================================================
# TESTS principaux (cas Jackson 16/06)
# ============================================================

def test_confirm_long_es_at_vwap_w_bullish():
    """NQ LONG + ES proche VWAP_W (0.05%) + bar verte = ALLOWED.

    Cas typique Jackson : NQ LONG quand ES tient son VWAP weekly.
    """
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(
        dist_vwap_w_pct=0.05,   # Tres proche VWAP_W (sous 0.10% threshold)
        bar_color_up=1,         # Bar verte
        delta_bar=500.0,        # Delta bullish
    )
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is True
    assert "vwap_w" in verdict.reason
    assert "bullish" in verdict.reason
    assert verdict.leader_sym == "ES"
    assert verdict.level_matched == "vwap_w"


def test_confirm_long_es_no_level_proximity():
    """NQ LONG + ES loin de tous niveaux = REJECT (pas de confluence)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(bar_color_up=1, delta_bar=300.0)  # Tous niveaux > 0.10%
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is False
    assert verdict.reason == "leader_no_level_proximity"
    assert verdict.leader_sym == "ES"


def test_confirm_long_es_at_level_but_bearish_bias():
    """NQ LONG + ES proche VWAP_W mais bar ROUGE = REJECT (bias contraire)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(
        dist_vwap_w_pct=0.03,    # Proche VWAP_W
        bar_color_dn=1,          # Bar rouge
        delta_bar=-400.0,        # Delta bearish
    )
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is False
    assert "vwap_w" in verdict.reason
    assert "no_bullish_bias" in verdict.reason


def test_confirm_short_es_at_vah_bearish():
    """NQ SHORT + ES proche VAH + bar rouge = ALLOWED."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(
        dist_cur_vah_pct=-0.04,   # Tres proche VAH (signe ne compte pas, abs())
        bar_color_dn=1,           # Bar rouge
        delta_bar=-600.0,         # Delta bearish
    )
    verdict = gate.confirm("NQ", "SHORT", es_bar)
    assert verdict.allowed is True
    assert "vah" in verdict.reason
    assert "bearish" in verdict.reason


def test_confirm_leader_bar_none():
    """leader_bar=None = REJECT (fail-closed)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    verdict = gate.confirm("NQ", "LONG", None)
    assert verdict.allowed is False
    assert verdict.reason == "leader_bar_missing"
    assert verdict.leader_sym == "ES"


def test_gate_disabled():
    """Config gate disabled = always allow (gate transparent)."""
    cfg = BotMRConfig()
    cfg_off = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=False)
    gate = IntermarketGate(cfg_off)
    # Meme avec leader_bar=None
    verdict = gate.confirm("NQ", "LONG", None)
    assert verdict.allowed is True
    assert verdict.reason == "gate_disabled"


# ============================================================
# TESTS edge cases
# ============================================================

def test_no_leader_configured_passes_through():
    """ES n'a pas de leader -> gate transparent (allow toujours)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    verdict = gate.confirm("ES", "LONG", None)
    assert verdict.allowed is True
    assert "no_leader" in verdict.reason


def test_leader_for_helper():
    """leader_for() retourne le bon mapping + None si gate off."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    assert gate.leader_for("NQ") == "ES"
    assert gate.leader_for("ES") is None
    assert gate.leader_for("MGC") is None

    # Gate disabled : leader_for() retourne None pour tout
    cfg_off = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=False)
    gate_off = IntermarketGate(cfg_off)
    assert gate_off.leader_for("NQ") is None


def test_confirm_long_priority_vwap_w_over_vwap_d():
    """Si ES proche VWAP_W ET VWAP_D, on garde le PLUS proche (priorise correctement)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(
        dist_vwap_w_pct=0.08,    # Plus loin
        dist_vwap_d_pct=0.02,    # Plus proche -> doit etre matched
        bar_color_up=1,
        delta_bar=200.0,
    )
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is True
    # Le plus proche = vwap_d
    assert verdict.level_matched == "vwap_d"


def test_confirm_long_only_delta_bullish_no_color():
    """Bar sans bar_color_up=1 mais delta_bar > 0 suffit pour bullish bias."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(
        dist_vwap_w_pct=0.05,
        bar_color_up=0,        # Pas marquee verte (doji par ex)
        bar_color_dn=0,
        delta_bar=750.0,       # Mais delta bullish fort
    )
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is True
    assert "bullish" in verdict.reason


def test_confirm_long_delta_zero_no_color_reject():
    """Bar neutre (color=0/0 + delta=0) = REJECT pour LONG (pas de bullish bias)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    es_bar = _es_bar(
        dist_vwap_w_pct=0.05,
        bar_color_up=0,
        bar_color_dn=0,
        delta_bar=0.0,
    )
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is False
    assert "no_bullish_bias" in verdict.reason


def test_confirm_missing_dist_columns_far_safe():
    """Si toutes les colonnes dist_* sont None -> leader_no_level_proximity (pas de crash)."""
    cfg = BotMRConfig()
    cfg = dataclasses.replace(cfg, INTERMARKET_GATE_ENABLED=True)
    gate = IntermarketGate(cfg)
    # Bar avec aucune colonne dist_* (None partout)
    es_bar = {
        "ts": 1718524800000,
        "close": 5800.0,
        "bar_color_up": 1,
        "delta_bar": 500.0,
    }
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is False
    assert verdict.reason == "leader_no_level_proximity"


def test_confirm_custom_proximity_threshold():
    """Configurer proximity a 0.30% : niveaux jusqu'a 0.30% acceptes."""
    cfg = BotMRConfig()
    cfg_wide = dataclasses.replace(
        cfg, INTERMARKET_GATE_ENABLED=True, INTERMARKET_LEVEL_PROXIMITY_PCT=0.30,
    )
    gate = IntermarketGate(cfg_wide)
    es_bar = _es_bar(
        dist_vwap_w_pct=0.25,    # Hors 0.10% defaut, mais dans 0.30%
        bar_color_up=1,
        delta_bar=300.0,
    )
    verdict = gate.confirm("NQ", "LONG", es_bar)
    assert verdict.allowed is True
    assert "vwap_w" in verdict.reason
