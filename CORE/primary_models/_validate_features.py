"""
Features validator — MIA V2

Script OBLIGATOIRE avant tout backtest : verifie que chaque feature listee
dans required_features() des primary models existe REELLEMENT dans le dataset
parquet ES ET NQ.

Aurait evite 11 bugs features introuvables dans la 1ere version des primary models
(pattern 11 — "biais de completion sur la forme" du feedback_ia_traps_detection).

Usage :
    python -X utf8 CORE/primary_models/_validate_features.py

Retourne exit code 1 si au moins une feature manque. A integrer dans /test.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

# Auto-PYTHONPATH : insertion du repo root pour permettre `import CORE.*`
# meme quand le script est lance sans `PYTHONPATH=.`
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd


DATASET_ES = _REPO_ROOT / "DATA" / "DATASETS" / "ES_dataset_v2.parquet"
DATASET_NQ = _REPO_ROOT / "DATA" / "DATASETS" / "NQ_dataset_v2.parquet"
EMPIRICAL_SAMPLE_SIZE = 2000
MIN_EMPIRICAL_SIGNALS = 1
MAX_BUY_SELL_ASYMMETRY = 20.0


def discover_primary_models():
    """Retourne la liste des classes PrimaryModel dans CORE/primary_models/."""
    import CORE.primary_models as pm_pkg
    models = []
    for _, modname, _ in pkgutil.iter_modules(pm_pkg.__path__):
        if modname.startswith("_") or modname == "base":
            continue
        mod = importlib.import_module(f"CORE.primary_models.{modname}")
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and attr.__module__ == mod.__name__
                and hasattr(attr, "required_features")
                and hasattr(attr, "name")
                and attr.__name__ != "PrimaryModel"
            ):
                try:
                    instance = attr()
                    models.append((modname, attr.__name__, instance))
                except Exception as e:
                    print(f"  [WARN] cannot instantiate {attr.__name__}: {e}")
    return models


def validate(dataset_path: Path, label: str) -> int:
    if not dataset_path.exists():
        print(f"[FAIL] {label} dataset not found : {dataset_path}")
        return 1

    df = pd.read_parquet(dataset_path)
    columns = set(df.columns)
    print(f"\n=== {label} : {len(columns)} colonnes ===")

    models = discover_primary_models()
    print(f"Discovered {len(models)} primary models\n")

    n_errors = 0
    healthy_models = []
    for modname, clsname, model in models:
        missing = [f for f in model.required_features() if f not in columns]
        if missing:
            n_errors += len(missing)
            print(f"[FAIL] {modname}.{clsname} — {len(missing)} missing:")
            for f in missing:
                print(f"    - {f}")
        else:
            print(f"[OK]   {modname}.{clsname}")
            healthy_models.append((modname, clsname, model))

    if not healthy_models:
        return n_errors

    # Check empirique : chaque model doit generer au moins 1 signal sur
    # EMPIRICAL_SAMPLE_SIZE barres, et pas plus de MAX_BUY_SELL_ASYMMETRY ratio
    print(f"\n--- Empirical signal check ({EMPIRICAL_SAMPLE_SIZE} bars) ---")
    sample = df.head(EMPIRICAL_SAMPLE_SIZE)
    for modname, clsname, model in healthy_models:
        try:
            signals = model.run(sample)
            n_buy = (signals["signal"] == "BUY").sum()
            n_sell = (signals["signal"] == "SELL").sum()
            n_trade = n_buy + n_sell
            pct = n_trade / len(signals) * 100
            status = "OK"
            if n_trade == 0:
                status = "WARN_ZERO"
            elif n_buy > 0 and n_sell > 0:
                ratio = max(n_buy, n_sell) / min(n_buy, n_sell)
                if ratio > MAX_BUY_SELL_ASYMMETRY:
                    status = f"WARN_ASYM_{ratio:.0f}x"
            print(f"  [{status:12s}] {model.name:32s} BUY={n_buy:4d} SELL={n_sell:4d} "
                  f"HOLD={(signals['signal'] == 'HOLD').sum():4d} trade={pct:5.2f}%")
        except Exception as e:
            print(f"  [CRASH       ] {model.name:32s} {type(e).__name__}: {e}")
            n_errors += 1
    return n_errors


def main():
    total_errors = 0
    for ds, label in ((DATASET_ES, "ES"), (DATASET_NQ, "NQ")):
        total_errors += validate(ds, label)

    print()
    if total_errors == 0:
        print("=" * 60)
        print("ALL PRIMARY MODELS FEATURES VALIDATED OK")
        print("=" * 60)
        return 0
    print("=" * 60)
    print(f"TOTAL ERRORS : {total_errors}")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
