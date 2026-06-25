"""Bot 4 v2 menthorq_source — Source unique cross-bar des niveaux options MenthorQ.

Module NEW Phase P2 Batch 4 (25/06/2026) — PAS de FORK CORE/menthorq_reader.

Pattern :
- Charge fichiers JSON `DATA/MENTHORQ/{YYYYMMDD}_menthorq_complete.json` au boot
  ou cache rolling par jour
- Extrait key_levels (call_resistance, put_support, hvl, 0dte, gamma_wall_0dte,
  top_gex_strikes, bl_levels, etc.) par symbole (ES, NQ, MGC)
- Convertit en KeyLevel consommables par narrative_engine (P2 batch 3b)
- Fail-soft : si fichier absent OR section erreur (status!=ok) OR symbol absent
  -> retourne MenthorQLevels vide + emit warning (anti silent fallback)

Spec format MenthorQ (CLAUDE.md section "Procedure MenthorQ") :
- `key_levels: { ES, NQ }` avec call_resistance, put_support, hvl, 0dte,
  1d_max, 1d_min, iv_30d, gamma_condition, total_gex/dex, pc_gex/dex
- `vol_model: { ES, NQ }` avec iv_30d, GEX/DEX, top_gex_strikes (10 strikes),
  bl_levels (10 BL), gamma_wall_0dte
- Tolerance format intermediaire : `{symbol}: {structured: {...}}` (legacy scrape)

Garde-fous :
- Pas de silent fallback (warning si fichier absent OR section corrompue)
- Validation symbol path-safe (alphanumeric, max 8 chars)
- Validation date format YYYYMMDD strict
- Fail-loud raise ValueError si arguments invalides (anti VALIDATION_MISS)

Pattern caller attendu (R2 review batch 4a P2) :
- Charger UNE fois par (symbol, date_str) et CACHER cote consumer (P3 decision_router).
- Si appele par bar sans cache, ~780 warnings file_not_found/jour si MenthorQ
  manque (390 bars/jour x 2 symboles). Risk saturation logs.
- Recommandation P3 : LRU cache key=(symbol, date_str, file_mtime).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Optional

from bot4_v2.core.narrative_engine import KeyLevel
from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)

# Symbol path-safety regex (anti path traversal, max 8 chars)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,8}$")

# Date format YYYYMMDD strict (8 digits)
_DATE_RE = re.compile(r"^\d{8}$")


@dataclass(frozen=True)
class MenthorQLevels:
    """Niveaux options MenthorQ pour un symbole/date (immutable container).

    Fields documentation CLAUDE.md :
    - call_resistance / put_support : niveaux principaux options
    - hvl : High Volume Level (zone defense)
    - level_0dte : strike 0DTE max gamma
    - day_1d_max / day_1d_min : range theorique journalier
    - iv_30d : IV 30 jours
    - total_gex / net_gex / pc_gex : Gamma Exposure metrics
    - total_dex / net_dex / pc_dex : Delta Exposure metrics
    - top_gex_strikes : 10 strikes max GEX (sorted by abs)
    - bl_levels : 10 Break Levels (institutionnel)
    - gamma_wall_0dte : Gamma Wall 0DTE (mur defense)
    """

    symbol: str
    date_str: str  # YYYYMMDD format

    # Key levels principaux
    call_resistance: Optional[float] = None
    put_support: Optional[float] = None
    hvl: Optional[float] = None
    level_0dte: Optional[float] = None
    day_1d_max: Optional[float] = None
    day_1d_min: Optional[float] = None

    # Vol metrics
    iv_30d: Optional[float] = None
    total_gex: Optional[float] = None
    net_gex: Optional[float] = None
    pc_gex: Optional[float] = None
    total_dex: Optional[float] = None
    net_dex: Optional[float] = None
    pc_dex: Optional[float] = None
    gamma_condition: Optional[int] = None  # 0/1 (long gamma vs short gamma dealer)

    # Strikes / BL
    top_gex_strikes: tuple[float, ...] = field(default_factory=tuple)
    bl_levels: tuple[float, ...] = field(default_factory=tuple)
    gamma_wall_0dte: Optional[float] = None

    # Meta
    source: str = "menthorq"
    is_empty: bool = False  # True si fichier absent ou section corrompue

    @property
    def has_data(self) -> bool:
        """True si au moins 1 niveau principal present."""
        return any(
            level is not None
            for level in (
                self.call_resistance, self.put_support, self.hvl,
                self.level_0dte, self.gamma_wall_0dte,
            )
        )


def _validate_symbol(symbol: str) -> str:
    """Valide symbol path-safe et retourne UPPER. Raise ValueError sinon."""
    if not isinstance(symbol, str):
        raise ValueError(
            f"symbol must be str, got {type(symbol).__name__}"
        )
    sym_upper = symbol.upper()
    if not _SYMBOL_RE.match(sym_upper):
        raise ValueError(
            f"Invalid symbol {symbol!r}: only [A-Z0-9]+ max 8 chars allowed "
            "(path safety + Sierra Chart constraint)"
        )
    return sym_upper


def _validate_date_str(date_input) -> str:
    """Valide date input (str YYYYMMDD ou datetime.date) et retourne str canonique."""
    if isinstance(date_input, date_type):
        return date_input.strftime("%Y%m%d")
    if isinstance(date_input, str):
        if not _DATE_RE.match(date_input):
            raise ValueError(
                f"Invalid date format {date_input!r}: expected YYYYMMDD (8 digits)"
            )
        return date_input
    raise ValueError(
        f"date must be str (YYYYMMDD) or datetime.date, got {type(date_input).__name__}"
    )


def _menthorq_file_path(base_dir: Path, date_str: str) -> Path:
    """Construit le path canonique fichier MenthorQ pour une date."""
    return base_dir / f"{date_str}_menthorq_complete.json"


def _safe_extract_float(d: dict, key: str) -> Optional[float]:
    """Extract float fail-soft (None si absent / NaN / non-castable)."""
    v = d.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_extract_int(d: dict, key: str) -> Optional[int]:
    """Extract int fail-soft."""
    v = d.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _safe_extract_strikes(d: dict, key: str, max_count: int = 10) -> tuple[float, ...]:
    """Extract liste strikes en tuple float fail-soft."""
    v = d.get(key)
    if not isinstance(v, (list, tuple)):
        return ()
    out = []
    for x in v[:max_count]:
        try:
            f = float(x)
            if f == f:  # not NaN
                out.append(f)
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _is_status_ok(section: dict) -> bool:
    """True si section MenthorQ NON en erreur scraping.

    Convention : section avec keys {"message", "error_type", "status"} = erreur.
    Section valide = status absent OR status=="ok".
    """
    if not isinstance(section, dict):
        return False
    if {"message", "error_type", "status"} <= set(section.keys()):
        return section.get("status") == "ok"
    return True


def _extract_symbol_section(menthorq_json: dict, symbol: str) -> Optional[dict]:
    """Extrait la section symbole avec tolerance multi-format.

    Formats supportes (defensive parsing) :
    - `{key_levels: {ES: {...}, NQ: {...}}}` (CLAUDE.md spec officielle)
    - `{ES: {structured: {...}}, NQ: {...}}` (legacy scrape intermediaire)
    - `{ES: {call_resistance: ..., ...}, NQ: {...}}` (flat direct)

    Returns:
        dict avec niveaux symbole OR None si introuvable / corrompue.
    """
    # Format 1 : key_levels top-level (CLAUDE.md officiel)
    key_levels = menthorq_json.get("key_levels")
    if isinstance(key_levels, dict) and _is_status_ok(key_levels):
        section = key_levels.get(symbol)
        if isinstance(section, dict) and _is_status_ok(section):
            return section

    # Format 2 + 3 : symbol direct top-level
    section = menthorq_json.get(symbol)
    if not isinstance(section, dict):
        return None
    if not _is_status_ok(section):
        return None

    # Format 2 : section.structured (legacy)
    structured = section.get("structured")
    if isinstance(structured, dict):
        # Cherche key_levels dans structured
        kl = structured.get("key_levels")
        if isinstance(kl, dict) and _is_status_ok(kl):
            return kl
        # Sinon retourne structured tel quel (chercher fields directs)
        return structured

    # Format 3 : flat direct
    return section


def _extract_vol_model_section(menthorq_json: dict, symbol: str) -> Optional[dict]:
    """Extrait section vol_model (top_gex_strikes, bl_levels, gamma_wall_0dte)."""
    vol_model = menthorq_json.get("vol_model")
    if isinstance(vol_model, dict) and _is_status_ok(vol_model):
        section = vol_model.get(symbol)
        if isinstance(section, dict) and _is_status_ok(section):
            return section

    # Fallback : chercher dans symbol.structured
    section = menthorq_json.get(symbol)
    if isinstance(section, dict):
        structured = section.get("structured")
        if isinstance(structured, dict):
            return structured
    return None


def _build_levels_from_sections(
    symbol: str,
    date_str: str,
    key_levels_section: Optional[dict],
    vol_model_section: Optional[dict],
) -> MenthorQLevels:
    """Construit MenthorQLevels a partir des sections JSON extraites."""
    kl = key_levels_section or {}
    vm = vol_model_section or {}

    return MenthorQLevels(
        symbol=symbol,
        date_str=date_str,
        call_resistance=_safe_extract_float(kl, "call_resistance"),
        put_support=_safe_extract_float(kl, "put_support"),
        hvl=_safe_extract_float(kl, "hvl"),
        level_0dte=_safe_extract_float(kl, "0dte"),
        day_1d_max=_safe_extract_float(kl, "1d_max"),
        day_1d_min=_safe_extract_float(kl, "1d_min"),
        iv_30d=_safe_extract_float(kl, "iv_30d") or _safe_extract_float(vm, "iv_30d"),
        total_gex=_safe_extract_float(kl, "total_gex") or _safe_extract_float(vm, "total_gex"),
        net_gex=_safe_extract_float(kl, "net_gex") or _safe_extract_float(vm, "net_gex"),
        pc_gex=_safe_extract_float(kl, "pc_gex") or _safe_extract_float(vm, "pc_gex"),
        total_dex=_safe_extract_float(kl, "total_dex") or _safe_extract_float(vm, "total_dex"),
        net_dex=_safe_extract_float(kl, "net_dex") or _safe_extract_float(vm, "net_dex"),
        pc_dex=_safe_extract_float(kl, "pc_dex") or _safe_extract_float(vm, "pc_dex"),
        gamma_condition=_safe_extract_int(kl, "gamma_condition"),
        top_gex_strikes=_safe_extract_strikes(vm, "top_gex_strikes"),
        bl_levels=_safe_extract_strikes(vm, "bl_levels"),
        gamma_wall_0dte=_safe_extract_float(vm, "gamma_wall_0dte"),
        is_empty=False,
    )


def _empty_levels(symbol: str, date_str: str, reason: str) -> MenthorQLevels:
    """Construit MenthorQLevels vide + emit warning (anti silent fallback)."""
    _LOG.warning(
        "menthorq_source: empty levels for sym=%s date=%s reason=%s",
        symbol, date_str, reason,
    )
    return MenthorQLevels(symbol=symbol, date_str=date_str, is_empty=True)


def load_menthorq_levels(
    date_input,
    symbol: str,
    base_dir: Path,
) -> MenthorQLevels:
    """Charge niveaux MenthorQ pour une date + symbole.

    Args:
        date_input : str YYYYMMDD OR datetime.date
        symbol : "ES" / "NQ" / "MGC" (case insensitive, [A-Z0-9]+ <=8 chars)
        base_dir : Path racine `DATA/MENTHORQ/`

    Returns:
        MenthorQLevels (is_empty=True si fichier absent / section corrompue).

    Raises:
        ValueError : si date OR symbol invalides (anti VALIDATION_MISS).
    """
    sym_upper = _validate_symbol(symbol)
    date_str = _validate_date_str(date_input)

    file_path = _menthorq_file_path(base_dir, date_str)
    if not file_path.exists():
        return _empty_levels(sym_upper, date_str, "file_not_found")

    try:
        with file_path.open("r", encoding="utf-8") as f:
            menthorq_json = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return _empty_levels(
            sym_upper, date_str, f"read_fail_{type(exc).__name__}"
        )

    if not isinstance(menthorq_json, dict):
        return _empty_levels(sym_upper, date_str, "json_not_dict")

    key_levels_section = _extract_symbol_section(menthorq_json, sym_upper)
    vol_model_section = _extract_vol_model_section(menthorq_json, sym_upper)

    if key_levels_section is None and vol_model_section is None:
        return _empty_levels(
            sym_upper, date_str, "symbol_section_missing_or_corrupt"
        )

    return _build_levels_from_sections(
        sym_upper, date_str, key_levels_section, vol_model_section,
    )


def menthorq_levels_to_key_levels(
    levels: MenthorQLevels,
    close: float,
    atr: float,
) -> list[KeyLevel]:
    """Convertit MenthorQLevels en list[KeyLevel] consommable par narrative_engine.

    Args:
        levels : MenthorQLevels (peut etre is_empty=True -> retourne [])
        close : prix courant pour calcul distance_atr signed
        atr : ATR intraday en POINTS (memes unites que close)

    Returns:
        list[KeyLevel] tries par distance ascending. Vide si is_empty ou atr<=0.

    KeyLevel.label format : "MQ_{level_type}" (ex "MQ_call_resistance").
    """
    if levels.is_empty or atr <= 0:
        return []

    out = []

    def _add(price: Optional[float], label: str, level_type: str):
        if price is None:
            return
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        dist_atr = round((p - close) / atr, 4)
        out.append(KeyLevel(
            price=round(p, 2),
            label=f"MQ_{label}",
            level_type=level_type,
            distance_atr=dist_atr,
            sources=[f"MenthorQ_{label}"],
        ))

    # Resistances (level > close) sont classifiees apres tri
    _add(levels.call_resistance, "call_resistance", "resistance")
    _add(levels.put_support, "put_support", "support")
    _add(levels.hvl, "hvl", "pivot")
    _add(levels.level_0dte, "0dte", "pivot")
    _add(levels.day_1d_max, "1d_max", "resistance")
    _add(levels.day_1d_min, "1d_min", "support")
    _add(levels.gamma_wall_0dte, "gamma_wall_0dte", "pivot")

    # Top GEX strikes (max 5 plus proches)
    for i, strike in enumerate(levels.top_gex_strikes[:5]):
        _add(strike, f"top_gex_{i+1}", "pivot")

    # Break levels (max 5 plus proches)
    for i, bl in enumerate(levels.bl_levels[:5]):
        _add(bl, f"bl_{i+1}", "pivot")

    # Sort by absolute distance ascending (le plus proche en premier)
    out.sort(key=lambda kl: abs(kl.distance_atr))
    return out
