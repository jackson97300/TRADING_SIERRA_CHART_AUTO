"""mia_backtest_patterns.py — Backtest double bottom/top + divergence + niveaux.

Teste le setup complet:
  Double Bottom/Top + Delta Divergence + Niveau cle (VWAP, Options, Prev VPOC)

Pour chaque session JSONL:
1. Detecte les double bottoms/tops intraday
2. Verifie si un niveau cle est proche (confluence)
3. Verifie si delta_divergence est actif
4. Simule l'entree + SL/TP
5. Calcule win rate, profit factor, EV

Usage:
    python CORE/mia_backtest_patterns.py
    python CORE/mia_backtest_patterns.py --symbol NQ
"""
import json
import os
import sys
from datetime import datetime, timezone
from glob import glob

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA")
TICK_SIZE = 0.25


def get_field(bar, field, default=0.0):
    v = bar.get(field, default)
    return float(v) if v is not None else default


def get_int_field(bar, field, default=0):
    v = bar.get(field, default)
    return int(v) if v is not None else default


def dist_to_price(bar, dist_field):
    price = get_field(bar, "price", 0.0)
    dist = get_field(bar, "dist_" if not dist_field.startswith("dist_") else "" + dist_field, None)
    dist = bar.get(dist_field, None)
    if dist is None or price == 0:
        return None
    return price + float(dist) * TICK_SIZE


def load_bars(filepath):
    bars = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                bars.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return bars


def get_key_levels(bar):
    """Extrait tous les niveaux cles depuis une barre DMP."""
    price = get_field(bar, "price", 0.0)
    if not price:
        return []

    levels = []

    def add(name, dist_field, category):
        dist = bar.get(dist_field)
        if dist is not None:
            lvl_price = price + float(dist) * TICK_SIZE
            levels.append({"name": name, "price": lvl_price, "category": category})

    # Options MenthorQ
    add("Call Wall", "dist_mq_call", "options")
    add("Put Wall", "dist_mq_put", "options")
    add("HVL", "dist_mq_hvl", "options")
    add("0DTE Call", "dist_mq_call_0dte", "options")
    add("0DTE Put", "dist_mq_put_0dte", "options")
    # VWAP
    add("VWAP D", "dist_vwap_d", "vwap")
    add("VWAP W", "dist_vwap_w", "vwap")
    add("VWAP M", "dist_vwap_m", "vwap")
    add("SD1+", "dist_vwap_d_sd1u", "vwap")
    add("SD1-", "dist_vwap_d_sd1d", "vwap")
    add("SD2+", "dist_vwap_d_sd2u", "vwap")
    add("SD2-", "dist_vwap_d_sd2d", "vwap")
    # Market Profile prev
    add("Prev VPOC", "dist_prev_vpoc", "profile")
    add("Prev VAH", "dist_prev_vah", "profile")
    add("Prev VAL", "dist_prev_val", "profile")
    add("Prev VWAP", "dist_prev_vwap", "profile")
    # IB
    add("IB High", "dist_ib_high", "ib")
    add("IB Low", "dist_ib_low", "ib")
    # OVN
    add("OVN High", "dist_ovn_high", "ovn")
    add("OVN Low", "dist_ovn_low", "ovn")

    return levels


def find_nearby_levels(price, levels, tolerance_ticks=15):
    """Trouve les niveaux cles proches d'un prix."""
    nearby = []
    for lvl in levels:
        if lvl["price"] is None:
            continue
        dist = abs(price - lvl["price"]) / TICK_SIZE
        if dist <= tolerance_ticks:
            nearby.append({**lvl, "dist_ticks": round(dist, 1)})
    return nearby


def backtest_session(filepath, symbol):
    """Backteste une session complete."""
    bars = load_bars(filepath)
    if len(bars) < 60:
        return []

    date_str = os.path.basename(filepath).split("_")[0]
    tick = TICK_SIZE
    tolerance = 120 if symbol == "NQ" else 40
    min_bars = 30
    min_retrace = 30 * tick
    level_proximity = 15  # ticks

    # Collecter swing lows/highs
    swing_lows = []
    swing_highs = []

    for i, b in enumerate(bars):
        price = get_field(b, "price")
        bar_low = get_field(b, "bar_low")
        bar_high = get_field(b, "bar_high")
        vol = get_field(b, "total_vol")
        delta = get_field(b, "delta_bar")

        if get_int_field(b, "new_swing_low"):
            swing_lows.append({
                "idx": i, "price": bar_low, "vol": vol, "delta": delta,
                "delta_div": get_int_field(b, "retest_low_delta_div"),
                "bar": b,
            })
        if get_int_field(b, "new_swing_high"):
            swing_highs.append({
                "idx": i, "price": bar_high, "vol": vol, "delta": delta,
                "delta_div": get_int_field(b, "retest_high_delta_div"),
                "bar": b,
            })

    trades = []

    # Double bottoms
    for i in range(len(swing_lows)):
        for j in range(i + 1, len(swing_lows)):
            s1, s2 = swing_lows[i], swing_lows[j]
            gap = s2["idx"] - s1["idx"]
            if gap < min_bars:
                continue
            diff = abs(s1["price"] - s2["price"]) / tick
            if diff > tolerance:
                continue

            avg_low = (s1["price"] + s2["price"]) / 2
            neckline = max(get_field(bars[k], "bar_high") for k in range(s1["idx"], s2["idx"] + 1))
            if neckline - avg_low < min_retrace:
                continue

            # Confirmations
            vol_ratio = s2["vol"] / s1["vol"] if s1["vol"] > 0 else 1
            vol_ok = vol_ratio >= 1.2  # vol MONTE au 2eme bottom
            delta_ok = s2["delta"] > 0
            div_ok = bool(s2["delta_div"]) or bool(get_int_field(s2["bar"], "delta_divergence"))

            # Niveaux cles proches du bottom
            levels = get_key_levels(s2["bar"])
            nearby = find_nearby_levels(avg_low, levels, level_proximity)
            level_ok = len(nearby) > 0

            # Score
            quality = 0
            if diff <= tolerance / 3:
                quality += 2
            elif diff <= tolerance / 2:
                quality += 1
            if vol_ok:
                quality += 2
            if delta_ok:
                quality += 1
            if div_ok:
                quality += 2
            if level_ok:
                quality += 2
            if gap >= 60:
                quality += 1

            if quality < 4:
                continue

            # Simuler le trade : LONG au close de la barre du 2eme bottom
            entry_idx = s2["idx"] + 1
            if entry_idx >= len(bars):
                continue
            entry_price = get_field(bars[entry_idx], "price")
            sl_price = min(s1["price"], s2["price"]) - 4 * tick  # SL sous le double bottom
            tp_price = neckline  # TP a la neckline

            # Simuler le resultat
            result = simulate_trade(bars, entry_idx, entry_price, sl_price, tp_price, "LONG", max_bars=120)

            trades.append({
                "date": date_str,
                "symbol": symbol,
                "type": "DOUBLE_BOTTOM",
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "entry_bar": entry_idx,
                "quality": quality,
                "vol_confirmed": vol_ok,
                "delta_confirmed": delta_ok,
                "div_confirmed": div_ok,
                "level_confirmed": level_ok,
                "nearby_levels": [l["name"] for l in nearby],
                "bars_between": gap,
                **result,
            })

    # Double tops
    for i in range(len(swing_highs)):
        for j in range(i + 1, len(swing_highs)):
            s1, s2 = swing_highs[i], swing_highs[j]
            gap = s2["idx"] - s1["idx"]
            if gap < min_bars:
                continue
            diff = abs(s1["price"] - s2["price"]) / tick
            if diff > tolerance:
                continue

            avg_high = (s1["price"] + s2["price"]) / 2
            neckline = min(get_field(bars[k], "bar_low") for k in range(s1["idx"], s2["idx"] + 1) if get_field(bars[k], "bar_low") > 0)
            if avg_high - neckline < min_retrace:
                continue

            vol_ratio = s2["vol"] / s1["vol"] if s1["vol"] > 0 else 1
            vol_ok = vol_ratio <= 0.8  # vol BAISSE au 2eme top
            delta_ok = s2["delta"] < 0
            div_ok = bool(s2["delta_div"]) or bool(get_int_field(s2["bar"], "delta_divergence"))

            levels = get_key_levels(s2["bar"])
            nearby = find_nearby_levels(avg_high, levels, level_proximity)
            level_ok = len(nearby) > 0

            quality = 0
            if diff <= tolerance / 3:
                quality += 2
            elif diff <= tolerance / 2:
                quality += 1
            if vol_ok:
                quality += 2
            if delta_ok:
                quality += 1
            if div_ok:
                quality += 2
            if level_ok:
                quality += 2
            if gap >= 60:
                quality += 1

            if quality < 4:
                continue

            entry_idx = s2["idx"] + 1
            if entry_idx >= len(bars):
                continue
            entry_price = get_field(bars[entry_idx], "price")
            sl_price = max(s1["price"], s2["price"]) + 4 * tick
            tp_price = neckline

            result = simulate_trade(bars, entry_idx, entry_price, sl_price, tp_price, "SHORT", max_bars=120)

            trades.append({
                "date": date_str,
                "symbol": symbol,
                "type": "DOUBLE_TOP",
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "entry_bar": entry_idx,
                "quality": quality,
                "vol_confirmed": vol_ok,
                "delta_confirmed": delta_ok,
                "div_confirmed": div_ok,
                "level_confirmed": level_ok,
                "nearby_levels": [l["name"] for l in nearby],
                "bars_between": gap,
                **result,
            })

    return trades


def simulate_trade(bars, entry_idx, entry, sl, tp, direction, max_bars=120):
    """Simule un trade et retourne le resultat."""
    for i in range(entry_idx + 1, min(entry_idx + max_bars, len(bars))):
        high = get_field(bars[i], "bar_high")
        low = get_field(bars[i], "bar_low")

        if direction == "LONG":
            if low <= sl:
                pnl = (sl - entry) / TICK_SIZE
                return {"outcome": "SL", "pnl_ticks": round(pnl), "exit_bar": i, "bars_held": i - entry_idx}
            if high >= tp:
                pnl = (tp - entry) / TICK_SIZE
                return {"outcome": "TP", "pnl_ticks": round(pnl), "exit_bar": i, "bars_held": i - entry_idx}
        else:
            if high >= sl:
                pnl = (entry - sl) / TICK_SIZE
                return {"outcome": "SL", "pnl_ticks": round(pnl), "exit_bar": i, "bars_held": i - entry_idx}
            if low <= tp:
                pnl = (entry - tp) / TICK_SIZE
                return {"outcome": "TP", "pnl_ticks": round(pnl), "exit_bar": i, "bars_held": i - entry_idx}

    # Timeout — fermer au prix de la derniere barre
    last_price = get_field(bars[min(entry_idx + max_bars - 1, len(bars) - 1)], "price")
    if direction == "LONG":
        pnl = (last_price - entry) / TICK_SIZE
    else:
        pnl = (entry - last_price) / TICK_SIZE
    return {"outcome": "TIMEOUT", "pnl_ticks": round(pnl), "exit_bar": min(entry_idx + max_bars, len(bars) - 1), "bars_held": max_bars}


def run_backtest(symbol="ES"):
    pattern_path = os.path.join(DATA_DIR, symbol, f"*_{symbol}.jsonl")
    files = sorted(glob(pattern_path))

    all_trades = []
    for f in files:
        if os.path.getsize(f) < 100000:
            continue
        trades = backtest_session(f, symbol)
        all_trades.extend(trades)

    print(f"\n{'='*80}")
    print(f"BACKTEST DOUBLE BOTTOM/TOP + DIV + NIVEAUX — {symbol}")
    print(f"{'='*80}")
    print(f"Sessions analysees: {len(files)}")
    print(f"Trades detectes: {len(all_trades)}")

    if not all_trades:
        print("Aucun trade trouve.")
        return

    # Stats globales
    wins = [t for t in all_trades if t["outcome"] == "TP"]
    losses = [t for t in all_trades if t["outcome"] == "SL"]
    timeouts = [t for t in all_trades if t["outcome"] == "TIMEOUT"]
    total_pnl = sum(t["pnl_ticks"] for t in all_trades)
    win_pnl = sum(t["pnl_ticks"] for t in wins)
    loss_pnl = sum(abs(t["pnl_ticks"]) for t in losses)

    wr = len(wins) / len(all_trades) * 100 if all_trades else 0
    pf = win_pnl / loss_pnl if loss_pnl > 0 else float("inf")
    ev = total_pnl / len(all_trades) if all_trades else 0

    print(f"\n--- RESULTATS GLOBAUX ---")
    print(f"Win Rate: {wr:.1f}% ({len(wins)}W / {len(losses)}L / {len(timeouts)}T)")
    print(f"Profit Factor: {pf:.2f}")
    print(f"EV/trade: {ev:+.1f} ticks")
    print(f"Total PnL: {total_pnl:+.0f} ticks")

    # Par type
    for ptype in ("DOUBLE_BOTTOM", "DOUBLE_TOP"):
        subset = [t for t in all_trades if t["type"] == ptype]
        if not subset:
            continue
        w = sum(1 for t in subset if t["outcome"] == "TP")
        l = sum(1 for t in subset if t["outcome"] == "SL")
        pnl = sum(t["pnl_ticks"] for t in subset)
        print(f"\n  {ptype}: {len(subset)} trades, WR={w}/{len(subset)} ({w/len(subset)*100:.0f}%), PnL={pnl:+.0f}t")

    # Par qualite
    print(f"\n--- PAR QUALITE ---")
    for min_q in (4, 5, 6, 7):
        subset = [t for t in all_trades if t["quality"] >= min_q]
        if not subset:
            continue
        w = sum(1 for t in subset if t["outcome"] == "TP")
        pnl = sum(t["pnl_ticks"] for t in subset)
        print(f"  Q>={min_q}: {len(subset)} trades, WR={w/len(subset)*100:.0f}%, PnL={pnl:+.0f}t")

    # Par confirmation
    print(f"\n--- PAR CONFIRMATION ---")
    for label, key in [("Volume", "vol_confirmed"), ("Delta", "delta_confirmed"), ("Divergence", "div_confirmed"), ("Niveau cle", "level_confirmed")]:
        with_conf = [t for t in all_trades if t.get(key)]
        without = [t for t in all_trades if not t.get(key)]
        if with_conf:
            w = sum(1 for t in with_conf if t["outcome"] == "TP")
            pnl = sum(t["pnl_ticks"] for t in with_conf)
            print(f"  AVEC {label}: {len(with_conf)} trades, WR={w/len(with_conf)*100:.0f}%, PnL={pnl:+.0f}t")
        if without:
            w = sum(1 for t in without if t["outcome"] == "TP")
            pnl = sum(t["pnl_ticks"] for t in without)
            print(f"  SANS {label}: {len(without)} trades, WR={w/len(without)*100:.0f}%, PnL={pnl:+.0f}t")

    # Setup A+ : vol + div + niveau
    aplus = [t for t in all_trades if t.get("vol_confirmed") and t.get("div_confirmed") and t.get("level_confirmed")]
    if aplus:
        w = sum(1 for t in aplus if t["outcome"] == "TP")
        pnl = sum(t["pnl_ticks"] for t in aplus)
        print(f"\n  *** SETUP A+ (vol+div+niveau): {len(aplus)} trades, WR={w/len(aplus)*100:.0f}%, PnL={pnl:+.0f}t ***")

    # Detail des trades
    print(f"\n--- DETAIL DES TRADES ---")
    for t in all_trades:
        levels_str = ",".join(t.get("nearby_levels", [])[:3])
        conf = []
        if t.get("vol_confirmed"):
            conf.append("V")
        if t.get("delta_confirmed"):
            conf.append("D")
        if t.get("div_confirmed"):
            conf.append("DIV")
        if t.get("level_confirmed"):
            conf.append("LVL")
        conf_str = "+".join(conf) if conf else "none"
        print(f"  {t['date']} {t['type']:15} Q:{t['quality']} | {t['outcome']:7} {t['pnl_ticks']:+5.0f}t | {conf_str:12} | {levels_str}")


if __name__ == "__main__":
    symbol = "ES"
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1].upper()

    if symbol == "ALL":
        for s in ("ES", "NQ"):
            run_backtest(s)
    else:
        run_backtest(symbol)
