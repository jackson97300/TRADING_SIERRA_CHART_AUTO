"""audit_databento_features.py — Inventaire complet sources data dashboard.

Objectif : repondre a la question Jackson "verifie si on a TOUT avec les donnees
Databento" pour brancher le dashboard sur Databento.

Sources auditees :
  1. Databento LIVE_CACHE (_last.json OHLCV + _last_trade.json raw trades)
  2. Databento Historical parquet V4 (DATA/V4_enriched_parquet/)
  3. DMP Sierra Chart JSONL (DATA/{ES,NQ}/*.jsonl, 262 features schema 3.7.2)
  4. MenthorQ JSON (DATA/MENTHORQ/*.json, key levels)

Pour chaque feature utilisee par les widgets dashboard, on indique :
  - Source actuelle (DMP)
  - Source Databento equivalente (si existe)
  - Calculable depuis Databento ? (et a quel cout)
  - Gap a combler (si feature pas dispo Databento)
"""
import json, glob, os
from pathlib import Path

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")

# === 1. Lire un snapshot de chaque source ===
print("=" * 80)
print("AUDIT DATABENTO — sources disponibles vs features dashboard")
print("=" * 80)

# 1A. Databento LIVE_CACHE OHLCV
print("\n[1A] Databento LIVE_CACHE OHLCV (_last.json)")
print("-" * 80)
ohlcv_path = ROOT / "DATA/LIVE_CACHE/ES_c_0_last.json"
if ohlcv_path.exists():
    with open(ohlcv_path, "r", encoding="utf-8") as f:
        ohlcv = json.load(f)
    print(f"  Champs disponibles : {sorted(ohlcv.keys())}")
else:
    print("  ABSENT")

# 1B. Databento LIVE_CACHE Trades
print("\n[1B] Databento LIVE_CACHE Trades (_last_trade.json)")
print("-" * 80)
trade_path = ROOT / "DATA/LIVE_CACHE/ES_c_0_last_trade.json"
if trade_path.exists():
    with open(trade_path, "r", encoding="utf-8") as f:
        trade = json.load(f)
    print(f"  Champs disponibles : {sorted(trade.keys())}")
else:
    print("  ABSENT")

# 1C. Databento parquet V4 enrichi (colonnes)
print("\n[1C] Databento Historical V4 parquet enrichi (colonnes)")
print("-" * 80)
v4_dir = ROOT / "DATA/V4_enriched_parquet"
if v4_dir.exists():
    parquets = sorted(v4_dir.glob("*.parquet"), key=os.path.getmtime, reverse=True)
    if parquets:
        try:
            import pyarrow.parquet as pq
            schema = pq.read_schema(parquets[0])
            cols = sorted(schema.names)
            print(f"  Fichier : {parquets[0].name}")
            print(f"  Total colonnes : {len(cols)}")
            print(f"  Premieres 30 : {cols[:30]}")
        except ImportError:
            print(f"  pyarrow non dispo (skip)")
    else:
        print("  Aucun parquet")
else:
    print("  Dir ABSENT")

# 2. DMP JSONL (last bar) - source actuelle dashboard
print("\n[2] DMP Sierra Chart JSONL (last bar) — source actuelle dashboard")
print("-" * 80)
dmp_files = sorted(glob.glob(str(ROOT / "DATA/ES/*_ES.jsonl")), key=os.path.getmtime, reverse=True)
if dmp_files:
    with open(dmp_files[0], "r", encoding="utf-8") as f:
        lines = f.readlines()
    if lines:
        bar = json.loads(lines[-1])
        cols = sorted(bar.keys())
        print(f"  Fichier : {Path(dmp_files[0]).name}")
        print(f"  Total features : {len(cols)}")
else:
    print("  ABSENT")

# === 3. Features utilisees par les widgets dashboard (Phase 1+2+3) ===
print("\n" + "=" * 80)
print("FEATURES UTILISEES PAR WIDGETS DASHBOARD (Phase 1+2+3)")
print("=" * 80)

WIDGETS = {
    "VWAP align": ["vwap_d_side", "vwap_w_side", "vwap_m_side", "vwap_slope_10",
                    "vwap_slope_10_dir", "vwap_triple_align"],
    "RVOL z-score": ["rvol", "rvol_zscore"],
    "Delta DIV": ["delta_divergence_clean", "delta_div_buy_clean",
                   "delta_div_sell_clean", "delta_div_strength"],
    "Next Wall": ["next_wall_dist_ticks", "next_wall_is_call"],
    "Trapped @ niveau": ["bn_trapped_buyers_at_resistance",
                          "bn_trapped_sellers_at_support",
                          "n_trapped_buyers_zones_active",
                          "n_trapped_sellers_zones_active"],
    "POC migration": ["poc_migration_dir", "ctx_poc_migration_10",
                       "poc_position", "dist_cur_vpoc"],
    "Absorption": ["bn_absorb_bid", "bn_absorb_ask", "bool_near_level"],
    "Setup actif (composite)": [
        "ib_broken_up", "ib_broken_down", "ib_is_narrow", "ib_position_pct",
        "profile_shape", "va_position_pct", "bars_in_va",
        "open_bias_conf", "vix_regime", "dist_swing_high", "dist_swing_low",
    ],
}

# Lire un bar DMP recent pour cross-check
bar_dmp = {}
if dmp_files:
    with open(dmp_files[0], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                bar_dmp = json.loads(line)

# Lire colonnes parquet V4 si dispo
v4_cols = set()
try:
    import pyarrow.parquet as pq
    parquets = sorted((ROOT / "DATA/V4_enriched_parquet").glob("*.parquet"),
                       key=os.path.getmtime, reverse=True)
    if parquets:
        schema = pq.read_schema(parquets[0])
        v4_cols = set(schema.names)
except (ImportError, OSError, FileNotFoundError):
    pass

# Sources Databento Live brutes (limitees)
DATABENTO_LIVE_FIELDS = {"open", "high", "low", "close", "volume", "ts_event_iso",
                         "ts_event_ns", "price", "size", "side"}

# Calculables depuis Databento Live trades + OHLCV (via Python rolling)
DATABENTO_CALCULABLE = {
    "vwap_d_side", "vwap_w_side", "vwap_m_side", "vwap_slope_10", "vwap_slope_10_dir",
    "vwap_triple_align",  # VWAP rolling depuis OHLCV
    "rvol", "rvol_zscore",  # volume vs moyenne historique
    "delta_divergence_clean", "delta_div_buy_clean", "delta_div_sell_clean",
    "delta_div_strength",  # depuis trades raw
    "poc_migration_dir", "ctx_poc_migration_10", "poc_position", "dist_cur_vpoc",
    # Volume profile reconstructible depuis trades raw + tick size
    "ib_broken_up", "ib_broken_down", "ib_is_narrow", "ib_position_pct",
    # Initial Balance reconstructible depuis OHLCV premiere heure
    "va_position_pct", "bars_in_va", "profile_shape",
    "dist_swing_high", "dist_swing_low",
}

# Externes : pas dispo Databento (sources tierces)
DATABENTO_EXTERNAL = {
    "next_wall_dist_ticks", "next_wall_is_call",  # MenthorQ
    "vix_regime", "dist_vix_*",  # VIX index (CBOE, separe)
    "open_bias_conf",  # calcule depuis open type day type Sierra
}

# Footprint = needs MBO/MBP order book Databento (pas dans subscription actuelle)
DATABENTO_NEEDS_MBO = {
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    "bn_absorb_bid", "bn_absorb_ask", "bool_near_level",  # footprint = MBO
}

print(f"\n{'Widget':<28s} {'Feature':<42s} {'DMP?':<6s} {'V4?':<5s} {'Source':<25s}")
print("-" * 110)
total = ok_dmp = ok_v4 = needs_calc = needs_external = needs_mbo = 0
for widget_name, features in WIDGETS.items():
    for feat in features:
        total += 1
        in_dmp = "✓" if feat in bar_dmp else "✗"
        in_v4 = "✓" if feat in v4_cols else "✗"
        if feat in DATABENTO_CALCULABLE:
            source = "DBN calc Python"
            needs_calc += 1
        elif feat in DATABENTO_EXTERNAL:
            source = "Externe (MQ/VIX)"
            needs_external += 1
        elif feat in DATABENTO_NEEDS_MBO:
            source = "DBN MBO/MBP needed"
            needs_mbo += 1
        else:
            source = "?"
        if in_dmp == "✓":
            ok_dmp += 1
        if in_v4 == "✓":
            ok_v4 += 1
        print(f"{widget_name:<28s} {feat:<42s} {in_dmp:<6s} {in_v4:<5s} {source:<25s}")

print("-" * 110)
print(f"\nTotal features : {total}")
print(f"  Disponibles DMP JSONL live : {ok_dmp}/{total} ({100*ok_dmp/total:.0f}%)")
print(f"  Disponibles parquet V4 enrichi : {ok_v4}/{total} ({100*ok_v4/total:.0f}%)")
print(f"  Calculables Python live depuis Databento : {needs_calc}/{total}")
print(f"  Externes (MenthorQ / VIX) : {needs_external}/{total}")
print(f"  Necessitent MBO/MBP Databento (subscribe additionnel) : {needs_mbo}/{total}")
