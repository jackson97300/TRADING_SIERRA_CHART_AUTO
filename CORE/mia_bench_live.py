"""mia_bench_live.py — le benchmark MIA branche sur les donnees reelles.

Pourquoi ce fichier existe
--------------------------
`CORE/mia_bench.py` lit des JSONL au format DMP brut (`YYYYMMDD_SYM.jsonl`,
schema 3.7.3) et reconstruit lui-meme tout le pipeline : IB recalc, features
contextuelles, intermarket, MenthorQ. Or :

  - la collecte de ce format s'est arretee le 05/06/2026 ; le bench ne peut
    donc analyser que des donnees vieilles de trois mois ;
  - la source vivante est `DATA/live_enriched/sierra/{SYM}/*_sierra_enriched.jsonl`,
    626 colonnes, ou ctx_*, im_*, mq_*, rvol_*, bn_*, ib_* sont **deja
    calculees** — reconstruire le pipeline par-dessus serait a la fois inutile
    et une source de divergence.

Ce module reprend donc les 21 tests de `mia_bench.py` sans les reecrire, mais
leur fournit les donnees enrichies au lieu de les recalculer.

Ce qui change par rapport au bench d'origine
--------------------------------------------
- `NQ_raw`, `NQ_ctx` et `NQ_full` designent la MEME table. Dans le pipeline
  d'origine ces trois etages etaient successifs ; ici l'enrichissement est
  deja fait en amont par `CORE/enricher_chain.py`. Les tests qui comparaient
  un etage a l'autre deviennent tautologiques — c'est signale dans le rapport
  plutot que masque.
- La famille `amd_*` (AMD Power of 3) est **absente** de live_enriched :
  le test correspondant est declare NON APPLICABLE au lieu d'echouer.
- Chaque test tourne isole. Un test qui casse sur la nouvelle source est
  rapporte comme tel, avec son message d'erreur, et n'interrompt pas les
  autres. On veut savoir lesquels survivent, pas obtenir un zero global.

Usage :
    python -X utf8 CORE/mia_bench_live.py
    python -X utf8 CORE/mia_bench_live.py --jours 20 --sortie DOCS/BENCH_LIVE.txt
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
import traceback
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

_ICI = os.path.dirname(os.path.abspath(__file__))
_RACINE = os.path.dirname(_ICI)
for _p in (_RACINE, _ICI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mia_bench as mb  # noqa: E402

# Repertoire de la source vivante.
DOSSIER_DEFAUT = os.path.join(_RACINE, "DATA", "live_enriched_clean")
MOTIF = re.compile(r"(\d{8})_(NQ|ES)_sierra_enriched\.jsonl$")

# Tests non applicables a la source enrichie, avec la raison.
NON_APPLICABLES = {
    "test_amd": "la famille amd_* est absente de live_enriched (0 colonne). "
                "L'AMD Power of 3 n'a jamais ete porte dans l'enricher.",
}


def decouvrir(dossier: str, jours: int) -> dict:
    """{date: {"ES": chemin, "NQ": chemin}} pour les `jours` derniers jours."""
    trouve: dict[str, dict[str, str]] = {}
    for sym in ("ES", "NQ"):
        motif = os.path.join(dossier, sym, "*_sierra_enriched.jsonl")
        for chemin in sorted(glob.glob(motif)):
            m = MOTIF.search(os.path.basename(chemin))
            if not m:
                continue
            if os.path.getsize(chemin) < 10000:
                continue  # week-end ou journee tronquee
            trouve.setdefault(m.group(1), {})[m.group(2)] = chemin
    # Ne garder que les journees ou les DEUX symboles existent : les tests
    # cross-asset et intermarket en dependent.
    completes = {d: s for d, s in trouve.items() if len(s) == 2}
    return dict(sorted(completes.items())[-jours:])


def lire(chemin: str) -> pd.DataFrame:
    lignes = []
    with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if ligne:
                lignes.append(json.loads(ligne))
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    if "ts" in df.columns:
        df = df.sort_values("ts").drop_duplicates("ts", keep="last")
    return df.reset_index(drop=True)


def construire(fichiers: dict) -> dict:
    """Meme structure que mia_bench.build_pipeline, sans recalculer.

    Les trois etages raw / ctx / full pointent sur la meme table : dans la
    source enrichie l'enrichissement est deja applique.
    """
    data = {}
    for date, syms in sorted(fichiers.items()):
        entree = {"date": date}
        for sym in ("NQ", "ES"):
            df = lire(syms[sym]) if sym in syms else pd.DataFrame()
            if df.empty:
                entree[f"{sym}_raw"] = None
                entree[f"{sym}_ctx"] = None
                entree[f"{sym}_full"] = None
                continue
            entree[f"{sym}_raw"] = df
            entree[f"{sym}_ctx"] = df
            entree[f"{sym}_full"] = df
        data[date] = entree
    return data


def lancer_tests(data: dict, sortie: list) -> list[dict]:
    """Chaque test isole. Retourne le journal des reussites et des echecs."""
    journal: list[dict] = []
    resultats = None
    nq_all = None

    # (nom lisible, attribut du module, façon de l'appeler)
    plan = [
        ("Fonctionnel", "test_functional", "simple"),
        ("Inventaire", "test_inventory", "simple"),
        ("Ranking bootstrap", "test_ranking", "ranking"),
        ("Cross-asset", "test_cross_asset", "avec_resultats"),
        ("Par regime", "test_regime", "avec_resultats"),
        ("Seuils", "test_thresholds", "nq_all"),
        ("Game changers", "test_game_changers", "simple"),
        ("Verdict", "test_verdict", "verdict"),
        ("Signal vs bruit", "test_signal_bruit", "nq_all_data"),
        ("Noyau dur", "test_noyau_dur", "nq_all_data"),
        ("Wall tracker", "test_wall_tracker", "simple"),
        ("Timing de session", "test_session_timing", "nq_all_data"),
        ("Sante DMP", "test_dmp_health", "simple"),
        ("Validation RVOL", "test_rvol_validation", "simple"),
        ("Session / IB", "test_session_ib", "simple"),
        ("Rendements veille", "test_prev_returns", "simple"),
        ("Market Profile avance", "test_market_profile_advanced", "simple"),
        ("AMD Power of 3", "test_amd", "simple"),
        ("Double top", "test_double_top", "simple"),
    ]

    for libelle, nom, mode in plan:
        if nom in NON_APPLICABLES:
            print("  %-24s NON APPLICABLE" % libelle)
            sortie.append("")
            sortie.append("  [NON APPLICABLE] %s — %s" % (libelle, NON_APPLICABLES[nom]))
            journal.append({"test": libelle, "etat": "NON_APPLICABLE",
                            "detail": NON_APPLICABLES[nom]})
            continue

        fn = getattr(mb, nom, None)
        if fn is None:
            journal.append({"test": libelle, "etat": "ABSENT", "detail": nom})
            continue

        t0 = time.perf_counter()
        try:
            if mode == "ranking":
                resultats, nq_all = fn(data, sortie)
            elif mode == "avec_resultats":
                fn(data, resultats, sortie)
            elif mode == "nq_all":
                fn(nq_all, sortie)
            elif mode == "nq_all_data":
                fn(nq_all, data, sortie)
            elif mode == "verdict":
                fn(resultats, data, sortie)
            else:
                fn(data, sortie)
            dt = time.perf_counter() - t0
            print("  %-24s OK        (%.1fs)" % (libelle, dt))
            journal.append({"test": libelle, "etat": "OK", "detail": "%.1fs" % dt})
        except Exception as exc:  # on veut la carte complete, pas le premier echec
            dt = time.perf_counter() - t0
            detail = "%s: %s" % (type(exc).__name__, exc)
            print("  %-24s ECHEC     %s" % (libelle, detail[:70]))
            sortie.append("")
            sortie.append("  [ECHEC] %s — %s" % (libelle, detail))
            sortie.append("  " + traceback.format_exc().replace("\n", "\n  "))
            journal.append({"test": libelle, "etat": "ECHEC", "detail": detail})
    return journal


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=DOSSIER_DEFAUT)
    ap.add_argument("--jours", type=int, default=20)
    ap.add_argument("--sortie", default="DOCS/BENCH_LIVE.txt")
    args = ap.parse_args()

    fichiers = decouvrir(args.data, args.jours)
    if not fichiers:
        print("Aucun fichier *_sierra_enriched.jsonl exploitable dans %s" % args.data)
        print("Attendu : {ES,NQ}/YYYYMMDD_{ES,NQ}_sierra_enriched.jsonl")
        return 1

    sortie = []
    sortie.append("=" * 74)
    sortie.append("  MIA BENCH LIVE — source enrichie (live_enriched)")
    sortie.append("  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    sortie.append("=" * 74)
    sortie.append("")
    sortie.append("  Source   : %s" % os.path.abspath(args.data))
    sortie.append("  Journees : %d (%s -> %s)"
                  % (len(fichiers), min(fichiers), max(fichiers)))
    sortie.append("")
    sortie.append("  NOTE : dans cette source, raw / ctx / full designent la meme")
    sortie.append("  table — l'enrichissement est fait en amont par enricher_chain.")
    sortie.append("  Les tests qui comparaient ces etages sont donc tautologiques.")
    sortie.append("")

    print("Chargement de %d journees..." % len(fichiers), end=" ", flush=True)
    t0 = time.perf_counter()
    data = construire(fichiers)
    n_barres = sum(len(e["ES_full"]) for e in data.values()
                   if e.get("ES_full") is not None)
    print("OK (%d barres ES, %.1fs)" % (n_barres, time.perf_counter() - t0))
    print()

    journal = lancer_tests(data, sortie)

    ok = sum(1 for j in journal if j["etat"] == "OK")
    ech = sum(1 for j in journal if j["etat"] == "ECHEC")
    na = sum(1 for j in journal if j["etat"] == "NON_APPLICABLE")

    resume = []
    resume.append("")
    resume.append("=" * 74)
    resume.append("  BILAN DU PORTAGE : %d tests OK, %d en echec, %d non applicables"
                  % (ok, ech, na))
    resume.append("=" * 74)
    for j in journal:
        resume.append("  %-12s %-26s %s" % (j["etat"], j["test"], j["detail"][:60]))
    sortie = resume + [""] + sortie

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sortie))

    print()
    print("\n".join(resume))
    print()
    print("Rapport complet : %s" % args.sortie)
    return 0 if ech == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
