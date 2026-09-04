"""PHASE 3 — Empiler les zones ameliore-t-il l'esperance ?

Question posee
--------------
Jackson ne trade pas un niveau isole : il trade une **confluence**, plusieurs
zones qui se superposent dans un mouchoir de poche. La phase 2 a montre que les
zones prises une par une n'ont aucune esperance positive (0 candidat sur 64,
ES comme NQ). La question est donc : est-ce que l'empilement change quelque
chose ?

Un indice existe : une mesure du 03/09 donnait un profit factor de 0,96 puis
1,05 puis 1,11 selon le nombre de zones. Faible, mais monotone. Ce script
reprend la question avec la rigueur de la phase 2 : esperance en ticks nets de
couts, barrieres symetriques, decoupage temporel, et surtout le test qui
compte — la **monotonie**.

Pourquoi la monotonie plutot que la significativite d'un seul palier
--------------------------------------------------------------------
Tester "3 zones est-il meilleur que la moyenne ?" revient a chercher un palier
gagnant parmi plusieurs, et on en trouve toujours un par hasard. Un vrai effet
de confluence doit produire une PROGRESSION : plus il y a de zones empilees,
meilleure est l'esperance. On teste donc la correlation de Spearman entre le
nombre de zones et le resultat du trade — une seule hypothese, pas une par
palier.

Si la correlation est nulle, la confluence est une illusion, quel que soit le
palier qui aura l'air bon.

Piege a eviter
--------------
La phase 2 a montre que les "candidats" NQ etaient du beta directionnel : NQ a
baisse de 0,96 % sur la periode, donc vendre marchait mecaniquement. Ce script
rapporte donc systematiquement les achats et les ventes SEPAREMENT. Un effet
de confluence reel doit apparaitre des deux cotes.

Usage :
    python -X utf8 CORE/research/phase3_confluence.py
    python -X utf8 CORE/research/phase3_confluence.py --fenetre-ticks 12
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from scipy import stats  # noqa: E402

from CORE.constants import get_tick_size  # noqa: E402
from CORE.research.audit_niveaux_tiennent import (  # noqa: E402
    COOLDOWN, LOOKBACK, TOLERANCE, ZONES,
)
from CORE.research.phase2_balayage_strategies import (  # noqa: E402
    BARRIERE, COUT, TIMEOUT, _f, charger, resume, simuler,
)

# Largeur de la fenetre de confluence, en ticks, par symbole. Une "zone
# proche" est un niveau situe a moins de cette distance du prix teste.
# Choisie a l'echelle de chaque instrument (cf feedback_calibration_par_instrument).
FENETRE_CONFLUENCE = {"ES": 8, "NQ": 32}


def compter_zones_proches(bar: dict, fenetre_ticks: float) -> tuple[int, list[str]]:
    """Combien de zones distinctes sont a portee du prix actuel ?"""
    proches = []
    for nom, cle in ZONES.items():
        d = _f(bar, cle)
        if d is not None and abs(d) <= fenetre_ticks:
            proches.append(nom)
    return len(proches), proches


def collecter(barres, symbole: str, fenetre_ticks: float,
              rth_seul: bool) -> list[dict]:
    """Un trade par touche de zone, avec le nombre de zones en confluence.

    Contrairement a la phase 2, on ne declenche qu'UNE fois par barre (sur la
    zone la plus proche) : sinon une confluence de 4 zones produirait 4 trades
    quasi identiques et gonflerait artificiellement l'effectif des paliers
    eleves.
    """
    tol = TOLERANCE[symbole]
    tick = get_tick_size(symbole)
    barriere = BARRIERE[symbole]
    trades: list[dict] = []
    dernier = -10 ** 9
    n = len(barres)

    for i in range(LOOKBACK, n - TIMEOUT - 2):
        bar = barres[i]
        if rth_seul and not bar.get("is_cash_session"):
            continue
        prix = _f(bar, "close")
        if prix is None:
            continue
        if i - dernier < COOLDOWN:
            continue

        # Zone la plus proche parmi celles effectivement touchees
        candidates = []
        for nom, cle in ZONES.items():
            d = _f(bar, cle)
            if d is not None and abs(d) <= tol:
                candidates.append((abs(d), nom, d))
        if not candidates:
            continue
        candidates.sort()
        _, zone, d = candidates[0]

        niveau = prix + d * tick
        avant = _f(barres[i - LOOKBACK], "close")
        if avant is None or abs(avant - niveau) < tol * tick:
            continue
        support = avant > niveau
        dernier = i

        n_zones, noms = compter_zones_proches(bar, fenetre_ticks)

        for direction, sens_trade in (("FADE", 1 if support else -1),
                                      ("BREAK", -1 if support else 1)):
            r = simuler(barres, i + 1, prix, sens_trade, barriere, tick)
            if r is None:
                continue
            trades.append({
                "zone": zone,
                "sens": "SUPPORT" if support else "RESISTANCE",
                "direction": direction,
                "sens_trade": sens_trade,
                "n_zones": n_zones,
                "zones": noms,
                "ticks": r,
            })
    return trades


def tableau_par_palier(trades, cout: float, libelle: str) -> None:
    paliers = sorted({t["n_zones"] for t in trades})
    print("    %-9s %6s %10s %9s %7s" % ("zones", "n", "esperance", "reussite", "PF"))
    for p in paliers:
        sous = [t["ticks"] for t in trades if t["n_zones"] == p]
        if len(sous) < 20:
            continue
        r = resume(sous, cout)
        print("    %-9s %6d %+10.2f %8.1f%% %7.2f"
              % ("%d zone%s" % (p, "s" if p > 1 else ""), r["n"],
                 r["esperance"], 100 * r["wr"], min(r["pf"], 99.9)))
    # Test de monotonie : une seule hypothese, pas un test par palier.
    xs = [t["n_zones"] for t in trades]
    ys = [t["ticks"] - cout for t in trades]
    if len(set(xs)) > 2:
        rho, p = stats.spearmanr(xs, ys)
        verdict = "effet monotone" if p < 0.05 else "pas d'effet"
        print("    monotonie %s : rho=%+.3f  p=%.3f  -> %s"
              % (libelle, rho, p, verdict))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=49)
    ap.add_argument("--fenetre-ticks", type=float, default=None,
                    help="largeur de la confluence en ticks (defaut : par symbole)")
    ap.add_argument("--tout", action="store_true")
    ap.add_argument("--sortie", default="DOCS/PHASE3_CONFLUENCE.md")
    args = ap.parse_args()

    rapport = ["# Phase 3 — effet de la confluence de zones\n\n",
               "Genere par `CORE/research/phase3_confluence.py`.\n\n",
               "Le test qui compte est la **monotonie** (correlation de Spearman "
               "entre le nombre de zones empilees et le resultat du trade), pas "
               "la performance d'un palier isole. Achats et ventes sont "
               "rapportes separement pour ecarter le beta directionnel.\n"]

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        barres = charger(sym, args.jours, args.data)
        if not barres:
            print("[%s] aucune donnee" % sym)
            continue
        fen = args.fenetre_ticks or FENETRE_CONFLUENCE[sym]
        trades = collecter(barres, sym, fen, rth_seul=not args.tout)
        if not trades:
            print("[%s] aucun trade" % sym)
            continue

        jours = len({b.get("session_date_trading") or b.get("session_date")
                     for b in barres if b.get("is_cash_session")})
        touches = len(trades) // 2
        entete = ("%s — %d touches sur %d jours (%.1f/jour), confluence mesuree "
                  "sur +/-%g ticks, barriere +/-%d ticks"
                  % (sym, touches, jours, touches / max(jours, 1), fen, BARRIERE[sym]))
        print("\n" + "=" * len(entete))
        print(entete)
        print("=" * len(entete))

        rapport.append("\n## %s\n\n" % entete)

        for direction in ("FADE", "BREAK"):
            sel = [t for t in trades if t["direction"] == direction]
            print("\n  %s — toutes directions de trade" % direction)
            tableau_par_palier(sel, COUT[sym], direction)

            for cote, libelle in ((1, "ACHATS"), (-1, "VENTES")):
                sous = [t for t in sel if t["sens_trade"] == cote]
                if len(sous) < 60:
                    continue
                print("\n  %s — %s seulement" % (direction, libelle))
                tableau_par_palier(sous, COUT[sym], "%s/%s" % (direction, libelle))

        # Rapport markdown : synthese par palier, toutes directions
        for direction in ("FADE", "BREAK"):
            sel = [t for t in trades if t["direction"] == direction]
            rapport.append("\n### %s\n\n" % direction)
            rapport.append("| zones | n | esperance | reussite | PF |\n|---|---|---|---|---|\n")
            for p in sorted({t["n_zones"] for t in sel}):
                sous = [t["ticks"] for t in sel if t["n_zones"] == p]
                if len(sous) < 20:
                    continue
                r = resume(sous, COUT[sym])
                rapport.append("| %d | %d | %+.2f | %.1f %% | %.2f |\n"
                               % (p, r["n"], r["esperance"], 100 * r["wr"],
                                  min(r["pf"], 99.9)))
            xs = [t["n_zones"] for t in sel]
            ys = [t["ticks"] - COUT[sym] for t in sel]
            if len(set(xs)) > 2:
                rho, p = stats.spearmanr(xs, ys)
                rapport.append("\nMonotonie : rho = %+.3f, p = %.3f — **%s**\n"
                               % (rho, p, "effet" if p < 0.05 else "pas d'effet"))

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    print("\nRapport : %s" % args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
