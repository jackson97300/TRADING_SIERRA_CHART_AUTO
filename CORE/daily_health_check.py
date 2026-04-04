"""
daily_health_check.py — Verification quotidienne du pipeline MIA
=================================================================

Verifie chaque jour que :
1. Le DMP C++ ecrit les JSONL (ES + NQ)
2. Le scraper MenthorQ a produit le JSON du jour
3. Le bot tourne
4. Les barres arrivent
5. Les donnees sont coherentes

Usage :
    python daily_health_check.py           # Check aujourd'hui
    python daily_health_check.py 20260402  # Check une date specifique

Deploiement VPS : tache planifiee MIA_HealthCheck a 15:00 (09:00 ET)

Auteur : MIA Trading System
Date   : 2026-04-02
"""

import json
import os
import sys
import time
import glob
import socket
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = r"C:\TRADING_SIERRA_CHART_AUTO\DATA"
LOG_DIR = os.path.join(DATA_DIR, "LOGS")
MQ_DIR = os.path.join(DATA_DIR, "MENTHORQ")

# Seuils d'alerte
MIN_BARS_PER_DAY = 200       # Minimum barres attendues (Asia+London = ~200)
MAX_JSONL_AGE_SECONDS = 120  # JSONL modifie il y a plus de 2 min = alerte
MIN_MQ_SIZE_BYTES = 50000    # MenthorQ JSON < 50 KB = incomplet


def check_date(date_str: str = None):
    """Verification complete pour une date."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    results = []
    all_ok = True

    print(f"\n{'=' * 60}")
    print(f"  MIA DAILY HEALTH CHECK — {date_str}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")

    # ─── 1. JSONL DMP (ES + NQ) ─────────────────────────────────
    print("  [1] DONNEES DMP (JSONL)")
    for sym in ["ES", "NQ"]:
        sym_dir = os.path.join(DATA_DIR, sym)
        # Chercher le fichier le plus recent (pas forcement la date du jour)
        files = sorted(glob.glob(os.path.join(sym_dir, "*.jsonl")),
                       key=lambda f: os.path.getmtime(f), reverse=True)

        if not files:
            print(f"      {sym}: ERREUR — aucun fichier JSONL")
            results.append(("DMP", sym, "FAIL", "Aucun fichier"))
            all_ok = False
            continue

        latest = files[0]
        age = time.time() - os.path.getmtime(latest)
        n_lines = sum(1 for _ in open(latest))
        size_kb = os.path.getsize(latest) / 1024
        fname = os.path.basename(latest)

        # Verifier age
        if age > MAX_JSONL_AGE_SECONDS:
            status = "WARN"
            msg = f"Modifie il y a {age:.0f}s (>{MAX_JSONL_AGE_SECONDS}s)"
            if age > 3600:
                status = "FAIL"
                msg = f"Modifie il y a {age/3600:.1f}h — DMP ARRETE?"
                all_ok = False
        else:
            status = "OK"
            msg = f"Actif (modifie il y a {age:.0f}s)"

        # Verifier nb barres
        if n_lines < MIN_BARS_PER_DAY and date_str in fname:
            if status == "OK":
                status = "WARN"
            msg += f" | {n_lines} barres (<{MIN_BARS_PER_DAY})"

        icon = "OK" if status == "OK" else "WARN" if status == "WARN" else "FAIL"
        print(f"      {sym}: [{icon}] {fname} — {n_lines} barres, {size_kb:.0f}KB | {msg}")
        results.append(("DMP", sym, status, msg))

    # ─── 2. MENTHORQ JSON ────────────────────────────────────────
    print(f"\n  [2] MENTHORQ (scraper)")

    # Chercher le fichier MQ le plus recent
    mq_files = sorted(glob.glob(os.path.join(MQ_DIR, "*_menthorq_complete.json")),
                      reverse=True)

    if not mq_files:
        print(f"      ERREUR — aucun fichier MenthorQ")
        results.append(("MQ", "ALL", "FAIL", "Aucun fichier"))
        all_ok = False
    else:
        latest_mq = mq_files[0]
        mq_fname = os.path.basename(latest_mq)
        mq_size = os.path.getsize(latest_mq)
        mq_age = time.time() - os.path.getmtime(latest_mq)
        mq_date = mq_fname.split("_")[0]  # "20260401"

        # Charger et verifier le contenu
        try:
            mq_data = json.load(open(latest_mq))
            n_slugs_ok = 0
            n_slugs_total = 0
            for section in ["ES", "NQ", "ES_swing", "NQ_swing",
                            "ES_intraday", "NQ_intraday", "CTA", "VOL"]:
                raw = mq_data.get(section, {}).get("raw_ajax", {})
                for slug, resp in raw.items():
                    n_slugs_total += 1
                    if isinstance(resp, dict) and resp.get("success"):
                        n_slugs_ok += 1

            if mq_size < MIN_MQ_SIZE_BYTES:
                status = "WARN"
                msg = f"{mq_size/1024:.0f}KB (<{MIN_MQ_SIZE_BYTES/1024:.0f}KB)"
            elif mq_age > 86400:  # Plus de 24h
                status = "WARN"
                msg = f"Date {mq_date} — {mq_age/3600:.0f}h ancien"
            else:
                status = "OK"
                msg = f"Date {mq_date}"

            print(f"      [{status}] {mq_fname} — {mq_size/1024:.0f}KB | "
                  f"{n_slugs_ok}/{n_slugs_total} slugs OK | {msg}")

            # Verifier les sections critiques
            for section in ["ES", "NQ"]:
                kl = mq_data.get(section, {}).get("raw_ajax", {}).get("key_levels", {})
                if kl.get("success"):
                    data = kl.get("data", {}).get("resource", {}).get("data", {})
                    hvl = data.get("High Vol Level", "?")
                    call = data.get("Call Resistance 0DTE", "?")
                    put = data.get("Put Support 0DTE", "?")
                    print(f"        {section}: HVL={hvl} Call0DTE={call} Put0DTE={put}")
                else:
                    print(f"        {section}: key_levels ABSENT")
                    all_ok = False

            results.append(("MQ", "ALL", status, f"{n_slugs_ok}/{n_slugs_total} slugs"))

        except Exception as e:
            print(f"      FAIL — erreur lecture: {e}")
            results.append(("MQ", "ALL", "FAIL", str(e)))
            all_ok = False

    # ─── 3. BOT STATUS ──────────────────────────────────────────
    print(f"\n  [3] BOT")

    # Verifier process
    try:
        import subprocess
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                           capture_output=True, text=True, timeout=5)
        python_count = r.stdout.count("python.exe")
        if python_count > 0:
            print(f"      [OK] {python_count} process Python actif(s)")
            results.append(("BOT", "process", "OK", f"{python_count} process"))
        else:
            print(f"      [FAIL] Aucun process Python — bot arrete!")
            results.append(("BOT", "process", "FAIL", "Aucun process"))
            all_ok = False
    except Exception as e:
        print(f"      [WARN] Impossible de verifier: {e}")
        results.append(("BOT", "process", "WARN", str(e)))

    # Verifier log recent
    log_files = sorted(glob.glob(os.path.join(LOG_DIR, "*_bot.log")), reverse=True)
    if log_files:
        latest_log = log_files[0]
        log_age = time.time() - os.path.getmtime(latest_log)
        lines = open(latest_log, encoding="utf-8").readlines()

        # Derniere ligne STATUS
        last_status = None
        for line in reversed(lines):
            if "[STATUS]" in line:
                last_status = line.strip()
                break

        if last_status:
            print(f"      Dernier status: {last_status}")
        if log_age > 600:  # Plus de 10 min sans update
            print(f"      [WARN] Log pas modifie depuis {log_age:.0f}s")
            results.append(("BOT", "log", "WARN", f"Stale {log_age:.0f}s"))
        else:
            results.append(("BOT", "log", "OK", f"Actif ({log_age:.0f}s)"))
    else:
        print(f"      [WARN] Aucun fichier log")
        results.append(("BOT", "log", "WARN", "Aucun log"))

    # ─── 4. DTC CONNEXION ────────────────────────────────────────
    print(f"\n  [4] DTC (Sierra Chart)")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("127.0.0.1", 11099))
        sock.sendall(json.dumps({"Type": 1, "ProtocolVersion": 8,
                                  "HeartbeatIntervalInSeconds": 10,
                                  "ClientName": "MIA_HEALTH"}).encode("utf-8") + b"\x00")
        time.sleep(1)
        buf = b""
        sock.settimeout(2)
        try:
            while True:
                buf += sock.recv(8192)
        except:
            pass
        sock.close()

        if b"Result" in buf and b"1" in buf:
            print(f"      [OK] DTC connecte, Sierra Chart repond")
            results.append(("DTC", "SC", "OK", "Connecte"))
        else:
            print(f"      [WARN] DTC repond mais resultat incertain")
            results.append(("DTC", "SC", "WARN", "Reponse incertaine"))
    except Exception as e:
        print(f"      [FAIL] DTC non joignable: {e}")
        results.append(("DTC", "SC", "FAIL", str(e)))
        all_ok = False

    # ─── 5. SNAPSHOTS ────────────────────────────────────────────
    print(f"\n  [5] SNAPSHOTS")
    snap_dir = os.path.join(DATA_DIR, "SNAPSHOTS")
    if os.path.exists(snap_dir):
        snap_files = os.listdir(snap_dir)
        total_trades = 0
        for f in snap_files:
            n = sum(1 for _ in open(os.path.join(snap_dir, f)))
            total_trades += n
            print(f"      {f} — {n} trade(s)")
        results.append(("SNAP", "ALL", "OK", f"{total_trades} trades total"))
    else:
        print(f"      [WARN] Dossier SNAPSHOTS absent")
        results.append(("SNAP", "ALL", "WARN", "Dossier absent"))

    # ─── RESUME ──────────────────────────────────────────────────
    n_ok = sum(1 for _, _, s, _ in results if s == "OK")
    n_warn = sum(1 for _, _, s, _ in results if s == "WARN")
    n_fail = sum(1 for _, _, s, _ in results if s == "FAIL")

    print(f"\n{'=' * 60}")
    if all_ok:
        print(f"  SANTE: OK — {n_ok} checks OK, {n_warn} warnings")
    else:
        print(f"  SANTE: PROBLEME — {n_fail} FAIL, {n_warn} WARN, {n_ok} OK")
    print(f"{'=' * 60}\n")

    # Sauvegarder le resultat
    health_log = os.path.join(LOG_DIR, "health_check.log")
    with open(health_log, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "OK" if all_ok else "PROBLEME"
        f.write(f"{ts} | {date_str} | {status} | "
                f"OK={n_ok} WARN={n_warn} FAIL={n_fail} | "
                f"{'; '.join(f'{c}:{s}={st}' for c,s,st,_ in results)}\n")

    return all_ok


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    ok = check_date(date)
    sys.exit(0 if ok else 1)
