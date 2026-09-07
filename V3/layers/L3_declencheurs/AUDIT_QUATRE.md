# AUDIT DES QUATRE DECLENCHEURS GELES — L3, cycle 2

*Fable, depose le 07/09/2026 (l'original portait « 09/09 », la meme derive
de date que les fichiers renommes). Sur `layers/L3_declencheurs/SPEC.md` a
`e7e6319` et `test_spec_l3.py`. La campagne est en cours : rien ici ne
propose de changer le code. Tout ce qui est « a faire » va dans
`LECTURE_JOUR_61.md` ou `NEXT_CYCLE.md` — et y est, depuis ce depot.*

## Le resume en une ligne

**Quatre declencheurs bien ecrits, un seul vivant, tous suspendus a une
colonne dont personne ne connait la formule.** Ce n'est pas un echec de L3,
c'est le point exact ou le cycle 2 commence.

## H3-VPOC — le seul vivant

Un vrai lieu de desk (l'extreme de la valeur), une vraie reaction, le bon
regime, les bonnes unites. Mais : (1) son lieu est un NIVEAU QUI BOUGE
(`cur_vah` — la raison meme de la quarantaine F23 des `cur_*`) ; la cible
VPOC, elle, est FIGEE a l'entree — verifie dans le code, ecrit dans
DECISIONS le 07/09. (2) `finish < 0,4` : seuil herite, distribution mesuree
le 07/09 (rapports/finish_lieu_h3) — filtre MOU (garde ~la moitie du lieu),
gradue sur les deux instruments au site de decision, formule toujours
inconnue. (3) LA PUISSANCE : N ~ 30/instrument pour +0,02 ATR — **H3 ne peut
pas passer seule au jour 61, par arithmetique** (LECTURE_JOUR_61 regle 1).
(4) ES et NQ comptent pour 1,3 test (regle 2).

## H2p — annonce mort, correctement

Son regime garde 141/143 : une decoration, pas une condition (regle 5 de la
lecture). Et H2p est un cas particulier de H-EXT : au jour 61 ce n'est pas
un resultat independant — H2p/H3/H-EXT se lisent comme UN phenomene, la
reversion vers la valeur (regle 4).

## H6p — le bon setup avec la mauvaise definition

« Cassure acceptee » = `ib_broken_up == 1`, un flag C++ dont personne ne
sait s'il veut dire une meche, une cloture ou deux. F23 a defini
l'acceptation ; H6p ne la lit pas (NEXT_CYCLE §2). Son regime « IB etroite »
est peut-etre INVERSE par rapport au lieu — les retests d'IB arrivent les
jours d'IB large (lecture avec/sans, regle 6).

## H8p — lance pour que ce soit ecrit

Trois conditions au p90 en 15 minutes ~ 0,1 % des barres : l'absorption est
un evenement d'UNE minute, H8p la mesure au mauvais grain — structurel, pas
un seuil. Sa vraie place est dans L4 (`absorption_sens`, NEXT_CYCLE §3).

## Le constat commun

Les quatre lisent `finish_delta_pct` — formule C++ inconnue. Si la colonne
est cassee, la couche l'est. Limitation etendue aux quatre dans la SPEC,
distribution du seuil dans rapports/, `finish_r` recalcule = premiere ligne
de NEXT_CYCLE.

## Ce qui manquait, et qui est repare depuis ce depot

- S-1 (momentum de fin de journee, JFE) et S-4 (regle des 80 %) n'etaient
  nulle part : la decision par defaut est rendue EXPLICITE (NEXT_CYCLE §4).
- Les seize en ombre n'etaient ni listes au miroir NI CABLES — aucun coureur
  ne les executait. Repare le 07/09 : `ombre16.py` + `OMBRE.md` + parite
  dans `test_spec_l3.py`.
- La question la plus importante de la campagne : chaque declencheur, au
  jour 61, se lit AVEC et SANS B5 (LECTURE_JOUR_61 regle 7). C'est
  probablement la que la premiere vraie information sortira — pas des seuils.
