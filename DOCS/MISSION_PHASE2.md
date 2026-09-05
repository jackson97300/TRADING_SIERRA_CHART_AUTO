# MISSION PHASE 2 — Y a-t-il un edge ? (v1.2 — cases 1 a 4 tranchees le 06/09 ; le tag attend le GO)

> **Gouvernance** : ce fichier est commité UNE fois, daté, par Jackson. Après ce commit, aucune
> retouche : toute idée née en regardant les résultats va dans `NEXT_CYCLE.md`.
> Les champs `[À TRANCHER]` doivent être remplis avant le commit. Un champ vide bloque le runner.

Etabli le 05/09/2026, cases tranchees le 06/09. Donnees : **57 jours de seance** (10/06 -> 04/09),
source unique `DATA/live_enriched/sierra/`, ES + NQ, cash uniquement,
noyau v1 = 122 features communes (`DATA/feature_reduction.json`), conventions = `CONVENTIONS.md` w1.

---

## 0. Ce que cette mission décide, et ce qu'elle ne décide pas

Elle répond à une question : **parmi six hypotheses ecrites avant de regarder les donnees, lesquelles
survivent à un protocole qui ne peut pas fabriquer d'edge ?** Elle ne cherche pas « ce qui aurait marché ».
Prior : cinq campagnes à zéro (0/26 zones, 0/64 stratégies, 0 feature prédictive, 3 bots NOGO).
Résultat attendu : zéro à deux survivantes, espérance modeste. **Zéro est un résultat, et un livrable.**

**Survivantes attendues, ecrit avant de lancer : 0 a 2.** Si le runner en rend six, ce n'est pas une
bonne nouvelle : c'est un critere qui fuit quelque part. Pre-enregistrer l'attendu est ce qui distingue
une recherche d'une peche.

**Ce cycle elimine.** Une CANDIDATE passe en ombre. Une hypothese qui SURVIT sur 40 jours est traitee
en CANDIDATE jusqu'a 60 jours d'ombre : aucune n'est executee en reel a l'issue de ce cycle.

**Source de verite unique : `DATA/live_enriched/sierra/`, fenetre w1 controlee par L6.** Aucune donnee
externe n'entre dans une mesure. Databento est abandonne : ni ses datasets, ni les verdicts qui en
viennent (batterie V5 du 27/04) ne sont admis comme argument, de selection comme d'exclusion.

**Donnees COLLECTEES uniquement — regle Jackson du 06/09.** N'entre dans une mesure que ce qui a ete
**collecte** et se trouve dans le fichier : le JSONL Sierra (`DATA/live_enriched/sierra/`) et le dump
Sierra des niveaux MenthorQ (`DATA/mq_levels/`, schema `mq_levels_1.0` : `mq_call`, `mq_put`,
`mq_hvl`, `mq_*_0dte`, `mq_1d_min/max`, `mq_gex[10]`, `mq_blind[10]`). Sont **exclus** :
- toute colonne **reconstruite par proxy**, meme documentee — au premier chef
  `mq_gamma_condition`, qui n'est pas dans le dump Sierra (il ne porte pas `net_gex`) et que
  `enricher_chain.py:283` reconstruit depuis `bool_gex_flip_zone` depuis que le scraper est tombe
  le 27/05 ;
- toute colonne issue du **scraper MenthorQ** (`net_gex`, `total_gex`, `iv_30d`, CTA), mort depuis
  le 27/05 et nul dans les fichiers (verifie sur le JSON du 14/06) ;
- toute donnee externe, Databento compris.

Motif : un proxy se comporte comme la donnee qu'il remplace juste assez pour qu'on l'oublie, et
jamais assez pour qu'on puisse conclure. Une hypothese conditionnee a un proxy ne mesure pas ce
qu'elle croit mesurer.

**Derivee n'est pas proxy — la distinction qui rend la regle applicable.** Un **proxy** remplace une
donnee absente par une autre grandeur (`mq_gamma_condition` reconstruit depuis `bool_gex_flip_zone`
parce que `net_gex` n'existe plus) : il est **exclu**. Une colonne **derivee** applique une formule a
une donnee presente (`ib_broken_up`, `sweep_*_this_bar`, `open_within_prev_va`, `rule_80pct`,
`bar_upper_wick_pct` calcules par le dumper depuis l'OHLCV ; `rvol_r`, `cvd_sess_r`, les bandes
VWAP-SD par `recalc.py`) : elle est **admise**, qu'elle vienne du C++ ou de Python. Sans cette
distinction, la regle exclurait tout le niveau B et il ne resterait aucune hypothese.

**Crible proxy passe sur les six le 06/09.** Recherche des chemins `proxy`, `fallback`, `default`
dans `enricher_chain.py` et `DMP_Transform.h` pour chaque colonne des six hypotheses :
- **Aucun proxy** sur les colonnes des six. Les deux autres proxys de l'enricher
  (`diag_imbalance_ofi_proxy` l.511, `large_trader_max_size_proxy` l.516) ne sont lus par aucune.
- Les `= 0.0f` de `DMP_Transform.h:1355-1390` sont des **initialisations** ecrasees par les modules
  de calcul, pas des substitutions.
- **Deux fallbacks inventent une valeur** : `f.day_type = 2.0f` (« NormVar = le type le plus frequent
  (42 %) ») et **`f.rvol = 1.0f` (« Normal par defaut »)** quand le ring buffer n'est pas pret. Le
  second concernait H8 : elle lit **`rvol_r`**, le recalcul de `recalc.py`, et non `rvol`. Le
  recalcul de P1 la protege deja — c'est retrospectivement sa justification principale.
- `rule_80pct` est initialise a 0 (= inactif). C'est un defaut **conservateur** : il peut faire
  manquer un signal a H4, jamais en inventer un.

**Cout par trade : MNQ 2,82 $ / MES 4,32 $** (Tradeify, le plus eleve des trois prop firms verifiees,
plus 1 tick de slippage par cote), soit **~ 0,23 / 0,14 ATR-5m**. C'est la barre. Sur micro, un setup
neutre avant frais perd ~0,2 ATR par trade. Elle ne bouge pas apres lecture des resultats.

## 1. Prérequis bloquants (le runner refuse de tourner si l'un manque)

| # | Prérequis | État |
|---|---|---|
| 1 | Filtre `stable` + 10 journées en panne exclues + dédoublonnage `ts` (CONVENTIONS §4) | ✔ 5eb6eb9 |
| 2 | `recalc.py` validé 7/7, colonnes recalculées injectées, ligne `lecture` en place | ✔ 7affc05 |
| 3 | Noyau v1 figé | ✔ b50b278 |
| 3b | `window_version` **posée dans les données** (le §9 de CONVENTIONS la définit, rien ne l'écrit encore). En attendant le dumper : calculée au chargement — `w1` si `ts` ≥ 2026-09-06 21:00 UTC (première session après le changement de session times), `w0` avant. Le runner refuse un lot qui mélange w0 et w1 sur une colonne de session. | ☐ |
| 3c | Table des familles dans le dépôt : `config/families.yaml` (feature → F1…F23, source = tableau §1.3 de `ANALYSE_RIGOUREUSE_REDUCTION_ET_COUCHES.md`, **pas** le JSON Kimi qui contient des fuites). Le runner résout F3, F10, F11… par ce fichier. | ☐ |
| 3d | Le runner LIT DOCS/features_stale.csv et exclut les couples (colonne, jour) suspects pour toute hypothese qui lit la colonne concernee. 1 080 couples sur 18 jours ; 63 colonnes du noyau touchees, dont deux au-dela de 10 jours : cvd_day (19 j) et rvol (12 j). Consequence : H3 et H6 perdent pres de la moitie de l echantillon si ces deux colonnes ne sont pas recalculees (cvd_sess_r, rvol_r). | [ ] |
| 4 | `direction()` C++ = Python, 0 mismatch sur 10 jours | ☐ — **bloque l'exécution live, pas la recherche sur l'historique** |
| 5 | Ce fichier commite, date, sans `[A TRANCHER]` restant | ✔ cases 1 a 4 tranchees le 06/09 — reste le GO |

## 2. Conventions d'exécution — fixées une fois

- **Fenetre RTH** : 9h30 -> **16:00 ET** (20:00 UTC en ete, 21:00 en hiver). **DECIDE 06/09.**
  Motif : c'est la borne de `is_in_us_cash`, de `recalc.CASH_FIN`, du noyau (381 barres/jour) et de
  tous les checks. 16:15 est la cloture futures de Dalton, mais creerait un quart d'heure que rien
  ne couvre.
- **Unité de décision** : barres **5 min** agrégées depuis la 1 min (flux = somme, états = dernier,
  extrêmes = max/min, ratios recalculés, `ctx_*` recalculés, ATR-5m recalculé). Alignées sur 9h30 ET.
- **Toute distance en ATR-5m**, jamais en ticks fixes. Toute feature du noyau lue via `lire(feature, df)`,
  qui applique la ligne `lecture` de `feature_reduction.json` — **jamais** une colonne `_atr` livrée lue directement.
- **Cible — triple barrière, unique pour les dix** : TP = +1,5 ATR-5m, SL = −1,0 ATR-5m, expiration = 20 barres
  de 5 min. Résultat par signal : +1 (TP d'abord), −1 (SL d'abord), 0 (expiré, P&L réel signé).
- **Cout par trade** : **DECIDE 06/09.** Contrats modelises = **les micros, MNQ et MES**.
  Commissions de reference = **Tradeify**, le plus eleve des trois prop firms verifiees le 06/09
  (Topstep 1,22 $ / Tradeify 1,82 $ / Lucid 1,00 $ aller-retour par micro) : un edge qui survit a des
  frais surestimes existe, l'inverse n'est pas garanti. Slippage = **1 tick par cote**.
  **MNQ : 1,82 + 1,00 = 2,82 $ ~ 0,23 ATR-5m. MES : 1,82 + 2,50 = 4,32 $ ~ 0,14 ATR-5m.**
  Le runner convertit en ATR-5m **a chaque trade avec l'ATR du jour**, jamais par une constante.
  Consequence ecrite d'avance : la commission d'un micro vaut ~1/3 de celle d'un mini pour 1/10 de
  l'exposition, donc les micros paient 3x plus de frais par unite de risque. Sur MNQ, le cout vaut
  15 % du TP et 23 % du SL.
- **Instant d'entrée** : la condition est évaluée sur la barre 5 min **clôturée** t ; l'entrée est à l'**ouverture de la barre t+1**. TP et SL sont posés par rapport au prix d'entrée, avec l'ATR-5m de la barre t. Aucune feature de la barre t+1 n'est lue avant l'entrée. (C'est la frontière entre backtest et look-ahead ; une barre de décalage, mais la seule qui compte.)
- **Signaux consécutifs** : un signal par **franchissement** (la condition passe de faux à vrai), jamais par barre où elle reste vraie. Et pas de nouveau signal de la même hypothèse tant que le précédent n'a pas atteint une barrière. Six barres consécutives de H3 = un signal.
- **Signaux simultanés** : deux hypothèses sur la même barre = deux signaux, comptés séparément, même en sens opposé. Pour le test elles sont indépendantes ; en live, c'est L3 (compte de confluence) qui tranchera — pas ici.
- **Espérance** : moyenne du **P&L réalisé en ATR-5m** — `(prix de sortie − prix d'entrée) × side / ATR-5m(t)` — nette de coûts. L'étiquette +1/−1/0 sert au WR, jamais au critère de survie : quand les expirations dominent, les deux signes divergent, et c'est le P&L qui paie.
- **Blocages appliqués à toutes les hypothèses, non testés** : `is_blocked_combined`, `is_eco_blocked`,
  `gamma_block_long/short`, ±5 min autour des news critiques, `data_quality_flag ≠ stable`.

## 3. Decoupage — 57 jours

- **Recherche : jours 1-40. Embargo : 1 journee. Scelles : jours 42-57 (16 jours).**
  Les 40 jours de recherche sont conserves tels quels : tous les criteres du §8 sont ecrits sur ce
  nombre (N >= 40, 5 blocs de 8). Les six jours gagnes par le comptage correct vont aux scelles, qui
  passent de 11 a 16. La validation finale y gagne, la recherche n'y perd rien.
- Walk-forward dans les 40 : **5 blocs de 8 jours**. Parametres cales sur un bloc, mesures sur le suivant.
- Les 16 jours scelles ne sont ouverts qu'**une fois, a la fin, pour les survivantes uniquement**.
  Si zero survivante, ils restent scelles pour le cycle suivant.
- Volumetrie mesuree le 05/09 sur les barres `stable` **distinctes par minute** : lundi-jeudi 1379,
  vendredi 1259/1260 (seance courte, attendu), dimanche 119 (ouverture du soir, exclue).
  ~76 000 barres par instrument. Detail : `CONVENTIONS.md` §4.1.

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

**B5 est exclu du score pour H4.** Cette hypothese se declenche sur les memes
colonnes que B5 (`open_within_prev_va`, `prev_vah_lvl`) : mesurer « H4 avec /
sans L1 » en gardant B5 reviendrait a mesurer si une condition s'aide elle-meme.
Pour H4, le score L1 se calcule sur B1 + B5b + B4 seulement ; pour les six
autres, sur les quatre regles. (H5 etait l'autre cas concerne : elle est
retiree, cf §6.)

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

### DECIDE 06/09 — biais L1

Retenu tel qu'ecrit : B1 (cote de `dist_vwap_w`), B5 (ouverture vs VA veille), B5b (acceptation
>= 3 barres), B4 (accord ES/NQ). Decision a **+/-2**. **B5 est exclu du score pour H4** (son lieu
est deja l'ouverture vs VA veille : l'y compter reviendrait a compter deux fois la meme
observation).

**Non-participation** si `vix_regime` vaut un code extreme **OU** `atr_14m_hnorm` > 1,8, **ET**
score dans {-1, 0, +1}.

**Codes `vix_regime`, lus dans le C++ le 06/09** — `CPP/MIA_REFACTORED/DUMPER/13/DMP_Transform.h`
lignes 684-689, recopies tels quels, jamais un adjectif :

```
0 = calme     VIX < 15
1 = normal    15 <= VIX <= 25
2 = volatile  VIX > 25
3 = extreme   VIX > 35
```

Codes extremes retenus : **{2, 3}**.

**Mesure a inscrire avant de lancer** : sur les 57 jours, `vix_regime` ne prend que les valeurs
**0 (10 578 barres) et 1 (69 711 barres)** sur ES. Le VIX plafonne a **22,01**, sous le seuil 25.
Les codes 2 et 3 ont **zero occurrence**. La clause VIX est donc **structurellement inactive sur ce
lot** : en pratique, `atr_14m_hnorm` > 1,8 porte seul la non-participation. Ce n'est pas un defaut de
la regle, c'est une propriete de la periode (un ete sans episode de volatilite) : elle est ecrite
pour que personne ne croie plus tard qu'une garde VIX a protege quoi que ce soit ici.

Verification annexe : `vix_level` est absent ou nul sur **7 barres sur 80 296** (0,0 %), et les
bornes des regimes correspondent exactement (0 -> 13,80-15,00 ; 1 -> 15,01-22,01). Le fallback
`vix_regime = 1.0f` de la ligne 689 ne masque donc aucun trou sur ce lot.


## 5. Contexte L2 — regime observable (hypothese, mesure)

Quatre regimes, lus a 10h30 ET sur l'IB, le gamma et le profil ; chacun **autorise** des hypotheses.
Correspondance de vocabulaire, pour qu'il n'y en ait qu'un : **ROTATION = RANGE**, **BREAKOUT =
TREND**, **REVERSAL** se lit sur DOUBLE / NEUTRE.

- **TREND / BREAKOUT** (`ctx_ib_extension_ratio` > 1,5 OU `ctx_trend_day_score` haut ; gamma negatif)
  -> H6.
- **RANGE / ROTATION** (IB tenu, profil symetrique, `ib_range_atr` < 0,8) -> H2, H3, H8.
  La lecture du gamma est retiree de la definition du regime : elle reposait sur un proxy.
- **DOUBLE / NEUTRE / REVERSAL** (`is_double_dist`, POC migrant) -> H7, H8, taille x0,5.
- **INDETERMINE** (IB non forme, qualite degradee) -> rien. H7 est explicitement exclue de ce regime.
- **H4 est mesuree sans L2** : elle definit le regime, elle n'en depend pas.

Chaque hypothese est mesuree **avec et sans** ce filtre.

**A verifier avant de lancer, pas apres** : que les quatre regimes soient calculables avec des
colonnes A/B du noyau (`va_position_pct` est en C, `ctx_ib_extension_ratio` depend de la fenetre) et
qu'ils soient assez peuples sur 57 jours pour etre compares. Un regime a moins de 5 journees rend la
comparaison avec/sans L2 ininterpretable, et doit etre annonce comme tel.

## 6. Les hypotheses — FERMEES (six, apres retrait de H5 et H1)

Regles d'ecriture appliquees : **lieu + reaction** (une position n'est jamais un signal) ; seuils en
ATR-5m ; colonnes du noyau uniquement ; entree a l'ouverture de t+1 (t+2 pour H7) ; un signal par
franchissement, remise a zero a la frontiere de journee. Aucune reference a la batterie V5, dont les
verdicts sont disqualifies (source abandonnee, cinq features fausses, filtre de regime inactif).

**H5 (open drive qui echoue) est RETIREE — decision Jackson, 06/09.** Motif mesure : `game_changers.py`
lignes 50-51 definit `ODF_UP = 10` et `ODF_DOWN = 11` ; sur les 160 000 barres stable ES + NQ des 57
jours, `open_type` ne prend jamais ces valeurs (observees : 0 a 9). L'hypothese aurait rendu N = 0,
c'est-a-dire le resultat exact d'un runner casse. La numerotation garde un trou en H5 : renumeroter
ferait diverger toutes les references deja ecrites.

**H1 (rejet de mur gamma) est RETIREE — decision Jackson, 06/09.** Deux motifs independants, chacun
suffisant :
1. **Sa condition de regime est un proxy.** `mq_gamma_condition` n'est pas dans le dump Sierra
   (`mq_levels_1.0` ne porte pas `net_gex`) : `enricher_chain.py:283` la reconstruit depuis
   `bool_gex_flip_zone` depuis la chute du scraper le 27/05. La regle « donnees collectees
   uniquement » l'exclut.
2. **Son lieu est inatteignable.** `dist_mq_call` mediane 338 ticks = 84 points ; 0,16 % des barres
   a moins de 0,25 ATR-5m, 0,43 % a 0,50 ATR. Desserrer le seuil n'y change rien : le prix
   n'approche pas ce niveau sur ce lot.

Les **niveaux** MenthorQ eux-memes restent admis — ils sont collectes par le study Sierra et vivants
(`mq_call` = 7 400 en mai avec ES a 7 350 ; 7 700 / 7 750 / 7 800 en aout-septembre avec ES a 7 700),
et fixes intra-journee. C'est la condition de **gamma** qui est interdite, pas les distances aux murs.
H8 peut donc continuer de lire F11 comme lieu.

**H2 perd sa clause gamma** pour la meme raison, et garde `ib_range_atr` < 0,8 comme seule condition
de regime. La consequence est ecrite d'avance : le rationnel de retour a la moyenne (les dealers
long gamma vendent les hausses) n'est plus verifie par la donnee, seulement suppose. Si H2 survit,
c'est la premiere chose a reprendre.

**Bonferroni passe donc a 0,05 / 6.**

| # | Nom | Regime L2 | LIEU (barre 5 min t) | REACTION (barre t) | Side | Colonnes (niveau) |
|---|---|---|---|---|---|---|
| **H2** | Fade des bandes VWAP-SD2 avec rejet | ROTATION, `ib_range_atr` < 0,8 (**clause gamma retiree** : proxy) | `dist_vwap_rth_sd2u_r` dans [-P15 ; +P10] (short) / `dist_vwap_rth_sd2d_r` dans [-P10 ; +P15] (long), avec P10 = `max(0,10 ATR, 2 t)` et P15 = `max(0,15 ATR, 3 t)` | `delta_bar` < 0 ET `finish_delta_pct` < 0,4 (short) ; miroir (long) | SHORT / LONG | bandes recalculees par `recalc.vwap_bandes(..., n_sd=2.0)` (A), `delta_bar` (A), `finish_delta_pct` (A), `ib_range_atr` (B) |
| **H3** | Rejet a l'extreme de la VA courante | ROTATION | `dist_cur_vah` dans +/- `max(0,10 ATR, 2 t)` (short) / `dist_cur_val` (long) | barre t sort de la VA (high > VAH) ET cloture < VAH ET `finish_delta_pct` < 0,4 ; miroir | SHORT / LONG | `dist_cur_vah/val` (A), `inside_cur_va` (A), `finish_delta_pct` (A) |
| **H4** | Regle des 80 % (Dalton) | definit le regime — mesuree sans L2 | ouverture cash hors VA veille puis retour : cloture 5 min dans [`prev_val_lvl` ; `prev_vah_lvl`] | maintien dans la VA pendant **6 barres 5 min consecutives** (= 2 x 30 min) | sens de la traversee | `open_within_prev_va` (B), `open_outside_prev_range` (B), `prev_vah/val_lvl` (N), `rule_80pct` (B, en information) |
| **H6** | Retest de l'IB apres cassure acceptee | BREAKOUT, `ib_range_atr` < 0,4 | `ib_broken_up` = 1 ET `dist_ib_high` dans [-`max(0,15 ATR, 3 t)` ; +`max(0,05 ATR, 1 t)`] ; miroir bas | cloture 5 min au-dessus de l'IB high ET `finish_delta_pct` > 0,6 ; miroir | LONG / SHORT | `ib_broken_up/dn` (B), `dist_ib_high/low` (A), `finish_delta_pct` (A), `ib_range_atr` (B) |
| **H7** | Sweep de liquidite + reclaim N+1 | tous, **sauf INDETERMINE** | `sweep_low_this_bar` = 1 **et** le low de t depasse un niveau de reference (`dist_ovn_low`, `dist_pdl`, `dist_ib_low`) de >= `max(0,10 ATR, 2 t)` ; miroir haut | cloture de t+1 au-dessus du low de t (**decision evaluee a la cloture de t+1, entree a l'ouverture de t+2**) | LONG / SHORT | `sweep_high/low_this_bar` (B), `dist_ovn_high/low` (A), `dist_pdh/pdl` (A), `dist_ib_high/low` (A) |
| **H8** | Absorption a un niveau | ROTATION / REVERSAL | <= `max(0,20 ATR, 4 t)` d'un niveau de F3/F10/F11/F12 (VA veille ou courante, mur, PDH/PDL, ONH/ONL) | `rvol_r` >= 2,0 ET `delta_pct` <= -0,30 (long) / >= +0,30 (short) ET `finish_delta_pct` contraire au delta (> 0,6 long / < 0,4 short) | LONG / SHORT | `rvol_r` (A, recalcule), `delta_pct` (A), `finish_delta_pct` (A), distances (A/B) |

**H9 et H10 restent vides.** Aucun trade manuel avec trois occurrences nommees n'a ete fourni. Si
Jackson en nomme un avant le tag, il devient H9 et le seuil repasse a /7.

**Sorti de la liste, avec le motif** — rejet baissier Bot 4 v2 (C3) : sa condition reelle
(`distance_atr <= 1,5`, et `range_pos` qui est en C) est un trade sur position, et la corriger revient
a H1/H3. Exhaustion (S4) : seuil cale sur un lag faux, cycle suivant. Retour VWAP en tendance (S8) :
en reserve derriere H2. Double top et Battle Navale : boosters L3/L4, pas des hypotheses.

### Planchers en ticks sur toute proximite — correction du 06/09, avant le tag

Les unites mesurees le montrent sans le dire : ATR-5m ~ **11,3 ticks sur ES**, donc un seuil de
0,10 ATR vaut **1,13 tick**. H3 exigerait d'etre a un tick du VAH ; la borne basse de H6
(-0,15 ATR ... +0,05 ATR) vaut **0,6 tick**, plus fin que la grille de cotation. Sur NQ le meme
seuil vaut 8 ticks et respire. Une definition qui n'est atteignable que sur un instrument n'est pas
une hypothese, c'est un artefact d'unite.

**Regle appliquee a toutes les hypotheses, symetrique entre instruments :**

| notion | definition |
|---|---|
| **proximite** (etre « a » un niveau) | `max(0,10 x ATR-5m, 2 ticks)` |
| **fenetre de retest** | `max(0,15 x ATR-5m, 3 ticks)` |
| **depassement** (H7, reserve de liquidite) | `max(0,10 x ATR-5m, 2 ticks)` |

Effet mesure : sur ES le plancher devient actif (2 ticks au lieu de 1,13) ; sur NQ il ne mord jamais
(8 ticks > 2). Ce n'est pas un assouplissement cale sur un resultat — il est ecrit **avant** de
tourner, il vaut pour les deux instruments, et son motif est la grille de cotation, pas le rendement.


### Dimensionnement mesure avant de lancer (06/09, 57 jours, source unique)

Franchissements `false -> true` du **lieu seul**, sans la condition de reaction : c'est une **borne
superieure** de N, pas une prevision.

| | ES | NQ | lecture |
|---|---|---|---|
| H4 `rule_80pct` actif | 16 | 16 | **sous-dimensionnee** — evenement rare par nature, ce n'est pas un defaut de mesure |
| H3 extreme de VA | 807 | 728 | testable |
| H6 `ib_broken_up` | 175 | 147 | testable |
| H7 `sweep_low_this_bar` | 4 972 | 7 419 | testable, mais le detecteur seul declenche 87 a 130 fois par jour : **c'est la condition de reserve de liquidite (>= max(0,10 ATR, 2 t)) qui fait tout le travail** |
| H8 rvol >= 2 et \|delta\| >= 0,30 | 770 | 1 098 | testable |

**H4 est annoncee sous-dimensionnee AVANT de tourner** (16 franchissements sur 57 jours),
conformement au §8 : son resultat attendu est « non testable sur ce lot ». Elle est conservee parce
que la regle des 80 % est un evenement rare par nature et que le statut le dira ; elle ne sera pas
requalifiee apres coup.

**Point ferme le 06/09** : `mq_gamma_condition` vaut bien 1 quand `net_gex` > 0
(`menthorq_backfill_injector.py:148`), donc la lecture « > 0 » etait correcte — mais la colonne est un
proxy depuis le 27/05, et la regle « donnees collectees uniquement » la retire. H1 et la clause gamma
de H2 tombent avec elle.

**Pour chaque hypothese, le runner rapporte en plus** : la **sortie naturelle** (VPOC, VWAP ou VA
opposee atteinte avant la barriere) — mesure d'information, jamais un critere ; et `repose_sur_B`
quand une condition ne lit que du niveau B.

### Unites et proximite des niveaux — mesure du 06/09, avant le tag

**Unites etablies** (elles n'etaient ecrites nulle part, et c'est le piege qui a deja frappe deux fois) :

| grandeur | unite | mesure ES | mesure NQ |
|---|---|---|---|
| `atr_14m` | TICKS | mediane 5,07 t | 35,86 t |
| ATR-5m (= `atr_14m` x racine(5)) | TICKS | ~11,3 t = 2,83 pts | ~80,2 t = 20,05 pts |
| `dist_mq_*`, `dist_cur_*` | TICKS | — | — |
| **seuil 0,10 ATR-5m** | | **1,13 tick** | **8,02 ticks** |

Verification de coherence : le niveau `mq_call` reconstruit par `close + dist_mq_call x 0,25` est
**constant sur toute la journee** (un seul niveau distinct sur 1 260 barres) et prend des valeurs de
strike rondes — 7 700 / 7 750 / 7 800 sur les vingt derniers jours ES. La colonne est vivante et
correctement figee : elle n'a pas besoin du gel par session que la revue reclamait.

**Proximite des niveaux MenthorQ au prix** (ES, 15 jours, 17 164 barres) — part des barres a
**moins de 0,25 ATR-5m** du niveau :

| colonne | mediane | <= 0,25 ATR |
|---|---|---|
| `dist_mq_call` | 338 t (84 pts) | **0,16 %** |
| `dist_mq_put` | 293 t | 0,33 % |
| `dist_mq_call_0dte` | 138 t | 0,64 % |
| `dist_mq_put_0dte` | 135 t | 0,87 % |
| `dist_mq_hvl` | 119 t (30 pts) | **1,65 %** |
| `dist_cur_vah` (comparaison) | 29 t | 4,60 % |

**Consequence pour H1.** Le prix n'approche pas le mur gamma : il en est a 84 points en mediane, et
meme en desserrant le seuil a 0,50 ATR on ne touche que 0,43 % des barres. Ce n'est donc pas un
probleme de calibrage de seuil — **le mur gamma n'est pas un lieu de test intraday sur ce lot**.
H1 est conservee telle quelle et son resultat attendu est ecrit d'avance : **non testable**.

Si Jackson veut un huitieme lieu options-driven, le seul candidat mesure est **`dist_mq_hvl`**
(1,65 % des barres a 0,25 ATR, soit environ dix fois H1). Ce serait une **autre** hypothese — un
rejet sur niveau de volume, pas un rejet de mur gamma — et elle devrait etre ecrite comme telle,
pas substituee en silence.

**Source de `mq_gamma_condition`** : `menthorq_backfill_injector.py:148` — vaut **1 si `net_gex` > 0**
(dealers long gamma, stabilisant), 0 sinon. La lecture « > 0 » de H1 et H2 est donc correcte, et le
rationnel de retour a la moyenne est bien celui du code. **Mais** `enricher_chain.py:279-284` indique
que le scraper MenthorQ est **down depuis le 27/05** : sur les 57 jours, la colonne est un **proxy**
reconstruit depuis `bool_gex_flip_zone` Sierra natif, et non le `net_gex` de MenthorQ (verifie :
`gamma_condition` et `net_gex` sont nuls dans le JSON MenthorQ du 14/06).
**C'est ce constat qui a fait retirer H1 et la clause gamma de H2** (regle « donnees collectees
uniquement », §0). Le dump Sierra `mq_levels_1.0` porte les NIVEAUX (`mq_call`, `mq_put`, `mq_hvl`,
`mq_*_0dte`, `mq_1d_min/max`, `mq_gex[10]`, `mq_blind[10]`) mais pas `net_gex` : les distances aux
murs restent admises, la condition de gamma non.


## 7. Ce que le runner mesure, à l'aveugle

Le runner calcule signaux et triple barriere pour les six, ES et NQ, sur les 40 jours, **sans afficher de résultat
intermédiaire**. Le tableau de survie s'affiche une fois, complet. Pour chaque hypothèse × instrument :
N signaux, espérance nette (ATR et $), WR, distribution par jour, courbe walk-forward (5 blocs), sensibilité
±30 % sur chaque seuil, et les quatre variantes : brute / avec L1 / avec L2 / avec L1+L2.

**Entonnoir par hypothese — obligatoire, pas seulement le N final.** Pour chaque hypothese x
instrument, le runner rapporte N a **chaque etage**, dans l'ordre :

```
  lieu seul  ->  lieu + reaction  ->  + regime L2  ->  + biais L1
```

Sans ces quatre chiffres, « non testable » ne dit pas **ou** l'hypothese perd ses signaux : si c'est
le lieu qui est rare (rien a faire) ou la reaction qui est trop stricte (a rouvrir au cycle suivant).
Le cas est deja visible avant de lancer : H7 declenche 4 972 fois sur le lieu seul, et c'est la
condition de reserve de liquidite qui fera tout le travail ; H3 passe de 807 a peut-etre une centaine
apres la reaction. C'est une colonne du rapport, pas une hypothese de plus.


## 8. Critères de survie — une hypothèse survit si TOUT est vrai

- N ≥ 40 signaux sur les 40 jours, **sur chaque instrument** (sinon statut « non testable sur ce lot », pas « meurt »).
- Espérance nette > 0 en ATR **sur ES ET sur NQ**, séparément.
- ≥ 5 jours distincts ; aucun jour ne porte > 60 % du gain.
- Walk-forward positif sur ≥ 4 des 5 blocs.
- Bootstrap **par jour** (blocs = journees entieres, jamais par barre), **p < 0,05 / 6**
  (six hypotheses apres le retrait de H5 et de H1 ; se penaliser sur des hypotheses qui ne peuvent
  pas produire de signal couterait de la puissance sans rien acheter).
- Robuste : ±30 % sur chaque seuil ne change pas le signe.
Puis, et seulement pour les survivantes : lecture unique des jours 41–51, comparée aux 40.

**Lecture du critere statistique — a ne pas confondre.** p < 0,05/6 sur 40 journees independantes est très exigeant : peu d'hypothèses réelles l'atteindront sur ce lot, et c'est voulu. Le tableau distingue donc trois sorties, pas deux :
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
**Ce que le tag fige : le TEXTE de la mission, pas le code.** Les quatre corrections du runner
(remise a zero a la frontiere de journee, blocs fixes de 8 jours, `lire()` + exclusions `stale`,
ATR-5m dans l'entonnoir) restent a faire **avant de lancer**, pas avant de taguer. Le tag verrouille
les hypotheses ; le code doit ensuite prouver qu'il les execute comme ecrites.

Cases 1 a 4 tranchees le 06/09 ; **la case 5, le GO, est la seule qui reste**. Par Jackson : `git tag mission-phase2-v1` sur le commit, message « MISSION PHASE 2 v1 — hypothèses figées le <date> ». Le runner vérifie que le tag existe et que le fichier n'a pas changé depuis (hash) avant de tourner. Après ce tag, `NEXT_CYCLE.md`.

## 10. Règle de franchise
Si zéro survit, c'est le résultat attendu et c'est un livrable. Aucun critère n'est assoupli pour en faire passer une.
Aucun seuil n'est retouché après avoir vu un résultat. Ce qui vient après un résultat va dans `NEXT_CYCLE.md`.
