"""intermarket_divergence_validation.py — Harness auditable du gate ES->NQ.

Reproduit le PF 1.445 du gate IntermarketDivergenceGate sur les trades
continuation CONT_NQ_R1p5 (backtest databento). Rend la validation auditable
(exigence code-reviewer 16/06, anti VALIDATION_MISS).

Resultat attendu (in-sample databento, NON transferable tel quel — cf caveat
module) :
  TOUS    : PF ~1.11 n=1611
  ALLOWED : PF ~1.445 n=210  (ES diverge, gate percentile top-13% rolling)
  BLOCKED : PF ~1.04 n=1401

Usage : python -X utf8 CORE/research/intermarket_divergence_validation.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.intermarket_divergence_gate import IntermarketDivergenceGate  # noqa: E402

TRADES = ROOT / "LOGS/bot3_continuation/CONT_NQ_R1p5/trades.jsonl"
ES_GLOB = str(ROOT / "DATA/live_enriched/ES/*.jsonl")


def _pf(trades: list) -> tuple[float, int]:
    p = np.array([t["pnl_ticks_gross"] for t in trades], dtype=float)
    losses = -p[p < 0].sum()
    return (p[p > 0].sum() / losses if losses > 0 else 99.0), len(p)


def main() -> None:
    # 1. serie ES (ts_ns, dist_vwap_w_pct)
    es = []
    for f in sorted(glob.glob(ES_GLOB)):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            ts = d.get("ts_event_ns") or d.get("ts")
            v = d.get("dist_vwap_w_pct")
            if ts and isinstance(v, (int, float)):
                es.append((ts, v))
    es.sort()
    es_min = {pd.to_datetime(t, unit="ns", utc=True).isoformat()[:16]: v for t, v in es}

    # 2. trades tries par entry ts
    trades = [json.loads(l) for l in open(TRADES, encoding="utf-8") if l.strip()]
    for t in trades:
        t["_ns"] = int(pd.Timestamp(t["entry_bar_ts"]).value)
    trades.sort(key=lambda t: t["_ns"])

    # 3. replay : update() AVANT should_allow() (contrat R3a)
    gate = IntermarketDivergenceGate(window=600, pct=13.0, min_samples=100, fail_safe_block=True)
    ei = 0
    allowed, blocked = [], []
    for t in trades:
        while ei < len(es) and es[ei][0] <= t["_ns"]:
            gate.update(es[ei][1])
            ei += 1
        cur = es_min.get(t["entry_bar_ts"][:16])
        ok, _ = gate.should_allow(t["side"], cur)
        (allowed if ok else blocked).append(t)

    for label, sub in [("TOUS", trades), ("ALLOWED", allowed), ("BLOCKED", blocked)]:
        pf, n = _pf(sub)
        print(f"  {label:8} : PF={pf:.3f} n={n}")
    print(f"  stats gate: {gate.stats()}")


if __name__ == "__main__":
    main()
