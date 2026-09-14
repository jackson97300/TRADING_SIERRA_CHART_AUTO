"""Les comptes de simulation — lus, jamais devines, jamais dans le depot.

Extrait de `exec_sim.py` le 13/09 : ce fichier etait au plafond des 300 lignes
et ce bloc n'a rien a voir avec l'execution d'un ordre. La regle du depot dit
« si c'est plus long, extraire un sous-module » — pas « raboter les
commentaires ».

LES NOMS DE COMPTES NE SONT NULLE PART DANS LE CODE. Ils vivent dans
`V3/config/comptes.local.yaml`, ignore par git. Un nom de compte de trading n'a
rien a faire dans un depot public, meme simule — le jour ou il passe en reel,
il serait deja expose. Le garde-fou du miroir refuse d'ailleurs le motif
`\\bSim[1-9]\\b` dans tout fichier publie.

Ici on ne garde que la FORME admise : un compte de SIMULATION Sierra, et rien
d'autre. Tout autre nom leve a la construction d'EXEC — un bot qui devine un
nom de compte est un bot qui peut trader sur le mauvais.
"""

from __future__ import annotations

import os
import re
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

MOTIF_COMPTE_SIM = re.compile(r"^%s[0-9]$" % "Sim")


def charger_comptes(chemin=None):
    """`config/comptes.local.yaml` -> {sym: compte}. Absent = on ne trade pas :
    EXEC ne devine JAMAIS un nom de compte."""
    import yaml
    p = chemin or os.path.join(RACINE, "V3", "config", "comptes.local.yaml")
    if not os.path.exists(p):
        raise FileNotFoundError(
            "comptes.local.yaml absent — copier comptes.example.yaml et le renseigner. "
            "EXEC ne devine pas un nom de compte.")
    cfg = yaml.safe_load(open(p, encoding="utf-8")) or {}
    comptes = {sym: cfg.get("COMPTE_%s" % sym) for sym in ("ES", "NQ")}
    manquants = [s for s, c in comptes.items() if not c]
    if manquants:
        raise ValueError("comptes.local.yaml : COMPTE_%s manquant" % ", COMPTE_".join(manquants))
    return comptes
