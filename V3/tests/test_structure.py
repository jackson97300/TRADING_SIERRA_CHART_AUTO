"""Le garde-fou du miroir public. Tourne EN PRE-COMMIT, pas avant le push.

Pourquoi en pre-commit : un `git subtree push` pousse **tout l'historique** du
dossier. Un secret committe une seule fois y reste, meme supprime au commit
suivant. Verifier l'etat courant avant le premier push ne protege de rien —
il faut verifier avant chaque commit.

    python -X utf8 V3/tests/test_structure.py

Rend 0 si tout passe, 1 sinon. A brancher dans `.git/hooks/pre-commit`.
"""

from __future__ import annotations

import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- ce qui ne doit JAMAIS sortir -------------------------------------------
# Motifs volontairement larges : un faux positif coute une minute, une fuite
# est definitive.
INTERDITS = [
    (r"discord(app)?\.com/api/webhooks", "webhook Discord"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "adresse IP"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "cle privee"),
    (r"\bSim[1-9]\b", "compte de trading"),
    (r"[A-Za-z]:\\\\?(Users|TRADING|MIA)", "chemin de machine"),
    (r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[=:]\s*['\"][^'\"]{8,}",
     "identifiant en dur"),
    (r"(?i)\bmq_levels\b.*\d{4,}", "niveau MenthorQ (donnee sous licence)"),
]

# Ces fichiers parlent des interdits sans en contenir — le garde-fou s'exclut
# lui-meme, sinon il se declenche sur ses propres motifs.
EXEMPTS = {"tests/test_structure.py"}

TAILLE_MAX = 1_000_000          # 1 Mo : au-dela, c'est une donnee, pas du code
LIGNES_MAX = 300                # regle du chantier : un fichier se relit


def fichiers():
    """Seuls les fichiers que GIT SUIVRAIT. Un fichier ignore ne part jamais
    dans le miroir public : le scanner produit des faux positifs, et un faux
    positif qui bloque un commit legitime finit par faire desactiver le
    garde-fou. `comptes.local.yaml` a declenche ce cas des le premier usage.
    """
    import subprocess
    try:
        r = subprocess.run(["git", "ls-files", "--cached", "--others",
                            "--exclude-standard", "V3/"],
                           capture_output=True, text=True, timeout=30,
                           cwd=os.path.dirname(RACINE))
        rels = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        rels = []
    if not rels:                       # pas de git : on scanne tout, prudence
        for base, dirs, noms in os.walk(RACINE):
            dirs[:] = [d for d in dirs if d not in
                       {".git", "__pycache__", ".venv", "venv", "node_modules"}]
            for n in noms:
                p = os.path.join(base, n)
                yield p, os.path.relpath(p, RACINE).replace("\\", "/")
        return
    for rel in rels:                   # rel est relatif a la racine du depot
        p = os.path.join(os.path.dirname(RACINE), rel)
        if os.path.exists(p):
            yield p, rel[3:] if rel.startswith("V3/") else rel


def controler():
    echecs = []
    for chemin, rel in fichiers():
        try:
            taille = os.path.getsize(chemin)
        except OSError:
            continue

        if taille > TAILLE_MAX:
            echecs.append("%s : %.1f Mo — une donnee, pas du code"
                          % (rel, taille / 1e6))
            continue
        if re.search(r"(_backup|_old|\.bak|_BACKUP|_OLD)", rel):
            echecs.append("%s : sauvegarde a cote du vivant — git existe" % rel)
        if rel in EXEMPTS or not rel.endswith((".py", ".md", ".yaml", ".yml",
                                               ".json", ".txt", ".bat", ".sh")):
            continue

        try:
            txt = open(chemin, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue

        for motif, quoi in INTERDITS:
            m = re.search(motif, txt)
            if m:
                extrait = m.group(0)[:40]
                echecs.append("%s : %s — %r" % (rel, quoi, extrait))

        if rel.endswith(".py"):
            n = txt.count("\n") + 1
            if n > LIGNES_MAX:
                echecs.append("%s : %d lignes (max %d) — a decouper"
                              % (rel, n, LIGNES_MAX))
    return echecs


def main():
    echecs = controler()
    n = sum(1 for _ in fichiers())
    print("  garde-fou V3 — %d fichiers examines" % n)
    if not echecs:
        print("  OK : rien de sensible, rien de volumineux, rien de trop long.")
        return 0
    print("  %d PROBLEME(S) — le commit doit etre refuse :" % len(echecs))
    for e in echecs:
        print("     %s" % e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
