"""SCÉNARIOS — LE CARNET (B5) : `erreurs.py` écrit le jour ; le carnet CUMULE.
Sans cumul, pas de candidat pour le cycle 2.

    python -X utf8 V3/scenarios/carnet.py            # agrège tous les erreurs_<jour>.jsonl

Agrège `LOGS/scenarios/erreurs_*.jsonl` → `LOGS/scenarios/carnet.json` : par
type d'erreur, le compte, les jours, un EXEMPLE (le premier), et le CANDIDAT
(texte) pour le cycle suivant ; par jour ; par bloc de deux semaines (la
mesure de l'apprentissage, spec §8 : si le taux baisse sans qu'un paramètre
ait bougé, la grammaire s'améliore). Toujours recalculé depuis les fichiers
(idempotent, aucun état qui dérive). Lu par la vitrine (bloc « hier ») et par
le rapport du soir.
Ne fait JAMAIS : modifier un seuil, une grammaire, un fichier de seuils. Le
carnet propose ; DECISIONS dispose au cycle suivant.
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys
import time
from datetime import date

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

CANDIDATS = {
    "VALIDATION_PRECOCE": "validation = acceptation (deux clotures), jamais une tentative ; reporter la validation de 10h30",
    "BASCULE_FANTOME": "ne basculer que sur une acceptation qui a tenu une barre de plus",
    "ZONE_TROP_LARGE": "dehors par nature : p75 des depassements au lieu de p80",
    "ZONE_TROP_ETROITE": "dehors par nature : p85 des depassements au lieu de p80",
    "ROLE_INVERSE": "revoir la table des roles du scenario concerne",
    "EXCLUSION_FAUSSE": "revoir la table 'ce qui ne se trade pas' du scenario concerne",
    "FUITE": "INCIDENT : une colonne lue depend de i+2 ou au-dela",
}


def dossier_defaut():
    from V3.scenarios import scenarios
    return scenarios.JOURNAL_DIR


def jours(dossier=None):
    d = dossier or dossier_defaut()
    out = []
    for f in glob.glob(os.path.join(d, "erreurs_*.jsonl")):
        m = re.search(r"erreurs_(\d{8})\.jsonl$", f)
        if m:
            out.append(m.group(1))
    return sorted(out)


def erreurs_du(jour, dossier=None):
    p = os.path.join(dossier or dossier_defaut(), "erreurs_%s.jsonl" % jour)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _bloc(jour):
    """Bloc de deux semaines ISO : 'AAAA-B<n>' (semaines 2n-1 et 2n)."""
    y, w, _ = date(int(jour[:4]), int(jour[4:6]), int(jour[6:8])).isocalendar()
    return "%d-B%02d" % (y, (w + 1) // 2)


def agreger(dossier=None, ecrire=True):
    d = dossier or dossier_defaut()
    c = {"types": {}, "jours": [], "par_jour": {}, "blocs": {}, "maj": int(time.time() * 1000)}
    for j in jours(d):
        errs = erreurs_du(j, d)
        c["jours"].append(j)
        c["par_jour"][j] = dict(collections.Counter(e["type"] for e in errs))
        b = c["blocs"].setdefault(_bloc(j), {"jours": 0, "erreurs": {}})
        b["jours"] += 1
        for e in errs:
            t = c["types"].setdefault(e["type"], {"compte": 0, "jours": [], "exemple": None,
                                                  "candidat_cycle_suivant": CANDIDATS.get(e["type"])})
            t["compte"] += 1
            if j not in t["jours"]:
                t["jours"].append(j)
            if t["exemple"] is None:
                t["exemple"] = {k: e.get(k) for k in ("jour", "sym", "heure_et", "zone", "scenario", "ce_qui_aurait_ete_juste")}
            b["erreurs"][e["type"]] = b["erreurs"].get(e["type"], 0) + 1
    for b in c["blocs"].values():
        b["par_jour"] = {t: round(n / b["jours"], 2) for t, n in b["erreurs"].items()}
    if ecrire:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "carnet.json")
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(p + ".tmp", p)
    return c


def charger(dossier=None):
    p = os.path.join(dossier or dossier_defaut(), "carnet.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {"types": {}, "jours": [], "par_jour": {}, "blocs": {}}


def hier(jour, dossier=None):
    """Le dernier jour AVANT `jour` qui a un fichier d'erreurs, et ses erreurs."""
    avant = [j for j in jours(dossier) if j < jour]
    if not avant:
        return None
    j = avant[-1]
    return {"jour": j, "erreurs": erreurs_du(j, dossier)}


def texte(c):
    if not c["types"]:
        return "carnet vide (%d jour(s))" % len(c["jours"])
    return "carnet : %d jour(s) — " % len(c["jours"]) + ", ".join(
        "%s %d (%d j)" % (t, v["compte"], len(v["jours"])) for t, v in sorted(c["types"].items(), key=lambda kv: -kv[1]["compte"]))


def main():
    os.chdir(RACINE)
    c = agreger()
    print(texte(c))
    for t, v in c["types"].items():
        print("  %-19s candidat cycle suivant : %s" % (t, v["candidat_cycle_suivant"]))
    for b, v in sorted(c["blocs"].items()):
        print("  bloc %s : %d jour(s), par jour %s" % (b, v["jours"], v["par_jour"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
