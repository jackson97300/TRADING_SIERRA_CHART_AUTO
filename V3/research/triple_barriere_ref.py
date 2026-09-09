"""triple_barriere_ref — l'implementation de REFERENCE, conventions ECRITES.

Fable, 09/09/2026. Ce fichier ne remplace pas `CORE.research.hypothesis_runner.
triple_barriere` : il sert a LA CONFRONTER. On rejoue les memes signaux avec
les deux, et chaque ecart est une convention differente — nommee, mesuree,
puis tranchee dans DECISIONS.md. Zero ecart = les conventions sont les memes.
Des ecarts = on sait lesquels, et de combien les devenirs du jour 61 bougent.

    from V3.research.triple_barriere_ref import triple_barriere_ref

LES CINQ CONVENTIONS — toutes CONSERVATRICES, toutes explicites
--------------------------------------------------------------
C1  ENTREE = open(t+1). La decision est prise a la cloture de t ; l'ordre part
    apres. close(t) est un prix qu'on ne peut plus avoir.
C2  La barre d'entree (t+1) EST testee : un SL touche dans la barre ou l'on
    entre a l'open est un SL. Un runner qui commence a t+2 rate ce cas.
C3  TP et SL touches dans la MEME barre = SL. Sans les ticks intra-barre on ne
    sait pas lequel est venu en premier ; l'hypothese defavorable est la seule
    qui ne fabrique pas d'edge. (Le biais est mesurable : `meme_barre=True`
    dans la sortie — on saura combien de trades sont dans ce cas.)
C4  EXPIRATION = close de la barre t+1+expiration_barres-1, c'est-a-dire
    `expiration_barres` barres DETENUES a partir de l'entree incluse. 20 barres
    detenues = sortie a la cloture de la 20e. Et jamais au-dela de la SORTIE
    HORAIRE : l'EOD tombe sur la barre qui CONTIENT `sortie_minutes_et` (955 =
    15h55 ET), a sa CLOTURE. `minutes_et` etiquette le DEBUT d'une barre : 945
    couvre 15h45-16h00, donc 15h55 est DEDANS -> EOD a la cloture de 945 (16h00).
    (Corrige le 09/09 : `>= 955` attendait une barre commencant a 15h55, qui
    n'existe pas en 15 min, et ne se declenchait jamais sur donnee cash.)
C5  FRAIS deduits UNE fois, aller-retour compris (`cout_usd` est le cout
    complet d'un trade : commission A/R + slippage 2 cotes), convertis en ATR
    DU JOUR (`atr` = atr_barre de la barre du signal), jamais une constante.

Ce qu'elle REND — un dict, jamais un tuple positionnel (un tuple se lit dans
le mauvais ordre sans crash : c'est le bug (etiquette, pnl, i_sortie) qui
attend son heure) :
    {"issue": "TP"|"SL"|"EXPIRATION"|"EOD"|"INDETERMINE",
     "i_entree": int, "i_sortie": int|None, "prix_entree": float,
     "prix_sortie": float|None, "pnl_pts": float|None, "pnl_atr": float|None,
     "frais_atr": float, "meme_barre": bool, "barres_detenues": int|None,
     "mfe_atr": float|None, "mae_atr": float|None}
INDETERMINE = pas assez de barres apres t pour conclure (fin de fichier) —
ce n'est pas une expiration, c'est un trou, et il se journalise comme tel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ISSUES = ("TP", "SL", "EXPIRATION", "EOD", "INDETERMINE")


def triple_barriere_ref(df, i, side, atr, cout_usd, val_point,
                        sl_atr=1.0, tp_atr=1.5, expiration_barres=20,
                        sortie_minutes_et=955, largeur_barre_min=15,
                        col_minutes_et="minutes_et"):
    """Le devenir d'un signal a la barre `i`, sens `side` (+1/-1), en ATR.

    `df` : barres 15 min d'UNE journee cash, colonnes open/high/low/close et
           `col_minutes_et` (minutes ET depuis minuit ; 570 = 9h30).
    `atr` : ATR-15m en POINTS de la barre du signal (jamais NaN ici :
           l'appelant a deja rendu None / TROU si l'ATR manque).
    `cout_usd`, `val_point` : cout complet A/R d'un trade, valeur du point.
    """
    if side not in (1, -1):
        raise ValueError("side doit valoir +1 ou -1, recu %r" % side)
    if atr is None or not (float(atr) > 0):
        raise ValueError("atr invalide : %r" % atr)
    n = len(df)
    i_entree = i + 1                                           # C1
    if i_entree >= n:
        return _indetermine(i_entree)

    o = pd.to_numeric(df["open"], errors="coerce").to_numpy(float)
    h = pd.to_numeric(df["high"], errors="coerce").to_numpy(float)
    lo = pd.to_numeric(df["low"], errors="coerce").to_numpy(float)
    c = pd.to_numeric(df["close"], errors="coerce").to_numpy(float)
    m_et = pd.to_numeric(df[col_minutes_et], errors="coerce").to_numpy(float)

    entree = o[i_entree]
    if not np.isfinite(entree):
        return _indetermine(i_entree)
    sl = entree - sl_atr * atr * side
    tp = entree + tp_atr * atr * side
    frais_atr = (cout_usd / val_point) / atr                    # C5 : une fois

    i_fin = min(i_entree + expiration_barres - 1, n - 1)        # C4
    mfe = mae = 0.0
    for j in range(i_entree, i_fin + 1):                        # C2 : t+1 inclus
        if not (np.isfinite(h[j]) and np.isfinite(lo[j]) and np.isfinite(c[j])):
            return _indetermine(i_entree)
        # excursions signees dans le sens du trade, en ATR
        mfe = max(mfe, ((h[j] if side > 0 else lo[j]) - entree) * side / atr)
        mae = min(mae, ((lo[j] if side > 0 else h[j]) - entree) * side / atr)
        touche_sl = lo[j] <= sl if side > 0 else h[j] >= sl
        touche_tp = h[j] >= tp if side > 0 else lo[j] <= tp
        if touche_sl:                                           # C3 : SL prime
            return _sortie("SL", i_entree, j, entree, sl, side, atr, frais_atr,
                           touche_tp, mfe, mae)
        if touche_tp:
            return _sortie("TP", i_entree, j, entree, tp, side, atr, frais_atr,
                           False, mfe, mae)
        # C4 : EOD = la barre qui CONTIENT l'heure de sortie ferme dessus.
        # `minutes_et` etiquette une barre par son DEBUT : 945 couvre 15h45-
        # 16h00, donc 15h55 tombe DEDANS. `+ largeur_barre_min` (correction
        # 09/09 : `>= 955` seul ne se declenchait JAMAIS sur donnee cash
        # finissant a 15h45 = 945 -> les trades de fin de journee tombaient a
        # tort en INDETERMINE, la confrontation l'a montre).
        if np.isfinite(m_et[j]) and m_et[j] + largeur_barre_min > sortie_minutes_et:
            return _sortie("EOD", i_entree, j, entree, c[j], side, atr,
                           frais_atr, False, mfe, mae)
    if i_fin < i_entree + expiration_barres - 1:               # fichier trop court
        return _indetermine(i_entree)
    return _sortie("EXPIRATION", i_entree, i_fin, entree, c[i_fin], side, atr,
                   frais_atr, False, mfe, mae)


def _sortie(issue, i_entree, i_sortie, entree, prix_sortie, side, atr,
            frais_atr, meme_barre, mfe, mae):
    pnl_pts = (prix_sortie - entree) * side
    return {"issue": issue, "i_entree": int(i_entree), "i_sortie": int(i_sortie),
            "prix_entree": float(entree), "prix_sortie": float(prix_sortie),
            "pnl_pts": float(pnl_pts),
            "pnl_atr": float(pnl_pts / atr - frais_atr),
            "frais_atr": float(frais_atr), "meme_barre": bool(meme_barre),
            "barres_detenues": int(i_sortie - i_entree + 1),
            "mfe_atr": float(mfe), "mae_atr": float(mae)}


def _indetermine(i_entree):
    return {"issue": "INDETERMINE", "i_entree": int(i_entree), "i_sortie": None,
            "prix_entree": None, "prix_sortie": None, "pnl_pts": None,
            "pnl_atr": None, "frais_atr": None, "meme_barre": False,
            "barres_detenues": None, "mfe_atr": None, "mae_atr": None}


# --------------------------------------------------------------------------
# TESTS — chaque convention a son cas, LONG et SHORT en miroir.
# Barres synthetiques : atr = 10 pts, entree = 100 (open de t+1), SL 90 / TP 115
# pour un LONG ; SL 110 / TP 85 pour un SHORT. cout 2.5 $, val_point 5 $ ->
# frais_atr = 0.05.
# --------------------------------------------------------------------------

def _df(rows, m0=570):
    """rows : liste de (open, high, low, close) ; minutes_et en 15 min depuis m0."""
    return pd.DataFrame({
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
        "minutes_et": [m0 + 15 * k for k in range(len(rows))]})


def _tb(df, side, **kw):
    return triple_barriere_ref(df, 0, side, atr=10.0, cout_usd=2.5,
                               val_point=5.0, **kw)


def test_c1_entree_open_t1():
    df = _df([(95, 96, 94, 95), (100, 101, 99, 100)] + [(100, 101, 99, 100)] * 20)
    r = _tb(df, +1)
    assert r["prix_entree"] == 100.0 and r["i_entree"] == 1


def test_c2_sl_dans_la_barre_d_entree():
    df = _df([(95, 96, 94, 95), (100, 101, 89, 90)] + [(90, 91, 89, 90)] * 20)
    r = _tb(df, +1)
    assert r["issue"] == "SL" and r["i_sortie"] == 1 and r["barres_detenues"] == 1


def test_c3_meme_barre_sl_prime():
    df = _df([(95, 96, 94, 95), (100, 116, 89, 100)] + [(100, 101, 99, 100)] * 20)
    r = _tb(df, +1)
    assert r["issue"] == "SL" and r["meme_barre"] is True
    r = _tb(_df([(105, 106, 104, 105), (100, 111, 84, 100)] + [(100, 101, 99, 100)] * 20), -1)
    assert r["issue"] == "SL" and r["meme_barre"] is True


def test_c4_expiration_20_barres_detenues():
    df = _df([(95, 96, 94, 95)] + [(100, 101, 99, 100.5)] * 25)
    r = _tb(df, +1)
    assert r["issue"] == "EXPIRATION" and r["barres_detenues"] == 20
    assert r["i_sortie"] == 20 and r["prix_sortie"] == 100.5


def test_c4_eod_barre_qui_contient_l_heure():
    # minutes_et etiquette le DEBUT : la barre 945 couvre 15h45-16h00, donc
    # 15h55 (955, defaut) est DEDANS. m0=915 -> barres 915/930/945. Signal i=0,
    # entree i=1 (930). L'EOD tombe sur 945 (945+15=960 > 955) a sa cloture.
    # Avec l'ancien `>= 955`, aucune barre ne se declenchait -> INDETERMINE :
    # ce test distingue l'ancien du nouveau.
    df = _df([(95, 96, 94, 95), (100, 101, 99, 101), (101, 102, 100, 102)], m0=915)
    r = _tb(df, +1)                          # sortie_minutes_et=955 par defaut
    assert r["issue"] == "EOD" and r["i_sortie"] == 2 and r["prix_sortie"] == 102
    assert r["barres_detenues"] == 2         # la barre 930 (945 <= 955) ne tire pas


def test_c5_frais_une_fois_en_atr_du_jour():
    df = _df([(95, 96, 94, 95), (100, 116, 99, 115)] + [(115, 116, 114, 115)] * 20)
    r = _tb(df, +1)
    assert r["issue"] == "TP"
    assert abs(r["pnl_atr"] - (1.5 - 0.05)) < 1e-9


def test_indetermine_fichier_court():
    df = _df([(95, 96, 94, 95), (100, 101, 99, 100), (100, 101, 99, 100)])
    r = _tb(df, +1)
    assert r["issue"] == "INDETERMINE" and r["pnl_atr"] is None


def test_miroir_short_tp():
    df = _df([(105, 106, 104, 105), (100, 101, 84, 85)] + [(85, 86, 84, 85)] * 20)
    r = _tb(df, -1)
    assert r["issue"] == "TP" and abs(r["pnl_pts"] - 15.0) < 1e-9


def test_mfe_mae():
    df = _df([(95, 96, 94, 95), (100, 108, 96, 100)] + [(100, 101, 99, 100.0)] * 20)
    r = _tb(df, +1)
    assert abs(r["mfe_atr"] - 0.8) < 1e-9 and abs(r["mae_atr"] + 0.4) < 1e-9


def test_fail_loud():
    df = _df([(95, 96, 94, 95)] * 3)
    for bad in (0, 2, None):
        try:
            triple_barriere_ref(df, 0, bad, 10.0, 2.5, 5.0)
            assert False, "side invalide accepte"
        except ValueError:
            pass
    try:
        triple_barriere_ref(df, 0, 1, None, 2.5, 5.0)
        assert False, "atr None accepte"
    except ValueError:
        pass


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print("%d/%d — triple_barriere_ref : cinq conventions, toutes ecrites"
          % (len(tests), len(tests)))
    sys.exit(0)
