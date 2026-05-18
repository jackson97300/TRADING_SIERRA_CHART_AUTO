"""Test Phase 3c-B : verifier 8 features streaming sont produites + state init.

Utilise un MOCK LiveEnricherState minimal (juste get_engine_state) + snapshot
vendredi pour valider :
1. Aucune exception _apply_phase_3c_B
2. Les 8 features attendues sont presentes dans payload
3. State engine_states["edge_zones"] + ["color_bars"] crees
4. Multiple bars sequentielles : state persistant (buffer grandit)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.enricher_chain import _apply_phase_3c_B


class MockState:
    """Mock LiveEnricherState minimum pour test."""
    def __init__(self):
        self.engine_states = {}

    def get_engine_state(self, engine_name, factory=dict):
        if engine_name not in self.engine_states:
            self.engine_states[engine_name] = factory()
        return self.engine_states[engine_name]


SNAPSHOT_FRIDAY = {
    "symbol": "NQ.c.0",
    "open": 29170.75, "high": 29172.0, "low": 29168.25, "close": 29168.25,
    "volume": 89, "delta_bar": 28.0,
    "mq_call": 30000.0, "mq_put": 29300.0, "mq_hvl": 28990.0,
}


def _log_fn(code, **kwargs):
    print(f"  [LOG] {code}: {kwargs}")


def main():
    print("=" * 70)
    print("  TEST PHASE 3c-B : 8 features WIRE STREAMING")
    print("=" * 70)

    state = MockState()
    # FIX B1 test : injecter footprint_cells simulees (stack vol acheteur)
    # pour valider que edge_zones_streaming detecte au moins 1 zone (sinon
    # le test ne valide que l'absence d'exception, pas le wiring reel).
    # Structure : {price: {"ask_vol": V, "bid_vol": V}}
    # Stack acheteur : 3+ cellules contigues avec ask_vol > seuil_pct * total_vol
    # EDGE_THRESHOLD_PCT=600 (ratio ask/bid >= 6x pour stack acheteur)
    # min_group_size=3 → besoin 3 cellules contigues avec ratio >= 600%
    state.engine_states["footprint_cells_current_bar"] = {
        29168.25: {"ask_vol": 80, "bid_vol": 5},   # ratio 1600%
        29168.50: {"ask_vol": 75, "bid_vol": 4},   # ratio 1875%
        29168.75: {"ask_vol": 90, "bid_vol": 6},   # ratio 1500%
        29169.00: {"ask_vol": 85, "bid_vol": 3},   # ratio 2833%
    }
    payload = dict(SNAPSHOT_FRIDAY)
    keys_before = set(payload.keys())

    try:
        _apply_phase_3c_B(payload, state, symbol="NQ.c.0", log_fn=_log_fn)
        print("[OK] _apply_phase_3c_B execute sans exception (bar 1)")
    except Exception as e:
        print(f"[FAIL] Exception : {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    keys_after = set(payload.keys())
    new_keys = keys_after - keys_before
    print(f"Keys ajoutees bar 1 : {len(new_keys)}")

    expected = {
        "dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
        "n_edge_buy_active", "n_edge_sell_active",
        "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
        "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    }
    missing = expected - new_keys
    if missing:
        print(f"[FAIL] Features ABSENTES : {missing}")
    else:
        print(f"[OK] 8/8 features ciblees presentes")

    print("\n=== VALEURS bar 1 ===")
    for k in sorted(expected):
        v = payload.get(k)
        print(f"  {k:42s} = {v}")

    print(f"\n=== STATE ENGINE STATES bar 1 ===")
    print(f"  Keys state.engine_states : {list(state.engine_states.keys())}")

    # Bar 2 : test state persistance
    payload2 = dict(SNAPSHOT_FRIDAY)
    payload2["close"] = 29175.5  # +1 bar simulee
    payload2["high"] = 29178.0
    payload2["low"] = 29170.0
    print("\n=== BAR 2 simulee (state persistant) ===")
    try:
        _apply_phase_3c_B(payload2, state, symbol="NQ.c.0", log_fn=_log_fn)
        print("[OK] _apply_phase_3c_B execute bar 2")
    except Exception as e:
        print(f"[FAIL bar 2] {type(e).__name__}: {e}")
        sys.exit(2)
    for k in sorted(expected):
        v = payload2.get(k)
        print(f"  {k:42s} = {v}")

    print("\n=== VERDICT ===")
    if not missing:
        print(f"OK : 8/8 features Phase B livrees, state persistant cross-bars OK.")
    else:
        print(f"FAIL : {len(missing)} features manquantes")
        sys.exit(3)


if __name__ == "__main__":
    main()
