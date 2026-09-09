"""MARGES DES QUATRE — de combien le LIEU a manqué, hypothèse par hypothèse,
jour par jour. Brique 2 du brief Fable (09/09). Jamais un devenir.

    python -X utf8 V3/marges_quatre.py [YYYYMMDD]

Écrit `LOGS/marges/marges_quatre_<jour>.jsonl` (hors dépôt, hors miroir),
schéma `marges/2` : UNE ligne par hypothèse × instrument, MÊME LES JOURS
MUETS — le dénominateur d'abord.

POURQUOI. 6 journées sur 9 sans signal des quatre : c'est le régime. Un
silence sans marge est un jour perdu — « ES à 1-3 ticks de la bande VAL à
11h45 » a été recalculé à la main le 09/09. Ici c'est une ligne : la distance
minimale au LIEU dans la journée (ticks, signée : ≤ 0 = dedans), l'heure, et
LEQUEL DES DEUX manquait — le lieu, ou la réaction (et laquelle de ses
conditions). Quarante silences deviennent lisibles.

CE QUE CE FICHIER NE FERA JAMAIS. Aucun devenir, aucun prix d'entrée ou de
sortie, rien dont on puisse les déduire. Règle 35 de LECTURE_JOUR_61 :
« bande trop serrée de X ticks sur N jours » est une CALIBRATION, jamais une
PERMISSION de l'élargir pendant la campagne.

L'EXPOSITION NE DÉCIDE RIEN. `exposer()` recompose le lieu, la porte, le
régime et chaque condition de réaction des quatre à partir des MÊMES colonnes
et du même `seuil_ticks` que `hypotheses.py` (gelé) ; `test_marges_quatre.py`
prouve barre à barre, sur des journées réelles, que (lieu & porte & régime &
réactions) == la fonction gelée. Un écart fait tomber le test — jamais une
marge fausse en silence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from CORE.research import hypotheses as H                       # noqa: E402
from CORE.research.hypothesis_runner import (                    # noqa: E402
    injecter_recalculs, signaux_par_franchissement)
from V3 import calendrier                                       # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min               # noqa: E402
from V3.marges import AVERTISSEMENT, ENV, _heure_et             # noqa: E402

VERSION = "2026-09-10b"   # b : porte_jamais_ouverte = JOUR_MUET (Fable Q5)
DOSSIER = "LOGS/marges"
SCHEMA = "marges/2"
ETATS = ("LIEU_REAGI", "LIEU_SANS_REACTION", "QUASI", "LIEU_IMPOSSIBLE",
         "JOUR_MUET")


def _bande(x, bas, haut):
    """Distance signée à la bande [bas ; haut], en ticks : ≤ 0 dedans, > 0 = de
    combien on est dehors. NaN reste NaN (pas de mètre = pas de lieu)."""
    return np.maximum(bas - x, x - haut)


def exposer(df, tick=H.TICK):
    """{hypothese: {cote: {marge, seuil, porte, regime, reactions}}} — la
    décomposition de chaque fonction gelée, colonne par colonne. L'ordre des
    réactions est celui de la docstring gelée : la PREMIÈRE qui manque nomme
    le manque. `seuil` = l'unité de la marge relative (la proximité P10, ou
    la borne fine P05 de H6, ou P20 de H8)."""
    def f(c):
        return H._f(df, c)
    p05 = H.seuil_ticks(df["atr_ref"], "P05", tick)
    p10 = H.seuil_ticks(df["atr_ref"], "P10", tick)
    p15 = H.seuil_ticks(df["atr_ref"], "P15", tick)
    p20 = H.seuil_ticks(df["atr_ref"], "P20", tick)
    vrai = pd.Series(True, index=df.index)
    fin, close = f("finish_delta_pct"), f("close")
    dh, dl = f("dist_cur_vah"), f("dist_cur_val")            # H3 : VA courante
    vah, val = close + dh * tick, close - dl * tick
    du, dd = f("dist_vwap_rth_sd2u_r"), f("dist_vwap_rth_sd2d_r")   # H2p
    delta, ib_r = f("delta_bar"), H._ib_range_atr_r(df, tick)
    ih, il = f("dist_ib_high"), f("dist_ib_low")             # H6p
    pres = pd.concat([f(c).abs() for c in H.NIVEAUX_H8], axis=1).min(axis=1)
    rvol, dp = f("rvol_r"), f("delta_pct")                   # H8p
    return {
        "H3-VPOC": {
            "short": dict(marge=dh.abs() - p10, seuil=p10, porte=vrai, regime=vrai,
                          reactions={"meche": f("high") > vah,
                                     "cloture_dedans": dh > 0, "finish": fin < 0.4}),
            "long": dict(marge=dl.abs() - p10, seuil=p10, porte=vrai, regime=vrai,
                         reactions={"meche": f("low") < val,
                                    "cloture_dedans": dl > 0, "finish": fin > 0.6})},
        "H2p": {
            "short": dict(marge=_bande(du, -p15, p10), seuil=p10, porte=vrai,
                          regime=ib_r < 0.8,
                          reactions={"delta": delta < 0, "finish": fin < 0.4}),
            "long": dict(marge=_bande(dd, -p10, p15), seuil=p10, porte=vrai,
                         regime=ib_r < 0.8,
                         reactions={"delta": delta > 0, "finish": fin > 0.6})},
        "H6p": {
            "long": dict(marge=_bande(ih, -p15, p05), seuil=p05,
                         porte=f("ib_broken_up") == 1, regime=ib_r < 0.4,
                         reactions={"cloture_au_dela": ih < 0, "finish": fin > 0.6}),
            "short": dict(marge=_bande(il, -p15, p05), seuil=p05,
                          porte=f("ib_broken_dn") == 1, regime=ib_r < 0.4,
                          reactions={"cloture_au_dela": il < 0, "finish": fin < 0.4})},
        "H8p": {
            "long": dict(marge=pres - p20, seuil=p20, porte=vrai, regime=vrai,
                         reactions={"rvol": rvol >= 1.8, "delta": dp <= -0.18,
                                    "finish": fin > 0.6}),
            "short": dict(marge=pres - p20, seuil=p20, porte=vrai, regime=vrai,
                          reactions={"rvol": rvol >= 1.8, "delta": dp >= 0.18,
                                     "finish": fin < 0.4})},
    }


def recomposer(e):
    """(lieu & porte & régime & toutes les réactions) — ce que le test compare
    barre à barre à la fonction gelée."""
    out = ((pd.to_numeric(e["marge"], errors="coerce") <= 0)
           & e["porte"].fillna(False).astype(bool)
           & e["regime"].fillna(False).astype(bool))
    for r in e["reactions"].values():
        out = out & r.fillna(False).astype(bool)
    return out


def resumer(df, hyp, cotes, fn):
    """Une ligne par hypothèse × jour : la marge minimale (côté, heure, seuil,
    atr_source), l'état, et — quand le lieu était là — ce qui a manqué."""
    meilleur, manques = None, {}
    n_lieu = n_signaux = 0
    porte_ouverte = regime_au_lieu = False
    for cote, e in cotes.items():
        gelee = fn(df)[cote][0].fillna(False).astype(bool)
        n_signaux += len(signaux_par_franchissement(gelee, df["jour"]))
        porte = e["porte"].fillna(False).astype(bool)
        porte_ouverte |= bool(porte.any())
        marge = pd.to_numeric(e["marge"], errors="coerce").where(porte)
        m = marge.to_numpy(dtype=float)
        if np.isfinite(m).any():
            i = int(np.nanargmin(m))
            if meilleur is None or m[i] < meilleur[0]:
                meilleur = (float(m[i]), i, cote, float(e["seuil"].iloc[i]))
        lieu = (marge <= 0) & porte
        reg = e["regime"].fillna(False).astype(bool)
        au_lieu = lieu & reg
        regime_au_lieu |= bool(au_lieu.any())
        sans = au_lieu & ~gelee
        n_lieu += int(sans.sum())
        for k in np.flatnonzero(sans.to_numpy()):
            for nom, r in e["reactions"].items():     # la PREMIÈRE qui manque
                if not bool(r.fillna(False).iloc[k]):
                    manques[nom] = manques.get(nom, 0) + 1
                    break
        hors_regime = int((lieu & ~reg).sum())
        if hors_regime:
            manques["regime"] = manques.get("regime", 0) + hors_regime
    if n_signaux:
        etat, motif = "LIEU_REAGI", None
    elif n_lieu or manques.get("regime"):
        etat, motif = "LIEU_SANS_REACTION", None
    elif meilleur is None and not porte_ouverte:
        # Fable Q5 (10/09) : une IB jamais cassee est une mesure PRISE dont la
        # precondition n'a pas eu lieu — c'est le DENOMINATEUR qui dit combien
        # H6p est rare, il reste dedans. JOUR_MUET, pas LIEU_IMPOSSIBLE.
        etat, motif = "JOUR_MUET", "porte_jamais_ouverte"
    elif meilleur is None:
        # LIEU_IMPOSSIBLE = la mesure n'a PAS pu etre prise : hors denominateur.
        etat = "LIEU_IMPOSSIBLE"
        motif = ("atr_ref_absent"
                 if pd.to_numeric(df["atr_ref"], errors="coerce").isna().all()
                 else "colonne_absente")
    elif meilleur[3] and meilleur[0] <= meilleur[3]:
        etat, motif = "QUASI", None
    else:
        etat, motif = "JOUR_MUET", "lieu_loin"
    return {
        "type": "marge_quatre", "hypothese": hyp, "etat": etat, "motif": motif,
        "lieu_min_ticks": round(meilleur[0], 2) if meilleur else None,
        "seuil_ticks": round(meilleur[3], 2) if meilleur else None,
        "marge_rel": (round(meilleur[0] / meilleur[3], 3)
                      if meilleur and meilleur[3] else None),
        "cote": meilleur[2] if meilleur else None,
        "lieu_min_heure_et": _heure_et(df["ts"].iloc[meilleur[1]]) if meilleur else None,
        "atr_source": str(df["atr_source"].iloc[meilleur[1]]) if meilleur else None,
        "lieu_atteint": bool(n_signaux or n_lieu or manques.get("regime")),
        "regime_au_lieu": regime_au_lieu,
        "reaction_manquante": max(manques, key=manques.get) if manques else None,
        "manques": manques, "n_barres_lieu": n_lieu, "n_signaux": n_signaux,
        "n_barres": int(len(df)),
    }


def _muette(hyp, sym, n, motif):
    return {"type": "marge_quatre", "hypothese": hyp, "sym": sym,
            "etat": "JOUR_MUET", "motif": motif, "n_barres": n,
            "n_signaux": 0, "n_barres_lieu": 0, "lieu_atteint": False}


def courir(jour):
    os.chdir(RACINE)
    os.makedirs(DOSSIER, exist_ok=True)
    chemin = os.path.join(DOSSIER, "marges_quatre_%s.jsonl" % jour)
    ferie = calendrier.est_ferie(jour)
    lignes, entete = [], {}
    for sym in ("ES", "NQ"):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if df.empty or len(df) < 6:
            entete[sym] = {"n_barres": int(len(df))}
            lignes += [_muette(h, sym, int(len(df)), "jour_sans_donnee")
                       for h in H.LES_QUATRE]
            continue
        recalc.ts_plage(df["ts"])                    # invariant d'unité, fail-loud
        df = injecter_recalculs(pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                                          ignore_index=True), df, minutes=15)
        entete[sym] = {"n_barres": int(len(df)), "ts_debut": int(df["ts"].iloc[0]),
                       "ts_fin": int(df["ts"].iloc[-1]),
                       "atr_source": {k: int(v) for k, v in
                                      df["atr_source"].value_counts().items()}}
        expo = exposer(df)
        for hyp, fn in H.LES_QUATRE.items():
            lignes.append(dict(resumer(df, hyp, expo[hyp], fn), sym=sym))
    for o in lignes:
        o.update(schema=SCHEMA, jour=jour, marges_version=VERSION)
    tete = {"type": "entete", "schema": SCHEMA, "jour": jour,
            "marges_version": VERSION, "env": ENV, "ferie": ferie, "sym": entete,
            "hypotheses": list(H.LES_QUATRE), "etats": list(ETATS),
            "avertissement": AVERTISSEMENT}
    with open(chemin + ".tmp", "w", encoding="utf-8") as fh:      # jamais append
        for o in [tete] + lignes:
            fh.write(json.dumps(o, ensure_ascii=False, default=float) + "\n")
    os.replace(chemin + ".tmp", chemin)
    par_etat = {}
    for o in lignes:
        par_etat[o["etat"]] = par_etat.get(o["etat"], 0) + 1
    print("%s — %d lignes (hypothèse × instrument) : %s" % (jour, len(lignes), par_etat))
    for o in lignes:
        print("  %s %-8s %-19s marge_min %6s t (seuil %s, %s, %s) manque=%s"
              % (o["sym"], o["hypothese"], o["etat"] + ("(%s)" % o["motif"] if o["motif"] else ""),
                 o.get("lieu_min_ticks"), o.get("seuil_ticks"), o.get("cote"),
                 o.get("lieu_min_heure_et"), o.get("reaction_manquante")))
    print("  -> %s" % chemin)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Marges des quatre — le lieu manqué")
    ap.add_argument("jour", nargs="?", help="YYYYMMDD (défaut : aujourd'hui UTC)")
    a = ap.parse_args()
    return courir(a.jour or pd.Timestamp.utcnow().strftime("%Y%m%d"))


if __name__ == "__main__":
    sys.exit(main())
