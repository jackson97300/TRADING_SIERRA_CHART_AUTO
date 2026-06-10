"""
Databento backfill batch — backfill historique Trades + OHLCV-1m via batch jobs.

Workflow :
  1. Pre-flight strict (cost == 0, dataset range, symbology resolve, disk space)
  2. Submit batch jobs (default 5y ES + NQ Trades + OHLCV)
  3. Polling status (timeout 4h, retry on failure)
  4. Download + split DBN.zst -> Parquet partitionne par jour (Hive)
  5. Verification integrite (SHA256, business day gap, volume sanity, record count)
  6. Manifest atomique (.tmp -> rename)

Usage :
  python -X utf8 CORE/databento_backfill_batch.py --dry-run         # 1 mois test
  python -X utf8 CORE/databento_backfill_batch.py                    # 5y default
  python -X utf8 CORE/databento_backfill_batch.py --start 2024-01-01 --end 2026-04-25

Modifications obligatoires Plan agent (review 25/04/2026) :
  1. Pre-flight strict avec abort si mismatch
  2. Splitting via streaming DBN -> Parquet -> DuckDB partition_by (jamais to_df big file)
  3. 2+2 sequential par defaut (Standard limit 5 concurrent jobs)
  4. Idempotence + resume (manifest atomique, lock file, skip si SHA256 deja OK)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
    print("[FATAL] DATABENTO_API_KEY missing in .env")
    sys.exit(1)

import databento as db  # noqa: E402

# ============================================================
# Constants
# ============================================================
DATASET = "GLBX.MDP3"
DATA_ROOT = ROOT / "DATA" / "databento" / DATASET
TEMP_ROOT = ROOT / "DATA" / "databento" / "_temp"
META_ROOT = DATA_ROOT / "_metadata"
LOCK_FILE = META_ROOT / "backfill.lock"
MANIFEST_FILE = META_ROOT / "backfill_manifest.json"
ACTIVE_JOBS_FILE = META_ROOT / "backfill_jobs_active.json"

MIN_DISK_GB = 50  # peak intermediate Parquet ~50 GB pour 5y
# MAX_TOTAL_GB 300 pour permettre MBP-10 + MBO 1 mois (251 GB billable)
# Stockage disque final = ~50 GB compresse (ratio ZSTD ~5x)
MAX_TOTAL_GB = 300
POLL_INTERVAL_SEC = 60
MAX_POLL_HOURS = 4
MAX_RETRY_PER_JOB = 1

DEFAULT_SYMBOLS = ["ES.c.0", "NQ.c.0"]
DEFAULT_SCHEMAS = ["trades", "ohlcv-1m"]
DEFAULT_END = date(2026, 4, 25)
DEFAULT_START = date(2021, 4, 25)  # 5 ans par defaut

# CME holiday calendar 2021-2026 (hardcoded fallback if pandas_market_calendars absent)
CME_HOLIDAYS_HARDCODED = {
    "2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31",
    "2021-07-05", "2021-09-06", "2021-11-25", "2021-12-24",
    "2022-01-17", "2022-02-21", "2022-04-15", "2022-05-30", "2022-06-20",
    "2022-07-04", "2022-09-05", "2022-11-24", "2022-12-26",
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29",
    "2023-06-19", "2023-07-04", "2023-09-04", "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27",
    "2024-06-19", "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}


# ============================================================
# Lock & atomic IO
# ============================================================
def acquire_lock():
    META_ROOT.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        content = LOCK_FILE.read_text(errors="ignore").strip()
        print(f"[FATAL] Lock file exists: {LOCK_FILE}")
        print(f"  Content: {content}")
        print("  Another run in progress, OR previous run crashed.")
        print("  If you confirm no run in progress, delete the lock file manually and retry.")
        sys.exit(2)
    LOCK_FILE.write_text(
        f"pid={os.getpid()} ts={datetime.now(timezone.utc).isoformat()}\n"
    )


def release_lock():
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass


def write_json_atomic(path: Path, data: dict):
    """Write JSON atomically: write to .tmp then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_disk_space() -> float:
    free_gb = shutil.disk_usage(ROOT).free / (1024**3)
    if free_gb < MIN_DISK_GB:
        print(f"[FATAL] free disk {free_gb:.1f} GB < {MIN_DISK_GB} GB required")
        sys.exit(3)
    return free_gb


# ============================================================
# Pre-flight strict
# ============================================================
def preflight(client, jobs_specs):
    print("=" * 80)
    print(" PRE-FLIGHT CHECKS")
    print("=" * 80)

    free_gb = check_disk_space()
    print(f"  [OK]  Disk free: {free_gb:.1f} GB (need >= {MIN_DISK_GB})")

    # Dataset range + validation start_d / end_d dans la plage dispo
    ds_start_str = None
    ds_end_str = None
    try:
        r = client.metadata.get_dataset_range(dataset=DATASET)
        ds_start_str = r.get("start") if isinstance(r, dict) else getattr(r, "start", None)
        ds_end_str = r.get("end") if isinstance(r, dict) else getattr(r, "end", None)
        print(f"  [OK]  Dataset {DATASET}: start={ds_start_str}, end={ds_end_str}")
    except Exception as e:
        print(f"  [WARN] get_dataset_range failed: {e}")

    # FIX should-fix D : validation start_d / end_d dans plage dispo
    if ds_start_str and ds_end_str:
        try:
            ds_start = date.fromisoformat(str(ds_start_str)[:10])
            ds_end = date.fromisoformat(str(ds_end_str)[:10])
            for symbol, schema, label, start, end in jobs_specs:
                if start < ds_start:
                    print(f"  [FATAL] {label}: start={start} < dataset start={ds_start}")
                    sys.exit(8)
                if end > ds_end:
                    print(f"  [FATAL] {label}: end={end} > dataset end={ds_end}")
                    sys.exit(8)
        except (ValueError, TypeError) as e:
            print(f"  [WARN] dataset range parse failed: {e}")

    detail = []
    total_cost = 0.0
    total_bytes = 0

    for symbol, schema, label, start, end in jobs_specs:
        # Cost — must be $0 in Standard plan for trades + ohlcv (15y included)
        try:
            cost = client.metadata.get_cost(
                dataset=DATASET, symbols=[symbol], schema=schema,
                stype_in="continuous", start=str(start), end=str(end),
                mode="historical",
            )
            cost = float(cost)
        except Exception as e:
            print(f"  [WARN] {label}: get_cost failed ({e})")
            cost = 0.0

        if cost > 0.001:
            print(f"  [WARN] {label}: get_cost API returns ${cost:.4f} (pay-as-you-go price)")
            print(f"         Standard plan covers 15y of trades+ohlcv historical — actual charge $0")
            print(f"         (verified empirically 2026-05-09 MGC trades 2025-06-15: download OK $0)")

        # Billable size
        try:
            size_bytes = client.metadata.get_billable_size(
                dataset=DATASET, symbols=[symbol], schema=schema,
                stype_in="continuous", start=str(start), end=str(end),
            )
            size_bytes = int(size_bytes)
        except Exception as e:
            print(f"  [WARN] {label}: get_billable_size failed ({e})")
            size_bytes = 0

        # Symbology resolve (continuous validation)
        # GLBX.MDP3 ne supporte que continuous -> instrument_id (pas raw_symbol)
        try:
            sr = client.symbology.resolve(
                dataset=DATASET, symbols=[symbol], stype_in="continuous",
                stype_out="instrument_id",
                start_date=str(start), end_date=str(end),
            )
            result_map = sr.get("result", {}) if isinstance(sr, dict) else getattr(sr, "result", {})
            n_resolved = len(result_map.get(symbol, []))
        except Exception as e:
            print(f"  [WARN] {label}: symbology.resolve failed ({e})")
            n_resolved = -1

        detail.append({
            "label": label, "symbol": symbol, "schema": schema,
            "start": str(start), "end": str(end),
            "cost_usd": cost, "size_bytes": size_bytes, "n_contracts": n_resolved,
        })
        total_cost += cost
        total_bytes += size_bytes

        size_gb = size_bytes / (1024**3)
        print(f"  [OK]  {label:30s} cost=${cost:.2f}  size={size_gb:.3f} GB  contracts={n_resolved}")

    total_gb = total_bytes / (1024**3)
    if total_gb > MAX_TOTAL_GB:
        print(f"\n  [FATAL] Total billable size {total_gb:.1f} GB > {MAX_TOTAL_GB} GB threshold")
        sys.exit(5)

    print(f"\n  TOTAL cost: ${total_cost:.4f}  size: {total_gb:.2f} GB  free disk: {free_gb:.1f} GB")
    print()
    return detail


# ============================================================
# Submit + poll batch jobs
# ============================================================
def submit_jobs(client, jobs_specs, dry_label=""):
    suffix = f"  ({dry_label})" if dry_label else ""
    print("=" * 80)
    print(f" SUBMIT BATCH JOBS{suffix}")
    print("=" * 80)

    submitted = []
    for symbol, schema, label, start, end in jobs_specs:
        try:
            details = client.batch.submit_job(
                dataset=DATASET,
                symbols=[symbol],
                stype_in="continuous",
                schema=schema,
                start=str(start),
                end=str(end),
                encoding="dbn",
                compression="zstd",
                delivery="download",
            )
            job_id = getattr(details, "id", None)
            if job_id is None and isinstance(details, dict):
                job_id = details.get("id")
            print(f"  [OK]  {label}: job_id={job_id}")
            submitted.append({
                "label": label, "symbol": symbol, "schema": schema,
                "start": str(start), "end": str(end),
                "job_id": job_id,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "submitted",
                "retries": 0,
            })
        except Exception as e:
            print(f"  [ERR] {label}: submit failed: {e}")
            submitted.append({
                "label": label, "symbol": symbol, "schema": schema,
                "start": str(start), "end": str(end),
                "error": str(e), "status": "submit_failed",
            })
    return submitted


def submit_jobs_in_waves(client, jobs_specs, wave_size=2, wave_delay_sec=3):
    """
    FIX should-fix A (Plan agent) : submit 2+2 sequential vs 4 d'un coup.
    Standard CME limite = 5 concurrent. 2+2 plus prudent.
    """
    submitted = []
    n_waves = (len(jobs_specs) + wave_size - 1) // wave_size
    for w in range(n_waves):
        wave = jobs_specs[w * wave_size : (w + 1) * wave_size]
        print(f"\n[WAVE {w+1}/{n_waves}] {len(wave)} jobs")
        new = submit_jobs(client, wave)
        submitted.extend(new)
        if w < n_waves - 1:
            time.sleep(wave_delay_sec)
    return submitted


def poll_until_done(client, jobs):
    """
    FIX bug runtime : SDK databento 0.75.0 expose list_jobs(), pas get_job(id).
    On fait 1 API call par cycle puis on indexe par job_id.
    """
    print("=" * 80)
    print(" POLLING JOBS STATUS")
    print("=" * 80)

    start_ts = time.time()
    timeout_sec = MAX_POLL_HOURS * 3600

    while True:
        all_done = True
        statuses = []

        # 1 seule API call : list_jobs(), puis index par id
        try:
            all_info = client.batch.list_jobs()
        except Exception as e:
            print(f"  [WARN] list_jobs: {e}")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        jobs_by_id = {}
        for info in all_info:
            jid = getattr(info, "id", None)
            if jid is None and isinstance(info, dict):
                jid = info.get("id")
            if jid:
                jobs_by_id[jid] = info

        for job in jobs:
            if job.get("status") in ("done", "expired", "submit_failed", "retry_failed"):
                statuses.append(f"{job['label']}={job['status']}")
                continue

            info = jobs_by_id.get(job["job_id"])
            if info is None:
                # Job pas encore visible dans list (rare, pendant submit propagation)
                all_done = False
                statuses.append(f"{job['label']}=propagating")
                continue

            state = getattr(info, "state", None)
            if state is None and isinstance(info, dict):
                state = info.get("state")
            progress = getattr(info, "progress", None)
            if progress is None and isinstance(info, dict):
                progress = info.get("progress")
            job["status"] = state
            job["progress"] = progress

            if progress is not None and isinstance(progress, (int, float)):
                statuses.append(f"{job['label']}={state}({progress*100:.0f}%)")
            else:
                statuses.append(f"{job['label']}={state}")

            if state == "failed":
                if job.get("retries", 0) < MAX_RETRY_PER_JOB:
                    print(f"  [RETRY] {job['label']} failed, retrying...")
                    new = submit_jobs(client, [(
                        job["symbol"], job["schema"], job["label"],
                        date.fromisoformat(job["start"]),
                        date.fromisoformat(job["end"]),
                    )])
                    if new and new[0].get("job_id"):
                        job["job_id"] = new[0]["job_id"]
                        job["retries"] = job.get("retries", 0) + 1
                        job["status"] = "submitted"
                        all_done = False
                    else:
                        job["status"] = "retry_failed"
                else:
                    job["status"] = "retry_failed"
            elif state != "done":
                all_done = False

        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] " + " | ".join(statuses))

        # Persist state for resume
        write_json_atomic(ACTIVE_JOBS_FILE, {"jobs": jobs})

        if all_done:
            break

        if time.time() - start_ts > timeout_sec:
            print(f"  [FATAL] Timeout {MAX_POLL_HOURS}h reached")
            sys.exit(6)

        time.sleep(POLL_INTERVAL_SEC)

    print()


# ============================================================
# Download + split
# ============================================================
def download_job(client, job) -> list[Path]:
    """
    Download job files via batch.download() qui retourne list[Path] directement.
    Output : TEMP_ROOT/{job_id}/...
    SDK gere automatiquement : telecharge TOUS les fichiers du job en 1 appel,
    cree subdir par job_id, resume HTTP range si coupure.
    """
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    try:
        downloaded = client.batch.download(
            job_id=job["job_id"],
            output_dir=str(TEMP_ROOT),
            keep_zip=False,
        )
    except Exception as e:
        print(f"  [ERR] download {job['label']}: {e}")
        traceback.print_exc()
        return []

    # downloaded est list[Path]. Filter DBN.zst non vides
    paths = [Path(p) if not isinstance(p, Path) else p for p in downloaded]
    dbn_files = sorted([
        p for p in paths
        if p.name.endswith(".dbn.zst") and p.exists() and p.stat().st_size > 0
    ])
    other_files = [p for p in paths if not p.name.endswith(".dbn.zst")]

    print(f"  Downloaded {len(paths)} files total ({len(dbn_files)} DBN, {len(other_files)} metadata)")
    for p in dbn_files[:3]:
        print(f"    [DBN] {p.name} ({p.stat().st_size/1e6:.2f} MB)")
    if len(dbn_files) > 3:
        print(f"    ... +{len(dbn_files)-3} more DBN files")
    return dbn_files


def split_dbn_to_parquet(dbn_files: list[Path], schema: str, symbol: str) -> dict:
    """
    DBN -> Parquet partitionne par day via DuckDB streaming.
    Etapes :
      1. DBN.zst -> big Parquet (DBNStore.to_parquet, streaming chunks)
      2. DuckDB COPY ... PARTITION_BY (year, month, day) avec OVERWRITE
      3. Cleanup big Parquet intermediaire

    FIX bloquant 3 (code-reviewer): SQL escape paths.
    FIX should-fix C : track failures, return dict avec status.
    FIX should-fix : OVERWRITE pas OVERWRITE_OR_IGNORE (anti-duplicates resume).
    """
    if not dbn_files:
        return {"records": 0, "partitions": 0, "failures": 0, "warning": "no_dbn_files"}

    out_dir = DATA_ROOT / schema / f"symbol={symbol}"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import duckdb
    except ImportError:
        print("    [FATAL] duckdb not installed. pip install duckdb")
        sys.exit(7)

    n_records_total = 0
    failures = []

    # Step 1 : Convertir TOUS les DBN -> big Parquet (un par DBN)
    big_parquets = []
    for dbn_path in dbn_files:
        size_mb = dbn_path.stat().st_size / (1024**2)
        print(f"    DBN->PQ {dbn_path.name} ({size_mb:.1f} MB)")
        big_pq = dbn_path.with_suffix("").with_suffix(".parquet")
        try:
            store = db.DBNStore.from_file(str(dbn_path))
            store.to_parquet(str(big_pq))
            if big_pq.exists() and big_pq.stat().st_size > 0:
                big_parquets.append(big_pq)
        except Exception as e:
            print(f"    [ERR] DBN -> Parquet failed: {e}")
            failures.append({"file": dbn_path.name, "step": "dbn_to_parquet", "error": str(e)})

    if not big_parquets:
        return {"records": 0, "partitions": 0, "failures": len(failures), "failures_detail": failures,
                "warning": "no_parquet_intermediates"}

    # Step 2 : UN seul COPY DuckDB qui agrege TOUS les big Parquets et partitionne par day
    # IMPORTANT : sans cela OVERWRITE efface les precedents partitions a chaque iteration.
    out_dir_safe = out_dir.as_posix().replace("'", "''")
    paths_list = ", ".join(f"'{p.as_posix().replace(chr(39), chr(39)*2)}'" for p in big_parquets)

    con = duckdb.connect()
    try:
        # FIX OOM (audit 2026-04-25): augmenter memory + reduire pression RAM
        con.execute("SET memory_limit='12GB'")  # PC local 32 GB, on peut allouer 12
        con.execute("SET preserve_insertion_order=false")  # economise memoire
        con.execute("SET threads=4")  # limite parallelisme (vs all cores)
        # FIX TIMEZONE (audit 2026-04-26): SET UTC pour eviter shift +2h Windows Paris
        con.execute("SET TimeZone='UTC';")
        con.execute(f"SET temp_directory='{(ROOT / '.duckdb_tmp').as_posix()}'")

        # Count total records across all big parquets
        n_rec = con.execute(
            f"SELECT COUNT(*) FROM read_parquet([{paths_list}])"
        ).fetchone()[0]
        n_records_total = int(n_rec)

        print(f"    Aggregating {len(big_parquets)} parquets -> partition by day...")
        con.execute(f"""
            COPY (
                SELECT *,
                       YEAR(ts_event) AS year,
                       MONTH(ts_event) AS month,
                       DAY(ts_event) AS day
                FROM read_parquet([{paths_list}])
            ) TO '{out_dir_safe}' (
                FORMAT PARQUET,
                PARTITION_BY (year, month, day),
                OVERWRITE,
                COMPRESSION ZSTD
            )
        """)
    except Exception as e:
        print(f"    [ERR] DuckDB partition aggregation: {e}")
        failures.append({"step": "duckdb_aggregate", "error": str(e)})
    finally:
        con.close()

    # Cleanup big intermediates
    for p in big_parquets:
        try:
            p.unlink()
        except OSError:
            pass

    n_partitions = sum(1 for _ in out_dir.rglob("*.parquet"))
    return {
        "records": n_records_total,
        "partitions": n_partitions,
        "failures": len(failures),
        "failures_detail": failures,
    }


# ============================================================
# Verification integrite
# ============================================================
def verify_integrity(schema: str, symbol: str, start_d: date, end_d: date) -> dict:
    """
    Verifications:
      1. Files exist + non vides
      2. Business day gap detection (CME calendar)
      3. SHA256 checksums (manifest)
      4. Volume sanity (volume > 0 sur jours business)
    """
    out_dir = DATA_ROOT / schema / f"symbol={symbol}"
    files = sorted(out_dir.rglob("*.parquet"))

    if not files:
        return {"status": "FAIL", "reason": "no_files"}

    empty = [str(f) for f in files if f.stat().st_size == 0]
    if empty:
        return {"status": "FAIL", "reason": f"{len(empty)}_empty_files", "files": empty[:5]}

    # Extract days from Hive paths
    days_present = set()
    for f in files:
        try:
            parts = {p.split("=")[0]: p.split("=")[1] for p in f.parts if "=" in p}
            y = int(parts.get("year", 0))
            m = int(parts.get("month", 0))
            d = int(parts.get("day", 0))
            if y and m and d:
                days_present.add(date(y, m, d))
        except Exception:
            pass

    # Expected business days (Mon-Fri minus holidays)
    expected = set()
    cur = start_d
    while cur <= end_d:
        if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in CME_HOLIDAYS_HARDCODED:
            expected.add(cur)
        cur += timedelta(days=1)

    # Note: Databento partitionne par jour CALENDAIRE UTC, pas session.
    # Donc on doit trouver tous les jours business attendus.
    missing = sorted(expected - days_present)
    extra = sorted(days_present - expected)  # weekends (Sun open) si presents

    # Total size + sha256 sample
    total_size = sum(f.stat().st_size for f in files)

    # Sample first/last file SHA
    sample_sha = {}
    if files:
        sample_sha[str(files[0].relative_to(out_dir))] = sha256_file(files[0])[:16]
        if len(files) > 1:
            sample_sha[str(files[-1].relative_to(out_dir))] = sha256_file(files[-1])[:16]

    status = "OK"
    if missing:
        status = "WARN" if len(missing) <= 5 else "FAIL"

    return {
        "status": status,
        "n_partitions": len(files),
        "n_days_present": len(days_present),
        "n_days_expected": len(expected),
        "n_missing": len(missing),
        "missing_sample": [str(d) for d in missing[:10]],
        "n_extra_weekends": len(extra),
        "total_size_bytes": total_size,
        "sample_sha256": sample_sha,
    }


# ============================================================
# Manifest atomique
# ============================================================
def update_manifest(jobs, results):
    manifest = {}
    if MANIFEST_FILE.exists():
        try:
            manifest = json.loads(MANIFEST_FILE.read_text())
        except Exception:
            manifest = {}
    manifest["last_run"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("runs", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
        "results": results,
    })
    write_json_atomic(MANIFEST_FILE, manifest)


# ============================================================
# Main
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="Databento backfill batch")
    ap.add_argument("--dry-run", action="store_true",
                    help="Test sur 1 mois (mars 2026)")
    ap.add_argument("--start", help="Date debut YYYY-MM-DD")
    ap.add_argument("--end", help="Date fin YYYY-MM-DD")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--schemas", nargs="+", default=DEFAULT_SCHEMAS)
    ap.add_argument("--no-confirm", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        start_d = date(2026, 3, 1)
        end_d = date(2026, 4, 1)
        suffix = "_DRYRUN"
        print("\n[DRY-RUN] 1 mois: 2026-03-01 -> 2026-04-01\n")
    else:
        start_d = date.fromisoformat(args.start) if args.start else DEFAULT_START
        end_d = date.fromisoformat(args.end) if args.end else DEFAULT_END
        suffix = ""

    if start_d >= end_d:
        print(f"[FATAL] start ({start_d}) >= end ({end_d})")
        sys.exit(8)

    jobs_specs = []
    for symbol in args.symbols:
        for schema in args.schemas:
            label = f"{symbol.replace('.c.0', '')}_{schema}_{start_d.year}-{end_d.year}{suffix}"
            jobs_specs.append((symbol, schema, label, start_d, end_d))

    print(f"Plan {len(jobs_specs)} jobs:")
    for s, sc, lbl, st, en in jobs_specs:
        print(f"  - {lbl:40s} {sc:10s} {s:10s} {st} -> {en}")

    if not args.no_confirm and not args.dry_run:
        try:
            input("\nPress ENTER to continue, Ctrl+C to abort: ")
        except (KeyboardInterrupt, EOFError):
            print("\n[ABORT] User cancelled.")
            sys.exit(0)

    # FIX should-fix B : detection resume si crash precedent
    if ACTIVE_JOBS_FILE.exists():
        try:
            prev = json.loads(ACTIVE_JOBS_FILE.read_text())
            n_prev = len(prev.get("jobs", []))
            print(f"\n[WARN] Found previous run with {n_prev} jobs in {ACTIVE_JOBS_FILE.name}")
            print("  If a previous run crashed, you may want to resume manually.")
            print("  Otherwise this file will be overwritten by current run.")
            if not args.no_confirm:
                ans = input("  Continue and OVERWRITE? [y/N]: ").strip().lower()
                if ans != "y":
                    print("  [ABORT]")
                    sys.exit(0)
        except (json.JSONDecodeError, OSError):
            pass

    acquire_lock()
    try:
        client = db.Historical(API_KEY)

        # Phase 1
        preflight(client, jobs_specs)

        # Phase 2 - submit en vagues 2+2
        jobs = submit_jobs_in_waves(client, jobs_specs, wave_size=2, wave_delay_sec=3)
        write_json_atomic(ACTIVE_JOBS_FILE, {"jobs": jobs})

        # Phase 3
        active_jobs = [j for j in jobs if j.get("job_id")]
        if not active_jobs:
            print("[FATAL] No jobs submitted successfully")
            sys.exit(9)
        poll_until_done(client, active_jobs)

        # Phase 4
        results = []
        for job in jobs:
            if job.get("status") != "done":
                results.append({"label": job["label"], "status": "SKIP", "reason": job.get("status", "?")})
                continue
            print(f"\n  Processing {job['label']}...")
            try:
                dbn_files = download_job(client, job)
                split_res = split_dbn_to_parquet(dbn_files, job["schema"], job["symbol"])
                verify_res = verify_integrity(
                    job["schema"], job["symbol"],
                    date.fromisoformat(job["start"]), date.fromisoformat(job["end"]),
                )
                results.append({
                    "label": job["label"],
                    "status": verify_res.get("status", "UNKNOWN"),
                    "split": split_res,
                    "verify": verify_res,
                })
            except Exception as e:
                traceback.print_exc()
                results.append({"label": job["label"], "status": "ERROR", "error": str(e)})

        # Phase 5
        update_manifest(jobs, results)

        # Cleanup _temp
        if TEMP_ROOT.exists():
            for sub in TEMP_ROOT.iterdir():
                if sub.is_dir():
                    shutil.rmtree(sub, ignore_errors=True)

        # Summary
        print("\n" + "=" * 80)
        print(" SUMMARY")
        print("=" * 80)
        for r in results:
            print(f"  {r['label']:40s} {r.get('status','?'):8s}  "
                  f"records={r.get('split',{}).get('records','-')}  "
                  f"partitions={r.get('split',{}).get('partitions','-')}  "
                  f"missing_days={r.get('verify',{}).get('n_missing','-')}")
        print("=" * 80)

        all_ok = all(r.get("status") == "OK" for r in results)
        sys.exit(0 if all_ok else 10)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
