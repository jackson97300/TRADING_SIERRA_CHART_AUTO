"""bn_v5_recent_vs_30d.py — Compare drift_pct distribution 30j vs last 7j.

Jackson a dit "max 0.199% sur 95975 candidats today". On verifie : la baisse
de volatilite est-elle vraiment recente (last 7d) ou cohérente 30j ?
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
LIVE = ROOT / "DATA" / "live_enriched"
LOOKBACK = 30


def load_jsonl_keep(path: Path, cols=("date_et", "mins_et", "close")) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rows.append({k: rec.get(k) for k in cols})
    return pd.DataFrame(rows)


def drift(df: pd.DataFrame, lookback: int = LOOKBACK) -> pd.Series:
    c = df["close"].astype(float)
    c_lag = c.shift(lookback)
    return ((c - c_lag).abs() / c_lag * 100)


def session_label(m) -> str:
    try:
        m = int(m)
    except Exception:
        return "UNK"
    if 180 <= m < 570: return "LONDON"
    if 570 <= m < 960: return "US_RTH"
    if 960 <= m < 1080: return "US_AH"
    return "ASIA"


def main():
    for sym in ("NQ", "ES"):
        print(f"\n========== {sym} ==========")
        files = sorted((LIVE / sym).glob(f"*_{sym}.jsonl"))

        for window_label, file_subset in (
            ("Last 30 days", files[-30:]),
            ("Last 10 days", files[-10:]),
            ("Last 5 days",  files[-5:]),
        ):
            dfs = []
            for p in file_subset:
                df = load_jsonl_keep(p)
                if df.empty: continue
                dfs.append(df)
            if not dfs:
                continue
            df = pd.concat(dfs, ignore_index=True)
            df["drift_pct"] = drift(df)
            df["sess"] = df["mins_et"].map(session_label)
            s = df["drift_pct"].dropna()
            print(f"\n  [{window_label}] {len(file_subset)} files, n={len(s):,} bars")
            print(f"    drift_pct  P50={s.quantile(0.5):.4f}  P75={s.quantile(0.75):.4f}  P90={s.quantile(0.9):.4f}  P95={s.quantile(0.95):.4f}  P99={s.quantile(0.99):.4f}  max={s.max():.4f}")
            for thr in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
                passed = int((s >= thr).sum())
                print(f"    thr {thr:.2f}%  -> {passed:6,} ({100*passed/len(s):.2f}%)")
            # par session US RTH
            s_rth = df.loc[df["sess"] == "US_RTH", "drift_pct"].dropna()
            if len(s_rth) > 100:
                print(f"    US_RTH-only n={len(s_rth):,} P50={s_rth.quantile(0.5):.4f} P90={s_rth.quantile(0.9):.4f} P95={s_rth.quantile(0.95):.4f}")
                for thr in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
                    passed = int((s_rth >= thr).sum())
                    print(f"      US_RTH thr {thr:.2f}%  -> {passed:6,} ({100*passed/len(s_rth):.2f}%)")


if __name__ == "__main__":
    main()
