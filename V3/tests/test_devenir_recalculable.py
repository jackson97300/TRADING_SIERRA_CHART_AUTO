"""LE JOUR 61 POURRA-T-IL LIRE CE QU'ON ECRIT AUJOURD'HUI ?

    python -X utf8 V3/tests/test_devenir_recalculable.py

LA QUESTION DE JACKSON, le 11/09 au soir : « le devenir est ferme, d'accord,
mais est-ce qu'il est bien enregistre et bien calcule ? On ne doit pas arriver
au jour 61 et se rendre compte que rien n'est enregistre et que le systeme est
casse. » C'est la bonne question, et elle ne se verifie pas en l'esperant.

CE QUI A ETE TROUVE EN LA POSANT. Le devenir n'a PAS besoin d'etre stocke : il
doit etre RECALCULABLE. Un signal est recalculable si le journal garde son
identite, son horodatage, son sens, son entree et ses deux barrieres — les
barres, elles, sont conservees dans `DATA/live_enriched`. Sur les quatre
premiers jours, 26 lignes sur 27 le sont ; la 27e porte
`motif_ligne: fenetre_absente` (un signal sur la DERNIERE barre, donc sans
fenetre pour poser des barrieres), ce qui est une absence DECLAREE, pas un trou.

MAIS LE SCHEMA A DERIVE EN QUATRE JOURS. Les trois premiers jours nomment le
declencheur `setup` et `famille` ; le quatrieme le nomme `hypothese`. Un
lecteur du jour 61 qui cherche `hypothese` ne trouverait RIEN pour les trois
premiers jours — et il ne planterait pas, il compterait zero. C'est exactement
le scenario que Jackson redoute, et il a deja commence. Cinquante-sept jours
restent a courir.

CE TEST NE LIT AUCUN DEVENIR. Il verifie que les champs qui permettront de le
RECALCULER sont la, et que le schema ne bouge pas. Il compte des cles, jamais
une valeur de `pnl_atr` ni d'`issue`.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

PASSED = FAILED = 0

# Ce qu'il FAUT pour recalculer un devenir au jour 61, et rien de plus.
MINIMUM = ("snapshot_id", "ts", "sym", "side", "entree", "sl_prix", "tp_prix", "barriere")
# Le nom du declencheur a porte TROIS noms differents en quatre jours. Le
# lecteur du jour 61 doit accepter les trois, sinon il lit zero en silence.
NOMS_DECLENCHEUR = ("hypothese", "setup", "famille")
# Champs de DEVENIR : ce test verifie leur PRESENCE, jamais leur valeur.
DEVENIR = ("pnl_atr", "issue", "motif_issue")
JOUR_1 = "20260908"


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def lignes_campagne():
    """Toutes les lignes de barrieres depuis le jour 1, jour par jour."""
    out = []
    for f in sorted(glob.glob("LOGS/barrieres/barrieres_2026*.jsonl")):
        j = re.search(r"(\d{8})", os.path.basename(f))
        if not j or j.group(1) < JOUR_1 or "_avant_" in f:
            continue
        for ln in open(f, encoding="utf-8"):
            try:
                out.append((j.group(1), json.loads(ln)))
            except ValueError:
                out.append((j.group(1), None))
    return out


# Le lecteur normalise vit dans `campagne.py` — SOURCE UNIQUE. Une copie ici
# deriverait le jour ou une quatrieme convention apparait, et le jour 61 lirait
# deux verites differentes selon le fichier qui l'interroge.
from V3.journal_lecture import declencheur, NOMS_DECLENCHEUR as NOMS_CAMPAGNE  # noqa: E402


def main():
    lignes = lignes_campagne()
    print("\n[1] chaque signal est-il RECALCULABLE au jour 61 ?")
    check("[1a] le journal des barrieres existe et porte des lignes", bool(lignes))
    if not lignes:
        print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
        return 1
    check("[1b] aucune ligne illisible (JSON casse)",
          all(d is not None for _, d in lignes))

    incomplets, declarees = [], []
    for j, d in lignes:
        if d is None:
            continue
        absents = [c for c in MINIMUM if d.get(c) is None]
        if not absents:
            continue
        (declarees if d.get("motif_ligne") else incomplets).append(
            (j, d.get("snapshot_id"), absents, d.get("motif_ligne")))
    check("[1c] toute ligne incomplete porte un MOTIF — une absence declaree, jamais un trou",
          not incomplets, incomplets[:2])
    print("     %d ligne(s) completes, %d avec absence declaree (%s)"
          % (len(lignes) - len(declarees) - len(incomplets), len(declarees),
             ", ".join(sorted({x[3] for x in declarees})) or "-"))

    check("[1d] chaque ligne nomme son declencheur (quel que soit le champ)",
          all(declencheur(d) for _, d in lignes if d), )

    print("\n[2] le SCHEMA derive-t-il ? — le piege du jour 61")
    schemas = defaultdict(set)
    for j, d in lignes:
        if d:
            schemas[tuple(sorted(d.keys()))].add(j)
    print("     %d schema(s) distinct(s) sur %d jour(s)"
          % (len(schemas), len({j for j, _ in lignes})))
    for i, (cles, jours) in enumerate(sorted(schemas.items(), key=lambda kv: min(kv[1])), 1):
        print("       schema %d : %2d cles, jours %s" % (i, len(cles), ", ".join(sorted(jours))))
    # La derive est un FAIT constate, pas un echec : ce qui doit echouer, c'est
    # qu'un champ du MINIMUM disparaisse d'un schema a l'autre.
    # Un schema peut legitimement manquer du minimum S'IL porte `motif_ligne` :
    # c'est le cas de l'absence DECLAREE (signal sur la derniere barre, aucune
    # fenetre pour poser des barrieres). Ce qui doit echouer, c'est un schema
    # qui perd un champ SANS le dire.
    manquants = [sorted(set(MINIMUM) - set(c)) for c in schemas
                 if (set(MINIMUM) - set(c)) and "motif_ligne" not in c]
    check("[2a] aucun schema ne perd un champ du minimum SANS declarer son motif",
          not manquants, manquants[:2])
    noms = {c for cles in schemas for c in cles if c in NOMS_DECLENCHEUR}
    check("[2b] les noms du declencheur vus sont tous connus du lecteur du jour 61",
          noms <= set(NOMS_DECLENCHEUR), sorted(noms))
    check("[2c] le lecteur normalise de `campagne.py` connait les MEMES noms — source unique",
          set(NOMS_CAMPAGNE) == set(NOMS_DECLENCHEUR), (NOMS_CAMPAGNE, NOMS_DECLENCHEUR))
    check("[2d] il lit les trois conventions sur de VRAIES lignes des quatre jours",
          all(declencheur(d) for _, d in lignes if d))
    if len(schemas) > 1:
        print("     ATTENTION : le schema a deja bouge. Un lecteur qui ne chercherait")
        print("     que `hypothese` compterait ZERO sur les premiers jours, sans planter.")

    print("\n[3] le devenir : present ou absent, JAMAIS lu")
    avec = sum(1 for _, d in lignes if d and any(c in d for c in DEVENIR))
    print("     %d ligne(s) portent des champs de devenir, %d n'en portent pas"
          % (avec, len(lignes) - avec))
    src = Path("V3/tests/test_devenir_recalculable.py").read_text(encoding="utf-8")
    corps = src.split('"""', 2)[-1]
    check("[3a] ce test ne LIT aucune valeur de devenir",
          all(("d[%r]" % c) not in corps and ("d.get(%r)" % c) not in corps for c in DEVENIR))
    check("[3b] le devenir n'est PAS necessaire : le minimum recalculable suffit",
          all(c not in MINIMUM for c in DEVENIR))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
