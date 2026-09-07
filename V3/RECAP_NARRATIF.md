# LE MODULE NARRATIF (F23) — récap complet pour avis extérieur

*Écrit le 08/09/2026 pour être soumis à une IA tierce, sans autre contexte que
ce document et le dépôt `github.com/jackson97300/mia-v3`. Les questions
ouvertes sont en §6 — c'est l'avis demandé.*

---

## 1. Le contexte en cinq lignes

MIA v3 est un système de trading **full rules** (pas de ML au cycle 1) sur ES
et NQ futures micros, barres 15 min, construit couche par couche : L0
(a-t-on le droit de trader), REG (régime), L1 (biais), L3 (déclencheurs), L4
(confirmation order flow), L5 (risque). Chaque couche est mesurée sur ~60
jours avant d'agir ; tout refus est journalisé avec son devenir ; rien ne
change pendant une campagne ; lecture unique au jour 61. Trois bots
précédents sont morts sans qu'on sache jamais *pourquoi* ils refusaient ou
prenaient un trade — V3 est construit contre ça.

## 2. La genèse de l'idée

Trois sources convergentes :

1. **L'intuition du trader** (Jackson, discrétionnaire, 10 000 h+) : *« des
   fois on trade un niveau qui a été défendu plusieurs fois et on ne le sait
   pas »*. Son ancien dashboard montrait l'histoire à l'œil ; rien ne la
   stockait.
2. **La faiblesse mesurée du biais-photo** : B1 (« le prix est au-dessus de la
   VWAP semaine ») a une couverture de 100 % — il a toujours un avis, donc il
   ne dit rien — et sa séparation est nulle ou inversée. Un desk n'appelle pas
   « biais » une photo mais une **histoire** : *testée trois fois par le
   dessous, elle a tenu, les défenses s'affermissent*.
3. **Wyckoff** : effort et résultat, à chaque test. Compter les tests ne
   suffit pas ; c'est *comment* le niveau a tenu qui prédit le test suivant.

D'où F23 : **une fiche par test d'un niveau de référence** (VAH/VAL/VPOC du
jour et de la veille), sur clé de session, avec six dimensions — effort
(volume relatif), qui pousse (delta, ask/bid), contexte cumulé (CVD), forme
(mèches, finish), gros ordres, et **résultat** (excursion dans le sens du
rejet). Issue ∈ {tenu, cassé, regagné}, et si cassé : le **piège** — volume et
delta échangés au-delà avant le regain, comptés sur les barres 1 min.

## 3. Le cheminement — chaque étape corrigée par une mesure

| étape | ce qu'on croyait | ce que la mesure a dit | correction |
|---|---|---|---|
| touche = proximité | « barre à ≤ z ATR du niveau » | 38–53 % des barres, **14 touches/jour** (la VA contient 70 % du volume : le prix y séjourne) | **hystérésis** : s'éloigner de 0,5 ATR pour re-tester → 1,2–1,6/jour, et le compteur discrimine (2, 3, 4 tests existent dans 45 % des cas) |
| l'issue est lisible à la barre du test | filtre sur l'indice du test | **fuite d'avenir** : 5 fiches sur 6 ont une issue connue jusqu'à 6 barres (90 min) plus tard | chaque fiche porte `i_connu` ; rien n'est révélé avant ; test dédié |
| le côté se lit à la clôture | signe de dist à la barre i | une barre qui monte et clôture au-dessus était « testée par le dessus » — issue, réaction, piège inversés | le côté se lit sur **d'où le prix venait** (barre i−1) |
| regain = un retour | 1 clôture revenue | un aller-retour d'une barre comptait comme regain | **symétrie** : 2 clôtures, comme la cassure (acceptation de Dalton) |
| le récit peut résumer | prose libre | « cassée 03:00 » désignait une cassure de 04:15 (la fiche horodatait le test) ; contre-lecture manuelle : 0 volume sous le niveau dans la fenêtre annoncée | le récit est **un test** : niveau EN PRIX, heure de CHAQUE événement, chiffres **recomptés depuis les barres brutes à chaque exécution**, écart > 5 % = refus de publier |
| niveaux du jour = niveaux de la veille | même traitement | les écarts fiche/recomptage ne touchent QUE les niveaux **dynamiques** (cur_*) sur 3 jours × 2 instruments — le niveau bouge entre le test et la cassure | fiches `prev_*` fiables ; `cur_*` **en quarantaine** jusqu'au correctif (piège contre le niveau de chaque barre) |
| « piégé » = volume au-delà | 200 538 contrats « piégés » sous la VAH (04/09) | **delta −534 sur 200 538 = 0,27 %** : une rotation à deux sens, personne de net coincé. Les vrais épisodes font 4–6 % | « piège » exige un **déséquilibre** au-dessus d'un seuil sur distribution ; sinon le lexique dit « rotation au-delà » |

Deux leçons transverses : **un lexique est un ensemble de seuils, pas de
métaphores** (même faute que « ORIENTE » sans regarder le signe) ; et le
narratif est **séduisant** — trois briques de récit construites le jour où la
couche prioritaire (L4) n'a pas avancé. C'est noté comme un risque de
processus.

## 4. L'état actuel

- `CORE/features/f23.py` : les fiches, testées au tick (7 contrôles, dont
  anti-fuite d'avenir et symétrie cassure/regain) sur 2 journées réelles.
- `V3/recit.py` : le récit auto-vérifié — 3 journées, 2 instruments ; exact
  sur les niveaux statiques, refuse de publier quand les dynamiques divergent.
- Quarantaines actives : fiches `cur_*` ; mot « piège » sous condition de
  déséquilibre ; et l'inventaire lui-même est traité en **hypothèse**
  (H-PIÈGE, pré-enregistrée, lue au jour 61).
- Usage prévu, jamais câblé : **machine** — 4 scalaires par niveau
  (`n_tests`, `defense_tendance`, `cvd_cote_defense`, `piege_proche`) lus par
  le biais narratif B1n et les déclencheurs L3, en observation ;
  **discrétionnaire** — une « carte des stocks » à 9h25 (une ligne par niveau,
  triée par distance : tests, issues, déséquilibre au-delà, âge) + le journal
  manuel qui note l'état de la carte au moment du clic. Règle dure : **la
  carte décrit, elle n'ordonne jamais** — toute influence sur une couche est
  une hypothèse pré-enregistrée et mesurée, jamais un câblage.

## 5. Ce que nous croyons avoir compris

Un desk ne consomme pas une histoire mais un **inventaire d'obligations** :
qui est coincé où, et qui devra faire quoi. La valeur du narratif n'est pas de
prédire le prix mais de rendre l'état du terrain **contre-lisible** — chaque
affirmation recomptable à la main depuis les barres. Et un récit qui ne peut
pas refuser de publier est plus dangereux que pas de récit du tout : il a
l'autorité du chiffre sans en avoir la discipline.

## 6. Les questions ouvertes — l'avis demandé

1. **L'inventaire sans open interest.** Nous voyons le volume et le delta
   échangés au-delà d'un niveau, pas qui tient encore sa position. Le
   déséquilibre `|delta|/volume` est-il un proxy défendable du « net piégé » ?
   Quel seuil, et posé comment ? Existe-t-il une meilleure construction avec
   volume/delta/temps seuls (pas de carnet, pas d'OI intrajour) ?
2. **La décroissance du carburant.** Les stops des piégés se retirent, les
   positions se ferment. Comment modéliser/mesurer l'âge au-delà duquel un
   piège ne « doit » plus rien — sans introduire un paramètre libre de plus ?
3. **Les niveaux dynamiques.** VAH/VAL/VPOC du jour bougent entre le test et
   la cassure. Piège compté contre le niveau de chaque barre, contre le niveau
   figé au test, ou faut-il ne raconter que les niveaux figés ? Y a-t-il un
   sens à « tester » un niveau qui se déplace ?
4. **La machine à confirmation.** Le récit ne parle que des 6 niveaux qu'on
   regarde, et 30–50 fiches/jour garantissent qu'une aura l'air prophétique.
   Comment structurer la validation de la *valeur prédictive* d'un narratif
   (états → devenirs) sans data mining — au-delà de nos réflexes actuels
   (pré-enregistrement, IC par blocs semaine, contrôle négatif à 1 000
   tirages, lecture unique au jour 61) ?
5. **L'acceptation à deux clôtures 15 min.** Définition unique pour cassure et
   regain, tous niveaux, toutes heures. Trop rigide (une cassure de 20:00
   n'a pas deux barres devant elle) ? Trop lâche la nuit (volume mince) ?
6. **Le lexique.** « Tenu », « défense », « s'use » — quels autres mots de
   notre vocabulaire embarquent une conclusion non mesurée, comme « piégé »
   l'a fait ?
7. **La frontière description/décision.** La carte « décrit, n'ordonne pas »
   — mais un trader discrétionnaire qui la lit est influencé par construction.
   Comment garder l'outil falsifiable quand son consommateur est un humain ?
   (Notre réponse actuelle : journaliser l'état de la carte à chaque clic et
   mesurer au jour 61. Est-elle suffisante ?)
8. **Ce que les desks font réellement.** Notre modèle du « pro » (niveaux,
   temps, inventaire, effort) vient de Dalton/Wyckoff et de l'expérience d'un
   trader. Quels éléments de la pratique réelle des desks intraday manquent à
   cette fiche — et lesquels sont des mythes qu'on s'apprête à mesurer pour
   rien ?

*Répondre avec des mécanismes mesurables sur OHLCV+delta 1 min, pas des
principes. Tout ce qui exige une donnée que nous ne collectons pas (carnet,
OI intrajour) doit le dire explicitement.*
