"""Backtest de TRI des 11 setups Bot 2 V2 + filtre BIAS ENGINE MTF 4 timeframes.

OBJECTIF : ce script ne rend PAS un verdict GO/NOGO global. Il TRIE et MESURE.
  1. Pour chaque setup : PF / WR / n sur TRAIN (mois -2 exclus) et OOS (2 derniers mois).
  2. Pour chaque setup : compare 3 variantes
       - BASELINE      : aucun filtre directionnel
       - MTF >= 3/4    : trade seulement si >=3 TF alignes dans le sens du signal
       - MTF == 4/4    : trade seulement si les 4 TF alignes (ACHAT/VENTE FORT)
  Output = quels setups tiennent, et si le filtre MTF ameliore le PF.

BIAS ENGINE MTF : reproduction EXACTE de DASHBOARD/api/readers.py:read_mtf_bias
  (widget "ACHAT FORT 4/4"). Pour chaque TF (1m/5m/15m/1h) : score =
  0.4*VWAP + 0.3*delta + 0.3*momentum sur les N dernieres barres agregees.
  BULL si score > 0.25, BEAR si < -0.25. Calcule intraday (barres du jour
  jusqu'a la barre courante) — pas de look-ahead.

DONNEES : DATA/datasets/v4_enriched (ES + NQ). Exit = logique EXACTE du
  SetupEngine live (SL fixe, trailing, TP cap, timeout 40min). Cout COST_TICKS.

USAGE : python -X utf8 tools/backtest_setups_tri.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from CORE.setup_definitions import evaluate_all_setups, SETUP_REGISTRY

TICK = 0.25
COST_TICKS = 1.0

TRAILING_CONFIG = {
    "NQ": {"sl_ticks": 200, "trailing_activation_ticks": 80,
           "trailing_distance_ticks": 60, "timeout_minutes": 40,
           "tp_cap_ticks": 500},
    "ES": {"sl_ticks": 80, "trailing_activation_ticks": 32,
           "trailing_distance_ticks": 24, "timeout_minutes": 40,
           "tp_cap_ticks": 200},
}

FEAT_COLS = [
    "ts_event", "high", "low", "close",
    "position_in_range", "finish_strength", "im_cross_delta_agreement_5",
    "delta_bar", "time_to_session_close_norm", "dist_1d_max_ticks_pct",
    "delta_day_dir", "dist_vwap_d_pct", "rvol", "ctx_delta_exhaustion",
    "vwap_slope_10", "dist_mq_put_pct", "n_naked_poc_within_0_5pct",
    # BIAS ENGINE MTF :
    "vwap_d", "total_vol",
]

# ───────────────────────── BIAS ENGINE MTF ─────────────────────────
# Reproduction read_mtf_bias (DASHBOARD/api/readers.py).
_TFS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
_N_BARS = {"1m": 10, "5m": 6, "15m": 4, "1h": 4}
_MOM_NORM = {"1m": 0.1, "5m": 0.2, "15m": 0.3, "1h": 0.5}


def _aggregate(bars, tf_min):
    if tf_min <= 1:
        return bars
    interval = tf_min * 60
    agg, cur = [], None
    for b in bars:
        bucket = (b["time"] // interval) * interval
        if cur is None or cur["time"] != bucket:
            if cur:
                agg.append(cur)
            cur = dict(b)
            cur["time"] = bucket
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["delta"] = cur.get("delta", 0) + b.get("delta", 0)
            cur["volume"] = cur.get("volume", 0) + b.get("volume", 0)
            cur["vwap"] = b["vwap"]
    if cur:
        agg.append(cur)
    return agg


def _calc_bias_score(bars, n_bars, tf_name):
    subset = bars[-n_bars:] if len(bars) >= n_bars else bars
    if not subset:
        return 0.0
    last = subset[-1]
    vwap, price = last.get("vwap", 0), last["close"]
    vwap_score = 0.0
    if vwap > 0:
        vwap_score = max(-1, min(1, ((price - vwap) / TICK) / 60))
    total_delta = sum(b.get("delta", 0) for b in subset)
    total_vol = sum(b.get("volume", 1) for b in subset)
    delta_score = max(-1, min(1, (total_delta / max(total_vol, 1)) * 5))
    first_open, last_close = subset[0]["open"], subset[-1]["close"]
    if first_open > 0:
        change_pct = (last_close - first_open) / first_open * 100
        momentum_score = max(-1, min(1, change_pct / _MOM_NORM.get(tf_name, 0.3)))
    else:
        momentum_score = 0.0
    return round(0.4 * vwap_score + 0.3 * delta_score + 0.3 * momentum_score, 3)


def compute_mtf(day_bars, upto_idx):
    """Retourne (bulls, bears) — nb de TF alignes, calcule sur day_bars[:upto_idx+1]."""
    sub = day_bars[:upto_idx + 1]
    if len(sub) < 5:
        return 0, 0
    bulls = bears = 0
    for tf_name, tf_min in _TFS.items():
        score = _calc_bias_score(_aggregate(sub, tf_min), _N_BARS[tf_name], tf_name)
        if score > 0.25:
            bulls += 1
        elif score < -0.25:
            bears += 1
    return bulls, bears


def load_symbol(sym):
    """Charge le dataset live_enriched (jsonl) — meme moteur que le bot live.

    sym : "ES" / "NQ" (nom court du dossier live_enriched).
    """
    files = sorted(glob.glob(f"DATA/live_enriched/{sym}/*.jsonl"))
    rows = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    df = pd.DataFrame(rows)
    df = df[[c for c in FEAT_COLS if c in df.columns]]
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    df["ts"] = df["ts_event"].astype("int64") // 1_000_000_000
    df["ym"] = df["ts_event"].dt.strftime("%Y-%m")
    df["day"] = df["ts_event"].dt.strftime("%Y-%m-%d")
    return df


def precompute_mtf(df):
    """Pre-calcule (bulls, bears) MTF par index de barre. Intraday, par jour."""
    mtf = [(0, 0)] * len(df)
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    deltas = df["delta_bar"].fillna(0).tolist()
    vwaps = df["vwap_d"].fillna(0).tolist()
    vols = df["total_vol"].fillna(0).tolist()
    ts = df["ts"].tolist()
    days = df["day"].tolist()

    i = 0
    n = len(df)
    while i < n:
        j = i
        while j < n and days[j] == days[i]:
            j += 1
        # barres du jour [i, j)
        day_bars = []
        for k in range(i, j):
            day_bars.append({
                "time": int(ts[k]),
                "open": float(closes[k]) if k == i else float(closes[k - 1]),
                "high": float(highs[k]), "low": float(lows[k]),
                "close": float(closes[k]), "delta": float(deltas[k]),
                "vwap": float(vwaps[k]), "volume": float(vols[k]),
            })
        for k in range(i, j):
            mtf[k] = compute_mtf(day_bars, k - i)
        i = j
    return mtf


def simulate_trade(df, entry_idx, side, sym):
    """Retourne (pnl_ticks, exit_idx). exit_idx = index de la barre de sortie."""
    cfg = TRAILING_CONFIG[sym]
    entry = float(df.at[entry_idx, "close"])
    e_ts = int(df.at[entry_idx, "ts"])
    sl_pts = cfg["sl_ticks"] * TICK
    tp_pts = cfg["tp_cap_ticks"] * TICK
    act, dist = cfg["trailing_activation_ticks"], cfg["trailing_distance_ticks"]
    timeout_s = cfg["timeout_minutes"] * 60
    sl_price = entry - sl_pts if side == "LONG" else entry + sl_pts
    tp_price = entry + tp_pts if side == "LONG" else entry - tp_pts
    mfe, trail_stop = 0.0, None
    n = len(df)
    for i in range(entry_idx + 1, n):
        hi, lo, ts = float(df.at[i, "high"]), float(df.at[i, "low"]), int(df.at[i, "ts"])
        if side == "LONG":
            if lo <= sl_price:
                return -cfg["sl_ticks"] - COST_TICKS, i
            if trail_stop is not None and lo <= trail_stop:
                return (trail_stop - entry) / TICK - COST_TICKS, i
            if hi >= tp_price:
                return cfg["tp_cap_ticks"] - COST_TICKS, i
            fav = (hi - entry) / TICK
            if fav > mfe:
                mfe = fav
            if mfe >= act:
                nt = entry + (mfe - dist) * TICK
                if trail_stop is None or nt > trail_stop:
                    trail_stop = nt
        else:
            if hi >= sl_price:
                return -cfg["sl_ticks"] - COST_TICKS, i
            if trail_stop is not None and hi >= trail_stop:
                return (entry - trail_stop) / TICK - COST_TICKS, i
            if lo <= tp_price:
                return cfg["tp_cap_ticks"] - COST_TICKS, i
            fav = (entry - lo) / TICK
            if fav > mfe:
                mfe = fav
            if mfe >= act:
                nt = entry - (mfe - dist) * TICK
                if trail_stop is None or nt < trail_stop:
                    trail_stop = nt
        if ts - e_ts >= timeout_s:
            c = float(df.at[i, "close"])
            pnl = (c - entry) / TICK if side == "LONG" else (entry - c) / TICK
            return pnl - COST_TICKS, i
    c = float(df.at[n - 1, "close"])
    pnl = (c - entry) / TICK if side == "LONG" else (entry - c) / TICK
    return pnl - COST_TICKS, n - 1


def backtest_setup(df, mtf, setup_name, sym, min_align):
    """min_align : 0 = baseline, 3 = MTF>=3/4, 4 = MTF==4/4 dans le sens du signal.

    1 position max : apres un trade on reprend le scan APRES la barre d'exit
    (pas de chevauchement — reproduit le comportement du bot live).
    """
    side = SETUP_REGISTRY[setup_name]["side"]
    rows = df.to_dict("records")
    trades, i, n = [], 0, len(df)
    while i < n:
        triggered = evaluate_all_setups(rows[i], sym)
        if any(t["name"] == setup_name for t in triggered):
            if min_align > 0:
                bulls, bears = mtf[i]
                aligned = (bulls >= min_align) if side == "LONG" else (bears >= min_align)
                if not aligned:
                    i += 1
                    continue
            pnl, exit_idx = simulate_trade(df, i, side, sym)
            trades.append({"entry_ym": df.at[i, "ym"], "pnl_ticks": pnl})
            i = exit_idx + 1   # 1 position max : reprend apres l'exit
        else:
            i += 1
    return trades


def summarize(trades):
    if not trades:
        return {"n": 0, "pf": 0.0, "wr": 0.0, "total": 0.0}
    wins = [t["pnl_ticks"] for t in trades if t["pnl_ticks"] > 0]
    losses = [t["pnl_ticks"] for t in trades if t["pnl_ticks"] <= 0]
    gains, pertes = sum(wins), -sum(losses)
    pf = gains / pertes if pertes > 0 else (999.0 if gains > 0 else 0.0)
    return {"n": len(trades), "pf": pf,
            "wr": 100.0 * len(wins) / len(trades),
            "total": sum(t["pnl_ticks"] for t in trades)}


def main():
    print("Chargement v4_enriched ES + NQ...")
    data = {s: load_symbol(s) for s in ("NQ", "ES")}
    print("Pre-calcul BIAS ENGINE MTF (intraday, 4 TF)...")
    mtf = {s: precompute_mtf(data[s]) for s in ("NQ", "ES")}
    for s in ("NQ", "ES"):
        months = sorted(data[s]["ym"].unique())
        print(f"  {s}: {len(data[s])} barres, {months[0]} -> {months[-1]}")

    print()
    print("=" * 100)
    print(f"{'SETUP':<24} {'variante':<12} | {'n':>6} {'PF':>7} {'WR%':>6} {'ticks':>9}")
    print("-" * 100)
    for name in sorted(SETUP_REGISTRY):
        syms = SETUP_REGISTRY[name]["symbols"]
        line_printed = False
        for min_align, label in ((0, "BASELINE"), (3, "MTF>=3/4"), (4, "MTF==4/4")):
            trades = []
            for sym in syms:
                trades += backtest_setup(data[sym], mtf[sym], name, sym, min_align)
            r = summarize(trades)
            prefix = name if not line_printed else ""
            line_printed = True
            print(f"{prefix:<24} {label:<12} | {r['n']:>6} {r['pf']:>7.2f} "
                  f"{r['wr']:>6.1f} {r['total']:>+9.0f}")
        print("-" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
