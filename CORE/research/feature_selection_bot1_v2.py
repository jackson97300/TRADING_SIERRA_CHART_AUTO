
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path("d:/TRADING_SIERRA_CHART_AUTO")
TRADES_DIR = ROOT / "DATA" / "PAPER_TRADES"
ENR_NQ = ROOT / "DATA" / "live_enriched" / "NQ"
ENR_ES = ROOT / "DATA" / "live_enriched" / "ES"

CANDIDATE_FEATURES = [
    "cvd_day", "cvd_session", "aggressor_imbalance", "delta_day",
    "delta_pct", "delta_bar", "delta_div_strength",
    "vwap_slope_10", "vwap_slope_10_atr", "vwap_m_side", "vwap_w_side", "vwap_d_side",
    "momentum_5b",
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    "dist_mq_call_0dte_pct", "dist_mq_put_0dte_pct",
    "dist_vwap_d_pct", "dist_cur_vah_pct", "dist_cur_val_pct", "dist_cur_vpoc_pct",
    "dist_pdh_pct", "dist_pdl_pct",
    "dist_1d_max_ticks_pct", "dist_1d_min_ticks_pct",
    "is_in_us_cash", "mins_et", "atr_14m_pct", "ctx_day_type_intensity",
    "open_type", "open_zone", "open_bias_conf",
    "ctx_mq_put_call_ratio",
    "long_up_bar", "long_dn_bar",
    "regime_confidence", "regime_vol",
    "atr_regime_zscore_60d", "ctx_rvol_session",
    "delta_divergence_clean", "div_confluence_with_regime",
    "ib_position_pct", "range_pos", "va_position_pct",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
]


def load_trades():
    trades = []
    files = sorted(TRADES_DIR.glob("*_trades.jsonl"))
    files = [f for f in files if "_databento" not in f.name and "_v3" not in f.name and "_v6" not in f.name]
    for f in files:
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except Exception:
                    pass
    return trades


def load_enriched_index(symbol, dates_needed):
    base = ENR_NQ if symbol == "NQ" else ENR_ES
    out = {}
    for d in dates_needed:
        fname = base / f"{d}_{symbol}.jsonl"
        if not fname.exists():
            out[d] = []
            continue
        bars = []
        with open(fname, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    b = json.loads(line)
                    ts_ns = b.get("ts_event_ns") or b.get("ts_event") or b.get("ts")
                    if ts_ns is None:
                        continue
                    bars.append((int(ts_ns), b))
                except Exception:
                    pass
        bars.sort(key=lambda x: x[0])
        out[d] = bars
    return out


def nearest_bar(bars, entry_ts_ns):
    if not bars:
        return None
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid][0] <= entry_ts_ns:
            lo = mid + 1
        else:
            hi = mid
    idx = lo - 1
    if idx < 0:
        return None
    ts, bar = bars[idx]
    diff_s = (entry_ts_ns - ts) / 1e9
    if diff_s > 120 or diff_s < -2:
        return None
    return bar


def bootstrap_ci(x, y, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(x)
    rhos = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        xi = x[idx]
        yi = y[idx]
        if np.std(xi) == 0 or np.std(yi) == 0:
            continue
        r, _ = stats.spearmanr(xi, yi)
        if not math.isnan(r):
            rhos.append(r)
    if not rhos:
        return float("nan"), float("nan")
    return float(np.percentile(rhos, 2.5)), float(np.percentile(rhos, 97.5))


def main():
    print("=" * 80)
    print("FEATURE SELECTION - Bot 1 SIM1 - bias_calculator V2")
    print("=" * 80)

    trades = load_trades()
    print(f"\n[1] Trades total : {len(trades)}")
    closed = [t for t in trades if t.get("pnl_usd") is not None and t.get("exit_reason")]
    print(f"    Trades closed : {len(closed)}")

    dates_nq = set()
    dates_es = set()
    for t in closed:
        sym = t.get("symbol")
        et = t.get("entry_time", "")
        if not et or len(et) < 10:
            continue
        d = et[:10].replace("-", "")
        if sym == "NQ":
            dates_nq.add(d)
        elif sym == "ES":
            dates_es.add(d)
    print(f"    Dates NQ : {len(dates_nq)} | ES : {len(dates_es)}")

    print("\n[2] Chargement live_enriched...")
    bars_nq = load_enriched_index("NQ", dates_nq)
    bars_es = load_enriched_index("ES", dates_es)

    print("\n[3] Jointure trades x features...")
    rows = []
    matched = 0
    unmatched = 0
    for t in closed:
        sym = t.get("symbol")
        et = t.get("entry_time", "")
        entry_ts = t.get("entry_ts")
        if entry_ts is None or not sym:
            continue
        d = et[:10].replace("-", "")
        entry_ts_ns = int(float(entry_ts) * 1e9)
        bars = bars_nq.get(d, []) if sym == "NQ" else bars_es.get(d, [])
        bar = nearest_bar(bars, entry_ts_ns)
        if bar is None:
            unmatched += 1
            continue
        matched += 1
        row = {
            "trade_id": t.get("trade_id"),
            "date": d,
            "symbol": sym,
            "direction": t.get("direction"),
            "pnl_usd": float(t.get("pnl_usd", 0)),
            "pnl_ticks": float(t.get("pnl_ticks", 0)),
            "outcome": t.get("outcome"),
            "is_win": 1 if float(t.get("pnl_usd", 0)) > 0 else 0,
            "entry_ts_ns": entry_ts_ns,
        }
        bias_factors = t.get("bias_factors", [])
        bull_pts = 0
        bear_pts = 0
        for bf in bias_factors:
            if isinstance(bf, dict):
                pts = bf.get("points", 0) or 0
                icon = bf.get("icon", "")
                if "bull" in str(icon).lower():
                    bull_pts += pts
                elif "bear" in str(icon).lower():
                    bear_pts += pts
        row["conseil_bull_pts"] = bull_pts
        row["conseil_bear_pts"] = bear_pts
        for f in CANDIDATE_FEATURES:
            v = bar.get(f)
            try:
                row[f] = float(v) if v is not None else float("nan")
            except Exception:
                row[f] = float("nan")
        rows.append(row)

    print(f"    Matched : {matched} | Unmatched : {unmatched}")
    df = pd.DataFrame(rows)
    print(f"    Shape : {df.shape}")
    if df.empty:
        return

    df = df.sort_values("entry_ts_ns").reset_index(drop=True)
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")

    print("\n    Repartition par symbole/direction :")
    rep = df.groupby(["symbol", "direction"]).agg(
        n=("pnl_usd", "size"),
        pnl_sum=("pnl_usd", "sum"),
        wr=("is_win", "mean"),
    )
    print(rep.to_string())

    out_dir = ROOT / "CORE" / "research" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "bot1_trades_x_features.parquet")
    print(f"\n    Saved: {out_dir / 'bot1_trades_x_features.parquet'}")


if __name__ == "__main__":
    main()
