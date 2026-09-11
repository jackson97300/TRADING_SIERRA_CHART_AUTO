"""LE LANCEUR — une seule commande pour ouvrir le narrateur et VOIR ce qui se passe.

    V3\\execution\\LANCER_NARRATEUR.bat        (double-clic, ou depuis un terminal)
    python -X utf8 V3/execution/lanceur.py [--sans-fenetre] [--une-fois]

NE DE LA DEMANDE DE JACKSON (11/09) : « V3 fonctionnera a l'image de V1 : on le
lance dans un terminal et on VOIT ce qui se passe ; les quatre bots, je ne
voyais rien. » Les quatre .bat qui existaient avant celui-ci sont tous MUETS
(pythonw detache, sortie dans un fichier de log) : ils font tourner le module,
ils ne le MONTRENT pas. Celui-ci le montre.

CE QU'IL GARANTIT, ET C'EST SA RAISON D'ETRE :
  **il ne demarre JAMAIS un second ecrivain.** Deux ecrivains sur le meme
  journal, c'est l'incident du 08/09 — deux coureurs decouverts, et plus aucun
  journal live qui fasse foi jusqu'a la bascule. La vivacite se lit avec
  `garde_scenarios.age_heartbeat` et le seuil `MAX_AGE_S` du garde, IMPORTES :
  une seconde notion de « vivant » a cote de la premiere, c'est la meme panne
  sous un autre nom. Le demarrage passe par `garde_scenarios.relancer`, qui
  pose deja le battement tampon anti-course (leçon du 08/09).

Ce qu'il fait, dans l'ordre : il regarde ce qui tourne deja, il demarre ce qui
MANQUE et rien d'autre, puis il affiche l'etat au premier plan. Fermer le
moniteur (Ctrl-C) ne tue NI l'ecrivain NI la vitrine : ils sont detaches, la
campagne ne s'arrete pas parce qu'on ferme une fenetre.

Il ne decide rien et n'ecrit dans aucun journal. Il lit `/etat.json`, la meme
source que la page — jamais un calcul a lui (SPEC_VITRINE, phrase 2). Console
sans accents, comme le reste de `V3/execution` : une console Windows mal reglee
ne doit pas pouvoir casser l'affichage de l'etat.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.execution import garde_scenarios                          # noqa: E402
from V3.scenarios import lot                                      # noqa: E402

DETACHE = garde_scenarios.DETACHE        # survit a la fermeture du moniteur
SANS_FENETRE_CONSOLE = 0x08000000        # l'inventaire des processus, sans flash noir
RAFRAICHIR_S = 5                         # le moniteur ; la page a son propre reglage
LARGE = 74
# La classe de caracteres porte DEUX barres obliques inversees : par `-Command`
# (le chemin livre) PowerShell y lit `[\\/]`, qui correspond a `\` comme a `/`.
# Avec une seule, elle ne correspond a RIEN — et on ne verrait jamais la fenetre
# deja ouverte. Verifie sur le processus reel, pas deduit.
MOTIF_FENETRE = "scenarios[\\\\/]fenetre"


def port_vitrine():
    """Le port vient du yaml, jamais d'un defaut en dur : un defaut silencieux
    qui devie du reglage reel est la panne classique de ce depot."""
    return lot.seuils()["vitrine"]["port"]


def heartbeat():
    try:
        return json.load(open(garde_scenarios.HEARTBEAT, encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- ce qui tourne deja ------------------------------------------------------

def processus_vivant(motif):
    """Un processus python dont la ligne de commande contient `motif`.
    Rend None si la question n'a pas pu etre posee — jamais False : « je ne
    sais pas » et « il n'y en a pas » ne se confondent pas."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
           "Where-Object { $_.CommandLine -match '" + motif + "' } | "
           "Measure-Object | Select-Object -ExpandProperty Count")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=25,
                           creationflags=SANS_FENETRE_CONSOLE)
        return int(r.stdout.strip() or 0) > 0
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def vitrine_debout(port, delai=2.0):
    try:
        with urllib.request.urlopen("http://localhost:%d/version" % port, timeout=delai) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def etat_vitrine(port, delai=4.0):
    try:
        with urllib.request.urlopen("http://localhost:%d/etat.json" % port, timeout=delai) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _detacher(script, journal):
    """Demarre un module V3 detache, sa console dans LOGS/<journal>."""
    chemin = os.path.join(RACINE, "LOGS", journal)
    with open(chemin, "a", encoding="utf-8") as fh:
        fh.write("\n--- lanceur : demarrage %s ---\n"
                 % datetime.now().isoformat(timespec="seconds"))
        fh.flush()
        subprocess.Popen([sys.executable, "-X", "utf8", "-u", script],
                         cwd=RACINE, stdout=fh, stderr=fh, creationflags=DETACHE)


# --- demarrer ce qui manque, et rien d'autre ---------------------------------

def assurer_ecrivain():
    """Ne demarre que si le garde le declarerait mort. C'est LE garde-fou du
    fichier : tout le reste est du confort."""
    age = garde_scenarios.age_heartbeat()
    if age is not None and age <= garde_scenarios.MAX_AGE_S:
        return False, "deja vivant (bat il y a %.0f s) — je n'en demarre pas un second" % age
    garde_scenarios.relancer()
    return True, "absent (%s) — demarre" % ("aucun battement" if age is None else "%.0f s" % age)


def assurer_vitrine(port):
    if vitrine_debout(port):
        return False, "deja debout sur le port %d" % port
    _detacher(os.path.join("V3", "scenarios", "vitrine.py"), "vitrine_console.log")
    for _ in range(20):                                   # ~10 s : un serveur met un instant
        time.sleep(0.5)
        if vitrine_debout(port):
            return True, "demarree sur le port %d" % port
    return True, "demarree, mais muette — voir LOGS/vitrine_console.log"


def assurer_fenetre():
    """Comme la vitrine : on VERIFIE qu'elle est apparue avant de le dire.
    Annoncer « ouverte » sans regarder, c'est ce que faisait la premiere
    version — et si pywebview manque, elle ne s'ouvre jamais en ecrivant
    seulement une ligne dans son journal. Un lanceur qui ment sur ce qu'il a
    fait est pire qu'un lanceur qui echoue."""
    vivante = processus_vivant(MOTIF_FENETRE)
    if vivante is True:
        return False, "deja ouverte"
    _detacher(os.path.join("V3", "scenarios", "fenetre.py"), "fenetre_console.log")
    for _ in range(6):                          # pywebview met quelques secondes
        if processus_vivant(MOTIF_FENETRE) is True:
            return True, "ouverte"
        time.sleep(1.0)
    return True, "lancee, mais je ne la vois pas encore — voir LOGS/fenetre_console.log"


# --- l'affichage -------------------------------------------------------------

def _ligne(etiquette, texte):
    return "  %-10s %s" % (etiquette, texte)


def bloc(port, etat, age, hb):
    """Le pave affiche. `etat` = /etat.json (ou None), `hb` = le heartbeat sur
    disque, lu en repli QUAND la vitrine ne repond pas : le moniteur doit
    pouvoir dire pourquoi il ne dit rien."""
    out = ["-" * LARGE,
           "  NARRATEUR DE SEANCE" + " " * 21 + datetime.now().strftime("%d/%m/%Y  %H:%M:%S"),
           "-" * LARGE]

    if age is None:
        out.append(_ligne("ECRIVAIN", "AUCUN BATTEMENT — rien ne s'ecrit"))
    elif age > garde_scenarios.MAX_AGE_S:
        out.append(_ligne("ECRIVAIN", "MUET depuis %.0f s (seuil %d s) — le garde va le relancer"
                          % (age, garde_scenarios.MAX_AGE_S)))
    else:
        out.append(_ligne("ECRIVAIN", "bat il y a %.0f s   motif %s"
                          % (age, (hb or {}).get("motif", "?"))))
    env = (hb or {}).get("env") or {}
    if env:
        out.append(_ligne("", "python %s . pandas %s"
                          % (env.get("python", "?"), env.get("pandas", "?"))))

    if etat is None:
        out.append(_ligne("VITRINE", "MUETTE sur le port %d — voir LOGS/vitrine_console.log" % port))
        out += ["-" * LARGE, "  Ctrl-C ferme ce moniteur. L'ecrivain continue.", ""]
        return "\n".join(out)

    out.append(_ligne("VITRINE", "http://localhost:%d   jour %s   source %s"
                      % (port, etat.get("jour", "?"), etat.get("source", "?"))))

    syms = etat.get("sym") or {}
    if syms:
        for s in sorted(syms):
            d = syms[s] or {}
            out.append(_ligne(s, "%s   %s" % (d.get("heure_et", "--h--"),
                                              str(d.get("titre") or "-")[:46])))
    else:
        avant = etat.get("avant") or {}
        for s in sorted(avant):
            d = avant[s] or {}
            out.append(_ligne(s, "dernier %s a %s ET   (aucune barre de 15 min close)"
                              % (d.get("close", "?"), d.get("heure_et", "--h--"))))
        if not avant:
            out.append(_ligne("", "rien a montrer pour l'instant"))

    carnet = etat.get("carnet") or {}
    if carnet:
        out.append(_ligne("CARNET", " . ".join("%s %d" % (k, v)
                                               for k, v in sorted(carnet.items()))[:60]))
    if etat.get("non_mesure_w1"):
        out.append(_ligne("", "NON MESURE w1 — le dehors de VA_veille est provisoire (jour 20)"))

    out += ["-" * LARGE,
            "  Ctrl-C ferme ce moniteur. L'ecrivain et la vitrine CONTINUENT.", ""]
    return "\n".join(out)


def main(argv):
    os.chdir(RACINE)
    os.makedirs(os.path.join(RACINE, "LOGS"), exist_ok=True)
    port = port_vitrine()

    print("\n  MIA V3 — module SCENARIOS\n")
    print("  ecrivain : %s" % assurer_ecrivain()[1], flush=True)
    print("  vitrine  : %s" % assurer_vitrine(port)[1], flush=True)
    if "--sans-fenetre" not in argv:
        print("  fenetre  : %s" % assurer_fenetre()[1], flush=True)
    print()

    while True:
        print(bloc(port, etat_vitrine(port), garde_scenarios.age_heartbeat(), heartbeat()),
              flush=True)
        if "--une-fois" in argv:
            return 0
        time.sleep(RAFRAICHIR_S)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\n  moniteur ferme. L'ecrivain continue d'ecrire.\n")
        sys.exit(0)
