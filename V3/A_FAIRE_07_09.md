# A faire — 07/09

*Fichier d'abord nomme `A_FAIRE_08_09` : les documents portaient la date du
lendemain alors que l'horloge etait au lundi 07/09 (le rapport de session le
dit). Renomme le 07/09 a la revue Fable — une date de fichier qui ment est le
genre de chose que `pourquoi.py` cherchera un jour a 21:01. Les mentions
« nuit du 08/09 » dans le corps datent de la meme confusion : c'etait la nuit
du 06 au 07/09.*

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

## 11. CONTRE-LECTURE F23 sur la nuit du 08/09 : DEUX ECARTS, a diagnostiquer AVANT de se servir des fiches
- F23 dit « prev_val cassee 03:00, 2540 contrats pieges » ; les barres brutes montrent
  ZERO cloture ni volume sous 7712,50 entre 03:00 et 04:00. Suspect n.1 : la reference
  « veille » CHANGE pendant la nuit (limite de journee de trading) — dist_prev_val a 03:00
  ne pointe peut-etre pas le meme jour qu'a 09:35. Regle 13 : deux conventions d'abord.
- Piege VPOC : F23 dit 8526/+498, la main dit 1376/+252 — la fenetre i_debut->i_connu et
  le niveau reconstruit (close+dist*tick a i_debut) doivent etre JOURNALISES dans la fiche
  pour etre verifiables. Sans ca, une fiche n'est pas contre-lisible.
- ACTION : test au tick de F23 etendu a une session de NUIT + la fiche porte le niveau
  reconstruit en prix. Tant que ce n'est pas vert, les fiches ne nourrissent NI le
  discretionnaire NI B1n.

## 12. LE RECIT F23 — demande Jackson 08/09 : F23 raconte EXACTEMENT, sans grain de sel
Principe : une fiche = des FAITS contre-lisibles ; le recit = un rendu mecanique
des fiches, aucune interpretation libre.
- chaque fiche porte : le NIVEAU EN PRIX (reconstruit, verifiable), la fenetre
  [ts_debut, ts_fin] en clair, le volume/delta RECOMPTABLES a la main ;
- chaque phrase du recit porte sa preuve entre parentheses : « VAL 7712,50
  testee 03:00 (plus bas 7712,75, 0 volume dessous) — PAS de cassure » ;
- le lexique est FERME et defini une fois (touche/tenue/cassure/regain/piege,
  les 4 definitions existantes) — aucun mot hors lexique dans le recit ;
- « piege » ne se dit que si volume_au_dela est recomptable ; sinon le recit
  dit « cassure sans volume mesurable au-dela » ;
- un mode --verifier recompte chaque chiffre du recit depuis les barres brutes
  et echoue au premier ecart : LE RECIT EST UN TEST, pas une prose.
Livrable : `V3/recit.py` (lit les fiches, rend le recit du jour) + extension du
test au tick. C'est la brique qui sert le discretionnaire (briefing 9h25).

## 13. LA CARTE — comment le recit se CONSOMME (Jackson 08/09, ultra-think)
Un desk ne lit pas de la prose : il tient une CARTE DES STOCKS. Livrable
`V3/carte.py`, meme fiches que le recit, autre rendu :
- une ligne par niveau, triee par distance au prix, A L'INSTANT t :
  `VAL_veille 7712,50 | -0,8 ATR | 3 tests, 2 tenus, defense s'use (0,4) |
   1 900 shorts pieges dessous (04:15, age 5h)`
- l'INVENTAIRE est la colonne decisionnelle : des longs pieges au-dessus =
  vendeurs sur tout retour (carburant baissier) ; des shorts pieges dessous =
  acheteurs en dessous. C'est ce que les pros lisent : pas « que va faire le
  prix » mais « qui DOIT faire quoi ».
- le recit (prose) = piste d'audit ; la carte = surface de decision. MEMES
  fiches, deux rendus — jamais deux calculs.
- consommation MACHINE : les scalaires F23 dans L1/L3 (deja specifie).
  consommation DISCRETIONNAIRE : carte a 9h25 + maj a chaque fiche nouvelle ;
  le journal MANUEL note l'etat de la carte au moment du clic — c'est ainsi
  que l'instinct devient mesurable au jour 61.
- REGLE : la carte n'ordonne rien, elle decrit. Tout passage « la carte
  influence une couche » est une hypothese pre-enregistree, jamais un cablage.

## 14. AUDIT DU RECIT (Jackson 08/09) — six trous, dont un prouve par nos donnees
1. **« PIEGE » ment sur 200 538 contrats.** ES 04/09, prev_vah : volume 200 538,
   delta -534 -> |d|/vol = 0,27 %. C'est une ROTATION a deux sens, personne n'est
   net coince — et notre lexique a appele ca un piege. Un piege exige un
   DESEQUILIBRE : seuil |delta|/volume a poser sur distribution, PAR EPISODE.
   Renommer le champ `volume_au_dela` (fait) et n'ecrire « piege » dans le recit
   QUE si le desequilibre passe le seuil. Sinon : « rotation au-dela ».
2. **L'inventaire est une HYPOTHESE, pas une lecture** : on voit le volume
   echange au-dela, pas qui tient encore la position (pas d'open interest).
   H-PIEGE a pre-enregistrer : les regains a fort desequilibre produisent-ils
   des reactions plus fortes ? Mesure au jour 61, jamais crue avant.
3. **Le carburant expire** : age du piege non teste (stops retires, clotures).
4. **Selection** : le recit ne parle QUE des 6 niveaux qu'on regarde. La carte
   montre TOUS les niveaux, y compris ceux ou il ne s'est rien passe — sinon
   c'est une machine a confirmation.
5. **Multiplicite** : ~6 niveaux x 5-8 fiches/jour = une histoire aura toujours
   l'air prophetique. Aucune lecture sur un episode isole.
6. **Le piege de la facilite EN PROCESSUS** : aujourd'hui 3 briques de recit,
   0 pas sur L4 J2 — le narratif est seduisant et demontrable, les vetos sont
   arides. La priorite de la semaine reste L4, la carte vient APRES.

## 15. AUDIT DIRECTION (Jackson 08/09) — le mode de mort de V1 est REPRODUIT, et l'antidote est mesure
Question : « NQ prend +400 points et le bot short toute la journee » — sommes-nous proteges ?
MESURE sur 60 jours, quintile superieur de |direction| (12 jours de tendance par instrument) :
- **NON par les declencheurs** : H3+H7 tirent a 97 % (ES) / 95 % (NQ) CONTRE le
  sens du jour les jours de tendance. Devenir des contre-tendance : -0,940 ATR
  (ES) / -0,540 (NQ) contre +1,31 / +0,67 pour les rares avec-tendance.
  C'est structurel : des fades vendent le haut — un jour de tendance haussiere,
  le haut ne cesse de monter. V1 est mort de ca ; nos declencheurs seuls le
  reproduiraient.
- **OUI par B5, et c'est mesure** : l'ouverture hors de la VA de la veille
  (regle des 80 % de Dalton, disponible a 9h30 SANS fuite) a donne le bon sens
  du jour **8/8 fois sur ES et 7/7 sur NQ** les jours de tendance ou elle avait
  un avis. Sur l'ensemble des jours elle n'est qu'a 62 % — sa valeur n'est pas
  de predire tous les jours, c'est de flaguer LES JOURS DE TENDANCE, exactement
  la protection qui manquait.
- RESERVES ecrites : n=8 et n=7 (binomial : 8/8 sous p=0,5 = 0,4 %, mais ES/NQ
  correles ~0,9 comptent pour un) ; mesure sur le lot qui a deja servi.
- **H-B5TREND pre-enregistree pour le jour 61** : les jours ou l'ouverture est
  hors VA veille, les signaux CONTRE le cote de B5 ont un devenir negatif ;
  attendu directionnel ecrit. Si elle survit, elle devient au cycle 2 la porte
  L1 « pas de fade contre B5 un jour d'ouverture hors valeur » — JAMAIS cablee
  avant.
- Ou F23 aide le biais : PAS a l'echelle du jour (c'est L1/B5) — a l'echelle du
  niveau (3e test, defense qui s'use, B1n). Le test « F23 aide-t-il » est
  l'etape 5 de REPONSES_NARRATIF : avec/sans dans B1n et H7.

## 16. ARBITRAGE JACKSON — le veto gamma : ENQUETE CLOSE le 07/09 au soir, le dossier est RETOURNE
L'enquete (option 3 de Fable, executee) : gamma_block_* n'est PAS un proxy.
`gamma_veto_engine` (SSoT 18/06, reviewe) le calcule depuis dist_mq_call/put
(murs collectes, A) + atr (threshold = clamp(0,5 x ATR, [10, 80]) — d'ou ES
~28 t variable et NQ fige au cap 80) + bool_gex_flip_zone (DMP natif,
DMP_Transform.h:1731). Le proxy sierra_proxy_v2 ne produit que le label
`mq_gamma_condition`, DERIVE de bool_gex_flip_zone — le proxy va dans CE
sens, jamais l'inverse. REPRODUCTION : 5 275 barres stables dedoublonnees
(2 j x 2 sym), 0 ecart. Le -0,48 ATR a ete mesure sur une entree PROPRE ;
la condamnation du matin etait une association de famille, corrigee dans
SOURCES_DECLAREES (mesure a l'appui). La « confrontation aux 11 signaux »
est la reproduction elle-meme : les signaux fermes l'ont ete par EXACTEMENT
cette formule sur ces entrees.
RESTE TON MOT : repasser la porte `appliquee` = une ligne de seuils.yaml,
un commit. Aucune exemption, aucune attente de source : il n'y a rien a
exempter.

## 16bis. (HISTORIQUE du matin, garde tel quel) — le veto gamma lisait un proxy
Le point 7 est execute : `lecture.py` refuse mecaniquement toute colonne
gouvernee par une `_source` contenant « proxy » (`SOURCES_DECLAREES`), et les
champs `_mq_gamma_source` / `_aggressor_source` survivent a l'agregation.
Consequence MESUREE : `gamma_block_long` (proxy sierra_proxy_v2, scraper mort
le 27/05) rend None -> `L5_VETO_GAMMA` rend un TROU permanent. En appliquee +
strict, ce trou fermait 100 % du live (test_faux_live cassait sur son cas
nominal — la preuve). La porte est donc passee **observee** (seuils.yaml) et
`campagne.yaml` dit desormais la meme chose. A trancher AVANT vendredi :
1. exemption explicite du proxy pour CE veto (le -0,48 ATR a ete mesure SUR le
   proxy — il peut proteger quand meme), documentee dans SOURCES_DECLAREES ;
2. ou attendre une source gamma propre (API MenthorQ morte — cf memoire) et
   laisser le veto en observation pendant la campagne.
Revert trivial par commit si desaccord. Rien d'autre ne change : rvol/frais
inchanges, la campagne demarre le 08/09 avec ce jeu de portes.

## 17. REPRODUCTION ctx_* PROUVEE (07/09) — et une colonne condamnee
Le point 4 est execute : `V3/tests/test_ctx.py` (8e controle de publier.sh),
mismatch = 0 sur 2 jours x 2 instruments x 24 colonnes. La relecture de la
nuit avait rate les conditions COMPOSEES (climax = vol_z > 2 ET range_pos
extreme ; absorption lit `bn_absorb_*`, pas le delta) — la formule du code
etait bonne, les « ecarts » etaient TROIS conventions, prouvees une a une :
1. le JSONL arrondit a 6 decimales ;
2. fichier decoupe par DATE UTC, pipeline par JOURNEE DE TRADING (reset
   22:00 UTC) — la reproduction exige chauffe veille + reset au boundary ;
3. blocs RE-EMIS (2 000 lignes pour 1 260 minutes le 04/09) → dedoublonner,
   comparer les barres `stable` seulement (la decision ne lit qu'elles).
**CONDAMNEE : `ctx_rvol_session`** — le producteur la contamine les jours a
re-emission (220 barres fausses par instrument le 04/09, 17:19→20:58, ratio
~0,46 : l'accumulateur de session compte les lignes re-emises). INTERDITE
pour L4. Correction : avec la dette C++/pipeline groupee (point 6 de la nuit).

## 18. RESTES DE LA REVIEW C2 DU SOIR (R3/S1/S4) — demain matin
- R3 : lire prev_vah_lvl/prev_val_lvl/open_cash_lvl (A) directement au lieu
  de reconstruire depuis dist_* ; a minima assert de concordance au bar 0.
  Ajouter lieu_prix, colonnes_lues{}, regime aux lignes signal du journal C2.
- S1 : FAIT le soir meme (predicat unifie sur la VA reconstruite). EFFET
  MESURE et il n'est pas neutre : le rejeu ES 04/09 passe de 1 a 3 signaux
  (15:00, 17:30, 19:15 UTC — trois episodes de re-acceptation que le flag
  C++ masquait). Le message du commit 6050ae0 disait « inchange » : FAUX,
  corrige au commit suivant. Lecon : re-mesurer APRES l'unification d'un
  predicat, pas avant.
- S4 : FAIT le 08/09 — test ACTIFS ⊆ LES_C2 + 8 cas par setup actif
  (test_ombre_c2.py, filtrage PAR SETUP), livre AVEC l'activation de C2_EOD.

## 19. DETTE est_cash DST — DEADLINE DURE 31/10 (review C2_EOD 08/09, R1)
`recalc.est_cash` est fige EDT (13:30-20:00 UTC toute l'annee). Des le
2/11 : la barre EOD 15h15 ET (20:15 UTC) est COUPEE par `charger_jour`
avant d'atteindre les setups (motif `barre_eod_absente` FAUX chaque jour),
l'open cash glisse a 8h30 ET (la definition de `rendement_r` casse), et le
N de C2_EOD plafonne sous 40 — invalidation structurelle silencieuse.
Fix : reecrire `est_cash` sur `minutes_et` (fenetre ET [570, 960)). Tache
SEPAREE cross-module (les quatre officiels, ombre16, VWAP RTH, F23, IB
lisent tous ce filtre) : review obligatoire + test de parite sur le lot
AVANT/APRES (attendu : zero barre changee tant qu'on est en EDT).
