"""backtest_v4_modes_abd.py — Backtest empirique des 3 modes integration V4 widgets
sur Bot 1 paper trades (24/04, 28/04, 29/04, 30/04, 01/05) — 111 trades.

Modes :
  A. VETO contradictions V4 (filtre les pires setups)
  B. SIZING module par V4 (boost/reduce n_micros)
  D. Setups composites (deja existant via detect_active_setups)

Sortie : comparatif WR / PF / PnL / DD / N_trades par mode.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timezone

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")

# 1. Charger tous les trades Bot 1
def load_trades_bot1():
    trades = []
    files = sorted((ROOT / "DATA/PAPER_TRADES/").glob("2026*_trades.jsonl"))
    files = [f for f in files if "databento" not in f.name]
    for f in files:
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                    trades.append(t)
                except Exception:
                    pass
    return trades

# 2. Charger les V4 enriched par symbol (avril+mai)
def load_v4_for_symbol(sym):
    cols = ["ts_event",
            # Sources cluster_signal (refactor 04/05 swap)
            "n_big_ask_v2_t1", "n_big_bid_v2_t1",
            "near_resistance_level", "near_support_level",
            "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
            # Sources big_signal (deja live)
            "big_buy_dominance", "big_sell_dominance",
            "n_big_buy_t1", "n_big_sell_t1",
            # Source smt_signal (refactor : delta_day antisymetrique)
            "im_delta_day_divergence",
            # Source npoc_signal
            "dist_naked_poc_nearest_pct", "naked_poc_age_max_days",
            "n_naked_poc_active",
            ]
    dfs = []
    for month in (4, 5):
        p = ROOT / f"DATA/datasets/v4_enriched/symbol={sym}.c.0/year=2026/month={month:02d}/data.parquet"
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p, columns=cols)
            # Normalise tz UTC AVANT concat (fix mix tz-naive/aware)
            df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
            dfs.append(df)
        except Exception as e:
            print(f"WARN read {p}: {e}")
    if not dfs:
        return None
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df

# 3. Pour chaque trade, retrouver la barre V4 (nearest minute)
def _safe_int(x, default=0):
    """Convert to int safely (handles NaN, None, str)."""
    try:
        if x is None:
            return default
        if isinstance(x, float) and np.isnan(x):
            return default
        return int(x)
    except (ValueError, TypeError):
        return default


def enrich_trades_with_v4(trades, v4_es, v4_nq):
    enriched = []
    for t in trades:
        sym = t.get("symbol", "ES")
        v4 = v4_es if sym == "ES" else v4_nq
        if v4 is None:
            continue
        # entry_time -> dt UTC truncate to minute
        try:
            entry_dt = pd.to_datetime(t["entry_time"], utc=True).floor("min")
        except Exception:
            continue
        # nearest match (within 1 minute)
        mask = v4["ts_event"] == entry_dt
        if not mask.any():
            # fallback : barre la plus proche dans 1min
            diffs = (v4["ts_event"] - entry_dt).abs()
            idx = diffs.idxmin()
            if diffs[idx] > pd.Timedelta(minutes=1):
                continue
            row = v4.iloc[idx]
        else:
            row = v4[mask].iloc[0]
        # Compute widgets V4 signals (replique build_order_flow_advanced refactor)
        # Cluster
        if _safe_int(row.get("bn_trapped_buyers_at_resistance"), 0):
            cluster_signal = "TRAP_BUY_AT_RES"
        elif _safe_int(row.get("bn_trapped_sellers_at_support"), 0):
            cluster_signal = "TRAP_SELL_AT_SUP"
        elif _safe_int(row.get("n_big_ask_v2_t1"), 0) >= 1 and _safe_int(row.get("near_resistance_level"), 0):
            cluster_signal = "AT_RESISTANCE"
        elif _safe_int(row.get("n_big_bid_v2_t1"), 0) >= 1 and _safe_int(row.get("near_support_level"), 0):
            cluster_signal = "AT_SUPPORT"
        else:
            cluster_signal = "OFF"
        # Big orders
        big_buy_dom = float(row.get("big_buy_dominance") or 0.5)
        big_sell_dom = float(row.get("big_sell_dominance") or 0.5)
        n_buy_t1 = _safe_int(row.get("n_big_buy_t1"), 0)
        n_sell_t1 = _safe_int(row.get("n_big_sell_t1"), 0)
        if big_buy_dom >= 0.65 and n_buy_t1 >= 1:
            big_signal = "BUY_AGGRESSIVE"
        elif big_sell_dom >= 0.65 and n_sell_t1 >= 1:
            big_signal = "SELL_AGGRESSIVE"
        else:
            big_signal = "BALANCED"
        # SMT (delta_day_divergence -1/0/+1)
        im_d = _safe_int(row.get("im_delta_day_divergence"), 0)
        smt_signal = "BULL" if im_d > 0 else "BEAR" if im_d < 0 else "OFF"
        # Naked POC (informatif)
        npoc_dist = float(row.get("dist_naked_poc_nearest_pct") or 0)
        npoc_age = _safe_int(row.get("naked_poc_age_max_days"), 0)
        if 0 < npoc_dist <= 0.2 and npoc_age >= 5:
            npoc_signal = "MAGNET_STRONG"
        else:
            npoc_signal = "OFF"

        enriched.append({**t, "v4_cluster": cluster_signal, "v4_big": big_signal,
                         "v4_smt": smt_signal, "v4_npoc": npoc_signal})
    return enriched

# 4. Simulation des 3 modes
def simulate_mode_a_veto(trades):
    """Mode A : VETO contradictions V4."""
    kept = []
    blocked = []
    for t in trades:
        d = t.get("direction", "LONG")
        cl = t["v4_cluster"]
        bg = t["v4_big"]
        # Contradiction : LONG bloqué si V4 bearish, SHORT bloqué si V4 bullish
        if d == "LONG":
            if cl == "TRAP_BUY_AT_RES" or bg == "SELL_AGGRESSIVE":
                blocked.append(t)
                continue
        elif d == "SHORT":
            if cl == "TRAP_SELL_AT_SUP" or bg == "BUY_AGGRESSIVE":
                blocked.append(t)
                continue
        kept.append(t)
    return kept, blocked

def simulate_mode_b_sizing(trades):
    """Mode B : SIZING modulé V4. Retourne trades avec n_micros_v4."""
    out = []
    for t in trades:
        d = t.get("direction", "LONG")
        cl = t["v4_cluster"]
        bg = t["v4_big"]
        smt = t["v4_smt"]
        confirm = 0
        contra = 0
        if d == "LONG":
            confirm += int(cl == "AT_SUPPORT" or cl == "TRAP_SELL_AT_SUP")
            confirm += int(bg == "BUY_AGGRESSIVE")
            confirm += int(smt == "BULL")
            contra += int(cl == "AT_RESISTANCE" or cl == "TRAP_BUY_AT_RES")
            contra += int(bg == "SELL_AGGRESSIVE")
            contra += int(smt == "BEAR")
        else:  # SHORT
            confirm += int(cl == "AT_RESISTANCE" or cl == "TRAP_BUY_AT_RES")
            confirm += int(bg == "SELL_AGGRESSIVE")
            confirm += int(smt == "BEAR")
            contra += int(cl == "AT_SUPPORT" or cl == "TRAP_SELL_AT_SUP")
            contra += int(bg == "BUY_AGGRESSIVE")
            contra += int(smt == "BULL")
        # Net score
        net = confirm - contra
        if net >= 2:
            n_v4 = 4   # forte confirmation
        elif net >= 1:
            n_v4 = 3   # default (legere confirmation = pas de boost pour rester safe)
        elif net <= -2:
            n_v4 = 2   # contradiction forte
        else:
            n_v4 = 3   # neutre/incertain = default
        t2 = dict(t)
        t2["n_micros_v4"] = n_v4
        out.append(t2)
    return out

def metrics(trades, n_micros_key="n_micros"):
    """Calcule WR / PF / PnL ticks / PnL$ / N / max DD."""
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "pnl_ticks": 0, "pnl_usd": 0, "max_dd_usd": 0}
    n = len(trades)
    wins = 0
    losses = 0
    win_ticks = 0
    loss_ticks = 0
    cum_pnl = 0
    peak = 0
    max_dd = 0
    pnl_total_usd = 0
    pnl_total_ticks = 0
    for t in trades:
        ticks = t.get("pnl_ticks", 0) or 0
        # Recompute pnl_usd selon n_micros effectif
        n_mic = t.get(n_micros_key, t.get("n_micros", 3))
        sym = t.get("symbol", "ES")
        tv = 1.25 if sym == "ES" else 0.50
        pnl_usd = ticks * tv * n_mic
        pnl_total_usd += pnl_usd
        pnl_total_ticks += ticks
        if ticks > 0:
            wins += 1
            win_ticks += ticks * tv * n_mic
        else:
            losses += 1
            loss_ticks += abs(ticks * tv * n_mic)
        cum_pnl += pnl_usd
        peak = max(peak, cum_pnl)
        max_dd = max(max_dd, peak - cum_pnl)
    wr = 100 * wins / n
    pf = win_ticks / loss_ticks if loss_ticks > 0 else 999
    return {
        "n": n,
        "wr": round(wr, 1),
        "pf": round(pf, 2),
        "pnl_ticks": round(pnl_total_ticks, 1),
        "pnl_usd": round(pnl_total_usd, 2),
        "max_dd_usd": round(max_dd, 2),
        "wins": wins,
        "losses": losses,
    }

def main():
    print("="*70)
    print("BACKTEST V4 modes A+B+D — Bot 1 paper trades (24/04 - 01/05)")
    print("="*70)

    # 1. Trades historiques
    trades_raw = load_trades_bot1()
    print(f"\n[1/4] Trades Bot 1 charges: {len(trades_raw)}")

    # 2. V4 enriched
    print("[2/4] Lecture parquet V4 ES + NQ avril+mai 2026...")
    v4_es = load_v4_for_symbol("ES")
    v4_nq = load_v4_for_symbol("NQ")
    print(f"      V4 ES: {len(v4_es) if v4_es is not None else 0} barres")
    print(f"      V4 NQ: {len(v4_nq) if v4_nq is not None else 0} barres")

    # 3. Enrichir trades avec widgets V4
    print("[3/4] Enrichissement trades avec widgets V4 sur barre d'entree...")
    trades_v4 = enrich_trades_with_v4(trades_raw, v4_es, v4_nq)
    print(f"      Trades avec V4 matchee: {len(trades_v4)} / {len(trades_raw)}")

    # 4. Distribution V4 signals
    print(f"\n=== Distribution widgets V4 sur trades historiques ===")
    for col in ("v4_cluster", "v4_big", "v4_smt"):
        vc = pd.Series([t[col] for t in trades_v4]).value_counts()
        print(f"\n  {col}:")
        for k, v in vc.items():
            print(f"    {k}: {v} ({100*v/len(trades_v4):.1f}%)")

    # 5. Metriques BASELINE
    base = metrics(trades_v4)
    print(f"\n=== BASELINE (trades reels Bot 1) ===")
    print(f"  N: {base['n']}  WR: {base['wr']}%  PF: {base['pf']}  "
          f"PnL: ${base['pnl_usd']} ({base['pnl_ticks']}t)  Wins: {base['wins']} Losses: {base['losses']}  Max DD: ${base['max_dd_usd']}")

    # 6. Mode A : VETO
    kept_a, blocked_a = simulate_mode_a_veto(trades_v4)
    metrics_a = metrics(kept_a)
    metrics_blocked = metrics(blocked_a)
    print(f"\n=== MODE A : VETO contradictions V4 ===")
    print(f"  Trades bloques: {len(blocked_a)} ({100*len(blocked_a)/len(trades_v4):.1f}%)")
    print(f"  Trades blocked metrics: WR={metrics_blocked['wr']}% PF={metrics_blocked['pf']} PnL=${metrics_blocked['pnl_usd']}")
    print(f"  Trades restants: N={metrics_a['n']} WR={metrics_a['wr']}% PF={metrics_a['pf']} PnL=${metrics_a['pnl_usd']}")
    print(f"  Delta vs baseline: WR {metrics_a['wr']-base['wr']:+.1f}pp  PF {metrics_a['pf']-base['pf']:+.2f}  PnL ${metrics_a['pnl_usd']-base['pnl_usd']:+.2f}")

    # 7. Mode B : SIZING
    trades_b = simulate_mode_b_sizing(trades_v4)
    metrics_b = metrics(trades_b, n_micros_key="n_micros_v4")
    sizes_dist = pd.Series([t["n_micros_v4"] for t in trades_b]).value_counts().sort_index()
    print(f"\n=== MODE B : SIZING modulee V4 ===")
    print(f"  Distribution n_micros: {dict(sizes_dist)}")
    print(f"  N={metrics_b['n']} WR={metrics_b['wr']}% PF={metrics_b['pf']} PnL=${metrics_b['pnl_usd']}")
    print(f"  Delta vs baseline: WR {metrics_b['wr']-base['wr']:+.1f}pp  PF {metrics_b['pf']-base['pf']:+.2f}  PnL ${metrics_b['pnl_usd']-base['pnl_usd']:+.2f}")

    # 8. Mode A + B combine
    trades_a_b = simulate_mode_b_sizing(kept_a)
    metrics_ab = metrics(trades_a_b, n_micros_key="n_micros_v4")
    print(f"\n=== MODE A + B combine ===")
    print(f"  N={metrics_ab['n']} WR={metrics_ab['wr']}% PF={metrics_ab['pf']} PnL=${metrics_ab['pnl_usd']} Max DD=${metrics_ab['max_dd_usd']}")
    print(f"  Delta vs baseline: WR {metrics_ab['wr']-base['wr']:+.1f}pp  PF {metrics_ab['pf']-base['pf']:+.2f}  PnL ${metrics_ab['pnl_usd']-base['pnl_usd']:+.2f}")

    # 9. Mode D : setups composites (TRAP_*+confirm)
    setups_d = []
    for t in trades_v4:
        d = t.get("direction", "LONG")
        cl = t["v4_cluster"]
        bg = t["v4_big"]
        smt = t["v4_smt"]
        if d == "LONG":
            is_setup = (cl == "TRAP_SELL_AT_SUP" or cl == "AT_SUPPORT") and \
                       (bg == "BUY_AGGRESSIVE" or smt == "BULL")
        else:
            is_setup = (cl == "TRAP_BUY_AT_RES" or cl == "AT_RESISTANCE") and \
                       (bg == "SELL_AGGRESSIVE" or smt == "BEAR")
        if is_setup:
            setups_d.append(t)
    metrics_d = metrics(setups_d)
    print(f"\n=== MODE D : Setups composites haute conviction (cluster + big OU smt aligne) ===")
    print(f"  Trades qui matchent setup: {len(setups_d)} ({100*len(setups_d)/len(trades_v4):.1f}%)")
    if metrics_d['n'] > 0:
        print(f"  N={metrics_d['n']} WR={metrics_d['wr']}% PF={metrics_d['pf']} PnL=${metrics_d['pnl_usd']}")
        print(f"  Delta vs baseline: WR {metrics_d['wr']-base['wr']:+.1f}pp  PF {metrics_d['pf']-base['pf']:+.2f}")

    # 10. Recap final
    print(f"\n{'='*70}\nRECAP COMPARATIF (objectif : maximiser PnL avec PF >= baseline)")
    print(f"{'='*70}")
    rows = [
        ("BASELINE", base),
        ("MODE A (VETO)", metrics_a),
        ("MODE B (SIZING)", metrics_b),
        ("MODE A+B", metrics_ab),
        ("MODE D (SETUPS only)", metrics_d),
    ]
    print(f"{'MODE':<22} {'N':>4} {'WR%':>6} {'PF':>6} {'PnL$':>10} {'Max_DD$':>10}")
    for name, m in rows:
        if m['n'] > 0:
            print(f"{name:<22} {m['n']:>4} {m['wr']:>5.1f}% {m['pf']:>6.2f} {m['pnl_usd']:>10.2f} {m['max_dd_usd']:>10.2f}")
        else:
            print(f"{name:<22} N=0 (pas de trades dans ce mode)")

if __name__ == "__main__":
    main()
