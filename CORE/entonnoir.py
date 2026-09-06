"""L'entonnoir — journal des decisions, couche par couche.

Ce qui a tue les trois bots precedents n'est pas d'avoir refuse des trades :
c'est de n'avoir jamais su ce que les refuses seraient devenus. Quinze
validateurs non traces, des seuils cales sur les jours de test, et aucune mesure
du devenir des rejetes — on ouvrait une porte au hasard, ou on la fermait au
hasard.

Ce module existe AVANT le premier signal. Il n'a pas d'autre role que de rendre
mesurable la question : **cette porte laisse-t-elle partir des trades gagnants ?**

SCHEMA D'UNE LIGNE — les huit champs sont obligatoires
-------------------------------------------------------
    ts            horodatage de la barre de decision, ms epoch UTC
    sym           ES ou NQ
    couche        L0 | L1 | L2 | L3 | L4 | L5 | L6
    hypothese     H1..H10, ou le nom de la regle pour L0/L5
    decision      PASSE | BLOQUE
    motif         pourquoi — jamais vide sur un BLOQUE
    snapshot_id   identifiant de l'etat lu, pour rejouer la decision
    devenir_atr   REMPLI 20 BARRES PLUS TARD, en multiples d'ATR-5m

Le dernier champ est la raison d'etre du fichier. Sans lui, on sait ce qu'on a
refuse, pas ce qu'on a manque — et c'est exactement l'aveuglement de janvier.
Il est ecrit `null` a la decision, puis complete par `completer_devenir()`.

Un `motif` vide sur un BLOQUE fait lever une exception : une porte qui se ferme
sans dire pourquoi est une porte qu'on ne pourra pas juger.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

CHAMPS = ("ts", "sym", "couche", "hypothese", "decision", "motif",
          "snapshot_id", "devenir_atr")
COUCHES = {"L0", "L1", "L2", "L3", "L4", "L5", "L6"}
DECISIONS = {"PASSE", "BLOQUE"}

# Horizon du devenir : le meme que l'expiration de la triple barriere de la
# mission, pour que « ce que le rejete serait devenu » se compare a « ce que
# l'accepte est devenu ».
HORIZON_BARRES = 20

_DOSSIER = "LOGS/entonnoir"


def chemin_du_jour(jour: str | None = None) -> str:
    j = jour or datetime.now(timezone.utc).strftime("%Y%m%d")
    return os.path.join(_DOSSIER, "entonnoir_%s.jsonl" % j)


def journaliser(ts, sym, couche, hypothese, decision, motif="",
                snapshot_id=None, chemin=None, extra=None):
    """Ecrit une decision. Rend la ligne ecrite.

    Leve `ValueError` si un BLOQUE n'a pas de motif : c'est la seule regle
    dure de ce module.

    `extra` ajoute des champs a la ligne, sans jamais ecraser les huit du
    schema. Il sert aux TRADES FANTOMES : un signal bloque par une porte
    d'existence — `L0_POSITION_OUVERTE` — est simule en entier, et porte alors
    `fantome`, `meme_sens`, `barres_depuis_entree`, `issue_position_ouverte`.
    Bloquer ne suffit pas : il faut savoir ce que la porte COUTE.
    """
    if couche not in COUCHES:
        raise ValueError("couche inconnue : %r" % couche)
    if decision not in DECISIONS:
        raise ValueError("decision inconnue : %r" % decision)
    if decision == "BLOQUE" and not str(motif).strip():
        raise ValueError(
            "un BLOQUE sans motif ne peut pas etre juge : %s / %s"
            % (couche, hypothese))
    ligne = {"ts": int(ts), "sym": str(sym), "couche": couche,
             "hypothese": str(hypothese), "decision": decision,
             "motif": str(motif), "snapshot_id": snapshot_id,
             "devenir_atr": None}
    for k, v in (extra or {}).items():
        if k not in CHAMPS:                    # les huit du schema sont intouchables
            ligne[k] = v
    c = chemin or chemin_du_jour(
        pd.Timestamp(int(ts), unit="ms", tz="UTC").strftime("%Y%m%d"))
    os.makedirs(os.path.dirname(c), exist_ok=True)
    with open(c, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def completer_devenir(chemin, prix_par_sym, horizon=HORIZON_BARRES, col_atr="atr5"):
    """Remplit `devenir_atr` sur toutes les lignes qui l'ont a `null`.

    `prix_par_sym` : {"ES": df, "NQ": df} ou chaque df porte `ts`, `close` et
    la colonne d'ATR nommee par `col_atr`, trie par `ts`.

    **Les barres doivent etre celles de 5 min, et `col_atr` l'ATR-5m** — c'est
    le defaut `atr5`, le nom que porte la colonne produite par
    `hypothesis_runner.agreger_5min`. Deux raisons de ne pas y toucher :
      - `horizon` compte des BARRES. Vingt barres de 1 min font vingt minutes,
        vingt barres de 5 min font cent minutes : le devenir mesure ne serait
        pas celui de l'expiration de la triple barriere, et les deux ne se
        compareraient plus.
      - l'ATR 1 min et l'ATR-5m ne sont pas dans le meme rapport selon les
        instruments ; normaliser par le mauvais rend ES et NQ incomparables.
    Passer `col_atr="atr"` reste possible pour un df 1 min, mais alors
    `horizon` doit etre ajuste et le resultat ne se compare plus a la mission.

    Le devenir est signe dans le sens du marche, pas de la decision : c'est au
    lecteur de le rapprocher du sens qu'aurait eu le trade. Une porte qui bloque
    des LONG dans un marche qui monte se voit alors immediatement.

    Rend le nombre de lignes completees.
    """
    if not os.path.exists(chemin):
        return 0
    lignes = []
    with open(chemin, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                lignes.append(json.loads(ln))
    if not lignes:
        return 0

    tables = {}
    for sym, df in prix_par_sym.items():
        if col_atr not in df.columns:
            raise KeyError(
                "colonne d'ATR absente pour %s : %s. Le runner produit "
                "'atr5' via agreger_5min ; ne pas retomber en silence "
                "sur l'ATR 1 min." % (sym, col_atr))
        d = df[["ts", "close", col_atr]].dropna(subset=["ts"]).sort_values("ts")
        d = d.rename(columns={col_atr: "atr"})
        d = d.reset_index(drop=True)
        d["fwd"] = d["close"].shift(-horizon) - d["close"]
        tables[sym] = d

    n = 0
    for l in lignes:
        if l.get("devenir_atr") is not None:
            continue
        d = tables.get(l["sym"])
        if d is None or d.empty:
            continue
        i = int(np.searchsorted(d["ts"].values, l["ts"], side="left"))
        if i >= len(d):
            continue
        atr = d["atr"].iloc[i]
        fwd = d["fwd"].iloc[i]
        if pd.isna(atr) or pd.isna(fwd) or atr <= 0:
            continue
        l["devenir_atr"] = round(float(fwd / atr), 4)
        n += 1

    with open(chemin, "w", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    return n


def bilan(chemin):
    """Ce que chaque porte a laisse partir. -> DataFrame par (couche, motif).

    C'est la seule sortie qui compte : `devenir_moyen` sur les BLOQUE dit si
    la porte protege ou si elle coute. Une porte dont les rejetes ont un
    devenir favorable est une porte a rouvrir — et c'est mesure, pas debattu.
    """
    if not os.path.exists(chemin):
        return pd.DataFrame()
    d = pd.read_json(chemin, lines=True)
    if d.empty:
        return d
    g = (d.groupby(["couche", "decision", "motif"], dropna=False)
           .agg(n=("ts", "size"),
                devenir_moyen=("devenir_atr", "mean"),
                devenir_median=("devenir_atr", "median"),
                mesures=("devenir_atr", "count"))
           .reset_index()
           .sort_values(["couche", "n"], ascending=[True, False]))
    return g
