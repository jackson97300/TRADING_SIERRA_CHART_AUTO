"""SCÉNARIOS — la grammaire v0 (spec §1, décisions Fable du 10/09 à `e26236a`).

Un scénario est une SÉQUENCE D'ÉTATS DATÉS, jamais une position, jamais une
direction attendue. Ce module ne lit que des faits CAUSAUX : acceptations à
deux clôtures, tenues `tenu_a`, états de `range_r`, `open_type_r` — jamais
l'`issue` F23. Rejoué barre à barre sur les barres 0..i seules, il rend le
même état que sur la journée complète (test « direct = rétrospectif »).

Les huit canoniques v0 (Fable, relectures e26236a puis c6c12dd) — des FAMILLES
en MIROIR EXACT, et ce qui les valide / invalide :
  S_OUV_HAUT_TEND      ouvre > VAH ; validé : acceptation > IB high ;
                       invalidé : réintégration ACCEPTÉE (→ S_OUV_HAUT_REINT)
  S_OUV_HAUT_REINT     réintégration acceptée depuis le haut — validé à
                       l'acceptation (deux clôtures dans la VA) ; `precision`
                       ∈ {PULL, TRAV, null} : PULL = pullback sur le VAH TENU
                       (puis NOUVEL_EXTREME_APRES_PULLBACK, daté), TRAV = 80 %
                       vers la VAL SANS pullback ; invalidé : acceptation > VAH
                       (reprise → TEND) ; TRAV puis rejet au VPOC accepté →
                       S_AUTRE(rejet_vpoc)
  S_OUV_BAS_TEND       miroir exact de HAUT_TEND
  S_OUV_BAS_REINT      miroir exact de HAUT_REINT (précisions PULL / TRAV)
  S_DANS_POSE          ouvre dans la VA → IB posée, aucune acceptation dehors
                       (validé à la clôture) ; invalidé : CASSE (→ CASSURE)
  S_DANS_CASSURE_H/B   acceptation au-delà d'un bord de l'IB ; validé : retest
                       tenu (CONTINUATION) ; invalidé : REGAIN (→ HEADFAKE)
  S_DANS_HEADFAKE      cassure acceptée → regain à deux clôtures (validé au
                       regain) ; invalidé : nouvelle acceptation dehors
  gardes : S_DANS_ROTATION (ETABLI strict, rare) ; S_AUTRE(raison) pour tout le
  reste — IB hors [w_min, w_max] sur une ouverture dans la VA, rejet au VPOC,
  pas de VA, journée sans IB.
Réintégration : TENTÉE = une clôture dans la VA ; ACCEPTÉE = deux. Une famille
avec `precision: null` est un canonique, pas S_AUTRE. Chaque changement de
scénario est une BASCULE datée avec sa cause, jamais une correction. Chaque
ligne porte `etat_scenario` ∈ {en_cours, valide, invalide} et un `titre` :
« S_OUV_HAUT_TEND (en cours, non validé) » / « (validé 10h45) » — un scénario
en cours non validé ne fait rien s'armer (`arme: false`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Fable, relecture c6c12dd (10/09) : les codes sont des FAMILLES en miroir exact ;
# PULL / TRAV sont une `precision` (PULL, TRAV ou null), jamais un code.
CANONIQUES = ("S_OUV_HAUT_TEND", "S_OUV_HAUT_REINT", "S_OUV_BAS_TEND", "S_OUV_BAS_REINT",
              "S_DANS_POSE", "S_DANS_CASSURE_HAUT", "S_DANS_CASSURE_BAS", "S_DANS_HEADFAKE")
GARDES = ("S_DANS_ROTATION",)
FAMILLES = CANONIQUES + GARDES
PRECISIONS = ("PULL", "TRAV")
ETATS_SCENARIO = ("en_cours", "valide", "invalide")
QUATRE_VINGTS = 0.8          # la règle des 80 % de Dalton — une définition, pas un seuil mesuré
DERNIERE_BARRE_ET = 15 * 60 + 45   # la barre 15h45 ET : la clôture cash


def _minutes_et(ts):
    from CORE.features import recalc
    return int(recalc.minutes_et(pd.Series([int(ts)]).pipe(pd.to_datetime, unit="ms", utc=True)).iloc[0])


def _hhmm(ts):
    m = _minutes_et(ts)
    return "%02dh%02d" % (m // 60, m % 60)

# rôle des zones par scénario (v0) : cible | invalidation | pullback | neutre
ROLES = {
    "S_OUV_HAUT_TEND": {"prev_vah": "invalidation", "ib_high": "cible", "ib_low": "neutre"},
    "S_OUV_HAUT_REINT": {"prev_vah": "pullback", "prev_vpoc": "cible", "prev_val": "cible"},
    "S_OUV_BAS_TEND": {"prev_val": "invalidation", "ib_low": "cible", "ib_high": "neutre"},
    "S_OUV_BAS_REINT": {"prev_val": "pullback", "prev_vpoc": "cible", "prev_vah": "cible"},
    "S_DANS_POSE": {"ib_high": "invalidation", "ib_low": "invalidation", "prev_vpoc": "cible"},
    "S_DANS_ROTATION": {"ib_high": "invalidation", "ib_low": "invalidation", "prev_vpoc": "cible"},
    "S_DANS_CASSURE_HAUT": {"ib_high": "pullback", "ib_low": "neutre"},
    "S_DANS_CASSURE_BAS": {"ib_low": "pullback", "ib_high": "neutre"},
    "S_DANS_HEADFAKE": {},
}
# ce qui ne se trade pas, par scénario (v0) — des définitions, pas des seuils
HORS_SCENARIO = {
    "S_OUV_HAUT_TEND": [("short", "prev_vah", "fade contre l'ouverture au-dessus"),
                        ("short", "ib_high", "fade de la cassure attendue")],
    "S_OUV_HAUT_REINT": [("long", "prev_vah", "chasser la reprise avant acceptation")],
    "S_OUV_BAS_TEND": [("long", "prev_val", "fade contre l'ouverture en dessous"),
                       ("long", "ib_low", "fade de la cassure attendue")],
    "S_OUV_BAS_REINT": [("short", "prev_val", "vendre le pullback d'une reintegration acceptee")],
    "S_DANS_POSE": [("long", "ib_high", "cassure non acceptee"), ("short", "ib_low", "cassure non acceptee")],
    "S_DANS_ROTATION": [("long", "ib_high", "cassure non acceptee"), ("short", "ib_low", "cassure non acceptee")],
    "S_DANS_CASSURE_HAUT": [("short", "ib_high", "fade d'une cassure acceptee")],
    "S_DANS_CASSURE_BAS": [("long", "ib_low", "fade d'une cassure acceptee")],
    "S_DANS_HEADFAKE": [],
}


def _prix(zones, nom):
    for z in zones:
        if z["nom"] == nom:
            return z["prix"]
    return None


class Grammaire:
    """L'état d'une journée, nourri barre à barre par `barre()`."""

    def __init__(self, sym, zones, bornes_ib):
        self.sym, self.zones, self.bornes = sym, zones, bornes_ib
        self.vah, self.val, self.vpoc = _prix(zones, "prev_vah"), _prix(zones, "prev_val"), _prix(zones, "prev_vpoc")
        self.position = None
        self.type_ouverture = None
        self.scenario, self.depuis, self.precision = None, None, None
        self.valide_a = None
        self.sequence, self.validations, self.invalidations, self.bascules = [], [], [], []
        self.reintegration = {"tentee_i": None, "acceptee_i": None}
        self.session_high = self.session_low = None
        self.pullback = None            # {"i": barre du test tenu, "high"/"low": extrême de session à ce moment}
        self.vu_vpoc = False
        self.ib = None

    # --- outils -------------------------------------------------------------
    def _ev(self, i, ts, etat, **k):
        self.sequence.append({"i": i, "ts": int(ts), "etat": etat, **k})

    def _bascule(self, i, ts, vers, cause):
        self.bascules.append({"i": i, "ts": int(ts), "de": self.scenario, "vers": vers, "cause": cause})
        self.scenario, self.depuis, self.precision, self.valide_a = vers, int(ts), None, None
        self._ev(i, ts, "BASCULE", vers=vers, cause=cause)

    def _valider(self, i, ts, quoi, zone):
        if self.valide_a is None:
            self.valide_a = i
            self.validations.append({"i": i, "ts": int(ts), "quoi": quoi, "zone": zone, "scenario": self.scenario})

    def _invalider(self, i, ts, quoi, zone, vers, cause):
        self.invalidations.append({"i": i, "ts": int(ts), "quoi": quoi, "zone": zone, "scenario": self.scenario})
        self.invalide_barre = {"de": self.scenario, "quoi": quoi, "zone": zone, "vers": vers}
        self._bascule(i, ts, vers, cause)

    def _dans_va(self, c):
        return self.val is not None and self.vah is not None and self.val <= c <= self.vah

    # --- la barre ----------------------------------------------------------
    def barre(self, df15, i, range_ligne=None, open_type=None):
        """Avance d'une barre. `df15` peut être tronqué à i (direct) ou
        complet (rétrospectif) : seules les lignes <= i sont lues."""
        c = float(df15["close"].iloc[i])
        h, l_, ts = float(df15["high"].iloc[i]), float(df15["low"].iloc[i]), int(df15["ts"].iloc[i])
        cp = float(df15["close"].iloc[i - 1]) if i > 0 else None
        self.invalide_barre = None
        self.session_high = h if self.session_high is None else max(self.session_high, h)
        self.session_low = l_ if self.session_low is None else min(self.session_low, l_)
        if i == 0:
            self._ouverture(df15, ts)
        if i == 1 and open_type is not None and open_type.get("type"):
            self.type_ouverture = open_type["type"]
            self._ev(i, ts, "TYPE_OUVERTURE", type=open_type["type"], retour_open=open_type.get("retour_open"))
        if range_ligne is not None:
            self._ib(df15, i, ts, range_ligne)
        if self.scenario and self.scenario.startswith("S_OUV"):
            self._ouverture_hors_va(i, ts, c, cp, h, l_)
        return self.etat(i, ts, c)

    def _ouverture(self, df15, ts):
        o = float(df15["open"].iloc[0])
        if self.vah is None or self.val is None:
            self.position, self.scenario, self.depuis = None, "S_AUTRE", ts
            self._ev(0, ts, "S_AUTRE", raison="pas_de_VA")
            return
        self.position = "au_dessus" if o > self.vah else "sous" if o < self.val else "dans"
        self._ev(0, ts, "OUVRE_" + self.position.upper(), open=o)
        self.scenario = {"au_dessus": "S_OUV_HAUT_TEND", "sous": "S_OUV_BAS_TEND", "dans": "S_DANS_POSE"}[self.position]
        self.depuis = ts

    def _ib(self, df15, i, ts, r):
        if self.ib is None:
            self.ib = {"haut": r["bord_haut"], "bas": r["bord_bas"], "largeur_atr": r["largeur_atr"]}
            hors = (r["largeur_atr"] is None or r["largeur_atr"] < self.bornes[0] or r["largeur_atr"] > self.bornes[1])
            self._ev(i, ts, "IB_POSEE", haut=r["bord_haut"], bas=r["bord_bas"], largeur_atr=r["largeur_atr"],
                     hors_norme=hors)
            if self.position == "dans" and hors:
                self._bascule(i, ts, "S_AUTRE", "IB_hors_norme")
        ev = r["evenement"]
        if ev:
            self._ev(i, ts, "IB_" + ev, casse_par=r["casse_par"])
        if self.position != "dans" or self.scenario == "S_AUTRE":
            return self._ib_ouverture_hors_va(i, ts, r)
        if ev == "TRANSITION":
            vers = "S_DANS_CASSURE_HAUT" if r["casse_par"] > 0 else "S_DANS_CASSURE_BAS"
            self._invalider(i, ts, "acceptation_hors_IB", "ib_high" if r["casse_par"] > 0 else "ib_low", vers, "IB_cassee")
        elif ev == "REGAIN" and self.scenario.startswith("S_DANS_CASSURE"):
            zone = "ib_high" if self.scenario.endswith("HAUT") else "ib_low"
            self._invalider(i, ts, "regain", zone, "S_DANS_HEADFAKE", "regain_deux_clotures")
            self._valider(i, ts, "regain_deux_clotures", zone)
        elif ev == "CONTINUATION" and self.scenario.startswith("S_DANS_CASSURE"):
            self._valider(i, ts, "retest_tenu", "ib_high" if self.scenario.endswith("HAUT") else "ib_low")
        elif ev == "ETABLI" and self.scenario == "S_DANS_POSE":
            self._bascule(i, ts, "S_DANS_ROTATION", "ETABLI")
            self._valider(i, ts, "deux_tenues_par_bord", "ib")
        if self.scenario == "S_DANS_POSE" and _minutes_et(ts) >= DERNIERE_BARRE_ET:
            # « IB posee, aucune acceptation dehors jusqu'a la cloture » : validee a la
            # derniere barre cash (15h45 ET), jamais avant — POSE decrit, la cloture confirme.
            self._valider(i, ts, "aucune_acceptation_dehors_jusqu_a_la_cloture", "ib")

    def _ib_ouverture_hors_va(self, i, ts, r):
        """Sur une ouverture hors VA, l'IB est l'outil de validation de TEND."""
        if r["evenement"] != "TRANSITION":
            return
        if self.scenario == "S_OUV_HAUT_TEND" and r["casse_par"] > 0:
            self._valider(i, ts, "acceptation_au_dela_IB_high", "ib_high")
        elif self.scenario == "S_OUV_BAS_TEND" and r["casse_par"] < 0:
            self._valider(i, ts, "acceptation_sous_IB_low", "ib_low")

    def _ouverture_hors_va(self, i, ts, c, cp, h, l_):
        haut = self.position == "au_dessus"
        dedans, dedans_p = self._dans_va(c), cp is not None and self._dans_va(cp)
        r = self.reintegration
        if dedans and r["tentee_i"] is None:
            r["tentee_i"] = i
            self._ev(i, ts, "REINT_TENTEE", zone="prev_vah" if haut else "prev_val")
        if self.scenario.endswith("_TEND"):
            if dedans and dedans_p:
                r["acceptee_i"] = i
                self._ev(i, ts, "REINT_ACCEPTEE", zone="prev_vah" if haut else "prev_val")
                vers = "S_OUV_HAUT_REINT" if haut else "S_OUV_BAS_REINT"
                self._invalider(i, ts, "reintegration_acceptee", "prev_vah" if haut else "prev_val", vers, "reintegration_acceptee")
                # miroir exact (Fable, c6c12dd) : la famille REINT est validee par
                # l'acceptation, des deux cotes ; PULL / TRAV sont des precisions datees
                self._valider(i, ts, "deux_clotures_dans_la_VA", "prev_vah" if haut else "prev_val")
            return
        # réintégré : reprise (acceptation de nouveau hors VA) ?
        hors = (c > self.vah and cp is not None and cp > self.vah) if haut else (c < self.val and cp is not None and cp < self.val)
        if hors:
            self._invalider(i, ts, "acceptation_hors_VA_de_nouveau", "prev_vah" if haut else "prev_val",
                            "S_OUV_HAUT_TEND" if haut else "S_OUV_BAS_TEND", "reprise")
            self.reintegration = {"tentee_i": None, "acceptee_i": None}
            return
        self._precision(i, ts, c, cp, h, l_, haut)

    def _precision(self, i, ts, c, cp, h, l_, haut):
        """PULL ou TRAV, la première venue — miroir exact entre les deux côtés."""
        bord, oppose = (self.vah, self.val) if haut else (self.val, self.vah)
        zone_bord = "prev_vah" if haut else "prev_val"
        # pullback sur le bord franchi, TENU (tenue causale : la barre suivante clôture du bon côté)
        if self.precision is None and self.pullback is None and self._pullback_tenu(i, bord, haut):
            self.pullback = {"i": i, "extreme": self.session_low if haut else self.session_high}
            self._ev(i, ts, "PULLBACK_TENU", zone=zone_bord)
            self.precision = "PULL"
        if self.precision == "PULL" and self.pullback:
            nouveau = (c < self.pullback["extreme"]) if haut else (c > self.pullback["extreme"])
            if nouveau and not self.pullback.get("confirme"):
                self.pullback["confirme"] = True
                self._ev(i, ts, "NOUVEL_EXTREME_APRES_PULLBACK", zone=zone_bord)
        if self.precision is None and self.vpoc is not None:
            franchi = (c <= oppose + QUATRE_VINGTS * (bord - oppose)) if haut else (c >= bord + QUATRE_VINGTS * (oppose - bord))
            if franchi:
                self._ev(i, ts, "QUATRE_VINGTS_FRANCHI", zone="prev_val" if haut else "prev_vah")
                self.precision = "TRAV"
        if self.precision == "TRAV" and self.vpoc is not None and cp is not None:
            if (c < self.vpoc if haut else c > self.vpoc):
                self.vu_vpoc = True
            rejet = self.vu_vpoc and ((c > self.vpoc and cp > self.vpoc) if haut else (c < self.vpoc and cp < self.vpoc))
            if rejet:
                self._invalider(i, ts, "rejet_au_VPOC_accepte", "prev_vpoc", "S_AUTRE", "rejet_vpoc")

    def _pullback_tenu(self, i, bord, haut):
        """Le pullback : à la barre i-1 le prix est revenu sur le bord franchi
        (la barre l'englobe), et la barre i clôture du côté de la
        réintégration — connu à i, rien avant."""
        z = next((z for z in self.zones if z["nom"] == ("prev_vah" if haut else "prev_val")), None)
        if z is None or i < 1:
            return False
        f = z["fiche"]
        if f.get("dernier_test_i") != i - 1 or f.get("dernier_tenu") is not True:
            return False
        cote = f.get("dernier_cote")
        return (cote > 0) if haut else (cote < 0)   # testé par le dessous (haut) / par le dessus (bas)

    # --- l'état journalisé --------------------------------------------------
    def etat(self, i, ts, close):
        code = self.scenario
        roles = ROLES.get(code, {})
        for z in self.zones:
            z["role"] = roles.get(z["nom"], "neutre")
        hors = [{"setup": "%s@%s" % (s, z), "raison": r} for s, z, r in HORS_SCENARIO.get(code, [])]
        inv = getattr(self, "invalide_barre", None)
        etat_sc = "invalide" if inv else "valide" if self.valide_a is not None else "en_cours"
        nom = code + (" [%s]" % self.precision if self.precision else "")
        if inv:
            titre = "%s (invalide %s : %s) -> %s" % (inv["de"], _hhmm(ts), inv["quoi"], nom)
        elif self.valide_a is not None:
            titre = "%s (valide %s)" % (nom, _hhmm(self.validations[-1]["ts"]) if self.validations else "?")
        else:
            titre = "%s (en cours, non valide)" % nom
        return {"i": i, "ts": ts, "position_ouverture": self.position, "type_ouverture": self.type_ouverture,
                "scenario_en_cours": code, "precision": self.precision, "scenario_depuis": self.depuis,
                "etat_scenario": etat_sc, "titre": titre, "arme": etat_sc == "valide", "invalide": inv,
                "valide": self.valide_a is not None, "valide_a_i": self.valide_a,
                "ib": self.ib, "session_high": self.session_high, "session_low": self.session_low,
                "sequence_etats": list(self.sequence), "validations": list(self.validations),
                "invalidations": list(self.invalidations), "bascules": list(self.bascules),
                "reintegration": dict(self.reintegration), "ce_qui_ne_se_trade_pas": hors,
                "confiance": None}
