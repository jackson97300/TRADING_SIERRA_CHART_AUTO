"""L'ÉTAT LIVE — le dict que `chaine.appliquer(strict=True, live=...)` consomme.

Chaque clé est sourcée, chaque inconnue est laissée en TROU (None) — jamais
inventée. D'où vient chaque clé :

  age_s            maintenant − ts de la dernière barre 1 min du fichier.
                   Inclut le retard de sync : c'est l'âge de ce que la
                   décision LIRAIT, pas celui du feed côté VPS.
  l6_alerte        la dernière `LOGS/surveillance/surveillance_*.jsonl`
                   fraîche (≤ 4 jours calendaires : week-end + férié).
                   Plus vieille ou absente → None, le trou bloque.
                   NUANCE : verdict GLOBAL — une alerte NQ bloque aussi ES.
                   Sur-blocage conservateur, assumé pour la preuve live.
  rollover         contrat du fichier du jour ≠ contrat du jour précédent.
                   L'un des deux illisible → None.
  contrat_actif    contrat du fichier ∈ contrats attendus (campagne.py).
  colonnes_mortes  None — AUCUNE source quotidienne aujourd'hui (stale.csv
                   est un rapport historique, L6 ne le produit pas par jour).
                   Trou VOULU : il bloque, et c'est écrit plutôt qu'inventé.
  dtc_connecte     None — le pont DTC vient plus tard cette semaine. Trou
                   VOULU, même raison.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
import sys                                                        # noqa: E402
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.campagne import contrat_ok, jours_disponibles             # noqa: E402

FRAICHEUR_L6_JOURS = 4   # J-1 en semaine, J-3 apres un week-end + ferie


def _contrat(sym, jour):
    """Le contrat écrit dans le fichier — lu, jamais supposé."""
    fs = sorted(glob.glob("DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)))
    if not fs:
        return None
    for ln in open(fs[0], encoding="utf-8", errors="ignore"):
        if ln[:1] == "{":
            try:
                return str(json.loads(ln).get("contract") or "") or None
            except ValueError:
                continue
    return None


def etat_l6(jour):
    """Le verdict de la dernière surveillance FRAÎCHE, ou None (trou).

    Pendant la journée J, la surveillance disponible est celle de J-1 (elle
    tourne à 21:01) : on accepte jusqu'à `FRAICHEUR_L6_JOURS` de retard, et
    au-delà on ne sait pas — on ne devine pas."""
    fichiers = sorted(glob.glob("LOGS/surveillance/surveillance_*.jsonl"))
    if not fichiers:
        return None
    date_f = os.path.basename(fichiers[-1])[len("surveillance_"):-len(".jsonl")]
    try:
        ecart = (datetime.strptime(jour, "%Y%m%d")
                 - datetime.strptime(date_f, "%Y%m%d")).days
    except ValueError:
        return None
    if not (0 <= ecart <= FRAICHEUR_L6_JOURS):
        return None
    for ln in open(fichiers[-1], encoding="utf-8"):
        ln = ln.strip()
        if ln and json.loads(ln).get("etat") == "ALERTE":
            return True
    return False


def etat_live(sym, jour, brut_1min):
    """Le dict `live` complet — cf le docstring du module pour chaque clé."""
    age = None
    if len(brut_1min):
        age = (datetime.now(timezone.utc).timestamp()
               - int(brut_1min["ts"].max()) / 1000.0)
    contrat = _contrat(sym, jour)
    precedent = ([j for j in jours_disponibles(sym) if j < jour] or [None])[-1]
    contrat_veille = _contrat(sym, precedent) if precedent else None
    rollover = (None if not contrat or not contrat_veille
                else contrat != contrat_veille)
    return {
        "age_s": age,
        "l6_alerte": etat_l6(jour),
        "colonnes_mortes": None,          # pas de source quotidienne — trou voulu
        "rollover": rollover,
        "contrat_actif": contrat_ok(sym, jour),
        "dtc_connecte": None,             # pont DTC plus tard — trou voulu
    }
