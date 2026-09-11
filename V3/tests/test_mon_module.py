"""MON MODULE — le biais ne doit JAMAIS pouvoir mentir sur ce qu'il ne sait pas.

    python -X utf8 V3/tests/test_mon_module.py

NE DU DEFAUT DU 11/09, trouve par deux relectures croisees et verifie a la
main. La premiere version de `biais.py` rendait une force en fraction,
`alignees / connues`. Une composante absente sortait du DENOMINATEUR. Mesure
sur les 166 lignes de journal existantes, ou le champ `flux` n'etait present
sur AUCUNE : la page annoncait « BIAIS HAUSSIER, 2 sur 2 » — une unanimite,
batie sur deux capteurs morts. Sur le 10/09, 26 barres sur 26, les deux
instruments : « BAISSIER 2 sur 2 », immobile toute la seance.

La propriete que ces tests defendent, et qui n'est pas negociable :

    UNE PANNE DE CAPTEUR NE DOIT JAMAIS AUGMENTER LA FORCE AFFICHEE.

Le test [1b] la verifie directement : retirer une mesure ALIGNEE ne doit jamais
rendre le resultat plus affirmatif. Avec un denominateur variable, il l'etait
(2/2 se lit mieux que 3/4) — le test echouait sur le fichier d'hier.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.mon_module import biais                                  # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


OUV = {1: "au_dessus", -1: "sous", 0: "dans", None: None}


def ligne(ouv=1, vwap=0.3, cvd=700.0, hvl=1, avec_flux=True):
    d = {"position_ouverture": OUV[ouv], "cote_hvl": hvl}
    if avec_flux:
        d["flux"] = {"vwap_slope_r": vwap, "cvd_sess_r": cvd, "rvol_r": 1.1, "delta_pct": 0.0}
    return d


def main():
    print("\n[1] la cardinalite est FIXE — c'est tout le fichier")
    ok = True
    for ouv, vw, cv, hv in itertools.product((1, -1, 0, None), (0.3, -0.3, 0.0, None),
                                             (700.0, -700.0, 0.0, None), (1, -1, 0, None)):
        b = biais.composer(ligne(ouv, vw, cv, hv))
        if b["hausse"] + b["baisse"] + b["plates"] + b["absentes"] != biais.N_COMPOSANTES:
            ok = False
            break
        if len(b["composantes"]) != biais.N_COMPOSANTES:
            ok = False
            break
    check("[1a] sur les 256 combinaisons : les 4 compteurs totalisent TOUJOURS 4", ok)

    # LE test. Retirer une mesure ALIGNEE ne doit jamais rendre plus affirmatif.
    rang = {"INCOMPLET": 0, "PARTAGE": 1, "HAUSSIER": 2, "BAISSIER": 2}
    pire = None
    for ouv, vw, cv, hv in itertools.product((1, -1, 0), (0.3, -0.3, 0.0),
                                             (700.0, -700.0, 0.0), (1, -1, 0)):
        complet = biais.composer(ligne(ouv, vw, cv, hv))
        ampute = biais.composer(ligne(ouv, None, cv, hv))       # la VWAP meurt
        if rang[ampute["sens"]] > rang[complet["sens"]] or \
           (ampute["absentes"] and ampute["sens"] not in ("INCOMPLET",)):
            pire = (complet["sens"], ampute["sens"])
            break
    check("[1b] une panne de capteur ne rend JAMAIS le biais plus affirmatif", pire is None, pire)

    print("\n[2] le mot directionnel est interdit sur preuves manquantes")
    b = biais.composer(ligne(avec_flux=False))                   # exactement le journal d'hier
    check("[2a] journal sans flux (2 capteurs morts) -> INCOMPLET, jamais HAUSSIER",
          b["sens"] == "INCOMPLET" and b["absentes"] == 2, b["sens"])
    check("[2b] et la phrase affichee ne contient aucun mot directionnel",
          "HAUSSIER" not in biais.phrase_courte(b) and "BAISSIER" not in biais.phrase_courte(b),
          biais.phrase_courte(b))
    check("[2c] AUCUNE fraction n'est rendue (pas de 'X sur Y' dans le contrat)",
          not any(isinstance(v, str) and " sur " in v for v in b.values() if not isinstance(v, list)))

    print("\n[3] deux contre deux est un ETAT, pas un vide")
    b = biais.composer(ligne(ouv=-1, vwap=0.3, cvd=700.0, hvl=-1))
    check("[3a] 2 hausse / 2 baisse -> PARTAGE (et non 'rien')",
          b["sens"] == "PARTAGE" and b["hausse"] == 2 and b["baisse"] == 2, b["sens"])
    check("[3b] PARTAGE et INCOMPLET sont deux mots DIFFERENTS",
          biais.phrase_courte(b) != biais.phrase_courte(biais.composer(ligne(avec_flux=False))))
    quatre = biais.composer(ligne(ouv=1, vwap=0.3, cvd=700.0, hvl=1))
    check("[3c] quatre mesures dans le meme sens -> HAUSSIER, 4 en hausse",
          quatre["sens"] == "HAUSSIER" and quatre["hausse"] == 4, quatre["sens"])

    print("\n[4] alignement : quatre reponses distinctes, jamais un 'neutre' fourre-tout")
    h = biais.composer(ligne(ouv=1, vwap=0.3, cvd=700.0, hvl=1))
    p = biais.composer(ligne(ouv=-1, vwap=0.3, cvd=700.0, hvl=-1))
    i = biais.composer(ligne(avec_flux=False))
    check("[4a] long sur biais haussier -> aligne", biais.alignement("long", h) == "aligne")
    check("[4b] short sur biais haussier -> contre", biais.alignement("short", h) == "contre")
    check("[4c] biais partage -> biais_partage (PAS 'non mesure')",
          biais.alignement("short", p) == "biais_partage")
    check("[4d] biais incomplet -> biais_non_mesure", biais.alignement("short", i) == "biais_non_mesure")
    check("[4e] pas de sens -> non_applicable", biais.alignement(None, h) == "non_applicable")
    check("[4f] les quatre reponses sont bien DISTINCTES",
          len({biais.alignement("long", h), biais.alignement("short", h),
               biais.alignement("short", p), biais.alignement("short", i)}) == 4)

    print("\n[5] le HVL : trois etats, et le trou n'est pas un equilibre")
    check("[5a] cote_hvl None -> composante absente",
          biais.composer(ligne(hvl=None))["absentes"] >= 1)
    check("[5b] cote_hvl 0 (prix SUR le HVL) -> plate, PAS absente",
          biais.composer(ligne(hvl=0))["plates"] >= 1 and biais.composer(ligne(hvl=0))["absentes"] == 0)

    print("\n[6] l'age : une mesure figee doit se voir")
    lignes = [ligne(ouv=1, vwap=0.3, cvd=700.0, hvl=1) for _ in range(12)]
    ages = biais.chronologie(lignes)
    check("[6a] une composante qui ne bouge pas sur 12 barres est annoncee figee",
          ages["ouverture"]["figee"] and ages["hvl"]["figee"], ages)
    bascule = lignes[:6] + [ligne(ouv=1, vwap=-0.3, cvd=700.0, hvl=1) for _ in range(6)]
    ch = biais.chronologie(bascule)
    check("[6b] une composante qui a change il y a 5 barres n'est PAS figee",
          not ch["vwap"]["figee"] and ch["vwap"]["barres_depuis_changement"] == 5, ch["vwap"])

    print("\n[7] la frontiere : aucun mot interdit, aucun pourcentage")
    rendu = json.dumps([biais.composer(ligne()), biais.composer(ligne(avec_flux=False))],
                       ensure_ascii=False) + biais.phrase_courte(biais.composer(ligne()))
    # Motifs ANCRES sur les mots entiers. « acheteur » decrit le SENS d'un CVD
    # mesure : c'est un fait, et le vocabulaire du carnet d'ordres. C'est
    # l'imperatif « achete » qui est un ordre. Un test qui confond les deux
    # force a appauvrir la description pour passer, ce qui est l'inverse du but.
    for motif, quoi in ((r"\bach[eè]te[sz]?\b", "achete"), (r"\bvend[sz]?\b", "vends"),
                        (r"\bconseil", "conseil"), (r"\bdevrait\b", "devrait"),
                        (r"probabilit", "probabilite"), (r"r[eé]ussite", "reussite"),
                        (r"\bconfiance\b", "confiance"), (r"esp[eé]rance", "esperance"),
                        (r"fiabilit", "fiabilite"), (r"%", "pourcentage")):
        m = re.search(motif, rendu, flags=re.I)
        check("[7-%s] '%s' absent de la SORTIE" % (quoi[:5], quoi), m is None,
              m.group(0) if m else "")
    check("[7y] « acheteur » reste permis : c'est le sens d'un CVD mesure, pas un ordre",
          "acheteur" in rendu.lower())
    # Le CODE ne divise aucun compte. La docstring, elle, DOIT pouvoir nommer
    # l'ancienne faute (`alignees / connues`) pour qu'on ne la refasse pas :
    # on grep donc le source PRIVE de sa docstring de module.
    src = (RACINE / "V3" / "mon_module" / "biais.py").read_text(encoding="utf-8")
    code = src.split('"""', 2)[-1]
    check("[7z] le CODE ne calcule aucun taux (aucune division par un compte)",
          "/ connues" not in code and "alignees /" not in code and "/ N_COMPOSANTES" not in code)

    print("\n[8] une ligne ne doit JAMAIS se contredire elle-meme")
    # Mesure du 11/09 : sur un frame ampute, la ligne portait a la fois
    # `setups_armes_motif: frame_sans_recalculs` — « ce frame n'est pas fiable,
    # je n'expose aucun setup » — ET `flux.rvol_r: 0.9259`, un nombre tire de ce
    # meme frame. On ne sait pas laquelle des deux moities croire.
    import pandas as pd
    from V3.scenarios import scenarios as sc
    df = pd.DataFrame({"vwap_slope_r": [0.3], "cvd_sess_r": [700.0],
                       "rvol_r": [1.4], "delta_pct": [0.02]})
    plein = sc._flux(df, 0, recalculs=True)
    vide = sc._flux(df, 0, recalculs=False)
    check("[8a] frame FIABLE : les quatre nombres sont rendus",
          all(v is not None for v in plein.values()), plein)
    check("[8b] frame SANS recalculs : toutes les colonnes `_r` sont videes",
          all(vide[c] is None for c in sc.FLUX_RECALCULES), vide)
    check("[8c] ... et delta_pct, qui n'est pas recalcule, survit",
          vide["delta_pct"] == 0.02, vide)
    check("[8d] les colonnes recalculees sont bien un sous-ensemble du flux lu",
          set(sc.FLUX_RECALCULES) < set(sc.FLUX_LUS))
    check("[8e] une colonne absente vaut None dans les deux cas",
          sc._flux(pd.DataFrame({"delta_pct": [0.02]}), 0)["rvol_r"] is None)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
