"""PHASE 1 — Quelles zones tiennent plus souvent que le hasard ?

Question posee
--------------
Quand le prix vient tester une zone (VPOC, IB, niveau d'options, VWAP...),
elle tient dans 32 % des cas et casse dans 68 % — c'est le taux de base mesure
sur 5 646 tests. La question de la phase 1 est simple : **existe-t-il des
zones qui s'ecartent significativement de ce taux de base ?**

Une zone qui tient a 47 % n'est interessante que si l'ecart survit a trois
controles :
  1. un intervalle de confiance (47 % sur n=44, c'est +/- 15 points) ;
  2. un test contre le taux de base du symbole, pas contre 50 % ;
  3. une correction pour tests multiples — on teste 18 zones x 2 sens x
     2 symboles, donc environ 70 hypotheses : au seuil de 5 %, trois "decouvertes"
     sont attendues par pur hasard.

Et un quatrieme, decisif : **l'ecart tient-il sur une periode que l'on n'a pas
regardee ?** Le jeu est coupe en deux dans le temps. Une zone qui ne tient que
sur la premiere moitie est un accident.

Ce que ce script ne fait pas
----------------------------
Il ne cherche PAS de strategie et ne teste aucune condition d'entree. Il
etablit seulement la carte des taux de base, qui servira de reference a la
phase 2 (confluence) et a la phase 3 (le niveau "defendu"). Sans cette
reference, tout chiffre annonce plus tard serait ininterpretable.

Choix methodologiques
---------------------
- **Seance US uniquement** pour le declenchement : c'est la que Jackson trade,
  et les distributions hors seance sont trop differentes (facteur 11 sur
  certaines features). L'observation, elle, se poursuit sur toutes les barres :
  un niveau teste a 15h55 peut casser a 16h10.
- **Parametres par symbole** (tolerance, rebond, cassure) : ES et NQ ne
  partagent pas d'echelle. Cf memoire feedback_calibration_par_instrument.
- **Cooldown** de 15 barres par zone : deux tests consecutifs du meme niveau
  ne sont pas des observations independantes.
- **Support et resistance separes** : ce ne sont pas les memes populations.

Usage :
    python -X utf8 CORE/research/phase1_base_rate_zones.py
    python -X utf8 CORE/research/phase1_base_rate_zones.py --jours 49 --min-n 40
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from scipy import stats  # noqa: E402

from CORE.constants import get_tick_size  # noqa: E402
from CORE.research.audit_niveaux_tiennent import (  # noqa: E402
    CASSURE, COOLDOWN, FENETRE, LOOKBACK, REBOND, TOLERANCE, ZONES,
)


def charger(symbole: str, jours: int, dossier: str) -> list[dict]:
    barres = []
    motif = os.path.join(dossier, symbole, "2026*.jsonl")
    for chemin in sorted(glob.glob(motif))[-jours:]:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if ligne:
                    barres.append(json.loads(ligne))
    barres.sort(key=lambda b: b.get("ts", 0))
    # dedoublonnage sur ts
    vus, propres = set(), []
    for b in barres:
        t = b.get("ts")
        if t in vus:
            continue
        vus.add(t)
        propres.append(b)
    return propres


def _f(bar: dict, cle: str):
    v = bar.get(cle)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        return f if f == f else None
    return None


def detecter(barres: list[dict], symbole: str, rth_seul: bool) -> list[dict]:
    """Un evenement par test de zone. Aucune information posterieure au test.

    Le declenchement est restreint a la seance US, mais l'observation de
    l'issue se poursuit sur les barres suivantes quelles qu'elles soient.
    """
    tol, reb, cas = TOLERANCE[symbole], REBOND[symbole], CASSURE[symbole]
    tick = get_tick_size(symbole)
    evenements: list[dict] = []
    dernier: dict[str, int] = {}
    n = len(barres)

    for i in range(LOOKBACK, n - FENETRE - 1):
        bar = barres[i]
        if rth_seul and not bar.get("is_cash_session"):
            continue
        prix = _f(bar, "close")
        if prix is None:
            continue

        for nom, cle in ZONES.items():
            d = _f(bar, cle)
            if d is None or abs(d) > tol:
                continue
            if i - dernier.get(nom, -10 ** 9) < COOLDOWN:
                continue

            niveau = prix + d * tick
            avant = _f(barres[i - LOOKBACK], "close")
            if avant is None or abs(avant - niveau) < tol * tick:
                continue  # approche ambigue, on ne tranche pas
            support = avant > niveau
            dernier[nom] = i

            issue = None
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
            if issue is None:
                continue  # indecis dans la fenetre : on n'invente pas d'issue

            evenements.append({
                "i": i,
                "ts": bar.get("ts"),
                "zone": nom,
                "sens": "SUPPORT" if support else "RESISTANCE",
                "tient": issue == "TIENT",
            })
    return evenements


def wilson(succes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance de Wilson — fiable meme sur petits effectifs."""
    if total == 0:
        return (0.0, 1.0)
    p = succes / total
    d = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    demi = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return (max(0.0, centre - demi), min(1.0, centre + demi))


def benjamini_hochberg(pvals: list[float], alpha: float = 0.05) -> list[bool]:
    n = len(pvals)
    if n == 0:
        return []
    paires = sorted(enumerate(pvals), key=lambda x: x[1])
    garde = [False] * n
    dernier = -1
    for rang, (_, p) in enumerate(paires, start=1):
        if p <= alpha * rang / n:
            dernier = rang
    for rang, (idx, _) in enumerate(paires, start=1):
        if rang <= dernier:
            garde[idx] = True
    return garde


def analyser(evenements: list[dict], min_n: int, part_train: float):
    total = len(evenements)
    base = sum(1 for e in evenements if e["tient"]) / total if total else 0.0

    coupe = int(total * part_train)
    train_ids = {id(e) for e in evenements[:coupe]}

    groupes: dict[tuple[str, str], list[dict]] = {}
    for e in evenements:
        groupes.setdefault((e["zone"], e["sens"]), []).append(e)

    lignes = []
    for (zone, sens), evs in groupes.items():
        n = len(evs)
        if n < min_n:
            continue
        k = sum(1 for e in evs if e["tient"])
        taux = k / n
        bas, haut = wilson(k, n)
        # Test contre le taux de base observe, pas contre 50 %.
        p = stats.binomtest(k, n, base, alternative="two-sided").pvalue

        tr = [e for e in evs if id(e) in train_ids]
        te = [e for e in evs if id(e) not in train_ids]
        taux_tr = (sum(1 for e in tr if e["tient"]) / len(tr)) if tr else float("nan")
        taux_te = (sum(1 for e in te if e["tient"]) / len(te)) if te else float("nan")
        lignes.append({
            "zone": zone, "sens": sens, "n": n, "taux": taux,
            "ic_bas": bas, "ic_haut": haut, "p": p,
            "n_train": len(tr), "taux_train": taux_tr,
            "n_test": len(te), "taux_test": taux_te,
        })

    if lignes:
        garde = benjamini_hochberg([l["p"] for l in lignes])
        for l, g in zip(lignes, garde):
            l["significatif"] = g
            # Stable = ecart de meme signe sur les deux moities, et l'IC exclut
            # le taux de base.
            meme_sens = ((l["taux_train"] - base) * (l["taux_test"] - base) > 0
                         if l["taux_train"] == l["taux_train"]
                         and l["taux_test"] == l["taux_test"] else False)
            l["stable"] = bool(g and meme_sens
                               and (l["ic_bas"] > base or l["ic_haut"] < base))
    lignes.sort(key=lambda l: -abs(l["taux"] - base))
    return base, lignes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=49)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--part-train", type=float, default=0.6)
    ap.add_argument("--tout", action="store_true",
                    help="declencher aussi hors seance US")
    ap.add_argument("--sortie", default="DOCS/PHASE1_BASE_RATE_ZONES.md")
    args = ap.parse_args()

    rapport = ["# Phase 1 — taux de base des zones\n\n",
               "Genere par `CORE/research/phase1_base_rate_zones.py`.\n\n",
               "Une zone n'est retenue que si son ecart au taux de base survit a "
               "la correction de Benjamini-Hochberg (environ 70 hypotheses testees), "
               "que son intervalle de Wilson exclut le taux de base, et que "
               "l'ecart garde le meme signe sur les deux moities temporelles.\n"]

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        barres = charger(sym, args.jours, args.data)
        if not barres:
            print("[%s] aucune donnee" % sym)
            continue
        evs = detecter(barres, sym, rth_seul=not args.tout)
        if not evs:
            print("[%s] aucun test de zone" % sym)
            continue
        base, lignes = analyser(evs, args.min_n, args.part_train)

        jours = len({b.get("session_date_trading") or b.get("session_date")
                     for b in barres if b.get("is_cash_session")})
        entete = ("%s — %d tests de zones sur %d jours de seance (%.1f tests/jour)"
                  % (sym, len(evs), jours, len(evs) / max(jours, 1)))
        print("\n" + "=" * len(entete))
        print(entete)
        print("=" * len(entete))
        print("  taux de base (toutes zones) : %.1f %% tiennent, %.1f %% cassent"
              % (100 * base, 100 * (1 - base)))
        print()
        print("  %-14s %-11s %5s %7s %-15s %8s %8s %6s"
              % ("zone", "sens", "n", "tient", "IC 95%", "1e moitie", "2e moitie", "solide"))
        for l in lignes:
            print("  %-14s %-11s %5d %6.1f%% [%5.1f-%5.1f%%] %7.1f%% %8.1f%% %6s"
                  % (l["zone"][:14], l["sens"], l["n"], 100 * l["taux"],
                     100 * l["ic_bas"], 100 * l["ic_haut"],
                     100 * l["taux_train"], 100 * l["taux_test"],
                     "OUI" if l.get("stable") else ""))

        solides = [l for l in lignes if l.get("stable")]
        print("\n  zones solides : %d sur %d testees (min n=%d)"
              % (len(solides), len(lignes), args.min_n))

        rapport.append("\n## %s\n\n" % entete)
        rapport.append("Taux de base : **%.1f %%** tiennent.\n\n" % (100 * base))
        rapport.append("| zone | sens | n | tient | IC 95 % | 1re moitie | 2e moitie | solide |\n")
        rapport.append("|---|---|---|---|---|---|---|---|\n")
        for l in lignes:
            rapport.append("| %s | %s | %d | %.1f %% | %.1f-%.1f %% | %.1f %% | %.1f %% | %s |\n"
                           % (l["zone"], l["sens"], l["n"], 100 * l["taux"],
                              100 * l["ic_bas"], 100 * l["ic_haut"],
                              100 * l["taux_train"], 100 * l["taux_test"],
                              "**OUI**" if l.get("stable") else ""))

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    print("\nRapport : %s" % args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
