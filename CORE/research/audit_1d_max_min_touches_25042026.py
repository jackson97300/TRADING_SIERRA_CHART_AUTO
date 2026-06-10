"""
Audit statistique : le 1d_max / 1d_min MenthorQ est-il touche dans la journee ?

Strategie pour chaque jour :
  1. Charger JSONL DMP ES (ou NQ) du jour J
  2. Compute high_of_day_rth et low_of_day_rth sur bars session US (13:30-20:00 UTC)
     (Note : on prend aussi Asia+London pour completeness)
  3. Charger MQ file du jour J
  4. Lire 1d_max et 1d_min (publies au close jour J-1, valides pour J)
  5. Verifier :
     - high_day >= 1d_max (1d_max touche ou franchi)
     - low_day <= 1d_min (1d_min touche ou franchi)
     - distance high au 1d_max (si pas touche)
     - distance low au 1d_min (si pas touche)

Output : stats par instrument + agrege.
"""
import json
import glob
import os
from collections import defaultdict

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"
DATA_ES = f"{ROOT}/DATA/ES"
DATA_NQ = f"{ROOT}/DATA/NQ"
DATA_MQ = f"{ROOT}/DATA/MENTHORQ"

TICK = 0.25


def load_mq_levels(date_str: str):
    """Charge 1d_max, 1d_min, call_res, put_sup pour ES et NQ. Tolere structure variable."""
    path = f"{DATA_MQ}/{date_str}_menthorq_complete.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    kl = d.get("key_levels", {}) or {}
    out = {}
    for sym in ("ES", "NQ"):
        s = kl.get(sym, {}) or {}
        if not isinstance(s, dict) or not s:
            continue
        out[sym] = {
            "1d_max": s.get("1d_max"),
            "1d_min": s.get("1d_min"),
            "call_res": s.get("call_resistance"),
            "put_sup": s.get("put_support"),
            "hvl": s.get("hvl"),
        }
    return out


def analyze_day(date_str: str):
    """Pour un jour donne, verifie si high/low ont touche 1d_max/1d_min."""
    results = {}
    mq = load_mq_levels(date_str)
    if not mq:
        return None
    for sym in ("ES", "NQ"):
        jsonl_path = f"{ROOT}/DATA/{sym}/{date_str}_{sym}.jsonl"
        if not os.path.exists(jsonl_path):
            continue
        # Size guard : skip fichiers trop petits (week-end, jour ferie, erreur collecte)
        if os.path.getsize(jsonl_path) < 100_000:  # < 100KB = pas une vraie journee
            continue
        highs, lows = [], []
        try:
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        b = json.loads(line)
                    except Exception:
                        continue
                    h = b.get("bar_high") or b.get("price", 0)
                    l_ = b.get("bar_low") or b.get("price", 0)
                    if h: highs.append(float(h))
                    if l_: lows.append(float(l_))
        except Exception:
            continue
        if not highs or not lows:
            continue
        high_day = max(highs)
        low_day = min(lows)
        levels = mq.get(sym)
        if not levels:
            continue
        d1_max = levels.get("1d_max")
        d1_min = levels.get("1d_min")
        if d1_max is None or d1_min is None:
            continue
        # Normalize to float
        try:
            d1_max = float(d1_max); d1_min = float(d1_min)
        except (TypeError, ValueError):
            continue
        # Touches ?
        touched_max = high_day >= d1_max
        touched_min = low_day <= d1_min
        # Distance en ticks
        dist_high_to_max = (d1_max - high_day) / TICK  # positif = max pas atteint
        dist_low_to_min = (low_day - d1_min) / TICK    # positif = min pas atteint
        results[sym] = {
            "date": date_str,
            "high_day": high_day,
            "low_day": low_day,
            "1d_max": d1_max,
            "1d_min": d1_min,
            "touched_max": touched_max,
            "touched_min": touched_min,
            "touched_both": touched_max and touched_min,
            "dist_high_to_max_t": round(dist_high_to_max, 0),
            "dist_low_to_min_t": round(dist_low_to_min, 0),
            "range_day_pts": round(high_day - low_day, 2),
        }
    return results


def main():
    # Trouver tous les jours avec ES JSONL ET MQ file
    es_files = sorted(glob.glob(f"{DATA_ES}/2026*_ES.jsonl"))
    all_results_es = []
    all_results_nq = []
    for f in es_files:
        name = os.path.basename(f)
        date_str = name.split("_")[0]
        r = analyze_day(date_str)
        if not r:
            continue
        if "ES" in r:
            all_results_es.append(r["ES"])
        if "NQ" in r:
            all_results_nq.append(r["NQ"])

    def print_stats(results, label):
        if not results:
            print(f"{label}: 0 jour analyse")
            return
        n = len(results)
        touched_max = sum(1 for r in results if r["touched_max"])
        touched_min = sum(1 for r in results if r["touched_min"])
        touched_both = sum(1 for r in results if r["touched_both"])
        touched_none = sum(1 for r in results if not (r["touched_max"] or r["touched_min"]))
        print(f"\n=== {label} : {n} jours analyses ===")
        print(f"  1d_max touche : {touched_max}/{n} ({touched_max/n*100:.1f}%)")
        print(f"  1d_min touche : {touched_min}/{n} ({touched_min/n*100:.1f}%)")
        print(f"  LES DEUX touches (breakout les 2 cotes) : {touched_both}/{n} ({touched_both/n*100:.1f}%)")
        print(f"  AUCUN touche (range interne) : {touched_none}/{n} ({touched_none/n*100:.1f}%)")
        print()
        # Distance median si non touche
        not_touched_max = [r["dist_high_to_max_t"] for r in results if not r["touched_max"]]
        not_touched_min = [r["dist_low_to_min_t"] for r in results if not r["touched_min"]]
        if not_touched_max:
            from statistics import median, mean
            print(f"  Si 1d_max PAS touche : distance mediane = {median(not_touched_max):.0f}t (moyenne {mean(not_touched_max):.0f}t)")
        if not_touched_min:
            from statistics import median, mean
            print(f"  Si 1d_min PAS touche : distance mediane = {median(not_touched_min):.0f}t (moyenne {mean(not_touched_min):.0f}t)")
        print()
        print(f"  Detail par jour :")
        print(f"  {'date':<12}{'high':<10}{'low':<10}{'1d_max':<10}{'1d_min':<10}{'max?':<7}{'min?':<7}{'range_pts':<10}")
        for r in sorted(results, key=lambda x: x['date']):
            mx = "YES" if r["touched_max"] else f"({r['dist_high_to_max_t']:+.0f}t)"
            mn = "YES" if r["touched_min"] else f"({r['dist_low_to_min_t']:+.0f}t)"
            print(f"  {r['date']:<12}{r['high_day']:<10.2f}{r['low_day']:<10.2f}{r['1d_max']:<10.2f}{r['1d_min']:<10.2f}{mx:<7}{mn:<7}{r['range_day_pts']:<10.2f}")

    print("=" * 100)
    print("AUDIT : le 1d_max / 1d_min MenthorQ est-il touche dans la journee ?")
    print("=" * 100)
    print_stats(all_results_es, "ES")
    print_stats(all_results_nq, "NQ")

    # Combined
    all_combined = all_results_es + all_results_nq
    if all_combined:
        n = len(all_combined)
        tmax = sum(1 for r in all_combined if r["touched_max"])
        tmin = sum(1 for r in all_combined if r["touched_min"])
        tboth = sum(1 for r in all_combined if r["touched_both"])
        print(f"\n=== COMBINED ES+NQ : {n} jours-instruments ===")
        print(f"  1d_max touche : {tmax}/{n} ({tmax/n*100:.1f}%)")
        print(f"  1d_min touche : {tmin}/{n} ({tmin/n*100:.1f}%)")
        print(f"  Les 2 touches : {tboth}/{n} ({tboth/n*100:.1f}%)")
        print(f"  Aucun touche  : {sum(1 for r in all_combined if not (r['touched_max'] or r['touched_min']))}/{n}")


if __name__ == "__main__":
    main()
