# PROMPT DE REPRISE — à coller au début de la prochaine session
*Écrit le 07/09/2026, révisé plusieurs fois le 07/09 (relecture Fable,
coureur corrigé), puis dans la NUIT du 07 au 08/09 : mission Jackson
« câbler les déclencheurs un à un, jusqu'à GO » — 4 blocs exécutés, chacun
avec review agent et publication miroir. Se met à jour à chaque fin de
session si l'état a bougé.*

---

Tu reprends le chantier **MIA V3** — un système de trading **full rules**
(aucun ML au cycle 1), couche par couche, ES/NQ futures micros, barres 15 min.
Le dépôt est la mémoire : **rien de ce qui compte ne vit dans une
conversation.** Tu travailles sous la méthode de `V3/METHODE.md` — tu
construis, mesures, commites et publies ; tu ne scelles jamais seul ; Fable
(chat externe) relit à chaque scellement ; Jackson décide.

## 1. Lis dans cet ordre, avant toute réponse substantielle

1. `V3/METHODE.md` — les rôles, la brique en 8 étapes, les 14 règles dures.
2. `V3/STATUS.md` — l'état des briques.
3. `V3/A_FAIRE_07_09.md` — points 1-15 : les bloqueurs de revue (1-5, TRAITÉS
   le 07/09), la lecture des barres de nuit (points 1-10), la quarantaine F23
   (11), le récit (12), la carte (13), l'audit du narratif (14), l'audit
   direction (15 : H3+H7 contre-tendance 95-97 % les jours de tendance — le
   mode de mort de V1 ; B5 est l'antidote mesuré, H-B5TREND pré-enregistrée).
4. `V3/REPONSES_NARRATIF.md` — l'ordre en 7 étapes qui décidera si F23 devient
   une feature.
5. `V3/DECISIONS.md` + `git log --oneline -15` — ce qui est tranché.

## 2. L'état en six lignes (07/09 au soir)

- **L0 + L0-live** : scellée / mesurée (14 scénarios de faux live — un CHEMIN
  prouvé, pas un branchement : le bot n'emprunte pas encore
  `chaine.appliquer(strict=True)`). **L6** : passée.
- **L1** : B1p mesurée et écartée (couverture 100 %, séparation nulle/inversée) ;
  B1n attend F23 ; H-EXT pré-enregistrée pour le jour 61.
- **F23** : fiches testées au tick, MAIS `cur_*` en quarantaine (niveaux
  dynamiques) et « piégé » sous condition de déséquilibre (l'épisode 200 538
  contrats / delta −534 était une ROTATION). `recit.py` s'auto-vérifie et
  refuse de publier sur écart.
- **L4** : **J2 FAIT le 07/09** — mesurée aux trois k, séparation DANS LE
  BRUIT, k=2 écrit, L4 reste OBSERVÉE (elle ne passe pas sur le lot, se
  rejuge au jour 61). **L5 barrières J2 FAIT** : `barrieres.py` (B-ATR /
  B-NIV / B-NAT, parité 108/108) + `barrieres_du_jour.py` — reste le
  branchement au rythme 21:01 (Jackson) et la mesure 57 j (matin).
- **Campagne d'ombre** : démarrée le 08/09, **tag `campagne-ombre-1` posé**.
  Le coureur `V3/campagne.py` fait EXISTER la journée : LES_QUATRE
  pré-enregistrées + les SEIZE ED (`ombre16`) + **les C2 actifs**
  (`ombre_c2`), injection `rvol_r`/`cvd_sess_r`/SD2/`finish_r`/
  `vwap_slope_r`/`dist_vwap_rth_r` (chauffe 20 j), comptage par
  franchissement, journal VIDE = jour couru muet. Rythme 21:01 UTC =
  `campagne.py` puis `pourquoi.py` + journal MANUEL +
  `barrieres_du_jour.py`. Jamais le P&L. Rollover à contrôler le 10/09.
- **Ombre C2 (nuit 07→08/09, mission « un à un jusqu'à GO »)** : TROIS
  actifs — `C2_80PCT` (07/09), `C2_EOD` (08/09, r_min p25 0,273/0,275,
  sortie horaire 16h00, écart « range vs ATR-jour » ASSUMÉ → arbitrage
  Fable), `C2_DIV_DELTA` (08/09, attendu corrigé PAR LA MESURE : ~6/60 j —
  58 % des extrêmes dans le trou de chauffe ATR → arbitrage Fable
  ATR-VEILLE, pas P15/P20). **`C2_POOR` pré-câblé PAS actif** : v1 morte
  par construction (0 lieu / 52 j × 2, le flag roulant s'éteint au retour) —
  redesign J+2 avec brief Fable, rapport `lieu_poor_20260908`. Chaque bloc :
  review agent GO-AVEC-RESERVES, réserves appliquées, miroir publié.
- **Dette DST : FERMÉE pour L0 le 08/09** (`est_cash` + `initial_balance`
  sur `minutes_et`, parité 0/271 940 barres réelles — audit Fable §2).
  RÉSIDUEL côté recherche (surveillance_l6, classer_colonnes, test_ctx,
  sync_vps), deadline 31/10 — A_FAIRE pt 19.
- **Audit Fable 08/09 : EXÉCUTÉ pts 1-5 le jour même** — la campagne gelée
  est AVEUGLE avant 11h00 (mesuré : 0 signal / 52 j × 2, atr NaN 300/300 —
  SPEC limitation n° 2, LECTURE règles 11-13, phrase « ça ne marche pas le
  matin » INTERDITE) ; dette DST L0 fermée ; `atr_ref` généralisé (DIV v2
  ×4 lieux) ; EOD deux verdicts (`side_pur`/`rend_pts`, `close_1545`) ;
  80PCT règle d'ouverture journalisée. RESTE de l'audit : **B-BOUEE +
  branchement `barrieres_du_jour` au 21:01** (pt 6 — avec la mesure 57 j
  des barrières du matin), POOR v2 (après F23 hors quarantaine).
- **BLOQUEUR JACKSON** : 3 webhooks Discord actifs dans le dépôt principal
  public ; 75+ commits locaux attendent. Troisième jour. Dix minutes.

## 3. Le travail, dans l'ordre

**OBJECTIF DE LA SEMAINE (decide par Jackson le 07/09) : tout construire EN
OBSERVATION, fige vendredi 12/09** — pour que les 60 jours d'ombre soient
homogenes. Ordre : coureur live (strict reel) -> prerequis L4 -> L4 J2 ->
scalaires F23 (prev_* seulement) -> carte + recap Discord (nouveaux webhooks,
jamais le P&L) -> pont DTC (ordres de TEST Sim, hors chaine decisionnelle) ->
tache planifiee 21:01. Apres vendredi : on n'ajoute plus, on regarde tourner.
Au jour 61 on ne « corrige » pas : on bascule observee->appliquee pour ce qui
a survecu. Branchement decisionnel Sim : cycle 2, ~mi-decembre.

0. **Le coureur LIVE — FAIT le 07/09** (`V3/execution/coureur_live.py`, avec
   `sync_vps.py` et `etat_live.py`) : boucle sur le fichier vivant, `age_s`
   réel (~90 s via `--sync`), battements + signaux dans
   `LOGS/entonnoir/live_<jour>.jsonl` (append-only, SÉPARÉ de l'entonnoir
   officiel du rejeu). Testé en réel le 07/09 (férié) : `L0_FERIE_CME` bloque,
   trous DTC/colonnes_mortes bloquent en strict — attendu pré-enregistré tenu.
   **Reste : le LANCER en continu** (`python -X utf8
   V3/execution/coureur_live.py --sync`) — la nuit doit montrer
   SESSION_BLOQUEE + TROU_VIX (question 3 du constat) ; puis le pont DTC et la
   tâche planifiée (plus tard cette semaine, cf objectif).
1. **L4 J2** (spec : `layers/L4_orderflow/SPEC.md`, seuils mesurés dans son
   `seuils.yaml`) : bloc `l4` de `lecture.py` + test anti-fuite → `vetos.py`
   (5 vetos en SÉRIE, jamais un compte) → glissement → mesure k=1/2/3 →
   `k` dans DECISIONS.md. **Les QUATRE prérequis sont FAITS (07/09 au soir),
   chacun avec son test — plus aucun verrou devant J2** :
   - ~~`rvol_r` / `cvd_sess_r` dans l'agrégation~~ — **FAIT**
     (`injecter_recalculs` porte `cvd_sess_r` = cumul de session 17h ET via
     `recalc.cumul_delta`, jamais `cvd_day` ; `test_recalc_agg.py`,
     9e contrôle) ;
   - ~~reproduction des `ctx_*`~~ — **FAIT, mismatch = 0** (`test_ctx.py`,
     8e contrôle de publier.sh). La formule du code était bonne : les
     « écarts » étaient TROIS conventions (arrondi 6 décimales, fichier par
     date UTC vs pipeline par journée de trading, blocs ré-émis →
     dédoublonner + stable seulement). **`ctx_rvol_session` CONDAMNÉE**
     (contaminée par le producteur les jours à ré-émission) — INTERDITE
     pour L4, cf A_FAIRE point 17 ;
   - ~~B4 lit UNE colonne `im_smt`~~ — **FAIT** (seuils L1 : `colonne_smt:
     im_smt_divergence, instrument_smt: ES`, et la mesure 57 j ne fabrique
     plus d'accord) ;
   - ~~`lecture.py` refuse les `_source` proxy~~ — **FAIT** (test_proxys.py,
     7e contrôle de publier.sh). CONSÉQUENCE : le veto gamma lisait un proxy
     → porte passée OBSERVEE — **ARBITRAGE JACKSON avant vendredi, A_FAIRE
     point 16**.
2. **F23 étape par étape** selon `REPONSES_NARRATIF.md` §ordre — PAS avant L4.
3. La carte (`carte.py`, point 13) vient APRÈS L4 — le point 14 le dit : le
   narratif a déjà mangé une journée.
4. **Les vides de la photo structurelle** (revue Fable, 07/09 au soir) —
   par ordre : ~~L4 J2~~ (socle fait, reste la mesure) ; ~~SPEC L5~~ — **FAITE le 07/09** avec le chantier BARRIÈRES :
   brief Fable déposé (`L5_risque/BRIEF_NIVEAUX.md`), H-L5-NIVEAUX
   pré-enregistrée (le concept V1 de Jackson : SL derrière un niveau +
   buffer, TP devant), distributions mesurées, `seuils.yaml` L5 rempli.
   **Reste J2** : `barrieres.py` + tests + journal + mesure 57 j — hors
   ligne, rien ne touche au bot ; **le pont DTC** (aucun ordre nulle part — jeudi
   10/09 le rollover passera par `L0_CONTRAT_INACTIF`, test gratuit à
   REGARDER) ; **les règles PROP FIRM n'ont pas de nom** (seule la porte
   `L0_STOP_PROPFIRM` −200 $ existe — la brique complète est à nommer dans
   `NEXT_CYCLE.md`) ; les mesures de REG citées dans son README (99,7 %,
   1,8 bascule/jour) ne sont dans aucun `rapports/`. Et le RAPPORT_SESSION
   du jour 1 (08/09) — le pire jour pour le manquer.

## 4. Les règles qu'on ne re-négocie pas (chacune a coûté)

- Série, jamais somme (`grep` anti-score dans les tests) ; `None` jamais
  `False` ; aucune mesure hors `rapports/` ; aucun nombre dans le code ;
  l'attendu écrit AVANT chaque mesure ; unité statistique déclarée (bloc
  semaine pour ce qui est hebdo) ; signe avant magnitude ; deux conventions
  avant une anomalie ; un incident écrit le jour même ; rien ne change pendant
  la campagne ; **mesurer avant d'annoncer, et qu'un autre lise**.
- Publier = `sh V3/publier.sh` (DOUZE contrôles). Jamais de push direct.
- Le dépôt public est `github.com/jackson97300/mia-v3` (V3 seul). Le dépôt
  principal ne se pousse PAS tant que les webhooks ne sont pas révoqués.

## 5. Ce que tu fais en premier — un CONSTAT, pas une vérification

Réponds d'abord à trois questions par **oui/non, avec la preuve** :

1. **Le bot a-t-il tourné aujourd'hui en `strict=True`** — c'est-à-dire en
   passant réellement par `chaine.appliquer(strict=True, live={...})` ?
   Preuve : son journal du jour, pas une lecture du code.
2. **Le fichier de la journée de trading du 08/09 est-il en local**
   (`scp` depuis le VPS, fichiers nommés par journée de trading) ?
3. **L'entonnoir du jour contient-il des lignes L0 avec `TROU_VIX` sur les
   barres de nuit** (`vix_level == 0` → TROU, jamais un régime) ?

**Si l'une est non, c'est LA tâche, avant tout le reste.** Un premier jour de
campagne sans preuve qu'il a eu lieu est un jour perdu. Si les trois sont oui :
`python -X utf8 V3/pourquoi.py --journal <dernier>` puis
`python -X utf8 V3/layers/L0_interrupteur/test_portes.py`, et attaque le §3.1.

Si un point de ce prompt contredit le dépôt, **le dépôt a raison** ; corrige ce
fichier.
