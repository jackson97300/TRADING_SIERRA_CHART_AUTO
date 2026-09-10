# `range_r` sur le lot — l'IB comme premier range (prérequis 2 du module SCÉNARIOS)

*Définition écrite avant la mesure : docstring de `recalc.range_r` (deux fiches F23 face à face,
tenue causale, acceptation = deux clôtures strictement au-delà, regain = deux clôtures dedans).
Bords = max/min des quatre premières barres 15 min ; `w_min`/`w_max` = None (pas de borne :
la distribution est ci-dessous, la borne est à fixer dans `seuils.yaml`). Aucun devenir de trade.*

## ES — 57 journees, machine de 10h30 a 15h45 (1243 barres)

| mesure | valeur |
|---|---|
| largeur IB en ATR-15m : p10 / p25 / p50 / p75 / p90 | 1.72 / 2.19 / 2.91 / 4.06 / 5.03 |
| part des barres FORMATION / ETABLI / CASSE / RETEST | 55 % / 0 % / 38 % / 7 % |
| journees ETABLI un jour | 0 (0 %) |
| barre mediane d'ETABLI (index 15 min depuis 9h30) | — |
| journees ou l'IB est CASSEE (deux clotures) | 43 (75 %) ; jamais cassee : 14 |
| barre mediane de la premiere CASSE | 7.0 |
| premiere cassure ECHOUEE (REGAIN avant toute autre cassure) | 23 / 43 (53 %) |
| premiere cassure RETESTEE / retest TENU (CONTINUATION) | 20 / 8 |
| compression a la barre AVANT la premiere CASSE : mediane (N) | 1.183 (40) |
| compression, barres des journees SANS cassure : mediane (N) | 1.049 (166) |
| n_tests haut / bas en fin de journee : mediane | 1.0 / 1.0 |

<details><summary>par jour</summary>

| jour | largeur ATR | metre | ETABLI a | 1re CASSE a | echouee | retest | cont. | n_tests h/b | etats |
|---|---|---|---|---|---|---|---|---|---|
| 20260612 | — | aucun | — | 11h00 | oui | oui | — | 1/0 | F F C C R F F F F F C C C C C C C C C C C C |
| 20260615 | 0.94 | veille | — | 11h00 | non | oui | oui | 2/0 | F F C C C C C C C C C C C C C C C C C R R R |
| 20260616 | 2.94 | veille | — | 11h30 | oui | — | — | 0/1 | F F F F C C C F F F C C C C C C C C C C C C |
| 20260617 | 2.16 | veille | — | 11h00 | oui | — | — | 1/3 | F F C C F F F F F F F C C C C C R R R R R R |
| 20260618 | 3.01 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260622 | 2.78 | veille | — | 10h45 | non | oui | oui | 0/1 | F C C C R R R R R R R R R R R R R R R R R R |
| 20260623 | 4.94 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260625 | 6.72 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F |
| 20260626 | 5.13 | veille | — | 11h30 | oui | — | — | 1/1 | F F F F C C C F F F C C C F F F F F F F F F |
| 20260629 | 4.25 | veille | — | 13h15 | non | oui | — | 2/0 | F F F F F F F F F F F C C C C C C C C C C R |
| 20260701 | 3.12 | veille | — | 11h15 | oui | oui | oui | 3/0 | F F F C C C C C C R R R R R R R R R R R F F |
| 20260702 | 4.24 | veille | — | 11h15 | non | — | — | 0/1 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260706 | 1.32 | veille | — | 11h00 | non | oui | oui | 2/0 | F F C C C C C C C C C C R R R R R R R R R R |
| 20260707 | 6.08 | veille | — | — | — | — | — | 0/2 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260708 | 2.23 | veille | — | 10h45 | oui | oui | — | 1/2 | F C C C C C R R F F F F C C C C C C C C C C |
| 20260709 | 2.39 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260710 | 1.56 | veille | — | 12h45 | non | — | — | 2/1 | F F F F F F F F F C C C C C C C C C C C C C |
| 20260713 | 2.87 | veille | — | 13h00 | non | oui | oui | 0/2 | F F F F F F F F F F C C C C C C R R R R R R |
| 20260714 | 2.35 | veille | — | 11h15 | oui | — | — | 1/0 | F F F C C F F F F F C C C C C C C C C C C C |
| 20260715 | 1.68 | veille | — | 12h00 | oui | oui | — | 0/3 | F F F F F F C C C C C R R F F F F F F F F F |
| 20260716 | 2.93 | veille | — | 14h45 | non | oui | — | 1/2 | F F F F F F F F F F F F F F F F F C C C C R |
| 20260717 | 5.49 | veille | — | — | — | — | — | 1/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260720 | 3.13 | veille | — | 13h15 | oui | — | — | 0/2 | F F F F F F F F F F F C C C F F F C C C C C |
| 20260721 | 2.05 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260722 | 3.46 | veille | — | 12h00 | oui | — | — | 1/1 | F F F F F F C C C C C F F F F F F F F F F F |
| 20260723 | 4.94 | veille | — | 11h00 | oui | oui | — | 0/3 | F F C C C R R F F F F F F C C C C C C C C R |
| 20260724 | 1.72 | veille | — | 11h00 | oui | — | — | 1/3 | F F C C C C C C C C C C C C C C F F F F F F |
| 20260727 | 4.53 | veille | — | 11h45 | oui | — | — | 0/2 | F F F F F C C C F F C C C R R R R R F F F F |
| 20260728 | 1.94 | veille | — | 11h30 | non | — | — | 1/0 | F F F F C C C C C C C C C C C C C C C C C C |
| 20260729 | 4.34 | veille | — | 11h45 | oui | oui | oui | 1/3 | F F F F F C C R R R F F F F F F F C C F F C |
| 20260730 | 2.35 | veille | — | 13h15 | non | — | — | 1/1 | F F F F F F F F F F F C C C C C C C C C C C |
| 20260731 | 5.68 | veille | — | 15h30 | non | oui | — | 2/0 | F F F F F F F F F F F F F F F F F F F F C R |
| 20260804 | 2.77 | veille | — | 10h45 | non | — | — | 1/0 | F C C C C C C C C C C C C C C C C C C C C C |
| 20260805 | 2.33 | veille | — | 10h45 | non | — | — | 0/1 | F C C C C C C C C C C C C C C C C |
| 20260806 | 2.61 | veille | — | 11h45 | oui | oui | — | 0/2 | F F F F F C C C C C C C C C R F F C C C C C |
| 20260807 | 3.06 | veille | — | — | — | — | — | 2/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260811 | 1.57 | veille | — | 11h30 | non | — | — | 0/1 | F F F F C C C C C C C C C C C C C C C C C C |
| 20260812 | 4.05 | veille | — | — | — | — | — | 0/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260813 | 6.47 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260814 | 1.95 | veille | — | 11h00 | non | — | — | 0/0 | F F C C C C C C C C C C C C C C C C C C C C |
| 20260817 | 2.81 | veille | — | 12h45 | non | — | — | 0/2 | F F F F F F F F F C C C C C C C C C C C C C |
| 20260818 | 3.05 | veille | — | — | — | — | — | 0/3 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260819 | 3.35 | veille | — | 10h45 | oui | oui | — | 2/0 | F C C R R F F F F F F F F F F F F F F F F F |
| 20260820 | 2.21 | veille | — | 13h30 | non | — | — | 1/2 | F F F F F F F F F F F F C C C C C C C C C C |
| 20260821 | 1.74 | veille | — | 11h45 | oui | oui | oui | 3/0 | F F F F F C R R R R R R F F F F F F F F F F |
| 20260824 | 3.23 | veille | — | — | — | — | — | 2/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260825 | 2.28 | veille | — | — | — | — | — | 0/2 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260826 | 2.90 | veille | — | — | — | — | — | 1/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260827 | 3.40 | veille | — | 11h00 | oui | oui | — | 2/0 | F F C C C C C C C C C C C C R R F F F F C C |
| 20260828 | 3.93 | veille | — | 10h45 | oui | oui | — | 2/1 | F C C C R F F F C C C C C C C C C C C C C C |
| 20260831 | 1.73 | veille | — | — | — | — | — | 1/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260901 | 3.32 | veille | — | 11h45 | oui | — | — | 2/4 | F F F F F C C F F F F F F F F F F C C F F F |
| 20260902 | 4.09 | veille | — | 11h30 | oui | — | — | 3/0 | F F F F C C C C F F F F F F F F F F F F F F |
| 20260903 | 2.83 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260904 | 1.98 | veille | — | 10h45 | oui | oui | oui | 0/2 | F C C C C C R R R F F C C C C C C C C C C C |
| 20260908 | 4.60 | veille | — | — | — | — | — | 0/2 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260909 | 2.12 | veille | — | 11h15 | oui | oui | — | 0/3 | F F F C C C C C R R F F F F F F F F F F F F |

</details>

## NQ — 57 journees, machine de 10h30 a 15h45 (1243 barres)

| mesure | valeur |
|---|---|
| largeur IB en ATR-15m : p10 / p25 / p50 / p75 / p90 | 2.30 / 2.65 / 3.24 / 4.59 / 5.84 |
| part des barres FORMATION / ETABLI / CASSE / RETEST | 63 % / 0 % / 34 % / 4 % |
| journees ETABLI un jour | 1 (2 %) |
| barre mediane d'ETABLI (index 15 min depuis 9h30) | 9.0 |
| journees ou l'IB est CASSEE (deux clotures) | 41 (72 %) ; jamais cassee : 16 |
| barre mediane de la premiere CASSE | 8.0 |
| premiere cassure ECHOUEE (REGAIN avant toute autre cassure) | 22 / 41 (54 %) |
| premiere cassure RETESTEE / retest TENU (CONTINUATION) | 14 / 4 |
| compression a la barre AVANT la premiere CASSE : mediane (N) | 1.083 (38) |
| compression, barres des journees SANS cassure : mediane (N) | 1.068 (217) |
| n_tests haut / bas en fin de journee : mediane | 1.0 / 1.0 |

<details><summary>par jour</summary>

| jour | largeur ATR | metre | ETABLI a | 1re CASSE a | echouee | retest | cont. | n_tests h/b | etats |
|---|---|---|---|---|---|---|---|---|---|
| 20260612 | — | aucun | — | 11h00 | oui | oui | — | 2/0 | F F C C R F F F F F C C C C C C C R R R R R |
| 20260615 | 1.33 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260616 | 3.89 | veille | — | 11h00 | non | — | — | 0/1 | F F C C C C C C C C C C C C C C C C C C C C |
| 20260617 | 2.31 | veille | — | 14h15 | non | — | — | 1/2 | F F F F F F F F F F F F F F F C C C C C C C |
| 20260618 | 2.36 | veille | — | 12h15 | non | oui | oui | 2/0 | F F F F F F F C C C C C C C C C C C R R R R |
| 20260622 | 2.57 | veille | — | 10h45 | non | — | — | 0/0 | F C C C C C C C C C C C C C C C C C C C C C |
| 20260623 | 4.63 | veille | — | — | — | — | — | 0/2 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260625 | 9.26 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F |
| 20260626 | 5.00 | veille | — | — | — | — | — | 1/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260629 | 4.58 | veille | — | 12h15 | non | — | — | 1/0 | F F F F F F F C C C C C C C C C C C C C C C |
| 20260701 | 2.23 | veille | — | — | — | — | — | 1/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260702 | 5.34 | veille | — | 10h45 | non | — | — | 0/1 | F C C C C C C C C C C C C C C C C C C C C C |
| 20260706 | 1.84 | veille | — | 11h30 | oui | — | — | 2/0 | F F F F C C C C F F F F F F F F F F F F F F |
| 20260707 | 6.38 | veille | — | — | — | — | — | 0/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260708 | 2.40 | veille | — | 11h15 | oui | oui | — | 1/2 | F F F C C C R F F F F F F F F F F C C C C C |
| 20260709 | 2.93 | veille | — | 13h15 | non | oui | — | 2/0 | F F F F F F F F F F F C C C C C C R R R R R |
| 20260710 | 2.50 | veille | 11h45 | 12h15 | non | — | — | 2/2 | F F F F F E E C C C C C C C C C C C C C C C |
| 20260713 | 2.78 | veille | — | 15h15 | non | oui | — | 1/2 | F F F F F F F F F F F F F F F F F F F C C R |
| 20260714 | 2.82 | veille | — | 11h15 | oui | — | — | 2/0 | F F F C C C F F F F C C C C C C R R R R F F |
| 20260715 | 3.59 | veille | — | 10h45 | oui | oui | oui | 0/3 | F C C C C C C C C C C R R R F F F F F F F F |
| 20260716 | 2.80 | veille | — | 13h45 | non | oui | — | 0/2 | F F F F F F F F F F F F F C C C C C C C C R |
| 20260717 | 5.19 | veille | — | 12h00 | oui | oui | — | 3/0 | F F F F F F C C C C C C C R R F F F F F F F |
| 20260720 | 2.66 | veille | — | 14h45 | non | — | — | 0/2 | F F F F F F F F F F F F F F F F F C C C C C |
| 20260721 | 1.94 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260722 | 3.24 | veille | — | 11h15 | oui | — | — | 1/0 | F F F C C C C C C C C C C C F F F F F F F F |
| 20260723 | 4.41 | veille | — | 10h45 | oui | oui | — | 0/3 | F C C C C C R R F F C C C C C C C C C C C R |
| 20260724 | 3.32 | veille | — | 15h15 | non | — | — | 1/2 | F F F F F F F F F F F F F F F F F F F C C C |
| 20260727 | 5.27 | veille | — | 11h30 | oui | — | — | 0/1 | F F F F C C C F F F C C C C F F F F F F F F |
| 20260728 | 3.25 | veille | — | 11h45 | oui | — | — | 2/0 | F F F F F C C C C C C C C F F F F F F F F F |
| 20260729 | 4.48 | veille | — | 11h45 | oui | — | — | 1/2 | F F F F F C C C C C F F F F F F F F F F F C |
| 20260730 | 3.15 | veille | — | 15h15 | oui | — | — | 2/0 | F F F F F F F F F F F F F F F F F F F C C F |
| 20260731 | 6.53 | veille | — | — | — | — | — | 0/1 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260804 | 3.09 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260805 | 3.21 | veille | — | 10h45 | non | — | — | 0/1 | F C C C C C C C C C C C C C C C C |
| 20260806 | 7.90 | veille | — | — | — | — | — | 1/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260807 | 3.00 | veille | — | — | — | — | — | 2/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260811 | 2.62 | veille | — | 13h00 | oui | oui | — | 0/2 | F F F F F F F F F F C C C C C C C C C R R F |
| 20260812 | 3.09 | veille | — | 11h45 | oui | — | — | 0/2 | F F F F F C C F F F F F F F F F F F F F F F |
| 20260813 | 7.20 | veille | — | — | — | — | — | 3/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260814 | 3.20 | veille | — | 11h00 | non | oui | — | 0/2 | F F C C C C C C C C C C C C C C C C C C C R |
| 20260817 | 2.44 | veille | — | 13h15 | non | — | — | 1/1 | F F F F F F F F F F F C C C C C C C C C C C |
| 20260818 | 4.60 | veille | — | 11h00 | oui | — | — | 0/3 | F F C C F F F F F F F F F F F F F F F F F F |
| 20260819 | 6.12 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260820 | 2.57 | veille | — | 13h30 | oui | oui | oui | 1/3 | F F F F F F F F F F F F C C C C C C R R R F |
| 20260821 | 3.66 | veille | — | — | — | — | — | 1/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260824 | 5.55 | veille | — | — | — | — | — | 1/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260825 | 3.60 | veille | — | — | — | — | — | 0/2 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260826 | 3.41 | veille | — | 15h15 | oui | — | — | 1/1 | F F F F F F F F F F F F F F F F F F F C C F |
| 20260827 | 3.75 | veille | — | 12h45 | oui | — | — | 3/0 | F F F F F F F F F C C C C C F F F F F F F C |
| 20260828 | 3.64 | veille | — | 10h45 | oui | oui | — | 2/1 | F C C C R F F F C C C C C C C C C C C C C C |
| 20260831 | 1.79 | veille | — | — | — | — | — | 1/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260901 | 2.83 | veille | — | 10h45 | oui | oui | oui | 2/1 | F C R R R R R R F F F F F F F F F F F F F F |
| 20260902 | 2.99 | veille | — | — | — | — | — | 2/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260903 | 3.49 | veille | — | 11h15 | non | — | — | 1/0 | F F F C C C C C C C C C C C C C C C C C C C |
| 20260904 | 2.29 | veille | — | 10h45 | oui | — | — | 0/2 | F C C C C C C C C F F C C C C C C C C C R R |
| 20260908 | 5.47 | veille | — | — | — | — | — | 0/0 | F F F F F F F F F F F F F F F F F F F F F F |
| 20260909 | 3.46 | veille | — | 11h15 | oui | — | — | 0/1 | F F F C C F F C C F F F F F F F F F F F F F |

</details>

