"""Pull Databento ohlcv-1m pour symboles Gold-relevant + sauvegarde Hive partitioned.

Mission Phase B (12/05/2026) — enrichir dataset Gold avec features state-of-the-art.

Symboles pulled :
  - 6E.c.0  : Euro/USD futures → proxy DXY (corr -0.45)
  - ZN.c.0  : 10-yr Treasury futures → real yields proxy (corr -0.85)
  - ZB.c.0  : 30-yr Treasury futures → long-end yields
  - SI.c.0  : Silver futures → Gold/Silver ratio (mean reversion edge)
  - HG.c.0  : Copper futures → Copper/Gold ratio (risk-on/off)
  - CL.c.0  : Crude Oil futures → Oil/Gold ratio (inflation proxy)
  - MGC.v.0 : Micro Gold update (24/04 → 12/05, 19 jours manquants)

Output : DATA/databento/GLBX.MDP3/ohlcv-1m/symbol={ticker}/year=YYYY/month=MM/data.parquet
         (Hive partitioned, compatible load_ohlcv_databento existant)

Anti-pattern évité : pas de recharge si data déjà locale (incrémental).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Load .env (fix portabilité D:/ vs C:/)
def load_env():
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [repo_root / ".env", Path("C:/TRADING_SIERRA_CHART_AUTO/.env")]
    for fp in candidates:
        if fp.exists():
            for line in fp.read_text().split("\n"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return fp
    return None

env_loaded = load_env()
print(f"Loaded .env from : {env_loaded}")

api_key = os.environ.get("DATABENTO_API_KEY")
if not api_key:
    print("ERROR: no DATABENTO_API_KEY found")
    sys.exit(1)
print(f"API key loaded: {api_key[:8]}...{api_key[-4:]}")

import databento as db
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
OHLCV_ROOT = REPO_ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"
OHLCV_ROOT.mkdir(parents=True, exist_ok=True)

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"
STYPE_IN = "continuous"

# Symboles à pull (Gold-relevant)
SYMBOLS_TO_PULL = {
    "6E.c.0":  "Euro/USD futures (proxy DXY corr -0.45)",
    "ZN.c.0":  "10-yr Treasury futures (real yields corr -0.85)",
    "ZB.c.0":  "30-yr Treasury futures (long-end yields)",
    "SI.c.0":  "Silver futures (Gold/Silver ratio mean rev)",
    "HG.c.0":  "Copper futures (Copper/Gold ratio risk-on/off)",
    "CL.c.0":  "Crude Oil futures (Oil/Gold inflation proxy)",
    "MGC.v.0": "Micro Gold update 24/04 -> 12/05",
}

# Range historique 12 mois
RANGE_START = date(2025, 5, 1)
RANGE_END = date(2026, 5, 12)   # Databento data jusqu'au 12/05 10:20 UTC


def save_hive_partitioned(df: pd.DataFrame, symbol: str):
    """Sauvegarde Hive : symbol=X/year=Y/month=M/data.parquet."""
    if df.empty:
        return 0
    df = df.copy()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df["_year"] = df["ts_event"].dt.year
    df["_month"] = df["ts_event"].dt.month

    n_files = 0
    for (year, month), sub in df.groupby(["_year", "_month"]):
        out_dir = OHLCV_ROOT / f"symbol={symbol}" / f"year={year}" / f"month={month:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "data.parquet"
        sub_clean = sub.drop(columns=["_year", "_month"])
        # ts_event sans tz pour DuckDB compatibility
        sub_clean["ts_event"] = sub_clean["ts_event"].dt.tz_localize(None)
        sub_clean.to_parquet(out_file, index=False)
        n_files += 1
    return n_files


def pull_symbol(client, symbol, start, end):
    """Pull 1 symbol depuis Databento. Retourne DataFrame."""
    try:
        data = client.timeseries.get_range(
            dataset=DATASET, symbols=[symbol], schema=SCHEMA,
            start=start.isoformat(), end=end.isoformat(),
            stype_in=STYPE_IN,
        )
        df = data.to_df()
        return df
    except Exception as e:
        print(f"    ERROR: {str(e)[:150]}")
        return pd.DataFrame()


def main():
    print(f"\n=== PULL DATABENTO GOLD AUXILIARY ===\n")
    print(f"  Dataset : {DATASET}, schema : {SCHEMA}")
    print(f"  Range : {RANGE_START} -> {RANGE_END}")
    print(f"  Output Hive root : {OHLCV_ROOT}")
    print(f"  Symbols : {len(SYMBOLS_TO_PULL)}")
    print()

    client = db.Historical(api_key)
    summary = {}

    for sym, desc in SYMBOLS_TO_PULL.items():
        print(f"\n--- {sym} : {desc}")
        # Check si déjà partiellement pulled
        sym_dir = OHLCV_ROOT / f"symbol={sym}"
        existing_files = list(sym_dir.rglob("*.parquet")) if sym_dir.exists() else []
        if existing_files:
            print(f"    Existant : {len(existing_files)} fichiers parquet déjà locaux")
            # Vérifier si couverture complète
            existing_df = pd.concat([pd.read_parquet(f) for f in existing_files], ignore_index=True)
            existing_df["ts_event"] = pd.to_datetime(existing_df["ts_event"], utc=True, errors="coerce")
            ex_min = existing_df["ts_event"].min()
            ex_max = existing_df["ts_event"].max()
            print(f"    Range existant : {ex_min} -> {ex_max}")
            # Pull seulement le delta (ex_max + 1 -> RANGE_END)
            pull_start = ex_max.date() + timedelta(days=1) if ex_max is not pd.NaT else RANGE_START
            if pull_start >= RANGE_END:
                print(f"    Skip : déjà à jour")
                summary[sym] = {"status": "SKIP", "n_bars": 0, "n_files": 0}
                continue
            print(f"    Pull delta : {pull_start} -> {RANGE_END}")
            start_iter = pull_start
        else:
            start_iter = RANGE_START

        # Pull (Databento accepte ranges larges, mais limiter à 60j par chunk pour stabilité)
        all_chunks = []
        chunk_size = timedelta(days=60)
        cur = start_iter
        while cur < RANGE_END:
            chunk_end = min(cur + chunk_size, RANGE_END)
            print(f"    Pulling {cur} -> {chunk_end}...")
            df_chunk = pull_symbol(client, sym, cur, chunk_end)
            if not df_chunk.empty:
                all_chunks.append(df_chunk)
                print(f"      OK : {len(df_chunk):,} bars")
            else:
                print(f"      EMPTY ou ERROR")
            cur = chunk_end

        if not all_chunks:
            summary[sym] = {"status": "FAIL", "n_bars": 0, "n_files": 0}
            continue

        # Databento to_df() retourne ts_event comme INDEX → reset_index inconditionnel
        # Note : ignore_index=True dans concat = perd index, donc reset_index AVANT concat
        all_chunks_reset = []
        for chunk in all_chunks:
            if "ts_event" not in chunk.columns:
                chunk = chunk.reset_index()
            all_chunks_reset.append(chunk)
        df_full = pd.concat(all_chunks_reset, ignore_index=True)
        if "ts_event" not in df_full.columns:
            print(f"    WARN : ts_event missing after concat, cols={list(df_full.columns)[:5]}")
            continue
        df_full = df_full.drop_duplicates(subset=["ts_event"]).sort_values("ts_event")
        print(f"    Total pulled : {len(df_full):,} bars")

        # Save Hive partitioned
        n_files = save_hive_partitioned(df_full, sym)
        print(f"    Saved : {n_files} fichiers parquet (Hive year=*/month=*)")
        summary[sym] = {"status": "OK", "n_bars": len(df_full), "n_files": n_files}

    # Final summary
    print(f"\n\n=== SUMMARY PULL DATABENTO ===")
    for sym, s in summary.items():
        print(f"  {sym:10s} {s['status']:6s} bars={s['n_bars']:>10,}  files={s['n_files']}")


if __name__ == "__main__":
    main()
