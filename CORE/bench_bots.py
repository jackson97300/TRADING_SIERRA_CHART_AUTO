# -*- coding: utf-8 -*-
"""
bench_bots.py — Sante des 3 bots (Bot 1, Bot 2 V6, Bot 3 MP)
==============================================================

Tests par bot :
  - Service nssm Running
  - Process Python actif
  - State file fresh + integrite
  - Logs recent activity (events, decisions, errors)
  - Funnel populated (steps + rejections)
  - Trades cycle integrity (open/close, no orphan)
  - Cohérence cross-bot (pas de double trading sur meme compte)
  - Anti-orphan check (OCO_ORPHAN_DETECTED dernière heure)
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _print(out, msg):
    print(msg)
    out.append(msg)


def get_service_status(name):
    try:
        r = subprocess.run(
            ["powershell", "-Command", f"Get-Service {name} | Select -ExpandProperty Status"],
            capture_output=True, text=True, timeout=5
        )
        return (r.stdout or "").strip()
    except Exception:
        return "ERROR"


def find_python_process(needle):
    """P1 fix code-reviewer : split + strip pour nettoyer CRLF Windows."""
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
             f"Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=5
        )
        out = (r.stdout or "").strip()
        if not out: return None
        # Premier PID de la liste, nettoye CRLF
        return out.split()[0].strip()
    except Exception:
        return None


def file_age(p):
    if not p.exists(): return None
    return (datetime.now(timezone.utc) - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).total_seconds()


def count_recent_in_log(log_path, code_pattern, max_age_sec=3600):
    if not log_path.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_sec
    n = 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if code_pattern not in line:
                    continue
                try:
                    j = json.loads(line)
                    ts = datetime.fromisoformat(j["ts"].replace("Z", "+00:00")).timestamp()
                    if ts > cutoff:
                        n += 1
                except Exception: pass
    except OSError: pass
    return n


def test_bot1(out):
    out.append("=" * 70)
    out.append("  BOT 1 DMP (Sim3, MIA-Paper, mia_paper_trader.py)")
    out.append("=" * 70)
    out.append("")
    # Service
    status = get_service_status("MIA-Paper")
    _print(out, f"  Service MIA-Paper : {status} [{'OK' if status=='Running' else 'FAIL'}]")
    # Process
    pid = find_python_process("mia_paper_trader")
    _print(out, f"  Process Python    : pid={pid or 'NOT FOUND'}")
    # State
    state_file = ROOT / "DATA" / "PAPER_TRADES" / "state.json"
    age = file_age(state_file)
    if age is None:
        _print(out, f"  state.json        : MISSING [FAIL]")
    else:
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
            n_closed = len(s.get("closed_today", []))
            n_open = len(s.get("open_by_symbol", {}))
            funnel = s.get("entry_funnel_today", {})
            polls = funnel.get("polls_total", 0)
            actionable = funnel.get("actionable", 0)
            trades_taken = funnel.get("trades_taken", 0)
            _print(out, f"  state.json age    : {age:.0f}s [{'OK' if age<60 else 'STALE'}]")
            _print(out, f"  closed today      : {n_closed} | open: {n_open} | trades_taken: {trades_taken}")
            _print(out, f"  funnel polls      : {polls} (actionable: {actionable})")
        except Exception as e:
            _print(out, f"  state.json parse error : {e}")
    # Recent activity (decisions today)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    decisions = ROOT / "LOGS" / "decisions" / f"decisions_{today}_paper.jsonl"
    n_dec = count_recent_in_log(decisions, "GATE_", 3600)
    _print(out, f"  decisions GATE_ 1h: {n_dec}")
    # Anti-orphan
    errors = ROOT / "LOGS" / "errors" / f"errors_{today}_bot_legacy.jsonl"
    n_orphan = count_recent_in_log(errors, "OCO_ORPHAN_DETECTED", 3600)
    n_cancel_fail = count_recent_in_log(errors, "CANCEL_FAILED_RETRY", 3600)
    _print(out, f"  OCO_ORPHAN 1h     : {n_orphan} | CANCEL_FAILED 1h: {n_cancel_fail}")
    out.append("")


def test_bot2_v6(out):
    out.append("=" * 70)
    out.append("  BOT 2 V6 (Sim2, MIA-Brain-V6, mia2_brain_v6_databento.py)")
    out.append("=" * 70)
    out.append("")
    status = get_service_status("MIA-Brain-V6")
    _print(out, f"  Service MIA-Brain-V6 : {status} [{'OK' if status=='Running' else 'FAIL'}]")
    pid = find_python_process("mia2_brain_v6")
    _print(out, f"  Process Python       : pid={pid or 'NOT FOUND'}")
    state_file = ROOT / "DATA" / "PAPER_TRADES" / "state_v6.json"
    age = file_age(state_file)
    if age is None:
        _print(out, f"  state_v6.json        : MISSING [FAIL]")
    else:
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
            n_closed = len(s.get("closed_today", []))
            n_open = len(s.get("open_by_symbol", {}))
            _print(out, f"  state_v6.json age    : {age:.0f}s [{'OK' if age<60 else 'STALE'}]")
            _print(out, f"  closed today         : {n_closed} | open: {n_open}")
        except Exception as e:
            _print(out, f"  state_v6.json parse error : {e}")
    # V6 brain activity
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    events = ROOT / "LOGS" / "events" / f"events_{today}_paper_v6.jsonl"
    n_brain_active = count_recent_in_log(events, "BRAIN_V6_ACTIVE", 600)
    n_v4_stale = count_recent_in_log(events, "V6_V4_BAR_STALE", 3600)
    n_v4_fallback = count_recent_in_log(events, "V6_V4_FALLBACK_DMP", 3600)
    _print(out, f"  BRAIN_V6_ACTIVE 10m : {n_brain_active} (>=10 typique)")
    _print(out, f"  V6_V4_BAR_STALE 1h  : {n_v4_stale} (V4 pipeline lag indicateur)")
    _print(out, f"  V6_V4_FALLBACK_DMP 1h : {n_v4_fallback}")
    # Logs decisions chase top
    decisions = ROOT / "LOGS" / "decisions" / f"decisions_{today}_paper_v6.jsonl"
    n_chase = count_recent_in_log(decisions, "GATE_CHASE_TOP_LONG_BLOCK", 3600)
    n_rescued = count_recent_in_log(decisions, "GATE_CONSEIL_EXEC_RESCUED", 3600)
    _print(out, f"  ChaseTopGate fires 1h : {n_chase}")
    _print(out, f"  Conseil EXEC RESCUED 1h : {n_rescued} (Option B sauvetages)")
    out.append("")


def test_bot3(out):
    out.append("=" * 70)
    out.append("  BOT 3 MP (Sim1, MIA-DataBento-Paper-V2, bot3_mp_engine)")
    out.append("=" * 70)
    out.append("")
    status = get_service_status("MIA-DataBento-Paper-V2")
    _print(out, f"  Service MIA-DataBento-Paper-V2 : {status} [{'OK' if status=='Running' else 'FAIL'}]")
    pid = find_python_process("databento_paper_trader_v2")
    _print(out, f"  Process Python                 : pid={pid or 'NOT FOUND'}")
    state_file = ROOT / "DATA" / "PAPER_TRADES" / "databento_paper_v3_state.json"
    age = file_age(state_file)
    if age is None:
        _print(out, f"  state_v3.json                  : MISSING [FAIL]")
    else:
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
            n_contacts = s.get("n_contacts_today", 0)
            n_go = s.get("n_go_today", 0)
            n_skip = s.get("n_skip_today", 0)
            level_stats = s.get("level_stats", {}) or {}
            _print(out, f"  state_v3.json age              : {age:.0f}s [{'OK' if age<120 else 'STALE'}]")
            _print(out, f"  contacts/go/skip today         : {n_contacts}/{n_go}/{n_skip}")
            _print(out, f"  niveaux actifs cumul          : {len(level_stats)} types")
        except Exception as e:
            _print(out, f"  state_v3.json parse error : {e}")
    # Bot 3 specific events
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    events = ROOT / "LOGS" / "events" / f"events_{today}_paper_v2.jsonl"
    n_boot = count_recent_in_log(events, "BOT3_BOOT_READY", 86400)
    _print(out, f"  BOT3_BOOT_READY 24h            : {n_boot}")
    # Critical : pas d'erreurs _bot3_persist_state
    errors = ROOT / "LOGS" / "errors" / f"errors_{today}_paper_v2.jsonl"
    n_persist_err = count_recent_in_log(errors, "_bot3_persist_state", 3600)
    n_orphan = count_recent_in_log(errors, "BOT3_TIMEOUT", 3600)
    _print(out, f"  _bot3_persist_state errors 1h  : {n_persist_err} [{'OK' if n_persist_err==0 else 'FAIL fix bug'}]")
    _print(out, f"  BOT3_TIMEOUT 1h                : {n_orphan} [{'OK' if n_orphan==0 else 'WARN'}]")
    # Decisions
    decisions = ROOT / "LOGS" / "decisions" / f"decisions_{today}_paper_v2.jsonl"
    n_decision = count_recent_in_log(decisions, "BOT3_DECISION", 3600)
    _print(out, f"  BOT3_DECISION_* 1h             : {n_decision}")
    out.append("")


def test_cross_bot_consistency(out):
    """Verifie pas de double trading sur Sim2 (V6 + Bot 2 V2 silencé).

    P1 fix code-reviewer : verifier service Up AVANT de conclure 'silence'.
    Sinon n=0 ne distingue pas 'silencé OK' de 'bot mort'.
    """
    out.append("=" * 70)
    out.append("  CROSS-BOT : COHERENCE TRADE_ACCOUNT (anti double-trading)")
    out.append("=" * 70)
    out.append("")
    # Service hosting Bot 2 V2 + Bot 3 (meme process)
    svc_status = get_service_status("MIA-DataBento-Paper-V2")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    events = ROOT / "LOGS" / "events" / f"events_{today}_paper_v2.jsonl"
    n_bot2_observe = count_recent_in_log(events, "BOT2_REGIME_OBSERVE", 3600)
    n_bot3_observe = count_recent_in_log(events, "BOT3_REGIME_OBSERVE", 3600)
    _print(out, f"  Service MIA-DataBento-Paper-V2 : {svc_status}")
    if svc_status != "Running":
        _print(out, f"  BOT2_REGIME_OBSERVE 1h : {n_bot2_observe} [N/A — service down, conclusion silence indeterminee]")
        _print(out, f"  BOT3_REGIME_OBSERVE 1h : {n_bot3_observe} [N/A — idem]")
    else:
        # Service Up : interpretation des counts est valide
        if n_bot3_observe > 0 and n_bot2_observe == 0:
            verdict = "OK silencé (Bot 3 actif, Bot 2 V2 ne logue pas)"
        elif n_bot3_observe == 0 and n_bot2_observe == 0:
            verdict = "INDETERMINE — Bot 3 silence aussi (peut-etre eco_block, normal nuit)"
        elif n_bot2_observe > 0:
            verdict = "WARN double trading risk (Bot 2 V2 emet OBSERVE = pipeline actif)"
        else:
            verdict = "WARN — Bot 3 silencieux mais Bot 2 V2 actif"
        _print(out, f"  BOT2_REGIME_OBSERVE 1h (Bot 2 V2) : {n_bot2_observe}")
        _print(out, f"  BOT3_REGIME_OBSERVE 1h (Bot 3)    : {n_bot3_observe}")
        _print(out, f"  Verdict cross-bot                  : {verdict}")
    # Verification kill-switch env var
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "nssm get MIA-DataBento-Paper-V2 AppEnvironmentExtra 2>$null"],
            capture_output=True, text=True, timeout=5
        )
        envs = (r.stdout or "").strip()
        has_kill = "MIA_BOT2_V2_PAPER_ENABLED=0" in envs or "MIA_BOT2_V2_PAPER_ENABLED" not in envs
        _print(out, f"  MIA_BOT2_V2_PAPER_ENABLED kill-switch : {'OK (default 0)' if has_kill else 'WARN (=1)'}")
    except Exception as e:
        _print(out, f"  Kill-switch check : ERROR {str(e)[:60]}")
    out.append("")


def test_watchdog(out):
    """Verifie watchdog config + heartbeats."""
    out.append("=" * 70)
    out.append("  WATCHDOG MIA-Watchdog (auto-restart bots)")
    out.append("=" * 70)
    out.append("")
    status = get_service_status("MIA-Watchdog")
    _print(out, f"  Service MIA-Watchdog : {status} [{'OK' if status=='Running' else 'FAIL'}]")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    events = ROOT / "LOGS" / "events" / f"events_{today}_watchdog.jsonl"
    n_heart = count_recent_in_log(events, "WATCHDOG_HEARTBEAT", 1200)
    n_restart = count_recent_in_log(events, "WATCHDOG_RESTART", 86400)
    n_stale = count_recent_in_log(events, "WATCHDOG_FLAG_STALE", 3600)
    _print(out, f"  HEARTBEAT 20m       : {n_heart} [{'OK' if n_heart>=1 else 'STALE'}]")
    _print(out, f"  RESTARTS 24h        : {n_restart}")
    _print(out, f"  FLAG_STALE 1h       : {n_stale}")
    out.append("")


def main():
    out = []
    out.append(f"BENCH BOTS — {datetime.now().isoformat()[:19]}")
    out.append("")
    test_bot1(out)
    test_bot2_v6(out)
    test_bot3(out)
    test_cross_bot_consistency(out)
    test_watchdog(out)
    out.append("=" * 70)
    out.append("  END BENCH BOTS")
    out.append("=" * 70)
    out_file = ROOT / "DATA" / f"BENCH_BOTS_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    out_file.write_text("\n".join(out), encoding="utf-8")
    print(f"\nRapport sauve : {out_file}")


if __name__ == "__main__":
    main()
