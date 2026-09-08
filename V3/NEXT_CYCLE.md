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

**a) C2_BOND_CLOSE — une QUESTION, pas un setup.** Hypothèse mesurable : le
sens du spike de 15h00 (clôture 15h00-15h05 vs 14h55) continue-t-il ou se
retourne-t-il dans les 30 minutes ? Deux attendus OPPOSÉS possibles, aucun
de niveau A — les deux s'écrivent AVANT la mesure, brief Fable requis.
CONSÉQUENCE L5 IMMÉDIATE (cycle 2, B-NIV) : **un stop à portée de 0,5 ATR
entre 14h58 et 15h03 est un stop OFFERT** — la fenêtre du spike récolte les
stops proches ; le placement doit la connaître.

**b) C2_MOC_FADE — EXIGE UNE DONNÉE NON COLLECTÉE.** Le retournement
post-15h50 (Wu 2019 : ~13 bp/jour) se mesure sur les DÉSÉQUILIBRES MOC
publiés, que nous ne collectons pas. Sans ce flux, il ne resterait que le
proxy « mouvement 15h50-15h59 vs retour overnight » — exactement la classe
de proxy que la règle refuse. Ne se pré-enregistre PAS tant que la donnée
n'existe pas dans la collecte.

**c) LES RÈGLES DE SPIKE DE DALTON — le plus solide des trois.** Mind over
Markets (« Special Situations: Spikes ») : un spike ≥ x ATR dans les
30 dernières minutes ne SE TRADE PAS le soir — il crée une référence pour
LE LENDEMAIN (base du spike = support ; ouverture au-dessus / dedans /
dessous = trois lectures). Design : une fiche F23 de forme `spike` (base
FIGÉE, mémoire d'épisode — la même famille que POOR v2, A_FAIRE pt 20),
lue à l'open suivant. Quarante ans de pratique derrière ; brief Fable +
seuil x posé sur distribution, jamais inventé.

L'instinct « 14h45 » de Jackson reste au journal MANUEL — noté au clic, lu
au jour 61. Références : Baltussen et al. 2021 (déjà C2_EOD),
Gao-Han-Li-Zhou 2018, Wu 2019, Bogousslavsky-Muravyev 2023,
Cushing-Madhavan 2000, Wood-McInish-Ord 1985, Admati-Pfleiderer 1988,
Dalton Mind over Markets.

## 6. Confirmations positives, footprint, L4 en sortie

Reportés de la SPEC L4 §10, inchangés : modificateur de taille après 200
trades ; footprint par niveau de prix (même ligne C++ que le spread) ;
absorption lue sur la fiche F23 du niveau ; un veto L4 qui apparaît en
position = signal de sortie, mesuré comme les fantômes.
