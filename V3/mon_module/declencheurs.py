"""LE RADAR DES DECLENCHEURS — deux blocs, deux natures, jamais melanges.

    python -X utf8 V3/mon_module/declencheurs.py [jour]

POURQUOI DEUX BLOCS ET PAS UNE LISTE. La demande d'origine etait « tous les
declencheurs avec leur distance et ce qui leur manque ». Verification faite
dans le code : ce n'est possible que pour LES QUATRE. `marges_quatre.exposer`
les decompose barre par barre — distance au lieu, condition restante, marge en
ticks. Les seize ED et les C2 n'ont rien de tel : leurs modules n'exposent que
`signaux_seize` et `journaliser`, ils produisent des EVENEMENTS, pas un etat
par barre. Un ED n'existe dans le journal que le jour ou il tire.

Alors :
  - RADAR pour ce qui a un etat : les quatre, avec distance, ce qui manque, et
    l'alignement au biais du jour ;
  - JOURNAL D'EVENEMENTS pour ce qui est un evenement : les ombres qui ont
    TIRE dans la journee, avec leur heure. Aucune distance, parce qu'il n'en
    existe aucune.
Melanger les deux sous une seule liste ferait croire a un etat la ou il n'y a
qu'une trace.

LA FORME, TRANCHEE PAR LA MESURE. Sur les quatre jours : 85 % des barres n'ont
AUCUN lieu atteint, et un radar complet ferait trente lignes dont vingt-six
diraient « loin ». Donc en grand, les declencheurs dont le lieu est ATTEINT —
un fait binaire, aucun seuil a inventer. Le reste est replie AVEC SON COMPTE et
la distance du plus proche : le vide est un CHIFFRE, pas un silence. On voit
qu'il n'y a rien, on ne le devine pas.

LE VERROU EST SUR CE CHEMIN. Les lignes du journal C2 portent `rendement_r` et
`rend_pts` — un DEVENIR. Toute ligne d'ombre passe par
`devenir.sans_devenir()` avant d'etre rendue : ce qui n'est pas dans la
structure ne peut pas fuiter a l'ecran. Un test le verifie sur la sortie.
"""

from __future__ import annotations

import json
import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3 import devenir                                            # noqa: E402
from V3.mon_module import biais as B                              # noqa: E402

# `marge_ticks` est en TICKS ; `atr_ref` est en POINTS (MANIFESTE_DONNEES).
# Les melanger est la confusion d'unites la plus frequente de ce depot — sept
# en une semaine, toutes d'un facteur constant. La conversion est ecrite ici,
# une fois.
TICK = 0.25


def _en_atr(marge_ticks, atr_ref_points):
    """Une marge en ticks -> un multiple d'ATR. None si l'ATR manque : on ne
    remplace jamais un ATR absent par un defaut, ca ferait un nombre credible
    et faux."""
    if marge_ticks is None or not atr_ref_points:
        return None
    return round(marge_ticks * TICK / atr_ref_points, 2)


def radar(ligne, sym, b=None):
    """Les QUATRE a cette barre : une entree par (setup, side), avec la
    distance au lieu, ce qui manque, et l'alignement au biais du jour.

    Les entrees viennent de deux endroits que la chaine remplit : celles dont
    le lieu est une ZONE vivent dans `zones[].setups_armes`, les autres dans
    `setups_hors_zones`. Les deux portent les memes champs.
    """
    b = b if b is not None else B.composer(ligne)
    atr = ligne.get("atr_ref")
    out = []
    sources = [(None, s) for s in (ligne.get("setups_hors_zones") or [])]
    sources += [(z.get("nom"), s) for z in (ligne.get("zones") or [])
                for s in (z.get("setups_armes") or [])]
    for nom_zone, s in sources:
        side = s.get("side")
        marge = s.get("marge_ticks")
        out.append({
            "setup": s.get("setup"), "side": side,
            "lieu": s.get("lieu") or nom_zone,
            "lieu_atteint": bool(s.get("lieu_atteint")),
            "manque": s.get("condition_restante"),
            "marge_ticks": marge,
            "marge_atr": _en_atr(marge, atr),
            "alignement": B.alignement(side, b),
        })
    # Tri par distance : une commodite de LECTURE, jamais un pronostic. Le plus
    # proche n'est pas « plus probable » — rien ne le mesure. Le lieu atteint
    # passe devant parce que c'est un FAIT binaire, pas parce qu'il vaut mieux.
    out.sort(key=lambda d: (not d["lieu_atteint"],
                            abs(d["marge_ticks"]) if d["marge_ticks"] is not None else 1e9))
    return out


def _lire(chemin):
    if not os.path.exists(chemin):
        return []
    out = []
    for ln in open(chemin, encoding="utf-8"):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def ombres_tirees(jour, sym):
    """Les ombres qui ont TIRE ce jour-la : des evenements, pas un etat.

    CHAQUE LIGNE PASSE PAR `devenir.sans_devenir()`. Le journal C2 porte
    `rendement_r` et `rend_pts` — un devenir. Sans ce filtre, le module perso
    ferait fuiter un resultat a l'ecran parce que personne n'aurait regarde
    d'ou venait la ligne. C'est exactement la fuite silencieuse qu'on traque.
    """
    out = []
    for fichier, famille in (("ombre16_%s.jsonl", "ED"), ("ombre_c2_%s.jsonl", "C2")):
        for d in _lire(os.path.join(RACINE, "LOGS", "entonnoir", fichier % jour)):
            if d.get("sym") != sym:
                continue
            net = devenir.sans_devenir(d)
            out.append({"famille": famille, "setup": net.get("setup"),
                        "side": net.get("side") or net.get("side_pur"),
                        "ts": net.get("ts"), "heure_et": _heure(net.get("ts")),
                        "motif": net.get("motif")})
    return sorted(out, key=lambda d: d.get("ts") or 0)


def _heure(ts):
    """L'heure ET d'un tir. SANS elle, quatre tirs du meme declencheur a
    quatre moments differents s'affichent comme quatre lignes identiques et se
    lisent comme un doublon — alors que ce sont quatre EVENEMENTS. L'heure est
    ce qui en fait des evenements plutot qu'une liste."""
    if not ts:
        return None
    import pandas as pd
    return pd.to_datetime(int(ts), unit="ms", utc=True).tz_convert(
        "America/New_York").strftime("%Hh%M")


def assembler(ligne, jour, sym):
    """Ce que la page affiche : ce qui est ATTEINT en grand, le reste replie
    avec son compte, et les ombres tirees a part."""
    b = B.composer(ligne)
    r = radar(ligne, sym, b)
    atteints = [d for d in r if d["lieu_atteint"]]
    replies = [d for d in r if not d["lieu_atteint"]]
    proches = [d["marge_ticks"] for d in replies if d["marge_ticks"] is not None]
    return {
        "heure_et": ligne.get("heure_et"),
        "biais": {"sens": b["sens"], "phrase": B.phrase_courte(b)},
        "atteints": atteints,
        "replies": {"n": len(replies),
                    "plus_proche_ticks": min(proches, key=abs) if proches else None,
                    "lignes": replies},
        "ombres_tirees": ombres_tirees(jour, sym),
    }


def texte(a):
    """Le radar en lignes lisibles. Le vide est un CHIFFRE, pas un silence."""
    out = ["  %s   BIAIS : %s" % (a["heure_et"], a["biais"]["phrase"])]
    if a["atteints"]:
        out.append("  LIEU ATTEINT")
        for d in a["atteints"]:
            out.append("     %-10s %-6s %-16s manque %-14s %s"
                       % (d["setup"], "long" if (d["side"] or 0) > 0 else "short",
                          d["lieu"] or "-", d["manque"] or "rien", _align(d["alignement"])))
    else:
        out.append("  LIEU ATTEINT   aucun")
    rep = a["replies"]
    pp = rep["plus_proche_ticks"]
    out.append("  replies        %d autre(s)%s"
               % (rep["n"], ", le plus proche a %.0f t" % abs(pp) if pp is not None else ""))
    om = a["ombres_tirees"]
    if om:
        out.append("  OMBRES QUI ONT TIRE AUJOURD'HUI (evenements, aucune distance)")
        for d in om:
            out.append("     %-6s %-4s %-28s %s"
                       % (d["heure_et"] or "--h--", d["famille"], d["setup"],
                          "long" if (d["side"] or 0) > 0 else "short"))
    else:
        out.append("  ombres         aucune n'a tire aujourd'hui")
    return "\n".join(out)


def _align(a):
    return {"aligne": "aligne au biais", "contre": "CONTRE le biais",
            "biais_partage": "biais partage", "biais_non_mesure": "biais non mesure",
            "non_applicable": ""}.get(a, a or "")


def main(argv):
    from V3.scenarios import boucle, scenarios
    jour = argv[1] if len(argv) > 1 else boucle.maintenant_et()[0]
    lignes = scenarios.lire(scenarios.chemin_direct(jour)) or \
        scenarios.lire(scenarios.chemin_rejeu(jour))
    if not lignes:
        print("  aucune ligne pour %s" % jour)
        return 1
    for sym in sorted({l["sym"] for l in lignes}):
        a_lui = sorted((l for l in lignes if l["sym"] == sym), key=lambda x: x["i"])
        print("\n=== %s %s ===" % (sym, jour))
        print(texte(assembler(a_lui[-1], jour, sym)))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
