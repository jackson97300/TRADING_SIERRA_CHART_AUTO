"""Deux runs de reduction donnent-ils la MEME partition, ou seulement le meme compte ?

Pourquoi ce script existe
-------------------------
Le passage de 49 a 75 jours a change le nombre de clusters de 224 a 228 sur ES
et le nombre de features communes de 191 a 190. Des comptes aussi proches
donnent l'impression d'un noyau stable — mais un compte identique peut cacher
une reorganisation complete du contenu : les memes 228 boites, remplies
autrement.

Ce script mesure ce que les comptes ne disent pas : **est-ce que les memes
features se retrouvent ensemble ?**

Methode
-------
Pour chaque cluster du run de reference, on cherche le cluster du run compare
qui recouvre le mieux ses membres, et on rapporte l'indice de Jaccard de cette
paire : |intersection| / |union|. Un Jaccard de 1 signifie que le cluster est
identique ; 0.5 qu'il a perdu ou gagne la moitie de ses membres.

Trois chiffres resument la comparaison :
  - la part des FEATURES qui restent dans un cluster equivalent (le chiffre
    qui compte : si 90 % ou plus ne bougent pas, la partition est figeable) ;
  - le Jaccard median, pondere par la taille des clusters ;
  - la liste des clusters qui se sont reorganises, pour savoir OU la structure
    a bouge — c'est la que les representants risquent de changer d'un run a
    l'autre, donc la que le noyau serait fragile.

On rapporte aussi les changements de representant a cluster inchange : meme
groupe, autre porte-drapeau, ce qui suffit a faire varier la liste finale
sans que la structure ait bouge.

Usage :
    python -X utf8 CORE/research/compare_partitions.py \\
        --reference DATA/feature_reduction_49j.json \\
        --compare   DATA/feature_reduction_75j.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from statistics import median


def charger(chemin: str) -> dict:
    with open(chemin, "r", encoding="utf-8") as fh:
        return json.load(fh)


def partition(bloc: dict) -> dict[str, list[str]]:
    """{representant: membres} pour un symbole."""
    return {cid: cl["membres"] for cid, cl in bloc["clusters"].items()}


def representants(bloc: dict) -> dict[str, str]:
    return {cid: cl["representant"] for cid, cl in bloc["clusters"].items()}


def jaccard(a: set, b: set) -> float:
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def comparer(ref: dict, cmp: dict, seuil_reorg: float = 0.7):
    part_ref, part_cmp = partition(ref), partition(cmp)
    rep_ref, rep_cmp = representants(ref), representants(cmp)

    # Ou se trouve chaque feature dans le run compare ?
    ou_cmp = {}
    for cid, membres in part_cmp.items():
        for m in membres:
            ou_cmp[m] = cid

    lignes = []
    features_stables = 0
    features_total = 0

    for cid, membres in part_ref.items():
        ens = set(membres)
        # Le cluster compare qui recouvre le mieux
        candidats = {}
        for m in membres:
            c = ou_cmp.get(m)
            if c is not None:
                candidats[c] = candidats.get(c, 0) + 1
        if not candidats:
            lignes.append({"jaccard": 0.0, "taille": len(ens),
                           "rep_ref": rep_ref[cid], "rep_cmp": None,
                           "membres_ref": sorted(ens), "perdus": sorted(ens),
                           "gagnes": []})
            features_total += len(ens)
            continue
        meilleur = max(candidats, key=candidats.get)
        ens_cmp = set(part_cmp[meilleur])
        j = jaccard(ens, ens_cmp)
        inter = ens & ens_cmp
        features_stables += len(inter)
        features_total += len(ens)
        lignes.append({
            "jaccard": j, "taille": len(ens),
            "rep_ref": rep_ref[cid], "rep_cmp": rep_cmp[meilleur],
            "membres_ref": sorted(ens),
            "perdus": sorted(ens - ens_cmp),
            "gagnes": sorted(ens_cmp - ens),
        })

    lignes.sort(key=lambda l: (l["jaccard"], -l["taille"]))
    part_features = features_stables / features_total if features_total else 0.0
    # Jaccard median pondere par la taille du cluster
    pondere = []
    for l in lignes:
        pondere.extend([l["jaccard"]] * l["taille"])
    j_median = median(pondere) if pondere else 0.0
    reorganises = [l for l in lignes if l["jaccard"] < seuil_reorg]
    # Meme cluster, autre representant
    changements_rep = [l for l in lignes
                       if l["jaccard"] >= 0.9 and l["rep_cmp"]
                       and l["rep_ref"] != l["rep_cmp"]]
    return {
        "n_clusters_ref": len(part_ref), "n_clusters_cmp": len(part_cmp),
        "part_features_stables": part_features,
        "jaccard_median_pondere": j_median,
        "reorganises": reorganises,
        "changements_representant": changements_rep,
        "lignes": lignes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reference", default="DATA/feature_reduction_49j.json")
    ap.add_argument("--compare", default="DATA/feature_reduction_75j.json")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--seuil-reorg", type=float, default=0.7)
    ap.add_argument("--figeable", type=float, default=0.90,
                    help="part de features devant rester en place pour juger "
                         "la partition figeable")
    ap.add_argument("--sortie", default="DOCS/COMPARAISON_PARTITIONS.md")
    args = ap.parse_args()

    for chemin in (args.reference, args.compare):
        if not os.path.exists(chemin):
            print("introuvable : %s" % chemin)
            return 1

    ref_all, cmp_all = charger(args.reference), charger(args.compare)
    rapport = ["# Les deux runs donnent-ils la meme partition ?\n\n",
               "Genere par `CORE/research/compare_partitions.py`.\n\n",
               "Reference : `%s`  ·  Comparaison : `%s`\n\n"
               % (os.path.basename(args.reference), os.path.basename(args.compare)),
               "Un nombre de clusters identique ne prouve rien : les memes "
               "boites peuvent etre remplies autrement. Ce qui compte est la "
               "part de features qui restent groupees ensemble.\n"]

    verdict_global = True
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        if sym not in ref_all or sym not in cmp_all:
            continue
        r = comparer(ref_all[sym], cmp_all[sym], args.seuil_reorg)
        figeable = r["part_features_stables"] >= args.figeable
        verdict_global = verdict_global and figeable

        print("\n" + "=" * 74)
        print("%s — %d clusters (reference) contre %d (comparaison)"
              % (sym, r["n_clusters_ref"], r["n_clusters_cmp"]))
        print("=" * 74)
        print("  features restant dans un cluster equivalent : %.1f %%   %s"
              % (100 * r["part_features_stables"],
                 "FIGEABLE" if figeable else "PAS ENCORE FIGEABLE"))
        print("  Jaccard median (pondere par la taille)      : %.2f"
              % r["jaccard_median_pondere"])
        print("  clusters reorganises (Jaccard < %.2f)       : %d sur %d"
              % (args.seuil_reorg, len(r["reorganises"]), r["n_clusters_ref"]))

        if r["reorganises"]:
            print("\n  OU LA STRUCTURE A BOUGE (les representants y sont fragiles)")
            for l in r["reorganises"][:10]:
                print("     %-28s J=%.2f  %d membres" % (l["rep_ref"][:28],
                                                         l["jaccard"], l["taille"]))
                if l["perdus"]:
                    print("        partis  : %s" % ", ".join(l["perdus"][:5]))
                if l["gagnes"]:
                    print("        arrives : %s" % ", ".join(l["gagnes"][:5]))

        if r["changements_representant"]:
            print("\n  MEME CLUSTER, AUTRE REPRESENTANT (%d) — suffit a faire"
                  % len(r["changements_representant"]))
            print("  varier la liste finale sans que la structure ait bouge")
            for l in r["changements_representant"][:8]:
                print("     %-28s -> %-28s (J=%.2f)"
                      % (l["rep_ref"][:28], l["rep_cmp"][:28], l["jaccard"]))

        rapport.append("\n## %s\n\n" % sym)
        rapport.append("- clusters : %d (reference) contre %d (comparaison)\n"
                       % (r["n_clusters_ref"], r["n_clusters_cmp"]))
        rapport.append("- **features restant groupees ensemble : %.1f %%** — %s\n"
                       % (100 * r["part_features_stables"],
                          "la partition est figeable" if figeable
                          else "la partition n'est pas encore figeable"))
        rapport.append("- Jaccard median pondere : %.2f\n" % r["jaccard_median_pondere"])
        rapport.append("- clusters reorganises : %d\n\n" % len(r["reorganises"]))
        if r["reorganises"]:
            rapport.append("### Ou la structure a bouge\n\n")
            rapport.append("| representant | Jaccard | membres | partis | arrives |\n")
            rapport.append("|---|---|---|---|---|\n")
            for l in r["reorganises"]:
                rapport.append("| `%s` | %.2f | %d | %s | %s |\n"
                               % (l["rep_ref"], l["jaccard"], l["taille"],
                                  ", ".join("`%s`" % x for x in l["perdus"][:4]) or "—",
                                  ", ".join("`%s`" % x for x in l["gagnes"][:4]) or "—"))
        if r["changements_representant"]:
            rapport.append("\n### Meme cluster, autre representant\n\n")
            for l in r["changements_representant"]:
                rapport.append("- `%s` -> `%s` (Jaccard %.2f)\n"
                               % (l["rep_ref"], l["rep_cmp"], l["jaccard"]))

    print("\n" + "=" * 74)
    print("VERDICT : %s"
          % ("la partition est stable entre les deux runs — figeable"
             if verdict_global else
             "la partition bouge encore — ne pas figer"))
    print("=" * 74)

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    print("Rapport : %s" % args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
