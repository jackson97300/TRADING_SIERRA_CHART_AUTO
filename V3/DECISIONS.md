# DECISIONS — les arbitrages, avec leur date et leur raison

*Ce qui a ete tranche, pourquoi, et sur quelle mesure. Rien ne se decide deux fois.*

| date | decision | raison | mesure a l'appui |
|---|---|---|---|
| 06/09 | source unique `DATA/live_enriched/sierra/` | Databento abandonne | 57 jours de seance, ~76 000 barres/instrument |
| 06/09 | donnees collectees ou derivees uniquement, **aucun proxy** | `mq_gamma_condition` reconstruit depuis un scraper mort le 27/05 | H1 retiree, clause gamma de H2 retiree |
| 06/09 | **un seuil ne s'ecrit pas sans sa distribution** | H6 (`< 0,40` = 0,13 % des barres) et C2-3 (`> 1,2` = 0 %) | 6 confusions points/ticks en une semaine |
| 06/09 | le HVL est un **regime**, pas un lieu | 1,65 % des barres a portee comme lieu ; 99,7 % de couverture comme regime | zone morte 1,0 ATR : 10,2 -> 1,8 bascules/jour |
| 06/09 | grid search = **generateur**, jamais juge | 528 essais -> 43 "candidats" NQ ; apres retrait des regles degenerees, **zero** | attendu sous H0 : 26 gagnants par hasard |
| 06/09 | le verdict du dashboard vient du **backend** | deux implementations divergentes, 10,6 % de desaccord sur ES | 253 ecarts sur 258 : l'ecran agit, le bot attend |
