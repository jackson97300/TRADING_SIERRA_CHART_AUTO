"""Analyse rapide des resultats grid search SLTP."""
import pandas as pd
import sys

run_id = sys.argv[1] if len(sys.argv) > 1 else "test_validation"

for sym in ["NQ", "ES"]:
    path = f"DATA/BACKTEST/BOT3_GRID_SLTP/grid_{sym}_{run_id}.csv"
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"  Pas de fichier {path}")
        continue

    print("=" * 70)
    print(f"{sym} - SUMMARY ({len(df)} configs testees)")
    print("=" * 70)
    valid = df[(df["n"] >= 100) & (df["wr"] >= 50)]
    print(f"Configs valides (n>=100 & wr>=50): {len(valid)}/{len(df)}")
    if len(valid) > 0:
        print(f"PF: {valid['pf'].min():.3f} - {valid['pf'].max():.3f}")
        print(f"WR: {valid['wr'].min():.1f}% - {valid['wr'].max():.1f}%")
        print(f"EV/trade: ${valid['ev_dollars'].min():.2f} - ${valid['ev_dollars'].max():.2f}")
        print(f"Reject%: {valid['reject_pct'].min():.1f}% - {valid['reject_pct'].max():.1f}%")
        print(f"TP%: {valid['tp_pct'].min():.1f}% - {valid['tp_pct'].max():.1f}%")
        print(f"SL%: {valid['sl_pct'].min():.1f}% - {valid['sl_pct'].max():.1f}%")
        print(f"Trail%: {valid['trail_pct'].min():.1f}% - {valid['trail_pct'].max():.1f}%")
    else:
        print(f"Best PF all: {df['pf'].max():.3f}")
        print(f"Best EV all: ${df['ev_dollars'].max():.2f}")

    print()
    top5 = df.sort_values("pf", ascending=False).head(5)
    cols = ["sl_min_respiration", "sl_max_budget", "max_rr_cap", "timeout_minutes",
            "trailing_activation", "trailing_distance",
            "n", "pf", "wr", "ev_dollars", "total_pnl",
            "sl_pct", "tp_pct", "timeout_pct", "trail_pct", "reject_pct"]
    print(f"TOP 5 {sym}:")
    print(top5[cols].to_string(index=False))
    print()
