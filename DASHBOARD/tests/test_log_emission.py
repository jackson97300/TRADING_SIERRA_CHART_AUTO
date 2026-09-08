"""Le test qui manquait depuis 3 mois : une EMISSION reelle, pas un verdict.

Le bug (audit 08/09) : `from CORE import logging_v2 as _v2log` puis
`_v2log.emit(...)` — le module n'a pas de emit() module-level, chaque appel
levait AttributeError, avalee par les try/except des sites. ZERO emission
depuis le 08/06 : les audits J+7 des fixes BUG#1/#4 n'ont jamais eu de
donnees. test_zone_gate valide les VERDICTS ; celui-ci asserte qu'une
ligne de log EXISTE.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

PASSED = 0
FAILED = 0
FAILURES = []


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
    else:
        FAILED += 1
        FAILURES.append("%s %s" % (name, detail))


# 1. les modules dashboard portent un VRAI logger (pas le module nu)
from DASHBOARD.api import builders, stabilizers  # noqa: E402

check("builders_logger", builders._v2log is not None
      and callable(getattr(builders._v2log, "emit", None)),
      str(type(builders._v2log)))
check("stabilizers_logger", stabilizers._v2log is not None
      and callable(getattr(stabilizers._v2log, "emit", None)),
      str(type(stabilizers._v2log)))

# 2. une emission ECRIT une ligne (cwd temporaire — LOG_BASE_DIR relatif)
ancien = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    try:
        # _ensure_directories() ne tourne qu'a l'IMPORT du module — dans un
        # cwd vierge il faut creer les dossiers (en prod, le cwd du service
        # les a deja). MAJEUR ecrit aussi une copie dans errors/.
        os.makedirs("LOGS/decisions", exist_ok=True)
        os.makedirs("LOGS/errors", exist_ok=True)
        from CORE.logging_v2 import get_logger
        lg = get_logger("test_emission", process="dashboard_test")
        lg.emit("CONSEIL_ZONE_GATE_BLOCK", sym="NQ", action="VENTE PRUDENTE",
                niveau="VWAP_D", dist_ticks=60, seuil_ticks=40)
        fichiers = list(Path(tmp).glob("LOGS/decisions/decisions_*.jsonl"))
        check("fichier_cree", len(fichiers) >= 1,
              "aucun decisions_*.jsonl sous %s" % tmp)
        if fichiers:
            contenu = fichiers[0].read_text(encoding="utf-8")
            check("code_present", "CONSEIL_ZONE_GATE_BLOCK" in contenu,
                  contenu[:120])
    finally:
        os.chdir(ancien)

print("log emission : %d PASS, %d FAIL" % (PASSED, FAILED))
for f in FAILURES:
    print("  FAIL:", f)
sys.exit(1 if FAILED else 0)
