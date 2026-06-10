"""bot3_ablation_3features.py - Mission A Ablation 3 features."""
import json, glob
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)


def load_v4(symbol):
    files = sorted(glob.glob("DATA/datasets/v4_enriched/symbol=" + symbol + ".c.0/**/*.parquet", recursive=True))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce").dt.tz_convert(None)
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)
    df["bias_score_signed"] = (df.get("open_direction", 0).fillna(0) * df.get("open_bias_conf", 0).fillna(0)).clip(-1, 1)
    return df


def load_trades(symbol):
    rows = []
    path = "DATA/BACKTEST/BOT3/trades_" + symbol + "_full_14m_v3.jsonl"
    for line in open(path):
        rows.append(json.loads(line))
    tdf = pd.DataFrame(rows)
    tdf["entry_bar_ts"] = pd.to_datetime(tdf["entry_bar_ts"])
    return tdf


def enrich_trades(trades, v4):
    tdf = trades.sort_values("entry_bar_ts").reset_index(drop=True)
    v4_keys = v4[["ts_event", "regime_favor", "regime_mode", "regime_vol",
                  "bias_score_signed", "open_direction", "open_bias_conf", "vix_regime"]]
    merged = pd.merge_asof(tdf, v4_keys, left_on="entry_bar_ts", right_on="ts_event",
                           direction="backward", tolerance=pd.Timedelta("5min"))
    merged["regime_favor"] = merged["regime_favor"].fillna("NEUTRE")
    merged["regime_vol"] = merged["regime_vol"].fillna("NORMAL")
    merged["bias_score_signed"] = merged["bias_score_signed"].fillna(0.0)
    return merged


def compute_stats(pnls, label):
    if len(pnls) == 0:
        return {"config": label, "N": 0, "WR": 0, "PF": 0, "avg": 0, "PnL": 0, "sharpe": 0, "DD": 0}
    wins = (pnls > 0).sum()
    gw = pnls[pnls > 0].sum() if (pnls > 0).any() else 0
    gl = abs(pnls[pnls < 0].sum()) if (pnls < 0).any() else 1e-9
    pf = gw / gl if gl > 1e-9 else 0
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq).max() if len(eq) > 0 else 0
    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
    return {"config": label, "N": len(pnls), "WR": round(wins/len(pnls)*100, 1),
            "PF": round(pf, 2), "avg": round(pnls.mean(), 2), "PnL": round(pnls.sum(), 0),
            "sharpe": round(sharpe, 2), "DD": round(dd, 0)}


def bootstrap_pf(pnls, n=1000):
    if len(pnls) < 10: return (0, 0)
    pfs = []
    for _ in range(n):
        s = RNG.choice(pnls, size=len(pnls), replace=True)
        gw = s[s>0].sum() if (s>0).any() else 0
        gl = abs(s[s<0].sum()) if (s<0).any() else 1e-9
        pfs.append(gw/gl if gl>1e-9 else 1.0)
    return (float(np.quantile(pfs, 0.025)), float(np.quantile(pfs, 0.975)))


def fold_stab(pnls, k=5):
    if len(pnls) < k*10: return (0.0, 0.0, 0)
    chunks = np.array_split(pnls, k)
    pfs = []
    for c in chunks:
        gw = c[c>0].sum() if (c>0).any() else 0
        gl = abs(c[c<0].sum()) if (c<0).any() else 1e-9
        pfs.append(gw/gl if gl>1e-9 else 1.0)
    return (round(float(np.mean(pfs)), 2), round(float(np.std(pfs)), 2), sum(1 for p in pfs if p>1.0))


def apply_cfg(merged, cfg):
    df = merged.copy()
    if cfg in (2, 5, 6):
        m = ((df["regime_favor"]=="LONG") & (df["side"]=="SHORT")) | \
            ((df["regime_favor"]=="SHORT") & (df["side"]=="LONG"))
        df = df.loc[~m].copy()
    if cfg in (3, 5, 6):
        b = df["bias_score_signed"].fillna(0).values
        sd = df["side"].values
        conf = df["confidence"].fillna(50).values.astype(float)
        adj = conf.copy()
        for i in range(len(df)):
            if sd[i] == "LONG":
                adj[i] = conf[i] + (10*b[i] if b[i]>0 else 20*b[i])
            else:
                adj[i] = conf[i] + (10*abs(b[i]) if b[i]<0 else -20*b[i])
        df = df.loc[adj >= 50].copy()
    if cfg in (4, 6):
        def adj(row):
            if row.get("regime_vol") != "EXTREME":
                return row["pnl_ticks_net"]
            if row.get("exit_reason") == "SL":
                new_sl = abs(row["sl_ticks"]) * 1.5
                if abs(row.get("mae_ticks", 0)) < new_sl:
                    return row.get("mfe_ticks", 0) * 0.5
                return row["pnl_ticks_net"] * 1.5
            return row["pnl_ticks_net"]
        df["pnl_adj"] = df.apply(adj, axis=1)
        return df["pnl_adj"].values
    return df["pnl_ticks_net"].values


def main():
    out = []
    for sym in ["NQ", "ES"]:
        print()
        print("=== " + sym + " ===")
        v4 = load_v4(sym)
        trades = load_trades(sym)
        trades = trades[trades["entry_bar_ts"] >= "2025-12-15"].reset_index(drop=True)
        print("  trades in window: " + str(len(trades)))
        merged = enrich_trades(trades, v4)
        print("  regime_favor: " + str(merged.regime_favor.value_counts().to_dict()))
        print("  regime_vol:   " + str(merged.regime_vol.value_counts().to_dict()))

        configs = {1:"BASELINE", 2:"+regime_favor", 3:"+bias_score", 4:"+regime_vol",
                   5:"+favor+bias", 6:"+ALL3"}
        for cid, name in configs.items():
            pnls = apply_cfg(merged, cid)
            s = compute_stats(pnls, sym + "_" + name)
            ci = bootstrap_pf(pnls)
            fs = fold_stab(pnls)
            s["ci_lo"] = round(ci[0], 2)
            s["ci_hi"] = round(ci[1], 2)
            s["fold_pf"] = fs[0]
            s["fold_std"] = fs[1]
            s["fold_n_pos"] = fs[2]
            out.append(s)
            print("  {:14s} N={:5d} WR={:5.1f}% PF={:.2f} [CI {:.2f}-{:.2f}] avg={:+6.2f}t fold pf={:.2f}+-{:.2f}".format(
                name, s["N"], s["WR"], s["PF"], ci[0], ci[1], s["avg"], fs[0], fs[1]))

    pd.DataFrame(out).to_csv("DATA/BACKTEST/BOT3/ABLATION/ablation_results.csv", index=False)
    print()
    print("Saved CSV")


if __name__ == "__main__":
    main()
