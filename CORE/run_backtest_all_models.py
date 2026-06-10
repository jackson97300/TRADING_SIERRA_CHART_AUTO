"""
Backtest all primary models sur ES + NQ — MIA V2

Lance `BacktestFramework.run()` sur les 10 primary models (sans le filter)
et produit un rapport synthetique GO/NO-GO par model.

Usage :
    python -X utf8 CORE/run_backtest_all_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from CORE.backtest_pm import BacktestConfig, BacktestFramework
from CORE.primary_models.double_top_bottom import DoubleTopBottomModel
from CORE.primary_models.dow_trend_fractal import DowTrendFractalModel
from CORE.primary_models.expected_move_reversion import ExpectedMoveReversionModel
from CORE.primary_models.gap_fade import GapFadeModel
from CORE.primary_models.mq_level_bounce import MqLevelBounceModel
from CORE.primary_models.orb import OpeningRangeBreakoutModel
from CORE.primary_models.poor_high_low_retest import PoorHighLowRetestModel
from CORE.primary_models.trend_day_rider import TrendDayRiderModel
from CORE.primary_models.va_failure_fade import VaFailureFadeModel
from CORE.primary_models.vwap_reversion import VwapReversionModel


MODELS = [
    VwapReversionModel(),
    ExpectedMoveReversionModel(),
    VaFailureFadeModel(),
    MqLevelBounceModel(),
    TrendDayRiderModel(),
    OpeningRangeBreakoutModel(),
    GapFadeModel(),
    DoubleTopBottomModel(),
    PoorHighLowRetestModel(),
    DowTrendFractalModel(),
]


def enrich_with_bar_ohlc(df: pd.DataFrame, jsonl_dir: Path, symbol: str) -> pd.DataFrame:
    """Enrichit le parquet ML avec bar_high/bar_low depuis les JSONL bruts.

    Le parquet v2 a drop bar_high/bar_low mais ils sont presents dans le JSONL.
    Le backtest framework en a besoin pour Triple Barrier realiste.
    """
    import json
    import glob

    ohlc = {}
    files = sorted(glob.glob(str(jsonl_dir / f"*_{symbol}.jsonl")))
    for f in files:
        with open(f, "r") as fh:
            for line in fh:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = data.get("ts")
                bh = data.get("bar_high")
                bl = data.get("bar_low")
                if ts is not None and bh is not None and bl is not None:
                    ohlc[ts] = (bh, bl)

    df = df.copy()
    df["bar_high"] = df["ts"].map(lambda t: ohlc.get(t, (None, None))[0])
    df["bar_low"] = df["ts"].map(lambda t: ohlc.get(t, (None, None))[1])
    # Fallback : si pas trouve dans JSONL, utiliser price +/- 1 tick
    df["bar_high"] = df["bar_high"].fillna(df["price"] + 0.25)
    df["bar_low"] = df["bar_low"].fillna(df["price"] - 0.25)
    return df


def run_backtest(dataset_path: Path, label: str, config: BacktestConfig):
    print(f"\n{'='*70}")
    print(f"BACKTEST {label} — {dataset_path.name}")
    print(f"{'='*70}")

    bt = BacktestFramework(dataset_path, config=config)
    bt.load()
    jsonl_dir = _REPO_ROOT / f"DATA/{label}"
    bt.df = enrich_with_bar_ohlc(bt.df, jsonl_dir, label)
    df = bt.df
    print(f"Dataset : {len(df)} bars (enrichi avec bar_high/bar_low depuis JSONL)")
    print()

    header = f"{'model':32s} {'N':>5s} {'PF':>7s} {'EV(t)':>7s} {'WR%':>6s} {'MDD':>7s} {'p':>7s} {'verdict':>8s}"
    print(header)
    print("-" * len(header))

    results = []
    for model in MODELS:
        try:
            report = bt.run(model)
            m = report.metrics_oos
            line = (
                f"{model.name:32s} "
                f"{m.n_trades:>5d} "
                f"{m.profit_factor:>7.2f} "
                f"{m.expectancy_ticks:>7.2f} "
                f"{m.win_rate*100:>5.1f}% "
                f"{m.max_drawdown_ticks:>7.1f} "
                f"{m.p_value_mc:>7.3f} "
                f"{report.verdict:>8s}"
            )
            print(line)
            results.append({
                "model": model.name,
                "n_trades": m.n_trades,
                "pf": m.profit_factor,
                "ev_ticks": m.expectancy_ticks,
                "win_rate": m.win_rate,
                "max_dd": m.max_drawdown_ticks,
                "p_value": m.p_value_mc,
                "degradation_pct": report.degradation_is_oos_pct,
                "verdict": report.verdict,
                "reasons": report.reasons,
            })
        except Exception as e:
            print(f"{model.name:32s} CRASH: {type(e).__name__}: {e}")
            results.append({"model": model.name, "verdict": "CRASH", "error": str(e)})

    return results


def main():
    config = BacktestConfig(
        tp_ticks=36,
        sl_ticks=20,
        horizon_bars=60,
        tick_size=0.25,
        tick_value_usd=1.25,
        commission_ticks_per_rt=0.5,
        cooldown_bars=60,
        n_folds=5,
        # embargo_bars s'applique sur la liste des TRADES (pas des barres).
        # Avec cooldown_bars=60, chaque trade est deja espace de >= 60 barres donc
        # leakage par label overlap (horizon=60) est deja bloque. embargo=1 trade suffit.
        embargo_bars=1,
        n_permutations=500,  # reduit pour gagner du temps
        n_trials_optuna=10,  # approx 10 strategies testees
        min_trades=30,  # relaxed for 12-day dataset
        min_profit_factor=1.3,
        min_expectancy_ticks=2.0,
        max_degradation_pct=30.0,
        max_p_value=0.05,
    )

    es_results = run_backtest(_REPO_ROOT / "DATA/DATASETS/ES_dataset_v2.parquet",
                                "ES", config)
    nq_results = run_backtest(_REPO_ROOT / "DATA/DATASETS/NQ_dataset_v2.parquet",
                                "NQ", config)

    # Sauvegarder les resultats
    out_dir = _REPO_ROOT / "DATA/BACKTEST"
    out_dir.mkdir(parents=True, exist_ok=True)
    es_df = pd.DataFrame(es_results)
    nq_df = pd.DataFrame(nq_results)
    es_df.to_csv(out_dir / "es_backtest_10models.csv", index=False)
    nq_df.to_csv(out_dir / "nq_backtest_10models.csv", index=False)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nES GO models: {es_df[es_df['verdict'] == 'GO']['model'].tolist()}")
    print(f"NQ GO models: {nq_df[nq_df['verdict'] == 'GO']['model'].tolist()}")
    print(f"\nResults saved to {out_dir}/")


if __name__ == "__main__":
    main()
