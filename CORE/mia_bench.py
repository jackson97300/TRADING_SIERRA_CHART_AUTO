"""
mia_bench.py — Benchmark automatique du pipeline MIA
=====================================================

Drop tes JSONL dans le même dossier et lance:
    python mia_bench.py

Il détecte automatiquement tous les fichiers YYYYMMDD_SYM.jsonl,
construit le pipeline complet, et produit un rapport avec:
  1. Tests fonctionnels (parité C++, NaN, sync, schema 266 cols)
  2. Ranking global bootstrap avec IC 95%
  3. Stabilité jour/jour et cross-asset
  4. Analyse par régime (session)
  5. Seuils: sensibilité
  6. Verdict BÉTON / PROBABLE / FRAGILE
  7-12. Game changers, Signal/Bruit, Noyau dur, Wall tracker, Timing
  13. DMP Health Check (signaux BN vivants/morts)
  14. RVOL Validation (C++ ring buffer vs Python recalcul)

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_bench.py

Schema: 3.7.3 — 266 colonnes (262 + 4 Cluster Volume via VAP)
Auteur : MIA Trading System
Date   : 2026-03-13
"""

import warnings
warnings.filterwarnings('ignore')

import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── Imports MIA ──────────────────────────────────────────────────────
from dmp_reader import DmpReader
from rolling_features import RollingFeatures
from intermarket_features import IntermarketFeatures
from game_changers import (
    run_parity_tests, classify_profile_shape, direction,
    confidence, open_type_name, day_type_name, profile_shape_name,
    bias_boost
)
from mia_amd import AmdEngine, FEATURES as AMD_FEATURES
from ib_recalc import IBRecalc
from mia_menthorq_reader import MenthorQReader


# ═════════════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════════════

N_BOOTSTRAP = 2000
SEED = 42
FUT_HORIZONS = [3, 5]                       # barres en avant
GC_NUMERIC = [
    'profile_skew', 'poc_position', 'volume_imbalance',
    'open_bias_conf', 'open_direction'
]
REPORT_FILE = "MIA_BENCH_REPORT.txt"
REPORT_FILE_DATED = f"MIA_BENCH_{datetime.now().strftime('%Y%m%d')}.txt"

# Schema 3.7.3 — 13/04/2026 (262 + 4 Cluster Volume via VAP)
EXPECTED_SCHEMA_COLS = 266
SCHEMA_VERSION = "3.7.3"


# ═════════════════════════════════════════════════════════════════════
# DISCOVERY
# ═════════════════════════════════════════════════════════════════════

def discover_files(base_dir: str = ".") -> dict:
    """
    Trouve tous les fichiers YYYYMMDD_SYM.jsonl.
    Retourne {date_str: {"NQ": path, "ES": path}}.
    """
    pattern = re.compile(r"(\d{8})_(NQ|ES)\.jsonl$")
    found = {}
    for f in sorted(glob.glob(os.path.join(base_dir, "*.jsonl"))):
        m = pattern.search(os.path.basename(f))
        if m:
            # Exclure les fichiers weekends/incomplets (<10 KB = <50 barres)
            if os.path.getsize(f) < 10000:
                continue
            date, sym = m.group(1), m.group(2)
            found.setdefault(date, {})[sym] = f
    return found


# ═════════════════════════════════════════════════════════════════════
# PIPELINE
# ═════════════════════════════════════════════════════════════════════

def build_pipeline(files: dict) -> dict:
    """
    Construit le pipeline complet pour chaque date.
    Retourne {date: {"NQ_raw": df, "ES_raw": df, "NQ_full": df, "ES_full": df, ...}}
    """
    reader = DmpReader(".")
    ib = IBRecalc()
    rf = RollingFeatures()
    im = IntermarketFeatures()

    # MenthorQ — chercher le dossier MENTHORQ relatif aux données
    mq = None
    for mq_path in ["../MENTHORQ", "../../DATA/MENTHORQ", "../DATA/MENTHORQ"]:
        mq_dir = Path(files[list(files.keys())[0]][list(files[list(files.keys())[0]].keys())[0]]).parent.parent / "MENTHORQ"
        if mq_dir.exists():
            mq = MenthorQReader(str(mq_dir))
            break
    if mq is None:
        # Fallback chemin absolu
        for p in ["D:/TRADING_SIERRA_CHART_AUTO/DATA/MENTHORQ",
                   "C:/TRADING_SIERRA_CHART_AUTO/DATA/MENTHORQ"]:
            if Path(p).exists():
                mq = MenthorQReader(p)
                break

    data = {}
    for date, syms in sorted(files.items()):
        entry = {"date": date}
        # Load + IB recalc + rolling
        for sym in ["NQ", "ES"]:
            if sym in syms:
                raw = reader.load_file(syms[sym])
                raw = ib.compute(raw, symbol=sym)
                ctx = rf.compute(raw)
                entry[f"{sym}_raw"] = raw
                entry[f"{sym}_ctx"] = ctx
            else:
                entry[f"{sym}_raw"] = None
                entry[f"{sym}_ctx"] = None

        # Intermarket si les deux symboles existent
        if entry["NQ_ctx"] is not None and entry["ES_ctx"] is not None:
            entry["NQ_full"] = im.compute(entry["NQ_ctx"], entry["ES_ctx"], target="NQ")
            entry["ES_full"] = im.compute(entry["ES_ctx"], entry["NQ_ctx"], target="ES")
        else:
            entry["NQ_full"] = entry.get("NQ_ctx")
            entry["ES_full"] = entry.get("ES_ctx")

        # MenthorQ enrichissement
        if mq is not None:
            for sym in ["NQ", "ES"]:
                key = f"{sym}_full"
                if entry.get(key) is not None and not entry[key].empty:
                    try:
                        entry[key] = mq.enrich(entry[key], date, sym, tick_size=0.25)
                    except Exception:
                        pass  # MenthorQ optionnel — pas de blocage si absent

        data[date] = entry
    return data


# ═════════════════════════════════════════════════════════════════════
# TEST 1 — FONCTIONNEL
# ═════════════════════════════════════════════════════════════════════

def test_functional(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 1 — FONCTIONNEL")
    out.append("=" * 70)
    out.append("")

    # 1a. Parité C++
    import io, contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        ok = run_parity_tests()
    out.append(f"  game_changers.py parité C++: {'105/105 ✅' if ok else '❌ ÉCHEC'}")

    # 1a2. Schema check
    total_tests = 0
    total_pass = 0
    for date, d in sorted(data.items()):
        for sym in ["NQ", "ES"]:
            raw = d.get(f"{sym}_raw")
            if raw is None or raw.empty:
                continue
            ncols = len(raw.columns)
            ok = ncols >= EXPECTED_SCHEMA_COLS - 5  # tolérance datetime_utc/et ajoutés par reader
            total_tests += 1; total_pass += int(ok)
            status = "✅" if ncols >= EXPECTED_SCHEMA_COLS - 5 else "❌"
            out.append(f"  schema {sym} {date}: {ncols} colonnes (attendu ≥{EXPECTED_SCHEMA_COLS-5}) {status}")

            # Colonnes critiques 3.6.0
            critical = ['bn_color_up_2', 'bn_color_dn_2', 'dist_ext_edge_buy',
                        'dist_ext_edge_sell', 'retest_high_count', 'retest_low_count',
                        'rvol', 'rvol_zscore', 'rvol_buy', 'rvol_sell',
                        'rvol_absorb_buy', 'rvol_absorb_sell']
            missing = [c for c in critical if c not in raw.columns]
            if missing:
                out.append(f"  ⚠️ Colonnes manquantes {sym} {date}: {', '.join(missing)}")

    # 1b. Par date
    for date, d in sorted(data.items()):
        for sym in ["NQ", "ES"]:
            raw = d.get(f"{sym}_raw")
            if raw is None or raw.empty:
                continue
            df = raw.reset_index(drop=True)
            n = len(df)

            # direction
            miss = sum(1 for i in range(n)
                       if direction(int(df.iloc[i]['open_type'])) != int(df.iloc[i]['open_direction']))
            ok = miss == 0
            total_tests += 1; total_pass += int(ok)
            out.append(f"  direction() {sym} {date}: {miss}/{n} mismatch {'✅' if ok else '❌'}")

            # confidence
            miss = sum(1 for i in range(n)
                       if abs(confidence(int(df.iloc[i]['open_type'])) - float(df.iloc[i]['open_bias_conf'])) > 0.01)
            ok = miss == 0
            total_tests += 1; total_pass += int(ok)
            out.append(f"  confidence() {sym} {date}: {miss}/{n} mismatch {'✅' if ok else '❌'}")

            # profile_shape
            miss = 0
            for i in range(n):
                py = classify_profile_shape(
                    float(df.iloc[i]['poc_position']),
                    float(df.iloc[i]['profile_skew']),
                    float(df.iloc[i]['volume_imbalance']),
                    bool(df.iloc[i]['is_double_dist']))
                if py != int(df.iloc[i]['profile_shape']):
                    miss += 1
            ok = miss == 0
            total_tests += 1; total_pass += int(ok)
            out.append(f"  profile_shape {sym} {date}: {miss}/{n} mismatch {'✅' if ok else '❌'}")

    # 1c. Features sync
    for date, d in sorted(data.items()):
        full = d.get("NQ_full")
        if full is None:
            continue
        ctx_ok = set(RollingFeatures.FEATURES) == set(c for c in full.columns if c.startswith('ctx_'))
        im_ok = set(IntermarketFeatures.FEATURES) == set(c for c in full.columns if c.startswith('im_'))
        total_tests += 2; total_pass += int(ctx_ok) + int(im_ok)
        out.append(f"  FEATURES sync {date}: ctx={'✅' if ctx_ok else '❌'} im={'✅' if im_ok else '❌'}")

    # 1d. NaN
    for date, d in sorted(data.items()):
        full = d.get("NQ_full")
        if full is None:
            continue
        feat_cols = [c for c in full.columns if c.startswith('ctx_') or c.startswith('im_')]
        max_nan = max(full[c].isna().sum() for c in feat_cols) if feat_cols else 0
        ok = max_nan < 20
        total_tests += 1; total_pass += int(ok)
        out.append(f"  NaN check {date}: max={max_nan} {'✅' if ok else '⚠️'}")

    out.append(f"\n  Total: {total_pass}/{total_tests} tests passent")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 2 — INVENTAIRE DONNÉES
# ═════════════════════════════════════════════════════════════════════

def test_inventory(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 2 — INVENTAIRE")
    out.append("=" * 70)
    out.append("")

    total_bars = 0
    sessions_all = set()
    for date, d in sorted(data.items()):
        for sym in ["NQ", "ES"]:
            raw = d.get(f"{sym}_raw")
            if raw is None or raw.empty:
                continue
            df = raw.reset_index(drop=True)
            sessions = df['session_id'].value_counts().to_dict()
            sessions_all.update(sessions.keys())
            p0, p1 = df.iloc[0]['price'], df.iloc[-1]['price']
            ot = open_type_name(int(df.iloc[-1]['open_type']))
            total_bars += len(df)
            ncols = len(df.columns)
            out.append(f"  {sym} {date}: {len(df):>3d} barres | {ncols} cols | {sessions} | "
                       f"{p0:.2f}→{p1:.2f} ({p1-p0:+.2f}) | OT={ot}")

    out.append(f"\n  Total: {total_bars} barres, {len(data)} jours, sessions={sorted(sessions_all)}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 3 — RANKING GLOBAL BOOTSTRAP
# ═════════════════════════════════════════════════════════════════════

def test_ranking(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 3 — RANKING GLOBAL BOOTSTRAP")
    out.append("=" * 70)
    out.append("")

    # Combine all NQ_full
    frames = []
    for date, d in sorted(data.items()):
        full = d.get("NQ_full")
        if full is None:
            continue
        df = full.reset_index(drop=True).copy()
        df['_date'] = date
        frames.append(df)

    if not frames:
        out.append("  Pas de données NQ_full")
        return [], pd.DataFrame()

    nq_all = pd.concat(frames, ignore_index=True)
    for h in FUT_HORIZONS:
        # fut_r par date pour eviter look-ahead cross-day
        parts = []
        for date, grp in nq_all.groupby('_date'):
            grp = grp.copy()
            grp[f'fut_r{h}'] = grp['price'].shift(-h) - grp['price']
            parts.append(grp)
        nq_all = pd.concat(parts, ignore_index=True)

    all_feat = ([c for c in nq_all.columns if c.startswith('ctx_')] +
                [c for c in nq_all.columns if c.startswith('im_')] +
                [c for c in nq_all.columns if c.startswith('mq_')])
    for gc in GC_NUMERIC:
        if gc in nq_all.columns and gc not in all_feat:
            all_feat.append(gc)

    rng = np.random.RandomState(SEED)
    dates = sorted(nq_all['_date'].unique())
    results = []

    for col in all_feat:
        vals = nq_all[[col, 'fut_r3', '_date']].dropna()
        if len(vals) < 30:
            continue
        r_full = vals[col].corr(vals['fut_r3'])
        if pd.isna(r_full):
            continue

        # Bootstrap
        boot = []
        for _ in range(N_BOOTSTRAP):
            idx = rng.choice(len(vals), size=len(vals), replace=True)
            bc = vals.iloc[idx][col].corr(vals.iloc[idx]['fut_r3'])
            if not pd.isna(bc):
                boot.append(bc)

        if len(boot) < 50:
            ci_lo, ci_hi = -1.0, 1.0
        else:
            ci_lo = np.percentile(boot, 2.5)
            ci_hi = np.percentile(boot, 97.5)
        ci_ok = not (ci_lo < 0 and ci_hi > 0)

        # r5 if available
        r5_val = nq_all[['fut_r5', col]].dropna()
        r_r5 = r5_val[col].corr(r5_val['fut_r5']) if len(r5_val) > 20 else float('nan')

        # Per-day
        day_rs = {}
        for dt in dates:
            sub = vals[vals['_date'] == dt]
            if len(sub) > 10:
                day_rs[dt] = sub[col].corr(sub['fut_r3'])

        day_signs = [np.sign(r) for r in day_rs.values() if not pd.isna(r)]
        day_ok = len(set(day_signs)) == 1 if len(day_signs) >= 2 else False

        beton = ci_ok and day_ok
        if col.startswith('ctx_'):
            typ = 'CTX'
        elif col.startswith('im_'):
            typ = ' IM'
        else:
            typ = ' GC'

        results.append({
            'col': col, 'r3': r_full, 'r5': r_r5,
            'ci_lo': ci_lo, 'ci_hi': ci_hi,
            'ci_ok': ci_ok, 'day_ok': day_ok, 'beton': beton,
            'day_rs': day_rs, 'typ': typ
        })

    results.sort(key=lambda x: abs(x['r3']), reverse=True)

    # Header
    day_hdrs = "".join(f" {d[-4:]:>6s}" for d in dates)
    out.append(f"  {'#':>3s} {'Feature':34s} {'r(3)':>6s} {'r(5)':>6s} {'95%CI':>17s}{day_hdrs} {'T':>3s} {'Class':>7s}")
    out.append("  " + "-" * (88 + 7 * len(dates)))

    for i, r in enumerate(results):
        cls = "BETON" if r['beton'] else "PROB" if r['ci_ok'] else "frag"
        r5s = f"{r['r5']:+.3f}" if not pd.isna(r['r5']) else "  N/A"
        day_vals = ""
        for dt in dates:
            rv = r['day_rs'].get(dt, float('nan'))
            day_vals += f" {rv:+.3f}" if not pd.isna(rv) else "   N/A"
        mark = " ★" if r['beton'] else ""
        out.append(f"  {i+1:2d}  {r['col']:32s} {r['r3']:+.3f}  {r5s}  "
                   f"[{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]{day_vals} {r['typ']} {cls}{mark}")

    beton = [r for r in results if r['beton']]
    probable = [r for r in results if r['ci_ok'] and not r['day_ok']]
    fragile = [r for r in results if not r['ci_ok']]

    out.append("")
    out.append(f"  BÉTON:    {len(beton):>2d}  (CI + jour/jour)")
    for r in beton:
        out.append(f"    {r['col']:34s} r={r['r3']:+.3f} [{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]")
    out.append(f"  PROBABLE: {len(probable):>2d}  (CI seul)")
    out.append(f"  FRAGILE:  {len(fragile):>2d}  (CI croise 0)")
    out.append("")

    return results, nq_all


# ═════════════════════════════════════════════════════════════════════
# TEST 4 — CROSS-ASSET (NQ vs ES target)
# ═════════════════════════════════════════════════════════════════════

def test_cross_asset(data: dict, results: list, out: list):
    out.append("=" * 70)
    out.append("  TEST 4 — CROSS-ASSET (NQ target vs ES target)")
    out.append("=" * 70)
    out.append("")

    top_cols = [r['col'] for r in results[:15]]

    # Build ES combined
    frames_es = []
    for date, d in sorted(data.items()):
        full = d.get("ES_full")
        if full is None:
            continue
        df = full.reset_index(drop=True).copy()
        df['_date'] = date
        df['fut_r3'] = df.groupby('_date')['price'].transform(lambda x: x.shift(-3) - x)
        frames_es.append(df)

    if not frames_es:
        out.append("  Pas de données ES_full")
        return

    es_all = pd.concat(frames_es, ignore_index=True)

    # Build NQ combined
    frames_nq = []
    for date, d in sorted(data.items()):
        full = d.get("NQ_full")
        if full is None:
            continue
        df = full.reset_index(drop=True).copy()
        df['_date'] = date
        df['fut_r3'] = df.groupby('_date')['price'].transform(lambda x: x.shift(-3) - x)
        frames_nq.append(df)
    nq_all = pd.concat(frames_nq, ignore_index=True)

    out.append(f"  {'Feature':34s} {'NQ r(3)':>8s} {'ES r(3)':>8s} {'Stable':>7s}")
    out.append("  " + "-" * 60)
    for col in top_cols:
        r_nq = nq_all[col].corr(nq_all['fut_r3']) if col in nq_all.columns else float('nan')
        r_es = es_all[col].corr(es_all['fut_r3']) if col in es_all.columns else float('nan')
        if pd.isna(r_nq) or pd.isna(r_es):
            ss = "N/A"
        elif np.sign(r_nq) == np.sign(r_es):
            ss = "✅ OUI"
        else:
            ss = "❌ FLIP"
        out.append(f"  {col:34s} {r_nq:+.3f}    {r_es:+.3f}    {ss}")

    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 5 — PAR RÉGIME (session)
# ═════════════════════════════════════════════════════════════════════

def test_regime(data: dict, results: list, out: list):
    out.append("=" * 70)
    out.append("  TEST 5 — PAR RÉGIME (session)")
    out.append("=" * 70)
    out.append("")

    # Build NQ with session tags
    frames = []
    for date, d in sorted(data.items()):
        full = d.get("NQ_full")
        if full is None:
            continue
        df = full.reset_index(drop=True).copy()
        df['_regime'] = df['session_id'] + "_" + date
        df['fut_r3'] = df.groupby('_regime')['price'].transform(lambda x: x.shift(-3) - x)
        frames.append(df)

    if not frames:
        return

    nq_all = pd.concat(frames, ignore_index=True)
    regimes = sorted(nq_all['_regime'].unique())

    top_cols = [r['col'] for r in results[:12]]

    hdr = f"  {'Feature':34s}" + "".join(f" {rg[:10]:>10s}" for rg in regimes) + f" {'stable':>7s}"
    out.append(hdr)
    out.append("  " + "-" * (35 + 11 * len(regimes) + 8))

    for col in top_cols:
        line = f"  {col:34s}"
        corrs = []
        for rg in regimes:
            sub = nq_all[nq_all['_regime'] == rg]
            if len(sub) > 15 and col in sub.columns:
                r = sub[col].corr(sub['fut_r3'])
                corrs.append(r)
                line += f" {r:+.3f}    " if not pd.isna(r) else "   N/A    "
            else:
                line += "   N/A    "

        signs = [np.sign(r) for r in corrs if not pd.isna(r)]
        stable = len(set(signs)) == 1 if len(signs) >= 2 else False
        line += f"  {'OUI' if stable else 'non'}"
        out.append(line)

    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 6 — SEUILS
# ═════════════════════════════════════════════════════════════════════

def test_thresholds(nq_all: pd.DataFrame, out: list):
    out.append("=" * 70)
    out.append("  TEST 6 — SENSIBILITÉ SEUILS")
    out.append("=" * 70)
    out.append("")

    if nq_all.empty:
        return

    fut = nq_all['fut_r3']
    delta = nq_all['delta_bar']
    price_diff = nq_all['price'].diff()

    # Climax
    out.append("  ctx_climax_signal — vol_z threshold")
    vol_z = nq_all.get('ctx_vol_z_5', pd.Series(dtype=float))
    dsum = nq_all.get('ctx_delta_sum_3', pd.Series(dtype=float))
    if not vol_z.empty:
        for t in [1.0, 1.2, 1.5, 2.0]:
            sig = np.where(vol_z.abs() > t, np.sign(dsum), 0.0)
            n_trig = (np.abs(sig) > 0).sum()
            r = pd.Series(sig).corr(fut)
            cur = " ← ACTUEL" if t == 1.5 else ""
            out.append(f"    {t:.1f}: {n_trig:>4d} triggers ({n_trig/len(nq_all)*100:.0f}%) "
                       f"r={r:+.3f}{cur}")

    # Absorption
    out.append("  ctx_instant_absorption — delta threshold")
    for t in [10, 20, 30, 50, 80]:
        inst = np.where((delta > t) & (price_diff < 0), -1.0,
               np.where((delta < -t) & (price_diff > 0), 1.0, 0.0))
        n_trig = (np.abs(inst) > 0).sum()
        r = pd.Series(inst).corr(fut)
        cur = " ← ACTUEL" if t == 30 else ""
        out.append(f"    {t:>3d}: {n_trig:>4d} triggers ({n_trig/len(nq_all)*100:.0f}%) "
                   f"r={r:+.3f}{cur}")

    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 7 — GAME CHANGERS
# ═════════════════════════════════════════════════════════════════════

def test_game_changers(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 7 — GAME CHANGERS")
    out.append("=" * 70)
    out.append("")

    for date, d in sorted(data.items()):
        for sym in ["NQ", "ES"]:
            raw = d.get(f"{sym}_raw")
            if raw is None or raw.empty:
                continue
            df = raw.reset_index(drop=True)
            sessions = df['session_id'].unique()

            for sess in sessions:
                sub = df[df['session_id'] == sess]
                if len(sub) == 0:
                    continue
                last = sub.iloc[-1]
                ot = open_type_name(int(last['open_type']))
                conf = confidence(int(last['open_type']))
                dt = day_type_name(int(last['day_type']))
                dirn = direction(int(last['open_type']))
                bb_long = bias_boost(+1, int(last['open_type']))
                bb_short = bias_boost(-1, int(last['open_type']))
                p0 = sub.iloc[0]['price']
                p1 = sub.iloc[-1]['price']
                out.append(f"  {sym} {date} {sess:8s}: OT={ot:10s} conf={conf:.2f} "
                           f"dir={dirn:+d} DT={dt:8s} bb(L/S)={bb_long:+.2f}/{bb_short:+.2f} "
                           f"px={p0:.0f}→{p1:.0f}({p1-p0:+.0f})")

    out.append("")


GC_NUMERIC = ['profile_skew', 'volume_imbalance', 'poc_position', 'open_bias_conf']


# ═════════════════════════════════════════════════════════════════════
# TEST 9 — SIGNAL vs BRUIT (tri automatique)
# ═════════════════════════════════════════════════════════════════════

def test_signal_bruit(nq_all: pd.DataFrame, data: dict, out: list):
    """
    Tri automatique: 252 colonnes → SIGNAL / MAYBE / BRUIT.
    Critères: |r|>0.05, stable jour/jour, CI 95% ne croise pas 0,
              pas proxy prix (|r_prix| < 0.80), nunique > 2, NaN < 20%.
    """
    out.append("=" * 70)
    out.append("  TEST 9 — SIGNAL vs BRUIT (tri automatique)")
    out.append("=" * 70)
    out.append("")

    if nq_all.empty:
        out.append("  Pas de données")
        return []

    skip = {'ts', 'sym', 'contract', 'session_id', 'session', 'bar_index',
            'datetime_utc', 'datetime_et', '_date', 'fut_r3', 'fut_r5'}
    all_cols = [c for c in nq_all.columns
                if c not in skip and nq_all[c].dtype != 'object']

    dates = sorted(nq_all['_date'].unique())
    rng = np.random.RandomState(SEED)

    results = []
    for col in all_cols:
        try:
            vals = nq_all[[col, 'fut_r3', '_date']].dropna()
            if len(vals) < 50:
                continue
            nu = nq_all[col].nunique()
            if nu <= 2:
                continue
            pct_nan = nq_all[col].isna().sum() / len(nq_all)
            if pct_nan > 0.20:
                continue

            # Proxy prix?
            rp = abs(nq_all[col].corr(nq_all['price'])) if 'price' in nq_all.columns else 0
            if rp > 0.80 and not col.startswith('ctx_') and not col.startswith('im_'):
                continue

            r_full = vals[col].corr(vals['fut_r3'])
            if pd.isna(r_full):
                continue

            # Stable jour/jour
            day_rs = {}
            for dt in dates:
                sub = vals[vals['_date'] == dt]
                if len(sub) > 10:
                    day_rs[dt] = sub[col].corr(sub['fut_r3'])
            day_signs = [np.sign(r) for r in day_rs.values() if not pd.isna(r)]
            day_ok = len(set(day_signs)) == 1 if len(day_signs) >= 2 else False

            # Bootstrap CI
            boot = []
            for _ in range(1000):
                idx = rng.choice(len(vals), size=len(vals), replace=True)
                bc = vals.iloc[idx][col].corr(vals.iloc[idx]['fut_r3'])
                if not pd.isna(bc):
                    boot.append(bc)
            ci_lo = np.percentile(boot, 2.5) if len(boot) > 50 else -1
            ci_hi = np.percentile(boot, 97.5) if len(boot) > 50 else 1
            ci_ok = not (ci_lo < 0 and ci_hi > 0)

            signal = abs(r_full) > 0.05
            tier = 'SIGNAL' if (signal and day_ok and ci_ok) else \
                   'MAYBE' if (signal and (day_ok or ci_ok)) else 'BRUIT'

            results.append({
                'col': col, 'r': r_full, 'ci_lo': ci_lo, 'ci_hi': ci_hi,
                'day_ok': day_ok, 'ci_ok': ci_ok, 'rp': rp, 'tier': tier,
            })
        except Exception:
            pass

    results.sort(key=lambda x: abs(x['r']), reverse=True)

    sig = [r for r in results if r['tier'] == 'SIGNAL']
    maybe = [r for r in results if r['tier'] == 'MAYBE']
    bruit = [r for r in results if r['tier'] == 'BRUIT']

    out.append(f"  {len(all_cols)} colonnes testées → "
               f"{len(sig)} SIGNAL, {len(maybe)} MAYBE, {len(bruit)} BRUIT")
    out.append("")

    out.append(f"  SIGNAL ({len(sig)}):")
    for i, r in enumerate(sig):
        out.append(f"    {i+1:2d}. {r['col']:34s} r={r['r']:+.3f} "
                   f"[{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]")
    out.append("")

    out.append(f"  MAYBE ({len(maybe)}):")
    for i, r in enumerate(maybe[:10]):
        ss = "stab" if r['day_ok'] else "flip"
        ci = "CI✅" if r['ci_ok'] else "CI✗"
        out.append(f"    {i+1:2d}. {r['col']:34s} r={r['r']:+.3f} {ss} {ci}")
    if len(maybe) > 10:
        out.append(f"    ... et {len(maybe)-10} de plus")
    out.append("")

    out.append(f"  BRUIT: {len(bruit)} colonnes éliminées")
    out.append("")

    return sig


# ═════════════════════════════════════════════════════════════════════
# TEST 10 — NOYAU DUR BACKTEST
# ═════════════════════════════════════════════════════════════════════

def test_noyau_dur(nq_all: pd.DataFrame, data: dict, out: list):
    """
    Backtest du score contextuel avec les 7 features noyau dur.
    Compare 7 features vs toutes les features.
    """
    out.append("=" * 70)
    out.append("  TEST 10 — NOYAU DUR BACKTEST (7 features)")
    out.append("=" * 70)
    out.append("")

    if nq_all.empty:
        out.append("  Pas de données")
        return

    from mia_entry import CORE_FEATURES, VA_BOOST_INSIDE, VA_BOOST_OUTSIDE, \
        IM_BOOST_US, IM_BOOST_OTHER

    def zscore(s):
        std = s.std()
        if std == 0 or pd.isna(std):
            return s * 0
        return (s - s.mean()) / std

    dates = sorted(nq_all['_date'].unique())

    # Score noyau dur contextuel par date
    for dt in dates:
        df = nq_all[nq_all['_date'] == dt].copy()
        if len(df) < 20:
            continue

        inside_va = (df.get('inside_prev_va', pd.Series(0, index=df.index)) == 1)
        is_us = (df.get('session_id', pd.Series('', index=df.index)) == 'US')

        score = pd.Series(0.0, index=df.index)
        for col, (base_w, domain) in CORE_FEATURES.items():
            if col not in df.columns:
                continue
            z = zscore(df[col])
            if domain == 'PROFIL':
                w = np.where(inside_va, base_w * VA_BOOST_INSIDE,
                             base_w * VA_BOOST_OUTSIDE)
            elif domain == 'INTERMAR':
                w = np.where(is_us, base_w * IM_BOOST_US,
                             base_w * IM_BOOST_OTHER)
            else:
                w = base_w
            score += w * z

        r3 = score.corr(df['fut_r3'])
        r5 = score.corr(df['fut_r5']) if 'fut_r5' in df.columns else float('nan')

        shorts = df[score < -0.08]
        longs = df[score > 0.08]
        neutral = df[score.abs() <= 0.08]

        out.append(f"  {dt}: r(3)={r3:+.3f}" +
                   (f"  r(5)={r5:+.3f}" if not pd.isna(r5) else ""))

        if len(shorts) > 0:
            sw = (shorts['fut_r3'] < 0).sum()
            avg3 = shorts['fut_r3'].mean()
            wr = sw / len(shorts) * 100
            out.append(f"    SHORT: {len(shorts):>3d} sig | {wr:.0f}% WR | avg_r3={avg3:+.1f}")
        if len(longs) > 0:
            lw = (longs['fut_r3'] > 0).sum()
            avg3 = longs['fut_r3'].mean()
            wr = lw / len(longs) * 100
            out.append(f"    LONG:  {len(longs):>3d} sig | {wr:.0f}% WR | avg_r3={avg3:+.1f}")
        out.append(f"    NEUTRE:{len(neutral):>3d}")

    # Comparaison 7 vs tout
    out.append("")
    score7_all = pd.Series(0.0, index=nq_all.index)
    inside_va = (nq_all.get('inside_prev_va', pd.Series(0, index=nq_all.index)) == 1)
    is_us = (nq_all.get('session_id', pd.Series('', index=nq_all.index)) == 'US')
    for col, (base_w, domain) in CORE_FEATURES.items():
        if col not in nq_all.columns:
            continue
        z = zscore(nq_all[col])
        if domain == 'PROFIL':
            w = np.where(inside_va, base_w * VA_BOOST_INSIDE,
                         base_w * VA_BOOST_OUTSIDE)
        elif domain == 'INTERMAR':
            w = np.where(is_us, base_w * IM_BOOST_US,
                         base_w * IM_BOOST_OTHER)
        else:
            w = base_w
        score7_all += w * z
    r7 = score7_all.corr(nq_all['fut_r3'])

    all_feat = ([c for c in nq_all.columns if c.startswith('ctx_')] +
                [c for c in nq_all.columns if c.startswith('im_')] +
                [c for c in nq_all.columns if c.startswith('mq_')])
    for gc in GC_NUMERIC:
        if gc in nq_all.columns and gc not in all_feat:
            all_feat.append(gc)
    score_all = pd.Series(0.0, index=nq_all.index)
    for col in all_feat:
        rc = nq_all[col].corr(nq_all['fut_r3'])
        if not pd.isna(rc):
            score_all += rc * zscore(nq_all[col])
    r_all = score_all.corr(nq_all['fut_r3'])

    pct = r7 / r_all * 100 if r_all != 0 else 0
    out.append(f"  7 features: r={r7:+.3f} | {len(all_feat)} features: r={r_all:+.3f} "
               f"| 7 capte {pct:.0f}% du signal")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 11 — WALL TRACKER (quels niveaux ont fonctionné par jour)
# ═════════════════════════════════════════════════════════════════════

WALL_LEVELS = {
    'dist_gex_nearest_up':   ('GEX_UP',        'gex',    1),
    'dist_gex_nearest_dn':   ('GEX_DN',        'gex',    1),
    'dist_session_hvn_above':('SESS_HVN_UP',   'profile',1),
    'dist_session_hvn_below':('SESS_HVN_DN',   'profile',1),
    'dist_session_lvn_above':('SESS_LVN_UP',   'profile',1),
    'dist_session_lvn_below':('SESS_LVN_DN',   'profile',1),
    'dist_ext_edge_buy':     ('EXT_EDGE_BUY',  'ext',    1),
    'dist_ext_edge_sell':    ('EXT_EDGE_SELL',  'ext',    1),
    'dist_sess_high':        ('SESS_HIGH',      'session',1),
    'dist_cur_vah':          ('CUR_VAH',        'cur_va', 2),
    'dist_cur_vpoc':         ('CUR_VPOC',       'cur_va', 2),
    'dist_cur_val':          ('CUR_VAL',        'cur_va', 2),
    'dist_prev_vah':         ('PREV_VAH',       'prev_va',2),
    'dist_prev_val':         ('PREV_VAL',       'prev_va',2),
    'dist_prev_vpoc':        ('PREV_VPOC',      'prev_va',2),
    'dist_vwap_d':           ('VWAP_D',         'vwap',   3),
    'dist_vwap_d_sd1u':      ('VWAP+1SD',       'vwap',   2),
    'dist_vwap_d_sd1d':      ('VWAP-1SD',       'vwap',   2),
    'dist_vwap_d_sd2u':      ('VWAP+2SD',       'vwap',   2),
    'dist_vwap_d_sd2d':      ('VWAP-2SD',       'vwap',   2),
    'dist_vwap_d_sd3u':      ('VWAP+3SD',       'vwap',   2),
    'dist_vwap_d_sd3d':      ('VWAP-3SD',       'vwap',   2),
    'dist_prev_vwap':        ('PREV_VWAP',      'prev_vw',3),
    'dist_prev_vwap_sd1u':   ('PREV_VWAP+1SD',  'prev_vw',2),
    'dist_prev_vwap_sd1d':   ('PREV_VWAP-1SD',  'prev_vw',2),
    'dist_ib_high':          ('IB_HIGH',        'ib',     3),
    'dist_ib_low':           ('IB_LOW',         'ib',     3),
    'dist_ovn_high':         ('OVN_HIGH',       'ovn',    2),
    'dist_ovn_low':          ('OVN_LOW',        'ovn',    3),
    'dist_1d_max_ticks':     ('1D_MAX',         '1d',     2),
    'dist_1d_min_ticks':     ('1D_MIN',         '1d',     2),
    'dist_mq_hvl':           ('MQ_HVL',         'gamma',  3),
    'dist_mq_put_0dte':      ('MQ_PUT_0DTE',    'gamma',  3),
    'dist_mq_call_0dte':     ('MQ_CALL_0DTE',   'gamma',  3),
    'dist_swing_high':       ('SWING_HIGH',     'swing',  2),
    'dist_swing_low':        ('SWING_LOW',      'swing',  2),
    'dist_open_cash':        ('OPEN_CASH',      'session',2),
    'dist_comp_20d_vpoc':    ('COMP20_VPOC',    'comp',   3),
    'dist_comp_20d_val':     ('COMP20_VAL',     'comp',   2),
    'dist_vwap_w':           ('VWAP_W',         'htf',    3),
    'dist_vwap_m':           ('VWAP_M',         'htf',    3),
}

WALL_PROXIMITY = 25  # ticks

def test_wall_tracker(data: dict, out: list):
    """Track which levels bounced/broke per day, with double top/bottom."""
    out.append("=" * 70)
    out.append("  TEST 11 — WALL TRACKER (niveaux par jour)")
    out.append("=" * 70)
    out.append("")

    global_stats = {}  # col -> {approaches, bounces, crosses, penetrations, dts, dbs}

    for date in sorted(data.keys()):
        for sym_key in ['NQ_full', 'ES_full']:
            df = data[date].get(sym_key)
            if df is None or df.empty:
                continue
            sym = 'NQ' if 'NQ' in sym_key else 'ES'
            df = df.reset_index(drop=True)

            day_results = []

            for col, (name, cat, default_tier) in WALL_LEVELS.items():
                if col not in df.columns:
                    continue

                approaches = 0; bounces = 0; crosses = 0
                pens = []; touch_bars = []

                for i in range(1, len(df) - 10):
                    d_now = df.iloc[i][col]
                    d_prev = df.iloc[i-1][col]
                    if pd.isna(d_now) or pd.isna(d_prev):
                        continue

                    if abs(d_now) < WALL_PROXIMITY and abs(d_prev) >= WALL_PROXIMITY:
                        approaches += 1
                        touch_bars.append((i, d_now))
                        fds = [df.iloc[i+j][col] for j in range(1, 6)
                               if i+j < len(df) and not pd.isna(df.iloc[i+j][col])]
                        if fds and max(abs(d) for d in fds) > abs(d_now) + 10:
                            bounces += 1

                    if d_prev * d_now < 0:
                        crosses += 1
                        mp = 0
                        for j in range(1, 11):
                            if i+j >= len(df): break
                            fd = df.iloc[i+j][col]
                            if not pd.isna(fd) and abs(fd) > mp:
                                mp = abs(fd)
                        pens.append(mp * 0.25)

                # Double top/bottom
                dts = 0; dbs = 0
                for t1 in range(len(touch_bars)):
                    for t2 in range(t1+1, len(touch_bars)):
                        gap = touch_bars[t2][0] - touch_bars[t1][0]
                        if gap < 8 or gap > 60: continue
                        s1 = 'above' if touch_bars[t1][1] > 0 else 'below'
                        s2 = 'above' if touch_bars[t2][1] > 0 else 'below'
                        if s1 != s2: continue
                        between = [abs(df.iloc[k][col]) for k in range(touch_bars[t1][0], touch_bars[t2][0]+1)
                                   if not pd.isna(df.iloc[k][col])]
                        if not between or max(between) < WALL_PROXIMITY + 15: continue
                        if s1 == 'above': dts += 1
                        else: dbs += 1
                        break

                if approaches > 0:
                    br = bounces / approaches * 100
                    ap = np.mean(pens) if pens else 0
                    ws = br / 100 * (1 / (1 + ap / 10))
                    day_results.append({
                        'name': name, 'app': approaches, 'bnc': bounces,
                        'br': br, 'cross': crosses, 'pen': ap,
                        'ws': ws, 'dts': dts, 'dbs': dbs, 'tier': default_tier
                    })

                    # Global accumulation
                    if col not in global_stats:
                        global_stats[col] = {'name': name, 'app': 0, 'bnc': 0,
                                             'cross': 0, 'pens': [], 'dts': 0, 'dbs': 0,
                                             'tier': default_tier, 'day_scores': []}
                    g = global_stats[col]
                    g['app'] += approaches
                    g['bnc'] += bounces
                    g['cross'] += crosses
                    g['pens'].extend(pens)
                    g['dts'] += dts
                    g['dbs'] += dbs
                    g['day_scores'].append(ws)

            # Per-day output
            if day_results:
                day_results.sort(key=lambda x: x['ws'], reverse=True)
                out.append(f"  {sym} {date}:")
                worked = [r for r in day_results if r['ws'] > 0.25]
                failed = [r for r in day_results if r['ws'] <= 0.10 and r['app'] >= 2]
                dt_db = [r for r in day_results if r['dts'] > 0 or r['dbs'] > 0]

                if worked:
                    worked_str = ', '.join(f"{r['name']}({r['br']:.0f}%)" for r in worked[:6])
                    out.append(f"    ✅ FONCTIONNÉ: {worked_str}")
                if failed:
                    failed_str = ', '.join(f"{r['name']}(pen {r['pen']:.0f}p)" for r in failed[:4])
                    out.append(f"    ❌ CASSÉ:      {failed_str}")
                if dt_db:
                    parts = []
                    for r in dt_db:
                        s = r['name']
                        if r['dts']: s += f" {r['dts']}DT"
                        if r['dbs']: s += f" {r['dbs']}DB"
                        parts.append(s)
                    out.append(f"    🔄 DT/DB:      {', '.join(parts[:5])}")
                out.append("")

    # Global summary with tier reclassification
    if global_stats:
        out.append("  ── CLASSEMENT GLOBAL (tous jours) ──")
        out.append("")
        out.append(f"  {'Niveau':18s} {'App':>4s} {'%Reb':>5s} {'Cross':>5s} {'Pen':>5s} {'Score':>6s} {'DT':>3s} {'DB':>3s} {'Tier'}")
        out.append("  " + "-" * 70)

        globals_list = []
        for col, g in global_stats.items():
            br = g['bnc'] / g['app'] * 100 if g['app'] > 0 else 0
            ap = np.mean(g['pens']) if g['pens'] else 0
            ws = br / 100 * (1 / (1 + ap / 10)) if g['app'] > 0 else 0

            if g['app'] < 3:
                tier = '?'
            elif ws > 0.35:
                tier = 'T1 🧱'
            elif ws > 0.20:
                tier = 'T2 🪨'
            else:
                tier = 'T3 💨'

            globals_list.append({
                'name': g['name'], 'app': g['app'], 'br': br,
                'cross': g['cross'], 'pen': ap, 'ws': ws,
                'dts': g['dts'], 'dbs': g['dbs'], 'tier': tier
            })

        globals_list.sort(key=lambda x: x['ws'], reverse=True)
        for r in globals_list:
            dt_s = str(r['dts']) if r['dts'] else ''
            db_s = str(r['dbs']) if r['dbs'] else ''
            out.append(f"  {r['name']:18s} {r['app']:>3d} {r['br']:>4.0f}% {r['cross']:>4d} {r['pen']:>4.0f}p {r['ws']:>5.2f}  {dt_s:>3s} {db_s:>3s} {r['tier']}")

        out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 12 — BEST SESSIONS / HORAIRES
# ═════════════════════════════════════════════════════════════════════

PHASE_RULES = [
    ('Asia',       lambda h, m: (h >= 18) or (h < 2)),
    ('Asia_Late',  lambda h, m: (2 <= h < 4)),
    ('London',     lambda h, m: (4 <= h < 8)),
    ('Pre_Mkt',    lambda h, m: (8 <= h < 9)),
    ('Pre_Open',   lambda h, m: (h == 9 and m < 30)),
    ('Open_30m',   lambda h, m: (h == 9 and m >= 30) or (h == 10 and m < 30)),
    ('IB_Form',    lambda h, m: (h == 10 and m >= 30) or (h == 11 and m < 30)),
    ('Mid_AM',     lambda h, m: (11 <= h < 13)),
    ('Afternoon',  lambda h, m: (13 <= h < 15)),
    ('Power_Hr',   lambda h, m: (15 <= h < 16)),
]

def _assign_phase(h, m):
    for name, fn in PHASE_RULES:
        if fn(h, m):
            return name
    return 'Other'


def test_session_timing(nq_all: pd.DataFrame, data: dict, out: list):
    """Analyse les meilleures sessions et slots horaires pour trader."""
    out.append("=" * 70)
    out.append("  TEST 12 — MEILLEURES SESSIONS / HORAIRES")
    out.append("=" * 70)
    out.append("")

    if nq_all.empty or 'datetime_et' not in nq_all.columns:
        out.append("  Pas de données datetime")
        return

    df = nq_all.copy()
    df['hour_et'] = df['datetime_et'].dt.hour
    df['minute_et'] = df['datetime_et'].dt.minute
    df['phase'] = [_assign_phase(h, m) for h, m in zip(df['hour_et'], df['minute_et'])]
    df['slot_30'] = (df['hour_et'].astype(str).str.zfill(2) + ':' +
                     np.where(df['minute_et'] < 30, '00', '30'))

    has_bias = 'entry_bias' in df.columns
    has_signal = 'entry_signal' in df.columns
    has_sltp = 'sltp_valid' in df.columns

    # ── 1. Score contextuel par phase ──
    out.append("  ── PAR PHASE (score contextuel vs retour) ──")
    out.append("")
    out.append(f"  {'Phase':12s} {'Barres':>6s} {'r(bias→r3)':>11s} {'r(bias→r5)':>11s} "
               f"{'|r3| moy':>9s} {'Verdict'}")
    out.append("  " + "-" * 60)

    phase_order = [name for name, _ in PHASE_RULES]
    phase_scores = []

    for phase in phase_order:
        sub = df[df['phase'] == phase]
        if len(sub) < 10:
            continue

        r3_corr = sub['entry_bias'].corr(sub['fut_r3']) if has_bias else 0
        r5_corr = sub['entry_bias'].corr(sub['fut_r5']) if has_bias and 'fut_r5' in sub.columns else 0
        if pd.isna(r3_corr): r3_corr = 0
        if pd.isna(r5_corr): r5_corr = 0
        vol = sub['fut_r3'].abs().mean()

        n_valid = (sub['sltp_valid'] == True).sum() if has_sltp else 0
        n_sig = (sub['entry_signal'] != 0).sum() if has_signal else 0
        pct_valid = n_valid / max(1, n_sig) * 100 if n_sig > 0 else 0

        # Score composite
        composite = abs(r3_corr) * vol * (pct_valid / 100 + 0.1)

        verdict = "🟢 BON" if abs(r3_corr) > 0.20 else "🟡 OK" if abs(r3_corr) > 0.10 else "🔴 FAIBLE"

        out.append(f"  {phase:12s} {len(sub):>5d}   {r3_corr:>+.3f}       {r5_corr:>+.3f}    "
                   f"{vol:>7.1f}p  {verdict}")

        phase_scores.append({
            'phase': phase, 'r': abs(r3_corr), 'vol': vol,
            'n_valid': n_valid, 'n_bars': len(sub), 'pct_valid': pct_valid,
            'score': composite
        })

    out.append("")

    # ── 2. WR par slot 30 min (si signaux disponibles) ──
    if has_signal:
        out.append("  ── PAR SLOT 30 MIN (win rate signaux) ──")
        out.append("")
        out.append(f"  {'Slot':>6s} {'#Sig':>5s} {'SHORT':>6s} {'LONG':>6s} "
                   f"{'WR_S':>5s} {'WR_L':>5s} {'r3_S':>7s} {'r3_L':>7s}")
        out.append("  " + "-" * 55)

        for slot in sorted(df['slot_30'].unique()):
            sub = df[df['slot_30'] == slot]
            shorts = sub[sub['entry_signal'] == -1]
            longs = sub[sub['entry_signal'] == 1]
            n_sig = len(shorts) + len(longs)
            if n_sig < 3:
                continue

            wr_s = (shorts['fut_r3'] < 0).mean() * 100 if len(shorts) > 2 else 0
            wr_l = (longs['fut_r3'] > 0).mean() * 100 if len(longs) > 2 else 0
            r3_s = shorts['fut_r3'].mean() if len(shorts) > 2 else 0
            r3_l = longs['fut_r3'].mean() if len(longs) > 2 else 0

            best = max(wr_s, wr_l)
            icon = "🟢" if best > 65 else "🟡" if best > 55 else "  "

            out.append(f"  {slot:>6s} {n_sig:>4d}  {len(shorts):>5d}  {len(longs):>5d}  "
                       f"{wr_s:>4.0f}% {wr_l:>4.0f}% {r3_s:>+6.1f} {r3_l:>+6.1f}  {icon}")

        out.append("")

    # ── 3. Trades SLTP-validés par phase ──
    if has_sltp:
        valid = df[df['sltp_valid'] == True]
        if len(valid) > 0:
            out.append("  ── TRADES SLTP-VALIDÉS PAR PHASE ──")
            out.append("")
            out.append(f"  {'Phase':12s} {'Trades':>7s} {'SL moy':>7s} {'TP1':>5s} "
                       f"{'R:R':>5s} {'$SL':>5s}")
            out.append("  " + "-" * 45)

            for phase in phase_order:
                sub = valid[valid['phase'] == phase]
                if len(sub) < 2:
                    continue
                out.append(f"  {phase:12s} {len(sub):>6d}  {sub['sltp_sl_ticks'].mean():>4.0f}t "
                           f"{sub['sltp_tp1_ticks'].mean():>4.0f}t "
                           f"{sub['sltp_rr'].mean():>4.1f} ${sub['sltp_sl_usd'].mean():>3.0f}")

            out.append("")

    # ── 4. Volatilité par phase ──
    out.append("  ── VOLATILITÉ PAR PHASE (mouvement moyen 3 barres) ──")
    out.append("")
    for phase in phase_order:
        sub = df[df['phase'] == phase]
        if len(sub) < 10:
            continue
        vol = sub['fut_r3'].abs().mean()
        bar = "█" * int(vol / 2)
        out.append(f"  {phase:12s} {vol:>5.1f}p {bar}")
    out.append("")

    # ── 5. Classement final ──
    if phase_scores:
        phase_scores.sort(key=lambda x: x['score'], reverse=True)
        out.append("  ── CLASSEMENT (score = |corrélation| × volatilité × taux validation) ──")
        out.append("")
        for ps in phase_scores:
            icon = "🟢" if ps['score'] > 1.5 else "🟡" if ps['score'] > 0.5 else "🔴"
            out.append(f"  {icon} {ps['phase']:12s} score={ps['score']:>5.1f} | "
                       f"r={ps['r']:.2f} vol={ps['vol']:.1f}p "
                       f"valid={ps['n_valid']:>2d}/{ps['n_bars']}")
        out.append("")
        out.append(f"  RECOMMANDATION: trader en priorité les phases 🟢")
        out.append(f"  Phases 🔴 = le score contextuel ne prédit rien → pas de trade")
        out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 8 — VERDICT
# ═════════════════════════════════════════════════════════════════════

def test_verdict(results: list, data: dict, out: list):
    out.append("=" * 70)
    out.append("  VERDICT")
    out.append("=" * 70)
    out.append("")

    beton = [r for r in results if r['beton']]
    probable = [r for r in results if r['ci_ok'] and not r['day_ok']]
    fragile = [r for r in results if not r['ci_ok']]

    n_days = len(data)
    total_bars = sum(
        len(d["NQ_raw"]) for d in data.values()
        if d.get("NQ_raw") is not None and not d["NQ_raw"].empty
    )

    out.append(f"  Dataset: {n_days} jours, {total_bars} barres NQ")
    out.append(f"  Bootstrap: {N_BOOTSTRAP} itérations, IC 95%")
    out.append("")
    out.append(f"  BÉTON:    {len(beton):>2d} features")
    for r in beton:
        out.append(f"    {r['col']:34s} r={r['r3']:+.3f} [{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]")
    out.append(f"  PROBABLE: {len(probable):>2d} features")
    for r in probable:
        out.append(f"    {r['col']:34s} r={r['r3']:+.3f} [{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]")
    out.append(f"  FRAGILE:  {len(fragile):>2d} features")
    out.append("")

    # Minimum data needed
    if n_days < 5:
        out.append(f"  ⚠️ {n_days} jours seulement — minimum recommandé: 20 jours")
        out.append(f"     Les features FRAGILES sont non-prouvées, pas mortes.")
        out.append(f"     Ne pas optimiser de seuils sur ce dataset.")
    elif n_days < 20:
        out.append(f"  ⚠️ {n_days} jours — résultats indicatifs, pas définitifs.")
    else:
        out.append(f"  ✅ {n_days} jours — résultats exploitables.")

    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 13 — DMP HEALTH CHECK (signaux BN vivants/morts)
# ═════════════════════════════════════════════════════════════════════

# Signaux persistants GARDES (CLAUDE.md liste DROP retirees : bn_color_up/dn, bn_pressure_ask,
# bar_color_up/dn, bar_pressure_ask, bn_long_up/dn, bn_volume_up/dn)
BN_MUST_FIRE = [
    ('bn_color_up_2',    0.01, 'COLOR UP 2 — double stacke'),
    ('bn_color_dn_2',    0.01, 'COLOR DN 2 — double stacke'),
    ('bn_pressure_bid',  0.10, 'TRIPLE/DOUBLE BID'),
    ('bar_pressure_bid', 0.10, 'TRIPLE/DOUBLE BID BARRES'),
    ('bn_absorb_bid',    0.05, 'ABSORB BID'),
    ('bn_absorb_ask',    0.05, 'ABSORB ASK'),
]

# Signaux per-bar GARDES — au moins 1 fire sur 50+ barres
BN_SHOULD_FIRE = [
    'bar_edge_buy', 'bar_edge_sell',
    'fp_edge_buy', 'fp_edge_sell',
    'rvol_buy', 'rvol_sell', 'rvol_absorb_buy', 'rvol_absorb_sell',
    'delta_divergence',
]

# Distances Extension Lines GARDEES (dist_ext_color_up/dn retirees du DROP list)
EXT_MUST_LIVE = [
    ('dist_ext_edge_buy',  0.03, 'EDGE BUY distance (tracker 6D)'),
    ('dist_ext_edge_sell', 0.03, 'EDGE SELL distance (tracker 6D)'),
    ('dist_ext_long_up',   0.01, 'LONG UP BAR distance (fix 13/03)'),
    ('dist_ext_long_dn',   0.01, 'LONG DN BAR distance (fix 13/03)'),
]

# Features qui doivent varier
# NOTE: range_pos et bars_in_va retirés — peuvent être constants (100% / 0)
# quand le prix reste hors VA toute la session (breakout, gap day). Pas un bug.
MUST_VARY = [
    ('momentum_3b', 5), ('momentum_5b', 5),
    ('cvd_bar_delta', 5),
    ('bn_score_raw', 2), ('bn_score_bull', 2), ('bn_score_bear', 2),
    ('rvol', 5), ('rvol_zscore', 5),
]


def test_dmp_health(data: dict, out: list):
    """Vérifie que tous les signaux BN, Extension Lines et features range sont vivants."""
    out.append("=" * 70)
    out.append("  TEST 13 — DMP HEALTH CHECK (signaux vivants/morts)")
    out.append("=" * 70)
    out.append("")

    errors = 0
    warnings = 0
    ok = 0

    for date in sorted(data.keys()):
        for sym_key in ['NQ_raw', 'ES_raw']:
            df = data[date].get(sym_key)
            if df is None or df.empty:
                continue
            sym = 'NQ' if 'NQ' in sym_key else 'ES'
            df = df.reset_index(drop=True)
            n = len(df)
            sessions = df['session_id'].value_counts().to_dict() if 'session_id' in df.columns else {}

            out.append(f"  {sym} {date} ({n} barres, {sessions}):")

            # Signaux persistants
            for col, min_pct, desc in BN_MUST_FIRE:
                if col not in df.columns:
                    out.append(f"    ⚠️ {col:25s} ABSENT du JSONL")
                    warnings += 1
                    continue
                nz = (df[col].fillna(0) != 0).sum()
                pct = nz / n if n > 0 else 0
                if pct < min_pct and n >= 30:
                    out.append(f"    ❌ {col:25s} {nz:>3d}/{n} ({pct:>4.0%}) < {min_pct:.0%} — {desc}")
                    errors += 1
                else:
                    ok += 1

            # Signaux per-bar
            for col in BN_SHOULD_FIRE:
                if col not in df.columns:
                    continue
                nz = (df[col].fillna(0) != 0).sum()
                if nz == 0 and n >= 50:
                    out.append(f"    ⚠️ {col:25s} 0/{n} — jamais firé")
                    warnings += 1
                else:
                    ok += 1

            # Distances Extension Lines
            for col, min_pct, desc in EXT_MUST_LIVE:
                if col not in df.columns:
                    continue
                nn = df[col].notna().sum()
                pct = nn / n if n > 0 else 0
                if pct < min_pct and n >= 30:
                    out.append(f"    ❌ {col:25s} {nn}/{n} non-null ({pct:.0%}) — {desc}")
                    errors += 1
                else:
                    ok += 1

            # Features range trading
            for col, min_unique in MUST_VARY:
                if col not in df.columns:
                    continue
                nu = df[col].dropna().nunique()
                if nu < min_unique and n >= 30:
                    out.append(f"    ❌ {col:25s} nu={nu} < {min_unique} — CONSTANT")
                    errors += 1
                else:
                    ok += 1

            # Cohérence logique
            if 'buy_vol' in df.columns and 'sell_vol' in df.columns:
                bv, sv, tv = df['buy_vol'], df['sell_vol'], df['total_vol']
                bad = ((bv + sv - tv).abs() > 1).sum()
                if bad > 0:
                    out.append(f"    ❌ buy+sell≠total: {bad}/{n} incohérences")
                    errors += 1
                else:
                    ok += 1

            if 'bn_score_raw' in df.columns:
                raw = df['bn_score_raw']
                bull = df['bn_score_bull']
                bear = df['bn_score_bear']
                bad = ((raw - (bull - bear)).abs() > 0.02).sum()
                if bad > 0:
                    out.append(f"    ❌ score≠bull-bear: {bad}/{n}")
                    errors += 1
                else:
                    ok += 1

            out.append("")

    # Verdict
    if errors == 0:
        out.append(f"  ✅ DMP PROPRE — {ok} checks passent, {warnings} warnings")
    else:
        out.append(f"  🔴 {errors} ERREURS — données potentiellement corrompues")
        out.append(f"     Lancer dmp_validator.py pour diagnostic détaillé")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def test_rvol_validation(data: dict, out: list):
    """Test 14 — Compare RVOL C++ (ring buffer) vs Python (recalcul pandas)."""
    out.append("=" * 70)
    out.append("  TEST 14 — RVOL VALIDATION (C++ vs Python)")
    out.append("=" * 70)
    out.append("")

    LOOKBACK = 20
    SPIKE = 2.0
    DELTA_THRESH = 0.05

    total_ok = 0
    total_err = 0

    for date in sorted(data.keys()):
        for sym_key in ['NQ_raw', 'ES_raw']:
            df = data[date].get(sym_key)
            if df is None or df.empty:
                continue
            sym = 'NQ' if 'NQ' in sym_key else 'ES'
            df = df.reset_index(drop=True)
            n = len(df)

            if 'rvol' not in df.columns or 'total_vol' not in df.columns:
                out.append(f"  ⚠️ {sym} {date}: colonnes RVOL absentes")
                continue

            # ── Python recalcul ──
            vol = df['total_vol'].values.astype(float)
            py_rvol = np.full(n, 1.0)
            for i in range(n):
                lo = max(0, i - LOOKBACK)
                window = vol[lo:i]  # barres AVANT (sans la barre courante)
                if len(window) >= 5:
                    avg = np.mean(window)
                    if avg > 0:
                        py_rvol[i] = vol[i] / avg

            cpp_rvol = df['rvol'].values.astype(float)

            # ── Comparaison ──
            # Ignorer les 5 premières barres (warmup)
            start = min(5, n)
            if n <= start:
                out.append(f"  ⚠️ {sym} {date}: trop peu de barres ({n})")
                continue

            # Tolérance: ±20% ou ±0.1 absolu (C++ = rolling strict, Python = fenêtre glissante)
            diffs = []
            mismatches = 0
            for i in range(start, n):
                c = cpp_rvol[i]
                p = py_rvol[i]
                if c == 1.0 and i < LOOKBACK:
                    continue  # warmup C++
                rel_diff = abs(c - p) / max(p, 0.01)
                diffs.append(rel_diff)
                if rel_diff > 0.30:  # 30% tolérance (ring buffer vs window)
                    mismatches += 1

            valid = len(diffs)
            if valid == 0:
                continue

            avg_diff = np.mean(diffs) * 100
            max_diff = np.max(diffs) * 100
            match_pct = (valid - mismatches) / valid * 100

            status = "✅" if match_pct >= 90 else ("🟡" if match_pct >= 70 else "🔴")
            out.append(f"  {status} {sym} {date}: {match_pct:.0f}% match | "
                       f"avg_diff={avg_diff:.1f}% max_diff={max_diff:.0f}% | "
                       f"{mismatches}/{valid} hors tolérance")

            if match_pct >= 90:
                total_ok += 1
            else:
                total_err += 1

            # ── RVOL signaux check ──
            rvol_buy_cpp = (df['rvol_buy'].fillna(0) > 0).sum() if 'rvol_buy' in df.columns else 0
            rvol_sell_cpp = (df['rvol_sell'].fillna(0) > 0).sum() if 'rvol_sell' in df.columns else 0
            rvol_abs_b = (df['rvol_absorb_buy'].fillna(0) > 0).sum() if 'rvol_absorb_buy' in df.columns else 0
            rvol_abs_s = (df['rvol_absorb_sell'].fillna(0) > 0).sum() if 'rvol_absorb_sell' in df.columns else 0
            spikes = (cpp_rvol >= SPIKE).sum()

            out.append(f"         spikes≥2x: {spikes} | buy={rvol_buy_cpp} sell={rvol_sell_cpp} "
                       f"absorb_buy={rvol_abs_b} absorb_sell={rvol_abs_s}")

            # ── Stats RVOL ──
            active_rvol = cpp_rvol[cpp_rvol != 1.0]
            if len(active_rvol) > 0:
                out.append(f"         RVOL stats: min={active_rvol.min():.3f} "
                           f"avg={active_rvol.mean():.3f} max={active_rvol.max():.3f} "
                           f"std={active_rvol.std():.3f}")
            out.append("")

    # Verdict
    if total_err == 0 and total_ok > 0:
        out.append(f"  ✅ RVOL C++ validé — {total_ok} datasets matchent Python (>90%)")
    elif total_err > 0:
        out.append(f"  🟡 RVOL divergences — {total_err} datasets < 90% match")
        out.append(f"     Normal si mix données pre/post fix dans le même fichier")
    else:
        out.append(f"  ⚠️ Pas assez de données pour valider RVOL")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 15 — SESSION IB & TRANSITIONS
# ═════════════════════════════════════════════════════════════════════

def test_session_ib(data: dict, out: list):
    """Test 15 — Analyse IB Asia/London/US, transitions, zones no-trade."""
    out.append("=" * 70)
    out.append("  TEST 15 — SESSION IB & TRANSITIONS")
    out.append("=" * 70)
    out.append("")

    ZONES = [
        ('ASIA_WARMUP',     19, 0,  20, 0,  '00h-01h Paris'),
        ('ASIA_IB',         20, 0,  22, 0,  '01h-03h Paris  ◀ IB Asia'),
        ('ASIA_QUIET',      22, 0,   2, 0,  '03h-07h Paris'),
        ('PRE_LONDON',       2, 0,   2, 30, '07h-07h30 Paris'),
        ('LONDON_TRANS',     2, 30,  3, 15, '07h30-08h15 Paris ⚠️'),
        ('LONDON_ACTIVE',    3, 15,  4, 30, '08h15-09h30 Paris'),
        ('US_TRANS',         9, 30,  9, 45, '15h30-15h45 Paris ⚠️'),
        ('US_IB_FORMING',    9, 45, 10, 30, '15h45-16h30 Paris ◀ IB US'),
        ('US_ACTIVE',       10, 30, 12, 0,  '16h30-18h Paris'),
        ('MID_AM',          12, 0,  14, 0,  '18h-20h Paris'),
        ('US_PM',           14, 0,  16, 0,  '20h-22h Paris'),
    ]

    def get_zone_et(h, m):
        t = h * 60 + m
        for name, sh, sm, eh, em, _ in ZONES:
            s = sh * 60 + sm
            e = eh * 60 + em
            if e > s:
                if s <= t < e:
                    return name
            else:
                if t >= s or t < e:
                    return name
        return 'OTHER'

    all_zone_stats = {}

    for date in sorted(data.keys()):
        for sym_key in ['NQ_raw']:
            df = data[date].get(sym_key)
            if df is None or df.empty:
                continue
            df = df.reset_index(drop=True)
            n = len(df)
            if n < 30:
                continue

            prices = df['price'].values
            r3 = np.full(n, np.nan)
            for i in range(n - 3):
                r3[i] = prices[i + 3] - prices[i]

            if 'datetime_et' in df.columns:
                hours_et = df['datetime_et'].dt.hour.values
                mins_et = df['datetime_et'].dt.minute.values
            elif 'ts' in df.columns:
                dts = pd.to_datetime(df['ts'], unit='ms', utc=True)
                hours_et = ((dts.dt.hour - 4) % 24).values
                mins_et = dts.dt.minute.values
            else:
                continue

            zones_arr = [get_zone_et(int(hours_et[i]), int(mins_et[i])) for i in range(n)]

            out.append(f"  NQ {date} ({n} barres):")
            out.append("")

            # ── Asia IB range ──
            asia_ib_mask = [z == 'ASIA_IB' for z in zones_arr]
            asia_ib_bars = df[asia_ib_mask]
            if len(asia_ib_bars) > 5:
                ib_high = asia_ib_bars['price'].max()
                ib_low = asia_ib_bars['price'].min()
                ib_range = ib_high - ib_low
                ib_vol = asia_ib_bars['total_vol'].mean()
                out.append(f"    📐 ASIA IB: {ib_low:.2f} — {ib_high:.2f} "
                           f"(range={ib_range:.0f}t, vol_moy={ib_vol:.0f})")

                london_mask = [z in ('LONDON_ACTIVE', 'LONDON_TRANS') for z in zones_arr]
                london_bars = df[london_mask]
                if len(london_bars) > 0:
                    broke_up = london_bars['price'].max() > ib_high
                    broke_dn = london_bars['price'].min() < ib_low
                    if broke_dn and not broke_up:
                        out.append(f"    → London casse Asia IB LOW → direction DOWN")
                    elif broke_up and not broke_dn:
                        out.append(f"    → London casse Asia IB HIGH → direction UP")
                    elif broke_up and broke_dn:
                        out.append(f"    → London casse les DEUX côtés → CHOP")
                    else:
                        out.append(f"    → London reste DANS l'Asia IB → range")

                us_mask = [z in ('US_ACTIVE', 'US_IB_FORMING', 'MID_AM', 'US_PM') for z in zones_arr]
                us_bars = df[us_mask]
                if len(us_bars) > 0:
                    us_broke_up = us_bars['price'].max() > ib_high
                    us_broke_dn = us_bars['price'].min() < ib_low
                    if us_broke_dn or us_broke_up:
                        out.append(f"    → US casse Asia IB {'HIGH ' if us_broke_up else ''}"
                                   f"{'LOW' if us_broke_dn else ''}")
                out.append("")

            # ── Stats par zone ──
            out.append(f"    {'Zone':<18s} {'N':>4s} {'Vol':>6s} {'|r3|':>6s} "
                       f"{'WR%':>5s} {'BN→r3':>6s} {'Verdict':>12s}")
            out.append(f"    {'-'*65}")

            for zone_name, sh, sm, eh, em, desc in ZONES:
                mask = [z == zone_name for z in zones_arr]
                idx = [i for i, m in enumerate(mask) if m and not np.isnan(r3[i])]
                if len(idx) < 3:
                    continue

                vols = [df.iloc[i]['total_vol'] for i in idx]
                r3_vals = [r3[i] for i in idx]
                abs_r3 = [abs(v) for v in r3_vals]
                vol_avg = np.mean(vols)
                abs_r3_avg = np.mean(abs_r3)

                r3_mean = np.mean(r3_vals)
                if r3_mean >= 0:
                    wr = sum(1 for v in r3_vals if v > 0) / len(r3_vals) * 100
                else:
                    wr = sum(1 for v in r3_vals if v < 0) / len(r3_vals) * 100

                bn_ok = bn_tot = 0
                for i in idx:
                    bn = df.iloc[i].get('bn_score_raw', 0)
                    if bn is None or bn == 0:
                        continue
                    bn_tot += 1
                    if (bn > 0 and r3[i] > 0) or (bn < 0 and r3[i] < 0):
                        bn_ok += 1
                bn_wr = (bn_ok / bn_tot * 100) if bn_tot >= 5 else np.nan

                if abs_r3_avg > 8 and wr < 53:
                    verdict = "🔴 NO TRADE"
                elif abs_r3_avg > 6 and wr < 52:
                    verdict = "🟡 PRUDENT"
                elif wr >= 60 or (not np.isnan(bn_wr) and bn_wr >= 60):
                    verdict = "🟢 TRADE"
                elif 'IB' in zone_name or 'FORMING' in zone_name:
                    verdict = "📐 OBSERVER"
                elif 'TRANS' in zone_name:
                    verdict = "⚠️ TRANSITION"
                else:
                    verdict = "🟡 NEUTRE"

                bn_str = f"{bn_wr:.0f}%" if not np.isnan(bn_wr) else "  N/A"
                out.append(f"    {zone_name:<18s} {len(idx):>4d} {vol_avg:>5.0f} "
                           f"{abs_r3_avg:>5.1f} {wr:>4.0f}% {bn_str:>6s} {verdict:>12s}")

                if zone_name not in all_zone_stats:
                    all_zone_stats[zone_name] = {'n': 0, 'wr_sum': 0, 'vol_sum': 0,
                                                  'abs_r3_sum': 0, 'days': 0}
                all_zone_stats[zone_name]['n'] += len(idx)
                all_zone_stats[zone_name]['wr_sum'] += wr * len(idx)
                all_zone_stats[zone_name]['vol_sum'] += vol_avg * len(idx)
                all_zone_stats[zone_name]['abs_r3_sum'] += abs_r3_avg * len(idx)
                all_zone_stats[zone_name]['days'] += 1

            out.append("")

    # ── Résumé multi-jours ──
    if all_zone_stats:
        n_days = max(s['days'] for s in all_zone_stats.values())
        out.append(f"  ── CLASSEMENT ZONES ({n_days} jours) ──")
        out.append("")
        out.append(f"    {'Zone':<18s} {'Barres':>7s} {'Vol':>6s} {'|r3|':>6s} "
                   f"{'WR%':>5s} {'Verdict':>12s}")
        out.append(f"    {'-'*60}")

        sorted_zones = sorted(all_zone_stats.items(),
                              key=lambda x: x[1]['wr_sum'] / max(x[1]['n'], 1),
                              reverse=True)
        for zone_name, s in sorted_zones:
            if s['n'] < 5:
                continue
            avg_wr = s['wr_sum'] / s['n']
            avg_vol = s['vol_sum'] / s['n']
            avg_r3 = s['abs_r3_sum'] / s['n']
            if avg_r3 > 8 and avg_wr < 53:
                verdict = "🔴 NO TRADE"
            elif avg_wr >= 60:
                verdict = "🟢 TRADE"
            elif 'TRANS' in zone_name:
                verdict = "⚠️ DANGER"
            elif 'IB' in zone_name or 'FORMING' in zone_name:
                verdict = "📐 OBSERVER"
            else:
                verdict = "🟡 NEUTRE"
            out.append(f"    {zone_name:<18s} {s['n']:>7d} {avg_vol:>5.0f} "
                       f"{avg_r3:>5.1f} {avg_wr:>4.0f}% {verdict:>12s}")

        out.append("")
        out.append("  → Verdicts = base pour le Session Planner (Phase 2)")
        out.append(f"  → Minimum recommandé: 10 jours (actuellement: {n_days})")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 16 — RETOUR AUX NIVEAUX PREV
# ═════════════════════════════════════════════════════════════════════

def test_prev_returns(data: dict, out: list):
    """Test 16 — Le prix revient-il aux PREV levels ? Rebond ou continuation ?
    + CROISEMENT avec signaux de divergence (absorb, retest_delta_div).
    """
    out.append("  ═══ TEST 16: RETOUR AUX PREV LEVELS ═══")
    out.append("")

    prev_cols = [
        ('dist_prev_vwap',      'PREV_VWAP'),
        ('dist_prev_vah',       'PREV_VAH'),
        ('dist_prev_val',       'PREV_VAL'),
        ('dist_prev_vpoc',      'PREV_VPOC'),
        ('dist_prev_vwap_sd1u', 'PREV_VWAP+1SD'),
        ('dist_prev_vwap_sd1d', 'PREV_VWAP-1SD'),
    ]

    out.append(f"  {'Niveau':<18s} {'Sym':>3s} {'Sess':>7s} {'N':>5s} "
               f"{'r5':>6s} {'r10':>6s} {'Reb%':>5s}")
    out.append(f"  {'-'*55}")

    for sym, sym_key in [('NQ', 'NQ_raw'), ('ES', 'ES_raw')]:
        sym_frames = []
        for date in sorted(data.keys()):
            df = data[date].get(sym_key)
            if df is not None and not df.empty:
                sym_frames.append(df)
        if not sym_frames:
            continue
        df_all = pd.concat(sym_frames, ignore_index=True)

        df_all['_r5'] = df_all['price'].shift(-5) - df_all['price']
        df_all['_r10'] = df_all['price'].shift(-10) - df_all['price']
        df_all['_r20'] = df_all['price'].shift(-20) - df_all['price']

        for col, name in prev_cols:
            if col not in df_all.columns:
                continue
            for sess in ['Asia', 'London', 'US']:
                mask = (df_all[col].notna() &
                        (df_all[col].abs() < 20) &
                        (df_all.get('session_id', '') == sess) &
                        df_all['_r5'].notna())
                close = df_all[mask]
                if len(close) < 3:
                    continue
                avg_r5 = close['_r5'].mean()
                avg_r10 = close['_r10'].mean()
                avg_sign = close[col].mean()
                rebounds = (close['_r5'] < 0).sum() if avg_sign > 0 else (close['_r5'] > 0).sum()
                reb_pct = rebounds / len(close) * 100
                v = "🔥" if reb_pct >= 64 else ("✅" if reb_pct >= 55 else "⚠️")
                out.append(f"  {name:<18s} {sym:>3s} {sess:>7s} {len(close):>5d} "
                           f"{avg_r5:>+5.1f} {avg_r10:>+5.1f} {reb_pct:>4.0f}% {v}")

        # ── 16b. CROISEMENT PREV LEVELS × DIVERGENCES ──
        out.append("")
        out.append(f"  ── 16b. {sym} — PREV × DIVERGENCES (< 20 ticks du niveau) ──")
        out.append(f"  {'Combo':<40s} {'N':>4s} {'WR+10b':>7s} {'Avg':>8s}")
        out.append(f"  {'-'*62}")

        # Divergence signals
        absorb_b = (df_all.get('rvol_absorb_buy', 0) == 1)
        absorb_s = (df_all.get('rvol_absorb_sell', 0) == 1)
        retest_l = (df_all.get('retest_low_delta_div', 0) == 1)
        retest_h = (df_all.get('retest_high_delta_div', 0) == 1)
        any_bull_div = absorb_b | retest_l
        any_bear_div = absorb_s | retest_h

        for col, name in [('dist_prev_vwap', 'PVWAP'),
                          ('dist_prev_vpoc', 'PVPOC'),
                          ('dist_prev_val', 'PVAL'),
                          ('dist_prev_vah', 'PVAH')]:
            if col not in df_all.columns:
                continue
            near = df_all[col].abs() < 20

            # SEUL (baseline)
            for side_name, side_mask, bounce_dir in [
                ("dessus", df_all[col] > 0, -1),
                ("dessous", df_all[col] < 0, 1),
            ]:
                base = near & side_mask & df_all['_r10'].notna()
                base_df = df_all[base]
                if len(base_df) >= 3:
                    wr = ((base_df['_r10'] * bounce_dir) > 0).sum() / len(base_df) * 100
                    avg = base_df['_r10'].mean()
                    out.append(f"  {name+' '+side_name+' SEUL':<40s} "
                               f"{len(base_df):>4d} {wr:>5.1f}%  {avg:>+7.2f}t")

            # PREV + divergence bullish (prix en dessous → rebond up attendu)
            combo_bull = near & (df_all[col] < 0) & any_bull_div & df_all['_r10'].notna()
            cb = df_all[combo_bull]
            if len(cb) >= 2:
                wr = (cb['_r10'] > 0).sum() / len(cb) * 100
                star = "⭐" if wr >= 60 else ""
                out.append(f"  {name+' dessous + BULL div':<40s} "
                           f"{len(cb):>4d} {wr:>5.1f}%  {cb['_r10'].mean():>+7.2f}t {star}")

            # PREV + divergence bearish (prix au dessus → rejet down attendu)
            combo_bear = near & (df_all[col] > 0) & any_bear_div & df_all['_r10'].notna()
            cbr = df_all[combo_bear]
            if len(cbr) >= 2:
                wr = (cbr['_r10'] < 0).sum() / len(cbr) * 100
                star = "⭐" if wr >= 60 else ""
                out.append(f"  {name+' dessus + BEAR div':<40s} "
                           f"{len(cbr):>4d} {wr:>5.1f}%  {cbr['_r10'].mean():>+7.2f}t {star}")

        out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 17 — MARKET PROFILE AVANCÉ
# ═════════════════════════════════════════════════════════════════════

def test_market_profile_advanced(data: dict, out: list):
    """Test 17 — IB Extension, Failed Auction, Rotation Factor, POC Migration."""
    out.append("  ═══ TEST 17: MARKET PROFILE AVANCÉ ═══")
    out.append("")

    mp_cols = [
        ('ctx_ib_extension_ratio', 'IB Extension'),
        ('ctx_rotation_factor_20', 'Rotation Factor'),
        ('ctx_poc_migration_10',   'POC Migration'),
        ('ctx_va_developing_10',   'VA Developing'),
        ('ctx_failed_auction',     'Failed Auction'),
    ]

    for sym, sym_key in [('NQ', 'NQ_ctx'), ('ES', 'ES_ctx')]:
        sym_frames = []
        for date in sorted(data.keys()):
            df = data[date].get(sym_key)
            if df is not None and not df.empty:
                sym_frames.append(df)
        if not sym_frames:
            continue
        df_all = pd.concat(sym_frames, ignore_index=True)
        n = len(df_all)
        df_all['_r5'] = df_all['price'].shift(-5) - df_all['price']

        out.append(f"  ── {sym} ({n} barres) ──")

        for col, name in mp_cols:
            if col not in df_all.columns:
                out.append(f"    {name:<20s} ⚠️ absent")
                continue
            vals = df_all[col].dropna()
            if len(vals) == 0:
                continue
            out.append(f"    {name:<20s} n={len(vals):>5d} "
                       f"min={vals.min():>8.3f} max={vals.max():>8.3f} "
                       f"mean={vals.mean():>8.3f}")

        # IB Extension buckets
        if 'ctx_ib_extension_ratio' in df_all.columns:
            out.append(f"    IB Extension buckets:")
            for label, lo, hi in [('Inside (<1.0)', 0, 1.0),
                                   ('Normal (1-1.5)', 1.0, 1.5),
                                   ('Extend (1.5-2)', 1.5, 2.0),
                                   ('Trend (>2.0)', 2.0, 99)]:
                bars = ((df_all['ctx_ib_extension_ratio'] >= lo) &
                        (df_all['ctx_ib_extension_ratio'] < hi)).sum()
                out.append(f"      {label:<20s} {bars:>5d} ({bars/n*100:>4.0f}%)")

        # Failed Auction
        if 'ctx_failed_auction' in df_all.columns:
            fa = df_all[df_all['ctx_failed_auction'] == 1]
            out.append(f"    Failed Auctions: {len(fa)} détectés")
            if len(fa) > 2:
                fa_r = fa[fa['_r5'].notna()]
                if len(fa_r) > 0:
                    vpoc_d = fa_r.get('dist_cur_vpoc', pd.Series(0, index=fa_r.index))
                    aligned = sum(1 for v, r in zip(vpoc_d, fa_r['_r5'])
                                  if (v > 0 and r > 0) or (v < 0 and r < 0))
                    out.append(f"      Retour vers VPOC: {aligned}/{len(fa_r)} "
                               f"({aligned/len(fa_r)*100:.0f}%)")

        # Rotation Factor
        if 'ctx_rotation_factor_20' in df_all.columns:
            rot = df_all['ctx_rotation_factor_20'].dropna()
            if len(rot) > 0:
                hi_rot = (rot >= 4).sum()
                lo_rot = (rot <= 1).sum()
                out.append(f"    Rotation: mean={rot.mean():.1f} | "
                           f"≥4(range)={hi_rot}({hi_rot/len(rot)*100:.0f}%) | "
                           f"≤1(trend)={lo_rot}({lo_rot/len(rot)*100:.0f}%)")
        out.append("")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 18 — AMD (Accumulation, Manipulation, Distribution)
# ═════════════════════════════════════════════════════════════════════

def test_amd(data: dict, out: list):
    """
    Test du module AMD (ICT Power of 3).
    Vérifie: phases, sweeps (one-shot), Judas Swings, PO3, performance.
    """
    out.append("")
    out.append("=" * 70)
    out.append("  TEST 18 — AMD (Accumulation, Manipulation, Distribution)")
    out.append("=" * 70)

    for sym in ('NQ', 'ES'):
        sym_key = f'{sym}_raw'
        dates = sorted([d for d in data if data[d].get(sym_key) is not None
                        and not data[d][sym_key].empty])
        if not dates:
            continue

        all_dfs = []
        for date in dates:
            df = data[date][sym_key].copy()
            if len(df) < 10:
                continue
            engine = AmdEngine(symbol=sym)
            df = engine.compute(df)
            all_dfs.append((date, df))

        if not all_dfs:
            out.append(f"  {sym}: pas assez de données")
            continue

        out.append(f"\n  ── {sym} ({len(all_dfs)} jours) ──")

        # 18a. Structure
        out.append(f"  18a. Structure:")
        total_bars = sum(len(d) for _, d in all_dfs)
        total_judas = sum((d['amd_judas_swing'] > 0).sum() for _, d in all_dfs)
        total_sw = sum((d['amd_sweep_up'] > 0).sum() + (d['amd_sweep_dn'] > 0).sum() for _, d in all_dfs)
        total_po3b = sum((d['amd_po3_bullish'] > 0).sum() for _, d in all_dfs)
        total_po3br = sum((d['amd_po3_bearish'] > 0).sum() for _, d in all_dfs)
        total_dist = sum((d['amd_dist_confirmed'] > 0).sum() for _, d in all_dfs)

        out.append(f"    Barres: {total_bars} | Sweeps: {total_sw} | Judas: {total_judas}")
        out.append(f"    Dist conf: {total_dist} | PO3 Bull/Bear: {total_po3b}/{total_po3br}")

        # Sweep ratio < 5%
        sw_pct = total_sw / max(total_bars, 1) * 100
        out.append(f"    Sweep ratio: {sw_pct:.1f}% {'✅ (<5%)' if sw_pct < 5 else '❌ trop'}")

        # Features check
        sample = all_dfs[0][1]
        missing = [f for f in AMD_FEATURES if f not in sample.columns]
        out.append(f"    Features: {len(AMD_FEATURES)-len(missing)}/18 "
                   f"{'✅' if not missing else '❌ ' + str(missing)}")

        # 18b. Par jour
        out.append(f"  18b. Par jour:")
        for date, df in all_dfs:
            n = len(df)
            sw = (df['amd_sweep_up'] > 0).sum() + (df['amd_sweep_dn'] > 0).sum()
            jd = (df['amd_judas_swing'] > 0).sum()
            dc = (df['amd_dist_confirmed'] > 0).sum()
            p3 = (df['amd_po3_bullish'] > 0).sum() + (df['amd_po3_bearish'] > 0).sum()
            ar = df['amd_asia_range_ticks'].dropna()
            ar_s = f"{ar.mean():.0f}t" if len(ar) > 0 else "N/A"
            out.append(f"    {date}: {n:>4d}b Asia={ar_s:>5s} sw={sw} jd={jd} dc={dc} po3={p3}")

        # 18c. Performance prédictive
        out.append(f"  18c. Performance +10b:")
        combined = pd.concat([d for _, d in all_dfs], ignore_index=True)
        combined['future_10b'] = combined['price'].shift(-10) - combined['price']

        for label, mask, edir in [
            ("Judas BULL", (combined['amd_judas_swing']>0)&(combined['amd_manip_dir']<0), 1),
            ("Judas BEAR", (combined['amd_judas_swing']>0)&(combined['amd_manip_dir']>0), -1),
            ("PO3 Bull",   combined['amd_po3_bullish']>0, 1),
            ("PO3 Bear",   combined['amd_po3_bearish']>0, -1),
        ]:
            fut = combined.loc[mask, 'future_10b'].dropna()
            if len(fut) >= 3:
                wr = ((fut * edir) > 0).sum() / len(fut) * 100
                star = "⭐" if wr >= 55 else ""
                out.append(f"    {label:15s}: {len(fut):>4d} sig WR={wr:>5.1f}% avg={fut.mean():>+7.2f}t {star}")
            else:
                out.append(f"    {label:15s}: <3 sig (insuffisant)")

        # 18d. Corrélation manip_score
        ms = combined.loc[combined['amd_manip_score'] > 0]
        if len(ms) >= 10:
            corr = ms[['amd_manip_score', 'future_10b']].dropna().corr().iloc[0, 1]
            out.append(f"  18d. Corr(manip_score→future): {corr:+.3f} "
                       f"{'✅' if abs(corr)>0.05 else '⚠️ faible'}")
        out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 19 — DOUBLE TOP / BOTTOM (mia_double_top.py)
# ═════════════════════════════════════════════════════════════════════

def test_double_top(data: dict, out: list):
    """
    Test du module mia_double_top.py.
    Exécute detect_double_top_bottom sur chaque barre et évalue:
      - Fréquence des détections (DT / DB)
      - Qualité des boost scores
      - Performance prédictive des retests confirmés
    """
    out.append("")
    out.append("=" * 70)
    out.append("  TEST 19 — DOUBLE TOP / BOTTOM (mia_double_top.py)")
    out.append("=" * 70)

    try:
        from mia_double_top import detect_double_top_bottom, RetestConfig
    except ImportError:
        out.append("  ⚠️ mia_double_top.py non trouvé — test ignoré")
        return

    for sym, sym_key in [('NQ', 'NQ_raw'), ('ES', 'ES_raw')]:
        sym_frames = []
        for date in sorted(data.keys()):
            df = data[date].get(sym_key)
            if df is not None and not df.empty:
                sym_frames.append(df)
        if not sym_frames:
            continue

        df_all = pd.concat(sym_frames, ignore_index=True)
        n = len(df_all)
        if n < 50:
            out.append(f"  {sym}: {n} barres (< 50, skip)")
            continue

        out.append(f"\n  ── {sym} ({n} barres) ──")

        # Exécuter detect_double_top_bottom sur chaque barre
        bars = df_all.to_dict('records')
        config = RetestConfig()
        results = []
        for i in range(len(bars)):
            try:
                r = detect_double_top_bottom(bars, i, symbol=sym, config=config)
                results.append(r)
            except Exception:
                results.append(None)

        # Classifier les résultats
        dt_count = sum(1 for r in results if r and r.retest_type and r.retest_type.name == 'DOUBLE_TOP')
        db_count = sum(1 for r in results if r and r.retest_type and r.retest_type.name == 'DOUBLE_BOTTOM')
        active = [r for r in results if r and r.is_active()]
        boost_scores = [r.boost_score for r in active if r.boost_score > 0]

        out.append(f"    Double Tops:    {dt_count:>4d}")
        out.append(f"    Double Bottoms: {db_count:>4d}")
        out.append(f"    Actifs:         {len(active):>4d} ({len(active)/n*100:.1f}%)")

        if boost_scores:
            out.append(f"    Boost score:    {np.mean(boost_scores):.3f} moy | "
                       f"{np.min(boost_scores):.3f}-{np.max(boost_scores):.3f}")

        # Performance des DT/DB
        df_all['_r10'] = df_all['price'].shift(-10) - df_all['price']
        for i, r in enumerate(results):
            if r and r.is_active() and i < len(df_all):
                df_all.loc[df_all.index[i], '_dt_dir'] = r.boost_direction
                df_all.loc[df_all.index[i], '_dt_score'] = r.boost_score

        dt_mask = df_all.get('_dt_dir', pd.Series(0, index=df_all.index))
        for label, mask, edir in [
            ("DT (short)", dt_mask < 0, -1),
            ("DB (long)",  dt_mask > 0, 1),
        ]:
            sel = df_all[mask]
            fut = sel['_r10'].dropna()
            if len(fut) >= 3:
                wr = ((fut * edir) > 0).sum() / len(fut) * 100
                star = "⭐" if wr >= 55 else ""
                out.append(f"    {label:15s}: {len(fut):>4d} sig | "
                           f"WR={wr:>5.1f}% | avg={fut.mean():>+7.2f}t {star}")
            else:
                out.append(f"    {label:15s}: <3 sig")

        # Qualité
        for q_name in ['STRONG', 'MODERATE', 'WEAK']:
            q_list = [r for r in active if r.quality and r.quality.name == q_name]
            if q_list:
                out.append(f"    Qualité {q_name:10s}: {len(q_list):>4d}")

    out.append("")


# ═════════════════════════════════════════════════════════════════════
# MAIN — runner
# ═════════════════════════════════════════════════════════════════════

def main():
    t_start = time.perf_counter()

    # Accepter un ou plusieurs dossiers
    paths = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    paths = [p for p in paths if not p.startswith("-")]  # Ignorer les flags
    files = {}
    for base in paths:
        found = discover_files(base)
        for date, syms in found.items():
            if date not in files:
                files[date] = {}
            files[date].update(syms)
    base = paths[0]

    if not files:
        print(f"❌ Aucun fichier YYYYMMDD_SYM.jsonl trouvé dans {base}")
        print(f"   Attendu: 20260305_NQ.jsonl, 20260305_ES.jsonl, ...")
        sys.exit(1)

    out = []
    out.append("╔══════════════════════════════════════════════════════════════════╗")
    out.append("║              MIA BENCH — RAPPORT AUTOMATIQUE                   ║")
    out.append(f"║  {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^62s}  ║")
    out.append(f"║  Schema {SCHEMA_VERSION} — {EXPECTED_SCHEMA_COLS} colonnes{' ' * 42}║")
    out.append("╚══════════════════════════════════════════════════════════════════╝")
    out.append("")

    # Discovery
    out.append(f"  Fichiers trouvés dans {os.path.abspath(base)}:")
    for date, syms in sorted(files.items()):
        syms_str = ", ".join(f"{s}={os.path.basename(p)}" for s, p in sorted(syms.items()))
        out.append(f"    {date}: {syms_str}")
    out.append("")

    # Build pipeline
    print("Building pipeline...", end=" ", flush=True)
    data = build_pipeline(files)
    print("OK")

    # Run tests
    print("Test 1: Fonctionnel...", end=" ", flush=True)
    test_functional(data, out)
    print("OK")

    print("Test 2: Inventaire...", end=" ", flush=True)
    test_inventory(data, out)
    print("OK")

    print("Test 3: Ranking bootstrap...", end=" ", flush=True)
    results, nq_all = test_ranking(data, out)
    print("OK")

    print("Test 4: Cross-asset...", end=" ", flush=True)
    test_cross_asset(data, results, out)
    print("OK")

    print("Test 5: Par régime...", end=" ", flush=True)
    test_regime(data, results, out)
    print("OK")

    print("Test 6: Seuils...", end=" ", flush=True)
    test_thresholds(nq_all, out)
    print("OK")

    print("Test 7: Game changers...", end=" ", flush=True)
    test_game_changers(data, out)
    print("OK")

    print("Test 8: Verdict...", end=" ", flush=True)
    test_verdict(results, data, out)
    print("OK")

    print("Test 9: Signal vs Bruit...", end=" ", flush=True)
    sig_features = test_signal_bruit(nq_all, data, out)
    print("OK")

    print("Test 10: Noyau dur backtest...", end=" ", flush=True)
    test_noyau_dur(nq_all, data, out)
    print("OK")

    print("Test 11: Wall tracker...", end=" ", flush=True)
    test_wall_tracker(data, out)
    print("OK")

    print("Test 12: Session timing...", end=" ", flush=True)
    # Enrich nq_all with entry + sltp columns for timing analysis
    try:
        from mia_entry import EntryEngine
        from mia_sltp import SLTPEngine
        _entry = EntryEngine()
        _sltp = SLTPEngine(symbol="NQ")
        _nq_timing = _entry.compute(nq_all.copy())
        _nq_timing = _sltp.compute(_nq_timing)
        test_session_timing(_nq_timing, data, out)
    except Exception as e:
        out.append(f"  Test 12 erreur: {e}")
    print("OK")

    print("Test 13: DMP Health Check...", end=" ", flush=True)
    test_dmp_health(data, out)
    print("OK")

    print("Test 14: RVOL Validation...", end=" ", flush=True)
    test_rvol_validation(data, out)
    print("OK")

    print("Test 15: Session IB & Transitions...", end=" ", flush=True)
    test_session_ib(data, out)
    print("OK")

    print("Test 16: PREV Level Returns...", end=" ", flush=True)
    test_prev_returns(data, out)
    print("OK")

    print("Test 17: Market Profile Avancé...", end=" ", flush=True)
    test_market_profile_advanced(data, out)
    print("OK")

    print("Test 18: AMD (Power of 3)...", end=" ", flush=True)
    try:
        test_amd(data, out)
    except Exception as e:
        out.append(f"  Test 18 erreur: {e}")
    print("OK")

    print("Test 19: Double Top/Bottom...", end=" ", flush=True)
    try:
        test_double_top(data, out)
    except Exception as e:
        out.append(f"  Test 19 erreur: {e}")
    print("OK")

    elapsed = time.perf_counter() - t_start
    out.append(f"  Temps total: {elapsed:.1f}s")

    # Output
    report = "\n".join(out)
    print()
    print(report)

    report_path = os.path.join(base, REPORT_FILE)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    # Copie datee (jamais ecrasee)
    dated_path = os.path.join(base, REPORT_FILE_DATED)
    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  Rapport sauvegardé: {report_path}")
    print(f"  Rapport daté: {dated_path}")


if __name__ == "__main__":
    main()
