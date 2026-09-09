"""Un trou promu bloquant se journalise UNE fois — jamais en double.

Le defaut (audit 09/09, C1 arbitre Fable) : en strict, un trou entrait dans
`bloquantes` ET restait dans `trous` — journalise sous son nom plein PUIS
sous TROU_<nom>. 210/624 lignes du jour 1 en double ; pourquoi.py annoncait
204 blocages L0 pour 99 reels. Ce test compte : par snapshot, un motif ne
peut exister a la fois en TROU_X et en X.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3 import chaine  # noqa: E402

n = 40
df = pd.DataFrame({
    "ts": [1788883200000 + i * 900_000 for i in range(n)],
    "jour": ["20260908"] * n,
    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
    "atr_barre": 2.0, "data_quality_flag": "stable",
    "window_version": "w1", "barre_complete": True,
    "is_news_60m": 0, "is_session_blocked": 0,
    "vix_regime": 1.0, "vix_level": 15.0, "dist_mq_hvl": 40.0,
    "gamma_block_long": 0, "rvol_zscore": 0.5,
})

echecs = 0
with tempfile.TemporaryDirectory() as tmp:
    journal = os.path.join(tmp, "j.jsonl")
    # live={} : age_s, dtc, contrat, l6 = None -> TROUS, promus bloquants en
    # strict. C'est exactement le cas des 624 lignes du jour 1.
    chaine.appliquer([(10, 1), (20, -1)], df, "ES", journal=journal,
                     hypothese="test", strict=True, live={})
    lignes = [json.loads(l) for l in open(journal, encoding="utf-8")]
    par_snap = {}
    for o in lignes:
        base = o["snapshot_id"].rsplit(":", 1)[0]
        par_snap.setdefault(base, []).append(o["motif"])
    doubles = 0
    for base, motifs in par_snap.items():
        trous = {m[5:] for m in motifs if m.startswith("TROU_")}
        pleins = {m for m in motifs if not m.startswith("TROU_")}
        doubles += len(trous & pleins)
    if doubles:
        echecs += 1
        print("  FAIL : %d motif(s) journalises en TROU_ ET en plein" % doubles)
    else:
        print("  PASS : %d lignes, zero motif en double (TROU_ vs plein)"
              % len(lignes))
    # et le comportement bloquant n'a pas change : aucun PASSE (tout est
    # bloque par les trous stricts)
    passes = [o for o in lignes if o.get("decision") == "PASSE"]
    if passes:
        echecs += 1
        print("  FAIL : %d PASSE alors que les trous stricts bloquent"
              % len(passes))
    else:
        print("  PASS : blocage strict intact (0 PASSE)")

print("chaine journal : %s" % ("2 PASS" if not echecs else "%d FAIL" % echecs))
sys.exit(1 if echecs else 0)
