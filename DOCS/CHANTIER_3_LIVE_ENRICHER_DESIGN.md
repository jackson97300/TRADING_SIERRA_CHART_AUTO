# Chantier 3 — Live Enricher Streaming (Design Doc)

**Date** : 2026-05-13 nuit
**Statut** : DESIGN, validation Plan agent requise avant impl
**Estimation** : 1-2 semaines selon option retenue

## Contexte stratégique

Migration Bot 2 V6 à 100% Databento. Etat actuel post-Chantier 2 (13/05/2026) :

- VIX_Lite C++ + Python : OPERATIONNEL (commit 406cc7f + 76373be)
- Phase 1b GROUPE A : 5 features Python validees (commit 712d2ce + 33df029)
- Chantier 2 Trades buffer rolling : OPERATIONNEL VPS (commit bd9b323)
- Tous les engines Python existent et sont chaines par `apply_all_engines()` dans
  `CORE/build_dataset_v4_phase_b.py:351` (~13 engines, ~460 features)

But Chantier 3 : produire `DATA/live_enriched/{sym}/YYYYMMDD.jsonl` en STREAMING
(1 ligne/min) avec ~460 features, equivalent au DMP C++ snapshot complet mais
calcule a 100% en Python depuis Databento Live + Sierra MQ_Lite/VIX_Lite.

## Inputs disponibles (tous OPERATIONNELS)

| Source | Path | Cadence | Lag |
|---|---|---|---|
| Databento Live OHLCV-1m | `DATA/LIVE_CACHE/{sym}_last.json` | 1/min | <60s |
| Databento Live Trades | `DATA/LIVE_CACHE/trades/{sym}/{YYYYMMDD}.jsonl` | ~100/sec | <5s (Chantier 2) |
| Sierra MQ_Lite niveaux | `DATA/mq_levels/{ES,NQ,GC}/year=*/month=*/day=*/levels.jsonl` | 1-2/jour | <60s (change-detect) |
| Sierra VIX_Lite | `DATA/vix_levels/year=*/month=*/day=*/vix.jsonl` | 1/min | <60s |
| Databento Historical (pour backfill 60j initial) | `DATA/databento/GLBX.MDP3/...` | - | 20-35min |

## Output cible

```
DATA/live_enriched/{sym}/{YYYYMMDD}.jsonl
  - 1 ligne JSONL par cloture bar 1-min
  - Schema : ~460 features (alignees build_dataset_v4_phase_b output)
  - Append-only, rotation quotidienne
  - Retention : 60 jours (volume ~5KB/bar x 1440/jour x 60 = ~430 MB par sym)
```

## Contrainte perf

**Bench reel** apply_phase_b_plus (1 engine sur 13) :
- Window 1 jour (1440 bars) : 384 ms
- Window 3 jours (4320 bars) : 868 ms (linaire)

**Estimation totale** apply_all_engines (13 engines) :
- 1 jour buffer : ~5s/cycle
- 3 jours buffer : ~11s/cycle (probablement trop lent en streaming)
- 30 jours buffer : ~50s/cycle (INACCEPTABLE)

Cible streaming : **<10s par cycle** (sinon backlog cumule jusqu'a saturation).

## 4 options architecturales

### Option A — Naïf, window 1 jour
- Buffer in-memory : 1440 bars + trades 1 jour
- A chaque close : append nouvelle bar + appel `apply_all_engines(window_1j, trades_1j)`
- Latence : ~5s/cycle
- Effort : 1 semaine (impl + tests + deploy)
- **CON** : perd contexte 60j pour features rolling longues (ATR daily Wilder,
  market_profile_rolling, VPOC running, sessions_swings 30j historiques)

### Option B — Naïf, window 3 jours
- Buffer in-memory : 3 jours bars + trades
- Latence : ~11s/cycle (limite tight pour 1-min)
- Effort : 1 semaine
- **CON** : meme limite contexte long-terme, perf marginal

### Option C — Hybride streaming + snapshot quotidien
- Buffer in-memory : 3 jours bars + trades (streaming court)
- Snapshot 60j sur disque, refresh 1x/jour (00:00 UTC ou 17:00 ET CME open)
- A chaque close streaming : appel `apply_all_engines(buffer_3j, trades_3j)`
- Pour features rolling longues : merge avec colonnes snapshot 60j
- Latence streaming : ~3-5s/cycle (buffer 1j + colonnes pre-calc snapshot)
- Effort : 2 semaines
- **PRO** : meilleur compromis perf/completness
- **CON** : complexite split logic (quelles features viennent du snapshot vs streaming)

### Option D — Engines streaming-aware (refacto profond)
- Adapter chaque engine pour mode incremental :
  - `apply_phase_b_helpers(df_new_bar, state)` -> retourne nouvelle bar enrichie + state update
  - Maintenir state in-memory (rolling windows ATR, VPOC running, etc.)
- Latence : <500ms/cycle (calcul juste la derniere bar)
- Effort : 3-4 semaines (refacto 13 engines + tests parite)
- **PRO** : perf optimale, pas de window limit
- **CON** : refacto invasive 13 modules, double maintenance batch vs stream

## Decision Jackson 13/05/2026 nuit : **OPTION D — solution long terme**

Choix confirme : "on n'est pas presses, on fait les choses bien". Pattern aligne
[[feedback_no_quick_fixes]] : pas de solution rapide a refaire plus tard.

### Avantages Option D vs C
- Perf optimale (<500ms/cycle = marge enorme sous 60s, scale 3 syms + futurs)
- Pas de double maintenance batch+stream (engines stream-aware utilisables en batch)
- Architecture clean, scalable (ajout future symbol/feature = pas de refacto)
- Une fois pour toutes (pas Phase 3b a faire dans 2 semaines)

### Risques Option D + mitigation
- Refacto invasive 13 modules -> 3-4 sem effort
  Mitigation : refacto 1 engine a la fois + tests parite apres chaque
- Pattern 11 risk si bacle
  Mitigation : agents code-reviewer + tests parite strict batch vs stream
- Drift Python vs build_dataset_v4_phase_b si engines modifies en parallele
  Mitigation : garder API batch retro-compatible (chaque engine expose
  `apply_full(df)` ET `apply_streaming(df_new_bar, state)`)

## Phasing Option D — 4 semaines

### Phase 3a (Semaine 1) — Infrastructure + 3 engines simples

**Livrables** :
- `CORE/live_enricher.py` : service principal (callback close bar)
- `CORE/live_enricher_state.py` : state manager (buffer in-memory rolling + persisted)
- `CORE/live_enricher_io.py` : read inputs (OHLCV cache, Trades buffer, MQ, VIX)
- `CORE/live_enricher_writer.py` : write output JSONL atomic + rotation
- Tests parite engine-by-engine (batch output == streaming output)

**3 engines refactorises (les plus simples, deja stream-friendly)** :
1. `game_changers.py` : `apply_streaming(row, state)` - daily groupby simple
2. `phase_b_v6_complete.py` : deja stream-friendly (functions add_*)
3. `vix_lite_reader.py` : deja stream-friendly (loader + enrich row-by-row)

### Phase 3b (Semaine 2) — 5 engines moyens

**Engines refactorises** :
4. `phase_b_helpers.py` : sessions metadata, IB, sess HL, volume_profile, rvol_inputs
5. `phase_b_rolling_inputs.py` : ATR, VWAP slope, IB derives, CVD momentum, VPOC derives
6. `phase_b_plus_engine.py` : Color, Long, OVN, Opens, News (mostly row-level)
7. `sessions_swings_engine.py` : swing detection (rolling window stream-aware)
8. `phase_d_dalton_levels.py` : pVWAP, naked POC, single prints, excess

### Phase 3c (Semaine 3) — 3 engines complexes (footprint-based)

**Engines refactorises** :
9. `footprint_builder.py` : `build_footprint_per_bar` -> streaming `update_footprint(bar, trades)`
10. `phase_b_plus_plus_engine.py` : BIG orders, STACK, DELTA_DIV, TRAPPED, CLUSTER, ABSORPTION
11. `edge_zones_engine.py` : `apply_edge_zones` stream-aware

### Phase 3d (Semaine 4) — Finalisation + Deploy

**Engines finaux** :
12. `market_profile_rolling.py` : ctx_* features (running VPOC/VA/range)
13. `vwap_diff` + `option_c_plus_transforms` : trivial row-level
14. `regime_engine_v6.py` : deja row-by-row, juste cabler

**Validation** :
- Shadow run 7 jours : `DATA/live_enriched/` vs V4 batch parquet
- Critere parite : <0.001 diff par feature continue, 100% match boolean
- Audit code-reviewer + ml-trainer global Chantier 3

**Deploy** :
- nssm service `MIA-Live-Enricher` (24/7 VPS)
- Bot 2 V6 adapte pour lire `DATA/live_enriched/` au lieu de V4 parquet stale
- DMP JSONL devient legacy (cutover progressif Chantier 4 futur)

## Convention API streaming engines

Pour chaque engine refactorise, exposer 2 APIs :

```python
# API BATCH (retro-compatible, pour build_dataset_v4_phase_b.py)
def apply_phase_b_plus(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """Process tout df en mode batch (1 pass) - usage build_v4 historique."""
    state = PhaseBPlusState()
    for i, row in df.iterrows():
        df.loc[i, ...] = apply_phase_b_plus_streaming(row, state, symbol)
    return df

# API STREAMING (nouveau, pour MIA-Live-Enricher)
@dataclass
class PhaseBPlusState:
    """Rolling state minimal (last N bars, EMA, anchored counts)."""
    vwap_anchor: float = 0.0
    color_streak: int = 0
    # ...

def apply_phase_b_plus_streaming(row: dict, state: PhaseBPlusState, symbol: str) -> dict:
    """Process 1 nouvelle bar, update state, return enriched row."""
    # logique engine sur 1 ligne + state
    return enriched_row
```

**DRY** : la fonction batch APPELLE la fonction streaming dans une boucle.
Zero divergence garantie batch vs stream.

## Tests parite obligatoires

Apres chaque engine refactorise, lancer test :

```python
# tools/test_engine_parity_{engine_name}.py
df_v4 = load_parquet_v4()  # batch baseline
state = EngineState()
df_stream = pd.DataFrame()
for i, row in df_v4.iterrows():
    enriched = apply_streaming(row, state)
    df_stream.loc[i] = enriched
# Compare
diff = (df_v4[engine_cols] - df_stream[engine_cols]).abs()
assert diff.max().max() < 0.001, "PARITE VIOLATION"
```

Critere : <0.001 diff par feature continue, 100% match boolean/categorial.

## Schema output `live_enriched_1.0`

Identique au schema parquet V4 enriched mais format JSONL (1 ligne/bar) :

```json
{
  "ts_event": "2026-05-13T13:14:00Z",
  "symbol": "ES.c.0",
  "schema_version": "live_enriched_1.0",

  // OHLCV (5 features)
  "open": 5847.25, "high": 5849.50, "low": 5846.00, "close": 5848.75, "volume": 1234,

  // Trades aggregate (50 features)
  "delta_bar": 145, "cvd_session": 12450, "buy_vol": 689, "sell_vol": 544,
  "n_trades": 287, "avg_trade_size": 4.30, ...

  // Engines Python phase_b_* (370 features)
  "range_pos": 67.8, "vwap_d_side": 1, "vwap_triple_align": 1, ...
  "bn_color_dn": 0, "bn_absorb_ask": 0, "n_big_ask_t1": 3, ...
  "edge_buy_zone_size": 4, "edge_sell_zone_size": 0, ...
  "open_type": 3, "day_type": 4, "profile_shape": 2, ...

  // MQ_Lite levels (17 features)
  "dist_mq_call_pct": 0.45, "dist_mq_put_pct": -0.21, ...

  // VIX_Lite (17 features)
  "vix_level": 17.85, "vix_regime": 1, "dist_vix_call_0dte_pct": ...

  // Regime engine (7 features)
  "regime_label": "RANGE", "regime_strength": 0.62, "regime_actionable": true, ...
}
```

## Module structure proposee

```
CORE/live_enricher.py        Service principal (callback close bar)
CORE/live_enricher_state.py  State manager (buffer in-memory rolling)
CORE/live_enricher_io.py     Read inputs (OHLCV cache, Trades buffer, MQ, VIX)
CORE/live_enricher_writer.py Write output JSONL atomic + rotation
```

## Service deployment

- nssm service `MIA-Live-Enricher` (similaire `MIA-Live-OHLCV`)
- Tourne 24/7 VPS
- Dependencies : `MIA-Live-OHLCV` (Databento stream) + Sierra Chart actif

## Validation requise (Plan agent + ml-trainer)

Avant impl :
1. Plan agent valide Option C vs A/B/D
2. ml-trainer valide methodologie shadow run vs V4 batch
3. Parite cible : <0.001 diff par feature, 100% bars matching

## Backlog post-impl

- Bot 2 V6 : adapter pour lire `DATA/live_enriched/` au lieu de V4 parquet
- Couper progressivement DMP JSONL consumption (Chantier 3+ : cutover DMP)
- Pipeline V4 batch reste pour backtests/training historique seulement

## Risques

- **Perte data** : crash service = trou dans live_enriched JSONL.
  Mitigation : monitoring nssm + auto-restart + backfill V4 batch reprend.
- **Drift Python vs V4 batch** : si engines modifies en batch mais pas streaming.
  Mitigation : appel meme `apply_all_engines()` fonction (DRY garanti).
- **Latence cycle** : si > 60s/cycle, backlog cumule.
  Mitigation : monitoring time/cycle + alerte Discord si > 30s.

## Decisions ouvertes (a trancher avec Jackson)

1. Option A vs C : Option C plus ambitieuse mais 2 semaines. Option A possible 1 semaine.
2. Buffer initial 60j au boot : load depuis V4 parquet ou Databento Historical ?
3. Si downstream `databento_paper_trader.py:2748` (Bot 3) consomme `ma_trend`
   du V4 parquet, fait-on un fallback ou un cutover net ?
4. Schema bump `live_enriched_2.0` quand on rajoutera des features (anticipation).

---

# AUDIT PLAN AGENT 13/05/2026 NUIT — RESERVES ET FIXES

Verdict Plan agent : **GO-AVEC-RESERVES Option D**. 4 reserves critiques + 3 omissions
phasing + 4 recommandations decisions ouvertes.

## Reserves critiques (avant impl)

### R1. Engines a SEMANTIQUE differente batch vs stream

**`game_changers.py:apply_game_changers` (build_dataset_v4_phase_b.py:231)** fait
un `groupby(date_et)` avec **lookahead intra-jour** :
```python
sess_high = grp["sess_high"].iloc[-1]   # fin de jour, INDISPONIBLE en stream
```
En batch : EOD definitif. En stream : snapshot intra-jour evolutif.

**Idem `apply_market_profile_rolling`, `apply_phase_d_dalton_levels`** :
pVWAP/Naked POC depend session complete.

**Mitigation** : documenter ces engines comme "DUAL_SEMANTIC" :
- Batch : output definitif EOD (build_v4 historique)
- Stream : output `*_provisional` evolutif (e.g. `open_type_provisional`,
  `day_type_provisional`) qui converge vers la valeur batch a EOD.

DRY garanti "batch appelle streaming" **NE TIENT PAS** pour ces engines.
Documenter explicitement.

### R2. Critere parite incomplete

Critere actuel : `df_batch[cols] - df_stream[cols] | .abs().max() < 0.001`.
Valide la coherence sur DONNEES IDENTIQUES mais pas :
- Warmup state apres redemarrage service
- Gap data (Databento outage)
- Cross-day boundary (state reset session CME 17:00 ET)

**Mitigation** : ajouter test parite secondaire :
```python
# df_stream_redemarre_a_J3 vs df_stream_continu_depuis_J0 apres 7 jours
df_continu = run_stream(start=J0, end=J7)
df_restart = run_stream(start=J0, end=J3) + restart_load_state() + run_stream(J3, J7)
assert (df_continu - df_restart).abs().max() < 0.001  # state serialization OK
```

### R3. Pattern 11 V1 risk MAJEUR

Refacto 13 modules simultanee avec batch+stream coexistants =
surface erreur enorme.

**Mitigation** :
- Review agent obligatoire APRES CHAQUE engine refactorise (pas en bloc semaine)
- Tests parite GO/NO-GO bloquant merge avant engine suivant
- **FREEZE code batch `apply_all_engines()` pendant 4 semaines** : aucun
  commit sur les 13 engines hors stream pour eviter drift

### R4. n=6 trades Bot 2 V6 = data mining trap

Cf `feedback_data_mining_trap.md` + `project_bot2v6_dmp_in_practice.md`.

**Mitigation** : NE PAS COUPER DMP avant n>=50 trades shadow run. Cutover
PROGRESSIF (Bot 2 V6 lit `live_enriched/` ET DMP en parallele).

## Omissions phasing detectees

### O1. `phase_b_v6_complete.py` (GROUPE A) absent

Pas dans `apply_all_engines()` actuel (verifie build_v4_phase_b.py:382-470).
Est-ce un sous-chantier independant Bot 2 V6 ou wire pendant Chantier 3 ?

**Decision** : **sortir de Phase 3a**. Wire dans pipeline V4 batch d'abord
(Phase 2c ulterieure), puis adapter streaming Chantier 3.

### O2. `IntermarketFeatures (im_*)` separe

Appele `process_partition_intermarket()` ligne 814, passe ES<->NQ cross-sym.
Manquant dans phasing 13 engines.

**Decision** : ajouter Phase 3d (state cross-symbol = complexite reelle).

### O3. `rvol` engine oublie de la liste explicite

Maintient deja un state interne.

**Decision** : ajouter Phase 3b avec `phase_b_helpers` (rvol_inputs deja la).

## Reorganisation phasing Option D corrigee

### Phase 3a (Semaine 1) — Infrastructure + 1 engine simple

- Infrastructure : `live_enricher_io.py` + `_state.py` + `_writer.py` + `live_enricher.py` skeleton
- **1 engine refactorise** : `vix_lite_reader.py` (deja row-by-row, simplest)
- ~~game_changers retire~~ (DUAL_SEMANTIC, decale Phase 3d apres convention provisional)
- ~~phase_b_v6_complete retire~~ (sous-chantier independant)

### Phase 3b (Semaine 2) — 6 engines moyens (corrige)

4. `phase_b_helpers.py` (sessions, IB, sess HL, volume_profile)
5. `rvol_engine` (recalibre apres phase_b_helpers)
6. `phase_b_rolling_inputs.py` (ATR Wilder, VWAP slope, IB derives, CVD momentum, VPOC derives)
7. `phase_b_plus_engine.py` (Color, Long, OVN, Opens, News)
8. `sessions_swings_engine.py` (swing detection rolling window)
9. `vwap_diff` + `option_c_plus_transforms` (trivial row-level)

### Phase 3c (Semaine 3) — 4 engines complexes footprint-based + Dalton (corrige)

10. `footprint_builder.py` (streaming update_footprint(bar, trades))
11. `phase_b_plus_plus_engine.py` (BIG orders, STACK, DELTA_DIV, TRAPPED, CLUSTER, ABSORPTION)
12. `edge_zones_engine.py` (apply_edge_zones stream-aware)
13. `phase_d_dalton_levels.py` (pVWAP, naked POC, single prints, excess) — DUAL_SEMANTIC

### Phase 3d (Semaine 4) — Finalisation + DUAL_SEMANTIC engines + Cross-sym

14. `market_profile_rolling.py` (ctx_*) — DUAL_SEMANTIC
15. `game_changers.py` (open_type, day_type) — DUAL_SEMANTIC convention `*_provisional`
16. `regime_engine_v6.py` (deja row-by-row)
17. **`IntermarketFeatures` (im_*)** — cross-sym ES<->NQ (NOUVEAU Phase 3d)
18. Shadow run 7 jours + audit code-reviewer + ml-trainer + deploy nssm service

## Decisions ouvertes — recommandations Plan agent

1. **Cutover DMP** : **PROGRESSIF** (n>=50 trades shadow, n>=30 jours parallele)
2. **Schema** : **`live_enriched_1.0` MVP** (YAGNI semver, bump quand features ajoutees)
3. **Service deploy** : **nssm NEW `MIA-Live-Enricher`** distinct de `MIA-Live-OHLCV` (blast radius limite)
4. **Shadow run** : **V4 batch parallele LIVE** 7j minimum (replay historique ne capte pas gaps reels)

## Plan d'attaque Phase 3a semaine 1 (Plan agent jour-par-jour)

- **Lundi** : `CORE/live_enricher_io.py` (read OHLCV cache `CORE/live_cache.py`,
  trades buffer Chantier 2, MQ levels, VIX). Tests unitaires + lag <60s verification.
- **Mardi** : `CORE/live_enricher_state.py` (rolling buffer 60j bars + 3j trades
  in-memory, snapshot disque toutes 5min crash recovery). Test redemarrage OK.
- **Mercredi** : `CORE/live_enricher_writer.py` (JSONL atomic write `.tmp` +
  `os.replace`, rotation quotidienne UTC). Test write concurrent safe.
- **Jeudi** : `CORE/live_enricher.py` skeleton service (callback close bar,
  schedule 60s, monitoring time/cycle). PAS d'engines — output JSONL minimal
  `{ts, OHLCV, volume}` seulement.
- **Vendredi** : refacto **engine #1** `vix_lite_reader.py` (deja row-by-row,
  le plus simple). Test parite batch vs stream + integration enricher.
  **GO/NO-GO checkpoint Jackson**.

## Source agents

- code-reviewer (audit C++ VIX_Lite v1.3, audit v6_complete v0.2/0.3/0.4, audit Chantier 2 pre+post fix)
- ml-trainer (audit GROUPE A backtest, DROP momentum_3b, audit GROUPE B variantes)
- market-analyst (audit composites trend_composite + vwap_alignment, recommandation discretise)
- Plan agent (ce verdict GO-AVEC-RESERVES Option D Chantier 3)
