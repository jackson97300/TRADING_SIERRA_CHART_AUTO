"""LA FRAICHEUR DU CODE — le serveur tourne-t-il sous ce qui est sur le disque ?

Un serveur Python charge son code UNE fois, au demarrage, et le garde en
memoire. Le HTML, lui, est relu a chaque requete. Les deux derivent donc
separement, et rien ne le signale.

MESURE DU 11/09, c'est ce qui a fait naitre ce fichier. Le processus de la
vitrine avait demarre a 14h59 ; `vitrine.py` avait ete modifie a 17h13 ;
`/etat.json` ne portait toujours pas les deux ages ajoutes entre-temps. Le
JavaScript neuf les demandait, recevait `undefined`, et affichait « donnee : — »
en permanence. Aucune erreur, nulle part. La page se rechargeait toute seule,
ce qui donnait l'illusion d'un systeme a jour : la moitie l'etait.

Le controle tient en deux valeurs : l'empreinte du code AU DEMARRAGE, figee a
l'import, et l'empreinte du code MAINTENANT, lue sur le disque. Si elles
different, le processus est perime et seul un redemarrage y change quelque
chose — recharger la page n'y peut rien, et c'est pour ca que la page le DIT
au lieu de boucler.
"""

from __future__ import annotations

import hashlib
import os

DOSSIER = os.path.dirname(os.path.abspath(__file__))


def empreinte_code(dossier=DOSSIER):
    """Le hash des `.py` du dossier, nom compris — un fichier RENOMME compte
    comme un changement. Rend douze caracteres : de quoi distinguer deux etats
    du code, pas de quoi servir de preuve cryptographique."""
    h = hashlib.sha256()
    for nom in sorted(os.listdir(dossier)):
        if nom.endswith(".py"):
            with open(os.path.join(dossier, nom), "rb") as f:
                h.update(nom.encode("utf-8"))
                h.update(f.read())
    return h.hexdigest()[:12]


# Fige a l'import : c'est l'empreinte du code REELLEMENT charge en memoire.
EMPREINTE_DEMARRAGE = empreinte_code()


def perime():
    """Le code du disque a-t-il change depuis le demarrage de ce processus ?"""
    return empreinte_code() != EMPREINTE_DEMARRAGE


def etat():
    """Ce que `/version` publie : l'empreinte de demarrage et le verdict."""
    return {"serveur": EMPREINTE_DEMARRAGE, "serveur_perime": perime()}
