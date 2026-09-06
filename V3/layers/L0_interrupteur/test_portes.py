"""Deux tests par porte — une barre qui passe, une barre qui bloque — plus le
controle « rien de cache ».

    python -X utf8 V3/layers/L0_interrupteur/test_portes.py

Le controle « rien de cache » va dans les DEUX SENS : il echoue si une porte du
code n'a pas de ligne dans `seuils.yaml`, ET si une ligne du YAML n'a pas de
porte dans le code. C'est la seule protection contre la derive silencieuse —
V1 embarquait 27 modules dont personne ne savait ce que chacun filtrait.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3 import registre                                       # noqa: E402
from V3.layers.L0_interrupteur import portes                  # noqa: E402
from V3.layers.L5_risque import vetos                         # noqa: E402,F401

SEUILS, APPLIQUEES, ABSENTES = portes.charger_seuils()

BARRE = {"ts": 1_757_000_000_000, "sym": "ES", "i": 100, "minute_utc": 14 * 60,
         "jour": "20260903", "news_60m": False, "session_bloquee": False,
         "vix_regime": 1.0, "gamma_block_long": False, "rvol_zscore": 0.4,
         "atr5": 3.0}
ETAT = {"n_jour": 0, "pnl_jour": 0.0, "fin_cooldown": -1, "libre_a": -1,
        "side_ouvert": 0, "i_entree": -1, "issue_ouverte": None}

# (porte, ce qui change dans la barre, ce qui change dans l'etat, doit bloquer)
CAS = [
    ("L0_NEWS", {"news_60m": True}, {}, True),
    ("L0_NEWS", {}, {}, False),
    ("L0_SESSION_BLOQUEE", {"session_bloquee": True}, {}, True),
    ("L0_SESSION_BLOQUEE", {}, {}, False),
    ("L0_EOD_LOCKOUT", {"minute_utc": 19 * 60 + 55}, {}, True),
    ("L0_EOD_LOCKOUT", {"minute_utc": 19 * 60 + 45}, {}, False),
    ("L0_VIX_REGIME", {"vix_regime": 2.0}, {}, True),
    ("L0_VIX_REGIME", {"vix_regime": 1.0}, {}, False),
    ("L0_MAX_TRADES_JOUR", {}, {"n_jour": 5}, True),
    ("L0_MAX_TRADES_JOUR", {}, {"n_jour": 4}, False),
    ("L0_STOP_JOURNALIER", {}, {"pnl_jour": -1000.0}, True),
    ("L0_STOP_JOURNALIER", {}, {"pnl_jour": -999.0}, False),
    ("L0_STOP_PROPFIRM", {}, {"pnl_jour": -250.0}, True),
    ("L0_STOP_PROPFIRM", {}, {"pnl_jour": -100.0}, False),
    ("L0_COOLDOWN", {}, {"fin_cooldown": 1_757_000_000_001}, True),
    ("L0_COOLDOWN", {}, {"fin_cooldown": 1_756_000_000_000}, False),
    ("L0_POSITION_OUVERTE", {}, {"libre_a": 105}, True),
    ("L0_POSITION_OUVERTE", {}, {"libre_a": 99}, False),
    ("L5_VETO_GAMMA", {"gamma_block_long": True}, {}, True),
    ("L5_VETO_GAMMA", {}, {}, False),
    ("L5_VETO_RVOL_EXTREME", {"rvol_zscore": -3.4}, {}, True),
    ("L5_VETO_RVOL_EXTREME", {"rvol_zscore": 2.9}, {}, False),
    # MES : 4,32 $ / (1,5 x 0,5 pt x 5 $) = 115 % > 10 % -> bloque
    ("L5_FRAIS_TROP_LOURDS", {"atr5": 0.5}, {}, True),
    # MES : 4,32 $ / (1,5 x 8 pts x 5 $) = 7,2 % < 10 % -> passe
    ("L5_FRAIS_TROP_LOURDS", {"atr5": 8.0}, {}, False),
]


def _un_cas(nom, dbarre, detat, attendu):
    lec = dict(BARRE, **dbarre)
    etat = dict(ETAT, **detat)
    obtenu = bool(registre.REGISTRE[nom]["fn"](lec, etat, SEUILS.get(nom, {})))
    if obtenu != attendu:
        return ("%s : attendu %s, obtenu %s (barre %s, etat %s)"
                % (nom, attendu, obtenu, dbarre or "nominale", detat or "neuf"))
    return None


def rien_de_cache():
    """Le registre du code == les portes du YAML, dans les deux sens."""
    code, yaml_ = set(registre.REGISTRE), set(SEUILS)
    e = []
    for n in sorted(code - yaml_):
        e.append("%s : porte dans le code, aucune ligne dans seuils.yaml" % n)
    for n in sorted(yaml_ - code):
        e.append("%s : declaree dans seuils.yaml, aucune porte dans le code" % n)
    return e


def couverture():
    """Chaque porte a-t-elle SES DEUX cas — une qui passe, une qui bloque ?"""
    vus = {}
    for nom, _b, _e, attendu in CAS:
        vus.setdefault(nom, set()).add(attendu)
    return ["%s : %d cas sur 2 — il manque « une barre qui %s »"
            % (n, len(vus.get(n, ())), "bloque" if True not in vus.get(n, ()) else "passe")
            for n in sorted(registre.REGISTRE) if len(vus.get(n, ())) < 2]


def main():
    echecs = rien_de_cache() + couverture()
    echecs += [m for m in (_un_cas(*c) for c in CAS) if m]
    print("  L0 + L5 — %d portes, %d cas" % (len(registre.REGISTRE), len(CAS)))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : rien de cache, chaque porte a sa barre qui passe et sa barre "
          "qui bloque.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
