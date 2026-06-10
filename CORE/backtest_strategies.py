"""
Backtest rigoureux V2 des strategies MIA (17/04/2026)

Fix post-agent-review (17/04/2026) :
  [C1] random_baseline respecte daily_cap (meme contrainte que strat)
  [C2] random_baseline respecte ratio BUY/SELL empirique de la strat
  [C3] random_baseline utilise distribution realiste de sl_ticks (bootstrap)
  [C4] filtre session US RTH (09:30-16:00 ET) dans run_strategy
  [C5] estimate_trading_days compte sessions US (pas jours UTC)
  [I4] Baseline moyenne sur 100 seeds -> IC 95% + p-value
  [I3] Penalite slippage -0.1R par trade systematique
  [S3] Tests unitaires simulate_bracket (cf test_backtest_strategies.py)

USAGE :
    python -X utf8 CORE/backtest_strategies.py           # full
    python -X utf8 CORE/backtest_strategies.py --csv     # + export CSV
    python -X utf8 CORE/backtest_strategies.py --no-slip # desactiver slippage
    python -X utf8 CORE/backtest_strategies.py --seeds 20  # moins de seeds (dev)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rolling_features import RollingFeatures  # noqa: E402
from strategies import (  # noqa: E402
    BattleNavaleStrategy,
    DeltaAccumSupportStrategy,
    DivOptimStrategy,
    DoubleTopBottomStrategy,
    EdgeImbalanceNQStrategy,
    ESContrarianShortStrategy,
    ESTrendVPOCLongStrategy,
    NQPullbackLongStrategy,
    ReversalRareStrategy,
    Strategy,
    TrendHVNReboundStrategy,
    WinnerMorningSellStrategy,
)

DATA_ROOT = Path("DATA")
OUTPUT_DIR = Path("DATA/BACKTEST_STRATEGIES")
TICK_SIZE = 0.25
SLIPPAGE_R_PENALTY = 0.1  # ~0.5-1 tick slip per trade en R
RTH_START_MIN = 9 * 60 + 30   # 09:30 ET
RTH_END_MIN = 16 * 60          # 16:00 ET


# ─────────────────────────────────────────────────────────────────────────────
# I/O + SESSION US
# ─────────────────────────────────────────────────────────────────────────────

def load_jsonl_dir(symbol: str) -> pd.DataFrame:
    rows = []
    for f in sorted((DATA_ROOT / symbol).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
    for col in ["price", "bar_high", "bar_low", "atr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def add_session_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute ts_et (Timestamp ET DST-aware), session_date (date ET), is_rth."""
    if "ts" not in df.columns:
        df["is_rth"] = False
        df["session_date"] = pd.NaT
        return df
    ts_utc = pd.to_datetime(pd.to_numeric(df["ts"], errors="coerce"),
                            unit="ms", utc=True, errors="coerce")
    ts_et = ts_utc.dt.tz_convert("America/New_York")
    minutes_et = ts_et.dt.hour * 60 + ts_et.dt.minute
    df["is_rth"] = (minutes_et >= RTH_START_MIN) & (minutes_et < RTH_END_MIN)
    # Pour la session date : si hour_et >= 18 → next trading day (CME), sinon same day
    shift = (ts_et.dt.hour >= 18).astype("Int64")
    session_date = ts_et.dt.normalize() + pd.to_timedelta(
        shift.fillna(0).astype(int), unit="D"
    )
    df["session_date"] = session_date.dt.tz_localize(None)
    return df


def prepare(symbol: str) -> pd.DataFrame:
    print(f"  [{symbol}] Loading JSONL...", flush=True)
    df = load_jsonl_dir(symbol)
    if df.empty:
        return df
    print(f"  [{symbol}] Computing rolling features ({len(df)} bars)...", flush=True)
    df = RollingFeatures().compute(df)
    df = add_session_columns(df)
    return df


def estimate_trading_days(df: pd.DataFrame) -> int:
    """Nombre de sessions US distinctes (RTH only)."""
    if df.empty or "is_rth" not in df.columns:
        return 1
    rth = df[df["is_rth"]]
    if rth.empty:
        return 1
    return max(rth["session_date"].nunique(), 1)


# ─────────────────────────────────────────────────────────────────────────────
# BRACKET SIMULATOR
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    idx: int
    entry_pos: int
    ts_entry: Optional[float]
    direction: int
    entry_price: float
    sl_price: float
    tp_price: float
    sl_ticks: float
    outcome: str
    r: float
    bars_to_exit: int
    strategy: str
    symbol: str


def simulate_bracket(
    df: pd.DataFrame,
    entry_pos: int,
    direction: int,
    sl_ticks: float,
    rr: float,
    max_bars: int,
) -> dict:
    """Simule bracket conservateur : SL wins sur TP dans la meme barre."""
    if entry_pos >= len(df):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0,
                "entry_price": np.nan, "sl_price": np.nan, "tp_price": np.nan}
    entry = float(df["price"].iloc[entry_pos])
    if pd.isna(entry):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0,
                "entry_price": np.nan, "sl_price": np.nan, "tp_price": np.nan}
    tp_ticks = sl_ticks * rr
    if direction > 0:
        sl_price = entry - sl_ticks * TICK_SIZE
        tp_price = entry + tp_ticks * TICK_SIZE
    else:
        sl_price = entry + sl_ticks * TICK_SIZE
        tp_price = entry - tp_ticks * TICK_SIZE
    end_idx = min(entry_pos + 1 + max_bars, len(df))
    for i in range(entry_pos + 1, end_idx):
        bh = df["bar_high"].iloc[i]
        bl = df["bar_low"].iloc[i]
        if pd.isna(bh) or pd.isna(bl):
            continue
        bh, bl = float(bh), float(bl)
        if direction > 0:
            if bl <= sl_price:
                return {"outcome": "SL", "r": -1.0, "bars": i - entry_pos,
                        "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}
            if bh >= tp_price:
                return {"outcome": "TP", "r": rr, "bars": i - entry_pos,
                        "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}
        else:
            if bh >= sl_price:
                return {"outcome": "SL", "r": -1.0, "bars": i - entry_pos,
                        "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}
            if bl <= tp_price:
                return {"outcome": "TP", "r": rr, "bars": i - entry_pos,
                        "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}
    if end_idx <= entry_pos + 1:
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0,
                "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}
    final = df["price"].iloc[end_idx - 1]
    if pd.isna(final):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": end_idx - entry_pos,
                "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}
    if direction > 0:
        r = (float(final) - entry) / (sl_ticks * TICK_SIZE)
    else:
        r = (entry - float(final)) / (sl_ticks * TICK_SIZE)
    return {"outcome": "TIMEOUT", "r": float(r), "bars": end_idx - 1 - entry_pos,
            "entry_price": entry, "sl_price": sl_price, "tp_price": tp_price}


def apply_slippage(r: float, penalty: float) -> float:
    """Applique penalite slippage en R (toujours deduite du resultat net)."""
    return r - penalty


# ─────────────────────────────────────────────────────────────────────────────
# RUN STRATEGY — avec filtre RTH [C4]
# ─────────────────────────────────────────────────────────────────────────────

def run_strategy(strat: Strategy, df: pd.DataFrame, symbol: str,
                 daily_cap: int = 5,
                 rth_only: bool = True,
                 apply_slip: bool = True) -> list[Trade]:
    """Execute strat sur df et retourne trades. Filtre RTH applique."""
    trades: list[Trade] = []
    signals = strat.signals(df)
    cfg = strat.config
    signal_positions = np.where(signals.values != 0)[0]

    # Session date par barre pour daily_cap
    if "session_date" not in df.columns:
        df = add_session_columns(df)
    session_dates = df["session_date"].to_numpy()
    is_rth = df["is_rth"].to_numpy() if "is_rth" in df.columns else np.ones(len(df), dtype=bool)

    day_counts: dict = {}

    for signal_pos in signal_positions:
        entry_pos = signal_pos + cfg.entry_delay
        if entry_pos >= len(df):
            continue

        # [C4] Filtre RTH : le signal ET l'entry doivent etre en session US
        if rth_only:
            if not bool(is_rth[signal_pos]):
                continue
            if not bool(is_rth[entry_pos]):
                continue

        # Confirmation a l'entry (rvol etc.)
        if not strat.confirm_at_entry(df, entry_pos):
            continue

        # Daily cap par session US
        d = session_dates[entry_pos]
        if pd.isna(d):
            continue
        cur = day_counts.get(d, 0)
        if cur >= daily_cap:
            continue
        day_counts[d] = cur + 1

        direction = int(signals.iloc[signal_pos])
        sl_t = strat.sl_ticks(df, signal_pos)
        res = simulate_bracket(df, entry_pos, direction, sl_t, cfg.rr, cfg.max_bars)
        if res["outcome"] == "NO_DATA":
            continue

        r_final = float(res["r"])
        if apply_slip:
            r_final = apply_slippage(r_final, SLIPPAGE_R_PENALTY)

        ts_e = None
        if "ts" in df.columns:
            ts_val = df["ts"].iloc[entry_pos]
            ts_e = float(ts_val) if pd.notna(ts_val) else None

        trades.append(Trade(
            idx=int(df.index[signal_pos]),
            entry_pos=int(entry_pos),
            ts_entry=ts_e,
            direction=direction,
            entry_price=float(res["entry_price"]),
            sl_price=float(res["sl_price"]),
            tp_price=float(res["tp_price"]),
            sl_ticks=float(sl_t),
            outcome=str(res["outcome"]),
            r=r_final,
            bars_to_exit=int(res["bars"]),
            strategy=strat.name,
            symbol=symbol,
        ))
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# BASELINE RANDOM FIXE — avec [C1], [C2], [C3]
# ─────────────────────────────────────────────────────────────────────────────

def random_baseline_realistic(
    df: pd.DataFrame,
    strat_trades: list[Trade],
    rr: float,
    max_bars: int,
    symbol: str,
    seed: int,
    daily_cap: int = 5,
    rth_only: bool = True,
    apply_slip: bool = True,
) -> list[Trade]:
    """Baseline respectant les contraintes strat :
       - meme n_trades
       - meme ratio BUY/SELL empirique [C2]
       - distribution sl_ticks bootstrap [C3]
       - daily_cap applique [C1]
       - RTH only [C4]
    """
    n = len(strat_trades)
    if n == 0 or df.empty:
        return []

    rng = np.random.default_rng(seed)

    # [C2] Ratio empirique BUY/SELL
    n_buy = sum(1 for t in strat_trades if t.direction > 0)
    buy_ratio = n_buy / n if n > 0 else 0.5

    # [C3] Bootstrap sl_ticks empirique
    sl_ticks_empirical = np.array([t.sl_ticks for t in strat_trades])

    # [C4] RTH filter - on ne tire que dans les barres RTH
    if "is_rth" not in df.columns:
        df = add_session_columns(df)
    valid_pool = np.where(df["is_rth"].to_numpy() &
                           (np.arange(len(df)) >= 10) &
                           (np.arange(len(df)) < len(df) - max_bars - 1))[0]
    if len(valid_pool) == 0:
        return []

    # Tire 3x n pour avoir marge apres filtrage daily_cap
    n_candidates = min(n * 4, len(valid_pool))
    candidate_positions = rng.choice(valid_pool, size=n_candidates, replace=False)
    candidate_positions.sort()

    session_dates = df["session_date"].to_numpy()
    day_counts: dict = {}

    trades: list[Trade] = []
    for pos in candidate_positions:
        if len(trades) >= n:
            break
        d = session_dates[pos]
        if pd.isna(d):
            continue
        cur = day_counts.get(d, 0)
        if cur >= daily_cap:
            continue

        direction = int(rng.choice([1, -1], p=[buy_ratio, 1 - buy_ratio]))
        sl_t = float(rng.choice(sl_ticks_empirical))
        res = simulate_bracket(df, int(pos), direction, sl_t, rr, max_bars)
        if res["outcome"] == "NO_DATA":
            continue

        day_counts[d] = cur + 1

        r_final = float(res["r"])
        if apply_slip:
            r_final = apply_slippage(r_final, SLIPPAGE_R_PENALTY)

        trades.append(Trade(
            idx=int(pos), entry_pos=int(pos), ts_entry=None,
            direction=direction,
            entry_price=float(res["entry_price"]),
            sl_price=float(res["sl_price"]),
            tp_price=float(res["tp_price"]),
            sl_ticks=float(sl_t),
            outcome=str(res["outcome"]),
            r=r_final,
            bars_to_exit=int(res["bars"]),
            strategy="RANDOM_BASELINE",
            symbol=symbol,
        ))
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats(trades: list[Trade], n_days: int) -> dict:
    if not trades:
        return {"n": 0}
    r = pd.Series([t.r for t in trades])
    wins = r[r > 0]
    losses = r[r < 0]
    total_win = float(wins.sum()) if len(wins) else 0.0
    total_loss = float(-losses.sum()) if len(losses) else 0.0
    pf = total_win / total_loss if total_loss > 0 else float("inf")
    wr = len(wins) / len(r)
    cum = r.cumsum()
    running_max = cum.cummax()
    dd = cum - running_max
    max_dd = float(dd.min()) if len(dd) else 0.0
    if r.std() > 0:
        trades_per_day = len(r) / max(n_days, 1)
        sharpe_proxy = float(r.mean() / r.std() * np.sqrt(trades_per_day))
    else:
        sharpe_proxy = 0.0
    return {
        "n": len(trades),
        "tp": sum(1 for t in trades if t.outcome == "TP"),
        "sl": sum(1 for t in trades if t.outcome == "SL"),
        "timeout": sum(1 for t in trades if t.outcome == "TIMEOUT"),
        "wr": wr,
        "pf": pf,
        "ev_r": float(r.mean()),
        "ev_r_std": float(r.std()) if len(r) > 1 else 0.0,
        "total_r": float(r.sum()),
        "max_dd_r": max_dd,
        "sharpe_proxy": sharpe_proxy,
        "avg_bars": float(pd.Series([t.bars_to_exit for t in trades]).mean()),
        "avg_sl_ticks": float(pd.Series([t.sl_ticks for t in trades]).mean()),
        "trades_per_day": len(r) / max(n_days, 1),
    }


def fmt_stats(label: str, s: dict) -> str:
    if s.get("n", 0) == 0:
        return f"  {label:50s}  n=0"
    pf_str = f"{s['pf']:.2f}" if np.isfinite(s["pf"]) else "inf"
    return (
        f"  {label:50s}  "
        f"n={s['n']:4d}  WR={s['wr']:.1%}  PF={pf_str:>5s}  "
        f"EV={s['ev_r']:+.2f}R  totR={s['total_r']:+6.0f}  "
        f"DD={s['max_dd_r']:+6.1f}  Sh={s['sharpe_proxy']:+.2f}  "
        f"t/j={s['trades_per_day']:.1f}"
    )


def multi_seed_baseline(
    df: pd.DataFrame,
    strat_trades: list[Trade],
    rr: float,
    max_bars: int,
    symbol: str,
    n_days: int,
    n_seeds: int = 100,
    daily_cap: int = 5,
    apply_slip: bool = True,
) -> dict:
    """Moyenne stats sur N seeds. Retourne pf/ev mean + std + p-value du strat."""
    pfs, evs, totrs = [], [], []
    strat_stats = compute_stats(strat_trades, n_days)
    if strat_stats.get("n", 0) == 0:
        return {}

    print(f"    Running {n_seeds} seeds...", flush=True)
    for seed in range(n_seeds):
        rand_trades = random_baseline_realistic(
            df, strat_trades, rr, max_bars, symbol, seed,
            daily_cap=daily_cap, apply_slip=apply_slip,
        )
        if not rand_trades:
            continue
        rs = compute_stats(rand_trades, n_days)
        if rs.get("n", 0) > 0 and np.isfinite(rs.get("pf", 0)):
            pfs.append(rs["pf"])
            evs.append(rs["ev_r"])
            totrs.append(rs["total_r"])

    if not pfs:
        return {}

    pf_arr = np.array(pfs)
    ev_arr = np.array(evs)
    totr_arr = np.array(totrs)

    strat_pf = strat_stats["pf"] if np.isfinite(strat_stats.get("pf", 0)) else None
    strat_ev = strat_stats["ev_r"]
    strat_totr = strat_stats["total_r"]

    # p-value empirique : % des seeds ayant un PF >= strat_pf
    if strat_pf is not None:
        p_pf = float((pf_arr >= strat_pf).mean())
    else:
        p_pf = np.nan
    p_ev = float((ev_arr >= strat_ev).mean())
    p_totr = float((totr_arr >= strat_totr).mean())

    return {
        "n_seeds": len(pfs),
        "baseline_pf_mean": float(pf_arr.mean()),
        "baseline_pf_std": float(pf_arr.std()),
        "baseline_pf_95ci_low": float(np.quantile(pf_arr, 0.025)),
        "baseline_pf_95ci_hi": float(np.quantile(pf_arr, 0.975)),
        "baseline_ev_mean": float(ev_arr.mean()),
        "baseline_ev_std": float(ev_arr.std()),
        "baseline_totr_mean": float(totr_arr.mean()),
        "baseline_totr_std": float(totr_arr.std()),
        "strat_pf": strat_pf,
        "strat_ev": strat_ev,
        "strat_totr": strat_totr,
        "p_value_pf": p_pf,    # fraction seeds battant la strat
        "p_value_ev": p_ev,
        "p_value_totr": p_totr,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD
# ─────────────────────────────────────────────────────────────────────────────

def split_train_test(df: pd.DataFrame, train_pct: float = 0.7) -> tuple:
    if df.empty:
        return df, df
    split_idx = int(len(df) * train_pct)
    return (df.iloc[:split_idx].reset_index(drop=True),
            df.iloc[split_idx:].reset_index(drop=True))


def kfold_chronological(df: pd.DataFrame, k: int = 3) -> list[tuple]:
    """Retourne k folds : (train, test) avec test = chaque 1/k segment chrono."""
    folds = []
    chunk_size = len(df) // k
    for i in range(k):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < k - 1 else len(df)
        test = df.iloc[start:end].reset_index(drop=True)
        train = pd.concat([df.iloc[:start], df.iloc[end:]]).reset_index(drop=True)
        folds.append((train, test))
    return folds


# ─────────────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    print("\n" + "=" * 95)
    print(f"  {title}")
    print("=" * 95)


def export_trades_csv(trades: list[Trade], output_file: Path) -> None:
    if not trades:
        return
    output_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(t) for t in trades]).to_csv(output_file, index=False)


def run_backtest_for_symbol(
    symbol: str, strategies: list[Strategy],
    export_csv: bool = False, n_seeds: int = 100,
    apply_slip: bool = True,
) -> dict:
    df_full = prepare(symbol)
    if df_full.empty:
        return {}
    df_train, df_test = split_train_test(df_full, train_pct=0.7)

    days_full = estimate_trading_days(df_full)
    days_train = estimate_trading_days(df_train)
    days_test = estimate_trading_days(df_test)

    rth_full = df_full["is_rth"].sum() if "is_rth" in df_full.columns else 0
    print(f"\n  [{symbol}] Dataset: {len(df_full)} bars ({rth_full} RTH), "
          f"{days_full} US sessions")
    print(f"  [{symbol}] Train: {days_train} sessions US, Test: {days_test} sessions US")

    results = {"symbol": symbol, "strategies": {}}

    for strat in strategies:
        if not strat.can_trade_symbol(symbol):
            print(f"\n  [{symbol}] SKIP {strat.name} (pas applicable)")
            continue
        print_header(f"{symbol} — {strat.name}")

        # FULL
        trades_full = run_strategy(strat, df_full, symbol,
                                    daily_cap=strat.config.max_trades_per_day,
                                    rth_only=True, apply_slip=apply_slip)
        stats_full = compute_stats(trades_full, days_full)
        print(fmt_stats(f"FULL ({days_full}j US)", stats_full))

        # TRAIN
        trades_train = run_strategy(strat, df_train, symbol,
                                     daily_cap=strat.config.max_trades_per_day,
                                     rth_only=True, apply_slip=apply_slip)
        stats_train = compute_stats(trades_train, days_train)
        print(fmt_stats(f"TRAIN ({days_train}j)", stats_train))

        # TEST
        trades_test = run_strategy(strat, df_test, symbol,
                                    daily_cap=strat.config.max_trades_per_day,
                                    rth_only=True, apply_slip=apply_slip)
        stats_test = compute_stats(trades_test, days_test)
        print(fmt_stats(f"TEST  ({days_test}j)", stats_test))

        # BASELINE multi-seed sur TRAIN (plus robuste que FULL)
        if stats_train.get("n", 0) >= 30:
            print(f"\n  BASELINE RANDOM ({n_seeds} seeds, meme contraintes que strat) :")
            baseline = multi_seed_baseline(
                df_train, trades_train, strat.config.rr, strat.config.max_bars,
                symbol, days_train, n_seeds=n_seeds,
                daily_cap=strat.config.max_trades_per_day,
                apply_slip=apply_slip,
            )
            if baseline:
                print(f"    Baseline PF : {baseline['baseline_pf_mean']:.2f} "
                      f"+/- {baseline['baseline_pf_std']:.2f}  "
                      f"[95% IC: {baseline['baseline_pf_95ci_low']:.2f} - "
                      f"{baseline['baseline_pf_95ci_hi']:.2f}]")
                print(f"    Strat PF    : {baseline['strat_pf']:.2f}")
                print(f"    p-value PF  : {baseline['p_value_pf']:.3f}  "
                      f"(fraction seeds battant la strat)")
                print(f"    Baseline totR mean  : "
                      f"{baseline['baseline_totr_mean']:+.1f} "
                      f"+/- {baseline['baseline_totr_std']:.1f}")
                print(f"    Strat totR   : {baseline['strat_totr']:+.1f}")
                print(f"    p-value totR: {baseline['p_value_totr']:.3f}")

                # Verdict
                if baseline["p_value_pf"] < 0.05:
                    print(f"    [GATE OK] p-value PF < 0.05 : edge significatif")
                else:
                    print(f"    [GATE FAIL] p-value PF >= 0.05 : edge NON significatif "
                          f"vs baseline")
        else:
            baseline = {}
            print(f"\n  BASELINE skipped : n_train={stats_train.get('n', 0)} < 30")

        # Degradation train -> test
        if stats_train.get("pf") and stats_test.get("pf"):
            pf_train = stats_train["pf"]
            pf_test = stats_test["pf"]
            if np.isfinite(pf_train) and np.isfinite(pf_test) and pf_train > 0:
                deg = 100.0 * (pf_test - pf_train) / pf_train
                status = "OK" if pf_test >= 1.0 else "FAIL"
                print(f"\n  Walk-forward PF Train -> Test : "
                      f"{pf_train:.2f} -> {pf_test:.2f} ({deg:+.1f}%)  [{status}]")

        if export_csv:
            output_file = OUTPUT_DIR / f"{symbol}_{strat.name}_trades.csv"
            export_trades_csv(trades_full, output_file)
            print(f"  CSV: {output_file}")

        results["strategies"][strat.name] = {
            "full": stats_full,
            "train": stats_train,
            "test": stats_test,
            "baseline": baseline,
        }

    return results


def main():
    export_csv = "--csv" in sys.argv
    apply_slip = "--no-slip" not in sys.argv
    n_seeds = 100
    if "--seeds" in sys.argv:
        idx = sys.argv.index("--seeds")
        if idx + 1 < len(sys.argv):
            n_seeds = int(sys.argv[idx + 1])

    strat_filter: Optional[str] = None
    if "--strategy" in sys.argv:
        idx = sys.argv.index("--strategy")
        if idx + 1 < len(sys.argv):
            strat_filter = sys.argv[idx + 1]

    print_header("BACKTEST STRATEGIES MIA V2 — POST-REVIEW FIX (17/04/2026)")
    print(f"  Slippage : {'-0.1R/trade' if apply_slip else 'OFF'}")
    print(f"  Baseline : {n_seeds} seeds, cap-aware, ratio BUY/SELL empirique, SL bootstrap")
    print(f"  Filtre RTH 09:30-16:00 ET (DST-aware)")
    print(f"  Gate GO : p-value PF < 0.05 vs baseline random")

    all_results = {}
    for symbol in ["ES", "NQ"]:
        strategies: list[Strategy] = []
        if strat_filter is None or strat_filter == "DivOptim":
            strategies.append(DivOptimStrategy(symbol=symbol))
        if strat_filter is None or strat_filter == "DoubleTopBottom":
            strategies.append(DoubleTopBottomStrategy(symbol=symbol))
        if strat_filter is None or strat_filter == "BattleNavale":
            strategies.append(BattleNavaleStrategy(symbol=symbol, use_full_features=False))
        if strat_filter is None or strat_filter == "TrendHVNRebound":
            strategies.append(TrendHVNReboundStrategy(symbol=symbol))
        if strat_filter is None or strat_filter == "DeltaAccumSupport":
            strategies.append(DeltaAccumSupportStrategy(symbol=symbol))
        if strat_filter is None or strat_filter == "WinnerMorningSell":
            strategies.append(WinnerMorningSellStrategy(symbol=symbol))
        if strat_filter is None or strat_filter == "ReversalRare":
            strategies.append(ReversalRareStrategy(symbol=symbol))
        if strat_filter is None or strat_filter == "EdgeImbalanceNQ":
            edge = EdgeImbalanceNQStrategy(symbol=symbol)
            if edge.can_trade_symbol(symbol):
                strategies.append(edge)
        # Pattern Discovery strategies (17/04 post-leakage)
        if strat_filter is None or strat_filter == "ESContrarianShort":
            s = ESContrarianShortStrategy(symbol=symbol)
            if s.can_trade_symbol(symbol):
                strategies.append(s)
        if strat_filter is None or strat_filter == "ESTrendVPOCLong":
            s = ESTrendVPOCLongStrategy(symbol=symbol)
            if s.can_trade_symbol(symbol):
                strategies.append(s)
        if strat_filter is None or strat_filter == "NQPullbackLong":
            s = NQPullbackLongStrategy(symbol=symbol)
            if s.can_trade_symbol(symbol):
                strategies.append(s)
        res = run_backtest_for_symbol(symbol, strategies, export_csv,
                                       n_seeds=n_seeds, apply_slip=apply_slip)
        if res:
            all_results[symbol] = res

    # Resume final
    print_header("RESUME FINAL + DECISION GATE")
    print(f"  {'Symbol':6s}  {'Strategy':18s}  {'Split':7s}  "
          f"{'n':4s}  {'PF':6s}  {'totR':7s}  {'BaselPF':8s}  "
          f"{'pval_PF':8s}  {'Verdict':12s}")
    print(f"  {'-' * 90}")
    for sym, res in all_results.items():
        for name, data in res["strategies"].items():
            baseline = data.get("baseline", {})
            base_pf = baseline.get("baseline_pf_mean")
            p_pf = baseline.get("p_value_pf")
            for split_name in ["full", "train", "test"]:
                s = data[split_name]
                if s.get("n", 0) == 0:
                    continue
                pf = f"{s['pf']:.2f}" if np.isfinite(s["pf"]) else "inf"
                bpf_str = f"{base_pf:.2f}" if (split_name == "train" and base_pf) else "-"
                pval_str = f"{p_pf:.3f}" if (split_name == "train" and p_pf is not None) else "-"
                verdict = ""
                if split_name == "train" and p_pf is not None:
                    verdict = "GO" if p_pf < 0.05 else "NO-GO"
                print(f"  {sym:6s}  {name:18s}  {split_name.upper():7s}  "
                      f"{s['n']:4d}  {pf:>5s}   {s['total_r']:+7.1f}  "
                      f"{bpf_str:>6s}    {pval_str:>6s}   {verdict}")
    print()


if __name__ == "__main__":
    main()
