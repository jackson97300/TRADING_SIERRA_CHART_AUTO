"""AXE 2 — Une feature est-elle fiable sur TOUTE la periode, ou seulement par moments ?

La question
-----------
Le clustering de correlation voit une colonne comme une distribution. Il ne
voit pas qu'elle etait constante pendant dix jours, qu'elle a change d'echelle
au milieu, ou qu'elle n'existe que depuis six semaines. Une feature fiable
30 jours sur 41 n'a rien a faire dans un noyau de decision, quel que soit son
cluster — et rien dans la methode de reduction ne l'attrape.

La preuve que c'est necessaire : entre le run 49 jours et le run 75 jours,
cinq clusters ont un indice de Jaccard de 0.00 — `dist_swing_high`,
`bars_since_retest_high`, `bars_since_retest_low`, `ctx_va_developing_10`,
`is_new_sess_low`. Ces features n'ont pas change de groupe : elles ont
DISPARU, parce qu'elles n'existent pas sur les 26 jours anterieurs. La
partition bouge de 10 % sans qu'aucune redondance n'ait change.

Les quatre defauts recherches
-----------------------------
1. **Intermittence** — la feature n'a de donnees exploitables que sur une
   partie des jours. Elle fera bouger toute partition qui l'inclut.

2. **Mort par plages** — constante pendant plusieurs jours consecutifs alors
   qu'elle varie ailleurs. Signature typique d'un capteur Sierra qui decroche
   ou d'une etude desactivee sur le chart.

3. **Rupture d'echelle** — la mediane journaliere saute d'un facteur important
   d'un jour a l'autre. C'est le motif du bug ATR ticks/points deja paye une
   fois sur ce projet : la meme colonne, deux unites, aucune alerte.

4. **Rupture au redemarrage** — le champ `boot_id` change 18 fois sur la
   periode. Les features a etat cumule (compteurs, moyennes glissantes,
   sessions) peuvent se reinitialiser a chaque redemarrage de l'enricher.
   Une rupture qui coincide avec un changement de `boot_id` n'est pas un
   evenement de marche, c'est un artefact d'infrastructure.

Ce que le script ne fait pas
----------------------------
Il ne dit pas si une feature est JUSTE (c'est la verification semantique,
axe 3), ni si elle est UTILE (axe 5). Il dit si l'on peut lui faire confiance
de bout en bout de la periode.

Usage :
    python -X utf8 CORE/research/audit_qualite_temporel.py
    python -X utf8 CORE/research/audit_qualite_temporel.py --jours 75 --symbols ES
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# Une feature disponible sur moins que cette part des jours est intermittente :
# elle ne peut pas servir de base a une decision prise n'importe quel jour.
PART_JOURS_MIN = 0.90

# Une feature constante sur au moins ce nombre de jours consecutifs, alors
# qu'elle varie ailleurs, est morte par plages.
PLAGE_MORTE_MIN = 3

# Saut de mediane journaliere au-dela duquel on parle de rupture d'echelle.
# Volontairement haut : les medianes journalieres bougent naturellement.
FACTEUR_RUPTURE = 5.0

_TECHNIQUES = {
    "ts", "ts_raw_ms", "ts_event", "ts_event_ns", "date", "session",
    "session_id", "session_date", "session_segment", "session_date_trading",
    "sym", "symbol", "contract", "instrument", "schema_version", "boot_id",
    "seq", "bar_index", "_phase3_bars_processed",
}


def stats_par_jour(symbole: str, jours: int, dossier: str, rth_seul: bool):
    """Une ligne de statistiques par (jour, colonne). Chargement fichier par
    fichier : la periode complete pese pres de 2 Go, on n'en garde que les
    agregats."""
    lignes = []
    boots = {}
    non_numeriques: set = set()
    for chemin in sorted(glob.glob(os.path.join(dossier, symbole, "*.jsonl")))[-jours:]:
        barres = []
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne:
                    continue
                b = json.loads(ligne)
                if rth_seul and not b.get("is_cash_session"):
                    continue
                barres.append(b)
        if not barres:
            continue
        df = pd.DataFrame(barres)
        jour = str(df.get("session_date_trading", df.get("session_date")).iloc[0])[:10]
        if "boot_id" in df.columns:
            boots[jour] = str(df["boot_id"].iloc[0])
        for c in df.columns:
            if c in _TECHNIQUES:
                continue
            brute = df[c]
            s = pd.to_numeric(brute, errors="coerce")
            n_ok = int(s.notna().sum())
            # Une colonne de texte n'est pas "absente" : elle n'est simplement
            # pas numerique. La compter comme vide produisait des faux positifs
            # (`_aggressor_source`, `date_et`, `data_quality_flag` a 0 j / 62).
            if n_ok == 0 and brute.notna().sum() > 0.5 * len(df):
                non_numeriques.add(c)
                continue
            lignes.append({
                "jour": jour, "feature": c, "n": len(df), "n_ok": n_ok,
                "nunique": int(s.nunique(dropna=True)),
                "median": float(s.median()) if n_ok else float("nan"),
                "min": float(s.min()) if n_ok else float("nan"),
                "max": float(s.max()) if n_ok else float("nan"),
            })
    return pd.DataFrame(lignes), boots, sorted(non_numeriques)


def plus_longue_plage(valeurs: list[bool]) -> int:
    """Longueur de la plus longue suite de True."""
    best = cur = 0
    for v in valeurs:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def analyser(stats: pd.DataFrame, boots: dict) -> pd.DataFrame:
    jours = sorted(stats["jour"].unique())
    n_jours = len(jours)
    resultats = []

    for feature, g in stats.groupby("feature"):
        g = g.set_index("jour").reindex(jours)
        presente = (g["n_ok"].fillna(0) > 0.5 * g["n"].fillna(1)).tolist()
        n_presente = sum(presente)
        # CORRECTION : une valeur JOURNALIERE (open_cash, ib_high,
        # price_1030) est constante dans la journee par definition — ce n'est
        # pas une panne, c'est sa nature. La mort par plages se lit ENTRE les
        # jours : la valeur ne bouge plus d'un jour au suivant alors qu'elle
        # bougeait avant.
        # Deux conditions, pas une. Une mediane journaliere identique ne
        # suffit pas : `rvol_buy` ou `within_news_930_5m` ont une mediane de 0
        # tous les jours parce que l'evenement est rare, alors qu'elles varient
        # tres bien dans la journee. Une feature n'est morte que si elle ne
        # bouge NI dans le jour (une seule valeur distincte) NI d'un jour au
        # suivant.
        med_j = g["median"].tolist()
        nu_j = g["nunique"].fillna(0).tolist()
        fige = []
        for i in range(len(med_j)):
            if i == 0 or not presente[i] or not presente[i - 1]:
                fige.append(False)
                continue
            plat_dans_le_jour = nu_j[i] <= 1 and nu_j[i - 1] <= 1
            av, ap = med_j[i - 1], med_j[i]
            plat_entre_jours = bool(np.isfinite(av) and np.isfinite(ap) and av == ap)
            fige.append(plat_dans_le_jour and plat_entre_jours)
        plage_morte = plus_longue_plage(fige)

        # Rupture d'echelle : saut d'AMPLITUDE d'un jour au suivant.
        # GARDE — sur une feature signee, la mediane journaliere oscille
        # autour de zero et le rapport de deux medianes explose par pur
        # artefact numerique. C'est la meme erreur qui avait fait passer
        # `dist_vwap_d` pour une horloge a x150. On compare donc l'etendue
        # (max - min) du jour, et on refuse le rapport quand le denominateur
        # est negligeable devant le numerateur, ou quand l'amplitude du jour
        # est infime devant l'amplitude habituelle : ce n'est alors pas une
        # rupture d'echelle, c'est une journee calme.
        ampl = [(mx - mn) if (np.isfinite(mn) and np.isfinite(mx)) else float("nan")
                for mn, mx in zip(g["min"].tolist(), g["max"].tolist())]
        finies = [a for a in ampl if np.isfinite(a) and a > 0]
        ref = float(np.median(finies)) if finies else float("nan")
        facteur_max, jour_rupture = 0.0, None
        for i in range(1, len(ampl)):
            av, ap = ampl[i - 1], ampl[i]
            if not (np.isfinite(av) and np.isfinite(ap)):
                continue
            bas, haut = min(av, ap), max(av, ap)
            if haut <= 0 or bas <= 0.01 * haut:
                continue
            if np.isfinite(ref) and haut < 0.01 * ref:
                continue
            f = haut / bas
            if f > facteur_max:
                facteur_max, jour_rupture = f, jours[i]

        # La rupture coincide-t-elle avec un redemarrage ?
        rupture_au_boot = False
        if jour_rupture is not None and boots:
            i = jours.index(jour_rupture)
            if i > 0:
                rupture_au_boot = boots.get(jours[i - 1]) != boots.get(jour_rupture)

        part = n_presente / n_jours if n_jours else 0.0
        motifs = []
        if part < PART_JOURS_MIN:
            motifs.append("intermittente (%d j / %d)" % (n_presente, n_jours))
        if plage_morte >= PLAGE_MORTE_MIN and n_presente > plage_morte:
            motifs.append("morte %d jours d'affilee" % plage_morte)
        if facteur_max > FACTEUR_RUPTURE:
            motifs.append("rupture d'echelle x%.0f le %s%s"
                          % (facteur_max, jour_rupture,
                             " (AU REDEMARRAGE)" if rupture_au_boot else ""))

        resultats.append({
            "feature": feature,
            "jours_presente": n_presente,
            "jours_total": n_jours,
            "part_presente": part,
            "plage_morte": plage_morte,
            "facteur_rupture": facteur_max,
            "jour_rupture": jour_rupture,
            "rupture_au_boot": rupture_au_boot,
            "fiable": not motifs,
            "motifs": " ; ".join(motifs),
        })

    df = pd.DataFrame(resultats)
    return df.sort_values(["fiable", "part_presente"], ascending=[True, True])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched/sierra")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=75)
    ap.add_argument("--tout", action="store_true",
                    help="inclure les barres hors seance US")
    ap.add_argument("--sortie", default="DOCS/AUDIT_QUALITE_TEMPOREL.md")
    ap.add_argument("--json", default="DATA/qualite_temporel.json")
    args = ap.parse_args()

    rapport = ["# Audit qualite temporel des features\n\n",
               "Genere par `CORE/research/audit_qualite_temporel.py`.\n\n",
               "Repond a une seule question : **peut-on faire confiance a "
               "cette feature sur toute la periode ?** Pas si elle est juste "
               "(axe 3), pas si elle est utile (axe 5).\n\n",
               "Quatre defauts recherches : intermittence (presente moins de "
               "%.0f %% des jours), mort par plages (constante %d jours "
               "d'affilee ou plus), rupture d'echelle (saut de mediane "
               "journaliere superieur a x%.0f), et coincidence de cette "
               "rupture avec un changement de `boot_id` — auquel cas c'est un "
               "artefact de redemarrage, pas un evenement de marche.\n"
               % (100 * PART_JOURS_MIN, PLAGE_MORTE_MIN, FACTEUR_RUPTURE)]

    sortie_json = {}
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        print("Chargement %s..." % sym, end=" ", flush=True)
        stats, boots, non_num = stats_par_jour(sym, args.jours, args.data,
                                               rth_seul=not args.tout)
        if stats.empty:
            print("aucune donnee")
            continue
        print("OK (%d jours, %d colonnes)"
              % (stats["jour"].nunique(), stats["feature"].nunique()))
        res = analyser(stats, boots)
        if non_num:
            print("  (%d colonnes non numeriques ignorees : %s%s)"
                  % (len(non_num), ", ".join(non_num[:4]),
                     " ..." if len(non_num) > 4 else ""))

        fiables = res[res["fiable"]]
        problemes = res[~res["fiable"]]
        interm = problemes[problemes["motifs"].str.contains("intermittente")]
        mortes = problemes[problemes["motifs"].str.contains("morte")]
        ruptures = problemes[problemes["motifs"].str.contains("rupture")]
        # Le drapeau `rupture_au_boot` est pose des qu'un saut coincide avec
        # un changement de boot_id, meme si le saut reste sous le seuil de
        # rejet. Compter ces cas parmi les ruptures donnait 357 "au
        # redemarrage" pour 306 ruptures — plus d'un sous-ensemble que
        # d'ensemble. On ne retient que celles qui sont effectivement des
        # ruptures.
        au_boot = ruptures[ruptures["rupture_au_boot"]]

        print("\n" + "=" * 74)
        print("%s — %d colonnes sur %d jours (%d redemarrages de l'enricher)"
              % (sym, len(res), stats["jour"].nunique(), len(set(boots.values()))))
        print("=" * 74)
        print("  fiables sur toute la periode : %d  (%.0f %%)"
              % (len(fiables), 100 * len(fiables) / len(res)))
        print("  a exclure du noyau           : %d" % len(problemes))
        print("     intermittentes            : %d" % len(interm))
        print("     mortes par plages         : %d" % len(mortes))
        print("     ruptures d'echelle        : %d  (dont %d au redemarrage)"
              % (len(ruptures), len(au_boot)))

        if len(interm):
            print("\n  INTERMITTENTES — elles font bouger toute partition qui les inclut")
            for _, r in interm.head(10).iterrows():
                print("     %-34s %2d j / %d" % (r["feature"][:34],
                                                 r["jours_presente"], r["jours_total"]))

        if len(mortes):
            print("\n  MORTES PAR PLAGES — capteur qui decroche ou etude desactivee")
            for _, r in mortes.sort_values("plage_morte", ascending=False).head(8).iterrows():
                print("     %-34s constante %d jours d'affilee"
                      % (r["feature"][:34], r["plage_morte"]))

        if len(au_boot):
            print("\n  RUPTURES AU REDEMARRAGE — artefact d'infrastructure, pas de marche")
            for _, r in au_boot.sort_values("facteur_rupture", ascending=False).head(8).iterrows():
                print("     %-34s x%-7.0f le %s"
                      % (r["feature"][:34], r["facteur_rupture"], r["jour_rupture"]))

        autres_ruptures = ruptures[~ruptures["rupture_au_boot"]]
        if len(autres_ruptures):
            print("\n  RUPTURES HORS REDEMARRAGE — a investiguer une par une")
            for _, r in autres_ruptures.sort_values("facteur_rupture", ascending=False).head(8).iterrows():
                print("     %-34s x%-7.0f le %s"
                      % (r["feature"][:34], r["facteur_rupture"], r["jour_rupture"]))

        rapport.append("\n## %s — %d colonnes, %d jours, %d redemarrages\n\n"
                       % (sym, len(res), stats["jour"].nunique(),
                          len(set(boots.values()))))
        rapport.append("**%d fiables** sur toute la periode, **%d a exclure du "
                       "noyau**.\n\n" % (len(fiables), len(problemes)))
        rapport.append("| feature | jours | plage morte | rupture | au redemarrage | motifs |\n")
        rapport.append("|---|---|---|---|---|---|\n")
        for _, r in problemes.iterrows():
            rapport.append("| `%s` | %d/%d | %d | %s | %s | %s |\n"
                           % (r["feature"], r["jours_presente"], r["jours_total"],
                              r["plage_morte"],
                              "x%.0f" % r["facteur_rupture"] if r["facteur_rupture"] > 1 else "—",
                              "oui" if r["rupture_au_boot"] else "—",
                              r["motifs"]))

        sortie_json[sym] = {
            "jours": int(stats["jour"].nunique()),
            "redemarrages": len(set(boots.values())),
            "fiables": sorted(fiables["feature"].tolist()),
            "a_exclure": [{"feature": r["feature"], "motifs": r["motifs"],
                           "jours_presente": int(r["jours_presente"]),
                           "jours_total": int(r["jours_total"]),
                           "plage_morte": int(r["plage_morte"]),
                           "facteur_rupture": float(r["facteur_rupture"]),
                           "rupture_au_boot": bool(r["rupture_au_boot"])}
                          for _, r in problemes.iterrows()],
        }

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(sortie_json, fh, indent=2, ensure_ascii=False)

    print("\nRapport : %s" % args.sortie)
    print("Liste exploitable : %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
