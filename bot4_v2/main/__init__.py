"""Bot 4 v2 main : boucle principale + JSONL stream Protocol.

P5.2 (sem 8) : bot_main_v2 orchestre router + reconciler + jsonl stream pour
le pipeline complet de bot4_v2 paper Sim4 (reuse compte Bot 4 v1 stopped).

API publique :
- BotMainLoop : boucle principale (consomme JSONL, route, reconcile, heartbeat)
- BotMainSettings : config frozen (heartbeat_sec, symbols, max_cycles)
- JSONLStream Protocol : interface streaming bar par bar (test stub friendly)
- StreamEnded : exception fin de stream (simu / end of file)
"""
from bot4_v2.main.bot_main_v2 import (
    BotMainLoop,
    BotMainSettings,
    JSONLStream,
    JSONLTailStream,
    StreamEnded,
)

__all__ = [
    "BotMainLoop",
    "BotMainSettings",
    "JSONLStream",
    "JSONLTailStream",
    "StreamEnded",
]
