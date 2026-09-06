"""Etape 1 — ce que chaque porte ferme, et ce que ses rejetes seraient devenus.

C'est l'entonnoir applique au passe. Ce qui a tue les trois bots precedents n'est
pas d'avoir refuse des trades : c'est de n'avoir jamais su ce que les refuses
seraient devenus. Une porte dont les rejetes ont un devenir favorable est une
porte a rouvrir — et c'est mesure, pas debattu.

    python -X utf8 V3/layers/L0_interrupteur/mesure_57j.py
    python -X utf8 V3/layers/L0_interrupteur/mesure_57j.py --minutes 5

Sortie : `rapports/portes_57j.csv`, a cote de ce fichier, quelques Ko, versionne.


CE QUE CE SCRIPT MESURE, ET CE QU'IL NE MESURE PAS
---------------------------------------------------
Il mesure **les portes** : leur taux de rejet, et le devenir moyen a 20 barres de
ce qu'elles ferment. Le devenir est agrege **par porte**, jamais par hypothese —
on lit « la porte X ferme des signaux dont le devenir moyen vaut Y », pas
« l'hypothese H3 gagne ». La rentabilite des declencheurs se juge en ombre, sur
des jours que personne n'a vus.

Il tourne sur les **57 jours**, pas sur les 40 de recherche : la mesure porte sur
les portes, qui n'ont jamais ete lues, et un echantillon plus large rend chaque
case de regime plus peuplee.


LA REGLE DU CHANTIER
--------------------
Une porte qui ne rejette rien est **inerte** — elle donne l'illusion d'une
protection. Une porte qui rejette tout est **etrangleuse**. Ni l'une ni l'autre
ne passe a la brique suivante. Plages attendues dans `PLAGES`, tirees des
pratiques de janvier et de ce qu'on a mesure le 06/09.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour, regime_gamma, regime_ib  # noqa: E402
from CORE.research import hypotheses as H  # noqa: E402
from V3 import chaine  # noqa: E402
from V3.layers.L0_interrupteur.journal import (  # noqa: E402
    _lire_journal, controler_effectifs)

PLAGES = {"L0": (0.15, 0.30), "REGIME": (0.30, 0.70), "L5": (0.10, 0.25)}
HORIZON = 20                       # barres, comme l'expiration de la barriere


def devenir(df, i, side, horizon=HORIZON):
    """Ce que la barre i serait devenue, **dans le sens du trade**, en ATR.

    Le signe est celui du TRADE, pas du marche. Un devenir signe marche est
    ininterpretable : -0,44 sur un lot majoritairement SHORT est FAVORABLE, et
    la premiere version de ce script le lisait comme defavorable.

    Positif = la porte a ferme un trade qui aurait gagne. C'est le seul sens qui
    permette de dire « cette porte coute » ou « cette porte protege ».
    """
    j = min(i + horizon, len(df) - 1)
    atr = df["atr5"].iloc[i]
    if not np.isfinite(atr) or atr <= 0:
        return np.nan
    return float(side * (df["close"].iloc[j] - df["close"].iloc[i]) / atr)


def jours_du_lot(sym):
    import glob
    import re
    out = []
    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)):
        m = re.search(r"(\d{8})", os.path.basename(f))
        if m:
            out.append(m.group(1))
    return out


def mesurer(sym, minutes, journal):
    """Rend une liste de lignes {couche, motif, n, part, devenir_moyen, ...}."""
    fns = {"H3": H.h3, "H6": H.h6, "H7": H.h7, "H8": H.h8}
    tot_signaux = 0
    par_motif = {}                 # motif -> [devenirs]
    passes_dev = []
    sens = {"long": 0, "short": 0}
    cases = {}                     # (gamma, ib) -> [jours]

    for jour in jours_du_lot(sym):
        df = charger_jour(sym, jour, minutes)
        if df.empty or len(df) < 6:
            continue

        # --- regime : une case par journee, lue a la premiere barre exploitable
        g = regime_gamma(df, min(6, len(df) - 1))
        r, _ = regime_ib(df, min(6, len(df) - 1))
        cases.setdefault((g, r), []).append(jour)

        # --- signaux de tous les declencheurs, dans l'ordre
        sig = []
        for nom, fn in fns.items():
            for cote, (cond, side) in fn(df).items():
                for i in range(len(df)):
                    try:
                        if bool(cond.iloc[i]):
                            sig.append((i, nom, side))
                    except Exception:
                        break
        sig.sort(key=lambda x: x[0])
        # DEDUPLICATION PAR (barre, sens) — corrigee le 06/09.
        # Deux declencheurs qui tirent LONG sur la meme barre, ce n'est pas deux
        # trades : c'est un seul, que le bot ne prendrait qu'une fois. Sans cette
        # ligne, `par_motif` comptait le devenir deux fois pour une seule ligne
        # de journal — 312 rejets annonces pour 282 reellement journalises sur ES.
        vus, uniques = set(), []
        for s in sig:
            cle = (s[0], s[2])
            if cle not in vus:
                vus.add(cle)
                uniques.append(s)
        sig = uniques
        if not sig:
            continue
        tot_signaux += len(sig)

        for _i, _n, _s in sig:
            sens["long" if _s > 0 else "short"] += 1
        _, avant = _lire_journal(journal)
        retenus = set(chaine.appliquer([(s[0], s[2]) for s in sig], df, sym,
                                       journal=journal, hypothese="portes57"))
        motifs, _ = _lire_journal(journal, depuis=avant)

        for i, _nom, side in sig:
            d = devenir(df, i, side)
            if i in retenus:
                passes_dev.append(d)
            # Chaque porte qui AURAIT ferme ce signal recoit son devenir —
            # y compris si une autre l'a ferme aussi, et y compris si le signal
            # est finalement passe (cas d'une porte OBSERVEE). C'est ce qui rend
            # l'attribution independante de l'ordre.
            cle = "%s:%d:%s" % (sym, i, "L" if side > 0 else "S")
            for m in motifs.get(cle, []):
                par_motif.setdefault(m, []).append(d)

    lignes = []
    from V3.registre import REGISTRE
    for nom in REGISTRE:                    # les inertes AUSSI, avec n = 0
        par_motif.setdefault(nom, [])
    for m, devs in sorted(par_motif.items(), key=lambda x: -len(x[1])):
        v = [x for x in devs if np.isfinite(x)]
        couche = m[:2] if m[:2] in ("L0", "L5") else "?"
        applique = m in chaine._APPLIQUEES
        part = len(devs) / max(tot_signaux, 1)
        lo, hi = PLAGES.get(couche, (0.0, 1.0))
        lignes.append({
            "sym": sym, "unite_min": minutes, "couche": couche, "motif": m,
            "classe": "appliquee" if applique else "observee",
            "n_rejetes": len(devs), "part_des_signaux": round(part, 4),
            "devenir_moyen_atr": round(float(np.mean(v)), 4) if v else None,
            "devenir_median_atr": round(float(np.median(v)), 4) if v else None,
            "verdict": _verdict(part, lo, hi),
        })
    v = [x for x in passes_dev if np.isfinite(x)]
    lignes.append({
        "sym": sym, "unite_min": minutes, "couche": "PASSE",
        "motif": "(retenus)", "classe": "-",
        "n_rejetes": len(passes_dev),
        "part_des_signaux": round(len(passes_dev) / max(tot_signaux, 1), 4),
        "devenir_moyen_atr": round(float(np.mean(v)), 4) if v else None,
        "devenir_median_atr": round(float(np.median(v)), 4) if v else None,
        "verdict": "-",
    })
    return lignes, cases, tot_signaux, sens


def _verdict(part, lo, hi):
    if part <= 0.0001:
        return "INERTE — ne rejette rien, ne protege de rien"
    if part < lo:
        return "sous la plage (%.0f-%.0f %%)" % (100 * lo, 100 * hi)
    if part > hi:
        return "ETRANGLEUSE — au-dessus de %.0f %%" % (100 * hi)
    return "dans la plage"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=15)
    a = ap.parse_args()

    os.chdir(RACINE)
    j = "LOGS/entonnoir/portes57_%dmin.jsonl" % a.minutes
    os.makedirs(os.path.dirname(j), exist_ok=True)
    if os.path.exists(j):
        os.remove(j)

    print("ETAPE 1 — ce que chaque porte ferme, sur les 57 jours, barres %d min\n"
          % a.minutes)
    toutes, tous_cases = [], {}
    for sym in ("ES", "NQ"):
        lignes, cases, n, sens = mesurer(sym, a.minutes, j)
        toutes.extend(lignes)
        tous_cases[sym] = cases
        print("  %s : %d signaux bruts | %d long / %d short"
              % (sym, n, sens["long"], sens["short"]))

    ecarts = controler_effectifs(toutes, j)
    if ecarts:
        print("\n  EFFECTIFS FAUX — le tableau ne dit pas ce que le journal "
              "porte :")
        for e in ecarts:
            print("     %s" % e)
        print("  Rien de ce rapport n'est publiable en l'etat.")
        return 1

    df = pd.DataFrame(toutes)
    sortie = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapports")
    os.makedirs(sortie, exist_ok=True)
    df.to_csv(os.path.join(sortie, "portes_57j.csv"), index=False, encoding="utf-8")

    print("\n%-4s %-28s %8s %9s %11s  %s"
          % ("sym", "porte", "rejetes", "part", "devenir", "verdict"))
    print("-" * 100)
    for r in toutes:
        print("%-4s %-28s %8d %8.1f%% %11s  %s"
              % (r["sym"], r["motif"][:28], r["n_rejetes"],
                 100 * r["part_des_signaux"],
                 "%+.3f" % r["devenir_moyen_atr"] if r["devenir_moyen_atr"] is not None else "-",
                 r["verdict"]))

    print("\ncases de regime (une case sous 5 jours est inutilisable) :")
    for sym, cases in tous_cases.items():
        for (g, r), jours in sorted(cases.items(), key=lambda x: -len(x[1])):
            marque = "" if len(jours) >= 5 else "   <<< trop peu"
            print("  %-3s %-16s / %-12s %3d jours%s" % (sym, g, r, len(jours), marque))

    print("\necrit : %s" % os.path.join(sortie, "portes_57j.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
