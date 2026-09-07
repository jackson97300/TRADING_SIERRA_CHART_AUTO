"""Les FONCTIONS de setup du brief OMBRE C2 — séparées du coureur.

`ombre_c2.py` porte le registre (LES_C2, ACTIFS), les seuils et le journal ;
ce module porte les fonctions pures. Scindé le 08/09 à l'activation du 3e
setup (garde des 300 lignes du miroir) — un concept par fichier : le
COMMENT des setups ici, le QUOI courir là-bas.

Contrat d'une fonction de setup : `f(df, sym, seuils)` rend
    {"short": (cond, -1), "long": (cond, +1), "_lieu": cond_lieu,
     "_cibles": {side: prix_ou_Serie},
     "_extra": {nom: Serie}?, "_sortie": str?, "_muet_jour": motif?}
Conditions par FRANCHISSEMENT, `None`/NaN ne signale jamais, anti-fuite :
rien après la barre t n'entre dans la condition de t.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import recalc                                   # noqa: E402
from CORE.research import hypotheses as HYP                        # noqa: E402

TICK = 0.25   # default ES/NQ. MGC=0,10 — hors perimetre du cycle.
MINUTE_EOD = 15 * 60 + 15   # ouverture 15h15 ET -> cloture 15h30 (DST : recalc)


def _col(df, nom):
    """Colonne numérique, None si absente — le setup rend alors le jour muet
    au lieu de crasher, et `journaliser` REND l'absence (jamais avalée)."""
    return pd.to_numeric(df[nom], errors="coerce") if nom in df.columns else None


def _figes(df, cols):
    """Prix FIGÉS reconstruits `close + dist × TICK`, première valeur finie
    de la journée (méthode F23) — un dist entièrement NaN = niveau inconnu
    ce jour, absent de la liste, jamais 0."""
    clo = _col(df, "close")
    out = []
    for c in cols:
        d = _col(df, c)
        if d is None or clo is None:
            continue
        px = (clo + d * TICK).dropna()
        if len(px):
            out.append(float(px.iloc[0]))
    return out


def c2_80pct(df, sym, s):
    """Règle des 80 % (Dalton) — brief §1, définitions F23.

    Régime B5 : l'ouverture cash HORS de la VA veille (recalculé depuis
    l'open de la première barre cash vs les niveaux reconstruits — jamais le
    flag C++ `rule_80pct`). Lieu ET acceptation sur le MÊME prédicat : la VA
    reconstruite figée (S1 de la review — le flag C++ `inside_prev_va` et la
    reconstruction divergeaient d'un tick, fragmentaient l'épisode et
    gonflaient N ; unifié provenance A). Réaction : DEUX clôtures 15 min
    consécutives dans la VA. Side : vers le bord opposé (ouverture
    au-dessus → SHORT vers VAL ; miroir)."""
    close = pd.to_numeric(df["close"], errors="coerce")
    vah = close + pd.to_numeric(df.get("dist_prev_vah"), errors="coerce") * TICK
    val = close + pd.to_numeric(df.get("dist_prev_val"), errors="coerce") * TICK
    # niveaux FIGÉS : la reconstruction est constante sur la journée, on
    # prend la première valeur finie — règle F23.
    vah_j = vah.dropna().iloc[0] if vah.notna().any() else None
    val_j = val.dropna().iloc[0] if val.notna().any() else None
    ouverture = pd.to_numeric(df["open"], errors="coerce").iloc[0]
    if vah_j is None or val_j is None or not pd.notna(ouverture):
        vide = pd.Series(False, index=df.index)
        return {"short": (vide, -1), "long": (vide, +1),
                "_lieu": vide, "_cibles": {}}
    dedans = (close >= val_j) & (close <= vah_j)
    acceptation = dedans & dedans.shift(1, fill_value=False)
    return {
        "short": (acceptation & (ouverture > vah_j), -1),
        "long": (acceptation & (ouverture < val_j), +1),
        "_lieu": dedans & ((ouverture > vah_j) | (ouverture < val_j)),
        "_cibles": {-1: val_j, +1: vah_j},   # le bord opposé (B-NAT de L5)
    }


def c2_eod(df, sym, s):
    """Momentum de fin de journée — brief §2 (Baltussen et al., JFE 2021).

    Lieu : la barre 15h15-15h30 ET clôturée. `recalc.minutes_et` gère
    EDT/EST ICI, mais la garantie ne tient PAS de bout en bout (review
    08/09, R1) : `est_cash` amont est figé EDT (dette CONVENTIONS §2) et
    couperait la barre 20:15 UTC dès le 2/11 — motif `barre_eod_absente`
    FAUX chaque jour, open cash glissé à 8h30 ET, N plafonné sous 40.
    DEADLINE DURE 31/10 : réécrire `est_cash` sur `minutes_et` (tâche
    séparée, review + parité — DECISIONS + A_FAIRE pt 19). Réaction :
    |rendement_r| ≥ r_min, où rendement_r = (close(15h30) − open(9h30)) /
    range cash du même instant — provenance A pure ; l'écart au « ATR-jour »
    du brief est documenté dans `mesure_c2.py` et `seuils_c2.yaml`, points
    bruts journalisés pour re-normalisation au jour 61. Side : le signe.
    Pas de cible prix : sortie HORAIRE 16h00 ET. Demi-séance : pas de barre
    15h15 → ligne `jour_muet`, jamais un signal. Anti-fuite :
    `cummax`/`cummin` n'utilisent que les barres ≤ t."""
    r_min = ((s.get("C2_EOD") or {}).get("r_min") or {}).get(sym)
    if r_min is None:
        raise ValueError("C2_EOD actif sans r_min %s — poser la distribution"
                         " dans seuils_c2.yaml (fail-loud)" % sym)
    vide = pd.Series(False, index=df.index)
    ouv, clo = _col(df, "open"), _col(df, "close")
    haut, bas = _col(df, "high"), _col(df, "low")
    if any(x is None for x in (ouv, clo, haut, bas)):
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "colonne_absente"}
    mn = recalc.minutes_et(pd.to_datetime(df["ts"], unit="ms", utc=True))
    est_eod = pd.Series((mn == MINUTE_EOD).to_numpy(), index=df.index)
    rng = (haut.cummax() - bas.cummin())
    rend = (clo - float(ouv.iloc[0])) / rng.where(rng > 0)
    if not est_eod.any():
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "barre_eod_absente"}
    lieu = est_eod & rend.notna()
    if not lieu.any():
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "rendement_incalculable"}
    return {"short": (lieu & (rend <= -r_min), -1),
            "long": (lieu & (rend >= r_min), +1),
            "_lieu": lieu, "_cibles": {},
            "_extra": {"rendement_r": rend, "range_pts": rng},
            "_sortie": str((s.get("C2_EOD") or {}).get("sortie", "1600_ET"))}


def c2_div_delta(df, sym, s):
    """Divergence delta au niveau — brief §6, famille flux, sans régime.

    Lieu : NOUVEAU plus haut de session à ≤ P10 (planchers SPEC L3) d'un
    niveau figé (prev_vah, pdh, mq_call — miroir bas : prev_val, pdl,
    mq_put). Réaction : `cvd_sess_r` au nouvel extrême < (resp. >) sa valeur
    au PRÉCÉDENT extrême de session, ET clôture du bon côté du niveau.
    GRAIN 15 MIN ÉCRIT : le CVD est lu à la CLÔTURE de la barre de
    l'extrême, pas au tick de l'extrême — la même limitation que les seize,
    notée pour le jour 61. Cible : `vwap_rth_r` de la barre (Série,
    échantillonnée au signal). NaN (cvd, atr, dist) = jamais un signal.
    Anti-fuite : extrêmes courants et cumuls, rien après t.

    TROU DE CHAUFFE ÉCRIT (review 08/09) : `atr_barre` est NaN les 6
    premières barres (min_periods=7) → AUCUN lieu possible 9h30-11h00 ET,
    là où la session teste PDH/VAH — 58 % des nouveaux extrêmes du lot y
    tombent, la cause PREMIÈRE du N mesuré (~6/60 j, rapport
    lieu_div_delta). Arbitrage Fable ouvert : ATR de la VEILLE (la solution
    L1 du 07/09) — une v2 aurait sa propre date d'ombre, jamais rétroactive.
    Niveaux MQ figés au snapshot du MATIN toute la journée (le §9 prévoit la
    mise à jour de midi — limitation v1 écrite)."""
    vide = pd.Series(False, index=df.index)
    muet = {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
            "_cibles": {}}
    cols = {n: _col(df, n) for n in ("high", "low", "close",
                                     "cvd_sess_r", "atr_barre")}
    if any(v is None for v in cols.values()):
        return dict(muet, _muet_jour="colonne_absente")
    h, l_ = cols["high"].to_numpy(float), cols["low"].to_numpy(float)
    c, cvd = cols["close"].to_numpy(float), cols["cvd_sess_r"].to_numpy(float)
    p10 = np.asarray(HYP.seuil_ticks(cols["atr_barre"], "P10"), float)
    nv_h = _figes(df, ("dist_prev_vah", "dist_pdh", "dist_mq_call"))
    nv_b = _figes(df, ("dist_prev_val", "dist_pdl", "dist_mq_put"))
    if not nv_h and not nv_b:        # un jour sans niveaux doit se VOIR (R2)
        return dict(muet, _muet_jour="niveaux_absents")
    lieu = np.zeros(len(df), bool)
    cshort, clong = np.zeros(len(df), bool), np.zeros(len(df), bool)
    # journalises pour la re-coupe du jour 61 et l'arbitrage du lieu (R4)
    nv_px, d_tk, cvd_prec = (np.full(len(df), np.nan) for _ in range(3))
    hmax, lmin, j_h, j_b = -np.inf, np.inf, -1, -1
    for i in range(len(df)):
        if np.isfinite(h[i]) and h[i] > hmax:      # nouveau plus haut
            hmax = h[i]
            nv = min(nv_h, key=lambda x: abs(x - h[i])) if nv_h else None
            if nv is not None and abs(nv - h[i]) / TICK <= p10[i]:
                lieu[i], nv_px[i], d_tk[i] = True, nv, abs(nv - h[i]) / TICK
                cvd_prec[i] = cvd[j_h] if j_h >= 0 else np.nan
                if (j_h >= 0 and np.isfinite(cvd[i]) and np.isfinite(cvd[j_h])
                        and cvd[i] < cvd[j_h] and c[i] < nv):
                    cshort[i] = True
            j_h = i
        if np.isfinite(l_[i]) and l_[i] < lmin:    # miroir bas
            lmin = l_[i]
            nv = min(nv_b, key=lambda x: abs(x - l_[i])) if nv_b else None
            if nv is not None and abs(nv - l_[i]) / TICK <= p10[i]:
                lieu[i], nv_px[i], d_tk[i] = True, nv, abs(nv - l_[i]) / TICK
                cvd_prec[i] = cvd[j_b] if j_b >= 0 else np.nan
                if (j_b >= 0 and np.isfinite(cvd[i]) and np.isfinite(cvd[j_b])
                        and cvd[i] > cvd[j_b] and c[i] > nv):
                    clong[i] = True
            j_b = i
    vwap = df["vwap_rth_r"] if "vwap_rth_r" in df.columns else None
    return {"short": (pd.Series(cshort, index=df.index), -1),
            "long": (pd.Series(clong, index=df.index), +1),
            "_lieu": pd.Series(lieu, index=df.index),
            "_cibles": {} if vwap is None else {-1: vwap, +1: vwap},
            "_extra": {"niveau_prix": pd.Series(nv_px, index=df.index),
                       "dist_niveau_ticks": pd.Series(d_tk, index=df.index),
                       "cvd_prec": pd.Series(cvd_prec, index=df.index)}}


SETUPS = {"C2_80PCT": c2_80pct, "C2_EOD": c2_eod,
          "C2_DIV_DELTA": c2_div_delta}
