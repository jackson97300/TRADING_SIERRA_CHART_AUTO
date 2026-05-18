"""Backtest confluence Jackson sur DMP RAW Sierra Chart.

Jackson 19/05 directive : "FAIS LE SUR DMP SIERRA CHART PUIS V4 - DROP LONG BAR
(juste transition 1 bar)".

Confluence LONG (rebond support MQ_1D_LL) - DMP raw NQ format ticks :
- `dist_1d_min_ticks` proximity <= 20 ticks (= 5 pts NQ touche MQ_1D_min)
- AU MOINS 2/4 confirmations parmi :
    a) `bar_color_up`==1 (COLOR UP active sur la barre)
    b) `bar_edge_buy`==1 (EDGE BUY zone fire sur la barre)
    c) `dist_ext_color_up` in [-100, 0] (proche extension COLOR UP zone)
    d) `dist_ext_edge_buy` in [-100, 0] (proche extension EDGE BUY zone)
    e) BONUS niveau veille proche : abs(dist_prev_val) <= 50t OR abs(dist_pdl) <= 50t

Convention DMP : tous les `dist_*` en TICKS bruts (1 tick NQ = 0.25 = $0.50/micro)
Convention `dist_ext_X = -3` => 3 ticks au-dessous de l'extension X = dans la zone.

Output : n events, TP/SL/timeout distribution, WR, PF, avg pnl.

LIMITE : data DMP raw NQ ~14 jours (24/04 + mai). Edge significatif Lopez n_min=30/fold
requiert >=360 events. Sur 14 jours probablement insuffisant => extension VPS si prometteur.

Usage : python -X utf8 tools/backtest_confluence_jackson.py
"""
from __future__ import annotations

import json
from glob import glob
from pathlib import Path

NQ_FILES = sorted(glob("DATA/NQ/2026*_NQ.jsonl"))
NQ_FILES = [f for f in NQ_FILES if "PRE_FIX" not in f and "fresh" not in f and "v2" not in f]

PROXIMITY_TICKS = 20  # touche MQ_1D_min : <= 20 ticks NQ (= 5 pts)
TP_TICKS = 80         # +80t (20 pts NQ) = TP rebond raisonnable
SL_TICKS = 40         # -40t (10 pts NQ) = SL sous le low
MAX_BARS = 30         # exit timeout 30 min
TICK_SIZE = 0.25
MIN_CONFLUENCE = 2    # min 2 confirmations sur 5


def confluence_score(bar: dict) -> tuple[int, list[str]]:
    """Compte le nombre de confirmations Jackson actives sur cette barre.

    LUB drop intentionnel (Jackson 19/05 : "juste 1 barre de transition").
    """
    score = 0
    reasons = []
    if bar.get("bar_color_up") == 1:
        score += 1
        reasons.append("COLOR_UP_bar")
    if bar.get("bar_edge_buy") == 1:
        score += 1
        reasons.append("EDGE_BUY_bar")
    d_color = bar.get("dist_ext_color_up")
    if d_color is not None and -100 < d_color < 0:
        score += 1
        reasons.append(f"NEAR_COLOR_UP_ext({d_color}t)")
    d_edge = bar.get("dist_ext_edge_buy")
    if d_edge is not None and -100 < d_edge < 0:
        score += 1
        reasons.append(f"NEAR_EDGE_BUY_ext({d_edge}t)")
    # Bonus : niveau veille proche (PDL/PVAL <= 50t)
    d_pdl = bar.get("dist_pdl")
    d_pval = bar.get("dist_prev_val")
    near_prev = False
    if d_pdl is not None and abs(d_pdl) <= 50:
        near_prev = True
        reasons.append(f"NEAR_PDL({d_pdl}t)")
    if d_pval is not None and abs(d_pval) <= 50:
        near_prev = True
        reasons.append(f"NEAR_PVAL({d_pval}t)")
    if near_prev:
        score += 1
    return score, reasons


def simulate_exit(bars: list[dict], entry_idx: int, entry_price: float) -> tuple[str, float, int]:
    """Simule exit LONG TP/SL/timeout. Retourne (reason, pnl_ticks, bars_held)."""
    tp_price = entry_price + TP_TICKS * TICK_SIZE
    sl_price = entry_price - SL_TICKS * TICK_SIZE
    for j in range(entry_idx + 1, min(entry_idx + 1 + MAX_BARS, len(bars))):
        b = bars[j]
        high = b.get("high") or b.get("bar_high")
        low = b.get("low") or b.get("bar_low")
        if high is None or low is None:
            continue
        # LONG : check TP first if simul "fav"
        if high >= tp_price:
            return ("TP", (tp_price - entry_price) / TICK_SIZE, j - entry_idx)
        if low <= sl_price:
            return ("SL", (sl_price - entry_price) / TICK_SIZE, j - entry_idx)
    # Timeout : exit at last close
    last_close = bars[min(entry_idx + MAX_BARS, len(bars) - 1)].get("close") or entry_price
    return ("TIMEOUT", (last_close - entry_price) / TICK_SIZE, MAX_BARS)


def main() -> int:
    print(f"=== Backtest confluence Jackson MQ_1D_LL + COLOR/LUB/EDGE ===")
    print(f"Files : {len(NQ_FILES)} NQ DMP jsonl")
    print(f"Confluence min : {MIN_CONFLUENCE}/5 confirmations")
    print(f"TP={TP_TICKS}t SL={SL_TICKS}t timeout={MAX_BARS} bars")
    print()

    events = []
    n_bars_total = 0
    n_touch_mq1d_min = 0
    distrib_score = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for path in NQ_FILES:
        with open(path, "r") as f:
            bars = []
            for line in f:
                try:
                    b = json.loads(line.strip())
                    bars.append(b)
                except (json.JSONDecodeError, ValueError):
                    continue
        n_bars_total += len(bars)

        for i, bar in enumerate(bars):
            # DMP raw format : dist_1d_min_ticks (TICKS, pas pct)
            d_mq = bar.get("dist_1d_min_ticks")
            if d_mq is None:
                continue
            if abs(d_mq) > PROXIMITY_TICKS:
                continue
            n_touch_mq1d_min += 1
            score, reasons = confluence_score(bar)
            distrib_score[score] += 1
            if score < MIN_CONFLUENCE:
                continue
            entry_price = bar.get("close") or bar.get("bar_close")
            if entry_price is None:
                continue
            exit_reason, pnl_ticks, bars_held = simulate_exit(bars, i, entry_price)
            events.append({
                "file": Path(path).name,
                "bar_idx": i,
                "ts": bar.get("ts_event"),
                "entry": entry_price,
                "score": score,
                "reasons": reasons,
                "exit_reason": exit_reason,
                "pnl_ticks": pnl_ticks,
                "bars_held": bars_held,
                "mq_1d_min": bar.get("mq_1d_min"),
                "dist_mq_1d_min_pct": d_mq,
            })

    print(f"Bars total : {n_bars_total}")
    print(f"Touch MQ_1D_min (prox <= {PROXIMITY_TICKS}t) : {n_touch_mq1d_min}")
    print(f"Distribution score confluence : {distrib_score}")
    print(f"Events >= {MIN_CONFLUENCE}/5 : {len(events)}")
    print()

    if not events:
        print("Aucun event confluence sur ces data. Try relaxe MIN_CONFLUENCE ou plus de data.")
        return 0

    n_win = sum(1 for e in events if e["pnl_ticks"] > 0)
    n_loss = sum(1 for e in events if e["pnl_ticks"] <= 0)
    win_t = sum(e["pnl_ticks"] for e in events if e["pnl_ticks"] > 0)
    loss_t = abs(sum(e["pnl_ticks"] for e in events if e["pnl_ticks"] <= 0)) or 1
    pf = win_t / loss_t
    pnl_total = sum(e["pnl_ticks"] for e in events)

    print(f"=== STATS ===")
    print(f"n={len(events)} | wins={n_win} losses={n_loss}")
    print(f"WR={n_win / len(events) * 100:.1f}%  PF={pf:.2f}  pnl_total={pnl_total:.0f}t ({pnl_total * 0.5:.0f}$/micro)")
    avg = pnl_total / len(events)
    print(f"avg_per_trade={avg:.1f}t ({avg * 0.5:.1f}$/micro)")
    print()
    exit_distrib = {}
    for e in events:
        exit_distrib[e["exit_reason"]] = exit_distrib.get(e["exit_reason"], 0) + 1
    print(f"Exit distribution : {exit_distrib}")
    print()
    print(f"=== Sample 5 events ===")
    for e in events[:5]:
        print(f"  {e['file'][:20]} bar={e['bar_idx']} entry={e['entry']} "
              f"score={e['score']} reasons={e['reasons']} "
              f"-> {e['exit_reason']} pnl={e['pnl_ticks']:.1f}t in {e['bars_held']}b")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
