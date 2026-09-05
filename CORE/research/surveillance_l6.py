"""L6 — surveillance quotidienne des donnees.

Tourne sur chaque nouveau fichier, sans rien savoir d'un edge. Repond a une
seule question : **ce que Sierra a ecrit aujourd'hui ressemble-t-il a ce qu'il
ecrivait hier ?**

Cinq controles, chacun ne pouvant se declencher que sur une mesure :

  A  VOLUMETRIE      combien de barres `stable`, contre 1 380 attendues
  B  CONTINUITE      trous INTERNES en seance cash — c'est ce qui distingue une
                     seance ecourtee (bloc continu qui s'arrete tot) d'une panne
                     (trous disperses). Le compte de barres ne les distingue pas :
                     le 19/06 avait 210 barres cash, ce qui ressemblait a une
                     demi-seance de ferie, et 56 trous internes.
  C  FENETRE         le lot melange-t-il `w0` et `w1` ? Un lot mixte sur une
                     colonne de session doit etre refuse, pas moyenne.
  D  RESET VWAP      l'heure du reset de `vwap_d` correspond-elle a 17h ET
                     converti au jour pres ? C'est le check qui porte la dette
                     DST de CONVENTIONS §2 : au 1er novembre, la session doit
                     passer a 22:00 UTC, et si personne ne l'a fait, ce controle
                     le dit au lieu d'un silence de trois mois.
  E  DERIVE          mediane du jour par famille, comparee aux 20 jours
                     precedents. Une famille entiere qui bouge d'un facteur
                     signale un changement de source, pas un mouvement de marche.

Sortie : une ligne JSONL par controle dans `LOGS/surveillance/`, et un code
retour non nul des qu'une ALERTE est levee — de quoi brancher une tache
planifiee.

Usage :
    python -X utf8 CORE/research/surveillance_l6.py            # dernier jour
    python -X utf8 CORE/research/surveillance_l6.py 20260908   # un jour precis
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from CORE.features import recalc  # noqa: E402

BARRES_SESSION = 1380
BARRES_CASH = 390
# En deca, la journee n'est pas exploitable (CONVENTIONS §4).
SEUIL_EXPLOITABLE = 0.90
# Au-dela, les trous ne sont plus une seance courte mais une panne.
MAX_TROUS_CASH = 5
# Une famille dont la mediane bouge de plus de cela contre ses 20 derniers
# jours a change de source, pas de regime.
MAX_DERIVE_FAMILLE = 3.0
N_JOURS_REFERENCE = 20
# Familles dont les niveaux changent tous les jours par construction : de
# nouveaux strikes, un nouveau gamma. Mesure ES du 01 au 03/09 :
# `dist_mq_put` passe de 55 a 162 puis 302 — un facteur 5 en trois jours, sans
# le moindre defaut de donnee. Leur appliquer le seuil commun revient a lever
# une alerte chaque semaine, et une alerte qui se declenche sans action est
# une alerte qu'on finit par ignorer.
FAMILLES_MOUVANTES = {"F11", "F8"}
MAX_DERIVE_MOUVANTE = 10.0


def charger_jour(sym: str, jour: str) -> pd.DataFrame:
    motif = "DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)
    lignes = []
    for f in sorted(glob.glob(motif)):
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln[:1] != "{":
                continue
            try:
                lignes.append(json.loads(ln))
            except ValueError:
                continue
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    df["_ts"] = recalc.horodatage(df)
    df = df.dropna(subset=["_ts"]).sort_values("_ts").drop_duplicates("_ts")
    df["_dt"] = pd.to_datetime(df["_ts"], unit="ms", utc=True)
    return df.reset_index(drop=True)


def _res(nom, etat, message, **ctx):
    return {"controle": nom, "etat": etat, "message": message, **ctx}


def controle_volumetrie(df, sym, jour):
    st = df[df.get("data_quality_flag", "stable") == "stable"]
    n = len(st)
    part = n / BARRES_SESSION
    dow = pd.Timestamp(jour).day_name()
    if dow == "Sunday":
        return _res("volumetrie", "INFO",
                    "dimanche : %d barres, seance courte attendue" % n,
                    barres=n, part=round(part, 3))
    etat = "OK" if part >= SEUIL_EXPLOITABLE else "ALERTE"
    return _res("volumetrie", etat,
                "%d barres stable sur %d attendues (%.0f %%)"
                % (n, BARRES_SESSION, 100 * part),
                barres=n, part=round(part, 3),
                degraded=int((df.get("data_quality_flag") != "stable").sum()))


def controle_continuite(df, sym, jour):
    """Trous INTERNES en cash : ce qui distingue une seance courte d'une panne."""
    st = df[df.get("data_quality_flag", "stable") == "stable"]
    m = recalc.est_cash(st["_dt"])
    mn = (st.loc[m, "_dt"].dt.hour * 60 + st.loc[m, "_dt"].dt.minute).sort_values()
    if mn.empty:
        return _res("continuite", "ALERTE", "aucune barre en seance cash", trous=None)
    debut, fin = int(mn.iloc[0]), int(mn.iloc[-1])
    trous = (fin - debut + 1) - mn.nunique()
    tot = mn.nunique()
    if trous <= MAX_TROUS_CASH and debut <= recalc.CASH_DEBUT_MIN_EDT + 1:
        etat, quoi = ("OK", "complete") if tot >= BARRES_CASH - 5 else \
                     ("INFO", "seance ecourtee (bloc continu)")
    else:
        etat, quoi = "ALERTE", "PANNE (trous disperses)"
    return _res("continuite", etat,
                "%s : %d barres cash, %d trous internes, %02d:%02d -> %02d:%02d UTC"
                % (quoi, tot, trous, debut // 60, debut % 60, fin // 60, fin % 60),
                barres_cash=tot, trous=int(trous))


def controle_fenetre(df, sym, jour):
    v = recalc.window_version(df["_ts"])
    vals = sorted(set(v.dropna()))
    etat = "OK" if len(vals) == 1 else "ALERTE"
    return _res("fenetre", etat,
                "window_version = %s" % ", ".join(vals) if vals else "indeterminee",
                versions=vals)


def controle_reset_vwap(df, sym, jour):
    """L'heure du reset de `vwap_d` suit-elle 17h ET ?

    Porte la dette DST de CONVENTIONS §2 : au premier dimanche de novembre, la
    session doit passer de 21:00 a 22:00 UTC. Si le reglage Sierra n'a pas ete
    change, ce controle le dit — au lieu de trois mois de silence.
    """
    if "vwap_d" not in df.columns:
        return _res("reset_vwap", "INFO", "colonne vwap_d absente")
    v = pd.to_numeric(df["vwap_d"], errors="coerce")
    saut = v.diff().abs()
    seuil = max(float(saut.quantile(0.995)), 5.0)
    pas = df["_dt"].diff().dt.total_seconds()
    reset = (saut > seuil) & (pas <= 300)
    if not reset.any():
        return _res("reset_vwap", "INFO", "aucun reset detecte ce jour")
    heures = df.loc[reset, "_dt"].dt.hour
    attendue = int(recalc.ouverture_sess_utc(df["_dt"]).iloc[0])
    proche = int(((heures - attendue).abs() <= 1).sum())
    etat = "OK" if proche else "ALERTE"
    return _res("reset_vwap", etat,
                "%d reset(s), %d a %02dh UTC attendu (17h ET) — heures vues : %s"
                % (int(reset.sum()), proche, attendue,
                   ", ".join("%02dh" % h for h in sorted(set(heures)))),
                attendue_utc=attendue, vues=sorted(int(h) for h in set(heures)))


def _familles():
    try:
        import yaml
        cfg = yaml.safe_load(open("config/families.yaml", encoding="utf-8"))
        return [(re.compile(r["motif"]), r["famille"]) for r in cfg["regles"]]
    except Exception:  # noqa: BLE001
        return []


def controle_derive(df, sym, jour, regles):
    """Mediane par famille, contre les N jours precedents."""
    if not regles:
        return _res("derive", "INFO", "config/families.yaml illisible")
    ref = []
    fichiers = sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym))
    fichiers = [f for f in fichiers if os.path.basename(f)[:8] < jour][-N_JOURS_REFERENCE:]
    if len(fichiers) < 5:
        return _res("derive", "INFO", "moins de 5 jours de reference disponibles")
    for f in fichiers:
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln[:1] != "{":
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("data_quality_flag") == "stable":
                ref.append(d)
    if not ref:
        return _res("derive", "INFO", "aucune barre de reference")
    dref = pd.DataFrame(ref)
    st = df[df.get("data_quality_flag", "stable") == "stable"]

    def par_famille(x):
        out = {}
        for c in x.columns:
            if c.startswith("_"):
                continue
            fam = next((fa for rx, fa in regles if rx.search(c)), None)
            if fam is None:
                continue
            s = pd.to_numeric(x[c], errors="coerce")
            if s.notna().sum() > 50 and s.abs().median() > 1e-9:
                out.setdefault(fam, []).append(float(s.abs().median()))
        return {k: float(np.median(v)) for k, v in out.items() if v}

    a, b = par_famille(dref), par_famille(st)
    derives = []
    for fam in sorted(set(a) & set(b)):
        if a[fam] <= 1e-9:
            continue
        r = b[fam] / a[fam]
        seuil = (MAX_DERIVE_MOUVANTE if fam in FAMILLES_MOUVANTES
                 else MAX_DERIVE_FAMILLE)
        if r > seuil or r < 1.0 / seuil:
            derives.append((fam, round(r, 2)))
    etat = "ALERTE" if derives else "OK"
    return _res("derive", etat,
                ("familles derivant d'un facteur > %g : %s" % (
                    MAX_DERIVE_FAMILLE,
                    ", ".join("%s x%.2f" % (f, r) for f, r in derives)))
                if derives else "%d familles comparees, aucune derive" % len(set(a) & set(b)),
                familles_en_derive=[f for f, _ in derives])


def surveiller(sym: str, jour: str, regles) -> list:
    df = charger_jour(sym, jour)
    if df.empty:
        return [_res("chargement", "ALERTE", "aucune donnee pour %s %s" % (sym, jour))]
    return [controle_volumetrie(df, sym, jour),
            controle_continuite(df, sym, jour),
            controle_fenetre(df, sym, jour),
            controle_reset_vwap(df, sym, jour),
            controle_derive(df, sym, jour, regles)]


def main() -> int:
    jour = sys.argv[1] if len(sys.argv) > 1 else None
    if jour is None:
        fichiers = sorted(glob.glob("DATA/live_enriched/sierra/NQ/*.jsonl"))
        if not fichiers:
            print("aucun fichier")
            return 1
        jour = os.path.basename(fichiers[-1])[:8]
    regles = _familles()
    os.makedirs("LOGS/surveillance", exist_ok=True)
    chemin = "LOGS/surveillance/surveillance_%s.jsonl" % jour
    alertes = 0
    with open(chemin, "w", encoding="utf-8") as fh:
        for sym in ("NQ", "ES"):
            print("\n=== %s — %s" % (sym, jour))
            for r in surveiller(sym, jour, regles):
                r.update({"symbole": sym, "jour": jour,
                          "ecrit_a": datetime.now(timezone.utc).isoformat()})
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                marque = {"OK": "  ", "INFO": "  ", "ALERTE": ">>"}[r["etat"]]
                print("%s %-12s %-7s %s" % (marque, r["controle"], r["etat"],
                                            r["message"]))
                alertes += r["etat"] == "ALERTE"
    print("\n[ecrit] %s — %d alerte(s)" % (chemin, alertes))
    return 1 if alertes else 0


if __name__ == "__main__":
    sys.exit(main())
