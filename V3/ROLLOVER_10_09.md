# ROLLOVER 10/09 — préparé la veille, à décider vite à l'ouverture

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
