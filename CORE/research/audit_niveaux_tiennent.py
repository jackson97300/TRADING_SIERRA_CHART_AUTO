"""Qu'est-ce qui fait qu'un niveau TIENT et qu'un autre CASSE ?

Question posee par Jackson le 04/09 : "pas juste etre sur le put support, mais
le put support DEFENDU". Ce script cherche la difference mesurable entre les
deux, sur donnees reelles.

PRINCIPE
--------
On ne teste pas une strategie. On compare deux POPULATIONS :
  - les tests de niveau ou le niveau a TENU
  - les tests de niveau ou le niveau a CASSE
et on regarde quelles conditions d'order flow different au MOMENT du test.

C'est une analyse descriptive, pas une recherche d'edge. Aucune conclusion
"voici la regle" ne doit en sortir directement : ce qui en sort, ce sont des
CANDIDATS a tester ensuite en walk-forward.

DEFINITIONS (fixees a priori)
-----------------------------
Un niveau est une ZONE, pas un prix (Jackson) : tolerance en ticks autour.

Evenement de test : le prix entre dans la zone (|dist| <= TOLERANCE).
  Sens deduit du prix LOOKBACK barres avant :
    prix avant > niveau  -> test par le haut  -> SUPPORT
    prix avant < niveau  -> test par le bas   -> RESISTANCE

Issue, observee sur les FENETRE barres suivantes, premiere atteinte :
  TIENT  : le prix s'eloigne de +REBOND ticks du bon cote
  CASSE  : le prix traverse de -CASSURE ticks du mauvais cote
  INDECIS: ni l'un ni l'autre dans la fenetre (exclu de la comparaison)

ANTI-BIAIS
----------
  - cooldown : un meme niveau ne peut pas generer 50 evenements d'affilee
    tant que le prix reste dans la zone
  - l'observation demarre a la barre i+1 (jamais la barre du test)
  - les conditions d'order flow sont lues sur la barre du test uniquement
    (aucune information posterieure)

Usage :
    python -X utf8 CORE/research/audit_niveaux_tiennent.py --symbols ES
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict

# ─── Parametres fixes A PRIORI (jamais ajustes sur les resultats) ───
# Un niveau est une zone : tolerance ~1 point ES / ~2,5 points NQ.
TOLERANCE = {"ES": 4, "NQ": 16}
# Rebond significatif = 1 SL (ES 20t = 5 pts, NQ 80t = 20 pts).
REBOND = {"ES": 20, "NQ": 80}
# Cassure = traversee nette, ~2 points ES / 5 points NQ.
CASSURE = {"ES": 8, "NQ": 32}
FENETRE = 30      # barres d'observation apres le test
LOOKBACK = 5      # barres pour determiner le sens d'approche
COOLDOWN = 15     # barres avant qu'un meme niveau puisse re-declencher

# Zones testees, groupees par famille.
ZONES = {
    "VPOC_jour": "dist_cur_vpoc",
    "VAH_jour": "dist_cur_vah",
    "VAL_jour": "dist_cur_val",
    "VPOC_veille": "dist_prev_vpoc",
    "VAH_veille": "dist_prev_vah",
    "VAL_veille": "dist_prev_val",
    "PDH": "dist_pdh",
    "PDL": "dist_pdl",
    "VWAP_jour": "dist_vwap_d",
    "VWAP_SD1u": "dist_vwap_d_sd1u",
    "VWAP_SD1d": "dist_vwap_d_sd1d",
    "IB_high": "dist_ib_high",
    "IB_low": "dist_ib_low",
    "OVN_high": "dist_ovn_high",
    "OVN_low": "dist_ovn_low",
    "MQ_call": "dist_mq_call",
    "MQ_put": "dist_mq_put",
    "MQ_hvl": "dist_mq_hvl",
}

# Conditions d'order flow mesurees au moment du test.
# UNIQUEMENT des features verifiees VIVANTES le 04/09 (audit exhaustif).
# NOTE 04/09 : `n_big_ask_v2_t1` / `n_big_bid_v2_t1` sont PLAFONNES a 20
# (tableau C++ `bn_ask100[20]`, DMP_Reader.h:445). 33,6 % des barres tapent le
# plafond => la mediane vaut 20 dans les deux groupes => aveugle exactement la
# ou on veut discriminer. On les garde pour l'analyse par palier (voir plus
# bas) mais on ne s'en sert PAS comme mesure d'intensite : on utilise les
# VOLUMES, non plafonnes (max_big_ask_vol_in_bar : max 3487, 0 % au plafond).
CONDITIONS = [
    "max_big_ask_vol_in_bar",
    "max_big_bid_vol_in_bar",
    "delta_bar",
    "aggressor_imbalance",
    "ctx_absorption_streak_5",
    "bn_absorb_ask",
    "bn_absorb_bid",
    "delta_divergence",
    "retest_high_count",
    "retest_low_count",
    "rvol",
    "volume",
    "vix_level",
]


def charger(sym: str, racine: str, jours: int) -> list[dict]:
    barres = []
    fichiers = sorted(glob.glob(os.path.join(racine, sym, "2026*_sierra_enriched.jsonl")))
    for f in fichiers[-jours:]:
        for l in open(f, "r", encoding="utf-8", errors="replace"):
            l = l.strip()
            if l:
                barres.append(json.loads(l))
    barres.sort(key=lambda b: b.get("ts", 0))
    return barres


def _f(bar: dict, cle: str):
    v = bar.get(cle)
    if isinstance(v, bool):
        return float(v)
    return float(v) if isinstance(v, (int, float)) else None


def analyser(barres: list[dict], sym: str) -> list[dict]:
    """Retourne un evenement par test de niveau, avec son issue et son contexte."""
    tol, reb, cas = TOLERANCE[sym], REBOND[sym], CASSURE[sym]
    tick = 0.25
    evenements: list[dict] = []
    dernier_test: dict[str, int] = {}
    n = len(barres)

    for i in range(LOOKBACK, n - FENETRE - 1):
        bar = barres[i]
        prix = _f(bar, "close")
        if prix is None:
            continue

        for nom, cle in ZONES.items():
            d = _f(bar, cle)
            if d is None or abs(d) > tol:
                continue
            if i - dernier_test.get(nom, -10**9) < COOLDOWN:
                continue

            niveau = prix + d * tick
            prix_avant = _f(barres[i - LOOKBACK], "close")
            if prix_avant is None or abs(prix_avant - niveau) < tol * tick:
                continue  # approche ambigue : on ne tranche pas

            support = prix_avant > niveau
            dernier_test[nom] = i

            # Observation : premiere barriere atteinte, a partir de i+1
            issue = "INDECIS"
            for j in range(i + 1, min(i + 1 + FENETRE, n)):
                h, b_ = _f(barres[j], "high"), _f(barres[j], "low")
                if h is None or b_ is None:
                    continue
                if support:
                    if b_ <= niveau - cas * tick:
                        issue = "CASSE"
                        break
                    if h >= niveau + reb * tick:
                        issue = "TIENT"
                        break
                else:
                    if h >= niveau + cas * tick:
                        issue = "CASSE"
                        break
                    if b_ <= niveau - reb * tick:
                        issue = "TIENT"
                        break

            if issue == "INDECIS":
                continue

            # Contexte au moment du test (aucune info posterieure)
            ctx = {}
            for c in CONDITIONS:
                ctx[c] = _f(bar, c)
            # conserve pour l'analyse du plafond (pas dans CONDITIONS)
            ctx["_n_big_ask"] = _f(bar, "n_big_ask_v2_t1") or 0.0
            ctx["_n_big_bid"] = _f(bar, "n_big_bid_v2_t1") or 0.0
            ctx["_vol_big"] = ((_f(bar, "max_big_ask_vol_in_bar") or 0.0)
                               + (_f(bar, "max_big_bid_vol_in_bar") or 0.0))

            evenements.append({
                "zone": nom, "sens": "SUPPORT" if support else "RESISTANCE",
                "issue": issue, "session": bar.get("session_segment", "?"),
                **ctx,
            })

    return evenements


def comparer(evs: list[dict], titre: str, min_n: int = 30) -> None:
    tient = [e for e in evs if e["issue"] == "TIENT"]
    casse = [e for e in evs if e["issue"] == "CASSE"]
    tot = len(evs)
    if tot < min_n:
        print(f"{titre} : n={tot} — insuffisant (< {min_n}), pas de comparaison")
        return
    print(f"\n{titre}")
    print(f"  n={tot}  TIENT={len(tient)} ({100*len(tient)/tot:.0f}%)  "
          f"CASSE={len(casse)} ({100*len(casse)/tot:.0f}%)")
    if len(tient) < 10 or len(casse) < 10:
        print("  (un des deux groupes < 10, comparaison non fiable)")
        return
    print(f"  {'condition':<26}{'TIENT':>12}{'CASSE':>12}{'ecart':>10}")
    for c in CONDITIONS:
        a = [e[c] for e in tient if e.get(c) is not None]
        b = [e[c] for e in casse if e.get(c) is not None]
        if len(a) < 10 or len(b) < 10:
            continue
        ma, mb = st.median(a), st.median(b)
        if ma == 0 and mb == 0:
            continue
        base = max(abs(ma), abs(mb), 1e-9)
        ecart = 100.0 * (ma - mb) / base
        flag = "  <<<" if abs(ecart) >= 20 else ""
        print(f"  {c:<26}{ma:>12.3f}{mb:>12.3f}{ecart:>9.0f}%{flag}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Ce qui distingue un niveau qui tient d'un niveau qui casse.")
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES")
    ap.add_argument("--jours", type=int, default=74)
    args = ap.parse_args()

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        barres = charger(sym, args.data, args.jours)
        if not barres:
            print(f"[{sym}] aucune barre")
            continue
        print("=" * 76)
        print(f"{sym} — {len(barres)} barres | zone +-{TOLERANCE[sym]}t | "
              f"rebond {REBOND[sym]}t | cassure {CASSURE[sym]}t | fenetre {FENETRE}b")
        print("=" * 76)

        evs = analyser(barres, sym)
        print(f"\n{len(evs)} tests de niveau tranches (hors INDECIS)")

        comparer(evs, ">>> TOUS NIVEAUX CONFONDUS")
        comparer([e for e in evs if e["sens"] == "SUPPORT"], ">>> SUPPORTS")
        comparer([e for e in evs if e["sens"] == "RESISTANCE"], ">>> RESISTANCES")

        # --- Le plafond a 20 est-il un probleme ? ---
        # Si le taux de tenue MONTE encore en arrivant au plafond, on perd de
        # l'information (le signal continue au-dela de 20). S'il sature avant,
        # le plafond ne coute rien.
        print("\n>>> TAUX DE TENUE PAR NOMBRE DE GROS ORDRES (test du plafond)")
        for lo, hi, lab in [(0, 0, "0"), (1, 5, "1-5"), (6, 19, "6-19"),
                            (20, 999, "20 (PLAFOND)")]:
            sel = [e for e in evs
                   if lo <= max(e.get("_n_big_ask") or 0, e.get("_n_big_bid") or 0) <= hi]
            if len(sel) < 30:
                print(f"     {lab:<14} n={len(sel):>4}  (insuffisant)")
                continue
            t = sum(1 for e in sel if e["issue"] == "TIENT")
            print(f"     {lab:<14} n={len(sel):>4}  tient {100 * t / len(sel):>5.1f}%")

        # Meme lecture avec le VOLUME (non plafonne) : la mesure honnete.
        print("\n>>> TAUX DE TENUE PAR VOLUME DE GROS ORDRES (non plafonne)")
        vols = sorted(e.get("_vol_big") or 0.0 for e in evs)
        if vols:
            q = [vols[int(len(vols) * x)] for x in (0.25, 0.5, 0.75, 0.9)]
            for lo, hi, lab in [(0, q[0], f"<= {q[0]:.0f}"),
                                (q[0], q[1], f"{q[0]:.0f}-{q[1]:.0f}"),
                                (q[1], q[2], f"{q[1]:.0f}-{q[2]:.0f}"),
                                (q[2], q[3], f"{q[2]:.0f}-{q[3]:.0f}"),
                                (q[3], 10 ** 9, f"> {q[3]:.0f} (top 10%)")]:
                sel = [e for e in evs if lo <= (e.get("_vol_big") or 0.0) < hi]
                if len(sel) < 30:
                    print(f"     {lab:<18} n={len(sel):>4}  (insuffisant)")
                    continue
                t = sum(1 for e in sel if e["issue"] == "TIENT")
                print(f"     {lab:<18} n={len(sel):>4}  tient {100 * t / len(sel):>5.1f}%")

        print("\n>>> TAUX DE TENUE PAR ZONE")
        par_zone = defaultdict(list)
        for e in evs:
            par_zone[e["zone"]].append(e)
        lignes = []
        for z, es in par_zone.items():
            t = sum(1 for e in es if e["issue"] == "TIENT")
            if len(es) >= 20:
                lignes.append((100.0 * t / len(es), len(es), z))
        for taux, nn, z in sorted(lignes, reverse=True):
            print(f"     {z:<16} n={nn:>4}  tient {taux:>5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
