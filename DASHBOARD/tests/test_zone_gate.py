"""Tests PORTE DE LIEU (Jackson 08/09) — « les achats se font aux zones,
pas au milieu de nulle part ».

Valide :
  1. zone_info : niveau le plus proche, distance, seuil par instrument
     (P10 de V3 : ES 6 t / NQ 40 t), en_zone, bar sans prix.
  2. build_conseil_global : un verdict directionnel HORS zone passe
     ATTENDRE avec le motif dans les checks ; EN zone il passe ; sans
     cle `zone` (retro-compat) rien ne change.

Pourquoi : audit du 08/09 — « Breakdown SWING_H » conseille 17 pts sous
la zone, dans un aimant a 10 pts (R:R 0,23 contre 1,7 a la zone). Le
detecteur de cassures exige >= 8 t AU-DELA du niveau : par construction,
un signal d'evenement n'est jamais A la zone.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from DASHBOARD.api.builders import build_conseil_global
from DASHBOARD.api.stabilizers import SEUIL_ZONE_TICKS, zone_info

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


# ─── 1. zone_info ────────────────────────────────────────────────

# NQ : VWAP a 40 t (= seuil 40) -> EN zone ; le VPOC a 120 t ne gagne pas
z = zone_info({"sym": "NQ", "price": 29610.0,
               "dist_vwap_d": -40, "dist_cur_vpoc": -120})
check("nq_en_zone", z["en_zone"] is True and z["niveau"] == "VWAP_D"
      and z["dist_ticks"] == 40 and z["seuil_ticks"] == 40, str(z))

# NQ : plus proche a 60 t > 40 -> HORS zone
z = zone_info({"sym": "NQ", "price": 29610.0,
               "dist_vwap_d": -60, "dist_cur_vpoc": -120})
check("nq_hors_zone", z["en_zone"] is False and z["dist_ticks"] == 60, str(z))

# ES : seuil 6 t — 28 t = hors, 4 t = dedans (calibration PAR instrument)
z = zone_info({"sym": "ES", "price": 7710.0, "dist_cur_vah": 28})
check("es_hors_zone", z["en_zone"] is False and z["seuil_ticks"] == 6, str(z))
z = zone_info({"sym": "ES", "price": 7710.0, "dist_cur_vah": 4})
check("es_en_zone", z["en_zone"] is True and z["dist_ticks"] == 4, str(z))

# bar sans prix / sans niveaux -> jamais en zone, jamais un crash
check("sans_prix", zone_info({"sym": "NQ"})["en_zone"] is False)
check("sans_niveaux", zone_info({"sym": "NQ", "price": 1.0})["en_zone"] is False)
check("seuils_dict", SEUIL_ZONE_TICKS["ES"] == 6 and SEUIL_ZONE_TICKS["NQ"] == 40)

# ─── 2. build_conseil_global — la porte ──────────────────────────

REGIME_BULL = {"bias": "BULLISH", "range_pos": 10, "mtf_bulls": 2,
               "mtf_bears": 0, "mtf_verdict": "BULL 2/4"}
BAR = {"sym": "NQ", "ts": 900000, "delta_day_dir": 1, "rvol": 1.0}

# HORS zone -> le verdict directionnel passe ATTENDRE, motif dans checks
reg = dict(REGIME_BULL)
reg["zone"] = {"en_zone": False, "niveau": "VWAP_D", "prix": 29595.0,
               "dist_ticks": 60, "seuil_ticks": 40}
r = build_conseil_global(dict(BAR), reg, None)
check("gate_attendre", r["action"] == "ATTENDRE", r["action"])
check("gate_motif", any("HORS ZONE" in c for c in r.get("checks", [])),
      str(r.get("checks", []))[-160:])

# EN zone -> le verdict passe (ACHAT, 5 pts bull)
reg = dict(REGIME_BULL)
reg["zone"] = {"en_zone": True, "niveau": "VWAP_D", "prix": 29600.0,
               "dist_ticks": 40, "seuil_ticks": 40}
r = build_conseil_global({"sym": "NQ", "ts": 1800000, "delta_day_dir": 1,
                          "rvol": 1.0}, reg, None)
check("en_zone_passe", r["action"] == "ACHAT", r["action"])

# retro-compat : sans cle zone, rien ne change
r = build_conseil_global({"sym": "ES", "ts": 900000, "delta_day_dir": 1,
                          "rvol": 1.0}, dict(REGIME_BULL), None)
check("retro_compat", r["action"] == "ACHAT", r["action"])

# ─── 3. veto de coherence MTF (cas live 08/09) ───────────────────

# VENTE PRUDENTE (bias BEARISH 2 + delta -1 + range 97% = 4 bear) CONTRE
# un MTF 4/4 BULL -> CONFLIT, jamais une vente contre l'unanimite
reg = {"bias": "BEARISH", "range_pos": 97, "mtf_bulls": 4, "mtf_bears": 0,
       "mtf_verdict": "ACHAT FORT (4/4)"}
r = build_conseil_global({"sym": "NQ", "ts": 2700000, "delta_day_dir": -1,
                          "rvol": 2.1}, reg, None)
check("veto_mtf_bull", r["action"] == "CONFLIT"
      and any("VETO MTF" in c for c in r["checks"]), r["action"])

# miroir : ACHAT PRUDENT contre 4/4 BEAR -> CONFLIT
reg = {"bias": "BULLISH", "range_pos": 10, "mtf_bulls": 0, "mtf_bears": 4,
       "mtf_verdict": "VENTE FORTE (4/4)"}
r = build_conseil_global({"sym": "ES", "ts": 2700000, "delta_day_dir": 1,
                          "rvol": 1.0}, reg, None)
check("veto_mtf_bear", r["action"] == "CONFLIT", r["action"])

# 4/4 n'INVERSE jamais : sans verdict directionnel oppose, pas de veto
reg = {"bias": "NEUTRAL", "range_pos": 50, "mtf_bulls": 4, "mtf_bears": 0,
       "mtf_verdict": "ACHAT FORT (4/4)"}
r = build_conseil_global({"sym": "NQ", "ts": 3600000, "delta_day_dir": 0,
                          "rvol": 1.0}, reg, None)
check("mtf_pas_override", r["action"] in ("ATTENDRE",), r["action"])

# a 2/4 seulement, le verdict directionnel n'est PAS vetoe
reg = {"bias": "BEARISH", "range_pos": 97, "mtf_bulls": 2, "mtf_bears": 0,
       "mtf_verdict": "ACHAT MODERE (2/4)"}
r = build_conseil_global({"sym": "ES", "ts": 3600000, "delta_day_dir": -1,
                          "rvol": 1.0}, reg, None)
check("pas_de_veto_2sur4", r["action"] == "VENTE PRUDENTE", r["action"])

# ─── bilan ───────────────────────────────────────────────────────
print("zone gate : %d PASS, %d FAIL" % (PASSED, FAILED))
for f in FAILURES:
    print("  FAIL:", f)
sys.exit(1 if FAILED else 0)
