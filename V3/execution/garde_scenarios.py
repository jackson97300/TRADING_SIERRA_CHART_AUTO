"""Le GARDE de l'écrivain SCÉNARIOS — relance `scenarios/boucle.py` si son
battement de cœur s'arrête (copie du garde du coureur : la leçon du 07/09).

    python -X utf8 V3/execution/garde_scenarios.py

Lancé par le planificateur TOUTES LES 5 MINUTES :
    schtasks /create /tn "V3 garde scenarios" /sc minute /mo 5
             /tr "<racine du dépôt>\\V3\\execution\\garde_scenarios.bat"
Si `LOGS/heartbeat_scenarios.json` est absent, illisible ou vieux de plus de
MAX_AGE_S, il tue tout `scenarios/boucle` encore accroché puis en relance un,
détaché, console dans `LOGS/scenarios_console.log`. Backoff : trois relances
en quinze minutes → il n'insiste pas et l'écrit (un écrivain qui meurt trois
fois de suite a une raison, la relance ne la soigne pas).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
HEARTBEAT = os.path.join(RACINE, "LOGS", "heartbeat_scenarios.json")
RELANCES = os.path.join(RACINE, "LOGS", "garde_scenarios_relances.json")
MAX_AGE_S = 300
BACKOFF_N, BACKOFF_S = 3, 15 * 60
DETACHE = 0x00000008 | 0x00000200          # survit au garde et à la session


def age_heartbeat(chemin=HEARTBEAT):
    if not os.path.exists(chemin):
        return None
    try:
        d = json.load(open(chemin, encoding="utf-8"))
        quand = datetime.fromisoformat(d["quand_utc"])
    except (ValueError, KeyError, OSError):
        return None
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - quand).total_seconds()


def relances_recentes(chemin=RELANCES, maintenant=None):
    now = maintenant or datetime.now(timezone.utc).timestamp()
    try:
        l = json.load(open(chemin, encoding="utf-8"))
    except (OSError, ValueError):
        l = []
    return [t for t in l if now - t <= BACKOFF_S]


def noter_relance(chemin=RELANCES, maintenant=None):
    now = maintenant or datetime.now(timezone.utc).timestamp()
    l = relances_recentes(chemin, now) + [now]
    with open(chemin + ".tmp", "w", encoding="utf-8") as f:
        json.dump(l, f)
    os.replace(chemin + ".tmp", chemin)
    return l


def tuer(motif):
    """Tue les processus python dont la ligne de commande contient `motif`.

    UN SEUL endroit sait tuer un processus V3. Le motif porte DEUX barres
    obliques inversees : par `-Command` — le chemin utilise ici — PowerShell y
    lit la classe `[\\/]`, qui correspond a `\\` comme a `/`. Avec une seule,
    elle ne correspond a RIEN et le garde ne tuerait jamais personne, en
    silence (verifie le 11/09 sur le processus reel).
    """
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
           "Where-Object { $_.CommandLine -match '" + motif + "' } | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                       timeout=60, creationflags=0x08000000)
    except (subprocess.TimeoutExpired, OSError) as e:
        print("kill : %s (la relance continue)" % type(e).__name__)


def tuer_ecrivains():
    tuer("scenarios[\\\\/]boucle")


def relancer():
    log = os.path.join(RACINE, "LOGS", "scenarios_console.log")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("\n--- garde : relance %s UTC ---\n" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
        fh.flush()
        subprocess.Popen([sys.executable, "-X", "utf8", "-u", os.path.join("V3", "scenarios", "boucle.py")],
                         cwd=RACINE, stdout=fh, stderr=fh, creationflags=DETACHE)
    # battement PROVISOIRE tamponné : un écrivain jeune met quelques secondes à
    # battre ; sans tampon, un garde croisé tue un écrivain SAIN (course vue le 08/09)
    with open(HEARTBEAT + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"quand_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "relance_par_garde": True}, fh)
    os.replace(HEARTBEAT + ".tmp", HEARTBEAT)


def main():
    age = age_heartbeat()
    if age is not None and age <= MAX_AGE_S:
        print("ecrivain vivant (%.0f s)" % age)
        return 0
    if len(relances_recentes()) >= BACKOFF_N:
        print("BACKOFF : %d relances en %d min — je n'insiste pas, voir LOGS/scenarios_console.log"
              % (BACKOFF_N, BACKOFF_S // 60))
        return 2
    print("ecrivain mort (%s) : kill + relance" % ("absent" if age is None else "%.0f s" % age))
    tuer_ecrivains()
    relancer()
    noter_relance()
    return 1


if __name__ == "__main__":
    sys.exit(main())
