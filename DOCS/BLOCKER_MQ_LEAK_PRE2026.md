# BLOCKER — Leak look-ahead mq_* pre-2026

**Date** : 2026-05-02 01:50 UTC (nuit, finding agent ml-trainer 2nd round)
**Severite** : CRITIQUE — bloque V5 build samedi
**Status** : DOCUMENTE, fix samedi 9h AVANT V5 build

## Bug confirme

`CORE/dataset_builder.py:516` :
```python
medians = df_clean.median()
df_clean = df_clean.fillna(medians)
```

S'applique a **toutes les features** y compris `mq_*` (MenthorQ).

## Consequence

MenthorQ data dispo uniquement depuis 2026 (collecte demarree). Sur dataset
V5 15 ans (2011-2026) :

- Bars 2011-2024 : `mq_call`, `mq_put`, `mq_hvl`, etc. = NaN (pas de fichier
  MenthorQ pour ces dates)
- `_compute_menthorq` ligne 707-763 : `enriched_parts` ne recoit rien pour
  ces dates, sub n'est pas enrichie → mq_* reste NaN
- Ligne 515-516 fillna : `medians = df_clean.median()` calcule median sur
  **toute la periode**, dominee par les valeurs 2026 (les seules non-NaN)
- Ligne 516 : `fillna(medians)` applique median 2026 sur bars 2011

**Impact** : LightGBM "voit" indirectement des stats 2026 sur sa donnee
2011-2024 d'entrainement = leak look-ahead massif.

## Pourquoi c'est CRITIQUE pour V5

- Train V5 sur 15 ans data avec mq_* → faux edge garanti
- DSR samedi sera artificiellement bon
- Hold-out 12 mois (mai 2025 - mai 2026) heuristique aussi pollue (2025 = pas
  de MenthorQ → median 2026 leak)
- Faux GO V5 → deploy paper avec edge bidon → perd 2-4 semaines

## Fix samedi 9h (3 options)

### Option A — Restreindre dataset V5 a 2024-2026 (recommandee)

```python
# Dans build_v5_dataset.py
df_v5 = df_v5[df_v5["ts_event"] >= "2024-01-01"]
```

Pro : honnete, pas de leak, scope clair
Contra : ~2 ans data au lieu de 15 ans (mais MenthorQ exploitable seulement
sur cette periode de toute facon)

### Option B — Remplacer fillna(medians) par fillna selectif

```python
# Pour features mq_*, garder NaN (LightGBM gere natif)
mq_cols = [c for c in df_clean.columns if c.startswith(("mq_", "dist_mq_"))]
non_mq_cols = [c for c in df_clean.columns if c not in mq_cols]
medians = df_clean[non_mq_cols].median()
df_clean[non_mq_cols] = df_clean[non_mq_cols].fillna(medians)
# mq_* restent NaN sur dates pre-MenthorQ
```

Pro : garde 15 ans data
Contra : LightGBM va apprendre que NaN mq_* signifie "ancienne donnee" (proxy
implicite de la date) → leak indirect different mais reel

### Option C — Mediane par fenetre temporelle

```python
# Calcul median rolling 90j vs static
medians_rolling = df_clean.rolling("90D").median()
df_clean = df_clean.fillna(medians_rolling)
```

Pro : evite leak avenir (median calculee sur passe seulement)
Contra : complexe, premier 90j problematique

## Recommandation finale

**Option A** : restreindre V5 a 2024-2026 (~2 ans).

Justifications :
1. MenthorQ exploitable seulement post-2026 de toute facon
2. Pas de leak look-ahead
3. Volume data suffisant (2 ans × ~250 jours × ~6000 bars/j = 3M bars 1m)
4. Scope V5 propre = honnete

## Test bloquant samedi 9h

Avant V5 build :
```bash
python -X utf8 -c "
import pandas as pd
df = pd.read_parquet('DATA/DATASETS/v4/some_recent.parquet')
mq_cols = [c for c in df.columns if c.startswith('mq_')]
for c in mq_cols[:5]:
    print(f'{c}: NaN ratio = {df[c].isna().mean():.2%}, '
          f'min_date_non_nan = {df.loc[df[c].notna(), \"ts\"].min()}')
"
```

Si `min_date_non_nan` > 2024 → confirmation leak en post-fillna setup.

## Lien

- Finding par : ml-trainer agent 2nd round review GATE_17H_METHODOLOGY
- Fichier : `CORE/dataset_builder.py:516`
- Memory : `feedback_data_quality_first.md` (5 couches defense)
- Decision tree V5 : `DOCS/GATE_17H_METHODOLOGY.md`
