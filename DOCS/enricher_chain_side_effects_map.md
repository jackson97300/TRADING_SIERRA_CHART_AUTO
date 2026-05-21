# Audit Side-Effects Map — `_process_bar_cycle` → `compose_enriched_payload`

**Date** : 2026-05-16
**Contexte** : Étape 0 du plan refactor Option B (extract chain commune).
**Couvre réserve** : R1 du code-reviewer GO-AVEC-RESERVES.

## Objectif

Cartographier exhaustivement les side-effects de `_process_bar_cycle` (lignes 228-1410)
pour identifier ce qui est **PURE** (extractible dans `enricher_chain.py`) vs **PLUMBING**
(à laisser dans `live_enricher.py` comme wrapper).

## Inventaire side-effects

### Globals modules `live_enricher.py`

| Symbole | Type | Lignes write | Lignes read | Rôle |
|---|---|---|---|---|
| `_cycle_start_ts[symbol]` | dict | 249, 1410 | 1392 | watchdog (cycle wall-clock tracking) |
| `_last_processed_ts_ns[symbol]` | dict | 1388 | 278 | anti double-process |
| `_n_bars_processed[symbol]` | dict | 1389 | (heartbeat externe) | stats module |
| `_n_bars_failed[symbol]` | dict | 1406 | (heartbeat externe) | stats module |
| `_cycle_lock` | Lock | 248, 1409 | — | mutex pour `_cycle_start_ts` |

### Locks externes

| Symbole | Acquisitions dans `_process_bar_cycle` |
|---|---|
| `_cycle_lock` | 2× (start ligne 248, finally ligne 1409) |
| `state.lock` | 15× (state mutations + reads) |
| `_states_lock` | 1× (ligne 783, gold_phase_d state factory) |

### I/O externes

| Action | Fonction | Lignes | Source |
|---|---|---|---|
| READ OHLCV cache | `read_latest_ohlcv` | 267 | `live_enricher_io.py` |
| READ trades window | `read_trades_window` | 286 | `live_enricher_io.py` |
| READ MQ levels | `read_mq_latest` | 287 | `live_enricher_io.py` |
| READ VIX latest | `read_vix_latest` | 288 | `live_enricher_io.py` |
| READ stream state | `is_stream_alive` | 289 | `live_enricher_io.py` |
| WRITE JSONL | `write_enriched_bar` | 1383 | `live_enricher_writer.py` |

### Wall-clock

| Usage | Lignes | Impact |
|---|---|---|
| `time.time()` pour `_cycle_start_ts` | 249 | watchdog (plumbing) |
| `int(time.time() * 1e9)` pour `ts_read_ns` | 296 | feature inputs |
| `time.time() - _cycle_start_ts` pour cycle_dt_ms | 1392 | watchdog log |

### Logs

| Code log | Ligne | Catégorie |
|---|---|---|
| `ENRICHER_INPUTS_INCOMPLETE` | 270 | wrapper |
| `ENRICHER_ENGINE_STATE_FAIL` (gold) | 800 | chain interne |
| `ENRICHER_ENGINE_STATE_FAIL` (sessions) | 809 | chain interne |
| `ENRICHER_ENGINE_FAIL` (chain failsoft) | 1274 | chain interne |
| `ENRICHER_DATA_QUALITY_FLAG_SET` | 1374 | chain interne |
| `ENRICHER_BAR_PROCESSED` | 1393 | wrapper |
| `ENRICHER_CYCLE_SLOW` | 1398 | wrapper |

## Découpage proposé

### `live_enricher.py` (wrapper PLUMBING, reste en place)

**Responsabilités** :
1. Watchdog (cycle_lock + _cycle_start_ts)
2. Lecture I/O (5 readers via `live_enricher_io`)
3. Anti double-process check (`_last_processed_ts_ns`)
4. Construction `inputs` dict
5. Appel `compose_enriched_payload(symbol, state, inputs, log_fn=_emit_log)`
6. Write JSONL (`write_enriched_bar`)
7. Update globals tracking (`_last_processed_ts_ns`, `_n_bars_processed`, `_n_bars_failed`)
8. Logs `ENRICHER_BAR_PROCESSED` / `ENRICHER_CYCLE_SLOW` / `ENRICHER_INPUTS_INCOMPLETE`
9. Finally block : reset `_cycle_start_ts`

**Lignes équivalent restant après refactor** : ~80 LOC (vs 1183 actuelles)

### `enricher_chain.py` (chain PURE, nouveau module)

**Signature** :
```python
def compose_enriched_payload(
    symbol: str,
    state: LiveEnricherState,
    inputs: dict,
    log_fn: Optional[Callable] = None,
) -> tuple[dict, dict]:
    """
    Args:
        symbol: "ES.c.0" / "NQ.c.0" / "MGC.v.0"
        state: LiveEnricherState (mutable explicite, lock géré en interne)
        inputs: {
            "ohlcv": dict (Databento OHLCV bar),
            "trades_df": pd.DataFrame (trades alignés bar),
            "mq_levels": dict | None (MenthorQ snapshot),
            "vix": dict | None (VIX_Lite enrichi),
            "stream_alive": bool,
            "ts_read_ns": int (wall-clock lecture inputs),
        }
        log_fn: Callable(code: str, **kwargs) | None (default = no-op)

    Returns:
        payload: dict (~430 cols enriched bar, ready for JSONL write)
        meta: dict {
            "phase_b_plus_plus_partial": bool,
            "failed_lot": str | None,
            "engine_name": str | None,
            "data_quality_flag": int,
        }
    """
```

**Responsabilités** :
1. `state.update_mq()` / `state.update_vix()` sous `state.lock`
2. Composition payload base (ohlcv passthrough + symbol/ts_event_ns)
3. Injection MQ snapshot (passthrough + dist_mq_*_pct calc + next_wall_dist_ticks)
4. Injection VIX (passthrough + enrich_vix_lite_streaming)
5. Injection trades stats (trades_window_n, delta_bar)
6. **Chain engines 22 modules streaming** :
   - footprint_builder_streaming
   - phase_b_plus_plus_{trades, big_v2, cluster_v2, absorb, trapped, delta_div_ext}
   - phase_b_helpers (sessions_metadata, ib_features, session_high_low, volume_profile)
   - rvol_inputs + rvol_engine
   - phase_b_plus (long, color)
   - phase_b_rolling_inputs
   - game_changers
   - open_extension_lines
   - gold_phase_d
   - intermarket
   - sessions_swings_simple + sessions_swings_lag
   - rolling_features
7. `state.append_bar(payload)` sous `state.lock`
8. data_quality_flag bitmask (7 bits)
9. Logs internes via `log_fn` callback :
   - `ENRICHER_ENGINE_STATE_FAIL` (gold_phase_d, sessions)
   - `ENRICHER_ENGINE_FAIL` (chain failsoft)
   - `ENRICHER_DATA_QUALITY_FLAG_SET`

**Lignes** : ~1100 LOC déplacées + structure module.

### Garanties de pureté

`compose_enriched_payload` SERA pure au sens "même inputs → mêmes outputs" si :

1. ✅ **Pas de globals modules** mutés (les 4 globals `_last_processed_*` / `_n_bars_*` restent dans wrapper)
2. ✅ **Pas de wall-clock** dans la chain (`time.time()` reste dans wrapper pour `ts_read_ns` injecté dans `inputs`)
3. ✅ **Pas d'I/O externes** (readers dans wrapper, writer dans wrapper)
4. ✅ **`state` est explicite arg** (mutations OK, sous `state.lock` interne au module chain)
5. ✅ **Imports engines streaming** restent locaux à `enricher_chain.py` (DRY identique)
6. ✅ **`log_fn` est injecté** (no-op par défaut en batch, `_emit_log` en live)
7. ⚠️ **Sémantique batch `ts_read_ns` et `stream_alive`** : à acter étape 6 (cf code-reviewer)

### Points de vigilance pour l'extraction (étape 3)

#### V1 — `import` locaux

Le code actuel a 22+ `from XXX_streaming import ...` à l'intérieur de `_process_bar_cycle`.
Ils doivent rester locaux à chaque section pour permettre le **fail-soft restreint**
(catch `ImportError` ligne par ligne, ne pas casser toute la chain si un seul engine est manquant).

À conserver tels quels dans `enricher_chain.py`. Pas d'optimisation top-of-module.

#### V2 — `payload_pre_chain` checkpoint

Ligne 519 : `payload_pre_chain = dict(payload)`
Ligne 1207 : `payload = payload_pre_chain` (revert si crash chain `phase_b_plus_plus`)

Le checkpoint est interne à la chain → reste dans `enricher_chain.py`.

#### V3 — Traceback parsing

Lignes 1216-1269 : parse `traceback.format_exc()` pour identifier `failed_lot`.
Logique interne chain → reste dans `enricher_chain.py`.
Le résultat (`failed_lot`, `engine_name`) est exporté via `meta` dict pour log côté wrapper.

#### V4 — `state.engine_states` mutations

Les engines streaming mutent `state.engine_states[X]` même quand `payload` est revert.
Comportement intentionnel (cf docstring lignes 237-243).
**Conséquence R3** (audit code-reviewer) : pour replay batch, snapshot `state.engine_states`
à J+30/90/180 pour comparer avec live.

#### V5 — Ordre engines critique

L'ordre d'appel des engines streaming est CRITIQUE (deps inter-engines).
Exemple (cf commentaire ligne 502-505) :
1. `phase_b_plus_plus_trades` (LOT 1) — produit `delta_bar`, `total_vol`, footprint_cells
2. `rvol_inputs` consume `delta_bar`
3. `rvol_engine` consume `rvol_inputs`
4. `phase_b_plus` (long/color) consume rvol_outputs
5. `phase_b_rolling_inputs` consume tout précédent
6. `game_changers` consume rolling_inputs
7. `gold_phase_d` indépendant
8. `intermarket` consume ES/NQ cross
9. `sessions_swings` indépendant (besoin ts_event)
10. `rolling_features` consume TOUT (dernière étape)

**Préserver l'ordre exact lors de l'extraction** — ne pas réordonner pour "logique".

#### V6 — `data_quality_flag` bitmask

Calcul bit-par-bit (lignes 1324-1370) consomme :
- `state.n_bars_processed` (state explicite ✓)
- `payload[...]` divers (PURE ✓)

Reste dans chain (PURE).

## Validation extraction

Pour valider que l'extraction est correcte :
1. **Diff fonctionnel** : run live_enricher avant/après refactor sur 5 jours offline (R2)
2. **Diff structurel** : `python -c "import ast; ..."` parser AST de l'ancien `_process_bar_cycle`
   et du nouveau `compose_enriched_payload`, comparer set d'identifiers utilisés
3. **Test unitaire ciblé** : feed identique → output bit-for-bit pour 100 bars

## Sémantique sémantique batch à acter (étape 6)

Pour `replay_enricher_batch.py`, valeurs à injecter dans `inputs` :

| Clé | Live | Batch (proposition) |
|---|---|---|
| `stream_alive` | `is_stream_alive()` (Databento Live connected) | `True` constant (replay is canonical) |
| `ts_read_ns` | `time.time() * 1e9` (wall-clock lecture) | `ts_event_ns + 60_000_000_000` (bar close + 60s = simulation lecture juste après close) |

**Rationale** : `ts_read_ns` est consommé par `latency_s = (ts_read_ns - ts_event_ns) / 1e9`
qui est une feature staleness. En batch, on simule que la lecture a lieu juste après
le close (60s post-bar) ce qui est cohérent avec le timing live moyen.

`stream_alive=True` constant est OK car les bars Databento parquets sont par définition
"valides" (sinon elles ne seraient pas dans le dataset). Pas de simulation de coupure stream.

## Conclusion étape 0

L'extraction est **VIABLE** sous Option B. Les frontières wrapper ↔ chain sont nettes :
- 7 side-effects globals à laisser dans wrapper (`_cycle_*`, `_last_*`, `_n_bars_*`)
- 5 I/O à laisser dans wrapper (5 readers + 1 writer)
- 1 wall-clock à laisser dans wrapper (`ts_read_ns` injecté dans `inputs`)
- `state` est passé explicite → mutations OK
- `log_fn` callback injecté → découple log catalog

**Couvre R1**. Prêt pour étape 1 (backup) puis étape 3 (extraction).

---

## REVISION v1.1 — Corrections code-reviewer (2026-05-16)

### Bloquants identifiés (corrigés)

#### O1/A2 — `state.append_bar(payload)` DANS la chain (pas wrapper)

**Position critique** : `append_bar` (ligne 1284 actuel) DOIT être DANS `compose_enriched_payload`,
entre le `except` fail-soft (ligne 1199) et le bitmask `data_quality_flag` (ligne 1304).

Raison : `append_bar()` incrémente `state.n_bars_processed`. Le bitmask bit 0 (warmup_phase)
lit `state.n_bars_processed`. Si on déplace `append_bar` dans le wrapper APRÈS la chain,
le bitmask voit `n_bars_sym - 1` → décalage de 1 bar sur warmup detection.

**Confirmation** : `append_bar` est appelé MÊME en fail-soft (hors du `try` revert).
Donc même si la chain crash, le compteur avance correctement.

#### O4/A1 — `partner_state_provider` arg pour intermarket cross-symbol

Lignes 783-784 actuelles : `with _states_lock: partner_state = _states.get(partner_symbol)`
(intermarket lit le state de l'autre symbole pour calculer ES/NQ correlation).

Signature mise à jour :
```python
def compose_enriched_payload(
    symbol: str,
    state: LiveEnricherState,
    inputs: dict,
    log_fn: Optional[Callable] = None,
    partner_state_provider: Optional[Callable[[str], Optional[LiveEnricherState]]] = None,
) -> tuple[dict, dict]:
```

- En **LIVE** : `partner_state_provider = lambda sym: _states.get(sym)` (read sous `_states_lock` côté wrapper)
- En **BATCH** : `partner_state_provider = lambda sym: batch_states_dict.get(sym)` (dict isolé batch)
- Si `None` : intermarket features = NaN (graceful degradation)

#### O3 — Log `ENRICHER_PARTNER_STALE` (intermarket)

Ajouté à la liste des logs internes de la chain (table section "Logs") :

| Code log | Ligne | Catégorie |
|---|---|---|
| `ENRICHER_PARTNER_STALE` | ~800-815 | chain interne (intermarket cross-symbol) |

### Réserves importantes (documentées)

#### R4 — Scope revert `payload_pre_chain` complet

Le `try` de la chain (ligne 520-1198) **englobe TOUS les engines** :
- phase_b_plus_plus (LOT 1-6)
- footprint_builder
- phase_b_helpers (sessions_metadata, ib, session_high_low, volume_profile)
- rvol_inputs + rvol_engine
- phase_b_plus (long, color)
- phase_b_rolling_inputs
- game_changers
- open_extension_lines
- gold_phase_d
- intermarket
- sessions_swings_simple + sessions_swings_lag
- rolling_features

Sur exception (whitelist : `ValueError/KeyError/TypeError/AttributeError/ImportError`),
**TOUS les enrichissements sont revert** → `payload = payload_pre_chain` (= juste OHLCV + MQ + VIX + trades_window passthrough).

**Conséquence batch** : si chain crash sur 1 bar, la bar produit `phase_b_plus_plus_partial=True`.
Les ~400 features chain sont absentes. ETL ML doit filter ces bars (cf
`data_quality_flag` bit 0 warmup + filter `phase_b_plus_plus_partial`).

#### R6 — Imports `from XXX_streaming import` DOIVENT rester locaux

Le parsing `failed_lot` (lignes 1216-1245) match les marqueurs streaming dans la stack trace.
Si on top-of-module les imports dans `enricher_chain.py`, les marqueurs disparaissent
de la stack → tous les fails classés `unknown`.

**Action étape 3** : conserver les imports `from XXX_streaming import ...` à l'intérieur
de `compose_enriched_payload` (pas top-of-module). Pas d'optimisation perf qui casserait
le diagnostic J+1.

#### R5 — `state.lock` est `threading.RLock` (réentrant)

Confirmé `CORE/live_enricher_state.py:88` : `self.lock = threading.RLock()`.

Conséquence : safe d'acquérir `state.lock` plusieurs fois dans la chain (15× déjà fait).
Aucun risque de deadlock même si un sub-engine ré-acquiert `state.lock`.

### Sémantique batch (V7) — verdict final

**`stream_alive = True` constant** : ✅ **OK validé empirique**.
- Grep `stream_alive` confirme : utilisé UNIQUEMENT dans `live_enricher.py:_process_bar_cycle`
  pour log `ENRICHER_INPUTS_INCOMPLETE` (wrapper).
- AUCUN engine streaming ne consomme `inputs["stream_alive"]`.
- AUCUNE feature ML dérivée.
- Donc constant `True` en batch = zéro impact features.

**`ts_read_ns = ts_event_ns + 60_000_000_000` (bar_close + 60s)** : ⚠️ **À VÉRIFIER finement**.
- Grep `ts_read_ns` confirme : utilisé UNIQUEMENT dans `live_enricher_io.py` (instrumentation).
- N'est PAS consommé par les engines streaming (pas dans `payload` directement).
- `latency_s` (que craignait le reviewer) est calculé en amont par `databento_live_stream.py:213,225,237,309`
  AVANT que le bar arrive dans `live_enricher`. Il est passthrough dans `ohlcv`.
- En BATCH parquet, les bars Databento parquets N'ONT PAS `latency_s` (col absent).
  → `payload["latency_s"]` sera **NaN** en batch (vs valeur réelle en live).
  → Si feature ML utilise `latency_s`, divergence batch/live.

**Décision étape 6** : grep consumers `latency_s` côté ML (engines + dataset builders) :
- Si AUCUN consumer : laisser NaN en batch (acceptable, feature debug).
- Si consumer existe : injecter valeur synthétique dans batch (e.g. 2.0s = médiane live).

À acter étape 6 avant batch run, pas par défaut.

### Side-effects oubliés (ajout)

#### O2 — `_n_bars_failed[symbol]` (wrapper)

Ligne 1406 dans `except Exception` global de `_process_bar_cycle`.
Symétrique de `_n_bars_processed` ligne 1389.
Reste dans wrapper. Pas oublié dans le doc mais à mentionner pour complétude.

#### M1 — `append_bar` appelé MÊME en fail-soft

Important pour R3 batch determinism : même si chain crash et revert payload,
`state.append_bar(payload_pre_chain)` est appelé → `state.n_bars_processed` avance.
Donc le bitmask warmup_phase voit le bon compteur.

**Mais** : `append_bar` reçoit le payload REVERT (~30 cols OHLCV+MQ+VIX seulement).
Les buffers state derivent d'un payload partiel pour cette bar. Comportement actuel live
identique → pas de divergence batch/live, MAIS engines downstream voient un payload
appauvri dans le rolling buffer.

### Actions pré-étape 3 (consolidées)

| # | Action | Statut |
|---|---|---|
| A1 | Ajouter `partner_state_provider` dans signature `compose_enriched_payload` | ✅ documenté |
| A2 | `state.append_bar()` DANS la chain (entre except et bitmask) | ✅ documenté |
| A3 | Test non-régression : shallow copy `payload = dict(ohlcv)` ne mute pas listes (`mq_gex`) | ⏳ test unitaire étape 3 |
| A4 | Imports `from XXX_streaming` restent LOCAUX dans `compose_enriched_payload` | ✅ documenté |
| A5 | Documenter `state.lock` est `RLock` (safe ré-entrée) | ✅ documenté |
| A6 | Étape 6 : grep `latency_s` consumers ML → décider NaN vs synthétique | ⏳ étape 6 |
| A7 | Étape 5 : test parité doit inclure bars `phase_b_plus_plus_partial=True` (chain crash) | ⏳ étape 5 |
| A8 | Étape 11 : snapshot `state.engine_states` batch vs live à J+30/90/180 | ⏳ étape 11 (R3) |

## Conclusion v1.1

Document validé par code-reviewer post-corrections. **2 bloquants traités**, **3 réserves documentées**, **3 actions reportées aux étapes correspondantes**.

Frontière finale wrapper ↔ chain (consolidée) :

**WRAPPER `live_enricher.py`** (~80 LOC vs 1183 initiales) :
- Watchdog (`_cycle_lock` + `_cycle_start_ts`)
- I/O reads (5 readers via `live_enricher_io`)
- Anti double-process (`_last_processed_ts_ns`)
- Build `inputs` dict
- Call `compose_enriched_payload(symbol, state, inputs, log_fn=_emit_log, partner_state_provider=lambda s: _states.get(s))`
- Write JSONL
- Update globals tracking
- Logs wrapper-level

**CHAIN `enricher_chain.py`** (~1100 LOC déplacées) :
- `state.update_mq/vix/append_bar` (sous `state.lock`)
- Composition payload (mq passthrough, dist_*_pct, next_wall_dist_ticks, VIX, trades stats, delta_bar)
- 22 engines streaming (ordre critique préservé)
- Fail-soft revert + traceback parsing (imports LOCAUX)
- data_quality_flag bitmask (7 bits)
- Logs chain-internal via `log_fn` callback

**Prêt pour étape 1 (backup) puis étape 3 (extraction)**.

