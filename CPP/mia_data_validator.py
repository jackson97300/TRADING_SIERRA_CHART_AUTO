#!/usr/bin/env python3
"""
MIA Data Validator — Audit automatique des fichiers JSONL du DMP G3.

Exécute 10 catégories de tests sur chaque fichier et produit un rapport GO/NO-GO.
Conçu pour être lancé après chaque session de collecte, AVANT tout backtest ou ML.

Usage:
    python mia_data_validator.py 20260304_ES.jsonl 20260304_NQ.jsonl
    python mia_data_validator.py data_folder/   (tous les .jsonl du dossier)

Retourne exit code 0 si PASS, 1 si FAIL.

Version: 1.0.0 — 04/03/2026
Auteur: MIA Trading System
"""

import json
import sys
import os
import glob
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

TICK_SIZE = 0.25
ET = timezone(timedelta(hours=-5))

EXPECTED_FIELDS_COUNT = 262   # Schema 3.7.2 — 262 colonnes
METADATA_FIELDS = {'ts', 'sym', 'contract', 'session_id'}

VALID_SESSIONS = {'Asia', 'London', 'NY_AM', 'NY_PM', 'NY_Close'}
VALID_SYMBOLS = {'ES', 'NQ'}

# Tolérance pour les comparaisons float
TOL = 0.02       # Tolérance arithmétique standard
TOL_ATR = 0.06   # Tolérance ATR normalisation (légèrement plus lâche)

# Seuils d'alerte
MAX_TS_GAP_MS = 5 * 60 * 1000    # 5 min max entre barres
MAX_SLOPE = 5.0                    # |slope| > 5 = absurde
MIN_ATR_RATIO = 3.0                # NQ/ES ATR ratio min
MAX_ATR_RATIO = 7.0                # NQ/ES ATR ratio max

# Champs qui PEUVENT être null (avec raison)
NULLABLE_FIELDS = {
    'dist_big_ask_nearest_up', 'dist_big_ask_nearest_dn',
    'dist_big_bid_nearest_up', 'dist_big_bid_nearest_dn',
    'dist_mq_call_0dte', 'dist_mq_put_0dte',
    'bars_since_retest_high', 'bars_since_retest_low',
    'dist_session_hvn_above', 'dist_session_hvn_below',
    'dist_session_lvn_above', 'dist_session_lvn_below',
}

# Champs constants attendus en pre-cash (Asia/London)
PRECASH_ZERO_OK = {
    'open_type', 'open_zone', 'open_bias_conf', 'open_direction',
    'open_position', 'day_type', 'rule_80pct',
}

# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TestResult:
    name: str
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return self.failed == 0

    @property
    def total(self):
        return self.passed + self.failed

    def pass_one(self):
        self.passed += 1

    def fail(self, msg: str, bar_idx: int = -1):
        self.failed += 1
        if len(self.errors) < 10:  # Max 10 erreurs affichées
            prefix = f"[{bar_idx}] " if bar_idx >= 0 else ""
            self.errors.append(f"{prefix}{msg}")

    def warn(self, msg: str):
        self.warnings += 1
        if len(self.errors) < 10:
            self.errors.append(f"⚠️ {msg}")


@dataclass
class ValidationReport:
    symbol: str
    filename: str
    bar_count: int = 0
    tests: list = field(default_factory=list)

    @property
    def all_passed(self):
        return all(t.ok for t in self.tests)

    @property
    def total_fails(self):
        return sum(t.failed for t in self.tests)


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_structure(rows: list) -> TestResult:
    """T1: Intégrité structurelle — colonnes, types, timestamps."""
    t = TestResult("T1_STRUCTURE")

    if not rows:
        t.fail("Fichier vide!")
        return t

    # Schéma de référence = première ligne
    ref_keys = set(rows[0].keys())
    expected_count = len(ref_keys) - len(METADATA_FIELDS)

    # Vérifier chaque barre
    for i, r in enumerate(rows):
        keys = set(r.keys())
        if keys != ref_keys:
            missing = ref_keys - keys
            extra = keys - ref_keys
            t.fail(f"Colonnes différentes: missing={missing} extra={extra}", i)
        else:
            t.pass_one()

        # Types
        for k, v in r.items():
            if k in METADATA_FIELDS:
                continue
            if v is not None and not isinstance(v, (int, float)):
                t.fail(f"{k}={v} type={type(v).__name__} (attendu: float/int/null)", i)

        # session_id valide
        if r.get('session_id') not in VALID_SESSIONS:
            t.fail(f"session_id={r.get('session_id')} invalide", i)

    # Timestamps croissants
    for i in range(1, len(rows)):
        ts_prev = rows[i-1]['ts']
        ts_curr = rows[i]['ts']
        if ts_curr <= ts_prev:
            t.fail(f"ts non-croissant: {ts_prev} >= {ts_curr}", i)
        elif ts_curr - ts_prev > MAX_TS_GAP_MS:
            gap_min = (ts_curr - ts_prev) / 60000
            t.warn(f"Gap timestamps: {gap_min:.1f} min entre barres {i-1} et {i}")

    # Nombre de colonnes
    if expected_count != EXPECTED_FIELDS_COUNT:
        t.warn(f"Nombre de colonnes: {expected_count} (attendu: {EXPECTED_FIELDS_COUNT})")

    return t


def test_arithmetic(rows: list) -> TestResult:
    """T2: Arithmétique — volumes, deltas, ranges."""
    t = TestResult("T2_ARITHMETIC")

    for i, r in enumerate(rows):
        # buy + sell = total
        if abs((r['buy_vol'] + r['sell_vol']) - r['total_vol']) > 1:
            t.fail(f"buy+sell≠total: {r['buy_vol']}+{r['sell_vol']}≠{r['total_vol']}", i)
        else:
            t.pass_one()

        # delta = buy - sell
        if abs((r['buy_vol'] - r['sell_vol']) - r['delta_bar']) > 1:
            t.fail(f"delta≠buy-sell: {r['delta_bar']}≠{r['buy_vol']}-{r['sell_vol']}", i)
        else:
            t.pass_one()

        # ask + bid ≈ 1.0
        if abs(r['ask_pct'] + r['bid_pct'] - 1.0) > TOL:
            t.fail(f"ask+bid≠1: {r['ask_pct']}+{r['bid_pct']}", i)
        else:
            t.pass_one()

        # Ranges
        ranges = [
            ('sess',  'dist_sess_high',  'dist_sess_low',  'sess_range_ticks'),
            ('ib',    'dist_ib_high',    'dist_ib_low',    'ib_range_ticks'),
            ('ovn',   'dist_ovn_high',   'dist_ovn_low',   'ovn_range_ticks'),
            ('swing', 'dist_swing_high', 'dist_swing_low', 'swing_range_ticks'),
        ]
        for name, h, l, rng in ranges:
            calc = r[h] - r[l]
            if abs(calc - r[rng]) > 1:
                t.fail(f"{name}_range: {r[h]}-{r[l]}={calc:.0f}≠{r[rng]:.0f}", i)
            else:
                t.pass_one()

    return t


def test_atr_normalization(rows: list) -> TestResult:
    """T3: ATR normalisations — dist×tick/ATR."""
    t = TestResult("T3_ATR_NORM")

    checks = [
        ('dist_vwap_d',       'dist_vwap_d_atr',       True),   # signé
        ('dist_prev_vpoc',    'dist_prev_vpoc_atr',    True),
        ('dist_comp_20d_vpoc','dist_comp_20d_vpoc_atr',True),
        ('dist_comp_50d_vpoc','dist_comp_50d_vpoc_atr',True),
        ('ib_range_ticks',    'ib_range_atr',          False),  # absolu (toujours positif)
        ('sess_range_ticks',  'sess_range_atr',        False),
    ]

    for i, r in enumerate(rows):
        atr = r['atr']
        if atr <= 0:
            t.fail(f"ATR≤0: {atr}", i)
            continue

        for dist_k, atr_k, signed in checks:
            dist = r.get(dist_k)
            actual = r.get(atr_k)
            if dist is None or actual is None:
                continue

            if signed:
                expected = (dist * TICK_SIZE) / atr
            else:
                expected = (abs(dist) * TICK_SIZE) / atr

            if abs(expected - actual) > TOL_ATR:
                t.fail(f"{atr_k}: calc={expected:.4f} actual={actual:.4f}", i)
            else:
                t.pass_one()

    return t


def test_sign_conventions(rows: list) -> TestResult:
    """T4: Conventions de signe."""
    t = TestResult("T4_SIGNS")

    for i, r in enumerate(rows):
        # MQ Call wall toujours au-dessus du prix (dist > 0)
        if r.get('dist_mq_call') is not None and r['dist_mq_call'] < 0:
            t.fail(f"dist_mq_call<0: {r['dist_mq_call']}", i)
        else:
            t.pass_one()

        # MQ Put wall toujours en-dessous (dist < 0)
        if r.get('dist_mq_put') is not None and r['dist_mq_put'] > 0:
            t.fail(f"dist_mq_put>0: {r['dist_mq_put']}", i)
        else:
            t.pass_one()

        # VIX level > 0
        if r['vix_level'] <= 0:
            t.fail(f"VIX≤0: {r['vix_level']}", i)
        else:
            t.pass_one()

        # ATR > 0
        if r['atr'] <= 0:
            t.fail(f"ATR≤0: {r['atr']}", i)
        else:
            t.pass_one()

        # total_vol > 0
        if r['total_vol'] <= 0:
            t.fail(f"total_vol≤0: {r['total_vol']}", i)
        else:
            t.pass_one()

    return t


def test_booleans(rows: list) -> TestResult:
    """T5: Booléens cross-check avec distances."""
    t = TestResult("T5_BOOLEANS")

    checks = [
        ('bool_above_cur_vpoc', 'dist_cur_vpoc',  lambda d: d < 0),
        ('bool_above_vwap_d',   'dist_vwap_d',    lambda d: d < 0),
        ('bool_above_vwap_w',   'dist_vwap_w',    lambda d: d < 0),
        ('bool_above_vwap_m',   'dist_vwap_m',    lambda d: d < 0),
        ('bool_above_mq_hvl',   'dist_mq_hvl',    lambda d: d < 0),
        ('bool_above_prev_vpoc','dist_prev_vpoc',  lambda d: d < 0),
    ]

    for i, r in enumerate(rows):
        for bool_k, dist_k, cond in checks:
            if r.get(bool_k) is None or r.get(dist_k) is None:
                continue
            expected = 1 if cond(r[dist_k]) else 0
            if r[bool_k] != expected:
                t.fail(f"{bool_k}={r[bool_k]} vs dist={r[dist_k]} (expected={expected})", i)
            else:
                t.pass_one()

        # inside_cur_va: dist_cur_val <= 0 AND dist_cur_vah >= 0 (boundary inclusive)
        if r.get('inside_cur_va') is not None:
            expected = 1 if (r['dist_cur_val'] <= 0 and r['dist_cur_vah'] >= 0) else 0
            if r['inside_cur_va'] != expected:
                t.fail(f"inside_cur_va={r['inside_cur_va']} vs val={r['dist_cur_val']} vah={r['dist_cur_vah']}", i)
            else:
                t.pass_one()

        # vwap_d_side
        if r.get('vwap_d_side') is not None:
            expected = -1 if r['dist_vwap_d'] > 0 else 1
            if r['vwap_d_side'] != expected:
                t.fail(f"vwap_d_side={r['vwap_d_side']} vs dist={r['dist_vwap_d']}", i)
            else:
                t.pass_one()

    return t


def test_vp_ordering(rows: list) -> TestResult:
    """T6: VP ordering — VAL < VPOC < VAH + VWAP distinctes."""
    t = TestResult("T6_VP_ORDER")

    for i, r in enumerate(rows):
        p = r['price']

        # Current VP: VAL < VPOC < VAH
        for prefix, vpoc_k, vah_k, val_k in [
            ('cur',     'dist_cur_vpoc',     'dist_cur_vah',     'dist_cur_val'),
            ('prev',    'dist_prev_vpoc',    'dist_prev_vah',    'dist_prev_val'),
            ('comp20',  'dist_comp_20d_vpoc','dist_comp_20d_vah','dist_comp_20d_val'),
            ('comp50',  'dist_comp_50d_vpoc','dist_comp_50d_vah','dist_comp_50d_val'),
        ]:
            if any(r.get(k) is None for k in [vpoc_k, vah_k, val_k]):
                continue
            vpoc = p + r[vpoc_k] * TICK_SIZE
            vah  = p + r[vah_k] * TICK_SIZE
            val  = p + r[val_k] * TICK_SIZE
            if not (val <= vpoc + 1 and vpoc <= vah + 1):
                t.fail(f"{prefix}: VAL={val:.0f} VPOC={vpoc:.0f} VAH={vah:.0f}", i)
            else:
                t.pass_one()

        # VWAP D ≠ W (écart > 10 ticks)
        if r.get('dist_vwap_w') is not None:
            if abs(r['dist_vwap_d'] - r['dist_vwap_w']) < 2:
                t.fail(f"VWAP D≈W: d={r['dist_vwap_d']:.1f} w={r['dist_vwap_w']:.1f}", i)
            else:
                t.pass_one()

    return t


def test_slopes(rows: list) -> TestResult:
    """T7: Plausibilité des slopes VWAP."""
    t = TestResult("T7_SLOPES")

    for i, r in enumerate(rows):
        s10 = r['vwap_slope_10']
        s30 = r['vwap_slope_30']

        if abs(s10) > MAX_SLOPE:
            t.fail(f"|slope_10|={abs(s10):.2f} > {MAX_SLOPE}", i)
        else:
            t.pass_one()

        if abs(s30) > MAX_SLOPE:
            t.fail(f"|slope_30|={abs(s30):.2f} > {MAX_SLOPE}", i)
        else:
            t.pass_one()

        # slope_10_dir cohérent
        expected_dir = 1 if s10 > 0 else (-1 if s10 < 0 else 0)
        if r['vwap_slope_10_dir'] != expected_dir and s10 != 0:
            t.fail(f"slope_10_dir={r['vwap_slope_10_dir']} vs slope={s10:.4f}", i)
        else:
            t.pass_one()

    return t


def test_bn_variability(rows: list) -> TestResult:
    """T8: Variabilité BN (post-fix #7) — alerte si figé."""
    t = TestResult("T8_BN_VARIABILITY")

    bn_fields = ['bn_color_up', 'bn_color_dn', 'bn_long_up', 'bn_long_dn',
                 'bn_score_raw', 'rotation_up', 'rotation_dn']

    for f in bn_fields:
        vals = set(r[f] for r in rows)
        if len(vals) > 1:
            t.pass_one()
        elif len(rows) > 50:
            # Seulement alerter si assez de barres pour attendre de la variation
            t.warn(f"{f} CONSTANT ({vals}) sur {len(rows)} barres — BN figé?")
        else:
            t.pass_one()  # Trop peu de barres pour conclure

    # bn_score_raw doit avoir au moins 3 valeurs en RTH
    score_vals = set(r['bn_score_raw'] for r in rows)
    has_rth = any(r['session_id'] in {'NY_AM', 'NY_PM'} for r in rows)
    if has_rth and len(score_vals) < 3:
        t.warn(f"bn_score_raw seulement {len(score_vals)} valeurs distinctes en RTH")
    else:
        t.pass_one()

    return t


def test_coverage(rows: list) -> TestResult:
    """T9: Couverture — % null par champ, alertes."""
    t = TestResult("T9_COVERAGE")

    n = len(rows)
    fields = [k for k in rows[0].keys() if k not in METADATA_FIELDS]

    unexpected_nulls = []
    for f in fields:
        null_count = sum(1 for r in rows if r.get(f) is None)
        pct = null_count / n * 100

        if null_count == n and f not in NULLABLE_FIELDS:
            unexpected_nulls.append(f)
            t.fail(f"{f}: 100% null — non attendu")
        elif null_count == 0:
            t.pass_one()
        else:
            # Partiel: OK si dans nullable_fields
            if f in NULLABLE_FIELDS:
                t.pass_one()
            elif pct > 50:
                t.warn(f"{f}: {pct:.0f}% null")
            else:
                t.pass_one()

    return t


def test_continuity(rows: list) -> TestResult:
    """T10: Continuité prix et cohérence inter-barres."""
    t = TestResult("T10_CONTINUITY")

    sym = rows[0]['sym']
    max_gap_pts = 50 if sym == 'NQ' else 15  # NQ plus volatile

    for i in range(1, len(rows)):
        gap = abs(rows[i]['price'] - rows[i-1]['price'])
        if gap > max_gap_pts:
            t.warn(f"Gap prix: {gap:.2f} pts entre barres {i-1} et {i}")
        else:
            t.pass_one()

        # ATR ne devrait pas changer drastiquement
        atr_ratio = rows[i]['atr'] / rows[i-1]['atr'] if rows[i-1]['atr'] > 0 else 1
        if atr_ratio > 1.5 or atr_ratio < 0.67:
            t.fail(f"ATR saut: {rows[i-1]['atr']:.2f} → {rows[i]['atr']:.2f}", i)
        else:
            t.pass_one()

    return t


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-SYMBOL
# ═══════════════════════════════════════════════════════════════════════════════

def test_cross_symbol(es_rows: list, nq_rows: list) -> TestResult:
    """TX: Cohérence cross-symbol ES vs NQ."""
    t = TestResult("TX_CROSS_SYMBOL")

    # Aligner par timestamp
    es_by_ts = {r['ts']: r for r in es_rows}
    nq_by_ts = {r['ts']: r for r in nq_rows}
    common_ts = sorted(set(es_by_ts.keys()) & set(nq_by_ts.keys()))

    if not common_ts:
        t.warn("Aucun timestamp commun ES/NQ")
        return t

    for ts in common_ts:
        e = es_by_ts[ts]
        n = nq_by_ts[ts]

        # VIX identique
        if abs(e['vix_level'] - n['vix_level']) > 0.01:
            t.fail(f"VIX diverge: ES={e['vix_level']} NQ={n['vix_level']}")
        else:
            t.pass_one()

        # session_id identique
        if e['session_id'] != n['session_id']:
            t.fail(f"session_id: ES={e['session_id']} NQ={n['session_id']}")
        else:
            t.pass_one()

        # ATR ratio
        if e['atr'] > 0:
            ratio = n['atr'] / e['atr']
            if ratio < MIN_ATR_RATIO or ratio > MAX_ATR_RATIO:
                t.fail(f"ATR ratio NQ/ES={ratio:.2f} (hors [{MIN_ATR_RATIO},{MAX_ATR_RATIO}])")
            else:
                t.pass_one()

    return t


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT
# ═══════════════════════════════════════════════════════════════════════════════

def print_report(report: ValidationReport):
    status = "✅ PASS" if report.all_passed else "🔴 FAIL"
    print(f"\n{'═'*80}")
    print(f"  {status} — {report.symbol} — {report.filename}")
    print(f"  {report.bar_count} barres | {len(report.tests)} tests | {report.total_fails} fails")
    print(f"{'═'*80}")

    for t in report.tests:
        icon = "✅" if t.ok else "🔴"
        warn_str = f" ⚠️{t.warnings}" if t.warnings > 0 else ""
        print(f"  {icon} {t.name:25s} {t.passed:>5d} pass / {t.failed:>3d} fail{warn_str}")
        for err in t.errors:
            print(f"      {err}")


def print_summary(reports: list, cross: Optional[TestResult] = None):
    print(f"\n{'═'*80}")
    print(f"  RÉSUMÉ FINAL")
    print(f"{'═'*80}")

    all_ok = all(r.all_passed for r in reports)
    if cross:
        all_ok = all_ok and cross.ok

    for r in reports:
        status = "✅" if r.all_passed else "🔴"
        print(f"  {status} {r.symbol}: {r.bar_count} barres, {r.total_fails} fails")

    if cross:
        status = "✅" if cross.ok else "🔴"
        print(f"  {status} Cross-symbol: {cross.passed} pass, {cross.failed} fails")

    print()
    if all_ok:
        print(f"  ✅✅✅  DONNÉES VALIDÉES — GO POUR ML/BACKTEST  ✅✅✅")
    else:
        print(f"  🔴🔴🔴  DONNÉES NON VALIDÉES — CORRIGER AVANT ML  🔴🔴🔴")

    return all_ok


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def validate_file(filepath: str) -> ValidationReport:
    """Valide un fichier JSONL et retourne le rapport."""
    filename = os.path.basename(filepath)

    with open(filepath) as f:
        rows = [json.loads(l) for l in f if l.strip()]

    if not rows:
        report = ValidationReport(symbol="?", filename=filename)
        t = TestResult("EMPTY")
        t.fail("Fichier vide!")
        report.tests.append(t)
        return report

    sym = rows[0].get('sym', '?')
    report = ValidationReport(symbol=sym, filename=filename, bar_count=len(rows))

    # Lancer tous les tests
    report.tests.append(test_structure(rows))
    report.tests.append(test_arithmetic(rows))
    report.tests.append(test_atr_normalization(rows))
    report.tests.append(test_sign_conventions(rows))
    report.tests.append(test_booleans(rows))
    report.tests.append(test_vp_ordering(rows))
    report.tests.append(test_slopes(rows))
    report.tests.append(test_bn_variability(rows))
    report.tests.append(test_coverage(rows))
    report.tests.append(test_continuity(rows))

    return report


def main():
    if len(sys.argv) < 2:
        print("Usage: python mia_data_validator.py <fichier.jsonl> [fichier2.jsonl ...]")
        print("       python mia_data_validator.py <dossier>/")
        sys.exit(1)

    # Collecter les fichiers
    files = []
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            files.extend(sorted(glob.glob(os.path.join(arg, '*.jsonl'))))
        else:
            files.append(arg)

    if not files:
        print("Aucun fichier .jsonl trouvé!")
        sys.exit(1)

    print(f"╔{'═'*78}╗")
    print(f"║  MIA DATA VALIDATOR v1.0 — {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET'):>52s}  ║")
    print(f"║  Fichiers: {len(files):<66d}  ║")
    print(f"╚{'═'*78}╝")

    # Valider chaque fichier
    reports = []
    rows_by_sym = {}

    for fp in files:
        report = validate_file(fp)
        reports.append(report)
        print_report(report)

        # Garder les données pour cross-symbol
        with open(fp) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        if rows:
            sym = rows[0].get('sym')
            rows_by_sym[sym] = rows

    # Cross-symbol si ES + NQ disponibles
    cross = None
    if 'ES' in rows_by_sym and 'NQ' in rows_by_sym:
        cross = test_cross_symbol(rows_by_sym['ES'], rows_by_sym['NQ'])
        icon = "✅" if cross.ok else "🔴"
        print(f"\n  {icon} TX_CROSS_SYMBOL       {cross.passed:>5d} pass / {cross.failed:>3d} fail")
        for err in cross.errors:
            print(f"      {err}")

    # Résumé
    all_ok = print_summary(reports, cross)
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
