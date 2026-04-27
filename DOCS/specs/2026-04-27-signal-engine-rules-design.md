# signal_engine_rules V1 — Design Spec

**Date** : 2026-04-27
**Statut** : Validé par Plan agent (GO-AVEC-RESERVES) + Jackson (OK final)
**Schema version** : 1.0

---

## 1. Contexte et motivation

### 1.1 Pourquoi cette feature

Pipeline ML actuel : edge ML ES BUY PF 1.09 (post-fix anti-leak v5b, marginal mais réel). Edge ML ES SELL PF 0.64 (NO-GO). Plafond empirique sur 28 stratégies trader testées = PF 1.29 (JL2 Long Reversal Pattern, mais identifié comme bruit statistique post-audit). Jackson est rentable LIVE (Topstep +$665 / 35 min le 22/04) avec une combinaison de signaux dashboard + sizing dynamique + skip jours mous + lecture order flow.

**Plan B Jackson (validé 27/04 soir)** :
1. Trader en mode "rules-only" (sans ML) avec règles déjà identifiées comme robustes
2. Collecter des données comportementales sur chaque trade (features pre-trade + outcome)
3. Avec 100-300 trades réels, re-entraîner ML sur dataset annoté
4. Mois 4+ : ML augmenté par règles trader (meta-labeling Lopez ch.3)

`signal_engine_rules` est le **middleware tagger** qui supporte ce plan : pour chaque bar, il calcule N tags binaires/scorés (1 par règle validée) sans s'immiscer dans la décision d'entry du paper_trader. Le paper_trader continue de décider via `conseil_global` du dashboard. Les tags sont **annexés au snapshot trade** pour analyse post-hoc.

### 1.2 Différence vs RuleEngine V1 (rule_engine.py 02/04)

RuleEngine V1 (593 LOC) = **moteur de décision composite** avec voting/scoring sur 16 règles. Identifié comme pattern 11 V1 risqué (cascading rules → 65% faux rejets historique).

`signal_engine_rules` V1 = **library de fonctions pures + tagger middleware**. Pas de voting, pas de cascading. Chaque rule est isolée, testable, traçable. Le paper_trader décide indépendamment.

### 1.3 Goal

- ✅ Permettre le paper trading rules-only (déjà 80% en place via `conseil_global`)
- ✅ Collecter dataset comportemental robuste (1 ligne par bar avec tags des règles fired)
- ✅ Préparer le re-training ML futur (dataset annoté > dataset brut)
- ❌ NON-GOAL : remplacer le decision engine du paper_trader (option C confirmée par Jackson)
- ❌ NON-GOAL : courir en sub-minute latence (V2 si besoin)

---

## 2. Architecture

### 2.1 Modules

```
CORE/signal_engine_rules/
├── __init__.py
├── rules.py            ← Library : 9 fonctions pures rule_X(features: dict) -> RuleTag
├── batch_tagger.py     ← Wrapper batch : parquet v5b → parquet v5c enrichi
├── schema.py           ← RuleTag dataclass + RULES_SCHEMA_VERSION="1.0"
└── tests/
    ├── test_rules.py            ← 9 tests unitaires sur bars synthétiques
    └── test_no_lookahead.py     ← Future divergente → output identique
```

**`live_tagger.py` reporté V2** (batch-only V1 avec polling 60s, justifié section 3.2).

### 2.2 RuleTag dataclass (schema.py)

```python
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

RULES_SCHEMA_VERSION = "1.0"

@dataclass
class RuleTag:
    """Output d'une rule. Riche pour traçabilité comportementale ML-ready."""
    direction: int                  # -1 SELL, 0 nothing, +1 BUY
    strength: float                 # [0, 1] distance normalisée au threshold
    version: str                    # = RULES_SCHEMA_VERSION
    fired_at: pd.Timestamp          # ts_event de la bar
    meta: dict = field(default_factory=dict)  # ex: {"dist_color_up_pct": 0.0003}

    def to_dict(self) -> dict:
        return {
            "direction": int(self.direction),
            "strength": float(self.strength),
            "version": self.version,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "meta": self.meta,
        }
```

### 2.3 Format sérialisation

- **Parquet (batch)** : 2 colonnes par rule = `<rule_name>_dir` (int8) + `<rule_name>_strength` (float32) = 18 cols totales
- **JSONL (live, V2)** : dataclass complet avec meta

---

## 3. Les 9 règles V1

### 3.1 Liste finale (validée Plan agent)

| # | Tag name | Source | Anti-leak guard |
|---|---|---|---|
| 1 | `long_up_bar` | Acosta long bar | RTH + bar closed |
| 2 | `long_dn_bar` | Acosta long bar | RTH + bar closed |
| 3 | `color_up_proximity` | top SHAP v5b #4 | bar closed |
| 4 | `color_dn_proximity` | top SHAP v5b #3 | bar closed |
| 5 | `color_zone_break` | JC2 PF 1.11 NQ | bar closed |
| 6 | `cluster_at_high` | feature dataset rare | bar closed |
| 7 | `cluster_at_low` | feature dataset rare | bar closed |
| 8 | `failed_ib_poor_high` | H3 PF 1.18 NQ | **mins_et >= 630** obligatoire |
| 9 | `edge_zone_fire` | JE setup live Jackson | bar closed |

**JL2 SORTIE V1** : `long_up_dn_pattern` + `long_dn_up_pattern` ont 99.7% top_freq = QUASI_CONST (cf `DOCS/AUDIT_FEATURES_V4_RAPPORT_28042026.md`). Feature morte ES (Extension Lines off, cf CLAUDE.md). PF 1.29 sur ~70 trades = bruit statistique. À ré-évaluer V2 sur v5b avec ≥100 trades.

### 3.2 Détails algorithmiques

#### Rule 1 — `long_up_bar`

```python
def rule_long_up_bar(features: dict) -> RuleTag:
    """Long up bar continuation (Acosta long-bar pattern)."""
    if features.get("long_up_bar", 0) != 1:
        return RuleTag(0, 0.0, RULES_SCHEMA_VERSION, features.get("ts_event"))
    if features.get("is_in_us_cash", 0) != 1:
        return RuleTag(0, 0.0, RULES_SCHEMA_VERSION, features.get("ts_event"))
    return RuleTag(
        direction=+1,
        strength=1.0,  # binary fire pour long bars
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"is_in_us_cash": 1},
    )
```

#### Rule 3 — `color_up_proximity`

```python
def rule_color_up_proximity(features: dict) -> RuleTag:
    """BUY si proche zone color_up + delta day positif."""
    d_up = features.get("dist_color_up_nearest_pct")
    if d_up is None or pd.isna(d_up):
        return RuleTag(0, 0.0, ...)
    if abs(d_up) > 0.0005:  # > 0.05%
        return RuleTag(0, 0.0, ...)
    delta_dir = features.get("delta_day_dir", 0)
    if delta_dir <= 0:
        return RuleTag(0, 0.0, ...)
    # Strength = inverse normalisée de la distance (plus proche = plus fort)
    strength = 1.0 - min(abs(d_up) / 0.0005, 1.0)
    return RuleTag(+1, strength, RULES_SCHEMA_VERSION, features.get("ts_event"),
                   meta={"dist_color_up_pct": float(d_up)})
```

#### Rule 8 — `failed_ib_poor_high` (H3)

```python
def rule_failed_ib_poor_high(features: dict) -> RuleTag:
    """Failed IB break = poor high → reversal (Crabel 1990)."""
    # ANTI-LEAK GUARD obligatoire : IB pas complete = NaN
    mins_et = features.get("mins_et", 0)
    if mins_et < 630:  # avant 10:30 ET
        return RuleTag(0, 0.0, ...)
    br_up = features.get("ib_broken_up", 0)
    br_dn = features.get("ib_broken_down", 0)
    pos = features.get("ib_position_pct")
    if pos is None or pd.isna(pos):
        return RuleTag(0, 0.0, ...)
    # Broke up mais revient dans IB → SHORT
    if br_up == 1 and -0.5 < pos < 0.5:
        return RuleTag(-1, 0.7, ..., meta={"ib_position_pct": pos})
    if br_dn == 1 and -0.5 < pos < 0.5:
        return RuleTag(+1, 0.7, ..., meta={"ib_position_pct": pos})
    return RuleTag(0, 0.0, ...)
```

(Logique simplifiée pour les autres rules dans plan d'implémentation détaillé.)

### 3.3 Anti-leak invariants (NON-NÉGOCIABLES)

1. **Tagger UNIQUEMENT sur bars closed** : `live_tagger` (V2) doit attendre bar fermée. Batch tagger sur parquet historique = bars closed par définition.
2. **Guard IB pré-10:30** : rule 8 retourne RuleTag(0,...) si `mins_et < 630`. Test obligatoire dans `test_no_lookahead.py`.
3. **Aucune feature broadcast leaky** : la liste blacklist v5b (ovn_*, ib_* pré-fix, above_open_*) n'est PAS utilisée. Les rules utilisent uniquement features post-fix v5b.
4. **Pas de `bars_since_*` cumulant futurs** : aucune des 9 rules V1 utilise ces features. Si V2 les utilise, vérifier shift backward only.

---

## 4. Flow d'exécution

### 4.1 Batch tagger (V1)

```
parquet v5b (351K bars × 175 features)
        ↓
batch_tagger.py
  - Charge parquet
  - Pour chaque rule dans RULES_V1 :
      - apply_vectorized(df) → 2 colonnes (direction int8, strength float32)
  - Concat avec df original
        ↓
parquet v5c (parquet v5b + 18 colonnes rules tags)
```

**Coût** : ~5-10 min sur 351K bars × 9 rules vectorized pandas.

### 4.2 Live tagger (V2 reporté)

Justification report V2 : polling 60s sur dashboard JSONL suffit pour MVP collecte. `mia_paper_trader.py` poll déjà à 10s. Tags annexés au snapshot trade à la **CLOSE** du trade (lookback), pas à l'OPEN — évite race condition.

### 4.3 Intégration paper_trader (V1) — sans live_tagger

Architecture sans live_tagger en V1 :

```
[batch_tagger.py] tourne en cron 60s
        ↓
   Lit parquet v5b courant (mis à jour par dataset_builder)
        ↓
   Calcule tags pour les N dernières bars (par défaut N=120 = 2h lookback)
        ↓
   Écrit parquet v5c.parquet (atomic write : v5c.tmp → rename)

[mia_paper_trader.py] (poll 10s existant, pas modifié)
        ↓
   À l'OPEN du trade : capture features (déjà fait, snapshot ligne 1390-1411)
        ↓
   À la CLOSE du trade : ouvre parquet v5c, lookup les tags par ts_event entre 
                         (open_ts - 5min) et close_ts (window N bars autour du trade)
        ↓
   Append au snapshot dans la clé `rules_fired`
```

Modification dans `mia_paper_trader.py` :
- Field snapshot : `rules_fired: {<rule_name>: {direction: int, strength: float}}` à la close
- Field snapshot : `rules_schema_version: "1.0"`
- Helper `_lookup_rules_tags(ts_event_open, ts_event_close) -> dict` qui lit parquet v5c

**Cron batch_tagger** : Task Scheduler Windows ou nssm service (cohérent avec autres services VPS, cf `reference_nssm_dashboard.md`).

**Aucun changement logique entry** — toujours via `conseil_global` dashboard.

**Ambiguïté résolue** : pas de race condition car le tag est lu à la CLOSE du trade, pas à l'OPEN. Latence acceptable pour annotation comportementale (≠ latence pour decision).

---

## 5. Tests (obligatoires V1)

### 5.1 `test_rules.py`

Pour chaque rule (9 tests) :
- Bar synthétique qui DOIT firer → vérifier `direction != 0`
- Bar synthétique qui NE DOIT PAS firer → vérifier `direction == 0`
- Bar avec NaN sur feature critique → vérifier `direction == 0` (pas crash)

Estimé : 30 min total.

### 5.2 `test_no_lookahead.py` (NON-NÉGOCIABLE)

- Charger 100 bars test
- Pour chaque rule, calculer le tag à la bar i
- Modifier bars i+1, i+2, ... avec valeurs aléatoires
- Re-calculer tag bar i → DOIT être identique
- Si différence détectée → test FAIL → leak structurel à fixer

Justification : incident 27/04 21:30 (3 leaks dans v5 → 13h fix). Cette suite empêche réémergence.

### 5.3 `test_wrappers.py` (V2, optionnel)

Tests d'intégration batch_tagger sur sample parquet. Reporté V2 (plomberie, casse visible).

---

## 6. Roadmap V2

**Post-paper trading 30 jours + 100+ trades collectés :**

| Feature | Coût estimé | Priorité |
|---|---|---|
| `poc_migration_signal` (top SHAP #1) | 2-3j re-coding | Haute |
| `open_drive_first_hour_fire` | 1-2j | Haute |
| `jl2_long_reversal` re-évalué v5b | 1j si ≥100 trades | Moyenne |
| `menthorq_confluence_2plus_fire` | Attendre v6 post-purge MQ (juin 2026) | Bloquée |
| `live_tagger.py` Databento WebSocket | 3-5j | Basse (si MVP suffisant) |
| Score composite agrégé `composite_score` | 2-3j post-rules validées | Basse |

---

## 7. Risques et mitigations

| Risque | Mitigation |
|---|---|
| Rule fire trop fréquemment (saturation) | `test_rules.py` vérifie distribution attendue (cohérent avec battery_v5_full) |
| Rule jamais fire (feature constante) | Audit `top_freq < 99%` et `nunique > 5` avant ajout V1 (cf JL2 sortie) |
| Leak future détecté post-déploiement | `test_no_lookahead.py` obligatoire ; audit Plan agent annuel |
| Race condition live_tagger ↔ paper_trader | V2 reportée, polling synchrone V1, tag à la CLOSE |
| Format RuleTag breaking change V2 | `version` field dans dataclass + backward compat checker |

---

## 8. Questions ouvertes

Aucune. Toutes les questions de design ont été tranchées par Jackson + Plan agent.

---

## 9. Critères d'acceptation V1

- [ ] 9 fonctions `rule_X(features: dict) -> RuleTag` codées dans `rules.py`
- [ ] `RuleTag` dataclass dans `schema.py` avec `RULES_SCHEMA_VERSION = "1.0"`
- [ ] `batch_tagger.py` tourne sur parquet v5b → produit v5c (18 cols ajoutées)
- [ ] `test_rules.py` : 9 tests passent (1 par rule)
- [ ] `test_no_lookahead.py` : 9 tests passent (1 par rule)
- [ ] `mia_paper_trader.py` : snapshot enrichi avec `rules_fired` + `rules_schema_version`
- [ ] Document `DOCS/BOT_CHANGELOG.md` mis à jour
- [ ] Run smoke batch_tagger sur sample 1000 bars : pas d'exception, distribution cohérente

---

**Spec self-review : à faire après écriture (étape suivante).**
