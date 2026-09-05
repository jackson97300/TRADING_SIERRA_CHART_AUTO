# MISSION PHASE 2 — Y a-t-il un edge ? (v1.1 — brouillon à compléter par Jackson, puis figer)

> **Gouvernance** : ce fichier est commité UNE fois, daté, par Jackson. Après ce commit, aucune
> retouche : toute idée née en regardant les résultats va dans `NEXT_CYCLE.md`.
> Les champs `[À TRANCHER]` doivent être remplis avant le commit. Un champ vide bloque le runner.

Établi le 05/09/2026. Données : 51 jours exploitables (15/06 → 03/09), ES + NQ, cash uniquement,
noyau v1 = 122 features communes (`DATA/feature_reduction.json`), conventions = `CONVENTIONS.md` w1.

---

## 0. Ce que cette mission décide, et ce qu'elle ne décide pas

Elle répond à une question : **parmi dix hypothèses écrites avant de regarder les données, lesquelles
survivent à un protocole qui ne peut pas fabriquer d'edge ?** Elle ne cherche pas « ce qui aurait marché ».
Prior : cinq campagnes à zéro (0/26 zones, 0/64 stratégies, 0 feature prédictive, 3 bots NOGO).
Résultat attendu : zéro à deux survivantes, espérance modeste. **Zéro est un résultat, et un livrable.**

## 1. Prérequis bloquants (le runner refuse de tourner si l'un manque)

| # | Prérequis | État |
|---|---|---|
| 1 | Filtre `stable` + 10 journées en panne exclues + dédoublonnage `ts` (CONVENTIONS §4) | ✔ 5eb6eb9 |
| 2 | `recalc.py` validé 7/7, colonnes recalculées injectées, ligne `lecture` en place | ✔ 7affc05 |
| 3 | Noyau v1 figé | ✔ b50b278 |
| 3b | `window_version` **posée dans les données** (le §9 de CONVENTIONS la définit, rien ne l'écrit encore). En attendant le dumper : calculée au chargement — `w1` si `ts` ≥ 2026-09-06 21:00 UTC (première session après le changement de session times), `w0` avant. Le runner refuse un lot qui mélange w0 et w1 sur une colonne de session. | ☐ |
| 3c | Table des familles dans le dépôt : `config/families.yaml` (feature → F1…F23, source = tableau §1.3 de `ANALYSE_RIGOUREUSE_REDUCTION_ET_COUCHES.md`, **pas** le JSON Kimi qui contient des fuites). Le runner résout F3, F10, F11… par ce fichier. | ☐ |
| 4 | `direction()` C++ = Python, 0 mismatch sur 10 jours | ☐ — **bloque l'exécution live, pas la recherche sur l'historique** |
| 5 | Ce fichier commité, daté, sans `[À TRANCHER]` restant | ☐ |

## 2. Conventions d'exécution — fixées une fois

- **Fenêtre RTH** : 9h30 → `[À TRANCHER : 16:00 ou 16:15 ET]`.
  *Défaut proposé par Fable : **16:00.** C'est la borne de `is_in_us_cash` (13:30–20:00 UTC), de `recalc.CASH_FIN`, et du noyau (381 barres/jour). 16:15 est la clôture futures de Dalton, mais créerait un quart d'heure absent du noyau et de tous les checks. Choisir 16:00, et l'écrire une fois.*
- **Unité de décision** : barres **5 min** agrégées depuis la 1 min (flux = somme, états = dernier,
  extrêmes = max/min, ratios recalculés, `ctx_*` recalculés, ATR-5m recalculé). Alignées sur 9h30 ET.
- **Toute distance en ATR-5m**, jamais en ticks fixes. Toute feature du noyau lue via `lire(feature, df)`,
  qui applique la ligne `lecture` de `feature_reduction.json` — **jamais** une colonne `_atr` livrée lue directement.
- **Cible — triple barrière, unique pour les dix** : TP = +1,5 ATR-5m, SL = −1,0 ATR-5m, expiration = 20 barres
  de 5 min. Résultat par signal : +1 (TP d'abord), −1 (SL d'abord), 0 (expiré, P&L réel signé).
- **Coût par trade** : `[À TRANCHER]`. *Défaut proposé par Fable : modéliser le contrat que tu trades réellement en prop firm (MNQ/MES si c'est le cas — tick MNQ 0,50 $, MES 1,25 $), coût = commissions aller-retour réelles de ton compte + 1 tick de slippage par côté. Ordre de grandeur MNQ : ~2 $ de commissions + 1 $ de slippage ≈ 3 $ par aller-retour, soit ~6 % d'un ATR-5m de 25 points (12,50 $). Mets le chiffre réel de ton relevé, pas une estimation : c'est lui qui décide si +0,5 tick d'espérance est un edge ou une facture.*
- **Instant d'entrée** : la condition est évaluée sur la barre 5 min **clôturée** t ; l'entrée est à l'**ouverture de la barre t+1**. TP et SL sont posés par rapport au prix d'entrée, avec l'ATR-5m de la barre t. Aucune feature de la barre t+1 n'est lue avant l'entrée. (C'est la frontière entre backtest et look-ahead ; une barre de décalage, mais la seule qui compte.)
- **Signaux consécutifs** : un signal par **franchissement** (la condition passe de faux à vrai), jamais par barre où elle reste vraie. Et pas de nouveau signal de la même hypothèse tant que le précédent n'a pas atteint une barrière. Six barres consécutives de H3 = un signal.
- **Signaux simultanés** : deux hypothèses sur la même barre = deux signaux, comptés séparément, même en sens opposé. Pour le test elles sont indépendantes ; en live, c'est L3 (compte de confluence) qui tranchera — pas ici.
- **Espérance** : moyenne du **P&L réalisé en ATR-5m** — `(prix de sortie − prix d'entrée) × side / ATR-5m(t)` — nette de coûts. L'étiquette +1/−1/0 sert au WR, jamais au critère de survie : quand les expirations dominent, les deux signes divergent, et c'est le P&L qui paie.
- **Blocages appliqués à toutes les hypothèses, non testés** : `is_blocked_combined`, `is_eco_blocked`,
  `gamma_block_long/short`, ±5 min autour des news critiques, `data_quality_flag ≠ stable`.

## 3. Découpage — 51 jours

- **Recherche : jours 1–40. Scellés : jours 41–51.** Embargo d'**une journée** entre les deux (les niveaux
  « veille » du premier jour scellé regardent le dernier jour de recherche).
- Walk-forward dans les 40 : **5 blocs de 8 jours**. Paramètres calés sur un bloc, mesurés sur le suivant.
- Les 11 jours scellés ne sont ouverts qu'**une fois, à la fin, pour les survivantes uniquement**.
  Si zéro survivante, ils restent scellés pour le cycle suivant.

## 4. Biais L1 — regles de Jackson (decrete, non teste ; mesure avec / sans sur chaque hypothese)

Quatre regles, score de -3 a +4. Toutes les colonnes sont verifiees presentes et
classees A ou B au 05/09.

| # | Regle | Condition | Score | Colonne | Niveau |
|---|---|---|---|---|---|
| B1 | Cote de la reference hebdomadaire | `dist_vwap_w` < 0 (prix au-dessus de la VWAP semaine) | +1 / -1 | `dist_vwap_w` | **A** |
| B5 | Position vs valeur de la veille | ouverture au-dessus de `prev_vah_lvl` : +1 ; en dessous de `prev_val_lvl` : -1 ; dans la VA : 0 | +1 / -1 / 0 | `open_above_prev_vah`, `open_below_prev_val` | B |
| B5b | Acceptation de la valeur | prix hors VA veille depuis >= 3 barres 5 min, dans le sens de B5 | +1 si confirme | `inside_prev_va` | B |
| B4 | Accord intermarche | ES et NQ du meme cote de leur VWAP hebdo : +1 ; SMT contre le biais : -1 | +1 / -1 | `im_smt_divergence`, `dist_vwap_w` des deux | B |

**Decision** : score >= +2 -> long seul ; <= -2 -> short seul ; sinon les deux
sens a taille x0,5.

**Non-participation** — un filtre qui ne sait pas dire non n'est pas un filtre.
Aucun trade le jour ou : score dans {-1, 0, +1} **ET** `atr_14m` du jour depasse
1,8 fois sa mediane sur les 51 jours.  Un biais indetermine dans une volatilite
anormale n'est pas un jour a taille reduite, c'est un jour sans.

*Seuil mesure, pas choisi : `atr_14m` rapporte au prix a un ratio a sa mediane de
1,87 au p90 et 2,45 au p95. Le seuil 1,8 retient environ un jour sur dix.*

*Le VIX est ecarte de cette regle. `vix_regime` ne prend que deux valeurs, 0 et 1,
separant un VIX median de 14,56 d'un VIX median de 15,45 : c'est un seuil binaire
autour de 15, pas un regime, et il ne distingue rien d'extreme. `vix_level`
contient par ailleurs des valeurs nulles impossibles et sort en C pour desaccord
ES/NQ.*

**B5 est exclu du score pour H4 et H5.** Ces deux hypotheses se declenchent sur
les memes colonnes que B5 (`open_within_prev_va`, `prev_vah_lvl`) : mesurer
« H4 avec / sans L1 » en gardant B5 reviendrait a mesurer si une condition
s'aide elle-meme. Pour H4 et H5, le score L1 se calcule sur B1 + B5b + B4
seulement ; pour les huit autres, sur les quatre regles.

**B2 (structure des swings 4h) est reportee au cycle suivant.** Toutes ses
colonnes sont hors noyau pour une seule et meme raison — reinitialisation au
redemarrage : `dist_swing_high` saute a 14 fois sa derive quotidienne au boot,
`dist_swing_low` a 25 fois, `swing_range_ticks` a 10 fois, et
`bars_since_last_swing_high/low` ont 12 a 16 % de nulls. C'est le mecanisme de
`cvd_day` et `rvol` : une feature **a etat**, pas une feature fausse. Les swings
se recalculent depuis les OHLC comme la VWAP. Va dans `NEXT_CYCLE.md`, puis dans
`recalc.py`.

**B3 (POC composite) est abandonnee** : `dist_comp_20d_vpoc` et toute sa famille
sont vides a 99 % par jour sur les 51 jours. La source n'est pas alimentee.

## 5. Contexte L2 — régime observable (hypothèse, mesuré)

Quatre régimes, lus à 10h30 ET sur l'IB, le gamma et le profil ; chacun **autorise** des hypothèses :
- **TREND** (`ctx_ib_extension_ratio` > 1,5 OU `ctx_trend_day_score` haut ; gamma négatif) → H3, H6.
- **RANGE** (IB tenu, `mq_gamma_condition` positif, profil symétrique) → H1, H2, H4, H5.
- **DOUBLE / NEUTRE** (`is_double_dist`, POC migrant) → H7, H8, taille ×0,5.
- **INDÉTERMINÉ** (IB non formé, qualité dégradée) → rien, sauf H4/H5 en fenêtre IB.
Chaque hypothèse est mesurée **avec et sans** ce filtre.

## 6. Les dix hypothèses — FERMÉES

Règles d'écriture : une condition booléenne sur 2–4 features du noyau, en ATR-5m ; un side ; un créneau.
**Sur les niveaux lents, écrire sur le représentant du cluster** (`dist_prev_vwap_rth_r` des deux côtés), pas sur un
membre : sur NQ, PDH / VWAP hebdo / VA veille sont la même variable sur ces 51 jours, sur ES ce sont trois.
Une hypothèse dont toutes les features sont de niveau B le signale (`repose_sur_B = true`).

`[À TRANCHER — remplace ces dix par les tiennes, garde le nombre à dix. Celles-ci sont un brouillon déduit de ta stack.]`

*Avis de Fable sur les dix, pour t'aider à trancher :*
- *H1, H2, H4, H5, H6, H8 sont les plus solides : niveau A ou A+B, N probablement suffisant, et ce sont des setups que tu as déjà tradés (H1 est la logique de `gamma_wall_rejection_strategy.py`). Garde-les.*
- *H3 dépend du régime TREND : N sera faible sur 40 jours (peut-être 10 jours de tendance). Attends-toi à « non testable » — garde-la quand même, elle a un sens, et le statut le dira.*
- *H7 et H9 reposent uniquement sur du niveau B (`ctx_div_at_swing`, `bool_gex_flip_zone`). Ce n'est pas disqualifiant, mais si l'une survit, la première chose à faire sera de vérifier à la main ce que ces colonnes ont réellement déclenché.*
- ***H10 n'est pas testable ce cycle** : elle demande les scores de famille, qui n'existent pas encore. Remplace-la. Deux candidates issues de ta pratique : **« Retest de l'extrême de l'IB après cassure »** (Dalton : `ib_broken_up` puis retour à `dist_ib_high` ≤ 0,15 ATR avec `finish_delta_pct` > 0,6 → LONG, miroir) ; ou **« Battle Navale alignée sur un niveau »** (`bn_score_raw` > seuil ET distance à un niveau lent ≤ 0,2 ATR), si tu veux enfin mesurer BN dans un cadre propre.*
- *Ne cherche pas dix hypothèses « bonnes ». Cherche dix hypothèses que tu reconnaîtrais comme tiennes en relisant le tableau dans six mois.*

| # | Nom | Condition d'entrée (5 min) | Side | Créneau | Familles | Niveau |
|---|---|---|---|---|---|---|
| H1 | Rejet Call Wall | `dist_mq_call` ≤ 0,15 ATR ET `ask_pct` < 0,45 sur la barre | SHORT | après IB | F11, F13 | B + A |
| H2 | Rejet Put Wall | miroir de H1 (`dist_mq_put`, `bid_pct`) | LONG | après IB | F11, F13 | B + A |
| H3 | Retour VWAP en tendance | régime TREND ET `dist_vwap_rth_r` ∈ [−0,3 ; 0] ATR ET `cvd_day` du côté de la tendance | sens de la tendance | 10h30–15h ET | F10, F13 | A |
| H4 | Sortie de VA veille | `open_within_prev_va` ET 1ʳᵉ clôture 5 m > `prev_vah_lvl` ET `delta_bar` > 0 (miroir) | LONG / SHORT | IB | F3, F13 | A |
| H5 | Échec de retour en VA | `open_outside_prev_range` ET retest de `dist_prev_vwap_rth_r` ≤ 0,2 ATR avec `ctx_failed_auction` | sens de l'ouverture | IB + 1 h | F3, F21 | A + B |
| H6 | Cassure IB avec volume | `ib_broken_up` ET `rvol` > 1,5 ET `ctx_absorption_score_5` bas (miroir) | LONG / SHORT | 10h30–12h ET | F5, F7, F14 | A + B |
| H7 | Divergence delta au swing | `ctx_div_at_swing` ET `delta_div_buy_clean` ET `dist_session_lvn_below` ≤ 0,2 ATR (miroir) | LONG / SHORT | après IB | F15, F6 | B |
| H8 | Sweep + reprise | `sweep_low_this_bar` ET clôture > `sess_low` + 0,2 ATR ET `finish_delta_pct` > 0,6 (miroir) | LONG / SHORT | toute la session cash | F17, F19 | A + B |
| H9 | Gamma flip aligné | `bool_gex_flip_zone` ET `vwap_slope_10_dir` aligné | sens de la pente | après IB | F8, F10 | B |
| H10 | Confluence 3 familles | scores « niveaux » + « agressivité » + « absorption » tous > 0,7 dans le même sens (nécessite les scores de famille) | ce sens | après IB | F10, F13, F14 | mixte |

## 7. Ce que le runner mesure, à l'aveugle

Le runner calcule signaux et triple barrière pour les dix, ES et NQ, sur les 40 jours, **sans afficher de résultat
intermédiaire**. Le tableau de survie s'affiche une fois, complet. Pour chaque hypothèse × instrument :
N signaux, espérance nette (ATR et $), WR, distribution par jour, courbe walk-forward (5 blocs), sensibilité
±30 % sur chaque seuil, et les quatre variantes : brute / avec L1 / avec L2 / avec L1+L2.

## 8. Critères de survie — une hypothèse survit si TOUT est vrai

- N ≥ 40 signaux sur les 40 jours, **sur chaque instrument** (sinon statut « non testable sur ce lot », pas « meurt »).
- Espérance nette > 0 en ATR **sur ES ET sur NQ**, séparément.
- ≥ 5 jours distincts ; aucun jour ne porte > 60 % du gain.
- Walk-forward positif sur ≥ 4 des 5 blocs.
- Bootstrap **par jour** (blocs = journées entières, jamais par barre), p < 0,05 / 10.
- Robuste : ±30 % sur chaque seuil ne change pas le signe.
Puis, et seulement pour les survivantes : lecture unique des jours 41–51, comparée aux 40.

**Lecture du critère statistique — à ne pas confondre.** p < 0,05/10 sur 40 journées indépendantes est très exigeant : peu d'hypothèses réelles l'atteindront sur ce lot, et c'est voulu. Le tableau distingue donc trois sorties, pas deux :
- **SURVIT** : tous les critères.
- **MEURT** : espérance ≤ 0 sur un instrument, ou concentration, ou flip de signe, ou sensibilité.
- **CANDIDATE** : espérance > 0 sur ES **et** NQ, ≥ 4/5 blocs, robuste — mais p au-dessus du seuil. Ne s'exécute pas ; passe en **mode ombre** le cycle suivant, où N s'accumule sans coût. C'est la seule voie par laquelle un critère exigeant ne tue pas un vrai edge trop rare pour 40 jours.

## 9. Livrables

- Tableau de survie : par hypothèse, SURVIT / MEURT / NON TESTABLE, et **comment** elle meurt (N, concentration,
  flip de signe ES/NQ, bloc négatif, sensibilité).
- Effet de L1 et L2 : pour chaque hypothèse, espérance avec / sans — c'est ce qui décide si le biais devient porte,
  modificateur de taille, ou disparaît.
- Résultat sur 41–51 pour les survivantes.
- `NEXT_CYCLE.md` : hypothèses apparues pendant l'analyse, NON testées.
- Ce que la méthode NE dit PAS.

## 9b. Le commit
Par Jackson, une fois les cases remplies : `git tag mission-phase2-v1` sur le commit, message « MISSION PHASE 2 v1 — hypothèses figées le <date> ». Le runner vérifie que le tag existe et que le fichier n'a pas changé depuis (hash) avant de tourner. Après ce tag, `NEXT_CYCLE.md`.

## 10. Règle de franchise
Si zéro survit, c'est le résultat attendu et c'est un livrable. Aucun critère n'est assoupli pour en faire passer une.
Aucun seuil n'est retouché après avoir vu un résultat. Ce qui vient après un résultat va dans `NEXT_CYCLE.md`.
