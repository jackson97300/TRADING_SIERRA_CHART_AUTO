"""Les quatre gardes de `marges.py`, exigées avant push (brief Fable 09/09).

1. IDEMPOTENCE — deux runs rendent le MÊME fichier (hash). La parade au
   doublement silencieux du N : un journal appendé deux fois fausserait le
   dénominateur, et personne ne le verrait à N=360.
2. INVARIANT D'UNITÉ — `ts` hors [1,5e12 ; 3e12] fait ÉCHOUER le run en
   nommant l'unité. Reproduit sous pandas 2 en forçant l'index en `ms` :
   c'est le bug du 08/09 (pandas 3 sur le VPS → toute la chaîne datée de
   1970), et il ne doit jamais revenir en silence.
3. LE DÉNOMINATEUR — une ligne `setup_jour` par setup × instrument, ÉCRITE
   MÊME À ZÉRO, avec son motif. Sans elle, « rien tiré » et « le setup n'a
   pas tourné » sont indiscernables.
4. SIGNATURE — une clé `_extra` disparue fait crier, jamais des marges à
   `null` prises pour un marché calme.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.features import recalc          # noqa: E402
from V3 import marges                     # noqa: E402

JOUR = "20260908"
PASSED = 0
FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("  %-34s PASS %s" % (nom, detail))
    else:
        FAILED += 1
        print("  %-34s FAIL %s" % (nom, detail))


def _hash(chemin):
    return hashlib.sha256(open(chemin, "rb").read()).hexdigest()


chemin = os.path.join(marges.DOSSIER, "marges_%s.jsonl" % JOUR)

# 1. idempotence
marges.courir(JOUR)
h1 = _hash(chemin)
marges.courir(JOUR)
check("idempotence (2 runs, meme hash)", h1 == _hash(chemin), h1[:12])

lignes = [json.loads(l) for l in open(chemin, encoding="utf-8")]
tete = lignes[0]
sj = [o for o in lignes if o["type"] == "setup_jour"]
mg = [o for o in lignes if o["type"] == "marge"]

# 2. invariant d'unite — l'ancien code rendait des mega-secondes sous pandas 3
for valeur, attendu in ((1788883200, "secondes"), (1788883, "mega-secondes")):
    try:
        recalc.ts_plage(pd.Series([float(valeur)]))
        check("invariant ts %s" % attendu, False, "aurait du lever")
    except ValueError as e:
        check("invariant ts %s" % attendu, attendu in str(e))

# 3. LE DENOMINATEUR : une ligne par setup x instrument, meme a zero
attendu_n = len(marges.ACTIFS) * 2
check("denominateur complet", len(sj) == attendu_n,
      "%d lignes pour %d setups x 2" % (len(sj), len(marges.ACTIFS)))
check("zero marge => motif ecrit",
      all(o["motif_muet"] for o in sj if o["n_marges"] == 0),
      "%d a zero" % sum(1 for o in sj if o["n_marges"] == 0))
check("date_ombre sur chaque ligne",
      all(o.get("date_ombre") for o in sj))

# 4. la ligne rouge : AUCUN champ de devenir, jamais
INTERDITS = ("pnl", "gain", "mae", "mfe", "devenir", "issue", "prix_sortie",
             "prix_entree", "stop", "sl", "tp", "r_multiple")
fuite = sorted({c for o in lignes for c in o
                if any(m == c or c.startswith(m + "_") for m in INTERDITS)})
check("aucun champ de devenir", not fuite, str(fuite))
check("avertissement en ligne 1",
      "INTERDIT" in tete.get("avertissement", "") and tete["type"] == "entete")
check("grille de tranches dans l entete",
      len(tete.get("tranches_declarees", [])) == len(marges.TRANCHES))
check("env journalise (lecon 08/09)",
      "pandas" in tete.get("env", {}), str(tete.get("env")))

# 5. les marges portent leur unite et leur source de seuil
check("marge : unite + seuil_source",
      all(o.get("unite") and o.get("seuil_source") for o in mg),
      "%d marges" % len(mg))
# tolerance 5e-4 et non 1e-6 : `marge` et `marge_rel` sont deux arrondis
# INDEPENDANTS de la meme grandeur (4 decimales chacun). Sur un seuil de
# 0,27 l'ecart d'arrondi atteint 1,9e-4 — l'exiger a 1e-6 testerait la
# virgule flottante, pas la coherence.
check("marge_rel coherent avec marge",
      all(abs(o["marge_rel"] - o["marge"] / o["seuil_natif"]) < 5e-4
          for o in mg if o.get("seuil_natif")),
      "tolerance d arrondi 5e-4")

print("marges : %d PASS, %d FAIL" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
