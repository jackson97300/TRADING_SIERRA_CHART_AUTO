"""bn_composites_streaming.py - Composites Battle Navale recodes Python.

Phase 1 Group A (11/06/2026) - Decision Jackson B3 + fix review NOGO #1+#2.

Sierra DMP C++ initialise `bn_score_*` a 0.0 et ne les update JAMAIS
(cf DMP_Transform.h:1397-1413 desactive 18/04/2026 audit code-reviewer).
Decision Jackson : recoder `bn_score_*` Python pour controle.

IMPORTANT - bn_pressure_ask/bid sont VIVANTS cote Sierra DMP
==============================================================
DMP_Transform.h:1393-1395 :
    f.bn_pressure_ask = SafeBool(r.is_nq ? r.bn_triple_ask : r.bn_double_ask);
    f.bn_pressure_bid = SafeBool(r.is_nq ? r.bn_triple_bid : r.bn_double_bid);
Signal Double/Triple Ask actif. Verification empirique sur 20260605_ES.jsonl :
0.5% bars `bn_pressure_ask=1`, 1.2% bars `bn_pressure_bid=1`. PAS placeholder.

Ce module NE TOUCHE PAS a bn_pressure_*. Si proxy volume-weighted necessaire,
utiliser ask_pct/bid_pct natifs (Phase 3 deja calcule).

GARDE-FOU PATTERN_11 V1 :
=========================
Si un gate hardcode sur `bn_score_X > seuil` est propose AVANT backtest
walk-forward 12-fold + DSR Lopez ml-trainer : INCIDENT_LOG PATTERN_11
immediat + rollback.

FORMULES bn_score (provisoires, a re-evaluer DSR Lopez avant tout gate) :
========================================================================

bn_score_raw = somme ponderee sous-features BN, normalisee [-1, +1]
bn_score_bull = max(0, bn_score_raw)
bn_score_bear = max(0, -bn_score_raw)

PONDERATIONS provisoires :
- bn_color_up/dn : +/- 1.0
- bn_color_up_2/dn_2 : +/- 0.5
- bn_long_up/dn : +/- 1.5
- bn_absorb_ask/bid : +/- 0.5
Normalise par 3.5 + clamp [-1, +1].

Auteur : MIA Trading V2 (Phase 1 Group A portage Sierra)
"""
from __future__ import annotations

from typing import Callable, Optional


# Normalisation : somme max ponderation positive = 1+0.5+1.5+0.5 = 3.5
_BN_SCORE_NORMALIZE = 3.5

# Whitelist features que CE module est autorise a override via _safe_update.
# bn_pressure_ask/bid EXCLUS volontairement (signal Sierra vivant).
BN_COMPOSITES_OVERRIDE_KEYS = frozenset((
    "bn_score_raw",
    "bn_score_bull",
    "bn_score_bear",
))


def compute_bn_composites(bar: dict) -> dict:
    """Calcule bn_score_raw/bull/bear depuis sous-features BN Sierra natives.

    Args:
        bar : dict avec features BN brutes (bn_color_*, bn_long_*, bn_absorb_*).

    Returns:
        dict {bn_score_raw, bn_score_bull, bn_score_bear} avec valeurs [-1, +1].
        Si inputs manquants : 0.0 (downstream attend un score, pas NaN).

    NE CALCULE PAS bn_pressure_ask/bid (signal Sierra natif vivant).
    """
    out = {
        "bn_score_raw": 0.0,
        "bn_score_bull": 0.0,
        "bn_score_bear": 0.0,
    }

    try:
        score = 0.0
        score += 1.0 * float(bar.get("bn_color_up", 0) or 0)
        score -= 1.0 * float(bar.get("bn_color_dn", 0) or 0)
        score += 0.5 * float(bar.get("bn_color_up_2", 0) or 0)
        score -= 0.5 * float(bar.get("bn_color_dn_2", 0) or 0)
        score += 1.5 * float(bar.get("bn_long_up", 0) or 0)
        score -= 1.5 * float(bar.get("bn_long_dn", 0) or 0)
        score += 0.5 * float(bar.get("bn_absorb_ask", 0) or 0)
        score -= 0.5 * float(bar.get("bn_absorb_bid", 0) or 0)

        normalized = max(-1.0, min(1.0, score / _BN_SCORE_NORMALIZE))

        out["bn_score_raw"] = round(normalized, 6)
        out["bn_score_bull"] = round(max(0.0, normalized), 6)
        out["bn_score_bear"] = round(max(0.0, -normalized), 6)
    except (TypeError, ValueError):
        pass

    return out


def inject_bn_composites(payload: dict,
                          safe_update_fn: Callable[[dict, dict], None],
                          log_fn: Optional[Callable] = None,
                          sym: str = "?") -> dict:
    """Injection bn_composites dans payload via _safe_update strict.

    NE PAS faire payload.update brutal (bypass whitelist, ecrasement Sierra non-zero).

    Args:
        payload         : dict bar enrichi.
        safe_update_fn  : callable(payload, new_dict) -> None. Doit etre
                          `SierraPipelineOrchestrator._safe_update` (gere
                          whitelist SIERRA_ZERO_NEVER_CALCULATED).
        log_fn          : callable(code, **kwargs) optional.
        sym             : symbole pour log.

    Returns:
        payload modifie in-place (via safe_update_fn).
    """
    composites = compute_bn_composites(payload)
    safe_update_fn(payload, composites)

    if log_fn is not None:
        try:
            log_fn("SIERRA_PORT_BN_COMPOSITES_OK", sym=sym)
        except Exception:  # noqa: BLE001
            pass

    return payload
