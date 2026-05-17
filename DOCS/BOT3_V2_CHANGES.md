# Bot 3 v2 — Recap consolide des modifications

**Date** : 2026-05-17
**Statut** : v1.0 — review code-reviewer + market-analyst appliquees (12 fixes).
**Cross-references** :
- `DOCS/BIAS_DIRECTION_DETECTION_CLARIFICATION.md` v1.0 (source unique de
  verite bias/regime/decision).
- `.claude/rules/critical-tasks-review.md` (8 criteres review TIER 1).
- `.claude/memory/feedback_lightgbm_no_composite_indicators.md` (anti
  Pattern 11).
- `.claude/memory/feedback_data_mining_trap.md` (DSR Lopez obligatoire).

## Pourquoi Bot 3 v2

**Probleme actuel** : Bot 3 prend des trades "a contre-sens" (Jackson 12/05).
Cause racine confirmee : `bot3_decision_engine.evaluate_decision()` ignore
totalement `bias_calculator.compute_bias` et `regime_engine.compute_regime`.
Seul le `level["side"]` (fixe) + `dist_signed` (positionnel) + funnel NEUTRAL
guident la decision.

Le Bot 3 a ete cree avant que ces features n'existent. Resultat : il peut
trader LONG sur un IB_LOW en plein jour BEAR fort sans aucun garde-fou
directionnel.

**Verdicts empiriques 14 mois 2024-2025 + janv-mai 2026** :
- Bot 3 NQ : PF 1.05 baseline marginal.
- Bot 3 ES : PF 0.66/0.83 broken sur 14m (catastrophic — voir audit
  cluster `stats_per_level_full_14m_v3.csv` post-regen).

**Objectif Bot 3 v2** :
1. Reduire trades contre-sens (perte directe).
2. Ajouter confluences identifiees post-creation (COLOR/LONG BAR autonomes
  NOGO mais 3 confluences NQ GO).
3. Bloquer Session × Level combinaisons mesurees a -$107k 14m.
4. Filtrer ATR-too-low ES (mesure -$30k 14m).
5. Brancher sur source live (lag actuel V4 = 10-22 min, perte d'edge open).

## AXES de modification

### AXE 1 — Source de donnees live (lag minimal)

**Etat actuel** : Bot 3 lit `DATA/datasets/v4_enriched/symbol=ES.c.0/...`
avec lag 10-22 min (pipeline Phase B batch). En live cela signifie que
quand le prix touche un niveau a `14:05:30`, le bot ne le voit qu'a `14:25-14:30`.
Sur des setups breakout/rejet open ce lag est letal.

**Cible** : lire `DATA/live_enriched/{SYM}/{YYYYMMDD}_{SYM}.jsonl` (~435
cols, lag ~5-10s).

**Bloqueurs decouverts (cf BIAS_DIRECTION_DETECTION_CLARIFICATION.md D.4)** :
- 14/27 champs DMP necessaires au regime sont **ABSENTS** de live_enriched
  (notamment `new_swing_high/low`, `delta_divergence`, `ib_broken_up/down`,
  `day_type`, `single_print_count`, `profile_shape`, `poc_bar_dist`,
  `bars_in_va`, `trend_day_probability`, `open_type`).
- `atr_regime_zscore_60d` ABSENT (calcule en Phase B batch).
- `regime_*` et `bias_*` ABSENTS (non persistes).

**Plan**:
1. **Etendre `live_enricher_writer.py`** pour forward tous les champs DMP
   necessaires au regime + bias (28 distincts cf
   BIAS_DIRECTION_DETECTION_CLARIFICATION D.3). Cout : ~50 LOC + restart.
2. **Calculer `compute_regime(bar)` + `compute_bias(bar)` cote Bot 3 v2**
   apres lecture live_enriched. Pas de cache (pure recalc par barre).
3. **Accepter `vol_regime = NORMAL` constant** temporairement (option 1
   Section D.5). Cout : 0. Risque : skip d'un EXTREME rare (~3% des
   barres). Acceptable Phase 1.
4. **Backlog Phase 2** : porter `atr_regime_zscore_60d` en streaming
   (option 3 Section D.5, cout 120-180 LOC + test parite bit-for-bit TIER 1).

### AXE 2 — Dimension 13 `regime_bias_consensus`

**Etat actuel** : `bot3_context_analyzer.py:analyze_context(bar)` expose 12
dimensions (`poc_mig_*`, `va_dev`, `delta_pct`, `finish_strength`,
`liq_sweep_*`, etc.). Aucune expose le VERDICT consolide `regime.favor` ou
`bias.direction`.

**Cible** : ajouter une 13e dimension nommee `regime_bias_consensus` (pas
"DIM 13" numerique pour eviter confusion d'ordre) :

```python
ctx["regime_favor"]      = "LONG" / "SHORT" / "NEUTRE"
ctx["regime_mode"]       = "TREND" / "RANGE" / "NORMAL"
ctx["regime_vol"]        = "EXTREME" / "HIGH" / "NORMAL" / "LOW"
ctx["regime_actionable"] = bool
ctx["regime_confidence"] = float [0,1]
ctx["bias_score_signed"] = float [-1,+1]
ctx["bias_direction"]    = "BULL" / "BEAR" / "NEUTRE"
ctx["bias_clarity"]      = float [0,2]
```

**Source** :
- Si lecture v4_enriched : `regime_*` lus du parquet (depuis 03/05).
- Si lecture live_enriched (AXE 1) : recalcul cote Bot 3.
- `bias_*` : TOUJOURS recalcul cote Bot 3 (jamais persiste).

### AXE 3 — Utilisation regime_bias_consensus en mode anti Pattern 11

**Regle souveraine** (cf BIAS_DIRECTION_DETECTION_CLARIFICATION C.5) :
les penalites sont **TRACKING-ONLY** Phase 1, pas des gates.

**Risque de cycle de retroaction** (review code-reviewer 17/05) : si les
penalites sur `confidence` influencent `BLOCKED_COMBOS_BOT3` qui re-influencent
le confidence agrege, on cree un composite indicator deguise (anti
`feedback_lightgbm_no_composite_indicators.md`). **Fix structurel** :

```python
# AVANT - composite cache
confidence = 50 + bonus_whales + ... + dim13_adjustment
# (cette valeur est tracked pour BLOCKED_COMBOS calcule plus tard)

# APRES - separation explicite
confidence_raw = 50 + bonus_whales + bonus_sweep + bonus_smt + ...
# raw = base bonus existants Bot 3 v1 SEULS, tracked pour BLOCKED_COMBOS
confidence_adjusted = confidence_raw + dim13_adjustment
# adjusted = signal au dashboard/log uniquement, JAMAIS feed-back dans stats
```

Les stats `BLOCKED_COMBOS_BOT3` se calculent sur `confidence_raw` (signal
pur), pas sur `confidence_adjusted` (signal + DIM 13). Ainsi pas de cycle.

**Table penalites confidence_adjusted (Phase 1)** :

| Cas | Action sur `confidence_adjusted` |
|---|---|
| `regime.favor == side` | `+ 5` bonus (signal aligne) |
| `regime.favor == NEUTRE` | rien |
| `regime.favor == oppose(side)` ET `regime.confidence < 0.30` | rien (regime trop faible) |
| `regime.favor == oppose(side)` ET `regime.confidence >= 0.30` ET `regime.actionable` | `- 15` malus |
| `bias.direction == oppose(side)` ET `bias.clarity > 0.4` | `- 10` malus |

Aucune decision GO/SKIP n'est faite sur ces seuils tant que validation
Phase 1 (200+ trades + walk-forward 12-fold + DSR >= 0.95) n'est pas faite.

**Reserves market-analyst 17/05** : les seuils `0.30`, `0.50`, `0.4` couvrent
~50% des regimes actionnables (0.30 = 3.6 votes nets sur 12, soit la moitie
superieure). Plausibles mais non backtestes. Phase 2 grid search obligatoire.

**Alternative musclee** (Phase 2 si tracking insuffisant) : VETO_REGIME_OPPOSITE
documente Section C.5 du doc clarification. NE PAS coder avant review TIER 1
agents `ml-trainer` + `market-analyst`.

### AXE 4 — Confluences niveau × COLOR/LONG BAR

**Etat actuel** : 19 niveaux dans `bot3_level_definitions.py` (TIER 1/2/3).
COLOR UP/DN + LONG UP/DN BAR existent en JSONL DMP mais non utilises par
Bot 3.

**Backtest realise (sur 14m enriched)** :
- Autonomes (COLOR/LONG BAR seuls) : tous PF < 1.4 -> NOGO.
- Confluences (niveau + pattern) : **3 GO sur NQ**, **0 GO sur ES** :
  - `PVAH + color_dn_2` -> PF mesure (cf backtest result).
  - `IB_HIGH + long_dn_bar` -> PF mesure.
  - `IB_LOW + long_up_bar` -> PF mesure.

**Cible** : ajouter dans `bot3_level_definitions.py` un dict
`CONFLUENCE_LEVELS` :

```python
CONFLUENCE_LEVELS = {
    "PVAH_COLOR_DN_2": {
        "base_level": "PVAH",
        "extra_pattern": "bn_color_dn_2",
        "side": "SHORT",
        "tier": 2,
        "symbols": ["NQ"],
        "min_dist_ticks": 0,
        "max_dist_ticks": 5,
    },
    # ... 7 autres confluences identifiees
}
```

**PREREQUIS Phase 1.0 (avant tout code AXE 4)** :
1. Regenerer `stats_per_level_full_14m_v4.csv` post-fix dist_signed 15/05
   (les v3 datees du 03/05 sont potentiellement inversees sur niveaux
   REJECTION — cf BIAS_DIRECTION_DETECTION_CLARIFICATION C.6).
2. Extraire `setups_confluences_v4.csv` avec niveau, pattern, side, n_trades,
   PF par fold, DSR Lopez, bootstrap CI 95%.
3. **Jackson valide la liste finale** (8 setups ? plus ? moins ?).
4. `market-analyst` GO + `ml-trainer` GO (DSR>=0.95 fold-par-fold + n>=100
   par confluence + concentration<33%).
5. Si verdict DSR<0.95 sur une confluence -> drop avant code.

**Reserves market-analyst 17/05** : 3 GO sur 8 setups testes sur 14 mois only
= proche du seuil de data mining (8 cellules × 19 niveaux × 2 directions =
~300 combos testes, 3 GO = 1% top tail). DSR par confluence individuelle
obligatoire, **PAS de DSR global Bot 3 v2 suffisant**.

### AXE 5 — BLOCKED_COMBOS_BOT3 (Session × Level)

**Etat actuel** : Bot 3 trade tous les niveaux sur toutes les sessions
(Asia, London, US_pre_open, US_open, US_AH).

**Backtest 14m** : 15 combinaisons Session × Level PF < 0.7 sur ES principalement.
Mesure : eviter ces combos = +$107k 14m sur 3 micros.

**Cible** : ajouter dans `bot3_config.py` :

```python
BLOCKED_COMBOS_BOT3 = {
    # Format (symbol, session, level_name) ou (session, level_name) si symbol-agnostique
    ("ES", "US_AH", "IB_HIGH"): {"pf_observed": 0.42, "trades": 87},
    # ... 14 autres combos
}
```

**Check dans `evaluate_decision`** apres VETOS, avant resolution side :
```python
session = ctx.get("session", "UNKNOWN")
combo_key = (symbol, session, level_name)
if combo_key in BLOCKED_COMBOS_BOT3:
    return False, f"BLOCK_COMBO_{symbol}_{session}_{level_name}", {
        "pf_observed": BLOCKED_COMBOS_BOT3[combo_key]["pf_observed"]
    }
```

**RISQUE DATA MINING ELEVE** (market-analyst 17/05) : 28 sessions × 19 niveaux
× ~2 directions = ~1064 combos testes, 15 bloques = 1.4% top tail negatif
— exactement ce que le hasard pur produit sur 1064 tirages. Le $107k gain
est mecanique (retrait des pires combos retrospectifs).

**PREREQUIS Phase 1.5 stricts** :
1. Regenerer `stats_per_level_full_14m_v4.csv` post-fix dist_signed 15/05.
2. Appliquer correction Bonferroni : seuil PF<0.7 devient effectivement
   `PF<0.5 avec n>=87 trades/combo` (compense le test multiple sur 1064
   combos). Le 15 combos bloques devraient tomber a 5-7 apres correction.
3. Walk-forward 12-fold par combo : garder UNIQUEMENT les combos PF<0.7
   stable sur >=8/12 folds.
4. `ml-trainer` GO sur 5 controles `feedback_data_mining_trap.md`
   (walk-forward + DSR + n + concentration + couts).
5. Post-deploy : tracker PF reel par combo bloque (regression to mean
   attendue) — re-evaluation hebdomadaire.

### AXE 6 — SESSION_BOOST_CONFIDENCE

**Backtest 14m** : 9 combinaisons Session × Level PF >= 1.3. Ces combos
meritent un bonus de confidence (pas un gate, juste un signal de fiabilite).

**Cible** :
```python
SESSION_BOOST_CONFIDENCE = {
    ("NQ", "US_open", "IB_LOW"): {"boost": 15, "pf_observed": 1.67},
    # ... 8 autres
}
```

Applique dans `evaluate_decision` etape 6 (calcul confidence) :
```python
boost_key = (symbol, session, level_name)
if boost_key in SESSION_BOOST_CONFIDENCE:
    confidence += SESSION_BOOST_CONFIDENCE[boost_key]["boost"]
```

### AXE 7 — VETO_VOLA_TOO_LOW_ES

**Logique trading** (market-analyst 17/05) : ES en faible vol = sessions
Asia / early London / consolidations. Pas de momentum -> niveaux IB/VWAP/POC
ne tiennent pas, rejections = bruit. Causalite claire.

**Backtest 14m** : ES avec `atr_multiplier <= 0.8` (volatilite tres faible
vs baseline) = PF effondre. Eviter = +$30k 14m.

**Cible** : ajouter dans `bot3_config.py` :
```python
VETO_VOLA_TOO_LOW_ES = 0.8   # ES uniquement, NQ pas concerne
```

**PREREQUIS Phase 1.6 (avant code)** : tester la grille
`[0.7, 0.8, 0.9, 1.0]` fold-par-fold pour eviter un seuil overfit. Si la
relation est monotone (PF croissant avec atr_mult), `0.8` est robuste. Si
non, overfit possible -> choisir le seuil le plus stable.

Source backtest : `DATA/BACKTEST/BOT3/atr_sweep_es_*.csv` a generer si pas
encore present.

Check dans `evaluate_decision` au niveau des VETOS :
```python
if symbol == "ES":
    atr_mult = ctx.get("atr_14m_pct", 0.030) / ATR_BASELINE["ES"]
    if atr_mult <= VETO_VOLA_TOO_LOW_ES:
        return False, "VETO_VOLA_TOO_LOW_ES", {"atr_mult": round(atr_mult, 3)}
```

### AXE 8 — Timeout differentie Session × Symbol

**Etat actuel** : timeout signal `BOT3_TIMEOUT_SECONDS` global.

**Cible** : timeout adapte au volume/volatilite de chaque session :
```python
TIMEOUT_BY_SESSION_SYM = {
    ("ES", "US_open"): 90,
    ("ES", "US_AH"): 300,
    ("NQ", "US_open"): 75,
    # ...
}
```

Phase 2 (apres stabilisation des autres axes).

## Plan d'execution (Phase 1) — hierarchie market-analyst

**Hierarchie revisitee** : market-analyst 17/05 a identifie 3 axes prioritaires
sur 8 (ROI eleve, risque faible) : **AXE 1 + AXE 3 + AXE 7**. Les AXE 4-5-6
sont reportes en bout de Phase 1 car risque data mining eleve sans regenerer
les stats post-fix dist_signed (15/05) ni walk-forward fold-par-fold.

Workflow strict avec **review agent apres CHAQUE module** (directive Jackson) :

### Phase 1.0 — Prerequis (NON CODE)

- **P1.0.1** : Regenerer `stats_per_level_full_14m_v4.csv` post-fix dist_signed
  (input critique pour AXE 4-5-6).
- **P1.0.2** : Extraire `setups_confluences_v4.csv` + `combos_blocked_v4.csv`
  + `combos_boost_v4.csv` + `atr_sweep_es_v4.csv` avec :
  - DSR Lopez fold-par-fold,
  - bootstrap CI 95%,
  - Bonferroni correction sur seuils (AXE 5).
- **P1.0.3** : Jackson valide les listes finales AXE 4 (confluences) et
  AXE 5 (combos).
- **P1.0.4** : Reviews `ml-trainer` GO (5 controles
  `feedback_data_mining_trap.md`) + `market-analyst` GO (causalite trading).

### Phase 1.1 — AXE 1 etape 1 (foundational)

- Etendre `live_enricher_writer.py` pour forward les 14 champs DMP manquants
  + bump `SCHEMA_VERSION` `live_enriched_1.0` -> `1.1`.
- Tests parite live vs DMP brut (subset 1000 barres, identite a 1e-6 pres).
- Reviews : `code-reviewer` + `schema-auditor`.

### Phase 1.2 — AXE 2 (regime_bias_consensus)

- Ajouter dimension `regime_bias_consensus` dans `bot3_context_analyzer.py`.
- Import `compute_bias` + `compute_regime`, calcul cote bot.
- Tests unitaires : ctx contient les 8 nouveaux champs.
- Review : `code-reviewer`.

### Phase 1.3 — AXE 3 (penalites confidence_raw vs adjusted)

- Modifier `bot3_decision_engine.py` :
  - Separation `confidence_raw` (base bonus) vs `confidence_adjusted`
    (raw + DIM 13).
  - Tracking JSONL log de raw + adjusted.
- Tests : verdict identique a v1 sauf `confidence_adjusted` ajustee ; raw
  inchange.
- Review : `code-reviewer` + verification
  `feedback_lightgbm_no_composite_indicators.md`.

### Phase 1.4 — AXE 7 (VETO_VOLA_TOO_LOW_ES)

- Tester grille `[0.7, 0.8, 0.9, 1.0]` fold-par-fold (P1.0.2 atr_sweep).
- Choisir seuil le plus stable.
- Ajouter `VETO_VOLA_TOO_LOW_ES` dans `bot3_config.py` + check
  `evaluate_decision`.
- Tests : ES atr_mult <= seuil -> VETO emis ; NQ inchange.
- Review : `code-reviewer` + `market-analyst` (causalite).

### Phase 1.5 — AXE 1 etape 2 (source live)

- Brancher `databento_paper_trader_v2.py` Bot 3 path sur `live_enriched`
  JSONL.
- Smoke test 1 jour live ES + NQ.
- Tests : aucun NaN imprevu, lag mesure <30s.
- Review : `code-reviewer` + CHANGELOG entry obligatoire.

### Phase 1.6 — AXE 4 (confluences, sous reserve P1.0.4 GO)

- Implementer `CONFLUENCE_LEVELS` dans `bot3_level_definitions.py` (liste
  validee P1.0.3).
- Brancher `bot3_mp_engine.py` pour detection confluences.
- Tests : confluences trigger uniquement sur match exact.
- Reviews : `code-reviewer` + `market-analyst` (logique trading) +
  `backtest-runner` (gain mesure).

### Phase 1.7 — AXE 5 + AXE 6 (BLOCK/BOOST, sous reserve P1.0.4 GO)

- `BLOCKED_COMBOS_BOT3` et `SESSION_BOOST_CONFIDENCE` dans `bot3_config.py`
  avec listes Bonferroni-corrigees.
- Check BLOCK dans `evaluate_decision` apres VETOS.
- Application BOOST dans calcul `confidence_raw`.
- Tests : combos bloques retournent `BLOCK_COMBO_*` reason ; boost
  applique uniquement aux match exact.
- Reviews : `code-reviewer` + `backtest-runner` + `ml-trainer` (DSR par
  combo).

### Phase 1.8 — AXE 8 (timeout, optionnel)

- `TIMEOUT_BY_SESSION_SYM` dans `bot3_config.py`.
- Backlog Phase 2 si gain marginal.

Apres Phase 1 complete -> **Phase 2 Backtest 14m + walk-forward 12-fold**
(critere `feedback_data_mining_trap.md`).

## Criteres GO Phase 2 -> Phase 3 (Shadow)

- PF Bot 3 v2 >= Bot 3 v1 × 1.10 sur 14m hold-out.
- **DSR Lopez >= 0.95 sur fold-par-fold global Bot 3 v2** ET
  **DSR Lopez >= 0.95 par CONFLUENCE individuelle (AXE 4)** ET
  **DSR Lopez >= 0.95 par COMBO bloque individuel (AXE 5)**.
- Concentration <= 33% (pas plus d'un tiers du PnL sur 1 mois ou 1 niveau ou
  1 confluence).
- Pas de degradation > 10% sur NQ vs v1.
- Plafond empirique edge 1m bars = PF 1.29 (JL2 best) -> PF Bot 3 v2 > 1.30
  = suspect overfit, investigation requise.

## Criteres GO Phase 3 -> Live promotion

- Shadow mode paper Sim1 7-14j PF >= 1.30.
- Aucun trade contre-sens fort (cf E.4 audit).
- Trade per day cible : 3-8 (pas plus, pas moins).
- **0 orphelin sur 50 trades Phase 1** (cf `lessons.md` OCO et regle
  `orphan-prevention` si elle existe).
- Stats par combo bloque : tracker PF reel post-deploy, hebdo. Si regression
  to mean ramene PF > 1.0 sur un combo bloque -> debloquer.

## Risques data mining identifies (market-analyst 17/05)

| AXE | Risque | Mitigation Phase 1 |
|---|---|---|
| AXE 3 penalites | Faible (tracking-only par construction) | Separation `confidence_raw` vs `adjusted` |
| AXE 4 confluences | **Moyen** (3 GO sur 8 setups = 1% top tail) | DSR par confluence + n>=100 + Phase 1.0 GO |
| AXE 5 BLOCKED_COMBOS | **Tres eleve** (15/1064 = 1.4% top tail = noise statistique) | Bonferroni correction + walk-forward 12-fold/combo + ml-trainer GO |
| AXE 6 SESSION_BOOST | **Moyen** (9 boostes sur 1064 combos = 0.8%) | Bonferroni + tracker post-deploy |
| AXE 7 VETO_VOLA | Faible (causalite trading claire) | Grid `[0.7-1.0]` fold-par-fold |
| AXE 8 timeout | Negligeable | Backlog Phase 2 |

## Backlog non couvert Phase 1

- Confluences MQ_WALL_HEAVY (AXE 4 element 7-8).
- VETO_REGIME_OPPOSITE_HIGH_CONF (Phase 2 si tracking insuffisant + review
  TIER 1 `ml-trainer` + `market-analyst`).
- Migration `atr_regime_zscore_60d` streaming
  (`CORE/live_enricher_writer.py` option 3 D.5, 120-180 LOC + parite
  bit-for-bit TIER 1).
- Recalibration seuils penalties par grid search (Phase 2).
- Persist `bias_*` dans v4_enriched (extension Phase B). Cout faible mais
  pas critique pour Bot 3 v2 (recalcul cote bot OK).

## Annexe — Fichiers a modifier (LOC revue 17/05)

| Fichier | Modif | LOC estimee |
|---|---|---|
| `CORE/live_enricher_writer.py` | Forward 14 champs DMP + bump SCHEMA_VERSION + parite tests | **+100-150** |
| `CORE/bot3_context_analyzer.py` | Ajouter dimension `regime_bias_consensus` (8 champs) | +30 |
| `CORE/bot3_decision_engine.py` | Separation `confidence_raw`/`adjusted` + penalites + check BLOCK + VETO_ATR_LOW_ES | +50 |
| `CORE/bot3_level_definitions.py` | `CONFLUENCE_LEVELS` dict (8 setups apres validation) | +60 |
| `CORE/bot3_config.py` | `BLOCKED_COMBOS_BOT3`, `SESSION_BOOST_CONFIDENCE`, `VETO_VOLA_TOO_LOW_ES`, `TIMEOUT_BY_SESSION_SYM` | +60 |
| `CORE/bot3_mp_engine.py` | Branch confluences AXE 4 + timeout AXE 8 | +40 |
| `CORE/databento_paper_trader_v2.py` | Source switch live_enriched (Bot 3 path) + fallback v4 | +30 |
| `tools/inspect_bias_decision.py` | Nouveau (E.1) | +80 |
| `tools/audit_bot3_countertrend.py` | Nouveau (E.4) | +120 |
| `tools/regen_stats_post_fix_dist_signed.py` | Nouveau (P1.0.1) | +60 |

Total : **~630-680 LOC** + tests + docs + bump CHANGELOG (anti
sous-estimation review code-reviewer 17/05).
