"""Analyse premier trade Bot 3 v4 28/05 SHORT SWING_HIGH @ 30050.0.

Demande Jackson : pourquoi ce trade a-t-il ete pris, contexte marche reel ?
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ENTRY_TS = '2026-05-28T00:58:21+00:00'

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z','+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

target = parse_ts(ENTRY_TS)

# Charger live_enriched 28/05
bars = []
with open('D:/tmp_28may_NQ.jsonl', encoding='utf-8') as f:
    for line in f:
        try:
            b = json.loads(line)
            t = b.get('ts_event')
            if t:
                b['_t'] = parse_ts(t)
                bars.append(b)
        except: pass
bars.sort(key=lambda x: x['_t'])

# Barres avant entry
prior = [b for b in bars if b['_t'] <= target]
entry_bar = prior[-1]
ctx60 = prior[-60:] if len(prior) >= 60 else prior

print(f'=== ENTRY BAR ===')
print(f'ts_event = {entry_bar.get("ts_event")}')
print(f'close = {entry_bar.get("close")}')
print(f'bar_high = {entry_bar.get("bar_high")} / bar_low = {entry_bar.get("bar_low")}')
print(f'bar_body_ticks = {entry_bar.get("bar_body_ticks")}')
print(f'bar_upper_wick_pct = {entry_bar.get("bar_upper_wick_pct")} / lower = {entry_bar.get("bar_lower_wick_pct")}')

print(f'\n=== TREND / MOMENTUM ===')
print(f'vwap_slope_10 = {entry_bar.get("vwap_slope_10")}')
sl_vals = [b.get('vwap_slope_10') for b in ctx60 if b.get('vwap_slope_10') is not None]
if sl_vals:
    print(f'vwap_slope_10 mean 60bars = {sum(sl_vals)/len(sl_vals):.4f}')
print(f'close_now - close_60ago = {(entry_bar["close"] - ctx60[0]["close"])/0.25:+.0f} ticks (60 bars)')
print(f'close_now - close_10ago = {(entry_bar["close"] - prior[-10]["close"])/0.25:+.0f} ticks (10 bars)')

print(f'\n=== POSITION RANGE ===')
print(f'position_in_range = {entry_bar.get("position_in_range")}')
pir_vals = [b.get('position_in_range') for b in ctx60 if b.get('position_in_range') is not None]
if pir_vals:
    print(f'position_in_range mean 60bars = {sum(pir_vals)/len(pir_vals):.3f}')
print(f'session_high = {entry_bar.get("session_high")} / session_low = {entry_bar.get("session_low")}')
print(f'asia_high = {entry_bar.get("asia_high")} / asia_low = {entry_bar.get("asia_low")}')
print(f'dist_swing_high = {entry_bar.get("dist_swing_high")} / dist_swing_low = {entry_bar.get("dist_swing_low")}')

print(f'\n=== ORDERFLOW ===')
print(f'delta_bar = {entry_bar.get("delta_bar")} / delta_pct = {entry_bar.get("delta_pct")}')
print(f'aggressor_imbalance = {entry_bar.get("aggressor_imbalance")}')
print(f'total_vol = {entry_bar.get("total_vol")}')
print(f'buy_vol = {entry_bar.get("buy_vol")} / sell_vol = {entry_bar.get("sell_vol")}')

print(f'\n=== BATTLE NAVALE / FOOTPRINT ===')
print(f'long_up_bar = {entry_bar.get("long_up_bar")} / long_dn_bar = {entry_bar.get("long_dn_bar")}')
print(f'bn_color_up = {entry_bar.get("bn_color_up")} / bn_color_dn = {entry_bar.get("bn_color_dn")}')
print(f'bn_score_raw = {entry_bar.get("bn_score_raw")}')
print(f'bn_absorb_bid = {entry_bar.get("bn_absorb_bid")} / bn_absorb_ask = {entry_bar.get("bn_absorb_ask")}')

print(f'\n=== MENTHORQ ===')
print(f'mq_call_resistance = {entry_bar.get("mq_call_resistance")}')
print(f'mq_put_support = {entry_bar.get("mq_put_support")}')
print(f'mq_hvl = {entry_bar.get("mq_hvl")}')
print(f'mq_gamma_condition = {entry_bar.get("mq_gamma_condition")}')
print(f'dist_mq_call_resistance_atr = {entry_bar.get("dist_mq_call_resistance_atr")}')

print(f'\n=== VIX ===')
print(f'vix_level = {entry_bar.get("vix_level")}')

print(f'\n=== ATR ===')
print(f'atr = {entry_bar.get("atr")}')
print(f'atr_14m = {entry_bar.get("atr_14m")}')

print(f'\n=== 10 dernieres bars contexte ===')
for b in prior[-10:]:
    print(f'  {b["_t"].strftime("%H:%M:%S")} close={b.get("close")} vol={b.get("total_vol")} delta={b.get("delta_bar")} slope10={b.get("vwap_slope_10")}')
