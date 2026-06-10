"""backtest_dbn_only_levels.py — Test rejection rate + PF tous niveaux DATABENTO PUR.

Jackson 09/05 : "TESTE QUE SUR NIVEAU DATABENTO" — identifier nouveaux niveaux
exploitables pour Bot 2 et Bot 3, en utilisant la methodologie qui a permis
de decouvrir les 13 niveaux Bot 3 actuels (rejection rate + PF + best session).

EXCLUSIONS strictes : aucune feature DMP source.
  - Pas de MQ_*, GEX_*, blind_*, dist_mq_*, dist_gex_*
  - Que des niveaux calcules Python depuis OHLCV/Trades Databento

Methodologie REJECTION (aligne level_probability_analyzer_v4) :
  Pour chaque "touche" (|dist_pct| < proximity_threshold) :
    - LONG : MOVE FWD 30b HIGH - close >= 8t = REJECTION (bounce reussi)
    - SHORT : close - MOVE FWD 30b LOW >= 8t = REJECTION (rejet reussi)
  Rejection rate = % touches reussies
  PF = sum(reward) / sum(loss)

Output : ranking + Tier suggere par level :
  *** rej >= 55% ET PF >= 1.3 -> Tier 1 candidat (haute confiance)
  **  rej >= 52% ET PF >= 1.0 -> Tier 2 candidat
  *   rej >= 50%               -> Tier 3 candidat
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
FORWARD_BARS = 30
REJECTION_TICKS = 8
PROXIMITY_PCT = 0.05
MIN_N = 100

# ─── CANDIDATS NIVEAUX SIMPLES (Databento + MQ historique propre validé 09/05) ───
# Audit MQ pollution 09/05 : 6/7 features dist_mq_* PROPRES sur ES+NQ -> OK utiliser
CANDIDATES = [
    # === LONG (bounce sur SUPPORT) ===
    # 1. Niveaux veille (J-1 daily)
    {"name": "PDL",                "dist_col": "dist_pdl_pct",                  "side": "LONG", "ctx_req": None},
    {"name": "PVAL",               "dist_col": "dist_prev_val_pct",             "side": "LONG", "ctx_req": None},
    {"name": "PVPOC_below",        "dist_col": "dist_prev_vpoc_pct",            "side": "LONG", "ctx_req": None},
    {"name": "PVWAP_SD1D",         "dist_col": "dist_pvwap_sd1d_pct",           "side": "LONG", "ctx_req": None},
    {"name": "PVWAP_SD2D",         "dist_col": "dist_pvwap_sd2d_pct",           "side": "LONG", "ctx_req": None},
    # 2. Niveaux session courante
    {"name": "IB_LOW",             "dist_col": "dist_ib_low_pct",               "side": "LONG", "ctx_req": None},
    {"name": "SWING_LOW",          "dist_col": "dist_last_swing_low_pct",       "side": "LONG", "ctx_req": None},
    {"name": "CUR_VAL",            "dist_col": "dist_cur_val_pct",              "side": "LONG", "ctx_req": None},
    {"name": "ASIA_LOW",           "dist_col": "dist_asia_low_pct",             "side": "LONG", "ctx_req": None},
    {"name": "LONDON_LOW",         "dist_col": "dist_london_low_pct",           "side": "LONG", "ctx_req": None},
    {"name": "CASH_LOW",           "dist_col": "dist_cash_low_pct",             "side": "LONG", "ctx_req": None},
    {"name": "OVN_LOW",            "dist_col": "dist_ovn_low_pct",              "side": "LONG", "ctx_req": None},
    # 3. MenthorQ + GEX (MQ historique audit PROPRE 09/05)
    {"name": "MQ_PUT",             "dist_col": "dist_mq_put_pct",               "side": "LONG", "ctx_req": None},
    {"name": "MQ_PUT_0DTE",        "dist_col": "dist_mq_put_0dte_pct",          "side": "LONG", "ctx_req": None},
    {"name": "MQ_HVL",             "dist_col": "dist_mq_hvl_pct",               "side": "LONG", "ctx_req": None},
    {"name": "GEX_DN",             "dist_col": "dist_gex_nearest_dn_pct",       "side": "LONG", "ctx_req": None},
    # 4. VWAP weekly (decouverte 09/05)
    {"name": "VWAP_W",             "dist_col": "dist_vwap_w_pct",               "side": "LONG", "ctx_req": None},
    {"name": "VWAP_W_SD1D",        "dist_col": "dist_vwap_w_sd1d_pct",          "side": "LONG", "ctx_req": None},
    {"name": "VWAP_W_SD2D",        "dist_col": "dist_vwap_w_sd2d_pct",          "side": "LONG", "ctx_req": None},
    # 5. VWAP daily SD bands
    {"name": "VWAP_D_SD1D",        "dist_col": "dist_vwap_d_sd1d_pct",          "side": "LONG", "ctx_req": None},
    {"name": "VWAP_D_SD2D",        "dist_col": "dist_vwap_d_sd2d_pct",          "side": "LONG", "ctx_req": None},
    # 6. Battle Navale extensions
    {"name": "LONG_UP_zone",       "dist_col": "dist_long_up_nearest_pct",      "side": "LONG", "ctx_req": None},
    {"name": "COLOR_UP_zone",      "dist_col": "dist_color_up_nearest_pct",     "side": "LONG", "ctx_req": None},
    # 7. Edge / delta div / NAKED / SINGLE / OPEN / TRAPPED
    {"name": "EDGE_BUY",           "dist_col": "dist_edge_buy_nearest_pct",     "side": "LONG", "ctx_req": None},
    {"name": "DELTA_DIV_BUY",      "dist_col": "dist_delta_div_buy_nearest_pct","side": "LONG", "ctx_req": None},
    {"name": "OPEN_830",           "dist_col": "dist_open_830_pct",             "side": "LONG", "ctx_req": None},
    {"name": "OPEN_930",           "dist_col": "dist_open_930_pct",             "side": "LONG", "ctx_req": None},
    {"name": "NAKED_POC",          "dist_col": "dist_naked_poc_nearest_pct",    "side": "LONG", "ctx_req": None},
    {"name": "SINGLE_PRINT",       "dist_col": "dist_single_print_nearest_pct", "side": "LONG", "ctx_req": None},
    {"name": "TRAPPED_SELLERS",    "dist_col": "dist_trapped_sellers_nearest_pct","side": "LONG", "ctx_req": None},

    # === SHORT (rejet sur RESISTANCE) ===
    {"name": "PDH",                "dist_col": "dist_pdh_pct",                  "side": "SHORT", "ctx_req": None},
    {"name": "PVAH",               "dist_col": "dist_prev_vah_pct",             "side": "SHORT", "ctx_req": None},
    {"name": "PVPOC_above",        "dist_col": "dist_prev_vpoc_pct",            "side": "SHORT", "ctx_req": None},
    {"name": "PVWAP_SD1U",         "dist_col": "dist_pvwap_sd1u_pct",           "side": "SHORT", "ctx_req": None},
    {"name": "PVWAP_SD2U",         "dist_col": "dist_pvwap_sd2u_pct",           "side": "SHORT", "ctx_req": None},
    {"name": "IB_HIGH",            "dist_col": "dist_ib_high_pct",              "side": "SHORT", "ctx_req": None},
    {"name": "SWING_HIGH",         "dist_col": "dist_last_swing_high_pct",      "side": "SHORT", "ctx_req": None},
    {"name": "CUR_VAH",            "dist_col": "dist_cur_vah_pct",              "side": "SHORT", "ctx_req": None},
    {"name": "ASIA_HIGH",          "dist_col": "dist_asia_high_pct",            "side": "SHORT", "ctx_req": None},
    {"name": "LONDON_HIGH",        "dist_col": "dist_london_high_pct",          "side": "SHORT", "ctx_req": None},
    {"name": "CASH_HIGH",          "dist_col": "dist_cash_high_pct",            "side": "SHORT", "ctx_req": None},
    {"name": "OVN_HIGH",           "dist_col": "dist_ovn_high_pct",             "side": "SHORT", "ctx_req": None},
    {"name": "MQ_CALL",            "dist_col": "dist_mq_call_pct",              "side": "SHORT", "ctx_req": None},
    {"name": "MQ_CALL_0DTE",       "dist_col": "dist_mq_call_0dte_pct",         "side": "SHORT", "ctx_req": None},
    {"name": "MQ_HVL_short",       "dist_col": "dist_mq_hvl_pct",               "side": "SHORT", "ctx_req": None},
    {"name": "GEX_UP",             "dist_col": "dist_gex_nearest_up_pct",       "side": "SHORT", "ctx_req": None},
    {"name": "VWAP_W_SD1U",        "dist_col": "dist_vwap_w_sd1u_pct",          "side": "SHORT", "ctx_req": None},
    {"name": "VWAP_W_SD2U",        "dist_col": "dist_vwap_w_sd2u_pct",          "side": "SHORT", "ctx_req": None},
    {"name": "VWAP_D_SD1U",        "dist_col": "dist_vwap_d_sd1u_pct",          "side": "SHORT", "ctx_req": None},
    {"name": "VWAP_D_SD2U",        "dist_col": "dist_vwap_d_sd2u_pct",          "side": "SHORT", "ctx_req": None},
    {"name": "LONG_DN_zone",       "dist_col": "dist_long_dn_nearest_pct",      "side": "SHORT", "ctx_req": None},
    {"name": "COLOR_DN_zone",      "dist_col": "dist_color_dn_nearest_pct",     "side": "SHORT", "ctx_req": None},
    {"name": "EDGE_SELL",          "dist_col": "dist_edge_sell_nearest_pct",    "side": "SHORT", "ctx_req": None},
    {"name": "DELTA_DIV_SELL",     "dist_col": "dist_delta_div_sell_nearest_pct","side": "SHORT", "ctx_req": None},
    {"name": "TRAPPED_BUYERS",     "dist_col": "dist_trapped_buyers_nearest_pct","side": "SHORT", "ctx_req": None},
]


# ─── COMBINAISONS DE NIVEAUX (touche simultanee de 2 niveaux differents) ───
# Inspire des candidats forts emerges aujourd'hui (audits cluster_phase_v3 + V2 backtest)
COMBOS = [
    # === LONG combos ===
    # Daily + intraday session
    {"name": "PDL_x_IB_LOW",        "side": "LONG", "cols": ["dist_pdl_pct", "dist_ib_low_pct"]},
    {"name": "PVAL_x_SWING_LOW",    "side": "LONG", "cols": ["dist_prev_val_pct", "dist_last_swing_low_pct"]},
    {"name": "PVPOC_x_IB_LOW",      "side": "LONG", "cols": ["dist_prev_vpoc_pct", "dist_ib_low_pct"]},
    # MQ + structure (V2 ES Variante C : EV +0.73t)
    {"name": "MQ_PUT_x_IB_LOW",     "side": "LONG", "cols": ["dist_mq_put_pct", "dist_ib_low_pct"]},
    {"name": "MQ_PUT_0DTE_x_IB_LOW","side": "LONG", "cols": ["dist_mq_put_0dte_pct", "dist_ib_low_pct"]},
    {"name": "MQ_HVL_x_LONDON_LOW", "side": "LONG", "cols": ["dist_mq_hvl_pct", "dist_london_low_pct"]},
    {"name": "MQ_HVL_x_SWING_LOW",  "side": "LONG", "cols": ["dist_mq_hvl_pct", "dist_last_swing_low_pct"]},
    {"name": "GEX_DN_x_IB_LOW",     "side": "LONG", "cols": ["dist_gex_nearest_dn_pct", "dist_ib_low_pct"]},
    # Battle Navale clusters
    {"name": "LONG_UP_x_COLOR_UP",  "side": "LONG", "cols": ["dist_long_up_nearest_pct", "dist_color_up_nearest_pct"]},
    {"name": "LONG_UP_x_SWING_LOW", "side": "LONG", "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"]},
    {"name": "COLOR_UP_x_PVAL",     "side": "LONG", "cols": ["dist_color_up_nearest_pct", "dist_prev_val_pct"]},
    # Edge + delta div (Tier 3 BN style)
    {"name": "EDGE_BUY_x_DELTA_BUY","side": "LONG", "cols": ["dist_edge_buy_nearest_pct", "dist_delta_div_buy_nearest_pct"]},
    {"name": "SINGLE_x_IB_LOW",     "side": "LONG", "cols": ["dist_single_print_nearest_pct", "dist_ib_low_pct"]},
    {"name": "TRAPPED_S_x_IB_LOW",  "side": "LONG", "cols": ["dist_trapped_sellers_nearest_pct", "dist_ib_low_pct"]},
    # VWAP weekly + structure
    {"name": "VWAP_W_SD1D_x_IB_LOW","side": "LONG", "cols": ["dist_vwap_w_sd1d_pct", "dist_ib_low_pct"]},

    # === SHORT combos ===
    {"name": "PDH_x_IB_HIGH",       "side": "SHORT", "cols": ["dist_pdh_pct", "dist_ib_high_pct"]},
    {"name": "PVAH_x_SWING_HIGH",   "side": "SHORT", "cols": ["dist_prev_vah_pct", "dist_last_swing_high_pct"]},
    {"name": "PVPOC_x_IB_HIGH",     "side": "SHORT", "cols": ["dist_prev_vpoc_pct", "dist_ib_high_pct"]},
    # MQ + structure
    {"name": "MQ_CALL_x_IB_HIGH",   "side": "SHORT", "cols": ["dist_mq_call_pct", "dist_ib_high_pct"]},
    {"name": "MQ_CALL_0DTE_x_IB_H", "side": "SHORT", "cols": ["dist_mq_call_0dte_pct", "dist_ib_high_pct"]},
    {"name": "MQ_HVL_x_LONDON_H",   "side": "SHORT", "cols": ["dist_mq_hvl_pct", "dist_london_high_pct"]},
    {"name": "MQ_HVL_x_SWING_H",    "side": "SHORT", "cols": ["dist_mq_hvl_pct", "dist_last_swing_high_pct"]},
    {"name": "GEX_UP_x_IB_HIGH",    "side": "SHORT", "cols": ["dist_gex_nearest_up_pct", "dist_ib_high_pct"]},
    # Battle Navale clusters
    {"name": "LONG_DN_x_COLOR_DN",  "side": "SHORT", "cols": ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"]},
    {"name": "LONG_DN_x_SWING_H",   "side": "SHORT", "cols": ["dist_long_dn_nearest_pct", "dist_last_swing_high_pct"]},
    {"name": "COLOR_DN_x_PVAH",     "side": "SHORT", "cols": ["dist_color_dn_nearest_pct", "dist_prev_vah_pct"]},
    # Edge + delta div
    {"name": "EDGE_SELL_x_DELTA_S", "side": "SHORT", "cols": ["dist_edge_sell_nearest_pct", "dist_delta_div_sell_nearest_pct"]},
    {"name": "SINGLE_x_IB_HIGH",    "side": "SHORT", "cols": ["dist_single_print_nearest_pct", "dist_ib_high_pct"]},
    {"name": "TRAPPED_B_x_IB_H",    "side": "SHORT", "cols": ["dist_trapped_buyers_nearest_pct", "dist_ib_high_pct"]},
    {"name": "VWAP_W_SD1U_x_IB_H",  "side": "SHORT", "cols": ["dist_vwap_w_sd1u_pct", "dist_ib_high_pct"]},
]


def load_v4(symbol: str, max_months: int = 6) -> pd.DataFrame:
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    if not files:
        return pd.DataFrame()
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_parquet(f))
        except Exception:
            continue
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def evaluate_candidate(df, sym, candidate):
    name = candidate["name"]
    dist_col = candidate["dist_col"]
    side = candidate["side"]
    ctx_req = candidate.get("ctx_req")
    tick = TICK_SIZE[sym]
    n = len(df)
    rej_threshold_pts = REJECTION_TICKS * tick

    if dist_col not in df.columns:
        return {"name": name, "error": f"col absent: {dist_col}", "side": side}

    dist = df[dist_col].astype(float)
    near_mask = dist.abs() <= PROXIMITY_PCT

    if ctx_req:
        ctx_col, op, val = ctx_req
        if ctx_col not in df.columns:
            return {"name": name, "error": f"ctx col absent: {ctx_col}", "side": side}
        ctx_series = df[ctx_col]
        if op == "==":
            ctx_mask = ctx_series == val
        elif op == "<=":
            ctx_mask = ctx_series.abs() <= val
        elif op == ">=":
            ctx_mask = ctx_series.abs() >= val
        else:
            return {"name": name, "error": f"op inconnu: {op}", "side": side}
        near_mask = near_mask & ctx_mask

    touches = df[near_mask].index.tolist()
    n_touches = len(touches)
    if n_touches < MIN_N:
        return {"name": name, "n_touches": n_touches, "error": "n < min", "side": side}

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    n_rejection = 0
    sum_reward = 0.0
    sum_loss = 0.0
    sessions = defaultdict(lambda: {"n": 0, "rej": 0})

    for idx in touches:
        end_idx = min(idx + FORWARD_BARS, n - 1)
        if end_idx <= idx:
            continue
        close_t = closes[idx]
        fwd_high = np.max(highs[idx + 1:end_idx + 1])
        fwd_low = np.min(lows[idx + 1:end_idx + 1])
        if side == "LONG":
            move_up = fwd_high - close_t
            move_dn = close_t - fwd_low
            is_rejection = move_up >= rej_threshold_pts
        else:
            move_up = fwd_high - close_t
            move_dn = close_t - fwd_low
            is_rejection = move_dn >= rej_threshold_pts
        if is_rejection:
            n_rejection += 1
            sum_reward += (move_up if side == "LONG" else move_dn)
        else:
            sum_loss += (move_dn if side == "LONG" else move_up)
        bar = df.iloc[idx]
        sess = bar.get("session_id") or "?"
        sessions[sess]["n"] += 1
        if is_rejection:
            sessions[sess]["rej"] += 1

    rej_rate = n_rejection / n_touches if n_touches else 0
    pf = sum_reward / sum_loss if sum_loss > 0 else float("inf")
    avg_reward = sum_reward / n_rejection if n_rejection else 0
    avg_loss = sum_loss / (n_touches - n_rejection) if (n_touches - n_rejection) > 0 else 0
    best_sess = max(((s, d["rej"] / d["n"]) for s, d in sessions.items() if d["n"] >= 20),
                    key=lambda x: x[1], default=(None, 0))

    return {
        "name": name, "side": side,
        "n_touches": n_touches, "rejection_rate": rej_rate, "pf": pf,
        "avg_reward_pts": avg_reward, "avg_loss_pts": avg_loss,
        "best_session": best_sess[0], "best_session_rej": best_sess[1],
    }


def evaluate_combo(df, sym, combo):
    """Evaluate combo : touche simultanee de 2 niveaux (les 2 dist_pct < proximity)."""
    name = combo["name"]
    cols = combo["cols"]
    side = combo["side"]
    tick = TICK_SIZE[sym]
    n = len(df)
    rej_threshold_pts = REJECTION_TICKS * tick

    # Verifier que les 2 cols existent
    for col in cols:
        if col not in df.columns:
            return {"name": name, "error": f"col absent: {col}", "side": side}

    # Mask : les 2 niveaux actifs simultanement
    masks = [df[c].astype(float).abs() <= PROXIMITY_PCT for c in cols]
    near_mask = masks[0]
    for m in masks[1:]:
        near_mask = near_mask & m

    touches = df[near_mask].index.tolist()
    n_touches = len(touches)
    if n_touches < MIN_N // 2:  # combos plus restrictifs, lower min
        return {"name": name, "n_touches": n_touches, "error": "n < min", "side": side}

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    n_rejection = 0
    sum_reward = 0.0
    sum_loss = 0.0
    for idx in touches:
        end_idx = min(idx + FORWARD_BARS, n - 1)
        if end_idx <= idx:
            continue
        close_t = closes[idx]
        fwd_high = np.max(highs[idx + 1:end_idx + 1])
        fwd_low = np.min(lows[idx + 1:end_idx + 1])
        if side == "LONG":
            move_up = fwd_high - close_t
            move_dn = close_t - fwd_low
            is_rejection = move_up >= rej_threshold_pts
        else:
            move_up = fwd_high - close_t
            move_dn = close_t - fwd_low
            is_rejection = move_dn >= rej_threshold_pts
        if is_rejection:
            n_rejection += 1
            sum_reward += (move_up if side == "LONG" else move_dn)
        else:
            sum_loss += (move_dn if side == "LONG" else move_up)
    rej_rate = n_rejection / n_touches if n_touches else 0
    pf = sum_reward / sum_loss if sum_loss > 0 else float("inf")
    avg_reward = sum_reward / n_rejection if n_rejection else 0
    avg_loss = sum_loss / (n_touches - n_rejection) if (n_touches - n_rejection) > 0 else 0
    return {
        "name": name, "side": side,
        "n_touches": n_touches, "rejection_rate": rej_rate, "pf": pf,
        "avg_reward_pts": avg_reward, "avg_loss_pts": avg_loss,
    }


def tier_label(rej_pct, pf):
    if rej_pct >= 55 and pf >= 1.3:
        return "TIER1 ***"
    if rej_pct >= 52 and pf >= 1.0:
        return "TIER2 **"
    if rej_pct >= 50:
        return "TIER3 *"
    return "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["NQ", "ES"], required=True)
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()

    sym = args.symbol
    print(f"=== Backtest niveaux DATABENTO PUR — {sym} ({args.months} mois) ===")
    df = load_v4(sym, max_months=args.months)
    if df.empty:
        print("  No data"); return
    print(f"  Loaded {len(df)} bars : {df['ts_event'].min()} -> {df['ts_event'].max()}")
    print(f"  Forward {FORWARD_BARS}b, rejection >= {REJECTION_TICKS}t, proximity {PROXIMITY_PCT}%, n>={MIN_N}")

    results = [evaluate_candidate(df, sym, c) for c in CANDIDATES]

    print(f"\n{'Candidat':<22} {'Side':<6} {'N':>7} {'Rej%':>6} {'PF':>6} {'AvgR':>6} {'AvgL':>6} {'BestSess':<6} {'Tier':>11}")
    print("-" * 100)
    # Trie : par tier puis par PF * sqrt(N)
    valid = [r for r in results if "error" not in r]
    err = [r for r in results if "error" in r]
    valid.sort(key=lambda r: -(r["pf"] if r["pf"] != float("inf") else 0) * np.sqrt(max(r["n_touches"], 1)))
    for r in valid:
        rej_pct = r["rejection_rate"] * 100
        pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
        bs_raw = r.get("best_session")
        bs = "?" if bs_raw is None else (str(bs_raw)[:8] if isinstance(bs_raw, str) else "?")
        tier = tier_label(rej_pct, r["pf"])
        print(f"  {r['name']:<20} {r['side']:<6} {r['n_touches']:>7} {rej_pct:>5.1f}% "
              f"{pf_str:>6} {r['avg_reward_pts']:>5.2f} {r['avg_loss_pts']:>5.2f} {bs:<8} {tier:>11}")
    if err:
        print(f"\n  Erreurs ({len(err)}) :")
        for r in err:
            print(f"    {r['name']:<22} {r['side']:<6} : {r.get('error')} (n={r.get('n_touches', 0)})")

    # ===== COMBINAISONS =====
    print(f"\n{'=' * 100}")
    print(f"=== COMBINAISONS DE NIVEAUX (touche simultanee) ===")
    print(f"{'=' * 100}")
    combo_results = [evaluate_combo(df, sym, c) for c in COMBOS]
    valid_c = [r for r in combo_results if "error" not in r]
    err_c = [r for r in combo_results if "error" in r]
    valid_c.sort(key=lambda r: -(r["pf"] if r["pf"] != float("inf") else 0) * np.sqrt(max(r["n_touches"], 1)))
    print(f"\n{'Combo':<25} {'Side':<6} {'N':>6} {'Rej%':>6} {'PF':>6} {'AvgR':>6} {'AvgL':>6} {'Tier':>11}")
    print("-" * 90)
    for r in valid_c:
        rej_pct = r["rejection_rate"] * 100
        pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
        tier = tier_label(rej_pct, r["pf"])
        print(f"  {r['name']:<23} {r['side']:<6} {r['n_touches']:>6} {rej_pct:>5.1f}% "
              f"{pf_str:>6} {r['avg_reward_pts']:>5.2f} {r['avg_loss_pts']:>5.2f} {tier:>11}")
    if err_c:
        print(f"\n  Combos errors ({len(err_c)}) : {[r['name'] for r in err_c]}")


if __name__ == "__main__":
    main()
