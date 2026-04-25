"""
Reconstruit MTF ES historique sur 24/04 pour diagnostiquer 0 trade ES.

Reproduit la logique de DASHBOARD/api/readers.py:read_mtf_bias
sur les bars ES US RTH pour chaque moment de la journee.

Pour chaque heure US, calcule mtf_bulls/bears sur 4 TFs (1m, 5m, 15m, 60m)
en utilisant l'historique jusqu'a ce moment.
"""
import json
from collections import Counter

ES_F = "d:/TRADING_SIERRA_CHART_AUTO/DATA/ES/20260424_ES.jsonl"
TICK_SIZE = 0.25

bars_all = []
with open(ES_F, encoding="utf-8") as f:
    for line in f:
        d = json.loads(line.strip())
        ts = d.get("ts")
        if not ts:
            continue
        price = d.get("price", 0)
        dist_vwap = d.get("dist_vwap_d", 0) or 0
        vwap_price = price + dist_vwap * TICK_SIZE if dist_vwap != 0 else price
        bars_all.append({
            "time": int(ts) // 1000,
            "ts_iso": d.get("ts_iso", ""),
            "price": price,
            "close": price,
            "high": d.get("bar_high", price),
            "low": d.get("bar_low", price),
            "delta": d.get("delta_bar", 0) or 0,
            "vwap": vwap_price,
            "volume": d.get("total_vol", 0) or 0,
            "session": d.get("session_id", "?"),
        })
# Fix open = close precedent
for i in range(1, len(bars_all)):
    bars_all[i]["open"] = bars_all[i - 1]["close"]
bars_all[0]["open"] = bars_all[0]["close"]


def aggregate(bars, tf_min):
    if tf_min <= 1:
        return bars
    interval = tf_min * 60
    agg = []
    cur = None
    for b in bars:
        bucket = (b["time"] // interval) * interval
        if cur is None or cur["bucket"] != bucket:
            if cur:
                agg.append(cur)
            cur = {
                "bucket": bucket, "time": bucket,
                "open": b["open"], "high": b["high"], "low": b["low"],
                "close": b["close"], "delta": b["delta"], "vwap": b["vwap"],
                "volume": b["volume"],
            }
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["delta"] += b["delta"]
            cur["volume"] += b["volume"]
    if cur:
        agg.append(cur)
    return agg


def mtf_vote(bars_subset, tf_min, n_bars=5):
    """Pour chaque TF, agrege bars et vote bull/bear sur les n_bars dernieres."""
    if len(bars_subset) < 5:
        return None
    agg = aggregate(bars_subset, tf_min)
    if len(agg) < n_bars:
        return None
    recent = agg[-n_bars:]
    # 3 criteres : VWAP position, delta sum, momentum price
    last = recent[-1]
    above_vwap = last["close"] > last["vwap"]
    delta_sum = sum(b["delta"] for b in recent)
    momentum_up = recent[-1]["close"] > recent[0]["open"]
    # Score
    bull = int(above_vwap) + int(delta_sum > 0) + int(momentum_up)
    bear = 3 - bull
    if bull >= 2:
        return "BULL"
    if bear >= 2:
        return "BEAR"
    return "NEUTRAL"


def compute_mtf(bars_until):
    """Reproduit read_mtf_bias pour un snapshot de bars."""
    if len(bars_until) < 5:
        return None, None, ""
    votes = {}
    for tf in (1, 5, 15, 60):
        votes[tf] = mtf_vote(bars_until, tf)
    bulls = sum(1 for v in votes.values() if v == "BULL")
    bears = sum(1 for v in votes.values() if v == "BEAR")
    verdict = f"bulls={bulls}/4 bears={bears}/4 votes={votes}"
    return bulls, bears, verdict


# Sample plusieurs moments de la journee
print("=" * 100)
print("RECONSTRUCTION MTF ES 24/04 (sample horaire)")
print("=" * 100)

# Pick bars at each hour from start to end of US
us_bars = [b for b in bars_all if b.get("session") == "US"]
if not us_bars:
    print("Pas de bars US")
    exit()

print(f"Total bars analysees : {len(bars_all)} (dont {len(us_bars)} US)")
print(f"Premier bar : {bars_all[0]['ts_iso']}")
print(f"Dernier bar : {bars_all[-1]['ts_iso']}")
print()

# Sample points : chaque heure dans US RTH + a la fin
snapshots_idx = []
us_start_time = us_bars[0]["time"]
us_end_time = us_bars[-1]["time"]
# Sample every 30 min
cur = us_start_time
while cur <= us_end_time:
    # Find nearest bar_all index
    for i, b in enumerate(bars_all):
        if b["time"] >= cur:
            if i not in snapshots_idx:
                snapshots_idx.append(i)
            break
    cur += 1800  # 30 min

print(f"{'time UTC':<22}{'price':<10}{'MTF':<25}{'verdict':<50}")
print("-" * 110)
for idx in snapshots_idx:
    b = bars_all[idx]
    bars_until = bars_all[: idx + 1]
    bulls, bears, verdict = compute_mtf(bars_until)
    if bulls is None:
        continue
    mtf_str = f"bulls={bulls} bears={bears}"
    print(f"{b['ts_iso'][:19]:<22}{b['price']:<10.2f}{mtf_str:<25}{verdict[:50]}")
print()

# Count bucket final MTF
print("=" * 100)
print("DISTRIBUTION MTF ES DURANT US RTH (sample toutes 30 min)")
print("=" * 100)
bulls_hist = Counter()
bears_hist = Counter()
for idx in snapshots_idx:
    bars_until = bars_all[: idx + 1]
    bulls, bears, _ = compute_mtf(bars_until)
    if bulls is not None:
        bulls_hist[bulls] += 1
        bears_hist[bears] += 1
print(f"Bulls distribution : {dict(bulls_hist)}")
print(f"Bears distribution : {dict(bears_hist)}")
print()
print("Interpretation : combien d'instants MTF ES aurait donne bulls>=3 ou bears>=3")
print(f"  Instants MTF bulls>=3 (aurait boost LONG) : {sum(n for b,n in bulls_hist.items() if b>=3)}")
print(f"  Instants MTF bears>=3 (aurait boost SHORT): {sum(n for b,n in bears_hist.items() if b>=3)}")
