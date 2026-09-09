"""LE RYTHME DU SOIR — la séquence de 21:01 UTC, en une commande.

    python -X utf8 V3/execution/rythme_soir.py [YYYYMMDD]

Cinq étapes, dans l ordre, chacune sur la MÊME journée :

    1. `campagne.py`         le rejeu officiel — LA mesure (strict=False)
    2. `pourquoi.py`         où chaque signal s'est arrêté, les TROIS journaux
    3. `reactions.py`        ce que le marché a fait aux 17 niveaux
    4. `barrieres_du_jour`   les trois SL candidats par signal (B-ATR/NIV/NAT)
    5. `marges.py`           de combien une condition a manque (la puissance)

LIMITE CONNUE DE L'ÉTAPE 4, mesurée le 08/09 : `barrieres_du_jour` ne voit
que les signaux de `signaux_l3` — LES QUATRE gelées. Les seize ED et les C2
actifs n'ont donc AUCUNE barrière, alors que ce sont eux qui tirent (9
signaux le jour 1, tous hors des quatre). Le branchement est nécessaire
(règle 15 : un module écrit mais pas couru n'existe pas) et INSUFFISANT :
tant que les barrières ne couvrent pas les ombres, la campagne journalise
des entrées sans sorties. Étendre = un chantier, pas un branchement.

Le journal MANUEL de Jackson reste à écrire à la main — c'est le seul
maillon que la machine ne remplace pas (METHODE §6).

POURQUOI UNE SÉQUENCE ET PAS TROIS TÂCHES : elles doivent porter sur la MÊME
journée. Trois tâches indépendantes, lancées à trois instants, peuvent tomber
de part et d'autre de la bascule de 22:00 UTC et mesurer deux jours
différents sans que rien ne le signale.

PIÈGE DST — À LIRE AVANT LE 25/10/2026 : la tâche planifiée Windows tourne en
heure LOCALE. 23:01 Paris = 21:01 UTC en heure d'été SEULEMENT. Après le
changement d'heure (25/10, DANS la campagne), sans déplacer la tâche à 22:01
locale, la séquence tournera une heure PLUS TARD mais — depuis le fix du
09/09, jour résolu UNE FOIS en UTC — sur le BON jour : 22:01 UTC reste dans
la fenêtre et avant minuit. Le refus hors fenêtre ne garde plus que le vrai
danger restant : un lancement sans argument après minuit UTC.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
FENETRE_UTC = (20, 45), (23, 30)     # bornes larges : un retard n'est pas une faute


def _dans_la_fenetre(maintenant):
    (h0, m0), (h1, m1) = FENETRE_UTC
    return (h0 * 60 + m0) <= (maintenant.hour * 60 + maintenant.minute) <= (h1 * 60 + m1)


def _etape(nom, args):
    print("\n=== %s ===" % nom, flush=True)
    r = subprocess.run([sys.executable, "-X", "utf8", *args], cwd=RACINE)
    if r.returncode:
        print("  (%s sort en %d — la sequence continue)" % (nom, r.returncode))
    return r.returncode


def main():
    jour = sys.argv[1] if len(sys.argv) > 1 else None
    maintenant = datetime.now(timezone.utc)
    print("RYTHME DU SOIR — %s UTC" % maintenant.isoformat(timespec="seconds"))
    if jour is None and not _dans_la_fenetre(maintenant):
        print("HORS FENETRE (%02d:%02d UTC, attendu %02d:%02d-%02d:%02d).\n"
              "  Changement d'heure ? La tache planifiee est en heure LOCALE.\n"
              "  Rien n'a tourne — relancer avec un jour explicite si voulu."
              % (maintenant.hour, maintenant.minute,
                 *FENETRE_UTC[0], *FENETRE_UTC[1]))
        return 2
    # UN SEUL jour, resolu UNE FOIS (audit 09/09) : sans argument, les etapes
    # 1 et 4 prenaient dernier_jour() (le fichier du LENDEMAIN apparait des
    # 22:00 UTC via le coureur) et les etapes 2, 3, 5 prenaient utcnow() —
    # la meme sequence mesurait DEUX journees, et l'etape 1 pouvait rejouer
    # (et ecraser) un jour a peine commence.
    if jour is None:
        jour = datetime.now(timezone.utc).strftime("%Y%m%d")
        print("  jour resolu : %s (UTC, une fois pour les cinq etapes)" % jour)
    args = [jour]
    codes = [
        # Etape 0 (Fable C4, 09/09) : L6 n'avait AUCUN producteur quotidien —
        # dernier verdict du 04/09, et L0_DATA_L6_ALERTE (appliquee) a bloque
        # 84 battements du jour 1 sur un verdict de 4 jours. Observateur pur.
        _etape("0/5 surveillance L6", ["CORE/research/surveillance_l6.py",
                                       *args]),
        _etape("1/5 campagne (LA mesure)", ["V3/campagne.py", *args]),
        _etape("2/5 pourquoi (les trois journaux)", ["V3/pourquoi.py", *args]),
        _etape("3/5 reactions (les niveaux)", ["V3/reactions.py", *args]),
        _etape("4/5 barrieres (les SL candidats)",
               ["V3/layers/L5_risque/barrieres_du_jour.py", *args]),
        _etape("5/5 marges (la distance au seuil)", ["V3/marges.py", *args]),
        # Brique 2 (Fable 09/09) : la marge des QUATRE — de combien le lieu a
        # manque, et lequel des deux manquait. Observateur pur, journal separe.
        _etape("5b/5 marges des quatre (le lieu manque)",
               ["V3/marges_quatre.py", *args]),
    ]
    print("\n--- fait. Reste le JOURNAL MANUEL (METHODE 6) — la machine ne "
          "l'ecrit pas.")
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main())
