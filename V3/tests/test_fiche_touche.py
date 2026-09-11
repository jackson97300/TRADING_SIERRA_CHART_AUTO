"""LA FICHE DE TOUCHE — elle montre des faits avec leur taux de fond, jamais un score.

    python -X utf8 V3/tests/test_fiche_touche.py

CE QUE CES TESTS DEFENDENT, et chacun vient d'une mesure :

  - AUCUN DECOMPTE. Mesure : « trois signes d'accord » sort sur 19 a 25 % des
    barres SANS aucune zone. Un decompte aurait fait lire du bruit comme une
    reaction. La regle 5 de METHODE et la SPEC L4 §1 l'interdisent deja pour la
    chaine ; la mesure dit que ce serait faux meme ailleurs.
  - UNE LIGNE PAR FAMILLE INDEPENDANTE. delta, CVD et finish s'accordent aux
    deux tiers : trois angles d'un meme temoin. Sur trois lignes, ils feraient
    lire trois confirmations.
  - LE VOLUME NE VOTE PAS. Il s'accorde avec les autres une fois sur deux : il
    dit une intensite, pas un sens.
  - CHAQUE SIGNE PORTE SON TAUX DE FOND. « acheteur » seul est un piege quand
    ca arrive sur 54 % des barres.
  - UNE SEULE ZONE. Deux zones organiseraient une course, et une course a
    toujours un gagnant — y compris quand il n'y a rien a lire.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.mon_module import fiche_touche as FT                      # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def zone(nom="prev_val", bas=99.0, haut=101.0, **k):
    f = {"etat": "testee", "n_tests": 2, "n_tenues": 1, "depassement_max_ticks": 3.0}
    f.update(k.pop("fiche", {}))
    return {"nom": nom, "bas": bas, "haut": haut, "prix": 100.0, "role": "neutre",
            "nature": "VA_veille", "dedans_ticks": 4.0, "dehors_ticks": 20.0,
            "provisoire": False, "dormant": False, "setups_armes": [], "fiche": f, **k}


def ligne(close=100.0, zones=None, flux=None, **k):
    return {"i": 10, "sym": "ES", "heure_et": "12h00", "close": close,
            "zones": zones if zones is not None else [zone()],
            "setups_hors_zones": [], "prochaine_zone_haut": "pdh",
            "prochaine_zone_bas": "pdl",
            "flux": flux if flux is not None else
            {"delta_bar": 400.0, "cvd_sess_r": 900.0, "finish_delta_pct": 0.8,
             "bar_lower_wick_pct": 0.45, "bar_upper_wick_pct": 0.1, "rvol_r": 1.5}, **k}


def main():
    t = FT.taux_fond()

    print("\n[1] elle DORT hors zone, et une seule zone l'ouvre")
    check("[1a] prix hors de toute bande -> dort",
          FT.fiche(ligne(close=150.0), "ES", t).get("dort") is True)
    check("[1b] prix dans la bande -> la fiche s'ouvre",
          FT.fiche(ligne(), "ES", t).get("zone", {}).get("nom") == "prev_val")
    deux = [zone("prev_val", 99.0, 101.0), zone("pdh", 120.0, 122.0)]
    f = FT.fiche(ligne(zones=deux), "ES", t)
    check("[1c] deux zones existent, UNE SEULE est ouverte (pas de course)",
          f["zone"]["nom"] == "prev_val" and isinstance(f["voisines"], dict))
    check("[1d] une zone DORMANTE (0DTE avant 14h) n'ouvre rien",
          FT.fiche(ligne(zones=[zone("mq_put_0dte", dormant=True)]), "ES", t).get("dort") is True)

    print("\n[2] AUCUN decompte — ni dans la sortie, ni dans le code")
    f = FT.fiche(ligne(), "ES", t)
    dump = json.dumps(f, ensure_ascii=False) + FT.texte(f)
    check("[2a] la sortie ne contient jamais « n pour / n contre »",
          not re.search(r"\d+\s*(pour|contre)\b", dump, re.I), dump[:80])
    check("[2b] ni « X sur Y » applique a des signes",
          not re.search(r"\b\d+\s*(sur|/)\s*\d+\b", FT.texte(f)), FT.texte(f)[:80])
    src = (RACINE / "V3" / "mon_module" / "fiche_touche.py").read_text(encoding="utf-8")
    corps = src.split('"""', 2)[-1]
    check("[2c] le CODE ne somme aucune famille",
          "sum(" not in corps.replace("sum(membres)", ""), )

    print("\n[3] une ligne par FAMILLE — delta et CVD ne se comptent pas deux fois")
    b = f["barre"]
    check("[3a] delta, CVD et finish sont dans la MEME famille",
          set(b["flux_forme"]["valeurs"]) == {"delta", "CVD depuis 17h ET", "cloture dans le range"},
          sorted(b["flux_forme"]["valeurs"]))
    check("[3b] la meche est une famille SEPAREE", "penche" in b["meche"] and "basse" in b["meche"])
    check("[3c] le volume QUALIFIE et ne penche jamais",
          "intensite" in b["volume"] and "penche" not in b["volume"], sorted(b["volume"]))

    print("\n[4] chaque signe porte son TAUX DE FOND — sinon il ment")
    check("[4a] flux+forme porte son taux de fond", b["flux_forme"]["taux_fond"] is not None)
    check("[4b] meche porte son taux de fond", b["meche"]["taux_fond"] is not None)
    check("[4c] volume porte son taux de fond", b["volume"]["taux_fond"] is not None)
    check("[4d] quand les deux penchent, le taux de fond DE CET ACCORD est rendu",
          f["les_deux_penchent"] and f["les_deux_penchent"]["taux_fond"] is not None,
          f.get("les_deux_penchent"))
    check("[4e] le texte affiche le taux a cote du signe, pas ailleurs",
          "[fond 54 %]" in FT.texte(f), FT.texte(f)[:120])

    print("\n[5] l'absence est DECLAREE, jamais comptee comme « rien contre »")
    vide = FT.fiche(ligne(flux={}), "ES", t)
    check("[5a] sans flux, la famille ne penche pas et dit pourquoi",
          vide["barre"]["flux_forme"]["penche"] is None and vide["barre"]["flux_forme"].get("motif"))
    check("[5b] sans flux, aucun accord n'est proclame", vide["les_deux_penchent"] is None)
    check("[5c] une mesure absente s'ecrit « - », jamais « None » ni 0",
          "None" not in FT.texte(FT.fiche(ligne(zones=[zone(fiche={"n_tenues": None,
                                                                  "depassement_max_ticks": None})]), "ES", t)))

    print("\n[6] l'avertissement mesure est TOUJOURS la")
    check("[6a] la fiche porte l'ecart zone / hors zone", f["discrimination"] is not None)
    check("[6b] et le verdict en toutes lettres dans le texte",
          "ne distinguent pas" in FT.texte(f))

    print("\n[7] la frontiere : aucun devenir, aucun mot conclusif")
    # Motifs ancres sur les mots ENTIERS. « acheteur » decrit le sens d'un flux
    # mesure — c'est le vocabulaire du carnet, un fait. C'est l'imperatif
    # « achete » qui serait un ordre. Un test qui confond les deux force a
    # appauvrir la description pour passer, ce qui est l'inverse du but.
    for motif, quoi in ((r"\bpnl\b", "pnl"), (r"\bissue\b", "issue"),
                        (r"gagn", "gagnant"), (r"\bach[eè]te[sz]?\b", "achete"),
                        (r"\bvend[sz]?\b", "vends"), (r"\bconseil", "conseil"),
                        (r"\bdevrait\b", "devrait"), (r"r[eé]ussite", "reussite")):
        m = re.search(motif, dump, re.I)
        check("[7-%s] « %s » absent de la sortie" % (quoi[:5], quoi), m is None,
              m.group(0) if m else "")
    check("[7y] « acheteur » reste permis : c'est le sens d'un flux mesure",
          "acheteur" in dump.lower())
    check("[7z] aucune colonne inventee par le squelette n'est cherchee",
          not any(c in corps for c in ("C_ACCEL", "C_DIV", "C_EDGE", "vitesse_approche_r")))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
