"""SCÉNARIOS — L'ÉCRIVAIN (A1) : un processus, sans écran, qui recalcule la
journée entière à chaque barre 15 min complète et écrit UNE ligne par barre et
par instrument dans `LOGS/scenarios/direct_<jour>.jsonl`.

    python -X utf8 V3/scenarios/boucle.py            # boucle, Ctrl-C pour arrêter
    python -X utf8 V3/scenarios/boucle.py --un-tour  # un seul tour (tests, tâche)

Ce qu'il fait, toutes les CYCLE_S secondes :
  1. bat le cœur : `LOGS/heartbeat_scenarios.json` (quand_utc, jour, dernière
     barre écrite par instrument, env, grammaire_version) — même sans barre ;
  2. avant 9h30 ET, férié CME, week-end : dort ; après 16h15 ET : un passage de
     RATTRAPAGE des barres complètes non écrites (écrivain relancé tard), puis dort ;
  3. sinon, par instrument : les barres 15 min COMPLÈTES (la barre en cours
     n'existe pas), par le MÊME chemin que le rejeu (`scenarios.charger`) ;
     si la dernière n'est pas encore écrite → `derouler` sur la journée depuis
     9h30 (1-2 s, aucun état à maintenir) et les lignes manquantes sont
     ajoutées, idempotentes par (sym, ts).
Il n'écrit JAMAIS `scenarios_<jour>.jsonl` (réservé au rejeu du soir) : c'est
la paire que 5b/5 compare. Le garde (`execution/garde_scenarios.py`, toutes
les 5 min) le relance si le cœur s'arrête — un écrivain qui meurt à 11h n'est
relancé par personne, la leçon du 07/09.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import recalc                                # noqa: E402
from V3 import calendrier                                       # noqa: E402
from V3.scenarios import grammaire, scenarios                   # noqa: E402

CYCLE_S = 30
CASH_DE, CASH_A = 570, 16 * 60 + 15          # 9h30 ET ; 16h15 ET (la barre 15h45 est complète à 16h00)
HEARTBEAT = os.path.join(RACINE, "LOGS", "heartbeat_scenarios.json")


def maintenant_et():
    """(jour ET 'YYYYMMDD', minutes ET) — l'heure de l'Est, EDT / EST par `recalc`."""
    now = pd.Timestamp.now(tz="UTC")
    m = int(recalc.minutes_et(pd.Series([now])).iloc[0])
    dec = 240 if recalc._est_edt(now) else 300
    return (now - pd.Timedelta(minutes=dec)).strftime("%Y%m%d"), m


def battre_coeur(jour, dernieres, motif=None):
    d = {"quand_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jour": jour,
         "derniere_barre": dernieres, "motif": motif, "grammaire_version": grammaire.GRAMMAIRE_VERSION,
         "env": {"python": platform.python_version(), "pandas": pd.__version__, "exe": sys.executable}}
    os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
    with open(HEARTBEAT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(HEARTBEAT + ".tmp", HEARTBEAT)


def dernieres_ecrites(jour):
    out = {}
    for l in scenarios.lire(scenarios.chemin_direct(jour)):
        out[l["sym"]] = max(out.get(l["sym"], 0), int(l["ts"]))
    return out


def ecrire_nouvelles(jour, sym, lignes, deja):
    """Ajoute au journal direct les lignes de `sym` dont le ts n'y est pas —
    idempotent par (sym, ts), un écrivain, `.tmp` + `os.replace`."""
    vus = {(l["sym"], int(l["ts"])) for l in deja}
    neuves = [dict(l, mode="direct", ecrit_a=int(time.time() * 1000)) for l in lignes
              if (l["sym"], int(l["ts"])) not in vus]
    if neuves:
        scenarios.ecrire(scenarios.chemin_direct(jour), deja + neuves)
    return neuves


def un_tour(jour=None, minutes=None):
    """Un tour de boucle. Rend (motif, {sym: nb lignes écrites})."""
    j, m = maintenant_et()
    jour, minutes = jour or j, m if minutes is None else minutes
    dernieres = dernieres_ecrites(jour)
    if pd.Timestamp(jour).dayofweek >= 5:
        battre_coeur(jour, dernieres, "week_end")
        return "week_end", {}
    if calendrier.est_ferie(jour):
        battre_coeur(jour, dernieres, "ferie")
        return "ferie", {}
    if minutes < CASH_DE:
        battre_coeur(jour, dernieres, "hors_cash")
        return "hors_cash", {}
    # apres la cloture : un ecrivain relance a 17h RATTRAPE les barres completes qu'il
    # n'a pas ecrites (un seul passage utile, puis il dort) — jamais avant 9h30
    motif = "cash" if minutes <= CASH_A else "rattrapage"
    ecrits = {}
    for sym in ("ES", "NQ"):
        df, brut = scenarios.charger(sym, jour, completes_seulement=True)
        if df.empty:
            continue
        dernier = int(df["ts"].iloc[-1])
        if dernier <= dernieres.get(sym, 0):
            continue                                  # rien de neuf : pas un recalcul
        lignes = scenarios.derouler(df, brut, sym)
        neuves = ecrire_nouvelles(jour, sym, lignes, scenarios.lire(scenarios.chemin_direct(jour)))
        ecrits[sym] = len(neuves)
        dernieres[sym] = dernier
    battre_coeur(jour, dernieres, motif if ecrits or motif == "cash" else "hors_cash")
    return (motif if ecrits or motif == "cash" else "hors_cash"), ecrits


def main(argv):
    os.chdir(RACINE)
    if "--un-tour" in argv:
        motif, ecrits = un_tour()
        print("tour : %s %s" % (motif, ecrits))
        return 0
    print("ecrivain scenarios : boucle toutes les %d s (Ctrl-C pour arreter)" % CYCLE_S, flush=True)
    while True:
        debut = time.time()
        try:
            motif, ecrits = un_tour()
            if ecrits:
                print("%s %s" % (datetime.now().strftime("%H:%M:%S"), ecrits), flush=True)
        except Exception as e:                        # noqa: BLE001 — un tour rate ne tue pas l'ecrivain
            print("tour en erreur : %s: %s" % (type(e).__name__, e), flush=True)
        time.sleep(max(1.0, CYCLE_S - (time.time() - debut)))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
