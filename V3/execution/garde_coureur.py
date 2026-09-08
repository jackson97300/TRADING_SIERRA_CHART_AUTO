"""Le GARDE du coureur — relance si le battement de cœur s'arrête.

    python -X utf8 V3/execution/garde_coureur.py [--sync]

Lancé par le planificateur TOUTES LES 5 MINUTES (machine de dev : avec
`--sync` ; VPS : sans — le fichier y est local). Si
`LOGS/heartbeat_coureur.json` est absent, illisible ou vieux de plus de
MAX_AGE_S, il tue tout `coureur_live` encore accroché puis en relance un,
détaché, console dans `LOGS/coureur_console.log`.

C'était l'étape 2 du tout premier plan (janvier), jamais copiée — la nuit
du 07 au 08/09 l'a payée : un processus qui doit vivre 23 h/24 sans
surveillant ne vit pas (INCIDENT VALIDATION_MISS 08/09). Les arguments du
garde sont TRANSMIS tels quels au coureur relancé.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
# 300 s, pas 180 (review R3) : deux scp en timeout (120 s chacun, panne
# reseau) font un tour a ~245 s — un garde a 180 force-tuerait un coureur
# SAIN toutes les 5 min pendant toute la panne.
MAX_AGE_S = 300
# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP : le coureur survit au garde
# ET a la session qui a lance le garde (planificateur, ssh, console).
DETACHE = 0x00000008 | 0x00000200


def age_heartbeat():
    """Âge du dernier battement en secondes — None si absent/illisible
    (les deux valent « mort », le garde relance)."""
    chemin = os.path.join(RACINE, "LOGS", "heartbeat_coureur.json")
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


def tuer_coureurs():
    """Tue tout python dont la ligne de commande porte `coureur_live` — un
    coureur accroché (battement mort mais process vivant) doublerait le
    journal si on relançait par-dessus. PowerShell est le seul filtre par
    ligne de commande portable sur Windows ; un échec du kill ne bloque
    pas la relance (la reprise du coureur dédoublonne de toute façon)."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
           "Where-Object { $_.CommandLine -match 'coureur_live' } | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, timeout=60,
                       creationflags=0x08000000)   # jamais de fenetre
    except (subprocess.TimeoutExpired, OSError) as e:
        print("kill : %s (la relance continue)" % type(e).__name__)


def relancer(args):
    log = os.path.join(RACINE, "LOGS", "coureur_console.log")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("\n--- garde : relance %s UTC ---\n"
                 % datetime.now(timezone.utc).isoformat(timespec="seconds"))
        fh.flush()
        subprocess.Popen(
            [sys.executable, "-X", "utf8", "-u",
             os.path.join("V3", "execution", "coureur_live.py"), *args],
            cwd=RACINE, stdout=fh, stderr=fh, creationflags=DETACHE)
    # Battement PROVISOIRE tamponne a la relance : un jeune coureur met
    # ~60-90 s a battre (chauffe) — sans ce tampon, un tick du garde dans
    # la fenetre tue un coureur SAIN (course OBSERVEE au deploiement VPS
    # 08/09 : la relance de 10:38:03 tuee a 10:38:47 par un garde croise).
    tmp = os.path.join(RACINE, "LOGS", "heartbeat_coureur.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"quand_utc": datetime.now(timezone.utc)
                   .isoformat(timespec="seconds"),
                   "relance_par_garde": True}, fh)
    os.replace(tmp, os.path.join(RACINE, "LOGS", "heartbeat_coureur.json"))


# Reserve 2 revue Fable 08/09 : 443 battements bloques pendant des heures de
# cash et rien n'a alerte — le garde voyait un heartbeat vivant, L0 fermait
# avec un motif FAUX (ferie fantome 1970). Un bot qui dit non a tout n'est
# pas prudent, il est casse. Si les K dernieres tournees de battement en
# CASH sont toutes bloquees par une porte de DONNEES ou de CALENDRIER, on
# l'ecrit — une fois par jour, dans un fichier qu'un humain regarde.
FAMILLE_VIVACITE = ("L0_FERIE_CME", "L0_DATA_PERIMEE",
                    "L0_DATA_COLONNE_MORTE", "L0_DATA_FENETRE_MELANGEE",
                    "L0_DATA_L6_ALERTE")
K_TOURNEES = 3


def alerte_vivacite(jour):
    """K tournees consecutives bloquees donnees/calendrier en cash -> alerte."""
    if not jour:
        return
    marque = os.path.join(RACINE, "LOGS", "ALERTE_VIVACITE_%s.txt" % jour)
    if os.path.exists(marque):
        return                        # deja alerte aujourd'hui, pas de spam
    chemin = os.path.join(RACINE, "LOGS", "entonnoir", "live_%s.jsonl" % jour)
    if not os.path.exists(chemin):
        return
    if RACINE not in sys.path:        # schtasks ne garantit pas le cwd
        sys.path.insert(0, RACINE)
    import pandas as pd               # import tardif : le tick nominal du
    from CORE.features import recalc  # garde reste leger
    tours = {}                        # (sym, idx) -> {ts, famille}
    for ln in open(chemin, encoding="utf-8"):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("hypothese") != "battement" or e.get("decision") != "BLOQUE":
            continue
        bouts = (e.get("snapshot_id") or "").split(":")
        if len(bouts) < 3:
            continue
        cle = (bouts[0], int(bouts[1]) if bouts[1].isdigit() else -1)
        t = tours.setdefault(cle, {"ts": e.get("ts"), "motifs": set()})
        if e.get("motif") in FAMILLE_VIVACITE:
            t["motifs"].add(e["motif"])
    for sym in ("ES", "NQ"):
        derniers = sorted(k for k in tours if k[0] == sym)[-K_TOURNEES:]
        if len(derniers) < K_TOURNEES:
            continue
        if not all(tours[k]["motifs"] for k in derniers):
            continue
        ts = pd.Series([tours[k]["ts"] for k in derniers], dtype="float64")
        dt = pd.to_datetime(ts, unit="ms", utc=True)
        minutes = recalc.minutes_et(dt)
        if not ((minutes >= recalc.CASH_DEBUT_MIN_ET)
                & (minutes < recalc.CASH_FIN_MIN_ET)).all():
            continue                  # au moins une tournee hors cash : non
        motifs = sorted(set().union(*(tours[k]["motifs"] for k in derniers)))
        msg = ("%s UTC — VIVACITE %s : %d tournees de battement en cash "
               "toutes bloquees donnees/calendrier (indices %s, motifs %s)."
               " Un bot qui dit non a tout est casse — diagnostiquer." % (
                   datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   sym, K_TOURNEES, [k[1] for k in derniers], motifs))
        with open(marque, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
        with open(os.path.join(RACINE, "LOGS", "coureur_console.log"),
                  "a", encoding="utf-8") as fh:
            fh.write("\n!!! " + msg + "\n")
        print(msg)


def main():
    # Un jour POSITIONNEL transmis au coureur l'epinglerait pour toujours
    # (roule=False) — c'est l'incident meme qu'on corrige. Flags seulement.
    if any(not x.startswith("-") for x in sys.argv[1:]):
        print("REFUS : le garde ne transmet que des flags (--sync), jamais"
              " un jour — un jour fige a coute la nuit du 07 au 08.")
        return 1
    os.makedirs(os.path.join(RACINE, "LOGS"), exist_ok=True)
    age = age_heartbeat()
    if age is not None and age <= MAX_AGE_S:
        print("coureur vivant — battement il y a %.0f s" % age)
        try:
            chemin = os.path.join(RACINE, "LOGS", "heartbeat_coureur.json")
            jour = json.load(open(chemin, encoding="utf-8")).get("jour")
            alerte_vivacite(jour)
        except Exception as e:        # la vivacite ne doit JAMAIS casser le
            print("vivacite KO : %s: %s" % (type(e).__name__, e))  # garde
        return 0
    print("battement %s — kill puis relance"
          % ("ABSENT" if age is None else "vieux de %.0f s" % age))
    tuer_coureurs()
    relancer(sys.argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
