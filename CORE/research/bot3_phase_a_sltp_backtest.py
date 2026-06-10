"""bot3_phase_a_sltp_backtest.py — Phase A backtest SLTPEngine vs TP actuel Bot 3.

PHASE A du plan integration SLTPEngine dans Bot 3 (verdict market-analyst 07/05).
Analyse pure : aucune modif code prod.

Methodologie :
  1. Charge trades Bot 3 logges sur VPS (LOGS/trades_bot3_*.jsonl ou paper trades)
  2. Pour chaque trade : recharge la bar V4/JSONL DMP correspondante
  3. Recalcule TP avec `SLTPEngine.calculate_row(row, direction, sl_ticks)`
  4. Compare :
     - tp_actuel (calcul live SL × 1.5 cape 160t)
     - tp_sltpengine (CAS 4 capot devant mur si trigger)
  5. Pour les trades historiques : checker si MFE peak >= tp_post_capot (TP touche capote)
     vs MFE peak >= tp_pre_capot (TP touche actuel hypothetique)
  6. Compute delta PnL net + verdict GO/NOGO Phase B

Criteres GO Phase B (verdict market-analyst) :
  - cas4_trigger_rate >= 30% (sinon trop peu de trades concernes)
  - tp_hit_rate_avec_capot >= 60% (vs ~20% actuel hypothetique)
  - delta PnL net >= 0% (au minimum equivalent)

Usage :
    python -X utf8 CORE/research/bot3_phase_a_sltp_backtest.py [--symbol NQ] [--days 60]

Date : 2026-05-07
Auteur : MIA Trading System (Phase A integration plan, post-verdict market-analyst)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import math
from CORE.mia_sltp import (
    SLTPEngine,
    SL_BUFFER_TICKS,
    SL_BUDGET,
    SL_MIN_TICKS,
    DEFAULT_TP_RR_FALLBACK,
    MAX_TP_WALL_DISTANCE,
    MAX_TP_TICKS_ABSOLUTE,
    MAX_TP_RR_RATIO,
    MIN_RR_RATIO,
    T2_STRUCTUREL_WALLS,
    TP_BUFFER_TICKS,
)


@dataclass
class TradeAnalysis:
    """Analyse 1 trade : TP actuel vs TP SLTPEngine."""
    ts_entry: str
    symbol: str
    direction: str  # LONG/SHORT
    entry_price: float
    sl_initial_ticks: int

    # TP actuel Bot 3 (calcul SL × tp_rr_ratio cape tp_cap)
    tp_actuel_ticks: float
    tp_actuel_price: float

    # TP SLTPEngine (CAS 4 si trigger)
    tp_sltp_ticks: float
    tp_sltp_price: float
    tp_sltp_wall: str
    cas4_triggered: bool
    cas4_blocked_wall: str
    cas4_subtier: str  # T1/T2_STRUCTUREL/T2_OBSERVABILITY

    # MFE peak (pour verifier TP touche)
    mfe_peak_ticks: float = 0.0
    mfe_peak_price: float = 0.0

    # Verdicts
    tp_actuel_touche: bool = False
    tp_sltp_touche: bool = False

    # Delta PnL theorique
    pnl_actuel_ticks: float = 0.0
    pnl_sltp_ticks: float = 0.0


def load_trades_from_logs(symbol: str, days: int = 60,
                          local_logs: Path = Path("LOGS")) -> pd.DataFrame:
    """Charge trades Bot 3 depuis logs events locaux.

    Format : events JSONL avec code BOT3_TRADE_OPEN.
    """
    rows = []
    # Bot 3 = paper_v2. Trades = LOGS/trading/trading_*_paper_v2.jsonl
    log_dir = local_logs / "trading"
    if not log_dir.exists():
        log_dir = local_logs
    for f in log_dir.glob("trading_*paper_v2.jsonl"):
        try:
            with f.open("r", encoding="utf-8") as fp:
                for line in fp:
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if ev.get("code") in ("BOT3_TRADE_OPEN",):
                        # Flatten ctx
                        ctx = ev.get("ctx", {})
                        rows.append({
                            "ts_event": ev.get("ts"),
                            "code": ev.get("code"),
                            "sym": ctx.get("sym"),
                            "level": ctx.get("level"),
                            "side": ctx.get("side"),
                            "action": ctx.get("action"),
                            "qty": ctx.get("qty"),
                            "price": ctx.get("price"),
                            "sl": ctx.get("sl"),
                            "conf": ctx.get("conf"),
                        })
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


def load_bar_for_trade(ts_entry: pd.Timestamp, symbol: str = "NQ") -> Optional[pd.Series]:
    """Charge la bar JSONL DMP la plus proche de ts_entry."""
    date_str = ts_entry.strftime("%Y%m%d")
    path = Path(f"DATA/{symbol}/{date_str}_{symbol}.jsonl")
    if not path.exists():
        return None

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    # La bar la plus proche AVANT entry (decision time)
    before = df[df["ts_event"] <= ts_entry]
    if len(before) == 0:
        return None
    return before.iloc[-1]


def compute_mfe_peak(ts_entry: pd.Timestamp, ts_exit: Optional[pd.Timestamp],
                     direction: str, entry_price: float, symbol: str = "NQ"
                     ) -> tuple[float, float]:
    """Calcule MFE peak entre ts_entry et ts_exit.

    Returns (mfe_ticks, mfe_price).
    """
    date_str = ts_entry.strftime("%Y%m%d")
    path = Path(f"DATA/{symbol}/{date_str}_{symbol}.jsonl")
    if not path.exists():
        return 0.0, entry_price

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return 0.0, entry_price

    df = pd.DataFrame(rows)
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    if ts_exit is not None:
        df = df[(df["ts_event"] >= ts_entry) & (df["ts_event"] <= ts_exit)]
    else:
        # Si pas exit, prendre 60 min apres entry
        df = df[(df["ts_event"] >= ts_entry) &
                (df["ts_event"] <= ts_entry + pd.Timedelta(minutes=60))]

    if len(df) == 0:
        return 0.0, entry_price

    if direction == "LONG":
        peak_price = float(df["bar_high"].max() if "bar_high" in df.columns else df["price"].max())
        mfe_ticks = (peak_price - entry_price) / 0.25
    else:
        peak_price = float(df["bar_low"].min() if "bar_low" in df.columns else df["price"].min())
        mfe_ticks = (entry_price - peak_price) / 0.25

    return max(mfe_ticks, 0.0), peak_price


def analyze_trade(trade_row: dict, symbol: str = "NQ") -> Optional[TradeAnalysis]:
    """Analyse 1 trade Bot 3 : compare TP actuel vs SLTPEngine."""
    try:
        ts_entry = pd.to_datetime(trade_row["ts_event"], utc=True)
    except Exception:
        return None

    direction = trade_row.get("side", "LONG")
    entry_price = float(trade_row.get("price", 0))
    sl_ticks = int(trade_row.get("sl", 0))

    if entry_price == 0 or sl_ticks == 0:
        return None

    # Recharge bar features
    bar = load_bar_for_trade(ts_entry, symbol)
    if bar is None:
        return None

    # Calcul TP actuel Bot 3 (ce que le bot a fait)
    rr_ratio = 1.5  # bot3_config NQ default
    tp_cap_ticks = 160 if symbol == "NQ" else 80
    tp_actuel_ticks = min(sl_ticks * rr_ratio, tp_cap_ticks)
    if direction == "LONG":
        tp_actuel_price = entry_price + tp_actuel_ticks * 0.25
    else:
        tp_actuel_price = entry_price - tp_actuel_ticks * 0.25

    # Calcul TP SLTPEngine — REPRODUIT logique _evaluate ligne 464-599 avec sl_ticks fixe
    eng = SLTPEngine(symbol=symbol)
    direction_int = 1 if direction == "LONG" else -1
    try:
        tp_buffer = TP_BUFFER_TICKS.get(symbol, 4)
        max_tp_dist = MAX_TP_WALL_DISTANCE.get(symbol, 200)
        max_tp_abs = MAX_TP_TICKS_ABSOLUTE.get(symbol, 100)

        # Etape 2 : premier mur TP
        tp1_ticks, tp1_wall, tp1_reason = eng._find_tp_obstacle(bar, direction_int, sl_ticks)

        # CAS 1 : aucun obstacle → TP standard SL × DEFAULT_TP_RR_FALLBACK (2.0)
        if tp1_ticks == 0:
            tp1_ticks = sl_ticks * DEFAULT_TP_RR_FALLBACK
            tp1_wall = "TP_STANDARD_NO_WALL"
        elif tp1_ticks > max_tp_dist:
            # CAS 2 : mur trop loin → fallback
            tp1_ticks = sl_ticks * DEFAULT_TP_RR_FALLBACK
            tp1_wall = "TP_STANDARD_WALL_FAR"

        # CAS 3 : cap absolu sur fallback TP_STANDARD
        if tp1_wall.startswith("TP_STANDARD") and tp1_ticks > max_tp_abs:
            tp1_ticks = max_tp_abs

        # CAS 4 mutation T1 + T2_STRUCTUREL
        cas4_triggered = False
        cas4_wall = ""
        cas4_subtier = ""
        obstacles = eng._scan_obstacles(bar, direction_int)
        walls_in_path = [o for o in obstacles if o.tier in (1, 2)]
        if walls_in_path:
            first_wall = walls_in_path[0]
            already_at_first_wall = (
                first_wall.name == tp1_wall
                or tp1_wall == f"TP_DEVANT_{first_wall.name}"
            )
            if not already_at_first_wall and first_wall.abs_dist < tp1_ticks:
                tp_devant_mur = math.floor(first_wall.abs_dist - tp_buffer)
                if tp_devant_mur > 0:
                    is_t2_structurel = (
                        first_wall.tier == 2
                        and first_wall.col in T2_STRUCTUREL_WALLS
                    )
                    apply_mutation = (first_wall.tier == 1 or is_t2_structurel)
                    if apply_mutation:
                        cas4_triggered = True
                        cas4_wall = first_wall.name
                        cas4_subtier = "T1" if first_wall.tier == 1 else "T2_STRUCTUREL"
                        tp1_ticks = float(tp_devant_mur)
                        tp1_wall = f"TP_DEVANT_{first_wall.name}"

        # CAS 5 : cap RR final
        if sl_ticks > 0 and tp1_ticks > sl_ticks * MAX_TP_RR_RATIO:
            tp1_ticks = sl_ticks * MAX_TP_RR_RATIO
            tp1_wall = f"TP_CAPPED_RR{MAX_TP_RR_RATIO}"

        tp_ticks_calc = tp1_ticks
        tp_wall = tp1_wall

        if direction == "LONG":
            tp_sltp_price = entry_price + tp_ticks_calc * 0.25
        else:
            tp_sltp_price = entry_price - tp_ticks_calc * 0.25
    except Exception as e:
        return None

    # MFE peak (pour verifier si TP touche)
    ts_exit = trade_row.get("ts_close")
    if ts_exit:
        ts_exit = pd.to_datetime(ts_exit, utc=True)
    mfe_ticks, mfe_price = compute_mfe_peak(ts_entry, ts_exit, direction, entry_price, symbol)

    return TradeAnalysis(
        ts_entry=str(ts_entry),
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        sl_initial_ticks=sl_ticks,
        tp_actuel_ticks=tp_actuel_ticks,
        tp_actuel_price=tp_actuel_price,
        tp_sltp_ticks=tp_ticks_calc,
        tp_sltp_price=tp_sltp_price,
        tp_sltp_wall=tp_wall,
        cas4_triggered=cas4_triggered,
        cas4_blocked_wall=cas4_wall,
        cas4_subtier=cas4_subtier,
        mfe_peak_ticks=mfe_ticks,
        mfe_peak_price=mfe_price,
        tp_actuel_touche=mfe_ticks >= tp_actuel_ticks,
        tp_sltp_touche=mfe_ticks >= tp_ticks_calc,
        pnl_actuel_ticks=tp_actuel_ticks if mfe_ticks >= tp_actuel_ticks else -sl_ticks,
        pnl_sltp_ticks=tp_ticks_calc if mfe_ticks >= tp_ticks_calc else -sl_ticks,
    )


def synthesize(analyses: list[TradeAnalysis]) -> dict:
    """Synthese des analyses : verdicts criteres GO Phase B."""
    n_total = len(analyses)
    if n_total == 0:
        return {"n_total": 0, "verdict": "NO_DATA"}

    n_cas4 = sum(1 for a in analyses if a.cas4_triggered)
    cas4_trigger_rate = n_cas4 / n_total

    n_tp_actuel_hit = sum(1 for a in analyses if a.tp_actuel_touche)
    n_tp_sltp_hit = sum(1 for a in analyses if a.tp_sltp_touche)
    tp_hit_rate_actuel = n_tp_actuel_hit / n_total
    tp_hit_rate_sltp = n_tp_sltp_hit / n_total

    # Delta PnL net
    pnl_actuel_total = sum(a.pnl_actuel_ticks for a in analyses)
    pnl_sltp_total = sum(a.pnl_sltp_ticks for a in analyses)
    delta_pnl_ticks = pnl_sltp_total - pnl_actuel_total

    # Critere GO Phase B
    go_phase_b = (
        cas4_trigger_rate >= 0.30
        and tp_hit_rate_sltp >= 0.60
        and delta_pnl_ticks >= 0
    )

    return {
        "n_total": n_total,
        "n_cas4_triggered": n_cas4,
        "cas4_trigger_rate": round(cas4_trigger_rate, 3),
        "tp_hit_rate_actuel": round(tp_hit_rate_actuel, 3),
        "tp_hit_rate_sltp": round(tp_hit_rate_sltp, 3),
        "pnl_actuel_total_ticks": round(pnl_actuel_total, 1),
        "pnl_sltp_total_ticks": round(pnl_sltp_total, 1),
        "delta_pnl_ticks": round(delta_pnl_ticks, 1),
        "verdict_phase_b": "GO" if go_phase_b else "NOGO",
        "criteria": {
            "cas4_trigger_rate >= 30%": cas4_trigger_rate >= 0.30,
            "tp_hit_rate_sltp >= 60%": tp_hit_rate_sltp >= 0.60,
            "delta_pnl >= 0": delta_pnl_ticks >= 0,
        }
    }


def main(symbol: str, days: int) -> None:
    print(f"=== Bot 3 Phase A : SLTPEngine backtest {symbol} (last {days}j) ===\n")

    # Step 1 : charger trades Bot 3
    df_trades = load_trades_from_logs(symbol, days)
    if df_trades.empty:
        print("Aucun trade Bot 3 trouve dans LOGS/. Sync VPS requis.")
        print("\nCommande sync :")
        print(f"  scp Administrator@212.28.179.199:'C:/TRADING_SIERRA_CHART_AUTO/LOGS/trades/*.jsonl' LOGS/trades/")
        return

    # Filtre BOT3_TRADE_OPEN avec symbole
    df_trades = df_trades[df_trades["code"] == "BOT3_TRADE_OPEN"]
    if "sym" in df_trades.columns:
        df_trades = df_trades[df_trades["sym"] == symbol]

    print(f"Trades Bot 3 {symbol} chargees : {len(df_trades)}")

    # Step 2 : analyse chaque trade
    analyses = []
    for _, row in df_trades.iterrows():
        a = analyze_trade(row.to_dict(), symbol)
        if a is not None:
            analyses.append(a)

    print(f"Trades analysables (data dispo) : {len(analyses)}")

    if not analyses:
        print("Aucun trade analysable — JSONL DMP manquants ou format incompatible")
        return

    # Step 3 : synthese
    summary = synthesize(analyses)
    print("\n=== Synthese ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # Step 4 : examples cas4_triggered
    cas4_trades = [a for a in analyses if a.cas4_triggered]
    if cas4_trades:
        print(f"\n=== Exemples CAS 4 triggered ({len(cas4_trades)}) ===")
        for a in cas4_trades[:5]:
            print(f"  {a.ts_entry} {a.direction} entry={a.entry_price:.2f}")
            print(f"    TP actuel: {a.tp_actuel_ticks:.0f}t @ {a.tp_actuel_price:.2f} touche={a.tp_actuel_touche}")
            print(f"    TP SLTP:   {a.tp_sltp_ticks:.0f}t @ {a.tp_sltp_price:.2f} ({a.cas4_subtier} {a.cas4_blocked_wall}) touche={a.tp_sltp_touche}")
            print(f"    MFE peak: {a.mfe_peak_ticks:.0f}t")

    # Step 5 : dump CSV
    if analyses:
        out_csv = Path(f"DATA/RESEARCH/bot3_phase_a_{symbol}_{len(analyses)}t.csv")
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([a.__dict__ for a in analyses]).to_csv(out_csv, index=False)
        print(f"\nDump CSV: {out_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    main(args.symbol, args.days)
