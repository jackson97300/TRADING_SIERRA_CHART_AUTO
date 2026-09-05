#!/usr/bin/env python3
"""
Verification semantique — chaque feature vaut-elle ce que son nom dit ?
Usage: python semantic_check.py "data/*.jsonl" [--tick 0.25] [--out rapport.csv]
Convention testee : dist_<niveau> = (niveau - close) en ticks  (positif = niveau AU-DESSUS du prix)
Sortie : un tableau check -> % de barres en echec, ecart median, exemple.
"""
import glob, argparse, numpy as np, pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from CORE.features import recalc

# Journees ecartees : trous internes massifs (15 a 122 minutes manquantes en
# seance cash), pas seances courtes. 0619 et 0703 sont aussi des feries CME,
# mais ce n'est pas ce qui explique leurs donnees. Cf CONVENTIONS.md §4.
JOURS_EN_PANNE = {"20260612", "20260619", "20260624", "20260625", "20260630",
                  "20260703", "20260803", "20260805", "20260810", "20260904"}


def load(path, tout=False):
    df = pd.concat([pd.read_json(f, lines=True) for f in sorted(glob.glob(path))], ignore_index=True)
    # Selection mesuree, pas raisonnee : la derniere occurrence est la moins
    # complete (548 champs contre 573 le 04/09) et porte les nulls.
    _ordre = {"stable": 0, "warmup": 1, "degraded": 2}
    _r = (df["data_quality_flag"].map(_ordre).fillna(3)
          if "data_quality_flag" in df.columns else 0)
    df = (df.assign(_r=_r, _n=-df.notna().sum(axis=1))
            .sort_values(["ts", "_r", "_n"], kind="mergesort")
            .drop_duplicates("ts", keep="first")
            .drop(columns=["_r", "_n"]).reset_index(drop=True))
    df["dt"] = pd.to_datetime(df.ts, unit="ms")
    if not tout:
        n0 = len(df)
        # Le filtre unique de CONVENTIONS.md §4 : une ligne degraded a des
        # colonnes derivees vides ET des OHLC non fiables (pdh recalcule tombe
        # a 64,4 % contre 70,1 % quand on les inclut).
        if "data_quality_flag" in df.columns:
            df = df[df.data_quality_flag == "stable"]
        df = df[~df.dt.dt.strftime("%Y%m%d").isin(JOURS_EN_PANNE)].reset_index(drop=True)
        print("[filtre] %d -> %d lignes (stable + %d journees en panne ecartees)"
              % (n0, len(df), len(JOURS_EN_PANNE)))
    return df

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--tick", type=float, default=0.25)
    ap.add_argument("--out", default="semantic_report.csv")
    ap.add_argument("--out-jours", default="semantic_par_jour.csv")
    ap.add_argument("--seuil-rupture", type=float, default=0.30,
                    help="ecart de taux d'echec entre deux jours consecutifs "
                         "au-dela duquel on parle de rupture")
    a = ap.parse_args()
    df = load(a.path); T = a.tick
    JOURS = df.dt.dt.date            # ventilation temporelle
    PAR_JOUR = {}                    # check -> Series(jour -> taux d'echec)
    BOOTS = (df.groupby(JOURS)["boot_id"].first().astype(str)
             if "boot_id" in df.columns else None)
    n_dup = pd.concat([pd.read_json(f, lines=True) for f in sorted(glob.glob(a.path))]).ts.duplicated().sum()
    print(f"[load] {len(df)} barres uniques ({n_dup} doublons ts retires), {df.dt.min()} -> {df.dt.max()}")
    C = df.close.astype(float); R = []
    # Cle de session : importee, jamais reimplementee. La version precedente
    # codait `dt + 2h` en dur, soit 22:00 UTC — juste en heure d'hiver, faux en
    # heure d'ete ou la session ouvre a 21:00. Les barres 21:00-22:00 etaient
    # donc attribuees au jour suivant pendant tout l'ete.
    SESS = pd.Series(recalc.session_sess(df.dt), index=df.index)

    def chk(name, expected, actual, tol, unit="", mask=None, note=""):
        e, o = pd.Series(expected, index=df.index).astype(float), pd.Series(actual, index=df.index).astype(float)
        m = e.notna() & o.notna()
        if mask is not None: m &= mask
        if m.sum() == 0: R.append((name, "N/A", 0, np.nan, np.nan, "aucune barre testable", note)); return
        d = (o - e)[m]; bad = (d.abs() > tol)
        # signe inverse ?
        flip = ((o[m] * e[m]) < 0) & (e[m].abs() > tol)
        ex = ""
        if bad.any():
            i = bad.idxmax(); ex = f"{df.dt[i]} attendu={e[i]:.2f} obtenu={o[i]:.2f}"
        R.append((name, f"{100*bad.mean():.1f}%", int(m.sum()), round(float(d.median()),3), round(float(100*flip.mean()),1), ex, note))
        # Taux d'echec jour par jour : c'est la seule facon de distinguer
        # "toujours faux" de "casse le 3 juillet".
        try:
            PAR_JOUR[name] = bad.groupby(JOURS[m]).mean()
        except Exception:
            pass

    # --- OHLC de base
    chk("high >= max(open,close)", np.maximum(df.open, C), np.minimum(df.high, np.maximum(df.open, C)), 0)
    chk("low  <= min(open,close)", np.minimum(df.open, C), np.maximum(df.low, np.minimum(df.open, C)), 0)
    chk("range_size = high-low (pts)", df.high - df.low, df.range_size, 0.01)
    chk("bar_body_ticks = |close-open|/tick", (C - df.open).abs()/T, df.bar_body_ticks, 1)
    chk("bar_body_pct = body/range*100", 100*(C-df.open).abs()/(df.high-df.low).replace(0,np.nan), df.bar_body_pct, 1)
    chk("range_size_ticks = (high-low)/tick", (df.high-df.low)/T, df.range_size_ticks, 2, note="si echec massif: mesure autre chose que la barre")

    # --- volume / delta
    chk("volume = total_vol", df.total_vol, df.volume, 0)
    chk("total_vol = buy+sell", df.buy_vol + df.sell_vol, df.total_vol, 0)
    chk("delta_bar = buy-sell", df.buy_vol - df.sell_vol, df.delta_bar, 0)
    chk("ask_pct + bid_pct = 1", 1.0, df.ask_pct + df.bid_pct, 0.001)
    chk("ask_pct = buy/total", df.buy_vol/df.total_vol.replace(0,np.nan), df.ask_pct, 0.002)
    chk("delta_pct = delta/total", df.delta_bar/df.total_vol.replace(0,np.nan), df.delta_pct, 0.002)
    chk("delta_bar_vol_norm = delta_pct", df.delta_pct, df.delta_bar_vol_norm, 0.002)
    chk("ask_bid_imbalance = ask_pct-bid_pct", df.ask_pct - df.bid_pct, df.ask_bid_imbalance, 0.002)
    chk("cvd_bar_delta = delta_bar", df.delta_bar, df.cvd_bar_delta, 0)
    # cumul depuis le debut de journee de session (session_date)
    cum = df.groupby(SESS).delta_bar.cumsum()
    chk("delta_day = cumsum(delta_bar) par session Sierra", cum, df.delta_day, 1, note="si echec: autre borne de session ou autre source")
    cum_sd = df.groupby("session_date").delta_bar.cumsum()
    chk("delta_day = cumsum par session_date (temoin)", cum_sd, df.delta_day, 1, note="temoin : compare l'ancienne cle a la nouvelle")
    chk("cvd_day = delta_day", df.delta_day, df.cvd_day, 0)
    cum_cash = df[df.is_in_us_cash==1].groupby("date_et").delta_bar.cumsum()
    chk("cvd_session = cumsum(delta) depuis 9h30 ET", cum_cash.reindex(df.index), df.cvd_session, 1, mask=(df.is_in_us_cash==1))

    # --- distances : convention (niveau - close)/tick
    for lvl, dist in [("vwap_d","dist_vwap_d"),("vwap_w","dist_vwap_w"),("vwap_m","dist_vwap_m"),
                      ("cur_vpoc","dist_cur_vpoc"),("cur_vah","dist_cur_vah"),("cur_val","dist_cur_val"),
                      ("prev_vpoc","dist_prev_vpoc"),("prev_vah","dist_prev_vah"),("prev_val","dist_prev_val"),
                      ("pvwap","dist_prev_vwap"),("pvwap_sd1u","dist_prev_vwap_sd1u"),("pvwap_sd1d","dist_prev_vwap_sd1d"),
                      ("vwap_d_sd1u","dist_vwap_d_sd1u"),("vwap_d_sd2u","dist_vwap_d_sd2u"),("vwap_d_sd1d","dist_vwap_d_sd1d"),
                      ("pdh","dist_pdh"),("pdl","dist_pdl"),("sess_high","dist_sess_high"),("sess_low","dist_sess_low"),
                      ("ovn_high","dist_ovn_high"),("ovn_low","dist_ovn_low"),("ib_high","dist_ib_high"),("ib_low","dist_ib_low"),
                      ("open_cash","dist_open_cash"),("open_830","dist_open_830"),("cash_high","dist_cash_high_atr"),
                      ("asia_high","dist_asia_high_pct")]:
        # Deux colonnes peuvent porter le meme niveau : l'alias DMP (`prev_vpoc`)
        # et le snapshot cable le 19/06 (`prev_vpoc_lvl`). On retient celle qui
        # alimente reellement la distance, et on le dit dans le rapport.
        sources = [c for c in (lvl + "_lvl", lvl) if c in df]
        if not sources or dist not in df:
            continue
        if len(sources) > 1:
            def _colle(c):
                if dist.endswith("_pct"): e = 100*(df[c]-C)/C; tol = 0.01
                elif dist.endswith("_atr"): e = (df[c]-C)/df.atr_14m.replace(0,np.nan); tol = 0.05
                else: e = (df[c]-C)/T; tol = 1.5
                m = e.notna() & df[dist].notna()
                return float((e[m]-df[dist][m]).abs().le(tol).mean()) if m.sum() else -1.0
            sources.sort(key=_colle, reverse=True)
        src = sources[0]
        note_src = ("source reelle: %s" % src) if src != lvl else ""
        if dist.endswith("_pct"): chk(f"{dist} = ({src}-close)/close*100", 100*(df[src]-C)/C, df[dist], 0.01, note=note_src)
        elif dist.endswith("_atr"): chk(f"{dist} = ({src}-close)/atr_14m", (df[src]-C)/df.atr_14m.replace(0,np.nan), df[dist], 0.05, note=note_src or "teste atr_14m; sinon voir 'atr'")
        else: chk(f"{dist} = ({src}-close)/tick", (df[src]-C)/T, df[dist], 1.5, note=note_src)

    # --- variantes _atr et _pct derivees des distances en ticks
    for base in ["dist_vwap_d","dist_vwap_w","dist_vwap_m","dist_prev_vpoc","dist_pdh","dist_pdl"]:
        if base+"_atr" in df:
            cands = []
            for nom_d, den in (("atr", df.atr), ("atr_14m", df.atr_14m)):
                d = den.replace(0, np.nan)
                for nom_u, num in ((f"{base}", df[base]), (f"{base}*tick", df[base]*T)):
                    for sgn, lib in ((1, ""), (-1, "-")):
                        cands.append((f"{lib}{nom_u}/{nom_d}", sgn*num/d))
            def _colle(x):
                e = x[1]; o = df[base+"_atr"]
                m = e.notna() & o.notna()
                return float((e[m]-o[m]).abs().le(0.05).mean()) if m.sum() else -1.0
            cands.sort(key=_colle, reverse=True)
            lib, val = cands[0]
            chk(f"{base}_atr = {lib}", val, df[base+"_atr"], 0.05,
                note=("formule retenue parmi 8 candidates" if _colle(cands[0]) > 0.5
                      else "AUCUNE des 8 formules candidates ne colle"))
        if base+"_pct" in df:
            chk(f"{base}_pct = {base}*tick/close*100", 100*df[base]*T/C, df[base+"_pct"], 0.01)
    chk("dist_cur_vwap_vp = dist_vwap_d", df.dist_vwap_d, df.dist_cur_vwap_vp, 0.5)

    # --- coherence des niveaux entre eux
    _pv = "prev_vpoc_lvl" if "prev_vpoc_lvl" in df else "prev_vpoc"
    _ph = "prev_vah_lvl" if "prev_vah_lvl" in df else "prev_vah"
    _pl = "prev_val_lvl" if "prev_val_lvl" in df else "prev_val"
    chk(f"{_ph} >= {_pv}", df[_pv], np.minimum(df[_ph], df[_pv]), 0)
    chk(f"{_pv} >= {_pl}", df[_pl], np.minimum(df[_pv], df[_pl]), 0)
    chk("cur_vah >= cur_vpoc >= cur_val", df.cur_val, np.minimum(np.minimum(df.cur_vah, df.cur_vpoc), df.cur_val), 0)
    chk("vwap_d_sd1u-vwap_d = vwap_d-vwap_d_sd1d (bandes symetriques)", df.vwap_d - df.vwap_d_sd1d, df.vwap_d_sd1u - df.vwap_d, 0.5)
    chk("vwap_d_sd2u-vwap_d = 2*(sd1u-vwap_d)", 2*(df.vwap_d_sd1u - df.vwap_d), df.vwap_d_sd2u - df.vwap_d, 0.5)
    chk("sess_high >= high (monotone)", df.high, np.minimum(df.sess_high, df.high), 0)
    chk("sess_low <= low", df.low, np.maximum(df.sess_low, df.low), 0)
    us = df.is_in_us_cash == 1
    ib_done = us & (df.ib_complete == 1)
    chk("ib_range_ticks = (ib_high-ib_low)/tick", (df.ib_high-df.ib_low)/T, df.ib_range_ticks, 1.5, mask=ib_done)
    chk("ib_range constante apres IB (par jour)", df[ib_done].groupby("date_et").ib_range_ticks.transform("first").reindex(df.index), df.ib_range_ticks, 0.5, mask=ib_done)
    chk("ib_range_atr = ib_range_ticks*tick/atr_14m", df.ib_range_ticks*T/df.atr_14m.replace(0,np.nan), df.ib_range_atr, 0.1, mask=ib_done)
    # pdh/pdl = high/low de la veille (session_date precedente)
    dh = df.groupby(SESS).agg(h=("high","max"), l=("low","min")); dh_prev = dh.shift(1)
    chk("pdh = max(high) session Sierra precedente", SESS.map(dh_prev.h), df.pdh, 0.5, note="echec: pdh defini sur une autre session (RTH ?)")
    chk("pdl = min(low) session Sierra precedente", SESS.map(dh_prev.l), df.pdl, 0.5)
    # open_cash = open de la premiere barre 9h30 ET
    oc = df[us].groupby("date_et").open.first(); oc_c = df[us].groupby("date_et").close.first()
    chk("open_cash = open 1ere barre cash", df.date_et.map(oc), df.open_cash, 0.01, mask=us)
    chk("dist_open_cash utilise open_cash (pas 1ere cloture)", (df.date_et.map(oc)-C)/T, df.dist_open_cash, 1.5, mask=us, note="si echec + 'dist_open_cash = close1' passe: utilise la 1ere CLOTURE")
    chk("dist_open_cash = (close_1ere_barre - close)/tick", (df.date_et.map(oc_c)-C)/T, df.dist_open_cash, 1.5, mask=us)

    # --- momentum / rolling
    chk("momentum_3b = close - close[-3] (pts)", C - C.shift(3), df.momentum_3b, 0.01)
    chk("momentum_5b = close - close[-5] (pts)", C - C.shift(5), df.momentum_5b, 0.01)
    chk("momentum_3b en ticks ?", (C - C.shift(3))/T, df.momentum_3b, 1, note="l'un des deux doit passer")
    chk("ctx_delta_sum_3 = somme delta 3 barres", df.delta_bar.rolling(3).sum(), df.ctx_delta_sum_3, 1)
    chk("ctx_delta_sum_10 = somme delta 10 barres", df.delta_bar.rolling(10).sum(), df.ctx_delta_sum_10, 1)
    chk("ctx_price_slope_5 = close - close[-5]", C - C.shift(5), df.ctx_price_slope_5, 0.5, note="definition supposee")
    # `atr_14m` est en TICKS (CONVENTIONS.md §3) : il faut le convertir en
    # points avant de le rapporter au prix. Le check sans tick echouait a 100 %
    # — c'etait la formule qui etait fausse, pas la colonne.
    chk("atr_14m_pct = atr_14m*tick/close*100", 100*df.atr_14m*T/C, df.atr_14m_pct, 0.01)
    chk("vol_per_sec = total_vol/bar_duration", df.total_vol/df.bar_duration_sec.replace(0,np.nan), df.vol_per_sec, 0.05)
    chk("finish_delta_pct dans [0,1]", np.clip(df.finish_delta_pct,0,1), df.finish_delta_pct, 0)
    chk("rvol = volume / mediane(volume meme minute, jours precedents)", None, None, 0) if False else None
    chk("dist_1d_max_ticks = (pdh - close)/tick ?", (df.pdh-C)/T, df.dist_1d_max_ticks, 1.5, note="'ticks' mais valeurs fractionnaires petites")
    chk("dist_1d_max_ticks = (pdh-close)/atr_14m ?", (df.pdh-C)/df.atr_14m.replace(0,np.nan), df.dist_1d_max_ticks, 0.05)
    chk("dist_1d_max_ticks = (pdh-close)/atr ?", (df.pdh-C)/df.atr.replace(0,np.nan), df.dist_1d_max_ticks, 0.05)
    chk("open_gap_ticks = (open_cash - close_veille_17h)/tick", None, None, 0) if False else None
    # signes booleens
    chk("bool_above_vwap_d = (close > vwap_d)", (C > df.vwap_d).astype(float), df.bool_above_vwap_d, 0)
    chk("vwap_d_side = sign(close - vwap_d)", np.sign(C - df.vwap_d), df.vwap_d_side, 0)
    chk("inside_cur_va = val<=close<=vah", ((C>=df.cur_val)&(C<=df.cur_vah)).astype(float), df.inside_cur_va, 0)
    chk("bool_above_pdh <-> dist_pdh<0", (df.dist_pdh<0).astype(float), (C>df.pdh).astype(float), 0)

    # ================= VENTILATION TEMPORELLE =================
    # Pour chaque identite en echec, on regarde si le taux d'echec est stable
    # dans le temps (une seule formule fautive) ou s'il bascule a une date
    # (deux regimes successifs). Une bascule qui coincide avec un changement
    # de boot_id designe un redemarrage de l'enricher, pas le marche.
    lignes_j = []
    for nom, serie in PAR_JOUR.items():
        if serie.empty:
            continue
        for jour, taux in serie.items():
            lignes_j.append({"check": nom, "jour": str(jour),
                             "taux_echec": round(float(taux), 4),
                             "boot_id": (str(BOOTS.get(jour, ""))[:8]
                                         if BOOTS is not None else "")})
    if lignes_j:
        dj = pd.DataFrame(lignes_j)
        dj.to_csv(a.out_jours, index=False)
        print("\n[ventilation] %s (%d lignes)" % (a.out_jours, len(dj)))

        print("\n" + "=" * 92)
        print("RUPTURES — identites dont le comportement CHANGE dans le temps")
        print("=" * 92)
        ruptures = []
        for nom, serie in PAR_JOUR.items():
            if len(serie) < 6:
                continue
            v = serie.values.astype(float)
            jours_l = list(serie.index)
            saut, pos = 0.0, None
            for i in range(1, len(v)):
                d = abs(v[i] - v[i - 1])
                if d > saut:
                    saut, pos = d, i
            if saut < a.seuil_rupture:
                continue
            jour_r = jours_l[pos]
            chg_boot = (BOOTS is not None
                        and BOOTS.get(jours_l[pos - 1]) != BOOTS.get(jour_r))
            ruptures.append((saut, nom, jour_r, v[:pos].mean(), v[pos:].mean(),
                             chg_boot))
        ruptures.sort(reverse=True)
        if not ruptures:
            print("  aucune : tous les taux d'echec sont stables dans le temps.")
            print("  -> chaque identite fautive l'est de bout en bout : une")
            print("     formule de correction unique suffira.")
        for saut, nom, jour_r, avant, apres, chg in ruptures[:25]:
            print("  %-52s %s : %5.1f%% -> %5.1f%%%s"
                  % (nom[:52], jour_r, 100 * avant, 100 * apres,
                     "   (CHANGEMENT DE BOOT)" if chg else ""))
        print("\n  %d identites changent de comportement dans le temps."
              % len(ruptures))
        print("  Celles-la ne peuvent PAS etre corrigees par une formule unique :")
        print("  il faut une normalisation par periode, ou reparer la source.")

    rep = pd.DataFrame([r for r in R if r], columns=["check","%echec","n","ecart_median","%signe_inverse","exemple","note"])
    rep.to_csv(a.out, index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print(rep.drop(columns=["exemple"]).to_string(index=False))
    print(f"\n[ecrit] {a.out}")

if __name__ == "__main__": main()
