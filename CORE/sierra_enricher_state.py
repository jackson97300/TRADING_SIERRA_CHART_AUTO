"""Sierra Enricher State : wrapper save/load avec STATE_DIR dedie.

Phase 0 Sierra Pipeline Port (11/06/2026) - Decision B1 Option C.

Re-implemente save/load de live_enricher_state.py avec sous-dossier dedie pour
eviter collision avec Live-Enricher Databento prod.

POLITIQUE :
==========
- Reutilise LiveEnricherState dataclass (heritage schema, anti-drift)
- SIERRA_STATE_DIR distinct de STATE_DIR Databento
- Detection collision : si load resout dans STATE_DIR Databento -> abort + log CRITIQUE
- Zero impact sur live_enricher_state.py module Databento prod (pas de patch global)

AVANTAGES Option C vs Option A (patch global STATE_DIR) ou Option B (refactor _state_path) :
- Zero modif Databento prod : `live_enricher_state.py` intact
- Schema partage : reutilise dataclass parent, anti-drift schema
- Isolation totale : SIERRA_STATE_DIR distinct
- Detection collision : ajoute defense en profondeur

Cf design doc : DOCS/superpowers/specs/2026-06-11-sierra-pipeline-port-phase0-design-v2.md
"""
from __future__ import annotations

import pickle
import time
from pathlib import Path
from typing import Optional

from CORE.live_enricher_state import (
    LiveEnricherState,
    STATE_SCHEMA_VERSION,
    _emit_log,
)

ROOT = Path(__file__).resolve().parents[1]

# CRITIQUE : sous-dossier dedie Sierra pour eviter collision Databento
SIERRA_STATE_DIR = ROOT / "DATA" / "LIVE_CACHE" / "enricher_state_sierra"
SIERRA_STATE_DIR.mkdir(parents=True, exist_ok=True)

# Detection collision : path Databento (pour assertion defense en profondeur)
DATABENTO_STATE_DIR = ROOT / "DATA" / "LIVE_CACHE" / "enricher_state"


def _sierra_state_path(symbol: str) -> Path:
    """Path snapshot Sierra dans sous-dossier dedie.

    Args:
        symbol : ES, NQ, ES.c.0, etc.

    Returns:
        Path : SIERRA_STATE_DIR / "sierra_{sym}_state.pickle"
    """
    safe = symbol.replace("/", "_").replace(".", "_")
    return SIERRA_STATE_DIR / f"sierra_{safe}_state.pickle"


def _validate_path_isolation(path: Path) -> bool:
    """Defense en profondeur : verifier path est bien dans SIERRA_STATE_DIR.

    Si le path resolu est dans DATABENTO_STATE_DIR (symlink, bug, mistake),
    abort + emit CRITIQUE pour eviter collision pickle Databento prod.

    Returns:
        bool : True si path est dans SIERRA_STATE_DIR, False sinon (collision detectee).
    """
    try:
        resolved = path.resolve()
        sierra_resolved = SIERRA_STATE_DIR.resolve()
        databento_resolved = DATABENTO_STATE_DIR.resolve()

        # Path doit etre dans Sierra
        if sierra_resolved not in resolved.parents and resolved.parent != sierra_resolved:
            return False

        # Path NE DOIT PAS etre dans Databento (defense croisee)
        if databento_resolved in resolved.parents or resolved.parent == databento_resolved:
            return False

        return True
    except (OSError, RuntimeError):
        return False


def save_sierra_state(state: LiveEnricherState) -> bool:
    """Snapshot atomic Sierra state sur disque (pickle).

    Mirror save_state Databento mais path Sierra-dedie. Pattern atomic
    tmp + rename pour eviter corruption mid-write.

    Returns:
        bool : True si OK, False si erreur.
    """
    path = _sierra_state_path(state.symbol)

    # Defense profondeur : valider isolation avant ecriture
    if not _validate_path_isolation(path):
        _emit_log(
            "SIERRA_STATE_COLLISION_DETECTED",
            sym=state.symbol,
            path=str(path),
            err="path validation failed (Databento collision suspected)",
        )
        return False

    tmp = path.with_suffix(".pickle.tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        state.last_snapshot_ts = time.time()
        _emit_log(
            "SIERRA_STATE_SNAPSHOT_OK",
            sym=state.symbol,
            bars=len(state._bars_deque),
            trades=len(state._trades_deque),
            engines=len(state.engine_states),
            path=str(path),
        )
        return True
    except (OSError, pickle.PickleError) as e:
        _emit_log(
            "SIERRA_STATE_SNAPSHOT_FAIL",
            sym=state.symbol,
            err=str(e)[:200],
        )
        return False


def load_sierra_state(symbol: str) -> Optional[LiveEnricherState]:
    """Charge le Sierra state depuis disque si existe + valide.

    + Detection collision : si load resout dans DATABENTO_STATE_DIR (probleme
    symlink/path mistake), abort + emit CRITIQUE.

    Returns:
        LiveEnricherState | None : None si fichier absent/corrompu/collision.
    """
    path = _sierra_state_path(symbol)

    # Defense profondeur : valider isolation avant lecture
    if not _validate_path_isolation(path):
        _emit_log(
            "SIERRA_STATE_COLLISION_DETECTED",
            sym=symbol,
            path=str(path),
            err="path validation failed (Databento collision suspected)",
        )
        return None

    if not path.exists() or path.stat().st_size == 0:
        return None

    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
        if not isinstance(state, LiveEnricherState):
            _emit_log(
                "SIERRA_STATE_LOAD_FAIL",
                sym=symbol,
                err=f"not LiveEnricherState instance ({type(state).__name__})",
            )
            return None
        if state.symbol != symbol:
            _emit_log(
                "SIERRA_STATE_LOAD_FAIL",
                sym=symbol,
                err=f"symbol mismatch (loaded={state.symbol})",
            )
            return None
        if state.schema_version != STATE_SCHEMA_VERSION:
            _emit_log(
                "SIERRA_STATE_SCHEMA_MISMATCH",
                sym=symbol,
                loaded=state.schema_version,
                expected=STATE_SCHEMA_VERSION,
            )
            return None
        return state
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError) as e:
        _emit_log(
            "SIERRA_STATE_LOAD_FAIL",
            sym=symbol,
            err=str(e)[:200],
        )
        return None


def make_sierra_enricher_state(symbol: str) -> LiveEnricherState:
    """Factory : load existing Sierra state OR create new.

    Pattern uniforme avec live_enricher_state.initialize_state() Databento
    mais isolation totale (sous-dossier + validation path).

    Args:
        symbol : ES, NQ, ES.c.0, etc.

    Returns:
        LiveEnricherState : pret a etre passe a SierraPipelineOrchestrator.
    """
    state = load_sierra_state(symbol)
    if state is None:
        state = LiveEnricherState(symbol=symbol)
    return state
