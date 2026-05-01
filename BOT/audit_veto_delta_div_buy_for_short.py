#!/usr/bin/env python3
"""Audit veto_delta_div_buy_for_short — verif statistique data-driven.

Question : sur les SHORTs Bot 2 historiques, combien avaient delta_div_buy > 0 ?
Quel WR et P&L ? Le veto est-il justifie ou speculatif (commentaire code dit
"symetrie attendue, a valider J+7") ?

Usage : python BOT/audit_veto_delta_div_buy_for_short.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\TRADING_SIERRA_CHART_AUTO")
TRADES_DIR = ROOT / "DATA" / "PAPER_TRADES"


def load_trades_for_day(day: str) -> list[dict]:
    """Lit trading_YYYYMMDD_databento_paper.jsonl. Codes : TRADE_OPEN, TRADE_CLOSE_SL, TRADE_CLOSE_TP."""
    fp = ROOT / "LOGS" / "trading" / f"trading_{day}_databento_paper.jsonl"
    if not fp.exists():
        return []
    trades = []
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("code", "").startswith("TRADE_"):
                trades.append(evt)
    return trades


def load_snapshots_for_day(day: str) -> dict[str, dict]:
    """Index snapshots par parent_id (snapshot.parent_id non-null = traded)."""
    fp = TRADES_DIR / f"{day}_databento_paper_snapshots.jsonl"
    if not fp.exists():
        return {}
    idx = {}
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = snap.get("parent_id")
            if pid:  # traded
                idx[pid] = snap
    return idx


def audit():
    days = ["20260428", "20260429", "20260430", "20260501"]

    n_total_trades = 0
    n_short = 0
    n_short_with_div_buy = 0
    n_short_without_div_buy = 0
    short_with_div_buy_pnl = []
    short_without_div_buy_pnl = []
    short_with_div_buy_wins = 0
    short_without_div_buy_wins = 0

    for day in days:
        trades = load_trades_for_day(day)
        snapshots = load_snapshots_for_day(day)

        # Map closes by parent_id (codes : TRADE_CLOSE_SL, TRADE_CLOSE_TP, TRADE_CLOSE_TIME, etc.)
        opens = {t.get("ctx", {}).get("parent_id"): t for t in trades if t.get("code") == "TRADE_OPEN"}
        closes = {t.get("ctx", {}).get("parent_id"): t for t in trades
                  if t.get("code", "").startswith("TRADE_CLOSE")}

        for parent_id, open_evt in opens.items():
            close_evt = closes.get(parent_id)
            if close_evt is None:
                continue
            n_total_trades += 1
            ctx_open = open_evt.get("ctx", {}) or {}
            ctx_close = close_evt.get("ctx", {}) or {}
            sym = ctx_open.get("sym", "")
            direction = ctx_open.get("direction", "")
            pnl_usd = ctx_close.get("pnl_usd", 0)

            if direction != "SELL":
                continue
            n_short += 1

            # Match snapshot par parent_id (precis)
            snap = snapshots.get(parent_id)
            if snap is None:
                continue
            features = snap.get("features", {}) or {}
            delta_div_buy = features.get("delta_div_buy", 0)

            if delta_div_buy and delta_div_buy > 0:
                n_short_with_div_buy += 1
                short_with_div_buy_pnl.append(pnl_usd)
                if pnl_usd > 0:
                    short_with_div_buy_wins += 1
            else:
                n_short_without_div_buy += 1
                short_without_div_buy_pnl.append(pnl_usd)
                if pnl_usd > 0:
                    short_without_div_buy_wins += 1

    print(f"\n{'='*60}")
    print(f"AUDIT veto_delta_div_buy_for_short (Jackson 01/05)")
    print(f"{'='*60}")
    print(f"Total trades historiques Bot 2 : {n_total_trades}")
    print(f"Total SHORTs                   : {n_short}")
    print(f"")
    print(f"--- SHORTs AVEC delta_div_buy > 0 (= bloques par veto v3) ---")
    print(f"  N        : {n_short_with_div_buy}")
    if n_short_with_div_buy > 0:
        wr = short_with_div_buy_wins / n_short_with_div_buy * 100
        sum_pnl = sum(short_with_div_buy_pnl)
        avg_pnl = sum_pnl / n_short_with_div_buy
        print(f"  Wins     : {short_with_div_buy_wins}/{n_short_with_div_buy} = {wr:.1f}% WR")
        print(f"  Sum PnL  : ${sum_pnl:.2f}")
        print(f"  Avg PnL  : ${avg_pnl:.2f}")
    else:
        print(f"  -> JAMAIS pris de SHORT avec delta_div_buy en historique")
    print(f"")
    print(f"--- SHORTs SANS delta_div_buy (= passent le veto v3) ---")
    print(f"  N        : {n_short_without_div_buy}")
    if n_short_without_div_buy > 0:
        wr = short_without_div_buy_wins / n_short_without_div_buy * 100
        sum_pnl = sum(short_without_div_buy_pnl)
        avg_pnl = sum_pnl / n_short_without_div_buy
        print(f"  Wins     : {short_without_div_buy_wins}/{n_short_without_div_buy} = {wr:.1f}% WR")
        print(f"  Sum PnL  : ${sum_pnl:.2f}")
        print(f"  Avg PnL  : ${avg_pnl:.2f}")

    print(f"")
    print(f"--- VERDICT ---")
    if n_short_with_div_buy < 5:
        print(f"  N={n_short_with_div_buy} < 5 -> echantillon insuffisant pour validation statistique.")
        print(f"  Veto base sur 'symetrie attendue', PAS sur evidence empirique.")
        print(f"  Recommandation : retirer veto OU attendre N>=20 avant decision.")
    elif n_short_with_div_buy >= 5:
        wr = short_with_div_buy_wins / n_short_with_div_buy * 100
        if wr < 30:
            print(f"  WR={wr:.1f}% < 30% -> veto JUSTIFIE empiriquement.")
        elif wr > 50:
            print(f"  WR={wr:.1f}% > 50% -> veto TROP STRICT, retirer.")
        else:
            print(f"  WR={wr:.1f}% intermediaire -> ambiguite, garder + observer.")


if __name__ == "__main__":
    audit()
