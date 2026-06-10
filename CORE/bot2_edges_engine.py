"""bot2_edges_engine.py — Framework long terme edges validés Bot 2 V6.

Architecture (Jackson 13/05/2026) : au lieu d'ajouter chaque edge inline dans
bias_calculator_v6.py (patch one-shot), centraliser dans un registre
dédié avec metadata validation walk-forward.

Avantages :
- Nouveau edge = `register_edge(ValidatedEdge(...))`, zero modif bias_calculator
- Audit visible : DSR + validation_date + backtest_pf documentés par edge
- Désactivable via config sans toucher code : `EDGES_DISABLED = [...]`
- Test unitaire isolé par edge
- Catalog edges = roadmap visible
- ZERO régression : si registry vide ou tous disabled, retourne (0, []) →
  comportement Bot 2 V6 identique à pré-deploy

Usage dans bias_calculator_v6.compute_bias() :
    boost, fired_edges = compute_edges_boost(bar, side)
    score += boost  # 0 si aucun edge fire ou tous disabled
    # log les fired_edges pour traçabilité

Validation date : 2026-05-13 (bench V4 36 tests TripleSym).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ValidatedEdge:
    """Métadonnées d'un edge validé pour Bot 2 V6.

    Args:
        name : identifiant unique edge (kebab-case)
        fire_condition : (bar_dict, side) -> bool. True si edge fire sur la bar/side.
        score_boost : +N points score si fire (typiquement 10-20)
        side : "LONG"/"SHORT"/None (bilateral, fire pour les 2 sides distinctement)
        regime_filter : optional list ex ["RANGE","NORMAL"] (exclu TREND pour mean rev)
        symbol_filter : optional list ex ["NQ"] (edge sym-specific)
        dsr_walk_forward : DSR Lopez 12-fold (-1.0 si pas calculé)
        n_fold_min : n minimum/fold (typically ≥30 Lopez)
        backtest_pf : PF backtest 12-fold global
        backtest_wr : Win Rate backtest 12-fold
        validation_date : YYYY-MM-DD
        notes : commentaire libre (régime favori, edge case, etc.)
    """
    name: str
    fire_condition: Callable[[dict, str], bool]
    score_boost: int
    side: Optional[str] = None
    regime_filter: Optional[list[str]] = None
    symbol_filter: Optional[list[str]] = None
    dsr_walk_forward: float = -1.0
    n_fold_min: int = 0
    backtest_pf: float = 0.0
    backtest_wr: float = 0.0
    validation_date: str = ""
    notes: str = ""


# Registry global. Populé via register_edge() ci-dessous.
EDGES_REGISTRY: list[ValidatedEdge] = []

# Edges désactivés via config (sans toucher code). Liste de names.
# Exemple : pour rollback urgent d'un edge en production, ajouter ici.
EDGES_DISABLED: set[str] = set()


def register_edge(edge: ValidatedEdge) -> None:
    """Enregistre un edge dans le registry global.

    Vérifications :
    - Pas de doublon name
    - score_boost dans [1, 50] (sanity check)
    - fire_condition callable
    """
    if edge.name in [e.name for e in EDGES_REGISTRY]:
        raise ValueError(f"Edge name déjà enregistré : {edge.name}")
    if not (1 <= edge.score_boost <= 50):
        raise ValueError(f"score_boost {edge.score_boost} hors range [1, 50]")
    if not callable(edge.fire_condition):
        raise ValueError(f"fire_condition non callable pour {edge.name}")
    EDGES_REGISTRY.append(edge)


def compute_edges_boost(bar: dict, side: str, symbol: str = "", regime: str = "") -> tuple[int, list[str]]:
    """Calcule le boost total + liste des edges actifs pour une bar/side.

    Args:
        bar : dict features bar courante (incluant bars_since_*, regime_mode, etc.)
        side : "LONG" ou "SHORT"
        symbol : symbol courant (ES, NQ, MGC) pour filtre symbol_filter
        regime : régime courant (TREND/RANGE/NORMAL) pour filtre regime_filter

    Returns:
        (total_boost, fired_edges_names) — total_boost=0 si aucun edge fire
        ou tous disabled. Aucune exception ne remonte (best-effort logging).
    """
    if not EDGES_REGISTRY:
        return (0, [])

    total_boost = 0
    fired_edges: list[str] = []

    for edge in EDGES_REGISTRY:
        if edge.name in EDGES_DISABLED:
            continue
        # Filtre side
        if edge.side and edge.side != side:
            continue
        # Filtre symbol
        if edge.symbol_filter and symbol and symbol not in edge.symbol_filter:
            continue
        # Filtre regime
        if edge.regime_filter and regime and regime not in edge.regime_filter:
            continue
        # Évaluer fire_condition (best-effort, jamais raise)
        try:
            if edge.fire_condition(bar, side):
                total_boost += edge.score_boost
                fired_edges.append(edge.name)
        except (KeyError, TypeError, ValueError):
            # Edge condition échoue silencieusement (feature manquante etc.)
            # Préserve ZERO régression du bias_calculator parent.
            continue

    return (total_boost, fired_edges)


def get_edge(name: str) -> Optional[ValidatedEdge]:
    """Récupère un edge par name (None si absent)."""
    for edge in EDGES_REGISTRY:
        if edge.name == name:
            return edge
    return None


def disable_edge(name: str) -> bool:
    """Désactive un edge runtime sans toucher code. True si trouvé."""
    if any(e.name == name for e in EDGES_REGISTRY):
        EDGES_DISABLED.add(name)
        return True
    return False


def enable_edge(name: str) -> bool:
    """Réactive un edge précédemment désactivé. True si trouvé dans EDGES_DISABLED."""
    if name in EDGES_DISABLED:
        EDGES_DISABLED.remove(name)
        return True
    return False


def list_edges() -> list[dict]:
    """Liste plate des edges enregistrés (pour dashboard/audit)."""
    return [
        {
            "name": e.name,
            "score_boost": e.score_boost,
            "side": e.side,
            "regime_filter": e.regime_filter,
            "symbol_filter": e.symbol_filter,
            "dsr_walk_forward": e.dsr_walk_forward,
            "backtest_pf": e.backtest_pf,
            "backtest_wr": e.backtest_wr,
            "validation_date": e.validation_date,
            "enabled": e.name not in EDGES_DISABLED,
        }
        for e in EDGES_REGISTRY
    ]


# ─────────────────────────────────────────────────────────────────────────
# CONDITIONS D'EDGE — fonctions pure helper (testables isolement)
# ─────────────────────────────────────────────────────────────────────────

def _swing_low_recency_5_long(bar: dict, side: str) -> bool:
    """Fire si bars_since_last_swing_low <= 5 ET side == LONG.

    Mean reversion post-swing low récent. Validé bench 13/05 :
      ES 1512 trades WR 74% +2.0t médian
      NQ 2078 trades WR 77% +9.5t médian
      MGC 58390 trades WR 75% +1.4t médian
    """
    if side != "LONG":
        return False
    bars_since = bar.get("bars_since_last_swing_low")
    if bars_since is None:
        return False
    try:
        return float(bars_since) <= 5
    except (TypeError, ValueError):
        return False


def _swing_high_recency_5_short(bar: dict, side: str) -> bool:
    """Fire si bars_since_last_swing_high <= 5 ET side == SHORT.

    Mean reversion post-swing high récent. Validé bench 13/05 :
      ES 2183 trades WR 67% -0.5t médian
      NQ 2264 trades WR 72% -6.0t médian
      MGC 58341 trades WR 76% -1.3t médian (inv WR>0=24%)
    """
    if side != "SHORT":
        return False
    bars_since = bar.get("bars_since_last_swing_high")
    if bars_since is None:
        return False
    try:
        return float(bars_since) <= 5
    except (TypeError, ValueError):
        return False


# ─────────────────────────────────────────────────────────────────────────
# REGISTRY POPULATION — edges à activer post-validation walk-forward
# ─────────────────────────────────────────────────────────────────────────

# NOTE 13/05/2026 : edges PRE-VALIDATION. À enregistrer SEULEMENT après
# validation walk-forward 12-fold par ml-trainer (Phase 2 plan).
# Pour activer post-validation : décommenter les register_edge() ci-dessous
# avec dsr_walk_forward / backtest_pf / backtest_wr empiriques.

# register_edge(ValidatedEdge(
#     name="swing-low-recency-5-long",
#     fire_condition=_swing_low_recency_5_long,
#     score_boost=15,
#     side="LONG",
#     regime_filter=["RANGE", "NORMAL"],  # mean rev exclu TREND fort
#     symbol_filter=None,  # bilateral 3 syms
#     dsr_walk_forward=0.0,  # À remplir post-Phase2
#     n_fold_min=0,          # À remplir post-Phase2
#     backtest_pf=0.0,       # À remplir post-Phase2
#     backtest_wr=0.0,       # À remplir post-Phase2
#     validation_date="2026-05-13",
#     notes="Bench V4 13/05 TripleSym WR 74-77% post swing low récent.",
# ))

# register_edge(ValidatedEdge(
#     name="swing-high-recency-5-short",
#     fire_condition=_swing_high_recency_5_short,
#     score_boost=15,
#     side="SHORT",
#     regime_filter=["RANGE", "NORMAL"],
#     symbol_filter=None,
#     dsr_walk_forward=0.0,
#     n_fold_min=0,
#     backtest_pf=0.0,
#     backtest_wr=0.0,
#     validation_date="2026-05-13",
#     notes="Bench V4 13/05 TripleSym WR 67-76% post swing high récent.",
# ))
