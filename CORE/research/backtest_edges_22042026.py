# -*- coding: utf-8 -*-
# Backtest edges + color 21-22/04/2026
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, joblib
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))
from dataset_builder import DatasetBuilder

DATA_PATH = ROOT / "DATA_BACKTEST"
MODELS_PATH = ROOT / "DATA" / "MODELS"
TICK_SIZE = 0.25

def _load_enriched(symbol, normalize=True):
    """Retourne DataFrame enrichi.
    normalize=True -> drop PROHIBITED + cree _atr (pour modeles ML)
    normalize=False -> garde toutes features brutes (pour Phase A analyse)
    """
    b = DatasetBuilder(data_path=str(DATA_PATH), labels_path=str(DATA_PATH/"LABELS"), use_derived=True)
    print("LOAD", symbol, "normalize=" + str(normalize))
    df = b._load_features(symbol)
    df = b._compute_ib_recalc(df, symbol)
    other = "NQ" if symbol == "ES" else "ES"
    df = b._compute_derived(df, symbol, other)
    df = b._compute_menthorq(df, symbol)
    if normalize:
        df = b._normalize_by_atr(df)
    dt = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert("US/Eastern")
    df["datetime_et"] = dt
    df["date_et"] = dt.dt.strftime("%Y-%m-%d")
    df["hour_et"] = dt.dt.hour
    df["minute_et"] = dt.dt.minute
    df["time_et"] = dt.dt.strftime("%H:%M")
    df = df.sort_values("ts").reset_index(drop=True)
    print("LOAD", symbol, len(df), "barres,", len(df.columns), "cols")
    return df


def _rth_mask(df):
    h = df["hour_et"]
    m = df["minute_et"]
    return ((h > 9) | ((h == 9) & (m >= 30))) & (h < 16)


def _fwd(df, h):
    return (df["price"].shift(-h).astype(float) - df["price"].astype(float)) / TICK_SIZE


def _regime(df):
    df = df.copy()
    rth = _rth_mask(df)
    rp = df.get("range_pos", pd.Series(50.0, index=df.index))
    inside = df.get("inside_cur_va", pd.Series(1, index=df.index)).astype(int)
    rs = df.get("range_size_ticks", pd.Series(0.0, index=df.index)).astype(float)
    p50 = rs[rth].median() if rth.sum() else 100.0
    df["is_range"] = ((inside == 1) & (rs < p50 * 1.2) & (rp.between(30, 70))).astype(int)
    df["is_trend"] = (1 - df["is_range"]).astype(int)
    regs = {}
    for d, g in df[rth].groupby("date_et"):
        if len(g) >= 2:
            regs[d] = "BULL" if g["price"].iloc[-1] > g["price"].iloc[0] else "BEAR"
    df["day_regime"] = df["date_et"].map(regs).fillna("NA")
    return df


FEATS = ["bar_edge_buy","bar_edge_sell","bar_color_up","bar_color_dn",
         "bar_long_up_bar","bar_long_dn_bar","bn_absorb_bid","bn_absorb_ask",
         "edge_buy_and_color_up","edge_buy_and_long_up","edge_buy_and_absorb_bid",
         "edge_sell_and_color_dn","edge_sell_and_long_dn","edge_sell_and_absorb_ask",
         "color_up_and_long_up","color_dn_and_long_dn"]
HORIZONS = [5, 10, 15, 30, 60]


def _combos(df):
    df = df.copy()
    def g(c):
        return df.get(c, pd.Series(0, index=df.index)).fillna(0).astype(int)
    df["edge_buy_and_color_up"] = (g("bar_edge_buy") & g("bar_color_up")).astype(int)
    df["edge_buy_and_long_up"] = (g("bar_edge_buy") & g("bar_long_up_bar")).astype(int)
    df["edge_buy_and_absorb_bid"] = (g("bar_edge_buy") & g("bn_absorb_bid")).astype(int)
    df["edge_sell_and_color_dn"] = (g("bar_edge_sell") & g("bar_color_dn")).astype(int)
    df["edge_sell_and_long_dn"] = (g("bar_edge_sell") & g("bar_long_dn_bar")).astype(int)
    df["edge_sell_and_absorb_ask"] = (g("bar_edge_sell") & g("bn_absorb_ask")).astype(int)
    df["color_up_and_long_up"] = (g("bar_color_up") & g("bar_long_up_bar")).astype(int)
    df["color_dn_and_long_dn"] = (g("bar_color_dn") & g("bar_long_dn_bar")).astype(int)
    return df



def _stats(df, feat, h, is_bull, seg=None):
    rth = _rth_mask(df)
    mask = rth
    if seg == "range":
        mask = mask & (df["is_range"] == 1)
    elif seg == "trend":
        mask = mask & (df["is_trend"] == 1)
    elif seg in ("BULL", "BEAR"):
        mask = mask & (df["day_regime"] == seg)
    sub = df[mask]
    base = {"feat": feat, "h": h, "seg": seg or "all", "n_fire": 0, "fire_rate": 0.0,
            "wr_up": np.nan, "mean_ticks": np.nan, "std_ticks": np.nan,
            "min_ticks": np.nan, "max_ticks": np.nan, "sharpe": np.nan, "pf": np.nan}
    if len(sub) < 20:
        return base
    fire = sub[feat].fillna(0).astype(int) == 1
    fwd = _fwd(df, h).reindex(sub.index)
    fwd_fire = fwd[fire].dropna()
    if len(fwd_fire) < 5:
        base["n_fire"] = int(fire.sum())
        base["fire_rate"] = float(fire.mean())
        return base
    if is_bull:
        wr = (fwd_fire > 0).mean()
        w = fwd_fire[fwd_fire > 0].sum()
        l = -fwd_fire[fwd_fire < 0].sum()
        pf = w / l if l > 0 else np.inf
    else:
        wr = (fwd_fire < 0).mean()
        w = -fwd_fire[fwd_fire < 0].sum()
        l = fwd_fire[fwd_fire > 0].sum()
        pf = w / l if l > 0 else np.inf
    return {"feat": feat, "h": h, "seg": seg or "all",
            "n_fire": int(len(fwd_fire)), "fire_rate": float(fire.mean()),
            "wr_up": float(wr), "mean_ticks": float(fwd_fire.mean()),
            "std_ticks": float(fwd_fire.std()),
            "min_ticks": float(fwd_fire.min()), "max_ticks": float(fwd_fire.max()),
            "sharpe": float(fwd_fire.mean() / (fwd_fire.std() + 1e-9)),
            "pf": float(pf) if np.isfinite(pf) else 99.9}


def phase_a(df, symbol):
    print()
    print("=" * 70)
    print("PHASE A -", symbol)
    print("=" * 70)
    df = _combos(df)
    df = _regime(df)
    bull = [f for f in FEATS
            if "buy" in f or "color_up" in f or "long_up" in f or "absorb_bid" in f]
    rows = []
    for f in FEATS:
        if f not in df.columns:
            print(" SKIP", f, "absente")
            continue
        isb = f in bull
        for h in HORIZONS:
            for s in [None, "range", "trend", "BULL", "BEAR"]:
                rows.append(_stats(df, f, h, isb, s))
    return pd.DataFrame(rows)


def _lm(sym, side):
    cfg = json.load(open(MODELS_PATH / (sym + "_" + side + "_config.json")))
    return joblib.load(MODELS_PATH / (sym + "_" + side + "_model.pkl")), cfg


def _score(df, sym, side, m, cfg):
    feats = cfg["features"]
    th = cfg["threshold"]
    miss = [f for f in feats if f not in df.columns]
    if miss:
        print(" WARN missing", sym, side, len(miss), "->", miss[:5])
        for f in miss:
            df[f] = 0.0
    X = df[feats].copy()
    for c in feats:
        v = pd.to_numeric(X[c], errors="coerce")
        v[v < -1e9] = np.nan
        X[c] = v
    X = X.fillna(X.median()).fillna(0.0)
    p = m.predict_proba(X.values)[:, 1]
    out = df[["ts", "datetime_et", "date_et", "time_et", "price", "atr"]].copy()
    out["proba"] = p
    out["signal"] = (p >= th).astype(int)
    out["threshold"] = th
    out["side"] = side
    out["symbol"] = sym
    return out


def _gates(ds, df):
    rth = _rth_mask(df)
    ds = ds.copy()
    ds["rth"] = rth.values
    ds["pass_pre"] = ds["rth"] & (ds["signal"] == 1) & (df["atr"].astype(float).values > 0)
    keep = []
    last_ts = {}
    cnt = {}
    for _, r in ds.iterrows():
        if not r["pass_pre"]:
            keep.append(False); continue
        k = (r["symbol"], r["side"], r["date_et"])
        if cnt.get(k, 0) >= 5:
            keep.append(False); continue
        if r["ts"] - last_ts.get((r["symbol"], r["side"]), 0) < 5 * 60 * 1000:
            keep.append(False); continue
        keep.append(True)
        last_ts[(r["symbol"], r["side"])] = r["ts"]
        cnt[k] = cnt.get(k, 0) + 1
    ds["entry"] = keep
    return ds



def _pnl(de, df, side):
    trades = []
    price = df["price"].values
    atr = df["atr"].values
    hi_s = df.get("bar_high", df["price"]).values
    lo_s = df.get("bar_low", df["price"]).values
    ix = {t: i for i, t in enumerate(df["ts"].values)}
    for _, r in de[de["entry"]].iterrows():
        i = ix.get(r["ts"])
        if i is None:
            continue
        ep = price[i]
        at = atr[i]
        if not np.isfinite(at) or at <= 0:
            continue
        sl = max(at * 0.08, 4.0)
        tp = sl * 2.0
        if side == "buy":
            slp = ep - sl * TICK_SIZE
            tpp = ep + tp * TICK_SIZE
        else:
            slp = ep + sl * TICK_SIZE
            tpp = ep - tp * TICK_SIZE
        ex = None
        reason = None
        for j in range(i + 1, min(i + 61, len(price))):
            h = hi_s[j]
            l = lo_s[j]
            if side == "buy":
                if l <= slp:
                    ex = -sl; reason = "SL"; break
                if h >= tpp:
                    ex = tp; reason = "TP"; break
            else:
                if h >= slp:
                    ex = -sl; reason = "SL"; break
                if l <= tpp:
                    ex = tp; reason = "TP"; break
        if ex is None:
            lp = price[min(i + 60, len(price) - 1)]
            d = (lp - ep) / TICK_SIZE
            ex = d if side == "buy" else -d
            reason = "TIME"
        trades.append({"symbol": r["symbol"], "side": side, "ts": r["ts"],
                       "date_et": r["date_et"], "time_et": r["time_et"],
                       "price": ep, "atr": at, "sl_ticks": sl, "tp_ticks": tp,
                       "exit_ticks": ex, "exit_reason": reason, "proba": r["proba"]})
    return pd.DataFrame(trades)


def phase_b(es, nq):
    print()
    print("=" * 70)
    print("PHASE B - Pipeline ML realiste")
    print("=" * 70)
    all_t = []
    for sym, df in [("ES", es), ("NQ", nq)]:
        for side in ["buy", "sell"]:
            try:
                m, cfg = _lm(sym, side)
            except Exception as e:
                print(" SKIP", sym, side, e)
                continue
            print()
            print("--", sym, side, "th=%.3f" % cfg["threshold"],
                  "verdict=", cfg.get("verdict", "NA"), "--")
            ds = _score(df, sym, side, m, cfg)
            ds["date_et"] = df["date_et"].values
            ds = _gates(ds, df)
            trades = _pnl(ds, df, side)
            print(" Signals bruts:", int(ds["signal"].sum()),
                  "| apres gates:", int(ds["entry"].sum()))
            if not trades.empty:
                w = trades[trades["exit_ticks"] > 0]
                l = trades[trades["exit_ticks"] <= 0]
                gw = w["exit_ticks"].sum()
                gl = -l["exit_ticks"].sum()
                pf = gw / gl if gl > 0 else float("inf")
                wr = len(w) / len(trades)
                ev = trades["exit_ticks"].mean()
                print(" Trades:", len(trades),
                      "| WR %.1f%%" % (wr * 100),
                      "| PF %.2f" % pf,
                      "| EV %+.1ft" % ev,
                      "| Total %+.1ft" % trades["exit_ticks"].sum())
                for _, t in trades.iterrows():
                    print("   ", t["date_et"], t["time_et"], t["symbol"], t["side"],
                          "@%.2f" % t["price"], "-> %+.1ft" % t["exit_ticks"],
                          "(" + t["exit_reason"] + ")", "p=%.3f" % t["proba"])
                all_t.append(trades)
    return pd.concat(all_t, ignore_index=True) if all_t else pd.DataFrame()


def phase_c(nq):
    print()
    print("=" * 70)
    print("PHASE C - NQ 22/04 10:00-10:45 ET (entry Jackson @26970)")
    print("=" * 70)
    mask = (nq["date_et"] == "2026-04-22") & nq["time_et"].between("10:00", "10:45")
    sub = nq[mask].copy()
    if sub.empty:
        print("WARN fenetre vide")
        return
    res = {}
    for side in ["buy", "sell"]:
        try:
            m, cfg = _lm("NQ", side)
        except Exception as e:
            print(" SKIP NQ", side, e); continue
        feats = cfg["features"]
        for f in feats:
            if f not in sub.columns:
                sub[f] = 0.0
        X = sub[feats].copy()
        for c in feats:
            v = pd.to_numeric(X[c], errors="coerce")
            v[v < -1e9] = np.nan
            X[c] = v
        X = X.fillna(X.median()).fillna(0.0)
        res[side] = {"proba": m.predict_proba(X.values)[:, 1], "th": cfg["threshold"]}
    header = "%6s %9s %7s %7s %5s %6s %6s %5s %5s %6s %6s %20s"
    print()
    print(header % ("time", "price", "atr", "rng_pos", "range",
                    "edge_b", "edge_s", "col_u", "col_d", "p_buy", "p_sell", "DEC"))
    sr = sub.reset_index(drop=True)
    for i, row in sr.iterrows():
        pb = res.get("buy", {}).get("proba", [np.nan] * len(sr))[i]
        ps = res.get("sell", {}).get("proba", [np.nan] * len(sr))[i]
        tb = res.get("buy", {}).get("th", 1.0)
        ts = res.get("sell", {}).get("th", 1.0)
        dec = "HOLD"
        if np.isfinite(pb) and pb >= tb:
            dec = "BUY p=%.3f" % pb
        elif np.isfinite(ps) and ps >= ts:
            dec = "SELL p=%.3f" % ps
        rp = row.get("range_pos", np.nan)
        inside = int(row.get("inside_cur_va", 0))
        rpstr = "%.1f" % float(rp) if pd.notna(rp) else "na"
        pbstr = "%.3f" % pb if np.isfinite(pb) else "na"
        psstr = "%.3f" % ps if np.isfinite(ps) else "na"
        print(header % (row["time_et"], "%.2f" % row["price"],
                        "%.1f" % float(row.get("atr", 0)),
                        rpstr, inside, int(row.get("bar_edge_buy", 0)),
                        int(row.get("bar_edge_sell", 0)),
                        int(row.get("bar_color_up", 0)),
                        int(row.get("bar_color_dn", 0)),
                        pbstr, psstr, dec))



def main():
    print("=" * 70)
    print("BACKTEST EDGES 21-22/04/2026 - ES + NQ")
    print("=" * 70)
    # Brute (pour Phase A, garde les features PROHIBITED qui sont bruts)
    es_raw = _load_enriched("ES", normalize=False)
    nq_raw = _load_enriched("NQ", normalize=False)
    # Normalise (pour Phase B/C avec modeles LGBM)
    es = _load_enriched("ES", normalize=True)
    nq = _load_enriched("NQ", normalize=True)
    re = phase_a(es_raw, "ES")
    rn = phase_a(nq_raw, "NQ")

    def _sum(r, s):
        print()
        print("--- Summary", s, "(h=15, n_fire>=5) ---")
        cols = ["feat", "seg", "n_fire", "fire_rate", "wr_up", "mean_ticks", "pf"]
        sub = r[(r["h"] == 15) & (r["n_fire"] >= 5)]
        if sub.empty:
            print(" (aucun)")
            return
        sub = sub[cols].sort_values(["feat", "seg"])
        print(sub.to_string(index=False, formatters={
            "fire_rate": "{:.3f}".format, "wr_up": "{:.3f}".format,
            "mean_ticks": "{:+.2f}".format, "pf": "{:.2f}".format,
        }))

    _sum(re, "ES")
    _sum(rn, "NQ")
    all_r = pd.concat([re.assign(symbol="ES"), rn.assign(symbol="NQ")], ignore_index=True)
    outp = ROOT / "CORE" / "research" / "backtest_edges_22042026_phaseA.csv"
    all_r.to_csv(outp, index=False)
    print()
    print("PHASE A CSV ->", outp)
    tr = phase_b(es, nq)
    if not tr.empty:
        outp2 = ROOT / "CORE" / "research" / "backtest_edges_22042026_phaseB_trades.csv"
        tr.to_csv(outp2, index=False)
        print()
        print("PHASE B trades ->", outp2)
    phase_c(nq)
    print()
    print("=" * 70)
    print("CONCLUSION - edge_buy + color_up")
    print("=" * 70)
    key = "edge_buy_and_color_up"
    for sym, r in [("ES", re), ("NQ", rn)]:
        sub = r[(r["feat"] == key) & (r["h"] == 15) & (r["n_fire"] >= 5)]
        if sub.empty:
            print(" ", sym, ": pas assez de fires (<5)")
            continue
        print()
        print(" ", sym, "(h=15):")
        for _, rr in sub.iterrows():
            print("   seg=%-6s n=%4d fire=%.3f WR=%.1f%% mean=%+.2ft PF=%.2f" %
                  (rr["seg"], int(rr["n_fire"]), rr["fire_rate"],
                   rr["wr_up"] * 100, rr["mean_ticks"], rr["pf"]))


if __name__ == "__main__":
    main()
