"""Le journal de l'entonnoir, relu — appariement et controle d'effectifs.

Deux fonctions, une seule raison d'etre : ce qu'un rapport affiche doit etre
EXACTEMENT ce que le journal porte. Elles sont sorties de `mesure_57j.py` apres
l'incident du 06/09, ou le tableau annoncait 312 rejets ES pour 282 journalises.
"""

from __future__ import annotations

import collections
import json
import os


def controler_effectifs(lignes, chemin_journal):
    """Le tableau doit porter EXACTEMENT ce que le journal contient.

    Ajoute apres l'incident du 06/09 : le tableau annoncait 312 rejets ES pour
    `POSITION_OUVERTE`, le journal en portait 282. Un effectif faux est
    SILENCIEUX — il resserre les intervalles de confiance et fait sortir du
    bruit ce qui n'en sort pas. Dix secondes de comptage valent mieux qu'une
    conclusion batie sur des effectifs inventes.
    """
    reels = collections.Counter()
    if os.path.exists(chemin_journal):
        for ln in open(chemin_journal, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            o = json.loads(ln)
            if o.get("decision") == "BLOQUE":
                reels[(o["sym"], o["motif"])] += 1
    ecarts = []
    for r in lignes:
        if r["motif"] == "(retenus)":
            continue
        vu = reels[(r["sym"], r["motif"])]
        if r["n_rejetes"] != vu:
            ecarts.append("%s %s : tableau %d, journal %d"
                          % (r["sym"], r["motif"], r["n_rejetes"], vu))
    return ecarts


def _lire_journal(chemin, depuis=0):
    """{ts: [portes qui auraient bloque]} — PLUSIEURS par signal desormais.

    Depuis la correction de Q7, les portes sont evaluees independamment : un
    signal peut etre ferme par news ET par max_trades, et les deux sont
    journalisees. Ne garder qu'un motif par ts reintroduirait exactement le
    biais d'ordre qu'on vient d'eliminer.

    Rend aussi le nombre de lignes lues, pour que l'appelant reprenne au bon
    endroit sans relire tout le fichier a chaque journee.
    """
    out = {}
    n = 0
    if not chemin or not os.path.exists(chemin):
        return out, 0
    for k, ln in enumerate(open(chemin, encoding="utf-8")):
        n = k + 1
        if k < depuis:
            continue
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("decision") == "BLOQUE":
            # cle = SYM:barre:SENS, jamais le ts seul : deux signaux de sens
            # opposes sur la meme barre ont le meme ts et ne doivent pas
            # partager leurs motifs.
            cle = ":".join(str(o.get("snapshot_id", "")).split(":")[:3])
            out.setdefault(cle, []).append(o.get("motif", "?"))
    return out, n
