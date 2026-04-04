"""
AUDIT CALCUL TP/SL NQ vs ES - 28 JANVIER 2026
Analyse les différences entre NQ et ES
"""

# Données du log NQ (ligne 87)
nq_entry = 26187.75
nq_sl = 26182.50
nq_tp = 26199.25

nq_sl_distance = abs(nq_entry - nq_sl)
nq_tp_distance = abs(nq_tp - nq_entry)
nq_sl_ticks = nq_sl_distance / 0.25
nq_tp_ticks = nq_tp_distance / 0.25

# Données du log ES (ligne 20)
es_entry = 7037.75
es_sl = 7032.50
es_tp = 7046.75

es_sl_distance = abs(es_entry - es_sl)
es_tp_distance = abs(es_tp - es_entry)
es_sl_ticks = es_sl_distance / 0.25
es_tp_ticks = es_tp_distance / 0.25

print("="*80)
print("AUDIT CALCUL TP/SL NQ vs ES - 28 JANVIER 2026")
print("="*80)

print("\n" + "="*80)
print("NQ (Trade @ 23:58)")
print("="*80)
print(f"Entry: {nq_entry}")
print(f"SL: {nq_sl} - Distance: {nq_sl_distance:.2f} pts = {nq_sl_ticks:.0f} ticks")
print(f"TP: {nq_tp} - Distance: {nq_tp_distance:.2f} pts = {nq_tp_ticks:.0f} ticks")
print(f"R:R: {nq_tp_ticks/nq_sl_ticks:.2f}")
print(f"")
print(f"Config NQ:")
print(f"  sl_default: 28 ticks (7 pts)")
print(f"  sl_min: 20 ticks (5 pts)")
print(f"  sl_max: 40 ticks (10 pts)")
print(f"  tp_default: 35 ticks (8.75 pts)")
print(f"  tp_max: 50 ticks (12.5 pts)")
print(f"  min_rr_ratio: 1.25")
print(f"")
print(f"ANALYSE:")
print(f"  SL: {nq_sl_ticks:.0f} ticks OK (20 <= {nq_sl_ticks:.0f} <= 40) [OK]")
print(f"  TP: {nq_tp_ticks:.0f} ticks {'OK' if nq_tp_ticks <= 50 else 'TROP HAUT!'} ({nq_tp_ticks:.0f} <= 50) {'[OK]' if nq_tp_ticks <= 50 else '[X]'}")
print(f"  R:R: {nq_tp_ticks/nq_sl_ticks:.2f} {'OK' if nq_tp_ticks/nq_sl_ticks >= 1.25 else 'FAIBLE'} ({nq_tp_ticks/nq_sl_ticks:.2f} >= 1.25) {'[OK]' if nq_tp_ticks/nq_sl_ticks >= 1.25 else '[!]'}")

print("\n" + "="*80)
print("ES (Trade @ 08:02)")
print("="*80)
print(f"Entry: {es_entry}")
print(f"SL: {es_sl} - Distance: {es_sl_distance:.2f} pts = {es_sl_ticks:.0f} ticks")
print(f"TP: {es_tp} - Distance: {es_tp_distance:.2f} pts = {es_tp_ticks:.0f} ticks")
print(f"R:R: {es_tp_ticks/es_sl_ticks:.2f}")
print(f"")
print(f"Config ES:")
print(f"  sl_default: 20 ticks (5 pts)")
print(f"  sl_min: 16 ticks (4 pts)")
print(f"  sl_max: 28 ticks (7 pts)")
print(f"  tp_default: 24 ticks (6 pts)")
print(f"  tp_max: 32 ticks (8 pts)")
print(f"  min_rr_ratio: 1.20")
print(f"")
print(f"ANALYSE:")
print(f"  SL: {es_sl_ticks:.0f} ticks {'OK' if es_sl_ticks <= 28 else 'TROP HAUT!'} ({es_sl_ticks:.0f} <= 28) {'[OK]' if es_sl_ticks <= 28 else '[X]'}")
print(f"  TP: {es_tp_ticks:.0f} ticks {'OK' if es_tp_ticks <= 32 else 'TROP HAUT!'} ({es_tp_ticks:.0f} <= 32) {'[OK]' if es_tp_ticks <= 32 else '[X]'}")
print(f"  R:R: {es_tp_ticks/es_sl_ticks:.2f} {'OK' if es_tp_ticks/es_sl_ticks >= 1.20 else 'FAIBLE'} ({es_tp_ticks/es_sl_ticks:.2f} >= 1.20) {'[OK]' if es_tp_ticks/es_sl_ticks >= 1.20 else '[!]'}")

print("\n" + "="*80)
print("COMPARAISON NQ vs ES")
print("="*80)
print(f"")
print(f"| Métrique | NQ | ES | Ratio NQ/ES |")
print(f"|----------|----|----|-------------|")
print(f"| SL ticks | {nq_sl_ticks:.0f} | {es_sl_ticks:.0f} | {nq_sl_ticks/es_sl_ticks:.2f}x |")
print(f"| TP ticks | {nq_tp_ticks:.0f} | {es_tp_ticks:.0f} | {nq_tp_ticks/es_tp_ticks:.2f}x |")
print(f"| R:R | {nq_tp_ticks/nq_sl_ticks:.2f} | {es_tp_ticks/es_sl_ticks:.2f} | {(nq_tp_ticks/nq_sl_ticks)/(es_tp_ticks/es_sl_ticks):.2f}x |")

print("\n" + "="*80)
print("DIAGNOSTIC")
print("="*80)

# Vérifier si NQ dépasse les limites
nq_sl_ok = 20 <= nq_sl_ticks <= 40
nq_tp_ok = nq_tp_ticks <= 50
nq_rr_ok = (nq_tp_ticks/nq_sl_ticks) >= 1.25

es_sl_ok = 16 <= es_sl_ticks <= 28
es_tp_ok = es_tp_ticks <= 32
es_rr_ok = (es_tp_ticks/es_sl_ticks) >= 1.20

if nq_sl_ok and nq_tp_ok and nq_rr_ok:
    print("[OK] NQ: Tous les parametres sont dans les limites")
else:
    print("[X] NQ: Probleme detecte!")
    if not nq_sl_ok:
        print(f"  - SL hors limites: {nq_sl_ticks:.0f} ticks (20-40 requis)")
    if not nq_tp_ok:
        print(f"  - TP dépasse max: {nq_tp_ticks:.0f} ticks (max 50)")
    if not nq_rr_ok:
        print(f"  - R:R faible: {nq_tp_ticks/nq_sl_ticks:.2f} (min 1.25 requis)")

if es_sl_ok and es_tp_ok and es_rr_ok:
    print("[OK] ES: Tous les parametres sont dans les limites")
else:
    print("[X] ES: Probleme detecte!")
    if not es_sl_ok:
        print(f"  - SL hors limites: {es_sl_ticks:.0f} ticks (16-28 requis)")
    if not es_tp_ok:
        print(f"  - TP dépasse max: {es_tp_ticks:.0f} ticks (max 32)")
    if not es_rr_ok:
        print(f"  - R:R faible: {es_tp_ticks/es_sl_ticks:.2f} (min 1.20 requis)")

print("\n" + "="*80)
print("HYPOTHÈSE SUR LE PROBLÈME NQ")
print("="*80)

if nq_tp_ticks > 35:
    print(f"")
    print(f"TP NQ est à {nq_tp_ticks:.0f} ticks au lieu de ~35 (default).")
    print(f"")
    print(f"Causes possibles:")
    print(f"1. Aucun obstacle détecté entre Entry et TP max")
    print(f"   -> TP placé à tp_max_ticks = 50")
    print(f"")
    print(f"2. Obstacle détecté mais TRÈS LOIN")
    print(f"   -> TP placé avant obstacle")
    print(f"   -> Obstacle a: {nq_entry + (nq_tp_ticks + 2) * 0.25:.2f}")
    print(f"      (TP + buffer de 2 ticks)")
    print(f"")
    print(f"3. Rectangle détecté comme obstacle")
    print(f"   -> Log WHY montre: 'BEFORE_RECT_ROUGE' ou similaire")
    print(f"")
    print(f"RECOMMANDATION:")
    print(f"  Vérifier dans le log WHY complet la colonne 'tp_based_on'")
    print(f"  pour comprendre pourquoi le TP est si élevé.")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
print("")
if nq_sl_ok and nq_tp_ok and es_sl_ok and es_tp_ok:
    print("[OK] Les calculs respectent les limites configurees")
    print("[!] Mais le TP NQ est proche du max (46/50 ticks)")
    print("   -> Normal si aucun obstacle detecte")
    print("   -> Verifier que les niveaux MenthorQ NQ sont bien charges")
else:
    print("[X] Des valeurs depassent les limites!")
    print("   -> Recompiler le DLL avec les corrections du 28/01")
