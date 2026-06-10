"""
Investigation manuelle 3 bars — DMP vs Databento (24/04/2026 ES.c.0).

Objectif :
1. Confirmer convention timestamp (DMP = fin de bar ? DBN = debut de bar ?)
2. Verifier instrument_id DBN constant sur la journee (pas de roll intra-day)
3. Comparer cote-a-cote 3 bars cibles : Asia / RTH-open / RTH-close

Output : rapport visuel pour decider methodologie comparaison globale.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATABENTO_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3"


def load_dmp(jsonl_path: Path) -> pd.DataFrame:
    """Lit JSONL DMP en DataFrame minimaliste (close/high/low/vol/buy/sell)."""
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                rows.append({
                    "ts_ms": d.get("ts"),
                    "close": d.get("price"),
                    "high": d.get("bar_high"),
                    "low": d.get("bar_low"),
                    "vol": d.get("total_vol"),
                    "buy_vol": d.get("buy_vol"),
                    "sell_vol": d.get("sell_vol"),
                })
            except Exception:
                continue
    df = pd.DataFrame(rows)
    df["ts_utc"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df


def load_dbn_parquet(parquet_path: Path) -> pd.DataFrame:
    """Lit Parquet OHLCV-1m Databento."""
    if not parquet_path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(parquet_path)
    if not isinstance(df.index, pd.DatetimeIndex):
        # Fallback si index pas datetime
        if "ts_event" in df.columns:
            df.index = pd.to_datetime(df["ts_event"], utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def find_bar(df_dmp: pd.DataFrame, target_utc: datetime, label: str):
    """Cherche le bar DMP dont ts == target_utc (en ms)."""
    target_ms = int(target_utc.timestamp() * 1000)
    match = df_dmp[df_dmp["ts_ms"] == target_ms]
    if match.empty:
        # Cherche bar precedent (convention "fin de bar")
        prev_match = df_dmp[df_dmp["ts_ms"] == target_ms - 60_000]
        if not prev_match.empty:
            return prev_match.iloc[0], "ts-1min (DMP=fin_de_bar)"
        next_match = df_dmp[df_dmp["ts_ms"] == target_ms + 60_000]
        if not next_match.empty:
            return next_match.iloc[0], "ts+1min (DMP=debut_de_bar)"
        return None, "NOT_FOUND"
    return match.iloc[0], "exact"


def find_dbn_bar(df_dbn: pd.DataFrame, target_utc: datetime):
    """Cherche le bar DBN dont ts_event == target_utc."""
    target = pd.Timestamp(target_utc).tz_convert("UTC") if target_utc.tzinfo else pd.Timestamp(target_utc).tz_localize("UTC")
    if target in df_dbn.index:
        return df_dbn.loc[target], "exact"
    # Cherche bar dans la fenetre +/- 1 min
    nearest_idx = df_dbn.index.get_indexer([target], method="nearest")[0]
    nearest = df_dbn.index[nearest_idx]
    delta = (nearest - target).total_seconds()
    return df_dbn.loc[nearest], f"nearest delta={delta:+.0f}s"


def main():
    print("=" * 90)
    print(" INVESTIGATION 3 BARS — DMP vs DATABENTO (24/04/2026 ES)")
    print("=" * 90)

    # --- Load DMP 24/04 + 23/04 ---
    dmp_24 = load_dmp(ROOT / "DATA" / "ES" / "20260424_ES.jsonl")
    dmp_23 = load_dmp(ROOT / "DATA" / "ES" / "20260423_ES.jsonl")
    dmp = pd.concat([dmp_23, dmp_24], ignore_index=True) if not dmp_23.empty else dmp_24
    print(f"\nDMP loaded: {len(dmp)} bars")
    print(f"  Range: {dmp['ts_utc'].min()} -> {dmp['ts_utc'].max()}")
    print(f"  Sample first bar: ts_ms={dmp['ts_ms'].iloc[0]} ({dmp['ts_utc'].iloc[0]})")
    print(f"                    close={dmp['close'].iloc[0]} hi={dmp['high'].iloc[0]} lo={dmp['low'].iloc[0]} vol={dmp['vol'].iloc[0]}")

    # --- Load DBN 24/04 + 23/04 ---
    p24 = DATABENTO_ROOT / "ohlcv-1m" / "symbol=ES.c.0" / "year=2026" / "month=04" / "day=24" / "data.parquet"
    p23 = DATABENTO_ROOT / "ohlcv-1m" / "symbol=ES.c.0" / "year=2026" / "month=04" / "day=23" / "data.parquet"
    dbn_24 = load_dbn_parquet(p24)
    dbn_23 = load_dbn_parquet(p23)
    dbn = pd.concat([dbn_23, dbn_24]) if not dbn_23.empty else dbn_24
    print(f"\nDBN loaded: {len(dbn)} bars")
    print(f"  Range: {dbn.index.min()} -> {dbn.index.max()}")
    print(f"  Columns: {list(dbn.columns)}")
    if "instrument_id" in dbn.columns:
        unique_ids = dbn["instrument_id"].unique()
        print(f"  instrument_id unique: {unique_ids} (count={len(unique_ids)})")
    print(f"  Sample first bar:")
    print(f"    {dbn.iloc[0].to_dict()}")

    # --- 3 bars investigation ---
    targets = [
        ("Asia",      datetime(2026, 4, 24,  2,  0, 0, tzinfo=timezone.utc)),  # 22:00 ET J-1
        ("RTH-open",  datetime(2026, 4, 24, 13, 30, 0, tzinfo=timezone.utc)),  # 09:30 ET
        ("RTH-close", datetime(2026, 4, 24, 20,  0, 0, tzinfo=timezone.utc)),  # 16:00 ET
    ]

    print("\n" + "=" * 90)
    print(" COMPARAISON 3 BARS")
    print("=" * 90)

    for label, target in targets:
        print(f"\n--- {label} | target UTC: {target} ---")

        # DMP
        dmp_row, dmp_status = find_bar(dmp, target, label)
        # DBN
        if not dbn.empty:
            dbn_row, dbn_status = find_dbn_bar(dbn, target)
        else:
            dbn_row, dbn_status = None, "no_data"

        # Print cote-a-cote
        if dmp_row is not None:
            print(f"  DMP  [{dmp_status:30s}] close={dmp_row['close']:.2f}  hi={dmp_row['high']:.2f}  lo={dmp_row['low']:.2f}  vol={int(dmp_row['vol'])}")
        else:
            print(f"  DMP  [NOT_FOUND]")

        if dbn_row is not None:
            o = dbn_row.get("open", "-")
            h = dbn_row.get("high", "-")
            l = dbn_row.get("low", "-")
            c = dbn_row.get("close", "-")
            v = dbn_row.get("volume", "-")
            print(f"  DBN  [{dbn_status:30s}] open={o:.2f}  hi={h:.2f}  lo={l:.2f}  close={c:.2f}  vol={int(v)}")

        # Convention check : DMP-1min vs DBN
        if dmp_row is not None and dbn_row is not None:
            dmp_minus_1, _ = find_bar(dmp, datetime.fromtimestamp(target.timestamp() - 60, tz=timezone.utc), label)
            if dmp_minus_1 is not None:
                close_match_at_t = abs(dmp_row["close"] - dbn_row.get("close", -1)) <= 0.125
                close_match_dmpminus1 = abs(dmp_minus_1["close"] - dbn_row.get("close", -1)) <= 0.125
                print(f"  Match close (tol 0.125):")
                print(f"    DMP@t == DBN@t      : {'YES' if close_match_at_t else 'NO'}")
                print(f"    DMP@t-1 == DBN@t    : {'YES' if close_match_dmpminus1 else 'NO'}")

    # --- Summary instrument_id ---
    print("\n" + "=" * 90)
    print(" INSTRUMENT_ID DBN sur la journee 24/04")
    print("=" * 90)
    if "instrument_id" in dbn.columns and not dbn_24.empty:
        ids = dbn_24["instrument_id"].value_counts()
        print(f"  {ids.to_dict()}")
        if len(ids) == 1:
            print(f"  ✅ instrument_id stable sur 24/04 (pas de roll intra-day)")
        else:
            print(f"  ⚠️ MULTI instrument_id detectes — possible roll")


if __name__ == "__main__":
    main()
