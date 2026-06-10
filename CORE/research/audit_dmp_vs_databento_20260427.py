"""
Audit DMP vs Databento — 27/04/2026.

Approche :
1. Categoriser features DMP (268 colonnes)
2. Stats par feature : NaN%, constance, min/max/mean/p99, fire rate (binaires)
3. Comparaison 24/04 (PF 2.64 - jour qui marchait) vs 27/04
4. Recalculer primitives Databento (delta_bar, total_vol, big trades) depuis trades
5. Verdict : OK / SUSPECT / CASSE par feature
"""
from __future__ import annotations

import json
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


# ----- Categorisation features -----

CATEGORIES = {
    "OHLCV_PRIMITIVES": [
        "price", "bar_high", "bar_low", "total_vol", "buy_vol", "sell_vol",
    ],
    "DELTA_VOLUME_PROFILE": [
        "delta_bar", "delta_bar_vol_norm", "delta_day", "delta_day_dir",
        "ask_pct", "bid_pct", "ask_bid_imbalance",
        "buy_sell_ratio", "delta_pct", "ticks_count",
        "finish_delta_pct", "high_pullback_delta", "low_pullback_delta",
        "diag_pos_delta", "diag_neg_delta", "diag_imbalance",
        "low_bid_vol_pct", "high_ask_vol_pct",
        "avg_trade_size", "avg_bid_size", "avg_ask_size", "large_trader_ratio",
        "vol_per_sec", "bar_duration_sec",
        "cvd_bar_delta", "cvd_day", "cvd_day_dir", "cvd_ohlc_range",
        "rotation_up", "rotation_dn", "rotation_zz_osc",
        "delta_divergence",
    ],
    "VWAP_SD": [
        "dist_vwap_d", "dist_vwap_d_atr",
        "dist_vwap_d_sd1u", "dist_vwap_d_sd1d",
        "dist_vwap_d_sd2u", "dist_vwap_d_sd2d",
        "dist_vwap_d_sd3u", "dist_vwap_d_sd3d",
        "dist_vwap_w", "dist_vwap_w_atr",
        "dist_vwap_m", "dist_vwap_m_atr",
        "vwap_d_side", "vwap_w_side", "vwap_m_side",
        "vwap_slope_10", "vwap_slope_30", "vwap_slope_10_dir",
        "vwap_ma_align", "vwap_triple_align",
        "dist_prev_vwap", "dist_prev_vwap_sd1u", "dist_prev_vwap_sd1d",
    ],
    "IB": [
        "dist_ib_high", "dist_ib_low", "ib_range_ticks", "ib_range_atr",
        "ib_is_narrow", "ib_is_wide", "ib_position_pct",
        "ib_broken_up", "ib_broken_down", "ib_complete",
        "bool_ib_inside",
    ],
    "PROFILE_VPOC": [
        "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val", "dist_cur_vwap_vp",
        "va_position_pct", "inside_cur_va", "vah_touches_20b", "val_touches_20b",
        "bars_in_va", "poc_bar_dist",
        "dist_prev_vpoc", "dist_prev_vpoc_atr", "dist_prev_vah", "dist_prev_val",
        "inside_prev_va", "open_in_prev_va",
        "dist_comp_20d_vpoc", "dist_comp_20d_vpoc_atr", "dist_comp_20d_vah",
        "dist_comp_20d_val", "dist_comp_20d_vwap",
        "dist_comp_50d_vpoc", "dist_comp_50d_vpoc_atr", "dist_comp_50d_vah",
        "dist_comp_50d_val", "dist_comp_50d_vwap",
        "inside_comp_20d_va", "inside_comp_50d_va",
        "comp_vpoc_align_20_50", "comp_vpoc_align_day_20",
        "profile_shape", "profile_skew", "poc_position", "volume_imbalance",
        "is_double_dist", "poc_separation_ticks",
        "single_print_mid", "single_print_count", "profile_hvn_dominant",
    ],
    "MENTHORQ": [
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
        "dist_gex_nearest_up", "dist_gex_nearest_dn", "gex_cluster_count",
        "dist_blind_nearest_up", "dist_blind_nearest_dn",
        "next_wall_dist_ticks", "next_wall_is_call",
        "dist_1d_min_ticks", "dist_1d_max_ticks",
        "bool_above_mq_hvl", "bool_above_mq_call",
        "bool_gex_flip_zone",
    ],
    "VIX": [
        "vix_level", "dist_vix_hvl", "vix_regime", "vix_above_hvl",
        "dist_vix_call", "dist_vix_put",
        "dist_vix_call_0dte", "dist_vix_put_0dte",
        "dist_vix_hvl_0dte", "vix_above_hvl_0dte",
        "dist_vix_gex_nearest_up", "dist_vix_gex_nearest_dn",
    ],
    "BN_CRITICAL": [
        # PRIORITE
        "bn_color_up", "bn_color_dn", "bn_color_up_2", "bn_color_dn_2",
        "bn_absorb_ask", "bn_absorb_bid",
        "bn_long_up", "bn_long_dn",
        "bn_pressure_ask", "bn_pressure_bid",
        "bn_score_raw", "bn_score_bull", "bn_score_bear",
        "bn_volume_up", "bn_volume_dn",
        # bar_* extension lines (lecture etudes SC famille A)
        "bar_color_up", "bar_color_dn",
        "bar_long_up_bar", "bar_long_dn_bar",
        "bar_long_dn_up", "bar_long_up_dn",
        "bar_edge_buy", "bar_edge_sell",
        "bar_pressure_ask", "bar_pressure_bid",
        "dist_ext_color_up", "dist_ext_color_dn",
        "dist_ext_long_up", "dist_ext_long_dn",
        "dist_ext_edge_buy", "dist_ext_edge_sell",
        "fp_edge_buy", "fp_edge_sell",
    ],
    "BIG_ORDERS": [
        "dist_big_ask_nearest_up", "dist_big_ask_nearest_dn",
        "dist_big_bid_nearest_up", "dist_big_bid_nearest_dn",
        "n_big_ask_t1", "n_big_bid_t1",
        "n_big_ask_t2", "n_big_bid_t2",
        "n_big_ask_t3", "n_big_bid_t3",
        "n_big_ask_t4", "n_big_bid_t4",
        "big_ask_cluster_20t", "big_bid_cluster_20t",
        "big_ask_cluster_50t", "big_bid_cluster_50t",
        "big_ask_cluster_20t_t1", "big_bid_cluster_20t_t1",
        "big_ask_cluster_20t_t2", "big_bid_cluster_20t_t2",
        "big_ask_cluster_20t_t3", "big_bid_cluster_20t_t3",
        "big_ask_cluster_20t_t4", "big_bid_cluster_20t_t4",
        "dist_cluster_nearest_up", "dist_cluster_nearest_dn",
        "n_clusters_20t", "n_clusters_50t",
    ],
    "SWING": [
        "dist_swing_high", "dist_swing_low", "swing_range_ticks",
        "price_vs_swing_mid", "new_swing_high", "new_swing_low",
    ],
    "SESSION_OPEN": [
        "open_type", "open_zone", "open_bias_conf", "open_direction",
        "day_type", "rule_80pct", "trend_day_probability", "ma_trend",
        "dist_open_cash", "dist_open_830",
        "open_gap_ticks", "open_position",
        "session_id", "session", "bool_session_early",
        "dist_sess_high", "dist_sess_low", "sess_range_ticks", "sess_range_atr",
        "dist_ovn_high", "dist_ovn_low", "ovn_range_ticks",
    ],
    "BOOLS": [
        "bool_above_cur_vpoc", "bool_above_prev_vpoc",
        "bool_above_vwap_d", "bool_above_vwap_w", "bool_above_vwap_m",
        "bool_near_level", "bool_va_confluence",
    ],
    "HVN_LVN": [
        "dist_session_hvn_above", "dist_session_hvn_below",
        "dist_session_lvn_above", "dist_session_lvn_below",
        "session_hvn_count", "session_lvn_count",
        "lvn_between", "hvn_between", "lvn_confluence_count",
    ],
    "RETEST": [
        "retest_high_count", "retest_low_count",
        "retest_high_delta_div", "retest_low_delta_div",
        "bars_since_retest_high", "bars_since_retest_low",
    ],
    "RVOL": [
        "rvol", "rvol_zscore", "rvol_buy", "rvol_sell",
        "rvol_absorb_buy", "rvol_absorb_sell",
    ],
    "MISC": [
        "atr", "atr_14m", "range_pos", "range_size_ticks",
        "momentum_3b", "momentum_5b", "finish_strength",
    ],
}


def load_jsonl(path: Path) -> pd.DataFrame:
    """Charge un JSONL DMP en DataFrame."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    # ts JSONL est en epoch ms UTC
    df["ts_dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Filtre RTH 13:30-20:00 UTC (= 09:30-16:00 ET en DST avril)."""
    if df.empty or "ts_dt" not in df.columns:
        return df
    h = df["ts_dt"].dt.hour
    m = df["ts_dt"].dt.minute
    minutes = h * 60 + m
    mask = (minutes >= 13 * 60 + 30) & (minutes < 20 * 60)
    return df[mask].copy()


def feature_stats(s: pd.Series) -> dict:
    """Stats robustes pour une feature."""
    n = len(s)
    if n == 0:
        return {"n": 0}

    nan_pct = s.isna().sum() / n * 100
    s_clean = s.dropna()
    if len(s_clean) == 0:
        return {"n": n, "nan_pct": 100.0, "verdict": "ALL_NAN"}

    try:
        s_num = pd.to_numeric(s_clean, errors="coerce").dropna()
        is_numeric = len(s_num) >= len(s_clean) * 0.95
    except Exception:
        is_numeric = False

    if is_numeric and len(s_num) > 0:
        unique_n = int(s_num.nunique())
        std = float(s_num.std()) if not np.isnan(s_num.std()) else 0.0
        stats = {
            "n": n,
            "nan_pct": round(nan_pct, 2),
            "unique": unique_n,
            "min": round(float(s_num.min()), 4),
            "max": round(float(s_num.max()), 4),
            "mean": round(float(s_num.mean()), 4),
            "std": round(std, 4),
            "p99": round(float(s_num.quantile(0.99)), 4),
            "p1": round(float(s_num.quantile(0.01)), 4),
        }
        if unique_n <= 5:
            fires = int((s_num > 0).sum())
            stats["fires"] = fires
            stats["fire_rate_pct"] = round(fires / n * 100, 2)
        if unique_n == 1:
            stats["verdict"] = "CONSTANT"
        elif nan_pct > 50:
            stats["verdict"] = "HIGH_NAN"
        elif std == 0:
            stats["verdict"] = "ZERO_STD"
        else:
            stats["verdict"] = "OK"
        return stats
    else:
        unique_n = int(s_clean.nunique())
        return {
            "n": n,
            "nan_pct": round(nan_pct, 2),
            "unique": unique_n,
            "verdict": "CONSTANT" if unique_n == 1 else "OK",
            "sample": str(s_clean.iloc[0]) if len(s_clean) > 0 else None,
        }


def categorize_features(df: pd.DataFrame) -> dict:
    all_cols = set(df.columns) - {"ts", "ts_dt", "sym", "contract"}
    categorized = {cat: [c for c in cols if c in all_cols] for cat, cols in CATEGORIES.items()}
    flat = {c for cs in categorized.values() for c in cs}
    uncategorized = sorted(all_cols - flat)
    if uncategorized:
        categorized["UNCATEGORIZED"] = uncategorized
    return categorized


def audit_day(df: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    cats = categorize_features(df)
    for cat, cols in cats.items():
        for c in cols:
            stats = feature_stats(df[c])
            stats["feature"] = c
            stats["category"] = cat
            stats["day"] = label
            rows.append(stats)
    return pd.DataFrame(rows)


def load_databento_trades(symbol: str) -> pd.DataFrame:
    path = (
        ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades"
        / f"symbol={symbol}" / "year=2026" / "month=4" / "day=27"
        / "data.dbn.zst"
    )
    if not path.exists():
        return pd.DataFrame()
    store = db.DBNStore.from_file(str(path))
    df = store.to_df()
    return df


def recalc_databento_minute(trades: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    trades = trades.copy()

    # Index = ts_recv UTC. On utilise ts_event (timestamp matching engine).
    if trades.index.name == "ts_recv":
        trades = trades.reset_index()

    if "ts_event" not in trades.columns:
        return pd.DataFrame()

    trades["minute"] = pd.to_datetime(trades["ts_event"]).dt.floor("min")
    trades["size"] = trades["size"].astype(np.int64)

    # Convention Databento: side='B'=aggressive buy (lifted offer), 'A'=aggressive sell (hit bid)
    trades["buy_size"] = np.where(trades["side"] == "B", trades["size"], 0)
    trades["sell_size"] = np.where(trades["side"] == "A", trades["size"], 0)

    big_t1 = 100 if symbol == "ES.c.0" else 10
    big_t2 = 150 if symbol == "ES.c.0" else 30
    big_t3 = 400 if symbol == "ES.c.0" else 100

    grp = trades.groupby("minute").agg(
        total_vol=("size", "sum"),
        buy_vol=("buy_size", "sum"),
        sell_vol=("sell_size", "sum"),
        ticks_count=("size", "count"),
        big_t1=("size", lambda x: int((x >= big_t1).sum())),
        big_t2=("size", lambda x: int((x >= big_t2).sum())),
        big_t3=("size", lambda x: int((x >= big_t3).sum())),
        avg_trade_size=("size", "mean"),
        max_trade_size=("size", "max"),
    ).reset_index()
    grp["delta_bar"] = grp["buy_vol"] - grp["sell_vol"]
    grp["delta_pct"] = grp["delta_bar"] / grp["total_vol"].replace(0, np.nan)
    grp["ask_pct"] = grp["buy_vol"] / grp["total_vol"].replace(0, np.nan)
    return grp


def main():
    print("=" * 90)
    print(" AUDIT DMP vs DATABENTO — 27/04/2026")
    print("=" * 90)

    out_dir = ROOT / "CORE" / "research" / "out"
    out_dir.mkdir(exist_ok=True)

    print("\n[1] Chargement JSONL DMP")
    es_27 = load_jsonl(ROOT / "DATA" / "ES" / "20260427_ES.jsonl")
    nq_27 = load_jsonl(ROOT / "DATA" / "NQ" / "20260427_NQ.jsonl")
    es_24 = load_jsonl(ROOT / "DATA" / "ES" / "20260424_ES.jsonl")
    nq_24 = load_jsonl(ROOT / "DATA" / "NQ" / "20260424_NQ.jsonl")

    es_27_rth = filter_rth(es_27)
    nq_27_rth = filter_rth(nq_27)
    es_24_rth = filter_rth(es_24)
    nq_24_rth = filter_rth(nq_24)
    print(f"  ES 27/04 : {len(es_27)} bars total | {len(es_27_rth)} RTH (13:30-20:00 UTC)")
    print(f"  NQ 27/04 : {len(nq_27)} bars total | {len(nq_27_rth)} RTH")
    print(f"  ES 24/04 : {len(es_24)} bars total | {len(es_24_rth)} RTH")
    print(f"  NQ 24/04 : {len(nq_24)} bars total | {len(nq_24_rth)} RTH")

    # ----- Audit features (RTH) -----
    print("\n[2] Audit stats par feature (RTH only) - sauvegarde CSV")
    rep = []
    for label, df in [("ES_27", es_27_rth), ("NQ_27", nq_27_rth),
                      ("ES_24", es_24_rth), ("NQ_24", nq_24_rth)]:
        rep.append(audit_day(df, label))
    audit_df = pd.concat(rep, ignore_index=True)
    audit_df.to_csv(out_dir / "audit_features_20260427_rth.csv", index=False)

    # ----- Detect regressions -----
    print("\n[3] Detection regressions 24/04 -> 27/04")
    broken_es = []
    broken_nq = []
    for cat, cols in CATEGORIES.items():
        for c in cols:
            for sym, df27, df24, broken in [
                ("ES", es_27_rth, es_24_rth, broken_es),
                ("NQ", nq_27_rth, nq_24_rth, broken_nq),
            ]:
                if c not in df27.columns or c not in df24.columns:
                    continue
                s27 = pd.to_numeric(df27[c], errors="coerce")
                s24 = pd.to_numeric(df24[c], errors="coerce")
                if len(s27) == 0 or len(s24) == 0:
                    continue
                u27 = int(s27.dropna().nunique())
                u24 = int(s24.dropna().nunique())
                std27 = float(s27.std()) if not np.isnan(s27.std()) else 0
                std24 = float(s24.std()) if not np.isnan(s24.std()) else 0
                nan27 = s27.isna().sum() / len(s27) * 100
                nan24 = s24.isna().sum() / len(s24) * 100
                fires27 = int((s27.fillna(0) > 0).sum()) if u27 <= 5 else None
                fires24 = int((s24.fillna(0) > 0).sum()) if u24 <= 5 else None

                if u24 > 1 and u27 <= 1:
                    broken.append({
                        "feature": c, "category": cat, "issue": "BECAME_CONSTANT",
                        "uniq_24": u24, "uniq_27": u27,
                        "std_24": round(std24, 4), "std_27": round(std27, 4),
                    })
                elif nan27 > 50 and nan24 < 30:
                    broken.append({
                        "feature": c, "category": cat, "issue": "NAN_EXPLODED",
                        "nan_24_pct": round(nan24, 1), "nan_27_pct": round(nan27, 1),
                    })
                elif fires24 is not None and fires27 is not None and fires24 >= 5 and fires27 == 0:
                    broken.append({
                        "feature": c, "category": cat, "issue": "FIRES_DEAD",
                        "fires_24": fires24, "fires_27": fires27,
                    })

    print(f"  ES regressions : {len(broken_es)}")
    for b in broken_es:
        det = "  ".join(f"{k}={v}" for k, v in b.items() if k not in ("feature", "category", "issue"))
        print(f"    [{b['issue']:18s}] {b['category']:22s} {b['feature']:32s} {det}")
    print(f"\n  NQ regressions : {len(broken_nq)}")
    for b in broken_nq:
        det = "  ".join(f"{k}={v}" for k, v in b.items() if k not in ("feature", "category", "issue"))
        print(f"    [{b['issue']:18s}] {b['category']:22s} {b['feature']:32s} {det}")

    pd.DataFrame(broken_es).to_csv(out_dir / "broken_es_20260427.csv", index=False)
    pd.DataFrame(broken_nq).to_csv(out_dir / "broken_nq_20260427.csv", index=False)

    # ----- Focus BN_CRITICAL : fire rates 24 vs 27 -----
    print("\n[4] BN_CRITICAL — Fire rates 24/04 vs 27/04 (RTH 390 bars)")
    print(f"  {'Feature':32s} | {'ES_24':>7s} | {'ES_27':>7s} | {'NQ_24':>7s} | {'NQ_27':>7s}")
    print(f"  {'-'*32}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}")
    bn_summary = []
    for c in CATEGORIES["BN_CRITICAL"]:
        if c not in es_27_rth.columns:
            continue
        try:
            es24_s = pd.to_numeric(es_24_rth[c], errors="coerce").fillna(0)
            es27_s = pd.to_numeric(es_27_rth[c], errors="coerce").fillna(0)
            nq24_s = pd.to_numeric(nq_24_rth[c], errors="coerce").fillna(0)
            nq27_s = pd.to_numeric(nq_27_rth[c], errors="coerce").fillna(0)
        except Exception:
            continue
        all_uniq = int(pd.concat([es24_s, es27_s, nq24_s, nq27_s]).nunique())
        if all_uniq <= 5:
            es24f = int((es24_s > 0).sum())
            es27f = int((es27_s > 0).sum())
            nq24f = int((nq24_s > 0).sum())
            nq27f = int((nq27_s > 0).sum())
            flag = ""
            if (es24f >= 5 and es27f == 0) or (nq24f >= 5 and nq27f == 0):
                flag = " <-- DEAD ON 27/04"
            elif es24f == 0 and es27f == 0 and nq24f == 0 and nq27f == 0:
                flag = " <-- ALWAYS DEAD"
            print(f"  {c:32s} | {es24f:>7d} | {es27f:>7d} | {nq24f:>7d} | {nq27f:>7d}{flag}")
            bn_summary.append({"feature": c, "es_24": es24f, "es_27": es27f,
                               "nq_24": nq24f, "nq_27": nq27f, "type": "binary",
                               "flag": flag.strip()})
        else:
            es24m = float(es24_s.mean())
            es27m = float(es27_s.mean())
            nq24m = float(nq24_s.mean())
            nq27m = float(nq27_s.mean())
            es24sd = float(es24_s.std()) if not np.isnan(es24_s.std()) else 0
            es27sd = float(es27_s.std()) if not np.isnan(es27_s.std()) else 0
            nq24sd = float(nq24_s.std()) if not np.isnan(nq24_s.std()) else 0
            nq27sd = float(nq27_s.std()) if not np.isnan(nq27_s.std()) else 0
            flag = ""
            if es24sd > 0.001 and es27sd < 0.0001:
                flag = " <-- ES STD COLLAPSE"
            if nq24sd > 0.001 and nq27sd < 0.0001:
                flag += " <-- NQ STD COLLAPSE"
            print(f"  {c:32s} | E24:{es24m:7.2f}/sd{es24sd:5.2f} | E27:{es27m:7.2f}/sd{es27sd:5.2f}"
                  f" | N24:{nq24m:7.2f}/sd{nq24sd:5.2f} | N27:{nq27m:7.2f}/sd{nq27sd:5.2f}{flag}")
            bn_summary.append({"feature": c, "es_24_mean": es24m, "es_27_mean": es27m,
                               "nq_24_mean": nq24m, "nq_27_mean": nq27m,
                               "es_24_std": es24sd, "es_27_std": es27sd,
                               "nq_24_std": nq24sd, "nq_27_std": nq27sd,
                               "type": "numeric", "flag": flag.strip()})
    pd.DataFrame(bn_summary).to_csv(out_dir / "bn_summary_20260427.csv", index=False)

    # ----- Recalc Databento primitives -----
    print("\n[5] Recalcul primitives Databento (trades) — comparaison vs DMP RTH")
    db_compare = []
    for symbol in ["ES.c.0", "NQ.c.0"]:
        sym_short = "ES" if symbol.startswith("ES") else "NQ"
        print(f"\n  ----- {symbol} -----")
        try:
            trades = load_databento_trades(symbol)
            print(f"    Trades lus : {len(trades):,}")
            if trades.empty:
                continue
            db_min = recalc_databento_minute(trades, symbol)

            # Filter RTH (UTC)
            db_min["minute"] = pd.to_datetime(db_min["minute"])
            if db_min["minute"].dt.tz is not None:
                db_min["minute"] = db_min["minute"].dt.tz_convert("UTC").dt.tz_localize(None)
            mask_rth = ((db_min["minute"].dt.hour > 13) |
                        ((db_min["minute"].dt.hour == 13) & (db_min["minute"].dt.minute >= 30)))
            mask_rth &= db_min["minute"].dt.hour < 20
            db_rth = db_min[mask_rth].copy()
            print(f"    Databento RTH minutes : {len(db_rth)}")

            df_dmp = es_27_rth if sym_short == "ES" else nq_27_rth

            # Stats globales
            db_total = int(db_rth["total_vol"].sum())
            db_buy = int(db_rth["buy_vol"].sum())
            db_sell = int(db_rth["sell_vol"].sum())
            db_delta = int(db_rth["delta_bar"].sum())
            db_big1 = int(db_rth["big_t1"].sum())
            db_big2 = int(db_rth["big_t2"].sum())
            db_big3 = int(db_rth["big_t3"].sum())
            dmp_total = int(df_dmp["total_vol"].sum())
            dmp_buy = int(df_dmp["buy_vol"].sum())
            dmp_sell = int(df_dmp["sell_vol"].sum())
            dmp_delta = int(df_dmp["delta_bar"].sum())

            print(f"    {'Metric':22s} | {'DMP RTH':>14s} | {'Databento RTH':>14s} | Ratio")
            for met, dmp_v, db_v in [
                ("total_vol", dmp_total, db_total),
                ("buy_vol", dmp_buy, db_buy),
                ("sell_vol", dmp_sell, db_sell),
                ("delta_bar (sum)", dmp_delta, db_delta),
            ]:
                r = dmp_v / db_v if db_v else float("inf")
                print(f"    {met:22s} | {dmp_v:>14,} | {db_v:>14,} | {r:.3f}")
            print(f"    Big trades t1 (DMP n_big_*_t1 sum): "
                  f"ask={int(df_dmp['n_big_ask_t1'].sum())} bid={int(df_dmp['n_big_bid_t1'].sum())}"
                  f" | DB={db_big1}")
            print(f"    Big trades t2 (DMP n_big_*_t2 sum): "
                  f"ask={int(df_dmp['n_big_ask_t2'].sum())} bid={int(df_dmp['n_big_bid_t2'].sum())}"
                  f" | DB={db_big2}")
            print(f"    Big trades t3 (DMP n_big_*_t3 sum): "
                  f"ask={int(df_dmp['n_big_ask_t3'].sum())} bid={int(df_dmp['n_big_bid_t3'].sum())}"
                  f" | DB={db_big3}")

            # Per-minute correlation
            df_dmp_idx = df_dmp.set_index(df_dmp["ts_dt"].dt.floor("min").dt.tz_convert("UTC").dt.tz_localize(None))
            db_rth_idx = db_rth.set_index("minute")
            common = df_dmp_idx.index.intersection(db_rth_idx.index)
            if len(common) > 30:
                vol_corr = df_dmp_idx.loc[common, "total_vol"].corr(db_rth_idx.loc[common, "total_vol"])
                delta_corr = df_dmp_idx.loc[common, "delta_bar"].corr(db_rth_idx.loc[common, "delta_bar"])
                print(f"    Correlation per-minute (n={len(common)}):")
                print(f"      total_vol corr  : {vol_corr:.4f}  (1.0 = parfait)")
                print(f"      delta_bar corr  : {delta_corr:.4f}")
                db_compare.append({"symbol": sym_short,
                                   "vol_corr": vol_corr, "delta_corr": delta_corr,
                                   "dmp_total": dmp_total, "db_total": db_total,
                                   "ratio_total": dmp_total / db_total if db_total else 0})

            db_min.to_parquet(out_dir / f"databento_recalc_{sym_short}_20260427.parquet")
        except Exception as e:
            import traceback
            print(f"    ERREUR : {e}")
            traceback.print_exc()

    pd.DataFrame(db_compare).to_csv(out_dir / "db_dmp_compare_20260427.csv", index=False)

    # ----- Suspect features -----
    print("\n[6] Features SUSPECTES sur 27/04 (constantes ou >80% NaN sur RTH)")
    suspect = []
    for label, df, df24 in [("ES_27", es_27_rth, es_24_rth),
                              ("NQ_27", nq_27_rth, nq_24_rth)]:
        for c in df.columns:
            if c in ("ts", "ts_dt", "sym", "contract"):
                continue
            s = pd.to_numeric(df[c], errors="coerce")
            if len(s) == 0:
                continue
            nan_pct = s.isna().sum() / len(s) * 100
            uniq = int(s.dropna().nunique())
            std = float(s.std()) if not np.isnan(s.std()) else 0
            if uniq <= 1 or nan_pct > 80:
                s24 = pd.to_numeric(df24[c], errors="coerce") if c in df24.columns else None
                u24 = int(s24.dropna().nunique()) if s24 is not None else 0
                suspect.append({
                    "day": label, "feature": c,
                    "nan_pct": round(nan_pct, 1),
                    "uniq_27": uniq, "uniq_24": u24,
                    "std_27": round(std, 4),
                    "regression": u24 > 1 and uniq <= 1,
                })

    sus_df = pd.DataFrame(suspect)
    sus_df.to_csv(out_dir / "suspect_features_20260427.csv", index=False)
    print(f"  Total suspectes : {len(sus_df)}")
    if not sus_df.empty:
        regr = sus_df[sus_df["regression"]]
        print(f"  Regressions reelles (24 ok -> 27 cassee) : {len(regr)}")
        if not regr.empty:
            print(regr[["day", "feature", "uniq_24", "uniq_27", "nan_pct"]].to_string(index=False))
        # Top constantes communes ES+NQ
        print("\n  Top 30 features constantes (ES_27):")
        es_const = sus_df[(sus_df["day"] == "ES_27") & (sus_df["uniq_27"] <= 1)]
        print(es_const[["feature", "nan_pct", "uniq_24"]].head(30).to_string(index=False))

    print(f"\n[OK] Outputs : {out_dir}")


if __name__ == "__main__":
    main()
