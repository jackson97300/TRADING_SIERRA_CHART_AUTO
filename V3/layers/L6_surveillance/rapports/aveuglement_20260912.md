# L'audit du mètre — l'aveuglement par cause nommée (L6)

*Attendu écrit avant la passe : une douzaine de jours par instrument à
zéro barre cash (dimanches, un fichier sans ligne `stable`, une collecte
tronquée) ; vrai trou d'ATR quasi nul ; `atr_source = veille` ≈ un quart
des barres ; VIX à zéro sur quelques pourcents dont un jour entier ;
quarantaine effective ZÉRO ; aucun jour mixte. Aucun devenir lu.*

## ES

- fichiers listés : **81** — rendant ≥ 2 barres cash : **66** — avec assez de chauffe pour `atr_ref` : **56**
- dénominateur 1 (colonnes brutes) : **1627 barres**
- dénominateur 2 (colonnes recalculées) : **1394 barres**
- configuration Sierra : `w0` 61 jour(s), `w1` 5 jour(s)

### Journées entièrement aveugles — 15

| jour | cause | détail |
|---|---|---|
| 20260610 | `aucune_ligne_stable` | 840 lignes, 0 stables, fin 23:58 UTC |
| 20260614 | `dimanche_globex_seul` | 240 lignes, 2 stables, fin 23:59 UTC |
| 20260621 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260624 | `collecte_arretee_avant_cash` | 683 lignes, 683 stables, fin 11:22 UTC |
| 20260628 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260705 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260712 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260719 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260726 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260802 | `aucune_ligne_stable` | 120 lignes, 0 stables, fin 23:59 UTC |
| 20260809 | `dimanche_globex_seul` | 230 lignes, 119 stables, fin 23:59 UTC |
| 20260816 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260823 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260830 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260906 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |

### Séances amputées — 9

| jour | première barre (min ET) | dernière |
|---|---|---|
| 20260611 | 705 ⚠ attendu 570 | 945 |
| 20260619 | 570 | 765 ⚠ attendu 945 |
| 20260625 | 570 | 855 ⚠ attendu 945 |
| 20260630 | 570 | 840 ⚠ attendu 945 |
| 20260703 | 570 | 765 ⚠ attendu 945 |
| 20260803 | 825 ⚠ attendu 570 | 945 |
| 20260805 | 570 | 870 ⚠ attendu 945 |
| 20260810 | 705 ⚠ attendu 570 | 945 |
| 20260907 | 570 | 765 ⚠ attendu 945 |

### Barres — causes lisibles sans recalcul

| cause | barres | part | lecture |
|---|---|---|---|
| `barre_incomplete` | 30 | 1.84 % | aveuglement |
| `colonne_absente:gamma_absent` | 121 | 7.44 % | colonne ABSENTE de la trame ce jour-là |
| `gamma_absent` | 24 | 1.48 % | aveuglement |
| `hvl_absent` | 3 | 0.18 % | aveuglement |
| `vix_absent_ou_nul` | 21 | 1.29 % | aveuglement |
| `volumetrie_nulle` | 0 | 0.00 % | aveuglement |

### Barres — causes qui exigent la chauffe

| cause | barres | part | lecture |
|---|---|---|---|
| `atr_barre_chauffe` | 336 | 24.10 % | dépendance déclarée, PAS un aveuglement |
| `atr_de_la_veille` | 336 | 24.10 % | dépendance déclarée, PAS un aveuglement |
| `atr_aucune_source` | 0 | 0.00 % | aveuglement |
| `atr_ref_absent` | 0 | 0.00 % | aveuglement |
| `rvol_r_absent` | 27 | 1.94 % | aveuglement |

## NQ

- fichiers listés : **79** — rendant ≥ 2 barres cash : **66** — avec assez de chauffe pour `atr_ref` : **56**
- dénominateur 1 (colonnes brutes) : **1626 barres**
- dénominateur 2 (colonnes recalculées) : **1394 barres**
- configuration Sierra : `w0` 61 jour(s), `w1` 5 jour(s)

### Journées entièrement aveugles — 13

| jour | cause | détail |
|---|---|---|
| 20260610 | `aucune_ligne_stable` | 3413 lignes, 0 stables, fin 23:58 UTC |
| 20260621 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260624 | `collecte_arretee_avant_cash` | 683 lignes, 683 stables, fin 11:22 UTC |
| 20260628 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260705 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260712 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260719 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260726 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260809 | `dimanche_globex_seul` | 123 lignes, 119 stables, fin 23:59 UTC |
| 20260816 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260823 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260830 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |
| 20260906 | `dimanche_globex_seul` | 120 lignes, 119 stables, fin 23:59 UTC |

### Séances amputées — 9

| jour | première barre (min ET) | dernière |
|---|---|---|
| 20260611 | 705 ⚠ attendu 570 | 945 |
| 20260619 | 570 | 750 ⚠ attendu 945 |
| 20260625 | 570 | 855 ⚠ attendu 945 |
| 20260630 | 570 | 840 ⚠ attendu 945 |
| 20260703 | 570 | 765 ⚠ attendu 945 |
| 20260803 | 825 ⚠ attendu 570 | 945 |
| 20260805 | 570 | 870 ⚠ attendu 945 |
| 20260810 | 705 ⚠ attendu 570 | 945 |
| 20260907 | 570 | 765 ⚠ attendu 945 |

### Barres — causes lisibles sans recalcul

| cause | barres | part | lecture |
|---|---|---|---|
| `barre_incomplete` | 29 | 1.78 % | aveuglement |
| `colonne_absente:gamma_absent` | 121 | 7.44 % | colonne ABSENTE de la trame ce jour-là |
| `gamma_absent` | 24 | 1.48 % | aveuglement |
| `hvl_absent` | 55 | 3.38 % | aveuglement |
| `vix_absent_ou_nul` | 20 | 1.23 % | aveuglement |
| `volumetrie_nulle` | 0 | 0.00 % | aveuglement |

### Barres — causes qui exigent la chauffe

| cause | barres | part | lecture |
|---|---|---|---|
| `atr_barre_chauffe` | 336 | 24.10 % | dépendance déclarée, PAS un aveuglement |
| `atr_de_la_veille` | 336 | 24.10 % | dépendance déclarée, PAS un aveuglement |
| `atr_aucune_source` | 0 | 0.00 % | aveuglement |
| `atr_ref_absent` | 0 | 0.00 % | aveuglement |
| `rvol_r_absent` | 28 | 2.01 % | aveuglement |

## Ce que la passe a tenu

- quarantaine effective sur une colonne `REQUISES` : **AUCUNE — le mécanisme est armé mais ne gouverne aucune colonne que la chaîne lit (`mq_gamma_condition` n'est dans aucune `REQUISES`)**

- **ES** : journées vides sans cause instruite : **aucune** ; jours mélangeant deux configurations Sierra : **aucun** ; vrai trou d'ATR (`atr_source = aucun`) : **0** barre(s) ; VIX absent ou nul : **21** barre(s) ; colonnes absentes rencontrées : gamma_absent
- **NQ** : journées vides sans cause instruite : **aucune** ; jours mélangeant deux configurations Sierra : **aucun** ; vrai trou d'ATR (`atr_source = aucun`) : **0** barre(s) ; VIX absent ou nul : **20** barre(s) ; colonnes absentes rencontrées : gamma_absent

*Aucun champ de devenir n'a été lu ni écrit : ce module ne touche
ni l'entonnoir, ni les barrières, ni les réactions.*