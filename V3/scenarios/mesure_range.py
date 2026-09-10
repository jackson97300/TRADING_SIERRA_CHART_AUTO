"""SCENARIOS, prérequis 2 — `range_r` sur le lot : l'IB comme premier range
(post-it §2.2 : « après 10h30, l'IB EST le premier range »).

    python -X utf8 V3/scenarios/mesure_range.py

Par instrument, sur les journées du lot (bords = max/min des quatre premières
barres 15 min, machine à partir de 10h30, `atr_ref` comme mètre) :
  - la largeur de l'IB en ATR-15m (distribution → `w_min` / `w_max`, null avant) ;
  - la part des barres 10h30-15h45 dans chaque état ; la part des journées
    ETABLI un jour, et l'heure ET médiane où l'état est atteint ;
  - la mort du range : première CASSE (heure médiane) ou extinction (jamais cassé) ;
  - l'échec de la première cassure (CASSE suivie d'un REGAIN) — « la plupart »
    de Dalton, en chiffre ; la part des CASSE retestées, puis tenues ;
  - `compression` à la barre qui précède la première CASSE, contre sa médiane
    sur les barres sans cassure (description ; le contrôle par permutation
    appartient au trade de range, pas au prérequis) ;
  - `n_tests` par bord en fin de journée.
Écrit `V3/scenarios/rapports/range_ib_57j.md`. Aucun devenir de trade.
"""

from __future__ import annotations

import collections
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import recalc                                # noqa: E402
from V3.scenarios import lot                                    # noqa: E402

RAPPORT = os.path.join(RACINE, "V3", "scenarios", "rapports", "range_ib_57j.md")
I_DEBUT = 4                     # 10h30 ET : la cinquième barre 15 min


def heure_et(df15, i):
    m = int(recalc.minutes_et(pd.Series([int(df15["ts"].iloc[i])]).pipe(pd.to_datetime, unit="ms", utc=True)).iloc[0])
    return "%02dh%02d" % (m // 60, m % 60)


def mesurer(sym):
    r = {"jours": 0, "largeur": [], "etats": collections.Counter(), "etabli": 0, "min_etabli": [],
         "casse": 0, "min_casse": [], "regain_apres_1re": 0, "retest": 0, "continuation": 0,
         "comp_avant_casse": [], "comp_sans": [], "n_tests": [], "lignes": []}
    for jour, df, _ in lot.journees(sym):
        haut, bas = float(df["high"].iloc[:I_DEBUT].max()), float(df["low"].iloc[:I_DEBUT].min())
        L = recalc.range_r(df, haut, bas, i_debut=I_DEBUT, tick=lot.TICK)
        if not L:
            continue
        r["jours"] += 1
        r["largeur"].append(L[0]["largeur_atr"])
        for l in L:
            r["etats"][l["etat"]] += 1
        i_etabli = next((l["i"] for l in L if l["evenement"] == "ETABLI"), None)
        if i_etabli is not None:
            r["etabli"] += 1
            r["min_etabli"].append(i_etabli)
        i_casse = next((l["i"] for l in L if l["evenement"] == "TRANSITION"), None)
        regain = retest = cont = False
        if i_casse is not None:
            r["casse"] += 1
            r["min_casse"].append(i_casse)
            apres = [l for l in L if l["i"] > i_casse]
            fin = next((k for k, l in enumerate(apres) if l["evenement"] == "TRANSITION"), len(apres))
            evs = [l["evenement"] for l in apres[:fin]]
            regain, retest, cont = "REGAIN" in evs, "RETEST" in evs, "CONTINUATION" in evs
            r["regain_apres_1re"] += regain
            r["retest"] += retest
            r["continuation"] += cont
            avant = next((l for l in L if l["i"] == i_casse - 1), None)
            if avant and avant["compression"] is not None:
                r["comp_avant_casse"].append(avant["compression"])
        else:
            r["comp_sans"] += [l["compression"] for l in L if l["compression"] is not None]
        r["n_tests"].append((L[-1]["n_tests_haut"], L[-1]["n_tests_bas"]))
        r["lignes"].append((jour, lot.fmt(L[0]["largeur_atr"]), df["atr_source"].iloc[I_DEBUT],
                            heure_et(df, i_etabli) if i_etabli is not None else "—",
                            heure_et(df, i_casse) if i_casse is not None else "—",
                            "oui" if regain else ("—" if i_casse is None else "non"),
                            "oui" if retest else "—", "oui" if cont else "—",
                            "%d/%d" % (L[-1]["n_tests_haut"], L[-1]["n_tests_bas"]),
                            " ".join(l["etat"][0] for l in L)))
    return r


def bloc(sym, r):
    n = r["jours"]
    q = lot.quantiles(r["largeur"])
    tot = sum(r["etats"].values()) or 1
    out = ["## %s — %d journees, machine de 10h30 a 15h45 (%d barres)" % (sym, n, tot), "",
           "| mesure | valeur |", "|---|---|",
           "| largeur IB en ATR-15m : p10 / p25 / p50 / p75 / p90 | %s / %s / %s / %s / %s |" % tuple(
               lot.fmt(q[k]) for k in (0.1, 0.25, 0.5, 0.75, 0.9)),
           "| part des barres FORMATION / ETABLI / CASSE / RETEST | %s |" % " / ".join(
               "%.0f %%" % (100.0 * r["etats"][e] / tot) for e in recalc.ETATS_RANGE),
           "| journees ETABLI un jour | %d (%.0f %%) |" % (r["etabli"], 100.0 * r["etabli"] / n if n else 0),
           "| barre mediane d'ETABLI (index 15 min depuis 9h30) | %s |" % lot.fmt(np.median(r["min_etabli"]) if r["min_etabli"] else None, 1),
           "| journees ou l'IB est CASSEE (deux clotures) | %d (%.0f %%) ; jamais cassee : %d |" % (
               r["casse"], 100.0 * r["casse"] / n if n else 0, n - r["casse"]),
           "| barre mediane de la premiere CASSE | %s |" % lot.fmt(np.median(r["min_casse"]) if r["min_casse"] else None, 1),
           "| premiere cassure ECHOUEE (REGAIN avant toute autre cassure) | %d / %d (%.0f %%) |" % (
               r["regain_apres_1re"], r["casse"], 100.0 * r["regain_apres_1re"] / r["casse"] if r["casse"] else 0),
           "| premiere cassure RETESTEE / retest TENU (CONTINUATION) | %d / %d |" % (r["retest"], r["continuation"]),
           "| compression a la barre AVANT la premiere CASSE : mediane (N) | %s (%d) |" % (
               lot.fmt(np.median(r["comp_avant_casse"]) if r["comp_avant_casse"] else None, 3), len(r["comp_avant_casse"])),
           "| compression, barres des journees SANS cassure : mediane (N) | %s (%d) |" % (
               lot.fmt(np.median(r["comp_sans"]) if r["comp_sans"] else None, 3), len(r["comp_sans"])),
           "| n_tests haut / bas en fin de journee : mediane | %s / %s |" % (
               lot.fmt(np.median([a for a, _ in r["n_tests"]]) if r["n_tests"] else None, 1),
               lot.fmt(np.median([b for _, b in r["n_tests"]]) if r["n_tests"] else None, 1)),
           "", "<details><summary>par jour</summary>", "",
           "| jour | largeur ATR | metre | ETABLI a | 1re CASSE a | echouee | retest | cont. | n_tests h/b | etats |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    out += ["| " + " | ".join(str(x) for x in l) + " |" for l in r["lignes"]]
    out += ["", "</details>", ""]
    return out


def main():
    out = ["# `range_r` sur le lot — l'IB comme premier range (prérequis 2 du module SCÉNARIOS)", "",
           "*Définition écrite avant la mesure : docstring de `recalc.range_r` (deux fiches F23 face à face,",
           "tenue causale, acceptation = deux clôtures strictement au-delà, regain = deux clôtures dedans).",
           "Bords = max/min des quatre premières barres 15 min ; `w_min`/`w_max` = None (pas de borne :",
           "la distribution est ci-dessous, la borne est à fixer dans `seuils.yaml`). Aucun devenir de trade.*",
           ""]
    for sym in ("ES", "NQ"):
        out += bloc(sym, mesurer(sym))
    os.makedirs(os.path.dirname(RAPPORT), exist_ok=True)
    open(RAPPORT, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("\n".join(l for l in out if not l.startswith("| 2026")))
    print("rapport :", RAPPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
