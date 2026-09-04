# Phase 3 — effet de la confluence de zones

Genere par `CORE/research/phase3_confluence.py`.

Le test qui compte est la **monotonie** (correlation de Spearman entre le nombre de zones empilees et le resultat du trade), pas la performance d'un palier isole. Achats et ventes sont rapportes separement pour ecarter le beta directionnel.

## ES — 843 touches sur 41 jours (20.6/jour), confluence mesuree sur +/-8 ticks, barriere +/-10 ticks


### FADE

| zones | n | esperance | reussite | PF |
|---|---|---|---|---|
| 1 | 305 | -2.62 | 46.9 % | 0.59 |
| 2 | 271 | -2.68 | 46.5 % | 0.58 |
| 3 | 136 | -0.53 | 57.4 % | 0.90 |
| 4 | 82 | -2.24 | 48.8 % | 0.63 |
| 5 | 22 | +3.45 | 77.3 % | 2.27 |

Monotonie : rho = +0.065, p = 0.059 — **pas d'effet**

### BREAK

| zones | n | esperance | reussite | PF |
|---|---|---|---|---|
| 1 | 305 | -1.77 | 51.1 % | 0.70 |
| 2 | 271 | -1.61 | 52.0 % | 0.72 |
| 3 | 136 | -3.62 | 41.9 % | 0.48 |
| 4 | 82 | -2.00 | 50.0 % | 0.67 |
| 5 | 22 | -7.45 | 22.7 % | 0.20 |

Monotonie : rho = -0.055, p = 0.110 — **pas d'effet**

## NQ — 786 touches sur 41 jours (19.2/jour), confluence mesuree sur +/-32 ticks, barriere +/-40 ticks


### FADE

| zones | n | esperance | reussite | PF |
|---|---|---|---|---|
| 1 | 399 | -8.71 | 42.9 % | 0.65 |
| 2 | 218 | -6.30 | 45.9 % | 0.73 |
| 3 | 108 | -2.26 | 50.9 % | 0.89 |
| 4 | 25 | +1.80 | 56.0 % | 1.10 |

Monotonie : rho = +0.083, p = 0.020 — **effet**

### BREAK

| zones | n | esperance | reussite | PF |
|---|---|---|---|---|
| 1 | 399 | -6.31 | 45.9 % | 0.73 |
| 2 | 218 | -7.40 | 44.5 % | 0.69 |
| 3 | 108 | -5.22 | 47.2 % | 0.77 |
| 4 | 25 | -11.00 | 40.0 % | 0.57 |

Monotonie : rho = -0.017, p = 0.635 — **pas d'effet**
