# Les seize en ombre — fréquence sur le lot (aucun devenir lu)

*Attendu écrit avant la passe : si les quatre jours de campagne étaient
représentatifs, ED09 tirerait ~112 fois et ED10 ~98 sur le lot. Un écart
net vers le bas dirait que la fenêtre de quatre jours était un accident.*

**Ce tableau ne dit RIEN de la qualité de ces déclencheurs.** La fréquence
est une condition nécessaire de testabilité, jamais un signe de valeur : un
déclencheur fréquent à espérance négative ruine plus vite qu'un rare.
Lecture PAR SETUP, jamais en groupe — additionner les treize produirait
des gagnants par combinatoire (règle du pré-enregistrement).

## ES — 56 jours évalués (20260626 → 20260911)

| déclencheur | N | par jour | jours pour N=40 | jours actifs | mois le + chargé | jour le + chargé |
|---|---|---|---|---|---|---|
| `ED03_SELL_VPOC_FAR_ABOVE` | 60 | 1.07 | 37 | 48 % | 48 % | 10 % |
| `ED11_SELL_IB_BREAK_DOWN` | 41 | 0.73 | 55 | 38 % | 51 % | 12 % |
| `ED12_BUY_IB_BREAK_UP` | 37 | 0.66 | 61 | 32 % | 59 % | 14 % |
| `ED04_BUY_VPOC_RECLAIM` | 31 | 0.55 | 72 | 43 % | 52 % | 10 % |
| `ED10_BUY_CVD_DIVERGENCE` | 29 | 0.52 | 77 | 34 % | 41 % | 17 % |
| `ED08_BUY_VWAP_RECLAIM_TREND` | 22 | 0.39 | 102 | 32 % | 50 % | 9 % |
| `ED07_SELL_MQ_CALL_WALL` | 20 | 0.36 | 112 | 9 % | 70 % | 30 % |
| `ED05_SELL_GEX_REJECTION` | 19 | 0.34 | 118 | 32 % | 42 % | 11 % |
| `ED06_BUY_GEX_SUPPORT` | 19 | 0.34 | 118 | 29 % | 42 % | 11 % |
| `ED01_SELL_OPEN_ABOVE_PREV_VA` | 18 | 0.32 | 124 | 30 % | 39 % | 11 % |
| `ED09_SELL_CVD_DIVERGENCE` | 14 | 0.25 | 160 | 18 % | 50 % | 29 % |
| `ED02_BUY_PREV_VA_RECLAIM` | 13 | 0.23 | 172 | 14 % | 54 % | 23 % |
| `ED14_SELL_EXTREME_HIGH_RANGE` | 6 | 0.11 | 373 | 9 % | 50 % | 33 % |
| `ED16_BUY_VWAP_SD2_SUPPORT` | 6 | 0.11 | 373 | 11 % | 67 % | 17 % |
| `ED15_SELL_VWAP_SD2_REJECTION` | 5 | 0.09 | 448 | 7 % | 80 % | 40 % |
| `ED13_BUY_EXTREME_LOW_RANGE` | 3 | 0.05 | 747 | 5 % | 33 % | 33 % |

### Répartition horaire

| déclencheur | 09h30-11h00 | 11h00-13h00 | 13h00-15h00 | 15h00-16h00 |
|---|---|---|---|---|
| `ED03_SELL_VPOC_FAR_ABOVE` | 21 | 32 | 1 | 6 |
| `ED11_SELL_IB_BREAK_DOWN` | 2 | 13 | 18 | 8 |
| `ED12_BUY_IB_BREAK_UP` | 3 | 11 | 16 | 7 |
| `ED04_BUY_VPOC_RECLAIM` | 3 | 6 | 19 | 3 |
| `ED10_BUY_CVD_DIVERGENCE` | 12 | 7 | 4 | 6 |
| `ED08_BUY_VWAP_RECLAIM_TREND` | 1 | 9 | 12 | 0 |
| `ED07_SELL_MQ_CALL_WALL` | 2 | 2 | 8 | 8 |
| `ED05_SELL_GEX_REJECTION` | 4 | 7 | 6 | 2 |
| `ED06_BUY_GEX_SUPPORT` | 3 | 10 | 5 | 1 |
| `ED01_SELL_OPEN_ABOVE_PREV_VA` | 17 | 1 | 0 | 0 |
| `ED09_SELL_CVD_DIVERGENCE` | 4 | 5 | 4 | 1 |
| `ED02_BUY_PREV_VA_RECLAIM` | 5 | 6 | 1 | 1 |
| `ED14_SELL_EXTREME_HIGH_RANGE` | 1 | 2 | 1 | 2 |
| `ED16_BUY_VWAP_SD2_SUPPORT` | 0 | 2 | 3 | 1 |
| `ED15_SELL_VWAP_SD2_REJECTION` | 0 | 2 | 2 | 1 |
| `ED13_BUY_EXTREME_LOW_RANGE` | 0 | 0 | 3 | 0 |

## NQ — 56 jours évalués (20260626 → 20260911)

| déclencheur | N | par jour | jours pour N=40 | jours actifs | mois le + chargé | jour le + chargé |
|---|---|---|---|---|---|---|
| `ED11_SELL_IB_BREAK_DOWN` | 39 | 0.70 | 57 | 30 % | 54 % | 13 % |
| `ED08_BUY_VWAP_RECLAIM_TREND` | 38 | 0.68 | 59 | 55 % | 45 % | 8 % |
| `ED03_SELL_VPOC_FAR_ABOVE` | 36 | 0.64 | 62 | 36 % | 44 % | 11 % |
| `ED04_BUY_VPOC_RECLAIM` | 33 | 0.59 | 68 | 43 % | 48 % | 9 % |
| `ED12_BUY_IB_BREAK_UP` | 33 | 0.59 | 68 | 27 % | 52 % | 18 % |
| `ED07_SELL_MQ_CALL_WALL` | 23 | 0.41 | 97 | 9 % | 48 % | 30 % |
| `ED09_SELL_CVD_DIVERGENCE` | 23 | 0.41 | 97 | 18 % | 43 % | 17 % |
| `ED01_SELL_OPEN_ABOVE_PREV_VA` | 17 | 0.30 | 132 | 29 % | 53 % | 12 % |
| `ED02_BUY_PREV_VA_RECLAIM` | 17 | 0.30 | 132 | 20 % | 65 % | 18 % |
| `ED05_SELL_GEX_REJECTION` | 16 | 0.29 | 140 | 27 % | 50 % | 12 % |
| `ED06_BUY_GEX_SUPPORT` | 13 | 0.23 | 172 | 18 % | 54 % | 15 % |
| `ED10_BUY_CVD_DIVERGENCE` | 13 | 0.23 | 172 | 20 % | 38 % | 15 % |
| `ED15_SELL_VWAP_SD2_REJECTION` | 5 | 0.09 | 448 | 9 % | 60 % | 20 % |
| `ED13_BUY_EXTREME_LOW_RANGE` | 4 | 0.07 | 560 | 5 % | 100 % | 50 % |
| `ED14_SELL_EXTREME_HIGH_RANGE` | 4 | 0.07 | 560 | 7 % | 50 % | 25 % |
| `ED16_BUY_VWAP_SD2_SUPPORT` | 4 | 0.07 | 560 | 5 % | 100 % | 50 % |

### Répartition horaire

| déclencheur | 09h30-11h00 | 11h00-13h00 | 13h00-15h00 | 15h00-16h00 |
|---|---|---|---|---|
| `ED11_SELL_IB_BREAK_DOWN` | 1 | 8 | 22 | 8 |
| `ED08_BUY_VWAP_RECLAIM_TREND` | 2 | 10 | 25 | 1 |
| `ED03_SELL_VPOC_FAR_ABOVE` | 15 | 16 | 3 | 2 |
| `ED04_BUY_VPOC_RECLAIM` | 1 | 12 | 17 | 3 |
| `ED12_BUY_IB_BREAK_UP` | 2 | 11 | 13 | 7 |
| `ED07_SELL_MQ_CALL_WALL` | 2 | 6 | 9 | 6 |
| `ED09_SELL_CVD_DIVERGENCE` | 10 | 11 | 2 | 0 |
| `ED01_SELL_OPEN_ABOVE_PREV_VA` | 15 | 0 | 2 | 0 |
| `ED02_BUY_PREV_VA_RECLAIM` | 7 | 2 | 4 | 4 |
| `ED05_SELL_GEX_REJECTION` | 0 | 9 | 4 | 3 |
| `ED06_BUY_GEX_SUPPORT` | 4 | 5 | 3 | 1 |
| `ED10_BUY_CVD_DIVERGENCE` | 4 | 5 | 2 | 2 |
| `ED15_SELL_VWAP_SD2_REJECTION` | 0 | 3 | 1 | 1 |
| `ED13_BUY_EXTREME_LOW_RANGE` | 1 | 3 | 0 | 0 |
| `ED14_SELL_EXTREME_HIGH_RANGE` | 0 | 2 | 1 | 1 |
| `ED16_BUY_VWAP_SD2_SUPPORT` | 0 | 0 | 4 | 0 |

## Ce que la passe permet de dire

- **ES** (56 jours) : 2 déclencheur(s) atteindraient N=40 dans les 57 jours restants au rythme mesuré — `ED03_SELL_VPOC_FAR_ABOVE`, `ED11_SELL_IB_BREAK_DOWN`
- **ES** : déclencheur(s) dont plus d'un tiers des tirs tombent dans UN mois (artefact probable, cf 28/04) — `ED03_SELL_VPOC_FAR_ABOVE`, `ED11_SELL_IB_BREAK_DOWN`, `ED12_BUY_IB_BREAK_UP`, `ED04_BUY_VPOC_RECLAIM`, `ED10_BUY_CVD_DIVERGENCE`, `ED08_BUY_VWAP_RECLAIM_TREND`, `ED07_SELL_MQ_CALL_WALL`, `ED05_SELL_GEX_REJECTION`, `ED06_BUY_GEX_SUPPORT`, `ED01_SELL_OPEN_ABOVE_PREV_VA`, `ED09_SELL_CVD_DIVERGENCE`, `ED02_BUY_PREV_VA_RECLAIM`, `ED14_SELL_EXTREME_HIGH_RANGE`, `ED16_BUY_VWAP_SD2_SUPPORT`, `ED15_SELL_VWAP_SD2_REJECTION`, `ED13_BUY_EXTREME_LOW_RANGE`
- **NQ** (56 jours) : 0 déclencheur(s) atteindraient N=40 dans les 57 jours restants au rythme mesuré — aucun
- **NQ** : déclencheur(s) dont plus d'un tiers des tirs tombent dans UN mois (artefact probable, cf 28/04) — `ED11_SELL_IB_BREAK_DOWN`, `ED08_BUY_VWAP_RECLAIM_TREND`, `ED03_SELL_VPOC_FAR_ABOVE`, `ED04_BUY_VPOC_RECLAIM`, `ED12_BUY_IB_BREAK_UP`, `ED07_SELL_MQ_CALL_WALL`, `ED09_SELL_CVD_DIVERGENCE`, `ED01_SELL_OPEN_ABOVE_PREV_VA`, `ED02_BUY_PREV_VA_RECLAIM`, `ED05_SELL_GEX_REJECTION`, `ED06_BUY_GEX_SUPPORT`, `ED10_BUY_CVD_DIVERGENCE`, `ED15_SELL_VWAP_SD2_REJECTION`, `ED13_BUY_EXTREME_LOW_RANGE`, `ED14_SELL_EXTREME_HIGH_RANGE`, `ED16_BUY_VWAP_SD2_SUPPORT`

*Aucun devenir n'a été lu ni écrit : ce module ne touche pas
`LOGS/`, ne calcule aucune barrière et n'ouvre aucun journal.*