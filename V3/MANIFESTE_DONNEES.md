# MANIFESTE DES DONNEES — ce que V3 consomme vraiment

*GENERE par `V3/mesure_manifeste.py`, jamais ecrit a la main. Regenerer
apres toute modification d'une colonne : un catalogue tape ment des la
premiere derive. Mesure sur le 20260910, ES et NQ.*

## La source, en une ligne

`DATA/live_enriched/sierra/{ES,NQ}/*.jsonl`, barres de 1 minute, agregees
en 15 minutes par la chaine (`injecter_recalculs`, chauffe vingt jours).
**Le frame que la chaine LIT porte 87 colonnes** ; le brut 1 min en porte
plusieurs centaines — tout ce qui n'est pas dans la liste ci-dessous meurt
a l'agregation et n'existe pas pour V3.

## Le compte

| provenance | colonnes | ce que ca veut dire |
|---|---|---|
| `A` | 21 | reproduite en C++ et verifiee par IDENTITE |
| `B` | 35 | colonne C++ NON reproduite (plausibilite seulement) |
| `C` | 9 | metadonnee, fuite, ou trop peu de valeurs — ecartee |
| `N` | 4 | niveau de prix : entree de recalcul, pas une feature |
| `chaine` | 10 | produite par la CHAINE, pas par le C++ — absente de la table DMP, et c'est normal : la table catalogue les colonnes du dumper |
| `recalc` | 8 | recalculee par la chaine (`_r`) |

> Les colonnes `recalc` sont calculees par la chaine avec VINGT jours
> de chauffe. Sur un frame `lot` de trois jours elles peuvent etre absentes
> — ou pire, PRESENTES ET FAUSSES. C'est pourquoi la ligne de journal porte
> `setups_armes_motif` et `flux_motif` quand le frame n'est pas fiable.

## Ce sur quoi repose la decision (★)

**21 colonnes** sur 87 sont lues par LES_QUATRE et les setups
(citees dans `V3/marges_quatre.py`). Tout le reste est du contexte :

`atr_ref`, `atr_source`, `close`, `delta_bar`, `delta_pct`, `dist_cur_vah`, `dist_cur_val`, `dist_ib_high`, `dist_ib_low`, `dist_vwap_rth_sd2d_r`, `dist_vwap_rth_sd2u_r`, `finish_delta_pct`, `high`, `ib_broken_dn`, `ib_broken_up`, `jour`, `low`, `open`, `rvol`, `rvol_r`, `ts`

## Les pieges d'unite

Sept confusions d'unites en une semaine dans ce depot, toutes d'un facteur
constant. Les quatre qui comptent :

| colonne | unite | d'ou elle vient |
|---|---|---|
| `atr` | **points** | ATR JOURNALIER, lu du chart daily de Sierra en prix |
| `atr_14m` | **ticks** | ATR(14) 1 min ; le C++ divise par `tick_size` avant de rendre |
| `atr_barre`, `atr_veille`, `atr_ref` | **points** | recalcules par la chaine sur la barre agregee |
| `dist_*` | **ticks** | `niveau = close + dist x tick` (CONVENTIONS §8) |
| `*_pct` | **part de 0 a 1** | PAS un pourcentage affichable tel quel |

> `atr` et `atr_14m` n'ont ni la meme periode ni la meme unite : l'un est
> JOURNALIER en points, l'autre est sur 14 barres de 1 MINUTE en ticks. Les
> comparer par leur ordre de grandeur ne prouve rien — c'est l'erreur que la
> premiere version de ce manifeste a commise, en affirmant a tort que
> `CLAUDE.md` disait l'inverse de la realite. `CLAUDE.md` avait raison.

### Verification, a chaque generation

| colonne | unite declaree | mediane du jour | ATR recalcule des barres | verdict |
|---|---|---|---|---|
| `atr_14m` | ticks | 10.25 | 10.43 | coherent |
| `atr_barre` | points | 11.63 | 12.34 | coherent |

## VWAP et bandes

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `dist_vwap_d` | F10 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_vwap_rth_r` | F10 | `recalc` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | recalc (chauffe 20 j) |
| ★ `dist_vwap_rth_sd2d_r` | F10 | `recalc` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | recalc (chauffe 20 j) |
| ★ `dist_vwap_rth_sd2u_r` | F10 | `recalc` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | recalc (chauffe 20 j) |
| `dist_vwap_w` | F1 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `vwap_rth_r` | recalc | `recalc` | prix absolu — un niveau, pas une distance | recalc (chauffe 20 j) |
| `vwap_slope_10` | F10 | `B` | points par barre — « Pente VWAP 10 barres (pts/barre) » (`DMP_Transform.h`). PIEGE : `vwap_slope_r` est en ATR sur 4 barres — deux pentes, deux unites, deux fenetres | — |
| `vwap_slope_r` | F10 | `recalc` | ATR par 4 barres — pente de `vwap_rth_r` sur 4 barres, normalisee par `atr_barre` | recalc (chauffe 20 j) |

## Valeur : VA, VPOC, composite

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| ★ `dist_cur_vah` | F10 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| ★ `dist_cur_val` | F10 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_cur_vpoc` | F10 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_prev_vah` | F3 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_prev_val` | F3 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_prev_vpoc` | F3 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `inside_prev_va` | F3 | `B` | booleen | — |
| `poc_migration_dir` | F6 | `B` | signe -1 / 0 / +1 — sens de migration du POC (`DMP_Transform.h`) | — |

## Initial Balance

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| ★ `dist_ib_high` | F5 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| ★ `dist_ib_low` | F5 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| ★ `ib_broken_dn` | F5 | `B` | booleen | — |
| ★ `ib_broken_up` | F5 | `B` | booleen | — |
| `ib_range_ticks` | F5 | `A` | ticks | — |

## Overnight, PDH / PDL

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `dist_ovn_high` | F12 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_ovn_low` | F12 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_pdh` | F1 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_pdl` | F1 | `A` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |

## Delta, CVD, flux d'ordres

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `ask_pct` | F13 | `A` | part (0 a 1) — PAS un pourcentage affichable tel quel | — |
| `bid_pct` | F13 | `A` | part (0 a 1) — PAS un pourcentage affichable tel quel | — |
| `cvd_day` | F13 | `B` | contrats — « CVD cumulatif journee » (`DMP_Transform.h`) | — |
| `cvd_day_dir` | F13 | `B` | signe -1 / 0 / +1 — « Direction CVD » (`DMP_Transform.h`) | — |
| `cvd_sess_r` | F13 | `recalc` | contrats — cumul du delta depuis 17h ET — la NUIT est dedans, ce n'est PAS depuis 9h30 | recalc (chauffe 20 j) |
| `cvd_session` | F13 | `C` | contrats — `cvd_day` moins le snapshot a l'ouverture RTH ; INVALIDE hors RTH. A ne PAS confondre avec `cvd_sess_r`, qui cumule depuis 17h ET — la nuit comprise | hors noyau (alias ou §7) |
| ★ `delta_bar` | F13 | `A` | contrats (signe) — « Delta barre (ask - bid volume) » (`DMP_Transform.h`) | — |
| ★ `delta_pct` | F13 | `A` | part (0 a 1) — PAS un pourcentage affichable tel quel | — |
| `dist_big_ask_nearest_dn` | F16 | `C` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | desaccord structurel ES/NQ |
| `dist_big_ask_nearest_up` | F16 | `C` | booleen — unite DIFFERENTE sur NQ (ticks) | desaccord structurel ES/NQ |
| `dist_big_bid_nearest_dn` | F16 | `C` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | desaccord structurel ES/NQ |
| `dist_big_bid_nearest_up` | F16 | `C` | booleen | nulls 10% par jour |
| ★ `finish_delta_pct` | F19 | `A` | part (0 a 1) — PAS un pourcentage affichable tel quel | — |
| `max_big_ask_vol_in_bar` | F16 | `B` | compte | — |
| `max_big_bid_vol_in_bar` | F16 | `B` | compte | — |
| `n_big_ask_t3` | F16 | `B` | compte | — |
| `n_big_ask_t4` | F16 | `C` | compte — unite DIFFERENTE sur NQ (booleen) | desaccord structurel ES/NQ |
| `n_big_bid_t3` | F16 | `B` | compte | — |
| `n_big_bid_t4` | F16 | `C` | compte — unite DIFFERENTE sur NQ (booleen) | desaccord structurel ES/NQ |
| `retest_high_count` | F21 | `B` | compte — unite DIFFERENTE sur NQ (booleen) | — |
| `retest_low_count` | F21 | `B` | compte | — |
| ★ `rvol` | F7 | `B` | ratio — « Volume relatif (1.0 = normal, >2.0 = spike) » (`DMP_Transform.h`) | — |
| ★ `rvol_r` | F7 | `recalc` | ratio — volume de la barre / mediane de la MEME MINUTE de session sur 20 jours (`recalc.rvol`) ; 1,0 = volume habituel. Toujours positif | recalc (chauffe 20 j) |
| `rvol_zscore` | F7 | `B` | ecarts-types — « Z-Score volume » (`DMP_Transform.h`) | — |
| `sweep_high_this_bar` | F17 | `B` | booleen | — |
| `sweep_low_this_bar` | F17 | `B` | booleen | — |
| `total_vol` | F19 | `A` | compte | — |

## MenthorQ, GEX, 0DTE

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `_mq_gamma_source` | F8 | `chaine` | — — aucune valeur finie sur la journee mesuree | — |
| `dist_gex_nearest_dn` | F11 | `B` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_gex_nearest_up` | F11 | `B` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_mq_call` | F11 | `B` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_mq_hvl` | F8 | `B` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `dist_mq_put` | F11 | `B` | ticks — convention `niveau = close + dist x tick` (CONVENTIONS §8) | — |
| `gamma_block_long` | F22 | `B` | booleen | — |

## VIX

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `vix_level` | F7 | `B` | points d'indice — « Prix courant du VIX » (`DMP_Reader.h`) | — |
| `vix_regime` | F7 | `B` | booleen | — |

## ATR

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `atr` | F22 | `B` | points — ATR JOURNALIER, lu sur le chart daily de Sierra en PRIX (`DMP_Reader.h`, `DMP_ReadDaily` -> `atr_daily`) | — |
| `atr_14m` | F22 | `B` | ticks — ATR(14) sur barres 1 min : `DMP_Calc_ATR_14m` rend `atr_price / tick_size` — le C++ le dit en toutes lettres | — |
| `atr_barre` | hors famille | `chaine` | points — ATR de la barre agregee 15 min, recalcule par la chaine | nee a l'agregation 15 min |
| ★ `atr_ref` | hors famille | `chaine` | points — = `atr_barre` si fini, sinon `atr_veille` ; `atr_source` dit lequel | nee a l'agregation 15 min ; = `atr_barre` si fini, sinon `atr_veille` ; `atr_source` dit lequel |
| ★ `atr_source` | hors famille | `chaine` | — — aucune valeur finie sur la journee mesuree | nee a l'agregation 15 min |
| `atr_veille` | hors famille | `chaine` | points — ATR de la veille, meme famille qu'`atr_barre` | nee a l'agregation 15 min |

## Barre courante et meches

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `bar_lower_wick_pct` | F19 | `B` | part (0 a 1) — PAS un pourcentage affichable tel quel | — |
| `bar_upper_wick_pct` | F19 | `B` | part (0 a 1) — PAS un pourcentage affichable tel quel | — |
| ★ `close` | F19 | `N` | prix absolu — ne JAMAIS mettre dans un modele : niveau de prix | — |
| `finish_r` | F19 | `recalc` | part (0 a 1) — position de la cloture dans le range de la barre AGREGEE | recalc (chauffe 20 j) |
| ★ `high` | F19 | `N` | prix absolu — ne JAMAIS mettre dans un modele : niveau de prix | — |
| ★ `low` | F19 | `N` | prix absolu — ne JAMAIS mettre dans un modele : niveau de prix | — |
| ★ `open` | F19 | `N` | prix absolu — ne JAMAIS mettre dans un modele : niveau de prix | — |

## Contexte ctx_*

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `ctx_poor_high` | F21 | `B` | booleen | — |
| `ctx_poor_low` | F21 | `B` | booleen | — |

## Calendrier, news, session

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `is_news_60m` | F9 | `B` | booleen | — |
| `is_session_blocked` | F9 | `B` | booleen | — |
| ★ `jour` | hors famille | `chaine` | — — aucune valeur finie sur la journee mesuree | nee a l'agregation 15 min |
| `minutes_reelles` | hors famille | `chaine` | compte | nee a l'agregation 15 min |
| ★ `ts` | hors famille | `C` | compte | metadonnee ou fuite |

## Technique et qualite

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `_aggressor_source` | hors famille | `chaine` | — — aucune valeur finie sur la journee mesuree | — |
| `barre_complete` | hors famille | `chaine` | booleen | nee a l'agregation 15 min |
| `data_quality_flag` | hors famille | `C` | — — aucune valeur finie sur la journee mesuree | moins de 100 valeurs |
| `window_version` | hors famille | `chaine` | — — aucune valeur finie sur la journee mesuree | nee a l'agregation 15 min |

## Hors bloc

| colonne | fam. | prov. | unite | note |
|---|---|---|---|---|
| `vah_touches_20b` | F10 | `B` | compte | — |
| `val_touches_20b` | F10 | `B` | compte | — |

