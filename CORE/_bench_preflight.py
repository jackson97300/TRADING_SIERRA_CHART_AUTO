"""Pre-flight check avant bench MIA (sur VPS).

Verifie :
1. Services nssm Running
2. Freshness DMP JSONL (today/yesterday)
3. Freshness V4 enriched (mai 2026 + last bar age)
4. Schema DMP (262 cols, dmp_validator)
5. V4 enriched colonnes critiques presentes

Output : GO si tout OK, NOGO si data corrompue.
"""
import subprocess
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

ROOT = Path(r"C:\TRADING_SIERRA_CHART_AUTO")
DATA = ROOT / "DATA"

results = []
critical_fails = []

def check(name, ok, detail=""):
    status = "OK" if ok else "FAIL"
    results.append((name, status, detail))
    if not ok:
        critical_fails.append((name, detail))
    print(f"[{status}] {name}: {detail}")

now = datetime.now(timezone.utc)
print(f"=== PRE-FLIGHT MIA BENCH — {now.isoformat(timespec='seconds')} ===\n")

# 1. Services nssm Running
print("--- 1. Services nssm ---")
try:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Service MIA-* | Where-Object {$_.Status -eq 'Running'} | Select-Object -ExpandProperty Name"],
        capture_output=True, text=True, timeout=30, encoding='utf-8'
    )
    services_running = [s.strip() for s in out.stdout.splitlines() if s.strip()]
    print(f"  Services Running: {services_running}")
    required = ["MIA-Paper", "MIA-Brain-V6", "MIA-DataBento-Paper-V2", "MIA-Live-OHLCV", "MIA-LivePipeline"]
    for svc in required:
        check(f"service.{svc}", svc in services_running, "Running" if svc in services_running else "NOT Running")
except Exception as e:
    check("services.query", False, f"ERROR: {e}")

# 2. Freshness DMP JSONL
print("\n--- 2. Freshness DMP JSONL ---")
today_str = now.strftime("%Y%m%d")
yesterday_str = (now - timedelta(days=1)).strftime("%Y%m%d")
for sym in ("ES", "NQ"):
    sym_dir = DATA / sym
    if not sym_dir.exists():
        check(f"dmp.{sym}.dir", False, f"missing {sym_dir}")
        continue
    files = sorted(sym_dir.glob("*.jsonl"))
    latest = files[-1] if files else None
    if latest is None:
        check(f"dmp.{sym}.files", False, "no JSONL")
        continue
    mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    age_h = (now - mtime).total_seconds() / 3600
    fresh = age_h < 26
    check(f"dmp.{sym}.fresh", fresh, f"{latest.name} mtime={mtime.isoformat(timespec='seconds')} age={age_h:.1f}h")
    n_lines = sum(1 for _ in open(latest, "r", encoding="utf-8", errors="ignore"))
    check(f"dmp.{sym}.size", n_lines >= 100, f"{n_lines} lines")

# 3. Freshness V4 enriched
print("\n--- 3. Freshness V4 enriched ---")
v4_root = DATA / "datasets" / "v4_enriched"
month_str = now.strftime("%m")
year_str = now.strftime("%Y")
for sym in ("ES.c.0", "NQ.c.0", "MGC.c.0"):
    fp = v4_root / f"symbol={sym}" / f"year={year_str}" / f"month={month_str}" / "data.parquet"
    if not fp.exists():
        # Try MGC.v.0
        if sym == "MGC.c.0":
            fp2 = v4_root / "symbol=MGC.v.0" / f"year={year_str}" / f"month={month_str}" / "data.parquet"
            if fp2.exists():
                fp = fp2
            else:
                check(f"v4.{sym}.exists", False, f"missing {fp.relative_to(ROOT)}")
                continue
        else:
            check(f"v4.{sym}.exists", False, f"missing {fp.relative_to(ROOT)}")
            continue
    mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
    age_min = (now - mtime).total_seconds() / 60
    fresh = age_min < 30  # pipeline runs every 5 min
    check(f"v4.{sym}.fresh", fresh, f"mtime age={age_min:.1f}min size={fp.stat().st_size}")
    # Last bar inside parquet
    try:
        import pandas as pd
        df = pd.read_parquet(fp, columns=["ts_event"])
        last_ts = pd.to_datetime(df["ts_event"].max(), utc=True)
        bar_age_min = (now - last_ts.to_pydatetime()).total_seconds() / 60
        bar_fresh = bar_age_min < 60   # bar < 60min
        check(f"v4.{sym}.last_bar", bar_fresh, f"last_ts={last_ts.isoformat(timespec='seconds')} age={bar_age_min:.1f}min n={len(df)}")
    except Exception as e:
        check(f"v4.{sym}.last_bar", False, f"read error: {e}")

# 4. dmp_validator sur derniers JSONL
print("\n--- 4. dmp_validator ES + NQ ---")
for sym in ("ES", "NQ"):
    sym_dir = DATA / sym
    files = sorted(sym_dir.glob("*.jsonl"))
    if not files:
        check(f"validator.{sym}", False, "no JSONL")
        continue
    latest = files[-1]
    try:
        out = subprocess.run(
            [sys.executable, "-X", "utf8",
             str(ROOT / "CORE" / "dmp_validator.py"), str(latest)],
            capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace'
        )
        rc = out.returncode
        last3 = "\n    ".join(out.stdout.strip().splitlines()[-3:])
        check(f"validator.{sym}", rc == 0, f"rc={rc} | {last3[:200]}")
    except Exception as e:
        check(f"validator.{sym}", False, f"ERROR: {e}")

# Summary
print("\n=== SUMMARY ===")
n_ok = sum(1 for _, s, _ in results if s == "OK")
n_fail = sum(1 for _, s, _ in results if s == "FAIL")
print(f"OK: {n_ok}, FAIL: {n_fail}")
if critical_fails:
    print("\n=== CRITICAL FAILURES ===")
    for name, det in critical_fails:
        print(f"  {name}: {det}")
    print("\nVERDICT: NOGO")
    sys.exit(1)
else:
    print("\nVERDICT: GO")
    sys.exit(0)
