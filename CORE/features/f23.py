"""F23 — la mémoire de session : ce que le prix a fait de ses références.

Une **fiche par test** d'un niveau, sur clé de session. Sert L1 (le biais
narratif) et L3 (premier test contre troisième, le piège) : on la construit une
fois, deux couches la lisent.

    from CORE.features import f23
    fiches = f23.fiches(df15, df1, "dist_cur_vah", tick=0.25)
    s = f23.scalaires(fiches, i_courant=42)


POURQUOI PAS LES COLONNES DU C++
---------------------------------
`vah_touches_20b` compte sur **vingt barres d'une minute** — vingt minutes de
mémoire pour un biais de journée — et sa définition de « touche » vit dans le
C++. Les colonnes F21 (`ctx_double_top_trap`, `ctx_failed_auction`,
`ctx_poor_high/low`) sont toutes en provenance **B** : la valeur est plausible,
la formule n'est pas vérifiée. Fenêtre inconnue, seuils inconnus.

C'est la règle qui a fait retirer `mq_gamma_condition`.


LES QUATRE DÉFINITIONS, ÉCRITES AVANT LE CODE
----------------------------------------------
    touche   l'écart barre-niveau <= z_touche ATR, ET le prix s'était éloigné
             d'au moins z_reset depuis la touche précédente
    tenue    la barre suivante clôture du côté d'où le prix venait
    cassure  DEUX clôtures 15 min consécutives de l'autre côté
    regain   une cassure, puis un retour avec tenue

**L'hystérésis n'est pas un raffinement.** Sans elle, « la barre est près du
niveau » vaut pour 38 à 53 % des barres, soit quatorze touches par jour sur la
VAH seule : la value area contient 70 % du volume, le prix y séjourne et ne la
teste pas. Avec `z_reset = 0,5 ATR`, 1,2 à 1,6 par niveau.

**La cassure à deux clôtures** est l'acceptation de Dalton — une seule clôture
de l'autre côté est un dépassement, pas une acceptation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ISSUES = ("tenu", "casse", "regagne", "indetermine")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _ecart_atr(df, col, tick):
    """Écart entre la barre et le niveau, en ATR. Négatif = la barre englobe.

    `dist = niveau - close` en TICKS, l'ATR en POINTS : le tick est
    indispensable, sans lui le rapport est faux d'un facteur quatre.
    """
    d = _num(df[col]).abs() * tick
    demi = (df["high"] - df["low"]) / 2.0
    return (d - demi) / _num(df["atr_barre"])


def _cote(df, col, i):
    """+1 si le prix teste le niveau PAR LE DESSOUS, -1 par le dessus.

    `dist = niveau - close` : positif veut dire que le niveau est au-dessus du
    prix, donc le prix monte vers lui.
    """
    v = _num(pd.Series([df[col].iloc[i]])).iloc[0]
    if not np.isfinite(v) or v == 0:
        return 0
    return 1 if v > 0 else -1


def _issue(df, col, i, cote, fenetre=8):
    """`tenu`, `casse`, `regagne` ou `indetermine`, plus l'indice de fin.

    Cassure = deux clôtures consécutives de l'autre côté. Regain = une cassure
    puis un retour avec tenue. La fenêtre borne la recherche : au-delà, ce
    n'est plus la même séquence.
    """
    d = _num(df[col])
    n_contre = 0
    casse_a = None
    for k in range(i + 1, min(i + 1 + fenetre, len(df))):
        v = d.iloc[k]
        if not np.isfinite(v):
            continue
        # le prix est passe de l'autre cote si le signe de dist s'inverse
        de_l_autre_cote = (v > 0) != (cote > 0)
        if casse_a is None:
            n_contre = n_contre + 1 if de_l_autre_cote else 0
            if n_contre >= 2:
                casse_a = k
        elif not de_l_autre_cote:
            return "regagne", k, casse_a
    if casse_a is not None:
        return "casse", min(i + fenetre, len(df) - 1), casse_a
    if i + 1 < len(df):
        v = d.iloc[i + 1]
        if np.isfinite(v) and (v > 0) == (cote > 0):
            return "tenu", i + 1, None
    return "indetermine", min(i + 1, len(df) - 1), None


def _reaction_atr(df, i, cote, k=4):
    """Excursion maximale dans le sens du REJET, en ATR. Le résultat.

    Un test par le dessous qui tient produit une baisse : le rejet va vers le
    bas. Effort sans résultat = faiblesse, et c'est la seule ligne de la fiche
    qui ne soit pas une colonne — elle se calcule.
    """
    a = _num(pd.Series([df["atr_barre"].iloc[i]])).iloc[0]
    if not np.isfinite(a) or a <= 0:
        return np.nan
    fin = min(i + k, len(df) - 1)
    ref = df["close"].iloc[i]
    if cote > 0:                       # teste par le dessous -> rejet vers le bas
        return float((ref - df["low"].iloc[i + 1:fin + 1].min()) / a) if fin > i else np.nan
    return float((df["high"].iloc[i + 1:fin + 1].max() - ref) / a) if fin > i else np.nan


def _piege(df1, df15, i_casse, i_fin, col, cote, tick):
    """Qui est resté coincé au-delà du niveau — compté sur les barres 1 MIN.

    Une barre de quinze minutes qui traverse un niveau et revient ne dit pas
    combien de contrats se sont échangés de l'autre côté. Le volume piégé et
    son delta se comptent minute par minute, entre la cassure et le regain.
    """
    vide = {"volume_au_dela": None, "delta_au_dela": None,
            "duree_au_dela": None, "dist_piege": None}
    if df1 is None or df1.empty or i_casse is None or "ts" not in df1.columns:
        return vide
    t0 = int(df15["ts"].iloc[i_casse])
    t1 = int(df15["ts"].iloc[min(i_fin, len(df15) - 1)])
    m = (_num(df1["ts"]) >= t0) & (_num(df1["ts"]) <= t1)
    bloc = df1[m]
    if bloc.empty:
        return vide
    niveau = df15["close"].iloc[i_casse] + _num(
        pd.Series([df15[col].iloc[i_casse]])).iloc[0] * tick
    # au-dela = du cote oppose a celui d'ou le prix testait
    au_dela = (bloc["close"] > niveau) if cote > 0 else (bloc["close"] < niveau)
    b = bloc[au_dela]
    if b.empty:
        return vide
    a = _num(pd.Series([df15["atr_barre"].iloc[i_casse]])).iloc[0]
    extreme = b["high"].max() if cote > 0 else b["low"].min()
    return {
        "volume_au_dela": float(_num(b["total_vol"]).sum()) if "total_vol" in b else None,
        "delta_au_dela": float(_num(b["delta_bar"]).sum()) if "delta_bar" in b else None,
        "duree_au_dela": int(len(b)),
        "dist_piege": (float(abs(extreme - niveau) / a)
                       if np.isfinite(a) and a > 0 else None),
    }


def fiches(df15, df1=None, col="dist_cur_vah", tick=0.25, z_touche=0.0,
           z_reset=0.5, k_reaction=4):
    """Une fiche par test du niveau `col`, dans l'ordre chronologique.

    `z_touche` et `z_reset` sont MESURÉS (06/09) — cf `seuils.yaml` de L1. Le
    second a été choisi sur la **discrimination** : à 0,5 ATR, « deux, trois,
    quatre tests » existe dans 45 % des cas ; à 1,5 le compteur est un booléen
    déguisé. C'est un choix raisonné sur une distribution, pas une valeur lue
    dans une distribution — la nuance compte.
    """
    if col not in df15.columns or "atr_barre" not in df15.columns:
        return []
    ecart = _ecart_atr(df15, col, tick)
    out, arme = [], True
    for i in range(len(df15)):
        e = ecart.iloc[i]
        if not np.isfinite(e):
            continue
        if not arme:
            if e >= z_reset:
                arme = True
            continue
        if e > z_touche:
            continue
        arme = False
        cote = _cote(df15, col, i)
        if cote == 0:
            continue
        issue, i_fin, i_casse = _issue(df15, col, i, cote)
        f = {
            "i": i, "ts": int(df15["ts"].iloc[i]), "niveau": col, "cote": cote,
            # effort — combien il a fallu se battre
            "rvol": _val(df15, "rvol", i), "total_vol": _val(df15, "total_vol", i),
            # qui pousse
            "delta_pct": _val(df15, "delta_pct", i),
            "ask_pct": _val(df15, "ask_pct", i),
            # contexte cumule
            "cvd_day": _val(df15, "cvd_day", i),
            # forme
            "meche_haut": _val(df15, "bar_upper_wick_pct", i),
            "meche_bas": _val(df15, "bar_lower_wick_pct", i),
            "finish": _val(df15, "finish_delta_pct", i),
            # gros ordres
            "big_ask": _val(df15, "max_big_ask_vol_in_bar", i),
            "big_bid": _val(df15, "max_big_bid_vol_in_bar", i),
            # resultat, puis issue
            "reaction_atr": _reaction_atr(df15, i, cote, k_reaction),
            "issue": issue,
        }
        f.update(_piege(df1, df15, i_casse, i_fin, col, cote, tick))
        out.append(f)
    return out


def _val(df, col, i):
    if col not in df.columns:
        return None
    v = _num(pd.Series([df[col].iloc[i]])).iloc[0]
    return None if not np.isfinite(v) else float(v)


def scalaires(fiches_du_niveau, i_courant):
    """Les quatre scalaires que `lecture.py` expose. Une porte ne lit pas une
    liste.

    `defense_tendance` < 1 veut dire que la défense S'USE : la réaction du
    dernier test est plus faible que celle du premier. C'est ce qui distingue
    « le niveau a tenu trois fois » de « le niveau a tenu trois fois de moins
    en moins bien ».
    """
    passees = [f for f in fiches_du_niveau if f["i"] <= i_courant]
    if not passees:
        return {"n_tests": 0, "defense_derniere": None,
                "defense_tendance": None, "cvd_cote_defense": None,
                "issue": None}
    d = passees[-1]
    r0 = passees[0].get("reaction_atr")
    rn = d.get("reaction_atr")
    tendance = (float(rn / r0) if r0 and rn and np.isfinite(r0)
                and np.isfinite(rn) and r0 > 0 else None)
    cvd = d.get("cvd_day")
    return {
        "n_tests": len(passees),
        # effort x resultat : se battre beaucoup pour rien n'est pas une defense
        "defense_derniere": (float(d["rvol"] * rn)
                             if d.get("rvol") and rn and np.isfinite(rn) else None),
        "defense_tendance": tendance,
        # le delta du jour est-il du cote de ceux qui defendent le niveau ?
        "cvd_cote_defense": (bool((cvd > 0) == (d["cote"] < 0))
                             if cvd is not None else None),
        "issue": d["issue"],
    }
