"""backtest_new_candidates_long_short.py — Backtest minutieux nouveaux candidats Bot 3.

Source : Jackson 09/05 demande backtest des 3 candidats LONG + symetriques SHORT.

Candidats LONG (rebound sur SUPPORT) :
  1. COLOR_UP -> Tier 2 (rejection 54.3% baseline NQ, n=49191)
  2. EDGE_BUY_Z + trap_buy_near=Y -> Tier 3 strict (PF 3.29 contextuel)
  3. NAKED_POC + open_type=T5 -> Tier 3 strict (PF 5.17 contextuel)
  4. PDL -> Tier 2 candidate (rej 51.7%)

Candidats SHORT (rejet sur RESISTANCE - symetriques) :
  5. COLOR_DN -> Tier 2 (rejection 50.8% baseline NQ - faible mais a verifier ES)
  6. EDGE_SELL_Z + trap_sell_near=Y -> Tier 3 strict
  7. NAKED_POC + open_type symetrique (T1=Open Drive ?) -> Tier 3
  8. PDH + prem_disc=NEUTRAL -> Tier 3 strict (PF 3.97 contextuel)

Methodologie REJECTION rate (aligne level_probability_analyzer_v4) :
  Pour chaque "touche" du niveau (dist_*_pct < proximity_threshold) :
    - LONG (bounce expected) : MOVE FWD 30bars HIGH - close_at_touch >= 8 ticks ? = rejection
    - SHORT (rejection expected) : MOVE FWD 30bars LOW - close_at_touch <= -8 ticks ? = rejection
  Rejection rate = % rejection / total touches
  PF = sum(move_when_rejection) / sum(abs(move_when_no_rejection))

Source : DATA/datasets/v4_enriched/symbol={NQ,ES}.c.0/year=*/month=*/data.parquet
Periode : 6 derniers mois (par defaut)
"""
from __future__ import annotations

import argparse
import glob
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
FORWARD_BARS = 30        # 30 bars 1m = 30 min
REJECTION_TICKS = 8      # 8 ticks = ~2 pts ES = 1R typical
PROXIMITY_PCT = 0.05     # 0.05% = ~5 ticks ES, ~12 ticks NQ
MIN_N = 100              # n minimum pour stat valide

# Candidats avec direction + contexte requis
CANDIDATES = [
    # LONG (bounce)
    {"name": "COLOR_UP", "dist_col": "dist_color_up_nearest_pct", "side": "LONG", "tier": 2, "ctx_req": None},
    {"name": "EDGE_BUY_Z", "dist_col": "dist_edge_buy_nearest_pct", "side": "LONG", "tier": 3,
     "ctx_req": ("dist_trapped_buyers_nearest_pct", "<=", 0.05)},  # trap_buy_near=Y
    {"name": "NAKED_POC_T5_LONG", "dist_col": "dist_naked_poc_nearest_pct", "side": "LONG", "tier": 3,
     "ctx_req": ("open_type", "==", 5)},
    {"name": "PDL", "dist_col": "dist_pdl_pct", "side": "LONG", "tier": 2, "ctx_req": None},
    # SHORT (rejet)
    {"name": "COLOR_DN", "dist_col": "dist_color_dn_nearest_pct", "side": "SHORT", "tier": 2, "ctx_req": None},
    {"name": "EDGE_SELL_Z", "dist_col": "dist_edge_sell_nearest_pct", "side": "SHORT", "tier": 3,
     "ctx_req": ("dist_trapped_sellers_nearest_pct", "<=", 0.05)},
    {"name": "NAKED_POC_T1_SHORT", "dist_col": "dist_naked_poc_nearest_pct", "side": "SHORT", "tier": 3,
     "ctx_req": ("open_type", "==", 1)},  # T1 = Open Drive (mirror T5 LONG)
    {"name": "PDH", "dist_col": "dist_pdh_pct", "side": "SHORT", "tier": 3,
     "ctx_req": None},  # prem_disc context = trop complexe, baseline d'abord
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
        except Exception as e:
            print(f"  [WARN] {f}: {e}")
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def evaluate_candidate(df: pd.DataFrame, sym: str, candidate: dict) -> dict:
    """Backtest 1 candidat sur df.

    Returns: {n_touches, rejection_rate, pf, top_session, top_open_type, ...}
    """
    name = candidate["name"]
    dist_col = candidate["dist_col"]
    side = candidate["side"]
    ctx_req = candidate.get("ctx_req")
    tick = TICK_SIZE[sym]
    n = len(df)
    rejection_threshold_pts = REJECTION_TICKS * tick

    if dist_col not in df.columns:
        return {"name": name, "error": f"col absent: {dist_col}"}

    # Touches : bars ou |dist_pct| < proximity AND signe coherent direction
    # LONG : bounce sur SUPPORT = niveau SOUS prix = dist_pct < 0 (price > level)
    #        ou dist_pct ~0 (price AT level)
    # SHORT : rejet sur RESISTANCE = niveau SUR prix = dist_pct > 0
    #        ou dist_pct ~0
    dist = df[dist_col].astype(float)
    abs_dist = dist.abs()
    near_mask = abs_dist <= PROXIMITY_PCT

    # Filter contextuel
    if ctx_req:
        ctx_col, op, val = ctx_req
        if ctx_col in df.columns:
            ctx_series = df[ctx_col]
            if op == "==":
                ctx_mask = ctx_series == val
            elif op == "<=":
                ctx_mask = ctx_series.abs() <= val
            elif op == ">=":
                ctx_mask = ctx_series.abs() >= val
            else:
                return {"name": name, "error": f"op inconnu: {op}"}
            near_mask = near_mask & ctx_mask
        else:
            return {"name": name, "error": f"ctx col absent: {ctx_col}"}

    touches = df[near_mask].index.tolist()
    n_touches = len(touches)
    if n_touches < MIN_N:
        return {"name": name, "n_touches": n_touches, "error": "n < min", "side": side, "tier": candidate["tier"]}

    # Pour chaque touche, evaluer forward
    n_rejection = 0
    sum_reward = 0.0   # sum |move_in_direction| pour rejection
    sum_loss = 0.0     # sum |move_against| pour no_rejection
    sessions = defaultdict(lambda: {"n": 0, "rej": 0})
    open_types = defaultdict(lambda: {"n": 0, "rej": 0})

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    for idx in touches:
        end_idx = min(idx + FORWARD_BARS, n - 1)
        if end_idx <= idx:
            continue
        close_t = closes[idx]
        # Forward window highs/lows
        fwd_high = np.max(highs[idx + 1:end_idx + 1])
        fwd_low = np.min(lows[idx + 1:end_idx + 1])
        if side == "LONG":
            move_up = (fwd_high - close_t)        # gain potentiel
            move_dn = (close_t - fwd_low)         # loss potentiel
            is_rejection = move_up >= rejection_threshold_pts
        else:  # SHORT
            move_up = (fwd_high - close_t)        # loss potentiel
            move_dn = (close_t - fwd_low)         # gain potentiel
            is_rejection = move_dn >= rejection_threshold_pts

        if is_rejection:
            n_rejection += 1
            if side == "LONG":
                sum_reward += move_up
            else:
                sum_reward += move_dn
        else:
            if side == "LONG":
                sum_loss += move_dn
            else:
                sum_loss += move_up

        # Stratification session + open_type
        bar = df.iloc[idx]
        sess = bar.get("session_id") or "?"
        ot = bar.get("open_type")
        sessions[sess]["n"] += 1
        if is_rejection:
            sessions[sess]["rej"] += 1
        if ot is not None and not pd.isna(ot):
            open_types[int(ot)]["n"] += 1
            if is_rejection:
                open_types[int(ot)]["rej"] += 1

    rejection_rate = n_rejection / n_touches if n_touches else 0
    pf = sum_reward / sum_loss if sum_loss > 0 else float("inf")
    avg_reward = sum_reward / n_rejection if n_rejection else 0
    avg_loss = sum_loss / (n_touches - n_rejection) if (n_touches - n_rejection) > 0 else 0

    # Top session + open_type (n>=20)
    best_sess = max(((s, d["rej"] / d["n"]) for s, d in sessions.items() if d["n"] >= 20),
                    key=lambda x: x[1], default=(None, 0))
    best_ot = max(((ot, d["rej"] / d["n"]) for ot, d in open_types.items() if d["n"] >= 10),
                  key=lambda x: x[1], default=(None, 0))

    return {
        "name": name,
        "side": side,
        "tier": candidate["tier"],
        "ctx_req": str(ctx_req) if ctx_req else "—",
        "n_touches": n_touches,
        "rejection_rate": rejection_rate,
        "pf": pf,
        "avg_reward_pts": avg_reward,
        "avg_loss_pts": avg_loss,
        "best_session": best_sess[0],
        "best_session_rej": best_sess[1],
        "best_open_type": best_ot[0],
        "best_ot_rej": best_ot[1],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()

    print(f"=== Backtest nouveaux candidats Bot 3 LONG + SHORT — {args.symbol} ===")
    df = load_v4(args.symbol, max_months=args.months)
    if df.empty:
        print("  Aucune data v4 enriched")
        return
    print(f"  Loaded {len(df)} bars, periode {df['ts_event'].min()} -> {df['ts_event'].max()}")
    print(f"  Forward window : {FORWARD_BARS} bars (~{FORWARD_BARS} min)")
    print(f"  Rejection threshold : {REJECTION_TICKS} ticks")
    print(f"  Proximity : {PROXIMITY_PCT}% (~{PROXIMITY_PCT * df['close'].iloc[-1] / 100 / TICK_SIZE[args.symbol]:.0f} ticks)")
    print()

    results = [evaluate_candidate(df, args.symbol, c) for c in CANDIDATES]

    print(f"{'Candidat':<25} {'Side':<6} {'T':<3} {'N':>6} {'Rej%':>6} {'PF':>6} {'AvgRew':>8} {'AvgLoss':>8} {'BestSess':<12}")
    print("-" * 95)
    for r in results:
        if "error" in r:
            print(f"  {r['name']:<23} ERR : {r['error']} (n={r.get('n_touches', 0)})")
            continue
        rej_pct = r["rejection_rate"] * 100
        pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
        bs = r.get("best_session") or "?"
        bs_rej = r.get("best_session_rej", 0) * 100
        marker = " ***" if rej_pct >= 55 and r["pf"] >= 1.3 else (" *" if rej_pct >= 52 else "")
        print(f"  {r['name']:<23} {r['side']:<6} {r['tier']:<3} {r['n_touches']:>6} {rej_pct:>5.1f}% "
              f"{pf_str:>6} {r['avg_reward_pts']:>7.1f}t {r['avg_loss_pts']:>7.1f}t {bs:<8} {bs_rej:.0f}%{marker}")

    print(f"\n{'-'*95}")
    print(f"Legende : Rej% = % touches qui ont REJECTION (move favorable >= 8t en 30 bars)")
    print(f"          PF = sum(reward) / sum(loss)")
    print(f"          *** = rej>=55% ET PF>=1.3 (Tier 1 candidate)")
    print(f"          * = rej>=52% (Tier 2 candidate)")

    # Compare baselines Tier 1 actuels
    print(f"\n=== BASELINES Tier 1 actuels (sur meme dataset) ===")
    BASELINES = [
        {"name": "MQ_PUT_0DTE_BASE", "dist_col": "dist_mq_put_0dte_pct", "side": "LONG", "tier": 1, "ctx_req": None},
        {"name": "IB_LOW_BASE", "dist_col": "dist_ib_low_pct", "side": "LONG", "tier": 1, "ctx_req": None},
        {"name": "MQ_CALL_0DTE_BASE", "dist_col": "dist_mq_call_0dte_pct", "side": "SHORT", "tier": 1, "ctx_req": None},
        {"name": "IB_HIGH_BASE", "dist_col": "dist_ib_high_pct", "side": "SHORT", "tier": 1, "ctx_req": None},
    ]
    base_results = [evaluate_candidate(df, args.symbol, c) for c in BASELINES]
    for r in base_results:
        if "error" in r:
            continue
        rej_pct = r["rejection_rate"] * 100
        pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
        print(f"  {r['name']:<23} {r['side']:<6} n={r['n_touches']:>5}  rej={rej_pct:.1f}%  PF={pf_str}")


if __name__ == "__main__":
    main()
