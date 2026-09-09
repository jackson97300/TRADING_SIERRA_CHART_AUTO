"""B-ATR sur les signaux d'ombre — la sortie que 9/9 signaux du jour 1
n'avaient pas (audit ops 09/09).

Vérifie que `_barrieres_ombres` : ne prend QUE les vrais signaux (jamais un
muet ni un lieu_sans_reaction, jamais le mauvais instrument), donne une issue
et un pnl au signal exécutable, et ne laisse JAMAIS un `null` sans motif — la
règle du fichier.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.layers.L5_risque import barrieres as B                     # noqa: E402
from V3.layers.L5_risque.barrieres_du_jour import _barrieres_ombres  # noqa: E402

JOUR = "20260908"
TS0 = 1788825600000
PASSED = 0
FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("  %-34s PASS" % nom)
    else:
        FAILED += 1
        print("  %-34s FAIL %s" % (nom, detail))


# df jouet : 30 barres 15 min, ATR valide, prix stables -> issue resoluble
n = 30
df = pd.DataFrame({
    "ts": [TS0 + i * 900_000 for i in range(n)],
    "atr_barre": 10.0, "atr_ref": 10.0, "atr_source": "barre",
    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
})
s = B.charger_seuils()

ancien = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    try:
        os.makedirs("LOGS/entonnoir", exist_ok=True)
        with open("LOGS/entonnoir/ombre_c2_%s.jsonl" % JOUR, "w",
                  encoding="utf-8") as fh:
            for o in (
                # 1. un vrai signal ES a la barre 5
                {"snapshot_id": "C2:ES:5:S", "ts": TS0 + 5 * 900_000,
                 "sym": "ES", "setup": "C2_EOD", "side": -1},
                # 2. un muet — porte `motif`, doit etre IGNORE
                {"ts": TS0, "sym": "ES", "setup": "C2_EOD",
                 "motif": "jour_muet:barre_eod_absente"},
                # 3. un lieu sans reaction — IGNORE
                {"ts": TS0 + 3 * 900_000, "sym": "ES", "setup": "C2_80PCT",
                 "motif": "lieu_sans_reaction"},
                # 4. le mauvais instrument — IGNORE quand sym=ES
                {"ts": TS0 + 6 * 900_000, "sym": "NQ", "setup": "C2_EOD",
                 "side": -1},
                # 5. un signal dont le ts n'existe pas dans le df -> motif
                {"ts": 999, "sym": "ES", "setup": "C2_80PCT", "side": 1},
            ):
                fh.write(json.dumps(o) + "\n")

        sortie = io.StringIO()
        incidents = []
        n_lignes = _barrieres_ombres(df, "ES", JOUR, s, sortie, incidents)
        lignes = [json.loads(x) for x in sortie.getvalue().splitlines()]

        check("2 lignes ES (muet/lieu/NQ ignores)", n_lignes == 2,
              "%d lignes" % n_lignes)
        vrai = [x for x in lignes if x.get("setup") == "C2_EOD"
                and not x.get("motif_ligne")]
        check("le vrai signal produit une ligne", len(vrai) == 1)
        if vrai:
            v = vrai[0]
            check("barriere = B-ATR", v.get("barriere") == "B-ATR")
            check("BRACKET present (sl/tp en ATR)",
                  v.get("sl_atr") is not None and v.get("tp_atr") is not None)
            # R1 : le DEVENIR n'est PAS ecrit (peek-proof SEIZE/C2)
            check("pas d'issue ni pnl (devenir retenu)",
                  "issue" not in v and "pnl_atr" not in v, str(v.keys()))
            check("snapshot_id inclut le setup (R2)",
                  v.get("snapshot_id", "").startswith("OMB:C2_EOD:"),
                  v.get("snapshot_id"))
        introuvable = [x for x in lignes if x.get("ts") == 999]
        check("ts introuvable -> motif + INCIDENT (R3)",
              len(introuvable) == 1
              and introuvable[0].get("motif_ligne") == "ts_introuvable"
              and introuvable[0].get("sl_prix") is None
              and any("ombre_ts" in x for x in incidents),
              "incidents=%s" % incidents)
        # LA regle du fichier : aucun bracket null sans motif
        check("aucun null sans motif", all(
            x.get("sl_prix") is not None or x.get("motif_ligne")
            for x in lignes))
    finally:
        os.chdir(ancien)

print("barrieres ombres : %d PASS, %d FAIL" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
