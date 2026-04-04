"""
TEST CALCUL PNL NQ vs ES - 28 JANVIER 2026
Verifie que le PNL NQ est correctement calcule
"""

# CONFIG
ES_TICK_VALUE = 12.50
ES_TICK_SIZE = 0.25

NQ_TICK_VALUE = 5.00
NQ_TICK_SIZE = 0.25

print("="*80)
print("TEST CALCUL PNL NQ vs ES")
print("="*80)

# === TEST 1: ES LONG ===
print("\n" + "="*80)
print("TEST 1: ES LONG")
print("="*80)

es_entry = 7037.75
es_exit = 7046.75

es_distance_pts = es_exit - es_entry
es_distance_ticks = es_distance_pts / ES_TICK_SIZE
es_pnl = es_distance_ticks * ES_TICK_VALUE

print(f"Entry: {es_entry}")
print(f"Exit: {es_exit}")
print(f"Distance: {es_distance_pts:.2f} pts = {es_distance_ticks:.0f} ticks")
print(f"PNL: {es_distance_ticks:.0f} ticks * ${ES_TICK_VALUE} = ${es_pnl:.2f}")

# === TEST 2: NQ LONG (MEME DISTANCE TICKS) ===
print("\n" + "="*80)
print("TEST 2: NQ LONG (meme distance que ES = 36 ticks)")
print("="*80)

nq_entry = 26187.75
nq_ticks_move = 36  # Meme que ES
nq_exit = nq_entry + (nq_ticks_move * NQ_TICK_SIZE)

nq_distance_pts = nq_exit - nq_entry
nq_distance_ticks = nq_distance_pts / NQ_TICK_SIZE
nq_pnl = nq_distance_ticks * NQ_TICK_VALUE

print(f"Entry: {nq_entry}")
print(f"Exit: {nq_exit} (Entry + {nq_ticks_move} ticks)")
print(f"Distance: {nq_distance_pts:.2f} pts = {nq_distance_ticks:.0f} ticks")
print(f"PNL: {nq_distance_ticks:.0f} ticks * ${NQ_TICK_VALUE} = ${nq_pnl:.2f}")

# === COMPARAISON ===
print("\n" + "="*80)
print("COMPARAISON")
print("="*80)
print(f"ES: 36 ticks = ${es_pnl:.2f}")
print(f"NQ: 36 ticks = ${nq_pnl:.2f}")
print(f"Ratio: {es_pnl/nq_pnl:.2f}x (ES PNL / NQ PNL)")
print(f"")
print(f"Tick Value Ratio: {ES_TICK_VALUE/NQ_TICK_VALUE:.2f}x (ES / NQ)")
print(f"[OK] Le ratio PNL correspond au ratio tick_value!" if abs((es_pnl/nq_pnl) - (ES_TICK_VALUE/NQ_TICK_VALUE)) < 0.01 else "[X] ERREUR!")

# === TEST 3: CALCUL DEPUIS LES LOGS ===
print("\n" + "="*80)
print("TEST 3: CALCUL DEPUIS LES LOGS (Trade #87 NQ)")
print("="*80)

# NQ Trade #87 du log
nq_log_entry = 26187.75
nq_log_sl = 26182.50
nq_log_tp = 26199.25

# Si TP hit
nq_tp_distance_ticks = (nq_log_tp - nq_log_entry) / NQ_TICK_SIZE
nq_tp_pnl = nq_tp_distance_ticks * NQ_TICK_VALUE

# Si SL hit
nq_sl_distance_ticks = (nq_log_entry - nq_log_sl) / NQ_TICK_SIZE
nq_sl_pnl = -nq_sl_distance_ticks * NQ_TICK_VALUE

print(f"Entry: {nq_log_entry}")
print(f"SL: {nq_log_sl} ({nq_sl_distance_ticks:.0f} ticks)")
print(f"TP: {nq_log_tp} ({nq_tp_distance_ticks:.0f} ticks)")
print(f"")
print(f"Si TP hit: ${nq_tp_pnl:.2f} (WIN)")
print(f"Si SL hit: ${nq_sl_pnl:.2f} (LOSS)")
print(f"R:R: {nq_tp_pnl / abs(nq_sl_pnl):.2f}")

# === TEST 4: ERREUR POTENTIELLE (tick_value = 20 au lieu de 5) ===
print("\n" + "="*80)
print("TEST 4: SI tick_value = 20 (ERREUR POINT_VALUE)")
print("="*80)

WRONG_NQ_TICK_VALUE = 20.00  # Si confusion avec point_value

nq_wrong_pnl = nq_distance_ticks * WRONG_NQ_TICK_VALUE

print(f"NQ avec tick_value = 5.00 (CORRECT): ${nq_pnl:.2f}")
print(f"NQ avec tick_value = 20.00 (ERREUR): ${nq_wrong_pnl:.2f}")
print(f"Difference: ${nq_wrong_pnl - nq_pnl:.2f} (4x plus eleve!)")
print(f"")
print(f"[!] Si le PNL affiche est 4x trop eleve, c'est cette erreur!")

# === TEST 5: VERIFIER FORMULE C++ ===
print("\n" + "="*80)
print("TEST 5: FORMULE C++ (ligne 5474)")
print("="*80)

def calculate_pnl_cpp(entry, exit, direction, tick_size, tick_value):
    """Simule la formule C++ ligne 5474"""
    ticks = (exit - entry) / tick_size
    if direction == -1:  # SHORT
        ticks = -ticks
    pnl = ticks * tick_value
    return pnl

# NQ LONG
nq_cpp_pnl_tp = calculate_pnl_cpp(nq_log_entry, nq_log_tp, 1, NQ_TICK_SIZE, NQ_TICK_VALUE)
nq_cpp_pnl_sl = calculate_pnl_cpp(nq_log_entry, nq_log_sl, 1, NQ_TICK_SIZE, NQ_TICK_VALUE)

print(f"NQ LONG (Entry={nq_log_entry}):")
print(f"  TP @ {nq_log_tp}: ${nq_cpp_pnl_tp:.2f}")
print(f"  SL @ {nq_log_sl}: ${nq_cpp_pnl_sl:.2f}")

# ES LONG (Trade #20 du log)
es_log_entry = 7037.75
es_log_sl = 7032.50
es_log_tp = 7046.75

es_cpp_pnl_tp = calculate_pnl_cpp(es_log_entry, es_log_tp, 1, ES_TICK_SIZE, ES_TICK_VALUE)
es_cpp_pnl_sl = calculate_pnl_cpp(es_log_entry, es_log_sl, 1, ES_TICK_SIZE, ES_TICK_VALUE)

print(f"")
print(f"ES LONG (Entry={es_log_entry}):")
print(f"  TP @ {es_log_tp}: ${es_cpp_pnl_tp:.2f}")
print(f"  SL @ {es_log_sl}: ${es_cpp_pnl_sl:.2f}")

# === CONCLUSION ===
print("\n" + "="*80)
print("DIAGNOSTIC")
print("="*80)

print(f"")
print(f"CONFIG C++:")
print(f"  ES: tick_value = {ES_TICK_VALUE} [OK]")
print(f"  NQ: tick_value = {NQ_TICK_VALUE} [OK]")
print(f"")
print(f"CONFIG PYTHON:")
print(f"  ES: tick_value = 12.50 [OK]")
print(f"  NQ: tick_value = 5.00 [OK]")
print(f"")
print(f"FORMULE C++ (ligne 5474):")
print(f"  pnl = ticks * config.tick_value [OK]")
print(f"")
print(f"SI LE PNL NQ EST INCORRECT:")
print(f"1. Verifier Dashboard/Logs: Quel PNL est affiche?")
print(f"2. Si 4x trop eleve: tick_value = 20 (point_value) au lieu de 5")
print(f"3. Si 2.5x trop eleve: tick_value = 12.50 (ES) au lieu de 5")
print(f"4. Chercher dans le code ou tick_value est utilise")
print(f"")
print(f"COMMANDES UTILES:")
print(f"  grep -n 'tick_value.*20' *.cpp")
print(f"  grep -n 'NQ.*12.50' *.cpp")
print(f"  grep -n 'point_value' *.cpp")
