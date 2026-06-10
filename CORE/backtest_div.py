"""
Backtest comparatif de la strategie divergence :
  A : DMP pur (div_confluence_dmp)
  B : DMP + proxies regime (div_confluence_with_regime)

Mesure le forward return 20 barres normalise par ATR pour chaque trigger de div
et compare PF/WR/EV pour differents seuils de confluence.

USAGE :
    python -X utf8 CORE/backtest_div.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rolling_features import RollingFeatures  # noqa: E402


DATA_ROOT = Path("DATA")


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
    return df


def compute_stats(returns: pd.Series) -> dict:
    """PF / WR / EV / count pour une serie de forward returns (signe-aligne)."""
    r = returns.dropna().astype(float)
    n = len(r)
    if n == 0:
        return {"n": 0, "pf": np.nan, "wr": np.nan, "ev": np.nan,
                "avg_win": np.nan, "avg_loss": np.nan}
    wins = r[r > 0]
    losses = r[r < 0]
    total_win = float(wins.sum()) if len(wins) else 0.0
    total_loss = float(-losses.sum()) if len(losses) else 0.0
    pf = total_win / total_loss if total_loss > 0 else np.inf
    wr = len(wins) / n
    ev = float(r.mean())
    return {
        "n": n,
        "pf": pf,
        "wr": wr,
        "ev": ev,
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
    }


def fmt_stats(label: str, s: dict) -> str:
    if s["n"] == 0:
        return f"  {label:55s} n=0 (pas assez de signaux)"
    pf_str = f"{s['pf']:.2f}" if np.isfinite(s["pf"]) else "inf"
    return (
        f"  {label:55s} "
        f"n={s['n']:4d}  PF={pf_str:>5s}  "
        f"WR={s['wr']:.1%}  EV={s['ev']:+.3f}  "
        f"(win={s['avg_win']:+.2f} / loss={s['avg_loss']:+.2f})"
    )


TICK_SIZE = 0.25  # ES et NQ (micro inclus)


def simulate_bracket(
    df: pd.DataFrame,
    signal_idx: int,
    direction: int,
    sl_ticks: float,
    rr: float,
    max_bars: int,
) -> dict:
    """Simule un trade bracket : entry a price de la barre, SL/TP ticks fixes.

    Returns dict avec outcome (TP/SL/TIMEOUT), r_multiple, bars_to_exit.
    Convention pessimiste : si TP et SL touches dans la meme barre, SL gagne.
    """
    entry = float(df["price"].iloc[signal_idx])
    tp_ticks = sl_ticks * rr
    if direction > 0:  # BUY
        sl_price = entry - sl_ticks * TICK_SIZE
        tp_price = entry + tp_ticks * TICK_SIZE
    else:  # SELL
        sl_price = entry + sl_ticks * TICK_SIZE
        tp_price = entry - tp_ticks * TICK_SIZE

    end_idx = min(signal_idx + 1 + max_bars, len(df))
    for i in range(signal_idx + 1, end_idx):
        bh = df["bar_high"].iloc[i]
        bl = df["bar_low"].iloc[i]
        if pd.isna(bh) or pd.isna(bl):
            continue
        bh, bl = float(bh), float(bl)
        if direction > 0:
            hit_sl = bl <= sl_price
            hit_tp = bh >= tp_price
        else:
            hit_sl = bh >= sl_price
            hit_tp = bl <= tp_price
        if hit_sl:
            return {"outcome": "SL", "r": -1.0, "bars": i - signal_idx}
        if hit_tp:
            return {"outcome": "TP", "r": rr, "bars": i - signal_idx}

    if end_idx <= signal_idx + 1:
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0}
    final = float(df["price"].iloc[end_idx - 1])
    if pd.isna(final):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": end_idx - signal_idx}
    if direction > 0:
        r_mult = (final - entry) / (sl_ticks * TICK_SIZE)
    else:
        r_mult = (entry - final) / (sl_ticks * TICK_SIZE)
    return {"outcome": "TIMEOUT", "r": float(r_mult), "bars": end_idx - 1 - signal_idx}


def run_bracket_backtest(
    df: pd.DataFrame,
    signal_mask: pd.Series,
    label: str,
    sl_buffer_ticks: float = 3.0,
    sl_min_ticks: float = 5.0,
    sl_max_ticks: float = 30.0,
    rr: float = 2.0,
    max_bars: int = 40,
) -> dict:
    """Simule tous les signaux. SL = div_at_key_level + buffer, clip [min,max]."""
    trades = []
    idx_list = df.index[signal_mask].tolist()
    for idx in idx_list:
        pos = df.index.get_loc(idx)
        dd = int(df["delta_divergence_clean"].iloc[pos])
        if dd == 0:
            continue
        raw_dist = df["div_at_key_level_ticks"].iloc[pos]
        if pd.isna(raw_dist):
            continue
        sl_ticks = float(raw_dist) + sl_buffer_ticks
        sl_ticks = max(sl_min_ticks, min(sl_max_ticks, sl_ticks))
        res = simulate_bracket(df, pos, dd, sl_ticks, rr, max_bars)
        if res["outcome"] == "NO_DATA":
            continue
        res["sl_ticks"] = sl_ticks
        res["direction"] = dd
        trades.append(res)

    if not trades:
        return {"n": 0, "label": label}

    r_series = pd.Series([t["r"] for t in trades])
    n_tp = sum(1 for t in trades if t["outcome"] == "TP")
    n_sl = sum(1 for t in trades if t["outcome"] == "SL")
    n_to = sum(1 for t in trades if t["outcome"] == "TIMEOUT")
    wins = r_series[r_series > 0]
    losses = r_series[r_series < 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf")
    wr = len(wins) / len(r_series)
    ev_r = float(r_series.mean())
    total_r = float(r_series.sum())

    return {
        "n": len(trades),
        "label": label,
        "n_tp": n_tp,
        "n_sl": n_sl,
        "n_timeout": n_to,
        "wr": wr,
        "pf": pf,
        "ev_r": ev_r,
        "total_r": total_r,
        "avg_bars": float(pd.Series([t["bars"] for t in trades]).mean()),
        "avg_sl_ticks": float(pd.Series([t["sl_ticks"] for t in trades]).mean()),
    }


def fmt_bracket(s: dict) -> str:
    if s["n"] == 0:
        return f"  {s['label']:55s} n=0"
    pf_str = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
    return (
        f"  {s['label']:55s} "
        f"n={s['n']:4d}  WR={s['wr']:.1%}  PF={pf_str:>5s}  "
        f"EV={s['ev_r']:+.2f}R  totR={s['total_r']:+.0f}  "
        f"(TP={s['n_tp']} SL={s['n_sl']} TO={s['n_timeout']}, "
        f"avgSL={s['avg_sl_ticks']:.0f}t avgBars={s['avg_bars']:.0f})"
    )


def run_backtest(symbol: str) -> None:
    print(f"\n{'=' * 78}")
    print(f"  BACKTEST DIV — {symbol}")
    print(f"{'=' * 78}")

    df = load_jsonl_dir(symbol)
    if df.empty:
        print(f"  [ERR] Aucun JSONL pour {symbol}")
        return

    print(f"  Raw rows: {len(df)}")

    rf = RollingFeatures()
    df = rf.compute(df)

    # Stats univariees
    n_div_total = int((df["delta_divergence_clean"].fillna(0) != 0).sum())
    n_bars = len(df)
    fire_rate = 100.0 * n_div_total / n_bars if n_bars > 0 else 0.0
    print(f"  Divs actives totales: {n_div_total} / {n_bars} bars = {fire_rate:.2f}%")

    if n_div_total == 0:
        print("  [WARN] Aucune div active, abort")
        return

    # Subset aux barres avec div active
    mask_div = df["delta_divergence_clean"].fillna(0) != 0
    div_df = df.loc[mask_div, [
        "delta_divergence_clean", "div_at_key_level_ticks",
        "div_confluence_dmp", "div_regime_proxy_ok",
        "div_confluence_with_regime", "div_forward_return_20b",
    ]].copy()

    print(f"\n  --- BASELINE (toutes les divs, sans filtre) ---")
    baseline = compute_stats(div_df["div_forward_return_20b"])
    print(fmt_stats("ALL divs", baseline))

    print(f"\n  --- A : DMP PUR (div_confluence_dmp) ---")
    for threshold in [1, 2, 3, 4]:
        subset = div_df[div_df["div_confluence_dmp"] >= threshold]
        s = compute_stats(subset["div_forward_return_20b"])
        print(fmt_stats(f"div_confluence_dmp >= {threshold}", s))

    print(f"\n  --- B : DMP + PROXIES REGIME (div_confluence_with_regime) ---")
    for threshold in [1, 2, 3, 4, 5]:
        subset = div_df[div_df["div_confluence_with_regime"] >= threshold]
        s = compute_stats(subset["div_forward_return_20b"])
        print(fmt_stats(f"div_confluence_with_regime >= {threshold}", s))

    print(f"\n  --- COMPARAISON DIRECTE (seuil equivalent : DMP>=3 vs REGIME>=4) ---")
    sa = compute_stats(div_df.loc[div_df["div_confluence_dmp"] >= 3,
                                   "div_forward_return_20b"])
    sb = compute_stats(div_df.loc[div_df["div_confluence_with_regime"] >= 4,
                                   "div_forward_return_20b"])
    print(fmt_stats("A : DMP pur >= 3", sa))
    print(fmt_stats("B : DMP+regime >= 4", sb))

    if sa["n"] > 0 and sb["n"] > 0 and np.isfinite(sa["pf"]) and np.isfinite(sb["pf"]):
        delta_pf = sb["pf"] - sa["pf"]
        delta_ev = sb["ev"] - sa["ev"]
        print(f"\n  UPLIFT B vs A : deltaPF = {delta_pf:+.2f}  "
              f"deltaEV = {delta_ev:+.3f}  deltaN = {sb['n'] - sa['n']:+d}")

    # ═══════════════════════════════════════════════════════════════════
    # BRACKET SL/TP FIXE (SL = niveau + 3 ticks buffer, TP = 2x SL)
    # Pessimiste : SL wins sur TP dans la meme barre
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  {'=' * 74}")
    print(f"  BACKTEST BRACKET SL/TP (R:R 1:2, max 40 barres)")
    print(f"  {'=' * 74}")

    # Enrichir df avec bar_high/bar_low convertis
    df["bar_high"] = pd.to_numeric(df["bar_high"], errors="coerce")
    df["bar_low"] = pd.to_numeric(df["bar_low"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    dd_mask = df["delta_divergence_clean"].fillna(0) != 0

    print(f"\n  --- A : DMP PUR ---")
    for thr in [1, 2, 3]:
        mask = dd_mask & (df["div_confluence_dmp"] >= thr)
        s = run_bracket_backtest(df, mask, f"DMP conf >= {thr}")
        print(fmt_bracket(s))

    print(f"\n  --- B : DMP + PROXIES REGIME ---")
    for thr in [1, 2, 3, 4]:
        mask = dd_mask & (df["div_confluence_with_regime"] >= thr)
        s = run_bracket_backtest(df, mask, f"REGIME conf >= {thr}")
        print(fmt_bracket(s))

    # Baseline : filtre strict "sur niveau" (div_at_key_level_ticks < 15)
    print(f"\n  --- BONUS : filtre strict 'div sur niveau <15t' ---")
    mask_strict_a = dd_mask & (df["div_confluence_dmp"] >= 2) & (df["div_at_key_level_ticks"] < 15)
    mask_strict_b = dd_mask & (df["div_confluence_with_regime"] >= 3) & (df["div_at_key_level_ticks"] < 15)
    print(fmt_bracket(run_bracket_backtest(df, mask_strict_a, "DMP>=2 & at_level<15t")))
    print(fmt_bracket(run_bracket_backtest(df, mask_strict_b, "REGIME>=3 & at_level<15t")))


def main():
    for symbol in ["ES", "NQ"]:
        run_backtest(symbol)
    print()


if __name__ == "__main__":
    main()
