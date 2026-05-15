"""Test empirique _seed_ib_from_warmup sur V4 batch VPS local."""
import sys
sys.path.insert(0, "CORE")

import pandas as pd
from pathlib import Path

# Imports locaux
from live_enricher_state import LiveEnricherState, _seed_ib_from_warmup
from phase_b_helpers import IBState

def test_seed_ib(sym: str, v4_path: str):
    """Test seed IB pour un symbole."""
    print(f"\n=== Test seed IB {sym} ===")
    df = pd.read_parquet(v4_path)
    state = LiveEnricherState(symbol=sym)

    # Avant seed
    state_ib_before = state.engine_states.get("ib_features")
    print(f"  Avant seed: ib_features={state_ib_before}")

    # Seed
    _seed_ib_from_warmup(state, sym, df=df)

    # Apres seed
    state_ib_after = state.engine_states.get("ib_features")
    print(f"  Apres seed: ib_features={state_ib_after}")
    if isinstance(state_ib_after, IBState):
        print(f"    current_date_et={state_ib_after.current_date_et} (type={type(state_ib_after.current_date_et).__name__})")
        print(f"    ib_high={state_ib_after.ib_high}")
        print(f"    ib_low={state_ib_after.ib_low}")
        print(f"    n_ib_bars_seen={state_ib_after.n_ib_bars_seen}")

if __name__ == "__main__":
    # ES VPS V4 path
    test_seed_ib("ES.c.0", "C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=05/data.parquet")
    test_seed_ib("NQ.c.0", "C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=05/data.parquet")
    test_seed_ib("MGC.v.0", "C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=MGC.c.0/year=2026/month=05/data.parquet")
