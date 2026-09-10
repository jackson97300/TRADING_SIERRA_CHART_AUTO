"""SCÉNARIOS — le mode DIRECT des prérequis, en lecture seule, sur la journée
en cours (ou une journée donnée). Ce n'est PAS le module : la grammaire vient
après la relecture de Fable. Ceci ne décide rien, n'entre dans aucune porte,
n'écrit que son propre journal.

    python -X utf8 V3/scenarios/direct.py            # aujourd'hui
    python -X utf8 V3/scenarios/direct.py 20260909   # une journée

Ce qu'il montre, sur les barres 15 min COMPLÈTES seulement (la barre en cours
n'existe pas — une barre de 15 min est complète quand sa 15e minute est dans
le fichier) :
  - le type d'ouverture (`open_type_r`) dès que deux barres existent ;
  - l'IB (bords figés à 10h30) et la machine `range_r` barre à barre ;
  - les niveaux figés à la première barre cash (VA veille, PDH/PDL, OVN,
    murs) avec `dedans` = P10 et le candidat `dehors` (p80 mesuré, NON fixé :
    affiché comme candidat, jamais comme zone).
Chaque passage écrit une ligne dans `LOGS/scenarios/prerequis_<jour>.jsonl` — ce
soir, le rejeu de la journée complète doit rendre les mêmes états barre à
barre (MISSION, test 6 : direct = rétrospectif, sur une vraie journée).
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from V3.scenarios import lot                                    # noqa: E402

BARRE_MS = 15 * 60 * 1000
I_DEBUT_IB = 4
NIVEAUX_FIGES = (("prev_vah", "dist_prev_vah"), ("prev_val", "dist_prev_val"),
                 ("prev_vpoc", "dist_prev_vpoc"), ("pdh", "dist_pdh"), ("pdl", "dist_pdl"),
                 ("ovn_high", "dist_ovn_high"), ("ovn_low", "dist_ovn_low"),
                 ("mq_call", "dist_mq_call"), ("mq_put", "dist_mq_put"))
# p80 du dépassement des tests tenus (rapports/reactions_niveaux_57j.md) — CANDIDATS
CANDIDAT_DEHORS_TICKS = {"ES": {"prev": 27.8, "pd": 19.4, "ovn": 20.8, "mq": 16.2},
                         "NQ": {"prev": 310.0, "pd": 120.8, "ovn": 94.4, "mq": 389.6}}


def barres_completes(df15, brut):
    """Ne garde que les barres 15 min dont la 15e minute est dans le fichier."""
    if df15.empty or brut.empty:
        return df15
    dernier = int(pd.to_numeric(brut["ts"]).max())
    fin = pd.to_numeric(df15["ts"]) + BARRE_MS - 60_000
    return df15[fin <= dernier].reset_index(drop=True)


def heure_et(ts):
    m = int(recalc.minutes_et(pd.Series([int(ts)]).pipe(pd.to_datetime, unit="ms", utc=True)).iloc[0])
    return "%02dh%02d" % (m // 60, m % 60)


def niveaux(df, sym):
    close0 = float(df["close"].iloc[0])
    a = float(df["atr_ref"].iloc[0])
    p10 = max(0.10 * a / lot.TICK, 2.0) if a and a > 0 else None
    out = []
    for nom, col in NIVEAUX_FIGES:
        d = pd.to_numeric(df.get(col), errors="coerce") if col in df.columns else None
        if d is None or not np.isfinite(d.iloc[0]):
            continue
        prix = round(close0 + float(d.iloc[0]) * lot.TICK, 2)
        cle = "prev" if nom.startswith("prev") else "pd" if nom.startswith("pd") else \
            "ovn" if nom.startswith("ovn") else "mq"
        out.append({"nom": nom, "prix": prix, "dedans_ticks": round(p10, 1) if p10 else None,
                    "dehors_ticks_candidat": CANDIDAT_DEHORS_TICKS[sym][cle], "fixe": False})
    return out


def lire(sym, jour):
    df, brut = charger_jour(sym, jour, 15, avec_1min=True)
    if df.empty or brut.empty:
        return {"sym": sym, "jour": jour, "barres": 0, "motif": "pas de barre cash"}
    df = barres_completes(df, brut)
    if df.empty:
        return {"sym": sym, "jour": jour, "barres": 0, "motif": "aucune barre 15 min complete"}
    veille = lot.atr_veille(sym, jour, brut)
    df = lot.avec_metre(df, veille)
    r = {"sym": sym, "jour": jour, "barres": int(len(df)), "derniere": heure_et(df["ts"].iloc[-1]),
         "atr_veille": round(veille, 2) if veille else None, "niveaux": niveaux(df, sym)}
    if len(df) >= 2:
        o = pd.to_numeric(brut.get("open_cash_lvl"), errors="coerce")
        o = float(o.dropna().iloc[0]) if o is not None and o.notna().any() else None
        r["open_type"] = recalc.open_type_r(df, veille, open_lvl=o)
    if len(df) > I_DEBUT_IB:
        haut, bas = float(df["high"].iloc[:I_DEBUT_IB].max()), float(df["low"].iloc[:I_DEBUT_IB].min())
        L = recalc.range_r(df, haut, bas, i_debut=I_DEBUT_IB, tick=lot.TICK)
        r["ib"] = {"haut": haut, "bas": bas, "largeur_atr": L[0]["largeur_atr"] if L else None}
        bornes = lot.seuils()["range"]
        w_min, w_max = bornes["w_min_atr"][sym], bornes["w_max_atr"][sym]
        la = L[0]["largeur_atr"] if L else None
        r["ib"]["hors_norme"] = bool(la is not None and (la < w_min or la > w_max))
        r["ib"]["bornes"] = [w_min, w_max]
        r["range"] = [{"h": heure_et(l["ts"]), "etat": l["etat"], "ev": l["evenement"],
                       "n": "%d/%d" % (l["n_tests_haut"], l["n_tests_bas"]),
                       "pression": l["pression"], "pose": l["barres_depuis_pose"]} for l in L]
    return r


def afficher(r):
    print("== %s %s — %d barre(s) 15 min complete(s)%s" % (
        r["sym"], r["jour"], r["barres"], (", derniere %s" % r["derniere"]) if r["barres"] else
        " (%s)" % r.get("motif")))
    if not r["barres"]:
        return
    print("   atr_veille %s pts" % r["atr_veille"])
    for n in r["niveaux"]:
        print("   %-9s %10.2f   dedans P10 %s t   dehors candidat %s t (non fixe)" % (
            n["nom"], n["prix"], n["dedans_ticks"], n["dehors_ticks_candidat"]))
    if "open_type" in r:
        o = r["open_type"]
        print("   OUVERTURE : %s  direction %s  retour sur O %s  ext b1 %s t / b2 %s t  (O %s, bande %s t)" % (
            o.get("type"), o.get("direction"), o.get("retour_ouverture"), o.get("ext_b1_ticks"),
            o.get("ext_b2_ticks"), o.get("open_cash"), o.get("bande_ticks")) if o.get("type") else
            "   OUVERTURE : non mesurable (%s)" % o.get("motif"))
    else:
        print("   OUVERTURE : attend la 2e barre (10h00 ET)")
    if "range" in r:
        ib = r["ib"]
        print("   IB %.2f / %.2f  largeur %s ATR%s — range_r :" % (
            ib["haut"], ib["bas"], ib["largeur_atr"],
            "  HORS NORME [%s ; %s] -> S_AUTRE(IB_hors_norme)" % tuple(ib["bornes"]) if ib["hors_norme"] else ""))
        for l in r["range"]:
            print("      %s  %-9s %-12s n_tests %s  pression %s  pose %s" % (
                l["h"], l["etat"], l["ev"] or "", l["n"], l["pression"], l["pose"]))
    else:
        print("   IB / range_r : attend la 5e barre (10h30 ET)")


def journal(r):
    d = os.path.join(RACINE, "LOGS", "scenarios")
    os.makedirs(d, exist_ok=True)
    r = dict(r, ecrit_a=int(time.time() * 1000), mode="direct")
    with open(os.path.join(d, "prerequis_%s.jsonl" % r["jour"]), "a", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def main(argv):
    os.chdir(RACINE)
    jour = argv[1] if len(argv) > 1 else time.strftime("%Y%m%d")
    for sym in ("ES", "NQ"):
        r = lire(sym, jour)
        afficher(r)
        journal(r)
    # le narrateur de séance (grammaire v0), sur les mêmes barres complètes —
    # il écrit son propre journal `direct_<jour>.jsonl`, rien d'autre
    from V3.scenarios import scenarios
    print("-- scenario en cours (grammaire v0, lecture seule) :")
    scenarios.direct(jour)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
