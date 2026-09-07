"""Parité SPEC L3 ↔ code tagué — la phrase « le code a raison » rendue inutile.

    python -X utf8 V3/tests/test_spec_l3.py

La SPEC dit : « si les deux divergent, le code tagué a raison et ce fichier se
corrige par commit ». Une divergence SILENCIEUSE est exactement ce que cette
phrase autorise (revue Fable du 07/09). Ce test lit les nombres du code
(`hypotheses.py`) et vérifie que la SPEC porte les mêmes : planchers P05-P20,
seuils de réaction 0,4/0,6, régimes 0,8/0,4, seuils H8p 1,8/0,18, les quatre
noms et les trois annoncées non testables.
"""

from __future__ import annotations

import inspect
import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.research import hypotheses as H                     # noqa: E402
from CORE.research.hypotheses_ed import LES_SEIZE             # noqa: E402

CHEMIN_SPEC = os.path.join(RACINE, "V3", "layers", "L3_declencheurs", "SPEC.md")
CHEMIN_OMBRE = os.path.join(RACINE, "V3", "layers", "L3_declencheurs", "OMBRE.md")


def main():
    spec = open(CHEMIN_SPEC, encoding="utf-8").read()
    echecs = []

    # 1. les planchers du code, dans la table de la SPEC
    attendus = {"P05": (0.05, 1.0), "P10": (0.10, 2.0),
                "P15": (0.15, 3.0), "P20": (0.20, 4.0)}
    if H.PLANCHERS != attendus:
        echecs.append("PLANCHERS du code ont bouge : %r" % H.PLANCHERS)
    for nom, (frac, ticks) in attendus.items():
        motif = "max(0,%02d ATR, %d tick" % (round(frac * 100), int(ticks))
        if motif not in spec:
            echecs.append("plancher %s : « %s » absent de la SPEC" % (nom, motif))

    # 2. les quatre, et les trois annoncees
    if set(H.LES_QUATRE) != {"H3-VPOC", "H2p", "H6p", "H8p"}:
        echecs.append("LES_QUATRE du code ont bouge : %r" % sorted(H.LES_QUATRE))
    if H.NON_TESTABLES_ANNONCEES != {"H2p", "H6p", "H8p"}:
        echecs.append("NON_TESTABLES_ANNONCEES ont bouge : %r"
                      % sorted(H.NON_TESTABLES_ANNONCEES))
    for nom in ("H3-VPOC", "H2p", "H6p", "H8p"):
        if nom not in spec:
            echecs.append("« %s » absent de la SPEC" % nom)

    # 3. les seuils numeriques des fonctions taguees, presents dans la SPEC
    # (source du code -> litteral attendu dans la prose, virgule francaise)
    controles = [
        (H.h3, "0.4", "0,4", "reaction finish de H3"),
        (H.h2_prime, "0.8", "0,8", "regime de H2p"),
        (H.h6_prime, "0.4", "0,4", "regime de H6p"),
        (H.h6_prime, "0.6", "0,6", "reaction finish de H6p"),
        (H.h8_prime, "1.8", "1,8", "rvol_r de H8p"),
        (H.h8_prime, "0.18", "0,18", "delta_pct de H8p"),
    ]
    for fn, dans_code, dans_spec, quoi in controles:
        if dans_code not in inspect.getsource(fn):
            echecs.append("%s : « %s » a disparu du code — la SPEC ment"
                          % (quoi, dans_code))
        if dans_spec not in spec:
            echecs.append("%s : « %s » absent de la SPEC" % (quoi, dans_spec))

    # 4. les SEIZE en ombre : la liste du miroir = LES_SEIZE du code
    ombre = open(CHEMIN_OMBRE, encoding="utf-8").read()
    for nom in LES_SEIZE:
        if nom not in ombre:
            echecs.append("« %s » absent d'OMBRE.md — le miroir ment" % nom)
    if len(LES_SEIZE) != 16:
        echecs.append("LES_SEIZE n'en compte pas seize : %d" % len(LES_SEIZE))

    # 5. REGLE 15 de METHODE : un pre-enregistrement sans coureur est un
    #    pre-enregistrement de rien. Le rejeu quotidien DOIT executer les
    #    deux jeux — les quatre (signaux_l3) et les seize (ombre16). C'est le
    #    test qui manquait le 07/09 : seize setups promis « des le 08/09 »
    #    et executes par personne, attrapes par une question, pas par un test.
    campagne_src = open(os.path.join(RACINE, "V3", "campagne.py"),
                        encoding="utf-8").read()
    for coureur, jeu in (("signaux_l3", "les quatre"),
                         ("ombre16", "les seize")):
        if coureur not in campagne_src:
            echecs.append("campagne.py n'execute plus « %s » (%s) — "
                          "pre-enregistrement sans coureur" % (coureur, jeu))

    print("  parite SPEC L3 <-> code — planchers, les quatre, %d seuils, "
          "les seize en ombre" % len(controles))
    if echecs:
        print("  %d DIVERGENCE(S) — corriger la SPEC par commit, le code "
              "tague a raison :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : la SPEC porte les nombres du code tague — aucune divergence")
    print("       silencieuse entre le miroir et ce qui court.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
