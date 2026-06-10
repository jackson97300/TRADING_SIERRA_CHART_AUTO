"""bot3_reform_variants.py — Definitions V1-V10 pour Bot 3 reform.

Jackson 24/05/2026 : Bot 3 MP casse (PF 0.98 sur 137 vrais trades, 4 derniers
jours actifs -$1546). 10 variantes a tester sur 15/12/2025 -> 21/05/2026 :

  V1 : purge 9 niveaux DROP (baseline reformee)
  V2 : V1 + filtre regime (TREND only, regime_actionable=1)
  V3 : V1 + V2 + footprint Dow (long_up_bar/long_dn_bar)
  V4 : V1 + symetrie SHORT (GEX_UP, MQ_CALL_0DTE, IB_HIGH)
  V5 : V1 + BN V4 density gate (n_color_up_cluster + n_long_up_cluster >= 3)
  V6 : V1 + BN V4 confluence gate (>=2 niveaux institutionnels proches)
  V7 : V1 + BN V4 edge zones gate (n_edge_buy_active >= 1)
  V8 : V1 + V5+V6+V7+V3 (BN V4 CONFLUENCE COMPLETE)
  V9 : INVERSION direction tous niveaux (test si Bot 3 vraiment a contre-sens)
  V10 : V1 + INVERSION (purge + inversion)

Format : dataclass pure, zero logique. Moteur consomme dans backtester.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import pandas as pd


# ════════════════════════════════════════════════════════════════════════
# LEVEL DEFINITIONS
# ════════════════════════════════════════════════════════════════════════

@dataclass
class LevelDef:
    """Un niveau institutionnel.

    name           : identifiant lisible (ex: "MQ_1D_MAX")
    tier           : 1=majeur, 2=moyen, 3=mineur
    dist_col       : colonne parquet de la distance signee en pourcentage
                     (positif = level au-dessus, negatif = en-dessous)
    threshold_pct  : seuil de contact (abs(dist_pct) <= threshold_pct)
    side_default   : LONG ou SHORT (sens normal du fade/bounce)
    family         : famille pour reporting (MQ / MP / VWAP / IB / GEX / CASH)
    """
    name: str
    tier: int
    dist_col: str
    threshold_pct: float
    side_default: str  # "LONG" ou "SHORT"
    family: str

    def __post_init__(self):
        assert self.side_default in ("LONG", "SHORT")
        assert self.tier in (1, 2, 3)
        assert self.threshold_pct > 0


# ─────────────────────────────────────────────────────────────────────────
# BASELINE V1 — purge des 9 niveaux DROP identifies par backtest 14 mois 03/05
# ─────────────────────────────────────────────────────────────────────────
#
# DROP (identifies par audit) : SINGLE_PRINT, OPEN_DRIVE, OPEN_REJECT, OPEN_TEST,
#                                PVAL, GEX_DN, VWAP_W_SD1D, ES entier (toutes
#                                strategies LONG ES = PF<1.0)
#
# Niveaux GARDES (V1 baseline) : MQ + MP cur + VWAP_D + GEX_UP + IB_HIGH

LEVELS_V1_LONG: List[LevelDef] = [
    # MenthorQ — niveaux options-driven
    LevelDef("MQ_1D_MIN",   tier=1, dist_col="dist_1d_min_ticks_pct",
             threshold_pct=0.02, side_default="LONG", family="MQ"),
    LevelDef("MQ_PUT",      tier=1, dist_col="dist_mq_put_pct",
             threshold_pct=0.02, side_default="LONG", family="MQ"),
    LevelDef("MQ_PUT_0DTE", tier=1, dist_col="dist_mq_put_0dte_pct",
             threshold_pct=0.02, side_default="LONG", family="MQ"),
    LevelDef("MQ_HVL",      tier=2, dist_col="dist_mq_hvl_pct",
             threshold_pct=0.02, side_default="LONG", family="MQ"),
    # Market Profile
    LevelDef("CUR_VAL",     tier=2, dist_col="dist_cur_val_pct",
             threshold_pct=0.02, side_default="LONG", family="MP"),
    LevelDef("CUR_VPOC",    tier=2, dist_col="dist_cur_vpoc_pct",
             threshold_pct=0.02, side_default="LONG", family="MP"),
    LevelDef("PREV_VAL",    tier=3, dist_col="dist_prev_val_pct",
             threshold_pct=0.02, side_default="LONG", family="MP"),
    # VWAP — daily seulement (W et M ont prouve weakness)
    LevelDef("PVWAP",       tier=2, dist_col="dist_pvwap_pct",
             threshold_pct=0.02, side_default="LONG", family="VWAP"),
    LevelDef("VWAP_D",      tier=2, dist_col="dist_vwap_d_pct",
             threshold_pct=0.02, side_default="LONG", family="VWAP"),
    # GEX support
    LevelDef("GEX_DN",      tier=2, dist_col="dist_gex_nearest_dn_pct",
             threshold_pct=0.02, side_default="LONG", family="GEX"),
    # Cash / Asia low (overnight)
    LevelDef("CASH_LOW",    tier=3, dist_col="dist_cash_low_pct",
             threshold_pct=0.02, side_default="LONG", family="CASH"),
    LevelDef("ASIA_LOW",    tier=3, dist_col="dist_asia_low_pct",
             threshold_pct=0.02, side_default="LONG", family="CASH"),
    # IB support
    LevelDef("IB_LOW",      tier=2, dist_col="dist_ib_low_pct",
             threshold_pct=0.02, side_default="LONG", family="IB"),
]

# ─────────────────────────────────────────────────────────────────────────
# V4 ADDITIF — symetrie SHORT (resistance institutionnelle)
# ─────────────────────────────────────────────────────────────────────────

LEVELS_V4_SHORT: List[LevelDef] = [
    LevelDef("MQ_1D_MAX",    tier=1, dist_col="dist_1d_max_ticks_pct",
             threshold_pct=0.02, side_default="SHORT", family="MQ"),
    LevelDef("MQ_CALL",      tier=1, dist_col="dist_mq_call_pct",
             threshold_pct=0.02, side_default="SHORT", family="MQ"),
    LevelDef("MQ_CALL_0DTE", tier=1, dist_col="dist_mq_call_0dte_pct",
             threshold_pct=0.02, side_default="SHORT", family="MQ"),
    LevelDef("CUR_VAH",      tier=2, dist_col="dist_cur_vah_pct",
             threshold_pct=0.02, side_default="SHORT", family="MP"),
    LevelDef("PREV_VAH",     tier=3, dist_col="dist_prev_vah_pct",
             threshold_pct=0.02, side_default="SHORT", family="MP"),
    LevelDef("GEX_UP",       tier=2, dist_col="dist_gex_nearest_up_pct",
             threshold_pct=0.02, side_default="SHORT", family="GEX"),
    LevelDef("IB_HIGH",      tier=2, dist_col="dist_ib_high_pct",
             threshold_pct=0.02, side_default="SHORT", family="IB"),
    LevelDef("CASH_HIGH",    tier=3, dist_col="dist_cash_high_pct",
             threshold_pct=0.02, side_default="SHORT", family="CASH"),
    LevelDef("ASIA_HIGH",    tier=3, dist_col="dist_asia_high_pct",
             threshold_pct=0.02, side_default="SHORT", family="CASH"),
]


# ════════════════════════════════════════════════════════════════════════
# ENTRY FILTERS (composables)
# ════════════════════════════════════════════════════════════════════════
#
# Un filter est une fonction (bar_row: pd.Series, side: str) -> bool
# Si elle retourne False, le trade est skippe (incremente skip_<filter>).
# Tous les filters d'une variante doivent passer (AND logique).

EntryFilter = Callable[[pd.Series, str], bool]


def _safe_get(row: pd.Series, col: str, default=None):
    if col not in row.index:
        return default
    v = row[col]
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except Exception:
        pass
    return v


def filter_news_veto(row: pd.Series, side: str) -> bool:
    """Skip si bar dans fenetre +/- 5 min autour news scheduled.

    Utilise mins_since_news et mins_to_next_news (deja dans parquet).
    FAIL-CLOSED : si valeur non castable / colonne absente, skip le trade
    (review code-reviewer 24/05 — cf gamma fail-closed CLAUDE.md).
    """
    since = _safe_get(row, "mins_since_news", default=None)
    to_next = _safe_get(row, "mins_to_next_news", default=None)
    if since is None or to_next is None:
        return False  # FAIL-CLOSED : si donnees news absentes, skip
    try:
        since = float(since)
        to_next = float(to_next)
    except (TypeError, ValueError):
        return False  # FAIL-CLOSED : valeur invalide = skip
    if 0 <= since <= 5:
        return False
    if 0 <= to_next <= 5:
        return False
    return True


def filter_regime_actionable(row: pd.Series, side: str) -> bool:
    """V2 — skip si regime non-actionable.

    Conditions :
      - regime_actionable == 1
      - regime_favor compatible avec side (LONG: NEUTRE/LONG ; SHORT: NEUTRE/SHORT)
    """
    actionable = _safe_get(row, "regime_actionable", default=0)
    favor = _safe_get(row, "regime_favor", default="NEUTRE")
    try:
        actionable = int(actionable)
    except (TypeError, ValueError):
        actionable = 0
    if actionable != 1:
        return False
    if side == "LONG" and favor == "SHORT":
        return False
    if side == "SHORT" and favor == "LONG":
        return False
    return True


def filter_footprint_dow(row: pd.Series, side: str) -> bool:
    """V3 — confirmation Dow Theory via footprint long_up_bar / long_dn_bar.

    LONG : long_up_bar == 1 (acheteur dominant sur la barre touch)
    SHORT : long_dn_bar == 1 (vendeur dominant)
    """
    if side == "LONG":
        v = _safe_get(row, "long_up_bar", default=0)
    else:
        v = _safe_get(row, "long_dn_bar", default=0)
    try:
        return int(v) == 1
    except (TypeError, ValueError):
        return False


def filter_bn_density(row: pd.Series, side: str) -> bool:
    """V5 — BN V4 density gate.

    LONG : n_color_up_zones_active + n_color_up_cluster_within_0_2pct >= 3
    SHORT : n_color_dn_zones_active + n_color_dn_cluster_within_0_2pct >= 3
    """
    if side == "LONG":
        a = _safe_get(row, "n_color_up_zones_active", default=0)
        b = _safe_get(row, "n_color_up_cluster_within_0_2pct", default=0)
    else:
        a = _safe_get(row, "n_color_dn_zones_active", default=0)
        b = _safe_get(row, "n_color_dn_cluster_within_0_2pct", default=0)
    try:
        return (int(a) + int(b)) >= 3
    except (TypeError, ValueError):
        return False


def filter_bn_confluence(row: pd.Series, side: str) -> bool:
    """V6 — BN V4 confluence gate.

    Au moins 2 niveaux institutionnels du meme cote dans 0.15% du prix.
    Approximation via distances pre-calculees : compte combien de dist_*_pct
    sont en abs <= 0.15.
    """
    if side == "LONG":
        cand_cols = [
            "dist_mq_put_pct", "dist_mq_put_0dte_pct", "dist_mq_hvl_pct",
            "dist_cur_val_pct", "dist_cur_vpoc_pct", "dist_prev_val_pct",
            "dist_pvwap_pct", "dist_vwap_d_pct",
            "dist_gex_nearest_dn_pct", "dist_ib_low_pct",
            "dist_1d_min_ticks_pct",
        ]
    else:
        cand_cols = [
            "dist_mq_call_pct", "dist_mq_call_0dte_pct",
            "dist_cur_vah_pct", "dist_prev_vah_pct",
            "dist_gex_nearest_up_pct", "dist_ib_high_pct",
            "dist_1d_max_ticks_pct",
        ]
    n = 0
    for c in cand_cols:
        v = _safe_get(row, c, default=None)
        if v is None:
            continue
        try:
            if abs(float(v)) <= 0.15:
                n += 1
                if n >= 2:
                    return True
        except (TypeError, ValueError):
            continue
    return False


def filter_bn_edge(row: pd.Series, side: str) -> bool:
    """V7 — BN V4 edge zones gate."""
    if side == "LONG":
        v = _safe_get(row, "n_edge_buy_active", default=0)
    else:
        v = _safe_get(row, "n_edge_sell_active", default=0)
    try:
        return int(v) >= 1
    except (TypeError, ValueError):
        return False


def filter_regime_no_trend(row: pd.Series, side: str) -> bool:
    """OPTION 2 — Skip si regime_mode == 'TREND'.

    Hypothese : le fade niveau marche en RANGE/NORMAL mais casse en TREND
    (audits 22-23/05 + V9 inversion PF 0.86 prouve mean reversion intra-trend
    rate des 2 cotes). Filter elimine la zone toxique.
    """
    mode = _safe_get(row, "regime_mode", default="NORMAL")
    if mode is None:
        return False  # fail-closed
    return str(mode).upper() != "TREND"


def filter_regime_trend_only(row: pd.Series, side: str) -> bool:
    """OPTION 1 — Skip si regime_mode != 'TREND'.

    Hypothese : continuation post-retest a son edge en TREND uniquement
    (Wyckoff phase E / Dalton breakout failure).
    """
    mode = _safe_get(row, "regime_mode", default="NORMAL")
    if mode is None:
        return False
    return str(mode).upper() == "TREND"


# ════════════════════════════════════════════════════════════════════════
# VARIANT DEFINITIONS
# ════════════════════════════════════════════════════════════════════════

@dataclass
class VariantConfig:
    """Configuration d'une variante de backtest.

    name              : identifiant (V1..V10 OU OPT2_*)
    description       : 1 ligne explication
    levels            : liste des LevelDef actifs
    filters           : liste de EntryFilter (AND logique, news_veto toujours
                        ajoute en interne)
    invert_direction  : si True, inverse side_default de chaque level
    sl_ticks_nq       : SL fixe en ticks NQ
    sl_ticks_es       : SL fixe en ticks ES
    tp_target_pct     : 0 = TP au 1d_max/min (target adaptatif),
                        sinon TP fixe en pourcentage du prix.
                        Ignore si target_R > 0.
    target_R          : 0 = utilise tp_target_pct (ou 1d_max si pct=0).
                        > 0 = TP = entry + target_R * sl_ticks (R-multiple fixe).
                        OPTION 2 = 1.5R / 2R / 3R typiquement.
    timeout_bars      : EOD ou max N bars apres entry
    """
    name: str
    description: str
    levels: List[LevelDef]
    filters: List[EntryFilter] = field(default_factory=list)
    invert_direction: bool = False
    sl_ticks_nq: int = 40
    sl_ticks_es: int = 30
    tp_target_pct: float = 0.0  # 0 = adaptatif via dist_1d_max/min
    target_R: float = 0.0       # > 0 = R-multiple TP fixe (override pct/1d_max)
    timeout_bars: int = 360     # ~6h en 1min bars


def build_variants() -> Dict[str, VariantConfig]:
    """Construit le dict des 10 variantes a tester."""
    variants: Dict[str, VariantConfig] = {}

    # V1 — Purge des 9 niveaux DROP (baseline reformee, LONG only)
    variants["V1"] = VariantConfig(
        name="V1",
        description="Purge 9 niveaux DROP (baseline reformee, LONG only)",
        levels=list(LEVELS_V1_LONG),
        filters=[],
    )

    # V2 — V1 + regime actionable
    variants["V2"] = VariantConfig(
        name="V2",
        description="V1 + regime_actionable=1 + regime_favor compatible",
        levels=list(LEVELS_V1_LONG),
        filters=[filter_regime_actionable],
    )

    # V3 — V2 + footprint Dow
    variants["V3"] = VariantConfig(
        name="V3",
        description="V2 + footprint Dow (long_up_bar/long_dn_bar)",
        levels=list(LEVELS_V1_LONG),
        filters=[filter_regime_actionable, filter_footprint_dow],
    )

    # V4 — V1 + symetrie SHORT (additif)
    variants["V4"] = VariantConfig(
        name="V4",
        description="V1 + symetrie SHORT (MQ_CALL/GEX_UP/IB_HIGH/CUR_VAH)",
        levels=list(LEVELS_V1_LONG) + list(LEVELS_V4_SHORT),
        filters=[],
    )

    # V5 — V1 + BN density gate
    variants["V5"] = VariantConfig(
        name="V5",
        description="V1 + BN V4 density gate (color_zones + cluster >= 3)",
        levels=list(LEVELS_V1_LONG),
        filters=[filter_bn_density],
    )

    # V6 — V1 + BN confluence gate
    variants["V6"] = VariantConfig(
        name="V6",
        description="V1 + BN V4 confluence (>=2 niveaux memes cote 0.15%)",
        levels=list(LEVELS_V1_LONG),
        filters=[filter_bn_confluence],
    )

    # V7 — V1 + BN edge gate
    variants["V7"] = VariantConfig(
        name="V7",
        description="V1 + BN V4 edge zones (n_edge_buy/sell_active >= 1)",
        levels=list(LEVELS_V1_LONG),
        filters=[filter_bn_edge],
    )

    # V8 — V1 + BN V4 CONFLUENCE COMPLETE (density + confluence + edge + footprint)
    variants["V8"] = VariantConfig(
        name="V8",
        description="V1 + BN V4 complet (density+confluence+edge+footprint)",
        levels=list(LEVELS_V1_LONG),
        filters=[
            filter_bn_density,
            filter_bn_confluence,
            filter_bn_edge,
            filter_footprint_dow,
        ],
    )

    # V9 — INVERSION direction tous niveaux baseline+SHORT (test contre-sens)
    variants["V9"] = VariantConfig(
        name="V9",
        description="INVERSION direction tous niveaux (test contre-sens)",
        levels=list(LEVELS_V1_LONG) + list(LEVELS_V4_SHORT),
        filters=[],
        invert_direction=True,
    )

    # V10 — V1 + INVERSION (purge + contre-sens LONG only)
    variants["V10"] = VariantConfig(
        name="V10",
        description="V1 + INVERSION (purge + contre-sens LONG only)",
        levels=list(LEVELS_V1_LONG),
        filters=[],
        invert_direction=True,
    )

    return variants


if __name__ == "__main__":
    # Auto-check : print sommaire variantes
    variants = build_variants()
    print(f"\n{'='*80}")
    print(f"BOT 3 REFORM — 10 VARIANTES DEFINIES")
    print(f"{'='*80}\n")
    for name, v in variants.items():
        n_long = sum(1 for lv in v.levels if lv.side_default == "LONG")
        n_short = sum(1 for lv in v.levels if lv.side_default == "SHORT")
        n_filters = len(v.filters)
        invert = "[INVERTED]" if v.invert_direction else ""
        print(f"  {name:5s} {invert:12s} | "
              f"LONG={n_long:2d} SHORT={n_short:2d} | filters={n_filters} | "
              f"{v.description}")
    print()
