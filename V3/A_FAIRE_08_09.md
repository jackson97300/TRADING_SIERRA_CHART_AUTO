# A faire — 08/09

## REVUE FABLE (commit 01cb645) — 5 bloqueurs AVANT le tag campagne-ombre-1

1. **campagne.yaml fige sur des chiffres 5 min** : ajouter `unite_decision: 15min`,
   couts en ATR-15m (MES 3,8 %, MNQ 0,9 %, mesures 06/09). AVANT le tag.
2. **news_calendrier.source** : campagne.yaml POINTE vers
   layers/L0_interrupteur/seuils.yaml, il ne redecrit pas. Une seule verite.
3. **defenses_du_niveau lit les compteurs C++ faux** (vah_touches_20b=20/20
   dans une VA de 7 pts) : la porte observee lit les fiches F23, sinon 60 jours
   d'un compteur qu'on sait faux. Peut attendre la semaine 1 SI ecrit ici.
4. **L3 absente du miroir** : les 4 declencheurs vivent dans
   CORE/research/hypotheses.py. Minimum : layers/L3_declencheurs/SPEC.md avec
   les 4 definitions GELEES + H6/H8 marques non testables ce cycle.
5. **STATUS contradictoire** : L0-live « PASSEE » ET « le bot ne l'emprunte
   pas ». Le faux live prouve un CHEMIN, pas un branchement -> L0-live repasse
   « mesuree » tant que rien ne l'emprunte. Et L4 n'est plus « absente ».
   (fait ce 08/09 : pourquoi.py L2 -> REG ; vix_level=0 -> TROU, commit 01cb645+)

# — lecture des barres de nuit —, tire de la lecture des barres de nuit (Fable)

*Treize barres NQ + quatorze ES, 07:36-07:51 UTC, session Londres. Chaque point
vient d'une donnee reelle, pas d'un synthetique. La prochaine session commence ici.*

1. **VIX la nuit : `vix_level = 0.0` et `vix_regime = 1` quand meme.** Le defaut
   dans le domaine, cas reel. `L0` doit voir `vix_level == 0` -> `TROU_VIX`,
   jamais laisser regime=1 passer pour une lecture. A 9h30 cash, vix encore a
   0 = panne du study, L6 le dit. **Passer ces barres reelles en faux live** :
   VIX en trou, SESSION bloque, DATA_* passent — sinon L0-live n'est pas branchee.
2. **Les trois ATR sont identifies** : `atr` = JOURNALIER en points, `atr_14m` =
   1 min en ticks, `atr_barre` = 15 min en points (rapport 6,03 = jour/15min).
   Une ligne dans CONVENTIONS.md.
3. **`finish_delta_pct` depend de l'instrument** : binaire sur NQ, gradue sur ES
   (denominateurs 5/8, 3/7). Pas « saturee » : DEUX colonnes sous un nom. H3
   jugee sur deux grandeurs differentes. `finish_strength` (signe, gradue) est
   peut-etre la bonne colonne — a definir. Incident a requalifier.
4. **Les ctx_* relus ne reproduisent PAS les donnees** : absorption true a
   delta=+20 (seuil relu 30), climax false a vol_z 2,14 (seuil relu 1,0).
   AVANT J2 : test de reproduction sur 2 jours, mismatch = 0, comme la parite
   direction(). Sans ca « recalcule selon la formule » n'a pas de sens.
5. **`im_smt_divergence` asymetrique** (ES -1, NQ 0 au meme ts) : B4 lit UNE
   des deux, toujours la meme, ecrit dans seuils.yaml L1.
6. **Le bug ticks/points VIT dans la collecte** : sess_range_atr = 1,206 (75
   ticks / 62 points), dist_vwap_d_atr pareil. Colonnes C, personne ne les lit,
   mais L6 le dit UNE fois pour la correction C++ groupee.
7. **Proxys auto-declares** : `_mq_gamma_source: sierra_proxy_v2` — lecture.py
   refuse mecaniquement toute colonne dont la _source contient `proxy`.
8. **Cas reel pour le test au tick F23** : ES 07:51, 402 contrats, delta +126,
   rvol 2,5, sous la VAH avec mur GEX a 1 tick — la fiche de test ideale.
9. `vah_touches_20b = 20/20 barres` dans une VA de 7 pts : le compteur C++ dit
   « touche » pour « proximite » — confirmation que F23 recalcule a raison.
10. Reset hebdo confirme sur les DEUX instruments (vwap_w = vwap_d un lundi).
