"""LE RENDU DU MANIFESTE — la mise en page markdown, separee de la mesure.

Sorti de `mesure_manifeste.py` le 11/09 : le fichier passait 300 lignes et la
regle du chantier est de DECOUPER, pas de tasser. La frontiere est nette —
`mesure_manifeste` introspecte et mesure, ce fichier met en forme et n'ouvre
aucune donnee.
"""

from __future__ import annotations

import re

from V3.mesure_manifeste import BLOCS, CLASSES


def rendre(lignes, jour, verif):
    total = len(lignes)
    par_prov = {}
    for l in lignes:
        par_prov[l["provenance"]] = par_prov.get(l["provenance"], 0) + 1
    out = ["# MANIFESTE DES DONNEES — ce que V3 consomme vraiment", "",
           "*GENERE par `V3/mesure_manifeste.py`, jamais ecrit a la main. Regenerer",
           "apres toute modification d'une colonne : un catalogue tape ment des la",
           "premiere derive. Mesure sur le %s, ES et NQ.*" % jour, "",
           "## La source, en une ligne", "",
           "`DATA/live_enriched/sierra/{ES,NQ}/*.jsonl`, barres de 1 minute, agregees",
           "en 15 minutes par la chaine (`injecter_recalculs`, chauffe vingt jours).",
           "**Le frame que la chaine LIT porte %d colonnes** ; le brut 1 min en porte" % total,
           "plusieurs centaines — tout ce qui n'est pas dans la liste ci-dessous meurt",
           "a l'agregation et n'existe pas pour V3.", "",
           "## Le compte", "",
           "| provenance | colonnes | ce que ca veut dire |", "|---|---|---|"]
    for cl in sorted(par_prov):
        out.append("| `%s` | %d | %s |" % (cl, par_prov[cl],
                                            "recalculee par la chaine (`_r`)" if cl == "recalc"
                                            else "proxy refuse par `lecture.py`" if cl == "proxy"
                                            else CLASSES.get(cl, "?")))
    etoiles = [l for l in lignes if l["etoile"]]
    out += ["", "> Les colonnes `recalc` sont calculees par la chaine avec VINGT jours",
            "> de chauffe. Sur un frame `lot` de trois jours elles peuvent etre absentes",
            "> — ou pire, PRESENTES ET FAUSSES. C'est pourquoi la ligne de journal porte",
            "> `setups_armes_motif` et `flux_motif` quand le frame n'est pas fiable.", "",
            "## Ce sur quoi repose la decision (★)", "",
            "**%d colonnes** sur %d sont lues par LES_QUATRE et les setups" % (len(etoiles), total),
            "(citees dans `V3/marges_quatre.py`). Tout le reste est du contexte :", "",
            "`" + "`, `".join(l["nom"] for l in etoiles) + "`", "",
            "## Les pieges d'unite", "",
            "Sept confusions d'unites en une semaine dans ce depot, toutes d'un facteur",
            "constant. Les quatre qui comptent :", "",
            "| colonne | unite | d'ou elle vient |", "|---|---|---|",
            "| `atr` | **points** | ATR JOURNALIER, lu du chart daily de Sierra en prix |",
            "| `atr_14m` | **ticks** | ATR(14) 1 min ; le C++ divise par `tick_size` avant de rendre |",
            "| `atr_barre`, `atr_veille`, `atr_ref` | **points** | recalcules par la chaine sur la barre agregee |",
            "| `dist_*` | **ticks** | `niveau = close + dist x tick` (CONVENTIONS §8) |",
            "| `*_pct` | **part de 0 a 1** | PAS un pourcentage affichable tel quel |", "",
            "> `atr` et `atr_14m` n'ont ni la meme periode ni la meme unite : l'un est",
            "> JOURNALIER en points, l'autre est sur 14 barres de 1 MINUTE en ticks. Les",
            "> comparer par leur ordre de grandeur ne prouve rien — c'est l'erreur que la",
            "> premiere version de ce manifeste a commise, en affirmant a tort que",
            "> `CLAUDE.md` disait l'inverse de la realite. `CLAUDE.md` avait raison.", "",
            "### Verification, a chaque generation", "",
            "| colonne | unite declaree | mediane du jour | ATR recalcule des barres | verdict |",
            "|---|---|---|---|---|"]
    for col, declare, med, attendu, ok in verif:
        out.append("| `%s` | %s | %.2f | %.2f | %s |"
                   % (col, declare, med, attendu, "coherent" if ok else "**INCOHERENT**"))
    out += [""]
    vus = set()
    for titre, motif in BLOCS:
        rx = re.compile(motif)
        bloc = [l for l in lignes if l["nom"] not in vus and rx.search(l["nom"])]
        if not bloc:
            continue
        vus |= {l["nom"] for l in bloc}
        out += ["## %s" % titre, "",
                "| colonne | fam. | prov. | unite | note |", "|---|---|---|---|---|"]
        for l in bloc:
            out.append("| %s`%s` | %s | `%s` | %s | %s |" % (
                "★ " if l["etoile"] else "", l["nom"], l["famille"], l["provenance"],
                l["unite"] + (" — " + l["piege"] if l["piege"] else ""), l["note"] or "—"))
        out.append("")
    reste = [l for l in lignes if l["nom"] not in vus]
    if reste:
        out += ["## Hors bloc", "", "| colonne | fam. | prov. | unite | note |", "|---|---|---|---|---|"]
        for l in reste:
            out.append("| %s`%s` | %s | `%s` | %s | %s |" % (
                "★ " if l["etoile"] else "", l["nom"], l["famille"], l["provenance"],
                l["unite"], l["note"] or "—"))
        out.append("")
    return "\n".join(out) + "\n"
