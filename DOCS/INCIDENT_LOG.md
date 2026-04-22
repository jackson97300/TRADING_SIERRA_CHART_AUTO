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
| VALIDATION_MISS | **3** | **OUI** (seuil atteint) — a promouvoir : "apres batch reviews modules individuels, OBLIGATION synthesis review cross-module" |
| AGENT_MISUSE | 1 | **OUI preventivement** `feedback_agent_brief_verify.md` |
| SCOPE_CREEP | 1 | Pas encore |
| COMMENT_FALSE | **2** | Pas encore (seuil 3+) — trigger nouveau 22/04 : "grep empirique toute reference file:line header" |
| **LAZY_DELEGATION** | **1** | **OUI preventivement** `.claude/rules/module-review-protocol.md` (6 STEPS) |

**Escalation auto** : quand categorie = 3+ → creer memoire dediee auto-chargee.
