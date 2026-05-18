# ADR 0002 — NSM Pattern Reference : LiveEnricherState (not BreakoutRetestStateMachine)

**Date** : 2026-05-18
**Phase** : Bot 3 v2 Narrative Layer Phase 0.5
**Status** : Accepted
**Auteur** : Claude (mode mentor adversarial) + agent Plan ULTRATHINK challenge
**Reviewers** : market-analyst (Phase 1 architecture review)

## Contexte

Le plan original Bot 3 v2 (master plan + KB section 2) proposait `BreakoutRetestStateMachine` (BRS, `CORE/bot3_breakout_retest.py`) comme "mirror pattern" pour le futur `NarrativeStateMachine` (NSM).

L'agent ULTRATHINK Plan a identifié que **ce mirror est trompeur** car les deux state machines ont des sémantiques fondamentalement différentes :

| Aspect | BRS | NSM |
|--------|-----|-----|
| Key shape | `dict[(symbol, level_name), State]` | `dict[symbol, NarrativeStateSnapshot]` |
| Instances per symbol | N en parallèle (1 par niveau touché) | 1 (état narratif global) |
| Lifecycle | Instance per event (TOUCH → CANCEL/ENTRY → DISPOSE) | Persistent FSM 24/7 |
| Events emitted | Lifecycle terminal | Transitions sémantiques |
| Cooldown | Per (sym, level), 5 bars | N/A (time decay 4h ScenarioValidator) |
| Persistence | None native (dette connue, perd état au restart) | **OBLIGATOIRE** pickle atomic + recovery |

Risque : un développeur (ou agent) qui lit "mirror BRS" risque de copy-paste la structure clé `dict[(sym, level), ...]` au lieu de `dict[symbol, ...]`, cassant la sémantique NSM.

## Décision

NSM est **inspired by `CORE/live_enricher_state.py:LiveEnricherState`** (PAS BRS).

Caractéristiques `LiveEnricherState` à mirror :

1. **1 instance per symbol** : `dict[symbol, NarrativeStateSnapshot]`
2. **Pickle persistent** avec atomic write + recovery (à coder Phase 1)
3. **schema_version** : Pydantic v2 ou dataclass avec field `schema_version: str = "2.0.0"` pour backward compat futur
4. **threading.RLock par symbol** : concurrency safety multi-symbol parallèle
5. **engine_states dict extensible** : ajout nouveaux trackers (story trackers, plot twists) sans migration

Exemple structurel cible :

```python
# CORE/bot3_narrative_state_machine.py

@dataclass
class NarrativeStateSnapshot:
    schema_version: str = "2.0.0"
    symbol: str = ""
    state: NarrativeState = NarrativeState.PRE_OPEN_NEUTRAL
    state_entered_at_ts: Optional[str] = None
    state_entered_at_bar_idx: int = 0
    bias_dir: int = 0
    confidence: float = 0.0
    triggering_features: dict = field(default_factory=dict)
    expected_targets: list[str] = field(default_factory=list)
    invalidation_triggers: list[str] = field(default_factory=list)
    # Mirror LiveEnricherState : extensible sans migration
    engine_states: dict[str, Any] = field(default_factory=dict)


class NarrativeStateMachine:
    """1 instance per symbol, pickle persistent, schema_version'ed.

    Pattern reference : CORE/live_enricher_state.py LiveEnricherState.
    NOT BreakoutRetestStateMachine (different lifecycle).
    """

    def __init__(self):
        self._states: dict[str, NarrativeStateSnapshot] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._pending_events: list[NarrativeEvent] = []

    def _get_lock(self, symbol: str) -> threading.RLock:
        if symbol not in self._locks:
            self._locks[symbol] = threading.RLock()
        return self._locks[symbol]

    def transition(self, symbol: str, bar: dict, ctx: dict,
                   regime, story_trackers, swing_state) -> Optional[NarrativeStateSnapshot]:
        with self._get_lock(symbol):
            # ... transitions deterministes
            ...

    def current(self, symbol: str) -> Optional[NarrativeStateSnapshot]:
        return self._states.get(symbol)

    def consume_events(self) -> list[NarrativeEvent]:
        # Mirror pattern de bot3_breakout_retest.consume_events() OK ici
        evts, self._pending_events = self._pending_events, []
        return evts
```

## Pattern BRS reste utile partiellement

Le pattern **Events buffer + `consume_events()`** de BRS reste applicable pour NSM (publish events de transitions sémantiques consommables par mp_engine pour logging). Cf `bot3_breakout_retest.BreakoutRetestEvent` + `_pending_events` list + `consume_events()` swap pattern.

Ce qui ne mirror PAS BRS :
- Structure clé `_states`
- Lifecycle instance vs FSM persistent
- Cooldown
- Persistence

## Conséquences

### Positives
- Pattern correct dès Phase 1 = pas de refactor Phase 4
- Concurrency safety multi-symbol native
- Pickle persistence aligné convention existante (`LiveEnricherState`)
- schema_version = backward compat futur

### Négatives
- Léger surcoût mental pour le développeur (deux patterns à connaître : BRS partial + LiveEnricherState complet)
- Documentation explicite obligatoire dans docstring module

### Risques
- Si développeur ignore ADR : risque copy-paste BRS = bug architectural majeur
  - **Mitigation** : docstring module début explicite + tests Phase 1 valident shape `dict[symbol, ...]` (pas `dict[(sym, level), ...]`)

## Validation

Phase 1 review market-analyst doit vérifier :
- [ ] `_states` shape = `dict[symbol, NarrativeStateSnapshot]`
- [ ] `_locks` per symbol présent
- [ ] `schema_version` field présent dans snapshot
- [ ] `engine_states` extensible dict présent
- [ ] Tests `test_narrative_state_machine.py` valident concurrency multi-symbol (threading)

## Cross-references

- Module reference : `CORE/live_enricher_state.py`
- Module NOT-to-mirror (partial only) : `CORE/bot3_breakout_retest.py`
- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md` section "NSM pattern reference"

## Status courant

- [x] ADR accepté (Phase 0.5 J+0)
- [ ] Validation par market-analyst Phase 1 review
- [ ] Implementation conforme `CORE/bot3_narrative_state_machine.py` (Phase 1)
