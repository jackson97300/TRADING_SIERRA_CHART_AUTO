"""Reproduction des `ctx_*` — le verrou de L4 J2 (point 4 de la nuit du 08/09).

    python -X utf8 V3/tests/test_ctx.py

ATTENDU : sur 2 journées × 2 instruments, les colonnes `ctx_*` que LA
DÉCISION LIT se reproduisent à l'identique en rejouant le code même de
production (`CtxRollingCalculator`) dans les conditions du pipeline —
**mismatch = 0**, comme la parité `direction()`.

L'attendu initial (« mismatch = 0 brut, ordre du fichier ») a été raffiné
TROIS fois par la mesure, et chaque fois c'était une CONVENTION, pas une
formule fausse — la règle « deux conventions avant une anomalie », vérifiée
trois fois de suite :
  1. le JSONL arrondit à 6 décimales (mesuré `0.013569`) → comparer
     `round(recalculé, 6)`, pas un rtol plus fin que l'écriture ;
  2. fichier découpé par DATE UTC, pipeline par JOURNÉE DE TRADING ;
  3. blocs RÉ-ÉMIS → dédoublonner, et ne comparer que les barres `stable`
     (la décision ne lit qu'elles).

UNE colonne est CONDAMNÉE et exclue du critère : `ctx_rvol_session`. Les
jours à ré-émission, le producteur la CONTAMINE (l'accumulateur de session
compte les lignes ré-émises : 221 barres fausses le 04/09, 17:19→20:58,
ratio ~0,46) — livrée fausse, donc irreproductible par construction.
INTERDITE pour L4 (la SPEC interdit déjà « tout ctx_* non relu » ;
celle-ci est relue et condamnée). Le test la MESURE et l'affiche, sans
échouer dessus. Correction côté producteur : avec la dette C++ groupée.

Pourquoi ce test existe : la RELECTURE des formules ne reproduisait pas les
données (« absorption true à delta +20, seuil relu 30 ; climax false à vol_z
2,14, seuil relu 1,0 ») — la relecture avait raté les conditions COMPOSÉES
(climax = vol_z > 2 ET range_pos extrême, absorption lit `bn_absorb_*`, pas
le delta). Sans reproduction prouvée, « L4 recalcule selon la formule » n'a
pas de sens : on recalculerait contre une formule qu'on sait fausse.

Conditions de reproduction (mesurées, pas supposées) :
  - **le fichier est découpé par DATE UTC (première barre 00:00), le pipeline
    par JOURNÉE DE TRADING (reset 18:00 ET = 22:00 UTC en EDT)** — la deuxième
    convention classique du dépôt. Au moment de la ligne 1 du fichier, le
    pipeline avait donc ~2 h d'état, et SON reset tombe au milieu du fichier ;
  - le replay reproduit ça : CHAUFFE depuis les barres ≥ 22:00 UTC du fichier
    de la veille, puis reset du calculateur à chaque changement de journée de
    trading, exactement comme `sierra_pipeline` ;
  - **l'enricher RÉ-ÉMET des blocs entiers** (mesuré le 04/09 : 2 000 lignes
    pour 1 260 minutes, deux retours en arrière du ts) — l'ordre brut du
    fichier n'est donc PAS un flux rejouable. Ce que la décision lit passe par
    `dedoublonner_par_minute` (CONVENTIONS §4, seul ordre admis) : le test
    compare la série DÉDOUBLONNÉE chronologique, celle que L4 consommera.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.ctx_rolling import CtxRollingCalculator             # noqa: E402
from CORE.features.recalc import dedoublonner_par_minute      # noqa: E402

JOURS = ("20260903", "20260904")
VEILLES = {"20260903": "20260902", "20260904": "20260903"}
SYMS = ("ES", "NQ")
BOUNDARY_UTC_H = 22       # 18:00 ET en EDT — la frontiere de journee de trading
ENTREES = ["close", "bar_high", "bar_low", "delta_bar", "total_vol", "atr",
           "buy_vol", "sell_vol", "vwap_d", "finish_strength", "range_pos",
           "va_position_pct", "bn_absorb_ask", "bn_absorb_bid"]
DECIMALES_JSONL = 6      # la precision d'ecriture du pipeline, mesuree
# Contaminee par le producteur les jours a re-emission — mesuree, condamnee,
# INTERDITE pour L4. Cf le docstring.
CONDAMNEES = {"ctx_rvol_session"}


def _lignes(sym, jour):
    chemin = "DATA/live_enriched/sierra/%s/%s_%s_sierra_enriched.jsonl" % (
        sym, jour, sym)
    if not os.path.exists(chemin):
        return []
    out = []
    for ln in open(chemin, encoding="utf-8", errors="ignore"):
        ln = ln.strip()
        if ln[:1] != "{":
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _compare(livre, calcule):
    """Compte les écarts d'une colonne. NaN = NaN ; bool exact ; float à
    RTOL près."""
    n = 0
    for a, b in zip(livre, calcule):
        a_nan = a is None or (isinstance(a, float) and np.isnan(a))
        b_nan = b is None or (isinstance(b, float) and np.isnan(b))
        if a_nan and b_nan:
            continue
        if a_nan != b_nan:
            n += 1
            continue
        if isinstance(b, (bool, np.bool_)) or isinstance(a, bool):
            n += int(bool(a) != bool(b))
        else:
            try:
                n += int(abs(round(float(b), DECIMALES_JSONL) - float(a))
                         > 10.0 ** -(DECIMALES_JSONL + 2))
            except (TypeError, ValueError):
                n += int(str(a) != str(b))
    return n


def _jour_trading(ts_ms):
    """La journee de trading d'une barre : bascule a BOUNDARY_UTC_H."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromtimestamp(ts_ms / 1000, timezone.utc)
    if d.hour >= BOUNDARY_UTC_H:
        d = d + timedelta(days=1)
    return d.date()


def _ts(o):
    return o.get("ts_raw_ms", o.get("ts"))


def _rejouer(sym, jour):
    """Rejoue les conditions du pipeline : chauffe depuis 22:00 la veille,
    reset a chaque changement de journee de trading. Rend (df_jour, rows)."""
    from datetime import date
    v = VEILLES[jour]
    date_veille = date(int(v[:4]), int(v[4:6]), int(v[6:]))
    # Les barres >= 22:00 UTC du fichier de la veille appartiennent a la
    # journee de trading de `jour` : c'est l'etat que le pipeline avait
    # a la premiere ligne du fichier de `jour`. Dedoublonnees et triees,
    # comme la journee elle-meme.
    chauffe = sorted((o for o in dedoublonner_par_minute(_lignes(sym, v))
                      if _jour_trading(_ts(o)) > date_veille), key=_ts)
    lignes = sorted(dedoublonner_par_minute(_lignes(sym, jour)), key=_ts)
    if not lignes:
        return pd.DataFrame(), []
    calc, rows, jt = CtxRollingCalculator(), [], None
    for garder, o in [(False, o) for o in chauffe] + [(True, o) for o in lignes]:
        t = _jour_trading(_ts(o))
        if jt is not None and t != jt:
            calc.reset()
        jt = t
        f = calc.update(
            close=o.get("close"), bar_high=o.get("bar_high"),
            bar_low=o.get("bar_low"), delta_bar=o.get("delta_bar"),
            total_vol=o.get("total_vol"), atr=o.get("atr"),
            buy_vol=o.get("buy_vol", np.nan), sell_vol=o.get("sell_vol", np.nan),
            vwap_d=o.get("vwap_d", np.nan),
            finish_strength=o.get("finish_strength", np.nan),
            range_pos=o.get("range_pos", np.nan),
            va_position_pct=o.get("va_position_pct", np.nan),
            bn_absorb_ask=o.get("bn_absorb_ask", 0.0),
            bn_absorb_bid=o.get("bn_absorb_bid", 0.0))
        if garder:
            rows.append(f)
    return pd.DataFrame(lignes), rows


def main():
    os.chdir(RACINE)
    total_ecarts, total_cols, absentes = 0, 0, set()
    detail = {}
    for sym in SYMS:
        for jour in JOURS:
            df, rows = _rejouer(sym, jour)
            if df.empty:
                print("  %s %s : fichier indisponible — test impossible"
                      % (sym, jour))
                return 1
            reproduit = pd.DataFrame(rows)
            # La decision ne lit que les barres `stable` (charger_jour) :
            # la comparaison porte sur elles, le replay nourrit tout.
            stable = (df["data_quality_flag"] == "stable"
                      if "data_quality_flag" in df.columns
                      else pd.Series(True, index=df.index))
            cols = [c for c in reproduit.columns if c.startswith("ctx_")]
            for c in cols:
                if c not in df.columns:
                    absentes.add(c)
                    continue
                e = _compare(df.loc[stable, c].tolist(),
                             reproduit.loc[stable.values, c].tolist())
                if c in CONDAMNEES:
                    if e:
                        print("  info %s %s : %s — %d barre(s) contaminee(s) "
                              "par le producteur (colonne condamnee, hors "
                              "critere)" % (sym, jour, c, e))
                    continue
                total_cols += 1
                if e:
                    detail["%s %s %s" % (sym, jour, c)] = (e, int(stable.sum()))
                total_ecarts += e

    print("  ctx_* — %d colonnes comparees sur %d jours x %d instruments"
          % (total_cols, len(JOURS), len(SYMS)))
    if absentes:
        print("  note : %d colonnes calculees mais non livrees (%s)"
              % (len(absentes), ", ".join(sorted(absentes)[:4])))
    if total_ecarts:
        print("  %d ECART(S) — la reproduction N'EST PAS prouvee :"
              % total_ecarts)
        for k, (e, n) in sorted(detail.items()):
            print("     %-42s %d/%d barres" % (k, e, n))
        return 1
    print("  OK : les ctx_* livrees se reproduisent a l'identique — L4 peut")
    print("       « recalculer selon la formule », la formule est prouvee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
