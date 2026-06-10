"""
backtest_shadow_trailing.py v2 — Audit empirique trailing stop (POST review code-reviewer)

Date : 2026-04-30 (Jackson "fais un backtest sur plusieurs jours")
Question : sur les trades historiques reels, un trailing stop aurait-il ameliore le PnL ?

5 fixes appliques apres review code-reviewer (NOGO sur v1) :
1. Source bars = JSONL DMP brut (DATA/ES, DATA/NQ) au lieu de snapshots paper trader
   → couverture passe de ~2 bars/trade a 100% (1378 bars/jour ES disponibles)
2. ATR depuis `atr_14m` (champ JSONL en TICKS, variable bar-by-bar) au lieu de
   fallback constant qui sous-estimait NQ de 49% (30t fallback vs 45t reel)
3. Tie-break intra-bar : si bar touche SL_armed ET TP, run DUAL (optimistic =
   TP first, pessimistic = SL first). Borne le PnL au lieu de prétendre.
4. `bar_ts < t_exit` strict (exclut la bar de sortie reelle pour eviter
   double-comptage de l'event de sortie)
5. Output separe ES vs NQ (ATR/tick value differents) + bootstrap CI 1000 resamples
   sur le delta PnL pour test de significativite

Methodologie :
- 4 strategies simulees (REAL = reference, BE_AT_1R, STEP_TRAIL, ATR_TRAIL_2.5)
- Pour chaque trade cloture, replay bar-by-bar JSONL DMP entre entry_time et exit_time
- Hypothese intra-bar : run optimistic (TP first if both touched) + pessimistic
  (SL first). Delta reporte avec borne min/max.
- Pas de slippage simule (cost neutral, on compare des deltas).

Usage :
    python -X utf8 CORE/research/backtest_shadow_trailing.py
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PAPER_DIR = Path("d:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")
ES_DIR = Path("d:/TRADING_SIERRA_CHART_AUTO/DATA/ES")
NQ_DIR = Path("d:/TRADING_SIERRA_CHART_AUTO/DATA/NQ")

TICK = {"ES": 0.25, "NQ": 0.25}
TICK_VAL = {"ES": 1.25, "NQ": 0.50}


# ─── DATA LOADING ────────────────────────────────────────────────────


def load_trades(path: Path) -> List[dict]:
    trades = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            if t.get("sl_ticks") and t.get("entry_price") and t.get("exit_price"):
                trades.append(t)
    return trades


def load_dmp_bars(symbol: str, date_str: str) -> List[dict]:
    """Charge JSONL DMP brut (toutes les bars 1-min de la journee)."""
    if symbol == "ES":
        path = ES_DIR / f"{date_str}_ES.jsonl"
    else:
        path = NQ_DIR / f"{date_str}_NQ.jsonl"

    if not path.exists():
        return []

    bars = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                b = json.loads(line)
            except json.JSONDecodeError:
                continue
            if b.get("price") is None:
                continue
            ts_ms = b.get("ts")
            if not ts_ms:
                continue
            bars.append({
                "symbol": b.get("sym"),
                "ts_ms": ts_ms,
                "ts_dt": datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc),
                "close": b.get("price"),
                "bar_high": b.get("bar_high"),
                "bar_low": b.get("bar_low"),
                "atr_14m_ticks": b.get("atr_14m"),
            })
    bars.sort(key=lambda x: x["ts_ms"])
    return bars


def parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # Format ISO avec ou sans timezone
        if "+" in ts or "Z" in ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # Format snapshot "2026-04-30 01:21:00"
        dt = datetime.fromisoformat(ts.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_bars_in_window(bars: List[dict], t_entry: datetime,
                       t_exit: datetime) -> List[dict]:
    """Filtre bars STRICTEMENT entre entry_time et exit_time (exclusif sur exit
    pour eviter double-comptage de la bar de sortie reelle).

    NOTE : on inclut bar_ts >= t_entry (peut contenir la bar d'entree initiale
    qui contient deja l'evolution post-entree).
    """
    return [b for b in bars if t_entry <= b["ts_dt"] < t_exit]


# ─── INTRA-BAR SIMULATION (optimistic + pessimistic) ─────────────────


def _check_exit_intra_bar(direction: int, bh: float, bl: float,
                          sl_price: float, tp_price: float,
                          tk: float, entry: float,
                          mode: str) -> Optional[Tuple[float, str]]:
    """Verifie si SL ou TP est touche dans la bar.

    mode = 'optimistic' : si les 2 sont touches, retourne TP (favorable au trade)
    mode = 'pessimistic': si les 2 sont touches, retourne SL (defavorable)

    Retourne (pnl_ticks_per_contract, outcome_label) ou None si pas d'exit.
    """
    if direction == 1:  # LONG
        sl_hit = bl <= sl_price
        tp_hit = bh >= tp_price
        if sl_hit and tp_hit:
            if mode == "optimistic":
                return (tp_price - entry) / tk, "TP"
            else:
                return (sl_price - entry) / tk, "SL"
        if sl_hit:
            return (sl_price - entry) / tk, "SL"
        if tp_hit:
            return (tp_price - entry) / tk, "TP"
    else:  # SHORT
        sl_hit = bh >= sl_price
        tp_hit = bl <= tp_price
        if sl_hit and tp_hit:
            if mode == "optimistic":
                return (entry - tp_price) / tk, "TP"
            else:
                return (entry - sl_price) / tk, "SL"
        if sl_hit:
            return (entry - sl_price) / tk, "SL"
        if tp_hit:
            return (entry - tp_price) / tk, "TP"
    return None


# ─── TRAILING STRATEGIES ──────────────────────────────────────────────


def simulate_real(trade: dict) -> Tuple[float, str]:
    """REAL : ce qui s'est passe (PnL/contrat reel)."""
    pnl_total = trade["pnl_ticks"]
    n_micros = trade.get("n_micros") or 3
    return pnl_total / n_micros, trade.get("outcome") or trade.get("exit_reason") or "?"


def simulate_be_at_1r(trade: dict, bars: List[dict],
                      mode: str = "pessimistic") -> Tuple[float, str]:
    """BE_AT_1R : SL move a entry quand profit atteint 1R."""
    sym = trade["symbol"]
    direction = 1 if trade["direction"] == "LONG" else -1
    entry = trade["entry_price"]
    sl_ticks = trade["sl_ticks"]
    tp_ticks = trade["tp_ticks"]
    tk = TICK[sym]
    sl_price = entry - direction * sl_ticks * tk
    tp_price = entry + direction * tp_ticks * tk
    be_armed = False

    for b in bars:
        bh, bl = b["bar_high"], b["bar_low"]
        if bh is None or bl is None:
            continue
        # Update BE arm BEFORE checking exits
        if not be_armed:
            mfe_ticks = ((bh - entry) / tk) if direction == 1 else ((entry - bl) / tk)
            if mfe_ticks >= sl_ticks:
                be_armed = True
                sl_price = entry  # move SL to entry

        exit_res = _check_exit_intra_bar(direction, bh, bl, sl_price, tp_price,
                                          tk, entry, mode)
        if exit_res:
            pnl, outcome = exit_res
            label = outcome
            if be_armed and outcome == "SL":
                label = "BE_TOUCH"
            return pnl, label

    # End of bars : close at last price
    if bars:
        last = bars[-1]["close"]
        return ((last - entry) / tk * direction), "EOD"
    return simulate_real(trade)


def simulate_step_trail(trade: dict, bars: List[dict],
                        mode: str = "pessimistic") -> Tuple[float, str]:
    """STEP_TRAIL : BE @ 1R, +1R @ 2R, +2R @ 3R..."""
    sym = trade["symbol"]
    direction = 1 if trade["direction"] == "LONG" else -1
    entry = trade["entry_price"]
    sl_ticks = trade["sl_ticks"]
    tp_ticks = trade["tp_ticks"]
    tk = TICK[sym]
    initial_sl_price = entry - direction * sl_ticks * tk
    tp_price = entry + direction * tp_ticks * tk
    sl_price = initial_sl_price
    step_level = 0

    for b in bars:
        bh, bl = b["bar_high"], b["bar_low"]
        if bh is None or bl is None:
            continue
        mfe_ticks = ((bh - entry) / tk) if direction == 1 else ((entry - bl) / tk)
        new_level = int(mfe_ticks // sl_ticks)
        if new_level > step_level:
            step_level = new_level
            offset_R = max(0, step_level - 1)
            sl_price = entry + direction * offset_R * sl_ticks * tk

        exit_res = _check_exit_intra_bar(direction, bh, bl, sl_price, tp_price,
                                          tk, entry, mode)
        if exit_res:
            pnl, outcome = exit_res
            label = f"TRAIL_{step_level}R" if (step_level > 0 and outcome == "SL") else outcome
            return pnl, label

    if bars:
        last = bars[-1]["close"]
        return ((last - entry) / tk * direction), "EOD"
    return simulate_real(trade)


def simulate_atr_trail(trade: dict, bars: List[dict], k: float = 2.5,
                       mode: str = "pessimistic") -> Tuple[float, str]:
    """ATR_TRAIL : SL = max_high - k*ATR (LONG inverse SHORT). Arme apres 1R."""
    sym = trade["symbol"]
    direction = 1 if trade["direction"] == "LONG" else -1
    entry = trade["entry_price"]
    sl_ticks = trade["sl_ticks"]
    tp_ticks = trade["tp_ticks"]
    tk = TICK[sym]
    sl_price = entry - direction * sl_ticks * tk
    tp_price = entry + direction * tp_ticks * tk
    armed = False
    extreme = entry

    for b in bars:
        bh, bl = b["bar_high"], b["bar_low"]
        if bh is None or bl is None:
            continue
        if direction == 1:
            extreme = max(extreme, bh)
            mfe_ticks = (bh - entry) / tk
        else:
            extreme = min(extreme, bl)
            mfe_ticks = (entry - bl) / tk

        if not armed and mfe_ticks >= sl_ticks:
            armed = True

        if armed:
            atr_t = b.get("atr_14m_ticks")
            if atr_t is None or atr_t <= 0:
                # Fallback : pas de retrousser (skip update mais pas faussedone)
                pass
            else:
                offset = k * atr_t * tk
                new_sl = extreme - direction * offset
                # SL ne recule jamais (chandelier monotone)
                if direction == 1:
                    sl_price = max(sl_price, new_sl)
                else:
                    sl_price = min(sl_price, new_sl)

        exit_res = _check_exit_intra_bar(direction, bh, bl, sl_price, tp_price,
                                          tk, entry, mode)
        if exit_res:
            pnl, outcome = exit_res
            label = "ATR_TRAIL" if (armed and outcome == "SL") else outcome
            return pnl, label

    if bars:
        last = bars[-1]["close"]
        return ((last - entry) / tk * direction), "EOD"
    return simulate_real(trade)


# ─── BOOTSTRAP CI ─────────────────────────────────────────────────────


def bootstrap_ci_delta(deltas: List[float], n_resamples: int = 1000,
                        ci_pct: float = 95.0) -> Tuple[float, float, float]:
    """Bootstrap percentile CI sur le mean delta.

    Returns (mean, lo, hi). Si lo et hi sont du meme signe → significatif.
    """
    if not deltas:
        return 0.0, 0.0, 0.0
    n = len(deltas)
    means = []
    rng = random.Random(42)
    for _ in range(n_resamples):
        sample = [deltas[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (100 - ci_pct) / 200
    lo_idx = int(alpha * n_resamples)
    hi_idx = int((1 - alpha) * n_resamples) - 1
    return statistics.mean(means), means[lo_idx], means[hi_idx]


# ─── DRIVER ───────────────────────────────────────────────────────────


def run_day(trades_path: Path, date_str: str, label: str,
            modes: List[str] = ("optimistic", "pessimistic")) -> List[Dict]:
    """Run backtest pour un jour, separation par symbol + 2 modes intra-bar.

    Returns liste de trade results.
    """
    trades = load_trades(trades_path)
    bars_es = load_dmp_bars("ES", date_str)
    bars_nq = load_dmp_bars("NQ", date_str)
    print(f"\n=== {label} ({trades_path.name}) ===")
    print(f"  trades cloturees : {len(trades)}")
    print(f"  bars JSONL ES : {len(bars_es)} / NQ : {len(bars_nq)}")

    trade_results = []
    skipped = 0
    for t in trades:
        sym = t["symbol"]
        n_micros = t.get("n_micros") or 3
        t_entry = parse_iso(t["entry_time"])
        t_exit = parse_iso(t["exit_time"])
        if t_entry is None or t_exit is None:
            skipped += 1
            continue
        bars_all = bars_es if sym == "ES" else bars_nq
        bars = get_bars_in_window(bars_all, t_entry, t_exit)
        if len(bars) < 1:
            skipped += 1
            continue

        # Compute scenarios in both modes (optimistic + pessimistic)
        scenarios = {}
        scenarios["REAL"] = simulate_real(t)
        for mode in modes:
            scenarios[f"BE_AT_1R_{mode}"] = simulate_be_at_1r(t, bars, mode)
            scenarios[f"STEP_TRAIL_{mode}"] = simulate_step_trail(t, bars, mode)
            scenarios[f"ATR_TRAIL_2.5_{mode}"] = simulate_atr_trail(t, bars, k=2.5, mode=mode)

        trade_results.append({
            "symbol": sym,
            "n_micros": n_micros,
            "n_bars": len(bars),
            "scenarios": scenarios,
        })

    print(f"  trades eligibles backtest : {len(trade_results)} / skipped : {skipped}")
    print(f"  median bars/trade : {statistics.median([r['n_bars'] for r in trade_results]) if trade_results else 0:.0f}")
    return trade_results


def aggregate_and_report(all_trades: List[Dict]):
    """Agrege multi-jours, separe ES/NQ, bootstrap CI sur delta."""
    print("\n" + "=" * 90)
    print("SYNTHESE MULTI-JOURS — separation ES/NQ + intra-bar dual mode")
    print("=" * 90)

    by_symbol = defaultdict(list)
    for r in all_trades:
        by_symbol[r["symbol"]].append(r)

    if not by_symbol:
        print("AUCUN TRADE ELIGIBLE.")
        return

    for sym, trades in sorted(by_symbol.items()):
        print(f"\n--- {sym} ({len(trades)} trades) ---")
        if not trades:
            continue
        tv = TICK_VAL[sym]
        # Aggregate by strategy
        strats = list(trades[0]["scenarios"].keys())
        agg = {s: {"pnl_usd": 0.0, "wins": 0, "losses": 0, "n": 0,
                    "outcomes": defaultdict(int), "deltas": []}
               for s in strats}
        for r in trades:
            n = r["n_micros"]
            real_pnl = r["scenarios"]["REAL"][0] * tv * n
            for strat, (pnl_per_contract, outcome) in r["scenarios"].items():
                pnl_usd = pnl_per_contract * tv * n
                a = agg[strat]
                a["pnl_usd"] += pnl_usd
                a["n"] += 1
                a["outcomes"][outcome] += 1
                if pnl_per_contract > 0:
                    a["wins"] += 1
                elif pnl_per_contract < 0:
                    a["losses"] += 1
                if strat != "REAL":
                    a["deltas"].append(pnl_usd - real_pnl)

        # Print
        print(f"  {'Strategy':<28} {'PnL USD':>10} {'WR':>7} "
              f"{'delta_mean':>11} {'CI95 [lo, hi]':>26} {'sig':>5}")
        print("  " + "-" * 88)
        real_pnl = agg["REAL"]["pnl_usd"]
        for strat in strats:
            a = agg[strat]
            wr = (a["wins"] / max(1, a["wins"] + a["losses"])) * 100
            if strat == "REAL":
                print(f"  {strat:<28} ${a['pnl_usd']:>8.0f} {wr:>5.1f}%")
            else:
                mean, lo, hi = bootstrap_ci_delta(a["deltas"])
                sig = "[YES]" if (lo > 0 or hi < 0) else "[NO]"
                print(f"  {strat:<28} ${a['pnl_usd']:>8.0f} {wr:>5.1f}% "
                      f"${mean:>+9.1f} [${lo:>+7.1f}, ${hi:>+7.1f}] {sig}")

        # Outcomes for REAL only (le reste est trop verbeux)
        print(f"  REAL outcomes : {dict(agg['REAL']['outcomes'])}")

    print("\n" + "=" * 90)
    print("VERDICT (basé sur CI95 bootstrap 1000 resamples)")
    print("=" * 90)
    print("  [YES] = CI ne contient pas zero (delta significatif)")
    print("  [NO]  = CI contient zero (delta = bruit, pas de conclusion)")
    print()
    print("  Lecture : si OPTIMISTIC delta > 0 mais PESSIMISTIC delta <= 0,")
    print("  la conclusion depend de l'hypothese intra-bar → indeterminee.")
    print("  Si les 2 modes convergent → conclusion robuste.")


def main():
    days = [
        ("20260424_trades.jsonl", "20260424", "Bot1 24/04"),
        ("20260428_databento_trades.jsonl", "20260428", "Bot2 28/04"),
        ("20260429_databento_trades.jsonl", "20260429", "Bot2 29/04"),
        ("20260429_trades.jsonl", "20260429", "Bot1 29/04"),
        ("20260430_databento_trades.jsonl", "20260430", "Bot2 30/04"),
    ]
    all_trades = []
    for tf, date_str, label in days:
        tp = PAPER_DIR / tf
        if not tp.exists():
            print(f"[SKIP] {label} : trades file missing")
            continue
        all_trades.extend(run_day(tp, date_str, label))
    aggregate_and_report(all_trades)


if __name__ == "__main__":
    main()
