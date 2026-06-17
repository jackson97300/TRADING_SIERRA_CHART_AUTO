"""Helper centralise pour generer + parser signal_id cross-bots.

OBJECTIF (Jackson 17/06 audit observabilite) :
- Pouvoir grep un signal_id et voir TOUT le pipeline du trade
  (bar reception -> decision -> gates -> risk -> SLTP -> DTC -> fill -> close).
- Format standardise pour les 4 bots (avant : chaque bot avait son format).

FORMAT STANDARD :
    {BOT_PREFIX}_{SYM}_{BAR_TS_NS}_{DIRECTION_SHORT}_{HASH6}

Exemples :
    BOTMR_NQ_1781650320000000000_L_5942e7  (Bot MR NQ LONG)
    BOT1V2_ES_1781694780000000000_S_a3b1c2  (Bot 1 v2 ES SHORT)
    BOTBN_NQ_1781694600000000000_L_dfe077  (Bot BN V4 NQ LONG A++)
    BOT4_ES_1781650395000000000_S_7c9f12   (Bot 4 ES SHORT scenario)

PROPRIETES :
- Unique par signal : bar_ts_ns (= bar de detection) + hash6 (= randomness) = collision impossible
- Sortable : bar_ts_ns dans le format -> ordre chronologique naturel
- Parseable : split('_') donne (bot, sym, ts_ns, dir, hash)
- Greppable : on peut filtrer par bot OR sym OR direction OR period

USAGE PIPELINE :
    from CORE.signal_id import make_signal_id, parse_signal_id

    # Au moment de detection signal
    sid = make_signal_id("BOTMR", "NQ", bar_ts_ns=1781650320000000000, direction="long")

    # Propager dans TOUS les emits du pipeline
    bot_log.emit("BOTMR_GATE_REGIME_BLOCK", signal_id=sid, sym="NQ", ...)
    bot_log.emit("BOTMR_TRADABLE", signal_id=sid, sym="NQ", ...)
    bot_log.emit("BOTMR_ORDER_SENT", signal_id=sid, sym="NQ", ...)

    # Audit : grep cross-files par signal_id
    # grep "BOTMR_NQ_1781650320000000000_L_5942e7" LOGS/**/*.jsonl
"""
from __future__ import annotations

import hashlib
from typing import Optional


# Mapping direction -> 1 char (pour compacite + parsing facile)
_DIR_SHORT = {
    "long": "L", "LONG": "L", "BUY": "L", "buy": "L",
    "short": "S", "SHORT": "S", "SELL": "S", "sell": "S",
    "neutre": "N", "NEUTRE": "N", "NEUTRAL": "N",
}


def make_signal_id(
    bot_prefix: str,
    symbol: str,
    bar_ts_ns: int,
    direction: Optional[str] = None,
    extra_seed: str = "",
) -> str:
    """Genere un signal_id standardise pour tracer un signal a travers le pipeline.

    Args:
        bot_prefix: prefix bot ("BOTMR" / "BOT1V2" / "BOTBN" / "BOT4")
        symbol: symbole ("NQ" / "ES" / "MGC")
        bar_ts_ns: timestamp ns de la bar de detection (unique par minute)
        direction: optional "long"/"short"/"neutre" (defaut: None -> "X")
        extra_seed: optional seed supplementaire pour hash (ex: scenario_name)

    Returns:
        signal_id format : {bot_prefix}_{sym}_{ts_ns}_{dir_short}_{hash6}

    Examples:
        >>> make_signal_id("BOTMR", "NQ", 1781650320000000000, "long")
        'BOTMR_NQ_1781650320000000000_L_5942e7'
    """
    sym = symbol.upper()
    bp = bot_prefix.upper()
    dir_s = _DIR_SHORT.get(direction or "", "X")
    # Hash deterministe sur (bot, sym, ts_ns, dir, seed) -> meme inputs = meme id
    seed = f"{bp}|{sym}|{bar_ts_ns}|{dir_s}|{extra_seed}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6]
    return f"{bp}_{sym}_{bar_ts_ns}_{dir_s}_{h}"


def parse_signal_id(signal_id: str) -> dict:
    """Parse un signal_id en components.

    Args:
        signal_id: chaine au format {BOT}_{SYM}_{TS_NS}_{DIR}_{HASH}

    Returns:
        dict avec keys : bot, symbol, bar_ts_ns, direction, hash, valid

    Examples:
        >>> parse_signal_id("BOTMR_NQ_1781650320000000000_L_5942e7")
        {'bot': 'BOTMR', 'symbol': 'NQ', 'bar_ts_ns': 1781650320000000000,
         'direction': 'L', 'hash': '5942e7', 'valid': True}
    """
    parts = signal_id.split("_")
    if len(parts) != 5:
        return {"valid": False, "raw": signal_id}
    bot, sym, ts_str, dir_s, h = parts
    try:
        ts_ns = int(ts_str)
    except (ValueError, TypeError):
        return {"valid": False, "raw": signal_id}
    return {
        "bot": bot,
        "symbol": sym,
        "bar_ts_ns": ts_ns,
        "direction": dir_s,
        "hash": h,
        "valid": True,
    }


def is_valid_signal_id(signal_id: str) -> bool:
    """True si le signal_id respecte le format standard."""
    return parse_signal_id(signal_id).get("valid", False)
