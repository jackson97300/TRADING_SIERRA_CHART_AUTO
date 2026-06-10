"""backfill_pd_levels_from_parquet.py — PD_LEVELS via parquet v5d colonnes absolues.

FIX 28/04 (post code-reviewer NO-GO) :
  - Utiliser les colonnes ABSOLUES du parquet : cur_vpoc, cur_vah, cur_val, vwap_d,
    vwap_d_sd1u, vwap_d_sd1d (pas de calcul depuis dist_*).
  - L'ancienne version utilisait `level = price + dist` qui donnait des valeurs
    echangees (PVAH < PVAL) car la convention parquet est `dist = close - level`
    (oppose de la convention JSONL brut C++).

Couvre les 254 dates du parquet v5d.

Usage : python -X utf8 CORE/backfill_pd_levels_from_parquet.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=None):
    f = _safe_float(v, None)
    return int(f) if f is not None else default


def main():
    out_dir = ROOT / "DATA" / "PD_LEVELS"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_total, n_ok, n_skip = 0, 0, 0
    for symbol in ["ES", "NQ"]:
        fp = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5d.parquet"
        if not fp.exists():
            print(f"[{symbol}] parquet absent: {fp}")
            continue
        print(f"\n[{symbol}] Loading {fp.name}...")
        df = pd.read_parquet(fp)
        df["ts_dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df["date_str"] = df["ts_dt"].dt.strftime("%Y%m%d")
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
        dates = sorted(df["date_str"].unique())
        print(f"[{symbol}] {len(dates)} dates RTH")

        for date_str in dates:
            n_total += 1
            day_df = df[df["date_str"] == date_str].sort_values("ts")
            if len(day_df) == 0:
                n_skip += 1
                continue
            target = day_df.iloc[-1]
            close = _safe_float(target["close"])
            if close is None:
                n_skip += 1
                continue

            # PDH/PDL depuis high/low de la session
            pdh = _safe_float(day_df["bar_high"].max() if "bar_high" in day_df else day_df["close"].max())
            pdl = _safe_float(day_df["bar_low"].min() if "bar_low" in day_df else day_df["close"].min())

            # Niveaux ABSOLUS depuis colonnes parquet (pas de calcul dist)
            pvpoc = _safe_float(target.get("cur_vpoc"))
            pvah = _safe_float(target.get("cur_vah"))
            pval = _safe_float(target.get("cur_val"))
            pvwap = _safe_float(target.get("vwap_d"))
            psd_plus_1 = _safe_float(target.get("vwap_d_sd1u"))
            psd_minus_1 = _safe_float(target.get("vwap_d_sd1d"))

            # Validation : si niveaux absolus manquants, skip (pas de fallback foireux)
            if any(v is None for v in [pvpoc, pvah, pval, pvwap, psd_plus_1, psd_minus_1]):
                n_skip += 1
                continue

            # Validation coherence (sanity) : PVAH > PVAL, PSD+1 > PSD-1
            if pvah <= pval:
                print(f"  [WARN] {date_str} {symbol} PVAH({pvah}) <= PVAL({pval}), skip")
                n_skip += 1
                continue
            if psd_plus_1 <= psd_minus_1:
                print(f"  [WARN] {date_str} {symbol} PSD+1({psd_plus_1}) <= PSD-1({psd_minus_1}), skip")
                n_skip += 1
                continue

            day_type = _safe_int(target.get("day_type"))
            open_type = _safe_int(target.get("open_type"))
            open_bias_conf = _safe_float(target.get("open_bias_conf"))

            obj = {
                "symbol": symbol,
                "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
                "PDH": pdh, "PDL": pdl, "PDC": close,
                "PVWAP": pvwap, "PVAH": pvah, "PVAL": pval, "PVPOC": pvpoc,
                "PSD_plus_1": psd_plus_1, "PSD_minus_1": psd_minus_1,
                "day_type": day_type,
                "open_type": open_type,
                "open_bias_conf": open_bias_conf,
                "computed_at_et": datetime.now(timezone.utc).isoformat(),
            }
            out_fp = out_dir / f"{date_str}_{symbol}.json"
            with open(out_fp, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2, default=str)
            n_ok += 1
        print(f"[{symbol}] OK")

    print(f"\nTotal: {n_total}, written: {n_ok}, skipped: {n_skip}")


if __name__ == "__main__":
    main()
