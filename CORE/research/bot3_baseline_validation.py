"""Bot 3 — Backtest cohérence baseline.

Verifie que les chiffres baseline du PROMPT_CLAUDE_CODE_BOT3_FINAL.md tiennent
avec les params d'execution reels :
  - SL = 400t NQ / 160t ES
  - Trailing activation = 120t / 48t
  - Trailing distance = 80t / 32t
  - Timeout = 60 min
  - Entry au touch + 1 (clôture barre de contact)

Tier 1 only (5 niveaux). Tous symboles, toutes sessions.
Compare PF/win_rate/n au baseline du doc.

Usage : python -X utf8 CORE/research/bot3_baseline_validation.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "DATA" / "DATASETS" / "v4_enriched"

# Tick size + value
TICK_SIZE = 0.25
TICK_VALUE = {"NQ": 0.50, "ES": 1.25}  # micros

# Params Bot 3
SL_TICKS = {"NQ": 400, "ES": 160}
TRAIL_ACT = {"NQ": 120, "ES": 48}
TRAIL_DIST = {"NQ": 80, "ES": 32}
TIMEOUT_MIN = 60
TP_CAP = {"NQ": 800, "ES": 320}

# Baseline du doc (à valider)
BASELINE = {
    "SINGLE_PRINT": {"NQ": (70.1, 2.61, 26046), "ES": (69.1, 2.53, 27112)},
    "IB_LOW":       {"NQ": (59.6, 1.85, 6806),  "ES": (58.9, 1.91, 11827)},
    "MQ_PUT_0DTE":  {"NQ": (57.5, 1.80, 497),   "ES": (58.0, 2.00, 343)},
    "OPEN_830":     {"NQ": (54.3, 1.12, 42437), "ES": (56.7, 1.25, 79646)},
    "OPEN_930":     {"NQ": (53.4, 1.19, 34646), "ES": (56.7, 1.26, 71603)},
}

# Niveaux Tier 1 + side + proximity
TIER1 = {
    "SINGLE_PRINT": {"col": "dist_single_print_nearest_pct", "prox": 0.02, "side": "REJECTION"},
    "IB_LOW":       {"col": "dist_ib_low_pct",                "prox": 0.05, "side": "LONG"},
    "MQ_PUT_0DTE":  {"col": "dist_mq_put_0dte_pct",           "prox": 0.05, "side": "LONG"},
    "OPEN_830":     {"col": "dist_open_830_pct",              "prox": 0.05, "side": "REJECTION"},
    "OPEN_930":     {"col": "dist_open_930_pct",              "prox": 0.05, "side": "REJECTION"},
}


@dataclass
class TradeResult:
    symbol: str
    level: str
    side: str
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    pnl_ticks: float
    exit_reason: str  # TP_CAP, SL, TRAILING, TIMEOUT


def load_parquet_all(symbol: str) -> pd.DataFrame:
    """Charge tout V4 enriched pour un symbole."""
    sym_path = DATA_ROOT / f"symbol={symbol}.c.0"
    files = sorted(sym_path.glob("year=*/month=*/data.parquet"))
    if not files:
        raise FileNotFoundError(f"Aucun parquet pour {symbol}")
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        # Normaliser ts_event en tz-naive UTC pour eviter conflit
        if "ts_event" in df.columns:
            ts = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
            df["ts_event"] = ts.dt.tz_localize(None)
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def detect_contacts(df: pd.DataFrame, level_name: str, level_def: dict) -> list[int]:
    """Detect bar indices où le prix touche le niveau (dist <= proximity)."""
    col = level_def["col"]
    prox = level_def["prox"]
    if col not in df.columns:
        print(f"  WARN: colonne {col} absente, skip {level_name}")
        return []
    dist = df[col].abs()
    mask = dist <= prox
    # dedup : pas 2 contacts consecutifs (anti repeated touch)
    indices = []
    last = -10
    for i in df.index[mask]:
        if i - last >= 5:  # >=5 bars entre 2 contacts
            indices.append(int(i))
            last = int(i)
    return indices


def determine_side(df: pd.DataFrame, idx: int, level_def: dict) -> Optional[str]:
    """Determine direction du trade au contact."""
    side_def = level_def["side"]
    if side_def in ("LONG", "SHORT"):
        return side_def
    if side_def == "REJECTION":
        # Si dist < 0 → prix au-dessus → rejection = SHORT
        # Si dist > 0 → prix en-dessous → rejection = LONG
        col = level_def["col"]
        d = df.iloc[idx][col]
        if pd.isna(d) or d == 0:
            return None
        return "SHORT" if d < 0 else "LONG"
    return None


def simulate_trade(df: pd.DataFrame, entry_idx: int, side: str, symbol: str) -> Optional[TradeResult]:
    """Simule un trade depuis entry_idx+1 (clôture barre suivante)."""
    if entry_idx + 1 >= len(df):
        return None
    entry_idx_real = entry_idx + 1
    entry_price = float(df.iloc[entry_idx_real]["close"])

    sl_ticks = SL_TICKS[symbol]
    trail_act = TRAIL_ACT[symbol]
    trail_dist = TRAIL_DIST[symbol]
    tp_cap = TP_CAP[symbol]

    direction = 1 if side == "LONG" else -1
    sl_price = entry_price - direction * sl_ticks * TICK_SIZE
    tp_cap_price = entry_price + direction * tp_cap * TICK_SIZE

    trailing_active = False
    best_price = entry_price

    for j in range(1, TIMEOUT_MIN + 1):
        bar_idx = entry_idx_real + j
        if bar_idx >= len(df):
            break
        h = float(df.iloc[bar_idx]["high"])
        l = float(df.iloc[bar_idx]["low"])

        # SL hit ?
        if direction == 1 and l <= sl_price:
            return TradeResult(symbol, "", side, entry_idx_real, bar_idx,
                               entry_price, sl_price,
                               (sl_price - entry_price) / TICK_SIZE * direction,
                               "SL")
        if direction == -1 and h >= sl_price:
            return TradeResult(symbol, "", side, entry_idx_real, bar_idx,
                               entry_price, sl_price,
                               (sl_price - entry_price) / TICK_SIZE * direction,
                               "SL")

        # TP cap ?
        if direction == 1 and h >= tp_cap_price:
            return TradeResult(symbol, "", side, entry_idx_real, bar_idx,
                               entry_price, tp_cap_price,
                               tp_cap, "TP_CAP")
        if direction == -1 and l <= tp_cap_price:
            return TradeResult(symbol, "", side, entry_idx_real, bar_idx,
                               entry_price, tp_cap_price,
                               tp_cap, "TP_CAP")

        # Update best price
        if direction == 1:
            best_price = max(best_price, h)
        else:
            best_price = min(best_price, l)

        # Trailing activation
        favorable_ticks = (best_price - entry_price) / TICK_SIZE * direction
        if not trailing_active and favorable_ticks >= trail_act:
            trailing_active = True

        # Trailing stop update
        if trailing_active:
            new_sl = best_price - direction * trail_dist * TICK_SIZE
            # Tighten only
            if direction == 1 and new_sl > sl_price:
                sl_price = new_sl
            elif direction == -1 and new_sl < sl_price:
                sl_price = new_sl

    # Timeout
    final_idx = min(entry_idx_real + TIMEOUT_MIN, len(df) - 1)
    final_price = float(df.iloc[final_idx]["close"])
    pnl = (final_price - entry_price) / TICK_SIZE * direction
    reason = "TRAILING" if trailing_active else "TIMEOUT"
    return TradeResult(symbol, "", side, entry_idx_real, final_idx,
                       entry_price, final_price, pnl, reason)


def backtest_level(df: pd.DataFrame, symbol: str, level_name: str, level_def: dict) -> dict:
    """Backtest un niveau Tier 1 sur tout le dataframe."""
    contacts = detect_contacts(df, level_name, level_def)
    trades = []
    for idx in contacts:
        side = determine_side(df, idx, level_def)
        if side is None:
            continue
        tr = simulate_trade(df, idx, side, symbol)
        if tr is not None:
            tr.level = level_name
            trades.append(tr)
    if not trades:
        return {"n": 0, "win_rate": 0, "pf": 0, "avg_pnl_ticks": 0,
                "exit_reasons": {}, "median_duration_min": 0}
    pnls = np.array([t.pnl_ticks for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
    win_rate = (pnls > 0).mean() * 100
    durations = [t.exit_idx - t.entry_idx for t in trades]
    exit_reasons = {}
    for t in trades:
        exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1
    return {
        "n": len(trades),
        "win_rate": round(win_rate, 1),
        "pf": round(pf, 2),
        "avg_pnl_ticks": round(pnls.mean(), 1),
        "median_duration_min": int(np.median(durations)),
        "exit_reasons": exit_reasons,
    }


def main():
    print("=" * 90)
    print("Bot 3 — Backtest cohérence Tier 1 vs baseline doc")
    print("=" * 90)
    for symbol in ("NQ", "ES"):
        print(f"\n### {symbol} ###")
        try:
            df = load_parquet_all(symbol)
        except Exception as e:
            print(f"  ERREUR chargement: {e}")
            continue
        print(f"  Loaded {len(df):,} bars from {df['ts_event'].iloc[0]} to {df['ts_event'].iloc[-1]}")
        print(f"\n  {'Niveau':<18} {'n':>6} {'win%':>6} {'PF':>6} {'avg_t':>7} {'dur':>5} | baseline")
        for level_name, level_def in TIER1.items():
            res = backtest_level(df, symbol, level_name, level_def)
            base = BASELINE.get(level_name, {}).get(symbol, (None, None, None))
            base_str = f"rej={base[0]} pf={base[1]} n={base[2]}" if base[0] else "?"
            print(f"  {level_name:<18} {res['n']:>6} {res['win_rate']:>6.1f} {res['pf']:>6.2f} {res['avg_pnl_ticks']:>7.1f} {res['median_duration_min']:>5} | {base_str}")
            print(f"    exit_reasons: {res['exit_reasons']}")
    print("\n" + "=" * 90)
    print("Verdict : si PF observé tient à ±0.3 de baseline → cohérent → GO Phase 2")
    print("Si PF observé < baseline -0.5 → SL trop large → calibration nécessaire")
    print("=" * 90)


if __name__ == "__main__":
    main()
