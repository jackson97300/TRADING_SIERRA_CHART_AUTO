# PLAN — Refactor Pipeline Incrémental (v2 post-validation agent Plan)

**Date** : 2026-05-01
**Auteur** : Claude (orchestré par Jackson)
**Validateur** : agent Plan — **GO-AVEC-RÉSERVES** corrigées dans cette v2
**Durée révisée** : 24-28h sur 4-5 sessions
**Status** : VALIDÉ pour démarrage implémentation

---

## 1. OBJECTIF

Refactor SOLIDE ET DURABLE du pipeline `live_pipeline_loop` pour passer de 30 min de retard structurel à **2-5 min steady-state**. Une bonne fois pour toutes (Jackson directive).

## 2. CONTEXTE

Voir version v1 du plan + verdict agent Plan validation (réserves intégrées ci-dessous).

## 3. CORRECTIONS AGENT PLAN INTÉGRÉES

### 3.1 Réserves bloquantes corrigées (ordre de gravité)

#### CR1. CVD session warmup
**Mauvais** : warmup 200 bars
**Bon** : warmup = **session CME complète** (depuis dernier 17:00 CT = 22:00/23:00 UTC selon DST)
**Fichier** : `CORE/build_dataset_v4_dmp_databento.py:847+` (build_for_symbol)
**Logique** :
```python
from zoneinfo import ZoneInfo
chicago_tz = ZoneInfo("America/Chicago")
last_ts_chicago = pd.Timestamp(last_ts, tz="UTC").tz_convert(chicago_tz)
session_start_chicago = last_ts_chicago.replace(hour=17, minute=0, second=0, microsecond=0)
if last_ts_chicago.hour < 17:
    session_start_chicago -= pd.Timedelta(days=1)
session_start_utc = session_start_chicago.astimezone(ZoneInfo("UTC")).tz_localize(None)
recompute_from = min(last_ts - pd.Timedelta(minutes=warmup_bars), session_start_utc)
```

#### CR2. `bars_since_roll` cumcount append-safe
**Mauvais** : cumcount brut sur df_partial → reprend à 0
**Bon** : offset depuis `existing.iloc[-1]`
**Fichier** : `CORE/build_dataset_v4_dmp_databento.py:698-707` (detect_roll)
**Logique** :
```python
if incremental and not existing.empty:
    last_bsr = existing["bars_since_roll"].iloc[-1] if pd.notna(existing["bars_since_roll"].iloc[-1]) else 0
    last_dsr = existing["days_since_roll"].iloc[-1] if pd.notna(existing["days_since_roll"].iloc[-1]) else 0.0
    df_partial["bars_since_roll"] = df_partial.groupby(group_id).cumcount().astype("Int64") + last_bsr + 1
    df_partial["days_since_roll"] = (df_partial["bars_since_roll"].astype("Float64") / 1380).round(2)
```

#### CR3. FFD warmup assertion
**Risque** : FFD width 150-180 (d=0.4, threshold=1e-4), warmup 200 = marge faible
**Action** : assertion + fallback batch si insuffisant
**Fichier** : `CORE/build_dataset_v4_dmp_databento.py:635` (cvd_5d_rolling_ffd)
**Logique** :
```python
FFD_WIDTH_ESTIMATE = 200  # max attendu
if incremental and len(df_warmup) < FFD_WIDTH_ESTIMATE:
    print(f"[WARN] FFD warmup insufficient ({len(df_warmup)} < {FFD_WIDTH_ESTIMATE}) — fallback batch")
    incremental = False  # force full rebuild ce cycle
```

#### CR4. PHASE_B Dalton levels warmup 10 trading days
**Mauvais** : warmup jour
**Bon** : 10 trading days (naked POC peut référencer 5+ jours en arrière)
**Fichier** : `CORE/build_dataset_v4_phase_b.py:apply_phase_d_dalton_levels`
**Constante** : `WARMUP_DALTON_DAYS = 10`

#### CR5. Phase C `value_area_running` absent du plan
**Action** : ajouter Phase C dans étape 3, warmup = session entière (état TPO buckets cumulatifs par session)
**Fichier** : `CORE/market_profile_rolling.py` ou équivalent

#### CR6. databento_download.py ne supporte pas `--start-time`
**Action** : suppression simple de `--force` ligne 155 `live_pipeline.py`
**Vérification préalable** : tester si `databento_download.py --partial-end` mode est append-safe (lit fichier existant + fetch delta) ou écrase
**Fallback si non append-safe** : refactor `databento_download.py` (+1-2h)

### 3.2 Cas limites supplémentaires (CRITIQUES)

#### CL1. Race condition write parquet
**Risque** : Bot 2 `pd.read_parquet` pendant que pipeline écrit → corruption ou crash
**Action** :
- Pipeline : `tmp_path + os.replace()` atomic
- Bot 2 `load_last_bar` : retry 3x avec backoff sur OSError/ValueError
**Fichiers** :
- `CORE/build_dataset_v4_dmp_databento.py:write_partitioned`
- `CORE/build_dataset_v4_phase_b.py:write_v4_atomic` (déjà atomic ?)
- `CORE/databento_paper_trader.py:404` (read_parquet retry)

#### CL2. Boot froid VPS reboot
**Risque** : feature flag incremental + parquet absent → fallback batch OK MAIS Bot 2 lit ancien parquet stale
**Action** : ordre boot services :
1. `MIA-Live-OHLCV` (stream Databento)
2. `MIA-LivePipeline` (attendre 1 cycle complet)
3. `MIA-DataBento-Paper` (Bot 2)

#### CL3. Schema drift
**Risque** : nouvelle colonne entre 2 cycles → `pd.concat(existing, df_partial)` avec NaN silencieux
**Action** : assertion stricte
```python
if incremental:
    cols_existing = set(existing.columns)
    cols_partial = set(df_partial.columns)
    if cols_existing != cols_partial:
        new_cols = cols_partial - cols_existing
        missing_cols = cols_existing - cols_partial
        print(f"[WARN] schema drift : new={new_cols} missing={missing_cols} — fallback batch")
        incremental = False
```

#### CL4. DST switch mars/novembre
**Risque** : DST shift mid-cycle → session_id basculera
**Action** : test explicite T9 + utilisation `ZoneInfo` partout (jamais `replace(hour=...)` raw)

### 3.3 Critères d'acceptation reformulés

| # | Critère v1 (KO) | Critère v2 (corrigé) |
|---|---|---|
| 4 | "0 verdict différent vs batch" | "0 verdict différent sur rows < (last_ts - warmup_max=10j)" |

---

## 4. SÉQUENCE D'IMPLÉMENTATION VALIDÉE

```
SESSION A (cette session, ~6-7h dispo)
├── 1. ETAPE 0 : backup + branche + tag + golden parquet (1h)
├── 2. QUICK WIN test : supprimer --force, mesurer 2-3 cycles (45 min)
│   └─ Décision : si gain ≥ 80% → continuer Phase B mais sans urgence
│                 si gain ≤ 30% → confirmation refactor critique
├── 3. ETAPE 5 WARN-ONLY : seuils Bot 2 logs sans HARD SKIP, 30 min observation (1h)
└── 4. ETAPE 1 : BUILD_V4 incremental + CR1, CR2, CR3 (5-6h)
    └─ Test T1 byte-identique sur 30/04 (1h)

SESSION B (5-6h)
├── 5. ETAPE 3 : PHASE_B incremental + CR4, CR5 (5-6h)
└── 6. Tests T1 + T7 (race) + T8 (schema drift) (1-2h)

SESSION C (4-5h)
├── 7. ETAPE 2 : live_pipeline.py adapter incremental (1-2h)
├── 8. ETAPE 4 : interval 90s + phase-b-every 3 (15 min)
├── 9. ETAPE 6 : killswitch fallback (1h)
├── 10. Tests T1-T9 complets (2h)
└── 11. code-reviewer + ml-trainer reviews (1h)

SESSION D (3-4h)
├── 12. Deploy CANARY 24h SHADOW (no-trade) (5 min + 24h obs)
├── 13. Si SHADOW OK → ETAPE 5 activation HARD SKIP 480s (15 min)
├── 14. Re-validation agent Plan complète (30 min)
└── 15. Deploy PROD + monitoring J+1, J+7

SESSION E (J+1, ~2h)
├── 16. Monitoring metrics (latence p95, drift, restarts watchdog)
└── 17. Ajustements si nécessaires
```

---

## 5. TESTS PRE-DEPLOY (T1-T9)

### T1. Non-régression byte-identique (rows < warmup_max=10j)
- Run pipeline batch sur 2026-04-30 → `data_batch.parquet.golden`
- Run pipeline incremental sur 2026-04-30 → `data_incremental.parquet`
- Comparer rows ts_event < (last_ts - 10j) → diff = 0
- Comparer rows dans warmup → tolérance 1e-9 ulps

### T2. Test reprise après trou
- Simuler gap 2h (delete bars dans parquet)
- Lancer incremental → vérifier bars manquantes re-fetched
- `cvd_session`/`bars_since_roll`/`cvd_5d_rolling_ffd` continues sans drift

### T3. Test boundary session CME (17:00 CT)
- Run incremental sur bars chevauchant 22:00 UTC (été) ou 23:00 UTC (hiver)
- Vérifier `cvd_session` reset au bon ts (DST-aware via ZoneInfo)

### T4. Test boundary mois
- Run incremental le 1er du mois à 00:30 UTC
- Vérifier partition `month=04` ferme proprement, `month=05` démarre

### T5. Test latence steady-state
- 30 min runtime continu
- Mesurer p95 `last_bar_age` Bot 2
- Cible : < 240s

### T6. Régression Bot 2 trades
- Replay 1 jour paper sur batch vs incremental
- `score_consensus` même verdict BUY/SELL/HOLD pour rows hors warmup

### T7. Race condition Bot 2 read / pipeline write 🆕
- Lancer pipeline en boucle 30s ET Bot 2 read 5s en parallèle pendant 5 min
- Aucun crash Bot 2, aucune corruption parquet
- Atomic write `tmp + os.replace()` validé

### T8. Schema drift 🆕
- Ajouter manuellement une colonne dans existing parquet
- Lancer incremental → assertion levée + fallback batch déclenché

### T9. DST switch 🆕
- Replay incremental sur bars chevauchant DST shift (mars 2026 ou novembre 2026 historique)
- Vérifier session_id transition correcte

---

## 6. AGENT REVIEWS OBLIGATOIRES

1. ✅ **agent Plan** v1 validation : DONE 14:30 UTC (GO-AVEC-RÉSERVES corrigées dans v2)
2. **code-reviewer** : audit code après ETAPE 1, 3 (CRITIQUE)
3. **ml-trainer** : régression dataset features sur 1 jour test (CRITIQUE)
4. **agent Plan** re-validation finale avant merge master

---

## 7. PLAN ROLLBACK (corrigé)

### Niveau 1 — Feature flag
```bash
ssh Administrator@212.28.179.199 'powershell -Command "
  [Environment]::SetEnvironmentVariable(\"MIA_PIPELINE_MODE\", \"batch\", \"Machine\")
  Restart-Service MIA-LivePipeline
  Restart-Service MIA-Watchdog  # 🆕 reset RAM seuils watchdog
"'
# Bot 2 : remonter seuils Option B (FRESH 600 / WARN 1500 / CRIT 2700)
# manuellement ou via env var
```

### Niveau 2 — Git revert
```bash
git checkout pre-incremental-20260501 -- CORE/live_pipeline.py CORE/build_dataset_v4_dmp_databento.py CORE/build_dataset_v4_phase_b.py CORE/databento_paper_trader.py BOT/mia_watchdog.py
scp ... # redeploy
ssh ... 'Restart-Service MIA-LivePipeline, MIA-DataBento-Paper, MIA-Watchdog'
```

### Niveau 3 — Restore parquet backup
```bash
ssh Administrator@212.28.179.199 'powershell -Command "
  Stop-Service MIA-LivePipeline, MIA-DataBento-Paper
  Remove-Item -Recurse -Force C:\TRADING_SIERRA_CHART_AUTO\DATA\datasets\v4_enriched
  Copy-Item -Recurse C:\TRADING_SIERRA_CHART_AUTO\DATA\datasets\v4_enriched.backup.20260501 C:\TRADING_SIERRA_CHART_AUTO\DATA\datasets\v4_enriched
  Start-Service MIA-LivePipeline, MIA-DataBento-Paper
"'
```

---

## 8. CRITÈRES D'ACCEPTATION GLOBAUX

GO production si **TOUS** validés :

| # | Critère | Mesure |
|---|---|---|
| 1 | Tests T1-T9 PASS | 100% |
| 2 | Latence p95 steady-state | < 240s |
| 3 | Cycle complet duration | < 30s |
| 4 | Régression Bot 2 trades | 0 verdict diff sur rows < (last_ts - 10j) |
| 5 | code-reviewer | GO ou GO-AVEC-RÉSERVES (mineures) |
| 6 | ml-trainer | aucun feature flag drift |
| 7 | agent Plan re-validation | GO |
| 8 | 24h CANARY SHADOW sans crash | 0 erreur fatale |
| 9 | 24h prod sans incident post-deploy | 0 alerte CRIT watchdog |

---

## 9. ETAT PROD PENDANT REFACTOR

- **Master branche** : Option B en place (patch tolère 30 min). Bot 2 trade quand pipeline rattrape sous 40 min.
- **Branche `feature/pipeline-incremental`** : développement isolé.
- **Deploy mergé** : seulement après TOUS critères acceptation validés.

---

## 10. VARIABLES CRITIQUES

- `WARMUP_DALTON_DAYS = 10`  (CR4)
- `WARMUP_SESSION` = session CME complète depuis 17:00 CT (CR1)
- `FFD_WIDTH_ESTIMATE = 200` (CR3, fallback batch si insuffisant)
- `MIA_PIPELINE_MODE` env var : `incremental` | `batch` (default `batch`)

---

**STATUS V2** : VALIDÉ par agent Plan (validation v1 → corrections appliquées dans v2). Prêt pour démarrage implémentation séquentielle.
