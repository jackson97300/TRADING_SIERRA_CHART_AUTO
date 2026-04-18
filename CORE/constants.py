"""Constantes partagees MIA Trading.

Source unique pour eviter les duplications (violation DRY audit 2026-04-09).
"""

# Tick size par instrument (ES et NQ micros)
TICK_SIZE: dict[str, float] = {
    "ES": 0.25,
    "NQ": 0.25,
}

# Valeur d'un tick en USD (pour P&L)
TICK_VALUE: dict[str, float] = {
    "ES": 1.25,  # Micro ES : $1.25/tick
    "NQ": 0.50,  # Micro NQ : $0.50/tick
}

# Default tick size pour code generique (ES + NQ ont le meme)
DEFAULT_TICK_SIZE: float = 0.25

# Schema DMP version courante
DMP_SCHEMA_VERSION: str = "3.7.2"
DMP_SCHEMA_COLS: int = 262

# ── ROLLING FEATURES seuils (centralises 18/04/2026 audit code-reviewer) ──
# Avant : seuils absolus hardcodes dans rolling_features.py (risque feature morte
# sur sessions calmes NQ Asia/pre-FOMC avec delta_bar median ~10-15).
# Apres : seuils relatifs multipliant un rolling_std(delta_bar, 50).
INSTANT_ABSORPTION_DELTA_K: float = 1.5   # multiplicateur rolling_std(delta_bar, 50)
INSTANT_ABSORPTION_WINDOW: int = 50       # bars de lookback pour rolling_std


def get_tick_size(symbol: str) -> float:
    """Retourne le tick size d'un instrument."""
    return TICK_SIZE.get(symbol.upper(), DEFAULT_TICK_SIZE)


def get_tick_value(symbol: str) -> float:
    """Retourne la valeur d'un tick en USD."""
    return TICK_VALUE.get(symbol.upper(), 1.25)
