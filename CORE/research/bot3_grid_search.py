"""Bot 3 — Grid Search SL × Trailing × Timeout (vectorise numpy).

Pour chaque (niveau Tier 1, symbole), teste toutes les combinaisons :
  - SL_TICKS : NQ [150,200,250,300,400,500] / ES [60,80,100,120,160,200]
  - TRAIL_ACT : NQ [60,80,120,160,200] / ES [24,32,48,64,80]
  - TRAIL_DIST : NQ [40,60,80,100] / ES [16,24,32,40]
  - TIMEOUT : [30, 40, 60]

Total : 6 × 5 × 4 × 3 = 360 combinaisons par (niveau × symbole).
5 niveaux × 2 symboles × 360 = 3600 backtests.

Sortie :
  - Top 3 combinaisons par niveau × symbole (PF, win_rate, n)
  - Distribution exit_reasons
  - Rapport DOCS/BOT3_SL_CALIBRATION.md

Usage : python -X utf8 CORE/research/bot3_grid_search.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA_ROOT = ROOT / "DATA" / "DATASETS" / "v4_enriched"
DOCS_DIR = ROOT / "DOCS"
DOCS_DIR.mkdir(exist_ok=True)

TICK_SIZE = 0.25

# Grids
SL_GRID = {
    "NQ": [150, 200, 250, 300, 400, 500],
    "ES": [60, 80, 100, 120, 160, 200],
}
TRAIL_ACT_GRID = {
    "NQ": [60, 80, 120, 160, 200],
    "ES": [24, 32, 48, 64, 80],
}
TRAIL_DIST_GRID = {
    "NQ": [40, 60, 80, 100],
    "ES": [16, 24, 32, 40],
}
TIMEOUT_GRID = [30, 40, 60]

# Tier 1 levels
TIER1 = {
    "SINGLE_PRINT": {"col": "dist_single_print_nearest_pct", "prox": 0.02, "side": "REJECTION"},
    "IB_LOW":       {"col": "dist_ib_low_pct",                "prox": 0.05, "side": "LONG"},
    "MQ_PUT_0DTE":  {"col": "dist_mq_put_0dte_pct",           "prox": 0.05, "side": "LONG"},
    "OPEN_830":     {"col": "dist_open_830_pct",              "prox": 0.05, "side": "REJECTION"},
    "OPEN_930":     {"col": "dist_open_930_pct",              "prox": 0.05, "side": "REJECTION"},
}

BASELINE = {
    "SINGLE_PRINT": {"NQ": (70.1, 2.61), "ES": (69.1, 2.53)},
    "IB_LOW":       {"NQ": (59.6, 1.85), "ES": (58.9, 1.91)},
    "MQ_PUT_0DTE":  {"NQ": (57.5, 1.80), "ES": (58.0, 2.00)},
    "OPEN_830":     {"NQ": (54.3, 1.12), "ES": (56.7, 1.25)},
    "OPEN_930":     {"NQ": (53.4, 1.19), "ES": (56.7, 1.26)},
}


def load_all_parquet(symbol: str) -> pd.DataFrame:
    sym_path = DATA_ROOT / f"symbol={symbol}.c.0"
    files = sorted(sym_path.glob("year=*/month=*/data.parquet"))
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        if "ts_event" in df.columns:
            ts = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
            df["ts_event"] = ts.dt.tz_localize(None)
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    return df


def detect_contacts_vec(dist: np.ndarray, prox: float, cooldown: int = 5) -> np.ndarray:
    """Vectorise : indices ou |dist| <= prox + dedup cooldown bars.

    Retourne array d'indices (int64).
    """
    mask = (np.abs(dist) <= prox) & ~np.isnan(dist)
    cand = np.where(mask)[0]
    if len(cand) == 0:
        return cand
    # Dedup cooldown
    keep = [int(cand[0])]
    last = cand[0]
    for i in cand[1:]:
        if i - last >= cooldown:
            keep.append(int(i))
            last = i
    return np.array(keep, dtype=np.int64)


def simulate_grid(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
    entries: np.ndarray, sides: np.ndarray,
    sl_ticks: int, trail_act: int, trail_dist: int, timeout: int, tp_cap: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Simule N trades en numpy. Retourne (pnl_ticks_array, exit_reason_array).

    exit_reason : 0=SL, 1=TRAILING, 2=TIMEOUT, 3=TP_CAP
    """
    n = len(entries)
    pnls = np.full(n, 0.0, dtype=np.float64)
    reasons = np.full(n, 2, dtype=np.int8)  # default TIMEOUT
    nbar = len(close)

    for i in range(n):
        idx0 = int(entries[i])
        # Entry @ T+1 close (la barre de touch est evaluee, l'entry a la cloture suivante)
        entry_idx = idx0 + 1
        if entry_idx >= nbar:
            pnls[i] = 0.0
            reasons[i] = 2
            continue
        entry_price = close[entry_idx]
        direction = 1 if sides[i] > 0 else -1  # 1=LONG, -1=SHORT
        sl_price = entry_price - direction * sl_ticks * TICK_SIZE
        tp_cap_price = entry_price + direction * tp_cap * TICK_SIZE
        best = entry_price
        trailing = False

        last_idx = min(entry_idx + timeout, nbar - 1)
        exited = False
        for j in range(entry_idx + 1, last_idx + 1):
            h, l = high[j], low[j]
            # SL hit ?
            if direction == 1 and l <= sl_price:
                pnls[i] = (sl_price - entry_price) / TICK_SIZE
                reasons[i] = 1 if trailing else 0  # 1=TRAILING, 0=SL fix
                exited = True
                break
            if direction == -1 and h >= sl_price:
                pnls[i] = (entry_price - sl_price) / TICK_SIZE
                reasons[i] = 1 if trailing else 0
                exited = True
                break
            # TP cap ?
            if direction == 1 and h >= tp_cap_price:
                pnls[i] = tp_cap
                reasons[i] = 3
                exited = True
                break
            if direction == -1 and l <= tp_cap_price:
                pnls[i] = tp_cap
                reasons[i] = 3
                exited = True
                break
            # Update best
            if direction == 1 and h > best:
                best = h
            elif direction == -1 and l < best:
                best = l
            # Trailing activation
            fav = (best - entry_price) / TICK_SIZE * direction
            if not trailing and fav >= trail_act:
                trailing = True
            if trailing:
                new_sl = best - direction * trail_dist * TICK_SIZE
                if direction == 1 and new_sl > sl_price:
                    sl_price = new_sl
                elif direction == -1 and new_sl < sl_price:
                    sl_price = new_sl
        if not exited:
            final_price = close[last_idx]
            pnls[i] = (final_price - entry_price) / TICK_SIZE * direction
            reasons[i] = 2  # TIMEOUT

    return pnls, reasons


def calc_metrics(pnls: np.ndarray, reasons: np.ndarray) -> dict:
    n = len(pnls)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "pf": 0.0, "avg_t": 0.0,
                "exit_sl_pct": 0, "exit_trail_pct": 0, "exit_timeout_pct": 0, "exit_tpcap_pct": 0}
    wins = pnls[pnls > 0].sum()
    losses = abs(pnls[pnls < 0].sum())
    pf = (wins / losses) if losses > 0 else float("inf")
    win_rate = (pnls > 0).mean() * 100
    return {
        "n": n,
        "win_rate": round(win_rate, 1),
        "pf": round(pf, 2),
        "avg_t": round(pnls.mean(), 1),
        "exit_sl_pct": round((reasons == 0).mean() * 100, 0),
        "exit_trail_pct": round((reasons == 1).mean() * 100, 0),
        "exit_timeout_pct": round((reasons == 2).mean() * 100, 0),
        "exit_tpcap_pct": round((reasons == 3).mean() * 100, 0),
    }


def run_grid_for_level(
    df: pd.DataFrame, symbol: str, level_name: str, level_def: dict,
) -> list[dict]:
    """Test toutes les combos. Retourne liste de dicts (1 par combo)."""
    col = level_def["col"]
    if col not in df.columns:
        print(f"  WARN: colonne {col} absente, skip {level_name}")
        return []

    dist = df[col].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()

    contacts = detect_contacts_vec(dist, level_def["prox"], cooldown=5)
    if len(contacts) == 0:
        return []

    # Resolution side
    side_def = level_def["side"]
    if side_def == "LONG":
        sides = np.full(len(contacts), 1, dtype=np.int8)
    elif side_def == "SHORT":
        sides = np.full(len(contacts), -1, dtype=np.int8)
    else:  # REJECTION
        d = dist[contacts]
        sides = np.where(d > 0, 1, -1).astype(np.int8)

    sl_grid = SL_GRID[symbol]
    ta_grid = TRAIL_ACT_GRID[symbol]
    td_grid = TRAIL_DIST_GRID[symbol]
    tp_cap = sl_grid[-1] * 2  # tp_cap = 2x max SL

    results = []
    total = len(sl_grid) * len(ta_grid) * len(td_grid) * len(TIMEOUT_GRID)
    done = 0

    for sl in sl_grid:
        for ta in ta_grid:
            if ta >= sl * 0.6:  # trailing activation doit etre < 60% du SL
                continue
            for td in td_grid:
                if td >= ta:  # trail_dist doit etre < trail_act
                    continue
                for to in TIMEOUT_GRID:
                    pnls, reasons = simulate_grid(
                        high, low, close, contacts, sides,
                        sl_ticks=sl, trail_act=ta, trail_dist=td,
                        timeout=to, tp_cap=tp_cap,
                    )
                    m = calc_metrics(pnls, reasons)
                    m.update({"sl": sl, "trail_act": ta, "trail_dist": td, "timeout": to})
                    results.append(m)
                    done += 1
        print(f"  {level_name} {symbol} : SL={sl} done ({done}/{total})", flush=True)

    return results


def write_report(all_results: dict, output_path: Path) -> None:
    """Genere le rapport markdown."""
    lines = ["# Bot 3 — Grid Search SL × Trailing × Timeout\n"]
    lines.append("Generated automatically. Top 3 combinations par niveau × symbole.\n")
    lines.append("\n## Critere : maximize PF avec WR >= 50% et n >= 30.\n")

    for level_name in TIER1:
        lines.append(f"\n## {level_name}\n")
        baseline = BASELINE[level_name]
        for symbol in ("NQ", "ES"):
            key = (level_name, symbol)
            results = all_results.get(key, [])
            if not results:
                continue
            base_rej, base_pf = baseline.get(symbol, (None, None))
            lines.append(f"\n### {symbol} — Baseline doc : rej={base_rej}% pf={base_pf}\n")
            # Filtre WR>=50 + n>=30
            valid = [r for r in results if r["win_rate"] >= 50.0 and r["n"] >= 30]
            if not valid:
                valid = sorted(results, key=lambda r: r["pf"], reverse=True)[:3]
                lines.append(f"\n_(aucun avec WR>=50% n>=30, top 3 absolu)_\n")
            else:
                valid.sort(key=lambda r: r["pf"], reverse=True)
            top = valid[:3]
            lines.append("\n| Rank | SL | TrailAct | TrailDist | Timeout | n | WR% | PF | avgT | SL% | TRAIL% | TIMEOUT% | TPCAP% |\n")
            lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
            for i, r in enumerate(top, 1):
                lines.append(
                    f"| {i} | {r['sl']} | {r['trail_act']} | {r['trail_dist']} | {r['timeout']} | "
                    f"{r['n']} | {r['win_rate']} | {r['pf']} | {r['avg_t']} | "
                    f"{r['exit_sl_pct']:.0f} | {r['exit_trail_pct']:.0f} | "
                    f"{r['exit_timeout_pct']:.0f} | {r['exit_tpcap_pct']:.0f} |\n"
                )
            # Diagnostic
            best = top[0] if top else None
            if best:
                if best["exit_timeout_pct"] > 60:
                    lines.append(f"\n**Diagnostic** : >{60}% TIMEOUT → SL et trailing trop larges, le prix ne bouge pas assez.\n")
                elif best["exit_sl_pct"] > 40:
                    lines.append(f"\n**Diagnostic** : >{40}% SL → SL trop serre, niveaux n'ont pas le temps de travailler.\n")
                else:
                    lines.append(f"\n**Diagnostic** : equilibre OK (SL {best['exit_sl_pct']:.0f}% / TIMEOUT {best['exit_timeout_pct']:.0f}%).\n")

    output_path.write_text("".join(lines), encoding="utf-8")


def main():
    print("=" * 90)
    print("Bot 3 — Grid Search SL/Trailing/Timeout (vectorise numpy)")
    print("=" * 90)

    all_results = {}

    for symbol in ("NQ", "ES"):
        print(f"\n### {symbol} ###", flush=True)
        try:
            df = load_all_parquet(symbol)
        except Exception as e:
            print(f"  ERREUR: {e}", flush=True)
            continue
        print(f"  Loaded {len(df):,} bars", flush=True)

        for level_name, level_def in TIER1.items():
            print(f"\n--- {level_name} {symbol} ---", flush=True)
            results = run_grid_for_level(df, symbol, level_name, level_def)
            all_results[(level_name, symbol)] = results
            if results:
                # Top 3 par PF
                top3 = sorted(results, key=lambda r: r["pf"], reverse=True)[:3]
                for r in top3:
                    print(f"    SL={r['sl']:>4} TA={r['trail_act']:>3} TD={r['trail_dist']:>3} "
                          f"TO={r['timeout']:>2} | n={r['n']:>5} WR={r['win_rate']:>5.1f} "
                          f"PF={r['pf']:>5.2f}", flush=True)

    output_path = DOCS_DIR / "BOT3_SL_CALIBRATION.md"
    write_report(all_results, output_path)
    print(f"\nReport ecrit : {output_path}", flush=True)
    print("=" * 90, flush=True)


if __name__ == "__main__":
    main()
