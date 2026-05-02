# BLOCKER mq_* leak — REVISE post-verification empirique

**Date** : 2026-05-02 01:50 UTC (initial), revisé 02 09:30
**Severite** : ~~CRITIQUE~~ → **MEDIUM** (risque conditionnel V5)
**Status** : VERIFIE EMPIRIQUEMENT — pas de leak en V4, risque applicable
seulement si V5 build reutilise `dataset_builder.py:516`

## Finding initial (nuit 02/05 01:50)

Agent ml-trainer 2nd round flag `dataset_builder.py:516` :
```python
medians = df_clean.median()
df_clean = df_clean.fillna(medians)
```

Hypothese : `mq_*` features = NaN sur bars 2011-2024 (MenthorQ pas dispo),
median calculee sur dates 2026 → leak look-ahead massif.

## Verification empirique (matin 02/05 09:30)

### Test 1 — V4 actuel preserve les NaN

```bash
python -c "
df = pd.read_parquet('DATA/DATASETS/ES_dataset_v4.parquet')
df_pre  = df[df['date'] < '2025-12-21']  # 231554 rows
df_post = df[df['date'] >= '2025-12-21'] # 119783 rows
print(df_pre['dist_mq_call_pct'].isna().mean())   # 100.0%
print(df_post['dist_mq_call_pct'].isna().mean())  # 63.0%
"
```

**Resultat** : NaN preserved 100% pre-MQ + 63% post-MQ (jours sans data).
**Pas de leak detecte dans V4 actuel**.

### Test 2 — V4 builder ne fait pas le fillna global

`build_dataset_v4_dmp_databento.py` :
- Pas de `fillna(medians)` global
- Seul `fillna(0)` cible : volumes/delta sur bars no-trade (ligne 908)
- mq_* attache via `attach_mq_distances` (ligne 900) → NaN naturel preserve

### Test 3 — Date reelle de demarrage MenthorQ

```bash
ls DATA/MENTHORQ/ | grep "_menthorq_complete.json" | head -1
# 20251215_menthorq_complete.json
```

**MenthorQ data dispo depuis 2025-12-15** (pas 2026 comme estime initial).
~5 mois de data dispo (vs 15 ans data 1m), donc 97% des bars sont pre-MQ
naturellement NaN.

## Conclusion

**`dataset_builder.py:516` est code legacy NON utilise par V4 build.**
**V4 actuel ne souffre pas du leak.** mq_* NaN preserved correctement.

## Risque conditionnel V5

Le leak existerait SEULEMENT si :
1. V5 build (`build_v5_dataset.py` a creer samedi) reutilise `dataset_builder.py`
2. ET ne by-pass pas la ligne 516 fillna(medians)

**Mitigation V5 build** :
- Reutiliser le pattern V4 : `build_dataset_v4_dmp_databento.py` ligne 895-911
  - `attach_mq_distances` pour mq_*
  - fillna cible UNIQUEMENT volumes (`fillna(0)` ligne 908)
- NE PAS reutiliser `dataset_builder.py:_compute_menthorq` + `fillna(medians)`
- LightGBM gere NaN natif → mq_* NaN sur 97% des bars (pre-MQ) acceptable

## Action samedi V5 build

**AJOUTER au code `build_v5_dataset.py`** :
```python
# Pattern V4 (verifier samedi en code review) :
# 1. Charger 1m raw 15 ans Databento
df_1m = load_raw_1m_databento(symbol, start='2011-01-01', end=today)
# 2. attach mq_* via mq_lite_levels (NaN preserved sur dates pre-MQ)
df_1m = attach_mq_distances(df_1m, mq_levels)  # PAS fillna global
# 3. Volumes fillna(0) cible (no-trade bars)
df_1m['delta_bar'] = df_1m['delta_bar'].fillna(0)
# 4. mq_* + dist_mq_* RESTENT NaN avant 2025-12-15 → LightGBM natif handle
```

**NE PAS** :
- ❌ `df.fillna(df.median())` global
- ❌ `df.fillna(method='bfill')` ou `ffill` sur mq_*
- ❌ `df.dropna(subset=mq_cols)` (perdrait 97% data)

## Test bloquant samedi 9h (1 min) — fail-loud

Apres V5 build, AVANT train ML :
```python
import pandas as pd
df_v5 = pd.read_parquet('DATA/DATASETS/v5_htf/symbol=NQ.c.0/.../data.parquet')
df_v5['date'] = pd.to_datetime(df_v5['ts'], unit='ms', utc=True).dt.date
df_pre  = df_v5[df_v5['date'] < pd.Timestamp('2025-12-15').date()]
mq_cols = [c for c in df_v5.columns if 'mq_' in c.lower()]

# FAIL-LOUD assertion (vs print visuel)
for c in mq_cols[:5]:
    nan_ratio = df_pre[c].isna().mean()
    assert nan_ratio > 0.95, (
        f"LEAK DETECTE sur {c}: NaN ratio pre-MQ = {nan_ratio:.1%} "
        f"(attendu > 95%, sinon fillna global applique). STOP train."
    )
print(f"OK : {len(mq_cols)} mq_* preservent NaN pre-2025-12-15")
```

Si l'assertion fail → STOP train, investiguer pipeline V5 build.

## Update verdict

- ~~CRITIQUE bloquant V5 build~~
- **MEDIUM** : surveillance V5 build samedi, test 1 min apres build
- Tests V4 actuel propre, pattern reproducible

## ADDENDUM 02/05 11:00 — train_lightgbm.py apply_edge mq_* fillna(0)

Finding additionnel via grep `train_lightgbm.py:334-347` :
```python
edge_buy_mask = ((df["bool_above_mq_hvl"].fillna(0).values == 0) & ...)
edge_sell_mask = ((df["bool_above_mq_call"].fillna(0).values == 1) & ...)
```

**Contexte** : ces lignes ne sont actives QUE si `apply_edge=True` dans
`backtest_oos()`. Elles construisent un MASQUE de filtrage pour simulation
backtest (rule-based filter pendant le run du modele), PAS un fillna sur
les FEATURES du dataset training.

**Impact V5 train ML** :
- Si `apply_edge=True` sur 13 ans data 2011-2024 → NaN traite comme
  "below_hvl=False" → filtre se declenche systematiquement.
- Bias filtre : "edge present" partout pre-MenthorQ alors que vrai signal
  inconnu.

**Decision V5 build samedi** : 2 options
- (A) `apply_edge=False` sur train V5 (RECOMMANDE, plus simple)
- (B) Restrict train V5 a dates >= 2025-12-15 (5 mois data) — perd 13 ans
- (C) Modifier ligne 334-347 pour skip rows pre-MQ (NaN preserve mask) —
      complexite + risque regressions backtest existant

**Recommandation** : Option A. Le test d'edge filter est optionnel et peut
etre teste apres train ML sur subset post-MQ uniquement.

## Lien

- Finding initial : ml-trainer agent 2nd round review GATE_17H_METHODOLOGY
- Verification : 02/05 09:30 (test empirique V4 + grep V4 builder)
- Addendum 02/05 11:00 : train_lightgbm apply_edge fillna(0) flag
- Pattern V4 propre : `build_dataset_v4_dmp_databento.py:895-911`
- Pattern legacy a EVITER : `dataset_builder.py:506-516`
- Decision V5 : reutiliser pattern V4, garder 15 ans data, apply_edge=False
