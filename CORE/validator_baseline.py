"""
Baseline rolling 7 jours pour dmp_validator V2.

Stocke median fire_rate par (symbole, feature, session) sur les 7 derniers jours
valides (fichiers GREEN). Utilise pour detecter regression partielle : fire_rate
chute > 50% vs median = WARN meme si > seuil absolu.

Couvre le trou majeur identifie par Plan agent 20/04 :
- big_orders_cluster_* est mort 0% pendant 26 jours sans detection car seuil
  absolu etait trop permissif. Avec baseline rolling, chute de 4% a 0.1% = WARN.

Structure baseline.json :
{
  "version": "1.0",
  "updated_at": "2026-04-20T18:00:00Z",
  "symbols": {
    "ES": {
      "asia":   {"feature_name": {"samples": [0.02, 0.03, ...], "median": 0.025}},
      "london": {...},
      "rth":    {...}
    },
    "NQ": {...}
  }
}
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BASELINE_VERSION = "1.0"
ROLLING_WINDOW = 7          # jours
REGRESSION_RATIO = 0.5      # fire_rate < 50% median = WARN
MIN_SAMPLES_FOR_BASELINE = 3  # refuser comparaison si < 3 samples

# Sessions conventions DMP C++ (DMP_Main.cpp:798) : 0=Asia, 1=London, 2=US
SESSION_NAMES = {0: "asia", 1: "london", 2: "rth"}


@dataclass
class RegressionResult:
    """Resultat d'un check regression pour une (symbole, feature, session)."""
    feature: str
    session: str
    current_rate: float
    baseline_median: float | None
    samples_count: int
    ratio: float | None  # current / baseline_median
    is_regression: bool
    reason: str


def _default_baseline() -> dict:
    """Structure baseline vide."""
    return {
        "version": BASELINE_VERSION,
        "updated_at": None,
        "symbols": {"ES": {"asia": {}, "london": {}, "rth": {}},
                    "NQ": {"asia": {}, "london": {}, "rth": {}}},
    }


def load_baseline(path: Path) -> dict:
    """Charge baseline depuis JSON. Retourne structure vide si absent.

    Migration version : archive l'ancien fichier en .bak avant reset pour
    preserver l'historique (R2 code-reviewer 20/04). Un bump majeur ne doit
    pas effacer 7 jours de data silencieusement.
    """
    if not path.exists():
        return _default_baseline()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Migration si version obsolete : archive avant reset
    old_version = data.get("version")
    if old_version != BASELINE_VERSION:
        backup = path.with_suffix(f".v{old_version or 'unknown'}.bak")
        try:
            path.replace(backup)
        except Exception:
            pass  # meilleur effort, pas de crash si backup echoue
        return _default_baseline()
    return data


def save_baseline(baseline: dict, path: Path) -> None:
    """Persiste baseline sur disque."""
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)


def compute_fire_rates(lines: list[dict], features: Iterable[str]) -> dict[str, dict[str, float]]:
    """
    Retourne {session_name: {feature: fire_rate}} pour les features donnees.

    fire_rate = nb lignes ou feature != 0 et != None, divise par nb lignes session.
    """
    by_session: dict[int, list[dict]] = {0: [], 1: [], 2: []}
    for line in lines:
        sess = line.get("session")
        if sess in by_session:
            by_session[sess].append(line)

    result: dict[str, dict[str, float]] = {}
    for sess_id, sess_lines in by_session.items():
        if not sess_lines:
            continue
        sess_name = SESSION_NAMES[sess_id]
        rates = {}
        for feat in features:
            nz = sum(1 for r in sess_lines if r.get(feat, 0) and r.get(feat) is not None)
            rates[feat] = nz / len(sess_lines)
        result[sess_name] = rates
    return result


def update_baseline(baseline: dict, sym: str, fire_rates: dict[str, dict[str, float]]) -> None:
    """
    Met a jour baseline avec nouveaux fire_rates d'un fichier GREEN.

    Ajoute chaque sample dans la liste rolling, conserve au max ROLLING_WINDOW,
    recalcule median.
    """
    if sym not in baseline["symbols"]:
        return
    for sess_name, feat_rates in fire_rates.items():
        if sess_name not in baseline["symbols"][sym]:
            continue
        sess_data = baseline["symbols"][sym][sess_name]
        for feat, rate in feat_rates.items():
            if feat not in sess_data:
                sess_data[feat] = {"samples": [], "median": None}
            entry = sess_data[feat]
            entry["samples"].append(rate)
            # Rolling window : garder les N derniers
            if len(entry["samples"]) > ROLLING_WINDOW:
                entry["samples"] = entry["samples"][-ROLLING_WINDOW:]
            # Recalcul median
            entry["median"] = statistics.median(entry["samples"])


def check_regression(baseline: dict, sym: str, sess_name: str, feature: str,
                     current_rate: float) -> RegressionResult:
    """
    Compare current_rate vs baseline median pour (sym, sess, feature).

    Retourne is_regression=True si current < REGRESSION_RATIO * median.
    Si < MIN_SAMPLES_FOR_BASELINE samples, ne declenche pas (insuffisant).
    """
    default = RegressionResult(feature=feature, session=sess_name,
                               current_rate=current_rate, baseline_median=None,
                               samples_count=0, ratio=None, is_regression=False,
                               reason="no baseline available")

    sym_data = baseline["symbols"].get(sym, {})
    sess_data = sym_data.get(sess_name, {})
    entry = sess_data.get(feature)
    if entry is None:
        return default

    samples = entry.get("samples", [])
    n_samples = len(samples)
    median = entry.get("median")

    if n_samples < MIN_SAMPLES_FOR_BASELINE or median is None:
        return RegressionResult(feature=feature, session=sess_name,
                                current_rate=current_rate, baseline_median=median,
                                samples_count=n_samples, ratio=None,
                                is_regression=False,
                                reason=f"only {n_samples}/{MIN_SAMPLES_FOR_BASELINE} samples, skip")

    # Median proche zero : ratio non significatif
    if median < 1e-6:
        return RegressionResult(feature=feature, session=sess_name,
                                current_rate=current_rate, baseline_median=median,
                                samples_count=n_samples, ratio=None,
                                is_regression=False,
                                reason="median ~0, no comparison")

    ratio = current_rate / median
    is_regression = ratio < REGRESSION_RATIO
    reason = (f"current {current_rate:.4%} < {REGRESSION_RATIO:.0%} x median "
              f"{median:.4%} (ratio {ratio:.2f})") if is_regression else "within range"
    return RegressionResult(feature=feature, session=sess_name,
                            current_rate=current_rate, baseline_median=median,
                            samples_count=n_samples, ratio=ratio,
                            is_regression=is_regression, reason=reason)


def default_baseline_path() -> Path:
    """Chemin canonique du baseline.json."""
    return Path(__file__).parent.parent / "DATA" / "BASELINE" / "baseline.json"
