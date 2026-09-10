# La grammaire v0 sur le lot — les trois mesures de la spec §4.4 (module SCÉNARIOS)

**RÉSERVE w0 (Fable, c6c12dd) : le lot est en fenêtre w0 — la VA de 9h30 y est un profil ANTÉRIEUR, pas
J−1 (INCIDENT_LOG 04/09, CONVENTIONS §9). La position d'ouverture du lot n'est donc pas celle de la
campagne, et toutes les couvertures ci-dessous sont mesurées sur ce profil antérieur. Les vrais nombres
commencent le 10/09 au soir (23h01, rythme 5b/5), en w1.**

*Attendu pré-enregistré par la relectrice (Fable, 10/09) : couverture 60 % (45-80), validés à 10h30
encore vrais à 16h00 : 55 % (≥ 40), contrôle négatif battu d'au moins 15 points. Grammaire :
`scenarios/grammaire.py` ; zones : `zones.py` ; seuils : `seuils.yaml` v2026-09-10b. Rejeu
rétrospectif sur les 57 journées (le direct rend la même chose barre à barre : `test_grammaire` [8]).
Aucun devenir de trade, aucune direction attendue.*

## ES — 57 journées

| mesure | attendu (relectrice) | mesuré | verdict |
|---|---|---|---|
| 1. COUVERTURE = canoniques VALIDÉS à la clôture (Fable, c6c12dd) | 60 % (45-80) | **61 %** | ATTENDU |
| 1 bis. journées avec une hypothèse ouverte (scénario final en cours, validé ou non) | — | 93 % | description, pas une couverture |
| 2. validés à 10h30 encore vrais à 16h00 — SE LIT AU JOUR 20 DE w1 | 55 % (≥ 40) | **71 %** (N validés à 10h30 = 7) | N trop petit, pas de verdict |
| 2 bis. en cours à 10h30 encore en cours à 16h00 (large) | — | 69 % (N = 54) | description |
| 3. contrôle négatif, couverture : tirage moyen / p95 | grammaire − p95 ≥ 15 pts | 19 / 26 % → écart **+67** | BAT LE TIRAGE |
| 3. contrôle négatif, tenue : tirage moyen / p95 | idem | 8 / 29 % → écart +43 | |

Scénarios finaux :

| scénario final | journées | validé | bascules moy. | 1re validation (médiane) |
|---|---|---|---|---|
| S_OUV_HAUT_TEND | 16 | 11 | 0.4 | 11h15 |
| S_OUV_BAS_TEND | 14 | 8 | 0.3 | 11h00 |
| S_DANS_CASSURE_BAS | 6 | 2 | 1.7 | 14h00 |
| S_AUTRE | 4 | 0 | 1.0 | 11h00 |
| S_OUV_HAUT_REINT [TRAV] | 4 | 4 | 1.5 | 10h30 |
| S_DANS_POSE | 4 | 4 | 0.0 | 15h45 |
| S_DANS_CASSURE_HAUT | 3 | 0 | 1.0 | — |
| S_OUV_BAS_REINT | 2 | 2 | 3.0 | 10h00 |
| S_DANS_HEADFAKE | 2 | 2 | 2.0 | 12h15 |
| S_OUV_BAS_REINT [PULL] | 1 | 1 | 1.0 | 10h15 |
| S_OUV_HAUT_REINT | 1 | 1 | 5.0 | 11h00 |

S_AUTRE par raison : IB_hors_norme 2, pas_de_VA 1, rejet_vpoc 1
Position d'ouverture : au_dessus 22, dans 17, sous 17, None 1
Type d'ouverture : TEST_DRIVE 25, ENCHERE 19, REJET_RENVERSEMENT 12, None 1
Bascules par journée : moyenne 0.86, max 5

<details><summary>par jour</summary>

| jour | ouvre | type | à 10h30 (validé) | final [précision] (validé) | bascules | 1re validation |
|---|---|---|---|---|---|---|
| 20260612 | None | None | S_AUTRE (non) | S_AUTRE (non) | 0 | — |
| 20260615 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h00 |
| 20260616 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 3 | 12h15 |
| 20260617 | sous | REJET_RENVERSEMENT | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 11h00 |
| 20260618 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260622 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (oui) | 1 | 11h45 |
| 20260623 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260625 | au_dessus | TEST_DRIVE | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_REINT [TRAV] (oui) | 1 | 10h15 |
| 20260626 | sous | ENCHERE | S_OUV_BAS_REINT (oui) | S_OUV_BAS_REINT [PULL] (oui) | 1 | 10h15 |
| 20260629 | au_dessus | ENCHERE | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_TEND (oui) | 2 | 10h15 |
| 20260701 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260702 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 1 | — |
| 20260706 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h00 |
| 20260707 | dans | TEST_DRIVE | S_AUTRE (non) | S_AUTRE (non) | 1 | — |
| 20260708 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 10h45 |
| 20260709 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260710 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 12h45 |
| 20260713 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (oui) | 1 | 14h45 |
| 20260714 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_REINT (oui) | 5 | 09h45 |
| 20260715 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 2 | 12h15 |
| 20260716 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 1 | — |
| 20260717 | sous | REJET_RENVERSEMENT | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260720 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 3 | 14h00 |
| 20260721 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_HAUT (non) | 1 | — |
| 20260722 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 12h00 |
| 20260723 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 11h00 |
| 20260724 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 2 | 11h00 |
| 20260727 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_AUTRE (non) | 2 | 11h00 |
| 20260728 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_HAUT (non) | 1 | — |
| 20260729 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_TEND (non) | 2 | 09h45 |
| 20260730 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_HAUT (non) | 1 | — |
| 20260731 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 15h30 |
| 20260804 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 10h45 |
| 20260805 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260806 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 11h45 |
| 20260807 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_POSE (oui) | 0 | 15h45 |
| 20260811 | dans | TEST_DRIVE | S_AUTRE (non) | S_AUTRE (non) | 1 | — |
| 20260812 | au_dessus | TEST_DRIVE | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_REINT [TRAV] (oui) | 1 | 10h30 |
| 20260813 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260814 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_REINT [TRAV] (oui) | 1 | 11h00 |
| 20260817 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 12h45 |
| 20260818 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260819 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 11h45 |
| 20260820 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 2 | 10h45 |
| 20260821 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 12h15 |
| 20260824 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_POSE (oui) | 0 | 15h45 |
| 20260825 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260826 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_POSE (oui) | 0 | 15h45 |
| 20260827 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h00 |
| 20260828 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_REINT [TRAV] (oui) | 3 | 10h15 |
| 20260831 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260901 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 14h45 |
| 20260902 | sous | ENCHERE | S_OUV_BAS_REINT (oui) | S_OUV_BAS_REINT (oui) | 1 | 10h00 |
| 20260903 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260904 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_REINT (oui) | 5 | 11h00 |
| 20260908 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_POSE (oui) | 0 | 15h45 |
| 20260909 | sous | REJET_RENVERSEMENT | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 11h15 |

</details>

## NQ — 57 journées

| mesure | attendu (relectrice) | mesuré | verdict |
|---|---|---|---|
| 1. COUVERTURE = canoniques VALIDÉS à la clôture (Fable, c6c12dd) | 60 % (45-80) | **56 %** | ATTENDU |
| 1 bis. journées avec une hypothèse ouverte (scénario final en cours, validé ou non) | — | 93 % | description, pas une couverture |
| 2. validés à 10h30 encore vrais à 16h00 — SE LIT AU JOUR 20 DE w1 | 55 % (≥ 40) | **71 %** (N validés à 10h30 = 7) | N trop petit, pas de verdict |
| 2 bis. en cours à 10h30 encore en cours à 16h00 (large) | — | 66 % (N = 53) | description |
| 3. contrôle négatif, couverture : tirage moyen / p95 | grammaire − p95 ≥ 15 pts | 20 / 28 % → écart **+65** | BAT LE TIRAGE |
| 3. contrôle négatif, tenue : tirage moyen / p95 | idem | 9 / 29 % → écart +43 | |

Scénarios finaux :

| scénario final | journées | validé | bascules moy. | 1re validation (médiane) |
|---|---|---|---|---|
| S_OUV_HAUT_TEND | 15 | 9 | 0.3 | 11h15 |
| S_OUV_BAS_TEND | 15 | 8 | 0.3 | 13h30 |
| S_DANS_CASSURE_BAS | 6 | 0 | 1.7 | 13h00 |
| S_DANS_HEADFAKE | 6 | 6 | 2.3 | 15h45 |
| S_AUTRE | 4 | 0 | 0.8 | — |
| S_OUV_HAUT_REINT [PULL] | 2 | 2 | 1.0 | 11h45 |
| S_DANS_POSE | 2 | 2 | 0.0 | 15h45 |
| S_DANS_CASSURE_HAUT | 2 | 0 | 1.0 | — |
| S_OUV_BAS_REINT | 2 | 2 | 4.0 | 10h30 |
| S_OUV_HAUT_REINT [TRAV] | 2 | 2 | 1.0 | 10h30 |
| S_OUV_HAUT_REINT | 1 | 1 | 5.0 | 10h15 |

S_AUTRE par raison : IB_hors_norme 3, pas_de_VA 1
Position d'ouverture : au_dessus 20, dans 19, sous 17, None 1
Type d'ouverture : TEST_DRIVE 32, ENCHERE 13, REJET_RENVERSEMENT 11, None 1
Bascules par journée : moyenne 0.95, max 5

<details><summary>par jour</summary>

| jour | ouvre | type | à 10h30 (validé) | final [précision] (validé) | bascules | 1re validation |
|---|---|---|---|---|---|---|
| 20260612 | None | None | S_AUTRE (non) | S_AUTRE (non) | 0 | — |
| 20260615 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260616 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 1 | — |
| 20260617 | sous | REJET_RENVERSEMENT | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 14h15 |
| 20260618 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 2 | 09h45 |
| 20260622 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260623 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260625 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_REINT [PULL] (oui) | 1 | 11h45 |
| 20260626 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_POSE (oui) | 0 | 15h45 |
| 20260629 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_CASSURE_HAUT (non) | 1 | — |
| 20260701 | dans | REJET_RENVERSEMENT | S_AUTRE (non) | S_AUTRE (non) | 1 | — |
| 20260702 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 2 | 09h45 |
| 20260706 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h30 |
| 20260707 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260708 | sous | TEST_DRIVE | S_OUV_BAS_REINT (oui) | S_OUV_BAS_REINT (oui) | 3 | 09h45 |
| 20260709 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 13h15 |
| 20260710 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_HAUT (non) | 1 | — |
| 20260713 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 15h15 |
| 20260714 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_TEND (oui) | 2 | 10h15 |
| 20260715 | au_dessus | TEST_DRIVE | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_REINT [TRAV] (oui) | 1 | 09h45 |
| 20260716 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 13h45 |
| 20260717 | sous | REJET_RENVERSEMENT | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260720 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 1 | — |
| 20260721 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260722 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 14h00 |
| 20260723 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 10h45 |
| 20260724 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 1 | — |
| 20260727 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 4 | 12h15 |
| 20260728 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 13h45 |
| 20260729 | dans | REJET_RENVERSEMENT | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 3 | 13h00 |
| 20260730 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 15h45 |
| 20260731 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260804 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260805 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260806 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260807 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260811 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 15h45 |
| 20260812 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260813 | dans | TEST_DRIVE | S_AUTRE (non) | S_AUTRE (non) | 1 | — |
| 20260814 | au_dessus | REJET_RENVERSEMENT | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_REINT [TRAV] (oui) | 1 | 10h30 |
| 20260817 | dans | ENCHERE | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 1 | — |
| 20260818 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 11h00 |
| 20260819 | dans | TEST_DRIVE | S_AUTRE (non) | S_AUTRE (non) | 1 | — |
| 20260820 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (oui) | 0 | 13h30 |
| 20260821 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_POSE (oui) | 0 | 15h45 |
| 20260824 | sous | TEST_DRIVE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260825 | au_dessus | ENCHERE | S_OUV_HAUT_REINT (oui) | S_OUV_HAUT_REINT (oui) | 5 | 10h15 |
| 20260826 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_HEADFAKE (oui) | 2 | 15h45 |
| 20260827 | au_dessus | ENCHERE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 12h45 |
| 20260828 | dans | TEST_DRIVE | S_DANS_POSE (non) | S_DANS_CASSURE_BAS (non) | 3 | 11h45 |
| 20260831 | sous | ENCHERE | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260901 | sous | REJET_RENVERSEMENT | S_OUV_BAS_TEND (non) | S_OUV_BAS_TEND (non) | 0 | — |
| 20260902 | sous | ENCHERE | S_OUV_BAS_REINT (oui) | S_OUV_BAS_REINT (oui) | 5 | 10h30 |
| 20260903 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (oui) | 0 | 11h15 |
| 20260904 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_TEND (non) | 0 | — |
| 20260908 | au_dessus | TEST_DRIVE | S_OUV_HAUT_TEND (non) | S_OUV_HAUT_REINT [PULL] (oui) | 1 | 11h00 |
| 20260909 | sous | ENCHERE | S_OUV_BAS_REINT (oui) | S_OUV_BAS_TEND (oui) | 2 | 10h00 |

</details>

