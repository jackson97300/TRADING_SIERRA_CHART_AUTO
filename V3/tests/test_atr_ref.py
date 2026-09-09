"""Brique 1 (Fable 09/09) — `atr_ref` : le METRE des lieux, pas la regle.

    python -X utf8 V3/tests/test_atr_ref.py

Ce que ca prouve, ecrit avant :
  1. `atr_veille_15` lit la DERNIERE SESSION COMPLETE, pas la derniere
     session : apres un jour tronque, la veille utile est celle d'avant ;
     NaN sans session complete avant.
  2. Sur une journee REELLE : `atr_veille` est CONSTANT dans la journee (fige
     a 9h30), `atr_ref == atr_barre` partout ou celui-ci est fini, et
     `atr_source = veille` UNIQUEMENT sur des barres avant 11h00 ET.
  3. `seuil_ticks` : NaN reste NaN (le plancher ne sauve pas — la regle ne
     change pas) ; `h3` avec atr_barre NaN mais atr_ref fini evalue son lieu ;
     sans colonne `atr_ref` -> KeyError (fail-loud, jamais un silence).
  4. L6 `controle_echelle_atr` : gap >= 2 ATR-veille -> ALERTE
     echelle_douteuse ; gap 0,5 -> OK ; sans session complete -> INFO.
  5. `barrieres.issue` normalise par atr_ref : atr_barre NaN + atr_ref fini
     -> une issue, pas None.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402
from CORE.research import hypotheses as H                     # noqa: E402
from CORE.research import surveillance_l6 as L6               # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min             # noqa: E402
from V3.layers.L5_risque import barrieres as B                # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-46s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def jour_1min(date, n_min, amp, close=100.0, open_=None):
    """`n_min` barres 1 min depuis 9h30 ET (EDT = 13:30 UTC). TR d'une barre
    15 min = 2*amp (high-low), close constant."""
    t0 = pd.Timestamp("%s 13:30" % date, tz="UTC")
    ts = [int((t0 + pd.Timedelta(minutes=k)).value // 1_000_000) for k in range(n_min)]
    return pd.DataFrame({"ts": ts, "open": open_ if open_ is not None else close,
                         "high": close + amp, "low": close - amp, "close": close})


def frame_l6(df):
    """Le frame tel que `surveillance_l6.charger_jour` le rend."""
    out = df.copy()
    out["_ts"] = out["ts"]
    out["_dt"] = pd.to_datetime(out["_ts"], unit="ms", utc=True)
    return out


def main():
    # 1. derniere session COMPLETE
    a = jour_1min("2026-09-01", 390, 1.0)      # ATR 2, complete
    b = jour_1min("2026-09-02", 200, 5.0)      # ATR 10, TRONQUEE (14 barres < 26)
    c = jour_1min("2026-09-03", 390, 3.0)      # ATR 6, complete
    tout = pd.concat([a, b, c], ignore_index=True)
    dt = pd.to_datetime(tout["ts"], unit="ms", utc=True)
    v = recalc.atr_veille_15(tout, dt, minutes=15)
    d = {str(k): x for k, x in v.items()}
    check("[1a] premiere date : aucune veille -> NaN", np.isnan(d["2026-09-01"]), d)
    check("[1b] veille du jour tronque = la complete (2)",
          abs(d["2026-09-02"] - 2.0) < 1e-9, d)
    check("[1c] lendemain du tronque : SAUTE le tronque (2, pas 10)",
          abs(d["2026-09-03"] - 2.0) < 1e-9, d)
    b_ok = jour_1min("2026-09-02", 390, 5.0)
    tout2 = pd.concat([a, b_ok, c], ignore_index=True)
    v2 = recalc.atr_veille_15(tout2, pd.to_datetime(tout2["ts"], unit="ms",
                                                    utc=True), minutes=15)
    check("[1d] le meme jour COMPLET est pris (10)",
          abs(float(v2.iloc[-1]) - 10.0) < 1e-9, list(v2))
    # Fable Q7 : une session a DEUX contrats n'est pas complete (definition)
    b_roll = b_ok.assign(contract=["ESU26-CME"] * 200 + ["ESZ26-CME"] * 190)
    tout3 = pd.concat([a.assign(contract="ESU26-CME"), b_roll,
                       c.assign(contract="ESZ26-CME")], ignore_index=True)
    v3 = recalc.atr_veille_15(tout3, pd.to_datetime(tout3["ts"], unit="ms",
                                                    utc=True), minutes=15)
    check("[1e] session a deux contrats (bascule en seance) -> pas complete, sautee (2, pas 10)",
          abs(float(v3.iloc[-1]) - 2.0) < 1e-9, list(v3))

    # 2. journee reelle : fige a 9h30, atr_ref == atr_barre, veille avant 11h
    jour, sym = "20260903", "NQ"
    df, brut = charger_jour(sym, jour, 15, avec_1min=True)
    if df.empty:
        check("[2] journee %s indisponible" % jour, False)
    else:
        agg = injecter_recalculs(pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                                           ignore_index=True), df, minutes=15)
        mn = recalc.minutes_et(pd.to_datetime(agg["ts"], unit="ms", utc=True))
        fini = agg["atr_barre"].notna()
        check("[2a] atr_veille CONSTANT dans la journee (fige a 9h30)",
              agg["atr_veille"].nunique(dropna=False) == 1)
        check("[2b] atr_ref == atr_barre partout ou atr_barre est fini",
              bool((agg.loc[fini, "atr_ref"] == agg.loc[fini, "atr_barre"]).all()))
        veille = agg["atr_source"] == "veille"
        check("[2c] atr_source=veille EXACTEMENT sur les barres sans atr_barre",
              bool((veille == ~fini).all()) and int(veille.sum()) == 6,
              int(veille.sum()))
        check("[2d] toutes les barres `veille` sont avant 11h00 ET",
              bool((mn[veille] < 660).all()))
        check("[2e] aucune barre `aucun` (une session complete precede)",
              int((agg["atr_source"] == "aucun").sum()) == 0)
        check("[2f] les colonnes L5 requises sont la (atr_ref, atr_source)",
              {"atr_ref", "atr_source"} <= set(agg.columns))

    # 3. seuil_ticks / h3 : le metre, pas la regle
    s = H.seuil_ticks(pd.Series([np.nan, 10.0]), "P10")
    check("[3a] seuil_ticks : NaN reste NaN (le plancher ne sauve pas)",
          np.isnan(s.iloc[0]) and abs(s.iloc[1] - 4.0) < 1e-9, list(s))
    base = {"ts": [1], "jour": ["j"], "close": [100.0], "high": [100.5], "low": [99.9],
            "dist_cur_vah": [1.0], "dist_cur_val": [100.0],
            "finish_delta_pct": [0.2], "atr_barre": [np.nan]}
    lieu = H.h3(pd.DataFrame(dict(base, atr_ref=[10.0])))["short"][0]
    check("[3b] h3 : atr_barre NaN + atr_ref fini -> le lieu s'evalue (short)",
          bool(lieu.iloc[0]))
    muet = H.h3(pd.DataFrame(dict(base, atr_ref=[np.nan])))["short"][0]
    check("[3c] h3 : atr_ref NaN -> pas de lieu (aucune session avant)",
          not bool(muet.iloc[0]))
    try:
        H.h3(pd.DataFrame(base))
        check("[3d] h3 sans colonne atr_ref -> KeyError (fail-loud)", False)
    except KeyError:
        check("[3d] h3 sans colonne atr_ref -> KeyError (fail-loud)", True)

    # 4. L6 echelle_atr : JAMAIS ALERTE (couplage L0_DATA_L6_ALERTE), motifs
    veille = frame_l6(jour_1min("2026-09-08", 390, 1.0))          # ATR 2, close 100
    gap6 = frame_l6(jour_1min("2026-09-09", 390, 1.0, close=112.0))   # gap 12 = 6 ATR
    petit = frame_l6(jour_1min("2026-09-09", 390, 1.0, close=101.0))  # 0,5 ATR
    tronq = frame_l6(jour_1min("2026-09-08", 200, 1.0))
    vieille = frame_l6(jour_1min("2026-09-04", 390, 1.0))
    cas = {
        "4a": L6.controle_echelle_atr(gap6, "ES", "20260909", veilles=[veille]),
        "4b": L6.controle_echelle_atr(petit, "ES", "20260909", veilles=[veille]),
        "4c": L6.controle_echelle_atr(petit, "ES", "20260909", veilles=[]),
        "4d": L6.controle_echelle_atr(gap6, "ES", "20260909", veilles=[tronq]),
        "4e": L6.controle_echelle_atr(gap6.assign(contract="ESZ26-CME"), "ES", "20260910",
                                      veilles=[veille.assign(contract="ESU26-CME")]),
        "4f": L6.controle_echelle_atr(gap6, "ES", "20260909", veilles=[vieille, tronq]),
        "4h": L6.controle_echelle_atr(gap6, "NQ", "20260909", veilles=[veille]),
    }
    r = cas["4a"]
    check("[4a] ES gap 6 ATR-veille (>= p90 5,81) -> INFO motif=echelle_douteuse",
          r["etat"] == "INFO" and r.get("motif") == "echelle_douteuse"
          and abs(r["gap_atr"] - 6.0) < 1e-6, r)
    r = cas["4h"]
    check("[4h] NQ meme gap 6 (< p90 6,69) -> OK : seuil PAR INSTRUMENT",
          r["etat"] == "OK" and r.get("motif") is None, r)
    r = cas["4b"]
    check("[4b] gap 0,5 ATR-veille -> OK, sans motif",
          r["etat"] == "OK" and r.get("motif") is None, r)
    r = cas["4c"]
    check("[4c] sans session complete avant -> INFO (jamais un silence)",
          r["etat"] == "INFO" and r.get("atr_veille") is None, r)
    r = cas["4d"]
    check("[4d] veille TRONQUEE seule -> INFO (pas de metre)", r["etat"] == "INFO", r)
    r = cas["4e"]
    check("[4e] changement de contrat -> INFO motif=rollover (gap de base)",
          r["etat"] == "INFO" and r.get("motif") == "rollover", r)
    r = cas["4f"]
    check("[4f] veille presente TRONQUEE, complete avant -> INFO veille_incomplete",
          r["etat"] == "INFO" and r.get("motif") == "veille_incomplete"
          and r.get("atr_veille") == 2.0, r)
    check("[4g] AUCUN cas n'est ALERTE (une ALERTE fermerait la journee live suivante)",
          all(x["etat"] != "ALERTE" for x in cas.values()))

    # 5. barrieres.issue normalise par atr_ref
    dfb = pd.DataFrame({"ts": [1, 2, 3, 4], "open": 100.0, "high": 101.0,
                        "low": 99.0, "close": 100.0, "atr_barre": np.nan,
                        "atr_ref": 10.0, "atr_source": "veille"})
    r = B.issue(dfb, 0, +1, 95.0, 101.0, "ES")
    check("[5] issue : atr_barre NaN + atr_ref fini -> TP, pas None",
          r is not None and r[0] == "TP", r)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
