# Les réactions par nature de niveau — largeur des zones (prérequis 3 et 3 bis du module SCÉNARIOS)

*Définitions écrites avant la mesure : en-tête de `mesure_reactions.py`. Fiches F23 (`z_touche` 0,
`z_reset` 0,5 ATR — L1), niveaux figés seulement, `atr_ref` comme mètre. `depassement` = la mèche
au-delà du niveau sur la barre du test ; `reagit` = tenue causale à la barre suivante ; `casse` =
issue F23 finale. Un niveau qui a bougé entre deux barres est exclu (`ZONE_DEPLACEE`, pas une réaction).
Les valeurs de `seuils.yaml` restent null : la largeur par nature est à FIXER sur ces distributions
(Fable, réponse 4 : `dehors` = p80 des dépassements sur les tests tenus), pas lue dedans. Aucun
devenir de trade.*

## ES — 57 journées

Dépassement = mèche au-delà du niveau sur la barre du test ; **tenus** = tests dont la barre
suivante clôture du côté d'origine (la population de `dehors`, Fable réponse 4). Pour
comparaison, `dedans` = P10 `seuil_ticks` = 0,10 × atr_ref / tick (plancher 2 t).

| nature | tests | bougé (exclus) | réagit | cassé (F23) | dép. TENUS ticks p50 / p80 / p90 | dép. TENUS ATR p50 / p80 / p90 | dép. TOUS ATR p50 / p80 / p90 | réaction ATR méd. (tenus) |
|---|---|---|---|---|---|---|---|---|
| VA_veille (fige a 9h30) — w0 : profil anterieur, pas J-1 | 144 | 0 | 56 % | 42 % | 0.0 / 27.8 / 51.4 | 0.000 / 0.504 / 1.067 | 0.071 / 0.686 / 1.094 | 1.239 |
| VWAP_jour (non fige, pas une zone) | 31 | 112 | 71 % | 39 % | 3.5 / 29.4 / 47.8 | 0.071 / 0.617 / 0.930 | 0.129 / 0.680 / 0.945 | 1.019 |
| IB (fige a 10h30) | 84 | 0 | 54 % | 36 % | 0.0 / 7.8 / 13.6 | 0.000 / 0.197 / 0.350 | 0.000 / 0.305 / 0.472 | 0.883 |
| PDH_PDL (fige a 9h30) | 58 | 0 | 64 % | 40 % | 0.0 / 19.4 / 32.2 | 0.000 / 0.247 / 0.853 | 0.000 / 0.484 / 0.871 | 0.908 |
| OVN (fige a 9h30) | 125 | 0 | 62 % | 35 % | 0.0 / 20.8 / 40.0 | 0.000 / 0.459 / 0.745 | 0.000 / 0.587 / 0.890 | 1.017 |
| MUR_call_put (tel que livre) | 26 | 0 | 54 % | 50 % | 0.0 / 16.2 / 34.7 | 0.000 / 0.276 / 1.127 | 0.063 / 0.446 / 1.370 | 1.060 |
| GEX_nearest (non fige, pas une zone) | 149 | 151 | 93 % | 0 % | 0.0 / 20.4 / 33.6 | 0.000 / 0.349 / 0.808 | 0.000 / 0.349 / 0.756 | 0.679 |
| VA_veille_w1 (fige a 9h30) | 0 | 0 | — | — | — / — / — | — / — / — | — / — / — | — |

Sauts du niveau (> 1 tick entre deux barres 15 min) par heure ET — `ZONE_DEPLACEE` :

| nature | 9h | 10h | 11h | 12h | 13h | 14h | 15h | total |
|---|---|---|---|---|---|---|---|---|
| VA_veille | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| VWAP_jour | 51 | 191 | 173 | 171 | 197 | 177 | 155 | 1115 |
| IB | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PDH_PDL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| OVN | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUR_call_put | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| GEX_nearest | 43 | 127 | 104 | 55 | 52 | 68 | 72 | 521 |
| VA_veille_w1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## NQ — 57 journées

Dépassement = mèche au-delà du niveau sur la barre du test ; **tenus** = tests dont la barre
suivante clôture du côté d'origine (la population de `dehors`, Fable réponse 4). Pour
comparaison, `dedans` = P10 `seuil_ticks` = 0,10 × atr_ref / tick (plancher 2 t).

| nature | tests | bougé (exclus) | réagit | cassé (F23) | dép. TENUS ticks p50 / p80 / p90 | dép. TENUS ATR p50 / p80 / p90 | dép. TOUS ATR p50 / p80 / p90 | réaction ATR méd. (tenus) |
|---|---|---|---|---|---|---|---|---|
| VA_veille (fige a 9h30) — w0 : profil anterieur, pas J-1 | 122 | 0 | 61 % | 34 % | 0.0 / 310.0 / 425.4 | 0.000 / 0.976 / 1.406 | 0.024 / 0.716 / 1.173 | 1.136 |
| VWAP_jour (non fige, pas une zone) | 24 | 105 | 62 % | 42 % | 215.2 / 387.2 / 467.2 | 0.820 / 1.110 / 1.489 | 0.631 / 1.075 / 1.321 | 1.136 |
| IB (fige a 10h30) | 85 | 0 | 51 % | 35 % | 0.0 / 32.6 / 75.8 | 0.000 / 0.096 / 0.177 | 0.000 / 0.270 / 0.444 | 0.874 |
| PDH_PDL (fige a 9h30) | 73 | 0 | 59 % | 42 % | 11.0 / 120.8 / 413.4 | 0.035 / 0.496 / 0.847 | 0.072 / 0.555 / 1.013 | 1.103 |
| OVN (fige a 9h30) | 102 | 0 | 59 % | 40 % | 0.0 / 94.4 / 323.4 | 0.000 / 0.233 / 1.170 | 0.016 / 0.754 / 1.264 | 1.057 |
| MUR_call_put (tel que livre) | 27 | 0 | 67 % | 30 % | 39.5 / 389.6 / 535.5 | 0.064 / 1.508 / 2.233 | 0.063 / 1.225 / 2.095 | 1.372 |
| GEX_nearest (non fige, pas une zone) | 143 | 152 | 92 % | 0 % | 0.0 / 167.4 / 405.9 | 0.000 / 0.409 / 1.155 | 0.000 / 0.332 / 1.119 | 0.949 |
| VA_veille_w1 (fige a 9h30) | 10 | 0 | 70 % | 40 % | 52.0 / 373.4 / 457.2 | 0.229 / 1.973 / 2.388 | 0.031 / 1.218 / 2.266 | 1.028 |

Sauts du niveau (> 1 tick entre deux barres 15 min) par heure ET — `ZONE_DEPLACEE` :

| nature | 9h | 10h | 11h | 12h | 13h | 14h | 15h | total |
|---|---|---|---|---|---|---|---|---|
| VA_veille | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| VWAP_jour | 57 | 221 | 216 | 219 | 223 | 213 | 211 | 1360 |
| IB | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PDH_PDL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| OVN | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUR_call_put | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GEX_nearest | 45 | 161 | 80 | 98 | 56 | 65 | 77 | 582 |
| VA_veille_w1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

