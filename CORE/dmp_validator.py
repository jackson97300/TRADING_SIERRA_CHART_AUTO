#!/usr/bin/env python3
"""
dmp_validator.py — Validateur quotidien DMP Schema 3.7.x
=========================================================
Détecte les bugs AVANT d'accumuler 3 semaines de données mortes.

Usage:
    python dmp_validator.py 20260310_NQ.jsonl
    python dmp_validator.py 20260310_NQ.jsonl 20260310_ES.jsonl
    python dmp_validator.py *.jsonl

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\dmp_validator.py
Date: 2026-03-10
Schema: 3.7.x — 258/260/262/266/267 colonnes (3.7.0/3.7.1/3.7.2/3.7.3/3.7.9)
"""

import json, sys, os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from collections import Counter

# Import local (meme dossier)
sys.path.insert(0, str(Path(__file__).parent))
import validator_baseline as vb  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════════
# VERSIONING
# ═══════════════════════════════════════════════════════════════════════════════

VALIDATOR_VERSION = "2.0"
# V2.0 (20/04/2026) : ajout 5 checks critiques + baseline rolling + enum domain
# V1.1 (20/04/2026) : fix session==2 (bug Claude) + seuils tiered + IB null RTH
# V1.0 : validator historique (MUST_FIRE 15%, BOUNDS, coherence logique)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION V2 — Nouveaux checks critiques (Plan agent 20/04 GO-AVEC-MODIFS)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationRule:
    """Regle de validation typee pour architecture modulaire V2.
    Registre minimal pour les 5 nouveaux checks. Les 50+ checks existants
    restent en forme procedurale (migration progressive S2-S5 si besoin)."""
    name: str
    kind: str          # "outlier" | "saturation" | "tiered" | "enum" | "regression"
    severity: str      # "error" | "warning"
    params: dict = field(default_factory=dict)

# CHECK 1 — OUTLIER EXPLOSION (trou majeur quality-auditor R3)
# max(|x|) / p99(|x|) > 100 = explosion (division par zero C++, bug unit scale)
# quality-auditor R2 20/04 : ajout dist_cluster_* schema 3.7.3
OUTLIER_FEATURES = [
    "dist_swing_high", "dist_swing_low", "swing_range_ticks",
    "dist_vwap_d", "dist_vwap_w", "dist_vwap_m",
    "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val",
    "dist_prev_vpoc", "dist_prev_vwap",
    "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
    "delta_bar", "delta_day", "cvd_day",
    "momentum_3b", "momentum_5b", "total_vol",
    # Schema 3.7.3 additions (ajout quality-auditor R2 20/04)
    "dist_cluster_nearest_up", "dist_cluster_nearest_dn",
]
OUTLIER_RATIO_THRESHOLD = 100.0

# CHECK 2 — SATURATION CEILING (retour bug bar_color_up pre-17/04)
# Features bool qui ne doivent JAMAIS saturer >95% (sinon bug arr[sz-1] ou Extension Line)
SATURATION_FEATURES = [
    "bar_color_up", "bar_color_dn",
    "bar_long_up_bar", "bar_long_dn_bar",
    "bar_long_dn_up", "bar_long_up_dn",
    "bar_edge_buy", "bar_edge_sell",
    "bn_color_up", "bn_color_dn",
    "bn_color_up_2", "bn_color_dn_2",
    "bn_absorb_ask", "bn_absorb_bid",
    "bn_long_up", "bn_long_dn",
    "bn_volume_up", "bn_volume_dn",
    "fp_edge_buy", "fp_edge_sell",
    "delta_divergence",
]
SATURATION_CEILING = 0.95  # fire_rate > 95% = bug

# CHECK 3 — SEUIL TIERED ES/NQ (remplace MUST_FIRE global laxiste)
# Baseline 17/04 data propre complete :
#   ES bar_pressure_ask 0.15%, NQ bar_pressure_ask 4.1%
# Seuils tiered par instrument pour detecter regression legere.
TIERED_THRESHOLDS = {
    "ES": {
        "bn_pressure_bid":  0.001,  # 0.1% (baseline 0.3%)
        "bar_pressure_ask": 0.001,  # 0.1% (baseline 0.15%)
        "bar_pressure_bid": 0.001,  # 0.1% (baseline 0.4%)
    },
    "NQ": {
        "bn_pressure_bid":  0.01,   # 1% (baseline 3.8%)
        "bar_pressure_ask": 0.01,   # 1% (baseline 4.1%)
        "bar_pressure_bid": 0.01,   # 1% (baseline 3.8%)
    },
}
TIERED_MIN_BARS = 200  # skip tiered sur echantillon trop petit

# CHECK 4 — ENUM DOMAIN (couvre bug Claude session==3)
# Colonnes categorielles : valeurs autorisees strictes
ENUM_DOMAINS = {
    "session":    {0, 1, 2},                  # DMP_Main.cpp:798
    "session_id": {"Asia", "London", "US"},
    "sym":        {"ES", "NQ"},
    "vwap_d_side":    {-1, 0, 1},
    "vwap_w_side":    {-1, 0, 1},
    "vwap_m_side":    {-1, 0, 1},
    "cvd_day_dir":    {-1, 0, 1},
    "delta_day_dir":  {-1, 0, 1},
    "vwap_slope_10_dir": {-1, 0, 1},
    "ma_trend":       {-1, 0, 1},
    "next_wall_is_call": {0, 1, None},        # None hors US
}

# CHECK 5 — REGRESSION PARTIELLE via baseline rolling
# Utilise CORE/validator_baseline.py + DATA/BASELINE/baseline.json
# Features tracked par baseline (les plus critiques)
# quality-auditor R1 20/04 : ajout bn_pressure_*, bar_pressure_* pour fermer
# le trou "regression graduelle 4%->1.5% reste GREEN car seuil tiered 1%"
BASELINE_TRACKED_FEATURES = (
    SATURATION_FEATURES  # tous les evenements bool
    + ["rvol_absorb_buy", "rvol_absorb_sell",
       "big_ask_cluster_20t", "big_bid_cluster_20t",
       "big_ask_cluster_50t", "big_bid_cluster_50t",
       # Tiered features (quality-auditor R1 20/04)
       "bn_pressure_bid", "bn_pressure_ask",
       "bar_pressure_bid", "bar_pressure_ask"]
)

# Registre declaratif des 5 regles V2 (pour traceabilite + docs)
V2_RULES = [
    ValidationRule("outlier_explosion",    "outlier",    "error",
                   {"features": OUTLIER_FEATURES, "ratio": OUTLIER_RATIO_THRESHOLD}),
    ValidationRule("saturation_ceiling",   "saturation", "error",
                   {"features": SATURATION_FEATURES, "ceiling": SATURATION_CEILING}),
    ValidationRule("tiered_fire_rate",     "tiered",     "error",
                   {"thresholds": TIERED_THRESHOLDS, "min_bars": TIERED_MIN_BARS}),
    ValidationRule("enum_domain",          "enum",       "error",
                   {"domains": ENUM_DOMAINS}),
    ValidationRule("regression_partielle", "regression", "warning",
                   {"features": BASELINE_TRACKED_FEATURES,
                    "ratio": vb.REGRESSION_RATIO}),
]

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — Schema 3.7.0
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA_VERSION = "3.7.x"          # accepte 3.7.0 / 3.7.1 / 3.7.2 / 3.7.3 / 3.7.9
EXPECTED_COLS_370 = 258           # schema historique
EXPECTED_COLS_371 = 260           # +bar_high, +bar_low
EXPECTED_COLS_372 = 262           # +dist_vwap_d_sd3u, +dist_vwap_d_sd3d
EXPECTED_COLS_373 = 266           # +dist_cluster_nearest_up/dn, +n_clusters_20t/50t
EXPECTED_COLS_379 = 267           # +dist_mq_hvl_0dte (24/04/2026 cas niveaux distincts)
EXPECTED_COLS_3714 = 268          # +atr_14m (24/04/2026 soir - ATR intraday fix VolatilitySpikeGate)
EXPECTED_COLS_3715 = 272          # +4 G6C T&S aggregates (06/06/2026 migration full Sierra)
                                  #  max_ask_vol_in_bar, max_bid_vol_in_bar,
                                  #  p99_trade_size_proxy, large_trader_max_size
                                  # NB : Annonce anterieure "271 MenthorQ update" jamais deployee, override.
EXPECTED_COLS = EXPECTED_COLS_370 # rétrocompatibilité (remplacé dynamiquement)

# ─── NETTOYAGE 2026-04-12 ────────────────────────────────────────────────
# Colonnes mortes documentees dans CLAUDE.md (audit 2026-04-09) retirees des
# checks MUST_FIRE/SHOULD_FIRE/MUST_HAVE_DIST/MUST_VARY/BOUNDS :
#   - bn_color_up, bn_color_dn, bn_color_dn_2  → toujours 0 (BN Trigger per-bar ephemere)
#   - bar_color_up, bar_color_dn              → Extension to Future Intersection desactivee
#   - bn_pressure_ask                         → toujours 0 (mort post-3.7.0)
#   - bn_long_up, bn_long_dn                  → idem
#   - bn_volume_up, bn_volume_dn              → idem
#   - bn_score_bull                           → idem (bn_score_bear/raw survivent)
#   - dist_ext_color_up, dist_ext_color_dn    → API CBBAC non alimentee
# Survivants explicites gardes : bn_color_up_2 (+0.070 ES), bn_score_bear, bn_score_raw,
# bn_absorb_bid, bn_absorb_ask, bn_pressure_bid, fp_edge_*, bar_edge_*, bar_long_*.
# Ces colonnes mortes restent presentes dans le JSONL (DMP C++ les ecrit toujours),
# mais le validateur ne leve plus de faux positifs a leur sujet.

# Signaux qui DOIVENT firer (Extension Lines persistantes, toujours actives)
# (colonne, seuil_min_pct, description)
# Baseline 17/04 data propre journee complete : ES 0.15-0.4%, NQ 3.8-4.7%
# Seuil 0.05% : au-dessus de ES bar_pressure_ask 0.15% (2/1378), detecte vraie mort
# TODO [R2 code-reviewer 20/04]: seuil actuel detecte 0% mais manque regression partielle
# (ex: NQ 4%->0.1% reste GREEN). Evoluer vers seuil tiered (WARN <50% baseline)
# ou seuil par symbole (ES 0.001, NQ 0.01) en S1 semaine QA.
MUST_FIRE = [
    ("bn_pressure_bid",  0.0005, "TRIPLE/DOUBLE BID FP"),
    ("bar_pressure_ask", 0.0005, "TRIPLE/DOUBLE ASK BARRES"),
    ("bar_pressure_bid", 0.0005, "TRIPLE/DOUBLE BID BARRES"),
]

# Signaux qui DEVRAIENT firer (au moins 1 fois sur 50+ barres)
SHOULD_FIRE = [
    ("bn_color_up_2",    "COLOR UP 2 — double stacké (continuation)"),
    ("bar_edge_buy",     "EDGE BUY BARRES — imbalance acheteur"),
    ("bar_edge_sell",    "EDGE SELL BARRES — imbalance vendeur"),
    ("fp_edge_buy",      "EDGE BUY FP — imbalance footprint"),
    ("fp_edge_sell",     "EDGE SELL FP — imbalance footprint"),
    ("bar_long_up_bar",  "LONG UP BAR BARRES"),
    ("bar_long_dn_bar",  "LONG DN BAR BARRES"),
]

# Distances qui doivent être non-null régulièrement
MUST_HAVE_DIST = [
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
    ("bn_score_bear",    2, "Score BN bear"),
]

# Colonnes avec bornes logiques
BOUNDS = [
    ("price",             1000,  50000),
    ("atr",               10,    5000),
    ("range_pos",         0,     100.01),
    # FIX 2026-04-16 : va_position_pct est maintenant [0, 1] ou null hors range
    # (ancien sentinel -1 corrige dans DMP_Transform.h:531 PosInRange).
    # Bornes strictes [0, 1.01] au lieu de [-5, 5] laxiste.
    ("va_position_pct",   0,     1.01),
    # FIX 2026-04-16 : ib_position_pct meme convention que va_position_pct.
    # Bornes strictes pour detecter toute regression future (reintroduction du
    # sentinel -1, ou passage accidentel en echelle [0, 100] via ib_recalc.py).
    ("ib_position_pct",   0,     1.01),
    ("ask_pct",           0,     1.01),
    ("bid_pct",           0,     1.01),
    ("delta_bar_vol_norm",-1.01, 1.01),
    ("bn_score_raw",      -1.5,  1.5),
    ("bn_score_bear",     0,     1.5),
]

# Signaux US-only (0 attendu en London/Asia, warning seulement si 0 en US)
US_ONLY_SIGNALS = [
    "delta_divergence",
    "n_big_ask_t1", "n_big_bid_t1",
    "n_big_ask_t2", "n_big_bid_t2",
    "n_big_ask_t3", "n_big_bid_t3",
]


def load_jsonl(path):
    """Charge JSONL avec gestion robuste lignes malformees.

    R3 code-reviewer 20/04 : loguer les lignes malformees et continuer avec les valides.
    Si > 10% des lignes sont malformees, lever exception (fichier probablement corrompu).
    """
    valid_lines = []
    malformed = 0
    with open(path, encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                valid_lines.append(json.loads(raw))
            except json.JSONDecodeError as e:
                malformed += 1
                if malformed <= 3:  # loguer les 3 premieres, eviter spam
                    print(f"  ⚠ Ligne {i} malformee: {e} (skip)")
    if malformed > 0:
        total = len(valid_lines) + malformed
        ratio = malformed / total if total > 0 else 1.0
        print(f"  ⚠ {malformed}/{total} lignes malformees ({ratio:.1%})")
        if ratio > 0.1:
            raise ValueError(
                f"Fichier {path.name if hasattr(path, 'name') else path} : "
                f"{ratio:.1%} lignes malformees (> 10% = fichier corrompu)")
    return valid_lines


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
    # Détection automatique du schema selon le nombre de colonnes
    has_bar_hl  = ("bar_high" in lines[0]) and ("bar_low" in lines[0])
    has_vwap_sd3 = ("dist_vwap_d_sd3u" in lines[0]) and ("dist_vwap_d_sd3d" in lines[0])
    has_cluster_vol = ("dist_cluster_nearest_up" in lines[0]) and ("n_clusters_20t" in lines[0])
    has_hvl_0dte = "dist_mq_hvl_0dte" in lines[0]  # 3.7.9 (24/04)
    has_atr_14m = "atr_14m" in lines[0]            # 3.7.14 (24/04 soir)
    has_ts_aggregates = "max_ask_vol_in_bar" in lines[0]  # 3.7.15 (06/06 migration Sierra)
    if ncols == EXPECTED_COLS_3715 and has_bar_hl and has_vwap_sd3 and has_cluster_vol and has_hvl_0dte and has_atr_14m and has_ts_aggregates:
        detected_schema = "3.7.15"
        expected = EXPECTED_COLS_3715
    elif ncols == EXPECTED_COLS_3714 and has_bar_hl and has_vwap_sd3 and has_cluster_vol and has_hvl_0dte and has_atr_14m:
        detected_schema = "3.7.14"
        expected = EXPECTED_COLS_3714
    elif ncols == EXPECTED_COLS_379 and has_bar_hl and has_vwap_sd3 and has_cluster_vol and has_hvl_0dte:
        detected_schema = "3.7.9"
        expected = EXPECTED_COLS_379
    elif ncols == EXPECTED_COLS_373 and has_bar_hl and has_vwap_sd3 and has_cluster_vol:
        detected_schema = "3.7.3"
        expected = EXPECTED_COLS_373
    elif ncols == EXPECTED_COLS_372 and has_bar_hl and has_vwap_sd3:
        detected_schema = "3.7.2"
        expected = EXPECTED_COLS_372
    elif ncols == EXPECTED_COLS_371 and has_bar_hl and not has_vwap_sd3:
        detected_schema = "3.7.1"
        expected = EXPECTED_COLS_371
    elif ncols == EXPECTED_COLS_370 and not has_bar_hl:
        detected_schema = "3.7.0"
        expected = EXPECTED_COLS_370
    else:
        detected_schema = "INCONNU"
        expected = ncols  # éviter faux positif, on signale quand même

    if ncols not in (EXPECTED_COLS_370, EXPECTED_COLS_371, EXPECTED_COLS_372,
                     EXPECTED_COLS_373, EXPECTED_COLS_379, EXPECTED_COLS_3714,
                     EXPECTED_COLS_3715):
        errors.append(f"SCHEMA: {ncols} colonnes (attendu 258, 260, 262, 266, 267, 268 ou 272)")
    else:
        ok += 1
    print(f"  Schema detecte : {detected_schema}  ({ncols} colonnes)")
    
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
    # Seuil min 200 barres : signaux rares (baseline 0.1-4.7%) non-evaluables sur
    # echantillon trop petit (32 barres Asia = 1 fire attendu = bruit statistique)
    # TODO [R3 code-reviewer 20/04]: si n<200 ET has_rth, emettre warning explicite
    # au resume final (pas juste print noye) pour flagger jours feries / coupures RTH.
    print("  ── Signaux persistants (doivent firer) ──")
    for col, min_pct, desc in MUST_FIRE:
        vals = [l.get(col, 0) for l in lines]
        nz = sum(1 for v in vals if v and v != 0)
        pct = nz / n if n > 0 else 0
        if n < 200:
            print(f"  · {col:25s} {nz:>3d}/{n} ({pct:>5.2%}) — n<200, eval skip")
        elif pct < min_pct:
            errors.append(f"{col}: {nz}/{n} ({pct:.2%}) < {min_pct:.1%} — {desc}")
            print(f"  ❌ {col:25s} {nz:>3d}/{n} ({pct:>5.2%}) — MORT")
        else:
            ok += 1
            print(f"  ✅ {col:25s} {nz:>3d}/{n} ({pct:>5.2%})")

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
        
        # FIX 2026-04-16 : apres fix PosInRange -1 -> null, va_position_pct vaut :
        #   - dans [0, 1] quand prix dans VA (inside_cur_va = 1)
        #   - null (None en Python) quand hors VA (inside_cur_va = 0)
        # Ancien comportement : -1 hors VA (sentinel chiffre polluant le ML).
        iva = l.get('inside_cur_va', 0)
        vap = l.get('va_position_pct', None)
        if vap is None:
            # Nouveau format : hors VA -> null coherent avec iva=0
            if iva == 0:
                checks["inside_va↔va_pct"] += 1
        else:
            # Ancien format retro-compat (JSONL pre-16/04) OU nouveau format valide
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
                     'dist_big_bid_nearest_up', 'dist_big_bid_nearest_dn',
                     # ✅ 27/03/2026 — VIX MenthorQ architecture normale
                     # MenthorQ fusionne "Put Support & Put Support 0DTE" → sg1
                     # sg6 (Put Support 0DTE séparé) = 0.0 → guard invalide → null systématique
                     # Identique à dist_mq_put_0dte ES (même architecture MenthorQ)
                     'dist_vix_put_0dte'}

    # Features IB : non-null seulement en RTH. Si fichier ne contient aucune barre RTH
    # (Asia/London only), dist_ib_* null = OK (IB etabli a partir de 09:30 ET).
    # Convention DMP C++ (DMP_Main.cpp:798) : session=0 Asia, 1 London, 2 US/RTH
    has_rth = any(l.get('session') == 2 for l in lines)
    if not has_rth:
        expected_null |= {'dist_ib_high', 'dist_ib_low',
                          'ib_range_atr', 'ib_position_pct'}
    
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
                       'high_pullback_delta','low_pullback_delta',
                       # ✅ 27/03/2026 — Zéros normaux documentés
                       # vix_above_hvl_0dte = 0 quand dist_vix_hvl_0dte null (normal)
                       'vix_above_hvl_0dte',
                       # trend_day_probability = 0 valeur valide (pas de setup Trend Day)
                       'trend_day_probability',
                       # ib_range_ticks/narrow/wide peuvent être 0 en Asia (IB pas encore formée)
                       'ib_range_ticks','ib_is_narrow','ib_is_wide')]
    
    if unexpected_zero and has_us:
        for c in unexpected_zero[:5]:
            warnings.append(f"COLONNE TOUT ZÉRO (US): {c}")
        if unexpected_zero:
            print(f"  ⚠️ Tout zéro inattendu: {', '.join(unexpected_zero[:5])}")
    
    alive = ncols - len(all_null) - len(all_zero)
    print(f"  Vivantes: {alive} | Null: {len(all_null)} | Zéro: {len(all_zero)}")

    # ─── G15. BAR OHLC (schema 3.7.1 uniquement) ─────────────────────────
    if detected_schema == "3.7.1":
        print(f"\n  ── Bar OHLC — schema 3.7.1 ──")
        bh_vals = [l.get("bar_high") for l in lines]
        bl_vals = [l.get("bar_low")  for l in lines]
        p_vals  = [l.get("price")    for l in lines]
        a_vals  = [l.get("atr")      for l in lines]

        # Nulls
        null_h = sum(1 for v in bh_vals if v is None)
        null_l = sum(1 for v in bl_vals if v is None)
        if null_h > 0 or null_l > 0:
            errors.append(f"BAR_OHLC: {null_h} bar_high null, {null_l} bar_low null")
            print(f"  ❌ bar_high nulls={null_h}  bar_low nulls={null_l}")
        else:
            ok += 1
            print(f"  ✅ bar_high/bar_low — aucun null ({n} barres)")

        # Cohérence bar_low <= price <= bar_high
        viol_order = sum(
            1 for h, l, p in zip(bh_vals, bl_vals, p_vals)
            if h is not None and l is not None and p is not None
            and not (l <= p <= h)
        )
        if viol_order > 0:
            errors.append(f"BAR_OHLC: {viol_order} violations bar_low <= price <= bar_high")
            print(f"  ❌ Violations bar_low <= price <= bar_high : {viol_order}")
        else:
            ok += 1
            print(f"  ✅ bar_low <= price <= bar_high — 0 violation")

        # Range positif bar_high - bar_low > 0
        zero_range = sum(
            1 for h, l in zip(bh_vals, bl_vals)
            if h is not None and l is not None and h - l <= 0
        )
        if zero_range > 0:
            errors.append(f"BAR_OHLC: {zero_range} barres avec range <= 0")
            print(f"  ❌ Range <= 0 : {zero_range} barres")
        else:
            ok += 1
            ranges = [h - l for h, l in zip(bh_vals, bl_vals) if h is not None and l is not None]
            print(f"  ✅ Range > 0 — min={min(ranges):.2f} moy={sum(ranges)/len(ranges):.2f} max={max(ranges):.2f} pts")

        # Range aberrant bar_high - bar_low < atr * 5
        aberrant = sum(
            1 for h, l, a in zip(bh_vals, bl_vals, a_vals)
            if h is not None and l is not None and a is not None and a > 0
            and (h - l) > a * 5
        )
        if aberrant > 0:
            errors.append(f"BAR_OHLC: {aberrant} barres avec range > 5*ATR (aberrant)")
            print(f"  ❌ Range > 5*ATR : {aberrant} barres")
        else:
            ok += 1
            print(f"  ✅ Range < 5*ATR — aucune barre aberrante")
    else:
        print(f"\n  ── Bar OHLC — schema {detected_schema} : checks OHLC ignores (non applicable) ──")

    # ─── G16. VWAP SD3 (schema 3.7.2 uniquement) ─────────────────────────
    if detected_schema == "3.7.2":
        print(f"\n  ── VWAP SD3 — schema 3.7.2 ──")
        sd3u_vals = [l.get("dist_vwap_d_sd3u") for l in lines]
        sd3d_vals = [l.get("dist_vwap_d_sd3d") for l in lines]

        null_u = sum(1 for v in sd3u_vals if v is None)
        null_d = sum(1 for v in sd3d_vals if v is None)
        # SD3 peut être null en dehors RTH (avant formation du VWAP) → acceptable
        null_pct_u = null_u / n * 100
        null_pct_d = null_d / n * 100
        if null_pct_u > 80 or null_pct_d > 80:
            errors.append(f"VWAP_SD3: >80% nulls (u={null_pct_u:.0f}% d={null_pct_d:.0f}%)")
            print(f"  ❌ dist_vwap_d_sd3u/sd3d trop de nulls : {null_pct_u:.0f}% / {null_pct_d:.0f}%")
        else:
            ok += 1
            print(f"  ✅ dist_vwap_d_sd3u/sd3d présents — nulls={null_pct_u:.0f}%/{null_pct_d:.0f}%")

        # Cohérence : SD3 doit être > SD2 (en valeur absolue)
        sd2u_vals = [l.get("dist_vwap_d_sd2u") for l in lines]
        sd2d_vals = [l.get("dist_vwap_d_sd2d") for l in lines]
        viol_order = sum(
            1 for u3, u2 in zip(sd3u_vals, sd2u_vals)
            if u3 is not None and u2 is not None and u3 < u2
        )
        if viol_order > 0:
            errors.append(f"VWAP_SD3: {viol_order} violations SD3u < SD2u")
            print(f"  ❌ SD3u < SD2u sur {viol_order} barres")
        else:
            ok += 1
            print(f"  ✅ SD3u > SD2u — cohérence bandes respectée")

    # ─── G17. IB RANGE — detection bug sc.High footprint ────────────
    # Le DMP C++ peut retourner dist_ib_high=INVALID quand sc.High
    # ne fonctionne pas sur les charts footprint. ib_recalc.py corrige
    # en Python mais on detecte le probleme ici pour alerter.
    if has_us:
        print(f"\n  -- IB Range -- detection bug footprint --")
        us_lines = [l for l in lines if l.get("session_id") == "US"]
        n_us = len(us_lines)

        if n_us >= 30:
            # Barres US apres 10h30 ET (IB devrait etre formee)
            us_after_ib = []
            for l in us_lines:
                ts_s = l.get("ts", 0) / 1000.0
                h_utc = int((ts_s % 86400) / 3600)
                mo = 3  # mars 2026 approximation
                off = 4 if mo >= 3 else 5  # EDT
                h_et = (h_utc - off + 24) % 24
                m_et = int(((ts_s % 86400) % 3600) / 60)
                t_et = h_et * 60 + m_et
                if t_et > 10 * 60 + 30:
                    us_after_ib.append(l)

            n_after = len(us_after_ib)
            if n_after >= 10:
                ib_h_null = sum(1 for l in us_after_ib if l.get("dist_ib_high") is None)
                ib_r_zero = sum(1 for l in us_after_ib
                               if l.get("ib_range_ticks") is not None
                               and l.get("ib_range_ticks") == 0)

                # Check 1: dist_ib_high ne devrait pas etre null apres 10h30
                if ib_h_null > n_after * 0.5:
                    warnings.append(f"IB_HIGH NULL: {ib_h_null}/{n_after} barres US apres 10h30 "
                                    f"— ib_recalc.py corrigera en post-processing")
                    print(f"  !! IB HIGH NULL: {ib_h_null}/{n_after} barres US apres 10h30")
                    print(f"     Cause probable: sc.High footprint bug")
                    print(f"     Fix: ib_recalc.py dans DatasetBuilder (auto)")
                else:
                    ok += 1
                    print(f"  OK dist_ib_high: {n_after - ib_h_null}/{n_after} valides apres 10h30")

                # Check 2: ib_range ne devrait pas etre 0 apres 10h30
                if ib_r_zero > n_after * 0.5:
                    warnings.append(f"IB_RANGE=0: {ib_r_zero}/{n_after} barres US apres 10h30")
                    print(f"  !! IB RANGE=0: {ib_r_zero}/{n_after} barres apres 10h30")
                else:
                    ok += 1
                    valid_ranges = [l.get("ib_range_ticks", 0) for l in us_after_ib
                                   if l.get("ib_range_ticks") is not None
                                   and l.get("ib_range_ticks") > 0]
                    if valid_ranges:
                        print(f"  OK ib_range: {valid_ranges[0]:.0f}t (fige)")
                    else:
                        print(f"  OK ib_range: pas de barres apres IB pour verifier")
            else:
                print(f"  -- IB: seulement {n_after} barres apres 10h30 — skip")
        else:
            print(f"  -- IB: seulement {n_us} barres US — skip")

    # ═══════════════════════════════════════════════════════════════════
    # V2 CHECKS — 5 checks critiques (Plan agent 20/04 GO-AVEC-MODIFICATIONS)
    # ═══════════════════════════════════════════════════════════════════

    # ─── 11. ENUM DOMAIN — couvre bug Claude session==3 ──────────────────
    print(f"\n  ── V2.11 Enum domain (valeurs categorielles) ──")
    enum_violations = 0
    for col, allowed in ENUM_DOMAINS.items():
        vals = [l.get(col) for l in lines]
        bad = [v for v in vals if v not in allowed]
        if bad:
            enum_violations += 1
            unique_bad = sorted(set(str(b) for b in bad))[:3]
            errors.append(f"ENUM {col}: {len(bad)}/{n} valeurs hors {allowed} ({unique_bad})")
            print(f"  ❌ {col:20s} {len(bad)}/{n} hors domaine (ex: {unique_bad})")
        else:
            ok += 1
    if enum_violations == 0:
        print(f"  ✅ 11/11 colonnes enum dans leur domaine")

    # ─── 12. SATURATION CEILING — retour bug bar_color_up pre-17/04 ─────
    print(f"\n  ── V2.12 Saturation ceiling (bool fire_rate > 95% = bug) ──")
    sat_violations = 0
    for col in SATURATION_FEATURES:
        vals = [l.get(col, 0) for l in lines]
        nz = sum(1 for v in vals if v and v != 0)
        if n > 0 and nz / n > SATURATION_CEILING:
            sat_violations += 1
            errors.append(f"SATURATION {col}: {nz}/{n} ({nz/n:.1%}) > {SATURATION_CEILING:.0%}")
            print(f"  ❌ {col:25s} {nz:>4d}/{n} ({nz/n:>5.1%}) — SATURE")
        else:
            ok += 1
    if sat_violations == 0:
        print(f"  ✅ {len(SATURATION_FEATURES)}/{len(SATURATION_FEATURES)} features bool sous le ceiling 95%")

    # ─── 13. OUTLIER EXPLOSION — max/p99 > 100 ──────────────────────────
    print(f"\n  ── V2.13 Outlier explosion (max/p99 > 100) ──")
    outlier_violations = 0
    for col in OUTLIER_FEATURES:
        vals = [abs(l[col]) for l in lines
                if l.get(col) is not None and isinstance(l.get(col), (int, float))
                and not (isinstance(l.get(col), float) and (l[col] != l[col]))]  # skip NaN
        if len(vals) < 10:
            continue  # insuffisant
        sorted_vals = sorted(vals)
        p99_idx = max(0, int(len(sorted_vals) * 0.99) - 1)
        p99 = sorted_vals[p99_idx]
        mx = max(sorted_vals)
        if p99 > 0 and mx / p99 > OUTLIER_RATIO_THRESHOLD:
            outlier_violations += 1
            errors.append(f"OUTLIER {col}: max={mx:.1f} / p99={p99:.1f} ratio={mx/p99:.0f}")
            print(f"  ❌ {col:25s} max={mx:>10.1f} / p99={p99:>8.1f} = {mx/p99:>6.0f}x")
        else:
            ok += 1
    if outlier_violations == 0:
        print(f"  ✅ {len(OUTLIER_FEATURES)}/{len(OUTLIER_FEATURES)} features sous ratio {OUTLIER_RATIO_THRESHOLD}x")

    # ─── 14. TIERED FIRE RATE ES/NQ ─────────────────────────────────────
    print(f"\n  ── V2.14 Tiered fire rate (seuil par symbole) ──")
    tiered_thresholds = TIERED_THRESHOLDS.get(sym, {})
    if not tiered_thresholds:
        print(f"  · sym={sym} pas de tiered config")
    elif n < TIERED_MIN_BARS:
        # Warning HARD au lieu de skip silencieux (couvre TODO R3)
        warnings.append(f"TIERED: {n} barres < {TIERED_MIN_BARS} — fire rate eval skip ({sym})")
        print(f"  ⚠️  n={n} < {TIERED_MIN_BARS} : skip avec warning HARD (signal rare non-evaluable)")
    else:
        for col, min_pct in tiered_thresholds.items():
            vals = [l.get(col, 0) for l in lines]
            nz = sum(1 for v in vals if v and v != 0)
            pct = nz / n
            if pct < min_pct:
                errors.append(f"TIERED {sym}.{col}: {nz}/{n} ({pct:.3%}) < {min_pct:.2%}")
                print(f"  ❌ {col:25s} {nz:>4d}/{n} ({pct:>6.3%}) < {min_pct:.2%} ({sym})")
            else:
                ok += 1
                print(f"  ✅ {col:25s} {nz:>4d}/{n} ({pct:>6.3%}) >= {min_pct:.2%} ({sym})")

    # ─── 15. REGRESSION PARTIELLE via baseline rolling ──────────────────
    print(f"\n  ── V2.15 Regression vs baseline rolling 7j ──")
    baseline_path = vb.default_baseline_path()
    baseline = vb.load_baseline(baseline_path)
    fire_rates = vb.compute_fire_rates(lines, BASELINE_TRACKED_FEATURES)
    reg_violations = 0
    reg_checks_done = 0
    for sess_name, feat_rates in fire_rates.items():
        for feat, rate in feat_rates.items():
            result = vb.check_regression(baseline, sym, sess_name, feat, rate)
            if result.is_regression:
                reg_violations += 1
                warnings.append(f"REGRESSION {sym}.{sess_name}.{feat}: {result.reason}")
                print(f"  ⚠️  {sess_name:6s} {feat:25s} {result.reason}")
            elif result.baseline_median is not None:
                reg_checks_done += 1
    if reg_checks_done == 0 and reg_violations == 0:
        print(f"  · Baseline insuffisant (< {vb.MIN_SAMPLES_FOR_BASELINE} samples) — pas d'eval")
    elif reg_violations == 0:
        ok += 1
        print(f"  ✅ {reg_checks_done} comparaisons OK vs baseline")
    # Update baseline si aucune erreur detectee jusqu'ici (fichier GREEN)
    # NB : decision de persister deplacee apres verdict (seulement si GREEN)

    # ─── 16. COHERENCE IB (schema-auditor 20/04) ─────────────────────────
    # Detection Bug #2 : ib_position_pct non-null quand ib_complete=0
    # Design attendu (post fix C++ DMP_Transform.h:848) :
    # ib_complete=0 → ib_position_pct=null (IB partielle non-significatif)
    print(f"\n  ── V2.16 Coherence IB (ib_complete vs ib_position_pct) ──")
    incoh_partial = 0
    incoh_count = 0
    for r in lines:
        if r.get('ib_complete') == 0 and r.get('ib_position_pct') is not None:
            incoh_partial += 1
        incoh_count += 1
    if incoh_count > 0 and incoh_partial > 0:
        pct = incoh_partial / incoh_count
        # Pre-fix C++ : 60-80% incoherence attendu. Warning > 1% = design viole post-fix.
        if pct > 0.01:
            warnings.append(f"IB_COHERENCE: {incoh_partial}/{incoh_count} ({pct:.1%}) barres avec ib_complete=0 mais ib_position_pct non-null — fix C++ DMP_Transform.h:848 manquant")
            print(f"  ⚠️  {incoh_partial}/{incoh_count} ({pct:.1%}) barres IB partielle avec position_pct non-null")
        else:
            ok += 1
            print(f"  ✅ Coherence IB OK ({pct:.2%} residuel)")
    else:
        ok += 1
        print(f"  ✅ Coherence IB parfaite (0 barre incoherente)")

    # ─── 17. OPEN_TYPE CLASSIFICATION BLOQUEE (schema-auditor 20/04) ────
    # Detection Bug #3 : open_direction=0 sur > 95% barres RTH post-IB-complete
    # = DMP_ClassifyOpenType() bloque (input invalide prev_vah/val/ib_complete/price_at_1030)
    print(f"\n  ── V2.17 Open_type classification (bloquee si > 95% unknown) ──")
    rth_complete = [r for r in lines
                    if r.get('session') == 2 and r.get('ib_complete') == 1]
    if len(rth_complete) >= 30:
        unknown = sum(1 for r in rth_complete if r.get('open_direction') == 0
                      and r.get('open_type') == 0)
        pct_unknown = unknown / len(rth_complete)
        if pct_unknown > 0.95:
            warnings.append(f"OPEN_TYPE_BLOCKED: {sym} open_direction=0 sur {pct_unknown:.0%} RTH post-IB ({unknown}/{len(rth_complete)}) — classification probablement bloquee (prev_vah/val ou price_at_1030 invalide), check log SC [DMP_OpenType] ⚠️ BLOCKED")
            print(f"  ⚠️  {sym} open_type UNKNOWN sur {pct_unknown:.0%} RTH ({unknown}/{len(rth_complete)}) — investigation log SC requise")
        else:
            ok += 1
            print(f"  ✅ Open_type classification OK ({100*(1-pct_unknown):.0f}% RTH classifie)")
    else:
        print(f"  · RTH post-IB-complete insuffisant ({len(rth_complete)} < 30) — skip")

    # ═══════════════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  Validator v{VALIDATOR_VERSION}")
    if errors:
        print(f"  {len(errors)} ERREUR(S) — {'🔴' * min(len(errors), 10)}")
        for e in errors:
            print(f"    ❌ {e}")
    if warnings:
        print(f"  {len(warnings)} WARNING(S) — {'🟡' * min(len(warnings), 10)}")
        for w in warnings:
            print(f"    ⚠️ {w}")
    if not errors:
        print(f"  ✅ DONNÉES PROPRES — {ok} checks passent")
        print(f"     Schema {detected_schema}, {ncols} colonnes, {n} barres")
        # Update baseline SEULEMENT si fichier GREEN (pas d'erreur)
        # ET sans warning REGRESSION (sinon pollution auto-amplifiante — R1 code-reviewer 20/04).
        # Le warning REGRESSION indique une degradation : l'injecter dans baseline = definir
        # la degradation comme nouveau normal. Skip update dans ce cas.
        has_regression_warning = any("REGRESSION" in w for w in warnings)
        if has_regression_warning:
            print(f"     ⚠ Baseline NOT updated (REGRESSION warning present)")
        else:
            try:
                vb.update_baseline(baseline, sym, fire_rates)
                vb.save_baseline(baseline, baseline_path)
                print(f"     Baseline mis a jour ({sym}, {len(fire_rates)} sessions)")
            except Exception as e:
                print(f"     ⚠ Baseline update skipped: {e}")
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
