# Bot 3 v2 — Audit Phase 1.0 (run post_fix_6m_v4_enriched)

**Date** : auto-generated
**Source** : trades JSONL post-fix dist_signed 15/05/2026.
**Cross-ref** : `DOCS/BOT3_V2_CHANGES.md` AXE 4-5-6, 
`DOCS/BIAS_DIRECTION_DETECTION_CLARIFICATION.md`.

## Baseline Bot 3 v1 (post-fix)

- ES : 5771 trades, PF_net = 0.73
- NQ : 9782 trades, PF_net = 1.26
- Total : 15553 trades

## AXE 4 — Confluences niveau × COLOR/LONG BAR

- Confluences GO (5 criteres Lopez par item) : **0**
- Total combinaisons testees : 86

## AXE 5 — BLOCKED_COMBOS_BOT3

- Combos BLOCK (5 criteres Lopez par combo, Bonferroni n_trials=1064) : **5**
- Gain estime sur 6m (sum pnl_ticks_net negatif evite) : 
  5627 ticks

### Combos BLOCK

| symbol | session | level | n | PF | CI | DSR | folds LT 0.7 |
|---|---|---|---|---|---|---|---|
| ES | ASIA | SIDAK_SWING_HIGH | 306 | 0.46 | [0.33, 0.62] | 1.000 | 10/12 |
| ES | ASIA | VWAP_W_SD1D | 128 | 0.52 | [0.33, 0.82] | 1.000 | 9/12 |
| ES | ASIA | SIDAK_SWING_LOW | 230 | 0.53 | [0.37, 0.74] | 1.000 | 9/12 |
| ES | LONDON | CUR_VPOC | 236 | 0.45 | [0.32, 0.61] | 1.000 | 10/12 |
| ES | LONDON | SINGLE_PRINT | 127 | 0.66 | [0.40, 1.04] | 1.000 | 8/12 |

## AXE 6 — SESSION_BOOST_CONFIDENCE

- Combos BOOST : **2** 
  (verdict pour Phase 1.7 — application dans `bot3_decision_engine` etape 6)

### Combos BOOST

| symbol | session | level | n | PF | CI | DSR | folds GE 1.3 |
|---|---|---|---|---|---|---|---|
| ES | US_CASH | SIDAK_COLOR_DN_zone | 189 | 1.78 | [1.21, 2.71] | 1.000 | 10/12 |
| NQ | LONDON | SIDAK_COLOR_UP_zone | 459 | 2.02 | [1.59, 2.63] | 1.000 | 9/12 |

## AXE 7 — ATR sweep ES

| atr_bucket | n | WR | PF | CI |
|---|---|---|---|---|
| <=0.7 | 1542 | 35.1% | 0.43 | [0.38, 0.49] |
| 0.7-0.8 | 288 | 43.1% | 0.65 | [0.48, 0.86] |
| 0.8-0.9 | 293 | 47.8% | 0.60 | [0.46, 0.79] |
| 0.9-1.0 | 261 | 46.7% | 0.64 | [0.46, 0.84] |
| 1.0-1.2 | 501 | 53.3% | 0.74 | [0.60, 0.92] |
| 1.2-1.5 | 2886 | 66.0% | 0.87 | [0.80, 0.95] |
| <=0.7 | 1517 | 55.8% | 1.10 | [0.97, 1.23] |
| 0.7-0.8 | 534 | 59.2% | 1.11 | [0.93, 1.33] |
| 0.8-0.9 | 599 | 62.8% | 1.13 | [0.95, 1.36] |
| 0.9-1.0 | 544 | 65.8% | 1.18 | [0.98, 1.46] |
| 1.0-1.2 | 947 | 68.0% | 1.20 | [1.03, 1.39] |
| 1.2-1.5 | 5641 | 74.0% | 1.33 | [1.25, 1.42] |

## Verdict GO/NOGO Phase 1.0

- AXE 4 (confluences) : 0 setups GO. 
  -> NOGO (aucune confluence stable)
- AXE 5 (BLOCK) : 5 combos. 
  -> GO
- AXE 6 (BOOST) : 2 combos. 
  -> NOGO
- AXE 7 (VETO_ATR_LOW ES) : voir table sweep, choisir seuil ou la marche est monotone.

## Decision Jackson + ml-trainer + market-analyst

- Valider la liste finale des confluences (AXE 4) ?
- Valider la liste finale des combos BLOCK / BOOST (AXE 5/6) ?
- Choisir seuil VETO_ATR_LOW ES (AXE 7) ?

Si tout GO -> passer Phase 1.1+ implementation.
