# -*- coding: utf-8 -*-
"""Audit RESCUED ChaseTopGate (R2 code-reviewer 05/05).

Pour chaque GATE_CHASE_TOP_LONG_BLOCK dans les logs decisions, charge le DMP
du jour, mesure MFE 30min apres le block. Si MFE >= TP_target (36t NQ, 9t ES),
le filter aurait rate un TP = false-block.

Sortie : count blocks total, count rescued (false-blocks), false-block rate.
Idealement < 30% false-block (le filter doit majoritairement bloquer des SL,
pas des TP).

Usage : python -X utf8 CORE/audit_chase_top_rescued.py [--days 7]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "LOGS" / "decisions"
DMP_DIR = ROOT / "DATA"
TICK = 0.25
TP_TARGET_TICKS = {"NQ": 36, "ES": 9}
HORIZON_MIN = 30


def load_blocks(days: int = 7) -> list:
    """Lit GATE_CHASE_TOP_LONG_BLOCK des N derniers jours."""
    blocks = []
    today = datetime.now(timezone.utc).date()
    for delta in range(days):
        d = today - timedelta(days=delta)
        date_str = d.strftime("%Y%m%d")
        for f in LOG_DIR.glob(f"decisions_{date_str}_*.jsonl"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    for line in fp:
                        s = line.strip()
                        if not s or "GATE_CHASE_TOP_LONG_BLOCK" not in s:
                            continue
                        try:
                            j = json.loads(s)
                            if j.get("code") == "GATE_CHASE_TOP_LONG_BLOCK":
                                blocks.append(j)
                        except json.JSONDecodeError:
                            pass
            except OSError:
                pass
    return blocks


def load_dmp(symbol: str, date_str: str) -> pd.DataFrame:
    path = DMP_DIR / symbol / f"{date_str}_{symbol}.jsonl"
    if not path.exists():
        return pd.DataFrame()
    bars = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                bars.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df["ts_dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
    return df.dropna(subset=["ts_dt"]).sort_values("ts_dt").reset_index(drop=True)


def measure_rescued(blocks: list) -> dict:
    """Pour chaque block, charge le DMP et mesure MFE 30min post-block."""
    results = []
    dmp_cache = {}
    for b in blocks:
        ctx = b.get("ctx", {}) or {}
        sym = ctx.get("sym", "")
        block_ts = ctx.get("block_ts")
        price_ref = ctx.get("price_ref")
        if sym not in TP_TARGET_TICKS or not block_ts or not price_ref:
            continue
        block_dt = datetime.fromtimestamp(block_ts, tz=timezone.utc)
        date_str = block_dt.strftime("%Y%m%d")
        key = (sym, date_str)
        if key not in dmp_cache:
            dmp_cache[key] = load_dmp(sym, date_str)
        df = dmp_cache[key]
        if df.empty:
            continue

        # Bars dans la fenetre [block_dt, block_dt + HORIZON_MIN]
        end = block_dt + timedelta(minutes=HORIZON_MIN)
        window = df[(df["ts_dt"] >= pd.Timestamp(block_dt)) &
                    (df["ts_dt"] <= pd.Timestamp(end))]
        if window.empty:
            continue

        high_col = "bar_high" if "bar_high" in window.columns else "high"
        max_high = window[high_col].max()
        mfe_ticks = (max_high - float(price_ref)) / TICK

        rescued = mfe_ticks >= TP_TARGET_TICKS[sym]
        results.append({
            "sym": sym,
            "block_ts": block_dt,
            "price_ref": float(price_ref),
            "max_high_30min": max_high,
            "mfe_ticks": round(mfe_ticks, 1),
            "tp_target": TP_TARGET_TICKS[sym],
            "rescued": rescued,
        })
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    blocks = load_blocks(days=args.days)
    print(f"GATE_CHASE_TOP_LONG_BLOCK total {args.days}j : {len(blocks)}")
    if not blocks:
        return

    results = measure_rescued(blocks)
    if not results:
        print("Aucun block analysable (DMP manquant ou ctx incomplet).")
        return

    df = pd.DataFrame(results)
    n_rescued = df["rescued"].sum()
    rate = n_rescued / len(df) * 100
    print(f"\nAnalysables    : {len(df)}/{len(blocks)}")
    print(f"RESCUED (TP rate) : {n_rescued} ({rate:.1f}%)")
    print(f"  Critere GO J+7 : false-block rate < 30%")
    print(f"  Verdict        : {'OK keep gate' if rate < 30 else 'INVESTIGATE rollback gate'}")

    # Per symbol
    for sym in ["ES", "NQ"]:
        sub = df[df["sym"] == sym]
        if not len(sub):
            continue
        n_resc = sub["rescued"].sum()
        rt = n_resc / len(sub) * 100
        print(f"  {sym}: rescued={n_resc}/{len(sub)} ({rt:.1f}%) median MFE={sub['mfe_ticks'].median():.0f}t")


if __name__ == "__main__":
    main()
