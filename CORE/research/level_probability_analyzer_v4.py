"""level_probability_analyzer_v4.py — Analyse rejection 45 niveaux + contexte etendu.

Created : 2026-05-02 dimanche soir.
Spec    : DOCS/PROMPT_CLAUDE_CODE_LEVEL_PROB_V4.md

Source : DATA/datasets/v4_enriched/symbol={NQ,ES}.c.0/year=YYYY/month=MM/data.parquet

VS DMP (Bot 1) :
  - 45 niveaux (vs 16 DMP) : ajout PVWAP, VWAP weekly/monthly, Asia/London/US,
    naked POC, single print, swing, trapped, delta div, edge zones, color, etc.
  - Cols en pct (vs ticks DMP)
  - Contexte etendu : 20+ dimensions (momentum, delta, cvd, volume, finish,
    range_pos, session, segment, open_type, day_type, ib_status, vwap_side,
    premium/discount, rvol_regime, cross_agree, smt_div, trapped, absorption,
    spike, delta_exhaustion, time_to_close)

POUR CHAQUE NIVEAU avec n >= 30 :
  1. Rejection rate BASELINE
  2. Top 5 contextes qui augmentent rejection (edge > +15pp)
  3. Top 3 contextes qui augmentent acceptance (rejection < baseline - 15pp)
  4. PF si on trade rejection avec best contexte
  5. PF si on trade acceptance avec best contexte
  6. Stats par session (ASIA / LONDON / US_CASH / US_AFTER)

SYNTHESE finale : 10 meilleurs setups "niveau + contexte" tries par PF.

Usage :
  python -X utf8 CORE/research/level_probability_analyzer_v4.py \\
    --data-dir DATA/datasets/v4_enriched \\
    --symbol NQ --horizon 30 --min-n 10 \\
    --output DOCS/LEVEL_PROB_V4_NQ.md
"""
from __future__ import annotations
import argparse
import glob
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = 0.25
PROXIMITY_PCT_DEFAULT = 0.05  # 0.05% du prix
EDGE_THRESHOLD_PP = 15.0  # +15pp pour considerer un contexte "edge"
MIN_N_PER_CONTEXT = 30   # min n pour qualifier un contexte (anti data dredging)


# ═══════════════════════════════════════════════════════════════════
# 45 NIVEAUX V4
# ═══════════════════════════════════════════════════════════════════

LEVELS_V4 = {
    # Previous Day
    "PVPOC":         {"dist_col": "dist_prev_vpoc_pct",         "name": "Previous VPOC",         "group": "PREV_DAY"},
    "PVAH":          {"dist_col": "dist_prev_vah_pct",          "name": "Previous VAH",          "group": "PREV_DAY"},
    "PVAL":          {"dist_col": "dist_prev_val_pct",          "name": "Previous VAL",          "group": "PREV_DAY"},
    "PDH":           {"dist_col": "dist_pdh_pct",               "name": "Previous Day High",     "group": "PREV_DAY"},
    "PDL":           {"dist_col": "dist_pdl_pct",               "name": "Previous Day Low",      "group": "PREV_DAY"},
    # PVWAP previous
    "PVWAP":         {"dist_col": "dist_pvwap_pct",             "name": "Previous VWAP",         "group": "PVWAP_PREV"},
    "PVWAP_SD1U":    {"dist_col": "dist_pvwap_sd1u_pct",        "name": "Previous VWAP SD+1",    "group": "PVWAP_PREV"},
    "PVWAP_SD1D":    {"dist_col": "dist_pvwap_sd1d_pct",        "name": "Previous VWAP SD-1",    "group": "PVWAP_PREV"},
    # VWAP daily
    "VWAP_D":        {"dist_col": "dist_vwap_d_pct",            "name": "VWAP Daily",            "group": "VWAP_DAILY"},
    "VWAP_SD1U":     {"dist_col": "dist_vwap_d_sd1u_pct",       "name": "VWAP SD+1",             "group": "VWAP_DAILY"},
    "VWAP_SD1D":     {"dist_col": "dist_vwap_d_sd1d_pct",       "name": "VWAP SD-1",             "group": "VWAP_DAILY"},
    "VWAP_SD2U":     {"dist_col": "dist_vwap_d_sd2u_pct",       "name": "VWAP SD+2",             "group": "VWAP_DAILY"},
    "VWAP_SD2D":     {"dist_col": "dist_vwap_d_sd2d_pct",       "name": "VWAP SD-2",             "group": "VWAP_DAILY"},
    # Current Day MP
    "CUR_VPOC":      {"dist_col": "dist_cur_vpoc_pct",          "name": "Current VPOC",          "group": "CUR_DAY"},
    "CUR_VAH":       {"dist_col": "dist_cur_vah_pct",           "name": "Current VAH",           "group": "CUR_DAY"},
    "CUR_VAL":       {"dist_col": "dist_cur_val_pct",           "name": "Current VAL",           "group": "CUR_DAY"},
    # IB
    "IB_HIGH":       {"dist_col": "dist_ib_high_pct",           "name": "IB High",               "group": "IB"},
    "IB_LOW":        {"dist_col": "dist_ib_low_pct",            "name": "IB Low",                "group": "IB"},
    # Session
    "SESS_HIGH":     {"dist_col": "dist_sess_high_pct",         "name": "Session High",          "group": "SESS"},
    "SESS_LOW":      {"dist_col": "dist_sess_low_pct",          "name": "Session Low",           "group": "SESS"},
    "CASH_HIGH":     {"dist_col": "dist_cash_high_pct",         "name": "Cash High",             "group": "SESS"},
    "CASH_LOW":      {"dist_col": "dist_cash_low_pct",          "name": "Cash Low",              "group": "SESS"},
    # Overnight
    "OVN_HIGH":      {"dist_col": "dist_ovn_high_pct",          "name": "Overnight High",        "group": "OVN"},
    "OVN_LOW":       {"dist_col": "dist_ovn_low_pct",           "name": "Overnight Low",         "group": "OVN"},
    # Open prices
    "OPEN_830":      {"dist_col": "dist_open_830_pct",          "name": "Open 8:30 ET",          "group": "OPEN"},
    "OPEN_930":      {"dist_col": "dist_open_930_pct",          "name": "Open 9:30 ET",          "group": "OPEN"},
    # MQ
    "MQ_CALL":       {"dist_col": "dist_mq_call_pct",           "name": "MQ Call Wall",          "group": "MQ"},
    "MQ_PUT":        {"dist_col": "dist_mq_put_pct",            "name": "MQ Put Wall",           "group": "MQ"},
    "MQ_HVL":        {"dist_col": "dist_mq_hvl_pct",            "name": "MQ HVL",                "group": "MQ"},
    "MQ_CALL_0DTE":  {"dist_col": "dist_mq_call_0dte_pct",      "name": "MQ Call 0DTE",          "group": "MQ_0DTE"},
    "MQ_PUT_0DTE":   {"dist_col": "dist_mq_put_0dte_pct",       "name": "MQ Put 0DTE",           "group": "MQ_0DTE"},
    # GEX
    "GEX_UP":        {"dist_col": "dist_gex_nearest_up_pct",    "name": "GEX Nearest Up",        "group": "GEX"},
    "GEX_DN":        {"dist_col": "dist_gex_nearest_dn_pct",    "name": "GEX Nearest Down",      "group": "GEX"},
    # 1D max/min
    "MQ_1D_MAX":     {"dist_col": "dist_1d_max_ticks_pct",      "name": "MQ 1D Max",             "group": "MQ_1D"},
    "MQ_1D_MIN":     {"dist_col": "dist_1d_min_ticks_pct",      "name": "MQ 1D Min",             "group": "MQ_1D"},
    # Naked POC
    "NAKED_POC":     {"dist_col": "dist_naked_poc_nearest_pct", "name": "Naked POC Nearest",     "group": "STRUCT"},
    # Single print (oublie initialement, ajoute 03/05)
    "SINGLE_PRINT":  {"dist_col": "dist_single_print_nearest_pct", "name": "Single Print Nearest", "group": "STRUCT"},
    "SP_ZONE":       {"dist_col": "dist_single_print_zone_nearest_pct", "name": "Single Print Zone", "group": "STRUCT"},
    # Spikes
    "SPIKE_ORIGIN":  {"dist_col": "dist_last_spike_origin_pct", "name": "Last Spike Origin",     "group": "STRUCT"},
    # Cluster
    "CLUSTER_UP":    {"dist_col": "dist_cluster_nearest_up_pct", "name": "Cluster Up",           "group": "CLUSTER"},
    "CLUSTER_DN":    {"dist_col": "dist_cluster_nearest_dn_pct", "name": "Cluster Down",         "group": "CLUSTER"},
    # Swing
    "SWING_HIGH":    {"dist_col": "dist_last_swing_high_pct",   "name": "Last Swing High",       "group": "SWING"},
    "SWING_LOW":     {"dist_col": "dist_last_swing_low_pct",    "name": "Last Swing Low",        "group": "SWING"},
    # Trapped
    "TRAPPED_BUY":   {"dist_col": "dist_trapped_buyers_nearest_pct",  "name": "Trapped Buyers",  "group": "TRAPPED"},
    "TRAPPED_SELL":  {"dist_col": "dist_trapped_sellers_nearest_pct", "name": "Trapped Sellers", "group": "TRAPPED"},
    # Color zones
    "COLOR_UP":      {"dist_col": "dist_color_up_nearest_pct",  "name": "Color Zone Up",         "group": "COLOR"},
    "COLOR_DN":      {"dist_col": "dist_color_dn_nearest_pct",  "name": "Color Zone Down",       "group": "COLOR"},
    # Delta divergence
    "DELTA_DIV_BUY":  {"dist_col": "dist_delta_div_buy_nearest_pct",  "name": "Delta Div Buy",   "group": "DELTA_DIV"},
    "DELTA_DIV_SELL": {"dist_col": "dist_delta_div_sell_nearest_pct", "name": "Delta Div Sell",  "group": "DELTA_DIV"},
    # Edge zones
    "EDGE_BUY_Z":    {"dist_col": "dist_edge_buy_nearest_pct",  "name": "Edge Buy Zone",         "group": "EDGE"},
    "EDGE_SELL_Z":   {"dist_col": "dist_edge_sell_nearest_pct", "name": "Edge Sell Zone",        "group": "EDGE"},
    # Asia / London
    "ASIA_HIGH":     {"dist_col": "dist_asia_high_pct",         "name": "Asia High",             "group": "INTL"},
    "ASIA_LOW":      {"dist_col": "dist_asia_low_pct",          "name": "Asia Low",              "group": "INTL"},
    "LONDON_HIGH":   {"dist_col": "dist_london_high_pct",       "name": "London High",           "group": "INTL"},
    "LONDON_LOW":    {"dist_col": "dist_london_low_pct",        "name": "London Low",            "group": "INTL"},
}


# ═══════════════════════════════════════════════════════════════════
# CHARGEMENT V4
# ═══════════════════════════════════════════════════════════════════

def load_v4_parquets(data_dir: str, symbol: str) -> pd.DataFrame:
    """Charge tous les V4 enriched parquets."""
    sym_full = f"{symbol}.c.0"
    files = sorted(glob.glob(f"{data_dir}/symbol={sym_full}/**/*.parquet", recursive=True))
    if not files:
        print(f"[ERROR] Aucun parquet pour {symbol} dans {data_dir}")
        return pd.DataFrame()
    print(f"[load] {len(files)} fichiers parquet pour {symbol}")
    parts = []
    for f in files:
        try:
            parts.append(pd.read_parquet(f))
        except Exception as e:
            print(f"  [WARN] {f}: {e}")
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df["ts_event"] = df["ts_event"].dt.tz_convert(None)
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event")
    df = df.drop_duplicates("ts_event").reset_index(drop=True)
    df["session_date"] = df["ts_event"].dt.date
    print(f"[load] {len(df)} barres, {df['session_date'].nunique()} jours")
    print(f"[load] Periode : {df['ts_event'].min()} -> {df['ts_event'].max()}")
    return df


# ═══════════════════════════════════════════════════════════════════
# FORWARD MOVES
# ═══════════════════════════════════════════════════════════════════

def add_forward_moves_v4(df: pd.DataFrame, horizon: int = 30) -> pd.DataFrame:
    """Forward moves en ticks par session."""
    out = df.copy()
    col = f"fwd_{horizon}m"
    out[col] = np.nan
    for date, group in out.groupby("session_date"):
        idx = group.index
        price = group["close"].values
        fwd = np.full(len(price), np.nan)
        for i in range(len(price) - horizon):
            fwd[i] = (price[i + horizon] - price[i]) / TICK_SIZE
        out.loc[idx, col] = fwd
    return out


# ═══════════════════════════════════════════════════════════════════
# CONTEXTE ETENDU (20+ dimensions)
# ═══════════════════════════════════════════════════════════════════

def _safe_int(v, default: int = 0) -> int:
    """Cast safe vers int, NaN -> default."""
    if v is None or pd.isna(v):
        return default
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default


def _safe_float(v, default: float = 0.0) -> float:
    """Cast safe vers float, NaN -> default."""
    if v is None or pd.isna(v):
        return default
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return default
        return f
    except (ValueError, TypeError):
        return default


def classify_approach_context(bar: pd.Series) -> dict:
    """Retourne 20+ labels de contexte pour une barre."""
    ctx = {}

    m = abs(_safe_float(bar.get("momentum_5b"), 0.0))
    ctx["momentum"] = "FAST" if m > 200 else ("MEDIUM" if m > 50 else "SLOW")

    d = _safe_float(bar.get("delta_bar"), 0.0)
    ctx["delta_at_level"] = "BUY_AGGR" if d > 20 else ("SELL_AGGR" if d < -20 else "NEUTRAL")

    c = _safe_float(bar.get("delta_day_dir"), 0.0)
    ctx["cvd_trend"] = "UP" if c > 0 else ("DOWN" if c < 0 else "FLAT")

    r = _safe_float(bar.get("rvol"), 1.0)
    ctx["volume"] = "HIGH" if r > 1.5 else ("NORMAL" if r > 0.8 else "LOW")

    f = _safe_float(bar.get("finish_strength"), 0.0)
    ctx["finish"] = "STRONG_UP" if f > 15 else ("STRONG_DOWN" if f < -15 else "WEAK")

    p = _safe_float(bar.get("position_in_range"), 0.5)
    ctx["range_pos"] = "TOP" if p > 0.80 else ("BOT" if p < 0.20 else "MID")

    if _safe_int(bar.get("is_in_asia")) == 1:
        ctx["session"] = "ASIA"
    elif _safe_int(bar.get("is_in_london")) == 1:
        ctx["session"] = "LONDON"
    elif _safe_int(bar.get("is_in_us_cash")) == 1:
        ctx["session"] = "US_CASH"
    elif _safe_int(bar.get("is_in_us_after")) == 1:
        ctx["session"] = "US_AFTER"
    else:
        ctx["session"] = "OTHER"

    ctx["session_seg"] = f"S{_safe_int(bar.get('session_segment'), 0)}"
    ctx["open_type"] = f"T{_safe_int(bar.get('open_type'), 0)}"
    ctx["day_type"] = f"T{_safe_int(bar.get('day_type'), 0)}"

    if _safe_int(bar.get("ib_broken_up")) == 1:
        ctx["ib_status"] = "BROKEN_UP"
    elif _safe_int(bar.get("ib_broken_dn")) == 1:
        ctx["ib_status"] = "BROKEN_DN"
    else:
        ctx["ib_status"] = "INSIDE"

    ctx["vwap_side"] = "ABOVE" if _safe_float(bar.get("vwap_d_side")) > 0 else "BELOW"
    ctx["above_hvl"] = "Y" if _safe_int(bar.get("bool_above_mq_hvl")) == 1 else "N"
    ctx["gex_flip"] = "Y" if _safe_int(bar.get("bool_gex_flip_zone")) == 1 else "N"

    if _safe_int(bar.get("premium_zone")) == 1:
        ctx["prem_disc"] = "PREMIUM"
    elif _safe_int(bar.get("discount_zone")) == 1:
        ctx["prem_disc"] = "DISCOUNT"
    else:
        ctx["prem_disc"] = "NEUTRAL"

    ctx["rvol_reg"] = f"R{_safe_int(bar.get('rvol_regime'), 1)}"

    a = _safe_float(bar.get("im_cross_delta_agreement_5"), 0.0)
    ctx["cross_agree"] = "HIGH" if a > 0.7 else ("MED" if a > 0.3 else "LOW")

    ctx["smt_div"] = "Y" if _safe_int(bar.get("im_smt_divergence")) == 1 else "N"
    ctx["trap_buy_near"] = "Y" if _safe_int(bar.get("n_trapped_buyers_cluster_within_0_2pct")) > 0 else "N"
    ctx["trap_sell_near"] = "Y" if _safe_int(bar.get("n_trapped_sellers_cluster_within_0_2pct")) > 0 else "N"
    ctx["delta_exh"] = "Y" if _safe_float(bar.get("ctx_delta_exhaustion")) > 0.3 else "N"
    ctx["absorb"] = "Y" if _safe_int(bar.get("ctx_instant_absorption")) == 1 else "N"
    ctx["spike_near"] = "Y" if _safe_int(bar.get("spike_detected_lag3")) == 1 else "N"

    t = _safe_float(bar.get("time_to_session_close_norm"), 0.5)
    ctx["time_to_close"] = "LAST_Q" if t < 0.25 else ("MID" if t < 0.75 else "EARLY")

    # POC migration direction (Jackson 03/05) — feature V4 puissante :
    #  -1 = POC se deplace vers le bas (bear pressure)
    #   0 = POC stable (range)
    #  +1 = POC se deplace vers le haut (bull pressure)
    pmd = _safe_int(bar.get("poc_migration_dir"), 0)
    if pmd > 0:
        ctx["poc_mig"] = "UP"
    elif pmd < 0:
        ctx["poc_mig"] = "DOWN"
    else:
        ctx["poc_mig"] = "FLAT"

    # POC migration MAGNITUDE (10 bars rolling) — utile pour distinguer
    # "lent" vs "rapide" mouvement du POC
    pmag = _safe_float(bar.get("ctx_poc_migration_10"), 0.0)
    if abs(pmag) > 0.05:
        ctx["poc_mig_speed"] = "FAST"
    elif abs(pmag) > 0.01:
        ctx["poc_mig_speed"] = "SLOW"
    else:
        ctx["poc_mig_speed"] = "FLAT"

    # VA developing (10 bars rolling) — VA s'elargit (breakout possible) ou
    # se contracte (consolidation). Trio avec poc_mig + poc_mig_speed = film
    # complet de la structure qui evolue en temps reel.
    va_dev = _safe_float(bar.get("ctx_va_developing_10"), 0.0)
    if va_dev > 0.5:
        ctx["va_dev"] = "EXPAND"
    elif va_dev < -0.5:
        ctx["va_dev"] = "CONTRACT"
    else:
        ctx["va_dev"] = "STABLE"

    return ctx


# ═══════════════════════════════════════════════════════════════════
# DETECTION TOUCHES + REJECTION
# ═══════════════════════════════════════════════════════════════════

def detect_touches(df: pd.DataFrame, dist_col: str, proximity_pct: float,
                    fwd_col: str) -> pd.DataFrame:
    """Bars qui touchent le niveau (abs(dist_pct) < proximity).

    FIX (02/05) : exclure dist == 0 EXACT car c'est typiquement
    "niveau non defini" (ex: dist_mq_call_0dte_pct = 0.0 quand pas de
    call wall 0DTE pour le jour) et NON une vraie touche au tick.
    Sans ce filtre, MQ levels ressortent a 97% rejection (artefact).

    Threshold pratique : dist_col != 0 ET dist_col != null ET abs(dist) < proximity.
    On utilise un epsilon mini (1e-6) pour l'inegalite stricte.
    """
    if dist_col not in df.columns or fwd_col not in df.columns:
        return pd.DataFrame()
    EPS = 1e-6
    touched = df[(df[dist_col].abs() < proximity_pct)
                 & (df[dist_col].abs() > EPS)
                 & (df[dist_col].notna())].copy()
    touched = touched.dropna(subset=[fwd_col])
    return touched


def compute_rejection(touched: pd.DataFrame, dist_col: str,
                       fwd_col: str) -> pd.DataFrame:
    """Calcule rejection (signe oppose) ou acceptance (meme signe).

    Si dist > 0 (price en-dessous), rejection = price baisse plus = fwd < 0
    Si dist < 0 (price au-dessus), rejection = price monte plus = fwd > 0
    """
    if len(touched) == 0:
        return touched
    fwd = touched[fwd_col].values
    dist = touched[dist_col].values
    sign_dist = np.sign(dist)
    sign_fwd = np.sign(fwd)
    rejection = ((sign_dist != 0) & (sign_dist != sign_fwd)) | (sign_dist == 0)
    out = touched.copy()
    out["rejection"] = rejection.astype(int)
    out["move_ticks"] = np.where(rejection, np.abs(fwd), -np.abs(fwd))
    return out


def compute_pf(moves: np.ndarray) -> float:
    """Profit factor."""
    if len(moves) == 0:
        return 0.0
    gains = moves[moves > 0].sum()
    losses = abs(moves[moves < 0].sum())
    if losses == 0:
        return 999.0 if gains > 0 else 0.0
    return float(gains / losses)


# ═══════════════════════════════════════════════════════════════════
# ANALYSE PAR NIVEAU + CONTEXTE
# ═══════════════════════════════════════════════════════════════════

CONTEXT_DIMENSIONS = [
    "session", "session_seg", "momentum", "delta_at_level", "cvd_trend",
    "volume", "finish", "range_pos", "open_type", "day_type",
    "ib_status", "vwap_side", "above_hvl", "gex_flip", "prem_disc",
    "rvol_reg", "cross_agree", "smt_div", "trap_buy_near", "trap_sell_near",
    "delta_exh", "absorb", "spike_near", "time_to_close",
    "poc_mig", "poc_mig_speed", "va_dev",  # Jackson 03/05 — Trio structure evolution
]


def analyze_level_with_contexts(level_key: str, level_meta: dict,
                                  df: pd.DataFrame, fwd_col: str,
                                  proximity_pct: float, min_n: int) -> dict:
    """Analyse complete d'un niveau avec contextes etendus."""
    dist_col = level_meta["dist_col"]
    if dist_col not in df.columns:
        return {"level": level_key, "skip": "col_absent"}
    touched = detect_touches(df, dist_col, proximity_pct, fwd_col)
    if len(touched) < min_n:
        return {"level": level_key, "name": level_meta["name"],
                "group": level_meta["group"],
                "n_touches": len(touched), "skip": f"n<{min_n}"}

    touched = compute_rejection(touched, dist_col, fwd_col)
    n = len(touched)
    n_rej = int(touched["rejection"].sum())
    baseline_rej = (n_rej / n) * 100
    moves = touched["move_ticks"].values
    pf_baseline = compute_pf(moves)

    # Contextes : on calcule rejection rate par valeur de chaque dimension
    context_stats = []  # list of dict per (dim, value)
    for dim in CONTEXT_DIMENSIONS:
        if dim not in touched.columns:
            continue
        for value, sub in touched.groupby(dim):
            n_sub = len(sub)
            if n_sub < MIN_N_PER_CONTEXT:
                continue
            rej_sub = (sub["rejection"].sum() / n_sub) * 100
            edge = rej_sub - baseline_rej
            pf_sub = compute_pf(sub["move_ticks"].values)
            context_stats.append({
                "dim": dim, "value": str(value), "n": n_sub,
                "rejection_rate": round(rej_sub, 1),
                "edge_pp": round(edge, 1),
                "pf": round(pf_sub, 2),
            })

    # Top 5 contextes pro-rejection (edge > +15pp)
    pos_contexts = [c for c in context_stats if c["edge_pp"] > EDGE_THRESHOLD_PP]
    pos_contexts.sort(key=lambda x: x["edge_pp"], reverse=True)
    top_pos = pos_contexts[:5]

    # Top 3 contextes pro-acceptance (edge < -15pp)
    neg_contexts = [c for c in context_stats if c["edge_pp"] < -EDGE_THRESHOLD_PP]
    neg_contexts.sort(key=lambda x: x["edge_pp"])
    top_neg = neg_contexts[:3]

    # PF best contexte rejection
    best_rej_pf = top_pos[0]["pf"] if top_pos else None
    best_rej_label = (f"{top_pos[0]['dim']}={top_pos[0]['value']}"
                      if top_pos else None)
    # PF best contexte acceptance (= 1/PF inverse, ou PF en jouant le breakout)
    best_acc_pf = top_neg[0]["pf"] if top_neg else None
    best_acc_label = (f"{top_neg[0]['dim']}={top_neg[0]['value']}"
                      if top_neg else None)

    # Stats par session
    by_session = {}
    for sess, sub in touched.groupby("session"):
        n_s = len(sub)
        if n_s == 0:
            continue
        rej_s = (sub["rejection"].sum() / n_s) * 100
        by_session[str(sess)] = {
            "n": n_s, "rejection_rate": round(rej_s, 1),
            "pf": round(compute_pf(sub["move_ticks"].values), 2),
        }

    return {
        "level": level_key,
        "name": level_meta["name"],
        "group": level_meta["group"],
        "n_touches": n,
        "n_rejection": n_rej,
        "baseline_rej": round(baseline_rej, 1),
        "pf_baseline": round(pf_baseline, 2),
        "avg_move": round(float(np.mean(moves)), 1),
        "top_pos_contexts": top_pos,
        "top_neg_contexts": top_neg,
        "best_rej_pf": best_rej_pf,
        "best_rej_label": best_rej_label,
        "best_acc_pf": best_acc_pf,
        "best_acc_label": best_acc_label,
        "by_session": by_session,
    }


# ═══════════════════════════════════════════════════════════════════
# RAPPORT MARKDOWN
# ═══════════════════════════════════════════════════════════════════

def render_report(symbol: str, results: list[dict], df: pd.DataFrame,
                   horizon: int, output_path: str, proximity_pct: float):
    valid = [r for r in results if "skip" not in r]
    valid.sort(key=lambda x: x["baseline_rej"], reverse=True)

    lines = []
    lines.append(f"# LEVEL PROBABILITY V4 — {symbol} (45 niveaux + contexte etendu)\n")
    lines.append(f"**Genere** : {datetime.now().isoformat()}")
    lines.append(f"**Source** : DATA/datasets/v4_enriched/symbol={symbol}.c.0/")
    lines.append(f"**Donnees** : {df['session_date'].min()} → {df['session_date'].max()}")
    lines.append(f"**Barres** : {len(df)} ({df['session_date'].nunique()} jours)")
    lines.append(f"**Horizon** : {horizon} min")
    lines.append(f"**Proximity threshold** : {proximity_pct}% du prix")
    lines.append(f"**Edge threshold** : ±{EDGE_THRESHOLD_PP}pp")
    lines.append(f"**Min N per context** : {MIN_N_PER_CONTEXT}")
    lines.append(f"**Niveaux testes** : {len(LEVELS_V4)} | actifs (n>=min) : {len(valid)}\n")

    # ─── 1. Ranking baseline ────────────────────────────────
    lines.append("## 1. RANKING par REJECTION RATE BASELINE\n")
    lines.append("| Niveau | Group | N | Rej % | PF | Avg move | Best rej ctx | Best rej PF | Best acc ctx | Best acc PF |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in valid:
        v = ""
        if r["baseline_rej"] >= 65 and r["pf_baseline"] >= 1.5:
            v = " ⭐⭐⭐"
        elif r["baseline_rej"] >= 55 and r["pf_baseline"] >= 1.3:
            v = " ⭐⭐"
        elif r["baseline_rej"] >= 52:
            v = " ⭐"
        else:
            v = " ❌"
        lines.append(
            f"| {r['level']} | {r['group']} | {r['n_touches']} | "
            f"{r['baseline_rej']}% | {r['pf_baseline']} | {r['avg_move']}t | "
            f"{r['best_rej_label'] or '-'} | {r['best_rej_pf'] or '-'} | "
            f"{r['best_acc_label'] or '-'} | {r['best_acc_pf'] or '-'} |{v}"
        )
    lines.append("")

    # ─── 2. Detail top 15 niveaux (contextes complets) ───
    lines.append("## 2. DETAIL TOP 15 niveaux\n")
    for r in valid[:15]:
        lines.append(f"### {r['level']} — {r['name']} (n={r['n_touches']}, baseline={r['baseline_rej']}%, PF={r['pf_baseline']})\n")

        if r["top_pos_contexts"]:
            lines.append("**Top 5 contextes PRO-REJECTION (edge > +15pp)** :\n")
            lines.append("| Dimension | Value | N | Rejection % | Edge | PF |")
            lines.append("|---|---|---|---|---|---|")
            for c in r["top_pos_contexts"]:
                lines.append(f"| {c['dim']} | {c['value']} | {c['n']} | {c['rejection_rate']}% | +{c['edge_pp']}pp | {c['pf']} |")
            lines.append("")

        if r["top_neg_contexts"]:
            lines.append("**Top 3 contextes PRO-ACCEPTANCE (edge < -15pp = breakout)** :\n")
            lines.append("| Dimension | Value | N | Rejection % | Edge | PF |")
            lines.append("|---|---|---|---|---|---|")
            for c in r["top_neg_contexts"]:
                lines.append(f"| {c['dim']} | {c['value']} | {c['n']} | {c['rejection_rate']}% | {c['edge_pp']}pp | {c['pf']} |")
            lines.append("")

        if r["by_session"]:
            lines.append("**Par session** :\n")
            lines.append("| Session | N | Rejection % | PF |")
            lines.append("|---|---|---|---|")
            for sess, s in r["by_session"].items():
                lines.append(f"| {sess} | {s['n']} | {s['rejection_rate']}% | {s['pf']} |")
            lines.append("")

    # ─── 3. SYNTHESE — top 10 setups niveau+contexte par PF ────
    lines.append("## 3. SYNTHESE — TOP 10 SETUPS niveau+contexte par PF\n")
    setups = []
    for r in valid:
        for c in r["top_pos_contexts"]:
            if c["pf"] >= 1.3 and c["n"] >= MIN_N_PER_CONTEXT:
                setups.append({
                    "level": r["level"], "group": r["group"],
                    "context": f"{c['dim']}={c['value']}",
                    "n": c["n"],
                    "rejection_rate": c["rejection_rate"],
                    "edge_pp": c["edge_pp"],
                    "pf": c["pf"],
                    "type": "REJECTION",
                })
        for c in r["top_neg_contexts"]:
            if c["pf"] >= 1.3 and c["n"] >= MIN_N_PER_CONTEXT:
                setups.append({
                    "level": r["level"], "group": r["group"],
                    "context": f"{c['dim']}={c['value']}",
                    "n": c["n"],
                    "rejection_rate": c["rejection_rate"],
                    "edge_pp": c["edge_pp"],
                    "pf": c["pf"],
                    "type": "ACCEPTANCE",
                })
    setups.sort(key=lambda x: x["pf"], reverse=True)

    lines.append("| # | Type | Niveau | Context | N | Rejection % | Edge | PF |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(setups[:10], 1):
        lines.append(
            f"| {i} | {s['type']} | {s['level']} ({s['group']}) | {s['context']} | "
            f"{s['n']} | {s['rejection_rate']}% | {s['edge_pp']:+}pp | {s['pf']} |"
        )
    lines.append("")

    # ─── 4. Niveaux skipped ────
    skipped = [r for r in results if "skip" in r]
    if skipped:
        lines.append(f"## 4. NIVEAUX SKIPPED ({len(skipped)})\n")
        for r in skipped:
            lines.append(f"- {r['level']} : {r.get('skip', '?')}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[REPORT] {output_path}")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="DATA/datasets/v4_enriched")
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--min-n", type=int, default=10,
                        help="Min touches global pour considerer un niveau actif")
    parser.add_argument("--proximity-pct", type=float, default=PROXIMITY_PCT_DEFAULT,
                        help="Touch threshold en pct prix (default 0.05)")
    parser.add_argument("--output", default="DOCS/LEVEL_PROB_V4.md")
    parser.add_argument("--rth-only", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print(f"LEVEL PROBABILITY V4 (45 niveaux + contexte) — {args.symbol}")
    print(f"Horizon : {args.horizon} min")
    print(f"Min N global : {args.min_n} | Min N per context : {MIN_N_PER_CONTEXT}")
    print(f"Proximity : {args.proximity_pct}% du prix")
    print(f"Sessions : {'RTH only' if args.rth_only else 'ALL (Asia+London+US+AH)'}")
    print(f"Niveaux  : {len(LEVELS_V4)}")
    print("=" * 70)

    df = load_v4_parquets(args.data_dir, args.symbol)
    if df.empty:
        return
    if args.rth_only and "is_in_us_cash" in df.columns:
        n_b = len(df)
        df = df[df["is_in_us_cash"] == 1].reset_index(drop=True)
        print(f"[RTH] {n_b} -> {len(df)}")

    print(f"\n[FORWARD] fwd_{args.horizon}m_ticks par session...")
    df = add_forward_moves_v4(df, horizon=args.horizon)

    fwd_col = f"fwd_{args.horizon}m"

    # Pre-calcul context labels (vectorise sur df)
    print("[CONTEXT] Calcul 24 dimensions de contexte (vectorise)...")
    contexts_dict = {}
    for dim in CONTEXT_DIMENSIONS:
        contexts_dict[dim] = []
    for _, bar in df.iterrows():
        ctx = classify_approach_context(bar)
        for dim in CONTEXT_DIMENSIONS:
            contexts_dict[dim].append(ctx.get(dim, "UNK"))
    for dim, values in contexts_dict.items():
        df[dim] = values

    print(f"\n[ANALYZE] {len(LEVELS_V4)} niveaux x {len(CONTEXT_DIMENSIONS)} contextes...")
    results = []
    for level_key, meta in LEVELS_V4.items():
        r = analyze_level_with_contexts(level_key, meta, df, fwd_col,
                                          args.proximity_pct, args.min_n)
        results.append(r)
        if "skip" in r:
            pass
        else:
            n_pos = len(r["top_pos_contexts"])
            n_neg = len(r["top_neg_contexts"])
            print(f"  {level_key:18s} ({meta['group']:12s}) n={r['n_touches']:>5} "
                  f"baseline={r['baseline_rej']:>4.1f}% PF={r['pf_baseline']:>4.2f} "
                  f"+ctx={n_pos} -ctx={n_neg}")

    render_report(args.symbol, results, df, args.horizon, args.output,
                  args.proximity_pct)

    valid = [r for r in results if "skip" not in r]
    valid.sort(key=lambda x: x["baseline_rej"], reverse=True)
    print(f"\n{'='*70}")
    print(f"TOP 10 NIVEAUX par baseline rejection rate")
    for r in valid[:10]:
        print(f"  {r['level']:18s} : {r['baseline_rej']:>5.1f}% (n={r['n_touches']}) PF={r['pf_baseline']:.2f}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
