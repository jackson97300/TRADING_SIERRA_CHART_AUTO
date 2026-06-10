"""
Backtest multi-chantiers (17/04/2026) — Optimisation des 3 setups pro de Jackson :

  Chantier 1 : Div optim — grid search entry_delay x volume x absorb confirmation
  Chantier 2 : Double top/bottom rigoureux (retest_high/low + delta_div + confirm)
  Chantier 3 : Trend + confluence (Color Up + Edge Buy + Diag Imbalance + Niveau option)

Tous utilisent le framework bracket SL/TP fixe (R:R 1:2, max 40 bars, pessimiste).

USAGE :
    python -X utf8 CORE/backtest_chantiers.py            # 3 chantiers
    python -X utf8 CORE/backtest_chantiers.py --c1       # Chantier 1 seul
    python -X utf8 CORE/backtest_chantiers.py --c2
    python -X utf8 CORE/backtest_chantiers.py --c3
"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rolling_features import RollingFeatures  # noqa: E402

DATA_ROOT = Path("DATA")
TICK_SIZE = 0.25


# ─────────────────────────────────────────────────────────────────────────────
# I/O
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
    # Numeriser colonnes critiques
    for col in ["price", "bar_high", "bar_low", "atr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def prepare(symbol: str) -> pd.DataFrame:
    print(f"[{symbol}] Loading JSONL...")
    df = load_jsonl_dir(symbol)
    if df.empty:
        return df
    print(f"[{symbol}] Computing rolling features ({len(df)} bars)...")
    df = RollingFeatures().compute(df)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# BRACKET SIMULATOR (partage entre chantiers)
# ─────────────────────────────────────────────────────────────────────────────

def simulate_bracket(
    df: pd.DataFrame,
    entry_pos: int,
    direction: int,
    sl_ticks: float,
    rr: float,
    max_bars: int,
) -> dict:
    """Simule bracket : entry au price de la barre entry_pos."""
    if entry_pos >= len(df):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0}
    entry = float(df["price"].iloc[entry_pos])
    if pd.isna(entry):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0}
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
                return {"outcome": "SL", "r": -1.0, "bars": i - entry_pos}
            if bh >= tp_price:
                return {"outcome": "TP", "r": rr, "bars": i - entry_pos}
        else:
            if bh >= sl_price:
                return {"outcome": "SL", "r": -1.0, "bars": i - entry_pos}
            if bl <= tp_price:
                return {"outcome": "TP", "r": rr, "bars": i - entry_pos}
    if end_idx <= entry_pos + 1:
        return {"outcome": "NO_DATA", "r": 0.0, "bars": 0}
    final = df["price"].iloc[end_idx - 1]
    if pd.isna(final):
        return {"outcome": "NO_DATA", "r": 0.0, "bars": end_idx - entry_pos}
    if direction > 0:
        r = (float(final) - entry) / (sl_ticks * TICK_SIZE)
    else:
        r = (entry - float(final)) / (sl_ticks * TICK_SIZE)
    return {"outcome": "TIMEOUT", "r": float(r), "bars": end_idx - 1 - entry_pos}


def aggregate(trades: list[dict], label: str) -> dict:
    if not trades:
        return {"label": label, "n": 0}
    r = pd.Series([t["r"] for t in trades])
    wins = r[r > 0]
    losses = r[r < 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf")
    return {
        "label": label,
        "n": len(trades),
        "tp": sum(1 for t in trades if t["outcome"] == "TP"),
        "sl": sum(1 for t in trades if t["outcome"] == "SL"),
        "to": sum(1 for t in trades if t["outcome"] == "TIMEOUT"),
        "wr": len(wins) / len(r),
        "pf": pf,
        "ev_r": float(r.mean()),
        "total_r": float(r.sum()),
    }


def fmt_row(s: dict) -> str:
    if s["n"] == 0:
        return f"  {s['label']:65s} n=0"
    pf = f"{s['pf']:.2f}" if np.isfinite(s["pf"]) else "inf"
    return (
        f"  {s['label']:65s} "
        f"n={s['n']:4d} WR={s['wr']:.1%} PF={pf:>5s} "
        f"EV={s['ev_r']:+.2f}R totR={s['total_r']:+6.0f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CHANTIER 1 : DIV ENTRY OPTIMIZATION (grid search)
# ─────────────────────────────────────────────────────────────────────────────

def chantier1(symbol: str, df: pd.DataFrame) -> list[dict]:
    """Grid search : entry_delay x rvol_min x absorb_confirm x sl_buffer.

    Base setup : delta_divergence_clean != 0 & div_confluence_dmp >= 2.
    """
    print(f"\n{'=' * 82}")
    print(f"  CHANTIER 1 — DIV OPTIM ({symbol})")
    print(f"{'=' * 82}")

    dd = df["delta_divergence_clean"].fillna(0).astype(int)
    conf_dmp = df["div_confluence_dmp"].fillna(0).astype(int)
    base_mask = (dd != 0) & (conf_dmp >= 2)
    base_idx = df.index[base_mask].tolist()
    print(f"  Base signals (div + conf_dmp>=2) : {len(base_idx)}")

    rvol = pd.to_numeric(df.get("rvol", pd.Series(np.nan, index=df.index)),
                         errors="coerce").fillna(0)
    absorb_bid = pd.to_numeric(df.get("bn_absorb_bid", pd.Series(0, index=df.index)),
                                errors="coerce").fillna(0)
    absorb_ask = pd.to_numeric(df.get("bn_absorb_ask", pd.Series(0, index=df.index)),
                                errors="coerce").fillna(0)
    dist_key = pd.to_numeric(df["div_at_key_level_ticks"], errors="coerce")

    results = []
    entry_delays = [0, 1, 2, 3, 5]
    rvol_mins = [0.0, 1.5]
    absorb_modes = [False, True]
    sl_buffers = [3, 5]
    rr = 2.0
    max_bars = 40

    total_configs = len(entry_delays) * len(rvol_mins) * len(absorb_modes) * len(sl_buffers)
    config_i = 0

    for ed, rvmin, absorb_req, sl_buf in product(
        entry_delays, rvol_mins, absorb_modes, sl_buffers
    ):
        config_i += 1
        trades = []
        for idx in base_idx:
            pos = df.index.get_loc(idx)
            signal_dir = int(dd.iloc[pos])
            entry_pos = pos + ed
            if entry_pos >= len(df):
                continue

            # Confirmation volume sur la barre d'entry
            if rvmin > 0 and rvol.iloc[entry_pos] < rvmin:
                continue
            # Confirmation absorb alignee sur la barre d'entry
            if absorb_req:
                if signal_dir > 0 and absorb_bid.iloc[entry_pos] <= 0:
                    continue
                if signal_dir < 0 and absorb_ask.iloc[entry_pos] <= 0:
                    continue

            raw = dist_key.iloc[pos]
            if pd.isna(raw):
                continue
            sl_ticks = float(raw) + sl_buf
            sl_ticks = max(5.0, min(30.0, sl_ticks))
            res = simulate_bracket(df, entry_pos, signal_dir, sl_ticks, rr, max_bars)
            if res["outcome"] == "NO_DATA":
                continue
            trades.append(res)

        label = (f"delay={ed} rvol>={rvmin:.1f} absorb={'Y' if absorb_req else 'N'} "
                 f"slbuf={sl_buf}")
        agg = aggregate(trades, label)
        results.append(agg)

    # Top 10 by total_R
    sorted_res = sorted(results, key=lambda r: r.get("total_r", -1e9), reverse=True)
    print(f"\n  TOP 10 (by total R) :")
    for r in sorted_res[:10]:
        print(fmt_row(r))

    print(f"\n  BOTTOM 3 (worst) :")
    for r in sorted_res[-3:]:
        print(fmt_row(r))

    # Meilleur config stable : n >= 100 ET PF max
    stable = [r for r in results if r.get("n", 0) >= 100 and np.isfinite(r.get("pf", 0))]
    stable_sorted = sorted(stable, key=lambda r: r["pf"], reverse=True)
    if stable_sorted:
        print(f"\n  BEST STABLE (n>=100, sorted PF) :")
        for r in stable_sorted[:5]:
            print(fmt_row(r))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CHANTIER 2 : DOUBLE TOP / BOTTOM
# ─────────────────────────────────────────────────────────────────────────────

def chantier2(symbol: str, df: pd.DataFrame) -> list[dict]:
    """Backtest double top/bottom : retest_high/low + delta_div + confirmation."""
    print(f"\n{'=' * 82}")
    print(f"  CHANTIER 2 — DOUBLE TOP/BOTTOM ({symbol})")
    print(f"{'=' * 82}")

    req_cols = ["retest_high_delta_div", "retest_low_delta_div",
                "bars_since_retest_high", "bars_since_retest_low",
                "cvd_day_dir", "diag_imbalance"]
    for c in req_cols:
        if c not in df.columns:
            print(f"  [ERR] Colonne {c} manquante")
            return []

    rhdv = pd.to_numeric(df["retest_high_delta_div"], errors="coerce").fillna(0)
    rldv = pd.to_numeric(df["retest_low_delta_div"], errors="coerce").fillna(0)
    bsrh = pd.to_numeric(df["bars_since_retest_high"], errors="coerce").fillna(999)
    bsrl = pd.to_numeric(df["bars_since_retest_low"], errors="coerce").fillna(999)
    cvd_dir = pd.to_numeric(df["cvd_day_dir"], errors="coerce").fillna(0)
    diag = pd.to_numeric(df["diag_imbalance"], errors="coerce").fillna(0)

    # Plusieurs variantes a tester
    configs = [
        ("DT/DB raw", (rhdv == 1), (rldv == 1)),
        ("DT/DB + bsr<=5",
         (rhdv == 1) & (bsrh <= 5),
         (rldv == 1) & (bsrl <= 5)),
        ("DT/DB + bsr<=3",
         (rhdv == 1) & (bsrh <= 3),
         (rldv == 1) & (bsrl <= 3)),
        ("DT + cvd<=0 / DB + cvd>=0",
         (rhdv == 1) & (bsrh <= 5) & (cvd_dir <= 0),
         (rldv == 1) & (bsrl <= 5) & (cvd_dir >= 0)),
        ("DT + diag<0 / DB + diag>0",
         (rhdv == 1) & (bsrh <= 5) & (diag < 0),
         (rldv == 1) & (bsrl <= 5) & (diag > 0)),
        ("DT + cvd<=0 + diag<0 / DB + cvd>=0 + diag>0",
         (rhdv == 1) & (bsrh <= 5) & (cvd_dir <= 0) & (diag < 0),
         (rldv == 1) & (bsrl <= 5) & (cvd_dir >= 0) & (diag > 0)),
    ]

    dist_key = pd.to_numeric(df.get("div_at_key_level_ticks",
                                     pd.Series(np.nan, index=df.index)),
                              errors="coerce")

    results = []
    for label, m_short, m_long in configs:
        trades = []
        # Shorts (double top)
        for idx in df.index[m_short].tolist():
            pos = df.index.get_loc(idx)
            raw = dist_key.iloc[pos]
            sl_ticks = (float(raw) + 5) if pd.notna(raw) else 15.0
            sl_ticks = max(8.0, min(30.0, sl_ticks))
            res = simulate_bracket(df, pos, -1, sl_ticks, 2.0, 40)
            if res["outcome"] != "NO_DATA":
                trades.append(res)
        # Longs (double bottom)
        for idx in df.index[m_long].tolist():
            pos = df.index.get_loc(idx)
            raw = dist_key.iloc[pos]
            sl_ticks = (float(raw) + 5) if pd.notna(raw) else 15.0
            sl_ticks = max(8.0, min(30.0, sl_ticks))
            res = simulate_bracket(df, pos, 1, sl_ticks, 2.0, 40)
            if res["outcome"] != "NO_DATA":
                trades.append(res)
        agg = aggregate(trades, label)
        results.append(agg)
        print(fmt_row(agg))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CHANTIER 3 : TREND + CONFLUENCE (Color Up + Edge + Diag + Niveau option)
# ─────────────────────────────────────────────────────────────────────────────

def chantier3(symbol: str, df: pd.DataFrame) -> list[dict]:
    """Setup manuel de Jackson : trend (VWAP side) + Color Up + Edge Buy + Diag Imbalance >= 600 + niveau option proche."""
    print(f"\n{'=' * 82}")
    print(f"  CHANTIER 3 — TREND + CONFLUENCE ({symbol})")
    print(f"{'=' * 82}")

    def get(col, default=0.0):
        return pd.to_numeric(df.get(col, pd.Series(default, index=df.index)),
                             errors="coerce").fillna(default)

    # Color : ISOLER (up=1 AND dn=0) car les 2 = 1 simultanement = neutre
    # Rule lessons.md : "BN color up=1 ET dn=1 = neutre, pas confirmation"
    up_raw = get("bn_color_up_2").astype(int)
    dn_raw = get("bn_color_dn_2").astype(int)
    color_up = ((up_raw == 1) & (dn_raw == 0)).astype(int)
    color_dn = ((dn_raw == 1) & (up_raw == 0)).astype(int)
    # Edge zones (imbalance) - on combine bar_edge et fp_edge
    edge_buy = get("bar_edge_buy").astype(int)
    edge_sell = get("bar_edge_sell").astype(int)
    fp_edge_buy = get("fp_edge_buy").astype(int)
    fp_edge_sell = get("fp_edge_sell").astype(int)
    edge_buy_any = ((edge_buy == 1) | (fp_edge_buy == 1)).astype(int)
    edge_sell_any = ((edge_sell == 1) | (fp_edge_sell == 1)).astype(int)
    # Diag delta bruts (seuil 600 = parametre SC de Jackson)
    # diag_imbalance est un ratio [-1,+1] normalise, PAS la valeur brute 600
    diag_pos = get("diag_pos_delta")
    diag_neg = get("diag_neg_delta")
    # Trend filter : VWAP side
    above_vwap = get("bool_above_vwap_d").astype(int)
    # Niveau option proche (ticks)
    def near_level_up(thr_ticks: float):
        """Prix proche d'un call/hvl/gex au-dessus = obstacle (pour short)."""
        cols = ["dist_mq_call", "dist_mq_call_0dte", "dist_mq_hvl", "dist_gex_nearest_up"]
        available = [c for c in cols if c in df.columns]
        if not available:
            return pd.Series(False, index=df.index)
        dists = df[available].apply(pd.to_numeric, errors="coerce")
        pos_dists = dists.where(dists > 0)
        min_up = pos_dists.min(axis=1, skipna=True)
        return (min_up <= thr_ticks)

    def near_level_down(thr_ticks: float):
        cols = ["dist_mq_put", "dist_mq_put_0dte", "dist_mq_hvl", "dist_gex_nearest_dn"]
        available = [c for c in cols if c in df.columns]
        if not available:
            return pd.Series(False, index=df.index)
        dists = df[available].apply(pd.to_numeric, errors="coerce")
        neg_dists = dists.where(dists < 0).abs()
        min_dn = neg_dists.min(axis=1, skipna=True)
        return (min_dn <= thr_ticks)

    # Configurations a tester (refactor 17/04 : isoler color + diag bruts)
    configs = [
        # A1. Color isole (up=1 & dn=0)
        ("A1 ColorUp isole / ColorDn isole",
         (color_up == 1),
         (color_dn == 1)),
        # A2. Color + Edge
        ("A2 Color + Edge aligned",
         (color_up == 1) & (edge_buy_any == 1),
         (color_dn == 1) & (edge_sell_any == 1)),
        # A3. Color + Edge + Diag >= 600
        ("A3 Color + Edge + Diag>=600",
         (color_up == 1) & (edge_buy_any == 1) & (diag_pos >= 600),
         (color_dn == 1) & (edge_sell_any == 1) & (diag_neg >= 600)),
        # A4. Color + Edge + Diag + Trend VWAP
        ("A4 Color + Edge + Diag + VWAP trend",
         (color_up == 1) & (edge_buy_any == 1) & (diag_pos >= 600) & (above_vwap == 1),
         (color_dn == 1) & (edge_sell_any == 1) & (diag_neg >= 600) & (above_vwap == 0)),
        # A5. Full : Color + Edge + Diag + Trend + Niveau option <=20t
        ("A5 Full : Color+Edge+Diag+Trend + Niveau<=20t",
         (color_up == 1) & (edge_buy_any == 1) & (diag_pos >= 600) & (above_vwap == 1) & near_level_down(20),
         (color_dn == 1) & (edge_sell_any == 1) & (diag_neg >= 600) & (above_vwap == 0) & near_level_up(20)),
        # B1. Color + Niveau (sans edge/diag)
        ("B1 Color + Niveau<=20t",
         (color_up == 1) & near_level_down(20),
         (color_dn == 1) & near_level_up(20)),
        # B2. Diag bruts seuls >= 600
        ("B2 Diag >= 600 brut (sans color/edge)",
         (diag_pos >= 600),
         (diag_neg >= 600)),
        # B3. Edge + Diag + Niveau
        ("B3 Edge + Diag>=600 + Niveau<=15t",
         (edge_buy_any == 1) & (diag_pos >= 600) & near_level_down(15),
         (edge_sell_any == 1) & (diag_neg >= 600) & near_level_up(15)),
        # B4. Jackson setup variante : Color + Edge + Niveau (assoupli diag)
        ("B4 Color + Edge + Niveau<=15t (no diag filter)",
         (color_up == 1) & (edge_buy_any == 1) & near_level_down(15),
         (color_dn == 1) & (edge_sell_any == 1) & near_level_up(15)),
    ]

    results = []
    for label, m_long, m_short in configs:
        trades = []
        # Longs
        for idx in df.index[m_long].tolist():
            pos = df.index.get_loc(idx)
            res = simulate_bracket(df, pos, 1, 12.0, 2.0, 40)
            if res["outcome"] != "NO_DATA":
                trades.append(res)
        # Shorts
        for idx in df.index[m_short].tolist():
            pos = df.index.get_loc(idx)
            res = simulate_bracket(df, pos, -1, 12.0, 2.0, 40)
            if res["outcome"] != "NO_DATA":
                trades.append(res)
        agg = aggregate(trades, label)
        results.append(agg)
        print(fmt_row(agg))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    run_c1 = "--c1" in sys.argv or not any(f in sys.argv for f in ["--c1", "--c2", "--c3"])
    run_c2 = "--c2" in sys.argv or not any(f in sys.argv for f in ["--c1", "--c2", "--c3"])
    run_c3 = "--c3" in sys.argv or not any(f in sys.argv for f in ["--c1", "--c2", "--c3"])

    for symbol in ["ES", "NQ"]:
        df = prepare(symbol)
        if df.empty:
            continue
        if run_c1:
            chantier1(symbol, df)
        if run_c2:
            chantier2(symbol, df)
        if run_c3:
            chantier3(symbol, df)


if __name__ == "__main__":
    main()
