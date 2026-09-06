"""AXE 3 — Chaque feature dit-elle ce que son nom annonce ?

Pourquoi cet axe passe avant tous les autres
---------------------------------------------
Un cluster construit sur une feature fausse est un faux cluster, et il aura
une belle stabilite. Toute la reduction de phase 1 — 224 clusters, 190
features communes, une partition stable a 89,8 % — repose sur des colonnes
dont personne n'a verifie qu'elles calculent ce que leur nom promet.

C'est aussi le seul controle de la serie qui ne peut pas se tromper de
methode. Les autres reposent sur des metriques inventees (facteur d'horloge,
seuil de correlation, plage de declenchement), et chacune a demande trois a
cinq corrections avant de donner un resultat credible. Ici il n'y a ni seuil
a choisir ni garde a poser : `ask_pct + bid_pct` vaut 1 ou ne le vaut pas.

Ce que le script fait
---------------------
Il verifie des IDENTITES — des egalites qui decoulent de la definition des
features, pas de la theorie du marche. Pour chacune, il rapporte le taux de
violation JOUR PAR JOUR, parce qu'un controle qui echoue seulement a partir
d'une certaine date designe le moment ou la chaine a casse.

Trois natures de resultat, a ne pas confondre :
  - **VIOLEE**    l'egalite ne tient pas : la feature ne calcule pas ce qu'on croit
  - **CONVENTION** l'egalite tient au signe ou a l'unite pres : la feature est
                   juste, mais sa convention n'est pas celle qu'on supposait —
                   c'est une information a documenter, pas un bug
  - **VERIFIEE**  l'egalite tient

Usage :
    python -X utf8 CORE/research/verif_semantique.py
    python -X utf8 CORE/research/verif_semantique.py --jours 75 --symbols ES
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

try:
    from CORE.constants import get_tick_size
except ImportError:  # lance depuis CORE/
    from constants import get_tick_size

# Tolerance relative pour juger deux grandeurs egales.
TOL = 0.01
# Part de barres devant satisfaire l'identite pour qu'elle soit dite verifiee.
PART_OK = 0.98


def charger_jour(chemin: str, rth_seul: bool) -> pd.DataFrame:
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
        return pd.DataFrame()
    df = pd.DataFrame(barres)
    if "ts" in df.columns:
        df = df.sort_values("ts").drop_duplicates("ts", keep="last")
    return df.reset_index(drop=True)


def num(df: pd.DataFrame, c: str):
    return pd.to_numeric(df[c], errors="coerce") if c in df.columns else None


def proche(a, b, tol=TOL):
    """Egalite relative, robuste aux grandeurs proches de zero."""
    ech = np.maximum(np.abs(a), np.abs(b))
    ech = np.where(ech < 1e-9, 1.0, ech)
    return np.abs(a - b) / ech <= tol


def checks_du_jour(df: pd.DataFrame, tick: float) -> list[dict]:
    """Une entree par identite verifiee sur ce jour."""
    out = []

    def ajoute(nom, attendu, obtenu, note=""):
        if attendu is None or obtenu is None:
            return
        m = attendu.notna() & obtenu.notna()
        if m.sum() < 20:
            return
        a, b = attendu[m].to_numpy(float), obtenu[m].to_numpy(float)
        ok = proche(a, b)
        # Meme grandeur au signe pres ? (convention de signe inverse)
        ok_signe = proche(-a, b)
        # Meme grandeur a l'unite pres ? (points vs ticks)
        ok_tick = proche(a / tick, b) | proche(a * tick, b)
        out.append({
            "check": nom, "n": int(m.sum()),
            "part_ok": float(ok.mean()),
            "part_signe_inverse": float(ok_signe.mean()),
            "part_unite": float(ok_tick.mean()),
            "note": note,
        })

    close = num(df, "close")
    atr = num(df, "atr")

    # --- Identites de flux : elles decoulent des definitions, sans theorie
    ask, bid = num(df, "ask_pct"), num(df, "bid_pct")
    if ask is not None and bid is not None:
        ajoute("ask_pct + bid_pct = 1", pd.Series(np.ones(len(df))), ask + bid)

    buy, sell, tot = num(df, "buy_vol"), num(df, "sell_vol"), num(df, "total_vol")
    if buy is not None and sell is not None and tot is not None:
        ajoute("buy_vol + sell_vol = total_vol", buy + sell, tot)
        ajoute("delta_bar = buy_vol - sell_vol", buy - sell, num(df, "delta_bar"))
    if buy is not None and tot is not None and ask is not None:
        ajoute("ask_pct = buy_vol / total_vol", buy / tot.replace(0, np.nan), ask)

    # --- Cumul de session : cvd_day doit etre la somme courante des deltas
    delta = num(df, "delta_bar")
    if delta is not None:
        ajoute("cvd_day = cumul de delta_bar", delta.cumsum(), num(df, "cvd_day"),
               "cumul depuis la premiere barre de seance")

    # --- Distances : la convention (signe, unite) est justement ce qu'on teste
    for niveau, dist in (("vwap_d", "dist_vwap_d"),
                         ("cur_vah", "dist_cur_vah"),
                         ("cur_val", "dist_cur_val"),
                         ("prev_vah", "dist_prev_vah"),
                         ("prev_val", "dist_prev_val"),
                         ("prev_vpoc", "dist_prev_vpoc"),
                         ("pvwap", "dist_pvwap")):
        lv, dv = num(df, niveau), num(df, dist)
        if lv is None or dv is None or close is None:
            continue
        ajoute("%s = (close - %s) en ticks" % (dist, niveau),
               (close - lv) / tick, dv)

    # --- Normalisation ATR : dist_X_atr doit valoir dist_X / atr
    if atr is not None:
        for base in ("dist_vwap_d", "dist_prev_vpoc", "dist_cur_vpoc",
                     "dist_ib_high", "dist_ib_low"):
            d, da = num(df, base), num(df, base + "_atr")
            if d is None or da is None:
                continue
            ajoute("%s_atr = %s / atr" % (base, base), d / atr.replace(0, np.nan), da)

    # --- Initial Balance : figee une fois la fenetre passee
    ibh, ibl, ibr = num(df, "ib_high"), num(df, "ib_low"), num(df, "ib_range_ticks")
    if ibh is not None and ibl is not None and ibr is not None:
        ajoute("ib_range_ticks = (ib_high - ib_low) en ticks",
               (ibh - ibl) / tick, ibr)
    if ibr is not None and "mins_et" in df.columns:
        mins = num(df, "mins_et")
        apres = df[(mins >= 630) & ibr.notna() & (ibr > 0)]
        if len(apres) > 20:
            vals = pd.to_numeric(apres["ib_range_ticks"], errors="coerce")
            out.append({"check": "ib_range_ticks figee apres 10h30 ET",
                        "n": len(apres),
                        "part_ok": float((vals == vals.iloc[0]).mean()),
                        "part_signe_inverse": 0.0, "part_unite": 0.0,
                        "note": "une IB qui bouge apres sa fenetre est recalculee"})

    # --- Bornes : une part doit rester dans sa plage
    for col, lo, hi in (("range_pos_va", 0.0, 100.0), ("ask_pct", 0.0, 1.0),
                        ("bid_pct", 0.0, 1.0), ("va_position_pct", 0.0, 1.0)):
        s = num(df, col)
        if s is None or s.notna().sum() < 20:
            continue
        v = s.dropna()
        out.append({"check": "%s dans [%g, %g]" % (col, lo, hi), "n": len(v),
                    "part_ok": float(((v >= lo) & (v <= hi)).mean()),
                    "part_signe_inverse": 0.0, "part_unite": 0.0, "note": ""})

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched/sierra")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=75)
    ap.add_argument("--tout", action="store_true")
    ap.add_argument("--sortie", default="DOCS/VERIF_SEMANTIQUE.md")
    ap.add_argument("--json", default="DATA/verif_semantique.json")
    args = ap.parse_args()

    rapport = ["# Verification semantique des features\n\n",
               "Genere par `CORE/research/verif_semantique.py`.\n\n",
               "Verifie des **identites** — des egalites qui decoulent de la "
               "definition des features, pas d'une theorie du marche. Aucun "
               "seuil arbitraire n'intervient : `ask_pct + bid_pct` vaut 1 ou "
               "ne le vaut pas.\n\n",
               "Trois natures de resultat : **VERIFIEE** (l'egalite tient), "
               "**CONVENTION** (elle tient au signe ou a l'unite pres — la "
               "feature est juste mais sa convention n'est pas celle qu'on "
               "supposait), **VIOLEE** (elle ne calcule pas ce qu'on croit).\n"]

    sortie = {}
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        tick = get_tick_size(sym)
        fichiers = sorted(glob.glob(os.path.join(args.data, sym, "*.jsonl")))[-args.jours:]
        par_check: dict[str, list] = {}
        jours_vus = 0

        print("Analyse %s (tick %.2f)..." % (sym, tick), end=" ", flush=True)
        for chemin in fichiers:
            df = charger_jour(chemin, rth_seul=not args.tout)
            if df.empty:
                continue
            jours_vus += 1
            jour = str(df.get("session_date_trading",
                              df.get("session_date")).iloc[0])[:10]
            for c in checks_du_jour(df, tick):
                c["jour"] = jour
                par_check.setdefault(c["check"], []).append(c)
        print("OK (%d jours, %d identites)" % (jours_vus, len(par_check)))

        lignes = []
        for check, entrees in par_check.items():
            n_tot = sum(e["n"] for e in entrees)
            moy = float(np.mean([e["part_ok"] for e in entrees]))
            moy_sig = float(np.mean([e["part_signe_inverse"] for e in entrees]))
            moy_uni = float(np.mean([e["part_unite"] for e in entrees]))
            jours_ko = [e["jour"] for e in entrees if e["part_ok"] < PART_OK]
            if moy >= PART_OK:
                verdict, detail = "VERIFIEE", ""
            elif moy_sig >= PART_OK:
                verdict, detail = "CONVENTION", "signe inverse de l'attendu"
            elif moy_uni >= PART_OK:
                verdict, detail = "CONVENTION", "unite differente (points/ticks)"
            else:
                verdict, detail = "VIOLEE", ""
            lignes.append({
                "check": check, "verdict": verdict, "detail": detail,
                "n": n_tot, "part_ok": moy, "part_signe": moy_sig,
                "part_unite": moy_uni, "jours": len(entrees),
                "jours_ko": jours_ko, "note": entrees[0]["note"],
            })

        ordre = {"VIOLEE": 0, "CONVENTION": 1, "VERIFIEE": 2}
        lignes.sort(key=lambda l: (ordre[l["verdict"]], l["part_ok"]))

        print("\n" + "=" * 78)
        print("%s — %d identites sur %d jours" % (sym, len(lignes), jours_vus))
        print("=" * 78)
        for v in ("VIOLEE", "CONVENTION", "VERIFIEE"):
            grp = [l for l in lignes if l["verdict"] == v]
            if not grp:
                continue
            print("\n  %s (%d)" % (v, len(grp)))
            for l in grp:
                sup = ""
                if l["verdict"] == "CONVENTION":
                    sup = "  <- %s" % l["detail"]
                elif l["verdict"] == "VIOLEE":
                    sup = "  (signe: %.0f%%  unite: %.0f%%)" % (
                        100 * l["part_signe"], 100 * l["part_unite"])
                print("     %-46s %5.1f%% des barres%s"
                      % (l["check"][:46], 100 * l["part_ok"], sup))
                if l["verdict"] == "VIOLEE" and l["jours_ko"] and \
                        len(l["jours_ko"]) < l["jours"]:
                    print("        echoue %d jours sur %d, a partir du %s"
                          % (len(l["jours_ko"]), l["jours"], min(l["jours_ko"])))

        rapport.append("\n## %s — %d identites sur %d jours\n\n" % (sym, len(lignes), jours_vus))
        rapport.append("| identite | verdict | barres conformes | n | detail |\n")
        rapport.append("|---|---|---|---|---|\n")
        for l in lignes:
            rapport.append("| `%s` | **%s** | %.1f %% | %d | %s |\n"
                           % (l["check"], l["verdict"], 100 * l["part_ok"],
                              l["n"], l["detail"] or l["note"]))
        sortie[sym] = lignes

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(sortie, fh, indent=2, ensure_ascii=False)
    print("\nRapport : %s" % args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
