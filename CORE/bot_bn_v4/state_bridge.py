"""State bridge Bot BN V4 -> dashboard state_sim3.json.

Calque sur CORE.bot1_v2.state_bridge.StateBridge mais cible un fichier
DEDIE pour Sim3 afin d'eviter collision avec :
  - Bot 1 v2 -> DATA/PAPER_TRADES/state.json (Sim2)
  - Bot 4    -> DATA/PAPER_TRADES/state_sim4.json (Sim4)

Path : DATA/PAPER_TRADES/state_sim3.json
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from CORE.bot1_v2.state_bridge import StateBridge as _BaseStateBridge


def _bot_bn_state_path() -> Path:
    """Chemin VPS : DATA/PAPER_TRADES/state_sim3.json."""
    root = Path(os.environ.get("MIA_ROOT", Path.cwd()))
    return root / "DATA" / "PAPER_TRADES" / "state_sim3.json"


class BotBNStateBridge(_BaseStateBridge):
    """Sous-classe StateBridge avec path Sim3 dedie.

    Reutilise toute la logique (heartbeat, rotate_day, open_position,
    update_open_position_live, close_position) de Bot 1 v2.
    """

    def __init__(self, path: Optional[Path] = None):
        super().__init__(path=path or _bot_bn_state_path())
