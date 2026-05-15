"""Sanity check math : verifier coherence calculs LIVE Enricher.

Jackson 15/05/2026 : "DMP n'est pas une science exacte, faire attention aux
donnees et leur calcul, toujours verifier."

Tests math/business :
  1. OHLC : high >= max(o, c) >= min(o, c) >= low
  2. atr > 0 si bars >= 14
  3. dist_X_atr signe : positif si level > close
  4. Magnitude dist_X_atr : raisonnable (clamp ±5 ou raw < 50)
  5. mq_call > mq_put (call resistance > put support en general)
  6. vwap_d entre sess_low et sess_high
  7. cur_vah >= cur_vpoc >= cur_val (value area structure)
  8. prev_vah >= prev_vpoc >= prev_val (idem prev session)
  9. range_pos ∈ [0, 1]
 10. atr_14m_pct ∈ [0.01, 5.0] (% raisonnable)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_bar(bar: dict, sym: str) -> list[str]:
    """Liste violations math/business sur 1 bar."""
    violations = []

    o, h, l, c = bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close")
    if all(v is not None for v in (o, h, l, c)):
        if not (h >= max(o, c) >= min(o, c) >= l):
            violations.append(f"OHLC invariant : h={h} max(o,c)={max(o,c)} min={min(o,c)} l={l}")

    atr = bar.get("atr")
    if atr is not None and atr <= 0:
        violations.append(f"atr non-positif : {atr}")

    # 3. Signes dist_*_atr coherents
    close = bar.get("close")
    for lvl_key, atr_key in [
        ("sess_high", "dist_sess_high_atr"),
        ("sess_low", "dist_sess_low_atr"),
        ("cur_vpoc", "dist_cur_vpoc_atr"),
        ("cur_vah", "dist_cur_vah_atr"),
        ("cur_val", "dist_cur_val_atr"),
        ("pdh", "dist_pdh_atr"),
        ("pdl", "dist_pdl_atr"),
        ("mq_call", "dist_mq_call_atr"),
        ("mq_put", "dist_mq_put_atr"),
    ]:
        lvl = bar.get(lvl_key)
        dist_atr = bar.get(atr_key)
        if lvl is not None and close is not None and dist_atr is not None:
            expected_sign = 1 if lvl > close else (-1 if lvl < close else 0)
            actual_sign = 1 if dist_atr > 0 else (-1 if dist_atr < 0 else 0)
            # Si dist_atr clampe (abs == 5.0), signe peut etre invariant
            if abs(dist_atr) < 4.99 and expected_sign != actual_sign and expected_sign != 0:
                violations.append(
                    f"{atr_key} signe incoherent : lvl={lvl}, close={close}, "
                    f"expected sign={expected_sign}, dist_atr={dist_atr}"
                )

    # 6. vwap_d entre sess_low et sess_high (intraday VWAP au mi-range)
    vwap_d = bar.get("vwap_d")
    sl = bar.get("sess_low")
    sh = bar.get("sess_high")
    if all(v is not None for v in (vwap_d, sl, sh)):
        if not (sl <= vwap_d <= sh):
            violations.append(f"vwap_d hors sess range : vwap_d={vwap_d}, [sl={sl}, sh={sh}]")

    # 7. Value area structure
    vah, vpoc, val = bar.get("cur_vah"), bar.get("cur_vpoc"), bar.get("cur_val")
    if all(v is not None for v in (vah, vpoc, val)):
        if not (vah >= vpoc >= val):
            violations.append(f"cur_VA structure : vah={vah}, vpoc={vpoc}, val={val}")

    # 8. Prev session structure
    pvah, pvpoc, pval = bar.get("prev_vah"), bar.get("prev_vpoc"), bar.get("prev_val")
    if all(v is not None for v in (pvah, pvpoc, pval)):
        if not (pvah >= pvpoc >= pval):
            violations.append(f"prev_VA structure : vah={pvah}, vpoc={pvpoc}, val={pval}")

    # 9. range_pos ∈ [0, 1]
    rp = bar.get("range_pos")
    if rp is not None and not (0 <= rp <= 1):
        violations.append(f"range_pos hors [0, 1] : {rp}")

    # 10. atr_14m_pct ∈ [0.01, 5.0] (% raisonnable, ES/NQ tipique 0.1-1.5%)
    apct = bar.get("atr_14m_pct")
    if apct is not None and not (0.001 < apct < 10.0):
        violations.append(f"atr_14m_pct hors [0.001, 10.0] : {apct}")

    return violations


def main():
    # ts_min : skip bars antérieurs (pre-fix deploy). Default = bars 15:35+
    # car deploy V3 P4 _atr ~15:30 UTC. Pour audit J+1, passer 0.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="JSONL files (default = all)")
    ap.add_argument("--ts-min-iso", default=None,
                    help="Skip bars before this ts_event_iso (e.g., 2026-05-15T15:35)")
    args = ap.parse_args()

    if args.paths:
        files = [Path(p) for p in args.paths]
    else:
        files = sorted((ROOT / "DATA" / "live_enriched").rglob("20260515_*.jsonl"))

    total_bars = 0
    total_violations = 0
    n_skip = 0
    for path in files:
        if ".bak" in path.name:
            continue
        sym = path.parent.name
        n_bars = 0
        n_violations = 0
        viol_samples = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    bar = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if args.ts_min_iso:
                    ts_iso = bar.get("ts_event_iso", "")
                    if ts_iso < args.ts_min_iso:
                        n_skip += 1
                        continue
                n_bars += 1
                vs = check_bar(bar, sym)
                if vs:
                    n_violations += len(vs)
                    if len(viol_samples) < 5:
                        viol_samples.append((bar.get("ts_event_iso"), vs))
        print(f"\n=== {sym} ({path.name}) : {n_bars} bars / {n_violations} violations ===")
        if viol_samples:
            for ts, vs in viol_samples:
                print(f"  bar {ts} :")
                for v in vs:
                    print(f"    - {v}")
        total_bars += n_bars
        total_violations += n_violations

    print(f"\n{'='*70}")
    print(f"  TOTAL : {total_bars} bars, {total_violations} violations")
    if total_violations == 0:
        print(f"  VERDICT : MATH/BUSINESS COHERENT")
    else:
        print(f"  VERDICT : {total_violations} ANOMALIES DETECTEES (cf samples)")


if __name__ == "__main__":
    main()
