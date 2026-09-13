# Brancher V3 sur l'exécution éprouvée — la spécification

**Décision (14/09) : on n'écrit pas un nouveau bot.** La chaîne de décision V3
se branche sur la couche d'exécution de `BOT/`, qui a déjà tourné contre la
plateforme et qui a déjà payé ses leçons.

Ce document est écrit AVANT le code, pas après. Il dit ce que chaque monde
apporte, ce qui les relie, et surtout **ce qu'on éteint et pourquoi** — parce
qu'une désactivation sans raison écrite se fait rallumer six mois plus tard.

---

## 1. Pourquoi pas un nouveau bot

La question s'est posée naturellement : pourquoi `exec_sim` alors qu'un système
existe ? L'inventaire tranche.

La liste de mise en service (`MISE_EN_SERVICE_EXEC.md`) comptait **six points
rouges** sur neuf pour `exec_sim`. La plupart sont verts dans `BOT/` :

| point | `exec_sim` | `BOT/` |
|---|---|---|
| limites de risque appliquées | absent | `risk_manager.can_trade()` |
| réconciliation du P&L | absent | `on_trade_open()` / `on_trade_close()` |
| coupe-circuit | écrit, jamais éprouvé | `_kill()`, plus des tests réels |
| bracket garanti | **position nue** (revue 13/09) | OCO manuel validé, correctif de la course au fill |
| dimensionnement | absent | présent — mais à éteindre, cf §4 |
| mise à plat de fin de séance | **inatteignable** | `should_flatten_eod()` + moniteur de position |

Et surtout : une quinzaine de tests DTC de `BOT/` ont tourné contre la vraie
plateforme — brackets sur les deux instruments, OCO persistant, OCO simultané,
croisement micro. Pas des tests avec un faux connecteur : des runs réels.

**La distinction qui rend la reprise légitime** : les bots précédents ont échoué
sur la STRATÉGIE, pas sur l'exécution. Le verdict portait sur l'avantage. La
tuyauterie, elle, a tenu. On reprend ce qui a tenu, on remplace ce qui a échoué.

---

## 2. Ce que chaque monde apporte

**V3 décide et trace.** Les couches L0 à L6 : une porte dit si un signal a le
droit d'exister, un biais, des déclencheurs, une confirmation, des barrières,
une surveillance de la donnée. Plus la discipline qui fait la valeur du
projet : **aucun refus silencieux**, un verdict nommé par ligne.

**`BOT/` exécute et protège le compte.** Cycle de vie de l'ordre, gestion du
fill, suivi de position, risque de compte, sortie de fin de séance.

**L'adaptateur ne fait que traduire.** Il ne décide rien, il ne calcule rien.

---

## 3. Le contrat — ce qui traverse

Une intention V3 porte : `snapshot_id`, `sym`, `side`, `hypothese`,
`ts_signal`, `contrat`, `entree` (type, référence, date de péremption),
`barriere` (stop et objectif en ticks entiers, plus leurs sources), la sortie
horaire et sa source, la taille, l'horodatage d'émission, l'état.

La couture d'entrée de `BOT/` est `bot_main._get_signal()`, qui rend un objet
de signal (direction, score, confiance, motif) et dépose le couple
(stop, objectif) en ticks. Elle a **déjà deux modes** — modèle appris, sinon
règles — donc une troisième source est une couture, pas une réécriture.

| ce que `BOT/` attend | ce que V3 fournit |
|---|---|
| direction | `side` |
| stop et objectif en ticks | `barriere`, entiers, avec leurs sources |
| instrument | `sym` |
| motif | `hypothese` — la famille du déclencheur |

**Ce que V3 ajoute et que `BOT/` n'avait pas** : une clé d'idempotence (le même
signal ne peut pas partir deux fois), une date de péremption (une intention
trop vieille ne s'exécute pas), et les sources de la barrière — de quoi
recomposer la décision plus tard sans la deviner.

---

## 4. Les trois conflits, et leur résolution

### 4.1 Le dimensionnement — À ÉTEINDRE

`risk_manager.compute_position_size()` applique un demi-Kelly avec un **taux de
réussite supposé de 55 %** en valeur par défaut.

C'est précisément le nombre que la campagne existe pour mesurer, et il serait
ici inventé. Le point mort mesuré se situe entre 41 et 46 % selon l'instrument
et la géométrie ; supposer 55 % conduit à miser plusieurs fois trop gros sur un
avantage non démontré.

**L'intention V3 porte `taille: 1`, fixe et délibéré. L'adaptateur n'appelle
jamais le dimensionnement.** La question se rouvrira le jour où un taux de
réussite sera mesuré sur un échantillon suffisant — pas avant, et pas par
défaut.

### 4.2 Le score — À NEUTRALISER

V3 n'a **ni score ni confiance**. Sa chaîne est binaire : le signal passe ou il
est fermé, avec un motif. C'est voulu — pas de classement, donc pas de seuil de
score à régler, donc pas de réglage à faire dériver.

L'adaptateur pose une valeur de convention, et **toute logique de `BOT/` qui
dépend du score doit être neutralisée, pas nourrie d'un nombre inventé.** Elles
sont à débusquer une par une : plusieurs journalisations de rejet la
consomment.

### 4.3 Les sorties — UN SEUL PROPRIÉTAIRE

V3 porte une sortie horaire par famille et une expiration en barres. `BOT/`
porte sa propre mise à plat et une sortie sur durée.

Deux propriétaires pour « quand je sors » est une contradiction en attente. Et
la mesure tranche dans un sens inattendu : **la sortie horaire de V3 ne peut
jamais se déclencher** — son seuil est postérieur à la dernière barre de la
grille de quinze minutes —, alors que celle de `BOT/` fonctionne.

**`BOT/` est propriétaire de la sortie.** V3 continue de journaliser la sienne
comme une information, jamais comme un ordre. La question de fond — la mise à
plat doit-elle s'exprimer sur la dernière barre disponible plutôt que sur une
heure d'horloge — reste ouverte et se traite à part.

---

## 5. Qui décide quoi — un propriétaire par question

Trois endroits répondaient à « ai-je le droit de trader ? » : les portes L0, les
portes d'exécution, le gestionnaire de risque. Trois propriétaires pour une
question, c'est la garantie qu'un jour deux se contredisent.

| question | propriétaire | mode |
|---|---|---|
| ce signal a-t-il le droit d'exister ? | **L0** | appliqué en live, observé en campagne |
| où se placent stop et objectif ? | **L5** | appliqué |
| ce compte peut-il se le permettre ? | **`risk_manager`** | **seul à bloquer en live** |
| cette intention est-elle encore valable ? | **portes d'exécution** | doublon, péremption, contrat |
| la donnée est-elle lisible ? | **L6** | observé |

Les portes L0 de la campagne restent **volontairement inertes** : une limite qui
bloque tronque l'échantillon qu'elle prétend protéger. C'est juste pour la
mesure, et faux pour un compte réel — d'où la séparation.

---

## 6. Le P&L : un mur global, deux compteurs

L'état de risque actuel tient un P&L **global** ; le symbole est reçu et ignoré.
Or la lecture par instrument est nécessaire, et le mur doit rester global.

**Un seul plafond — celui du compte — et un compteur par instrument qui
informe.** Découper le budget en deux empêcherait d'utiliser tout le budget sur
un instrument quand l'autre est à plat, alors que la firme ne connaît que le
compte. Un sous-plafond par instrument reste possible plus tard ; ce sera un
ajout, jamais une découpe.

Bonne nouvelle : le pic de P&L de la journée est **déjà suivi**. C'est la base
d'un drawdown glissant, donc de ce que mesure une société de financement.

---

## 7. Un bot ou deux ?

**L'architecture suit le COMPTE, pas l'instrument.**

Un compte partagé impose **un seul processus** : deux processus indépendants ne
peuvent pas faire respecter une limite commune — chacun se croit dans les clous
pendant qu'ensemble ils la dépassent. Mesure : deux positions micro ouvertes
simultanément consomment déjà près de 80 % d'un budget journalier de 200 $.

Donc : **un bot, deux instruments, deux configurations** — parce que la
géométrie doit différer. Les frais d'aller-retour valent 9,6 % de l'ATR sur un
instrument contre 2,6 % sur l'autre : ils ne peuvent pas viser la même taille
d'objectif.

L'architecture précédente à quatre bots était cohérente parce qu'elle avait un
compte par bot. Avec une seule évaluation, elle ne l'est plus.

---

## 8. Le déroulement en console — un contrôle, pas un confort

Seize signaux ont perdu leur bracket pendant deux jours parce que personne ne
regardait. Un récit qu'on lit est un garde-fou ; un journal qu'on n'ouvre pas
n'en est pas un.

Ce qu'il doit montrer, par ordre d'importance :

1. **Les refus autant que les trades** — quand rien ne se passe, on doit voir
   quelle porte a fermé et sur quel motif. Un bot muet est indiscernable d'un
   bot cassé.
2. **Le chemin complet d'un signal** : déclencheur, portes traversées,
   intention, ordre, fill, bracket posé — chaque étape horodatée, pour que le
   glissement et le retard se lisent directement.
3. **L'état** : position, P&L par instrument et global, part du budget
   consommée, temps avant la mise à plat.

Deux modes, pas un : un tableau redessiné pour l'état, un flux qui défile pour
les événements. Un récit qui défile trop vite n'est pas lu — le lanceur V3 a
déjà appris cette leçon.

---

## 9. Ce qui reste ouvert

- La géométrie de la miette : objectif et stop, par instrument, dérivés de la
  structure de coûts et non choisis pour produire un nombre de trades.
- Les sessions hors cash : les déclencheurs actuels sont des objets de la
  séance américaine et n'y sont pas définis. C'est une conception, pas un
  réglage.
- La définition de la mise à plat : heure d'horloge ou dernière barre.
- Le nombre de contrats : dérivé du drawdown de la firme, jamais l'inverse.

---

## 10. La règle qui gouverne tout ce document

Chaque désactivation porte sa raison écrite. Chaque propriétaire est unique.
Chaque nombre vient d'une mesure ou d'une raison structurelle, jamais du fait
qu'il produise le résultat qu'on espérait.
