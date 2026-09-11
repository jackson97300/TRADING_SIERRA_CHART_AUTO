# CANDIDATS CYCLE 2 — ce que la campagne fait remonter, sans y toucher

*Ouvert le 11/09/2026, le jour du gel `campagne-ombre-1b`. Chaque ligne est
une **observation datée** née pendant les soixante jours : un trade légitime
que le narrateur montre passer, une condition qui bloque tout, une séquence
que la grammaire ne nomme pas. **Rien ici ne se code, ne se règle et ne
s'applique avant le jour 61.** C'est le carnet, pas le cahier des charges.*

**La règle qui gouverne ce fichier.** Une ligne s'écrit quand elle est
OBSERVÉE, avec sa date et sa mesure si elle en a une. Elle ne s'écrit jamais
sur un résultat (le devenir est fermé). Au jour 61, chaque ligne devient une
hypothèse pré-enregistrée du cycle 2, avec son attendu écrit AVANT sa mesure,
ou elle est rayée avec la raison. Une ligne qui n'a pas d'attendu écrit au
cycle 2 ne s'y code pas.

---

## 1. `rvol_r >= 1,8` rend H8p structurellement muette
**11/09/2026 — mesuré sur le lot (58 journées × 2 instruments, avant le gel).**
Quand le lieu de H8p est atteint, la condition de volume relatif bloque
**93 % des cas sur ES, 92 % sur NQ** :

| hypothèse | barres où le lieu est atteint | tire | ce qui manque, en tête |
|---|---|---|---|
| H8p ES | 1394 | 3 (0,2 %) | `rvol` 1290 (93 %), `delta` 96 (7 %) |
| H8p NQ | 1304 | 0 (0,0 %) | `rvol` 1200 (92 %), `delta` 98 (8 %) |
| H3 ES | 289 | 28 (9,7 %) | `cloture_dedans` 161 (56 %), `finish` 83 (29 %) |
| H3 NQ | 272 | 24 (8,8 %) | `cloture_dedans` 135 (50 %), `finish` 101 (37 %) |
| H2p ES | 117 | 2 (1,7 %) | `delta` 86 (74 %) |
| H2p NQ | 93 | 1 (1,1 %) | `delta` 80 (86 %) |
| H6p ES | 119 | 11 (9,2 %) | `porte` (IB cassée) 66 (55 %), `regime` 28 (24 %) |
| H6p NQ | 98 | 12 (12,2 %) | `porte` 50 (51 %), `regime` 22 (22 %) |

Deux lectures, aucune conclusion :
- Le lieu de H8p est atteint 1300 à 1400 fois par instrument, soit environ
  la moitié des barres cash. Un lieu qui est presque toujours là ne
  discrimine rien : c'est le minimum sur dix niveaux à P20, et à ce grain le
  prix est toujours près de quelque chose. **Le vrai filtre de H8p n'est pas
  son lieu, c'est son `rvol`** — et c'est le contraire de ce que sa
  description dit.
- H2p est bloquée par son `delta` dans 74 à 86 % des cas. Avec 3 signaux
  projetés sur soixante jours, elle ne sera pas mesurable. Déjà connu
  (règle 10, sous-puissance assumée), désormais chiffré à la condition près.

**Ce qui se pré-enregistrera au cycle 2, pas avant** : la distribution de
`rvol_r` AU LIEU de H8p (pas sur toutes les barres), pour savoir si 1,8 est
le p90 ou le p99 de cette population — un seuil posé sur la mauvaise
distribution est la faute déjà commise six fois dans ce dépôt.

---

## 2. Le spike de la minute 15h00 ET
**Pré-enregistré le 08/09 (NEXT_CYCLE §5 quinquies), repris ici comme
candidat vivant.** La minute de clôture du marché obligataire fait ×1,86 le
range médian sur ES et ×1,64 sur NQ, volume ×2, sur 60 jours et les deux
instruments. Personne n'a publié d'edge directionnel dessus : le spike est
réel, son sens est inconnu. Les deux hypothèses opposées — continuation et
retour — sont pré-enregistrées ENSEMBLE, et aucune ne se trade avant le
jour 61. La conséquence L5 est déjà active et indépendante du sens : un stop
à moins de 0,5 ATR-15m d'une position ouverte entre 14h57 et 15h03 est un
stop offert (porte observée `PF_SPIKE_1500`).

---

## 3. La valeur du jour n'est pas une zone du narrateur
**11/09/2026 — mesuré sur le lot.** Le VPOC, le VAH et le VAL **courants**
sont testés environ 140 fois par niveau et par instrument, avec des taux de
tenue de 51 à 71 % — le VAH du jour sur NQ tient 71 % des fois où il est
testé, le meilleur score du lot après l'IB. Et c'est **le lieu de H3**,
l'hypothèse principale. Ils sont en quarantaine parce qu'ils bougent en
séance : bonne raison de ne pas les FIGER à 9h30, pas de ne pas les
AFFICHER. Proposition mesurée à porter au module après le gel, jamais à la
chaîne.

---

## 4. La validation par persistance
**11/09/2026 — mesuré sur le lot.** 23 journées sur 58 (ES) et 26 sur 58
(NQ) finissent sans aucun scénario validé. Leur forme : 12 et 14 sont des
journées qui ouvrent hors valeur et n'y reviennent jamais (jamais validées
faute d'acceptation au-delà de l'IB), 7 et 8 sont des cassures d'IB qui
partent sans retest. Le mécanisme qui manque existe déjà pour un seul
scénario : `S_DANS_POSE` est validé à la clôture par la persistance, 4
journées, 4 validées. **Réserve écrite avant la mesure** : la couverture
attendue est bornée à 80 % par la relectrice ; si l'ajout la fait monter
au-delà et fait s'effondrer l'écart au tirage au sort, c'est une validation
qui ne dit rien — le test tranche, pas l'envie.

---

## 5. (à remplir) — les trades légitimes que le narrateur montre passer
*Une ligne par occasion vue et non prise, datée, avec le scénario en cours,
la zone, et ce qui manquait à la règle. C'est la moitié la plus intéressante
de la campagne : ce que la machine ne voit pas et que l'œil voit.*

| date | instrument | heure ET | scénario en cours | zone | ce qui manquait |
|---|---|---|---|---|---|
