"""SCÉNARIOS — le module se mesure lui-même (spec §4.4, MISSION étape 5) :
trois nombres sur le lot, AVANT tout affichage, contre l'attendu pré-enregistré
par la relectrice (`seuils.yaml: attendu_rejeu` — 60 % / 55 % / 15 points).

    python -X utf8 V3/scenarios/mesure_scenarios.py

  1. COUVERTURE : part des journées dont le scénario FINAL est canonique
     (les huit v0 + S_DANS_ROTATION ; `S_OUV_BAS_REINT` sans précision compte
     comme famille canonique ; S_AUTRE ne compte pas, ses raisons sont comptées).
  2. TENUE : part des scénarios VALIDÉS à 10h30 (la première barre avec l'IB,
     i = 4) encore vrais à la clôture (même code, toujours validé). À côté, la
     version large : scénario EN COURS à 10h30 encore en cours à 16h00.
  3. CONTRÔLE NÉGATIF : un scénario canonique tiré au sort par journée, mille
     tirages ; « couvert » = le tirage nomme un état que la journée a réellement
     traversé ; « tenu » = le tirage est le scénario validé à 10h30 ET final.
     La grammaire doit battre le p95 des tirages d'au moins `ecart_min` points
     sur les deux mesures — sinon le module décrit le passé.
Écrit `V3/scenarios/rapports/scenarios_57j.md`. Aucun devenir de trade, aucune
direction.
"""

from __future__ import annotations

import collections
import os
import sys

import numpy as np

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.scenarios import grammaire, lot, scenarios              # noqa: E402

RAPPORT = os.path.join(RACINE, "V3", "scenarios", "rapports", "scenarios_57j.md")
I_10H30 = 4
CANON = set(grammaire.CANONIQUES) | set(grammaire.GARDES) | {"S_OUV_BAS_REINT"}
TIRAGES = 1000


def _famille(code):
    return code if code in CANON else "S_AUTRE"


def mesurer(sym, seuils):
    jours = []
    for jour, df, brut in lot.journees(sym):
        L = scenarios.derouler(df, brut, sym, seuils)
        if len(L) <= I_10H30:
            continue
        d10, fin = L[I_10H30], L[-1]
        raison = next((e.get("raison") or e.get("cause") for e in fin["sequence_etats"]
                       if e["etat"] == "S_AUTRE" or (e["etat"] == "BASCULE" and e.get("vers") == "S_AUTRE")), None)
        jours.append({
            "jour": jour, "position": fin["position_ouverture"], "type": fin["type_ouverture"],
            "final": fin["scenario_en_cours"], "precision": fin["precision"], "valide_final": fin["valide"],
            "raison_autre": raison if fin["scenario_en_cours"] == "S_AUTRE" else None,
            "s10": d10["scenario_en_cours"], "v10": d10["valide"],
            "traverses": sorted({l["scenario_en_cours"] for l in L}),
            "bascules": len(fin["bascules"]),
            "h_valide": next((l["heure_et"] for l in L if l["valide"]), None),
        })
    return jours


def couverture(jours, validee=False):
    """Part des journees dont le scenario final est canonique ; `validee` :
    canonique ET valide (une TEND jamais validee est un scenario EN COURS,
    pas une journee decrite) — les deux nombres sont rendus, la relectrice
    dit lequel est « la couverture »."""
    if not jours:
        return 0.0
    return 100.0 * sum(j["final"] in CANON and (j["valide_final"] or not validee) for j in jours) / len(jours)


def tenue(jours):
    pop = [j for j in jours if j["v10"] and j["s10"] in CANON]
    ok = sum(j["final"] == j["s10"] and j["valide_final"] for j in pop)
    large_pop = [j for j in jours if j["s10"] in CANON]
    large = sum(j["final"] == j["s10"] for j in large_pop)
    return (100.0 * ok / len(pop) if pop else None, len(pop),
            100.0 * large / len(large_pop) if large_pop else None, len(large_pop))


def controle_negatif(jours, rng):
    codes = list(grammaire.CANONIQUES)
    couv, ten = [], []
    for _ in range(TIRAGES):
        tir = rng.choice(codes, size=len(jours))
        couv.append(100.0 * np.mean([t in j["traverses"] for t, j in zip(tir, jours)]))
        pop = [(t, j) for t, j in zip(tir, jours) if j["v10"] and j["s10"] in CANON]
        ten.append(100.0 * np.mean([t == j["s10"] == j["final"] for t, j in pop]) if pop else 0.0)
    return (float(np.mean(couv)), float(np.quantile(couv, 0.95)),
            float(np.mean(ten)), float(np.quantile(ten, 0.95)))


def bloc(sym, jours, att, rng):
    n = len(jours)
    c, cv = couverture(jours), couverture(jours, validee=True)
    t, npop, tl, nlarge = tenue(jours)
    cm, c95, tm, t95 = controle_negatif(jours, rng)
    ec_c, ec_t = c - c95, (t - t95) if t is not None else None
    verdict_c = ("ATTENDU" if att["couverture_min_pct"] <= c <= att["couverture_max_pct"] else
                 "TROP COURTE (< %d %%)" % att["couverture_min_pct"] if c < att["couverture_min_pct"] else
                 "TROP LARGE (> %d %%)" % att["couverture_max_pct"])
    verdict_t = ("—" if t is None else "ATTENDU" if t >= att["valides_min_pct"] else
                 "TROP PRECOCE (< %d %%)" % att["valides_min_pct"])
    verdict_n = ("BAT LE TIRAGE" if ec_c >= att["ecart_min_controle_negatif_points"]
                 and (ec_t is None or ec_t >= att["ecart_min_controle_negatif_points"]) else "NE BAT PAS LE TIRAGE")
    out = ["## %s — %d journées" % (sym, n), "",
           "| mesure | attendu (relectrice) | mesuré | verdict |", "|---|---|---|---|",
           "| 1. couverture des canoniques (scénario final EN COURS, pré-enregistrée) | %d %% (%d-%d) | **%.0f %%** | %s |" % (
               att["couverture_pct"], att["couverture_min_pct"], att["couverture_max_pct"], c, verdict_c),
           "| 1 bis. couverture des canoniques VALIDÉS à la clôture | — | **%.0f %%** | %s (à la relectrice de dire laquelle est la couverture) |" % (
               cv, "dans l'attendu" if att["couverture_min_pct"] <= cv <= att["couverture_max_pct"] else "hors attendu"),
           "| 2. validés à 10h30 encore vrais à 16h00 | %d %% (≥ %d) | **%s** (N validés à 10h30 = %d) | %s |" % (
               att["valides_10h30_vrais_16h_pct"], att["valides_min_pct"], lot.fmt(t, 0) + " %" if t is not None else "—", npop, verdict_t),
           "| 2 bis. en cours à 10h30 encore en cours à 16h00 (large) | — | %s (N = %d) | description |" % (
               lot.fmt(tl, 0) + " %" if tl is not None else "—", nlarge),
           "| 3. contrôle négatif, couverture : tirage moyen / p95 | grammaire − p95 ≥ %d pts | %.0f / %.0f %% → écart **%+.0f** | %s |" % (
               att["ecart_min_controle_negatif_points"], cm, c95, ec_c, verdict_n),
           "| 3. contrôle négatif, tenue : tirage moyen / p95 | idem | %.0f / %.0f %% → écart %s | |" % (
               tm, t95, ("%+.0f" % ec_t) if ec_t is not None else "—"),
           "", "Scénarios finaux :", ""]
    cnt = collections.Counter(_famille(j["final"]) + ((" [%s]" % j["precision"]) if j["precision"] else "") for j in jours)
    out += ["| scénario final | journées | validé | bascules moy. | 1re validation (médiane) |", "|---|---|---|---|---|"]
    for code, k in cnt.most_common():
        js = [j for j in jours if (_famille(j["final"]) + ((" [%s]" % j["precision"]) if j["precision"] else "")) == code]
        hv = sorted(j["h_valide"] for j in js if j["h_valide"])
        out.append("| %s | %d | %d | %.1f | %s |" % (code, k, sum(j["valide_final"] for j in js),
                                                     np.mean([j["bascules"] for j in js]), hv[len(hv) // 2] if hv else "—"))
    raisons = collections.Counter(j["raison_autre"] for j in jours if j["final"] == "S_AUTRE")
    out += ["", "S_AUTRE par raison : " + (", ".join("%s %d" % (r, k) for r, k in raisons.most_common()) or "aucune"),
            "Position d'ouverture : " + ", ".join("%s %d" % (p, k) for p, k in collections.Counter(j["position"] for j in jours).most_common()),
            "Type d'ouverture : " + ", ".join("%s %d" % (p, k) for p, k in collections.Counter(j["type"] for j in jours).most_common()),
            "Bascules par journée : moyenne %.2f, max %d" % (np.mean([j["bascules"] for j in jours]), max(j["bascules"] for j in jours)),
            "", "<details><summary>par jour</summary>", "",
            "| jour | ouvre | type | à 10h30 (validé) | final [précision] (validé) | bascules | 1re validation |", "|---|---|---|---|---|---|---|"]
    out += ["| %s | %s | %s | %s (%s) | %s%s (%s) | %d | %s |" % (
        j["jour"], j["position"], j["type"], j["s10"], "oui" if j["v10"] else "non", j["final"],
        " [%s]" % j["precision"] if j["precision"] else "", "oui" if j["valide_final"] else "non", j["bascules"], j["h_valide"] or "—")
        for j in jours]
    out += ["", "</details>", ""]
    return out


def main():
    s = lot.seuils()
    att = s["attendu_rejeu"]
    rng = np.random.default_rng(20260910)
    out = ["# La grammaire v0 sur le lot — les trois mesures de la spec §4.4 (module SCÉNARIOS)", "",
           "*Attendu pré-enregistré par la relectrice (Fable, 10/09) : couverture 60 % (45-80), validés à 10h30",
           "encore vrais à 16h00 : 55 % (≥ 40), contrôle négatif battu d'au moins 15 points. Grammaire :",
           "`scenarios/grammaire.py` ; zones : `zones.py` ; seuils : `seuils.yaml` v2026-09-10b. Rejeu",
           "rétrospectif sur les 57 journées (le direct rend la même chose barre à barre : `test_grammaire` [8]).",
           "Aucun devenir de trade, aucune direction attendue.*", ""]
    for sym in ("ES", "NQ"):
        out += bloc(sym, mesurer(sym, s), att, rng)
    os.makedirs(os.path.dirname(RAPPORT), exist_ok=True)
    open(RAPPORT, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("\n".join(l for l in out if not l.startswith("| 2026")))
    print("rapport :", RAPPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
