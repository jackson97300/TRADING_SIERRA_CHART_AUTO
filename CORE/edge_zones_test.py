"""Test rigoureux Edge Zones sur 1 jour ES + verifications."""
import sys, time
sys.path.insert(0, 'CORE')
import pandas as pd
import numpy as np
from footprint_builder import build_footprint_per_bar
from edge_zones_engine import apply_edge_zones, _detect_stacks_for_bar
from extension_lines_manager import ExtensionLineBuffer

# ===== TEST 1: ExtensionLineBuffer behavior =====
print("=== TEST 1 : ExtensionLineBuffer ===")
buf = ExtensionLineBuffer()
# Add zone BUY a prix [6500, 6500.25] sur bar 0
buf.add_zone(0, [6500.0, 6500.25], "buy")
buf.add_zone(0, [6502.0, 6502.25, 6502.5], "buy")  # zone plus haute
print(f"  Apres 2 zones BUY: active={buf.count_active('buy')}")  # devrait 2

# Bar 1 : prix bouge mais pas dans zones (range 6505-6506)
buf.update_with_bar(1, 6505.0, 6506.0)
print(f"  Bar 1 [6505, 6506]: active={buf.count_active('buy')}")  # 2

# Bar 2 : prix touche la zone basse [6500-6500.25]
buf.update_with_bar(2, 6499.5, 6500.5)
print(f"  Bar 2 [6499.5, 6500.5] (touche zone basse): active={buf.count_active('buy')}")  # 1

# Bar 3 : prix touche la zone haute
buf.update_with_bar(3, 6501.5, 6502.75)
print(f"  Bar 3 [6501.5, 6502.75] (touche zone haute): active={buf.count_active('buy')}")  # 0

# nearest_distance avec close=6504.5 et zone haute active a 6502.0-6502.5
buf.reset()
buf.add_zone(0, [6502.0, 6502.25, 6502.5], "buy")
d = buf.nearest_distance("buy", 6504.5)
print(f"  nearest distance close=6504.5 vs zone [6502-6502.5]: {d} (attendu = -2.0, signe negatif car zone en-dessous)")

print()

# ===== TEST 2: _detect_stacks_for_bar avec cellules synthetiques =====
print("=== TEST 2 : _detect_stacks_for_bar ===")
# Cas 1 : 3 cellules consecutives buy imbalance >= 600%
cells = {
    6500.0: {"ask_vol": 0, "bid_vol": 10, "total_vol": 10, "n_trades": 1},
    6500.25: {"ask_vol": 60, "bid_vol": 10, "total_vol": 70, "n_trades": 5},  # 60/10*100=600 OK
    6500.50: {"ask_vol": 70, "bid_vol": 10, "total_vol": 80, "n_trades": 6},  # 70/10*100=700 OK
    6500.75: {"ask_vol": 80, "bid_vol": 10, "total_vol": 90, "n_trades": 7},  # 80/10*100=800 OK
    6501.00: {"ask_vol": 5, "bid_vol": 5, "total_vol": 10, "n_trades": 1},
}
stacks = _detect_stacks_for_bar(cells, 600, 0.25, 2, "buy")
print(f"  Cellules avec 3 imb buy consecutives, attend stack [6500, 6500.25, 6500.5]: {stacks}")

# Cas 2 : pas assez (1 seule cellule imb)
cells2 = {
    6500.0: {"ask_vol": 0, "bid_vol": 10, "total_vol": 10, "n_trades": 1},
    6500.25: {"ask_vol": 60, "bid_vol": 10, "total_vol": 70, "n_trades": 5},  # 600 OK
    6500.50: {"ask_vol": 5, "bid_vol": 5, "total_vol": 10, "n_trades": 1},  # break
}
stacks2 = _detect_stacks_for_bar(cells2, 600, 0.25, 2, "buy")
print(f"  Cellules avec 1 imb seul, attend []: {stacks2}")

# Cas 3 : zero handling - bid=0 doit etre traite comme 1
cells3 = {
    6500.0: {"ask_vol": 0, "bid_vol": 100, "total_vol": 100, "n_trades": 5},  # not used (no cell above)
    6500.25: {"ask_vol": 600, "bid_vol": 0, "total_vol": 600, "n_trades": 10},  # bid=0 -> 1; ratio 600/1*100=60000 (?)
}
# Attention : la formule est ratio = AskAbove / BidCurrent. Pour cell 6500.0, ask_above = ask_vol[6500.25] = 600. bid_current = bid_vol[6500.0] = 100. ratio = 600/100*100 = 600. OK
stacks3 = _detect_stacks_for_bar(cells3, 600, 0.25, 2, "buy")
print(f"  Cellules zero handling test (1 imb seule): {stacks3}")
print()

# ===== TEST 3: Sur vraie data ES 24/04/2026 =====
print("=== TEST 3 : Sur trades reels ES 24/04 ===")
trades = pd.read_parquet('DATA/databento/GLBX.MDP3/trades/symbol=ES.c.0/year=2026/month=4/day=24/data_0.parquet',
                          columns=['ts_event', 'price', 'size', 'side'])

import duckdb
con = duckdb.connect()
con.execute("SET TimeZone='UTC';")
df = con.execute("""
    SELECT ts_event::TIMESTAMP AS ts_event, open, high, low, close, volume
    FROM read_parquet('DATA/databento/GLBX.MDP3/ohlcv-1m/symbol=ES.c.0/year=2026/month=4/day=24/data_0.parquet')
    ORDER BY ts_event
""").fetchdf()
con.close()
df['ts_event'] = df['ts_event'].dt.tz_localize('UTC')

t0 = time.time()
footprint = build_footprint_per_bar(trades, df['ts_event'])
df = apply_edge_zones(df, footprint, symbol='ES')
print(f"Edge Zones full pipeline ES 24/04 : {time.time()-t0:.2f}s")

# Distribution
n_fire_buy = (df['bar_edge_buy_fire'] == 1).sum()
n_fire_sell = (df['bar_edge_sell_fire'] == 1).sum()
print(f"  bar_edge_buy_fire : {n_fire_buy}/{len(df)} ({n_fire_buy/len(df)*100:.2f}%)")
print(f"  bar_edge_sell_fire : {n_fire_sell}/{len(df)} ({n_fire_sell/len(df)*100:.2f}%)")
print(f"  zone_size_buy max : {df['bar_edge_buy_zone_size'].max()}")
print(f"  zone_size_sell max : {df['bar_edge_sell_zone_size'].max()}")
print(f"  n_active_buy max : {df['n_edge_buy_active'].max()}")
print(f"  n_active_sell max : {df['n_edge_sell_active'].max()}")

# Sanity : zones eventually deactivees (n_active doit augmenter puis diminuer)
print(f"\n=== Trajectoire n_edge_buy_active ===")
print(df[['ts_event', 'n_edge_buy_active', 'n_edge_sell_active']].iloc[::100].head(15).to_string())
