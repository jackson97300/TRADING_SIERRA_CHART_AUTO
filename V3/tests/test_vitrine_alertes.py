"""SCÉNARIOS — la vitrine, les alertes, le bouton NOTER, la fenêtre, l'écrivain
(A5 de la liste fusionnée), sur des journaux JOUETS dans un répertoire
temporaire — jamais sur `LOGS/` réel.

    python -X utf8 V3/tests/test_vitrine_alertes.py

  1. vitrine : `etat_courant` sur un journal jouet → titre, zones triées par
     distance ; heartbeat mort → écrivain muet ; en_cours → rien d'armé, sorties
     None ; repli sur le rejeu marqué `source: rejeu` ; grep des mots interdits
     sur le HTML et sur /etat.json.
  2. alertes : événement → une ligne + un son ; état → rien ; 9h32 → journalisé,
     pas sonné ; MUET → journalisé, pas sonné ; même événement deux fois → une
     alerte ; grep des mots interdits sur les gabarits.
  3. NOTER : la ligne porte les champs exacts ; « autre » → HORS_SCENARIO ; side
     absent → refus ; rien d'effacé ; `scenarios_visibles` posé et relu.
  4. fenêtre : position écrite / relue ; serveur absent → page « absente ».
  5. écrivain : idempotence par (sym, ts) ; barre incomplète ignorée ; hors cash /
     férié / week-end → aucune écriture, heartbeat quand même.
  6. cohérence des trois : une ligne jouet avec bascule → la page affiche le
     nouveau titre, l'alerte émet, la fenêtre ne fait rien.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.scenarios import (alertes, boucle, fenetre, fraicheur, lot, noter,   # noqa: E402
                          scenarios, vitrine)

PASSED = FAILED = 0
INTERDITS = re.compile(r"\b(va monter|va baisser|devrait|conseil|conseillé|achète|achete|vends|signal|TP conseill|SL conseill)\b", re.I)
T0 = int(pd.Timestamp("2026-09-09 13:30", tz="UTC").value // 1_000_000)


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-74s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def ligne(sym, i, scenario="S_OUV_BAS_TEND", etat="en_cours", bascules=(), validations=(), invalidations=(), ev_zones=()):
    ts = T0 + i * 900_000
    valide = etat == "valide"
    return {"i": i, "ts": ts, "sym": sym, "heure_et": "%02dh%02d" % (9 + (30 + 15 * i) // 60, (30 + 15 * i) % 60),
            "close": 100.0, "atr_ref": 8.0, "scenario_en_cours": scenario, "precision": None, "etat_scenario": etat,
            "titre": "%s (%s)" % (scenario, "valide 10h00" if valide else "en cours, non valide"), "arme": valide,
            "valide": valide, "position_ouverture": "sous", "type_ouverture": "ENCHERE", "cote_hvl": 1,
            "range": None, "ib": None, "sequence_etats": [{"i": 0, "ts": T0, "etat": "OUVRE_SOUS"}],
            "validations": list(validations), "invalidations": list(invalidations), "bascules": list(bascules),
            "evenements_zones": list(ev_zones), "prochaine_zone_haut": "prev_val", "prochaine_zone_bas": "pdl",
            "ce_qui_ne_se_trade_pas": [{"setup": "long@prev_val", "raison": "fade"}],
            "zones": [{"nom": "prev_val", "prix": 104.0, "bas": 103.0, "haut": 111.0, "role": "invalidation" if valide else "neutre",
                       "dehors_ticks": 28.0, "dedans_ticks": 3.2, "provisoire": True, "setups_armes": [],
                       "fiche": {"etat": "intacte", "n_tests": 0}},
                      {"nom": "pdl", "prix": 98.0, "bas": 97.0, "haut": 103.0, "role": "cible" if valide else "neutre",
                       "dehors_ticks": 19.0, "dedans_ticks": 3.2, "provisoire": False, "setups_armes": [],
                       "fiche": {"etat": "testee", "n_tests": 1, "n_tenues": 1}}],
            "grammaire_version": "test", "confiance": None}


def main():
    tmp = tempfile.mkdtemp(prefix="scen_")
    scenarios.JOURNAL_DIR = tmp
    vitrine.HEARTBEAT = os.path.join(tmp, "heartbeat.json")
    vitrine.MESURE_W1 = os.path.join(tmp, "mesure_w1.json")
    boucle.HEARTBEAT = vitrine.HEARTBEAT
    cfg = lot.seuils()
    cfg["alertes"]["muet_fichier"] = os.path.join(tmp, "MUET")      # absolu : os.path.join(RACINE, absolu) = absolu
    jour = "20260909"

    def heartbeat(age_s):
        d = {"quand_utc": (pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=age_s)).isoformat(timespec="seconds")}
        json.dump(d, open(vitrine.HEARTBEAT, "w"))

    # 1. vitrine
    L = [ligne("ES", 0), ligne("ES", 1, etat="valide", validations=[{"i": 1, "ts": T0 + 900_000, "quoi": "acceptation", "zone": "ib_low", "scenario": "S_OUV_BAS_TEND"}]),
         ligne("NQ", 0)]
    scenarios.ecrire(scenarios.chemin_direct(jour), L)
    heartbeat(5)
    e = vitrine.etat_courant(jour, cfg)
    check("[1a] la derniere ligne par sym, titre, zones triees par distance (pdl 98 avant prev_val 104)",
          e["sym"]["ES"]["titre"].startswith("S_OUV_BAS_TEND (valide") and [z["nom"] for z in e["sym"]["ES"]["zones"]] == ["pdl", "prev_val"]
          and e["source"] == "direct" and not e["ecrivain_muet"], e["sym"]["ES"]["titre"])
    check("[1b] scenario valide -> arme, sorties des deux sens presentes (texte 'se termine' / 'meurt')",
          e["sym"]["ES"]["arme"] and e["sym"]["ES"]["sorties"] and "meurt a" in e["sym"]["ES"]["sorties"]["long"]["texte"], e["sym"]["ES"]["sorties"])
    check("[1c] en cours non valide (NQ) -> rien d'arme, sorties None",
          not e["sym"]["NQ"]["arme"] and e["sym"]["NQ"]["sorties"] is None)
    # DEUX ages, jamais un seul (11/09). `heartbeat_age_s` mesure L'ECRIVAIN.
    # Il valait 8 s pendant que la donnee affichee avait 14 minutes : une barre
    # de 15 min servie a une page qui se rafraichit toutes les 15 s. Un voyant
    # vert sur une photo perimee dit le CONTRAIRE de ce qui est.
    check("[1a-bis] l'etat porte DEUX ages distincts, l'ecrivain et la donnee",
          "age_ecrivain_s" in e and "age_donnee_s" in e and e["age_ecrivain_s"] == e["heartbeat_age_s"],
          (e.get("age_ecrivain_s"), e.get("age_donnee_s")))
    ad = e["sym"]["ES"]["age_donnee_s"]
    check("[1a-ter] l'age de la DONNEE se compte depuis la CLOTURE de la barre, pas depuis le battement",
          ad is not None and ad > e["age_ecrivain_s"] and e["age_donnee_s"] == max(
              v["age_donnee_s"] for v in e["sym"].values()), (ad, e["age_ecrivain_s"]))
    check("[1a-quater] chaque instrument porte l'heure a laquelle sa distance a ete calculee",
          all(v.get("heure_reference") == v.get("heure_et") for v in e["sym"].values()))
    # Un instrument ABSENT se DECLARE. Le repli direct -> rejeu se fait par
    # FICHIER : avec ES ecrit et NQ non, le fichier n'est pas vide, donc pas de
    # repli, et NQ disparaissait de la page sans un mot. Lire « rien sur NQ »
    # quand la verite est « NQ n'a pas ete ecrit » est une absence
    # d'information rendue comme une absence d'evenement.
    scenarios.ecrire(scenarios.chemin_direct(jour), [l for l in L if l["sym"] == "ES"])
    solo = vitrine.etat_courant(jour, cfg)
    check("[1a-5] un instrument sans ligne est PRESENT et marque indisponible",
          set(solo["sym"]) == {"ES", "NQ"} and solo["sym"]["NQ"].get("indisponible") is True
          and "NQ" in solo["sym"]["NQ"]["motif"], sorted(solo["sym"]))
    check("[1a-6] l'instrument servi n'est pas abime par l'absent",
          not solo["sym"]["ES"].get("indisponible") and solo["sym"]["ES"]["close"] is not None)
    scenarios.ecrire(scenarios.chemin_direct(jour), [])
    vide = vitrine.etat_courant(jour, cfg)
    check("[1a-7] AUCUN instrument -> les deux marques indisponibles, et `avant` calcule",
          all(v.get("indisponible") for v in vide["sym"].values()) and "avant" in vide)
    # Le SERVEUR peut tourner sous un code perime. Son Python vit en memoire
    # depuis son demarrage ; le HTML est relu a chaque requete. Mesure du
    # 11/09 : processus demarre a 14h59, `vitrine.py` modifie a 17h13, et
    # `/etat.json` ne portait toujours pas les deux ages — le JavaScript neuf
    # les demandait, recevait `undefined`, affichait « donnee : — » en silence.
    e0 = fraicheur.empreinte_code()
    check("[1a-8] l'empreinte du code est stable a donnee constante",
          e0 == fraicheur.empreinte_code() and e0 == fraicheur.EMPREINTE_DEMARRAGE, e0)
    mouchard = os.path.join(os.path.dirname(vitrine.HTML), "_zz_mouchard_test.py")
    try:
        open(mouchard, "w", encoding="utf-8").write("# fichier temporaire du test\n")
        check("[1a-9] un fichier .py qui change fait BOUGER l'empreinte",
              fraicheur.empreinte_code() != e0, fraicheur.empreinte_code())
    finally:
        os.remove(mouchard)
    check("[1a-10] ... et elle revient a l'identique une fois le fichier retire",
          fraicheur.empreinte_code() == e0)
    scenarios.ecrire(scenarios.chemin_direct(jour), L)
    heartbeat(120)
    e2 = vitrine.etat_courant(jour, cfg)
    check("[1d] heartbeat de 120 s > 60 -> ecrivain muet", e2["ecrivain_muet"] and e2["heartbeat_age_s"] >= 120)
    os.remove(scenarios.chemin_direct(jour))
    scenarios.ecrire(scenarios.chemin_rejeu(jour), L)
    check("[1e] sans journal direct -> repli sur le rejeu, marque source: rejeu", vitrine.etat_courant(jour, cfg)["source"] == "rejeu")
    scenarios.ecrire(scenarios.chemin_direct(jour), L)
    html = open(vitrine.HTML, encoding="utf-8").read()
    dump = json.dumps(vitrine.etat_courant(jour, cfg), ensure_ascii=False)
    check("[1f] aucun mot interdit dans vitrine.html ni dans /etat.json", not INTERDITS.search(html) and not INTERDITS.search(dump),
          (INTERDITS.search(html) or INTERDITS.search(dump)))
    check("[1g] NON MESURE w1 tant que mesure_w1.json est absent", e["non_mesure_w1"] is True)
    # [1h] LA SYNTAXE DU JAVASCRIPT. Le 11/09, un caractere d'echappement ecrit comme un
    # VRAI saut de ligne dans un `.join()` a casse TOUT le script : la fenetre affichait
    # ses boutons et plus rien d'autre, et le serveur repondait parfaitement — l'erreur
    # etait muette cote page, et c'est Jackson qui l'a vue. Publie sans etre verifie.
    import shutil, subprocess, tempfile as _tf
    js = html.split("<script>")[1].split("</script>")[0] if "<script>" in html else ""
    node = shutil.which("node")
    if not node:
        check("[1h] syntaxe JS non verifiee (node absent) — a verifier a la main", True)
    else:
        f = os.path.join(_tf.mkdtemp(), "v.js")
        open(f, "w", encoding="utf-8").write(js)
        r = subprocess.run([node, "--check", f], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        check("[1h] le JavaScript de vitrine.html est SYNTAXIQUEMENT valide (node --check)",
              r.returncode == 0, (r.stderr or "").strip().splitlines()[:3])
    # 2. alertes
    b = [{"i": 2, "ts": T0 + 2 * 900_000, "de": "S_OUV_BAS_TEND", "vers": "S_OUV_BAS_REINT", "cause": "reintegration_acceptee"}]
    L2 = L + [ligne("ES", 2, scenario="S_OUV_BAS_REINT", bascules=b, validations=L[1]["validations"],
                    ev_zones=[{"quoi": "CASSEE", "zone": "prev_val", "i": 2}, {"quoi": "TEST", "zone": "pdl", "i": 2}])]
    scenarios.ecrire(scenarios.chemin_direct(jour), L2)
    a = alertes.traiter(jour, cfg["alertes"], jouer=False)
    types = sorted(x["type"] for x in a)
    check("[2a] evenements detectes : validation (barre 1), bascule + zone_cassee (barre 2) ; TEST = un etat, rien",
          types == ["bascule", "validation", "zone_cassee"], types)
    check("[2b] textes depuis les gabarits, <= 10 mots, sans prix ni mot interdit",
          all(len(x["texte"].split()) <= 10 and not re.search(r"\d+\.\d+", x["texte"]) and not INTERDITS.search(x["texte"]) for x in a),
          [x["texte"] for x in a])
    check("[2c] meme evenement au tour suivant -> aucune alerte nouvelle (idempotence)", alertes.traiter(jour, cfg["alertes"], jouer=False) == [])
    check("[2d] 9h32 ET est dans le silence, 9h36 non", alertes.en_silence(572, cfg["alertes"]) and not alertes.en_silence(576, cfg["alertes"]))
    check("[2e] MUET : bascule le marqueur, muet() le voit, une alerte est journalisee sans son",
          alertes.basculer_muet(cfg["alertes"]) is True and alertes.muet(cfg["alertes"])
          and (lambda: (scenarios.ecrire(scenarios.chemin_direct(jour), L2 + [ligne("ES", 3, scenario="S_OUV_BAS_REINT", bascules=b, invalidations=[{"i": 3, "ts": T0 + 3 * 900_000, "quoi": "reprise", "zone": "prev_val", "scenario": "S_OUV_BAS_REINT"}])]),
                        alertes.traiter(jour, cfg["alertes"], jouer=True)))()[1][0]["sonne"] is False)
    alertes.basculer_muet(cfg["alertes"])
    check("[2f] gabarits du yaml : cinq evenements, aucun verbe d'action", set(cfg["alertes"]["gabarits"]) == set(cfg["alertes"]["evenements"])
          and not any(INTERDITS.search(g) for g in cfg["alertes"]["gabarits"].values()))
    # 3. NOTER
    noter.RACINE = tmp
    os.makedirs(os.path.join(tmp, "V3", "journal_manuel"), exist_ok=True)
    et = vitrine.etat_courant(jour, cfg)
    c = noter.ecrire(jour, {"heure_et": "11h07", "sym": "ES", "side": "long", "prix_entree": "7650.25", "issue": "+3",
                            "pourquoi": "pullback tenu sur la VAL un deux trois quatre cinq six sept", "scenario": "S_OUV_BAS_REINT", "zone": "prev_val"}, et)
    t = open(noter.chemin(jour), encoding="utf-8").read()
    check("[3a] la ligne est ecrite avec les champs exacts, pourquoi coupe a dix mots, hors_scenario false",
          "| 11h07 | ES | long | 7650.25 |" in t and c["hors_scenario"] == "false" and len(c["pourquoi"].split()) == 10, c)
    c2 = noter.ecrire(jour, {"heure_et": "11h20", "sym": "ES", "side": "short", "pourquoi": "x", "scenario": "autre", "zone": "pdl"}, et)
    check("[3b] scenario « autre » -> HORS_SCENARIO true, jamais refuse", c2["hors_scenario"] == "true")
    try:
        noter.ecrire(jour, {"heure_et": "11h30", "sym": "ES", "pourquoi": "x"}, et)
        refus = False
    except ValueError:
        refus = True
    check("[3c] side absent -> refus (jamais infere)", refus)
    t2 = open(noter.chemin(jour), encoding="utf-8").read()
    check("[3d] rien d'efface : les deux lignes sont la, le gabarit aussi", "| 11h07 |" in t2 and "| 11h20 |" in t2 and "JOURNAL MANUEL" in t2)
    check("[3e] scenarios_visibles pose puis relu", noter.marquer_visibles(jour, True) == "oui" and noter.visibles(jour) == "oui")
    # 4. fenetre
    fenetre.POSITION = os.path.join(tmp, "pos.json")
    fenetre.ecrire_position({"x": 12, "y": 34, "largeur": 400, "hauteur": 300})
    check("[4a] position ecrite / relue", fenetre.lire_position() == {"x": 12, "y": 34, "largeur": 400, "hauteur": 300})
    check("[4b] serveur absent -> False, page « absente » prete", fenetre.serveur_present("http://localhost:1/", 0.3) is False and "vitrine absente" in fenetre.ABSENTE)
    # 5. ecrivain
    scenarios.ecrire(scenarios.chemin_direct(jour), L)
    neuves = boucle.ecrire_nouvelles(jour, "ES", [ligne("ES", 0), ligne("ES", 1), ligne("ES", 2)], scenarios.lire(scenarios.chemin_direct(jour)))
    check("[5a] idempotence par (sym, ts) : trois lignes proposees, deux deja la -> une ecrite", len(neuves) == 1 and neuves[0]["i"] == 2)
    df = pd.DataFrame({"ts": [T0, T0 + 900_000], "close": [1, 2]})
    brut = pd.DataFrame({"ts": [T0 + 14 * 60_000, T0 + 15 * 60_000 + 5 * 60_000]})
    from V3.scenarios import direct as D
    check("[5b] barre incomplete ignoree (la 2e barre n'a que 6 minutes)", len(D.barres_completes(df, brut)) == 1)
    m, e5 = boucle.un_tour("20260913", 600)
    check("[5c] samedi -> week_end, aucune ecriture, heartbeat quand meme", m == "week_end" and e5 == {} and os.path.exists(boucle.HEARTBEAT))
    check("[5d] 8h00 ET -> hors_cash ; 4 juillet -> ferie", boucle.un_tour("20260910", 480)[0] == "hors_cash" and boucle.un_tour("20260703", 600)[0] == "ferie")
    m5, e5 = boucle.un_tour("20260908", 1000)            # 16h40 ET sur une journee reelle sans lignes jouets dans tmp
    check("[5e] apres la cloture, barres completes non ecrites -> RATTRAPAGE (26 barres par instrument), puis hors_cash",
          m5 == "rattrapage" and e5.get("ES") == 26 and e5.get("NQ") == 26 and boucle.un_tour("20260908", 1000)[0] == "hors_cash", (m5, e5))
    # 6. coherence des trois
    scenarios.ecrire(scenarios.chemin_direct(jour), L2)
    for p in (alertes.chemin_alertes(jour),):
        if os.path.exists(p):
            os.remove(p)
    e6 = vitrine.etat_courant(jour, cfg)
    a6 = alertes.traiter(jour, cfg["alertes"], jouer=False)
    check("[6] une bascule : la page affiche le nouveau titre, l'alerte emet, la fenetre ne fait rien",
          "S_OUV_BAS_REINT" in e6["sym"]["ES"]["titre"] and any(x["type"] == "bascule" for x in a6)
          and fenetre.lire_position() == {"x": 12, "y": 34, "largeur": 400, "hauteur": 300})

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
