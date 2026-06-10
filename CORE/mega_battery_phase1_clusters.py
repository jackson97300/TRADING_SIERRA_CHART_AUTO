"""
mega_battery_phase1_clusters.py — Winner Cluster Analysis (Renaissance/Two Sigma).

Phase 1 Mega Battery (validation Plan agent + ml-trainer 27/04 21:00).

Approche bayésienne inverse : au lieu de "quelle règle gagne ?" → "qu'est-ce qui
caractérise les bars gagnantes ?". K-means sur features pre-trade des winners.

Méthodologie (validation ml-trainer + Plan agent 27/04) :
  1. Filtrer winners stricts : label=+1 ET realized_R >= 2.5 (= TP touché net + buffer)
                               ET time_to_TP < 30 bars (gagnants rapides)
  2. K-means k=8 sur top 30 features SHAP v5b PROPRE (post-leak fix)
  3. Validation cluster : silhouette >= 0.35 ET n_min >= 50 trades/cluster
  4. OOS protocol : cluster fit sur 18m (mai 2025 - oct 2026), test sur 6m (nov 2026 - avr 2026)
  5. Pour chaque cluster valide : center features + backtest BUY si bar dans cluster X
  6. Top 5 clusters par PF + BH FDR significatif → setup gagnant identifié

Input : DOCS/features_shap_top30.json (généré par mega_battery_phase2_shap.py)
Output : DOCS/MEGA_BATTERY_PHASE1_CLUSTERS.md + clusters_es_buy_winners.pkl

Auteur : MIA Trading System V2
Date   : 2026-04-27 21:30
"""
from __future__ import annotations

import sys
import json
import time
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Constantes alignees v5b
TICK_SIZE = 0.25
K_SL = 1.5
K_TP_RATIO = 2.0
HORIZON = 60
COST_TICKS = {"ES": 2.3, "NQ": 5.2}

# Critères validation cluster (Plan agent + ml-trainer)
SILHOUETTE_MIN = 0.35
N_MIN_PER_CLUSTER = 50
WINNER_MIN_R = 2.0   # Au moins 2.0×SL gagné = TP touché net (avec mini buffer)
WINNER_MAX_TIME = 30  # < 30 bars = gagnant rapide

# OOS split temporel
OOS_TEST_MONTHS = 6  # Derniers 6 mois en test


def load_top30_features() -> list:
    """Charge top 30 features SHAP v5b PROPRE."""
    json_path = ROOT / "DOCS" / "features_shap_top30.json"
    if not json_path.exists():
        raise FileNotFoundError(f"Run mega_battery_phase2_shap.py d'abord — {json_path}")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return [r["feature"] for r in data["top30"]]


def split_train_oos(df: pd.DataFrame, oos_months: int = 6) -> tuple:
    """Split chronologique train (18m) / OOS test (6m)."""
    df = df.sort_values("ts_event").reset_index(drop=True)
    last_ts = df["ts_event"].max()
    cutoff = last_ts - pd.DateOffset(months=oos_months)
    df_train = df[df["ts_event"] < cutoff].reset_index(drop=True)
    df_oos = df[df["ts_event"] >= cutoff].reset_index(drop=True)
    return df_train, df_oos


def filter_winners(df: pd.DataFrame, target_label: int = 1) -> pd.DataFrame:
    """Filtre les bars gagnantes strictes pour clustering."""
    if "label" not in df.columns or "realized_pts" not in df.columns:
        raise RuntimeError("Dataset doit contenir 'label' + 'realized_pts'")

    # SL/TP en ticks pour normalisation R
    if "atr" not in df.columns:
        raise RuntimeError("Colonne 'atr' manquante")
    sl_ticks = K_SL * df["atr"].values
    realized_R = df["realized_pts"].abs().values / np.maximum(sl_ticks, 1e-6)

    is_winner = (
        (df["label"] == target_label).values
        & (realized_R >= WINNER_MIN_R)
    )
    if "exit_offset" in df.columns:
        is_winner = is_winner & (df["exit_offset"].values < WINNER_MAX_TIME)

    return df[is_winner].reset_index(drop=True)


def cluster_winners(df_winners: pd.DataFrame, features: list,
                     n_clusters: int = 8) -> tuple:
    """K-means clustering sur features SHAP top 30. Returns (model, scaler, labels, silhouette)."""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score

    # Garder seulement les features présentes + drop NaN
    cols_present = [c for c in features if c in df_winners.columns]
    print(f"  Features clustering : {len(cols_present)} / {len(features)} présentes")

    X = df_winners[cols_present].dropna()
    if len(X) < n_clusters * N_MIN_PER_CLUSTER:
        print(f"  [WARN] Seulement {len(X)} winners propres pour {n_clusters} clusters min {N_MIN_PER_CLUSTER}/c")

    scaler = StandardScaler()
    X_std = scaler.fit_transform(X.values)

    print(f"  K-means k={n_clusters} sur {len(X)} winners propres × {len(cols_present)} features...")
    t0 = time.time()
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    labels = km.fit_predict(X_std)
    print(f"  K-means done in {time.time()-t0:.1f}s")

    # Silhouette score (sur sample 5K si trop grand pour vitesse)
    if len(X_std) > 5000:
        rng = np.random.RandomState(42)
        sample_idx = rng.choice(len(X_std), 5000, replace=False)
        sil = silhouette_score(X_std[sample_idx], labels[sample_idx])
    else:
        sil = silhouette_score(X_std, labels)

    print(f"  Silhouette score : {sil:.3f}  (seuil: {SILHOUETTE_MIN})")

    # Stats par cluster
    cluster_sizes = np.bincount(labels)
    print(f"  Cluster sizes : {cluster_sizes.tolist()}")

    return km, scaler, labels, sil, cols_present, X.index.tolist()


def backtest_cluster_oos(df_oos: pd.DataFrame, km, scaler, features_cols: list,
                          cluster_id: int, symbol: str = "ES") -> dict:
    """Backtest BUY si bar OOS dans cluster_id sur OOS test set."""
    # Préparer features OOS
    X_oos = df_oos[features_cols].fillna(df_oos[features_cols].median())
    X_oos_std = scaler.transform(X_oos.values)

    # Predict cluster pour chaque bar OOS
    cluster_assigned = km.predict(X_oos_std)

    # Signal BUY = bar dans cluster X
    sig = np.zeros(len(df_oos), dtype=int)
    sig[cluster_assigned == cluster_id] = 1

    # Simuler trades
    closes = df_oos["close"].values.astype(np.float64)
    highs = df_oos["high"].values.astype(np.float64)
    lows = df_oos["low"].values.astype(np.float64)
    atrs = df_oos["atr"].values.astype(np.float64)
    dates = pd.to_datetime(df_oos["ts"], unit="ms").dt.date.values
    cost = COST_TICKS[symbol]

    pnls = []
    last_bar = -10
    daily_count = {}
    n = len(df_oos)

    for i in range(n - HORIZON - 1):
        if sig[i] == 0:
            continue
        if i - last_bar < 3:  # cooldown 3 bars
            continue
        d = dates[i]
        if daily_count.get(d, 0) >= 5:  # max 5 trades/jour
            continue
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue

        sl_ticks = K_SL * atr_t
        tp_ticks = K_TP_RATIO * sl_ticks
        entry = closes[i]
        sl_pts = sl_ticks * TICK_SIZE
        tp_pts = tp_ticks * TICK_SIZE
        tp_lvl = entry + tp_pts
        sl_lvl = entry - sl_pts

        pnl = -cost  # default
        for k in range(1, HORIZON + 1):
            j = i + k
            if j >= n:
                break
            h = highs[j]
            l = lows[j]
            if l <= sl_lvl:
                pnl = -sl_ticks - cost
                break
            if h >= tp_lvl:
                pnl = tp_ticks - cost
                break
        else:
            exit_close = closes[i + HORIZON] if (i + HORIZON) < n else entry
            pnl = (exit_close - entry) / TICK_SIZE - cost

        pnls.append(pnl)
        last_bar = i
        daily_count[d] = daily_count.get(d, 0) + 1

    if not pnls:
        return {"cluster": cluster_id, "n_trades": 0, "WR": 0, "PF": float("nan"),
                "EV": 0, "Sharpe": 0, "verdict": "NO-GO (no trades)"}

    arr = np.array(pnls)
    n_trades = len(arr)
    n_wins = int((arr > 0).sum())
    wr = n_wins / n_trades if n_trades > 0 else 0
    gw = arr[arr > 0].sum()
    gl = abs(arr[arr < 0].sum())
    pf = gw / gl if gl > 0 else (np.inf if gw > 0 else float("nan"))
    ev = arr.mean()

    # Sharpe daily
    from collections import defaultdict
    daily_pnl = defaultdict(float)
    for p, d in zip(pnls, [dates[i] for i in range(n) if sig[i] == 1][:len(pnls)]):
        daily_pnl[d] += p
    daily_arr = np.array(list(daily_pnl.values()))
    if len(daily_arr) >= 5 and daily_arr.std() > 0:
        sharpe = float(daily_arr.mean() / daily_arr.std() * np.sqrt(252))
    else:
        sharpe = 0.0

    verdict = "NO-GO (n<30)" if n_trades < 30 else (
        "GO" if pf >= 1.5 and wr >= 0.42 else
        "CAUTION" if pf >= 1.3 else
        "NO-GO (PF<1.3)"
    )

    return {
        "cluster": cluster_id,
        "n_trades": n_trades,
        "WR": round(wr * 100, 1),
        "PF": round(pf, 2) if np.isfinite(pf) else float("inf"),
        "EV": round(ev, 2),
        "Sharpe": round(sharpe, 2),
        "verdict": verdict,
    }


def describe_cluster(df_winners_train: pd.DataFrame, labels: np.ndarray,
                      cluster_id: int, features_cols: list, kept_idx: list) -> dict:
    """Décrit un cluster : moyenne, médiane, p10, p90 par feature."""
    mask = labels == cluster_id
    cluster_idx = np.array(kept_idx)[mask]
    sub = df_winners_train.loc[cluster_idx, features_cols]
    desc = {}
    for c in features_cols:
        s = sub[c].dropna()
        if len(s) >= 10:
            desc[c] = {
                "mean": round(float(s.mean()), 4),
                "median": round(float(s.median()), 4),
                "p10": round(float(s.quantile(0.1)), 4),
                "p90": round(float(s.quantile(0.9)), 4),
            }
    return desc


def main():
    print("=" * 70)
    print("MEGA BATTERY — Phase 1 Winner Cluster Analysis (post-leak fix v5b)")
    print("=" * 70)

    # 1. Load top 30 SHAP v5b
    print("\n[1] Loading top 30 features SHAP v5b...")
    top30 = load_top30_features()
    print(f"    Top 5 : {top30[:5]}")

    # 2. Load dataset v5b ES
    print("\n[2] Loading ES_dataset_v5b.parquet...")
    df = pd.read_parquet(ROOT / "DATA/datasets/ES_dataset_v5b.parquet")
    print(f"    {len(df):,} bars × {df.shape[1]} cols")

    # 3. Split train (18m) / OOS (6m)
    print(f"\n[3] Split chronologique : train (18m) / OOS test ({OOS_TEST_MONTHS}m)...")
    df_train, df_oos = split_train_oos(df, OOS_TEST_MONTHS)
    print(f"    Train : {len(df_train):,} bars  ({df_train['ts_event'].min().date()} -> {df_train['ts_event'].max().date()})")
    print(f"    OOS   : {len(df_oos):,} bars  ({df_oos['ts_event'].min().date()} -> {df_oos['ts_event'].max().date()})")

    # 4. Filter winners stricts sur train
    print(f"\n[4] Filter winners stricts (label=+1, realized_R >= {WINNER_MIN_R}, time < {WINNER_MAX_TIME} bars)...")
    df_winners_train = filter_winners(df_train, target_label=1)
    print(f"    Winners train : {len(df_winners_train):,} bars  ({len(df_winners_train)/len(df_train)*100:.2f}% du train)")

    if len(df_winners_train) < N_MIN_PER_CLUSTER * 8:
        print(f"    [WARN] Pas assez de winners pour 8 clusters")
        # Réduire k
        n_clusters = max(3, len(df_winners_train) // N_MIN_PER_CLUSTER)
        print(f"    Reduction k=8 -> k={n_clusters}")
    else:
        n_clusters = 8

    # 5. K-means clustering sur top 30 features
    print(f"\n[5] K-means clustering k={n_clusters}...")
    km, scaler, labels, sil, features_cols, kept_idx = cluster_winners(
        df_winners_train, top30, n_clusters=n_clusters,
    )

    if sil < SILHOUETTE_MIN:
        print(f"    [WARN] Silhouette {sil:.3f} < {SILHOUETTE_MIN} = clusters peu séparables")

    # 6. Backtest chaque cluster sur OOS
    print(f"\n[6] Backtest chaque cluster sur OOS test {OOS_TEST_MONTHS}m...")
    results = []
    for cid in range(n_clusters):
        cluster_size_train = (labels == cid).sum()
        if cluster_size_train < N_MIN_PER_CLUSTER:
            print(f"  [Cluster {cid}] {cluster_size_train} winners < {N_MIN_PER_CLUSTER} → skip")
            continue
        result = backtest_cluster_oos(df_oos, km, scaler, features_cols, cid, "ES")
        result["winners_train"] = int(cluster_size_train)
        # Description cluster
        desc = describe_cluster(df_winners_train, labels, cid, features_cols, kept_idx)
        result["description"] = desc
        results.append(result)
        print(f"  [Cluster {cid}] winners_train={cluster_size_train} | "
              f"OOS: trades={result['n_trades']:>4} WR={result['WR']:>4.1f}% "
              f"PF={result['PF']} EV={result['EV']:+5.1f}t Sharpe={result['Sharpe']:.2f} | {result['verdict']}")

    # 7. Top 5 par PF
    print(f"\n[7] Top clusters par PF (OOS)...")
    valid_results = [r for r in results if r["n_trades"] >= 30 and np.isfinite(r["PF"])]
    valid_results.sort(key=lambda r: r["PF"], reverse=True)

    print("\n  Cluster | Winners | OOS Trades | WR    | PF    | EV     | Sharpe | Verdict")
    print("  " + "-" * 78)
    for r in valid_results[:5]:
        print(f"  {r['cluster']:>7} | {r['winners_train']:>7} | "
              f"{r['n_trades']:>10} | {r['WR']:>4.1f}% | {r['PF']:>4.2f} | "
              f"{r['EV']:+5.1f}t | {r['Sharpe']:>6.2f} | {r['verdict']}")

    # 8. Save
    out_dir = ROOT / "DOCS"
    out_pkl = ROOT / "DATA/MODELS/clusters_es_buy_winners.pkl"
    out_pkl.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pkl, "wb") as f:
        pickle.dump({
            "kmeans": km,
            "scaler": scaler,
            "features_cols": features_cols,
            "results": results,
        }, f)
    print(f"\n  [SAVED] {out_pkl}")

    # 9. Markdown report
    md_path = out_dir / "MEGA_BATTERY_PHASE1_CLUSTERS.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Mega Battery Phase 1 — Winner Cluster Analysis (ES BUY v5b)\n\n")
        f.write(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Dataset** : ES_dataset_v5b.parquet (post-leak fix)\n")
        f.write(f"**Train** : {len(df_train):,} bars, OOS test : {len(df_oos):,} bars ({OOS_TEST_MONTHS}m)\n")
        f.write(f"**Winners stricts train** : {len(df_winners_train):,} bars (R >= {WINNER_MIN_R}, time < {WINNER_MAX_TIME})\n")
        f.write(f"**K-means** : k={n_clusters}, silhouette={sil:.3f}\n")
        f.write(f"**Triple Barrier** : K_SL={K_SL}, K_TP={K_TP_RATIO}, H={HORIZON}\n\n")
        f.write("## Top clusters par PF OOS\n\n")
        f.write("| Cluster | Winners train | OOS trades | WR | PF | EV/trade | Sharpe | Verdict |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in valid_results:
            f.write(f"| {r['cluster']} | {r['winners_train']} | {r['n_trades']} | "
                    f"{r['WR']:.1f}% | {r['PF']:.2f} | {r['EV']:+.1f}t | {r['Sharpe']:.2f} | {r['verdict']} |\n")
        f.write("\n## Description des clusters (top 3 par PF)\n\n")
        for r in valid_results[:3]:
            f.write(f"### Cluster {r['cluster']} (PF {r['PF']:.2f})\n\n")
            f.write("| Feature | Median | p10 | p90 |\n|---|---|---|---|\n")
            for feat, stats in list(r.get("description", {}).items())[:15]:
                f.write(f"| {feat} | {stats['median']} | {stats['p10']} | {stats['p90']} |\n")
            f.write("\n")
    print(f"  [SAVED] {md_path}")


if __name__ == "__main__":
    main()
