# MÉMO — VALIDATION POST-ROLLOVER H26 → M26

**De** : Jackson (via Claude Opus)
**Pour** : Agent de test
**Date** : 16/03/2026
**Objet** : Procédure de validation des données DMP après rollover trimestriel

---

## CONTEXTE

Le rollover CME trimestriel a eu lieu : les contrats H26 (Mars) ont été remplacés par M26 (Juin). Tous les charts Sierra Chart ont été mis à jour manuellement. Le bug MQ_GAMMA NQ (null car chart 23 encore sur NQH26) est corrigé.

**Action requise** : À la fin de la journée de trading du 16/03/2026, valider que les données JSONL produites par le DMP sont propres sur les nouveaux contrats M26.

---

## FICHIERS À COLLECTER (fin de journée)

Les fichiers JSONL de la session du jour se trouvent dans :

```
D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\20260316_ES.jsonl
D:\TRADING_SIERRA_CHART_AUTO\DATA\NQ\20260316_NQ.jsonl
```

---

## ÉTAPE 1 — VALIDATION RAPIDE (dmp_validator.py)

```bash
cd D:\TRADING_SIERRA_CHART_AUTO\CORE
python dmp_validator.py ..\DATA\NQ\20260316_NQ.jsonl ..\DATA\ES\20260316_ES.jsonl
```

**Vérifications automatiques** (13 tests) :
1. Schema : 250 colonnes (Schema 3.6.0 avec RVOL)
2. Timestamps monotones, pas de gaps > 5 min
3. Cohérence volume : `buy_vol + sell_vol = total_vol`
4. Cohérence delta : `delta_bar = buy_vol - sell_vol`
5. Cohérence pct : `ask_pct + bid_pct = 1.0`
6. Cohérence BN : `bn_score_raw = bn_score_bull - bn_score_bear`
7. Signaux MUST_FIRE (COLOR UP/DN, PRESSURE, etc.) > seuil minimal
8. Signaux SHOULD_FIRE (LONG UP/DN, EDGE, etc.) au moins 1× si >50 barres
9. Distances non-null (dist_ext_color_up/dn, dist_ext_edge_buy/sell)
10. Features range doivent varier (range_pos, momentum, cvd)
11. Bornes logiques (price 1000-50000, ask_pct 0-1, etc.)
12. Colonnes critiques présentes (bn_color_up_2, retest_high_count, etc.)
13. Sessions correctement détectées (Asia/London/US)

**⚠️ NOTE** : `dmp_validator.py` attend `EXPECTED_COLS = 246` (schema 3.5.2). Le schema actuel est 3.6.0 (250 colonnes avec RVOL). Il faudra mettre à jour cette constante **ou** ignorer le warning schema si 250 colonnes sont détectées. Les 4 colonnes supplémentaires sont : `rvol`, `rvol_zscore`, `rvol_buy`, `rvol_sell` (+ `rvol_absorb_buy`, `rvol_absorb_sell` = 6 au total → vérifier le compte exact).

---

## ÉTAPE 2 — VÉRIFICATIONS MANUELLES ROLLOVER

Ouvrir les JSONL et vérifier **spécifiquement** :

### 2a. Contrat correct
```python
import json
with open("20260316_NQ.jsonl") as f:
    first = json.loads(f.readline())
    last_lines = f.readlines()
    last = json.loads(last_lines[-1])

print(f"Premier contrat: {first['contract']}")  # Doit être NQM26-CME
print(f"Dernier contrat: {last['contract']}")   # Doit être NQM26-CME
# PAS de NQH26-CME → rollover OK
```

Faire pareil pour ES (doit être ESM26-CME, pas ESH26-CME).

### 2b. MQ_GAMMA non-null
```python
# Vérifier que MenthorQ Gamma fonctionne (le bug était là)
nq_lines = [json.loads(l) for l in open("20260316_NQ.jsonl")]
us_bars = [l for l in nq_lines if l.get('session_id') == 'US']
gamma_null = sum(1 for l in us_bars if l.get('dist_mq_gamma') is None)
print(f"MQ_GAMMA null en US: {gamma_null}/{len(us_bars)}")
# Doit être 0 (ou très faible). Si >50% → rollover chart 23 pas fait.
```

### 2c. RVOL actif
```python
# Les 6 champs RVOL doivent exister et computer après 5 barres
rvol_fields = ['rvol', 'rvol_zscore', 'rvol_buy', 'rvol_sell', 'rvol_absorb_buy', 'rvol_absorb_sell']
for field in rvol_fields:
    vals = [l.get(field) for l in us_bars]
    non_null = sum(1 for v in vals if v is not None)
    print(f"  {field}: {non_null}/{len(us_bars)} non-null")
# rvol doit être non-null après les ~5 premières barres de chaque session
```

### 2d. Pas de null patterns anormaux
Les 4 patterns null **normaux** (ne pas compter comme erreurs) :
- `dist_big_*` null en session Asia → normal, pas de big orders
- `dist_ext_long_up/dn` null → Bug #8 (Extension Lines non activées dans SC)
- `dist_mq_put_0dte` null pour ES → MenthorQ combine Put Support + Put 0DTE dans sg1
- `bars_since_retest_high` null → aucun retest n'a eu lieu, normal

Tout **autre** champ massivement null en session US = problème potentiel.

---

## ÉTAPE 3 — BENCHMARK COMPLET (mia_bench.py)

```bash
cd D:\TRADING_SIERRA_CHART_AUTO\CORE
python mia_bench.py .
```

Ce script lance 13 tests automatiques :
1. Fonctionnel (parité C++ game_changers, schema)
2. Inventaire (barres par session, couverture)
3. Ranking bootstrap (corrélations features)
4. Cross-asset (ES↔NQ)
5. Par régime (TREND vs RANGE)
6. Seuils (calibration)
7. Game changers (Market Profile)
8. Verdict (synthèse)
9. Signal vs Bruit (features significatives)
10. Noyau dur backtest
11. Wall tracker (GEX/Gamma)
12. Session timing
13. DMP Health Check (cohérence volume, BN scores)

Le rapport est sauvegardé dans `MIA_BENCH_REPORT.txt`.

**Critères de validation** :
- Test 13 (DMP Health) : zéro erreur cohérence volume + BN score
- Schema : ≥250 colonnes (3.6.0)
- Contrat : uniquement M26, aucun H26

---

## ÉTAPE 4 — CHECKLIST ROLLOVER CHARTS

Confirmer que **tous** ces charts SC pointent vers le bon contrat M26 :

| Chart # | Rôle | Contrat attendu |
|---------|------|-----------------|
| 1 | ES Footprint (BN) | ESM26-CME |
| 2 | NQ Footprint (BN) | NQM26-CME |
| 15 | VIX + MenthorQ | Pas de contrat (VIX) |
| 23 | NQ Barres (MQ) | NQM26-CME |
| 25 | ES Barres (MQ) | ESM26-CME |
| 26 | ES Volume Profile | ESM26-CME |
| 27 | NQ Volume Profile | NQM26-CME |
| 28 | ES CVD + Swing | ESM26-CME |
| 29 | NQ CVD + Swing | NQM26-CME |
| 30 | NQ Composite Profiles | NQM26-CME |
| 31 | ES Composite Profiles | ESM26-CME |

**+ DMP_Config** : vérifier que le symbole dans la config DMP pointe aussi vers M26.

---

## FICHIERS PYTHON À PARTAGER AVEC L'AGENT

L'agent a besoin de ces fichiers pour exécuter les tests. Tous sont dans `D:\TRADING_SIERRA_CHART_AUTO\CORE\` :

### Obligatoires (exécution des tests)
| Fichier | Rôle | Lignes |
|---------|------|--------|
| `dmp_validator.py` | Validation quotidienne schema + cohérence | ~350 |
| `dmp_reader.py` | Lecture JSONL → DataFrame | ~215 |
| `mia_bench.py` | Benchmark 13 tests automatiques | ~912 |
| `rolling_features.py` | 26 features ctx_* (requis par bench) | ~424 |
| `intermarket_features.py` | 10 features im_* (requis par bench) | ~369 |
| `game_changers.py` | Market Profile parité C++ (requis par bench) | ~945 |

### Optionnels (contexte mais pas requis pour les tests)
| Fichier | Rôle |
|---------|------|
| `mia_entry.py` | Moteur d'entrée (utilisé par bench test 12) |
| `mia_sltp.py` | Moteur SL/TP Python |
| `rvol.py` | Module RVOL Python |

### Documentation de référence
| Fichier | Contenu |
|---------|---------|
| `MIA_LEXIQUE_252_FEATURES.docx` | Lexique complet des 250 colonnes schema 3.6.0 |
| `README_MIA_PIPELINE.md` | Architecture pipeline, ordre des modules |
| `MIA_PIPELINE_RECAP.md` | Résultats ranking features, leçons apprises |

### Données du jour (à copier après fermeture session)
```
D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\20260316_ES.jsonl
D:\TRADING_SIERRA_CHART_AUTO\DATA\NQ\20260316_NQ.jsonl
```

---

## RÉSUMÉ : COMMANDES À EXÉCUTER

```bash
# 1. Validation rapide (2 secondes)
cd D:\TRADING_SIERRA_CHART_AUTO\CORE
python dmp_validator.py ..\DATA\NQ\20260316_NQ.jsonl ..\DATA\ES\20260316_ES.jsonl

# 2. Vérif contrat (10 secondes)
python -c "
import json
for sym in ['NQ','ES']:
    path = f'../DATA/{sym}/20260316_{sym}.jsonl'
    lines = open(path).readlines()
    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    print(f'{sym}: first={first[\"contract\"]} last={last[\"contract\"]} ({len(lines)} barres)')
"

# 3. Benchmark complet (30-60 secondes)
python mia_bench.py .

# 4. Lire le rapport
type MIA_BENCH_REPORT.txt
```

**Critère GO/NO-GO** : Si les 3 conditions sont remplies, la pipeline DMP est validée post-rollover :
1. `dmp_validator.py` : zéro erreur (warnings OK)
2. Contrats = uniquement M26, aucun H26
3. `mia_bench.py` Test 13 DMP Health : zéro erreur

---

*Mémo généré le 16/03/2026 — Pipeline DMP Schema 3.6.0 (250 colonnes)*
