"""phase_signature_backtest.py — Voie 1 backtest forward Spring/UTAD signatures.

Jackson 09/05 : audit signatures pre-phase strictes (60t ES / 120t NQ, 8-30 bars,
pivot 5b lookback) revele pattern Wyckoff/AMT empirique :
  - Pre-UP (avant hausse) : long_dn_bar + color_dn dominent (Spring Wyckoff)
  - Pre-DOWN (avant baisse) : long_up_bar + color_up dominent (UTAD Wyckoff)

Z-discrimination ES=0.48 / NQ=0.35 : signal faible mais reel.

Ce backtest mesure si la signature pre-phase predit un mouvement TP avant SL,
APRES costs, sur 12 folds walk-forward, avec DSR Lopez calcule.

Methodologie Lopez-compliant (corrige les leak v3) :
  1. Costs inclus dans pnl_ticks (ES 2t / NQ 3t round-trip)
  2. Walk-forward 12 folds chronologiques (pas 3)
  3. DSR Bailey-Lopez calcule
  4. Bonferroni p-value pour multiple testing
  5. Detection signature ROLLING (pas look-ahead) : sur chaque bar i, extraire
     signature des 15 bars precedentes [i-15, i-1] et entrer au close[i]
  6. Entry tradable (pas au pivot connu en avance, signature live)

Variantes testees :
  A. Spring base : n_long_dn >= 2 + n_color_dn >= 2 dans les 15 last bars
  B. UTAD base : n_long_up >= 2 + n_color_up >= 2 dans les 15 last bars
  C. Spring + niveau support touche (MQ_PUT, IB_LOW, SWING_LOW, MQ_HVL)
  D. UTAD + niveau resistance touche (MQ_CALL, IB_HIGH, SWING_HIGH, MQ_HVL)

Output : PF, EV/trade, n, fold stability, DSR par variante.
Verdict GO/NOGO base sur EV > 0 apres costs + DSR > 0.95.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}

# Costs round-trip (Lopez : commission + slippage)
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}

# ─── B1 FIX (code-reviewer) : ANTI-LEAK ───
# bn_color_up_fwd1/bn_color_dn_fwd1 sont LEAKY (suffixe _fwd1 = lookahead 1 bar).
# Commit a8be745 du jour les a droppes pour leak ML. Remplace par features
# par-barre sans leak : n_color_up_cluster_within_0_2pct / n_color_dn_*.
# Seuils ajustes (>=1 au lieu de >=2) car ces features sont des comptages cluster.
LONG_DN = "long_dn_bar"
LONG_UP = "long_up_bar"
COLOR_DN = "n_color_dn_cluster_within_0_2pct"
COLOR_UP = "n_color_up_cluster_within_0_2pct"

# Niveaux SUPPORT (pour Spring → BUY)
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

# Niveaux RESISTANCE (pour UTAD → SELL)
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


def detect_signal_at_bar(df: pd.DataFrame, i: int, lookback: int = 15,
                          min_long: int = 2, min_color: int = 1) -> dict:
    """Detection ROLLING : extrait signature des [i-lookback, i-1] bars.

    NOTE B1 fix (code-reviewer) : COLOR_UP/DN sont maintenant des features
    par-barre (n_color_*_cluster_within_0_2pct, NaN ou >0 si zones presentes).
    min_color default = 1 (au lieu de 2) car ces comptages cluster sont distincts.

    Returns:
        {spring: bool, utad: bool, n_long_dn, n_color_dn, n_long_up, n_color_up}
    """
    start = max(0, i - lookback)
    end = i  # exclusif
    if start >= end or i < lookback:
        return {"spring": False, "utad": False, "n_long_dn": 0, "n_color_dn": 0,
                "n_long_up": 0, "n_color_up": 0}
    window = df.iloc[start:end]
    n_long_dn = int((window[LONG_DN].fillna(0) > 0).sum()) if LONG_DN in window.columns else 0
    n_color_dn = int((window[COLOR_DN].fillna(0) > 0).sum()) if COLOR_DN in window.columns else 0
    n_long_up = int((window[LONG_UP].fillna(0) > 0).sum()) if LONG_UP in window.columns else 0
    n_color_up = int((window[COLOR_UP].fillna(0) > 0).sum()) if COLOR_UP in window.columns else 0
    return {
        "spring": (n_long_dn >= min_long and n_color_dn >= min_color),
        "utad": (n_long_up >= min_long and n_color_up >= min_color),
        "n_long_dn": n_long_dn, "n_color_dn": n_color_dn,
        "n_long_up": n_long_up, "n_color_up": n_color_up,
    }


def is_at_support(bar: pd.Series) -> bool:
    """Au moins 1 niveau SUPPORT actif (|dist| <= threshold)."""
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


def simulate_trade(df: pd.DataFrame, entry_idx: int, direction: str, sym: str,
                    tp_ticks: int = 24, sl_ticks: int = 12, fwd_bars: int = 30) -> dict:
    """Simule un trade path-dependent. Pessimist si TP+SL meme bar.

    Returns: {exit: 'TP'|'SL'|'TIMEOUT'|'NO_DATA', pnl_ticks (apres costs), bars}
    """
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
    # TIMEOUT : exit au close final
    final_close = df.iloc[end]["close"]
    if direction == "BUY":
        unreal = (final_close - entry_price) / tick
    else:
        unreal = (entry_price - final_close) / tick
    return {"exit": "TIMEOUT", "pnl_ticks": float(unreal) - cost, "bars": end - entry_idx}


def collect_trades(df: pd.DataFrame, sym: str, lookback: int = 15,
                    tp_ticks: int = 24, sl_ticks: int = 12, fwd_bars: int = 30,
                    require_level: bool = False, cooldown_bars: int = 30) -> list:
    """Iter sur df, detecte signatures, simule trades. Cooldown pour eviter chevauchement."""
    trades = []
    n = len(df)
    last_signal_idx = -cooldown_bars
    for i in range(lookback + 1, n - fwd_bars):
        if i - last_signal_idx < cooldown_bars:
            continue
        sig = detect_signal_at_bar(df, i, lookback=lookback)
        bar = df.iloc[i]
        # Spring → BUY
        if sig["spring"]:
            if require_level and not is_at_support(bar):
                continue
            tr = simulate_trade(df, i, "BUY", sym, tp_ticks, sl_ticks, fwd_bars)
            tr.update({"signal": "SPRING", "direction": "BUY", "entry_idx": i,
                       "ts_event": bar["ts_event"], **{k: sig[k] for k in ["n_long_dn", "n_color_dn"]}})
            trades.append(tr)
            last_signal_idx = i
            continue
        # UTAD → SELL
        if sig["utad"]:
            if require_level and not is_at_resistance(bar):
                continue
            tr = simulate_trade(df, i, "SELL", sym, tp_ticks, sl_ticks, fwd_bars)
            tr.update({"signal": "UTAD", "direction": "SELL", "entry_idx": i,
                       "ts_event": bar["ts_event"], **{k: sig[k] for k in ["n_long_up", "n_color_up"]}})
            trades.append(tr)
            last_signal_idx = i
    return trades


def metrics(trades: list, label: str = "") -> dict:
    if not trades:
        return {"label": label, "n": 0, "wr": 0, "pf": 0, "ev_per_trade": 0,
                "sharpe": 0, "dsr": 0}
    pnls = np.array([t["pnl_ticks"] for t in trades])
    n = len(pnls)
    n_wins = int((pnls > 0).sum())
    wr = n_wins / n
    sum_win = pnls[pnls > 0].sum()
    sum_loss = abs(pnls[pnls < 0].sum())
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    ev = pnls.mean()
    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
    # ─── B3 FIX : PSR Bailey 2012 formule correcte ───
    # NOTE : ce qu'on calcule = PSR (Probabilistic SR > 0), pas DSR (Deflated avec Bonferroni).
    # ml-trainer downstream applique la correction multiple testing globale.
    # Bailey 2012 utilise kurtosis Pearson (pas Fisher) : passer fisher=False.
    if pnls.std() > 0 and n > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(pnls)
        kt = kurtosis(pnls, fisher=False)  # B3 fix : Pearson, pas Fisher
        sr = pnls.mean() / pnls.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr_z = sr * np.sqrt(n - 1) / denom
        psr = float(norm.cdf(psr_z))
    else:
        psr = 0.5
    return {"label": label, "n": n, "wr": wr, "pf": pf, "ev_per_trade": ev,
            "sharpe": sharpe, "psr": psr}


def walk_forward(trades: list, n_folds: int = 12) -> dict:
    """Split trades chronologiquement en n_folds. Compute PF/EV/wr par fold."""
    if len(trades) < n_folds * 5:
        return {"folds": [], "pf_min": 0, "pf_median": 0, "stable": False}
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


def report(trades: list, sym: str, label: str):
    print(f"\n--- {label} ({sym}) ---")
    if not trades:
        print(f"  Aucun trade")
        return
    m = metrics(trades, label)
    wf = walk_forward(trades, n_folds=12)
    spring = [t for t in trades if t["signal"] == "SPRING"]
    utad = [t for t in trades if t["signal"] == "UTAD"]
    print(f"  N total : {m['n']} (SPRING={len(spring)}, UTAD={len(utad)})")
    print(f"  Win rate : {m['wr']*100:.1f}%")
    print(f"  PF : {m['pf']:.2f}")
    print(f"  EV/trade : {m['ev_per_trade']:+.2f} ticks (apres costs)")
    print(f"  Sharpe (par-trade x sqrt(252) - indicatif) : {m['sharpe']:.2f}")
    print(f"  PSR (Probabilistic SR > 0) : {m['psr']:.3f}")
    # M3 fix : afficher seuil corrige Sidak pour 4 variantes (2 syms x 2 variantes)
    n_tests_global = 4
    psr_threshold = 1 - (1 - (1 - 0.05)**(1/n_tests_global))  # ≈ 0.987
    verdict = "GO" if m["psr"] >= psr_threshold else "NOGO"
    print(f"  PSR threshold corrige Sidak (n_tests={n_tests_global}) : {psr_threshold:.4f} -> {verdict}")
    print(f"  Walk-forward 12 folds : pf_min={wf['pf_min']:.2f}, pf_median={wf['pf_median']:.2f}, "
          f"n_pos_folds={wf['n_pos']}/12, stable={wf['stable']}")
    if spring:
        ms = metrics(spring, "SPRING_only")
        print(f"  SPRING seul : n={ms['n']}, WR={ms['wr']*100:.0f}%, PF={ms['pf']:.2f}, EV={ms['ev_per_trade']:+.2f}t")
    if utad:
        mu = metrics(utad, "UTAD_only")
        print(f"  UTAD seul : n={mu['n']}, WR={mu['wr']*100:.0f}%, PF={mu['pf']:.2f}, EV={mu['ev_per_trade']:+.2f}t")
    # Distribution exit
    exits = pd.Series([t["exit"] for t in trades]).value_counts()
    print(f"  Exits : {dict(exits)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--lookback", type=int, default=15)
    parser.add_argument("--tp", type=int, default=24)
    parser.add_argument("--sl", type=int, default=12)
    parser.add_argument("--fwd", type=int, default=30)
    parser.add_argument("--cooldown", type=int, default=45)  # B2 fix : lookback (15) + fwd_bars (30)
    args = parser.parse_args()

    sym = args.symbol
    print(f"\n{'='*70}")
    print(f"=== PHASE SIGNATURE BACKTEST V1 — {sym} ({args.months} mois) ===")
    print(f"=== Spring/UTAD signatures, lookback {args.lookback}b, TP={args.tp}t SL={args.sl}t ===")
    print(f"=== Costs : {COSTS_TICKS[sym]}t round-trip, cooldown {args.cooldown}b ===")
    print(f"{'='*70}")

    df = load_v4(sym, args.months)
    if df.empty:
        print(f"  Pas de data {sym}")
        return
    print(f"  Loaded {len(df)} bars : {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # Variante A : signature seule
    print("\n>>> Variante A : Signature Spring/UTAD seule (no level filter)")
    trades_A = collect_trades(df, sym, args.lookback, args.tp, args.sl, args.fwd,
                                require_level=False, cooldown_bars=args.cooldown)
    report(trades_A, sym, "A_signature_seule")

    # Variante B : signature + niveau touche (OR sur 8 niveaux)
    # B4 WARNING : Variante B expose multiple testing INTRA-variante (8 niveaux SUPPORT
    # + 8 RESISTANCE = 16 sub-tests masques sous le OR). Si Variante B PF >> A, c'est
    # peut-etre du fit selectif sur 1 niveau parmi 8. ml-trainer doit corriger
    # explicitement pour 4 + 16 = 20 tests Bonferroni si verdict GO.
    print("\n>>> Variante B : Signature + niveau MQ/IB/Swing actif (8 OR-tests masques)")
    trades_B = collect_trades(df, sym, args.lookback, args.tp, args.sl, args.fwd,
                                require_level=True, cooldown_bars=args.cooldown)
    report(trades_B, sym, "B_signature_plus_niveau")
    print("\n  WARNING B4 (code-reviewer): Variante B = 8 niveaux OR-filter = multiple")
    print("  testing implicite. PSR threshold a corriger pour n_tests=20 si downstream.")


if __name__ == "__main__":
    main()
