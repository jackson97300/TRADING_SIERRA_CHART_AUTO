# LE POST-IT DE JACKSON — CE QU'IL TRADE, RENDU MESURABLE (v2)
*À déposer : `layers/L3_declencheurs/POSTIT_JACKSON.md`. Fable, 09/09/2026, v2 : la ligne « Range » détaillée (machine à états, balance, TP), et les autres lignes affinées de la même manière. Rien n'entre dans le gelé ; tout entre en ombre (`ombre_c2.py`), pré-enregistré, avec date et attendu. La première ligne du post-it gouverne le tout : « si tu ne sais pas où tu vas, regarde où tu sors » — la sortie se définit avant l'entrée (L5).*

---

## 0. La grammaire — trois natures, deux unités, jamais mélangées

| nature | ce que c'est | où ça vit | comment ça se mesure |
|---|---|---|---|
| **lieu** | l'endroit où quelqu'un a une raison d'agir (zone) | L3 `lieu()` | part des barres en zone ; porte `HORS_ZONE` observée sur les quatre |
| **réaction** | la barre qui dit que quelqu'un a répondu — les barres du post-it | L3 `reaction()` | entonnoir lieu → réaction, par setup |
| **confirmation** | ce que Jackson regarde en plus avant de cliquer | journalisée, **jamais filtrante** en ombre : six booléens par signal | avec/sans, une par une, jamais additionnées |

**Deux unités, deux rôles** : le **15 min décide** (le range existe, le prix est au bord, la barre a réagi — c'est l'unité de la mesure) ; le **1 min exécute** (L4 confirme sur `k` barres, l'entrée se fait à la clôture de la barre de confirmation ; le 5 min = `k = 5`). L'entrée *au touché* avant la clôture 15 min n'est pas exécutée : elle est **journalisée comme contrefactuel** (`prix_touche_1min`, et si une clôture 15 min a suivi ou non) — c'est ce qui a tué V1, on le mesure au lieu de le trader.

---

## 1. Les six confirmations — la boîte à outils commune

| conf | définition | colonnes | provenance |
|---|---|---|---|
| `C_VOL` | `rvol_r ≥ p75` de l'heure sur la barre de réaction | `rvol_r` | recalc (A) |
| `C_VA` | position dans la VA veille ; **confirmation = au bord** (≤ P10 de VAH/VAL) | `dist_prev_vah/val` | A |
| `C_DIV` | divergence delta : extrême de session avec `cvd_sess_r` non confirmé | `cvd_sess_r`, OHLC | recalc — pas `delta_div_*` C++ |
| `C_EDGE` | edge zone active dans le sens (bid/ask piégés au bord de la barre) | `bar_edge_*`, `fp_edge_*` | **B, DMP de Jackson → reproduction obligatoire** (mismatch = 0 / 2 jours), sinon `None` |
| `C_ACCEL` | ralentissement à l'approche : `vitesse_approche_r < p25` (5 barres 1 min avant la touche, en ATR) | OHLC 1 min | recalc |
| `C_ACCORD` | l'autre instrument est dans le même état (range `ETABLI` des deux côtés, ou même côté de sa VWAP) | états des deux instruments | recalc |

---

## 2. RANGE — la ligne détaillée

### 2.1 Ce qu'est un range pour du code
Un humain voit un range après coup, les deux bords dessinés. Le code doit le voir pendant qu'il se forme. Définition : **deux niveaux qui se font face, chacun testé et tenu au moins deux fois, séparés d'une largeur qui n'est ni du bruit ni une tendance, sans acceptation à l'extérieur.** Chaque mot est une définition F23 existante (touche, tenue, cassure = deux clôtures 15 min, regain). Un range = **deux fiches F23 face à face**. Rien de nouveau à inventer.

### 2.2 La machine à quatre états — `range_r` dans `recalc.py`, une seule unité : le 15 min
```
FORMATION  un haut et un bas existent (après 10h30, l'IB EST le premier range ;
           sinon : deux swings recalculés, ou VAH/VAL du jour après stabilite_cur)
ETABLI     chaque bord : n_tests >= 2, issue = tenu ; largeur dans [w_min, w_max] ATR-15m
           (distribution : attendu 0,8-2,5) ; aucune acceptation dehors
CASSE      acceptation au-delà d'un bord (deux clôtures) — c'est la « longue barre
           de transition » : événement TRANSITION, lu par REG (la rotation est finie)
RETEST     retour sur le bord cassé : continuation (H6p corrigé) si le bord tient de
           l'autre côté ; head-fake (PJ_HEADFAKE) si regain avec déséquilibre
```
Les bords sont **figés** dès `ETABLI` (règle F23). Par barre 15 min, le journal porte : `etat`, `bord_haut`, `bord_bas`, `largeur_atr`, `n_tests_haut/bas`, `age_barres`, `compression` (§2.6). Les `cur_*` n'entrent dans FORMATION qu'après `stabilite_cur_barres` (distribution de la stabilité de `cur_vah` par heure — attendu ~6 barres).

### 2.3 L'unité de temps — une seule pour détecter, une balance au-dessus
Plus l'unité monte, plus le range est fiable (plus de participants l'ont construit) — et moins il y a de trades, plus le stop est loin. On ne construit **pas** un détecteur par unité. On empile ce qui existe :
- **La balance multi-jours = REG** : VA veille / J−2 / J−3 qui se chevauchent (`profile_overlap_pct`, `composite_poc_5d`, A). Booléen `dans_balance` : le prix est dans la zone de chevauchement.
- **Le range intrajour 15 min = L3** : la machine ci-dessus.
- **L'empilement = une inclusion** : `range_dans_balance` = le range 15 min est à l'intérieur de la balance → fade du bord avec deux couches de monde derrière (le trade fort). Range formé *au bord* de la balance → la cassure du petit est la cassure de la grande (le trade de continuation). Un booléen, pas trois détecteurs.
- **ES et NQ** : jamais une condition. `C_ACCORD` journalisé ; le désaccord = *le faible et le fort* (P6).

### 2.4 Le trade du range — `PJ_RANGE_FADE`
- **Régime** : `ETABLI`, ROTATION (REG), et de préférence `range_dans_balance` (journalisé, pas exigé).
- **Lieu** : ≤ P10 d'un bord figé. **Réaction** : barre 15 min qui touche le bord (mèche au-delà admise, `high > bord`) et clôture dedans, `finish_r` contraire au bord — ou la barre de retournement P4. **L4** confirme sur `k` barres 1 min. **Side** : vers l'intérieur.
- **Confirmations attendues** : `C_VOL`, `C_EDGE`, `C_ACCORD`, `C_ACCEL` (ralentissement).
- **Contre-indications journalisées** (pas filtrantes en ombre) : `compression` haute (§2.6), `n_tests ≥ 4` sur ce bord (le carburant s'use — Q2 du narratif), `age_barres` > p90.
- **Attendu** : 60–70 % des barres cash en `ETABLI` (à vérifier — c'est le « 70 % en range » de Jackson), N ≈ 40–60 par instrument ; direction positive **quand la largeur ≥ w_frais** (§2.5), nulle en dessous.

### 2.5 Le TP dans le range — les deux écoles, et le profil en D
Les deux écoles ont raison dans deux ranges différents :
- **École du 50 % = le VPOC**, pas « la moitié » : l'aimant. Haute probabilité, petit gain. Le **profil en D** (le profil équilibré, symétrique autour du VPOC — `profile_shape`, `poc_position ≈ 0,5`, `is_double_dist = 0`) est le régime où cette école gagne : le prix rejeté d'un bord revient à la valeur, et traverser la valeur coûte du temps.
- **École du 70–80 % = le bord opposé − P05**, légitime **seulement après acceptation dans la valeur** (règle des 80 %, Dalton) — pas sur un simple rejet.
- **Quatre variantes B-NAT pour chaque signal de range**, hors ligne : `TP_VPOC`, `TP_75`, `TP_BORD`, `TP_2PARTS` (moitié au VPOC, moitié au bord, stop à l'entrée après la première). La mesure : **MFE en % de la largeur** avant la première réaction contraire, par tranche de largeur (0,8–1,2 / 1,2–2 / > 2 ATR) et par rang du test — la distribution dit où le prix s'arrête, et l'espérance nette de chaque TP se lit dessus.
- **Attendu écrit** : range étroit (< 1,2 ATR) → `TP_VPOC` gagne (le bord opposé coûte trop en probabilité) ; balance large + acceptation → `TP_BORD` ; `TP_2PARTS` meilleure espérance par trade, pire variance.
- **Largeur minimale rentable `w_frais`** : la largeur en dessous de laquelle même `TP_VPOC` ne paie pas les frais Tradeify (calcul direct : frais / (largeur/2), seuil = celui de `FRAIS_TROP_LOURDS`). Sur MES, un range de 0,8 ATR = 12 pts, aller au milieu = 6 pts, frais ≈ 1 pt.
- **Règle par défaut en attendant la mesure** : VPOC ; bord d'en face seulement après acceptation.
- **Journal `MANUEL`** : où Jackson a cliqué pour sortir, en un mot pourquoi → au jour 61, ses sorties contre les quatre règles sur les mêmes trades (« pas de règle stricte » = plus tôt que le VPOC, ou plus tard que le bord — et de combien).

### 2.6 La compression — ce que le code voit et l'œil rate
`compression` = largeur *effective* des tests récents (distance des k derniers tests au milieu) / largeur du range. En dessous d'un seuil (distribution), le range se resserre : le fade devient dangereux, la cassure devient le trade. Journalisé par barre ; attendu : les `CASSE` acceptées sont précédées d'une compression plus souvent que le hasard (contrôle : permutation des barres). C'est aussi la lecture qui rend la « longue barre de transition » prévisible au lieu de subie.

### 2.7 Les cinq mesures avant tout trade de range (une passe, 57 jours)
1. Distribution de la largeur des ranges `ETABLI`, par instrument.
2. Durée en barres, et mort par `CASSE` vs par extinction (le prix part sans accepter).
3. **Taux d'échec de la première cassure** (Dalton dit « la plupart » — c'est un chiffre).
4. MFE du fade vers le VPOC / le bord, par largeur et par rang (§2.5).
5. Part des barres cash en `ETABLI` — le « 70 % ».

---

## 3. Les autres lignes, affinées

### P2 — Swing high / low → lieu, et Dow
- **Prérequis** : `swings_r` (pivots à `k` barres 15 min de chaque côté, `k` sur distribution, attendu 2–3), séquence HH/HL/LH/LL journalisée (B2). Sans swings recalculés, pas de P2, pas de Dow, pas de bords de range hors IB/VA.
- **`PJ_SWING`** : lieu = dernier swing ≤ P10 ; réaction = P4 ou longue barre ; en ROTATION : rejet (contre le swing) ; en tendance (B5 + séquence HH/HL) : **le retracement qui tient au-dessus du dernier plus bas** — c'est Dow, et c'est le pullback du post-it. Confirmations : `C_VOL`, `C_EDGE`.

### P3 — Longue barre / longue barre de transition → réaction, et événement
- `range_15m ≥ p95` de l'heure (recalc ; `bar_long_*` C++ à reproduire d'abord — si elle reproduit, on la garde).
- Deux usages : **`TRANSITION`** (longue barre qui sort d'un range `ETABLI` ou casse un swing → REG : fin de rotation) ; **réaction forte** au lieu (pour `PJ_SWING`, `PJ_RANGE_FADE`).
- Attendu : `TRANSITION` avant 11h annonce un jour de tendance (lecture avec B5) ; `TRANSITION` précédée de `compression` plus souvent que le hasard.

### P4 — Long up-down / down-up → la barre de retournement, `PJ_RETOURNEMENT`
- Barre `t−1` longue (P3) dans un sens, barre `t` longue dans l'autre qui efface ≥ `e` de la précédente (distribution ; attendu 60–80 %) et clôture au-delà de son milieu. `long_*_pattern` (DMP, B) à reproduire ; cas réel : ES 07/09 07:45 (`bar_long_dn_up = 1`).
- **Hors zone, pas de signal** — lieu = toute zone déclarée ≤ P10 (bords de range, VA, VWAP/SD, swing, ON, mur, ouverture). Confirmations : `C_VOL` sur la 2ᵉ barre, `C_VA` au bord, `C_EDGE`. Cible : niveau opposé de la zone.
- Attendu : N ≈ 20–30 ; positif **avec** `C_VOL`, nul sans — l'attendu qui teste la grammaire.

### P5 / P11 — Head-fake, secoué (V ou Λ) → `PJ_HEADFAKE`
- Cassure (deux clôtures) puis regain, `desequilibre_au_dela ≥ seuil` (p75), sur **toute** zone déclarée (C2_SWEEP_ON n'en couvre que ON). Variante `forme = V` : `duree_au_dela ≤ 3 barres`. Un seul setup, une variante journalisée — on ne multiplie pas les comparaisons. Side : contre la cassure. Confirmations : `C_EDGE`, `C_VOL`. Dans un range : c'est le `RETEST` qui regagne.

### P6 — Le faible, le fort → `PJ_FORT_FAIBLE`
- Divergence ES/NQ (l'un fait un extrême de session, l'autre non — `im_smt_divergence` reproduit ou recalcul depuis les extrêmes de session) ; on **vend le faible** au retour sur sa VWAP en tendance baissière (B5), miroir pour le fort. Et en range : le désaccord `C_ACCORD = False` est l'information, pas l'obstacle. Confirmations : `C_ACCORD` (par construction inverse), `C_VOL`. Attendu N ≈ 15, séparer « divergence à l'ouverture » / « en séance ».

### P7 — Footprint et edge zone → L4, `C_EDGE`
- Pas un déclencheur : **le boom**. Prérequis : reproduction des colonnes edge de Jackson (`bar_edge_*`, `fp_edge_*`, `dist_ext_edge_*`), puis `C_EDGE` lisible partout, et veto L4 candidat (`V_EDGE_CONTRE` : edge active contre le trade → aurait bloqué, observé).

### P8 — Joue accélération → `C_ACCEL` et `V_ACCEL`
- Ralentissement vers la zone = confirmation (quelqu'un absorbe avant la touche) ; accélération à travers = veto observé (`vitesse_approche > p90` : personne ne défend, le fade est un contre-sens).

### P9 — Open / VWAP / SD… ground zero → références
- `OMBRE_C2.md` §3 (C2_VWAP_RET / SD1_RET). Le post-it ajoute **l'ouverture** (`open_cash_lvl`, A) comme zone déclarée et comme niveau de retour (`PJ_OPEN_RET`). Dans un range, la VWAP est souvent le *milieu* — `TP_VPOC` et `TP_VWAP` se comparent.

### P10 — Bouée de sauvetage → **B-BOUEE**, quatrième barrière (L5)
- Règle fixée (09/09) : après l'entrée, si le prix touche `entrée − a·ATR` (contre) puis revient à `entrée ± r` dans les `n` premières barres → **sortie à l'entrée, toujours, sans désarmement**. Le retour n'est pas une seconde chance, c'est un aveu.
- `a` = **p75 de la MAE des trades finis en TP** sous B-ATR (attendu ~0,4 ATR ; en dessous tout se scratche et la mesure ment) ; `r` = P05 ; `n` : distribution du temps au premier retour (attendu 4–8 barres).
- Journal : 4ᵉ ligne par signal (`declenchee`, barre, `mae_avant`, `mfe_avant`, issue B-ATR remplacée, **prix à +20 barres après la sortie**).
- **Attendu (H-L5-BOUEE)** : moins de SL, moins de TP, espérance inconnue ; **et l'affirmation de Jackson : après une bouée, le prix à 20 barres est du côté du SL plus souvent que du TP.** Si vrai → `NEXT_CYCLE` : le rebond qui fait sortir est un lieu d'entrée inverse (pas maintenant). Lecture séparée fade / continuation (un fade a souvent un premier retour contre lui).

---

## 4. Ce qui en sort

| setup / objet | type | prérequis | attendu N/60 j |
|---|---|---|---|
| `range_r` (machine à états) | recalc + journal par barre | F23 `prev_*` hors quarantaine, `swings_r`, `stabilite_cur` | — |
| `PJ_RANGE_FADE` | setup | `range_r`, `finish_r` | 40–60 |
| `PJ_RETOURNEMENT` | setup | P4 recalc (+ reproduction DMP) | 20–30 |
| `PJ_SWING` | setup | `swings_r` | 15–25 |
| `PJ_HEADFAKE` (+ V) | setup | F23 déséquilibre | 15–20 |
| `PJ_FORT_FAIBLE` | setup | `im_smt` reproduit / recalc | ~15 |
| `PJ_OPEN_RET` | setup | `finish_r`, B5 | 10–20 |
| `TRANSITION`, `HORS_ZONE`, `compression` | événements / colonnes | `range_r` | — |
| `TP_VPOC / TP_75 / TP_BORD / TP_2PARTS` | variantes B-NAT | J2 de L5 | tous les signaux de range |
| **B-BOUEE** | 4ᵉ barrière L5 | J2 de L5, MAE des gagnants | tous les signaux |
| `prix_touche_1min` | contrefactuel d'entrée | OHLC 1 min | tous les signaux |

---

## 5. Ordre de construction
1. **`test_dmp.py`** — reproduction des colonnes DMP de Jackson (`bar_long_*`, `long_*_pattern`, `bar_edge_*`, `fp_edge_*`, `im_smt_divergence`) : mismatch = 0 / 2 jours ; ce qui reproduit se garde, le reste se recalcule. Débloque P3, P4, P6, P7.
2. `recalc.py` : `finish_r`, `range_hnorm_r`, `retournement_r`, `vitesse_approche_r`, `swings_r`, **`range_r`** (machine à états + `compression`), `dans_balance`.
3. `lecture.py` : bloc `conf` (six booléens), bloc `range` (état, bords, largeur, inclusion).
4. **Les cinq mesures du range** (§2.7) → `rapports/ranges_57j.md` — **avant** tout setup de range.
5. Les setups dans `ombre_c2.py`, préfixe `PJ:`, entonnoir lieu → réaction, huit cas de test chacun, parité `test_spec_l3`.
6. L5 J2 : B-BOUEE, les quatre TP de range, `prix_touche_1min`.
7. `DECISIONS.md` (un par setup activé, date, attendu) ; `LECTURE_JOUR_61.md` : « confirmations avec/sans, une par une ; TP de range lus par tranche de largeur ; bouée lue fade / continuation séparément ».

---

## 6. Ce que ce document ne fait pas
Il ne choisit pas les seuils (distributions), ne trie pas le post-it (les douze lignes y sont), et ne dit pas que Jackson a raison : il écrit ce qu'il faudrait voir — `PJ_RETOURNEMENT` positif avec `C_VOL` et nul sans ; les ranges étroits payés au VPOC et les larges au bord ; la première cassure qui échoue plus souvent qu'elle réussit ; la bouée suivie d'une descente. Le jour 61 dira lesquelles de ces lignes sont des règles et lesquelles des souvenirs.
