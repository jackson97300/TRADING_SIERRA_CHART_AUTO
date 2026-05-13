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

## Recommandation initiale

**Option C (Hybride)** semble le bon compromis :
- Perf acceptable (3-5s/cycle, marge confortable)
- Effort raisonnable (2 semaines)
- Features rolling longues preservees via snapshot disque
- Permet validation incrementale (start avec Option A 1 jour, ajouter snapshot apres)

**Phasing propose** :

1. **Phase 3a (semaine 1)** : impl Option A (window 1j) + tests parite
   - Output `DATA/live_enriched/{sym}/*.jsonl` fonctionnel
   - Shadow run V4 batch parallele 7 jours
2. **Phase 3b (semaine 2)** : ajouter snapshot 60j quotidien
   - Refresh 1x/jour, merge avec streaming buffer
   - Features rolling longues retrouvees

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
