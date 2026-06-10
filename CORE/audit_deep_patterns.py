"""Audit DEEP — patterns invisibles a l'oeil nu.

Jackson : "patterns invisibles, plus profond plus general".

6 sections d'investigation orthogonales :
1. SEQUENCES TEMPORELLES : X[t-1] AND Y[t] vs X[t] AND Y[t] (markov order 2)
2. CONDITIONAL TREE : pour top clusters, split par contexte (day_type, time, dist_mq)
3. CONTINUOUS EDGES : non-linearites sur dist_*_pct via 10 quantiles, sweet spots
4. TIME PATTERNS : edge par heure UTC, jour semaine, minutes_since_open
5. ANTI-PATTERNS : combos qui RUINENT l'edge (filtres no-trade)
6. CROSS-INSTRUMENT LAG : ES leads NQ par k bars ?

Anti-Pattern 11 V1 : ne JAMAIS hardcode comme gate, juste documenter edge.
Lopez-aware : sample size + Sharpe + multiple testing flag.
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TICK_SIZE = 0.25

# ====================================================================
# Top features (depuis audit precedent — exclu _fwd1 leakage)
# ====================================================================
TOP_BOOL_FEATURES = [
    # BN raw
    "bn_absorb_ask_raw", "bn_absorb_bid_raw",
    "bn_stack_ask", "bn_stack_bid",
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
    # BN at_level (subset informatif)
    "bn_absorb_ask_at_level",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    # Trapped Phase B+++
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
    # Microstructure
    "rvol_absorb_buy", "rvol_absorb_sell",
    "n_big_t1", "n_big_buy_t1", "n_big_sell_t1",
    "n_big_ask_v2_t1", "n_big_bid_v2_t1",
    # Contexte bool
    "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
]

TOP_CONT_FEATURES = [
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    "dist_gex_nearest_up_pct", "dist_gex_nearest_dn_pct",
    "dist_blind_nearest_up_pct", "dist_blind_nearest_dn_pct",
    "dist_1d_min_ticks_pct", "dist_1d_max_ticks_pct",
    "aggressor_imbalance",
    "atr_14m_pct", "vwap_offset_pct",
    "cvd_5d_rolling_ffd",
    "im_cross_delta_agreement_5", "im_smt_divergence",
]

CONTEXT_BOOL = [
    "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
    "is_rth",
]


# ====================================================================
# Helpers
# ====================================================================
def fwd_return(df, horizon=5):
    """Forward return en TICKS."""
    return (df["close"].shift(-horizon) - df["close"]) / TICK_SIZE


def edge_metrics(fwd: pd.Series, mask: pd.Series, base_winrate: float):
    """Calcule metrics edge pour mask."""
    cond_fwd = fwd[mask & fwd.notna()]
    if len(cond_fwd) < 5:
        return None
    return {
        "n": int(len(cond_fwd)),
        "wr": float((cond_fwd > 0).mean()),
        "mean_t": float(cond_fwd.mean()),
        "sharpe": float(cond_fwd.mean() / cond_fwd.std()) if cond_fwd.std() > 0 else 0.0,
        "vs_base_wr": float((cond_fwd > 0).mean() - base_winrate),
    }


def binarize(df, feature, threshold=0.0, op="gt"):
    """Binarise feature continu."""
    if feature not in df.columns:
        return None
    if op == "gt":
        return (df[feature] > threshold).astype(int)
    elif op == "lt":
        return (df[feature] < threshold).astype(int)
    elif op == "abs_lt":
        return (df[feature].abs() < threshold).astype(int)


def get_active_bool_features(df, cols):
    """Retourne features bool actives (>=30 fires)."""
    out = {}
    for c in cols:
        if c not in df.columns:
            continue
        s = (df[c] != 0).astype(int)
        if s.sum() >= 30:
            out[c] = s
    # Helpers binarises
    if "aggressor_imbalance" in df.columns:
        for thr, name in [(0.3, "agg_strong_buy"), (-0.3, "agg_strong_sell")]:
            s = (df["aggressor_imbalance"] >= thr).astype(int) if thr > 0 else (df["aggressor_imbalance"] <= thr).astype(int)
            if s.sum() >= 30:
                out[name] = s
    return out


# ====================================================================
# Section 1 : SEQUENCES TEMPORELLES (markov order 2)
# ====================================================================
def audit_sequences(df, fwd, base_wr, features, max_pairs=50):
    """Pour chaque pair (X, Y) : compare X[t-1] AND Y[t] vs X[t] AND Y[t].

    Si la version sequentielle a edge supplementaire >= 3pp, c'est un PATTERN
    SEQUENTIEL.
    """
    print(f"\n[1] SEQUENCES TEMPORELLES (X[t-1] AND Y[t] vs simultane)")
    rows = []
    keys = list(features.keys())
    n_tested = 0
    for x, y in combinations(keys, 2):
        sx, sy = features[x], features[y]
        # Simultane
        cond_sim = (sx & sy).astype(bool)
        if cond_sim.sum() < 30:
            continue
        # Sequentiel : x[t-1] AND y[t]
        cond_seq = (sx.shift(1).fillna(0).astype(int) & sy).astype(bool)
        if cond_seq.sum() < 30:
            continue
        m_sim = edge_metrics(fwd, cond_sim, base_wr)
        m_seq = edge_metrics(fwd, cond_seq, base_wr)
        if not m_sim or not m_seq:
            continue
        diff = m_seq["vs_base_wr"] - m_sim["vs_base_wr"]
        if abs(diff) < 0.03:
            continue
        rows.append({
            "X_then_Y": f"{x} -> {y}",
            "n_sim": m_sim["n"], "n_seq": m_seq["n"],
            "sim_wr": round(m_sim["wr"], 3),
            "seq_wr": round(m_seq["wr"], 3),
            "seq_minus_sim_pp": round(diff, 3),
            "seq_sharpe": round(m_seq["sharpe"], 2),
        })
        n_tested += 1
        if n_tested > max_pairs * 5:
            break
    if not rows:
        print("  Aucun pattern sequentiel significatif")
        return pd.DataFrame()
    df_r = pd.DataFrame(rows).sort_values("seq_minus_sim_pp", key=lambda s: s.abs(), ascending=False)
    print(df_r.head(15).to_string(index=False))
    return df_r


# ====================================================================
# Section 2 : CONDITIONAL DECISION TREE
# ====================================================================
def audit_conditional_tree(df, fwd, base_wr, top_clusters, features):
    """Pour chaque top cluster, split par contexte. Trouve {cluster, ctx}
    qui maximise edge OU qui inverse edge."""
    print(f"\n[2] CONDITIONAL TREE (split top clusters par contexte)")

    rows = []
    contexts = {
        "RTH": (df["is_rth"] == 1) if "is_rth" in df.columns else None,
        "OFF": (df["is_rth"] == 0) if "is_rth" in df.columns else None,
    }
    if "day_type" in df.columns:
        for dt_val in [0, 1, 2, 3]:
            mask = df["day_type"] == dt_val
            if mask.sum() >= 1000:
                contexts[f"dt={dt_val}"] = mask
    if "open_type" in df.columns:
        for ot_val in [0, 1, 2, 3]:
            mask = df["open_type"] == ot_val
            if mask.sum() >= 1000:
                contexts[f"ot={ot_val}"] = mask
    # Heure UTC bucket
    ts = pd.to_datetime(df["ts_event"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    hour = ts.dt.hour
    contexts["asia_22_06"] = (hour >= 22) | (hour < 6)
    contexts["london_07_12"] = (hour >= 7) & (hour < 13)
    contexts["us_open_13_15"] = (hour >= 13) & (hour < 15)
    contexts["us_lunch_16_18"] = (hour >= 16) & (hour < 18)
    contexts["us_close_19_21"] = (hour >= 19) & (hour < 22)
    # MQ position
    if "dist_mq_hvl_pct" in df.columns:
        contexts["far_from_mq_hvl"] = df["dist_mq_hvl_pct"].abs() > 1.0
        contexts["near_mq_hvl"] = df["dist_mq_hvl_pct"].abs() <= 0.3
    # Volatility regime via atr
    if "atr_14m_pct" in df.columns:
        atr = df["atr_14m_pct"]
        atr_med = atr.median()
        contexts["high_vol"] = atr > atr_med * 1.5
        contexts["low_vol"] = atr < atr_med * 0.5

    for cluster_str in top_clusters:
        keys = cluster_str.split(" + ")
        cond = pd.Series(True, index=df.index)
        for k in keys:
            if k not in features:
                cond = pd.Series(False, index=df.index)
                break
            cond = cond & features[k].astype(bool)

        # Global baseline
        m_glob = edge_metrics(fwd, cond, base_wr)
        if not m_glob or m_glob["n"] < 30:
            continue

        # Pour chaque contexte
        for ctx_name, ctx_mask in contexts.items():
            if ctx_mask is None:
                continue
            cond_ctx = cond & ctx_mask
            m_ctx = edge_metrics(fwd, cond_ctx, base_wr)
            if not m_ctx or m_ctx["n"] < 20:
                continue
            edge_diff = m_ctx["vs_base_wr"] - m_glob["vs_base_wr"]
            if abs(edge_diff) < 0.05:
                continue
            rows.append({
                "cluster": cluster_str[:60],
                "context": ctx_name,
                "n_global": m_glob["n"], "n_ctx": m_ctx["n"],
                "wr_global": round(m_glob["wr"], 3),
                "wr_ctx": round(m_ctx["wr"], 3),
                "edge_amplification": round(edge_diff, 3),
                "ctx_sharpe": round(m_ctx["sharpe"], 2),
            })
    if not rows:
        print("  Aucune amplification contexte significative")
        return pd.DataFrame()
    df_r = pd.DataFrame(rows).sort_values(
        "edge_amplification", key=lambda s: s.abs(), ascending=False)
    print(f"\n  Top 15 amplifications/inversions par contexte:")
    print(df_r.head(15).to_string(index=False))
    return df_r


# ====================================================================
# Section 3 : CONTINUOUS EDGES (sweet spots non-lineaires)
# ====================================================================
def audit_continuous_edges(df, fwd, base_wr):
    """Pour chaque feature continu, bin en 10 quantiles + edge par bin.
    Identifie sweet spots (wr >> base) et dead zones."""
    print(f"\n[3] CONTINUOUS EDGES (10 quantiles par feature)")
    rows = []
    for feat in TOP_CONT_FEATURES:
        if feat not in df.columns:
            continue
        s = df[feat].dropna()
        if len(s) < 1000:
            continue
        try:
            quantiles = pd.qcut(s, q=10, duplicates="drop", labels=False)
        except ValueError:
            continue
        # Reconstruit aligne avec df
        quantiles_full = pd.Series(np.nan, index=df.index)
        quantiles_full.loc[s.index] = quantiles.values

        for q in range(10):
            mask = (quantiles_full == q)
            n = int(mask.sum())
            if n < 100:
                continue
            cond_fwd = fwd[mask & fwd.notna()]
            if len(cond_fwd) < 50:
                continue
            wr = float((cond_fwd > 0).mean())
            edge = wr - base_wr
            if abs(edge) < 0.03:
                continue
            # Bornes du bin
            bin_min = float(s[quantiles == q].min())
            bin_max = float(s[quantiles == q].max())
            rows.append({
                "feature": feat,
                "quantile": q,
                "bin_range": f"[{bin_min:.2f}, {bin_max:.2f}]",
                "n": n,
                "wr": round(wr, 3),
                "edge_vs_base": round(edge, 3),
                "mean_t": round(float(cond_fwd.mean()), 1),
            })
    if not rows:
        print("  Aucun sweet spot continu")
        return pd.DataFrame()
    df_r = pd.DataFrame(rows).sort_values(
        "edge_vs_base", key=lambda s: s.abs(), ascending=False)
    print(df_r.head(20).to_string(index=False))
    return df_r


# ====================================================================
# Section 4 : TIME PATTERNS (heure / jour semaine / session phase)
# ====================================================================
def audit_time_patterns(df, fwd, base_wr):
    """Edge global par heure UTC + jour semaine."""
    print(f"\n[4] TIME PATTERNS")
    ts = pd.to_datetime(df["ts_event"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    df_t = pd.DataFrame({
        "hour": ts.dt.hour,
        "dow": ts.dt.dayofweek,  # 0=Monday
        "fwd": fwd,
    })

    # Edge par heure
    print(f"\n  -- EDGE PAR HEURE UTC (n>=500) --")
    rows_h = []
    for h in range(24):
        sub = df_t[df_t["hour"] == h]
        valid = sub["fwd"].dropna()
        if len(valid) < 500:
            continue
        wr = float((valid > 0).mean())
        edge = wr - base_wr
        rows_h.append({
            "hour_utc": h,
            "n": len(valid),
            "wr": round(wr, 3),
            "edge": round(edge, 3),
            "mean_t": round(float(valid.mean()), 2),
        })
    df_h = pd.DataFrame(rows_h).sort_values("edge", key=lambda s: s.abs(), ascending=False)
    print(df_h.head(10).to_string(index=False))

    # Edge par jour semaine
    print(f"\n  -- EDGE PAR JOUR SEMAINE --")
    dow_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    rows_d = []
    for d in range(7):
        sub = df_t[df_t["dow"] == d]
        valid = sub["fwd"].dropna()
        if len(valid) < 500:
            continue
        wr = float((valid > 0).mean())
        rows_d.append({
            "day": dow_names[d],
            "n": len(valid),
            "wr": round(wr, 3),
            "edge": round(wr - base_wr, 3),
        })
    df_d = pd.DataFrame(rows_d)
    print(df_d.to_string(index=False))

    return {"hour": df_h, "dow": df_d}


# ====================================================================
# Section 5 : ANTI-PATTERNS (no-trade filters)
# ====================================================================
def audit_anti_patterns(df, fwd, base_wr, features, top_clusters):
    """Pour top clusters, trouver modificateurs qui INVERSENT l'edge."""
    print(f"\n[5] ANTI-PATTERNS (filtres no-trade)")
    rows = []
    for cluster_str in top_clusters:
        keys = cluster_str.split(" + ")
        cond = pd.Series(True, index=df.index)
        for k in keys:
            if k not in features:
                cond = pd.Series(False, index=df.index)
                break
            cond = cond & features[k].astype(bool)

        m_glob = edge_metrics(fwd, cond, base_wr)
        if not m_glob or m_glob["n"] < 30:
            continue

        # Test chaque feature comme MODIFIER (AND ou NOT)
        for mod_key, mod_s in features.items():
            if mod_key in keys:
                continue
            # AND modifier
            cond_and = cond & mod_s.astype(bool)
            m_and = edge_metrics(fwd, cond_and, base_wr)
            if m_and and m_and["n"] >= 20:
                edge_diff = m_and["vs_base_wr"] - m_glob["vs_base_wr"]
                if edge_diff < -0.10:  # MODIFIER ruine edge
                    rows.append({
                        "base_cluster": cluster_str[:50],
                        "modifier_AND": mod_key,
                        "n_base": m_glob["n"], "n_with_mod": m_and["n"],
                        "wr_base": round(m_glob["wr"], 3),
                        "wr_with_mod": round(m_and["wr"], 3),
                        "edge_lost": round(edge_diff, 3),
                    })
    if not rows:
        print("  Aucun anti-pattern significatif")
        return pd.DataFrame()
    df_r = pd.DataFrame(rows).sort_values("edge_lost").head(15)
    print(df_r.to_string(index=False))
    return df_r


# ====================================================================
# Section 6 : CROSS-INSTRUMENT LAG (ES -> NQ ?)
# ====================================================================
def audit_cross_instrument_lag(df_es, df_nq, features_es, features_nq):
    """Pattern X sur ES bar t -> edge fwd5 sur NQ bar t+k ?"""
    print(f"\n[6] CROSS-INSTRUMENT LAG (ES leads NQ ?)")

    # Aligne ES et NQ sur ts_event commun
    es = df_es.set_index("ts_event")[["close"]].rename(columns={"close": "close_es"})
    nq = df_nq.set_index("ts_event")[["close"]].rename(columns={"close": "close_nq"})
    common_ts = es.index.intersection(nq.index)
    if len(common_ts) < 10000:
        print("  Pas assez de timestamps communs")
        return pd.DataFrame()

    # Forward NQ
    nq_aligned = nq.loc[common_ts].sort_index()
    fwd_nq = (nq_aligned["close_nq"].shift(-5) - nq_aligned["close_nq"]) / TICK_SIZE
    base_wr_nq = float((fwd_nq.dropna() > 0).mean())

    # Pour chaque feature ES, mesure edge fwd_NQ
    rows = []
    es_aligned = df_es.set_index("ts_event").sort_index().loc[
        df_es.set_index("ts_event").index.intersection(common_ts)
    ]
    for feat_name, feat_s in features_es.items():
        # Reindex feature ES sur common_ts
        feat_full = pd.Series(feat_s.values, index=df_es["ts_event"].values)
        if not feat_full.index.is_unique:
            feat_full = feat_full[~feat_full.index.duplicated(keep="last")]
        feat_aligned = feat_full.reindex(common_ts).fillna(0).astype(int)
        if feat_aligned.sum() < 50:
            continue

        for lag in [0, 1, 2, 3]:
            cond = feat_aligned.shift(lag).fillna(0).astype(int).astype(bool)
            cond_fwd = fwd_nq[cond & fwd_nq.notna()]
            if len(cond_fwd) < 50:
                continue
            wr = float((cond_fwd > 0).mean())
            edge = wr - base_wr_nq
            if abs(edge) < 0.05:
                continue
            rows.append({
                "es_feature": feat_name,
                "lag_bars": lag,
                "n": len(cond_fwd),
                "nq_fwd5_wr": round(wr, 3),
                "nq_edge": round(edge, 3),
                "nq_mean_t": round(float(cond_fwd.mean()), 1),
            })
    if not rows:
        print("  Aucun cross-instrument lag pattern")
        return pd.DataFrame()
    df_r = pd.DataFrame(rows).sort_values("nq_edge", key=lambda s: s.abs(), ascending=False)
    print(df_r.head(15).to_string(index=False))
    return df_r


# ====================================================================
# MAIN
# ====================================================================
def run_deep_audit(symbol: str = "ES"):
    print(f"\n{'='*82}")
    print(f"  DEEP PATTERNS AUDIT — {symbol} — ULTRATHINK")
    print(f"{'='*82}")

    parq = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5e.parquet"
    if not parq.exists():
        print(f"MISSING {parq}")
        return None
    df = pd.read_parquet(parq)
    print(f"\nDataset: {parq.name}  shape={df.shape}")

    # Forward return + base winrate
    fwd = fwd_return(df, horizon=5)
    base_wr = float((fwd.dropna() > 0).mean())
    print(f"  base_wr fwd5 = {base_wr:.4f}")

    # Features actives
    features = get_active_bool_features(df, TOP_BOOL_FEATURES)
    print(f"  Features bool actives: {len(features)}")

    # Top clusters depuis audit precedent (manuel, top 5)
    if symbol == "ES":
        top_clusters = [
            "aggressor_strong_buy + bn_absorb_ask_at_level + bn_absorb_ask_raw",  # placeholder
            "bn_trapped_sellers_at_support + n_big_t1",
            "bn_trapped_sellers_raw + n_big_sell_t1",
            "n_trapped_buyers_zones_active + bn_absorb_bid_raw",
        ]
        # Adapte aux noms binarises
        top_clusters = [c.replace("aggressor_strong_buy", "agg_strong_buy")
                          .replace("aggressor_strong_sell", "agg_strong_sell")
                        for c in top_clusters]
    else:  # NQ
        top_clusters = [
            "agg_strong_sell + n_big_sell_t1 + bool_above_mq_hvl",  # near_mq_hvl approx
            "bn_stack_ask + n_big_sell_t1 + n_big_t1",
            "n_trapped_sellers_cluster_within_0_2pct + bool_above_mq_hvl",
            "bn_trapped_sellers_raw + n_big_sell_t1",
        ]

    results = {}
    # Section 1
    results["sequences"] = audit_sequences(df, fwd, base_wr, features)
    # Section 2
    results["conditional_tree"] = audit_conditional_tree(df, fwd, base_wr, top_clusters, features)
    # Section 3
    results["continuous"] = audit_continuous_edges(df, fwd, base_wr)
    # Section 4
    results["time"] = audit_time_patterns(df, fwd, base_wr)
    # Section 5
    results["anti_patterns"] = audit_anti_patterns(df, fwd, base_wr, features, top_clusters)

    return df, features, results


if __name__ == "__main__":
    df_es, feat_es, res_es = run_deep_audit("ES")
    df_nq, feat_nq, res_nq = run_deep_audit("NQ")

    # Section 6 : cross-instrument
    print(f"\n{'='*82}")
    print(f"  CROSS-INSTRUMENT LAG (ES -> NQ)")
    print(f"{'='*82}")
    audit_cross_instrument_lag(df_es, df_nq, feat_es, feat_nq)

    print(f"""
{'='*82}
  WARNINGS METHODOLOGIQUES
{'='*82}
  MULTIPLE TESTING : ~3000 combinaisons testees (sequences + conditional tree
  + continuous bins + time + anti-patterns + cross-lag). Bonferroni rigoureux
  exige p<0.05/3000 = 1.7e-5, soit |edge|>=15pp avec n>=100 pour TRUST.

  PATTERNS SEQUENTIELS : edge sequentiel > simultane peut etre artefact
  d'autocorrelation des features (X[t-1] correlated to X[t]). Verifier que
  l'edge reste apres controle pour autocorrelation features.

  CONDITIONAL TREE : sample par contexte tombe vite a n=20-30 pour clusters
  rares. Edge measure peut etre noise. Replication walk-forward obligatoire.

  CONTINUOUS QUANTILES : 10 bins testes par feature = 10 tests. Fenetre
  ouverte aux faux positifs si edge faible (3-5pp). Trust si edge >=10pp +
  bin coherent (sweet spots groupes, pas isoles).

  TIME PATTERNS : edge intraday peut etre dominee par session bias (ex:
  bias bear US lunch). NE PAS confondre time pattern avec strategy edge.

  CROSS-INSTRUMENT LAG : ES leads NQ par 1-3 bars peut etre du noise lie
  aux differences de tick size + liquidite. Lag stable sur sub-samples
  rolling ou one-shot ?
""")
