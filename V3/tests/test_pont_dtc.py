"""LE PONT VERS DTC — la traduction du cote, le chemin, et la non-divergence.

    python -X utf8 V3/tests/test_pont_dtc.py

CE QUE CE FICHIER EMPECHE, et les deux defauts sont du 14/09 :

**La traduction absente.** `exec_sim` passait `intent["side"]` TEL QUEL au
connecteur. V3 parle en +1 / -1, DTC en 1 / 2. Donc `BuySell = -1` partait sur
tout SHORT a l'entree et toute sortie de LONG. Le piege : **+1 vaut « long » en
V3 ET « BUY » en DTC**, donc la moitie des cas marchait par accident et cachait
l'autre. Et Sierra en serveur DTC **ignore silencieusement** ce qu'il ne
comprend pas — aucun refus, aucun log.

**L'import impossible.** `from BOT.dtc_connector import DTCConnector` levait
`ModuleNotFoundError: No module named 'bot_config'` : le connecteur fait un
import FRERE. Invisible pour toute la suite, l'import etant tardif et les tests
injectant un faux. EXEC aurait plante au premier tour reel.

Le POURQUOI complet vit dans `V3/execution/pont_dtc.py`. Ici, on verifie.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.execution import pont_dtc                            # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-70s %s %s" % (nom[:70], "PASS" if ok else "FAIL", "" if ok else detail))


def main():
    print("\n[1] la traduction du cote")
    check("[1a] long V3 (+1) -> BUY DTC (1)", pont_dtc.buysell(1) == 1)
    check("[1b] short V3 (-1) -> SELL DTC (2)", pont_dtc.buysell(-1) == 2)
    check("[1c] les deux sont DISTINCTS — sans quoi la traduction ne traduit rien",
          pont_dtc.buysell(1) != pont_dtc.buysell(-1))
    # +1 vaut « long » en V3 ET « BUY » en DTC : le long passe par accident.
    # C'est le SHORT qui revele la traduction, et lui seul.
    check("[1d] c'est le SHORT qui prouve la traduction : -1 ne reste PAS -1",
          pont_dtc.buysell(-1) != -1)

    print("\n[2] tout le reste leve — un cote intraduisible est une erreur de code")
    for mauvais in (0, 2, -2, None, "long", "L", 1.5, True, [1]):
        # `True == 1` en Python : il DOIT passer, et c'est voulu — un booleen
        # vrai est un entier egal a 1. On ne le compte pas comme un echec.
        if mauvais is True:
            continue
        try:
            pont_dtc.buysell(mauvais)
            ok = False
        except (ValueError, TypeError):
            ok = True
        check("[2] cote %r refuse, jamais devine" % (mauvais,), ok)

    print("\n[3] le chemin vers le connecteur qui TOURNE")
    chemin = pont_dtc.preparer_chemin()
    check("[3a] `BOT/` est bien ajoute au chemin", chemin in sys.path, chemin)
    # A LA FIN, jamais au debut : l'incident du 17/05 (DEPLOY_UNSAFE) a coute
    # une heure parce qu'un `insert(0, .../BOT)` masquait un module de `CORE/`
    # par une version vieille de cinq jours.
    check("[3b] et A LA FIN — en tete, il masquerait `CORE/` (incident 17/05)",
          sys.path.index(chemin) > 0 and chemin not in sys.path[:1], sys.path[:3])
    check("[3c] appele deux fois, il n'empile pas",
          sys.path.count(chemin) == 1, sys.path.count(chemin))

    print("\n[4] les constantes ne divergent pas de la source")
    src = pont_dtc.constantes_de_la_source()
    check("[4a] le connecteur qui tourne s'importe VRAIMENT", src is not None,
          "import impossible — EXEC planterait au premier tour reel")
    if src is not None:
        check("[4b] BUY/SELL du pont == ceux du connecteur vivant",
              (pont_dtc.BUY_DTC, pont_dtc.SELL_DTC) == src,
              ((pont_dtc.BUY_DTC, pont_dtc.SELL_DTC), src))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
