"""SCENARIOS, prérequis 1 — la distribution des quatre types d'ouverture sur
le lot, AVANT tout usage (MISSION.md, point 1).

    python -X utf8 V3/scenarios/mesure_open_type.py

Par instrument : le compte des types (v0 : trois — DRIVE fusionné dans TEST_DRIVE, `traverse_b1` False = l'ancien DRIVE pur) (`recalc.open_type_r`, deux
premières barres 15 min cash, O = `open_cash_lvl` du brut si présent, bande
P10 sur `atr_veille` — le mètre que la chaîne a à 9h30, via `lot.journees`) ; la part de retours
sur l'ouverture ; le croisement avec le `open_type` LIVRÉ (code C++ 0-9, dont
la table n'est pas connue ici — on le regarde, on ne l'interprète pas).
Écrit `V3/scenarios/rapports/open_type_57j.md`. Aucun devenir.
"""

from __future__ import annotations

import collections
import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import recalc                                # noqa: E402
from V3.scenarios import lot                                    # noqa: E402

RAPPORT = os.path.join(RACINE, "V3", "scenarios", "rapports", "open_type_57j.md")


def mesurer(sym):
    types, retours, croise, lignes = collections.Counter(), collections.Counter(), collections.Counter(), []
    for jour, df, brut in lot.journees(sym):
        # le metre a 9h30 : `atr_veille` (la barre 0 n'a pas encore d'ATR de barre fiable)
        atr = float(df["atr_ref"].iloc[0]) if df["atr_source"].iloc[0] == "veille" else             (lot.atr_veille(sym, jour, brut) or float(df["atr_ref"].iloc[0]))
        o_lvl = pd.to_numeric(brut.get("open_cash_lvl"), errors="coerce")
        o_lvl = float(o_lvl.dropna().iloc[0]) if o_lvl is not None and o_lvl.notna().any() else None
        r = recalc.open_type_r(df, atr, open_lvl=o_lvl)
        if r["type"] is None:
            types["(%s)" % r["motif"]] += 1
            continue
        types[r["type"]] += 1
        retours[(r["type"], r["retour_ouverture"])] += 1
        livre = pd.to_numeric(brut.get("open_type"), errors="coerce")
        code = int(livre.dropna().max()) if livre is not None and livre.notna().any() else None
        croise[(r["type"], code)] += 1
        lignes.append((jour, r["type"], r["direction"], r["ext_b1_ticks"], r["ext_b2_ticks"], code))
    return types, retours, croise, lignes


def main():
    out = ["# Distribution des types d'ouverture — `open_type_r` (prérequis 1 du module SCÉNARIOS)", "",
           "*Définition écrite avant la mesure : docstring de `recalc.open_type_r`. Deux premières",
           "barres 15 min cash, O = `open_cash_lvl`, bande = P10 sur `atr_veille`. Aucun devenir.*", ""]
    for sym in ("ES", "NQ"):
        types, retours, croise, lignes = mesurer(sym)
        n = sum(v for k, v in types.items() if not k.startswith("("))
        out += ["## %s — %d jours types (%s non mesurables)" % (
            sym, n, ", ".join("%s %d" % (k, v) for k, v in types.items() if k.startswith("(")) or "0"),
            "| type | jours | part | dont retour sur O |", "|---|---|---|---|"]
        for typ in recalc.OPEN_TYPES:
            k = types.get(typ, 0)
            out.append("| %s | %d | %.0f %% | %d |" % (typ, k, 100.0 * k / n if n else 0,
                                                     retours.get((typ, True), 0)))
        out += ["", "Croisement avec le `open_type` LIVRÉ (code C++, table inconnue ici) :",
                "| recalculé \\ livré | " + " | ".join(str(c) for c in sorted({c for _, c in croise}, key=lambda x: (x is None, x))) + " |",
                "|---|" + "---|" * len({c for _, c in croise})]
        codes = sorted({c for _, c in croise}, key=lambda x: (x is None, x))
        for typ in recalc.OPEN_TYPES:
            out.append("| %s | " % typ + " | ".join(str(croise.get((typ, c), 0)) for c in codes) + " |")
        out += ["", "<details><summary>par jour</summary>", "", "| jour | type | dir | ext b1 (t) | ext b2 (t) | livré |", "|---|---|---|---|---|---|"]
        out += ["| %s | %s | %+d | %s | %s | %s |" % l for l in lignes]
        out += ["", "</details>", ""]
    os.makedirs(os.path.dirname(RAPPORT), exist_ok=True)
    open(RAPPORT, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("\n".join(l for l in out if not l.startswith("|") or l.startswith("| type") or l.startswith("| DRIVE")
                    or l.startswith("| TEST") or l.startswith("| REJET") or l.startswith("| ENCHERE")))
    print("rapport :", RAPPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
