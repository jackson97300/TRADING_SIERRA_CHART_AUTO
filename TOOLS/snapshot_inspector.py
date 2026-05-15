"""Snapshot Inspector — analyse JSONL produits par MIA-Live-Enricher.

Phase 1 post-R5 (15/05/2026) — outil de verification contenu live_enriched
avant de brancher un bot. Repond a la demande Jackson :
> "on peux commencer a recevoir des snapshots dans des dossiers/fichiers bien
> organises en LIVE des snapshots complet et enrichis avant de brancher sur
> un bot"

Inspecte :
  DATA/live_enriched/{sym_safe}/{YYYYMMDD}.jsonl

Verifications :
  1. Structure fichier (count lignes, taille, parsabilite JSON)
  2. Schema version + n_cols par bar
  3. Coverage features (top features ML-critical presentes)
  4. NaN ratios par feature (detection Pattern V1 dead features)
  5. Comparaison vs V4 batch parquet ground truth (overlap dates)
  6. Heartbeat live_enricher last update

Usage:
  python tools/snapshot_inspector.py --symbol ES.c.0
  python tools/snapshot_inspector.py --symbol ES.c.0 --date 20260515
  python tools/snapshot_inspector.py --all
  python tools/snapshot_inspector.py --compare-v4 --symbol ES.c.0 --date 20260515
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE_ENRICHED_DIR = ROOT / "DATA" / "live_enriched"
HEARTBEAT_FILE = ROOT / "DATA" / "LIVE_CACHE" / "_enricher_heartbeat.json"
V4_BASE = ROOT / "DATA" / "datasets" / "v4_enriched"


# Features ML-critical attendues (subset top SHAP V5 + Pass 4 gates inputs)
ML_CRITICAL_FEATURES = [
    # Game changers (Pattern V1 prone)
    "open_type", "open_zone", "open_direction", "open_bias_conf",
    "day_type", "profile_shape",
    "open_cash", "price_1030",
    # Rolling features (top SHAP)
    "ctx_price_slope_5", "ctx_delta_sum_3", "ctx_vol_z_5",
    "ctx_va_position_velocity",
    # Regime
    "regime_mode", "regime_favor", "regime_actionable",
    # Edge zones / MQ
    "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
    # Phase B+
    "long_up_bar", "long_dn_bar",
    # Intermarket (proxies R1 attendus)
    "diag_imbalance_ofi_proxy", "large_trader_max_size_proxy",
]


def _safe_sym_dir(symbol: str) -> str:
    """ES.c.0 -> ES_c_0."""
    return symbol.replace("/", "_").replace(".", "_")


def list_snapshot_files(symbol: str) -> list[Path]:
    """Liste fichiers JSONL du symbol, tries chronologiquement."""
    sym_dir = LIVE_ENRICHED_DIR / _safe_sym_dir(symbol)
    if not sym_dir.exists():
        return []
    return sorted(sym_dir.glob("*.jsonl"))


def load_jsonl(path: Path) -> pd.DataFrame:
    """Load 1 fichier JSONL en DataFrame, 1 ligne = 1 row."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] {path.name}:{ln} JSON decode fail: {e}")
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def inspect_file(path: Path, symbol: str) -> dict:
    """Inspecte 1 fichier JSONL et retourne un rapport dict."""
    size_mb = path.stat().st_size / (1024 * 1024)
    df = load_jsonl(path)
    n_rows = len(df)
    if n_rows == 0:
        return {
            "path": str(path.name),
            "size_mb": round(size_mb, 3),
            "n_rows": 0,
            "status": "EMPTY",
        }

    n_cols = len(df.columns)
    schemas = df["schema_version"].unique().tolist() if "schema_version" in df.columns else ["?"]

    # ts_event range
    ts_range = "?"
    if "ts_event_ns" in df.columns:
        ts_min_ns = int(df["ts_event_ns"].min())
        ts_max_ns = int(df["ts_event_ns"].max())
        ts_range = (
            f"{datetime.fromtimestamp(ts_min_ns/1e9, tz=timezone.utc).isoformat()} "
            f"-> {datetime.fromtimestamp(ts_max_ns/1e9, tz=timezone.utc).isoformat()}"
        )

    # ML-critical features coverage
    missing_ml = [f for f in ML_CRITICAL_FEATURES if f not in df.columns]
    present_ml = [f for f in ML_CRITICAL_FEATURES if f in df.columns]

    # NaN ratios sur ML-critical
    nan_ratios = {}
    for f in present_ml:
        ratio = df[f].isna().mean() if df[f].dtype.kind in "fc" else (df[f] == 0).mean()
        nan_ratios[f] = round(float(ratio), 3)

    # Dead features (100% NaN ou constantes)
    dead_features = []
    for c in df.columns:
        if df[c].dtype.kind in "fc":
            if df[c].isna().all():
                dead_features.append(f"{c} (100% NaN)")
            elif df[c].nunique(dropna=True) <= 1:
                dead_features.append(f"{c} (constante={df[c].dropna().iloc[0] if len(df[c].dropna()) else 'all_nan'})")

    return {
        "path": str(path.name),
        "size_mb": round(size_mb, 3),
        "n_rows": n_rows,
        "n_cols": n_cols,
        "schemas": schemas,
        "ts_range": ts_range,
        "ml_present": len(present_ml),
        "ml_total": len(ML_CRITICAL_FEATURES),
        "ml_missing": missing_ml,
        "ml_nan_ratios": nan_ratios,
        "dead_features_count": len(dead_features),
        "dead_features_sample": dead_features[:10],
        "status": "OK" if not missing_ml else "INCOMPLETE",
    }


def print_report(rep: dict, verbose: bool = False) -> None:
    """Print rapport formate."""
    print(f"\n=== {rep['path']} ===")
    print(f"  Size : {rep['size_mb']} MB")
    print(f"  Rows : {rep['n_rows']}")
    if rep.get("status") == "EMPTY":
        print(f"  Status : EMPTY (file exists but no JSONL lines)")
        return
    print(f"  Cols : {rep['n_cols']}")
    print(f"  Schema(s) : {rep.get('schemas', [])}")
    print(f"  ts_event range : {rep.get('ts_range', '?')}")
    print(f"  ML-critical features : {rep['ml_present']}/{rep['ml_total']}")
    if rep["ml_missing"]:
        print(f"  Manquantes ({len(rep['ml_missing'])}) :")
        for f in rep["ml_missing"][:10]:
            print(f"    - {f}")
        if len(rep["ml_missing"]) > 10:
            print(f"    ... ({len(rep['ml_missing']) - 10} more)")
    print(f"  Dead features (100% NaN ou constantes) : {rep['dead_features_count']}")
    if verbose and rep["dead_features_sample"]:
        for f in rep["dead_features_sample"]:
            print(f"    - {f}")
    if verbose and rep["ml_nan_ratios"]:
        print(f"  NaN ratios (ML-critical) :")
        for f, r in sorted(rep["ml_nan_ratios"].items(), key=lambda x: -x[1])[:5]:
            print(f"    {f:35s} = {r:.3f}")
    print(f"  Status : {rep['status']}")


def check_heartbeat() -> Optional[dict]:
    """Lit heartbeat.json + retourne age + status."""
    if not HEARTBEAT_FILE.exists():
        return None
    try:
        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
            hb = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    last_iso = hb.get("last_heartbeat_iso", "")
    if last_iso:
        try:
            last_ts = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_sec = (now - last_ts).total_seconds()
            hb["age_sec"] = round(age_sec, 1)
            hb["alive"] = age_sec < 120  # 2 min tolerance
        except (ValueError, TypeError):
            pass
    return hb


def compare_vs_v4(symbol: str, date_str: str, jsonl_df: pd.DataFrame) -> dict:
    """Compare JSONL live vs V4 batch parquet pour les bars qui chevauchent."""
    year = int(date_str[:4])
    month = int(date_str[4:6])
    v4_path = V4_BASE / f"symbol={symbol}" / f"year={year}" / f"month={month:02d}" / "data.parquet"
    if not v4_path.exists():
        return {"status": "V4_PARQUET_ABSENT", "path": str(v4_path)}

    df_v4 = pd.read_parquet(v4_path)
    df_v4["ts_event"] = pd.to_datetime(df_v4["ts_event"], utc=True)

    # ts_event live
    if "ts_event_ns" not in jsonl_df.columns:
        return {"status": "NO_TS_EVENT_NS"}
    jsonl_df = jsonl_df.copy()
    jsonl_df["ts_event"] = pd.to_datetime(jsonl_df["ts_event_ns"], unit="ns", utc=True)

    # Inner join sur ts_event
    merged = jsonl_df.merge(
        df_v4, on="ts_event", how="inner", suffixes=("_live", "_v4")
    )
    n_overlap = len(merged)
    if n_overlap == 0:
        return {"status": "NO_OVERLAP", "n_live": len(jsonl_df), "n_v4": len(df_v4)}

    # Compare ML-critical features
    drifts = []
    for f in ML_CRITICAL_FEATURES:
        live_col = f"{f}_live"
        v4_col = f"{f}_v4"
        if live_col not in merged.columns or v4_col not in merged.columns:
            # Maybe present sans suffix
            if f in merged.columns:
                continue
            drifts.append({"feature": f, "status": "MISSING_LIVE_OR_V4"})
            continue
        try:
            b = merged[v4_col].astype("float64").values
            s = merged[live_col].astype("float64").values
            diff = np.abs(b - s)
            max_diff = float(np.nanmax(diff))
            n_diff = int((diff > 1e-6).sum())
            if max_diff > 1e-6:
                drifts.append({
                    "feature": f,
                    "max_diff": max_diff,
                    "n_diff": n_diff,
                    "pct_diff": round(100.0 * n_diff / n_overlap, 1),
                })
        except (ValueError, TypeError):
            drifts.append({"feature": f, "status": "DTYPE_ERROR"})

    return {
        "status": "OK",
        "n_overlap": n_overlap,
        "n_drifts": len(drifts),
        "drifts": drifts[:20],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", help="ES.c.0 / NQ.c.0 / MGC.v.0", default="ES.c.0")
    ap.add_argument("--date", help="YYYYMMDD (default: tous fichiers)")
    ap.add_argument("--all", action="store_true", help="Scan tous symbols")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--compare-v4", action="store_true", help="Compare vs V4 batch parquet")
    args = ap.parse_args()

    print("=" * 70)
    print(" MIA Live Enricher — Snapshot Inspector")
    print(f" Dir : {LIVE_ENRICHED_DIR}")
    print("=" * 70)

    # Heartbeat
    hb = check_heartbeat()
    if hb:
        alive = "ALIVE" if hb.get("alive") else "DEAD"
        age = hb.get("age_sec", "?")
        print(f"\nHeartbeat : {alive} (age={age}s)")
        print(f"  service : {hb.get('service', '?')}")
        print(f"  uptime  : {hb.get('uptime_sec', 0):.0f}s")
        print(f"  bars    : {hb.get('n_bars_processed', {})}")
        print(f"  failed  : {hb.get('n_bars_failed', {})}")
    else:
        print(f"\nHeartbeat : ABSENT ({HEARTBEAT_FILE})")
        print(f"  -> live_enricher jamais demarre ou heartbeat thread off.")

    # Symbols a scanner
    if args.all:
        if not LIVE_ENRICHED_DIR.exists():
            print(f"\n[WARN] {LIVE_ENRICHED_DIR} absent")
            sys.exit(1)
        symbols_dirs = [d for d in LIVE_ENRICHED_DIR.iterdir() if d.is_dir()]
        symbols = [d.name.replace("_", ".").replace("c.0", "c.0") for d in symbols_dirs]
    else:
        symbols = [args.symbol]

    grand_total_rows = 0
    grand_total_files = 0
    for sym in symbols:
        files = list_snapshot_files(sym)
        if args.date:
            files = [f for f in files if args.date in f.name]
        if not files:
            print(f"\n[{sym}] Aucun fichier JSONL")
            continue
        print(f"\n[{sym}] {len(files)} fichier(s)")
        for fp in files:
            rep = inspect_file(fp, sym)
            print_report(rep, verbose=args.verbose)
            grand_total_rows += rep.get("n_rows", 0)
            grand_total_files += 1

            # Comparaison V4 batch
            if args.compare_v4 and rep.get("n_rows", 0) > 0:
                date_str = fp.stem
                df_live = load_jsonl(fp)
                cmp = compare_vs_v4(sym, date_str, df_live)
                print(f"\n  [V4 COMPARE] {sym} {date_str}")
                print(f"    Status : {cmp['status']}")
                if cmp["status"] == "OK":
                    print(f"    Overlap : {cmp['n_overlap']} bars / drifts : {cmp['n_drifts']}")
                    if cmp["drifts"]:
                        for d in cmp["drifts"][:5]:
                            print(f"      - {d}")

    print(f"\n=== SUMMARY ===")
    print(f"  Files inspected : {grand_total_files}")
    print(f"  Total rows     : {grand_total_rows}")


if __name__ == "__main__":
    main()
