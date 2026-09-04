# Phase 2 — balayage des facons de trader les zones

Genere par `CORE/research/phase2_balayage_strategies.py`.

Esperance en **ticks nets de couts**, barrieres symetriques (TP = SL), sortie forcee a 30 barres. Un candidat n'est retenu que si son esperance est significativement differente de zero apres correction de Benjamini-Hochberg ET positive sur les deux moities temporelles.

## ES — 2714 touches de zones sur 41 jours (66.2/jour), barriere +/-10 ticks, cout 2.0 ticks

- **Toutes zones FADE** : n=2714, esperance -1.76 ticks, reussite 51.1 %, PF 0.70
- **Toutes zones BREAK** : n=2714, esperance -2.62 ticks, reussite 46.8 %, PF 0.59

| zone | sens | dir | n | esperance | reussite | PF | esp. train | esp. test | retenu |
|---|---|---|---|---|---|---|---|---|---|
| VWAP_jour | RESISTANCE | FADE | 140 | +0.06 | 60.0 % | 1.01 | -1.12 | +2.12 |  |
| VAL_veille | RESISTANCE | BREAK | 46 | -0.70 | 56.5 % | 0.87 | +1.33 | -4.50 |  |
| VAL_jour | SUPPORT | FADE | 208 | -0.86 | 55.3 % | 0.84 | -0.25 | -1.66 |  |
| VWAP_jour | SUPPORT | FADE | 151 | -0.87 | 55.6 % | 0.84 | -0.54 | -1.45 |  |
| VPOC_jour | SUPPORT | BREAK | 169 | -1.17 | 53.8 % | 0.79 | -0.72 | -1.85 |  |
| VWAP_SD1u | SUPPORT | FADE | 112 | -1.18 | 53.6 % | 0.78 | -0.89 | -1.55 |  |
| VPOC_jour | RESISTANCE | FADE | 192 | -1.26 | 53.6 % | 0.77 | -1.74 | -0.66 |  |
| VAH_veille | RESISTANCE | FADE | 43 | -1.30 | 53.5 % | 0.77 | -1.23 | -1.41 |  |
| VWAP_SD1u | RESISTANCE | FADE | 180 | -1.33 | 53.3 % | 0.76 | -1.37 | -1.28 |  |
| VPOC_veille | SUPPORT | BREAK | 42 | -1.52 | 52.4 % | 0.73 | -1.17 | -2.00 |  |
| IB_high | RESISTANCE | BREAK | 104 | -1.81 | 51.0 % | 0.69 | -1.21 | -2.73 |  |
| VWAP_SD1d | SUPPORT | FADE | 193 | -1.81 | 50.8 % | 0.69 | -1.39 | -2.36 |  |
| VAH_jour | SUPPORT | FADE | 91 | -1.89 | 50.5 % | 0.68 | -3.25 | -0.37 |  |
| VAH_jour | RESISTANCE | FADE | 195 | -1.95 | 50.3 % | 0.67 | -2.08 | -1.73 |  |
| IB_low | SUPPORT | FADE | 109 | -2.09 | 49.5 % | 0.65 | -2.00 | -2.22 |  |
| VWAP_SD1d | RESISTANCE | FADE | 109 | -2.09 | 49.5 % | 0.65 | -2.71 | -1.43 |  |
| VAL_jour | RESISTANCE | FADE | 73 | -2.14 | 49.3 % | 0.65 | -3.74 | +0.59 |  |
| OVN_low | SUPPORT | BREAK | 69 | -2.14 | 49.3 % | 0.65 | -0.82 | -3.43 |  |

## NQ — 2234 touches de zones sur 41 jours (54.5/jour), barriere +/-40 ticks, cout 3.0 ticks

- **Toutes zones FADE** : n=2234, esperance -5.54 ticks, reussite 46.8 %, PF 0.76
- **Toutes zones BREAK** : n=2234, esperance -6.37 ticks, reussite 45.8 %, PF 0.73

| zone | sens | dir | n | esperance | reussite | PF | esp. train | esp. test | retenu |
|---|---|---|---|---|---|---|---|---|---|
| VAL_jour | RESISTANCE | FADE | 74 | +5.65 | 60.8 % | 1.34 | +4.62 | +7.00 |  |
| VAH_jour | RESISTANCE | FADE | 160 | +4.50 | 59.4 % | 1.26 | +0.87 | +9.54 |  |
| IB_high | RESISTANCE | BREAK | 78 | +4.18 | 59.0 % | 1.24 | +2.49 | +7.37 |  |
| VWAP_SD1u | RESISTANCE | FADE | 156 | +4.18 | 59.0 % | 1.24 | +5.66 | +1.75 |  |
| VAL_jour | SUPPORT | BREAK | 170 | +4.06 | 58.8 % | 1.23 | -0.23 | +10.33 |  |
| VWAP_SD1d | SUPPORT | BREAK | 157 | +1.84 | 56.1 % | 1.10 | +2.60 | +0.51 |  |
| VWAP_SD1d | RESISTANCE | FADE | 106 | +0.02 | 53.8 % | 1.00 | -1.71 | +2.45 |  |
| VAH_jour | SUPPORT | BREAK | 65 | -1.15 | 52.3 % | 0.94 | -1.97 | +0.08 |  |
| VPOC_jour | RESISTANCE | BREAK | 169 | -2.29 | 50.9 % | 0.89 | -4.60 | +1.06 |  |
| VPOC_jour | SUPPORT | BREAK | 150 | -3.53 | 49.3 % | 0.84 | -4.82 | -1.71 |  |
| VWAP_SD1u | SUPPORT | FADE | 91 | -4.32 | 48.4 % | 0.81 | -4.67 | -3.93 |  |
| VWAP_jour | RESISTANCE | BREAK | 143 | -4.40 | 48.3 % | 0.80 | -9.83 | +2.90 |  |
| VWAP_jour | SUPPORT | FADE | 144 | -4.67 | 47.9 % | 0.79 | -3.93 | -5.76 |  |
| VWAP_jour | RESISTANCE | FADE | 143 | -4.96 | 47.6 % | 0.78 | -0.07 | -11.52 |  |
| VPOC_jour | RESISTANCE | FADE | 169 | -6.08 | 46.2 % | 0.74 | -3.00 | -10.54 |  |
| VWAP_jour | SUPPORT | BREAK | 144 | -6.33 | 45.8 % | 0.73 | -7.65 | -4.38 |  |
| VWAP_SD1u | SUPPORT | BREAK | 91 | -6.96 | 45.1 % | 0.71 | -9.67 | -3.93 |  |
| VAH_jour | SUPPORT | FADE | 65 | -8.54 | 43.1 % | 0.65 | -8.13 | -9.15 |  |
