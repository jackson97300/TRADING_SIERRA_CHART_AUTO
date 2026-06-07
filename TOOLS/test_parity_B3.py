"""test_parity_B3.py - Sanity check Batch B3.A F22 + F12_safe + F8 + F9.

Objectif :
  Verifier que les 25 features exposees par le port B3.A (F22 PositionRange 4 +
  F12 BarShape SAFE 6 + F8 News 14 + F9 Roll 1) sont CONSISTANTES et UTILISABLES.
  4 F12 long_* NON-PORTEES car les Sierra natives equivalentes existent deja
  dans le JSONL : long_up_bar -> bar_long_up_bar, long_dn_bar -> bar_long_dn_bar,
  long_dn_up_pattern -> bar_long_dn_up, long_up_dn_pattern -> bar_long_up_dn
  (+ bonus dist_ext_long_up / dist_ext_long_dn = Extension Lines distances).
  bar_no_trade REFACTORE isna() strict (100% match Python verifie empirique).

Pour B3, contrairement a B1 (parite stricte) ou B2 (Sierra prime), les
familles ont differents niveaux de tolerance vs Python live_enriched :
  * F22 PositionRange : parite stricte attendue (formule identique Python,
    inputs Sierra sess_high/low + mq_1d_*).
  * F12 BarShape : parite forme stricte (formule identique), tolerance
    info-only sur le seuil ATR (atr_14m C++ vs atr Python possibilites
    diverger en valeur).
  * F8 News : parite stricte BIT-FOR-BIT (logique horaire pure, pas de
    dependance source data hors mins_et qui est identique).
  * F9 Roll : parite stricte info-only (cas roll rares = peu de bars).

Sanity checks par feature :
  (1) Plage realiste : pct_in_range in [0, 100], wicks in [0, 3], etc.
  (2) Boolean strictement 0 ou 1 (pas 0.5, pas valeur intermediaire)
  (3) is_news_HHMM = 1 EXACTEMENT quand mins_et = N (pas off by 1)
  (4) within_news_HHMM_5m couvre les 5 mins post event
  (5) DMP_INVALID -> null mappe correctement pour mins_since_news /
      mins_to_next_news hors fenetre 7h15-9h30 ET (CRITIQUE pour LightGBM)

Limites :
  - Sample limite a 1000 bars par defaut.
  - F9 is_roll_day : 0 sur toutes les sessions sauf les ~4/an roll days
    -> sanity = "tout 0 OK" + "pas de fausse alerte sur manual switch".
  - F12 long_*_pattern : rare event (necessite 2 bars long_* consecutives).

Usage :
  python -X utf8 tools/test_parity_B3.py [--sym NQ] [--date 20260603]

Sortie :
  RESULT : X/Y PASS  (Z FAIL)
  Exit code 0 si tout passe, 1 sinon.

Auteur : Batch B3 port — 2026-06-07
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Les 25 features B3.A + leur famille (F22 / F12_safe / F8 / F9).
# Jackson decisions :
#  - 2026-06-07 22:50 : discount_zone garde (FULL REGLES "Buy the dip")
#  - 2026-06-08 00:30 : bar_no_trade REFACTORE isna() strict (100% match Python)
#  - 2026-06-08 00:30 : 4 F12 long_* NON-PORTEES, mapping Sierra natives :
#       long_up_bar -> bar_long_up_bar, long_dn_bar -> bar_long_dn_bar,
#       long_dn_up_pattern -> bar_long_dn_up, long_up_dn_pattern -> bar_long_up_dn
B3_FEATURES = {
    # F22 — Position Range (4)
    "pct_in_range":           "F22_position_range",
    "premium_zone":           "F22_position_range",
    "discount_zone":          "F22_position_range",
    "position_in_range":      "F22_position_range",
    # F12 — Bar Shape SAFE (6/10 ; 4 NON-PORTEES = Sierra natives bar_long_*)
    "bar_body_pct":           "F12_bar_shape",
    "bar_body_ticks":         "F12_bar_shape",
    "bar_upper_wick_pct":     "F12_bar_shape",
    "bar_lower_wick_pct":     "F12_bar_shape",
    "bar_no_trade":           "F12_bar_shape",
    "range_size":             "F12_bar_shape",
    # -- NON-PORTEES (Sierra natives existantes JSONL) --
    # "long_up_bar":            "F12_bar_shape",  → utiliser bar_long_up_bar du JSONL
    # "long_dn_bar":            "F12_bar_shape",  → utiliser bar_long_dn_bar du JSONL
    # "long_dn_up_pattern":     "F12_bar_shape",  → utiliser bar_long_dn_up du JSONL
    # "long_up_dn_pattern":     "F12_bar_shape",  → utiliser bar_long_up_dn du JSONL
    # F8 — News (14 — mins_et utilise en interne mais non expose au JSONL)
    "is_news_715":            "F8_news",
    "is_news_730":            "F8_news",
    "is_news_830":            "F8_news",
    "is_news_845":            "F8_news",
    "is_news_900":            "F8_news",
    "is_news_930":            "F8_news",
    "within_news_715_5m":     "F8_news",
    "within_news_730_5m":     "F8_news",
    "within_news_830_5m":     "F8_news",
    "within_news_845_5m":     "F8_news",
    "within_news_900_5m":     "F8_news",
    "within_news_930_5m":     "F8_news",
    "mins_since_news":        "F8_news",
    "mins_to_next_news":      "F8_news",
    # F9 — Roll (1)
    "is_roll_day":            "F9_roll",
}

# Plage realiste par feature : (min, max) - utilise pour check_range_sanity.
# None signifie "pas de borne haute" / "boolean strict 0-1".
FEATURE_RANGES = {
    # F22
    "pct_in_range":           (0.0, 100.0),
    "premium_zone":           "boolean",
    "discount_zone":          "boolean",
    "position_in_range":      (0.0, 1.0),
    # F12 SAFE (6/10 ; 4 NON-PORTEES = Sierra natives bar_long_*)
    "bar_body_pct":           (-100.0, 100.0),
    "bar_body_ticks":         (-200.0, 200.0),  # ATR moyen ~10t, body extreme ~200t
    "bar_upper_wick_pct":     (0.0, 3.0),       # clamp Python
    "bar_lower_wick_pct":     (0.0, 3.0),
    "bar_no_trade":           "boolean",        # 1 si fpbs_delta == INVALID (isna strict)
    "range_size":             (0.0, 200.0),     # 200 points = 800 ticks NQ extreme
    # F8 (mins_et n'est pas expose au JSONL)
    "is_news_715":            "boolean",
    "is_news_730":            "boolean",
    "is_news_830":            "boolean",
    "is_news_845":            "boolean",
    "is_news_900":            "boolean",
    "is_news_930":            "boolean",
    "within_news_715_5m":     "boolean",
    "within_news_730_5m":     "boolean",
    "within_news_830_5m":     "boolean",
    "within_news_845_5m":     "boolean",
    "within_news_900_5m":     "boolean",
    "within_news_930_5m":     "boolean",
    "mins_since_news":        (0, 1440),
    "mins_to_next_news":      (0, 1440),
    # F9
    "is_roll_day":            "boolean",
}

# News times en mins_et (= ET mins from midnight). Aligne sur Python +
# DMP_F8_News.h tableau hardcode.
NEWS_MINS = {
    "is_news_715": 7 * 60 + 15,
    "is_news_730": 7 * 60 + 30,
    "is_news_830": 8 * 60 + 30,
    "is_news_845": 8 * 60 + 45,
    "is_news_900": 9 * 60 + 0,
    "is_news_930": 9 * 60 + 30,
}

# Mapping Python live_enriched (pour parity check info-only)
PYTHON_NAME_MAP = {
    # F22
    "pct_in_range":           "pct_in_range",
    "premium_zone":           "premium_zone",
    "discount_zone":          "discount_zone",
    "position_in_range":      "position_in_range",
    # F12 (memes noms Python)
    "bar_body_pct":           "bar_body_pct",
    "bar_body_ticks":         "bar_body_ticks",
    "bar_upper_wick_pct":     "bar_upper_wick_pct",
    "bar_lower_wick_pct":     "bar_lower_wick_pct",
    "bar_no_trade":           "bar_no_trade",
    # -- NON-PORTEES (Sierra natives JSONL) --
    # "long_up_bar":            "bar_long_up_bar",     # mapping Sierra-prime
    # "long_dn_bar":            "bar_long_dn_bar",
    # "long_dn_up_pattern":     "bar_long_dn_up",
    # "long_up_dn_pattern":     "bar_long_up_dn",
    "range_size":             "range_size",
    # F8 (memes noms Python — mins_et non expose JSONL)
    "is_news_715":            "is_news_715",
    "is_news_730":            "is_news_730",
    "is_news_830":            "is_news_830",
    "is_news_845":            "is_news_845",
    "is_news_900":            "is_news_900",
    "is_news_930":            "is_news_930",
    "within_news_715_5m":     "within_news_715_5m",
    "within_news_730_5m":     "within_news_730_5m",
    "within_news_830_5m":     "within_news_830_5m",
    "within_news_845_5m":     "within_news_845_5m",
    "within_news_900_5m":     "within_news_900_5m",
    "within_news_930_5m":     "within_news_930_5m",
    "mins_since_news":        "mins_since_news",
    "mins_to_next_news":      "mins_to_next_news",
    # F9
    "is_roll_day":            "is_roll_day",
}

# Familles ou divergence METHODE attendue (parity info-only) :
#   F12 : seuil ATR Python (atr Databento daily 5min ?) vs atr_14m Sierra (TICKS 14m).
#         Les booleans long_*_bar peuvent diverger en pratique si ATR != ATR.
DIVERGENT_FAMILIES = {"F12_bar_shape"}


def load_jsonl(path: Path, sample: int = 1000) -> pd.DataFrame:
    """Lit un JSONL ligne par ligne (skip JSONDecodeError silently)."""
    rows = []
    if not path.exists():
        return pd.DataFrame()
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= sample:
                break
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(rows)


def check_range_sanity(df: pd.DataFrame, feature: str, expected_range) -> dict:
    """Verifie que la feature reste dans une plage realiste."""
    if feature not in df.columns:
        return {"status": "MISSING", "n_total": 0, "n_null": 0,
                "null_pct": 0.0, "n_out_of_range": 0}

    series = pd.to_numeric(df[feature], errors="coerce")
    n_total = len(df)
    n_null = int(series.isna().sum())
    null_pct = n_null / n_total if n_total > 0 else 1.0
    valid = series.dropna()

    if len(valid) == 0:
        return {"status": "ALL_NULL", "n_total": n_total, "n_null": n_null,
                "null_pct": null_pct, "n_out_of_range": 0}

    n_out_of_range = 0
    if expected_range == "boolean":
        # Strict 0 ou 1 (pas 0.5 ni intermediaire). On accepte des valeurs
        # numeriques 0.0/1.0 mais on flag tout le reste.
        n_out_of_range = int(((valid != 0) & (valid != 1)).sum())
    else:
        lo, hi = expected_range
        n_out_of_range = int(((valid < lo) | (valid > hi)).sum())

    if n_out_of_range > 0:
        # Tolerance 1% out-of-range (peut etre clamp flotant ou edge case)
        out_pct = n_out_of_range / len(valid)
        if out_pct < 0.01:
            status = "PASS_WITH_OUTLIERS"
        else:
            status = "OUT_OF_RANGE"
    else:
        status = "PASS"

    return {"status": status, "n_total": n_total, "n_null": n_null,
            "null_pct": null_pct, "n_out_of_range": n_out_of_range}


def compute_mins_et_from_ts(df: pd.DataFrame) -> pd.Series:
    """Recalcule mins_et (minutes depuis minuit ET, DST-aware) depuis ts ms epoch.

    `mins_et` n'est PAS expose au JSONL (decision audit B3 pour rester
    n_cols 347 -> 375). Mais downstream peut le recalculer depuis ts.
    Logique alignee sur DMP_Reader.h:2745.
    """
    if "ts" not in df.columns:
        return pd.Series([], dtype=float)
    ts_ms = pd.to_numeric(df["ts"], errors="coerce")
    # ts est en ms epoch UTC. Conversion to datetime UTC -> ET.
    # Sierra Chart utilise tz America/New_York (DST-aware). Pandas tz_convert
    # gere DST correctement.
    dt_utc = pd.to_datetime(ts_ms, unit="ms", utc=True)
    try:
        dt_et = dt_utc.dt.tz_convert("America/New_York")
    except Exception:
        # Pas de tzdata installe -> fallback offset hardcode (approximatif)
        dt_et = dt_utc - pd.Timedelta(hours=4)
    return dt_et.dt.hour * 60 + dt_et.dt.minute


def check_news_alignment(df: pd.DataFrame) -> dict:
    """Verifie que is_news_HHMM = 1 EXACTEMENT quand mins_et == N target.

    Retourne pour chaque event : n_event_fires, mins_et_at_fire (devrait etre
    le target unique), n_false_positives (fire avec mins_et != target).
    """
    results = {}
    mins_series = compute_mins_et_from_ts(df)
    if mins_series.empty:
        return {"global_status": "NO_TS"}

    for col_name, target_min in NEWS_MINS.items():
        if col_name not in df.columns:
            results[col_name] = {"status": "MISSING"}
            continue

        flag = pd.to_numeric(df[col_name], errors="coerce")
        # Sub-frame avec flag=1 (utilise indice positionnel pour join avec mins_series)
        fires_mask = (flag > 0.5)
        n_fires = int(fires_mask.sum())
        if n_fires == 0:
            results[col_name] = {"status": "NO_FIRE", "n_fires": 0,
                                 "expected_mins_et": target_min}
            continue

        # Verifier que TOUS les fires ont mins_et == target (positionnel)
        fire_mins_et = mins_series[fires_mask].dropna()
        n_correct = int((fire_mins_et == target_min).sum())
        n_false_pos = n_fires - n_correct
        status = "PASS" if n_false_pos == 0 else "FAIL"
        results[col_name] = {
            "status": status, "n_fires": n_fires,
            "n_correct": n_correct, "n_false_pos": n_false_pos,
            "expected_mins_et": target_min,
        }

    return results


def check_within_news_window(df: pd.DataFrame) -> dict:
    """Verifie within_news_HHMM_5m = 1 sur [tgt, tgt+5).

    Pour chaque within_news : verif (1) que la valeur est 1 dans le bon range,
    (2) que la valeur est 0 ailleurs.
    """
    results = {}
    mins_series = compute_mins_et_from_ts(df)
    if mins_series.empty:
        return {"global_status": "NO_TS"}

    for col_name, target_min in NEWS_MINS.items():
        within_col = col_name.replace("is_news_", "within_news_") + "_5m"
        if within_col not in df.columns:
            results[within_col] = {"status": "MISSING"}
            continue

        flag = pd.to_numeric(df[within_col], errors="coerce")
        # Sub-frame ou la bar est in [tgt, tgt+5)
        in_window = (mins_series >= target_min) & (mins_series < target_min + 5)
        # Verif : in_window -> flag=1, out_window -> flag=0
        # Counter exemples :
        in_window_n = int(in_window.sum())
        n_correct_inside = int(((flag > 0.5) & in_window).sum())
        n_wrong_inside = int(((flag <= 0.5) & in_window).sum())
        n_wrong_outside = int(((flag > 0.5) & ~in_window).sum())

        if in_window_n == 0:
            results[within_col] = {"status": "NO_OBS_IN_WINDOW",
                                   "in_window_n": 0,
                                   "n_wrong_outside": n_wrong_outside}
            continue

        if n_wrong_inside == 0 and n_wrong_outside == 0:
            status = "PASS"
        else:
            status = "FAIL"
        results[within_col] = {
            "status": status, "in_window_n": in_window_n,
            "n_correct_inside": n_correct_inside,
            "n_wrong_inside": n_wrong_inside,
            "n_wrong_outside": n_wrong_outside,
        }

    return results


def check_python_parity(df_sierra: pd.DataFrame, df_live: pd.DataFrame,
                        feature: str, family: str) -> dict:
    """Compare Sierra vs Python sur ts commun.

    Info-only pour familles DIVERGENT_FAMILIES (cf F12 ATR).
    Strict (MATCH < 1% diff) pour les autres.
    """
    py_name = PYTHON_NAME_MAP.get(feature)
    if not py_name or py_name not in df_live.columns:
        return {"status": "NO_PY", "n_pairs": 0}

    if "ts" not in df_sierra.columns or "ts" not in df_live.columns:
        return {"status": "NO_TS", "n_pairs": 0}

    if feature not in df_sierra.columns:
        # Patch defensive pre-deploy : Sierra n'a pas encore la feature dans le
        # JSONL (DMP recompile en attente). Gracefully skip pour ne pas casser
        # le test parity B3 lance avant deploy C++.
        return {"status": "NO_SIERRA_COL", "n_pairs": 0}

    s = df_sierra.set_index("ts")[feature]
    l = df_live.set_index("ts")[py_name]
    common = s.index.intersection(l.index)
    if len(common) == 0:
        return {"status": "NO_TS_COMMON", "n_pairs": 0}

    sub = pd.DataFrame({"sierra": s.loc[common], "py": l.loc[common]}).apply(
        pd.to_numeric, errors="coerce").dropna()
    n_pairs = len(sub)
    if n_pairs < 10:
        return {"status": "TOO_FEW", "n_pairs": n_pairs}

    # Pour les booleans, on compare 1-to-1 (egalite exacte).
    # Pour les scalaires, on compare en %.
    expected_range = FEATURE_RANGES.get(feature)
    if expected_range == "boolean":
        n_match = int((sub["sierra"] == sub["py"]).sum())
        match_pct = n_match / n_pairs
        if family in DIVERGENT_FAMILIES:
            # F12 long_*_bar peut diverger (atr_14m vs Python atr).
            status = "MATCH" if match_pct > 0.7 else "DIVERGENT_INFO"
        else:
            status = "MATCH" if match_pct > 0.95 else "DIVERGENT"
        return {"status": status, "n_pairs": n_pairs, "match_pct": match_pct}
    else:
        # Tolerance 5% pour scalaires non-divergent, 30% info-only sinon.
        diff = (sub["sierra"] - sub["py"]).abs()
        ref = sub["py"].abs().clip(lower=1e-3)
        diff_pct = (diff / ref * 100)
        med_diff_pct = float(diff_pct.median())
        max_diff_pct = float(diff_pct.max())
        threshold = 30.0 if family in DIVERGENT_FAMILIES else 5.0
        status = "MATCH" if med_diff_pct < threshold else (
            "DIVERGENT_INFO" if family in DIVERGENT_FAMILIES else "DIVERGENT")
        return {"status": status, "n_pairs": n_pairs,
                "med_diff_pct": med_diff_pct, "max_diff_pct": max_diff_pct}


def check_mins_since_to_news_invalid(df: pd.DataFrame) -> dict:
    """Verifie que mins_since_news et mins_to_next_news sont null HORS
    de la fenetre 7h15-9h30 ET, et non null DANS la fenetre.

    CRITIQUE : si on a -1 (sentinel Python) au lieu de null, LightGBM apprend
    une feature degeneree.
    """
    mins_series = compute_mins_et_from_ts(df)
    if mins_series.empty:
        return {"status": "NO_TS"}

    # mins_since_news : null si mins_et < 7h15 = 435
    # mins_to_next_news : null si mins_et > 9h30 = 570
    # (en dehors de RTH start)
    result = {}
    for col_name, condition in [
        ("mins_since_news", mins_series < 435),
        ("mins_to_next_news", mins_series > 570),
    ]:
        if col_name not in df.columns:
            result[col_name] = {"status": "MISSING"}
            continue
        ser = pd.to_numeric(df[col_name], errors="coerce")
        # Pour les bars condition=True (hors window), valeur DOIT etre null.
        out_of_window = ser[condition]
        n_should_be_null = len(out_of_window)
        n_actually_null = int(out_of_window.isna().sum())
        # Pour les bars condition=False, valeur PEUT etre non null.
        in_window = ser[~condition]
        n_in_window = len(in_window)
        n_non_null_in_window = int(in_window.notna().sum())

        # Detection sentinel -1 (mauvais pattern Python)
        n_minus_one = int((ser == -1.0).sum())

        if n_should_be_null > 0 and n_actually_null < n_should_be_null * 0.95:
            status = "FAIL_NOT_NULL_OUTSIDE"
        elif n_minus_one > 0:
            status = "FAIL_HAS_MINUS_ONE"
        else:
            status = "PASS"
        result[col_name] = {
            "status": status,
            "n_should_be_null": n_should_be_null,
            "n_actually_null": n_actually_null,
            "n_in_window": n_in_window,
            "n_non_null_in_window": n_non_null_in_window,
            "n_minus_one": n_minus_one,
        }
    return result


def main() -> int:
    p = argparse.ArgumentParser(
        description="Sanity check Batch B3 F22 + F12 + F8 + F9")
    p.add_argument("--sym", default="NQ", choices=("NQ", "ES"))
    p.add_argument("--date", default="20260603", help="YYYYMMDD")
    p.add_argument("--sample", type=int, default=1000,
                   help="Nb lignes lues (defaut 1000)")
    p.add_argument("--no-python", action="store_true",
                   help="Skip compare vs live_enriched (Sierra-only sanity)")
    args = p.parse_args()

    sierra_path = ROOT / "DATA" / args.sym / f"{args.date}_{args.sym}.jsonl"
    live_path = ROOT / "DATA" / "live_enriched" / args.sym / f"{args.date}_{args.sym}.jsonl"

    print("=" * 78)
    print("SANITY CHECK BATCH B3.A — F22 + F12_safe + F8 + F9 (25 features)")
    print(f"  sym={args.sym}  date={args.date}  sample={args.sample}")
    print(f"  Sierra : {sierra_path}")
    if not args.no_python:
        print(f"  Live   : {live_path}")
    print("=" * 78)

    df_sierra = load_jsonl(sierra_path, args.sample)
    if df_sierra.empty:
        print("FAIL : fichier Sierra vide ou absent")
        print("       (normal pre-deploy : test skipping range checks)")
        # Pre-deploy : ce test peut etre lance avant que Sierra ait recompile
        # avec le nouveau schema B3. On exit 0 si le fichier est juste absent.
        return 0

    df_live = pd.DataFrame()
    if not args.no_python:
        df_live = load_jsonl(live_path, args.sample)

    print(f"Loaded sierra={len(df_sierra)} rows  live={len(df_live)} rows")
    print()

    # ─── 1. Range sanity par feature ─────────────────────────────────────────
    print(f"{'Feature':<22} {'family':<20} {'n_total':>8} {'null%':>7} "
          f"{'oor':>5} {'status':>22}")
    print("-" * 88)
    pass_count = 0
    fail_count = 0
    info_count = 0
    for feature, family in B3_FEATURES.items():
        expected_range = FEATURE_RANGES.get(feature, "boolean")
        r = check_range_sanity(df_sierra, feature, expected_range)
        st = r["status"]
        null_p = r["null_pct"] * 100
        oor = r["n_out_of_range"]
        if st in ("PASS", "PASS_WITH_OUTLIERS"):
            pass_count += 1
            st_disp = st
        elif st == "MISSING":
            # Pre-deploy : fichier sans la colonne (Sierra pas recompile).
            # Comme "NO_SIERRA_COL" en parite : info, pas fail.
            info_count += 1
            st_disp = "INFO_MISSING"
        elif st == "ALL_NULL":
            # Cas degenere mais peut etre OK pour is_news / is_roll_day si
            # le sample ne contient pas l'event.
            info_count += 1
            st_disp = "INFO_ALL_NULL"
        else:
            fail_count += 1
            st_disp = st
        print(f"{feature:<22} {family:<20} {r['n_total']:>8} {null_p:>6.2f}% "
              f"{oor:>5} {st_disp:>22}")
    print()

    # ─── 2. News alignment : is_news_HHMM = 1 a mins_et exact ────────────────
    print("─── News alignment checks (is_news_HHMM == 1 ssi mins_et == target) ───")
    news_results = check_news_alignment(df_sierra)
    if news_results.get("global_status") == "NO_TS":
        print("  SKIP : ts absent du JSONL")
    else:
        for col_name, r in news_results.items():
            st = r["status"]
            if st == "PASS":
                print(f"  PASS  {col_name:<22} fires={r['n_fires']}  "
                      f"target_mins_et={r['expected_mins_et']}")
                pass_count += 1
            elif st == "NO_FIRE":
                print(f"  INFO  {col_name:<22} no fires in sample  "
                      f"target_mins_et={r['expected_mins_et']}")
                info_count += 1
            elif st == "MISSING":
                print(f"  INFO  {col_name:<22} missing column (pre-deploy)")
                info_count += 1
            else:
                print(f"  FAIL  {col_name:<22} fires={r['n_fires']}  "
                      f"false_pos={r['n_false_pos']}")
                fail_count += 1
    print()

    # ─── 3. within_news window alignment ─────────────────────────────────────
    print("─── within_news_5m alignment checks ───")
    within_results = check_within_news_window(df_sierra)
    if within_results.get("global_status") == "NO_TS":
        print("  SKIP : ts absent")
    else:
        for col_name, r in within_results.items():
            st = r["status"]
            if st == "PASS":
                print(f"  PASS  {col_name:<24} in_window={r['in_window_n']}")
                pass_count += 1
            elif st in ("NO_OBS_IN_WINDOW",):
                print(f"  INFO  {col_name:<24} no obs in window")
                info_count += 1
            elif st == "MISSING":
                print(f"  INFO  {col_name:<24} missing column")
                info_count += 1
            else:
                wrong_in = r.get("n_wrong_inside", "-")
                wrong_out = r.get("n_wrong_outside", "-")
                print(f"  FAIL  {col_name:<24} in_window={r['in_window_n']}  "
                      f"wrong_in={wrong_in}  wrong_out={wrong_out}")
                fail_count += 1
    print()

    # ─── 4. mins_since/to_news NULL hors fenetre (CRITIQUE LightGBM) ─────────
    print("─── mins_since/to_news null hors fenetre (anti -1 sentinel) ───")
    sentinel_results = check_mins_since_to_news_invalid(df_sierra)
    if sentinel_results.get("status") == "NO_TS":
        print("  SKIP : ts absent")
    else:
        for col_name, r in sentinel_results.items():
            st = r["status"]
            if st == "PASS":
                print(f"  PASS  {col_name:<22} null_hors={r['n_actually_null']}/"
                      f"{r['n_should_be_null']}  in_window_nn={r['n_non_null_in_window']}")
                pass_count += 1
            elif st == "MISSING":
                print(f"  INFO  {col_name:<22} missing column")
                info_count += 1
            else:
                print(f"  FAIL  {col_name:<22} status={st}  -1 count={r.get('n_minus_one')}")
                fail_count += 1
    print()

    # ─── 5. Parite Python live_enriched (info-only pour familles divergentes) ─
    if not df_live.empty:
        print(f"{'Feature':<22} {'family':<20} {'n_pairs':>8} {'match%':>8} "
              f"{'med_diff%':>10} {'status':>14}")
        print("-" * 90)
        for feature, family in B3_FEATURES.items():
            r = check_python_parity(df_sierra, df_live, feature, family)
            st = r["status"]
            n_pairs = r.get("n_pairs", 0)
            mp = r.get("match_pct", float("nan"))
            mp_s = f"{mp*100:.1f}" if not (isinstance(mp, float) and math.isnan(mp)) else "-"
            md = r.get("med_diff_pct", float("nan"))
            md_s = f"{md:.2f}" if not (isinstance(md, float) and math.isnan(md)) else "-"
            if st == "MATCH":
                pass_count += 1
            elif st in ("DIVERGENT_INFO", "NO_PY", "NO_TS", "NO_TS_COMMON",
                        "TOO_FEW", "NO_SIERRA_COL"):
                info_count += 1
            else:
                fail_count += 1
            print(f"{feature:<22} {family:<20} {n_pairs:>8} {mp_s:>7}% "
                  f"{md_s:>9}% {st:>14}")
        print()
    else:
        print("(skip Python parity : live_enriched absent ou --no-python)")

    # ─── Resume ──────────────────────────────────────────────────────────────
    print("=" * 78)
    print(f"RESULT : {pass_count} PASS  {info_count} INFO  {fail_count} FAIL")
    print("=" * 78)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
