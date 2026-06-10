import pandas as pd, numpy as np, json
from glob import glob
from pathlib import Path
ROOT = Path(r"D:/TRADING_SIERRA_CHART_AUTO")
TICK = {"ES": 0.25, "NQ": 0.25}
TP_TICKS = {"ES": 30, "NQ": 60}
SL_TICKS = {"ES": 12, "NQ": 30}
FWD_BARS = 30
NEEDED_COLS = {"ts","price","atr","session_id",
    "dist_ib_low","dist_ib_high","dist_mq_put_0dte","dist_mq_call",
    "dist_prev_val","dist_prev_vah","dist_cur_vpoc","dist_cur_vah",
    "dist_swing_high","dist_swing_low",
    "bn_color_up","bn_color_dn","bn_color_up_2","bn_color_dn_2",
    "bar_long_up_bar","bar_long_dn_bar","bar_long_up_dn","bar_long_dn_up",
    "dist_ext_color_up","dist_ext_color_dn"}

def load_jsonl(path):
    rows = []
    with open(path,"r",encoding="utf-8") as f:
        for line in f:
            try: obj = json.loads(line)
            except: continue
            rows.append({k: obj.get(k) for k in NEEDED_COLS if k in obj})
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
    return df

def load_symbol(symbol):
    folder = ROOT / "DATA" / symbol
    files = sorted(glob(str(folder / ("*_" + symbol + ".jsonl"))))
    dfs = []
    for f in files:
        d = load_jsonl(Path(f))
        if not d.empty:
            d["symbol"] = symbol
            dfs.append(d)
    if not dfs: return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)

def detect_contact(df, dist_col, prox_pct):
    if dist_col not in df.columns:
        return pd.Series([False]*len(df), index=df.index)
    sym = df["symbol"].iloc[0]
    tick = TICK[sym]
    d = pd.to_numeric(df[dist_col], errors="coerce")
    pct = (d * tick).abs() / df["price"].astype(float)
    return (pct <= prox_pct) & d.notna()

def compute_fwd(df, symbol):
    tick = TICK[symbol]
    tp_t = TP_TICKS[symbol] * tick
    sl_t = SL_TICKS[symbol] * tick
    price = df["price"].to_numpy(dtype=float)
    n = len(price); F = FWD_BARS
    future = np.full((n, F), np.nan, dtype=float)
    for j in range(1, F + 1):
        future[:n - j, j - 1] = price[j:]
    entry = price.reshape(-1, 1)
    tp_l = entry + tp_t
    sl_l = entry - sl_t
    hit_tp_l = future >= tp_l
    hit_sl_l = future <= sl_l
    idx_tp_l = np.where(hit_tp_l.any(axis=1), hit_tp_l.argmax(axis=1), F + 1)
    idx_sl_l = np.where(hit_sl_l.any(axis=1), hit_sl_l.argmax(axis=1), F + 1)
    long_pnl = np.full(n, np.nan)
    long_pnl[idx_tp_l < idx_sl_l] = TP_TICKS[symbol]
    long_pnl[idx_sl_l < idx_tp_l] = -SL_TICKS[symbol]
    none_l = (idx_tp_l > F) & (idx_sl_l > F)
    not_nan = ~np.isnan(future)
    has_any = not_nan.any(axis=1)
    last_valid_idx = np.where(has_any, F - 1 - not_nan[:, ::-1].argmax(axis=1), -1)
    last_p = np.where(last_valid_idx >= 0, future[np.arange(n), np.maximum(last_valid_idx, 0)], np.nan)
    timeout_l = (last_p - price) / tick
    long_pnl[none_l] = timeout_l[none_l]
    tie_l = (idx_tp_l == idx_sl_l) & (idx_tp_l <= F)
    long_pnl[tie_l] = -SL_TICKS[symbol]
    tp_s = entry - tp_t
    sl_s = entry + sl_t
    hit_tp_s = future <= tp_s
    hit_sl_s = future >= sl_s
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
    df = df.copy()
    df["fwd_long_pnl_ticks"] = long_pnl
    df["fwd_short_pnl_ticks"] = short_pnl
    return df

def block_boot_pf(df, col, n_boot=500, block_days=3, seed=42, min_p=2):
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
        for idx in chosen: sd.extend(blocks[idx])
        sub = df[df["date"].isin(sd)]
        p = sub[col].dropna().to_numpy()
        if len(p) < min_p: continue
        gw = p[p > 0].sum(); gl = -p[p < 0].sum()
        if gl == 0:
            samples.append(10.0); continue
        samples.append(gw / gl)
    if not samples: return (np.nan, np.nan)
    return (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))

LEVELS_DICT = {
    "IB_LOW": ("dist_ib_low", 0.0005),
    "MQ_PUT_0DTE": ("dist_mq_put_0dte", 0.0005),
    "PVAL": ("dist_prev_val", 0.0005),
    "IB_HIGH": ("dist_ib_high", 0.0005),
    "MQ_CALL": ("dist_mq_call", 0.0005),
    "PVAH": ("dist_prev_vah", 0.0005),
    "SWING_HIGH": ("dist_swing_high", 0.0005),
    "CUR_VAH": ("dist_cur_vah", 0.0005),
    "CUR_VPOC_SHORT": ("dist_cur_vpoc", 0.0003),
    "CUR_VPOC_LONG": ("dist_cur_vpoc", 0.0003),
    "SWING_LOW": ("dist_swing_low", 0.0005),
}

if __name__ == "__main__":
    print("Loading data...")
    all_dfs = {}
    for sym in ["NQ", "ES"]:
        df = load_symbol(sym)
        for c in NEEDED_COLS:
            if c in df.columns and c != "session_id":
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
        df = compute_fwd(df, sym)
        all_dfs[sym] = df
        print("  " + sym + " loaded " + str(len(df)) + " bars")
    csv_path = ROOT / "DATA" / "AUDIT_CONFLUENCES_COLOR.csv"
    results = pd.read_csv(csv_path)
    def recompute_ci(row):
        sym = row["symbol"]
        level = row["level"]
        pattern = str(row["pattern"])
        direction = row["direction"]
        variant = row["variant"]
        df = all_dfs[sym]
        if level not in LEVELS_DICT:
            return (row.get("ci95_lo", np.nan), row.get("ci95_hi", np.nan))
        dist_col, prox = LEVELS_DICT[level]
        m_level = detect_contact(df, dist_col, prox)
        if variant == "BASELINE":
            mask = m_level
        else:
            pat_col = pattern.replace("+ext_close", "").strip()
            if pat_col == "NONE" or pat_col not in df.columns:
                return (row.get("ci95_lo", np.nan), row.get("ci95_hi", np.nan))
            m_pat = (pd.to_numeric(df[pat_col], errors="coerce") == 1)
            mask = m_level & m_pat
            if variant == "B_WITH_EXT":
                ext_col = "dist_ext_color_up" if direction == "LONG" else "dist_ext_color_dn"
                ext_cap = 50 if sym == "NQ" else 20
                if ext_col in df.columns:
                    ext_vals = pd.to_numeric(df[ext_col], errors="coerce")
                    m_ext = (ext_vals.abs() <= ext_cap) & ext_vals.notna()
                    mask = mask & m_ext
        col = "fwd_long_pnl_ticks" if direction == "LONG" else "fwd_short_pnl_ticks"
        sub = df[mask].copy()
        return block_boot_pf(sub, col, n_boot=500, block_days=3, min_p=2)
    print("Recomputing CI for", len(results), "rows...")
    new_ci = [recompute_ci(r) for _, r in results.iterrows()]
    results["ci95_lo_v2"] = [c[0] for c in new_ci]
    results["ci95_hi_v2"] = [c[1] for c in new_ci]
    results.to_csv(csv_path, index=False)
    print("done")
