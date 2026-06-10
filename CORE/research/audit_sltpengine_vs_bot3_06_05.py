"""audit_sltpengine_vs_bot3_06_05.py — Audit cible 5 trades Bot 3 du 06/05/2026.

Demande Jackson 07/05 : verifier empiriquement si SLTPEngine (TP devant mur, SL derriere)
aurait donne des resultats meilleurs que la config Bot 3 actuelle (sl_ticks_base × ATR clamp,
tp = sl × 1.5 cap 80/160t).

Methodologie :
  1. Charger DMP JSONL 06/05 ES + NQ (dist_*_ticks bruts natifs SLTPEngine)
  2. Pour chaque trade Bot 3 du 06/05 : trouver bar JSONL au moment de l'entry
  3. Appeler SLTPEngine.evaluate_single(row, direction) → recupere SL/TP recommandes
  4. Comparer SL_actuel/TP_actuel (Bot 3 logs) vs SL_SLTPEngine/TP_SLTPEngine
  5. Path-aware forward 60 bars (depuis JSONL) : simule outcome avec les 2 systemes
  6. Calc pnl theorique difference

Trades audites (extraits BOT3_TRADE_OPEN logs 06/05) :
  - ES LONG GEX_DN @7362.0 a 14:51:36 UTC (sl=45t conf=50, MFE+40 MAE-4 → TIMEOUT)
  - ES LONG CUR_VPOC @7365.75 a 16:18:37 UTC (sl=27t conf=80, MFE+12 MAE-30 → TIMEOUT)
  - ES SHORT MQ_CALL_POC_FLAT @7368.0 a 17:56:37 UTC (sl=22t conf=50, en cours)
  - ES SHORT MQ_CALL_POC_FLAT @7338.25 a 12:31:17 UTC (sl=22t, MFE+35 MAE-22 → TIMEOUT)
  - NQ LONG GEX_DN @28602.5 a 11:51:15 UTC (sl=80t default, MFE+9 MAE-627 → TIMEOUT)

Run : python -X utf8 CORE/research/audit_sltpengine_vs_bot3_06_05.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
sys.path.insert(0, str(ROOT))

from CORE.mia_sltp import SLTPEngine

# ─── Trades reels du 06/05 (extraits logs BOT3_TRADE_OPEN) ────────────────
TRADES_TO_AUDIT = [
    {
        "label": "T1_ES_LONG_GEX_DN",
        "sym": "ES",
        "side": "LONG",
        "direction": 1,
        "ts_utc": "2026-05-06T14:51:36",
        "entry": 7362.0,
        "sl_actual_ticks": 45,
        "tp_actual_ticks": 91,  # TP @ 7384.63 - 7362 = 22.63 pts = 91t
        "mfe": 40,
        "mae": -4,
        "outcome_actual": "TIMEOUT",
    },
    {
        "label": "T2_ES_LONG_CUR_VPOC",
        "sym": "ES",
        "side": "LONG",
        "direction": 1,
        "ts_utc": "2026-05-06T16:18:37",
        "entry": 7365.75,
        "sl_actual_ticks": 27,
        "tp_actual_ticks": 48,  # estime R:R 1.5
        "mfe": 12,
        "mae": -30,
        "outcome_actual": "TIMEOUT",
    },
    {
        "label": "T3_ES_SHORT_MQ_CALL_POC_FLAT",
        "sym": "ES",
        "side": "SHORT",
        "direction": -1,
        "ts_utc": "2026-05-06T12:31:17",
        "entry": 7338.25,
        "sl_actual_ticks": 65,  # SL @ 7354.50 - 7338.25 = 16.25 pts = 65t
        "tp_actual_ticks": 55,  # TP @ 7338.25 - 7324.50 = 13.75 pts = 55t
        "mfe": 35,
        "mae": -22,
        "outcome_actual": "TIMEOUT",
    },
    {
        "label": "T4_NQ_LONG_GEX_DN",
        "sym": "NQ",
        "side": "LONG",
        "direction": 1,
        "ts_utc": "2026-05-06T11:51:15",
        "entry": 28602.5,
        "sl_actual_ticks": 80,  # default NQ
        "tp_actual_ticks": 120,  # R:R 1.5
        "mfe": 9,
        "mae": -627,
        "outcome_actual": "TIMEOUT",
    },
]

TICK_SIZES = {"ES": 0.25, "NQ": 0.25}
TICK_VALUES = {"ES": 1.25, "NQ": 0.50}
N_MICROS = 3
HORIZON_BARS = 60
SLIPPAGE_TICKS = 2


def load_jsonl_bars(sym: str) -> pd.DataFrame:
    """Charge les bars JSONL du 06/05 en DataFrame."""
    fp = ROOT / "DATA" / sym / "20260506_ES.jsonl" if sym == "ES" else ROOT / "DATA" / sym / "20260506_NQ.jsonl"
    rows = []
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    df = pd.DataFrame(rows)
    df["ts_event"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def find_bar_at_ts(df: pd.DataFrame, ts_utc: str):
    """Retourne la row la plus proche du ts_utc."""
    target = pd.Timestamp(ts_utc, tz="UTC")
    df = df.copy()
    df["delta"] = (df["ts_event"] - target).abs()
    idx = df["delta"].idxmin()
    return idx, df.iloc[idx]


def simulate_path_outcome(df: pd.DataFrame, entry_idx: int, direction: int,
                           entry_price: float, sl_ticks: float, tp_ticks: float,
                           tick_size: float):
    """Path-aware forward HORIZON_BARS bars. Retourne (outcome, exit_offset, pnl_ticks_net)."""
    sl_pts = sl_ticks * tick_size
    tp_pts = tp_ticks * tick_size
    if direction == 1:
        tp_target = entry_price + tp_pts
        sl_target = entry_price - sl_pts
    else:
        tp_target = entry_price - tp_pts
        sl_target = entry_price + sl_pts

    n = len(df)
    for k in range(1, HORIZON_BARS + 1):
        if entry_idx + k >= n:
            break
        bar = df.iloc[entry_idx + k]
        h = bar.get("bar_high") or bar.get("price")
        l = bar.get("bar_low") or bar.get("price")
        if h is None or l is None:
            continue
        h, l = float(h), float(l)
        if direction == 1:
            if l <= sl_target:
                return ("SL", k, -sl_ticks - SLIPPAGE_TICKS)
            if h >= tp_target:
                return ("TP", k, tp_ticks - SLIPPAGE_TICKS)
        else:
            if h >= sl_target:
                return ("SL", k, -sl_ticks - SLIPPAGE_TICKS)
            if l <= tp_target:
                return ("TP", k, tp_ticks - SLIPPAGE_TICKS)

    # TIMEOUT
    if entry_idx + HORIZON_BARS < n:
        close_h = df.iloc[entry_idx + HORIZON_BARS].get("price", entry_price)
        timeout_pnl_pts = (float(close_h) - entry_price) * direction
        return ("TIMEOUT", HORIZON_BARS, (timeout_pnl_pts / tick_size) - SLIPPAGE_TICKS)
    return ("TIMEOUT_NO_DATA", 0, 0)


def main():
    print("=" * 100)
    print("  AUDIT SLTPEngine vs Bot 3 actuel — 5 trades du 06/05/2026")
    print("=" * 100)

    # Cache JSONL par sym
    jsonl_cache = {}

    results = []
    for trade in TRADES_TO_AUDIT:
        print(f"\n{'='*100}")
        print(f"  {trade['label']}")
        print(f"  Side: {trade['side']} | Entry: {trade['entry']} | TS: {trade['ts_utc']}")
        print(f"  Bot 3 actuel : SL={trade['sl_actual_ticks']}t TP={trade['tp_actual_ticks']}t")
        print(f"  Outcome reel : {trade['outcome_actual']} MFE+{trade['mfe']} MAE{trade['mae']}")

        sym = trade["sym"]
        if sym not in jsonl_cache:
            jsonl_cache[sym] = load_jsonl_bars(sym)
        df = jsonl_cache[sym]

        idx, bar = find_bar_at_ts(df, trade["ts_utc"])
        print(f"  Bar JSONL trouve : idx={idx}, ts={bar['ts_event']}, price={bar['price']}")

        # Construire row pd.Series pour SLTPEngine
        row = bar.copy()
        # SLTPEngine attend close (utilise pour le check max_sl). Le DMP a price
        if "close" not in row:
            row["close"] = row.get("price", trade["entry"])

        # Appeler SLTPEngine
        engine = SLTPEngine(symbol=sym)
        sltp_result = engine.evaluate_single(row, trade["direction"])

        if not sltp_result.valid:
            print(f"\n  SLTPEngine REJET : {sltp_result.reject_reason}")
            sltp_sl_ticks = None
            sltp_tp_ticks = None
            sltp_rr = None
            sltp_pnl = None
            sltp_outcome = "REJECTED"
        else:
            sltp_sl_ticks = sltp_result.sl_ticks
            sltp_tp_ticks = sltp_result.tp1_ticks
            sltp_rr = sltp_result.rr_ratio
            print(f"\n  SLTPEngine VALID :")
            print(f"    SL = {sltp_sl_ticks:.0f}t (mur: {sltp_result.sl_wall} T{sltp_result.sl_wall_tier})")
            print(f"    TP = {sltp_tp_ticks:.0f}t (mur: {sltp_result.tp1_wall})")
            print(f"    R:R = {sltp_rr:.2f}")

            # Simuler outcome
            sltp_outcome, sltp_offset, sltp_pnl = simulate_path_outcome(
                df, idx, trade["direction"], trade["entry"],
                sltp_sl_ticks, sltp_tp_ticks, TICK_SIZES[sym])
            print(f"    Path-aware forward : {sltp_outcome} apres {sltp_offset} bars, pnl={sltp_pnl:+.1f}t/contract")

        # Simuler outcome Bot 3 actuel (path-aware avec sl/tp actuels)
        bot3_outcome, bot3_offset, bot3_pnl = simulate_path_outcome(
            df, idx, trade["direction"], trade["entry"],
            trade["sl_actual_ticks"], trade["tp_actual_ticks"], TICK_SIZES[sym])
        print(f"\n  Bot 3 actuel path-aware : {bot3_outcome} apres {bot3_offset} bars, pnl={bot3_pnl:+.1f}t/contract")

        # Comparer pnl total (3 micros)
        bot3_pnl_usd = bot3_pnl * TICK_VALUES[sym] * N_MICROS
        sltp_pnl_usd = sltp_pnl * TICK_VALUES[sym] * N_MICROS if sltp_pnl is not None else None

        print(f"\n  --- COMPARAISON ---")
        print(f"  Bot 3   : {bot3_outcome:>10} | pnl_ticks_per_contract = {bot3_pnl:+7.1f}t | pnl_total_usd = ${bot3_pnl_usd:+.2f}")
        if sltp_pnl is not None:
            print(f"  SLTPEng : {sltp_outcome:>10} | pnl_ticks_per_contract = {sltp_pnl:+7.1f}t | pnl_total_usd = ${sltp_pnl_usd:+.2f}")
            delta_usd = sltp_pnl_usd - bot3_pnl_usd
            print(f"  DELTA   : {delta_usd:+.2f} USD ({'BETTER' if delta_usd > 0 else 'WORSE' if delta_usd < 0 else 'EQUAL'})")
        else:
            print(f"  SLTPEng : REJECTED (pas de trade pris) — capital preserve")

        results.append({
            "label": trade["label"],
            "bot3_outcome": bot3_outcome,
            "bot3_pnl_usd": round(bot3_pnl_usd, 2),
            "sltp_outcome": sltp_outcome,
            "sltp_pnl_usd": round(sltp_pnl_usd, 2) if sltp_pnl_usd is not None else None,
            "sltp_sl_ticks": round(sltp_sl_ticks, 0) if sltp_sl_ticks else None,
            "sltp_tp_ticks": round(sltp_tp_ticks, 0) if sltp_tp_ticks else None,
            "sltp_rr": round(sltp_rr, 2) if sltp_rr else None,
            "sltp_reject_reason": sltp_result.reject_reason if not sltp_result.valid else "",
        })

    # Synthese
    print(f"\n\n{'='*100}")
    print(f"  SYNTHESE 5 trades 06/05")
    print(f"{'='*100}")
    bot3_total = sum(r["bot3_pnl_usd"] for r in results)
    sltp_total = sum(r["sltp_pnl_usd"] for r in results if r["sltp_pnl_usd"] is not None)
    sltp_n_taken = sum(1 for r in results if r["sltp_pnl_usd"] is not None)
    sltp_n_rejected = len(results) - sltp_n_taken

    print(f"\n  Trades audites : {len(results)}")
    print(f"  Bot 3 actuel total PnL : ${bot3_total:+.2f}")
    print(f"  SLTPEngine total PnL : ${sltp_total:+.2f} ({sltp_n_taken} pris, {sltp_n_rejected} rejected)")
    print(f"  DELTA : ${sltp_total - bot3_total:+.2f}")

    print(f"\n  Detail :")
    for r in results:
        bot3_str = f"${r['bot3_pnl_usd']:+.2f}"
        if r["sltp_pnl_usd"] is None:
            sltp_str = f"REJECTED ({r['sltp_reject_reason'][:50]})"
        else:
            sltp_str = f"${r['sltp_pnl_usd']:+.2f} (SL={r['sltp_sl_ticks']}t TP={r['sltp_tp_ticks']}t RR={r['sltp_rr']})"
        print(f"    {r['label']:<35} | Bot3 : {bot3_str:<12} | SLTP : {sltp_str}")


if __name__ == "__main__":
    main()
