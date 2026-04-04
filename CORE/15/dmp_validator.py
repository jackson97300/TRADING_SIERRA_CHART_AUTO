#!/usr/bin/env python3
"""
dmp_validator.py — Validateur quotidien DMP Schema 3.5.2
=========================================================
Détecte les bugs AVANT d'accumuler 3 semaines de données mortes.

Usage:
    python dmp_validator.py 20260310_NQ.jsonl
    python dmp_validator.py 20260310_NQ.jsonl 20260310_ES.jsonl
    python dmp_validator.py *.jsonl

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\dmp_validator.py
Date: 2026-03-10
Schema: 3.5.2 — 246 colonnes
"""

import json, sys, os
import numpy as np
from collections import Counter

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — Schema 3.5.2
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA_VERSION = "3.5.2"
EXPECTED_COLS = 246

# Signaux qui DOIVENT firer (Extension Lines persistantes, toujours actives)
# (colonne, seuil_min_pct, description)
MUST_FIRE = [
    ("bn_color_up",      0.30, "COLOR UP FP — pullback simple"),
    ("bn_color_dn",      0.30, "COLOR DN FP — pullback simple"),
    ("bn_pressure_ask",  0.15, "TRIPLE/DOUBLE ASK FP"),
    ("bn_pressure_bid",  0.15, "TRIPLE/DOUBLE BID FP"),
    ("bar_color_up",     0.20, "COLOR UP BARRES"),
    ("bar_color_dn",     0.20, "COLOR DN BARRES"),
    ("bar_pressure_ask", 0.15, "TRIPLE/DOUBLE ASK BARRES"),
    ("bar_pressure_bid", 0.15, "TRIPLE/DOUBLE BID BARRES"),
]

# Signaux qui DEVRAIENT firer (au moins 1 fois sur 50+ barres)
SHOULD_FIRE = [
    ("bn_long_up",       "LONG UP — barre longue haussière"),
    ("bn_long_dn",       "LONG DN — barre longue baissière"),
    ("bn_color_up_2",    "COLOR UP 2 — double stacké (continuation)"),
    ("bn_color_dn_2",    "COLOR DN 2 — double stacké"),
    ("bar_edge_buy",     "EDGE BUY BARRES — imbalance acheteur"),
    ("bar_edge_sell",    "EDGE SELL BARRES — imbalance vendeur"),
    ("fp_edge_buy",      "EDGE BUY FP — imbalance footprint"),
    ("fp_edge_sell",     "EDGE SELL FP — imbalance footprint"),
    ("bar_long_up_bar",  "LONG UP BAR BARRES"),
    ("bar_long_dn_bar",  "LONG DN BAR BARRES"),
]

# Distances qui doivent être non-null régulièrement
MUST_HAVE_DIST = [
    ("dist_ext_color_up",  0.40, "COLOR UP distance (API CBBAC)"),
    ("dist_ext_color_dn",  0.40, "COLOR DN distance (API CBBAC)"),
    ("dist_ext_edge_buy",  0.05, "EDGE BUY distance (tracker 6D)"),
    ("dist_ext_edge_sell", 0.05, "EDGE SELL distance (tracker 6D)"),
]

# Features range trading qui doivent varier
MUST_VARY = [
    ("range_pos",        5, "Position dans le range (%)"),
    ("range_size_ticks", 3, "Taille du range"),
    ("momentum_3b",      5, "Momentum 3 barres"),
    ("momentum_5b",      5, "Momentum 5 barres"),
    ("cvd_bar_delta",    5, "CVD per-bar"),
    ("bars_in_va",       5, "Barres consécutives dans la VA"),
    ("bn_score_raw",     2, "Score BN composite"),
    ("bn_score_bull",    2, "Score BN bull"),
    ("bn_score_bear",    2, "Score BN bear"),
]

# Colonnes avec bornes logiques
BOUNDS = [
    ("price",             1000,  50000),
    ("atr",               10,    5000),
    ("range_pos",         0,     100.01),
    ("va_position_pct",   -5,    5),
    ("ask_pct",           0,     1.01),
    ("bid_pct",           0,     1.01),
    ("delta_bar_vol_norm",-1.01, 1.01),
    ("bn_score_raw",      -1.5,  1.5),
    ("bn_score_bull",     0,     1.5),
    ("bn_score_bear",     0,     1.5),
]

# Signaux US-only (0 attendu en London/Asia, warning seulement si 0 en US)
US_ONLY_SIGNALS = [
    "delta_divergence",
    "n_big_ask_t1", "n_big_bid_t1",
    "n_big_ask_t2", "n_big_bid_t2",
    "n_big_ask_t3", "n_big_bid_t3",
    "bn_volume_up", "bn_volume_dn",
]


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f]


def validate(path):
    lines = load_jsonl(path)
    if not lines:
        print(f"  ❌ ERREUR: fichier vide")
        return 1

    sym = lines[0].get('sym', '?')
    n = len(lines)
    ncols = len(lines[0])
    sessions = Counter(l.get('session_id', '?') for l in lines)
    
    errors = []
    warnings = []
    ok = 0
    
    sess_str = ", ".join(f"{s}={c}" for s, c in sessions.items())
    print(f"\n{'='*70}")
    print(f"  {sym} — {os.path.basename(path)}")
    print(f"  {n} barres | {ncols} colonnes | {sess_str}")
    print(f"{'='*70}\n")

    # ─── 1. SCHEMA ───────────────────────────────────────────────────────
    if ncols != EXPECTED_COLS:
        errors.append(f"SCHEMA: {ncols} colonnes (attendu {EXPECTED_COLS})")
    else:
        ok += 1
    
    # Vérifier colonnes critiques présentes
    critical_cols = ['bn_color_up_2', 'bn_color_dn_2', 'dist_ext_edge_buy', 
                     'dist_ext_edge_sell', 'big_ask_cluster_20t_t3',
                     'retest_high_count', 'bars_since_retest_low']
    for c in critical_cols:
        if c not in lines[0]:
            errors.append(f"COLONNE MANQUANTE: {c}")
        else:
            ok += 1

    # ─── 2. TIMESTAMPS ───────────────────────────────────────────────────
    ts_list = [l['ts'] for l in lines]
    if ts_list != sorted(ts_list):
        errors.append("TIMESTAMPS non monotones")
    else:
        ok += 1
    
    gaps = []
    for i in range(1, len(ts_list)):
        diff = (ts_list[i] - ts_list[i-1]) / 60000
        if diff > 5:
            gaps.append(f"  gap {diff:.0f}min à barre {i}")
    if gaps and len(gaps) > 3:
        warnings.append(f"GAPS: {len(gaps)} trous > 5min")

    # ─── 3. SIGNAUX MUST_FIRE ────────────────────────────────────────────
    print("  ── Signaux persistants (doivent firer) ──")
    for col, min_pct, desc in MUST_FIRE:
        vals = [l.get(col, 0) for l in lines]
        nz = sum(1 for v in vals if v and v != 0)
        pct = nz / n if n > 0 else 0
        if pct < min_pct and n >= 30:
            errors.append(f"{col}: {nz}/{n} ({pct:.0%}) < {min_pct:.0%} — {desc}")
            print(f"  ❌ {col:25s} {nz:>3d}/{n} ({pct:>5.0%}) — MORT")
        else:
            ok += 1
            print(f"  ✅ {col:25s} {nz:>3d}/{n} ({pct:>5.0%})")

    # ─── 4. SIGNAUX SHOULD_FIRE ──────────────────────────────────────────
    print(f"\n  ── Signaux per-bar (devraient firer) ──")
    for col, desc in SHOULD_FIRE:
        vals = [l.get(col, 0) for l in lines]
        nz = sum(1 for v in vals if v and v != 0)
        if nz == 0 and n >= 50:
            warnings.append(f"{col}: 0/{n} — {desc}")
            print(f"  ⚠️ {col:25s}   0/{n} — jamais firé")
        elif nz == 0:
            print(f"  · {col:25s}   0/{n} (< 50 barres, normal)")
        else:
            ok += 1
            print(f"  ✅ {col:25s} {nz:>3d}/{n}")

    # ─── 5. DISTANCES EXTENSION LINES ────────────────────────────────────
    print(f"\n  ── Distances Extension Lines ──")
    for col, min_pct, desc in MUST_HAVE_DIST:
        vals = [l.get(col) for l in lines]
        nn = sum(1 for v in vals if v is not None)
        pct = nn / n if n > 0 else 0
        if pct < min_pct and n >= 30:
            errors.append(f"{col}: {nn}/{n} non-null ({pct:.0%}) — {desc}")
            print(f"  ❌ {col:25s} {nn:>3d}/{n} non-null ({pct:>5.0%}) — CASSÉ")
        else:
            ok += 1
            if nn > 0:
                valid = [v for v in vals if v is not None]
                print(f"  ✅ {col:25s} {nn:>3d}/{n} non-null  [{min(valid):+.0f} → {max(valid):+.0f}]")
            else:
                print(f"  · {col:25s}   0/{n} (pas encore de données)")

    # ─── 6. FEATURES RANGE TRADING ───────────────────────────────────────
    print(f"\n  ── Features range trading (doivent varier) ──")
    for col, min_unique, desc in MUST_VARY:
        vals = [l.get(col) for l in lines]
        valid = [v for v in vals if v is not None]
        nu = len(set(valid))
        if nu < min_unique and n >= 30:
            errors.append(f"{col}: {nu} valeurs uniques < {min_unique} — CONSTANT")
            print(f"  ❌ {col:25s} nu={nu} — CONSTANT")
        elif len(valid) == 0:
            warnings.append(f"{col}: tout null")
            print(f"  ⚠️ {col:25s} tout null")
        else:
            ok += 1
            print(f"  ✅ {col:25s} nu={nu:>3d}  [{min(valid):>8.1f} → {max(valid):>8.1f}]")

    # ─── 7. COHÉRENCE LOGIQUE ────────────────────────────────────────────
    print(f"\n  ── Cohérence logique ──")
    checks = {
        "buy+sell=total":    0,
        "delta=buy-sell":    0,
        "ask+bid=1":         0,
        "score=bull-bear":   0,
        "inside_va↔va_pct":  0,
    }
    
    for l in lines:
        bv, sv, tv = l.get('buy_vol',0), l.get('sell_vol',0), l.get('total_vol',0)
        if abs(bv + sv - tv) <= 1: checks["buy+sell=total"] += 1
        
        db = l.get('delta_bar', 0)
        if abs(db - (bv - sv)) <= 1: checks["delta=buy-sell"] += 1
        
        ap, bp = l.get('ask_pct',0), l.get('bid_pct',0)
        if abs(ap + bp - 1.0) <= 0.01: checks["ask+bid=1"] += 1
        
        raw = l.get('bn_score_raw', 0)
        bull, bear = l.get('bn_score_bull', 0), l.get('bn_score_bear', 0)
        if abs(raw - (bull - bear)) <= 0.01: checks["score=bull-bear"] += 1
        
        iva = l.get('inside_cur_va', 0)
        vap = l.get('va_position_pct', 0.5)
        if (iva == 1 and 0 <= vap <= 1) or (iva == 0 and (vap < 0 or vap > 1)):
            checks["inside_va↔va_pct"] += 1
    
    for name, count in checks.items():
        if count == n:
            ok += 1
            print(f"  ✅ {name:25s} {count}/{n}")
        else:
            errors.append(f"{name}: {count}/{n} cohérent")
            print(f"  ❌ {name:25s} {count}/{n}")

    # ─── 8. BORNES ───────────────────────────────────────────────────────
    print(f"\n  ── Bornes logiques ──")
    bounds_ok = 0
    for col, lo, hi in BOUNDS:
        vals = [l.get(col) for l in lines]
        valid = [v for v in vals if v is not None]
        if not valid:
            continue
        bad = sum(1 for v in valid if v < lo or v > hi)
        if bad > 0:
            errors.append(f"{col}: {bad} valeurs hors [{lo}, {hi}]")
            print(f"  ❌ {col:25s} {bad} hors bornes [{lo}, {hi}]")
        else:
            bounds_ok += 1
    print(f"  ✅ {bounds_ok}/{len(BOUNDS)} checks passent")
    ok += bounds_ok

    # ─── 9. SIGNAUX US-ONLY ─────────────────────────────────────────────
    has_us = 'US' in sessions
    if has_us:
        print(f"\n  ── Signaux US-only ──")
        us_lines = [l for l in lines if l.get('session_id') == 'US']
        for col in US_ONLY_SIGNALS:
            nz = sum(1 for l in us_lines if l.get(col, 0) != 0 and l.get(col) is not None)
            if nz == 0 and len(us_lines) >= 60:
                warnings.append(f"{col}: 0/{len(us_lines)} en US — devrait firer")
                print(f"  ⚠️ {col:25s} 0/{len(us_lines)} en US")
            elif nz > 0:
                ok += 1
                print(f"  ✅ {col:25s} {nz}/{len(us_lines)} en US")

    # ─── 10. COLONNES MORTES ─────────────────────────────────────────────
    all_null = []
    all_zero = []
    for col in lines[0].keys():
        if col in ('sym', 'contract', 'session_id'):
            continue
        vals = [l.get(col) for l in lines]
        if all(v is None for v in vals):
            all_null.append(col)
        elif all(v == 0 or v is None for v in vals):
            valid = [v for v in vals if v is not None]
            if valid and all(v == 0 for v in valid):
                all_zero.append(col)
    
    # Colonnes attendues null
    expected_null = {'dist_ext_long_up', 'dist_ext_long_dn',
                     'dist_mq_call_0dte', 'dist_mq_put_0dte',  # null hors US
                     'bars_since_retest_high', 'bars_since_retest_low',
                     'dist_big_ask_nearest_up', 'dist_big_ask_nearest_dn',
                     'dist_big_bid_nearest_up', 'dist_big_bid_nearest_dn'}
    
    unexpected_null = [c for c in all_null if c not in expected_null]
    
    print(f"\n  ── Colonnes mortes ──")
    print(f"  NULL attendu: {len([c for c in all_null if c in expected_null])}")
    if unexpected_null:
        for c in unexpected_null:
            warnings.append(f"COLONNE NULL INATTENDUE: {c}")
        print(f"  ⚠️ NULL inattendu: {', '.join(unexpected_null)}")
    
    # Colonnes 0 attendues (London/Asia = pas de big orders)
    expected_zero_london = {'n_big_ask_t1','n_big_bid_t1','n_big_ask_t2','n_big_bid_t2',
                            'n_big_ask_t3','n_big_bid_t3','n_big_ask_t4','n_big_bid_t4',
                            'big_ask_cluster_20t','big_bid_cluster_20t',
                            'big_ask_cluster_50t','big_bid_cluster_50t',
                            'big_ask_cluster_20t_t1','big_bid_cluster_20t_t1',
                            'big_ask_cluster_20t_t2','big_bid_cluster_20t_t2',
                            'big_ask_cluster_20t_t3','big_bid_cluster_20t_t3',
                            'big_ask_cluster_20t_t4','big_bid_cluster_20t_t4',
                            'bn_absorb_ask','bn_absorb_bid',
                            'bn_volume_up','bn_volume_dn',
                            'delta_divergence',
                            'vah_touches_20b','val_touches_20b'}
    
    unexpected_zero = [c for c in all_zero if c not in expected_zero_london 
                       and not c.startswith('open_') and c != 'session'
                       and c != 'rule_80pct' and c != 'vwap_triple_align'
                       and c != 'comp_vpoc_align_20_50' and c != 'comp_vpoc_align_day_20'
                       and c != 'bool_va_confluence' and c not in ('lvn_between','hvn_between',
                       'lvn_confluence_count','session_hvn_count','session_lvn_count',
                       'vix_above_hvl','bool_near_level','bool_ib_inside',
                       'new_swing_high','new_swing_low','ib_broken_up','ib_broken_down',
                       'retest_high_count','retest_low_count',
                       'retest_high_delta_div','retest_low_delta_div',
                       'gex_cluster_count','vwap_ma_align','ma_trend',
                       'high_pullback_delta','low_pullback_delta')]
    
    if unexpected_zero and has_us:
        for c in unexpected_zero[:5]:
            warnings.append(f"COLONNE TOUT ZÉRO (US): {c}")
        if unexpected_zero:
            print(f"  ⚠️ Tout zéro inattendu: {', '.join(unexpected_zero[:5])}")
    
    alive = ncols - len(all_null) - len(all_zero)
    print(f"  Vivantes: {alive} | Null: {len(all_null)} | Zéro: {len(all_zero)}")

    # ═══════════════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    if errors:
        print(f"  {len(errors)} ERREUR(S) — {'🔴' * len(errors)}")
        for e in errors:
            print(f"    ❌ {e}")
    if warnings:
        print(f"  {len(warnings)} WARNING(S) — {'🟡' * min(len(warnings), 10)}")
        for w in warnings:
            print(f"    ⚠️ {w}")
    if not errors:
        print(f"  ✅ DONNÉES PROPRES — {ok} checks passent")
        print(f"     Schema {SCHEMA_VERSION}, {ncols} colonnes, {n} barres")
    print(f"{'='*70}\n")
    
    return len(errors)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} fichier.jsonl [fichier2.jsonl ...]")
        print(f"       python {sys.argv[0]} *.jsonl")
        sys.exit(1)
    
    total_errors = 0
    for path in sys.argv[1:]:
        if not os.path.exists(path):
            print(f"  ❌ Fichier non trouvé: {path}")
            total_errors += 1
            continue
        total_errors += validate(path)
    
    if total_errors == 0:
        print("🟢 TOUS LES FICHIERS SONT PROPRES — collecte long terme OK")
    else:
        print(f"🔴 {total_errors} ERREUR(S) — CORRIGER AVANT DE COLLECTER")
    
    sys.exit(total_errors)


if __name__ == "__main__":
    main()
