# Phase 1 — taux de base des zones

Genere par `CORE/research/phase1_base_rate_zones.py`.

Une zone n'est retenue que si son ecart au taux de base survit a la correction de Benjamini-Hochberg (environ 70 hypotheses testees), que son intervalle de Wilson exclut le taux de base, et que l'ecart garde le meme signe sur les deux moities temporelles.

## ES — 2651 tests de zones sur 41 jours de seance (64.7 tests/jour)

Taux de base : **32.7 %** tiennent.

| zone | sens | n | tient | IC 95 % | 1re moitie | 2e moitie | solide |
|---|---|---|---|---|---|---|---|
| MQ_hvl | SUPPORT | 34 | 52.9 % | 36.7-68.5 % | 45.5 % | 56.5 % |  |
| VPOC_veille | SUPPORT | 40 | 15.0 % | 7.1-29.1 % | 8.3 % | 25.0 % |  |
| OVN_high | SUPPORT | 33 | 21.2 % | 10.7-37.8 % | 23.1 % | 14.3 % |  |
| IB_low | SUPPORT | 109 | 43.1 % | 34.2-52.5 % | 41.3 % | 45.7 % |  |
| VAH_veille | SUPPORT | 36 | 22.2 % | 11.7-38.1 % | 22.7 % | 21.4 % |  |
| VPOC_veille | RESISTANCE | 48 | 41.7 % | 28.8-55.7 % | 41.2 % | 42.9 % |  |
| OVN_high | RESISTANCE | 51 | 25.5 % | 15.5-38.9 % | 21.6 % | 35.7 % |  |
| VAL_jour | SUPPORT | 202 | 39.1 % | 32.6-46.0 % | 39.1 % | 39.1 % |  |
| VAH_jour | SUPPORT | 89 | 27.0 % | 18.8-37.0 % | 23.4 % | 31.0 % |  |
| VAL_jour | RESISTANCE | 73 | 27.4 % | 18.5-38.6 % | 21.7 % | 37.0 % |  |
| VPOC_jour | SUPPORT | 164 | 28.0 % | 21.7-35.4 % | 26.7 % | 30.2 % |  |
| IB_high | SUPPORT | 35 | 28.6 % | 16.3-45.1 % | 37.5 % | 21.1 % |  |
| VWAP_SD1d | RESISTANCE | 108 | 28.7 % | 21.0-37.9 % | 23.2 % | 34.6 % |  |
| VWAP_SD1u | SUPPORT | 107 | 29.0 % | 21.2-38.2 % | 28.3 % | 29.8 % |  |
| OVN_low | SUPPORT | 69 | 29.0 % | 19.6-40.6 % | 24.2 % | 33.3 % |  |
| IB_low | RESISTANCE | 36 | 36.1 % | 22.5-52.4 % | 29.6 % | 55.6 % |  |
| VWAP_jour | SUPPORT | 145 | 35.9 % | 28.5-43.9 % | 38.3 % | 31.4 % |  |
| IB_high | RESISTANCE | 104 | 29.8 % | 21.9-39.2 % | 30.6 % | 28.6 % |  |
| VAL_veille | SUPPORT | 46 | 30.4 % | 19.1-44.8 % | 35.3 % | 16.7 % |  |
| VAL_veille | RESISTANCE | 45 | 31.1 % | 19.5-45.7 % | 20.7 % | 50.0 % |  |
| VWAP_SD1d | SUPPORT | 184 | 31.5 % | 25.2-38.6 % | 30.8 % | 32.5 % |  |
| VWAP_SD1u | RESISTANCE | 175 | 33.7 % | 27.1-41.0 % | 33.3 % | 34.3 % |  |
| VAH_jour | RESISTANCE | 190 | 33.7 % | 27.3-40.7 % | 33.9 % | 33.3 % |  |
| VWAP_jour | RESISTANCE | 132 | 33.3 % | 25.9-41.7 % | 26.8 % | 44.0 % |  |
| VPOC_jour | RESISTANCE | 186 | 32.3 % | 26.0-39.3 % | 28.8 % | 36.6 % |  |
| VAH_veille | RESISTANCE | 43 | 32.6 % | 20.5-47.5 % | 30.8 % | 35.3 % |  |

## NQ — 2226 tests de zones sur 41 jours de seance (54.3 tests/jour)

Taux de base : **27.4 %** tiennent.

| zone | sens | n | tient | IC 95 % | 1re moitie | 2e moitie | solide |
|---|---|---|---|---|---|---|---|
| OVN_low | SUPPORT | 43 | 14.0 % | 6.6-27.3 % | 9.7 % | 25.0 % |  |
| VAH_jour | RESISTANCE | 158 | 39.2 % | 32.0-47.0 % | 37.0 % | 42.4 % | **OUI** |
| VWAP_SD1u | SUPPORT | 90 | 17.8 % | 11.2-26.9 % | 14.6 % | 21.4 % |  |
| IB_low | RESISTANCE | 32 | 18.8 % | 8.9-35.3 % | 14.3 % | 27.3 % |  |
| VAL_jour | SUPPORT | 170 | 18.8 % | 13.7-25.4 % | 19.0 % | 18.6 % |  |
| VAL_jour | RESISTANCE | 73 | 35.6 % | 25.6-47.1 % | 29.3 % | 43.8 % |  |
| IB_high | RESISTANCE | 78 | 19.2 % | 12.0-29.3 % | 15.7 % | 25.9 % |  |
| VWAP_SD1u | RESISTANCE | 155 | 34.8 % | 27.8-42.6 % | 37.5 % | 30.5 % |  |
| VWAP_SD1d | SUPPORT | 157 | 21.0 % | 15.4-28.0 % | 19.0 % | 24.6 % |  |
| VAH_veille | RESISTANCE | 36 | 33.3 % | 20.2-49.7 % | 42.9 % | 27.3 % |  |
| IB_low | SUPPORT | 81 | 30.9 % | 21.9-41.6 % | 29.4 % | 33.3 % |  |
| VWAP_SD1d | RESISTANCE | 105 | 30.5 % | 22.5-39.8 % | 26.2 % | 36.4 % |  |
| VWAP_jour | SUPPORT | 144 | 25.0 % | 18.6-32.7 % | 24.4 % | 25.9 % |  |
| VPOC_jour | SUPPORT | 150 | 26.0 % | 19.6-33.6 % | 25.0 % | 27.4 % |  |
| VPOC_jour | RESISTANCE | 168 | 26.2 % | 20.1-33.3 % | 30.0 % | 20.6 % |  |
| VWAP_jour | RESISTANCE | 143 | 28.0 % | 21.3-35.8 % | 31.7 % | 23.0 % |  |
| VAH_jour | SUPPORT | 65 | 27.7 % | 18.3-39.6 % | 28.2 % | 26.9 % |  |
