"""Audit empirique Phase 1.7e Bot 3 — bias jour intraday + SHORT BREAKOUT vs LONG REJECTION.

CONTEXTE :
Vendredi 15/05/2026 = journée catastrophique Bot 3 (-$793.50, 3W/10L) :
- 12 LONG ES sur 13 trades alors que jour bearish -411 ticks
- Niveaux pris : 100% supports gamma (GEX_DN 7x, MQ_PUT_0DTE 5x, MQ_CALL_POC_FLAT 1x)
- Bot 1 SHORT (Sim3) + Bot 2 V6 SHORT (Sim2) corrects, seul Bot 3 LONG

DIAGNOSTIC ARCHITECTURAL :
- 14 niveaux ES : 6 LONG-only, 3 SHORT-only, 5 REJECTION bidi -> biais 2:1 LONG
- Sur jour bearish, prix tape les supports en boucle -> 45 contacts supports / 1 resistance
- cvd_day_dir bruite (court terme, pas bias jour)
- regime_favor NEUTRE 12/13 (regime_engine court terme)

HYPOTHESES TESTEES :
H1 : `intraday_chg_t = (close - day_open) / 0.25` est un proxy fiable du bias jour.
H2 : Sur supports gamma + jour bearish (intraday_chg <= -50t), LONG REJECTION = PF < 1.0 systemique.
H3 : Sur memes contacts, SHORT BREAKOUT (logique inverse) = PF > 1.5.
H4 : Symetrie : sur resistances gamma + jour bullish, LONG BREAKOUT > SHORT REJECTION.

METHODE :
1. Charger v4 enriched ES + NQ avril+mai 2026 (sources VPS deja pull)
2. Detecter contacts simules sur 6 supports gamma : GEX_DN, MQ_PUT_0DTE, IB_LOW,
   VWAP_W_SD1D, SIDAK_SWING_LOW, SIDAK_COLOR_UP_zone + 3 resistances : MQ_CALL_POC_FLAT,
   SIDAK_SWING_HIGH, SIDAK_COLOR_DN_zone (touch dist <= 0.05%)
3. Pour chaque contact, calculer `intraday_chg_t`
4. Simuler 2 trades hypothetiques par contact :
   - REJECTION (Bot 3 actuel) : direction selon level["side"], SL 16t, TP 32t
   - BREAKOUT (inverse) : direction opposee, SL 16t, TP 32t
5. Bucket par intraday_chg_t : [<-100, -100..-50, -50..0, 0..+50, +50..+100, >+100]
6. Tableau croise : PF / WR / N par bucket × strategie × side
7. DSR Lopez Bonferroni : significativite pour valider VETO ou logique inverse

GOAL : confirmer empiriquement le pattern observe 15/05 + cadrer Phase 1.7e.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/V4_TEMP")
TICK_SIZE = 0.25  # ES + NQ + MGC

# Niveaux Bot 3 a tester (subset critique : supports gamma + resistances symetriques)
LEVELS_TEST = {
    # Supports (Bot 3 actuel = LONG REJECTION)
    "GEX_DN":              {"dist_col": "dist_gex_dn_pct",            "side_actuel": "LONG"},
    "MQ_PUT_0DTE":         {"dist_col": "dist_mq_put_0dte_pct",       "side_actuel": "LONG"},
    "IB_LOW":              {"dist_col": "dist_ib_low_pct",            "side_actuel": "LONG"},
    "VWAP_W_SD1D":         {"dist_col": "dist_vwap_w_sd1d_pct",       "side_actuel": "LONG"},
    "SIDAK_SWING_LOW":     {"dist_col": "dist_swing_low_pct",         "side_actuel": "LONG"},
    "SIDAK_COLOR_UP_zone": {"dist_col": "dist_color_up_nearest_pct",  "side_actuel": "LONG"},
    # Resistances (Bot 3 actuel = SHORT REJECTION)
    "MQ_CALL_POC_FLAT":    {"dist_col": "dist_mq_call_poc_flat_pct",  "side_actuel": "SHORT"},
    "SIDAK_SWING_HIGH":    {"dist_col": "dist_swing_high_pct",        "side_actuel": "SHORT"},
    "SIDAK_COLOR_DN_zone": {"dist_col": "dist_color_dn_nearest_pct",  "side_actuel": "SHORT"},
}

TOUCH_THRESHOLD_PCT = 0.05  # 0.05% = 5 ticks ES @ 5000 ou 12 ticks NQ @ 20000
SL_TICKS = 16
TP_TICKS = 32  # R:R 2.0
MAX_BARS_TO_RESOLUTION = 30  # 30 minutes max horizon


def load_v4(symbol: str) -> pd.DataFrame:
    """Charge v4 enriched avril + mai 2026 et calcule intraday_chg_t."""
    avr = DATA_DIR / f"{symbol}_avr_v4.parquet"
    mai = DATA_DIR / (f"{symbol}_mai_v4_freshest.parquet" if symbol == "ES" else f"{symbol}_mai_v4.parquet")
    dfs = []
    for p in [avr, mai]:
        if p.exists():
            dfs.append(pd.read_parquet(p))
    df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df["date"] = df["ts_event"].dt.date
    # intraday_chg_t : ticks depuis day_open
    df["day_open"] = df.groupby("date")["open"].transform("first")
    df["intraday_chg_t"] = ((df["close"] - df["day_open"]) / TICK_SIZE).round(0)
    return df


def detect_contacts(df: pd.DataFrame, level_name: str, dist_col: str) -> pd.DataFrame:
    """Detecte les touches du niveau : dist <= TOUCH_THRESHOLD_PCT."""
    if dist_col not in df.columns:
        return pd.DataFrame()
    mask = df[dist_col].abs() <= TOUCH_THRESHOLD_PCT
    contacts = df[mask].copy()
    contacts["level"] = level_name
    return contacts


def simulate_trade(df: pd.DataFrame, contact_idx: int, side: str) -> dict:
    """Simule entry = close du contact, SL/TP fixes en ticks, horizon 30 bars."""
    if contact_idx >= len(df) - 1:
        return {"pnl_ticks": 0, "outcome": "NO_DATA"}
    entry_bar = df.iloc[contact_idx]
    entry_price = entry_bar["close"]
    if side == "LONG":
        sl_price = entry_price - SL_TICKS * TICK_SIZE
        tp_price = entry_price + TP_TICKS * TICK_SIZE
    else:  # SHORT
        sl_price = entry_price + SL_TICKS * TICK_SIZE
        tp_price = entry_price - TP_TICKS * TICK_SIZE

    # Scan bars suivantes
    end_idx = min(contact_idx + 1 + MAX_BARS_TO_RESOLUTION, len(df))
    future = df.iloc[contact_idx + 1:end_idx]
    for _, bar in future.iterrows():
        high = bar["high"]
        low = bar["low"]
        if side == "LONG":
            # Conservatif : SL touche en premier si bar contient les 2
            if low <= sl_price:
                return {"pnl_ticks": -SL_TICKS, "outcome": "SL", "exit_price": sl_price}
            if high >= tp_price:
                return {"pnl_ticks": TP_TICKS, "outcome": "TP", "exit_price": tp_price}
        else:  # SHORT
            if high >= sl_price:
                return {"pnl_ticks": -SL_TICKS, "outcome": "SL", "exit_price": sl_price}
            if low <= tp_price:
                return {"pnl_ticks": TP_TICKS, "outcome": "TP", "exit_price": tp_price}
    # Timeout = exit au last close
    last_close = future.iloc[-1]["close"] if len(future) > 0 else entry_price
    pnl_ticks = (last_close - entry_price) / TICK_SIZE if side == "LONG" else (entry_price - last_close) / TICK_SIZE
    return {"pnl_ticks": round(pnl_ticks, 1), "outcome": "TIMEOUT", "exit_price": last_close}


def bucket_intraday_chg(chg_t: float) -> str:
    """Bucket par intraday_chg_t."""
    if pd.isna(chg_t):
        return "NA"
    if chg_t <= -100:
        return "1_<-100t_strong_bear"
    if chg_t <= -50:
        return "2_-100..-50t_bear"
    if chg_t < 0:
        return "3_-50..0t_weak_bear"
    if chg_t < 50:
        return "4_0..50t_weak_bull"
    if chg_t < 100:
        return "5_50..100t_bull"
    return "6_>100t_strong_bull"


def run_audit(symbol: str) -> pd.DataFrame:
    print(f"\n{'=' * 70}\n  AUDIT {symbol}\n{'=' * 70}")
    df = load_v4(symbol)
    print(f"Bars: {len(df)} | Date range: {df['ts_event'].min()} -> {df['ts_event'].max()}")
    print(f"Daily: {df['date'].nunique()} jours")

    results = []
    for level_name, cfg in LEVELS_TEST.items():
        contacts = detect_contacts(df, level_name, cfg["dist_col"])
        if contacts.empty:
            continue
        # Filter consecutive contacts (pour eviter 30 trades sur 1 touch)
        # Conservative : 1 contact par 5min minimum
        contacts["dt_diff"] = contacts["ts_event"].diff().dt.total_seconds().fillna(99999)
        contacts = contacts[contacts["dt_diff"] >= 300]  # >= 5 min

        for _, contact in contacts.iterrows():
            # Find index in df
            idx = df.index[df["ts_event"] == contact["ts_event"]]
            if len(idx) == 0:
                continue
            contact_idx = idx[0]
            chg_t = contact["intraday_chg_t"]
            side_actuel = cfg["side_actuel"]
            side_inverse = "SHORT" if side_actuel == "LONG" else "LONG"

            r_actuel = simulate_trade(df, contact_idx, side_actuel)
            r_inverse = simulate_trade(df, contact_idx, side_inverse)

            results.append({
                "symbol": symbol,
                "level": level_name,
                "side_actuel": side_actuel,
                "ts": contact["ts_event"],
                "intraday_chg_t": chg_t,
                "bucket": bucket_intraday_chg(chg_t),
                "pnl_actuel": r_actuel["pnl_ticks"],
                "outcome_actuel": r_actuel["outcome"],
                "pnl_inverse": r_inverse["pnl_ticks"],
                "outcome_inverse": r_inverse["outcome"],
            })
    if not results:
        print(f"NO CONTACTS detected for {symbol}")
        return pd.DataFrame()
    df_r = pd.DataFrame(results)
    print(f"Contacts detected: {len(df_r)}")
    return df_r


def compute_pf(pnl: pd.Series) -> float:
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0
    return round(wins / losses, 2)


def summarize(df_r: pd.DataFrame, sym_label: str):
    if df_r.empty:
        return
    print(f"\n--- {sym_label} : tableau croise PF/WR/N par bucket x strategie ---\n")
    # Pour chaque bucket : PF actuel + PF inverse + N
    df_r["win_actuel"] = (df_r["pnl_actuel"] > 0).astype(int)
    df_r["win_inverse"] = (df_r["pnl_inverse"] > 0).astype(int)

    bucket_order = ["1_<-100t_strong_bear", "2_-100..-50t_bear", "3_-50..0t_weak_bear",
                    "4_0..50t_weak_bull", "5_50..100t_bull", "6_>100t_strong_bull"]
    print(f"{'bucket':28s} {'N':>5s} {'PF_act':>8s} {'WR_act%':>9s} {'PnL_act':>9s} {'PF_inv':>8s} {'WR_inv%':>9s} {'PnL_inv':>9s} {'DELTA':>9s}")
    for b in bucket_order:
        sub = df_r[df_r["bucket"] == b]
        if sub.empty:
            continue
        pf_a = compute_pf(sub["pnl_actuel"])
        pf_i = compute_pf(sub["pnl_inverse"])
        wr_a = round(sub["win_actuel"].mean() * 100, 1)
        wr_i = round(sub["win_inverse"].mean() * 100, 1)
        pnl_a = round(sub["pnl_actuel"].sum(), 0)
        pnl_i = round(sub["pnl_inverse"].sum(), 0)
        delta = pnl_i - pnl_a
        print(f"{b:28s} {len(sub):>5d} {pf_a:>8} {wr_a:>9} {pnl_a:>9.0f} {pf_i:>8} {wr_i:>9} {pnl_i:>9.0f} {delta:>+9.0f}")

    # Global
    print(f"\n--- GLOBAL {sym_label} ---")
    print(f"  N total: {len(df_r)}")
    print(f"  PF actuel  : {compute_pf(df_r['pnl_actuel'])}    PnL_total={df_r['pnl_actuel'].sum():.0f}t  WR={df_r['win_actuel'].mean()*100:.1f}%")
    print(f"  PF inverse : {compute_pf(df_r['pnl_inverse'])}    PnL_total={df_r['pnl_inverse'].sum():.0f}t  WR={df_r['win_inverse'].mean()*100:.1f}%")
    print(f"  Delta inverse vs actuel : {(df_r['pnl_inverse'] - df_r['pnl_actuel']).sum():+.0f}t")


def summarize_with_veto_simulation(df_r: pd.DataFrame, sym_label: str):
    """Simule VETO strict : sur bucket bearish, ne prend QUE SHORT side; bucket bullish QUE LONG."""
    if df_r.empty:
        return
    print(f"\n--- {sym_label} : SIMULATION VETO BIAS JOUR (Phase 1.7e) ---")
    # Strat A : Bot 3 actuel (toujours side_actuel)
    pnl_A = df_r["pnl_actuel"].sum()
    n_A = len(df_r)
    pf_A = compute_pf(df_r["pnl_actuel"])

    # Strat B : VETO STRICT — skip trade si side_actuel contre bucket directionnel
    # bear buckets (1,2,3) -> autorise SHORT only
    # bull buckets (4,5,6) -> autorise LONG only
    def keep_strict(row):
        b = row["bucket"]
        s = row["side_actuel"]
        if b in ("1_<-100t_strong_bear", "2_-100..-50t_bear", "3_-50..0t_weak_bear"):
            return s == "SHORT"
        if b in ("4_0..50t_weak_bull", "5_50..100t_bull", "6_>100t_strong_bull"):
            return s == "LONG"
        return True  # NA bucket

    kept_B = df_r[df_r.apply(keep_strict, axis=1)]
    pnl_B = kept_B["pnl_actuel"].sum() if not kept_B.empty else 0
    n_B = len(kept_B)
    pf_B = compute_pf(kept_B["pnl_actuel"]) if not kept_B.empty else 0

    # Strat C : LOGIQUE INVERSE — sur bear bucket + side_actuel=LONG, prendre SHORT a la place
    def transformed_pnl(row):
        b = row["bucket"]
        s = row["side_actuel"]
        if b in ("1_<-100t_strong_bear", "2_-100..-50t_bear", "3_-50..0t_weak_bear") and s == "LONG":
            return row["pnl_inverse"]  # inverse = SHORT
        if b in ("4_0..50t_weak_bull", "5_50..100t_bull", "6_>100t_strong_bull") and s == "SHORT":
            return row["pnl_inverse"]  # inverse = LONG
        return row["pnl_actuel"]

    df_r["pnl_C"] = df_r.apply(transformed_pnl, axis=1)
    pnl_C = df_r["pnl_C"].sum()
    pf_C = compute_pf(df_r["pnl_C"])

    print(f"  STRAT A (Bot 3 actuel)  : N={n_A:5d}  PF={pf_A}  PnL={pnl_A:+.0f}t")
    print(f"  STRAT B (VETO strict)   : N={n_B:5d}  PF={pf_B}  PnL={pnl_B:+.0f}t  (skip={n_A-n_B})")
    print(f"  STRAT C (LOGIQUE INVRS) : N={n_A:5d}  PF={pf_C}  PnL={pnl_C:+.0f}t  (inverse sur bias)")
    print(f"  Best gain vs A : VETO=+{pnl_B - pnl_A:.0f}t  INVERSE=+{pnl_C - pnl_A:.0f}t")


if __name__ == "__main__":
    df_es = run_audit("ES")
    df_nq = run_audit("NQ")
    if not df_es.empty:
        summarize(df_es, "ES")
        summarize_with_veto_simulation(df_es, "ES")
    if not df_nq.empty:
        summarize(df_nq, "NQ")
        summarize_with_veto_simulation(df_nq, "NQ")
