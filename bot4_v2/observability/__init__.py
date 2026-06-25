"""Bot 4 v2 observability : telemetry + shadow_logger + calibration_persistence."""
from bot4_v2.observability.telemetry import emit_safe, get_logger

__all__ = ["emit_safe", "get_logger"]
