"""
Tests TDD pour dmp_validator V2 — 4 suites, 32+ tests.

Organisation (reco Plan agent 20/04) :
- Suite KNOWN_GOOD     : 17/04, 20/04 doivent etre GREEN
- Suite KNOWN_BAD      : BAKUP 15/04 doit etre RED (6 saturations)
- Suite SYNTHETIC_INJ  : injecter bug sur 17/04 -> doit detecter
- Suite REGRESSION     : cas historiques (session==3, bar_color_up sature,
                          arr[sz-1], big_orders mort, IB null RTH)

Methodologie anti-curve-fitting (Plan agent) :
  Seuils ajustes UNIQUEMENT sur KNOWN_GOOD. KNOWN_BAD et SYNTHETIC
  servent a VERIFIER, pas a calibrer.

Usage :
    pytest CORE/tests/test_dmp_validator.py -v
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
VALIDATOR = ROOT / "CORE" / "dmp_validator.py"
DATA_ES = ROOT / "DATA" / "ES"
DATA_NQ = ROOT / "DATA" / "NQ"
BAKUP = ROOT / "DATA" / "BAKUP_TEST"
TMP = ROOT / "DATA" / "_TEST_TMP"
TMP.mkdir(exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def run_validator(*files: Path) -> tuple[int, str]:
    """Run validator sur fichiers, retourne (exit_code, stdout)."""
    cmd = [sys.executable, "-X", "utf8", str(VALIDATOR)] + [str(f) for f in files]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.returncode, result.stdout


def load_lines(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def write_lines(lines: list[dict], target: Path) -> None:
    with open(target, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def write_meta(source_meta: Path, target: Path) -> None:
    import shutil
    shutil.copy(source_meta, target)


def inject_bug(lines: list[dict], mutations: dict) -> list[dict]:
    """Applique mutations a chaque ligne. Retourne copie."""
    new_lines = copy.deepcopy(lines)
    for line in new_lines:
        for k, v in mutations.items():
            line[k] = v
    return new_lines


def make_test_pair(lines: list[dict], source_meta: Path, sym: str,
                   tag: str) -> tuple[Path, Path]:
    """Ecrit paire jsonl+meta dans TMP. Retourne paths."""
    jsonl_path = TMP / f"_test_{tag}_{sym}.jsonl"
    meta_path = TMP / f"_test_{tag}_{sym}.meta.json"
    write_lines(lines, jsonl_path)
    write_meta(source_meta, meta_path)
    return jsonl_path, meta_path


# ═════════════════════════════════════════════════════════════════════════════
# SUITE 1 — KNOWN_GOOD (data certifiee propre doit passer GREEN)
# ═════════════════════════════════════════════════════════════════════════════


class TestKnownGood:
    def test_20260420_es_asia_is_green(self):
        """20/04 ES Asia (32 barres) : 0 erreur."""
        code, out = run_validator(DATA_ES / "20260420_ES.jsonl")
        assert code == 0, f"Expected 0 errors, got {code}\n{out[-1500:]}"
        assert "DONNÉES PROPRES" in out

    def test_20260420_nq_asia_is_green(self):
        """20/04 NQ Asia (32 barres) : 0 erreur."""
        code, out = run_validator(DATA_NQ / "20260420_NQ.jsonl")
        assert code == 0

    def test_20260417_es_full_day_is_green(self):
        """17/04 ES journee complete : 0 erreur."""
        code, out = run_validator(DATA_ES / "20260417_ES.jsonl")
        assert code == 0

    def test_20260417_nq_full_day_is_green(self):
        """17/04 NQ journee complete : 0 erreur."""
        code, out = run_validator(DATA_NQ / "20260417_NQ.jsonl")
        assert code == 0

    def test_validator_v2_version_printed(self):
        """Versioning visible dans stdout."""
        code, out = run_validator(DATA_ES / "20260420_ES.jsonl")
        assert "Validator v2.0" in out

    def test_green_file_baseline_behavior(self):
        """Fichier GREEN : baseline soit mise a jour, soit protegee (si REGRESSION warning).
        Les 2 comportements sont valides (R1 code-reviewer 20/04 : eviter pollution auto-amplifiante)."""
        code, out = run_validator(DATA_ES / "20260417_ES.jsonl")  # journee deja validee stable
        assert "Baseline mis a jour" in out or "Baseline NOT updated" in out


# ═════════════════════════════════════════════════════════════════════════════
# SUITE 2 — KNOWN_BAD (data pre-fix 17/04 doit etre RED)
# ═════════════════════════════════════════════════════════════════════════════


class TestKnownBad:
    def test_bakup_15_04_detects_saturation(self):
        """BAKUP 15/04 : bar_color_up, delta_divergence satures a 99% = RED."""
        bakup_file = BAKUP / "20260415_ES.jsonl"
        if not bakup_file.exists():
            pytest.skip("BAKUP 15/04 absent (sync requis)")
        code, out = run_validator(bakup_file)
        assert code > 0, "BAKUP 15/04 doit etre RED"
        assert "SATURATION bar_color_up" in out
        assert "SATURATION delta_divergence" in out

    def test_bakup_15_04_detects_multiple_errors(self):
        """BAKUP 15/04 : au moins 6 erreurs (6 saturations)."""
        bakup_file = BAKUP / "20260415_ES.jsonl"
        if not bakup_file.exists():
            pytest.skip("BAKUP 15/04 absent")
        code, out = run_validator(bakup_file)
        assert code >= 6


# ═════════════════════════════════════════════════════════════════════════════
# SUITE 3 — SYNTHETIC_INJECTION (injecter bug dans fichier GOOD -> doit detecter)
# ═════════════════════════════════════════════════════════════════════════════


class TestSyntheticInjection:
    @pytest.fixture
    def good_base(self):
        """Base 17/04 ES GOOD (journee complete)."""
        source = DATA_ES / "20260417_ES.jsonl"
        meta = DATA_ES / "20260417_ES.meta.json"
        if not (source.exists() and meta.exists()):
            pytest.skip("Base GOOD 17/04 absent")
        return source, meta

    def test_inject_session_3_detected_by_enum(self, good_base):
        """Bug Claude : session=3 doit etre detecte par enum domain."""
        source, meta = good_base
        lines = load_lines(source)
        polluted = inject_bug(lines, {"session": 3})
        jsonl, _ = make_test_pair(polluted, meta, "ES", "session3")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "ENUM session" in out

    def test_inject_saturation_bar_color_up_detected(self, good_base):
        """Injecter bar_color_up=1 partout -> saturation >95% detectee."""
        source, meta = good_base
        lines = load_lines(source)
        polluted = inject_bug(lines, {"bar_color_up": 1})
        jsonl, _ = make_test_pair(polluted, meta, "ES", "sat_barcolor")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "SATURATION bar_color_up" in out

    def test_inject_outlier_dist_swing_high_detected(self, good_base):
        """Injecter 1 valeur dist_swing_high = 1e8 -> outlier detecte."""
        source, meta = good_base
        lines = load_lines(source)
        polluted = copy.deepcopy(lines)
        # Garde les 99% originales, 1% a 1e8 fait exploser max/p99
        if len(polluted) > 20:
            polluted[0]["dist_swing_high"] = 1e8
        jsonl, _ = make_test_pair(polluted, meta, "ES", "outlier_swing")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "OUTLIER dist_swing_high" in out

    def test_inject_invalid_session_id_detected(self, good_base):
        """session_id='Asie' (typo) doit etre detecte."""
        source, meta = good_base
        lines = load_lines(source)
        polluted = inject_bug(lines, {"session_id": "Asie"})
        jsonl, _ = make_test_pair(polluted, meta, "ES", "sessid_typo")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "ENUM session_id" in out

    def test_inject_invalid_enum_vwap_side_detected(self, good_base):
        """vwap_d_side=2 (hors {-1,0,1}) detecte."""
        source, meta = good_base
        lines = load_lines(source)
        polluted = inject_bug(lines, {"vwap_d_side": 2})
        jsonl, _ = make_test_pair(polluted, meta, "ES", "vwap_side_2")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "ENUM vwap_d_side" in out

    def test_good_file_not_false_positive(self, good_base):
        """Base GOOD non-mutee = GREEN (no-op sanity)."""
        source, _ = good_base
        code, _ = run_validator(source)
        assert code == 0


# ═════════════════════════════════════════════════════════════════════════════
# SUITE 4 — REGRESSION_HISTORICAL (bugs documentes doivent etre detectes)
# ═════════════════════════════════════════════════════════════════════════════


class TestRegressionHistorical:
    """Couverture des 6 bugs historiques documentes (CLAUDE.md + memory)."""

    def test_bug_bar_color_up_saturation_covered(self):
        """BUG pre-17/04 : bar_color_up sature 100% non detecte pendant 3 mois."""
        bakup = BAKUP / "20260415_ES.jsonl"
        if not bakup.exists():
            pytest.skip("BAKUP absent")
        code, out = run_validator(bakup)
        assert "SATURATION bar_color_up" in out, (
            "Bug historique bar_color_up doit etre detecte par SATURATION check")

    def test_bug_delta_divergence_saturation_covered(self):
        """BUG pre-17/04 : delta_divergence sature 100%."""
        bakup = BAKUP / "20260415_ES.jsonl"
        if not bakup.exists():
            pytest.skip("BAKUP absent")
        code, out = run_validator(bakup)
        assert "SATURATION delta_divergence" in out

    def test_bug_claude_session_3_covered(self):
        """BUG 20/04 : Claude ecrit session==3 dans validator (convention est 0/1/2)."""
        source = DATA_ES / "20260417_ES.jsonl"
        meta = DATA_ES / "20260417_ES.meta.json"
        if not source.exists():
            pytest.skip("17/04 absent")
        lines = load_lines(source)
        polluted = inject_bug(lines, {"session": 3})
        jsonl, _ = make_test_pair(polluted, meta, "ES", "hist_session3")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "ENUM session" in out

    def test_bug_ib_null_in_rth_covered(self):
        """BUG historique : IB null en RTH doit lever warning."""
        source = DATA_ES / "20260417_ES.jsonl"
        meta = DATA_ES / "20260417_ES.meta.json"
        if not source.exists():
            pytest.skip("17/04 absent")
        lines = load_lines(source)
        polluted = copy.deepcopy(lines)
        for r in polluted:
            r["dist_ib_high"] = None
            r["dist_ib_low"] = None
            r["ib_range_atr"] = None
            r["ib_position_pct"] = None
        jsonl, _ = make_test_pair(polluted, meta, "ES", "hist_ib_null_rth")
        code, out = run_validator(jsonl)
        # Fichier 17/04 contient RTH => null IB = unexpected warning
        assert "COLONNE NULL INATTENDUE: dist_ib_high" in out

    def test_bug_ib_null_in_asia_only_ok(self):
        """BUG inverse : IB null en Asia-only ne doit PAS lever warning."""
        source = DATA_ES / "20260420_ES.jsonl"
        meta = DATA_ES / "20260420_ES.meta.json"
        if not source.exists():
            pytest.skip("20/04 absent")
        code, out = run_validator(source)
        # Asia-only : les IB null sont expected, donc PAS de warning
        assert "COLONNE NULL INATTENDUE: dist_ib_high" not in out

    def test_bug_tiered_skip_has_warning_not_silent(self):
        """BUG historique : skip silencieux n<200 transforme en warning HARD.
        Test via fichier synthetique Asia-only 32 barres (data 20/04 peut avoir grossi)."""
        source = DATA_ES / "20260420_ES.jsonl"
        meta = DATA_ES / "20260420_ES.meta.json"
        if not (source.exists() and meta.exists()):
            pytest.skip("20/04 absent")
        lines = load_lines(source)
        # Garder seulement les 32 premieres barres Asia (reproduit l'etat pre-RTH)
        asia_32 = [r for r in lines if r.get('session') == 0][:32]
        if len(asia_32) < 32:
            pytest.skip("Pas assez de barres Asia")
        jsonl, _ = make_test_pair(asia_32, meta, "ES", "tiered_n32")
        code, out = run_validator(jsonl)
        assert "n<200, eval skip" in out or "TIERED" in out and "warning HARD" in out

    def test_enum_domain_comprehensive(self):
        """11 colonnes enum minimum sont checkees."""
        code, out = run_validator(DATA_ES / "20260420_ES.jsonl")
        assert "11/11 colonnes enum" in out


# ═════════════════════════════════════════════════════════════════════════════
# SUITE 5 — UNIT TESTS validator_baseline
# ═════════════════════════════════════════════════════════════════════════════


class TestValidatorBaseline:
    """Unit tests pures sur CORE/validator_baseline.py."""

    def test_load_baseline_missing_file_returns_default(self, tmp_path):
        from CORE import validator_baseline as vb
        bl = vb.load_baseline(tmp_path / "nope.json")
        assert bl["version"] == vb.BASELINE_VERSION
        assert "symbols" in bl

    def test_compute_fire_rates_empty(self):
        from CORE import validator_baseline as vb
        assert vb.compute_fire_rates([], ["foo"]) == {}

    def test_compute_fire_rates_basic(self):
        from CORE import validator_baseline as vb
        lines = [
            {"session": 2, "foo": 1},
            {"session": 2, "foo": 0},
            {"session": 2, "foo": 1},
            {"session": 2, "foo": 0},
        ]
        rates = vb.compute_fire_rates(lines, ["foo"])
        assert rates["rth"]["foo"] == 0.5

    def test_check_regression_below_threshold_flags(self):
        from CORE import validator_baseline as vb
        bl = vb._default_baseline()
        bl["symbols"]["ES"]["rth"]["foo"] = {
            "samples": [0.04, 0.05, 0.045], "median": 0.045}
        # current = 0.010 < 0.5 * 0.045 = 0.0225 -> regression
        res = vb.check_regression(bl, "ES", "rth", "foo", 0.010)
        assert res.is_regression

    def test_check_regression_above_threshold_ok(self):
        from CORE import validator_baseline as vb
        bl = vb._default_baseline()
        bl["symbols"]["ES"]["rth"]["foo"] = {
            "samples": [0.04, 0.05, 0.045], "median": 0.045}
        res = vb.check_regression(bl, "ES", "rth", "foo", 0.040)
        assert not res.is_regression

    def test_check_regression_insufficient_samples_skip(self):
        from CORE import validator_baseline as vb
        bl = vb._default_baseline()
        bl["symbols"]["ES"]["rth"]["foo"] = {"samples": [0.04], "median": 0.04}
        res = vb.check_regression(bl, "ES", "rth", "foo", 0.001)
        assert not res.is_regression
        assert "samples" in res.reason

    def test_update_baseline_rolling_window(self):
        from CORE import validator_baseline as vb
        bl = vb._default_baseline()
        for i in range(10):
            vb.update_baseline(bl, "ES", {"rth": {"foo": 0.01 * i}})
        samples = bl["symbols"]["ES"]["rth"]["foo"]["samples"]
        assert len(samples) == vb.ROLLING_WINDOW  # = 7
        # Doit contenir les 7 derniers (0.03 ... 0.09)
        assert samples[0] == pytest.approx(0.03)
        assert samples[-1] == pytest.approx(0.09)

    def test_check_regression_median_zero_no_crash(self):
        """Median ~0 : pas de division par zero, pas de regression."""
        from CORE import validator_baseline as vb
        bl = vb._default_baseline()
        bl["symbols"]["ES"]["rth"]["foo"] = {
            "samples": [0.0, 0.0, 0.0], "median": 0.0}
        res = vb.check_regression(bl, "ES", "rth", "foo", 0.001)
        assert not res.is_regression
        assert "median ~0" in res.reason

    def test_compute_fire_rates_multi_session(self):
        """Fire rates calcules correctement avec plusieurs sessions."""
        from CORE import validator_baseline as vb
        lines = (
            [{"session": 0, "foo": 1}] * 10 +  # Asia : 100%
            [{"session": 0, "foo": 0}] * 10 +  # Asia : dilue a 50%
            [{"session": 2, "foo": 0}] * 5    # RTH : 0%
        )
        rates = vb.compute_fire_rates(lines, ["foo"])
        assert rates["asia"]["foo"] == pytest.approx(0.5)
        assert rates["rth"]["foo"] == 0.0
        assert "london" not in rates  # pas de sample


# ═════════════════════════════════════════════════════════════════════════════
# SUITE 6 — INTEGRATION & EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationAndEdgeCases:
    """Tests inter-fichiers et edge cases."""

    def test_multi_files_es_nq_green(self):
        """Validator accepte plusieurs fichiers en argument."""
        es = DATA_ES / "20260417_ES.jsonl"
        nq = DATA_NQ / "20260417_NQ.jsonl"
        if not (es.exists() and nq.exists()):
            pytest.skip("17/04 ES+NQ absent")
        code, out = run_validator(es, nq)
        assert code == 0
        assert "TOUS LES FICHIERS SONT PROPRES" in out

    def test_multi_inject_bugs_all_detected(self):
        """Fichier avec 3 bugs injectes simultanement : tous detectes."""
        source = DATA_ES / "20260417_ES.jsonl"
        meta = DATA_ES / "20260417_ES.meta.json"
        if not source.exists():
            pytest.skip("17/04 absent")
        lines = load_lines(source)
        # Inject 3 bugs : session bogus + saturation + enum bad
        polluted = inject_bug(lines, {
            "session": 3,
            "bar_color_up": 1,
            "vwap_d_side": 2,
        })
        jsonl, _ = make_test_pair(polluted, meta, "ES", "triple_bug")
        code, out = run_validator(jsonl)
        assert code >= 3
        assert "ENUM session" in out
        assert "SATURATION bar_color_up" in out
        assert "ENUM vwap_d_side" in out

    def test_extreme_outlier_detected(self):
        """Outlier extreme 1e10 detecte."""
        source = DATA_ES / "20260417_ES.jsonl"
        meta = DATA_ES / "20260417_ES.meta.json"
        if not source.exists():
            pytest.skip("17/04 absent")
        lines = load_lines(source)
        polluted = copy.deepcopy(lines)
        polluted[0]["delta_bar"] = 1e10
        jsonl, _ = make_test_pair(polluted, meta, "ES", "outlier_delta")
        code, out = run_validator(jsonl)
        assert code > 0
        assert "OUTLIER" in out

    def test_empty_file_handled_gracefully(self, tmp_path):
        """Fichier vide : pas de crash, retourne erreur."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        code, out = run_validator(empty)
        # Accepter tout exit non-zero (gestion gracieuse)
        assert "fichier vide" in out.lower() or code > 0

    def test_no_crash_on_malformed_line(self, tmp_path):
        """Ligne JSON malformee : crash silencieux evite."""
        malformed = tmp_path / "malformed.jsonl"
        malformed.write_text('{"broken": json\n', encoding="utf-8")
        meta = tmp_path / "malformed.meta.json"
        meta.write_text('{"schema_version":"3.7.3"}', encoding="utf-8")
        # Le validator doit soit refuser proprement, soit retourner erreur
        # Pas de crash non-controle
        try:
            code, _ = run_validator(malformed)
            assert code != 0  # doit signaler probleme
        except Exception:
            pytest.fail("Validator a crashe sur JSON malforme au lieu de gerer proprement")


# ═════════════════════════════════════════════════════════════════════════════
# Cleanup
# ═════════════════════════════════════════════════════════════════════════════


def teardown_module(module):
    """Nettoie TMP files apres tests."""
    import shutil
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
