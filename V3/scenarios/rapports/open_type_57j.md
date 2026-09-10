# Distribution des types d'ouverture — `open_type_r` (prérequis 1 du module SCÉNARIOS)

*Définition écrite avant la mesure : docstring de `recalc.open_type_r`. Deux premières
barres 15 min cash, O = `open_cash_lvl`, bande = P10 sur `atr_veille`. Aucun devenir.*

## ES — 56 jours types ((atr_ref_absent) 1 non mesurables)
| type | jours | part | dont retour sur O |
|---|---|---|---|
| DRIVE | 1 | 2 % | 0 |
| TEST_DRIVE | 24 | 43 % | 0 |
| REJET_RENVERSEMENT | 12 | 21 % | 12 |
| ENCHERE | 19 | 34 % | 19 |

Croisement avec le `open_type` LIVRÉ (code C++, table inconnue ici) :
| recalculé \ livré | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| DRIVE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| TEST_DRIVE | 2 | 2 | 1 | 2 | 0 | 2 | 6 | 4 | 5 |
| REJET_RENVERSEMENT | 0 | 2 | 0 | 0 | 0 | 1 | 3 | 3 | 3 |
| ENCHERE | 0 | 1 | 0 | 1 | 2 | 0 | 3 | 7 | 5 |

<details><summary>par jour</summary>

| jour | type | dir | ext b1 (t) | ext b2 (t) | livré |
|---|---|---|---|---|---|
| 20260615 | ENCHERE | +1 | 4.0 | 23.0 | 8 |
| 20260616 | REJET_RENVERSEMENT | -1 | 8.0 | -23.0 | 2 |
| 20260617 | REJET_RENVERSEMENT | -1 | 23.0 | -45.0 | 9 |
| 20260618 | TEST_DRIVE | -1 | -153.0 | -130.0 | 9 |
| 20260622 | REJET_RENVERSEMENT | +1 | -32.0 | 39.0 | 7 |
| 20260623 | TEST_DRIVE | +1 | 91.0 | 183.0 | 9 |
| 20260625 | TEST_DRIVE | -1 | -194.0 | -376.0 | 6 |
| 20260626 | ENCHERE | +1 | 23.0 | 92.0 | 5 |
| 20260629 | ENCHERE | +1 | 120.0 | 20.0 | 8 |
| 20260701 | REJET_RENVERSEMENT | +1 | -51.0 | 34.0 | 8 |
| 20260702 | TEST_DRIVE | +1 | 78.0 | 119.0 | 7 |
| 20260706 | ENCHERE | -1 | -22.0 | -26.0 | 8 |
| 20260707 | TEST_DRIVE | -1 | -16.0 | -71.0 | 4 |
| 20260708 | ENCHERE | +1 | 47.0 | 35.0 | 9 |
| 20260709 | TEST_DRIVE | +1 | 79.0 | 92.0 | 8 |
| 20260710 | REJET_RENVERSEMENT | +1 | -10.0 | 19.0 | 8 |
| 20260713 | REJET_RENVERSEMENT | +1 | -6.0 | 20.0 | 7 |
| 20260714 | ENCHERE | +1 | 28.0 | 29.0 | 9 |
| 20260715 | ENCHERE | -1 | -11.0 | -7.0 | 8 |
| 20260716 | TEST_DRIVE | -1 | -74.0 | -50.0 | 7 |
| 20260717 | REJET_RENVERSEMENT | +1 | -50.0 | 102.0 | 9 |
| 20260720 | REJET_RENVERSEMENT | -1 | 37.0 | -82.0 | 7 |
| 20260721 | TEST_DRIVE | -1 | -50.0 | -16.0 | 7 |
| 20260722 | TEST_DRIVE | +1 | 28.0 | 77.0 | 8 |
| 20260723 | TEST_DRIVE | +1 | 113.0 | 20.0 | 9 |
| 20260724 | ENCHERE | -1 | 1.0 | -51.0 | 9 |
| 20260727 | TEST_DRIVE | -1 | -48.0 | -125.0 | 2 |
| 20260728 | TEST_DRIVE | -1 | -70.0 | -95.0 | 7 |
| 20260729 | REJET_RENVERSEMENT | -1 | 8.0 | -85.0 | 2 |
| 20260730 | TEST_DRIVE | +1 | 33.0 | 122.0 | 3 |
| 20260731 | TEST_DRIVE | -1 | -77.0 | -125.0 | 8 |
| 20260804 | TEST_DRIVE | +1 | 21.0 | 83.0 | 1 |
| 20260805 | ENCHERE | +1 | 11.0 | 20.0 | 8 |
| 20260806 | TEST_DRIVE | +1 | 14.0 | 30.0 | 9 |
| 20260807 | ENCHERE | +1 | 39.0 | 3.0 | 7 |
| 20260811 | TEST_DRIVE | -1 | -28.0 | -15.0 | 7 |
| 20260812 | TEST_DRIVE | -1 | -43.0 | -52.0 | 6 |
| 20260813 | TEST_DRIVE | +1 | 55.0 | 132.0 | 1 |
| 20260814 | ENCHERE | +1 | 15.0 | 15.0 | 2 |
| 20260817 | TEST_DRIVE | -1 | -43.0 | -55.0 | 9 |
| 20260818 | ENCHERE | -1 | 2.0 | -9.0 | 9 |
| 20260819 | ENCHERE | -1 | -11.0 | -15.0 | 7 |
| 20260820 | DRIVE | +1 | 57.0 | 24.0 | 9 |
| 20260821 | ENCHERE | -1 | -11.0 | -35.0 | 4 |
| 20260824 | ENCHERE | -1 | -62.0 | -12.0 | 7 |
| 20260825 | ENCHERE | -1 | -5.0 | -24.0 | 8 |
| 20260826 | TEST_DRIVE | +1 | 58.0 | 82.0 | 7 |
| 20260827 | REJET_RENVERSEMENT | -1 | 24.0 | -9.0 | 8 |
| 20260828 | REJET_RENVERSEMENT | -1 | 30.0 | -5.0 | 6 |
| 20260831 | TEST_DRIVE | -1 | -64.0 | -50.0 | 2 |
| 20260901 | ENCHERE | +1 | 23.0 | 25.0 | 9 |
| 20260902 | ENCHERE | +1 | 32.0 | 42.0 | 5 |
| 20260903 | TEST_DRIVE | +1 | 54.0 | 48.0 | 8 |
| 20260904 | ENCHERE | +0 | -3.0 | 3.0 | 8 |
| 20260908 | TEST_DRIVE | -1 | -81.0 | -75.0 | 4 |
| 20260909 | REJET_RENVERSEMENT | +1 | -7.0 | 10.0 | 9 |

</details>

## NQ — 56 jours types ((atr_ref_absent) 1 non mesurables)
| type | jours | part | dont retour sur O |
|---|---|---|---|
| DRIVE | 0 | 0 % | 0 |
| TEST_DRIVE | 32 | 57 % | 0 |
| REJET_RENVERSEMENT | 11 | 20 % | 11 |
| ENCHERE | 13 | 23 % | 13 |

Croisement avec le `open_type` LIVRÉ (code C++, table inconnue ici) :
| recalculé \ livré | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| DRIVE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| TEST_DRIVE | 3 | 2 | 1 | 4 | 1 | 2 | 3 | 7 | 9 |
| REJET_RENVERSEMENT | 0 | 0 | 1 | 1 | 0 | 3 | 2 | 1 | 3 |
| ENCHERE | 0 | 1 | 0 | 0 | 2 | 1 | 3 | 4 | 2 |

<details><summary>par jour</summary>

| jour | type | dir | ext b1 (t) | ext b2 (t) | livré |
|---|---|---|---|---|---|
| 20260615 | TEST_DRIVE | +1 | 148.0 | 147.0 | 8 |
| 20260616 | ENCHERE | +1 | 48.0 | -3.0 | 2 |
| 20260617 | REJET_RENVERSEMENT | -1 | 166.0 | -522.0 | 9 |
| 20260618 | TEST_DRIVE | -1 | -679.0 | -414.0 | 8 |
| 20260622 | REJET_RENVERSEMENT | +1 | -408.0 | 180.0 | 6 |
| 20260623 | TEST_DRIVE | +1 | 363.0 | 1070.0 | 9 |
| 20260625 | TEST_DRIVE | -1 | -1415.0 | -3224.0 | 6 |
| 20260626 | ENCHERE | +1 | 29.0 | 422.0 | 7 |
| 20260629 | ENCHERE | +1 | 654.0 | -22.0 | 7 |
| 20260701 | REJET_RENVERSEMENT | +1 | -398.0 | 172.0 | 7 |
| 20260702 | TEST_DRIVE | +1 | 180.0 | 714.0 | 9 |
| 20260706 | TEST_DRIVE | +1 | 264.0 | 308.0 | 8 |
| 20260707 | TEST_DRIVE | -1 | -165.0 | -669.0 | 9 |
| 20260708 | TEST_DRIVE | +1 | 381.0 | 460.0 | 5 |
| 20260709 | TEST_DRIVE | +1 | 652.0 | 856.0 | 8 |
| 20260710 | REJET_RENVERSEMENT | +1 | -79.0 | 189.0 | 3 |
| 20260713 | TEST_DRIVE | -1 | -472.0 | -336.0 | 9 |
| 20260714 | REJET_RENVERSEMENT | +1 | -59.0 | 49.0 | 6 |
| 20260715 | TEST_DRIVE | -1 | -481.0 | -520.0 | 2 |
| 20260716 | TEST_DRIVE | -1 | -748.0 | -629.0 | 9 |
| 20260717 | REJET_RENVERSEMENT | +1 | -897.0 | 127.0 | 9 |
| 20260720 | REJET_RENVERSEMENT | -1 | 476.0 | -258.0 | 7 |
| 20260721 | ENCHERE | -1 | -162.0 | -129.0 | 8 |
| 20260722 | TEST_DRIVE | +1 | 223.0 | 615.0 | 3 |
| 20260723 | TEST_DRIVE | +1 | 679.0 | 82.0 | 9 |
| 20260724 | TEST_DRIVE | -1 | -179.0 | -830.0 | 4 |
| 20260727 | TEST_DRIVE | -1 | -504.0 | -933.0 | 2 |
| 20260728 | TEST_DRIVE | -1 | -775.0 | -1113.0 | 4 |
| 20260729 | REJET_RENVERSEMENT | -1 | 182.0 | -549.0 | 4 |
| 20260730 | TEST_DRIVE | +1 | 468.0 | 1170.0 | 1 |
| 20260731 | TEST_DRIVE | -1 | -719.0 | -953.0 | 8 |
| 20260804 | TEST_DRIVE | +1 | 430.0 | 648.0 | 1 |
| 20260805 | ENCHERE | +1 | 348.0 | 335.0 | 8 |
| 20260806 | TEST_DRIVE | +1 | 521.0 | 799.0 | 9 |
| 20260807 | REJET_RENVERSEMENT | -1 | 234.0 | -211.0 | 8 |
| 20260811 | TEST_DRIVE | -1 | -223.0 | -185.0 | 7 |
| 20260812 | ENCHERE | -1 | -302.0 | -271.0 | 8 |
| 20260813 | TEST_DRIVE | +1 | 477.0 | 1132.0 | 1 |
| 20260814 | REJET_RENVERSEMENT | -1 | 50.0 | -81.0 | 6 |
| 20260817 | ENCHERE | -1 | -227.0 | -73.0 | 7 |
| 20260818 | TEST_DRIVE | -1 | -107.0 | -272.0 | 9 |
| 20260819 | TEST_DRIVE | -1 | -251.0 | -704.0 | 4 |
| 20260820 | ENCHERE | +1 | 381.0 | 27.0 | 9 |
| 20260821 | TEST_DRIVE | -1 | -414.0 | -490.0 | 4 |
| 20260824 | TEST_DRIVE | -1 | -613.0 | -441.0 | 9 |
| 20260825 | ENCHERE | +1 | 188.0 | 40.0 | 6 |
| 20260826 | TEST_DRIVE | +1 | 245.0 | 406.0 | 7 |
| 20260827 | ENCHERE | -1 | 14.0 | -354.0 | 8 |
| 20260828 | TEST_DRIVE | +1 | 309.0 | 74.0 | 7 |
| 20260831 | ENCHERE | -1 | -291.0 | -167.0 | 9 |
| 20260901 | REJET_RENVERSEMENT | +1 | -54.0 | 31.0 | 9 |
| 20260902 | ENCHERE | +1 | 99.0 | -16.0 | 5 |
| 20260903 | TEST_DRIVE | +1 | 248.0 | 200.0 | 8 |
| 20260904 | TEST_DRIVE | +1 | 202.0 | 500.0 | 8 |
| 20260908 | TEST_DRIVE | -1 | -749.0 | -634.0 | 6 |
| 20260909 | ENCHERE | +1 | 66.0 | 385.0 | 5 |

</details>

