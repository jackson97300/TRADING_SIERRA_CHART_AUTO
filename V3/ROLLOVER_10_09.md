# ROLLOVER 10/09 — préparé la veille, à décider vite à l'ouverture

> **DÉCIDÉ le 10/09 à 10h01 Paris : LIGNE B.** ES 480 / NQ 481 lignes du
> 10/09, 100 % U26 (la nuit Globex), `contrat_actif` = Z26 → `L0_CONTRAT_INACTIF`
> observée pour le 10/09 (seuils.yaml). Reste : (1) redémarrer le coureur live
> à 15h15 (il a l'ancien YAML en mémoire) ; (2) ce soir, l'heure de bascule et
> `max(atr_barre)` ; (3) le 11/09 au matin, si le fichier ouvre en Z26 →
> remise `appliquee` + une ligne DECISIONS ; (4) ton clic MANUEL : U26 ou Z26 ?

*La décision se prend en une minute : lire le contrat des 3 premières barres du
10/09, garder la bonne ligne DECISIONS, noter l'heure. C'est la mesure qui dira
si « 3e vendredi − 8 jours » est l'horloge de **Sierra** ou seulement celle du
**CME** (le volume peut basculer avant/après le calendrier).*

## État de départ (mesuré le 09/09)
- **ES 09/09 = `ESU26-CME`**, **NQ 09/09 = `NQU26-CME`** — encore U26 (correct, le
  roll est le 10/09).
- `calendrier.contrat_actif('20260910')` = **`Z26`** → à partir du 10/09 INCLUS,
  le calendrier attend Z26. Si le fichier reste U26, `L0_CONTRAT_INACTIF`
  (fichier ≠ `contrat_actif`) se déclenche.

## La commande (à lancer à l'ouverture)
```bash
for sym in ES NQ; do
  f=$(ls DATA/live_enriched/sierra/$sym/20260910*.jsonl 2>/dev/null | head -1)
  [ -z "$f" ] && { echo "  $sym : pas encore de fichier 10/09"; continue; }
  python -X utf8 -c "import json; L=[l for l in open(r'$f',encoding='utf-8',errors='ignore') if l[:1]=='{'][:3]; print('  $sym 10/09 :', ' | '.join(str(json.loads(l).get('contract')) for l in L))"
done
```

## Les deux lignes DECISIONS — garder UNE, remplacer `<heure>`

**A) Sierra a basculé (fichier = Z26 à l'ouverture) :**
```
| 10/09 | Sierra a basculé sur Z26 à <heure> — `CONTRAT_INACTIF` RESTE appliquée (fichier = calendrier, aucun trou) | le roll « 3e vendredi − 8 jours » est AUSSI l'horloge de Sierra, pas seulement du CME | 3 premières barres 10/09 = Z26 (ES/NQ) |
```

**B) Fichier encore U26 à l'ouverture :**
```
| 10/09 | U26 à l'ouverture alors que `contrat_actif` dit Z26 — `CONTRAT_INACTIF` passe OBSERVÉE pour le 10/09, remise APPLIQUÉE à <heure> quand le fichier porte Z26 | le roll calendaire est celui du CME, pas de Sierra : le fichier suit le volume, pas la date. Bloquer toute la séance sur un décalage d'horloge serait un faux TROU | 3 premières barres 10/09 = U26 ; bascule fichier vers Z26 mesurée à <heure> |
```

## Le geste
1. Lancer la commande.
2. U26 → **B** (rendre `CONTRAT_INACTIF` observée dans `seuils.yaml` L0 pour le
   10/09) ; Z26 → **A** (rien à changer).
3. Noter l'heure de bascule si elle arrive en séance.
4. **Trace trader (Jackson)** : le clic MANUEL du matin — noté U26 ou Z26 ? Le
   jour 61 ne peut pas le reconstruire sans toi.

## Ajouts de la review (nuit du 09→10/09, brique 1 `atr_ref`)

- **(c) `contrat_ok` juge la PREMIÈRE ligne du fichier** (U26 la nuit si Sierra
  bascule en séance) → `L0_CONTRAT_INACTIF` (appliquée) bloquerait **100 % du
  rejeu du 10/09** — jour 3 muet par construction. C'est exactement la ligne
  **B** : à décider à l'ouverture, pas à 23h01.
- **(a) L6 `echelle_atr`** : un changement de contrat entre la veille et le
  jour rend `motif = rollover` (gap de BASE U26→Z26, ~40-60 pts ES ≈ 4-6
  ATR-veille — pas un gap de marché), hors règle 15, jamais ALERTE.
- **(b) Contrôle du SOIR 10/09** : si la bascule tombe DANS le cash, le bin
  15 min qui la contient a un TR de la taille de la base → `atr_barre` du
  10/09 et **`atr_veille` du 11/09** pollués (le 10/09 restera « complet » en
  bins). À lire à 22h : l'heure de bascule dans le fichier (la ligne où
  `contract` change) et `max(atr_barre)` du jour contre sa médiane. Si
  pollué → le 11/09 lit `atr_source = veille` avec un caveat écrit dans
  DECISIONS, et `atr_veille_15` reçoit son critère « un seul contrat par
  session » au prochain commit.
