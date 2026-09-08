# Le spike de fin de session — l'observation de Jackson, mesurée (08/09)

*Origine : « je remarque un setup vers 20h45-20h50 [Paris = 14h45-14h50 ET],
souvent le prix spike ». Mesure PAR MINUTE sur le lot (60 j ES / 59 j NQ),
range et volume seulement — AUCUN devenir, aucun P&L. Référence = médiane
des ranges 1 min de 14h00-15h00 ET.*

## Verdict : le spike existe, mais il est à 15h00 ET PILE (21h00 Paris)

| minute ET | ES range p50 | vs réf | NQ range p50 | vs réf |
|---|---|---|---|---|
| 14h45 (le souvenir) | 8,0 t | ×1,14 | 50,5 t | ×1,10 |
| 14h50 | 8,0 t | ×1,14 | 49,5 t | ×1,08 |
| **15h00 (la réalité)** | **13,0 t** | **×1,86** | **75,5 t** | **×1,64** |
| volume 15h00 | 2 674 | ×~2 | 822 | ×~1,6 |

**C'est la clôture des futures obligataires (Treasuries, 15h00 ET)** : la
minute est un événement de volatilité SYSTÉMATIQUE sur les deux
instruments. La fenêtre ressentie 14h45-14h50 n'est qu'une élévation
légère (×1,1) — la mémoire a avancé l'horloge de dix minutes, le
phénomène est réel.

## Et le plus gros est encore après : 15h50-15h59 ET

La minute la plus souvent dans le top-3 des ranges de l'après-midi :
**15h59 sur 45/60 jours ES (75 %) et 35/59 NQ** ; 15h50 (publication des
déséquilibres MOC) : 22 et 25 jours. La dernière décade de la séance
concentre l'essentiel des extrêmes — cohérent avec toute la littérature
de clôture.

## Ce qu'on en fait (méthode)

Un spike de volatilité n'est PAS un edge directionnel : il manque
l'hypothèse de SENS (fade du spike ? continuation ? règles de spike de
Dalton pour l'open du lendemain ?). Candidat pré-enregistré
`NEXT_CYCLE` § C2_BOND_CLOSE — brief Fable requis avant toute ombre,
attendu écrit avant. Rien ne se câble sur une impression datée du jour
même. Le journal MANUEL de Jackson capture ses clics dans cette fenêtre
dès aujourd'hui — c'est la voie propre pour son instinct.
