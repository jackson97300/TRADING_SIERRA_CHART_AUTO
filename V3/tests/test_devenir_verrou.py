"""LE VERROU DU DEVENIR — on ne doit PAS pouvoir lire avant le jour 61.

    python -X utf8 V3/tests/test_devenir_verrou.py

NE DE L'AUDIT DU 11/09. Jusque-la, « on ne regarde pas le devenir avant le jour
61 » etait une REGLE humaine. L'audit a montre que `pnl_atr` et `issue` sont
desormais ECRITS sur disque : le devenir du premier signal gele y est deja, et
rien n'empechait techniquement de l'ouvrir. Une porte fermee n'est pas une
porte verrouillee, et une regle se contourne un dimanche a 23h — exactement
quand elle compte le plus.

Ce test verifie que le verrou LEVE, que le contournement exige un motif ECRIT
(donc relisible dans le code, pas seulement dans un souvenir), et que le
compteur de jours ne peut pas ouvrir le dossier trop tot.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3 import devenir                                            # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


LIGNES = [{"sym": "NQ", "snapshot_id": "NQ:7:L", "entree": 29485.25,
           "pnl_atr": 1.23, "issue": "TP", "motif_issue": "tp_touche"}]


def main():
    print("\n[1] le verrou LEVE tant que la campagne court")
    try:
        devenir.lire_devenir(LIGNES)
        check("[1a] lire_devenir refuse avant le jour 61", False, "il n'a PAS leve")
    except devenir.DevenirFerme as e:
        msg = str(e)
        check("[1a] lire_devenir refuse avant le jour 61", True)
        check("[1b] le message dit ou on en est et ce qu'il reste",
              "jour" in msg and "reste" in msg, msg[:70])
        check("[1c] il nomme la regle, pas seulement l'erreur", "LECTURE_JOUR_61" in msg)

    print("\n[2] le contournement existe, mais il laisse une TRACE")
    try:
        devenir.lire_devenir(LIGNES, force=True)
        check("[2a] force sans motif est refuse", False, "accepte sans motif")
    except ValueError:
        check("[2a] force sans motif est refuse", True)
    out = devenir.lire_devenir(LIGNES, force=True, motif="test du verrou")
    check("[2b] force AVEC motif rend bien les champs de devenir",
          out and "pnl_atr" in out[0] and "issue" in out[0], out)

    print("\n[3] `sans_devenir` : ce qui n'est pas dans la structure ne peut pas fuiter")
    net = devenir.sans_devenir(LIGNES[0])
    check("[3a] tous les champs de devenir sont retires",
          not any(c in net for c in devenir.CHAMPS_DEVENIR), sorted(net))
    check("[3b] le reste de la ligne est intact",
          net["sym"] == "NQ" and net["entree"] == 29485.25 and net["snapshot_id"] == "NQ:7:L")
    check("[3c] la liste des champs couvre les deux conventions du depot",
          {"pnl_atr", "issue", "rendement_r", "rend_pts"} <= set(devenir.CHAMPS_DEVENIR))

    print("\n[4] le compteur de jours ne peut pas ouvrir le dossier trop tot")
    n = devenir.jour_campagne()
    jours = devenir.jours_courus()
    check("[4a] le compte egale le nombre de jours distincts trouves", n == len(jours), (n, len(jours)))
    check("[4b] aucun jour anterieur au jour 1 n'est compte",
          all(j >= devenir.JOUR_1 for j in jours), [j for j in jours if j < devenir.JOUR_1])
    check("[4c] aucune sauvegarde `_avant_` n'est comptee comme un jour",
          all(len(j) == 8 and j.isdigit() for j in jours), jours)
    # Le compteur lit une UNION de journaux : adosse a `scenarios_*` seul, il
    # annoncait 3 jours au lieu de 4 le 11/09 — le narrateur n'existait pas au
    # jour 1. Un compteur qui depend d'un seul producteur se trompe des que ce
    # producteur nait ou meurt, et se tromper ici veut dire ouvrir trop tot.
    check("[4d] le compteur lit PLUSIEURS journaux, pas un seul",
          len(devenir.JOURNAUX) >= 3, devenir.JOURNAUX)
    check("[4e] le dossier est ferme tant que les 61 jours ne sont pas courus",
          devenir.ouvert() == (n >= devenir.N_JOURS))
    e = devenir.etat()
    check("[4f] l'etat ne rend que des COMPTES, aucun resultat",
          set(e) == {"jour_1", "jours_courus", "n_jours", "reste", "ouvert"}, sorted(e))
    print("     jour %d sur %d, il reste %d" % (e["jours_courus"], e["n_jours"], e["reste"]))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
