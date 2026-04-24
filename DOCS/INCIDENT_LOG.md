# INCIDENT LOG — MIA Trading System

**USAGE** : ce fichier est lu par Claude au DEBUT de chaque session (nouvelle ou continuation apres `/compact`). Chaque incident documente ici doit guider Claude pour eviter sa repetition.

## Protocole de consultation

**AVANT toute action critique** (fix C++, dispatch agent, affirmation existence code/feature, design, deploy) :
1. Grep ce fichier pour la categorie concernee
2. Si match trouve, relire l'entree et appliquer la prevention
3. Si incident nouveau detecte : ajout immediat en haut du fichier (ordre anti-chronologique)

**Categories autorisees** :
- `CONTEXT_MISS` — non-consultation d'info disponible (memoire, rule, code existant)
- `PATTERN_11` — logique hardcoded au lieu de laisser ML apprendre (V1 reborn)
- `AGENT_MISUSE` — mauvais agent pour la tache OU agent non consulte quand requis
- `OVER_ENGINEERING` — solution trop complexe pour le probleme
- `VALIDATION_MISS` — affirmer sans preuve empirique
- `COMMENT_FALSE` — commentaire/doc dit X alors que realite = Y
- `SCOPE_CREEP` — depassement perimetre demande
- `DEPLOY_UNSAFE` — deploy sans confirmation/validation
- `LAZY_DELEGATION` — saute STEP 1-3 d'analyse manuelle, delegue tout aux agents (cf `.claude/rules/module-review-protocol.md`)

## Regles de maintenance

1. **JAMAIS supprimer** une entree (meme ancienne/resolue)
2. **Ordre anti-chronologique** : dernier incident en haut
3. **Une entree = 10 lignes max** (sinon linker vers fichier dedie)
4. **Escalation** : si une categorie atteint 3+ occurrences, promouvoir en memoire dediee auto-chargee
5. **Cross-reference** avec `.claude/rules/lessons.md` + memoires `feedback_*`

## Format d'entree

```
### YYYY-MM-DD HH:MM — [CATEGORIE] — Titre court

**Contexte** : 2 phrases max (tache + etat projet)
**Ce qui a mal tourne** : description factuelle
**Cause racine** : source manquee (memoire/rule/fichier non lu)
**Lecon** : regle imperative generalisee
**Trigger prevention** : signal concret pour detection future
**Reviewed** : Jackson / agent-name / self
```

---

## Incidents (anti-chronologique)

### 2026-04-25 00:30 — [VALIDATION_MISS + RESOLU] — Kill-switch paper_trader bug dormant (bouton STOP_BOT sans effet)

**Contexte** : Jackson demande ajout bouton "Relancer" au dashboard admin (il voulait pouvoir arreter/relancer le bot a distance en cas de news imminente). Audit preliminaire revele que le bouton "STOP BOT" existant ne fait RIEN depuis le depart : `STOP.flag` n'est lu que par `BOT/bot_main.py` (V1 legacy inactif) — pas par `CORE/mia_paper_trader.py` (bot paper actif).

**Ce qui a mal tourne** : infrastructure admin (endpoints `/api/bot/{stop,start}`, bouton UI dashboard, auto-show/hide selon `stop_flag_active`) deployee depuis session 09/04 SANS aucun test empirique bout-en-bout. Personne n'a jamais verifie qu'appuyer STOP_BOT → arrete effectivement le bot. Bouton REDEMARRER pareil (supprime un flag que personne ne lisait). Pattern `VALIDATION_MISS` identique aux V2-BIS risk.on_bar, reset_session, OCO_ORPHAN_DETECTED (code catalog sans emit).

**Cause racine** : confusion bot V1 (`BOT/bot_main.py` 275) vs bot V2 paper (`CORE/mia_paper_trader.py`). Le contrat "STOP.flag = kill-switch" etait documente pour V1, jamais porte a V2 apres migration paper. Les tests unitaires ne couvraient PAS le parcours complet `/api/bot/stop → flag → bot lit → flatten`.

**Lecon** : apres toute migration/refactor, **grep cross-codebase** pour verifier que les points d'integration (flag files, config, env vars) sont bien lus cote consumer actif en prod. Un fichier cree par producteur sans consumer = bug dormant.

**Fix 24/04 20:00-22:30** :
  1. `CORE/mia_paper_trader.py` : constante `STOP_FLAG_FILE`, `self._stop_flag_active` + `_stop_flag_activated_at`, bloc kill-switch dans `run()` avec retry flatten a chaque tick pause + alerte MAJEUR si pending > 30s (reserve #1 code-reviewer), expose `kill_switch` dans `_write_state()` (reserve #2).
  2. `CORE/log_catalog.py` : +`BOT_KILL_SWITCH_ACTIVATED` (MAJEUR) + `BOT_KILL_SWITCH_RELEASED` (INFO).
  3. `DASHBOARD/static/js/dashboard.js` ligne 5136 : `init()` passe `fetch()` brut → `fetchWithAuth()` pour auto-refresh JWT (fix bug dormant deco toutes 15min : aucun `POST /api/auth/refresh` dans logs historique).
  4. `DASHBOARD/static/sounds/*.wav` + UI sidebar sons (trade_open/tp/sl) avec mute + volume localStorage.

**Review code-reviewer** : GO-AVEC-RESERVES → 2 corrections appliquees (retry flatten + expose kill_switch state).

**Test empirique live VPS 14:25 UTC** :
  - STOP.flag cree → bot detecte en 12s → `[KILL_SWITCH] STOP.flag detecte -> flatten + pause` + `state.json kill_switch.active=true` ✓
  - STOP.flag supprime → bot detecte en 9s → `[KILL_SWITCH] STOP.flag supprime -> reprise trading` + `kill_switch.active=false` ✓

**Trigger prevention** : avant de commit une infra "fire-and-forget" (file flag, cache invalidation, env var), exiger un **test empirique bout-en-bout** documente dans le commit message. Le code-reviewer doit check : "le consumer de ce signal existe-t-il dans le code actif prod ?".

**Reviewed** : Jackson + code-reviewer

---

### 2026-04-24 23:45 — [CONTEXT_MISS + RESOLU] — Plan correction 3 findings audit market-analyst

**Contexte** : Audit impitoyable market-analyst apres 5 fixes en 3h (SLTP P1, SELL+Freshness, Bias gate, SL bornes, atr_14m). Revele 5 findings dont 3 actionnables cette nuit, 2 restants backlog.

**Finding #1 [CONTEXT_MISS] atr_14m non branche paper_trader** :
  Le fix schema 3.7.14 pour `atr_14m` + `VolatilitySpikeGate` est **inutile pour paper_trader actif**. VolatilitySpikeGate uniquement importe dans `BOT/bot_main.py` (legacy/futur). `mia_paper_trader.py` ne l'importe JAMAIS. **Cause** : biais "code correct = utile en prod" — je n'ai pas verifie la chaine d'usage end-to-end.
  **Decision** : Option (B) accepter que le fix sert uniquement pour futur bot live. Pas de branchement en paper_trader (scope creep). Le fix C++ reste valide techniquement pour consumers futurs.
  **Trigger prevention** : cf memory `feedback_pre_deploy_3_questions.md` — avant deploy fix, verifier qui consomme en boucle prod ACTIVE (pas qui importe le code).

**Finding #2 [RESOLU] Redondance bias STEP 6bis quasi-tautologique** :
  `conseil_global` lit `regime.bias` = `compute_bias(bar)` (builders.py:151). STEP 6bis rappelle `compute_bias(bar_row_dict)` sur meme input. Meme fonction, meme bar (dashboard/JSONL source), meme output 99%+ du temps. **Fix** : STEP 6bis gate supprime. Conserve uniquement :
    - Prereq `bar_dmp_missing` (bar DMP presente)
    - Soft-flag V2 log `bias_weak` pour observabilite
  Update FUNNEL_STEPS : `["bar_dmp_missing"]` (retire `bias_opposite_direction`, `bias_unclear`).
  Scoring conseil_global integre toujours bias comme 1/6 facteurs (poids 2/8) — non touche.

**Finding #4 [RESOLU] Kill-switch SELL asymetrique par instrument** :
  Avant : seuil DD hardcode 60t pour ES+NQ combined. NQ max_sl=80t → 1 SL plein peut declencher (trop agressif). ES max_sl=40t → 60t = 1.5 trades (jamais frein).
  Apres : compteurs DD/trades/disabled par SYMBOLE. Seuil = `max_sl_ticks[sym] * 1.5` :
    - NQ : DD > 120t (1.5 trades pleins max_sl 80)
    - ES : DD > 60t (1.5 trades pleins max_sl 40)
  Reset EOD par symbole dans `_rotate_day_if_needed`.

**Finding #3 [BACKLOG] P-hacking Lopez** : 5 fixes en 3h sans backtest empirique. A traiter demain avec simulation sur 1210 barres live 23/04 pour mesurer interaction reelle (SL bornes + T2 seul + freshness + SELL en combinaison).

**Finding #5 [BACKLOG] Payoff gate trivial + scoring ES=NQ** : dette architecturale pre-LightGBM. Post-30j data, scoring par instrument + meta-labeler ML.

**Review agent POST-plan** : GO-AVEC-RESERVES → 1 STEP 0 pre-code (grep compute_bias consumers + FUNNEL_REASONS + reset EOD kill-switch) effectue. 4 verifications OK.

**Tests** : 96/96 pytest passent post-fix.

**Fichiers modifies** : `CORE/mia_paper_trader.py` (FUNNEL_STEPS, STEP 6bis bloc, init + check + close_position SELL, _rotate_day_if_needed).

---

### 2026-04-24 22:00 — [RESOLU] — Fix ATR naming ambigu + VolatilitySpikeGate re-armee (schema 3.7.14)

**Contexte** : Audit ATR suite analyse 23/04. Feature `atr` dans JSONL = en fait `atr_daily` (lu chart DAILY, NQ ~437 ticks). Nom ambigu.
**Impact critique detecte** : `VolatilitySpikeGate` (BOT/bot_main.py:117) calcule `bar_range_ticks / atr_ticks`. Avec atr_daily ~437t, ratio toujours < 0.1 → gate spike JAMAIS declenchee → safety net cassee quand bot ira live.
**Fix** :
  - Nouveau champ C++ `atr_14m` (ATR 14-barres 1-min, True Range SMA, en ticks) calcule depuis chart BARRES (23/25) via `sc.GetChartArray(chart, SC_HIGH/LOW/LAST)`.
  - Schema 3.7.13 → **3.7.14**, 267 → 268 colonnes.
  - 5 fichiers C++ modifies (Reader/Transform/Writer/Config).
  - `CORE/volatility_gate.py` : priorite atr_14m, fallback atr_daily avec log WARN one-shot.
  - `CORE/dmp_validator.py` : EXPECTED_COLS_3714=268 + condition exclude mise a jour.
**Review code-reviewer initial** : NOGO (2 bugs) → fixes :
  1. `sc.GetChartArray(-chart_barres, ...)` avait signe negatif illegal ACSIL → retire.
  2. `dmp_validator.py` condition exclude n'incluait pas 268 → ajoute.
  3. Log WARN fallback atr_daily ajoute (pattern log-debug-protocol).
**Tests** : 96/96 pytest passent.
**Note** : pattern `arr[sz-1]` utilise (risque backfill v4) — blacklist v4 a noter.
**Trigger prevention** : avant tout nouveau champ ACSIL, verifier signature `sc.GetChartArray(ChartNumber, ...)` avec ChartNumber POSITIF. Le `-chart` n'est pas une convention SC valide.

---

### 2026-04-24 21:00 — [SCOPE_CREEP] — Re-activation SELL paper + freshness quick win

**Contexte** : Analyse 23/04 revele 0 trade pris (4026 polls → 3884 conseil_attendre 97%). Cause principale = patch 22/04 SELL DISABLED (builders.py:1329) qui forcait toutes les VENTE/VENTE PRUDENTE en ATTENDRE. Raison historique : audit market-analyst 22/04 PF SELL=0.00 ES (0/6 wins) + Jackson bust Topstep LIVE sur SELL news imprevue. Sur 23/04 NQ baisse 400pt + ES baisse 60pt → 50-70% des opportunites etaient SELL, toutes etouffees.

**Ce qui a change** :
  1. `builders.py:1329-1356` : retrait du forcage VENTE→ATTENDRE. SELL re-active paper uniquement.
  2. `mia_paper_trader.py:75-97 + check_entry` : freshness accepte `("NEW", "PERSISTENT")` au lieu de `"NEW"` seul. Deblocage 46 rejets freshness_not_new/jour.
  3. Kill-switch auto SELL ajoute (pas de boucle manuelle) : si DD_intraday_sell > 60 ticks OU (N>=20 trades ET WR < 25%) → `self._sell_disabled = True` → re-bloque VENTE automatiquement (reject code `sell_auto_disabled`).

**Justification vs pattern 11 V1** :
  - Base statistique 6 trades SELL (audit 22/04) = IC95% Jeffreys WR [0%, 46%] = decision inexploitable
  - Retirer un gate hardcode sur 6 obs = INVERSE du pattern 11 (pattern 11 = ajouter gates cascade apres loss)
  - Safety nets : Paper DTC Sim3 + gates bias/SLTP/payoff aval + kill-switch auto
  - TODO V2CLEAN : flag `ENABLE_SELL_PAPER=True` / `ENABLE_SELL_LIVE=False` dans config centrale

**Review code-reviewer** : GO-AVEC-RESERVES → 3 conditions traitees :
  - #1 entry_px = close courant (banner dashboard) ✅ verifie empiriquement
  - #2 kill-switch auto SELL ajoute ✅
  - #3 cette entree INCIDENT_LOG ✅

**Tests** : 93/93 pytest passent (dont 12 SLTP + 37 bias + 18 cross).

**Monitoring** : chaque fin de journee, review WR_sell_rolling + DD_intraday_sell. Review vendredi 25/04 sur N>=20 trades.

**Trigger prevention** : avant tout patch "DISABLE feature based on N<30 trades", exiger Bayesian IC95% dans la justification. Base stat < 30 = decision inexploitable.

---

### 2026-04-24 18:00 — [RESOLU] — Fix BUG#B+C DMP_ReadNearestExtensionLine max_dist filtre (schema 3.7.10)

**Contexte** : Audit diagnostique Jackson 24/04 afternoon identifie 11 bugs/ameliorations sur les 8 familles d'etudes SC lues par le DMP. Premier fix = BUG#B (NQ COLOR EL median -4531 ticks = -1133 points) + BUG#C (NQ EDGE EL outliers p99=1285t) — meme cause racine.
**Cause racine** : Doc officielle SC (ThreadID=57101) confirme "each recalculation duplicates the lineuntilfuture". Le reader `DMP_ReadNearestExtensionLine` scannait sans filtre de distance max → retournait lignes historiques stale (jamais intersectees apres Full Recalc). Pattern identique au fix delta_divergence 07/04 (meme famille Extension Lines).
**Fix applique 24/04 17:30-18:00** :
  - `DMP_Config.h` : +constante `DMP_MAX_EXT_LINE_DIST_TICKS = 500.0f` (= 125 points ES/NQ)
  - `DMP_Reader.h::DMP_ReadNearestExtensionLine` : filtre `if (d > max_dist_px) continue;` + signature tick_size obligatoire (pas de default pour eviter silent fallback)
  - 6 call sites passent `d.tick_size` explicite (pattern identique aux autres readers)
  - Schema 3.7.9 → 3.7.10 (comportemental, 267 cols inchanges)
**Review code-reviewer** : GO-AVEC-RESERVES → 2 corrections appliquees :
  1. MAX_DIST centralise dans Config.h (pas magic number Reader.h)
  2. Default tick_size retire (anti-pattern silent fallback)
  3+4 : backlog observabilite (counter filter declenche) + surveillance borne scan 50
**Validation empirique** (simulation post-fix sur 1034 barres NQ+ES existantes) :
  - NQ COLOR UP/DN : 100% filtered (-4531t aberrant eliminé) ✅
  - NQ EDGE BUY : p99 1285t → 70t (7.3% outliers filtres) ✅
  - NQ EDGE SELL : p99 1470t → 46t (10.9% outliers filtres) ✅
  - NQ LONG UP/DN : 0% filtered (p99 403-419t legitimes preserves) ✅
  - ES LONG + EDGE : 0% filtered (valeurs deja propres) ✅
**Deploy** : en attente confirmation Jackson (SCP ACS_Source + DUMPER + recompile SC).
**Trigger prevention** : Avant tout reader Extension Lines, toujours ajouter filtre max_dist centralise Config.h. Gotcha SC officiel — pas de bug a chercher dans le reader.

---

### 2026-04-24 10:53 — [CONTEXT_MISS] — Start-ScheduledTask MIA_PaperTrader cree doublon process avec service nssm MIA-Paper

**Contexte** : deploy regime GEX sur paper_trader VPS. Apres kill PID 3260, j'ai fait `Start-ScheduledTask -TaskName MIA_PaperTrader` pensant que la scheduled task etait le mecanisme de persistance.
**Ce qui a mal tourne** : 2 python.exe ont demarre en parallele = race condition sur state.json + 2 connexions DTC Sim3 potentielles. PID 7068 (cmd `-u -X utf8`) lance par le SERVICE nssm `MIA-Paper` (auto-restart apres kill 3260) + PID 11844 lance par ma scheduled task via .bat. Detecte 2 min plus tard au loop suivant.
**Cause racine** : j'ai checke `Get-ScheduledTask` mais pas `Get-Service` avant de restart. Memory `reference_nssm_dashboard.md` mentionnait nssm pour Dashboard — j'aurais du presumer qu'il existait peut-etre aussi un service nssm pour paper_trader.
**Lecon** : avant tout restart d'un process persistant VPS (dashboard, paper_trader, V2CLEAN), v�rifier **LES DEUX** mecanismes : `Get-Service | Where Name -like '*MIA*'` ET `Get-ScheduledTask | Where TaskName -like '*MIA*'`. Si 2 mecanismes existent, ne lancer QU'UN seul.
**Trigger prevention** : avant `Start-ScheduledTask` ou equivalent, run `Get-Service MIA-*` pour detecter les services nssm qui auto-restart deja.
**Reviewed** : self (detecte au loop suivant via ps double). A documenter avec Jackson : probable doublon historique (scheduled task + service) a desactiver un des deux.

---

### 2026-04-24 14:10 — [RESOLU] — Fix dist_mq_hvl_0dte deploye + valide empiriquement

**Contexte** : Bug decouvert matin 24/04 (cf entree precedente) — le HVL 0DTE visible chart Jackson etait AVEUGLE au bot car DMP_Transform n'exposait pas `dist_mq_hvl_0dte` comme feature JSONL (seulement comme fallback pour Call/Put 0DTE superposes). Cas niveaux distincts observe empiriquement 23/04.
**Fix applique 24/04 13:50-14:10** :
  - Schema 3.7.8 → **3.7.9** (266 → **267 colonnes**)
  - +1 feature `dist_mq_hvl_0dte` exposee explicitement
  - +check dans CalcDataQuality (bool_near_level inclut desormais les 3 niveaux 0DTE)
  - +patch dmp_validator.py (EXPECTED_COLS_379=267 + branche detection)
**Audit pre-deploy** : code-reviewer HOLD → 2 correctifs (dmp_validator + CalcDataQuality check) → GO.
**Deploy** : SCP ACS_Source + DUMPER backup (coherent 2 dossiers). Jackson recompile SC 14:05 UTC.
**Validation empirique 14:10 UTC** : barre post-recompile (prix 27064.50, UTC 12:08) :
  - `dist_mq_hvl_0dte = -558t` → niveau absolu 27064.50 - 139.50 = **26925.00**
  - Match EXACT avec HVL 0DTE visuel chart Jackson (label "HVL ODTE" a 26925)
  - Call 0DTE +342t → 27150 ✅, Put 0DTE -1458t → 26700 ✅ (cas distinct confirme)
**Lecon** : le protocol critical-tasks-review fonctionne. Audit agent pre-deploy a rattrape 2 bugs (validator bloquant + check oublie). Temps total bug → fix valide : **4h** (decouverte 10:30 → validation 14:10). Plus court que l'estimation Option 2 (1 jour) grace a scope ultra-minimal (3 lignes C++ + 7 lignes support).
**Trigger prevention** : Toujours verifier quand une feature LIVE dans le code (ici `r.mq_hvl_0dte` lu depuis 31/03) sans etre exposee dans le JSONL. Grep `f.X = ` pour toute variable `r.X` lue → si absent = feature silencieusement abandonnee cote consommateurs.
**Reviewed** : code-reviewer agent (pre-deploy) + Jackson (validation empirique visuelle).

---

### 2026-04-24 13:40 — [CONTEXT_MISS] — 4 affirmations erronees consecutives sur screenshots / niveaux MenthorQ

**Contexte** : Session matinale Q&R edge Jackson. J'ai affirme consecutivement plusieurs choses non verifiees :
1. "Le chart SC affiche en UTC" alors que j'avais 3 hypotheses possibles — verifie apres (valide)
2. "Les niveaux MenthorQ sont stale (Levels Timestamp 22/04)" alors que le screenshot affichait 2026-04-23 et je lisais mal la zone floue
3. "`dist_mq_*` aberrants" alors que distinction `_0dte` (sg5-7) vs generique (sg0-2) n'avait pas ete comprise
4. "BUG LONG UP=DOWN identiques" alors que Jackson avait copy-paste rate
**Ce qui a mal tourne** : 4 CONTEXT_MISS dans la meme session. Chaque fois j'ai affirme un fait (potentiellement un bug) sans verifier empiriquement AVANT. Jackson a du me corriger explicitement chaque fois.
**Cause racine** : Mode "analyse rapide" active sur des screenshots pas clairs → lecture approximative → affirmation premature. Regle `feedback_context_miss.md` existait deja depuis 20/04 mais pas respectee.
**Lecon** : Sur un **screenshot peu clair** (zoom pixelise, superposition legend), **demander zoom ou confirmation** au lieu d'affirmer. Sur une **valeur numerique aberrante** (ex dist_mq_hvl -3070t), **verifier la convention code AVANT** d'affirmer qu'elle est bugguee. Sur une **entree utilisateur incoherente avec empirique**, demander re-dump.
**Trigger prevention** : Si je vais affirmer un fait base sur un screenshot → prendre 5s pour auto-question "ai-je zoom-lu le screenshot proprement ? ai-je une hypothese alternative ?". Si non, demander. **Categorie CONTEXT_MISS atteint largement 3+ aujourd'hui (24/04) : promouvoir memoire dediee.**
**Fix applique** : Memoire `reference_timezone_convention.md` creee avec convention MQ_GAMMA subgraphs + warning mea culpa. MEMORY.md pointeur ajoute.
**Reviewed** : Jackson (corrections explicites). Pattern 11 evite de justesse sur les 4 occurrences (pas de code ecrit/deploye avant correction).

---

### 2026-04-24 10:30 — [VALIDATION_MISS] — Affirmé BUG LONG UP=DOWN sans verifier copy-paste Jackson

**Contexte** : Q&R Phase 0 sur formules Alert Conditions LONG BAR. Jackson m'a dumpe formules, j'ai constate que UP ES/NQ et DOWN ES/NQ avaient la meme Alert Condition (`=AND(O>C[-1], H>L[-1]+TICKSIZE*N)`).
**Ce qui a mal tourne** : J'ai affirme un "BUG 1 MAJEUR" en rouge dans le MANUEL et la reponse Jackson, supposant que les 2 etudes fonctionnaient sur le meme Alert Condition + differenciation via Inputs. En realite, Jackson avait fait un copy-paste raté dans son dump (meme formule UP pour les 4 lignes UP/DOWN ES/NQ).
**Cause racine** : Quand Jackson a redumpe correctement, la vraie formule NQ LONG DOWN BAR etait `=AND(O<C[-1], H[-1]>L+TICKSIZE*40)` — miroir bearish exact. Les fire rates differents (UP 0.5% ES vs DOWN 1.4% ES, UP 9.9% NQ vs DOWN 11.6% NQ) **auraient du me mettre la puce a l'oreille** : si les formules etaient identiques, les fire rates devraient etre egaux. J'ai pris l'incoherence pour un mystere ("inputs direction ?") au lieu de demander confirmation a Jackson.
**Lecon** : **Quand une entree utilisateur est incoherente avec un fait empirique observe**, demander confirmation AVANT d'affirmer un bug. Regle : si fire_rate_UP != fire_rate_DOWN mais formules semblent identiques, hypothese n°1 = "copy-paste rate utilisateur", hypothese n°2 = "differenciation via Inputs". Demander re-dump avant de creer un flag rouge dans la doc.
**Trigger prevention** : Lors de dump de formules / configs par utilisateur, si 2 entites conceptuellement differentes (UP/DOWN, BUY/SELL, LONG/SHORT) ont une config LITERALEMENT identique, c'est un signal d'alerte copy-paste. **Demander explicitement** "tu es sur que X et Y ont exactement la meme formule ?" avant de propager dans la doc.
**Fix applique** : MANUEL_EDGE_JACKSON.md §4.1 corrige avec vraies formules miroir. BUG 1 retire. Note historique ajoutee.
**Reviewed** : self-detection quand Jackson a re-dumpe correctement apres ma reponse. Aucun dommage dans le code (rien de deploye sur ce finding, uniquement doc).

---

### 2026-04-24 02:40 — [CONTEXT_MISS] — Fix C++ NQ_FP EDGE swap inoperant (2 traces manquees)

**Contexte** : Saturation `bar_edge_buy/sell` NQ 74% persiste malgre fix chart 14 matin 23/04 (entree 22:55 ci-dessous). J'ai propose un swap IDs dans `DMP_Reader.h::NQ_FP` : `EDGE_BUY=55↔4` et `EDGE_SELL=56↔2` pour pointer vers natives chart 2 avec `Percentage=1000` (fix Jackson). Deploye sur VPS (SCP) avant recompile DLL.
**Ce qui a mal tourne** : Review agent POST-DEPLOY a identifie 2 problemes bloquants :
  1. `DMP_Transform.h:1257` fait `fp_edge_buy = OR(fp_edge_buy, fp_edge_buy_2)` — l'overlay sature en `EDGE_BUY_2=55` va contaminer le OR → fix neutralise pour `fp_edge_*`.
  2. `bar_edge_buy/sell` NE LIT PAS `NQ_FP` mais `NQ_BARRES` (chart 23 ID 40/16). Mon swap sur `NQ_FP` (chart 2) n'affecte pas les features saturees observees.
Resultat : recompile aurait donne **ZERO changement observable** sur les 4 features cibles. Code mort + piege prochaine session.
**Cause racine** : J'ai propose le fix sans tracer end-to-end la feature `bar_edge_buy` dans le pipeline. Grep `DMP_Studies::NQ_FP::EDGE_BUY` fait, mais grep `bar_edge_buy\s*=` (source de la feature saturee observee) non fait. Confiance excessive sur le grep fp_edge_* qui renvoyait NQ_FP, ignorant que bar_edge_* passe par un autre namespace.
**Lecon** : **Avant tout swap d'ID C++, tracer la feature JSONL observee (celle qui a un comportement anormal) bout-en-bout**. Etapes minimales : (1) grep le nom exact de la feature dans le JSONL (ex: `bar_edge_buy`) dans tout le code C++ pour trouver l'assignation `d.X =`, (2) identifier le namespace/chart utilise, (3) vérifier toute cascade OR/AND dans Transform qui pourrait contaminer, (4) SEULEMENT APRÈS proposer le fix.
**Trigger prevention** : Si je propose un fix C++ sur une feature observee anormale, je dois lister dans ma proposition : (a) nom exact de la feature, (b) file:line de l'assignation directe, (c) file:line de toute cascade Transform qui la derive. Si je ne peux pas le faire de memoire, je grep avant de proposer.
**Fix applique** : Rollback complet du swap (IDs 55/56/4/2 restored a l'original) sur local + VPS. Aucune recompile DLL effectuee. Collecte continue avec saturation NQ jusqu'au vrai fix demain.
**Reviewed** : code-reviewer agent (2 reviews cross-check) + self-detection sur re-verification `bar_edge_buy\s*=`. Vraie source : `NQ_BARRES::EDGE_BUY=40` chart 23, Percentage Threshold inconnu (chart 23 non dumpe, le dump JSON ne contient pas les Input Parameters).

---

### 2026-04-23 22:55 — [VALIDATION_MISS] — Saturation bar_edge_buy/sell NQ 75% non detectee avant audit

**Contexte** : Audit empirique ML-readiness des features footprint a revele que `bar_edge_buy/sell` NQ fire 75% vs 15% ES (cassure symetrie ES/NQ). Features prohibitees training ML depuis avril mais pas questionnees.
**Ce qui a mal tourne** : Config Sierra Chart heritage V1 faisait pointer NQ_FOOTPRINT.EDGE_BUY=55 (chart 2) et NQ_BARRES.EDGE_BUY=32 (chart 23) vers des overlays copiant l'etude source chart 14 ID:1 `EDGE ZONES IMBALANCE BUY 0DIAG` avec `Percentage Threshold=1000` (permissif). Cote ES, configuration pointait vers des etudes avec Threshold=600 (strict). Resultat : saturation NQ 75% fire + BOTH simultane 64% = feature non-discriminante, training ML aveugle.
**Cause racine** : Legacy "A/B tests tick reversal" (Jackson V1 perso) avec plusieurs versions d'etudes EDGE ZONES (rev1 800%, rev2 800%, rev3 800%, 600%DIAG, rev8 0DIAG, 0DIAG) laisse dans le chartbook. Le DMP C++ lit via `study_mapping.json` hardcoded aligned sur IDs non-optimaux. Jamais audite empiriquement avant 23/04.
**Lecon** : **Features binaires avec fire_rate > 60% ET BOTH_simultane > 30% sont cassees par definition**. Planifier audit empirique periodique de la symetrie des features binaires entre symbols (ES vs NQ ES devraient avoir fire_rate comparables pour meme feature). Memory `feedback_es_nq_mirror.md` application empirique stricte.
**Trigger prevention** : Script `CORE/research/audit_footprint_efficiency_*.py` + `CORE/research/quick_check_bar_edge_post_fix.py` integres dans pipeline nightly. Alerte si abs(fire_ES - fire_NQ) > 30% sur une feature binaire.
**Fix applique** : Jackson a modifie chart 14 Rev 8t ID:1 et ID:2 : Percentage Threshold 1000→600 (BUY) / -1000→-600 (SELL). Les overlays chart 2 ID:55/56 et chart 23 ID:32/33 heritent automatiquement via `Study to Overlay = #14.ID1/ID2` + `Data Copy Mode = Use Latest Value from Chart`. Validation empirique sur 9 barres post-fix NQ : BOTH tombe de 52% → 22%, XOR de 15% → 44%. Sur 4 dernieres barres consecutives : 0 BOTH, 2 XOR, 2 NEITHER — convergence complete vers comportement ES.
**Reviewed** : Jackson (decouverte + fix SC) + empirique (46 barres NQ 23/04 analysees). Commit associé non necessaire (config SC uniquement, aucun code touche).

### 2026-04-22 21:15 — [CONTEXT_MISS] — Propose RTH-only a Jackson malgre decision 21/04 = 24h

**Contexte** : Jackson demande "rassure-moi le bot trade toutes les sessions". Je propose 3 options dont Option A = "ajouter gate US RTH". Jackson me reprend "IL DOIS TRADER TOUT LES SESSION".
**Ce qui a mal tourne** : J'ai cite memory `project_v2clean_multi_session` version 19/04 ("US RTH only pour demarrage") sans voir que le meme fichier ETAIT deja update 21/04 avec "Jackson tranche = 24h, NE PAS re-suggerer RTH-only sans signal empirique contrariant". Le fichier avait un tableau historique explicite + une section "Anti-pattern a eviter : NE PAS re-suggerer RTH-only".
**Cause racine** : j'ai read les 2 premieres lignes de memory (description type 2-3 phrases) puis ai synthetise sans lire la section "Anti-pattern" en fin. Memory auto-chargee dans MEMORY.md indexe la description, pas le corps detaille.
**Lecon** : **Quand memory cite une DECISION Jackson (avec date + "tranche" / "confirme"), lire le fichier ENTIER avant de proposer action contradictoire.** Les sections "Anti-pattern a eviter" et "Historique decisions" existent precisement pour ca.
**Trigger prevention** : avant de proposer une reco technique sur V2CLEAN/paper_trader/V2-bis, grep memory pour "NE PAS" + "tranche" + "Jackson confirme" sur le sujet.
**Reviewed** : Jackson (correction directe "IL DOIS TRADER TOUT LES SESSION ON ES PAPER"). Fix applique : memory updated 22/04 re-confirmation paper=24h (argument : collecte donnees). Pas de code change necessaire (bot deja sans filtre session).

### 2026-04-22 XX:XX — [VALIDATION_MISS] — Migration order_manager.py missed OCO_ORPHAN_DETECTED emit

**Contexte** : migration BOT/order_manager.py vers systeme logs V2 (5 emits ajoutes). Review code-reviewer post-commit a detecte gap critique.
**Ce qui a mal tourne** : le log `OCO_ORPHAN_DETECTED` n'etait PAS emis. Pourtant ce scenario est EXACTEMENT le bug DNA V1 (02/04) qui a motive tout l'OCO manuel. Sans ce log, un orphan en prod serait invisible — position ghost avec SL actif = risque perte non-trackee.
**Cause racine** : j'ai migre les emits "happy path" (submit/fill/cancel) mais pas les "failure modes" (orphan = cancel echoue). Pattern inverse du VALIDATION_MISS 22/04 precedent (`risk.on_bar` methode definie mais pas cablee dans dispatcher) — cette fois code defini dans catalog mais pas emis dans code reel.
**Lecon** : **Apres migration logging, verifier que TOUS les codes catalog pertinents au fichier sont effectivement emis**. Grep cross-reference : `codes definis pour categorie X` vs `codes emis dans fichiers de categorie X`.
**Trigger prevention** : script check `catalog_coverage.py` qui grep LOG_CODES["X_CATEGORY_*"] vs "emit(\"X_" dans codebase, flag missing.
**Reviewed** : code-reviewer BOT/order_manager (22/04) — 3 actions correctives identifiees. Fix applique : emit ajoute dans `_verify_cancel` (dtc_connector.py L566). Note : detection orphan REEL (via Open Orders Request Type 300) reportee P3 — actuellement emit ALERTE indicatif.

### 2026-04-22 XX:XX — [COMMENT_FALSE] — V2_StatePersistence header cite code Python inexistant

**Contexte** : review STEP 4 Tier 2 V2_StatePersistence.h par agent code-reviewer. Le header L6-7 disait "Port Python : risk_manager.py:545-564 (_write_snapshot_atomic, 20 LOC) + logique restore + backup".
**Ce qui a mal tourne** : l'agent a grep `BOT/risk_manager.py` pour verifier → **0 match pour `_write_snapshot_atomic`**. La reference etait inventee ou periumee. C'est exactement le pattern COMMENT_FALSE du 20/04 (chiffres LOC non-verifies empiriquement, section 4.6 cite ligne qui n'existe pas dans file Python).
**Cause racine** : au moment ou j'ai ecrit le stub V2_StatePersistence.h (session precedente), j'ai probablement copie une reference d'un autre stub ou l'ai inventee sans grep. **Pattern 2eme occurrence memoire COMMENT_FALSE depuis 20/04**.
**Lecon** : **AUCUNE reference file:line citee dans un header ou doc DOIT passer sans grep de verification empirique.** Meme pour les references "port de Python".
**Trigger prevention** : quand header C++ mentionne "port Python <file>:<lines>" → grep exact `grep -n "symbol" <file>` AVANT commit. Si 0 match = reference fausse, corriger ou retirer.
**Reviewed** : code-reviewer Tier 2 V2_StatePersistence (22/04) detecte. Correction appliquee : header reformule "ref exacte a confirmer P1".

### 2026-04-22 XX:XX — [VALIDATION_MISS] — `risk.on_bar()` defini mais jamais appele dispatcher

**Contexte** : session V2-BIS 22/04 review 4 modules Tier 1 (V2_Main, V2_OrderExec, V2_RiskManager, V2_HealthCheck, V2_SessionGuard). 8 agents reviews individuels ont approuve chaque module.
**Ce qui a mal tourne** : V2_RiskManager.h ligne 64-72 definit `on_bar(double mtm_pnl_usd)` avec commentaire "CRITIQUE : update peak + check_intraday_dd (sinon INTRADAY_DD trop tard)". MAIS `V2_Main.cpp on_bar_close_dispatcher` ne l'appelait JAMAIS. Methode = **dead code de bonne intention**. Classic : methode definie + test reference (peak_drop_intraday_dd) + impl P1 existera, mais cablage dispatcher manque → INTRADAY_DD ne peut PAS trigger pendant trade ouvert.
**Cause racine** : les 8 agents reviews individuels valident CHAQUE module en silo, sans tracer le flow cross-module. La review SYNTHESE GLOBALE (validateur tiers, 9eme agent) a detecte via grep multi-fichiers "qui appelle risk.on_bar ?" → vide.
**Lecon** : **Apres batch de reviews individuels modules, OBLIGATION dispatcher 1 agent SYNTHESE** qui valide :
  1. Chaque methode publique definie est appelee quelque part
  2. Chaque interface ajoutee est implementee ET injectee
  3. Chaque test cible a son cablage dispatcher
**Trigger prevention** : module-review-protocol.md STEP 5 Tier 1 → ajouter STEP 5b "synthesis review global" apres tous modules batches. Validator agent au lieu de 2 cross-checks individuels.
**Reviewed** : code-reviewer synthesis (22/04) detecte C1+C2, fix applique immediatement V2_Main.cpp.

### 2026-04-22 XX:XX — [CONTEXT_MISS] — Proposition doublon EventType::ORDER_ERROR

**Contexte** : application reco Plan V2_HealthCheck STEP 5 Q4 failure modes. Ajout 4 nouveaux EventType dans V2_Types.h enum (V2CLEAN_HEARTBEAT_MISSING, V2CLEAN_CLOCK_SKEW, HEARTBEAT_IO_ERROR, ORDER_ERROR).
**Ce qui a mal tourne** : `ORDER_ERROR` existait deja ligne 182 de V2_Types.h. J'ai ajoute un doublon ligne 193. Grep immediat apres ajout a detecte. Suppression dans la foulee.
**Cause racine** : j'ai lu la fin de l'enum (L167-170) pour positionner mes ajouts, mais pas grep exhaustivement avant. Le trigger prevention ajoute le 22/04 XX:XX (incident precedent KILL_SWITCH_TRIGGERED) etait precisement cette regle — mais applique au moment ADD, pas a l'ADD suivant quelques minutes plus tard.
**Lecon** : **Quand bundle plusieurs ajouts a un enum dans une meme edition, grep CHAQUE nouveau nom individuellement**, pas seulement le premier.
**Trigger prevention** : batch add enum = boucle `for each new_val: grep -n "new_val\b" file`.
**Reviewed** : self (detecte par grep immediat post-edit).

### 2026-04-22 XX:XX — [CONTEXT_MISS] — Proposition doublon EventType::KILL_SWITCH_TRIGGERED

**Contexte** : review V2_Main.cpp STEP 1 walk-through Gap #5 (spam journal kill-switch). Je propose d'ajouter `EventType::KILL_SWITCH_TRIGGERED` comme nouvelle entree enum.
**Ce qui a mal tourne** : `EventType::KILL_SWITCH_TRIGGER` (au singulier, sans D final) existe deja `V2_Types.h:154`. Mon design aurait cree doublon evitable. Code-reviewer a detecte l'angle mort lors STEP 4.
**Cause racine** : j'ai suivi STEP 1 (walk-through) et STEP 2 (grep design doc) MAIS pas STEP complementaire critique : grep EXHAUSTIF de l'enum EventType pour savoir ce qui existe deja. Mon grep STEP 2 a cible "V2_Main / dispatcher / chain.of.gates" sans verifier `V2_Types.h`.
**Lecon** : **Avant proposer AJOUT a un enum/struct C++, grep le type dans V2_Types.h (ou equivalent header types) pour lister les entrees existantes**. Specialement quand le design parle de "journal event X" ou "new enum value".
**Trigger prevention** : quand design proposition contient "ajouter EventType::X" ou "ajouter enum value", faire grep `grep -n "X\|equivalent\|similar" V2_Types.h` AVANT de valider le design.
**Reviewed** : code-reviewer (agent market-analyst agent_a2a08927c03d2bfd6 section "Angle mort detecte").

### 2026-04-21 16:XX — [LAZY_DELEGATION] — V2_JSONLBridge review sans STEP 1-3 manuel

**Contexte** : walkthrough stubs V2-bis module par module. Module 2/13 V2_JSONLBridge.h.
**Ce qui a mal tourne** : j'ai directement dispatche code-reviewer sans walk-through scenarios reels ni grep design doc. Code-reviewer a rendu 10 recommandations dont R2 (ajouter `is_v2clean_zombie()` a ISignalSource) qui viole SRP. Si applique directement, j'aurais pollue l'interface.
**Cause racine** : paresse methodologique - deleguer tout aux agents au lieu de faire STEP 1-3 manuel d'abord.
**Lecon** : **Avant dispatch agent sur module, appliquer STEP 1-3 du `module-review-protocol.md`** (walk-through scenarios + grep doc + 2 tests stubs). ~60% des issues sont detectables manuellement.
**Trigger prevention** : avant `Agent` tool sur module V2-bis, grep `.claude/rules/module-review-protocol.md` + appliquer STEPS.
**Reviewed** : Plan agent (cross-check) a detecte R2 faux positif + R11 trou additionnel.

### 2026-04-21 14:XX — [CONTEXT_MISS] — Ajout feature absolue violant data-quality.md

**Contexte** : Jackson demande derivation `mq_gamma_condition` dans `menthorq_backfill_injector.py`.
**Ce qui a mal tourne** : ajout initial de 6 features dont `mq_net_gex` (113M ES) + `mq_total_gex` (485M ES). Valeurs absolues non-normalisees, incomparables ES/NQ (ratio 25x+). Violation directe `data-quality.md` regle souveraine "NE JAMAIS stocker d'absolus de prix/volume".
**Cause racine** : n'ai pas consulte `.claude/rules/data-quality.md` AVANT d'ecrire code. Memoire `feedback_data_quality_first.md` est auto-chargee mais j'ai ajoute quand meme feature absolue.
**Lecon** : **Avant d'ajouter feature numerique ML, verifier mentalement : ES vs NQ comparable ? Si non (dollars/volumes absolus), normaliser par ratio ou drop**.
**Trigger prevention** : si je m'apprete a ecrire `result["mq_<quelque_chose>"] = _parse_suffix_number(...)` ou valeur $M/$B → **stop**, normaliser d'abord.
**Reviewed** : code-reviewer (attrape via protocol critical-tasks-review). Correction : DROP `mq_net_gex`/`mq_total_gex`, ADD `mq_net_gex_norm = net/total` (ratio). Temps perdu : 10 min.

### 2026-04-20 21:XX — [AGENT_MISUSE] — 3 agents dispatch mal adaptes pour JSONL multi-barres

**Contexte** : Jackson demande audit exhaustif 266 features multi-barres. J'ai dispatche quality-auditor + schema-auditor + code-reviewer + market-analyst.
**Ce qui a mal tourne** : quality-auditor est specialise **parquet V2** (5 criteres fuite/vol/outlier/constant), pas JSONL temporel multi-barres. code-reviewer generique pas arme pour VIX/open_type specifiques.
**Cause racine** : dispatche sans verifier `.claude/agents/*.md` definitions vs exigences de la tache. Plan agent l'a detecte au round suivant.
**Lecon** : **VERIFIER la definition de chaque agent AVANT dispatch** quand la tache differe du use-case standard.
**Trigger prevention** : si tache = nouvelle modalite (JSONL vs parquet, multi-barres vs snapshot), grep `.claude/agents/*.md` avant Agent dispatch.
**Reviewed** : Plan agent

### 2026-04-20 20:XX — [SCOPE_CREEP] — Proposition 2 agents a creer inutile

**Contexte** : Plan agent suggere `feature-distribution-auditor` + `audit-coordinator` comme solution ideale. J'ai presente a Jackson comme necessaire.
**Ce qui a mal tourne** : creer 2 agents = 2 fichiers .md + 2 prompts + maintenance pour UN audit ponctuel.
**Cause racine** : acceptation aveugle recommandation Plan agent sans pragmatic filter. Jackson a dit "on peut utiliser existants".
**Lecon** : **Avant de creer un nouvel agent, epuiser les possibilites de re-brief des agents existants**.
**Trigger prevention** : si ma solution necessite creer infra (agent/rule/script), d'abord demander "peut-on y arriver avec l'existant + prompt plus precis ?".
**Reviewed** : self (Jackson pragmatique l'a implicitement valide)

### 2026-04-20 19:XX — [VALIDATION_MISS] — Fix C++ deploy sans verifier ib_recalc.py Python

**Contexte** : Fix C++ DMP_Transform.h:848 pour bug IB position_pct. Deploy propose apres 1 round code-reviewer GO.
**Ce qui a mal tourne** : code-reviewer 2e round (audit complet) a trouve que `CORE/ib_recalc.py:195-201` **recalcule** `ib_position_pct` sans guard `ib_complete`. Le fix C++ serait annule cote pipeline ML. 17083/17083 barres polluees confirmees empiriquement.
**Cause racine** : n'ai pas mappe toutes les surfaces d'ecriture de la feature avant de fixer. C++ seul = insuffisant.
**Lecon** : **Avant tout fix feature, grep TOUT le pipeline** (C++ ET Python) pour tous les points d'ecriture/recalcul de cette feature.
**Trigger prevention** : fix C++ sur feature F → grep `F` sur CORE/*.py + BOT/*.py + V2CLEAN/*.py avant deploy.
**Reviewed** : code-reviewer (RESERVE #1 CRITIQUE)

### 2026-04-20 18:XX — [VALIDATION_MISS] — V2-bis design v1.4 : 10 reserves declare appliquees, 5 residus

**Contexte** : 4e review Plan agent sur design V2-bis. J'annonce 10 corrections appliquees → bump v1.4.
**Ce qui a mal tourne** : Plan agent re-audit v1.4 detecte 5 residus (78 tests vs 79 dans 4 endroits, "717 LOC" vs 716, refs cross brisees, timeline 7.5-8.5 vs 6 sem, v1.3 vs v1.4 tags).
**Cause racine** : correction faite dans une section mais pas propagee aux autres sections qui citent la meme valeur. Discipline editoriale de propagation faiblarde.
**Lecon** : **Apres chaque correction numerique/textuelle, grep le chiffre/texte AVANT et APRES correction dans tout le fichier**.
**Trigger prevention** : si Edit change "X" en "Y" → grep "X" dans meme fichier → fix toutes autres occurrences.
**Reviewed** : Plan agent

### 2026-04-20 16:XX — [CONTEXT_MISS] — Audit single_print_mid flagge comme bug alors que deja PROHIBITED

**Contexte** : Audit multi-barres 266 features. market-analyst flagge `single_print_mid` + `profile_hvn_dominant` = prix absolus → violation data-quality.md.
**Ce qui a mal tourne** : ces 2 features sont **deja dans `dataset_builder.py:185 PROHIBITED_FEATURES`** depuis longtemps. Drop auto au niveau parquet. Pas un "bug actif".
**Cause racine** : brief agent sans lui donner le contenu PROHIBITED_FEATURES. Agent a flagge ce qui etait deja gere.
**Lecon** : **Avant audit features, briefer l'agent avec la liste des features deja droppees/exemptees** pour eviter faux positifs.
**Trigger prevention** : audit qualite features → include `PROHIBITED_FEATURES` + `EXEMPT_FEATURES` dans brief.
**Reviewed** : self (investigation empirique post-audit)

### 2026-04-20 16:XX — [CONTEXT_MISS] — Collinearite 4 features signalee, deja documentee

**Contexte** : Audit detecte `ask_bid_imbalance = delta_pct = buy_sell_ratio = ask_pct` collineaires corr=1.0.
**Ce qui a mal tourne** : `dataset_builder.py:412` documente deja ces 3 redondances avec commentaire explicite `# ask_pct == buy_sell_ratio, delta_pct == ask_bid_imbalance` et drop auto.
**Cause racine** : pas lu dataset_builder.py avant de dispatcher audit. Aurait evite faux positif.
**Lecon** : **Quand audit ML features, lire d'abord dataset_builder.py PROHIBITED + commentaires explicatifs**.
**Trigger prevention** : tache = "audit features X" → Read `CORE/dataset_builder.py` PROHIBITED_FEATURES section AVANT tout.
**Reviewed** : self

### 2026-04-20 15:XX — [CONTEXT_MISS] — Convention DMP dist mal codee dans Phase 0

**Contexte** : Script audit_phase0.py, check derivation `bool_above_X == (dist_X > 0)`.
**Ce qui a mal tourne** : 7 faux positifs sur ES + 7 sur NQ (99-100% barres). La convention reelle = `bool_above_X == (dist_X < 0)` (DMP_Transform.h:531 `PosInRange`).
**Cause racine** : ecrit le check sans lire la formule C++ source. Intuition naturelle "dist > 0 = above" inversee dans DMP.
**Lecon** : **Pour coder un check sur feature DMP, TOUJOURS lire la formule C++ source avant d'affirmer la semantique**.
**Trigger prevention** : avant ecrire `check(feature_X)` → Read `CPP/.../DMP_Transform.h` section qui calcule X.
**Reviewed** : self (empirique : `price=26684, dist_cur_vpoc=-3, bool_above=1` a revele la convention)

### 2026-04-20 13:XX — [COMMENT_FALSE] — "60 LOC critiques lignes 545-564" reel = 20 LOC

**Contexte** : Design V2-bis P0 section V2_StatePersistence, justifie port Python.
**Ce qui a mal tourne** : j'ai ecrit "20 LOC critiques" puis Plan agent a corrige, j'ai revise en "60 LOC" ... faux aussi. Realite = `_write_snapshot_atomic` est 20 lignes exactes (545-564).
**Cause racine** : repete chiffre de Plan agent review sans verifier empiriquement. Plan agent lui-meme avait donne chiffre faux.
**Lecon** : **Tout chiffre cite (LOC, %, count) DOIT etre verifie empiriquement par Read/Grep avant ecriture dans doc**.
**Trigger prevention** : si je m'apprete a ecrire "N LOC", "X%", "K tests" → verifier avec Bash/Read avant.
**Reviewed** : code-reviewer

---

## Statistiques par categorie (auto-update si manuel)

| Categorie | Occurrences | Promoted en memoire ? |
|---|---|---|
| CONTEXT_MISS | **6** | **OUI** `feedback_context_miss.md` (deja promu, renforce 22/04 avec trigger "grep enum existant" + "batch add = grep chaque nouveau nom") |
| VALIDATION_MISS | **4** | **OUI** (4+ occurrences) — promu `feedback_validation_miss_patterns.md` : synthesis review obligatoire + catalog_coverage apres migration |
| AGENT_MISUSE | 1 | **OUI preventivement** `feedback_agent_brief_verify.md` |
| SCOPE_CREEP | 1 | Pas encore |
| COMMENT_FALSE | **2** | Pas encore (seuil 3+) — trigger nouveau 22/04 : "grep empirique toute reference file:line header" |
| **LAZY_DELEGATION** | **1** | **OUI preventivement** `.claude/rules/module-review-protocol.md` (6 STEPS) |

**Escalation auto** : quand categorie = 3+ → creer memoire dediee auto-chargee.
