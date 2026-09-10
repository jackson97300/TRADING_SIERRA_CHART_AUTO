"""SCÉNARIOS — les SORTIES du scénario (spec §9) : `B-SCEN`, une variante de
barrière HORS LIGNE, journalisée à côté de B-ATR / B-NIV / B-NAT, mesurée au
jour 61, jamais appliquée en campagne. Ce ne sont pas des « TP/SL
conseillés » : ce scénario se termine ici, et meurt là.

    s = b_scen(zones, scenario, side, entree, atr, sym)

  TP du scénario = la prochaine zone `cible` dans le sens du trade, DEVANT
                   l'obstacle : `prix - marge_tp_ticks x tick x side` — la
                   même marge que B-NIV (L5 `seuils.yaml`), jamais une autre.
  SL du scénario = DERRIÈRE la zone d'`invalidation` du scénario contre le
                   trade, plus le buffer de balayage : `prix - buffer_sweep_atr
                   x atr x side` — le même buffer que B-NIV. Le stop est là où
                   le scénario meurt, pas à une distance fixe (la règle V1 de
                   Jackson, avec le scénario comme raison du placement).
  Sans zone cible dans le sens, ou sans zone d'invalidation contre : le champ
  vaut None AVEC son motif — jamais un repli silencieux sur B-ATR.
Aucune logique nouvelle : L5 sait déjà placer ; le scénario dit derrière quoi
et devant quoi. Test : parité de la formule avec `barrieres.b_niv`.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.layers.L5_risque import barrieres                     # noqa: E402
from V3.scenarios import lot                                    # noqa: E402

_CFG = None


def cfg_niv():
    """Le bloc B-NIV du yaml L5 — buffer de balayage et marge devant le TP,
    lus UNE fois, jamais recopiés."""
    global _CFG
    if _CFG is None:
        _CFG = barrieres.charger_seuils()["B-NIV"]
    return _CFG


def b_scen(zones, scenario, side, entree, atr, sym, cfg=None):
    """`zones` : la liste exportée par `zones.exporter` (rôles posés par la
    grammaire pour `scenario`). `side` +1 long / -1 short. Rend le dict de
    barrière au format de `barrieres.py`."""
    c = cfg or cfg_niv()
    buffer_atr, marge_ticks = c["buffer_sweep_atr"][sym], c["marge_tp_ticks"]
    cibles = [z for z in zones if z.get("role") == "cible" and (z["prix"] - entree) * side > 0]
    invalid = [z for z in zones if z.get("role") == "invalidation" and (z["prix"] - entree) * side < 0]
    tp_prix = niveau_tp = motif_tp = None
    if cibles:
        z = min(cibles, key=lambda z: abs(z["prix"] - entree))
        tp_prix = round(z["prix"] - marge_ticks * lot.TICK * side, 2)          # DEVANT l'obstacle
        niveau_tp, motif_tp = {"nom": z["nom"], "prix": z["prix"], "role": "cible"}, "zone_cible"
    else:
        motif_tp = "aucune_zone_cible_dans_le_sens"
    sl_prix = niveau_sl = motif_sl = None
    if invalid:
        z = min(invalid, key=lambda z: abs(z["prix"] - entree))
        sl_prix = round(z["prix"] - buffer_atr * atr * side, 2)               # DERRIÈRE l'invalidation
        niveau_sl, motif_sl = {"nom": z["nom"], "prix": z["prix"], "role": "invalidation"}, "zone_invalidation"
    else:
        motif_sl = "aucune_zone_invalidation_contre"
    return {"barriere": "B-SCEN", "scenario": scenario, "side": side, "entree": entree,
            "sl_prix": sl_prix, "tp_prix": tp_prix, "niveau_sl": niveau_sl, "niveau_tp": niveau_tp,
            "motif_sl": motif_sl, "motif_tp": motif_tp, "buffer_sweep_atr": buffer_atr,
            "marge_tp_ticks": marge_ticks, "plafonne": False,
            "r_multiple": (round(abs(tp_prix - entree) / abs(sl_prix - entree), 2)
                           if sl_prix is not None and tp_prix is not None and sl_prix != entree else None)}


def texte(s):
    """Une ligne, sans conseil : où le scénario finit, où il meurt."""
    fin = ("%s (%s devant %s)" % (s["tp_prix"], s["scenario"], s["niveau_tp"]["nom"]) if s["tp_prix"] is not None
           else "pas de zone cible dans le sens")
    mort = ("%s (derriere %s + buffer %s ATR)" % (s["sl_prix"], s["niveau_sl"]["nom"], s["buffer_sweep_atr"])
            if s["sl_prix"] is not None else "pas de zone d'invalidation contre")
    return "sorties du scenario : se termine a %s ; meurt a %s" % (fin, mort)
