"""bot3_narrative_persistence.py - Atomic persistence Bot 3 v2 Narrative Layer.

Module : pickle persistence atomique COMMUNE pour NSM + StoryTrackers.

Architecture : Bot 3 v2 Narrative Layer (Phase 1 TRACKING ONLY).
Pattern reference : `CORE/live_enricher_state.py:890-909` (atomic save_state pattern).
Decision pattern : ADR 0003 `DOCS/ADR/0003-narrative-persistence-atomic-common.md`

Data source : N/A (module utility persistence).
  Inputs : NarrativeStateMachine instance + StoryTrackers states dict.

Strategie persistence :
  1. NarrativePersistedState wrapper contient nsm_states + story_states + schema_version + ts
  2. save_narrative_state : atomic write tmp + os.replace() POSIX (1 seul fail point)
  3. load_narrative_state : verif schema_version + return None si corrupt (recovery cold start)
  4. Backup horaire rotation 24h pour disaster recovery (cf risque pickle corruption full)

Path : DATA/LIVE_CACHE/bot3_narrative/narrative_state.pickle (+ backup-NN.pickle)

Created : 2026-05-18 by Jackson + Claude (mode mentor proactif)
Last modified : 2026-05-18 - creation Phase 1 J+0 PM ADR 0003

Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
Review trace : LOGS/reviews/REVIEW_BOT3V2_narrative_persistence_*.json
Memory feedback : .claude/memory/feedback_bot3v2_persistence_*.md (post-review)

Auteur : Bot 3 v2 Narrative Layer Phase 1
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 : creation skeleton (Phase 1 J+0 PM, ADR 0003 atomic commun)
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
import os
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from CORE.bot3_narrative_logging import emit
except ImportError:
    from bot3_narrative_logging import emit

logger = logging.getLogger("bot3_v2.narrative.persistence")

# Configuration via env vars (overridable tests)
NSM_PERSIST_SCHEMA_VERSION: str = "2.0.0"
NSM_PERSIST_DIR: Path = Path(
    os.getenv("BOT3V2_PERSIST_DIR", "DATA/LIVE_CACHE/bot3_narrative")
)
NSM_PERSIST_FILENAME: str = "narrative_state.pickle"
NSM_BACKUP_ROTATION_MAX: int = int(os.getenv("BOT3V2_BACKUP_ROTATION_MAX", "24"))


@dataclass
class NarrativePersistedState:
    """Wrapper persistence atomique NSM + StoryTrackers.

    Cf ADR 0003 : pickle commun = coherence temporelle critique (NSM consume
    StoryTrackers snapshot, desync au recovery = faux narratif Pattern 11 V1).

    Attributes:
        schema_version: "2.0.0" Phase 1. Bump si breaking change soit NSM
            soit Story (couplage versioning explicite).
        nsm_states: dict[symbol, NarrativeStateSnapshot] depuis NSM._states.
        story_states: dict[symbol, StoryTrackersState] depuis Story module.
        last_saved_ts: timestamp Unix dernier save (audit + sanity check).
    """
    schema_version: str = NSM_PERSIST_SCHEMA_VERSION
    nsm_states: dict[str, Any] = field(default_factory=dict)
    story_states: dict[str, Any] = field(default_factory=dict)
    last_saved_ts: float = 0.0


def _persist_path() -> Path:
    """Path absolu fichier pickle (cree dir si necessaire)."""
    NSM_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return NSM_PERSIST_DIR / NSM_PERSIST_FILENAME


def _backup_path(index: int) -> Path:
    """Path absolu backup pickle (rotation index)."""
    return NSM_PERSIST_DIR / f"narrative_state.backup-{index:02d}.pickle"


def save_narrative_state(
    nsm_states: dict[str, Any],
    story_states: dict[str, Any],
) -> bool:
    """Save atomic NSM + Story states ensemble.

    Args:
        nsm_states: dict[symbol, NarrativeStateSnapshot] (NSM._states).
        story_states: dict[symbol, StoryTrackersState] (Story module _states).

    Returns:
        True si save OK + emit BOT3_NSM_PERSIST_OK.
        False si fail + emit BOT3_NSM_PERSIST_FAIL.

    Strategy :
        1. Build NarrativePersistedState wrapper avec schema_version courant
        2. Pickle dump dans .pickle.tmp (meme directory pour atomic rename)
        3. os.replace() POSIX atomic (cross-platform sur Windows aussi)
        4. Rotate backup (move N-1 -> N, current -> 00)

    Cost : ~5-20ms selon taille NSM/Story (60 bars history * 3 symboles).
    """
    path = _persist_path()
    tmp = path.with_suffix(".pickle.tmp")

    state = NarrativePersistedState(
        schema_version=NSM_PERSIST_SCHEMA_VERSION,
        nsm_states=dict(nsm_states),  # shallow copy pour eviter mutation pendant pickle
        story_states=dict(story_states),
        last_saved_ts=time.time(),
    )

    try:
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        # Atomic rename POSIX (Windows : os.replace() = atomic, vs os.rename qui peut fail si dest exists)
        os.replace(tmp, path)
    except (OSError, pickle.PickleError, AttributeError) as e:
        emit(
            "BOT3_NSM_PERSIST_FAIL",
            err=f"{type(e).__name__}: {str(e)[:200]}",
        )
        # Cleanup tmp si reste
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False

    # Backup rotation : current -> backup-00, backup-NN-1 -> backup-NN
    try:
        _rotate_backups(path)
    except OSError as e:
        # Backup rotation fail = warning mais save OK
        logger.warning(f"Backup rotation fail : {e}")

    emit(
        "BOT3_NSM_PERSIST_OK",
        symbols=",".join(sorted(set(nsm_states) | set(story_states))),
        n_events=len(nsm_states) + len(story_states),
    )
    return True


def _rotate_backups(current_path: Path) -> None:
    """Rotation backup : current -> 00, 00 -> 01, ..., NN-1 -> NN, NN deleted.

    Strategy : shift backups indices, copier current vers backup-00.
    """
    # Delete oldest si present
    oldest = _backup_path(NSM_BACKUP_ROTATION_MAX - 1)
    if oldest.exists():
        oldest.unlink()

    # Shift backups : NN-2 -> NN-1, ..., 00 -> 01
    for i in range(NSM_BACKUP_ROTATION_MAX - 2, -1, -1):
        src = _backup_path(i)
        if src.exists():
            dst = _backup_path(i + 1)
            os.replace(src, dst)

    # Copy current -> backup-00 (NOT move, le current doit rester)
    if current_path.exists():
        backup_00 = _backup_path(0)
        # Pas de shutil.copy direct (atomicity issue) : read + write tmp + replace
        data = current_path.read_bytes()
        tmp_backup = backup_00.with_suffix(".pickle.tmp")
        tmp_backup.write_bytes(data)
        os.replace(tmp_backup, backup_00)


def load_narrative_state() -> NarrativePersistedState | None:
    """Load NSM + Story state depuis pickle. Return None si corrupt/mismatch.

    Returns:
        NarrativePersistedState si load OK + schema_version match.
        None si :
          - Fichier absent (premier boot)
          - Schema_version mismatch (migration future)
          - Pickle corrompu / EOFError / AttributeError (classe renomee)
        Dans tous les cas None -> emit BOT3_NSM_PERSIST_RECOVERED.
    """
    path = _persist_path()
    if not path.exists() or path.stat().st_size == 0:
        return None  # premier boot, pas d'emit

    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
    except (OSError, pickle.PickleError, EOFError, AttributeError) as e:
        emit(
            "BOT3_NSM_PERSIST_RECOVERED",
            sym="ALL",
            reason=f"corruption_{type(e).__name__}: {str(e)[:200]}",
        )
        return None

    if not isinstance(state, NarrativePersistedState):
        emit(
            "BOT3_NSM_PERSIST_RECOVERED",
            sym="ALL",
            reason=f"wrong_type: {type(state).__name__}",
        )
        return None

    if state.schema_version != NSM_PERSIST_SCHEMA_VERSION:
        emit(
            "BOT3_NSM_PERSIST_RECOVERED",
            sym="ALL",
            reason=f"schema_mismatch: {state.schema_version} != {NSM_PERSIST_SCHEMA_VERSION}",
        )
        return None

    return state


def cleanup_for_tests() -> None:
    """Utility tests : delete pickle + backups (re-init filesystem).

    NE PAS appeler en prod. Reserve pytest fixtures.
    """
    path = _persist_path()
    if path.exists():
        path.unlink()
    tmp = path.with_suffix(".pickle.tmp")
    if tmp.exists():
        tmp.unlink()
    for i in range(NSM_BACKUP_ROTATION_MAX):
        b = _backup_path(i)
        if b.exists():
            b.unlink()
