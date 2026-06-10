"""audit_wall_break_rate.py — Vrai test classification mur SLTPEngine.

Question : un niveau est-il un MUR SOLIDE (tier 1/2) ou MUR PAPIER (tier 3) ?

Methodologie correcte (adaptee au cas d'usage SLTPEngine) :
  Pour chaque "touche" (|dist_*_pct| <= 0.02%) :
    Mesurer si le prix PENETRE le niveau de >X ticks dans les Y bars suivantes.

  break_rate = % touches ou prix penetre.
    Tier 1 (mur solide)  : break_rate < 30%  (le mur tient majoritairement)
    Tier 2 (mur OK)      : break_rate 30-50% (mur partiel, OK si confluence)
    Tier 3 (mur papier)  : break_rate > 50%  (le prix le traverse)

Direction du break :
  - Niveau au-dessus du prix (dist > 0) : break si prix MONTE > X ticks au-dessus du niveau
  - Niveau en-dessous (dist < 0) : break si prix DESCEND > X ticks sous le niveau

Pour Y et X :
  - Y = 30 bars (1-min = 30 min apres touche)
  - X = 8 ticks NQ / 4 ticks ES (penetration significative, pas juste wick)
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
PROXIMITY_PCT = 0.02
FORWARD_BARS = 30
BREAK_TICKS = {"ES": 4, "NQ": 8}

WALLS = [
    # T1 actuels
    {"name": "MQ_PUT_0DTE",    "col": "dist_mq_put_0dte_pct",   "tier": 1},
    {"name": "MQ_CALL_0DTE",   "col": "dist_mq_call_0dte_pct",  "tier": 1},
    {"name": "GEX_DN",         "col": "dist_gex_nearest_dn_pct","tier": 1},
    {"name": "GEX_UP",         "col": "dist_gex_nearest_up_pct","tier": 1},
    # T2 actuels
    {"name": "VWAP_D_SD1U",    "col": "dist_vwap_d_sd1u_pct",   "tier": 2},
    {"name": "VWAP_D_SD1D",    "col": "dist_vwap_d_sd1d_pct",   "tier": 2},
    {"name": "VWAP_D_SD2U",    "col": "dist_vwap_d_sd2u_pct",   "tier": 2},
    {"name": "VWAP_D_SD2D",    "col": "dist_vwap_d_sd2d_pct",   "tier": 2},
    {"name": "MQ_CALL",        "col": "dist_mq_call_pct",       "tier": 2},
    {"name": "MQ_PUT",         "col": "dist_mq_put_pct",        "tier": 2},
    {"name": "MQ_HVL",         "col": "dist_mq_hvl_pct",        "tier": 2},
    {"name": "PVAH",           "col": "dist_prev_vah_pct",      "tier": 2},
    {"name": "PVAL",           "col": "dist_prev_val_pct",      "tier": 2},
    {"name": "PDH",            "col": "dist_pdh_pct",           "tier": 2},
    {"name": "PDL",            "col": "dist_pdl_pct",           "tier": 2},
    {"name": "VWAP_W",         "col": "dist_vwap_w_pct",        "tier": 2},
    {"name": "VWAP_M",         "col": "dist_vwap_m_pct",        "tier": 2},
    {"name": "PVWAP_SD1U",     "col": "dist_pvwap_sd1u_pct",    "tier": 2},
    {"name": "PVWAP_SD1D",     "col": "dist_pvwap_sd1d_pct",    "tier": 2},
    # T3 actuels (controle "papier")
    {"name": "VWAP_D",         "col": "dist_vwap_d_pct",        "tier": 3},
    {"name": "IB_LOW",         "col": "dist_ib_low_pct",        "tier": 3},
    {"name": "IB_HIGH",        "col": "dist_ib_high_pct",       "tier": 3},
    # === SUJET DU TEST ===
    {"name": "PREV_VWAP_NU",   "col": "dist_pvwap_pct",         "tier": 3, "highlight": True},
    # Niveaux supplementaires Sidak (pour voir leur classification mur)
    {"name": "SWING_LOW",      "col": "dist_last_swing_low_pct", "tier": 2, "note": "Sidak"},
    {"name": "SWING_HIGH",     "col": "dist_last_swing_high_pct","tier": 2, "note": "Sidak"},
    {"name": "COLOR_UP_zone",  "col": "dist_color_up_nearest_pct","tier": 2, "note": "Sidak"},
    {"name": "COLOR_DN_zone",  "col": "dist_color_dn_nearest_pct","tier": 2, "note": "Sidak"},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def measure_break_rate(df, sym, col):
    """Mesure le % de touches ou le prix PENETRE le niveau."""
    if col not in df.columns:
        return None
    tick = TICK_SIZE[sym]
    break_ticks_pts = BREAK_TICKS[sym] * tick
    dist = df[col].astype(float)
    # Touche + signe initial
    near = dist.abs() <= PROXIMITY_PCT
    indices = np.where(near)[0]
    n = len(df)
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n_touches = 0
    n_breaks = 0
    for i in indices:
        if i + FORWARD_BARS >= n:
            continue
        d_signed = float(dist.iloc[i])
        if abs(d_signed) > PROXIMITY_PCT:
            continue
        # Reconstituer prix du niveau (approx)
        close_i = closes[i]
        # niveau = close * (1 + d_signed/100)
        level_price = close_i * (1.0 + d_signed / 100.0)
        # Forward window
        fwd_high = np.max(highs[i:i + FORWARD_BARS + 1])
        fwd_low = np.min(lows[i:i + FORWARD_BARS + 1])
        # Break detection
        # Si niveau au-dessus (d_signed > 0) : break si fwd_high - level >= break_ticks_pts
        # Si niveau en-dessous (d_signed < 0) : break si level - fwd_low >= break_ticks_pts
        # Si d_signed ~0 : check les 2 directions
        is_break = False
        if d_signed > 0:  # niveau au-dessus, le prix peut MONTER pour casser
            if fwd_high - level_price >= break_ticks_pts:
                is_break = True
        elif d_signed < 0:  # niveau en-dessous
            if level_price - fwd_low >= break_ticks_pts:
                is_break = True
        else:  # d_signed == 0 (rare, on est exactement sur le niveau)
            if max(fwd_high - level_price, level_price - fwd_low) >= break_ticks_pts:
                is_break = True
        n_touches += 1
        if is_break:
            n_breaks += 1
    if n_touches < 30:
        return None
    return {"n_touches": n_touches, "n_breaks": n_breaks,
            "break_rate": n_breaks / n_touches}


def classify(break_rate):
    """Classification empirique selon break rate."""
    if break_rate < 0.30:
        return "T1_SOLIDE"
    if break_rate < 0.50:
        return "T2_OK"
    if break_rate < 0.70:
        return "T3_PARTIEL"
    return "T3_PAPIER"


def main():
    print(f"\n=== AUDIT WALL BREAK RATE — {FORWARD_BARS}b forward, break = {BREAK_TICKS}t ===\n")
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, 6)
        if df.empty: continue
        print(f"\n--- {sym} ({len(df)} bars) — break threshold {BREAK_TICKS[sym]}t ---\n")
        results = []
        for w in WALLS:
            m = measure_break_rate(df, sym, w["col"])
            if m is None:
                continue
            results.append({**w, **m})
        results.sort(key=lambda r: r["break_rate"])
        print(f"  {'Niveau':<22} {'Tier doc':<9} {'n':>5} {'breaks':>7} {'break_rate':>11} {'Classif emp':<14}")
        for r in results:
            classif = classify(r["break_rate"])
            doc_str = f"T{r['tier']}"
            highlight = " <<<" if r.get("highlight") else (" [Sidak]" if r.get("note") == "Sidak" else "")
            mismatch = " !!! " if (
                (r["tier"] == 1 and not classif.startswith("T1")) or
                (r["tier"] == 2 and not classif.startswith("T1") and not classif.startswith("T2")) or
                (r["tier"] == 3 and not classif.startswith("T3"))
            ) else ""
            print(f"  {r['name']:<22} {doc_str:<9} {r['n_touches']:>5} {r['n_breaks']:>7} "
                  f"{r['break_rate']*100:>10.1f}% {classif:<14}{mismatch}{highlight}")


if __name__ == "__main__":
    main()
