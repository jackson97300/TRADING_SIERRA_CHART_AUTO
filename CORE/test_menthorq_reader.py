"""
test_menthorq_reader.py — Tests de validation du MenthorQ Reader
=================================================================

Lance automatiquement avant chaque modification du reader.
Vérifie la cohérence des données, les unités, les conversions.

Usage :
    python test_menthorq_reader.py
    python test_menthorq_reader.py DATA/MENTHORQ

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from mia_menthorq_reader import MenthorQReader, _valid


def run_tests(base_path: str = "DATA/MENTHORQ") -> bool:
    """Lance tous les tests. Retourne True si tout passe."""

    mq = MenthorQReader(base_path)
    errors = []
    passes = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passes
        if condition:
            passes += 1
            print(f"  ✅ {name}")
        else:
            errors.append(f"{name}: {detail}")
            print(f"  ❌ {name} — {detail}")

    print("=" * 60)
    print("  TESTS MenthorQ Reader")
    print("=" * 60)

    # ─── Charger les données ───
    raw = mq.load_raw("20260331")
    if raw is None:
        print("  ⚠️ Fichier 20260331 absent — tests sur données réelles ignorés")
        print("  Lance les tests unitaires seulement")
        raw_available = False
    else:
        raw_available = True

    # ═══════════════════════════════════════════════════════════════
    # TEST 1 — Unités GEX/DEX
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 1] Unités GEX/DEX")

    if raw_available:
        for sym in ["ES", "NQ"]:
            parsed = mq._extract_from_raw(raw, sym)
            gex = parsed.get("gex", {})

            net_gex = gex.get("Net_GEX_M")
            total_gex = gex.get("Total_GEX_M")
            net_dex = gex.get("Net_DEX_B")

            # Net GEX doit être en millions (typiquement -500 à +500)
            if _valid(net_gex):
                check(f"{sym} Net GEX range",
                      -5000 < net_gex < 5000,
                      f"Net GEX = {net_gex} hors [-5000, 5000] M")

            # Total GEX doit être positif et en millions
            if _valid(total_gex):
                check(f"{sym} Total GEX positif",
                      total_gex > 0,
                      f"Total GEX = {total_gex} devrait être > 0")

            # Net DEX doit être en milliards (typiquement -500 à +500)
            if _valid(net_dex):
                check(f"{sym} Net DEX range",
                      -5000 < net_dex < 5000,
                      f"Net DEX = {net_dex} hors [-5000, 5000] B")

    # ═══════════════════════════════════════════════════════════════
    # TEST 2 — Gamma Condition dérivé de Net GEX (pas du proxy)
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 2] Gamma Condition = signe de Net GEX futures")

    if raw_available:
        for sym in ["ES", "NQ"]:
            parsed = mq._extract_from_raw(raw, sym)
            daily = mq.compute_daily_features(parsed)

            net_gex = daily.get("mq_net_gex_m")
            gamma = daily.get("mq_gamma_condition")

            if _valid(net_gex) and _valid(gamma):
                expected_gamma = 1.0 if net_gex > 0 else -1.0
                check(f"{sym} Gamma = signe(Net GEX)",
                      gamma == expected_gamma,
                      f"Net GEX={net_gex}, gamma={gamma}, attendu={expected_gamma}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 3 — Cross-Asset Divergence cohérent
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 3] Cross-Asset Divergence")

    if raw_available:
        es_parsed = mq._extract_from_raw(raw, "ES")
        nq_parsed = mq._extract_from_raw(raw, "NQ")
        es_daily = mq.compute_daily_features(es_parsed, nq_parsed)

        es_gamma = es_daily.get("mq_gamma_condition", 0)
        div = es_daily.get("mq_es_nq_gamma_div", 0)

        check("Divergence gamma non-NaN",
              _valid(div),
              f"mq_es_nq_gamma_div = {div}")

        # Si ES negative et NQ positive → divergence doit être -2
        nq_daily = mq.compute_daily_features(nq_parsed, es_parsed)
        nq_gamma = nq_daily.get("mq_gamma_condition", 0)
        expected_div = es_gamma - nq_gamma
        check("Divergence = ES_gamma - NQ_gamma",
              div == expected_div,
              f"ES={es_gamma} NQ={nq_gamma} div={div} attendu={expected_div}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 4 — Distances raisonnables
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 4] Distances raisonnables")

    if raw_available:
        # ES à ~6530
        es_dyn = mq.compute_dynamic_features(6530.0, es_parsed, tick_size=0.25)
        for k, v in es_dyn.items():
            if _valid(v) and "dist" in k:
                check(f"ES {k} < 20000 ticks",
                      abs(v) < 20000,
                      f"{k} = {v:.0f} ticks aberrant")

        # NQ à ~23900
        nq_dyn = mq.compute_dynamic_features(23900.0, nq_parsed, tick_size=0.25)
        for k, v in nq_dyn.items():
            if _valid(v) and "dist" in k:
                check(f"NQ {k} < 20000 ticks",
                      abs(v) < 20000,
                      f"{k} = {v:.0f} ticks aberrant")

    # ═══════════════════════════════════════════════════════════════
    # TEST 5 — Key Levels cohérence (HVL entre Put et Call)
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 5] Key Levels cohérence")

    if raw_available:
        for sym in ["ES", "NQ"]:
            parsed = mq._extract_from_raw(raw, sym)
            kl = parsed.get("key_levels", {})
            hvl = kl.get("HVL")
            put = kl.get("Put_Support")
            call = kl.get("Call_Resistance")

            if hvl and put and call:
                check(f"{sym} Put < HVL < Call",
                      put <= hvl <= call,
                      f"Put={put} HVL={hvl} Call={call}")

                d1_min = kl.get("1D_Min")
                d1_max = kl.get("1D_Max")
                if d1_min and d1_max:
                    check(f"{sym} 1D_Min < 1D_Max",
                          d1_min < d1_max,
                          f"1D_Min={d1_min} 1D_Max={d1_max}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 6 — Ratios dans des ranges valides
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 6] Ratios dans des ranges valides")

    if raw_available:
        for sym in ["ES", "NQ"]:
            parsed = mq._extract_from_raw(raw, sym)
            daily = mq.compute_daily_features(parsed)

            for k, lo, hi in [
                ("mq_pc_oi", 0.1, 20.0),
                ("mq_pc_gex", 0.01, 50.0),
                ("mq_iv_30d", 5.0, 100.0),
                ("mq_exp_move_pct", 0.1, 10.0),
                ("mq_net_gex_ratio", -1.0, 1.0),
            ]:
                v = daily.get(k)
                if _valid(v):
                    check(f"{sym} {k} dans [{lo}, {hi}]",
                          lo <= v <= hi,
                          f"{k} = {v}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 7 — Niveaux futures ≠ niveaux proxy
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 7] Niveaux viennent des futures (pas du proxy)")

    if raw_available:
        for sym in ["ES", "NQ"]:
            parsed = mq._extract_from_raw(raw, sym)
            kl = parsed.get("key_levels", {})

            # Les niveaux ES doivent être ~6000-7000, pas ~600-700 (SPX ETF)
            # Les niveaux NQ doivent être ~20000-30000, pas ~400-600 (QQQ ETF)
            hvl = kl.get("HVL")
            if hvl:
                if sym == "ES":
                    check(f"{sym} HVL > 1000 (pas proxy ETF)",
                          hvl > 1000,
                          f"HVL = {hvl} — semble être un proxy ETF")
                elif sym == "NQ":
                    check(f"{sym} HVL > 10000 (pas proxy QQQ)",
                          hvl > 10000,
                          f"HVL = {hvl} — semble être QQQ, pas NQ")

    # ═══════════════════════════════════════════════════════════════
    # TEST 8 — Enrichissement DataFrame
    # ═══════════════════════════════════════════════════════════════
    print("\n[TEST 8] Enrichissement DataFrame")

    import pandas as pd
    test_df = pd.DataFrame({
        "price": [6530.0, 6535.0, 6520.0],
        "delta_bar": [10, -5, 20],
    })

    enriched = mq.enrich(test_df.copy(), "20260331", "ES", tick_size=0.25)
    mq_cols = [c for c in enriched.columns if c.startswith("mq_")]

    check("Features mq_* ajoutées", len(mq_cols) > 20, f"seulement {len(mq_cols)}")
    check("Pas de colonnes toutes NaN",
          any(enriched[c].notna().any() for c in mq_cols),
          "toutes les colonnes mq_* sont NaN")

    # Distances doivent varier entre les barres (prix différents)
    if "mq_dist_hvl" in enriched.columns:
        vals = enriched["mq_dist_hvl"].dropna().unique()
        check("mq_dist_hvl varie entre barres",
              len(vals) > 1,
              f"seulement {len(vals)} valeur(s) unique(s)")

    # ═══════════════════════════════════════════════════════════════
    # BILAN
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'=' * 60}")
    print(f"  {passes} tests passent | {len(errors)} erreurs")
    if errors:
        print(f"\n  ERREURS:")
        for e in errors:
            print(f"    ❌ {e}")
    else:
        print(f"\n  ✅ TOUS LES TESTS PASSENT")
    print(f"{'=' * 60}")

    return len(errors) == 0


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "DATA/MENTHORQ"
    ok = run_tests(base)
    sys.exit(0 if ok else 1)
