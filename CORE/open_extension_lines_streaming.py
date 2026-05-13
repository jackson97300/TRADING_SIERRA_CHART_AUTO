"""open_extension_lines_streaming.py

Sub-engine streaming pour Open US / Futures Extension Lines.
NOUVELLE feature demandee Jackson 2026-05-14 : open_830_et et open_930_et
doivent etre tracees comme Extension Lines persistantes (= niveaux qui
restent visibles tant que non-touches par bar futur).

Convention SC reproduite (mirror color/long extension lines) :
  - Open futures (08:30 ET, mins_et=510) : zone tracee au prix open
  - Open cash (09:30 ET, mins_et=570) : zone tracee au prix open
  - Zone touchee si bar_low <= level <= bar_high (overlap)
  - Zone touchee = desactivee (mais gardee pour stats)
  - Multi-jours : zones d'opens des jours precedents restent visibles
    jusqu'a etre touchees (cf chart manuel Jackson 13/05 avec multiples
    niveaux opens horizontaux superposes)

Features generees (4) :
  open_830_zone_active     : count zones open_830 actives (multi-jours)
  open_930_zone_active     : idem 09:30 cash open
  dist_open_830_zone_pct   : distance % close -> nearest zone open_830
  dist_open_930_zone_pct   : idem 09:30

NB : ces features SONT DISTINCTES de open_830_et / dist_open_830_pct
(commit 394db1b phase_b_plus_streaming) qui broadcast le prix open_830
sur toutes les bars du JOUR uniquement. Ici on ajoute la persistance
inter-jours via Extension Lines (= niveau encore vierge ou touche ?).

Convention pipeline :
  add_phase_b_plus_streaming (74 features + open_830/930_et + dist_*)
  + add_open_extension_lines_streaming (4 features Extension Lines, CE MODULE)

Auteur : 2026-05-14 (Jackson demande explicite)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from extension_lines_manager import ExtensionLineBuffer


@dataclass
class OpenExtensionLinesState:
    """State streaming Open Extension Lines.

    Pickle-safe : 2 ExtensionLineBuffer + scalars primitifs.
    Multi-jours : les buffers accumulent les zones jusqu'a max_zones_per_side
    (default 100) ou jusqu'a touche prix.
    """
    current_date: Optional[Any] = None     # date_et de la session courante
    buf_830: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    buf_930: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    bar_idx: int = 0
    # Flags : capture une seule fois par session
    captured_830_today: bool = False
    captured_930_today: bool = False


def _safe_float(x) -> float:
    """Cast safe : retourne float ou NaN."""
    if x is None:
        return np.nan
    try:
        f = float(x)
        return f
    except (TypeError, ValueError):
        return np.nan


def add_open_extension_lines_streaming(
    row: dict,
    state: OpenExtensionLinesState,
) -> dict:
    """Sub-engine streaming Open Extension Lines — 4 features.

    Args:
        row : dict avec date_et, mins_et, open, high, low, close.
              Requiert add_session_metadata_streaming AVANT (date_et + mins_et).
        state : OpenExtensionLinesState mutable (2 buffers + flags session).

    Returns:
        dict row + 4 features open_*_zone_*.

    Raises:
        ValueError si date_et ou mins_et absent (ordre engines).
    """
    out = dict(row)

    date_et = out.get("date_et")
    mins_et = out.get("mins_et")
    if date_et is None or mins_et is None:
        raise ValueError(
            "add_open_extension_lines_streaming requires 'date_et' AND 'mins_et' "
            "in row. Call add_session_metadata_streaming BEFORE."
        )

    o = _safe_float(out.get("open"))
    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))
    c = _safe_float(out.get("close"))

    # ─── 1. Reset flags session si nouveau jour ────────────────────────────
    # NB : on NE reset PAS les buffers (les zones precedentes restent visibles
    # jusqu'a touche ou prune max_age - mirror comportement SC sur chart Jackson)
    if date_et != state.current_date:
        state.current_date = date_et
        state.captured_830_today = False
        state.captured_930_today = False

    # ─── 2. Update buffers : deactivate zones touchees par cette bar ───────
    # Doit etre fait AVANT add_zone pour eviter instant-touch (regle
    # ExtensionLineBuffer.update_with_bar ligne 97 : skip si created==bar_idx)
    if not (np.isnan(l) or np.isnan(h)):
        state.buf_830.update_with_bar(state.bar_idx, l, h)
        state.buf_930.update_with_bar(state.bar_idx, l, h)

    # ─── 3. Capture open_830 a mins_et=510 (08:30 ET = futures cash open) ─
    if (
        mins_et == 510
        and not state.captured_830_today
        and not np.isnan(o)
    ):
        state.buf_830.add_zone(state.bar_idx, [float(o)], "buy")
        state.captured_830_today = True

    # ─── 4. Capture open_930 a mins_et=570 (09:30 ET = US cash open) ──────
    if (
        mins_et == 570
        and not state.captured_930_today
        and not np.isnan(o)
    ):
        state.buf_930.add_zone(state.bar_idx, [float(o)], "buy")
        state.captured_930_today = True

    # ─── 5. Features count + nearest distance ──────────────────────────────
    out["open_830_zone_active"] = state.buf_830.count_active("buy")
    out["open_930_zone_active"] = state.buf_930.count_active("buy")

    if not np.isnan(c) and c > 0:
        d_830 = state.buf_830.nearest_distance("buy", c)
        d_930 = state.buf_930.nearest_distance("buy", c)
        out["dist_open_830_zone_pct"] = (
            (d_830 / c) * 100 if not np.isnan(d_830) else np.nan
        )
        out["dist_open_930_zone_pct"] = (
            (d_930 / c) * 100 if not np.isnan(d_930) else np.nan
        )
    else:
        out["dist_open_830_zone_pct"] = np.nan
        out["dist_open_930_zone_pct"] = np.nan

    state.bar_idx += 1
    return out
