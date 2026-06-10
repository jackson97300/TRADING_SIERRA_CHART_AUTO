"""eco_news_features.py — Features news / event blackouts pour live_enricher.

Phase 3.7 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.8

Module wrapper feature-engineering AUTOUR de `eco_calendar.py` (existant 29/04).
**AUCUNE source de calendrier additionnelle** — on consomme `eco_calendar.get_status()`
et `next_event_block()`.

Features produites (10) :

  Forward-looking events High USD (fenetres 5/15/30/60 min) :
    1. is_news_5m   : bool, event High USD dans 5 prochaines min
    2. is_news_15m  : bool, event dans 15 min
    3. is_news_30m  : bool, event dans 30 min
    4. is_news_60m  : bool, event dans 60 min

  Criticite (FOMC, NFP, CPI) :
    5. is_critical_news_60m : bool, event critical dans 60 min

  Temps avant event :
    6. news_seconds_until : int ou NaN, secondes jusqu'au prochain event blocking
    7. news_minutes_until : float ou NaN, minutes (= seconds / 60)

  Etat blackout actuel :
    8. is_eco_blocked       : bool, actuellement dans une fenetre eco event
    9. is_session_blocked   : bool, dans une fenetre session structurelle (open US vol, post-MOC)
   10. is_blocked_combined  : bool, eco OR session blocked

Source dependances :
  - `eco_calendar.next_event_block(now_utc)` : prochain event blocking
  - `eco_calendar.get_status(now_utc)` : etat complet (blocked + sessions)

Gracieux degraded (design eco_calendar 29/04) :
  - Si ForexFactory inaccessible : cache fallback (TTL 6h)
  - Si cache expired : features sont calculees sur cache stale + log warning
  - Pas de raise -> live_enricher continue en degraded mode

Anti-pattern interdit (cf BN V5 KILL 10/06) :
  - Composite hardcode (gate "skip if is_news_15m") -> garder features brutes,
    laisser LightGBM apprendre interactions
  - Silent fallback ts invalide -> raise ValueError (FAIL LOUD)

Auteur : MIA Trading V2 (Phase 3.7 Sierra Migration)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

# Import gracieux : si eco_calendar indispo en test, fallback degraded
try:
    from CORE.eco_calendar import get_status, next_event_block
except ImportError:
    try:
        from eco_calendar import get_status, next_event_block
    except ImportError:
        get_status = None
        next_event_block = None


# ────────────────────────────────────────────────────────────────────────────
# Constantes fenetres forward-looking (secondes)
# ────────────────────────────────────────────────────────────────────────────

WINDOW_5M_SEC = 5 * 60
WINDOW_15M_SEC = 15 * 60
WINDOW_30M_SEC = 30 * 60
WINDOW_60M_SEC = 60 * 60


# ────────────────────────────────────────────────────────────────────────────
# API publique
# ────────────────────────────────────────────────────────────────────────────

def compute_eco_news_features(
    now_utc: Optional[datetime] = None,
) -> dict:
    """Compute 10 features news/blackout pour une timestamp donnee.

    Args:
        now_utc : timestamp UTC tz-aware. None -> datetime.now(timezone.utc).

    Returns:
        dict avec 10 keys (cf docstring module).

    Raises:
        RuntimeError : si eco_calendar module indispo (degraded import path)
    """
    if get_status is None or next_event_block is None:
        raise RuntimeError(
            "eco_news_features : module eco_calendar non disponible. "
            "Verifier CORE/eco_calendar.py et imports."
        )

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # FAIL LOUD : ts naive interdit (DST hell)
    if now_utc.tzinfo is None:
        raise ValueError(
            f"compute_eco_news_features : now_utc doit etre tz-aware UTC, "
            f"obtenu naive {now_utc}"
        )

    status = get_status(now_utc)
    next_ev = next_event_block(now_utc)

    # Forward-looking : event High USD dans X seconds ?
    if next_ev is not None:
        in_sec = next_ev.get("in_seconds")
        is_critical = bool(next_ev.get("is_critical", False))
    else:
        in_sec = None
        is_critical = False

    return {
        "is_news_5m": _is_within(in_sec, WINDOW_5M_SEC),
        "is_news_15m": _is_within(in_sec, WINDOW_15M_SEC),
        "is_news_30m": _is_within(in_sec, WINDOW_30M_SEC),
        "is_news_60m": _is_within(in_sec, WINDOW_60M_SEC),
        "is_critical_news_60m": is_critical and _is_within(in_sec, WINDOW_60M_SEC),
        "news_seconds_until": int(in_sec) if in_sec is not None else np.nan,
        "news_minutes_until": float(in_sec) / 60.0 if in_sec is not None else np.nan,
        "is_eco_blocked": bool(status.get("eco_blocked", False)),
        "is_session_blocked": bool(status.get("session_blocked", False)),
        "is_blocked_combined": bool(status.get("blocked", False)),
    }


def _is_within(in_sec: Optional[int], window_sec: int) -> bool:
    """True si in_sec existe ET >= 0 ET <= window_sec.

    in_sec < 0 (event passe) ou None -> False.
    """
    if in_sec is None:
        return False
    return 0 <= in_sec <= window_sec


def compute_eco_news_features_batch(
    df: pd.DataFrame,
    ts_col: str = "ts_utc",
) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec colonne ts_utc (string ISO ou datetime tz-aware).
        ts_col : nom colonne timestamp.

    Returns:
        DataFrame copie + 10 colonnes ajoutees.

    Raises:
        ValueError : si ts_col manquant.
    """
    if ts_col not in df.columns:
        raise ValueError(
            f"compute_eco_news_features_batch : colonne '{ts_col}' manquante"
        )

    result = df.copy()
    rows = []
    for ts in df[ts_col].values:
        if pd.isna(ts):
            rows.append(_empty_features())
            continue
        if isinstance(ts, str):
            now_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, (datetime, pd.Timestamp)):
            now_utc = pd.Timestamp(ts).to_pydatetime()
        else:
            rows.append(_empty_features())
            continue

        # Force UTC tz-aware si naive (assume UTC convention pipeline)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        rows.append(compute_eco_news_features(now_utc))

    # Materialize en colonnes
    features_df = pd.DataFrame(rows, index=result.index)
    for col in features_df.columns:
        result[col] = features_df[col].values
    return result


def _empty_features() -> dict:
    """Features par defaut (NaN/False) pour ts invalide en batch."""
    return {
        "is_news_5m": False,
        "is_news_15m": False,
        "is_news_30m": False,
        "is_news_60m": False,
        "is_critical_news_60m": False,
        "news_seconds_until": np.nan,
        "news_minutes_until": np.nan,
        "is_eco_blocked": False,
        "is_session_blocked": False,
        "is_blocked_combined": False,
    }
