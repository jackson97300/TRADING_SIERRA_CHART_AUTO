"""V3 — LE LANCEUR : il ne doit JAMAIS demarrer un second ecrivain.

    python -X utf8 V3/tests/test_lanceur.py

POURQUOI CE TEST EXISTE. Le 08/09, deux coureurs ont tourne en meme temps sans
que personne le voie : le PC sous le code du gel, le VPS sous celui de la
veille. Resultat, aucun journal live ne fait foi jusqu'a la bascule. Le lanceur
est justement un bouton qui DEMARRE des choses, et Jackson va cliquer dessus
plusieurs fois par jour. S'il demarre un second ecrivain, il refabrique
l'incident, en pire : deux ecrivains sur le MEME journal.

Le defaut serait SILENCIEUX — deux ecrivains qui ecrivent des lignes correctes
ne levent aucune exception. C'est la leçon du JavaScript muet du 11/09 : ce qui
ne plante pas n'est pas teste pour autant. D'ou un test qui verifie la
DECISION (demarrer ou non), sans jamais lancer de processus.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.execution import garde_scenarios, lanceur                 # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-68s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def _avec_age(age, relances):
    """Remplace l'age du battement et compte les relances — aucun processus."""
    vrai_age, vrai_relancer = garde_scenarios.age_heartbeat, garde_scenarios.relancer
    garde_scenarios.age_heartbeat = lambda *a, **k: age
    garde_scenarios.relancer = lambda *a, **k: relances.append(1)
    try:
        return lanceur.assurer_ecrivain()
    finally:
        garde_scenarios.age_heartbeat, garde_scenarios.relancer = vrai_age, vrai_relancer


def main():
    print("\n[1] l'ecrivain — la seule regle qui compte")
    r = []
    demarre, phrase = _avec_age(5.0, r)
    check("[1a] battement frais : NE demarre PAS", demarre is False and not r, phrase)

    r = []
    demarre, phrase = _avec_age(garde_scenarios.MAX_AGE_S - 1, r)
    check("[1b] juste sous le seuil du garde : NE demarre PAS", demarre is False and not r, phrase)

    r = []
    demarre, phrase = _avec_age(garde_scenarios.MAX_AGE_S + 1, r)
    check("[1c] juste au-dessus du seuil : demarre, une seule fois",
          demarre is True and r == [1], phrase)

    r = []
    demarre, phrase = _avec_age(None, r)
    check("[1d] aucun battement : demarre, une seule fois", demarre is True and r == [1], phrase)

    check("[1e] le seuil est CELUI du garde, pas une copie locale",
          "MAX_AGE_S" not in [n for n in dir(lanceur) if n.isupper()]
          and garde_scenarios.MAX_AGE_S == 300, "une seconde notion de vivant")

    print("\n[2] l'inventaire des processus")
    check("[2a] un motif absent rend False", lanceur.processus_vivant("zzz_pas_de_processus") is False)
    # Temoin DETERMINISTE : le processus qui execute ce test est un python dont
    # la ligne de commande contient « test_lanceur ». Il existe forcement. Sans
    # ce temoin, le test passerait aussi bien avec une fonction qui rend
    # toujours False — et c'est exactement le motif du garde qui sert a TUER
    # l'ecrivain : s'il ne correspond a rien, le garde ne tue jamais rien.
    check("[2b] un motif present rend True (temoin : ce test lui-meme)",
          lanceur.processus_vivant("test_lanceur") is True,
          "l'inventaire ne voit pas le processus courant")
    # Le garde TUE avec ce motif. Une classe de caracteres a une barre oblique
    # inversee de moins (`[\/]`) ne correspond a RIEN et le garde ne tuerait
    # plus jamais un ecrivain accroche — en silence, sans erreur.
    garde_src = (RACINE / "V3" / "execution" / "garde_scenarios.py").read_text(encoding="utf-8")
    check("[2c] le garde tue avec le motif qui correspond vraiment",
          r"scenarios[\\\\/]boucle" in garde_src,
          "classe de caracteres affaiblie : le garde ne tuerait plus rien")

    print("\n[3] l'affichage ne ment pas quand il ne sait pas")
    txt = lanceur.bloc(8765, None, None, None)
    check("[3a] sans battement : le dit", "AUCUN BATTEMENT" in txt, txt[:80])
    check("[3b] sans vitrine : le dit", "MUETTE" in txt, txt[:80])
    txt = lanceur.bloc(8765, None, garde_scenarios.MAX_AGE_S + 10, {"motif": "cash"})
    check("[3c] battement vieux : annonce MUET, pas un etat normal", "MUET depuis" in txt)
    txt = lanceur.bloc(8765, {"jour": "20260911", "source": "rejeu", "avant": {}}, 5.0,
                       {"motif": "hors_cash", "env": {"python": "3.13.4", "pandas": "2.3.3"}})
    check("[3d] etat normal : jour, source et version de pandas affiches",
          "20260911" in txt and "rejeu" in txt and "2.3.3" in txt)

    print("\n[4] la frontiere : le lanceur ne decide rien, n'ecrit aucun journal")
    src = (RACINE / "V3" / "execution" / "lanceur.py").read_text(encoding="utf-8")
    for mot in ("achete", "vends", "conseil", "devrait"):
        check("[4-%s] le mot '%s' est absent" % (mot[:4], mot), mot not in src.lower())
    check("[4e] aucune ecriture dans LOGS/scenarios (journaux de campagne)",
          "LOGS/scenarios" not in src.replace("\\", "/") or "direct_" not in src)

    print("\n[5] la couleur ne doit RIEN decaler")
    # Les codes ANSI sont invisibles a l'ecran mais comptent dans un `%-10s`.
    # Colorer avant de completer decale toutes les colonnes d'une dizaine de
    # caracteres — et personne ne le voit dans un test qui ne lit que des
    # sous-chaines. On compare donc les deux rendus, codes retires.
    etat = {"jour": "20260911", "source": "direct", "carnet": {"ZONE_TROP_LARGE": 1},
            "sym": {"ES": {"heure_et": "09h30", "titre": "S_OUV_HAUT_TEND", "etat_scenario": "en_cours"},
                    "NQ": {"heure_et": "09h30", "titre": "S_DANS_CASSURE_HAUT", "etat_scenario": "valide"}}}
    hb = {"motif": "cash", "env": {"python": "3.13.4", "pandas": "2.3.3"}}
    ansi = re.compile(r"\033\[[0-9;]*m")
    avant = lanceur.COULEUR
    try:
        lanceur.COULEUR = False
        sans = lanceur.bloc(8765, etat, 12.0, hb)
        lanceur.COULEUR = True
        avec = lanceur.bloc(8765, etat, 12.0, hb)
    finally:
        lanceur.COULEUR = avant
    check("[5a] la couleur emet bien des codes", len(ansi.findall(avec)) > 10)
    check("[5b] codes retires, le rendu est IDENTIQUE (aucune colonne decalee)",
          ansi.sub("", avec) == sans, "les codes ANSI decalent le texte")
    check("[5c] sans terminal, aucun code (pas de [32m dans un journal)",
          ansi.search(sans) is None)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
