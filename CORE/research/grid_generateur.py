"""Grid search — GENERATEUR d'hypotheses, jamais juge.

LA REGLE, ET ELLE N'A PAS D'EXCEPTION
--------------------------------------
Un grid qui cherche ET juge sur les memes jours se trompe avec une probabilite
proche de 1. A un seuil de 5 %, N x 0,05 combinaisons « passent » par pur hasard :
sur 200 essais, dix survivantes garanties, toutes fausses. C'est l'incident #28 du
depot — 600 combinaisons, 5 sur 5 rejetees en validation. La methode n'avait pas
mal tourne : elle a fait ce qu'elle fait toujours sur peu de donnees.

Ce module explore les 40 jours **deja brules** par trois lectures, et n'en tire
AUCUN verdict. Il rend une liste de candidats, avec le nombre exact d'essais.
Le jugement appartient au mode ombre, sur des jours que personne n'a vus.

CE QUE CELA COUTE, ET QU'IL FAUT SAVOIR AVANT
----------------------------------------------
Garder les k meilleurs sur N essais revient a selectionner **les k meilleurs du
bruit**. Sur un echantillon independant, ils n'ont aucune raison de faire mieux
que le hasard : le rendement attendu d'un grid pur est nul.

Ce qui le releve — principe de Lopez de Prado — est de **ne retenir que les
candidats qui ont aussi une justification economique**. Le grid propose, la
theorie filtre, le temps juge. Un candidat sans mecanisme nommable est rejete
meme s'il sort premier.

POURQUOI L'ORDER FLOW, ET PAS TOUT L'ESPACE
--------------------------------------------
arXiv:2605.04004 (Mesfin, 2026) teste 14 familles OHLCV sur 947 jours de MNQ :
aucune ne passe, rendement brut maximal sous le cout de friction. Ratisser
l'OHLCV serait refaire, sur 40 jours, ce qui a echoue sur 947.

La litterature designe une seule porte encore ouverte : l'Order Flow Imbalance,
IC +0,0044 (+0,0022 hors echantillon), et surtout un R² ajuste **superieur a
l'OHLCV seul**. C'est exactement ce que ces donnees contiennent et que le papier
MNQ n'avait pas. Le grid est donc restreint a cet espace — restreindre l'espace
est la seule facon honnete de reduire le nombre d'essais.
"""

from __future__ import annotations

import itertools
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from CORE.research.hypothesis_runner import (  # noqa: E402
    COUT_DOLLARS, VAL_POINT, evaluer, preparer, signaux_par_franchissement)
from CORE.research.hypotheses import seuil_ticks  # noqa: E402

# --- L'espace, restreint et justifie ----------------------------------------
# Order flow : la seule famille ou la litterature mesure un avantage sur l'OHLCV.
FLUX = ["delta_pct", "finish_delta_pct", "ask_pct", "rvol_r",
        "delta_div_strength", "aggressor_imbalance", "ctx_absorption_score_5",
        "ctx_delta_sum_3", "cvd_day", "n_clusters_20t"]

# Lieux : ou le flux se lit. Un flux sans lieu est du bruit de marche.
LIEUX = {"VAH": "dist_cur_vah", "VAL": "dist_cur_val",
         "VWAP": "dist_vwap_rth_r", "SD2u": "dist_vwap_rth_sd2u_r",
         "SD2d": "dist_vwap_rth_sd2d_r"}

# Quantiles utilises comme seuils — mesures sur la colonne, jamais devines.
QUANTILES = (0.20, 0.80)
N_MIN = 40                      # meme plancher que la mission


def conditions_flux(df):
    """Conditions elementaires sur le flux, seuils pris dans la distribution."""
    out = []
    for c in FLUX:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        if v.notna().mean() < 0.5 or v.nunique() < 5:
            continue
        for q in QUANTILES:
            s = float(v.quantile(q))
            for op, m in ((">", v > s), ("<", v < s)):
                # Une condition vraie presque partout ne filtre rien : elle
                # gonfle le nombre d essais avec du vide et remonte en tete du
                # classement sans rien apporter. Mesure : finish_delta_pct a
                # une mediane de 1,00, donc "< 1" est vrai 4 fois sur 5.
                part = float(m.mean())
                if not (0.05 <= part <= 0.60):
                    continue
                out.append(("%s%s%.4g(q%.0f)" % (c, op, s, 100 * q), m, c))
    return out


def conditions_lieu(df):
    p = seuil_ticks(df["atr5"], "P20")
    out = []
    for nom, col in LIEUX.items():
        if col not in df.columns:
            continue
        v = pd.to_numeric(df[col], errors="coerce")
        if v.notna().mean() < 0.5:
            continue
        out.append(("@%s" % nom, v.abs() <= p, col))
    return out


def explorer(sym, max_essais=None):
    """Rend (candidats, n_essais). **Aucun verdict.**"""
    df, jours = preparer(sym)
    if df.empty:
        return pd.DataFrame(), 0
    lieux, flux = conditions_lieu(df), conditions_flux(df)
    couts = (COUT_DOLLARS[sym], VAL_POINT[sym])

    lignes, essais = [], 0
    for (nl, cl, _), (n1, c1, col1), (n2, c2, col2) in itertools.product(
            lieux, flux, flux):
        if n1 >= n2:                       # paires non ordonnees, pas de doublon
            continue
        if col1 == col2:
            # Deux conditions sur la MEME colonne sont soit redondantes
            # (delta>q20 ET delta>q80 se reduit a delta>q80), soit une bande
            # deguisee. Dans les deux cas la regle n a pas deux conditions,
            # elle en a une — et elle sortait en tete du premier run.
            continue
        for side in (+1, -1):
            essais += 1
            if max_essais and essais > max_essais:
                break
            cond = cl & c1 & c2
            idx = signaux_par_franchissement(cond, df["jour"])
            if len(idx) < N_MIN:
                continue
            t = evaluer(df, cond, side, couts_atr=couts)
            if len(t) < N_MIN:
                continue
            lignes.append({
                "regle": "%s & %s & %s" % (nl, n1, n2),
                "side": side, "N": len(t),
                "esperance_atr": round(float(t["pnl_atr"].mean()), 4),
                "jours": int(t["jour"].nunique()),
            })
    c = pd.DataFrame(lignes)
    if not c.empty:
        c = c.sort_values("esperance_atr", ascending=False).reset_index(drop=True)
    return c, essais


if __name__ == "__main__":
    mx = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print("GRID — GENERATEUR d'hypotheses. Aucun verdict n'est rendu ici.")
    print("Espace restreint a l'order flow (arXiv:2605.04004 : l'OHLCV est"
          " epuise).\n")
    for sym in ("NQ", "ES"):
        cand, n = explorer(sym, mx)
        print("=== %s — %d essais comptes, %d regles atteignent N>=%d ==="
              % (sym, n, len(cand), N_MIN))
        if len(cand):
            print(cand.head(8).to_string(index=False))
            print("\n  attendu sous l'hypothese nulle : %.0f regles 'gagnantes'"
                  " par pur hasard a 5 %%" % (0.05 * n))
        print()
    print("Ces regles sont des CANDIDATES. Elles ne valent rien tant qu'elles")
    print("n'ont pas tourne sur des jours que personne n'a vus.")
