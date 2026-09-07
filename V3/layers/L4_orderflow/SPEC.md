# L4 — LA CONFIRMATION ORDER FLOW

*Spécification v1.0 — 07/09/2026 — Fable. Déposée telle quelle : le dépôt est
la mémoire, pas la conversation. Les résultats de J1 (relecture des formules,
distributions, reformulation de V3) sont dans `seuils.yaml` — ils amendent
cette spec sans la réécrire.*

---

## 1. Rôle, place, frontières

**Question unique.** *Au moment d'entrer, le flux confirme-t-il ce que le
déclencheur a vu — ou le contredit-il ?*

**Place.** Entre L3 (le prix a réagi à un endroit, jugé à la clôture de la
barre 15 min `t`) et L5 (taille, barrière). L3 dit *quoi* et *où* ; L4 dit
*maintenant ou pas*.

**Ce que L4 fait.** Elle regarde les **premières barres 1 min de `t+1`** — la
fenêtre de confirmation, `k` barres dans `seuils.yaml` — et rend `CONFIRME` /
`VETO(motif)` / `None`. Elle lit le flux, pas le prix. C'est ce qu'un desk
fait au moment de cliquer : il ne clique pas sur la clôture de la 15 min, il
regarde le carnet et le tape pendant deux minutes.

**Ce que L4 ne fait pas.**
- Elle ne cherche pas de trade (L3), ne lit pas le contexte (REG, L1), ne
  dimensionne pas (L5).
- Elle ne compte pas : « au moins 2 sur 4 » est une somme, donc un score.
  **Des vetos en série**, chacun avec un seul droit — annuler.
- Elle ne bloque rien pendant l'ombre : chaque veto journalise « aurait
  bloqué », le signal vetoé est simulé en fantôme.
- Elle ne lit pas une colonne dont la formule est inconnue.

**Le coût qu'elle introduit.** Attendre la confirmation retarde l'entrée : le
prix d'entrée n'est plus l'ouverture de `t+1` mais la clôture de la barre de
confirmation. Ce **glissement** est une grandeur mesurée dès le début — L4
passe si `séparation × taux_veto > glissement`, sinon elle coûte plus qu'elle
ne filtre. `k` est choisi sur cette mesure, écrit, jamais retouché en ombre.

---

## 2. Entrées — 1 min, noyau v2, provenance vérifiée

Bloc `l4` de `lecture.py`, construit sur les `k` premières barres 1 min de
`t+1`, jamais au-delà de la barre de confirmation (test anti-fuite, §7).

- **Agression (F13)** : `ask_pct_k` / `bid_pct_k` volume-pondérés sur la
  fenêtre (A), `delta_k` = Σ delta / volume de la fenêtre (A), `cvd_sess_r`
  (recalc).
- **Forme (F19)** : `finish_k` (dernière barre de la fenêtre),
  `meche_contre_k` **recalculée depuis OHLC** — la colonne du dumper est une
  part du PRIX, pas du range (mesuré 07/09), `momentum_k`.
- **Gros ordres (F16)** : `big_contre_k` = `max_big_*_vol_in_bar` sur la
  fenêtre, côté opposé. `dist_big_*_nearest` est en provenance **C** —
  **V3 reformulé** : un print ≥ `g1` dans la fenêtre est à portée par
  construction (1 à 3 minutes).
- **Épuisement (F14)** : formules héritées relues le 07/09 et
  **disqualifiées** (climax = |vol_z|>1 déclenche 30 % des barres ;
  absorption = |delta|>30 contrats partagé ES/NQ). **Recalcul** : volume ≥ p99
  ET range ≥ p95 ET finish contraire, par instrument.
- **BN (F18)** : information journalisée, jamais lue par un veto ce cycle.
- **Interdits** : `rvol`, `rvol_zscore`, `cvd_day`, tout `ctx_*` non relu,
  toute somme de composantes.

---

## 3. Les vetos — série, un seul droit : annuler

`(lec_l4, side, s) → True | False | None`. `None` → `TROU_V*`, journalisé ; en
live strict, un trou **ne bloque pas** (L4 n'est pas une porte de sécurité)
mais marque `confirmation = indisponible`.

| id | nom | règle (LONG ; SHORT en miroir) |
|---|---|---|
| **V1** | personne n'achète | `ask_pct_k < a1` |
| **V2** | le flux pousse contre | `delta_k < −d1` |
| **V3** | print adverse pendant la confirmation | `big_contre_k ≥ g1` (par instrument) |
| **V4** | épuisement dans le sens | recalcul : volume p99 ET range p95 ET finish contraire |
| **V5** | la réaction se renie | finish faible OU mèche contraire (seuils à re-poser, cf `seuils.yaml`) |

Série V1 → V5 : le premier veto vrai donne le **motif** ; **tous** sont évalués
et journalisés (indépendance, comme L0 — sinon l'attribution est faussée par
l'ordre). L'absorption est `info` ; un test interdit qu'elle change la
décision. Un veto n'a que le droit d'annuler ; rien n'a le droit de renforcer.

---

## 4. Sortie

```
{ decision: CONFIRME | VETO | INDISPONIBLE,
  motif, vetos: {V1..V5: bool|None},
  barres_confirmation, prix_entree_l4, glissement_atr,
  info: {absorption_sens, bn_alignees, cvd_sess_r} }
```

Journalisée sur chaque signal L3 — et sur `MANUEL` : le seul endroit où « je
n'ai pas cliqué parce que le carnet disait non » devient un chiffre.

---

## 5. Mesure — ce qui fait passer L4

Sur les 57 jours, avec `stats.py` (bloc semaine, apparié, hasard 1 000
tirages). **Attendu écrit avant** : taux de veto 20–40 % ; devenir des vetoés
≤ retenus ; au moins deux vetos sur cinq dans le bruit.

| mesure | passage |
|---|---|
| taux de veto, global et par veto | hors [10 %, 50 %] global = inerte ou étrangleuse |
| séparation retenus / vetoés | IC exclut zéro ; contrôle (veto aléatoire au même taux) le contient |
| avec/sans par veto | un veto qui ne déplace pas la séparation reste observé |
| **glissement** | lu contre le gain : L4 passe si `séparation × taux_veto > glissement` |
| fantômes | ce que bloquer aurait coûté ou épargné |
| par déclencheur | jamais agrégé sans le détail — un veto peut servir un fade et nuire à un momentum |

`k` mesuré à 1, 2, 3 — une valeur choisie avant l'ombre, écrite dans
`DECISIONS.md`, jamais retouchée pendant.

**Verdicts par veto** : *filtre* (appliqué au cycle 2) · *muet* (observé) ·
*nuit* (retiré, **jamais inversé**). ~30 comparaisons affichées ; ES/NQ
comptent pour un.

---

## 6. Seuils

`seuils.yaml` — mesurés le 07/09, chaque seuil porte son origine. Un `null` en
mode `appliquee` refuse de tourner.

## 7. Tests

30 cas (3 par veto × LONG/SHORT en miroir) · série (un seul motif, cinq
booléens) · **anti-somme** (grep) · **anti-fuite** (modifier les barres 1 min
après la barre de confirmation ne change ni la décision ni `prix_entree_l4`) ·
glissement (LONG, open 100, confirmation 102, ATR 10 → +0,2) · **forme**
(signe opposé → verdict différent) · test au tick sur deux journées, trois
signaux lus à la main — un confirmé, un vetoé V2, un vetoé V3.

## 8. Risques, parade écrite

F14/F16 relues ou recalculées, sinon `absente` · `g1` par instrument, test
`g1_ES ≠ g1_NQ` — **validé par la mesure : rapport 7,6** · le glissement mange
le filtre → mesuré avant tout verdict · pas de score par la porte de service
(l'absorption est `info`) · fenêtre 1 min absente → `INDISPONIBLE`, entrée
comme sans L4, journalisé · 30 comparaisons → avertissement en bas du rapport.

## 9. Critère de scellement

1. Provenance vérifiée ; `verifier_colonnes` déclare le bloc `l4`.
2. Chaque seuil `null` a sa distribution datée, par instrument.
3. Test au tick sur deux journées, trois signaux à la main.
4. Mesure §5 avec contrôle négatif, glissement, par veto et par déclencheur.
5. `k` choisi et écrit dans `DECISIONS.md` avant le premier jour d'ombre.
6. Tests verts, garde-fou public, `STATUS.md` : une ligne par veto.

Après scellement, L4 tourne **observée** pendant l'ombre. Appliquée au
cycle 2, sur la lecture du jour 61.

## 10. NEXT_CYCLE

Confirmations positives comme modificateur de taille (L5, après 200 trades) ·
footprint par niveau de prix (même ligne C++ que le spread) · absorption lue
sur la fiche F23 du niveau (la défense *pendant* le test) · L4 pour la sortie
(un veto qui apparaît en position = signal de sortie, mesuré comme les
fantômes) · le journal `MANUEL`.

## 11. Ordre de travail

**J1 — fait le 07/09** : provenance → relecture des formules → distributions
par instrument → reformulation V3. Résultats dans `seuils.yaml`.

**J2** : `lecture.py` bloc `l4` + anti-fuite → `vetos.py` (cinq fonctions,
trois lignes) → `confirmation.py` (la série + glissement) →
`test_orderflow.py` → `mesure_57j.py` k = 1/2/3 → rapport → `k` et verdicts
dans `DECISIONS.md`.

Prérequis connus : H6/H8 à zéro signal — la première lecture portera sur H3 et
H7, écrit tel quel ; `rvol_r` / `cvd_sess_r` dans l'agrégation.
