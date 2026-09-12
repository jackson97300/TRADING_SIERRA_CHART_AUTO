# Rapport de session — samedi 12/09/2026 (jour 4 sur 61)

13 commits, 20 fichiers, de 00h13 à 16h07. Suite V3 : **575 PASS / 0 FAIL**,
dont 13 contrôles qui ne peuvent pas échouer — c'est écrit plus bas.
Miroir public : `8d7df8d`, contenu vérifié champ par champ après le push.

**Aucun devenir n'apparaît dans ce rapport.** Ni rendement, ni P&L, ni issue,
ni marge de setup dont la condition est un rendement. C'est la règle, et elle
a été enfreinte le 10/09 dans un rapport de session — voir §7.

---

## 1. La nuit — le verrou du devenir et la fiche de touche

`9f5e9ee` · `d2bd079` · `06788e6`

Question posée par Jackson : « est-ce qu'on est sûr que le devenir est bien
enregistré ? » Réponse : oui, **et le compteur des 61 jours était faux deux
fois**. D'abord sous-compté (adossé au seul journal du narrateur, qui n'existait
pas au jour 1). Puis sur-compté (adossé à l'UNION de quatre journaux, il
comptait un jour dont la mesure officielle avait été effacée par un incident —
donc il ouvrait le dossier trop tôt, la faute exactement inverse). Il ne lit
plus que `LOGS/entonnoir/entonnoir_<jour>.jsonl`, la seule source qui DÉFINIT
la mesure — ni un producteur commode, ni une union.

Puis le pré-enregistrement du cycle 2 (fréquence seulement, aucun devenir lu,
bornes de Poisson, arrêt Bonferroni, jours de sélection exclus), et la fiche de
touche — dont le chiffre central du squelette était faux.

## 2. Le matin — l'incident du 11/09, cause racine

`1516e43` · `25e9330`

**La journée du 11/09 avait été perdue.** Cause trouvée : `scp` écrivait le
fichier DIRECTEMENT sous son nom final, donc pendant la copie le fichier
existait ET il était partiel. Le rejeu officiel du soir a planté dessus
(`PermissionError`) et a effacé ses trois journaux — par conception, pour
qu'une demi-mesure ne passe pas pour un jour couru. Une course de quelques
secondes, un jour sur soixante-et-un.

Corrigé : `.tmp` puis `os.replace`. Un lecteur voit soit l'ANCIEN fichier
complet, soit le NOUVEAU complet, jamais un entre-deux. Jour récupéré.

## 3. Le matin — le radar, et un plantage latent dedans

`f1d34df` · `88961c3` · `2dbbd23`

Le radar des déclencheurs : un RADAR pour ce qui a un état (les quatre gelées,
avec distance et condition restante), un JOURNAL D'ÉVÉNEMENTS pour ce qui est un
événement (les ombres qui ont tiré, sans aucune distance, parce qu'aucun module
n'en calcule). Mélanger les deux ferait croire à un état là où il n'y a qu'une
trace.

**Vingt minutes plus tard, un plantage latent dedans.** `side` est une CHAÎNE
dans les journaux des quatre (800 occurrences sur quatre jours, jamais un
entier) et le code le comparait à un nombre. Il ne levait pas à l'essai parce
que la ligne n'est atteinte que si un lieu est ATTEINT : un plantage qui
n'arrive QUE sur les 7 % de barres qui comptent — donc sur la barre du seul
signal de la campagne. Le test ne l'avait pas vu parce que SA ligne d'exemple
portait un entier : **un décor qui ne ressemble pas aux données ne prouve rien.**
Fermé, puis la FAMILLE fermée (les deux conventions de `side` et la frontière
verrouillée), pas seulement le cas.

## 4. L'après-midi — l'audit des backtests a trouvé autre chose

`4a4a85d` · `e043523` · `952b788`

Deux agents missionnés sur ce qui pouvait être backtesté sans tricher. Ils
n'ont pas trouvé un problème de backtest : **ils ont trouvé deux fuites du
verrou du devenir**, dont une dans le module validé la veille.

- `side_pur` vaut `np.sign(rend_pts)`. `declencheurs.ombres_tirees` faisait
  `net.get("side") or net.get("side_pur")` : sur une ligne d'ombre sans `side`,
  le radar affichait donc LE RÉSULTAT sous l'étiquette « sens ». Et le test
  passait, parce qu'il cherchait des NOMS de champs, pas des VALEURS.
- `pourquoi.py`, étape 2/5 du rythme du soir, imprimait une somme de P&L en ATR
  sous un en-tête disant « JAMAIS le P&L ». Les champs concernés n'existaient
  sur aucun jour de campagne : une arme chargée, pas un coup parti — elle
  tirerait au premier jour où EXEC tient une position.

Neuf noms ajoutés à `CHAMPS_DEVENIR`, chacun mesuré. La **garde anti-recul de
l'horloge** posée avant qu'un rejeu touche le lot : `campagne.courir` refuse un
jour de campagne dont le journal existe déjà, parce que `jours_courus()` compte
ces fichiers et qu'un rejeu ne peut que faire RECULER le compteur. Et **L6
construite** — la couche qui doit dire « le bot ne voit rien » n'avait qu'un
README.

## 5. Deux défauts d'exécution trouvés à froid

Aucun des deux ne tire aujourd'hui ; les deux tireraient au premier ordre.

- **Le bot enverrait `Symbol: "Z26"`.** `calendrier.contrat_actif` rend un code
  de mois nu, `_to_contract('Z26')` le rend tel quel (vérifié en exécution), et
  `exec_sim` le passe en `symbol=`. **ES et NQ enverraient le même symbole.** La
  porte E8 ne peut pas l'attraper : les deux côtés de sa comparaison ignorent
  l'instrument. Et la table du connecteur est restée sur le contrat précédent.
- **La mise à plat EOD ne peut jamais se déclencher.** Seuil `sortie_horaire_et`
  à 955 minutes ET, mais sur 66 jours la dernière barre cash vaut 945 et
  **aucun jour n'a de barre à 950 ou plus**. Un backtest « cas limites EOD »
  mesurerait zéro, et ce zéro se lirait comme de la rareté.

Les deux touchent le périmètre gelé : ils attendent une revue, sous règle 16.
Déplacer 955 vers 945 « parce que ça ne se déclenche jamais » serait de
l'ajustement de seuil sur les données ; la vraie question est si la mise à plat
doit s'exprimer sur la DERNIÈRE BARRE DISPONIBLE plutôt que sur une heure
d'horloge — un changement de définition, pas de seuil.

## 6. Le soir — la revue a mordu sur le travail du jour

`42b4d92` · `4491f2b`

Trois agents sur les onze commits de la journée. **Deux régressions introduites
le matin même**, plus deux faux témoins.

- **La garde anti-recul aurait figé une demi-mesure.** Une passe lancée EN
  SÉANCE garde son journal (les deux instruments ont plus de six barres cash,
  donc le mécanisme d'effacement ne s'applique pas). Le rejeu de 21h01 aurait
  alors été REFUSÉ et la mesure officielle du jour serait restée la passe
  partielle de l'après-midi, définitivement. Le rejeu du soir EST la mesure
  officielle : il passe désormais `--rejouer-officiel`, et la garde protège
  tous les autres points d'entrée — la menace visée.
- **Le correctif atomique rendait un scénario plus SILENCIEUX, pas moins.**
  `final + ".tmp"` sans PID : deux coureurs simultanés écrivent le même `.tmp`
  puis basculent, et le résultat a l'air complet en étant mélangé — alors que
  l'écriture directe d'avant donnait un fichier partiel qui plantait
  bruyamment. On préfère toujours un crash visible à une donnée fausse.
  Suffixe PID, déjà la convention du dépôt.
- **Le test écrit le matin pour attraper une fuite de valeur était un faux
  témoin.** `side_pur` étant entré dans `CHAMPS_DEVENIR`, le filtre le retirait
  AVANT que le contrôle ne le lise : l'expression cassée et la corrigée
  rendaient toutes deux `None`. Prouvé par exécution. Corrigé en neutralisant
  le filtre pendant le contrôle — il échoue maintenant si le repli revient.
- **Le gardien de la frontière `side` ne voyait pas le bug qu'il commémore.**
  Son motif exigeait un `side` nu suivi d'un opérateur, alors que l'idiome du
  dépôt est `d["side"]`. Vérifié sur le source d'avant le correctif : aucun
  match. Motif élargi, plus un **méta-contrôle qui échoue si le détecteur
  reperd sa capacité à détecter**.
- `_sens(0)` rendait « short » et `_sens("0")` rendait `None` — deux réponses
  pour la même valeur selon son type, alors qu'un jour plat au tick est un
  NO-TRADE. Zéro n'est plus un sens.
- `lire_fantomes.py` imprimait moyenne, intervalle et somme d'un P&L simulé,
  avec le chemin en argument de ligne de commande : couvrir le CHAMP sans
  fermer le LECTEUR ne protégeait de rien. Verrou posé ; l'archive d'avant la
  campagne reste ouverte.
- L6 divisait tout par le même total, sous-estimant une cause dont la colonne
  avait manqué certains jours. Un dénominateur PAR CAUSE. Et sa borne « avant
  l'ouverture cash » était une heure UTC en dur, qui aurait mal classé tout le
  dernier mois de la campagne dès le 1er novembre : comparaison en minutes ET.

## 7. Ce qui reste ouvert, et ce n'est pas par oubli

- **Un devenir du jour 2 est publié** dans un rapport de session depuis le
  10/09. La valeur n'a pas été lue et le fichier n'a pas été touché : elle est
  dans l'historique git public, donc la retirer demande une réécriture
  d'historique, planifiée et pas précipitée.
  La raison de fond mérite d'être notée : pour le setup EOD, la condition de
  déclenchement **est** le rendement du jour. « De combien le setup a raté » et
  « ce que la journée a rendu » sont le même nombre. L'auteur ne rapportait pas
  un résultat, il rapportait une marge — et aucun garde-fou mécanique ne peut
  distinguer les deux, parce qu'il n'y a rien à distinguer.
- **Le verrou fuit encore par `side`.** Sur les lignes où EOD tire,
  `side == side_pur` par construction : masquer l'un et afficher l'autre ne
  cache rien. Une liste de noms plate ne peut pas attraper une **égalité
  structurelle**. Il faut une règle PAR SETUP — le vrai chantier.
- Même forme ailleurs : `x_natif` dans `LOGS/marges/` porte le rendement du
  jour sous un nom de distance, pour ce seul setup.
- `sans_devenir` ne filtre qu'un niveau : un dict imbriqué passera entier dès
  qu'EXEC tiendra une position.
- Quatre lots de mesure sans borne haute : une relance écrirait des jours de
  campagne dans leurs rapports.
- Un point d'entrée peut écrire dans la mesure officielle sans passer par la
  garde anti-recul.
- **13 contrôles de la suite ne peuvent pas échouer** (tautologies ou motifs
  hors sujet). 575 PASS surestime la couverture d'environ 2,5 %. Le chiffre
  honnête est « 562 qui prouvent quelque chose et 13 qui décorent ».

## 8. Corrections de chiffres annoncés

Un agent a reproduit indépendamment 40 mesures annoncées. Aucune n'est fausse,
cinq formulations étaient imprécises. Les deux qui comptaient :

- le glissement `open(t+1) − close(t)` avait été annoncé « médiane 0, max un
  tick » : c'était la médiane d'ES SEULE. Sur NQ, médiane 2 ticks, p99 12,
  maximum 132 ticks, et plus d'une transition sur deux dépasse le tick. Un
  paramètre unique pour les deux instruments ne veut rien dire ;
- le lot n'est ni 108 ni 79 jours mais **66 exploitables** par instrument (les
  mêmes 66 des deux côtés) et **56** avec assez de chauffe. Le dénominateur
  change la puissance de tout audit de fréquence ;
- et « 43 % des barres » est en réalité 43 % des **transitions** : il y a une
  paire de moins que de barres par jour.

## 9. État de la pile à la fermeture

Les trois processus locaux tournaient avec du code périmé — dont l'écrivain,
démarré deux jours plus tôt, qui portait encore en mémoire le `scp` non
atomique, c'est-à-dire le bug qui a coûté le 11/09. Les gardes planifiées ne
relancent que ce qui est MORT : un processus vivant avec du vieux code leur est
invisible, par conception. Seule la vitrine savait le dire d'elle-même — le
détecteur de péremption bâti le 11/09 a fonctionné et n'a pas menti.

Les trois ont été relancés par les fonctions du dépôt, jamais à la main
(`garde_coureur`, `garde_scenarios`, `lanceur.assurer_vitrine`), ce qui pose le
battement provisoire tamponné évitant qu'une garde croisée tue un processus
jeune et sain. Vérifié après : **écrivain unique**, battements frais des deux
côtés, empreinte du serveur changée, `pandas_hors_liste: false`.

La moitié VPS reste sur une version hors liste — c'est la bascule, et elle est
désormais la seule variable de sa journée.

## 10. Ce que la journée enseigne

**Trois fois aujourd'hui, un correctif a ouvert un trou plus silencieux que
celui qu'il fermait.** Une garde posée vite s'est retournée contre le flux
normal ; une écriture rendue atomique mais non unique a transformé un crash en
corruption muette ; un test écrit pour attraper une fuite de valeur ne pouvait
pas échouer sur le bug qu'il commémorait.

La parade n'est pas d'écrire plus de tests. C'est de **tester le test** : un
méta-contrôle qui échoue si le détecteur perd sa capacité à détecter. Un
système qui passe tous ses tests est moins solide qu'un système qui a prouvé
que ses tests peuvent mentir et qui a posé le niveau au-dessus.

Et le corollaire, valable pour les 57 jours restants : un garde-fou n'est pas
acquis parce qu'il est écrit. Il est acquis quand on a montré ce qui le fait
échouer.
