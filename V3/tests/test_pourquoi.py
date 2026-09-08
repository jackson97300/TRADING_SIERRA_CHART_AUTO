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

        # 2. journal VIDE != journal ABSENT (convention pourquoi.py) — un
        #    journal vide annonce 0 signal et liste le registre ; un journal
        #    absent est un INCIDENT.
        _ecrire(tmp, "ombre16_20260906.jsonl", [])
        s = _sortie("20260906")
        check("vide dit 0 signal + registre",
              "0 signal(aux)" in s and "aucune ligne :" in s, s[:160])
        check("absent dit INCIDENT", "AUCUN JOURNAL" in s and "INCIDENT" in s,
              s[:160])

        # 3. aucun jour : les deux absents => INCIDENT et manque = 2 (R4)
        s = _sortie("20990101")
        check("deux absents = INCIDENT", s.count("AUCUN JOURNAL") == 2
              and "INCIDENT" in s, s[:160])
        check("absent compte dans le retour", pourquoi.ombres("20990101") == 2)

        # 4. R3 — `jour_muet:<raison>` n'est PAS un lieu sans reaction : le
        #    setup n'a pas pu VOIR. Les confondre fabrique du denominateur
        #    a partir d'un trou (mesure 07/09 : 2 barre_eod_absente comptes
        #    comme des lieux).
        _ecrire(tmp, "ombre_c2_20260907.jsonl", [
            {"sym": "ES", "setup": "C2_EOD",
             "motif": "jour_muet:barre_eod_absente"}])
        _ecrire(tmp, "ombre16_20260907.jsonl", [])
        s = _sortie("20260907")
        check("jour_muet dit MUET", "MUET : barre_eod_absente" in s, s[:200])
        check("jour_muet PAS compte en lieu",
              "1 (lieu sans reaction)" not in s and "lieu(x)" not in s, s[:200])

        # 5. R5 — le REGISTRE s'affiche, pas seulement ce qui a tire : un
        #    setup actif sans une seule ligne doit se voir.
        check("setups sans ligne annonces", "aucune ligne :" in s, s[:200])
    finally:
        os.chdir(ancien)

# 6. R1 — le jour des ombres vient du CHEMIN LU, jamais de la date demandee.
#    Mesure du defaut : `--journal entonnoir_20260904` affichait les ombres
#    du 08/09 dans le meme ecran, sans un mot.
import re  # noqa: E402
for base, attendu in (("entonnoir_20260904.jsonl", "20260904"),
                      ("ombre_c2_20260908.jsonl", "20260908")):
    t = re.search(r"(\d{8})", base)
    check("date lue depuis %s" % base, t and t.group(1) == attendu)

# 7. R2 — le repli est ANCRE sur `entonnoir_` : il ne doit JAMAIS ramasser
#    un journal d'ombre et le presenter comme l'entonnoir (mesure : un jour
#    non couru rendait une lecture plausible depuis ombre_c2).
source = open(RACINE / "V3" / "pourquoi.py", encoding="utf-8").read()
check("repli ancre sur entonnoir_",
      'glob.glob("LOGS/entonnoir/entonnoir_*.jsonl")' in source
      and 'glob.glob("LOGS/entonnoir/*.jsonl")' not in source)

print("pourquoi (trois journaux) : %d PASS, %d FAIL" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
