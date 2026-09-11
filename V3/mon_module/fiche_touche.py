"""LA FICHE DE TOUCHE — ce qui est vrai a CE niveau, maintenant. Aucun decompte.

    python -X utf8 V3/mon_module/fiche_touche.py [jour]

ELLE DORT HORS ZONE. Elle ne s'ouvre que quand le prix est dans la bande d'une
zone, et sur CETTE zone seulement — jamais sur les deux voisines. Afficher la
reaction du niveau au-dessus ET de celui en dessous organise une course, et une
course a toujours un gagnant : le module produirait un penchant a chaque
hesitation, c'est-a-dire exactement quand il n'y a rien a lire. Les voisines
restent affichees en DISTANCE seule, un fait et pas une lecture.

QUATRE ETAGES, DU PLUS STABLE AU PLUS VOLATIL, ordre fige :
  1. ce que le GELE dit ici (les quatre : lieu atteint ou non, ce qui manque)
  2. la MEMOIRE de la zone — la seule chose que Jackson ne peut pas tenir de
     tete, et la plus precieuse
  3. ce que cette NATURE de zone fait d'habitude (bande mesuree sur le lot)
  4. la BARRE maintenant — et elle vient en dernier POUR UNE RAISON MESUREE

POURQUOI LA BARRE EST EN DERNIER. Mesure sur 48 jours : l'accord des deux
familles arrive sur 57,7 % des barres DANS une zone contre 58,0 % HORS zone sur
ES, 53,5 % contre 52,9 % sur NQ. Ecarts nuls, de signes opposes. **Les signes de
barre ne discriminent pas.** Ils ne sont pas faux, ils sont simplement les memes
partout — donc ils ne peuvent pas, a eux seuls, dire qu'un niveau reagit.

AUCUN DECOMPTE. Ni « 3 pour, 0 contre », ni score, ni jauge. Deux raisons : la
regle 5 de `METHODE.md` (« aucune somme de composantes ») et la SPEC L4 §1
l'interdisent deja pour la chaine ; et la mesure dit que ce serait FAUX meme
ailleurs — delta, CVD et finish s'accordent aux deux tiers, ce sont trois
angles d'un meme temoin. Une ligne par FAMILLE independante, et chaque ligne
porte son TAUX DE FOND : « acheteur — apparait sur 54 % des barres » est
honnete, « acheteur » seul est un piege.

LE VOLUME NE VOTE PAS. `rvol_r` s'accorde avec les autres signes une fois sur
deux : il ne dit pas un sens, il dit une intensite. Il QUALIFIE la touche,
reelle ou molle.

LECTURE SEULE. Lit la ligne de journal, jamais le frame (dix-huit secondes, cf.
mesure du 11/09). N'ecrit rien. Ne lit aucun devenir — le verrou `V3.devenir`
le refuserait de toute facon.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

TAUX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taux_fond.yaml")
SEUIL_MECHE = 0.33          # part du range ; le taux de fond mesure va avec
SEUIL_VOLUME = 1.2          # rvol_r ; qualifie, ne penche jamais


def taux_fond():
    """Les taux mesures, lus du yaml. Jamais recopies dans le code : un nombre
    en double derive, et celui-ci est le garde-fou de toute la fiche."""
    import yaml
    with open(TAUX, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _flux(ligne, col):
    return (ligne.get("flux") or {}).get(col)


def famille_flux_forme(ligne, sym, t):
    """Delta, CVD et finish : UNE famille, pas trois temoins. Mesure d'accord
    entre eux : 66 a 68 %. Les mettre sur trois lignes ferait lire trois
    confirmations la ou il y en a une."""
    membres, valeurs = [], {}
    for col, seuil, nom in (("delta_bar", 0.0, "delta"),
                            ("cvd_sess_r", 0.0, "CVD depuis 17h ET"),
                            ("finish_delta_pct", 0.5, "cloture dans le range")):
        v = _flux(ligne, col)
        valeurs[nom] = v
        if v is not None:
            membres.append(1 if v > seuil else -1)
    if not membres:
        return {"penche": None, "motif": "aucune des trois mesures n'est renseignee",
                "valeurs": valeurs, "taux_fond": None}
    s = sum(membres)
    penche = "acheteur" if s > 0 else ("vendeur" if s < 0 else None)
    return {"penche": penche, "membres_connus": len(membres), "valeurs": valeurs,
            "taux_fond": (t["flux_forme_penche_haut"] or {}).get(sym)}


def famille_meche(ligne, sym, t):
    """La meche dit ce que le delta ne dit pas : accord entre eux 49 a 56 %,
    autant dire aucun lien. C'est ce qui en fait une famille a part."""
    bas, haut = _flux(ligne, "bar_lower_wick_pct"), _flux(ligne, "bar_upper_wick_pct")
    if bas is None and haut is None:
        return {"penche": None, "motif": "meches non renseignees", "taux_fond": None}
    penche = None
    if bas is not None and bas > SEUIL_MECHE:
        penche = "acheteur"          # rejet par le bas
    elif haut is not None and haut > SEUIL_MECHE:
        penche = "vendeur"
    return {"penche": penche, "basse": bas, "haute": haut, "seuil": SEUIL_MECHE,
            "taux_fond": (t["meche_basse_longue"] or {}).get(sym)}


def qualificateur_volume(ligne, sym, t):
    """Le volume QUALIFIE, il ne penche jamais. Mesure : il s'accorde avec les
    autres signes 43 a 53 % du temps — c'est-a-dire aucun lien directionnel."""
    r = _flux(ligne, "rvol_r")
    if r is None:
        return {"intensite": None, "motif": "rvol non renseigne", "taux_fond": None}
    return {"intensite": "reelle" if r > SEUIL_VOLUME else "molle", "rvol": r,
            "seuil": SEUIL_VOLUME, "taux_fond": (t["volume_eleve"] or {}).get(sym)}


def zone_courante(ligne):
    """La zone dont la BANDE contient le prix. Une seule, jamais les voisines.
    Une zone dormante (0DTE avant 14h ET) n'ouvre rien."""
    c = ligne.get("close")
    if c is None:
        return None
    for z in ligne.get("zones") or []:
        if z.get("dormant"):
            continue
        bas, haut = z.get("bas"), z.get("haut")
        if bas is not None and haut is not None and bas <= c <= haut:
            return z
    return None


def gele_ici(ligne, z):
    """Ce que LES QUATRE disent a cet endroit : lieu atteint ou non, ce qui
    manque, la marge. Lu, jamais recalcule."""
    out = list(z.get("setups_armes") or [])
    for s in ligne.get("setups_hors_zones") or []:
        if s.get("lieu") == z.get("nom"):
            out.append(s)
    return out or None


def memoire(z):
    """L'etage le plus precieux : ce que Jackson ne peut pas tenir de tete.
    Combien de contacts, tenue ou non la derniere fois, de combien de ticks
    depassee avant de tenir. Tout vient de la fiche causale de la zone."""
    f = z.get("fiche") or {}
    return {"etat": f.get("etat"), "n_tests": f.get("n_tests"),
            "n_tenues": f.get("n_tenues"), "dernier_tenu": f.get("dernier_tenu"),
            "depassement_max_ticks": f.get("depassement_max_ticks"),
            "provisoire": z.get("provisoire")}


def nature(z):
    """Ce que cette NATURE de zone fait d'habitude : la bande `dehors` est un
    p80 mesure sur le lot, pas un reglage."""
    return {"nature": z.get("nature"), "dedans_ticks": z.get("dedans_ticks"),
            "dehors_ticks": z.get("dehors_ticks")}


def fiche(ligne, sym, t=None):
    """Rend la fiche si le prix est DANS une zone, sinon `{dort: True}`."""
    t = t or taux_fond()
    if not ligne:
        return {"vide": "aucune barre complete"}
    z = zone_courante(ligne)
    if z is None:
        return {"dort": True, "motif": "le prix n'est dans aucune bande"}
    ff, me = famille_flux_forme(ligne, sym, t), famille_meche(ligne, sym, t)
    ensemble = None
    if ff["penche"] and ff["penche"] == me.get("penche"):
        cle = "deux_familles_vers_le_haut" if ff["penche"] == "acheteur" else "deux_familles_d_accord"
        ensemble = {"sens": ff["penche"], "taux_fond": (t[cle] or {}).get(sym), "quoi": cle}
    return {
        "zone": {"nom": z.get("nom"), "prix": ligne.get("close"),
                 "bas": z.get("bas"), "haut": z.get("haut"), "role": z.get("role")},
        "heure_et": ligne.get("heure_et"),
        "gele_ici": gele_ici(ligne, z),
        "memoire": memoire(z),
        "nature": nature(z),
        "barre": {"flux_forme": ff, "meche": me, "volume": qualificateur_volume(ligne, sym, t)},
        "les_deux_penchent": ensemble,
        "voisines": {"haut": ligne.get("prochaine_zone_haut"),
                     "bas": ligne.get("prochaine_zone_bas")},
        "discrimination": (t["discrimination_zone_vs_hors_zone"] or {}).get(sym),
        "avertissement": (t["discrimination_zone_vs_hors_zone"] or {}).get("verdict"),
    }


def _ou(v):
    """Une valeur absente s'ecrit « - », jamais « None » et surtout jamais 0 :
    un zero se lirait « mesure a zero » au lieu de « pas de mesure »."""
    return "-" if v is None else v


def texte(f):
    """La fiche en lignes lisibles. Chaque signe porte son taux de fond."""
    if f.get("dort"):
        return "  la fiche dort : %s" % f["motif"]
    if f.get("vide"):
        return "  %s" % f["vide"]
    z, m, na = f["zone"], f["memoire"], f["nature"]
    pct = lambda x: "-" if x is None else "%.0f %%" % (100 * x)
    out = ["  ZONE  %s  %s - %s   prix %s   (%s ET)"
           % (z["nom"], z["bas"], z["haut"], z["prix"], f["heure_et"]),
           "  1. LE GELE ICI       %s" % (
               " | ".join("%s %s : manque %s" % (s.get("setup"), s.get("side"),
                                                 s.get("condition_restante") or "rien")
                          for s in (f["gele_ici"] or [])) or "aucun des quatre a ce lieu"),
           # `n_tenues` et `depassement_max_ticks` peuvent etre absents : une zone
           # touchee sans tenue n'a pas de compteur. Absent s'ecrit « - », jamais
           # « None » — et surtout jamais 0, qui se lirait « zero tenue mesuree »
           # au lieu de « pas encore de mesure ».
           "  2. MEMOIRE           %s, %s test(s), %s tenue(s), depassement max %s%s"
           % (m["etat"], _ou(m["n_tests"]), _ou(m["n_tenues"]),
              "-" if m["depassement_max_ticks"] is None else "%s t" % m["depassement_max_ticks"],
              "  (bande PROVISOIRE)" if m["provisoire"] else ""),
           "  3. CETTE NATURE      %s, bande mesuree : dedans %s t / dehors %s t"
           % (na["nature"], na["dedans_ticks"], na["dehors_ticks"]),
           "  4. LA BARRE"]
    b = f["barre"]
    out.append("     flux+forme        %-9s [fond %s]" % (b["flux_forme"]["penche"] or "ne penche pas",
                                                          pct(b["flux_forme"]["taux_fond"])))
    out.append("     meche             %-9s [fond %s]" % (b["meche"].get("penche") or "ne penche pas",
                                                          pct(b["meche"].get("taux_fond"))))
    out.append("     volume (qualifie) %-9s [fond %s]" % (b["volume"].get("intensite") or "-",
                                                          pct(b["volume"].get("taux_fond"))))
    if f["les_deux_penchent"]:
        e = f["les_deux_penchent"]
        out.append("     les DEUX familles penchent %s — cela arrive sur %s des barres SANS zone"
                   % (e["sens"], pct(e["taux_fond"])))
    out.append("  RAPPEL  %s (ecart zone/hors zone mesure : %+.1f point)"
               % (f["avertissement"], 100 * (f["discrimination"] or 0)))
    return "\n".join(out)


def main(argv):
    from V3.scenarios import boucle, scenarios
    jour = argv[1] if len(argv) > 1 else boucle.maintenant_et()[0]
    lignes = scenarios.lire(scenarios.chemin_direct(jour)) or \
        scenarios.lire(scenarios.chemin_rejeu(jour))
    if not lignes:
        print("  aucune ligne pour %s" % jour)
        return 1
    t = taux_fond()
    for sym in sorted({l["sym"] for l in lignes}):
        a_lui = sorted((l for l in lignes if l["sym"] == sym), key=lambda x: x["i"])
        print("\n=== %s %s ===" % (sym, jour))
        print(texte(fiche(a_lui[-1], sym, t)))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
