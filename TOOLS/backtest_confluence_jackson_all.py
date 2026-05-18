"""Backtest CONFLUENCES GENERALES Jackson - DMP raw + V4 enriched.

Jackson 19/05 directive : "ON NE TESTE PAS JUSTE CETTE CONFLUENCE LA - CES UN TOUT
AVEC DIVERSE NIVEAU - MenthorQ + COLOR UP/DN + LONG UP/DN BAR + VWAP D/W/M +
NIVEAU MARKET PROFILE - ON DOIS TOUT LES TESTER".

Architecture :
1. Iter bars DMP raw NQ (14j dispo local)
2. Pour chaque bar, identifier TOUS les niveaux touched (proximity 20t = 5pts NQ)
3. Identifier TOUTES les confirmations actives (COLOR/LUB/LDB/EDGE/extensions)
4. Pour chaque combo (level, [confirmations]) : entry @ close, simulate exit
   TP=80t / SL=40t / timeout 30 bars LONG (direction = side du niveau)
5. Aggregate stats par combo : n, WR, PF, avg_pnl
6. Output top 20 combos par PF (n>=10 mini)

Direction par niveau (canonique) :
- Supports (touche en bas, side=LONG) : MQ_PUT_0DTE, MQ_PUT, GEX_DN, 1D_MIN,
  PVAL, PDL, CUR_VAL, OVN_LOW, ASIA_LOW, LONDON_LOW, vwap_d_sd1d, vwap_d_sd2d, ...
- Resistances (touche en haut, side=SHORT) : MQ_CALL_0DTE, MQ_CALL, GEX_UP, 1D_MAX,
  PVAH, PDH, CUR_VAH, OVN_HIGH, ASIA_HIGH, LONDON_HIGH, vwap_d_sd1u, vwap_d_sd2u, ...
- Structurels (REJECTION dynamique) : VPOC, single_print, naked_poc, spike_origin, ...

Convention DMP raw : `dist_*` en TICKS bruts (1 tick NQ = 0.25 = $0.50/micro)

Usage : python -X utf8 tools/backtest_confluence_jackson_all.py [--source DMP|V4]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from glob import glob
from pathlib import Path

# ─── CONFIG ─────────────────────────────────────────────────────
PROXIMITY_TICKS = 20  # touche niveau : <= 20 ticks NQ (5 pts)
TP_TICKS = 80         # +80t = TP
SL_TICKS = 40         # -40t = SL
MAX_BARS = 30
TICK_SIZE = 0.25
MIN_N_PER_COMBO = 5   # discarder combos n<5

# ─── NIVEAUX par direction ───────────────────────────────────────
# Format : (level_name, dist_field, side_canonical)
# side_canonical : "LONG"=touche support (rebond), "SHORT"=touche resistance (rejet)
LEVELS = [
    # MenthorQ Options
    ("MQ_PUT_0DTE", "dist_mq_put_0dte", "LONG"),
    ("MQ_PUT", "dist_mq_put", "LONG"),
    ("MQ_HVL_0DTE", "dist_mq_hvl_0dte", "REJECTION"),  # pivot
    ("MQ_HVL", "dist_mq_hvl", "REJECTION"),
    ("MQ_CALL_0DTE", "dist_mq_call_0dte", "SHORT"),
    ("MQ_CALL", "dist_mq_call", "SHORT"),
    ("MQ_1D_MIN", "dist_1d_min_ticks", "LONG"),
    ("MQ_1D_MAX", "dist_1d_max_ticks", "SHORT"),
    ("GEX_DN", "dist_gex_nearest_dn", "LONG"),
    ("GEX_UP", "dist_gex_nearest_up", "SHORT"),
    # Market Profile jour
    ("CUR_VPOC", "dist_cur_vpoc", "REJECTION"),
    ("CUR_VAH", "dist_cur_vah", "SHORT"),
    ("CUR_VAL", "dist_cur_val", "LONG"),
    # Niveaux veille
    ("PVPOC", "dist_prev_vpoc", "REJECTION"),
    ("PVAH", "dist_prev_vah", "SHORT"),
    ("PVAL", "dist_prev_val", "LONG"),
    ("PDH", "dist_pdh_pct", "SHORT"),
    ("PDL", "dist_pdl_pct", "LONG"),
    # Sessions
    ("OVN_HIGH", "dist_ovn_high", "SHORT"),
    ("OVN_LOW", "dist_ovn_low", "LONG"),
    ("ASIA_HIGH", "dist_asia_high_pct", "SHORT"),
    ("ASIA_LOW", "dist_asia_low_pct", "LONG"),
    ("LONDON_HIGH", "dist_london_high_pct", "SHORT"),
    ("LONDON_LOW", "dist_london_low_pct", "LONG"),
    ("CASH_HIGH", "dist_cash_high_pct", "SHORT"),
    ("CASH_LOW", "dist_cash_low_pct", "LONG"),
    ("OPEN_830", "dist_open_830", "REJECTION"),
    ("OPEN_CASH", "dist_open_cash", "REJECTION"),
    # IB
    ("IB_HIGH", "dist_ib_high", "SHORT"),
    ("IB_LOW", "dist_ib_low", "LONG"),
    # Structure
    ("VPOC_PREV_VWAP", "dist_prev_vwap", "REJECTION"),
]


def list_active_confirmations(bar: dict) -> list[str]:
    """Confirmations Jackson - VERSION SAFE NO LOOK-AHEAD (fix 19/05 03h30).

    EXCLU :
    - `*_fwd1` : look-ahead direct (la PROCHAINE bar)
    - `n_*_zones_active` : zones BN sont Sierra Extension Lines qui persistent
      du past vers le future = peut implicitement contenir info future
    - `dist_*_nearest_pct` : distance a zone, idem peut etre biaisee si zone
      cree future-pointing extension
    - `n_*_cluster_within_*` : agregation locale qui peut inclure future bars

    GARDE (BAR-LEVEL RAW FLAGS, strictement bar courante) :
    - `bn_absorb_*` : absorption detectee sur la bar courante (volume profile)
    - `bn_trapped_*_raw` : trapped traders trigger sur la bar (instantane)
    - `bn_trapped_*_at_resistance/support` : trapped + niveau touched (instantane)
    - `bn_stack_*` : iceberg stacking sur la bar (DOM snapshot)
    - `delta_div_buy/sell` : divergence delta detectee sur la bar
    - `delta_div_buy_clean / sell_clean` : variants nettoyes
    - `bar_edge_buy_fire / sell_fire` : edge zone fire flag (probablement bar-level)
    - `rvol_absorb_buy/sell` : absorption volume relatif (volume profile bar)

    Note : ces features sont calculees a partir des trades DE LA BAR COURANTE
    (volume profile, DOM, delta intra-bar). Pas de look-ahead structurel.
    """
    confs = []
    # ABSORB (bar-level, volume profile current bar)
    if bar.get("bn_absorb_bid") == 1:
        confs.append("ABSORB_BID")
    if bar.get("bn_absorb_ask") == 1:
        confs.append("ABSORB_ASK")
    if bar.get("bn_absorb_bid_at_level") == 1:
        confs.append("ABSORB_BID_AT_LEVEL")
    if bar.get("bn_absorb_ask_at_level") == 1:
        confs.append("ABSORB_ASK_AT_LEVEL")
    if bar.get("rvol_absorb_buy") == 1:
        confs.append("RVOL_ABSORB_BUY")
    if bar.get("rvol_absorb_sell") == 1:
        confs.append("RVOL_ABSORB_SELL")
    # TRAPPED (bar-level instant flags)
    if bar.get("bn_trapped_sellers_raw") == 1:
        confs.append("TRAPPED_SELLERS")
    if bar.get("bn_trapped_buyers_raw") == 1:
        confs.append("TRAPPED_BUYERS")
    if bar.get("bn_trapped_buyers_at_resistance") == 1:
        confs.append("TRAPPED_BUYERS_AT_RES")
    if bar.get("bn_trapped_sellers_at_support") == 1:
        confs.append("TRAPPED_SELLERS_AT_SUP")
    # STACK (DOM bar-level snapshot)
    if bar.get("bn_stack_ask") == 1:
        confs.append("STACK_ASK")
    if bar.get("bn_stack_bid") == 1:
        confs.append("STACK_BID")
    # DELTA DIV (intra-bar delta computation)
    if bar.get("delta_div_buy") == 1:
        confs.append("DELTA_DIV_BUY")
    if bar.get("delta_div_sell") == 1:
        confs.append("DELTA_DIV_SELL")
    if bar.get("delta_div_buy_clean") == 1:
        confs.append("DELTA_DIV_BUY_CLEAN")
    if bar.get("delta_div_sell_clean") == 1:
        confs.append("DELTA_DIV_SELL_CLEAN")
    # EDGE fire (bar-level trigger, a verifier pas de look-ahead)
    if bar.get("bar_edge_buy_fire") == 1:
        confs.append("EDGE_BUY_fire")
    if bar.get("bar_edge_sell_fire") == 1:
        confs.append("EDGE_SELL_fire")
    return confs


def detect_touched_levels(bar: dict) -> list[tuple[str, str, float]]:
    """Returns (level_name, side, dist) for each level touched (proximity)."""
    touched = []
    for name, field, side in LEVELS:
        d = bar.get(field)
        if d is None:
            continue
        # DMP raw: dist en ticks; V4 enriched: dist en pct ; check field name
        if "pct" in field:
            # pct - proximity 0.05% ~ 14 ticks NQ at 28000
            if abs(d) <= 0.05:
                touched.append((name, side, d))
        else:
            # ticks
            if abs(d) <= PROXIMITY_TICKS:
                touched.append((name, side, d))
    return touched


def simulate_exit(bars: list[dict], entry_idx: int, entry_price: float, direction: str) -> tuple[str, float]:
    """Simule TP/SL/timeout. direction in {LONG, SHORT}. Returns (reason, pnl_ticks)."""
    if direction == "LONG":
        tp_price = entry_price + TP_TICKS * TICK_SIZE
        sl_price = entry_price - SL_TICKS * TICK_SIZE
    else:
        tp_price = entry_price - TP_TICKS * TICK_SIZE
        sl_price = entry_price + SL_TICKS * TICK_SIZE
    for j in range(entry_idx + 1, min(entry_idx + 1 + MAX_BARS, len(bars))):
        b = bars[j]
        high = b.get("high") or b.get("bar_high")
        low = b.get("low") or b.get("bar_low")
        if high is None or low is None:
            continue
        if direction == "LONG":
            if high >= tp_price:
                return ("TP", TP_TICKS)
            if low <= sl_price:
                return ("SL", -SL_TICKS)
        else:
            if low <= tp_price:
                return ("TP", TP_TICKS)
            if high >= sl_price:
                return ("SL", -SL_TICKS)
    # Timeout
    last = bars[min(entry_idx + MAX_BARS, len(bars) - 1)]
    last_close = last.get("close") or last.get("price") or last.get("bar_close") or entry_price
    if direction == "LONG":
        return ("TIMEOUT", (last_close - entry_price) / TICK_SIZE)
    else:
        return ("TIMEOUT", (entry_price - last_close) / TICK_SIZE)


def run_backtest(files: list[str], symbol: str, label: str) -> dict:
    """Run backtest on list of files. Returns aggregated stats."""
    print(f"\n{'=' * 78}")
    print(f"BACKTEST {label} - {symbol} ({len(files)} files)")
    print(f"{'=' * 78}")

    # combos[(level, frozenset(confs))] = list of pnl_ticks
    combos = defaultdict(list)
    level_only_stats = defaultdict(list)
    confs_only_stats = defaultdict(list)
    n_bars_total = 0
    n_touched_any = 0

    for path in files:
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
            touched = detect_touched_levels(bar)
            if not touched:
                continue
            n_touched_any += 1
            entry_price = bar.get("close") or bar.get("price") or bar.get("bar_close")
            if entry_price is None:
                continue
            confs = list_active_confirmations(bar)
            for (lvl_name, side, dist) in touched:
                # Direction trade : LONG si support, SHORT si resistance, REJECTION dynamique
                if side == "LONG":
                    direction = "LONG"
                elif side == "SHORT":
                    direction = "SHORT"
                else:  # REJECTION : si dist < 0 (level under price), bounce LONG; else SHORT
                    direction = "LONG" if dist < 0 else "SHORT"
                exit_reason, pnl = simulate_exit(bars, i, entry_price, direction)
                # Aggregate level only
                level_only_stats[(lvl_name, direction)].append(pnl)
                # Aggregate each conf alone with this level
                for c in confs:
                    combos[(lvl_name, direction, c)].append(pnl)
                # Aggregate confluence (level + all confs)
                if confs:
                    combos[(lvl_name, direction, frozenset(confs))].append(pnl)
                # Track confs only
                for c in confs:
                    confs_only_stats[(c, direction)].append(pnl)

    print(f"Bars total : {n_bars_total}")
    print(f"Bars touched any level : {n_touched_any}")

    def fmt(name: str, pnls: list[float]) -> tuple[str, dict]:
        if not pnls:
            return None, None
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        n = len(pnls)
        wr = len(wins) / n * 100
        gw = sum(wins)
        gl = abs(sum(losses)) or 1
        pf = gw / gl
        avg = sum(pnls) / n
        return f"{name:50s} n={n:4d}  WR={wr:5.1f}%  PF={pf:5.2f}  avg={avg:+6.1f}t", {
            "name": name, "n": n, "WR": wr, "PF": pf, "avg": avg, "pnl_total": sum(pnls),
        }

    # Top 15 baseline level-only par PF (n>=10)
    print(f"\n--- TOP 15 baseline (level seul, direction canonique, n>=10) ---")
    level_stats = []
    for (lvl, dir_), pnls in level_only_stats.items():
        if len(pnls) < 10:
            continue
        s, d = fmt(f"{lvl}_{dir_}", pnls)
        if s:
            level_stats.append((s, d))
    level_stats.sort(key=lambda x: -x[1]["PF"])
    for s, _ in level_stats[:15]:
        print(f"  {s}")

    # Top 20 combos (level + confluence) par PF (n>=5)
    print(f"\n--- TOP 20 confluences (level + confs, n>={MIN_N_PER_COMBO}) ---")
    combo_stats = []
    for key, pnls in combos.items():
        if len(pnls) < MIN_N_PER_COMBO:
            continue
        if len(key) == 3 and isinstance(key[2], frozenset):
            label = f"{key[0]}_{key[1]}+CONFS({','.join(sorted(key[2]))[:60]})"
        else:
            label = f"{key[0]}_{key[1]}+{key[2]}"
        s, d = fmt(label, pnls)
        if s:
            combo_stats.append((s, d))
    combo_stats.sort(key=lambda x: -x[1]["PF"])
    for s, _ in combo_stats[:20]:
        print(f"  {s}")

    # Top 10 confs alone (= direction canonique impose par confluence implicite)
    print(f"\n--- TOP 10 confirmations seules (toutes directions, n>=10) ---")
    conf_stats = []
    for (c, dir_), pnls in confs_only_stats.items():
        if len(pnls) < 10:
            continue
        s, d = fmt(f"{c}_{dir_}", pnls)
        if s:
            conf_stats.append((s, d))
    conf_stats.sort(key=lambda x: -x[1]["PF"])
    for s, _ in conf_stats[:10]:
        print(f"  {s}")

    return {"levels": level_stats, "combos": combo_stats, "confs": conf_stats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["DMP", "V4", "BOTH"], default="BOTH")
    args = ap.parse_args()

    if args.source in ("DMP", "BOTH"):
        files = sorted(glob("DATA/NQ/2026*_NQ.jsonl"))
        files = [f for f in files if "PRE_FIX" not in f and "fresh" not in f and "v2" not in f]
        run_backtest(files, "NQ", "DMP raw Sierra Chart")

    if args.source in ("V4", "BOTH"):
        v4_path = "DATA/V4_TEMP/NQ_5months_combined.parquet"
        if not Path(v4_path).exists():
            print(f"\nV4 enriched absent : {v4_path}")
        else:
            # V4 c'est parquet, on convertit en list de dicts
            import pandas as pd
            df = pd.read_parquet(v4_path)
            tmp_jsonl = "DATA/V4_TEMP/_NQ_v4_for_backtest.jsonl"
            df.to_json(tmp_jsonl, orient="records", lines=True)
            run_backtest([tmp_jsonl], "NQ", "V4 enriched 5 mois")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
