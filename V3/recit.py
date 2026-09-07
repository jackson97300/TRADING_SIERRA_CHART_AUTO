"""RECIT — F23 raconte la journée EXACTEMENT, sans grain de sel.

    python -X utf8 V3/recit.py [YYYYMMDD] [--sym ES]

**Le récit est un test, pas une prose.** Trois règles, nées de la
contre-lecture du 08/09 où « cassée 03:00 » désignait une cassure de 04:15 :

1. chaque phrase porte sa preuve — le niveau EN PRIX, l'heure de CHAQUE
   événement (le test, la cassure, le regain), jamais l'heure du test pour
   tout ;
2. lexique fermé : touche, tenue, cassure, regain, piège — aucun mot hors
   des quatre définitions écrites dans `f23.py` ;
3. chaque chiffre de piège est RECOMPTÉ ici depuis les barres 1 min brutes,
   indépendamment de la fiche. Un écart > 5 % = ECART affiché, code retour 1.
   Le récit se vérifie lui-même à chaque exécution.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import agreger                            # noqa: E402
from CORE.features import recalc                                 # noqa: E402
from CORE.features import f23                                    # noqa: E402

NIVEAUX = ("dist_prev_vah", "dist_prev_val", "dist_prev_vpoc",
           "dist_cur_vah", "dist_cur_val", "dist_cur_vpoc")


def _hh(ts):
    return pd.Timestamp(int(ts), unit="ms", tz="UTC").strftime("%H:%M")


def _recompter(df1, f):
    """Le piège, recompté depuis les barres 1 min brutes — PAS depuis la fiche.

    C'est la contre-lecture d'hier, mécanisée : volume et delta échangés
    au-delà du niveau (en prix), entre ts_casse et la fin de ts_connu.
    """
    if f.get("ts_casse") is None or f.get("niveau_prix") is None:
        return None
    ts = pd.to_numeric(df1["ts"], errors="coerce")
    m = (ts >= f["ts_casse"]) & (ts <= f["ts_connu"] + f23.MS_PAR_BARRE - 1)
    bloc = df1[m]
    au_dela = (bloc["close"] > f["niveau_prix"]) if f["cote"] > 0 \
        else (bloc["close"] < f["niveau_prix"])
    b = bloc[au_dela]
    if b.empty:
        return {"vol": 0.0, "delta": 0.0}
    return {"vol": float(pd.to_numeric(b["total_vol"], errors="coerce").sum()),
            "delta": float(pd.to_numeric(b["delta_bar"], errors="coerce").sum())}


def _charger_session_entiere(sym, jour):
    """La journee ENTIERE — nuit comprise. `charger_jour` filtre au cash, et un
    recit qui commence a 9h30 rate la moitie de l'histoire : les niveaux de la
    veille se testent la nuit."""
    import glob
    import json
    fs = sorted(glob.glob("DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)))
    lignes = []
    for fp in fs:
        for ln in open(fp, encoding="utf-8", errors="ignore"):
            if ln[:1] == "{":
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if d.get("data_quality_flag") == "stable":
                    lignes.append(d)
    if not lignes:
        return pd.DataFrame(), pd.DataFrame()
    lignes = recalc.dedoublonner_par_minute(lignes)
    df1 = pd.DataFrame(lignes)
    df1["ts"] = recalc.horodatage(df1)
    df1 = df1.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df1["dt"] = pd.to_datetime(df1["ts"], unit="ms", utc=True)
    return agreger(df1, 15), df1


def raconter(sym, jour):
    df15, df1 = _charger_session_entiere(sym, jour)
    if df15.empty:
        print("  %s %s : aucune barre" % (sym, jour))
        return 0
    print("%s %s — %d barres 15 min, %s -> %s UTC" % (
        sym, jour, len(df15), _hh(df15["ts"].iloc[0]), _hh(df15["ts"].iloc[-1])))
    ecarts = 0
    for col in NIVEAUX:
        fs = f23.fiches(df15, df1, col)
        for f in fs:
            nom = col.replace("dist_", "")
            niv = ("%.2f" % f["niveau_prix"]) if f.get("niveau_prix") else "?"
            cote = "dessous" if f["cote"] > 0 else "dessus"
            tete = "  %s  %s %s teste par le %s" % (_hh(f["ts"]), nom, niv, cote)
            if f["issue"] == "tenu":
                print("%s — TENU (cloture suivante du bon cote a %s)"
                      % (tete, _hh(f["ts_connu"])))
            elif f["issue"] in ("casse", "regagne"):
                quand_casse = _hh(f["ts_casse"]) if f.get("ts_casse") else "?"
                fin = (" — REGAGNE a %s (2 clotures revenues)" % _hh(f["ts_connu"])
                       if f["issue"] == "regagne" else
                       " — reste casse a %s" % _hh(f["ts_connu"]))
                print("%s — CASSE a %s (2e cloture au-dela)%s"
                      % (tete, quand_casse, fin))
                re = _recompter(df1, f)
                vol_f = f.get("volume_au_dela") or 0.0
                if re is None:
                    print("        piege : NON VERIFIABLE (bornes absentes)")
                elif re["vol"] <= 0:
                    print("        cassure sans volume mesurable au-dela")
                else:
                    ok = vol_f and abs(re["vol"] - vol_f) / re["vol"] <= 0.05
                    print("        PIEGE %d contrats (delta %+d) entre %s et %s "
                          "%s le niveau%s"
                          % (re["vol"], re["delta"], quand_casse,
                             _hh(f["ts_connu"]),
                             "au-dessus de" if f["cote"] > 0 else "sous",
                             "" if ok else
                             "  << ECART : la fiche dit %d" % vol_f))
                    if not ok:
                        ecarts += 1
            else:
                print("%s — %s (rien d'affirme au-dela)"
                      % (tete, f["issue"].upper()))
    return ecarts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jour", nargs="?", default="20260907")
    ap.add_argument("--sym", default=None)
    a = ap.parse_args()
    os.chdir(RACINE)
    ecarts = 0
    for sym in ([a.sym] if a.sym else ["ES", "NQ"]):
        ecarts += raconter(sym, a.jour)
        print()
    if ecarts:
        print("%d ECART(S) fiche/recomptage : le recit N'EST PAS publiable." % ecarts)
        return 1
    print("Chaque chiffre ci-dessus a ete recompte depuis les barres brutes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
