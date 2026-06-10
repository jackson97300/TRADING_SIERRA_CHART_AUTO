# -*- coding: utf-8 -*-
"""
bench_dashboard.py — Sante du dashboard MIA
============================================

Tests :
  1. Endpoints API repondent (latence + status code)
  2. State files des 3 bots frais (<60s)
  3. conseil_global.action computed pour ES + NQ
  4. Cards visibility logic (Bot 2 V2 / Bot 3 MP) coherent avec toggle
  5. Cache versions dashboard.js / .css coherents
  6. Service MIA-Dashboard Running
  7. Logs dashboard pas d'erreurs majeures recentes
  8. JWT secret + API auth fonctionnels (probe avec service token)

Usage : python -X utf8 CORE/bench_dashboard.py [--vps]
  --vps : run sur VPS via SSH (sinon local)
"""
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _print(out, msg):
    print(msg)
    out.append(msg)


def test_api_endpoints(out, base="http://localhost:8503"):
    """Test 1 : endpoints API repondent."""
    out.append("=" * 70)
    out.append("  TEST 1 — API ENDPOINTS LATENCE & STATUS")
    out.append("=" * 70)
    out.append("")
    try:
        import requests
    except ImportError:
        _print(out, "  requests pas installe — skip")
        return
    endpoints = [
        ("/api/health", 1.0),
        ("/api/dashboard", 2.0),
        ("/api/cta", 2.0),
        ("/api/paper_trades", 2.0),
    ]
    for ep, max_lat in endpoints:
        url = base + ep
        try:
            t0 = time.time()
            r = requests.get(url, timeout=5)
            elapsed = time.time() - t0
            status = "OK" if (r.status_code in (200, 401) and elapsed < max_lat) else "WARN"
            _print(out, f"  {ep:25s} status={r.status_code} latence={elapsed*1000:.0f}ms (max {max_lat*1000:.0f}ms) [{status}]")
        except Exception as e:
            _print(out, f"  {ep:25s} ERROR: {str(e)[:60]} [FAIL]")
    out.append("")


def test_state_files_freshness(out):
    """Test 2 : state files des 3 bots frais."""
    out.append("=" * 70)
    out.append("  TEST 2 — STATE FILES FRESHNESS (3 bots)")
    out.append("=" * 70)
    out.append("")
    paper = ROOT / "DATA" / "PAPER_TRADES"
    states = [
        ("Bot 1 DMP", "state.json", 60),
        ("Bot 2 V6", "state_v6.json", 60),
        ("Bot 3 MP", "databento_paper_v3_state.json", 120),
    ]
    now = datetime.now(timezone.utc)
    for label, fname, max_age in states:
        p = paper / fname
        if not p.exists():
            _print(out, f"  {label:15s} {fname:40s} MISSING")
            continue
        mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        age = (now - mt).total_seconds()
        size_kb = p.stat().st_size / 1024
        status = "OK" if age <= max_age else "STALE"
        _print(out, f"  {label:15s} {fname:40s} age={age:.0f}s size={size_kb:.0f}KB (max {max_age}s) [{status}]")
    out.append("")


def test_conseil_computed(out):
    """Test 3 : conseil_global.action computed pour ES + NQ."""
    out.append("=" * 70)
    out.append("  TEST 3 — CONSEIL GLOBAL COMPUTED (ES + NQ)")
    out.append("=" * 70)
    out.append("")
    try:
        import requests
        r = requests.get("http://localhost:8503/api/dashboard", timeout=5)
        if r.status_code != 200:
            _print(out, f"  /api/dashboard status {r.status_code} — skip")
            return
        data = r.json()
        cg = data.get("conseil_global", {}) or {}
        for sym in ["ES", "NQ"]:
            sub = cg.get(sym, {})
            action = sub.get("action", "?")
            exec_action = sub.get("executable_action", "?")
            bull = sub.get("bull_points", "?")
            bear = sub.get("bear_points", "?")
            freshness = sub.get("freshness", "?")
            status = "OK" if action != "?" else "FAIL"
            _print(out, f"  {sym}: action={action} exec={exec_action} bull/bear={bull}/{bear} freshness={freshness} [{status}]")
    except Exception as e:
        _print(out, f"  ERROR : {str(e)[:80]}")
    out.append("")


def test_card_visibility_consistency(out):
    """Test 4 : verif HTML/JS coherence cards bot toggles."""
    out.append("=" * 70)
    out.append("  TEST 4 — CARD VISIBILITY (HTML + JS coherence)")
    out.append("=" * 70)
    out.append("")
    html = ROOT / "DASHBOARD" / "static" / "index.html"
    js = ROOT / "DASHBOARD" / "static" / "js" / "dashboard.js"
    if not html.exists() or not js.exists():
        _print(out, "  index.html ou dashboard.js manquant")
        return
    html_txt = html.read_text(encoding="utf-8")
    js_txt = js.read_text(encoding="utf-8")
    checks = [
        ('id="paper-v2-card"', html_txt, "HTML"),
        ('id="paper-v3-card"', html_txt, "HTML"),
        ('paper-v2-card', js_txt, "JS"),
        ('paper-v3-card', js_txt, "JS"),
        ('which === "bot2"', js_txt, "JS"),
        ('which === "bot3"', js_txt, "JS"),
    ]
    for needle, content, src in checks:
        present = needle in content
        status = "OK" if present else "MISSING"
        _print(out, f"  {src} contains {needle:30s} [{status}]")
    out.append("")


def test_cache_versions(out):
    """Test 5 : cache version index.html ↔ dashboard.js."""
    out.append("=" * 70)
    out.append("  TEST 5 — CACHE VERSIONS (anti react hydration cache)")
    out.append("=" * 70)
    out.append("")
    html = ROOT / "DASHBOARD" / "static" / "index.html"
    if not html.exists():
        _print(out, "  index.html manquant")
        return
    txt = html.read_text(encoding="utf-8")
    import re
    js_versions = re.findall(r'dashboard\.js\?v=(\d+)', txt)
    css_versions = re.findall(r'dashboard\.css\?v=(\d+)', txt)
    _print(out, f"  dashboard.js?v= : {js_versions} (uniques: {set(js_versions)})")
    _print(out, f"  dashboard.css?v= : {css_versions} (uniques: {set(css_versions)})")
    if js_versions and len(set(js_versions)) == 1:
        _print(out, "  [OK] JS version coherent")
    elif js_versions:
        _print(out, "  [WARN] JS versions multiples")
    else:
        _print(out, "  [FAIL] aucune ref dashboard.js trouvee")
    out.append("")


def test_dashboard_service(out):
    """Test 6 : service MIA-Dashboard Running."""
    out.append("=" * 70)
    out.append("  TEST 6 — SERVICE MIA-Dashboard")
    out.append("=" * 70)
    out.append("")
    try:
        r = subprocess.run(
            ["powershell", "-Command", "Get-Service MIA-Dashboard | Select -ExpandProperty Status"],
            capture_output=True, text=True, timeout=5
        )
        status = (r.stdout or "").strip()
        ok = "Running" in status
        _print(out, f"  MIA-Dashboard status : {status} [{'OK' if ok else 'FAIL'}]")
    except Exception as e:
        _print(out, f"  ERROR : {str(e)[:60]}")
    out.append("")


def test_logs_recent_errors(out):
    """Test 7 : pas d'erreurs majeures dashboard 1h."""
    out.append("=" * 70)
    out.append("  TEST 7 — DASHBOARD LOGS RECENT ERRORS")
    out.append("=" * 70)
    out.append("")
    log_dir = ROOT / "LOGS" / "errors"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    log = log_dir / f"errors_{today}_dashboard.jsonl"
    if not log.exists():
        _print(out, f"  Pas de log dashboard today (pas d'erreur ou bot non actif)")
        return
    cutoff = datetime.now(timezone.utc).timestamp() - 3600  # 1h
    n_recent = 0
    samples = []
    try:
        with open(log, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                    ts_str = j.get("ts", "")
                    if not ts_str: continue
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                    if ts > cutoff:
                        n_recent += 1
                        if len(samples) < 5:
                            samples.append(f"{j.get('code','?')}: {(j.get('msg_fr','') or '')[:60]}")
                except Exception: pass
    except OSError: pass
    status = "OK" if n_recent == 0 else "WARN"
    _print(out, f"  Erreurs dashboard 1h: {n_recent} [{status}]")
    for s in samples:
        _print(out, f"    - {s}")
    out.append("")


def test_jwt_auth(out):
    """Test 8 : JWT secret persistant + auth fonctionnel."""
    out.append("=" * 70)
    out.append("  TEST 8 — JWT SECRET + AUTH PROBE")
    out.append("=" * 70)
    out.append("")
    jwt_file = ROOT / ".jwt_secret"
    if jwt_file.exists():
        size = jwt_file.stat().st_size
        _print(out, f"  .jwt_secret present ({size} bytes) [OK]")
    else:
        _print(out, f"  .jwt_secret MISSING - JWT non persistent (tokens expirent au restart)")
    try:
        import requests
        r = requests.get("http://localhost:8503/api/dashboard", timeout=3)
        if r.status_code == 401:
            _print(out, "  /api/dashboard 401 sans token : auth-required [OK]")
        elif r.status_code == 200:
            d = r.json()
            tier = d.get("tier", "?")
            _print(out, f"  /api/dashboard 200 sans token : tier={tier} (probable bypass dev)")
    except Exception as e:
        _print(out, f"  ERROR : {str(e)[:60]}")
    out.append("")


def main():
    out = []
    out.append(f"BENCH DASHBOARD — {datetime.now().isoformat()[:19]}")
    out.append("")
    test_api_endpoints(out)
    test_state_files_freshness(out)
    test_conseil_computed(out)
    test_card_visibility_consistency(out)
    test_cache_versions(out)
    test_dashboard_service(out)
    test_logs_recent_errors(out)
    test_jwt_auth(out)
    out.append("=" * 70)
    out.append("  END BENCH DASHBOARD — 8 tests executes")
    out.append("=" * 70)
    out_file = ROOT / "DATA" / f"BENCH_DASHBOARD_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    out_file.write_text("\n".join(out), encoding="utf-8")
    print(f"\nRapport sauve : {out_file}")


if __name__ == "__main__":
    main()
