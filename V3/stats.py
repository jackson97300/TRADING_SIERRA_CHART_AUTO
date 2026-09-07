"""Les intervalles de confiance, faits correctement — partagé par les couches.

Trois erreurs de mesure ont été corrigées ici le 07/09, toutes trouvées par
Fable sur le rapport L1 v1. Elles ont la même conséquence : **un intervalle
trop étroit**, donc un résultat qui « sort du bruit » sans en sortir.

1. **L'unité statistique n'est pas le jour.** B1 lit le côté de la VWAP
   *semaine* ; le prix y reste souvent du lundi au vendredi — 0,65 bascule par
   jour, mesuré. Soixante jours, ce sont huit ou neuf semaines. Un bootstrap
   par jour traite 60 tirages là où il y en a 9.

2. **Les groupes ne sont pas indépendants.** Sur un jour LONG, les signaux
   longs sont *avec* et les shorts *contre* : les deux groupes partagent les
   jours, en sens opposés. `hypot(ic_a, ic_c)` suppose l'indépendance et
   SOUS-ESTIME l'intervalle de la différence. Il faut rééchantillonner les
   blocs et recalculer la différence dans chaque tirage.

3. **Un contrôle négatif à un tirage n'est pas un contrôle.** Une seule
   réalisation d'un biais aléatoire est un exemple, pas une distribution.
   Qu'elle donne −0,30 dit surtout que le bruit de la mesure est de cet
   ordre-là.
"""

from __future__ import annotations

import numpy as np


def blocs_semaine(jours):
    """{jour: clé de semaine ISO}. Les jours d'une même semaine ne sont pas des
    observations indépendantes d'un biais hebdomadaire."""
    import pandas as pd
    return {j: "%d-%02d" % pd.Timestamp(j).isocalendar()[:2] for j in jours}


def _par_bloc(valeurs_par_jour, blocs):
    """{bloc: [toutes les valeurs de la semaine]}."""
    out = {}
    for jour, v in valeurs_par_jour.items():
        out.setdefault(blocs.get(jour, jour), []).extend(v)
    return out


def difference_appariee(a_par_jour, b_par_jour, blocs, n=2000, graine=7):
    """Moyenne de (a − b) et son IC 95 %, bootstrappés par BLOC et APPARIÉS.

    Apparié veut dire : on rééchantillonne les blocs, et dans chaque tirage on
    recalcule `moyenne(a) − moyenne(b)` sur les mêmes blocs. La corrélation
    entre les deux groupes est ainsi respectée, au lieu d'être supposée nulle.

    Rend (difference, demi_intervalle, n_blocs).
    """
    A, B = _par_bloc(a_par_jour, blocs), _par_bloc(b_par_jour, blocs)
    cles = sorted(set(A) | set(B))
    if len(cles) < 3:
        return np.nan, np.nan, len(cles)
    rng = np.random.default_rng(graine)
    idx = np.arange(len(cles))
    diffs = []
    for _ in range(n):
        tir = rng.choice(idx, size=len(idx), replace=True)
        va = [x for k in tir for x in A.get(cles[k], [])]
        vb = [x for k in tir for x in B.get(cles[k], [])]
        if va and vb:
            diffs.append(np.mean(va) - np.mean(vb))
    if len(diffs) < 100:
        return np.nan, np.nan, len(cles)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    va = [x for k in cles for x in A.get(k, [])]
    vb = [x for k in cles for x in B.get(k, [])]
    obs = (np.mean(va) - np.mean(vb)) if va and vb else np.nan
    return float(obs), float((hi - lo) / 2), len(cles)


def distribution_hasard(devenirs_par_jour_et_sens, blocs, n=1000, graine=99):
    """La distribution des séparations sous un biais ALÉATOIRE.

    `devenirs_par_jour_et_sens` : {jour: [(sens_du_signal, devenir), ...]}.

    Le faux biais est tiré **par semaine**, pas par jour : il doit imiter la
    persistance de B1, sinon l'étalon est plus facile à battre que le vrai —
    un biais qui change tous les jours sépare moins bien par construction.

    Rend (p5, p50, p95) des séparations obtenues.
    """
    rng = np.random.default_rng(graine)
    seps = []
    par_bloc = {}
    for jour, items in devenirs_par_jour_et_sens.items():
        par_bloc.setdefault(blocs.get(jour, jour), []).extend(items)
    cles = sorted(par_bloc)
    for _ in range(n):
        a, c = [], []
        for k in cles:
            faux = 1 if rng.random() < 0.5 else -1
            for sens, d in par_bloc[k]:
                if np.isfinite(d):
                    (a if sens == faux else c).append(d)
        if a and c:
            seps.append(np.mean(a) - np.mean(c))
    if len(seps) < 50:
        return np.nan, np.nan, np.nan
    return tuple(float(x) for x in np.percentile(seps, [5, 50, 95]))


def moyenne_par_bloc(valeurs_par_jour, blocs, n=2000, graine=7):
    """Moyenne et IC 95 % d'un seul groupe, bootstrappés par bloc."""
    B = _par_bloc(valeurs_par_jour, blocs)
    cles = sorted(B)
    if len(cles) < 3:
        vals = [x for k in cles for x in B[k]]
        return (float(np.mean(vals)) if vals else np.nan), np.nan, len(cles)
    rng = np.random.default_rng(graine)
    idx = np.arange(len(cles))
    tirages = []
    for _ in range(n):
        tir = rng.choice(idx, size=len(idx), replace=True)
        v = [x for k in tir for x in B[cles[k]]]
        if v:
            tirages.append(np.mean(v))
    lo, hi = np.percentile(tirages, [2.5, 97.5])
    tous = [x for k in cles for x in B[k]]
    return float(np.mean(tous)), float((hi - lo) / 2), len(cles)
