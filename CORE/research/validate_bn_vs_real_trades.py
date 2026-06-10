"""validate_bn_vs_real_trades.py — Test CTA replay : BN V2 detecte-t-il les setups Jackson ?

Methodologie (Klein 1998 cognitive task analysis) :
  1. Jackson identifie 5+ trades BN reels gagnants en surveillant live
  2. Pour chaque trade : date + heure UTC + direction + prix entry approximatif
  3. Script charge fenetre NQ +/- 30 min autour de chaque trade
  4. Run BN V2 iterative sur la fenetre
  5. Verifie : BN V2 a-t-il detecte un setup dans la fenetre ?
     - MATCH si is_range_macro=False ET signal LONG/SHORT_ENTRY dans +/- 5 min
     - PARTIAL si BN detecte mais autre direction
     - MISS si aucun setup dans la fenetre

  Verdict :
    >= 4/5 MATCH → code = methode Jackson confirmee → GO mode OBSERVATION
    2-3/5 MATCH → code partiellement aligne, ajustement methodo necessaire
    <= 1/5 MATCH → code != BN, redesign requis (CTA pure)

FORMAT INPUT : DATA/RESEARCH/jackson_bn_real_trades.csv

  ts_entry,direction,entry_price,outcome,notes
  2026-05-08T14:35:00Z,LONG,28650.0,WIN,"trend up Lundi London, 3 HH casses"
  2026-05-09T16:20:00Z,SHORT,25400.0,WIN,"baissier RTH, base rouge cassee"
  ...

Usage :
    python -X utf8 CORE/research/validate_bn_vs_real_trades.py [--csv DATA/RESEARCH/jackson_bn_real_trades.csv]

Date : 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CORE.bn_engine import BNEngine, BNState


WINDOW_MIN_BEFORE = 60   # 60 min avant trade entry
WINDOW_MIN_AFTER = 10    # 10 min apres
TOLERANCE_MATCH_MIN = 5  # +/- 5 min pour MATCH


def load_jackson_trades(csv_path: Path) -> pd.DataFrame:
    """Charge les trades references Jackson."""
    if not csv_path.exists():
        print(f"WARNING : {csv_path} absent. Cree-le selon format docstring.")
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    df["ts_entry"] = pd.to_datetime(df["ts_entry"], utc=True)
    return df


def load_nq_window(ts_entry: pd.Timestamp, sym: str = "NQ") -> pd.DataFrame:
    """Charge la fenetre NQ autour de ts_entry."""
    import pyarrow.dataset as ds
    sym_mapping = {"NQ": "NQ.c.0", "ES": "ES.c.0"}
    path = Path(f"D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS/v4_enriched/symbol={sym_mapping[sym]}")
    if not path.exists():
        print(f"Dataset {path} absent")
        return pd.DataFrame()

    dataset = ds.dataset(path, format="parquet")
    cols = [
        "ts_event", "open", "high", "low", "close",
        "long_up_bar", "long_dn_bar",
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
        "bars_since_last_swing_high", "bars_since_last_swing_low",
        "inside_value_area", "aggressor_imbalance",
    ]
    available = [c for c in cols if c in dataset.schema.names]
    df = dataset.to_table(columns=available).to_pandas()
    df = df.sort_values("ts_event").reset_index(drop=True)

    # Filter window
    start = ts_entry - pd.Timedelta(minutes=WINDOW_MIN_BEFORE)
    end = ts_entry + pd.Timedelta(minutes=WINDOW_MIN_AFTER)
    mask = (df["ts_event"] >= start) & (df["ts_event"] <= end)
    return df[mask].reset_index(drop=True)


def evaluate_match(window: pd.DataFrame, ts_entry: pd.Timestamp,
                   direction_real: str, sym: str = "NQ") -> dict:
    """Run BN V2 sur la fenetre et check si signal coherent avec trade reel."""
    if len(window) < 60:
        return {"verdict": "INSUFFICIENT_DATA", "n_bars": len(window)}

    eng = BNEngine(sym=sym)
    state = BNState()
    detections: list[dict] = []

    for i in range(60, len(window)):
        df_win = window.iloc[:i + 1]
        result = eng.update(df_win, state)
        ts_bar = window.iloc[i]["ts_event"]

        if result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
            detections.append({
                "ts": ts_bar,
                "signal": result.signal,
                "direction": result.direction,
                "entry_price": float(window.iloc[i]["close"]),
                "delta_min_to_real": (ts_bar - ts_entry).total_seconds() / 60.0,
            })
            # Reset state pour permettre detection suivante
            state = BNState()
            eng = BNEngine(sym=sym)

    # Verdict
    matches_close = [d for d in detections if abs(d["delta_min_to_real"]) <= TOLERANCE_MATCH_MIN]
    matches_close_dir = [d for d in matches_close
                         if (d["direction"] == direction_real)]

    if matches_close_dir:
        verdict = "MATCH"
        best = matches_close_dir[0]
    elif matches_close:
        verdict = "PARTIAL"  # BN detecte mais mauvaise direction
        best = matches_close[0]
    elif detections:
        verdict = "OUT_OF_WINDOW"
        best = detections[0]
    else:
        verdict = "MISS"
        best = None

    return {
        "verdict": verdict,
        "n_detections": len(detections),
        "best_match": best,
        "all_detections": detections,
    }


def main(csv_path: Path) -> None:
    print(f"=== Validation BN V2 vs trades reels Jackson ===")
    df = load_jackson_trades(csv_path)
    if df.empty:
        print("\nFORMAT CSV ATTENDU :")
        print("ts_entry,direction,entry_price,outcome,notes")
        print("2026-05-08T14:35:00Z,LONG,28650.0,WIN,\"trend up Lundi London\"")
        return

    print(f"N trades references : {len(df)}\n")

    results = []
    for idx, row in df.iterrows():
        ts = row["ts_entry"]
        direction = row["direction"]
        print(f"--- Trade #{idx + 1} : {ts} {direction} @ {row.get('entry_price', '?')} ---")

        window = load_nq_window(ts)
        if len(window) == 0:
            print("  Pas de data dispo dans cette fenetre")
            results.append({"idx": idx, "verdict": "NO_DATA"})
            continue

        eval_result = evaluate_match(window, ts, direction)
        print(f"  Verdict : {eval_result['verdict']}")
        print(f"  N detections BN dans fenetre : {eval_result['n_detections']}")
        if eval_result["best_match"]:
            bm = eval_result["best_match"]
            print(f"  Best match : {bm['signal']} {bm['direction']} @ {bm['entry_price']:.2f} "
                  f"(delta {bm['delta_min_to_real']:+.1f} min)")
        results.append({"idx": idx, "verdict": eval_result["verdict"],
                        "n_detections": eval_result["n_detections"]})
        print()

    # Synthese
    print("=== SYNTHESE ===")
    n_match = sum(1 for r in results if r["verdict"] == "MATCH")
    n_partial = sum(1 for r in results if r["verdict"] == "PARTIAL")
    n_out = sum(1 for r in results if r["verdict"] == "OUT_OF_WINDOW")
    n_miss = sum(1 for r in results if r["verdict"] == "MISS")
    n_total = len(results)

    print(f"  MATCH:         {n_match}/{n_total}")
    print(f"  PARTIAL:       {n_partial}/{n_total}")
    print(f"  OUT_OF_WINDOW: {n_out}/{n_total}")
    print(f"  MISS:          {n_miss}/{n_total}")

    print("\n=== VERDICT ===")
    if n_match >= 0.8 * n_total:
        verdict = "GO — Code BN V2 = methode Jackson confirmee (>= 80% match)"
    elif n_match >= 0.5 * n_total:
        verdict = "ADJUST — Code partiellement aligne. Ajuster seuils sur cas MISS"
    else:
        verdict = "REDESIGN — Code != BN reel. Faire CTA pure (replay verbal Jackson)"
    print(f"  >>> {verdict}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="DATA/RESEARCH/jackson_bn_real_trades.csv")
    args = parser.parse_args()
    main(Path(args.csv))
