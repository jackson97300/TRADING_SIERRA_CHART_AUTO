"""Les six hypotheses de MISSION_PHASE2, figees par le tag `mission-phase2-v1`.

Une fonction par hypothese. **La docstring de chacune recopie mot pour mot la
ligne du tableau tague** — lieu, reaction, side, colonnes. Le hash de
`MISSION_PHASE2.md`, verifie au demarrage du runner, protege le texte ; la
docstring protege la correspondance texte -> code, qui est ce que le hash ne
voit pas.

Rien ici ne doit etre modifie apres le tag. Une idee nee en lisant les resultats
va dans `NEXT_CYCLE.md`.


UNITES — la source d'erreur numero un de ce depot
--------------------------------------------------
Quatre bugs d'unite en six mois : `sess_range_atr` en avril, les `dist_*_atr`
livres (facteur 4) cette semaine, `atr` lu au lieu de `atr_14m`, et le seuil de
0,10 ATR qui valait 1,13 tick sur ES. Donc, explicitement :

    `atr_barre`            POINTS. Calcule sur high/low, qui sont des prix.
    `dist_*`          TICKS.  Mesure du 06/09 : le niveau reconstruit par
                              `close + dist x 0,25` est constant sur la journee
                              et tombe sur des strikes ronds.
    conversion        `atr5_ticks = atr_barre / tick`, tick = 0,25 sur ES et NQ.

**Toute comparaison entre une `dist_*` et un multiple d'ATR passe par
`seuil_ticks()`.** Comparer une distance en ticks a `0,10 * atr_barre` en points
donnerait un seuil quatre fois trop grand, silencieusement.


PLANCHERS EN TICKS — correction du 06/09, avant le tag
-------------------------------------------------------
ATR-5m ~ 11,3 ticks sur ES, donc 0,10 ATR = 1,13 tick : H3 exigerait d'etre a un
tick du VAH, et la borne de H6 valait 0,6 tick, plus fin que la grille. Sur NQ le
meme seuil vaut 8 ticks. Une definition atteignable sur un seul instrument est un
artefact d'unite, pas une hypothese.

    proximite        P10 = max(0,10 x ATR-5m, 2 ticks)
    retest           P15 = max(0,15 x ATR-5m, 3 ticks)
    borne fine       P05 = max(0,05 x ATR-5m, 1 tick)
    absorption       P20 = max(0,20 x ATR-5m, 4 ticks)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TICK = 0.25                      # ES et NQ. MGC = 0,10 — hors perimetre du cycle.
PLANCHERS = {"P05": (0.05, 1.0), "P10": (0.10, 2.0),
             "P15": (0.15, 3.0), "P20": (0.20, 4.0)}


def seuil_ticks(atr5_points, nom="P10", tick=TICK):
    """Seuil de proximite en TICKS : `max(fraction x ATR-5m, plancher)`.

    `atr5_points` est en points ; le resultat est en ticks, pour se comparer
    directement a une colonne `dist_*`. C'est la seule conversion admise entre
    les deux unites.
    """
    frac, plancher = PLANCHERS[nom]
    atr_ticks = pd.to_numeric(atr5_points, errors="coerce") / tick
    return np.maximum(frac * atr_ticks, plancher)


def _f(df, col):
    """Colonne en flottant, NaN si absente — une hypothese ne declenche pas sur
    une colonne manquante, et ne leve pas non plus : le rapport dira `N=0`."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


# ---------------------------------------------------------------------------
# H2 — Fade des bandes VWAP-SD2 avec rejet
# ---------------------------------------------------------------------------

def h2(df, tick=TICK):
    """H2 | Fade des bandes VWAP-SD2 avec rejet.

    REGIME L2  : ROTATION, `ib_range_atr` < 0,8 (clause gamma retiree : proxy)
    LIEU       : `dist_vwap_rth_sd2u_r` dans [-P15 ; +P10] (short) /
                 `dist_vwap_rth_sd2d_r` dans [-P10 ; +P15] (long), avec
                 P10 = max(0,10 ATR, 2 t) et P15 = max(0,15 ATR, 3 t)
    REACTION   : `delta_bar` < 0 ET `finish_delta_pct` < 0,4 (short) ;
                 miroir (long)
    SIDE       : SHORT / LONG
    COLONNES   : bandes recalculees par `recalc.vwap_bandes(..., n_sd=2.0)` (A),
                 `delta_bar` (A), `finish_delta_pct` (A), `ib_range_atr` (B)
    """
    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
    regime = _f(df, "ib_range_atr") < 0.8
    du, dd = _f(df, "dist_vwap_rth_sd2u_r"), _f(df, "dist_vwap_rth_sd2d_r")
    delta, fin = _f(df, "delta_bar"), _f(df, "finish_delta_pct")
    return {
        "short": ((du >= -p15) & (du <= p10) & regime & (delta < 0) & (fin < 0.4), -1),
        "long":  ((dd >= -p10) & (dd <= p15) & regime & (delta > 0) & (fin > 0.6), +1),
    }


# ---------------------------------------------------------------------------
# H3 — Rejet a l'extreme de la VA courante
# ---------------------------------------------------------------------------

def h3(df, tick=TICK):
    """H3 | Rejet a l'extreme de la VA courante.

    REGIME L2  : ROTATION
    LIEU       : `dist_cur_vah` dans +/- max(0,10 ATR, 2 t) (short) /
                 `dist_cur_val` (long)
    REACTION   : barre t sort de la VA (high > VAH) ET cloture < VAH ET
                 `finish_delta_pct` < 0,4 ; miroir
    SIDE       : SHORT / LONG
    COLONNES   : `dist_cur_vah/val` (A), `inside_cur_va` (A),
                 `finish_delta_pct` (A)

    `dist_cur_vah` = VAH - close, en ticks : positive sous le VAH. « Sortir puis
    revenir » se lit donc `high > VAH` (la meche depasse) et `dist_cur_vah > 0`
    (la cloture est revenue dessous).
    """
    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
    dh, dl = _f(df, "dist_cur_vah"), _f(df, "dist_cur_val")
    fin = _f(df, "finish_delta_pct")
    vah = _f(df, "close") + dh * tick
    val = _f(df, "close") - dl * tick
    return {
        "short": ((dh.abs() <= p10) & (_f(df, "high") > vah) & (dh > 0) & (fin < 0.4), -1),
        "long":  ((dl.abs() <= p10) & (_f(df, "low") < val) & (dl > 0) & (fin > 0.6), +1),
    }


# ---------------------------------------------------------------------------
# H4 — Regle des 80 % (Dalton)
# ---------------------------------------------------------------------------

def h4(df, tick=TICK):
    """H4 | Regle des 80 % (Dalton).

    REGIME L2  : definit le regime — mesuree sans L2
    LIEU       : ouverture cash hors VA veille puis retour : cloture 5 min dans
                 [`prev_val_lvl` ; `prev_vah_lvl`]
    REACTION   : maintien dans la VA pendant 6 barres 5 min consecutives
                 (= 2 x 30 min)
    SIDE       : sens de la traversee (vers la VA opposee)
    COLONNES   : `open_within_prev_va` (B), `open_outside_prev_range` (B),
                 `prev_vah/val_lvl` (N), `rule_80pct` (B, en information)

    Le side est celui de la traversee : entre par le bas de la VA, on vise le
    haut. Il est donne par le cote d'ou vient l'ouverture, fige par journee.
    """
    c = _f(df, "close")
    vah, val = _f(df, "prev_vah_lvl"), _f(df, "prev_val_lvl")
    dedans = (c >= val) & (c <= vah)
    hors = _f(df, "open_within_prev_va").fillna(1) == 0
    jour = df["jour"].astype(str)

    # six barres consecutives dans la VA, sans traverser la nuit
    tenu = dedans.groupby(jour).apply(
        lambda s: s.rolling(6, min_periods=6).sum().eq(6)).reset_index(level=0, drop=True)
    tenu = tenu.reindex(df.index).fillna(False)

    # cote d'ouverture, fige par journee : au-dessus de la VA -> on traverse vers le bas
    ouv = c.groupby(jour).transform("first")
    vah_j, val_j = vah.groupby(jour).transform("first"), val.groupby(jour).transform("first")
    par_haut, par_bas = ouv > vah_j, ouv < val_j
    return {
        "short": (tenu & hors & par_haut, -1),
        "long":  (tenu & hors & par_bas, +1),
    }


# ---------------------------------------------------------------------------
# H6 — Retest de l'IB apres cassure acceptee
# ---------------------------------------------------------------------------

def h6(df, tick=TICK):
    """H6 | Retest de l'IB apres cassure acceptee.

    REGIME L2  : BREAKOUT, `ib_range_atr` < 0,4
    LIEU       : `ib_broken_up` = 1 ET `dist_ib_high` dans
                 [-max(0,15 ATR, 3 t) ; +max(0,05 ATR, 1 t)] ; miroir bas
    REACTION   : cloture 5 min au-dessus de l'IB high ET `finish_delta_pct` > 0,6 ;
                 miroir
    SIDE       : LONG / SHORT
    COLONNES   : `ib_broken_up/dn` (B), `dist_ib_high/low` (A),
                 `finish_delta_pct` (A), `ib_range_atr` (B)

    `dist_ib_high` = IB_high - close, en ticks : negative quand la cloture est
    AU-DESSUS de l'IB. C'est ce signe qui distingue le retest par le haut (on
    est repasse au-dessus) du retest par le bas.
    """
    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
    p05 = seuil_ticks(df["atr_barre"], "P05", tick)
    regime = _f(df, "ib_range_atr") < 0.4
    dh, dl = _f(df, "dist_ib_high"), _f(df, "dist_ib_low")
    fin = _f(df, "finish_delta_pct")
    return {
        "long":  ((_f(df, "ib_broken_up") == 1) & (dh >= -p15) & (dh <= p05)
                  & regime & (dh < 0) & (fin > 0.6), +1),
        "short": ((_f(df, "ib_broken_dn") == 1) & (dl >= -p15) & (dl <= p05)
                  & regime & (dl < 0) & (fin < 0.4), -1),
    }


# ---------------------------------------------------------------------------
# H7 — Sweep de liquidite + reclaim N+1
# ---------------------------------------------------------------------------

def h7(df, tick=TICK):
    """H7 | Sweep de liquidite + reclaim N+1.

    REGIME L2  : tous, sauf INDETERMINE
    LIEU       : `sweep_low_this_bar` = 1 ET le low de t depasse un niveau de
                 reference (`dist_ovn_low`, `dist_pdl`, `dist_ib_low`) de
                 >= max(0,10 ATR, 2 t) ; miroir haut
    REACTION   : cloture de t+1 au-dessus du low de t (decision evaluee a la
                 cloture de t+1, entree a l'ouverture de t+2)
    SIDE       : LONG / SHORT
    COLONNES   : `sweep_high/low_this_bar` (B), `dist_ovn_high/low` (A),
                 `dist_pdh/pdl` (A), `dist_ib_high/low` (A)

    **La condition rendue est deja decalee d'une barre** : elle est vraie a
    l'indice t+1, de sorte que le runner — qui entre a l'ouverture de i+1 —
    entre bien a l'ouverture de t+2, comme le tableau l'exige.

    Le detecteur seul declenche 87 fois par jour sur ES et 130 sur NQ : c'est la
    condition de reserve de liquidite qui fait tout le travail. Elle est donc
    ecrite serree, et exige qu'un niveau de reference ait ete REELLEMENT depasse.
    """
    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
    low, high, close = _f(df, "low"), _f(df, "high"), _f(df, "close")

    def depasse(cols, sens):
        """Un niveau de reference depasse d'au moins P10, en ticks."""
        out = pd.Series(False, index=df.index)
        for c in cols:
            d = _f(df, c)                       # niveau - close, en ticks
            niveau = close + d * tick
            marge = ((niveau - low) if sens > 0 else (high - niveau)) / tick
            out = out | (marge >= p10)
        return out

    bas = (_f(df, "sweep_low_this_bar") == 1) & depasse(
        ["dist_ovn_low", "dist_pdl", "dist_ib_low"], +1)
    haut = (_f(df, "sweep_high_this_bar") == 1) & depasse(
        ["dist_ovn_high", "dist_pdh", "dist_ib_high"], -1)

    jour = df["jour"].astype(str)
    meme_jour = jour.eq(jour.shift(1))
    reclaim_bas = meme_jour & bas.shift(1).fillna(False) & (close > low.shift(1))
    reclaim_haut = meme_jour & haut.shift(1).fillna(False) & (close < high.shift(1))
    return {"long": (reclaim_bas, +1), "short": (reclaim_haut, -1)}


# ---------------------------------------------------------------------------
# H8 — Absorption a un niveau
# ---------------------------------------------------------------------------

NIVEAUX_H8 = ["dist_cur_vah", "dist_cur_val", "dist_prev_vah", "dist_prev_val",
              "dist_mq_call", "dist_mq_put", "dist_pdh", "dist_pdl",
              "dist_ovn_high", "dist_ovn_low"]


def h8(df, tick=TICK):
    """H8 | Absorption a un niveau.

    REGIME L2  : ROTATION / REVERSAL
    LIEU       : <= max(0,20 ATR, 4 t) d'un niveau de F3/F10/F11/F12
                 (VA veille ou courante, mur, PDH/PDL, ONH/ONL)
    REACTION   : `rvol_r` >= 2,0 ET `delta_pct` <= -0,30 (long) / >= +0,30 (short)
                 ET `finish_delta_pct` contraire au delta (> 0,6 long / < 0,4 short)
    SIDE       : LONG / SHORT
    COLONNES   : `rvol_r` (A, recalcule), `delta_pct` (A), `finish_delta_pct` (A),
                 distances (A/B)

    `rvol_r` et non `rvol` : le C++ initialise `f.rvol = 1.0f` (« Normal par
    defaut ») quand son ring buffer n'est pas pret, et 1,0 est une valeur valide
    — « normal mesure » et « jamais calcule » y sont indistinguables
    (CONVENTIONS §3.1, incident du 06/09).
    """
    p20 = seuil_ticks(df["atr_barre"], "P20", tick)
    pres = pd.Series(False, index=df.index)
    for c in NIVEAUX_H8:
        pres = pres | (_f(df, c).abs() <= p20)
    rvol, dp, fin = _f(df, "rvol_r"), _f(df, "delta_pct"), _f(df, "finish_delta_pct")
    return {
        "long":  (pres & (rvol >= 2.0) & (dp <= -0.30) & (fin > 0.6), +1),
        "short": (pres & (rvol >= 2.0) & (dp >= 0.30) & (fin < 0.4), -1),
    }



# ---------------------------------------------------------------------------
# Les lieux seuls — pour l'entonnoir, jamais pour decider
# ---------------------------------------------------------------------------

def lieux(df, tick=TICK):
    """Le LIEU de chaque hypothese, sans sa reaction et sans son regime.

    Sert uniquement a l'entonnoir du rapport : `lieu seul -> + regime ->
    + reaction`. Sans ces etages, « non testable » ne dit pas si c'est le lieu
    qui est rare, le regime qui ne mord jamais, ou la reaction qui est stricte —
    et c'est precisement ce qui a manque a la lecture du 06/09, ou H6 rendait
    N = 0 sans qu'on voie que son regime couvrait 0,13 % des barres.
    """
    p05 = seuil_ticks(df["atr_barre"], "P05", tick)
    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
    p20 = seuil_ticks(df["atr_barre"], "P20", tick)
    du, dd = _f(df, "dist_vwap_rth_sd2u_r"), _f(df, "dist_vwap_rth_sd2d_r")
    dh, dl = _f(df, "dist_cur_vah"), _f(df, "dist_cur_val")
    ih, il = _f(df, "dist_ib_high"), _f(df, "dist_ib_low")
    pres = pd.Series(False, index=df.index)
    for c in NIVEAUX_H8:
        pres = pres | (_f(df, c).abs() <= p20)
    c = _f(df, "close")
    return {
        "H2": ((du >= -p15) & (du <= p10)) | ((dd >= -p10) & (dd <= p15)),
        "H3": (dh.abs() <= p10) | (dl.abs() <= p10),
        "H4": (c >= _f(df, "prev_val_lvl")) & (c <= _f(df, "prev_vah_lvl")),
        "H6": (((_f(df, "ib_broken_up") == 1) & (ih >= -p15) & (ih <= p05))
               | ((_f(df, "ib_broken_dn") == 1) & (il >= -p15) & (il <= p05))),
        "H7": (_f(df, "sweep_low_this_bar") == 1) | (_f(df, "sweep_high_this_bar") == 1),
        "H8": pres,
    }


def regimes(df):
    """La condition de REGIME de chaque hypothese, isolee.

    H6 et H2 lisent `ib_range_atr`, dont la colonne livree divise des ticks par
    des points (`recalc.ib_range_atr_r`). Le tag les fige ainsi : elles sont
    donc evaluees sur la colonne LIVREE, comme ecrit, et l'entonnoir montre ce
    que cela coute. La version corrigee appartient au cycle suivant.
    """
    ib = _f(df, "ib_range_atr")
    vrai = pd.Series(True, index=df.index)
    return {"H2": ib < 0.8, "H3": vrai, "H4": vrai,
            "H6": ib < 0.4, "H7": vrai, "H8": vrai}

LES_SIX = {"H2": h2, "H3": h3, "H4": h4, "H6": h6, "H7": h7, "H8": h8}

# H4 est annoncee sous-dimensionnee AVANT de tourner : 16 franchissements sur 57
# jours. « NON TESTABLE » y signifiera « trop rare pour ce lot », jamais « le
# setup est mauvais ». Le mode ombre est sa seule voie.
SOUS_DIMENSIONNEES = {"H4"}


# ---------------------------------------------------------------------------
# CYCLE 2 — pre-enregistre le 06/09 dans DOCS/MISSION_CYCLE2.md
# ---------------------------------------------------------------------------

def _ib_range_atr_r(df, tick=TICK):
    """`ib_range_ticks x tick / atr` — points sur points.

    La colonne livree `ib_range_atr` divise des TICKS par des POINTS (identique
    au livre a 100 % sur 12 580 barres). Facteur 4. Voir `recalc.ib_range_atr_r`.
    """
    ir, at = _f(df, "ib_range_ticks"), _f(df, "atr")
    return ir * tick / at.where(at > 0)


def h2_prime(df, tick=TICK):
    """H2' | Fade des bandes VWAP-SD2, regime RECALCULE.

    Identique a H2 du cycle 1, sauf le regime : `ib_range_atr_r < 0,8` au lieu
    de la colonne livree. Annoncee NON TESTABLE avant de tourner — au cycle 1 la
    reaction ramenait 27 signaux a 3, et le regime corrige ne coupe presque plus
    (141 sur 143).
    """
    p10 = seuil_ticks(df["atr_barre"], "P10", tick)
    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
    regime = _ib_range_atr_r(df, tick) < 0.8
    du, dd = _f(df, "dist_vwap_rth_sd2u_r"), _f(df, "dist_vwap_rth_sd2d_r")
    delta, fin = _f(df, "delta_bar"), _f(df, "finish_delta_pct")
    return {
        "short": ((du >= -p15) & (du <= p10) & regime & (delta < 0) & (fin < 0.4), -1),
        "long":  ((dd >= -p10) & (dd <= p15) & regime & (delta > 0) & (fin > 0.6), +1),
    }


def h6_prime(df, tick=TICK):
    """H6' | Retest de l'IB, regime RECALCULE.

    Identique a H6, regime `ib_range_atr_r < 0,4`. Le regime corrige couvre 56 %
    des barres au lieu de 0,13 %, mais le LIEU ne rend que 58 signaux ES / 65 NQ,
    ramenes a 37 / 35 par le regime — sous le seuil de 40 avant meme la reaction.
    Annoncee NON TESTABLE.
    """
    p15 = seuil_ticks(df["atr_barre"], "P15", tick)
    p05 = seuil_ticks(df["atr_barre"], "P05", tick)
    regime = _ib_range_atr_r(df, tick) < 0.4
    dh, dl = _f(df, "dist_ib_high"), _f(df, "dist_ib_low")
    fin = _f(df, "finish_delta_pct")
    return {
        "long":  ((_f(df, "ib_broken_up") == 1) & (dh >= -p15) & (dh <= p05)
                  & regime & (dh < 0) & (fin > 0.6), +1),
        "short": ((_f(df, "ib_broken_dn") == 1) & (dl >= -p15) & (dl <= p05)
                  & regime & (dl < 0) & (fin < 0.4), -1),
    }


def h8_prime(df, tick=TICK):
    """H8' | Absorption, seuils recalibres sur LEUR DISTRIBUTION.

    `rvol_r >= 1,8` et `|delta_pct| >= 0,18` — le p90 mesure de chaque colonne,
    au lieu de 2,0 et 0,30 qui etaient hors distribution (`|delta_pct|` :
    mediane 0,069, p90 0,175).

    Annoncee NON TESTABLE, et pas seulement sous-dimensionnee : meme desserree a
    1,5 / 0,15 elle ne rend que 8 signaux ES et 7 NQ. **Ce n'est pas un seuil a
    corriger, c'est une conjonction impossible** — un rvol eleve, un delta fort
    et un finish contraire ne coexistent presque jamais. Elle est lancee pour que
    ce soit ecrit, pas parce qu'on l'espere.
    """
    p20 = seuil_ticks(df["atr_barre"], "P20", tick)
    pres = pd.Series(False, index=df.index)
    for c in NIVEAUX_H8:
        pres = pres | (_f(df, c).abs() <= p20)
    rvol, dp, fin = _f(df, "rvol_r"), _f(df, "delta_pct"), _f(df, "finish_delta_pct")
    return {
        "long":  (pres & (rvol >= 1.8) & (dp <= -0.18) & (fin > 0.6), +1),
        "short": (pres & (rvol >= 1.8) & (dp >= 0.18) & (fin < 0.4), -1),
    }


# H3-VPOC utilise EXACTEMENT h3() : lieu et reaction inchanges, seule la cible
# change, et c'est le runner qui la porte (barriere = VPOC atteint).
LES_QUATRE = {"H3-VPOC": h3, "H2p": h2_prime, "H6p": h6_prime, "H8p": h8_prime}
CIBLE_VPOC = {"H3-VPOC"}          # les seules a utiliser la barriere par famille
NON_TESTABLES_ANNONCEES = {"H2p", "H6p", "H8p"}
