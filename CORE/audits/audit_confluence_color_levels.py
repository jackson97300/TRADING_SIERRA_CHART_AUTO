import json
import numpy as np
import pandas as pd
import time
from glob import glob
from pathlib import Path

ROOT = Path(r"D:/TRADING_SIERRA_CHART_AUTO")
TICK = {"ES": 0.25, "NQ": 0.25}
TP_TICKS = {"ES": 30, "NQ": 60}
SL_TICKS = {"ES": 12, "NQ": 30}
FWD_BARS = 30

LEVELS = [
    ("IB_LOW", "dist_ib_low", "LONG", 0.0005),
    ("MQ_PUT_0DTE", "dist_mq_put_0dte", "LONG", 0.0005),
    ("PVAL", "dist_prev_val", "LONG", 0.0005),
    ("IB_HIGH", "dist_ib_high", "SHORT", 0.0005),
    ("MQ_CALL", "dist_mq_call", "SHORT", 0.0005),
    ("PVAH", "dist_prev_vah", "SHORT", 0.0005),
    ("SWING_HIGH", "dist_swing_high", "SHORT", 0.0005),
    ("CUR_VAH", "dist_cur_vah", "SHORT", 0.0005),
    ("CUR_VPOC_SHORT", "dist_cur_vpoc", "SHORT", 0.0003),
    ("CUR_VPOC_LONG", "dist_cur_vpoc", "LONG", 0.0003),
    ("SWING_LOW", "dist_swing_low", "LONG", 0.0005),
]

CONFLUENCES = [
    ("IB_LOW_color_up_2", "IB_LOW", "bn_color_up_2", "LONG"),
    ("IB_LOW_long_up_bar", "IB_LOW", "bar_long_up_bar", "LONG"),
    ("MQ_PUT_0DTE_color_up_2", "MQ_PUT_0DTE", "bn_color_up_2", "LONG"),
    ("MQ_PUT_0DTE_long_up_bar", "MQ_PUT_0DTE", "bar_long_up_bar", "LONG"),
    ("PVAL_color_up_2", "PVAL", "bn_color_up_2", "LONG"),
    ("CUR_VPOC_color_up_2", "CUR_VPOC_LONG", "bn_color_up_2", "LONG"),
    ("SWING_LOW_color_up_2", "SWING_LOW", "bn_color_up_2", "LONG"),
    ("IB_HIGH_color_dn_2", "IB_HIGH", "bn_color_dn_2", "SHORT"),
    ("IB_HIGH_long_dn_bar", "IB_HIGH", "bar_long_dn_bar", "SHORT"),
    ("MQ_CALL_color_dn_2", "MQ_CALL", "bn_color_dn_2", "SHORT"),
    ("PVAH_color_dn_2", "PVAH", "bn_color_dn_2", "SHORT"),
    ("SWING_HIGH_color_dn_2", "SWING_HIGH", "bn_color_dn_2", "SHORT"),
    ("CUR_VAH_color_dn_2", "CUR_VAH", "bn_color_dn_2", "SHORT"),
    ("CUR_VPOC_color_dn_2", "CUR_VPOC_SHORT", "bn_color_dn_2", "SHORT"),
    ("IB_HIGH_long_up_dn", "IB_HIGH", "bar_long_up_dn", "SHORT"),
    ("IB_LOW_long_dn_up", "IB_LOW", "bar_long_dn_up", "LONG"),
    ("PVAH_long_up_dn", "PVAH", "bar_long_up_dn", "SHORT"),
    ("PVAL_long_dn_up", "PVAL", "bar_long_dn_up", "LONG"),
    ("IB_HIGH_color_up_2_BO", "IB_HIGH", "bn_color_up_2", "LONG"),
    ("IB_LOW_color_dn_2_BO", "IB_LOW", "bn_color_dn_2", "SHORT"),
]

NEEDED_COLS = {"ts","price","atr","session_id",
    "dist_ib_low","dist_ib_high","dist_mq_put_0dte","dist_mq_call",
    "dist_prev_val","dist_prev_vah","dist_cur_vpoc","dist_cur_vah",
    "dist_swing_high","dist_swing_low",
    "bn_color_up","bn_color_dn","bn_color_up_2","bn_color_dn_2",
    "bar_long_up_bar","bar_long_dn_bar","bar_long_up_dn","bar_long_dn_up",
    "dist_ext_color_up","dist_ext_color_dn"}


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            rows.append({k: obj.get(k) for k in NEEDED_COLS if k in obj})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
    return df


def load_symbol(symbol):
    folder = ROOT / "DATA" / symbol
    pattern = str(folder / ("*_" + symbol + ".jsonl"))
    files = sorted(glob(pattern))
    print("[" + symbol + "] " + str(len(files)) + " files")
    dfs = []
    for fp in files:
        d = load_jsonl(Path(fp))
        if not d.empty:
            d["symbol"] = symbol
            dfs.append(d)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def compute_fwd(df, symbol):
    tick = TICK[symbol]
    tp_t = TP_TICKS[symbol] * tick
    sl_t = SL_TICKS[symbol] * tick
    price = df["price"].to_numpy(dtype=float)
    n = len(price)
    F = FWD_BARS
    future = np.full((n, F), np.nan, dtype=float)
    for j in range(1, F + 1):
        future[:n - j, j - 1] = price[j:]
    entry = price.reshape(-1, 1)
    # LONG
    tp_l = entry + tp_t
    sl_l = entry - sl_t
    hit_tp_l = (future >= tp_l)
    hit_sl_l = (future <= sl_l)
    idx_tp_l = np.where(hit_tp_l.any(axis=1), hit_tp_l.argmax(axis=1), F + 1)
    idx_sl_l = np.where(hit_sl_l.any(axis=1), hit_sl_l.argmax(axis=1), F + 1)
    long_pnl = np.full(n, np.nan)
    long_pnl[idx_tp_l < idx_sl_l] = TP_TICKS[symbol]
    long_pnl[idx_sl_l < idx_tp_l] = -SL_TICKS[symbol]
    none_l = (idx_tp_l > F) & (idx_sl_l > F)
    not_nan = ~np.isnan(future)
    has_any = not_nan.any(axis=1)
    last_valid_idx = np.where(has_any, F - 1 - not_nan[:, ::-1].argmax(axis=1), -1)
    last_p = np.where(last_valid_idx >= 0,
                      future[np.arange(n), np.maximum(last_valid_idx, 0)], np.nan)
    timeout_l = (last_p - price) / tick
    long_pnl[none_l] = timeout_l[none_l]
    tie_l = (idx_tp_l == idx_sl_l) & (idx_tp_l <= F)
    long_pnl[tie_l] = -SL_TICKS[symbol]
    long_win = (long_pnl > 0).astype(np.int8)
    # SHORT
    tp_s = entry - tp_t
    sl_s = entry + sl_t
    hit_tp_s = (future <= tp_s)
    hit_sl_s = (future >= sl_s)
    idx_tp_s = np.where(hit_tp_s.any(axis=1), hit_tp_s.argmax(axis=1), F + 1)
    idx_sl_s = np.where(hit_sl_s.any(axis=1), hit_sl_s.argmax(axis=1), F + 1)
    short_pnl = np.full(n, np.nan)
    short_pnl[idx_tp_s < idx_sl_s] = TP_TICKS[symbol]
    short_pnl[idx_sl_s < idx_tp_s] = -SL_TICKS[symbol]
    none_s = (idx_tp_s > F) & (idx_sl_s > F)
    timeout_s = (price - last_p) / tick
    short_pnl[none_s] = timeout_s[none_s]
    tie_s = (idx_tp_s == idx_sl_s) & (idx_tp_s <= F)
    short_pnl[tie_s] = -SL_TICKS[symbol]
    short_win = (short_pnl > 0).astype(np.int8)
    df = df.copy()
    df["fwd_long_pnl_ticks"] = long_pnl
    df["fwd_long_win"] = long_win
    df["fwd_short_pnl_ticks"] = short_pnl
    df["fwd_short_win"] = short_win
    return df


def detect_contact(df, dist_col, prox_pct):
    if dist_col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    sym = df["symbol"].iloc[0]
    tick = TICK[sym]
    d = pd.to_numeric(df[dist_col], errors="coerce")
    pct = (d * tick).abs() / df["price"].astype(float)
    return (pct <= prox_pct) & d.notna()


def stats(pnl, wins):
    n = len(pnl)
    if n == 0:
        return {"n": 0, "wr": np.nan, "pf": np.nan, "avg": np.nan, "sum": 0.0}
    wr = float(wins.mean())
    gw = pnl[pnl > 0].sum()
    gl = -pnl[pnl < 0].sum()
    if gl > 0:
        pf = float(gw / gl)
    elif gw > 0:
        pf = float("inf")
    else:
        pf = np.nan
    return {"n": int(n), "wr": wr, "pf": pf, "avg": float(pnl.mean()), "sum": float(pnl.sum())}


def block_boot_pf(df, col, n_boot=300, block_days=5, seed=42):
    rng = np.random.default_rng(seed)
    if df.empty or df[col].isna().all():
        return (np.nan, np.nan)
    dates = sorted(df["date"].unique())
    if len(dates) < 2 * block_days:
        return (np.nan, np.nan)
    blocks = [dates[i:i + block_days] for i in range(0, len(dates), block_days)]
    samples = []
    for _ in range(n_boot):
        chosen = rng.choice(len(blocks), size=len(blocks), replace=True)
        sd = []
        for idx in chosen:
            sd.extend(blocks[idx])
        sub = df[df["date"].isin(sd)]
        p = sub[col].dropna().to_numpy()
        if len(p) < 5:
            continue
        gw = p[p > 0].sum()
        gl = -p[p < 0].sum()
        if gl == 0:
            continue
        samples.append(gw / gl)
    if not samples:
        return (np.nan, np.nan)
    return (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))


def run_audit(df, symbol):
    rows = []
    baseline = {}
    for lev_name, dist_col, side, prox in LEVELS:
        mask = detect_contact(df, dist_col, prox)
        sub = df[mask].copy()
        if side == "LONG":
            col = "fwd_long_pnl_ticks"
            wcol = "fwd_long_win"
        else:
            col = "fwd_short_pnl_ticks"
            wcol = "fwd_short_win"
        pnl = sub[col].dropna().to_numpy()
        wins = sub[wcol].dropna().to_numpy()
        st = stats(pnl, wins)
        ci_lo, ci_hi = block_boot_pf(sub, col)
        baseline[lev_name] = (st["pf"], st["n"])
        rows.append({
            "symbol": symbol,
            "confluence": lev_name + "_BASELINE",
            "level": lev_name,
            "pattern": "NONE",
            "direction": side,
            "n": st["n"], "wr": st["wr"], "pf": st["pf"],
            "avg_ticks": st["avg"], "sum_ticks": st["sum"],
            "ci95_lo": ci_lo, "ci95_hi": ci_hi,
            "baseline_pf": st["pf"], "baseline_n": st["n"],
            "delta_pf": 0.0, "variant": "BASELINE",
        })
    for conf_name, level_name, pattern_col, direction in CONFLUENCES:
        lev_def = next((l for l in LEVELS if l[0] == level_name), None)
        if lev_def is None:
            continue
        _, dist_col, _, prox = lev_def
        if pattern_col not in df.columns:
            rows.append({"symbol": symbol, "confluence": conf_name,
                "level": level_name, "pattern": pattern_col, "direction": direction,
                "n": 0, "wr": np.nan, "pf": np.nan, "avg_ticks": np.nan, "sum_ticks": 0.0,
                "ci95_lo": np.nan, "ci95_hi": np.nan, "delta_pf": np.nan,
                "baseline_pf": np.nan, "baseline_n": 0, "variant": "A_NO_EXT"})
            continue
        m_level = detect_contact(df, dist_col, prox)
        m_pat = (pd.to_numeric(df[pattern_col], errors="coerce") == 1)
        mask = m_level & m_pat
        sub = df[mask].copy()
        if direction == "LONG":
            col = "fwd_long_pnl_ticks"
            wcol = "fwd_long_win"
        else:
            col = "fwd_short_pnl_ticks"
            wcol = "fwd_short_win"
        pnl = sub[col].dropna().to_numpy()
        wins = sub[wcol].dropna().to_numpy()
        st = stats(pnl, wins)
        ci_lo, ci_hi = block_boot_pf(sub, col)
        bl_pf, bl_n = baseline.get(level_name, (np.nan, 0))
        if not np.isnan(st["pf"]) and not np.isnan(bl_pf):
            delta_pf = st["pf"] - bl_pf
        else:
            delta_pf = np.nan
        rows.append({"symbol": symbol, "confluence": conf_name,
            "level": level_name, "pattern": pattern_col, "direction": direction,
            "n": st["n"], "wr": st["wr"], "pf": st["pf"],
            "avg_ticks": st["avg"], "sum_ticks": st["sum"],
            "ci95_lo": ci_lo, "ci95_hi": ci_hi, "delta_pf": delta_pf,
            "baseline_pf": bl_pf, "baseline_n": bl_n, "variant": "A_NO_EXT"})
        # Variant B avec ext
        if direction == "LONG":
            ext_col = "dist_ext_color_up"
        else:
            ext_col = "dist_ext_color_dn"
        ext_cap = 50 if symbol == "NQ" else 20
        if ext_col in df.columns:
            ext_vals = pd.to_numeric(df[ext_col], errors="coerce")
            m_ext = (ext_vals.abs() <= ext_cap) & ext_vals.notna()
            mask_b = mask & m_ext
            sub_b = df[mask_b].copy()
            pnl_b = sub_b[col].dropna().to_numpy()
            wins_b = sub_b[wcol].dropna().to_numpy()
            st_b = stats(pnl_b, wins_b)
            ci_lo_b, ci_hi_b = block_boot_pf(sub_b, col)
            if not np.isnan(st_b["pf"]) and not np.isnan(bl_pf):
                delta_pf_b = st_b["pf"] - bl_pf
            else:
                delta_pf_b = np.nan
            rows.append({"symbol": symbol, "confluence": conf_name,
                "level": level_name, "pattern": pattern_col + "+ext_close",
                "direction": direction, "n": st_b["n"], "wr": st_b["wr"], "pf": st_b["pf"],
                "avg_ticks": st_b["avg"], "sum_ticks": st_b["sum"],
                "ci95_lo": ci_lo_b, "ci95_hi": ci_hi_b, "delta_pf": delta_pf_b,
                "baseline_pf": bl_pf, "baseline_n": bl_n, "variant": "B_WITH_EXT"})
    return pd.DataFrame(rows)


def main():
    print("=" * 80)
    print("AUDIT CONFLUENCES Bot 3 niveaux x patterns COLOR/LONG BAR")
    print("=" * 80)
    all_results = []
    for sym in ["NQ", "ES"]:
        t0 = time.time()
        print()
        print("[" + sym + "] Loading JSONL...")
        df = load_symbol(sym)
        if df.empty:
            print("[" + sym + "] empty -> skip")
            continue
        nb = len(df)
        nd = df["date"].nunique()
        print("[" + sym + "] bars=" + str(nb) + " days=" + str(nd) +
              " load=" + str(round(time.time() - t0, 1)) + "s")
        for c in NEEDED_COLS:
            if c in df.columns and c != "session_id":
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
        print("[" + sym + "] Computing forward outcomes...")
        t0 = time.time()
        df = compute_fwd(df, sym)
        print("[" + sym + "] fwd done in " + str(round(time.time() - t0, 1)) + "s")
        print("[" + sym + "] Running audit...")
        res = run_audit(df, sym)
        all_results.append(res)
        non_base = res[res["variant"] != "BASELINE"].copy()
        non_base = non_base[non_base["n"] >= 30].sort_values("pf", ascending=False)
        print()
        print("[" + sym + "] TOP confluences (n>=30) :")
        if not non_base.empty:
            cols = ["confluence", "variant", "n", "wr", "pf",
                    "ci95_lo", "baseline_pf", "delta_pf"]
            print(non_base[cols].head(25).to_string(index=False))
        else:
            print("  (none with n>=30)")
        base = res[res["variant"] == "BASELINE"]
        print()
        print("[" + sym + "] BASELINES (niveau seul) :")
        print(base[["confluence", "n", "wr", "pf", "ci95_lo"]].to_string(index=False))
    if all_results:
        full = pd.concat(all_results, ignore_index=True)
        out_path = ROOT / "DATA" / "AUDIT_CONFLUENCES_COLOR.csv"
        full.to_csv(out_path, index=False)
        print()
        print("[OUT] " + str(out_path))
        print("[OUT] " + str(len(full)) + " rows total")


if __name__ == "__main__":
    main()
