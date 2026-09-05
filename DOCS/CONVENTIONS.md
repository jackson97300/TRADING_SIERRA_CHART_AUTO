# CONVENTIONS — fenetres, unites, qualite des donnees

> **Gouvernance** : toute modification de ce fichier = un commit dedie + une ligne
> dans `DECISIONS.md`. Ce document enonce des regles, pas des explications. Les
> justifications vont dans `INCIDENT_LOG.md`.

Etabli le 05/09/2026 sur 75 jours ES + NQ.

---

## 1. Fenetres de session

Deux fenetres, jamais une seule. **Le suffixe porte la fenetre. Aucune colonne de
ces familles ne doit exister sans suffixe.**

| Suffixe | Fenetre | Familles concernees |
|---|---|---|
| `_rth` | 9h30–16h00 ET | profil, VA, VPOC, VAH/VAL, IB, VWAP de reference et bandes, session high/low cash |
| `_sess` | 17h00 ET → 17h00 ET | PDH/PDL, overnight high/low, open 17h, gap, VWAP de session |

En UTC : `_rth` = 13:30–20:00 (EDT) / 14:30–21:00 (EST).
`_sess` = 21:00 → 20:59:59 (EDT) / 22:00 → 21:59:59 (EST).

## 2. Parametrage Sierra Chart

Le graphique est en **UTC** (`Global Time Zone`). Les session times sont donc
saisis en UTC. **Ne jamais changer `Time Zone (List)`** : `sc.BaseDateTimeIn` est
lu par le C++ comme de l'UTC ; le modifier decale tous les `ts` de 4 heures.

| Champ | EDT (ete) | EST (hiver) |
|---|---|---|
| Session Start Time | `21:00:00` | `22:00:00` |
| Session End Time | `20:59:59` | `21:59:59` |
| Volume Profile (plage RTH) | `13:30–20:00` | `14:30–21:00` |

**Bascule EST : premier dimanche de novembre 2026 (01/11).** A refaire sur chaque
graphique alimentant le DMP.

**Le check qui porte cette dette** : `vwap_reset_hour` dans `semantic_check`
compare l'heure UTC du reset de `vwap_sess` a 17:00 ET converti au jour pres.
Echec = integration bloquee. La date seule ne protege rien.

Sortie de dette : corriger le C++ pour convertir depuis le fuseau du graphique,
puis passer le fuseau en ET et laisser Sierra gerer le DST.

## 3. Unites

| Colonne | Unite | Controle de plausibilite |
|---|---|---|
| `atr` | POINTS | ATR journalier : 0,5–3 % du prix |
| `atr_14m` | TICKS | 0,02–0,15 % du prix apres conversion |
| `dist_*` sans suffixe | TICKS | convention `(niveau - close) / tick` |
| `dist_*_atr` | multiples d'ATR | `(niveau - close) / atr` |
| `dist_*_pct` | % du prix | |

| Instrument | Tick | Valeur | Note |
|---|---|---|---|
| ES | 0,25 pt | 12,50 $ | E-mini ESM26, 50 $/pt |
| NQ | 0,25 pt | 5,00 $ | E-mini NQM26, 20 $/pt |
| MGC | 0,10 pt | 1,00 $ | Micro Gold |

Source unique : `CORE/constants.py`. Le dashboard affiche en micro-equivalent ;
les bots envoient du E-mini. **Un seuil calibre sur un instrument ne se transpose
jamais a un autre** (cf `DOCS/ECART_ES_NQ_PAR_FEATURE.csv`).

**Controle d'ordre de grandeur obligatoire.** Une identite qui passe ne prouve pas
l'unite : les deux membres peuvent partager le meme defaut. Toute colonne en unite
physique doit avoir une borne de plausibilite verifiee independamment.

### 3.1 Un defaut d'initialisation ne doit jamais etre une valeur valide du domaine

`DMP_Transform.h:1355-1390` initialise les champs avant que leur module ne les calcule. Deux facons
de le faire coexistent dans le meme bloc, a deux lignes d'intervalle :

```c
f.day_type             = 2.0f;         // "NormVar = le type le plus frequent (42%)"
f.profile_hvn_dominant = DMP_INVALID;  // "Pas encore calcule"
```

La seconde est la bonne. La premiere rend « NormVar calcule » et « NormVar jamais calcule »
**indistinguables** : aucun consommateur ne peut les separer, aucun controle ne peut le detecter
sans comparer a une distribution attendue, et le champ ment sans jamais etre nul.

**Regle** : si le module de calcul peut ne pas tourner, la valeur d'initialisation doit etre
**hors du domaine** des valeurs mesurables (`DMP_INVALID`, ou un code « non calcule » ajoute a
l'enum). Un defaut « raisonnable » est precisement celui qu'on ne remarquera pas.

**Crible du bloc, mesure le 06/09** sur 53 jours de seance ES (RTH, dedoublonne). Neuf champs sont
initialises a une valeur qui appartient a leur domaine ; un seul se materialise :

| champ | defaut | jours figes | part du RTH |
|---|---|---|---|
| `day_type` | 2.0 (NormVar) | **33 / 53** | **82,1 %** |
| `open_zone` | 4.0 (AT_POC) | 0 / 53 | 0,0 % |
| `profile_shape` | 0.0 (D-shape) | 0 / 53 | 8,0 % |
| `poc_separation_ticks` | 0.0 | 0 / 53 | 43,7 % (valeur reelle : pas de double distribution) |
| `profile_skew`, `poc_position`, `volume_imbalance`, `rvol`, `rvol_zscore` | — | 0 / 53 | < 1 % |

Le risque est donc structurel sur neuf champs et realise sur un seul. Ce n'est pas une raison de
laisser les huit autres : ils sont a une panne de module de faire la meme chose, sans rien qui le
signale. Correctif C++ (`DMP_INVALID` partout) porte dans `NEXT_CYCLE.md`.

**Consequence de lecture** : `day_type` ne doit pas etre lu tel quel. Surveillance : controle L6
n7 `valeurs_par_defaut`.


## 4. Lecture des barres : le filtre unique

**Lire `ts`, jamais `ts_raw_ms`.** Le fichier porte les deux : `ts` est
aligne sur la minute a 100 %, `ts_raw_ms` a 68,8 % seulement (31 % des lignes
portent la fin de barre moins une seconde). Un groupby par minute sur
`ts_raw_ms` perd 30 % des barres : 950 minutes distinctes au lieu de 1 379.
Mesure sur 23 417 lignes ES + NQ. Helper : `recalc.horodatage(df)`.

**Ne lire que les lignes `data_quality_flag == stable`.** Ce filtre elimine les
lignes partielles et les doublons en une seule passe.

Mesure 04/09 NQ : 1 259 lignes `stable` pour 1 259 `ts` uniques, 731 `degraded`,
9 `warmup`. Les 260 lignes a `dist_vwap_d` nul sont toutes `degraded`.

- Une ligne `degraded` ou `warmup` n'entre ni dans le clustering, ni dans la
  mission, ni dans le bot. Elle reste dans le fichier brut, elle est exclue a la
  lecture. Le nombre de lignes exclues par jour est logue.
- Repli, si plusieurs lignes partagent un `ts` : `stable` avant `warmup` avant
  `degraded` ; a egalite **la ligne la plus complete** ; a egalite encore la
  premiere, par convention, pour etre deterministe.
  **Ni `keep="first"` ni `keep="last"`** — aucune position ne domine. Mesure du
  06/09 sur les 524 minutes dupliquees des 57 jours, lignes `stable` :

  | | premiere plus complete | derniere plus complete | a egalite |
  |---|---|---|---|
  | ES | 21,8 % | 18,4 % | 59,8 % |
  | NQ | 28,9 % | 29,3 % | 41,8 % |

  Mediane des champs non nuls : 515 / 516 sur ES, 513 / 512 sur NQ. L'ecart de
  548 contre 573 observe le 04/09, qui avait motive un « jamais `keep=last` »,
  etait une propriete de ce jour-la et non de la serie : la prescription reste
  bonne, son motif etait faux. **C'est la completude qui departage, pas le
  rang.** Choisir par position lit des nulls une fois sur cinq, et une hypothese
  qui tombe sur un null a la barre t ne declenche pas sans le dire.
- **Un seul ordre, une seule fonction** : `recalc.dedoublonner_par_minute()`.
  Tout script qui lit les JSONL brut l'importe ; aucun ne reimplemente le
  departage.
- `seen_ts` **persiste sur disque, par jour**, et se recharge au demarrage.

**Volumetrie** : session complete = 1 380 barres (23 h x 60), cash = 390. Compte
sur les lignes `stable`. Deux seuils, pas un :

| Part de 1 380 | Statut |
|---|---|
| >= 99 % | complet |
| 90–99 % | **exploitable** — utilisable pour clustering, mission, bot |
| < 90 % | **exclu** — signale, jamais integre en silence |

**Sauf dimanches et jours feries CME** (liste dans `sessions.yaml`) : sessions
courtes par nature, attendues, comptees a part.

**Validation du filtre (05/09, 75 jours ES + NQ)** — la reserve est levee :
- un seul `stable` par `ts` : 2 violations NQ, 0 ES sur ~79 400 lignes
- lignes `stable` a valeur nulle : 5 NQ, 7 ES (0,006 %)
- `ts` sans aucune ligne `stable` : 1,94 % NQ, 2,41 % ES — cout du filtre
- **51 jours ouvrables exploitables sur NQ, 52 sur ES**, sur 61 ouvrables
- fenetre continue : 15/06 → 03/09
- jours exclus (< 90 %), communs aux deux instruments : 06-12, 06-19, 06-24,
  06-25, 06-30, 07-03, 08-03, 08-10, 09-04

Script : `CORE/research/valider_filtre_stable.py`.

### 4.1 Source unique, et volumetrie mesuree le 05/09/2026

**`DATA/live_enriched/sierra/` est la seule source.** Databento est abandonne
pour ce projet : ne jamais le proposer, ne jamais s'appuyer sur un resultat qui
en vient (cf memoire `project_source_data_unique_jsonl_live_20260523`).

Comptage sur les barres `stable` **distinctes par minute** — jamais sur un ratio
de lignes, certains fichiers portant jusqu'a 20 940 lignes pour 1 259 barres :

| Jour | ES | NQ | lecture |
|---|---|---|---|
| lundi a jeudi | 1379 | 1379 | seance pleine |
| vendredi | 1259 | 1260 | seance courte — attendu |
| dimanche | 119 | 119 | ouverture du soir, pas une seance |

**57 jours de seance utilisables** par instrument (lun-ven, >= 1000 barres),
soit **114 jours-instruments**, ~76 000 barres stable chacun. Periode 10/06 au
04/09/2026.

Consequence pour toute hypothese : un declenchement par jour et par instrument
rend ~110 signaux. En dessous de 55 attendus, le dire **avant** de tourner.


## 5. Independance aux frontieres de fichier

Le DMP decoupe par journee de trading (22:01 → 20:58). L'enricher decoupe par
date UTC calendaire (00:00 → 23:58). Les deux conventions coexistent.

**Regle** : aucun calcul ne depend jamais d'une frontiere de fichier. Les seules
cles temporelles sont `ts` et les sessions qui en derivent. Un fichier peut
commencer a 00:00, a 21:00 ou a un redemarrage : aucune valeur ne doit changer.

**Test de non-regression** : concatener deux jours, verifier que les colonnes
produites sont identiques a celles produites fichier par fichier.

## 6. Source de verite par colonne

C'est ce principe qui rend le fuseau et les frontieres de fichier inoffensifs
pour le bot.

**Recalculees par l'enricher depuis les barres 1 min, et ecrasees** — ne dependent
d'aucune etude Sierra : VWAP `_rth` / `_sess` et bandes, PDH/PDL, session
high/low, IB, open cash, gap, momentum.

**Tout cumul depuis une borne de session se recalcule, sans exception.** Un
cumul repart de zero au redemarrage du processus, par construction : ce n'est
pas un defaut de la colonne, c'est sa nature. Sept colonnes sont dans ce cas —
`cvd_day`, `delta_day`, `cvd_session`, `ctx_cvd_session`, `ctx_delta_sum_3`,
`ctx_delta_sum_10`, `cvd_bar_delta` — et elles franchissent le seuil de
suspicion a des frequences differentes seulement parce qu'elles s'accumulent a
des vitesses differentes. Mesure : `cvd_day` et `delta_day` suspects 8 jours
sur 51, `cvd_session` 3, `ctx_delta_sum_3` 1.

**Lues de Sierra, seules sources possibles** : VA / VPOC / VAH / VAL, orderflow,
big prints, MenthorQ, VIX.

## 7. Colonnes dont le nom ne dit pas le contenu

Aucune n'est aleatoire ; toutes mesurent autre chose que leur nom. C'est ce qui
justifie le recalcul plutot que l'abandon.

| Colonne | Contenu reel | Cible |
|---|---|---|
| `momentum_3b` | `close - close[-1]` (lag 1) | `close - close[-3]`, points |
| `momentum_5b` | `close - close[-2]` (lag 2) | `close - close[-5]`, points |
| `dist_*_atr` | ticks / atr en points → 4x le vrai | `(niveau - close) / atr` |
| `dist_pdh_atr`, `dist_pdl_atr` | points / atr, signe inverse | `(pdh - close) / atr` |
| `dist_prev_vwap` et bandes | etude au fuseau errone | `(prev_vwap_rth - close) / tick` |
| `dist_asia_high_pct`, `dist_asia_low_pct` | `close - niveau` | `(niveau - close) / close * 100` |
| `dist_london_high_pct`, `dist_london_low_pct` | `close - niveau` | idem |
| `dist_cash_high_atr`, `dist_cash_low_atr` | `close - niveau` | `(niveau - close) / atr` |
| `dist_prev_vpoc_pct` | calcule depuis l alias DMP, pas depuis `_lvl` | `(prev_vpoc_lvl - close) / close * 100` |
| `ctx_price_slope_5` | definition inconnue (96 % NQ / 76 % ES d ecart) | hors noyau |
| `range_size_ticks` | largeur d'une zone de range detectee | renommer `range_zone_ticks` |
| `dist_1d_max_ticks` | distance a `mq_1d_max` (options) | renommer `dist_mq_1d_max_ticks` |
| `bar_body_ticks`, `bar_body_pct` | signes, pas absolus | renommer `bar_body_signed_*` |
| `delta_day` | alias de `cvd_day` | hors noyau |
| `cvd_session` | alias de `ctx_cvd_session`, repli `cvd_day` | hors noyau |

Signes inverses verifies a 0,0 % de conformite sur ES **et** NQ, 75 jours filtres
`stable`. Les variantes en ticks (`dist_ovn_*`, `dist_sess_*`, `dist_ib_*`) sont
conformes : l'inversion ne touche pas les familles entieres.

## 8. Niveaux : lire le suffixe `_lvl`

`prev_vpoc`, `prev_vah`, `prev_val`, `open_cash` existent en deux versions.
**Toujours lire `_lvl`** : la version sans suffixe est l'alias DMP qui pointe vers
l'etude courante (INCIDENT #76). Les distances livrees suivent deja `_lvl`.

## 9. Marquage de version

Toute barre porte `window_version`, qui qualifie les **colonnes dumpees en live** :
`w0` avant le 05/09/2026 (session a 17:00 UTC), `w1` a partir du 05/09/2026
(session a 17h ET).

Exception : les VA **exportees de l'historique** apres recalcul Sierra sont `w1`
meme pour des dates anterieures au 05/09 — c'est precisement leur interet. La
version qualifie la fenetre de calcul, pas la date de la barre.
