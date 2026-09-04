"""PHASE 2 — Balayage : quelle facon de trader les zones a la meilleure esperance ?

Question posee
--------------
Sur chaque test de zone, deux trades sont possibles :

    FADE   on joue le rebond    (acheter un support, vendre une resistance)
    BREAK  on joue la cassure   (vendre un support qui lache, acheter au-dessus
                                 d'une resistance franchie)

La phase 1 a montre que les niveaux **cassent deux fois sur trois** (ES 32,7 %
de tenue, NQ 27,4 %). On a longtemps cherche ou rebondir ; ce script teste
aussi l'autre cote, et classe toutes les combinaisons par esperance de gain
NETTE DE COUTS.

Ce qui distingue ce balayage du data mining
-------------------------------------------
L'incident #28 rappelle qu'un audit qui teste 600 combinaisons "trouve" des
edges qui sont du bruit. Cinq garde-fous ici :

1. **Espace restreint et justifie a priori** : 18 zones x 2 sens x 2
   directions. Rien n'est ajoute apres coup pour ameliorer un resultat.
2. **Metrique en ticks nets de couts**, jamais en taux de reussite. Un taux
   de 68 % ne dit rien si la barriere gagnante est deux fois plus loin que la
   perdante. Barrieres SYMETRIQUES : TP = SL.
3. **Decoupage temporel train / test**. Le test n'est jamais consulte pour
   choisir quoi que ce soit.
4. **Correction de Benjamini-Hochberg** sur toutes les hypotheses du symbole.
5. **Une seule taille de barriere par symbole**, choisie a partir de l'ATR
   median et non optimisee. Balayer les R:R serait la porte ouverte au
   surajustement ; ce sera l'etape suivante, seulement si un candidat survit.

Sortie
------
Un classement par esperance, avec pour chaque candidat : effectif, taux de
reussite, esperance nette en ticks, profit factor, et surtout la valeur sur la
periode de test — celle qui n'a servi a rien d'autre qu'a verifier.

Usage :
    python -X utf8 CORE/research/phase2_balayage_strategies.py
    python -X utf8 CORE/research/phase2_balayage_strategies.py --jours 49 --min-n 40
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
    COOLDOWN, LOOKBACK, TOLERANCE, ZONES,
)

# Barriere symetrique par symbole (en ticks). Choisie sur l'ordre de grandeur
# de l'ATR median de seance, PAS optimisee sur le resultat.
BARRIERE = {"ES": 10, "NQ": 40}

# Cout aller-retour en ticks : spread + slippage + commission.
COUT = {"ES": 2.0, "NQ": 3.0}

# Duree maximale du trade, en barres d'une minute.
TIMEOUT = 30


def charger(symbole: str, jours: int, dossier: str) -> list[dict]:
    barres = []
    for chemin in sorted(glob.glob(os.path.join(dossier, symbole, "2026*.jsonl")))[-jours:]:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if ligne:
                    barres.append(json.loads(ligne))
    barres.sort(key=lambda b: b.get("ts", 0))
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


def simuler(barres, depart: int, entree: float, sens_trade: int,
            barriere_ticks: int, tick: float):
    """Triple barriere symetrique. Retourne le resultat en TICKS, hors couts.

    sens_trade : +1 pour un achat, -1 pour une vente.
    L'observation commence a `depart` (barre suivant le signal) : le signal est
    lu a la cloture de la barre precedente, l'entree se fait a ce prix.
    Si les deux barrieres sont touchees dans la meme barre, on retient la
    PERTE — hypothese prudente, on ne sait pas dans quel ordre elles ont ete
    atteintes.
    """
    marge = barriere_ticks * tick
    tp = entree + sens_trade * marge
    sl = entree - sens_trade * marge
    for j in range(depart, min(depart + TIMEOUT, len(barres))):
        h, b_ = _f(barres[j], "high"), _f(barres[j], "low")
        if h is None or b_ is None:
            continue
        if sens_trade > 0:
            touche_sl = b_ <= sl
            touche_tp = h >= tp
        else:
            touche_sl = h >= sl
            touche_tp = b_ <= tp
        if touche_sl:
            return -barriere_ticks
        if touche_tp:
            return +barriere_ticks
    # Timeout : on solde a la cloture
    fin = _f(barres[min(depart + TIMEOUT, len(barres)) - 1], "close")
    if fin is None:
        return None
    return sens_trade * (fin - entree) / tick


def collecter(barres, symbole: str, rth_seul: bool) -> list[dict]:
    tol = TOLERANCE[symbole]
    tick = get_tick_size(symbole)
    barriere = BARRIERE[symbole]
    trades: list[dict] = []
    dernier: dict[str, int] = {}
    n = len(barres)

    for i in range(LOOKBACK, n - TIMEOUT - 2):
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
                continue
            support = avant > niveau
            dernier[nom] = i

            # FADE : on parie sur le rebond -> achat sur support, vente sur resistance
            # BREAK : on parie sur la cassure -> l'inverse
            for direction, sens_trade in (("FADE", 1 if support else -1),
                                          ("BREAK", -1 if support else 1)):
                r = simuler(barres, i + 1, prix, sens_trade, barriere, tick)
                if r is None:
                    continue
                trades.append({
                    "i": i,
                    "zone": nom,
                    "sens": "SUPPORT" if support else "RESISTANCE",
                    "direction": direction,
                    "ticks": r,
                })
    return trades


def wilson(succes: int, total: int, z: float = 1.96):
    if total == 0:
        return (0.0, 1.0)
    p = succes / total
    d = 1 + z * z / total
    c = (p + z * z / (2 * total)) / d
    demi = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return (max(0.0, c - demi), min(1.0, c + demi))


def benjamini_hochberg(pvals: list[float], alpha: float = 0.05) -> list[bool]:
    n = len(pvals)
    if n == 0:
        return []
    paires = sorted(enumerate(pvals), key=lambda x: x[1])
    garde = [False] * n
    dernier = 0
    for rang, (_, p) in enumerate(paires, start=1):
        if p <= alpha * rang / n:
            dernier = rang
    for rang, (idx, _) in enumerate(paires, start=1):
        if rang <= dernier:
            garde[idx] = True
    return garde


def resume(ticks: list[float], cout: float) -> dict:
    nets = [t - cout for t in ticks]
    n = len(nets)
    gains = [x for x in nets if x > 0]
    pertes = [-x for x in nets if x < 0]
    somme_gains, somme_pertes = sum(gains), sum(pertes)
    return {
        "n": n,
        "esperance": sum(nets) / n if n else 0.0,
        "wr": len(gains) / n if n else 0.0,
        "pf": (somme_gains / somme_pertes) if somme_pertes > 0 else float("inf"),
        "total": sum(nets),
    }


def analyser(trades: list[dict], symbole: str, min_n: int, part_train: float):
    cout = COUT[symbole]
    coupe = int(len(trades) * part_train)
    ids_train = {id(t) for t in trades[:coupe]}

    groupes: dict[tuple, list[dict]] = {}
    for t in trades:
        groupes.setdefault((t["zone"], t["sens"], t["direction"]), []).append(t)

    lignes = []
    for (zone, sens, direction), ts in groupes.items():
        if len(ts) < min_n:
            continue
        nets = [t["ticks"] - cout for t in ts]
        glob_ = resume([t["ticks"] for t in ts], cout)
        tr = [t for t in ts if id(t) in ids_train]
        te = [t for t in ts if id(t) not in ids_train]
        if len(tr) < 15 or len(te) < 15:
            continue
        r_tr = resume([t["ticks"] for t in tr], cout)
        r_te = resume([t["ticks"] for t in te], cout)
        # Test : l'esperance est-elle differente de zero ?
        p = stats.ttest_1samp(nets, 0.0).pvalue if len(nets) > 2 else 1.0
        if p != p:
            p = 1.0
        lignes.append({
            "zone": zone, "sens": sens, "direction": direction,
            "n": glob_["n"], "esp": glob_["esperance"], "wr": glob_["wr"],
            "pf": glob_["pf"], "total": glob_["total"], "p": p,
            "esp_train": r_tr["esperance"], "n_train": r_tr["n"],
            "esp_test": r_te["esperance"], "n_test": r_te["n"],
        })

    if lignes:
        garde = benjamini_hochberg([l["p"] for l in lignes])
        for l, g in zip(lignes, garde):
            l["significatif"] = g
            l["retenu"] = bool(g and l["esp_train"] > 0 and l["esp_test"] > 0)
    lignes.sort(key=lambda l: -l["esp"])
    return lignes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=49)
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--part-train", type=float, default=0.6)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--tout", action="store_true")
    ap.add_argument("--sortie", default="DOCS/PHASE2_BALAYAGE_STRATEGIES.md")
    args = ap.parse_args()

    rapport = ["# Phase 2 — balayage des facons de trader les zones\n\n",
               "Genere par `CORE/research/phase2_balayage_strategies.py`.\n\n",
               "Esperance en **ticks nets de couts**, barrieres symetriques "
               "(TP = SL), sortie forcee a %d barres. Un candidat n'est retenu "
               "que si son esperance est significativement differente de zero "
               "apres correction de Benjamini-Hochberg ET positive sur les deux "
               "moities temporelles.\n" % TIMEOUT]

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        barres = charger(sym, args.jours, args.data)
        if not barres:
            print("[%s] aucune donnee" % sym)
            continue
        trades = collecter(barres, sym, rth_seul=not args.tout)
        if not trades:
            print("[%s] aucun trade" % sym)
            continue
        lignes = analyser(trades, sym, args.min_n, args.part_train)

        jours = len({b.get("session_date_trading") or b.get("session_date")
                     for b in barres if b.get("is_cash_session")})
        touches = len(trades) // 2
        entete = ("%s — %d touches de zones sur %d jours (%.1f/jour), barriere "
                  "+/-%d ticks, cout %.1f ticks"
                  % (sym, touches, jours, touches / max(jours, 1),
                     BARRIERE[sym], COUT[sym]))
        print("\n" + "=" * len(entete))
        print(entete)
        print("=" * len(entete))

        for direction in ("FADE", "BREAK"):
            ts = [t["ticks"] for t in trades if t["direction"] == direction]
            r = resume(ts, COUT[sym])
            print("  TOUTES ZONES %-6s : n=%-5d esperance %+6.2f ticks  "
                  "reussite %.1f %%  PF %.2f  total %+.0f ticks"
                  % (direction, r["n"], r["esperance"], 100 * r["wr"],
                     r["pf"], r["total"]))

        print()
        print("  %-13s %-11s %-6s %5s %8s %7s %6s %9s %9s %5s"
              % ("zone", "sens", "dir", "n", "esp.", "reuss.", "PF",
                 "esp.train", "esp.test", "OK"))
        for l in lignes[:args.top]:
            print("  %-13s %-11s %-6s %5d %+8.2f %6.1f%% %6.2f %+9.2f %+9.2f %5s"
                  % (l["zone"][:13], l["sens"], l["direction"], l["n"],
                     l["esp"], 100 * l["wr"], min(l["pf"], 99.9),
                     l["esp_train"], l["esp_test"],
                     "OUI" if l.get("retenu") else ""))

        retenus = [l for l in lignes if l.get("retenu")]
        print("\n  candidats retenus : %d sur %d testes" % (len(retenus), len(lignes)))
        if retenus:
            total_j = sum(l["n"] for l in retenus) / max(jours, 1)
            print("  frequence cumulee des retenus : %.1f trades/jour" % total_j)

        rapport.append("\n## %s\n\n" % entete)
        for direction in ("FADE", "BREAK"):
            ts = [t["ticks"] for t in trades if t["direction"] == direction]
            r = resume(ts, COUT[sym])
            rapport.append("- **Toutes zones %s** : n=%d, esperance %+.2f ticks, "
                           "reussite %.1f %%, PF %.2f\n"
                           % (direction, r["n"], r["esperance"], 100 * r["wr"], r["pf"]))
        rapport.append("\n| zone | sens | dir | n | esperance | reussite | PF | esp. train | esp. test | retenu |\n")
        rapport.append("|---|---|---|---|---|---|---|---|---|---|\n")
        for l in lignes[:args.top]:
            rapport.append("| %s | %s | %s | %d | %+.2f | %.1f %% | %.2f | %+.2f | %+.2f | %s |\n"
                           % (l["zone"], l["sens"], l["direction"], l["n"],
                              l["esp"], 100 * l["wr"], min(l["pf"], 99.9),
                              l["esp_train"], l["esp_test"],
                              "**OUI**" if l.get("retenu") else ""))

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    print("\nRapport : %s" % args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
