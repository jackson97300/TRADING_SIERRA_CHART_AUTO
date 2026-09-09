"""Confrontation triple_barriere : CORE vs la reference de Fable.

Rejoue TOUS les signaux LES_QUATRE du lot avec les deux fonctions et sort le
tableau : combien de trades dont l'ISSUE differe, l'ecart de pnl_atr moyen, le
detail par couple (issue_core -> issue_ref), la REPARTITION HORAIRE des
divergences, et tout INDETERMINE residuel NOMME (jour + derniere barre cash).
Zero ecart = memes conventions ; des ecarts = on sait lesquels, et de combien
les devenirs du jour 61 bougent. Ce script MESURE, il ne tranche rien : le
verdict va dans DECISIONS.md. Le tableau est ecrit dans `research/rapports/`.

    python -X utf8 V3/research/parite_barriere.py [YYYYMMDD]   (defaut : tout le lot)
"""

from __future__ import annotations

import collections
import io
import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                       # noqa: E402
from CORE.features import recalc                                 # noqa: E402
from CORE.research.hypothesis_runner import (                    # noqa: E402
    COUT_DOLLARS, VAL_POINT, injecter_recalculs, triple_barriere)
from V3.campagne import (COLS_RECALC, chauffe_1min,              # noqa: E402
                         jours_disponibles, signaux_l3)
from V3.research.triple_barriere_ref import triple_barriere_ref  # noqa: E402

ETIQ = {1: "TP", -1: "SL", 0: "EXPIRATION"}
RAPPORT = os.path.join(RACINE, "V3", "research", "rapports", "parite_barriere.txt")


def _issue_core(r):
    """CORE rend (etiquette, pnl_atr, i_sortie) ou None. Mappe vers l'issue."""
    return "INDETERMINE" if r is None else ETIQ[r[0]]


def confronter(jours):
    lignes, derniere_barre = [], {}
    for sym in ("ES", "NQ"):
        for jour in jours:
            df, brut = charger_jour(sym, jour, 15, avec_1min=True)
            if df.empty or len(df) < 6:
                continue
            brut = pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                             ignore_index=True)
            df = injecter_recalculs(brut, df, minutes=15)
            if "minutes_et" not in df.columns:                   # la ref en a besoin (C4)
                df = df.assign(minutes_et=recalc.minutes_et(
                    pd.to_datetime(df["ts"], unit="ms", utc=True)).to_numpy())
            m_et = pd.to_numeric(df["minutes_et"], errors="coerce").to_numpy()
            derniere_barre[(sym, jour)] = float(m_et[-1]) if len(m_et) else None
            sig, _ = signaux_l3(df)
            atrv = pd.to_numeric(df["atr_barre"], errors="coerce")
            for i, side, fam in sig:
                a = atrv.iloc[i]
                if pd.isna(a) or a <= 0:
                    continue
                atr = float(a)
                rc = triple_barriere(df, i, side, (COUT_DOLLARS[sym], VAL_POINT[sym]))
                rr = triple_barriere_ref(df, i, side, atr,
                                         COUT_DOLLARS[sym], VAL_POINT[sym])
                # heure d'ENTREE = barre du signal + une barre (t+1), en ET
                h_ent = m_et[i] + 15 if (i < len(m_et) and pd.notna(m_et[i])) else None
                lignes.append({
                    "sym": sym, "jour": jour, "i": i, "side": side, "fam": fam,
                    "issue_core": _issue_core(rc), "issue_ref": rr["issue"],
                    "pnl_core": None if rc is None else float(rc[1]),
                    "pnl_ref": rr["pnl_atr"], "meme_barre": rr["meme_barre"],
                    "h_entree": h_ent, "barre_fin": derniere_barre[(sym, jour)]})
    return lignes


def tableau(lignes):
    out = io.StringIO()

    def p(s=""):
        print(s, file=out)

    n = len(lignes)
    if not n:
        p("  aucun signal dans le lot — rien a confronter")
        return out.getvalue()
    diff = [x for x in lignes if x["issue_core"] != x["issue_ref"]]
    ecarts = [abs(x["pnl_core"] - x["pnl_ref"]) for x in lignes
              if x["pnl_core"] is not None and x["pnl_ref"] is not None]
    couples = collections.Counter((x["issue_core"], x["issue_ref"]) for x in diff)
    n_meme = sum(1 for x in lignes if x["meme_barre"])
    indet = [x for x in lignes if x["issue_ref"] == "INDETERMINE"]

    p("=== CONFRONTATION triple_barriere : CORE vs reference ===")
    p("  signaux confrontes         : %d" % n)
    p("  issues qui DIFFERENT        : %d (%.1f %%)" % (len(diff), 100.0 * len(diff) / n))
    if ecarts:
        p("  |pnl_atr core - ref| moyen  : %.4f ATR (max %.4f) sur %d resolus"
          % (sum(ecarts) / len(ecarts), max(ecarts), len(ecarts)))
    p("  TP+SL meme barre (C3)       : %d (%.1f %%)" % (n_meme, 100.0 * n_meme / n))

    p("\n  DIVERGENCES D'ISSUE (core -> ref) :")
    if couples:
        for (ic, ir), k in couples.most_common():
            p("     %-12s -> %-12s : %d" % (ic, ir, k))
    else:
        p("     AUCUNE — les cinq conventions sont les MEMES.")

    # (2) INDETERMINE residuel = jour dont la derniere barre cash != 945
    p("\n  INDETERMINE residuels (attendu 0) : %d" % len(indet))
    for x in indet:
        p("     %s %s : derniere barre cash = %s (attendu 945) — jour a NOMMER"
          % (x["sym"], x["jour"], x["barre_fin"]))

    # (3) repartition horaire des divergences (les trades coupes par la cloture)
    if diff:
        p("\n  REPARTITION HORAIRE des %d divergences (heure d'entree ET) :" % len(diff))
        par_h = collections.Counter(int(x["h_entree"] // 60) for x in diff
                                    if x["h_entree"] is not None)
        for h in sorted(par_h):
            p("     %02dh : %d" % (h, par_h[h]))
    return out.getvalue()


def main():
    os.chdir(RACINE)
    if len(sys.argv) > 1:
        jours = [sys.argv[1]]
    else:
        jours = sorted(set(jours_disponibles("ES")) | set(jours_disponibles("NQ")))
    entete = ("CONFRONTATION — %d jour(s), signaux LES_QUATRE, CORE vs reference\n"
              % len(jours))
    corps = tableau(confronter(jours))
    print(entete + corps)
    os.makedirs(os.path.dirname(RAPPORT), exist_ok=True)
    with open(RAPPORT, "w", encoding="utf-8") as fh:
        fh.write(entete + corps)
    print("rapport : %s" % RAPPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
