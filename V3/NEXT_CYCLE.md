# NEXT_CYCLE — ce qui attend le cycle 2, et rien d'autre

*Créé le 07/09/2026 sur l'audit Fable des quatre déclencheurs. La règle vit
dans `campagne.yaml` : les idées nées pendant la campagne vont ICI, jamais
dans le code. Chaque entrée porte sa raison ; rien ne se code avant la
lecture du jour 61.*

## 1. `finish_r` recalculé — LA première ligne du cycle 2

Les quatre déclencheurs gelés lisent `finish_delta_pct` : formule C++
inconnue, binaire sur NQ, seuil 0,4/0,6 jamais posé sur une distribution ES.
Si la colonne est cassée, L3 entière l'est. Cycle 2 : `finish_r` recalculé
depuis OHLC dans `recalc.py` — `(close − low) / (high − low)` ou une
définition Wyckoff ÉCRITE — et le seuil posé sur SA distribution. Le bloc
`lire_l4` fait déjà exactement ça pour L4 (`range_pos` par barre).

## 2. H6 lit l'acceptation de F23, pas le flag C++

« Cassure acceptée » = `ib_broken_up == 1`, une colonne dont personne ne sait
si elle veut dire une mèche, une clôture ou deux. F23 a défini l'acceptation ;
H6 doit lire `issue = casse` de la fiche F23 de l'IB. Et son régime « IB
étroite < 0,4 » est peut-être INVERSÉ par rapport au lieu (les retests d'IB
arrivent les jours d'IB large) — à mesurer avec/sans au jour 61 avant tout.

## 3. H8 = un lieu 15 min + une absorption 1 MIN

L'absorption est un événement d'une minute : volume anormal, delta déséquilibré
et clôture qui ne suit pas coexistent sur 1 min et se diluent sur 15. Trois
conditions au p90 en 15 min ≈ 0,1 % des barres — le mauvais grain, structurel.
La bonne version existe déjà : `absorption_sens` de L4 (SPEC §2.4, 1 min,
info). Cycle 2 : H8 = lieu 15 min + absorption lue par L4.

## 4. S-1, le momentum de fin de journée — premier candidat du cycle 2

Le plan d'ombre du 06/09 portait S-1 (momentum de fin de journée, JFE 2021 —
la seule référence de niveau A du chantier) et S-4 (règle des 80 %). AUCUN des
deux n'est dans LES_QUATRE ni dans les seize ED : la décision « pas ce
cycle » avait été prise PAR DÉFAUT — elle est désormais EXPLICITE, ici.
S-1 entre au cycle 2 avec l'entrée à 15h30 ET, la sortie à 16h00, et
l'exception `SESSION_CLOTURE` déjà prévue dans L0. S-4 (= H4 du cycle 1,
16 franchissements sur 57 jours, `SOUS_DIMENSIONNEES`) reste en attente d'un
effectif — sa « seule voie est l'ombre » est écrite dans `hypotheses.py`
mais AUCUN coureur ne l'exécute : la câbler est une décision de Jackson,
pas un oubli à réparer en silence.

## 5. Figer les lieux mobiles au signal

H3 teste la VA COURANTE — un niveau qui bouge entre le signal et son issue
(la raison exacte de la quarantaine F23 des `cur_*`). La cible VPOC est déjà
figée à l'entrée (DECISIONS 07/09) ; cycle 2 : figer AUSSI le niveau du lieu
au moment du signal, comme F23 fige ses niveaux, et lire par heure (la VA de
10h00 a deux barres de vie ; celle de 14h en a dix-huit).

## 5 bis. Les quatre sur `atr_ref` — boucher le trou 9h30-11h00 (audit 08/09)

**FAIT le 09/09 (brique 1 Fable, DECISIONS) — sorti du cycle 2, entre dans la
campagne AVANT le gel avec re-rejeu des jours 1-2** : un NaN dans le metre
n'est pas une convention (meme classe que le DST). Reste ici pour l'histoire.

`atr_barre` (min_periods = 7) est NaN sur 100 % des barres 9h30-11h00 :
ZERO signal des quatre avant 11h00 sur 52 j x 2 (rapport
trou_atr_les_quatre) — la campagne gelee est aveugle pendant l'IB, la ou
la session teste PDH/VAH. Le cycle 2 lit `atr_ref` (= atr_barre, sinon
la MEDIANE de l'ATR de la VEILLE cash — `recalc.atr_veille_15`, sans
fuite, la solution L1). Deja fait pour les setups non geles : DIV_DELTA
v2 (lieux x4,2 ES / x3 NQ a P10 constant). `atr_source` se journalise.

## 5 ter. L'exception L0 `SESSION_CLOTURE` pour C2_EOD (revue 08/09, B1)

L0 n'a AUCUN mecanisme d'exception : C2_EOD entre a 15h30, la porte
`SESSION_CLOTURE` bloque a 15h30 — sans effet en ombre (l'ombre ne passe
pas par la chaine), BLOQUANT PAR CONSTRUCTION le jour ou EOD passe en
EXEC. L0 est scellee : l'exception s'ecrit ICI, maintenant, pas le jour
ou on s'en apercevra. Cycle 2 : cle `exceptions: [C2_EOD]` sur la porte,
portee STRICTE (uniquement l'entree 15h30 + sortie close_1545 d'EOD,
jamais un canal generique), avec son test : la porte bloque tout le reste
a l'identique, et EOD passe UNIQUEMENT dans sa fenetre.

## 5 quater. L4 : V1/V2 RETOURNES par famille (revue 08/09, C)

k=2 ES : retenus -0,162, vetoes +0,251 (N=23, bruit — mais le mecanisme
est visible) : V1 « personne n'achete » et V2 « le flux pousse contre »
sont ecrits pour une CONTINUATION ; sur un fade au VAH, « personne
n'achete » est LA THESE DU TRADE. Cycle 2 — signe attendu PAR FAMILLE,
ecrit avant la mesure : sur les fades (H3, retours a la valeur), le flux
qui pousse DANS LE SENS DU NIVEAU confirme le rejet → V1/V2 s'inversent
ou se retirent de la famille ; sur les continuations (EOD, cassures), ils
gardent leur sens. La regle 12 de LECTURE_JOUR_61 (lecture par famille)
est la version jour-61 de cette ligne.

## 5 quinquies. La fin de séance — TROIS candidats DISTINCTS, jamais un fourre-tout
*(observation Jackson mesurée — rapport spike_fin_session_20260908 — puis
recherche Fable 08/09 : académique + desk. Pré-enregistrés séparément.)*

Le fait mesuré : la minute 15h00 ET (clôture du marché obligataire, l'horloge
des desks taux) fait ×1,86 le range médian sur ES, ×1,64 sur NQ, volume ×2 —
60 jours, les deux instruments. Et 15h50-15h59 (déséquilibres MOC publiés à
15h50, D-Orders ~60 % du volume dès 15h57:30) porte le top-3 des ranges
3 jours sur 4. PERSONNE n'a publié d'edge directionnel sur la minute de
15h00 — le spike est réel, son sens est inconnu.

**a) C2_BOND_CLOSE — la minute 15h00, une QUESTION, pas un setup (brief
Fable 08/09).** Lieu : la barre 1 min 15h00-15h01 ET, `range ≥ p90` de la
distribution de CETTE minute (jamais de l'heure). Réaction : le sens du
spike = signe de `close(15h05) − close(14h55)`. Sens attendu — écrit
avant, et c'est un AVEU D'IGNORANCE : deux hypothèses opposées
pré-enregistrées ENSEMBLE — *continuation* (le rééquilibrage taux/actions
se prolonge, cohérent Baltussen) contre *retour* (choc de liquidité, pas
d'information — il se résorbe). Mesure : devenir à 15h30 et 16h00, signé
sens du spike ; attendu = **« l'un des deux, hors bruit, ou aucun »** —
et on ne trade NI l'un NI l'autre avant le jour 61. CONSÉQUENCE L5
IMMÉDIATE, indépendante du sens : un stop à ≤ 0,5 ATR-15m d'une position
ouverte entre 14h57 et 15h03 est un stop OFFERT — porte observée
**`PF_SPIKE_1500`** (« aurait été touché par la minute 15h00 »),
journalisée, lue à part.

**b) C2_SPIKE_DALTON — le plus solide des trois : une méthode COMPLÈTE.**
Un spike ≥ `x` ATR-15m dans les 30 dernières minutes (seuil sur
distribution ; attendu 0,7-1,0) crée une **fiche F23 de forme `spike`** :
base FIGÉE (le début du spike), extrême figé, sens. Elle ne se trade pas
le soir — elle se lit À L'OUVERTURE DU LENDEMAIN, trois régimes, trois
attendus écrits, UN journal : ouverture AU-DELÀ du spike = acceptation
(continuation, cible = extension) ; ouverture DANS le spike = équilibre
(rotation, on fade les bords) ; ouverture SOUS LA BASE = rejet (retour
vers la valeur de la veille). Même mécanique de mémoire d'épisode que
POOR v2 (A_FAIRE pt 20) — vit APRÈS F23 hors quarantaine. Référence :
Dalton, Mind over Markets, « Special Situations: Spikes ».

**c) C2_MOC_FADE — REFUSÉ, avec la raison écrite.** Le retournement
post-15h50 (Wu 2019 : ~13 bp/jour) repose sur les DÉSÉQUILIBRES MOC
publiés par le NYSE — non collectés. Sans eux, la seule version testable
est le proxy « mouvement 15h50-15h59 vs retour overnight », et la règle le
refuse. *À reconsidérer SI un flux de déséquilibres entre dans le DMP.*
Ce que la mesure GARDE de cette fenêtre : 15h59 au top-3 trois jours sur
quatre → **être plat à 15h55 n'est pas une prudence, c'est une porte
mesurée**.

L'instinct « 14h45 » de Jackson reste au journal MANUEL — noté au clic, lu
au jour 61. Références : Baltussen et al. 2021 (déjà C2_EOD),
Gao-Han-Li-Zhou 2018, Wu 2019, Bogousslavsky-Muravyev 2023,
Cushing-Madhavan 2000, Wood-McInish-Ord 1985, Admati-Pfleiderer 1988,
Dalton Mind over Markets.

## 5 sexies. Sites `astype("int64")` sur datetime NON traités (Fable 08/09, arb. 3)

Le chemin VIVANT (coureur + rejeu) est corrigé et couvert par l'invariant
`recalc.ts_ms`/`ts_plage` (fail-loud hors [2017..2065] ms). Les scripts hors
chemin gardent le vieux motif — ils ne tournent qu'en local pandas 2. S'ils
montent un jour sur le VPS (pandas 3), ils rendront des méga-secondes.
Motif à grep : `astype("int64")` sur un index/série datetime SANS
`as_unit("ns")`. Sites connus au 08/09 : `dataset_builder.py:916`,
`label_v4_dataset.py:223`, `label_v5_dataset.py:206`,
`build_dataset_v4_phase_b.py:894`, `phase_b_helpers.py:1384-1386`,
`train_v4_pure_lightgbm.py:218`. Condition de sortie : brancher
`recalc.ts_plage` en tête de chacun, ou les migrer vers `recalc.ts_ms`.

## 6. Confirmations positives, footprint, L4 en sortie

Reportés de la SPEC L4 §10, inchangés : modificateur de taille après 200
trades ; footprint par niveau de prix (même ligne C++ que le spread) ;
absorption lue sur la fiche F23 du niveau ; un veto L4 qui apparaît en
position = signal de sortie, mesuré comme les fantômes.

## 5 septies. H3 long : la VAL lue avec le signe inverse (mesure du 10/09, review du lieu)

`dist_cur_val` = VAL - close (mesure : `close + d x tick == cur_val_lvl` a
100 % sur 4 x 390 barres, `inside_cur_va = 1` -> d < 0), mais `h3` gele
reconstruit `val = close - dl x tick` = 2·close - VAL. Son LONG tire donc
quand la cloture est juste SOUS la VAL (`dl > 0`, |dl| <= P10) avec une meche
basse plus longue que la distance a la VAL — pas « sortie sous la VAL puis
cloture dedans ». Le short (VAH) est juste. Au cycle 2 : `val = close + dl x
tick`, `low < val`, `dl < 0` (cloture revenue AU-DESSUS) — miroir exact du
short — et lire les deux populations de longs cote a cote. En campagne : rien
ne bouge, H3-VPOC se mesure telle que taguee (LECTURE regles 37 et 38).
CADRAGE FABLE (10/09) : H3 gele est DEUX hypotheses sous un nom — le short au
VAH, celui qu'on a ecrit ; et un long ACCIDENTEL que personne n'a
pre-enregistre. La jambe long ne peut pas « passer » : un resultat sur elle
est une DECOUVERTE a pre-enregistrer ici, au cycle 2, jamais un verdict. Sa
taille (longs / shorts H3 sur le lot) est dans DECISIONS du 10/09 soir.
