# BASCULE DU COUREUR : PC → VPS — la procédure, écrite avant de la faire

*11/09/2026, après l'opération de déploiement à froid. Go de Fable et de
Jackson pour **lundi 14/09, avant l'ouverture**. Ce fichier dit le geste exact ;
il se relit au moment de le faire, pas de mémoire.*

## Pourquoi, en une phrase
Deux coureurs tournent depuis le 08/09 — le PC sous le code du gel, le VPS sous
celui du 08/09 et un pandas jamais testé. Un seul doit écrire. Ce sera le VPS :
il a les données à la source et il tourne sans que le PC de Jackson reste
allumé. C'est la raison d'être du VPS.

## Ce qui est déjà prouvé (11/09, ne pas refaire)
- Suite complète **28 / 28 verte sur le VPS**, dans un bac isolé, avec SON
  Python 3.11.9 et SON pandas — dont `test_agreger_ts` 10/10, le test né de
  l'incident du jour 1 (les `ts` empoisonnés par pandas 3).
- `test_dependances` **4 / 4 sur le VPS** : les 13 modules `CORE` de la
  fermeture transitive existent et s'importent là-bas.
- La production n'a pas été touchée : le coureur du VPS a battu pendant toute
  l'opération, son garde n'a rien eu à relancer.

## Le geste, lundi, dans cet ordre

**1. Avant l'ouverture (avant 15h30 Paris), sur le VPS**
- Désactiver la tâche `MIA-V3-GardeCoureur` — sinon elle relance l'ancien
  coureur pendant qu'on remplace le code :
  `schtasks /change /tn "MIA-V3-GardeCoureur" /disable`
- Arrêter le coureur du VPS (il tourne sous pandas 3.0.2 EN MÉMOIRE ; c'est
  l'arrêt qui le ramène sur 3.0.1, la version testée).
- Remplacer `V3/` et les 13 modules du manifeste (`V3/MANIFESTE_CORE.txt`) par
  le code à jour. Le bac `_TEST_1b` sert de source : il est déjà vérifié.

**2. Les trois vérifications, AVANT de relancer (Fable, 11/09)**
- `test_dependances` vert sur le VPS — le manifeste est complet là-bas.
- La suite complète verte sur le VPS (la relancer : le code a changé depuis).
- Le heartbeat, une fois le coureur relancé, doit afficher **`pandas: 3.0.1` et
  `pandas_hors_liste: false`**. C'est la preuve que la BONNE version court, pas
  seulement qu'un coureur court.

**3. L'instant de bascule — atomique**
Le coureur du PC s'arrête **au moment où** celui du VPS reprend. Pas avant (un
trou dans le live), pas après (deux écrivains). L'heure exacte va dans
`DECISIONS` : *« à partir du jour N, la campagne court sur le VPS »*.

**4. Après**
- Réactiver le garde : `schtasks /change /tn "MIA-V3-GardeCoureur" /enable`
- Vérifier un battement à 60 s d'intervalle, et qu'il n'y en a plus qu'un.

## Ce que la bascule ne fait PAS lundi
**EXEC ne démarre pas le même jour.** Une variable à la fois : lundi, le
coureur unique en ombre ; EXEC vient après qu'il ait fait une journée propre.
Deux changements le même jour, et si quelque chose casse, on ne sait pas lequel.

## Ce qui reste vrai quoi qu'il arrive
Le **rejeu du soir est la mesure** ; le live n'est que la preuve. Si la bascule
rate, la campagne ne perd rien — elle perd une preuve, pas une mesure. C'est
exactement pour ça qu'on peut se permettre de la faire proprement plutôt que
vite.
