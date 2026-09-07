"""L4 — la confirmation : série de vetos + glissement, jamais un score.

    from V3.layers.L4_orderflow import confirmation
    s = confirmation.charger_seuils("NQ")
    resultat = confirmation.confirmer(b_1min, i_debut, side, s, k=2, atr=...)

Rend le dict de la SPEC §4 : `decision` CONFIRME / VETO / INDISPONIBLE, le
motif, les CINQ booléens (tous évalués — l'attribution ne dépend pas de
l'ordre), le glissement en ATR, et l'info jamais décisionnelle.

Règles dures :
  - le premier veto VRAI de la série donne le motif ; tous sont évalués ;
  - un trou (None) se journalise `TROU_V*` ; en strict il rend la
    confirmation INDISPONIBLE, hors ligne il n'empêche rien — L4 n'est pas
    une porte de sécurité ;
  - fenêtre 1 min absente → INDISPONIBLE : l'entrée se fait comme sans L4,
    et c'est journalisé ;
  - RIEN n'a le droit de renforcer. L'absorption est `info` ; un test
    interdit qu'elle change la décision.

GLISSEMENT : `side × (prix_entrée_L4 − ouverture_t1) / ATR` — positif quand
attendre a DÉGRADÉ le prix d'entrée. LONG, open 100, confirmation 102,
ATR 10 → +0,2 (le cas du test, SPEC §7). C'est le coût que L4 doit battre :
elle passe si `séparation × taux_veto > glissement`.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3 import lecture                                        # noqa: E402
from V3.layers.L4_orderflow import vetos as V                 # noqa: E402

CHEMIN_SEUILS = os.path.join(os.path.dirname(__file__), "seuils.yaml")


def charger_seuils(sym):
    """Les seuils du yaml, RÉSOLUS par instrument : `g1_ES`/`g1_NQ` deviennent
    un seul `g1` — un veto ne sait pas sur quel instrument il tourne.

    Deux refus, jamais silencieux (revue du 07/09, R3/R6) :
      - un instrument inconnu lève — sinon les seuils suffixés disparaissent
        et V3/V4 tournent en trou permanent sans un mot ;
      - la RÈGLE DURE du yaml : un seuil `null` sur un veto `appliquee`
        refuse de tourner. Tous naissent `observee` ; le jour où l'un passe
        appliqué avec un trou de seuil, ça doit CASSER, pas journaliser.

    Rend {"k": ..., "V1": {...}, ..., "info": {...}, "modes": {...}}."""
    import yaml
    if sym not in ("ES", "NQ"):
        raise ValueError("instrument inconnu pour les seuils L4 : %r" % sym)
    with open(CHEMIN_SEUILS, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    out = {"k": cfg["fenetre"]["k_barres_1min"], "modes": {}, "info": {}}
    for vid, bloc in cfg["vetos"].items():
        s = {}
        for cle, valeur in (bloc.get("seuils") or {}).items():
            if cle.endswith("_ES") or cle.endswith("_NQ"):
                if cle.endswith("_" + sym):
                    s[cle[:-3]] = valeur
            else:
                s[cle] = valeur
        mode = bloc.get("mode", "observee")
        if mode == "appliquee" and any(v is None for v in s.values()):
            raise ValueError("%s : seuil null en mode appliquee — la regle "
                             "dure du yaml refuse de tourner" % vid)
        out[vid] = s
        out["modes"][vid] = mode
    out["info"] = dict(cfg.get("info", {}).get("absorption", {}))
    return out


def _absorption(lec, seuils_info, rvol_r=None):
    """INFO seulement — jamais décisionnelle (un test l'interdit).

    Sens du delta si |delta/vol| passe le plancher ET que le volume relatif
    est anormal. `rvol_r` absent → None : pas de moitié de réponse."""
    d, mini = lec["delta_k"], seuils_info.get("delta_vol_min")
    r_min = seuils_info.get("rvol_r_min")
    if d is None or mini is None or r_min is None or rvol_r is None:
        return None
    if abs(d) < mini or rvol_r < r_min:
        return 0
    return 1 if d > 0 else -1


def confirmer(b, i_debut, side, s, k=None, atr=None, strict=False,
              rvol_r=None, cvd_sess_r=None):
    """La série V1→V5 sur la fenêtre de `k` barres 1 min ouvrant à `i_debut`.

    `s` : seuils résolus (`charger_seuils`). `k` : taille de fenêtre — passée
    par la mesure (1/2/3) tant que `fenetre.k_barres_1min` est null ; une fois
    `k` écrit dans DECISIONS.md, l'omettre lit le yaml.
    `atr` : l'ATR-15m de la barre du signal, en POINTS — sans lui le
    glissement est None, jamais 0."""
    if k is None:
        k = s.get("k")
    if not k:
        return {"decision": "INDISPONIBLE", "motif": "K_NON_CHOISI",
                "vetos": {}, "barres_confirmation": None,
                "prix_entree_l4": None, "glissement_atr": None, "info": {}}
    lec = lecture.lire_l4(b, i_debut, int(k))
    if lec is None:
        return {"decision": "INDISPONIBLE", "motif": "FENETRE_ABSENTE",
                "vetos": {}, "barres_confirmation": None,
                "prix_entree_l4": None, "glissement_atr": None, "info": {}}

    verdicts, motif = {}, ""
    for vid, fn in V.SERIE:
        verdicts[vid] = fn(lec, side, s.get(vid, {}))
    for vid, _fn in V.SERIE:                 # le premier VRAI de la serie
        if verdicts[vid] is True:
            motif = vid
            break
    trous = [vid for vid, _ in V.SERIE if verdicts[vid] is None]
    # En strict, seuls les trous des vetos APPLIQUES rendent la confirmation
    # indisponible : un veto observe qui ne sait pas repondre se journalise
    # et n'empeche rien — L4 n'est pas une porte de securite (SPEC §3).
    # Pendant l'ombre tout est observe : strict ne ferme donc jamais sur V5.
    trous_appliques = [vid for vid in trous
                       if s.get("modes", {}).get(vid) == "appliquee"]

    if motif:
        decision = "VETO"
    elif strict and trous_appliques:
        decision, motif = "INDISPONIBLE", "TROU_%s" % trous_appliques[0]
    else:
        decision = "CONFIRME"

    glissement = None
    if (atr and atr > 0 and lec["prix_entree_l4"] is not None
            and lec["ouverture_t1"] is not None):
        glissement = side * (lec["prix_entree_l4"] - lec["ouverture_t1"]) / atr

    return {
        "decision": decision, "motif": motif, "vetos": verdicts,
        "barres_confirmation": lec["k"],
        "prix_entree_l4": lec["prix_entree_l4"],
        "glissement_atr": glissement,
        "info": {
            "absorption_sens": _absorption(lec, s.get("info", {}), rvol_r),
            # F18 : journalisee, JAMAIS lue par un veto ce cycle — le champ
            # attend sa definition (BN/F23), None = pas encore lu.
            "bn_alignees": None,
            "cvd_sess_r": cvd_sess_r,
        },
    }
