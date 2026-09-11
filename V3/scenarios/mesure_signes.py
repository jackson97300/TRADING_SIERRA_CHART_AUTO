"""MESURE PREALABLE A LA FICHE DE TOUCHE — les signes discriminent-ils, oui ou non ?

    python -X utf8 V3/scenarios/mesure_signes.py [n_jours]

LA QUESTION, ET ELLE EST ELIMINATOIRE. Jackson veut une fiche qui s'ouvre quand
le prix entre dans une zone et qui montre ce qui penche. Mesure faite sur 12
jours : les trois familles s'accordent deja sur 19 % des barres ES et 13 % des
barres NQ, PARTOUT, sans aucune zone. Si ce taux est le MEME dans les zones,
la fiche ne montre rien que le hasard ne montre deja, et il ne faut pas
l'ecrire. C'est la seule mesure qui tranche, et elle doit exister AVANT le code.

Ce fichier ne construit rien, ne decide rien, n'ecrit aucun journal de
campagne. Il MESURE, sur le lot, par instrument — jamais un seuil partage entre
ES et NQ (`feedback_calibration_par_instrument`).

TROIS FAMILLES, pas six. Mesure d'accord de signe sur 242 barres : delta, CVD
et finish s'accordent aux deux tiers (66-68 %) — c'est UNE famille, pas trois.
La meche s'accorde avec le delta une fois sur deux (49-56 %) — elle en est une
autre. `rvol` s'accorde avec tout le monde une fois sur deux (43-53 %) parce
qu'il ne dit pas un SENS mais une INTENSITE : il qualifie, il ne vote pas.

AUCUN DEVENIR N'EST LU. On compte des etats de barre et une appartenance a une
bande, rien d'autre. Le jour 61 reste ferme.
"""

from __future__ import annotations

import glob
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.scenarios import lot, scenarios, zones as Z             # noqa: E402

# Seuils PROVISOIRES, uniquement pour cette mesure : ils servent a repondre
# « les signes discriminent-ils ? », pas a regler quoi que ce soit. Les vrais
# seuils se fixeront sur les distributions que cette mesure produit.
SEUILS_MESURE = {"finish": 0.5, "meche": 0.33, "rvol": 1.2}


def familles(df, i):
    """Rend (flux, meche, rvol) : trois etats +1 / -1 / None a la barre i.

    `flux` agrege delta, CVD et finish — ils s'accordent aux deux tiers, donc
    ils forment UNE famille ; les compter separement ferait lire trois temoins
    la ou il y en a un. La famille penche si au moins deux de ses trois membres
    connus penchent du meme cote.
    """
    def v(col):
        if col not in df.columns:
            return None
        x = pd.to_numeric(df[col], errors="coerce").iloc[i]
        return None if not np.isfinite(x) else float(x)

    membres = []
    for col, seuil in (("delta_bar", 0.0), ("cvd_sess_r", 0.0),
                       ("finish_delta_pct", SEUILS_MESURE["finish"])):
        x = v(col)
        if x is not None:
            membres.append(1 if x > seuil else -1)
    flux = None
    if membres:
        s = sum(membres)
        flux = 1 if s > 0 else (-1 if s < 0 else None)

    m = v("bar_lower_wick_pct")
    meche = None if m is None else (1 if m > SEUILS_MESURE["meche"] else -1)
    r = v("rvol_r")
    rvol = None if r is None else (r > SEUILS_MESURE["rvol"])
    return flux, meche, rvol


def dans_zone(zs, close):
    """Le prix est-il DANS la bande d'au moins une zone active ?"""
    for z in Z.actives(zs):
        bas, haut = Z.bande(z, close)
        if bas is not None and haut is not None and bas <= close <= haut:
            return True
    return False


def mesurer(sym, jours):
    c = Counter()
    s = lot.seuils()
    for j in jours:
        try:
            df, brut = scenarios.charger(sym, j)
        except Exception:                              # noqa: BLE001 — un jour illisible n'arrete pas la mesure
            c["jour_illisible"] += 1
            continue
        if df.empty or len(df) < 6:
            c["jour_court"] += 1
            continue
        zs = Z.construire(df, brut, sym, s)
        c["jours"] += 1
        for i in range(len(df)):
            if i == 4:
                Z.ajouter_ib(zs, df, sym, 4, s)
            Z.observer(zs, df, i, brut)
            close = float(pd.to_numeric(df["close"], errors="coerce").iloc[i])
            flux, meche, rvol = familles(df, i)
            ou = "zone" if dans_zone(zs, close) else "hors"
            c["n_" + ou] += 1
            if flux is None or meche is None:
                c["incomplet_" + ou] += 1
                continue
            c["complet_" + ou] += 1
            if flux == meche:
                c["accord_" + ou] += 1
                if rvol:
                    c["accord_volume_" + ou] += 1
    return c


def main(argv):
    os.chdir(RACINE)
    n = int(argv[1]) if len(argv) > 1 else 57
    jours = sorted({os.path.basename(f)[:8]
                    for f in glob.glob("DATA/live_enriched/sierra/ES/2026*.jsonl")})[-n:]
    print("\n  LES SIGNES DISCRIMINENT-ILS ? — %d jours, par instrument\n" % len(jours))
    for sym in ("ES", "NQ"):
        c = mesurer(sym, jours)
        print("  === %s — %d jours lus ===" % (sym, c["jours"]))
        for ou, nom in (("zone", "DANS une zone"), ("hors", "HORS zone")):
            n_ou, comp = c["n_" + ou], c["complet_" + ou]
            if not n_ou:
                print("     %-14s aucune barre" % nom)
                continue
            acc = c["accord_" + ou]
            accv = c["accord_volume_" + ou]
            print("     %-14s %5d barres | %5d completes | flux et meche d'accord : "
                  "%5.1f %% | ... et volume eleve : %5.1f %%"
                  % (nom, n_ou, comp, 100 * acc / comp if comp else 0,
                     100 * accv / comp if comp else 0))
        z, h = c["complet_zone"], c["complet_hors"]
        if z and h:
            tz, th = c["accord_zone"] / z, c["accord_hors"] / h
            print("     ECART zone - hors : %+.1f point(s) de pourcentage%s"
                  % (100 * (tz - th),
                     "   <<< les signes ne discriminent PAS" if abs(tz - th) < 0.05 else ""))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
