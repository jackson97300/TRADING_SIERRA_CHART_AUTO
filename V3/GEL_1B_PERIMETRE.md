# GEL 1b — ce qui a change dans le perimetre gele depuis `campagne-ombre-1` (61d76a1, 08/09 09h06)

*Regenere le 11/09 a 10h45, APRES la revision de la regle 38 : la version d'hier soir ne la contenait
pas. Diff des SEULS fichiers du perimetre gele, entre `campagne-ombre-1` (miroir `61d76a1` = local
`eaf69be`) et la tete du miroir (`0e08ddc`). Ce qui n'a pas bouge a deja ete relu.*

## LIRE CECI EN PREMIER — la regle 38 a ete REVISEE ce matin, avant le tag

La version du 10/09 au soir coupait les deux jambes de H3 **pour le verdict**. Projection depuis le lot
sur 60 jours x 2 instruments : H3 entiere ~50, H3 short seul ~33, H3 long seul ~17, H6p ~24, H2p ~3,
H8p ~3. **H3 entiere est la seule case de toute la campagne au-dessus de N = 40** : la version d'hier
soir rendait la campagne incapable de conclure sur quoi que ce soit. La regle 9 l'interdisait deja dans
les deux sens (ni fusionner, ni decouper sous la puissance). Version revisee : le verdict porte sur H3
ENTIERE, la jambe est marquee (le `snapshot_id` finit deja par L ou S — aucune ligne de code a changer)
et lue descriptivement ; un resultat sur une jambe seule se pre-enregistre au cycle 2.

## Le nom du tag, et pourquoi il y en a deux

`campagne-ombre-1` reste sur `61d76a1` : un tag qui bouge n'est plus un tag. Le gel d'aujourd'hui
s'appelle **`campagne-ombre-1b`**. Phrase pour DECISIONS, a poser avec le hash au moment du tag :
*« Deux tags, deux dates, une seule campagne : `campagne-ombre-1` (61d76a1) a fige l'etat du 08/09 ;
`campagne-ombre-1b` fige l'etat CORRIGE — DST, unites, `atr_ref`, B3, A1 minimal, les regles 1-39 dont
la 38 revisee — sur lequel courent les soixante jours. Un lecteur du jour 61 doit pouvoir dire lequel
des deux a couru quel jour : le 08/09 et le 09/09 ont couru sous 1, du 10/09 au jour 60 sous 1b. »*

## Le stat

```
 DECISIONS.md                       |  37 ++++++++
 LECTURE_JOUR_61.md                 | 171 ++++++++++++++++++++++++++++++++++++-
 layers/L0_interrupteur/seuils.yaml |  66 ++++++++++----
 layers/L5_risque/seuils.yaml       |  14 ++-
 4 files changed, 267 insertions(+), 21 deletions(-)
CORE/research/hypotheses.py (local eaf69be..HEAD, hors miroir) : 1 file changed, 27 insertions(+), 17 deletions(-)
```

## seuils_c2.yaml — les setups C2

**Inchange depuis le 08/09** — deja relu.

## seuils.yaml L0 — les portes

```diff
diff --git a/layers/L0_interrupteur/seuils.yaml b/layers/L0_interrupteur/seuils.yaml
index 443ff3f..ec142d5 100644
--- a/layers/L0_interrupteur/seuils.yaml
+++ b/layers/L0_interrupteur/seuils.yaml
@@ -104,10 +104,10 @@ portes:
     mesure: "aucune decision avant que le regime soit lisible"
   L0_EOD_LOCKOUT:
     mode: appliquee
-    seuils: {cloture_utc_min: 1200, marge_min: 10}   # 20:00 UTC - 10 min
-    mesure: "REDONDANTE avec SESSION_BLOQUEE, pas inerte : 20h UTC est deja
-             100 % bloque en amont. Gardee car elle protege si le calendrier
-             economique tombe."
+    seuils: {cloture_min_et: 960, marge_min: 10}   # 16:00 ET - 10 = 15:50 ET
+    mesure: "seuil en MINUTES ET (DST-aware), pas UTC fige : en EST un
+             cloture_utc_min aurait bloque des 14h50 ET, mangeant la barre
+             15h15 de C2_EOD. REDONDANTE avec SESSION_BLOQUEE, gardee en filet."
 
   # === FAMILLE C — CONDITIONS DE MARCHE : le marche est-il tradable ? ======
   L0_VIX_REGIME:
@@ -119,7 +119,13 @@ portes:
              reveille c'est de la securite elementaire."
   L0_REGIME_INDETERMINE:
     mode: observee
-    seuils: {zone_morte_atr: 1.0}
+    # 0,25 et non 1,0 (arbitrage Fable C2, 09/09) : le YAML disait 1,0 par
+    # ERREUR D'UNITE (ticks divises par points dans _dist_hvl_atr) — la zone
+    # morte de 1,0 n'a JAMAIS existe. Le comportement mesure le 06/09
+    # (10,2 -> 1,8 bascules/jour) est celui de 0,25 ATR-15m : on ecrit ce qui
+    # a ete mesure. Zero changement de comportement (conversion x0,25 dans le
+    # code + seuil /4 = identite). Re-poser au cycle 2 sur distribution.
+    seuils: {zone_morte_atr: 0.25}
     mesure: "zone morte autour du HVL — combien de barres sans regime lisible ?"
 
   # === FAMILLE D — ETAT DU RISQUE : ai-je encore le droit de perdre ? ======
@@ -138,24 +144,33 @@ portes:
     seuils: {max: 12}
     mesure: "rang du signal dans la journee, execute ou non — le 15e vaut-il
              moins que le 3e ? Seuil provisoire : a caler sur la distribution."
+  # CORRECTION 09/09 (audit) : ces TROIS portes sont INERTES PAR CONSTRUCTION
+  # dans l'etat actuel — `etat["pnl_jour"]` et `etat["fin_cooldown"]` sont
+  # initialises par `chaine.etat_neuf()` et ECRITS NULLE PART (aucun trade
+  # simule n'alimente le P&L en ombre). Elles rendent False en toute
+  # circonstance : n=0 ne dit RIEN du marche. Ma phrase du 08/09 (« MESURABLE,
+  # jamais inerte par construction ») confondait deux choses : le SEUIL est
+  # atteignable (4,9 SL de 1 ATR sur NQ), mais la GRANDEUR n'est pas cablee.
+  # Cablage = cycle 2 (le fantome L0_POSITION_OUVERTE porte deja un pnl_atr
+  # simule — c'est la brique). Jamais pendant la campagne.
   L0_STOP_JOURNALIER:
     mode: appliquee
     seuils: {usd: -1000.0}
-    mesure: "PEU PROBABLE sur NQ (4,9 SL de 1 ATR), improbable sur ES (13,2) —
-             MESURABLE, jamais « inerte par construction » (revue 08/09 A2 :
-             ses propres chiffres disaient le contraire). Si une seance NQ
-             ferme dessus, LECTURE_JOUR_61 regle 16 la lit A PART."
+    mesure: "INERTE PAR CONSTRUCTION (pnl_jour jamais ecrit) — cf bloc ci-dessus.
+             Le seuil lui-meme reste atteignable : si le cablage arrive et
+             qu'une seance NQ ferme dessus, LECTURE_JOUR_61 regle 16 la lit A PART."
   L0_STOP_PROPFIRM:
     mode: observee
     seuils: {usd: -200.0}
-    mesure: "la vraie regle Douglas — combien de jours coupes ?"
+    mesure: "INERTE PAR CONSTRUCTION (pnl_jour jamais ecrit). La vraie regle
+             Douglas — combien de jours coupes ? — attend le cablage cycle 2."
   L0_COOLDOWN:
     mode: observee
     seuils: {apres_perte_min: 90, apres_gain_min: 60}
-    mesure: "90/60 min, PAS les 3/5 min de janvier. Raison : en barres de 15
-             min, un cooldown de 3 min ne saute meme pas une barre — il ne
-             pourrait rien empecher. 90 min = six barres. A trancher sur la
-             mesure quand il se declenchera : il ne l'a jamais fait en 57 jours."
+    mesure: "INERTE PAR CONSTRUCTION (fin_cooldown jamais ecrit). 90/60 min,
+             PAS les 3/5 min de janvier (en 15 min, 3 min ne saute pas une
+             barre). « il ne s'est jamais declenche en 57 jours » etait vrai
+             pour une mauvaise raison : il ne POUVAIT pas."
 
   # === FAMILLE E — ETAT DE L'EXECUTION : puis-je passer l'ordre ? ==========
   L0_POSITION_OUVERTE:
@@ -165,7 +180,13 @@ portes:
              Bloque l'entree, ne bloque PAS la mesure : chaque signal qu'elle
              ferme est simule en trade fantome complet — rapports/fantomes_57j.txt"
   L0_CONTRAT_INACTIF:
-    mode: appliquee
+    # ROLLOVER 10/09, ligne B (ROLLOVER_10_09.md, DECISIONS 10/09 10h01) : les
+    # fichiers du 10/09 ouvrent en U26 (ES 480 / NQ 481 lignes, 100 %) alors
+    # que contrat_actif dit Z26 — le roll calendaire est celui du CME, pas de
+    # Sierra. Bloquer toute la seance sur un decalage d'horloge serait un
+    # faux TROU : OBSERVEE pour le 10/09, remise `appliquee` des qu'un
+    # fichier OUVRE en Z26 (a verifier le 11/09 au matin, une ligne DECISIONS).
+    mode: observee
     seuils: {}
     mesure: "contrat du JSONL != contrat du compte — a brancher avant le 10/09"
   L0_DTC_DECONNECTE:
@@ -185,11 +206,24 @@ portes:
     # du matin etait une association de famille (SOURCES_DECLAREES corrigee).
     # RESTE LE MOT DE JACKSON : repasser appliquee = changer cette ligne,
     # un commit. Cf A_FAIRE point 16, DECISIONS 07/09 soir.
+    # A1 CORRIGE EN FORME MINIMALE (passe lecture 10/09) : `_gamma` lit le
+    # SENS — un LONG lit gamma_block_long, un SHORT rend un TROU
+    # (gamma_block_short n'est PAS dans l'agregation 15 min). NE PAS repasser
+    # appliquee AVANT la passe complete : en strict, le trou bloquerait TOUS
+    # les shorts. Les longs sont mesures, les shorts non (LECTURE regle 36).
     mode: observee
     seuils: {}
     mesure: "mur gamma dans le sens du TP — voir rapports/portes_57j.csv"
   L5_VETO_RVOL_EXTREME:
-    mode: appliquee
+    # OBSERVEE depuis le 09/09 (arbitrage Fable C3) : le z lu est celui de la
+    # DERNIERE MINUTE du bloc 15 min (bot_terminal, famille ETATS .last()).
+    # Mesure : NQ 64 blocages avec la derniere minute, ZERO avec la barre
+    # reconstruite (moyenne ponderee volume) — 100 % d'artefact d'agregation.
+    # Un veto applique qui bloque sur un artefact n'est pas une protection,
+    # c'est un biais actif sur un instrument. L'agregation juste (73 / 0 /
+    # 25 / 401 sur ES selon la definition) se tranche au cycle 2 SUR
+    # DISTRIBUTION — pas en campagne. Re-application = ligne DECISIONS.
+    mode: observee
     seuils: {zscore_max: 3.0}
     # DEUX DEFINITIONS EXISTENT, ET ELLES NE SE REMPLACENT PAS.
     #   `rvol_zscore`  volume inhabituel par rapport au passe RECENT (intraday)
```

## seuils.yaml L5 — vetos et barrieres

```diff
diff --git a/layers/L5_risque/seuils.yaml b/layers/L5_risque/seuils.yaml
index da1e301..8f17387 100644
--- a/layers/L5_risque/seuils.yaml
+++ b/layers/L5_risque/seuils.yaml
@@ -4,7 +4,19 @@
 #
 # Les PORTES L5 (veto gamma/rvol/frais) restent dans
 # layers/L0_interrupteur/seuils.yaml — une seule verite, on ne demenage pas
-# un fichier que la chaine lit. Ce fichier-ci ne porte que les BARRIERES.
+# un fichier que la chaine lit. Ce fichier-ci porte les BARRIERES et la table
+# de sortie horaire (C3).
+
+# Plat au plus tard, PAR FAMILLE (C3, audit Fable 09/09) — une DEFINITION, pas
+# un seuil tune : C2_EOD est le trade de la derniere demi-heure (JFE 15h30 ->
+# cloture), sa sortie EST la cloture cash (960) ; les autres familles sortent
+# au plat de fin de journee (955 = 15h55, cf L0_EOD_LOCKOUT / jamais overnight).
+# Une famille absente prend `defaut` ET le journalise (sortie_source), jamais
+# en silence. Aucune distribution ne deplace une borne de seance.
+sortie_horaire_et:
+  defaut: 955
+  par_famille:
+    C2_EOD: 960
 
 barrieres:
```

## campagne.yaml

**Inchange depuis le 08/09** — deja relu.

## test_spec_l3.py — LES_QUATRE epinglees

**Inchange depuis le 08/09** — deja relu.

## LECTURE_JOUR_61.md — les regles 1-39

```diff
diff --git a/LECTURE_JOUR_61.md b/LECTURE_JOUR_61.md
index ef00170..82c8cd4 100644
--- a/LECTURE_JOUR_61.md
+++ b/LECTURE_JOUR_61.md
@@ -48,9 +48,12 @@ complète par commit AVANT le jour 61 ; il ne se modifie plus après.*
     `atr_barre` NaN 9h30-11h00 — min_periods = 7). La sous-population
     « avant 11h00 » de la règle 1 est **VIDE PAR CONSTRUCTION**, pas par le
     marché : toute phrase du type « la stratégie ne marche pas le matin »
-    est INTERDITE au jour 61 — elle n'y a pas été essayée. L'IB et la
-    première heure sont un angle mort ASSUMÉ de la campagne gelée ; le
-    cycle 2 lit `atr_ref` (ATR-veille en secours, la solution L1). ET LE
+    est INTERDITE au jour 61 — elle n'y a pas été essayée. **Corrigé le
+    09/09 (brique 1 Fable, DECISIONS)** : depuis le jour 1 REJOUÉ, les
+    quatre et les seize lisent `atr_ref` (ATR de la dernière session
+    complète en secours) — la sous-population du matin EXISTE, elle porte
+    `atr_source = veille` et se lit À PART (règle 15 étendue) ; les jours
+    L6 `echelle_douteuse` (gap ≥ 2 ATR-veille) à part encore. ET LE
     TABLEAU DIT PLUS (revue 08/09, B7) : H3-VPOC fait 13/4/2 signaux ES et
     8/5/2 NQ sur les tranches 11h-13h / 13h-15h / 15h-16h — **les quatre
     gelées sont, EN PRATIQUE, un setup de 11h00-13h00**. Un H3 lu sur 60
@@ -82,7 +85,12 @@ complète par commit AVANT le jour 61 ; il ne se modifie plus après.*
     HAUT. Une ouverture au-dessus, un tour SOUS la VA, puis une ré-entrée
     par le bas : l'ouverture n'est plus la référence — le cas `mixte` se
     lit À PART, jamais mélangé au cas Dalton.
-15. **DIV_DELTA v2 se lit en séparant `atr_source`** (revue 08/09, C) :
+15. **DIV_DELTA v2 — et depuis le 09/09 LES QUATRE et LES SEIZE (brique 1) —
+    se lisent en séparant `atr_source`** (revue 08/09, C ; les lignes
+    antérieures à la brique — intentions du 04/09, journaux ≤ 08/09 non
+    rejoués — n'ont pas le champ : absent = `barre`, un PASSE n'existait que
+    sur `atr_barre` fini ; les jours L6 `motif = echelle_douteuse` ou
+    `rollover` se lisent à part encore) :
     un lieu à 9h35 sur l'ATR de la VEILLE dans une journée à gap de 2 ATR
     est un lieu sur une échelle fausse pour CETTE journée. Les signaux
     `veille` et `barre` sont deux populations — la colonne est dans chaque
@@ -92,6 +100,161 @@ complète par commit AVANT le jour 61 ; il ne se modifie plus après.*
     (4,9 SL de 1 ATR sur NQ) — si une séance ferme dessus, ses signaux
     post-fermeture n'existent pas dans le journal officiel, et la comparer
     aux journées pleines fausserait les deux.
+17. **La nuit du jour 1 n'a PAS de preuve live** (INCIDENT 08/09 : le
+    coureur ne basculait pas de journée — le journal live du 08 commence
+    vers 10:30 UTC, pas à 22:00 la veille). Elle se lit comme un TROU,
+    jamais comme une nuit calme. Le rejeu de 21:01, lui, couvre la journée
+    entière — c'est pour ça qu'il est LA mesure et que le live n'est que
+    la preuve.
+18. **Jour 1 (08/09) : le journal live est un RODAGE — il ne fait pas foi**
+    (verdict Fable 08/09). `ts` empoisonné (méga-secondes, pandas 3 VPS),
+    motifs faux (`L0_FERIE_CME` fantôme du 1er janvier 1970,
+    `L0_DATA_PERIMEE` d'un âge de 56 ans) jusqu'au fix de ~16:30 UTC. Seul
+    le rejeu 21:01 fait foi ce jour-là. Le live fait foi à partir du
+    premier jour où le battement porte `env` (versions python/pandas/numpy)
+    ET où `test_agreger_ts.py` est vert SUR le VPS. Le fichier empoisonné
+    est conservé renommé `_rodage` — pièce d'incident, jamais supprimé.
+
+18b. **`POSITION_OUVERTE` : le journal LIVE ne fait pas foi dessus, jusqu'au pas
+    2b** (audit Fable 09/09, A4 ; défaut `PLAN_ENTREE_EXEC` §0). En live,
+    `triple_barriere` ne voit pas la sortie future → `libre_a = −1` → la porte
+    ne ferme rien → DEUX `PASSE` simultanés possibles sur un instrument. Le
+    REJEU 21:01 a le futur : `libre_a` juste, un seul PASSE. Sur CETTE porte, la
+    mesure = le rejeu, jamais le live, tant que le câblage sur l'état réel (pas
+    2b, après le gel) n'est pas fait.
+
+## Les réactions aux niveaux (`reactions.py`) — règles écrites AVANT la donnée
+
+*Ajoutées le 08/09 au soir, avant la première ligne du journal. Un journal
+sans sa règle de lecture est un jeu de données à miner (incident 28/04).*
+
+19. **Unité statistique** : le TEST pour les lignes `type=test`, le
+    JOUR-INSTRUMENT pour `niveau_jour`. Jamais mélangées dans une phrase.
+20. **Lecture par CLASSE** : primaires d'abord, secondaires à part avec leur
+    `derive_niveau_atr`, et `vwap_d` en TÉMOIN. **Un niveau primaire qui ne se
+    distingue pas du témoin n'est pas un niveau : c'est une heure.**
+21. **Test de permutation obligatoire** : mélanger les étiquettes `niveau`
+    entre fiches d'une même journée, 1 000 fois. Si la séparation réelle est
+    sous le p95 du mélange, F23 décrit l'heure ou le régime, pas le niveau.
+22. **`issue` se lit en composition à quatre voies**, jamais en taux de
+    réussite : « 55 tenu sur 80 » n'est pas 69 % de réussite.
+23. **Symétrie obligatoire** : `exc_rejet_atr_4` et `exc_poursuite_atr_4` se
+    lisent CÔTE À CÔTE, jamais l'un sans l'autre. `reaction_atr` (hérité de
+    f23) est ASYMÉTRIQUE — il ne se lit jamais seul.
+24. Les fiches à `barres_restantes < 8` sont **censurées à droite** : lues à
+    part ou exclues, décidé avant de regarder.
+25. Une ligne à `motif_zero != null` ne compte **JAMAIS** comme « ce niveau
+    n'a pas marché » — la colonne était absente, vide, ou le prix n'est
+    jamais venu.
+26. Jours `ferie` et demi-séances **à part** (07/09 = Labor Day est déjà dans
+    le lot).
+27. ES et NQ comptent **1,3**, pas 2 (règle 2). Aucun épisode isolé (règle 3).
+28. **Aucune phrase de devenir.** Ce journal ne porte ni gain, ni R, ni
+    entrée, ni sortie, ni stop. « Ce niveau a marché » est un contresens
+    d'usage : le fichier dit ce que le marché a FAIT, jamais ce qu'il aurait
+    fallu faire.
+
+## Le devenir (`triple_barriere`) — CORE confronté à la référence (09/09)
+
+*Rangées dans la plage jour-61 (29-34) ; 29-32 réservées à la lecture des
+devenirs par famille. Écrites après la confrontation `research/parite_barriere`.*
+
+33. **Une `EXPIRATION` de CORE sur la dernière barre cash (945 = 15h45) est un
+    EOD** — un trade coupé par la clôture, pas un trade qui a duré 20 barres. La
+    confrontation 09/09 (`research/rapports/parite_barriere.txt`) le chiffre :
+    sur 70 signaux des quatre, **22 `EXPIRATION → EOD`** (MÊME prix, étiquette
+    CORE fausse), répartis 11h-15h — **un tiers dès 11h** : la barrière 20 barres
+    (5h) dépasse la clôture pour tout signal après ~11h, l'EOD est le vrai plafond.
+    **Zéro écart de `pnl_atr`** entre CORE et la référence sur les 66 résolus :
+    CORE n'a pas tort sur le PRIX, seulement sur le NOM. Les devenirs se lisent
+    en SÉPARANT `EOD` des vraies `EXPIRATION`.
+34. **Trois jours ont une donnée cash TRONQUÉE** (dernière barre < 945) : `09/07`
+    (Labor Day, demi-séance — attendu), `09/09` (collecte en cours — attendu),
+    `08/05` (**inexpliqué, à investiguer**). CORE y fabrique une `EXPIRATION` sur
+    une barre trop précoce ; la référence dit `INDETERMINE`. À lire comme un TROU
+    de données, jamais un devenir. La correction de CORE (étiquette `EOD` +
+    20 barres détenues) attend le CYCLE 2 : la campagne est gelée sur CORE,
+    changer le moteur des devenirs en cours ferait deux populations de mesures.
+
+35. **Le silence des quatre se lit en `lieu_min_ticks`** (brique 2 Fable,
+    09/09 — `marges_quatre_<jour>.jsonl`, une ligne par hypothèse × instrument,
+    MÊME les jours muets, parité barre à barre avec les fonctions gelées
+    prouvée par `test_marges_quatre`). « Bande trop serrée de X ticks sur N
+    jours », « lieu atteint, réaction manquante = finish sur M jours » sont
+    des CALIBRATIONS pour le cycle 2 — JAMAIS une permission d'élargir une
+    bande ou de desserrer une réaction pendant la campagne. QUASI n'est pas un
+    signal manqué : c'est une distance. La seule phrase autorisée a la forme
+    « à seuil × k, N passerait de A à B », et elle se prononce au jour 61.
+
+36. **`L5_VETO_GAMMA` se lit sur les LONGS seulement** (A1, forme minimale,
+    passe lecture 10/09) : CHAQUE short depuis le 10/09 porte une ligne
+    `TROU_L5_VETO_GAMMA` — mur ou pas — parce que `gamma_block_short` n'est
+    pas dans l'agrégation ; ce n'est pas « aucun mur sous le prix », c'est
+    « non mesuré » (mesuré au re-rejeu : 13 shorts sur 14 jours, 13 lignes ;
+    avant, un short sans mur n'écrivait rien). Les lignes antérieures au
+    10/09 (non rejouées, et le journal LIVE du 10/09 avant le redémarrage du
+    coureur — `ts` dans DECISIONS) lisaient le mur du DESSUS pour les
+    shorts : un `BLOQUE:L5_VETO_GAMMA` sur un `:S` y est un veto inversé,
+    pas une mesure. Et depuis la même passe, `L5_FRAIS_TROP_LOURDS` et
+    `L0_REGIME_INDETERMINE` RÉPONDENT avant 11h00 (sur `atr_ref`) : leurs
+    `TROU_` du matin antérieurs sont des trous de MÈTRE, pas de marché.
+
+37. **Le LIEU est sur la ligne depuis le 10/09** (`lieux`, `seuil_ticks`,
+    `bande_ticks`, `close`, `lieux_motif` — `V3/lieux.py`) : nom du niveau,
+    prix reconstruit `close + dist × tick` (TOUTES les `dist_*` sont
+    « niveau − close », `dist_cur_val` comprise — mesuré à 100 % contre
+    `cur_val_lvl` ; review du 10/09), distance en ticks, la BANDE du lieu
+    (bas, haut — H6p `[−P15 ; +P05]`, H2p asymétrique : `seuil_ticks` est la
+    borne de proximité de la famille, PAS la bande). Les lignes antérieures
+    (non rejouées) n'ont pas le champ : leur lieu se reconstruit par rejeu,
+    pas par lecture. Un `lieux: None` porte son motif ; un signal hors des
+    quatre (battement, ombre) en a un par construction. Le lieu DÉCRIT ;
+    « le niveau X marche mieux que Y » est une lecture du jour 61 par
+    famille, jamais une raison de retoucher un lieu en campagne. **Et une
+    lecture pour NEXT_CYCLE, pas pour le tag** : `h3` gelé reconstruit la VAL
+    avec le signe inverse (`close − dl × tick` = 2·close − VAL) — son LONG
+    tire quand la clôture est juste SOUS la VAL (`dl > 0`) avec une mèche
+    basse plus longue que la distance à la VAL, pas « sortie sous la VAL
+    puis clôture dedans » comme sa docstring le dit. Le journal porte la
+    vraie VAL ; le déclencheur reste tel qu'il a été tagué et mesuré.
+
+38. **H3-VPOC se lit ENTIÈRE, la jambe long est MARQUÉE, jamais verdictée**
+    (Fable, 11/09, révision AVANT le tag — la version du 10/09 au soir était
+    un piège, dite ci-dessous). Le fait mesuré ne bouge pas : `close +
+    dist_cur_val × tick = cur_val_lvl` à 100 % sur 4 × 390 barres, et `h3`
+    gelé reconstruit la VAL au signe inverse ; la jambe SHORT (rejet au VAH)
+    est l'hypothèse pré-enregistrée, la jambe LONG tire quand la clôture est
+    juste SOUS la VAL avec une mèche basse — **une hypothèse ACCIDENTELLE,
+    sans attendu écrit, que personne n'a pré-enregistrée** (NEXT_CYCLE
+    §5 septies).
+    **Ce qui change, et pourquoi.** « Lire à part » ne veut pas dire
+    « partitionner le verdict ». Projection depuis le lot sur 60 jours × 2
+    instruments : H3 entière ≈ 50 signaux, H3 short seul ≈ 33, H3 long seul
+    ≈ 17 ; H6p ≈ 24, H2p ≈ 3, H8p ≈ 3. H3 entière est **la seule case de
+    toute la campagne au-dessus de N = 40**. La version du 10/09, en coupant
+    les jambes pour le verdict, faisait passer la seule hypothèse testable
+    sous le seuil : soixante jours qui ne peuvent conclure sur rien. La
+    règle 9 l'interdit déjà dans les deux sens — ni fusionner, ni découper
+    sous la puissance.
+    **Donc** : le verdict du jour 61 porte sur **H3 ENTIÈRE** (N ≈ 50). La
+    jambe est marquée sur chaque signal — elle est déjà dans le journal, le
+    `snapshot_id` finit par `L` ou `S` — et se lit **descriptivement** : sa
+    part, son heure, son comportement. Un résultat sur le short seul (≈ 33)
+    ou le long seul (≈ 17) est une **observation à pré-enregistrer au
+    cycle 2**, jamais une conclusion du jour 61. Le long ne peut toujours pas
+    « passer » ; il ne peut pas non plus faire échouer H3 à lui seul.
+    Taille mesurée : DECISIONS 10/09 (45 H3 sur le lot, 30 shorts / 15 longs).
+
+39. **Le scénario est sur chaque ligne ; il DÉCRIT, il ne DÉCOUPE pas**
+    (Fable, 10/09, module SCÉNARIOS — pré-enregistrée avant que le module
+    existe). `scenario_en_cours` sera sur chaque ligne de l'entonnoir, des
+    fantômes et des marges : au jour 61 il se lit comme une **colonne de
+    contexte**, jamais comme une partition du verdict. Sur le lot, 73 signaux
+    des quatre en 54 jours : découpés par scénario, aucune case n'a de
+    puissance. Une partition par scénario exige N ≥ 40 par case — le cycle 2
+    ou au-delà. La règle 9 (jamais en groupe) s'applique dans les deux sens :
+    ni fusionner, ni découper en dessous de la puissance. Le module n'entre
+    dans aucune porte, ne décide rien, n'écrit que ses propres journaux.
 
 ## Ce que le jour 61 NE fait pas
```

## DECISIONS.md — depuis le 08/09

```diff
diff --git a/DECISIONS.md b/DECISIONS.md
index 2066004..c48706c 100644
--- a/DECISIONS.md
+++ b/DECISIONS.md
@@ -41,3 +41,40 @@
 | 08/09 (audit) | **la dette DST L0 est FERMEE LE JOUR MEME** — pas au 31/10 : `est_cash` + `initial_balance` sur `minutes_et` (la session cash est en HEURE DE L'EST, plus jamais en UTC fige) | audit Fable pt 2 : « le 2/11, L0 elle-meme deplacerait la session d'une heure — dette L0, pas C2, cette semaine » | LA PREUVE : l'annee synthetique 2026, la SEULE a contenir de l'EST (ecarts uniquement aux bords de fenetre attendus) ; le lot reel, ENTIEREMENT EDT, ne prouve rien sur l'hiver — il est la NON-REGRESSION : 0/271 940 barres, 152 fichiers (ordre corrige par la revue B2). Residuel RECHERCHE (classer_colonnes, test_ctx, sync_vps — surveillance_l6 migre le 08/09, c'est le chien de garde du 2/11) : A_FAIRE pt 19, deadline 31/10 |
 | 08/09 (revue) | **la revue de coherence Fable (be87301) executee POINT PAR POINT, aucune omise** : A1 le yaml fige ne redecrit plus le gamma (pointeur unique vers seuils L5 + DECISIONS — le fait faux « mesure sur le proxy » disparait) ; A2 le stop SIM re-etiquete « PEU PROBABLE sur NQ, mesurable » (4,9 SL — jamais « inerte par construction ») + regle 16 ; A3 STATUS reecrit (jour 1, prochains pas reels ; regle : PROMPT_REPRISE cite STATUS, jamais l'inverse) ; A4 le tag `campagne-ombre-1` DEPLACE UNE FOIS (jamais pousse nulle part auparavant) sur le commit qui court le premier rejeu officiel, et publier.sh pousse desormais le tag SUR LE MIROIR (un tag du depot principal ne survit pas au split) | une revue de coherence ne cherche pas des bugs — elle cherche ou le depot dit une chose et fait l'autre ; trois des quatre trouvailles etaient dans les documents que la methode designe comme LA memoire | B1 exception L0 SESSION_CLOTURE → NEXT_CYCLE 5 ter (avec son test, ecrit MAINTENANT) ; B2 preuve DST re-ordonnee (l'annee synthetique EST la preuve, le lot EDT la non-regression) + L6 continuite migre sur minutes_et ; B3 defenses_du_niveau sous reserve du diagnostic pt 11 sinon TROU_DEFENSES ; B4 provenance du buffer ecrite (fiches prev_* 1 min, immunisee des ecarts cur_*) ; B5 + A2-journal + PF_PERTE_JOUR + B-BOUEE → pt 21 DEMAIN (ordre E2) ; B6 A_FAIRE reordonne ; B7 regle 11 completee (les quatre = un setup de 11h-13h EN PRATIQUE) ; C → regles 14-16 (cote_reentree journalise par le code, atr_source separe, stop SIM a part) + NEXT_CYCLE 5 quater (V1/V2 retournes par famille, signe attendu ecrit) |
 | 08/09 (audit) | **les trois arbitrages Fable ACTES et EXECUTES** : A) EOD = DEUX verdicts en colonnes (side_pur/rend_pts tous les jours — le papier ET le filtre, side_pur=0 = no-trade, sortie close_1545) ; B) atr_ref GENERALISE (atr_barre sinon ATR-veille, atr_source journalise) — DIV v2 : lieux x4,2 ES / x3 NQ a P10 constant ; C) POOR v2 = MEMOIRE D'EPISODE en fiche F23 (sommet plat touche par >= 2 barres, persiste jusqu'a reparation), apres F23 hors quarantaine | l'attendu d'un effet de niveau A se lit tel que publie (A) ; le trou etait un defaut de feature, pas de setup (B) ; un flag roulant ne portera jamais un episode (C) | A et B executes le jour meme (commits f00574b + suivant, reviews GO appliquees) ; C attend F23 hors quarantaine (A_FAIRE pt 20, ordre Fable §6.8). 80PCT enrichi au passage : fenetre_reentree_barres + cible_atteinte (regle d'OUVERTURE de Dalton, journalise d'abord, filtre au cycle 2) |
+| 08/09 (soir) | **le REGISTRE des niveaux est GELE a 17 entrees** (`niveaux_version: 2026-09-08`) et `reactions.py` decrit chaque soir ce que le marche leur a fait — description pure, aucune simulation de decision | demande Jackson : « qu'est-ce qui a marche aujourd'hui, quel niveau a fonctionne » ramene a sa forme mesurable — on decrit le MARCHE, jamais une DECISION qu'on n'a pas prise. Test decisif applique a chaque champ : pourrais-je l'ecrire si les prix futurs etaient masques ? Trois classes : PRIMAIRE (prev_vah/val/vpoc, pdh/pdl, ovn_high/low, vwap_w), SECONDAIRE (ib_*, cur_* mobiles, mq_*), TEMOIN (vwap_d — le plus teste de tous, 6,2/jour-instrument : le CONTROLE NEGATIF sans lequel toute distribution paraitra significative) | `barrieres.COLONNES_NIVEAUX` (13) et `recit.NIVEAUX` (6) sont des SOUS-ENSEMBLES du registre — jamais deux listes qui divergent. **vwap_w ajoute sur decision Jackson** (sa seance du 08/09 s'est jouee dedans : 73 % ES / 86 % NQ des barres cash entre SD-1 et SD+1, ZERO au-dessus de SD+1 — et il ressort le plus teste du jour sur ES, 8 tests). Bandes SD1/SD2 hebdo : pas de colonne `dist_`, reportees a marges.py. Trois apports que la simple persistance de `recit.py` n'aurait pas donnes : (1) LE DENOMINATEUR — une ligne `niveau_jour` par niveau x instrument TOUJOURS ecrite, avec `motif_zero` (colonne_absente / jamais_couverte / atr_indisponible / jamais_approche), sans quoi 60 jours de silence se liraient « ce niveau ne marche pas » ; (2) LA SYMETRIE — `f23._reaction_atr` ne mesure QUE l'excursion de rejet, le biais directionnel est DANS le moteur : `exc_rejet_atr_4/8` et `exc_poursuite_atr_4/8` en miroir, jamais l'un sans l'autre ; (3) LA DERIVE — `derive_niveau_atr`, la mesure que la quarantaine `cur_*` attend. Contrat de verification CORRIGE : `recit.py` sort en erreur au 1er ecart et echouait 2 jours sur 2 (8 ecarts le 07/09, 3 le 04/09, 11/11 sur `cur_*` = la derive du niveau entre test et cassure) ; ici l'ecart n'arrete la publication que sur un niveau FIGE, et sur un mobile il DEVIENT la mesure. Resultat : 0 ecart sur 3 jours/4. Sortie `LOGS/reactions/` (hors miroir, licence MenthorQ) ; tronquage en tete de run = idempotent. Regles de lecture 19-28 ecrites dans LECTURE_JOUR_61.md AVANT la premiere ligne de donnees |
+| 09/09 | **ARBITRAGE FABLE BLOC C execute** : C1 doublons du journal corriges (un trou promu bloquant se journalise UNE fois, sous TROU_ seulement — 210/624 lignes du jour 1 etaient en double, pourquoi.py annoncait 204 blocages L0 pour 99 reels) ; C2 unite de _dist_hvl_atr corrigee (ticks x0,25 / points) ET zone_morte_atr 1,0 -> 0,25 au meme commit — LA VALEUR MESUREE le 06/09, identite au bit pres PROUVEE (hashes entonnoir 04 et 07/09 identiques apres re-rejeu) ; C3 L5_VETO_RVOL_EXTREME passe OBSERVEE (NQ : 64 blocages avec la derniere minute du bloc, ZERO avec la barre reconstruite — 100 % d'artefact d'agregation ; la bonne agregation se tranche au cycle 2 SUR DISTRIBUTION, 4 definitions candidates 73/0/25/401) ; C4 surveillance_l6 branchee en etape 0 du rythme du soir (L6 n'avait AUCUN producteur quotidien, L0_DATA_L6_ALERTE bloquait sur un verdict de 4 jours) | un veto applique qui bloque sur un artefact n'est pas une protection, c'est un biais actif ; un YAML qui dit 1,0 pour un comportement de 0,25 est un seuil qui n'a jamais existe ; un journal double fabrique 34 % de lignes fausses par jour | test_chaine_journal (2 PASS) garde C1 ; test_portes realigne sur la vraie unite ; re-application du veto RVOL = ligne DECISIONS dediee. Enigme env : `exe` (sys.executable) dans chaque battement — deux interpreteurs presumes, le chemin tranchera |
+| 09/09 | **B-ATR sur les signaux d'ombre** (16 ED + C2 actifs) — la sortie que 9/9 signaux du jour 1 n'avaient pas. Observateur pur dans `barrieres_du_jour` : lit les journaux d'ombre deja ecrits par `campagne` (rien de gele touche), reutilise `b_atr`. **BRACKET SEULEMENT, DEVENIR RETENU** (review R1, DECISION_SOUVERAINE) : la pre-inscription des SEIZE/C2 (OMBRE_ED16) est « du N, rien d'autre, sans un seul regard sur le passe » — `B.issue` regarde le futur, on ne l'appelle pas ; l'issue se recalcule au JOUR 61 depuis (sl_prix, tp_prix, i). Le devenir quotidien est un opt-in explicite JAMAIS pris (peek-proof par defaut) | demande Jackson : donner une sortie aux ombres pour repondre « pourquoi le SL a ete touche » et fonder le bot SIM. Ecrire le devenir chaque jour, meme non lu, c'est le CALCULER = « consommer un regard » que la pre-inscription interdit. Le bracket (sl/tp), lui, est connu a t+1, aucun regard sur le futur — il se journalise | snapshot_id UNIQUE par setup `OMB:<setup>:<sym>:<i>:<L/S>` (cle jour 61 = (setup,ts,side), R2) ; `ts_introuvable` = rupture invariant df campagne/barrieres -> print + incident code retour 1 (R3). test_barrieres_ombres 8 PASS, coureur intact, run 08/09 = 9 lignes 0 devenir. reviewed-by code-reviewer (GO-AVEC-RESERVES, R1/R2/R3 appliquees). Le rythme est LOCAL — pas de deploy VPS |
+| 09/09 | **confrontation `triple_barriere` : CORE vs la reference de Fable** (`V3/research/`). Quatre conventions IDENTIQUES (entree open(t+1), barre d'entree testee, TP+SL meme barre = SL, frais 1x en ATR du jour) ; la 5e (sortie horaire) diverge — CORE n'a PAS d'EOD et detient 21 barres, la ref corrige (la barre qui CONTIENT l'heure ferme dessus, 20 barres detenues). **CORE n'est PAS change** : campagne gelee dessus, aligner en jour 3 ferait deux populations. Le harnais tournera au rythme du soir, journalisant l'ecart par signal (nul sur le prix, informatif sur l'etiquette) jusqu'au cycle 2 | une `EXPIRATION` sur la derniere barre cash n'est pas une expiration, c'est un trade coupe par la cloture — 22/70 signaux des quatre, un tiers des 11h (la barriere 20 barres depasse la seance). Bonus : la ref a attrape 3 jours a donnee TRONQUEE que CORE masquait en EXPIRATION (07/09 Labor Day, 09/09 collecte, 08/05 a investiguer) | 0 ecart de `pnl_atr` sur 66 resolus, 22 relabels EXPIRATION->EOD, 4 INDETERMINE nommes (`research/rapports/parite_barriere.txt`). `triple_barriere_ref` 10 tests ; confrontee a la donnee elle a PERDU sur C4b (EOD sur la barre qui contient 15h55, pas `>= 955`) et a ete corrigee — une reference qu'on ne peut pas prendre en defaut ne prouve rien |
+| 09/09 (nuit) | **BRIQUE 1 FABLE — `atr_ref` DANS LE METRE DES QUATRE ET DES SEIZE, AVANT LE GEL, avec re-rejeu des jours 1-2** : `seuil_ticks` lit `atr_ref` (= `atr_barre` si fini, sinon la mediane de l'ATR agrege de la DERNIERE SESSION COMPLETE — pas la derniere session : le lendemain d'une demi-seance, c'est vendredi) ; meme repli pour les brackets (`barrieres_du_jour`, `barrieres.issue`, `intentions`) ; `atr_source` (barre / veille / aucun) sur CHAQUE ligne de signal (entonnoir, ombre16, ombre_c2) et de bracket ; alerte L6 `echelle_douteuse` si le gap d'ouverture >= 2 ATR-veille ; `atr_veille` fige a 9h30 par construction (ne lit que les dates precedentes). Anciens journaux des jours 1-2 CONSERVES (`*_avant_atr_ref`). **RENVERSE la ligne du 08/09 (audit) « rien ne change au gele » et NEXT_CYCLE §5 bis** | `np.maximum(0,10 x NaN, 2) = NaN` : la bande n'existe pas avant 11h00 parce que le METRE est vide, pas parce que la regle l'a voulu — meme classe que le DST fige EDT et `dist_hvl` ticks/points, traites en campagne avec re-rejeu (« un bug du metre n'est pas une convention »). Mesure 09/09 : 6/9 jours sans signal des quatre, 2/2 sur la campagne ; les SEIZE aveugles aussi (0/43 ED avant 11h00, meme `seuil_ticks`) ; le plancher 2 t disparaissait avec le NaN. Geler vendredi soixante jours d'un systeme qui n'a jamais essaye le matin — la regle 11 le dirait, on l'aurait su avant | **ATTENDU ECRIT AVANT LA RELANCE** : sur le lot (52 j x 2), nombre de lieux des quatre entre 9h30 et 11h00 avec `atr_ref` = N > 0 (aujourd'hui 0) — aucune direction attendue sur leur devenir ; a partir de 11h00 les journaux des jours 1-2 sont IDENTIQUES ligne a ligne (le repli ne touche que les barres sans ATR) ; les signaux `atr_source = veille` se lisent A PART (regle 15 etendue aux quatre) ; `atr_ref` NaN seulement sans session complete avant. Mesure : `mesure_trou_atr.py` rejoue -> rapport date 09/09 |
+| 09/09 (nuit) | **BRIQUE 1 MESUREE — attendu TENU** : `mesure_trou_atr` rejoue sur 54 j x 2 avec `atr_ref` : lieux des quatre 9h30-11h00 = **ES 6** (H3-VPOC 4, H6p 2), **NQ 5** (H3-VPOC 5), tous `atr_source = veille` ; `atr_ref` NaN 0/312 barres du matin (0 jour sans session complete avant). Re-rejeu des jours 1-2 : **>= 11h00 IDENTIQUE ligne a ligne** sur les 5 journaux x 2 jours (entonnoir, ombre16, ombre_c2, barrieres, marges) ; le matin apparait : 08/09 ES ED10 9h30 ; 09/09 ES ED04 + **ED06** 10h00 (le « ED06 muet » de la lecture du soir — c'etait le trou, pas la condition) ; le bracket NQ C2_80PCT 10h00 EXISTE (atr 50,76 veille — plus d'`atr_invalide` apres 9h30) | ce que la mesure a dit EN PLUS de l'attendu, consigne tel quel : (1) « apres 11h00 » sur le lot passe de 31->35 ES / 27->28 NQ — 12 barres apres 11h avaient AUSSI `atr_barre` NaN (jours a trous) et ont un metre maintenant, ce n'est pas « le meme lot >= 11h » ; (2) le 08/09 (jour 1) est LE cas « lendemain de ferie » : sa veille utile est le VENDREDI 04/09, pas la demi-seance de Labor Day — DIV v2 y gagne un `lieu_sans_reaction` 9h30 ; (3) `ombre_c2` porte `atr_source` sur DIV v2 seulement (seul C2 dont le LIEU est en ATR) — 80PCT et EOD le portent sur leur bracket, pas sur un lieu qui n'a pas de metre | rapport `L3_declencheurs/rapports/trou_atr_les_quatre_20260909.md` ; anciens journaux conserves `*_avant_atr_ref.jsonl` (hors depot) ; tests : `test_atr_ref` 19/19, `test_intentions` 40/40, suite V3 18 fichiers verts ; review code-reviewer avant commit |
+| 09/09 (nuit) | **BRIQUE 2 FABLE — LA MARGE DES QUATRE** : `V3/marges_quatre.py` ecrit chaque soir (etape 5b/5 du rythme) UNE ligne par hypothese x instrument, MEME les jours muets — `lieu_min_ticks` (signee, <= 0 = dedans), `seuil_ticks`, `marge_rel`, cote, heure, `atr_source`, `lieu_atteint`, `regime_au_lieu`, `reaction_manquante` (la PREMIERE condition qui manque, comptee sur les barres au lieu) et l'etat LIEU_REAGI / LIEU_SANS_REACTION / QUASI (hors bande de moins d'un seuil) / LIEU_IMPOSSIBLE(porte_jamais_ouverte, atr_ref_absent, colonne_absente) / JOUR_MUET(lieu_loin). Observateur pur : rien de gele touche, journal SEPARE (`marges_quatre_<jour>.jsonl`, schema marges/2) | un silence sans marge est un jour perdu ; l'exposition recompose lieu + porte + regime + reactions depuis les MEMES colonnes et le meme `seuil_ticks` que les fonctions gelees, et `test_marges_quatre` prouve la PARITE barre a barre (0 ecart sur 1 248 barres x cotes, 3 journees reelles ES+NQ) — l'exposition ne peut pas deriver en silence | 09/09 rejoue : ES H3 QUASI a 0,95 t de la bande (long 11h45 — ce qui avait ete recalcule a la main), NQ H3 QUASI 0,7 t a 9h45 (le matin, grace au metre) ; les six autres lieux ATTEINTS, reaction manquante nommee (delta, cloture, rvol, finish, regime). 08/09 : NQ H3 lieu atteint a 11h15 (le low), manque finish. Regle 35 LECTURE : calibration, jamais permission |
+| 10/09 (nuit) | **REVIEW code-reviewer de la brique 1 : GO-AVEC-RESERVES, reserves EXECUTEES avant commit** — R1 (critique) : l'alerte L6 `echelle_douteuse` passait par `etat_live.etat_l6` (toute ALERTE → `L0_DATA_L6_ALERTE` appliquee) et aurait FERME la journee live suivante ; taux mesure sur le lot : ES 44 % / NQ 58 % (p50 2,47 ATR) / union 66 % → INFO + `motif`, seuil OBSERVE, test « aucun cas ALERTE » ; R2 : un PASSE du matin n'ouvrait jamais la position virtuelle (`chaine._ouvrir/_fantome` lisent CORE sur `atr_barre`) → `_metre(df)` = `atr_barre ← atr_ref` pour CORE, identique >= 11h00, test « PASSE 9h45 → suivant BLOQUE POSITION_OUVERTE avec fantome » ; R4a : changement de contrat → `motif = rollover` (gap de base, hors regle 15) ; R8 : veille presente tronquee → `motif = veille_incomplete` ; Q1 : complet = 26 bins ET >= 380 minutes ; R5/R6/R7 : commentaire battement, docs ombre_c2 (DIV v2 seul), colonnes selectionnees avant concat. **R3 REPORTE a la passe lecture (avant le gel)** : `lecture.lire` n'expose que `atr_barre` → `L5_FRAIS_TROP_LOURDS` et `L0_REGIME_INDETERMINE` (observees) sont des TROUS sur la population du matin ; `lecture.py` est a 299/300, le decoupage requis pour A1 l'est maintenant deux fois. **R4b/R4c → ROLLOVER_10_09.md** (bascule dans le cash = TR pollue ; `contrat_ok` juge la premiere ligne = ligne B) | une review qui mesure ce que les tests ne mesurent pas (le TAUX et l'AVAL d'une alerte) — incident SCALE_DRIFT consigne | `test_atr_ref` 21/21 (4a-4g), `test_chaine_journal` 4/4, suite V3 verte |
+| 10/09 (avant l'ouverture) | **HUIT ARBITRAGES FABLE EXECUTES + L6 CORRIGE AVANT 9H30** : L6 `derive` -> INFO + motif=derive_feature (une DERIVE informe, l'INTEGRITE ferme — la F15 x44 du 09/09 aurait ferme le live du 10/09 entier via `L0_DATA_L6_ALERTE`, appliquee, qui reste telle quelle) ; Q1 seuil `echelle_douteuse` = p90 PAR INSTRUMENT mesure sur 62 j (ES 5,81 / NQ 6,69), le 2,0 (la mediane) retire ; Q2 R3 AVANT le gel, avec le decoupage de lecture.py (une fois pour A1 et R3) ; Q3 les 12 barres apres 11h tel quel, `atr_source` les distingue deja ; Q4 taxonomie des verdicts L6 (integrite ferme / derive informe) formalisee apres le gel ; Q5 `porte_jamais_ouverte` = JOUR_MUET (dans le denominateur — c'est lui qui dit combien H6p est rare), LIEU_IMPOSSIBLE = mesure NON prise (hors denominateur), QUASI valide, jours 1-2 rejoues (marges/2 version b) ; Q6 CONVENTIONS §10 avec le 8,2054 du vendredi ; Q7 « une session a deux contrats n'est pas complete » dans `atr_veille_15` MAINTENANT (une definition, pas un resultat ; `contract` entre dans COLS_RECALC — 79/77 fichiers le portent) ; Q8 pre-enregistre ci-dessous | Fable a pris le seuil a son nom dans INCIDENT_LOG ; le reste est l'application d'une regle deja ecrite : un seuil se pose sur SA distribution, un verdict L6 ne ferme que sur l'integrite | `surveillance_20260909` regenere : 0 ALERTE (derive F15 en INFO, echelle_atr ES 2,23 < 5,81 -> OK) — le coureur live du 10/09 s'ouvre ; test_atr_ref 24/24 (1e deux contrats, 4h seuil par instrument), test_marges_quatre 12/12 |
+| 10/09 | **PRE-ENREGISTREMENT — la CARTE DU MATIN en aveugle (Fable Q8), ecrit AVANT la premiere carte** : tirage par BLOCS D'UNE SEMAINE, 50/50, generateur seede (la seed est fixee ET ecrite ici au commit de `carte_matin.py`, jamais retiree), calendrier tire pour HUIT semaines d'un coup ; les jours « sans carte » la carte est GENEREE ET STOCKEE, pas affichee ; le journal manuel porte `carte_visible: bool` chaque jour ; AUCUNE lecture avant huit blocs ; lecture au jour 61+ : les trades manuels avec / sans, et l'ECART trader-machine avec / sans — c'est ce dernier qui dit si la carte rapproche Jackson de la chaine ou l'en eloigne | sans alternance en aveugle on ne saura jamais s'il trade mieux GRACE a elle ou MALGRE elle ; on accepte qu'il devine parfois, le tirage par blocs rend la devinette inutile | la carte nait de `marges_quatre.exposer()` (niveau ± seuil en PRIX, regime lu a 9h30) — brique 3, apres le gel |
+| 10/09 (passe lecture) | **ATTENDU ECRIT AVANT LA RELANCE — R3 + A1 + B3 (brief Fable)** : `lecture.py` decoupe (216 + `lecture_colonnes.py` 108, re-exports, huit tests verts avant/apres) ; R3 `lec` expose `atr_ref` + `atr_source`, `vetos._frais` et `_dist_hvl_atr` lisent `atr_ref` ; A1 minimal `lire(side)`, `_gamma` -> None pour un SHORT (TROU_L5_VETO_GAMMA : la colonne short n'est pas dans l'agregation) et pour un sens inconnu ; B3 `rang_du_jour = (minutes_et - 570) // 15`, fail-loud sur une barre hors grille 15 min (le ts). Re-rejeu de 14 jours (les 10 du lot avec un signal des quatre LE MATIN — 01, 03, 06, 14, 16, 24, 31/07, 05, 11/08, 07/09 — + 01, 04, 07, 08, 09/09), « avant » fabriques avec le code d'AVANT la passe (post-brique 1) et conserves `_avant_lecture`. ATTENDU sur 159 lignes d'entonnoir : (a) les 22 trous du matin — 11 `TROU_L0_REGIME_INDETERMINE` + 11 `TROU_L5_FRAIS_TROP_LOURDS`, un couple par signal du matin — deviennent des REPONSES (ligne disparue, ou `BLOQUE:<porte>:O` si elle bloque) ; (b) le seul `BLOQUE:L5_VETO_GAMMA` sur un short (05/08) devient `TROU_L5_VETO_GAMMA` ; les 7 `L0_PREMIERE_BARRE` INCHANGEES (les 14 cash commencent a 9h30, rang = i sur la premiere heure) ; ombre16 / ombre_c2 IDENTIQUES ; 14 PASSE inchanges ; AUCUN autre ecart | un attendu tenu a vide ne prouve rien (la reference du 09/09) : les jours 1-2 n'ont pas de signal des quatre, la mesure se fait la ou la population du matin EXISTE | comparateur `diff_lecture.py` (echoue sur tout ecart hors a/b) ; mesure a suivre |
+| 10/09 (passe lecture) | **MESURE — attendu TENU, avec un ecart non prevu consigne** : re-rejeu des 14 jours, 0 erreur, comparateur 0 INATTENDU sur 159 lignes. (a) **22 trous du matin devenus reponses** — les 22 prevus (11 REGIME + 11 FRAIS ; la reponse ne bloque jamais : les lignes disparaissent, aucun `BLOQUE:<porte>:O` ajoute) ; (b) le `BLOQUE:L5_VETO_GAMMA` du short du 05/08 devient TROU (prevu) **ET 12 shorts sans mur gagnent une ligne `TROU_L5_VETO_GAMMA`** (NON prevu dans l'attendu : un short sans mur ne faisait pas de ligne, un TROU en fait une — les 13 shorts du lot portent maintenant tous « non mesure », c'est la lecture honnete de la regle 36) ; 7 `L0_PREMIERE_BARRE` inchangees ; ombre16 / ombre_c2 identiques ; 14 PASSE inchanges ; jours 1-2 : 0 ligne avant, 0 apres ; barrieres des jours 1-2 recalculees a l'identique | l'ecart (b) est une consequence mecanique de « un short rend None » que l'attendu aurait du deduire ; il est dans la bonne direction (une ligne de plus, jamais une de moins) et il est nomme | anciens journaux `*_avant_lecture.jsonl` conserves (LOGS) ; `diff_lecture.py` ; review code-reviewer avant commit |
+| 10/09 (passe lecture) | **REVIEW code-reviewer : GO-AVEC-RESERVES, reserves EXECUTEES avant commit** — R1 : l'attendu (b) disait 1, la mesure dit 13 (12 TROU gamma sur des shorts sans mur) : attendu NON reecrit, mesure consignee a cote, regle 36 dit « chaque short porte un TROU » ; R3 : les battements de NUIT du coureur live sont maintenant BLOQUES par L0_PREMIERE_BARRE (rang negatif — avant, i grand passait ; 9h30-10h15 : le battement et le chemin signaux sont enfin d'accord ; 18h00-18h45 ET plus bloques, c'etait un artefact d'indice) — ecrit dans l'attendu pre-enregistre de coureur_live.py, tests [3e]/[3f] ; R4 : la « garde YAML » n'etait qu'un commentaire — test [4] `L5_VETO_GAMMA not in APPLIQUEES` tant que gamma_block_short n'est pas dans l'agregation ; R5 : atr_ref/atr_source lus sur UN fait (les deux colonnes) ; R6 : `issue_position_ouverte` masque dans le comparateur ; R7 : lecture.py = 235 lignes (216 au decoupage), lecture_colonnes dans LISEZ_MOI ; R8 : fixture test_proxys sur un ts reel de la grille, lint. **R2 — A FAIRE PAR JACKSON : le coureur live (pythonw 26360, lance le 09/09 10h55) tourne l'ANCIEN lecture.py en memoire ; redemarrage propose a 15h15 Paris (9h15 ET, frontiere de barre, avant l'ouverture), le ts du redemarrage a ecrire ICI et dans la regle 36 — avant lui, le live du 10/09 lit rang=i, gamma mono-sens, FRAIS/REGIME en trou le matin** | une review qui mesure la PREUVE (l'attendu, le comparateur trop permissif) et le LIVE (le processus en memoire), pas seulement le code | test_passe_lecture 18/18 ; test_portes, test_faux_live, test_chaine_journal, test_proxys, test_structure, test_coureur_live, test_orderflow, test_ctx, test_spec_l3, test_intentions, test_atr_ref verts |
+| 10/09 | **LE LIEU DANS LA LIGNE PASSE (V1-lesson 4, « si possible avant le gel » — fait)** : `V3/lieux.py` rend, pour chaque signal des quatre, `lieux: [{nom, prix, dist_ticks}]` + `seuil_ticks` (P10 / P05 / P20 sur `atr_ref`) ; la chaine l'ecrit dans `extra` de CHAQUE ligne du signal (PASSE, BLOQUE, TROU — comme `atr_source`), un `None` porte toujours son motif (famille_hors_quatre, sans_recalculs, atr_ref_absent, niveau_absent). Un niveau par hypothese et par cote (H3 : cur_vah / cur_val ; H2p : bandes SD2 ; H6p : ib_high / ib_low) ; H8p : ceux des dix a <= P20. CONVENTION DE SIGNE MESUREE (04/09 + 14/07, ES+NQ, 4 x 390 barres 1 min contre les colonnes `_lvl` du brut) : `niveau = close + dist x tick` pour TOUTES les dist_*, `dist_cur_val` COMPRISE (`close + d x tick == cur_val_lvl` a 100 %, `inside_cur_va = 1` -> d < 0) — la premiere version de cette ligne disait « exception cur_val, le code gele fait foi » : FAUX, attrape par la review avant commit (R1) ; le code gele fait foi pour la DECISION, pas pour la DESCRIPTION d'un niveau. `bande_ticks` (bas, haut) par cote — H6p [-P15 ; +P05] (la borne active est P15), H2p asymetrique — et `close` sur la ligne (R2, R3) | colonne de journal, JAMAIS une decision : personne ne lit `lieux` (test : memes PASSE avec ou sans) ; c'est la seule information qu'on ne peut pas reconstruire au jour 61 sans rejouer — V1 la journalisait par trade | `test_lieux` 12/12 (synthetique, 5 signaux reels du 14/07 tous avec lieu, |dist| <= seuil sur H3, chaine NQ 14/07 16 lignes) ; les lignes anterieures au 10/09 (non rejouees) n'ont pas le champ (regle 37) |
+| 10/09 | **LECTURE POUR NEXT_CYCLE, née du lieu (review 10/09, R1) — le LONG de `h3` gelé ne teste pas ce que sa docstring dit** : `h3` reconstruit `val = close - dl x tick` alors que `dist_cur_val` = VAL - close (mesure 100 % contre `cur_val_lvl`) ; son long tire donc quand la cloture est juste SOUS la VAL (`dl > 0`, |dl| <= P10) avec une meche basse plus longue que la distance a la VAL (`low < 2·close - VAL`) — pas « sortie sous la VAL puis cloture dedans ». Le short (VAH) est juste. RIEN NE CHANGE au tag : H3-VPOC se mesure telle qu'elle a ete pre-enregistree, et le jour 61 lira ses longs pour ce qu'ils sont ; la version corrigee est une hypothese du cycle 2 (NEXT_CYCLE §5 septies) | une idee nee en lisant les resultats va dans NEXT_CYCLE (hypotheses.py, l.9) — c'en est une, meme si elle vient d'une mesure de convention et pas d'un devenir | le journal porte la vraie VAL depuis le 10/09 ; les longs H3 anterieurs se relisent par rejeu |
+| 10/09 | **REVIEW du lieu (code-reviewer) : GO-AVEC-RESERVES, executees avant commit** — R1 (important) : mon signe -1 sur `dist_cur_val` etait FAUX, la mesure contre `cur_val_lvl` tranche a 100 % (« le code gele fait foi » pour une description = VALIDATION_MISS consigne) → signe uniforme, test reel [2a] contre les `_lvl`, lecture NEXT_CYCLE §5 septies ; R2 : `seuil_ticks` trompeur (H6p : la borne active est P15, pas P05 ; H2p asymetrique) → `bande_ticks` (bas, haut) par cote, `seuil_ticks` = la proximite de la famille (regle 37 le dit) ; R3 : `close` sur la ligne (le lieu est autoportant) ; R4 : docstring du test, motif close_absent teste. Verifie par la review : table = fonctions gelees, battement immediat, cout negligeable, aucun lecteur de l'entonnoir a schema strict (23h01 intact), peek-proof | une review qui MESURE la ou j'avais conclu du code | `test_lieux` 16/16 ; chaine, structure, passe lecture, faux live, pourquoi, coureur live verts |
+| 10/09 10h01 Paris | **ROLLOVER — LIGNE B** : les fichiers du 10/09 OUVRENT en U26 (ES 480 lignes / NQ 481, 100 % U26 sur la nuit Globex, aucun changement de contrat a 10h01) alors que `contrat_actif('20260910')` = Z26 → `L0_CONTRAT_INACTIF` passe OBSERVEE pour le 10/09 (seuils.yaml, commentaire date), remise APPLIQUEE des qu'un fichier OUVRE en Z26 — a verifier le 11/09 au matin (une ligne ici). Heure de bascule en seance : a mesurer ce soir (la ligne ou `contract` change) + `max(atr_barre)` du jour (review R4b : le bin de bascule porte la BASE, pas un range) ; `atr_veille_15` juge de lui-meme le 10/09 incomplet (deux contrats) si la bascule tombe dans le cash | le roll « 3e vendredi - 8 jours » est l'horloge du CME, pas celle de Sierra : le fichier suit le volume, pas la date. Bloquer toute la seance sur un decalage d'horloge serait un faux TROU — c'est la ligne B ecrite la veille, pas une decision du matin | le coureur live (ancien code ET ancien YAML en memoire) doit etre REDEMARRE avant 15h30 (15h15 Paris, review R2) pour lire la porte en observee ; `test_faux_live` lit le mode de la porte (un trou n'exige le blocage strict que sur une porte appliquee) |
+| 10/09 | **BRIQUE 4 FABLE — L6 AVEC DENOMINATEURS** (`CORE/research/surveillance_l6.py`, `test_l6_denominateurs` 12/12) : (G) `volumetrie_cash` = barres cash 9h30-16h00 stable sur 390 — LE compte qui FERME (ALERTE sous 390 - MAX_TROUS_CASH un jour normal ; un ferie du calendrier rend INFO) ; le compte Globex (1 380) ne ferme PLUS (INFO `globex_incomplet`, se lit le lendemain — le « 90 % a 20h41 » n'est plus une alerte) ; (H) `vix_cash_zero` = ALERTE au-dela de MAX_TROUS_CASH minutes a vix_level = 0 en cash — MESURE sur 130 jour-instruments : les pannes du lot durent 101, 147, 160, 210 min, jamais une minute isolee, donc pas de seuil invente ; (I) `derive_feature` = compte C++ (`delta_divergence_any`) / compte RECALCULE (`_div_recalc` : plus-haut de cloture sur 10 barres 1 min sans plus-haut du CVD, et le miroir — DEFINITION v1 ECRITE, A VALIDER PAR FABLE), ratio hors [1/3 ; 3] = INFO `derive_feature`, jamais ALERTE (une derive informe). Reel 09/09 : NQ C++ 189 / recalcule 51 = x3,71 → la feature s'emballe (les ED10 NQ du jour portent caveat_F15) ; ES 185/74 = x2,50, meme ordre ; 0 ALERTE | « integrite ferme, derive informe » (Fable Q4) rendu mecanique : seuls G et H peuvent etre ALERTE, et un test le prouve | `surveillance_20260909` regenere avec les neuf controles |
+| 10/09 | **BRIQUE 5 FABLE — LE RAPPORT GENERE, PAS REDIGE** : `V3/pourquoi_plus.py` (appele par `pourquoi.py` a 23h01) ecrit les deux lignes qui manquaient — (1) les LIEUX SANS REACTION des quatre par hypothese x instrument (etat, marge, heure, ce qui a manque — depuis marges_quatre) ; (2) TRADER vs MACHINE : chaque clic du journal manuel (7 champs : heure_et, sym, side, prix_entree, prix_sortie, issue, pourquoi) face aux signaux de la machine a ± 15 min, et la journee de la machine ; `--ecrire` regenere dans le journal la section « ce que le bot a vu » entre deux marqueurs, jamais une ligne du trader. `recit.py` : l'OBSERVATION separee de l'INTERPRETATION — « AU-DELA N contrats (delta), D = duree, R = distance en ATR » est un fait ; « H-PIEGE : oui » n'entre que si le niveau est REGAGNE. Journal manuel : 7 champs + `ce_que_j_ai_vu` + `carte_visible` | un rapport redige raconte ; un rapport genere se compare jour a jour | 09/09 : les 8 lignes des quatre, la journee de la machine, journal present mais AUCUN clic note |
+| 10/09 | **BRIQUE 3 — LA CARTE DU MATIN existe, et son tirage en aveugle est FIXE** : `V3/carte_matin.py` (9h25 ET, `execution/carte_matin.bat`) rend, par instrument, les PRIX ou chaque hypothese des quatre tirerait — niveau + bande `lieux.BANDE` en prix sur le metre que la chaine lira a 9h30 (`atr_veille`, derniere session complete), les dix niveaux de H8p, les reperes de la veille avec leur source (`_lvl` ou close + dist). H2p / H6p disent « pas encore » avant l'ouverture (bandes RTH et IB n'existent pas a 9h25). TIRAGE : **SEED = 20260910**, DEBUT = lundi 07/09/2026 (semaine 1), blocs d'une semaine, 8 blocs tires d'un coup (4 visibles / 4 non, permutation seedee), redessines tous les 8 avec le MEME generateur ; la carte est TOUJOURS generee et stockee (`LOGS/carte/carte_<jour>.txt`), affichee les blocs visibles seulement ; le journal manuel du jour porte `carte_visible: true|false` (gabarit cree si absent — la machine n'ecrit que sa ligne) ; `--forcer` affiche sans jamais ecrire dans le journal. AUCUNE lecture avant huit blocs ; jour 61+ : trades manuels avec / sans et ECART trader-machine avec / sans | le protocole pre-enregistre le 10/09 (Q8), rendu executable le jour meme — la seed est ici, elle ne bouge plus | `test_carte_matin` 12/12 (deterministe, blocs, 4/4, journal intact) ; tache planifiee 15h25 Paris : a creer par Jackson (`schtasks`, meme piege DST que rythme_soir) |
+| 10/09 | **REVIEW des briques 3-4-5 (code-reviewer) : GO-AVEC-RESERVES, douze reserves EXECUTEES avant commit** — R1 (critique) : la carte etait VIDE a 9h25, son seul horaire (`atr_veille_15` n'indexait que les dates a cash ; le test tournait sur un jour complet — VALIDATION_MISS consigne) → indexation sur toutes les dates du frame, test « nuit seule » (atr_ref 25/25, carte 14/14), verifie sur le brut reel du 10/09 a 04h42 ET : metre 10,80 pts ; R2 : garde TARDIVE sur la DONNEE (une barre cash deja la → carte etiquetee, rc 2, rien au journal) ; R3 : marges_quatre AVANT pourquoi dans le rythme (1b/5), journal manuel absent = pas un incident machine ; R4 : marqueurs machine du journal — refus si incoherents, lambda dans re.sub ; R5 : `derive_feature` = flag LIVRE `delta_divergence_any` (Python — le C++ `delta_divergence` fait 0-8 barres/jour, mediane nulle, inutilisable) contre SA mediane 20 j par instrument, garde « trop rare » ; reel 09/09 : NQ x4,50 vs mediane x3,28 (rel x1,37) et ES rel x0,97 → UN REGIME, pas la feature — le « F15 x44 » du 09/09 etait le flush ; R6 : un roll ATTENDU par le calendrier et un week-end sans fichier rendent INFO (une ALERTE ce soir aurait ferme le jour du GEL) ; R7 : VIX_MORT_MIN = 30 (pannes observees >= 101 min, une impression en retard de 10 min ne ferme rien) ; R8 : plus-hauts STRICTS, 0 barre cash = non mesurable ; R9-R12 : parsing, libelle `pas regagne dans la fenetre`, lint, `lieux.seuil_p` public, cartes aveugles dans `LOGS/carte/aveugle/` | deux VALIDATION_MISS en une journee, tous deux attrapes par la review avant commit : un test qui n'exerce pas la condition d'usage ne prouve rien | test_l6_denominateurs 19/19, test_carte_matin 14/14, test_atr_ref 25/25, test_lieux 16/16, structure / pourquoi / marges_quatre verts |
+| 10/09 13h30 Paris | **REGLE 38 — LA TAILLE DES DEUX JAMBES DE H3, mesuree SANS DEVENIR** (compteur `signaux_l3` sur le lot, 54 j x 2 instruments, 73 signaux des quatre AVANT C2/L5 ; matin = avant 11h00 ET) : H3 = 45, dont **15 LONGS** — la jambe ACCIDENTELLE (ES 7 / NQ 8 ; matin 4 / apres 11) — et **30 SHORTS** — l'hypothese ecrite (ES 18 / NQ 12 ; matin 5 / apres 25). Les autres : H6p 22 (ES 10 / NQ 12), H2p 3 (ES 2 / NQ 1), H8p 3 (ES). Un tiers des H3 est la jambe que personne n'a pre-enregistree : au jour 61 elle se lit A PART et ne peut pas « passer » (LECTURE regle 38, NEXT_CYCLE §5 septies) ; rien ne bouge au tag. Aucun devenir, aucun P&L lu (le premier compteur, via `confronter`, a ete TUE avant sa sortie : trop lent, et il aurait calcule le devenir — le second ne compte que les signaux). |
+| 10/09 14h10 Paris | **SCENARIOS — PREREQUIS 1-3, ATTENDU ECRIT AVANT DE LIRE LES MESURES** (module pre-enregistre : `V3/SCENARIOS_SPEC.md`, `scenarios/MISSION.md` ; les mesures tournent, aucune lue). Definitions ecrites avant : `recalc.open_type_r` (deux premieres barres 15 min, bande P10 sur `atr_veille`, retour sur `open_cash_lvl`), `recalc.range_r` (deux fiches F23 face a face, tenue CAUSALE a i+1, acceptation = deux clotures strictement au-dela, regain = deux clotures dedans ; `test_range` 26/26 dont DIRECT = RETROSPECTIF sur ES et NQ 09/09), `mesure_reactions` (depassement = meche au-dela du niveau sur la barre du test, reagit = tenue causale, niveau qui bouge exclu). ATTENDU — (1) types d'ouverture : ENCHERE majoritaire (> 40 %), DRIVE minoritaire (< 20 %), les deux autres entre ; c'est un a priori Dalton, pas une mesure. (2) IB comme premier range : largeur p50 dans 0,8-2,5 ATR (post-it §2.2) ; ETABLI atteint sur MOINS de 30 % des barres (deux tenus par bord avant la cassure, c'est exigeant — le « 70 % en range » de Jackson ne se lira pas sur l'IB seule) ; IB cassee (deux clotures) plus de 60 % des jours ; premiere cassure echouee (regain) entre 40 et 60 % (« la plupart », Dalton, = au-dessus de 50 %). (3) reactions : murs `mq_call/put` et PDH/PDL plus larges que la VA de la veille (depassement p80 en ATR superieur) ; VA/VWAP/IB p80 autour de P10 (0,10 ATR) — c'est l'hypothese de la spec §2, a verifier. Ce qui sort de l'attendu se dit tel quel. |
+| 10/09 14h30 Paris | **SCENARIOS — LES DIX DECISIONS DE FABLE, avant la grammaire** (details : `scenarios/MISSION.md`) : (1) la grammaire ne lit que la tenue CAUSALE `tenu_a` et les acceptations a deux clotures, jamais l'`issue` F23 (NEXT_CYCLE §5 octies) ; (2) v0 = UN range par journee, l'IB, les journees a deux ranges en S_AUTRE ; (3) ETABLI reste strict, etat de sequence POSE qui decrit sans valider (`barres_depuis_pose`) ; (4) zones ASYMETRIQUES : dedans = P10, dehors = p80 des depassements sur les tests TENUS (`quantile_contenance: 0.80`) ; (5) ZONE_DEPLACEE par saut > 1 tick du niveau reconstruit, avec l'heure — `mq_snapshot_ts` absent du brut (verifie), demande au DMP en NEXT_CYCLE ; (6) compression sur l'EXTREME de la barre du test (`range_r` corrige, test [1k] au tick) ; (7) le TAG demain matin sur la tete a 9h00 Paris, apres relecture, avant l'ouverture ; (8) regle 39 : le scenario DECRIT, ne decoupe pas le verdict (LECTURE, pre-enregistree) ; (9) ses trois attendus du rejeu, ci-dessous ; (10) 0DTE `dormant` avant 14h00 ET, `dist_mq_hvl < 0` = prix au-dessus du HVL, prouve sur barres reelles (`test_cote_hvl`). |
+| 10/09 14h30 Paris | **SCENARIOS — ATTENDU DU REJEU (spec §4.4), PRE-ENREGISTRE PAR LA RELECTRICE (Fable), ecrit AVANT toute grammaire et tout rejeu** : couverture des canoniques sur les 57 jours = **60 %** (sous 45 % la grammaire est trop courte, on ajoute des sequences avant tout affichage ; au-dessus de 80 % les scenarios sont trop larges, S_AUTRE trop rare) ; scenarios valides a 10h30 encore vrais a 16h00 = **55 %** (sous 40 %, la validation a 10h30 est trop precoce par construction) ; controle negatif (un scenario tire au sort par jour, mille tirages) : la grammaire bat le tirage d'au moins **15 points** sur les deux mesures, hors bruit — sous 15, le module decrit le passe. Aucune direction attendue sur quoi que ce soit. Copie dans `scenarios/seuils.yaml` (`attendu_rejeu`). |
+| 10/09 15h05 Paris | **SCENARIOS — PREREQUIS 1-3, MESURE (57 journees par instrument, lecteur commun `scenarios/lot.py`, atr_ref ; rapports `scenarios/rapports/*.md`) — contre l'attendu de 14h10** : (1) types d'ouverture ES / NQ : DRIVE 2 / 0 %, TEST_DRIVE 43 / 57 %, REJET_RENVERSEMENT 21 / 20 %, ENCHERE 34 / 23 % — ECART : ENCHERE n'est pas majoritaire et DRIVE n'existe pas a 30 minutes (la bande P10 est traversee des deux cotes par presque toute barre de 15 min : TEST_DRIVE avale DRIVE) — definition gardee telle qu'ecrite, candidat cycle 2 en NEXT_CYCLE §5 nonies ; (2) IB comme premier range : largeur p10 / p50 / p90 = 1,72 / 2,91 / 5,03 ATR-15m (ES) et 2,30 / 3,24 / 5,84 (NQ) — ECART : plus large que les 0,8-2,5 du post-it ; ETABLI strict = 0 jour ES / 1 jour NQ (attendu < 30 % des barres : 0 %, POSE decrit le reste) ; IB cassee 75 / 72 % (attendu > 60 %, conforme) ; premiere cassure echouee 53 / 54 % (dans l'attendu 40-60, « la plupart » = tout juste) ; retestee 20/43 et 14/41, retest tenu 8 et 4 ; compression sur l'extreme AVANT la 1re cassure 1,18 / 1,08 contre 1,05 / 1,07 sans cassure — ECART : les meches s'allongent avant la cassure, elles ne se resserrent pas (description, pas de permutation) ; (3) reactions par nature, depassement des tests TENUS p80 en ticks (ATR) — ES : VA 27,8 (0,50), IB 7,8 (0,20), PDH/PDL 19,4 (0,25), OVN 20,8 (0,46), murs 16,2 (0,28, N=26) ; NQ : VA 310 (0,98), IB 32,6 (0,10), PDH/PDL 121 (0,50), OVN 94 (0,23), murs 390 (1,51, N=27) ; reagit (tenue causale) 51-71 % partout, casse F23 30-50 % — ECART : aucune nature n'est contenue par P10 (0,10 ATR), pas meme l'IB ; les murs sont plus larges que la VA sur NQ, pas sur ES ; VWAP et GEX_nearest bougent a chaque barre (112 / 151 tests exclus) : pas des zones. DEUX FAITS de donnees : (a) les `prev_*_lvl` du brut basculent a 12h59-13h00 ET sur 55 / 57 journees et prennent les `cur_*` de la minute d'avant (sonde 10/09 — c'est la fenetre w0 d'INCIDENT_LOG 04/09 et CONVENTIONS §9 ; 08/09 et 09/09, w1, ne basculent pas) → la mesure fige tous les niveaux a 9h30 (IB 10h30) et la VA du lot est un profil anterieur, pas J-1 (VA_veille_w1 : 0 test ES, 10 NQ) ; (b) les murs `mq_call/put` ne bougent PAS en seance dans le brut (2 sauts ES a 14h sur 57 jours, 0 NQ) : la mise a jour de midi attendue n'est pas dans les donnees, ZONE_DEPLACEE sera rare. `seuils.yaml` reste null ; les p80 tenus sont ecrits en commentaire a cote. Aucun devenir de trade lu. |
+| 10/09 15h50 Paris | **SCENARIOS — RELECTURE FABLE A `e26236a` : les ecarts tranches, les valeurs FIXEES** (`scenarios/seuils.yaml` v2026-09-10b, `MISSION.md`) — ecart 1 : DRIVE n'existe pas a 30 min → TROIS types en v0, DRIVE fusionne dans TEST_DRIVE avec `retour_open` journalise, traversee 1 min = candidat cycle 2 ; ecart 2 : l'IB est plus large que le post-it et c'est normal (les 0,8-2,5 decrivaient un range de milieu de seance) → `w_min / w_max` = p10 / p90 par instrument (ES 1,72 / 5,03 ; NQ 2,30 / 5,84), hors bornes = S_AUTRE(IB_hors_norme) ; ecart 3 : les meches s'allongent avant la cassure — on ne renverse pas l'hypothese apres coup : meme definition, colonne renommee `pression`, journalisee, PAS un etat, aucun seuil, H-PRESSION pre-enregistree cycle 2 (attendu : pression > 1,1 sur les 3 dernieres barres precede une cassure acceptee plus souvent que le hasard) ; ecart 4 : `dedans` reste P10, `dehors` = p80 mesure par nature — IB 8 / 33 t, PDH_PDL 19 / 121, OVN 21 / 94, VA_veille 28 / 310 PROVISOIRE (provenance w0_profil_anterieur, re-mesure au jour 20 de w1), murs ES 16 provisoire (N=26) / NQ null (1,51 ATR sur N=27 = un mur qui n'est pas la), VWAP et GEX_nearest null DEFINITIFS. ETABLI 0/57 et 1/57 = attendu ; un fait de mesure exige une NEUVIEME sequence maintenant : 53 % des premieres cassures echouent → S_DANS_HEADFAKE (cassure acceptee → regain a deux clotures → retour dans l'IB) et S_DANS_POSE (IB posee jusqu'a la cloture, 25 % des jours) canoniques v0 ; S_DANS_ROTATION garde pour l'ETABLI rare. Grammaire v0 = huit canoniques autrement composees. Attendus du rejeu inchanges (60 / 55 / 15). Tag demain 9h00 Paris sur la tete. « La grammaire peut se coder maintenant sur ces valeurs. » |
+| 10/09 16h15 Paris | **SCENARIOS — GRAMMAIRE v0 CONSTRUITE ET MESUREE sur le lot, contre l'attendu de la relectrice** (`scenarios/grammaire.py`, `zones.py`, `scenarios.py`, `sorties.py`, `erreurs.py` ; `test_grammaire` 24/24, `test_scenarios_soir` 18/18 ; rapport `rapports/scenarios_57j.md`, 57 j x 2, aucun devenir) — (1) COUVERTURE telle que pre-enregistree (scenario final EN COURS canonique) : **93 % ES / 93 % NQ** = TROP LARGE (> 80 %) ; la cause est mecanique : toute ouverture hors VA est une TEND en cours tant que rien ne l'invalide (30 / 57 jours), validee ou non. Couverture des canoniques VALIDES a la cloture (ligne 1 bis, ajoutee AVANT de la lire comme verdict, jamais substituee) : **58 % / 53 %** — dans l'attendu 45-80. A la relectrice de dire laquelle est « la couverture » ; les deux sont ecrites. (2) TENUE : valides a 10h30 encore vrais a 16h00 = 60 % / 75 % mais sur N = 5 / 4 (rien ne se valide a 10h30 sauf une reintegration acceptee tot) — trop petit pour un verdict ; la version large (en cours a 10h30 encore en cours a 16h00) = 67 % / 64 % sur N = 54 / 53. (3) CONTROLE NEGATIF : le tirage au sort (mille) couvre 16-17 % en moyenne, p95 25-26 % → la grammaire bat le p95 de **+68 / +67 points** sur la couverture et +40 / +50 sur la tenue (attendu ≥ 15). S_AUTRE 4 / 57 par instrument (IB_hors_norme 2-3, pas_de_VA 1, rejet_vpoc 0-1) ; bascules 0,88 / 0,96 par jour, max 5 ; S_DANS_HEADFAKE 2 ES / 6 NQ, tous valides ; S_DANS_POSE 4 / 2. Position d'ouverture sur le lot : au-dessus 22 / dans 17 / sous 17 — avec la reserve w0 (la VA de 9h30 est un profil anterieur). Rien n'entre dans une porte ; `scenario_en_cours` sur l'entonnoir attend la relecture de Fable (touche `chaine.py`). |
+| 10/09 16h30 Paris | **SCENARIOS — RELECTURE FABLE A `c6c12dd` : la grammaire est celle decidee, les mesures honnetes, trois arbitrages nets** — (1) LA COUVERTURE = les scenarios VALIDES a la cloture (58 % ES / 53 % NQ, dans l'intervalle) : le 93 % « en cours » est une POSITION deguisee en scenario (toute ouverture hors VA est une TEND tant que rien ne l'invalide) — la relectrice note que sa definition pre-enregistree etait mal posee ; l'« en cours » reste journalise comme part de journees avec une hypothese ouverte ; consequence : le titre porte l'ETAT (`en cours, non valide` en gris / `valide 10h45`), un scenario non valide ne fait rien s'armer (`arme: false`). (2) La tenue a 10h30 sur N = 5 / 4 : vrai et trop petit, PAS DE VERDICT — se lit au jour 20 de w1 ; la 2 bis (67 / 64 % sur 54) est le proxy DECLARE, un chiffre sur la position. (3) Les deux definitions validees avec une correction de NOM : `S_OUV_HAUT_REJET` disparait, `S_OUV_HAUT_REINT` (famille) avec `precision` dans {PULL, TRAV, null}, miroir EXACT de `S_OUV_BAS_REINT` — les codes sont des familles, PULL / TRAV des precisions datees, jamais des codes ; une famille sans precision est un canonique ; rejet au VPOC 1 / 57 reste S_AUTRE, revu au jour 20. Ce qui compte : S_AUTRE 4 / 57, tirage battu de +68 / +67, HEADFAKE tous valides, 0,9 bascule par jour, etape 8 retenue avant le tag. DEMANDES avant le mode vivant, FAITES le 10/09 soir : (a) le renommage HAUT_REINT (miroir exact, la famille REINT validee par l'acceptation des deux cotes — c'est le choix qui rend le miroir exact, dit tel quel) ; (b) `etat_scenario` dans {en_cours, valide, invalide} + `titre` sur chaque ligne ; (c) la reserve w0 en gras en tete du rapport : les vrais nombres commencent ce soir, 23h01, sur le 10/09. Tag demain 9h00 Paris sur la tete. |
+| 10/09 16h45 Paris | **SCENARIOS — MESURE APRES LES TROIS DEMANDES de c6c12dd** (familles en miroir exact, REINT validee par l'acceptation des deux cotes ; `rapports/scenarios_57j.md`) : COUVERTURE = canoniques VALIDES a la cloture **61 % ES / 56 % NQ** (attendu 60, 45-80 : dans l'intervalle — les deux journees BAS_REINT sans precision comptent desormais, comme leur miroir HAUT) ; hypothese ouverte 93 % (description) ; tenue a 10h30 : 71 % / 71 % sur N = 7 / 7 — pas de verdict, jour 20 de w1 ; large 69 / 66 % sur 54 / 53 ; tirage battu de **+67 / +65 points** (p95 26 / 28 %). Rien n'a bouge d'autre. |
+| 10/09 17h30 Paris | **SCENARIOS — LISTE FUSIONNEE (Fable) : PHASE A CODEE sur ordre de Jackson** (seize fichiers, trois phases ; le document de Fable fait foi, `MISSION.md`) : `SPEC_VITRINE.md` (cinq phrases, frontiere des ecritures = journal_manuel + alertes_ + MUET) ; l'ECRIVAIN `boucle.py` (un processus, recalcule la journee entiere a chaque barre complete, `direct_<jour>.jsonl` DISTINCT du rejeu `scenarios_<jour>.jsonl` — la paire que 5b/5 compare, heartbeat_scenarios.json, dort hors cash / ferie / week-end) + garde toutes les 5 min avec backoff (Python, comme le coureur) ; `vitrine.py` + `vitrine.html` (une seule source HTML, `/etat.json`, ecrivain muet > 60 s, bandeau NON MESURE w1, un scenario non valide n'arme rien) ; `alertes.py` (cinq evenements, gabarits dans le yaml, silence 9h30-9h35, MUET, idempotence) ; `noter.py` (NOTER -> journal manuel, HORS_SCENARIO, side jamais infere) ; `fenetre.py` (pywebview, pose `scenarios_visibles : oui` le jour ou elle tourne) ; `pourquoi_plus` lit `carte_visible` et `scenarios_visibles` (deux populations). `grammaire_version` + `seuils_version` sur chaque ligne. Premier tour reel de l'ecrivain a 11h12 ET sur le 10/09 ; premieres alertes reelles : ovn_low cassee 10h00, et un 0DTE dormant qui sonnait -> tu (les zones dormantes n'ont ni memoire ni evenement avant 14h00). Rien n'est lance en tache avant le tag ; les `.bat` portent la commande `schtasks`. |
+| 10/09 18h00 Paris | **SCENARIOS — PHASE A RELUE A `2670789` PAR FABLE : ELLE PASSE** — verifie sur le code : la frontiere tient (seules ecritures : journal_manuel, alertes_<jour>, MUET ; `grep` confirme ; NOTER en .tmp + os.replace, side jamais deduit, rien efface) ; les deux journaux sont distincts (boucle -> direct_<jour>, rejeu -> scenarios_<jour> : la paire que 5b/5 compare, FUITE a deux choses a confronter) ; les alertes obeissent (silence depuis les seuils, MUET par fichier, idempotence (ts, sym, type, objet), `muet` / `silence` / `sonne` portes separement — on saura toujours ce qui AURAIT sonne) ; le garde en Python comme le coureur, 300 s, backoff : d'accord ; aucun mot interdit. Deux remarques, pas des corrections : (1) alertes.py reecrit le fichier entier a chaque passage (atomique, sur) — si un jour la boucle ralentit, c'est la (NEXT_CYCLE) ; (2) WebView2 non confirme : le premier lancement de la fenetre se fait AVEC JACKSON DEVANT, pas en tache — si elle s'ouvre vide, c'est ca, pas la page. Ce soir 23h01, 5b/5 sur le 10/09 : premiere comparaison direct / rejeu d'une vraie journee. Demain 9h00 : la tete, le tag, puis scenarios.bat, le garde, la vitrine, la fenetre — dans cet ordre, rien avant le tag. « Le module a existe une journee en direct, a sonne deux fois, a ete tu une fois pour une bonne raison, et n'a touche a rien. » |
+| 10/09 19h15 Paris | **SCENARIOS — PHASE B1 ET B5 CODEES (GO Jackson, soir du 10/09)** — B1 `zones.setups_armes` : pour chaque zone, ce qui tirerait ici et ce qui manque encore, LU dans la decomposition `marges_quatre.exposer` des quatre (marge / porte / regime / reactions dans l'ordre de la docstring gelee — la PREMIERE condition fausse nomme le manque), jamais une condition recopiee : H6p sur ib_high / ib_low, H8p sur la plus proche de ses dix niveaux qui est une zone ; H3 (VA courante, quarantaine) et H2p (bandes VWAP) ne sont pas des zones et sont rendus a part (`setups_hors_zones`, avec leur lieu) ; metre ou colonne absents -> `lieu_inconnu` / « x (colonne absente) », rien d'invente ; C2 : aucune decomposition exposee en v0, absent. Vu sur ES 09/09 : 12h30 ib_low H6p short lieu atteint (-1,3 t), manque `cloture_au_dela` ; 15h45 lieu atteint, manque `finish`. B5 `carnet.py` : cumul par type (compte, jours, EXEMPLE, candidat cycle suivant), par jour, par bloc de deux semaines (le taux, spec §8), recalcule depuis les fichiers (idempotent), un seul ecrivain (`carnet_maj` retire d'erreurs.py) ; ne touche rien d'autre (test : hash de seuils.yaml identique). La vitrine porte « ce qui tirerait ici », « hors zones » et le bloc « hier » (erreurs de la veille + carnet). Rien ne touche la chaine : B2 / B3 (chaine.py, barrieres du jour) restent apres le tag et relecture. |
+| 10/09 19h40 Paris | **SCENARIOS — le module lit LE MEME FRAME que la chaine** (`scenarios.charger` = charger_jour + chauffe 1 min + `injecter_recalculs`, comme `campagne._boucle`) : sans l'injection, `marges_quatre.exposer` rendait « rvol faux » pour une colonne ABSENTE — une condition qui ment, attrapee par test_grammaire [9c] avant tout affichage. Les trois mesures de la grammaire gardent `lot.journees` (trois jours de chauffe : elles ne lisent pas `setups_armes`), dit dans lot.py. |
+| 10/09 22h47 Paris | **RYTHME DU SOIR DU 10/09 lance a la main (Jackson : « lance tout »), et ce qu'il a trouve** — L6 : `reset_vwap ALERTE` sur NQ (saut de 8 pts du VWAP a 13h30 UTC, le VWAP reste a 168 pts du prix : la premiere minute de cash d'un gap de 5,7 ATR-veille, PAS un reset) ; `L0_DATA_L6_ALERTE` appliquee aurait FERME le live du 11/09 sur un faux positif. Mesure sur le lot AVANT de qualifier : les vrais resets posent le VWAP a 0,1-10 pts du prix pour des sauts de 10-270. Correction (CORE/research/surveillance_l6.py, hors perimetre gele, GO Jackson 22h47) : un reset = saut > seuil ET |vwap - close| < saut ; test_l6 [6a-6c] ; L6 rejouee sur le 10/09 -> NQ INFO « deplacement, pas un reset », verdict sans ALERTE, `etat_l6(20260911) = False`. Deuxieme incident : l'afficheur de L6 ne connaissait pas l'etat CONNU (KeyError), verdict ES ampute — corrige (INCIDENT_LOG x2). Campagne 10/09 : 0 signal des quatre sur ES et NQ (1 ombre16 chacun, 1 C2 NQ, 1 lieu muet ES) ; volumetrie cash 390 / 390 ; contrat 100 % U26 (pas de bascule : L0_CONTRAT_INACTIF reste observee). 5b/5 : ES et NQ `S_OUV_BAS_TEND`, 0 erreur, **direct = rejeu sur la premiere vraie journee : aucune FUITE**. Copilote lance a 22h50 (ecrivain, garde toutes les 5 min, vitrine, fenetre avec Jackson devant) — il dort jusqu'a 15h30 Paris, apres le tag. |
+| 11/09 10h30 Paris | **REGLE 38 REVISEE AVANT LE TAG — H3 se lit ENTIERE (N ~ 50), la jambe long est MARQUEE, jamais verdictee** (arbitrage Fable, sur mesure de Claude Code du matin). CE QUI A ETE MESURE : projection depuis le lot (73 signaux / 54 j x 2) sur 60 j x 2 — H3 entiere ~50, H3 short seul ~33, H3 long seul ~17, H6p ~24, H2p ~3, H8p ~3. H3 ENTIERE EST LA SEULE CASE DE TOUTE LA CAMPAGNE AU-DESSUS DE N = 40. La version de la regle 38 ecrite le 10/09 au soir, en coupant les jambes POUR LE VERDICT, faisait passer la seule hypothese testable sous le seuil : soixante jours sans pouvoir conclure sur rien — un piege, ecrit de bonne foi pour etre honnete, jamais recalcule derriere. La regle 9 l'interdisait deja dans les deux sens (ni fusionner, ni decouper sous la puissance). DECISION : le verdict du jour 61 porte sur H3 ENTIERE ; la jambe est marquee sur chaque signal — elle est DEJA dans le journal, `snapshot_id` finit par L ou S, aucune ligne de code a changer — et se lit DESCRIPTIVEMENT (part, heure, comportement) ; un resultat sur le short seul ou le long seul est une observation a PRE-ENREGISTRER au cycle 2, jamais une conclusion. Le long ne peut toujours pas « passer », il ne peut pas non plus faire echouer H3 a lui seul. Une regle de LECTURE a le droit d'etre completee avant le gel : c'est ce que `LECTURE_JOUR_61` dit de lui-meme, et c'est fait AVANT le tag, pas apres. Fond assume et redit : la campagne est sous-puissante (regle 10), le jour 61 aura UN verdict solide, des dizaines de signaux descriptifs, et un cycle 2 qui demarre avec trente hypotheses deja en ombre au lieu de zero. |
+| 11/09 10h35 Paris | **ROLLOVER, jour 2 de la ligne B : rien ne change** — le fichier du 11/09 ouvre en **U26** (ES 557 lignes 100 % ESU26 a 10h30 ; NQ verrouille par le coureur au moment du controle, meme fichier, meme source) alors que `calendrier.contrat_actif('20260911')` dit Z26. L'ecart mesure le 10/09 est donc MAINTENU au deuxieme jour : `L0_CONTRAT_INACTIF` reste **observee**, aucune modification du YAML, aucune porte touchee avant le tag. Remise en `appliquee` le premier jour ou un fichier OUVRE en Z26, avec sa ligne. |
```

## hypotheses.py — LES_QUATRE (CORE, hors miroir : le diff est colle ici pour la relecture)

*Ce que `test_spec_l3` epingle n'a pas bouge ; ce qui a bouge, c'est le METRE (`atr_ref` a la place
de `atr_barre`, brique 1 du 09/09) et la docstring datee de l'exception.*

```diff
diff --git a/CORE/research/hypotheses.py b/CORE/research/hypotheses.py
index 9171b5a..a12e45e 100644
--- a/CORE/research/hypotheses.py
+++ b/CORE/research/hypotheses.py
@@ -9,6 +9,14 @@ voit pas.
 Rien ici ne doit etre modifie apres le tag. Une idee nee en lisant les resultats
 va dans `NEXT_CYCLE.md`.
 
+EXCEPTION DU 09/09 (DECISIONS, brique 1 Fable) — LE METRE, PAS LA REGLE.
+`seuil_ticks` lit `atr_ref` (= `atr_barre` si fini, sinon la mediane de l'ATR
+agrege de la derniere session cash COMPLETE, `recalc.atr_veille_15`).
+`np.maximum(0,10 x NaN, 2)` valait NaN : la bande n'existait pas avant 11h00
+parce que le metre etait vide, pas parce que la regle l'a voulu (0 signal des
+quatre sur 52 j x 2 avant 11h00, rapport trou_atr_les_quatre). Planchers,
+fractions, reactions : inchanges. `atr_source` dit lequel a servi.
+
 
 UNITES — la source d'erreur numero un de ce depot
 --------------------------------------------------
@@ -20,7 +28,9 @@ livres (facteur 4) cette semaine, `atr` lu au lieu de `atr_14m`, et le seuil de
     `dist_*`          TICKS.  Mesure du 06/09 : le niveau reconstruit par
                               `close + dist x 0,25` est constant sur la journee
                               et tombe sur des strikes ronds.
-    conversion        `atr5_ticks = atr_barre / tick`, tick = 0,25 sur ES et NQ.
+    `atr_ref`              POINTS. `atr_barre` si fini, sinon l'ATR de la derniere
+                              session complete (`atr_source` = barre | veille).
+    conversion        `atr5_ticks = atr_ref / tick`, tick = 0,25 sur ES et NQ.
 
 **Toute comparaison entre une `dist_*` et un multiple d'ATR passe par
 `seuil_ticks()`.** Comparer une distance en ticks a `0,10 * atr_barre` en points
@@ -87,8 +97,8 @@ def h2(df, tick=TICK):
     COLONNES   : bandes recalculees par `recalc.vwap_bandes(..., n_sd=2.0)` (A),
                  `delta_bar` (A), `finish_delta_pct` (A), `ib_range_atr` (B)
     """
-    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
-    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
+    p10 = seuil_ticks(df["atr_ref"], "P10", tick)
+    p15 = seuil_ticks(df["atr_ref"], "P15", tick)
     regime = _f(df, "ib_range_atr") < 0.8
     du, dd = _f(df, "dist_vwap_rth_sd2u_r"), _f(df, "dist_vwap_rth_sd2d_r")
     delta, fin = _f(df, "delta_bar"), _f(df, "finish_delta_pct")
@@ -118,7 +128,7 @@ def h3(df, tick=TICK):
     revenir » se lit donc `high > VAH` (la meche depasse) et `dist_cur_vah > 0`
     (la cloture est revenue dessous).
     """
-    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
+    p10 = seuil_ticks(df["atr_ref"], "P10", tick)
     dh, dl = _f(df, "dist_cur_vah"), _f(df, "dist_cur_val")
     fin = _f(df, "finish_delta_pct")
     vah = _f(df, "close") + dh * tick
@@ -189,8 +199,8 @@ def h6(df, tick=TICK):
     AU-DESSUS de l'IB. C'est ce signe qui distingue le retest par le haut (on
     est repasse au-dessus) du retest par le bas.
     """
-    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
-    p05 = seuil_ticks(df["atr_barre"], "P05", tick)
+    p15 = seuil_ticks(df["atr_ref"], "P15", tick)
+    p05 = seuil_ticks(df["atr_ref"], "P05", tick)
     regime = _f(df, "ib_range_atr") < 0.4
     dh, dl = _f(df, "dist_ib_high"), _f(df, "dist_ib_low")
     fin = _f(df, "finish_delta_pct")
@@ -227,7 +237,7 @@ def h7(df, tick=TICK):
     condition de reserve de liquidite qui fait tout le travail. Elle est donc
     ecrite serree, et exige qu'un niveau de reference ait ete REELLEMENT depasse.
     """
-    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
+    p10 = seuil_ticks(df["atr_ref"], "P10", tick)
     low, high, close = _f(df, "low"), _f(df, "high"), _f(df, "close")
 
     def depasse(cols, sens):
@@ -278,7 +288,7 @@ def h8(df, tick=TICK):
     — « normal mesure » et « jamais calcule » y sont indistinguables
     (CONVENTIONS §3.1, incident du 06/09).
     """
-    p20 = seuil_ticks(df["atr_barre"], "P20", tick)
+    p20 = seuil_ticks(df["atr_ref"], "P20", tick)
     pres = pd.Series(False, index=df.index)
     for c in NIVEAUX_H8:
         pres = pres | (_f(df, c).abs() <= p20)
@@ -303,10 +313,10 @@ def lieux(df, tick=TICK):
     et c'est precisement ce qui a manque a la lecture du 06/09, ou H6 rendait
     N = 0 sans qu'on voie que son regime couvrait 0,13 % des barres.
     """
-    p05 = seuil_ticks(df["atr_barre"], "P05", tick)
-    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
-    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
-    p20 = seuil_ticks(df["atr_barre"], "P20", tick)
+    p05 = seuil_ticks(df["atr_ref"], "P05", tick)
+    p10 = seuil_ticks(df["atr_ref"], "P10", tick)
+    p15 = seuil_ticks(df["atr_ref"], "P15", tick)
+    p20 = seuil_ticks(df["atr_ref"], "P20", tick)
     du, dd = _f(df, "dist_vwap_rth_sd2u_r"), _f(df, "dist_vwap_rth_sd2d_r")
     dh, dl = _f(df, "dist_cur_vah"), _f(df, "dist_cur_val")
     ih, il = _f(df, "dist_ib_high"), _f(df, "dist_ib_low")
@@ -368,8 +378,8 @@ def h2_prime(df, tick=TICK):
     reaction ramenait 27 signaux a 3, et le regime corrige ne coupe presque plus
     (141 sur 143).
     """
-    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
-    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
+    p10 = seuil_ticks(df["atr_ref"], "P10", tick)
+    p15 = seuil_ticks(df["atr_ref"], "P15", tick)
     regime = _ib_range_atr_r(df, tick) < 0.8
     du, dd = _f(df, "dist_vwap_rth_sd2u_r"), _f(df, "dist_vwap_rth_sd2d_r")
     delta, fin = _f(df, "delta_bar"), _f(df, "finish_delta_pct")
@@ -387,8 +397,8 @@ def h6_prime(df, tick=TICK):
     ramenes a 37 / 35 par le regime — sous le seuil de 40 avant meme la reaction.
     Annoncee NON TESTABLE.
     """
-    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
-    p05 = seuil_ticks(df["atr_barre"], "P05", tick)
+    p15 = seuil_ticks(df["atr_ref"], "P15", tick)
+    p05 = seuil_ticks(df["atr_ref"], "P05", tick)
     regime = _ib_range_atr_r(df, tick) < 0.4
     dh, dl = _f(df, "dist_ib_high"), _f(df, "dist_ib_low")
     fin = _f(df, "finish_delta_pct")
@@ -413,7 +423,7 @@ def h8_prime(df, tick=TICK):
     et un finish contraire ne coexistent presque jamais. Elle est lancee pour que
     ce soit ecrit, pas parce qu'on l'espere.
     """
-    p20 = seuil_ticks(df["atr_barre"], "P20", tick)
+    p20 = seuil_ticks(df["atr_ref"], "P20", tick)
     pres = pd.Series(False, index=df.index)
     for c in NIVEAUX_H8:
         pres = pres | (_f(df, c).abs() <= p20)
```

