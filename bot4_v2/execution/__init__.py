"""Bot 4 v2 execution : DTC adapter isolated wrapper + bracket manager + position reconciler.

Spec Phase P2 + P4 :
- P2 Batch 4b : dtc_adapter NEW Pydantic ISOLATED wrapper vs BOT/dtc_connector.py
- P4 sem 7 : bracket_manager + position_reconciler

API publique exposee P2 batch 4b :
- dtc_adapter : DTCAdapter, DTCSettings, OrderRequest, BracketRequest, BracketResult,
  ConnectionStatus, IDTCBackend Protocol
"""
from bot4_v2.execution.dtc_adapter import (
    BracketRequest,
    BracketResult,
    ConnectionStatus,
    DTCAdapter,
    DTCSettings,
    IDTCBackend,
    OrderRequest,
    OrderSide,
)

__all__ = [
    "BracketRequest",
    "BracketResult",
    "ConnectionStatus",
    "DTCAdapter",
    "DTCSettings",
    "IDTCBackend",
    "OrderRequest",
    "OrderSide",
]
