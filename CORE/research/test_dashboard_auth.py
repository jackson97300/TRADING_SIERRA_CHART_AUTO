"""Test empirique : confirme que paper_trader sans auth recoit tier=free."""
import sys, json, urllib.request

sys.path.insert(0, ".")

print("=" * 70)
print("TEST 1 — Dashboard SANS AUTH (flow actuel paper_trader)")
print("=" * 70)
try:
    r = urllib.request.urlopen("http://localhost:8503/api/dashboard", timeout=10)
    d = json.loads(r.read())
    print(f"  HTTP OK, payload size: {len(json.dumps(d))} bytes")
    print(f"  tier returned: {d.get('tier')}")
    cg = d.get("conseil_global", {})
    es = cg.get("es", {})
    nq = cg.get("nq", {})
    print(f"  conseil_global keys: {list(cg.keys())}")
    print(f"  ES.action: {es.get('action')} | freshness: {es.get('freshness')} | signal_id: {es.get('signal_id')}")
    print(f"  NQ.action: {nq.get('action')} | freshness: {nq.get('freshness')} | signal_id: {nq.get('signal_id')}")
    print(f"  instruments keys: {list(d.keys())[:15]}")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=" * 70)
print("TEST 2 — Dashboard AVEC AUTH OWNER (fix propose)")
print("=" * 70)
try:
    from DASHBOARD.api.auth import _create_token
    token = _create_token("paper_service@internal", "owner", "access")
    print(f"  JWT genere: {token[:50]}...")
    req = urllib.request.Request("http://localhost:8503/api/dashboard")
    req.add_header("Authorization", f"Bearer {token}")
    r = urllib.request.urlopen(req, timeout=10)
    d = json.loads(r.read())
    print(f"  HTTP OK, payload size: {len(json.dumps(d))} bytes")
    print(f"  tier returned: {d.get('tier')}")
    cg = d.get("conseil_global", {})
    es = cg.get("es", {})
    nq = cg.get("nq", {})
    print(f"  ES.action: {es.get('action')} | freshness: {es.get('freshness')} | confidence: {es.get('confidence')}")
    print(f"  ES signal_id: {(es.get('signal_id') or '')[:20]}")
    print(f"  NQ.action: {nq.get('action')} | freshness: {nq.get('freshness')} | confidence: {nq.get('confidence')}")
    print(f"  NQ signal_id: {(nq.get('signal_id') or '')[:20]}")
    # Details complementaires
    inst_es = d.get("es", {}).get("regime", {})
    inst_nq = d.get("nq", {}).get("regime", {})
    print(f"  ES regime.mtf_bulls={inst_es.get('mtf_bulls')} mtf_bears={inst_es.get('mtf_bears')} bias_confidence={inst_es.get('bias_confidence')}")
    print(f"  NQ regime.mtf_bulls={inst_nq.get('mtf_bulls')} mtf_bears={inst_nq.get('mtf_bears')} bias_confidence={inst_nq.get('bias_confidence')}")
except Exception as e:
    import traceback
    print(f"  ERROR: {e}")
    traceback.print_exc()

print()
print("=" * 70)
print("VERDICT")
print("=" * 70)
