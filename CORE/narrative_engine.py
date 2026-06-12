"""narrative_engine.py - Formalisation reproductible analyse narration marche.

Sortie de l'audit ULTRATHINK 12/06 PM cross-check 2 agents (market-analyst +
trading-strategy-analyst). Formalise les findings de l'analyse narrative
en STRUCTURE DE DONNEES reproductible (NarrativeContext dataclass).

# Principe ANTI-PATTERN_11

Ce module produit des OBSERVATIONS STRUCTUREES uniquement.
PAS de hardcoded gates, PAS de decisions trade automatiques.

Le ML / strategy downstream consomme la NarrativeContext et decide.

# Architecture

NarrativeContext (dataclass top-level) contient :
  - timestamp + symbol + close + atr
  - key_levels : List[KeyLevel] (niveaux cles tries par distance close)
  - market_structure : MarketStructureState (open relation, profile, day type)
  - order_flow : OrderFlowState (delta day vs session, bias macro)
  - session : SessionState (London, Judas, segment)
  - patterns : PatternsDetected (single prints, FVG, sweeps)
  - macro_regime : str (VIX-based)

# Usage

    bar = ... # bar live_enriched JSONL (575+ features post Phase A)
    context = build_narrative_context(bar)
    # context.key_levels[0] = niveau le plus proche
    # context.market_structure.profile_shape = "P-shape"
    # ...

Auteur : MIA Trading V5 Phase B narrative formalization
Date   : 2026-06-12
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class KeyLevel:
    """Niveau cle (support, resistance ou pivot)."""
    price: float
    label: str  # e.g. "PDH", "VWAP_+1SD", "Cash high HIER"
    level_type: str  # "support" / "resistance" / "pivot"
    distance_atr: float  # (level - close) / atr (signed)
    sources: list = field(default_factory=list)  # ex: ["VWAP month", "cash high"]
    confluence_count: int = 1  # nombre de niveaux clusterises (<=3 ticks)


@dataclass
class MarketStructureState:
    """Etat structure marche (Dalton + Steidlmayer)."""
    open_relation: str = "UNKNOWN"  # "OAIR" / "OAOR" / "OOR"
    profile_shape: str = "UNKNOWN"  # "P" / "D" / "B" / "b"
    day_type: str = "UNKNOWN"  # "NormVar" / "Trend" / "Normal" / "Neutral" / "NonTrend"
    range_extension_completed: bool = False
    range_pos_va_pct: float = 0.0
    inside_va: bool = False
    profile_overlap_pct: Optional[float] = None
    trend_day_probability: float = 0.0


@dataclass
class OrderFlowState:
    """Etat order flow / delta."""
    delta_day: int = 0
    cvd_day: int = 0
    cvd_session: int = 0
    macro_bias: str = "NEUTRAL"  # "BULL" / "BEAR" / "NEUTRAL"
    session_bias: str = "NEUTRAL"
    bn_signals_active: bool = False
    delta_div_slope_strength: float = 0.0
    delta_div_event: int = 0  # C++ event +1/-1/0
    finish_strength: float = 0.0


@dataclass
class SessionState:
    """Etat session courante (Asia/London/US)."""
    current_segment: str = "unknown"
    is_in_london: bool = False
    is_in_us_cash: bool = False
    is_in_us_after: bool = False
    is_in_asia: bool = False
    london_open: Optional[float] = None
    london_first_hour_direction: Optional[int] = None
    judas_swing_active: bool = False
    judas_swing_direction: int = 0
    bars_since_london_open: Optional[int] = None
    mins_et: Optional[int] = None
    tod_bucket_rth: Optional[int] = None


@dataclass
class PatternsDetected:
    """Patterns ICT/Wyckoff/Dalton detectes."""
    single_prints_present: bool = False
    single_print_position: Optional[str] = None  # "above" / "below"
    single_print_dist_atr: Optional[float] = None
    single_print_density: float = 0.0
    fvg_up_count: int = 0
    fvg_dn_count: int = 0
    fvg_up_dist_atr: Optional[float] = None
    fvg_dn_dist_atr: Optional[float] = None
    sweep_high_active: int = 0
    sweep_low_active: int = 0
    sweep_high_this_bar: bool = False
    sweep_low_this_bar: bool = False
    judas_swing_active: bool = False


@dataclass
class NarrativeContext:
    """Contexte narration marche complete et structuree."""
    timestamp_utc: str
    symbol: str
    close: float
    atr: float
    atr_14m: float
    key_levels_resistance: list = field(default_factory=list)  # List[KeyLevel]
    key_levels_support: list = field(default_factory=list)
    market_structure: MarketStructureState = field(default_factory=MarketStructureState)
    order_flow: OrderFlowState = field(default_factory=OrderFlowState)
    session: SessionState = field(default_factory=SessionState)
    patterns: PatternsDetected = field(default_factory=PatternsDetected)
    macro_regime: str = "UNKNOWN"  # "calm_vix_low" / "elevated" / "extreme"
    vix_level: float = 0.0


# ════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

DAY_TYPE_MAP = {
    0: "NonTrend",
    1: "Normal",
    2: "NormVar",
    3: "Neutral",
    4: "Trend",
}

PROFILE_SHAPE_MAP = {
    0: "D",  # equilibre
    1: "P",  # acceptance haut
    2: "b",  # acceptance bas
    3: "B",  # double distribution
}

OPEN_RELATION_MAP = {
    0: "UNKNOWN",
    1: "OAIR",  # Open Auction In Range
    2: "OAOR",  # Out of VA but within range
    3: "OOR",   # Outside Range
}

CONFLUENCE_TICKS = 0.5  # tolerance pour clustering niveaux (en ATR units)


# ════════════════════════════════════════════════════════════════════════════
# EXTRACTION HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _safe_float(bar: dict, key: str, default: float = 0.0) -> float:
    v = bar.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(bar: dict, key: str, default: int = 0) -> int:
    v = bar.get(key)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_bool(bar: dict, key: str, default: bool = False) -> bool:
    v = bar.get(key)
    if v is None:
        return default
    return bool(v)


def _bias_from_value(value: float, threshold: float = 0.0) -> str:
    if value > threshold:
        return "BULL"
    if value < -threshold:
        return "BEAR"
    return "NEUTRAL"


def _macro_regime_from_vix(vix: float) -> str:
    if vix < 15.0:
        return "calm_vix_low"
    if vix < 20.0:
        return "calm"
    if vix < 25.0:
        return "elevated"
    if vix < 35.0:
        return "stressed"
    return "extreme"


# ════════════════════════════════════════════════════════════════════════════
# KEY LEVELS EXTRACTION
# ════════════════════════════════════════════════════════════════════════════

def _extract_resistance_levels(bar: dict, close: float, atr: float) -> list:
    """Extrait niveaux de resistance au-dessus du close."""
    levels = []

    def _add(price: Optional[float], label: str):
        if price is None or atr <= 0:
            return
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        if p <= close:
            return
        dist_atr = round((p - close) / atr, 4)
        levels.append(KeyLevel(
            price=round(p, 2), label=label,
            level_type="resistance", distance_atr=dist_atr,
            sources=[label],
        ))

    # Niveaux veille
    _add(bar.get("pdh"), "PDH")
    _add(bar.get("cash_high"), "Cash high HIER")
    _add(bar.get("prev_vah"), "Prev VAH")
    # VWAP bands
    _add(bar.get("vwap_d_sd1u"), "VWAP +1 SD")
    _add(bar.get("vwap_d_sd2u"), "VWAP +2 SD")
    _add(bar.get("vwap_d_sd3u"), "VWAP +3 SD")
    _add(bar.get("vwap_w"), "VWAP week")
    _add(bar.get("vwap_m"), "VWAP month")
    # Session courante
    _add(bar.get("cur_vah"), "Cur VAH")
    _add(bar.get("sess_high"), "Session high")
    _add(bar.get("ovn_high"), "OVN high")
    # Composite POC (Phase A.3)
    _add(bar.get("composite_poc_5d"), "Composite POC 5d")
    _add(bar.get("composite_poc_20d"), "Composite POC 20d")
    # PSD veille (Phase A.2a)
    _add(bar.get("prev_vwap_sd2u"), "PSD +2")
    _add(bar.get("prev_vwap_sd1u"), "PSD +1")
    _add(bar.get("prev_vwap"), "PVWAP")
    # Swing
    swing_high = None
    dsh = bar.get("dist_swing_high")
    if dsh is not None:
        try:
            swing_high = close + float(dsh)
        except (TypeError, ValueError):
            pass
    _add(swing_high, "Swing high")

    # Sort by distance ascending
    levels.sort(key=lambda l: l.distance_atr)
    return _cluster_levels(levels, atr)


def _extract_support_levels(bar: dict, close: float, atr: float) -> list:
    """Extrait niveaux de support sous le close."""
    levels = []

    def _add(price: Optional[float], label: str):
        if price is None or atr <= 0:
            return
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        if p >= close:
            return
        dist_atr = round((p - close) / atr, 4)  # negatif
        levels.append(KeyLevel(
            price=round(p, 2), label=label,
            level_type="support", distance_atr=dist_atr,
            sources=[label],
        ))

    # Niveaux veille
    _add(bar.get("pdl"), "PDL")
    _add(bar.get("cash_low"), "Cash low HIER")
    _add(bar.get("prev_val"), "Prev VAL")
    _add(bar.get("prev_vpoc"), "Prev VPOC")
    # VWAP bands
    _add(bar.get("vwap_d"), "VWAP day")
    _add(bar.get("vwap_d_sd1d"), "VWAP -1 SD")
    _add(bar.get("vwap_d_sd2d"), "VWAP -2 SD")
    _add(bar.get("vwap_d_sd3d"), "VWAP -3 SD")
    # Session courante
    _add(bar.get("cur_val"), "Cur VAL")
    _add(bar.get("cur_vpoc"), "Cur VPOC")
    _add(bar.get("sess_low"), "Session low")
    _add(bar.get("ovn_low"), "OVN low")
    # PSD veille
    _add(bar.get("prev_vwap_sd1d"), "PSD -1")
    _add(bar.get("prev_vwap_sd2d"), "PSD -2")
    # Composite POC (peut etre below)
    cp5d = bar.get("composite_poc_5d")
    if cp5d is not None:
        try:
            if float(cp5d) < close:
                _add(cp5d, "Composite POC 5d")
        except (TypeError, ValueError):
            pass
    # Swing
    swing_low = None
    dsl = bar.get("dist_swing_low")
    if dsl is not None:
        try:
            swing_low = close + float(dsl)  # dsl negatif
        except (TypeError, ValueError):
            pass
    _add(swing_low, "Swing low")

    # Sort by distance descending (plus proche = distance plus proche de 0)
    levels.sort(key=lambda l: -l.distance_atr)
    return _cluster_levels(levels, atr)


def _cluster_levels(levels: list, atr: float) -> list:
    """Clusterise niveaux proches (<0.5 ATR) en confluences.

    Returns liste avec confluence_count + sources fusionnees.
    """
    if not levels or atr <= 0:
        return levels

    clustered = []
    used = [False] * len(levels)

    for i, level in enumerate(levels):
        if used[i]:
            continue
        cluster_sources = list(level.sources)
        cluster_count = 1
        cluster_prices = [level.price]
        for j in range(i + 1, len(levels)):
            if used[j]:
                continue
            other = levels[j]
            if abs(other.price - level.price) / atr <= CONFLUENCE_TICKS:
                cluster_sources.extend(other.sources)
                cluster_count += 1
                cluster_prices.append(other.price)
                used[j] = True
        used[i] = True
        # Cluster level = mediane des prix + sources fusionnees
        median_price = round(sum(cluster_prices) / len(cluster_prices), 2)
        new_level = KeyLevel(
            price=median_price,
            label=" + ".join(cluster_sources) if cluster_count > 1 else level.label,
            level_type=level.level_type,
            distance_atr=round((median_price - (median_price - level.price * 0))
                               / atr, 4),  # placeholder fix below
            sources=cluster_sources,
            confluence_count=cluster_count,
        )
        # Recalcul distance pour mediane
        new_level.distance_atr = round((median_price - (level.price - level.distance_atr * atr))
                                       / atr, 4)
        clustered.append(new_level)

    return clustered


# ════════════════════════════════════════════════════════════════════════════
# STATE EXTRACTION
# ════════════════════════════════════════════════════════════════════════════

def _extract_market_structure(bar: dict) -> MarketStructureState:
    """Extrait MarketStructureState depuis bar."""
    return MarketStructureState(
        open_relation=OPEN_RELATION_MAP.get(_safe_int(bar, "open_relation_type"), "UNKNOWN"),
        profile_shape=PROFILE_SHAPE_MAP.get(_safe_int(bar, "profile_shape"), "UNKNOWN"),
        day_type=DAY_TYPE_MAP.get(_safe_int(bar, "day_type"), "UNKNOWN"),
        range_extension_completed=_safe_bool(bar, "range_extension_completed"),
        range_pos_va_pct=_safe_float(bar, "range_pos_va") / 100.0 if _safe_float(bar, "range_pos_va") > 1.5 else _safe_float(bar, "range_pos_va"),
        inside_va=_safe_bool(bar, "inside_cur_va"),
        profile_overlap_pct=bar.get("profile_overlap_pct"),
        trend_day_probability=_safe_float(bar, "trend_day_probability"),
    )


def _extract_order_flow(bar: dict) -> OrderFlowState:
    """Extrait OrderFlowState depuis bar."""
    delta_day = _safe_int(bar, "delta_day")
    cvd_day = _safe_int(bar, "cvd_day")
    cvd_session = _safe_int(bar, "cvd_session")

    # BN signals actifs si au moins 1 non-nul
    bn_active = any(
        _safe_float(bar, k) != 0.0
        for k in ("bn_color_up", "bn_color_dn", "bn_absorb_ask", "bn_absorb_bid",
                  "bn_score_raw", "bn_long_up", "bn_long_dn")
    )

    return OrderFlowState(
        delta_day=delta_day,
        cvd_day=cvd_day,
        cvd_session=cvd_session,
        macro_bias=_bias_from_value(cvd_day, threshold=1000),
        session_bias=_bias_from_value(cvd_session, threshold=200),
        bn_signals_active=bn_active,
        delta_div_slope_strength=_safe_float(bar, "delta_div_slope_strength"),
        delta_div_event=_safe_int(bar, "delta_divergence"),
        finish_strength=_safe_float(bar, "finish_strength"),
    )


def _extract_session(bar: dict) -> SessionState:
    """Extrait SessionState depuis bar."""
    return SessionState(
        current_segment=bar.get("session_segment", "unknown"),
        is_in_london=_safe_bool(bar, "is_in_london"),
        is_in_us_cash=_safe_bool(bar, "is_in_us_cash"),
        is_in_us_after=_safe_bool(bar, "is_in_us_after"),
        is_in_asia=_safe_bool(bar, "is_in_asia"),
        london_open=bar.get("london_open"),
        london_first_hour_direction=bar.get("london_first_hour_direction"),
        judas_swing_active=_safe_bool(bar, "judas_swing_active"),
        judas_swing_direction=_safe_int(bar, "judas_swing_direction"),
        bars_since_london_open=bar.get("bars_since_london_open"),
        mins_et=bar.get("mins_et"),
        tod_bucket_rth=bar.get("tod_bucket_rth"),
    )


def _extract_patterns(bar: dict) -> PatternsDetected:
    """Extrait PatternsDetected depuis bar."""
    sp_present = _safe_bool(bar, "has_single_prints")
    sp_pos = None
    if sp_present:
        if _safe_bool(bar, "single_print_above"):
            sp_pos = "above"
        elif _safe_bool(bar, "single_print_below"):
            sp_pos = "below"

    return PatternsDetected(
        single_prints_present=sp_present,
        single_print_position=sp_pos,
        single_print_dist_atr=bar.get("dist_single_print_atr"),
        single_print_density=_safe_float(bar, "single_print_density"),
        fvg_up_count=_safe_int(bar, "fvg_up_active"),
        fvg_dn_count=_safe_int(bar, "fvg_dn_active"),
        fvg_up_dist_atr=bar.get("dist_fvg_up_nearest_atr"),
        fvg_dn_dist_atr=bar.get("dist_fvg_dn_nearest_atr"),
        sweep_high_active=_safe_int(bar, "sweep_high_active"),
        sweep_low_active=_safe_int(bar, "sweep_low_active"),
        sweep_high_this_bar=_safe_bool(bar, "sweep_high_this_bar"),
        sweep_low_this_bar=_safe_bool(bar, "sweep_low_this_bar"),
        judas_swing_active=_safe_bool(bar, "judas_swing_active"),
    )


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE
# ════════════════════════════════════════════════════════════════════════════

def build_narrative_context(bar: dict) -> NarrativeContext:
    """Construit NarrativeContext complet depuis bar live_enriched.

    Args:
        bar : dict bar JSONL avec 575+ features post Phase A

    Returns:
        NarrativeContext immutable (sauf via dataclass setattr).
    """
    close = _safe_float(bar, "close")
    atr = _safe_float(bar, "atr", default=1.0)
    atr_14m = _safe_float(bar, "atr_14m", default=1.0)
    vix = _safe_float(bar, "vix_level", default=20.0)

    ts_ms = bar.get("ts", 0)
    try:
        ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        ts_iso = "unknown"

    return NarrativeContext(
        timestamp_utc=ts_iso,
        symbol=bar.get("sym", "UNKNOWN"),
        close=close,
        atr=atr,
        atr_14m=atr_14m,
        key_levels_resistance=_extract_resistance_levels(bar, close, atr),
        key_levels_support=_extract_support_levels(bar, close, atr),
        market_structure=_extract_market_structure(bar),
        order_flow=_extract_order_flow(bar),
        session=_extract_session(bar),
        patterns=_extract_patterns(bar),
        macro_regime=_macro_regime_from_vix(vix),
        vix_level=vix,
    )
