# Distributions pour la barriere par niveaux — mesure J1

*20 dernieres journees par instrument. Aucun seuil choisi ici.*

## ES — 20 jours, 308 barres cash

### 1. Premier niveau, distance en ATR (les deux cotes)
| quantile | au-dessus | au-dessous | confondu |
|---|---|---|---|
| p10 | 0.048 | 0.050 | 0.049 |
| p25 | 0.098 | 0.113 | 0.104 |
| p50 | 0.234 | 0.237 | 0.235 |
| p75 | 0.507 | 0.538 | 0.528 |
| p90 | 0.992 | 0.945 | 0.971 |

### 2. Buffer de balayage (prev_* regagnes, 1 min, ticks)
tous episodes : n = 98 | p50 16.0 | p75 31.8 | p90 63.0
**SWEEPS (<= 15 min)** : n = 77 | p50 13.0 | **p75 20.0** | p90 32.6 — le buffer prend celui-ci

### 3. Derive mediane de cur_vah par heure UTC (ticks/barre)
| heure | derive p50 | n |
|---|---|---|
| 13 | 4.5 | 16 |
| 14 | 3.0 | 64 |
| 15 | 2.0 | 64 |
| 16 | 1.0 | 64 |
| 17 | 5.5 | 60 |
| 18 | 3.0 | 60 |
| 19 | 2.0 | 60 |

## NQ — 20 jours, 298 barres cash

### 1. Premier niveau, distance en ATR (les deux cotes)
| quantile | au-dessus | au-dessous | confondu |
|---|---|---|---|
| p10 | 0.030 | 0.039 | 0.034 |
| p25 | 0.095 | 0.100 | 0.097 |
| p50 | 0.205 | 0.233 | 0.224 |
| p75 | 0.439 | 0.456 | 0.452 |
| p90 | 0.800 | 0.799 | 0.800 |

### 2. Buffer de balayage (prev_* regagnes, 1 min, ticks)
tous episodes : n = 123 | p50 78.0 | p75 151.0 | p90 375.6
**SWEEPS (<= 15 min)** : n = 101 | p50 58.0 | **p75 109.0** | p90 178.0 — le buffer prend celui-ci

### 3. Derive mediane de cur_vah par heure UTC (ticks/barre)
| heure | derive p50 | n |
|---|---|---|
| 13 | 17.5 | 16 |
| 14 | 4.0 | 64 |
| 15 | 7.5 | 64 |
| 16 | 3.5 | 64 |
| 17 | 35.5 | 60 |
| 18 | 9.0 | 60 |
| 19 | 8.0 | 60 |
