# CONVENTIONS — fenetres, unites, qualite des donnees

> **Gouvernance** : toute modification de ce fichier = un commit dedie + une ligne
> dans `DECISIONS.md`. Ce document enonce des regles, pas des explications. Les
> justifications vont dans `INCIDENT_LOG.md`.

Etabli le 05/09/2026 sur 75 jours ES + NQ. Version `w1`.

---

## 1. Fenetres de session

Deux fenetres, jamais une seule. **Le suffixe porte la fenetre. Aucune colonne
de ces familles ne doit exister sans suffixe.**

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
graphique alimentant le DMP. Sortie de dette : corriger le C++ pour convertir
depuis le fuseau du graphique, puis passer le fuseau en ET.

## 3. Unites

| Colonne | Unite | Consequence |
|---|---|---|
| `atr` | POINTS | ATR journalier ; controle : 0,5–3 % du prix |
| `atr_14m` | TICKS | multiplier par le tick pour des points ; controle : 0,02–0,15 % |
| `dist_*` sans suffixe | TICKS | convention `(niveau - close) / tick` |
| `dist_*_pct` | % du prix | |

**Controle d'ordre de grandeur obligatoire.** Une identite qui passe ne prouve
pas l'unite : les deux membres peuvent partager le meme defaut. Toute colonne en
unite physique doit avoir une borne de plausibilite verifiee independamment.

## 4. Lecture des barres : le filtre unique

**Ne lire que les lignes `data_quality_flag == stable`.** Ce filtre suffit : il
elimine les lignes partielles et les doublons en une seule passe.

Mesure 04/09 NQ : 1 259 lignes `stable` pour 1 259 `ts` uniques, 731 `degraded`,
9 `warmup`. Les 260 lignes a `dist_vwap_d` nul sont toutes `degraded`.

- Une ligne `degraded` ou `warmup` n'entre ni dans le clustering, ni dans la
  mission, ni dans le bot. Elle reste dans le fichier brut, elle est exclue a la
  lecture. Le nombre de lignes exclues par jour est logue.
- Repli, si plusieurs lignes `stable` partagent un `ts` : garder le dernier boot.
- `seen_ts` **persiste sur disque, par jour**, et se recharge au demarrage. Il ne
  vit plus en memoire du process.

**Controle de volumetrie** : session complete = 1 380 barres (23 h x 60), cash =
390. Compte sur les lignes `stable`. Tout fichier hors de +/- 1 % est signale,
jamais integre en silence.

## 5. Reserve

Le filtre de la section 4 est verifie sur le 04/09. A confirmer sur les 75 jours
avant d'etre considere comme invariant ; jusque-la, controler la volumetrie
`stable` a chaque lecture.

## 6. Independance aux frontieres de fichier

Le DMP decoupe par journee de trading (22:01 → 20:58). L'enricher decoupe par
date UTC calendaire (00:00 → 23:58). Les deux conventions coexistent.

**Regle** : aucun calcul ne depend jamais d'une frontiere de fichier. Les seules
cles temporelles sont `ts` et les sessions qui en derivent (`_rth`, `_sess`). Un
fichier peut commencer a 00:00, a 21:00 ou a un redemarrage : aucune valeur ne
doit changer.

**Test de non-regression** : concatener deux jours, verifier que les colonnes
produites sont identiques a celles produites fichier par fichier.

## 7. Colonnes a definition non identifiee

Aucune n'est cassee : elles mesurent autre chose que ce que leur nom indique.

| Colonne | Contenu reel | Statut |
|---|---|---|
| `range_size_ticks` | largeur d'une zone de range detectee, pas la barre | renommer |
| `dist_1d_max_ticks` | distance a `mq_1d_max` (niveau options) | renommer |
| `momentum_3b` | `close - close[-1]` (lag 1, pas 3) | recalculer |
| `momentum_5b` | `close - close[-2]` (lag 2, pas 5) | recalculer |
| `dist_pdh_atr`, `dist_pdl_atr` | points / atr, **signe inverse** | recalculer |
| `dist_*_atr` (autres) | ticks / atr en points → vaut 4x le vrai nombre d'ATR | recalculer |
| `delta_day` | alias de `cvd_day` | hors noyau |
| `cvd_session` | alias de `ctx_cvd_session`, repli sur `cvd_day` | hors noyau |
| `bar_body_ticks`, `bar_body_pct` | signes, pas des valeurs absolues | renommer |
| `dist_prev_vwap` et bandes | etude au fuseau errone | recalculer |

## 8. Niveaux : lire le suffixe `_lvl`

`prev_vpoc`, `prev_vah`, `prev_val`, `open_cash` existent en deux versions.
**Toujours lire `_lvl`** : la version sans suffixe est l'alias DMP qui pointe vers
l'etude courante (INCIDENT #76). Les distances livrees suivent deja `_lvl`.

## 9. Marquage de version

Toute barre porte `window_version`. Valeur `w0` avant le 05/09/2026 (session a
17:00 UTC), `w1` a partir du 05/09/2026 (session a 17h ET). Les VA anterieures au
05/09 sont sur `w0` et ne sont pas comparables aux suivantes.
