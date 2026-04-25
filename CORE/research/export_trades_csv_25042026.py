"""
Export 18 trades 24/04 en CSV pour analyse manuelle Jackson.

Combine data des 3 sources :
- snapshots_v2_ml (entry context : conf, mtf, dmp_bar 266 features)
- trades.jsonl (outcome, PnL, MAE, MFE, exit_context)
- Selection features cles pour Excel

Output : DATA/PAPER_TRADES/20260424_trades_analyse.csv
"""
import json
import csv

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"
SNAPS_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_snapshots.jsonl"
TRADES_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_trades.jsonl"
OUT_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_trades_analyse.csv"


def main():
    snaps = [json.loads(l) for l in open(SNAPS_F, encoding="utf-8")]
    trades = [json.loads(l) for l in open(TRADES_F, encoding="utf-8")]
    snap_by_id = {s["trade_id"]: s for s in snaps}

    rows = []
    for t in trades:
        s = snap_by_id.get(t["trade_id"], {})
        db = s.get("dmp_bar", {}) or {}
        ec = t.get("exit_context", {}) or {}
        row = {
            # Identite
            "trade_id": t["trade_id"],
            "symbol": t["symbol"],
            "direction": t["direction"],
            "entry_time_utc": t["entry_time"][11:19],
            "exit_time_utc": t["exit_time"][11:19],
            "duration_sec": round(t["duration_sec"]),
            "bars_held": t["bars_held"],
            "session": db.get("session_id"),
            # Prix
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "sl_price": s.get("sl_price"),
            "tp_price": s.get("tp_price"),
            # Outcome
            "outcome": t["outcome"],
            "pnl_ticks": t["pnl_ticks"],
            "pnl_usd": t.get("pnl_usd"),
            "mae_ticks": t["mae"],
            "mfe_ticks": t["mfe"],
            # SLTP params
            "sl_ticks": s.get("sl_ticks"),
            "tp_ticks": s.get("tp_ticks"),
            "sl_wall": t.get("sl_wall"),
            "sl_tier": t.get("sl_tier"),
            "tp_wall": t.get("tp_wall"),
            "rr_ratio": t.get("rr_ratio"),
            "expected_payoff_usd": t.get("expected_payoff_usd"),
            # Conseil decision
            "conseil_action": s.get("conseil_action"),
            "confidence": s.get("confidence"),
            "mtf_bulls": s.get("mtf_bulls"),
            "mtf_bears": s.get("mtf_bears"),
            "conseil_bull_pts": s.get("conseil_bull_pts"),
            "conseil_bear_pts": s.get("conseil_bear_pts"),
            # Regime + marche (entry)
            "atr_14m_ticks": db.get("atr_14m"),
            "dist_vwap_d_atr": db.get("dist_vwap_d_atr"),
            "range_pos_pct": db.get("range_pos"),
            "range_size_ticks": db.get("range_size_ticks"),
            "momentum_3b": db.get("momentum_3b"),
            "momentum_5b": db.get("momentum_5b"),
            "rvol_1m": db.get("rvol_1m"),
            "vix": db.get("vix"),
            # MenthorQ
            "mq_gamma_condition": db.get("mq_gamma_condition"),
            "mq_iv_30d": db.get("mq_iv_30d"),
            "mq_net_gex": db.get("mq_net_gex"),
            "mq_dist_call_resistance_atr": db.get("mq_dist_call_resistance_atr"),
            "mq_dist_put_support_atr": db.get("mq_dist_put_support_atr"),
            "mq_dist_hvl_atr": db.get("mq_dist_hvl_atr"),
            # Order flow entry
            "ask_bid_imbalance": db.get("ask_bid_imbalance"),
            "delta_bar_vol_norm": db.get("delta_bar_vol_norm"),
            "cvd_bar_delta": db.get("cvd_bar_delta"),
            "delta_day_dir": db.get("delta_day_dir"),
            # Contexte exit (snapshot au moment close)
            "exit_regime_bias": ec.get("regime_bias"),
            "exit_regime_favor": ec.get("regime_favor"),
            "exit_conseil_action": ec.get("conseil_action"),
            "exit_atr": ec.get("atr"),
            "exit_vix": ec.get("vix"),
            "exit_rvol": ec.get("rvol"),
            # Bracket DTC
            "parent_id": t.get("parent_id"),
            "tp_cid": t.get("tp_cid"),
            "sl_cid": t.get("sl_cid"),
            "exit_order_id": t.get("exit_order_id"),
            "slip_entry_ticks": t.get("slip_entry_ticks"),
            "slip_exit_ticks": t.get("slip_exit_ticks"),
        }
        rows.append(row)

    # Sort chronologique
    rows.sort(key=lambda r: r["entry_time_utc"])

    # Write CSV
    if not rows:
        print("Aucun trade trouve")
        return
    with open(OUT_F, "w", encoding="utf-8-sig", newline="") as f:  # BOM utf-8 pour Excel FR
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)

    print(f"OK : {len(rows)} trades exportes")
    print(f"Fichier : {OUT_F}")
    print(f"Format : CSV separateur ;  encoding UTF-8 BOM (ouverture directe Excel FR)")
    print(f"Colonnes : {len(rows[0])}")
    print()
    print("=== APERCU ===")
    for r in rows[:2]:
        print(f"  {r['entry_time_utc']} {r['symbol']} {r['direction']} "
              f"{r['outcome']}={r['pnl_ticks']:+.0f}t "
              f"conf={r['confidence']} mtf={r['mtf_bulls']}/{r['mtf_bears']} "
              f"sl_wall={r['sl_wall']}")


if __name__ == "__main__":
    main()
