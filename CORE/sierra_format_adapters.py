"""Sierra Format Adapters : conversions Sierra -> Databento payload format.

Phase 0 Sierra Pipeline Port (11/06/2026) - Decision B2.

Permet aux modules streaming portee de enricher_chain.py (pipeline Databento)
de consommer les bars Sierra DMP via wrappers de format.

POURQUOI :
==========
Les modules streaming attendent un dict `inputs` structure :
- `ohlcv` : OHLCV bar
- `trades_df` : DataFrame trades (Sierra n'a pas -> VAP wrapper)
- `mq_levels` : dict mq_call/put/hvl + arrays (Sierra emet plats)
- `vix` : dict vix_level + dist_vix_* (Sierra emet plats)
- `stream_alive` : bool
- `ts_read_ns` : int nanoseconds

Sierra DMP emet differemment :
- bar dict 380+ cols avec champs aplats (ex: dist_mq_call, vix_level)
- `ts` en milliseconds epoch UTC (pas `ts_event_ns`)
- pas de `trades_df` (juste VAP aggregates)
- pas de dicts pour mq_levels/vix

Ces adapters reconstruisent les formats attendus depuis le bar Sierra brut.

LIMITATION CONNUE (B2 design v2) :
===================================
VAP -> trades_df proxy : on synthetise des trades aggregees par price level,
ce qui fausse `p99_trade_size` et `max_size_buy/sell` (categorie C3 harness).

Auteur : MIA Trading V2 (Phase 0 portage)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
# Constantes pour validation
# ═══════════════════════════════════════════════════════════════════════════════

# ts Sierra (ms epoch) doit etre dans cette plage realiste
_TS_MS_MIN = 1_577_836_800_000   # 2020-01-01 UTC ms
_TS_MS_MAX = 2_524_608_000_000   # 2050-01-01 UTC ms


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OHLCV adapter
# ═══════════════════════════════════════════════════════════════════════════════

def sierra_bar_to_databento_ohlcv(sierra_bar: dict) -> dict:
    """Convertit bar Sierra (380+ cols) en OHLCV-like Databento.

    Args:
        sierra_bar : dict bar Sierra brut.

    Returns:
        dict : {
            'open', 'high', 'low', 'close', 'volume',
            'ts_event_ns', 'ts_event' (pd.Timestamp tz=UTC),
            'instrument_id',
            '_sierra_bar' : reference original 380 cols pour merge ulterieur,
            '_source' : 'sierra',
        }

    Raises:
        ValueError : si ts hors plage realiste OR ts absent.
    """
    ts_ms = sierra_bar.get("ts")
    if ts_ms is None:
        raise ValueError("Sierra bar missing 'ts' (ms epoch)")
    if not (_TS_MS_MIN <= ts_ms <= _TS_MS_MAX):
        raise ValueError(
            f"Sierra ts={ts_ms} out of realistic ms range [{_TS_MS_MIN}, {_TS_MS_MAX}]"
        )

    ts_ns = int(ts_ms) * 1_000_000  # ms -> ns
    ts_event = pd.Timestamp(ts_ms, unit="ms", tz="UTC")

    # Aliases deja resolus dans sierra_pipeline.py (close/price, bar_high/high, etc.)
    close = sierra_bar.get("close") or sierra_bar.get("price")
    high = sierra_bar.get("bar_high") or sierra_bar.get("high")
    low = sierra_bar.get("bar_low") or sierra_bar.get("low")
    volume = sierra_bar.get("total_vol") or sierra_bar.get("volume")
    open_ = sierra_bar.get("open") or close  # fallback close si open absent

    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "ts_event_ns": ts_ns,
        "ts_event": ts_event,
        "instrument_id": sierra_bar.get("instrument_id", -1),
        "_sierra_bar": sierra_bar,  # passthrough complet pour merge
        "_source": "sierra",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MQ levels adapter (Sierra plats -> dict)
# ═══════════════════════════════════════════════════════════════════════════════

def sierra_bar_to_mq_levels(sierra_bar: dict) -> Optional[dict]:
    """Reconstruit dict mq_levels depuis champs Sierra absolus 3.7.19+.

    Sierra emet les niveaux MQ comme champs plats dans le bar :
    - mq_call, mq_put, mq_hvl (niveaux regular)
    - mq_call_0dte, mq_put_0dte, mq_hvl_0dte (niveaux 0DTE)
    - mq_gex[10], mq_blind[10] (arrays - peuvent etre absents Sierra V1)

    Returns:
        dict | None : None si tous les niveaux sont None (= MQ absent).
    """
    levels = {
        "mq_call": sierra_bar.get("mq_call"),
        "mq_put": sierra_bar.get("mq_put"),
        "mq_hvl": sierra_bar.get("mq_hvl"),
        "mq_call_0dte": sierra_bar.get("mq_call_0dte"),
        "mq_put_0dte": sierra_bar.get("mq_put_0dte"),
        "mq_hvl_0dte": sierra_bar.get("mq_hvl_0dte"),
    }

    # Arrays MQ (optionnels)
    mq_gex = []
    mq_blind = []
    for i in range(10):
        gex_val = sierra_bar.get(f"mq_gex_{i}")
        blind_val = sierra_bar.get(f"mq_blind_{i}")
        if gex_val is not None:
            mq_gex.append(gex_val)
        if blind_val is not None:
            mq_blind.append(blind_val)

    if mq_gex:
        levels["mq_gex"] = mq_gex
    if mq_blind:
        levels["mq_blind"] = mq_blind

    # Si tous None : retourner None (= MQ absent, downstream gere)
    if all(v is None for v in (levels["mq_call"], levels["mq_put"],
                                 levels["mq_hvl"], levels.get("mq_gex"))):
        return None

    return levels


# ═══════════════════════════════════════════════════════════════════════════════
# 3. VIX dict adapter (Sierra plats -> dict)
# ═══════════════════════════════════════════════════════════════════════════════

def sierra_bar_to_vix(sierra_bar: dict) -> Optional[dict]:
    """Reconstruit dict vix depuis champs Sierra plats.

    Sierra emet :
    - vix_level, vix_regime
    - dist_vix_call, dist_vix_put, dist_vix_hvl
    - dist_vix_call_0dte, dist_vix_put_0dte, dist_vix_hvl_0dte

    Returns:
        dict | None : None si vix_level absent.
    """
    vix_level = sierra_bar.get("vix_level")
    if vix_level is None:
        return None

    return {
        "vix_level": vix_level,
        "vix_regime": sierra_bar.get("vix_regime"),
        "dist_vix_call": sierra_bar.get("dist_vix_call"),
        "dist_vix_put": sierra_bar.get("dist_vix_put"),
        "dist_vix_hvl": sierra_bar.get("dist_vix_hvl"),
        "dist_vix_call_0dte": sierra_bar.get("dist_vix_call_0dte"),
        "dist_vix_put_0dte": sierra_bar.get("dist_vix_put_0dte"),
        "dist_vix_hvl_0dte": sierra_bar.get("dist_vix_hvl_0dte"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Composition complete : inputs dict
# ═══════════════════════════════════════════════════════════════════════════════

def sierra_inputs_to_enricher_inputs(
    sierra_bar: dict,
    tick: float,
    trades_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Composition complete : retourne dict 'inputs' attendu par modules streaming.

    Args:
        sierra_bar : dict bar Sierra brut (380+ cols).
        tick : tick size pour symbole.
        trades_df : DataFrame trades optional (Phase 1+ via wrapper VAP).
                    Si None, trades_df vide (modules tolerant).

    Returns:
        dict : {
            'ohlcv': ...,
            'trades_df': pd.DataFrame (vide si VAP absent),
            'mq_levels': ... | None,
            'vix': ... | None,
            'stream_alive': True,  # batch mode = always alive
            'ts_read_ns': ts_event_ns + 60_000_000_000,  # batch +60s
        }
    """
    ohlcv = sierra_bar_to_databento_ohlcv(sierra_bar)
    mq_levels = sierra_bar_to_mq_levels(sierra_bar)
    vix = sierra_bar_to_vix(sierra_bar)

    return {
        "ohlcv": ohlcv,
        "trades_df": trades_df if trades_df is not None else pd.DataFrame(),
        "mq_levels": mq_levels,
        "vix": vix,
        "stream_alive": True,
        "ts_read_ns": ohlcv["ts_event_ns"] + 60_000_000_000,
    }
