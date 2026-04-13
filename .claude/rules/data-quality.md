# Regles DATA QUALITY (pipeline ML V2)

**Regle souveraine** (Jackson 13/04/2026) :
> "AVOIR DE DONNER PROPRE EST LA BASE POUR UN BOT DE TRADING"

Hierarchie des regles V2 :
1. **Qualite des donnees** (souverain)
2. **Symetrie ES/NQ** (subordonne a la qualite)
3. **Screening Spearman** (implementation de 2)

---

## NE JAMAIS FAIRE

### Rechute #1 — Valider un dataset sur sa FORME uniquement
Symptomes :
- Verifier shape (7480, 129), symetrie colonnes, sum ES+NQ=0
- Dire "mission accomplie" sans regarder le CONTENU des features
- Confondre "passe le screening Spearman" avec "feature de qualite"

**Le screening Spearman ne detecte pas les fuites d'info.** Une feature peut avoir rho=0.08 uniquement parce qu'elle revele l'instrument au modele (ex: dist_swing_high qui vaut 31 ES vs 160 NQ).

### Rechute #2 — Invoquer "non-bloquant" pour reporter un vrai probleme
Si un audit flag une feature polluee et que je dis :
> "A investiguer apres 15 jours de data, pas avant"

C'est une rechute. Une feature polluee aujourd'hui = un modele pollue demain. **Le dataset doit etre propre AVANT le training, pas apres.**

### Rechute #3 — Ignorer les absolus de prix/volume
Jamais stocker dans le dataset :
- Des niveaux de prix (`mq_top_gex_strike_1 = 6707`, `amd_asia_high = 6662`)
- Des ticks non normalises (`ib_range_ticks`, `swing_range_ticks`, `ovn_range_ticks`)
- Des volumes absolus (`total_vol`, `buy_vol`, `sell_vol`, `delta_day`)
- Des distances en points bruts (`dist_vwap_m`, `dist_cur_vpoc`)

Toujours preferer :
- **Distances normalisees** : `/ atr` ou `/ ib_range`
- **Ratios** : `buy_vol / total_vol`, `delta_bar / atr`
- **Pourcentages** : `dist / price * 100`
- **Bools** et **scores [0-1]** : comparables par nature

---

## TOUJOURS FAIRE

### 1. Lancer quality_validator.py apres chaque dataset_builder
```bash
python -X utf8 CORE/quality_validator.py
```
Le validator est appelle automatiquement en fin de `dataset_builder.py --current`. S'il leve `QualityViolation`, le dataset **n'est pas sauvegarde**. C'est normal, c'est le garde-fou.

### 2. Avant de dire "GO" sur un dataset
Verifier **4 criteres** (le validator les check automatiquement, mais garder en tete) :
1. Aucune feature avec `|mean_ES - mean_NQ| / std_union > 0.5` (sauf exemptees)
2. Aucune feature en ticks/range/dist avec `std_NQ / std_ES > 2.5` sans suffixe `_atr`
3. Aucune feature avec `max / |p99| > 100` (outlier explosion)
4. Aucune feature quasi-constante (`std < 1e-6` ou top_value_freq > 95%)

### 3. Si une feature YELLOW est flaggee
Ne pas la passer en GREEN sans :
- Lire le code source de son calcul
- Comprendre pourquoi elle est asymetrique/polluee
- Choisir : DROP, NORMALIZE, ou exemption explicite (avec commentaire justifiant)

### 4. Ajouter des exemptions explicites dans quality_validator.py
Si une feature est legitimement differenciee (ex: `mq_iv_30d` ES 18% vs NQ 22%), l'ajouter a `NATURALLY_DIFFERENT` avec un commentaire justifiant la raison.

Si une feature est partagee ES=NQ (ex: `vix_level`), l'ajouter a `SHARED_FEATURES`.

**Jamais baisser les seuils globaux pour faire passer une feature.** Toujours preferer une exemption nommee.

---

## Protocole de fix en cas de violation

Si `quality_validator.py` bloque le dataset :
1. Lire le rapport complet (red flags + raisons)
2. Trier par type de violation (INSTRUMENT / VOLATILITY / PRICE_LEVEL / OUTLIER / CONSTANT)
3. Pour chaque feature RED :
   - **Absolu de prix** : DROP et remplacer par `dist_*_atr`
   - **Ticks non normalise** : DROP et remplacer par `/atr` ou `/ib_range`
   - **Volume absolu** : DROP et remplacer par ratio `/ total_vol`
   - **Outlier explosion** : winsoriser ou log1p ou clip p99
   - **Quasi-constante** : investiguer source, probable bug C++ ou seuil mal calibre
4. Regenerer le dataset : `python -X utf8 CORE/dataset_builder.py --current`
5. Verifier que le validator passe (ou liste un sous-ensemble plus petit de red flags)
6. Iterer jusqu'a zero red flag

---

## Commandes rapides

```bash
# Audit complet datasets existants (read-only, ne modifie rien)
python -X utf8 CORE/quality_validator.py

# Audit en mode non-strict (affiche mais ne leve pas exception)
python -X utf8 CORE/quality_validator.py --no-strict

# Regenerer datasets avec validation automatique
python -X utf8 CORE/dataset_builder.py --current

# Slash command complete (audit + rapport 4 agents)
/audit-features
```

---

## Liens

- Code : `CORE/quality_validator.py`
- Appel : `CORE/dataset_builder.py` (fin de main())
- Memory : `feedback_data_quality_first.md`, `feedback_ia_traps_detection.md` (pattern 11)
- Slash : `/audit-features`
- Subagent : `quality-auditor`
