"""F23 — la mémoire de session : ce que le prix a fait de ses références.

Une **fiche par test** d'un niveau, sur clé de session. Sert L1 (le biais
narratif) et L3 (premier test contre troisième, le piège) : on la construit une
fois, deux couches la lisent.

    from CORE.features import f23
    fiches = f23.fiches(df15, df1, "dist_cur_vah", tick=0.25)
    s = f23.scalaires(fiches, i_courant=42)


CE QU'UNE FICHE SAIT, ET QUAND ELLE LE SAIT
--------------------------------------------
Une fiche naît à la barre `i` du test, mais son **issue** — tenu, cassé,
regagné — n'est connue qu'à `i_connu`, jusqu'à huit barres plus tard. Le piège
et la réaction aussi.

`scalaires(fiches, i_courant)` ne révèle donc `issue`, `reaction_atr` et le
piège **que si `i_connu <= i_courant`**. Sinon l'issue vaut `en_cours` et les
champs sont `None`.

Sans cette précaution, une couche lirait « cassé » deux heures avant que la
cassure ait lieu : la fiche existe à `i`, et un filtre sur `i` seul laisse
passer tout ce qu'elle apprendra plus tard. C'est la fuite d'avenir dans sa
forme la plus discrète — le code tourne, les chiffres sortent, et ils décrivent
un futur que personne ne connaissait.


POURQUOI PAS LES COLONNES DU C++
---------------------------------
`vah_touches_20b` compte sur **vingt barres d'une minute** — vingt minutes de
mémoire pour un biais de journée — et sa définition de « touche » vit dans le
C++. Les colonnes F21 (`ctx_double_top_trap`, `ctx_failed_auction`,
`ctx_poor_high/low`) sont toutes en provenance **B** : la valeur est plausible,
la formule n'est pas vérifiée.


LES QUATRE DÉFINITIONS, ÉCRITES AVANT LE CODE
----------------------------------------------
    touche   l'écart barre-niveau <= z_touche ATR, ET le prix s'était éloigné
             d'au moins z_reset depuis la touche précédente
    tenue    la barre suivante clôture du côté d'où le prix venait
    cassure  DEUX clôtures 15 min consécutives de l'autre côté
    regain   une cassure, puis DEUX clôtures revenues du côté d'origine

Cassure et regain sont **symétriques** : deux clôtures dans les deux cas. Un
aller-retour d'une seule barre n'est ni une acceptation, ni un regain.

**L'hystérésis n'est pas un raffinement.** Sans elle, « la barre est près du
niveau » vaut pour 38 à 53 % des barres, soit quatorze touches par jour sur la
VAH seule. Avec `z_reset = 0,5 ATR`, 1,2 à 1,6 par niveau.

*Après une cassure, l'hystérésis réarme de l'autre côté : le retest du niveau
devenu support produit une nouvelle fiche, de côté opposé. C'est voulu —
support-turned-resistance — et le test au tick le montre.*
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ISSUES = ("tenu", "casse", "regagne", "en_cours", "indetermine")
MS_PAR_BARRE = 15 * 60 * 1000


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _val(df, col, i):
    if col not in df.columns:
        return None
    v = _num(pd.Series([df[col].iloc[i]])).iloc[0]
    return None if not np.isfinite(v) else float(v)


def _ecart_atr(df, col, tick):
    """Écart entre la barre et le niveau, en ATR. Négatif = la barre englobe.

    `dist = niveau - close` en TICKS, l'ATR en POINTS : sans le tick, le
    rapport est faux d'un facteur quatre.

    *Approximation assumée* : `|dist|·tick − (high−low)/2` suppose la clôture
    au milieu de la barre. « Englobe » est donc approché à une demi-amplitude
    près. Acceptable pour un compteur de tests ; à ne pas utiliser pour placer
    un ordre.
    """
    d = _num(df[col]).abs() * tick
    demi = (df["high"] - df["low"]) / 2.0
    return (d - demi) / _num(df["atr_barre"])


def _cote(df, col, i):
    """+1 si le prix teste le niveau PAR LE DESSOUS, -1 par le dessus.

    Le côté se lit sur **d'où le prix VENAIT**, donc sur la barre précédente.
    Le lire à `i` donnait le côté d'arrivée : une barre qui monte vers un
    niveau et clôture au-dessus était classée « testée par le dessus », et
    l'issue, la réaction et le piège s'inversaient tous les trois.
    """
    j = i - 1 if i > 0 else i
    v = _num(pd.Series([df[col].iloc[j]])).iloc[0]
    if not np.isfinite(v) or v == 0:
        return 0
    return 1 if v > 0 else -1


def _issue(df, col, i, cote, fenetre=8):
    """Rend (issue, i_connu, i_premiere_barre_au_dela).

    `i_connu` est la barre où l'issue devient CONNUE — pas celle du test. Une
    couche qui lit avant cette barre ne doit rien voir.
    """
    d = _num(df[col])
    n_contre = n_revenu = 0
    premiere_au_dela = casse_connue_a = None
    for k in range(i + 1, min(i + 1 + fenetre, len(df))):
        v = d.iloc[k]
        if not np.isfinite(v):
            continue
        de_l_autre_cote = (v > 0) != (cote > 0)
        if casse_connue_a is None:
            if de_l_autre_cote:
                n_contre += 1
                if premiere_au_dela is None:
                    premiere_au_dela = k
                if n_contre >= 2:
                    casse_connue_a = k
            else:
                n_contre = 0
                premiere_au_dela = None
        else:
            # regain : DEUX clotures revenues, symetrique de la cassure
            n_revenu = n_revenu + 1 if not de_l_autre_cote else 0
            if n_revenu >= 2:
                return "regagne", k, premiere_au_dela
    if casse_connue_a is not None:
        return "casse", casse_connue_a, premiere_au_dela
    if i + 1 < len(df):
        v = d.iloc[i + 1]
        if np.isfinite(v) and (v > 0) == (cote > 0):
            return "tenu", i + 1, None
    return "indetermine", min(i + 1, len(df) - 1), None


def _reaction_atr(df, i, cote, k=4):
    """Excursion maximale dans le sens du REJET, en ATR. Le résultat.

    Un test par le dessous qui tient produit une baisse. Effort sans résultat
    = faiblesse — et c'est la seule ligne de la fiche qui ne soit pas une
    colonne : elle se calcule.
    """
    a = _val(df, "atr_barre", i)
    if not a or a <= 0 or i + 1 >= len(df):
        return np.nan
    fin = min(i + k, len(df) - 1)
    ref = df["close"].iloc[i]
    if cote > 0:
        return float((ref - df["low"].iloc[i + 1:fin + 1].min()) / a)
    return float((df["high"].iloc[i + 1:fin + 1].max() - ref) / a)


def _piege(df1, df15, i_debut, i_fin, col, cote, tick):
    """Qui est resté coincé au-delà — compté sur les barres 1 MIN.

    `i_debut` est la PREMIERE barre passée de l'autre côté, pas la seconde :
    c'est souvent là que le volume piégé se fait, quand la cassure paraît
    encore valide. Et la fenêtre va jusqu'à la FIN de `i_fin` : borner au `ts`
    de cette barre exclurait ses quinze minutes.
    """
    vide = {"volume_au_dela": None, "delta_au_dela": None,
            "duree_au_dela": None, "dist_piege": None}
    if df1 is None or df1.empty or i_debut is None or "ts" not in df1.columns:
        return vide
    t0 = int(df15["ts"].iloc[i_debut])
    t1 = int(df15["ts"].iloc[min(i_fin, len(df15) - 1)]) + MS_PAR_BARRE - 1
    ts1 = _num(df1["ts"])
    bloc = df1[(ts1 >= t0) & (ts1 <= t1)]
    if bloc.empty:
        return vide
    dist = _val(df15, col, i_debut)
    if dist is None:
        return vide
    niveau = float(df15["close"].iloc[i_debut]) + dist * tick
    au_dela = (bloc["close"] > niveau) if cote > 0 else (bloc["close"] < niveau)
    b = bloc[au_dela]
    if b.empty:
        return vide
    a = _val(df15, "atr_barre", i_debut)
    extreme = b["high"].max() if cote > 0 else b["low"].min()
    return {
        "volume_au_dela": float(_num(b["total_vol"]).sum()) if "total_vol" in b else None,
        "delta_au_dela": float(_num(b["delta_bar"]).sum()) if "delta_bar" in b else None,
        "duree_au_dela": int(len(b)),
        "dist_piege": (float(abs(extreme - niveau) / a) if a and a > 0 else None),
    }


def fiches(df15, df1=None, col="dist_cur_vah", tick=0.25, z_touche=0.0,
           z_reset=0.5, k_reaction=4):
    """Une fiche par test du niveau `col`, dans l'ordre chronologique.

    `z_touche` et `z_reset` viennent du `seuils.yaml` de L1. Le second a été
    choisi sur la **discrimination** — à 0,5 ATR, « deux, trois, quatre tests »
    existe dans 45 % des cas ; à 1,5 le compteur est un booléen déguisé. C'est
    un choix raisonné sur une distribution, pas une valeur lue dedans.

    `rvol_r` et `cvd_sess_r` sont des RECALCULS, pas des colonnes du dumper.
    S'ils ne sont pas dans `df15`, la fiche les porte à `None` — **jamais un
    repli sur `rvol`**, dont le défaut vaut `1.0f` dans le domaine.
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
        issue, i_connu, i_debut = _issue(df15, col, i, cote)
        # CONTRE-LISIBILITE (08/09) : la fiche porte son niveau EN PRIX et ses
        # bornes en ts. Sans eux, le recit attribuait la cassure a l'heure du
        # TEST — « cassee 03:00 » pour une cassure de 04:15 — et le piege
        # etait invérifiable a la main.
        _d = _val(df15, col, i)
        f = {
            "i": i, "i_connu": i_connu, "ts": int(df15["ts"].iloc[i]),
            "ts_connu": int(df15["ts"].iloc[min(i_connu, len(df15) - 1)]),
            "ts_casse": (int(df15["ts"].iloc[i_debut])
                         if i_debut is not None else None),
            "niveau_prix": (round(float(df15["close"].iloc[i]) + _d * tick, 2)
                            if _d is not None else None),
            "niveau": col, "cote": cote,
            "rvol_r": _val(df15, "rvol_r", i),
            "total_vol": _val(df15, "total_vol", i),
            "delta_pct": _val(df15, "delta_pct", i),
            "ask_pct": _val(df15, "ask_pct", i),
            "cvd_sess_r": _val(df15, "cvd_sess_r", i),
            "meche_haut": _val(df15, "bar_upper_wick_pct", i),
            "meche_bas": _val(df15, "bar_lower_wick_pct", i),
            "finish": _val(df15, "finish_delta_pct", i),
            "big_ask": _val(df15, "max_big_ask_vol_in_bar", i),
            "big_bid": _val(df15, "max_big_bid_vol_in_bar", i),
            "reaction_atr": _reaction_atr(df15, i, cote, k_reaction),
            "issue": issue,
        }
        f.update(_piege(df1, df15, i_debut, i_connu, col, cote, tick))
        out.append(f)
    return out


def scalaires(fiches_du_niveau, i_courant):
    """Ce que `lecture.py` expose. Une porte ne lit pas une liste.

    **Rien de ce qui n'est pas encore connu n'est révélé.** Une fiche dont
    l'issue tombe à `i_connu > i_courant` rend `en_cours`, et sa réaction comme
    son piège restent `None`.

    `effort` et `resultat` restent SÉPARÉS. Leur produit confondrait un gros
    effort sans résultat — une faiblesse — avec un petit effort qui suffit —
    une défense facile. `defense_forte` se définit dans `seuils.yaml` comme une
    conjonction sur quantiles, pas comme une multiplication.
    """
    vus = [f for f in fiches_du_niveau if f["i"] <= i_courant]
    if not vus:
        return {"n_tests": 0, "issue": None, "effort_dernier": None,
                "resultat_dernier": None, "defense_tendance": None,
                "cvd_cote_defense": None, "piege_volume": None}
    d = vus[-1]
    connu = d["i_connu"] <= i_courant
    # la tendance ne compare que des reactions DEJA connues
    connues = [f for f in vus if f["i_connu"] <= i_courant
               and f.get("reaction_atr") is not None
               and np.isfinite(f["reaction_atr"])]
    tendance = None
    if len(connues) >= 2 and connues[0]["reaction_atr"] > 0:
        tendance = float(connues[-1]["reaction_atr"] / connues[0]["reaction_atr"])
    cvd = d.get("cvd_sess_r")
    return {
        "n_tests": len(vus),
        "issue": d["issue"] if connu else "en_cours",
        "effort_dernier": d.get("rvol_r"),
        "resultat_dernier": (d["reaction_atr"] if connu
                             and d.get("reaction_atr") is not None
                             and np.isfinite(d["reaction_atr"]) else None),
        "defense_tendance": tendance,
        "cvd_cote_defense": (bool((cvd > 0) == (d["cote"] < 0))
                             if cvd is not None else None),
        "piege_volume": d.get("volume_au_dela") if connu else None,
    }
