# Audit B3 — F8 News + F9 Roll + F12 BarShape + F22 PositionRange

**Date** : 2026-06-07
**Scope** : audit pre-port C++ Sierra (lecture uniquement, pas de code).
**Schema actuel** : 3.7.19, n_cols 347 (B1 + B2 inclus).
**Auteur** : Claude Opus 4.7 — ULTRATHINK.
**Sources** :
- `DOCS/PORT_C++_SIERRA_INVENTORY.md` (inventaire exhaustif 5 jours)
- `DOCS/SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md` (30 jours NQ stratifies)
- `DOCS/AUDIT_FEATURES_V4_RAPPORT_28042026.md` (HIGH_CORR / LEAK flags)
- `DOCS/FORMULES_FEATURES_PHASE_B_PLUS.md` (formules canoniques)
- Inspection JSONL live `DATA/NQ/20260603_NQ.jsonl` (268 cols actuelles → 347 apres B1/B2 deploye)
- Code Python : `CORE/phase_b_plus_streaming.py`, `CORE/phase_b_plus_engine.py`,
  `CORE/enricher_chain.py`, `CORE/phase_b_helpers.py`,
  `CORE/sessions_swings_simple_streaming.py`
- Code C++ : `CPP/MIA_REFACTORED/DUMPER/DMP_Reader.h`,
  `DMP_Transform.h`, `DMP_Config.h`, `DMP_Writer.h`

---

## Contexte cle (avant d'entrer dans les matrices)

1. **Le `time_et` (mins_et) est deja calcule en C++** (`DMP_Reader.h:2727`)
   mais **PAS expose comme feature dans le JSONL**. Tout port F8 News
   coute "0 nouvelle logique horaire" : juste exposer `mins_et` puis 6+6+2
   booleans/scalaires derives.

2. **Le `d.contract` (sc.Symbol → "ESH26-CME")** est lu en C++
   (`DMP_Reader.h:2666-2673`). On peut detecter la roll par discontinuite
   de contrat (equivalent du `instrument_id` Databento utilise en Python).

3. **Le `range_pos` C++ existant** (DMP_Transform.h:824) =
   `(close - cur_val) / (cur_vah - cur_val)` clip 0-100. C'est la
   position dans la **Value Area courante**, pas dans le range
   journalier. Il **NE COLLIDE PAS** avec F22 Python qui couvre 2
   autres metriques :
     - `pct_in_range` = position dans `sess_high/sess_low` (range session)
     - `position_in_range` = position dans `mq_1d_max/min` (range MQ daily)
   Les 3 features mesurent 3 choses differentes. Pas de doublon.

4. **`atr_14m` est PRESENT dans le JSONL live** (vu C++ DMP_Config.h ligne 162).
   Donc on peut normaliser `bar_body` en TICKS (deja fait en Python ligne
   754 de `enricher_chain.py` via `body / _tick`). Bonne nouvelle pour F12.

5. **AUCUNE etude Sierra `NEWS XX.XX` n'est mappee** dans
   `CPP/MIA_REFACTORED/study_mapping.json`. Le Python utilise des mins_et
   hardcodes (NEWS_TIMES_ET). Le port C++ devra donc **reproduire la
   meme logique hardcodee** (ou utiliser le `news_filter.py` JSON externe,
   mais cela depasse le scope du port).

---

## F8 News (14 features Python)

Source canonique Python : `CORE/phase_b_plus_engine.py:708-715` + `CORE/phase_b_plus_streaming.py:456-474`.

```python
NEWS_TIMES_ET = [
    (7, 15, "news_715"),   # ICSM / Tankan / Survey du jeudi
    (7, 30, "news_730"),   # NFP / CPI / PCE / Jobless Claims
    (8, 30, "news_830"),   # Retail Sales / Durable Goods
    (8, 45, "news_845"),   # ECB rate
    (9, 0,  "news_900"),   # Consumer Confidence
    (9, 30, "news_930"),   # RTH open + ISM / Pending Home Sales
]
```

### Matrice F8

| Feature Python | Formule (resume) | Source Sierra | Type | Spearman documente | Effort C++ |
|---|---|---|---|---|---|
| `is_news_715` | `mins_et == 7*60+15` | mins_et interne C++ | boolean event | NC (rare event) | TRIVIAL (5 min) |
| `is_news_730` | `mins_et == 7*60+30` | mins_et interne C++ | boolean event | NC | TRIVIAL (5 min) |
| `is_news_830` | `mins_et == 8*60+30` | mins_et interne C++ | boolean event | NC | TRIVIAL (5 min) |
| `is_news_845` | `mins_et == 8*60+45` | mins_et interne C++ | boolean event | NC | TRIVIAL (5 min) |
| `is_news_900` | `mins_et == 9*60+0`  | mins_et interne C++ | boolean event | NC | TRIVIAL (5 min) |
| `is_news_930` | `mins_et == 9*60+30` | mins_et interne C++ | boolean event | NC (collide is_cash_session) | TRIVIAL (5 min) |
| `within_news_715_5m` | `mins_et in [tgt, tgt+5)` | mins_et interne | boolean fenetre | NC | TRIVIAL |
| `within_news_730_5m` | idem | mins_et | boolean | NC | TRIVIAL |
| `within_news_830_5m` | idem | mins_et | boolean | NC | TRIVIAL |
| `within_news_845_5m` | idem | mins_et | boolean | NC | TRIVIAL |
| `within_news_900_5m` | idem | mins_et | boolean | NC | TRIVIAL |
| `within_news_930_5m` | idem | mins_et | boolean | NC | TRIVIAL |
| `mins_since_news` | min(mins_et - n) for n <= mins_et, default -1 | mins_et + tableau static | scalar | NC (probable -0.02 a +0.02) | TRIVIAL (10 min) |
| `mins_to_next_news` | min(n - mins_et) for n > mins_et, default -1 | mins_et + tableau | scalar | NC | TRIVIAL (10 min) |

### Verdict F8

**GO PORT C++** (14 features, **TOUTES**).
- Le coeur de la logique est **deja en C++** (`time_et` calcule
  `DMP_Reader.h:2727`).
- Aucune dependance externe (pas de JSON eco a parser).
- Effort C++ minimal : ~1-2h total (struct fields + tableau hardcode +
  serialization + CSV header).
- Spearman non documente individuellement, mais features connues utilisees
  par bias_calculator_v6 + bot3_context_analyzer (filtres veto pre-news).
- **Note critique** : `is_news_930` collide avec `is_cash_session==1`
  starting (mins_et==570). Pas un bug — c'est la realite : 09:30 = RTH
  open + news ISM. Pas d'action.

**Risque** : `mins_since_news = -1` et `mins_to_next_news = -1` sont des
sentinelles qui peuvent leak dans LightGBM si pas mappees `null`. Verifier
que `DMP_WR_IsInvalid` traite -1 correctement, sinon clip a `DMP_INVALID`.

**ETA F8** : **2h** (incl. tests parite Python).

---

## F9 Roll (3 features Python)

Source canonique Python : `CORE/enricher_chain.py:1861-1904`.

```python
# Detection : discontinuity instrument_id entre 2 bars consecutives
is_roll_now = (cur_iid != last_iid)
# Compteur depuis dernier roll
bars_since_roll = 0 if is_roll_now else bars_since_roll + 1
# Phase (3 classes)
days_since_roll = bars_since_roll / 1380   # 1380 bars 1m = 1 jour trading
roll_phase = 0 if dsr <= 15 else 1 if dsr <= 45 else 2
```

### Matrice F9

| Feature Python | Formule (resume) | Source Sierra | Type | Spearman documente | Effort C++ |
|---|---|---|---|---|---|
| `is_roll_day` | `1` le jour de discontinuite contrat, `0` sinon (broadcast tout le jour) | `d.contract` discontinuite (sc.Symbol) | boolean event-day | NC | EASY (1h, persistant state) |
| `days_since_roll` | `bars_since_roll / 1380` (NaN si jamais vu roll) | counter persistant | scalar continu | NC | EASY (1h) |
| `roll_phase` | 0=early <=15j, 1=mid 15-45j, 2=late >45j | derivee days_since_roll | categorical | **HIGH_CORR_INSTRUMENT (ks=1.0)** ⚠️ | EASY (10 min) |

### Verdict F9

**Audit critique** : `roll_phase` est tagge `HIGH_CORR_INSTRUMENT` avec
**ks=1.0** dans `AUDIT_FEATURES_V4_RAPPORT_28042026.md:555`. Cela veut
dire que **la distribution de `roll_phase` est identique entre ES et NQ**
(1.0 = correlation parfaite avec l'instrument). Ce qui est LOGIQUE : si
on est a J+20 du roll ES, on est a J+20 du roll NQ aussi (quarterly meme
date). C'est un **leak instrument** trivial. LightGBM peut s'appuyer
dessus pour distinguer ES vs NQ. **Edge ML douteux**.

`days_since_roll` est `null` 100% du temps dans l'inventaire 5 jours
(PORT_C++_SIERRA_INVENTORY.md:564) parce qu'au cold start le premier
roll n'a jamais ete vu. **Probleme operationnel** : il faut un seed
initial (ex: `bars_since_roll = bars_since_session_start * N`) sinon
toujours null en mode short-window.

`is_roll_day` est l'evenement RARE (4 fois/an pour ES, 4 fois/an pour
NQ). Sur 5 jours d'inventaire : `0.0% null` mais 100% = 0 → pas vu
de roll donc valeur = 0 partout. Spearman impossible a calculer.

**Decisions** :
1. `is_roll_day` → **GO PORT C++** (event-driven, edge connu pour roll
   day volatility spike, utile pour filtrage RiskManager). Effort 1h.
2. `days_since_roll` → **DEFER** (semantiquement OK mais probleme
   "null au cold start" non resolu, edge ML probablement nul, 100%
   null sur 5 jours inventoires).
3. `roll_phase` → **DROP** (LEAK INSTRUMENT, ks=1.0 entre ES/NQ — risque
   train-serve skew, biais structurel).

### Detail technique implementation `is_roll_day`

- Stocker `last_contract[32]` en PersistVars (per chart).
- Au boot premier bar : initialiser `last_contract = d.contract`,
  `is_roll_day = 0`.
- Chaque bar : si `strcmp(d.contract, last_contract) != 0` →
  `is_roll_day = 1`, `last_contract = d.contract`. Sinon `is_roll_day = 0`
  (mais reset session le maintient flag du jour entier via session_date
  tracker — cf logique Python ligne 1864-1867).
- Reset `is_roll_day = 0` au changement de `date_et` (sauf si la
  discontinuite a lieu CE jour).

**Risque** : sc.Symbol peut changer si Jackson change manuellement de
chart (ex: passe de ESM26 a NQM26). Ce ne sont PAS des rolls, ce sont
des switches operateur. **Mitigation** : detecter aussi le changement
de ticker root (`ES` → `NQ`) et flagger comme `manual_switch` distinct
du `roll`. **Sinon le faux positif passe en prod**.

**ETA F9** : **2h** pour `is_roll_day` seul (incl. test cas roll +
test cas manual switch + test cas idempotent intra-day).

---

## F12 BarShape (12 features Python)

Sources :
- `CORE/enricher_chain.py:740-758` (bar_body_pct, bar_body_ticks, avg_price)
- `CORE/enricher_chain.py:1341-1364` (bar_upper_wick_pct, bar_lower_wick_pct, bar_no_trade)
- `CORE/phase_b_plus_streaming.py:499-505` (long_up_bar, long_dn_bar, range_h_minus_lprev_ticks)
- `CORE/phase_b_helpers.py:1275` (range_size)
- `CORE/build_dataset_v4_dmp_databento.py:809` (bar_upper_wick_pct clamp 0-3)

### Matrice F12

| Feature Python | Formule (resume) | Source Sierra | Type | Spearman / SHAP | Effort C++ |
|---|---|---|---|---|---|
| `bar_body_pct` | `(close - open) / range * 100`, signed | OHLC bar (deja en C++) | scalar continu | OK (non flagge audit 28/04) | TRIVIAL (5 min) |
| `bar_body_ticks` | `(close - open) / tick_size` signed | OHLC + DMP_TICK_NQ/ES | scalar integer | OK | TRIVIAL (5 min) |
| `bar_upper_wick_pct` | `(high - max(open,close)) / close * 100` clamp 0-3 | OHLC | scalar [0,3] | **mentionne design Bot 4 SIM4** (sim4-redesign-design.md:337) | TRIVIAL (5 min) |
| `bar_lower_wick_pct` | `(min(open,close) - low) / close * 100` clamp 0-3 | OHLC | scalar [0,3] | idem (Bot 4) | TRIVIAL (5 min) |
| `bar_no_trade` | `1 if delta_bar isna else 0` | delta_bar (deja en C++) | boolean | OK | TRIVIAL (5 min) |
| `long_up_bar` | `body > seuil * ATR` ET close > open | body + ATR (deja en C++) | boolean | OK | EASY (15 min, seuil per-symbol) |
| `long_dn_bar` | `body > seuil * ATR` ET close < open | idem | boolean | OK | EASY (15 min) |
| `long_dn_up_pattern` | long_dn_bar[-1] ET long_up_bar[0] | shift(-1) → state | boolean | OK | EASY (20 min, persistant) |
| `long_up_dn_pattern` | long_up_bar[-1] ET long_dn_bar[0] | shift(-1) → state | boolean | OK | EASY (20 min) |
| `range_h_minus_lprev_ticks` | `(high[0] - low[-1]) / tick` | high + prev_low (state) | scalar continu | **LEAK_VOLATILITY HIGH_CORR_INSTRUMENT** ⚠️ (audit 28/04 ligne 553) | EASY (15 min) |
| `range_hprev_minus_l_ticks` | `(high[-1] - low[0]) / tick` | prev_high + low (state) | scalar continu | **LEAK_VOLATILITY HIGH_CORR_INSTRUMENT** ⚠️ (audit 28/04 ligne 554) | EASY (15 min) |
| `range_size` | `(high - low)` en POINTS | OHLC | scalar continu | OK | TRIVIAL (5 min) |

### Verdict F12

**GO PORT C++ — 10 features sur 12**.

**Justifications** :
- F12 est la famille la plus simple (tous calculs O(1) sur OHLC + tick +
  ATR — TOUS deja disponibles en C++).
- 6 features TRIVIAL (5 min chacune).
- 4 features EASY (15-20 min chacune, persistance shift -1).
- Aucune dependance externe.
- `bar_upper_wick_pct` / `bar_lower_wick_pct` sont **DEMANDES PAR LE
  DESIGN BOT 4 SIM4** (cf `sim4-redesign-design.md:337` "Bar shape").
  Edge use-case identifie.

**DROP — 2 features** :
- `range_h_minus_lprev_ticks` : **LEAK_VOLATILITY + HIGH_CORR_INSTRUMENT**
  (ks_em=4.382, ks_em > 4 = leak severissime, audit 28/04). Pas de port.
- `range_hprev_minus_l_ticks` : idem (ks_em=4.451). Pas de port.

  **Note** : ces 2 features mesurent le "range etendu sur 2 bars"
  (gap detection). Probleme : `(high[0] - low[-1])` peut etre negatif
  (gap down) ou exploser (range elargi), donc tres skewed et fait du
  data-mining sur l'instrument. **Si Jackson y tient**, considerer
  une version normalisee `_pct` au lieu de `_ticks`.

**Risque pattern 11** : `long_up_bar` et `long_dn_bar` utilisent un
**seuil**, et le seuil C++ existant pour `bar_long_up_bar` /
`bar_long_dn_bar` (Sierra study) est connu DIVERGENT de la formule
Python (cf `SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md` features Sierra-only
ligne 197-200). **DECISION** : ne pas dupliquer — utiliser le standard
**Python** (seuil `2.0 * ATR` documente dans `add_phase_b_plus_long`).

**ETA F12** : **3h** pour les 10 features (5 trivial + 5 easy).

---

## F22 PositionRange (3 features Python)

Sources :
- `CORE/sessions_swings_simple_streaming.py:332-339` (pct_in_range, premium_zone, discount_zone)
- `CORE/enricher_chain.py:1373-1381` (position_in_range — 4eme feature
  NON listee F22 dans l'inventaire mais cle pour Bot 3)

### Matrice F22

| Feature Python | Formule (resume) | Source Sierra | Type | Spearman / Audit | Effort C++ |
|---|---|---|---|---|---|
| `pct_in_range` | `(close - sess_low) / (sess_high - sess_low) * 100` clamp 0-100 | sess_high/low (deja en C++ via OHLC RTH) | scalar [0,100] | OK (audit 28/04 ligne 548) | TRIVIAL (5 min) |
| `premium_zone` | `1 if pct_in_range > 50 else 0` | derivee pct_in_range | boolean | OK (audit ligne 552) | TRIVIAL (3 min) |
| `discount_zone` | `1 if pct_in_range < 50 else 0` | derivee pct_in_range | boolean | **COLLINEAR with premium_zone (corr -0.989)** ⚠️ | TRIVIAL (3 min) |
| `position_in_range` (BONUS hors inventaire F22) | `(close - mq_1d_min) / (mq_1d_max - mq_1d_min)` clamp 0-1 | mq_1d_min/max (deja en C++) | scalar [0,1] | **HIGH_CORR_INSTRUMENT (ks=1.044)** ⚠️ (ligne 551) | TRIVIAL (10 min) |

### Verdict F22

**Audit critique** :
- `discount_zone` = **1 - premium_zone STRICT** (corr -0.989). **Doublon
  parfait**. C'est le meme signal cote LightGBM. Sur 2, ne porter QU'UNE
  des deux. Convention : garder `premium_zone` (semantique positive
  "premium au-dessus mid-range").
- `position_in_range` est HIGH_CORR_INSTRUMENT (ks=1.044), donc
  potentiellement **leak instrument**. Mais formule basee sur MQ daily
  (instrument-specific input). Edge : utilise par Bot 3 (`MQ_CALL_POC_FLAT
  >= 0.70` cf bot3_decision_engine.py test_211). **Si Bot 3 le consomme
  en live, il DOIT etre porte aussi**, sinon Bot 3 verra `None`.

**Pas de collision avec range_pos C++ existant** :
- `range_pos` (C++ existant) = position dans **Value Area** courante.
- `pct_in_range` (F22) = position dans **session high/low**.
- `position_in_range` (Bot 3) = position dans **MQ daily max/min**.
- 3 metriques semantiquement distinctes → on les garde **toutes les 3**
  (cote C++ : 1 existante + 2 a porter).

**GO PORT C++** :
- `pct_in_range` (TRIVIAL, 5 min)
- `premium_zone` (TRIVIAL, 3 min)
- `position_in_range` (TRIVIAL, 10 min — depend mq_1d_max/min lus dans
  C++)

**DROP** :
- `discount_zone` (DOUBLON `premium_zone`, corr -0.989).

**ETA F22** : **30 min** (3 features TRIVIAL).

---

## Synthese

### Features GO PORT par famille

| Famille | GO | DEFER | DROP | Notes |
|---|---|---|---|---|
| F8 News | 14 | 0 | 0 | Tous portables, edge sentinelle `-1` a verifier |
| F9 Roll | 1 | 1 | 1 | `is_roll_day` seul (DEFER `days_since_roll`, DROP `roll_phase` leak) |
| F12 BarShape | 10 | 0 | 2 | 2 DROP : `range_h_minus_lprev_ticks` / `range_hprev_minus_l_ticks` LEAK |
| F22 PositionRange | 3 | 0 | 1 | `position_in_range` ajoute (hors inventaire initial). DROP `discount_zone` doublon |
| **TOTAL** | **28** | **1** | **4** | |

### Schema bump

- Schema actuel : `3.7.19` → n_cols **347**
- Schema apres B3 : `3.7.20` → n_cols **347 + 28 = 375**

### ETA total

| Famille | ETA | Detail |
|---|---|---|
| F8 News | 2h | Expose mins_et (trivial) + tableau hardcode + 14 features |
| F9 Roll | 2h | is_roll_day seul + state PersistVars + protection manual_switch |
| F12 BarShape | 3h | 10 features dont 4 stateful (shift -1) |
| F22 PositionRange | 30 min | 3 features TRIVIAL |
| Tests parite Python | 2h | `tools/test_parity_B3.py` sur 5 jours NQ |
| Deploy + bench + INCIDENT_LOG | 1h | scp, recompile, validate, doc |
| **TOTAL** | **10h30** | sur 1 a 2 sessions selon Jackson |

### Ordre d'implementation suggere

**Sequencing intentionnel anti pattern 11 (1 famille a la fois,
backtest entre) — recommandation forte** :

1. **F22 PositionRange** (30 min, le plus rapide) — quick win, prouve
   l'infra de bump schema 3.7.19 → 3.7.20.
2. **F12 BarShape** (3h) — couvre 10 features, edge use-case
   documente (Bot 4 SIM4).
3. **F8 News** (2h) — ajoute la couche temporelle/event.
4. **F9 Roll** (2h) — feature evenementielle rare, faire en dernier
   (risque faux positif manual switch a tester soigneusement).

### Risques identifies

1. **Pattern 11** : ne PAS porter en bloc 28 features puis backtester
   sur le total. Porter famille par famille, valider apres chaque
   famille (test_parity + bench mia_bench.py + verdict feature-engineer
   sur edge marginal).

2. **Sentinelles `-1` F8** : `mins_since_news = -1` et `mins_to_next_news = -1`
   pendant 23h/24h (hors fenetre 7h15-9h30 ET). Si serialisees sans clip
   `DMP_INVALID`, LightGBM apprendra une feature constante a -1 +
   pic 0-285 pendant 2h15. **Strict requirement** : DMP_INVALID au lieu
   de -1.

3. **F9 manual_switch** : sc.Symbol peut changer si Jackson edit le
   chart. Risque faux positif `is_roll_day = 1`. Tester en
   incident-simulation (changer sc.Symbol manuellement, verifier
   detection vs faux positif).

4. **F12 `long_up_bar` divergence Sierra** : eviter le piege Sierra-only
   `bar_long_up_bar` (formule SC differente). Implementer formule
   Python `body > 2 * ATR` pour parite.

5. **F22 `position_in_range` HIGH_CORR_INSTRUMENT** : a flagger dans
   quality_validator.py NATURALLY_DIFFERENT (justification : input
   MQ daily est instrument-specific par design).

6. **Train-serve skew B3** : apres deploy, Bot 4 doit etre **re-entraine**
   sur dataset incluant les 28 nouvelles features. Sinon scoring sur
   features absentes → fallback null → degradation. **Mandatory ml-trainer
   verdict apres backfill + retrain**.

7. **Documentation** : update `DMP_Config.h` schema bump notes,
   `DOCS/BOT_CHANGELOG.md` entry, `DOCS/INCIDENT_LOG.md` si imprevu.
