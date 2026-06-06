# Backtest 2 Raffinement + Backtest 3 Walk-forward

**Date** : 2026-06-07
**Mode** : FULL REGLES (pas de ML)
**NQ jours** : 80
**ES jours** : 81
**Label** : forward 60 bars (close[t+60] - close[t])

## Backtest 2 — Raffinement A3 (6 variantes)

Variantes testees :
- V1 : Baseline A3 (Multi-temporal momentum + Confluence)
- V2 : V1 + delta_bar persistence (% bars positifs sur 20)
- V3 : V1 + big_spawn_rate (n_big_ask - n_big_bid normalise)
- V4 : V1 + cvd_session direction (log-scaled)
- V5 : V1 + range_pos extremes (Sierra sain)
- V6 : MIX BEST (combinaison V2+V3+V4+V5)

### Resultats NQ + ES

| Variant | n_NQ | rho_NQ | |rho|_NQ | sig% NQ | n_ES | rho_ES | |rho|_ES | sig% ES |
|---|---|---|---|---|---|---|---|---|
| `V4_with_cvd_session` | 79 | -0.1613 | 0.1993 | 74.7% | - | -0.185 | 0.2174 | 73.8% |
| `V1_baseline` | 80 | -0.1614 | 0.1989 | 75.0% | - | -0.1815 | 0.2126 | 72.8% |
| `V5_with_range_pos` | 80 | -0.1576 | 0.1925 | 73.8% | - | -0.1782 | 0.2084 | 74.1% |
| `V6_mix_best` | 79 | -0.1199 | 0.1507 | 68.4% | - | -0.1357 | 0.166 | 68.8% |
| `V2_with_delta_pers` | 80 | -0.11 | 0.1443 | 58.8% | - | -0.1212 | 0.1546 | 65.4% |

**BEST** : `V4_with_cvd_session` (|rho| = 0.1993)

## Backtest 3 — Walk-forward 4-fold NQ

Best variante teste : `V4_with_cvd_session`

| Fold | Periode | n_days | rho_mean | rho_median | sig% (>0.1) |
|---|---|---|---|---|---|
| Q1 | 20260121->20260217 | 20 | -0.0781 | -0.0399 | 75.0% |
| Q2 | 20260218->20260317 | 20 | -0.1754 | -0.1723 | 70.0% |
| Q3 | 20260318->20260416 | 20 | -0.2107 | -0.2153 | 75.0% |
| Q4 | 20260417->20260602 | 19 | -0.182 | -0.162 | 78.9% |

⚠️ **PARTIEL** : 3/4 folds significatifs, 1 fold faible

Range rho : [-0.211, -0.078], variance = 0.133

## Verdict global

⚠️ **CANDIDATE** : `V4_with_cvd_session` solide global mais instabilite cross-period.