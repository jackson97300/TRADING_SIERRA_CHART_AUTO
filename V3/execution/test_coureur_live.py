"""La bascule de journée et le battement de cœur — le test de l'incident.

    python -X utf8 V3/execution/test_coureur_live.py

Simule l'horloge (21:59 → 22:01 UTC via `journee_courante` substituée) et
vérifie : même journée = rien ne bouge ; journée nouvelle = le chemin
change, la reprise est relue sur le NOUVEAU journal, la chauffe est
recalculée — et le journal de la veille n'est plus la cible. Puis le
battement : fichier écrit, atomique, relisible par le garde.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.execution import coureur_live as CL                   # noqa: E402
from V3.execution import garde_coureur as GC                  # noqa: E402


def main():
    e = []
    ancien_jc = CL.journee_courante
    ancien_ch = CL.chauffe_1min
    appels_chauffe = []
    try:
        CL.chauffe_1min = lambda sym, jour: appels_chauffe.append((sym, jour)) or []

        # 1. 21:59 UTC : la journee de trading est encore 20260907 -> RIEN
        CL.journee_courante = lambda: "20260907"
        etat = ("20260907", "LOGS/entonnoir/live_20260907.jsonl",
                {"X:1:L"}, {"ES": 4}, {"ES": [], "NQ": []})
        apres = CL.rouler_si_nouvelle_journee(*etat)
        if apres != etat or appels_chauffe:
            e.append("21:59 : rien ne devait bouger (%s)" % (apres,))

        # 2. 22:01 UTC : journee 20260908 -> chemin NOUVEAU, reprise relue
        #    (journal neuf = vide), chauffe recalculee sur le nouveau jour
        CL.journee_courante = lambda: "20260908"
        jour, chemin, vus, battues, chauffe = CL.rouler_si_nouvelle_journee(*etat)
        if jour != "20260908" or chemin != "LOGS/entonnoir/live_20260908.jsonl":
            e.append("22:01 : bascule attendue vers live_20260908 (%s, %s)"
                     % (jour, chemin))
        if "LOGS/entonnoir/live_20260907.jsonl" == chemin:
            e.append("22:01 : le journal de la veille est encore la cible")
        if vus == etat[2] and vus:
            e.append("22:01 : la reprise n'a pas ete RELUE (vus herites)")
        if appels_chauffe != [("ES", "20260908"), ("NQ", "20260908")]:
            e.append("22:01 : chauffe non recalculee sur 20260908 (%s)"
                     % appels_chauffe)
    finally:
        CL.journee_courante = ancien_jc
        CL.chauffe_1min = ancien_ch

    # 3. battement : ecrit, atomique (pas de .tmp restant), relisible
    ancien_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            os.makedirs("LOGS", exist_ok=True)
            CL.battre_coeur("20260908", {"ES": {"age_s": 42.0,
                                                "dernier_ts": 123}})
            if os.path.exists("LOGS/heartbeat_coureur.json.tmp"):
                e.append("battement : .tmp restant — ecriture non atomique")
            d = json.load(open("LOGS/heartbeat_coureur.json", encoding="utf-8"))
            if d.get("jour") != "20260908" or d.get("ES", {}).get("age_s") != 42.0:
                e.append("battement : contenu inattendu (%s)" % d)
            # 4. le garde lit le battement frais -> vivant
            ancien_racine = GC.RACINE
            GC.RACINE = tmp
            try:
                age = GC.age_heartbeat()
                if age is None or age > 60:
                    e.append("garde : battement frais lu comme mort (%s)" % age)
            finally:
                GC.RACINE = ancien_racine
        finally:
            os.chdir(ancien_cwd)

    print("  coureur — bascule 21:59/22:01 simulee, battement atomique, garde")
    if e:
        print("  %d ECHEC(S) :" % len(e))
        for x in e:
            print("     %s" % x)
        return 1
    print("  OK : la nuit du 07 au 08 ne peut plus se reproduire en silence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
