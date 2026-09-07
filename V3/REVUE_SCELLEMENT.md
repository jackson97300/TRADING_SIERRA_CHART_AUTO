# La revue de scellement — la liste fixe

*Établie le 07/09, après une semaine où chaque erreur a été attrapée par un
second lecteur — jamais par l'auteur, jamais par le modèle le plus fort.*

**Le principe.** Celui qui a trouvé l'erreur n'était pas *meilleur* — il était
*ailleurs* : pas dans le fichier, pas dans l'élan de la tâche. Un agent au fond
d'un chantier valide ce qu'il vient de construire, quel que soit le modèle.
L'ATR faux d'un facteur cinq, la séparation à l'unité fausse, le `bool(None)`,
la plage par porte contradictoire à 25 portes : quatre erreurs, quatre fois un
lecteur extérieur.

**Quand.** À chaque **scellement** — pas à chaque étape. Le lecteur peut être
Fable, ou une session Claude Code **neuve** avec le dépôt et rien d'autre.
Toujours donner **la racine du dépôt et le commit** — lire un sous-dossier a
déjà fait rater la moitié du système une fois.

---

## La liste — sept contrôles, aucun facultatif

1. **Unité statistique.** L'unité du bootstrap est celle de la grandeur
   mesurée — la semaine pour un biais hebdomadaire, jamais « le jour » par
   défaut. *(60 jours = 13 semaines ; l'IC par jour a fabriqué un −0,78.)*

2. **Contrôle négatif.** Une distribution (≥ 1 000 tirages), avec la même
   persistance que la vraie grandeur. Un tirage unique est un exemple.

3. **Fuite d'avenir.** Toute grandeur porte l'instant où elle est **connue**,
   pas celui où elle naît. Test : modifier les barres futures ne change rien.
   *(Cinq fiches sur six de F23 avaient une issue lue 90 minutes trop tôt.)*

4. **Provenance des colonnes.** A, ou recalculée avec formule écrite. Une
   colonne B se relit ou se refait ; une C ne se lit pas. Et
   `verifier_colonnes` déclare les dépendances — trois colonnes se sont
   perdues à l'agrégation en un seul jour.

5. **Seuil sur distribution.** Aucun seuil sans sa distribution datée dans
   `rapports/`, par instrument. *(g1_ES/g1_NQ = 7,6 ; le seuil partagé se
   serait trompé d'un facteur huit.)*

6. **Signe avant magnitude.** « Même magnitude, signe opposé » doit changer le
   verdict — en test, pas en intention. *(Trois occurrences de la même faute
   en deux jours.)*

7. **Plage sur l'agrégat.** Les plages s'établissent sur la mesure, jamais
   avant elle, et se posent sur l'agrégat — pas par élément. *(15–30 % par
   porte × 19 portes = 4,56 % de survivants : arithmétiquement impossible.)*

---

## Les trois règles d'accompagnement

- **Le dépôt est la mémoire, pas la conversation.** Décisions dans
  `DECISIONS.md`, specs dans `layers/*/SPEC.md`, critères dans `BRIEF.md`.
- **L'attendu écrit avant chaque mesure.** La seule protection contre un
  modèle qui se convainc lui-même, et elle ne coûte rien.
- **Mesurer avant d'annoncer, et qu'un autre lise.** La première moitié, un
  modèle plus fort la fait mieux. **La seconde, aucun modèle ne la fait seul.**
