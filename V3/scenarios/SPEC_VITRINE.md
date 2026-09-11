# SPEC_VITRINE — ce que la vitrine a le droit de faire

*Fable, 10/09/2026 (A0 de la liste fusionnée). Une page, écrite avant le
premier fichier. Cinq phrases qui ne bougent plus ; chacune a son test.*

1. **La vitrine LIT** `LOGS/scenarios/direct_<jour>.jsonl` (l'écrivain),
   `LOGS/scenarios/scenarios_<jour>.jsonl` (le rejeu du soir, en repli, marqué
   `source: rejeu`), `LOGS/scenarios/alertes_<jour>.jsonl` et
   `LOGS/heartbeat_scenarios.json`. **Elle n'écrit que** dans
   `V3/journal_manuel/<jour>.md` (le bouton NOTER), dans
   `LOGS/scenarios/alertes_<jour>.jsonl` (les alertes émises) et le marqueur
   `LOGS/scenarios/MUET`. Jamais ailleurs — un `grep` des écritures le prouve.
2. **Aucun seuil, aucune logique de scénario dans la vitrine** : elle affiche
   ce que l'écrivain a écrit. Aucun calcul en JavaScript, juste l'affichage.
3. **Aucun mot conclusif ni conseil** : « va », « devrait », « conseil »,
   « achète », « vends », « signal », « TP conseillé », « SL conseillé » sont
   interdits dans le HTML, dans `/etat.json`, dans les gabarits d'alertes et
   dans les phrases de voix — test `grep`. Les sorties du scénario disent où il
   « se termine » et où il « meurt ».
4. **Un état « en cours, non validé » est gris et n'arme rien.** Un heartbeat
   de plus de 60 s grise toute la page : « écrivain muet ». Un bandeau
   « NON MESURÉ w1 » reste affiché tant que `mesure_w1` n'a pas produit son
   rapport.
5. **La même page sert le desk (fenêtre épinglée), le dashboard et le stream.**
   Une seule source HTML (`vitrine.html`), servie sur `localhost:8765` en local,
   copiée telle quelle sur le dashboard par `publier`, jamais éditée à la main.

## Ce que la page montre AVANT la première barre (11/09)
La capture du 11/09 disait tout : « aucune barre complète aujourd'hui », et rien
d'autre — alors que c'est le moment où Jackson prépare sa journée. Depuis, quand
aucune barre de 15 min n'est complète, la page montre les **niveaux figés qui
serviront** (VA de la veille, PDH/PDL, murs, HVL, extrêmes de la nuit), le
dernier prix connu, et la distance à chacun **en ticks, en points, et en dollars
SUR UN MICRO** — parce que c'est un micro qui part, et qu'une distance en ticks
ne dit rien tant qu'on ne l'a pas traduite.

Le diviseur est écrit dans le code (`MICRO_PAR_STANDARD`), jamais recopié : la
valeur de tick de `CORE` est celle du E-mini STANDARD, le micro vaut un dixième.
Six confusions d'unités en une semaine dans ce dépôt, toutes d'un facteur
constant — celle-ci ne s'ajoutera pas à la liste.

Et cela ne franchit aucune des cinq phrases : ce sont des faits et des
distances. La page dit où est le prix, jamais quoi en faire.

## La page se recharge quand son code change (11/09)
Une fenêtre native charge son HTML **une seule fois**. Le 11/09, le bloc
avant-ouverture était déployé, le serveur le servait, et la fenêtre affichait
toujours « aucune barre complète » : l'ancien JavaScript vivait en mémoire.
Depuis, le serveur expose `/version` (le hash du HTML servi) et la page le
compare toutes les quinze secondes : si le code a changé, elle se recharge
seule. Sans ça, chaque amélioration exige de fermer la fenêtre — et on finit
par croire que la page est cassée alors qu'elle est simplement périmée.

## Ce que Fable vérifie à chaque livraison
- la frontière (les écritures) ; les mots interdits ; direct = rétrospectif
  chaque soir (`FUITE` = incident) et `grammaire_version` sur chaque ligne ;
  aucun effet sur la décision (phase B) ; le garde qui relance l'écrivain en
  moins de cinq minutes, sans doublon.
