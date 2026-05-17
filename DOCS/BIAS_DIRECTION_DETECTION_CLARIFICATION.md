# Clarification BIAIS + Direction trade — MIA V2

**Date** : 2026-05-17
**Auteur** : Jackson (mentor) + Claude (orchestrateur)
**Statut** : v1.0 — sections A-B-C-D-E completes, 5 rounds code-reviewer
appliques (A: 6 fixes, B: 4 fixes, C: 3 reserves, D: 5 corrections incl.
decouverte bias_* non persiste, E: 4 fixes finaux).

## Pourquoi ce document

Le bot 3 prenait des trades "a contre-sens" (audit 12/05). Cause racine partielle :
absence de clarte ecrite sur (1) ce qu'est le BIAIS et comment il se calcule,
(2) ce qu'est le REGIME et comment il se distingue du biais, (3) qui decide la
DIRECTION du trade et avec quels champs. Le code existe (`CORE/bias_calculator.py`,
`CORE/regime_engine.py`, `CORE/bot3_decision_engine.py`) mais aucun document de
reference cross-bot ne l'expose.

Ce document est la source unique de verite pour :

- Bot 1 paper (`CORE/mia_paper_trader.py`)
- Bot 2 V6 (`CORE/databento_paper_trader_v2.py` mode V6)
- Bot 3 (`CORE/databento_paper_trader_v2.py` Bot 3 path + `bot3_decision_engine.py`)
- Bot 4 BN V3 dedie (futur Sim4)

Toute modification d'une des 3 briques (`bias_calculator`, `regime_engine`,
decision direction) doit mettre a jour ce document dans la meme PR.

---

## Section A — Calcul du BIAIS

Source : `CORE/bias_calculator.py:compute_bias(bar)` (497 LOC, version 1.0 du
24/04/2026 issue de l'extraction de `DASHBOARD/api/builders.py:build_regime`).

### A.1 — Intention

Le BIAIS repond a une question simple : **dans cette barre, qui paye le marche ?**

Il est calcule **par barre** a partir de 5 blocs ponderes + 1 bloc divergence
optionnel. Le resultat n'est PAS un verdict binaire BULL/BEAR : c'est un couple
`(score_bull, score_bear)` qui permet de mesurer la **conviction** via
`bias_clarity = |score_bull - score_bear|`.

Le biais reste un **input** pour la decision trade — il ne suffit pas a lui seul
a declencher un signal. Il est combine avec le REGIME (section B) et les
NIVEAUX (Bot 3) ou les SETUPS (Bot 2 V6, BN V3).

### A.2 — Les 5 blocs ponderes

| Bloc | Poids | Source DMP | Logique |
|---|---|---|---|
| 1. Position 1D range | 30 % (0.30) | `range_pos`, `new_swing_high/low`, `delta_day` | `pos >= 80` + `new_high` + `delta_day > 0` -> BULL breakout 0.10. `pos >= 80` sans confirmation -> BEAR top 0.30. Symetrique en bas. |
| 2. OrderFlow | 25 % (0.25) | `delta_day_dir`, `delta_pct` | `delta_day_dir > 0` + `delta_pct > 5%` -> BULL strong 0.25. `delta_day_dir > 0` seul (barre neutre) -> BULL weak 0.10. Symetrique vendeur. |
| 3. VWAP position | 20 % (0.20) | `dist_vwap_d` (convention DMP : positif = VWAP au-dessus prix = BEAR) | `dist_vwap_d < -15t` -> BULL (prix au-dessus). `dist_vwap_d > +15t` -> BEAR (prix en-dessous). |
| 4. VWAP slope | 15 % (0.15) | `vwap_slope_10` | `slope > +2.0` -> BULL. `slope < -2.0` -> BEAR. |
| 5. CVD direction | 10 % (0.10) | `cvd_day_dir` | `+1` -> BULL accumulation. `-1` -> BEAR distribution. |

Score brut max par side : `0.30 + 0.25 + 0.20 + 0.15 + 0.10 = 1.00`.

### A.3 — Bloc DIVERGENCE (bonus conditionnel)

Si `delta_divergence = 1` sur la barre, on calcule un `div_quality` ∈ [0, 10]
agrege depuis 6 facteurs :

1. **VWAP stretch** : `|dist_vwap_d|` > 200 = +3.0, > 80 = +2.0, > 30 = +1.0.
2. **Range extreme** : `range_pos >= 90` ou `<= 10` = +2.0. `>= 80` ou `<= 20` = +1.0.
3. **Session extension** : `sess_range_atr > 1.3` = +1.5. `> 1.0` = +0.5.
4. **VIX eleve** : `vix_level > 25` = +1.0. `> 20` = +0.5.
5. **Triple VWAP align** :
   - `dist_vwap_d < -100` (prix tres au-dessus VWAP) + `vwap_d/w/m_side = +1` = +1.5 -> signal mean reversion **BEARISH** (fade le push haut).
   - `dist_vwap_d > +100` (prix tres en-dessous VWAP) + `vwap_d/w/m_side = -1` = +1.5 -> signal mean reversion **BULLISH** (fade le push bas).
6. **RVOL faible** : `rvol < 0.7` = +1.0 (push sans conviction).

Grade :
- `div_quality >= 6` -> EXTREME
- `>= 4` -> FORTE
- `>= 3` -> MODEREE
- `delta_div = 1` et `div_quality < 3` -> FAIBLE
- `delta_div = 0` -> NONE (default dataclass)

**Garde-fou anti-fade-trend** : le bonus n'est applique **que si non trending**.
`is_trending = (vwap_slope_10 > +5 AND delta_day_dir > 0)` ou symetrique
bearish. Si trending, la divergence est loggee mais ignoree (pas de fade
breakout).

**Bonus applique** (seulement si `div_quality >= 5` ET non trending) :
- Si `pos >= 70 AND dist_vwap_d < -50` (overextended haut) -> `score_bear += min(div_quality/20, 0.35)`.
- Si `pos <= 30 AND dist_vwap_d > +50` (overextended bas) -> `score_bull += min(div_quality/20, 0.35)`.

**Cas intermediaire** : si `3 <= div_quality < 5` (grade MODEREE) -> aucun bonus
applique, mais une `reason_neutral` est emise (`"DIV {grade}: contexte
insuffisant ({quality}/10)"`) pour audit. La divergence existe mais le contexte
(stretch, range, vol, vix) est juge trop faible pour fader.

### A.4 — Finalisation

```
score_signed  = clip(score_bull - score_bear, -1.0, +1.0)
bias_clarity  = |score_bull - score_bear|
direction     = "BULL"   si score_signed >  +0.25
                "BEAR"   si score_signed <  -0.25
                "NEUTRE" sinon
```

Les seuils `+/- 0.25` sont **bornes empiriques** issues du dashboard V1 et n'ont
PAS ete recalibres par grid search. Ils marquent une zone "indecise" entre les
deux scores. La plupart du temps `bias_clarity < 0.20` signifie que les 5 blocs
sont en conflit (rejet trade conseille).

**Confidence dashboard** : `calc_confidence(score_signed, factors)` calcule
`consensus * 0.6 + amplitude * 0.4`. `consensus = max(bulls, bears) / active`,
`amplitude = min(|score| * 2, 1)`. Malus si `active < 3` facteurs
(`confidence *= active / 3`). Exposee dans `to_dashboard_dict()` sous la cle
`bias_confidence`. Consommee par le dashboard uniquement ; le bot ne s'appuie
PAS sur cette valeur (il utilise `bias_clarity` qui ne penalise pas).

### A.5 — Sortie utilisable par les bots

```python
from CORE.bias_calculator import compute_bias

bias = compute_bias(bar)   # bar = dict ligne JSONL ou parquet enriched
# bias.score_bull, bias.score_bear  -> floats separes
# bias.score_signed                 -> [-1, +1]
# bias.bias_clarity                 -> [0, 2] (rarement > 0.6)
# bias.direction                    -> "BULL" / "BEAR" / "NEUTRE"
# bias.div_active, bias.div_grade   -> divergence detail
# bias.reasons_bull / reasons_bear  -> liste lisible (audit trade)
```

### A.6 — Limites connues

- **Reproduction fidele V1 (pas optimal)** : aucune feature post-V1 (Game Changers,
  trapped traders, session_features, MQ niveaux) n'est integree.
- **Seuils non calibres par grid search** : `0.25`, `15t`, `2.0` (slope), `0.05`
  (delta_pct) sont des heuristiques V1. A challenger contre Lopez DSR si on veut
  ameliorer.
- **NaN-tolerant mais silent** : `_get(bar, key, default=0.0)` masque les features
  absentes. Sur un parquet stale (V4 lag 22 min) ou un JSONL DMP partiel, le
  biais reste calculable mais peut etre faussement neutre. Verifier
  `bar.get("ts_event_ns")` recent avant de trust.
- **Score borne asymetrique** : `score_signed` est clippe `[-1, +1]` mais
  `score_bull`/`score_bear` individuels peuvent atteindre `1.0 (brut) + 0.35 (bonus
  div) = 1.35`. Idem `bias_clarity` borne theorique `[0, 2.0]` (non clippee).
  Empiriquement `bias_clarity > 0.6` est rare et signal de tres forte conviction.

### A.7 — Reference rapide champs sources

Le calcul lit **16 champs** au total :

```
range_pos, new_swing_high, new_swing_low,
delta_day, delta_pct, delta_day_dir,
dist_vwap_d, vwap_slope_10, vwap_d_side, vwap_w_side, vwap_m_side,
cvd_day_dir,
delta_divergence, sess_range_atr, vix_level, rvol
```

Tous presents dans DMP JSONL 3.7.2 (262 cols). Dans live_enriched (435 cols)
et v4_enriched (87 cols), TOUS les 16 champs sont PRESENTS au schema, mais
`sess_range_atr` est NaN ~90% sur ES (cf D.6 pour mesure empirique). Le code
gere les NaN via `_get(bar, key, default=0.0)` -> les blocs concernes
contribuent simplement 0 au score.

---

## Section B — Calcul du REGIME

Source : `CORE/regime_engine.py:compute_regime(bar)` (409 LOC, version
`v2_optim_20260503`, calibree par grid search 14j NQ le 03/05/2026).

### B.1 — Intention

Le REGIME repond a une question structurelle : **dans quel etat est le marche
maintenant ?** Trois axes :

1. `mode` : `TREND` / `RANGE` / `NORMAL` (structure dominante).
2. `favor` : `LONG` / `SHORT` / `NEUTRE` (direction privilegiee si actionable).
3. `vol_regime` : `EXTREME` / `HIGH` / `NORMAL` / `LOW` (volatilite).

Le regime est **plus stable que le biais** (s'appuie sur 10 votes structurels
Market Profile + VWAP + Open Type). Le biais peut flotter barre par barre, le
regime tient generalement sur des plages de 30 min a quelques heures.

Le regime est calcule **UNE FOIS par barre** dans `build_dataset_v4_dmp_databento`
(depuis le 03/05/2026) puis persiste comme **7 features V4** : `regime_mode`,
`regime_favor`, `regime_confidence`, `regime_trend_votes`, `regime_range_votes`,
`regime_vol`, `regime_actionable`. Les 3 bots consomment ces features sans
recalculer (anti Pattern 11 V1 = 11 layers cascades).

**Limite empirique 17/05/2026** : `atr_regime_zscore_60d` (utilise pour
`vol_regime`) est ABSENT du parquet v4 mai 2026 (87 cols verifiees). Soit le
pipeline Phase B n'a pas tourne sur ce mois, soit le module
`phase_b_option_c_plus` ne dumpe pas la colonne. En attendant correction,
`vol_regime` retombe en fallback `NORMAL` constant sur les barres concernees.
Voir Section D.4 pour le detail des features persistees.

### B.2 — Les 10 votes ponderes (mode TREND vs RANGE)

| # | Vote | Champ DMP | Logique TREND | Logique RANGE |
|---|---|---|---|---|
| 1 | IB Breakout | `ib_broken_up`, `ib_broken_down`, `ib_formed_bool` (fallback `ib_range_ticks > 0` si bool absent) | IB cassee = +2 | IB intacte = +1 |
| 2 | Day Type | `day_type` (Steidlmayer 0-4) | 4 Trend = +2 ; 2 NormVar = +1 | 1 Normal = +1 ; 3 Neutral = +1 |
| 3 | Single Prints | `single_print_count` | > 100 = +1 (conviction) | < 30 = +1 (rotation) |
| 4 | VWAP Slope | `vwap_slope_10` | `\|slope\| > 3.5` = +1 | `\|slope\| < 0.5` = +1 (plat) |
| 5 | Sess/ATR | `sess_range_atr` | > 1.0 = +1 (expansion) | < 0.4 = +1 (compression) |
| 6 | Open Type | `open_type` (1-6) | 1-2 OD = +1 ; 3-4 OTD = +1 | 5-6 ORR = +1 |
| 7 | Profile Shape | `profile_shape` (0-3) | 1 P / 2 b = +1 | 0 D / 3 DoubleDist = +1 |
| 8 | POC distance | `poc_bar_dist` | > 15 bars = +1 | < 3 bars = +1 |
| 9 | Bars in VA | `bars_in_va` (%) | < 10% = +1 (hors VA) | > 30% = +1 (confine) |
| 10 | Trend Day Prob | `trend_day_probability` | > 0.30 = +1 | < 0.10 = +1 |

Score max theorique : trend_votes ∈ [0, 12], range_votes ∈ [0, 12].

**Seuils calibres grid search 03/05** (anti V1 trop strict) :
- `mode_strong = 3` (avant : 5) -> plus permissif.
- `vol_extreme = 5.5` (avant : 2.0).
- `conf_actionable = 0.10` (avant : 0.20).
- `vwap_dir = 3.5` (avant : 5.0).
- `sp_strong = 100`, `sp_weak = 30` (avant : 10 / 3).
- `poc_distant = 15`, `poc_close = 3` (avant : 30 / 5).
- `va_confine = 30`, `va_hors = 10` (avant : 60 / 30).
- `tdp_strong = 0.30`, `tdp_weak = 0.10` (avant : 0.65 / 0.30).

Resultat : actionable rate `3% -> 20.2%` (cible 15-25%). Cross-validation PnL
Bot V1 sur 4/5 jours alignes (22/04 BULL OK, 28/04 SHORT-dom OK, 23/04 choppy
OK, 30/04 BULL predit mais reversal).

### B.3 — Verdict mode

```python
if trend_votes >= 3 and trend_votes >= range_votes + 1:
    mode = "TREND"
elif range_votes >= 3 and range_votes >= trend_votes + 1:
    mode = "RANGE"
else:
    mode = "NORMAL"
```

`NORMAL` = zone indecise (votes faibles ou conflit). C'est la sortie par
defaut, pas une "qualite" du marche.

### B.4 — Bias proxy (utilise pour `favor` en mode TREND/NORMAL)

`_compute_bias_proxy(bar)` est une version **simplifiee** de `compute_bias`
(section A) — 60% des inputs, sans cycle d'import. Composantes :

| Vote | Champ | Score |
|---|---|---|
| VWAP slope | `vwap_slope_10` | > 1.0 = +0.25 ; < -1.0 = -0.25 |
| OrderFlow direction | `delta_day_dir` OR `cvd_day_dir` | > 0 = +0.25 ; < 0 = -0.25 |
| Range position | `range_pos` | > 70 = -0.20 (top bearish) ; < 30 = +0.20 (bottom bullish) |
| VWAP side | `vwap_d_side` | > 0 = +0.15 ; < 0 = -0.15 |
| Delta divergence | `delta_divergence` | != 0 -> +/- 0.15 |

Sortie : `bias_score [-1, +1]`, `bias_label "BULLISH/BEARISH/NEUTRE"` (seuil
+/- 0.30), `bear_factors_count`, `bull_factors_count`.

**Note importante** : ce proxy est calcule **a l'interieur** du regime_engine et
n'est PAS le meme que `compute_bias()` (section A). Le proxy est plus simple
pour eviter cycle d'import et garantir auto-suffisance du regime. Quand un bot
veut le biais detaille, il appelle `compute_bias()` separement.

### B.5 — Direction (`favor`)

```python
if mode == "RANGE":
    if range_pos >= 70:   favor = "SHORT"   # top du range = fader haut
    elif range_pos <= 30: favor = "LONG"    # bas du range = fader bas
    else:                 favor = "NEUTRE"  # milieu range = pas d'edge
elif bias_label == "BULLISH": favor = "LONG"
elif bias_label == "BEARISH": favor = "SHORT"
else:                         favor = "NEUTRE"
```

**Override coherence** (anti faux signal) :
- Si `favor = LONG` ET `bear_factors >= 3` -> `favor = NEUTRE` (structure
  contraire).
- Symetrique : `favor = SHORT` ET `bull_factors >= 3` -> `NEUTRE`.

### B.6 — `vol_regime` (volatilite)

**Fix 11/05/2026** : avant cette date, basee sur `sess_range_atr` qui est NaN
97.5% sur ES et absent sur MGC -> fallback 0.0 -> `vol_regime = LOW` quasi
constant. Feature inutilisable.

Apres fix : utilise `atr_regime_zscore_60d` (z-score normalise rolling 60 jours,
cross-instrument coherent).

```python
if atr_z != atr_z:        vol_regime = "NORMAL"   # NaN -> neutralite
elif atr_z >= 2.5:        vol_regime = "EXTREME"
elif atr_z >= 1.5:        vol_regime = "HIGH"
elif atr_z >= -0.5:       vol_regime = "NORMAL"
else:                     vol_regime = "LOW"
```

Distribution attendue : LOW 25%, NORMAL 60%, HIGH 12%, EXTREME 3%.

### B.7 — `confidence` et `is_actionable`

```python
net = abs(trend_votes - range_votes)
confidence = min(1.0, net / 12.0)

is_actionable = (
    mode != "NORMAL"
    and favor != "NEUTRE"
    and vol_regime != "EXTREME"
    and confidence >= 0.10
)
```

`is_actionable = True` -> le bot peut trader dans le sens `favor` (sous reserve
d'autres gates : niveau touche, orderflow recent, R:R).

### B.8 — Kill switch

`REGIME_SKIP_ENABLED` lit `os.environ["MIA_REGIME_SKIP_ENABLED"]` (default `"1"`).
Si `"0"`, le regime engine peut etre court-circuite par les bots qui le
verifient (Bot 2 V6 / Bot 3) -> rollback rapide sans redeploy.

Commande VPS pour rollback :
```
$env:MIA_REGIME_SKIP_ENABLED = "0"
nssm restart MIA-DataBento-Paper-V2
```

### B.9 — Champs sources

**19 champs distincts** lus au total :

```
# Mode votes (13 champs)
ib_broken_up, ib_broken_down, ib_formed_bool, ib_range_ticks (fallback),
day_type, single_print_count, vwap_slope_10, sess_range_atr,
open_type, profile_shape, poc_bar_dist, bars_in_va, trend_day_probability

# Bias proxy (5 champs)
delta_day_dir, cvd_day_dir, range_pos, vwap_d_side, delta_divergence

# Vol regime (1 champ)
atr_regime_zscore_60d
```

**Origine de chaque champ** :
- Les 18 premiers sont presents dans DMP JSONL 3.7.2 **ET** dans live_enriched
  JSONL (430 cols) **ET** dans v4_enriched parquet.
- `atr_regime_zscore_60d` est calcule UNIQUEMENT par
  `CORE/phase_b_option_c_plus.py:add_atr_regime_zscore_60d` (rolling 60 jours
  RTH), appele depuis le pipeline batch Phase B
  (`build_dataset_v4_phase_b.py`). **Cette feature n'existe PAS dans
  live_enriched JSONL** (verifie empiriquement 17/05/2026 sur
  `DATA/live_enriched/ES/20260330_ES.jsonl`).
- Sur les premiers 60j de rolling, retourne NaN -> `compute_regime` fallback
  explicite `vol_regime = "NORMAL"`.

### B.10 — Sortie utilisable par les bots

```python
from CORE.regime_engine import compute_regime

reg = compute_regime(bar)
# reg.mode        -> "TREND" / "RANGE" / "NORMAL"
# reg.favor       -> "LONG" / "SHORT" / "NEUTRE"
# reg.confidence  -> [0.0, 1.0]
# reg.vol_regime  -> "EXTREME" / "HIGH" / "NORMAL" / "LOW"
# reg.bias_score  -> [-1, +1] (proxy, pas compute_bias)
# reg.is_actionable -> bool (mode != NORMAL AND favor != NEUTRE AND vol != EXTREME AND conf >= 0.10)
# reg.bear_factors / bull_factors -> int (audit override)
# reg.details     -> list[str] (audit trade)
```

Ou via le pipeline V4 (parquet enriched) :
```python
bar["regime_mode"], bar["regime_favor"], bar["regime_confidence"],
bar["regime_vol"], bar["regime_actionable"]  # int 0/1
```

### B.11 — Limites connues

- **`bias_score` du regime != `score_signed` du bias_calculator** : le proxy est
  une version simplifiee. Si un bot veut le biais detaille, il doit appeler
  `compute_bias()` separement (Bot 3 le fait dans `context_analyzer`).
- **`favor` en mode RANGE** est purement geometrique (`range_pos`) — ne tient
  pas compte du biais. Volontaire : en RANGE on fade les extremes peu importe le
  biais.
- **`vol_regime` depend de `atr_regime_zscore_60d`** qui est calcule par le
  pipeline batch Phase B (`phase_b_option_c_plus.py`) et persiste dans le
  parquet v4_enriched. **Cette feature est ABSENTE de live_enriched JSONL et de
  DMP JSONL brut** (verifie empiriquement). Implications :
  - Bot 3 v2 qui lirait live_enriched JSONL en direct (sans passer par
    v4_enriched parquet) verrait `vol_regime = NORMAL` constant -> gate
    `vol != EXTREME` jamais bloquant -> perte d'edge.
  - Solution recommandee : enrichir le path live avec ce champ (rolling cache
    cote bot) OU rester sur v4_enriched parquet pour la decision regime.
- **Override coherence asymetrique vs bias** : `_compute_bias_proxy` peut donner
  `BULLISH` mais `bear_factors >= 3` -> override `NEUTRE`. Coherent mais peut
  surprendre. Audit via `reg.details`.

---

## Section C — Decision direction du trade

Qui decide finalement la `side` (LONG/SHORT) executee ? Reponse : **pas le
biais, pas le regime — la combinaison niveau + dist_signed + contexte** dans
`bot3_decision_engine.evaluate_decision`.

C'est la source du probleme "Bot 3 contre-sens" : le decision engine **ignore
totalement `bias` et `regime.favor`** au moment de choisir le side. Il regarde
le `level["side"]` (directionnel fixe) ou la position relative prix/niveau
(REJECTION) ou un funnel 7-scenarios (NEUTRAL).

### C.1 — Arbre de decision Bot 3 (verite operationnelle)

Source : `CORE/bot3_decision_engine.py:evaluate_decision()` lignes 79-342.

```
1. VETOS ABSOLUS (return SKIP si l'un actif)
   - VETO_ROLL_DAY
   - VETO_NEWS_IMMINENT (715/730/830/845/900/930 ET dans -5 min)
   - VETO_NEWS_JUST_HIT (< 3 min apres news)
   - VETO_VOLUME_MORT (rvol < VETO_RVOL_MIN)
   - VETO_MQ_STALE (niveaux MQ_* perimes > 12h)

2. RESOLUTION SIDE selon level["side"]
   - level["side"] == "LONG"      -> side = "LONG"  (fixe)
   - level["side"] == "SHORT"     -> side = "SHORT" (fixe)
   - level["side"] == "REJECTION" -> calcul positionnel :
       dist_signed = (level - close)
         dist_signed > 0 (level AU-DESSUS prix = resistance)  -> side = "SHORT"
         dist_signed < 0 (level EN-DESSOUS prix = support)    -> side = "LONG"
         dist_signed == 0                                     -> SKIP_DIST_ZERO
   - level["side"] == "NEUTRAL"   -> side resolu par funnel 7 scenarios

3. REQUIRED CONTEXT (Tier 3 only)
   Si level_def["required_context"] : verifier chaque cle == ctx[cle]. Sinon
   TIER3_MISS_<key>.

4. FILTRE ANTI-TREND (skip si NEUTRAL — deja couvert par funnel)
   - side == "SHORT" ET poc_mig_dir == +1 ET poc_speed > 0.05  -> SKIP_BULL_STRONG
   - side == "SHORT" ET va_dev > 2.0                           -> SKIP_VA_EXPANDING
   - side == "LONG"  ET poc_mig_dir == -1 ET poc_speed < -0.05 -> SKIP_BEAR_STRONG

5. FILTRE ORDERFLOW (crush detection)
   Seuils : delta_strong = 50.0 * max(rvol, 0.5) [floor rvol 0.5], finish_strong = 25.0
   - side == "LONG" : delta tres negatif + finish negatif = vendeurs ecrasent
     -> PENDING_BREAKOUT_REGISTERED (mp_engine gere acceptance + retest)
     -> ou SKIP_SELLERS_CRUSHING_* selon flags
   - side == "SHORT" : symetrique acheteurs

6. CALCUL CONFIDENCE (TRACKING-ONLY)
   confidence = 50 + bonus (whales, sweep, failed_auction, smt, trapped, cross)
   Clamp final `max(0, min(100, confidence))` (FIX M-1 review code-reviewer 03/05).
   NON utilise comme gate Phase 1 (review market-analyst 03/05).

7. SL ADAPTATIF
   atr_ratio = atr_14m_pct / ATR_BASELINE[symbol], clamp [low, high]
   sl_ticks = base_sl * atr_ratio

8. RETURN (True, "GO", {side, action, confidence, sl_ticks, atr_multiplier})
```

### C.2 — Le BIAS et le REGIME ne sont PAS consommes ici

Verification empirique : grep `evaluate_decision` ne montre AUCUNE reference a :

- `bias_score`, `bias_clarity`, `compute_bias` -> bias_calculator IGNORE.
- `regime_favor`, `regime_mode`, `compute_regime` -> regime_engine IGNORE.

C'est volontaire (anti-Pattern 11) — eviter cascade de gates. Mais c'est aussi
la cause des trades "a contre-sens" decrits par Jackson : un niveau IB_LOW
(`side=LONG` fixe) peut declencher LONG meme si `regime.favor = SHORT` et
`bias = BEAR` (jour vendeur fort).

### C.3 — Ou s'arrete la responsabilite "bias/regime" ?

Le bias/regime servent (actuellement) UNIQUEMENT a :

1. **Dashboard** (`build_regime_context`) - affichage humain.
2. **Bot 2 V6** - STEP 0 gate (`regime.favor` filtre LONG/SHORT par jour).
3. **Bot 1 paper** - STEP 0 gate similaire.
4. **bot3_context_analyzer** (12 dimensions actuelles) - ce module calcule des
   fragments de regime/bias mais **n'expose pas le verdict consolide au
   decision engine** : on retrouve `poc_mig_dir`, `va_dev`, `delta_pct`... qui
   sont des morceaux, pas le verdict final.

**Bot 3 ne connait donc PAS le verdict `regime.favor` au moment de decider.**

### C.4 — Plan Bot 3 v2 : DIM 13 regime/bias

Ajouter dans `bot3_context_analyzer.py` une 13e dimension qui expose le verdict
consolide :

```python
ctx["regime_favor"]      = "LONG" / "SHORT" / "NEUTRE"
ctx["regime_mode"]       = "TREND" / "RANGE" / "NORMAL"
ctx["regime_vol"]        = "EXTREME" / "HIGH" / "NORMAL" / "LOW"
ctx["regime_actionable"] = bool
ctx["regime_confidence"] = [0, 1]
ctx["bias_score_signed"] = [-1, +1]
ctx["bias_direction"]    = "BULL" / "BEAR" / "NEUTRE"
ctx["bias_clarity"]      = [0, 2]
```

Ces champs DOIVENT etre obtenus comme suit (cf Section D.4 pour realite
empirique) :
- `regime_*` : lus depuis v4_enriched (PRESENT depuis 03/05) OU recalcules
  cote bot via `compute_regime(bar)` si lecture live_enriched.
- `bias_*` : **calcul cote bot OBLIGATOIRE** via `compute_bias(bar)` —
  les colonnes `bias`, `bias_score` ne sont PAS persistees dans v4_enriched
  actuellement (jamais appele dans `build_dataset_v4_*`).

Implication : `bot3_context_analyzer.py` doit importer `compute_bias` ET
soit `compute_regime` (si live), soit lire les champs `regime_*` du parquet
(si v4).

**Important** : la presence du verdict dans `ctx` ne signifie PAS qu'on bloque
le trade si `regime.favor != side`. Cf C.5.

### C.5 — Comment utiliser DIM 13 sans tomber en Pattern 11

Pattern 11 V1 = 11 gates cascades = 65% faux rejets. Interdit. Mais le bot 3
contre-sens est aussi un probleme.

**Compromis recommande** (anti Pattern 11) :

| Cas | Action |
|---|---|
| `regime.favor == side` | rien (pas de bonus, pas de penalite) |
| `regime.favor == NEUTRE` | rien (regime indecis = pas d'info) |
| `regime.favor == oppose(side)` ET `regime.confidence < 0.30` | rien (regime faible) |
| `regime.favor == oppose(side)` ET `regime.confidence >= 0.30` ET `regime.actionable` | penalite `confidence -= 15` (TRACKING uniquement, pas gate) |
| `bias.direction == oppose(side)` ET `bias.clarity > 0.4` | penalite `confidence -= 10` (TRACKING) |

Ces penalites n'arretent PAS le trade — elles affectent le score de
confidence qui sert au tracking et au filtre `BLOCKED_COMBOS_BOT3` (BLOCK ne
s'applique qu'aux combos PF<0.7 mesures empiriquement).

**Seuils provisoires (0.30, 0.50, 0.4) NON backtestes** : les seuils proposes
sont des heuristiques. Ils tombent sous le coup de `feedback_data_mining_trap.md`
(28/04) - composite hardcode sans walk-forward DSR = risque. Avant activation
des penalites Phase 1 :
- Tracking obligatoire 200+ trades reels.
- Recalibration des seuils par walk-forward 12-fold + DSR Lopez sur l'historique
  v4_enriched 8 mois (quand le batch finit).
- Si DSR < 0.95 sur fold-par-fold, abandonner la regle ou ajuster.

**Alternative MUSCLEE** (si la version compromis ne resout pas le contre-sens
apres shadow mode 7-14j) : ajouter UN seul gate :

```python
if (regime_favor and regime_favor != "NEUTRE"
    and regime_favor != side
    and regime_confidence >= 0.50):
    return False, "VETO_REGIME_OPPOSITE_HIGH_CONF", {...}
```

A activer SEULEMENT si tracking Phase 1 montre que la majorite des trades
perdants ont `regime.favor == oppose(side)` ET `regime.confidence >= 0.50`.

**[REVIEW AGENT REQUIS avant code]** : cette alternative est un nouveau gate
critique (critere 1 Trading/Risk + critere 8 Backtest de
`.claude/rules/critical-tasks-review.md`). Avant toute implementation :
1. Backtest empirique standalone (50-100 LOC) sur 14m enriched.
2. Verdict obligatoire `ml-trainer` (PSR/DSR Lopez, fold stability) + verdict
   `market-analyst` (coherence trading, pas Pattern 11).
3. Si verdict GO -> implementation + tests + re-review code-reviewer avant
   commit.

### C.6 — Inversion convention `dist_signed` (FIX 15/05/2026)

**Important historique** : avant le 15/05/2026, la convention `dist_signed`
etait `(close - level)` -> `dist_signed > 0` = prix au-dessus = level support.
Cette convention a ete inversee pour s'aligner sur DMP C++ qui utilise
`(level - close)` -> `dist_signed > 0` = level au-dessus = resistance.

Tout backtest pre-15/05 a pu inverser involontairement `side` sur les niveaux
REJECTION.

**TODO non resolu au 17/05/2026** : `DATA/BACKTEST/BOT3/stats_per_level_full_14m_v3.csv`
date du **03/05/2026 04:35** soit 12 jours AVANT le fix dist_signed. Les
verdicts par niveau (PF, WR, DSR) qui ont guide la roadmap Bot 3 v2 sont basees
sur ces stats potentiellement inversees. **Action requise avant deploy
Bot 3 v2** : regenerer `stats_per_level_full_14m_v3.csv` sur trades post-fix
ou re-run le backtest 14m complet avec la convention corrigee.

**Note docstring obsolete** : `bot3_decision_engine.py:93-94` docstring dit
"Negatif = prix au-dessus, positif = prix en-dessous" — convention INVERSE de
l'implementation l.142-147 et de la verite documentee ici. Le code est correct,
le docstring est obsolete pre-fix. A nettoyer dans la PR Bot 3 v2.

### C.7 — Direction NEUTRAL : funnel 7 scenarios

Pour les niveaux `side="NEUTRAL"` (ex: `CUR_VPOC`, `MQ_HVL`), la decision side
est prise par `_resolve_neutral_side_with_funnel(ctx)` qui evalue 7 scenarios
de convergence (structure + orderflow). En cas d'echec, un `funnel` est
emis pour audit (Jackson 03/05 : "savoir exactement quelle feature bloque a
chaque etape"). Detail des scenarios : voir
`bot3_decision_engine.py:_resolve_neutral_side`.

### C.8 — Resume : qui decide quoi

| Decision | Source | Module |
|---|---|---|
| Liste des niveaux a tracker | Static `BOT3_LEVELS` | `bot3_level_definitions.py` |
| Touch niveau | Distance prix/niveau | `bot3_mp_engine.py` |
| Vetos absolus | `ctx` (news, rvol, roll, mq stale) | `bot3_decision_engine.py:101-128` |
| Side du trade | level["side"] OR dist_signed OR funnel | `bot3_decision_engine.py:130-166` |
| Anti-trend | poc_mig_dir, va_dev | l.185-203 |
| Anti-crush | delta_bar, finish_strength | l.205-272 |
| Confidence | bonus whales/sweep/smt | l.274-320 (tracking) |
| SL | atr_14m_pct | l.322-333 |
| BIAS / REGIME | non consommes (a corriger Bot 3 v2 DIM 13) | a venir |

---

## Section D — Mapping features -> barres

Ou trouver chaque feature, et sous quel nom, selon la source de donnees. Cette
section sert de cartographie pour ne pas se tromper de champ entre live JSONL,
v4 parquet, dashboard et bot.

### D.1 — Les trois sources

| Source | Format | Nb cols | Lag | Use-case |
|---|---|---|---|---|
| DMP JSONL brut | JSONL line-per-bar | 262 (schema 3.7.2) | quasi-temps reel (~5-10s) | C++ DMP -> live_enricher / live |
| live_enriched JSONL | JSONL line-per-bar | **435** (mesure ES 31/03/2026) | quasi-temps reel | live trading bot 2 V6 / bot 3 v2 cible |
| v4_enriched parquet | parquet Hive partitionne | **87** (mesure ES mai 2026, evolutif) | 10-22 min (batch retraitement) | backtest, dashboard hist, bot 3 v1 |

`live_enriched` = `DMP` + `mq_levels` Hive merge + features enriched online
(Battle Naval, session, edge zones, etc.). `v4_enriched` = idem +
post-processing Phase B (z-scores rolling, regime).

**Important — dette de persistance** : malgre la mention "Phase B persiste
regime + bias" dans plusieurs sections amont, la realite empirique (verifiee
17/05/2026) :
- `regime_mode/favor/confidence/trend_votes/range_votes/vol/actionable` :
  **persistes** dans v4_enriched depuis le 03/05.
- `bias`, `bias_score`, `bias_confidence`, `div_*` : **NON persistes** dans
  v4_enriched (grep `compute_bias` dans `build_dataset_v4_*` = 0 match).
- `atr_regime_zscore_60d` : **PRESENT** dans le module
  `phase_b_option_c_plus.py` mais **ABSENT** des parquets v4 ES mai 2026
  (87 cols verifiees). Soit Phase B n'a pas tourne sur ces parquets, soit
  la colonne n'est pas dumpee.

Implication : la Section B.1 et la Section C.4 qui affirmaient "regime + bias
lus depuis v4_enriched" sont partiellement fausses pour le bias. Voir D.4
pour le tableau de disponibilite empirique.

### D.2 — Convention nommage features regime/bias persistees

Quand le pipeline Phase B persiste les sorties de `compute_regime` et
`compute_bias`, il utilise les noms suivants dans le parquet :

```
# Sortie compute_regime (regime_engine.compute_regime_dict)
regime_mode          str  "TREND"/"RANGE"/"NORMAL"
regime_favor         str  "LONG"/"SHORT"/"NEUTRE"
regime_confidence    float [0,1]
regime_trend_votes   int  [0,12]
regime_range_votes   int  [0,12]
regime_vol           str  "EXTREME"/"HIGH"/"NORMAL"/"LOW"
regime_actionable    int  0 ou 1

# Sortie compute_bias (extraction depuis BiasResult.to_dashboard_dict
#  ou colonnes derivees ; nom canonique dans v4 parquet)
bias                 str  "BULLISH"/"BEARISH"/"NEUTRAL"
bias_score           float [-1,+1]   (= BiasResult.score_signed)
bias_confidence      float [0,1]
div_active           int  0/1
div_grade            str
div_quality          float
```

Si une colonne avec ce nom est **absente** du parquet -> appel a
`compute_bias`/`compute_regime` cote bot necessaire.

**Etat au 17/05/2026** (cf D.4) : les colonnes `regime_*` sont persistees
depuis 03/05. Les colonnes `bias_*` ci-dessus sont une **convention si Phase B
est etendu** — elles ne sont actuellement PAS persistees dans v4_enriched. Tout
bot qui veut le verdict bias doit appeler `compute_bias(bar)` lui-meme.

### D.3 — Champs DMP utilises (16 + 19 = 28 distincts)

**16 champs bias** (cf A.7) + **19 champs regime** (cf B.9), avec chevauchement
exact de **7** champs :

```
# Communs (7)
range_pos, vwap_slope_10, vwap_d_side, delta_day_dir, cvd_day_dir,
delta_divergence, sess_range_atr

# Bias-only (9)
new_swing_high, new_swing_low, delta_day, delta_pct,
dist_vwap_d, vwap_w_side, vwap_m_side, vix_level, rvol

# Regime-only (12)
ib_broken_up, ib_broken_down, ib_formed_bool, ib_range_ticks,
day_type, single_print_count, open_type, profile_shape,
poc_bar_dist, bars_in_va, trend_day_probability,
atr_regime_zscore_60d
```

Total distincts : `16 + 19 - 7 = 28`.

### D.4 — Disponibilite par source (mesure empirique 17/05/2026)

Verifie sur :
- `DATA/live_enriched/ES/20260331_ES.jsonl` (435 cols)
- `DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=05/data.parquet` (87 cols)

| Champ | DMP JSONL brut | live_enriched JSONL | v4_enriched parquet |
|---|:---:|:---:|:---:|
| 13 champs bias/regime de base (range_pos, vwap_slope_10, dist_vwap_d, vwap_d/w/m_side, delta_day/pct/dir, cvd_day_dir, sess_range_atr, vix_level, rvol) | OK | OK (partiel — voir note) | OK (partiel) |
| `new_swing_high`, `new_swing_low` | OK | **ABSENT** | **ABSENT** |
| `delta_divergence` | OK | **ABSENT** | **ABSENT** |
| `ib_broken_up/down`, `ib_formed_bool`, `ib_range_ticks` | OK | **ABSENT** | OK |
| `day_type`, `open_type`, `profile_shape` | OK | **ABSENT** | OK |
| `single_print_count`, `poc_bar_dist`, `bars_in_va`, `trend_day_probability` | OK | **ABSENT** | OK |
| `atr_regime_zscore_60d` | **ABSENT** | **ABSENT** | **ABSENT** (parquet mai 2026 verifie) |
| `regime_mode`, `regime_favor`, `regime_confidence`, etc. | ABSENT | ABSENT | **PRESENT** (depuis 03/05) |
| `bias`, `bias_score`, `bias_confidence`, `div_*` | ABSENT | ABSENT | **ABSENT** (jamais persistes) |

**Note** : sur live_enriched, le code-reviewer a empiriquement constate
**14/27 champs DMP manquants**. Cela signifie que `live_enricher_writer` ne
forward pas tous les champs DMP. Avant de brancher Bot 3 sur live_enriched, il
faut soit :
1. Etendre `live_enricher_writer` pour forward tous les 28 champs.
2. Lire DMP JSONL directement en parallele et merger cote bot.

**Implications criticues pour Bot 3 v2 AXE 1** :
- Si bot lit live_enriched JSONL en direct : `compute_regime` plante sur
  features manquantes -> fallback aux defaults -> regime = `NORMAL/NEUTRE`
  constant inutile.
- Si bot lit v4_enriched parquet (lag 10-22 min) : regime OK depuis 03/05,
  mais `bias_*` doit etre calcule cote bot via `compute_bias(bar)` car
  jamais persiste.
- `atr_regime_zscore_60d` ABSENT meme du parquet v4 mai 2026 -> verifier
  Phase B status; en attendant `vol_regime = NORMAL` constant peu importe la
  source.

### D.5 — Solutions au trou `atr_regime_zscore_60d` cote live

3 options par ordre de cout croissant :

1. **Accepter vol_regime = NORMAL constant** -> on perd le gate
   `vol != EXTREME`. Si ce gate ne bloque que ~3% des trades historiquement
   (cf B.6 distribution attendue), perte marginale. Cout : 0. Risque : skip
   d'un EXTREME rare.
2. **Calculer cote bot un rolling 60d en streaming** : tenir un buffer ATR
   60 jours dans le bot, recalculer le z-score a chaque barre. Cout : ~50 LOC.
3. **Ajouter dans `live_enricher_writer.py`** un module Phase B online qui
   calcule `atr_regime_zscore_60d` au moment du write. Cout : **120-180 LOC +
   tests parite bit-for-bit avec batch** (buffer circulaire RTH-aware + state
   persistence + portage rolling pandas en streaming). Critique TIER 1 cf
   `.claude/rules/critical-tasks-review.md`.

**Recommande** : option 1 pour Phase 1 (perte minime), migration option 2
plus tard si gate EXTREME devient critique.

### D.6 — Pieges connus

- **`dist_vwap_d` convention** : positif = VWAP au-dessus du prix = prix
  SOUS VWAP = BEAR. Inverse de l'intuition.
- **`new_swing_high/low`** : peuvent etre `0` faux negatifs si la barre
  cloture pile sur l'ancien high (depend du tick size).
- **`delta_day_dir`** : `+1`/`-1`/`0`. Peut etre `0` si delta_day quasi nul
  (NaN tolerant via `_get_int_field`).
- **`atr_regime_zscore_60d`** : NaN sur les 60 premiers jours d'un instrument
  neuf -> fallback `NORMAL`. ES/NQ depuis 2024+ OK, MGC depuis activation
  05/2026 NaN avant ~07/2026.
- **`sess_range_atr`** : NaN ~90% sur ES (mesure 17/05 v4 mai 2026), absent
  MGC (cf B.6 fix 11/05). Utilise UNIQUEMENT vote 5 regime. Si NaN -> vote 5
  = 0 vote (ni TREND ni RANGE). (Note : valeur 97.5% citee anciennement dans
  B.6 source inconnue, mesure empirique recente donne 90.1%.)
- **`vix_level`** : peut etre stale (collecte H+1 vs barre 1m). Pour
  divergence quality (A.3 facteur 4), un VIX legerement perime est
  acceptable.

---

## Section E — Audit reproductible

Cette section donne les commandes exactes pour reproduire le calcul bias +
regime sur une barre donnee, et auditer une decision Bot 3 a posteriori.

### E.1 — Reproduire bias + regime sur une barre arbitraire

Script `tools/inspect_bias_decision.py` (a creer) :

```python
"""Inspect bias + regime + decision Bot 3 sur une barre precise.

Usage:
    python tools/inspect_bias_decision.py --symbol ES --date 20260331 --bar-ts 15:30:00
    python tools/inspect_bias_decision.py --jsonl DATA/live_enriched/ES/20260331_ES.jsonl --index 240
    python tools/inspect_bias_decision.py --parquet DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=05/data.parquet --row 1000
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from bias_calculator import compute_bias
from regime_engine import compute_regime


def load_bar(args) -> dict:
    if args.jsonl:
        with open(args.jsonl, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == args.index:
                    return json.loads(line)
        raise IndexError(f"index {args.index} out of range")
    elif args.parquet:
        import pandas as pd
        df = pd.read_parquet(args.parquet)
        return df.iloc[args.row].to_dict()
    else:
        # date + bar-ts -> chercher dans live_enriched/{SYM}/{YYYYMMDD}_{SYM}.jsonl
        sym_dir = "GC" if args.symbol == "MGC" else args.symbol
        path = ROOT / "DATA" / "live_enriched" / sym_dir / f"{args.date}_{args.symbol}.jsonl"
        target = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:8]}T{args.bar_ts}"
        with open(path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("ts_event_utc", "").startswith(target):
                    return d
        raise ValueError(f"bar {target} not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ES")
    ap.add_argument("--date", help="YYYYMMDD")
    ap.add_argument("--bar-ts", help="HH:MM:SS UTC")
    ap.add_argument("--jsonl")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--parquet")
    ap.add_argument("--row", type=int, default=0)
    args = ap.parse_args()

    bar = load_bar(args)
    print(f"--- Bar source : ts={bar.get('ts_event_utc', 'N/A')} close={bar.get('close')}")
    print()

    # BIAS
    bias = compute_bias(bar)
    print(f"=== BIAS ===")
    print(f"  direction     : {bias.direction}")
    print(f"  score_signed  : {bias.score_signed:+.3f}")
    print(f"  score_bull    : {bias.score_bull:.3f}")
    print(f"  score_bear    : {bias.score_bear:.3f}")
    print(f"  clarity       : {bias.bias_clarity:.3f}")
    print(f"  div_active    : {bias.div_active} (quality={bias.div_quality:.1f}, grade={bias.div_grade})")
    print(f"  reasons_bull  : {bias.reasons_bull}")
    print(f"  reasons_bear  : {bias.reasons_bear}")
    print(f"  is_trending   : {bias.is_trending}")
    print()

    # REGIME
    reg = compute_regime(bar)
    print(f"=== REGIME ===")
    print(f"  mode          : {reg.mode}")
    print(f"  favor         : {reg.favor}")
    print(f"  confidence    : {reg.confidence:.2f}")
    print(f"  votes T/R     : {reg.trend_votes}/{reg.range_votes}")
    print(f"  vol_regime    : {reg.vol_regime}")
    print(f"  bias_proxy    : {reg.bias_score:+.2f} (bear_factors={reg.bear_factors}, bull_factors={reg.bull_factors})")
    print(f"  actionable    : {reg.is_actionable}")
    print(f"  details       : {reg.details}")


if __name__ == "__main__":
    main()
```

### E.2 — Audit decision Bot 3 a posteriori

Une fois un trade pris (ou un skip), reproduire le verdict :

```python
# Apres avoir charge bar via E.1
from bot3_context_analyzer import analyze_context
from bot3_decision_engine import evaluate_decision
from bot3_level_definitions import BOT3_LEVELS

ctx = analyze_context(bar)  # signature reelle (cf bot3_context_analyzer.py:47)
# DIM 13 a venir : ctx["regime_favor"] = reg.favor, etc.

level_name = "IB_LOW"  # le niveau touche
level_def = BOT3_LEVELS[level_name]
dist_signed = level_def["price"] - bar["close"]   # convention 15/05

trade, reason, params = evaluate_decision(
    level_name, level_def, ctx, symbol="ES", dist_signed=dist_signed,
)
print(f"VERDICT : trade={trade}, reason={reason}, params={params}")
```

### E.3 — Sanity check sur trade journal Bot 3

Pour chaque trade JSONL emis par Bot 3 (Bot 3 ecrit dans le fichier partage
V3 paper_trader : `DATA/PAPER_TRADES/*_databento_v3_trades.jsonl`, filtrer
sur `mode == "BOT3"` ou champ equivalent),
les champs suivants permettent de reproduire le verdict :

```
ts_event_ns  -> retrouver la barre exacte dans live_enriched ou v4
symbol
level_name   -> level_def via BOT3_LEVELS
side         -> verdict final
reason       -> "GO" / "VETO_*" / "SKIP_*" / "TIER3_MISS_*"
confidence   -> tracking score
sl_ticks
atr_multiplier
```

Cross-checker avec :
- Verdict `compute_bias` -> direction (BULL / BEAR / NEUTRE)
- Verdict `compute_regime` -> favor (LONG / SHORT / NEUTRE)

Si `side != regime.favor` AND `regime.confidence > 0.50` -> trade "contre-sens
fort". A tracker dans un audit periodique (script E.4 a venir).

### E.4 — Audit periodique contre-sens

Backlog : ecrire `tools/audit_bot3_countertrend.py` qui scanne tous les
trades Bot 3 de la derniere semaine, joint la barre source pour chaque trade,
calcule bias + regime, et flag les `side != regime.favor` avec
`confidence > 0.50`. Sortie CSV avec colonnes (trade_id, ts, symbol, level,
side, regime_favor, bias_direction, pnl). Si > 30% des perdants sont des
contre-sens fort -> activer la version musclee de C.5.

### E.5 — Reproduction stricte (parite bit-for-bit)

Pour la migration AXE 1 (live_enriched -> Bot 3 v2), exiger un test de parite.
**Important** : la parite stricte 1e-6 n'est realiste que si les INPUTS sont
strictement identiques. Vu D.4 (14/27 champs manquants dans live_enriched), 2
options :

**Option A — parite sur DMP JSONL brut commun** (recommande) :
1. Selectionner 1000 barres aleatoires dans DMP JSONL brut ES mai 2026.
2. Calculer `compute_bias(bar)` et `compute_regime(bar)` directement.
3. Verifier que le verdict produit est stable et bien defini sur DMP brut.
4. Mesurer pour chaque barre la difference avec ce que produit le bot 3 v2
   en lisant la meme barre via live_enriched.
5. Divergence attendue UNIQUEMENT sur les champs manquants live ; logger les
   features qui different et estimer impact.

**Option B — parite sur v4_enriched output** :
1. Pour les barres ou `regime_*` est persiste (v4 depuis 03/05) :
2. Comparer `compute_regime(bar)` (recalcul) vs colonnes `regime_*` (lues).
3. Verifier identite a 1e-6 pres (sauf NaN attendus).
4. Si divergence > 1% des barres -> investigation obligatoire (calibration
   regime_engine drift entre 03/05 et aujourd'hui).

Cette parite garantit qu'on n'introduit pas de regression silencieuse en
migrant les sources.

---

## Annexe — Cross-references

- `CORE/bias_calculator.py` (497 LOC) — implementation biais.
- `CORE/regime_engine.py` (409 LOC) — implementation regime.
- `CORE/bot3_decision_engine.py` (~700 LOC) — decision Bot 3.
- `CORE/bot3_context_analyzer.py` (~277 LOC) — 12 dimensions contexte.
- `CORE/bot3_level_definitions.py` — 19 niveaux TIER 1/2/3.
- `CORE/phase_b_option_c_plus.py` — calcul `atr_regime_zscore_60d`.
- `DASHBOARD/api/builders.py:build_regime_context` — version dashboard
  (consomme `compute_bias` + `compute_regime`).
- `feedback_lightgbm_no_composite_indicators.md` — anti Pattern 11.
- `feedback_data_mining_trap.md` — DSR Lopez obligatoire.
- `.claude/rules/critical-tasks-review.md` — protocol review agents.
- `DOCS/BOT3_V2_CHANGES.md` (a venir) — recap consolide des modifications Bot 3 v2.
