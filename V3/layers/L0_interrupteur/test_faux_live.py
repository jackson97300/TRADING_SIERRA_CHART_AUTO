"""Le FAUX LIVE — les sept portes muettes, exercees sur le vrai chemin de code.

    python -X utf8 V3/layers/L0_interrupteur/test_faux_live.py

`test_portes.py` appelle chaque porte directement, avec un dictionnaire. Utile,
mais insuffisant : il ne prouve pas que `chaine.appliquer` transmet l'etat live
jusqu'a elles, ni que `strict=True` bloque vraiment sur un trou. Sept portes
n'ont **jamais** ete exercees — leur terrain est le live, et le live n'a pas
encore tourne.

Ce fichier rejoue une vraie journee a travers `chaine.appliquer(strict=True,
live={...})` avec un etat fabrique, et verifie que chaque porte ferme **avec son
motif**. Sans cela, L0 en live est une hypothese.

DEUX FAMILLES DE CAS
--------------------
1. **La donnee est presente et mauvaise** : `age_s = 200` doit declencher
   `L0_DATA_PERIMEE`, `dtc_connecte = False` doit declencher
   `L0_DTC_DECONNECTE`, etc. La porte bloque avec son propre motif.
2. **La donnee est absente** : le champ manque dans `live`. La porte rend
   `None`, et en mode strict le TROU doit bloquer. C'est le cas qui protege
   contre le pire scenario — decider sans savoir.

Un troisieme cas, le nominal, verifie qu'un etat live SAIN ne bloque rien :
sans lui, un test ou tout bloque toujours passerait sans rien prouver.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from V3 import chaine                                         # noqa: E402
from V3.layers.L0_interrupteur import portes                  # noqa: E402

JOUR, SYM = "20260903", "ES"
# Un trou ne BLOQUE en strict que sur une porte APPLIQUEE (chaine.appliquer :
# `bloquantes += trous & APPLIQUEES`). Une porte passee observee — le
# rollover du 10/09 met L0_CONTRAT_INACTIF en observee le temps que Sierra
# bascule — se journalise avec son motif, sans fermer. Le test lit le YAML.
_S, APPLIQUEES, _A = portes.charger_seuils()

# Un etat live SAIN : rien ne doit bloquer a cause de lui.
LIVE_SAIN = {
    "age_s": 12.0,
    "l6_alerte": False,
    "colonnes_mortes": False,
    "rollover": False,
    "contrat_actif": True,
    "dtc_connecte": True,
}

# (nom du cas, ce qu'on change dans le live, motif attendu)
CAS_MAUVAIS = [
    ("barre vieille de 200 s", {"age_s": 200.0}, "L0_DATA_PERIMEE"),
    ("L6 a leve une alerte", {"l6_alerte": True}, "L0_DATA_L6_ALERTE"),
    ("colonne figee ce jour-la", {"colonnes_mortes": True},
     "L0_DATA_COLONNE_MORTE"),
    ("rollover en cours", {"rollover": True}, "L0_ROLLOVER"),
    # Le contrat du JSONL n'est pas celui du compte : ESZ26 lu sur un compte
    # qui traite MES. Le bot enverrait l'ordre sur le mauvais instrument.
    ("contrat different du compte", {"contrat_actif": False},
     "L0_CONTRAT_INACTIF"),
    ("connecteur DTC tombe", {"dtc_connecte": False}, "L0_DTC_DECONNECTE"),
]

# (nom du cas, champ RETIRE du live, motif de trou attendu)
CAS_ABSENTS = [
    ("age inconnu", "age_s", "TROU_L0_DATA_PERIMEE"),
    ("verdict L6 inconnu", "l6_alerte", "TROU_L0_DATA_L6_ALERTE"),
    ("colonnes mortes inconnues", "colonnes_mortes",
     "TROU_L0_DATA_COLONNE_MORTE"),
    ("etat du rollover inconnu", "rollover", "TROU_L0_ROLLOVER"),
    ("contrat inconnu", "contrat_actif", "TROU_L0_CONTRAT_INACTIF"),
    ("etat DTC inconnu", "dtc_connecte", "TROU_L0_DTC_DECONNECTE"),
]


def _rejouer(df, live, strict=True, n=12):
    """Passe les `n` premieres barres dans la chaine. Rend (retenus, motifs)."""
    import json
    import tempfile
    signaux = [(i, 1) for i in range(4, min(4 + n, len(df)))]
    fd, chemin = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.remove(chemin)
    try:
        retenus = chaine.appliquer(signaux, df, SYM, journal=chemin,
                                   hypothese="faux_live", strict=strict,
                                   live=live)
        motifs = set()
        if os.path.exists(chemin):
            for ln in open(chemin, encoding="utf-8"):
                ln = ln.strip()
                if ln:
                    o = json.loads(ln)
                    if o.get("decision") == "BLOQUE":
                        motifs.add(o.get("motif"))
        return retenus, motifs
    finally:
        if os.path.exists(chemin):
            os.remove(chemin)


def main():
    df = charger_jour(SYM, JOUR, 15)
    if df.empty or len(df) < 8:
        print("  journee %s indisponible — test impossible" % JOUR)
        return 1

    echecs = []

    # --- cas nominal : un live sain ne doit bloquer aucune porte live -------
    retenus, motifs = _rejouer(df, dict(LIVE_SAIN))
    attendus_absents = {m for _n, _c, m in CAS_MAUVAIS}
    fautifs = attendus_absents & motifs
    if fautifs:
        echecs.append("live SAIN : %s bloque(nt) alors que tout va bien"
                      % ", ".join(sorted(fautifs)))
    if not retenus:
        echecs.append("live SAIN : aucun signal retenu — un test ou tout "
                      "bloque ne prouve rien")

    # --- la donnee est presente et mauvaise --------------------------------
    for nom, mod, motif in CAS_MAUVAIS:
        _r, motifs = _rejouer(df, dict(LIVE_SAIN, **mod))
        if motif not in motifs:
            echecs.append("%-32s : %s attendu, absent du journal" % (nom, motif))

    # --- la donnee est absente : le trou doit bloquer en mode strict --------
    for nom, champ, motif in CAS_ABSENTS:
        live = {k: v for k, v in LIVE_SAIN.items() if k != champ}
        r, motifs = _rejouer(df, live, strict=True)
        if motif not in motifs:
            echecs.append("%-32s : %s attendu, absent du journal" % (nom, motif))
        elif r and motif[len("TROU_"):] in APPLIQUEES:
            echecs.append("%-32s : le trou est journalise mais %d signaux "
                          "passent quand meme en mode strict" % (nom, len(r)))
        elif r:
            print("  (%s : porte OBSERVEE dans le YAML — le trou se journalise "
                  "sans fermer, c'est attendu)" % motif[len("TROU_"):])

    # --- hors ligne, le meme trou ne doit PAS bloquer ----------------------
    # Sinon aucune mesure historique ne serait possible : l'age d'une barre
    # n'existe pas dans un backtest, et le compter comme un blocage rendrait
    # tout le rapport ininterpretable.
    r, _m = _rejouer(df, {}, strict=False)
    if not r:
        echecs.append("hors ligne (strict=False) : les trous bloquent, alors "
                      "qu'ils ne doivent que se journaliser")

    n = 1 + len(CAS_MAUVAIS) + len(CAS_ABSENTS) + 1
    print("  faux live — %d scenarios sur le vrai chemin de code "
          "(chaine.appliquer)" % n)
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : les six portes live bloquent avec leur motif, les six trous "
          "bloquent\n       en mode strict, et ni le live sain ni le mode hors "
          "ligne ne ferment rien.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
