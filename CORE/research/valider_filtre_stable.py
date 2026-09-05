"""Etape 1 — le filtre `data_quality_flag == stable` est-il un invariant ?

Verifie sur le 04/09 seulement, la reserve du CONVENTIONS §4 bloque tout ce qui
suit. Quatre questions, sur les 75 jours ES + NQ :
  Q1  repartition stable / degraded / warmup, par jour
  Q2  exactement une ligne `stable` par `ts` ?
  Q3  des `ts` sans aucune ligne `stable` (barres qu'on perdrait) ?
  Q4  des lignes `stable` a valeur nulle sur une colonne temoin ?
Lecture par expressions regulieres : json.loads sur 3 Go serait dix fois plus lent
pour quatre champs.
"""
import glob
import re
import sys
from collections import defaultdict

import pandas as pd

RE_TS = re.compile(r'"ts_raw_ms"\s*:\s*(\d+)')
RE_FLAG = re.compile(r'"data_quality_flag"\s*:\s*"([a-z_]+)"')
RE_TEMOIN = re.compile(r'"dist_vwap_d"\s*:\s*(null|-?[\d.eE+]+)')

BARRES_SESSION = 1380
TOLERANCE = 0.01


def analyser(sym: str) -> None:
    par_jour = defaultdict(lambda: defaultdict(int))
    ts_par_flag = defaultdict(set)
    stable_multi = 0
    stable_nul = 0
    vus_stable = set()

    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)):
        jour = f.replace("\\", "/").split("/")[-1][:8]
        for ligne in open(f, encoding="utf-8", errors="ignore"):
            if len(ligne) < 50:
                continue
            m_ts = RE_TS.search(ligne)
            if not m_ts:
                continue
            ts = int(m_ts.group(1))
            m_f = RE_FLAG.search(ligne)
            flag = m_f.group(1) if m_f else "absent"
            par_jour[jour][flag] += 1
            ts_par_flag[flag].add(ts)
            if flag == "stable":
                if ts in vus_stable:
                    stable_multi += 1
                vus_stable.add(ts)
                m_t = RE_TEMOIN.search(ligne)
                if m_t and m_t.group(1) == "null":
                    stable_nul += 1

    d = pd.DataFrame(par_jour).T.fillna(0).astype(int).sort_index()
    for c in ("stable", "degraded", "warmup", "absent"):
        if c not in d:
            d[c] = 0
    total = int(d.sum().sum())
    tous_ts = set().union(*ts_par_flag.values()) if ts_par_flag else set()
    orphelins = tous_ts - vus_stable

    print("\n########## %s — %d jours, %d lignes" % (sym, len(d), total))
    print("  stable %d (%.1f%%) | degraded %d (%.1f%%) | warmup %d | sans flag %d"
          % (d.stable.sum(), 100 * d.stable.sum() / total,
             d.degraded.sum(), 100 * d.degraded.sum() / total,
             d.warmup.sum(), d.absent.sum()))
    print()
    print("  Q2 — un seul `stable` par ts : %s (%d violations)"
          % ("OUI" if stable_multi == 0 else "NON", stable_multi))
    print("  Q3 — ts sans aucune ligne stable : %d (%.2f%% des ts)"
          % (len(orphelins), 100 * len(orphelins) / max(len(tous_ts), 1)))
    print("  Q4 — lignes stable a dist_vwap_d nul : %d" % stable_nul)
    print()
    bas = int(BARRES_SESSION * (1 - TOLERANCE))
    haut = int(BARRES_SESSION * (1 + TOLERANCE))
    hors = d[(d.stable < bas) | (d.stable > haut)]
    print("  volumetrie stable : mediane %d | hors [%d, %d] : %d jours sur %d"
          % (d.stable.median(), bas, haut, len(hors), len(d)))
    if len(hors):
        print("     %s" % ", ".join("%s:%d" % (j, n) for j, n in
                                    list(hors.stable.items())[:10]))
    if orphelins:
        o = pd.to_datetime(pd.Series(sorted(orphelins)), unit="ms", utc=True)
        print("  jours concernes par les orphelins : %s"
              % ", ".join(sorted(set(o.dt.strftime("%m-%d")))[:8]))


for s in (sys.argv[1:] or ["NQ", "ES"]):
    analyser(s)
