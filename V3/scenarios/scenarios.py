"""SCÉNARIOS — le module vivant (spec §3) : une journée déroulée barre à barre,
les zones (§2), la grammaire (§1), le journal (un écrivain, `.tmp` +
`os.replace`). Ne décide rien, n'entre dans aucune porte, n'écrit que
`LOGS/scenarios/`.

    python -X utf8 V3/scenarios/scenarios.py 20260909            # rejeu d'une journée (ES + NQ) -> scenarios_<jour>.jsonl
    python -X utf8 V3/scenarios/scenarios.py --direct            # la journée en cours, barres complètes -> direct_<jour>.jsonl

Deux journaux DISTINCTS par jour (Fable, liste fusionnée) : `direct_<jour>.jsonl`,
écrit barre à barre par l'écrivain (`boucle.py`, ou `--direct`), et
`scenarios_<jour>.jsonl`, écrit par le rejeu du soir — c'est la paire que le
rythme 5b/5 compare (`FUITE` si différence). Chaque ligne porte
`grammaire_version` et `seuils_version`.

Rétrospectif (`rejouer`) et direct (`direct`) passent par la MÊME fonction
`derouler(df15, brut, sym)` : en direct, `df15` est tronqué aux barres
complètes ; en rejeu, c'est la journée. Le test « direct = rétrospectif »
compare les deux, ligne à ligne.
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from V3 import marges_quatre                                    # noqa: E402
from V3.scenarios import carnet, grammaire, lot, zones as Z      # noqa: E402

I_DEBUT_IB = 4
BARRE_MS = 15 * 60 * 1000
JOURNAL_DIR = os.path.join(RACINE, "LOGS", "scenarios")


def _cote_hvl(df15, i):
    d = pd.to_numeric(df15.get("dist_mq_hvl"), errors="coerce") if "dist_mq_hvl" in df15.columns else None
    if d is None or not np.isfinite(d.iloc[i]) or d.iloc[i] == 0:
        return 0
    return 1 if d.iloc[i] < 0 else -1


def _heure_et(ts):
    m = int(recalc.minutes_et(pd.Series([int(ts)]).pipe(pd.to_datetime, unit="ms", utc=True)).iloc[0])
    return "%02dh%02d" % (m // 60, m % 60)


def _propre(x):
    if isinstance(x, dict):
        return {k: _propre(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_propre(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 4)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def derouler(df15, brut, sym, seuils=None):
    """Une ligne par barre 15 min de `df15` (spec §3). Causal : la ligne i ne
    lit que les barres <= i ; `df15` tronqué ou complet, même résultat."""
    s = seuils or lot.seuils()
    if df15.empty:
        return []
    zones = Z.construire(df15, brut, sym, s)
    bornes = (s["range"]["w_min_atr"][sym], s["range"]["w_max_atr"][sym])
    g = grammaire.Grammaire(sym, zones, bornes)
    veille = float(df15["atr_ref"].iloc[0]) if "atr_ref" in df15.columns else None
    open_type = None
    if len(df15) >= 2:
        o = pd.to_numeric(brut.get("open_cash_lvl"), errors="coerce") if "open_cash_lvl" in brut.columns else None
        o = float(o.dropna().iloc[0]) if o is not None and o.notna().any() else None
        open_type = recalc.open_type_r(df15.iloc[:2], veille, open_lvl=o)
    lignes_range = {}
    if len(df15) > I_DEBUT_IB:
        haut, bas = float(df15["high"].iloc[:I_DEBUT_IB].max()), float(df15["low"].iloc[:I_DEBUT_IB].min())
        lignes_range = {l["i"]: l for l in recalc.range_r(df15, haut, bas, i_debut=I_DEBUT_IB, tick=lot.TICK,
                                                              w_min=bornes[0], w_max=bornes[1])}
    # la decomposition des quatre, lue, jamais recopiee — SEULEMENT sur le frame de la
    # chaine (rvol_r = mediane roulante sur vingt jours, bandes SD2 injectees) : sur un
    # frame sans recalculs, exposer rendrait « rvol faux » (colonne absente) ou, pire,
    # un rvol_r calcule sur trois jours qui existe et qui ment. Alors : aucun setup,
    # et le motif sur la ligne (Fable, relecture 8ba1d64).
    if "rvol_r" in df15.columns and "dist_vwap_rth_sd2u_r" in df15.columns:
        expo, motif_setups = marges_quatre.exposer(df15), None
    else:
        expo, motif_setups = {}, "frame_sans_recalculs"
    out = []
    for i in range(len(df15)):
        if i == I_DEBUT_IB:
            Z.ajouter_ib(zones, df15, sym, I_DEBUT_IB, s)
        ev_zones = Z.observer(zones, df15, i, brut)
        r = g.barre(df15, i, lignes_range.get(i), open_type if i == 1 else None)
        c = float(df15["close"].iloc[i])
        cote = _cote_hvl(df15, i)
        for z in zones:
            if z["nature"] == "MUR_call_put" and z["role"] in (None, "neutre"):
                z["role"] = "rejet" if cote > 0 else "continuation" if cote < 0 else "neutre"
        hors = Z.setups_armes(zones, df15, i, expo)
        ph, pb = Z.prochaines(zones, c)
        r.update({"sym": sym, "heure_et": _heure_et(df15["ts"].iloc[i]), "close": c, "cote_hvl": cote,
                  "range": {k: lignes_range[i][k] for k in ("etat", "evenement", "n_tests_haut", "n_tests_bas",
                                                             "pression", "barres_depuis_pose", "largeur_atr")}
                  if i in lignes_range else None,
                  "zones": Z.exporter(zones, c), "evenements_zones": ev_zones, "setups_hors_zones": hors,
                  "setups_armes_motif": motif_setups,
                  "prochaine_zone_haut": ph, "prochaine_zone_bas": pb})
        r["grammaire_version"], r["seuils_version"] = grammaire.GRAMMAIRE_VERSION, str(s.get("version"))
        out.append(_propre(r))
    return out


def charger(sym, jour, completes_seulement=False):
    """Le MEME frame que la chaine (Fable, A1) : `charger_jour` + la chauffe
    1 min + `injecter_recalculs` (rvol_r, bandes SD2, atr_ref / atr_source).
    Sans l'injection, `marges_quatre.exposer` rendrait « rvol faux » pour une
    colonne ABSENTE — une condition qui ment (test_grammaire [9c])."""
    from CORE.research.hypothesis_runner import injecter_recalculs
    from V3.campagne import COLS_RECALC, chauffe_1min
    df, brut = charger_jour(sym, jour, 15, avec_1min=True)
    if df.empty or brut.empty:
        return df, brut
    if completes_seulement:
        dernier = int(pd.to_numeric(brut["ts"]).max())
        fin = pd.to_numeric(df["ts"]) + BARRE_MS - 60_000
        df = df[fin <= dernier].reset_index(drop=True)
        if df.empty:
            return df, brut
    b = pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]], ignore_index=True)
    df = injecter_recalculs(b, df, minutes=15)
    if "atr_ref" not in df.columns:
        df = lot.avec_metre(df, lot.atr_veille(sym, jour, brut))
    return df, brut


def rejouer(sym, jour):
    df, brut = charger(sym, jour)
    return derouler(df, brut, sym) if not df.empty else []


def chemin_direct(jour):
    return os.path.join(JOURNAL_DIR, "direct_%s.jsonl" % jour)


def chemin_rejeu(jour):
    return os.path.join(JOURNAL_DIR, "scenarios_%s.jsonl" % jour)


def rejouer_journal(jour):
    """Le rejeu du soir des deux instruments -> `scenarios_<jour>.jsonl`
    (réécrit en entier, un écrivain). Rend {sym: lignes}."""
    par = {sym: rejouer(sym, jour) for sym in ("ES", "NQ")}
    lignes = [dict(l, mode="rejeu", ecrit_a=int(time.time() * 1000)) for sym in ("ES", "NQ") for l in par[sym]]
    if lignes:
        ecrire(chemin_rejeu(jour), lignes)
    return par


def ecrire(chemin, lignes):
    """Un écrivain, `.tmp` + `os.replace` : jamais un journal amputé."""
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin + ".tmp", "w", encoding="utf-8") as f:
        for l in lignes:
            f.write(json.dumps(l, ensure_ascii=False, default=str) + "\n")
    os.replace(chemin + ".tmp", chemin)


def lire(chemin):
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def resume(lignes):
    if not lignes:
        return "aucune barre"
    d = lignes[-1]
    seq = " > ".join(e["etat"] + ("(%s)" % e.get("vers", e.get("type", e.get("raison", "")))
                                  if e["etat"] in ("BASCULE", "TYPE_OUVERTURE", "S_AUTRE") else "")
                     for e in d["sequence_etats"])
    return ("%s %s | ouvre %s | %s | bascules %d | %s" % (
        d["sym"], d["heure_et"], d["position_ouverture"], d["titre"], len(d["bascules"]), seq))


def direct(jour=None):
    """La journée en cours sur les barres complètes ; la ligne de la dernière
    barre est ajoutée au journal du jour si elle n'y est pas encore."""
    jour = jour or time.strftime("%Y%m%d")
    for sym in ("ES", "NQ"):
        df, brut = charger(sym, jour, completes_seulement=True)
        if df.empty:
            print("== %s %s : aucune barre 15 min complete" % (sym, jour))
            continue
        lignes = derouler(df, brut, sym)
        chemin = chemin_direct(jour)
        deja = lire(chemin)
        vus = {(l["sym"], l["i"]) for l in deja}
        neuves = [dict(l, mode="direct", ecrit_a=int(time.time() * 1000)) for l in lignes if (l["sym"], l["i"]) not in vus]
        if neuves:
            ecrire(chemin, deja + neuves)
        print("== " + resume(lignes) + " | +%d ligne(s) au journal" % len(neuves))


def main(argv):
    os.chdir(RACINE)
    if len(argv) >= 2 and argv[1] == "--direct":
        direct(argv[2] if len(argv) > 2 else None)
        return 0
    jour = argv[1] if len(argv) >= 2 else "20260909"
    par = rejouer_journal(jour)
    for sym in ("ES", "NQ"):
        print(resume(par[sym]))
    print("journal :", chemin_rejeu(jour))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
