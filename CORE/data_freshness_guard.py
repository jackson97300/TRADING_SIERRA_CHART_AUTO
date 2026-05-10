"""
data_freshness_guard.py — Multi-source data freshness check 3-source.

CREE 11/05/2026 apres incident "trades fantomes ES" (bug DMP Gold pollution)
+ audit safety agent code-reviewer. Reference DOCS/SPEC_GLOBAL_RISK_CAP.md
+ DOCS/INCIDENT_LOG.md categorie VALIDATION_MISS.

But : eviter cas Jackson "oubli paiement Denali => 15min delay invisible".

Architecture 3 sources independantes :
  A. Sierra Chart DMP mtime fichier JSONL (DATA/ES/*.jsonl, DATA/NQ/*.jsonl)
  B. Databento heartbeat (DATA/LIVE_CACHE/_stream_heartbeat.json)
  C. NTP externe pool.ntp.org via ntplib

Decision matrix :
  3/3 OK  → trade autorise
  2/3 OK  → WARN (mode degrade)
  1/3 OK  → BLOCK trades
  0/3 OK  → KILL + alert Discord

Service `MIA-FreshnessGuard` (nssm) loop 30s appelle evaluate() :
  Ecrit DATA/BOT_CONTROL/DATA_FRESH_STATE.json (atomic).

Bots lisent ce state avant chaque _execute_trade.
Si block=True → skip avec emit GATE_DATA_STALE_BLOCK.

Usage :
  # Bot (avant _execute_trade) :
  from CORE.data_freshness_guard import read_state
  fresh = read_state()
  if fresh.get("block"):
      _emit("GATE_DATA_STALE_BLOCK", level=fresh["level"], reasons=fresh["reasons"])
      return  # skip trade

  # Service guard loop :
  python -m CORE.data_freshness_guard --loop
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "DATA" / "BOT_CONTROL" / "DATA_FRESH_STATE.json"
KILL_FLAG = ROOT / "DATA" / "BOT_CONTROL" / "DATA_STALE_KILL.flag"
DB_HEARTBEAT = ROOT / "DATA" / "LIVE_CACHE" / "_stream_heartbeat.json"

SC_DMP_GLOBS = {
    "ES": str(ROOT / "DATA" / "ES" / "*_ES.jsonl"),
    "NQ": str(ROOT / "DATA" / "NQ" / "*_NQ.jsonl"),
}

# Seuils calibres pour le cas Jackson "Denali delay 15min"
# Tighter que les seuils existants Bot 3 (45min trop large).
WALL_DELAY_MAX_SEC = 90      # |NTP_now - source.mtime| > 90s = delivery retardee
DRIFT_AB_MAX_SEC = 30        # |SC.mtime - DB.last_data| > 30s = derive 1 source
NTP_SKEW_MAX_SEC = 60        # |sys clock - NTP| > 60s = horloge VPS drift
NTP_QUERY_INTERVAL_SEC = 30  # query NTP pas trop frequent (cache)
NTP_OFFSET_STALE_MAX_SEC = 300  # offset NTP cache valide 5min

LOOP_INTERVAL_SEC = 30       # poll loop service guard

# Cache NTP module-level
_ntp_cache = {"ts": 0.0, "offset": 0.0, "ever_succeeded": False}


# ─────────────────────────────────────────────────────────────────────────────
# Source C : NTP externe
# ─────────────────────────────────────────────────────────────────────────────

def query_ntp(servers: tuple = ("pool.ntp.org", "time.windows.com")) -> Optional[float]:
    """Retourne offset (sec) entre horloge locale et NTP. Cache 30s.

    Failsafe :
      - Si NTP succede au moins 1x : utilise cache si age < 5 min
      - Si NTP n'a jamais marche : return None (echec total, log warning)
    """
    now = time.time()
    cache_age = now - _ntp_cache["ts"]
    if cache_age < NTP_QUERY_INTERVAL_SEC:
        return _ntp_cache["offset"]

    try:
        import ntplib
    except ImportError:
        logger.error("ntplib not installed. Run: pip install ntplib")
        return None

    c = ntplib.NTPClient()
    for server in servers:
        try:
            r = c.request(server, version=3, timeout=2)
            _ntp_cache["offset"] = float(r.offset)
            _ntp_cache["ts"] = now
            _ntp_cache["ever_succeeded"] = True
            return float(r.offset)
        except Exception as e:
            logger.debug("NTP %s failed: %s", server, e)
            continue

    # All servers failed
    if _ntp_cache["ever_succeeded"] and cache_age < NTP_OFFSET_STALE_MAX_SEC:
        # Cache acceptable
        return _ntp_cache["offset"]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Source A : SC DMP JSONL mtime
# ─────────────────────────────────────────────────────────────────────────────

def sc_dmp_age(symbol: str) -> Optional[float]:
    """Retourne age (sec) du fichier JSONL le plus recent du symbole.

    None si aucun fichier trouve (rare, instances en arret).
    """
    pattern = SC_DMP_GLOBS.get(symbol.upper())
    if not pattern:
        return None
    files = glob.glob(pattern)
    if not files:
        return None
    latest_mtime = max(os.stat(f).st_mtime for f in files)
    return time.time() - latest_mtime


# ─────────────────────────────────────────────────────────────────────────────
# Source B : Databento heartbeat
# ─────────────────────────────────────────────────────────────────────────────

def databento_state() -> tuple[Optional[float], bool]:
    """Retourne (max_silence_age, subscribe_alive).

    None si fichier absent / corrupt.
    """
    try:
        with open(DB_HEARTBEAT, "r", encoding="utf-8") as f:
            d = json.load(f)
        alive = bool(d.get("subscribe_alive", False))
        silence = d.get("data_silence_per_sym") or {}
        ages = [v for v in silence.values() if isinstance(v, (int, float))]
        max_age = max(ages) if ages else 0.0
        return (max_age, alive)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return (None, False)


# ─────────────────────────────────────────────────────────────────────────────
# Main evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate() -> dict:
    """Evaluate 3 sources + decision matrix. Atomic write STATE_FILE.

    Returns state dict.
    """
    now_local = time.time()
    ntp_offset = query_ntp()
    sources_ok = {"SC": False, "DB": False, "NTP": ntp_offset is not None}
    reasons: list[str] = []

    # Source A : SC DMP (worst des 2 symbols)
    sc_ages_per_sym: dict[str, Optional[float]] = {}
    for sym in ("ES", "NQ"):
        sc_ages_per_sym[sym] = sc_dmp_age(sym)
    sc_ages_valid = [a for a in sc_ages_per_sym.values() if a is not None]
    sc_age = max(sc_ages_valid) if sc_ages_valid else None
    if sc_age is not None and sc_age < WALL_DELAY_MAX_SEC:
        sources_ok["SC"] = True
    elif sc_age is None:
        reasons.append("SC_NO_FILE")
    else:
        reasons.append(f"SC_STALE_age_{int(sc_age)}s")

    # Source B : Databento
    db_age, db_alive = databento_state()
    if db_alive and db_age is not None and db_age < WALL_DELAY_MAX_SEC:
        sources_ok["DB"] = True
    else:
        if not db_alive:
            reasons.append("DB_NOT_ALIVE")
        elif db_age is None:
            reasons.append("DB_NO_HEARTBEAT")
        else:
            reasons.append(f"DB_STALE_age_{int(db_age)}s")

    # Source C : NTP (deja calcule en haut)
    if ntp_offset is None:
        reasons.append("NTP_UNREACHABLE")
    elif abs(ntp_offset) > NTP_SKEW_MAX_SEC:
        sources_ok["NTP"] = False
        reasons.append(f"VPS_CLOCK_DRIFT_offset_{ntp_offset:.1f}s")

    # Crosscheck drift A-B (warning info, pas critere blocage seul)
    drift_ab = None
    if sc_age is not None and db_age is not None:
        drift_ab = abs(sc_age - db_age)
        if drift_ab > DRIFT_AB_MAX_SEC:
            reasons.append(f"SC_DB_DRIFT_{drift_ab:.1f}s")

    # Decision matrix
    n_ok = sum(sources_ok.values())
    if n_ok >= 3:
        level, block = "OK", False
    elif n_ok == 2:
        level, block = "WARN", False  # mode degrade autorise
    elif n_ok == 1:
        level, block = "BLOCK", True
    else:
        level, block = "KILL", True

    state = {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": level,
        "block": block,
        "sources_ok": sources_ok,
        "n_ok": n_ok,
        "ntp_offset_sec": ntp_offset,
        "sc_age_sec": sc_age,
        "sc_ages_per_sym": sc_ages_per_sym,
        "db_age_sec": db_age,
        "db_alive": db_alive,
        "drift_ab_sec": drift_ab,
        "reasons": reasons,
    }

    # Write atomic
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)

    # Kill flag management
    if level == "KILL" and not KILL_FLAG.exists():
        KILL_FLAG.parent.mkdir(parents=True, exist_ok=True)
        KILL_FLAG.write_text(json.dumps(state))
    elif level != "KILL" and KILL_FLAG.exists():
        try:
            KILL_FLAG.unlink()
        except OSError:
            pass

    return state


def read_state() -> dict:
    """Helper pour bots : lit STATE_FILE.

    Failsafe : retourne fail-closed (block=True) si fichier absent ou corrupt.
    Au moins 1 cycle eval doit avoir tourne avant que les bots puissent trader.
    """
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {
            "block": True,
            "level": "KILL",
            "reasons": ["STATE_FILE_MISSING_FAIL_CLOSED"],
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


def loop():
    """Loop principal du service guard. Eval toutes les LOOP_INTERVAL_SEC."""
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(message)s",
        level=logging.INFO,
    )
    logger.info("data_freshness_guard service start (interval=%ds)", LOOP_INTERVAL_SEC)
    while True:
        try:
            state = evaluate()
            logger.info(
                "state level=%s n_ok=%d/3 reasons=%s",
                state["level"], state["n_ok"], state["reasons"][:3]
            )
        except Exception as e:
            logger.exception("evaluate() error: %s", e)
        time.sleep(LOOP_INTERVAL_SEC)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true",
                        help="Lance le loop service (defaut: 1 evaluation)")
    parser.add_argument("--once", action="store_true",
                        help="1 evaluation puis print state JSON")
    args = parser.parse_args()

    if args.loop:
        loop()
    else:
        state = evaluate()
        print(json.dumps(state, indent=2, default=str))


if __name__ == "__main__":
    main()
