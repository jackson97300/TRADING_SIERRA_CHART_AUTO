"""SCÉNARIOS — l'auto-évaluation (§8) nomme chaque type d'erreur sur un cas
synthétique, et B-SCEN (§9) est en parité de formule avec `barrieres.b_niv`.

    python -X utf8 V3/tests/test_scenarios_soir.py

  1. Chaque erreur nommée sur un journal synthétique minimal : VALIDATION_PRECOCE,
     BASCULE_FANTOME (retour en <= N barres ; en N+1 : rien), ZONE_TROP_LARGE,
     ZONE_TROP_ETROITE, ROLE_INVERSE, EXCLUSION_FAUSSE, FUITE (direct != rejeu) ;
     et une journée propre ne produit aucune erreur.
  2. B-SCEN : SL = prix d'invalidation - buffer_sweep_atr x atr x side (DERRIÈRE),
     TP = prix cible - marge_tp_ticks x tick x side (DEVANT), les mêmes nombres que
     le bloc B-NIV du yaml L5 ; sans zone : None + motif ; LONG et SHORT en miroir ;
     aucun mot conclusif dans le texte.
"""
import os
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.layers.L5_risque import barrieres                   # noqa: E402
from V3.scenarios import erreurs, sorties                     # noqa: E402

PASSED = FAILED = 0
SEUILS = {"auto_evaluation": {"bascule_fantome_barres": 4, "etroite_max_ticks": 2}}


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def zone(nom, prix, role="neutre", etat="intacte", n_tests=0, n_tenues=0, dep=None, cote=None, dehors=20.0):
    return {"nom": nom, "prix": prix, "role": role, "dehors_ticks": dehors, "dedans_ticks": 4.0,
            "fiche": {"etat": etat, "n_tests": n_tests, "n_tenues": n_tenues, "depassement_max_ticks": dep,
                      "dernier_cote": cote, "dernier_test_i": 7}}


def journal(n=26, s10="S_OUV_BAS_TEND", v10=True, final=None, vfinal=True, bascules=(), zones=(), hors=(),
            validations=None):
    """26 lignes minimales ; les champs lus par `evaluer` seulement."""
    final = final or s10
    L = []
    for i in range(n):
        sc = final if i >= 5 else s10
        L.append({"i": i, "heure_et": "%02dh%02d" % (9 + (30 + 15 * i) // 60, (30 + 15 * i) % 60),
                  "scenario_en_cours": sc, "precision": None, "valide": (v10 if i <= 4 else vfinal),
                  "validations": validations if validations is not None else
                  [{"i": 2, "quoi": "x", "zone": "prev_val"}] if v10 else [],
                  "bascules": [b for b in bascules if b["i"] <= i], "zones": list(zones),
                  "ce_qui_ne_se_trade_pas": list(hors)})
    return L


def types(errs):
    return sorted({e["type"] for e in errs})


# Les entrees de CONTROLE du couple direct/rejeu, ajoutees le 11/09. Elles ne
# decrivent pas une erreur de lecture du marche mais l'etat du controle
# lui-meme ; les tests 1a-1h portent sur les sept erreurs nommees et ne leur
# passent aucun direct, donc ils recevraient FUITE_NON_VERIFIABLE a chaque
# fois. On les filtre ICI plutot que de faire taire le controle : un controle
# qu'on n'a pas pu faire doit se voir dans le rapport du soir.
CONTROLES = ("FUITE_NON_VERIFIABLE", "DIRECT_AVEUGLE", "VERSION_CHANGEE")


def ev(*a, **k):
    return [e for e in erreurs.evaluer(*a, **k) if e["type"] not in CONTROLES]


def main():
    # 1. les erreurs, une par une
    L = journal(final="S_OUV_BAS_REINT_PULL", validations=[{"i": 2, "quoi": "x", "zone": "prev_val"},
                                                          {"i": 9, "quoi": "pullback_tenu", "zone": "prev_val"}])
    e = ev(L, SEUILS)
    check("[1a] valide a 10h30, autre scenario a 16h -> VALIDATION_PRECOCE, avec ce qui aurait ete juste",
          types(e) == ["VALIDATION_PRECOCE"] and "pullback_tenu" in e[0]["ce_qui_aurait_ete_juste"], e)
    b = [{"i": 6, "de": "S_OUV_BAS_TEND", "vers": "S_OUV_BAS_REINT", "cause": "reintegration_acceptee"},
         {"i": 9, "de": "S_OUV_BAS_REINT", "vers": "S_OUV_BAS_TEND", "cause": "reprise"}]
    e = ev(journal(bascules=b), SEUILS)
    check("[1b] A -> B -> A en 3 barres (<= 4) -> BASCULE_FANTOME", types(e) == ["BASCULE_FANTOME"], e)
    b2 = [dict(b[0]), dict(b[1], i=11)]
    check("[1c] retour en 5 barres (> 4) -> rien", ev(journal(bascules=b2), SEUILS) == [])
    e = ev(journal(zones=[zone("pdh", 120, etat="testee", n_tests=2, n_tenues=0)]), SEUILS)
    check("[1d] zone testee deux fois, 0 tenue, 0 cassure -> ZONE_TROP_LARGE", types(e) == ["ZONE_TROP_LARGE"], e)
    e = ev(journal(zones=[zone("pdh", 120, etat="testee", n_tests=1, n_tenues=1, dep=21.5, dehors=20.0)]), SEUILS)
    check("[1e] tenue avec depassement 21,5 t pour dehors 20 (1,5 t hors bande) -> ZONE_TROP_ETROITE",
          types(e) == ["ZONE_TROP_ETROITE"] and "21.5" in e[0]["ce_qui_aurait_ete_juste"], e)
    e = ev(journal(zones=[zone("pdh", 120, etat="testee", n_tests=1, n_tenues=1, dep=26.0, dehors=20.0)]), SEUILS)
    check("[1f] depassement 6 t hors bande (> 2) -> pas TROP_ETROITE (c'est une cassure tentee)", e == [])
    zs = [zone("prev_vpoc", 105, role="cible", etat="intacte"), zone("prev_val", 100, role="invalidation", etat="cassee", n_tests=1)]
    e = ev(journal(zones=zs), SEUILS)
    check("[1g] cible jamais atteinte + invalidation cassee -> ROLE_INVERSE (et pas TROP_LARGE sur la cassee)",
          types(e) == ["ROLE_INVERSE"], e)
    zs = [zone("prev_val", 100, etat="testee", n_tests=1, n_tenues=1, cote=-1)]
    e = ev(journal(zones=zs, hors=[{"setup": "long@prev_val", "raison": "fade"}]), SEUILS)
    check("[1h] 'long@prev_val ne se trade pas', mais la VAL a tenu par le dessus -> EXCLUSION_FAUSSE",
          types(e) == ["EXCLUSION_FAUSSE"], e)
    L = journal()
    D = [dict(l) for l in L]
    D[8] = dict(D[8], scenario_en_cours="S_AUTRE")
    e = erreurs.evaluer(L, SEUILS, direct=D)
    check("[1i] direct != rejeu a la barre 8 -> FUITE, une seule, marquee INCIDENT",
          types(e) == ["FUITE"] and len(e) == 1 and e[0]["i"] == 8 and "INCIDENT" in e[0]["ce_qui_aurait_ete_juste"], e)
    propre = journal(zones=[zone("prev_val", 100, role="pullback", etat="testee", n_tests=1, n_tenues=1, dep=3.0, cote=-1)],
                     hors=[{"setup": "short@prev_val", "raison": "x"}])
    check("[1j] une journee propre (meme scenario, validee, zones tenues) -> aucune erreur",
          erreurs.evaluer(propre, SEUILS, direct=[dict(l) for l in propre]) == [])
    # --- le controle direct/rejeu porte sur la LIGNE ENTIERE (11/09) ---------
    # Avant, il comparait quatre scalaires. Ni les zones, ni les setups, ni les
    # distances, ni le flux n'etaient regardes : tout ce qu'un tableau de bord
    # afficherait naissait HORS du controle.
    base = journal()
    neuf_rejeu = [dict(l, champ_tout_neuf={"a": 1}) for l in base]
    e = erreurs.evaluer(neuf_rejeu, SEUILS, direct=[dict(l) for l in base])
    check("[1l] un champ NEUF absent du direct -> DIRECT_AVEUGLE (le live en savait moins)",
          types(e) == ["DIRECT_AVEUGLE"] and "champ_tout_neuf" in e[0]["ce_qui_aurait_ete_juste"], e)
    contredit = [dict(l, champ_tout_neuf={"a": 2}) for l in base]
    e = erreurs.evaluer(neuf_rejeu, SEUILS, direct=contredit)
    check("[1m] un champ NEUF qui se CONTREDIT -> FUITE (couvert par defaut, sans liste blanche)",
          types(e) == ["FUITE"], e)
    # la distinction se mesure en PROFONDEUR : le 10/09 a 10h45 le direct portait
    # `setups_armes: []` dans une zone, le rejeu la liste pleine — meme zone, meme
    # nom, donc « different » a la racine et pourtant aucun mensonge.
    profond = [dict(l, zones=[{"nom": "pdh", "setups_armes": [{"setup": "H6p"}], "fiche": {"etat": "intacte"},
                               "role": "neutre", "prix": 1, "dehors_ticks": 20.0}]) for l in base]
    creux = [dict(l, zones=[{"nom": "pdh", "setups_armes": [], "fiche": {"etat": "intacte"},
                             "role": "neutre", "prix": 1, "dehors_ticks": 20.0}]) for l in base]
    e = erreurs.evaluer(profond, SEUILS, direct=creux)
    check("[1n] vide contre plein DANS une structure imbriquee -> AVEUGLE, pas FUITE",
          "FUITE" not in types(e), e)
    e = erreurs.evaluer(base, SEUILS, direct=None)
    check("[1o] aucun direct -> le controle le DIT, il ne se tait pas",
          "FUITE_NON_VERIFIABLE" in types(e), e)
    check("[1k] chaque type d'erreur a un candidat pre-enregistre pour le cycle suivant",
          all(t in erreurs.CANDIDATS for t in ("VALIDATION_PRECOCE", "BASCULE_FANTOME", "ZONE_TROP_LARGE",
                                                "ZONE_TROP_ETROITE", "ROLE_INVERSE", "EXCLUSION_FAUSSE", "FUITE")))
    # 2. B-SCEN
    cfg = barrieres.charger_seuils()["B-NIV"]
    buf, marge = cfg["buffer_sweep_atr"]["ES"], cfg["marge_tp_ticks"]
    zs = [zone("prev_val", 100, role="invalidation"), zone("prev_vpoc", 105, role="cible"), zone("prev_vah", 110, role="cible")]
    s = sorties.b_scen(zs, "S_OUV_BAS_REINT_PULL", +1, 101.0, 8.0, "ES")
    check("[2a] LONG : SL = 100 - %s x 8 (DERRIERE l'invalidation), TP = 105 - %s t (DEVANT la cible la plus proche)" % (buf, marge),
          s["sl_prix"] == round(100 - buf * 8, 2) and s["tp_prix"] == round(105 - marge * 0.25, 2)
          and s["niveau_tp"]["nom"] == "prev_vpoc" and s["motif_sl"] == "zone_invalidation", s)
    check("[2b] memes nombres que le bloc B-NIV du yaml L5 (buffer, marge)",
          s["buffer_sweep_atr"] == buf and s["marge_tp_ticks"] == marge)
    m = [zone("prev_vah", 110, role="invalidation"), zone("prev_vpoc", 105, role="cible"), zone("prev_val", 100, role="cible")]
    t = sorties.b_scen(m, "S_OUV_HAUT_REJET", -1, 109.0, 8.0, "ES")
    check("[2c] SHORT en miroir : SL = 110 + buffer, TP = 105 + marge",
          t["sl_prix"] == round(110 + buf * 8, 2) and t["tp_prix"] == round(105 + marge * 0.25, 2), t)
    u = sorties.b_scen([zone("prev_vpoc", 105, role="cible")], "S_DANS_HEADFAKE", +1, 101.0, 8.0, "ES")
    check("[2d] sans zone d'invalidation contre : sl None + motif, jamais un repli silencieux",
          u["sl_prix"] is None and u["motif_sl"] == "aucune_zone_invalidation_contre" and u["tp_prix"] is not None)
    v = sorties.b_scen([zone("prev_val", 100, role="invalidation")], "S_OUV_BAS_TEND", +1, 101.0, 8.0, "ES")
    check("[2e] sans zone cible dans le sens : tp None + motif", v["tp_prix"] is None and v["motif_tp"] == "aucune_zone_cible_dans_le_sens")
    check("[2f] r_multiple = |tp - entree| / |sl - entree|",
          s["r_multiple"] == round(abs(s["tp_prix"] - 101.0) / abs(s["sl_prix"] - 101.0), 2))
    conclusifs = re.compile(r"\b(va monter|va baisser|devrait|conseil|achete|vend)\b", re.I)
    check("[2g] le texte dit ou le scenario finit et meurt, sans conseil", not conclusifs.search(sorties.texte(s))
          and "se termine a" in sorties.texte(s) and "meurt a" in sorties.texte(s), sorties.texte(s))
    # 3. B5 : le carnet cumule, ne touche rien d'autre
    import hashlib
    import json
    import tempfile
    from V3.scenarios import carnet
    tmp = tempfile.mkdtemp(prefix="carnet_")
    jeux = {"20260901": ["ZONE_TROP_LARGE", "ZONE_TROP_LARGE"], "20260902": ["VALIDATION_PRECOCE"],
            "20260915": ["ZONE_TROP_LARGE", "FUITE"]}
    for j, types_ in jeux.items():
        with open(os.path.join(tmp, "erreurs_%s.jsonl" % j), "w", encoding="utf-8") as f:
            for k, t_ in enumerate(types_):
                f.write(json.dumps({"type": t_, "jour": j, "sym": "ES", "heure_et": "1%dh00" % k, "zone": "pdh",
                                    "scenario": "S_OUV_BAS_TEND", "ce_qui_aurait_ete_juste": "x"}) + "\n")
    seuils_p = RACINE / "V3" / "scenarios" / "seuils.yaml"
    avant = hashlib.sha256(open(seuils_p, "rb").read()).hexdigest()
    c = carnet.agreger(tmp)
    check("[3a] trois jours jouets -> comptes exacts par type, jours, exemple = la premiere occurrence",
          c["types"]["ZONE_TROP_LARGE"]["compte"] == 3 and c["types"]["ZONE_TROP_LARGE"]["jours"] == ["20260901", "20260915"]
          and c["types"]["ZONE_TROP_LARGE"]["exemple"]["jour"] == "20260901" and c["types"]["FUITE"]["compte"] == 1
          and c["par_jour"]["20260902"] == {"VALIDATION_PRECOCE": 1}, c["types"])
    check("[3b] blocs de deux semaines : 01-02/09 ensemble, 15/09 dans un autre bloc, taux par jour",
          len(c["blocs"]) == 2 and any(v["jours"] == 2 and v["par_jour"].get("ZONE_TROP_LARGE") == 1.0 for v in c["blocs"].values()), c["blocs"])
    check("[3c] chaque type porte son candidat pour le cycle suivant", all(v["candidat_cycle_suivant"] for v in c["types"].values()))
    check("[3d] carnet.json ecrit, relu identique ; agreger deux fois = meme resultat (idempotent)",
          carnet.charger(tmp)["types"] == c["types"] and carnet.agreger(tmp)["types"] == c["types"])
    check("[3e] hier(20260915) = le 02/09 (dernier jour AVANT avec un fichier), hier(20260901) = None",
          carnet.hier("20260915", tmp)["jour"] == "20260902" and carnet.hier("20260901", tmp) is None)
    check("[3f] le carnet n'a touche a rien d'autre : seuils.yaml identique",
          hashlib.sha256(open(seuils_p, "rb").read()).hexdigest() == avant)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
