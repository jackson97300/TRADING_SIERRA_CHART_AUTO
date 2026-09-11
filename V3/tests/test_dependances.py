"""V3 — LE MANIFESTE DES DEPENDANCES : ce que V3 importe vraiment de CORE.

    python -X utf8 V3/tests/test_dependances.py
    python -X utf8 V3/tests/test_dependances.py --manifeste   # ecrit MANIFESTE_CORE.txt

NE DE L'OPERATION DU 11/09 : le deploiement de V3 sur le VPS a echoue deux fois
parce que `CORE.entonnoir` et `CORE.research.semantic_check_fable` n'etaient
dans AUCUNE liste — ni dans une doc, ni dans un script de deploiement. A chaud,
ils auraient casse A L'EXECUTION, lundi, en seance. Un bac isole les a montres
a froid. La lecon : **on ne connaissait pas la liste des dependances de V3**.

Ce test la GENERE (il ne la recopie pas) et verifie trois choses :
  1. tout module `CORE.*` de la FERMETURE TRANSITIVE (V3 -> CORE -> CORE...)
     EXISTE sur le disque — les dependances des dependances comprises ;
  2. il est IMPORTABLE dans cet environnement (c'est le test qui compte sur le
     VPS : un import qui marche ici peut echouer la-bas) ;
  3. le manifeste ecrit sur disque est a jour — sinon il dit lequel a bouge.
Il tourne dans la suite, donc sur le VPS avant chaque bascule : une dependance
oubliee ne peut plus etre decouverte en seance.

Ce qu'il ne fait pas : deviner les imports dynamiques (`importlib`, `__import__`
construit). Il n'y en a pas dans V3 aujourd'hui ; le jour ou il y en a, ce test
ne les verra pas et c'est ecrit ici pour que personne ne s'y fie aveuglement.
"""
import ast
import importlib
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

MANIFESTE = RACINE / "V3" / "MANIFESTE_CORE.txt"
PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-68s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def sur_disque(mod):
    """`CORE.features.recalc` -> le .py existe-t-il (module ou paquet) ?"""
    base = RACINE / Path(mod.replace(".", "/"))
    return (base.with_suffix(".py")).exists() or (base / "__init__.py").exists() or base.is_dir()


def modules_importes_fichier(p):
    """Les modules `CORE.*` importes par UN fichier — lus dans l'AST, jamais par
    regex : `# from CORE.x import y` en commentaire ne compte pas, et
    `from CORE import a, b` donne bien deux modules."""
    trouves = {}
    if True:
        try:
            arbre = ast.parse(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError) as e:
            trouves.setdefault("!SYNTAXE:%s" % p, set()).add(str(e))
            return trouves
        for n in ast.walk(arbre):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "CORE":
                # `from CORE.research import hypotheses` importe le SOUS-MODULE
                # `CORE.research.hypotheses`, pas seulement le paquet. Ne retenir
                # que le paquet, c'est le defaut qui a fait echouer le deploiement
                # du 11/09 (`semantic_check_fable` invisible). On resout chaque nom
                # importe : si `<module>/<nom>.py` existe, c'est un sous-module.
                for a in n.names:
                    candidat = "%s.%s" % (n.module, a.name)
                    if sur_disque(candidat):
                        trouves.setdefault(candidat, set()).add(str(p))
                if n.module != "CORE":
                    trouves.setdefault(n.module, set()).add(str(p))
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] == "CORE":
                        trouves.setdefault(a.name, set()).add(str(p))
    return trouves


def modules_importes(dossier="V3"):
    """Idem sur tout un dossier."""
    trouves = {}
    for p in sorted(Path(dossier).rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        for m, src in modules_importes_fichier(p).items():
            trouves.setdefault(m, set()).update(src)
    return trouves


def fermeture(trouves):
    """Les dependances des dependances. `hypothesis_runner` importe
    `semantic_check_fable` : un deploiement qui n'envoie que ce que V3 importe
    DIRECTEMENT echoue a l'import — c'est l'erreur exacte du 11/09, deux fois.
    On suit la chaine jusqu'au point fixe."""
    vus, a_voir = dict(trouves), [m for m in trouves if not m.startswith("!")]
    while a_voir:
        mod = a_voir.pop()
        base = RACINE / Path(mod.replace(".", "/"))
        fichiers = [base.with_suffix(".py")] if base.with_suffix(".py").exists() else (
            [base / "__init__.py"] if (base / "__init__.py").exists() else [])
        for f in fichiers:
            for m2, src in modules_importes_fichier(f).items():
                if m2 not in vus:
                    vus[m2] = set()
                    a_voir.append(m2)
                vus[m2] |= src
    return vus


def main(argv):
    trouves = fermeture(modules_importes())
    casses = {m: v for m, v in trouves.items() if m.startswith("!SYNTAXE")}
    mods = sorted(m for m in trouves if not m.startswith("!"))
    check("[0] aucun fichier V3 illisible par l'analyseur", not casses, list(casses)[:2])
    print("     %d module(s) CORE importe(s) par V3 :" % len(mods))
    for m in mods:
        print("       %-42s <- %d fichier(s)" % (m, len(trouves[m])))

    manquants = [m for m in mods if not sur_disque(m)]
    check("[1] tout module CORE importe par V3 EXISTE sur le disque", not manquants, manquants)

    non_importables = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:                              # noqa: BLE001 — on VEUT le nom de l'echec
            non_importables.append("%s (%s: %s)" % (m, type(e).__name__, str(e)[:60]))
    check("[2] tout module CORE importe par V3 est IMPORTABLE dans CET environnement",
          not non_importables, non_importables[:3])

    lignes = ["# MANIFESTE des modules CORE dont V3 depend — GENERE par",
              "# V3/tests/test_dependances.py, jamais ecrit a la main.",
              "# Fermeture TRANSITIVE : V3 -> CORE -> CORE. C'est la liste a envoyer",
              "# avec V3 au deploiement, et rien d'autre.",
              ""] + mods
    texte = "\n".join(lignes) + "\n"
    if "--manifeste" in argv:
        MANIFESTE.write_text(texte, encoding="utf-8", newline="\n")
        print("     manifeste ecrit : %s" % MANIFESTE)
    check("[3] le manifeste sur disque est a jour (sinon : --manifeste)",
          MANIFESTE.exists() and MANIFESTE.read_text(encoding="utf-8") == texte,
          "absent" if not MANIFESTE.exists() else "perime")

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
