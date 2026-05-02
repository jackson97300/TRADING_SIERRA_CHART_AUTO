"""
grid_search_pt_sl_horizon.py — Calibration params labeler_v3 sur ES + NQ reel

Created : 2026-05-02 samedi pre-V5 build
Author : Jackson + finding test integration data reel NQ (57/43/0.1 vs 25/50/25)

Goal : trouver (pt_sl, horizon) qui donne distribution ~25/50/25 sur ES ET NQ
avec sample weights coherents et balance acceptable.

Grid search :
  pt_sl ∈ [(1.5, 1.0), (2.0, 1.5), (2.0, 2.0), (2.5, 2.0), (1.5, 1.5)]
  horizon ∈ [6, 8, 12, 16, 24]

Score critere :
  + min(class_pct) >= 0.10 (Lopez : 10% par classe minimum)
  + |HOLD - 0.50| < 0.20 (HOLD entre 30% et 70%)
  + |class_+1 - class_-1| < 0.15 (asymetrie acceptable)
  + cohrent ES vs NQ (memes params performent sur 2 instruments)
"""

from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from labeler_v3 import label_dataset_v3

PARQUET_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"


def load_1m_avril_2026(symbol: str, rth_only: bool = True) -> pd.DataFrame:
    base = PARQUET_ROOT / f"symbol={symbol}" / "year=2026" / "month=4"
    parts = []
    for day_dir in sorted(base.glob("day=*")):
        for parquet in sorted(day_dir.glob("*.parquet")):
            parts.append(pd.read_parquet(parquet))
    if not parts:
        return pd.DataFrame()
    full = pd.concat(parts, ignore_index=True)
    if "ts_event" not in full.columns:
        full = full.reset_index().rename(columns={"index": "ts_event"})
    full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
    full = full.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)

    # AMELIORATION agent Claude.com point 3 : filtre RTH 9:30-16:00 ET
    # ts_event est UTC naive. RTH ET = UTC-4 en avril 2026 (DST).
    # 9:30 ET = 13:30 UTC, 16:00 ET = 20:00 UTC.
    if rth_only:
        n_before = len(full)
        full['ts_utc'] = full['ts_event']
        full['hour_utc'] = full['ts_utc'].dt.hour
        full['min_utc'] = full['ts_utc'].dt.minute
        # RTH UTC = [13:30, 20:00[
        mask = ((full['hour_utc'] > 13) | ((full['hour_utc'] == 13) & (full['min_utc'] >= 30))) & \
               (full['hour_utc'] < 20)
        full = full[mask].drop(columns=['ts_utc', 'hour_utc', 'min_utc']).reset_index(drop=True)
        print(f"  [RTH filter {symbol}] {n_before} → {len(full)} bars 1m (drop {n_before-len(full)} overnight)")
    return full


def resample_1m_to_5m(df_1m: pd.DataFrame) -> pd.DataFrame:
    df = df_1m.set_index("ts_event")
    df_5m = df.resample("5min", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna().reset_index()
    return df_5m


def run_grid_for_symbol(symbol: str, df_5m: pd.DataFrame, grid: list) -> list:
    """Run grid search sur un symbol, retourne list of dict."""
    results = []
    print(f"\n{'='*80}")
    print(f"GRID SEARCH {symbol} ({len(df_5m)} bars 5m)")
    print(f"{'='*80}\n")

    for pt_sl, horizon in grid:
        try:
            events = label_dataset_v3(
                df_5m.copy(),
                tf_name='5m',
                pt_sl=pt_sl,
                horizon_bars=horizon,
                rvol_threshold=0.3,
            )
            if events.empty:
                results.append({
                    'symbol': symbol, 'pt_sl': pt_sl, 'horizon': horizon,
                    'n_events': 0, 'class_pos': 0, 'class_neg': 0, 'class_hold': 0,
                    'sw_mean': 0, 'sw_std': 0, 'min_class': 0, 'score': -999,
                })
                continue
            dist = events['label'].value_counts(normalize=True)
            n_pos = float(dist.get(1, 0))
            n_neg = float(dist.get(-1, 0))
            n_hold = float(dist.get(0, 0))
            min_class = min(n_pos, n_neg, n_hold)

            sw = events['sample_weight'].dropna()
            sw_mean = float(sw.mean()) if len(sw) > 0 else 0
            sw_std = float(sw.std()) if len(sw) > 0 else 0

            # Score binaire (Lopez gates) :
            score = 0
            if min_class >= 0.10:
                score += 1
            if 0.20 <= n_hold <= 0.70:
                score += 1
            if abs(n_pos - n_neg) < 0.15:
                score += 1
            # AMELIORATION agent point 2 : sample weight raisonnable
            if sw_mean > 0.30 and sw_mean < 50:
                score += 0.5

            # AMELIORATION agent point 1 : score CONTINU pour departage
            # Cible : HOLD ~40% (realiste futures), asymetrie 0
            penalty_hold = abs(n_hold - 0.40)
            penalty_asym = abs(n_pos - n_neg)
            score_fine = score - penalty_hold - penalty_asym

            results.append({
                'symbol': symbol,
                'pt_sl': str(pt_sl),
                'horizon': horizon,
                'n_events': len(events),
                'class_pos': n_pos,
                'class_neg': n_neg,
                'class_hold': n_hold,
                'sw_mean': sw_mean,
                'sw_std': sw_std,
                'min_class': min_class,
                'score': score,
                'score_fine': score_fine,
            })
            print(f"  pt_sl={pt_sl} horizon={horizon}: "
                  f"+{n_pos:.1%}/-{n_neg:.1%}/HOLD={n_hold:.1%} "
                  f"sw={sw.mean():.2f}+/-{sw.std():.2f} score={score}")
        except Exception as e:
            print(f"  pt_sl={pt_sl} horizon={horizon}: CRASH {type(e).__name__}: {e}")
            continue
    return results


def main():
    print("CHARGEMENT donnees ES + NQ avril 2026")
    df_es_1m = load_1m_avril_2026("ES.c.0")
    df_nq_1m = load_1m_avril_2026("NQ.c.0")
    print(f"  ES 1m: {len(df_es_1m)} bars")
    print(f"  NQ 1m: {len(df_nq_1m)} bars")

    df_es_5m = resample_1m_to_5m(df_es_1m)
    df_nq_5m = resample_1m_to_5m(df_nq_1m)
    print(f"  ES 5m: {len(df_es_5m)} bars")
    print(f"  NQ 5m: {len(df_nq_5m)} bars")

    # Grid : 5 pt_sl x 5 horizons = 25 combinaisons par symbol
    pt_sl_grid = [
        (1.5, 1.0),  # default actuel (RR 1.5)
        (1.5, 1.5),  # RR 1.0 (symetrique tight)
        (2.0, 1.5),  # RR 1.33
        (2.0, 2.0),  # RR 1.0 (plus de HOLD attendu)
        (2.5, 2.0),  # RR 1.25 (large)
        (3.0, 3.0),  # RR 1.0 large (cible HOLD eleve)
    ]
    horizon_grid = [4, 6, 8, 12, 16, 24]  # +4 (20 min) ajoute (agent point 4)

    grid = [(pt_sl, h) for pt_sl in pt_sl_grid for h in horizon_grid]
    print(f"\n{len(grid)} combinaisons par symbol")

    results_es = run_grid_for_symbol("ES", df_es_5m, grid)
    results_nq = run_grid_for_symbol("NQ", df_nq_5m, grid)

    # Cross-symbol analysis : score combine ES + NQ
    print(f"\n{'='*80}")
    print("CROSS-SYMBOL : score combine ES + NQ (max 7, min 0) + score_fine")
    print(f"{'='*80}")
    df_es = pd.DataFrame(results_es).set_index(['pt_sl', 'horizon'])
    df_nq = pd.DataFrame(results_nq).set_index(['pt_sl', 'horizon'])
    combined = df_es[['score']].rename(columns={'score': 'score_es'})
    combined['score_nq'] = df_nq['score']
    combined['total'] = combined['score_es'] + combined['score_nq']
    # Score fine combine pour departager
    combined['fine_es'] = df_es['score_fine']
    combined['fine_nq'] = df_nq['score_fine']
    combined['total_fine'] = combined['fine_es'] + combined['fine_nq']
    combined['es_pos'] = df_es['class_pos']
    combined['es_neg'] = df_es['class_neg']
    combined['es_hold'] = df_es['class_hold']
    combined['nq_pos'] = df_nq['class_pos']
    combined['nq_neg'] = df_nq['class_neg']
    combined['nq_hold'] = df_nq['class_hold']

    # Top 10 combinaisons : trier par total puis total_fine pour departage
    top10 = combined.sort_values(['total', 'total_fine'], ascending=False).head(10)
    print("\nTOP 10 combinaisons (score binaire + fine) :")
    cols_disp = ['total', 'total_fine', 'es_pos', 'es_neg', 'es_hold',
                 'nq_pos', 'nq_neg', 'nq_hold']
    print(top10[cols_disp].to_string())

    # Save raw results
    out_path = ROOT / "DATA" / "GRID_SEARCH_PT_SL_HORIZON_20260502.csv"
    combined.reset_index().to_csv(out_path, index=False)
    print(f"\nResultats sauvegardes : {out_path}")

    # Recommandation
    best = top10.iloc[0]
    print(f"\n{'='*80}")
    print(f"RECOMMANDATION : pt_sl={best.name[0]}, horizon={best.name[1]}")
    print(f"  ES: +{best['es_pos']:.1%}/-{best['es_neg']:.1%}/HOLD={best['es_hold']:.1%}")
    print(f"  NQ: +{best['nq_pos']:.1%}/-{best['nq_neg']:.1%}/HOLD={best['nq_hold']:.1%}")
    print(f"  Score combined : {int(best['total'])}/6")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
