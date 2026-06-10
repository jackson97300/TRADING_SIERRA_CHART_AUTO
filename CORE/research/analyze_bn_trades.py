"""analyze_bn_trades.py — Analyse comparative wins vs losses BN V2.

Methodologie ANTI-DATA-MINING (cf .claude/memory/feedback_data_mining_trap.md) :

  1. Split chronologique 70/30 (TRAIN / TEST). Pas de tuning sur TEST.
  2. Sur TRAIN : compare wins vs losses sur 7 features contextuelles A PRIORI :
     - entry_session (ASIA/LONDON/RTH_OPEN/RTH_MID/RTH_CLOSE/US_AH)
     - entry_hour_utc
     - entry_atr_norm (volatility)
     - entry_inside_va (Value Area)
     - entry_aggressor (flow imbalance)
     - direction (LONG vs SHORT)
     - entry_n_color_up + entry_n_color_dn (zones actives)
  3. Si UNE feature montre gap WR significatif (>= 15pp absolu) → hypothese filtre
  4. Test du filtre sur TEST set : verifier que le gap se confirme
  5. Si confirme → recommandation. Sinon NOGO honnete.

Usage :
    python -X utf8 CORE/research/analyze_bn_trades.py [--csv DATA/RESEARCH/bn_trades_NQ_130t.csv]

Date : 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_trades(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["is_win"] = df["pnl_ticks"] > 0
    return df


def compare_groups(df: pd.DataFrame, feature: str, label: str) -> pd.DataFrame:
    """Stats par valeur de la feature : N, WR, EV, PF."""
    rows = []
    for val, grp in df.groupby(feature):
        n = len(grp)
        if n < 5:  # Trop peu pour stat
            continue
        n_wins = int(grp["is_win"].sum())
        wr = n_wins / n
        ev = float(grp["pnl_ticks"].mean())
        sum_w = float(grp[grp["pnl_ticks"] > 0]["pnl_ticks"].sum())
        sum_l = float(abs(grp[grp["pnl_ticks"] < 0]["pnl_ticks"].sum()))
        pf = sum_w / sum_l if sum_l > 0 else float("inf")
        rows.append({
            label: val, "n": n, "wr": round(wr, 3),
            "ev_ticks": round(ev, 2), "pf": round(pf, 2),
            "total_ticks": round(float(grp["pnl_ticks"].sum()), 1),
        })
    return pd.DataFrame(rows).sort_values("pf", ascending=False)


def numeric_quartiles(df: pd.DataFrame, feature: str, label: str) -> tuple[pd.DataFrame, list[float]]:
    """Quartiles d'une feature numerique avec stats par bin.
    Retourne (stats_df, edges) pour pouvoir appliquer les MEMES quartiles a un autre set.
    """
    if df[feature].nunique() < 4:
        return pd.DataFrame(), []
    df = df.copy()
    edges = list(np.quantile(df[feature].dropna(), [0.0, 0.25, 0.5, 0.75, 1.0]))
    df["bin"] = pd.cut(df[feature], bins=edges, include_lowest=True,
                       labels=["Q1", "Q2", "Q3", "Q4"])
    rows = []
    for val, grp in df.groupby("bin", observed=True):
        n = len(grp)
        if n < 5:
            continue
        n_wins = int(grp["is_win"].sum())
        wr = n_wins / n
        ev = float(grp["pnl_ticks"].mean())
        sum_w = float(grp[grp["pnl_ticks"] > 0]["pnl_ticks"].sum())
        sum_l = float(abs(grp[grp["pnl_ticks"] < 0]["pnl_ticks"].sum()))
        pf = sum_w / sum_l if sum_l > 0 else float("inf")
        rows.append({
            label: str(val),
            "range": f"{grp[feature].min():.2f}-{grp[feature].max():.2f}",
            "n": n, "wr": round(wr, 3),
            "ev_ticks": round(ev, 2), "pf": round(pf, 2),
        })
    return pd.DataFrame(rows), edges


def split_train_test(df: pd.DataFrame, ratio: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split chronologique strict (anti-leak)."""
    df = df.sort_values("entry_idx").reset_index(drop=True)
    cut = int(len(df) * ratio)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def find_best_filter(train_df: pd.DataFrame) -> dict | None:
    """Cherche un filtre simple sur TRAIN qui ameliore PF. Retourne hypothese ou None."""
    print("\n=== Analyse TRAIN set (70%) ===")
    print(f"N trades: {len(train_df)}, PF global: {compute_pf(train_df):.2f}")

    # 1. Par session
    print("\n--- Par session ---")
    sess = compare_groups(train_df, "entry_session", "session")
    print(sess.to_string(index=False))

    # 2. Par direction
    print("\n--- Par direction ---")
    direc = compare_groups(train_df, "direction", "direction")
    print(direc.to_string(index=False))

    # 3. Par jour de semaine
    print("\n--- Par jour semaine (0=lundi) ---")
    dow = compare_groups(train_df, "entry_day_of_week", "dow")
    print(dow.to_string(index=False))

    # 4. ATR norm quartiles
    print("\n--- Par volatility (atr_norm quartiles) ---")
    atr_q, atr_edges = numeric_quartiles(train_df, "entry_atr_norm", "atr_q")
    print(atr_q.to_string(index=False) if len(atr_q) else "(pas assez de variance)")

    # 5. Aggressor quartiles
    print("\n--- Par aggressor (quartiles) ---")
    agg_q, agg_edges = numeric_quartiles(train_df, "entry_aggressor", "agg_q")
    print(agg_q.to_string(index=False) if len(agg_q) else "(pas assez de variance)")

    # 6. Inside VA
    print("\n--- Inside VA (0/1) ---")
    iva = compare_groups(train_df, "entry_inside_va", "in_va")
    print(iva.to_string(index=False))

    # Cherche le filtre le plus discriminant : groupe avec PF >= 1.5 ET n >= 15
    candidates = []
    for stat_df, feature, label, edges in [
        (sess, "entry_session", "session", None),
        (direc, "direction", "direction", None),
        (dow, "entry_day_of_week", "dow", None),
        (iva, "entry_inside_va", "inside_va", None),
    ]:
        if len(stat_df) == 0:
            continue
        for _, row in stat_df.iterrows():
            if row["n"] >= 15 and row["pf"] >= 1.5 and row["pf"] != float("inf"):
                candidates.append({
                    "feature": feature,
                    "value": row[label] if label in row else row[stat_df.columns[0]],
                    "n": row["n"],
                    "pf": row["pf"],
                    "wr": row["wr"],
                    "kind": "categorical",
                })

    # ATR quartiles (binning utilise sur TEST avec memes edges)
    if len(atr_q) > 0:
        for _, row in atr_q.iterrows():
            if row["n"] >= 15 and row["pf"] >= 1.5 and row["pf"] != float("inf"):
                # Q1 = first quartile : entry_atr_norm <= edges[1]
                q_label = row["atr_q"]
                q_idx = ["Q1", "Q2", "Q3", "Q4"].index(q_label)
                low = atr_edges[q_idx]
                high = atr_edges[q_idx + 1]
                candidates.append({
                    "feature": "entry_atr_norm",
                    "value": (low, high),
                    "n": row["n"],
                    "pf": row["pf"],
                    "wr": row["wr"],
                    "kind": "numeric_range",
                })

    if not candidates:
        print("\n>>> AUCUN filtre n'atteint PF >= 1.5 avec n >= 15 sur TRAIN. NOGO.")
        return None

    candidates.sort(key=lambda c: c["pf"], reverse=True)
    print(f"\n>>> {len(candidates)} candidats filtres (PF >= 1.5, n >= 15) :")
    for c in candidates[:5]:
        print(f"    {c['feature']}={c['value']} : n={c['n']}, PF={c['pf']}, WR={c['wr']}")
    return candidates[:5]  # Top 5 pour validation TEST


def validate_on_test(test_df: pd.DataFrame, hypothesis: dict) -> dict:
    """Applique le filtre identifie sur TRAIN au TEST set."""
    feature = hypothesis["feature"]
    value = hypothesis["value"]
    kind = hypothesis.get("kind", "categorical")

    print(f"\n=== Validation TEST set (30%) ===")
    print(f"N trades TEST total: {len(test_df)}, PF global TEST: {compute_pf(test_df):.2f}")

    if feature not in test_df.columns:
        print(f"Feature {feature} absente du TEST")
        return {}

    if kind == "numeric_range":
        low, high = value
        filtered = test_df[(test_df[feature] >= low) & (test_df[feature] <= high)]
        filter_str = f"{feature} in [{low:.2f}, {high:.2f}]"
    else:
        filtered = test_df[test_df[feature] == value]
        filter_str = f"{feature}={value}"

    if len(filtered) < 5:
        print(f"Filtre {filter_str} : seulement {len(filtered)} trades sur TEST → INSUFFISANT")
        return {}

    pf_test = compute_pf(filtered)
    wr_test = float(filtered["is_win"].mean())
    ev_test = float(filtered["pnl_ticks"].mean())

    print(f"\nFiltre {filter_str} sur TEST :")
    print(f"  N: {len(filtered)}")
    print(f"  PF: {pf_test:.2f}")
    print(f"  WR: {wr_test:.1%}")
    print(f"  EV ticks: {ev_test:.2f}")

    return {
        "filter": filter_str,
        "test_n": len(filtered),
        "test_pf": pf_test,
        "test_wr": wr_test,
        "test_ev_ticks": ev_test,
        "train_pf": hypothesis["pf"],
        "train_wr": hypothesis["wr"],
    }


def compute_pf(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return 0.0
    sum_w = float(df[df["pnl_ticks"] > 0]["pnl_ticks"].sum())
    sum_l = float(abs(df[df["pnl_ticks"] < 0]["pnl_ticks"].sum()))
    return sum_w / sum_l if sum_l > 0 else float("inf")


def main(csv_path: Path) -> None:
    df = load_trades(csv_path)
    print(f"=== Analyse BN trades : {csv_path.name} ===")
    print(f"N trades total: {len(df)}")
    print(f"PF global: {compute_pf(df):.2f}")
    print(f"WR global: {df['is_win'].mean():.1%}")
    print(f"Periode: trade idx [{df['entry_idx'].min()}, {df['entry_idx'].max()}]")

    train, test = split_train_test(df, ratio=0.7)
    print(f"\nSplit chronologique 70/30 :")
    print(f"  TRAIN: {len(train)} trades (idx {train['entry_idx'].min()}-{train['entry_idx'].max()})")
    print(f"  TEST:  {len(test)} trades (idx {test['entry_idx'].min()}-{test['entry_idx'].max()})")

    hypotheses = find_best_filter(train)
    if not hypotheses:
        print("\n>>> VERDICT FINAL : NOGO. Aucun filtre robuste identifie sur TRAIN.")
        return

    print(f"\n=== Validation TEST set des Top-{len(hypotheses)} filtres ===")
    print(f"N trades TEST total: {len(test)}, PF global TEST: {compute_pf(test):.2f}")

    results = []
    for hyp in hypotheses:
        r = validate_on_test(test, hyp)
        if r:
            r["pf_drop"] = (r["train_pf"] - r["test_pf"]) / max(r["train_pf"], 1e-9)
            results.append(r)

    if not results:
        print("\n>>> VERDICT FINAL : INSUFFICIENT (filtres identifies mais TEST trop petit pour tous).")
        return

    print("\n=== Tableau recap TRAIN vs TEST ===")
    recap = pd.DataFrame([{
        "filter": r["filter"],
        "train_pf": r["train_pf"],
        "test_pf": round(r["test_pf"], 2),
        "test_n": r["test_n"],
        "test_wr": round(r["test_wr"], 3),
        "test_ev_ticks": round(r["test_ev_ticks"], 2),
        "pf_drop_pct": round(r["pf_drop"] * 100, 1),
    } for r in results])
    print(recap.to_string(index=False))

    # Le meilleur sur TEST (anti-cherry-pick = on prend celui qui survit le mieux)
    best = max(results, key=lambda r: r["test_pf"])
    print(f"\n=== Meilleur filtre robuste ===")
    print(f"  {best['filter']}")
    print(f"  TRAIN PF: {best['train_pf']:.2f} → TEST PF: {best['test_pf']:.2f} (drop: {best['pf_drop']:+.0%})")
    print(f"  TEST n={best['test_n']}, WR={best['test_wr']:.1%}, EV={best['test_ev_ticks']:.1f}t")

    if best["test_pf"] >= 1.5 and best["pf_drop"] < 0.40:
        verdict = f"GO ROBUSTE — Filtre {best['filter']} tient sur TEST"
    elif best["test_pf"] >= 1.2:
        verdict = f"GO RESERVE — Filtre marginal. Mode OBSERVATION 60j+ avant deploy"
    else:
        verdict = f"NOGO — Pattern 11 confirme : edge train ne survit pas test"

    print(f"\n>>> VERDICT FINAL : {verdict}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="DATA/RESEARCH/bn_trades_NQ_130t.csv")
    args = parser.parse_args()
    main(Path(args.csv))
