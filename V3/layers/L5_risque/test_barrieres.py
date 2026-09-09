"""Tests des barrières L5 — brief §7.

    python -X utf8 V3/layers/L5_risque/test_barrieres.py

Miroir LONG/SHORT × {niveau trouvé, aucun niveau, plafonné, veto frais},
le niveau se FIGE au signal, le buffer est dans le bon sens, l'anti-proxy,
et la parité B-ATR = `triple_barriere()` sur 100 signaux réels.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.research.hypothesis_runner import triple_barriere   # noqa: E402
from V3.layers.L5_risque import barrieres as B                # noqa: E402

S_NIV = {"sl_fenetre_atr": [0.5, 1.5], "tp_min_atr": 0.5,
         "marge_tp_ticks": 1, "buffer_sweep_atr": {"ES": 0.33},
         "plafond_sl_atr": 1.5, "plafond_tp_atr": 1.5,
         "part_max_frais": 0.10,
         "niveaux": ["prev_vah", "prev_val", "pdh", "pdl"]}
S_ATR = {"seuils": {"sl_atr": 1.0, "tp_atr": 1.5, "expiration_barres": 20}}


def _df(close=100.0, atr=10.0, **dists):
    """Une barre de signal + assez de suite pour l'issue. dists en TICKS."""
    lignes = []
    for i in range(4):
        ligne = {"ts": 1_000_000 + i * 900_000, "open": close, "high": close,
                 "low": close, "close": close, "atr_barre": atr,
                 "atr_ref": atr, "atr_source": "barre"}
        for col, v in dists.items():
            ligne[col] = v
        lignes.append(ligne)
    return pd.DataFrame(lignes)


def main():
    e = []
    entree, atr = 100.0, 10.0

    # --- B-NIV LONG : niveau contre a 1 ATR sous l'entree -------------------
    df = _df(dist_prev_val=(90.0 - 100.0) / 0.25, dist_prev_vah=(107.0 - 100.0) / 0.25)
    r = B.b_niv(df, 0, +1, "ES", S_NIV, entree, atr)
    if r["motif_sl"] != "niveau" or r["niveau_sl"]["nom"] != "prev_val":
        e.append("LONG SL : prev_val a 1,0 ATR devait etre choisi (%s)"
                 % r["motif_sl"])
    if not (r["sl_prix"] < 90.0):
        e.append("LONG buffer : le SL doit etre SOUS le niveau (%.2f)"
                 % r["sl_prix"])
    if abs(r["sl_prix"] - (90.0 - 0.33 * atr)) > 1e-9:
        e.append("LONG buffer : attendu 90 − 3,3 = 86,7 (obtenu %.2f)"
                 % r["sl_prix"])
    if r["motif_tp"] != "niveau" or abs(r["tp_prix"] - (107.0 - 0.25)) > 1e-9:
        e.append("LONG TP : devant prev_vah, 106,75 attendu (%.2f, %s)"
                 % (r["tp_prix"], r["motif_tp"]))

    # --- B-NIV SHORT miroir -------------------------------------------------
    r = B.b_niv(df, 0, -1, "ES", S_NIV, entree, atr)
    if r["niveau_sl"] is None or r["niveau_sl"]["nom"] != "prev_vah":
        e.append("SHORT SL : prev_vah a 0,7 ATR devait etre choisi")
    if not (r["sl_prix"] > 107.0):
        e.append("SHORT buffer : le SL doit etre AU-DESSUS du niveau")

    # --- aucun niveau -> defaut motive, jamais un null nu -------------------
    r = B.b_niv(_df(), 0, +1, "ES", S_NIV, entree, atr)
    if r["motif_sl"] != "defaut_aucun_niveau" or r["niveau_sl"] is not None:
        e.append("aucun niveau : defaut motive attendu (%s)" % r["motif_sl"])
    if r["motif_tp"] != "defaut_aucun_niveau":
        e.append("aucun niveau TP : defaut motive attendu")

    # --- plafonne : niveau a 1,4 ATR + buffer -> depasse 1,5 ----------------
    df = _df(dist_prev_val=(86.0 - 100.0) / 0.25)
    r = B.b_niv(df, 0, +1, "ES", S_NIV, entree, atr)
    if r["motif_sl"] != "plafonne" or not r["plafonne"]:
        e.append("plafond : 1,4 ATR + 0,33 devait plafonner (%s)"
                 % r["motif_sl"])

    # --- veto frais : TP minuscule ------------------------------------------
    df_petit = _df(atr=0.4, dist_prev_val=(99.7 - 100.0) / 0.25)
    r = B.b_niv(df_petit, 0, +1, "ES", S_NIV, entree, 0.4)
    if r["verdict"] != "veto_frais":
        e.append("frais : TP ~0,6 pt sur MES devait etre vetoe (%s)"
                 % r["verdict"])

    # --- le niveau se FIGE au signal ----------------------------------------
    df = _df(dist_prev_val=(90.0 - 100.0) / 0.25, dist_prev_vah=(107.0 - 100.0) / 0.25)
    avant = B.b_niv(df, 0, +1, "ES", S_NIV, entree, atr)
    df2 = df.copy()
    df2.loc[1:, "dist_prev_val"] = (70.0 - 100.0) / 0.25   # bouge DES i+1 — l'off-by-one le plus probable (review R4)
    apres = B.b_niv(df2, 0, +1, "ES", S_NIV, entree, atr)
    if avant["sl_prix"] != apres["sl_prix"] or avant["tp_prix"] != apres["tp_prix"]:
        e.append("FIGE : modifier un dist apres t a change la barriere")

    # --- anti-proxy : gamma_block_* interdit dans les candidats -------------
    reels = B.charger_seuils()
    for nom in reels["B-NIV"]["niveaux"] + reels["B-NIV"].get("niveaux_reduits", []):
        if "gamma" in nom:
            e.append("anti-proxy : « %s » dans les candidats" % nom)

    # --- B-NAT : cible famille figee, defaut motive -------------------------
    df = _df(dist_cur_vpoc=(104.0 - 100.0) / 0.25)
    S_NAT = {"cible_par_famille": {"H3-VPOC": "cur_vpoc_fige", "H2p": "vwap_rth"},
             "sl_atr": 1.0, "plafond_tp_atr": 1.5, "part_max_frais": 0.10}
    r = B.b_nat(df, 0, +1, "ES", S_NAT, entree, atr, "H3-VPOC")
    if r["niveau_tp"] is None or abs(r["tp_prix"] - 104.0) > 1e-9:
        e.append("B-NAT : cible VPOC figee 104,0 attendue (%.2f)" % r["tp_prix"])
    r = B.b_nat(_df(), 0, +1, "ES", S_NAT, entree, atr, "H9")
    if r["motif_tp"] != "pas_de_cible_famille":
        e.append("B-NAT : famille sans cible -> motif attendu")
    r = B.b_nat(_df(), 0, +1, "ES", S_NAT, entree, atr, "H2p")
    if r["motif_tp"] != "cible_non_cablee":
        e.append("B-NAT : vwap_rth non cablee -> motif distinct attendu (%s)"
                 % r["motif_tp"])
    df_atteinte = _df(dist_cur_vpoc=(99.0 - 100.0) / 0.25)
    r = B.b_nat(df_atteinte, 0, +1, "ES", S_NAT, entree, atr, "H3-VPOC")
    if r["motif_tp"] != "cible_deja_atteinte":
        e.append("B-NAT : cible derriere l'entree -> artefact flagge (%s)"
                 % r["motif_tp"])

    # --- parite B-ATR = triple_barriere sur 100 signaux reels ---------------
    n_ok, n_tot = 0, 0
    for jour in ("20260902", "20260903", "20260904"):
        df15 = charger_jour("ES", jour, 15)
        if df15.empty:
            continue
        # parite avec triple_barriere (atr_barre) : le metre est le MEME ici
        df15 = df15.assign(atr_ref=df15["atr_barre"], atr_source="barre")
        for i in range(len(df15) - 2):
            for side in (+1, -1):
                ref = triple_barriere(df15, i, side, B.COUTS["ES"])
                atr_i = float(pd.to_numeric(df15["atr_barre"],
                                            errors="coerce").iloc[i])
                if ref is None or not np.isfinite(atr_i) or atr_i <= 0:
                    continue
                ent = float(df15["open"].iloc[i + 1])
                ba = B.b_atr(ent, atr_i, side, S_ATR)
                mien = B.issue(df15, i, side, ba["sl_prix"], ba["tp_prix"], "ES")
                n_tot += 1
                if (mien is not None and abs(mien[1] - ref[1]) < 1e-9
                        and mien[2] == ref[2]):
                    n_ok += 1
    if n_tot < 80 or n_ok != n_tot:
        e.append("parite B-ATR : %d/%d identiques a triple_barriere"
                 % (n_ok, n_tot))

    print("  barrieres L5 — miroir, defauts motives, plafond, veto frais,")
    print("       fige-au-signal, anti-proxy, B-NAT (3 motifs), parite (%d reels)"
          % n_tot)
    if e:
        print("  %d ECHEC(S) :" % len(e))
        for x in e:
            print("     %s" % x)
        return 1
    print("  OK : le SL est derriere quelque chose, le TP devant, et chaque")
    print("       null porte son motif.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
