"""trade_analysis_report.py — Analyse cross trades Bot 1 + Bot 2 vs features V4/V5.

Produit DOCS/TRADE_ANALYSIS_REPORT.md avec :
  1. Win rate par heure ET, jour semaine, VIX regime
  2. Top 10 features les plus differentes winners vs losers (Welch t-test + effect size)
  3. Filtres funnel rejetant des trades qui auraient ete gagnants (simulation Triple Barrier)
  4. Comparaison Bot 1 vs Bot 2 sur trades simultanes (overlap fenetre 30min)
  5. Performance par type de wall SL (Tier 1/2/3)

Created : 2026-05-02 dimanche soir post-V5 NO-GO (Jackson demande analyse paper trading)
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = ROOT / "DATA" / "PAPER_TRADES"
V4_DIR = ROOT / "DATA" / "datasets" / "v4_enriched"
LOGS_REJ = ROOT / "LOGS" / "rejections"
LOGS_FUNNEL = ROOT / "LOGS" / "funnel"
OUTPUT = ROOT / "DOCS" / "TRADE_ANALYSIS_REPORT.md"


# ═══════════════════════════════════════════════════════════════════
# 1. CHARGEMENT TRADES
# ═══════════════════════════════════════════════════════════════════

def load_bot1_trades() -> pd.DataFrame:
    """Bot 1 = mia_paper_trader (Sim3, DMP Sierra Chart)."""
    rows = []
    for fp in sorted(PAPER_DIR.glob("*_trades.jsonl")):
        if "databento" in fp.name:
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df["bot"] = "bot1"
    return df


def load_bot2_trades() -> pd.DataFrame:
    """Bot 2 = databento_paper_trader (Sim2, parquet V4 enrichi)."""
    rows = []
    for fp in sorted(PAPER_DIR.glob("*_databento_trades.jsonl")):
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df["bot"] = "bot2"
    return df


def add_common_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Heure ET, jour semaine, winner flag."""
    if df.empty:
        return df
    et = df["entry_time"].dt.tz_convert("America/New_York")
    df["hour_et"] = et.dt.hour
    df["dow_et"] = et.dt.day_name()
    df["date_et"] = et.dt.date
    df["winner"] = df["pnl_usd"] > 0
    return df


# ═══════════════════════════════════════════════════════════════════
# 2. CROSS V4 FEATURES POUR BOT 1
# ═══════════════════════════════════════════════════════════════════

def load_v4_parquet(symbol: str, months: list[tuple[int, int]]) -> pd.DataFrame:
    """Charge V4 enriched pour les mois requis. months = [(year, month), ...]."""
    parts = []
    for year, month in months:
        fp = V4_DIR / f"symbol={symbol}.c.0" / f"year={year}" / f"month={month:02d}" / "data.parquet"
        if fp.exists():
            parts.append(pd.read_parquet(fp))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    return df.sort_values("ts_event").reset_index(drop=True)


def cross_bot1_with_v4(bot1: pd.DataFrame) -> pd.DataFrame:
    """merge_asof backward pour rattacher chaque trade Bot 1 a la barre V4 la plus recente."""
    if bot1.empty:
        return bot1
    months_needed = set()
    for ts in bot1["entry_time"]:
        et = ts.tz_convert("America/New_York")
        months_needed.add((et.year, et.month))
        # safety : aussi le mois UTC (cas rollover ET<->UTC)
        months_needed.add((ts.year, ts.month))
    out = []
    for sym in bot1["symbol"].unique():
        v4 = load_v4_parquet(sym, sorted(months_needed))
        if v4.empty:
            continue
        sub = bot1[bot1["symbol"] == sym].copy().sort_values("entry_time")
        merged = pd.merge_asof(
            sub, v4, left_on="entry_time", right_on="ts_event",
            direction="backward", tolerance=pd.Timedelta("5min"),
            suffixes=("", "_v4"),
        )
        out.append(merged)
    if not out:
        return bot1
    return pd.concat(out, ignore_index=True)


# ═══════════════════════════════════════════════════════════════════
# 3. WIN RATE ANALYSES
# ═══════════════════════════════════════════════════════════════════

def wr_by_dimension(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    """WR + n_trades + pnl par dimension."""
    if df.empty or dim not in df.columns:
        return pd.DataFrame()
    g = df.groupby(dim).agg(
        n_trades=("winner", "size"),
        n_winners=("winner", "sum"),
        pnl_usd_sum=("pnl_usd", "sum"),
        pnl_usd_mean=("pnl_usd", "mean"),
    )
    g["wr_pct"] = (g["n_winners"] / g["n_trades"] * 100).round(1)
    g["pnl_usd_sum"] = g["pnl_usd_sum"].round(2)
    g["pnl_usd_mean"] = g["pnl_usd_mean"].round(2)
    return g.reset_index().sort_values("n_trades", ascending=False)


def vix_regime_label(vix: float) -> str:
    if pd.isna(vix):
        return "UNKNOWN"
    if vix < 15:
        return "LOW (<15)"
    if vix < 20:
        return "MODERATE (15-20)"
    if vix < 25:
        return "ELEVATED (20-25)"
    return "HIGH (>=25)"


def extract_vix(row: dict) -> float:
    """Extrait VIX du trade (Bot 1: exit_context.vix, Bot 2: features_at_entry.vix_level)."""
    # Bot 1
    ec = row.get("exit_context")
    if isinstance(ec, dict):
        v = ec.get("vix")
        if v is not None and not pd.isna(v):
            return float(v)
    dmp = row.get("dmp_bar_at_exit")
    if isinstance(dmp, dict):
        v = dmp.get("vix_level")
        if v is not None and not pd.isna(v):
            return float(v)
    # Bot 2
    feats = row.get("features_at_entry")
    if isinstance(feats, dict):
        v = feats.get("vix_level") or feats.get("vix")
        if v is not None and not pd.isna(v):
            return float(v)
    return float("nan")


# ═══════════════════════════════════════════════════════════════════
# 4. TOP FEATURES WINNERS VS LOSERS
# ═══════════════════════════════════════════════════════════════════

def features_winners_vs_losers(df: pd.DataFrame, feature_cols: list[str],
                                top_n: int = 10) -> pd.DataFrame:
    """Welch t-test + Cohen's d sur chaque feature numerique. Trie par |d|."""
    if df.empty or "winner" not in df.columns:
        return pd.DataFrame()
    win = df[df["winner"] == True]
    los = df[df["winner"] == False]
    if len(win) < 5 or len(los) < 5:
        return pd.DataFrame()
    rows = []
    for col in feature_cols:
        if col not in df.columns:
            continue
        try:
            w = pd.to_numeric(win[col], errors="coerce").dropna()
            l = pd.to_numeric(los[col], errors="coerce").dropna()
            if len(w) < 3 or len(l) < 3:
                continue
            if w.std() < 1e-12 and l.std() < 1e-12:
                continue
            t, p = stats.ttest_ind(w, l, equal_var=False, nan_policy="omit")
            pooled_std = np.sqrt((w.std() ** 2 + l.std() ** 2) / 2)
            d = (w.mean() - l.mean()) / pooled_std if pooled_std > 1e-12 else 0.0
            rows.append({
                "feature": col,
                "mean_win": round(float(w.mean()), 4),
                "mean_loss": round(float(l.mean()), 4),
                "diff": round(float(w.mean() - l.mean()), 4),
                "cohen_d": round(float(d), 3),
                "p_value": round(float(p), 4),
                "n_win": len(w),
                "n_loss": len(l),
            })
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["abs_d"] = out["cohen_d"].abs()
    out = out.sort_values("abs_d", ascending=False).head(top_n).drop(columns=["abs_d"])
    return out


def explode_bot2_features(bot2: pd.DataFrame) -> pd.DataFrame:
    """Bot 2 a features_at_entry comme dict. Explode en cols."""
    if bot2.empty or "features_at_entry" not in bot2.columns:
        return bot2
    feats_list = []
    for f in bot2["features_at_entry"]:
        if isinstance(f, dict):
            feats_list.append(f)
        else:
            feats_list.append({})
    feats_df = pd.DataFrame(feats_list)
    return pd.concat([bot2.reset_index(drop=True), feats_df.reset_index(drop=True)], axis=1)


# ═══════════════════════════════════════════════════════════════════
# 5. FUNNEL REJETS — SIMULATION TRIPLE BARRIER
# ═══════════════════════════════════════════════════════════════════

def load_rejections() -> pd.DataFrame:
    """Charge tous les rejections Bot 1 paper."""
    rows = []
    for fp in sorted(LOGS_REJ.glob("*paper.jsonl")):
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def simulate_triple_barrier(rej: pd.DataFrame, sl_ticks: int = 16, tp_ticks: int = 32,
                             horizon_min: int = 30, tick_size: float = 0.25) -> pd.DataFrame:
    """Pour chaque rejet, simule un trade fixed-barrier sur V4 parquet.

    Retourne ratio winner si trade avait pris place.
    """
    if rej.empty:
        return pd.DataFrame()
    # Charger V4 pour mois requis
    months = set()
    for ts in rej["ts"]:
        months.add((ts.year, ts.month))
    v4_es = load_v4_parquet("ES", sorted(months))
    v4_nq = load_v4_parquet("NQ", sorted(months))
    out = []
    for _, r in rej.iterrows():
        sym = r.get("sym")
        direction = r.get("direction")
        ts = r["ts"]
        if direction not in ("LONG", "SHORT"):
            continue
        v4 = v4_es if sym == "ES" else v4_nq
        if v4.empty:
            continue
        # Barre courante : derniere barre <= ts
        idx = v4["ts_event"].searchsorted(ts, side="right") - 1
        if idx < 0 or idx >= len(v4):
            continue
        entry_price = float(v4.iloc[idx]["close"]) if "close" in v4.columns else None
        if entry_price is None or pd.isna(entry_price):
            continue
        # Horizon barres futures
        end_idx = min(idx + horizon_min, len(v4) - 1)
        future = v4.iloc[idx + 1:end_idx + 1]
        if future.empty or "high" not in future.columns or "low" not in future.columns:
            continue
        sl_pts = sl_ticks * tick_size
        tp_pts = tp_ticks * tick_size
        if direction == "LONG":
            sl_price = entry_price - sl_pts
            tp_price = entry_price + tp_pts
            hit_tp = (future["high"] >= tp_price).idxmax() if (future["high"] >= tp_price).any() else None
            hit_sl = (future["low"] <= sl_price).idxmax() if (future["low"] <= sl_price).any() else None
        else:
            sl_price = entry_price + sl_pts
            tp_price = entry_price - tp_pts
            hit_tp = (future["low"] <= tp_price).idxmax() if (future["low"] <= tp_price).any() else None
            hit_sl = (future["high"] >= sl_price).idxmax() if (future["high"] >= sl_price).any() else None
        if hit_tp is not None and (hit_sl is None or hit_tp < hit_sl):
            outcome = "TP"
        elif hit_sl is not None:
            outcome = "SL"
        else:
            outcome = "TIMEOUT"
        out.append({
            "ts": ts, "sym": sym, "direction": direction,
            "step": r.get("step"), "reason": r.get("reason"),
            "outcome_simu": outcome,
        })
    return pd.DataFrame(out)


def funnel_simu_summary(simu: pd.DataFrame) -> pd.DataFrame:
    """Resume par reason : n_rejets, simu_wr_si_pris (TP / (TP+SL))."""
    if simu.empty:
        return pd.DataFrame()
    g = simu.groupby(["step", "reason", "outcome_simu"]).size().unstack(fill_value=0)
    g["n_rejets"] = g.sum(axis=1)
    if "TP" in g.columns and "SL" in g.columns:
        denom = g["TP"] + g["SL"]
        g["simu_wr_pct"] = np.where(denom > 0, (g["TP"] / denom * 100).round(1), np.nan)
    else:
        g["simu_wr_pct"] = np.nan
    return g.reset_index().sort_values("n_rejets", ascending=False)


# ═══════════════════════════════════════════════════════════════════
# 6. A/B BOT 1 vs BOT 2 SUR TRADES SIMULTANES
# ═══════════════════════════════════════════════════════════════════

def find_simultaneous_trades(bot1: pd.DataFrame, bot2: pd.DataFrame,
                              window_min: int = 30) -> pd.DataFrame:
    """Trades sur meme symbole + direction dans fenetre window_min."""
    if bot1.empty or bot2.empty:
        return pd.DataFrame()
    pairs = []
    for _, t1 in bot1.iterrows():
        candidates = bot2[
            (bot2["symbol"] == t1["symbol"]) &
            (bot2["direction"] == t1["direction"]) &
            ((bot2["entry_time"] - t1["entry_time"]).abs() <= pd.Timedelta(minutes=window_min))
        ]
        for _, t2 in candidates.iterrows():
            pairs.append({
                "symbol": t1["symbol"], "direction": t1["direction"],
                "bot1_entry": t1["entry_time"], "bot2_entry": t2["entry_time"],
                "delta_min": (t2["entry_time"] - t1["entry_time"]).total_seconds() / 60,
                "bot1_pnl": t1["pnl_usd"], "bot2_pnl": t2["pnl_usd"],
                "bot1_outcome": t1["outcome"], "bot2_outcome": t2["outcome"],
                "bot1_winner": t1["winner"], "bot2_winner": t2["winner"],
            })
    return pd.DataFrame(pairs)


# ═══════════════════════════════════════════════════════════════════
# 7. PERFORMANCE PAR TIER WALL SL
# ═══════════════════════════════════════════════════════════════════

def perf_by_sl_tier(bot1: pd.DataFrame) -> pd.DataFrame:
    """Bot 1 a sl_tier (1/2/3). Bot 2 ne l'a pas."""
    if bot1.empty or "sl_tier" not in bot1.columns:
        return pd.DataFrame()
    g = bot1.groupby("sl_tier").agg(
        n_trades=("winner", "size"),
        n_winners=("winner", "sum"),
        pnl_usd_sum=("pnl_usd", "sum"),
        pnl_usd_mean=("pnl_usd", "mean"),
        avg_mae=("mae", "mean"),
        avg_mfe=("mfe", "mean"),
    )
    g["wr_pct"] = (g["n_winners"] / g["n_trades"] * 100).round(1)
    return g.reset_index().sort_values("sl_tier")


def perf_by_sl_wall(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    if df.empty or "sl_wall" not in df.columns:
        return pd.DataFrame()
    g = df.groupby("sl_wall").agg(
        n_trades=("winner", "size"),
        n_winners=("winner", "sum"),
        pnl_usd_sum=("pnl_usd", "sum"),
    )
    g["wr_pct"] = (g["n_winners"] / g["n_trades"] * 100).round(1)
    return g[g["n_trades"] >= 2].reset_index().sort_values("n_trades", ascending=False).head(top_n)


# ═══════════════════════════════════════════════════════════════════
# 8. RAPPORT MARKDOWN
# ═══════════════════════════════════════════════════════════════════

def df_to_md(df: pd.DataFrame, max_rows: int = 50) -> str:
    """Conversion markdown manuelle (evite dependance tabulate)."""
    if df is None or df.empty:
        return "_(aucune donnee)_"
    df = df.head(max_rows).copy()
    # Format numeric pour readability
    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) and not isinstance(x, str) else x)
    cols = list(df.columns)
    lines = []
    lines.append("| " + " | ".join(str(c) for c in cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if pd.isna(v):
                cells.append("")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    print("=" * 70)
    print("TRADE ANALYSIS REPORT - Bot 1 + Bot 2 + Cross V4 features")
    print("=" * 70)

    # ─── 1. CHARGEMENT ─────────────────────────────────────────────
    bot1 = add_common_cols(load_bot1_trades())
    bot2 = add_common_cols(load_bot2_trades())
    print(f"\n[load] Bot 1 : {len(bot1)} trades | Bot 2 : {len(bot2)} trades")

    if not bot1.empty:
        bot1["vix"] = bot1.apply(extract_vix, axis=1)
        bot1["vix_regime"] = bot1["vix"].apply(vix_regime_label)
    if not bot2.empty:
        bot2 = explode_bot2_features(bot2)
        bot2["vix"] = bot2.apply(
            lambda r: float(r["vix_level"]) if pd.notna(r.get("vix_level")) else extract_vix(r),
            axis=1,
        )
        bot2["vix_regime"] = bot2["vix"].apply(vix_regime_label)

    # ─── 2. CROSS V4 POUR BOT 1 ────────────────────────────────────
    print("[cross] Cross Bot 1 trades with V4 parquet...")
    bot1_v4 = cross_bot1_with_v4(bot1) if not bot1.empty else bot1
    print(f"[cross] Bot 1 trades enriched : {len(bot1_v4)} (originaux {len(bot1)})")

    # ─── 3. WR BY DIMENSION ────────────────────────────────────────
    all_trades = pd.concat([bot1, bot2], ignore_index=True) if (not bot1.empty or not bot2.empty) else pd.DataFrame()

    wr_hour_b1 = wr_by_dimension(bot1, "hour_et")
    wr_hour_b2 = wr_by_dimension(bot2, "hour_et")
    wr_dow_b1 = wr_by_dimension(bot1, "dow_et")
    wr_dow_b2 = wr_by_dimension(bot2, "dow_et")
    wr_vix_b1 = wr_by_dimension(bot1, "vix_regime")
    wr_vix_b2 = wr_by_dimension(bot2, "vix_regime")
    wr_sym_b1 = wr_by_dimension(bot1, "symbol")
    wr_sym_b2 = wr_by_dimension(bot2, "symbol")
    wr_dir_b1 = wr_by_dimension(bot1, "direction")
    wr_dir_b2 = wr_by_dimension(bot2, "direction")

    # ─── 4. TOP FEATURES WINNERS VS LOSERS ─────────────────────────
    # Bot 1 : depuis V4 cross
    feat_cols_b1 = []
    if not bot1_v4.empty:
        # Filter numeric, exclude trade meta cols
        exclude = {"pnl_usd", "pnl_ticks", "mae", "mfe", "duration_sec", "bars_held",
                   "sl_ticks", "tp_ticks", "rr_ratio", "expected_payoff_usd",
                   "realized_vs_expected_pct", "n_micros", "winner", "vix",
                   "entry_price", "exit_price", "sl_price", "tp_price",
                   "slip_entry_ticks", "slip_exit_ticks"}
        feat_cols_b1 = [c for c in bot1_v4.columns
                        if c not in exclude
                        and pd.api.types.is_numeric_dtype(bot1_v4[c])
                        and bot1_v4[c].notna().sum() >= 5]
    top_features_b1 = features_winners_vs_losers(bot1_v4, feat_cols_b1, top_n=10)

    # Bot 2 : depuis features_at_entry
    feat_cols_b2 = []
    if not bot2.empty:
        exclude = {"pnl_usd", "pnl_ticks", "duration_sec", "sl_ticks", "tp_ticks",
                   "n_micros", "winner", "vix", "entry_price", "exit_price",
                   "bull_pts_entry", "bear_pts_entry", "n_features_at_entry"}
        feat_cols_b2 = [c for c in bot2.columns
                        if c not in exclude
                        and pd.api.types.is_numeric_dtype(bot2[c])
                        and bot2[c].notna().sum() >= 5]
    top_features_b2 = features_winners_vs_losers(bot2, feat_cols_b2, top_n=10)

    # ─── 5. FUNNEL REJETS ──────────────────────────────────────────
    rej = load_rejections()
    print(f"[funnel] Rejections charges : {len(rej)}")
    funnel_summary = pd.DataFrame()
    if not rej.empty:
        rej_top = rej.groupby(["step", "reason"]).size().reset_index(name="n").sort_values("n", ascending=False)
        # Echantillon pour simulation (max 1000 lignes pour eviter explosion temps)
        rej_sample = rej.sample(min(len(rej), 1000), random_state=42) if len(rej) > 1000 else rej
        print(f"[funnel] Simu Triple Barrier sur {len(rej_sample)} rejets...")
        simu = simulate_triple_barrier(rej_sample, sl_ticks=16, tp_ticks=32, horizon_min=30)
        print(f"[funnel] Simu retournee : {len(simu)} lignes")
        funnel_summary = funnel_simu_summary(simu)
    else:
        rej_top = pd.DataFrame()

    # ─── 6. A/B BOT 1 vs BOT 2 ─────────────────────────────────────
    ab_pairs = find_simultaneous_trades(bot1, bot2, window_min=30) if (not bot1.empty and not bot2.empty) else pd.DataFrame()

    # ─── 7. TIER WALLS ─────────────────────────────────────────────
    tier_perf = perf_by_sl_tier(bot1)
    wall_perf_b1 = perf_by_sl_wall(bot1)
    wall_perf_b2 = perf_by_sl_wall(bot2)

    # ─── 8. ECRITURE RAPPORT ───────────────────────────────────────
    print(f"\n[report] Ecriture {OUTPUT}")
    n_b1 = len(bot1)
    n_b2 = len(bot2)
    wr_b1 = (bot1["winner"].mean() * 100).round(1) if n_b1 > 0 else "N/A"
    wr_b2 = (bot2["winner"].mean() * 100).round(1) if n_b2 > 0 else "N/A"
    pnl_b1 = bot1["pnl_usd"].sum() if n_b1 > 0 else 0
    pnl_b2 = bot2["pnl_usd"].sum() if n_b2 > 0 else 0
    days_b1 = bot1["date_et"].nunique() if n_b1 > 0 else 0
    days_b2 = bot2["date_et"].nunique() if n_b2 > 0 else 0

    md = []
    md.append(f"# Trade Analysis Report — Bot 1 + Bot 2 paper trading\n")
    md.append(f"**Genere** : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    md.append(f"**Source** : `DATA/PAPER_TRADES/*.jsonl` + `DATA/datasets/v4_enriched/`")
    md.append(f"**Methodologie** : cross trades vs features V4 par `merge_asof backward 5min`, t-test Welch winners/losers, simu Triple Barrier rejets fixed (SL=16t TP=32t horizon=30min)\n")

    md.append("## 0. Resume executif\n")
    md.append("| Bot | Trades | Jours | WR | PnL total $ | PnL/trade $ |")
    md.append("|-----|--------|-------|----|-------------|-------------|")
    md.append(f"| **Bot 1** Sim3 (DMP Sierra) | {n_b1} | {days_b1} | {wr_b1}% | {pnl_b1:.2f} | {pnl_b1/max(n_b1,1):.2f} |")
    md.append(f"| **Bot 2** Sim2 (Databento V4) | {n_b2} | {days_b2} | {wr_b2}% | {pnl_b2:.2f} | {pnl_b2/max(n_b2,1):.2f} |")
    md.append("")

    md.append("## 1. Win rate par dimension\n")
    md.append("### 1.1 Par symbole\n")
    md.append("**Bot 1** :")
    md.append(df_to_md(wr_sym_b1))
    md.append("\n**Bot 2** :")
    md.append(df_to_md(wr_sym_b2))

    md.append("\n### 1.2 Par direction\n")
    md.append("**Bot 1** :")
    md.append(df_to_md(wr_dir_b1))
    md.append("\n**Bot 2** :")
    md.append(df_to_md(wr_dir_b2))

    md.append("\n### 1.3 Par heure ET\n")
    md.append("**Bot 1** :")
    md.append(df_to_md(wr_hour_b1.sort_values("hour_et")))
    md.append("\n**Bot 2** :")
    md.append(df_to_md(wr_hour_b2.sort_values("hour_et")))

    md.append("\n### 1.4 Par jour de semaine ET\n")
    md.append("**Bot 1** :")
    md.append(df_to_md(wr_dow_b1))
    md.append("\n**Bot 2** :")
    md.append(df_to_md(wr_dow_b2))

    md.append("\n### 1.5 Par regime VIX\n")
    md.append("**Bot 1** :")
    md.append(df_to_md(wr_vix_b1))
    md.append("\n**Bot 2** :")
    md.append(df_to_md(wr_vix_b2))

    md.append("\n## 2. Top 10 features differentes winners vs losers (Welch t-test + Cohen's d)\n")
    md.append("Effect size |d| : 0.2=small, 0.5=medium, 0.8=large. p<0.05 statistiquement different.\n")
    md.append("### 2.1 Bot 1 (V4 enriched cross)")
    md.append(df_to_md(top_features_b1))
    md.append("\n### 2.2 Bot 2 (features_at_entry)")
    md.append(df_to_md(top_features_b2))

    md.append("\n## 3. Funnel rejets — simulation Triple Barrier hypothetique\n")
    md.append(f"Rejets totaux Bot 1 paper : **{len(rej)}** (sur {rej['ts'].dt.date.nunique() if len(rej) else 0} jours).")
    md.append("Sim TB avec SL=16t TP=32t horizon=30min (RR 2:1) : si trade aurait ete pris, quel outcome ?\n")
    md.append("**Top raisons de rejet** :")
    md.append(df_to_md(rej_top.head(20)))
    md.append("\n**Simulation Triple Barrier (winner % theorique si rejet aurait passe)** :")
    md.append(df_to_md(funnel_summary.head(20)))
    md.append("\n_Lecture_ : si `simu_wr_pct >= 50%`, le filtre rejette des trades qui auraient ete gagnants en moyenne (mais cette simu ignore les costs/slippage et utilise barriers fixes generiques, pas les SL/TP reels du bot).")

    md.append("\n## 4. Bot 1 vs Bot 2 sur trades simultanes (overlap 30min)\n")
    if not ab_pairs.empty:
        n_pairs = len(ab_pairs)
        b1_better = ((ab_pairs["bot1_pnl"] > ab_pairs["bot2_pnl"]) & (ab_pairs["bot1_winner"] != ab_pairs["bot2_winner"])).sum()
        b2_better = ((ab_pairs["bot2_pnl"] > ab_pairs["bot1_pnl"]) & (ab_pairs["bot1_winner"] != ab_pairs["bot2_winner"])).sum()
        both_w = (ab_pairs["bot1_winner"] & ab_pairs["bot2_winner"]).sum()
        both_l = (~ab_pairs["bot1_winner"] & ~ab_pairs["bot2_winner"]).sum()
        md.append(f"**{n_pairs} paires** trouvees (meme symbol+direction, |delta_entry| <= 30min).")
        md.append(f"- Both winners : **{both_w}** | Both losers : **{both_l}**")
        md.append(f"- Bot 1 gagnant + Bot 2 perdant : **{b1_better}**")
        md.append(f"- Bot 2 gagnant + Bot 1 perdant : **{b2_better}**")
        md.append(f"- Bot 1 PnL pairs : **${ab_pairs['bot1_pnl'].sum():.2f}** | Bot 2 PnL pairs : **${ab_pairs['bot2_pnl'].sum():.2f}**")
        md.append(f"- Delta median entry : **{ab_pairs['delta_min'].median():.1f} min**\n")
        md.append("**Sample pairs** :")
        md.append(df_to_md(ab_pairs.head(20)))
    else:
        md.append("_Aucune paire simultanee trouvee_")

    md.append("\n## 5. Performance par tier wall SL (Bot 1)\n")
    md.append("Tier 1 = mur fort (POC, MQ Call/Put, IB), Tier 2 = mur moyen (VWAP SD, VAH/VAL), Tier 3 = mur faible.\n")
    md.append(df_to_md(tier_perf))

    md.append("\n### 5.1 Top walls SL specifiques (Bot 1, n>=2)")
    md.append(df_to_md(wall_perf_b1))

    md.append("\n### 5.2 Top walls SL specifiques (Bot 2, n>=2)")
    md.append(df_to_md(wall_perf_b2))

    md.append("\n## 6. Limites methodologiques\n")
    md.append("- **Echantillon faible** : 5j Bot 1 + 4j Bot 2 → faible significativite statistique.")
    md.append("- **Regime homogene** : tous les trades en regime baissier Q1 2026 (geopolitique). Pas de generalisation cross-regime.")
    md.append("- **Funnel simu generique** : Triple Barrier 16t/32t fixes ignore les SL/TP reels (Bot calcule via SLTPEngine murs adaptatifs).")
    md.append("- **Cross-bot pairs** : fenetre 30min large, peut surestimer correspondances (signaux differents, meme regime).")
    md.append("- **VIX regime** : extrait de exit_context (Bot 1) / features_at_entry (Bot 2). Coherence inter-bot non garantie.\n")
    md.append("**Pas de decision GO/NO-GO sur ce rapport seul. Indicatif pour orienter analyses ciblees.**\n")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(md), encoding="utf-8")
    print(f"[done] Rapport ecrit : {OUTPUT}")
    print(f"       {OUTPUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
