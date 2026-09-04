"""Audit EXHAUSTIF des donnees live_enriched, classe par ingredient de la methode.

Objectif (directive Jackson 04/09) : "ratisser large, n'oublier aucune donnee
importante". On ne regarde pas seulement la presence d'une feature : on regarde
si elle est VIVANTE (elle varie, elle se declenche parfois) ou MORTE (constante,
toujours zero, ou saturee a 100 %).

Pourquoi c'est necessaire — historique du projet :
  - #13/04 : 16 features big_orders mortes pendant 26 jours sans que rien n'alerte
  - #23/04 : bar_edge_buy/sell satures a 75 % sur NQ = feature non discriminante
  - #05/05 : 7 features "rare event" a 0.00-0.35 % au lieu de 0.5-2 % attendus
  - #57    : seuil MIN_DELTA_SLOPE=100 vs distribution reelle 0.001-0.05
  - #99    : range_pos en [0,1] lu comme [0,100] => zero signal VENTE

Verdicts :
  MORTE     constante sur tout l'echantillon (aucune information)
  ZERO      toujours nulle
  SATUREE   se declenche sur > 95 % des barres (ne discrimine plus rien)
  RARE      < 1 % — legitime pour un evenement rare, suspect sinon
  VIVANTE   varie et se declenche raisonnablement
  VIDE      absente ou > 50 % de trous

Usage :
    python -X utf8 CORE/research/audit_donnees_exhaustif.py
    python -X utf8 CORE/research/audit_donnees_exhaustif.py --jours 30 --symbols ES
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

# Familles = les ingredients de la methode. Ordre = importance declaree par
# Jackson : "au centre de tout ca, c'est le market profile".
FAMILLES: list[tuple[str, tuple[str, ...]]] = [
    ("MARKET PROFILE", ("vpoc", "vah", "val", "profile_", "poc_", "va_",
                        "single_print", "tpo", "naked_poc", "composite_poc")),
    ("VOLUME PROFILE", ("hvn", "lvn", "vol_at_price", "volume_profile",
                        "vol_node")),
    ("NIVEAUX VEILLE", ("prev_", "pdh", "pdl", "pvwap", "psd")),
    ("VWAP", ("vwap",)),
    ("INITIAL BALANCE", ("ib_",)),
    ("OPTIONS / MENTHORQ", ("mq_", "gex", "gamma", "dex", "0dte", "call_",
                            "put_", "blind", "vol_trigger")),
    ("ORDER FLOW", ("delta", "cvd", "absorb", "big_", "edge_", "imbalance",
                    "trapped", "aggressor", "buy_vol", "sell_vol", "ask_",
                    "bid_", "cluster", "footprint", "stack")),
    ("SWINGS / STRUCTURE", ("swing", "sweep", "bos", "retest", "fvg",
                            "judas", "liquidity")),
    ("SESSION / TEMPS", ("session", "ts", "date", "mins", "open_", "hour",
                         "is_cash", "rth", "day_type", "open_type")),
    ("VOLATILITE / REGIME", ("atr", "vix", "rvol", "regime", "volatil",
                             "range_", "sess_range")),
    ("BATTLE NAVALE", ("bn_", "long_up", "long_dn", "color_")),
    ("INTERMARKET", ("im_", "correl")),
    ("CONTEXTE ROLLING", ("ctx_",)),
    ("PRIX / OHLC", ("price", "open", "high", "low", "close", "bar_")),
]


def famille_de(cle: str) -> str:
    c = cle.lower()
    for nom, motifs in FAMILLES:
        if any(m in c for m in motifs):
            return nom
    return "AUTRES"


def verdict(n: int, remplis: int, non_zero: int, uniques: int,
            est_binaire: bool) -> str:
    if remplis < 0.5 * n:
        return "VIDE"
    if uniques <= 1:
        return "MORTE"
    if non_zero == 0:
        return "ZERO"
    taux = non_zero / max(remplis, 1)
    if est_binaire:
        # Une binaire qui fire > 95 % ou < 0.1 % ne discrimine plus rien.
        if taux > 0.95:
            return "SATUREE"
        if taux < 0.001:
            return "ZERO"
        if taux < 0.01:
            return "RARE"
    else:
        if uniques <= 3:
            return "QUASI-MORTE"
    return "VIVANTE"


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit exhaustif des donnees enrichies.")
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=20)
    ap.add_argument("--sortie", default="DOCS/AUDIT_DONNEES_EXHAUSTIF.md")
    args = ap.parse_args()

    rapport: list[str] = []
    rapport.append("# Audit exhaustif des donnees `live_enriched`\n")
    rapport.append("Genere par `CORE/research/audit_donnees_exhaustif.py`.\n")
    rapport.append("Verdicts : MORTE (constante) · ZERO · SATUREE (>95%) · "
                   "RARE (<1%) · QUASI-MORTE (<=3 valeurs) · VIDE (>50% trous) "
                   "· VIVANTE\n")

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        fichiers = sorted(glob.glob(os.path.join(args.data, sym,
                                                 "2026*_sierra_enriched.jsonl")))
        fichiers = fichiers[-args.jours:]
        if not fichiers:
            print(f"[{sym}] aucun fichier")
            continue

        lignes = []
        for f in fichiers:
            for l in open(f, "r", encoding="utf-8", errors="replace"):
                l = l.strip()
                if l:
                    lignes.append(json.loads(l))
        n = len(lignes)
        if n == 0:
            continue

        cles = sorted({k for b in lignes for k in b})
        stats: dict[str, dict] = {}
        for k in cles:
            vals = [b.get(k) for b in lignes]
            num = [float(v) for v in vals
                   if isinstance(v, (int, float, bool)) and not isinstance(v, str)]
            remplis = sum(1 for v in vals if v is not None)
            if not num:
                stats[k] = {"verdict": "NON-NUM", "remplis": remplis,
                            "non_zero": 0, "uniques": 0, "min": None, "max": None}
                continue
            uniq = set(num)
            non_zero = sum(1 for v in num if v != 0)
            binaire = uniq <= {0.0, 1.0} or len(uniq) == 2
            stats[k] = {
                "verdict": verdict(n, remplis, non_zero, len(uniq), binaire),
                "remplis": remplis, "non_zero": non_zero, "uniques": len(uniq),
                "min": min(num), "max": max(num),
            }

        par_famille: dict[str, list[str]] = defaultdict(list)
        for k in cles:
            par_famille[famille_de(k)].append(k)

        rapport.append(f"\n## {sym} — {n} barres ({len(fichiers)} jours), "
                       f"{len(cles)} colonnes\n")

        # Synthese : compte des verdicts par famille
        rapport.append("| Famille | total | VIVANTE | SATUREE | MORTE/ZERO | "
                       "RARE | VIDE |\n|---|---|---|---|---|---|---|\n")
        ordre = [nom for nom, _ in FAMILLES] + ["AUTRES"]
        for fam in ordre:
            ks = par_famille.get(fam, [])
            if not ks:
                continue
            c = defaultdict(int)
            for k in ks:
                c[stats[k]["verdict"]] += 1
            morte = c["MORTE"] + c["ZERO"] + c["QUASI-MORTE"]
            rapport.append(
                f"| {fam} | {len(ks)} | {c['VIVANTE']} | {c['SATUREE']} | "
                f"{morte} | {c['RARE']} | {c['VIDE']} |\n")

        # Detail : uniquement ce qui ne va pas
        rapport.append(f"\n### {sym} — features problematiques\n")
        for fam in ordre:
            ks = par_famille.get(fam, [])
            pb = [k for k in ks
                  if stats[k]["verdict"] in ("MORTE", "ZERO", "QUASI-MORTE",
                                             "SATUREE", "VIDE")]
            if not pb:
                continue
            rapport.append(f"\n**{fam}**\n\n")
            rapport.append("| feature | verdict | rempli | non-nul | uniques | min | max |\n")
            rapport.append("|---|---|---|---|---|---|---|\n")
            for k in sorted(pb, key=lambda x: stats[x]["verdict"]):
                s = stats[k]
                mn = f"{s['min']:.4g}" if s["min"] is not None else "-"
                mx = f"{s['max']:.4g}" if s["max"] is not None else "-"
                rapport.append(
                    f"| `{k}` | {s['verdict']} | {100*s['remplis']/n:.0f}% | "
                    f"{100*s['non_zero']/max(s['remplis'],1):.1f}% | "
                    f"{s['uniques']} | {mn} | {mx} |\n")

        # Console : synthese courte
        print(f"\n===== {sym} — {n} barres, {len(cles)} colonnes =====")
        for fam in ordre:
            ks = par_famille.get(fam, [])
            if not ks:
                continue
            c = defaultdict(int)
            for k in ks:
                c[stats[k]["verdict"]] += 1
            morte = c["MORTE"] + c["ZERO"] + c["QUASI-MORTE"]
            drapeau = " <== A REGARDER" if (morte + c["SATUREE"] + c["VIDE"]) > len(ks) * 0.3 else ""
            print(f"  {fam:<22} {len(ks):>4} cles | vivantes {c['VIVANTE']:>3} | "
                  f"saturees {c['SATUREE']:>3} | mortes {morte:>3} | "
                  f"rares {c['RARE']:>3} | vides {c['VIDE']:>3}{drapeau}")

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    print(f"\nRapport detaille : {args.sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
