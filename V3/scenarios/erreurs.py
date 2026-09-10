"""SCÉNARIOS — l'auto-évaluation du soir (spec §8) : le module NOTE, il ne se
règle pas. Sur la description, jamais sur un gain ; chaque erreur porte « ce
qui aurait été juste » — la valeur observable qui l'aurait évitée. Le carnet
cumule par type ; les candidats d'ajustement se PRÉ-ENREGISTRENT pour le cycle
suivant ; aucun paramètre ne bouge en campagne.

    python -X utf8 V3/scenarios/erreurs.py [jour]      # le soir, après la clôture

Les erreurs nommées (une définition chacune, `seuils.yaml: auto_evaluation`) :
  VALIDATION_PRECOCE  validé à 10h30, plus vrai à 16h00 (autre scénario, ou
                      plus validé) — juste : la première validation du
                      scénario final, ou « attendre l'acceptation »
  BASCULE_FANTOME     A -> B puis B -> A en <= N barres — juste : ne basculer
                      que sur l'acceptation qui a tenu
  ZONE_TROP_LARGE     zone atteinte ou testée, sans tenue ni cassure de la
                      journée — juste : la bande n'a rien contenu
  ZONE_TROP_ETROITE   tenue dont le dépassement sort de `dehors` de moins de
                      `etroite_max_ticks` — juste : dehors = ce dépassement
  ROLE_INVERSE        la zone `cible` du scénario final jamais atteinte ET une
                      zone `invalidation` cassée — juste : les rôles inversés
  EXCLUSION_FAUSSE    un setup « ne se trade pas » dont la zone a produit une
                      tenue dans son sens — juste : l'exclusion n'a pas tenu
  FUITE               le journal DIRECT diffère du rejeu — un INCIDENT, pas une
                      erreur (`DOCS/INCIDENT_LOG.md`)
Écrit `LOGS/scenarios/scenarios_<jour>.jsonl` (le rejeu), `erreurs_<jour>.jsonl`
et `carnet.py` cumule (`carnet.json`).
"""

from __future__ import annotations

import json
import os
import sys
import time

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.scenarios import lot, scenarios                         # noqa: E402

I_10H30 = 4
# les candidats du cycle suivant vivent dans carnet.py (un seul endroit) ; l'alias reste pour les tests
CANDIDATS = {
    "VALIDATION_PRECOCE": "validation = acceptation (deux clotures), jamais une tentative ; reporter la validation de 10h30",
    "BASCULE_FANTOME": "ne basculer que sur une acceptation qui a tenu une barre de plus",
    "ZONE_TROP_LARGE": "dehors par nature : p75 des depassements au lieu de p80",
    "ZONE_TROP_ETROITE": "dehors par nature : p85 des depassements au lieu de p80",
    "ROLE_INVERSE": "revoir la table des roles du scenario concerne",
    "EXCLUSION_FAUSSE": "revoir la table 'ce qui ne se trade pas' du scenario concerne",
    "FUITE": "INCIDENT : une colonne lue depend de i+2 ou au-dela",
}


def _err(type_, i, heure, zone, scenario, juste, **k):
    return {"type": type_, "i": i, "heure_et": heure, "zone": zone, "scenario": scenario,
            "ce_qui_aurait_ete_juste": juste, **k}


def evaluer(lignes, seuils=None, direct=None):
    """Les erreurs d'une journée (les lignes du rejeu, une par barre) ; si
    `direct` (les lignes du journal direct) est donné, FUITE est cherchée."""
    s = (seuils or lot.seuils())["auto_evaluation"]
    if len(lignes) <= I_10H30:
        return []
    fin, d10 = lignes[-1], lignes[I_10H30]
    out = []
    if d10["valide"] and (fin["scenario_en_cours"] != d10["scenario_en_cours"] or not fin["valide"]):
        v_fin = fin["validations"][-1] if fin["validations"] else None
        out.append(_err("VALIDATION_PRECOCE", I_10H30, d10["heure_et"], d10["validations"][0]["zone"] if d10["validations"] else None,
                        d10["scenario_en_cours"],
                        "%s a %s" % (v_fin["quoi"], lignes[v_fin["i"]]["heure_et"]) if v_fin else "attendre l'acceptation",
                        final=fin["scenario_en_cours"]))
    b = fin["bascules"]
    for k in range(1, len(b)):
        if b[k]["vers"] == b[k - 1]["de"] and b[k]["i"] - b[k - 1]["i"] <= s["bascule_fantome_barres"]:
            out.append(_err("BASCULE_FANTOME", b[k]["i"], lignes[b[k]["i"]]["heure_et"], None, b[k - 1]["vers"],
                            "ne basculer que sur l'acceptation qui a tenu (%s puis retour en %d barres)"
                            % (b[k - 1]["cause"], b[k]["i"] - b[k - 1]["i"])))
    for z in fin["zones"]:
        f = z["fiche"]
        if f["etat"] in ("atteinte", "testee") and not f.get("n_tenues") and f["etat"] not in ("cassee", "regagnee"):
            out.append(_err("ZONE_TROP_LARGE", f.get("dernier_test_i"), fin["heure_et"], z["nom"], fin["scenario_en_cours"],
                            "la bande n'a rien contenu : %d test(s), 0 tenue, 0 cassure" % f["n_tests"]))
        dep = f.get("depassement_max_ticks")
        if f.get("n_tenues") and dep is not None and 0 < dep - z["dehors_ticks"] <= s["etroite_max_ticks"]:
            out.append(_err("ZONE_TROP_ETROITE", f.get("dernier_test_i"), fin["heure_et"], z["nom"], fin["scenario_en_cours"],
                            "dehors = %.1f t (depassement observe), pas %.1f" % (dep, z["dehors_ticks"])))
    cibles = [z for z in fin["zones"] if z["role"] == "cible"]
    invalids = [z for z in fin["zones"] if z["role"] == "invalidation"]
    if cibles and all(z["fiche"]["etat"] == "intacte" for z in cibles) and any(z["fiche"]["etat"] in ("cassee", "regagnee") for z in invalids):
        out.append(_err("ROLE_INVERSE", fin["i"], fin["heure_et"], cibles[0]["nom"], fin["scenario_en_cours"],
                        "cible jamais atteinte, invalidation cassee : les roles etaient inverses"))
    for h in fin["ce_qui_ne_se_trade_pas"]:
        side, nom = h["setup"].split("@")
        z = next((z for z in fin["zones"] if z["nom"] == nom), None)
        if z and z["fiche"].get("n_tenues") and z["fiche"].get("dernier_cote") == (-1 if side == "long" else 1):
            out.append(_err("EXCLUSION_FAUSSE", z["fiche"].get("dernier_test_i"), fin["heure_et"], nom, fin["scenario_en_cours"],
                            "la zone a tenu dans le sens exclu (%s) : l'exclusion n'a pas tenu" % side))
    if direct:
        cle = lambda x: (x["scenario_en_cours"], x.get("precision"), x["valide"], len(x["bascules"]))   # noqa: E731
        par_i = {l["i"]: l for l in direct}
        for l in lignes:
            if l["i"] in par_i and cle(par_i[l["i"]]) != cle(l):
                out.append(_err("FUITE", l["i"], l["heure_et"], None, l["scenario_en_cours"],
                                "INCIDENT : direct %s != rejeu %s" % (cle(par_i[l["i"]]), cle(l))))
                break
    return out


def main(argv):
    os.chdir(RACINE)
    jour = argv[1] if len(argv) > 1 else time.strftime("%Y%m%d")
    # la paire que 5b/5 compare : direct_<jour> (l'ecrivain, barre a barre) contre
    # scenarios_<jour> (le rejeu du soir, ecrit ICI) — FUITE si difference
    direct = scenarios.lire(scenarios.chemin_direct(jour))
    par = scenarios.rejouer_journal(jour)
    toutes = []
    for sym in ("ES", "NQ"):
        lignes = par[sym]
        if not lignes:
            print("== %s %s : rien a evaluer" % (sym, jour))
            continue
        errs = [dict(e, sym=sym, jour=jour) for e in evaluer(lignes, direct=[l for l in direct if l["sym"] == sym] or None)]
        toutes += errs
        print("== %s %s : %s -> %d erreur(s) : %s" % (sym, jour, lignes[-1]["scenario_en_cours"], len(errs),
                                                        ", ".join(e["type"] for e in errs) or "aucune"))
        for e in errs:
            print("     %-18s %s %-12s %s" % (e["type"], e["heure_et"], e["zone"] or "-", e["ce_qui_aurait_ete_juste"]))
    scenarios.ecrire(os.path.join(scenarios.JOURNAL_DIR, "erreurs_%s.jsonl" % jour), toutes)
    from V3.scenarios import carnet                   # B5 : le carnet cumule, un seul ecrivain, recalcule depuis les fichiers
    print(carnet.texte(carnet.agreger()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
