"""State bridge Bot MR -> dashboard state_sim1.json.

Sub-class StateBridge avec path override pour DATA/PAPER_TRADES/state_sim1.json.
Permet au dashboard de visualiser Sim1 separement de Sim2 (Bot 1 v2).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from CORE.bot1_v2.state_bridge import StateBridge


def _default_sim1_state_path() -> Path:
    """Chemin VPS : DATA/PAPER_TRADES/state_sim1.json (relatif au cwd nssm)."""
    root = Path(os.environ.get("MIA_ROOT", Path.cwd()))
    return root / "DATA" / "PAPER_TRADES" / "state_sim1.json"


class BotMRStateBridge(StateBridge):
    """StateBridge dedie Bot MR -> state_sim1.json.

    Heritage propre : reutilise heartbeat / open_position / close_position /
    rotate_day de StateBridge, mais ecrit dans state_sim1.json (PAS state.json
    qui est utilise par Bot 1 v2 / mia_paper_trader legacy).
    """

    def __init__(self, path: Optional[Path] = None):
        super().__init__(path=path or _default_sim1_state_path())
