"""Deux tests par porte — une barre qui passe, une barre qui bloque — plus le
controle « rien de cache ».

    python -X utf8 V3/layers/L0_interrupteur/test_portes.py

Le controle « rien de cache » va dans les DEUX SENS : il echoue si une porte du
code n'a pas de ligne dans `seuils.yaml`, ET si une ligne du YAML n'a pas de
porte dans le code. C'est la seule protection contre la derive silencieuse —
V1 embarquait 27 modules dont personne ne savait ce que chacun filtrait.

Les portes de la famille A ont un TROISIEME cas : la donnee absente. Elles
doivent rendre `None` — « je ne peux pas repondre » — et surtout pas `False`.
Un feu vert invente sur une information manquante est le silent fallback qui a
deja coute deux regressions au chantier.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3 import registre                                       # noqa: E402
from V3.layers.L0_interrupteur import portes                  # noqa: E402
from V3.layers.L0_interrupteur import portes_donnees          # noqa: E402,F401
from V3.layers.L5_risque import vetos                         # noqa: E402,F401

SEUILS, APPLIQUEES, ABSENTES = portes.charger_seuils()

# Une barre nominale : tout va bien, aucune porte ne doit fermer.
BARRE = {
    "ts": 1_757_000_000_000, "sym": "ES", "i": 100, "minute_utc": 14 * 60,
    "jour": "20260903", "rang_du_jour": 20,
    "qualite": "stable", "fenetre_melangee": False, "barre_complete": True,
    "age_s": 12.0, "l6_alerte": False, "colonnes_mortes": False,
    "news_60m": False, "session_bloquee": False, "ferie": None,
    "rollover": False, "vix_regime": 1.0, "dist_hvl_atr": 2.4,
    "dtc_connecte": True, "contrat_actif": True,
    "gamma_block_long": False, "rvol_zscore": 0.4, "atr_barre": 15.0,
}
ETAT = {"n_jour": 0, "n_signaux_jour": 0, "pnl_jour": 0.0, "fin_cooldown": -1,
        "libre_a": -1, "side_ouvert": 0, "i_entree": -1, "issue_ouverte": None}

# (porte, ce qui change dans la barre, ce qui change dans l'etat, attendu)
CAS = [
    # --- famille A : la donnee est-elle vraie ? -------------------------
    ("L0_DATA_INSTABLE", {"qualite": "warmup"}, {}, True),
    ("L0_DATA_INSTABLE", {}, {}, False),
    ("L0_DATA_INSTABLE", {"qualite": None}, {}, None),
    ("L0_DATA_PERIMEE", {"age_s": 120.0}, {}, True),
    ("L0_DATA_PERIMEE", {"age_s": 30.0}, {}, False),
    ("L0_DATA_PERIMEE", {"age_s": None}, {}, None),
    ("L0_DATA_INCOMPLETE", {"barre_complete": False}, {}, True),
    ("L0_DATA_INCOMPLETE", {}, {}, False),
    ("L0_DATA_INCOMPLETE", {"barre_complete": None}, {}, None),
    ("L0_DATA_FENETRE_MELANGEE", {"fenetre_melangee": True}, {}, True),
    ("L0_DATA_FENETRE_MELANGEE", {}, {}, False),
    ("L0_DATA_FENETRE_MELANGEE", {"fenetre_melangee": None}, {}, None),
    ("L0_DATA_L6_ALERTE", {"l6_alerte": True}, {}, True),
    ("L0_DATA_L6_ALERTE", {}, {}, False),
    ("L0_DATA_L6_ALERTE", {"l6_alerte": None}, {}, None),
    ("L0_DATA_COLONNE_MORTE", {"colonnes_mortes": True}, {}, True),
    ("L0_DATA_COLONNE_MORTE", {}, {}, False),
    ("L0_DATA_COLONNE_MORTE", {"colonnes_mortes": None}, {}, None),
    # --- famille B : est-ce un moment ou decider ? ----------------------
    ("L0_NEWS", {"news_60m": True}, {}, True),
    ("L0_NEWS", {}, {}, False),
    ("L0_SESSION_BLOQUEE", {"session_bloquee": True}, {}, True),
    ("L0_SESSION_BLOQUEE", {}, {}, False),
    ("L0_FERIE_CME", {"ferie": "Labor Day"}, {}, True),
    ("L0_FERIE_CME", {}, {}, False),
    ("L0_ROLLOVER", {"rollover": True}, {}, True),
    ("L0_ROLLOVER", {}, {}, False),
    ("L0_ROLLOVER", {"rollover": None}, {}, None),
    ("L0_PREMIERE_BARRE", {"rang_du_jour": 2}, {}, True),
    ("L0_PREMIERE_BARRE", {"rang_du_jour": 8}, {}, False),
    ("L0_EOD_LOCKOUT", {"minute_utc": 19 * 60 + 55}, {}, True),
    ("L0_EOD_LOCKOUT", {"minute_utc": 19 * 60 + 45}, {}, False),
    # --- famille C : le marche est-il tradable ? ------------------------
    ("L0_VIX_REGIME", {"vix_regime": 2.0}, {}, True),
    ("L0_VIX_REGIME", {"vix_regime": 1.0}, {}, False),
    ("L0_REGIME_INDETERMINE", {"dist_hvl_atr": 0.3}, {}, True),
    ("L0_REGIME_INDETERMINE", {"dist_hvl_atr": -2.0}, {}, False),
    ("L0_REGIME_INDETERMINE", {"dist_hvl_atr": None}, {}, None),
    # --- famille D : ai-je encore le droit de perdre ? ------------------
    ("L0_MAX_TRADES_PRIS", {}, {"n_jour": 5}, True),
    ("L0_MAX_TRADES_PRIS", {}, {"n_jour": 4}, False),
    ("L0_RANG_DU_SIGNAL", {}, {"n_signaux_jour": 12}, True),
    ("L0_RANG_DU_SIGNAL", {}, {"n_signaux_jour": 11}, False),
    ("L0_STOP_JOURNALIER", {}, {"pnl_jour": -1000.0}, True),
    ("L0_STOP_JOURNALIER", {}, {"pnl_jour": -999.0}, False),
    ("L0_STOP_PROPFIRM", {}, {"pnl_jour": -250.0}, True),
    ("L0_STOP_PROPFIRM", {}, {"pnl_jour": -100.0}, False),
    ("L0_COOLDOWN", {}, {"fin_cooldown": 1_757_000_000_001}, True),
    ("L0_COOLDOWN", {}, {"fin_cooldown": 1_756_000_000_000}, False),
    # --- famille E : puis-je passer l'ordre ? ---------------------------
    ("L0_POSITION_OUVERTE", {}, {"libre_a": 105}, True),
    ("L0_POSITION_OUVERTE", {}, {"libre_a": 99}, False),
    ("L0_CONTRAT_INACTIF", {"contrat_actif": False}, {}, True),
    ("L0_CONTRAT_INACTIF", {}, {}, False),
    ("L0_CONTRAT_INACTIF", {"contrat_actif": None}, {}, None),
    ("L0_DTC_DECONNECTE", {"dtc_connecte": False}, {}, True),
    ("L0_DTC_DECONNECTE", {}, {}, False),
    ("L0_DTC_DECONNECTE", {"dtc_connecte": None}, {}, None),
    # --- L5 : combien, et ou est le stop ? ------------------------------
    ("L5_VETO_GAMMA", {"gamma_block_long": True}, {}, True),
    ("L5_VETO_GAMMA", {}, {}, False),
    ("L5_VETO_RVOL_EXTREME", {"rvol_zscore": -3.4}, {}, True),
    ("L5_VETO_RVOL_EXTREME", {"rvol_zscore": 2.9}, {}, False),
    # MES : 4,32 / (1,5 x 0,5 pt x 5 $) = 115 % > 10 % -> bloque
    ("L5_FRAIS_TROP_LOURDS", {"atr_barre": 0.5}, {}, True),
    # MES : 4,32 / (1,5 x 15,11 pts x 5 $) = 3,8 % -> passe (ATR median mesure)
    ("L5_FRAIS_TROP_LOURDS", {"atr_barre": 15.11}, {}, False),
]


def _un_cas(nom, dbarre, detat, attendu):
    lec = dict(BARRE, **dbarre)
    etat = dict(ETAT, **detat)
    r = registre.REGISTRE[nom]["fn"](lec, etat, SEUILS.get(nom, {}))
    obtenu = None if r is None else bool(r)
    if obtenu is not attendu:
        return ("%s : attendu %s, obtenu %s (barre %s, etat %s)"
                % (nom, attendu, obtenu, dbarre or "nominale", detat or "neuf"))
    return None


def rien_de_cache():
    """Le registre du code == les portes du YAML, dans les deux sens."""
    code, yaml_ = set(registre.REGISTRE), set(SEUILS)
    e = ["%s : porte dans le code, aucune ligne dans seuils.yaml" % n
         for n in sorted(code - yaml_)]
    e += ["%s : declaree dans seuils.yaml, aucune porte dans le code" % n
          for n in sorted(yaml_ - code)]
    return e


def couverture():
    """Chaque porte a-t-elle SES DEUX cas — une qui passe, une qui bloque ?"""
    vus = {}
    for nom, _b, _e, attendu in CAS:
        vus.setdefault(nom, set()).add(attendu)
    manque = []
    for n in sorted(registre.REGISTRE):
        v = vus.get(n, set())
        if True not in v:
            manque.append("%s : il manque une barre qui BLOQUE" % n)
        if False not in v:
            manque.append("%s : il manque une barre qui PASSE" % n)
    return manque


def pas_de_feu_vert_invente():
    """Une porte qui lit une donnee absente doit rendre None, jamais False.

    Ce controle vise le silent fallback : repondre « tout va bien » quand on ne
    sait pas. Il ne s'applique qu'aux portes dont un cas `None` est declare —
    les autres lisent des grandeurs qui existent toujours.
    """
    attendus = {n for n, _b, _e, a in CAS if a is None}
    e = []
    for n in sorted(attendus):
        cas = [(b, et) for nom, b, et, a in CAS if nom == n and a is None]
        for b, et in cas:
            r = registre.REGISTRE[n]["fn"](dict(BARRE, **b), dict(ETAT, **et),
                                           SEUILS.get(n, {}))
            if r is not None:
                e.append("%s : donnee absente -> a repondu %r au lieu de None"
                         % (n, r))
    return e


def main():
    echecs = rien_de_cache() + couverture() + pas_de_feu_vert_invente()
    echecs += [m for m in (_un_cas(*c) for c in CAS) if m]
    trous = len({n for n, _b, _e, a in CAS if a is None})
    print("  L0 + L5 — %d portes, %d cas dont %d portes testees sur donnee "
          "absente" % (len(registre.REGISTRE), len(CAS), trous))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : rien de cache, chaque porte a sa barre qui passe et sa barre "
          "qui bloque,\n       et aucune ne repond « tout va bien » sur une "
          "donnee absente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
