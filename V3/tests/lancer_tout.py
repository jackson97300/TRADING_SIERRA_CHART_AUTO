"""TOUS les tests de V3, DECOUVERTS et non listes.

    python -X utf8 V3/tests/lancer_tout.py
    python -X utf8 V3/tests/lancer_tout.py --rapide   (saute les lents)

POURQUOI CE FICHIER EXISTE
--------------------------
Mesure du 15/09 : `V3/` contenait **48 fichiers `test_*.py`, dont 32 que
`publier.sh` ne lancait pas** — parmi eux `test_conventions.py`, le cliquet
qui interdit qu'une colonne entre dans V3 sans passer par le registre, rendu
souverain la veille. Un garde-fou qui ne tourne pas ne garde rien.

La cause n'est pas un oubli, c'est la FORME : une liste ecrite a la main dans
un script se desynchronise du dossier des qu'on ajoute un fichier, et personne
ne s'en apercoit parce que tout reste vert. Ce lanceur DECOUVRE les tests au
lieu de les lister. Le prochain test cree tournera sans que personne y pense.

L'ORDRE N'EST PAS ALPHABETIQUE, et c'est voulu : `TETE` porte les controles
qui echouent vite et cher (les portes, la causalite, les secrets). Le reste
suit. On veut apprendre tot qu'on a casse quelque chose de grave.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V3 = os.path.join(RACINE, "V3")

# Les plus critiques d'abord — un echec ici doit tomber en moins d'une minute.
TETE = (
    "layers/L0_interrupteur/test_portes.py",
    "layers/L0_interrupteur/test_faux_live.py",
    "tests/test_dependances.py",
    "tests/test_structure.py",
    "tests/test_conventions.py",
    "layers/L1_biais/test_biais.py",
    "tests/test_causalite.py",
    "tests/test_calendrier.py",
    "tests/test_f23.py",
)

# Tests qui prennent plus d'une minute. `--rapide` les saute — et le dit.
# Ne JAMAIS s'en servir avant une publication : publier est irreversible.
LENTS = (
    "tests/test_conventions.py",
    "tests/test_causalite.py",
    "tests/test_f23.py",
)


def _decouvrir():
    """Tous les `test_*.py` sous V3/, chemins relatifs a V3/, TETE d'abord."""
    trouves = []
    for dossier, _sous, fichiers in os.walk(V3):
        for f in fichiers:
            if f.startswith("test_") and f.endswith(".py"):
                rel = os.path.relpath(os.path.join(dossier, f), V3)
                trouves.append(rel.replace(os.sep, "/"))
    tete = [t for t in TETE if t in trouves]
    manquants = [t for t in TETE if t not in trouves]
    reste = sorted(set(trouves) - set(tete))
    return tete + reste, manquants


def main():
    rapide = "--rapide" in sys.argv
    tests, manquants = _decouvrir()
    if manquants:
        print("  REFUS : %d test(s) de TETE introuvable(s) : %s"
              % (len(manquants), ", ".join(manquants)))
        print("  Un test renomme ou supprime doit l'etre SCIEMMENT — pas en "
              "silence. Corrige TETE dans ce fichier.")
        return 1

    echecs, sautes, t0 = [], [], time.time()
    print("  %d tests decouverts sous V3/%s\n"
          % (len(tests), "  (mode --rapide)" if rapide else ""))
    for rel in tests:
        if rapide and rel in LENTS:
            sautes.append(rel)
            print("     SAUTE  %s" % rel)
            continue
        d = time.time()
        r = subprocess.run([sys.executable, "-X", "utf8",
                            os.path.join(V3, rel.replace("/", os.sep))],
                           cwd=RACINE, capture_output=True, text=True)
        s = time.time() - d
        if r.returncode == 0:
            print("     ok     %-52s %5.1fs" % (rel, s))
        else:
            print("     ECHEC  %-52s %5.1fs" % (rel, s))
            queue = (r.stdout or r.stderr or "").strip().splitlines()[-6:]
            echecs.append((rel, queue))

    print("\n  %d verts / %d echecs / %d sautes — %.0fs au total"
          % (len(tests) - len(echecs) - len(sautes), len(echecs),
             len(sautes), time.time() - t0))
    if sautes:
        print("  ATTENTION : %d test(s) saute(s). `--rapide` est INTERDIT "
              "avant une publication." % len(sautes))
    for rel, queue in echecs:
        print("\n  --- %s ---" % rel)
        for l in queue:
            print("      %s" % l)
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
