# DESIGN DOC v2 — Phase 0 Preparation : Portage modules streaming vers `sierra_pipeline.py`

**Date** : 2026-06-11 (v2 post code-reviewer round 2)
**Auteur** : Orchestrateur Claude
**Statut** : DESIGN v2 — pending code-reviewer round 3 validation
**Reference v1** : `2026-06-11-sierra-pipeline-port-phase0-design.md`
**Reference review round 2** : GO-AVEC-RESERVES + 5 bloquants + 4 recommandes

---

## 1. Executive summary v2

### 1.1 Reponse aux 5 bloquants round 2

| # | Bloquant round 2 | Decision v2 | Effort impact |
|---|---|---|---|
| **B1** | Clarifier override STATE_DIR (option a/b/c) | **Option C**: re-implementer save/load Sierra-dedie dans nouveau `sierra_enricher_state.py` (~80 LOC, zero impact Databento) | -0h (deja budgete) |
| **B2** | Degradation VAP→trades aggreges (6-8 features impactees) | Classer `p99_trade_size`, `max_size_buy/sell` en **C3 categorie** (exclues drift harness). Documenter pour Bot 3 (`setup_engine.py`, `bot3_context_analyzer.py`, `bot3_snapshot_recorder.py` consument). | +30 min doc |
| **B3** | bn_score_* C++ bug vs Python recalcul | **Python recalcul** dans Phase 3. Confirmation C++ : `DMP_Transform.h:1414-1416` initialise a `0.0f` et N'UPDATE JAMAIS (placeholder). Modifier `_safe_update` avec whitelist `SIERRA_ZERO_NEVER_CALCULATED = ("bn_score_raw", "bn_score_bull", "bn_score_bear")` pour permettre override Python. | +1h code |
| **B4** | Audit consumers JSONL +200 cols | **Aucun risque** : 0 `schema_check` / `expected_cols` / `REQUIRED_COLS` trouve. Bots utilisent `row.get(...)` tolerant partout. Risque collision nom faible si nommage coherent enricher_chain. | -0h |
| **B5** | Decision game_changers porter OU skip | **PORTER** (revise apres challenge Jackson) : Sierra natif emet 9/9 game_changers a 100% set MAIS `trend_day_probability=0.0` constant 1512 bars + `open_direction=0` constant = signal placeholder/bug Sierra DMP (similaire bn_score_*). Top SHAP Bot 2 V5 utilise `open_type` → trader sur valeurs fausses = catastrophique. Ajouter au whitelist `_safe_update` Python override. | **0h** (pas d'economie) |

**Net effort B1-B5 (revise post-challenge Jackson)** : -0h + 30min + 1h + 0h + 0h = **+1h30** vs v1.

**Note importante** : v2 initial proposait SKIP B5 (-1h) mais Jackson a challenge "9 features constantes sur 1512 bars NQ pas normal".
Analyse empirique revisee : `trend_day_probability=0.0` strict 1512 bars + `open_direction=0` constant sont SUSPECTS (placeholder/bug Sierra DMP). PORTER avec whitelist override evite catastrophe Bot 2 V5 trade sur valeurs fausses.

### 1.2 Recommandes round 2 adresses

| # | Recommande | Action v2 |
|---|---|---|
| 6 | Tests 3h vs 1h | Phase 0 task 8 (tests pytest stubs) **re-budgete a 3h** au lieu de 1h |
| 7 | ml-trainer GO/NOGO | **Phase 4 ajoute** : `agent ml-trainer GO sur dataset enrichi Sierra-only 7j vs baseline Databento PF +/- 5%` |
| 8 | quality_validator.py GO/NOGO | **Condition GO 1.3 ajoutee** : "5 critères data-quality.md respectes (instrument-revealing, vol_NQ/vol_ES, prix absolu, outlier, quasi-constante)" |
| 9 | Test delta_bar parite | **Condition GO 1.3 ajoutee** : "signed_match >= 0.95 sur `delta_bar` Sierra vs Databento sur 7j" |

### 1.3 Effort revise final

| Phase | v1 design | v2 design (post-bloquants) |
|---|---|---|
| Phase 0 design + prep | 6h15 | **6h** (B5 -1h, tests +2h, B3 +30min, B2 +30min) |
| Phase 1 implementation | 18h30 | **~19h** (B3 +1h Python recalcul) |
| Phase 4 validation | non specifie | **+3h** (ml-trainer + quality_validator + delta_bar) |
| **TOTAL** | **24h45** | **~28h** sur 4-5 jours |

### 1.4 Criteres GO/NOGO finaux

**GO Phase 0 → Phase 1 SI** :
1. Design v2 valide par code-reviewer round 3 (zero piege architectural restant)
2. Harness parite differentielle implementee + scenario test stub PASS
3. Codes log_catalog merges (52 codes pre-enregistres)
4. Decisions arretees sur 5 bloquants (cf section 1.1)
5. Branche git `feat/sierra-pipeline-streaming-port` creee + procedure rollback documentee
6. **(NOUVEAU)** : 5 critères data-quality.md respectes sur sample Sierra v0
7. **(NOUVEAU)** : signed_match >= 0.95 sur `delta_bar` Sierra vs Databento sur 7j

---

## 2. Modules a porter (v2)

### 2.1 Liste revisee (12 modules au lieu de 13)

| # | Module | Action v2 | Features |
|---|---|---|---|
| 1 | `phase_b_helpers` | PORTER | cvd_session, sess_range_ticks, ovn_*, dist_pdh/pdl_atr |
| 2 | `phase_b_plus_long_streaming` | PORTER | bn_long_up/dn, bn_pressure_*, bn_score_* (avec whitelist B3) |
| 3 | `phase_b_plus_color_streaming` | PORTER | dist_color_up/dn_nearest_pct, n_color_*_cluster |
| 4 | `edge_zones_streaming` | PORTER | dist_edge_buy/sell_nearest_pct |
| 5 | `phase_b_plus_plus_delta_div_ext_streaming` | PORTER | dist_delta_div_*_nearest_atr |
| 6 | `rolling_features_streaming` | PORTER | poc_position, delta_div_*_clean, va_position_pct |
| 7 | `phase_b_plus_plus_big_v2_streaming` | PORTER | n_big_*_t1-t4, dist_big_*_nearest |
| 8 | `phase_b_plus_plus_cluster_v2_streaming` | PORTER | clusters volume |
| 9 | `phase_b_plus_plus_absorb_streaming` | PORTER | bn_absorb_* (deja partiel Sierra natif) |
| 10 | `phase_b_plus_plus_trapped_streaming` | PORTER | trapped traders |
| 11 | `rvol_streaming` | PORTER | rvol_* |
| 12 | `intermarket_streaming` | PORTER (avec callback partner_state_provider) | im_*, dist_intermarket_* |
| 13 | `game_changers_streaming` | **PORTER (revise B5)** avec whitelist `_safe_update` pour `trend_day_probability` + `open_direction` (Sierra placeholder bug suspect) | open_type, day_type, open_direction, trend_day_probability, rule_80pct, ma_trend |

### 2.2 Modules satellites Phase 0 prep

| Module | Action | LOC | Reference |
|---|---|---|---|
| `sierra_enricher_state.py` | NOUVEAU (Option C B1) | ~80 | Re-implementation save/load avec SIERRA_STATE_DIR dedie |
| `sierra_format_adapters.py` | NOUVEAU | ~200 | Conversions Sierra → Databento payload format |
| `sierra_vap_to_cells.py` | NOUVEAU | ~150 | Wrapper VAP → cells (accepte degradation C3 sur p99/max_size) |
| `sierra_databento_parity_harness.py` | NOUVEAU | ~250 | Harness parite differentielle |

---

## 3. Categorisation features pour harness parite (v2)

### 3.1 Categorie C1 - Identiques par construction (~280 features)

Seuil GO : drift mean abs < 5%, signed match > 95%.

Inclut : OHLCV, Sessions, Volume Profile, Rolling, ATR, distances ATR-norm, MQ distances, Regime, Roll, Wicks.

### 3.2 Categorie C2 - Sierra-only (acceptees)

Exclues du drift check.

Inclut : delta_bar Sierra natif convention saine, cvd_day, bn_absorb (DMP_Reader.h:1180-1189), n_big_*_t1-t4.

### 3.3 Categorie C3 - Databento-only / degradation acceptee (B2)

**NOUVEAU v2** : Features impactees par VAP→trades aggreges.

| Feature | Consumers | Impact | Decision v2 |
|---|---|---|---|
| `p99_trade_size` | `setup_engine.py:492`, `bot3_context_analyzer.py:206`, `bot3_snapshot_recorder.py:54` | Forte (10-100x ecart) | EXCLURE drift. Documenter pour Bot 3. |
| `max_size_buy/sell` | enricher_chain relais | Moyenne (5-50x ecart) | EXCLURE drift. |
| `aggressor_imbalance` | Bot3v4, BN V5 | DEJA proxy `aggressor_imbalance_proxy.py` deploye 11/06 | OK (deja propre semantique COUNT preserve) |
| `n_clusters` (Phase B+) | a verifier | Moyenne | EXCLURE drift jusqu'a verification |

### 3.4 Categorie C4 - Phase 3c (standard 5%)

Inclut : edge_zones, color_zones, rolling_features, atr_regime_zscore_60d, naked POC, roll, FFD.

---

## 4. State management Sierra (B1 - Option C details)

### 4.1 Module nouveau `CORE/sierra_enricher_state.py`

```python
# CORE/sierra_enricher_state.py (~80 LOC)
"""Sierra Enricher State : wrapper save/load avec STATE_DIR dedie.

Phase 0 Sierra Pipeline Port (11/06/2026).
Re-implemente save/load de live_enricher_state.py avec sous-dossier dedie
pour eviter collision avec Live-Enricher Databento prod.

Politique :
- Reutilise LiveEnricherState dataclass (heritage schema, anti-drift)
- Override SIERRA_STATE_DIR (different de STATE_DIR Databento)
- Detection collision : si load resout dans STATE_DIR Databento -> abort + emit CRITIQUE
"""
import pickle
import time
from pathlib import Path
from typing import Optional

from CORE.live_enricher_state import (
    LiveEnricherState, STATE_SCHEMA_VERSION, _emit_log,
)

ROOT = Path(__file__).resolve().parents[1]
SIERRA_STATE_DIR = ROOT / "DATA" / "LIVE_CACHE" / "enricher_state_sierra"
SIERRA_STATE_DIR.mkdir(parents=True, exist_ok=True)

# Detection collision : path Databento
DATABENTO_STATE_DIR = ROOT / "DATA" / "LIVE_CACHE" / "enricher_state"


def _sierra_state_path(symbol: str) -> Path:
    """Path snapshot Sierra dans sous-dossier dedie."""
    safe = symbol.replace("/", "_").replace(".", "_")
    return SIERRA_STATE_DIR / f"sierra_{safe}_state.pickle"


def save_sierra_state(state: LiveEnricherState) -> bool:
    """Mirror save_state Databento mais path Sierra-dedie."""
    path = _sierra_state_path(state.symbol)
    tmp = path.with_suffix(".pickle.tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        state.last_snapshot_ts = time.time()
        _emit_log("SIERRA_STATE_SNAPSHOT_OK", sym=state.symbol, ...)
        return True
    except (OSError, pickle.PickleError) as e:
        _emit_log("SIERRA_STATE_SNAPSHOT_FAIL", sym=state.symbol, err=str(e)[:200])
        return False


def load_sierra_state(symbol: str) -> Optional[LiveEnricherState]:
    """Mirror load_state Databento.
    
    + Detection collision : si fichier resout dans DATABENTO_STATE_DIR
    (probleme symlink ou path mistake) → abort + emit CRITIQUE.
    """
    path = _sierra_state_path(symbol)
    
    # Defense profondeur : valider que path est bien dans SIERRA_STATE_DIR
    if DATABENTO_STATE_DIR in path.resolve().parents:
        _emit_log("SIERRA_STATE_COLLISION_DETECTED", sym=symbol, path=str(path))
        return None
    
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
        # ... validation
        return state
    except Exception as e:
        _emit_log("SIERRA_STATE_LOAD_FAIL", sym=symbol, err=str(e)[:200])
        return None


def make_sierra_enricher_state(symbol: str) -> LiveEnricherState:
    """Factory : load existing OR create new Sierra-dedicated state."""
    state = load_sierra_state(symbol)
    if state is None:
        state = LiveEnricherState(symbol=symbol)
    return state
```

### 4.2 Avantages Option C

1. **Zero modif Databento prod** : `live_enricher_state.py` intact
2. **Schema partage** : reutilise dataclass parent, anti-drift
3. **Isolation totale** : SIERRA_STATE_DIR distinct
4. **Detection collision** : ajoute defense en profondeur

---

## 5. bn_score_* recalcul Python (B3)

### 5.1 Confirmation bug C++

`CPP/MIA_REFACTORED/DUMPER/DMP_Transform.h:1414-1416` :
```cpp
f.bn_score_bull = 0.0f;
f.bn_score_bear = 0.0f;
f.bn_score_raw  = 0.0f;
```

**Confirme** : C++ DMP initialise a 0 et n'update jamais. C'est un placeholder.

### 5.2 Modification `_safe_update`

```python
# CORE/sierra_pipeline.py
SIERRA_ZERO_NEVER_CALCULATED = (
    # B3 - bn_score_* placeholder C++ DMP_Transform.h:1414-1416
    "bn_score_raw", "bn_score_bull", "bn_score_bear",
    "bn_pressure_ask", "bn_pressure_bid",  # idem confirme cf NQ 1512 bars
    # B5 (revise post-Jackson) - game_changers suspects constants 1512 bars NQ
    "trend_day_probability",  # score [0,1] strictement 0 = placeholder Sierra DMP
    "open_direction",          # devrait varier vs open
)

@staticmethod
def _safe_update(enriched: dict, phase3_feats: dict) -> None:
    import math
    for k, phase3_v in phase3_feats.items():
        existing = enriched.get(k)
        is_p3_nan = (phase3_v is None or 
                     (isinstance(phase3_v, float) and math.isnan(phase3_v)))
        
        # B3 whitelist : Sierra=0.0 placeholder pour features jamais calculees C++
        # → permettre Python override
        if (k in SIERRA_ZERO_NEVER_CALCULATED 
            and existing == 0.0 
            and phase3_v is not None
            and not is_p3_nan):
            enriched[k] = phase3_v
            continue
        
        # Politique standard
        if is_p3_nan and existing is not None:
            continue
        enriched[k] = phase3_v
```

### 5.3 Python recalcul source

Module a importer en Phase 1 : `phase_b_plus_long_streaming` qui calcule probablement `bn_score_*` composites. A confirmer en lisant le source ; sinon ajouter formule custom dans Phase 3 :
```python
bn_score_raw = (bn_color_up - bn_color_dn 
                + bn_long_up - bn_long_dn 
                + bn_absorb_ask - bn_absorb_bid) / 6.0  # range [-1, +1]
bn_score_bull = max(0, bn_score_raw)
bn_score_bear = max(0, -bn_score_raw)
```

---

## 6. Checklist Phase 0 detaillee v2

| # | Tache | Effort v2 | Dependance |
|---|---|---|---|
| 1 | Brainstorm Jackson (workshop B1-B5 + bloquants residuels) | 1h00 | - |
| 2 | Specs `sierra_format_adapters.py` | 0h45 | 1 |
| 3 | Specs `sierra_enricher_state.py` (Option C B1) | 0h30 | 1 |
| 4 | Codes log_catalog : merger 52 codes | 0h30 | 1 |
| 5 | Specs harness parity (avec categorie C3 B2) | 0h45 | 2,3 |
| 6 | Tests pytest stubs 12 modules (3 min → 15 min/module avec fixtures complexes) | **3h00** | 5 |
| 7 | Doc sierra_pipeline.py mise a jour | 0h15 | 1 |
| 8 | CHANGELOG entry decisions B1-B5 | 0h15 | tous |
| 9 | Branch git + procedure rollback | 0h15 | tous |
| **TOTAL Phase 0 v2** | | **6h15** | |

---

## 7. Pre-mortem v2 : risques + mitigations

### 7.1 Risques residuels post-bloquants

| # | Risque v2 | Mitigation |
|---|---|---|
| R1 | bn_score_* Python formule != ce que Bot 2 BN V5 attendait | Harness parite check + agent ml-trainer GO/NOGO Phase 4 |
| R2 | SIERRA_STATE_DIR collision malgre Option C | Detection collision SIERRA_STATE_COLLISION_DETECTED CRITIQUE + assertion path validation |
| R3 | Intermarket callback ordre boot (race condition partner_state) | Mitigation Databento eprouvee : partner None → features NaN, log emit |
| R4 | VAP-proxy p99_trade_size biais Bot 3 | Documentation C3 + audit Bot 3 setup_engine.py impact AVANT cutover |
| R5 | game_changers Sierra natif change semantique Phase 1+ | Monitorer fire-rate post-RTH (rule_80pct, trend_day_probability) sur 7j |

### 7.2 Drill rollback complet

RTO < 15 min (inchange v1).

---

## 8. Plan implementation Phase 1+ (v2)

### 8.1 Order modules portage (PRIORITE B3 group ensemble)

**Group A (Phase 1.1 - 6h)** :
- phase_b_helpers (cvd_session)
- phase_b_plus_long_streaming (long + pressure + **bn_score** ensemble pour eviter drift)
- phase_b_plus_color_streaming
- phase_b_plus_plus_absorb_streaming

**Group B (Phase 1.2 - 4h)** :
- edge_zones_streaming (avec wrapper VAP cells)
- phase_b_plus_plus_delta_div_ext_streaming
- rolling_features_streaming

**Group C (Phase 1.3 - 5h)** :
- phase_b_plus_plus_big_v2_streaming
- phase_b_plus_plus_cluster_v2_streaming
- phase_b_plus_plus_trapped_streaming
- rvol_streaming

**Group D (Phase 1.4 - 4h)** :
- intermarket_streaming (registre callback)
- Tests integration end-to-end

**Total Phase 1 v2 : ~19h**.

### 8.2 Phase 4 validation (NOUVEAU)

- ml-trainer GO/NOGO PF +/- 5% Bot 1/2/3 sur 7j replay Sierra-only
- quality_validator.py 5 critères data-quality respectes
- delta_bar parite signed_match >= 0.95

**Total Phase 4 v2 : ~3h**.

---

## 9. Conclusion v2

### 9.1 Verdict apres adressage 5 bloquants

Design v2 adresse les 5 bloquants round 2 + integre 4 recommandes. Effort total revise : **~28h sur 4-5 jours** (vs 24h45 v1).

### 9.2 Demande au code-reviewer round 3

Verifier que :
1. Les 5 decisions B1-B5 sont coherentes et adresses les pieges
2. Aucun nouveau piege n'est introduit
3. Les criteres GO/NOGO 1-7 sont mesurables et stricts
4. Effort 28h sur 4-5 jours est realiste

**Si GO round 3** : commit Phase 0 implementation peut demarrer.
**Si NOGO round 3** : retour design avec corrections precises.
