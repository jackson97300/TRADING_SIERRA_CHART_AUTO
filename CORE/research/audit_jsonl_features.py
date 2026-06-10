"""audit_jsonl_features.py — verifie quelles features Phase1 widgets sont presentes dans le JSONL DMP live."""
import json, glob, os
WANTED = [
    "vwap_d_side", "vwap_w_side", "vwap_m_side", "vwap_slope_10", "vwap_slope_10_dir", "vwap_triple_align",
    "rvol", "rvol_zscore",
    "delta_divergence", "delta_divergence_clean", "delta_div_buy_clean", "delta_div_sell_clean", "delta_div_strength",
    "next_wall_dist_ticks", "next_wall_is_call",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    "poc_migration_dir", "ctx_poc_migration_10", "poc_position", "dist_cur_vpoc",
    "bn_absorb_bid", "bn_absorb_ask", "bool_near_level",
]
for sym in ("ES", "NQ"):
    files = sorted(glob.glob(f"C:/TRADING_SIERRA_CHART_AUTO/DATA/{sym}/*_{sym}.jsonl"), key=os.path.getmtime, reverse=True)
    if not files:
        print(f"{sym}: no files")
        continue
    with open(files[0], "r", encoding="utf-8") as f:
        last = None
        for line in f:
            if line.strip():
                last = line
    if not last:
        continue
    bar = json.loads(last)
    print(f"\n=== {sym} (last bar from {files[0].split(chr(92))[-1]}) ===")
    for k in WANTED:
        v = bar.get(k, "MISSING")
        marker = "[MISSING]" if v == "MISSING" else ("OK" if v != 0 else "[ZERO]")
        print(f"  {k:42s} = {str(v)[:40]:40s} {marker}")
