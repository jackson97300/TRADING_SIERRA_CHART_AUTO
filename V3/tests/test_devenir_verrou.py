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
    # CINQ TAUTOLOGIES RETIREES ICI le 12/09 (revue). Les anciens [4a]/[4b]/
    # [4c]/[4g]/[4h] verifiaient sur `jours` les proprietes que le glob de
    # `jours_courus` avait DEJA imposees pour le construire : que le compte
    # egale la longueur de la liste, que tout jour soit >= JOUR_1, que chaque
    # nom fasse huit chiffres, que le fichier existe. Aucune ne pouvait
    # echouer. Cinq PASS sur seize, et le SEUL vrai risque du compteur n'etait
    # teste par rien : `LOGS/entonnoir/` contient SIX AUTRES familles de
    # journaux — `live_`, `ombre16_`, `ombre_c2_`, `portes57_`, `scrutateur_`,
    # `.tmp_live_` — et le compteur ne tient que sur son PREFIXE. Elargir le
    # glob d'un caractere ferait bondir l'horloge des 61 jours.
    # On teste donc la DISCRIMINATION, sur un dossier temporaire.
    import tempfile
    vraie_racine = devenir.RACINE
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "LOGS", "entonnoir")
        os.makedirs(d)
        for nom, contenu in (
                ("entonnoir_20260908.jsonl", ""),            # vide = couru MUET
                ("entonnoir_20260909.jsonl", '{"a":1}\n'),    # couru avec signal
                ("entonnoir_20260907.jsonl", '{"a":1}\n'),    # avant le jour 1
                ("entonnoir_20260910_avant_lecture.jsonl", '{"a":1}\n'),
                ("live_20260911.jsonl", '{"a":1}\n'),
                ("ombre16_20260911.jsonl", '{"a":1}\n'),
                ("ombre_c2_20260911.jsonl", '{"a":1}\n'),
                ("portes57_20260911.jsonl", '{"a":1}\n'),
                ("scrutateur_20260911.jsonl", '{"a":1}\n'),
                (".tmp_live_20260911_ES.jsonl", '{"a":1}\n')):
            open(os.path.join(d, nom), "w", encoding="utf-8").write(contenu)
        devenir.RACINE = tmp
        try:
            vus = set(devenir.jours_courus())
        finally:
            devenir.RACINE = vraie_racine
    check("[4a] un journal VIDE compte (couru muet), un ABSENT ne compte pas",
          "20260908" in vus and "20260912" not in vus, sorted(vus))
    check("[4b] les SIX autres familles du meme dossier ne sont JAMAIS comptees",
          "20260911" not in vus, sorted(vus))
    check("[4c] ni une sauvegarde `_avant_`, ni un jour anterieur au jour 1",
          vus == {"20260908", "20260909"}, sorted(vus))
    # LE compteur lit LA MESURE OFFICIELLE, ni un producteur commode ni une
    # union. Deux erreurs successives l'ont montre : adosse au seul journal du
    # narrateur il annoncait 3 jours au lieu de 4 (le narrateur n'existait pas
    # au jour 1) ; adosse a l'union de quatre journaux il comptait le 11/09
    # alors que le rejeu officiel de ce jour-la avait PLANTE sur un verrou de
    # fichier et s'etait efface. La seconde faute est la pire : elle ouvre le
    # dossier trop tot.
    check("[4d] le compteur lit la MESURE OFFICIELLE (`entonnoir_`), pas un producteur commode",
          [d for d, _ in devenir.JOURNAUX] == ["entonnoir"], devenir.JOURNAUX)
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
