# DESIGN DOC — Phase 0 Preparation : Portage 13 modules streaming vers `sierra_pipeline.py`

**Date** : 2026-06-11
**Auteur** : Plan Agent (cross-check architectural)
**Statut** : DESIGN — pending code-reviewer validation round 2
**Cible review** : agent code-reviewer round 2 (a739376dbe4a6c2eb)

---

## 1. Executive summary

### 1.1 Verdict architecture

Le portage des ~13 modules streaming Phase B+/3c depuis `enricher_chain.py` (pipeline Databento prod) vers `sierra_pipeline.py` (pipeline Sierra DMP) est **techniquement faisable** mais necessite une **Phase 0 architecturale** de **6h15 effort planning** avant tout code, faute de quoi les 6 pieges identifies par le code-reviewer round 1 (`LiveEnricherState` manquant cote Sierra, `footprint_cells` absent, divergence format Databento/Sierra, ordre dependances modules, collision pickle, intermarket registre) se materialisent en cascade et reproduisent Pattern 11 V1 silent failures.

### 1.2 Effort revise par section

| Section | Effort design (h) | Effort impl Phase 1+ (h) |
|---|---|---|
| A. State management `SierraEnricherState` | 0h45 | 4h |
| B. Format conversions wrappers | 0h45 | 3h |
| C. Order modules / DAG | 0h30 | 2h |
| D. Intermarket registre | 0h30 | 3h |
| E. Snapshot pickle isolation | 0h15 | 0h30 |
| F. Codes log_catalog | 0h30 | 1h |
| G. Harness parite differentielle | 0h45 | 4h |
| H. Criteres GO/NOGO par module | 0h30 | 1h |
| I. Checklist Phase 0 ordonnee | 0h15 | n/a |
| J. Pre-mortem risques | 0h45 | n/a |
| **TOTAL** | **6h15** | **18h30** |

Total Phase 0 + implementation Phase 1 = **24h45** (compatible estimation reviewer 23-31h).

### 1.3 Criteres GO/NOGO globaux

**GO Phase 0 -> Phase 1 SI** :
1. Design valide par code-reviewer round 2 (zero piege architectural restant)
2. Harness parite differentielle implementee + scenario test stub PASS
3. Codes log_catalog merges (au moins 52 codes pre-enregistres)
4. Decision arretee sur intermarket (registre OU drop) + footprint_cells (VAP wrapper OU skip 4 modules)
5. Branche git dediee `feat/sierra-pipeline-streaming-port` creee + procedure rollback documentee

**NOGO** si une seule condition n'est pas satisfaite. Lopez : "edge prod intouchee tant que parite < 95% mean abs drift".

---

## 2. Decisions par section

## 2.A — State management : design `SierraEnricherState` lite

### A.1 Analyse `LiveEnricherState` existant

Source : `CORE/live_enricher_state.py:52-200` (@dataclass LiveEnricherState).

Composants critiques :
- `_bars_deque(maxlen=86400)` : 60j × 1440 bars 1-min
- `_trades_deque` : 3j de trades (purge cutoff_ns via popleft)
- `engine_states: dict[str, Any]` : state per-engine
- `mq_levels`, `vix_snapshot` : passthrough
- `_lock: threading.RLock` : thread-safety + exclu pickle via `__getstate__/__setstate__`
- Snapshot pickle : `STATE_DIR = ROOT/DATA/LIVE_CACHE/enricher_state/{sym}_state.pickle`
- `boot_ts`, `n_bars_processed`, `STATE_SCHEMA_VERSION = 1`

### A.2 Decision : REUTILISER `LiveEnricherState` + sous-dossier snapshot dedie

**Rationale chiffre** :

| Option | LOC | Risque | Maintenance | Reco |
|---|---|---|---|---|
| A. Reutiliser tel quel | 0 | Collision pickle | 1 fichier | NON |
| B. **Reutiliser + sous-dossier dedie + factory** | ~40 | Faible | 1 fichier | OUI |
| C. Creer `SierraEnricherState` distincte | ~250 (copy) | Drift schema | 2 fichiers | NON |
| D. Sous-classe heritage dataclass | ~80 | Pickle compat fragile | 2 fichiers | NON |

Choix : **B**. Factory `make_sierra_enricher_state(symbol)` dans `CORE/sierra_enricher_state.py` qui :
1. Instancie LiveEnricherState(symbol=symbol)
2. Override STATE_DIR via attribut classmethod
3. Ne touche PAS la classe parente

### A.3 Probleme trades_deque (Sierra DMP n'expose PAS trade-by-trade)

**Choix** : **Option C — porter `footprint_builder_streaming` modifie pour Sierra VAP -> cells (~150 LOC)**.

Sierra DMP via `sc.VolumeAtPriceForBars` C++ expose ASK/BID volume par prix = equivalent cells. Sans cells : ~30 features mortes. Avec cells : ~5 features mortes (`p99_trade_size`, aggressor exact).

Nouveau module Phase 1 : `CORE/sierra_vap_to_cells.py`. n_trades_proxy = round(total_vol / avg_trade_size).

### A.4 Snapshot interval

Reutiliser SNAPSHOT_INTERVAL_SEC = 300 (5 min).

---

## 2.B — Format conversions : wrappers Sierra -> Databento payload

### B.1 Tableau de conversions necessaires

| Champ Databento | Sierra emet | Conversion | Critique |
|---|---|---|---|
| ts_event_ns (int ns) | ts (int ms) | ts_ns = int(ts * 1e6) | OUI |
| ts_event (pd.Timestamp) | ts (int ms) | pd.Timestamp(ts, unit='ms', tz='UTC') | OUI |
| trades_df (DataFrame) | ABSENT (VAP) | Wrapper VAP -> cells + trades_df empty | OUI |
| mq_levels (dict) | mq_* aplaties | Construire dict | OUI |
| vix (dict enriched) | vix_* plats | Construire dict | NON |
| delta_bar convention | Sierra SAIN | Aucune (apres fix 07/06) | OUI |
| instrument_id | present | aucun | NON |
| open/high/low/close/volume | aliases OK | deja fait | NON |
| session_date_trading | direct | aucun | NON |

### B.2 Module a designer : `CORE/sierra_format_adapters.py`

API specifications (Phase 0) :
- `sierra_bar_to_databento_ohlcv(sierra_bar) -> dict`
- `sierra_bar_to_mq_levels(sierra_bar) -> dict | None`
- `sierra_bar_to_vix(sierra_bar) -> dict | None`
- `sierra_vap_to_trades_records(sierra_bar, tick) -> list[dict]`
- `sierra_inputs_to_enricher_inputs(sierra_bar, tick) -> dict` (composition)

### B.3 Convention delta_bar

Verifie : memes signes Sierra vs Databento post-fix 07/06. Aucune inversion. Test pytest `test_delta_bar_convention_match` obligatoire.

---

## 2.C — Order modules : Dependances et sequencement (DAG)

### C.1 DAG dependances

```
sierra_bar (380 cols) -> sierra_format_adapters -> inputs dict
                                                       |
                                                       v
              FORMAT-MERGE -> MQ snapshot -> VIX enrich
                                                       |
                                                       v
                           CHAINE STREAMING ordre CRITIQUE :

1. footprint_builder_streaming (cells depuis VAP-proxy)
2. LOT 1 phase_b_plus_plus_trades_streaming (delta_div, max/min)
3. proxies OFI + large_trader
4. Pass 4c-prereq : phase_b_helpers (sessions, ib, vol_profile, open_cash)
5. phase_b_plus_streaming (vwap_slope, cvd_day)
6. phase_b_plus_long_streaming (long_up/dn, bn_pressure, bn_score)
7. phase_b_rolling_inputs_streaming (24 features rolling)
8. game_changers_streaming (open_type, day_type)
9-13. LOT 2 (big_v2), LOT 3 (cluster_v2), LOT 4 (absorb), LOT 5 (trapped), LOT 6 (delta_div_ext)
14. intermarket_streaming (ES<->NQ)
15-16. sessions_swings_simple + lag
17. rvol_inputs + rvol_engine
18. rolling_features_streaming (basic+med+adv+div+conf)
19. Phase 3c-A: 17 features trivial/regime
20. Phase 3c-B: edge_zones + phase_b_plus_color
21. Phase 3c-C: atr_regime + naked POC + roll
22. data_quality_flag
23. state.append_bar(payload)
```

### C.2 Justification ordre critique

1. footprint_builder AVANT LOT 2/3/4/5 (consomment cells)
2. LOT 1 AVANT LOT 6 (delta_div outputs)
3. LOT 4 AVANT LOT 5 (near_resistance/support_level)
4. phase_b_helpers AVANT LOT 2-6 (dist_mq_*_pct, ib, sess)
5. phase_b_plus_long AVANT color (canonique long_dn_up_pattern)
6. **bn_score_*` ATTENTION : produit DOWNSTREAM par Bot 2 BN V5, mitigation = harness parite section G**
7. sessions_swings_simple AVANT lag
8. session = -1 recalcul APRES simple (bug V1 cousin 15/05)
9. rolling_features APRES tout le reste
10. Phase 3c en fin

### C.3 Modules a SKIP en Sierra V1

- `gold_phase_d_streaming` (MGC only, sierra_live_io.py SUPPORTED_SYMBOLS=("ES","NQ"))
- `intermarket_streaming` : decision section D

---

## 2.D — Intermarket registre : Cross-symbole thread-safe

### D.1 Decision : Option B — partner_state_provider callable injecte au constructeur

| Option | Complexite | Deadlock | Decoupling | Reco |
|---|---|---|---|---|
| A. Registre global thread-safe | Eleve | Eleve (lock global hot path) | Faible | NON |
| B. **Callback injecte au constructeur** | Faible | Faible | Eleve | OUI |
| C. Drop intermarket | Trivial | Nul | 10 features mortes Bot 2 V6 | NON |

### D.2 API design

```python
class SierraPipelineOrchestrator:
    def __init__(self, symbol, log_event=None,
                 partner_state_provider: Optional[Callable] = None,
                 state: Optional[LiveEnricherState] = None):
        self._partner_state_provider = partner_state_provider
        self._state = state or make_sierra_enricher_state(symbol)
```

### D.3 Caller multi-symbole

```python
states = {
    "ES.c.0": make_sierra_enricher_state("ES.c.0"),
    "NQ.c.0": make_sierra_enricher_state("NQ.c.0"),
}
def _provide(symbol): return states.get(symbol)

orch_es = SierraPipelineOrchestrator("ES", state=states["ES.c.0"], partner_state_provider=_provide)
orch_nq = SierraPipelineOrchestrator("NQ", state=states["NQ.c.0"], partner_state_provider=_provide)
```

### D.4 Locking + staleness check

Mirror enricher_chain.py:690-695 et 702-722. Reject si delta_ns > 120s ou partner_ts > target_ts.

---

## 2.E — Snapshot pickle : Eviter collision Live-Enricher Databento

### E.1 Analyse risque

Si meme STATE_DIR, snapshot Sierra ecrase Databento prod. CATASTROPHIQUE.

### E.2 Decision : Option 1 — Sous-dossier dedie

`SIERRA_STATE_DIR = ROOT / "DATA" / "LIVE_CACHE" / "enricher_state_sierra"`

### E.3 Detection collision (defense profondeur)

Si load resout dans dossier Databento -> emit `SIERRA_STATE_COLLISION_DETECTED` CRITIQUE + abort.

---

## 2.F — Codes log_catalog : 52 codes a pre-enregistrer

### F.1 Convention

`SIERRA_PORT_{MODULE}_{OK|FAIL|DEGRADED}` pour 13 modules = 39 codes
+ 13 codes meta (state, format, harness)

### F.2 Liste complete (52 codes)

**Per-module (39)** :
- SIERRA_PORT_FOOTPRINT_BUILDER_OK/FAIL/DEGRADED
- SIERRA_PORT_LOT1_TRADES_OK/FAIL/DEGRADED
- SIERRA_PORT_LOT2_BIG_V2_OK/FAIL/DEGRADED
- SIERRA_PORT_LOT3_CLUSTER_V2_OK/FAIL/DEGRADED
- SIERRA_PORT_LOT4_ABSORB_OK/FAIL/DEGRADED
- SIERRA_PORT_LOT5_TRAPPED_OK/FAIL/DEGRADED
- SIERRA_PORT_LOT6_DELTA_DIV_EXT_OK/FAIL/DEGRADED
- SIERRA_PORT_PHASE_B_HELPERS_OK/FAIL/DEGRADED
- SIERRA_PORT_PHASE_B_PLUS_OK/FAIL/DEGRADED
- SIERRA_PORT_PHASE_B_PLUS_LONG_OK/FAIL/DEGRADED
- SIERRA_PORT_PHASE_B_ROLLING_INPUTS_OK/FAIL/DEGRADED
- SIERRA_PORT_GAME_CHANGERS_OK/FAIL/DEGRADED
- SIERRA_PORT_RVOL_OK/FAIL/DEGRADED
- SIERRA_PORT_ROLLING_FEATURES_OK/FAIL/DEGRADED
- SIERRA_PORT_EDGE_ZONES_OK/FAIL/DEGRADED
- SIERRA_PORT_COLOR_BARS_OK/FAIL/DEGRADED
- SIERRA_PORT_INTERMARKET_OK/FAIL/DEGRADED
- SIERRA_PORT_SESSIONS_SIMPLE_OK/FAIL/DEGRADED
- SIERRA_PORT_SESSIONS_LAG_OK/FAIL/DEGRADED

**Meta codes (13)** :
- SIERRA_STATE_SNAPSHOT_OK/FAIL
- SIERRA_STATE_LOAD_FAIL
- SIERRA_STATE_SCHEMA_MISMATCH
- SIERRA_STATE_COLLISION_DETECTED (CRITIQUE)
- SIERRA_FORMAT_ADAPTER_OK
- SIERRA_FORMAT_ADAPTER_DROPPED
- SIERRA_FORMAT_TS_INCONSISTENT
- SIERRA_VAP_TO_CELLS_OK/EMPTY
- SIERRA_INTERMARKET_PARTNER_MISSING/STALE
- SIERRA_HARNESS_DRIFT_DETECTED

---

## 2.G — Harness parite differentielle

### G.1 Architecture

Module `CORE/sierra_databento_parity_harness.py` (~250 LOC) :
1. Input : 1 jour ES+NQ
   - Sierra : DATA/{SYM}/{YYYYMMDD}_{SYM}.jsonl
   - Databento : DATA_BACKTEST/databento_{date}_{sym}.parquet
2. Process : 2 voies (Live-Enricher Databento + Sierra-Enricher) -> 2 JSONL
3. Compare bar-par-bar par feature
4. Output : Markdown drift report

### G.2 Categorisation features

- **C1 identiques (~280)** : OHLCV, Sessions, Volume Profile, Rolling, ATR, distances ATR-norm, MQ distances, Regime, Roll, Wicks. Seuil drift mean abs < 5%
- **C2 Sierra-only (acceptees)** : delta_bar Sierra natif, cvd_day, bn_absorb, n_big_*. Exclues
- **C3 Databento-only** : p99_trade_size exact, max_size_buy/sell. Exclues si VAP-proxy
- **C4 Phase 3c** : standard 5%

### G.3 Seuils GO/NOGO

| Categorie | Drift mean abs | Bars KO | Action |
|---|---|---|---|
| C1 OHLCV exact | 0% | 0 | NOGO si != |
| C1 derivees | 2% | <5% bars | ALERTE |
| C1 derivees | 5% | <10% bars | NOGO |
| C1 signed | match >95% | n/a | NOGO si <95% |

### G.4 Pytest fixture

```python
def test_parity_es_20260610():
    report = run_parity_harness("ES", date="2026-06-10")
    assert report.c1_pass_rate >= 0.95
    assert "delta_bar" in report.signed_match_features
    assert report.signed_match["delta_bar"] >= 0.95
```

---

## 2.H — Criteres GO/NOGO par module

19 modules avec seuils :
- Fire-rate empirique > seuil (varies)
- 0 NaN incompressible sur features deterministes
- Pytest unitaire pass
- Backtest replay Bot consume 7j : PF ±5%, Sharpe ±10%
- Agent code-reviewer GO

Voir tableau detaille section 2.H du Plan agent original.

---

## 2.I — Plan Phase 0 detaille : Checklist ordonnee

| # | Tache | Effort | Dependance |
|---|---|---|---|
| 1 | Lire ce design + brainstorm Jackson | 1h00 | - |
| 2 | Specs `sierra_format_adapters.py` | 0h45 | 1 |
| 3 | Specs `make_sierra_enricher_state` | 0h30 | 1 |
| 4 | Decision intermarket (workshop) | 0h30 | 1 |
| 5 | Decision footprint_cells (workshop) | 0h30 | 1 |
| 6 | Codes log_catalog 52 codes | 0h30 | 1 |
| 7 | Specs harness parity | 0h45 | 2,3,4,5 |
| 8 | Tests pytest stubs 19 modules | 1h00 | 7 |
| 9 | Doc sierra_pipeline.py | 0h15 | 1 |
| 10 | CHANGELOG entry | 0h15 | tous |
| 11 | Branch git + procedure rollback | 0h15 | tous |
| **TOTAL Phase 0** | | **6h15** | |

### I.2 Parallelisme

- Sequentiel : 1 -> 2,3
- Workshop : 4, 5
- Parallele : 6 || 7 || 9
- Sequentiel : 8 APRES 7
- Final : 10, 11

---

## 2.J — Pre-mortem risques + mitigations

10 risques identifies, top 5 :

| # | Risque | Prob | Impact | Detection | Mitigation | Rollback |
|---|---|---|---|---|---|---|
| R1 | bn_score_* change semantique Bot 2 V5 | Moyenne | CRITIQUE | Harness C1 + backtest 7j | G + ordre C.6 | Revert branch |
| R2 | Pickle Sierra ecrit dossier Databento | Faible | CRITIQUE | SIERRA_STATE_COLLISION | Section E | Restore pickle backup |
| R3 | Intermarket deadlock | Moyenne | MAJEUR | Heartbeat slow | Callback (pas global) | Killer thread |
| R4 | ts ms vs ns silent NaN | Moyenne | MAJEUR | TS_INCONSISTENT | Assertion B.2 | Hotfix |
| R5 | LOT 5 trapped crash cascade | Faible | MAJEUR | TRAPPED_FAIL | Mirror revert pattern | Marker partial |

### J.2 Drill rollback complet

RTO < 15 min :
1. git checkout main (revert branche)
2. Verifier `DATA/LIVE_CACHE/enricher_state/{sym}_state.pickle` Databento intact
3. Restart Databento Live-Enricher
4. Backtest 1h Bot 2 paper -> PF == baseline
5. Post-mortem RCA Discord + INCIDENT_LOG

---

## 3. Plan rollback si Phase 0 echoue

### 3.1 Echec design Phase 0

Workshop tasks 4-5 bloque : fallback drop intermarket + LOT 2-5 (-50 features) -> 15h total au lieu de 24h.

### 3.2 Echec harness parite

C1 pass rate < 80% : Sierra-Enricher "experimental" shadow + ML continue Databento jusqu'a parite 95%.

### 3.3 Echec acceptation reviewer

NOGO reviewer round 2 : reuvrir Phase 0 design avec pieges identifies. Pas de deploy.

---

## 4. Annexes

### 4.1 Fichiers references

- CORE/sierra_pipeline.py
- CORE/enricher_chain.py
- CORE/live_enricher_state.py
- CORE/log_catalog.py
- CORE/sierra_live_io.py
- CORE/footprint_builder_streaming.py
- CORE/intermarket_streaming.py

### 4.2 Modules a CREER Phase 1

- CORE/sierra_enricher_state.py (~80 LOC)
- CORE/sierra_format_adapters.py (~200 LOC)
- CORE/sierra_vap_to_cells.py (~150 LOC)
- CORE/sierra_databento_parity_harness.py (~250 LOC)
- tests/sierra_port/test_*.py (~600 LOC)

---

## 5. Conclusion

### 5.1 Verdict global

Phase 0 PREPARATION de **6h15** valide architecturalement le portage. Les 6 pieges du code-reviewer round 1 sont resolus en amont :
- A : `make_sierra_enricher_state` + SIERRA_STATE_DIR dedie (resout 1, 5)
- B : `sierra_format_adapters.py` (resout 3)
- A.3 : VAP -> cells wrapper (resout 2 partiel, accepte degradation p99_trade_size)
- C : DAG ordre explicite (resout 4)
- D : partner_state_provider callback (resout 6)

### 5.2 Recommandation finale

**GO** pour Phase 0 implementation 11 taches checklist. Effort 6h15. Apres Phase 0 GO, Phase 1 (~18h30) demarre.

### 5.3 Prochaine etape

Workshop Jackson sur tasks 4-5 (intermarket + footprint). Puis Phase 0 execution parallele 1 journee.
