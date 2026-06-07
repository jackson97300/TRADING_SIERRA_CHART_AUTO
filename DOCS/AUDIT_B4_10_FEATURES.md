# Audit B4 — 11 features Python pour port C++ Sierra

**Date** : 2026-06-07
**Mode** : ULTRATHINK lecture pure (Grep + Read), no code change
**Source** : sweep `enricher_chain.py` + `rolling_features.py` + `rolling_features_streaming.py` + `phase_b_helpers.py` + `CPP/MIA_REFACTORED/DUMPER/15/*.h` + audits `PORT_C++_SIERRA_INVENTORY.md`, `SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md`, `AUDIT_FEATURES_V4_RAPPORT_28042026.md`, `BACKTEST_A3_RAFFINEMENT.md`, `INCIDENT_LOG.md`.

---

## Synthese executive

- **5 GO PORT immediate** : `mins_et`, `is_in_us_cash`, `dist_pdh_pct`, `dist_pdl_pct`, `atr_14m_pct`
- **2 GO-AVEC-VALIDATION** : `ctx_day_type_intensity` (walk-forward DSR avant trust ML, mais formule SAINE), `cvd_session` (audit RTH-filter)
- **2 DEFER** : `ctx_trend_day_score` (composite 5 criteres, rolling complex), `A3_v4_with_cvd_session` (STRATEGIE de scoring backtest, PAS feature)
- **2 DROP** : `delta_persistence_20`, `big_spawn_rate_20` (n'existent PAS dans code, backtests V2/V3 sous-performent V4)
- **1 BUG A CORRIGER AVANT PORT** : `range_pos` COLLISION C++ vs Python (semantiques differentes ecrivent meme cle)
- **Schema cible 3.7.21** : n_cols 372 + **6** (atr_14m_pct + mins_et + is_in_us_cash + dist_pdh_pct + dist_pdl_pct + ctx_day_type_intensity)
- **ETA total** : ~10h (3h port trivial + 4h ctx_day_type + 3h fix collision range_pos)

---

## ⚠️ ALERTE 1 — `range_pos` COLLISION C++ vs Python (critique a corriger AVANT B4)

**Bug confirme par grep** :

### C++ B2 `range_pos` (deja deploye, DMP_Transform.h:577-581)
```cpp
// 0-100% base VALUE AREA courante
float raw = (p - r.cur_val) / (r.cur_vah - r.cur_val);
f.range_pos = std::fmax(0.0f, std::fmin(1.0f, raw)) * 100.0f;  // 0-100%
```

### Python enricher_chain.py:739 `range_pos` (Phase 3c)
```python
# 0-1 base BAR 1min (high-low)
rng = h_f - l_f
payload["range_pos"] = (c_f - l_f) / rng if rng > 0 else 0.5
```

**Deux semantiques DIFFERENTES ecrivent la MEME cle `range_pos`** :
- C++ : base VA, echelle 0-100
- Python : base bar 1min, echelle 0-1

L'ordre d'execution determine quelle valeur survit dans live_enriched. Verifie sur `20260603_NQ.jsonl` : `range_pos = 0.604167` → c'est **Python qui ecrase C++** (echelle 0-1 = bar 1min).

**B3.A a contourne** en creant `position_in_range` (base mq_1d_min/max) au lieu de patcher. F22 PositionRange ajoute `pct_in_range`/`premium_zone`/`discount_zone`/`position_in_range` SANS toucher `range_pos` → collision toujours active.

**Verdict** : avant B4, decision strategique :
1. **OPTION A** : renommer C++ → `range_pos_va` (port B2 retro-incompatible)
2. **OPTION B** : renommer Python → `range_pos_bar` (Bot 1 / backtests qui lisent `range_pos` impactes)
3. **OPTION C** : laisser Python override C++ (status quo + documentation explicite)

Le backtest A3 V5_with_range_pos consomme `range_pos` (0-1 base bar) → si on porte la version C++ qui ecrit echelle 0-100, le backtest casse silencieusement.

**Recommandation** : OPTION A (renommer C++). Le `range_pos` Python est déjà consommé par bot3, backtest A3 et nombreux modules. Renommer C++ en `range_pos_va` evite cassure cote Python.

---

## ⚠️ ALERTE 2 — `ctx_day_type_intensity` Spearman annonce +0.83

### Verification de la formule (rolling_features.py:306-310, rolling_features_streaming.py:723-732)
```python
# dir = +1 si ib_broken_up seul, -1 si ib_broken_down seul, 0 sinon
# mag = |dist_vwap_d_atr|
df["ctx_day_type_intensity"] = (_dir * _mag).clip(-1.0, 1.0)
```

### Audit anti-lookahead
- ✅ `ib_broken_up`/`ib_broken_down` : booleens C++ DMP courants (DMP_Transform.h:726-727), `p > r.ib_high` evalue sur barre courante, **pas de futur**
- ✅ `dist_vwap_d_atr` : distance courante, calcul VWAP rolling, **pas de futur**
- ✅ **N'utilise PAS `day_type`** (qui lui est pollue par lookahead `.iloc[-1]` cf INCIDENT_LOG 39 06/06)
- ✅ Streaming et batch sont mirroir bit-for-bit (lignes 691-734 streaming + 280-310 batch)

### Verification Spearman documente
Grep DOCS confirme :
- `MIA_PIPELINE_RECAP.md:260` : **rho = -0.156 / -0.202** (PAS +0.83)
- `MIA_PIPELINE_RECAP.md:292` : NQ -0.156 / ES -0.101

**Le +0.83 du brief est probablement** :
- Une erreur de transcription
- OU un Spearman ES vs NQ (correlation cross-instrument)
- OU une mesure recente non documentee

**Verdict** : la formule est **SAINE, pas de lookahead**, mais le Spearman annonce est SUSPECT. Walk-forward DSR Lopez recommande **avant trust ML**, pas avant port C++ (port est sain).

### Plan walk-forward DSR Lopez (si Spearman +0.83 confirme)
1. Dataset : v4 parquets ES+NQ 80 jours (DATA/datasets/v4/)
2. Methodologie : Lopez AFML ch.4 Combinatorial Purged CV, 4-fold
3. Mesurer : rho ctx_day_type_intensity vs forward[60] par fold
4. Si rho_median > 0.5 fold-par-fold → suspecter leak cache (re-audit streaming/batch mirror)
5. Si rho_median ~ -0.156 (= documente) → +0.83 etait artefact, GO PORT

---

## Matrice synthese

| # | Feature | Module Python | Source C++ deja dispo ? | Type | Spearman/Edge | Verdict | Effort |
|---|---|---|---|---|---|---|---|
| 1 | `cvd_session` | enricher_chain.py:1460 (alias ctx_cvd_session) | cvd_day deja en C++ | Cumul session | rho=-0.07 (V4 backtest 0.20) | ✅ GO PORT (audit RTH-filter) | EASY 1h |
| 2 | `atr_14m_pct` | enricher_chain.py:783 | atr deja en C++ | Normalisation pct | HIGH_CORR_INSTRUMENT 0.98 (audit 28/04) | ✅ GO PORT (mais corr instrument flag) | TRIVIAL 0.5h |
| 3 | `range_pos` (collision) | enricher_chain.py:739 (bar 1min) | DMP_Transform.h:577 (base VA, echelle 100) | Position | rho=0.0689 | ⚠️ FIX COLLISION AVANT B4 | HARD 3h |
| 4 | `dist_pdh_pct` | phase_b_helpers.py:1222 | pdh deja en C++ | Distance pct | HIGH_CORR_INSTRUMENT 0.96 (audit 28/04) | ✅ GO PORT trivial | TRIVIAL 0.5h |
| 5 | `dist_pdl_pct` | phase_b_helpers.py:1223 | pdl deja en C++ | Distance pct | HIGH_CORR_INSTRUMENT 0.98 (audit 28/04) | ✅ GO PORT trivial | TRIVIAL 0.5h |
| 6 | `mins_et` | phase_b_helpers.py:112 + enricher_chain.py:1436 | DMP_Reader.h:1658 (`time_et` deja calcule, NON expose) | Time | utilise interne | ✅ GO PORT trivial (expose le champ) | TRIVIAL 0.3h |
| 7 | `is_in_us_cash` | enricher_chain.py:715 | DMP_Reader.h:1661 (`is_rth_session` deja calcule) | Bool RTH | utilise interne | ✅ GO PORT trivial (alias rename) | TRIVIAL 0.3h |
| 8 | `ctx_day_type_intensity` | rolling_features.py:310 | ib_broken_up/dn + dist_vwap_d_atr deja en C++ | Composite | rho=-0.156 (alarme +0.83 non confirme) | ⚠️ GO-AVEC-VALIDATION (walk-forward DSR) | EASY 2h |
| 9 | `ctx_trend_day_score` | rolling_features.py:299 | Tous inputs C++ (ib_range_atr, ib_broken, vol_slope, dist_vwap, delta_day_dir) | Composite 5 criteres | non documente | ⏸ DEFER (rolling 5 criteres + ctx_vol_slope_5 lui-meme MEDIUM) | MEDIUM 4h |
| 10 | `delta_persistence_20` | **N'EXISTE PAS** (formule backtest A3 V2 uniquement) | delta_bar deja C++ | Rolling 20 bars | V2_baseline rho=0.144 (perdant vs V4=0.199) | ❌ DROP (sous-performe) | n/a |
| 11 | `big_spawn_rate_20` | **N'EXISTE PAS** (formule backtest A3 V3 uniquement) | n_big_ask_t1/n_big_bid_t1 PRESENTES C++ MAIS ABSENTES live JSONL recent | Rolling 20 bars | V3 non concluant | ❌ DROP (data missing + sous-performe) | n/a |
| 12 | `A3_v4_with_cvd_session` | TOOLS/backtest_a3_raffinement_walkforward.py:108 | C'est une **STRATEGIE de scoring** combinant 5 features | Score composite | rho=0.199 best variant | ⏸ DEFER (= strategy Bot, pas feature C++) | n/a |

---

## Detail par feature

### 1. `cvd_session` — ✅ GO PORT

**Formule canonique** (enricher_chain.py:1453-1463) :
```python
# Phase 1.5 18/05 : alias de ctx_cvd_session
# En batch V4 : cumsum(delta_bar) per session_id chicago
# En streaming : ctx_cvd_session deja calcule par ctx engines, juste alias
_cvd_sess = payload.get("ctx_cvd_session")
if _cvd_sess is not None:
    payload["cvd_session"] = _cvd_sess
else:
    # Fallback : cvd_day (proche, session_id != session_date_trading mais accept degrade)
    payload["cvd_session"] = payload.get("cvd_day")
```

**Sources C++** : `cvd_day` deja present, mais cvd_session necessite reset par session_id (Asia/London/RTH).

**Edge** :
- Best backtest A3 V4 : rho = -0.199 NQ, -0.217 ES (BACKTEST_A3_RAFFINEMENT.md:23)
- Walk-forward partiel : 3/4 folds significatifs, fold Q1 fragile
- FLAG : `LEAK_VOLATILITY` dans audit 28/04 (ks_em 0.311) — a re-tester sur v4 clean

**Effort C++** : EASY 1h
- Ajouter `r.cvd_session` dans DMP_Reader.h : reset si session_id change
- Ajouter `f.cvd_session = r.cvd_session` dans DMP_Transform.h
- Expose JSONL

**Verdict** : ✅ GO PORT — feasible, edge documente (rho=-0.20 backtest), formule simple. CAVEAT : confirmer apres port que le `LEAK_VOLATILITY` ks=0.311 du 28/04 a disparu sur v4 clean.

---

### 2. `atr_14m_pct` — ✅ GO PORT trivial

**Formule** (enricher_chain.py:769-785) :
```python
# atr_points = atr_ticks * tick_size
# atr_14m_pct = atr_points / close * 100
atr_ticks = float(_atr_p3)
atr_points = atr_ticks * _tick_atr
payload["atr_14m"] = atr_points  # POINTS (= batch)
if c_f2 > 0:
    payload["atr_14m_pct"] = atr_points / c_f2 * 100
```

**Sources C++** : `atr` deja present (DMP_Transform.h). Direct.

**Edge** : `HIGH_CORR_INSTRUMENT 0.98` (audit 28/04 ligne 390) — feature **leak instrument** : ATR(ES) ≠ ATR(NQ) signal trivialement instrument. Pour ML : DROP ou normaliser cross-instrument. Pour analyse : OK.

**Effort C++** : TRIVIAL 0.5h. `f.atr_14m_pct = f.atr_14m / p * 100.0f`.

**Verdict** : ✅ GO PORT — trivial. CAVEAT ML : flag HIGH_CORR_INSTRUMENT, ne pas l'utiliser pour modele cross-asset sans normalisation.

---

### 3. `range_pos` (collision) — ⚠️ FIX COLLISION AVANT B4

Voir ALERTE 1 ci-dessus.

**Verdict** : ⚠️ **FIX COLLISION AVANT B4**. Sans correction, port additional cassera silencieusement le backtest A3 V5 et toute consommation downstream.

**Recommandation** : renommer C++ `range_pos` → `range_pos_va` (OPTION A). Effort HARD 3h (modif DMP_Transform + DMP_Writer + meta + audit downstream).

---

### 4. `dist_pdh_pct` — ✅ GO PORT trivial

**Formule** (phase_b_helpers.py:1222) :
```python
df["dist_pdh_pct"] = ((df["pdh"] - df["close"]) / df["close"] * 100).astype("float32")
```

**Sources C++** : `pdh` deja calcule (deja en C++ B2 absolus).

**Edge** : `HIGH_CORR_INSTRUMENT 0.96` (audit 28/04 ligne 460) — meme caveat que atr_14m_pct.

**Effort C++** : TRIVIAL 0.5h.

**Verdict** : ✅ GO PORT — extension B1 _pct trivial.

---

### 5. `dist_pdl_pct` — ✅ GO PORT trivial

Identique a `dist_pdh_pct` mais pour `pdl`. HIGH_CORR_INSTRUMENT 0.98 (audit 28/04 ligne 461).

**Effort C++** : TRIVIAL 0.5h.

---

### 6. `mins_et` — ✅ GO PORT trivial

**Formule** (phase_b_helpers.py:112) :
```python
df["mins_et"] = ts_et.dt.hour * 60 + ts_et.dt.minute
```

**Source C++** : DMP_Reader.h:1658 calcule deja `time_et = h_et * 60 + m_et`. Le champ n'est juste pas expose dans `d.{}` struct.

**Effort C++** : TRIVIAL 0.3h. Ajouter `d.mins_et = time_et` dans DMP_Reader.h, propager dans DMP_Transform/Writer.

**Verdict** : ✅ GO PORT — expose champ existant.

---

### 7. `is_in_us_cash` — ✅ GO PORT trivial

**Formule** (enricher_chain.py:715, sessions_swings_simple) :
- True si mins_et entre 570 (9:30 ET) et 960 (16:00 ET)

**Source C++** : DMP_Reader.h:1661 calcule deja `d.is_rth_session = (time_et >= 9*60+30) && (time_et < 16*60)`. **C'est exactement is_in_us_cash**.

**Effort C++** : TRIVIAL 0.3h. Alias `is_rth_session` → `is_in_us_cash` ou rename. PAS de calcul nouveau.

**Verdict** : ✅ GO PORT — alias trivial.

---

### 8. `ctx_day_type_intensity` — ⚠️ GO-AVEC-VALIDATION

Voir ALERTE 2 ci-dessus.

**Formule SAINE** (rolling_features.py:306-310) :
```python
_up_only = df["ib_broken_up"].astype(bool) & ~df["ib_broken_down"].astype(bool)
_dn_only = df["ib_broken_down"].astype(bool) & ~df["ib_broken_up"].astype(bool)
_dir = np.where(_up_only, 1.0, np.where(_dn_only, -1.0, 0.0))
_mag = df["dist_vwap_d_atr"].abs()
df["ctx_day_type_intensity"] = (_dir * _mag).clip(-1.0, 1.0)
```

**Sources C++** :
- `ib_broken_up` : DMP_Transform.h:726 ✅
- `ib_broken_down` : DMP_Transform.h:727 ✅
- `dist_vwap_d_atr` : deja en C++ B1 _pct ✅

**Audit lookahead** :
- `ib_broken_*` evalue sur barre courante (`p > r.ib_high`) — pas de futur
- `dist_vwap_d_atr` distance courante — pas de futur
- **N'utilise PAS `day_type`** (qui lui est pollue 06/06 INCIDENT 39)
- Streaming et batch **mirror bit-for-bit** verifies

**Spearman documente** : -0.156 NQ / -0.101 ES (MIA_PIPELINE_RECAP.md:292). +0.83 du brief NON confirme.

**Effort C++** : EASY 2h. Composite simple, inputs deja en C++.

**Verdict** : ⚠️ GO-AVEC-VALIDATION — port C++ OK (formule saine), MAIS walk-forward DSR Lopez recommande avant trust ML pour reconcilier Spearman annonce +0.83 vs documente -0.156.

---

### 9. `ctx_trend_day_score` — ⏸ DEFER

**Formule** (rolling_features.py:271-299) :
```python
# Score additif sur 5 criteres, clip(0, 1) :
# IB comprime (ib_range_atr < 0.40) : +0.20
# IB casse unilateral : +0.25
# Vol accelere (ctx_vol_slope_5 > 0) : +0.15
# Prix loin VWAP (|dist_vwap_d_atr| > 0.15) : +0.20
# Delta day aligne avec vwap_d_side : +0.20
df["ctx_trend_day_score"] = _score.clip(0.0, 1.0)
```

**Sources C++** : Tous inputs presents (ib_range_atr, ib_broken, dist_vwap_d_atr, vwap_d_side, delta_day_dir) SAUF `ctx_vol_slope_5` qui est lui-meme un rolling Python complex (MEDIUM).

**Verdict** : ⏸ DEFER — composite 5 criteres avec dependance circulaire (ctx_vol_slope_5 = rolling 5 bars de vol_slope). Necessite porter d'abord `ctx_vol_slope_5`. Batch ulterieur.

---

### 10. `delta_persistence_20` — ❌ DROP

**Formule** (backtest_a3_raffinement_walkforward.py:83) :
```python
delta_pers = (df["delta_bar"] > 0).rolling(20, min_periods=10).mean() - 0.5  # [-0.5, +0.5]
```

**N'existe PAS** dans enricher_chain ou rolling_features — formule **inline backtest A3 V2**.

**Edge** : V2_with_delta_pers `rho=-0.110 NQ / -0.121 ES` — **PERDANT** vs V1_baseline (-0.161/-0.181) et V4_with_cvd_session (-0.161/-0.185). Le backtest A3 a teste cette feature et l'a **rejetee**.

**Verdict** : ❌ DROP — sous-performe baseline, pas de raison de porter.

---

### 11. `big_spawn_rate_20` — ❌ DROP

**Formule** (backtest_a3_raffinement_walkforward.py:94) :
```python
big_diff = (df["n_big_ask_t1"] - df["n_big_bid_t1"]).rolling(20, min_periods=10).mean()
big_diff_norm = big_diff / (df["n_big_ask_t1"] + df["n_big_bid_t1"]).rolling(20, min_periods=10).mean().clip(lower=1)
```

**N'existe PAS** dans enricher_chain — inline backtest A3 V3.

**ALERTE DATA** : `n_big_ask_t1` et `n_big_bid_t1` **ABSENTS du live_enriched JSONL recent** (verifie sur `20260603_NQ.jsonl`). C'est Sierra-only (cf SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md ligne 339-346 : n_big_ask_t1-t4 Sierra-only). MAIS absents en live_enriched semble divergence Bot 3 / Bot 4 pipeline.

**Edge** : V3 backtest non concluant dans le doc (pas dans le top 5).

**Verdict** : ❌ DROP — formule sur features absentes du live + backtest non concluant.

---

### 12. `A3_v4_with_cvd_session` — ⏸ DEFER (n'est PAS une feature)

**Formule** (backtest_a3_raffinement_walkforward.py:108-114) :
```python
cvd_sess = df["cvd_session"]
cvd_norm = np.sign(cvd_sess) * np.log1p(cvd_sess.abs() / 100).clip(upper=5) / 5
out["V4_with_cvd_session"] = (
    coh * mag * 0.3 +                              # coherence momentum 5/20/60
    vwap_sign * mag.clip(upper=2) * 0.25 +         # alignement VWAP slope
    range_exp.fillna(0) * np.sign(mom_20) * 0.15 + # ATR expansion
    (1 - near_key) * np.sign(mom_20) * 0.05 +      # eloignement PDH/PDL
    cvd_norm.fillna(0) * 0.25                      # CVD session direction
)
```

**Composantes** (toutes already-in-Python) :
- `close.diff(5/20/60)` : OHLCV
- `atr` : C++ DMP
- `vwap_slope_10` : C++ DMP (Sierra-only)
- `atr_14m` : Python (enricher_chain:779)
- `dist_pdh_pct` / `dist_pdl_pct` : Python phase_b_helpers (a porter — items 4 et 5)
- `cvd_session` : Python (a porter — item 1)

**Verdict** : ⏸ **DEFER — c'est une STRATEGIE de scoring**, pas une feature unique. A coder dans le BOT (Bot 1/4 layer scoring), pas en C++ DMP.

Si dashboard doit l'afficher : calculer en Python live (apres port des composantes 1, 4, 5), exposer comme `score_a3_v4` dans live_enriched, dashboard consomme.

**Note brief Jackson** : "Doit etre affichee dashboard" → c'est un job Python live + dashboard, pas C++.

---

## Plan sequencing recommande

**Phase 0 — FIX prerequis (BLOQUANT)** :
1. ⚠️ Decision sur collision `range_pos` (OPTION A renommer C++ recommande). Effort 3h.

**Phase 1 — Trivial (1h30)** :
1. `mins_et` (expose champ existant DMP_Reader.h:1658) — 0.3h
2. `is_in_us_cash` (alias is_rth_session) — 0.3h
3. `dist_pdh_pct` (formule trivial sur pdh existant) — 0.5h
4. `dist_pdl_pct` (formule trivial sur pdl existant) — 0.5h

**Phase 2 — Easy (3h)** :
5. `atr_14m_pct` (formule trivial sur atr existant) — 0.5h
6. `cvd_session` (reset par session_id) — 1h
7. `ctx_day_type_intensity` (composite simple ib_broken + dist_vwap) — 2h (note : audit walk-forward DSR Lopez en parallele avant trust ML)

**Phase 3 — Apres v4 stabilise** :
8. `ctx_trend_day_score` (apres port ctx_vol_slope_5) — MEDIUM 4h
9. `A3_v4_with_cvd_session` (PAS C++ — Python live + dashboard) — separate chantier

**Phase 4 — DROP** :
10. `delta_persistence_20` — sous-performe
11. `big_spawn_rate_20` — data missing live + sous-performe

**Schema cible 3.7.21** : n_cols 372 + 6 (items 1, 2, 4, 5, 6, 7) = **378**.

**ETA total Phase 0+1+2** : ~10h (3h fix collision + 1.5h trivial + 3.5h easy + 2h validation DSR).

---

## Risques globaux

1. **Collision `range_pos`** : si OPTION A (renommer C++) choisie, audit consommateurs C++ downstream (deja en VPS) — Bot 1/2/3 references inattendues. Grep cross-codebase OBLIGATOIRE avant rename.

2. **`ctx_day_type_intensity` Spearman +0.83 non confirme** : si reel, suspecter leak cache stream/batch. Walk-forward DSR Lopez **avant trust ML**, **pas avant port C++**. Port reste OK.

3. **HIGH_CORR_INSTRUMENT 4 features** (audit 28/04) :
   - `atr_14m_pct` : 0.98
   - `dist_pdh_pct` : 0.96
   - `dist_pdl_pct` : 0.98
   - Pour ML cross-asset : DROP ou normaliser. Pour gates instrument-specific : OK.

4. **Convention timezone** (cf memory `reference_timezone_convention.md` 24/04) : `mins_et` en C++ depend de `is_dst` (DMP_Reader.h:1655). Verifier que conversion ET correcte DST/non-DST. Le code existe deja avec offset 4/5h, semble OK.

5. **Cycle DST** : recompiler C++ DMP requis 2x/an (transition DST mars + novembre). DMP_Reader.h:1655 utilise `is_dst` flag — verifier mecanisme detection.

6. **B3.A `position_in_range` deja deploye** : ne PAS le re-porter. C'est une feature distincte (base mq_1d_max/min, pas base bar 1min ni base VA). Confusion possible avec `range_pos` Python (qui est base bar).

7. **`n_big_ask_t1` absence live** : verifier pipeline Bot 1 → live_enriched. Si Sierra-only n'arrive pas en live, BIG cluster features (a porter dans batches futurs) inutilisables en live.

8. **Cousine Pattern 11 DATA_MINING_TRAP** : Le brief contient indicateurs typiques (Spearman annonce sans walk-forward documente). Toute feature avec edge "rare/exceptionnel" passer ml-trainer **avant** integration scoring.

---

## Verification logs INCIDENT_LOG.md (entries pertinentes)

- **#39 (06/06)** : `day_type` lookahead `.iloc[-1]` pollue TOUS modeles V4 SHAP TOP-4. **MAIS** `ctx_day_type_intensity` n'utilise PAS `day_type` — risque ECARTE pour ce port.
- **#38 (06/06)** : fix `b0a9662` add_ib_atr Phase 2.1 **aggrave** day_type batch. **Idem** : pas d'impact sur ctx_day_type_intensity (formule independante).
- **#13 (20/05)** : feature selection ignore PROHIBITED list — 6 features LEAK dans 9 winners. Avant integration scoring, leak-check OBLIGATOIRE.

---

## Conclusion

**Decision recommandee** :

1. **FIX D'ABORD** collision `range_pos` (OPTION A renommer C++) — bloquant.
2. **Port immediate Phase 1** : 4 features triviales (mins_et, is_in_us_cash, dist_pdh_pct, dist_pdl_pct) — 1.5h.
3. **Port Phase 2** : atr_14m_pct + cvd_session + ctx_day_type_intensity — 3.5h + 2h validation walk-forward.
4. **DEFER** : ctx_trend_day_score (apres ctx_vol_slope_5), A3_v4_with_cvd_session (chantier Python live + dashboard).
5. **DROP** : delta_persistence_20, big_spawn_rate_20.

**Schema cible 3.7.21** : n_cols **378** (= 372 + 6).

**Critique impitoyable** :
- Le brief Jackson mentionne "10 features" mais en compte 11 dont 2 strategies/composites et 2 inexistantes. Discipline d'audit AVANT brief recommandee.
- Le Spearman +0.83 sur ctx_day_type_intensity n'est PAS documente — risque de chasing un mirage statistique (cousin Pattern 11).
- `range_pos` collision **aurait du etre detectee a B3.A** quand F22 a ajoute pct_in_range — le contournement `position_in_range` masque le bug existant.
- A3_v4_with_cvd_session est une **STRATEGIE de bot** (mix scoring 5 composantes), pas une feature. La confusion strategie/feature est cousine Pattern 11 V1 (cascades de gates au lieu de ML).
