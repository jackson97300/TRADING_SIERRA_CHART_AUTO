"""Les trois barrières par signal — B-ATR, B-NIV (H-L5-NIVEAUX), B-NAT.

Fonctions PURES, calcul HORS LIGNE (le script `barrieres_du_jour.py` les
appelle après le rejeu de 21:01 ; rien ici ne touche la chaîne). Règles :
niveaux FIGÉS à la barre du signal (reconstruits `close + dist × tick`,
la méthode F23) ; éligibilité v1 = provenance A/reproduite seulement ;
JAMAIS `gamma_block_*` dans les candidats (un test l'interdit) ; aucun
`null` sans motif à côté (SPEC L5 §3).
"""

from __future__ import annotations

import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.research.hypothesis_runner import (                 # noqa: E402
    COUT_DOLLARS, VAL_POINT)

TICK = 0.25   # default ES/NQ. MGC=0,10 — hors perimetre du cycle.
CHEMIN_SEUILS = os.path.join(os.path.dirname(__file__), "seuils.yaml")
CHEMIN_SEUILS_L0 = os.path.join(os.path.dirname(__file__), os.pardir,
                                "L0_interrupteur", "seuils.yaml")
# nom de niveau (seuils.yaml) -> colonne dist_* (ticks, niveau - close)
COLONNES_NIVEAUX = {
    "prev_vah": "dist_prev_vah", "prev_val": "dist_prev_val",
    "prev_vpoc": "dist_prev_vpoc", "ib_high": "dist_ib_high",
    "ib_low": "dist_ib_low", "pdh": "dist_pdh", "pdl": "dist_pdl",
    "ovn_high": "dist_ovn_high", "ovn_low": "dist_ovn_low",
    "mq_call": "dist_mq_call", "mq_put": "dist_mq_put",
    "mq_hvl": "dist_mq_hvl", "cur_vpoc": "dist_cur_vpoc",
}
# JAMAIS recopie : les memes constantes que triple_barriere — la parite
# est structurelle, pas une coincidence de duplication (review R1).
COUTS = {sym: (COUT_DOLLARS[sym], VAL_POINT[sym]) for sym in COUT_DOLLARS}


def charger_seuils():
    """Les barrieres du yaml L5 + le seuil de frais du yaml L0 (une seule
    verite, review R2). Le denominateur diverge VOLONTAIREMENT de la porte
    L0 : elle lit le TP de reference 1,5 ATR, les barrieres lisent le TP
    REEL du niveau — la meme part, generalisee."""
    import yaml
    with open(CHEMIN_SEUILS, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)["barrieres"]
    with open(CHEMIN_SEUILS_L0, encoding="utf-8") as fh:
        l0 = yaml.safe_load(fh)
    part = l0["portes"]["L5_FRAIS_TROP_LOURDS"]["seuils"]["part_max"]
    for bloc in ("B-NIV", "B-NAT"):
        cfg[bloc]["part_max_frais"] = part
    return cfg


def charger_sortie():
    """La table de sortie horaire par famille (C3) — `{defaut, par_famille}`.

    Une DEFINITION, pas un seuil (cf en-tete seuils.yaml) : C2_EOD sort a la
    cloture, les autres au plat de fin de journee. Config, jamais en dur."""
    import yaml
    with open(CHEMIN_SEUILS, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["sortie_horaire_et"]


def _niveaux_figes(df, i, noms):
    """{nom: prix} reconstruits À la barre du signal — figés par F23.
    Un dist NaN = niveau inconnu ce jour : absent de la liste, jamais 0."""
    close = float(pd.to_numeric(df["close"], errors="coerce").iloc[i])
    out = {}
    for nom in noms:
        col = COLONNES_NIVEAUX.get(nom)
        if col is None or col not in df.columns:
            continue
        d = pd.to_numeric(df[col], errors="coerce").iloc[i]
        if pd.notna(d):
            out[nom] = close + float(d) * TICK
    return out


def b_atr(entree, atr, side, s):
    """La référence qui tourne — mêmes nombres que `triple_barriere()`."""
    return {"barriere": "B-ATR",
            "sl_prix": entree - s["seuils"]["sl_atr"] * atr * side,
            "tp_prix": entree + s["seuils"]["tp_atr"] * atr * side,
            "niveau_sl": None, "niveau_tp": None,
            "motif_sl": "atr", "motif_tp": "atr",
            "buffer_sweep_atr": None, "plafonne": False,
            "verdict": "trade", "candidats_ecartes": []}


def b_niv(df, i, side, sym, s, entree, atr):
    """H-L5-NIVEAUX : SL derrière le premier niveau éligible CONTRE + buffer ;
    TP devant le prochain niveau DANS le sens, plafonné. Défaut = B-ATR,
    toujours avec motif."""
    cfg = s
    fen_min, fen_max = cfg["sl_fenetre_atr"]
    buffer_atr = cfg["buffer_sweep_atr"][sym]
    niveaux = _niveaux_figes(df, i, cfg["niveaux"])
    ecartes, sl_choix, tp_choix = [], None, None

    for nom, prix in sorted(niveaux.items(), key=lambda kv: abs(kv[1] - entree)):
        dist_atr = (prix - entree) / atr * side     # >0 = dans le sens du TP
        if dist_atr < 0:                            # CONTRE le trade -> cote SL
            d = -dist_atr
            if d < fen_min:
                ecartes.append({"nom": nom, "dist_atr": round(-d, 3),
                                "raison": "trop_pres"})
            elif d > fen_max:
                ecartes.append({"nom": nom, "dist_atr": round(-d, 3),
                                "raison": "hors_fenetre"})
            elif sl_choix is None:
                sl_choix = (nom, prix, d)
            else:
                ecartes.append({"nom": nom, "dist_atr": round(-d, 3),
                                "raison": "plus_loin_que_le_choisi"})
        else:                                       # DANS le sens -> cote TP
            if dist_atr < cfg["tp_min_atr"]:
                ecartes.append({"nom": nom, "dist_atr": round(dist_atr, 3),
                                "raison": "sous_tp_min"})
            elif tp_choix is None:
                tp_choix = (nom, prix, dist_atr)
            else:
                ecartes.append({"nom": nom, "dist_atr": round(dist_atr, 3),
                                "raison": "plus_loin_que_le_choisi"})

    plafonne = False
    if sl_choix is None:
        sl_prix = entree - cfg["plafond_sl_atr"] * atr * side
        motif_sl, niveau_sl = "defaut_aucun_niveau", None
    else:
        nom, prix, d = sl_choix
        sl_prix = prix - buffer_atr * atr * side    # DERRIERE le niveau
        niveau_sl = {"nom": nom, "prix": prix, "dist_atr": round(d, 3)}
        motif_sl = "niveau"
        if abs(sl_prix - entree) > cfg["plafond_sl_atr"] * atr:
            sl_prix = entree - cfg["plafond_sl_atr"] * atr * side
            motif_sl, plafonne = "plafonne", True

    plafond_tp = entree + cfg["plafond_tp_atr"] * atr * side
    if tp_choix is None:
        tp_prix, motif_tp, niveau_tp = plafond_tp, "defaut_aucun_niveau", None
    else:
        nom, prix, d = tp_choix
        tp_prix = prix - cfg["marge_tp_ticks"] * TICK * side   # DEVANT
        niveau_tp = {"nom": nom, "prix": prix, "dist_atr": round(d, 3)}
        motif_tp = "niveau"
        if (tp_prix - plafond_tp) * side > 0:
            tp_prix, motif_tp = plafond_tp, "plafonne"

    verdict = _verdict_frais(entree, tp_prix, sym, cfg["part_max_frais"])
    return {"barriere": "B-NIV", "sl_prix": sl_prix, "tp_prix": tp_prix,
            "niveau_sl": niveau_sl, "niveau_tp": niveau_tp,
            "motif_sl": motif_sl, "motif_tp": motif_tp,
            "buffer_sweep_atr": buffer_atr, "plafonne": plafonne,
            "verdict": verdict, "candidats_ecartes": ecartes}


def _verdict_frais(entree, tp_prix, sym, part_max):
    frais, val_pt = COUTS[sym]
    tp_usd = abs(tp_prix - entree) * val_pt
    return "veto_frais" if (tp_usd <= 0 or frais / tp_usd > part_max) else "trade"


def b_nat(df, i, side, sym, s, entree, atr, famille):
    """La sortie naturelle : la cible du déclencheur, figée au signal.
    SL = B-ATR. TROIS motifs de défaut distincts (review R8) — le jour 61
    doit savoir si la famille n'a pas de cible, si la cible n'est pas
    câblée, ou si elle était déjà atteinte (artefact, review R7)."""
    cible_nom = (s.get("cible_par_famille") or {}).get(famille)
    if cible_nom == "cur_vpoc_fige":
        cible_nom = "cur_vpoc"
    sl_prix = entree - s["sl_atr"] * atr * side
    defaut = {"barriere": "B-NAT", "sl_prix": sl_prix,
              "tp_prix": entree + s["plafond_tp_atr"] * atr * side,
              "niveau_sl": None, "niveau_tp": None, "motif_sl": "atr",
              "buffer_sweep_atr": None, "plafonne": False,
              "verdict": "trade", "candidats_ecartes": []}
    if cible_nom is None:
        return dict(defaut, motif_tp="pas_de_cible_famille")
    if cible_nom not in COLONNES_NIVEAUX:
        return dict(defaut, motif_tp="cible_non_cablee")
    niveaux = _niveaux_figes(df, i, [cible_nom])
    if not niveaux:
        return dict(defaut, motif_tp="pas_de_cible_famille")
    nom, prix = next(iter(niveaux.items()))
    dist = (prix - entree) / atr * side
    if dist <= 0:
        # la cible est A ou DERRIERE l'entree : un « TP » instantane serait
        # du pur frais moyenne avec les vraies sorties (vu au 04/09)
        return dict(defaut, motif_tp="cible_deja_atteinte")
    return {"barriere": "B-NAT", "sl_prix": sl_prix, "tp_prix": prix,
            "niveau_sl": None,
            "niveau_tp": {"nom": nom, "prix": prix, "dist_atr": round(dist, 3)},
            "motif_sl": "atr", "motif_tp": "cible_famille",
            "buffer_sweep_atr": None, "plafonne": False,
            "verdict": _verdict_frais(entree, prix, sym, s["part_max_frais"]),
            "candidats_ecartes": []}


def issue(df, i, side, sl_prix, tp_prix, sym, expiration=20):
    """Premier touché, expiration sinon — entrée à l'open de t+1, pnl NET en
    ATR. Même moteur que `triple_barriere`, prix explicites."""
    j = i + 1
    if j >= len(df):
        return None
    atr = float(pd.to_numeric(df["atr_barre"], errors="coerce").iloc[i])
    if not atr or atr <= 0 or pd.isna(atr):
        return None
    entree = float(pd.to_numeric(df["open"], errors="coerce").iloc[j])
    frais, val_pt = COUTS[sym]
    couts_atr = frais / (atr * val_pt)
    fin = min(j + expiration, len(df) - 1)
    for k in range(j, fin + 1):
        h = float(pd.to_numeric(df["high"], errors="coerce").iloc[k])
        lo = float(pd.to_numeric(df["low"], errors="coerce").iloc[k])
        touche_tp = h >= tp_prix if side > 0 else lo <= tp_prix
        touche_sl = lo <= sl_prix if side > 0 else h >= sl_prix
        if touche_sl:                     # le SL d'abord : convention prudente
            return "SL", (sl_prix - entree) / atr * side - couts_atr, k
        if touche_tp:
            return "TP", (tp_prix - entree) / atr * side - couts_atr, k
    c = float(pd.to_numeric(df["close"], errors="coerce").iloc[fin])
    return "EXPIRATION", (c - entree) / atr * side - couts_atr, fin
