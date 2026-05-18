# ADR 0003 — Bot 3 v2 Narrative Persistence Atomic Common (NSM + StoryTrackers)

**Date** : 2026-05-18
**Phase** : Bot 3 v2 Narrative Layer Phase 0.5/1
**Status** : Accepted
**Auteur** : Agent market-analyst ULTRATHINK + Claude (mode mentor) + Jackson directive "no shortcut"
**Reviewers** : code-reviewer (Phase 1 implementation review)

## Contexte

Bot 3 v2 Narrative Layer comprend 2 modules stateful avec persistence :
1. `bot3_narrative_state_machine.py` (NSM) — état narratif 1 instance/symbol
2. `bot3_story_trackers.py` (StoryTrackers) — features rolling 60 bars history

Le module `bot3_narrative_persistence.py` (module 7 du plan) gère la sérialisation pickle.

**Question** : pickle séparé (Option B) OU commun (Option A) pour NSM + StoryTrackers ?

## Décision

**Option A : pickle commun atomic** via dataclass `NarrativePersistedState` qui contient NSM + StoryTrackers ensemble.

```python
# CORE/bot3_narrative_persistence.py (preview interface)
from dataclasses import dataclass
from pathlib import Path
import pickle
import sys

NSM_PERSIST_SCHEMA_VERSION = "2.0.0"
NSM_PERSIST_PATH = Path("DATA/LIVE_CACHE/bot3_narrative/narrative_state.pickle")


@dataclass
class NarrativePersistedState:
    """Wrapper persistence atomique NSM + StoryTrackers.

    1 fichier pickle, 1 schema_version commun, 1 os.replace() atomic.
    """
    schema_version: str = NSM_PERSIST_SCHEMA_VERSION
    nsm_states: dict[str, "NarrativeStateSnapshot"] = field(default_factory=dict)
    story_states: dict[str, "StoryTrackersState"] = field(default_factory=dict)
    last_saved_ts: float = 0.0


def save_narrative_state(nsm, story_trackers) -> bool:
    """Atomic write tmp + replace. Emit BOT3_NSM_PERSIST_OK/FAIL."""
    state = NarrativePersistedState(
        nsm_states=nsm._states,
        story_states=story_trackers._states,
        last_saved_ts=time.time(),
    )
    tmp = NSM_PERSIST_PATH.with_suffix(".pickle.tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(NSM_PERSIST_PATH)
        return True
    except (OSError, pickle.PickleError) as e:
        emit("BOT3_NSM_PERSIST_FAIL", err=str(e)[:200])
        return False


def load_narrative_state() -> NarrativePersistedState | None:
    """Load + schema check. Return None si corrompu ou schema mismatch."""
    if not NSM_PERSIST_PATH.exists():
        return None
    try:
        with open(NSM_PERSIST_PATH, "rb") as f:
            state = pickle.load(f)
        if state.schema_version != NSM_PERSIST_SCHEMA_VERSION:
            emit("BOT3_NSM_PERSIST_RECOVERED",
                 reason=f"schema_mismatch {state.schema_version}")
            return None
        return state
    except (OSError, pickle.PickleError, EOFError, AttributeError) as e:
        emit("BOT3_NSM_PERSIST_RECOVERED",
             reason=f"corruption: {e}")
        return None
```

## Justification (Option A)

### 1. Cohérence temporelle critique
NSM consume `StoryTrackers.snapshot()` à chaque `transition()`. Si recovery désynchronise (NSM v1 + Story v0), NSM peut émettre transitions sur `slope_close_60` stale = faux narratif.

→ Pattern 11 V1 silent fallback (cf `feedback_ia_traps_detection.md`).

### 2. Atomic write commun
1 seul `os.replace()` POSIX = soit les 2 sont sauvés, soit aucun.
Option B = race window entre 2 saves consécutives → desync garantie sur restart kill -9.

### 3. Schema version unique
1 vérif `schema_version == "2.0.0"` au load au lieu de 2 (anti drift versioning).

### 4. Path unique
`DATA/LIVE_CACHE/bot3_narrative/narrative_state.pickle` (vs 2 paths séparés `nsm_state.pickle` + `story_state.pickle`).

### 5. Recovery cold start cohérent
Si pickle corrompu → NSM + Story repartent ENSEMBLE de cold start (PRE_OPEN_NEUTRAL + bars_history vide).

## Option B (REJETÉE) : pickle séparés

**Pros** :
- Simplicité (1 module = 1 pickle = 1 lifecycle)
- Modularité (Story persisté sans NSM possible)

**Cons fatals** :
- Race window 2 saves consécutives → desync garantie
- Schema mismatch indépendant possible (NSM v2.0 + Story v1.0)
- Code dupliqué save/load pattern x2
- Recovery partielle (NSM recovered + Story corrompu) = état hybride dangereux

## Conséquences

### Positives
- NSM + Story synchronisés byte-perfect
- Recovery atomique cohérent
- Schema versioning unique
- Code persistence centralisé `bot3_narrative_persistence.py`

### Négatives
- NSM et Story DOIVENT advance leur `schema_version` ENSEMBLE
- Si breaking change schema l'un des 2 → bump schema_version global même si l'autre inchangé
- Couplage léger NSM ↔ Story via module persistence (acceptable car NSM consume déjà Story)

### Risques
- **Pickle corruption full** : si fichier corrompu, perte ATR buffer 60j NSM + bars_history 60 Story
  - **Mitigation** : backup horaire `narrative_state.pickle.backup-<hour>` (rotation 24h)
  - **Mitigation** : fresh start = perte ~10j data warmup ATR z-score 60d = 1-2 jours sans certaines transitions actives
- **Schema migration future** : si on ajoute field, bump version. Tests obligatoires recovery old → new.

## Validation

Avant Phase 1 commit complet :
1. **Test pickle roundtrip** : `save_narrative_state(nsm, story)` → `load_narrative_state()` → vérifier state identical
2. **Test kill -9 mid-save** : interrupt à .pickle.tmp stage → recovery fresh start (pas de corruption)
3. **Test schema mismatch** : pickle avec `schema_version="1.0.0"` → load retourne None + emit `BOT3_NSM_PERSIST_RECOVERED`
4. **Test backup rotation** : 25 saves → backup-00 à backup-23 présents, backup-24 inexistant

## Cross-references

- Spec NSM : `DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md`
- Spec StoryTrackers : `DOCS/specs/2026-05-18-bot3v2-phase1-story-trackers-spec.md`
- ADR 0002 pattern reference : `DOCS/ADR/0002-nsm-pattern-reference-live-enricher-state.md`
- Pattern existant : `CORE/live_enricher_state.py` (atomic write pickle via `bot3_narrative_persistence.py`)
- Memory `feedback_ia_traps_detection.md` (anti silent fallback contradictoire)
- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md`

## Status

- [x] ADR accepté (Phase 0.5 J+0, décision codée dans specs NSM + StoryTrackers)
- [ ] Implementation `bot3_narrative_persistence.py` (Phase 1, ~120 LOC)
- [ ] Tests 4 cas obligatoires (roundtrip / kill -9 / schema mismatch / backup rotation)
- [ ] Review code-reviewer Phase 1 Tier 2
