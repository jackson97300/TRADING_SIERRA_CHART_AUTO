"""Backtest Bot Mean Revert offline sur live_enriched/sierra/ JSONL.

Mission (18/06/2026) : prouver empiriquement si Bot MR a un edge
(PF > 1.3, EV > 0) AVANT d'investir dans plus de features (regime / circuit /
confluence). Bot perd en paper depuis le matin (carnage -$1025 17/06).

Mode : reproduit la logique signal_engine.evaluate() bar par bar SANS
dependre du PositionStore (mode counter-based legacy). Simule TP/SL/MAX_HOLD/
EOD/Cooldown/NO_REENTRY directement.

Compare 4 configurations cumulatives :
  1. naif       : cooldown + max_hold seulement (baseline brute)
  2. +no_reentry : 1 + anti-clustering spatial
  3. +regime    : 2 + regime trend_align_es / contrarian_nq
  4. +confluence : 3 + proximite niveaux MQ (>= 2 niveaux proches)

Output : metriques par config (PF, WR, EV, MaxDD, Sharpe, exit breakdown).

Limites assumees :
  - 5j ES / 4j NQ = SAMPLE EXTREMEMENT FAIBLE, signal directionnel pas
    statistiquement significatif (typically <30 trades par config).
  - Pas d'overlap avec valid set : zero out-of-sample, c'est un sanity check
    pas une validation Lopez.
  - Slippage = 0, commissions = 0 (paper-like).
  - PnL en E-mini USD (ES $12.50/t, NQ $5/t). Pour micro, diviser par 10.

Usage :
    python -X utf8 CORE/research/backtest_bot_mr.py --symbol ES
    python -X utf8 CORE/research/backtest_bot_mr.py --symbol NQ --days 20260610 20260611
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Repo root pour imports CORE.* quand lance depuis le projet root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from CORE.bot_mean_revert.config import BotMRConfig  # noqa: E402


# Pre-open US bruit (sweep ES : skip_preopen_us=True ameliore PF)
PREOPEN_US_START_MIN = 11 * 60 + 30  # 11:30 UTC
PREOPEN_US_END_MIN = 13 * 60 + 30    # 13:30 UTC

# Tick conventions (cf CORE/constants.py)
TICK_SIZE = {"ES": 0.25, "NQ": 0.25, "MGC": 0.10}
# E-mini standard (broker reel). Pour Sim Micro eq, diviser par 10.
USD_PER_TICK = {"ES": 12.50, "NQ": 5.0, "MGC": 1.0}

# Champs MenthorQ utilises par le filtre confluence stub.
# Format JSONL = distances (ticks/points), pas niveaux absolus.
# Un niveau est "proche" si abs(dist) <= radius_ticks * tick_size.
MQ_DIST_FIELDS = (
    "dist_mq_hvl",
    "dist_mq_call",
    "dist_mq_put",
    "dist_mq_hvl_0dte",
    "dist_mq_call_0dte",
    "dist_mq_put_0dte",
    "dist_gex_nearest_up",
    "dist_gex_nearest_dn",
)


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class Trade:
    sym: str
    entry_ts_ms: int
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    sl_ticks: int
    tp_ticks: int
    exit_ts_ms: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""  # TP / SL / MAX_HOLD / EOD
    pnl_ticks: float = 0.0
    pnl_usd: float = 0.0
    bars_held: int = 0
    day: str = ""

    def to_dict(self) -> dict:
        return {
            "sym": self.sym,
            "day": self.day,
            "direction": self.direction,
            "entry_ts": self.entry_ts_ms,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl_ticks": round(self.pnl_ticks, 2),
            "pnl_usd": round(self.pnl_usd, 2),
            "bars_held": self.bars_held,
        }


@dataclass
class BacktestMetrics:
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    win_rate: float = 0.0
    pf: float = 0.0
    ev_ticks: float = 0.0
    ev_usd: float = 0.0
    total_pnl_usd: float = 0.0
    max_dd_usd: float = 0.0
    sharpe: float = 0.0
    exit_breakdown: dict = field(default_factory=dict)
    by_day_pnl: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)


# ============================================================================
# Helpers
# ============================================================================

def _f(x, default: float = 0.0) -> float:
    """Coerce x en float, retourne default si None ou invalide."""
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _b(x) -> bool:
    if x is True or x == 1 or x == "true":
        return True
    return False


def load_jsonl_day(path: Path) -> list[dict]:
    """Charge un fichier JSONL en list[dict]. Ignore lignes mal formees."""
    bars = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return bars


def is_preopen_us(bar_ts_ms: int) -> bool:
    """True si bar tombe dans la fenetre 11:30-13:30 UTC (pre-open US)."""
    try:
        dt_utc = datetime.fromtimestamp(int(bar_ts_ms) / 1000, tz=timezone.utc)
        mins = dt_utc.hour * 60 + dt_utc.minute
        return PREOPEN_US_START_MIN <= mins < PREOPEN_US_END_MIN
    except (OSError, ValueError, OverflowError):
        return False


# ============================================================================
# Filters (reproduit signal_engine.evaluate)
# ============================================================================

def check_session(bar: dict, cfg: BotMRConfig, symbol: str) -> tuple[bool, str]:
    """Reproduit SignalEngine._check_session. Returns (allowed, reason)."""
    session_id = (bar.get("session_id") or "").upper()
    is_in_us = bool(bar.get("is_in_us_cash"))
    allowed = cfg.tradable_sessions(symbol)

    if is_in_us or session_id == "US":
        phase = "US"
    elif session_id == "ASIA":
        phase = "ASIA"
    elif session_id == "LONDON":
        phase = "LONDON"
    elif session_id == "US_AFTER":
        phase = "POST_RTH"
    elif session_id:
        phase = session_id
    else:
        phase = "?"

    if phase not in allowed:
        return False, f"SESSION_NOT_ALLOWED:{phase}"

    if cfg.SKIP_PREOPEN_US and phase == "US":
        if is_preopen_us(bar.get("ts", 0)):
            return False, "PREOPEN_US_SKIP"

    return True, ""


def check_regime(direction: str, bar: dict, cfg: BotMRConfig, symbol: str) -> tuple[bool, str]:
    """Reproduit SignalEngine._apply_regime_filter.

    Mode ES = trend_align_es, NQ = contrarian_nq.
    """
    mode = cfg.regime_filter_mode(symbol)
    if mode == "off":
        return True, ""

    slope_30 = _f(bar.get("vwap_slope_30"))
    vix = _f(bar.get("vix_level"))
    trend_day = _f(bar.get("ctx_trend_day_score"))

    if mode == "trend_align_es":
        if direction == "LONG" and slope_30 <= 0:
            return False, f"REGIME_ES_LONG_BLOCKED:slope={slope_30:.2f}"
        if direction == "SHORT":
            if slope_30 >= 0:
                return False, f"REGIME_ES_SHORT_BLOCKED:slope={slope_30:.2f}"
            if cfg.VIX_MIN_FOR_SHORT > 0 and vix <= cfg.VIX_MIN_FOR_SHORT:
                return False, f"VIX_TOO_LOW:{vix:.2f}"
        return True, ""

    if mode == "contrarian_nq":
        if direction == "LONG" and slope_30 >= 0:
            return False, f"REGIME_NQ_LONG_BLOCKED:slope={slope_30:.2f}"
        if direction == "SHORT":
            if slope_30 <= 0:
                return False, f"REGIME_NQ_SHORT_BLOCKED:slope={slope_30:.2f}"
            if trend_day > cfg.NQ_TREND_DAY_MAX:
                return False, f"NQ_TREND_DAY_TOO_HIGH:{trend_day:.2f}"
        return True, ""

    return True, ""


def check_confluence(bar: dict, symbol: str, close: float, min_levels: int = 2) -> tuple[bool, str]:
    """Stub confluence : >= min_levels niveaux MQ/GEX proches du close.

    Utilise les fields `dist_*` (distances) du JSONL sierra_enriched.
    Radius : 10 ticks ES (= 2.5 pts), 30 ticks NQ (= 7.5 pts) — calibrage
    indicatif sans optimisation. Le but du stub est d'illustrer le filtre,
    pas de produire le seuil optimal.
    """
    tick = TICK_SIZE[symbol]
    radius_ticks = 10 if symbol == "ES" else 30
    nearby = 0
    for fname in MQ_DIST_FIELDS:
        dist = bar.get(fname)
        if dist is None:
            continue
        try:
            dist_f = float(dist)
        except (TypeError, ValueError):
            continue
        # Les dist_mq_* sont en POINTS (cf head : dist_mq_call=210.0 = 210 pts).
        # 1 point ES = 4 ticks, donc dist_ticks = dist_pts / tick (tick=0.25 ES/NQ).
        dist_ticks = abs(dist_f) / tick
        if dist_ticks <= radius_ticks:
            nearby += 1
    if nearby < min_levels:
        return False, f"CONFLUENCE_LOW:{nearby}<{min_levels}"
    return True, ""


# ============================================================================
# Trade simulation
# ============================================================================

def simulate_close_on_bar(
    open_pos: Trade,
    bar: dict,
    tick_size: float,
    usd_per_tick: float,
    max_hold_minutes: int,
) -> Optional[Trade]:
    """Verifie si bar courante ferme open_pos.

    Ordre de priorite (conservateur) :
      1. MAX_HOLD -> close au close de la bar
      2. SL touche  -> close au SL price (prioritaire vs TP, conservateur)
      3. TP touche  -> close au TP price
    Si SL ET TP touches dans la meme bar, on assume SL (worst case).
    """
    high = _f(bar.get("high", bar.get("close")))
    low = _f(bar.get("low", bar.get("close")))
    close = _f(bar.get("close"))
    bar_ts_ms = int(bar.get("ts", 0))

    elapsed_min = (bar_ts_ms - open_pos.entry_ts_ms) / 60_000.0

    # MAX_HOLD (prio 1)
    if elapsed_min >= max_hold_minutes:
        open_pos.exit_ts_ms = bar_ts_ms
        open_pos.exit_price = close
        open_pos.exit_reason = "MAX_HOLD"
        sign = 1.0 if open_pos.direction == "LONG" else -1.0
        open_pos.pnl_ticks = sign * (close - open_pos.entry_price) / tick_size
        open_pos.pnl_usd = open_pos.pnl_ticks * usd_per_tick
        open_pos.bars_held = int(elapsed_min)
        return open_pos

    # SL/TP detection (high/low intra-bar)
    if open_pos.direction == "LONG":
        sl_hit = low <= open_pos.sl_price
        tp_hit = high >= open_pos.tp_price
        if sl_hit:
            open_pos.exit_ts_ms = bar_ts_ms
            open_pos.exit_price = open_pos.sl_price
            open_pos.exit_reason = "SL"
            open_pos.pnl_ticks = (open_pos.sl_price - open_pos.entry_price) / tick_size
            open_pos.pnl_usd = open_pos.pnl_ticks * usd_per_tick
            open_pos.bars_held = int(elapsed_min)
            return open_pos
        if tp_hit:
            open_pos.exit_ts_ms = bar_ts_ms
            open_pos.exit_price = open_pos.tp_price
            open_pos.exit_reason = "TP"
            open_pos.pnl_ticks = (open_pos.tp_price - open_pos.entry_price) / tick_size
            open_pos.pnl_usd = open_pos.pnl_ticks * usd_per_tick
            open_pos.bars_held = int(elapsed_min)
            return open_pos
    else:  # SHORT
        sl_hit = high >= open_pos.sl_price
        tp_hit = low <= open_pos.tp_price
        if sl_hit:
            open_pos.exit_ts_ms = bar_ts_ms
            open_pos.exit_price = open_pos.sl_price
            open_pos.exit_reason = "SL"
            open_pos.pnl_ticks = (open_pos.entry_price - open_pos.sl_price) / tick_size
            open_pos.pnl_usd = open_pos.pnl_ticks * usd_per_tick
            open_pos.bars_held = int(elapsed_min)
            return open_pos
        if tp_hit:
            open_pos.exit_ts_ms = bar_ts_ms
            open_pos.exit_price = open_pos.tp_price
            open_pos.exit_reason = "TP"
            open_pos.pnl_ticks = (open_pos.entry_price - open_pos.tp_price) / tick_size
            open_pos.pnl_usd = open_pos.pnl_ticks * usd_per_tick
            open_pos.bars_held = int(elapsed_min)
            return open_pos

    return None


# ============================================================================
# Backtest core
# ============================================================================

def run_backtest(
    symbol: str,
    day_files: list[Path],
    cfg: BotMRConfig,
    filters_active: dict,
) -> BacktestMetrics:
    """Backtest multi-jours pour un symbole avec un set de filtres actif.

    filters_active : {
        "no_reentry": bool,  # anti-clustering spatial
        "regime": bool,       # trend_align_es / contrarian_nq
        "confluence": bool,   # >=2 niveaux MQ proches
    }
    Cooldown + max_hold + session + SD threshold = TOUJOURS actifs (baseline).
    """
    tick_size = TICK_SIZE[symbol]
    usd_per_tick = USD_PER_TICK[symbol]
    metrics = BacktestMetrics()

    last_trade_ts_ms = 0
    last_entry_price_by_dir: dict[str, float] = {}
    open_pos: Optional[Trade] = None

    for day_path in sorted(day_files):
        day_str = day_path.stem.split("_")[0]  # YYYYMMDD
        bars = load_jsonl_day(day_path)
        if not bars:
            continue

        for bar in bars:
            bar_ts_ms = int(bar.get("ts", 0))

            # === 1. Si position ouverte, check close
            if open_pos is not None:
                closed = simulate_close_on_bar(
                    open_pos, bar, tick_size, usd_per_tick, cfg.MAX_HOLD_MINUTES,
                )
                if closed is not None:
                    metrics.trades.append(closed)
                    last_trade_ts_ms = bar_ts_ms
                    open_pos = None
                # Pas de nouveau signal tant que position ouverte
                continue

            # === 2. Cooldown (counter-based simplifie : compte bars depuis last close)
            # COOLDOWN_BARS = 30 default. 1 bar = 60s.
            if last_trade_ts_ms > 0:
                elapsed_sec = (bar_ts_ms - last_trade_ts_ms) / 1000.0
                if elapsed_sec < cfg.COOLDOWN_BARS * 60.0:
                    continue

            # === 3. Session
            sess_ok, _ = check_session(bar, cfg, symbol)
            if not sess_ok:
                continue

            # === 4. RVOL min
            rvol_z = _f(bar.get("rvol_zscore"))
            if rvol_z < cfg.RVOL_ZSCORE_MIN:
                continue

            # === 5. SD bands extension
            if cfg.SD_LEVEL == "sd3":
                d_low = _f(bar.get("dist_vwap_d_sd3d_pct"))
                d_high = _f(bar.get("dist_vwap_d_sd3u_pct"))
            else:
                d_low = _f(bar.get("dist_vwap_d_sd2d_pct"))
                d_high = _f(bar.get("dist_vwap_d_sd2u_pct"))

            thr = cfg.SD_THRESHOLD_PCT
            direction: Optional[str] = None
            if d_low <= -thr:
                direction = "LONG"
            elif d_high >= thr:
                direction = "SHORT"
            else:
                continue

            close = _f(bar.get("close"))
            if close <= 0:
                continue

            # === 6. NO_REENTRY (filtre optionnel)
            if filters_active.get("no_reentry", False):
                last_p = last_entry_price_by_dir.get(direction)
                if last_p is not None:
                    dist_ticks = abs(close - last_p) / tick_size
                    if dist_ticks < cfg.no_reentry_ticks(symbol):
                        continue

            # === 7. REGIME (filtre optionnel)
            if filters_active.get("regime", False):
                regime_ok, _ = check_regime(direction, bar, cfg, symbol)
                if not regime_ok:
                    continue

            # === 8. CONFLUENCE (filtre optionnel)
            if filters_active.get("confluence", False):
                conf_ok, _ = check_confluence(bar, symbol, close, min_levels=2)
                if not conf_ok:
                    continue

            # === 9. Open trade
            sl_ticks = cfg.sl_ticks(symbol)
            tp_ticks = int(round(sl_ticks * cfg.RR))
            if direction == "LONG":
                sl_price = close - sl_ticks * tick_size
                tp_price = close + tp_ticks * tick_size
            else:
                sl_price = close + sl_ticks * tick_size
                tp_price = close - tp_ticks * tick_size

            open_pos = Trade(
                sym=symbol,
                entry_ts_ms=bar_ts_ms,
                direction=direction,
                entry_price=close,
                sl_price=sl_price,
                tp_price=tp_price,
                sl_ticks=sl_ticks,
                tp_ticks=tp_ticks,
                day=day_str,
            )
            last_entry_price_by_dir[direction] = close

        # === EOD : force close si position ouverte au dernier bar du jour
        if open_pos is not None and bars:
            last_bar = bars[-1]
            close = _f(last_bar.get("close", open_pos.entry_price))
            bar_ts_ms = int(last_bar.get("ts", 0))
            sign = 1.0 if open_pos.direction == "LONG" else -1.0
            open_pos.exit_ts_ms = bar_ts_ms
            open_pos.exit_price = close
            open_pos.exit_reason = "EOD"
            open_pos.pnl_ticks = sign * (close - open_pos.entry_price) / tick_size
            open_pos.pnl_usd = open_pos.pnl_ticks * usd_per_tick
            open_pos.bars_held = int((bar_ts_ms - open_pos.entry_ts_ms) / 60_000.0)
            metrics.trades.append(open_pos)
            last_trade_ts_ms = bar_ts_ms
            open_pos = None

    return compute_metrics(metrics)


def compute_metrics(metrics: BacktestMetrics) -> BacktestMetrics:
    """Calcule PF, EV, WR, max DD, Sharpe + exit_breakdown + by_day_pnl."""
    trades = metrics.trades
    metrics.n_trades = len(trades)
    if metrics.n_trades == 0:
        return metrics

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    metrics.n_wins = len(wins)
    metrics.n_losses = len(losses)
    metrics.win_rate = metrics.n_wins / metrics.n_trades * 100.0

    gross_profit = sum(t.pnl_usd for t in wins)
    gross_loss = abs(sum(t.pnl_usd for t in losses))
    if gross_loss > 0:
        metrics.pf = gross_profit / gross_loss
    else:
        metrics.pf = float("inf") if gross_profit > 0 else 0.0

    metrics.total_pnl_usd = sum(t.pnl_usd for t in trades)
    metrics.ev_usd = metrics.total_pnl_usd / metrics.n_trades
    metrics.ev_ticks = sum(t.pnl_ticks for t in trades) / metrics.n_trades

    # Max DD
    cumul = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumul += t.pnl_usd
        if cumul > peak:
            peak = cumul
        dd = peak - cumul
        if dd > max_dd:
            max_dd = dd
    metrics.max_dd_usd = max_dd

    # Sharpe annualise approx (sur trade returns, hyp ~252 trading days)
    if metrics.n_trades >= 2:
        pnls = [t.pnl_usd for t in trades]
        mean_p = statistics.mean(pnls)
        stdev_p = statistics.stdev(pnls)
        metrics.sharpe = (mean_p / stdev_p) * (252.0 ** 0.5) if stdev_p > 0 else 0.0

    # Exit breakdown
    for t in trades:
        metrics.exit_breakdown[t.exit_reason] = (
            metrics.exit_breakdown.get(t.exit_reason, 0) + 1
        )

    # PnL par jour
    for t in trades:
        metrics.by_day_pnl[t.day] = metrics.by_day_pnl.get(t.day, 0.0) + t.pnl_usd

    return metrics


# ============================================================================
# CLI / Reporting
# ============================================================================

def print_metrics(name: str, m: BacktestMetrics) -> None:
    """Affiche les metriques d'un run."""
    print(f"=== {name} ===")
    if m.n_trades == 0:
        print("  N trades: 0 -- aucun signal valide")
        print()
        return
    pf_str = f"{m.pf:.2f}" if m.pf != float("inf") else "INF"
    print(
        f"  N={m.n_trades} | WR={m.win_rate:.1f}% | PF={pf_str} "
        f"| EV={m.ev_ticks:+.1f}t / ${m.ev_usd:+.2f}"
    )
    print(
        f"  Total=${m.total_pnl_usd:+.2f} | MaxDD=${m.max_dd_usd:.2f} "
        f"| Sharpe={m.sharpe:.2f}"
    )
    print(f"  Exits: {dict(sorted(m.exit_breakdown.items()))}")
    if m.by_day_pnl:
        days_sorted = sorted(m.by_day_pnl.items())
        day_str = ", ".join(f"{d}:${v:+.0f}" for d, v in days_sorted)
        print(f"  By day: {day_str}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Backtest Bot MR sur sierra_enriched JSONL"
    )
    parser.add_argument("--symbol", default="ES", choices=["ES", "NQ", "MGC"])
    parser.add_argument(
        "--data-dir",
        default="DATA/live_enriched/sierra",
        help="Repertoire racine sierra_enriched (default: DATA/live_enriched/sierra)",
    )
    parser.add_argument(
        "--days",
        nargs="*",
        help="Liste YYYYMMDD a inclure. Vide = tous les jours dispo.",
    )
    parser.add_argument(
        "--trades-out",
        help="Optionnel : fichier JSONL ou dumper les trades de chaque config",
    )
    args = parser.parse_args()

    cfg = BotMRConfig.from_env()
    print("=" * 70)
    print(f"BACKTEST BOT MR — symbol={args.symbol}")
    print("=" * 70)
    print(f"Config :")
    print(f"  SD_LEVEL={cfg.SD_LEVEL} SD_THRESHOLD={cfg.SD_THRESHOLD_PCT}")
    print(f"  RVOL_MIN={cfg.RVOL_ZSCORE_MIN}")
    print(f"  COOLDOWN_BARS={cfg.COOLDOWN_BARS} MAX_HOLD_MIN={cfg.MAX_HOLD_MINUTES}")
    print(f"  SL_TICKS={cfg.sl_ticks(args.symbol)} RR={cfg.RR}")
    print(f"  NO_REENTRY_TICKS={cfg.no_reentry_ticks(args.symbol)}")
    print(f"  REGIME_MODE={cfg.regime_filter_mode(args.symbol)}")
    print(f"  TRADABLE_SESSIONS={cfg.tradable_sessions(args.symbol)}")
    print(f"  SKIP_PREOPEN_US={cfg.SKIP_PREOPEN_US}")
    print()

    # Discover files
    data_dir = Path(args.data_dir) / args.symbol
    if not data_dir.exists():
        print(f"ERROR: data dir absent : {data_dir}")
        sys.exit(1)
    pattern = f"*_{args.symbol}_sierra_enriched.jsonl"
    all_files = sorted(data_dir.glob(pattern))
    if args.days:
        all_files = [f for f in all_files if any(d in f.stem for d in args.days)]
    if not all_files:
        print(f"ERROR: aucun fichier match dans {data_dir}")
        sys.exit(1)

    print(f"Fichiers ({len(all_files)}) : {[f.name for f in all_files]}")
    print()

    # 4 configurations cumulatives
    configs = [
        ("1. naif (cooldown + max_hold)",
         {"no_reentry": False, "regime": False, "confluence": False}),
        ("2. +no_reentry",
         {"no_reentry": True, "regime": False, "confluence": False}),
        ("3. +no_reentry +regime",
         {"no_reentry": True, "regime": True, "confluence": False}),
        ("4. +no_reentry +regime +confluence",
         {"no_reentry": True, "regime": True, "confluence": True}),
    ]

    all_results = {}
    trades_dump = {}
    for name, filters in configs:
        m = run_backtest(args.symbol, all_files, cfg, filters)
        all_results[name] = m
        trades_dump[name] = [t.to_dict() for t in m.trades]
        print_metrics(name, m)

    # Summary comparatif
    print("=" * 70)
    print(f"COMPARATIF (symbol={args.symbol})")
    print("=" * 70)
    print(f"{'Config':<40} {'N':>4} {'WR%':>6} {'PF':>6} {'EV$':>8} {'Total$':>10}")
    for name, m in all_results.items():
        pf_str = f"{m.pf:.2f}" if m.pf != float("inf") else "INF"
        print(
            f"{name:<40} {m.n_trades:>4} {m.win_rate:>6.1f} "
            f"{pf_str:>6} {m.ev_usd:>+8.2f} {m.total_pnl_usd:>+10.2f}"
        )

    if args.trades_out:
        out_path = Path(args.trades_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(trades_dump, f, indent=2)
        print(f"\nTrades dumped to : {out_path}")


if __name__ == "__main__":
    main()
