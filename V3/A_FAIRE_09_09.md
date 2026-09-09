# À FAIRE — 09/09 : les deux audits Fable, consolidés

*Un seul endroit pour tout ce que les audits du 09/09 ont soulevé, pour que rien
ne tombe entre deux sessions (Jackson : « qu'on ne les oublie pas, qu'on ne
passe pas à côté »). Deux audits : la REVUE QUALITÉ (14 fichiers logique, à
`045443c`) et l'AUDIT V1-LESSONS (chaîne V3 en 12 étapes vs lanceur V1
`MIA-IA-SYSTEM-2026-`). État : ✅ fait / 📝 tracé / ⏳ passe dédiée.*

## ✅ Corrigé le 09/09 (revue qualité)
- **A2** frais → `None` jamais `False` sur ATR absent (cfb7af5)
- **C1** fail-loud sur sym inconnu, plus de défaut ES silencieux (cfb7af5)
- **A3** SPEC news alignée sur `is_news_60m` (±60 min), le −15/+30 par niveau
  = NEXT_CYCLE (391bf88 → ad25e65)
- **C3** sortie horaire PAR FAMILLE en config L5 (`seuils.yaml`) + `sortie_source`
  journalisé (repli défaut jamais silencieux) (ad25e65)

## 📝 Tracé (notes, pas de code)
- **A4** LECTURE règle 19 : le journal LIVE ne fait pas foi sur `POSITION_OUVERTE`
  jusqu'au pas 2b (défaut §0). Le rejeu 21:01 est juste.
- **B2 / C2** PLAN §7 : B-NIV exige une intention en PRIX absolus (cycle 2) ;
  TTL état 60 s + battement d'état toutes les 30 s.
- **A1** gamma : bug documenté à 3 endroits (docstring `_gamma`, INCIDENT_LOG,
  garde YAML au-dessus de `mode: observee` — ne pas promouvoir sans le fix).

## ⏳ PASSE DÉDIÉE — avant le gel SI POSSIBLE
- **#4 — LE LIEU dans la ligne PASSE** (V1-lessons #4). **PAS une colonne** :
  vérifié dans `CORE/research/hypotheses.py`, le lieu dépend de famille+sens et
  `h7` lit TROIS niveaux (ovn_low/pdl/ib_low). Exige que les fonctions
  d'hypothèse surfacent LE niveau déclencheur (nom de colonne + prix reconstruit
  `close + dist·tick` + `dist_ticks`), puis `chaine` le journalise dans
  l'entonnoir principal. Touche L3 + chaine GELÉS → review. « Si possible » (Fable) :
  colonne de journal, pas une décision — ne change pas ce que la chaîne décide.

## ⏳ PASSES DÉDIÉES — quand elles viennent
- **Passe lecture** : découper `lecture.py` (plafond 300), PUIS
  - **R3 (review brique 1, 10/09) — AVANT LE GEL** : `lecture.lire` n'expose
    que `atr_barre` → `vetos._frais` (`L5_FRAIS_TROP_LOURDS`) et
    `_dist_hvl_atr` (`L0_REGIME_INDETERMINE`), observées, rendent un TROU sur
    toute la population du matin (`atr_source = veille`) — « vide par
    construction », la classe que la brique 1 corrige pour L3. Fix : clé
    `atr_ref` dans `lec`, les deux consommateurs dessus, fixtures
    `test_portes`, + scénario `test_faux_live` avec une barre du matin
    (`atr_barre` NaN, `atr_ref` fini) qui PASSE en strict.
  - **A1** gamma PAR SENS : `side` dans `lire` + porter `gamma_block_short`
    dans l'agrégation 15 min (ABSENTE aujourd'hui — mesuré). Porte OBSERVÉE,
    ne bloque rien, mais corrompt la lecture du jour 61 (veto mono-sens).
  - **B3** `rang_du_jour` depuis `minutes_et` (au lieu de `i`, qui suppose
    silencieusement un `df` cash commençant à 9h30 ET).
- **B1 — coûts SOURCE UNIQUE** : 4 copies (`chaine.py`, `vetos.py`,
  `hypothesis_runner` CORE, `seuils`). `chaine.py:173/189` garde le silent-fallback
  ES que C1 a tué dans `vetos` — deux politiques pour le même nombre. Règle 1 de
  METHODE, 8 jours de retard. Une source, fail-loud partout, + test `grep`
  `2.82|4.32` dans `*.py` qui échoue.
- **`triple_barriere` (CORE)** : coller la fonction + ses tests à Fable. QUATRE
  conventions qui décident TOUTES les mesures : TP+SL touchés la même barre =
  SL (conservateur) ou TP ? entrée `open(t+1)` réelle ou `close(t)` ? frais
  déduits 1× ou 2× ? expiration à la clôture de la 20e barre ou de la 19e ? Si
  UNE réponse est « TP », 60 jours de devenirs sont optimistes.

## ⏳ PAS 2b / EXEC (post-gel) — le gros morceau, cahier des charges de l'audit V1
- **Pas 2b** (câblage de l'état, après le gel) : brancher `POSITION_OUVERTE` /
  `STOP_*` / `COOLDOWN` sur `etat_<sym>.json` ; TTL 60 s + battement 30 s ;
  réconciliation au boot broker → fichier → journal (`STOP` sur divergence) ;
  `source_etat` sur chaque ligne. + les V1-lessons qui en dépendent :
  - **#1 `L0_NIVEAU_RECENT`** (anti double-tap) : niveau tradé interdit 20 min
    après un gain / 45 après une perte, depuis `etat_<sym>.json` (`dernier_trade`
    a le `snapshot_id`, il faut ajouter le PRIX). Observée.
  - **#2 `L0_STREAK`** : 3 pertes consécutives → pause 30 min. Même source. Observée.
  - **#5 snapshot du rejet L4** : L4 journalise ses `k` barres 1 min AVEC le
    verdict, pas seulement le verdict. L4 ne trace RIEN aujourd'hui.
- **Pas 3 (EXEC)** : source DTC = `BOT/dtc_connector.py` V2 (cf `EXEC_COPIE_V1.md`,
  à copier — seule étape où V1 > V3). + **#3 rotation d'état** (`pnl_jour`, streak,
  cooldown à 22:00 UTC, JAMAIS au boot). + lecture des 2 instruments EN PARALLÈLE
  (V1 `_read_all_snapshots_parallel`, un timeout par instrument).
  + **glissement EOD mesuré** (confrontation `triple_barriere` 09/09) : le prix
  15h55 réel où EXEC est plat n'est PAS `close_945` (16h00, où sortent CORE ET la
  ref) ; mesurer `prix_15h55_réel − close_945` par trade de fin de journée dès le
  1er ordre SIM — 5 min de clôture, non modélisables, seulement mesurables.

## ⏳ DONNÉES — à investiguer
- **`08/05` a une donnée cash tronquée** (dernière barre 14h30 = 870, pas 945),
  révélé par la confrontation `triple_barriere` (`INDETERMINE` résiduel). `09/07`
  (Labor Day) et `09/09` (collecte en cours) sont attendus ; `08/05` non — trou de
  collecte ? demi-séance oubliée du calendrier ? À nommer avant le jour 61.
- **Pas 4 `pourquoi.py`** : trace un `snapshot_id` de bout en bout (retenu →
  émis → exécuté → refusé pourquoi).

## ⏳ JOURNÉES MUETTES — ce qui manque pour qu'elles paient (09/09 soir)
*Mesuré : 6 journées sur 9 sans signal des quatre (67 %), 2/2 sur la campagne.
C'est le RÉGIME. On ne touche ni bande ni déclencheur (pattern 11) ; on complète
ce qu'un silence ÉCRIT.*
- ✅ **BRIQUE 1 FAITE (nuit du 09/09, DECISIONS × 2)** : `seuil_ticks` et les
  brackets lisent `atr_ref`, `atr_source` partout, `atr_veille_15` = dernière
  session COMPLÈTE, L6 `echelle_douteuse`, `test_atr_ref` 19/19, jours 1-2
  rejoués (≥ 11h identique ; matin : ES ED10 08/09, ES ED04+ED06 09/09, bracket
  NQ C2_80PCT). Lot : ES 6 / NQ 5 lieux des quatre le matin. Check (ii) ED06 =
  RÉSOLU (le trou). Reste (i) ED02 vs regain prev_val NQ 11h15.
- **Trou ATR = 23 % de CHAQUE séance** — DÉJÀ MESURÉ le 08/09
  (`L3_declencheurs/rapports/trou_atr_les_quatre_20260908.md` : 0/58 signaux des
  quatre 9h30-11h00 sur 52 j × 2, attendu tenu ; décision d'alors : rien au gelé,
  SPEC L3 limitation n° 2). NEUF le 09/09 : **les SEIZE aussi** (0/43 ED avant
  11h, `hypotheses_ed` lit `seuil_ticks`) et le plancher 2 t disparaît
  (`np.maximum` propage NaN). **ARBITRAGE FABLE 09/09 soir : voie (a) AVANT LE
  GEL** — `atr_barre` NaN ← `recalc.atr_veille_15` (existe : L1 depuis le 07/09,
  DIV_DELTA v2), `atr_source` journalisé (`barre|veille`), `seuil_ticks` intact.
  **Deux conditions** : l'attendu écrit AVANT (« N lieux des quatre 9h30-11h00
  sur 57 j avec atr_ref, aucune direction attendue », = `mesure_trou_atr.py`
  rejoué avec le repli) et la lecture SÉPARÉE `atr_source = veille` au jour 61
  (règle 15 : un gap de 2 ATR rend l'échelle de la veille fausse). Re-rejeu des
  jours 1-2 (déterministe, une population ; anciens journaux CONSERVÉS,
  renommés, jamais effacés). Même repli pour les brackets d'ombre.
  **Renverse la décision du 08/09 → ligne DECISIONS à écrire par Jackson.**
- ✅ **BRIQUE 2 FAITE (nuit du 09/09)** : `V3/marges_quatre.py` (étape 5b/5 du
  rythme, journal `marges_quatre_<jour>.jsonl`, schéma marges/2), parité
  barre à barre avec les gelées (`test_marges_quatre` 12/12, 0 écart / 1 248),
  règle 35 LECTURE. 09/09 : ES H3 QUASI 0,95 t (11h45), NQ H3 QUASI 0,7 t
  (9h45) ; 08/09 : NQ H3 lieu atteint 11h15, manque finish. **Reste** : la
  **carte du matin** (`carte_matin.py`, 9h25, même exposition en PRIX :
  niveau ± seuil, régime lu à 9h30, alternance en aveugle Q7) — brique 3.
- **Journal MANUEL absent du dépôt** (`V3/**/*manuel*` → 0). Seule pièce que la
  machine n'écrit pas ; sans lui l'angle trader d'un jour muet vaut zéro.
  `V3/journal_manuel/AAAAMMJJ.md` : heure, prix, sens, une ligne pourquoi.
- **Check (iii) résolu** : `h3` ne lit PAS `inside_cur_va` (code : `dist_cur_vah/
  val`, high/low/close, `finish_delta_pct`) — docstring fausse dans CORE gelé,
  à noter au cycle 2. Restent ED02 / ED06 (conditions vs 11h15 NQ, `mq_put` ES).

## ✅ Anti-patterns V1 à NE JAMAIS reprendre (déjà évités dans V3)
- **somme pondérée** (`ml_3layer`, contexte à 0,12) → V3 a le test anti-addition.
- **signal dérivé du régime** (`generate_fade_signal`) → REG autorise des
  familles, il ne déclenche rien (deux étages séparés).
- **taille dynamique + trailing stop** avant qu'une hypothèse les ait mesurés
  → non pré-enregistrés au cycle 1 ; au cycle 2 après 200 trades.
