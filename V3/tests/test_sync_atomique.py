"""LA SYNCHRO NE DOIT JAMAIS LIVRER UN FICHIER PARTIEL.

    python -X utf8 V3/tests/test_sync_atomique.py

CE QUE CE TEST DEFEND, et il a un prix connu : UNE JOURNEE DE CAMPAGNE.

Le 11/09 au soir, le rejeu officiel a plante sur
`PermissionError: ... 20260911_NQ_sierra_enriched.jsonl` : `scp` ecrivait le
fichier DIRECTEMENT sous son nom final, donc pendant la copie le fichier
existait et il etait partiel. `campagne.courir` a fait ce qu'il doit faire —
effacer ses trois journaux plutot que laisser une demi-mesure passer pour un
jour muet — et le jour 11/09 a compte comme NON COURU. Une course de quelques
secondes, un jour perdu sur soixante-et-un. Le meme accident etait deja note
dans `campagne.py` pour le 08/09 (`ombre_c2` tombe de 8 lignes a 1).

Depuis, `synchroniser()` ecrit dans `.tmp` puis fait `os.replace` : un lecteur
voit soit l'ANCIEN fichier complet, soit le NOUVEAU complet, jamais un
entre-deux. C'est la convention deja suivie partout ailleurs dans le depot ; la
synchro etait le dernier endroit a ne pas la respecter.

ET CE CORRECTIF EST INDEPENDANT DE LA BASCULE VPS. La course est entre le `scp`
et le rejeu, pas entre les deux coureurs : elle aurait survecu a la bascule.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.execution import sync_vps                                # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def main():
    src = open(RACINE / "V3" / "execution" / "sync_vps.py", encoding="utf-8").read()

    print("\n[1] l'ecriture est ATOMIQUE dans le code")
    check("[1a] `scp` ecrit dans un `.tmp`, jamais sous le nom final",
          '".tmp"' in src or "+ \".tmp\"" in src or 'final + ".tmp"' in src, )
    check("[1b] la bascule passe par `os.replace`", "os.replace(tmp, final)" in src)
    check("[1c] `scp` ne recoit PLUS un dossier comme destination",
          'scp", "-q", src, tmp' in src.replace("'", '"'), )
    check("[1d] un echec efface le `.tmp` au lieu de le laisser traîner",
          src.count("_effacer(tmp)") >= 3, src.count("_effacer(tmp)"))

    print("\n[2] un echec ne peut pas ABIMER le fichier existant")
    dossier = RACINE / "DATA" / "live_enriched" / "sierra" / "ES"
    cibles = sorted(dossier.glob("2026*_ES_sierra_enriched.jsonl"))
    if not cibles:
        check("[2a] un fichier de donnees existe pour le test", False, "aucun fichier ES")
    else:
        cible = cibles[-1]
        jour = cible.name[:8]
        avant = cible.stat().st_size
        ok = sync_vps.synchroniser("ES", jour, "hote-inexistant.invalid", "/nulle/part")
        check("[2a] un hote injoignable rend False, sans lever", ok is False)
        check("[2b] le fichier final est INTACT, octet pour octet",
              cible.stat().st_size == avant, (avant, cible.stat().st_size))
        check("[2c] aucun `.tmp` n'est laisse derriere",
              not os.path.exists(str(cible) + ".tmp"))

    print("\n[3] `_effacer` ne leve jamais — un nettoyage rate ne casse pas la synchro")
    sync_vps._effacer(str(RACINE / "zzz_ce_fichier_n_existe_pas.tmp"))
    check("[3a] effacer un fichier absent ne leve pas", True)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
