"""Le lecteur du soir doit voir les TROIS journaux — pas un sur trois.

Le défaut (08/09) : `pourquoi.py` n'ouvrait que `entonnoir_<jour>.jsonl` et
répondait « zéro signal » un jour où NEUF avaient tiré (4 ombre16 ES, 5 C2).
Sa propre docstring dit qu'une couche absente du résumé est un incident ;
deux couches sur trois y manquaient depuis le premier jour de campagne.

Ce test écrit trois journaux jouets et vérifie que chaque famille apparaît,
avec la distinction VIDE / ABSENT préservée.
"""
import io
import os
import sys
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from V3 import pourquoi  # noqa: E402

PASSED = 0
FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("  %-38s PASS" % nom)
    else:
        FAILED += 1
        print("  %-38s FAIL %s" % (nom, detail))


def _ecrire(dossier, nom, lignes):
    chemin = os.path.join(dossier, "LOGS", "entonnoir", nom)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as fh:
        for o in lignes:
            fh.write(json.dumps(o) + "\n")


def _sortie(jour):
    tampon = io.StringIO()
    with redirect_stdout(tampon):
        pourquoi.ombres(jour)
    return tampon.getvalue()


ancien = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    try:
        # 1. les trois familles presentes -> les trois visibles
        _ecrire(tmp, "ombre16_20260908.jsonl", [
            {"sym": "ES", "setup": "ED04_BUY_VPOC_RECLAIM", "side": 1},
            {"sym": "ES", "setup": "ED10_BUY_CVD_DIVERGENCE", "side": 1}])
        _ecrire(tmp, "ombre_c2_20260908.jsonl", [
            {"sym": "NQ", "setup": "C2_80PCT", "side": -1},
            {"sym": "NQ", "setup": "C2_80PCT", "motif": "lieu_sans_reaction"}])
        s = _sortie("20260908")
        check("ombre16 visible", "ED04_BUY_VPOC_RECLAIM" in s)
        check("C2 visible", "C2_80PCT" in s)
        check("signaux comptes", "2 signal(aux)" in s, s[:200])
        check("lieu sans reaction distingue",
              "lieu(x) sans reaction" in s and "1 (lieu sans reaction)" in s)

        # 2. journal VIDE != journal ABSENT (convention pourquoi.py)
        _ecrire(tmp, "ombre16_20260907.jsonl", [])
        s = _sortie("20260907")
        check("vide dit COURU", "journal VIDE" in s, s[:160])
        check("absent dit NON COURU", "AUCUN JOURNAL" in s, s[:160])

        # 3. aucun jour : les deux absents, aucune exception
        s = _sortie("20990101")
        check("deux absents sans crash", s.count("AUCUN JOURNAL") == 2, s[:160])
    finally:
        os.chdir(ancien)

print("pourquoi (trois journaux) : %d PASS, %d FAIL" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
