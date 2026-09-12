"""LE RADAR — deux natures jamais melangees, et AUCUN devenir a l'ecran.

    python -X utf8 V3/tests/test_declencheurs.py

LE TEST QUI COMPTE EST [1]. Les lignes du journal C2 portent `rendement_r` et
`rend_pts` : un DEVENIR, verrouille jusqu'au jour 61. Le radar les lit pour
afficher les ombres qui ont tire. Sans filtre, le module perso ferait fuiter un
resultat a l'ecran — non par malveillance, mais parce que personne n'aurait
regarde d'ou venait la ligne. C'est exactement la fuite silencieuse qu'on
traque depuis une semaine, et c'est Fable qui l'a vue avant qu'une ligne soit
ecrite.

LE RESTE DEFEND LA FORME, tranchee par la mesure :
  - un RADAR pour ce qui a un etat (les quatre : distance, ce qui manque), un
    JOURNAL D'EVENEMENTS pour ce qui est un evenement (les ombres, qui n'ont
    aucune distance parce qu'aucun module n'en calcule) ;
  - les lieux ATTEINTS en grand — un fait binaire, aucun seuil ; le reste
    replie AVEC SON COMPTE, parce que 85 % des barres n'ont aucun lieu atteint
    et qu'un vide doit etre un CHIFFRE, pas un silence.
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

from V3 import devenir                                            # noqa: E402
from V3.mon_module import biais as B                              # noqa: E402
from V3.mon_module import declencheurs as D                       # noqa: E402

# `biais.alignement` doit attendre la convention TEXTUELLE du journal. On le
# verifie sur le comportement, pas sur le source : la chaine « long » doit etre
# acceptee, et un entier +1 doit tomber en `non_applicable` — preuve qu'il ne
# compare pas un side a un nombre.
_B = B.composer({"position_ouverture": "au_dessus", "cote_hvl": 1,
                 "flux": {"vwap_slope_r": 0.3, "cvd_sess_r": 900.0}})
B_ALIGN_TEXTE = (B.alignement("long", _B) in ("aligne", "contre")
                 and B.alignement(1, _B) == "non_applicable")

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def ligne(atteint=False):
    return {"heure_et": "12h00", "atr_ref": 10.0,
            "position_ouverture": "au_dessus", "cote_hvl": 1,
            "flux": {"delta_bar": 400.0, "cvd_sess_r": 900.0, "rvol_r": 1.4,
                     "vwap_slope_r": 0.3, "finish_delta_pct": 0.8,
                     "bar_lower_wick_pct": 0.4, "bar_upper_wick_pct": 0.1,
                     "delta_pct": 0.02},
            "setups_hors_zones": [
                {"setup": "H3-VPOC", "side": "short", "lieu": "cur_vah",
                 "lieu_atteint": atteint, "condition_restante": "finish",
                 "marge_ticks": 0.0 if atteint else 40.0},
                {"setup": "H2p", "side": "long", "lieu": "vwap_rth_sd2d",
                 "lieu_atteint": False, "condition_restante": "lieu",
                 "marge_ticks": 12.0}],
            "zones": []}


def main():
    print("\n[1] AUCUN devenir n'atteint l'ecran — le test que Fable a exige")
    # Une VRAIE ligne C2, telle que le journal la porte : elle a un devenir.
    brute = {"sym": "ES", "setup": "C2_EOD", "side_pur": 1.0, "ts": 1789154100000,
             "motif": "lieu_sans_reaction", "rendement_r": 0.0957, "rend_pts": 2.75,
             "range_pts": 28.75}
    net = devenir.sans_devenir(brute)
    check("[1a] la ligne BRUTE porte bien un devenir (sinon le test ne prouve rien)",
          "rendement_r" in brute and "rend_pts" in brute)
    check("[1b] apres le filtre, plus aucun champ de devenir",
          not any(c in net for c in devenir.CHAMPS_DEVENIR), sorted(net))
    check("[1c] le reste de la ligne survit (setup, sens, heure)",
          net["setup"] == "C2_EOD" and net["ts"] == 1789154100000)
    src = (RACINE / "V3" / "mon_module" / "declencheurs.py").read_text(encoding="utf-8")
    check("[1d] le filtre est SUR LE CHEMIN des ombres, pas seulement disponible",
          "devenir.sans_devenir(d)" in src)
    om = D.ombres_tirees("20260911", "ES")
    dump = json.dumps(om, ensure_ascii=False)
    for mot in ("rendement", "rend_pts", "pnl", "issue"):
        check("[1-%s] « %s » absent des ombres rendues" % (mot[:5], mot),
              mot not in dump.lower(), dump[:90])

    print("\n[2] deux natures, jamais melangees")
    a = D.assembler(ligne(), "20260911", "ES")
    check("[2a] le radar porte une distance, les ombres n'en portent AUCUNE",
          all("marge_ticks" in d for d in a["atteints"] + a["replies"]["lignes"])
          and not any("marge_ticks" in d for d in a["ombres_tirees"]))
    check("[2b] chaque ombre porte son HEURE — sinon quatre tirs se lisent comme un doublon",
          all("heure_et" in d for d in a["ombres_tirees"]))
    txt = D.texte(a)
    check("[2c] le texte nomme les ombres comme des EVENEMENTS",
          "evenements" in txt or not a["ombres_tirees"], txt[:100])

    print("\n[3] la forme : atteint en grand, le reste replie AVEC son compte")
    check("[3a] sans lieu atteint, le bloc le DIT au lieu de disparaitre",
          "aucun" in D.texte(D.assembler(ligne(atteint=False), "20260911", "ES")))
    check("[3b] le replie porte un COMPTE, pas un silence",
          "autre(s)" in D.texte(D.assembler(ligne(), "20260911", "ES")))
    check("[3c] et la distance du PLUS PROCHE",
          a["replies"]["plus_proche_ticks"] == 12.0, a["replies"]["plus_proche_ticks"])
    b = D.assembler(ligne(atteint=True), "20260911", "ES")
    check("[3d] un lieu atteint remonte dans le bloc visible",
          len(b["atteints"]) == 1 and b["atteints"][0]["setup"] == "H3-VPOC")
    check("[3e] le lieu atteint passe DEVANT dans le tri (fait binaire, pas pronostic)",
          D.radar(ligne(atteint=True), "ES")[0]["lieu_atteint"] is True)

    print("\n[4] l'unite : ticks et ATR ne se melangent pas")
    # `marge_ticks` en TICKS, `atr_ref` en POINTS (MANIFESTE_DONNEES).
    check("[4a] 40 ticks avec un ATR de 10 points font 1,0 ATR",
          D._en_atr(40.0, 10.0) == 1.0, D._en_atr(40.0, 10.0))
    check("[4b] un ATR absent rend None, jamais un defaut credible",
          D._en_atr(40.0, None) is None and D._en_atr(40.0, 0) is None)
    check("[4c] une marge absente rend None", D._en_atr(None, 10.0) is None)

    print("\n[5] l'alignement au biais vient d'un seul endroit")
    aligns = {d["alignement"] for d in D.radar(ligne(), "ES")}
    check("[5a] chaque ligne du radar porte son alignement", None not in aligns and aligns)
    check("[5b] les valeurs sont celles de `biais.alignement`, pas un vocabulaire local",
          aligns <= {"aligne", "contre", "biais_partage", "biais_non_mesure",
                     "non_applicable"}, aligns)

    print("\n[7] LE TYPE DE `side` — un decor qui ne ressemble pas aux donnees ne teste rien")
    # PLANTAGE LATENT du 12/09. `side` est une CHAINE dans les journaux des
    # quatre (800 occurrences sur quatre jours, jamais un entier) ; le code
    # faisait `side > 0`, ce qui leve. Il ne levait pas a l'essai parce que la
    # ligne n'est atteinte que si un lieu est ATTEINT : un plantage qui n'arrive
    # QUE sur les 7 % de barres qui comptent — et c'est la barre du seul signal
    # de la campagne. Le test ne l'a pas vu parce que SA ligne d'exemple portait
    # un entier : un decor qui ne ressemble pas aux donnees ne prouve rien.
    from V3.scenarios import scenarios as SC
    vus = set()
    for j in ("20260908", "20260909", "20260910", "20260911"):
        for l in SC.lire(SC.chemin_rejeu(j)):
            for s in (l.get("setups_hors_zones") or []):
                vus.add(type(s.get("side")).__name__)
            for z in (l.get("zones") or []):
                for s in (z.get("setups_armes") or []):
                    vus.add(type(s.get("side")).__name__)
    check("[7a] les journaux REELS portent `side` en chaine", vus == {"str"}, vus)
    exemple = ligne()["setups_hors_zones"][0]["side"]
    check("[7b] la ligne d'exemple de CE test porte le MEME type que le reel",
          type(exemple).__name__ in vus, (type(exemple).__name__, vus))
    for v, attendu in (("long", "long"), ("short", "short"), ("LONG", "long"),
                       (1, "long"), (-1, "short"), (1.0, "long"),
                       (None, None), ("x", None)):
        check("[7-%s] `_sens(%r)` rend %s" % (str(v)[:4], v, attendu),
              D._sens(v) == attendu, D._sens(v))
    txt_att = D.texte(D.assembler(ligne(atteint=True), "20260911", "ES"))
    check("[7z] un lieu ATTEINT se rend sans lever, avec son sens en toutes lettres",
          "short" in txt_att and "H3-VPOC" in txt_att, txt_att[:120])

    print("\n[8] LA FRONTIERE DES DEUX `side` — deux conventions, deux couches")
    # Il y a DEUX `side` dans ce depot, et ils sont legitimes tous les deux :
    #   - celui de la CHAINE, en memoire, rendu par les hypotheses : un ENTIER
    #     +/-1. `chaine.py`, `vetos.py`, `barrieres.py` le comparent a 0, et
    #     c'est correct.
    #   - celui du JOURNAL, ecrit pour etre relu par un humain : une CHAINE
    #     « long » / « short ».
    # Le plantage du 12/09 vient d'avoir compare le second comme le premier.
    # Ce test fixe la frontiere : tout ce qui lit le JOURNAL passe par `_sens`,
    # et aucun fichier de `mon_module/` ne compare un `side` a un nombre.
    import re as _re
    for f in sorted((RACINE / "V3" / "mon_module").glob("*.py")):
        code = "\n".join(l for l in f.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        corps = code.split('"""')
        corps = "".join(corps[i] for i in range(0, len(corps), 2))   # hors docstrings
        m = _re.search(r"side[a-z_]*\s*(>|<|>=|<=|==|!=)\s*-?\d", corps)
        check("[8a-%s] aucune comparaison numerique sur un `side` de journal" % f.stem,
              m is None, m.group(0) if m else "")
    check("[8b] `biais.alignement` attend bien la convention TEXTUELLE",
          B_ALIGN_TEXTE, "il compare side a un nombre")
    check("[8c] `_sens` est le seul point de passage du radar",
          D.radar(ligne(), "ES")[0]["sens"] in ("long", "short"))

    print("\n[6] la frontiere : aucun mot conclusif")
    rendu = json.dumps(a, ensure_ascii=False) + txt
    for motif, quoi in ((r"\bach[eè]te[sz]?\b", "achete"), (r"\bvend[sz]?\b", "vends"),
                        (r"\bconseil", "conseil"), (r"\bdevrait\b", "devrait"),
                        (r"probabilit", "probabilite"), (r"r[eé]ussite", "reussite")):
        m = re.search(motif, rendu, re.I)
        check("[6-%s] « %s » absent" % (quoi[:5], quoi), m is None, m.group(0) if m else "")

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
