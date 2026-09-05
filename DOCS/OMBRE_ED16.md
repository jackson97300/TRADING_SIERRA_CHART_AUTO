# MODE OMBRE — les seize setups d'edge_discovery

**Pre-enregistre le 06/09/2026. Aucun resultat n'a ete lu avant d'ecrire ce document.**

## Origine

`CORE/research/edge_discovery_bot1.py` (804 lignes, recu le 02/05/2026) et son
mode d'emploi `DOCS/PROMPT_EDGE_DISCOVERY.md`. Le jumeau `edge_discovery_bot2.py`
est mort : parquets Databento, source abandonnee.

Portage : `CORE/research/hypotheses_ed.py`. Principe — **garder l'intention,
corriger l'unite**.

## Pourquoi ils n'ont jamais rien pu mesurer tels quels

Seuils en ticks absolus, donc incomparables entre instruments :

| seuil du fichier | en ATR-5m ES | % barres ES | % barres NQ |
|---|---|---|---|
| `dist_prev_vah < -500` | 18,5 ATR | 0,8 % | 13,7 % |
| `dist_cur_vpoc < -300` | 11,1 ATR | 1,0 % | 17,8 % |
| `dist_cur_vpoc abs< 100` | 3,7 ATR | **78,4 %** | 34,2 % |

Facteur **17** entre ES et NQ sur le meme setup. Et « proche du VPOC » est vrai
78 % du temps sur ES : une condition vraie quatre fois sur cinq ne filtre rien.

Trois substitutions, chacune motivee : `range_pos` (statut C, 15 % de nulls)
recalcule en `range_pos_r` ; `rvol` -> `rvol_r` (le C++ initialise a 1,0, valeur
valide) ; `delta_bar` -> `delta_pct` (le brut depend du volume de la barre).

## Dimensionnement mesure sur 40 jours — signaux SEULEMENT, aucun P&L lu

| setup | ES | NQ |
|---|---|---|
| ED11_SELL_IB_BREAK_DOWN | 83 | 79 |
| ED12_BUY_IB_BREAK_UP | 70 | 57 |
| ED16_BUY_VWAP_SD2_SUPPORT | 57 | 70 |
| ED03_SELL_VPOC_FAR_ABOVE | 75 | 29 |
| ED10_BUY_CVD_DIVERGENCE | 49 | 32 |
| ED04_BUY_VPOC_RECLAIM | 46 | 32 |
| ED02_BUY_PREV_VA_RECLAIM | 34 | 46 |
| ED11 a ED16 restants, ED01, ED05 a ED09 | 8 a 30 | 5 a 35 |
| ED13, ED14, ED15 | 4 a 11 | 5 a 9 |
| **TOTAL** | **566** | **500** |

Quatre setups atteignent 40 signaux sur au moins un instrument eligible (NQ).

## La regle, et pourquoi elle n'est pas negociable

**Ces seize ne tournent PAS sur les 40 jours de recherche.** Ceux-ci ont deja
recu trois lectures — cycle 1, cycle 2, horizon 15 min. Une quatrieme sur seize
setups produirait des gagnants par pure combinatoire, et rien ne permettrait de
les distinguer du bruit.

Ils tournent en **mode ombre a partir du 08/09/2026**, sur les jours qui
s'ajoutent, en meme temps que H3-15min. Ils accumulent du N sans consommer un
seul regard sur le passe.

**Lecture : quand un setup atteint N = 40 sur NQ, pas avant.** A ~14 signaux par
jour tous setups confondus, les premiers seront lisibles vers la mi-octobre.

Criteres inchanges : esperance nette > 0, >= 5 jours distincts, aucun jour au-dela
de 60 % du gain, >= 4/5 blocs positifs, bootstrap par jour. **Bonferroni 0,05 / 16**
— seize setups pre-enregistres, seize dans le denominateur, quel que soit le
nombre qui finira par etre lisible.

## Ce qui reste a faire

Inventorier les **gates** des quatre bots (session, circuit breaker, calendrier
economique, cooldowns) — ce sont des couches L0/L5, elles ne creent pas d'edge
mais empechent d'en perdre. Elles se mesurent avec `CORE/entonnoir.py`, qui est
ecrit et toujours pas branche.
