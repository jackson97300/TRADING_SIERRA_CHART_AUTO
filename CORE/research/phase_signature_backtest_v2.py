"""phase_signature_backtest_v2.py — Voie 1 v2 : SEMANTIQUE RETOUCHE BN.

Correction Jackson 09/05 : v1 melangeait "barre origine" (long_up_bar) et
"retouche cluster" (n_color_*_cluster_within_0_2pct). Inconsistent.

V2 : signature pure RETOUCHE BN.
  - Prix DANS zone extension active (LONG_UP/DN, COLOR_UP/DN) = retouche
  - Pression contraire recente (5 bars) = signal Spring/UTAD valide

Spring (BUY) au demarrage UP :
  - Barre i : retouche zone LONG_UP support (n_long_up_cluster >= 1)
  - Dans last 5 bars : pression vendeuse (long_dn_bar OU n_color_dn_cluster >=1 ou raw color_dn)
  - = panique vendeuse leurree par support LONG_UP qui tient

UTAD (SELL) au demarrage DOWN :
  - Barre i : retouche zone LONG_DN resistance (n_long_dn_cluster >= 1)
  - Dans last 5 bars : pression acheteuse (long_up_bar OU n_color_up_cluster >=1)
  - = euphorie acheteuse butee sur resistance LONG_DN

Variantes :
  A. Retouche LONG seule (no condition pressure)
  B. Retouche LONG + pressure contraire recente (5 bars)
  C. Retouche LONG + pressure contraire + niveau MQ/IB/Swing actif

Toutes les corrections code-reviewer v1 conservees :
  - No leak _fwd1 (utilise n_color_up/dn_cluster_within_0_2pct par-barre)
  - Costs ES 2t / NQ 3t round-trip
  - Walk-forward 12 folds
  - PSR Bailey 2012 Pearson kurtosis
  - Cooldown 45b (lookback + fwd)
  - Sidak threshold n_tests=6 (3 variantes x 2 syms)
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}

# ─── Features RETOUCHE (zones extension actives au prix courant) ───
N_LONG_UP_CLUSTER = "n_long_up_cluster_within_0_2pct"   # prix dans cluster LONG_UP zone(s)
N_LONG_DN_CLUSTER = "n_long_dn_cluster_within_0_2pct"
N_COLOR_UP_CLUSTER = "n_color_up_cluster_within_0_2pct"
N_COLOR_DN_CLUSTER = "n_color_dn_cluster_within_0_2pct"

# ─── Features PRESSION RECENTE (origine candle, fenetre 5 bars) ───
LONG_UP_BAR = "long_up_bar"
LONG_DN_BAR = "long_dn_bar"
LONG_UP_DN = "long_up_dn_pattern"
LONG_DN_UP = "long_dn_up_pattern"

# Niveaux SUPPORT (Variante C)
SUPPORT_LEVELS = [
    ("dist_mq_put_pct", 0.05),
    ("dist_mq_put_0dte_pct", 0.05),
    ("dist_mq_hvl_pct", 0.05),
    ("dist_ib_low_pct", 0.05),
    ("dist_last_swing_low_pct", 0.05),
    ("dist_pdl_pct", 0.10),
    ("dist_prev_val_pct", 0.10),
    ("dist_gex_nearest_dn_pct", 0.05),
]
RESISTANCE_LEVELS = [
    ("dist_mq_call_pct", 0.05),
    ("dist_mq_call_0dte_pct", 0.05),
    ("dist_mq_hvl_pct", 0.05),
    ("dist_ib_high_pct", 0.05),
    ("dist_last_swing_high_pct", 0.05),
    ("dist_pdh_pct", 0.10),
    ("dist_prev_vah_pct", 0.10),
    ("dist_gex_nearest_up_pct", 0.05),
]


def load_v4(symbol: str, max_months: int = 6) -> pd.DataFrame:
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def detect_retouche_signal(df: pd.DataFrame, i: int, pressure_window: int = 5) -> dict:
    """Detection RETOUCHE BN.

    Spring : retouche LONG_UP cluster + pressure vendeuse recente
    UTAD   : retouche LONG_DN cluster + pressure acheteuse recente
    """
    if i < pressure_window:
        return {"spring_pure": False, "utad_pure": False,
                "spring_full": False, "utad_full": False,
                "n_long_up_cluster": 0, "n_long_dn_cluster": 0,
                "pressure_dn_recent": 0, "pressure_up_recent": 0}
    bar = df.iloc[i]
    n_long_up = float(bar.get(N_LONG_UP_CLUSTER, 0) or 0)
    n_long_dn = float(bar.get(N_LONG_DN_CLUSTER, 0) or 0)
    is_in_long_up = n_long_up >= 1
    is_in_long_dn = n_long_dn >= 1

    # Pressure window : last `pressure_window` bars [i-window, i-1]
    win = df.iloc[i - pressure_window:i]
    p_dn = (
        int((win[LONG_DN_BAR].fillna(0) > 0).sum() if LONG_DN_BAR in win.columns else 0)
        + int((win[N_COLOR_DN_CLUSTER].fillna(0) > 0).sum() if N_COLOR_DN_CLUSTER in win.columns else 0)
    )
    p_up = (
        int((win[LONG_UP_BAR].fillna(0) > 0).sum() if LONG_UP_BAR in win.columns else 0)
        + int((win[N_COLOR_UP_CLUSTER].fillna(0) > 0).sum() if N_COLOR_UP_CLUSTER in win.columns else 0)
    )

    return {
        "spring_pure": is_in_long_up,
        "spring_full": is_in_long_up and p_dn >= 1,
        "utad_pure": is_in_long_dn,
        "utad_full": is_in_long_dn and p_up >= 1,
        "n_long_up_cluster": n_long_up,
        "n_long_dn_cluster": n_long_dn,
        "pressure_dn_recent": p_dn,
        "pressure_up_recent": p_up,
    }


def is_at_support(bar: pd.Series) -> bool:
    for col, thresh in SUPPORT_LEVELS:
        v = bar.get(col)
        if v is not None and not pd.isna(v) and abs(float(v)) <= thresh:
            return True
    return False


def is_at_resistance(bar: pd.Series) -> bool:
    for col, thresh in RESISTANCE_LEVELS:
        v = bar.get(col)
        if v is not None and not pd.isna(v) and abs(float(v)) <= thresh:
            return True
    return False


def simulate_trade(df, entry_idx, direction, sym, tp_ticks=24, sl_ticks=12, fwd_bars=30):
    n = len(df)
    end = min(entry_idx + fwd_bars, n - 1)
    if entry_idx + 1 >= end:
        return {"exit": "NO_DATA", "pnl_ticks": 0.0, "bars": 0}
    tick = TICK_SIZE[sym]
    entry_price = df.iloc[entry_idx]["close"]
    cost = COSTS_TICKS[sym]
    if direction == "BUY":
        tp_price = entry_price + tp_ticks * tick
        sl_price = entry_price - sl_ticks * tick
    else:
        tp_price = entry_price - tp_ticks * tick
        sl_price = entry_price + sl_ticks * tick
    for k in range(entry_idx + 1, end + 1):
        bar_high = df.iloc[k]["high"]
        bar_low = df.iloc[k]["low"]
        if direction == "BUY":
            sl_hit = bar_low <= sl_price
            tp_hit = bar_high >= tp_price
        else:
            sl_hit = bar_high >= sl_price
            tp_hit = bar_low <= tp_price
        if sl_hit and tp_hit:
            return {"exit": "SL_PESSIMIST", "pnl_ticks": -float(sl_ticks) - cost, "bars": k - entry_idx}
        if sl_hit:
            return {"exit": "SL", "pnl_ticks": -float(sl_ticks) - cost, "bars": k - entry_idx}
        if tp_hit:
            return {"exit": "TP", "pnl_ticks": float(tp_ticks) - cost, "bars": k - entry_idx}
    final_close = df.iloc[end]["close"]
    if direction == "BUY":
        unreal = (final_close - entry_price) / tick
    else:
        unreal = (entry_price - final_close) / tick
    return {"exit": "TIMEOUT", "pnl_ticks": float(unreal) - cost, "bars": end - entry_idx}


def collect_trades(df, sym, mode: str = "full",
                    require_level: bool = False,
                    pressure_window: int = 5,
                    tp=24, sl=12, fwd=30, cooldown=45):
    """mode = 'pure' (retouche LONG seule) ou 'full' (retouche + pressure contraire)."""
    trades = []
    n = len(df)
    last = -cooldown
    for i in range(pressure_window + 1, n - fwd):
        if i - last < cooldown:
            continue
        sig = detect_retouche_signal(df, i, pressure_window=pressure_window)
        bar = df.iloc[i]
        # Spring -> BUY
        is_spring = sig["spring_full"] if mode == "full" else sig["spring_pure"]
        if is_spring:
            if require_level and not is_at_support(bar):
                continue
            tr = simulate_trade(df, i, "BUY", sym, tp, sl, fwd)
            tr.update({"signal": "SPRING", "direction": "BUY", "entry_idx": i,
                       "ts_event": bar["ts_event"],
                       "n_long_up_cluster": sig["n_long_up_cluster"],
                       "pressure_dn_recent": sig["pressure_dn_recent"]})
            trades.append(tr)
            last = i
            continue
        # UTAD -> SELL
        is_utad = sig["utad_full"] if mode == "full" else sig["utad_pure"]
        if is_utad:
            if require_level and not is_at_resistance(bar):
                continue
            tr = simulate_trade(df, i, "SELL", sym, tp, sl, fwd)
            tr.update({"signal": "UTAD", "direction": "SELL", "entry_idx": i,
                       "ts_event": bar["ts_event"],
                       "n_long_dn_cluster": sig["n_long_dn_cluster"],
                       "pressure_up_recent": sig["pressure_up_recent"]})
            trades.append(tr)
            last = i
    return trades


def metrics(trades, label=""):
    if not trades:
        return {"label": label, "n": 0, "wr": 0, "pf": 0, "ev_per_trade": 0,
                "sharpe": 0, "psr": 0}
    pnls = np.array([t["pnl_ticks"] for t in trades])
    n = len(pnls)
    n_wins = int((pnls > 0).sum())
    wr = n_wins / n
    sum_win = pnls[pnls > 0].sum()
    sum_loss = abs(pnls[pnls < 0].sum())
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    ev = pnls.mean()
    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
    if pnls.std() > 0 and n > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(pnls)
        kt = kurtosis(pnls, fisher=False)
        sr = pnls.mean() / pnls.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr_z = sr * np.sqrt(n - 1) / denom
        psr = float(norm.cdf(psr_z))
    else:
        psr = 0.5
    return {"label": label, "n": n, "wr": wr, "pf": pf, "ev_per_trade": ev,
            "sharpe": sharpe, "psr": psr}


def walk_forward(trades, n_folds=12):
    if len(trades) < n_folds * 5:
        return {"folds": [], "pf_min": 0, "pf_median": 0, "n_pos": 0, "stable": False}
    cuts = np.linspace(0, len(trades), n_folds + 1, dtype=int)
    folds = []
    for k in range(n_folds):
        sub = trades[cuts[k]:cuts[k + 1]]
        m = metrics(sub, f"F{k+1}")
        folds.append(m)
    pfs = [f["pf"] if f["pf"] != float("inf") else 99.0 for f in folds]
    pf_min = min(pfs)
    pf_median = float(np.median(pfs))
    n_pos = sum(1 for pf in pfs if pf >= 1.0)
    stable = (n_pos >= n_folds * 0.66) and pf_median >= 1.3
    return {"folds": folds, "pf_min": pf_min, "pf_median": pf_median,
            "n_pos": n_pos, "stable": stable}


def report(trades, sym, label, n_tests_global=6):
    print(f"\n--- {label} ({sym}) ---")
    if not trades:
        print(f"  Aucun trade")
        return
    m = metrics(trades, label)
    wf = walk_forward(trades, 12)
    spring = [t for t in trades if t["signal"] == "SPRING"]
    utad = [t for t in trades if t["signal"] == "UTAD"]
    print(f"  N total : {m['n']} (SPRING={len(spring)}, UTAD={len(utad)})")
    print(f"  WR : {m['wr']*100:.1f}%, PF : {m['pf']:.2f}, EV/trade : {m['ev_per_trade']:+.2f}t")
    print(f"  Sharpe : {m['sharpe']:.2f}, PSR : {m['psr']:.3f}")
    psr_th = 1 - (1 - (1 - 0.05)**(1/n_tests_global))
    verdict = "GO" if m["psr"] >= psr_th else "NOGO"
    print(f"  Sidak threshold (n_tests={n_tests_global}) : {psr_th:.4f} -> {verdict}")
    print(f"  Walk-forward 12f : pf_min={wf['pf_min']:.2f}, pf_med={wf['pf_median']:.2f}, "
          f"pos_folds={wf['n_pos']}/12, stable={wf['stable']}")
    if spring:
        ms = metrics(spring, "SPRING")
        print(f"  SPRING : n={ms['n']}, WR={ms['wr']*100:.0f}%, PF={ms['pf']:.2f}, EV={ms['ev_per_trade']:+.2f}t")
    if utad:
        mu = metrics(utad, "UTAD")
        print(f"  UTAD   : n={mu['n']}, WR={mu['wr']*100:.0f}%, PF={mu['pf']:.2f}, EV={mu['ev_per_trade']:+.2f}t")
    exits = pd.Series([t["exit"] for t in trades]).value_counts()
    print(f"  Exits : {dict(exits)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--pressure", type=int, default=5)
    parser.add_argument("--tp", type=int, default=24)
    parser.add_argument("--sl", type=int, default=12)
    parser.add_argument("--fwd", type=int, default=30)
    parser.add_argument("--cooldown", type=int, default=45)
    args = parser.parse_args()

    sym = args.symbol
    print(f"\n{'='*70}")
    print(f"=== PHASE SIGNATURE BACKTEST V2 — {sym} ({args.months} mois) — RETOUCHE BN ===")
    print(f"=== TP={args.tp}t SL={args.sl}t fwd={args.fwd}b cooldown={args.cooldown}b ===")
    print(f"=== Costs : {COSTS_TICKS[sym]}t round-trip, pressure window {args.pressure}b ===")
    print(f"{'='*70}")

    df = load_v4(sym, args.months)
    if df.empty:
        print(f"  Pas de data {sym}")
        return
    print(f"  Loaded {len(df)} bars : {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # Variante A : retouche LONG seule (pure)
    print("\n>>> Variante A : Retouche LONG_UP/DN seule (no pressure, no level)")
    trades_A = collect_trades(df, sym, mode="pure", require_level=False,
                               pressure_window=args.pressure,
                               tp=args.tp, sl=args.sl, fwd=args.fwd, cooldown=args.cooldown)
    report(trades_A, sym, "A_retouche_pure")

    # Variante B : retouche LONG + pressure contraire recente
    print("\n>>> Variante B : Retouche LONG_UP/DN + pressure contraire 5 bars")
    trades_B = collect_trades(df, sym, mode="full", require_level=False,
                               pressure_window=args.pressure,
                               tp=args.tp, sl=args.sl, fwd=args.fwd, cooldown=args.cooldown)
    report(trades_B, sym, "B_retouche_plus_pressure")

    # Variante C : retouche + pressure + niveau MQ/IB/Swing
    print("\n>>> Variante C : Retouche + pressure + niveau actif (8 OR-tests)")
    trades_C = collect_trades(df, sym, mode="full", require_level=True,
                               pressure_window=args.pressure,
                               tp=args.tp, sl=args.sl, fwd=args.fwd, cooldown=args.cooldown)
    report(trades_C, sym, "C_retouche_pressure_niveau")
    print("\n  WARNING B4 : Variante C = 8 niveaux OR = multiple testing implicite.")
    print("  Si GO, ml-trainer doit corriger pour n_tests=6 + 16 = 22 Bonferroni.")


if __name__ == "__main__":
    main()
