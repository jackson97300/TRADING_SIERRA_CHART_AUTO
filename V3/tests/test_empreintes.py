"""L'EMPREINTE DOIT BOUGER QUAND LE CODE BOUGE — sinon elle ne sert a rien.

    python -X utf8 V3/tests/test_empreintes.py

Une empreinte qui ne change pas quand le code change est pire qu'aucune
empreinte : elle certifie une continuite qui n'existe pas. C'est la meme
famille que les deux faux temoins du 12/09 — un controle qui ne peut pas
echouer sur ce qu'il garde.

Ce fichier teste donc la CAPACITE A DETECTER, pas seulement la presence de la
fonction : on modifie un fichier dans un dossier temporaire et on exige que
l'empreinte change.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3 import empreintes as E                                    # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def main():
    print("\n[1] l'empreinte distingue deux etats du code")
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.py")
        open(a, "w", encoding="utf-8").write("x = 1\n")
        h1 = E._hash_fichiers([a])
        check("[1a] un dossier lisible rend une empreinte", h1 is not None)
        check("[1b] deux appels sans changement rendent la MEME",
              E._hash_fichiers([a]) == h1)
        open(a, "w", encoding="utf-8").write("x = 2\n")
        h2 = E._hash_fichiers([a])
        check("[1c] un CONTENU qui change, une empreinte qui change", h2 != h1,
              (h1, h2))
        b = os.path.join(tmp, "b.py")
        os.rename(a, b)
        check("[1d] un fichier RENOMME compte comme un changement",
              E._hash_fichiers([b]) != h2)
        check("[1e] plus rien a lire rend None, jamais une empreinte de vide",
              E._hash_fichiers([os.path.join(tmp, "absent.py")]) is None)

    print("\n[2] le perimetre : ce qui DOIT etre couvert")
    core = E.fichiers_core()
    check("[2a] le manifeste CORE est lu et rend des fichiers", len(core) > 0, len(core))
    noms = {os.path.basename(c) for c in core}
    # `hypotheses.py` porte LES QUATRE hypotheses gelees ET le regime. Il
    # n'etait couvert par AUCUNE empreinte avant le 14/09 — trou trouve par le
    # module lui-meme, le dossier de la couche REG etant vide.
    check("[2b] `hypotheses.py` est couvert — il porte les quatre gelees",
          "hypotheses.py" in noms, sorted(noms))
    check("[2c] les tests sont EXCLUS du code d'une couche",
          not any(os.path.basename(f).startswith("test_")
                  for f in E._lister(str(RACINE / "V3" / "layers" / "L0_interrupteur"),
                                     (".py",))))

    print("\n[3] une ligne du jour se compose sans rien lire d'interdit")
    ligne = E.composer("20260101")
    check("[3a] la ligne porte le noyau, le core et les couches",
          {"jour", "ecrit_a", "noyau", "core", "couches"} <= set(ligne), sorted(ligne))
    check("[3b] chaque couche declaree a son entree",
          set(ligne["couches"]) == set(E.COUCHES), sorted(ligne["couches"]))
    plat = str(ligne)
    for mot in ("rendement", "pnl", "issue", "close", "high"):
        check("[3-%s] aucun « %s » dans la ligne — que des empreintes"
              % (mot[:4], mot), mot not in plat.lower())

    print("\n[4] `derives` voit un changement d'un jour a l'autre")
    # ON APPELLE LA VRAIE FONCTION. La premiere version de ce controle rejouait
    # la logique de `derives` a cote au lieu de l'invoquer : elle testait sa
    # propre copie. PROUVE le 14/09 — en vidant `derives` de sa comparaison des
    # couches, l'ancien [4a] passait encore. C'est la tautologie qu'on traque
    # depuis le 12/09, et je venais de la reecrire.
    import json as _json
    vrai_dossier = E.DOSSIER
    with tempfile.TemporaryDirectory() as tmp:
        E.DOSSIER = tmp
        try:
            for jour, code_l0 in (("20260101", "1"), ("20260102", "9")):
                d = {"jour": jour, "ecrit_a": "t", "noyau": "aaa", "core": "ccc",
                     "couches": {"L0": {"code": code_l0, "seuils": "2"},
                                 "L5": {"code": "5", "seuils": "6"}}}
                with open(os.path.join(tmp, "empreintes_%s.jsonl" % jour),
                          "w", encoding="utf-8") as fh:
                    fh.write(_json.dumps(d) + "\n")
            out = E.derives()
        finally:
            E.DOSSIER = vrai_dossier
    check("[4a] la couche dont le code a bouge est signalee, avec son jour",
          out.get("L0") == ["20260102"], out)
    check("[4b] la couche INCHANGEE ne l'est pas", "L5" not in out, out)
    check("[4c] ni le noyau ni le core, inchanges",
          "noyau" not in out and "core" not in out, out)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
