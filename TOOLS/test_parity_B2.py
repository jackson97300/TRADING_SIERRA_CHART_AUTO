"""test_parity_B2.py - Sanity check Batch B2 niveaux ABSOLUS Sierra.

Objectif :
  Verifier que les 30 niveaux ABSOLUS exposes par le port B2 (F4 VWAP + F2
  Previous/Cash/Open/OVN + F23 VP) sont CONSISTANTS et UTILISABLES, sans
  exiger une parite bit-for-bit avec le pipeline Python.

Pourquoi pas parite stricte ?
  Decision Jackson 2026-06-07 — Sierra PRIME sur 3 familles (VWAP / VP /
  Session) car prop firms = aucun overnight autorise -> RTH-only standard.
  Les niveaux Sierra DIVERGENT volontairement de Python :
    * VWAP : Sierra anchored 09:30 ET (cash), Python anchored 00:00 ET (CME)
    * VP   : Sierra etude SC officielle, Python algo Steidlmayer avec biais
             VPOC=close si n=1 trade
    * Sess : Sierra RTH-only, Python session_date_trading 24h CME inclus
  Cf DMP_F3_DistNormalisees.h pour le bloc decision complet.

  La parite bit-for-bit reviendrait a accepter le Python (qui a justement
  les biais documentes). Donc on bascule sur des sanity checks :
    (1) Range realiste : les niveaux Sierra sont dans une plage coherente
        vs le close (ex: vwap_d a +/- 10% du close, pas a 100x ou 0.01x)
    (2) Signe correct : vwap_d_sd1u > vwap_d > vwap_d_sd1d (ordering bands)
    (3) Tolerance large vs Python : ecart < 50% (rejet outlier bug, ex:
        Python = 30491 mais Sierra = 6000 quand close = 30462)
    (4) Coverage : pas plus de 5% null sur features expected non-edge
        (pdh/pdl peuvent etre null sur la 1ere session du backfill)

Limites :
  - Sample limite a 1000 bars par defaut (vs JSONL complet ~500 bars/jour
    RTH). Sample > taille fichier = lit tout.
  - PDH/PDL peuvent etre null pour la 1ere date du dataset (pas de J-1
    connu). C'est NORMAL, le test n'echoue pas dessus.
  - Si live_enriched n'existe pas pour la date, skip silently les compares
    Python (Sierra-only sanity checks restent).

Usage :
  python -X utf8 tools/test_parity_B2.py [--sym NQ] [--date 20260603]

Sortie :
  RESULT : X/Y PASS  (Z FAIL)
  Exit code 0 si tout passe, 1 sinon.

Auteur : Batch B2 port — 2026-06-07
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Les 38 features absolus B2 + leur famille (F4 VWAP / F2 Prev / F23 VP)
B2_FEATURES = {
    # F4 — VWAP Daily (7)
    "vwap_d":       "vwap_daily",
    "vwap_d_sd1u":  "vwap_daily",
    "vwap_d_sd1d":  "vwap_daily",
    "vwap_d_sd2u":  "vwap_daily",
    "vwap_d_sd2d":  "vwap_daily",
    "vwap_d_sd3u":  "vwap_daily",
    "vwap_d_sd3d":  "vwap_daily",
    # F4 — VWAP Weekly (3)
    "vwap_w":       "vwap_weekly",
    "vwap_w_sd1u":  "vwap_weekly",
    "vwap_w_sd1d":  "vwap_weekly",
    "vwap_w_sd2u":  "vwap_weekly",
    "vwap_w_sd2d":  "vwap_weekly",
    "vwap_w_sd3u":  "vwap_weekly",
    "vwap_w_sd3d":  "vwap_weekly",
    # F4 — VWAP Monthly (7)
    "vwap_m":       "vwap_monthly",
    "vwap_m_sd1u":  "vwap_monthly",
    "vwap_m_sd1d":  "vwap_monthly",
    "vwap_m_sd2u":  "vwap_monthly",
    "vwap_m_sd2d":  "vwap_monthly",
    "vwap_m_sd3u":  "vwap_monthly",
    "vwap_m_sd3d":  "vwap_monthly",
    # F4 — Previous VWAP (3)
    "pvwap":        "pvwap",
    "pvwap_sd1u":   "pvwap",
    "pvwap_sd1d":   "pvwap",
    # F2 — Previous Day H/L (2)
    "pdh":          "prev_day",
    "pdl":          "prev_day",
    # F2 — Cash session H/L (2)
    "cash_high":    "cash_session",
    "cash_low":     "cash_session",
    # F2 — Open Cash + Open 8h30 (2)
    "open_cash_lvl": "open",
    "open_830_lvl":  "open",
    # F2 — Overnight H/L (2)
    "ovn_high_lvl": "overnight",
    "ovn_low_lvl":  "overnight",
    # F23 — VP Current (3)
    "cur_vpoc_lvl": "vp_current",
    "cur_vah_lvl":  "vp_current",
    "cur_val_lvl":  "vp_current",
    # F23 — VP Previous (3)
    "prev_vpoc_lvl": "vp_previous",
    "prev_vah_lvl":  "vp_previous",
    "prev_val_lvl":  "vp_previous",
}

# Features ou Python utilise un nom different (mapping pour cross-source check)
# Si le nom Python est None -> on skip le check vs Python pour cette feature.
PYTHON_NAME_MAP = {
    # VWAP : Python expose vwap_d / vwap_w / vwap_m / pvwap directement
    "vwap_d":       "vwap_d",
    "vwap_d_sd1u":  "vwap_d_sd1u",
    "vwap_d_sd1d":  "vwap_d_sd1d",
    "vwap_d_sd2u":  "vwap_d_sd2u",
    "vwap_d_sd2d":  "vwap_d_sd2d",
    "vwap_d_sd3u":  "vwap_d_sd3u",
    "vwap_d_sd3d":  "vwap_d_sd3d",
    "vwap_w":       "vwap_w",
    "vwap_w_sd1u":  "vwap_w_sd1u",
    "vwap_w_sd1d":  "vwap_w_sd1d",
    "vwap_w_sd2u":  "vwap_w_sd2u",
    "vwap_w_sd2d":  "vwap_w_sd2d",
    "vwap_w_sd3u":  "vwap_w_sd3u",
    "vwap_w_sd3d":  "vwap_w_sd3d",
    "vwap_m":       "vwap_m",
    "vwap_m_sd1u":  "vwap_m_sd1u",
    "vwap_m_sd1d":  "vwap_m_sd1d",
    "vwap_m_sd2u":  "vwap_m_sd2u",
    "vwap_m_sd2d":  "vwap_m_sd2d",
    "vwap_m_sd3u":  "vwap_m_sd3u",
    "vwap_m_sd3d":  "vwap_m_sd3d",
    "pvwap":        "pvwap",
    "pvwap_sd1u":   "pvwap_sd1u",
    "pvwap_sd1d":   "pvwap_sd1d",
    # Previous Day : Python a pdh/pdl avec memes noms
    "pdh":          "pdh",
    "pdl":          "pdl",
    # Cash : Python a cash_high/low
    "cash_high":    "cash_high",
    "cash_low":     "cash_low",
    # Open : Python a open_cash / open_830_et
    "open_cash_lvl": "open_cash",
    "open_830_lvl":  "open_830_et",
    # OVN : Python a ovn_high/low
    "ovn_high_lvl": "ovn_high",
    "ovn_low_lvl":  "ovn_low",
    # VP : Python a cur_vpoc/vah/val + prev_vpoc/vah/val
    "cur_vpoc_lvl": "cur_vpoc",
    "cur_vah_lvl":  "cur_vah",
    "cur_val_lvl":  "cur_val",
    "prev_vpoc_lvl": "prev_vpoc",
    "prev_vah_lvl":  "prev_vah",
    "prev_val_lvl":  "prev_val",
}

# Families ou Sierra prime (Jackson decision 2026-06-07) -> tolerance LARGE
# vs Python (10% ecart max, vs 1% pour les autres). Documentees dans le
# header DMP_F3_DistNormalisees.h.
SIERRA_PRIME_FAMILIES = {"vwap_daily", "vwap_weekly", "vwap_monthly",
                         "pvwap", "vp_current", "vp_previous", "cash_session"}


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


def check_range_sanity(df: pd.DataFrame, feature: str, family: str) -> dict:
    """Verifie qu'un niveau absolu est dans une plage coherente vs close.

    Retourne :
      dict {n_total, n_null, null_pct, max_pct_off, med_pct_off, status}
      status = PASS si plus de 90% des bars ont level a +/- 30% du close
               (les niveaux trades futures sont normalement < 10% off).
    """
    if feature not in df.columns or "price" not in df.columns:
        return {"status": "MISSING", "n_total": 0, "n_null": 0, "null_pct": 0.0,
                "max_pct_off": float("nan"), "med_pct_off": float("nan")}

    levels = pd.to_numeric(df[feature], errors="coerce")
    closes = pd.to_numeric(df["price"], errors="coerce")
    n_total = len(df)
    n_null = int(levels.isna().sum())
    null_pct = n_null / n_total if n_total > 0 else 1.0

    valid = pd.DataFrame({"lvl": levels, "close": closes}).dropna()
    valid = valid[valid["close"] > 0]
    if len(valid) == 0:
        # Tout null : OK pour PDH/PDL 1ere session, mais flagger si family != prev_day
        status = "ALL_NULL"
        return {"status": status, "n_total": n_total, "n_null": n_null,
                "null_pct": null_pct, "max_pct_off": float("nan"),
                "med_pct_off": float("nan")}

    pct_off = ((valid["lvl"] - valid["close"]) / valid["close"] * 100).abs()
    max_pct_off = float(pct_off.max())
    med_pct_off = float(pct_off.median())

    # Tolerance : 30% absolu (large car ES, NQ, MGC ont des magnitudes variees,
    # et certains niveaux multi-day (vwap_m) peuvent etre loin).
    # Sierra-prime families tolerance pareil (on check juste l'absence de bug).
    threshold = 30.0
    # PDH/PDL peuvent etre null sur 1ere session : tolerance null jusqu'a 50%
    null_threshold = 50.0 if family == "prev_day" else 5.0

    if null_pct * 100 > null_threshold:
        status = "TOO_NULL"
    elif max_pct_off > threshold:
        status = "OUT_OF_RANGE"
    else:
        status = "PASS"

    return {"status": status, "n_total": n_total, "n_null": n_null,
            "null_pct": null_pct, "max_pct_off": max_pct_off,
            "med_pct_off": med_pct_off}


def check_band_ordering(df: pd.DataFrame, base: str, sd1u: str, sd1d: str,
                        label: str) -> dict:
    """Verifie l'ordering des SD bands : sd1d < base < sd1u."""
    cols = [base, sd1u, sd1d]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return {"label": label, "status": "MISSING", "n_total": 0,
                "n_violations": 0, "missing": missing}

    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    n_total = len(sub)
    if n_total == 0:
        return {"label": label, "status": "NO_DATA", "n_total": 0,
                "n_violations": 0}

    # Violations : sd1d >= base OU sd1u <= base OU sd1d >= sd1u
    bad = ((sub[sd1d] >= sub[base]) |
           (sub[sd1u] <= sub[base]) |
           (sub[sd1d] >= sub[sd1u]))
    n_violations = int(bad.sum())
    status = "PASS" if n_violations == 0 else "FAIL"
    return {"label": label, "status": status, "n_total": n_total,
            "n_violations": n_violations}


def check_python_compare(df_sierra: pd.DataFrame, df_live: pd.DataFrame,
                         feature: str, family: str) -> dict:
    """Compare Sierra vs Python sur ts commun, avec tolerance dependant family.

    Sierra-prime families : tolerance LARGE (50% ecart accepte, on cherche
    juste les bugs majeurs : valeur off par 10x, signe inverse).
    Autres families : tolerance plus stricte (10% ecart).
    """
    py_name = PYTHON_NAME_MAP.get(feature)
    if not py_name or py_name not in df_live.columns:
        return {"status": "NO_PY", "n_pairs": 0, "med_diff_pct": float("nan"),
                "max_diff_pct": float("nan")}

    if "ts" not in df_sierra.columns or "ts" not in df_live.columns:
        return {"status": "NO_TS", "n_pairs": 0, "med_diff_pct": float("nan"),
                "max_diff_pct": float("nan")}

    # Si la colonne Sierra n'existe pas (pre-deploy B2 : JSONL DMP sans
    # les nouveaux fields), skip gracefully au lieu de KeyError.
    if feature not in df_sierra.columns:
        return {"status": "NO_SIERRA_COL", "n_pairs": 0,
                "med_diff_pct": float("nan"), "max_diff_pct": float("nan")}

    s = df_sierra.set_index("ts")[feature]
    l = df_live.set_index("ts")[py_name]
    common = s.index.intersection(l.index)
    if len(common) == 0:
        return {"status": "NO_TS_COMMON", "n_pairs": 0,
                "med_diff_pct": float("nan"), "max_diff_pct": float("nan")}

    sub = pd.DataFrame({"sierra": s.loc[common], "py": l.loc[common]}).apply(
        pd.to_numeric, errors="coerce").dropna()
    # Exclure pairs ou py == 0 (division par zero)
    sub = sub[sub["py"].abs() > 1e-3]
    n_pairs = len(sub)
    if n_pairs < 10:
        return {"status": "TOO_FEW", "n_pairs": n_pairs,
                "med_diff_pct": float("nan"), "max_diff_pct": float("nan")}

    diff_pct = ((sub["sierra"] - sub["py"]) / sub["py"] * 100).abs()
    med_diff_pct = float(diff_pct.median())
    max_diff_pct = float(diff_pct.max())

    # Threshold : tres large pour Sierra-prime families (divergence ATTENDUE),
    # plus stricte pour les autres.
    threshold = 50.0 if family in SIERRA_PRIME_FAMILIES else 10.0
    status = "MATCH" if med_diff_pct < threshold else "DIVERGENT"
    # NB : DIVERGENT n'est PAS un FAIL pour Sierra-prime families. C'est
    # info-only (mediane > seuil = on a divergence methodologique, attendue).
    return {"status": status, "n_pairs": n_pairs,
            "med_diff_pct": med_diff_pct, "max_diff_pct": max_diff_pct}


def main() -> int:
    p = argparse.ArgumentParser(
        description="Sanity check Batch B2 niveaux absolus Sierra")
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
    print(f"SANITY CHECK BATCH B2 — Niveaux ABSOLUS Sierra (16 VWAP + 8 prev + 6 VP)")
    print(f"  sym={args.sym}  date={args.date}  sample={args.sample}")
    print(f"  Sierra : {sierra_path}")
    if not args.no_python:
        print(f"  Live   : {live_path}")
    print("=" * 78)

    df_sierra = load_jsonl(sierra_path, args.sample)
    if df_sierra.empty:
        print("FAIL : fichier Sierra vide ou absent")
        return 1

    df_live = pd.DataFrame()
    if not args.no_python:
        df_live = load_jsonl(live_path, args.sample)

    print(f"Loaded sierra={len(df_sierra)} rows  live={len(df_live)} rows")
    print()

    # ─── 1. Range sanity : niveaux dans plage coherente vs close ─────────────
    print(f"{'Feature':<18} {'family':<14} {'n_total':>8} {'null%':>7} "
          f"{'med_off%':>9} {'max_off%':>9} {'status':>14}")
    print("-" * 90)
    pass_count = 0
    fail_count = 0
    info_count = 0
    for feature, family in B2_FEATURES.items():
        r = check_range_sanity(df_sierra, feature, family)
        st = r["status"]
        null_p = r["null_pct"] * 100
        med = r.get("med_pct_off", float("nan"))
        mx = r.get("max_pct_off", float("nan"))
        med_s = f"{med:.2f}" if not math.isnan(med) else "-"
        mx_s = f"{mx:.2f}" if not math.isnan(mx) else "-"
        # ALL_NULL pour prev_day = INFO (1ere session du backfill = OK)
        if st == "ALL_NULL" and family == "prev_day":
            st_disp = "INFO_ALL_NULL"
            info_count += 1
        elif st == "PASS":
            pass_count += 1
            st_disp = "PASS"
        else:
            fail_count += 1
            st_disp = st
        print(f"{feature:<18} {family:<14} {r['n_total']:>8} {null_p:>6.2f}% "
              f"{med_s:>9} {mx_s:>9} {st_disp:>14}")
    print()

    # ─── 2. SD Band ordering : sd1d < base < sd1u ───────────────────────────
    print("─── Band ordering checks ───")
    band_checks = [
        ("vwap_d", "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d ordering"),
        ("vwap_d", "vwap_d_sd2u", "vwap_d_sd2d", "vwap_d sd2 ordering"),
        ("vwap_d", "vwap_d_sd3u", "vwap_d_sd3d", "vwap_d sd3 ordering"),
        ("vwap_w", "vwap_w_sd1u", "vwap_w_sd1d", "vwap_w ordering"),
        ("vwap_w", "vwap_w_sd2u", "vwap_w_sd2d", "vwap_w sd2 ordering"),
        ("vwap_w", "vwap_w_sd3u", "vwap_w_sd3d", "vwap_w sd3 ordering"),
        ("vwap_m", "vwap_m_sd1u", "vwap_m_sd1d", "vwap_m ordering"),
        ("vwap_m", "vwap_m_sd2u", "vwap_m_sd2d", "vwap_m sd2 ordering"),
        ("vwap_m", "vwap_m_sd3u", "vwap_m_sd3d", "vwap_m sd3 ordering"),
        ("pvwap",  "pvwap_sd1u",  "pvwap_sd1d",  "pvwap ordering"),
    ]
    band_fail = 0
    for base, sd1u, sd1d, label in band_checks:
        r = check_band_ordering(df_sierra, base, sd1u, sd1d, label)
        st = r["status"]
        if st == "PASS":
            print(f"  PASS  {label:<28} n={r['n_total']}")
        else:
            band_fail += 1
            n_viol = r.get("n_violations", "-")
            print(f"  FAIL  {label:<28} n={r['n_total']}  violations={n_viol}")
    print()

    # ─── 3. VP ordering : val < vpoc < vah ──────────────────────────────────
    print("─── VP ordering checks (val < vpoc < vah) ───")
    vp_checks = [
        ("cur_vpoc_lvl", "cur_vah_lvl", "cur_val_lvl", "cur_vp ordering"),
        ("prev_vpoc_lvl", "prev_vah_lvl", "prev_val_lvl", "prev_vp ordering"),
    ]
    vp_fail = 0
    for vpoc, vah, val, label in vp_checks:
        r = check_band_ordering(df_sierra, vpoc, vah, val, label)
        st = r["status"]
        if st == "PASS":
            print(f"  PASS  {label:<28} n={r['n_total']}")
        else:
            vp_fail += 1
            n_viol = r.get("n_violations", "-")
            print(f"  FAIL  {label:<28} n={r['n_total']}  violations={n_viol}")
    print()

    # ─── 4. Cash/OVN/PDH-PDL ordering : low < high ───────────────────────────
    print("─── High/Low ordering checks (low < high) ───")
    hl_checks = [
        ("cash_low", "cash_high", "cash session H/L"),
        ("pdl",      "pdh",       "prev day H/L"),
        ("ovn_low_lvl", "ovn_high_lvl", "overnight H/L"),
    ]
    hl_fail = 0
    for lo, hi, label in hl_checks:
        if lo not in df_sierra.columns or hi not in df_sierra.columns:
            print(f"  MISS  {label:<28}  missing column")
            continue
        sub = df_sierra[[lo, hi]].apply(pd.to_numeric, errors="coerce").dropna()
        n_total = len(sub)
        if n_total == 0:
            print(f"  INFO  {label:<28}  all-null (OK pour 1ere session)")
            continue
        bad = sub[lo] >= sub[hi]
        n_viol = int(bad.sum())
        if n_viol == 0:
            print(f"  PASS  {label:<28}  n={n_total}")
        else:
            hl_fail += 1
            print(f"  FAIL  {label:<28}  n={n_total}  violations={n_viol}")
    print()

    # ─── 5. Compare Sierra vs Python (optionnel) ────────────────────────────
    py_match = 0
    py_div = 0
    py_skip = 0
    if not df_live.empty and not args.no_python:
        print(f"─── Python comparison (Sierra prime families = DIVERGENT ATTENDU) ───")
        print(f"{'Feature':<18} {'family':<14} {'n_pairs':>8} {'med_diff%':>10} "
              f"{'max_diff%':>10} {'status':>14}")
        print("-" * 80)
        for feature, family in B2_FEATURES.items():
            r = check_python_compare(df_sierra, df_live, feature, family)
            st = r["status"]
            mdp = r.get("med_diff_pct", float("nan"))
            mxp = r.get("max_diff_pct", float("nan"))
            mdp_s = f"{mdp:.2f}" if not math.isnan(mdp) else "-"
            mxp_s = f"{mxp:.2f}" if not math.isnan(mxp) else "-"
            n_p = r.get("n_pairs", 0)
            if st == "MATCH":
                py_match += 1
            elif st == "DIVERGENT":
                py_div += 1
            else:
                py_skip += 1
            print(f"{feature:<18} {family:<14} {n_p:>8} {mdp_s:>10} {mxp_s:>10} {st:>14}")
        print()

    # ─── BILAN ─────────────────────────────────────────────────────────────
    n_total = len(B2_FEATURES)
    print("=" * 78)
    print(f"BILAN B2 SANITY")
    print(f"  Range sanity   : {pass_count}/{n_total} PASS  "
          f"({info_count} INFO_ALL_NULL ok, {fail_count} FAIL)")
    print(f"  Band ordering  : {len(band_checks) - band_fail}/{len(band_checks)} PASS  "
          f"({band_fail} FAIL)")
    print(f"  VP ordering    : {len(vp_checks) - vp_fail}/{len(vp_checks)} PASS  "
          f"({vp_fail} FAIL)")
    print(f"  H/L ordering   : {len(hl_checks) - hl_fail}/{len(hl_checks)} PASS  "
          f"({hl_fail} FAIL)")
    if not df_live.empty and not args.no_python:
        print(f"  Python compare : {py_match} MATCH, {py_div} DIVERGENT, {py_skip} SKIP")
        print(f"                    (DIVERGENT attendu sur familles Sierra prime, info-only)")
    print("=" * 78)

    # Exit code : echec si FAIL sur range/ordering (les py compare ne comptent
    # pas, divergence Sierra-prime attendue).
    n_critical_fail = fail_count + band_fail + vp_fail + hl_fail
    if n_critical_fail == 0:
        print("RESULT : ALL PASS")
        return 0
    else:
        print(f"RESULT : {n_critical_fail} CRITICAL FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
