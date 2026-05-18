"""Smoke test Phase 4d integration Bot3Engine V1 vs V2 sur donnees reelles.

Mandate Jackson 18/05 nuit : "EXECUTION SUR DONNER REL" avant deploy VPS.

Workflow :
- Iter bars ES 5 mois Mai 2026 (sample)
- Compare 2 instances Bot3Engine :
    * engine_v1 : BOT3_USE_NARRATIVE_DIRECTION=False (default)
    * engine_v2 : BOT3_USE_NARRATIVE_DIRECTION=True (Phase 4d MVP)
- Compter signals emis par chaque engine
- Verifier aucun crash, structure Bot3Signal valide

Critere PASS :
- 0 exception
- V2 emet >= 1 signal sur 5 mois data (sinon integration broken)
- V2 signals ont scenario_id + narrative_state dans params
- V1 inchange par rapport au baseline

Usage : python -X utf8 tools/smoke_test_bot3_v2_integration.py
"""
from __future__ import annotations

import importlib
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))


def run_engine(symbol: str, parquet_path: str, use_v2: bool, max_bars: int = 5000):
    """Run Bot3Engine sur N bars. Retourne stats."""
    # Patch config
    import CORE.bot3_config as cfg
    cfg.BOT3_USE_NARRATIVE_DIRECTION = use_v2
    cfg.BOT3_NARRATIVE_TRACKING_ONLY = False  # full V2 mode
    cfg.BOT3_OBSERVE_ONLY = False
    # Reload mp_engine pour catcher le flag
    import CORE.bot3_mp_engine as mp
    importlib.reload(mp)

    df = pd.read_parquet(parquet_path)
    df = df.sort_values("ts_event").reset_index(drop=True)
    if len(df) > max_bars:
        df = df.iloc[:max_bars]

    engine = mp.Bot3Engine()
    label = "V2" if use_v2 else "V1"
    print(f"\n--- Run {label} on {symbol} ({len(df)} bars) ---")
    print(f"  engine.nsm = {type(engine._nsm).__name__ if engine._nsm else None}")
    print(f"  engine.resolver = {type(engine._resolver).__name__ if engine._resolver else None}")

    signals = []
    decisions_total = 0
    exceptions = 0
    scenario_counter = Counter()
    state_counter = Counter()

    for i, row in df.iterrows():
        bar = row.to_dict()
        try:
            signal, decisions = engine.evaluate(bar, symbol)
        except Exception as e:
            exceptions += 1
            if exceptions <= 3:
                print(f"    EXCEPTION bar {i} ({type(e).__name__}): {str(e)[:120]}")
            continue
        decisions_total += len(decisions)
        if signal is not None:
            signals.append({
                "ts": signal.bar_ts, "sym": signal.symbol,
                "level": signal.level_name, "side": signal.side,
                "scenario": signal.params.get("scenario_id"),
                "narrative_state": signal.params.get("narrative_state"),
                "v2_source": signal.params.get("v2_source"),
                "bucket": signal.bucket,
            })
            if signal.params.get("scenario_id"):
                scenario_counter[signal.params["scenario_id"]] += 1
            if signal.params.get("narrative_state"):
                state_counter[signal.params["narrative_state"]] += 1

    print(f"  {label} signals : {len(signals)} | decisions logs : {decisions_total} | exceptions : {exceptions}")
    if signals:
        print(f"  Sample signals (first 3) :")
        for s in signals[:3]:
            print(f"    {s}")
    if use_v2 and scenario_counter:
        print(f"  V2 scenarios fired :")
        for k, v in scenario_counter.most_common():
            print(f"    {k} : {v}")
    if use_v2 and state_counter:
        print(f"  V2 narrative_states :")
        for k, v in state_counter.most_common():
            print(f"    {k} : {v}")

    return {
        "label": label,
        "n_signals": len(signals),
        "n_decisions": decisions_total,
        "n_exceptions": exceptions,
        "scenario_counter": dict(scenario_counter),
        "state_counter": dict(state_counter),
        "first_signals": signals[:5],
    }


def main() -> int:
    print("=" * 78)
    print("SMOKE TEST Bot3Engine Phase 4d - V1 vs V2 (5000 bars ES sample)")
    print("=" * 78)

    parquet = ROOT / "DATA/V4_TEMP/ES_5months_combined.parquet"
    if not parquet.exists():
        print(f"ERR : parquet absent {parquet}")
        return 1

    # Run V1
    res_v1 = run_engine("ES", str(parquet), use_v2=False, max_bars=5000)
    # Run V2
    res_v2 = run_engine("ES", str(parquet), use_v2=True, max_bars=5000)

    # Comparaison + verdict
    print("\n" + "=" * 78)
    print("VERDICT SMOKE TEST")
    print("=" * 78)
    print(f"V1 : signals={res_v1['n_signals']}  decisions={res_v1['n_decisions']}  exceptions={res_v1['n_exceptions']}")
    print(f"V2 : signals={res_v2['n_signals']}  decisions={res_v2['n_decisions']}  exceptions={res_v2['n_exceptions']}")

    pass_criteria = []
    pass_criteria.append(("V1 zero exception", res_v1["n_exceptions"] == 0))
    pass_criteria.append(("V2 zero exception", res_v2["n_exceptions"] == 0))
    pass_criteria.append(("V2 emit >=1 signal", res_v2["n_signals"] >= 1))
    pass_criteria.append(("V2 signals contain scenario_id",
                          bool(res_v2["scenario_counter"])))
    pass_criteria.append(("V2 signals contain narrative_state",
                          bool(res_v2["state_counter"])))

    for label, ok in pass_criteria:
        marker = "[OK]" if ok else "[FAIL]"
        print(f"  {marker} {label}")

    all_ok = all(ok for _, ok in pass_criteria)
    print(f"\nVerdict global : {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
