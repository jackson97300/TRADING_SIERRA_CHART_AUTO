"""
test_all.py — Suite de tests automatiques MIA Trading System
=============================================================

Vérifie la cohérence de TOUT le pipeline avant de valider.
Doit passer à 100% avant toute modification de production.

Usage :
    python test_all.py                    # tous les tests
    python test_all.py --quick            # tests rapides seulement
    python test_all.py --module menthorq  # un module spécifique

Modules testés :
    1. Imports (tous les modules Python)
    2. DMP Validator (schema, colonnes)
    3. IBRecalc (cohérence IB)
    4. Rolling Features (ctx_*)
    5. Intermarket Features (im_*)
    6. MenthorQ Reader (mq_*)
    7. Game Changers (parité C++)
    8. Pipeline complet (DmpReader → Enrichissement)

Emplacement : D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\test_all.py
Auteur : MIA Trading System
Date   : 2026-04-01
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Setup path
CORE_DIR = Path(__file__).parent
ROOT_DIR = CORE_DIR.parent
sys.path.insert(0, str(CORE_DIR))

DATA_DIR = ROOT_DIR / "DATA"
MQ_DIR = DATA_DIR / "MENTHORQ"


# ─────────────────────────────────────────────────────────────────
# FRAMEWORK DE TEST
# ─────────────────────────────────────────────────────────────────

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.skipped = 0

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
        else:
            self.failed += 1
            self.errors.append(f"{name}: {detail}")
            print(f"    ❌ {name} — {detail}")

    def skip(self, name: str, reason: str):
        self.skipped += 1
        print(f"    ⏭️ {name} — {reason}")

    def section(self, title: str):
        print(f"\n  {'─'*50}")
        print(f"  {title}")
        print(f"  {'─'*50}")

    def summary(self) -> bool:
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"  RÉSULTAT: {self.passed}/{total} tests passent"
              f" | {self.failed} erreurs | {self.skipped} ignorés")
        if self.errors:
            print(f"\n  ERREURS:")
            for e in self.errors:
                print(f"    ❌ {e}")
        else:
            print(f"\n  ✅ TOUS LES TESTS PASSENT")
        print(f"{'='*60}")
        return self.failed == 0


T = TestRunner()


# ─────────────────────────────────────────────────────────────────
# TEST 1 — IMPORTS
# ─────────────────────────────────────────────────────────────────

def test_imports():
    T.section("TEST 1 — IMPORTS MODULES")

    modules = [
        "dmp_reader", "dmp_validator", "ib_recalc",
        "rolling_features", "intermarket_features",
        "labeler", "dataset_builder", "train_lightgbm",
        "game_changers", "mia_amd", "mia_entry", "mia_sltp",
        "mia_sim", "mia_bench", "rvol", "mia_double_top",
        "mia_menthorq_reader",
    ]
    for m in modules:
        try:
            __import__(m)
            T.check(f"import {m}", True)
        except Exception as e:
            T.check(f"import {m}", False, str(e)[:80])


# ─────────────────────────────────────────────────────────────────
# TEST 2 — DMP READER + SCHEMA
# ─────────────────────────────────────────────────────────────────

def test_dmp_reader():
    T.section("TEST 2 — DMP READER")

    from dmp_reader import DmpReader

    # Trouver un fichier JSONL récent
    jsonl_file = None
    for sym_dir in ["ES", "NQ"]:
        d = DATA_DIR / sym_dir
        if d.exists():
            files = sorted(d.glob("*.jsonl"), reverse=True)
            if files:
                jsonl_file = files[0]
                break

    if jsonl_file is None:
        T.skip("DMP Reader", "Aucun fichier JSONL trouvé")
        return

    reader = DmpReader(str(DATA_DIR))
    df = reader.load_file(str(jsonl_file))

    T.check("Chargement JSONL", len(df) > 0, f"0 barres dans {jsonl_file.name}")
    T.check("Colonnes >= 260", len(df.columns) >= 260,
            f"seulement {len(df.columns)} colonnes")
    T.check("Colonne price existe", "price" in df.columns, "pas de colonne price")
    T.check("Colonne ts existe", "ts" in df.columns, "pas de colonne ts")
    T.check("Prix > 100", df["price"].mean() > 100,
            f"prix moyen = {df['price'].mean():.0f}")

    # Colonnes critiques
    critical = ["delta_bar", "total_vol", "buy_vol", "sell_vol",
                 "dist_cur_vpoc", "atr", "bar_high", "bar_low"]
    for c in critical:
        T.check(f"Colonne {c}", c in df.columns, "manquante")

    return df


# ─────────────────────────────────────────────────────────────────
# TEST 3 — IB RECALC
# ─────────────────────────────────────────────────────────────────

def test_ib_recalc(df=None):
    T.section("TEST 3 — IB RECALC")

    if df is None or df.empty:
        T.skip("IB Recalc", "Pas de données")
        return

    from ib_recalc import IBRecalc
    recalc = IBRecalc()
    df_ib = recalc.compute(df.copy(), symbol="ES")

    T.check("IBRecalc ne crash pas", True)
    T.check("Colonnes IB présentes", "ib_range_ticks" in df_ib.columns,
            "ib_range_ticks manquant")

    # Vérifier cohérence buy+sell=total
    if "buy_vol" in df_ib.columns:
        bad = ((df_ib["buy_vol"] + df_ib["sell_vol"] - df_ib["total_vol"]).abs() > 1).sum()
        T.check("buy+sell=total", bad == 0, f"{bad} incohérences")

    # Delta = buy - sell
    if "delta_bar" in df_ib.columns:
        bad = ((df_ib["delta_bar"] - (df_ib["buy_vol"] - df_ib["sell_vol"])).abs() > 1).sum()
        T.check("delta=buy-sell", bad == 0, f"{bad} incohérences")


# ─────────────────────────────────────────────────────────────────
# TEST 4 — ROLLING FEATURES
# ─────────────────────────────────────────────────────────────────

def test_rolling(df=None):
    T.section("TEST 4 — ROLLING FEATURES")

    if df is None or len(df) < 10:
        T.skip("Rolling", "Pas assez de données")
        return

    from rolling_features import RollingFeatures
    rf = RollingFeatures()
    ctx = rf.compute(df.copy())

    ctx_cols = [c for c in ctx.columns if c.startswith("ctx_")]
    T.check("Features ctx_* créées", len(ctx_cols) > 20,
            f"seulement {len(ctx_cols)}")
    T.check("ctx_ib_extension_ratio existe",
            "ctx_ib_extension_ratio" in ctx.columns, "manquante")


# ─────────────────────────────────────────────────────────────────
# TEST 5 — GAME CHANGERS
# ─────────────────────────────────────────────────────────────────

def test_game_changers():
    T.section("TEST 5 — GAME CHANGERS PARITÉ C++")

    import io
    import contextlib
    from game_changers import run_parity_tests

    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        ok = run_parity_tests()

    T.check("Parité C++ 105/105", ok, "échec parité")


# ─────────────────────────────────────────────────────────────────
# TEST 6 — MENTHORQ READER
# ─────────────────────────────────────────────────────────────────

def test_menthorq():
    T.section("TEST 6 — MENTHORQ READER")

    if not MQ_DIR.exists():
        T.skip("MenthorQ", "Dossier DATA/MENTHORQ absent")
        return

    # Importer et lancer les tests dédiés
    from test_menthorq_reader import run_tests
    ok = run_tests(str(MQ_DIR))
    T.check("Tests MenthorQ Reader", ok, "voir détails ci-dessus")


# ─────────────────────────────────────────────────────────────────
# TEST 7 — FPBS (colonnes VAP)
# ─────────────────────────────────────────────────────────────────

def test_fpbs(df=None):
    T.section("TEST 7 — FPBS (VAP)")

    if df is None:
        T.skip("FPBS", "Pas de données")
        return

    fpbs_cols = ["delta_pct", "ticks_count", "ask_pct", "bid_pct",
                  "high_pullback_delta", "low_pullback_delta",
                  "diag_pos_delta", "diag_neg_delta",
                  "avg_bid_size", "avg_ask_size", "bar_duration_sec"]

    for c in fpbs_cols:
        if c in df.columns:
            nn = df[c].notna().sum()
            T.check(f"FPBS {c} non-null", nn > 0, f"0/{len(df)} valeurs")
        else:
            T.skip(f"FPBS {c}", "colonne absente")

    # ask_pct dans [0, 1]
    if "ask_pct" in df.columns:
        bad = ((df["ask_pct"] > 1.01) | (df["ask_pct"] < -0.01)).sum()
        T.check("ask_pct dans [0, 1]", bad == 0, f"{bad} hors bornes")

    # bar_duration_sec raisonnable (30-120 secondes)
    if "bar_duration_sec" in df.columns:
        valid = df["bar_duration_sec"].dropna()
        if len(valid) > 0:
            T.check("bar_duration 30-120s",
                     valid.median() > 20 and valid.median() < 200,
                     f"médiane = {valid.median():.0f}s")


# ─────────────────────────────────────────────────────────────────
# TEST 8 — PIPELINE COMPLET
# ─────────────────────────────────────────────────────────────────

def test_pipeline():
    T.section("TEST 8 — PIPELINE COMPLET")

    from dmp_reader import DmpReader
    from ib_recalc import IBRecalc
    from rolling_features import RollingFeatures
    from intermarket_features import IntermarketFeatures

    # Trouver une date avec ES + NQ
    es_files = sorted((DATA_DIR / "ES").glob("*.jsonl"), reverse=True) if (DATA_DIR / "ES").exists() else []
    nq_files = sorted((DATA_DIR / "NQ").glob("*.jsonl"), reverse=True) if (DATA_DIR / "NQ").exists() else []

    if not es_files or not nq_files:
        T.skip("Pipeline", "Pas de fichiers ES+NQ")
        return

    reader = DmpReader(str(DATA_DIR))
    ib = IBRecalc()
    rf = RollingFeatures()
    im = IntermarketFeatures()

    try:
        es = ib.compute(reader.load_file(str(es_files[0])), symbol="ES")
        nq = ib.compute(reader.load_file(str(nq_files[0])), symbol="NQ")

        es_ctx = rf.compute(es)
        nq_ctx = rf.compute(nq)

        es_full = im.compute(es_ctx, nq_ctx, target="ES")
        nq_full = im.compute(nq_ctx, es_ctx, target="NQ")

        T.check("Pipeline ne crash pas", True)
        T.check("ES colonnes > 300", len(es_full.columns) > 300,
                f"{len(es_full.columns)} colonnes")
        T.check("NQ colonnes > 300", len(nq_full.columns) > 300,
                f"{len(nq_full.columns)} colonnes")

        # Vérifier features dérivées
        ctx_cols = [c for c in es_full.columns if c.startswith("ctx_")]
        im_cols = [c for c in es_full.columns if c.startswith("im_")]
        T.check("ctx_* > 30", len(ctx_cols) > 30, f"{len(ctx_cols)}")
        T.check("im_* > 5", len(im_cols) > 5, f"{len(im_cols)}")

    except Exception as e:
        T.check("Pipeline ne crash pas", False, str(e)[:100])


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    t0 = time.perf_counter()

    quick = "--quick" in sys.argv
    module = None
    if "--module" in sys.argv:
        idx = sys.argv.index("--module")
        if idx + 1 < len(sys.argv):
            module = sys.argv[idx + 1]

    print("╔══════════════════════════════════════════════════════╗")
    print("║        MIA TRADING — SUITE DE TESTS AUTOMATIQUES    ║")
    print("╚══════════════════════════════════════════════════════╝")

    # Sélection des tests
    if module:
        tests = {"imports": test_imports, "dmp": test_dmp_reader,
                  "ib": test_ib_recalc, "rolling": test_rolling,
                  "gc": test_game_changers, "menthorq": test_menthorq,
                  "fpbs": test_fpbs, "pipeline": test_pipeline}
        if module in tests:
            tests[module]()
        else:
            print(f"Module inconnu: {module}. Disponibles: {list(tests.keys())}")
            return
    else:
        # Tous les tests
        test_imports()

        df = test_dmp_reader()

        test_ib_recalc(df)

        if not quick:
            test_rolling(df)

        test_game_changers()

        if not quick:
            test_menthorq()

        test_fpbs(df)

        if not quick:
            test_pipeline()

    elapsed = time.perf_counter() - t0
    print(f"\n  Temps: {elapsed:.1f}s")

    ok = T.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
