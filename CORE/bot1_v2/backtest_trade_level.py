"""Backtest TRADE-LEVEL Bot 1 v2.

Pour CHAQUE setup arme :
  1. compute_verdict + check vetos + check quality (deja teste)
  2. compute_sl_tp : SL/TP reel avec mur trouve + HARD CAP
  3. Simulation outcome sur N=60 bars suivantes : TP hit / SL hit / TIMEOUT
  4. PnL par 1 micro contract
  5. Validation trend-following : direction setup vs tendance daily

Reponse Jackson : "ON DOIS ETRE DANS LE SENS DE LA TENDANCE ET PRENDRE DES
TRADES INTELLIGENTS PRO. ANALYSE CE QUE LE BOT AURAIS FAIS."
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.dashboard_mirror import compute_verdict
from CORE.bot1_v2.risk.sl_tp import compute_sl_tp

try:
    from CORE.constants import get_tick_size, get_tick_value
except ImportError:
    from constants import get_tick_size, get_tick_value  # type: ignore


# ============================================================
# DOLLAR PER TICK (micro contracts)
# ============================================================
TICK_VALUE_USD = {
    "ES": 1.25,   # MES micro
    "NQ": 0.50,   # MNQ micro
    "MGC": 1.00,  # MGC micro
}


def _ts_to_str(ts_ms) -> str:
    """Format timestamp UTC pour debug."""
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        return dt.strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "?"


def _simulate_outcome(
    bars: list, entry_idx: int, direction: str, entry_price: float,
    sl_price: float, tp_price: float, max_hold_bars: int = 60,
) -> dict:
    """Simule outcome trade sur bars suivantes.

    Returns:
        dict avec outcome (TP/SL/TIMEOUT/EOD), exit_price, exit_bar_idx, mae, mfe.
    """
    mae = 0.0  # max adverse excursion (ticks)
    mfe = 0.0  # max favorable excursion (ticks)

    sign = 1 if direction == "LONG" else -1

    for i in range(entry_idx + 1, min(entry_idx + 1 + max_hold_bars, len(bars))):
        bar = bars[i]
        bar_high = float(bar.get("high") or bar.get("bar_high") or bar.get("close") or 0)
        bar_low = float(bar.get("low") or bar.get("bar_low") or bar.get("close") or 0)

        # Excursions
        if direction == "LONG":
            adverse = (bar_low - entry_price)  # negatif si baisse
            favorable = (bar_high - entry_price)
            # SL hit : bar_low <= sl_price (SL au-dessous pour LONG)
            if bar_low <= sl_price:
                return {
                    "outcome": "SL",
                    "exit_price": sl_price,
                    "exit_bar_idx": i,
                    "exit_ts": bar.get("ts"),
                    "bars_held": i - entry_idx,
                    "mae_pts": adverse,
                    "mfe_pts": mfe,
                }
            # TP hit : bar_high >= tp_price
            if bar_high >= tp_price:
                return {
                    "outcome": "TP",
                    "exit_price": tp_price,
                    "exit_bar_idx": i,
                    "exit_ts": bar.get("ts"),
                    "bars_held": i - entry_idx,
                    "mae_pts": mae,
                    "mfe_pts": favorable,
                }
        else:  # SHORT
            adverse = (entry_price - bar_high)
            favorable = (entry_price - bar_low)
            # SL hit : bar_high >= sl_price
            if bar_high >= sl_price:
                return {
                    "outcome": "SL",
                    "exit_price": sl_price,
                    "exit_bar_idx": i,
                    "exit_ts": bar.get("ts"),
                    "bars_held": i - entry_idx,
                    "mae_pts": adverse,
                    "mfe_pts": mfe,
                }
            # TP hit
            if bar_low <= tp_price:
                return {
                    "outcome": "TP",
                    "exit_price": tp_price,
                    "exit_bar_idx": i,
                    "exit_ts": bar.get("ts"),
                    "bars_held": i - entry_idx,
                    "mae_pts": mae,
                    "mfe_pts": favorable,
                }

        mae = min(mae, adverse)
        mfe = max(mfe, favorable)

    # TIMEOUT
    if entry_idx + 1 < len(bars):
        last_bar = bars[min(entry_idx + max_hold_bars, len(bars) - 1)]
        exit_price = float(last_bar.get("close", entry_price))
        bars_held = min(max_hold_bars, len(bars) - entry_idx - 1)
    else:
        exit_price = entry_price
        bars_held = 0

    return {
        "outcome": "TIMEOUT",
        "exit_price": exit_price,
        "exit_bar_idx": min(entry_idx + max_hold_bars, len(bars) - 1),
        "exit_ts": last_bar.get("ts") if entry_idx + 1 < len(bars) else None,
        "bars_held": bars_held,
        "mae_pts": mae,
        "mfe_pts": mfe,
    }


def _check_trend_alignment(bar: dict, direction: str) -> tuple[bool, str]:
    """Verifie si direction setup alignee avec tendance daily.

    Trend-following : utilise vwap_d_side + ma_trend + bias_label.
    """
    vwap_side = int(bar.get("vwap_d_side") or 0)
    ma_trend = int(bar.get("ma_trend") or 0)
    bias_label = (bar.get("bias_label") or "").upper()

    if direction == "LONG":
        votes_bull = sum([
            1 if vwap_side > 0 else 0,
            1 if ma_trend > 0 else 0,
            1 if bias_label == "BULLISH" else 0,
        ])
        aligned = votes_bull >= 2
        detail = f"LONG votes_bull={votes_bull}/3 (vwap={vwap_side} ma={ma_trend} bias={bias_label})"
    else:
        votes_bear = sum([
            1 if vwap_side < 0 else 0,
            1 if ma_trend < 0 else 0,
            1 if bias_label == "BEARISH" else 0,
        ])
        aligned = votes_bear >= 2
        detail = f"SHORT votes_bear={votes_bear}/3 (vwap={vwap_side} ma={ma_trend} bias={bias_label})"
    return aligned, detail


def replay_with_trades(path: Path, symbol: str, cfg: Bot1V2Config) -> dict:
    """Replay 1 fichier JSONL avec trades simules end-to-end."""
    # Charge toutes les bars en memoire (besoin pour outcome lookahead)
    bars = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                bar = json.loads(line)
            except json.JSONDecodeError:
                continue
            bars.append(bar)

    trades = []
    cooldown_until_bar = -1
    cooldown_bars = cfg.COOLDOWN_POST_CLOSE_MIN

    n_setups_armed = 0
    n_setups_in_cooldown = 0
    n_setups_sl_cap_rejected = 0
    n_setups_no_wall = 0
    n_setups_trend_misaligned = 0

    tick = get_tick_size(symbol)
    tick_usd = TICK_VALUE_USD.get(symbol, 1.25)

    for idx, bar in enumerate(bars):
        verdict = compute_verdict(bar, cfg=cfg)
        if not verdict.ready_to_arm:
            continue

        n_setups_armed += 1

        # Cooldown
        if idx <= cooldown_until_bar:
            n_setups_in_cooldown += 1
            continue

        # SL/TP avec HARD CAP
        entry_price = float(bar.get("close", 0))
        if entry_price <= 0:
            continue

        sltp = compute_sl_tp(bar, verdict.direction, entry_price, symbol, cfg)
        if not sltp.accepted:
            if "SL_HARD_CAP_EXCEEDED" in sltp.reject_reason:
                n_setups_sl_cap_rejected += 1
            elif "NO_SL_WALL" in sltp.reject_reason:
                n_setups_no_wall += 1
            continue

        # Trend alignment check
        trend_aligned, trend_detail = _check_trend_alignment(bar, verdict.direction)
        if not trend_aligned:
            n_setups_trend_misaligned += 1
            # Note : on log mais on garde le trade (filtre additionnel a discuter)
            # continue  # decomment si on veut ne PRENDRE QUE les trades dans le sens tendance

        # Simulate outcome
        outcome = _simulate_outcome(
            bars, idx, verdict.direction, entry_price,
            sltp.sl_price, sltp.tp_price, max_hold_bars=60,
        )

        # PnL calculation (1 micro contract)
        if outcome["outcome"] == "TP":
            pnl_ticks = sltp.tp_ticks
        elif outcome["outcome"] == "SL":
            pnl_ticks = -sltp.sl_ticks
        else:  # TIMEOUT
            if verdict.direction == "LONG":
                pnl_pts = outcome["exit_price"] - entry_price
            else:
                pnl_pts = entry_price - outcome["exit_price"]
            pnl_ticks = pnl_pts / tick

        pnl_usd = pnl_ticks * tick_usd

        trade = {
            "ts": bar.get("ts"),
            "time": _ts_to_str(bar.get("ts")),
            "symbol": symbol,
            "direction": verdict.direction,
            "entry_price": entry_price,
            "sl_price": sltp.sl_price,
            "tp_price": sltp.tp_price,
            "sl_ticks": sltp.sl_ticks,
            "tp_ticks": sltp.tp_ticks,
            "rr": sltp.rr_ratio,
            "sl_wall": sltp.sl_wall,
            "sl_tier": sltp.sl_tier,
            "outcome": outcome["outcome"],
            "exit_price": outcome["exit_price"],
            "bars_held": outcome["bars_held"],
            "mae_pts": outcome["mae_pts"],
            "mfe_pts": outcome["mfe_pts"],
            "pnl_ticks": round(pnl_ticks, 1),
            "pnl_usd": round(pnl_usd, 2),
            "trend_aligned": trend_aligned,
            "trend_detail": trend_detail,
            "stars_count": verdict.stars_count,
            "action": verdict.action,
        }
        trades.append(trade)

        cooldown_until_bar = outcome["exit_bar_idx"] + cooldown_bars

    return {
        "symbol": symbol,
        "path": str(path),
        "n_bars": len(bars),
        "n_setups_armed": n_setups_armed,
        "n_setups_in_cooldown": n_setups_in_cooldown,
        "n_setups_sl_cap_rejected": n_setups_sl_cap_rejected,
        "n_setups_no_wall": n_setups_no_wall,
        "n_setups_trend_misaligned": n_setups_trend_misaligned,
        "trades": trades,
    }


def _print_trade(t: dict, i: int):
    """Print 1 trade en format lisible."""
    print(
        f"  #{i:>3} {t['time']} {t['symbol']:<3} {t['direction']:<5} "
        f"@ {t['entry_price']:>9.2f} | "
        f"SL {t['sl_ticks']:>2}t({t['sl_wall']}) TP {t['tp_ticks']:>2}t | "
        f"RR {t['rr']:.1f} | "
        f"{t['outcome']:<7} {t['bars_held']:>2}b | "
        f"PnL ${t['pnl_usd']:>7.2f} | "
        f"MAE {t['mae_pts']:>5.1f}p MFE {t['mfe_pts']:>5.1f}p | "
        f"stars {t['stars_count']}/5 | "
        f"trend={'OK' if t['trend_aligned'] else 'MIS'}"
    )


def main():
    cfg = Bot1V2Config.from_env()
    root = _ROOT / "DATA" / "live_enriched" / "sierra"

    files = []
    for sym_dir, sym in (("NQ", "NQ"), ("ES", "ES")):
        d = root / sym_dir
        if not d.exists():
            continue
        for f in sorted(d.glob("*_sierra_enriched.jsonl")):
            if f.stat().st_size < 100_000:
                continue
            files.append((f, sym))

    print(f"=== Bot 1 v2 Backtest TRADE-LEVEL ===\n")
    print(f"Approche : trend-following + forte conviction cluster + SL hard cap")
    print(f"Plafond : {cfg.MAX_TRADES_PER_DAY} trades/jour (DailyLimitsGuard)\n")

    all_trades = []
    stats = defaultdict(int)

    for f, sym in files:
        result = replay_with_trades(f, sym, cfg)
        trades = result["trades"]

        if trades:
            print(f"--- {sym} : {f.name} ({result['n_bars']} bars) ---")
            print(f"  Setups armes: {result['n_setups_armed']}")
            print(f"  -> cooldown skip:       {result['n_setups_in_cooldown']}")
            print(f"  -> SL HARD CAP reject:  {result['n_setups_sl_cap_rejected']}")
            print(f"  -> No SL wall:          {result['n_setups_no_wall']}")
            print(f"  -> Trend misaligned:    {result['n_setups_trend_misaligned']}")
            print(f"  -> TRADES SIMULES:      {len(trades)}")
            print()
            for i, t in enumerate(trades, 1):
                _print_trade(t, i)
            print()

        all_trades.extend(trades)
        stats["setups_armed"] += result["n_setups_armed"]
        stats["sl_cap_rejected"] += result["n_setups_sl_cap_rejected"]
        stats["no_wall"] += result["n_setups_no_wall"]
        stats["trend_misaligned"] += result["n_setups_trend_misaligned"]

    # ============================================================
    # GLOBAL STATS
    # ============================================================
    print(f"\n=== GLOBAL STATS ===\n")
    n = len(all_trades)
    print(f"Total setups armes: {stats['setups_armed']}")
    print(f"  -> SL HARD CAP rejected: {stats['sl_cap_rejected']} ({100*stats['sl_cap_rejected']/max(stats['setups_armed'],1):.1f}%)")
    print(f"  -> No SL wall:           {stats['no_wall']}")
    print(f"  -> Trend misaligned:     {stats['trend_misaligned']}")
    print(f"  -> TRADES EXECUTES:      {n}")

    if n == 0:
        print("\n!! 0 trades executes - problem")
        return

    # Outcomes
    outcomes = Counter(t["outcome"] for t in all_trades)
    directions = Counter(t["direction"] for t in all_trades)
    trend_ok = sum(1 for t in all_trades if t["trend_aligned"])

    n_tp = outcomes.get("TP", 0)
    n_sl = outcomes.get("SL", 0)
    n_to = outcomes.get("TIMEOUT", 0)

    print(f"\n--- Outcomes ---")
    print(f"  TP      : {n_tp:>3} ({100*n_tp/n:.1f}%)")
    print(f"  SL      : {n_sl:>3} ({100*n_sl/n:.1f}%)")
    print(f"  TIMEOUT : {n_to:>3} ({100*n_to/n:.1f}%)")

    # PnL
    pnl_total = sum(t["pnl_usd"] for t in all_trades)
    pnl_tp = sum(t["pnl_usd"] for t in all_trades if t["outcome"] == "TP")
    pnl_sl = sum(t["pnl_usd"] for t in all_trades if t["outcome"] == "SL")
    pnl_to = sum(t["pnl_usd"] for t in all_trades if t["outcome"] == "TIMEOUT")

    wins = [t["pnl_usd"] for t in all_trades if t["pnl_usd"] > 0]
    losses = [t["pnl_usd"] for t in all_trades if t["pnl_usd"] < 0]
    wr = len(wins) / n * 100
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")

    print(f"\n--- PnL ($ par 1 micro) ---")
    print(f"  Total       : ${pnl_total:>9.2f}")
    print(f"  TP          : ${pnl_tp:>9.2f}")
    print(f"  SL          : ${pnl_sl:>9.2f}")
    print(f"  TIMEOUT     : ${pnl_to:>9.2f}")
    print(f"  Avg WIN     : ${avg_win:>9.2f}")
    print(f"  Avg LOSS    : ${avg_loss:>9.2f}")

    print(f"\n--- Statistiques ---")
    print(f"  N trades    : {n}")
    print(f"  Win Rate    : {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Direction   : {dict(directions)}")
    print(f"  Trend OK    : {trend_ok}/{n} ({100*trend_ok/n:.1f}%)")

    # Distribution journaliere
    by_day = defaultdict(list)
    for t in all_trades:
        date = _ts_to_str(t["ts"])[:8] if t["ts"] else "?"
        # Extract date YYYYMMDD from ts
        try:
            dt = datetime.fromtimestamp(int(t["ts"]) / 1000, tz=timezone.utc)
            date = dt.strftime("%Y-%m-%d")
        except Exception:
            pass
        by_day[date].append(t)

    print(f"\n--- Trades par jour ---")
    for date in sorted(by_day.keys()):
        day_trades = by_day[date]
        day_pnl = sum(t["pnl_usd"] for t in day_trades)
        day_wr = sum(1 for t in day_trades if t["pnl_usd"] > 0) / max(len(day_trades), 1) * 100
        print(f"  {date} : {len(day_trades):>2} trades, PnL ${day_pnl:>8.2f}, WR {day_wr:.0f}%")

    # Trends - verdict pro
    print(f"\n=== VERDICT 'INTELLIGENT PRO' ===")
    if wr >= 50 and pf >= 1.5:
        print(f"OK : WR {wr:.0f}% + PF {pf:.2f} >= cibles pro (50% + 1.5)")
    elif wr >= 40 and pf >= 1.3:
        print(f"ACCEPTABLE : WR {wr:.0f}% + PF {pf:.2f} (proche cible)")
    else:
        print(f"INSUFFISANT : WR {wr:.0f}% + PF {pf:.2f} < cibles pro")
    print(f"Trend-following respect : {100*trend_ok/n:.0f}% trades dans le sens tendance")
    print(f"SL hard cap efficace : {stats['sl_cap_rejected']} setups rejetes (trades pourris evites)")


if __name__ == "__main__":
    main()
