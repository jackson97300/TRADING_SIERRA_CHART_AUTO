"""test_phase_b_trades_streaming_weekend.py

Test transition weekend 3-day gap : vendredi 21:00 UTC -> lundi 22:00 UTC.
Verifie que le compteur daily_running reset correctement (pas de pollution
cross-week) et que prev_day_high/low correspondent bien au last day available.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "CORE"))

from phase_b_plus_plus_trades_streaming import (  # noqa: E402
    add_phase_b_plus_plus_trades_streaming,
    make_phase_b_plus_plus_trades_state,
)


def test_weekend_gap():
    state = make_phase_b_plus_plus_trades_state(symbol="ES")

    # Vendredi 21:00 UTC : 5 bars
    ts_fri = pd.Timestamp("2026-04-03 21:00:00", tz="UTC")
    for i in range(5):
        row = {
            "ts_event": ts_fri + pd.Timedelta(minutes=i),
            "high": 5800 + i, "low": 5790 + i, "close": 5795 + i,
        }
        trades = [
            {"price": 5795 + i, "size": 10, "side": "A", "ts_event": row["ts_event"]},
            {"price": 5793 + i, "size": 5, "side": "B", "ts_event": row["ts_event"]},
        ]
        add_phase_b_plus_plus_trades_streaming(row, state, trades_in_window=trades)

    fri_high = state.daily_high_running
    fri_low = state.daily_low_running
    print(f"Vendredi close : high={fri_high} low={fri_low}")
    assert fri_high == 5804, f"Vendredi high attendu 5804, recu {fri_high}"
    assert fri_low == 5790, f"Vendredi low attendu 5790, recu {fri_low}"

    # Lundi 22:00 UTC : 5 bars (gap 3 jours)
    ts_mon = pd.Timestamp("2026-04-06 22:00:00", tz="UTC")
    for i in range(5):
        row = {
            "ts_event": ts_mon + pd.Timedelta(minutes=i),
            "high": 5850 + i, "low": 5840 + i, "close": 5845 + i,
        }
        trades = [
            {"price": 5845 + i, "size": 8, "side": "A", "ts_event": row["ts_event"]},
        ]
        add_phase_b_plus_plus_trades_streaming(row, state, trades_in_window=trades)

    # Apres gap : daily_running doit etre lundi (5850-5854), prev_day = vendredi
    print(f"Lundi running : high={state.daily_high_running} low={state.daily_low_running}")
    print(f"prev_day : high={state.prev_day_high} low={state.prev_day_low}")
    assert state.daily_high_running == 5854, (
        f"Lundi daily high attendu 5854, recu {state.daily_high_running}"
    )
    assert state.daily_low_running == 5840, (
        f"Lundi daily low attendu 5840, recu {state.daily_low_running}"
    )
    assert state.prev_day_high == fri_high, (
        f"prev_day_high doit etre vendredi {fri_high}, recu {state.prev_day_high}"
    )
    assert state.prev_day_low == fri_low, (
        f"prev_day_low doit etre vendredi {fri_low}, recu {state.prev_day_low}"
    )

    print("PASS : weekend gap correctement gere")


if __name__ == "__main__":
    test_weekend_gap()
