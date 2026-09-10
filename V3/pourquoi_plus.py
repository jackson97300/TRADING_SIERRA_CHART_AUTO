"""POURQUOI, la suite — les deux lignes qui manquaient (brique 5, Fable 10/09).

    python -X utf8 V3/pourquoi_plus.py [YYYYMMDD] [--ecrire]

1. LES LIEUX SANS RÉACTION DES QUATRE — `LOGS/marges/marges_quatre_<jour>.jsonl`
   (brique 2) : par hypothèse × instrument, l'état, la marge au lieu, l'heure,
   ce qui a manqué. La ligne la plus instructive du journal, absente du
   rapport du soir jusqu'ici.
2. TRADER vs MACHINE — `V3/journal_manuel/<jour>.md` (le clic de Jackson,
   7 champs par trade) face à ce que la machine a vu à la même heure
   (entonnoir + ombre16 + ombre_c2, ± 15 min, même instrument). `--ecrire`
   régénère dans le journal la section « ce que le bot a vu » entre ses deux
   marqueurs — jamais une ligne du trader.

Généré, pas rédigé. Aucun devenir : ni issue, ni P&L (`issue` du trader est
SA colonne, la machine ne la lit pas). Appelé par `pourquoi.py` à 23h01.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import recalc                                # noqa: E402

MARQUE_DEBUT = "<!-- machine:debut -->"
MARQUE_FIN = "<!-- machine:fin -->"
FENETRE_MIN = 15


def _heure(ts):
    m = int(recalc.minutes_et(pd.Series([pd.Timestamp(int(ts), unit="ms",
                                                      tz="UTC")])).iloc[0])
    return m, "%02d:%02d" % divmod(m, 60)


def _jsonl(chemin):
    """Les lignes JSON d'un journal ; une ligne tronquee est sautee, jamais
    fatale (meme tolerance que `pourquoi.charger`)."""
    if not os.path.exists(chemin):
        return None
    out = []
    for ln in open(chemin, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def lieux_sans_reaction(jour):
    """1. Par hypothèse × instrument : l'état de la journée et ce qui a manqué."""
    L = _jsonl("LOGS/marges/marges_quatre_%s.jsonl" % jour)
    print("LES QUATRE — le lieu, et ce qui a manque (marges_quatre, brique 2) :")
    if L is None:
        print("  AUCUN JOURNAL marges_quatre — l'etape 5b/5 n'a pas tourne : incident.")
        return 1
    corps = [o for o in L if o.get("type") == "marge_quatre"]
    for o in sorted(corps, key=lambda x: (x["sym"], x["hypothese"])):
        etat = o["etat"] + ("(%s)" % o["motif"] if o.get("motif") else "")
        print("  %s %-8s %-30s marge %6s t / seuil %5s  %s  %s" % (
            o["sym"], o["hypothese"], etat,
            o.get("lieu_min_ticks") if o.get("lieu_min_ticks") is not None else "-",
            o.get("seuil_ticks") if o.get("seuil_ticks") is not None else "-",
            o.get("lieu_min_heure_et") or "     ",
            ("manque : %s" % o["reaction_manquante"]) if o.get("reaction_manquante")
            else ""))
    print()
    return 0


def _signaux_machine(jour):
    """[(minutes_et, heure, sym, quoi)] — entonnoir (PASSE/BLOQUE des quatre),
    ombre16, ombre_c2, dedoublonnes par (ts, sym, quoi)."""
    out, vus = [], set()
    for nom, chemin in (("entonnoir", "LOGS/entonnoir/entonnoir_%s.jsonl"),
                        ("ombre16", "LOGS/entonnoir/ombre16_%s.jsonl"),
                        ("ombre_c2", "LOGS/entonnoir/ombre_c2_%s.jsonl")):
        L = _jsonl(chemin % jour) or []
        for o in L:
            if o.get("ts") is None or str(o.get("motif") or "").startswith("jour_muet"):
                continue
            if nom == "entonnoir":
                if o.get("decision") not in ("PASSE", "BLOQUE"):
                    continue
                quoi = "%s %s" % (o.get("hypothese"), o.get("decision"))
            else:
                if o.get("side") is None:
                    continue
                quoi = "%s %s" % (o.get("setup"), "long" if o["side"] > 0 else "short")
            cle = (o["ts"], o.get("sym"), quoi)
            if cle in vus:
                continue
            vus.add(cle)
            m, h = _heure(o["ts"])
            out.append((m, h, o.get("sym"), quoi))
    return sorted(out)


def _lignes_trader(chemin):
    """Les lignes du tableau des clics : | heure_et | sym | side | prix_entree |
    prix_sortie | issue | pourquoi |. Les cellules vides = pas encore de clic."""
    rows = []
    for ln in open(chemin, encoding="utf-8"):
        # l'en-tete, la ligne de separation (`|---|` ou `|:---:|`) et les
        # lignes vides ne sont pas des clics
        if not ln.startswith("|") or "heure_et" in ln or set(ln.strip()) <= {"|", "-", ":", " "}:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0]:
            continue
        cells[1] = cells[1].upper()
        rows.append(cells)
    return rows


def trader_vs_machine(jour, ecrire=False):
    """2. Le clic face aux signaux de la machine a la meme heure (± 15 min)."""
    chemin = "V3/journal_manuel/%s.md" % jour
    print("TRADER vs MACHINE :")
    if not os.path.exists(chemin):
        # pas un incident MACHINE (review R3) : la ligne est a Jackson
        print("  journal manuel ABSENT (%s) — la seule ligne que la machine "
              "n'ecrit pas. Sans elle, l'angle trader de ce jour vaut zero." % chemin)
        print()
        return 0
    machine = _signaux_machine(jour)
    trades = _lignes_trader(chemin)
    if not trades:
        print("  journal present, AUCUN clic note (tableau vide).")
    for t in trades:
        try:
            hh, mm = t[0].split(":")
            m_t = int(hh) * 60 + int(mm)
        except ValueError:
            print("  ligne illisible : %s" % t)
            continue
        proches = [x for x in machine if x[2] == t[1] and abs(x[0] - m_t) <= FENETRE_MIN]
        print("  trader %s %s %s @ %s  |  machine (± %d min) : %s" % (
            t[0], t[1], t[2], t[3], FENETRE_MIN,
            ", ".join("%s %s" % (x[1], x[3]) for x in proches) or "RIEN"))
    print("  la machine, toute la journee : %s" % (
        ", ".join("%s %s %s" % (h, s, q) for _m, h, s, q in machine) or "aucun signal"))
    print()
    if ecrire:
        _ecrire_section(chemin, machine)
    return 0


def _ecrire_section(chemin, machine):
    """Regenere la section « ce que le bot a vu » entre ses marqueurs — et
    RIEN d'autre du fichier (les lignes du trader sont a lui)."""
    txt = open(chemin, encoding="utf-8").read()
    corps = "\n".join("- %s %s %s" % (h, s, q) for _m, h, s, q in machine) or "- aucun signal"
    bloc = "%s\n## Ce que le bot a vu (rempli par la machine, pourquoi_plus)\n%s\n%s" % (
        MARQUE_DEBUT, corps, MARQUE_FIN)
    n_d, n_f = txt.count(MARQUE_DEBUT), txt.count(MARQUE_FIN)
    if n_d != n_f or n_d > 1:
        # review R4 : un marqueur orphelin ferait avaler le texte du trader
        # entre le premier DEBUT et le premier FIN — on REFUSE, on ne devine pas
        print("  REFUS : marqueurs machine incoherents dans %s (%d debut / %d fin)"
              " — a corriger a la main, rien n'est ecrit" % (chemin, n_d, n_f))
        return
    if n_d == 1:
        txt = re.sub(re.escape(MARQUE_DEBUT) + r".*?" + re.escape(MARQUE_FIN),
                     lambda _m: bloc, txt, flags=re.S)     # lambda : pas d'escape
    else:
        txt = txt.rstrip("\n") + "\n\n" + bloc + "\n"
    open(chemin, "w", encoding="utf-8", newline="\n").write(txt)
    print("  -> section machine ecrite dans %s" % chemin)


def tout(jour, ecrire=False):
    return lieux_sans_reaction(jour) + trader_vs_machine(jour, ecrire=ecrire)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jour", nargs="?", default=pd.Timestamp.utcnow().strftime("%Y%m%d"))
    ap.add_argument("--ecrire", action="store_true")
    a = ap.parse_args()
    os.chdir(RACINE)
    return 1 if tout(a.jour, ecrire=a.ecrire) else 0


if __name__ == "__main__":
    sys.exit(main())
