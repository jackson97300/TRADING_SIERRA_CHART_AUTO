"""SHADOW_FULL collector Bot 3 BN V4 — replay historique sierra_enriched.

PROPOSITION 2 audit ULTRATHINK 24/06 (trading-strategy-analyst) :
- Bot 3 BN V4 actuel : 0 trade en 7 jours (Grade A++ ultra-selectif)
- audit code-reviewer R2 BLOQUANT : `BOTBN_GRADE_MIN=A` data mining trap (n=12 << n=100 Lopez)
- Solution non-destructive : replay sierra_enriched historique avec GRADE_MIN relaxe
  pour collecter empiriquement N>=100 setups Grade A/B avant decision strategique

Methodologie :
1. Pour chaque jour de la fenetre, charge bars sierra_enriched
2. Cree SignalEngine instance avec cfg shadow (grade_min relaxe, both directions)
3. Loop bars : SignalEngine.on_bar() -> SignalDecision
4. Pour chaque setup detecte (tradable OR hypothetical) :
   - Cree TrailingManager
   - Simule entry au prix de la bar
   - Loop bars suivantes (max TIMEOUT_BARS) : trail.on_bar, detect SL hit
   - Calcul PnL_ticks, PnL_usd, MFE, MAE, duration
5. Append JSONL `LOGS/bot_bn_v4_shadow/shadow_{date}_{sym}.jsonl`

Usage :
    python -X utf8 -m CORE.bot_bn_v4.shadow_collector \
        --start-date 2026-06-16 --end-date 2026-06-24 \
        --symbols NQ,ES --grade-min B \
        --output-dir LOGS/bot_bn_v4_shadow

Output JSONL fields :
    signal_id, ts_event, sym, direction, grade, density, n_levels, regime, session
    entry_price, entry_bar_ts, sl_initial_price, sl_initial_ticks
    exit_reason (SL_HIT/TIMEOUT/EOD), exit_price, exit_bar_ts, duration_bars
    pnl_ticks, pnl_usd, mfe_ticks, mae_ticks
    setup_full (dict complet pour audit gates)

Permet ensuite analyse :
- PF par grade (A++/A/B/C) -> valider GRADE_MIN=A vs A++ avec n>=100
- DSR Lopez walk-forward 12-fold
- Distribution par session/regime
- Sans toucher au bot prod (zero risque)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

# Tick value per symbol pour PnL USD (E-mini standard, pas micro)
# Bot 3 BN V4 trade E-mini standard mais paper Sim3, alignement dashboard avec
# memoire feedback_dashboard_micro_eq.md (Bot 3 utilise micro equivalent)
TICK_VALUE_USD = {
    "NQ": 0.50,  # micro equivalent (memoire feedback_dashboard_micro_eq)
    "ES": 1.25,
    "MGC": 1.00,
}


@dataclass
class ShadowTrade:
    """Trade simule dans le shadow collector."""
    signal_id: str
    ts_event: str
    sym: str
    direction: str
    grade: str
    density: int
    n_levels: int
    session: str
    regime: str
    entry_price: float
    entry_bar_ts: int
    sl_initial_price: float
    sl_initial_ticks: float
    exit_reason: str = "OPEN"  # SL_HIT / TIMEOUT / EOD / NO_EXIT
    exit_price: float = 0.0
    exit_bar_ts: int = 0
    duration_bars: int = 0
    pnl_ticks: float = 0.0
    pnl_usd: float = 0.0
    mfe_ticks: float = 0.0
    mae_ticks: float = 0.0
    setup_full: dict = field(default_factory=dict)


def _iter_jsonl(path: Path) -> Iterator[dict]:
    """Iterate JSONL with corrupt-tolerant skip."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _list_dates(start: date, end: date) -> Iterator[date]:
    """Yield each date in [start, end] inclusive."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _load_bars_for_day(symbol: str, day: date, root: Path) -> list[dict]:
    """Load all sierra_enriched bars for a given day + symbol.

    File pattern : DATA/live_enriched/sierra/{SYM}/{YYYYMMDD}_{SYM}_sierra_enriched.jsonl
    """
    sym_dir = root / "DATA" / "live_enriched" / "sierra" / symbol.upper()
    fname = f"{day.strftime('%Y%m%d')}_{symbol.upper()}_sierra_enriched.jsonl"
    fpath = sym_dir / fname
    bars = list(_iter_jsonl(fpath))
    return bars


def _detect_sl_hit(bar: dict, direction: str, sl_price: float) -> bool:
    """True if bar's wick hit SL."""
    try:
        if direction == "long":
            return float(bar.get("low", 0.0)) <= sl_price
        else:
            return float(bar.get("high", 0.0)) >= sl_price
    except (TypeError, ValueError):
        return False


def _exit_price_on_sl(bar: dict, direction: str, sl_price: float) -> float:
    """Realistic SL exit price : slippage 0 ticks (paper).

    For prod realistic, ajouter slippage 1-2 ticks selon liquidite session.
    """
    return sl_price


def _compute_pnl(direction: str, entry: float, exit_p: float, tick: float) -> float:
    """PnL in ticks (positive = profit)."""
    if direction == "long":
        return (exit_p - entry) / tick
    else:
        return (entry - exit_p) / tick


def _update_mfe_mae(direction: str, entry: float, bar: dict, tick: float,
                    mfe: float, mae: float) -> tuple[float, float]:
    """Track max favorable/adverse excursion in ticks."""
    try:
        hi = float(bar.get("high", entry))
        lo = float(bar.get("low", entry))
    except (TypeError, ValueError):
        return (mfe, mae)
    if direction == "long":
        fav = (hi - entry) / tick
        adv = (lo - entry) / tick  # negative
    else:
        fav = (entry - lo) / tick
        adv = (entry - hi) / tick
    return (max(mfe, fav), min(mae, adv))


def simulate_trade(
    entry_bar_idx: int,
    setup: dict,
    direction: str,
    bars: list[dict],
    cfg,
    symbol: str,
) -> tuple[str, float, int, int, float, float, float]:
    """Simulate one trade with trailing Dow pivots.

    Returns:
        (exit_reason, exit_price, exit_bar_ts, duration_bars, pnl_ticks, mfe_ticks, mae_ticks)
    """
    from CORE.bn_v4_engine import TICK_SIZE
    from CORE.bot_bn_v4.trailing import TrailingManager

    tick = TICK_SIZE.get(symbol.upper(), 0.25)
    entry_bar = bars[entry_bar_idx]
    entry_price = float(setup.get("entry_price") or entry_bar.get("close") or 0.0)
    if entry_price <= 0:
        return ("NO_EXIT_BAD_ENTRY", 0.0, 0, 0, 0.0, 0.0, 0.0)

    trail = TrailingManager(symbol=symbol, cfg=cfg)
    err = trail.start(direction=direction, entry_bar=entry_bar,
                       entry_price=entry_price, entry_bar_idx=entry_bar_idx)
    if err is not None:
        return (f"TRAIL_START_FAIL:{err}", entry_price, 0, 0, 0.0, 0.0, 0.0)

    sl_current = trail.get_current_sl() or 0.0
    mfe, mae = 0.0, 0.0
    max_bars = cfg.TIMEOUT_BARS

    for offset in range(1, max_bars + 1):
        idx = entry_bar_idx + offset
        if idx >= len(bars):
            return ("EOD", entry_price, int(entry_bar.get("ts") or 0), offset, 0.0, mfe, mae)
        bar = bars[idx]

        # Update MFE/MAE
        mfe, mae = _update_mfe_mae(direction, entry_price, bar, tick, mfe, mae)

        # SL hit check (wick) BEFORE trail update
        if _detect_sl_hit(bar, direction, sl_current):
            exit_p = _exit_price_on_sl(bar, direction, sl_current)
            pnl = _compute_pnl(direction, entry_price, exit_p, tick)
            return ("SL_HIT", exit_p, int(bar.get("ts") or 0), offset, pnl, mfe, mae)

        # Trail update
        upd = trail.on_bar(bar)
        if upd.error and "INACTIVE" not in upd.error:
            return (f"TRAIL_ERR:{upd.error[:50]}", entry_price, int(bar.get("ts") or 0),
                    offset, 0.0, mfe, mae)
        if upd.new_sl is not None:
            sl_current = upd.new_sl
        if upd.is_timeout:
            close_p = float(bar.get("close") or entry_price)
            pnl = _compute_pnl(direction, entry_price, close_p, tick)
            return ("TIMEOUT", close_p, int(bar.get("ts") or 0), offset, pnl, mfe, mae)

    # Exited loop : max_bars reached without timeout via ts_event_ns
    last_bar = bars[min(entry_bar_idx + max_bars, len(bars) - 1)]
    close_p = float(last_bar.get("close") or entry_price)
    pnl = _compute_pnl(direction, entry_price, close_p, tick)
    return ("MAX_BARS", close_p, int(last_bar.get("ts") or 0), max_bars, pnl, mfe, mae)


def replay_day(symbol: str, day: date, cfg, output_dir: Path) -> int:
    """Replay one day for one symbol, append shadow trades JSONL.

    Returns:
        Number of shadow trades appended.
    """
    from CORE.bot_bn_v4.signal_engine import SignalEngine

    project_root = Path(__file__).resolve().parents[2]
    bars = _load_bars_for_day(symbol, day, project_root)
    if len(bars) < 250:  # warmup 240 + marge
        print(f"[shadow] {day} {symbol} : {len(bars)} bars < 250, skip")
        return 0

    eng = SignalEngine(symbol=symbol, cfg=cfg, log_fn=None)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"shadow_{day.strftime('%Y%m%d')}_{symbol.upper()}.jsonl"

    n_trades = 0
    with out_path.open("a", encoding="utf-8") as out:
        for i, bar in enumerate(bars):
            decision = eng.on_bar(bar)

            # On collecte tradable OR hypothetical (mode OBSERVE Grade A)
            setup = decision.setup
            if setup is None:
                continue
            direction = decision.direction
            if direction not in ("long", "short"):
                continue

            grade = setup.get("grade", "?")
            density = int(setup.get("density") or 0)
            n_levels = int(setup.get("n_levels") or 0)
            entry_price = float(setup.get("entry_price") or bar.get("close") or 0.0)
            if entry_price <= 0:
                continue

            # Simulate
            exit_reason, exit_price, exit_bar_ts, duration_bars, pnl_ticks, mfe, mae = \
                simulate_trade(i, setup, direction, bars, cfg, symbol)

            # PnL USD
            tick_value = TICK_VALUE_USD.get(symbol.upper(), 1.0)
            pnl_usd = pnl_ticks * tick_value

            from CORE.bn_v4_engine import TICK_SIZE
            tick = TICK_SIZE.get(symbol.upper(), 0.25)
            sl_init_price = setup.get("zone_bottom") if direction == "long" else setup.get("zone_top")
            sl_init_price = float(sl_init_price or 0.0)
            sl_init_ticks = abs(entry_price - sl_init_price) / tick if sl_init_price else 0.0

            signal_id = f"SHADOW_{symbol.upper()}_{int(bar.get('ts') or 0)}_{direction}"
            trade = ShadowTrade(
                signal_id=signal_id,
                ts_event=bar.get("ts_event") or "",
                sym=symbol.upper(),
                direction=direction,
                grade=grade,
                density=density,
                n_levels=n_levels,
                session=bar.get("session_segment") or "?",
                regime=bar.get("regime") or "?",
                entry_price=entry_price,
                entry_bar_ts=int(bar.get("ts") or 0),
                sl_initial_price=sl_init_price,
                sl_initial_ticks=sl_init_ticks,
                exit_reason=exit_reason,
                exit_price=exit_price,
                exit_bar_ts=exit_bar_ts,
                duration_bars=duration_bars,
                pnl_ticks=round(pnl_ticks, 2),
                pnl_usd=round(pnl_usd, 2),
                mfe_ticks=round(mfe, 2),
                mae_ticks=round(mae, 2),
                setup_full={k: v for k, v in setup.items() if k != "engine"},
            )
            out.write(json.dumps(trade.__dict__, default=str) + "\n")
            n_trades += 1

    print(f"[shadow] {day} {symbol} : {n_trades} setups appended -> {out_path.name}")
    return n_trades


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Shadow collector Bot BN V4 (replay sierra_enriched)")
    ap.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--symbols", default="NQ,ES")
    ap.add_argument("--grade-min", default="B", help="GRADE_MIN relaxe pour shadow (default B)")
    ap.add_argument("--output-dir", default="LOGS/bot_bn_v4_shadow")
    args = ap.parse_args(argv)

    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    output_dir = Path(args.output_dir).resolve()

    # Build shadow config : GRADE_MIN relaxe + both directions
    os.environ["BOTBN_GRADE_MIN"] = args.grade_min
    os.environ["BOTBN_DIRECTION_MODE"] = "both"
    from CORE.bot_bn_v4.config import BotBNV4Config
    cfg = BotBNV4Config.from_env()

    print(f"[shadow] config : GRADE_MIN={cfg.GRADE_MIN}, DIRECTION_MODE={cfg.DIRECTION_MODE}")
    print(f"[shadow] range : {start} -> {end} ({(end - start).days + 1} jours)")
    print(f"[shadow] symbols : {symbols}")
    print(f"[shadow] output : {output_dir}")

    total = 0
    for day in _list_dates(start, end):
        if day.weekday() == 5:  # samedi
            continue
        for sym in symbols:
            total += replay_day(sym, day, cfg, output_dir)

    print(f"\n[shadow] DONE : {total} setups shadow collectes sur {(end - start).days + 1} jours")
    return 0


if __name__ == "__main__":
    sys.exit(main())
