"""Mesure le PF BRUT du CONSEIL GLOBAL du dashboard (Triple Barrier Lopez ch.3).

QUESTION POSEE : la methode de Jackson, telle qu'elle est deja encodee dans le
dashboard (Market Profile + niveaux veille + volume profile + options MenthorQ +
order flow + delta), a-t-elle un edge brut ?

POURQUOI CETTE MESURE D'ABORD (INCIDENT 03/05) :
    "Un meta-labeler ne sauve pas un edge sous-jacent inexistant. Si PF brut
     < 1.2 stable, le meta amplifie le bruit pas le signal."
Donc : pas de selection de features, pas de meta-labeling, pas de ML tant que
ce chiffre n'est pas connu.

METHODE
-------
1. On rejoue `build_conseil_global` barre par barre sur les JSONL propres.
2. On n'evalue une decision que toutes les N barres (--decision-tf), pour
   simuler une timeframe de decision plus lente sans toucher aux features.
   Cf INCIDENT 03/05 : "ES en 1 min = bar size mismatch structurel, 5 min min".
3. Triple Barrier (Lopez ch.3) : TP / SL / timeout. Le label est la barriere
   touchee EN PREMIER. C'est la reponse methodologique a "c'est aleatoire" :
   peu importe la vitesse ou le chemin, seul compte ce qui est touche d'abord.

ANTI-LOOKAHEAD (INCIDENT #13 : 6 features leak dans le "subset 9 winners",
PF 6.26 -> 0.92 apres ablation) :
  - le signal est calcule sur la barre i (donnees closes)
  - l'entree se fait au CLOSE de la barre i
  - la recherche TP/SL commence a la barre i+1, jamais sur la barre i
  - si TP et SL sont touches dans la MEME barre, on compte SL (conservateur :
    on ne peut pas savoir l'ordre intra-barre sans les ticks)

COUTS : soustraits systematiquement (INCIDENT #28 : un "edge" de +1.2 tick brut
devient -0.76 tick net apres 2 ticks de couts).

Usage :
    python -X utf8 CORE/research/backtest_conseil_global.py
    python -X utf8 CORE/research/backtest_conseil_global.py --decision-tf 15
    python -X utf8 CORE/research/backtest_conseil_global.py --symbols ES
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from DASHBOARD.api.builders import (  # noqa: E402
    build_conseil_global,
    build_options_levels,
    build_regime_context,
)

# Parametres par instrument. SL/TP en TICKS (tick = 0.25 pour ES et NQ).
# Bases sur les ordres de grandeur donnes par Jackson : ES SL 4-5 pts,
# NQ SL 15-20 pts. R:R 2:1.
PARAMS = {
    "ES": {"sl_ticks": 20, "tp_ticks": 40, "cost_ticks": 2.0, "tick": 0.25,
           "tick_value": 12.50},
    "NQ": {"sl_ticks": 80, "tp_ticks": 160, "cost_ticks": 3.0, "tick": 0.25,
           "tick_value": 5.00},
}

ACTIONS_LONG = ("ACHAT", "ACHAT PRUDENT")
ACTIONS_SHORT = ("VENTE", "VENTE PRUDENTE")


def charger_barres(sym: str, racine: str) -> list[dict]:
    """Charge toutes les barres d'un symbole, triees chronologiquement."""
    barres = []
    for f in sorted(glob.glob(os.path.join(racine, sym, "2026*_sierra_enriched.jsonl"))):
        for ligne in open(f, "r", encoding="utf-8", errors="replace"):
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                barres.append(json.loads(ligne))
            except json.JSONDecodeError:
                continue
    barres.sort(key=lambda b: b.get("ts", 0))
    return barres


def simuler(barres: list[dict], sym: str, decision_tf: int, timeout_bars: int,
            rth_only: bool) -> list[dict]:
    """Rejoue le conseil et applique le Triple Barrier. Retourne les trades."""
    p = PARAMS[sym]
    tick = p["tick"]
    trades: list[dict] = []
    i = 0
    n = len(barres)

    while i < n - 1:
        # Echantillonnage de la decision : on ne regarde qu'une barre sur N.
        if i % decision_tf != 0:
            i += 1
            continue

        bar = barres[i]
        if rth_only and not bar.get("is_cash_session"):
            i += 1
            continue

        try:
            reg = build_regime_context(bar)
            cg = build_conseil_global(bar, reg, build_options_levels(bar, sym))
        except Exception:
            i += 1
            continue

        action = cg.get("raw_action", "ATTENDRE")
        if action in ACTIONS_LONG:
            sens = 1
        elif action in ACTIONS_SHORT:
            sens = -1
        else:
            i += 1
            continue

        entree = bar.get("close")
        if not isinstance(entree, (int, float)) or entree <= 0:
            i += 1
            continue

        tp = entree + sens * p["tp_ticks"] * tick
        sl = entree - sens * p["sl_ticks"] * tick

        # Triple Barrier : on demarre a i+1 (jamais la barre du signal).
        sortie = None
        motif = "TIMEOUT"
        j = i + 1
        limite = min(i + 1 + timeout_bars, n)
        while j < limite:
            h = barres[j].get("high")
            b_ = barres[j].get("low")
            if not isinstance(h, (int, float)) or not isinstance(b_, (int, float)):
                j += 1
                continue
            touche_tp = (h >= tp) if sens > 0 else (b_ <= tp)
            touche_sl = (b_ <= sl) if sens > 0 else (h >= sl)
            if touche_sl:
                # Conservateur : si TP et SL dans la meme barre, on compte SL.
                sortie, motif = sl, "SL"
                break
            if touche_tp:
                sortie, motif = tp, "TP"
                break
            j += 1

        if sortie is None:
            sortie = barres[min(j, n - 1)].get("close", entree)

        ticks_bruts = sens * (sortie - entree) / tick
        ticks_nets = ticks_bruts - p["cost_ticks"]

        trades.append({
            "sym": sym,
            "sens": "LONG" if sens > 0 else "SHORT",
            "action": action,
            "motif": motif,
            "ticks_nets": ticks_nets,
            "usd": ticks_nets * p["tick_value"],
            "session": bar.get("session_segment", "?"),
            "barres_tenues": j - i,
        })

        # Une position a la fois : on reprend apres la sortie (realiste,
        # et evite de compter 40 fois le meme mouvement).
        i = j + 1

    return trades


def resumer(trades: list[dict], titre: str) -> None:
    """Affiche PF, WR, EV/trade. PF = somme gains / somme pertes (Lopez)."""
    if not trades:
        print(f"{titre:<34} aucun trade")
        return
    gains = sum(t["ticks_nets"] for t in trades if t["ticks_nets"] > 0)
    pertes = -sum(t["ticks_nets"] for t in trades if t["ticks_nets"] < 0)
    n_win = sum(1 for t in trades if t["ticks_nets"] > 0)
    total = sum(t["ticks_nets"] for t in trades)
    pf = (gains / pertes) if pertes > 0 else float("inf")
    wr = 100.0 * n_win / len(trades)
    ev = total / len(trades)
    usd = sum(t["usd"] for t in trades)
    print(f"{titre:<34} n={len(trades):>5}  WR={wr:>5.1f}%  PF={pf:>5.2f}  "
          f"EV={ev:>+6.2f}t  total={total:>+9.1f}t ({usd:>+9.0f}$)")


def main() -> int:
    ap = argparse.ArgumentParser(description="PF brut du CONSEIL GLOBAL (Triple Barrier).")
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--decision-tf", type=int, default=5,
                    help="evalue une decision toutes les N barres 1-min (defaut 5)")
    ap.add_argument("--timeout-bars", type=int, default=60)
    ap.add_argument("--rth-only", action="store_true", help="restreint a la session US cash")
    args = ap.parse_args()

    print("=" * 84)
    print(f"PF BRUT — CONSEIL GLOBAL | decision toutes les {args.decision_tf} barres "
          f"| timeout {args.timeout_bars} barres | RTH_only={args.rth_only}")
    print("=" * 84)

    tous: list[dict] = []
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        if sym not in PARAMS:
            print(f"[{sym}] non parametre — ignore")
            continue
        barres = charger_barres(sym, args.data)
        if not barres:
            print(f"[{sym}] aucune barre trouvee dans {args.data}")
            continue
        p = PARAMS[sym]
        print(f"\n### {sym} — {len(barres)} barres | SL {p['sl_ticks']}t / "
              f"TP {p['tp_ticks']}t / couts {p['cost_ticks']}t")
        tr = simuler(barres, sym, args.decision_tf, args.timeout_bars, args.rth_only)
        tous.extend(tr)

        resumer(tr, f"  {sym} TOTAL")
        for sens in ("LONG", "SHORT"):
            resumer([t for t in tr if t["sens"] == sens], f"  {sym} {sens}")
        par_session = defaultdict(list)
        for t in tr:
            par_session[t["session"]].append(t)
        for sess in sorted(par_session):
            resumer(par_session[sess], f"    session {sess}")
        motifs = defaultdict(int)
        for t in tr:
            motifs[t["motif"]] += 1
        print(f"  sorties : {dict(motifs)}")

    if tous:
        print("\n" + "=" * 84)
        resumer(tous, "TOTAL TOUS INSTRUMENTS")
        print("=" * 84)
        print("\nRappel seuils GO/NO-GO du projet : PF >= 1.3 | EV >= 1.0 tick | WR >= 45%")
        print("Un PF brut < 1.2 rend le meta-labeling inutile (cf INCIDENT 03/05).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
