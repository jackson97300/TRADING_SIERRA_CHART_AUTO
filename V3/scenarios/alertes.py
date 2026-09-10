"""SCÉNARIOS — LES ALERTES (A4) : un lecteur du journal direct qui SONNE sur
cinq ÉVÉNEMENTS — bascule, validation, invalidation, zone cassée (acceptée),
ZONE_DEPLACEE — jamais sur un état (« en cours » ne sonne pas, « armé » est un
état, un prix n'est pas un événement).

    python -X utf8 V3/scenarios/alertes.py            # boucle (5 s)
    python -X utf8 V3/scenarios/alertes.py --un-tour

Règles (seuils.yaml : alertes) : silence 9h30-9h35 ET ; muet = le marqueur
`LOGS/scenarios/MUET` (présent → rien ne sonne, tout se journalise) ; une
alerte par événement (idempotence par ts + sym + type + objet) ; une file, jamais
deux sons superposés. Les textes viennent des GABARITS du yaml (≤ 10 mots, aucun
prix nu, aucun verbe d'action), jamais du code. Écrit
`LOGS/scenarios/alertes_<jour>.jsonl` {ts, sym, type, texte, muet, sonne}.
"""

from __future__ import annotations

import json
import os
import sys
import time

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.scenarios import lot, scenarios                         # noqa: E402

CYCLE_S = 5


def chemin_alertes(jour):
    return os.path.join(scenarios.JOURNAL_DIR, "alertes_%s.jsonl" % jour)


def muet(cfg=None):
    c = cfg or lot.seuils()["alertes"]
    return os.path.exists(os.path.join(RACINE, c["muet_fichier"]))


def basculer_muet(cfg=None):
    c = cfg or lot.seuils()["alertes"]
    p = os.path.join(RACINE, c["muet_fichier"])
    if os.path.exists(p):
        os.remove(p)
        return False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()
    return True


def en_silence(minutes_et, cfg=None):
    c = cfg or lot.seuils()["alertes"]
    return c["silence_de"] <= minutes_et < c["silence_a"]


def detecter(ligne, precedente):
    """Les événements NOUVEAUX entre la ligne précédente et celle-ci (même sym)."""
    ev = []
    nb = len(precedente["bascules"]) if precedente else 0
    for b in ligne["bascules"][nb:]:
        ev.append({"type": "bascule", "vers": b["vers"], "cause": b["cause"], "objet": "%s>%s" % (b["de"], b["vers"])})
    nv = len(precedente["validations"]) if precedente else 0
    for v in ligne["validations"][nv:]:
        ev.append({"type": "validation", "scenario": v["scenario"], "zone": v["zone"], "objet": v["quoi"]})
    ni = len(precedente["invalidations"]) if precedente else 0
    for v in ligne["invalidations"][ni:]:
        ev.append({"type": "invalidation", "scenario": v["scenario"], "zone": v["zone"], "objet": v["quoi"]})
    for e in ligne.get("evenements_zones", []):
        if e["quoi"] == "CASSEE":
            ev.append({"type": "zone_cassee", "zone": e["zone"], "objet": e["zone"]})
        elif e["quoi"] == "ZONE_DEPLACEE":
            ev.append({"type": "zone_deplacee", "zone": e["zone"], "objet": e["zone"]})
    return ev


def texte(ev, sym, ligne, cfg=None):
    c = cfg or lot.seuils()["alertes"]
    g = c["gabarits"][ev["type"]]
    return g.format(sym=sym, scenario=ev.get("scenario") or ligne["scenario_en_cours"], zone=ev.get("zone") or "",
                    vers=ev.get("vers") or "", cause=(ev.get("cause") or "").replace("_", " "))


def sonner(type_, cfg=None):
    """Trois sons distincts, les deux autres = ding ; séquentiel : jamais superposés."""
    c = cfg or lot.seuils()["alertes"]
    notes = c["sons"].get(type_) or c["sons"]["ding"]
    try:
        import winsound
        for f, d in notes:
            winsound.Beep(int(f), int(d))
    except (ImportError, RuntimeError):
        return False
    return True


def _minutes_et(ts):
    import pandas as pd
    from CORE.features import recalc
    return int(recalc.minutes_et(pd.Series([int(ts)]).pipe(pd.to_datetime, unit="ms", utc=True)).iloc[0])


def traiter(jour, cfg=None, jouer=True):
    """Un tour : lit le journal direct, émet ce qui n'a pas encore été émis.
    Rend les alertes ajoutées."""
    c = cfg or lot.seuils()["alertes"]
    lignes = scenarios.lire(scenarios.chemin_direct(jour))
    deja = scenarios.lire(chemin_alertes(jour))
    vus = {(a["ts"], a["sym"], a["type"], a.get("objet")) for a in deja}
    neuves = []
    par_sym = {}
    for l in lignes:
        par_sym.setdefault(l["sym"], []).append(l)
    for sym, ls in par_sym.items():
        ls.sort(key=lambda x: x["i"])
        prec = None
        for l in ls:
            for ev in detecter(l, prec):
                cle = (l["ts"], sym, ev["type"], ev["objet"])
                if cle in vus:
                    continue
                vus.add(cle)
                silence, m = en_silence(_minutes_et(l["ts"]), c), muet(c)
                sonne = bool(jouer and not silence and not m and sonner(ev["type"], c))
                neuves.append({"ts": l["ts"], "sym": sym, "type": ev["type"], "objet": ev["objet"],
                               "texte": texte(ev, sym, l, c), "muet": m, "silence": silence, "sonne": sonne,
                               "heure_et": l["heure_et"], "emis_a": int(time.time() * 1000)})
            prec = l
    if neuves:
        scenarios.ecrire(chemin_alertes(jour), deja + neuves)
    return neuves


def main(argv):
    os.chdir(RACINE)
    from V3.scenarios import boucle
    if "--un-tour" in argv:
        jour, _ = boucle.maintenant_et()
        for a in traiter(jour):
            print("%s %-13s %s%s" % (a["heure_et"], a["type"], a["texte"], "" if a["sonne"] else "  (silencieux)"))
        return 0
    print("alertes scenarios : boucle toutes les %d s" % CYCLE_S, flush=True)
    while True:
        try:
            jour, _ = boucle.maintenant_et()
            for a in traiter(jour):
                print("%s %-13s %s" % (a["heure_et"], a["type"], a["texte"]), flush=True)
        except Exception as e:                        # noqa: BLE001
            print("tour en erreur : %s: %s" % (type(e).__name__, e), flush=True)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
