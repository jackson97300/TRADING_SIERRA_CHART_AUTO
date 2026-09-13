"""L'EMPREINTE DES COUCHES — savoir, au jour 61, quel code a juge quel jour.

    python -X utf8 V3/empreintes.py [jour]

POURQUOI. Trois couches sur six — L1, L4 et REG — n'ecrivent AUCUN journal
quotidien. Ce n'est pas grave en soi : leurs verdicts sont des fonctions pures
de la trame, et la trame est conservee. Ils se RECALCULENT au jour 61, comme le
devenir (`test_devenir_recalculable` : « le devenir n'a pas besoin d'etre
stocke, il doit etre recalculable »).

MAIS UN RECALCUL N'EST UNE MESURE QUE SI LE CODE N'A PAS BOUGE. Si `biais.py`
change entre aujourd'hui et le terme, le verdict recalcule ne sera pas celui
qui a tourne — et rien ne le dirait. Or la derive a deja commence : le schema
des journaux a bouge en quatre jours, et trois conventions de nommage du
declencheur coexistent.

Ce module ecrit donc UNE LIGNE PAR JOUR par couche : l'empreinte de son code et
celle de ses seuils. Au terme, on saura pour quels jours le code qui juge est
le code qui a tourne — et surtout, on saura de quels jours il faut se mefier.

Meme geste que l'empreinte du serveur de la vitrine, qui lui permet de dire
« je suis perime » au lieu de mentir. Une empreinte ne corrige rien ; elle
empeche de croire a une continuite qui n'existe pas.

CE N'EST PAS UNE PREUVE CRYPTOGRAPHIQUE — douze caracteres, de quoi distinguer
deux etats du code. Et ce n'est pas un gel : le code a le droit de changer. Ce
qui n'a pas le droit, c'est de changer sans que la mesure le sache.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

# Les couches, et ce qui les definit. Le NOYAU est le code que la chaine
# execute ; les SEUILS sont les nombres qu'il lit. Les deux doivent etre
# suivis : un seuil qui bouge change le verdict autant qu'une ligne de code.
COUCHES = {
    "L0": "V3/layers/L0_interrupteur",
    "REG": "V3/layers/REG_regime",
    "L1": "V3/layers/L1_biais",
    "L3": "V3/layers/L3_declencheurs",
    "L4": "V3/layers/L4_orderflow",
    "L5": "V3/layers/L5_risque",
    "L6": "V3/layers/L6_surveillance",
}
# Le tronc commun : ce que TOUTES les couches traversent. Un changement ici
# touche tout le monde, et il serait invisible dans l'empreinte d'une couche.
NOYAU = ("V3/chaine.py", "V3/lecture.py", "V3/lecture_colonnes.py",
         "V3/registre.py", "V3/lieux.py")

# ET LE CORE, trou trouve par ce module lui-meme le 14/09. Le dossier de la
# couche REG est VIDE — son README affirme pourtant que « rien de cette couche
# ne vit ailleurs ». Son code vit en realite dans `CORE/research/hypotheses.py`,
# le fichier qui definit AUSSI les quatre hypotheses gelees. Autrement dit : le
# fichier le plus important de la campagne n'etait couvert par aucune empreinte.
# La liste vient de `MANIFESTE_CORE.txt`, GENERE par `test_dependances.py` et
# jamais ecrit a la main — donc elle suit les dependances au lieu de les deviner.
MANIFESTE_CORE = os.path.join(RACINE, "V3", "MANIFESTE_CORE.txt")

DOSSIER = os.path.join(RACINE, "LOGS", "empreintes")


def _hash_fichiers(chemins):
    """Le nom compte autant que le contenu : un fichier RENOMME est un
    changement. Rend douze caracteres, ou None si rien a lire."""
    h = hashlib.sha256()
    vus = 0
    for c in sorted(chemins):
        if not os.path.isfile(c):
            continue
        with open(c, "rb") as f:
            h.update(os.path.basename(c).encode("utf-8"))
            h.update(f.read())
        vus += 1
    return h.hexdigest()[:12] if vus else None


def _lister(dossier, suffixes):
    if not os.path.isdir(dossier):
        return []
    return [os.path.join(dossier, n) for n in os.listdir(dossier)
            if n.endswith(suffixes) and not n.startswith("test_")]


def empreinte_couche(nom):
    """(code, seuils) pour une couche. Les tests sont EXCLUS du code : ils ne
    changent aucun verdict, et les inclure ferait clignoter l'empreinte a
    chaque test ajoute — une alarme qui clignote finit ignoree."""
    d = os.path.join(RACINE, COUCHES[nom])
    return {"code": _hash_fichiers(_lister(d, (".py",))),
            "seuils": _hash_fichiers(_lister(d, (".yaml", ".yml")))}


def empreinte_noyau():
    return _hash_fichiers([os.path.join(RACINE, c) for c in NOYAU])


def fichiers_core():
    """Les modules CORE dont la chaine depend, lus dans le manifeste GENERE.
    On ne devine pas la liste : elle change quand les dependances changent."""
    if not os.path.exists(MANIFESTE_CORE):
        return []
    out = []
    for ln in open(MANIFESTE_CORE, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        base = os.path.join(RACINE, *ln.split("."))
        for cand in (base + ".py", os.path.join(base, "__init__.py")):
            if os.path.isfile(cand):
                out.append(cand)
    return out


def empreinte_core():
    return _hash_fichiers(fichiers_core())


def composer(jour):
    """La ligne du jour. Aucun devenir, aucune donnee de marche — uniquement
    des empreintes de code et de configuration."""
    return {"jour": jour, "ecrit_a": datetime.now(timezone.utc)
            .isoformat(timespec="seconds"),
            "noyau": empreinte_noyau(),
            "core": empreinte_core(),
            "couches": {n: empreinte_couche(n) for n in sorted(COUCHES)}}


def chemin(jour):
    return os.path.join(DOSSIER, "empreintes_%s.jsonl" % jour)


def ecrire(jour):
    """Une ligne par passage. On N'ECRASE PAS : si le rythme du soir tourne
    deux fois, deux lignes — et l'ecart entre elles est en soi l'information
    qu'on cherche (le code a bouge en cours de journee)."""
    os.makedirs(DOSSIER, exist_ok=True)
    ligne = composer(jour)
    tmp = "%s.%d.tmp" % (chemin(jour), os.getpid())
    ancien = ""
    if os.path.exists(chemin(jour)):
        ancien = open(chemin(jour), encoding="utf-8").read()
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(ancien + json.dumps(ligne, ensure_ascii=False) + "\n")
    os.replace(tmp, chemin(jour))
    return ligne


def derives(jusqu_a=None):
    """Les couches dont l'empreinte a CHANGE d'un jour a l'autre, avec les
    jours concernes. C'est la lecture du jour 61 : pour quels jours le code qui
    juge n'est-il pas le code qui a tourne ?"""
    import glob
    lignes = []
    for f in sorted(glob.glob(os.path.join(DOSSIER, "empreintes_2026*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            try:
                lignes.append(json.loads(ln))
            except ValueError:
                continue
    lignes.sort(key=lambda d: (d["jour"], d["ecrit_a"]))
    if jusqu_a:
        lignes = [d for d in lignes if d["jour"] <= jusqu_a]
    out = {}
    precedent = None
    for d in lignes:
        if precedent is not None:
            for cle in ("noyau", "core"):
                if d.get(cle) != precedent.get(cle):
                    out.setdefault(cle, []).append(d["jour"])
            for n, e in d["couches"].items():
                if e != precedent["couches"].get(n):
                    out.setdefault(n, []).append(d["jour"])
        precedent = d
    return out


def main():
    os.chdir(RACINE)
    jour = sys.argv[1] if len(sys.argv) > 1 else \
        datetime.now(timezone.utc).strftime("%Y%m%d")
    ligne = ecrire(jour)
    print("EMPREINTES — %s" % jour)
    print("  noyau : %s   core : %s (%d fichiers)"
          % (ligne["noyau"], ligne["core"], len(fichiers_core())))
    for n, e in sorted(ligne["couches"].items()):
        print("  %-4s code %s   seuils %s"
              % (n, e["code"] or "—", e["seuils"] or "—"))
    d = derives()
    print()
    if d:
        print("  DERIVES CONSTATEES — le code qui juge n'est pas celui qui a tourne :")
        for n, jours in sorted(d.items()):
            print("     %-6s a change le(s) : %s" % (n, ", ".join(jours)))
    else:
        print("  aucune derive constatee sur les jours releves")
    print("\njournal : %s" % chemin(jour))
    return 0


if __name__ == "__main__":
    sys.exit(main())
