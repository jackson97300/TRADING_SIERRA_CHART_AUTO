"""Les cinq vetos L4 — série, un seul droit : annuler.

Contrat : `(lec_l4, side, s) -> True | False | None`. `side` vaut +1 (LONG) ou
−1 (SHORT), les règles sont écrites LONG et le miroir est mécanique. `s` est
le dict de seuils DÉJÀ RÉSOLU par instrument (`confirmation.charger_seuils`) —
un veto ne sait pas s'il tourne sur ES ou NQ, et c'est voulu : `g1_ES/g1_NQ`
(rapport 7,6) se résolvent en un seul `g1` avant lui.

`None` = « je ne peux pas répondre » (colonne absente, seuil non posé) — un
TROU journalisé, jamais un feu vert. V5 rend None TANT QUE ses seuils sont
`null` : ses colonnes sources sont l'une saturée, l'autre d'unité trompeuse
(seuils.yaml, pièges du 07/09).

LE SENS de V3, écrit avant le code (condition de la revue du 07/09) :
volume au ASK = acheteurs agressifs → adverse à un SHORT ; volume au BID =
vendeurs agressifs → adverse à un LONG. Le test miroir échoue si ça s'inverse.

« Finish contraire » de V4 : la barre clôture dans la MOITIÉ opposée de son
range (`range_pos` sous 1/2 pour un LONG, au-dessus pour un SHORT) — la
frontière de signe, pas un seuil : `finish_delta_pct` 1 min sature à 1,0 et
ne porte aucun seuil posable (seuils.yaml V5).
"""

from __future__ import annotations


def v1_personne_n_achete(lec, side, s):
    """LONG : `ask_pct_k < a1` — personne n'achète pendant la confirmation."""
    p = lec["ask_pct_k"] if side > 0 else lec["bid_pct_k"]
    return None if p is None or s.get("a1") is None else bool(p < s["a1"])


def v2_flux_contre(lec, side, s):
    """LONG : `delta_k < −d1` — le flux de la fenêtre pousse contre."""
    d = lec["delta_k"]
    if d is None or s.get("d1") is None:
        return None
    return bool(d < -s["d1"]) if side > 0 else bool(d > s["d1"])


def v3_print_adverse(lec, side, s):
    """Un print ≥ g1 est apparu pendant la confirmation, côté adverse.

    Adverse à un LONG = volume au BID (vendeurs agressifs)."""
    b = lec["big_bid_max_k"] if side > 0 else lec["big_ask_max_k"]
    return None if b is None or s.get("g1") is None else bool(b >= s["g1"])


def v4_epuisement(lec, side, s):
    """Une barre de la fenêtre : volume ≥ p99 ET range ≥ p95 ET finish
    contraire — l'épuisement DANS le sens, trois conditions sur leur
    distribution par instrument."""
    if s.get("vol_p99") is None or s.get("range_p95") is None:
        return None
    verdicts = []
    for barre in lec["barres"]:
        v, r, pos = barre["vol"], barre["range_pts"], barre["range_pos"]
        if v is None or r is None or pos is None:
            verdicts.append(None)
            continue
        contraire = pos < 0.5 if side > 0 else pos > 0.5
        verdicts.append(v >= s["vol_p99"] and r >= s["range_p95"] and contraire)
    if any(v is True for v in verdicts):
        return True
    return None if any(v is None for v in verdicts) else False


def v5_reniement(lec, side, s):
    """La réaction se renie : finish faible OU mèche contraire.

    `finish_k` est RECALCULÉ (position de la clôture de la dernière barre
    dans son range, 0-1) — jamais `finish_delta_pct`, saturée et condamnée.
    Le miroir `1 − f1` est positionnel, cohérent avec cette base.

    `f1` et `m1` sont `null` tant que leurs distributions PAR FENÊTRE ne sont
    pas mesurées : le veto rend None — TROU_V5, jamais une réponse inventée."""
    if s.get("f1") is None or s.get("m1") is None:
        return None
    meche = lec["meche_haute_k"] if side > 0 else lec["meche_basse_k"]
    if lec["finish_k"] is None or meche is None:
        return None
    faible = lec["finish_k"] < s["f1"] if side > 0 else lec["finish_k"] > (1 - s["f1"])
    return bool(faible or meche >= s["m1"])


# L'ORDRE de la série — V1 d'abord donne le motif, TOUS sont évalués.
SERIE = (("V1", v1_personne_n_achete), ("V2", v2_flux_contre),
         ("V3", v3_print_adverse), ("V4", v4_epuisement),
         ("V5", v5_reniement))
