# Quelles features predisent le regime ?

Genere par `CORE/research/audit_features_vs_regime.py`.

Cible : Efficiency Ratio de Kaufman sur les 30 barres suivantes. TREND = ER au-dessus du 70e percentile, RANGE = sous le 30e.

Une feature est **retenue** seulement si elle est significative sur la periode d'entrainement ET sur la periode de test (Benjamini-Hochberg a 5 %), avec le meme sens, et un ecart |AUC-0.50| d'au moins 0.05 sur l'entrainement et 0.03 sur le test.

## ES — 9380 barres classees (5628 train / 3752 test), 325 features testees

Seuil TREND : ER >= 0.258. Seuil RANGE : ER <= 0.096.

**3 features retenues sur 325 testees.**

| feature | AUC train | AUC test | ecart test | retenue |
|---|---|---|---|---|
| `n_long_up_zones_active` | 0.568 | 0.560 | 0.060 | **OUI** |
| `dist_sess_low` | 0.422 | 0.453 | 0.047 | **OUI** |
| `dist_sess_low_pct` | 0.421 | 0.453 | 0.047 | **OUI** |
| `dist_prev_vwap_sd1u` | 0.473 | 0.390 | 0.110 |  |
| `dist_prev_vwap_sd1d` | 0.454 | 0.390 | 0.110 |  |
| `dist_prev_vwap` | 0.464 | 0.390 | 0.110 |  |
| `dist_prev_vpoc` | 0.477 | 0.392 | 0.108 |  |
| `dist_prev_vpoc_atr` | 0.477 | 0.394 | 0.106 |  |
| `dist_prev_val` | 0.453 | 0.394 | 0.106 |  |
| `dist_prev_vah` | 0.476 | 0.394 | 0.106 |  |
| `dist_sess_high` | 0.509 | 0.397 | 0.103 |  |
| `dist_sess_high_pct` | 0.509 | 0.397 | 0.103 |  |

## NQ — 9374 barres classees (5624 train / 3750 test), 305 features testees

Seuil TREND : ER >= 0.256. Seuil RANGE : ER <= 0.096.

**0 features retenues sur 305 testees.**

| feature | AUC train | AUC test | ecart test | retenue |
|---|---|---|---|---|
| `dist_ib_high_pct` | 0.538 | 0.423 | 0.077 |  |
| `ctx_range_vs_atr_10` | 0.542 | 0.425 | 0.075 |  |
| `atr_14m_pct` | 0.537 | 0.427 | 0.073 |  |
| `dist_ib_low` | 0.521 | 0.427 | 0.073 |  |
| `atr_14m` | 0.535 | 0.427 | 0.073 |  |
| `trend_day_probability` | 0.469 | 0.429 | 0.071 |  |
| `dist_ib_high` | 0.536 | 0.430 | 0.070 |  |
| `dist_cash_high_atr` | 0.458 | 0.568 | 0.068 |  |
| `dist_cash_high_pct` | 0.539 | 0.434 | 0.066 |  |
| `dist_us_high_pct` | 0.461 | 0.566 | 0.066 |  |
| `dist_ib_low_pct` | 0.523 | 0.436 | 0.064 |  |
| `dist_mq_hvl_0dte` | 0.533 | 0.436 | 0.064 |  |
