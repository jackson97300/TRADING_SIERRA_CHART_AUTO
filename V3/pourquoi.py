"""POURQUOI — la reponse mecanique a « pourquoi zero trade aujourd'hui ? ».

    python -X utf8 V3/pourquoi.py                    # le journal du jour
    python -X utf8 V3/pourquoi.py 20260903           # une date
    python -X utf8 V3/pourquoi.py --journal chemin.jsonl

Lit l'entonnoir et rend, par instrument et par couche : combien de signaux,
combien fermes et par quel motif, les trous a part, les fantomes. C'est le
lecteur qui manquait aux trois projets precedents : le journal existait,
personne ne le resumait — et « pas de trade » restait inexplicable.

Fait partie du rythme quotidien (METHODE.md §6, 21:01 UTC). JAMAIS le P&L.

REGLE D'ARCHITECTURE que ce fichier rend visible : une couche qui n'ecrit pas
dans l'entonnoir n'entre pas dans la chaine. Une couche absente de ce resume
un jour de campagne est un incident, pas un detail.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from datetime import datetime, timezone

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUCHES = ("L0", "REG", "L1", "L3", "L4", "L5", "L6")


def charger(chemin):
    lignes = []
    if not os.path.exists(chemin):
        return lignes
    for ln in open(chemin, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            lignes.append(json.loads(ln))
        except ValueError:
            continue
    return lignes


def resumer(lignes, sym):
    l = [x for x in lignes if x.get("sym") == sym]
    if not l:
        return None
    # un signal = (ts, snapshot sans suffixe :A/:O/:T). Le ts est OBLIGATOIRE
    # dans la cle : le snapshot_id porte l'indice de BARRE, identique d'un jour
    # a l'autre — sans le ts, "ES:14:L" de 60 jours comptait pour UN signal
    # (38 annonces pour ~380 reels au premier run de ce lecteur).
    def cle(x):
        s = str(x.get("snapshot_id") or "")
        return (x.get("ts"), ":".join(s.split(":")[:3]))
    signaux = {cle(x) for x in l if x.get("decision") in ("PASSE", "BLOQUE")}
    passes = {cle(x) for x in l if x.get("decision") == "PASSE"}

    par_couche = {}
    trous = collections.Counter()
    for x in l:
        if x.get("decision") != "BLOQUE":
            continue
        m = str(x.get("motif") or "?")
        if m.startswith("TROU_"):
            trous[m[5:]] += 1
            continue
        c = x.get("couche") or "?"
        par_couche.setdefault(c, collections.Counter())[m] += 1

    fantomes = [x.get("fantome_pnl_atr") for x in l
                if x.get("fantome") and x.get("fantome_pnl_atr") is not None]
    return {"n_signaux": len(signaux), "n_passes": len(passes),
            "par_couche": par_couche, "trous": trous,
            "fantomes_n": len(fantomes), "fantomes_somme": sum(fantomes)}


def afficher(r, sym, n_barres_attendues=26):
    if r is None:
        print("  %s : RIEN DANS L'ENTONNOIR — soit pas de signal, soit une "
              "couche qui n'ecrit pas. Les deux se verifient, aucun ne s'ignore."
              % sym)
        return
    n = max(r["n_signaux"], 1)
    print("  %s — %d signaux bruts, %d retenus (%.0f %%)"
          % (sym, r["n_signaux"], r["n_passes"], 100 * r["n_passes"] / n))
    for c in COUCHES:
        motifs = r["par_couche"].get(c)
        if not motifs:
            continue
        total = sum(motifs.values())
        detail = ", ".join("%s %d" % (m.replace(c + "_", ""), k)
                           for m, k in motifs.most_common(4))
        print("     %s  ferme %3d  (%s)" % (c, total, detail))
    if r["trous"]:
        detail = ", ".join("%s %d" % (m, k) for m, k in r["trous"].most_common(4))
        print("     TROUS (« je ne sais pas », jamais un feu vert) : %s" % detail)
    if r["fantomes_n"]:
        print("     fantomes : %d refuses simules, somme %+.1f ATR"
              % (r["fantomes_n"], r["fantomes_somme"]))
    couches_muettes = [c for c in ("L0", "L5") if c not in r["par_couche"]]
    if couches_muettes and r["n_signaux"]:
        print("     ATTENTION : %s n'a rien ecrit — couche muette ou journee sans"
              " blocage, a departager" % "/".join(couches_muettes))


def ombres(date):
    """Les DEUX autres journaux — sans eux, ce lecteur repondait « zero
    signal » un jour ou NEUF avaient tire (08/09 : 4 ombre16 ES, 5 C2).

    L'entonnoir ne porte que LES_QUATRE ; les seize ED et les C2 actifs ont
    leur journal separe, par construction (ils ne passent pas par la chaine,
    ils fausseraient la position virtuelle des quatre). Une couche absente de
    ce resume est un incident — la docstring de ce fichier le dit, et deux
    couches sur trois y manquaient depuis le premier jour."""
    for nom, motif in (("les SEIZE (ED)", "LOGS/entonnoir/ombre16_%s.jsonl"),
                       ("les C2 actifs", "LOGS/entonnoir/ombre_c2_%s.jsonl")):
        chemin = motif % date
        if not os.path.exists(chemin):
            print("%s : AUCUN JOURNAL — le jour n'a pas ete couru pour eux."
                  % nom)
            continue
        lg = charger(chemin)
        if not lg:
            print("%s : journal VIDE (couru, rien tire)." % nom)
            continue
        par = collections.Counter()
        muets = collections.Counter()
        for o in lg:
            cle = (o.get("sym"), o.get("setup"))
            (muets if o.get("motif") else par)[cle] += 1
        n = sum(par.values())
        print("%s : %d signal(aux)%s" % (
            nom, n, (" + %d lieu(x) sans reaction" % sum(muets.values()))
            if muets else ""))
        for (sym, setup), k in sorted(par.items()):
            print("    %s %-24s %d" % (sym, setup, k))
        for (sym, setup), k in sorted(muets.items()):
            print("    %s %-24s %d (lieu sans reaction)" % (sym, setup, k))
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?",
                    default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    ap.add_argument("--journal", default=None)
    a = ap.parse_args()
    os.chdir(RACINE)

    chemin = a.journal or "LOGS/entonnoir/entonnoir_%s.jsonl" % a.date
    # VIDE et ABSENT ne disent pas la meme chose : vide = le jour a ete couru
    # et n'a rien produit (les declencheurs sont rares par construction) ;
    # absent = le jour n'a jamais ete couru, et LUI est un incident. Les
    # confondre ferait crier « incident » presque chaque soir de campagne.
    existe = os.path.exists(chemin)
    lignes = charger(chemin)
    if not existe:
        # repli : le dernier journal de mesure, pour que la commande reponde
        # toujours quelque chose de verifiable
        cands = sorted(glob.glob("LOGS/entonnoir/*.jsonl"),
                       key=os.path.getmtime)
        if cands and a.journal is None:
            chemin = cands[-1]
            lignes = charger(chemin)
            existe = True
            print("POURQUOI — pas de journal pour %s ; lecture du plus recent :"
                  % a.date)
    print("source : %s (%d lignes)\n" % (chemin, len(lignes)))
    if not existe:
        print("  AUCUN JOURNAL. Un jour de campagne sans entonnoir est un "
              "incident (METHODE.md §7), pas une journee calme.")
        return 1
    if not lignes:
        print("  ENTONNOIR VIDE : le jour a ete couru, zero signal des QUATRE.")
        print("  Normal quand les declencheurs sont rares par construction — un")
        print("  jour NON couru serait un fichier ABSENT, et lui est un incident.")
    else:
        for sym in ("ES", "NQ"):
            afficher(resumer(lignes, sym), sym)
            print()
    ombres(a.date)
    print("Ce resume ne montre JAMAIS le P&L (METHODE.md §6). Il repond a une")
    print("seule question : ou chaque signal s'est-il arrete, et pourquoi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
