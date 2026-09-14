# L1 — ce qui a été trouvé et décidé le 14/09/2026

Journée entière sur la couche biais. Ce document existe pour qu'aucune des
décisions ne se reperde : elles ont été prises sur mesure, et chaque chiffre
ici a sa source. **Aucun devenir de campagne n'a été lu** — tout le lot est
antérieur au 08/09.

---

## 1. LES QUATRE DÉFAUTS TROUVÉS

### 1.1 La couche était muette — 208 trous sur 208

`charger_seuils()` rendait le YAML brut ; `evaluer()` et le test cherchent les
seuils de composante au **premier niveau**. Donc `cfg.get("B1p")` valait `None`,
`z1_atr` était introuvable, et L1 disait `AUCUN` sur **156 barres sur 156**.
Le seuil était écrit dans le fichier **depuis le 07/09** et n'a jamais été lu.

### 1.2 La couche était FAUSSE — signe inversé sur 100 % des barres

La convention du dépôt est `dist_X = (niveau − prix) / tick` : un prix
**au-dessus** rend un nombre **négatif**. La clé `d_vwap_w` a été écrite sans
la négation. **B1p disait SHORT quand le prix était au-dessus de sa VWAP
semaine.**

La vérification écrite le même matin comparait la distribution de la **valeur
absolue** à celle publiée : un contrôle d'amplitude est aveugle à la direction.

Quatre preuves après correction :

| preuve | résultat |
|---|---|
| balayage des 25 colonnes `dist_*` à jumeau | accord ~0 partout, n > 4000 |
| sabotage (on retire la négation) | 0 barre correcte sur 26, ES et NQ |
| attendus P1/P2 écrits AVANT | côtés échangés exactement, zone morte figée (341 / 279) |
| confrontation avec `mon_module` | **38 désaccords → 38 accords**, 0 bloc sur 6 |
| lecture à l'œil contre le prix brut | **18 / 18**, dont 4 abstentions en zone morte |

### 1.3 Quatre composantes sur cinq sont MORTES

`lecture.lire()` ne produit **aucune** des cinq autres clés consommées :

| composante | clé manquante | état mesuré |
|---|---|---|
| B1n candidat rival | `issue_vwap_w` | `None` 100 % |
| B4 **veto** | `d_vwap_w_autre`, `smt_div` | `None` 1053/1053 ES, 1115/1115 NQ |
| B5 qualificateur | `open_vs_va` | `None` 100 % |
| B5b annulateur | `barres_inside_prev_va` | `None` 100 % |

Conséquence directe : `force` était `"fort"` par défaut → **2168 avis étiquetés
« fort », pas un seul « faible »**. Corrigé en `None` (non qualifié).

**La donnée existe pour les cinq** — `inside_prev_va`, `dist_prev_vah/val`,
`im_smt_divergence` (390/390), `dist_vwap_w` de l'autre instrument. C'est du
câblage, pas de la collecte.

### 1.4 `mesure_57j` portait le même signe, plus deux fabrications

Même négation manquante ; `issue_vwap_w = "tenu"` en dur (B1n devenait
**identique** à B1p — le duel annoncé comparait B1p à lui-même) ; et
`barres_inside_prev_va = 0` en dur. Sur les lignes mêmes où le commentaire se
félicite de ne rien fabriquer. CSV renommé `_PERIMEE_SIGNE`, narratif suspendu.

**Piège anti-peek trouvé** : `jours_du_lot` ne filtrait rien alors que
`devenir()` calcule un rendement FUTUR. Relancer aurait lu le devenir des
4 jours de campagne. **Rien n'a fuité** — le CSV est daté du 07/09, la veille
du jour 1 — mais la correction du signe rendait cette relance nécessaire.
Filtre posé dans `jours_du_lot`.

### 1.5 Aucune contamination du dossier de campagne

`biais.relation()` est appelé dans **un seul endroit** : `mesure_57j.py:195`,
module hors-ligne. Les **64 fichiers** de journal des 4 jours de campagne ne
portent **aucun** champ de biais. L1 n'est branchée sur rien — par construction,
`biais.py` n'a aucun accès à `chaine.appliquer`.

---

## 2. LES DÉCISIONS ARRÊTÉES (Jackson)

### D1 — Aucune colonne n'entre dans V3 sans passer par le registre

**Règle souveraine.** Source unique `V3/conventions.yaml` (35 colonnes :
producteur, unité, signe, et *comment le vérifier*). Appliquée par
`V3/tests/test_conventions.py`, qui **échoue** si une colonne lue par V3 n'y
figure pas. Prouvé par sabotage : **5 sur 5 détectés**, deux fois.
Inscrite dans `.claude/rules/data-quality.md`.

Trois conventions coexistent, et c'est le cas normal :

| producteur | famille | convention |
|---|---|---|
| DMP C++ / enricher | `dist_*` | **inversée** |
| recalc V3 | `*_r` | **directe** |
| DMP C++ | les trois ATR | `atr_14m` TICKS 1 min ; `atr_barre` POINTS 15 min ; `atr` TICKS fenêtre large |

### D2 — Le biais se place APRÈS le déclencheur, en observation

Jamais avant. Filtrer avant **détruit le contrefactuel** : on ne peut plus
mesurer si bloquer était juste. Une fois prouvé, il pourra se déplacer avant
pour l'efficacité — **jamais l'inverse**.

Et c'est mesuré : filtrer avant ne garderait que **19,4 % (ES) / 20,0 % (NQ)**
des signaux, en coupant les **shorts deux fois plus fort** que les longs
(14,3 % contre 24,9 % de survie sur ES). Ça reproduirait par construction le
biais long-only qui a tué Bot 3 v1 (14 trades sur 15 en LONG, WR 13 %).

### D3 — Six états, pas cinq

| | nom | ce que le module AFFIRME | action |
|---|---|---|---|
| +2 | **ACHETEURS +** | j'ai regardé : les acheteurs mènent nettement | 1 micro long |
| +1 | **ACHETEURS** | j'ai regardé : les acheteurs mènent | 1 micro long |
| 0 | **PERSONNE** | j'ai regardé : aucun camp ne mène | rien |
| −1 | **VENDEURS** | | 1 micro short |
| −2 | **VENDEURS +** | | 1 micro short |
| — | **MUET** | **je n'ai pas pu regarder** | rien |

`MUET` et `PERSONNE` font la même chose mais **ne doivent jamais être
confondus** : l'un est un état de marché, l'autre une panne. C'est ainsi que le
bug des 110 946 barres (zéro signal VENTE, 74 jours) a survécu deux mois.
Doctrine fondatrice : **`None` n'est pas `0`**.

Les noms décrivent un **constat**, pas une prévision. « Haussier » affirme
l'avenir et ne peut pas être réfuté ; « les acheteurs mènent » se vérifie.

### D4 — Taille FIXE, un micro sur tout cran non nul

La pyramide de taille est la **récompense d'une monotonie prouvée**, pas un
point de départ. Mesuré ce jour : l'échelle de B1p est **INVERSE des deux
côtés, aux deux horizons** — le cran +2 est moins bien aligné (48,7 %) que
le +1 (52,5 %). Doser 2× dessus doublerait la variance sur le plus mauvais cran.
Précédent du dépôt : BotBN, grade non monotone `A++ PF 0,81 < C 1,92`.

### D5 — Garder l'architecture V3, changer la FORME

V3 est la seule des trois générations qui peut être prise en défaut, qui
distingue « pas d'avis » de « donnée absente », et qui ne peut pas faire de
dégât. On la garde.

Mais on passe **du biais par barre à la lecture datée** : une mesure, à un
moment choisi, valable pour une **jambe** (entre deux extrêmes de value area).
C'est la seule forme avec un soutien externe — Gao, Han, Li & Zhou, *JFE* 2018,
R² hors échantillon 1,7 à 2,5 %, répliqué sur 11 instruments.

F23 porte déjà la machinerie (`z_touche_atr`, `z_reset_atr`,
`k_reaction_barres`). Le nombre de jambes par jour est un réglage d'hystérésis.

### D6 — La question est « QUI A LA MAIN », pas « où va le prix »

Formulation de Jackson, et déjà codée dans le Dashboard
(`builders.py:876-885`). C'est un constat d'orderflow, pas une prévision.
Les 48 tests d'alignement n'ont porté que sur des indicateurs de **position** ;
les indicateurs de **domination** (absorption, pression, gros ordres) n'ont pas
été testés.

**Méthode de Jackson, à reproduire** : *« quand j'arrive dans ma zone, je
n'achète pas automatiquement — je regarde leur flow, je cherche une
confirmation »*. Zone → flux → confirmation → trade.

### D7 — Journaliser le SCORE CONTINU, jamais seulement le cran

Le cran est une **décision** ; le score est une **donnée**. Journaliser le score
signé permet de redécouper les seuils après coup, à 3, 5 ou 7 crans. Même
doctrine que le devenir : *« il doit être RECALCULABLE »*.

Et journaliser **aussi sur les décisions qu'on ne prend pas**, sinon `PERSONNE`
ne produit aucune mesure.

### D8 — Données : `live_enriched/sierra` uniquement

Règle souveraine du 16/06. Les 129 jours de `live_enriched/{ES,NQ}`
(déc. 2025 – mai 2026) sont **écartés** : sur les 2 jours de chevauchement,
`close` identique sur 408/412 mais `dist_vwap_w` et `atr_14m` **différents sur
100 % des barres**. Même marché, définitions différentes.

### D9 — Cooldown maintenu à 90/60

45/30 doublerait la cadence. Coût sur 61 jours, 1 MNQ + 2 MES :
**3 523 $ à 5 trades/jour**, **7 046 $ à 10** — contre un **drawdown suiveur de
2 000 $**. Et doubler les trades ne double **pas** la puissance : l'unité
indépendante est la **session**, et il y en a 61 dans les deux cas (leçon du
04/07 : PF 1,81 au niveau trade, aucun t-stat > 2,0 au niveau session).

Mesuré : **10,9 signaux/séance sur ES, 12,9 sur NQ** (avant les portes L0) —
le cooldown mord donc bien.

### D10 — 2 MES pour 1 MNQ, stops 9 / 36

Mesuré : ATR 15 min **ES 34,9 ticks / NQ 213,1 ticks** (×6,1). À risque égal,
1 MNQ vaut **1,60 MES** avec les stops en miettes, **2,44** avec des stops
proportionnels à l'ATR. Le « 3 » lu ailleurs est trop haut pour cet usage.

Avec les stops 9/36, le coût tombe à **39 % du stop sur ES** (était 70 %) et
**16 % sur NQ**.

### D11 — P&L séparés, comparaison APPARIÉE par session

ES et NQ sont corrélés (le biais dit la même chose 96 % du temps). Comparer
deux séries indépendantes gaspillerait cette information : il faut comparer la
**différence jour par jour**, le facteur de marché commun s'annule.

---

## 3. LES CHIFFRES DE RÉFÉRENCE

| mesure | valeur |
|---|---|
| Alignement, 48 tests pré-enregistrés | **1 case exclut zéro** — moins que les ~2,4 faux positifs attendus |
| Étalon hasard, NQ flux | +5,0 à **+14,6 pp** — même ampleur que le « meilleur » candidat |
| avec / contre / sans | ES 19,4 / 58,0 / 22,6 % — NQ 20,0 / 62,3 / 17,6 % |
| Veto, variante C + hystérésis k=2 | **0,21 bascule/jour**, 2,4 % de barres, 7 épisodes / 52 j |
| Niveaux respectés (VAH+VAL) | **60 à 80 %** sur les deux instruments |
| Rejet vs traversée à k=2 | **0,94 ATR contre 0,14 ATR** |
| Déclencheurs | **H7 = 96 %** des tirs ; **H6 et H8 muettes (0 signal)** |
| Couverture B1p | 76 % ES / 80 % NQ des barres — **100 % / 96 % des jours, hors spec [30-95 %]** |
| Persistance B1p | **15 barres ES / 23 NQ** sur 26 → un avis par jour, pas 26 |
| Accord ES/NQ du biais | **96 %** |

**Externe** : OFI (Cont-Kukanov-Stoikov) IC +0,0044 ; à 10 s les coûts
dépassent l'edge d'un **facteur 164** ; à 5-10 min l'IC monte à +0,015 mais ne
survit pas à la correction pour tests multiples. Pour comparaison,
`vwap_slope_10` mesuré dans ce dépôt vaut rho **+0,0174** — **le signal est
réellement de cette taille-là**.

---

## 4. CE QUI RESTE OUVERT

- **H6 et H8 ne tirent jamais** sur ce chemin — colonne manquante ou défaut ?
- **Câbler les 5 clés mortes**, chacune par le registre. Ordre de risque :
  `open_vs_va` et `barres_inside_prev_va` (recette déjà dans le dépôt), puis
  `smt_div`, puis `d_vwap_w_autre` (croise deux instruments), puis
  `issue_vwap_w` (le plus risqué : look-ahead si la fenêtre de réaction est mal
  posée).
- **Test de causalité générique** : `lire(df[:i+1], i)` doit rendre exactement
  `lire(df, i)`.
- **`prev_vah` / `prev_val`** désignent un autre niveau que `dist_prev_vah` /
  `dist_prev_val` — écart jusqu'à 63 points. V3 n'utilise que les distances et
  reste cohérent, mais l'anomalie est réelle.
- **Le biais de domination** (orderflow) n'a jamais été testé.
- **L'ES mérite-t-il sa place** : 2 669 $ de frais sur 61 jours pour 2 MES.
- **Relance du test d'alignement au jour 61** : 52 → 113 sessions. À
  pré-enregistrer avant de voir quoi que ce soit.
