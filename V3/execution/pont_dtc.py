"""LE PONT VERS LE CONNECTEUR QUI TOURNE — conventions, chemin, instanciation.

Un seul endroit traduit entre le vocabulaire de V3 et celui de DTC. Deux
endroits divergeraient, et la divergence serait silencieuse : c'est exactement
ce qui s'est passe le 14/09, et ce module existe pour que ca ne recommence pas.

LE CONNECTEUR VIVANT EST `BOT/dtc_connector.py` — trois ordres Type 208 separes
et OCO gere a la main. PAS `V1_ARCHIVE/sierra_dtc_connector.py`, dont le bracket
(`SUBMIT_NEW_OCO_ORDER` 206, `IsParentOrder`, `ParentTriggerClientOrderID`) a
ete teste et REJETE le 02/04 : Sierra Chart en serveur DTC l'ignore
SILENCIEUSEMENT. Et `BOT/` porte en plus le fix du 04/05 que V1 n'a pas : la paire OCO est
enregistree AVANT l'envoi des enfants. Un TP rempli en 596 ms sur NQ arrivait
avant l'enregistrement, l'annulation du jumeau echouait sans un mot, et l'ordre
restait orphelin en seance. `BOT/` n'est pas seulement le bon code, c'est celui
qui a le PLUS de lecons (detail dans `V3/DECISIONS.md`).

On IMPORTE ce connecteur, on ne le recopie jamais.
"""
from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

# Les valeurs viennent du connecteur qui TOURNE (`BOT/dtc_connector.py`,
# `BUY = 1` / `SELL = 2`), jamais d'une supposition. Elles sont redeclarees ici
# pour que les tests n'aient pas besoin des dependances de `BOT/` — et
# `test_pont_dtc` interdit qu'elles divergent de la source.
BUY_DTC, SELL_DTC = 1, 2


def buysell(side):
    """Traduit le cote V3 (+1 / -1) en `BuySell` DTC (1 / 2).

    LE PIEGE EST VICIEUX, et c'est pour ca qu'il a survecu : **+1 vaut « long »
    en V3 ET « BUY » en DTC**. Le LONG passe donc par accident, et seul le
    SHORT casse — un defaut cache derriere la moitie des cas qui marchent.

    MESURE DU 14/09, avant correction : `exec_sim` passait `intent["side"]`
    TEL QUEL au connecteur, et `intentions._parse_snapshot` rend +1 / -1. Donc
    `BuySell = -1` partait sur **tout SHORT a l'entree et toute sortie de
    LONG**. Sierra en serveur DTC **ignore silencieusement** ce qu'il ne
    comprend pas (verifie le 02/04 sur OCOGroup1, Type 206, IsParentOrder et le
    cancel sans ServerOrderID) : pas de refus, pas de log, rien.

    Meme famille que le signe de `dist_vwap_w` trouve le matin meme — une
    convention non verifiee — sauf qu'ici une inversion n'etiquette pas mal un
    journal : elle envoie le mauvais cote au broker.

    Fail-loud sur tout le reste : un cote qui n'est ni +1 ni -1 est une erreur
    de programmation, pas une donnee de marche. On ne devine pas.
    """
    if side == 1:
        return BUY_DTC
    if side == -1:
        return SELL_DTC
    raise ValueError("cote V3 attendu +1 ou -1, recu %r" % (side,))


def preparer_chemin():
    """`BOT/` A LA FIN de `sys.path`, jamais au debut. Mesure du 14/09.

    `from BOT.dtc_connector import DTCConnector` ECHOUAIT :
    `ModuleNotFoundError: No module named 'bot_config'`. Le connecteur fait un
    import FRERE (`import bot_config`) qui n'existe que si `BOT/` est lui-meme
    sur le chemin — la racine seule ne suffit pas.

    Et c'etait INVISIBLE POUR TOUTE LA SUITE : l'import est tardif, et les
    tests injectent un faux connecteur. EXEC aurait plante au premier tour
    reel, pas avant.

    A LA FIN, et c'est le point : l'incident du 17/05 (`DEPLOY_UNSAFE`) a coute
    une heure de debug parce qu'un fichier faisait `insert(0, ROOT/"CORE")`
    puis `insert(0, ROOT/"BOT")` — `BOT/` passait devant et masquait un module
    de `CORE/` par une version vieille de cinq jours. En ajoutant a la FIN,
    `BOT/` ne peut masquer personne.
    """
    chemin = os.path.join(RACINE, "BOT")
    if chemin not in sys.path:
        sys.path.append(chemin)
    return chemin


def connecteur():
    """Le connecteur vivant, instancie. L'import est TARDIF : les tests
    injectent un faux et n'ont donc aucune dependance vers `BOT/`."""
    preparer_chemin()
    from BOT.dtc_connector import DTCConnector      # noqa: E402 — import tardif voulu
    return DTCConnector()


def constantes_de_la_source():
    """Rend `(BUY, SELL)` lus DANS le connecteur vivant, ou `None` s'il n'est
    pas importable. Sert au controle de non-divergence — une copie qui derive
    en silence est le defaut que ce module existe pour empecher."""
    preparer_chemin()
    try:
        from BOT.dtc_connector import BUY, SELL     # noqa: E402
    except Exception:                               # noqa: BLE001
        return None
    return (BUY, SELL)
