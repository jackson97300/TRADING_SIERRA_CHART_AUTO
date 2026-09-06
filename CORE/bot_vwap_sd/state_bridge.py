"""State bridge dashboard Bot 5 VWAP-SD (Sim3 emplacement)."""
from __future__ import annotations

from pathlib import Path

from CORE.bot1_v2.dashboard_mirror import StateBridge


class VwapSdStateBridge(StateBridge):
    """Sub-class StateBridge pour pointer vers state_sim3_vwapsd.json."""

    def __init__(self):
        root = Path(__file__).resolve().parents[2]
        super().__init__(
            state_path=root / "DATA" / "DASHBOARD" / "state_sim3_vwapsd.json",
        )
