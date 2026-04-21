# Regle — Protocole INCIDENT_LOG obligatoire

**Date** : 2026-04-21
**Source** : Jackson directive "chaque correction devient permanente"

## Regle souveraine

**AVANT toute action critique**, Claude DOIT :
1. Consulter `DOCS/INCIDENT_LOG.md`
2. Grep la categorie de la tache
3. Appliquer les lecons des incidents passes matchs

**Actions critiques** (trigger protocole) :
- Fix C++ (DMP_*, CPP/*)
- Fix Python pipeline ML (dataset_builder, train_lightgbm, validator, risk_manager)
- Dispatch agent (Agent tool)
- Design doc (spec architecture)
- Deploy VPS (scp C++/Python)
- Affirmation existence de code/feature ("X n'existe pas", "Y est deja documente")
- Creation nouvelle infra (agent, rule, script, schema bump)

## Protocole strict

### Etape 1 — Consultation

Grep `DOCS/INCIDENT_LOG.md` pour la categorie applicable. Categories autorisees :
- `CONTEXT_MISS`, `PATTERN_11`, `AGENT_MISUSE`, `OVER_ENGINEERING`
- `VALIDATION_MISS`, `COMMENT_FALSE`, `SCOPE_CREEP`, `DEPLOY_UNSAFE`

### Etape 2 — Pre-action checks

Pour chaque incident matching la tache en cours :
- Lire "Trigger prevention"
- Verifier que le trigger ne s'applique pas maintenant
- Si oui → appliquer la lecon

### Etape 3 — Detection incident nouveau

Si durant la tache ou apres, un incident est detecte (par Jackson, un agent, ou self-reflexion) :
1. Ajouter entree en haut de `DOCS/INCIDENT_LOG.md` avec template :
   ```
   ### YYYY-MM-DD HH:MM — [CATEGORIE] — Titre court
   **Contexte** : ...
   **Ce qui a mal tourne** : ...
   **Cause racine** : ...
   **Lecon** : ...
   **Trigger prevention** : ...
   **Reviewed** : Jackson / agent-name / self
   ```
2. Update stats categorie en bas du fichier
3. Si categorie atteint 3+ occurrences → promouvoir en memoire dediee auto-chargee

### Etape 4 — Escalation

Si incident grave (deploy casse, feature ML polluee, pattern 11 detecte) :
- Documenter dans INCIDENT_LOG **ET** creer memoire dediee meme si < 3 occurrences
- Trigger agent review pour validation independante

## Check de non-bypass

Si je commence une reponse sans avoir consulte INCIDENT_LOG sur tache critique :
- Jackson peut dire **"INCIDENT_LOG !"**
- Je dois :
  1. M'arreter
  2. Lire le fichier
  3. Documenter mon propre oubli comme incident `CONTEXT_MISS`
  4. Reprendre

## Regle de cross-reference

INCIDENT_LOG coexiste avec :
- `.claude/rules/lessons.md` : lecons techniques marche/DTC/DMP
- `.claude/rules/critical-tasks-review.md` : protocole agent review
- `.claude/rules/data-quality.md` : regles V2 dataset
- Memoires `feedback_*.md` : patterns auto-chargees

INCIDENT_LOG = **trace chronologique factuelle** (evenementielle).
Rules = **regles generales** (comportementales).
Memoires = **patterns promouvables** (seuil 3+ atteint).

## Protocole de fin de session

Avant cloture (ou avant `/compact`) :
1. Review incidents ajoutes cette session
2. Verifier stats categories
3. Si escalation declenchee (3+) → creer memoire dediee
4. Commit `DOCS/INCIDENT_LOG.md` (ne jamais perdre trace)

## Anti-patterns interdits

- ❌ Supprimer une entree INCIDENT_LOG (meme ancienne/resolue)
- ❌ Agir sans consulter INCIDENT_LOG sur tache critique
- ❌ Affirmer "bug detecte" sans verifier PROHIBITED_FEATURES / code existant d'abord
- ❌ Dispatcher agent sans verifier `.claude/agents/*.md` adapte a la tache
- ❌ Modifier un chiffre (LOC, count, %) dans doc sans grep les autres occurrences

## Regle d'enforcement

Cette regle est **prioritaire** sur la productivite. Mieux vaut 2 min de consultation INCIDENT_LOG que 30 min de fix duplique / dette technique / re-audit.

La **zero dette** exigee par Jackson commence par **zero repetition d'erreur connue**.
