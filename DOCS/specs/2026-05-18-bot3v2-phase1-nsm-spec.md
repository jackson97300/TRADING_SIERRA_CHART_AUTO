# Spec Phase 1 — `CORE/bot3_narrative_state_machine.py` (NSM)

**Date** : 2026-05-18
**Phase** : Bot 3 v2 Narrative Layer Phase 1 (Foundations TRACKING ONLY)
**Spec author** : Agent market-analyst ULTRATHINK (mode mentor adversarial)
**Reviewers** : Phase 1 review market-analyst + code-reviewer (Tier 1 cross-check)
**Verdict spec** : **4.20/5 GO-AVEC-RESERVES** (2 réserves à lever avant code)

---

## TL;DR

- **17 états** NarrativeState canon (Dalton Day Types + Wyckoff Phases C + ICT BOS)
- **32 transitions** déterministes table-driven (anti Pattern 11 composite hardcoded)
- **~650 LOC code** + **~460 LOC tests** (50+ tests pytest, coverage 90% cible)
- Mirror `LiveEnricherState` pattern (ADR 0002), NOT `BreakoutRetestStateMachine`
- Pickle persistence module séparé `bot3_narrative_persistence.py` (1 module 7 du plan)
- 8 codes log enregistrés `log_catalog.py`
- TRACKING ONLY Phase 1 = ZERO impact production Bot 3 v1

## 2 réserves à lever AVANT code NSM (Phase 1.5)

### Réserve #1 — `bot3_story_trackers.py` spec en parallèle
NSM consomme `story_trackers.hh_count_60`, `slope_close_60`, `bars_since_BOS`. Sans module 2 spec/code en parallèle, tests Phase 1 ne peuvent pas tourner.

**Action J+1 PM** : spec `bot3_story_trackers.py` avant code NSM (3-4h).

### Réserve #2 — Phase 1.5 mini-detour features manquantes live
Sanity check 18/05 a découvert 3 features ABSENTES du payload live mais PRÉSENTES dans batch parquet :
- `session_segment` (T1/T2/T3 transitions session-aware)
- `profile_shape` (T6/T7 OPEN_DRIVE detection Dalton)
- `cvd_session` (Wyckoff VSA effort-result)

Sans Phase 1.5, NSM transitions seraient cassées par fallback `None` = exactement Pattern 11 V1.

**Action J+1 AM** : porter ces 3 features live via `enricher_chain.py` (~3h).

Sera dropped : `bn_color_up_2` / `bn_color_dn_2` (absent batch ET live, jamais existé fonctionnellement).

---

## 17 États NarrativeState (Enum)

```python
class NarrativeState(Enum):
    # Pre-open (avant 09:30 ET)
    PRE_OPEN_BEARISH = "PRE_OPEN_BEARISH"
    PRE_OPEN_BULLISH = "PRE_OPEN_BULLISH"
    PRE_OPEN_NEUTRAL = "PRE_OPEN_NEUTRAL"

    # Dalton Open Types (RTH first hour 09:30-10:30 ET)
    OPEN_DRIVE_UP = "OPEN_DRIVE_UP"             # D1 OD_UP
    OPEN_DRIVE_DOWN = "OPEN_DRIVE_DOWN"          # D1 OD_DOWN
    OPEN_TEST_DRIVE = "OPEN_TEST_DRIVE"          # D2 OTD
    OPEN_ROTATION = "OPEN_ROTATION"              # D4 OA

    # Sessions établies (post-IB)
    TREND_UP_CONTINUATION = "TREND_UP_CONTINUATION"
    TREND_DOWN_CONTINUATION = "TREND_DOWN_CONTINUATION"
    RANGE_RESPECTED = "RANGE_RESPECTED"

    # Wyckoff Phase C (reversal setups)
    WYCKOFF_SPRING_LONG = "WYCKOFF_SPRING_LONG"
    WYCKOFF_UPTHRUST_SHORT = "WYCKOFF_UPTHRUST_SHORT"

    # ICT BOS confirmed
    BREAKDOWN_CONTINUATION = "BREAKDOWN_CONTINUATION"
    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"

    # Exhaustion / Terminal
    EXHAUSTION_TOP = "EXHAUSTION_TOP"
    EXHAUSTION_BOTTOM = "EXHAUSTION_BOTTOM"

    # Reset / error
    INVALIDATED = "INVALIDATED"
```

---

## 32 Transitions table (table-driven déterministe)

Format compact (LHS = formule features, RHS = next state). Premier match wins. Évaluation `with self._get_lock(symbol)`.

| # | From | Condition | To | Bias |
|---|------|-----------|----|----|
| T1 | * | session_date_trading changed + ctx.session=="ASIA" | PRE_OPEN_NEUTRAL | 0 |
| T2 | PRE_OPEN_NEUTRAL | session∈{ASIA,LONDON} + slope_60<-0.2 + asia_close<asia_open | PRE_OPEN_BEARISH | -1 |
| T3 | PRE_OPEN_NEUTRAL | session∈{ASIA,LONDON} + slope_60>+0.2 + asia_close>asia_open | PRE_OPEN_BULLISH | +1 |
| T4 | PRE_OPEN_BEARISH | slope_60 ∈ [-0.1,+0.1] | PRE_OPEN_NEUTRAL | 0 |
| T5 | PRE_OPEN_BULLISH | slope_60 ∈ [-0.1,+0.1] | PRE_OPEN_NEUTRAL | 0 |
| T6 | PRE_OPEN_* | session=="NY" + open_type==0 + close>open_cash+atr + vol_zscore_20>+1.0 | OPEN_DRIVE_UP | +1 |
| T7 | PRE_OPEN_* | session=="NY" + open_type==0 + close<open_cash-atr + vol_zscore_20>+1.0 | OPEN_DRIVE_DOWN | -1 |
| T8 | PRE_OPEN_* | session=="NY" + open_type==1 | OPEN_TEST_DRIVE | 0 |
| T9 | PRE_OPEN_* | session=="NY" + open_type==3 | OPEN_ROTATION | 0 |
| T10 | OPEN_DRIVE_UP | bar_idx_session>30 + story.hh_count_60>=3 | TREND_UP_CONTINUATION | +1 |
| T11 | OPEN_DRIVE_DOWN | bar_idx_session>30 + story.ll_count_60>=3 | TREND_DOWN_CONTINUATION | -1 |
| T12 | OPEN_DRIVE_UP | close<open_cash + vol_zscore_20<-0.5 | OPEN_ROTATION | 0 |
| T13 | OPEN_DRIVE_DOWN | close>open_cash + vol_zscore_20<-0.5 | OPEN_ROTATION | 0 |
| T14 | OPEN_TEST_DRIVE | bar_idx∈[5,15] + close>open_cash+0.5*atr + vol_zscore_20>+0.5 | OPEN_DRIVE_UP | +1 |
| T15 | OPEN_TEST_DRIVE | bar_idx∈[5,15] + close<open_cash-0.5*atr + vol_zscore_20>+0.5 | OPEN_DRIVE_DOWN | -1 |
| T16 | OPEN_TEST_DRIVE | bar_idx_session>15 | OPEN_ROTATION | 0 |
| T17 | OPEN_ROTATION | ib_complete + inside_value_area + ib_range/atr<1.2 | RANGE_RESPECTED | 0 |
| T18 | RANGE_RESPECTED | close>prev_vah + close[-1]>prev_vah | BREAKOUT_CONTINUATION | +1 |
| T19 | RANGE_RESPECTED | close<prev_val + close[-1]<prev_val | BREAKDOWN_CONTINUATION | -1 |
| T20 | TREND_UP_CONT | close<last_swing_low + close[-1]>=last_swing_low + vol_zscore>0 | BREAKDOWN_CONTINUATION (BOS) | -1 |
| T21 | TREND_DOWN_CONT | close>last_swing_high + close[-1]<=last_swing_high + vol_zscore>0 | BREAKOUT_CONTINUATION (BOS) | +1 |
| T22 | * (sauf INVAL) | low<=last_swing_low + close>last_swing_low+2*tick + vol_zscore>+1.5 + bars_since_BOS>5 | WYCKOFF_SPRING_LONG | +1 |
| T23 | * (sauf INVAL) | high>=last_swing_high + close<last_swing_high-2*tick + vol_zscore>+1.5 + bars_since_BOS>5 | WYCKOFF_UPTHRUST_SHORT | -1 |
| T24 | WYCKOFF_SPRING_LONG | next.close>last_swing_low+atr | TREND_UP_CONTINUATION | +1 |
| T25 | WYCKOFF_UPTHRUST_SHORT | next.close<last_swing_high-atr | TREND_DOWN_CONTINUATION | -1 |
| T26 | WYCKOFF_SPRING_LONG | next.close<last_swing_low-atr | INVALIDATED | 0 |
| T27 | WYCKOFF_UPTHRUST_SHORT | next.close>last_swing_high+atr | INVALIDATED | 0 |
| T28 | TREND_UP_CONT | vol_zscore_20>+2.5 + close<open + bar_range>2*atr | EXHAUSTION_TOP | -1 |
| T29 | TREND_DOWN_CONT | vol_zscore_20>+2.5 + close>open + bar_range>2*atr | EXHAUSTION_BOTTOM | +1 |
| T30 | EXHAUSTION_TOP | next.close<high-atr | INVALIDATED | 0 |
| T31 | EXHAUSTION_BOTTOM | next.close>low+atr | INVALIDATED | 0 |
| T32 | INVALIDATED | session_date_trading changed | PRE_OPEN_NEUTRAL | 0 |

**Anti-flicker** : `n_transitions_today > 8` → block + log `BOT3_NSM_FLICKER_GUARD` (anti Pattern 11 V1).

---

## Interfaces complètes (typings + docstrings Google)

### `NarrativeStateSnapshot` dataclass

```python
@dataclass(frozen=False)
class NarrativeStateSnapshot:
    schema_version: str = "2.0.0"
    symbol: str = ""
    state: NarrativeState = NarrativeState.PRE_OPEN_NEUTRAL
    state_entered_at_ts: Optional[str] = None
    state_entered_at_bar_idx: int = 0
    bar_idx_current: int = 0
    bias_dir: int = 0                       # -1/0/+1
    confidence: float = 0.0                  # [0.0, 1.0]
    triggering_features: dict[str, Any] = field(default_factory=dict)
    expected_targets: list[str] = field(default_factory=list)
    invalidation_triggers: list[str] = field(default_factory=list)
    engine_states: dict[str, Any] = field(default_factory=dict)
    n_transitions_today: int = 0
```

### `NarrativeEvent` dataclass

```python
@dataclass
class NarrativeEvent:
    event_type: str  # STATE_TRANSITION / SCENARIO_INVALIDATED / STATE_RESET_SESSION
    from_state: Optional[NarrativeState]
    to_state: NarrativeState
    bar_ts: str
    bar_idx: int
    symbol: str
    payload: dict[str, Any] = field(default_factory=dict)
```

### `NarrativeStateMachine` class

```python
class NarrativeStateMachine:
    def __init__(self) -> None:
        self._states: dict[str, NarrativeStateSnapshot] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._lock_creation_lock: threading.Lock = threading.Lock()
        self._pending_events: list[NarrativeEvent] = []

    def _get_lock(self, symbol: str) -> threading.RLock: ...
    def transition(self, symbol, bar, ctx, regime, story_trackers, swing_state) -> Optional[NarrativeStateSnapshot]: ...
    def current(self, symbol: str) -> Optional[NarrativeStateSnapshot]: ...
    def consume_events(self) -> list[NarrativeEvent]: ...
    def reset_session(self, symbol: str, new_session_date: str) -> None: ...
    def __getstate__(self) -> dict: ...  # exclude _locks
    def __setstate__(self, state: dict) -> None: ...  # recreate _locks
```

---

## 5 tests pytest obligatoires (squelette)

1. `test_initial_state_pre_open_neutral_cold_start` — cold start, snapshot None puis PRE_OPEN_NEUTRAL après 1ère transition
2. `test_transition_pre_open_to_open_drive_down` — T7 OPEN_DRIVE_DOWN avec NY open + open_type=0 + close<open_cash-atr + vol_zscore>+1.0
3. `test_concurrency_multi_symbol_no_race` — 2 threads ES+NQ workers 50 iter chacun, 0 race, 0 cross-pollution
4. `test_pickle_roundtrip_preserves_state` — pickle dump/load, `_locks` recreate, snapshot preserved
5. `test_events_consumed_once_then_empty` — `consume_events()` idempotent vide la liste

Plus 45+ tests additionnels par transition T1-T32 + edge cases.

**Total tests cible** : 50+, coverage 90%.

---

## 8 Codes log (CORE/log_catalog.py)

```python
"BOT3_NSM_STATE_TRANSITION":  (LogLevel.MAJEUR,   "decisions", "NSM transition : {sym} {from_state} -> {to_state} bias={bias_dir} conf={confidence:.2f} bar={bar_ts}"),
"BOT3_NSM_STATE_OBSERVE":     (LogLevel.INFO,     "decisions", "NSM observe : {sym} state={state} bar_idx={bar_idx} bars_in_state={bars_in_state}"),
"BOT3_NSM_INVALIDATED":       (LogLevel.CRITIQUE, "events",    "NSM scenario invalidated : {sym} from={from_state} trigger={trigger} bar={bar_ts}"),
"BOT3_NSM_FLICKER_GUARD":     (LogLevel.ALERTE,   "decisions", "NSM flicker guard : {sym} blocked transition n_transitions_today={n}"),
"BOT3_NSM_PERSIST_OK":        (LogLevel.INFO,     "events",    "NSM persist OK : symbols={symbols} n_events_flushed={n_events}"),
"BOT3_NSM_PERSIST_FAIL":      (LogLevel.MAJEUR,   "events",    "NSM persist FAIL : err={err}"),
"BOT3_NSM_PERSIST_RECOVERED": (LogLevel.ALERTE,   "events",    "NSM recovered fresh state apres corruption : {sym} reason={reason}"),
"BOT3_NSM_SESSION_RESET":     (LogLevel.INFO,     "events",    "NSM session reset : {sym} new_sdt={new_sdt} n_transitions_yesterday={n}"),
```

---

## Pickle persistence design

**Module dédié `CORE/bot3_narrative_persistence.py`** (module 7 du plan, ~120 LOC).

Architecture :
- Atomic write : `.pickle.tmp` puis `os.replace()` (POSIX atomic rename)
- Save interval : 60s (vs 5min enricher car NSM volatile)
- Path : `DATA/LIVE_CACHE/bot3_narrative/nsm_state.pickle`
- Schema check : `schema_version == "2.0.0"` au load
- Fail-safe recovery : si pickle corrompu, return None (NSM repart cold start + log `BOT3_NSM_PERSIST_RECOVERED`)
- `__getstate__` exclut `_locks` + `_lock_creation_lock`
- `__setstate__` recrée locks au load

Décision **PAS d'intégration dans `LiveEnricherState.engine_states["narrative_state_machine"]`** car :
1. Violation SRP (enricher = pure ingestion)
2. Bot 3 v2 lit payload V4 enriched MAIS exécute son propre NSM
3. Couplage croisé = nightmare migration

---

## Critère passage Phase 2 (mesurable)

Replay 5 jours (13-17/05) `databento_paper_trader_v2 --replay --narrative-tracking-only` :

1. Latence ajoutée NSM **< 5ms/bar médiane** (profiling cProfile p50/p95/p99)
2. **Diff `LOGS/decisions/*_paper_v2.jsonl` Phase 1 pre/post = 0** (TRACKING ONLY)
3. **≥4 transitions NSM par jour par symbole** (sinon FSM endormi)
4. **0 KeyError sur log_catalog** (8 codes enregistrés avant commit)
5. **Pickle recovery PASS** : kill -9 mid-replay → state recovered
6. **Coverage tests ≥ 90%** (pytest-cov Tier 1)
7. **0 transition EXHAUSTION_* sans vol_zscore > 2.5** (anti faux-positif)
8. **Bidirectional split** : ratio `bias_dir==-1` transitions ≥ 30% (anti biais structurel)

**Review agents Tier 1 cross-check** : market-analyst + code-reviewer. Verdict 4 dim moyenne ≥4.0 pour passage Phase 2.

---

## Sequencing Phase 1 (ordre obligatoire)

1. **J+1 AM (~3h)** : Phase 1.5 porter 3 features manquantes live (`session_segment` + `profile_shape` + `cvd_session`) via `enricher_chain.py`
2. **J+1 PM (~3-4h)** : Spec `bot3_story_trackers.py` (module 2) + spec replay tool
3. **J+2-3 (2 jours)** : Code NSM skeleton + 32 transitions + StoryTrackers + Persistence + Logging
4. **J+4** : Tests 50+ pytest + replay 5j 13-17/05 + profiling latence
5. **J+5** : Review market-analyst + code-reviewer (Tier 1 cross-check)
6. **Fin sem** : Commit Phase 1 complète + tag `bot3v2-phase1-complete-202605XX`

---

## Score 4 dimensions (auto-eval)

| Dim | Score | Justification |
|-----|-------|---------------|
| Méthodologie | 4.5/5 | 17 états canon Dalton+Wyckoff+ICT, citations chapitres précis, probabilistic Mark Douglas |
| Code Quality | 4.0/5 | Mirror LiveEnricherState, RLock per sym, table-driven anti Pattern 11, anti-flicker explicit |
| Empirique | 3.5/5 | 50+ tests squelette OK, mais replay 11j Bot 3 v1 baseline pas encore instrumenté |
| Trading Sense | 4.5/5 | Adresse 3 problèmes baseline : LONG bias 80% via mirror up/down, timeouts 46% via INVALIDATED/EXHAUSTION terminal exit, regime ignoré via NSM consomme regime.is_actionable |

**Score global** : `4.5×0.30 + 4.0×0.20 + 3.5×0.30 + 4.5×0.20 = 4.20` → **GO-AVEC-RESERVES**

Réserves levées avant code : Phase 1.5 + spec story_trackers.

---

## Cross-references

- Master plan : `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md`
- KB livres + modules : `DOCS/BOT3V2_KNOWLEDGE_BASE.md`
- ADR 0002 pattern : `DOCS/ADR/0002-nsm-pattern-reference-live-enricher-state.md`
- Baseline Bot 3 v1 : `DOCS/BOT3_V1_BASELINE_11D_20260518.md`
- Pattern reference code : `CORE/live_enricher_state.py:51-200`
- Pattern partial mirror : `CORE/bot3_breakout_retest.py:117-160`

## Status

- [x] Spec rédigée (agent market-analyst ULTRATHINK 4.20/5)
- [ ] Réserve #1 levée : spec `bot3_story_trackers.py` (J+1 PM)
- [ ] Réserve #2 levée : Phase 1.5 features manquantes live (J+1 AM)
- [ ] Code NSM (J+2-3)
- [ ] Tests + replay (J+4)
- [ ] Review agents Tier 1 (J+5)
- [ ] Commit Phase 1 + tag (fin semaine)
