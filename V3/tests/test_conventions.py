"""LE REGISTRE DES CONVENTIONS EST-IL ENCORE VRAI ? — et rien ne lui echappe.

    python -X utf8 V3/tests/test_conventions.py

Le registre est `V3/conventions.yaml`, ses controles vivent dans
`V3/conventions.py`, et ce fichier n'est que le lanceur. Le POURQUOI — la cle
`d_vwap_w` calculee sans negation le 14/09, et les quatre erreurs de reference
commises dans l'audit lui-meme — est ecrit en tete de `V3/conventions.py`.

DEUX ROLES, et le second compte autant que le premier :

  1. VERIFIER chaque convention declaree contre une grandeur reconstruite
     depuis le prix ou le volume bruts ;
  2. REFUSER qu'une colonne entre dans V3 sans etre au registre. C'est le
     cliquet — celui qui aurait tue le bug du 14/09 avant qu'il n'existe.

PROUVE PAR SABOTAGE le 14/09, cinq sur cinq : signe de famille retourne, unite
fausse, valeur discrete inattendue toleree, colonne lue retiree du registre, et
colonne NOUVELLE lue sans entree. Chacun fait echouer ce fichier.

Aucun devenir n'est lu : on ne compare que des colonnes d'entree entre elles.
"""
from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)
os.chdir(RACINE)

from V3 import conventions as C                                  # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-70s %s %s" % (nom[:70], "PASS" if ok else "FAIL", "" if ok else detail))


def main():
    colonnes, familles = C.charger()
    print("\n[0] le registre se lit")
    check("[0a] `V3/conventions.yaml` declare des colonnes", bool(colonnes),
          "registre vide : ce test ne garderait plus rien")
    check("[0b] chaque entree declare un controle",
          all("controle" in (e or {}) for e in colonnes.values()),
          sorted(k for k, e in colonnes.items() if "controle" not in (e or {})))

    # LES DEUX INSTRUMENTS, ET LEURS VERDICTS CONFRONTES. Une convention
    # verifiee sur ES seul ne dit rien de NQ : le depot a deja paye d'avoir
    # calibre sur un instrument et applique a l'autre (66,7 % des features ont
    # un ecart ES/NQ superieur a x1,5). Mesure du 14/09 : 17 controles, ZERO
    # divergence — mais c'est un fait a garder, pas une propriete acquise.
    verdicts, jours_par_sym, muets = {}, {}, []
    for sym in ("ES", "NQ"):
        jours = jours_par_sym[sym] = C.lots(sym)
        print("\n[1-%s] les conventions declarees, sur %d jours d'archive"
              % (sym, len(jours)))
        check("[1a-%s] au moins trois jours d'archive lisibles" % sym,
              len(jours) >= 3,
              "sans donnee, ce test ne prouve RIEN et doit echouer")
        v = verdicts[sym] = {}
        for nom in sorted(colonnes) if jours else []:
            e = colonnes[nom] or {}
            f = C.CONTROLES.get(e.get("controle"))
            if f is None:
                continue
            ok, detail = f(nom, e, familles, jours)
            v[nom] = ok
            if ok is None:
                muets.append("%s/%s (%s)" % (sym, nom, detail))
                continue
            check("[1-%s] %s — %s" % (sym, nom, e["controle"]), ok, detail)
    check("[1z] au plus quatre controles restent muets faute de donnee",
          len(muets) <= 4, muets)

    print("\n[1x] les deux instruments s'accordent sur chaque convention")
    divergentes = [n for n in set(verdicts.get("ES", {})) | set(verdicts.get("NQ", {}))
                   if verdicts.get("ES", {}).get(n) != verdicts.get("NQ", {}).get(n)]
    check("[1x] aucun verdict ne differe entre ES et NQ", not divergentes,
          "divergentes : %s" % sorted(divergentes))

    jours = jours_par_sym.get("ES") or []

    print("\n[2] le cliquet — aucune colonne lue hors registre")
    lues = C.colonnes_lues_par_v3()
    reelles = set()
    for _j, dfe, brut in jours:
        reelles |= set(dfe.columns) | set(brut.columns)
    inconnues = {c: f for c, f in lues.items()
                 if c in reelles and c not in colonnes}
    check("[2a] toute colonne lue par V3 est au registre", not inconnues,
          ", ".join("%s (%s)" % (c, ", ".join(sorted(f)))
                    for c, f in sorted(inconnues.items())))
    check("[2b] le scan a vraiment trouve des accesseurs", len(lues) >= 10,
          "%d accesseurs — le cliquet ne garde plus rien" % len(lues))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
