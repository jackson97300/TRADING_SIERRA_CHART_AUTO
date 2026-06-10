"""audit_prev_vwap_wall.py — Test empirique : PREV_VWAP est-il un mur papier (T3) ou solide (T2) ?

Jackson 09/05 : "PREV_VWAP n'est pas un mur papier".
Code mia_sltp.py:263 le classe TIER 3 (mur papier piege).
Avant promotion, audit empirique strict (anti pattern 11).

Methodologie :
  - 6 mois v4 enriched ES + NQ
  - Touches : |dist_pvwap_pct| <= 0.02%
  - Direction : neutre -> on prend BUY si dist > 0 (prix sous PVWAP, support)
                       ou SELL si dist < 0 (prix au-dessus PVWAP, resistance)
  - TP=24t, SL=12t, costs ES 2t / NQ 3t, fwd 30b
  - Compare a benchmarks tier 1, 2, 3 actuels

Verdict :
  EV positif + WF >= 10/12 + n >= 100 -> mur SOLIDE (au moins T2)
  EV negatif OU WF instable -> mur PAPIER (T3 confirme)
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}
TP_TICKS = 24
SL_TICKS = 12
FWD_BARS = 30
COOLDOWN = 45
PROXIMITY_PCT = 0.02

# Benchmarks pour comparaison
BENCHMARKS = [
    # TIER 1 actuels
    {"name": "MQ_PUT_0DTE",     "col": "dist_mq_put_0dte_pct",   "side_neutral": True, "tier": 1},
    {"name": "MQ_CALL_0DTE",    "col": "dist_mq_call_0dte_pct",  "side_neutral": True, "tier": 1},
    {"name": "GEX_DN",          "col": "dist_gex_nearest_dn_pct","side_neutral": True, "tier": 1},
    # TIER 2 actuels
    {"name": "VWAP_D_SD1D",     "col": "dist_vwap_d_sd1d_pct",   "side_neutral": True, "tier": 2},
    {"name": "VWAP_D_SD1U",     "col": "dist_vwap_d_sd1u_pct",   "side_neutral": True, "tier": 2},
    {"name": "MQ_CALL",         "col": "dist_mq_call_pct",       "side_neutral": True, "tier": 2},
    {"name": "MQ_PUT",          "col": "dist_mq_put_pct",        "side_neutral": True, "tier": 2},
    {"name": "MQ_HVL",          "col": "dist_mq_hvl_pct",        "side_neutral": True, "tier": 2},
    {"name": "PVAH",            "col": "dist_prev_vah_pct",      "side_neutral": True, "tier": 2},
    {"name": "PVAL",            "col": "dist_prev_val_pct",      "side_neutral": True, "tier": 2},
    {"name": "VWAP_W",          "col": "dist_vwap_w_pct",        "side_neutral": True, "tier": 2},
    # TIER 3 actuels (controle "mur papier")
    {"name": "VWAP_D",          "col": "dist_vwap_d_pct",        "side_neutral": True, "tier": 3},
    {"name": "IB_LOW",          "col": "dist_ib_low_pct",        "side_neutral": True, "tier": 3},
    {"name": "IB_HIGH",         "col": "dist_ib_high_pct",       "side_neutral": True, "tier": 3},
    # === SUJET DU TEST ===
    {"name": "PREV_VWAP_NU",    "col": "dist_pvwap_pct",         "side_neutral": True, "tier": 3, "highlight": True},
    {"name": "PVWAP_SD1U",      "col": "dist_pvwap_sd1u_pct",    "side_neutral": True, "tier": 2, "highlight": False},
    {"name": "PVWAP_SD1D",      "col": "dist_pvwap_sd1d_pct",    "side_neutral": True, "tier": 2, "highlight": False},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def simulate_trade(df, i, side, sym):
    n = len(df)
    if i + FWD_BARS >= n:
        return None
    tick = TICK_SIZE[sym]; cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    entry = closes[i]
    if side == "LONG":
        tp = entry + TP_TICKS * tick; sl = entry - SL_TICKS * tick
    else:
        tp = entry - TP_TICKS * tick; sl = entry + SL_TICKS * tick
    for k in range(i + 1, min(i + FWD_BARS + 1, n)):
        bh = highs[k]; bl = lows[k]
        if side == "LONG":
            sl_hit = bl <= sl; tp_hit = bh >= tp
        else:
            sl_hit = bh >= sl; tp_hit = bl <= tp
        if sl_hit and tp_hit: return -float(SL_TICKS) - cost
        if sl_hit:            return -float(SL_TICKS) - cost
        if tp_hit:            return float(TP_TICKS) - cost
    final = closes[min(i + FWD_BARS, n - 1)]
    return float(((final - entry) if side == "LONG" else (entry - final)) / tick - cost)


def evaluate_neutral(df, sym, col):
    """Evalue niveau neutre : LONG si prix sous niveau (dist > 0), SHORT si prix au-dessus."""
    if col not in df.columns:
        return None
    dist = df[col].astype(float)
    near = dist.abs() <= PROXIMITY_PCT
    indices = np.where(near)[0]
    n = len(df)
    last = -COOLDOWN
    pnls = []
    for i in indices:
        if i - last < COOLDOWN:
            continue
        if i + FWD_BARS >= n:
            continue
        d = float(dist.iloc[i])
        if d > 0:
            side = "LONG"   # prix sous niveau -> bounce LONG
        elif d < 0:
            side = "SHORT"  # prix au-dessus -> rejet SHORT
        else:
            continue
        pnl = simulate_trade(df, i, side, sym)
        if pnl is None:
            continue
        pnls.append(pnl); last = i
    if len(pnls) < 30:
        return {"n": len(pnls), "ev": 0, "pf": 0, "wr": 0, "pos_folds": 0, "psr": 0}
    arr = np.array(pnls)
    n_t = len(arr)
    wr = (arr > 0).mean()
    sw = arr[arr > 0].sum(); sl = abs(arr[arr < 0].sum())
    pf = sw / sl if sl > 0 else float("inf")
    ev = arr.mean()
    if arr.std() > 0 and n_t > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(arr); kt = kurtosis(arr, fisher=False)
        sr = arr.mean() / arr.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n_t - 1) / denom))
    else:
        psr = 0.5
    cuts = np.linspace(0, n_t, 13, dtype=int)
    pos_folds = 0
    for k in range(12):
        sub = arr[cuts[k]:cuts[k + 1]]
        if len(sub) >= 1 and sub.sum() >= 0:
            pos_folds += 1
    return {"n": n_t, "ev": float(ev), "pf": float(pf), "wr": float(wr),
            "pos_folds": pos_folds, "psr": float(psr)}


def main():
    print(f"\n=== AUDIT PREV_VWAP : MUR PAPIER OU SOLIDE ? ===")
    print(f"=== Methodologie : prox {PROXIMITY_PCT}%, TP {TP_TICKS}t SL {SL_TICKS}t, costs round-trip ===\n")
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, 6)
        if df.empty: continue
        print(f"\n--- {sym} ({len(df)} bars) ---\n")
        print(f"  {'Niveau':<22} {'Tier':>4} {'n':>6} {'WR':>6} {'PF':>5} {'EV':>7} {'WF+':>5} {'PSR':>6}  {'Verdict':>10}")
        results = []
        for b in BENCHMARKS:
            m = evaluate_neutral(df, sym, b["col"])
            if m is None or m["n"] < 30:
                continue
            results.append({**b, **m})
        # Trie par EV
        results.sort(key=lambda r: -r["ev"])
        for r in results:
            verdict = "SOLIDE" if (r["ev"] >= 1.0 and r["pos_folds"] >= 8) else (
                      "MARG"  if (r["ev"] >= 0.5)                            else "PAPIER")
            highlight = " <<<" if r.get("highlight") else ""
            print(f"  {r['name']:<22} T{r['tier']:>3} {r['n']:>6} {r['wr']*100:>5.1f}% "
                  f"{r['pf']:>5.2f} {r['ev']:>+6.2f} {r['pos_folds']:>3}/12 {r['psr']:>5.3f}  "
                  f"{verdict:>10}{highlight}")


if __name__ == "__main__":
    main()
