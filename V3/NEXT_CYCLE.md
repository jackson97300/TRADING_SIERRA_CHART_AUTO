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

`atr_barre` (min_periods = 7) est NaN sur 100 % des barres 9h30-11h00 :
ZERO signal des quatre avant 11h00 sur 52 j x 2 (rapport
trou_atr_les_quatre) — la campagne gelee est aveugle pendant l'IB, la ou
la session teste PDH/VAH. Le cycle 2 lit `atr_ref` (= atr_barre, sinon
la MEDIANE de l'ATR de la VEILLE cash — `recalc.atr_veille_15`, sans
fuite, la solution L1). Deja fait pour les setups non geles : DIV_DELTA
v2 (lieux x4,2 ES / x3 NQ a P10 constant). `atr_source` se journalise.

## 6. Confirmations positives, footprint, L4 en sortie

Reportés de la SPEC L4 §10, inchangés : modificateur de taille après 200
trades ; footprint par niveau de prix (même ligne C++ que le spread) ;
absorption lue sur la fiche F23 du niveau ; un veto L4 qui apparaît en
position = signal de sortie, mesuré comme les fantômes.
