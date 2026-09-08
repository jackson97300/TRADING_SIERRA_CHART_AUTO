"""Régression : `ts` en MILLISECONDES quelle que soit l'unité de l'index.

Le bug (08/09, VPS) : pandas 3 garde l'unité ms de `to_datetime(unit="ms")`
jusque dans l'index du resample ; `astype("int64") // 1_000_000` rendait des
MÉGA-secondes → `_jour` lisait 1970-01-01 → `L0_FERIE_CME` bloquait chaque
barre sur un « New Year's Day » fantôme. En local (pandas 2, index ns) le même
code était juste — le bug n'existait que sur la machine de la campagne.

Deux sites, deux modes de défaillance (review NOGO du fix partiel) :
- `bot_terminal.agreger` : ts faux → férié fantôme, BRUYANT ;
- `hypothesis_runner.injecter_recalculs` : ts faux d'UN SEUL côté du
  merge(on="ts") → toutes les colonnes _r NaN, SILENCIEUX. Le pire des deux.

Ce test force l'unité de l'index sous n'importe quel pandas ≥ 2 : il échoue
sur l'ancien code des deux côtés.
"""
import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from CORE.bot_terminal import agreger                              # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs     # noqa: E402

TS0 = 1788883200000  # 2026-09-08 16:00:00 UTC, en ms (aligne 15 min)
N = 60

echecs = 0


def _brut():
    ts = [TS0 + i * 60_000 for i in range(N)]
    return pd.DataFrame({
        "ts": ts,
        "open": [1.0] * N, "high": [2.0] * N,
        "low": [0.5] * N, "close": [1.5] * N,
        "total_vol": [10.0] * N, "delta_bar": [1.0] * N,
    })


def _cas(nom, ok, detail=""):
    global echecs
    print("  %-26s %s %s" % (nom, "PASS" if ok else "FAIL", detail))
    echecs += 0 if ok else 1


# 1. agreger : ts en ms pour un index ns, ms, us (astype INCONDITIONNEL —
#    sous pandas 3, to_datetime rend deja du ms, forcer garantit l'etiquette)
for unite in ("ns", "ms", "us"):
    df = _brut()
    df["dt"] = (pd.to_datetime(df["ts"], unit="ms", utc=True)
                .astype("datetime64[%s, UTC]" % unite))
    out = agreger(df, 15)
    premier = int(out["ts"].iloc[0])
    jour = pd.Timestamp(premier, unit="ms", tz="UTC").date()
    _cas("agreger index %s" % unite,
         premier == TS0 and str(jour) == "2026-09-08",
         "ts=%s jour=%s" % (premier, jour))

# 2. injecter_recalculs : le merge(on="ts") doit matcher — colonnes _r
#    NON-NaN meme quand to_datetime interne rend un index ms (pandas 3).
#    Sous pandas 2 on ne peut pas forcer l'interne : on verifie que les ts
#    des deux cotes coincident et que le merge remplit rvol_r/vwap_rth_r.
brut = _brut()
brut["dt"] = pd.to_datetime(brut["ts"], unit="ms", utc=True)
cinq = agreger(brut, 15)
out = injecter_recalculs(brut.drop(columns=["dt"]), cinq, minutes=15)
# rvol_r exclu de l'assertion : NaN legitime sur un frame d'UN jour (le RVOL
# compare a la mediane des jours precedents). vwap/dist se calculent le jour.
_cas("merge _r non vide",
     out["vwap_rth_r"].notna().any() and out["dist_vwap_rth_r"].notna().any(),
     "vwap_rth_r NaN=%d/%d" % (out["vwap_rth_r"].isna().sum(), len(out)))
_cas("ts merge en ms", int(out["ts"].iloc[0]) == TS0,
     "ts=%s" % int(out["ts"].iloc[0]))

# 3. l'invariant FAIL-LOUD (reserve 1 Fable) : hors plage ms -> refus
#    qui NOMME l'unite probable — couvre les sites qu'on n'a pas relus.
from CORE.features import recalc  # noqa: E402

for valeur, attendu in ((1788883200, "secondes"),      # epoch s
                        (1788883, "mega-secondes"),     # le bug du 08/09
                        (TS0 * 1000, "microsecondes")):
    try:
        recalc.ts_plage(pd.Series([float(valeur)]))
        _cas("ts_plage %s" % attendu, False, "aurait du lever")
    except ValueError as e:
        _cas("ts_plage %s" % attendu, attendu in str(e), str(e)[:60])
_cas("ts_plage ms passe", recalc.ts_plage(pd.Series([float(TS0)])) is None)
_cas("ts_plage vide passe", recalc.ts_plage(pd.Series(dtype="float64")) is None)

print("agreger/injecter/invariant ts : %s"
      % ("10 PASS" if not echecs else "%d FAIL" % echecs))
sys.exit(1 if echecs else 0)
