"""Test empirique du fix get_dashboard() avec JWT owner.

Lance 3 iterations de get_dashboard() et affiche la reponse complete.
Verifie qu'on recoit bien tier=owner + conseil_global complet.
"""
import sys, json, time
sys.path.insert(0, ".")

# Import du paper_trader qu'on vient de modifier
from CORE.mia_paper_trader import get_dashboard, _get_service_token

print("=" * 70)
print("TEST FIX — get_dashboard() avec JWT owner service")
print("=" * 70)

# Test token generation
t = _get_service_token()
print(f"\n[1] Service token genere: {t[:60]}... (len {len(t)})")

# Test 3 iterations avec cache
for i in range(3):
    d = get_dashboard()
    if d is None:
        print(f"[{i+1}] FETCH FAIL")
        continue

    tier = d.get("tier")
    cg = d.get("conseil_global", {})
    es = cg.get("es", {})
    nq = cg.get("nq", {})
    print(f"\n[{i+1}] HTTP OK | tier={tier} | payload={len(json.dumps(d))} bytes")
    print(f"    ES : action={es.get('action')} freshness={es.get('freshness')} conf={es.get('confidence')} favor={es.get('favor')}")
    print(f"    ES signal_id: {(es.get('signal_id') or '')[:24]}")
    print(f"    NQ : action={nq.get('action')} freshness={nq.get('freshness')} conf={nq.get('confidence')} favor={nq.get('favor')}")
    print(f"    NQ signal_id: {(nq.get('signal_id') or '')[:24]}")

    # Check instrument richness
    es_inst = d.get("es", {})
    print(f"    ES panels : {list(es_inst.keys())[:8]}...")

    if i < 2:
        time.sleep(2)

# Verifier token cache
t2 = _get_service_token()
print(f"\n[2] Token cache check: same token = {t == t2}")

print("\n" + "=" * 70)
print("VERDICT : tier=owner attendu + conseil_global NON vide")
print("=" * 70)
