"""Brique 4 (Fable 10/09) — L6 avec dénominateurs : ce qui ferme, ce qui informe.

    python -X utf8 V3/tests/test_l6_denominateurs.py

Ce que ça prouve, écrit avant :
  1. `volumetrie_cash` : 390 barres cash stable → OK ; 300 un jour normal →
     ALERTE (intégrité) ; 210 un férié (Labor Day 07/09) → INFO ; un dimanche
     → INFO ; 386 → OK.
  2. `vix_cash_zero` : 0 minute → OK ; 3 et 20 minutes → INFO (sous
     VIX_MORT_MIN) ; 101 minutes (la panne du 08/09) → ALERTE ; 0 barre cash →
     INFO non_mesurable.
  3. `derive_feature` (flag livré `delta_divergence_any` / recalculé, contre SA médiane
     de référence) : ratio 4× la médiane → INFO derive_feature ; ratio dans la
     plage → OK ; moins de 5 jours de référence → INFO ; sans delta_bar → INFO.
  4. `volumetrie` (Globex) incomplète → INFO globex_incomplet, jamais ALERTE.
  5. Un roll ATTENDU par le calendrier (U26 → Z26 le 10/09) → INFO motif
     rollover ; un dimanche sans fichier → chargement INFO.
  Les closers restants (chargement en semaine, continuité, fenêtre, reset,
  valeurs par défaut, volumetrie_cash, vix_cash_zero) sont des atteintes à
  l'intégrité — c'est la taxonomie de Fable (Q4), rendue mécanique.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.research import surveillance_l6 as L6               # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-66s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def jour_1min(date, n_cash, vix_zero=0, div_cpp=0, delta=None, globex=0, contrats=None):
    t0 = pd.Timestamp("%s 13:30" % date, tz="UTC")
    ts = [int((t0 - pd.Timedelta(minutes=globex - k)).value // 1_000_000)
          for k in range(globex)]
    ts += [int((t0 + pd.Timedelta(minutes=k)).value // 1_000_000) for k in range(n_cash)]
    n = len(ts)
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.25, n))
    df = pd.DataFrame({"_ts": ts, "open": close, "high": close + 0.25,
                       "low": close - 0.25, "close": close,
                       "data_quality_flag": "stable",
                       "vix_level": [15.0] * n, "delta_divergence_any": 0})
    df["_dt"] = pd.to_datetime(df["_ts"], unit="ms", utc=True)
    df.loc[globex:globex + vix_zero - 1, "vix_level"] = 0.0
    df.loc[globex:globex + div_cpp - 1, "delta_divergence_any"] = 1
    if delta is not None:
        df["delta_bar"] = delta
    if contrats is not None:
        df["contract"] = contrats
    return df


def main():
    # 1. volumetrie_cash
    r = L6.controle_volumetrie_cash(jour_1min("2026-09-09", 390), "ES", "20260909")
    check("[1a] 390 barres cash stable -> OK", r["etat"] == "OK", r)
    r = L6.controle_volumetrie_cash(jour_1min("2026-09-09", 300), "ES", "20260909")
    check("[1b] 300 barres un jour normal -> ALERTE cash_incomplet (integrite)",
          r["etat"] == "ALERTE" and r["motif"] == "cash_incomplet", r)
    r = L6.controle_volumetrie_cash(jour_1min("2026-09-07", 210), "ES", "20260907")
    check("[1c] 210 barres un FERIE (Labor Day) -> INFO, jamais ALERTE",
          r["etat"] == "INFO" and r["motif"] == "ferie", r)
    r = L6.controle_volumetrie_cash(jour_1min("2026-09-13", 0, globex=60), "ES", "20260913")
    check("[1d] un DIMANCHE -> INFO week_end", r["etat"] == "INFO" and r["motif"] == "week_end", r)
    r = L6.controle_volumetrie_cash(jour_1min("2026-09-09", 386), "ES", "20260909")
    check("[1e] 386 (sous MAX_TROUS_CASH) -> OK", r["etat"] == "OK", r)

    # 2. vix_cash_zero
    r = L6.controle_vix_cash_zero(jour_1min("2026-09-09", 390), "ES", "20260909")
    check("[2a] vix > 0 partout -> OK", r["etat"] == "OK", r)
    for k in (3, 20):
        r = L6.controle_vix_cash_zero(jour_1min("2026-09-09", 390, vix_zero=k), "ES", "20260909")
        check("[2b] %d minutes a 0 -> INFO (sous VIX_MORT_MIN = %d)" % (k, L6.VIX_MORT_MIN),
              r["etat"] == "INFO" and r["minutes_zero"] == k, r)
    r = L6.controle_vix_cash_zero(jour_1min("2026-09-09", 390, vix_zero=101), "ES", "20260909")
    check("[2c] 101 minutes a 0 (la panne du 08/09) -> ALERTE vix_zero",
          r["etat"] == "ALERTE" and r["motif"] == "vix_zero", r)
    r = L6.controle_vix_cash_zero(jour_1min("2026-09-09", 0, globex=30), "ES", "20260909")
    check("[2d] 0 barre cash -> INFO non_mesurable (pas un OK invente)",
          r["etat"] == "INFO" and r["motif"] == "non_mesurable", r)

    # 3. derive_feature : flag livre delta_divergence_any, contre une reference injectee
    rng = np.random.default_rng(3)
    df = jour_1min("2026-09-09", 390, delta=rng.normal(0, 50, 390))
    rec = L6._div_recalc(df, L6._masque_cash(df["_dt"]))
    df.loc[0:rec - 1, "delta_divergence_any"] = 1             # ratio 1
    r = L6.controle_derive_feature(df, "NQ", "20260909", reference=[1.0] * 20)
    check("[3a] ratio 1 contre mediane 1 -> OK (%d recalculees)" % rec,
          rec > 0 and r["etat"] == "OK" and abs(r["ratio"] - 1.0) < 1e-9, r)
    df2 = df.copy()
    df2["delta_divergence_any"] = 0
    df2.loc[0:min(4 * rec, 389) - 1, "delta_divergence_any"] = 1  # ratio ~4
    r = L6.controle_derive_feature(df2, "NQ", "20260909", reference=[1.0] * 20)
    check("[3b] ratio 4x la mediane -> INFO derive_feature, jamais ALERTE",
          r["etat"] == "INFO" and r["motif"] == "derive_feature", r)
    r = L6.controle_derive_feature(df2, "NQ", "20260909", reference=[4.0] * 20)
    check("[3c] le meme ratio 4 contre une mediane 4 -> OK (relatif a SA plage)",
          r["etat"] == "OK", r)
    r = L6.controle_derive_feature(df, "NQ", "20260909", reference=[1.0] * 3)
    check("[3d] moins de 5 jours de reference -> INFO non_mesurable",
          r["etat"] == "INFO" and r["motif"] == "non_mesurable", r)
    r = L6.controle_derive_feature(jour_1min("2026-09-09", 390), "NQ", "20260909",
                                   reference=[1.0] * 20)
    check("[3e] sans delta_bar -> INFO non_mesurable", r["etat"] == "INFO"
          and r["motif"] == "non_mesurable", r)

    # 4. volumetrie Globex incomplete -> INFO
    r = L6.controle_volumetrie(jour_1min("2026-09-09", 390, globex=850), "ES", "20260909")
    check("[4] Globex 1240/1380 (90 %%) -> INFO globex_incomplet, pas ALERTE",
          r["etat"] == "INFO" and r["motif"] == "globex_incomplet", r)

    # 5. roll attendu et dimanche
    ct = ["ESU26-CME"] * 200 + ["ESZ26-CME"] * 190
    r = L6.controle_rollover(jour_1min("2026-09-10", 390, contrats=ct), "ES", "20260910")
    check("[5a] bascule U26 -> Z26 en seance le 10/09 (attendue) -> INFO motif rollover",
          r["etat"] == "INFO" and r["motif"] == "rollover", r)
    ct = ["ESU26-CME"] * 200 + ["ESH27-CME"] * 190
    r = L6.controle_rollover(jour_1min("2026-09-10", 390, contrats=ct), "ES", "20260910")
    check("[5b] bascule vers un contrat NON attendu (H27) -> ALERTE", r["etat"] == "ALERTE", r)
    r = L6.surveiller("ES", "20260913", [])
    check("[5c] dimanche 13/09 sans fichier -> chargement INFO week_end",
          r and r[0]["controle"] == "chargement" and r[0]["etat"] == "INFO", r)

    # 6. reset_vwap (10/09 soir) : un RESET pose le VWAP sur le prix ; un gros saut qui
    # laisse le VWAP loin du prix est un deplacement (premiere minute d'un gap), pas un reset
    def jour_vwap(h_saut, repose):
        ts = pd.date_range("2026-09-09 20:00", periods=1380, freq="min", tz="UTC")   # le reset de 21h n'est pas la 1re barre
        close = pd.Series(np.linspace(29000, 29100, 1380))
        v = (close - 150.0).copy()               # VWAP loin du prix toute la nuit
        i = int(((ts.hour == h_saut) & (ts.minute == 0)).argmax())
        v.iloc[i:] = (close.iloc[i:] - 0.5) if repose else (v.iloc[i:] - 8.0)
        return pd.DataFrame({"ts": (ts.asi8 // 10**6), "close": close, "vwap_d": v, "_dt": ts})
    r = L6.controle_reset_vwap(jour_vwap(21, True), "NQ", "20260910")
    check("[6a] reset a 21h UTC (le VWAP se pose sur le prix) -> OK", r["etat"] == "OK", r)
    r = L6.controle_reset_vwap(jour_vwap(13, True), "NQ", "20260910")
    check("[6b] reset a 13h UTC (pose sur le prix, mauvaise heure) -> ALERTE", r["etat"] == "ALERTE", r)
    r = L6.controle_reset_vwap(jour_vwap(13, False), "NQ", "20260910")
    check("[6c] saut de 8 pts a 13h qui LAISSE le VWAP a 150 pts du prix -> INFO deplacement, pas un reset (NQ 10/09)",
          r["etat"] == "INFO" and "sans reset" in r["message"], r)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
