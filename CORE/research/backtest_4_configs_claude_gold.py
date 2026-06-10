"""Backtest des 4 configurations Claude.com conseillées pour Gold.

Configurations :
  1. VWAP_D SD1/SD2 Mean Reversion (long sur SD-2 oversold, short sur SD+2 overbought)
  2. IB Breakout London/NY overlap (entry cassure ib_high/low avec confirmation flow)
  3. PVWAP + POC Niveaux (rebound depuis prev_vpoc + prev_vah/val)
  4. Cross-Asset Hedge (proxy : LONG MGC quand cross-bear signal ES/NQ via delta+CVD)

Output : PF/WR/n par config + verdict GO/NOGO statistique.

Source : MGC_dataset_v5e_mq_enriched.parquet (4 mois jan-avril 2026, ~85K bars
filtered post target valid).

Usage : python -X utf8 CORE/research/backtest_4_configs_claude_gold.py
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import date
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_mq_enriched.parquet"
OUT_DIR = ROOT / "DATA" / "BACKTEST" / "GOLD"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Constantes Gold
TICK_SIZE = 0.10
TICK_VALUE = 1.0
N_CONTRACTS = 3
COMMISSION_PER_RT = 0.74

# Anti-triche slippage
SLIP_RTH = {"entry": 1.5, "sl": 1.5, "tp": 0.5}
SLIP_ASIA = {"entry": 4.0, "sl": 3.0, "tp": 1.0}


def safe_get(bar, col, default=np.nan):
    if col not in bar:
        return default
    v = bar[col]
    if v is None or pd.isna(v):
        return default
    return v


def detect_session(bar):
    if int(safe_get(bar, "is_in_us_cash", 0) or 0) == 1:
        return "RTH"
    if int(safe_get(bar, "is_in_us_after", 0) or 0) == 1:
        return "RTH"
    if int(safe_get(bar, "is_in_london", 0) or 0) == 1:
        return "LONDON"
    if int(safe_get(bar, "is_in_asia", 0) or 0) == 1:
        return "ASIA"
    return "OTHER"


def is_news_bar(bar):
    rvol = float(safe_get(bar, "rvol", 1.0))
    if rvol > 3.0:
        return True
    atr_ticks = float(safe_get(bar, "atr", 17.0))
    h = float(safe_get(bar, "high", 0))
    l = float(safe_get(bar, "low", 0))
    if atr_ticks > 0 and (h - l) > 2.0 * atr_ticks * TICK_SIZE:
        return True
    for k in ("within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
              "within_news_845_5m", "within_news_900_5m", "within_news_930_5m"):
        if int(safe_get(bar, k, 0) or 0) == 1:
            return True
    return False


# ===========================================================================
# 4 CONFIGURATIONS SIGNAL DETECTION
# ===========================================================================

def signal_config1_vwap_mean_rev(bar):
    """Config 1 — VWAP_D SD2 Mean Reversion.

    LONG si prix touche/dépasse VWAP_D SD-2 (oversold extrême) avec rvol normal.
    SHORT si prix touche/dépasse VWAP_D SD+2 (overbought extrême).
    Filtre : pas de news bar, regime atr normal/high.
    """
    if is_news_bar(bar):
        return None
    # dist_vwap_d_sd2d_pct : distance % de prix au VWAP_D SD-2 (négatif = prix au-dessous SD-2)
    sd2d = safe_get(bar, "dist_vwap_d_sd2d_pct", np.nan)
    sd2u = safe_get(bar, "dist_vwap_d_sd2u_pct", np.nan)

    # LONG mean rev : prix sous VWAP_D SD-2 (dist > 0 = prix au-dessus level, on veut prix au level)
    if pd.notna(sd2d) and abs(sd2d) < 0.002:  # < 0.2% du level = touch
        # Mean rev LONG depuis support extrême
        return "LONG"
    if pd.notna(sd2u) and abs(sd2u) < 0.002:
        return "SHORT"
    return None


def signal_config2_ib_breakout(bar):
    """Config 2 — IB Breakout London/NY overlap.

    Entry breakout ib_high/low pendant overlap 12:30-16:00 UTC + confirmation flow.
    """
    if is_news_bar(bar):
        return None
    # London/NY overlap = mgc_asia_london_overlap_vol > 0 (12:30-16:00 UTC)
    overlap_vol = safe_get(bar, "mgc_asia_london_overlap_vol", 0)
    if overlap_vol == 0:
        return None
    # IB doit être formed
    if int(safe_get(bar, "ib_complete", 0) or 0) != 1:
        return None
    close = safe_get(bar, "close", np.nan)
    ib_high = safe_get(bar, "ib_high", np.nan)
    ib_low = safe_get(bar, "ib_low", np.nan)
    delta_pct = safe_get(bar, "delta_pct", 0)
    rvol = safe_get(bar, "rvol", 0)

    if pd.isna(close) or pd.isna(ib_high) or pd.isna(ib_low):
        return None
    if rvol < 1.2:
        return None

    # Breakout UP avec confirmation flow
    if close > ib_high and delta_pct > 0.2:
        return "LONG"
    if close < ib_low and delta_pct < -0.2:
        return "SHORT"
    return None


def signal_config3_pvwap_poc(bar):
    """Config 3 — PVWAP + POC Niveaux Mean Reversion.

    Trade rebound depuis prev_vpoc (POC veille) avec confirmation orderflow.
    """
    if is_news_bar(bar):
        return None
    dist_pvpoc = safe_get(bar, "dist_prev_vpoc_pct", np.nan)
    dist_pvah = safe_get(bar, "dist_prev_vah_pct", np.nan)
    dist_pval = safe_get(bar, "dist_prev_val_pct", np.nan)

    # Touch prev_vpoc (mean rev pivot)
    if pd.notna(dist_pvpoc) and abs(dist_pvpoc) < 0.001:  # < 0.1% touch
        # Side selon delta
        delta_pct = safe_get(bar, "delta_pct", 0)
        if delta_pct > 0.15:
            return "LONG"
        if delta_pct < -0.15:
            return "SHORT"

    # Touch prev_val (support veille) → LONG rebond
    if pd.notna(dist_pval) and abs(dist_pval) < 0.001:
        return "LONG"
    # Touch prev_vah (résistance veille) → SHORT rejet
    if pd.notna(dist_pvah) and abs(dist_pvah) < 0.001:
        return "SHORT"
    return None


def signal_config4_cross_asset_hedge(bar):
    """Config 4 — Cross-Asset Hedge proxy.

    Difficile à backtester sans état Bot 2/3 historique ES/NQ.
    Proxy : LONG MGC quand cross-bear signal détecté via im_dxy_corr_60d
    + im_real_yields_proxy (real yields baissent = bull Gold = risk-off).

    Logique :
      - im_dxy_corr_60d < -0.6 = DXY corr forte négative (Gold décolle quand $ chute)
      - im_real_yields_proxy < -1.0 = real yields chutent fort
      - regime atr_regime_zscore_60d > 1 = volatility regime élevé (stress)
    """
    if is_news_bar(bar):
        return None
    dxy_corr = safe_get(bar, "im_dxy_corr_60d", np.nan)
    yields = safe_get(bar, "im_real_yields_proxy", np.nan)
    atr_regime = safe_get(bar, "atr_regime_zscore_60d", np.nan)

    if pd.isna(dxy_corr) or pd.isna(yields) or pd.isna(atr_regime):
        return None

    # Risk-off Gold rally setup
    if dxy_corr < -0.6 and yields < -1.0 and atr_regime > 1.0:
        return "LONG"
    # Inverse : risk-on Gold dump
    if dxy_corr > -0.1 and yields > 1.0 and atr_regime > 1.0:
        return "SHORT"
    return None


CONFIGS = {
    "C1_VWAP_SD2_MeanRev": signal_config1_vwap_mean_rev,
    "C2_IB_Breakout_London_NY": signal_config2_ib_breakout,
    "C3_PVWAP_POC_Levels": signal_config3_pvwap_poc,
    "C4_CrossAsset_Hedge_Proxy": signal_config4_cross_asset_hedge,
}


# ===========================================================================
# SIMULATE TRADE
# ===========================================================================

def simulate_trade(df, entry_idx, side, sl_ticks, tp_ticks, timeout_min, session):
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    slip = SLIP_RTH if session in ("RTH",) else SLIP_ASIA
    direction = 1 if side == "LONG" else -1
    entry_with_slip = entry_price + direction * slip["entry"] * TICK_SIZE
    sl_price = entry_with_slip - direction * sl_ticks * TICK_SIZE
    tp_price = entry_with_slip + direction * tp_ticks * TICK_SIZE

    for j in range(1, timeout_min + 1):
        idx = entry_idx + j
        if idx >= len(df):
            break
        bar = df.iloc[idx]
        h = float(bar["high"])
        l = float(bar["low"])
        sl_hit = (direction == 1 and l <= sl_price) or (direction == -1 and h >= sl_price)
        tp_hit = (direction == 1 and h >= tp_price) or (direction == -1 and l <= tp_price)
        if sl_hit and tp_hit:
            exit_p = sl_price - direction * slip["sl"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL_AMB"
        if sl_hit:
            exit_p = sl_price - direction * slip["sl"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL"
        if tp_hit:
            exit_p = tp_price - direction * slip["tp"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "TP"

    # Timeout
    last_idx = min(entry_idx + timeout_min, len(df) - 1)
    exit_p = float(df.iloc[last_idx]["close"]) - direction * slip["sl"] * TICK_SIZE * 0.5
    pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
    pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
    return pnl_d, last_idx - entry_idx, "TIMEOUT"


# ===========================================================================
# RUN BACKTEST PAR CONFIG
# ===========================================================================

def run_config(df, config_name, signal_fn, sl_ticks=50, tp_ticks=100, timeout=30):
    pnls = []
    open_until = -1
    exit_counts = {"TP": 0, "SL": 0, "SL_AMB": 0, "TIMEOUT": 0}
    n_long = 0
    n_short = 0

    for i in range(len(df)):
        if i <= open_until:
            continue
        bar = df.iloc[i].to_dict()
        side = signal_fn(bar)
        if side is None:
            continue
        session = detect_session(bar)
        result = simulate_trade(df, i, side, sl_ticks, tp_ticks, timeout, session)
        if result is None:
            continue
        pnl, dur, reason = result
        pnls.append(pnl)
        open_until = i + dur
        exit_counts[reason] = exit_counts.get(reason, 0) + 1
        if side == "LONG":
            n_long += 1
        else:
            n_short += 1

    if not pnls:
        return {"config": config_name, "n": 0, "pf": 0, "wr": 0, "ev": 0, "total_pnl": 0,
                "n_long": 0, "n_short": 0}

    pnls_arr = np.array(pnls)
    wins = pnls_arr[pnls_arr > 0].sum()
    losses = abs(pnls_arr[pnls_arr < 0].sum())
    pf = wins / losses if losses > 0 else 999.0
    wr = (pnls_arr > 0).sum() / len(pnls_arr) * 100
    ev = pnls_arr.mean()
    total = pnls_arr.sum()
    tp_pct = exit_counts["TP"] / len(pnls) * 100
    sl_pct = (exit_counts["SL"] + exit_counts["SL_AMB"]) / len(pnls) * 100
    timeout_pct = exit_counts["TIMEOUT"] / len(pnls) * 100

    return {
        "config": config_name, "n": len(pnls),
        "pf": round(pf, 3), "wr": round(wr, 1),
        "ev": round(ev, 2), "total_pnl": round(total, 2),
        "n_long": n_long, "n_short": n_short,
        "tp_pct": round(tp_pct, 1), "sl_pct": round(sl_pct, 1),
        "timeout_pct": round(timeout_pct, 1),
    }


def main():
    print(f"=== BACKTEST 4 CONFIGS CLAUDE.COM GOLD ===\n")
    print(f"  Source : {INPUT}")
    df = pd.read_parquet(INPUT)
    print(f"  Shape : {df.shape}")
    print(f"  Range : {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # Sort by ts
    df = df.sort_values("ts_event").reset_index(drop=True)

    # Run each config
    print(f"\n  Params communs : SL=50t TP=100t timeout=30min, 3 micros, costs réels")
    results = []
    for name, fn in CONFIGS.items():
        print(f"\n  Running {name}...", flush=True)
        r = run_config(df, name, fn)
        print(f"    -> n={r['n']} pf={r['pf']} wr={r['wr']}% ev=${r['ev']} total=${r['total_pnl']}",
              flush=True)
        results.append(r)

    # Verdict
    print(f"\n\n=== RESULTATS ===")
    df_res = pd.DataFrame(results)
    print(df_res.to_string(index=False))

    print(f"\n=== VERDICT PAR CONFIG ===")
    for r in results:
        if r["n"] < 30:
            verdict = "INSUFFICIENT n"
        elif r["pf"] >= 1.5 and r["wr"] >= 50:
            verdict = "GO STRONG"
        elif r["pf"] >= 1.2 and r["wr"] >= 45:
            verdict = "GO MARGINAL"
        elif r["pf"] >= 1.0:
            verdict = "NEUTRAL"
        else:
            verdict = "NOGO"
        print(f"  {r['config']:35s} n={r['n']:5d} PF={r['pf']:5.2f} WR={r['wr']:5.1f}% -> {verdict}")

    out = OUT_DIR / "gold_4configs_claude_results.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved : {out}")


if __name__ == "__main__":
    main()
