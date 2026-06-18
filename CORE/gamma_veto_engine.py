"""gamma_veto_engine.py - Moteur veto MenthorQ gamma walls (SSoT cross-codebase).

# Contexte

INCIDENT_LOG #74 (18/06/2026) - Root cause trade -$967 Bot 1 v2 (Sim2) :
  - `gamma_block_long/short` ABSENTS du bar enriched live (sierra_pipeline)
  - `_check_gamma_veto` (bot1_v2/dashboard_mirror.py:339) lit `bar.get("gamma_block_long")` -> None -> veto silencieux
  - Bug supplementaire detecte 18/06 lors du refactor : formule existante
    `DASHBOARD/api/builders.py:1039-1112` utilisait `0 < put_dist <= threshold`
    alors que convention `dist_mq_put < 0` (wall en-dessous) -> put veto NEVER FIRED
    meme en dashboard. Bug silencieux double.

# Solution (OPTION C - Single Source of Truth)

Extraction de la formule + fix bug signed convention + integration cross-codebase :
  - sierra_pipeline.py (enricher live)
  - DASHBOARD/api/builders.py (refactor pour importer ce module)
  - Bot 1 v2 consume via bar enriched
  - tests/test_gamma_veto_engine.py (regression complete)

# Conventions FIELDS bar enriched (verifie empirique 18/06)

  - `atr`              : ATR ticks (float, fallback 100.0 si absent)
  - `dist_mq_call`     : ticks signed, POSITIF = call wall au-dessus (resistance LONG)
                         (cf builders.py:1635-1638 + DMP_Transform.h:508)
  - `dist_mq_put`      : ticks signed, NEGATIF = put wall en-dessous (support SHORT)
  - `bool_gex_flip_zone` : 0/1, zone GEX flip = regime dealer instable
  - `call_wall_price`/`put_wall_price` : prix absolu walls (optionnels, dispos en dashboard
                                          via build_options_levels, ABSENTS bars live)

# Sentinelle 0.0 ambigue

`dist_mq_call == 0` peut signifier (a) prix PILE sur le wall, OU (b) wall absent.
  - SI `call_wall_price` is not None ET `dist == 0` -> PILE DESSUS (block hard)
  - SINON ambigu (probablement wall absent) -> pas de block

Pour les bars live (sierra_pipeline) qui n'ont PAS `call_wall_price`/`put_wall_price`,
ce check est skippe (cas rare, GEX flip capture la majorite).

# Seuil ATR-adaptatif

  threshold = clamp(_ATR_RATIO * atr, [_MIN, _MAX])
  Default: ratio=0.5, min=10, max=80

# Date : 2026-06-18
# Reviewed : code-reviewer (OPTION C SSoT) + market-analyst (pattern dormant fix)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GammaVetoConfig:
    """Configuration immutable du veto gamma.

    Calibration historique :
      - min 10t / max 80t = bornes empiriques builders.py (validees code-reviewer 13/04)
      - ratio 0.5 * ATR = demi range typique d'une barre 1min
      - default_atr 100t = fallback si ATR absent (ES typique 100-150t)
    """
    enabled: bool = True
    threshold_min_ticks: float = 10.0
    threshold_max_ticks: float = 80.0
    threshold_atr_ratio: float = 0.5
    default_atr_ticks: float = 100.0
    enable_call_wall: bool = True
    enable_put_wall: bool = True
    enable_gex_flip: bool = True


# ════════════════════════════════════════════════════════════════════════════
# VERDICT
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GammaVerdict:
    """Resultat immutable d'un check gamma sur 1 bar.

    Champs reasons_long/reasons_short : tuple JSON-serializable
    (evite collision avec `|` split, vs string concatenee).
    """
    block_long: bool
    block_short: bool
    threshold_ticks: float
    reasons_long: tuple[str, ...] = field(default_factory=tuple)
    reasons_short: tuple[str, ...] = field(default_factory=tuple)
    # Diagnostic complementaire pour debug/audit
    atr_used: float = 0.0
    call_dist_ticks: float = 0.0
    put_dist_ticks: float = 0.0
    gex_flip_active: bool = False


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _safe_float(x, default: float = 0.0) -> float:
    """Cast float defensif. None / NaN / str invalide -> default."""
    if x is None:
        return default
    try:
        v = float(x)
        if v != v:  # NaN check
            return default
        return v
    except (TypeError, ValueError):
        return default


def _compute_threshold(atr: float, cfg: GammaVetoConfig) -> float:
    """Threshold ATR-adaptatif clampe [min, max]."""
    raw = atr * cfg.threshold_atr_ratio
    return max(cfg.threshold_min_ticks,
               min(cfg.threshold_max_ticks, raw))


# ════════════════════════════════════════════════════════════════════════════
# CORE
# ════════════════════════════════════════════════════════════════════════════

def compute_gamma_verdict(
    bar: dict,
    cfg: Optional[GammaVetoConfig] = None,
) -> GammaVerdict:
    """Pure function : bar -> GammaVerdict.

    Idempotent. Pas d'effet de bord. Safe sur fields manquants/None/NaN.

    Args:
        bar : dict bar enriched (lit atr, dist_mq_call/put, bool_gex_flip_zone,
              optionnellement call_wall_price/put_wall_price pour sentinelle).
        cfg : config (default GammaVetoConfig()).

    Returns:
        GammaVerdict immutable avec block_long/short + diagnostics.

    Convention signed (cf DMP_Transform.h:508 + builders.py:1635-1638) :
        dist_mq_call > 0 = call wall au-dessus = resistance LONG
        dist_mq_put  < 0 = put wall en-dessous = support SHORT
    """
    if cfg is None:
        cfg = GammaVetoConfig()

    # Disabled -> verdict no-op
    if not cfg.enabled:
        return GammaVerdict(
            block_long=False, block_short=False, threshold_ticks=0.0,
        )

    # ATR + threshold
    atr = _safe_float(bar.get("atr"), cfg.default_atr_ticks)
    if atr <= 0:
        atr = cfg.default_atr_ticks
    threshold = _compute_threshold(atr, cfg)

    # Distances
    call_dist = _safe_float(bar.get("dist_mq_call"), 0.0)
    put_dist = _safe_float(bar.get("dist_mq_put"), 0.0)
    call_wall_price = bar.get("call_wall_price")
    put_wall_price = bar.get("put_wall_price")
    gex_flip = bool(_safe_float(bar.get("bool_gex_flip_zone"), 0.0))

    block_long = False
    block_short = False
    reasons_long: list[str] = []
    reasons_short: list[str] = []

    # ── CALL WALL ── (resistance pour LONG)
    # FIX bug builders.py : convention dist_mq_call > 0 = au-dessus
    if cfg.enable_call_wall:
        call_near = 0 < call_dist <= threshold
        call_on = (call_dist == 0.0 and call_wall_price is not None)
        if call_near or call_on:
            block_long = True
            if call_on:
                reasons_long.append("CALL_WALL_ON")
            else:
                reasons_long.append(f"CALL_WALL_NEAR_{call_dist:.0f}t")

    # ── PUT WALL ── (support pour SHORT)
    # FIX bug builders.py : convention dist_mq_put < 0 = en-dessous
    # (l'ancienne formule `0 < put_dist <= threshold` ne firait JAMAIS sur du signed negatif)
    if cfg.enable_put_wall:
        put_dist_abs = abs(put_dist) if put_dist < 0 else 0.0
        put_near = 0 < put_dist_abs <= threshold
        put_on = (put_dist == 0.0 and put_wall_price is not None)
        if put_near or put_on:
            block_short = True
            if put_on:
                reasons_short.append("PUT_WALL_ON")
            else:
                reasons_short.append(f"PUT_WALL_NEAR_{put_dist_abs:.0f}t")

    # ── GEX FLIP ── (bloque les 2 cotes)
    if cfg.enable_gex_flip and gex_flip:
        block_long = True
        block_short = True
        reasons_long.append("GEX_FLIP_ZONE")
        reasons_short.append("GEX_FLIP_ZONE")

    return GammaVerdict(
        block_long=block_long,
        block_short=block_short,
        threshold_ticks=round(threshold, 1),
        reasons_long=tuple(reasons_long),
        reasons_short=tuple(reasons_short),
        atr_used=round(atr, 1),
        call_dist_ticks=call_dist,
        put_dist_ticks=put_dist,
        gex_flip_active=gex_flip,
    )


# ════════════════════════════════════════════════════════════════════════════
# Backward-compat API (builders.py legacy `_gamma_gate_check`)
# ════════════════════════════════════════════════════════════════════════════

def gamma_gate_check_legacy(
    bar: dict,
    options: Optional[dict],
) -> tuple[bool, bool, list[str]]:
    """Compat API pour DASHBOARD/api/builders.py:_gamma_gate_check.

    Args:
        bar     : bar enriched (lit ATR).
        options : dict de build_options_levels() OU None.

    Returns:
        (block_long, block_short, warnings) - format historique builders.py.
    """
    if not options:
        return False, False, []

    # Bar enrichi de overrides options (parite avec ancien code)
    merged = dict(bar)
    for k in ("dist_mq_call", "dist_mq_put", "call_wall_price",
              "put_wall_price"):
        if k in options:
            merged[k] = options[k]
    if "gex_flip_zone" in options:
        merged["bool_gex_flip_zone"] = options["gex_flip_zone"]

    verdict = compute_gamma_verdict(merged)

    # Reconstruction warnings format historique (compat tests dashboard)
    warnings: list[str] = []
    if verdict.gex_flip_active:
        warnings.append("GAMMA: GEX FLIP ZONE — regime dealer instable")
    for r in verdict.reasons_long:
        if r == "CALL_WALL_ON":
            warnings.append("GAMMA: prix PILE sur CALL WALL MQ")
        elif r.startswith("CALL_WALL_NEAR_"):
            dist = r.replace("CALL_WALL_NEAR_", "").rstrip("t")
            warnings.append(
                f"GAMMA: CALL WALL a {dist}t (seuil {verdict.threshold_ticks:.0f}t)"
            )
    for r in verdict.reasons_short:
        if r == "PUT_WALL_ON":
            warnings.append("GAMMA: prix PILE sur PUT SUPPORT MQ")
        elif r.startswith("PUT_WALL_NEAR_"):
            dist = r.replace("PUT_WALL_NEAR_", "").rstrip("t")
            warnings.append(
                f"GAMMA: PUT SUPPORT a {dist}t (seuil {verdict.threshold_ticks:.0f}t)"
            )

    return verdict.block_long, verdict.block_short, warnings
