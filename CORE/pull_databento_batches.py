"""pull_databento_batches.py — Pull batches Databento ready + conversion Hive.

Pull les jobs Databento DEJA generes (state=done, billed_cost=$0 — couverts par
le plan), decompresse les .dbn.zst et ecrit le parquet dans la structure Hive
attendue par le loader MIA_V3 :
    DATA/databento/GLBX.MDP3/{schema}/symbol={sym}/year=Y/month=M/day=D/
        data_0.parquet

ATTENTION : year/month/day NON zero-paddes (convention loader.py — verifiee).

USAGE : python -X utf8 CORE/pull_databento_batches.py
"""
from __future__ import annotations

import gc
import os
import pathlib
import sys
import traceback

import databento as db


# --- charge .env (dotenv plante avec __file__ depuis stdin) -----------------
for line in pathlib.Path(".env").read_text().splitlines():
    line = line.strip()
    if line and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


HIVE_ROOT = pathlib.Path("DATA/databento/GLBX.MDP3")
PULL_DIR = pathlib.Path("DATA/_databento_pull")   # cache persistant (rerunnable)
TARGET_BATCHES = [
    "GLBX-20260521-8M75WKVDCE",   # NQ.c.0 trades 2025-12-14 -> 2026-05-01
    "GLBX-20260521-6EBXLU93V8",   # ES.c.0 trades 2025-12-14 -> 2026-05-01
    "GLBX-20260520-3LX9UG5YFX",   # NQ.c.0 trades 2024-01-01 -> 2025-01-01
    "GLBX-20260520-JRCT743VS6",   # ES.c.0 trades 2024-01-01 -> 2025-01-01
]


def hive_partition(schema: str, symbol: str, ymd: str) -> pathlib.Path:
    """Construit le chemin Hive attendu par le loader.

    NB : mois et jours NON zero-paddes ('month=3' pas 'month=03') — convention
    observee dans les partitions existantes et codee dans loader.py:42-45.
    """
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    return (HIVE_ROOT / schema / f"symbol={symbol}" /
            f"year={y}" / f"month={m}" / f"day={d}")


def extract_date(filename: str) -> str:
    """`glbx-mdp3-YYYYMMDD.trades.dbn.zst` -> 'YYYYMMDD'."""
    base = filename.split(".")[0]                # 'glbx-mdp3-YYYYMMDD'
    ymd = base.rsplit("-", 1)[-1]
    if len(ymd) != 8 or not ymd.isdigit():
        raise ValueError(f"date introuvable dans nom {filename}")
    return ymd


def convert_dbn(dbn_path: pathlib.Path, symbol: str, schema: str,
                 force: bool = False) -> int:
    """Lit un .dbn.zst, ecrit le parquet dans la partition Hive.

    Retourne le nombre de trades convertis (0 si fichier vide ou skip).
    Si le parquet existe deja, skip sauf si force=True.
    """
    ymd = extract_date(dbn_path.name)
    part = hive_partition(schema, symbol, ymd)
    out = part / "data_0.parquet"
    if out.exists() and not force:
        return -1                                  # skip
    store = db.DBNStore.from_file(str(dbn_path))
    df = store.to_df()
    if len(df) == 0:
        del df, store
        return 0
    # Le loader fait df.reset_index() si ts_event est en index : on l'aligne
    # AVANT d'ecrire pour eviter de stocker l'index nomme dans le parquet.
    if df.index.name == "ts_event":
        df = df.reset_index()
    part.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    n = len(df)
    del df, store
    gc.collect()
    return n


def pull_batch(client, job_id: str, all_jobs: dict) -> None:
    job = all_jobs.get(job_id)
    if not job:
        print(f"  [{job_id}] JOB ABSENT cote API — skip")
        return
    # `symbols` cote API : str CSV ("NQ.c.0" ou "NQ.FUT,ES.FUT") OU list.
    # Bug pre-fix : job["symbols"][0] sur une str renvoie "N" (1er char) -> typo.
    raw = job.get("symbols") or ""
    syms = raw if isinstance(raw, list) else [s.strip() for s in raw.split(",")]
    if not syms or not syms[0]:
        print(f"  [{job_id}] symbols vide -- skip")
        return
    sym = syms[0]
    schema = job["schema"]
    start = (job.get("start") or "")[:10]
    end = (job.get("end") or "")[:10]
    print(f"\n=== {job_id} ===")
    print(f"  {sym} / {schema} / {start} -> {end}")

    batch_dir = PULL_DIR / job_id
    already = list(batch_dir.glob("*.dbn.zst")) if batch_dir.exists() else []
    if already:
        print(f"  Deja telecharge : {len(already)} .dbn.zst dans {batch_dir}")
    else:
        print(f"  Telechargement vers {PULL_DIR} ...")
        client.batch.download(output_dir=str(PULL_DIR), job_id=job_id)

    dbns = sorted((PULL_DIR / job_id).glob("*.dbn.zst"))
    print(f"  {len(dbns)} .dbn.zst pretes a convertir")

    n_total = n_skip = n_fail = 0
    failed = []
    for i, dbn in enumerate(dbns, 1):
        try:
            r = convert_dbn(dbn, sym, schema)
            if r == -1:
                n_skip += 1
            else:
                n_total += r
            if i % 30 == 0 or i == len(dbns):
                print(f"    {i}/{len(dbns)}  trades_cumul={n_total:,}  "
                      f"skip={n_skip}  fail={n_fail}")
        except Exception as e:
            n_fail += 1
            failed.append((dbn.name, str(e)[:90]))
    print(f"  TERMINE  trades={n_total:,}  skip(deja_la)={n_skip}  fail={n_fail}")
    if failed:
        print("  FAILURES :")
        for name, err in failed[:5]:
            print(f"    {name}  ->  {err}")


def main():
    PULL_DIR.mkdir(parents=True, exist_ok=True)
    client = db.Historical(os.environ["DATABENTO_API_KEY"])
    print("=== PULL DATABENTO BATCHES .c.0 (already done, $0) ===")
    all_jobs = {j["id"]: j for j in client.batch.list_jobs()}
    for job_id in TARGET_BATCHES:
        try:
            pull_batch(client, job_id, all_jobs)
        except Exception as e:
            print(f"  ERREUR batch {job_id} : {e}")
            traceback.print_exc()
    print("\n=== PULL+CONVERSION COMPLETS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
