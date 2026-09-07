# MÉTHODE DE TRAVAIL — MIA v3
*Version 1.0, 07/09/2026 — Fable. Elle se modifie par commit, avec une ligne
dans `DECISIONS.md`. Elle ne contient rien de nouveau : elle fixe ce que la
semaine a fait marcher, pour que ça ne dépende plus de la mémoire de personne.*

---

## 1. Trois rôles, et ce que chacun ne fait pas

| rôle | fait | ne fait pas |
|---|---|---|
| **Jackson** | décide (règles de trading, instruments, risque, priorités) ; trade et tient le journal `MANUEL` ; fait ce qui touche à la production (VPS, Sierra, comptes, secrets) | ne code pas sous pression ; ne change pas un seuil en cours de campagne |
| **Claude Code** (Fable) | construit et mesure : specs → code → tests → rapport ; propose ; commite et publie | ne scelle pas seul ; ne juge pas la rentabilité en cours de campagne ; ne touche pas au bot qui tourne |
| **Fable-chat** | relit à chaque scellement contre la liste fixe (§5) ; écrit les specs de couche ; tranche les questions de méthode | n'écrit pas dans le dépôt ; ne supervise pas chaque étape ; ne connaît que ce que le dépôt et le message de contrôle lui donnent |

Règle de `CLAUDE.md`, inchangée : *mesurer avant d'annoncer, et qu'un autre
lise.* Le second lecteur n'est pas là parce qu'il est meilleur — il est là
parce qu'il est ailleurs.

---

## 2. L'unité de travail : la brique

Tout ce qui entre dans le système est une **brique** (une couche, un module,
une porte, un déclencheur). Une brique suit huit étapes, dans l'ordre, chacune
avec son artefact. On ne saute pas d'étape ; on peut s'arrêter à n'importe
laquelle.

| # | étape | artefact | qui |
|---|---|---|---|
| 1 | **Spec** — rôle, frontières, entrées avec provenance, ce que ça ne fait pas | `layers/<X>/SPEC.md` | Fable-chat (ou Claude Code, relue) |
| 2 | **Attendu** — ce que la mesure doit donner, écrit *avant* | `BRIEF.md` §attendu | Claude Code |
| 3 | **Distributions** — chaque seuil a sa distribution datée, par instrument, avec l'échantillon | `rapports/distributions_<date>.csv` | Claude Code |
| 4 | **Code** — fonctions pures, < 300 lignes, aucun nombre, `None` possible | `*.py`, `seuils.yaml` | Claude Code |
| 5 | **Tests** — un par élément, deux cas + `None` ; anti-somme ; anti-fuite ; forme (signe) | `test_*.py` | Claude Code |
| 6 | **Mesure** — via `stats.py` (bloc semaine, apparié, hasard 1 000 tirages), contrôle négatif | `rapports/<brique>_57j.csv` + `RAPPORT_<date>.md` | Claude Code |
| 7 | **Revue** — liste fixe §5, verdict binaire par élément | réponse Fable-chat → `reviewed-by` dans le commit | Fable-chat |
| 8 | **Scellement** — critère du `BRIEF` rempli, `STATUS.md` une ligne par élément, `DECISIONS.md` datée | commit + publication | Claude Code, validé par Jackson |

Après scellement, la brique **ne se rouvre pas**. Ce qui naît va dans
`NEXT_CYCLE.md`.

---

## 3. Les règles dures (celles qui viennent d'un échec daté)

1. **Aucun nombre dans le code.** Tout seuil dans `seuils.yaml`, avec unité,
   instrument, distribution et date.
2. **Aucune mesure hors `rapports/`.** Ni docstring, ni YAML, ni commentaire.
   Le YAML *pointe* vers le rapport.
3. **Aucun proxy.** Collecté, ou dérivé par formule connue (`recalc.py`).
   Formule inconnue (provenance B non relue) = colonne absente.
4. **Aucun seuil sans distribution.** Un `null` en mode `appliquee` refuse de
   tourner.
5. **Aucune somme de composantes.** Séries de booléens ; un élément a un seul
   droit (bloquer, annuler, qualifier). `grep` anti-addition dans les tests.
6. **`None`, jamais `False`,** quand on ne peut pas répondre. Journalisé
   `TROU_`.
7. **Pas de fuite d'avenir.** Tout état porte l'instant où il est connu ; un
   test modifie le futur et vérifie que la lecture ne bouge pas.
8. **Unité statistique déclarée** avant la mesure (signal, jour, semaine).
   Contrôle négatif à N tirages, jamais un.
9. **Le signe avant la magnitude.** Un verdict qui compare à un seuil a son
   test « même valeur, signe opposé ».
10. **Une brique appliquée a fermé quelque chose quelque part** (dans le lot
    ou en faux live), ou elle reste observée.
11. **Rien ne change pendant une campagne** : ni seuil, ni déclencheur, ni
    convention. Les idées vont dans `NEXT_CYCLE.md`. La lecture se fait à la
    date fixée, une fois.
12. **Un seul écrivain** par journal, par dépôt, par entonnoir. Le garde-fou
    de `publier.sh` avant chaque push.
13. **Deux conventions avant une anomalie.** Chercher la seconde convention
    (fuseau, unité, borne) avant de déclarer un bug.
14. **Chaque incident est daté** dans `INCIDENT_LOG.md` avec sa catégorie, son
    impact par couche et son action — le jour même.
15. **Un pré-enregistrement sans coureur est un pré-enregistrement de rien.**
    Toute hypothèse pré-enregistrée qui doit ACCUMULER du N a un coureur qui
    l'exécute, et un test de parité qui refuse de publier sans lui. Échec
    daté : les seize d'`OMBRE_ED16`, promis « dès le 08/09 », portés, testés
    — et exécutés par personne. Soixante jours de N = 0 se seraient lus comme
    de la rareté, le piège H6 du cycle 1 à l'échelle seize (07/09, attrapé
    par une question de liste, pas par un test — d'où cette règle).
    **Complément du même jour (revue C2)** : actif = coureur le soir même
    **ET huit cas verts** (LONG/SHORT miroir × lieu seul, lieu + réaction,
    lieu sans réaction, colonne absente → None). Sans les huit cas, le
    setup activé n'a pas de preuve.

---

## 4. Le dépôt est la mémoire

Les conversations se perdent ; le dépôt reste. Ce qui n'est pas dans le dépôt
n'a pas été décidé.

| fichier | contient | mis à jour |
|---|---|---|
| `STATUS.md` | état de chaque brique : écrite / mesurée / passée / scellée, une ligne par élément | à chaque étape |
| `DECISIONS.md` | chaque décision, datée, en une ligne, avec qui l'a prise | à chaque décision |
| `INCIDENT_LOG.md` | chaque erreur trouvée, catégorie, impact, action | le jour même |
| `NEXT_CYCLE.md` | tout ce qu'on refuse de faire maintenant | quand l'idée naît |
| `CONVENTIONS.md` | unités, bornes, fuseaux, clés de session, noms | quand une convention est posée |
| `layers/<X>/SPEC.md`, `BRIEF.md`, `RAPPORT_<date>.md`, `rapports/` | la brique | pendant la brique |
| `CLAUDE.md` | les règles pour l'agent, 300 lignes max | rarement |

Message de commit : ce qui a changé, ce qui a été mesuré (avec le chiffre), ce
qui reste ; `reviewed-by: Fable` quand une revue a eu lieu.

---

## 5. La revue — liste fixe, verdict binaire

Fable-chat reçoit **la racine du dépôt, le commit, et trois lignes** : ce qui a
été fait, ce qui est demandé (revue de scellement / contrôle ponctuel), ce que
l'auteur pense fragile. Il répond par brique : *passe* / *ne passe pas*, le
point bloquant nommé avec fichier et ligne, les défauts avant les qualités,
aucune affirmation sans chiffre.

Les dix questions, toutes posées, à chaque fois :

1. Unité statistique déclarée et respectée ?
2. Contrôle négatif à N tirages, distribution donnée ?
3. Fuite d'avenir — état horodaté à l'instant connu, test présent ?
4. Provenance de chaque colonne lue (A / recalc), formules B relues ?
5. Chaque seuil sur une distribution datée, par instrument, dans `rapports/` ?
6. Signe avant magnitude — test de forme présent ?
7. Plage sur l'agrégat, verdicts par élément (mord / dort avec raison / à retirer) ?
8. Aucun nombre dans le code, aucune mesure hors `rapports/` ?
9. Deux conventions cherchées avant chaque anomalie déclarée ?
10. Impact des incidents tiré sur les *autres* couches ?

Une revue qui ne pose pas les dix n'est pas une revue.

---

## 6. Les rythmes

**Par brique** : les huit étapes, deux jours en général. Revue à l'étape 7
seulement — pas à chaque commit.

**Par jour, pendant une campagne** (à 21:01 UTC après L6) :
- L6 : verdict par instrument, alerte = incident.
- Entonnoir : nombre de signaux, part par porte, trous. **Jamais le P&L.**
- Sauvegarde : le fichier du jour est en local (contrôle L6 « présent en local »).
- `MANUEL` : les trades de Jackson sont dans l'entonnoir avec leur snapshot.

Dix minutes, un message, pas de revue.

**Par semaine** : `STATUS.md` relu par Jackson ; `NEXT_CYCLE.md` trié ; une
brique choisie pour la semaine suivante.

**Au jour 61** : lecture unique, `research/lecture_finale.py`, revue de
Fable-chat sur le rapport avant toute décision.

---

## 7. Protocole d'incident

1. **Constat** : le fait, la mesure, la date de début si elle se trouve.
2. **Catégorie** : SCALE_DRIFT (unité), COLONNE (défaut, saturation, base),
   FUITE, CONCURRENCE, PROXY, SEUIL, CONVENTION.
3. **Impact par couche** : quelles couches lisent la colonne ou le résultat ;
   quelles mesures sont à refaire.
4. **Action** : recalcul, régénération, relance de mesure — datées.
5. **Ce que ça n'affecte pas**, dit explicitement.

Le jour même, avant de continuer. Un incident non écrit se reproduit.

---

## 8. Économie de la revue

Fable-chat coûte cher et perd le fil des longues sessions. Donc :
- une revue par **scellement**, pas par étape ;
- un contrôle ponctuel seulement sur une question précise ;
- toujours la racine et le commit ;
- les specs de couche par Fable-chat en amont, en une fois, déposées dans
  `layers/<X>/SPEC.md`.

Tout le reste est le travail de Claude Code, avec la liste §5 qu'il s'applique
lui-même avant de demander la revue.

---

## 9. Ce que cette méthode ne promet pas

Un edge. Elle promet qu'une erreur ne survit pas à une revue, qu'une mesure
fausse est annotée et non effacée, que rien ne change en silence, et que le
résultat — quel qu'il soit — voudra dire ce qu'il dit.
