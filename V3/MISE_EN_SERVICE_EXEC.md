# Mise en service du chemin d'ordre — la liste qui bloque

**Règle souveraine : aucun ordre ne part tant que les neuf points ne sont pas
verts.** Pas « on verra en route », pas « c'est du SIM donc ce n'est pas grave ».
Un bot qui perd de l'argent est un problème de stratégie ; un bot qui perd le
**contrôle** est un problème d'ingénierie, et c'est celui-là que cette liste
ferme.

Chaque point porte son critère MESURABLE et le test qui le prouve. Un point
sans test n'est pas vert, il est *espéré*.

---

## Pourquoi ce document existe

Le 13/09, trois défauts critiques du chemin d'ordre ont été trouvés — par une
revue, pas par la conception :

- la position serait partie **NUE**, sans stop ni objectif : le connecteur ne
  pose le bracket que si on lui donne des PRIX, et on ne lui donnait que des
  ticks. L'ordre parent partait seul et le code journalisait `envoye` avec les
  ticks du bracket, comme s'il existait ;
- le **sens** était hors protocole : la convention interne est ±1, l'énumération
  DTC est 1 = achat / 2 = vente. Le long passait par coïncidence, le short
  envoyait une valeur qui n'existe pas — et fermer un long était impossible ;
- le connecteur **ne s'importait même pas**, ce qui prouve que ce chemin n'a
  jamais tourné une seule fois, pas même à vide.

Le premier correctif de la journée — l'identité de l'instrument — avait rendu
le chemin *fonctionnel sans le rendre sûr* : avant, un symbole invalide se
faisait probablement rejeter, échec bruyant et gratuit ; après, l'ordre routait
correctement et partait sans protection. **Retirer un fusible sans réparer le
court-circuit est une régression, pas un correctif.**

Cette liste est la question qu'un quant de salle pose AVANT d'écrire la
première ligne : *qu'est-ce qui doit être vrai pour qu'un ordre ait le droit de
partir ?*

---

## Les neuf points

### 1. Contrôles de risque APPLIQUÉS, pas observés

Taille maximale, perte journalière maximale, cadence maximale d'ordres. Un
garde-fou en mode « observé » journalise qu'il aurait bloqué — il ne bloque pas.

**Critère** : sur un état forcé au-delà de chaque limite, l'ordre est REFUSÉ et
le refus est journalisé avec son motif.
**Test** : un cas par limite, état fabriqué, verdict attendu `refus`.

### 2. Réconciliation au démarrage et en continu

Ce que le broker dit qu'on tient contre ce qu'on croit tenir. Sans elle, l'état
diverge en silence et toutes les portes qui le lisent deviennent fausses.

**Critère** : après un fill, la position apparaît dans l'état et les ordres en
vol se vident ; après un redémarrage, l'état reconstruit correspond à ce que le
broker rapporte ; un état plus vieux que son TTL est un TROU, jamais un
« tout va bien ».
**Test** : un cycle complet ouverture → fill → fermeture, plus un redémarrage
au milieu.

> Aujourd'hui : rien ne met l'état à jour après l'envoi. Les ordres en vol ne se
> vident jamais, donc la porte qui les lit **refuse tout après le premier ordre
> de la vie du bot**. Le bot s'auto-bloque, et rien ne le dit.

### 3. Kill switch ÉPROUVÉ

Un interrupteur écrit et jamais actionné n'est pas un interrupteur.

**Critère** : avec une position ouverte, la présence du fichier d'arrêt ferme la
position, journalise la sortie et empêche tout nouvel ordre — vérifié sur un
run réel, pas par lecture du code.
**Test** : run avec position ouverte, dépôt du fichier, journal à l'appui.

### 4. Bracket garanti, ou position fermée immédiatement

Une position sans stop n'est jamais tolérée, même une seconde, même en
simulation — parce que l'habitude prise en simulation est celle qu'on garde.

**Critère** : si le connecteur ne rend pas les identifiants du stop ET de
l'objectif, la position est fermée au marché dans la foulée, un incident est
écrit, et le bot s'arrête. Jamais un verdict `envoye` sur un ordre nu.
**Test** : connecteur simulé qui rend un parent sans enfants → fermeture
immédiate + incident + arrêt.

### 5. Identité de l'instrument vérifiée sur le fil

**Critère** : le symbole envoyé porte la racine de l'instrument ET le contrat
actif du calendrier ; deux instruments ne peuvent jamais produire le même
symbole ; une racine inconnue lève au lieu de deviner la place de cotation.
**Test** : un contrôle par instrument, plus un contrôle d'inégalité, plus un
cas de racine inconnue.

> Le contrat seul (« un code de mois ») n'identifie pas un instrument. La porte
> qui compare les contrats ne peut structurellement pas voir une confusion entre
> deux instruments : ses deux côtés ignorent la racine.

### 6. Dimensionnement décidé et ÉCRIT

Le dépôt porte deux conventions de valeur du point, dans un rapport de **dix**.
La mesure de la campagne calcule en micros ; le symbole routé est le contrat
standard. Tant que ce n'est pas tranché, la taille du risque est inconnue.

**Critère** : le contrat retenu et sa valeur du point sont écrits dans le dépôt,
et le coût d'un stop à l'ATR médian est exprimé en **part du budget de perte
journalière**. Si un seul stop dépasse ce budget, le dimensionnement est refusé.
**Test** : un contrôle qui recalcule ce rapport depuis les constantes et échoue
s'il dépasse la part déclarée.

> Mesuré : un stop de 1 ATR vaut 111 $ en micro sur l'instrument le plus
> volatil — **55 % du budget journalier**. Sur le contrat standard, 1 105 $,
> soit **cinq fois et demie** ce budget. Un seul trade perdant clôt la journée
> dans un cas, la fait exploser dans l'autre.
>
> Et changer de contrat n'est pas un changement de chaîne de caractères : le
> dépôt garde la trace d'un retour arrière causé par un contrat micro non
> configuré côté plateforme — ordres non routés, positions fantômes. La
> vérification côté plateforme fait partie du critère.

### 7. Mise à plat de fin de séance PROUVÉE

Jamais de position gardée d'un jour sur l'autre.

**Critère** : avec une position ouverte à l'heure de sortie, elle est fermée ;
et la condition doit être **atteignable sur la grille réellement parcourue**.
Une branche inatteignable qui mesure zéro n'est pas de la rareté, c'est un
câblage manquant.
**Test** : un cas avec position, plus un contrôle qui vérifie que l'heure de
sortie tombe sur une barre qui existe.

> Aujourd'hui : le seuil de sortie est postérieur à la dernière barre de la
> grille. La mise à plat ne peut **jamais** se déclencher. Le correctif n'est
> pas de déplacer le seuil pour qu'il tombe bien — ce serait un réglage sur les
> données — mais de décider si la sortie s'exprime sur la **dernière barre
> disponible** plutôt que sur une heure d'horloge.

### 8. Journal de qualité d'exécution dès le premier ordre

Un avantage de quelques ticks détruit par le glissement est un avantage mort,
et personne ne le voit si personne ne le mesure.

**Critère** : chaque ordre écrit le prix visé, le prix obtenu, l'écart en ticks
et en ATR, le délai entre la décision et l'envoi, le délai entre l'envoi et le
fill, et le motif de tout rejet.
**Test** : un ordre simulé produit une ligne portant les six champs.

> Le retard mesuré hors ligne vaut identiquement zéro : l'émission y est posée
> à l'instant de référence. **La latence n'existe qu'en live** — c'est la seule
> grandeur que les 61 jours ne produiront pas sans ce journal.

### 9. Plan de retour arrière

**Critère** : une commande documentée qui arrête tout, met à plat et laisse le
système dans un état lisible ; plus la procédure pour revenir à la version
précédente.
**Test** : la procédure a été exécutée une fois, à froid.

---

## Ce que cette liste ne couvre PAS

Elle ne dit rien sur la question de savoir si la stratégie gagne. C'est le
travail de la campagne, et il est scellé jusqu'au terme.

Un bot qui coche les neuf points peut parfaitement perdre de l'argent — mais il
perdra ce qu'on a décidé de risquer, au rythme qu'on a choisi, et on saura
pourquoi. C'est la seule chose que l'ingénierie peut garantir ; le reste est du
ressort de la mesure.

---

## Comment on s'en sert

Un point passe au vert quand son test existe, qu'il est vert, **et qu'on a vu
son test échouer** en cassant volontairement ce qu'il garde. Un test qui n'a
jamais échoué n'a rien prouvé : c'est la leçon du 12/09, où deux contrôles
centraux passaient avec le code cassé.

Une régression sur un point vert arrête le bot. Pas « on note et on continue ».
