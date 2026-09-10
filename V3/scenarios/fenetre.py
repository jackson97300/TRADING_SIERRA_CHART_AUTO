"""SCÉNARIOS — LA FENÊTRE ÉPINGLÉE (A3) : `pywebview`, native, always-on-top,
qui affiche LE MÊME HTML que la vitrine (http://localhost:<port>). Un onglet de
navigateur disparaît derrière Sierra ; un copilote qu'on doit aller chercher
n'est plus dans le champ de vision.

    python -X utf8 V3/scenarios/fenetre.py

Aucune logique ici. Position mémorisée dans `LOGS/scenarios/vitrine_position.json`.
Si le serveur est absent : une page « vitrine absente », jamais un crash. Les
boutons (muet, NOTER) sont ceux de la page.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

POSITION = os.path.join(RACINE, "LOGS", "scenarios", "vitrine_position.json")
DEFAUT = {"x": 40, "y": 40, "largeur": 380, "hauteur": 260}
ABSENTE = ("<html><body style='background:#111;color:#888;font:13px Consolas;padding:12px'>"
           "vitrine absente — lancer <code>python -X utf8 V3/scenarios/vitrine.py</code>, puis relancer la fenêtre."
           "</body></html>")


def lire_position():
    try:
        d = json.load(open(POSITION, encoding="utf-8"))
        return {k: int(d.get(k, DEFAUT[k])) for k in DEFAUT}
    except (OSError, ValueError, TypeError):
        return dict(DEFAUT)


def ecrire_position(pos):
    os.makedirs(os.path.dirname(POSITION), exist_ok=True)
    with open(POSITION + ".tmp", "w", encoding="utf-8") as f:
        json.dump({k: int(pos[k]) for k in DEFAUT}, f)
    os.replace(POSITION + ".tmp", POSITION)
    return POSITION


def serveur_present(url, delai=1.5):
    try:
        with urllib.request.urlopen(url, timeout=delai) as r:
            return r.status == 200
    except Exception:                                 # noqa: BLE001 — absent = absent
        return False


def main():
    from V3.scenarios import boucle, lot, noter
    port = lot.seuils()["vitrine"]["port"]
    # la fenetre a tourne ce jour : les clics ne sont plus independants de la
    # machine — `scenarios_visibles : oui` dans le journal manuel (A6)
    try:
        noter.marquer_visibles(boucle.maintenant_et()[0], True)
    except OSError as e:
        print("scenarios_visibles non pose : %s" % e)
    url = "http://localhost:%d/" % port
    try:
        import webview
    except ImportError:
        print("pywebview absent : python -m pip install pywebview")
        return 2
    pos = lire_position()
    if serveur_present(url):
        w = webview.create_window("Narrateur de séance", url, x=pos["x"], y=pos["y"],
                                  width=pos["largeur"], height=pos["hauteur"], on_top=True)
    else:
        w = webview.create_window("Narrateur de séance", html=ABSENTE, x=pos["x"], y=pos["y"],
                                  width=pos["largeur"], height=pos["hauteur"], on_top=True)

    def memoriser():
        try:
            ecrire_position({"x": w.x, "y": w.y, "largeur": w.width, "hauteur": w.height})
        except Exception:                             # noqa: BLE001 — la position est un confort
            pass
    w.events.closing += memoriser
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
