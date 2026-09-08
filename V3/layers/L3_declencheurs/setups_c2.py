"""Les FONCTIONS de setup du brief OMBRE C2 — séparées du coureur.

`ombre_c2.py` porte le registre (LES_C2, ACTIFS), les seuils et le journal ;
ce module porte les fonctions pures (scindé 08/09, garde des 300 lignes —
le COMMENT ici, le QUOI courir là-bas).

Contrat d'une fonction de setup : `f(df, sym, seuils)` rend
    {"short": (cond, -1), "long": (cond, +1), "_lieu": cond_lieu, "_cibles":
     {side: prix_ou_Serie}, "_extra": {}?, "_sortie": str?, "_muet_jour": ?}
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

    Régime B5 : l'ouverture cash HORS de la VA veille (recalculée — jamais
    le flag C++ `rule_80pct`). Lieu ET acceptation sur le MÊME prédicat :
    la VA reconstruite figée (S1 : le flag C++ `inside_prev_va` divergeait
    d'un tick et fragmentait l'épisode ; unifié provenance A). Réaction :
    DEUX clôtures 15 min consécutives dans la VA. Side : vers le bord
    opposé (ouverture au-dessus → SHORT vers VAL ; miroir)."""
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

    Lieu : la barre 15h15-15h30 ET clôturée — DST géré DE BOUT EN BOUT
    depuis le 08/09 : `est_cash` amont est passé sur `minutes_et` (audit
    Fable §2, parité 0/271 940 barres — la dette qui aurait coupé la barre
    dès le 2/11 est FERMÉE ; résiduel côté recherche : A_FAIRE pt 19).
    Réaction :
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

    Lieu : NOUVEAU plus haut de session à ≤ P10 d'un niveau figé (prev_vah,
    pdh, mq_call — miroir bas : prev_val, pdl, mq_put). Réaction :
    `cvd_sess_r` au nouvel extrême < (resp. >) sa valeur au PRÉCÉDENT
    extrême de session, ET clôture du bon côté du niveau.
    GRAIN 15 MIN ÉCRIT : CVD lu à la CLÔTURE de la barre de l'extrême, pas
    au tick — la limitation des seize. Cible : `vwap_rth_r` de la barre (Série,
    échantillonnée au signal). NaN (cvd, atr, dist) = jamais un signal.
    Anti-fuite : extrêmes courants et cumuls, rien après t.

    V2 (08/09, arbitrage Fable B, adopté AVANT le premier rejeu officiel —
    aucune ligne v1 journalisée, pas de rétroactivité) : le seuil lit
    `atr_ref` (atr_barre, sinon ATR-VEILLE) — le trou 9h30-11h00 bouché
    pour ce setup NON GELÉ, `atr_source` journalisé ; sans `atr_ref`
    (frames nus), repli atr_barre, le trou revient — voulu. Niveaux MQ
    figés au snapshot du MATIN (le §9 prévoit midi — limitation écrite)."""
    vide = pd.Series(False, index=df.index)
    muet = {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
            "_cibles": {}}
    cols = {n: _col(df, n) for n in ("high", "low", "close",
                                     "cvd_sess_r", "atr_barre")}
    if any(v is None for v in cols.values()):
        return dict(muet, _muet_jour="colonne_absente")
    h, l_ = cols["high"].to_numpy(float), cols["low"].to_numpy(float)
    c, cvd = cols["close"].to_numpy(float), cols["cvd_sess_r"].to_numpy(float)
    base_atr = _col(df, "atr_ref")
    if base_atr is None:
        base_atr = cols["atr_barre"]
    p10 = np.asarray(HYP.seuil_ticks(base_atr, "P10"), float)
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
    extra = {"niveau_prix": pd.Series(nv_px, index=df.index),
             "dist_niveau_ticks": pd.Series(d_tk, index=df.index),
             "cvd_prec": pd.Series(cvd_prec, index=df.index)}
    if "atr_source" in df.columns:      # d'ou vient le seuil (v2, jour 61)
        extra["atr_source"] = df["atr_source"]
    return {"short": (pd.Series(cshort, index=df.index), -1),
            "long": (pd.Series(clong, index=df.index), +1),
            "_lieu": pd.Series(lieu, index=df.index),
            "_cibles": {} if vwap is None else {-1: vwap, +1: vwap},
            "_extra": extra}


def c2_poor(df, sym, s):
    """Réparation de poor high/low — brief §5. PRÉ-CÂBLÉ, PAS ACTIF :
    0 lieu sur 52 j × 2 (rapport lieu_poor) — l'état 15 min ne persiste
    jamais les 3 barres exigées : flag ROULANT 60 min, pas une mémoire
    d'épisode, et le retour vers le niveau l'éteint avant la clôture de
    fenêtre. Redesign J+2 : mémoire d'épisode en fiche F23 (un poor RESTE
    poor jusqu'à réparation/invalidation — Dalton), brief Fable.

    L'état `ctx_poor_high/low` vient du producteur 1 min (REPRODUIT
    mismatch=0, test_ctx), porté à l'agrégat par sa dernière minute de
    fenêtre — grain 15 min écrit. Formation = passage à l'état poor ; le
    PRIX du poor est FIGÉ là (le plus haut de session de cette barre) et
    RE-FIGÉ si un nouvel extrême survient poor toujours actif ; flag
    retombé = épisode clos. Lieu : poor formé depuis ≥ `formation_min_barres`
    ET extrême de la barre revenu à ≤ P10 du prix figé. Réaction : clôture
    AU-DELÀ du prix du poor (la réparation) avec rvol_r ≥ rvol_min (p50
    mesuré). Side : LONG à travers le poor high, SHORT miroir. Cible : le
    prochain niveau figé au-delà (pdh/prev_vah/mq_call, miroir bas) — NaN
    si aucun. Trou de chauffe comme DIV v1 (atr_barre ; atr_ref au redesign).
    L'évaluation de la barre i lit l'état d'AVANT i (le repair fait souvent
    un nouvel extrême : re-figer d'abord tuerait chaque signal). NaN =
    jamais un signal — et un flag NaN CLÔT l'épisode (fillna(0),
    conservateur ; le brief J+2 tranchera : tenir l'état ou le clore).
    Anti-fuite : états courants seulement."""
    cfg = s.get("C2_POOR") or {}
    rvol_min = (cfg.get("rvol_min") or {}).get(sym)
    if rvol_min is None:
        raise ValueError("C2_POOR actif sans rvol_min %s — poser la"
                         " distribution dans seuils_c2.yaml" % sym)
    age_min = int(cfg.get("formation_min_barres", 3))
    vide = pd.Series(False, index=df.index)
    muet = {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
            "_cibles": {}}
    cols = {n: _col(df, n) for n in ("high", "low", "close", "ctx_poor_high",
                                     "ctx_poor_low", "rvol_r", "atr_barre")}
    if any(v is None for v in cols.values()):
        return dict(muet, _muet_jour="colonne_absente")
    h, l_, c = (cols[n].to_numpy(float) for n in ("high", "low", "close"))
    ph = cols["ctx_poor_high"].fillna(0).to_numpy(float) > 0
    pl = cols["ctx_poor_low"].fillna(0).to_numpy(float) > 0
    rv = cols["rvol_r"].to_numpy(float)
    p10 = np.asarray(HYP.seuil_ticks(cols["atr_barre"], "P10"), float)
    cib_h = _figes(df, ("dist_pdh", "dist_prev_vah", "dist_mq_call"))
    cib_b = _figes(df, ("dist_pdl", "dist_prev_val", "dist_mq_put"))
    lieu = np.zeros(len(df), bool)
    clong, cshort = np.zeros(len(df), bool), np.zeros(len(df), bool)
    # DEUX colonnes de prix, jamais une ecrasee : les deux lieux peuvent
    # tomber sur la MEME barre (review R2), le journal porte les deux.
    poor_h_px, poor_b_px, cib_l, cib_s = (np.full(len(df), np.nan)
                                          for _ in range(4))
    hmax, lmin = -np.inf, np.inf
    px_h = idx_h = px_b = idx_b = None
    for i in range(len(df)):
        # 1) evaluer contre l'etat d'AVANT la barre i
        if (px_h is not None and i - idx_h >= age_min
                and np.isfinite(h[i]) and (px_h - h[i]) / TICK <= p10[i]):
            lieu[i], poor_h_px[i] = True, px_h
            if np.isfinite(rv[i]) and rv[i] >= rvol_min and c[i] > px_h:
                clong[i] = True
                dessus = [x for x in cib_h if x > px_h]
                if dessus:
                    cib_l[i] = min(dessus)
        if (px_b is not None and i - idx_b >= age_min
                and np.isfinite(l_[i]) and (l_[i] - px_b) / TICK <= p10[i]):
            lieu[i], poor_b_px[i] = True, px_b
            if np.isfinite(rv[i]) and rv[i] >= rvol_min and c[i] < px_b:
                cshort[i] = True
                dessous = [x for x in cib_b if x < px_b]
                if dessous:
                    cib_s[i] = max(dessous)
        # 2) mettre a jour l'etat avec la barre i
        neuf_h = np.isfinite(h[i]) and h[i] > hmax
        neuf_b = np.isfinite(l_[i]) and l_[i] < lmin
        hmax = h[i] if neuf_h else hmax
        lmin = l_[i] if neuf_b else lmin
        if ph[i] and np.isfinite(hmax):
            if px_h is None or neuf_h:
                px_h, idx_h = hmax, i          # formation / re-formation
        elif not ph[i]:
            px_h = idx_h = None                # episode clos
        if pl[i] and np.isfinite(lmin):
            if px_b is None or neuf_b:
                px_b, idx_b = lmin, i
        elif not pl[i]:
            px_b = idx_b = None
    return {"short": (pd.Series(cshort, index=df.index), -1),
            "long": (pd.Series(clong, index=df.index), +1),
            "_lieu": pd.Series(lieu, index=df.index),
            "_cibles": {+1: pd.Series(cib_l, index=df.index),
                        -1: pd.Series(cib_s, index=df.index)},
            "_extra": {"poor_prix_h": pd.Series(poor_h_px, index=df.index),
                       "poor_prix_b": pd.Series(poor_b_px, index=df.index),
                       "rvol_r": cols["rvol_r"]}}


SETUPS = {"C2_80PCT": c2_80pct, "C2_EOD": c2_eod,
          "C2_DIV_DELTA": c2_div_delta, "C2_POOR": c2_poor}
