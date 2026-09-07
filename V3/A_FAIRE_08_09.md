# A faire — 08/09, tire de la lecture des barres de nuit (Fable)

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
